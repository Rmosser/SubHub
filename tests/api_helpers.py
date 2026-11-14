from __future__ import annotations

from app.models import ScenarioProfile


class _FakeHttpResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _ProtocolProbeClient:
    def __init__(self, clash_payloads_by_ua: dict[str, str]) -> None:
        self.clash_payloads_by_ua = clash_payloads_by_ua

    async def __aenter__(self) -> "_ProtocolProbeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str, timeout=None, headers=None) -> _FakeHttpResponse:
        ua = str((headers or {}).get("User-Agent", "")).strip()
        if "clash" in str(url):
            return _FakeHttpResponse(self.clash_payloads_by_ua.get(ua, "proxies: []\n"))
        return _FakeHttpResponse("")


def _stub_standard_refresh(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        return {
            "ok": True,
            "pull_method": "clash",
            "pull_node_count": 3,
            "error": "",
            "attempts": [{"method": "clash", "ok": True}],
            "last_success_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)


def _create_standard_source(client) -> str:
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "二维码测试源",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "quality_group": "中等质量",
            "pull_network_mode": "direct_then_proxy",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    return str(created.json()["item"]["id"])


def _create_gorelay_source(client, name: str = "家宽A") -> str:
    created = client.post(
        "/api/sources/gorelay",
        json={
            "name": name,
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    return str(created.json()["item"]["id"])


DEFAULT_SCENARIO_SLUG = "default"


def _scenario_sub_path(token: str, suffix: str, *, flavor: str | None = None) -> str:
    return f"/sub/device/{token}/{DEFAULT_SCENARIO_SLUG}/{suffix}"


def _create_scenario(client, scenario_id: str = "s1", slug: str = "s1", name: str = "Scenario 1") -> ScenarioProfile:
    return client.app.state.services.repo.save_scenario(
        ScenarioProfile(id=scenario_id, slug=slug, name=name)
    )


def _find_capability_view(
    payload: dict[str, object],
    *,
    group_id: str,
    capability_id: str,
    subfield_id: str,
    client: str,
) -> dict[str, object]:
    groups = payload.get("groups", [])
    for group in groups:
        if str(group.get("id")) != group_id:
            continue
        for capability in group.get("capabilities", []):
            if str(capability.get("id")) != capability_id:
                continue
            for subfield in capability.get("subfields", []):
                if str(subfield.get("id")) != subfield_id:
                    continue
                clients = subfield.get("clients", {})
                return dict(clients.get(client, {}))
    raise AssertionError(f"missing capability view for {group_id}.{capability_id}.{subfield_id}.{client}")
