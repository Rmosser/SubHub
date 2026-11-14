from __future__ import annotations

import inspect
import base64
import hashlib
from datetime import datetime, timezone
from typing import Mapping
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from app.routes.url_resolver import resolve_base_url
from app.services.render_environment import capture_local_host_aliases
from app.services.export_artifacts import ascii_filename
from app.services.lazycat_profile import (
    LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY,
    normalize_lazycat_profile_settings,
)
from app.services.subscription_ids import verify_subscription_asset_signature
from app.services.subscription_builder import (
    build_clash_blocked_detail,
    build_clash_profile_artifacts,
    build_clash_provider_config,
    build_clash_rule_provider_config,
    build_subscription_download_name,
    build_surge_profile_artifacts,
    build_surge_mac_overlay,
    build_shadowrocket_profile_artifacts,
    shadowrocket_config_filename,
    build_shadowrocket_nodes_subscription,
    resolve_preferred_surge_base_url,
    resolve_clash_provider_quality_group,
    surge_blocked_detail,
)
from app.services.subscription_urls import build_signed_subscription_asset_url
from app.services.tenant_registry import request_services

router = APIRouter(tags=["subscription"])

# Preserve the historical route-level name so tests and callers that monkeypatch
# app.routes.subscription.build_clash_config keep working.
build_clash_config = build_clash_profile_artifacts


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _services(request: Request):
    return request_services(request)


def _resolve_subscription_or_error(services, subscription_id: str):
    sub = services.hub_service.get_subscription_by_public_id(subscription_id)
    if sub is None:
        sub = services.hub_service.get_subscription(subscription_id)
    if sub:
        return sub
    gorelay_sub = services.gorelay_service.get_subscription_by_public_id(subscription_id)
    if gorelay_sub is None:
        gorelay_sub = services.gorelay_service.get_subscription_by_token(subscription_id)
    if gorelay_sub:
        return gorelay_sub
    raise HTTPException(status_code=403, detail="invalid or disabled subscription id")


def _resolve_internal_token_or_error(services, subscription_id: str) -> str:
    return str(_resolve_subscription_or_error(services, subscription_id).token or "").strip()


def _resolve_public_subscription_id(services, subscription_id: str) -> str:
    sub = _resolve_subscription_or_error(services, subscription_id)
    return str(getattr(sub, "public_id", "") or subscription_id or "").strip() or subscription_id


def _resolve_subscription_device_name(services, subscription_id: str) -> str:
    try:
        sub = _resolve_subscription_or_error(services, subscription_id)
    except HTTPException:
        return "SubHub"
    if sub:
        return str(sub.device_name or "").strip() or "SubHub"
    return "SubHub"


def _resolve_scenario_by_slug(request: Request, scenario_slug: str):
    scenario = _services(request).repo.get_scenario_by_slug(scenario_slug)
    if not scenario or not scenario.enabled:
        raise HTTPException(status_code=404, detail="scenario not found")
    return scenario


def _scenario_profile_settings(request: Request, scenario) -> dict[str, object]:
    return normalize_lazycat_profile_settings(getattr(scenario, "settings", {}) or {})


def _reject_removed_profile_query_params(request: Request) -> None:
    if "profile" in request.query_params or "flavor" in request.query_params:
        raise HTTPException(status_code=400, detail="profile/flavor query parameters are no longer supported")


def _device_blocked_detail(detail: Mapping[str, object]) -> dict[str, object]:
    """Return the 409 body that anonymous device endpoints may expose.

    Intent diagnostics are documented as management-only. The builders put
    them into the same warning list as the existing diagnostics, so remove
    them here; the 409 body then matches the established device contract.
    Authenticated management routes keep using the full detail.
    """
    device_detail = dict(detail)
    device_warnings = []
    for warning in detail.get("warnings") or []:
        code = str(warning.get("code") or "")
        if code.startswith("intent-"):
            continue
        device_warnings.append(warning)
    device_detail["warnings"] = device_warnings
    return device_detail


