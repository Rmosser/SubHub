from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.i18n import localize_egress_payload, resolve_locale
from app.models import (
    BUSINESS_GROUP_MODE_STANDARD,
    BUSINESS_GROUP_MODES,
    CONTRACT_AD_BLOCK,
    CONTRACT_CHAIN_HOME,
    CONTRACT_DIRECT,
    CONTRACT_DISPLAY_NAMES,
    ROUTE_DIRECT_ACTION,
    ROUTE_REJECT_ACTION,
    DEVICE_STRATEGY_PRESETS,
    DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
    GeneralProfile,
    RULE_CATEGORY_TYPE_AUTO,
    RULE_CATEGORY_TYPE_MANUAL,
    RULE_DIRECTNESS_DIRECT,
    RULE_DIRECTNESS_PROXY,
    RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
    RULE_LOCK_SOURCE_MANUAL,
    RULE_LOCK_SOURCE_SYSTEM,
    STANDARD_SOURCE_INGEST_MANUAL_NODES,
    STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION,
    STANDARD_SOURCE_INGEST_KINDS,
    STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT,
    STANDARD_SOURCE_MODE_ROUTE_CONTRACT,
    STANDARD_SOURCE_MODES,
    STANDARD_SOURCE_PULL_NETWORK_MODES,
    STANDARD_SOURCE_QR_FIELDS,
    CustomRule,
    GoRelaySource,
    QUALITY_HIGH_AIRPORT,
    QUALITY_GROUPS,
    QUALITY_MEDIUM,
    RenderWarning,
    RendererDiagnostics,
    RouteContract,
    RouteContractView,
    ScenarioProfile,
    ServiceCatalogEntry,
    STANDARD_SOURCE_ALLOWED_GROUPS,
    StandardSource,
    StandardSourceQrAsset,
    SURGE_PROCESS_RULE_TYPES,
    VALID_TARGETS,
    NodeRecord,
    contract_display_name,
    effective_contract_id,
    effective_contract_source,
    contract_legacy_group,
    normalize_standard_source_mode,
    normalize_standard_source_ingest_kind,
    normalize_contract_id,
    resolve_contract_id,
)
from app.routes.url_resolver import resolve_base_url, resolve_base_url_context
from app.services.render_environment import capture_local_host_aliases
from app.services.export_artifacts import (
    ascii_filename,
    attach_clash_bundle_audit,
    bundle_zip_bytes,
)
from app.services.lazycat_profile import (
    normalize_lazycat_profile_settings,
    validate_lazycat_profile_settings_for_write,
)
from app.services.profile_capabilities import (
    profile_capabilities_payload,
    profile_capabilities_to_settings,
    settings_to_profile_capabilities,
)
from app.services.hub_service import summarize_refresh_status
from app.services.policy_backup_service import RestoreSnapshotChanged
from app.services.profile_editor_schema import (
    apply_editor_state_to_settings,
    default_profile_editor_state,
    harmonize_profile_single_source_settings,
    normalize_profile_editor_state,
    profile_editor_schema_payload,
)
from app.services.route_contract_views import (
    ScenarioContractLookup,
    scenario_contract_description,
    scenario_contract_display_name,
    scenario_contract_lookup,
    scenario_default_contract_id,
    scenario_resolve_contract_id,
    scenario_route_contract,
    scenario_route_contracts,
    scenario_route_contracts_by_id,
)
from app.services.skip_proxy_decomposer import decompose_skip_proxy
from app.services.qr_decoder import decode_qr_url
from app.services.rule_catalog import _RULE_TYPES as RULE_CATALOG_RULE_TYPES
from app.storage.sqlite_repo import SqliteRepo
from app.storage.base import standard_source_diagnostics_key
from app.services.standard_source_resolver import resolve_standard_source_target
from app.services.source_diagnostics import (
    KnownSecrets, known_source_secrets, public_runtime, public_source_status, source_pull_reasons, summarize_pull_errors,
)
from app.services.subscription_builder import (
    build_clash_blocked_detail,
    build_clash_export_bundle,
    build_clash_profile_artifacts,
    build_device_import_links,
    build_device_import_links_for_scenario,
    build_surge_profile_artifacts,
    build_shadowrocket_profile_artifacts,
    derive_protocol_diagnostics,
    resolve_preferred_surge_base_url,
    surge_blocked_detail,
)
from app.services.subscription_urls import build_signed_subscription_asset_url
from app.services.tenant_registry import request_services

router = APIRouter(prefix="/api", tags=["management"])

_QR_ALLOWED_FIELDS = set(STANDARD_SOURCE_QR_FIELDS)
_QR_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_QR_ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
_QR_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_QR_MAX_FILE_BYTES = 4 * 1024 * 1024
_CATEGORY_RULE_TYPE_ORDER = (
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "IP-CIDR",
    "IP-CIDR6",
    "SRC-IP-CIDR",
    "GEOIP",
    "GEOSITE",
    "DST-PORT",
    "SRC-PORT",
    "PROCESS-NAME",
    "PROCESS-PATH",
    "USER-AGENT",
)
_CATEGORY_RULE_TYPES = tuple(
    [item for item in _CATEGORY_RULE_TYPE_ORDER if item in RULE_CATALOG_RULE_TYPES]
    + sorted(item for item in RULE_CATALOG_RULE_TYPES if item not in _CATEGORY_RULE_TYPE_ORDER)
)
_CATEGORY_PREVIEW_DEFAULT_LIMIT = 200
_CATEGORY_PREVIEW_MAX_LIMIT = 1000
_SCENARIO_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_CONTRACT_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DEFAULT_SCENARIO_ID = "scenario-default"
_SCENARIO_CATALOG_GROUP_INHERIT = "__scenario_inherit__"
_UNREAD = object()  # matcher not read yet in this request (None means "no values")


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


def _normalize_scenario_slug(value: object) -> str:
    slug = str(value or "").strip().lower()
    if not slug:
        raise HTTPException(status_code=400, detail="scenario slug is required")
    if not _SCENARIO_SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="scenario slug must match [a-z0-9-]+")
    return slug


def _slugify_contract_name(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "contract"
    slug = _CONTRACT_SLUG_RE.sub("-", text).strip("-")
    return slug or "contract"


def _next_contract_id(repo, *, display_name: object, owner_scenario_id: str) -> str:
    safe_owner = str(owner_scenario_id or "").strip()
    base_slug = _slugify_contract_name(display_name)
    if safe_owner:
        scenario = repo.get_scenario(safe_owner)
        scenario_slug = _normalize_scenario_slug(scenario.slug if scenario else safe_owner)
        prefix = f"scenario-{scenario_slug}-{base_slug}"
    else:
        prefix = f"custom-{base_slug}"
    candidate = prefix
    index = 2
    while repo.get_route_contract(candidate):
        candidate = f"{prefix}-{index}"
        index += 1
    return candidate


def _resolve_scenario_or_404(request: Request, scenario_id: str) -> ScenarioProfile:
    item = _services(request).repo.get_scenario(scenario_id)
    if not item:
        raise HTTPException(status_code=404, detail="scenario not found")
    return item


def _resolve_scenario_context(request: Request, scenario_id: str | None = None) -> ScenarioProfile:
    return _resolve_scenario_or_404(request, _scenario_id_or_default(scenario_id))


def _derive_rule_category_states(category) -> dict[str, object]:
    system_group = str(category.system_default_group or "").strip()
    if not system_group and str(category.system_directness or "").upper() == RULE_DIRECTNESS_DIRECT:
        system_group = RULE_DIRECTNESS_DIRECT
    system_locked = bool(category.system_default_locked)
    if system_group == RULE_DIRECTNESS_DIRECT:
        system_locked = True

    override_active = bool(category.override_active)
    override_group = str(category.override_group or "").strip()
    if category.category_type == RULE_CATEGORY_TYPE_AUTO and not override_active:
        if str(category.directness_override or "").upper() == RULE_DIRECTNESS_DIRECT:
            override_active = True
            override_group = RULE_DIRECTNESS_DIRECT
        elif str(category.directness_override or "").upper() == RULE_DIRECTNESS_PROXY:
            override_active = True
            assigned = str(category.assigned_group or "").strip()
            override_group = assigned if assigned != RULE_DIRECTNESS_DIRECT else ""
        elif str(category.assigned_group or "").strip() != system_group:
            override_active = True
            override_group = str(category.assigned_group or "").strip()
    if category.category_type != RULE_CATEGORY_TYPE_AUTO:
        override_active = False
        override_group = ""

    effective_group = str(category.assigned_group or "").strip()
    if category.category_type == RULE_CATEGORY_TYPE_AUTO:
        expected_group = override_group if override_active else system_group
        if effective_group != expected_group:
            effective_group = expected_group

    effective_locked = bool(category.locked)
    effective_lock_source = str(category.lock_source or "").strip()
    if effective_lock_source == RULE_LOCK_SOURCE_MANUAL:
        effective_locked = True
    if (
        category.category_type == RULE_CATEGORY_TYPE_AUTO
        and not override_active
        and system_locked
        and effective_lock_source != RULE_LOCK_SOURCE_MANUAL
    ):
        effective_locked = True
        effective_lock_source = RULE_LOCK_SOURCE_SYSTEM
    if override_active and effective_lock_source == RULE_LOCK_SOURCE_SYSTEM:
        effective_locked = False
        effective_lock_source = ""
    if not effective_locked:
        effective_lock_source = ""

    effective_directness = (
        RULE_DIRECTNESS_DIRECT if effective_group == RULE_DIRECTNESS_DIRECT else RULE_DIRECTNESS_PROXY
    )
    if override_active and effective_group == RULE_DIRECTNESS_DIRECT:
        current_source = "override-direct"
    elif override_active:
        current_source = "override-proxy"
    elif system_group == RULE_DIRECTNESS_DIRECT:
        current_source = "system"
    else:
        current_source = "default-proxy"
    derived_override_directness = ""
    if override_active and effective_group == RULE_DIRECTNESS_DIRECT:
        derived_override_directness = RULE_DIRECTNESS_DIRECT
    elif override_active and system_group == RULE_DIRECTNESS_DIRECT:
        derived_override_directness = RULE_DIRECTNESS_PROXY

    return {
        "system_state": {
            "group": system_group,
            "locked": system_locked,
            "directness": RULE_DIRECTNESS_DIRECT if system_group == RULE_DIRECTNESS_DIRECT else RULE_DIRECTNESS_PROXY,
        },
        "override_state": {
            "active": override_active,
            "group": override_group if override_active else "",
        },
        "effective_state": {
            "group": effective_group,
            "locked": effective_locked,
            "lock_source": effective_lock_source,
            "directness": effective_directness,
        },
        "can_restore_system_default": category.category_type == RULE_CATEGORY_TYPE_AUTO and override_active,
        "current_decision_source": current_source,
        "directness_override": derived_override_directness,
    }


def _contract_display_name_from_repo(repo, contract_id: object, *, scenario_id: str | None = None) -> str:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return str(contract_id or "").strip()
    if repo:
        if scenario_id is None:
            contract = repo.get_route_contract(normalized)
            if contract and str(contract.display_name or "").strip():
                return str(contract.display_name or "").strip()
        else:
            return scenario_contract_display_name(repo, _scenario_id_or_default(scenario_id), normalized)
    return contract_display_name(normalized)


def _contract_display_name_map(repo, *, scenario_id: str | None = None) -> dict[str, str]:
    if scenario_id is None:
        return {
            str(item.id or "").strip(): str(item.display_name or "").strip()
            for item in repo.list_route_contracts()
            if str(item.id or "").strip() and str(item.display_name or "").strip()
        }
    return {
        str(item.id or "").strip(): str(item.display_name or "").strip()
        for item in scenario_route_contracts(repo, _scenario_id_or_default(scenario_id))
        if str(item.id or "").strip()
    }


def _resolve_contract_id_from_repo(repo, value: object, *, scenario_id: str | None = None) -> str:
    if scenario_id is None:
        return resolve_contract_id(value, display_name_map=_contract_display_name_map(repo, scenario_id=None))
    return scenario_resolve_contract_id(repo, _scenario_id_or_default(scenario_id), value)


def _eligible_standard_source_contract_ids(repo, *, scenario_id: str | None = None) -> set[str]:
    contracts = (
        scenario_route_contracts(repo, _scenario_id_or_default(scenario_id))
        if scenario_id is not None
        else repo.list_route_contracts()
    )
    return {item.id for item in contracts if item.can_bind_standard_source()}


def _contract_legacy_group_from_repo(repo, contract_id: object, *, scenario_id: str | None = None) -> str:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return ""
    contract = (
        scenario_route_contract(repo, _scenario_id_or_default(scenario_id), normalized)
        if scenario_id is not None
        else repo.get_route_contract(normalized)
    )
    if contract:
        return contract.primary_legacy_group()
    return contract_legacy_group(normalized)


def _public_rule_group_name(
    group: object,
    *,
    repo=None,
    scenario_id: str | None = None,
    contracts: ScenarioContractLookup | None = None,
) -> str:
    text = str(group or "").strip()
    if not text:
        return ""
    if contracts is not None:
        contract_id = contracts.resolve_contract_id(text)
        return contracts.display_name(contract_id) if contract_id else text
    contract_id = (
        _resolve_contract_id_from_repo(repo, text, scenario_id=scenario_id)
        if repo
        else normalize_contract_id(text)
    )
    return (
        _contract_display_name_from_repo(repo, contract_id, scenario_id=scenario_id)
        if contract_id
        else text
    )


def _public_rule_category_states(
    states: dict[str, object],
    *,
    repo=None,
    scenario_id: str | None = None,
    contracts: ScenarioContractLookup | None = None,
) -> dict[str, object]:
    public_states = {
        "system_state": dict(states["system_state"]),
        "override_state": dict(states["override_state"]),
        "effective_state": dict(states["effective_state"]),
        "can_restore_system_default": states["can_restore_system_default"],
        "current_decision_source": states["current_decision_source"],
        "directness_override": states["directness_override"],
    }
    public_states["system_state"]["group"] = _public_rule_group_name(
        public_states["system_state"]["group"], repo=repo, scenario_id=scenario_id, contracts=contracts
    )
    public_states["override_state"]["group"] = _public_rule_group_name(
        public_states["override_state"]["group"], repo=repo, scenario_id=scenario_id, contracts=contracts
    )
    public_states["effective_state"]["group"] = _public_rule_group_name(
        public_states["effective_state"]["group"], repo=repo, scenario_id=scenario_id, contracts=contracts
    )
    return public_states


def _scenario_contract_reference_count(services, scenario_id: str, contract_id: str) -> int:
    normalized_contract_id = normalize_contract_id(contract_id)
    if not normalized_contract_id:
        return 0
    count = 0
    bindings = services.repo.list_scenario_service_catalog_entries(scenario_id)
    count += sum(1 for item in bindings if normalize_contract_id(item.contract_id) == normalized_contract_id)
    count += sum(
        1
        for item in services.repo.list_scenario_custom_rules(scenario_id)
        if item.resolved_target_contract_id() == normalized_contract_id
    )
    process_rules = services.repo.list_scenario_process_rules(scenario_id)
    if isinstance(process_rules, list):
        count += sum(1 for item in process_rules if normalize_contract_id(item.get("contract_id")) == normalized_contract_id)
    external_programs = services.repo.list_scenario_external_proxy_programs(scenario_id)
    if isinstance(external_programs, list):
        count += sum(1 for item in external_programs if normalize_contract_id(item.get("contract_id")) == normalized_contract_id)
    return count


def _effective_contract_disable_reference_count(services, scenario_id: str, contract_id: str) -> int:
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    normalized_contract_id = normalize_contract_id(contract_id)
    if not normalized_contract_id:
        return 0
    count = _scenario_contract_reference_count(services, safe_scenario_id, normalized_contract_id)
    base_contract = services.repo.get_route_contract(normalized_contract_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID or (
        base_contract and base_contract.owner_scenario_id == safe_scenario_id
    ):
        count += sum(
            1
            for item in services.repo.list_standard_sources()
            if item.resolved_target_contract_id() == normalized_contract_id
        )
    if safe_scenario_id != _DEFAULT_SCENARIO_ID:
        return count
    for scenario in services.repo.list_scenarios():
        if scenario.id == _DEFAULT_SCENARIO_ID:
            continue
        if services.repo.get_scenario_route_contract_view(scenario.id, normalized_contract_id) is not None:
            continue
        count += _scenario_contract_reference_count(services, scenario.id, normalized_contract_id)
    return count


def _global_contract_delete_reference_count(services, contract_id: str) -> int:
    normalized_contract_id = normalize_contract_id(contract_id)
    if not normalized_contract_id:
        return 0
    count = sum(
        1
        for item in services.repo.list_standard_sources()
        if item.resolved_target_contract_id() == normalized_contract_id
    )
    for scenario in services.repo.list_scenarios():
        count += _scenario_contract_reference_count(services, scenario.id, normalized_contract_id)
    return count


def _contract_allows_topology_edit(contract: RouteContract, *, scenario_id: str) -> bool:
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if not bool(contract.editable):
        return False
    owner_scenario_id = str(contract.owner_scenario_id or "").strip()
    if owner_scenario_id:
        return owner_scenario_id == safe_scenario_id
    return safe_scenario_id == _DEFAULT_SCENARIO_ID


def _rebind_service_catalog_contracts(services, scenario_id: str, from_contract_id: str, to_contract_id: str) -> int:
    count = 0
    entries = services.repo.list_scenario_service_catalog_entries(scenario_id)
    for item in entries:
        if normalize_contract_id(item.contract_id) != from_contract_id:
            continue
        entry = ServiceCatalogEntry(
            category_name=item.category_name,
            catalog_group=item.catalog_group,
            contract_id=to_contract_id,
            sort_order=item.sort_order,
            source=item.source or "manual",
        )
        if scenario_id == _DEFAULT_SCENARIO_ID:
            services.repo.save_service_catalog_entry(entry)
        else:
            services.repo.save_scenario_service_catalog_entry(scenario_id, entry)
        count += 1
    return count


def _rebind_custom_rules(services, scenario_id: str, from_contract_id: str, to_contract_id: str) -> int:
    count = 0
    if scenario_id == _DEFAULT_SCENARIO_ID:
        seen_rule_ids: set[str] = set()
        for item in services.repo.list_custom_rules():
            if item.resolved_target_contract_id() != from_contract_id:
                continue
            services.repo.save_custom_rule(
                CustomRule(
                    id=item.id,
                    rule_type=item.rule_type,
                    value=item.value,
                    target_contract_id=to_contract_id,
                    category_name=item.category_name,
                    created_at=item.created_at,
                )
            )
            seen_rule_ids.add(item.id)
            count += 1
        for item in services.repo.list_explicit_scenario_custom_rules(scenario_id):
            if item.id in seen_rule_ids or item.resolved_target_contract_id() != from_contract_id:
                continue
            services.repo.save_scenario_custom_rule(
                scenario_id,
                CustomRule(
                    id=item.id,
                    rule_type=item.rule_type,
                    value=item.value,
                    target_contract_id=to_contract_id,
                    category_name=item.category_name,
                    created_at=item.created_at,
                ),
            )
            count += 1
        return count
    for item in services.repo.list_explicit_scenario_custom_rules(scenario_id):
        if item.resolved_target_contract_id() != from_contract_id:
            continue
        services.repo.save_scenario_custom_rule(
            scenario_id,
            CustomRule(
                id=item.id,
                rule_type=item.rule_type,
                value=item.value,
                target_contract_id=to_contract_id,
                category_name=item.category_name,
                created_at=item.created_at,
            ),
        )
        count += 1
    return count


def _rebind_process_rules(services, scenario_id: str, from_contract_id: str, to_contract_id: str) -> int:
    raw = services.repo.list_scenario_process_rules(scenario_id)
    if not isinstance(raw, list):
        return 0
    count = 0
    updated: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        if normalize_contract_id(item.get("contract_id")) == from_contract_id:
            next_item["contract_id"] = to_contract_id
            count += 1
        updated.append(next_item)
    if not count:
        return 0
    if scenario_id == _DEFAULT_SCENARIO_ID:
        services.repo.set_runtime_setting("surge.process_rules", updated)
    if scenario_id == _DEFAULT_SCENARIO_ID:
        services.repo.set_scenario_process_rules(scenario_id, updated)
    else:
        services.repo.set_scenario_process_rules(scenario_id, updated)
    return count


def _rebind_external_proxy_programs(services, scenario_id: str, from_contract_id: str, to_contract_id: str) -> int:
    raw = services.repo.list_scenario_external_proxy_programs(scenario_id)
    if not isinstance(raw, list):
        return 0
    count = 0
    updated: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        if normalize_contract_id(item.get("contract_id")) == from_contract_id:
            next_item["contract_id"] = to_contract_id
            count += 1
        updated.append(next_item)
    if not count:
        return 0
    if scenario_id == _DEFAULT_SCENARIO_ID:
        services.repo.set_runtime_setting("surge.external_proxy_programs", updated)
    if scenario_id == _DEFAULT_SCENARIO_ID:
        services.repo.set_scenario_external_proxy_programs(scenario_id, updated)
    else:
        services.repo.set_scenario_external_proxy_programs(scenario_id, updated)
    return count


def _refresh_policy_payload(services) -> dict[str, object]:
    payload = dict(services.rule_catalog.get_refresh_policy())
    payload.update(services.hub_service.get_standard_source_refresh_policy())
    return payload


def _llm_export_settings_payload(services) -> dict[str, str]:
    return services.rule_catalog.get_llm_export_preferences()


def _scenario_id_or_default(scenario_id: str | None) -> str:
    return str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID


def _pin_group_meta_map(services, scenario_id: str | None = None) -> dict[str, dict[str, object]]:
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    groups = (
        services.repo.list_scenario_pin_groups(safe_scenario_id)
        if safe_scenario_id
        else services.repo.list_pin_groups()
    )
    return {
        str(item.get("group_name") or "").strip(): dict(item)
        for item in groups
        if str(item.get("group_name") or "").strip()
    }


def _effective_catalog_group(
    catalog_entry: ServiceCatalogEntry | None,
    pin: dict[str, object] | None,
) -> str:
    catalog_group = str(catalog_entry.catalog_group or "").strip() if catalog_entry else ""
    if catalog_group:
        return catalog_group
    return str((pin or {}).get("pin_group") or "").strip()


def _effective_contract_payload(
    *,
    category,
    catalog_entry: ServiceCatalogEntry | None,
    pin_group_meta: dict[str, dict[str, object]],
    current_directness: str,
) -> dict[str, str]:
    stored_contract_id = normalize_contract_id(catalog_entry.contract_id if catalog_entry else "")
    catalog_group = str(catalog_entry.catalog_group or "") if catalog_entry else ""
    group_mode = str((pin_group_meta.get(catalog_group) or {}).get("mode") or "")
    resolved_contract_id = effective_contract_id(
        stored_contract_id=stored_contract_id,
        catalog_group_mode=group_mode,
        current_directness=current_directness,
    )
    return {
        "stored_contract_id": stored_contract_id,
        "effective_contract_id": resolved_contract_id,
        "effective_contract_source": effective_contract_source(
            stored_contract_id=stored_contract_id,
            catalog_group_mode=group_mode,
            current_directness=current_directness,
        ),
        "catalog_group_mode": group_mode or BUSINESS_GROUP_MODE_STANDARD,
    }


def _category_custom_rule_contract_payload(
    services,
    *,
    category,
    scenario_id: str,
) -> dict[str, object]:
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    scenario_category = next(
        (
            item
            for item in services.repo.list_scenario_categories(safe_scenario_id)
            if item.name == category.name
        ),
        category,
    )
    catalog_entry = next(
        (
            item
            for item in services.repo.list_scenario_service_catalog_entries(safe_scenario_id)
            if item.category_name == category.name
        ),
        None,
    )
    states = _derive_rule_category_states(scenario_category)
    contract_payload = _effective_contract_payload(
        category=scenario_category,
        catalog_entry=catalog_entry,
        pin_group_meta=_pin_group_meta_map(services, safe_scenario_id),
        current_directness=str(states["effective_state"]["directness"]),
    )
    effective_contract_id_value = str(contract_payload["effective_contract_id"] or "")
    return {
        **contract_payload,
        "effective_contract_display_name": _contract_display_name_from_repo(
            services.repo,
            effective_contract_id_value,
            scenario_id=safe_scenario_id,
        ),
        "active": bool(effective_contract_id_value),
    }


def _serialize_category_custom_rule(item: CustomRule, *, contract_payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": item.id,
        "rule_type": item.rule_type,
        "value": item.value,
        "category_name": item.category_name,
        "created_at": item.created_at,
        "effective_contract_id": str(contract_payload["effective_contract_id"] or ""),
        "effective_contract_display_name": str(contract_payload["effective_contract_display_name"] or ""),
        "effective_contract_source": str(contract_payload["effective_contract_source"] or ""),
        "active": bool(contract_payload["active"]),
    }


def _require_category_custom_rule_contract(contract_payload: dict[str, object]) -> None:
    if bool(contract_payload.get("active")):
        return
    raise HTTPException(status_code=409, detail="category route contract required before adding category rules")


def _serialize_custom_rule(item: CustomRule, *, contracts: ScenarioContractLookup) -> dict[str, object]:
    contract_id = item.resolved_target_contract_id()
    if contract_id == ROUTE_DIRECT_ACTION:
        target_group = RULE_DIRECTNESS_DIRECT
    elif contract_id == ROUTE_REJECT_ACTION:
        target_group = "REJECT"
    else:
        target_group = contracts.display_name(contract_id) if contract_id else str(item.target_group or "").strip()
    payload = item.to_dict()
    payload["target_contract_id"] = contract_id
    payload["target_contract_display_name"] = target_group
    payload["target_group"] = target_group
    return payload


def _normalize_pull_result(
    raw: dict[str, object] | None, known_secrets: KnownSecrets = None,
) -> dict[str, object]:
    data = dict(raw or {})
    attempts = data.get("attempts")
    filtered_examples = data.get("filtered_technical_examples")
    warnings = _normalize_standard_source_warnings(data.get("warnings"))
    return public_source_status({
        "ok": bool(data.get("ok")),
        "method": str(data.get("pull_method") or data.get("method") or ""),
        "node_count": int(data.get("pull_node_count") or data.get("node_count") or 0),
        "cached_node_count": int(
            data.get("cached_node_count")
            if data.get("cached_node_count") is not None
            else data.get("pull_node_count") or data.get("node_count") or 0
        ),
        "error": str(data.get("error") or ""),
        "attempts": attempts if isinstance(attempts, list) else [],
        "warning_count": int(data.get("warning_count") or len(warnings)),
        "warnings": warnings,
        "filtered_technical_count": int(data.get("filtered_technical_count") or 0),
        "filtered_technical_examples": (
            [str(item or "").strip() for item in filtered_examples if str(item or "").strip()]
            if isinstance(filtered_examples, list)
            else []
        ),
        "last_success_at": data.get("last_success_at"),
        "config_fingerprint": str(data.get("config_fingerprint") or ""),
        "last_success_config_fingerprint": str(data.get("last_success_config_fingerprint") or ""),
    }, *((known_secrets,) if known_secrets else ()))


def _normalize_pull_network_mode(value: str | None, *, fallback: str) -> str:
    mode = str(value or "").strip()
    if not mode:
        mode = fallback
    if mode not in STANDARD_SOURCE_PULL_NETWORK_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                "pull_network_mode must be direct_then_proxy or direct_only or proxy_then_direct"
            ),
        )
    return mode


