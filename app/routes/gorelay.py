from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.i18n import localize_gorelay_reason_text, resolve_locale
from app.models import DEVICE_STRATEGY_PRESETS, GoRelayAccount
from app.routes.url_resolver import resolve_base_url
from app.services.subscription_builder import build_device_import_links, resolve_preferred_surge_base_url
from app.services.tenant_registry import request_services

router = APIRouter(prefix="/api/gorelay", tags=["gorelay"])
_DEFAULT_SCENARIO_ID = "scenario-default"


def _services(request: Request):
    return request_services(request)


def _require_login_if_needed(request: Request) -> None:
    settings = _services(request).settings
    if not settings.manage_api_require_login:
        return
    user_id = str(getattr(request.state, "lazycat_user_id", "") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="lazycat login required")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _legacy_default_scenario_settings(services) -> dict[str, object]:
    default_scenario = services.repo.get_scenario(_DEFAULT_SCENARIO_ID)
    if default_scenario is None:
        return {}
    return dict(getattr(default_scenario, "settings", {}) or {})


def _normalize_json_object_text(raw: str, field_name: str) -> str:
    text = str(raw or "").strip() or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON object")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


class AccountPayload(BaseModel):
    name: str
    login_url: str
    rules_url: str = ""
    gorelay_username: str = ""
    gorelay_password: str = ""
    proxy_username_default: str = ""
    proxy_password_default: str = ""
    selectors_json: str = "{}"
    mcp_url: str = ""
    auth_header: str = ""
    login_tool: str = "auth_login"
    nodes_tool: str = "list_nodes"
    login_args_json: str = '{"username":"{username}","password":"{password}"}'
    nodes_args_json: str = "{}"
    enabled: bool = True


class AccountUpdatePayload(BaseModel):
    name: str | None = None
    login_url: str | None = None
    rules_url: str | None = None
    gorelay_username: str | None = None
    gorelay_password: str | None = None
    proxy_username_default: str | None = None
    proxy_password_default: str | None = None
    selectors_json: str | None = None
    mcp_url: str | None = None
    auth_header: str | None = None
    login_tool: str | None = None
    nodes_tool: str | None = None
    login_args_json: str | None = None
    nodes_args_json: str | None = None
    enabled: bool | None = None


class ProxyCredentialPayload(BaseModel):
    username: str = ""
    password: str = ""


class DeviceStrategyPresetPayload(BaseModel):
    strategy_preset: str


class DomainImportPayload(BaseModel):
    reply_text: str


class EntryMultiplierImportPayload(BaseModel):
    text: str


class DomainUpdatePayload(BaseModel):
    host_value: str
    status: str = "approved"