def _scenario_managed_url(
    request: Request,
    *,
    subscription_id: str,
    scenario_slug: str,
    suffix: str,
    profile_settings: Mapping[str, object] | None = None,
) -> str:
    base = resolve_base_url(request, _services(request).settings.app_base_url)
    if suffix.startswith("surge"):
        base = resolve_preferred_surge_base_url(base, profile_settings)
    return f"{base}/sub/device/{subscription_id}/{scenario_slug}/{suffix}"


def _signed_asset_url_builder(
    request: Request,
    *,
    subscription_id: str,
    scenario_slug: str,
    revision: str,
    profile_settings: Mapping[str, object] | None = None,
):
    services = _services(request)
    base = resolve_base_url(request, services.settings.app_base_url)
    base = resolve_preferred_surge_base_url(base, profile_settings)

    def _builder(kind: str, asset_key: str) -> str:
        return build_signed_subscription_asset_url(
            services.settings,
            base_url=base,
            public_id=subscription_id,
            scenario_slug=scenario_slug,
            kind=kind,
            asset_key=asset_key,
            revision=revision,
        )

    return _builder


def _signed_clash_provider_url_builder(
    request: Request,
    *,
    subscription_id: str,
    scenario_slug: str,
):
    services = _services(request)
    base = resolve_base_url(request, services.settings.app_base_url)

    def _builder(provider_key: str, revision: str) -> str:
        return build_signed_subscription_asset_url(
            services.settings,
            base_url=base,
            public_id=subscription_id,
            scenario_slug=scenario_slug,
            kind="clash-provider",
            asset_key=provider_key,
            revision=revision,
        )

    return _builder


def _signed_clash_rule_provider_url_builder(
    request: Request,
    *,
    subscription_id: str,
    scenario_slug: str,
):
    services = _services(request)
    base = resolve_base_url(request, services.settings.app_base_url)

    def _builder(asset_key: str, revision: str) -> str:
        return build_signed_subscription_asset_url(
            services.settings,
            base_url=base,
            public_id=subscription_id,
            scenario_slug=scenario_slug,
            kind="clash-rule-provider",
            asset_key=asset_key,
            revision=revision,
        )

    return _builder


def _validate_asset_signature(
    request: Request,
    *,
    subscription_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
    expires_at: int,
    signature: str,
) -> None:
    if not expires_at and not signature:
        return
    if not expires_at or not signature:
        raise HTTPException(status_code=403, detail="missing asset signature")
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if int(expires_at) < now_ts:
        raise HTTPException(status_code=403, detail="expired asset signature")
    if not verify_subscription_asset_signature(
        _services(request).settings,
        public_id=subscription_id,
        scenario_slug=scenario_slug,
        kind=kind,
        asset_key=asset_key,
        revision=revision,
        expires_at=int(expires_at),
        signature=signature,
    ):
        raise HTTPException(status_code=403, detail="invalid asset signature")


def _validate_surge_asset_signature_best_effort(
    request: Request,
    *,
    subscription_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
    expires_at: int,
    signature: str,
) -> None:
    try:
        _validate_asset_signature(
            request,
            subscription_id=subscription_id,
            scenario_slug=scenario_slug,
            kind=kind,
            asset_key=asset_key,
            revision=revision,
            expires_at=expires_at,
            signature=signature,
        )
    except HTTPException as exc:
        # Surge auto-refreshes cached external resources aggressively. These
        # asset paths are already reachable via the tokenized URL without a
        # signature, so stale signed query params should not degrade into
        # repeated 403 popups for the user.
        if exc.status_code == 403 and str(exc.detail or "") in {
            "missing asset signature",
            "expired asset signature",
            "invalid asset signature",
        }:
            return
        raise


async def _refresh_hub_for_subscription(hub) -> None:
    params = inspect.signature(hub.refresh).parameters
    if "force_rule_catalog" in params:
        await hub.refresh(force=False, force_rule_catalog=False)
        return
    await hub.refresh(force=False)


def _artifact_headers(
    entry,
    *,
    extra: dict[str, str] | None = None,
    cache_state: str,
) -> dict[str, str]:
    headers = {
        **_NO_CACHE_HEADERS,
        "ETag": entry.etag,
        "Last-Modified": entry.last_modified,
        "X-Artifact-Revision": entry.revision,
        "X-Artifact-Cache": cache_state,
    }
    if extra:
        headers.update(extra)
    return headers


