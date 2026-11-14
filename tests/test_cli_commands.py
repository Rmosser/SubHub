from __future__ import annotations

import json

import httpx
from click.testing import CliRunner

from app.cli.main import cli


def test_cli_help_shows_new_core_commands() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "get" in result.output
    assert "preview" in result.output
    assert "apply" in result.output
    assert "render" in result.output
    assert "diagnose" in result.output
    assert "  sources" not in result.output
    assert "  rules" not in result.output
    assert "  categories" not in result.output
    assert "  llm" not in result.output


def test_get_help_shows_device_commands() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["get", "--help"])

    assert result.exit_code == 0
    assert "devices" in result.output
    assert "device" in result.output


def test_get_category_filters_core_state(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request(method: str, path: str, payload=None) -> dict:
        assert method == "GET"
        assert path == "/api/core/state"
        return {
            "schema": "subhub.state.v1",
            "routing": {
                "categories": [
                    {"name": "OpenAI", "assigned_group": "高质量-低倍率"},
                    {"name": "Bilibili", "assigned_group": "直连"},
                ]
            },
        }

    monkeypatch.setattr("app.cli.commands._request", _fake_request)

    result = runner.invoke(cli, ["get", "category", "OpenAI"])

    assert result.exit_code == 0
    assert '"name": "OpenAI"' in result.output
    assert '"assigned_group": "高质量-低倍率"' in result.output


def test_get_devices_reads_management_device_list(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request(method: str, path: str, payload=None) -> dict:
        assert method == "GET"
        assert path == "/api/devices"
        return {
            "ok": True,
            "items": [
                {"device_name": "Mac", "token": "tok-mac", "enabled": True, "links": {"clash": "https://example.com"}},
                {"device_name": "iPhone", "token": "tok-iphone", "enabled": False, "links": {}},
            ],
        }

    monkeypatch.setattr("app.cli.commands._request", _fake_request)

    result = runner.invoke(cli, ["get", "devices"])

    assert result.exit_code == 0
    assert '"device_name": "Mac"' in result.output
    assert '"token": "tok-mac"' in result.output


def test_get_device_filters_management_device_list(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request(method: str, path: str, payload=None) -> dict:
        assert method == "GET"
        assert path == "/api/devices"
        return {
            "ok": True,
            "items": [
                {"device_name": "Mac", "token": "tok-mac", "enabled": True, "links": {"clash": "https://example.com"}},
                {"device_name": "iPhone", "token": "tok-iphone", "enabled": False, "links": {}},
            ],
        }

    monkeypatch.setattr("app.cli.commands._request", _fake_request)

    result = runner.invoke(cli, ["get", "device", "tok-mac"])

    assert result.exit_code == 0
    assert '"device_name": "Mac"' in result.output
    assert '"token": "tok-mac"' in result.output
    assert '"iPhone"' not in result.output


def test_get_device_returns_clear_error_when_token_missing(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request(method: str, path: str, payload=None) -> dict:
        assert method == "GET"
        assert path == "/api/devices"
        return {"ok": True, "items": [{"device_name": "Mac", "token": "tok-mac", "enabled": True, "links": {}}]}

    monkeypatch.setattr("app.cli.commands._request", _fake_request)

    result = runner.invoke(cli, ["get", "device", "tok-missing"])

    assert result.exit_code != 0
    assert "device not found" in result.output


def test_preview_patch_posts_core_payload(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request(method: str, path: str, payload=None) -> dict:
        assert method == "POST"
        assert path == "/api/core/preview"
        assert payload == {
            "schema": "subhub.patch.v1",
            "actions": [
                {
                    "id": "codex-category",
                    "type": "ensure_manual_category",
                    "name": "Codex",
                    "default_policy": "group",
                    "default_group": "高质量-高倍率",
                    "locked": False,
                },
                {
                    "id": "codex-route",
                    "type": "set_category_route",
                    "category": "Codex",
                    "contract_id": "hq_premium",
                },
                {
                    "id": "codex-app-process",
                    "type": "add_category_rule",
                    "category": "Codex",
                    "rule_type": "PROCESS-NAME",
                    "value": "Codex",
                },
                {
                    "id": "codex-process",
                    "type": "add_category_rule",
                    "category": "Codex",
                    "rule_type": "PROCESS-NAME",
                    "value": "codex",
                },
                {
                    "id": "codex-helper-process",
                    "type": "add_category_rule",
                    "category": "Codex",
                    "rule_type": "PROCESS-NAME",
                    "value": "Codex Helper",
                }
            ],
        }
        return {"schema": "subhub.preview.v1", "ok": True, "changes": []}

    monkeypatch.setattr("app.cli.commands._request", _fake_request)

    with runner.isolated_filesystem():
        with open("patch.json", "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema": "subhub.patch.v1",
                    "actions": [
                        {
                            "id": "codex-category",
                            "type": "ensure_manual_category",
                            "name": "Codex",
                            "default_policy": "group",
                            "default_group": "高质量-高倍率",
                            "locked": False,
                        },
                        {
                            "id": "codex-route",
                            "type": "set_category_route",
                            "category": "Codex",
                            "contract_id": "hq_premium",
                        },
                        {
                            "id": "codex-app-process",
                            "type": "add_category_rule",
                            "category": "Codex",
                            "rule_type": "PROCESS-NAME",
                            "value": "Codex",
                        },
                        {
                            "id": "codex-process",
                            "type": "add_category_rule",
                            "category": "Codex",
                            "rule_type": "PROCESS-NAME",
                            "value": "codex",
                        },
                        {
                            "id": "codex-helper-process",
                            "type": "add_category_rule",
                            "category": "Codex",
                            "rule_type": "PROCESS-NAME",
                            "value": "Codex Helper",
                        },
                    ],
                },
                handle,
                ensure_ascii=False,
            )
        result = runner.invoke(cli, ["preview", "patch", "patch.json"])

    assert result.exit_code == 0
    assert '"schema": "subhub.preview.v1"' in result.output


def test_render_device_content_prints_raw_text(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request_response(method: str, path: str, payload=None) -> httpx.Response:
        assert method == "GET"
        assert path == "/api/devices/tok-cli/preview-content?target=clash"
        return httpx.Response(200, text="mixed-port: 7890\n")

    monkeypatch.setattr("app.cli.commands._request_response", _fake_request_response)

    result = runner.invoke(
        cli,
        ["render", "device", "tok-cli", "--target", "clash", "--content"],
    )

    assert result.exit_code == 0
    assert "mixed-port: 7890" in result.output


def test_render_device_requires_explicit_target() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["render", "device", "tok-cli"])

    assert result.exit_code != 0
    assert "Missing option '--target'" in result.output


def test_cli_headers_include_lazycat_cookie_when_present(monkeypatch) -> None:
    monkeypatch.setenv("SUBHUB_USER_ID", "user-123")
    monkeypatch.setenv("LAZYCAT_COOKIE_HEADER", "HC-Auth-Token=abc; lang=zh")

    from app.cli.commands import _headers

    assert _headers() == {
        "accept": "application/json",
        "X-HC-User-ID": "user-123",
        "cookie": "HC-Auth-Token=abc; lang=zh",
    }


def test_cli_requests_do_not_inherit_host_proxy_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def request(self, method: str, url: str, headers=None, json=None) -> httpx.Response:
            captured["request"] = {"method": method, "url": url, "headers": headers, "json": json}
            return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url, headers=headers, json=json))

    monkeypatch.setattr("app.cli.commands.httpx.Client", _FakeClient)

    from app.cli.commands import _request

    payload = _request("GET", "/api/devices")

    assert payload == {"ok": True}
    assert captured["kwargs"] == {"timeout": 30, "trust_env": False}
    assert captured["request"] == {
        "method": "GET",
        "url": "http://127.0.0.1:8000/api/devices",
        "headers": {"accept": "application/json"},
        "json": None,
    }


def test_cli_reports_lazycat_login_redirect_as_click_error(monkeypatch) -> None:
    request = httpx.Request("GET", "https://subhub.mybox.heiyu.space/api/devices")
    response = httpx.Response(
        307,
        headers={"location": "https://mybox.heiyu.space/sys/login?redirect=..."},
        request=request,
    )

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def request(self, method: str, url: str, headers=None, json=None) -> httpx.Response:
            return response

    monkeypatch.setattr("app.cli.commands.httpx.Client", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["get", "devices"])

    assert result.exit_code != 0
    assert "redirected to LazyCat login" in result.output


def test_sync_source_posts_core_sync(monkeypatch) -> None:
    runner = CliRunner()

    def _fake_request(method: str, path: str, payload=None) -> dict:
        assert method == "POST"
        assert path == "/api/core/sync"
        assert payload == {"target": "source", "source_id": "src-1"}
        return {"schema": "subhub.sync.v1", "ok": True}

    monkeypatch.setattr("app.cli.commands._request", _fake_request)

    result = runner.invoke(cli, ["sync", "source", "src-1"])

    assert result.exit_code == 0
    assert '"schema": "subhub.sync.v1"' in result.output
