from __future__ import annotations

import json
import os

import click
import httpx


def _base_url() -> str:
    return os.getenv("SUBHUB_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict[str, str]:
    user_id = os.getenv("SUBHUB_USER_ID", "").strip()
    cookie_header = os.getenv("LAZYCAT_COOKIE_HEADER", "").strip()
    headers = {"accept": "application/json"}
    if user_id:
        headers["X-HC-User-ID"] = user_id
    if cookie_header:
        headers["cookie"] = cookie_header
    return headers


def _request_response(method: str, path: str, payload: dict | None = None) -> httpx.Response:
    url = f"{_base_url()}{path}"
    with httpx.Client(timeout=30, trust_env=False) as client:
        response = client.request(method, url, headers=_headers(), json=payload)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        location = exc.response.headers.get("location", "")
        if exc.response.status_code in {301, 302, 303, 307, 308} and "/sys/login" in location:
            raise click.ClickException(
                "request was redirected to LazyCat login; refresh browser login, wait for CookieCloud sync, and retry with LAZYCAT_COOKIE_HEADER"
            ) from exc
        raise
    return response


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    return _request_response(method, path, payload=payload).json()


def _print_json(data: object) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _load_json_object(json_file: str) -> dict:
    with open(json_file, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise click.ClickException("JSON file must contain an object")
    return payload


def _core_state() -> dict:
    return _request("GET", "/api/core/state")


def _devices_payload() -> dict:
    return _request("GET", "/api/devices")


@click.group("get")
def get_group() -> None:
    """Read canonical SubHub state."""


@get_group.command("state")
def get_state() -> None:
    _print_json(_core_state())


@get_group.command("category")
@click.argument("name")
def get_category(name: str) -> None:
    state = _core_state()
    items = list((state.get("routing") or {}).get("categories") or [])
    item = next((entry for entry in items if str(entry.get("name") or "") == name), None)
    if item is None:
        raise click.ClickException("category not found")
    _print_json(item)


@get_group.command("source")
@click.argument("source_id")
def get_source(source_id: str) -> None:
    state = _core_state()
    standard = list((state.get("sources") or {}).get("standard") or [])
    gorelay = list((state.get("sources") or {}).get("gorelay") or [])
    item = next((entry for entry in [*standard, *gorelay] if str(entry.get("id") or "") == source_id), None)
    if item is None:
        raise click.ClickException("source not found")
    _print_json(item)


@get_group.command("devices")
def get_devices() -> None:
    _print_json(_devices_payload())


@get_group.command("device")
@click.argument("token")
def get_device(token: str) -> None:
    items = list((_devices_payload().get("items") or []))
    item = next((entry for entry in items if str(entry.get("token") or "") == token), None)
    if item is None:
        raise click.ClickException("device not found")
    _print_json(item)


@click.group("preview")
def preview_group() -> None:
    """Preview structured patch changes."""


@preview_group.command("patch")
@click.argument("patch_file", type=click.Path(exists=True, dir_okay=False, path_type=str))
def preview_patch(patch_file: str) -> None:
    _print_json(_request("POST", "/api/core/preview", _load_json_object(patch_file)))


@click.group("apply")
def apply_group() -> None:
    """Apply structured patch changes."""


@apply_group.command("patch")
@click.argument("patch_file", type=click.Path(exists=True, dir_okay=False, path_type=str))
def apply_patch(patch_file: str) -> None:
    _print_json(_request("POST", "/api/core/apply", _load_json_object(patch_file)))


@click.group("render")
def render_group() -> None:
    """Render device subscriptions."""


@render_group.command("device")
@click.argument("token")
@click.option("--target", type=click.Choice(["surge", "clash", "shadowrocket"]), required=True)
@click.option("--content", is_flag=True, default=False, help="Print raw subscription content")
def render_device(token: str, target: str, content: bool) -> None:
    if content:
        response = _request_response(
            "GET",
            f"/api/devices/{token}/preview-content?target={target}",
        )
        click.echo(response.text)
        return
    _print_json(
        _request(
            "GET",
            f"/api/devices/{token}/preview-summary?target={target}",
        )
    )


@click.group("explain")
def explain_group() -> None:
    """Explain routing decisions."""


@explain_group.command("domain")
@click.argument("domain")
@click.option("--device", "device_token", required=True)
def explain_domain(domain: str, device_token: str) -> None:
    _print_json(
        _request(
            "GET",
            f"/api/core/explain/domain?domain={domain}&device={device_token}",
        )
    )


@explain_group.command("category")
@click.argument("name")
@click.option("--device", "device_token", required=True)
def explain_category(name: str, device_token: str) -> None:
    _print_json(
        _request(
            "GET",
            f"/api/core/explain/category?name={name}&device={device_token}",
        )
    )


@click.group("diagnose")
def diagnose_group() -> None:
    """Inspect environment and source diagnostics."""


@diagnose_group.command("egress")
def diagnose_egress() -> None:
    _print_json(_request("GET", "/api/core/diagnose/egress"))


@diagnose_group.command("source")
@click.argument("source_id")
def diagnose_source(source_id: str) -> None:
    _print_json(_request("GET", f"/api/core/diagnose/source/{source_id}"))


@click.group("sync")
def sync_group() -> None:
    """Synchronize sources or rule catalogs."""


@sync_group.command("all")
@click.option("--rule-catalog-mode", type=click.Choice(["incremental", "full"]), default="incremental", show_default=True)
def sync_all(rule_catalog_mode: str) -> None:
    _print_json(_request("POST", "/api/core/sync", {"target": "all", "rule_catalog_mode": rule_catalog_mode}))


@sync_group.command("rules")
@click.option("--rule-catalog-mode", type=click.Choice(["incremental", "full"]), default="incremental", show_default=True)
def sync_rules(rule_catalog_mode: str) -> None:
    _print_json(_request("POST", "/api/core/sync", {"target": "rules", "rule_catalog_mode": rule_catalog_mode}))


@sync_group.command("source")
@click.argument("source_id")
def sync_source(source_id: str) -> None:
    _print_json(_request("POST", "/api/core/sync", {"target": "source", "source_id": source_id}))
