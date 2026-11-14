from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

from app.config import Settings
from app.models import GoRelayAccount, StandardSource
from app.services.tenant_registry import TenantRegistry
from app.services.subscription_ids import sign_subscription_asset, verify_subscription_asset_signature


def test_management_and_public_subscription_resolve_separate_owners(client) -> None:
    registry = client.app.state.tenant_registry
    alice = registry.for_user("test-user")
    alice_id = alice.repo.list_device_subscriptions()[0].public_id
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "Alice Airport", "ingest_kind": "manual_nodes", "target_contract_id": "medium",
            "manual_nodes_text": "trojan://alice-password@alice.example:443#Alice",
        },
    )
    assert created.status_code == 200, created.text
    source_id = created.json()["item"]["id"]
    bob_headers = {"X-HC-User-ID": "bob"}
    assert client.get("/api/devices", headers=bob_headers).status_code == 409
    initialized = client.post("/api/setup/init", headers=bob_headers)
    assert initialized.status_code == 200
    bob = registry.for_user("bob")
    assert bob.repo.list_standard_sources() == []
    assert client.get("/api/sources/standard", headers=bob_headers).json()["items"] == []
    assert client.post(f"/api/sources/standard/{source_id}/pull", headers=bob_headers).status_code == 404
    assert client.get(f"/api/devices/{alice_id}/preview-summary?target=clash", headers=bob_headers).status_code == 404
    bob_id = initialized.json()["device_public_id"]
    assert alice_id != bob_id
    for services in (alice, bob):
        services.hub_service.runtime.last_refresh_at = datetime.now(timezone.utc).isoformat()
    downloaded = client.get(f"/sub/device/{alice_id}/shadowrocket-nodes.txt", headers={"X-HC-User-ID": ""})
    assert downloaded.status_code == 200
    assert client.get(f"/sub/device/{bob_id}/shadowrocket-nodes.txt", headers={"X-HC-User-ID": ""}).status_code == 200
    assert registry.for_subscription(alice_id) is alice
    assert registry.for_subscription(bob_id) is bob
    assert registry.for_subscription("unknown-public-id") is None


def test_registry_persists_user_storage_keys_and_tokens_across_restart(tmp_path) -> None:
    from app.main import build_services

    settings = replace(Settings.from_env(), storage_root=str(tmp_path), manage_api_require_login=True)
    baseline = build_services(replace(settings))
    registry = TenantRegistry(settings, build_services, baseline)
    alice = registry.initialize("alice/../unsafe")
    bob = registry.initialize("bob")
    alice.repo.save_standard_source(StandardSource(id="source", name="Private source", target_contract_id="medium"))
    alice_token = alice.repo.list_device_subscriptions()[0].token
    alice_key = alice.settings.field_cipher_key_path.read_bytes()
    assert alice.repo.db_path != bob.repo.db_path
    assert alice.settings.field_cipher_key_path != bob.settings.field_cipher_key_path
    assert alice.policy_backup.backend.local_root != bob.policy_backup.backend.local_root
    assert alice.settings.policy_backup_subdir != bob.settings.policy_backup_subdir
    assert alice.settings.url_signing_secret != bob.settings.url_signing_secret
    assert alice.repo.db_path.is_relative_to(tmp_path / "tenants")
    assert registry.initialize("alice/../unsafe") is alice
    restart = TenantRegistry(replace(settings), build_services, build_services(replace(settings)))
    restored = restart.for_subscription(alice_token)
    assert restored is not None
    assert restored.repo.get_standard_source("source").name == "Private source"
    assert restored.settings.field_cipher_key_path.read_bytes() == alice_key
    assert restored.settings.url_signing_secret == alice.settings.url_signing_secret
    assert restart.for_user("bob").repo.get_standard_source("source") is None
    assert len(restart._records()) == 2
    assert restart.for_subscription("random") is None
    assert len(restart._records()) == 2
    with pytest.raises(HTTPException) as exc:
        restart.for_user("unknown")
    assert exc.value.status_code == 409