def _not_modified_if_matched(
    request: Request,
    entry,
    *,
    extra: dict[str, str] | None = None,
    cache_state: str,
) -> Response | None:
    if_none_match = str(request.headers.get("if-none-match", "") or "").strip()
    if if_none_match and if_none_match == entry.etag:
        return Response(
            status_code=304,
            headers=_artifact_headers(entry, extra=extra, cache_state=cache_state),
        )
    return None


def _surge_subscription_headers(
    *,
    revision: str,
    metadata: dict[str, object],
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        **_NO_CACHE_HEADERS,
        "X-Artifact-Revision": str(revision or "").strip(),
        "X-Subscription-Base-Url": str(metadata.get("base_url", "") or "").strip(),
        "X-Surge-Managed-Url": str(metadata.get("managed_url", "") or "").strip(),
        "X-Surge-Domain-Set-Count": str(int(metadata.get("domain_set_count", 0) or 0)),
        "X-Surge-Rule-Set-Count": str(int(metadata.get("rule_set_count", 0) or 0)),
    }
    if extra:
        headers.update(extra)
    return headers


def _get_cached_surge_artifacts(
    request: Request,
    *,
    internal_token: str,
    subscription_id: str,
    scenario,
    policy_entry,
):
    services = _services(request)
    hub = services.hub_service
    profile_settings = _scenario_profile_settings(request, scenario)
    managed_url = _scenario_managed_url(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        suffix="surge.conf",
        profile_settings=profile_settings,
    )
    variant = f"{scenario.id}|{managed_url}"
    artifact = hub.get_cached_artifact(
        kind="surge-profile-artifacts",
        token=internal_token,
        revision=policy_entry.revision,
        variant=variant,
    )
    cache_state = "hit"
    if artifact is None:
        built = build_surge_profile_artifacts(
            policy_entry.nodes,
            list(policy_entry.policy_ir.rule_lines),
            managed_url,
            local_host_aliases=frozenset(capture_local_host_aliases()),
            profile="lazycat",
            profile_settings=profile_settings,
            policy_ir=policy_entry.policy_ir,
            revision=policy_entry.revision,
            asset_url_builder=_signed_asset_url_builder(
                request,
                subscription_id=subscription_id,
                scenario_slug=scenario.slug,
                revision=policy_entry.revision,
                profile_settings=profile_settings,
            ),
        )
        artifact = hub.store_cached_artifact(
            kind="surge-profile-artifacts",
            token=internal_token,
            revision=policy_entry.revision,
            variant=variant,
            value=built,
        )
        cache_state = "miss"
    return artifact.value, cache_state


@router.get("/sub/clash.yaml", response_class=PlainTextResponse)
async def legacy_sub_clash(request: Request, token: str = Query(...)) -> PlainTextResponse:
    return await sub_clash(request, token)


@router.get("/sub/shadowrocket.conf", response_class=PlainTextResponse)
async def legacy_sub_shadowrocket(request: Request, token: str = Query(...)) -> PlainTextResponse:
    return await sub_shadowrocket(request, token)