def _gorelay_source_runtime_payload(services, source_id: str) -> dict[str, object]:
    latest = services.repo.load_gorelay_latest_account_snapshot(source_id)
    latest_account = latest.account if latest else None
    latest_snapshot_id = latest_account.snapshot_id if latest_account else ""
    active_snapshot_id = services.repo.load_gorelay_active_snapshot_id(source_id) or ""
    return {
        "last_refresh_at": latest_account.created_at if latest_account else None,
        "last_refresh_status": latest_account.status if latest_account else "",
        "last_refresh_error": (
            str(latest_account.error or "")
            if latest_account and latest_account.error
            else ""
        ),
        "last_node_count": int(latest_account.node_count if latest_account else 0),
        "last_device_count": int(latest_account.device_count if latest_account else 0),
        "pending_domain_count": len(latest.pending_bindings) if latest else 0,
        "latest_snapshot_id": latest_snapshot_id,
        "active_snapshot_id": active_snapshot_id,
        "active_snapshot_is_latest": (
            not latest_snapshot_id or active_snapshot_id == latest_snapshot_id
        ),
    }


def _normalize_business_group_mode(
    value: str | None,
    *,
    default: str = BUSINESS_GROUP_MODE_STANDARD,
) -> str:
    mode = str(value or "").strip()
    if not mode:
        mode = default
    if mode not in BUSINESS_GROUP_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of: {', '.join(BUSINESS_GROUP_MODES)}",
        )
    return mode


def _validate_qr_field(field: str) -> str:
    value = str(field or "").strip().lower()
    if value not in _QR_ALLOWED_FIELDS:
        raise HTTPException(status_code=400, detail="invalid qr field")
    return value


def _empty_qr_asset_payload(source_id: str, field: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "field": field,
        "image_exists": False,
        "updated_at": "",
        "detected_url": "",
        "image_url": "",
    }


def _standard_source_cached_count(services, source_id: str) -> int:
    return len(services.repo.load_standard_node_cache(source_id) or [])


def _standard_source_compatibility_payload(nodes: list[NodeRecord]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for target in ("clash", "shadowrocket", "surge"):
        skipped = (
            [str(node.name or "").strip() for node in nodes if str(node.protocol or "").strip().lower() == "vless"]
            if target == "surge"
            else []
        )
        diagnostics = list(derive_protocol_diagnostics(nodes, skipped, target=target))
        if nodes and not diagnostics:
            diagnostics.append(
                RenderWarning(
                    code=f"{target}-source-supported",
                    message=f"{target} has no known protocol blockers for cached nodes",
                    target=target,
                    severity="info",
                    bucket="supported",
                )
            )
        payload[target] = _renderer_diagnostics_payload(diagnostics)
    return payload


def _standard_source_model_payload(source: StandardSource) -> dict[str, object]:
    return dict(source.__dict__)


def _normalize_standard_source_warnings(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    warnings: list[dict[str, object]] = []
    for item in raw:
        payload = dict(item or {}) if isinstance(item, dict) else {}
        code = str(payload.get("code") or "").strip()
        message = str(payload.get("message") or "").strip()
        field = str(payload.get("field") or "").strip()
        expected_method = str(payload.get("expected_method") or "").strip()
        actual_variant = str(payload.get("actual_variant") or "").strip()
        severity = str(payload.get("severity") or "warning").strip() or "warning"
        if not code or not message:
            continue
        warnings.append(
            {
                "code": code,
                "message": message,
                "field": field,
                "expected_method": expected_method,
                "actual_variant": actual_variant,
                "severity": severity,
            }
        )
    return warnings


def _standard_source_payload(
    services,
    source: StandardSource,
    *,
    scenario_id: str = _DEFAULT_SCENARIO_ID,
    known_secrets: KnownSecrets | object = _UNREAD,
) -> dict[str, object]:
    payload = source.to_dict()
    if known_secrets is _UNREAD:
        known_secrets = known_source_secrets(services.repo.list_standard_sources())
    payload["last_pull_error"] = summarize_pull_errors(source.last_pull_error, known_secrets) if source.last_pull_error else ""
    payload["last_pull_reasons"] = source_pull_reasons(source, known_secrets)
    cached_nodes = services.repo.load_standard_node_cache(source.id) or []
    resolved_contract_id = source.resolved_target_contract_id()
    resolved_mode = source.resolved_source_mode()
    if resolved_mode == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
        payload["quality_group"] = QUALITY_HIGH_AIRPORT
        payload["target_contract_id"] = ""
        payload["target_contract_display_name"] = ""
        payload["source_mode"] = STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT
    else:
        display_name = _contract_display_name_from_repo(
            services.repo,
            resolved_contract_id,
            scenario_id=scenario_id,
        )
        payload["quality_group"] = display_name
        payload["target_contract_id"] = resolved_contract_id
        payload["target_contract_display_name"] = display_name
        payload["source_mode"] = STANDARD_SOURCE_MODE_ROUTE_CONTRACT
    runtime_standard = (
        dict((services.hub_service.runtime.source_status or {}).get("standard") or {})
        if hasattr(services, "hub_service")
        else {}
    )
    saved_diagnostics = services.repo.get_runtime_setting(standard_source_diagnostics_key(source.id))
    runtime_item = public_source_status(dict(runtime_standard.get(source.id) or (
        saved_diagnostics if isinstance(saved_diagnostics, dict) else {}
    )), *((known_secrets,) if known_secrets else ()))
    runtime_filtered_examples = runtime_item.get("filtered_technical_examples")
    payload["filtered_technical_count"] = int(runtime_item.get("filtered_technical_count") or 0)
    payload["filtered_technical_examples"] = (
        [str(item or "").strip() for item in runtime_filtered_examples if str(item or "").strip()]
        if isinstance(runtime_filtered_examples, list)
        else []
    )
    warnings = _normalize_standard_source_warnings(runtime_item.get("warnings"))
    payload["pull_warning_count"] = int(runtime_item.get("warning_count") or len(warnings))
    payload["pull_warnings"] = warnings
    payload["cached_node_count"] = len(cached_nodes)
    payload["qr_assets"] = _build_qr_assets_payload(services, source.id)
    payload["compatibility"] = _standard_source_compatibility_payload(cached_nodes)
    return payload


def _qr_asset_payload(
    source_id: str,
    field: str,
    asset: StandardSourceQrAsset | None,
) -> dict[str, object]:
    payload = _empty_qr_asset_payload(source_id, field)
    if not asset:
        return payload
    payload.update(
        {
            "image_exists": True,
            "updated_at": asset.updated_at,
            "detected_url": asset.detected_url,
            "image_url": f"/api/sources/standard/{source_id}/qr/{field}/image",
        }
    )
    return payload


def _build_qr_assets_payload(services, source_id: str) -> dict[str, dict[str, object]]:
    assets = services.repo.list_standard_source_qr_assets(source_id)
    return {
        field: _qr_asset_payload(source_id, field, assets.get(field))
        for field in STANDARD_SOURCE_QR_FIELDS
    }


def _resolve_qr_asset_path(data_dir: Path, file_relpath: str) -> Path:
    base = data_dir.resolve()
    target = (data_dir / str(file_relpath or "")).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="invalid qr asset path")
    return target


def _detect_qr_file_extension(filename: str) -> str:
    ext = Path(str(filename or "")).suffix.lower().strip()
    if ext not in _QR_ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="unsupported image extension")
    return ext


def _decode_standard_source_qr_url(content: bytes) -> str:
    return decode_qr_url(content).strip()


def _is_supported_subscription_url(value: str) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _standard_source_field_by_qr_field(field_name: str) -> str:
    return {
        "clash": "clash_url",
        "shadowrocket": "shadowrocket_url",
        "surge": "surge_url",
    }[field_name]