def test_legacy_storage_requires_explicit_owner_and_cannot_be_reassigned(tmp_path) -> None:
    from app.main import build_services

    settings = replace(Settings.from_env(), storage_root=str(tmp_path), manage_api_require_login=True,
                       policy_backup_subdir="existing-policy")
    baseline = build_services(replace(settings))
    baseline.hub_service._ensure_default_device_subscription()
    old_signature_args = dict(public_id="old-id", scenario_slug="default", kind="clash-provider", asset_key="medium", revision="before", expires_at=9999999999)
    old_signature = sign_subscription_asset(baseline.settings, **old_signature_args)
    token = baseline.repo.list_device_subscriptions()[0].token
    baseline.repo.save_standard_source(StandardSource(id="legacy", name="Existing data", target_contract_id="medium"))
    registry = TenantRegistry(settings, build_services, baseline)
    assert registry.for_subscription(token) is None
    outsider = registry.initialize("first-login")
    assert outsider.repo.get_standard_source("legacy") is None
    claimed_settings = replace(settings, legacy_data_owner_id="operator-selected-owner")
    claimed = TenantRegistry(claimed_settings, build_services, baseline)
    owner = claimed.for_user("operator-selected-owner")
    assert owner is baseline
    assert claimed.for_subscription(token) is owner
    assert owner.settings.policy_backup_subdir == "existing-policy"
    assert verify_subscription_asset_signature(owner.settings, signature=old_signature, **old_signature_args)
    assert owner.repo.get_standard_source("legacy").name == "Existing data"
    with pytest.raises(ValueError, match="cannot reassign"):
        TenantRegistry(replace(settings, legacy_data_owner_id="different-owner"), build_services, baseline)


def test_health_is_public_and_omits_tenant_state(client) -> None:
    health = client.get("/healthz", headers={"X-HC-User-ID": ""})
    assert health.status_code == 200
    payload = health.json()
    assert payload["setup_required"] is False
    assert payload["access_mode"] == "per-user"
    assert "hub" not in payload
    assert "egress" not in payload
    assert client.get("/diagnostics", headers={"X-HC-User-ID": ""}).status_code == 401
    assert client.get("/readyz", headers={"X-HC-User-ID": ""}).status_code == 401
    assert client.get("/metrics", headers={"X-HC-User-ID": ""}).status_code == 401