@router.get("/sub/device/{token}/clash.yaml", response_class=PlainTextResponse)
async def sub_clash(
    request: Request,
    token: str,
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    return await sub_clash_scenario(request, token, "default")


@router.get("/sub/device/{token}/clash/providers/{provider_key}.yaml", response_class=PlainTextResponse)
async def sub_clash_provider(
    request: Request,
    token: str,
    provider_key: str,
) -> PlainTextResponse:
    return await sub_clash_provider_scenario(request, token, "default", provider_key)


@router.get("/sub/device/{token}/clash/rules/{asset_key}.list", response_class=PlainTextResponse)
async def sub_clash_rule_provider(
    request: Request,
    token: str,
    asset_key: str,
) -> PlainTextResponse:
    return await sub_clash_rule_provider_scenario(request, token, "default", asset_key)


async def sub_shadowrocket_named(request: Request, token: str, config_id: str) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    subscription_id = _resolve_public_subscription_id(_services(request), token)
    if f"shadowrocket-{config_id}.conf" != shadowrocket_config_filename(subscription_id):
        raise HTTPException(status_code=404, detail="configuration filename not found")
    return await sub_shadowrocket_scenario(request, token, "default")


@router.get("/sub/device/{token}/shadowrocket.conf", response_class=PlainTextResponse)
async def sub_shadowrocket(
    request: Request,
    token: str,
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    return await sub_shadowrocket_scenario(request, token, "default")


@router.get("/sub/device/{token}/shadowrocket-nodes.txt", response_class=PlainTextResponse)
async def sub_shadowrocket_nodes(
    request: Request,
    token: str,
) -> PlainTextResponse:
    return await sub_shadowrocket_nodes_scenario(request, token, "default")


@router.get("/sub/device/{token}/shadowrocket-legacy.conf", response_class=RedirectResponse)
async def sub_shadowrocket_legacy(
    request: Request,
    token: str,
) -> RedirectResponse:
    _reject_removed_profile_query_params(request)
    return RedirectResponse(
        url=f"/sub/device/{token}/shadowrocket.conf",
        status_code=308,
    )


@router.get("/sub/device/{token}/surge.conf", response_class=PlainTextResponse)
async def sub_surge(
    request: Request,
    token: str,
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    return await sub_surge_scenario(request, token, "default")


@router.get("/sub/device/{token}/surge/domain-set/{asset_key}.txt", response_class=PlainTextResponse)
async def sub_surge_domain_set(
    request: Request,
    token: str,
    asset_key: str,
) -> PlainTextResponse:
    return await sub_surge_domain_set_scenario(request, token, "default", asset_key)


@router.get("/sub/device/{token}/surge/rule-set/{asset_key}.list", response_class=PlainTextResponse)
async def sub_surge_rule_set(
    request: Request,
    token: str,
    asset_key: str,
) -> PlainTextResponse:
    return await sub_surge_rule_set_scenario(request, token, "default", asset_key)


@router.get("/sub/device/{token}/surge-mac-overlay.conf", response_class=PlainTextResponse)
async def sub_surge_mac_overlay(
    request: Request,
    token: str,
) -> PlainTextResponse:
    return await sub_surge_mac_overlay_scenario(request, token, "default")


@router.get("/sub/device/{token}/{scenario_slug}/clash.yaml", response_class=PlainTextResponse)
async def sub_clash_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    nodes = policy_entry.nodes
    policy_ir = policy_entry.policy_ir
    base = resolve_base_url(request, services.settings.app_base_url)
    profile_settings = _scenario_profile_settings(request, scenario)
    provider_url_builder = _signed_clash_provider_url_builder(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
    )
    rule_provider_url_builder = _signed_clash_rule_provider_url_builder(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
    )
    variant = f"{scenario.id}|{base}"
    artifact = hub.get_cached_artifact(
        kind="clash-config",
        token=internal_token,
        revision=policy_entry.revision,
        variant=variant,
    )
    cache_state = "hit"
    if artifact is None:
        content, _, rendered_warnings = build_clash_config(
            nodes,
            list(policy_ir.rule_lines),
            local_host_aliases=frozenset(capture_local_host_aliases()),
            profile="lazycat",
            profile_settings=profile_settings,
            policy_ir=policy_ir,
            provider_base_url=base,
            subscription_token=internal_token,
            subscription_public_id=subscription_id,
            provider_url_builder=provider_url_builder,
            rule_provider_url_builder=rule_provider_url_builder,
        )
        blocked_detail = build_clash_blocked_detail(
            policy_ir,
            profile="lazycat",
            profile_settings=profile_settings,
            provider_base_url=base,
            subscription_token=internal_token,
            subscription_public_id=subscription_id,
            provider_url_builder=provider_url_builder,
            rendered_content=content,
            rendered_warnings=rendered_warnings,
        )
        if blocked_detail["blockers"]:
            raise HTTPException(status_code=409, detail=_device_blocked_detail(blocked_detail))
        artifact = hub.store_cached_artifact(
            kind="clash-config",
            token=internal_token,
            revision=policy_entry.revision,
            variant=variant,
            value=content,
        )
        cache_state = "miss"
    else:
        content = str(artifact.value)
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    filename = ascii_filename(
        build_subscription_download_name(f"{_resolve_subscription_device_name(services, subscription_id)}-{scenario.slug}"),
        ".yaml",
    )
    extra_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "profile-title": "base64:" + base64.b64encode(f"SubHub · 场景 {hashlib.sha256(scenario.id.encode()).hexdigest()[:8]}".encode("utf-8")).decode("ascii"),
        "Profile-Update-Interval": "1800",
    }
    not_modified = _not_modified_if_matched(request, artifact, extra=extra_headers, cache_state=cache_state)
    if not_modified is not None:
        return not_modified
    return PlainTextResponse(
        content,
        media_type="application/x-yaml",
        headers=_artifact_headers(artifact, extra=extra_headers, cache_state=cache_state),
    )


@router.get("/sub/device/{token}/{scenario_slug}/clash/providers/{provider_key}.yaml", response_class=PlainTextResponse)
async def sub_clash_provider_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
    provider_key: str,
    rev: str = Query(default=""),
    exp: int = Query(default=0),
    sig: str = Query(default=""),
) -> PlainTextResponse:
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    if resolve_clash_provider_quality_group(provider_key) is None:
        raise HTTPException(status_code=404, detail="invalid clash provider key")
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    _validate_asset_signature(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        kind="clash-provider",
        asset_key=provider_key,
        revision=str(rev or policy_entry.revision),
        expires_at=exp,
        signature=sig,
    )
    profile_settings = _scenario_profile_settings(request, scenario)
    udp_default_enabled = bool(profile_settings[LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY])
    variant = f"{scenario.id}|{provider_key}|udp={int(udp_default_enabled)}"
    artifact = hub.get_cached_artifact(
        kind="clash-provider",
        token=internal_token,
        revision=policy_entry.revision,
        variant=variant,
    )
    cache_state = "hit"
    if artifact is None:
        content, _ = build_clash_provider_config(
            policy_entry.nodes,
            provider_key,
            policy_ir=policy_entry.policy_ir,
            udp_default_enabled=udp_default_enabled,
        )
        artifact = hub.store_cached_artifact(
            kind="clash-provider",
            token=internal_token,
            revision=policy_entry.revision,
            variant=variant,
            value=content,
        )
        cache_state = "miss"
    else:
        content = str(artifact.value)
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    not_modified = _not_modified_if_matched(request, artifact, cache_state=cache_state)
    if not_modified is not None:
        return not_modified
    return PlainTextResponse(
        content,
        media_type="application/x-yaml",
        headers=_artifact_headers(artifact, cache_state=cache_state),
    )


@router.get("/sub/device/{token}/{scenario_slug}/clash/rules/{asset_key}.list", response_class=PlainTextResponse)
async def sub_clash_rule_provider_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
    asset_key: str,
    rev: str = Query(default=""),
    exp: int = Query(default=0),
    sig: str = Query(default=""),
) -> PlainTextResponse:
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    _validate_asset_signature(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        kind="clash-rule-provider",
        asset_key=asset_key,
        revision=str(rev or policy_entry.revision),
        expires_at=exp,
        signature=sig,
    )
    variant = f"{scenario.id}|{asset_key}|rule-provider"
    artifact = hub.get_cached_artifact(
        kind="clash-rule-provider",
        token=internal_token,
        revision=policy_entry.revision,
        variant=variant,
    )
    cache_state = "hit"
    if artifact is None:
        content = build_clash_rule_provider_config(
            policy_entry.nodes,
            list(policy_entry.policy_ir.rule_lines),
            asset_key,
            policy_ir=policy_entry.policy_ir,
            profile="lazycat",
            profile_settings=_scenario_profile_settings(request, scenario),
        )
        artifact = hub.store_cached_artifact(
            kind="clash-rule-provider",
            token=internal_token,
            revision=policy_entry.revision,
            variant=variant,
            value=content,
        )
        cache_state = "miss"
    else:
        content = str(artifact.value)
    if not content.strip():
        raise HTTPException(status_code=404, detail="clash rule-provider asset not found")
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    not_modified = _not_modified_if_matched(request, artifact, cache_state=cache_state)
    if not_modified is not None:
        return not_modified
    return PlainTextResponse(
        content,
        headers=_artifact_headers(artifact, cache_state=cache_state),
    )