def _normalize_standard_source_target(
    services,
    *,
    scenario_id: str = _DEFAULT_SCENARIO_ID,
    target_contract_id: str | None = None,
    source_mode: str | None = None,
    quality_group: str | None = None,
    existing_source: StandardSource | None = None,
) -> tuple[str, str, str]:
    # Standard sources are persisted globally, so their contract binding must
    # resolve against globally visible contracts instead of scenario-private ones.
    resolution_scenario_id = _DEFAULT_SCENARIO_ID
    try:
        return resolve_standard_source_target(
            target_contract_id=target_contract_id,
            source_mode=source_mode,
            quality_group=quality_group,
            existing_source=existing_source,
            display_name_map=_contract_display_name_map(
                services.repo,
                scenario_id=resolution_scenario_id,
            ),
            eligible_contract_ids=_eligible_standard_source_contract_ids(
                services.repo,
                scenario_id=resolution_scenario_id,
            ),
            display_name_for_contract=lambda contract_id: _contract_display_name_from_repo(
                services.repo,
                contract_id,
                scenario_id=resolution_scenario_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _normalize_standard_source_ingest_payload(
    *,
    ingest_kind: str | None = None,
    clash_url: str | None = None,
    shadowrocket_url: str | None = None,
    surge_url: str | None = None,
    login_url: str | None = None,
    manual_nodes_text: str | None = None,
    pull_network_mode: str | None = None,
    source_mode: str | None = None,
    existing_source: StandardSource | None = None,
) -> tuple[str, str, str, str, str, str, str]:
    raw_ingest_kind = str(ingest_kind or "").strip()
    if raw_ingest_kind and raw_ingest_kind not in STANDARD_SOURCE_INGEST_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"ingest_kind must be one of: {', '.join(STANDARD_SOURCE_INGEST_KINDS)}",
        )
    resolved_ingest_kind = normalize_standard_source_ingest_kind(
        raw_ingest_kind or (existing_source.resolved_ingest_kind() if existing_source else "")
    )

    clean_clash_url = str(clash_url or "").strip()
    clean_shadowrocket_url = str(shadowrocket_url or "").strip()
    clean_surge_url = str(surge_url or "").strip()
    clean_login_url = str(login_url or "").strip()
    clean_manual_nodes_text = str(manual_nodes_text or "").strip()
    clean_pull_network_mode = _normalize_pull_network_mode(
        pull_network_mode,
        fallback=(
            existing_source.pull_network_mode
            if existing_source
            and existing_source.pull_network_mode
            and existing_source.pull_network_mode in STANDARD_SOURCE_PULL_NETWORK_MODES
            else DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE
        ),
    )

    if resolved_ingest_kind == STANDARD_SOURCE_INGEST_MANUAL_NODES:
        if normalize_standard_source_mode(source_mode) == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
            raise HTTPException(
                status_code=400,
                detail="manual_nodes ingest only supports route_contract source_mode",
            )
        if not clean_manual_nodes_text:
            raise HTTPException(status_code=400, detail="manual_nodes_text is required for manual_nodes ingest")
        return (
            resolved_ingest_kind,
            "",
            "",
            "",
            "",
            clean_manual_nodes_text,
            DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
        )

    if not clean_clash_url or not clean_shadowrocket_url:
        raise HTTPException(
            status_code=400,
            detail="clash_url and shadowrocket_url are required for remote_subscription ingest",
        )
    return (
        resolved_ingest_kind,
        clean_clash_url,
        clean_shadowrocket_url,
        clean_surge_url,
        clean_login_url,
        "",
        clean_pull_network_mode,
    )


class GoRelaySourcePayload(BaseModel):
    name: str
    login_url: str
    gorelay_username: str
    gorelay_password: str = ""
    proxy_username: str = ""
    proxy_password: str = ""
    selectors_json: str = "{}"
    enabled: bool = True


class GoRelaySourceUpdatePayload(BaseModel):
    name: str
    login_url: str
    gorelay_username: str
    gorelay_password: str | None = None
    proxy_username: str = ""
    proxy_password: str | None = None
    selectors_json: str = "{}"
    enabled: bool = True


class StandardSourcePayload(BaseModel):
    name: str
    clash_url: str = ""
    shadowrocket_url: str = ""
    surge_url: str = ""
    login_url: str = ""
    quality_group: str | None = None
    target_contract_id: str | None = None
    source_mode: str | None = None
    ingest_kind: str | None = None
    manual_nodes_text: str = ""
    enabled: bool = True
    pull_network_mode: str | None = None


class CategoryAssignPayload(BaseModel):
    assigned_group: str = ""


class ManualCategoryRulePayload(BaseModel):
    rule_type: str = "DOMAIN-SUFFIX"
    value: str


class ManualCategoryCreatePayload(BaseModel):
    name: str
    assigned_group: str | None = None
    default_policy: Literal["direct", "proxy", "group"] | None = None
    default_group: str = ""
    rules: list[ManualCategoryRulePayload] = Field(default_factory=list)
    locked: bool = False


class ManualCategoryRenamePayload(BaseModel):
    new_name: str


class BulkAssignPayload(BaseModel):
    assignments: dict[str, str]


class ServiceCatalogBulkGroupPayload(BaseModel):
    assignments: dict[str, str]


class CustomRulePayload(BaseModel):
    rule_type: str
    value: str
    target_contract_id: str | None = None
    target_group: str = ""


class CategoryCustomRulePayload(BaseModel):
    rule_type: str
    value: str


class CategoryCustomRuleBulkPayload(BaseModel):
    items: list[CategoryCustomRulePayload] = Field(default_factory=list)
    dedupe: bool = True


class RuleRefreshPayload(BaseModel):
    mode: Literal["incremental", "full"] = "incremental"


class GlobalRefreshPayload(BaseModel):
    rule_catalog_mode: Literal["incremental", "full"] = "incremental"


class RefreshPolicyPayload(BaseModel):
    rule_catalog_cache_hours: int = Field(ge=1, le=168)
    cn_cache_hours: int = Field(ge=1, le=168)
    standard_source_auto_pull_enabled: bool | None = None
    standard_source_auto_pull_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


class LlmExportSettingsPayload(BaseModel):
    rules_preferences: str | None = None
    pins_preferences: str | None = None
    directness_preferences: str | None = None


class DirectnessReviewApplyPayload(BaseModel):
    review_ids: list[str]
    action: Literal["accept", "dismiss"] = "accept"


class PinCategoryPayload(BaseModel):
    pin_group: str = ""
    sort_order: int = 0


class PinReorderPayload(BaseModel):
    items: list[dict[str, object]]


class PinGroupRenamePayload(BaseModel):
    new_name: str
    mode: str | None = None
    description: str | None = None


class PinGroupOrderPayload(BaseModel):
    items: list[dict[str, object]]


class CreatePinGroupPayload(BaseModel):
    group_name: str
    mode: str = BUSINESS_GROUP_MODE_STANDARD
    description: str = ""


class BusinessGroupAssignPayload(BaseModel):
    business_group: str = ""
    sort_order: int = 0


class BusinessGroupRenamePayload(BaseModel):
    new_name: str
    mode: str | None = None
    description: str | None = None


class CreateBusinessGroupPayload(BaseModel):
    name: str
    mode: str = BUSINESS_GROUP_MODE_STANDARD
    description: str = ""


class LlmWorkflowExportPayload(BaseModel):
    intent_override: str = ""
    sample_rule_limit: int = Field(default=5, ge=0, le=20)


class LlmWorkflowPreviewPayload(BaseModel):
    snapshot_fingerprint: str
    result: dict[str, object]


class LlmWorkflowApplyPayload(BaseModel):
    snapshot_fingerprint: str
    result: dict[str, object]
    selected_change_ids: list[str] | None = None


class LogRoutingSessionExportPayload(BaseModel):
    intent_override: str = ""
    sample_evidence_limit: int = Field(default=3, ge=1, le=10)


class LogRoutingPatchPayload(BaseModel):
    snapshot_id: str
    patch: dict[str, object]
    selected_action_ids: list[str] | None = None


class SurgeProcessRuleItemPayload(BaseModel):
    id: str = ""
    contract_id: str | None = None
    business_group: str = ""
    match_type: str = "PROCESS-NAME"
    value: str
    sort_order: int = 0
    enabled: bool = True


class SurgeProcessRulesPayload(BaseModel):
    items: list[SurgeProcessRuleItemPayload] = Field(default_factory=list)


class SurgeExternalProxyProgramItemPayload(BaseModel):
    id: str = ""
    contract_id: str | None = None
    business_group: str = ""
    program_path: str
    args: list[str] = Field(default_factory=list)
    local_port: int = Field(ge=1, le=65535)
    name: str = ""
    sort_order: int = 0
    enabled: bool = True


class SurgeExternalProxyProgramsPayload(BaseModel):
    items: list[SurgeExternalProxyProgramItemPayload] = Field(default_factory=list)


class ContractUpdatePayload(BaseModel):
    routing_action: Literal["proxy", "direct", "reject"] | None = None
    display_name: str | None = None
    description: str | None = None
    llm_routing_intent: str | None = None
    sort_order: int | None = None
    is_default: bool | None = None
    enabled: bool | None = None
    strategy_type: str | None = None
    primary_pools: list[str] | None = None
    fallback_pools: list[str] | None = None
    failure_action: str | None = None


class ContractCreatePayload(BaseModel):
    routing_action: Literal["proxy", "direct", "reject"] = "proxy"
    display_name: str
    description: str = ""
    llm_routing_intent: str = ""
    sort_order: int = 0
    is_default: bool = False
    enabled: bool = True
    strategy_type: str = "strict"
    primary_pools: list[str] = Field(default_factory=list)
    fallback_pools: list[str] = Field(default_factory=list)
    failure_action: str = "interrupt"


class ContractRebindPayload(BaseModel):
    to_contract_id: str


class ServiceCatalogUpdatePayload(BaseModel):
    contract_id: str | None = None
    catalog_group: str | None = None
    sort_order: int | None = None


class GeneralProfileUpdatePayload(BaseModel):
    name: str = "LazyCat Default"
    settings: dict[str, object] = Field(default_factory=dict)
    capabilities: dict[str, object] | None = None
    editor_state: dict[str, object] | None = None


class GeneralProfileCreatePayload(BaseModel):
    name: str
    settings: dict[str, object] = Field(default_factory=dict)
    capabilities: dict[str, object] | None = None
    editor_state: dict[str, object] | None = None


class ScenarioPayload(BaseModel):
    slug: str
    name: str
    description: str = ""
    enabled: bool = True
    sort_order: int = 0
    settings: dict[str, object] = Field(default_factory=dict)
    editor_state: dict[str, object] | None = None


class PolicyBackupRestorePayload(BaseModel):
    ref: str = ""
    expected_digest: str = ""


def _profile_settings_from_payload(
    payload: GeneralProfileUpdatePayload | GeneralProfileCreatePayload,
    *,
    current_settings: Mapping[str, object] | None = None,
    current_editor_state: Mapping[str, object] | None = None,
    legacy_default: bool = False,
) -> dict[str, object]:
    if isinstance(payload.capabilities, dict):
        normalized = profile_capabilities_to_settings(
            payload.capabilities,
            base_settings=current_settings,
        )
        if isinstance(payload.editor_state, Mapping):
            editor_state = normalize_profile_editor_state(payload.editor_state, legacy_default=legacy_default)
            return apply_editor_state_to_settings(normalized, editor_state, current_settings=current_settings)
        return harmonize_profile_single_source_settings(normalized, current_settings=current_settings)
    validate_lazycat_profile_settings_for_write(payload.settings or {})
    normalized = normalize_lazycat_profile_settings(payload.settings or current_settings or {})
    if isinstance(payload.editor_state, Mapping):
        editor_state = normalize_profile_editor_state(payload.editor_state, legacy_default=legacy_default)
        return apply_editor_state_to_settings(normalized, editor_state, current_settings=current_settings)
    return harmonize_profile_single_source_settings(normalized, current_settings=current_settings)


def _profile_editor_state_from_payload(
    editor_state: Mapping[str, object] | None,
    *,
    current_editor_state: Mapping[str, object] | None,
    legacy_default: bool,
) -> dict[str, Any]:
    return normalize_profile_editor_state(
        editor_state if isinstance(editor_state, Mapping) else current_editor_state,
        legacy_default=legacy_default,
    )


def _profile_item_payload(item) -> dict[str, object]:
    payload = item.to_dict()
    payload["settings"] = harmonize_profile_single_source_settings(payload.get("settings"))
    payload["capabilities"] = settings_to_profile_capabilities(payload.get("settings"))
    payload["legacy"] = bool(((payload.get("editor_state") or {}) if isinstance(payload.get("editor_state"), dict) else {}).get("legacy"))
    return payload


class ReviewSettingsPayload(BaseModel):
    gemini_api_key: str = ""
    review_model: str = "gemini-2.0-flash"


class ReviewPayload(BaseModel):
    primary_profile_id: str
    target_profile_ids: list[str]


def _resolve_manual_category_group(
    payload: ManualCategoryCreatePayload,
    repo: SqliteRepo,
    *,
    scenario_id: str = _DEFAULT_SCENARIO_ID,
) -> str:
    policy = str(payload.default_policy or "").strip().lower()
    if policy:
        if policy == "direct":
            return "DIRECT"
        if policy == "proxy":
            return ""
        if policy == "group":
            group = str(payload.default_group or "").strip()
            normalized_contract_id = normalize_contract_id(group)
            if normalized_contract_id and normalized_contract_id != ROUTE_REJECT_ACTION:
                group = _contract_legacy_group_from_repo(
                    repo,
                    normalized_contract_id,
                    scenario_id=scenario_id,
                )
            if group not in QUALITY_GROUPS:
                raise HTTPException(status_code=400, detail="default_group must be one of quality groups")
            return group
        raise HTTPException(status_code=400, detail="invalid default_policy")

    assigned_group = str(payload.assigned_group or "").strip()
    normalized_contract_id = normalize_contract_id(assigned_group)
    if normalized_contract_id and normalized_contract_id != ROUTE_REJECT_ACTION:
        assigned_group = _contract_legacy_group_from_repo(
            repo,
            normalized_contract_id,
            scenario_id=scenario_id,
        )
    if assigned_group not in {*QUALITY_GROUPS, "DIRECT", ""}:
        raise HTTPException(status_code=400, detail="invalid assigned_group")
    if not assigned_group:
        raise HTTPException(status_code=400, detail="assigned_group or default_policy is required")
    return assigned_group


def _normalize_manual_category_rules(rules: list[ManualCategoryRulePayload]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for item in rules or []:
        rule_type = str(item.rule_type or "").strip().upper() or "DOMAIN-SUFFIX"
        value = str(item.value or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail="rule value is required")
        normalized.append(_normalize_category_custom_rule(rule_type, value))
    return normalized


def _normalize_category_custom_rule(rule_type: str, value: str) -> tuple[str, str]:
    normalized_rule_type = str(rule_type or "").strip().upper()
    normalized_value = str(value or "").strip()
    if not normalized_rule_type or not normalized_value:
        raise HTTPException(status_code=400, detail="rule_type and value are required")
    if normalized_rule_type not in _CATEGORY_RULE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"rule_type must be one of: {', '.join(_CATEGORY_RULE_TYPES)}",
        )
    return normalized_rule_type, normalized_value


def _normalize_contract_binding(
    *,
    repo=None,
    scenario_id: str | None = None,
    contract_id: str | None = None,
    business_group: str | None = None,
) -> tuple[str, str]:
    raw_business_group = str(business_group or "").strip()
    if repo is not None:
        normalized_contract_id = _resolve_contract_id_from_repo(repo, contract_id, scenario_id=scenario_id)
        if not normalized_contract_id:
            normalized_contract_id = _resolve_contract_id_from_repo(repo, raw_business_group, scenario_id=scenario_id)
    else:
        normalized_contract_id = normalize_contract_id(contract_id)
        if not normalized_contract_id:
            normalized_contract_id = normalize_contract_id(raw_business_group)
    if not normalized_contract_id and not raw_business_group:
        raise HTTPException(status_code=400, detail="contract_id or business_group is required")
    return normalized_contract_id, (
        _contract_display_name_from_repo(repo, normalized_contract_id, scenario_id=scenario_id)
        if normalized_contract_id
        else raw_business_group
    )


def _normalize_process_rule_items(
    payload: list[SurgeProcessRuleItemPayload],
    *,
    repo=None,
    scenario_id: str | None = None,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for entry in payload:
        contract_id, display_name = _normalize_contract_binding(
            repo=repo,
            scenario_id=scenario_id,
            contract_id=entry.contract_id,
            business_group=entry.business_group,
        )
        match_type = str(entry.match_type or "").strip().upper() or "PROCESS-NAME"
        value = str(entry.value or "").strip()
        if match_type not in SURGE_PROCESS_RULE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"match_type must be one of: {', '.join(SURGE_PROCESS_RULE_TYPES)}",
            )
        if not value:
            raise HTTPException(status_code=400, detail="value is required")
        items.append(
            {
                "id": str(entry.id or "").strip() or uuid4().hex,
                "contract_id": contract_id,
                "contract_display_name": display_name,
                "business_group": display_name,
                "match_type": match_type,
                "value": value,
                "sort_order": int(entry.sort_order or 0),
                "enabled": bool(entry.enabled),
            }
        )
    return items


def _normalize_external_proxy_program_items(
    payload: list[SurgeExternalProxyProgramItemPayload],
    *,
    repo=None,
    scenario_id: str | None = None,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for entry in payload:
        contract_id, display_name = _normalize_contract_binding(
            repo=repo,
            scenario_id=scenario_id,
            contract_id=entry.contract_id,
            business_group=entry.business_group,
        )
        program_path = str(entry.program_path or "").strip()
        if not program_path:
            raise HTTPException(status_code=400, detail="program_path is required")
        args = [str(item).strip() for item in list(entry.args or []) if str(item).strip()]
        items.append(
            {
                "id": str(entry.id or "").strip() or uuid4().hex,
                "contract_id": contract_id,
                "contract_display_name": display_name,
                "business_group": display_name,
                "program_path": program_path,
                "args": args,
                "local_port": int(entry.local_port),
                "name": str(entry.name or "").strip(),
                "sort_order": int(entry.sort_order or 0),
                "enabled": bool(entry.enabled),
            }
        )
    return items


def _business_group_items(repo, scenario_id: str | None = None) -> list[dict[str, object]]:
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    groups = repo.list_scenario_pin_groups(safe_scenario_id)
    assignments = repo.list_scenario_pinned_categories(safe_scenario_id)
    categories_by_group: dict[str, list[str]] = {}
    for item in assignments:
        group_name = str(item.get("pin_group", "") or "").strip()
        category_name = str(item.get("category_name", "") or "").strip()
        if not group_name or not category_name:
            continue
        categories_by_group.setdefault(group_name, []).append(category_name)
    items: list[dict[str, object]] = []
    for sort_order, item in enumerate(groups):
        group_name = str(item.get("group_name", "") or "").strip()
        if not group_name:
            continue
        items.append(
            {
                "name": group_name,
                "sort_order": int(item.get("sort_order", sort_order) or sort_order),
                "mode": str(item.get("mode", BUSINESS_GROUP_MODE_STANDARD) or BUSINESS_GROUP_MODE_STANDARD),
                "description": str(item.get("description", "") or ""),
                "category_names": sorted(categories_by_group.get(group_name, [])),
                # Pin groups are catalog organization, not route-pool bindings.
                # Keep the boundary explicit for clients that share the
                # BusinessGroup shape with policy rendering.
                "pool_names": [],
                "created_by_system": False,
            }
        )
    return items


@router.get("/sources/gorelay")
async def list_gorelay_sources(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    items: list[dict[str, object]] = []
    for item in services.repo.list_gorelay_sources():
        payload = item.to_public_dict()
        payload.update(_gorelay_source_runtime_payload(services, item.id))
        items.append(payload)
    return {"ok": True, "items": items}


@router.post("/sources/gorelay")
async def create_gorelay_source(request: Request, payload: GoRelaySourcePayload) -> dict[str, object]:
    _require_login_if_needed(request)
    selectors_text = payload.selectors_json.strip() or "{}"
    try:
        parsed = json.loads(selectors_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="selectors_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="selectors_json must be a JSON object")

    source = GoRelaySource(
        id=uuid4().hex,
        name=payload.name.strip(),
        login_url=payload.login_url.strip(),
        gorelay_username=payload.gorelay_username.strip(),
        gorelay_password=payload.gorelay_password,
        proxy_username=payload.proxy_username.strip(),
        proxy_password=payload.proxy_password,
        selectors_json=json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        enabled=payload.enabled,
        updated_at=_now(),
    )
    _services(request).repo.save_gorelay_source(source)
    return {"ok": True, "item": source.to_public_dict()}


@router.put("/sources/gorelay/{source_id}")
async def update_gorelay_source(
    request: Request,
    source_id: str,
    payload: GoRelaySourceUpdatePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    selectors_text = payload.selectors_json.strip() or "{}"
    try:
        parsed = json.loads(selectors_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="selectors_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="selectors_json must be a JSON object")

    existing_account = services.repo.get_gorelay_account(source_id)
    existing_source = next(
        (item for item in services.repo.list_gorelay_sources() if item.id == source_id),
        None,
    )

    existing_gorelay_password = (
        existing_account.gorelay_password
        if existing_account
        else (existing_source.gorelay_password if existing_source else "")
    )
    existing_proxy_password = (
        existing_account.proxy_password_default
        if existing_account
        else (existing_source.proxy_password if existing_source else "")
    )

    incoming_gorelay_password = str(payload.gorelay_password or "").strip()
    incoming_proxy_password = str(payload.proxy_password or "").strip()

    source = GoRelaySource(
        id=source_id,
        name=payload.name.strip(),
        login_url=payload.login_url.strip(),
        gorelay_username=payload.gorelay_username.strip(),
        gorelay_password=incoming_gorelay_password or existing_gorelay_password,
        proxy_username=payload.proxy_username.strip(),
        proxy_password=incoming_proxy_password or existing_proxy_password,
        selectors_json=json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        enabled=payload.enabled,
        updated_at=_now(),
    )
    services.repo.save_gorelay_source(source)
    return {"ok": True, "item": source.to_public_dict()}


@router.delete("/sources/gorelay/{source_id}")
async def delete_gorelay_source(request: Request, source_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    _services(request).repo.delete_gorelay_source(source_id)
    return {"ok": True}


@router.get("/sources/standard")
async def list_standard_sources(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    # One source read and one matcher for every row of this response.
    sources = services.repo.list_standard_sources()
    known_secrets = known_source_secrets(sources)
    items = [
        _standard_source_payload(services, item, scenario_id=safe_scenario_id, known_secrets=known_secrets)
        for item in sources
    ]
    return {"ok": True, "items": items}


@router.post("/sources/standard")
async def create_standard_source(
    request: Request,
    payload: StandardSourcePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    target_contract_id, source_mode, quality_group = _normalize_standard_source_target(
        services,
        scenario_id=safe_scenario_id,
        target_contract_id=payload.target_contract_id,
        source_mode=payload.source_mode,
        quality_group=payload.quality_group,
    )
    (
        ingest_kind,
        clash_url,
        shadowrocket_url,
        surge_url,
        login_url,
        manual_nodes_text,
        pull_network_mode,
    ) = _normalize_standard_source_ingest_payload(
        ingest_kind=payload.ingest_kind,
        clash_url=payload.clash_url,
        shadowrocket_url=payload.shadowrocket_url,
        surge_url=payload.surge_url,
        login_url=payload.login_url,
        manual_nodes_text=payload.manual_nodes_text,
        pull_network_mode=payload.pull_network_mode,
        source_mode=source_mode,
    )

    source = StandardSource(
        id=uuid4().hex,
        name=payload.name.strip(),
        clash_url=clash_url,
        shadowrocket_url=shadowrocket_url,
        surge_url=surge_url,
        login_url=login_url,
        quality_group=quality_group,
        target_contract_id=target_contract_id,
        source_mode=source_mode,
        ingest_kind=ingest_kind,
        manual_nodes_text=manual_nodes_text,
        enabled=payload.enabled,
        pull_network_mode=pull_network_mode,
        updated_at=_now(),
    )
    services.repo.save_standard_source(source)
    pull_result: dict[str, object]
    try:
        pull_result = await services.hub_service.refresh_one_standard_source(
            source.id,
            trigger="save",
        )
    except Exception as exc:
        pull_result = {
            "ok": False,
            "error": str(exc),
            "attempts": [],
            "last_success_at": None,
            "pull_method": "",
            "pull_node_count": 0,
        }
    current = services.repo.get_standard_source(source.id) or source
    known_secrets = known_source_secrets(services.repo.list_standard_sources())
    return {
        "ok": True,
        "item": _standard_source_payload(services, current, scenario_id=safe_scenario_id, known_secrets=known_secrets),
        "pull_result": _normalize_pull_result(pull_result, known_secrets),
    }


@router.put("/sources/standard/{source_id}")
async def update_standard_source(
    request: Request,
    source_id: str,
    payload: StandardSourcePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    existing = services.repo.get_standard_source(source_id)
    target_contract_id, source_mode, quality_group = _normalize_standard_source_target(
        services,
        scenario_id=safe_scenario_id,
        target_contract_id=payload.target_contract_id,
        source_mode=payload.source_mode,
        quality_group=payload.quality_group,
        existing_source=existing,
    )
    (
        ingest_kind,
        clash_url,
        shadowrocket_url,
        surge_url,
        login_url,
        manual_nodes_text,
        pull_network_mode,
    ) = _normalize_standard_source_ingest_payload(
        ingest_kind=payload.ingest_kind,
        clash_url=payload.clash_url,
        shadowrocket_url=payload.shadowrocket_url,
        surge_url=payload.surge_url,
        login_url=payload.login_url,
        manual_nodes_text=payload.manual_nodes_text,
        pull_network_mode=payload.pull_network_mode,
        source_mode=source_mode,
        existing_source=existing,
    )

    source = StandardSource(
        id=source_id,
        name=payload.name.strip(),
        clash_url=clash_url,
        shadowrocket_url=shadowrocket_url,
        surge_url=surge_url,
        login_url=login_url,
        quality_group=quality_group,
        target_contract_id=target_contract_id,
        source_mode=source_mode,
        ingest_kind=ingest_kind,
        manual_nodes_text=manual_nodes_text,
        enabled=payload.enabled,
        pull_network_mode=pull_network_mode,
        updated_at=_now(),
    )
    services.repo.save_standard_source(source)
    pull_result: dict[str, object]
    try:
        pull_result = await services.hub_service.refresh_one_standard_source(
            source.id,
            trigger="save",
        )
    except Exception as exc:
        pull_result = {
            "ok": False,
            "error": str(exc),
            "attempts": [],
            "last_success_at": None,
            "pull_method": "",
            "pull_node_count": 0,
        }
    current = services.repo.get_standard_source(source.id) or source
    known_secrets = known_source_secrets(services.repo.list_standard_sources())
    return {
        "ok": True,
        "item": _standard_source_payload(services, current, scenario_id=safe_scenario_id, known_secrets=known_secrets),
        "pull_result": _normalize_pull_result(pull_result, known_secrets),
    }


@router.delete("/sources/standard/{source_id}")
async def delete_standard_source(request: Request, source_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    _services(request).repo.delete_standard_source(source_id)
    return {"ok": True}


@router.post("/sources/standard/{source_id}/pull")
async def pull_standard_source(
    request: Request,
    source_id: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    current = services.repo.get_standard_source(source_id)
    if not current:
        raise HTTPException(status_code=404, detail="standard source not found")
    pull_result: dict[str, object]
    try:
        pull_result = await services.hub_service.refresh_one_standard_source(
            source_id,
            trigger="manual",
        )
    except Exception as exc:
        pull_result = {
            "ok": False,
            "error": str(exc),
            "attempts": [],
            "last_success_at": current.last_success_at,
            "pull_method": "",
            "pull_node_count": 0,
        }
    latest = services.repo.get_standard_source(source_id) or current
    known_secrets = known_source_secrets(services.repo.list_standard_sources())
    return {
        "ok": True,
        "item": _standard_source_payload(services, latest, scenario_id=safe_scenario_id, known_secrets=known_secrets),
        "pull_result": _normalize_pull_result(pull_result, known_secrets),
    }


@router.post("/sources/standard/{source_id}/qr/{field}")
async def upload_standard_source_qr(
    request: Request,
    source_id: str,
    field: str,
    file: UploadFile = File(...),
    detected_url: str = Form(default=""),
) -> dict[str, object]:
    _require_login_if_needed(request)
    field_name = _validate_qr_field(field)
    services = _services(request)
    source = services.repo.get_standard_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="standard source not found")

    ext = _detect_qr_file_extension(file.filename)
    content_type = str(file.content_type or "").strip().lower()
    if content_type not in _QR_ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="unsupported image content type")
    expected_type = _QR_MIME_BY_EXT.get(ext, "")
    if expected_type and content_type != expected_type:
        raise HTTPException(status_code=400, detail="image extension/content-type mismatch")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty image file")
    if len(content) > _QR_MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="image too large (max 4MB)")

    provided_detected_url = str(detected_url or "").strip()
    decoded_detected_url = ""
    if not provided_detected_url:
        decoded_detected_url = _decode_standard_source_qr_url(content)
    final_detected_url = provided_detected_url or decoded_detected_url
    detected_url_source = (
        "provided"
        if provided_detected_url
        else "decoded"
        if decoded_detected_url
        else "none"
    )

    target_dir = services.repo.data_dir / "standard-source-qr" / source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    for stale in target_dir.glob(f"{field_name}.*"):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
    target = target_dir / f"{field_name}{ext}"
    target.write_bytes(content)

    relpath = target.relative_to(services.repo.data_dir).as_posix()
    saved = StandardSourceQrAsset(
        source_id=source_id,
        field=field_name,
        file_relpath=relpath,
        mime_type=_QR_MIME_BY_EXT[ext],
        detected_url=final_detected_url,
        updated_at=_now(),
    )
    services.repo.save_standard_source_qr_asset(saved)

    source_updated = False
    updated_field = ""
    pull_result: dict[str, object] | None = None
    if final_detected_url and _is_supported_subscription_url(final_detected_url):
        source_field = _standard_source_field_by_qr_field(field_name)
        if str(getattr(source, source_field, "") or "").strip() != final_detected_url:
            source_payload = _standard_source_model_payload(source)
            source_payload[source_field] = final_detected_url
            source_payload["updated_at"] = _now()
            services.repo.save_standard_source(StandardSource(**source_payload))
            source = services.repo.get_standard_source(source_id) or source
            source_updated = True
            updated_field = source_field
        try:
            pull_result = await services.hub_service.refresh_one_standard_source(
                source_id,
                trigger="manual",
            )
        except Exception as exc:
            pull_result = {
                "ok": False,
                "error": str(exc),
                "attempts": [],
                "last_success_at": source.last_success_at,
                "pull_method": "",
                "pull_node_count": 0,
            }

    current = services.repo.get_standard_source_qr_asset(source_id, field_name)
    return {
        "ok": True,
        "item": _qr_asset_payload(source_id, field_name, current),
        "detected_url_source": detected_url_source,
        "source_updated": source_updated,
        "updated_field": updated_field,
        "pull_result": _normalize_pull_result(pull_result, known_source_secrets(services.repo.list_standard_sources())) if pull_result else None,
    }


@router.get("/sources/standard/{source_id}/qr/{field}")
async def get_standard_source_qr(
    request: Request,
    source_id: str,
    field: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    field_name = _validate_qr_field(field)
    services = _services(request)
    source = services.repo.get_standard_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="standard source not found")
    asset = services.repo.get_standard_source_qr_asset(source_id, field_name)
    if not asset:
        raise HTTPException(status_code=404, detail="qr asset not found")
    return {"ok": True, "item": _qr_asset_payload(source_id, field_name, asset)}


@router.delete("/sources/standard/{source_id}/qr/{field}")
async def delete_standard_source_qr(
    request: Request,
    source_id: str,
    field: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    field_name = _validate_qr_field(field)
    services = _services(request)
    source = services.repo.get_standard_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="standard source not found")

    asset = services.repo.get_standard_source_qr_asset(source_id, field_name)
    services.repo.delete_standard_source_qr_asset(source_id, field_name)
    if asset:
        target = _resolve_qr_asset_path(services.repo.data_dir, asset.file_relpath)
        if target.exists():
            target.unlink()
    qr_dir = services.repo.data_dir / "standard-source-qr" / source_id
    if qr_dir.exists() and not any(qr_dir.iterdir()):
        qr_dir.rmdir()
    return {"ok": True}


@router.get("/sources/standard/{source_id}/qr/{field}/image")
async def get_standard_source_qr_image(
    request: Request,
    source_id: str,
    field: str,
) -> FileResponse:
    _require_login_if_needed(request)
    field_name = _validate_qr_field(field)
    services = _services(request)
    source = services.repo.get_standard_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="standard source not found")
    asset = services.repo.get_standard_source_qr_asset(source_id, field_name)
    if not asset:
        raise HTTPException(status_code=404, detail="qr asset not found")
    target = _resolve_qr_asset_path(services.repo.data_dir, asset.file_relpath)
    if not target.exists():
        raise HTTPException(status_code=404, detail="qr image file not found")
    return FileResponse(path=str(target), media_type=asset.mime_type)


@router.get("/rules/metadata")
async def get_rule_metadata(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return {
        "ok": True,
        "category_rule_types": list(_CATEGORY_RULE_TYPES),
    }


@router.get("/rules/categories")
async def list_rule_categories(
    request: Request,
    q: str = Query(default=""),
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    items = services.repo.list_scenario_categories(safe_scenario_id)
    if q:
        query = q.casefold()
        items = [item for item in items if query in item.name.casefold()]
    category_custom_counts: dict[str, int] = {}
    for item in services.repo.list_scenario_custom_rules(safe_scenario_id):
        category_name = str(item.category_name or "").strip()
        if category_name:
            category_custom_counts[category_name] = category_custom_counts.get(category_name, 0) + 1
    pinned = services.repo.list_scenario_pinned_categories(safe_scenario_id)
    catalog_map = {
        item.category_name: item for item in services.repo.list_scenario_service_catalog_entries(safe_scenario_id)
    }
    pin_group_meta = _pin_group_meta_map(services, safe_scenario_id)
    pending_reviews = services.repo.list_rule_category_directness_reviews(
        status=RULE_DIRECTNESS_REVIEW_STATUS_PENDING
    )
    pending_map = {item.category_name: item for item in pending_reviews}
    pin_map = {p["category_name"]: p for p in pinned}
    # Every row maps three group references and its effective contract to
    # display names.  Read the scenario's contracts once per request: resolving
    # them per row re-reads every contract and view, thousands of queries for a
    # few hundred categories.
    contracts = scenario_contract_lookup(services.repo, safe_scenario_id)
    payload_items = []
    for item in items:
        payload = item.to_dict()
        states = _derive_rule_category_states(item)
        public_states = _public_rule_category_states(states, contracts=contracts)
        payload["system_default_group"] = public_states["system_state"]["group"]
        payload["system_default_locked"] = public_states["system_state"]["locked"]
        payload["override_group"] = public_states["override_state"]["group"]
        payload["override_active"] = public_states["override_state"]["active"]
        payload["system_state"] = public_states["system_state"]
        payload["override_state"] = public_states["override_state"]
        payload["effective_state"] = public_states["effective_state"]
        payload["can_restore_system_default"] = states["can_restore_system_default"]
        payload["assigned_group"] = public_states["effective_state"]["group"]
        payload["locked"] = public_states["effective_state"]["locked"]
        payload["lock_source"] = public_states["effective_state"]["lock_source"]
        payload["directness_override"] = states["directness_override"]
        payload["current_effective_directness"] = public_states["effective_state"]["directness"]
        payload["current_decision_source"] = states["current_decision_source"]
        payload["custom_rule_count"] = int(category_custom_counts.get(item.name, 0))
        pin = pin_map.get(item.name)
        catalog_entry = catalog_map.get(item.name)
        contract_payload = _effective_contract_payload(
            category=item,
            catalog_entry=catalog_entry,
            pin_group_meta=pin_group_meta,
            current_directness=states["effective_state"]["directness"],
        )
        effective_catalog_group = _effective_catalog_group(catalog_entry, pin)
        payload["pinned"] = pin is not None
        payload["pin_group"] = effective_catalog_group
        payload["pin_sort_order"] = pin["sort_order"] if pin else 0
        payload["catalog_group"] = effective_catalog_group
        payload["catalog_group_mode"] = contract_payload["catalog_group_mode"]
        payload["contract_id"] = contract_payload["stored_contract_id"]
        payload["stored_contract_id"] = contract_payload["stored_contract_id"]
        payload["effective_contract"] = contract_payload["effective_contract_id"]
        payload["effective_contract_id"] = contract_payload["effective_contract_id"]
        payload["effective_contract_display_name"] = contracts.display_name(contract_payload["effective_contract_id"])
        payload["effective_contract_source"] = contract_payload["effective_contract_source"]
        payload["system_contract"] = normalize_contract_id(states["system_state"]["group"])
        payload["override_contract"] = normalize_contract_id(states["override_state"]["group"])
        pending = pending_map.get(item.name)
        payload["pending_directness_review"] = pending.proposed_decision if pending else ""
        payload["pending_directness_confidence"] = pending.confidence if pending else ""
        payload_items.append(payload)
    return {
        "ok": True,
        "items": payload_items,
        "count": len(items),
    }


@router.get("/rules/categories/{name}/preview")
async def preview_rule_category_raw_rules(
    request: Request,
    name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=_CATEGORY_PREVIEW_DEFAULT_LIMIT, ge=1),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    category = services.repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")

    page_limit = min(int(limit), _CATEGORY_PREVIEW_MAX_LIMIT)
    start = int(offset)

    if category.category_type == RULE_CATEGORY_TYPE_MANUAL:
        return {
            "ok": True,
            "category": category.to_dict(),
            "total": 0,
            "offset": start,
            "limit": page_limit,
            "has_more": False,
            "items": [],
        }

    rules = await services.rule_catalog.get_category_raw_rules(category.name)
    total = len(rules)
    if start >= total:
        items: list[str] = []
    else:
        items = rules[start : start + page_limit]
    return {
        "ok": True,
        "category": category.to_dict(),
        "total": total,
        "offset": start,
        "limit": page_limit,
        "has_more": (start + len(items)) < total,
        "items": items,
    }


@router.put("/rules/categories/{name}")
async def assign_rule_category(
    request: Request,
    name: str,
    payload: CategoryAssignPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    category = next(
        (item for item in services.repo.list_scenario_categories(safe_scenario_id) if item.name == name),
        None,
    )
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    states = _derive_rule_category_states(category)
    if states["effective_state"]["locked"]:
        raise HTTPException(status_code=409, detail="category locked")
    allowed_groups = set(QUALITY_GROUPS)
    if category.category_type == RULE_CATEGORY_TYPE_MANUAL:
        allowed_groups.add("DIRECT")
    requested_group = str(payload.assigned_group or "").strip()
    normalized_contract_id = _resolve_contract_id_from_repo(
        services.repo,
        requested_group,
        scenario_id=safe_scenario_id,
    )
    if normalized_contract_id and normalized_contract_id != ROUTE_REJECT_ACTION:
        requested_group = _contract_legacy_group_from_repo(
            services.repo,
            normalized_contract_id,
            scenario_id=safe_scenario_id,
        )
    if requested_group and requested_group not in allowed_groups:
        raise HTTPException(status_code=400, detail="invalid group")
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = services.repo.set_rule_category_override_group(name, requested_group)
    else:
        ok = services.repo.update_scenario_category_assignment(safe_scenario_id, name, requested_group)
    if not ok:
        raise HTTPException(status_code=400, detail="assign failed")
    return {"ok": True}


@router.post("/rules/categories/manual")
async def create_manual_rule_category(
    request: Request,
    payload: ManualCategoryCreatePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    assigned_group = _resolve_manual_category_group(payload, services.repo)
    rules = _normalize_manual_category_rules(payload.rules)
    if rules and assigned_group != RULE_DIRECTNESS_DIRECT:
        raise HTTPException(status_code=409, detail="category route contract required before adding category rules")
    created = services.repo.create_manual_rule_category(
        name,
        assigned_group,
        locked=bool(payload.locked),
    )
    if not created:
        raise HTTPException(status_code=409, detail="category already exists")
    for rule_type, value in rules:
        services.repo.save_custom_rule(
            CustomRule(
                id=uuid4().hex,
                rule_type=rule_type,
                value=value,
                target_group="",
                category_name=created.name,
                created_at=_now(),
            )
        )
    created = services.repo.get_rule_category(created.name) or created
    states = _derive_rule_category_states(created)
    public_states = _public_rule_category_states(states, repo=services.repo)
    custom_rule_count = len(services.repo.list_custom_rules(category_name=created.name))
    catalog_entry = services.repo.get_service_catalog_entry(created.name)
    pin_group_meta = _pin_group_meta_map(services)
    contract_payload = _effective_contract_payload(
        category=created,
        catalog_entry=catalog_entry,
        pin_group_meta=pin_group_meta,
        current_directness=states["effective_state"]["directness"],
    )
    item = created.to_dict()
    item["system_default_group"] = public_states["system_state"]["group"]
    item["system_default_locked"] = public_states["system_state"]["locked"]
    item["override_group"] = public_states["override_state"]["group"]
    item["override_active"] = public_states["override_state"]["active"]
    item["system_state"] = public_states["system_state"]
    item["override_state"] = public_states["override_state"]
    item["effective_state"] = public_states["effective_state"]
    item["can_restore_system_default"] = states["can_restore_system_default"]
    item["assigned_group"] = public_states["effective_state"]["group"]
    item["locked"] = public_states["effective_state"]["locked"]
    item["lock_source"] = public_states["effective_state"]["lock_source"]
    item["directness_override"] = states["directness_override"]
    item["custom_rule_count"] = custom_rule_count
    item["current_effective_directness"] = public_states["effective_state"]["directness"]
    item["current_decision_source"] = states["current_decision_source"]
    item["pinned"] = False
    item["pin_group"] = catalog_entry.catalog_group if catalog_entry else ""
    item["pin_sort_order"] = 0
    item["catalog_group"] = catalog_entry.catalog_group if catalog_entry else ""
    item["catalog_group_mode"] = contract_payload["catalog_group_mode"]
    item["contract_id"] = contract_payload["stored_contract_id"]
    item["stored_contract_id"] = contract_payload["stored_contract_id"]
    item["effective_contract"] = contract_payload["effective_contract_id"]
    item["effective_contract_id"] = contract_payload["effective_contract_id"]
    item["effective_contract_display_name"] = _contract_display_name_from_repo(
        services.repo,
        contract_payload["effective_contract_id"],
    )
    item["effective_contract_source"] = contract_payload["effective_contract_source"]
    item["system_contract"] = normalize_contract_id(states["system_state"]["group"])
    item["override_contract"] = normalize_contract_id(states["override_state"]["group"])
    item["pending_directness_review"] = ""
    item["pending_directness_confidence"] = ""
    return {"ok": True, "item": item}


@router.put("/rules/categories/manual/{name}/rename")
async def rename_manual_rule_category(
    request: Request,
    name: str,
    payload: ManualCategoryRenamePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    old = _services(request).repo.get_rule_category(name)
    if not old:
        raise HTTPException(status_code=404, detail="category not found")
    if old.category_type != RULE_CATEGORY_TYPE_MANUAL:
        raise HTTPException(status_code=409, detail="only manual categories can be renamed")
    if name == new_name:
        return {"ok": True}
    ok = _services(request).repo.rename_manual_rule_category(name, new_name)
    if not ok:
        raise HTTPException(status_code=409, detail="rename failed")
    return {"ok": True}


@router.delete("/rules/categories/manual/{name}")
async def delete_manual_rule_category(
    request: Request,
    name: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    category = _services(request).repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    if category.category_type != RULE_CATEGORY_TYPE_MANUAL:
        raise HTTPException(status_code=409, detail="only manual categories can be deleted")
    ok = _services(request).repo.delete_manual_rule_category(name)
    if not ok:
        raise HTTPException(status_code=404, detail="category not found")
    return {"ok": True}


@router.post("/rules/categories/{name}/restore-system-default")
async def restore_rule_category_system_default(
    request: Request,
    name: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    category = services.repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    if category.category_type != RULE_CATEGORY_TYPE_AUTO:
        raise HTTPException(status_code=409, detail="only auto categories can be restored")
    states = _derive_rule_category_states(category)
    if not states["can_restore_system_default"]:
        raise HTTPException(status_code=409, detail="category has no override")
    if states["effective_state"]["locked"] and states["effective_state"]["lock_source"] == RULE_LOCK_SOURCE_MANUAL:
        raise HTTPException(status_code=409, detail="category locked")
    ok = services.repo.restore_rule_category_system_default(name)
    if not ok:
        raise HTTPException(status_code=409, detail="restore failed")
    return {"ok": True}


@router.put("/rules/categories/{name}/lock")
async def lock_rule_category(
    request: Request,
    name: str,
    payload: dict[str, object],
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    category = next(
        (item for item in services.repo.list_scenario_categories(safe_scenario_id) if item.name == name),
        None,
    )
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    states = _derive_rule_category_states(category)
    locked = bool(payload.get("locked", True))
    if states["effective_state"]["lock_source"] == RULE_LOCK_SOURCE_SYSTEM:
        raise HTTPException(status_code=409, detail="category system locked")
    ok = services.repo.update_scenario_category_locked(
        safe_scenario_id,
        name,
        locked,
        lock_source="manual" if locked else "",
    )
    if not ok:
        raise HTTPException(status_code=404, detail="category not found")
    return {"ok": True, "locked": locked}


@router.post("/rules/categories/bulk-assign")
async def bulk_assign_rule_categories(
    request: Request,
    payload: BulkAssignPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        try:
            updated, skipped_locked = services.rule_catalog.bulk_assign(payload.assignments)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "updated": updated, "skipped_locked": skipped_locked}

    existing = {item.name: item for item in services.repo.list_scenario_categories(safe_scenario_id)}
    skipped_locked: list[str] = []
    filtered: dict[str, str] = {}
    for name, group in (payload.assignments or {}).items():
        item = existing.get(name)
        if not item:
            continue
        if bool(_derive_rule_category_states(item)["effective_state"]["locked"]):
            skipped_locked.append(name)
            continue
        filtered[name] = group

    for name, group in filtered.items():
        item = existing.get(name)
        allowed = set(QUALITY_GROUPS)
        if item and item.category_type == RULE_CATEGORY_TYPE_MANUAL:
            allowed.add(RULE_DIRECTNESS_DIRECT)
        requested_group = str(group or "").strip()
        normalized_contract_id = _resolve_contract_id_from_repo(
            services.repo,
            requested_group,
            scenario_id=safe_scenario_id,
        )
        if normalized_contract_id and normalized_contract_id != ROUTE_REJECT_ACTION:
            requested_group = _contract_legacy_group_from_repo(
                services.repo,
                normalized_contract_id,
                scenario_id=safe_scenario_id,
            )
        if requested_group and requested_group not in allowed:
            raise HTTPException(status_code=400, detail="invalid quality group in assignments")
        filtered[name] = requested_group

    updated = 0
    for name, group in filtered.items():
        if services.repo.update_scenario_category_assignment(safe_scenario_id, name, group):
            updated += 1
    return {"ok": True, "updated": updated, "skipped_locked": skipped_locked}


@router.put("/service-catalog/bulk-groups")
async def bulk_update_service_catalog_groups(
    request: Request,
    payload: ServiceCatalogBulkGroupPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    scenario = _resolve_scenario_context(request, scenario_id)
    existing = {item.name for item in services.repo.list_scenario_categories(scenario.id)}
    valid: dict[str, str] = {}
    invalid: list[str] = []

    for key, value in (payload.assignments or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        if name not in existing:
            invalid.append(name)
            continue
        valid[name] = str(value or "").strip()

    if scenario.id == _DEFAULT_SCENARIO_ID:
        updated = services.repo.bulk_update_service_catalog_groups(valid)
    else:
        updated = services.repo.bulk_update_scenario_service_catalog_groups(scenario.id, valid)
    return {"ok": True, "updated": updated, "invalid": invalid}


@router.post("/rules/refresh")
async def refresh_rules(
    request: Request,
    payload: RuleRefreshPayload | None = None,
) -> dict[str, object]:
    _require_login_if_needed(request)
    mode = payload.mode if payload else "incremental"
    result = await _services(request).rule_catalog.refresh_categories(force=True, mode=mode)
    response = {"ok": bool(result.get("ok")) and not bool(result.get("failed_count")), "result": result}
    if not response["ok"]:
        return JSONResponse(status_code=502, content=response)
    return response


@router.get("/rules/export")
async def export_rules_assignment(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    payload = _services(request).rule_catalog.export_assignment_payload()
    return {"ok": True, "data": payload, **payload}


@router.post("/rules/import")
async def import_rules_assignment(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = _services(request).rule_catalog.import_assignment_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.get("/rules/directness/export")
async def export_directness_reviews(
    request: Request,
    scope: str = Query(default="all"),
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        payload = _services(request).rule_catalog.export_directness_review_payload(scope=scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": payload, **payload}


@router.post("/rules/directness/import")
async def import_directness_reviews(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = _services(request).rule_catalog.import_directness_review_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.get("/rules/directness/reviews")
async def list_directness_reviews(
    request: Request,
    status: str = Query(default=RULE_DIRECTNESS_REVIEW_STATUS_PENDING),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    reviews = services.rule_catalog.list_directness_reviews(status=status)
    categories = {item.name: item for item in services.rule_catalog.list_categories()}
    items: list[dict[str, object]] = []
    for review in reviews:
        payload = review.to_dict()
        category = categories.get(review.category_name)
        if category:
            states = _derive_rule_category_states(category)
            payload["current_effective_directness"] = states["effective_state"]["directness"]
            payload["current_group"] = states["effective_state"]["group"]
            payload["system_directness"] = states["system_state"]["directness"]
            payload["current_decision_source"] = states["current_decision_source"]
        items.append(payload)
    return {
        "ok": True,
        "items": items,
        "count": len(reviews),
    }


@router.post("/rules/directness/reviews/apply")
async def apply_directness_reviews(
    request: Request,
    payload: DirectnessReviewApplyPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = _services(request).rule_catalog.apply_directness_reviews(
            review_ids=payload.review_ids,
            action=payload.action,
            lock_after_apply=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.get("/rules/custom")
async def list_custom_rules(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    services = _services(request)
    items = services.repo.list_scenario_custom_rules(
        safe_scenario_id,
        global_only=True,
    )
    contracts = scenario_contract_lookup(services.repo, safe_scenario_id)
    return {"ok": True, "items": [_serialize_custom_rule(item, contracts=contracts) for item in items]}


@router.post("/rules/custom")
async def create_custom_rule(
    request: Request,
    payload: CustomRulePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    target_contract_id = _resolve_contract_id_from_repo(
        services.repo,
        payload.target_contract_id or payload.target_group,
        scenario_id=safe_scenario_id,
    )
    if not target_contract_id:
        raise HTTPException(status_code=400, detail="invalid target_contract_id")
    rule = CustomRule(
        id=uuid4().hex,
        rule_type=payload.rule_type.strip().upper(),
        value=payload.value.strip(),
        target_contract_id=target_contract_id,
        category_name="",
        created_at=_now(),
    )
    repo = services.repo
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        repo.save_custom_rule(rule)
    else:
        repo.save_scenario_custom_rule(safe_scenario_id, rule)
    return {"ok": True, "item": _serialize_custom_rule(rule, contracts=scenario_contract_lookup(repo, safe_scenario_id))}


@router.get("/rules/categories/{name}/custom")
async def list_custom_rules_for_category(
    request: Request,
    name: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    category = services.repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")

    contract_payload = _category_custom_rule_contract_payload(
        services,
        category=category,
        scenario_id=scenario_id,
    )
    items = services.repo.list_scenario_custom_rules(
        _scenario_id_or_default(scenario_id),
        category_name=category.name,
    )
    payload_items = [_serialize_category_custom_rule(item, contract_payload=contract_payload) for item in items]
    category_payload = {
        "name": category.name,
        "effective_contract_id": str(contract_payload["effective_contract_id"] or ""),
        "effective_contract_display_name": str(contract_payload["effective_contract_display_name"] or ""),
        "effective_contract_source": str(contract_payload["effective_contract_source"] or ""),
        "active": bool(contract_payload["active"]),
    }
    return {
        "ok": True,
        "category": category_payload,
        "items": payload_items,
    }


@router.post("/rules/categories/{name}/custom")
async def create_custom_rule_for_category(
    request: Request,
    name: str,
    payload: CategoryCustomRulePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    category = services.repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    contract_payload = _category_custom_rule_contract_payload(
        services,
        category=category,
        scenario_id=scenario_id,
    )
    _require_category_custom_rule_contract(contract_payload)

    rule_type, value = _normalize_category_custom_rule(payload.rule_type, payload.value)

    rule = CustomRule(
        id=uuid4().hex,
        rule_type=rule_type,
        value=value,
        target_group="",
        category_name=category.name,
        created_at=_now(),
    )
    if _scenario_id_or_default(scenario_id) == _DEFAULT_SCENARIO_ID:
        services.repo.save_custom_rule(rule)
    else:
        services.repo.save_scenario_custom_rule(_scenario_id_or_default(scenario_id), rule)
    item_payload = _serialize_category_custom_rule(rule, contract_payload=contract_payload)
    return {"ok": True, "item": item_payload}


@router.post("/rules/categories/{name}/custom/bulk")
async def create_custom_rules_for_category_bulk(
    request: Request,
    name: str,
    payload: CategoryCustomRuleBulkPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    category = services.repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    if not payload.items:
        raise HTTPException(status_code=400, detail="items is required")
    contract_payload = _category_custom_rule_contract_payload(
        services,
        category=category,
        scenario_id=scenario_id,
    )
    _require_category_custom_rule_contract(contract_payload)

    dedupe = bool(payload.dedupe)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    existing_keys = {
        (str(item.rule_type or "").strip().upper(), str(item.value or "").strip())
        for item in services.repo.list_scenario_custom_rules(safe_scenario_id, category_name=category.name)
    }
    seen_keys = set(existing_keys) if dedupe else set()
    created_items: list[dict[str, object]] = []
    skipped_count = 0

    for entry in payload.items:
        rule_type, value = _normalize_category_custom_rule(entry.rule_type, entry.value)
        key = (rule_type, value)
        if dedupe and key in seen_keys:
            skipped_count += 1
            continue
        seen_keys.add(key)
        rule = CustomRule(
            id=uuid4().hex,
            rule_type=rule_type,
            value=value,
            target_group="",
            category_name=category.name,
            created_at=_now(),
        )
        if safe_scenario_id == _DEFAULT_SCENARIO_ID:
            services.repo.save_custom_rule(rule)
        else:
            services.repo.save_scenario_custom_rule(safe_scenario_id, rule)
        created_items.append(_serialize_category_custom_rule(rule, contract_payload=contract_payload))

    return {
        "ok": True,
        "created_count": len(created_items),
        "skipped_count": skipped_count,
        "items": created_items,
    }


@router.delete("/rules/custom/{rule_id}")
async def delete_custom_rule(
    request: Request,
    rule_id: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    if _scenario_id_or_default(scenario_id) == _DEFAULT_SCENARIO_ID:
        repo.delete_custom_rule(rule_id)
    else:
        repo.delete_scenario_custom_rule(_scenario_id_or_default(scenario_id), rule_id)
    return {"ok": True}


# -- pinned categories --


@router.get("/rules/pins")
async def list_pins(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    return {
        "ok": True,
        "pinned": repo.list_scenario_pinned_categories(safe_scenario_id),
        "groups": repo.list_scenario_pin_groups(safe_scenario_id),
    }


@router.get("/rules/business-groups")
async def list_business_groups(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    return {
        "ok": True,
        "items": _business_group_items(repo, safe_scenario_id),
        "assignments": repo.list_scenario_pinned_categories(safe_scenario_id),
    }


@router.post("/rules/pin-groups")
async def create_pin_group(
    request: Request,
    payload: CreatePinGroupPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    name = payload.group_name.strip()
    mode = _normalize_business_group_mode(payload.mode)
    description = str(payload.description or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="group_name is required")
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        created = repo.create_pin_group(name, mode=mode, description=description)
    else:
        created = repo.create_scenario_pin_group(
            safe_scenario_id,
            name,
            mode=mode,
            description=description,
        )
    if not created:
        raise HTTPException(status_code=409, detail="group already exists")
    return {"ok": True, "group_name": name, "mode": mode, "description": description}


@router.post("/rules/business-groups")
async def create_business_group(
    request: Request,
    payload: CreateBusinessGroupPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    name = payload.name.strip()
    mode = _normalize_business_group_mode(payload.mode)
    description = str(payload.description or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    repo = _services(request).repo
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        created = repo.create_pin_group(name, mode=mode, description=description)
    else:
        created = repo.create_scenario_pin_group(
            safe_scenario_id,
            name,
            mode=mode,
            description=description,
        )
    if not created:
        raise HTTPException(status_code=409, detail="business group already exists")
    return {"ok": True, "item": {"name": name, "mode": mode, "description": description}}


@router.put("/rules/categories/{name}/pin")
async def pin_category(
    request: Request,
    name: str,
    payload: PinCategoryPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    category = repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        repo.pin_category(name, payload.pin_group, payload.sort_order)
    else:
        repo.pin_scenario_category(safe_scenario_id, name, payload.pin_group, payload.sort_order)
    return {"ok": True}


@router.put("/rules/categories/{name}/business-group")
async def assign_business_group(
    request: Request,
    name: str,
    payload: BusinessGroupAssignPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    category = repo.get_rule_category(name)
    if not category:
        raise HTTPException(status_code=404, detail="category not found")
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        repo.pin_category(name, payload.business_group, payload.sort_order)
    else:
        repo.pin_scenario_category(
            safe_scenario_id,
            name,
            payload.business_group,
            payload.sort_order,
        )
    return {"ok": True}


@router.delete("/rules/categories/{name}/pin")
async def unpin_category(
    request: Request,
    name: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = repo.unpin_category(name)
    else:
        ok = repo.unpin_scenario_category(safe_scenario_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail="category not pinned")
    return {"ok": True}


@router.delete("/rules/categories/{name}/business-group")
async def unassign_business_group(
    request: Request,
    name: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = repo.unpin_category(name)
    else:
        ok = repo.unpin_scenario_category(safe_scenario_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail="category not assigned to business group")
    return {"ok": True}


@router.put("/rules/pins/reorder")
async def reorder_pins(
    request: Request,
    payload: PinReorderPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        repo.save_pinned_categories_bulk(payload.items)
    else:
        repo.save_scenario_pinned_categories_bulk(safe_scenario_id, payload.items)
    return {"ok": True}


@router.put("/rules/pin-groups/{name}/rename")
async def rename_pin_group(
    request: Request,
    name: str,
    payload: PinGroupRenamePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    new_name = payload.new_name.strip()
    mode = _normalize_business_group_mode(payload.mode) if payload.mode is not None else None
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = repo.rename_pin_group(
            name,
            new_name,
            mode=mode,
            description=payload.description,
        )
    else:
        ok = repo.rename_scenario_pin_group(
            safe_scenario_id,
            name,
            new_name,
            mode=mode,
            description=payload.description,
        )
    if not ok:
        raise HTTPException(status_code=404, detail="group not found")
    return {"ok": True}


@router.put("/rules/business-groups/{name}/rename")
async def rename_business_group(
    request: Request,
    name: str,
    payload: BusinessGroupRenamePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    new_name = payload.new_name.strip()
    mode = _normalize_business_group_mode(payload.mode) if payload.mode is not None else None
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = repo.rename_pin_group(
            name,
            new_name,
            mode=mode,
            description=payload.description,
        )
    else:
        ok = repo.rename_scenario_pin_group(
            safe_scenario_id,
            name,
            new_name,
            mode=mode,
            description=payload.description,
        )
    if not ok:
        raise HTTPException(status_code=404, detail="business group not found")
    return {"ok": True}


@router.delete("/rules/pin-groups/{name}")
async def delete_pin_group(
    request: Request,
    name: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = repo.delete_pin_group(name)
    else:
        ok = repo.delete_scenario_pin_group(safe_scenario_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail="group not found")
    return {"ok": True}


@router.delete("/rules/business-groups/{name}")
async def delete_business_group(
    request: Request,
    name: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        ok = repo.delete_pin_group(name)
    else:
        ok = repo.delete_scenario_pin_group(safe_scenario_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail="business group not found")
    return {"ok": True}


@router.put("/rules/pin-groups/reorder")
async def reorder_pin_groups(
    request: Request,
    payload: PinGroupOrderPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        repo.save_pin_group_order(payload.items)
    else:
        repo.save_scenario_pin_group_order(safe_scenario_id, payload.items)
    return {"ok": True}


@router.put("/rules/business-groups/reorder")
async def reorder_business_groups(
    request: Request,
    payload: PinGroupOrderPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    if safe_scenario_id == _DEFAULT_SCENARIO_ID:
        repo.save_pin_group_order(payload.items)
    else:
        repo.save_scenario_pin_group_order(safe_scenario_id, payload.items)
    return {"ok": True}


@router.get("/rules/pins/export")
async def export_pins(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return _services(request).rule_catalog.export_pins_payload()


@router.post("/rules/pins/import")
async def import_pins(
    request: Request,
    payload: dict[str, object],
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)

    assignments_raw: object
    if isinstance(payload.get("assignments"), dict):
        assignments_raw = payload["assignments"]
    else:
        assignments_raw = payload

    if not isinstance(assignments_raw, dict):
        raise HTTPException(status_code=400, detail="invalid payload: must be a JSON object")

    existing = {item.name for item in services.rule_catalog.list_categories()}
    valid: dict[str, str] = {}
    invalid: list[str] = []

    for key, value in assignments_raw.items():
        name = str(key or "").strip()
        group = str(value or "").strip()
        if not name or not group:
            continue
        if name not in existing:
            invalid.append(name)
            continue
        valid[name] = group

    count = services.repo.replace_all_pins(valid)
    return {
        "ok": True,
        "pinned": count,
        "invalid": invalid,
    }


@router.get("/pools")
async def list_pools(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    items = [item.to_dict() for item in _services(request).repo.list_pool_statuses()]
    return {"ok": True, "items": items}


@router.get("/contracts")
async def list_contracts(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    items = [item.to_dict() for item in scenario_route_contracts(_services(request).repo, safe_scenario_id)]
    return {"ok": True, "items": items}


@router.post("/contracts")
async def create_contract(
    request: Request,
    payload: ContractCreatePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    owner_scenario_id = "" if safe_scenario_id == _DEFAULT_SCENARIO_ID else safe_scenario_id
    display_name = str(payload.display_name or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name is required")
    contract_id = _next_contract_id(
        services.repo,
        display_name=display_name,
        owner_scenario_id=owner_scenario_id,
    )
    try:
        with services.repo.policy_transaction():
            created = services.repo.create_route_contract(
                RouteContract(
                    id=contract_id,
                    display_name=display_name,
                    description=str(payload.description or "").strip(),
                    strategy_type=str(payload.strategy_type or "").strip(),
                    primary_pools=[str(item or "").strip() for item in payload.primary_pools],
                    fallback_pools=[str(item or "").strip() for item in payload.fallback_pools],
                    failure_action=str(payload.failure_action or "").strip(),
                    editable=True,
                    enabled=bool(payload.enabled),
                    sort_order=int(payload.sort_order or 0),
                    owner_scenario_id=owner_scenario_id,
                    is_system=False,
                    routing_action=payload.routing_action,
                )
            )
            services.repo.save_scenario_route_contract_view(
                safe_scenario_id,
                RouteContractView(
                    scenario_id=safe_scenario_id,
                    contract_id=created.id,
                    display_name=display_name,
                    description=str(payload.description or "").strip(),
                    llm_routing_intent=str(payload.llm_routing_intent or "").strip(),
                    enabled=bool(payload.enabled),
                    sort_order=int(payload.sort_order or 0),
                    is_default=bool(payload.is_default),
                ),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = scenario_route_contract(services.repo, safe_scenario_id, created.id)
    return {"ok": True, "item": saved.to_dict() if saved else created.to_dict()}


@router.put("/contracts/{contract_id}")
async def update_contract(
    request: Request,
    contract_id: str,
    payload: ContractUpdatePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    current = scenario_route_contract(services.repo, safe_scenario_id, contract_id)
    if not current:
        raise HTTPException(status_code=404, detail="contract not found")
    base_contract = services.repo.get_route_contract(current.id)
    if not base_contract:
        raise HTTPException(status_code=404, detail="contract not found")
    next_action = payload.routing_action if payload.routing_action is not None else base_contract.routing_action
    if next_action != "proxy" and any(
        item.resolved_target_contract_id() == current.id for item in services.repo.list_standard_sources()
    ):
        raise HTTPException(status_code=409, detail="contract is used by standard sources; rebind before changing its action")
    next_display_name = str(payload.display_name).strip() if payload.display_name is not None else current.display_name
    next_description = str(payload.description).strip() if payload.description is not None else current.description
    next_enabled = current.enabled if payload.enabled is None else bool(payload.enabled)
    next_sort_order = int(payload.sort_order if payload.sort_order is not None else current.sort_order)
    next_is_default = current.is_default if payload.is_default is None else bool(payload.is_default)
    if not next_enabled and _effective_contract_disable_reference_count(services, safe_scenario_id, current.id) > 0:
        raise HTTPException(status_code=409, detail="contract is still referenced; rebind before disabling")

    has_route_update = any(
        value is not None
        for value in (
            payload.routing_action,
            payload.strategy_type,
            payload.primary_pools,
            payload.fallback_pools,
            payload.failure_action,
        )
    )
    can_edit_topology = _contract_allows_topology_edit(base_contract, scenario_id=safe_scenario_id)
    if has_route_update and not can_edit_topology:
        raise HTTPException(status_code=409, detail="contract topology is managed by its owner scope")
    should_sync_base_contract = (
        safe_scenario_id == _DEFAULT_SCENARIO_ID
        or str(base_contract.owner_scenario_id or "").strip() == safe_scenario_id
    )

    updated = RouteContractView(
        scenario_id=safe_scenario_id,
        contract_id=current.id,
        display_name=next_display_name,
        description=next_description,
        llm_routing_intent=(
            str(payload.llm_routing_intent).strip()
            if payload.llm_routing_intent is not None
            else current.llm_routing_intent
        ),
        enabled=next_enabled,
        sort_order=next_sort_order,
        is_default=next_is_default,
        updated_at=current.updated_at,
    )
    try:
        services.repo.validate_scenario_route_contract_view(safe_scenario_id, updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        with services.repo.policy_transaction():
            if next_action == "reject" and any(
                scenario_default_contract_id(services.repo, item.id) == current.id
                for item in services.repo.list_scenarios()
            ):
                raise HTTPException(status_code=409, detail="select another default before changing its action to reject")
            if has_route_update or should_sync_base_contract:
                services.repo.save_route_contract(
                    RouteContract(
                        id=base_contract.id,
                        display_name=next_display_name if should_sync_base_contract else base_contract.display_name,
                        description=next_description if should_sync_base_contract else base_contract.description,
                        strategy_type=(
                            str(payload.strategy_type).strip()
                            if payload.strategy_type is not None and can_edit_topology
                            else base_contract.strategy_type
                        ),
                        primary_pools=(
                            [str(item or "").strip() for item in payload.primary_pools]
                            if payload.primary_pools is not None and can_edit_topology
                            else [] if next_action != "proxy" else list(base_contract.primary_pools)
                        ),
                        fallback_pools=(
                            [str(item or "").strip() for item in payload.fallback_pools]
                            if payload.fallback_pools is not None and can_edit_topology
                            else [] if next_action != "proxy" else list(base_contract.fallback_pools)
                        ),
                        failure_action=(
                            str(payload.failure_action).strip()
                            if payload.failure_action is not None and can_edit_topology
                            else base_contract.failure_action
                        ),
                        routing_action=payload.routing_action if payload.routing_action is not None and can_edit_topology else base_contract.routing_action,
                        editable=True,
                        enabled=next_enabled if should_sync_base_contract else base_contract.enabled,
                        sort_order=next_sort_order if should_sync_base_contract else base_contract.sort_order,
                        owner_scenario_id=base_contract.owner_scenario_id,
                        is_system=base_contract.is_system,
                        updated_at=base_contract.updated_at,
                    )
                )
            services.repo.save_scenario_route_contract_view(safe_scenario_id, updated)
            if has_route_update and any(
                source.resolved_target_contract_id() == current.id
                for source in services.repo.list_standard_sources()
            ):
                candidate = services.repo.get_route_contract(current.id)
                if candidate is None or not candidate.can_bind_standard_source():
                    raise HTTPException(status_code=409, detail="contract is used by standard sources; rebind before changing its topology")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = scenario_route_contract(services.repo, safe_scenario_id, current.id)
    return {"ok": True, "item": saved.to_dict() if saved else updated.to_dict()}


def _contract_delete_scope(services, contract: RouteContract, scenario_id: str) -> list[str]:
    owner = str(contract.owner_scenario_id or "").strip()
    if owner:
        if owner != scenario_id:
            raise HTTPException(status_code=409, detail="contract can only be deleted from owner scenario")
        return [owner]
    if scenario_id != _DEFAULT_SCENARIO_ID:
        raise HTTPException(status_code=409, detail="global contract must be deleted from default scenario")
    return [item.id for item in services.repo.list_scenarios()]


def _contract_references(services, contract: RouteContract, scenario_ids: list[str]) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for scenario_id in scenario_ids:
        kinds = {
            "service_catalog": sum(item.contract_id == contract.id for item in services.repo.list_scenario_service_catalog_entries(scenario_id)),
            "custom_rules": sum(item.resolved_target_contract_id() == contract.id for item in services.repo.list_scenario_custom_rules(scenario_id)),
            "process_rules": sum(normalize_contract_id(item.get("contract_id")) == contract.id for item in services.repo.list_scenario_process_rules(scenario_id)),
            "external_proxy_programs": sum(normalize_contract_id(item.get("contract_id")) == contract.id for item in services.repo.list_scenario_external_proxy_programs(scenario_id)),
            "default": int(scenario_default_contract_id(services.repo, scenario_id) == contract.id),
        }
        references.extend({"kind": kind, "count": count, "scenario_id": scenario_id} for kind, count in kinds.items() if count)
    source_count = sum(item.resolved_target_contract_id() == contract.id for item in services.repo.list_standard_sources())
    if source_count:
        references.append({"kind": "standard_sources", "count": source_count, "scenario_id": contract.owner_scenario_id or _DEFAULT_SCENARIO_ID})
    return references


@router.get("/contracts/{contract_id}/references")
async def contract_references(
    request: Request,
    contract_id: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    contract = scenario_route_contract(services.repo, safe_scenario_id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    scope = _contract_delete_scope(services, contract, safe_scenario_id)
    refs = _contract_references(services, contract, scope)
    data_refs = [item for item in refs if item["kind"] != "default"]
    default_needs_replacement = any(
        item["kind"] == "default" and any(
            candidate.id != contract.id and candidate.enabled and candidate.routing_action != "reject"
            for candidate in scenario_route_contracts(services.repo, str(item["scenario_id"]))
        )
        for item in refs
    )
    return {"references": refs, "is_default": any(item["kind"] == "default" for item in refs), "can_delete": not data_refs and not default_needs_replacement}


def _replace_contract_references(services, scenario_id: str, from_id: str, to_id: str) -> None:
    _rebind_service_catalog_contracts(services, scenario_id, from_id, to_id)
    _rebind_custom_rules(services, scenario_id, from_id, to_id)
    _rebind_process_rules(services, scenario_id, from_id, to_id)
    _rebind_external_proxy_programs(services, scenario_id, from_id, to_id)


@router.delete("/contracts/{contract_id}")
async def delete_contract(
    request: Request,
    contract_id: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
    replacement_contract_id: str | None = Query(default=None),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    try:
        with services.repo.policy_transaction():
            current = scenario_route_contract(services.repo, safe_scenario_id, contract_id)
            if current is None:
                raise HTTPException(status_code=404, detail="contract not found")
            scope = _contract_delete_scope(services, current, safe_scenario_id)
            refs = _contract_references(services, current, scope)
            default_scopes = [str(item["scenario_id"]) for item in refs if item["kind"] == "default"]
            data_refs = [item for item in refs if item["kind"] != "default"]
            if not replacement_contract_id:
                if data_refs:
                    raise HTTPException(status_code=409, detail="contract is still referenced; rebind before deleting")
                for affected in default_scopes:
                    candidates = [item for item in scenario_route_contracts(services.repo, affected) if item.id != current.id and item.enabled and item.routing_action != "reject"]
                    if candidates:
                        raise HTTPException(status_code=409, detail="default contract requires an explicit replacement before deleting")
            else:
                target = scenario_route_contract(services.repo, safe_scenario_id, replacement_contract_id)
                if target is None or target.id == current.id or not target.enabled:
                    raise HTTPException(status_code=400, detail="replacement must be a different enabled contract")
                if not current.owner_scenario_id and target.owner_scenario_id:
                    raise HTTPException(status_code=409, detail="global contract replacement must be global")
                if any(item["kind"] == "standard_sources" for item in refs) and not target.can_bind_standard_source():
                    raise HTTPException(status_code=409, detail="replacement is not usable by standard sources")
                for affected in scope:
                    affected_refs = [item for item in refs if item["scenario_id"] == affected]
                    visible_target = scenario_route_contract(services.repo, affected, target.id)
                    if affected_refs and (visible_target is None or not visible_target.enabled):
                        raise HTTPException(status_code=409, detail="replacement must be enabled in every affected scenario")
                    if affected in default_scopes and target.routing_action == "reject":
                        raise HTTPException(status_code=409, detail="reject contract cannot be a default replacement")
                # All eligibility checks precede writes; repo transaction also protects against mid-write errors.
                for affected in scope:
                    _replace_contract_references(services, affected, current.id, target.id)
                for source in services.repo.list_standard_sources():
                    if source.resolved_target_contract_id() == current.id:
                        services.repo.save_standard_source(replace(source, target_contract_id=target.id, quality_group=target.display_name))
                for affected in default_scopes:
                    visible_target = scenario_route_contract(services.repo, affected, target.id)
                    services.repo.save_scenario_route_contract_view(affected, RouteContractView(
                        scenario_id=affected, contract_id=target.id,
                        display_name=visible_target.display_name, description=visible_target.description,
                        llm_routing_intent=visible_target.llm_routing_intent, enabled=True,
                        sort_order=visible_target.sort_order, is_default=True,
                    ))
            services.repo.delete_route_contract(current.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/contracts/{contract_id}/rebind")
async def rebind_contract(
    request: Request,
    contract_id: str,
    payload: ContractRebindPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    current = scenario_route_contract(services.repo, safe_scenario_id, contract_id)
    if not current:
        raise HTTPException(status_code=404, detail="contract not found")
    from_contract_id = current.id
    to_contract_id = _resolve_contract_id_from_repo(services.repo, payload.to_contract_id, scenario_id=safe_scenario_id)
    if not from_contract_id or not to_contract_id or from_contract_id == to_contract_id:
        raise HTTPException(status_code=400, detail="invalid contract rebinding")

    target = scenario_route_contract(services.repo, safe_scenario_id, to_contract_id)
    if target is None or not target.enabled:
        raise HTTPException(status_code=400, detail="replacement must be an enabled contract")
    try:
        with services.repo.policy_transaction():
            service_catalog_count = _rebind_service_catalog_contracts(services, safe_scenario_id, from_contract_id, to_contract_id)
            custom_rule_count = _rebind_custom_rules(services, safe_scenario_id, from_contract_id, to_contract_id)
            process_rule_count = _rebind_process_rules(services, safe_scenario_id, from_contract_id, to_contract_id)
            external_program_count = _rebind_external_proxy_programs(services, safe_scenario_id, from_contract_id, to_contract_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "counts": {
            "service_catalog": service_catalog_count,
            "custom_rules": custom_rule_count,
            "process_rules": process_rule_count,
            "external_proxy_programs": external_program_count,
        },
    }


@router.get("/service-catalog")
async def list_service_catalog(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    scenario = _resolve_scenario_context(request, scenario_id)
    contracts = scenario_contract_lookup(services.repo, scenario.id)
    items = []
    for entry in services.repo.list_scenario_service_catalog_entries(scenario.id):
        payload = entry.to_dict()
        payload["contract_display_name"] = contracts.display_name(entry.contract_id)
        items.append(payload)
    return {"ok": True, "items": items}


@router.put("/service-catalog/{category_name}")
async def update_service_catalog_entry(
    request: Request,
    category_name: str,
    payload: ServiceCatalogUpdatePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    scenario = _resolve_scenario_context(request, scenario_id)
    default_effective = next(
        (
            item
            for item in services.repo.list_scenario_service_catalog_entries(_DEFAULT_SCENARIO_ID)
            if item.category_name == category_name
        ),
        None,
    )
    if scenario.id == _DEFAULT_SCENARIO_ID:
        existing = services.repo.get_service_catalog_entry(category_name)
    else:
        existing = services.repo.get_scenario_service_catalog_override(scenario.id, category_name)
    explicit_empty_scenario_group = (
        scenario.id != _DEFAULT_SCENARIO_ID
        and existing is not None
        and str(existing.catalog_group or "") == ""
    )
    contract_id = _resolve_contract_id_from_repo(
        services.repo,
        payload.contract_id or (existing.contract_id if existing else ""),
        scenario_id=scenario.id,
    )
    if not contract_id:
        raise HTTPException(status_code=400, detail="contract_id is required")
    if payload.catalog_group is not None:
        catalog_group = str(payload.catalog_group or "").strip()
    elif scenario.id == _DEFAULT_SCENARIO_ID:
        catalog_group = str(existing.catalog_group if existing else "").strip()
    elif explicit_empty_scenario_group:
        catalog_group = ""
    else:
        current_catalog_group = str(existing.catalog_group if existing else "")
        inherited_default_catalog_group = str(default_effective.catalog_group if default_effective else "")
        inherited_default_sort_order = int(default_effective.sort_order if default_effective else 0)
        if (
            current_catalog_group not in {"", _SCENARIO_CATALOG_GROUP_INHERIT}
            and current_catalog_group == inherited_default_catalog_group
            and int(existing.sort_order if existing else 0) == inherited_default_sort_order
        ):
            current_catalog_group = _SCENARIO_CATALOG_GROUP_INHERIT
        catalog_group = (
            current_catalog_group
            if current_catalog_group and current_catalog_group != _SCENARIO_CATALOG_GROUP_INHERIT
            else _SCENARIO_CATALOG_GROUP_INHERIT
        )
    if payload.sort_order is not None:
        sort_order = int(payload.sort_order)
    elif scenario.id == _DEFAULT_SCENARIO_ID:
        sort_order = int(existing.sort_order if existing else 0)
    elif explicit_empty_scenario_group:
        sort_order = int(existing.sort_order if existing else 0)
    else:
        current_catalog_group = str(existing.catalog_group if existing else "")
        inherited_default_catalog_group = str(default_effective.catalog_group if default_effective else "")
        inherited_default_sort_order = int(default_effective.sort_order if default_effective else 0)
        if (
            current_catalog_group not in {"", _SCENARIO_CATALOG_GROUP_INHERIT}
            and current_catalog_group == inherited_default_catalog_group
            and int(existing.sort_order if existing else 0) == inherited_default_sort_order
        ):
            current_catalog_group = _SCENARIO_CATALOG_GROUP_INHERIT
        sort_order = int(
            existing.sort_order
            if existing and current_catalog_group != _SCENARIO_CATALOG_GROUP_INHERIT
            else 0
        )
    try:
        if scenario.id == _DEFAULT_SCENARIO_ID:
            saved = services.repo.save_service_catalog_entry(
                ServiceCatalogEntry(
                    category_name=category_name,
                    catalog_group=catalog_group,
                    contract_id=contract_id,
                    sort_order=sort_order,
                    source="manual",
                )
            )
        else:
            saved = services.repo.save_scenario_service_catalog_entry(
                scenario.id,
                ServiceCatalogEntry(
                    category_name=category_name,
                    catalog_group=catalog_group,
                    contract_id=contract_id,
                    sort_order=sort_order,
                    source="manual",
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = saved.to_dict()
    payload["contract_display_name"] = _contract_display_name_from_repo(
        services.repo,
        saved.contract_id,
        scenario_id=scenario.id,
    )
    return {"ok": True, "item": payload}


@router.get("/general-profile")
async def get_general_profile(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    scenario = _resolve_scenario_context(request, scenario_id)
    item = _profile_item_payload(scenario)
    item["is_system_default"] = scenario.id == _DEFAULT_SCENARIO_ID
    return {"ok": True, "item": item}


@router.put("/general-profile")
async def update_general_profile(
    request: Request,
    payload: GeneralProfileUpdatePayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    current = _resolve_scenario_context(request, scenario_id)
    try:
        saved = services.repo.save_scenario(
            ScenarioProfile(
                id=current.id,
                slug=current.slug,
                name=str(payload.name or current.name or "默认场景"),
                description=current.description,
                enabled=current.enabled,
                sort_order=current.sort_order,
                settings=_profile_settings_from_payload(
                    payload,
                    current_settings=current.settings,
                    current_editor_state=current.editor_state,
                    legacy_default=current.id != _DEFAULT_SCENARIO_ID,
                ),
                editor_state=_profile_editor_state_from_payload(
                    payload.editor_state,
                    current_editor_state=current.editor_state,
                    legacy_default=current.id != _DEFAULT_SCENARIO_ID,
                ),
                updated_at=current.updated_at,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    services.repo.invalidate_review_cache(saved.id)
    item = _profile_item_payload(saved)
    item["is_system_default"] = saved.id == _DEFAULT_SCENARIO_ID
    return {"ok": True, "item": item}


@router.post("/general-profile/reset-editor-state")
async def reset_general_profile_editor_state(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    current = _resolve_scenario_context(request, scenario_id)
    saved = services.repo.save_scenario(
        ScenarioProfile(
            id=current.id,
            slug=current.slug,
            name=current.name,
            description=current.description,
            enabled=current.enabled,
            sort_order=current.sort_order,
            settings=normalize_lazycat_profile_settings({}),
            editor_state=default_profile_editor_state(legacy=False),
            updated_at=current.updated_at,
        )
    )
    item = _profile_item_payload(saved)
    item["is_system_default"] = saved.id == _DEFAULT_SCENARIO_ID
    return {"ok": True, "item": item}


@router.get("/profile-capabilities")
async def get_profile_capabilities(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return {"ok": True, **profile_capabilities_payload()}


@router.get("/profile-editor-schema")
async def get_profile_editor_schema(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return {"ok": True, **profile_editor_schema_payload()}


@router.post("/profile-capabilities/preview-decomposition")
async def preview_skip_proxy_decomposition(request: Request) -> dict[str, object]:
    """Preview how the shared skip-proxy truth projects to each client."""
    _require_login_if_needed(request)
    body = await request.json()
    patterns = body.get("patterns", [])
    if not isinstance(patterns, list):
        raise HTTPException(status_code=400, detail="patterns must be a list of strings")
    patterns = [str(p).strip() for p in patterns if str(p).strip()]
    decomp = decompose_skip_proxy(patterns)
    shared_value = ", ".join(decomp.direct_intent_patterns)
    return {
        "ok": True,
        "clients": {
            "surge": {
                "section": "[General]",
                "field": "skip-proxy",
                "value": shared_value,
            },
            "clash": {
                "sections": [
                    {
                        "section": "dns.fake-ip-filter",
                        "entries": decomp.fake_ip_filter_entries,
                    },
                    {
                        "section": "rules",
                        "entries": decomp.direct_rules,
                    },
                ],
                "warnings": decomp.warnings,
            },
            "shadowrocket": {
                "section": "[General]",
                "field": "skip-proxy",
                "value": shared_value,
            },
        },
        "excluded_routes": {
            "section": "Excluded Routes / tun.route-exclude-address",
            "entries": decomp.route_exclude_entries,
        },
    }


@router.get("/general-profiles")
async def list_general_profiles(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    items = [_profile_item_payload(item) for item in _services(request).repo.list_general_profiles()]
    return {"ok": True, "items": items}


@router.get("/general-profiles/{profile_id}")
async def get_general_profile_item(request: Request, profile_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    item = _services(request).repo.get_general_profile(profile_id)
    if not item:
        raise HTTPException(status_code=404, detail="profile not found")
    return {"ok": True, "item": _profile_item_payload(item)}


@router.post("/general-profiles")
async def create_general_profile(
    request: Request,
    payload: GeneralProfileCreatePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        profile = GeneralProfile(
            id=str(uuid4()),
            name=name,
            settings=_profile_settings_from_payload(
                payload,
                current_editor_state=default_profile_editor_state(legacy=True),
                legacy_default=True,
            ),
            editor_state=_profile_editor_state_from_payload(
                payload.editor_state,
                current_editor_state=default_profile_editor_state(legacy=True),
                legacy_default=True,
            ),
            is_system_default=False,
        )
        saved = services.repo.save_general_profile(profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": _profile_item_payload(saved)}


@router.put("/general-profiles/{profile_id}")
async def update_general_profile_item(
    request: Request,
    profile_id: str,
    payload: GeneralProfileUpdatePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    current = services.repo.get_general_profile(profile_id)
    if not current:
        raise HTTPException(status_code=404, detail="profile not found")
    try:
        saved = services.repo.save_general_profile(
            GeneralProfile(
                id=current.id,
                name=str(payload.name or current.name or "Profile"),
                settings=_profile_settings_from_payload(
                    payload,
                    current_settings=current.settings,
                    current_editor_state=current.editor_state,
                    legacy_default=True,
                ),
                editor_state=_profile_editor_state_from_payload(
                    payload.editor_state,
                    current_editor_state=current.editor_state,
                    legacy_default=True,
                ),
                is_system_default=current.is_system_default,
                updated_at=current.updated_at,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    services.repo.invalidate_review_cache(saved.id)
    return {"ok": True, "item": _profile_item_payload(saved)}


@router.post("/general-profiles/{profile_id}/reset-editor-state")
async def reset_general_profile_item_editor_state(
    request: Request,
    profile_id: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    current = services.repo.get_general_profile(profile_id)
    if not current:
        raise HTTPException(status_code=404, detail="profile not found")
    saved = services.repo.save_general_profile(
        GeneralProfile(
            id=current.id,
            name=current.name,
            settings=normalize_lazycat_profile_settings({}),
            editor_state=default_profile_editor_state(legacy=False),
            is_system_default=current.is_system_default,
            updated_at=current.updated_at,
        )
    )
    return {"ok": True, "item": _profile_item_payload(saved)}


@router.delete("/general-profiles/{profile_id}")
async def delete_general_profile(
    request: Request,
    profile_id: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    try:
        deleted = services.repo.delete_general_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="profile not found")
    services.repo.invalidate_review_cache(profile_id)
    return {"ok": True}


@router.get("/scenarios")
async def list_scenarios(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    items = [
        {
            **item.to_dict(),
            "legacy": bool(item.editor_state.get("legacy")),
        }
        for item in _services(request).repo.list_scenarios()
    ]
    return {"ok": True, "items": items}


@router.get("/scenarios/{scenario_id}")
async def get_scenario(request: Request, scenario_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    item = _resolve_scenario_or_404(request, scenario_id)
    return {"ok": True, "item": {**item.to_dict(), "legacy": bool(item.editor_state.get("legacy"))}}


@router.post("/scenarios")
async def create_scenario(request: Request, payload: ScenarioPayload) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    try:
        validate_lazycat_profile_settings_for_write(payload.settings or {})
        legacy_default = bool(payload.settings)
        editor_state = _profile_editor_state_from_payload(
            payload.editor_state,
            current_editor_state=default_profile_editor_state(legacy=legacy_default),
            legacy_default=legacy_default,
        )
        normalized_settings = normalize_lazycat_profile_settings(payload.settings or {})
        if isinstance(payload.editor_state, Mapping):
            normalized_settings = apply_editor_state_to_settings(normalized_settings, editor_state)
        else:
            normalized_settings = harmonize_profile_single_source_settings(normalized_settings)
        scenario = services.repo.save_scenario(
            ScenarioProfile(
                id=str(uuid4()),
                slug=_normalize_scenario_slug(payload.slug),
                name=str(payload.name or "").strip() or "未命名场景",
                description=str(payload.description or ""),
                enabled=bool(payload.enabled),
                sort_order=int(payload.sort_order or 0),
                settings=normalized_settings,
                editor_state=editor_state,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    services.repo.clone_scenario_state(_DEFAULT_SCENARIO_ID, scenario.id)
    scenario = services.repo.get_scenario(scenario.id) or scenario
    return {"ok": True, "item": {**scenario.to_dict(), "legacy": bool(scenario.editor_state.get("legacy"))}}


@router.put("/scenarios/{scenario_id}")
async def update_scenario(request: Request, scenario_id: str, payload: ScenarioPayload) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    current = _resolve_scenario_or_404(request, scenario_id)
    try:
        validate_lazycat_profile_settings_for_write(payload.settings or {})
        editor_state = _profile_editor_state_from_payload(
            payload.editor_state,
            current_editor_state=current.editor_state,
            legacy_default=current.id != _DEFAULT_SCENARIO_ID,
        )
        normalized_settings = normalize_lazycat_profile_settings(payload.settings or current.settings)
        if isinstance(payload.editor_state, Mapping):
            normalized_settings = apply_editor_state_to_settings(
                normalized_settings,
                editor_state,
                current_settings=current.settings,
            )
        else:
            normalized_settings = harmonize_profile_single_source_settings(
                normalized_settings,
                current_settings=current.settings,
            )
        saved = services.repo.save_scenario(
            ScenarioProfile(
                id=current.id,
                slug=_normalize_scenario_slug(payload.slug),
                name=str(payload.name or "").strip() or current.name,
                description=str(payload.description or ""),
                enabled=bool(payload.enabled),
                sort_order=int(payload.sort_order or 0),
                settings=normalized_settings,
                editor_state=editor_state,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": {**saved.to_dict(), "legacy": bool(saved.editor_state.get("legacy"))}}


@router.post("/scenarios/{scenario_id}/reset-editor-state")
async def reset_scenario_editor_state(request: Request, scenario_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    current = _resolve_scenario_or_404(request, scenario_id)
    saved = services.repo.save_scenario(
        ScenarioProfile(
            id=current.id,
            slug=current.slug,
            name=current.name,
            description=current.description,
            enabled=current.enabled,
            sort_order=current.sort_order,
            settings=normalize_lazycat_profile_settings({}),
            editor_state=default_profile_editor_state(legacy=False),
            updated_at=current.updated_at,
        )
    )
    return {"ok": True, "item": {**saved.to_dict(), "legacy": bool(saved.editor_state.get("legacy"))}}


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(request: Request, scenario_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    try:
        deleted = services.repo.delete_scenario(scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="scenario not found")
    return {"ok": True}


@router.post("/review")
async def review_profiles(
    request: Request,
    payload: ReviewPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    api_key = services.repo.get_runtime_setting("review.gemini_api_key") or services.settings.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY not configured")
    target_ids = [str(tid).strip() for tid in (payload.target_profile_ids or []) if str(tid).strip()]
    if not target_ids:
        raise HTTPException(status_code=400, detail="target_profile_ids is required")
    reviews = []
    for target_id in target_ids:
        result = await services.review_service.review(
            primary_profile_id=str(payload.primary_profile_id).strip(),
            target_profile_id=target_id,
        )
        reviews.append(result)
    return {"ok": True, "reviews": reviews}


@router.delete("/review/cache")
async def clear_review_cache(
    request: Request,
    profile_id: str | None = Query(default=None),
) -> dict[str, object]:
    _require_login_if_needed(request)
    _services(request).repo.invalidate_review_cache(
        profile_id=str(profile_id).strip() if profile_id else None,
    )
    return {"ok": True}


@router.get("/settings/review")
async def get_review_settings(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    key_val = repo.get_runtime_setting("review.gemini_api_key") or ""
    model_val = repo.get_runtime_setting("review.review_model") or "gemini-2.0-flash"
    return {
        "ok": True,
        "item": {
            "gemini_api_key_set": bool(key_val),
            "review_model": model_val,
        },
    }


@router.put("/settings/review")
async def update_review_settings(
    request: Request,
    payload: ReviewSettingsPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    repo = _services(request).repo
    key_val = payload.gemini_api_key.strip()
    model_val = payload.review_model.strip() or "gemini-2.0-flash"
    repo.set_runtime_setting("review.gemini_api_key", key_val)
    repo.set_runtime_setting("review.review_model", model_val)
    return {
        "ok": True,
        "item": {
            "gemini_api_key_set": bool(key_val),
            "review_model": model_val,
        },
    }


@router.get("/devices")
async def list_devices(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    scenario = _resolve_device_list_scenario_or_error(services, scenario_id)
    base = resolve_base_url(request, services.settings.app_base_url)
    overlay_status = services.hub_service.get_surge_mac_overlay_status(scenario_id=scenario.id)
    surge_base = resolve_preferred_surge_base_url(
        base,
        getattr(scenario, "settings", {}) if scenario else {},
    )
    items = []
    subscriptions = sorted(
        services.hub_service.list_devices(),
        key=lambda item: (0 if item.enabled else 1, item.device_name.casefold(), item.public_id or item.token),
    )
    for sub in subscriptions:
        subscription_id = sub.public_id or sub.token
        links = build_device_import_links(
            base,
            sub.device_name,
            subscription_id,
            scenario_slug=scenario.slug,
            surge_base_url=surge_base,
        )
        payload = sub.to_dict()
        payload.pop("token", None)
        payload["subscription_id"] = subscription_id
        payload["scenario_id"] = scenario.id
        payload["scenario_slug"] = scenario.slug
        payload["scenario_name"] = scenario.name
        payload["links"] = links
        payload["overlay_status"] = overlay_status.to_dict()
        items.append(payload)
    return {"ok": True, "items": items}


def _resolve_preview_subscription_or_error(services, subscription_id: str):
    sub = services.hub_service.gorelay_service.get_subscription_by_public_id(subscription_id)
    if sub is None:
        sub = services.hub_service.gorelay_service.get_subscription_by_token(subscription_id)
    if sub is None:
        sub = services.repo.get_device_subscription_by_public_id(subscription_id)
    if sub is None:
        sub = services.repo.get_device_subscription_by_token(subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="device subscription not found")
    if not bool(sub.enabled):
        raise HTTPException(status_code=409, detail="device subscription disabled")
    return sub


def _resolve_public_preview_subscription_id(services, subscription_id: str) -> str:
    sub = _resolve_preview_subscription_or_error(services, subscription_id)
    return str(getattr(sub, "public_id", "") or subscription_id or "").strip() or subscription_id


def _resolve_preview_scenario_or_error(services, scenario_id: str | None) -> ScenarioProfile:
    safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
    scenario = services.repo.get_scenario(safe_id)
    if not scenario or not scenario.enabled:
        raise HTTPException(status_code=404, detail="scenario not found")
    return scenario


def _resolve_device_list_scenario_or_error(services, scenario_id: str | None) -> ScenarioProfile:
    safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
    scenario = services.repo.get_scenario(safe_id)
    if scenario and scenario.enabled:
        return scenario
    if safe_id != _DEFAULT_SCENARIO_ID:
        raise HTTPException(status_code=404, detail="scenario not found")
    fallback = next((item for item in services.repo.list_scenarios() if item.enabled), None)
    if fallback is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return fallback


async def _build_device_preview_artifacts(
    request: Request,
    *,
    token: str,
    target: Literal["surge", "clash", "shadowrocket"],
    scenario_id: str | None = None,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_preview_subscription_id(services, token)
    sub = _resolve_preview_subscription_or_error(services, subscription_id)
    internal_token = str(sub.token or "").strip()
    scenario = _resolve_preview_scenario_or_error(services, scenario_id)

    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=404, detail="device subscription not found")
    nodes = policy_entry.nodes
    policy_ir = policy_entry.policy_ir
    rules = list(policy_ir.rule_lines)
    profile_settings = normalize_lazycat_profile_settings(scenario.settings or {})
    base_context = resolve_base_url_context(request, services.settings.app_base_url)
    base = str(base_context["base_url"])
    surge_base = resolve_preferred_surge_base_url(base, profile_settings)
    subscription_metadata = {
        "base_url": base,
        "managed_url": "",
        "asset_base_url": "",
        "revision": policy_entry.revision,
        "domain_set_count": 0,
        "rule_set_count": 0,
        "base_url_mismatch_detected": bool(base_context["base_url_mismatch_detected"]),
        "base_url_mismatch_reason": str(base_context["base_url_mismatch_reason"] or ""),
    }

    if target == "surge":
        surge_artifacts = build_surge_profile_artifacts(
            nodes,
            rules,
            f"{surge_base}/sub/device/{subscription_id}/{scenario.slug}/surge.conf",
            local_host_aliases=frozenset(capture_local_host_aliases()),
            profile="lazycat",
            profile_settings=profile_settings,
            policy_ir=policy_ir,
            revision=policy_entry.revision,
            asset_url_builder=_signed_asset_url_builder(
                services,
                base_url=surge_base,
                subscription_id=subscription_id,
                scenario_slug=scenario.slug,
                revision=policy_entry.revision,
            ),
        )
        if surge_artifacts.blocked:
            raise HTTPException(status_code=409, detail=surge_blocked_detail(surge_artifacts))
        content = surge_artifacts.main_conf
        skipped = surge_artifacts.skipped
        warnings = surge_artifacts.diagnostics
        asset_counts = {
            "domain_sets": len(surge_artifacts.domain_sets),
            "rule_sets": len(surge_artifacts.rule_sets),
        }
        subscription_metadata.update(dict(surge_artifacts.subscription_metadata))
    elif target == "clash":
        content, skipped, warnings = build_clash_profile_artifacts(
            nodes,
            rules,
            local_host_aliases=frozenset(capture_local_host_aliases()),
            profile="lazycat",
            profile_settings=profile_settings,
            policy_ir=policy_ir,
            provider_base_url=base,
            subscription_token=internal_token,
            subscription_public_id=subscription_id,
            provider_url_builder=_signed_clash_provider_url_builder(
                services,
                base_url=base,
                subscription_id=subscription_id,
                scenario_slug=scenario.slug,
            ),
            rule_provider_url_builder=_signed_clash_rule_provider_url_builder(
                services,
                base_url=base,
                subscription_id=subscription_id,
                scenario_slug=scenario.slug,
            ),
        )
        if policy_ir is not None:
            blocked_detail = build_clash_blocked_detail(
                policy_ir,
                profile="lazycat",
                profile_settings=profile_settings,
                provider_base_url=base,
                subscription_token=internal_token,
                subscription_public_id=subscription_id,
                provider_url_builder=_signed_clash_provider_url_builder(
                    services,
                    base_url=base,
                    subscription_id=subscription_id,
                    scenario_slug=scenario.slug,
                ),
                rendered_content=content,
                rendered_warnings=warnings,
            )
            if blocked_detail["blockers"]:
                raise HTTPException(status_code=409, detail=blocked_detail)
        asset_counts = {"domain_sets": 0, "rule_sets": 0}
    else:
        shadowrocket_artifacts = build_shadowrocket_profile_artifacts(
            nodes,
            rules,
            f"{base}/sub/device/{subscription_id}/{scenario.slug}/shadowrocket.conf",
            local_host_aliases=frozenset(capture_local_host_aliases()),
            profile="lazycat",
            profile_settings=profile_settings,
            policy_ir=policy_ir,
        )
        if shadowrocket_artifacts.blocked_detail["blockers"]:
            raise HTTPException(status_code=409, detail=shadowrocket_artifacts.blocked_detail)
        content = shadowrocket_artifacts.content
        skipped = shadowrocket_artifacts.skipped
        warnings = shadowrocket_artifacts.diagnostics
        asset_counts = {"domain_sets": 0, "rule_sets": 0}

    return {
        "revision": policy_entry.revision,
        "scenario_id": scenario.id,
        "scenario_slug": scenario.slug,
        "scenario_name": scenario.name,
        "target": target,
        "subscription_metadata": subscription_metadata,
        "content": content,
        "skipped": skipped,
        "policy_ir": policy_ir,
        "warnings": warnings,
        "asset_counts": asset_counts,
    }


async def _build_device_clash_bundle_artifacts(
    request: Request,
    *,
    token: str,
    scenario_id: str | None = None,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    hub = services.hub_service
    subscription_id = _resolve_public_preview_subscription_id(services, token)
    sub = _resolve_preview_subscription_or_error(services, subscription_id)
    internal_token = str(sub.token or "").strip()
    scenario = _resolve_preview_scenario_or_error(services, scenario_id)

    policy_entry = await hub.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=404, detail="device subscription not found")
    nodes = policy_entry.nodes
    policy_ir = policy_entry.policy_ir

    profile_settings = normalize_lazycat_profile_settings(scenario.settings or {})
    base = resolve_base_url(request, services.settings.app_base_url)
    # Capture once: the blocked detail and the bundle render the same config
    # and must judge host records against the same local aliases.
    local_host_aliases = frozenset(capture_local_host_aliases())
    blocked_detail = build_clash_blocked_detail(
        policy_ir,
        profile="lazycat",
        profile_settings=profile_settings,
        provider_base_url=base,
        subscription_token=internal_token,
        subscription_public_id=subscription_id,
        render_mode="export",
        local_host_aliases=local_host_aliases,
    )
    if blocked_detail["blockers"]:
        raise HTTPException(status_code=409, detail=blocked_detail)

    bundle = build_clash_export_bundle(
        nodes,
        list(policy_ir.rule_lines),
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        device_name=str(sub.device_name or "").strip() or "SubHub",
        device_key=str(sub.device_key or "").strip() or str(sub.id or ""),
        subscription_token=internal_token,
        subscription_public_id=subscription_id,
        local_host_aliases=local_host_aliases,
        profile="lazycat",
        profile_settings=profile_settings,
        policy_ir=policy_ir,
    )
    bundle = attach_clash_bundle_audit(
        bundle,
        profile="lazycat",
        base_url=base,
        warnings=list(bundle.get("warnings") or []),
    )
    return {
        "bundle": bundle,
        "device_name": str(sub.device_name or "").strip() or "SubHub",
        "scenario_slug": scenario.slug,
    }


def _preview_summary_payload(
    policy_ir,
    skipped: list[str],
    warnings: list[object],
    asset_counts: dict[str, int],
    subscription_metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "device_strategy_preset": policy_ir.device_strategy_preset if policy_ir else "",
        "general_profile_name": policy_ir.general_profile.name if policy_ir and policy_ir.general_profile else "",
        "contracts": [item.to_dict() for item in (policy_ir.contracts if policy_ir else [])],
        "catalog_bindings": [item.to_dict() for item in (policy_ir.catalog_bindings if policy_ir else [])],
        "warnings": [item.to_dict() if hasattr(item, "to_dict") else item for item in warnings],
        "diagnostics": _renderer_diagnostics_payload(warnings),
        "skipped_count": len(skipped),
        "node_count": len(policy_ir.nodes) if policy_ir else 0,
        "rule_line_count": len(policy_ir.rule_lines) if policy_ir else 0,
        "asset_counts": {
            "domain_sets": int(asset_counts.get("domain_sets", 0)),
            "rule_sets": int(asset_counts.get("rule_sets", 0)),
        },
        "subscription_metadata": dict(subscription_metadata),
    }


def _renderer_diagnostics_payload(warnings: list[object]) -> dict[str, object]:
    diagnostics = RendererDiagnostics()
    normalized: list[object] = []
    for item in warnings:
        if hasattr(item, "code") and hasattr(item, "message"):
            diagnostics.add(item)
            normalized.append(item)
    if not normalized and warnings:
        return diagnostics.to_dict()
    return diagnostics.to_dict()


def _signed_asset_url_builder(
    services,
    *,
    base_url: str,
    subscription_id: str,
    scenario_slug: str,
    revision: str,
):
    def _builder(kind: str, asset_key: str) -> str:
        return build_signed_subscription_asset_url(
            services.settings,
            base_url=base_url,
            public_id=subscription_id,
            scenario_slug=scenario_slug,
            kind=kind,
            asset_key=asset_key,
            revision=revision,
        )

    return _builder


def _signed_clash_provider_url_builder(
    services,
    *,
    base_url: str,
    subscription_id: str,
    scenario_slug: str,
):
    def _builder(provider_key: str, revision: str) -> str:
        return build_signed_subscription_asset_url(
            services.settings,
            base_url=base_url,
            public_id=subscription_id,
            scenario_slug=scenario_slug,
            kind="clash-provider",
            asset_key=provider_key,
            revision=revision,
        )

    return _builder


def _signed_clash_rule_provider_url_builder(
    services,
    *,
    base_url: str,
    subscription_id: str,
    scenario_slug: str,
):
    def _builder(asset_key: str, revision: str) -> str:
        return build_signed_subscription_asset_url(
            services.settings,
            base_url=base_url,
            public_id=subscription_id,
            scenario_slug=scenario_slug,
            kind="clash-rule-provider",
            asset_key=asset_key,
            revision=revision,
        )

    return _builder


def _preview_summary_variant(target: str, base_url: str, scenario_id: str) -> str:
    return f"{scenario_id}|{target}|{base_url}"


def _preview_text_headers(content: str, *, revision: str = "", metadata: dict[str, object] | None = None) -> dict[str, str]:
    headers = {
        "X-Preview-Lines": str(len(content.splitlines())),
        "X-Preview-Chars": str(len(content)),
    }
    if revision:
        headers["X-Preview-Revision"] = str(revision)
    if metadata:
        headers["X-Preview-Base-Url"] = str(metadata.get("base_url", "") or "")
        headers["X-Preview-Managed-Url"] = str(metadata.get("managed_url", "") or "")
        headers["X-Preview-Domain-Set-Count"] = str(int(metadata.get("domain_set_count", 0) or 0))
        headers["X-Preview-Rule-Set-Count"] = str(int(metadata.get("rule_set_count", 0) or 0))
    return headers


def _reject_removed_profile_query_params(request: Request) -> None:
    if "profile" in request.query_params or "flavor" in request.query_params:
        raise HTTPException(status_code=400, detail="profile/flavor query parameters are no longer supported")


@router.get("/devices/{token}/preview-summary")
async def get_device_preview_summary(
    request: Request,
    token: str,
    target: Literal["surge", "clash", "shadowrocket"] = Query(...),
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    _reject_removed_profile_query_params(request)
    services = _services(request)
    subscription_id = _resolve_public_preview_subscription_id(services, token)
    sub = _resolve_preview_subscription_or_error(services, subscription_id)
    internal_token = str(sub.token or "").strip()
    scenario = _resolve_preview_scenario_or_error(services, scenario_id)
    policy_entry = await services.hub_service.get_cached_policy_ir(internal_token, scenario_id=scenario.id)
    if policy_entry is None:
        raise HTTPException(status_code=404, detail="device subscription not found")
    cached = services.hub_service.get_cached_artifact(
        kind="preview-summary",
        token=internal_token,
        revision=policy_entry.revision,
        variant=_preview_summary_variant(
            target,
            resolve_base_url(request, services.settings.app_base_url),
            scenario.id,
        ),
    )
    if cached is None:
        artifacts = await _build_device_preview_artifacts(
            request,
            token=token,
            target=target,
            scenario_id=scenario.id,
        )
        summary = _preview_summary_payload(
            artifacts["policy_ir"],
            artifacts["skipped"],
            artifacts["warnings"],
            artifacts["asset_counts"],
            artifacts["subscription_metadata"],
        )
        services.hub_service.store_cached_artifact(
            kind="preview-summary",
            token=internal_token,
            revision=policy_entry.revision,
            variant=_preview_summary_variant(
                target,
                str(artifacts["subscription_metadata"].get("base_url", "") or ""),
                scenario.id,
            ),
            value=summary,
        )
    else:
        summary = dict(cached.value)
    return {
        "ok": True,
        "target": target,
        "scenario": scenario.to_dict(),
        "revision": policy_entry.revision,
        "metadata": dict(summary.get("subscription_metadata") or {}),
        "summary": summary,
    }


@router.get("/devices/{token}/preview-content", response_class=PlainTextResponse)
async def get_device_preview_content(
    request: Request,
    token: str,
    target: Literal["surge", "clash", "shadowrocket"] = Query(...),
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> PlainTextResponse:
    _reject_removed_profile_query_params(request)
    artifacts = await _build_device_preview_artifacts(
        request,
        token=token,
        target=target,
        scenario_id=scenario_id,
    )
    content = str(artifacts["content"])
    return PlainTextResponse(
        content,
        headers=_preview_text_headers(
            content,
            revision=str(artifacts["revision"] or ""),
            metadata=dict(artifacts["subscription_metadata"] or {}),
        ),
    )


@router.get("/devices/{token}/render-preview")
async def render_device_preview(
    request: Request,
    token: str,
    target: Literal["surge", "clash", "shadowrocket"] = Query(...),
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _reject_removed_profile_query_params(request)
    artifacts = await _build_device_preview_artifacts(
        request,
        token=token,
        target=target,
        scenario_id=scenario_id,
    )
    policy_ir = artifacts["policy_ir"]
    return {
        "ok": True,
        "target": target,
        "scenario_id": artifacts["scenario_id"],
        "scenario_slug": artifacts["scenario_slug"],
        "scenario_name": artifacts["scenario_name"],
        "revision": artifacts["revision"],
        "metadata": dict(artifacts["subscription_metadata"] or {}),
        "content": artifacts["content"],
        "skipped": artifacts["skipped"],
        "policy_ir": policy_ir.to_dict() if policy_ir else None,
        "diagnostics": _renderer_diagnostics_payload(list(artifacts["warnings"] or [])),
        "blockers": [],
        "blocked": False,
        "warnings": [
            item.to_dict() if hasattr(item, "to_dict") else item for item in artifacts["warnings"]
        ],
        "asset_counts": artifacts["asset_counts"],
    }


@router.get("/devices/{token}/export/clash-bundle.zip")
async def export_device_clash_bundle(
    request: Request,
    token: str,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> Response:
    _reject_removed_profile_query_params(request)
    artifacts = await _build_device_clash_bundle_artifacts(
        request,
        token=token,
        scenario_id=scenario_id,
    )
    bundle = dict(artifacts["bundle"] or {})
    files = dict(bundle.get("files") or {})
    filename = ascii_filename(
        str(artifacts["device_name"] or "SubHub"),
        f"-{artifacts['scenario_slug']}-clash-bundle.zip",
    )
    return Response(
        content=bundle_zip_bytes(files),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/settings/surge/process-rules")
async def get_surge_process_rules(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    items = [
        item.to_dict()
        for item in services.hub_service._load_process_rules(
            services.repo.list_scenario_service_catalog_entries(safe_scenario_id),
            raw_entries=services.repo.list_scenario_process_rules(safe_scenario_id),
            scenario_id=safe_scenario_id,
        )
    ]
    return {"ok": True, "items": items}


@router.put("/settings/surge/process-rules")
async def update_surge_process_rules(
    request: Request,
    payload: SurgeProcessRulesPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    items = _normalize_process_rule_items(
        payload.items,
        repo=services.repo,
        scenario_id=safe_scenario_id,
    )
    services.repo.set_scenario_process_rules(safe_scenario_id, items)
    return {"ok": True, "items": items}


@router.get("/settings/surge/external-proxy-programs")
async def get_surge_external_proxy_programs(
    request: Request,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    items = [
        item.to_dict()
        for item in services.hub_service._load_external_proxy_programs(
            services.repo.list_scenario_service_catalog_entries(safe_scenario_id),
            raw_entries=services.repo.list_scenario_external_proxy_programs(safe_scenario_id),
            scenario_id=safe_scenario_id,
        )
    ]
    return {"ok": True, "items": items}


@router.put("/settings/surge/external-proxy-programs")
async def update_surge_external_proxy_programs(
    request: Request,
    payload: SurgeExternalProxyProgramsPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    items = _normalize_external_proxy_program_items(
        payload.items,
        repo=services.repo,
        scenario_id=safe_scenario_id,
    )
    services.repo.set_scenario_external_proxy_programs(safe_scenario_id, items)
    return {"ok": True, "items": items}


@router.get("/settings/refresh-policy")
async def get_refresh_policy(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    policy = _refresh_policy_payload(_services(request))
    return {"ok": True, "item": policy}


@router.put("/settings/refresh-policy")
async def update_refresh_policy(
    request: Request,
    payload: RefreshPolicyPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    services.rule_catalog.update_refresh_policy(
        rule_catalog_cache_hours=payload.rule_catalog_cache_hours,
        cn_cache_hours=payload.cn_cache_hours,
    )
    services.hub_service.update_standard_source_refresh_policy(
        enabled=payload.standard_source_auto_pull_enabled,
        interval_minutes=payload.standard_source_auto_pull_interval_minutes,
    )
    policy = _refresh_policy_payload(services)
    return {"ok": True, "item": policy}


@router.get("/settings/llm-export")
async def get_llm_export_settings(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return {"ok": True, "item": _llm_export_settings_payload(_services(request))}


@router.put("/settings/llm-export")
async def update_llm_export_settings(
    request: Request,
    payload: LlmExportSettingsPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    item = _services(request).rule_catalog.update_llm_export_preferences(
        rules_preferences=payload.rules_preferences,
        pins_preferences=payload.pins_preferences,
        directness_preferences=payload.directness_preferences,
    )
    return {"ok": True, "item": item}


@router.get("/llm/workflows")
async def list_llm_workflows(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return {
        "ok": True,
        "items": [
            *_services(request).log_routing_workflows.list_workflows(),
            *_services(request).llm_workflows.list_workflows(),
        ],
    }


@router.post("/llm/log-routing/sessions")
async def create_log_routing_session(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return _services(request).log_routing_workflows.create_session()


@router.post("/llm/log-routing/sessions/{session_id}/files")
async def upload_log_routing_file(
    request: Request,
    session_id: str,
    file: UploadFile = File(...),
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        content = await file.read()
        return _services(request).log_routing_workflows.add_file(
            session_id,
            filename=str(file.filename or ""),
            content_type=str(file.content_type or ""),
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/llm/log-routing/sessions/{session_id}/candidates")
async def get_log_routing_candidates(
    request: Request,
    session_id: str,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return _services(request).log_routing_workflows.get_candidates(session_id)
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "session not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/llm/log-routing/sessions/{session_id}/export")
async def export_log_routing_session(
    request: Request,
    session_id: str,
    payload: LogRoutingSessionExportPayload | None = None,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return _services(request).log_routing_workflows.export_session(
            session_id,
            intent_override=payload.intent_override if payload else "",
            sample_evidence_limit=payload.sample_evidence_limit if payload else 3,
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "session not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/llm/log-routing/sessions/{session_id}/preview")
async def preview_log_routing_patch(
    request: Request,
    session_id: str,
    payload: LogRoutingPatchPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return _services(request).log_routing_workflows.preview_patch(
            session_id,
            snapshot_id=payload.snapshot_id,
            patch=payload.patch,
        )
    except ValueError as exc:
        detail = str(exc)
        if "snapshot drifted" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        status = 404 if "session not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/llm/log-routing/sessions/{session_id}/apply")
async def apply_log_routing_patch(
    request: Request,
    session_id: str,
    payload: LogRoutingPatchPayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return _services(request).log_routing_workflows.apply_patch(
            session_id,
            snapshot_id=payload.snapshot_id,
            patch=payload.patch,
            selected_action_ids=payload.selected_action_ids,
        )
    except ValueError as exc:
        detail = str(exc)
        if "snapshot drifted" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        status = 404 if "session not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/llm/workflows/{workflow}/export")
async def export_llm_workflow(
    request: Request,
    workflow: str,
    payload: LlmWorkflowExportPayload | None = None,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    try:
        data = _services(request).llm_workflows.export_workflow(
            workflow,
            scenario_id=safe_scenario_id,
            intent_override=payload.intent_override if payload else "",
            sample_rule_limit=payload.sample_rule_limit if payload else 5,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data


@router.post("/llm/workflows/{workflow}/preview-import")
async def preview_llm_workflow_import(
    request: Request,
    workflow: str,
    payload: LlmWorkflowPreviewPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    try:
        data = _services(request).llm_workflows.preview_import(
            workflow,
            scenario_id=safe_scenario_id,
            snapshot_fingerprint=payload.snapshot_fingerprint,
            result=payload.result,
        )
    except ValueError as exc:
        detail = str(exc)
        if "snapshot drifted" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return data


@router.post("/llm/workflows/{workflow}/apply")
async def apply_llm_workflow_import(
    request: Request,
    workflow: str,
    payload: LlmWorkflowApplyPayload,
    scenario_id: str = Query(default=_DEFAULT_SCENARIO_ID),
) -> dict[str, object]:
    _require_login_if_needed(request)
    safe_scenario_id = _scenario_id_or_default(scenario_id)
    try:
        data = _services(request).llm_workflows.apply_import(
            workflow,
            scenario_id=safe_scenario_id,
            snapshot_fingerprint=payload.snapshot_fingerprint,
            result=payload.result,
            selected_change_ids=payload.selected_change_ids,
        )
    except ValueError as exc:
        detail = str(exc)
        if "snapshot drifted" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return data


@router.get("/policy-backup/status")
async def get_policy_backup_status(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return {"ok": True, "item": _services(request).policy_backup.status().to_dict()}


@router.post("/policy-backup/sync")
async def sync_policy_backup(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = await _services(request).policy_backup.sync_now(force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/policy-backup/export")
async def export_policy_backup(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return _services(request).policy_backup.export_snapshot()


@router.post("/policy-backup/restore/preview")
async def preview_policy_backup_restore(
    request: Request,
    payload: PolicyBackupRestorePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = await _services(request).policy_backup.restore_preview(ref=payload.ref)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/policy-backup/restore/apply")
async def apply_policy_backup_restore(
    request: Request,
    payload: PolicyBackupRestorePayload,
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = await _services(request).policy_backup.restore_apply(ref=payload.ref, expected_digest=payload.expected_digest)
    except RestoreSnapshotChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/refresh")
async def refresh_all(
    request: Request,
    payload: GlobalRefreshPayload | None = None,
) -> dict[str, object]:
    _require_login_if_needed(request)
    mode = payload.rule_catalog_mode if payload else "incremental"
    runtime = await _services(request).hub_service.refresh(
        force=True,
        force_rule_catalog=True,
        rule_catalog_mode=mode,
    )
    runtime_payload = public_runtime(runtime.to_dict(), known_source_secrets(_services(request).repo.list_standard_sources()))
    source_status = runtime_payload.get("source_status") or {}
    aggregate = source_status.get("aggregate") if isinstance(source_status, dict) else None
    if not isinstance(aggregate, dict):
        aggregate = summarize_refresh_status(source_status if isinstance(source_status, dict) else {})
    response = {**aggregate, "runtime": runtime_payload}
    if response.get("ok") is False:
        return JSONResponse(status_code=502, content=response)
    return response


@router.get("/status")
async def status(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    services = _services(request)
    locale = resolve_locale(request)
    payload = services.hub_service.status()
    payload["egress"] = await services.egress_diagnostics.get_status(
        gorelay_source_count=len(services.gorelay_service.list_accounts())
    )
    proxy_bridge = dict((payload.get("egress") or {}).get("proxy_bridge") or {})
    payload["egress"]["proxy_bridge"] = localize_egress_payload(proxy_bridge, locale)
    return {"ok": True, **payload}
