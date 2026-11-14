from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote

import pytest

from app.models import (
    CollectedRule,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    GoRelayDeviceSubscription,
    GoRelayDomainBinding,
    NodeRecord,
    ScenarioProfile,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    StandardSource,
    StandardSourceWarning,
)
from tests.api_helpers import (
    _create_gorelay_source,
    _create_standard_source,
    _scenario_sub_path,
    _stub_standard_refresh,
)


@pytest.fixture
def diagnostic_client(monkeypatch, request):
    from app.services.tenant_registry import TenantRegistry

    async def no_background_workers(*_args, **_kwargs):
        pass

    # This new fixture freezes historical runtime before injection. Existing
    # fixtures/lifecycle tests keep their original behavior (B11).
    monkeypatch.setattr(TenantRegistry, "ensure_started", no_background_workers)
    client = request.getfixturevalue("client")

    async def healthy_egress(*_args, **_kwargs):
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(client.app.state.services.egress_diagnostics, "get_status", healthy_egress)
    return client


def test_known_secrets_tenant_history_update_delete_and_all_projections(diagnostic_client, monkeypatch) -> None:
    client = diagnostic_client
    services = client.app.state.services
    registry = client.app.state.tenant_registry
    other = registry.initialize("known-secret-other")

    async def healthy(*_args, **_kwargs):
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(other.egress_diagnostics, "get_status", healthy)
    # Word-shaped query values intentionally survive the heuristic on their
    # own, so these assertions distinguish tenant-configured replacement.
    source_id = "configured-history"
    raw = "clash: HTTP 404 orchard lantern"
    for tenant, secret in [(services, "orchard"), (other, "lantern")]:
        tenant.repo.save_standard_source(StandardSource(
            id=source_id, name="History", enabled=False, clash_url=f"https://h/sub?token={secret}",
        ))
        tenant.repo.save_standard_source_pull_status(
            source_id, attempt_at="2026-01-01T00:00:00Z", ok=False, method="", node_count=0,
            error=raw, trigger="manual",
        )
        tenant.hub_service.runtime.last_error = raw
        tenant.hub_service.runtime.source_status = {
            "aggregate": {"ok": False, "errors": [raw]},
            "standard": {source_id: {"error": raw, "attempts": [
                {"url": "orchard lantern", "error": raw, "skip_reasons": [raw]},
            ]}, "deleted-history": {"error": raw}},
        }
    originals = [deepcopy(s.hub_service.runtime.to_dict()) for s in (services, other)]
    db_before = [tuple(s.repo._conn.execute("SELECT * FROM standard_sources WHERE id=?", (source_id,)).fetchone())
                 for s in (services, other)]
    paths = ["/api/status", "/diagnostics", f"/api/core/diagnose/source/{source_id}"]

    def read(task):
        path, user, hidden, preserved = task
        response = client.get(path, headers={"X-HC-User-ID": user})
        assert response.status_code == 200
        text = response.text.casefold()
        assert hidden not in text and preserved in text
        return response.json()

    tasks = [(p, user, hidden, preserved) for p in paths for user, hidden, preserved in [
        ("test-user", "orchard", "lantern"), ("known-secret-other", "lantern", "orchard"),
    ]]
    first = [read(task) for task in tasks]
    second = [read(task) for task in tasks]
    with ThreadPoolExecutor(max_workers=6) as pool:
        concurrent = list(pool.map(read, tasks))
    for index in (4, 5):
        assert first[index] == second[index] == concurrent[index]

    async def existing_runtime(**_kwargs):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", existing_runtime)
    for endpoint, payload in [("/api/refresh", {}), ("/api/core/sync", {"target": "all"})]:
        response = client.post(endpoint, json=payload)
        assert response.status_code == 502
        assert "orchard" not in response.text.casefold() and "lantern" in response.text.casefold()
    # Configuration remains editable and literal; only diagnostic fields clean.
    listing = client.get("/api/sources/standard").json()["items"][0]
    state = client.get("/api/core/state").json()["sources"]["standard"][0]
    for item in (listing, state):
        assert item["clash_url"] == "https://h/sub?token=orchard"
        assert item["last_pull_error"] == "clash: HTTP 404 <redacted> lantern"
    for i, tenant in enumerate((services, other)):
        assert tenant.hub_service.runtime.to_dict() == originals[i]
        assert tuple(tenant.repo._conn.execute("SELECT * FROM standard_sources WHERE id=?", (source_id,)).fetchone()) == db_before[i]

    # Recompile from current configuration at every read, with no stale cache.
    updated = services.repo.get_standard_source(source_id)
    updated.clash_url = "https://h/sub?token=lantern"
    services.repo.save_standard_source(updated)
    read(("/api/status", "test-user", "lantern", "orchard"))
    services.repo.delete_standard_source(source_id)
    status = client.get("/api/status")
    assert "orchard" in status.text and "lantern" in status.text
    assert services.hub_service.runtime.to_dict() == originals[0]


def _without_config_urls(value: object) -> str:
    """Response JSON without editable source URL fields (they are not diagnostics)."""
    def strip(item: object) -> object:
        if isinstance(item, dict):
            return {key: strip(child) for key, child in item.items()
                    if key not in {"clash_url", "surge_url", "shadowrocket_url"}}
        return [strip(child) for child in item] if isinstance(item, list) else item
    return json.dumps(strip(value))


def test_known_secret_matcher_built_once_per_request(diagnostic_client, monkeypatch) -> None:
    from app.services import source_diagnostics

    client = diagnostic_client
    services = client.app.state.services
    tokens = [f"t0ken{index}AbCdEf123456" for index in range(6)]
    for index, token in enumerate(tokens):
        services.repo.save_standard_source(StandardSource(
            id=f"count-{index}", name=f"Count {index}", enabled=False, clash_url=f"https://h/sub?token={token}",
        ))
        services.repo.save_standard_source_pull_status(
            f"count-{index}", attempt_at="2026-01-01T00:00:00Z", ok=False, method="", node_count=0,
            error=f"clash: HTTP 404 {token}", trigger="manual",
        )
    # Each matcher build extracts every configured source once.
    extracted: list[int] = []
    original_extract = source_diagnostics.extract_source_secrets
    monkeypatch.setattr(source_diagnostics, "extract_source_secrets",
                        lambda *urls: extracted.append(1) or original_extract(*urls))
    # One build per request, for the list too (it used to build once per row).
    for path in ["/api/sources/standard", "/api/core/state", "/api/status", "/diagnostics",
                 "/api/core/diagnose/source/count-0"]:
        extracted.clear()
        response = client.get(path)
        assert response.status_code == 200, path
        assert "t0ken0abcdef123456" not in _without_config_urls(response.json()).casefold(), path
        assert len(extracted) == len(tokens), path
    items = client.get("/api/sources/standard").json()["items"]
    assert sorted(item["last_pull_error"] for item in items) == ["clash: HTTP 404 <redacted>"] * 6