@router.get("/sub/device/{token}/{scenario_slug}/shadowrocket.conf", response_class=PlainTextResponse)
async def sub_shadowrocket_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
) -> PlainTextResponse:
    return await _render_shadowrocket_scenario(request, token, scenario_slug)


async def sub_shadowrocket_named_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
    config_id: str,
) -> PlainTextResponse:
    return await _render_shadowrocket_scenario(request, token, scenario_slug, config_id=config_id)


async def _render_shadowrocket_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
    *,
    config_id: str | None = None,
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    if config_id is not None and f"shadowrocket-{config_id}.conf" != shadowrocket_config_filename(subscription_id, scenario_slug):
        raise HTTPException(status_code=404, detail="configuration filename not found")
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    managed_url = _scenario_managed_url(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        suffix=shadowrocket_config_filename(subscription_id, scenario.slug) if config_id is not None else "shadowrocket.conf",
    )
    profile_settings = _scenario_profile_settings(request, scenario)
    artifacts = build_shadowrocket_profile_artifacts(
        policy_entry.nodes,
        list(policy_entry.policy_ir.rule_lines),
        managed_url,
        local_host_aliases=frozenset(capture_local_host_aliases()),
        profile="lazycat",
        profile_settings=profile_settings,
        policy_ir=policy_entry.policy_ir,
    )
    if artifacts.blocked_detail["blockers"]:
        raise HTTPException(status_code=409, detail=_device_blocked_detail(artifacts.blocked_detail))
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    return PlainTextResponse(artifacts.content, headers={"Profile-Update-Interval": "1800"})
    

