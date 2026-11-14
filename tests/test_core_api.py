from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import Settings
from app.models import (
    CustomRule,
    GoRelayAccount,
    HubRuntime,
    NodeRecord,
    PolicyIR,
    PolicyRuleEntry,
    ServiceCatalogEntry,
    StandardSource,
)
from app.services.core_facade import _normalize_standard_source_payload
from app.storage.sqlite_repo import SqliteRepo


@pytest.mark.parametrize("error_type", [None, RuntimeError, ValueError])
def test_single_gorelay_sync_reports_one_attempt_and_upstream_failure(client, monkeypatch, error_type) -> None:
    services = client.app.state.services
    services.repo.save_gorelay_account(GoRelayAccount(id="sync-account", name="Sync account", login_url="https://example.test"))

    async def crawl(account_id):
        if error_type:
            raise error_type("upstream unavailable")
        return {"ok": True, "account_id": account_id, "node_count": 1}

    monkeypatch.setattr(services.gorelay_service, "crawl_account", crawl)
    response = client.post("/api/core/sync", json={"target": "source", "source_id": "sync-account"})
    failed = error_type is not None
    assert response.status_code == (502 if failed else 200)
    result = response.json()
    assert result["attempted_count"] == 1
    assert result["succeeded_count"] == int(not failed)
    assert result["failed_count"] == int(failed)


def _settings(tmp_path) -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root=str(tmp_path),
        refresh_interval_minutes=30,
        request_timeout_seconds=20,
        verify_tls=True,
        github_api_base="https://127.0.0.1/invalid",
        github_raw_base="https://127.0.0.1/invalid",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )


def _wait_for_hub_startup(client) -> None:
    portal = client.portal
    assert portal is not None
    portal.call(client.app.state.services.hub_service.refresh)


def test_core_state_revision_changes_after_repo_mutation(client) -> None:
    services = client.app.state.services

    first = client.get("/api/core/state")
    assert first.status_code == 200
    first_revision = first.json()["revision"]

    services.repo.save_standard_source(
        StandardSource(
            id="src-1",
            name="Test Source",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
            pull_network_mode="direct_then_proxy",
        )
    )

    second = client.get("/api/core/state")
    assert second.status_code == 200
    assert second.json()["revision"] != first_revision
    assert second.json()["schema"] == "subhub.state.v1"


def test_core_normalize_standard_source_payload_preserves_legacy_airport_mode(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))

    payload = _normalize_standard_source_payload(
        {
            "name": "Legacy Airport",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "quality_group": "高质量机场",
            "enabled": True,
        },
        repo=repo,
    )

    assert payload["source_mode"] == "high_quality_airport"
    assert payload["target_contract_id"] == ""
    assert payload["quality_group"] == "高质量机场"


