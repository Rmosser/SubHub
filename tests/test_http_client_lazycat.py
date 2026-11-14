from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any

import pytest

from app.config import Settings
from app.models import (
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    QUALITY_MEDIUM,
    StandardSource,
)
from app.services.http_client import build_async_http_client
from app.services.source_fetcher import SourceFetcher


def _settings() -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root="./var",
        refresh_interval_minutes=30,
        request_timeout_seconds=3,
        verify_tls=True,
        github_api_base="https://api.github.com/repos/blackmatrix7/ios_rule_script",
        github_raw_base="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )


class _ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


@dataclass
class _ServerHits:
    dest: int = 0
    proxy: int = 0


@dataclass
class _ServerState:
    hits: _ServerHits
    payload: str


class _DestHandler(BaseHTTPRequestHandler):
    server: "_TestHttpServer"

    def do_GET(self) -> None:  # noqa: N802
        self.server.state.hits.dest += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"dest-ok")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class _ProxyHandler(BaseHTTPRequestHandler):
    server: "_TestHttpServer"

    def do_GET(self) -> None:  # noqa: N802
        self.server.state.hits.proxy += 1
        self.send_response(200)
        self.end_headers()
        body = (
            self.server.state.payload
            if "clash" in self.path
            else self.path
        )
        self.wfile.write(body.encode("utf-8"))

    def do_CONNECT(self) -> None:  # noqa: N802
        self.server.state.hits.proxy += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class _TestHttpServer(_ThreadingServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], state: _ServerState):
        super().__init__(address, handler)
        self.state = state


@pytest.fixture
def http_servers():
    state = _ServerState(
        hits=_ServerHits(),
        payload=(
            "proxies:\n"
            "  - name: n1\n"
            "    server: n1.example.com\n"
            "    port: 443\n"
            "    type: trojan\n"
            "    password: p1\n"
        ),
    )
    dest = _TestHttpServer(("127.0.0.1", 0), _DestHandler, state)
    proxy = _TestHttpServer(("127.0.0.1", 0), _ProxyHandler, state)
    threads = [
        threading.Thread(target=dest.serve_forever, daemon=True),
        threading.Thread(target=proxy.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        yield {
            "state": state,
            "dest_url": f"http://127.0.0.1:{dest.server_port}/hello",
            "proxy_url": f"http://127.0.0.1:{proxy.server_port}",
            "missing_dest_url": "http://127.0.0.1:1/clash.yaml",
        }
    finally:
        dest.shutdown()
        proxy.shutdown()
        dest.server_close()
        proxy.server_close()


def _apply_proxy_env(monkeypatch: pytest.MonkeyPatch, proxy_url: str, *, lazycat_runtime: bool) -> None:
    monkeypatch.setenv("HTTP_PROXY", proxy_url)
    monkeypatch.setenv("HTTPS_PROXY", proxy_url)
    monkeypatch.setenv("http_proxy", proxy_url)
    monkeypatch.setenv("https_proxy", proxy_url)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    if lazycat_runtime:
        monkeypatch.setenv("LAZYCAT_APP_ID", "test-app")
    else:
        monkeypatch.delenv("LAZYCAT_APP_ID", raising=False)
    monkeypatch.delenv("LZCAPP_API_GATEWAY_ADDRESS", raising=False)
    monkeypatch.delenv("LAZYCAT_BOX_DOMAIN", raising=False)


async def _fetch_text(url: str, *, trust_env: bool) -> str:
    async with build_async_http_client(_settings(), trust_env=trust_env) as client:
        response = await client.get(url, timeout=3)
        return response.text


@pytest.mark.parametrize("lazycat_runtime", [False, True])
def test_build_async_http_client_separates_direct_and_proxy_paths(
    monkeypatch: pytest.MonkeyPatch,
    http_servers,
    lazycat_runtime: bool,
) -> None:
    _apply_proxy_env(monkeypatch, http_servers["proxy_url"], lazycat_runtime=lazycat_runtime)
    state = http_servers["state"]

    state.hits.dest = 0
    state.hits.proxy = 0
    direct_body = asyncio.run(_fetch_text(http_servers["dest_url"], trust_env=False))
    assert direct_body == "dest-ok"
    assert state.hits.dest == 1
    assert state.hits.proxy == 0

    state.hits.dest = 0
    state.hits.proxy = 0
    proxy_body = asyncio.run(_fetch_text(http_servers["dest_url"], trust_env=True))
    assert proxy_body == http_servers["dest_url"]
    assert state.hits.dest == 0
    assert state.hits.proxy == 1


def test_source_fetcher_direct_then_proxy_falls_back_to_proxy_in_lazycat_runtime(
    monkeypatch: pytest.MonkeyPatch,
    http_servers,
) -> None:
    _apply_proxy_env(monkeypatch, http_servers["proxy_url"], lazycat_runtime=True)
    state = http_servers["state"]
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url=http_servers["missing_dest_url"],
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
        pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    )

    state.hits.dest = 0
    state.hits.proxy = 0
    result = asyncio.run(fetcher.fetch_source(source))

    assert result.ok is True
    assert result.method == "clash"
    assert result.node_count == 1
    assert any(item.network_path == "direct" and item.ok is False for item in result.attempts)
    assert any(item.network_path == "proxy" and item.ok is True for item in result.attempts)
    assert state.hits.proxy >= 1


def test_source_fetcher_direct_only_never_uses_proxy_in_lazycat_runtime(
    monkeypatch: pytest.MonkeyPatch,
    http_servers,
) -> None:
    _apply_proxy_env(monkeypatch, http_servers["proxy_url"], lazycat_runtime=True)
    state = http_servers["state"]
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url=http_servers["missing_dest_url"],
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
        pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    )

    state.hits.dest = 0
    state.hits.proxy = 0
    result = asyncio.run(fetcher.fetch_source(source))

    assert result.ok is False
    assert not any(item.network_path == "proxy" for item in result.attempts)
    assert state.hits.proxy == 0