@router.get("/sub/device/{token}/{scenario_slug}/shadowrocket-nodes.txt", response_class=PlainTextResponse)
async def sub_shadowrocket_nodes_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
) -> PlainTextResponse:
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    nodes = hub.get_nodes_for_token(internal_token)
    if nodes is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    content, _ = build_shadowrocket_nodes_subscription(nodes)
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename(build_subscription_download_name(_resolve_subscription_device_name(services, subscription_id)), "-leaf-nodes.txt")}"'
        ),
        "Profile-Update-Interval": "1800",
    }
    userinfo = hub.get_shadowrocket_subscription_userinfo(internal_token, nodes=nodes)
    if userinfo:
        headers["subscription-userinfo"] = userinfo
    return PlainTextResponse(content, media_type="text/plain", headers=headers)


@router.get("/sub/device/{token}/{scenario_slug}/shadowrocket-legacy.conf", response_class=RedirectResponse)
async def sub_shadowrocket_legacy_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
) -> RedirectResponse:
    _reject_removed_profile_query_params(request)
    return RedirectResponse(
        url=f"/sub/device/{token}/{scenario_slug}/shadowrocket.conf",
        status_code=308,
    )


@router.get("/sub/device/{token}/{scenario_slug}/surge.conf", response_class=PlainTextResponse)
async def sub_surge_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    artifacts, _cache_state = _get_cached_surge_artifacts(
        request,
        internal_token=internal_token,
        subscription_id=subscription_id,
        scenario=scenario,
        policy_entry=policy_entry,
    )
    if artifacts.blocked:
        raise HTTPException(status_code=409, detail=_device_blocked_detail(surge_blocked_detail(artifacts)))
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    headers = _surge_subscription_headers(
        revision=policy_entry.revision,
        metadata=artifacts.subscription_metadata,
        extra={"Profile-Update-Interval": "1800"},
    )
    return PlainTextResponse(artifacts.main_conf, headers=headers)


