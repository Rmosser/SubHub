from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "var"))
    monkeypatch.setenv("APP_BASE_URL", "http://testserver")
    monkeypatch.setenv("MANAGE_API_REQUIRE_LOGIN", "true")
    monkeypatch.setenv("GITHUB_API_BASE", "https://127.0.0.1/invalid")
    monkeypatch.setenv("GITHUB_RAW_BASE", "https://127.0.0.1/invalid")
    monkeypatch.delenv("LEGACY_DATA_OWNER_ID", raising=False)
    import app.main

    return importlib.reload(app.main)


def _headers(user: str) -> dict[str, str]:
    return {"X-HC-User-ID": user}


def test_fresh_instance_requires_setup_without_exposing_tenant_data(setup_app) -> None:
    with TestClient(setup_app.app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["setup_required"] is True
        assert client.get("/manage").status_code == 200
        assert client.get("/sub/device/unknown/shadowrocket.conf").status_code == 503
        assert client.get("/rules/ai.list?token=unknown").status_code == 503
        assert client.get("/api/setup/status").status_code == 401
        assert client.post("/api/setup/init").status_code == 401
        assert client.get("/setup").status_code == 401
        response = client.get("/api/sources/standard", headers=_headers("alice"))
        assert response.status_code == 409
        status = client.get("/api/setup/status", headers=_headers("alice")).json()
        assert status["setup_required"] is True
        assert status["initialized"] is False
        assert status["instance_initialized"] is False
        assert "device_token" not in status
        page = client.get("/setup", headers=_headers("alice"))
        assert page.status_code == 200
        assert '/api/setup/init' in page.text


def test_setup_is_idempotent_and_current_user_only(setup_app) -> None:
    with TestClient(setup_app.app) as client:
        initialized = client.post("/api/setup/init", headers=_headers("alice"))
        assert initialized.status_code == 200
        token = initialized.json()["device_token"]
        public_id = initialized.json()["device_public_id"]
        assert token
        assert initialized.json()["device_public_id"]
        again = client.post("/api/setup/init", headers=_headers("alice"))
        assert again.json()["device_token"] == token
        assert client.get("/setup", headers=_headers("alice"), follow_redirects=False).status_code == 302
        bob_status = client.get("/api/setup/status", headers=_headers("bob")).json()
        assert bob_status["setup_required"] is True
        assert bob_status["instance_initialized"] is True
        assert token not in str(bob_status)
        assert client.get("/api/devices", headers=_headers("bob")).status_code == 409
        bob = client.post("/api/setup/init", headers=_headers("bob"))
        assert bob.status_code == 200
        assert bob.json()["device_token"] != token
        alice_devices = client.get("/api/devices", headers=_headers("alice")).json()
        bob_devices = client.get("/api/devices", headers=_headers("bob")).json()
        assert public_id in str(alice_devices)
        assert public_id not in str(bob_devices)
        assert client.get(f"/api/devices/{token}/preview-content?target=shadowrocket", headers=_headers("bob")).status_code == 404
        assert client.get("/sub/device/unknown/shadowrocket.conf").status_code in {403, 404}


def test_initialized_source_and_subscription_survive_restart(setup_app) -> None:
    with TestClient(setup_app.app) as client:
        token = client.post("/api/setup/init", headers=_headers("alice")).json()["device_token"]
        created = client.post(
            "/api/sources/standard",
            headers=_headers("alice"),
            json={
                "name": "Restart source",
                "ingest_kind": "manual_nodes",
                "manual_nodes_text": "trojan://synthetic-secret@restart.example.com:443?sni=example.com#Restart",
                "target_contract_id": "medium",
                "enabled": True,
            },
        )
        assert created.status_code == 200
        source_id = created.json()["item"]["id"]
        assert created.json()["pull_result"]["ok"] is True
        subscription = client.get(f"/sub/device/{token}/shadowrocket.conf")
        assert subscription.status_code == 200
        assert "restart.example.com" in subscription.text
        assert "synthetic-secret" in subscription.text
    restarted = importlib.reload(setup_app)
    with TestClient(restarted.app) as client:
        status = client.get("/api/setup/status", headers=_headers("alice")).json()
        assert status["initialized"] is True
        sources = client.get("/api/sources/standard", headers=_headers("alice")).json()
        assert source_id in str(sources)
        subscription = client.get(f"/sub/device/{token}/shadowrocket.conf")
        assert subscription.status_code == 200
        assert "restart.example.com" in subscription.text
        assert "synthetic-secret" in subscription.text
        assert client.get("/api/sources/standard", headers=_headers("bob")).status_code == 409