def test_unavailable_user_does_not_block_other_users_and_can_recover(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("MANAGE_API_REQUIRE_LOGIN", "true")
    monkeypatch.setenv("GITHUB_API_BASE", "https://127.0.0.1/invalid")
    monkeypatch.setenv("GITHUB_RAW_BASE", "https://127.0.0.1/invalid")
    monkeypatch.delenv("LEGACY_DATA_OWNER_ID", raising=False)
    import app.main

    main = importlib.reload(app.main)
    with TestClient(main.app) as http:
        alice_token = http.post("/api/setup/init", headers={"X-HC-User-ID": "alice"}).json()["device_token"]
        bob_token = http.post("/api/setup/init", headers={"X-HC-User-ID": "bob"}).json()["device_token"]
        alice = main.app.state.tenant_registry.for_user("alice")
        alice.repo.save_gorelay_account(GoRelayAccount(id="account", name="Encrypted", login_url="https://example.test", gorelay_password="must-stay-private", enabled=False))
        original_key = alice.settings.field_cipher_key_path.read_bytes()
        key_path = alice.settings.field_cipher_key_path
    key_path.write_bytes(Fernet.generate_key())
    # Unassigned legacy data must never be constructed in production mode.
    (tmp_path / "data" / "field_cipher.key").write_bytes(b"invalid unclaimed root key")
    (tmp_path / "data" / "subhub.db").write_bytes(b"unclaimed corrupt root database")
    restarted = importlib.reload(main)
    with TestClient(restarted.app) as http:
        assert http.get("/api/devices", headers={"X-HC-User-ID": "bob"}).status_code == 200
        assert http.get(f"/sub/device/{bob_token}/shadowrocket.conf").status_code == 200
        blocked = http.get("/api/devices", headers={"X-HC-User-ID": "alice"})
        assert blocked.status_code == 503
        assert "field_cipher.key" in blocked.json()["detail"]
        assert "must-stay-private" not in blocked.text
        assert http.get(f"/sub/device/{alice_token}/shadowrocket.conf").status_code == 503
        assert http.get("/api/setup/status", headers={"X-HC-User-ID": "alice"}).json()["storage_status"] == "unavailable"
        key_path.write_bytes(original_key)
        assert http.get("/api/devices", headers={"X-HC-User-ID": "alice"}).status_code == 200
        assert http.get("/api/setup/status", headers={"X-HC-User-ID": "alice"}).json()["storage_status"] == "ready"
        assert http.get(f"/sub/device/{alice_token}/shadowrocket.conf").status_code == 200


@pytest.mark.parametrize("legacy,canonical", [
    ("clash.yaml", "clash.yaml"),
    ("shadowrocket.conf", "shadowrocket.conf"),
])
def test_legacy_query_subscription_alias_uses_canonical_renderer(client, legacy, canonical) -> None:
    services = client.app.state.services
    services.hub_service.runtime.last_refresh_at = datetime.now(timezone.utc).isoformat()
    device = services.repo.list_device_subscriptions()[0]
    alias = client.get(f"/sub/{legacy}?token={device.token}")
    current = client.get(f"/sub/device/{device.token}/{canonical}")
    assert alias.status_code == current.status_code
    assert alias.content == current.content
    assert client.get(f"/sub/{legacy}?token={device.token}&profile=raw").status_code == 400
    assert client.get(f"/sub/{legacy}?token=invalid").status_code == 403


def test_local_mode_explicitly_shares_one_workspace(tmp_path) -> None:
    from app.main import build_services

    settings = replace(Settings.from_env(), storage_root=str(tmp_path), manage_api_require_login=False)
    baseline = build_services(replace(settings))
    registry = TenantRegistry(settings, build_services, baseline)
    assert registry.for_user("alice") is registry.for_user("bob") is baseline
    assert registry.status("alice")["access_mode"] == "single-user"
    assert registry.status("")["setup_required"] is False
    asyncio.run(registry.shutdown())


def test_source_pull_warnings_survive_restart_and_clear_after_success_and_delete(tmp_path, monkeypatch) -> None:
    from app.services.hub_service import HubService
    from app.storage.base import standard_source_diagnostics_key

    # Disable scheduled collection so only persisted evidence can satisfy restart assertions.
    async def no_background_collection(self):
        pass

    monkeypatch.setattr(HubService, "ensure_started", no_background_collection)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("MANAGE_API_REQUIRE_LOGIN", "true")
    monkeypatch.delenv("LEGACY_DATA_OWNER_ID", raising=False)
    import app.main

    headers = {"X-HC-User-ID": "alice"}
    main = importlib.reload(app.main)
    with TestClient(main.app, headers=headers) as http:
        assert http.post("/api/setup/init").status_code == 200
        created = http.post("/api/sources/standard", json={
            "name": "Mixed import", "ingest_kind": "manual_nodes", "enabled": True,
            "target_contract_id": "medium",
            "manual_nodes_text": "trojan://private-good@good.example:443#Good\ntrojan://private-bad@bad.example:bad#Bad",
        })
        assert created.status_code == 200
        source_id = created.json()["item"]["id"]
        assert created.json()["pull_result"]["ok"] is True

    main = importlib.reload(main)
    with TestClient(main.app, headers=headers) as http:
        services = main.app.state.tenant_registry.for_user("alice")
        assert not services.hub_service.runtime.source_status
        item = next(item for item in http.get("/api/sources/standard").json()["items"] if item["id"] == source_id)
        assert item["pull_warning_count"] == 1
        assert item["pull_warnings"][0]["code"] == "source-parse-rejected"
        assert "private-bad" not in str(item["pull_warnings"])
        source = services.repo.get_standard_source(source_id)
        source.manual_nodes_text = "trojan://private-bad@bad.example:bad#Bad"
        services.repo.save_standard_source(source)
        failed = http.post(f"/api/sources/standard/{source_id}/pull")
        assert failed.status_code == 200
        assert failed.json()["pull_result"]["ok"] is False

    main = importlib.reload(main)
    with TestClient(main.app, headers=headers) as http:
        services = main.app.state.tenant_registry.for_user("alice")
        item = next(item for item in http.get("/api/sources/standard").json()["items"] if item["id"] == source_id)
        assert item["last_pull_ok"] is False
        assert item["pull_warnings"][0]["code"] == "source-parse-rejected"
        source = services.repo.get_standard_source(source_id)
        source.manual_nodes_text = "trojan://private-good@good.example:443#Good"
        services.repo.save_standard_source(source)
        assert http.post(f"/api/sources/standard/{source_id}/pull").status_code == 200
        item = next(item for item in http.get("/api/sources/standard").json()["items"] if item["id"] == source_id)
        assert item["pull_warnings"] == []
        assert services.repo.get_runtime_setting(standard_source_diagnostics_key(source_id))["warnings"] == []
        assert http.delete(f"/api/sources/standard/{source_id}").status_code == 200
        assert services.repo.get_runtime_setting(standard_source_diagnostics_key(source_id)) is None