@router.get("/accounts")
async def list_accounts(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    items = [item.to_public_dict() for item in _services(request).gorelay_service.list_accounts()]
    return {"ok": True, "items": items}


@router.post("/accounts")
async def create_account(request: Request, payload: AccountPayload) -> dict[str, object]:
    _require_login_if_needed(request)
    selectors_text = _normalize_json_object_text(payload.selectors_json, "selectors_json")
    login_args_text = _normalize_json_object_text(payload.login_args_json, "login_args_json")
    nodes_args_text = _normalize_json_object_text(payload.nodes_args_json, "nodes_args_json")

    account = GoRelayAccount(
        id=uuid4().hex,
        name=payload.name.strip(),
        login_url=payload.login_url.strip(),
        rules_url=payload.rules_url.strip() or payload.login_url.strip(),
        gorelay_username=payload.gorelay_username.strip(),
        gorelay_password=payload.gorelay_password,
        proxy_username_default=payload.proxy_username_default.strip(),
        proxy_password_default=payload.proxy_password_default,
        selectors_json=selectors_text,
        mcp_url=payload.mcp_url.strip(),
        auth_header=payload.auth_header.strip(),
        login_tool=payload.login_tool.strip() or "auth_login",
        nodes_tool=payload.nodes_tool.strip() or "list_nodes",
        login_args_json=login_args_text,
        nodes_args_json=nodes_args_text,
        enabled=payload.enabled,
        updated_at=_now(),
    )
    _services(request).gorelay_service.save_account(account)
    return {"ok": True, "item": account.to_public_dict()}


@router.put("/accounts/{account_id}")
async def update_account(
    request: Request,
    account_id: str,
    payload: AccountUpdatePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    service = _services(request).gorelay_service
    target = service.get_account(account_id)
    if not target:
        raise HTTPException(status_code=404, detail="account not found")

    patch = payload.model_dump(exclude_unset=True)
    if "selectors_json" in patch:
        patch["selectors_json"] = _normalize_json_object_text(
            str(patch["selectors_json"] or "{}"), "selectors_json"
        )
    if "login_args_json" in patch:
        patch["login_args_json"] = _normalize_json_object_text(
            str(patch["login_args_json"] or "{}"), "login_args_json"
        )
    if "nodes_args_json" in patch:
        patch["nodes_args_json"] = _normalize_json_object_text(
            str(patch["nodes_args_json"] or "{}"), "nodes_args_json"
        )

    for key, value in patch.items():
        if isinstance(value, str):
            stripped = value.strip()
            if key in {"gorelay_password", "proxy_password_default", "auth_header"} and not stripped:
                continue
            if key == "login_tool":
                stripped = stripped or "auth_login"
            if key == "nodes_tool":
                stripped = stripped or "list_nodes"
            if key == "login_args_json":
                stripped = stripped or '{"username":"{username}","password":"{password}"}'
            if key == "nodes_args_json":
                stripped = stripped or "{}"
            setattr(target, key, stripped)
            continue
        setattr(target, key, value)

    target.updated_at = _now()
    service.save_account(target)
    return {"ok": True, "item": target.to_public_dict()}


@router.delete("/accounts/{account_id}")
async def delete_account(request: Request, account_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    _services(request).gorelay_service.delete_account(account_id)
    return {"ok": True}


@router.post("/accounts/{account_id}/crawl")
async def crawl_account(request: Request, account_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    service = services.gorelay_service
    if not service.get_account(account_id):
        raise HTTPException(status_code=404, detail="account not found")
    try:
        result = await service.crawl_account(account_id)
        result["device_sync"] = services.hub_service.sync_devices_from_gorelay_snapshots()
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/devices")
async def list_account_devices(
    request: Request,
    account_id: str,
    include_stale: bool = Query(default=False),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    locale = resolve_locale(request)
    account = services.gorelay_service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")

    base_url = resolve_base_url(request, services.settings.app_base_url)
    surge_base_url = resolve_preferred_surge_base_url(
        base_url,
        _legacy_default_scenario_settings(services),
    )
    items: list[dict[str, object]] = []
    for item in services.gorelay_service.list_account_device_views(account_id, include_stale=include_stale):
        subscription_id = str(item.get("public_id") or "")
        links = (
            build_device_import_links(
                base_url,
                f"{account.name}-{item['device_name']}",
                subscription_id,
                surge_base_url=surge_base_url,
            )
            if subscription_id
            else {
                "clash_url": "",
                "shadowrocket_url": "",
                "shadowrocket_nodes_url": "",
                "surge_url": "",
                "surge_mac_overlay_url": "",
                "clash_scheme": "",
                "shadowrocket_scheme": "",
                "surge_scheme": "",
                "surge_mac_overlay_scheme": "",
            }
        )
        links["sha_url"] = links.get("shadowrocket_nodes_url", "")
        links["sha_scheme"] = links.get("shadowrocket_scheme", "")
        row = dict(item)
        row.pop("token", None)
        row["subscription_id"] = subscription_id
        preview = dict(row.get("preview") or {})
        for client_name in ("clash", "shadowrocket", "surge"):
            client_preview = dict(preview.get(client_name) or {})
            if "reason_text" in client_preview:
                client_preview["reason_text"] = localize_gorelay_reason_text(
                    list(client_preview.get("reason_text") or []),
                    locale,
                )
                preview[client_name] = client_preview
        row["preview"] = preview
        row["links"] = links
        items.append(row)
    return {"ok": True, "items": items}


@router.put("/accounts/{account_id}/proxy-credentials")
async def update_account_proxy_credentials(
    request: Request,
    account_id: str,
    payload: ProxyCredentialPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        account = _services(request).gorelay_service.update_account_proxy_credentials(
            account_id,
            payload.username,
            payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "item": account.to_public_dict()}


@router.put("/accounts/{account_id}/devices/{device_key}/proxy-credentials")
async def update_device_proxy_credentials(
    request: Request,
    account_id: str,
    device_key: str,
    payload: ProxyCredentialPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        profile = _services(request).gorelay_service.update_device_proxy_credentials(
            account_id,
            device_key,
            payload.username,
            payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "item": profile.to_dict()}


@router.put("/accounts/{account_id}/devices/{device_key}/strategy-preset")
async def update_device_strategy_preset(
    request: Request,
    account_id: str,
    device_key: str,
    payload: DeviceStrategyPresetPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    preset = str(payload.strategy_preset or "").strip().lower()
    if preset not in DEVICE_STRATEGY_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"strategy_preset must be one of: {', '.join(DEVICE_STRATEGY_PRESETS)}",
        )
    try:
        profile = _services(request).gorelay_service.update_device_strategy_preset(
            account_id,
            device_key,
            preset,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 400 if "strategy_preset" in message else 404
        raise HTTPException(status_code=status_code, detail=message) from exc
    return {"ok": True, "item": profile.to_dict()}


@router.get("/accounts/{account_id}/domain-bindings/pending")
async def list_pending_domain_bindings(request: Request, account_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    service = _services(request).gorelay_service
    if not service.get_account(account_id):
        raise HTTPException(status_code=404, detail="account not found")
    entry_items = service.list_entry_usage(account_id)
    entry_index = {
        (str(item.get("entry_name", "")), str(item.get("isp", "")), str(item.get("ip_version", ""))): item
        for item in entry_items
    }
    pending = []
    for item in service.list_pending_bindings(account_id):
        key = (str(item.get("entry_name", "")), str(item.get("isp", "")), str(item.get("ip_version", "")))
        usage = entry_index.get(key, {})
        merged = dict(item)
        merged["ports"] = merged.get("ports") or usage.get("ports") or []
        merged["devices"] = usage.get("devices") or []
        pending.append(merged)

    bindings = []
    for raw in _services(request).repo.list_gorelay_domain_bindings(account_id):
        if str(raw.status).strip() != "approved":
            continue
        item = raw.to_dict()
        key = (item["entry_name"], item["isp"], item["ip_version"])
        usage = entry_index.get(key, {})
        item["ports"] = usage.get("ports") or []
        item["devices"] = usage.get("devices") or []
        bindings.append(item)
    return {
        "ok": True,
        "items": pending,
        "pending": pending,
        "bindings": bindings,
    }


@router.get("/accounts/{account_id}/entries")
async def list_entry_usage(request: Request, account_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    service = _services(request).gorelay_service
    if not service.get_account(account_id):
        raise HTTPException(status_code=404, detail="account not found")
    items = service.list_entry_usage(account_id)
    return {"ok": True, "items": items}


@router.get("/accounts/{account_id}/status")
async def account_status(request: Request, account_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return _services(request).gorelay_service.account_status(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/domain-bindings/import")
async def import_domain_bindings(
    request: Request,
    account_id: str,
    payload: DomainImportPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = await _services(request).gorelay_service.import_domain_bindings_from_text(
            account_id, payload.reply_text
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/accounts/{account_id}/entry-multipliers/import")
async def import_entry_multipliers(
    request: Request,
    account_id: str,
    payload: EntryMultiplierImportPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = await _services(request).gorelay_service.import_entry_multipliers_from_text(
            account_id,
            payload.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.put("/accounts/{account_id}/domain-bindings/{binding_id}")
async def update_domain_binding(
    request: Request,
    account_id: str,
    binding_id: str,
    payload: DomainUpdatePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        item = _services(request).gorelay_service.update_domain_binding(
            account_id,
            binding_id,
            payload.host_value,
            payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service = _services(request).gorelay_service
    try:
        rebuild = service.rebuild_account_from_latest_rules(account_id)
    except ValueError:
        rebuild = await service.crawl_account(account_id)
    return {"ok": True, "item": item.to_dict(), "rebuild": rebuild}


@router.get("/accounts/{account_id}/domain-import-histories")
async def list_domain_import_histories(
    request: Request,
    account_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    _require_login_if_needed(request)
    items = _services(request).gorelay_service.list_domain_import_histories(account_id, limit=limit)
    return {"ok": True, "items": [item.to_dict() for item in items]}


@router.delete("/accounts/{account_id}/domain-import-histories/{history_id}")
async def delete_domain_import_history(
    request: Request,
    account_id: str,
    history_id: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return await _services(request).gorelay_service.delete_domain_import_history(account_id, history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/snapshots")
async def list_snapshots(request: Request, account_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    service = _services(request).gorelay_service
    if not service.get_account(account_id):
        raise HTTPException(status_code=404, detail="account not found")
    active_id = _services(request).repo.load_gorelay_active_snapshot_id(account_id) or ""
    items = []
    for item in service.list_account_snapshots(account_id):
        payload = item.to_dict()
        payload["active"] = item.snapshot_id == active_id
        items.append(payload)
    return {"ok": True, "active_snapshot_id": active_id, "items": items}


@router.post("/accounts/{account_id}/snapshots/{snapshot_id}/activate")
async def activate_snapshot(
    request: Request,
    account_id: str,
    snapshot_id: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        _services(request).gorelay_service.activate_snapshot(account_id, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "account_id": account_id, "snapshot_id": snapshot_id}


@router.get("/subscriptions")
async def list_subscriptions(
    request: Request,
    account_id: str | None = Query(default=None),
    include_disabled: bool = Query(default=False),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    base_url = resolve_base_url(request, services.settings.app_base_url)
    surge_base_url = resolve_preferred_surge_base_url(
        base_url,
        _legacy_default_scenario_settings(services),
    )

    account_map = {item.id: item for item in services.gorelay_service.list_accounts()}
    items: list[dict[str, object]] = []
    for sub in services.gorelay_service.list_subscriptions(
        account_id=account_id,
        include_disabled=include_disabled,
    ):
        account = account_map.get(sub.account_id)
        display_name = f"{account.name}-{sub.device_name}" if account else sub.device_name
        row = sub.to_dict()
        row.pop("token", None)
        row["subscription_id"] = sub.public_id or sub.token
        links = build_device_import_links(
            base_url,
            display_name,
            row["subscription_id"],
            surge_base_url=surge_base_url,
        )
        links["sha_url"] = links.get("shadowrocket_nodes_url", "")
        links["sha_scheme"] = links.get("shadowrocket_scheme", "")
        row["links"] = links
        items.append(row)
    return {"ok": True, "items": items}


@router.post("/subscriptions/{subscription_id}/disable")
async def disable_subscription(request: Request, subscription_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    found = _services(request).gorelay_service.disable_subscription(subscription_id)
    if not found:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"ok": True}


@router.post("/refresh")
async def refresh_gorelay(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    service = _services(request).gorelay_service
    runtime = await service.refresh(force=True)
    summary = service.refresh_summary()
    response = {
        **summary,
        "last_refresh_at": runtime.last_refresh_at,
        "last_error": runtime.last_error,
        "accounts": runtime.account_status,
    }
    if response.get("ok") is False:
        return JSONResponse(status_code=502, content=response)
    return response
