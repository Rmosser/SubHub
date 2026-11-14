from __future__ import annotations

import asyncio

from app.config import Settings
from app.services.egress_diagnostics import EgressDiagnostics


def _settings() -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root="./var",
        refresh_interval_minutes=30,
        request_timeout_seconds=20,
        verify_tls=True,
        github_api_base="https://api.github.com/repos/blackmatrix7/ios_rule_script",
        github_raw_base="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )


def test_egress_diagnostics_missing_proxy_env_warns_when_gorelay_required(monkeypatch) -> None:
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    diagnostics = EgressDiagnostics(_settings(), cache_ttl_seconds=1)

    payload = asyncio.run(diagnostics.get_status(gorelay_source_count=1))
    proxy_bridge = payload["proxy_bridge"]

    assert proxy_bridge["code"] == "missing_proxy_env"
    assert proxy_bridge["severity"] == "warning"
    assert "GoRelay" in str(proxy_bridge["meaning"])
    assert proxy_bridge["actions"]


def test_egress_diagnostics_bridge_unreachable_has_repair_hint(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://172.18.0.1:17890")
    diagnostics = EgressDiagnostics(_settings(), cache_ttl_seconds=1)

    async def _fake_tcp_probe(host: str, port: int, timeout: float):
        return False, "connection refused"

    monkeypatch.setattr(diagnostics, "_tcp_probe", _fake_tcp_probe)

    payload = asyncio.run(diagnostics.get_status(gorelay_source_count=2, force=True))
    proxy_bridge = payload["proxy_bridge"]

    assert proxy_bridge["code"] == "proxy_bridge_unreachable"
    assert proxy_bridge["severity"] == "warning"
    assert "check_mihomo_bridge.sh" in str(proxy_bridge["repair_hint"])
    assert len(proxy_bridge["actions"]) >= 2


def test_egress_diagnostics_ok_reports_meaning(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://172.18.0.1:17890")
    diagnostics = EgressDiagnostics(_settings(), cache_ttl_seconds=1)

    async def _fake_tcp_probe(host: str, port: int, timeout: float):
        return True, ""

    async def _fake_proxy_probe(proxy_url: str, *, timeout: float, probe_url: str):
        return True, 401, ""

    monkeypatch.setattr(diagnostics, "_tcp_probe", _fake_tcp_probe)
    monkeypatch.setattr(diagnostics, "_proxy_http_probe", _fake_proxy_probe)

    payload = asyncio.run(diagnostics.get_status(gorelay_source_count=1, force=True))
    proxy_bridge = payload["proxy_bridge"]

    assert proxy_bridge["code"] == "ok"
    assert proxy_bridge["severity"] == "info"
    assert "HTTPS 代理探测" in str(proxy_bridge["meaning"])
    assert proxy_bridge["proxy_probe_status_code"] == 401