@router.get("/sub/device/{token}/{scenario_slug}/surge/domain-set/{asset_key}.txt", response_class=PlainTextResponse)
async def sub_surge_domain_set_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
    asset_key: str,
    rev: str = Query(default=""),
    exp: int = Query(default=0),
    sig: str = Query(default=""),
) -> PlainTextResponse:
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    _validate_surge_asset_signature_best_effort(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        kind="domain-set",
        asset_key=asset_key,
        revision=str(rev or policy_entry.revision),
        expires_at=exp,
        signature=sig,
    )
    artifacts, _cache_state = _get_cached_surge_artifacts(
        request,
        internal_token=internal_token,
        subscription_id=subscription_id,
        scenario=scenario,
        policy_entry=policy_entry,
    )
    if artifacts.blocked:
        raise HTTPException(status_code=409, detail=_device_blocked_detail(surge_blocked_detail(artifacts)))
    content = artifacts.domain_sets.get(asset_key)
    if content is None:
        raise HTTPException(status_code=404, detail="surge domain-set asset not found")
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    return PlainTextResponse(
        content,
        headers=_surge_subscription_headers(revision=policy_entry.revision, metadata=artifacts.subscription_metadata),
    )


@router.get("/sub/device/{token}/{scenario_slug}/surge/rule-set/{asset_key}.list", response_class=PlainTextResponse)
async def sub_surge_rule_set_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
    asset_key: str,
    rev: str = Query(default=""),
    exp: int = Query(default=0),
    sig: str = Query(default=""),
) -> PlainTextResponse:
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    _validate_surge_asset_signature_best_effort(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        kind="rule-set",
        asset_key=asset_key,
        revision=str(rev or policy_entry.revision),
        expires_at=exp,
        signature=sig,
    )
    artifacts, _cache_state = _get_cached_surge_artifacts(
        request,
        internal_token=internal_token,
        subscription_id=subscription_id,
        scenario=scenario,
        policy_entry=policy_entry,
    )
    if artifacts.blocked:
        raise HTTPException(status_code=409, detail=_device_blocked_detail(surge_blocked_detail(artifacts)))
    content = artifacts.rule_sets.get(asset_key)
    if content is None:
        raise HTTPException(status_code=404, detail="surge rule-set asset not found")
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    return PlainTextResponse(
        content,
        headers=_surge_subscription_headers(revision=policy_entry.revision, metadata=artifacts.subscription_metadata),
    )


@router.get("/sub/device/{token}/{scenario_slug}/surge-mac-overlay.conf", response_class=PlainTextResponse)
async def sub_surge_mac_overlay_scenario(
    request: Request,
    token: str,
    scenario_slug: str,
) -> PlainTextResponse:
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_subscription_id(services, token)
    internal_token = _resolve_internal_token_or_error(services, subscription_id)
    scenario = _resolve_scenario_by_slug(request, scenario_slug)
    await _refresh_hub_for_subscription(hub)
    nodes = hub.get_nodes_for_token(internal_token)
    if nodes is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    managed_url = _scenario_managed_url(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        suffix="surge-mac-overlay.conf",
        profile_settings=_scenario_profile_settings(request, scenario),
    )
    include_url = _scenario_managed_url(
        request,
        subscription_id=subscription_id,
        scenario_slug=scenario.slug,
        suffix="surge.conf",
        profile_settings=_scenario_profile_settings(request, scenario),
    )
    overlay = await hub.build_surge_mac_overlay(
        internal_token,
        managed_url,
        include_url,
        scenario_id=scenario.id,
    )
    if overlay is None:
        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
    overlay_status = overlay.overlay_status
    if overlay_status and overlay_status.reason_code == "needs_rebind":
        raise HTTPException(status_code=409, detail=overlay_status.reason or "surge mac overlay requires contract rebinding")
    hub.touch_subscription(internal_token, request.client.host if request.client else "unknown")
    return PlainTextResponse(build_surge_mac_overlay(overlay), headers={"Profile-Update-Interval": "1800"})


# Register parameterized filenames after the historical static legacy routes.
router.add_api_route(
    "/sub/device/{token}/shadowrocket-{config_id}.conf",
    sub_shadowrocket_named, methods=["GET"], response_class=PlainTextResponse,
)
router.add_api_route(
    "/sub/device/{token}/{scenario_slug}/shadowrocket-{config_id}.conf",
    sub_shadowrocket_named_scenario, methods=["GET"], response_class=PlainTextResponse,
)