class _ClashProtocolServer:
    """Real HTTP upstream: /<label> serves one Clash proxy whose type is that case's raw name; /fail is 404."""

    def __init__(self, protocols: dict[str, str]) -> None:
        protocols_by_label = protocols

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                label = self.path.split("?", 1)[0].strip("/")
                if label in protocols_by_label:
                    body = json.dumps({"proxies": [{"name": "Probe", "server": "192.0.2.1", "port": 443,
                                                    "type": protocols_by_label[label]}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/yaml")
                else:
                    body = b""
                    self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.worker = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.worker.join()
        self.server.server_close()


# (configured query value as written in the URL, protocol name the upstream sends, fragments that must not survive)
_PROTOCOL_CASES = {
    "plus": ("orchard+lantern", "orchard+lantern", ["orchard", "lantern"]),
    "marker": ("%3Credacted%3Etail", "<redacted>tail", [">tail"]),
    "truncated": ("1234567890" * 9, "1234567890" * 9, ["1234567890"]),
    "preclean": ("orchardpassword%3Dx%3Blantern", "orchardpassword=x;lantern", ["orchard", "lantern"]),
}


@pytest.mark.parametrize("case", sorted(_PROTOCOL_CASES))
def test_real_http_configured_protocol_names_are_hidden_whole(diagnostic_client, monkeypatch, case) -> None:
    # Real Clash JSON -> fetcher -> Hub -> SQLite -> API. The protocol name is
    # this source's configured value; it must become one marker everywhere.
    client = diagnostic_client
    registry = client.app.state.tenant_registry
    written, protocol, fragments = _PROTOCOL_CASES[case]
    user = f"protocol-{case}"
    services = registry.initialize(user)

    async def healthy(*_args, **_kwargs):
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(services.egress_diagnostics, "get_status", healthy)
    headers = {"X-HC-User-ID": user, "X-HC-User-Role": "owner"}

    def assert_clean(text: str) -> None:
        for fragment in fragments:
            assert fragment not in text and fragment not in unquote(text), (case, fragment)

    with _ClashProtocolServer({case: protocol}) as upstream:
        services.repo.save_standard_source(StandardSource(
            id="s", name="Probe", enabled=False, clash_url=f"http://127.0.0.1:{upstream.port}/{case}?token={written}",
            pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
        ))
        response = client.post("/api/sources/standard/s/pull", headers=headers)
        assert response.status_code == 200
        stored = services.repo.get_standard_source("s").last_pull_error
        assert "unsupported protocol <redacted>" in stored
        assert_clean(stored)
        assert_clean(json.dumps(response.json()["pull_result"], ensure_ascii=False))
        for path in ["/api/status", "/diagnostics", "/api/core/diagnose/source/s", "/api/sources/standard"]:
            read = client.get(path, headers=headers)
            assert read.status_code == 200, path
            assert_clean(_without_config_urls(read.json()))


def test_same_upstream_with_different_credentials_diagnoses_alike(diagnostic_client, monkeypatch) -> None:
    # A user name equal to an enum value ("proxy") must not rewrite
    # network_path: the diagnosis depends on it.
    client = diagnostic_client
    registry = client.app.state.tenant_registry

    async def broken(*_args, **_kwargs):
        return {"proxy_bridge": {"code": "unavailable", "repair_hint": "repair bridge"}}

    outcomes = {}
    with _ClashProtocolServer({}) as upstream:
        for user in ("proxy", "otheruser"):
            tenant = f"credential-{user}"
            services = registry.initialize(tenant)
            monkeypatch.setattr(services.egress_diagnostics, "get_status", broken)
            headers = {"X-HC-User-ID": tenant, "X-HC-User-Role": "owner"}
            services.repo.save_standard_source(StandardSource(
                id="s", name="Proxy", enabled=False, clash_url=f"http://{user}:x@127.0.0.1:{upstream.port}/fail",
                pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
            ))
            pulled = client.post("/api/sources/standard/s/pull", headers=headers)
            assert pulled.status_code == 200
            diagnosed = client.get("/api/core/diagnose/source/s", headers=headers).json()
            outcomes[user] = {
                "pull_paths": [attempt["network_path"] for attempt in pulled.json()["pull_result"]["attempts"]],
                "diagnose_paths": [attempt["network_path"] for attempt in diagnosed["attempts"]],
                "status": diagnosed["status"],
                "action": diagnosed["suggested_action"],
            }
    assert outcomes["proxy"] == outcomes["otheruser"]
    assert outcomes["proxy"]["status"] == "egress_failed" and outcomes["proxy"]["action"] == "repair bridge"
    assert "proxy" in outcomes["proxy"]["pull_paths"]


@pytest.mark.parametrize("failure_layer", ["fetcher", "hub", "route"])
def test_known_secrets_clean_persistence_and_outer_exceptions(diagnostic_client, monkeypatch, failure_layer) -> None:
    from app.services.source_fetcher import SourcePullAttempt, SourcePullResult

    client = diagnostic_client
    services = client.app.state.services
    source_id = "configured-exception"
    url = "https://h/sub?token=orchard"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Exception", enabled=False, clash_url=url))

    async def fail(*_args, **_kwargs):
        if failure_layer == "fetcher":
            return SourcePullResult(ok=False, error="orchard failed", attempts=[
                SourcePullAttempt("clash", False, 0, error="orchard", url="//orchard", skip_reasons=["orchard"]),
            ])
        raise RuntimeError("orchard failed") from ValueError("orchard cause")

    target, method = {
        "fetcher": (services.hub_service.source_fetcher, "fetch_source"),
        "hub": (services.hub_service, "_refresh_standard_source"),
        "route": (services.hub_service, "refresh_one_standard_source"),
    }[failure_layer]
    monkeypatch.setattr(target, method, fail)
    response = client.post(f"/api/sources/standard/{source_id}/pull")
    assert response.status_code == 200
    assert response.json()["item"]["clash_url"] == url
    assert "orchard" not in json.dumps(response.json()["pull_result"]).casefold()
    if failure_layer != "route":
        assert services.repo.get_standard_source(source_id).last_pull_error == "<redacted> failed"
    for endpoint in ("/api/status", "/diagnostics", f"/api/core/diagnose/source/{source_id}"):
        assert "orchard" not in client.get(endpoint).text.casefold()
    if failure_layer == "route":
        payload = {"name": "Exception", "clash_url": url, "shadowrocket_url": "https://h/sr",
                   "quality_group": "中等质量", "enabled": False}
        for response in [client.post("/api/sources/standard", json=payload),
                         client.put(f"/api/sources/standard/{source_id}", json=payload)]:
            assert response.status_code == 200
            assert "orchard" not in json.dumps(response.json()["pull_result"]).casefold()


@pytest.mark.parametrize("method", ["clash", "surge"])
@pytest.mark.parametrize("prefix", ["a", "api/https://inner", "api/https://inner/https://third"])
def test_real_http_ambiguous_paths_remain_clean_through_database_and_api(diagnostic_client, method, prefix) -> None:
    from app.services.source_diagnostics import public_runtime, public_source_status

    client = diagnostic_client
    services = client.app.state.services
    requests = []
    token = "AbC123dEf456"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    def assert_clean(value):
        assert token.casefold() not in json.dumps(value).casefold()

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            for index, punctuation in enumerate([",", ";", "'", '"']):
                source_id = f"real-boundary-{method}-{index}"
                path = f"/{prefix}{punctuation}//{token}/sub"
                raw = f"http://127.0.0.1:{server.server_port}{path}"
                services.repo.save_standard_source(StandardSource(
                    id=source_id, name="Boundary", enabled=False, **{method + "_url": raw},
                    pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
                ))
                # Real httpx/httpcore, fetcher and Hub. The returned diagnostic
                # has no editable source URL fields (those intentionally stay raw).
                result = asyncio.run(services.hub_service.refresh_one_standard_source(source_id, trigger="manual"))
                assert result["ok"] is False
                assert_clean(result)
                assert public_source_status(result) == result
                attempts = [a for a in result["attempts"] if a["method"] == method]
                assert len(attempts) == (3 if method == "clash" else 1)
                assert all("<redacted>" in a["url"] for a in attempts)
                stored = services.repo._conn.execute(
                    "SELECT last_pull_error FROM standard_sources WHERE id=?", (source_id,),
                ).fetchone()[0]
                assert stored == result["error"]
                assert_clean(stored)
                original = deepcopy(services.hub_service.runtime.to_dict())

                def read(endpoint):
                    response = client.get(endpoint)
                    assert response.status_code == 200
                    payload = response.json()
                    assert_clean(payload)  # Entire JSON, not selected diagnostic fields.
                    return payload

                endpoints = ["/api/status", "/diagnostics", f"/api/core/diagnose/source/{source_id}"]
                sequential = [read(endpoint) for endpoint in endpoints]
                with ThreadPoolExecutor(max_workers=3) as pool:
                    concurrent = list(pool.map(read, endpoints * 2))
                for i, payload in enumerate(concurrent):
                    if i % 3 == 2:
                        assert payload == sequential[2]
                assert services.hub_service.runtime.to_dict() == original
                assert public_runtime(original) == original
                assert services.repo.get_standard_source(source_id).last_pull_error == stored
                # httpx percent-encodes a double quote; the server still sees
                # the exact constructed path when decoded, including punctuation.
                assert sum(unquote(request_path) == path for request_path in requests) == len(attempts)
        finally:
            server.shutdown()
            worker.join()
    assert len(requests) == (12 if method == "clash" else 4)


@pytest.mark.parametrize("raw, public, expected_status", [
    ("code:403@upstream", "code:403@upstream", "suspected_expired"),
    ("expired:token@host/x", "//host/x", "unavailable"),
    ("status=403/forbidden@gateway/1", "//gateway/1", "unavailable"),
])
def test_bare_authority_decision_state_uses_public_text_only(diagnostic_client, raw, public, expected_status) -> None:
    client = diagnostic_client
    services = client.app.state.services
    source_id = "bare-authority-state"
    services.repo.save_standard_source(StandardSource(id=source_id, name="State", enabled=False))
    replies = []
    for text in (raw, public):
        services.repo.save_standard_source_pull_status(
            source_id, attempt_at="2026-01-01T00:00:00Z", ok=False, method="", node_count=0,
            error=text, trigger="manual",
        )
        response = client.get(f"/api/core/diagnose/source/{source_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == expected_status
        assert payload["reason"] == payload["last_pull_error"] == public
        assert services.repo.get_standard_source(source_id).last_pull_error == text
        replies.append(payload)
    assert replies[0] == replies[1]


@pytest.mark.parametrize("detail, public_detail", [
    ("https://sub.example/link/abc403defghijklmnop", "https://sub.example/link/<redacted>"),
    ("https://sub.example/link/abc401defghijklmnop", "https://sub.example/link/<redacted>"),
    ("https://sub.example/link/abcexpireddefghijklmnop", "https://sub.example/link/<redacted>"),
    ("https://sub.example/link/abcparsedefghijklmnop", "https://sub.example/link/<redacted>"),
    ("https://sub.example/parse/x", "https://sub.example/parse/x"),
    ("https://sub.example/403/x", "https://sub.example/403/x"),
    ("https://sub.example/expired/x", "https://sub.example/expired/x"),
    ("https://user403:pass@sub.example/sub", "https://sub.example/sub"),
    ("token=expired", "token=<redacted>"),
])
def test_legacy_diagnosis_uses_only_public_error_and_keeps_database(diagnostic_client, detail, public_detail) -> None:
    client = diagnostic_client
    services = client.app.state.services
    source_id = "legacy-public-state"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Legacy", enabled=False))
    if not detail.startswith("token="):
        detail, public_detail = f"({detail})", f"({public_detail})"
    raw = f"clash: HTTP 404 {detail}; clash: HTTP 404 {detail}"
    expected = f"clash: HTTP 404 {public_detail}"
    services.repo.save_standard_source_pull_status(
        source_id, attempt_at="2026-01-01T00:00:00Z", ok=False,
        method="", node_count=0, error=raw, trigger="manual",
    )
    before = tuple(services.repo._conn.execute("SELECT * FROM standard_sources WHERE id=?", (source_id,)).fetchone())
    for _ in range(2):
        response = client.get(f"/api/core/diagnose/source/{source_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "unavailable"
        assert response.json()["last_pull_error"] == response.json()["reason"] == expected
    after = tuple(services.repo._conn.execute("SELECT * FROM standard_sources WHERE id=?", (source_id,)).fetchone())
    assert before == after
    # Identical public text gives identical state, even when the DB used to
    # contain sensitive keywords. This is the B1 decision for historical rows.
    services.repo.save_standard_source_pull_status(
        source_id, attempt_at="2026-01-01T00:00:00Z", ok=False,
        method="", node_count=0, error=expected, trigger="manual",
    )
    assert client.get(f"/api/core/diagnose/source/{source_id}").json() == response.json()


@pytest.mark.parametrize("path", ["/s/0123456789abcdef", "/a//0123456789abcdef"])
def test_all_runtime_api_projections_hide_history_without_mutation(diagnostic_client, monkeypatch, path) -> None:
    client = diagnostic_client
    services = client.app.state.services
    hub = services.hub_service
    source_id = "history-runtime"
    services.repo.save_standard_source(StandardSource(id=source_id, name="History", enabled=False))
    raw_url = f"https://private-user:private-pass@sub.example{path}?ordinary=query-secret#fragment-secret"
    entry = f"clash: HTTP 404 ({raw_url})"
    old = f"{entry}; {entry}"
    clean = "clash: HTTP 404 (https://sub.example" + path.replace("0123456789abcdef", "<redacted>") + ")"
    services.repo.save_standard_source_pull_status(
        source_id, attempt_at="2026-01-01T00:00:00Z", ok=False,
        method="", node_count=0, error=old, trigger="manual",
    )
    hub.runtime.last_error = f"{old}; {old}"
    attempt = {"method": "clash", "ok": False, "url": raw_url, "error": entry,
               "node_count": 0, "network_path": "direct", "skip_reasons": [f"unsupported protocol {raw_url}"]}
    hub.runtime.source_status = {
        "standard": {source_id: {"error": old, "attempts": [attempt]}, "other": {"error": old, "attempts": [attempt]}},
        "aggregate": {"ok": False, "failed_count": 2, "errors": [old, old]},
    }
    original = deepcopy(hub.runtime.to_dict())

    def read(path):
        response = client.get(path)
        assert response.status_code == 200
        return response.json()

    paths = ["/api/status", "/diagnostics", f"/api/core/diagnose/source/{source_id}"]
    sequential = [read(path) for path in paths for _ in range(2)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        concurrent = list(pool.map(read, paths * 2))

    async def existing_runtime(**_kwargs):
        return hub.runtime

    monkeypatch.setattr(hub, "refresh", existing_runtime)
    refresh = client.post("/api/refresh")
    sync = client.post("/api/core/sync", json={"target": "all"})
    assert refresh.status_code == sync.status_code == 502
    for payload in sequential + concurrent + [refresh.json(), sync.json()]:
        text = json.dumps(payload)
        for secret in ("private-user", "private-pass", "0123456789abcdef", "query-secret", "fragment-secret"):
            assert secret not in text
    status = sequential[0]
    assert status["last_error"] == status["runtime"]["last_error"] == f"{clean}; {clean}"
    assert status["runtime"]["source_status"]["aggregate"]["errors"] == [clean, clean]
    assert hub.runtime.to_dict() == original
    assert services.repo.get_standard_source(source_id).last_pull_error == old
    # Modifying the returned attempt cannot change any original shared alias.
    status["runtime"]["source_status"]["standard"][source_id]["attempts"][0]["skip_reasons"].append("changed")
    assert hub.runtime.to_dict() == original


def test_refresh_exception_cleans_full_message_cause_and_stack_before_truncation(diagnostic_client, monkeypatch) -> None:
    from app.services.error_diagnostics import error_detail
    from app.services.source_diagnostics import public_source_status, source_error_detail

    client = diagnostic_client
    services = client.app.state.services
    source_id = "long-refresh-exception"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Exception", enabled=False))
    raw = "upstream failed https://private-user:" + "private-pass-" * 800 + "@host.test/sub"
    cause_text = "cause https://cause-user:" + "cause-pass-" * 900 + "@cause.test/sub"
    log_details = []

    async def fail_refresh(*_args, **_kwargs):
        raise RuntimeError(raw) from ValueError(cause_text)

    def capture_log(_message, _source_id, diagnostic):
        log_details.append(diagnostic)

    monkeypatch.setattr(services.hub_service, "_refresh_standard_source", fail_refresh)
    monkeypatch.setattr("app.services.hub_service._logger.error", capture_log)
    response = client.post(f"/api/sources/standard/{source_id}/pull")
    assert response.status_code == 200
    assert services.repo.get_standard_source(source_id).last_pull_error == "upstream failed https://host.test/sub"
    assert response.json()["pull_result"]["error"] == "upstream failed https://host.test/sub"
    detail = services.hub_service.runtime.source_status["standard"][source_id]["error_detail"]
    assert detail["message"] == "upstream failed https://host.test/sub"
    assert detail["cause"] == "cause https://cause.test/sub"
    assert len(detail["stack"]) <= 8000
    assert public_source_status(detail) == detail
    for payload in [response.json(), detail] + [
        client.get(path).json() for _ in range(2) for path in ("/api/status", "/diagnostics")
    ]:
        text = json.dumps(payload).casefold()
        for secret in ("private-user", "private-pass-", "cause-user", "cause-pass-"):
            assert secret not in text
    # The opt-in cleaner must leave the existing log diagnostic unchanged.
    assert log_details[0]["message"] == error_detail(RuntimeError(raw), "standard_source_refresh", "id")["message"]
    assert "private-pass-" in log_details[0]["message"]
    assert "cause-pass-" in log_details[0]["cause"]
    original_error = RuntimeError(raw)
    original_error.__cause__ = ValueError(cause_text)
    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(pool.map(lambda exc: source_error_detail(exc, "phase", "id"), [original_error] * 12))
    assert all(public_source_status(item) == item == details[0] for item in details)
    assert "private-user" not in json.dumps(details)
    assert "cause-pass-" not in json.dumps(details)
    assert str(original_error) == raw
    assert str(original_error.__cause__) == cause_text
    long_prose = source_error_detail(RuntimeError("plain " * 2000), "phase", "id")
    assert len(long_prose["message"]) == 2000
    assert len(long_prose["stack"]) == 8000


def test_create_update_pull_outer_exceptions_share_the_public_boundary(diagnostic_client, monkeypatch) -> None:
    client = diagnostic_client
    services = client.app.state.services
    raw = "outer failed https://outer-user:outer-pass@h.test/link/abc123def456?q=secret#f"

    async def outer_failure(*_args, **_kwargs):
        raise RuntimeError(raw)

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", outer_failure)
    payload = {"name": "Outer error", "clash_url": "https://example.test/sub",
               "shadowrocket_url": "https://example.test/sr", "quality_group": "中等质量", "enabled": False}
    created = client.post("/api/sources/standard", json=payload)
    assert created.status_code == 200, created.text
    source_id = created.json()["item"]["id"]
    responses = [created, client.put(f"/api/sources/standard/{source_id}", json=payload),
                 client.post(f"/api/sources/standard/{source_id}/pull")]
    for response in responses:
        assert response.status_code == 200
        assert response.json()["pull_result"]["error"] == "outer failed https://h.test/link/<redacted>"
        for secret in ("outer-user", "outer-pass", "abc123def456", "q=secret", "#f"):
            assert secret not in response.text


def test_public_exception_truncation_keeps_markers_limits_and_idempotence() -> None:
    from app.services.source_diagnostics import public_source_status, source_error_detail

    for url in ("https://u:p@h/link/abc123def456", "https://u:p@h/sub;token=secret",
                "https://u:p@[2001:db8::1]/link/abc123def456"):
        for length in [*range(1960, 2001), *range(7960, 8001)]:
            exc = RuntimeError("x" * length + " " + url)
            exc.__cause__ = ValueError(str(exc))
            detail = source_error_detail(exc, "phase", "id")
            assert len(detail["message"]) <= 2000
            assert len(detail["cause"]) <= 2000
            assert len(detail["stack"]) <= 8000
            assert public_source_status(detail) == detail
            for secret in ("u:p@", "abc123def456", "token=secret"):
                assert secret not in json.dumps(detail)


def test_normalize_pull_result_cleans_attempts_without_mutating_input() -> None:
    from app.routes.management import _normalize_pull_result

    raw = "https://outer-user:outer-pass@h.test/a//abc123def456?q=secret#f"
    original = {"ok": False, "error": raw, "attempts": [{"url": raw, "error": raw, "skip_reasons": [raw]}]}
    before = deepcopy(original)
    expected = "https://h.test/a//<redacted>"
    with ThreadPoolExecutor(max_workers=4) as pool:
        copies = list(pool.map(_normalize_pull_result, [original] * 12))
    for public in copies:
        assert public["error"] == public["attempts"][0]["url"] == public["attempts"][0]["error"] == expected
        assert public["attempts"][0]["skip_reasons"] == [expected]
        assert _normalize_pull_result(public) == public
    copies[0]["attempts"][0]["skip_reasons"].append("changed")
    assert original == before
    assert copies[1]["attempts"][0]["skip_reasons"] == [expected]


def test_refresh_exception_sanitizes_database_and_all_public_aliases(diagnostic_client, monkeypatch) -> None:
    client = diagnostic_client
    services = client.app.state.services
    source_id = "refresh-exception"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Exception", enabled=False))
    raw_url = "https://private-user:private-pass@sub.example/link/abc123def456?ordinary=query-secret#fragment-secret"

    async def fail_refresh(*_args, **_kwargs):
        raise RuntimeError(f"upstream failed {raw_url}")

    monkeypatch.setattr(services.hub_service, "_refresh_standard_source", fail_refresh)
    response = client.post(f"/api/sources/standard/{source_id}/pull")
    assert response.status_code == 200
    expected = "upstream failed https://sub.example/link/<redacted>"
    assert services.repo.get_standard_source(source_id).last_pull_error == expected
    assert response.json()["pull_result"]["error"] == expected
    for payload in (response.json(), client.get("/api/status").json(), client.get("/diagnostics").json()):
        text = json.dumps(payload)
        for secret in ("private-user", "private-pass", "abc123def456", "query-secret", "fragment-secret"):
            assert secret not in text


def test_standard_source_history_is_summarized_on_every_read_without_db_writes(client, monkeypatch) -> None:
    services = client.app.state.services
    source_id = "historical-error"
    services.repo.save_standard_source(StandardSource(id=source_id, name="History", enabled=False))
    raw_url = "https://user:private-pass@sub.example:8443/link/aB3dE5fG7hI9jK1m?foo=query-secret#fragment-secret"
    first = f"clash: HTTP 404 ({raw_url})"
    second = "surge: 0 valid nodes parsed; reason1; reason1; reason2"
    third = "shadowrocket: HTTP 403"
    original = "; ".join([first] * 6 + [second] * 2 + [third] * 2)
    expected = (
        "clash: HTTP 404 (https://sub.example:8443/link/<redacted>); "
        f"{second}; {third}"
    )
    services.repo.save_standard_source_pull_status(
        source_id, attempt_at="2026-01-01T00:00:00Z", ok=False,
        method="", node_count=0, error=original, trigger="manual",
    )

    async def healthy_egress():
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(services.core_facade, "diagnose_egress", healthy_egress)
    before = tuple(services.repo._conn.execute("SELECT * FROM standard_sources WHERE id=?", (source_id,)).fetchone())
    for _ in range(2):
        listed = client.get("/api/sources/standard")
        assert listed.status_code == 200
        assert next(item for item in listed.json()["items"] if item["id"] == source_id)["last_pull_error"] == expected
        state = client.get("/api/core/state")
        assert state.status_code == 200
        assert next(item for item in state.json()["sources"]["standard"] if item["id"] == source_id)["last_pull_error"] == expected
        diagnosed = client.get(f"/api/core/diagnose/source/{source_id}")
        assert diagnosed.status_code == 200
        assert diagnosed.json()["last_pull_error"] == diagnosed.json()["reason"] == expected
    after = tuple(services.repo._conn.execute("SELECT * FROM standard_sources WHERE id=?", (source_id,)).fetchone())
    assert before == after
    assert services.repo.get_standard_source(source_id).last_pull_error == original


@pytest.mark.parametrize("error, expected_status", [
    ("clash: HTTP 401", "suspected_expired"),
    ("surge: HTTP 403", "suspected_expired"),
    ("shadowrocket: subscription expired", "suspected_expired"),
    ("clash: 0 valid nodes parsed; reason1; reason2", "parse_failed"),
])
def test_standard_source_diagnosis_is_unchanged_by_summary_deduplication(client, monkeypatch, error, expected_status) -> None:
    services = client.app.state.services
    source_id = "diagnosis"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Diagnosis", enabled=False))

    async def healthy_egress():
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(services.core_facade, "diagnose_egress", healthy_egress)
    responses = []
    for text in ("; ".join([error] * 6), error):
        services.repo.save_standard_source_pull_status(
            source_id, attempt_at="2026-01-01T00:00:00Z", ok=False,
            method="", node_count=0, error=text, trigger="manual",
        )
        response = client.get(f"/api/core/diagnose/source/{source_id}")
        assert response.status_code == 200
        responses.append(response.json())
    assert responses[0] == responses[1]
    assert responses[0]["status"] == expected_status
    assert responses[0]["reason"] == error


def test_standard_source_read_preserves_empty_success_error(client, monkeypatch) -> None:
    services = client.app.state.services
    source_id = "no-error"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Healthy", enabled=False))
    services.repo.save_standard_source_pull_status(
        source_id, attempt_at="2026-01-01T00:00:00Z", ok=True,
        method="clash", node_count=1, error="", trigger="manual",
    )

    async def healthy_egress():
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(services.core_facade, "diagnose_egress", healthy_egress)
    assert next(item for item in client.get("/api/sources/standard").json()["items"] if item["id"] == source_id)["last_pull_error"] == ""
    response = client.get(f"/api/core/diagnose/source/{source_id}").json()
    assert response["last_pull_error"] == ""
    assert response["status"] == "healthy"
    assert response["reason"] == "latest pull succeeded"


def test_standard_source_save_update_and_pull_serialize_historical_errors(client, monkeypatch) -> None:
    services = client.app.state.services
    original = "clash: HTTP 404; clash: HTTP 404; surge: timeout; surge: timeout"
    expected = "clash: HTTP 404; surge: timeout"

    async def old_refresh(source_id, trigger="manual"):
        services.repo.save_standard_source_pull_status(
            source_id, attempt_at="2026-01-01T00:00:00Z", ok=False,
            method="", node_count=0, error=original, trigger=trigger,
        )
        return {"ok": False, "error": original, "attempts": []}

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", old_refresh)
    payload = {
        "name": "Old error", "clash_url": "https://example.test/clash.yaml",
        "shadowrocket_url": "https://example.test/sr", "quality_group": "中等质量", "enabled": False,
    }
    created = client.post("/api/sources/standard", json=payload)
    assert created.status_code == 200, created.text
    source_id = created.json()["item"]["id"]
    updated = client.put(f"/api/sources/standard/{source_id}", json=payload)
    pulled = client.post(f"/api/sources/standard/{source_id}/pull")
    for response in (created, updated, pulled):
        assert response.status_code == 200
        assert response.json()["item"]["last_pull_error"] == expected
    assert services.repo.get_standard_source(source_id).last_pull_error == original


def test_gorelay_refresh_propagates_account_failure(client, monkeypatch) -> None:
    service = client.app.state.services.gorelay_service

    async def _fake_refresh(*, force: bool = False):
        assert force is True
        service.runtime.last_error = "account unavailable"
        service.runtime.last_refresh_status = "failed"
        service.runtime.last_refresh_attempted_count = 1
        service.runtime.last_refresh_succeeded_count = 0
        service.runtime.last_refresh_failed_count = 1
        return service.runtime

    monkeypatch.setattr(service, "refresh", _fake_refresh)

    response = client.post("/api/gorelay/refresh")

    assert response.status_code == 502
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["failed_count"] == 1
    assert payload["last_error"] == "account unavailable"


def test_update_gorelay_source_preserves_passwords_when_fields_missing(client, monkeypatch) -> None:
    created = client.post(
        "/api/sources/gorelay",
        json={
            "name": "密码保留-A",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p-secret",
            "proxy_username": "proxy-u",
            "proxy_password": "proxy-secret",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = str(created.json()["item"]["id"])
    services = client.app.state.services

    async def _fake_collect(relay, selectors):
        assert relay.gorelay_password == "p-secret"
        return [], [], {"collector": "fake"}

    monkeypatch.setattr(services.gorelay_service.collector, "collect", _fake_collect)

    updated = client.put(
        f"/api/sources/gorelay/{source_id}",
        json={
            "name": "密码保留-A",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "proxy_username": "proxy-u",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert updated.status_code == 200

    account = services.repo.get_gorelay_account(source_id)
    assert account is not None
    assert account.gorelay_password == "p-secret"
    assert account.proxy_password_default == "proxy-secret"

    source = next(item for item in services.repo.list_gorelay_sources() if item.id == source_id)
    assert source.gorelay_password == "p-secret"
    assert source.proxy_password == "proxy-secret"

    listed = client.get("/api/sources/gorelay")
    assert listed.status_code == 200
    item = next(it for it in listed.json()["items"] if it["id"] == source_id)
    assert item["has_gorelay_password"] is True
    assert item["has_proxy_password"] is True

    crawled = client.post(f"/api/gorelay/accounts/{source_id}/crawl")
    assert crawled.status_code == 200
    assert crawled.json()["ok"] is True


def test_update_gorelay_source_preserves_passwords_when_fields_empty_string(client, monkeypatch) -> None:
    created = client.post(
        "/api/sources/gorelay",
        json={
            "name": "密码保留-B",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p-secret",
            "proxy_username": "proxy-u",
            "proxy_password": "proxy-secret",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = str(created.json()["item"]["id"])
    services = client.app.state.services

    async def _fake_collect(relay, selectors):
        assert relay.gorelay_password == "p-secret"
        return [], [], {"collector": "fake"}

    monkeypatch.setattr(services.gorelay_service.collector, "collect", _fake_collect)

    updated = client.put(
        f"/api/sources/gorelay/{source_id}",
        json={
            "name": "密码保留-B",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "",
            "proxy_username": "proxy-u",
            "proxy_password": "",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert updated.status_code == 200

    account = services.repo.get_gorelay_account(source_id)
    assert account is not None
    assert account.gorelay_password == "p-secret"
    assert account.proxy_password_default == "proxy-secret"

    source = next(item for item in services.repo.list_gorelay_sources() if item.id == source_id)
    assert source.gorelay_password == "p-secret"
    assert source.proxy_password == "proxy-secret"

    listed = client.get("/api/sources/gorelay")
    assert listed.status_code == 200
    item = next(it for it in listed.json()["items"] if it["id"] == source_id)
    assert item["has_gorelay_password"] is True
    assert item["has_proxy_password"] is True

    crawled = client.post(f"/api/gorelay/accounts/{source_id}/crawl")
    assert crawled.status_code == 200
    assert crawled.json()["ok"] is True


def test_gorelay_crawl_syncs_devices_for_management_api_without_global_refresh(client, monkeypatch) -> None:
    source_id = _create_gorelay_source(client, name="自动同步源")
    services = client.app.state.services

    async def _fake_collect(relay, selectors):
        return [
            CollectedRule(
                account_id=source_id,
                rule_id="r-mac",
                device_name="Mac",
                line_name="Mac #1",
                entry_name="上海 1x",
                isp="电信",
                ip_version="ipv4",
                port=1080,
                host="1.1.1.1",
                status="ready",
                raw={"multiplier": "1"},
            )
        ], [], {"collector": "fake"}

    monkeypatch.setattr(services.gorelay_service.collector, "collect", _fake_collect)

    before_devices = client.get("/api/devices")
    assert before_devices.status_code == 200
    before_count = len(before_devices.json()["items"])

    crawled = client.post(f"/api/gorelay/accounts/{source_id}/crawl")
    assert crawled.status_code == 200
    payload = crawled.json()
    assert payload["ok"] is True
    assert payload["account_id"] == source_id
    assert "device_sync" in payload
    assert payload["device_sync"]["after_count"] >= before_count
    assert payload["device_sync"]["added_count"] >= 1

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    assert any(item["device_name"] == "Mac" for item in devices.json()["items"])


def test_gorelay_crawl_failure_keeps_saved_source_configuration(client, monkeypatch) -> None:
    source_id = _create_gorelay_source(client, name="失败不丢配置")
    services = client.app.state.services

    async def _fake_crawl_account(_account_id: str):
        raise RuntimeError("crawl failed")

    monkeypatch.setattr(services.gorelay_service, "crawl_account", _fake_crawl_account)

    crawled = client.post(f"/api/gorelay/accounts/{source_id}/crawl")
    assert crawled.status_code == 400

    listed = client.get("/api/sources/gorelay")
    assert listed.status_code == 200
    item = next((row for row in listed.json()["items"] if row["id"] == source_id), None)
    assert item is not None
    assert item["name"] == "失败不丢配置"
    assert item["enabled"] is True


def test_gorelay_sources_include_latest_refresh_status_and_active_version(client) -> None:
    services = client.app.state.services
    source_id = _create_gorelay_source(client, name="主力GoRelay")

    services.repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id=source_id,
                snapshot_id="snap-old",
                created_at="2026-03-09T09:36:20Z",
                node_count=48,
                device_count=5,
                status="success",
            ),
            collected_rules=[],
            device_nodes={},
            device_names={},
            pending_bindings=[],
            source_status={},
        )
    )
    services.repo.save_gorelay_active_snapshot_id(source_id, "snap-old")
    services.repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id=source_id,
                snapshot_id="snap-new",
                created_at="2026-03-09T10:42:26Z",
                node_count=50,
                device_count=5,
                status="failed",
                error="login failed",
            ),
            collected_rules=[],
            device_nodes={},
            device_names={},
            pending_bindings=[{"entry_name": "沪日 IPLC"}],
            source_status={},
        )
    )

    listed = client.get("/api/sources/gorelay")
    assert listed.status_code == 200
    item = next(item for item in listed.json()["items"] if item["id"] == source_id)
    assert item["last_refresh_at"] == "2026-03-09T10:42:26Z"
    assert item["last_refresh_status"] == "failed"
    assert item["last_refresh_error"] == "login failed"
    assert item["last_node_count"] == 50
    assert item["last_device_count"] == 5
    assert item["pending_domain_count"] == 1
    assert item["latest_snapshot_id"] == "snap-new"
    assert item["active_snapshot_id"] == "snap-old"
    assert item["active_snapshot_is_latest"] is False


def test_standard_source_accepts_high_quality_airport(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        return {
            "ok": True,
            "pull_method": "surge",
            "pull_node_count": 12,
            "error": "",
            "attempts": [{"method": "clash", "ok": False}, {"method": "surge", "ok": True}],
            "last_success_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "高质量机场A",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "quality_group": "高质量机场",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = created.json()["item"]["id"]
    assert created.json()["item"]["quality_group"] == "高质量机场"
    assert created.json()["item"]["source_mode"] == "high_quality_airport"
    assert created.json()["item"]["target_contract_id"] == ""
    assert created.json()["pull_result"]["ok"] is True
    assert created.json()["pull_result"]["method"] == "surge"

    updated = client.put(
        f"/api/sources/standard/{source_id}",
        json={
            "name": "高质量机场A",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "quality_group": "高质量机场",
            "enabled": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["quality_group"] == "高质量机场"
    assert updated.json()["item"]["source_mode"] == "high_quality_airport"
    assert updated.json()["pull_result"]["ok"] is True


def test_standard_source_accepts_manual_nodes_ingest_and_reports_compatibility(client) -> None:
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "自建节点源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": (
                "vless://ed3fe100-6b33-4a4c-9ce4-ccef569adfab@r.example.com:443"
                "?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.samsung.com"
                "&fp=chrome&pbk=pub-key-1&sid=short-1&type=tcp#Fast%20Lane"
            ),
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["ingest_kind"] == "manual_nodes"
    assert item["manual_nodes_text"].startswith("vless://ed3fe100")
    assert item["clash_url"] == ""
    assert item["shadowrocket_url"] == ""
    assert created.json()["pull_result"]["ok"] is True
    assert created.json()["pull_result"]["method"] == "manual_nodes"

    compatibility = item["compatibility"]
    assert any(diag["code"] == "surge-vless-refused" for diag in compatibility["surge"]["refused"])
    pending_codes = {diag["code"] for diag in compatibility["shadowrocket"]["pending_validation"]}
    assert "shadowrocket-unverified-fields-omitted" in pending_codes


def test_standard_source_manual_nodes_pull_revalidates_updated_text(client) -> None:
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "自建节点源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": "trojan://secret@a.example.com:443?sni=example.com#A",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = created.json()["item"]["id"]
    assert created.json()["pull_result"]["node_count"] == 1

    updated = client.put(
        f"/api/sources/standard/{source_id}",
        json={
            "name": "自建节点源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": (
                "trojan://secret@a.example.com:443?sni=example.com#A\n"
                "ss://YWVzLTI1Ni1nY206cGFzczFAc3MuZXhhbXBsZS5jb206NDQz#B"
            ),
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["pull_result"]["node_count"] == 2

    pulled = client.post(f"/api/sources/standard/{source_id}/pull")
    assert pulled.status_code == 200
    assert pulled.json()["pull_result"]["ok"] is True
    assert pulled.json()["pull_result"]["node_count"] == 2


def test_standard_source_manual_nodes_requires_text(client) -> None:
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "空自建节点源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": "",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 400
    assert created.json()["detail"] == "manual_nodes_text is required for manual_nodes ingest"


def test_standard_source_accepts_target_contract_id(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        return {
            "ok": True,
            "pull_method": "clash",
            "pull_node_count": 6,
            "error": "",
            "attempts": [{"method": "clash", "ok": True}],
            "last_success_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    updated_contract = client.put(
        "/api/contracts/medium",
        json={
            "display_name": "中等质量 IP",
            "description": "通用海外访问",
        },
    )
    assert updated_contract.status_code == 200

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场B",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    assert created.json()["item"]["target_contract_id"] == "medium"
    assert created.json()["item"]["target_contract_display_name"] == "中等质量 IP"
    assert created.json()["item"]["quality_group"] == "中等质量 IP"


def test_standard_source_list_uses_selected_scenario_contract_display_name(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        return {
            "ok": True,
            "pull_method": "clash",
            "pull_node_count": 6,
            "error": "",
            "attempts": [{"method": "clash", "ok": True}],
            "last_success_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    renamed_contract = client.put(
        "/api/contracts/medium?scenario_id=scenario-work",
        json={"display_name": "工作中转"},
    )
    assert renamed_contract.status_code == 200

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场Work",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 200

    default_list = client.get("/api/sources/standard")
    assert default_list.status_code == 200
    default_item = next(item for item in default_list.json()["items"] if item["name"] == "机场Work")
    assert default_item["target_contract_display_name"] == "中等质量"

    scenario_list = client.get("/api/sources/standard?scenario_id=scenario-work")
    assert scenario_list.status_code == 200
    scenario_item = next(item for item in scenario_list.json()["items"] if item["name"] == "机场Work")
    assert scenario_item["target_contract_display_name"] == "工作中转"
    assert scenario_item["quality_group"] == "工作中转"


def test_standard_source_rejects_disabled_default_scenario_contract_target(client) -> None:
    disabled = client.put(
        "/api/contracts/medium",
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场Disabled",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 400
    assert "target_contract_id" in created.json()["detail"]


def test_standard_source_rejects_scenario_only_contract_visibility_for_global_source(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )
    _stub_standard_refresh(client, monkeypatch)

    disabled = client.put(
        "/api/contracts/medium",
        json={"enabled": False},
    )
    assert disabled.status_code == 200

    enabled_for_scenario = client.put(
        "/api/contracts/medium?scenario_id=scenario-work",
        json={"enabled": True},
    )
    assert enabled_for_scenario.status_code == 200

    created = client.post(
        "/api/sources/standard?scenario_id=scenario-work",
        json={
            "name": "机场ScenarioWork",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 400
    assert "target_contract_id" in created.json()["detail"]


def test_standard_source_update_accepts_existing_disabled_target_contract(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    services = client.app.state.services

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场B",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = created.json()["item"]["id"]

    source_disabled = client.put(
        f"/api/sources/standard/{source_id}",
        json={
            "name": "机场B-停用",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": False,
        },
    )
    assert source_disabled.status_code == 200

    medium = services.repo.get_route_contract("medium")
    assert medium is not None
    services.repo.save_route_contract(
        medium.__class__(
            id=medium.id,
            display_name=medium.display_name,
            description="暂时禁用",
            strategy_type=medium.strategy_type,
            primary_pools=list(medium.primary_pools),
            fallback_pools=list(medium.fallback_pools),
            failure_action=medium.failure_action,
            editable=medium.editable,
            enabled=False,
            sort_order=medium.sort_order,
            owner_scenario_id=medium.owner_scenario_id,
            is_system=medium.is_system,
            updated_at=medium.updated_at,
        )
    )
    disabled = services.repo.get_route_contract("medium")
    assert disabled is not None
    assert disabled.enabled is False

    updated = client.put(
        f"/api/sources/standard/{source_id}",
        json={
            "name": "机场B-已停用",
            "clash_url": "https://example.com/updated.yaml",
            "shadowrocket_url": "https://example.com/updated.conf",
            "target_contract_id": "medium",
            "source_mode": "route_contract",
            "enabled": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["target_contract_id"] == "medium"
    assert updated.json()["item"]["enabled"] is False


def test_standard_source_rejects_invalid_target_contract(client) -> None:
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场X",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "target_contract_id": "direct",
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created.status_code == 400
    assert "target_contract_id" in created.json()["detail"]


def test_standard_source_rejects_invalid_source_mode(client) -> None:
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场模式错误",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "source_mode": "high_quality_airprot",
            "enabled": True,
        },
    )
    assert created.status_code == 400
    assert "source_mode must be one of" in created.json()["detail"]


def test_standard_source_accepts_optional_surge_url(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        return {
            "ok": True,
            "pull_method": "clash",
            "pull_node_count": 5,
            "error": "",
            "attempts": [{"method": "clash", "ok": True}],
            "last_success_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场Y",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "quality_group": "中等质量",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    assert created.json()["item"]["surge_url"] == ""
    assert created.json()["pull_result"]["ok"] is True


def test_standard_source_save_failure_returns_warning_payload(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        services.repo.save_standard_source_pull_status(
            source_id,
            attempt_at="2026-01-02T00:00:00Z",
            ok=False,
            method="",
            node_count=0,
            error="clash: timeout",
            trigger="save",
        )
        return {
            "ok": False,
            "pull_method": "",
            "pull_node_count": 0,
            "error": "clash: timeout",
            "attempts": [{"method": "clash", "ok": False, "error": "timeout"}],
            "last_success_at": None,
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场Z",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "quality_group": "中等质量",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    assert created.json()["pull_result"]["ok"] is False
    assert "timeout" in created.json()["pull_result"]["error"]
    assert created.json()["item"]["last_pull_ok"] is False
    assert "timeout" in created.json()["item"]["last_pull_error"]


def test_standard_source_manual_pull_endpoint(client, monkeypatch) -> None:
    services = client.app.state.services
    calls: list[str] = []

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        calls.append(source_id)
        return {
            "ok": True,
            "pull_method": "surge",
            "pull_node_count": 9,
            "error": "",
            "attempts": [{"method": "surge", "ok": True}],
            "last_success_at": "2026-01-03T00:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)
    source_id = _create_standard_source(client)

    pulled = client.post(f"/api/sources/standard/{source_id}/pull")
    assert pulled.status_code == 200
    assert pulled.json()["ok"] is True
    assert pulled.json()["pull_result"]["ok"] is True
    assert pulled.json()["pull_result"]["method"] == "surge"
    assert pulled.json()["pull_result"]["node_count"] == 9
    assert pulled.json()["item"]["id"] == source_id
    assert pulled.json()["item"]["pull_network_mode"] == "direct_then_proxy"
    assert pulled.json()["item"]["auto_pull_consecutive_failures"] == 0
    assert pulled.json()["item"]["auto_pull_expired"] is False
    assert pulled.json()["item"]["auto_pull_expired_at"] is None
    assert pulled.json()["item"]["qr_assets"]["clash"]["field"] == "clash"
    assert calls == [source_id, source_id]


def test_standard_source_warning_payloads_exposed_for_save_pull_and_list(client, monkeypatch) -> None:
    services = client.app.state.services
    warning = StandardSourceWarning(
        code="standard-source-clash-url-format-mismatch",
        message="clash_url parsed as uri-plain; expected clash-yaml",
        field="clash_url",
        expected_method="clash",
        actual_variant="format:uri-plain",
    )

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        detail = {
            "source_name": "机场A",
            "node_count": 5,
            "ok": True,
            "error": "",
            "attempts": [{"method": "clash", "ok": True, "request_variant": "ua:test|format:uri-plain"}],
            "pull_method": "clash",
            "pull_node_count": 5,
            "cached_node_count": 5,
            "warning_count": 1,
            "warnings": [warning.to_dict()],
            "filtered_technical_count": 0,
            "filtered_technical_examples": [],
            "last_success_at": "2026-01-03T00:00:00Z",
            "config_fingerprint": "cfg-1",
            "last_success_config_fingerprint": "cfg-1",
            "pull_network_mode": "direct_then_proxy",
            "auto_pull_consecutive_failures": 0,
            "auto_pull_expired": False,
            "auto_pull_expired_at": None,
            "unrecognized_multiplier_count": 0,
            "unrecognized_examples": [],
        }
        source_status = dict(services.hub_service.runtime.source_status or {})
        standard_status = dict(source_status.get("standard") or {})
        standard_status[source_id] = detail
        source_status["standard"] = standard_status
        services.hub_service.runtime.source_status = source_status
        return {"source_id": source_id, **detail}

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场A",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "quality_group": "中等质量",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = str(created.json()["item"]["id"])
    assert created.json()["pull_result"]["ok"] is True
    assert created.json()["pull_result"]["warning_count"] == 1
    assert created.json()["pull_result"]["warnings"][0]["code"] == warning.code
    assert created.json()["item"]["pull_warning_count"] == 1
    assert created.json()["item"]["pull_warnings"][0]["actual_variant"] == "format:uri-plain"

    pulled = client.post(f"/api/sources/standard/{source_id}/pull")
    assert pulled.status_code == 200
    assert pulled.json()["pull_result"]["warning_count"] == 1
    assert pulled.json()["pull_result"]["warnings"][0]["field"] == "clash_url"

    listed = client.get("/api/sources/standard")
    assert listed.status_code == 200
    listed_item = next(item for item in listed.json()["items"] if item["id"] == source_id)
    assert listed_item["pull_warning_count"] == 1
    assert listed_item["pull_warnings"][0]["code"] == warning.code


def test_standard_source_filtered_technical_fields_exposed(client, monkeypatch) -> None:
    services = client.app.state.services
    pulls: list[str] = []

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        pulls.append(trigger)
        filtered_count = 2 if trigger == "save" else 1
        return {
            "ok": True,
            "pull_method": "clash",
            "pull_node_count": 7,
            "cached_node_count": 7,
            "error": "",
            "attempts": [{"method": "clash", "ok": True}],
            "last_success_at": "2026-01-03T00:00:00Z",
            "filtered_technical_count": filtered_count,
            "filtered_technical_examples": [
                "[机场A] Traffic: 2.29 GB | 20 GB",
            ],
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场A",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "quality_group": "中等质量",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    source_id = str(created.json()["item"]["id"])
    assert created.json()["pull_result"]["filtered_technical_count"] == 2
    assert created.json()["pull_result"]["filtered_technical_examples"] == [
        "[机场A] Traffic: 2.29 GB | 20 GB"
    ]

    updated = client.put(
        f"/api/sources/standard/{source_id}",
        json={
            "name": "机场A 更新",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "https://example.com/surge.conf",
            "quality_group": "中等质量",
            "enabled": True,
            "pull_network_mode": "direct_then_proxy",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["pull_result"]["filtered_technical_count"] == 2

    pulled = client.post(f"/api/sources/standard/{source_id}/pull")
    assert pulled.status_code == 200
    assert pulled.json()["pull_result"]["filtered_technical_count"] == 1
    assert pulled.json()["pull_result"]["filtered_technical_examples"] == [
        "[机场A] Traffic: 2.29 GB | 20 GB"
    ]

    services.hub_service.runtime.source_status = {
        "standard": {
            source_id: {
                "filtered_technical_count": 3,
                "filtered_technical_examples": [
                    "[机场A] Traffic: 2.29 GB | 20 GB",
                ],
            }
        }
    }

    listed = client.get("/api/sources/standard")
    assert listed.status_code == 200
    listed_item = next(item for item in listed.json()["items"] if item["id"] == source_id)
    assert listed_item["filtered_technical_count"] == 3
    assert listed_item["filtered_technical_examples"] == ["[机场A] Traffic: 2.29 GB | 20 GB"]

    status = client.get("/api/status")
    assert status.status_code == 200
    assert (
        status.json()["runtime"]["source_status"]["standard"][source_id]["filtered_technical_count"]
        == 3
    )
    assert pulls == ["save", "save", "manual"]


def test_standard_source_manual_pull_404_for_missing_source(client) -> None:
    pulled = client.post("/api/sources/standard/not-exists/pull")
    assert pulled.status_code == 404
    assert pulled.json()["detail"] == "standard source not found"


def test_standard_source_pull_network_mode_default_and_override(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)

    created_default = client.post(
        "/api/sources/standard",
        json={
            "name": "机场D",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "quality_group": "中等质量",
            "enabled": True,
        },
    )
    assert created_default.status_code == 200
    source_id = created_default.json()["item"]["id"]
    assert created_default.json()["item"]["pull_network_mode"] == "direct_then_proxy"
    assert created_default.json()["item"]["config_fingerprint"]
    assert created_default.json()["item"]["last_success_config_fingerprint"] == ""
    assert created_default.json()["item"]["export_config"]["pull_network_mode"] == "direct_then_proxy"
    assert created_default.json()["item"]["auto_pull_consecutive_failures"] == 0
    assert created_default.json()["item"]["auto_pull_expired"] is False
    assert created_default.json()["item"]["auto_pull_expired_at"] is None

    updated = client.put(
        f"/api/sources/standard/{source_id}",
        json={
            "name": "机场D",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "surge_url": "",
            "quality_group": "中等质量",
            "pull_network_mode": "direct_only",
            "enabled": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["pull_network_mode"] == "direct_only"
    assert updated.json()["item"]["config_fingerprint"]

    listed = client.get("/api/sources/standard")
    assert listed.status_code == 200
    item = next(it for it in listed.json()["items"] if it["id"] == source_id)
    assert item["pull_network_mode"] == "direct_only"
    assert item["export_config"]["pull_network_mode"] == "direct_only"


def test_standard_source_rejects_invalid_pull_network_mode(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    created = client.post(
        "/api/sources/standard",
        json={
            "name": "机场E",
            "clash_url": "https://example.com/clash.yaml",
            "shadowrocket_url": "https://example.com/sr.conf",
            "quality_group": "中等质量",
            "pull_network_mode": "bad_mode",
            "enabled": True,
        },
    )
    assert created.status_code == 400
    assert "pull_network_mode" in created.json()["detail"]


def test_standard_source_manual_pull_success_clears_expired_state(client, monkeypatch) -> None:
    services = client.app.state.services
    source_id = _create_standard_source(client)
    for idx in range(10):
        services.repo.save_standard_source_pull_status(
            source_id,
            attempt_at=f"2026-01-04T00:00:{idx:02d}Z",
            ok=False,
            method="",
            node_count=0,
            error="expired",
            trigger="auto",
        )

    async def _fake_refresh_one(source_id: str, trigger: str = "manual"):
        services.repo.save_standard_source_pull_status(
            source_id,
            attempt_at="2026-01-04T01:00:00Z",
            ok=True,
            method="clash",
            node_count=8,
            error="",
            trigger=trigger,
        )
        return {
            "ok": True,
            "pull_method": "clash",
            "pull_node_count": 8,
            "error": "",
            "attempts": [{"method": "clash", "ok": True}],
            "last_success_at": "2026-01-04T01:00:00Z",
        }

    monkeypatch.setattr(services.hub_service, "refresh_one_standard_source", _fake_refresh_one)
    pulled = client.post(f"/api/sources/standard/{source_id}/pull")
    assert pulled.status_code == 200
    assert pulled.json()["item"]["auto_pull_expired"] is False
    assert pulled.json()["item"]["auto_pull_consecutive_failures"] == 0
    assert pulled.json()["item"]["auto_pull_expired_at"] is None


def test_standard_source_qr_asset_upload_get_list_image_delete(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    source_id = _create_standard_source(client)

    listed = client.get("/api/sources/standard")
    assert listed.status_code == 200
    item = next(it for it in listed.json()["items"] if it["id"] == source_id)
    assert item["qr_assets"]["clash"]["image_exists"] is False
    assert item["qr_assets"]["shadowrocket"]["image_exists"] is False
    assert item["qr_assets"]["surge"]["image_exists"] is False

    content = b"\x89PNG\r\n\x1a\nfake-image"
    uploaded = client.post(
        f"/api/sources/standard/{source_id}/qr/clash",
        files={"file": ("clash.png", content, "image/png")},
        data={"detected_url": "https://example.com/clash.yaml"},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["item"]["image_exists"] is True
    assert uploaded.json()["item"]["detected_url"] == "https://example.com/clash.yaml"
    assert uploaded.json()["detected_url_source"] == "provided"
    assert uploaded.json()["source_updated"] is False
    assert uploaded.json()["updated_field"] == ""
    assert uploaded.json()["pull_result"]["ok"] is True
    assert uploaded.json()["item"]["image_url"].endswith(f"/api/sources/standard/{source_id}/qr/clash/image")

    got = client.get(f"/api/sources/standard/{source_id}/qr/clash")
    assert got.status_code == 200
    assert got.json()["item"]["image_exists"] is True
    assert got.json()["item"]["detected_url"] == "https://example.com/clash.yaml"

    image = client.get(f"/api/sources/standard/{source_id}/qr/clash/image")
    assert image.status_code == 200
    assert image.content == content

    listed_after_upload = client.get("/api/sources/standard")
    assert listed_after_upload.status_code == 200
    item_after_upload = next(
        it for it in listed_after_upload.json()["items"] if it["id"] == source_id
    )
    assert item_after_upload["qr_assets"]["clash"]["image_exists"] is True

    deleted = client.delete(f"/api/sources/standard/{source_id}/qr/clash")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    got_after_delete = client.get(f"/api/sources/standard/{source_id}/qr/clash")
    assert got_after_delete.status_code == 404
    image_after_delete = client.get(f"/api/sources/standard/{source_id}/qr/clash/image")
    assert image_after_delete.status_code == 404


def test_standard_source_qr_asset_reupload_replaces_file(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    source_id = _create_standard_source(client)
    repo = client.app.state.services.repo
    qr_dir = repo.data_dir / "standard-source-qr" / source_id

    first = client.post(
        f"/api/sources/standard/{source_id}/qr/clash",
        files={"file": ("clash.png", b"png-v1", "image/png")},
        data={"detected_url": "https://example.com/one"},
    )
    assert first.status_code == 200
    assert (qr_dir / "clash.png").exists()

    second = client.post(
        f"/api/sources/standard/{source_id}/qr/clash",
        files={"file": ("clash.jpg", b"jpeg-v2", "image/jpeg")},
        data={"detected_url": "https://example.com/two"},
    )
    assert second.status_code == 200
    assert not (qr_dir / "clash.png").exists()
    assert (qr_dir / "clash.jpg").exists()

    image = client.get(f"/api/sources/standard/{source_id}/qr/clash/image")
    assert image.status_code == 200
    assert image.content == b"jpeg-v2"


def test_standard_source_qr_asset_upload_decodes_and_backfills_url(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    monkeypatch.setattr(
        "app.routes.management._decode_standard_source_qr_url",
        lambda _content: "https://decoded.example.com/sub.yaml",
    )
    source_id = _create_standard_source(client)

    uploaded = client.post(
        f"/api/sources/standard/{source_id}/qr/clash",
        files={"file": ("clash.png", b"fake-png", "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["item"]["detected_url"] == "https://decoded.example.com/sub.yaml"
    assert uploaded.json()["detected_url_source"] == "decoded"
    assert uploaded.json()["source_updated"] is True
    assert uploaded.json()["updated_field"] == "clash_url"
    assert uploaded.json()["pull_result"]["ok"] is True

    source = client.app.state.services.repo.get_standard_source(source_id)
    assert source is not None
    assert source.clash_url == "https://decoded.example.com/sub.yaml"


def test_standard_source_qr_asset_upload_without_decoded_url_keeps_source_unchanged(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    monkeypatch.setattr(
        "app.routes.management._decode_standard_source_qr_url",
        lambda _content: "",
    )
    source_id = _create_standard_source(client)
    source_before = client.app.state.services.repo.get_standard_source(source_id)
    assert source_before is not None

    uploaded = client.post(
        f"/api/sources/standard/{source_id}/qr/shadowrocket",
        files={"file": ("sr.png", b"fake-png", "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["item"]["detected_url"] == ""
    assert uploaded.json()["detected_url_source"] == "none"
    assert uploaded.json()["source_updated"] is False
    assert uploaded.json()["updated_field"] == ""
    assert uploaded.json()["pull_result"] is None

    source_after = client.app.state.services.repo.get_standard_source(source_id)
    assert source_after is not None
    assert source_after.shadowrocket_url == source_before.shadowrocket_url


def test_standard_source_qr_asset_rejects_invalid_field(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    source_id = _create_standard_source(client)

    resp = client.post(
        f"/api/sources/standard/{source_id}/qr/not-real",
        files={"file": ("x.png", b"x", "image/png")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid qr field"


def test_standard_source_qr_asset_rejects_invalid_file_and_size(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    source_id = _create_standard_source(client)

    bad_type = client.post(
        f"/api/sources/standard/{source_id}/qr/clash",
        files={"file": ("x.png", b"x", "text/plain")},
    )
    assert bad_type.status_code == 400
    assert "content type" in bad_type.json()["detail"]

    oversized = client.post(
        f"/api/sources/standard/{source_id}/qr/clash",
        files={"file": ("x.png", b"a" * (4 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 400
    assert "max 4MB" in oversized.json()["detail"]


def test_standard_source_delete_cleans_qr_assets(client, monkeypatch) -> None:
    _stub_standard_refresh(client, monkeypatch)
    source_id = _create_standard_source(client)
    repo = client.app.state.services.repo
    qr_dir: Path = repo.data_dir / "standard-source-qr" / source_id

    uploaded = client.post(
        f"/api/sources/standard/{source_id}/qr/surge",
        files={"file": ("surge.webp", b"webp-v1", "image/webp")},
    )
    assert uploaded.status_code == 200
    assert qr_dir.exists()

    deleted_source = client.delete(f"/api/sources/standard/{source_id}")
    assert deleted_source.status_code == 200
    assert not qr_dir.exists()

    missing = client.get(f"/api/sources/standard/{source_id}/qr/surge")
    assert missing.status_code == 404


def test_list_standard_sources_reports_cached_node_count(client) -> None:
    services = client.app.state.services
    source_id = "s-cache"
    services.repo.save_standard_source(
        StandardSource(
            id=source_id,
            name="缓存可见性",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        source_id,
        [
            NodeRecord(
                name="[缓存可见性] n1",
                host="n1.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
                source_id=source_id,
                source_type="standard",
            ),
            NodeRecord(
                name="[缓存可见性] n2",
                host="n2.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
                source_id=source_id,
                source_type="standard",
            ),
        ],
    )

    listed = client.get("/api/sources/standard")
    assert listed.status_code == 200
    item = next(entry for entry in listed.json()["items"] if entry["id"] == source_id)
    assert int(item["cached_node_count"]) == 2


def test_gorelay_api_accounts_and_subscription_disable(client) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "GoRelay-A",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "mcp_url": "https://mcp.example.com",
            "auth_header": "Bearer x",
            "login_tool": "auth_login",
            "nodes_tool": "list_nodes",
            "login_args_json": "{}",
            "nodes_args_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["item"]["id"]

    listed = client.get("/api/gorelay/accounts")
    assert listed.status_code == 200
    account = next(item for item in listed.json()["items"] if item["id"] == account_id)
    assert account["mcp_url"] == "https://mcp.example.com"
    assert account["login_tool"] == "auth_login"
    assert account["nodes_tool"] == "list_nodes"
    assert account["has_auth_header"] is True

    client.app.state.services.repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="gs1",
            account_id=account_id,
            device_key="mac",
            device_name="Mac",
            token="tok-gorelay",
            enabled=True,
        )
    )

    subs = client.get(f"/api/gorelay/subscriptions?account_id={account_id}")
    assert subs.status_code == 200
    assert any(item["id"] == "gs1" for item in subs.json()["items"])

    disabled = client.post("/api/gorelay/subscriptions/gs1/disable")
    assert disabled.status_code == 200

    pending = client.get(f"/api/gorelay/accounts/{account_id}/domain-bindings/pending")
    assert pending.status_code == 200
    assert "pending" in pending.json()
    assert "bindings" in pending.json()

    entries = client.get(f"/api/gorelay/accounts/{account_id}/entries")
    assert entries.status_code == 200
    assert entries.json()["ok"] is True

    status = client.get(f"/api/gorelay/accounts/{account_id}/status")
    assert status.status_code == 200
    assert status.json()["ok"] is True
    assert "snapshot_id" in status.json()
    assert "created_at" in status.json()

    forbidden = client.get(_scenario_sub_path("tok-gorelay", "clash.yaml"))
    assert forbidden.status_code == 403


def test_gorelay_update_binding_triggers_rebuild(client, monkeypatch) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "GoRelay-B",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    account_id = created.json()["item"]["id"]
    client.app.state.services.repo.save_gorelay_domain_bindings(
        [
            GoRelayDomainBinding(
                id="b1",
                account_id=account_id,
                entry_name="入口A",
                isp="ct",
                ip_version="ipv4",
                host_value="1.1.1.1",
                source="manual_import",
                status="approved",
                updated_at="2026-01-01T00:00:00Z",
            )
        ]
    )

    def _fake_rebuild(_: str):
        return {"ok": True, "snapshot_id": "s1"}

    monkeypatch.setattr(
        client.app.state.services.gorelay_service,
        "rebuild_account_from_latest_rules",
        _fake_rebuild,
    )

    resp = client.put(
        f"/api/gorelay/accounts/{account_id}/domain-bindings/b1",
        json={"host_value": "2.2.2.2", "status": "approved"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["item"]["host_value"] == "2.2.2.2"
    assert body["rebuild"]["snapshot_id"] == "s1"


def test_gorelay_pending_and_entries_split_other_usage_to_specific_bindings(client) -> None:
    services = client.app.state.services
    account = GoRelayAccount(
        id="acc-split",
        name="GoRelay-Split",
        login_url="https://relay.example.com",
        rules_url="https://relay.example.com",
        gorelay_username="u",
        gorelay_password="p",
        selectors_json="{}",
        enabled=True,
        updated_at="2026-01-01T00:00:00Z",
    )
    services.gorelay_service.save_account(account)
    services.repo.save_gorelay_domain_bindings(
        [
            GoRelayDomainBinding(
                id="bind-ct",
                account_id=account.id,
                entry_name="「Lv1」广东隧道「电信联通」",
                isp="ct",
                ip_version="ipv4",
                host_value="119.147.22.121",
                source="manual_import",
                status="approved",
                updated_at="2026-01-01T00:00:00Z",
            )
        ]
    )
    services.repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id=account.id,
                snapshot_id="snap-split",
                created_at="2026-01-01T00:00:00Z",
                node_count=0,
                device_count=0,
                status="success",
            ),
            collected_rules=[
                CollectedRule(
                    account_id=account.id,
                    rule_id="r-split",
                    device_name="Mac",
                    line_name="Mac",
                    entry_name="「Lv1」广东隧道「电信联通」",
                    isp="other",
                    ip_version="ipv4",
                    port=38658,
                    host="",
                    status="pending_domain",
                    raw={"line": "联系客服申请，已申请可忽略。"},
                )
            ],
            device_nodes={},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
        )
    )
    services.repo.save_gorelay_active_snapshot_id(account.id, "snap-split")

    pending = client.get(f"/api/gorelay/accounts/{account.id}/domain-bindings/pending")
    assert pending.status_code == 200
    bindings = pending.json()["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["isp"] == "ct"
    assert bindings[0]["ports"] == [38658]
    assert bindings[0]["devices"][0]["device_name"] == "Mac"

    entries = client.get(f"/api/gorelay/accounts/{account.id}/entries")
    assert entries.status_code == 200
    items = entries.json()["items"]
    assert len(items) == 1
    assert items[0]["isp"] == "ct"
    assert items[0]["host_value"] == "119.147.22.121"
    assert items[0]["resolved"] is True
    assert items[0]["devices"][0]["device_name"] == "Mac"


def test_delete_gorelay_source_deletes_fallback_account(client) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "Compat-Delete",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["item"]["id"]

    sources = client.get("/api/sources/gorelay")
    assert sources.status_code == 200
    assert any(item["id"] == account_id for item in sources.json()["items"])

    deleted = client.delete(f"/api/sources/gorelay/{account_id}")
    assert deleted.status_code == 200

    sources_after = client.get("/api/sources/gorelay")
    assert sources_after.status_code == 200
    assert not any(item["id"] == account_id for item in sources_after.json()["items"])

    accounts_after = client.get("/api/gorelay/accounts")
    assert accounts_after.status_code == 200
    assert not any(item["id"] == account_id for item in accounts_after.json()["items"])


def test_pull_reasons_are_stored_cleaned_on_read_and_cleared_by_success(diagnostic_client, monkeypatch) -> None:
    from app.services.source_fetcher import SourcePullAttempt, SourcePullResult

    client = diagnostic_client
    services = client.app.state.services
    source_id = "reason-codes"
    url = "https://h.example/sub?token=orchard9secret"
    services.repo.save_standard_source(StandardSource(id=source_id, name="Reasons", enabled=False, clash_url=url))
    outcome = {"ok": False}

    async def fetch(_source):
        if outcome["ok"]:
            return SourcePullResult(ok=True, method="clash", node_count=1, nodes=[
                NodeRecord("n", "n.example", 443, "trojan", password="p"),
            ])
        return SourcePullResult(ok=False, error="clash: HTTP 403 (clash, https://h.example/sub)", attempts=[
            SourcePullAttempt("clash", False, 0, error="HTTP 403 (clash, https://h.example/sub)", url="https://h.example/sub",
                              network_path="direct", code="http_status", message="HTTP 403"),
            SourcePullAttempt("clash", False, 0, error="HTTP 403 (clash, https://h.example/sub)", url="https://h.example/sub",
                              network_path="proxy", code="http_status", message="HTTP 403"),
            SourcePullAttempt("surge", False, 0, error="rejected orchard9secret (surge)", code="invalid_payload",
                              message="rejected orchard9secret"),
        ])

    monkeypatch.setattr(services.hub_service.source_fetcher, "fetch_source", fetch)
    expected = [
        {"method": "clash", "code": "http_status", "url": "https://h.example/sub", "message": "HTTP 403"},
        {"method": "surge", "code": "invalid_payload", "url": "", "message": "rejected <redacted>"},
    ]
    response = client.post(f"/api/sources/standard/{source_id}/pull")
    assert response.status_code == 200
    assert response.json()["item"]["last_pull_reasons"] == expected
    assert services.repo.get_standard_source(source_id).last_pull_reasons == expected
    listed = next(item for item in client.get("/api/sources/standard").json()["items"] if item["id"] == source_id)
    assert listed["last_pull_reasons"] == expected
    assert listed["last_pull_error"]  # Kept for readers of the summary text.
    assert client.get(f"/api/core/diagnose/source/{source_id}").json()["last_pull_reasons"] == expected
    assert "orchard9secret" not in _without_config_urls(client.get("/api/core/state").json())

    outcome["ok"] = True
    response = client.post(f"/api/sources/standard/{source_id}/pull")
    assert response.json()["item"]["last_pull_reasons"] == []
    assert services.repo.get_standard_source(source_id).last_pull_reasons == []


def test_failures_saved_without_reasons_read_as_one_unclassified_reason(diagnostic_client) -> None:
    client = diagnostic_client
    services = client.app.state.services
    services.repo.save_standard_source(StandardSource(id="legacy", name="Legacy", enabled=False, clash_url="https://h.example/c"))
    services.repo.save_standard_source_pull_status(
        "legacy", attempt_at="2026-01-01T00:00:00Z", ok=False, method="", node_count=0,
        error="clash: timeout (clash, https://h.example/c); clash: timeout (clash, https://h.example/c)", trigger="manual",
    )
    item = next(item for item in client.get("/api/sources/standard").json()["items"] if item["id"] == "legacy")
    assert item["last_pull_reasons"] == [
        {"method": "", "code": "unclassified", "url": "", "message": "clash: timeout (clash, https://h.example/c)"},
    ]