def test_core_normalize_standard_source_payload_accepts_manual_nodes_ingest(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))

    payload = _normalize_standard_source_payload(
        {
            "name": "Manual Source",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": "trojan://secret@manual.example.com:443?sni=example.com#Manual",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
        repo=repo,
    )

    assert payload["ingest_kind"] == "manual_nodes"
    assert payload["manual_nodes_text"].startswith("trojan://secret")
    assert payload["clash_url"] == ""
    assert payload["pull_network_mode"] == "direct_then_proxy"


def test_core_normalize_standard_source_payload_rejects_explicit_invalid_target_and_mode(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    source = {
        "name": "Invalid Source",
        "clash_url": "https://example.com/clash.yaml",
        "shadowrocket_url": "https://example.com/sr.conf",
        "enabled": True,
    }

    with pytest.raises(ValueError, match="target_contract_id must reference"):
        _normalize_standard_source_payload(
            {**source, "target_contract_id": "not-a-contract"},
            repo=repo,
        )
    with pytest.raises(ValueError, match="source_mode must be one of"):
        _normalize_standard_source_payload(
            {**source, "source_mode": "route_contrct"},
            repo=repo,
        )


def test_core_normalize_standard_source_payload_rejects_omitted_route_target(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))

    with pytest.raises(ValueError, match="target_contract_id must reference"):
        _normalize_standard_source_payload(
            {
                "name": "Unbound Source",
                "clash_url": "https://example.com/clash.yaml",
                "shadowrocket_url": "https://example.com/sr.conf",
                "enabled": True,
            },
            repo=repo,
        )


def test_core_normalize_standard_source_payload_preserves_existing_disabled_target(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    existing = StandardSource(
        id="source-existing",
        name="Existing Source",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="https://example.com/sr.conf",
        target_contract_id="medium",
        source_mode="route_contract",
        enabled=False,
    )
    repo.save_standard_source(existing)
    medium = repo.get_route_contract("medium")
    assert medium is not None
    repo.save_route_contract(replace(medium, enabled=False))

    payload = _normalize_standard_source_payload(
        {
            "id": existing.id,
            "name": "Existing Source Updated",
            "clash_url": "https://example.com/updated.yaml",
            "shadowrocket_url": "https://example.com/updated.conf",
            "enabled": False,
        },
        repo=repo,
        existing_source=existing,
    )

    assert payload["target_contract_id"] == "medium"
    assert payload["source_mode"] == "route_contract"


def test_core_preview_blocks_add_rule_for_missing_category(client) -> None:
    response = client.post(
        "/api/core/preview",
        json={
            "schema": "subhub.patch.v1",
            "actions": [
                {
                    "id": "a1",
                    "type": "add_category_rule",
                    "category": "OpenAI",
                    "rule_type": "DOMAIN-SUFFIX",
                    "value": "openai.com",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["changes"][0]["status"] == "blocked"
    assert payload["blockers"][0]["code"] == "category_not_found"


def test_core_preview_marks_duplicate_category_rule_as_noop(client) -> None:
    services = client.app.state.services
    services.repo.create_manual_rule_category("OpenAI", "", locked=False)
    services.repo.save_custom_rule(
        CustomRule(
            id="rule-1",
            rule_type="DOMAIN-SUFFIX",
            value="openai.com",
            target_group="",
            category_name="OpenAI",
            created_at="2026-03-12T00:00:00Z",
        )
    )

    response = client.post(
        "/api/core/preview",
        json={
            "schema": "subhub.patch.v1",
            "actions": [
                {
                    "id": "a1",
                    "type": "add_category_rule",
                    "category": "OpenAI",
                    "rule_type": "DOMAIN-SUFFIX",
                    "value": "openai.com",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["changes"][0]["status"] == "noop"
    assert payload["blockers"] == []


def test_core_apply_rejects_revision_mismatch(client) -> None:
    response = client.post(
        "/api/core/apply",
        json={
            "schema": "subhub.patch.v1",
            "base_revision": "wrong-revision",
            "actions": [
                {
                    "id": "a1",
                    "type": "set_refresh_policy",
                    "rule_catalog_cache_hours": 24,
                    "cn_cache_hours": 24,
                    "standard_source_auto_pull_enabled": True,
                    "standard_source_auto_pull_interval_minutes": 30,
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["blockers"][0]["code"] == "revision_mismatch"


def test_core_diagnose_source_preserves_attempt_network_path_order(client) -> None:
    services = client.app.state.services
    _wait_for_hub_startup(client)
    modes = {
        "direct_then_proxy": ["direct", "proxy"],
        "direct_only": ["direct"],
        "proxy_then_direct": ["proxy", "direct"],
    }

    for idx, (mode, expected_paths) in enumerate(modes.items(), start=1):
        source_id = f"src-{idx}"
        services.repo.save_standard_source(
            StandardSource(
                id=source_id,
                name=f"Source {idx}",
                clash_url=f"https://example.com/{idx}/clash.yaml",
                shadowrocket_url=f"https://example.com/{idx}/sr.conf",
                surge_url=f"https://example.com/{idx}/surge.conf",
                quality_group="中等质量",
                enabled=True,
                pull_network_mode=mode,
            )
        )
        services.hub_service.runtime.source_status.setdefault("standard", {})[source_id] = {
            "attempts": [{"network_path": path, "ok": False, "method": "clash"} for path in expected_paths]
        }
        response = client.get(f"/api/core/diagnose/source/{source_id}")
        assert response.status_code == 200
        assert [item["network_path"] for item in response.json()["attempts"]] == expected_paths


def test_core_diagnose_egress_reflects_proxy_bridge_payload(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_status(*, gorelay_source_count: int = 0, force: bool = False):
        assert force is True
        return {
            "proxy_bridge": {
                "code": "proxy_bridge_unreachable",
                "severity": "warning",
                "summary": "盒子代理桥接入口不可达。",
                "meaning": "SubHub 无法连接 172.18.0.1:17890。",
                "repair_hint": "运行 check_mihomo_bridge.sh",
                "actions": ["运行自检脚本"],
            }
        }

    monkeypatch.setattr(services.egress_diagnostics, "get_status", _fake_status)

    response = client.get("/api/core/diagnose/egress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "subhub.diagnose.egress.v1"
    assert payload["proxy_bridge"]["code"] == "proxy_bridge_unreachable"
    assert payload["proxy_bridge"]["repair_hint"] == "运行 check_mihomo_bridge.sh"


def test_core_explain_domain_reports_fallback_when_primary_pool_empty(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.create_manual_rule_category("OpenAI", "", locked=False)
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_standard",
            sort_order=0,
            source="manual",
        )
    )
    contract = services.repo.get_route_contract("hq_standard")
    assert contract is not None

    async def _fake_build_policy_ir(token: str):
        assert token == "tok-openai"
        return PolicyIR(
            nodes=[
                NodeRecord(
                    name="hq-premium-node-1",
                    host="1.1.1.1",
                    port=443,
                    protocol="ss",
                    quality_group="高质量-高倍率",
                )
            ],
            pools={"高质量-低倍率": [], "高质量-高倍率": ["hq-premium-node-1"]},
            business_groups=[],
            rule_lines=[],
            default_group_name="中等质量",
            default_contract_id="medium",
            rule_entries=[
                PolicyRuleEntry(
                    target_contract_id="hq_standard",
                    rule_type="DOMAIN-SUFFIX",
                    value="openai.com",
                    category_name="OpenAI",
                )
            ],
            contracts=[contract],
            catalog_bindings=[services.repo.get_service_catalog_entry("OpenAI")],
        )

    monkeypatch.setattr(services.hub_service, "build_policy_ir_for_token", _fake_build_policy_ir)

    response = client.get("/api/core/explain/domain?domain=api.openai.com&device=tok-openai")

    assert response.status_code == 200
    payload = response.json()
    assert payload["match"]["matched"] is True
    assert payload["routing"]["effective_contract_id"] == "hq_standard"
    assert payload["pools"]["renderable_nodes"] == {
        "hq_standard": 0,
        "hq_premium": 1,
        "chain_home": 0,
    }
    assert payload["result"]["selected_pool"] == "hq_premium"
    assert payload["result"]["fallback_used"] is True
    assert payload["result"]["reason"] == "primary pool empty"


def test_core_sync_source_updates_runtime_and_diagnose_sees_latest_attempt(client, monkeypatch) -> None:
    services = client.app.state.services
    _wait_for_hub_startup(client)
    services.repo.save_standard_source(
        StandardSource(
            id="src-sync",
            name="Sync Source",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
            pull_network_mode="direct_then_proxy",
        )
    )

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        services.hub_service.runtime.source_status.setdefault("standard", {})[source_id] = {
            "attempts": [
                {"network_path": "direct", "ok": False, "method": "clash"},
                {"network_path": "proxy", "ok": True, "method": "clash"},
            ]
        }
        return {
            "source_id": source_id,
            "ok": True,
            "attempts": [
                {"network_path": "direct", "ok": False, "method": "clash"},
                {"network_path": "proxy", "ok": True, "method": "clash"},
            ],
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    synced = client.post("/api/core/sync", json={"target": "source", "source_id": "src-sync"})
    assert synced.status_code == 200
    assert synced.json()["ok"] is True

    diagnosed = client.get("/api/core/diagnose/source/src-sync")
    assert diagnosed.status_code == 200
    assert [item["network_path"] for item in diagnosed.json()["attempts"]] == ["direct", "proxy"]


def test_core_sync_all_propagates_nested_refresh_failure(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh(*, force: bool = False, rule_catalog_mode: str = "incremental"):
        assert force is True
        return HubRuntime(
            source_status={
                "rule_catalog": {"ok": False, "error": "catalog unavailable"},
                "standard": {},
                "gorelay": {"ok": True, "accounts": {}},
            }
        )

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    response = client.post("/api/core/sync", json={"target": "all"})

    assert response.status_code == 502
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["failed_count"] == 1
    assert payload["item"]["source_status"]["rule_catalog"]["error"] == "catalog unavailable"


def test_management_refresh_propagates_nested_refresh_failure(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh(*, force: bool = False, force_rule_catalog: bool = False, rule_catalog_mode: str = "incremental"):
        assert force is True
        return HubRuntime(
            source_status={
                "rule_catalog": {"ok": False, "error": "catalog unavailable"},
                "standard": {},
                "gorelay": {"ok": True, "accounts": {}},
            }
        )

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    response = client.post("/api/refresh")

    assert response.status_code == 502
    assert response.json()["ok"] is False
