from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.lazycat_profile import (
    LAZYCAT_PROFILE_CLASH_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY,
    LAZYCAT_PROFILE_CLASH_IPV6_KEY,
    LAZYCAT_PROFILE_CLASH_HOST_RECORDS_KEY,
    LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY,
    LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY,
    LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY,
    LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY,
    LAZYCAT_PROFILE_CLASH_SECRET_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY,
    LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY,
    LAZYCAT_PROFILE_CLASH_FAKE_IP_FILTER_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_HOST_RECORDS_KEY,
    LAZYCAT_PROFILE_SURGE_BLOCK_QUIC_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_SECRET_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_TLS_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_WEB_DASHBOARD_KEY,
    LAZYCAT_PROFILE_SURGE_IPV6_KEY,
    LAZYCAT_PROFILE_SURGE_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY,
    LAZYCAT_PROFILE_SURGE_LOGLEVEL_KEY,
    LAZYCAT_PROFILE_SURGE_MAP_LOCAL_KEY,
    LAZYCAT_PROFILE_SURGE_MITM_H2_KEY,
    LAZYCAT_PROFILE_SURGE_MITM_HOSTNAME_KEY,
    LAZYCAT_PROFILE_SURGE_MITM_SKIP_SERVER_CERT_VERIFY_KEY,
    LAZYCAT_PROFILE_SURGE_MITM_TCP_CONNECTION_KEY,
    LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TIMEOUT_KEY,
    LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TOLERANCE_KEY,
    LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY,
    LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY,
    LAZYCAT_PROFILE_SURGE_URL_REWRITE_KEY,
    LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY,
    normalize_lazycat_profile_settings,
    validate_lazycat_profile_setting_value,
)
from app.services.profile_capabilities import PROFILE_CAPABILITY_GROUPS
from app.services.skip_proxy_decomposer import decompose_skip_proxy

PROFILE_EDITOR_SCHEMA_VERSION = 1
_DEFAULT_PROFILE_SETTINGS = normalize_lazycat_profile_settings({})
_SKIP_PROXY_LEGACY_MODE_ALIASES = {
    "surge_native": "shared",
    "shadowrocket_experimental": "shared",
    "mihomo_split": "shared",
}


def _text(zh: str, en: str) -> dict[str, str]:
    return {"zh": zh, "en": en}


def default_profile_editor_state(*, legacy: bool) -> dict[str, Any]:
    return {
        "version": PROFILE_EDITOR_SCHEMA_VERSION,
        "families": {},
        "active_client": {},
        "legacy": bool(legacy),
    }


def normalize_profile_editor_state(
    state: Mapping[str, object] | None,
    *,
    legacy_default: bool,
) -> dict[str, Any]:
    raw = dict(state or {})
    families = raw.get("families")
    active_client = raw.get("active_client")
    return {
        "version": PROFILE_EDITOR_SCHEMA_VERSION,
        "families": dict(families) if isinstance(families, Mapping) else {},
        "active_client": dict(active_client) if isinstance(active_client, Mapping) else {},
        "legacy": bool(raw.get("legacy", legacy_default)),
    }


def _default_setting_value(key: str) -> object:
    return _DEFAULT_PROFILE_SETTINGS.get(key)


def _resolve_sync_group_value(
    normalized: Mapping[str, object],
    previous: Mapping[str, object],
    group: Mapping[str, object],
) -> object:
    keys = [str(key) for key in group.get("keys") or [] if str(key)]
    if not keys:
        return None
    primary_key = str(group.get("primary_key") or "")
    if all(isinstance(_default_setting_value(key), list) for key in keys):
        selected_keys = [key for key in keys if normalized.get(key) != _default_setting_value(key)]
        if not selected_keys:
            selected_keys = [primary_key] if primary_key in keys else keys[:1]
        merged: list[str] = []
        seen: set[str] = set()
        for key in selected_keys:
            value = normalized.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                text = str(item).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    changed_keys = [key for key in keys if normalized.get(key) != previous.get(key)]
    if changed_keys:
        return normalized.get(changed_keys[0])
    if primary_key in keys and normalized.get(primary_key) != _default_setting_value(primary_key):
        return normalized.get(primary_key)
    for key in keys:
        if normalized.get(key) != _default_setting_value(key):
            return normalized.get(key)
    fallback_key = primary_key if primary_key in keys else keys[0]
    return normalized.get(fallback_key)


def _migrate_skip_proxy_single_source(settings: Mapping[str, object]) -> dict[str, Any]:
    normalized = normalize_lazycat_profile_settings(settings or {})
    route_entries: list[str] = []
    seen_routes: set[str] = set()
    for key in (
        LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY,
        LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY,
        LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY,
    ):
        value = normalized.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item).strip()
            if not text or text in seen_routes:
                continue
            seen_routes.add(text)
            route_entries.append(text)

    for key in (
        LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY,
        LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY,
    ):
        value = normalized.get(key)
        patterns = [str(item).strip() for item in value] if isinstance(value, list) else []
        decomp = decompose_skip_proxy(patterns)
        normalized[key] = decomp.direct_intent_patterns
        for entry in decomp.route_exclude_entries:
            if entry in seen_routes:
                continue
            seen_routes.add(entry)
            route_entries.append(entry)

    normalized[LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY] = route_entries
    return normalized


