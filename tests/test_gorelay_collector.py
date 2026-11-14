"""Tests for app.services.collectors.gorelay_api.GoRelayApiCollector.

Every HTTP call is replaced by a fake httpx.AsyncClient injected via
``client_factory``.  No real network I/O happens.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.models import CollectedRule, RelayAccount
from app.services.collectors.gorelay_api import (
    GoRelayApiCollector,
    _as_items,
    _join_url,
    _safe_int,
    _safe_port,
)


# ── tiny helpers ─────────────────────────────────────────────────────────────

def _settings(**overrides: Any) -> Settings:
    defaults = dict(
        app_name="test",
        app_base_url="http://localhost",
        storage_root="/tmp/test",
        refresh_interval_minutes=30,
        request_timeout_seconds=10,
        verify_tls=False,
        github_api_base="https://127.0.0.1/invalid",
        github_raw_base="https://127.0.0.1/invalid",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _account(**overrides: Any) -> RelayAccount:
    defaults = dict(
        id="acc1",
        name="TestAcct",
        login_url="https://gorelay.example.com/api/v1/auth/login",
        rules_url="https://gorelay.example.com/api/v1/user/forward",
        gorelay_username="user1",
        gorelay_password="pass1",
        selectors_json="{}",
    )
    defaults.update(overrides)
    return RelayAccount(**defaults)


class FakeResponse:
    """Minimal httpx.Response look-alike."""

    def __init__(self, status_code: int = 200, body: Any = None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            resp = httpx.Response(
                status_code=self.status_code,
                request=httpx.Request("GET", "http://test"),
            )
            raise httpx.HTTPStatusError(
                message=f"HTTP {self.status_code}",
                request=resp.request,
                response=resp,
            )


class FakeAsyncClient:
    """Records calls and returns canned responses per URL substring."""

    def __init__(self, routes: dict[str, FakeResponse | list[FakeResponse]] | None = None):
        self._routes: dict[str, FakeResponse | list[FakeResponse]] = routes or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._call_count: dict[str, int] = {}

    def _resolve(self, url: str) -> FakeResponse:
        for pattern, resp in self._routes.items():
            if pattern in url:
                count = self._call_count.get(pattern, 0)
                self._call_count[pattern] = count + 1
                if isinstance(resp, list):
                    idx = min(count, len(resp) - 1)
                    return resp[idx]
                return resp
        return FakeResponse(404, {"error": "not found"})

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self._resolve(url)

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self._resolve(url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any):
        pass


def _make_factory(client: FakeAsyncClient):
    """Returns a client_factory callable that yields the same fake client."""
    def _factory(**_kw: Any):
        return client  # FakeAsyncClient implements __aenter__/__aexit__
    return _factory


# ── static/utility method tests ──────────────────────────────────────────────


class TestStaticUtilities:
    def test_safe_int(self):
        assert _safe_int("42") == 42
        assert _safe_int("abc", 10) == 10
        assert _safe_int(None, 5) == 5

    def test_safe_port_valid(self):
        assert _safe_port(443) == 443
        assert _safe_port("8080") == 8080

    def test_safe_port_invalid(self):
        assert _safe_port(0) == 0
        assert _safe_port(70000) == 0
        assert _safe_port("abc") == 0

    def test_join_url_relative(self):
        assert _join_url("https://example.com", "/api/v1/login") == "https://example.com/api/v1/login"

    def test_join_url_absolute(self):
        assert _join_url("https://example.com", "https://other.com/path") == "https://other.com/path"

    def test_join_url_strips_trailing_slash(self):
        assert _join_url("https://example.com/", "/path") == "https://example.com/path"

    def test_as_items_list(self):
        assert _as_items([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_as_items_dict_with_list_key(self):
        assert _as_items({"list": [{"a": 1}]}) == [{"a": 1}]

    def test_as_items_empty(self):
        assert _as_items("string") == []
        assert _as_items(None) == []


class TestSelectorConfig:
    def test_valid_json(self):
        account = _account(selectors_json='{"page_size": 100}')
        config = GoRelayApiCollector._selector_config(account)
        assert config == {"page_size": 100}

    def test_invalid_json(self):
        account = _account(selectors_json="not json")
        config = GoRelayApiCollector._selector_config(account)
        assert config == {}

    def test_non_dict_json(self):
        account = _account(selectors_json='[1, 2]')
        config = GoRelayApiCollector._selector_config(account)
        assert config == {}


class TestBaseUrl:
    def test_from_selectors(self):
        url = GoRelayApiCollector._base_url(
            _account(),
            {"api_base": "https://relay.example.com/some/path"},
        )
        assert url == "https://relay.example.com"

    def test_from_login_url(self):
        url = GoRelayApiCollector._base_url(
            _account(login_url="https://login.example.com/api/v1/auth/login"),
            {},
        )
        assert url == "https://login.example.com"

    def test_raises_when_missing(self):
        account = _account(login_url="", rules_url="")
        with pytest.raises(RuntimeError, match="unable to infer"):
            GoRelayApiCollector._base_url(account, {})


class TestAuthCandidates:
    def test_raw_mode(self):
        candidates = GoRelayApiCollector._auth_candidates("tok123", "raw")
        assert len(candidates) == 1
        assert candidates[0][0] == "raw"
        assert candidates[0][1]["Authorization"] == "tok123"

    def test_bearer_mode(self):
        candidates = GoRelayApiCollector._auth_candidates("tok123", "bearer")
        assert len(candidates) == 1
        assert candidates[0][0] == "bearer"
        assert candidates[0][1]["Authorization"] == "Bearer tok123"

    def test_auto_mode(self):
        candidates = GoRelayApiCollector._auth_candidates("tok123", "auto")
        assert len(candidates) == 2
        assert candidates[0][0] == "raw"
        assert candidates[1][0] == "bearer"


class TestMergeHeaders:
    def test_basic_merge(self):
        merged = GoRelayApiCollector._merge_headers(
            {"Authorization": "tok"},
            {"X-Custom": "val"},
            allow_auth_override=False,
        )
        assert merged["Authorization"] == "tok"
        assert merged["X-Custom"] == "val"

    def test_blocks_auth_override(self):
        merged = GoRelayApiCollector._merge_headers(
            {"Authorization": "tok"},
            {"Authorization": "hacked", "token": "hacked"},
            allow_auth_override=False,
        )
        assert merged["Authorization"] == "tok"
        assert "token" not in merged

    def test_allows_auth_override(self):
        merged = GoRelayApiCollector._merge_headers(
            {"Authorization": "tok"},
            {"Authorization": "custom"},
            allow_auth_override=True,
        )
        assert merged["Authorization"] == "custom"


class TestExtractPortFromRange:
    def test_int_input(self):
        assert GoRelayApiCollector._extract_port_from_range(443) == 443

    def test_string_range(self):
        assert GoRelayApiCollector._extract_port_from_range("10000-20000") == 10000

    def test_empty(self):
        assert GoRelayApiCollector._extract_port_from_range("") == 0
        assert GoRelayApiCollector._extract_port_from_range(None) == 0


class TestExtractRulesPage:
    def test_data_as_list(self):
        payload = {"data": [{"id": 1}, {"id": 2}]}
        records, total = GoRelayApiCollector._extract_rules_page(payload)
        assert len(records) == 2
        assert total == 2

    def test_data_as_dict_with_list(self):
        payload = {"data": {"list": [{"id": 1}], "count": 10}}
        records, total = GoRelayApiCollector._extract_rules_page(payload)
        assert len(records) == 1
        assert total == 10

    def test_non_dict_payload(self):
        records, total = GoRelayApiCollector._extract_rules_page("invalid")
        assert records == []
        assert total == 0


class TestFormatTemplate:
    def test_string_substitution(self):
        result = GoRelayApiCollector._format_template(
            {"user": "{username}", "pass": "{password}"},
            {"username": "admin", "password": "secret"},
        )
        assert result == {"user": "admin", "pass": "secret"}

    def test_nested_list(self):
        result = GoRelayApiCollector._format_template(
            ["{username}", 42],
            {"username": "admin"},
        )
        assert result == ["admin", 42]


class TestPrepareDetailText:
    def test_empty_text_with_port(self):
        result = GoRelayApiCollector._prepare_detail_text("", 443)
        assert "端口: 443" in result

    def test_empty_text_no_port(self):
        result = GoRelayApiCollector._prepare_detail_text("", 0)
        assert result == ""

    def test_contact_replacement(self):
        result = GoRelayApiCollector._prepare_detail_text("需联系客服申请", 10443)
        assert "10443" in result

    def test_port_prepended(self):
        result = GoRelayApiCollector._prepare_detail_text("relay.example.com", 10443)
        assert result.startswith("端口: 10443")
        assert "relay.example.com" in result


class TestToText:
    def test_none(self):
        assert GoRelayApiCollector._to_text(None) == ""

    def test_string(self):
        assert GoRelayApiCollector._to_text("  hello  ") == "hello"

    def test_list(self):
        assert GoRelayApiCollector._to_text(["line1", None, "line2"]) == "line1\nline2"


# ── collect() integration tests ──────────────────────────────────────────────


class TestCollectFullFlow:
    def test_collect_uses_environment_proxy_client(self):
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-123"}),
            "devicegroup": FakeResponse(200, {"data": []}),
            "forward": FakeResponse(200, {"data": []}),
            "user/info": FakeResponse(200, {"data": {}}),
        })
        seen_kwargs: list[dict[str, Any]] = []

        def _factory(**kwargs: Any):
            seen_kwargs.append(dict(kwargs))
            return fake

        collector = GoRelayApiCollector(_settings(), client_factory=_factory)

        asyncio.run(collector.collect(_account()))

        assert seen_kwargs == [{"trust_env": True}]

    def test_happy_path(self):
        """Login -> device groups -> paginated forwards -> rules built."""
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-123"}),
            "devicegroup": FakeResponse(200, {
                "data": [
                    {
                        "id": "g1",
                        "name": "Group1",
                        "connect_host": "relay.example.com",
                        "connect_port": 10443,
                    }
                ],
            }),
            "forward": FakeResponse(200, {
                "data": {
                    "list": [
                        {
                            "id": "fwd1",
                            "line_name": "TestDevice-「IPLC-JP」",
                            "devicegroup_id": "g1",
                            "device_group_out": "out1",
                            "connect_host": "【电信 IPv4】relay-ct.example.com:10443\n【联通 IPv4】relay-cu.example.com:10443",
                            "listen_port": 10443,
                            "config": '{"dest":["z.i1j.net:36512"]}',
                        }
                    ],
                    "count": 1,
                },
            }),
            "user/info": FakeResponse(200, {
                "data": {
                    "plan_name": "Premium",
                    "traffic_used": 1000,
                    "traffic_enable": 10000,
                    "expire": 1735689600,
                },
            }),
        })

        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        account = _account()
        out_group = {
            "id": "out1",
            "name": "🌐香港出口ℹ️IPv4 + IPv6",
            "type": "DeviceGroupType_OutboundBySite",
            "ratio": "0",
        }
        fake._routes["devicegroup"] = FakeResponse(200, {"data": [{"id": "g1", "name": "Group1", "connect_host": "relay.example.com", "connect_port": 10443}, out_group]})
        rules, outbounds, status = asyncio.run(collector.collect(account))

        assert len(rules) >= 1
        assert len(outbounds) == 1
        assert outbounds[0].outbound_group_name == "🌐香港出口ℹ️IPv4 + IPv6"
        assert outbounds[0].targets == ["z.i1j.net:36512"]
        assert status["collector"] == "api"
        assert status["auth_mode_used"] == "raw"
        assert status["counts"]["forward_records"] == 1
        assert status["counts"]["outbounds"] == 1
        for rule in rules:
            assert rule.account_id == "acc1"

    def test_login_failure_raises(self):
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(401, {"error": "bad creds"}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        with pytest.raises(RuntimeError, match="GoRelay login failed: HTTP 401: bad creds"):
            asyncio.run(collector.collect(_account()))

    def test_login_failure_prefers_msg_field(self):
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(400, {"code": 400, "msg": "Password长度不能超过64个字符"}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        with pytest.raises(
            RuntimeError,
            match="GoRelay login failed: HTTP 400: Password长度不能超过64个字符",
        ):
            asyncio.run(collector.collect(_account()))

    def test_401_retry_with_auto_auth(self):
        """When auth_mode=auto and first attempt gets 401, try bearer.

        The first auth attempt (raw) fails at devicegroup with 401, so forward
        and userinfo are never called during that attempt.  On the second
        attempt (bearer), devicegroup is call #2 (200), and forward/userinfo
        are each called for the first time (must return 200).
        """
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-abc"}),
            # First call (raw attempt) -> 401; second call (bearer) -> 200.
            "devicegroup": [
                FakeResponse(401),
                FakeResponse(200, {"data": []}),
            ],
            # Only called once (during the bearer attempt), must succeed.
            "forward": FakeResponse(200, {"data": []}),
            "user/info": FakeResponse(200, {"data": {}}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        account = _account(selectors_json='{"api_auth_mode": "auto"}')
        rules, outbounds, status = asyncio.run(collector.collect(account))

        assert status["auth_mode_used"] == "bearer"
        assert rules == []
        assert outbounds == []

    def test_pagination(self):
        """When first page returns page_size records and total > page_size, fetches page 2."""
        page1_records = [
            {
                "id": f"fwd{i}",
                "line_name": f"Dev-「Entry{i}」",
                "connect_host": f"relay{i}.example.com:10443",
                "listen_port": 10443,
            }
            for i in range(3)
        ]
        page2_records = [
            {
                "id": "fwd3",
                "line_name": "Dev-「Entry3」",
                "connect_host": "relay3.example.com:10443",
                "listen_port": 10443,
            }
        ]

        responses: list[FakeResponse] = [
            FakeResponse(200, {"data": {"list": page1_records, "count": 4}}),
            FakeResponse(200, {"data": {"list": page2_records, "count": 4}}),
        ]

        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-123"}),
            "devicegroup": FakeResponse(200, {"data": []}),
            "forward": responses,
            "user/info": FakeResponse(200, {"data": {}}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        account = _account(selectors_json='{"page_size": 3}')
        rules, outbounds, status = asyncio.run(collector.collect(account))

        assert status["counts"]["forward_records"] == 4
        assert status["counts"]["forward_pages"] == 2
        assert outbounds == []

    def test_empty_forwards(self):
        """When no forward records exist, returns empty rules."""
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-123"}),
            "devicegroup": FakeResponse(200, {"data": []}),
            "forward": FakeResponse(200, {"data": {"list": [], "count": 0}}),
            "user/info": FakeResponse(200, {"data": {}}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        rules, outbounds, status = asyncio.run(collector.collect(_account()))
        assert rules == []
        assert outbounds == []
        assert status["counts"]["rules"] == 0

    def test_userinfo_failure_non_fatal(self):
        """User info fetch failure should not break node collection."""
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-123"}),
            "devicegroup": FakeResponse(200, {"data": []}),
            "forward": FakeResponse(200, {
                "data": {
                    "list": [
                        {
                            "id": "fwd1",
                            "line_name": "Dev-「Entry」",
                            "connect_host": "relay.example.com:443",
                            "listen_port": 443,
                        }
                    ],
                    "count": 1,
                },
            }),
            "user/info": FakeResponse(500, {"error": "internal error"}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        rules, outbounds, status = asyncio.run(collector.collect(_account()))
        assert len(rules) >= 1
        assert outbounds == []
        assert "userinfo_error" in status

    def test_login_token_missing_raises(self):
        """Login that returns non-string data should raise."""
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": 12345}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        with pytest.raises(RuntimeError, match="missing token"):
            asyncio.run(collector.collect(_account()))

    def test_device_group_enrichment(self):
        """Forward records that reference a device group should get connect_host from group."""
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-123"}),
            "devicegroup": FakeResponse(200, {
                "data": [
                    {
                        "id": "g1",
                        "name": "Group1",
                        "connect_host": "【电信 IPv4】group-relay.example.com:10443",
                        "connect_port": 10443,
                    }
                ],
            }),
            "forward": FakeResponse(200, {
                "data": {
                    "list": [
                        {
                            "id": "fwd1",
                            "line_name": "Dev-「Entry1」",
                            "devicegroup_id": "g1",
                            "connect_host": None,
                            "listen_port": 10443,
                        }
                    ],
                    "count": 1,
                },
            }),
            "user/info": FakeResponse(200, {"data": {}}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))
        rules, _, _ = asyncio.run(collector.collect(_account()))
        assert len(rules) >= 1
        ready = [r for r in rules if r.status == "ready"]
        assert len(ready) >= 1
        assert ready[0].host == "group-relay.example.com"

    def test_custom_login_payload_template(self):
        """Custom api_login_payload template should be formatted and used."""
        fake = FakeAsyncClient({
            "auth/login": FakeResponse(200, {"data": "tok-custom"}),
            "devicegroup": FakeResponse(200, {"data": []}),
            "forward": FakeResponse(200, {"data": []}),
            "user/info": FakeResponse(200, {"data": {}}),
        })
        settings = _settings()
        collector = GoRelayApiCollector(settings, client_factory=_make_factory(fake))

        selectors = {
            "api_login_payload": {
                "email": "{username}",
                "pwd": "{password}",
            }
        }
        account = _account(selectors_json=json.dumps(selectors))
        rules, outbounds, status = asyncio.run(collector.collect(account, selectors=selectors))

        login_calls = [c for c in fake.calls if c[0] == "POST" and "login" in c[1]]
        assert len(login_calls) == 1
        assert login_calls[0][2]["json"]["email"] == "user1"
        assert login_calls[0][2]["json"]["pwd"] == "pass1"
        assert outbounds == []


class TestBuildRules:
    """Test _build_rules with pre-built forward records."""

    def test_skips_items_without_line_name(self):
        settings = _settings()
        collector = GoRelayApiCollector(settings)
        account = _account()
        forwards = [{"connect_host": "relay.example.com:443"}]
        rules = collector._build_rules(account, forwards, {}, {})
        assert rules == []

    def test_skips_items_without_detail_text(self):
        settings = _settings()
        collector = GoRelayApiCollector(settings)
        account = _account()
        forwards = [{"line_name": "Dev-Entry", "connect_host": "", "listen_port": 0}]
        rules = collector._build_rules(account, forwards, {}, {})
        assert rules == []


class TestExtractQuota:
    def test_normal(self):
        info = {
            "plan_name": "Premium",
            "traffic_used": 5000,
            "traffic_enable": 10000,
            "expire": 1735689600,
            "group_name": "VIP",
        }
        quota = GoRelayApiCollector._extract_quota(info)
        assert quota["plan_name"] == "Premium"
        assert quota["traffic_remaining"] == 5000
        assert quota["expire"] == 1735689600

    def test_empty(self):
        quota = GoRelayApiCollector._extract_quota({})
        assert quota["plan_name"] == ""
        assert quota["traffic_remaining"] == 0