def harmonize_profile_single_source_settings(
    settings: Mapping[str, object] | None,
    *,
    current_settings: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    normalized = _migrate_skip_proxy_single_source(settings or {})
    previous = normalize_lazycat_profile_settings(current_settings or {})

    for family in _PROFILE_EDITOR_SCHEMA["families"]:
        if "shared" not in set(family.get("mode_ids") or []):
            continue
        for group in family.get("sync_groups") or []:
            keys = [str(key) for key in group.get("keys") or [] if str(key)]
            if not keys:
                continue
            value = _resolve_sync_group_value(normalized, previous, group)
            for key in keys:
                validate_lazycat_profile_setting_value(key, value)
                normalized[key] = value

    return normalize_lazycat_profile_settings(normalized)


def _find_subfield(capability_id: str, subfield_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for group in PROFILE_CAPABILITY_GROUPS:
        for capability in group["capabilities"]:
            if str(capability["id"]) != capability_id:
                continue
            for subfield in capability["subfields"]:
                if str(subfield["id"]) == subfield_id:
                    return capability, subfield
    raise KeyError(f"missing capability subfield: {capability_id}.{subfield_id}")


def _setting_schema(view: Mapping[str, Any], *, key: str | None = None) -> dict[str, Any]:
    field: dict[str, Any] = {
        "key": key or str(view.get("key") or ""),
        "label": str(view.get("label") or ""),
        "label_i18n": dict(view.get("label_i18n") or {}),
        "type": str(view.get("type") or "string"),
        "description": str(view.get("description") or ""),
        "description_i18n": dict(view.get("description_i18n") or {}),
    }
    if view.get("placeholder"):
        field["placeholder"] = str(view["placeholder"])
        field["placeholder_i18n"] = dict(view.get("placeholder_i18n") or {})
    if view.get("rows") is not None:
        field["rows"] = int(view["rows"])
    if view.get("options"):
        field["options"] = [dict(option) for option in view["options"]]
    return field


def _support_detail(view: Mapping[str, Any]) -> list[dict[str, Any]]:
    support = dict(view.get("support") or {})
    sections: list[dict[str, Any]] = [{
        "kind": "support",
        "title": "Support",
        "title_i18n": _text("支持状态", "Support"),
        "body": str(support.get("reason") or ""),
        "body_i18n": dict(support.get("reason_i18n") or {}),
        "status": str(support.get("status") or ""),
    }]
    adapted_hint = str(view.get("adapted_hint") or "").strip()
    if adapted_hint:
        sections.append({
            "kind": "generated",
            "title": "Generated output",
            "title_i18n": _text("生成方式", "Generated output"),
            "body": adapted_hint,
            "body_i18n": dict(view.get("adapted_hint_i18n") or {}),
            "status": "generated",
        })
    for hint in view.get("syntax_hints") or []:
        sections.append({
            "kind": "syntax",
            "title": str(hint.get("title") or "Syntax"),
            "title_i18n": dict(hint.get("title_i18n") or {}),
            "body": str(hint.get("body") or ""),
            "body_i18n": dict(hint.get("body_i18n") or {}),
            "status": str(hint.get("status") or ""),
        })
    return sections


def _mapping_detail(
    mappings: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    zh_lines = [f"{client} -> {field}" for client, field in mappings]
    return {
        "kind": "mapping",
        "title": "Fields touched",
        "title_i18n": _text("会修改的字段", "Fields touched"),
        "body": "\n".join(f"{client} -> {field}" for client, field in mappings),
        "body_i18n": _text("\n".join(zh_lines), "\n".join(f"{client} -> {field}" for client, field in mappings)),
    }


def _card(
    *,
    card_id: str,
    family_id: str,
    group_id: str,
    title: str,
    title_zh: str,
    description: str,
    description_zh: str,
    mode_kind: str,
    status_badge: str,
    client: str | None,
    field_keys: Sequence[str],
    input_schema: Sequence[dict[str, Any]],
    detail_sections: Sequence[dict[str, Any]],
    activation_mode: str | None,
) -> dict[str, Any]:
    return {
        "id": card_id,
        "family_id": family_id,
        "group_id": group_id,
        "title": title,
        "title_i18n": _text(title_zh, title),
        "description": description,
        "description_i18n": _text(description_zh, description),
        "mode_kind": mode_kind,
        "status_badge": status_badge,
        "client": client,
        "field_keys": list(field_keys),
        "input_schema": [dict(field) for field in input_schema],
        "detail_sections": [dict(section) for section in detail_sections],
        "activation": {
            "family_id": family_id,
            "mode": activation_mode,
            "client": client,
        } if activation_mode else None,
    }


def _shared_family(
    *,
    family_id: str,
    group_id: str,
    title: str,
    title_zh: str,
    description: str,
    description_zh: str,
    fields: Sequence[dict[str, Any]],
    sync_groups: Sequence[dict[str, Any]],
    detail_sections: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    primary_keys = [str(group["primary_key"]) for group in sync_groups]
    field_keys = [key for group in sync_groups for key in group["keys"]]
    family = {
        "id": family_id,
        "group_id": group_id,
        "title": title,
        "title_i18n": _text(title_zh, title),
        "mode_label": "Shared",
        "mode_label_i18n": _text("共享", "Shared"),
        "mode_ids": ["shared"],
        "default_mode": "shared",
        "sync_groups": [dict(group) for group in sync_groups],
    }
    card = _card(
        card_id=f"{family_id}:shared",
        family_id=family_id,
        group_id=group_id,
        title=title,
        title_zh=title_zh,
        description=description,
        description_zh=description_zh,
        mode_kind="shared",
        status_badge="stable",
        client=None,
        field_keys=field_keys,
        input_schema=fields,
        detail_sections=detail_sections,
        activation_mode="shared",
    )
    return family, [card]


def _subfield_field(
    capability_id: str,
    subfield_id: str,
    client: str,
    *,
    key: str | None = None,
) -> dict[str, Any]:
    _, subfield = _find_subfield(capability_id, subfield_id)
    view = dict(subfield["clients"][client])
    return _setting_schema(view, key=key)


def _subfield_detail(
    capability_id: str,
    subfield_id: str,
    client: str,
    *,
    mappings: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    _, subfield = _find_subfield(capability_id, subfield_id)
    view = dict(subfield["clients"][client])
    return [_mapping_detail(mappings), *_support_detail(view)]


def _card_mode_kind_from_view(view: Mapping[str, Any]) -> str:
    support = dict(view.get("support") or {})
    support_status = str(support.get("status") or "").strip()
    editing_mode = str(view.get("editing_mode") or "").strip()
    if support_status == "unsupported" or editing_mode == "unavailable":
        return "unsupported"
    if support_status == "pending_validation" or editing_mode == "experimental":
        return "experimental"
    if editing_mode == "shared":
        return "shared"
    return "client_native"


def _card_status_badge_from_view(view: Mapping[str, Any]) -> str:
    support = dict(view.get("support") or {})
    support_status = str(support.get("status") or "").strip()
    editing_mode = str(view.get("editing_mode") or "").strip()
    if support_status == "downgraded":
        return "limited"
    if support_status == "unsupported" or editing_mode == "unavailable":
        return "unsupported"
    if support_status == "pending_validation" or editing_mode == "experimental":
        return "experimental"
    if support_status == "auto_mapped":
        return "generated"
    return "stable"


def profile_editor_schema_payload() -> dict[str, Any]:
    groups = [
        {
            "id": "traffic-control",
            "title": "Traffic Control",
            "title_i18n": _text("流量控制", "Traffic Control"),
            "description": "Traffic bypass and direct-connection behaviors.",
            "description_i18n": _text("控制哪些流量绕过代理、直接连接。", "Control which traffic bypasses the proxy and connects directly."),
        },
        {
            "id": "rewrite-and-mitm",
            "title": "Rewrite & MITM",
            "title_i18n": _text("重写与 MITM", "Rewrite & MITM"),
            "description": "HTTP interception features that are client-specific.",
            "description_i18n": _text("客户端专属的 HTTP 拦截能力。", "HTTP interception features that are client-specific."),
        },
        {
            "id": "dns",
            "title": "DNS & Host Path",
            "title_i18n": _text("DNS 与主机路径", "DNS & Host Path"),
            "description": "Host resolution intent and fake-IP related behavior.",
            "description_i18n": _text("域名解析方式与 fake-IP 相关设置。", "DNS resolution methods and fake-IP related settings."),
        },
        {
            "id": "tun",
            "title": "TUN & Routing",
            "title_i18n": _text("TUN 与路由", "TUN & Routing"),
            "description": "Tunnel routing and exclusion settings.",
            "description_i18n": _text("隧道路由与排除设置。", "Tunnel routing and exclusion settings."),
        },
        {
            "id": "general",
            "title": "Runtime & Control",
            "title_i18n": _text("运行时与控制", "Runtime & Control"),
            "description": "Shared runtime switches and client-native controls.",
            "description_i18n": _text("各客户端通用的运行时开关。", "Runtime switches shared across all clients."),
        },
    ]

    families: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []

    family, family_cards = _shared_family(
        family_id="excluded-routes",
        group_id="tun",
        title="Excluded Routes",
        title_zh="排除路由",
        description="Shared IP/CIDR routes that bypass tunnel routing across clients.",
        description_zh="跨客户端共享的 IP/CIDR 绕行路由。",
        fields=[
            _subfield_field("excluded-routes", "routes", "clash", key=LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY),
        ],
        sync_groups=[{
            "primary_key": LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY,
            "keys": [
                LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY,
                LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY,
                LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY,
            ],
        }],
        detail_sections=_subfield_detail(
            "excluded-routes",
            "routes",
            "clash",
            mappings=[
                ("Mihomo", "tun.route-exclude-address"),
                ("Surge", "tun-excluded-routes"),
                ("Shadowrocket", "tun-excluded-routes"),
            ],
        ),
    )
    families.append(family)
    cards.extend(family_cards)

    family, family_cards = _shared_family(
        family_id="ipv6-policy",
        group_id="general",
        title="IPv6 Preference",
        title_zh="IPv6 偏好",
        description="One switch for the clients whose IPv6 semantics are already aligned.",
        description_zh="对语义已对齐的客户端统一控制 IPv6。",
        fields=[
            _subfield_field("ipv6-policy", "enabled", "surge", key=LAZYCAT_PROFILE_SURGE_IPV6_KEY),
        ],
        sync_groups=[{
            "primary_key": LAZYCAT_PROFILE_SURGE_IPV6_KEY,
            "keys": [
                LAZYCAT_PROFILE_SURGE_IPV6_KEY,
                LAZYCAT_PROFILE_CLASH_IPV6_KEY,
                LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY,
            ],
        }],
        detail_sections=_subfield_detail(
            "ipv6-policy",
            "enabled",
            "surge",
            mappings=[
                ("Surge", "ipv6"),
                ("Mihomo", "ipv6"),
                ("Shadowrocket", "ipv6"),
            ],
        ),
    )
    families.append(family)
    cards.extend(family_cards)

    family, family_cards = _shared_family(
        family_id="control-api-access",
        group_id="general",
        title="Control API Access",
        title_zh="控制 API 访问",
        description="Shared control API endpoint and secret where the semantics are already aligned.",
        description_zh="语义已对齐的控制 API 地址与密钥。",
        fields=[
            _subfield_field("mihomo-control-api", "external_controller", "clash", key=LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY),
            _subfield_field("mihomo-control-api", "secret", "clash", key=LAZYCAT_PROFILE_CLASH_SECRET_KEY),
        ],
        sync_groups=[
            {
                "primary_key": LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY,
                "keys": [LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY, LAZYCAT_PROFILE_SURGE_HTTP_API_KEY],
            },
            {
                "primary_key": LAZYCAT_PROFILE_CLASH_SECRET_KEY,
                "keys": [LAZYCAT_PROFILE_CLASH_SECRET_KEY, LAZYCAT_PROFILE_SURGE_HTTP_API_SECRET_KEY],
            },
        ],
        detail_sections=[
            _mapping_detail([
                ("Mihomo", "external-controller / secret"),
                ("Surge", "http-api / http-api-secret"),
            ]),
            *_support_detail(dict(_find_subfield("mihomo-control-api", "external_controller")[1]["clients"]["clash"])),
        ],
    )
    families.append(family)
    cards.extend(family_cards)

    mihomo_runtime_family = {
        "id": "mihomo-runtime-native",
        "group_id": "general",
        "title": "Mihomo Runtime",
        "title_i18n": _text("Mihomo 运行时", "Mihomo Runtime"),
        "mode_ids": ["clash_native"],
        "default_mode": "clash_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY, "keys": [LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY, "keys": [LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY, "keys": [LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY]},
        ],
    }
    families.append(mihomo_runtime_family)
    cards.append(_card(
        card_id="mihomo-runtime-native:clash",
        family_id="mihomo-runtime-native",
        group_id="general",
        title="Mihomo Runtime",
        title_zh="Mihomo 运行时",
        description="Mihomo-only runtime switches.",
        description_zh="仅 Mihomo 的运行时开关。",
        mode_kind="client_native",
        status_badge="stable",
        client="clash",
        field_keys=[
            LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY,
            LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY,
            LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY,
            LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY,
        ],
        input_schema=[
            _subfield_field("mihomo-runtime", "log_level", "clash"),
            _subfield_field("mihomo-runtime", "mixed_port", "clash"),
            _subfield_field("mihomo-runtime", "allow_lan", "clash"),
            _subfield_field("mihomo-runtime", "udp_default", "clash"),
        ],
        detail_sections=[
            _mapping_detail([("Mihomo", "log-level / mixed-port / allow-lan / udp")]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "These are Mihomo native runtime fields. `log-level` is edited here in Mihomo-native terms and is not shared with Surge.",
                "body_i18n": _text(
                    "这些都是 Mihomo 原生运行时字段。`log-level` 只在这里按 Mihomo 原生语义编辑，不会与 Surge 共享。",
                    "These are Mihomo native runtime fields. `log-level` is edited here in Mihomo-native terms and is not shared with Surge.",
                ),
                "status": "stable",
            },
            *_support_detail(dict(_find_subfield("mihomo-runtime", "log_level")[1]["clients"]["clash"])),
        ],
        activation_mode="clash_native",
    ))

    mihomo_store_family = {
        "id": "mihomo-profile-store",
        "group_id": "general",
        "title": "Profile Persistence",
        "title_i18n": _text("配置持久化", "Profile Persistence"),
        "mode_ids": ["clash_native"],
        "default_mode": "clash_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY, "keys": [LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY, "keys": [LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY]},
        ],
    }
    families.append(mihomo_store_family)
    cards.append(_card(
        card_id="mihomo-profile-store:clash",
        family_id="mihomo-profile-store",
        group_id="general",
        title="Profile Persistence",
        title_zh="配置持久化",
        description="Mihomo profile store behavior.",
        description_zh="Mihomo 的配置持久化行为。",
        mode_kind="client_native",
        status_badge="stable",
        client="clash",
        field_keys=[
            LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY,
            LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY,
        ],
        input_schema=[
            _subfield_field("mihomo-profile-store", "store_selected", "clash"),
            _subfield_field("mihomo-profile-store", "store_fake_ip", "clash"),
        ],
        detail_sections=[
            _mapping_detail([("Mihomo", "profile.store-selected / profile.store-fake-ip")]),
            *_support_detail(dict(_find_subfield("mihomo-profile-store", "store_selected")[1]["clients"]["clash"])),
        ],
        activation_mode="clash_native",
    ))

    mihomo_ui_family = {
        "id": "mihomo-external-ui",
        "group_id": "general",
        "title": "Mihomo External UI",
        "title_i18n": _text("Mihomo 外部 UI", "Mihomo External UI"),
        "mode_ids": ["clash_native"],
        "default_mode": "clash_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY, "keys": [LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY, "keys": [LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY, "keys": [LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY]},
        ],
    }
    families.append(mihomo_ui_family)
    cards.append(_card(
        card_id="mihomo-external-ui:clash",
        family_id="mihomo-external-ui",
        group_id="general",
        title="Mihomo External UI",
        title_zh="Mihomo 外部 UI",
        description="Mihomo web UI bundle settings.",
        description_zh="Mihomo Web UI 相关设置。",
        mode_kind="client_native",
        status_badge="stable",
        client="clash",
        field_keys=[
            LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY,
            LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY,
            LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY,
        ],
        input_schema=[
            _subfield_field("mihomo-control-api", "external_ui", "clash"),
            _subfield_field("mihomo-control-api", "external_ui_name", "clash"),
            _subfield_field("mihomo-control-api", "external_ui_url", "clash"),
        ],
        detail_sections=[
            _mapping_detail([("Mihomo", "external-ui / external-ui-name / external-ui-url")]),
            *_support_detail(dict(_find_subfield("mihomo-control-api", "external_ui")[1]["clients"]["clash"])),
        ],
        activation_mode="clash_native",
    ))

    surge_runtime_family = {
        "id": "surge-runtime-native",
        "group_id": "general",
        "title": "Surge Runtime",
        "title_i18n": _text("Surge 运行时", "Surge Runtime"),
        "mode_ids": ["surge_native"],
        "default_mode": "surge_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TIMEOUT_KEY, "keys": [LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TIMEOUT_KEY]},
            {"primary_key": LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TOLERANCE_KEY, "keys": [LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TOLERANCE_KEY]},
        ],
    }
    families.append(surge_runtime_family)
    cards.append(_card(
        card_id="surge-runtime-native:surge",
        family_id="surge-runtime-native",
        group_id="general",
        title="Surge Runtime",
        title_zh="Surge 运行时",
        description="Surge-only runtime tuning.",
        description_zh="仅 Surge 的运行时调优。",
        mode_kind="client_native",
        status_badge="stable",
        client="surge",
        field_keys=[
            LAZYCAT_PROFILE_SURGE_LOGLEVEL_KEY,
            LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TIMEOUT_KEY,
            LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TOLERANCE_KEY,
            LAZYCAT_PROFILE_SURGE_BLOCK_QUIC_KEY,
            LAZYCAT_PROFILE_SURGE_HTTP_API_TLS_KEY,
            LAZYCAT_PROFILE_SURGE_HTTP_API_WEB_DASHBOARD_KEY,
        ],
        input_schema=[
            _subfield_field("surge-runtime", "loglevel", "surge"),
            _subfield_field("surge-runtime", "group_timeout", "surge"),
            _subfield_field("surge-runtime", "group_tolerance", "surge"),
            _subfield_field("surge-runtime", "block_quic", "surge"),
            _subfield_field("surge-runtime", "http_api_tls", "surge"),
            _subfield_field("surge-runtime", "http_api_web_dashboard", "surge"),
        ],
        detail_sections=[
            _mapping_detail([("Surge", "loglevel / proxy-group timeout / tolerance")]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "These are Surge native runtime fields. `loglevel` is edited here in Surge-native terms and is not shared with Mihomo.",
                "body_i18n": _text(
                    "这些都是 Surge 原生运行时字段。`loglevel` 只在这里按 Surge 原生语义编辑，不会与 Mihomo 共享。",
                    "These are Surge native runtime fields. `loglevel` is edited here in Surge-native terms and is not shared with Mihomo.",
                ),
                "status": "stable",
            },
            *_support_detail(dict(_find_subfield("surge-runtime", "loglevel")[1]["clients"]["surge"])),
        ],
        activation_mode="surge_native",
    ))

    family, family_cards = _shared_family(
        family_id="skip-proxy",
        group_id="traffic-control",
        title="Skip Proxy / Direct Intent",
        title_zh="跳过代理 / 直连意图",
        description="One shared domain / host bypass truth for Surge and Shadowrocket; Mihomo shows the generated projection.",
        description_zh="Surge 与 Shadowrocket 共享同一份域名 / 主机绕行真相；Mihomo 只展示生成后的投影。",
        fields=[
            _subfield_field("skip-proxy", "patterns", "surge", key=LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY),
        ],
        sync_groups=[{
            "primary_key": LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY,
            "keys": [
                LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY,
                LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY,
            ],
        }],
        detail_sections=[
            _mapping_detail([
                ("Surge", "skip-proxy"),
                ("Shadowrocket", "skip-proxy"),
                ("Mihomo", "rules (DIRECT) / dns.fake-ip-filter"),
            ]),
            {
                "kind": "support",
                "title": "Single source of truth",
                "title_i18n": _text("单一真相", "Single source of truth"),
                "body": "This family now keeps one shared domain / host bypass truth. Surge and Shadowrocket stay in sync, while Mihomo renders the same intent as DIRECT rules and fake-ip-filter entries only when fake-ip mode is enabled.",
                "body_i18n": _text(
                    "这个 family 现在只保留一份共享的域名 / 主机绕行真相。Surge 与 Shadowrocket 强制同步；Mihomo 则把同一意图渲染成 DIRECT 规则，并且只在 fake-ip 模式下额外生成 fake-ip-filter 条目。",
                    "This family now keeps one shared domain / host bypass truth. Surge and Shadowrocket stay in sync, while Mihomo renders the same intent as DIRECT rules and fake-ip-filter entries only when fake-ip mode is enabled.",
                ),
                "status": "stable",
            },
            *_support_detail(dict(_find_subfield("skip-proxy", "patterns")[1]["clients"]["shadowrocket"])),
        ],
    )
    families.append(family)
    cards.extend(family_cards)
    cards.append(_card(
        card_id="skip-proxy:mihomo",
        family_id="skip-proxy",
        group_id="traffic-control",
        title="Mihomo Projection",
        title_zh="Mihomo 投影",
        description="Mihomo has no native skip-proxy field; this card explains how the shared truth is rendered.",
        description_zh="Mihomo 没有原生 skip-proxy 字段；这个卡片只解释共享真相会如何被渲染。",
        mode_kind="generated_info",
        status_badge="generated",
        client="clash",
        field_keys=[],
        input_schema=[],
        detail_sections=[
            {
                "kind": "mapping",
                "title": "Generated behavior",
                "title_i18n": _text("生成行为", "Generated behavior"),
                "body": "Shared domain / host patterns become DIRECT rules in Mihomo, and only add dns.fake-ip-filter entries when fake-ip mode is enabled. IP/CIDR bypass now belongs to Excluded Routes instead of this family.",
                "body_i18n": _text(
                    "共享的域名 / 主机模式会在 Mihomo 中生成 DIRECT 规则，并且只在 fake-ip 模式下额外进入 dns.fake-ip-filter。IP/CIDR 绕行现在统一归到 Excluded Routes，而不再留在这个 family 里。",
                    "Shared domain / host patterns become DIRECT rules in Mihomo, and only add dns.fake-ip-filter entries when fake-ip mode is enabled. IP/CIDR bypass now belongs to Excluded Routes instead of this family.",
                ),
                "status": "generated",
            }
        ],
        activation_mode=None,
    ))

    real_host_family = {
        "id": "real-host-dns",
        "group_id": "dns",
        "title": "Real Host / Fake-IP Escape",
        "title_i18n": _text("真实主机 / Fake-IP 例外", "Real Host / Fake-IP Escape"),
        "mode_ids": [],
        "default_mode": "",
        "sync_groups": [],
    }
    families.append(real_host_family)
    cards.append(_card(
        card_id="real-host-dns:surge",
        family_id="real-host-dns",
        group_id="dns",
        title="Surge Always Real IP",
        title_zh="Surge 真实主机列表",
        description="Surge native always-real-ip list.",
        description_zh="Surge 原生 always-real-ip 列表。",
        mode_kind="client_native",
        status_badge="stable",
        client="surge",
        field_keys=[LAZYCAT_PROFILE_SURGE_ALWAYS_REAL_IP_KEY],
        input_schema=[_setting_schema({
            "key": LAZYCAT_PROFILE_SURGE_ALWAYS_REAL_IP_KEY,
            "label": "always-real-ip",
            "label_i18n": _text("真实主机列表", "always-real-ip"),
            "type": "list",
            "rows": 5,
            "description": "Domains that should stay on the real-host path instead of fake-IP mapping.",
            "description_i18n": _text("应保持真实主机路径、而不是走 fake-IP 映射的域名。", "Domains that should stay on the real-host path instead of fake-IP mapping."),
        })],
        detail_sections=[
            _mapping_detail([
                ("Surge", "always-real-ip"),
                ("Shadowrocket", "always-real-ip"),
                ("Mihomo", "dns.fake-ip-filter"),
            ]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "Surge exposes this intent directly as always-real-ip.",
                "body_i18n": _text("Surge 直接通过 always-real-ip 暴露这类意图。", "Surge exposes this intent directly as always-real-ip."),
                "status": "stable",
            },
        ],
        activation_mode=None,
    ))
    cards.append(_card(
        card_id="real-host-dns:shadowrocket",
        family_id="real-host-dns",
        group_id="dns",
        title="Shadowrocket Always Real IP",
        title_zh="Shadowrocket 真实主机列表",
        description="Shadowrocket always-real-ip is validated for subscription refresh and retained text export, while runtime routing evidence currently only lands when it is paired with skip-proxy in the constrained LAN probe.",
        description_zh="Shadowrocket always-real-ip 已完成订阅刷新与文本导出保留验证，但当前运行时路由证据只覆盖它与 skip-proxy 联用的受限局域网探针场景。",
        mode_kind="client_native",
        status_badge="limited",
        client="shadowrocket",
        field_keys=[LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY],
        input_schema=[_setting_schema({
            "key": LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY,
            "label": "always-real-ip",
            "label_i18n": _text("真实主机列表", "always-real-ip"),
            "type": "list",
            "rows": 5,
            "description": "Domains kept on the real-host path in Shadowrocket text config.",
            "description_i18n": _text("在 Shadowrocket 文本配置中保持真实主机路径的域名。", "Domains kept on the real-host path in Shadowrocket text config."),
        })],
        detail_sections=[
            _mapping_detail([
                ("Shadowrocket", "always-real-ip"),
                ("Surge", "always-real-ip"),
                ("Mihomo", "dns.fake-ip-filter"),
            ]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "Current evidence covers iPad subscription refresh, retained text export, and a constrained LAN routing probe where always-real-ip only succeeds when paired with skip-proxy. Keep the guidance scoped to that bounded direct-access / fake-IP escape pattern instead of treating it as a blanket DNS guarantee.",
                "body_i18n": _text("当前证据已经覆盖 iPad 订阅刷新、文本导出保留，以及一组受限局域网路由探针；其中 always-real-ip 只有在与 skip-proxy 联用时才拿到正向结果。因此对外表述仍应限定在这类有边界的直连 / fake-IP 例外场景，而不是泛化成所有 DNS 语义都已完全确认。", "Current evidence covers iPad subscription refresh, retained text export, and a constrained LAN routing probe where always-real-ip only succeeds when paired with skip-proxy. Keep the guidance scoped to that bounded direct-access / fake-IP escape pattern instead of treating it as a blanket DNS guarantee."),
                "status": "limited",
            },
        ],
        activation_mode=None,
    ))
    cards.append(_card(
        card_id="real-host-dns:mihomo",
        family_id="real-host-dns",
        group_id="dns",
        title="Mihomo Fake-IP Filter",
        title_zh="Mihomo Fake-IP 过滤",
        description="Compatibility control for fake-ip mode. Edit dns.fake-ip-filter only when you intentionally need a fake-ip exception.",
        description_zh="这是 fake-ip 模式下的兼容控制项。只有当你明确需要 fake-ip 例外时，才编辑 dns.fake-ip-filter。",
        mode_kind="client_native",
        status_badge="generated",
        client="clash",
        field_keys=[LAZYCAT_PROFILE_CLASH_FAKE_IP_FILTER_KEY],
        input_schema=[_setting_schema({
            "key": LAZYCAT_PROFILE_CLASH_FAKE_IP_FILTER_KEY,
            "label": "dns.fake-ip-filter",
            "label_i18n": _text("DNS fake-ip 过滤", "dns.fake-ip-filter"),
            "type": "list",
            "rows": 5,
            "description": "Domain patterns that should bypass fake-IP allocation when Mihomo fake-ip mode is explicitly enabled.",
            "description_i18n": _text("只有在显式启用 Mihomo fake-ip 模式时，这些域名模式才用于绕过 fake-IP 分配。", "Domain patterns that should bypass fake-IP allocation when Mihomo fake-ip mode is explicitly enabled."),
        })],
        detail_sections=[
            _mapping_detail([
                ("Mihomo", "dns.fake-ip-filter"),
                ("Surge", "always-real-ip"),
                ("Shadowrocket", "always-real-ip"),
            ]),
            {
                "kind": "generated",
                "title": "Generated behavior",
                "title_i18n": _text("生成行为", "Generated behavior"),
                "body": "Mihomo has no direct always-real-ip mirror. In this product, dns.fake-ip-filter is a compatibility control for fake-ip mode, while the default LazyCat mainline stays on redir-host + respect-rules + use-hosts.",
                "body_i18n": _text(
                    "Mihomo 没有直接对应的 always-real-ip 镜像。在当前产品里，dns.fake-ip-filter 只作为 fake-ip 模式下的兼容控制项；LazyCat 默认主线仍然是 redir-host + respect-rules + use-hosts。Surge 与 Shadowrocket 继续使用 always-real-ip。",
                    "Mihomo has no direct always-real-ip mirror. In this product, dns.fake-ip-filter is a compatibility control for fake-ip mode, while the default LazyCat mainline stays on redir-host + respect-rules + use-hosts.",
                ),
                "status": "generated",
            },
        ],
        activation_mode=None,
    ))

    host_records_family = {
        "id": "host-records",
        "group_id": "dns",
        "title": "Static Host Mapping",
        "title_i18n": _text("静态主机映射", "Static Host Mapping"),
        "mode_ids": [],
        "default_mode": "",
        "sync_groups": [],
    }
    families.append(host_records_family)
    cards.append(_card(
        card_id="host-records:surge",
        family_id="host-records",
        group_id="dns",
        title="Surge Host Records",
        title_zh="Surge Host Records",
        description="Advanced fallback for Surge [Host]. Use this only when you intentionally need to override platform DNS or pin a hostname for debugging.",
        description_zh="Surge [Host] 的高级兜底映射。只有在你明确要覆盖平台 DNS，或调试时临时钉住 hostname 时才需要填写。",
        mode_kind="client_native",
        status_badge="stable",
        client="surge",
        field_keys=[LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY],
        input_schema=[_setting_schema({
            "key": LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY,
            "label": "Host Records",
            "label_i18n": _text("Host Records", "Host Records"),
            "type": "dict",
            "rows": 6,
            "placeholder": '{"internal.example": "10.0.0.8"}',
            "description": "Advanced hostname -> IP overrides for Surge [Host]. This is a fallback override, not the default LazyCat direct-access path.",
            "description_i18n": _text(
                "填写高级 hostname -> IP 覆盖项，渲染到 Surge [Host]。它是兜底覆盖，不是 LazyCat 直连主路径。",
                "Advanced hostname -> IP overrides for Surge [Host]. This is a fallback override, not the default LazyCat direct-access path.",
            ),
        })],
        detail_sections=[
            _mapping_detail([
                ("Surge", "[Host]"),
                ("Shadowrocket", "[Host]"),
                ("Mihomo", "hosts"),
            ]),
            {
                "kind": "generated",
                "title": "Advanced fallback only",
                "title_i18n": _text("仅作高级兜底", "Advanced fallback only"),
                "body": "Use Host Records only when you intentionally need to override DNS for a special environment. LazyCat direct-access normally relies on always-real-ip and route controls, not on static [Host] entries.",
                "body_i18n": _text(
                    "只有在你明确要覆盖 DNS 的特殊环境里才需要 Host Records。LazyCat 默认直连主路径仍然依赖 always-real-ip 和路由控制，而不是静态 [Host]。",
                    "Use Host Records only when you intentionally need to override DNS for a special environment. LazyCat direct-access normally relies on always-real-ip and route controls, not on static [Host] entries.",
                ),
                "status": "generated",
            },
        ],
        activation_mode=None,
    ))
    cards.append(_card(
        card_id="host-records:shadowrocket",
        family_id="host-records",
        group_id="dns",
        title="Shadowrocket Host Records",
        title_zh="Shadowrocket Host Records",
        description="Advanced fallback for Shadowrocket [Host] with confirmed basic hostname -> IP mapping.",
        description_zh="Shadowrocket [Host] 的高级兜底映射；基础 hostname -> IP 形态已确认可用。",
        mode_kind="client_native",
        status_badge="stable",
        client="shadowrocket",
        field_keys=[LAZYCAT_PROFILE_SHADOWROCKET_HOST_RECORDS_KEY],
        input_schema=[_setting_schema({
            "key": LAZYCAT_PROFILE_SHADOWROCKET_HOST_RECORDS_KEY,
            "label": "Host Records",
            "label_i18n": _text("Host Records", "Host Records"),
            "type": "dict",
            "rows": 6,
            "placeholder": '{"internal.example": "10.0.0.8"}',
            "description": "Advanced hostname -> IP overrides for Shadowrocket [Host].",
            "description_i18n": _text(
                "填写高级 hostname -> IP 覆盖项，渲染到 Shadowrocket [Host]。",
                "Advanced hostname -> IP overrides for Shadowrocket [Host].",
            ),
        })],
        detail_sections=[
            _mapping_detail([
                ("Shadowrocket", "[Host]"),
                ("Surge", "[Host]"),
                ("Mihomo", "hosts"),
            ]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "Basic hostname -> IP mapping is confirmed. Keep this as a debugging or explicit-override fallback instead of the default LazyCat direct-access path.",
                "body_i18n": _text(
                    "基础 hostname -> IP 映射已经确认可用，但它更适合作为调试或显式覆盖的兜底项，不应被当成 LazyCat 直连主路径。",
                    "Basic hostname -> IP mapping is confirmed. Keep this as a debugging or explicit-override fallback instead of the default LazyCat direct-access path.",
                ),
                "status": "stable",
            },
        ],
        activation_mode=None,
    ))
    cards.append(_card(
        card_id="host-records:mihomo",
        family_id="host-records",
        group_id="dns",
        title="Mihomo Hosts",
        title_zh="Mihomo Hosts",
        description="Advanced fallback overrides rendered to Mihomo hosts.",
        description_zh="渲染到 Mihomo hosts 的高级兜底覆盖项。",
        mode_kind="client_native",
        status_badge="stable",
        client="clash",
        field_keys=[LAZYCAT_PROFILE_CLASH_HOST_RECORDS_KEY],
        input_schema=[_setting_schema({
            "key": LAZYCAT_PROFILE_CLASH_HOST_RECORDS_KEY,
            "label": "hosts",
            "label_i18n": _text("静态主机映射", "hosts"),
            "type": "dict",
            "rows": 6,
            "placeholder": '{"internal.example": "10.0.0.8"}',
            "description": "Advanced hostname -> IP overrides rendered to the top-level Mihomo hosts map.",
            "description_i18n": _text(
                "填写高级 hostname -> IP 覆盖项，渲染到 Mihomo 顶层 hosts 映射。",
                "Advanced hostname -> IP overrides rendered to the top-level Mihomo hosts map.",
            ),
        })],
        detail_sections=[
            _mapping_detail([
                ("Mihomo", "hosts"),
                ("Surge", "[Host]"),
                ("Shadowrocket", "[Host]"),
            ]),
            {
                "kind": "generated",
                "title": "Relationship to fake-ip-filter",
                "title_i18n": _text("与 fake-ip-filter 的关系", "Relationship to fake-ip-filter"),
                "body": "LazyCat now defaults Mihomo to redir-host + respect-rules + use-hosts. The hosts map remains an advanced fallback when you explicitly need to override DNS answers.",
                "body_i18n": _text(
                    "LazyCat 现在把 Mihomo 默认主线收敛为 redir-host + respect-rules + use-hosts；hosts 仍然只在你明确要覆盖 DNS 答案时作为高级兜底使用。",
                    "LazyCat now defaults Mihomo to redir-host + respect-rules + use-hosts. The hosts map remains an advanced fallback when you explicitly need to override DNS answers.",
                ),
                "status": "generated",
            },
        ],
        activation_mode=None,
    ))

    mihomo_dns_behavior_family = {
        "id": "mihomo-dns-behavior",
        "group_id": "dns",
        "title": "Mihomo DNS Behavior",
        "title_i18n": _text("Mihomo DNS 行为", "Mihomo DNS Behavior"),
        "mode_ids": ["clash_native"],
        "default_mode": "clash_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY, "keys": [LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY, "keys": [LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY]},
        ],
    }
    families.append(mihomo_dns_behavior_family)
    cards.append(_card(
        card_id="mihomo-dns-behavior:clash",
        family_id="mihomo-dns-behavior",
        group_id="dns",
        title="Mihomo DNS Behavior",
        title_zh="Mihomo DNS 行为",
        description="Core Mihomo DNS switches. The default LazyCat mainline is redir-host + respect-rules + use-hosts; fake-ip, TUN, and sniffer controls stay explicit.",
        description_zh="Mihomo 的核心 DNS 开关。LazyCat 当前默认主线是 redir-host + respect-rules + use-hosts；fake-ip、TUN 与 sniffer 控制项保持显式开启。",
        mode_kind="client_native",
        status_badge="stable",
        client="clash",
        field_keys=[
            LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY,
            LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY,
            LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY,
        ],
        input_schema=[
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY,
                "label": "dns.enable",
                "label_i18n": _text("DNS 开关", "dns.enable"),
                "type": "bool",
                "description": "Turn Mihomo DNS processing on or off.",
                "description_i18n": _text("开启或关闭 Mihomo DNS 处理。", "Turn Mihomo DNS processing on or off."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY,
                "label": "dns.listen",
                "label_i18n": _text("DNS 监听地址", "dns.listen"),
                "type": "string",
                "placeholder": "127.0.0.1:1053",
                "placeholder_i18n": _text("127.0.0.1:1053", "127.0.0.1:1053"),
                "description": "Local listen address for Mihomo DNS.",
                "description_i18n": _text("Mihomo DNS 的本地监听地址。", "Local listen address for Mihomo DNS."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY,
                "label": "dns.enhanced-mode",
                "label_i18n": _text("增强模式", "dns.enhanced-mode"),
                "type": "select",
                "options": [
                    {"value": "fake-ip", "label": "fake-ip", "label_i18n": _text("fake-ip", "fake-ip")},
                    {"value": "redir-host", "label": "redir-host", "label_i18n": _text("redir-host", "redir-host")},
                ],
                "description": "Choose fake-ip or redir-host behavior.",
                "description_i18n": _text("选择 fake-ip 或 redir-host 行为。", "Choose fake-ip or redir-host behavior."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY,
                "label": "dns.use-hosts",
                "label_i18n": _text("使用 hosts", "dns.use-hosts"),
                "type": "bool",
                "description": "Keep the top-level hosts map active on the redir-host mainline.",
                "description_i18n": _text("在 redir-host 主线上继续让顶层 hosts 映射生效。", "Keep the top-level hosts map active on the redir-host mainline."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY,
                "label": "dns.fake-ip-range",
                "label_i18n": _text("fake-ip 地址段", "dns.fake-ip-range"),
                "type": "string",
                "placeholder": "198.18.0.1/16",
                "placeholder_i18n": _text("198.18.0.1/16", "198.18.0.1/16"),
                "description": "CIDR range used only when fake-ip mode is enabled.",
                "description_i18n": _text("仅在启用 fake-ip 模式时使用的 CIDR 地址段。", "CIDR range used only when fake-ip mode is enabled."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY,
                "label": "dns.fake-ip-filter-mode",
                "label_i18n": _text("fake-ip 过滤模式", "dns.fake-ip-filter-mode"),
                "type": "select",
                "options": [
                    {"value": "rule", "label": "rule", "label_i18n": _text("rule", "rule")},
                    {"value": "blacklist", "label": "blacklist", "label_i18n": _text("blacklist", "blacklist")},
                    {"value": "whitelist", "label": "whitelist", "label_i18n": _text("whitelist", "whitelist")},
                ],
                "description": "How Mihomo applies fake-ip-filter entries when fake-ip mode is enabled.",
                "description_i18n": _text("仅在启用 fake-ip 模式时，Mihomo 如何应用 fake-ip-filter 条目。", "How Mihomo applies fake-ip-filter entries when fake-ip mode is enabled."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY,
                "label": "dns.respect-rules",
                "label_i18n": _text("遵循规则", "dns.respect-rules"),
                "type": "bool",
                "description": "Whether DNS resolution should respect routing rules.",
                "description_i18n": _text("DNS 解析是否遵循路由规则。", "Whether DNS resolution should respect routing rules."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY,
                "label": "dns.nameserver-policy",
                "label_i18n": _text("域名服务器策略", "dns.nameserver-policy"),
                "type": "dict",
                "rows": 8,
                "placeholder": '{\"+.example.com\": [\"https://dns.google/dns-query\"]}',
                "placeholder_i18n": _text(
                    '{\"+.example.com\": [\"https://dns.google/dns-query\"]}',
                    '{\"+.example.com\": [\"https://dns.google/dns-query\"]}',
                ),
                "description": "Per-domain upstream DNS policy.",
                "description_i18n": _text("按域名指定上游 DNS 策略。", "Per-domain upstream DNS policy."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY,
                "label": "tun.dns-hijack",
                "label_i18n": _text("TUN DNS 接管", "tun.dns-hijack"),
                "type": "list",
                "rows": 4,
                "description": "Advanced control: intercept local DNS traffic and hand it to Mihomo DNS when TUN is enabled.",
                "description_i18n": _text("高级控制项：在启用 TUN 时，把本地 DNS 流量接管到 Mihomo DNS。", "Advanced control: intercept local DNS traffic and hand it to Mihomo DNS when TUN is enabled."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY,
                "label": "sniffer.force-dns-mapping",
                "label_i18n": _text("嗅探强制 DNS 映射", "sniffer.force-dns-mapping"),
                "type": "bool",
                "description": "Advanced control: reuse sniffed hostname results to strengthen DNS mapping when sniffer is enabled.",
                "description_i18n": _text("高级控制项：在启用 sniffer 时，把嗅探得到的主机名结果回灌给 DNS 映射决策。", "Advanced control: reuse sniffed hostname results to strengthen DNS mapping when sniffer is enabled."),
            }),
        ],
        detail_sections=[
            _mapping_detail([
                ("Mihomo", "dns.enable / listen / enhanced-mode / use-hosts"),
                ("Mihomo", "dns.fake-ip-range / fake-ip-filter-mode (fake-ip only)"),
                ("Mihomo", "dns.respect-rules / nameserver-policy"),
                ("Mihomo", "tun.dns-hijack / sniffer.force-dns-mapping (advanced)"),
            ]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "These are first-class Mihomo DNS controls. The product now defaults to the redir-host mainline, while fake-ip, TUN, and sniffer controls stay explicit instead of being silently assumed.",
                "body_i18n": _text(
                    "这些都是 Mihomo 的一等 DNS 控制项，所以刻意保持原生编辑，而不伪装成和 Surge 或 Shadowrocket 共享。产品默认主线现在收敛为 redir-host；fake-ip、TUN 与 sniffer 都必须显式开启。",
                    "These are first-class Mihomo DNS controls. The product now defaults to the redir-host mainline, while fake-ip, TUN, and sniffer controls stay explicit instead of being silently assumed.",
                ),
                "status": "stable",
            },
            {
                "kind": "behavior",
                "title": "DNS / TUN / Sniffer interaction",
                "title_i18n": _text("DNS / TUN / 嗅探联动", "DNS / TUN / Sniffer interaction"),
                "body": "The default LazyCat Mihomo path is redir-host + respect-rules + use-hosts. tun.dns-hijack and sniffer.force-dns-mapping remain advanced controls: enable them only when you are deliberately testing TUN or sniffer behavior.",
                "body_i18n": _text(
                    "LazyCat 当前把 Mihomo 默认主线收敛为 redir-host + respect-rules + use-hosts。tun.dns-hijack 和 sniffer.force-dns-mapping 仍然是高级控制项；只有在你明确验证 TUN 或 sniffer 行为时才应开启。",
                    "The default LazyCat Mihomo path is redir-host + respect-rules + use-hosts. tun.dns-hijack and sniffer.force-dns-mapping remain advanced controls: enable them only when you are deliberately testing TUN or sniffer behavior.",
                ),
                "status": "stable",
            },
        ],
        activation_mode="clash_native",
    ))

    mihomo_dns_upstreams_family = {
        "id": "mihomo-dns-upstreams",
        "group_id": "dns",
        "title": "Mihomo DNS Upstreams",
        "title_i18n": _text("Mihomo DNS 上游", "Mihomo DNS Upstreams"),
        "mode_ids": ["clash_native"],
        "default_mode": "clash_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY]},
            {"primary_key": LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY, "keys": [LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY]},
        ],
    }
    families.append(mihomo_dns_upstreams_family)
    cards.append(_card(
        card_id="mihomo-dns-upstreams:clash",
        family_id="mihomo-dns-upstreams",
        group_id="dns",
        title="Mihomo DNS Upstreams",
        title_zh="Mihomo DNS 上游",
        description="Upstream DNS servers used by Mihomo for bootstrap, normal resolution, proxy hostname lookup, and direct-path resolution.",
        description_zh="Mihomo 在引导解析、普通解析、代理主机名解析与直连路径解析中使用的上游 DNS。",
        mode_kind="client_native",
        status_badge="stable",
        client="clash",
        field_keys=[
            LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY,
            LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY,
        ],
        input_schema=[
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY,
                "label": "dns.default-nameserver",
                "label_i18n": _text("默认 DNS", "dns.default-nameserver"),
                "type": "list",
                "rows": 4,
                "description": "Bootstrap resolvers used before DoH/DoT upstreams are reachable.",
                "description_i18n": _text("在 DoH/DoT 等上游可用前用于引导解析的基础 DNS。", "Bootstrap resolvers used before DoH/DoT upstreams are reachable."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY,
                "label": "dns.nameserver",
                "label_i18n": _text("主 DNS 上游", "dns.nameserver"),
                "type": "list",
                "rows": 4,
                "description": "Primary upstream nameservers for normal resolution.",
                "description_i18n": _text("普通解析流程使用的主上游 DNS。", "Primary upstream nameservers for normal resolution."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY,
                "label": "dns.fallback",
                "label_i18n": _text("回退 DNS 上游", "dns.fallback"),
                "type": "list",
                "rows": 4,
                "description": "Fallback resolvers used when the main path is unsuitable.",
                "description_i18n": _text("主解析路径不适合时使用的回退 DNS。", "Fallback resolvers used when the main path is unsuitable."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY,
                "label": "dns.proxy-server-nameserver",
                "label_i18n": _text("代理服务器解析 DNS", "dns.proxy-server-nameserver"),
                "type": "list",
                "rows": 4,
                "description": "Resolvers used specifically for proxy server hostnames.",
                "description_i18n": _text("专门用于解析代理服务器主机名的 DNS。", "Resolvers used specifically for proxy server hostnames."),
            }),
            _setting_schema({
                "key": LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY,
                "label": "dns.direct-nameserver",
                "label_i18n": _text("直连解析 DNS", "dns.direct-nameserver"),
                "type": "list",
                "rows": 4,
                "description": "Resolvers used for domains that should be resolved on the direct path.",
                "description_i18n": _text("需要在直连路径上解析的域名所使用的 DNS。", "Resolvers used for domains that should be resolved on the direct path."),
            }),
        ],
        detail_sections=[
            _mapping_detail([
                ("Mihomo", "dns.default-nameserver / nameserver / fallback"),
                ("Mihomo", "dns.proxy-server-nameserver / direct-nameserver"),
            ]),
            {
                "kind": "support",
                "title": "Support",
                "title_i18n": _text("支持状态", "Support"),
                "body": "These upstream selectors are native Mihomo DNS controls. Keeping them together lets the redir-host mainline, respect-rules behavior, and proxy hostname resolution stay visible in one place.",
                "body_i18n": _text(
                    "这些上游选择器都是 Mihomo 原生 DNS 控制项。把它们放进同一个工作台，就是为了让 redir-host 主线、respect-rules 行为和代理主机名解析都能在同一处被看见。",
                    "These upstream selectors are native Mihomo DNS controls. Keeping them together lets the redir-host mainline, respect-rules behavior, and proxy hostname resolution stay visible in one place.",
                ),
                "status": "stable",
            },
        ],
        activation_mode="clash_native",
    ))

    for family_id, capability_id, subfield_id, title, title_zh, description, description_zh, surge_key, sr_key in (
        (
            "url-rewrite",
            "url-rewrite",
            "rules",
            "URL Rewrite",
            "URL 重写",
            "Client-native URL rewrite syntax.",
            "客户端原生 URL 重写语法。",
            LAZYCAT_PROFILE_SURGE_URL_REWRITE_KEY,
            LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY,
        ),
        (
            "map-local",
            "surge-http-pipeline",
            "map_local",
            "Map Local",
            "本地映射",
            "Client-native local resource mapping.",
            "客户端原生的本地资源映射。",
            LAZYCAT_PROFILE_SURGE_MAP_LOCAL_KEY,
            LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY,
        ),
    ):
        family = {
            "id": family_id,
            "group_id": "rewrite-and-mitm",
            "title": title,
            "title_i18n": _text(title_zh, title),
            "mode_ids": ["surge_native", "shadowrocket_experimental", "mihomo_unsupported"],
            "default_mode": "surge_native",
            "sync_groups": [
                {"primary_key": surge_key, "keys": [surge_key]},
                {"primary_key": sr_key, "keys": [sr_key]},
            ],
        }
        families.append(family)
        cards.append(_card(
            card_id=f"{family_id}:surge",
            family_id=family_id,
            group_id="rewrite-and-mitm",
            title=f"Surge {title}",
            title_zh=f"Surge {title_zh}",
            description=description,
            description_zh=description_zh,
            mode_kind="client_native",
            status_badge="stable",
            client="surge",
            field_keys=[surge_key],
            input_schema=[_subfield_field(capability_id, subfield_id, "surge")],
            detail_sections=_subfield_detail(
                capability_id,
                subfield_id,
                "surge",
                mappings=[("Surge", title)],
            ),
            activation_mode="surge_native",
        ))
        cards.append(_card(
            card_id=f"{family_id}:shadowrocket",
            family_id=family_id,
            group_id="rewrite-and-mitm",
            title=f"Shadowrocket {title}",
            title_zh=f"Shadowrocket {title_zh}",
            description=(
                "Saved Map Local entries are omitted from Shadowrocket output. Prefer Script for response rewriting or mock payloads."
                if family_id == "map-local"
                else "Confirmed Shadowrocket HTTP pipeline field with product-specific limits."
            ),
            description_zh=(
                "Map Local 设置保留但不下发到 Shadowrocket；如需改写响应或返回 mock 内容，请优先改用 Script。"
                if family_id == "map-local"
                else "已确认可用、但带产品边界说明的 Shadowrocket HTTP 管线字段。"
            ),
            mode_kind=(
                _card_mode_kind_from_view(_find_subfield(capability_id, subfield_id)[1]["clients"]["shadowrocket"])
                if family_id == "map-local"
                else "client_native"
            ),
            status_badge=(
                _card_status_badge_from_view(_find_subfield(capability_id, subfield_id)[1]["clients"]["shadowrocket"])
                if family_id == "map-local"
                else "stable"
            ),
            client="shadowrocket",
            field_keys=[sr_key],
            input_schema=[_subfield_field(capability_id, subfield_id, "shadowrocket")],
            detail_sections=(
                [{
                    "kind": "recommendation",
                    "title": "Recommended path",
                    "title_i18n": _text("推荐路径", "Recommended path"),
                    "body": "Saved Map Local entries are omitted from output. To rewrite response bodies or return mock payloads, switch to Shadowrocket Script instead.",
                    "body_i18n": _text(
                        "已保存的 Map Local 条目不会下发；如果要改写响应体或返回 mock 内容，请改用 Shadowrocket Script。",
                        "Saved Map Local entries are omitted from output. To rewrite response bodies or return mock payloads, switch to Shadowrocket Script instead.",
                    ),
                    "status": "limited",
                }] if family_id == "map-local" else []
            ) + _subfield_detail(
                capability_id,
                subfield_id,
                "shadowrocket",
                mappings=[("Shadowrocket", title)],
            ),
            activation_mode="shadowrocket_experimental",
        ))
        cards.append(_card(
            card_id=f"{family_id}:mihomo",
            family_id=family_id,
            group_id="rewrite-and-mitm",
            title=f"Mihomo {title}",
            title_zh=f"Mihomo {title_zh}",
            description="Mihomo does not expose an equivalent HTTP interception layer for this feature.",
            description_zh="Mihomo 没有与此能力等价的 HTTP 拦截层。",
            mode_kind="unsupported",
            status_badge="unsupported",
            client="clash",
            field_keys=[],
            input_schema=[],
            detail_sections=_subfield_detail(
                capability_id,
                subfield_id,
                "clash",
                mappings=[("Mihomo", "unsupported")],
            ),
            activation_mode="mihomo_unsupported",
        ))

    script_family = {
        "id": "script",
        "group_id": "rewrite-and-mitm",
        "title": "Script",
        "title_i18n": _text("脚本", "Script"),
        "mode_ids": ["shadowrocket_experimental", "surge_unsupported", "mihomo_unsupported"],
        "default_mode": "shadowrocket_experimental",
        "sync_groups": [
            {
                "primary_key": LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY,
                "keys": [LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY],
            },
            {
                "primary_key": LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY,
                "keys": [LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY],
            },
        ],
    }
    families.append(script_family)
    cards.append(_card(
        card_id="script:shadowrocket",
        family_id="script",
        group_id="rewrite-and-mitm",
        title="Shadowrocket Script",
        title_zh="Shadowrocket 脚本",
        description="Recommended primary path for request/response interception, response rewrites, and mock payload delivery in Shadowrocket.",
        description_zh="Shadowrocket 中处理请求/响应拦截、响应改写和 mock 返回内容的首选主路径。",
        mode_kind="client_native",
        status_badge="stable",
        client="shadowrocket",
        field_keys=[
            LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY,
            LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY,
        ],
        input_schema=[
            _subfield_field("script", "request", "shadowrocket"),
            _subfield_field("script", "response", "shadowrocket"),
        ],
        detail_sections=[
            {
                "kind": "recommendation",
                "title": "Recommended path",
                "title_i18n": _text("推荐路径", "Recommended path"),
                "body": "Use Script as the primary Shadowrocket HTTP pipeline tool for request hooks, response body rewriting, or mock payload delivery. Saved Map Local entries are omitted from output.",
                "body_i18n": _text(
                    "请求钩子、响应体改写或 mock 返回内容使用 Shadowrocket Script；Map Local 设置保留但不会下发。",
                    "Use Script as the primary Shadowrocket HTTP pipeline tool for request hooks, response body rewriting, or mock payload delivery. Saved Map Local entries are omitted from output.",
                ),
                "status": "stable",
            },
            _mapping_detail([
                ("Shadowrocket", "Script request"),
                ("Shadowrocket", "Script response"),
            ]),
            *_support_detail(dict(_find_subfield("script", "request")[1]["clients"]["shadowrocket"])),
            *_support_detail(dict(_find_subfield("script", "response")[1]["clients"]["shadowrocket"])),
        ],
        activation_mode="shadowrocket_experimental",
    ))
    cards.append(_card(
        card_id="script:surge",
        family_id="script",
        group_id="rewrite-and-mitm",
        title="Surge Script",
        title_zh="Surge 脚本",
        description="Not expanded in this product editor yet.",
        description_zh="当前产品编辑器里暂未展开。",
        mode_kind="unsupported",
        status_badge="unsupported",
        client="surge",
        field_keys=[],
        input_schema=[],
        detail_sections=_support_detail(dict(_find_subfield("script", "request")[1]["clients"]["surge"])),
        activation_mode="surge_unsupported",
    ))
    cards.append(_card(
        card_id="script:mihomo",
        family_id="script",
        group_id="rewrite-and-mitm",
        title="Mihomo Script",
        title_zh="Mihomo 脚本",
        description="Mihomo has no equivalent HTTP interception script layer.",
        description_zh="Mihomo 没有等价的 HTTP 拦截脚本层。",
        mode_kind="unsupported",
        status_badge="unsupported",
        client="clash",
        field_keys=[],
        input_schema=[],
        detail_sections=_support_detail(dict(_find_subfield("script", "request")[1]["clients"]["clash"])),
        activation_mode="mihomo_unsupported",
    ))

    mitm_family = {
        "id": "mitm",
        "group_id": "rewrite-and-mitm",
        "title": "MITM Hostname",
        "title_i18n": _text("MITM 主机名", "MITM Hostname"),
        "mode_ids": ["surge_native", "shadowrocket_experimental", "mihomo_unsupported"],
        "default_mode": "surge_native",
        "sync_groups": [
            {"primary_key": LAZYCAT_PROFILE_SURGE_MITM_HOSTNAME_KEY, "keys": [LAZYCAT_PROFILE_SURGE_MITM_HOSTNAME_KEY]},
            {"primary_key": LAZYCAT_PROFILE_SURGE_MITM_SKIP_SERVER_CERT_VERIFY_KEY, "keys": [LAZYCAT_PROFILE_SURGE_MITM_SKIP_SERVER_CERT_VERIFY_KEY]},
            {"primary_key": LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY, "keys": [LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY]},
        ],
    }
    families.append(mitm_family)
    cards.append(_card(
        card_id="mitm:surge",
        family_id="mitm",
        group_id="rewrite-and-mitm",
        title="Surge MITM",
        title_zh="Surge MITM",
        description="Surge MITM hostname and certificate behavior.",
        description_zh="Surge 的 MITM 主机名与证书行为。",
        mode_kind="client_native",
        status_badge="stable",
        client="surge",
        field_keys=[
            LAZYCAT_PROFILE_SURGE_MITM_HOSTNAME_KEY,
            LAZYCAT_PROFILE_SURGE_MITM_SKIP_SERVER_CERT_VERIFY_KEY,
            LAZYCAT_PROFILE_SURGE_MITM_H2_KEY,
            LAZYCAT_PROFILE_SURGE_MITM_TCP_CONNECTION_KEY,
        ],
        input_schema=[
            _subfield_field("mitm-hostname", "hostname", "surge"),
            _subfield_field("mitm-hostname", "skip_cert_verify", "surge"),
            _subfield_field("mitm-hostname", "h2", "surge"),
            _subfield_field("mitm-hostname", "tcp_connection", "surge"),
        ],
        detail_sections=[
            _mapping_detail([
                ("Surge", "hostname"),
                ("Surge", "skip-server-cert-verify"),
                ("Surge", "h2"),
                ("Surge", "tcp-connection"),
            ]),
            *_support_detail(dict(_find_subfield("mitm-hostname", "hostname")[1]["clients"]["surge"])),
            *_support_detail(dict(_find_subfield("mitm-hostname", "h2")[1]["clients"]["surge"])),
        ],
        activation_mode="surge_native",
    ))
    cards.append(_card(
        card_id="mitm:shadowrocket",
        family_id="mitm",
        group_id="rewrite-and-mitm",
        title="Shadowrocket MITM",
        title_zh="Shadowrocket MITM",
        description="Confirmed Shadowrocket MITM hostname entry with certificate and port limits.",
        description_zh="已确认可用、但仍受证书链与端口范围限制的 Shadowrocket MITM 主机名入口。",
        mode_kind=_card_mode_kind_from_view(_find_subfield("mitm-hostname", "hostname")[1]["clients"]["shadowrocket"]),
        status_badge=_card_status_badge_from_view(_find_subfield("mitm-hostname", "hostname")[1]["clients"]["shadowrocket"]),
        client="shadowrocket",
        field_keys=[LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY],
        input_schema=[_subfield_field("mitm-hostname", "hostname", "shadowrocket")],
        detail_sections=_subfield_detail(
            "mitm-hostname",
            "hostname",
            "shadowrocket",
            mappings=[("Shadowrocket", "hostname")],
        ),
        activation_mode="shadowrocket_experimental",
    ))
    cards.append(_card(
        card_id="mitm:mihomo",
        family_id="mitm",
        group_id="rewrite-and-mitm",
        title="Mihomo MITM",
        title_zh="Mihomo MITM",
        description="Mihomo cannot provide Surge-style HTTP MITM processing in this product model.",
        description_zh="Mihomo 在当前产品模型下无法提供 Surge 式 HTTP MITM 处理。",
        mode_kind="unsupported",
        status_badge="unsupported",
        client="clash",
        field_keys=[],
        input_schema=[],
        detail_sections=_subfield_detail(
            "mitm-hostname",
            "hostname",
            "clash",
            mappings=[("Mihomo", "unsupported")],
        ),
        activation_mode="mihomo_unsupported",
    ))

    default_mode = {family["id"]: family["default_mode"] for family in families}
    return {
        "groups": groups,
        "families": families,
        "cards": cards,
        "default_mode": default_mode,
        "detail_sections": {
            "legend": {
                "stable": _text("稳定", "Stable"),
                "limited": _text("受限", "Limited"),
                "experimental": _text("实验性", "Experimental"),
                "unsupported": _text("不可用", "Unsupported"),
                "generated": _text("拆分生成", "Generated"),
            }
        },
        "legacy_handling": {
            "title": "Legacy profile",
            "title_i18n": _text("旧模型配置", "Legacy profile"),
            "message": "This profile still uses the legacy matrix model. Reset before editing with capability cards.",
            "message_i18n": _text(
                "这个配置仍在使用旧的矩阵模型。请先重置，再使用能力卡编辑。",
                "This profile still uses the legacy matrix model. Reset before editing with capability cards.",
            ),
            "action_label": "Reset to new editor",
            "action_label_i18n": _text("重置到新编辑器", "Reset to new editor"),
        },
    }


_PROFILE_EDITOR_SCHEMA = profile_editor_schema_payload()


def _family_modes() -> dict[str, dict[str, dict[str, Any]]]:
    modes: dict[str, dict[str, dict[str, Any]]] = {}
    families = {family["id"]: family for family in _PROFILE_EDITOR_SCHEMA["families"]}
    for family_id, family in families.items():
        family_modes = {
            mode_id: {
                "field_keys": set(),
                "sync_groups": [],
            }
            for mode_id in family.get("mode_ids", [])
        }
        for card in _PROFILE_EDITOR_SCHEMA["cards"]:
            if card["family_id"] != family_id:
                continue
            activation = card.get("activation") or {}
            mode_id = str(activation.get("mode") or "")
            if mode_id not in family_modes:
                continue
            family_modes[mode_id]["field_keys"].update(card.get("field_keys") or [])
        for mode_id in family_modes:
            if mode_id == "shared":
                family_modes[mode_id]["sync_groups"] = list(family.get("sync_groups") or [])
            elif mode_id.endswith("_native") or mode_id.endswith("_experimental") or mode_id.endswith("_split"):
                family_modes[mode_id]["sync_groups"] = [
                    group for group in family.get("sync_groups") or []
                    if set(group.get("keys") or []).intersection(family_modes[mode_id]["field_keys"])
                ]
        modes[family_id] = family_modes
    return modes


_PROFILE_EDITOR_FAMILY_MODES = _family_modes()


def apply_editor_state_to_settings(
    settings: Mapping[str, object] | None,
    editor_state: Mapping[str, object] | None,
    *,
    current_settings: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    normalized = normalize_lazycat_profile_settings(settings or {})
    state = normalize_profile_editor_state(editor_state, legacy_default=False)
    default_mode = dict(_PROFILE_EDITOR_SCHEMA.get("default_mode") or {})

    for family_id, family_modes in _PROFILE_EDITOR_FAMILY_MODES.items():
        requested_mode = str(state["families"].get(family_id) or "")
        active_mode = requested_mode
        if active_mode not in family_modes:
            active_mode = _SKIP_PROXY_LEGACY_MODE_ALIASES.get(active_mode, "")
        if active_mode not in family_modes:
            active_mode = str(default_mode.get(family_id) or "")
        allowed_keys = set()
        sync_groups = []
        if active_mode in family_modes:
            allowed_keys = set(family_modes[active_mode]["field_keys"])
            if active_mode != "shared":
                sync_groups = list(family_modes[active_mode]["sync_groups"])
        family_all_keys = {
            key
            for mode in family_modes.values()
            for key in mode["field_keys"]
        }
        for group in sync_groups:
            keys = [str(key) for key in group.get("keys") or []]
            primary_key = str(group.get("primary_key") or "")
            if not primary_key or primary_key not in normalized:
                continue
            value = normalized.get(primary_key)
            for key in keys:
                if key in allowed_keys:
                    normalized[key] = value
        for key in family_all_keys - allowed_keys:
            if key in normalized:
                normalized[key] = normalize_lazycat_profile_settings({}).get(key)
    return harmonize_profile_single_source_settings(normalized, current_settings=current_settings)
