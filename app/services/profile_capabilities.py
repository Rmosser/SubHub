from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.services.lazycat_profile import (
    LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY,
    LAZYCAT_PROFILE_CLASH_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY,
    LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY,
    LAZYCAT_PROFILE_LOG_LEVEL_OPTIONS,
    LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY,
    LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY,
    LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY,
    LAZYCAT_PROFILE_CLASH_SECRET_KEY,
    LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY,
    LAZYCAT_PROFILE_CLASH_IPV6_KEY,
    LAZYCAT_PROFILE_SETTING_KEYS,
    LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY,
    LAZYCAT_PROFILE_SURGE_BLOCK_QUIC_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_SECRET_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_TLS_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_WEB_DASHBOARD_KEY,
    LAZYCAT_PROFILE_SURGE_IPV6_KEY,
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

ProfileCapabilityGroup = dict[str, Any]
ProfileCapabilityRegistry = list[ProfileCapabilityGroup]
SupportKind = Literal["mirror_missing", "client_missing"]
EditingMode = Literal["shared", "standalone", "experimental", "adapted", "unavailable"]


def _text(zh: str, en: str) -> dict[str, str]:
    return {
        "zh": zh,
        "en": en,
    }


def _support(
    status: str,
    reason: str,
    reason_zh: str | None = None,
    *,
    diagnostic_codes: list[str] | None = None,
    kind: SupportKind | None = None,
) -> dict[str, Any]:
    support_kind = kind
    if support_kind is None and status == "unsupported":
        support_kind = "mirror_missing"
    return {
        "status": status,
        "reason": reason,
        "reason_i18n": _text(reason_zh or reason, reason),
        "diagnostic_codes": list(diagnostic_codes or []),
        "kind": support_kind,
    }


def _view(
    *,
    key: str | None = None,
    label: str,
    label_zh: str | None = None,
    field_type: str,
    options: tuple[dict[str, Any], ...] | None = None,
    placeholder: str = "",
    placeholder_zh: str | None = None,
    rows: int | None = None,
    description: str = "",
    description_zh: str | None = None,
    support: dict[str, Any],
    editing_mode_override: EditingMode | None = None,
    adapted_hint: str = "",
    adapted_hint_zh: str | None = None,
    adapted_targets: list[dict[str, str]] | None = None,
    syntax_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    editing_mode: EditingMode
    if editing_mode_override is not None:
        editing_mode = editing_mode_override
    else:
        support_status = str(support.get("status") or "").strip()
        support_kind = str(support.get("kind") or "").strip()
        if support_status in {"supported", "auto_mapped"}:
            editing_mode = "shared"
        elif support_status == "pending_validation" and key:
            editing_mode = "experimental"
        elif support_status == "unsupported" and key and support_kind != "client_missing":
            editing_mode = "standalone"
        else:
            editing_mode = "unavailable"
    payload: dict[str, Any] = {
        "label": label,
        "label_i18n": _text(label_zh or label, label),
        "type": field_type,
        "description": description,
        "description_i18n": _text(description_zh or description, description),
        "support": support,
        "editing_mode": editing_mode,
    }
    if key:
        payload["key"] = key
    if options:
        payload["options"] = [dict(option) for option in options]
    if placeholder:
        payload["placeholder"] = placeholder
        payload["placeholder_i18n"] = _text(placeholder_zh or placeholder, placeholder)
    if rows is not None:
        payload["rows"] = rows
    if adapted_hint:
        payload["adapted_hint"] = adapted_hint
        payload["adapted_hint_i18n"] = _text(adapted_hint_zh or adapted_hint, adapted_hint)
    if adapted_targets:
        payload["adapted_targets"] = adapted_targets
    if syntax_hints:
        payload["syntax_hints"] = syntax_hints
    return payload


def _subfield(
    *,
    subfield_id: str,
    label: str,
    label_zh: str | None = None,
    source_client: str,
    description: str = "",
    description_zh: str | None = None,
    clients: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": subfield_id,
        "label": label,
        "label_i18n": _text(label_zh or label, label),
        "source_client": source_client,
        "description": description,
        "description_i18n": _text(description_zh or description, description),
        "clients": clients,
    }


def _all_capabilities() -> ProfileCapabilityRegistry:
    return [
        {
            "id": "shared-routing",
            "title": "Shared Routing",
            "title_i18n": _text("共享路由", "Shared Routing"),
            "description": "These settings are shared across supported clients — edit once and they take effect everywhere.",
            "description_i18n": _text(
                "这些设置在支持的客户端之间共享，编辑一次即可生效。",
                "These settings are shared across supported clients — edit once and they take effect everywhere.",
            ),
            "capabilities": [
                {
                    "id": "excluded-routes",
                    "title": "Excluded Routes",
                    "title_i18n": _text("排除路由", "Excluded Routes"),
                    "description": "Manage IP/CIDR addresses that bypass the TUN tunnel.",
                    "description_i18n": _text(
                        "管理 TUN 隧道绕行的 IP/CIDR 地址。",
                        "Manage IP/CIDR addresses that bypass the TUN tunnel.",
                    ),
                    "subfields": [
                        _subfield(
                            subfield_id="routes",
                            label="Excluded routes",
                            label_zh="排除路由",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY,
                                    label="tun-excluded-routes",
                                    label_zh="排除路由",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "auto_mapped",
                                        "Auto-synced from Mihomo.",
                                        "自动从 Mihomo 同步。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY,
                                    label="tun.route-exclude-address",
                                    label_zh="排除路由地址",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "supported",
                                        "Your edits sync to other clients automatically.",
                                        "你的编辑会自动同步到其他客户端。",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY,
                                    label="tun-excluded-routes",
                                    label_zh="排除路由",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "auto_mapped",
                                        "Auto-synced from Mihomo.",
                                        "自动从 Mihomo 同步。",
                                    ),
                                ),
                            },
                        )
                    ],
                },
                {
                    "id": "ipv6-policy",
                    "title": "IPv6 Preference",
                    "title_i18n": _text("IPv6 偏好", "IPv6 Preference"),
                    "description": "Synchronize the IPv6 preference; Shadowrocket cannot disable IPv6 with this field.",
                    "description_i18n": _text(
                        "同步 IPv6 偏好；Shadowrocket 的此字段无法关闭 IPv6。",
                        "Synchronize the IPv6 preference; Shadowrocket cannot disable IPv6 with this field.",
                    ),
                    "subfields": [
                        _subfield(
                            subfield_id="enabled",
                            label="IPv6",
                            label_zh="IPv6",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_IPV6_KEY,
                                    label="ipv6",
                                    label_zh="IPv6",
                                    field_type="bool",
                                    support=_support(
                                        "supported",
                                        "Your edits sync to other clients automatically.",
                                        "你的编辑会自动同步到其他客户端。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_IPV6_KEY,
                                    label="ipv6",
                                    label_zh="IPv6",
                                    field_type="bool",
                                    support=_support(
                                        "auto_mapped",
                                        "Auto-synced from Surge.",
                                        "自动从 Surge 同步。",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY,
                                    label="ipv6",
                                    label_zh="IPv6",
                                    field_type="bool",
                                    support=_support(
                                        "downgraded",
                                        "2.2.93 ipv6=false does not disable IPv6 at runtime; restrict it with rules.",
                                        "2.2.93 的 ipv6=false 不能关闭运行时 IPv6，需用规则限制。",
                                    ),
                                ),
                            },
                        )
                    ],
                },
            ],
        },
        {
            "id": "mihomo-core",
            "title": "Mihomo Core",
            "title_i18n": _text("Mihomo 核心", "Mihomo Core"),
            "description": "Mihomo-only settings.",
            "description_i18n": _text("仅 Mihomo 可用的设置。", "Mihomo-only settings."),
            "capabilities": [
                {
                    "id": "mihomo-runtime",
                    "title": "Runtime Access",
                    "title_i18n": _text("运行时访问", "Runtime Access"),
                    "description": "Core runtime settings for Mihomo.",
                    "description_i18n": _text("Mihomo 核心运行时设置。", "Core runtime settings for Mihomo."),
                    "subfields": [
                        _subfield(
                            subfield_id="log_level",
                            label="Log level",
                            label_zh="日志级别",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_LOGLEVEL_KEY,
                                    label="loglevel",
                                    label_zh="日志级别",
                                    field_type="string",
                                    support=_support(
                                        "unsupported",
                                        "No shared Mihomo mirror. Manage `surge_loglevel` in Surge-native terms when you need a client-specific override.",
                                        "这个字段没有共享到 Mihomo 的镜像；如果需要客户端特定覆写，请按 Surge 原生语义单独管理 `surge_loglevel`。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY,
                                    label="log-level",
                                    label_zh="日志级别",
                                    field_type="select",
                                    options=LAZYCAT_PROFILE_LOG_LEVEL_OPTIONS[LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY],
                                    placeholder="info",
                                    placeholder_zh="info",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="loglevel",
                                    label_zh="日志级别",
                                    field_type="string",
                                    support=_support(
                                        "unsupported",
                                        "Mihomo only.",
                                        "仅 Mihomo 可用。",
                                    ),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="mixed_port",
                            label="Mixed port",
                            label_zh="混合端口",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    label="http-port/socks5-port",
                                    label_zh="HTTP/SOCKS5 端口",
                                    field_type="int",
                                    support=_support(
                                        "unsupported",
                                        "No shared mirror. This renderer does not expose a dedicated native mixed-port mapping key.",
                                        "没有共享镜像；当前渲染器没有独立的 mixed-port native key。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY,
                                    label="mixed-port",
                                    label_zh="混合端口",
                                    field_type="int",
                                    placeholder="7890",
                                    placeholder_zh="7890",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="local-port",
                                    label_zh="本地端口",
                                    field_type="int",
                                    support=_support(
                                        "unsupported",
                                        "Mihomo only.",
                                        "仅 Mihomo 可用。",
                                        kind="client_missing",
                                    ),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="allow_lan",
                            label="Allow LAN",
                            label_zh="允许局域网访问",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    label="allow-wifi-access",
                                    label_zh="允许局域网访问",
                                    field_type="bool",
                                    support=_support(
                                        "unsupported",
                                        "No shared mirror. This schema has no client-native allow-lan override slot for Surge.",
                                        "没有共享镜像；当前 schema 在 Surge 侧也没有可直接覆写的 allow-lan 原生配置槽位。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY,
                                    label="allow-lan",
                                    label_zh="允许局域网访问",
                                    field_type="bool",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="allow-lan",
                                    label_zh="允许局域网访问",
                                    field_type="bool",
                                    support=_support(
                                        "unsupported",
                                        "Mihomo only.",
                                        "仅 Mihomo 可用。",
                                        kind="client_missing",
                                    ),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="udp_default",
                            label="UDP default",
                            label_zh="UDP 默认开启",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    label="udp-policy",
                                    label_zh="UDP 策略",
                                    field_type="bool",
                                    support=_support(
                                        "unsupported",
                                        "No shared mirror. This card does not provide a client-native UDP default override key for Surge.",
                                        "没有共享镜像；此卡片没有为 Surge 提供可直接覆写的 UDP 默认值原生配置键。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY,
                                    label="udp-enabled-by-default",
                                    label_zh="默认启用 UDP",
                                    field_type="bool",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="udp",
                                    label_zh="UDP",
                                    field_type="bool",
                                    support=_support(
                                        "unsupported",
                                        "Mihomo only.",
                                        "仅 Mihomo 可用。",
                                        kind="client_missing",
                                    ),
                                ),
                            },
                        ),
                    ],
                },
                {
                    "id": "mihomo-profile-store",
                    "title": "Profile Persistence",
                    "title_i18n": _text("配置持久化", "Profile Persistence"),
                    "description": "Persist group selections and fake-ip cache between updates.",
                    "description_i18n": _text("在更新之间保留分组选择和 fake-ip 缓存。", "Persist group selections and fake-ip cache between updates."),
                    "subfields": [
                        _subfield(
                            subfield_id="store_selected",
                            label="Store selected groups",
                            label_zh="保存已选分组",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    label="policy-group store",
                                    label_zh="策略组持久化",
                                    field_type="bool",
                                    support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing"),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY,
                                    label="profile.store-selected",
                                    label_zh="保存已选分组",
                                    field_type="bool",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="selection cache",
                                    label_zh="选择缓存",
                                    field_type="bool",
                                    support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="store_fake_ip",
                            label="Store fake-ip cache",
                            label_zh="保存 fake-ip 缓存",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    label="fake-ip cache",
                                    label_zh="fake-ip 缓存",
                                    field_type="bool",
                                    support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing"),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY,
                                    label="profile.store-fake-ip",
                                    label_zh="保存 fake-ip 缓存",
                                    field_type="bool",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="fake-ip cache",
                                    label_zh="fake-ip 缓存",
                                    field_type="bool",
                                    support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                    ],
                },
                {
                    "id": "mihomo-control-api",
                    "title": "Control API",
                    "title_i18n": _text("控制 API", "Control API"),
                    "description": "External controller and dashboard settings for Mihomo.",
                    "description_i18n": _text("Mihomo 的外部控制器与面板设置。", "External controller and dashboard settings for Mihomo."),
                    "subfields": [
                        _subfield(
                            subfield_id="external_controller",
                            label="External controller",
                            label_zh="外部控制器",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_HTTP_API_KEY,
                                    label="http-api",
                                    label_zh="HTTP API",
                                    field_type="string",
                                    placeholder="127.0.0.1:6170",
                                    placeholder_zh="127.0.0.1:6170",
                                    support=_support(
                                        "auto_mapped",
                                        "Auto-synced from the shared Mihomo / Surge control API truth.",
                                        "自动从 Mihomo / Surge 共享控制 API 真相同步。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY,
                                    label="external-controller",
                                    label_zh="外部控制器",
                                    field_type="string",
                                    placeholder="127.0.0.1:9090",
                                    placeholder_zh="127.0.0.1:9090",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(
                                    label="control API",
                                    label_zh="控制 API",
                                    field_type="string",
                                    support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="secret",
                            label="Controller secret",
                            label_zh="控制器密钥",
                            source_client="clash",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_HTTP_API_SECRET_KEY,
                                    label="API key",
                                    label_zh="API 密钥",
                                    field_type="string",
                                    placeholder="Leave empty to disable auth",
                                    placeholder_zh="留空表示不启用鉴权",
                                    support=_support(
                                        "auto_mapped",
                                        "Auto-synced from the shared Mihomo / Surge control API truth.",
                                        "自动从 Mihomo / Surge 共享控制 API 真相同步。",
                                    ),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_SECRET_KEY,
                                    label="secret",
                                    label_zh="控制器密钥",
                                    field_type="string",
                                    placeholder="Leave empty to disable",
                                    placeholder_zh="留空表示禁用",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(label="API secret", label_zh="API 密钥", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                            },
                        ),
                        _subfield(
                            subfield_id="external_ui",
                            label="External UI path",
                            label_zh="外部 UI 路径",
                            source_client="clash",
                            clients={
                                "surge": _view(label="dashboard path", label_zh="控制台路径", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY,
                                    label="external-ui",
                                    label_zh="外部 UI 路径",
                                    field_type="string",
                                    placeholder="/path/to/ui",
                                    placeholder_zh="/path/to/ui",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(label="dashboard path", label_zh="控制台路径", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                            },
                        ),
                        _subfield(
                            subfield_id="external_ui_name",
                            label="External UI name",
                            label_zh="外部 UI 名称",
                            source_client="clash",
                            clients={
                                "surge": _view(label="dashboard name", label_zh="控制台名称", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY,
                                    label="external-ui-name",
                                    label_zh="外部 UI 名称",
                                    field_type="string",
                                    placeholder="zashboard",
                                    placeholder_zh="zashboard",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(label="dashboard name", label_zh="控制台名称", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                            },
                        ),
                        _subfield(
                            subfield_id="external_ui_url",
                            label="External UI URL",
                            label_zh="外部 UI URL",
                            source_client="clash",
                            clients={
                                "surge": _view(label="dashboard URL", label_zh="控制台 URL", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY,
                                    label="external-ui-url",
                                    label_zh="外部 UI URL",
                                    field_type="string",
                                    placeholder="https://example.com/ui.zip",
                                    placeholder_zh="https://example.com/ui.zip",
                                    support=_support("supported", "Mihomo native field.", "Mihomo 原生字段。"),
                                ),
                                "shadowrocket": _view(label="dashboard URL", label_zh="控制台 URL", field_type="string", support=_support("unsupported", "Mihomo only.", "仅 Mihomo 可用。", kind="client_missing")),
                            },
                        ),
                    ],
                },
            ],
        },
        {
            "id": "surge-routing",
            "title": "Surge Routing & Rewrite",
            "title_i18n": _text("Surge 路由与重写", "Surge Routing & Rewrite"),
            "description": "Surge-specific features: URL rewrite, MITM, skip-proxy, and more.",
            "description_i18n": _text(
                "Surge 专属功能，如 URL 重写、MITM、跳过代理等。",
                "Surge-specific features: URL rewrite, MITM, skip-proxy, and more.",
            ),
            "capabilities": [
                {
                    "id": "surge-runtime",
                    "title": "Surge Runtime",
                    "title_i18n": _text("Surge 运行时", "Surge Runtime"),
                    "description": "Surge native runtime and policy group settings.",
                    "description_i18n": _text("Surge 原生运行时与策略组设置。", "Surge native runtime and policy group settings."),
                    "subfields": [
                        _subfield(
                            subfield_id="loglevel",
                            label="Log level",
                            label_zh="日志级别",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_LOGLEVEL_KEY,
                                    label="loglevel",
                                    label_zh="日志级别",
                                    field_type="select",
                                    options=LAZYCAT_PROFILE_LOG_LEVEL_OPTIONS[LAZYCAT_PROFILE_SURGE_LOGLEVEL_KEY],
                                    placeholder="notify",
                                    placeholder_zh="notify",
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(
                                    key=LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY,
                                    label="log-level",
                                    label_zh="日志级别",
                                    field_type="string",
                                    support=_support("unsupported", "Surge only. Mihomo has its own log-level setting above.", "仅 Surge 可用。Mihomo 有独立的日志级别设置。"),
                                ),
                                "shadowrocket": _view(label="loglevel", label_zh="日志级别", field_type="string", support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing")),
                            },
                        ),
                        _subfield(
                            subfield_id="group_timeout",
                            label="Proxy group timeout",
                            label_zh="策略组超时",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TIMEOUT_KEY,
                                    label="group-timeout",
                                    label_zh="策略组超时",
                                    field_type="int",
                                    placeholder="5",
                                    placeholder_zh="5",
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(label="url-test timeout", label_zh="URL 测试超时", field_type="int", support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing")),
                                "shadowrocket": _view(label="group timeout", label_zh="策略组超时", field_type="int", support=_support("unsupported", "Surge only.", "仅 Surge 可用。")),
                            },
                        ),
                        _subfield(
                            subfield_id="group_tolerance",
                            label="Proxy group tolerance",
                            label_zh="策略组容差",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TOLERANCE_KEY,
                                    label="group-tolerance",
                                    label_zh="策略组容差",
                                    field_type="int",
                                    placeholder="50",
                                    placeholder_zh="50",
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(label="url-test tolerance", label_zh="URL 测试容差", field_type="int", support=_support("unsupported", "Surge only.", "仅 Surge 可用。")),
                                "shadowrocket": _view(label="group tolerance", label_zh="策略组容差", field_type="int", support=_support("unsupported", "Surge only.", "仅 Surge 可用。")),
                            },
                        ),
                        _subfield(
                            subfield_id="block_quic",
                            label="Block QUIC",
                            label_zh="阻止 QUIC",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_BLOCK_QUIC_KEY,
                                    label="block-quic",
                                    label_zh="阻止 QUIC",
                                    field_type="string",
                                    placeholder="all-proxy",
                                    placeholder_zh="all-proxy",
                                    support=_support(
                                        "supported",
                                        "Surge native field. Keep it explicit when QUIC routing behavior matters.",
                                        "Surge 原生字段；当 QUIC 路径会影响分流时，应显式配置。",
                                    ),
                                ),
                                "clash": _view(
                                    label="block-quic",
                                    label_zh="阻止 QUIC",
                                    field_type="string",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                                "shadowrocket": _view(
                                    label="block-quic",
                                    label_zh="阻止 QUIC",
                                    field_type="string",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="http_api_tls",
                            label="HTTP API TLS",
                            label_zh="HTTP API TLS",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_HTTP_API_TLS_KEY,
                                    label="http-api-tls",
                                    label_zh="HTTP API TLS",
                                    field_type="bool",
                                    support=_support(
                                        "supported",
                                        "Surge native field. Effective when http-api is configured.",
                                        "Surge 原生字段；仅在配置了 http-api 时生效。",
                                    ),
                                ),
                                "clash": _view(
                                    label="http-api-tls",
                                    label_zh="HTTP API TLS",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                                "shadowrocket": _view(
                                    label="http-api-tls",
                                    label_zh="HTTP API TLS",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="http_api_web_dashboard",
                            label="HTTP API Web Dashboard",
                            label_zh="HTTP API Web 控制台",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_HTTP_API_WEB_DASHBOARD_KEY,
                                    label="http-api-web-dashboard",
                                    label_zh="HTTP API Web 控制台",
                                    field_type="bool",
                                    support=_support(
                                        "supported",
                                        "Surge native field. Effective when http-api is configured.",
                                        "Surge 原生字段；仅在配置了 http-api 时生效。",
                                    ),
                                ),
                                "clash": _view(
                                    label="http-api-web-dashboard",
                                    label_zh="HTTP API Web 控制台",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                                "shadowrocket": _view(
                                    label="http-api-web-dashboard",
                                    label_zh="HTTP API Web 控制台",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                    ],
                },
                {
                    "id": "skip-proxy",
                    "title": "Skip Proxy",
                    "title_i18n": _text("跳过代理", "Skip Proxy"),
                    "description": "Shared domain / host bypass intent. IP/CIDR bypass belongs to Excluded Routes.",
                    "description_i18n": _text(
                        "共享的域名 / 主机绕行意图；IP/CIDR 绕行应编辑到 Excluded Routes。",
                        "Shared domain / host bypass intent. IP/CIDR bypass belongs to Excluded Routes.",
                    ),
                    "subfields": [
                        _subfield(
                            subfield_id="patterns",
                            label="Bypass patterns",
                            label_zh="绕过模式",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY,
                                    label="skip-proxy",
                                    label_zh="跳过代理",
                                    field_type="list",
                                    rows=4,
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(
                                    label="rule bypass",
                                    label_zh="规则绕过",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "auto_mapped",
                                        "Adapted from the shared domain / host bypass truth: domains and hosts become DIRECT rules, and only add dns.fake-ip-filter entries when fake-ip mode is enabled.",
                                        "自适应转换自共享的域名 / 主机绕行真相：域名与主机会生成 DIRECT 规则；只有在 fake-ip 模式下才额外进入 dns.fake-ip-filter。",
                                    ),
                                    editing_mode_override="adapted",
                                    adapted_hint="Mihomo has no native skip-proxy field. This shared domain / host intent is rendered as DIRECT rules by default, and only adds dns.fake-ip-filter entries when fake-ip mode is enabled. IP/CIDR bypass is reviewed separately in Excluded Routes.",
                                    adapted_hint_zh="Mihomo 没有原生 skip-proxy 字段。这里的共享域名 / 主机绕行意图会默认渲染成 DIRECT 规则；只有在启用 fake-ip 模式时才额外进入 dns.fake-ip-filter。IP/CIDR 绕行会单独走 Excluded Routes。",
                                    adapted_targets=[
                                        {"section": "dns.fake-ip-filter (fake-ip only)", "section_zh": "DNS fake-ip 过滤（仅 fake-ip）", "kind": "domain"},
                                        {"section": "rules (DIRECT)", "section_zh": "规则 (DIRECT)", "kind": "domain"},
                                    ],
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY,
                                    label="skip-proxy",
                                    label_zh="跳过代理",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "supported",
                                        "Supported as part of the shared domain / host bypass truth. Evidence source: user real-device validation.",
                                        "已纳入共享的域名 / 主机绕行真相。证据来源：用户实机验证。",
                                    ),
                                    syntax_hints=[{
                                        "title": "Syntax",
                                        "title_i18n": _text("语法说明", "Syntax"),
                                        "body": "Keep one domain or hostname pattern per line here. IP/CIDR bypass is reviewed from Excluded Routes so the shared truth stays aligned across clients.",
                                        "body_i18n": _text(
                                            "这里每行只保留一个域名或主机模式。IP/CIDR 绕行统一改到 Excluded Routes 审核和编辑，保证跨端共享真相保持一致。",
                                            "Keep one domain or hostname pattern per line here. IP/CIDR bypass is reviewed from Excluded Routes so the shared truth stays aligned across clients.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                            },
                        )
                    ],
                },
                {
                    "id": "url-rewrite",
                    "title": "URL Rewrite",
                    "title_i18n": _text("URL 重写", "URL Rewrite"),
                    "description": "Rewrite HTTP requests using client-native syntax.",
                    "description_i18n": _text("使用客户端原生语法重写 HTTP 请求。", "Rewrite HTTP requests using client-native syntax."),
                    "subfields": [
                        _subfield(
                            subfield_id="rules",
                            label="Rewrite rules",
                            label_zh="重写规则",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_URL_REWRITE_KEY,
                                    label="URL Rewrite",
                                    label_zh="URL 重写",
                                    field_type="list",
                                    rows=5,
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(
                                    label="URL Rewrite",
                                    label_zh="URL 重写",
                                    field_type="list",
                                    rows=5,
                                    support=_support(
                                        "unsupported",
                                        "Mihomo kernel has no Surge-style MITM / URL Rewrite / Script packet-editing capability. URL rewriting requires HTTPS decryption + HTTP omitted output: interception without reliable data deliverys that Mihomo's architecture does not support. Only rule-level REJECT blocking is available.",
                                        "Mihomo 内核没有 Surge 式 MITM / URL Rewrite / Script 改包能力。URL 重写需要 HTTPS 解密 + HTTP 拦截层，Mihomo 架构不支持。只能做规则级 REJECT 阻断。",
                                        kind="client_missing",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY,
                                    label="URL Rewrite",
                                    label_zh="URL 重写",
                                    field_type="list",
                                    rows=5,
                                    support=_support(
                                        "supported",
                                        "Shadowrocket 2.2.93 runs URL Rewrite immediately after download; HTTPS requires a trusted MITM CA.",
                                        "Shadowrocket 2.2.93 下载后直接激活 URL Rewrite；HTTPS 需要安装并完全信任 MITM 证书。",
                                        diagnostic_codes=["shadowrocket-rewrite-activation-may-be-required"],
                                    ),
                                    editing_mode_override="standalone",
                                    syntax_hints=[{
                                        "title": "Syntax",
                                        "title_i18n": _text("语法说明", "Syntax"),
                                        "body": "Stable confirmed patterns: regex replacement 302 and regex _ REJECT-DICT. Explicit host:8443 is also verified.",
                                        "body_i18n": _text(
                                            "当前已确认的稳定形态是 regex replacement 302 与 regex _ REJECT-DICT；显式 host:8443 也已验证。",
                                            "Stable confirmed patterns: regex replacement 302 and regex _ REJECT-DICT. Explicit host:8443 is also verified.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                            },
                        )
                    ],
                },
                {
                    "id": "mitm-hostname",
                    "title": "MITM Hostname",
                    "title_i18n": _text("MITM 主机名", "MITM Hostname"),
                    "description": "Hostname allowlist/denylist for MITM interception.",
                    "description_i18n": _text("用于 MITM 拦截的主机名白名单/黑名单。", "Hostname allowlist/denylist for MITM interception."),
                    "subfields": [
                        _subfield(
                            subfield_id="hostname",
                            label="Hostname list",
                            label_zh="主机名列表",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_MITM_HOSTNAME_KEY,
                                    label="hostname",
                                    label_zh="主机名",
                                    field_type="list",
                                    rows=4,
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(
                                    label="mitm.hostname",
                                    label_zh="MITM 主机名",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "unsupported",
                                        "Mihomo's skip-cert-verify is only for TLS proxy connections, not Surge/Shadowrocket's HTTPS decryption semantics. Mihomo cannot intercept and modify encrypted traffic.",
                                        "Mihomo 的 skip-cert-verify 仅用于 TLS 代理连接，不是 Surge/Shadowrocket 的 HTTPS 解密语义。Mihomo 无法拦截和修改加密流量。",
                                        kind="client_missing",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY,
                                    label="hostname",
                                    label_zh="主机名",
                                    field_type="list",
                                    rows=4,
                                    support=_support(
                                        "supported",
                                        "Shadowrocket 2.2.93 supports explicit host:8443. Install and fully trust a CA, then enable HTTPS decryption, save and restart VPN.",
                                        "Shadowrocket 2.2.93 支持显式 host:8443；须安装证书并开启系统完全信任，再启用 HTTPS 解密、保存并重启 VPN。",
                                        diagnostic_codes=["shadowrocket-mitm-certificate-required"],
                                    ),
                                    editing_mode_override="standalone",
                                    syntax_hints=[{
                                        "title": "Syntax",
                                        "title_i18n": _text("语法说明", "Syntax"),
                                        "body": "Subscription rendering emits [MITM] with enable = true and hostname = domain1, domain2. Supports * wildcard and - exclusion prefixes; first match wins.",
                                        "body_i18n": _text(
                                            "订阅渲染会输出 [MITM]，并补上 enable = true 与 hostname = domain1, domain2。支持 * 通配符和 - 排除前缀；Host List 先匹配先生效。",
                                            "Subscription rendering emits [MITM] with enable = true and hostname = domain1, domain2. Supports * wildcard and - exclusion prefixes; first match wins.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="skip_cert_verify",
                            label="Skip server cert verify",
                            label_zh="跳过服务端证书校验",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_MITM_SKIP_SERVER_CERT_VERIFY_KEY,
                                    label="skip-server-cert-verify",
                                    label_zh="跳过服务端证书校验",
                                    field_type="bool",
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(
                                    label="skip-cert-verify",
                                    label_zh="跳过证书校验",
                                    field_type="bool",
                                    support=_support(
                                        "unsupported",
                                        "Mihomo's skip-cert-verify is for TLS proxy connections only, not for MITM HTTPS decryption. Mihomo cannot intercept encrypted traffic.",
                                        "Mihomo 的 skip-cert-verify 仅适用于 TLS 代理连接，不是 MITM HTTPS 解密。Mihomo 无法拦截加密流量。",
                                        kind="client_missing",
                                    ),
                                ),
                                "shadowrocket": _view(label="skip-server-cert-verify", label_zh="跳过服务端证书校验", field_type="bool", support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing")),
                            },
                        ),
                        _subfield(
                            subfield_id="h2",
                            label="MITM HTTP/2",
                            label_zh="MITM HTTP/2",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_MITM_H2_KEY,
                                    label="h2",
                                    label_zh="HTTP/2",
                                    field_type="bool",
                                    support=_support(
                                        "supported",
                                        "Surge native field. Minimum version requirement: Surge iOS 5.17.1 / macOS 6.0.0 in this product baseline.",
                                        "Surge 原生字段。当前产品基线最低版本要求：Surge iOS 5.17.1 / macOS 6.0.0。",
                                    ),
                                    syntax_hints=[{
                                        "title": "Version gate",
                                        "title_i18n": _text("版本门槛", "Version gate"),
                                        "body": "Current product baseline: Surge iOS 5.17.1 / macOS 6.0.0.",
                                        "body_i18n": _text(
                                            "当前产品基线：Surge iOS 5.17.1 / macOS 6.0.0。",
                                            "Current product baseline: Surge iOS 5.17.1 / macOS 6.0.0.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                                "clash": _view(
                                    label="h2",
                                    label_zh="HTTP/2",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                                "shadowrocket": _view(
                                    label="h2",
                                    label_zh="HTTP/2",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="tcp_connection",
                            label="MITM TCP Connection",
                            label_zh="MITM TCP 连接",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_MITM_TCP_CONNECTION_KEY,
                                    label="tcp-connection",
                                    label_zh="TCP 连接",
                                    field_type="bool",
                                    support=_support(
                                        "supported",
                                        "Surge native field. Minimum version requirement: Surge iOS 5.17.1 / macOS 6.0.0 in this product baseline.",
                                        "Surge 原生字段。当前产品基线最低版本要求：Surge iOS 5.17.1 / macOS 6.0.0。",
                                    ),
                                    syntax_hints=[{
                                        "title": "Version gate",
                                        "title_i18n": _text("版本门槛", "Version gate"),
                                        "body": "Current product baseline: Surge iOS 5.17.1 / macOS 6.0.0.",
                                        "body_i18n": _text(
                                            "当前产品基线：Surge iOS 5.17.1 / macOS 6.0.0。",
                                            "Current product baseline: Surge iOS 5.17.1 / macOS 6.0.0.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                                "clash": _view(
                                    label="tcp-connection",
                                    label_zh="TCP 连接",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                                "shadowrocket": _view(
                                    label="tcp-connection",
                                    label_zh="TCP 连接",
                                    field_type="bool",
                                    support=_support("unsupported", "Surge only.", "仅 Surge 可用。", kind="client_missing"),
                                ),
                            },
                        ),
                    ],
                },
                {
                    "id": "surge-http-pipeline",
                    "title": "Surge HTTP Pipeline",
                    "title_i18n": _text("Surge HTTP 管线", "Surge HTTP Pipeline"),
                    "description": "Surge-only HTTP processing rules.",
                    "description_i18n": _text("Surge 专属 HTTP 处理规则。", "Surge-only HTTP processing rules."),
                    "subfields": [
                        _subfield(
                            subfield_id="map_local",
                            label="Map Local",
                            label_zh="本地映射",
                            source_client="surge",
                            clients={
                                "surge": _view(
                                    key=LAZYCAT_PROFILE_SURGE_MAP_LOCAL_KEY,
                                    label="Map Local",
                                    label_zh="本地映射",
                                    field_type="list",
                                    rows=6,
                                    support=_support("supported", "Surge native field.", "Surge 原生字段。"),
                                ),
                                "clash": _view(
                                    label="Map Local",
                                    label_zh="本地映射",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "unsupported",
                                        "Mihomo cannot equivalently implement Map Local (returning placeholder resources). If you only need blocking, downgrade to rule-level REJECT.",
                                        "Mihomo 无法等价实现 Map Local（返回占位资源）。如只需拦截，可降级为规则级 REJECT。",
                                        kind="client_missing",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY,
                                    label="Map Local",
                                    label_zh="本地映射",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "downgraded",
                                        "Settings retained, output omitted — tested Map Local forms intercept but fail to deliver. Use a response Script.",
                                        "设置保留但不再下发：已测 Map Local 只能拦截、无法交付。请改用响应 Script。",
                                        diagnostic_codes=[
                                            "shadowrocket-map-local-intercept-only",
                                            "shadowrocket-map-local-inline-data-unreliable",
                                        ],
                                    ),
                                    editing_mode_override="standalone",
                                    syntax_hints=[{
                                        "title": "Syntax",
                                        "title_i18n": _text("语法说明", "Syntax"),
                                        "body": 'Map Local values stay saved but are omitted from generated profiles with a warning; use response Script.',
                                        "body_i18n": _text(
                                            "Map Local 设置仍会保存，但生成配置省略此段并告警；响应体处理改用 Script。",
                                            "Map Local values stay saved but are omitted from generated profiles with a warning; use response Script.",
                                        ),
                                        "status": "downgraded",
                                    }],
                                ),
                            },
                        )
                    ],
                },
                {
                    "id": "script",
                    "title": "Script",
                    "title_i18n": _text("脚本", "Script"),
                    "description": "Client-native request/response scripts for HTTP interception.",
                    "description_i18n": _text("客户端原生的 HTTP 请求/响应脚本能力。", "Client-native request/response scripts for HTTP interception."),
                    "subfields": [
                        _subfield(
                            subfield_id="request",
                            label="Request scripts",
                            label_zh="请求脚本",
                            source_client="shadowrocket",
                            clients={
                                "surge": _view(
                                    label="Script",
                                    label_zh="脚本",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "unsupported",
                                        "Surge is not expanded in this product for Script editing yet.",
                                        "当前产品暂未为 Surge 扩展 Script 编辑入口。",
                                        kind="client_missing",
                                    ),
                                ),
                                "clash": _view(
                                    label="Script",
                                    label_zh="脚本",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "unsupported",
                                        "Mihomo kernel has no Surge/Shadowrocket-style HTTP interception script layer.",
                                        "Mihomo 内核没有 Surge/Shadowrocket 这种 HTTP 拦截脚本层。",
                                        kind="client_missing",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY,
                                    label="Request Script",
                                    label_zh="请求脚本",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "supported",
                                        "Supported — Shadowrocket request scripts are the preferred way to inject request-side HTTP behavior once MITM is active.",
                                        "已支持：在 MITM 可用后，Shadowrocket 请求脚本是注入请求侧 HTTP 行为的首选方式。",
                                    ),
                                    editing_mode_override="standalone",
                                    syntax_hints=[{
                                        "title": "Syntax",
                                        "title_i18n": _text("语法说明", "Syntax"),
                                        "body": "Each line is emitted verbatim inside [Script]. Use type=http-request when editing request-side behavior.",
                                        "body_i18n": _text(
                                            "每一行都会原样输出到 [Script]；需要修改请求侧行为时使用 type=http-request。",
                                            "Each line is emitted verbatim inside [Script]. Use type=http-request when editing request-side behavior.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                            },
                        ),
                        _subfield(
                            subfield_id="response",
                            label="Response scripts",
                            label_zh="响应脚本",
                            source_client="shadowrocket",
                            clients={
                                "surge": _view(
                                    label="Script",
                                    label_zh="脚本",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "unsupported",
                                        "Surge is not expanded in this product for Script editing yet.",
                                        "当前产品暂未为 Surge 扩展 Script 编辑入口。",
                                        kind="client_missing",
                                    ),
                                ),
                                "clash": _view(
                                    label="Script",
                                    label_zh="脚本",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "unsupported",
                                        "Mihomo kernel has no Surge/Shadowrocket-style HTTP interception script layer.",
                                        "Mihomo 内核没有 Surge/Shadowrocket 这种 HTTP 拦截脚本层。",
                                        kind="client_missing",
                                    ),
                                ),
                                "shadowrocket": _view(
                                    key=LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY,
                                    label="Response Script",
                                    label_zh="响应脚本",
                                    field_type="list",
                                    rows=6,
                                    support=_support(
                                        "supported",
                                        "Supported — use response scripts as the stable replacement for Body Rewrite and Map Local response mocking.",
                                        "已支持：响应脚本是 Body Rewrite 与 Map Local 响应 mock 的稳定替代方案。",
                                    ),
                                    editing_mode_override="standalone",
                                    syntax_hints=[{
                                        "title": "Syntax",
                                        "title_i18n": _text("语法说明", "Syntax"),
                                        "body": "Each line is emitted verbatim inside [Script]. Prefer type=http-response,requires-body=1 for response body rewriting or mock payload delivery.",
                                        "body_i18n": _text(
                                            "每一行都会原样输出到 [Script]；如需改写响应体或返回 mock 内容，优先使用 type=http-response,requires-body=1。",
                                            "Each line is emitted verbatim inside [Script]. Prefer type=http-response,requires-body=1 for response body rewriting or mock payload delivery.",
                                        ),
                                        "status": "supported",
                                    }],
                                ),
                            },
                        ),
                    ],
                },
            ],
        },
    ]


PROFILE_CAPABILITY_GROUPS = _all_capabilities()


def profile_capabilities_payload() -> dict[str, Any]:
    used_keys = {
        view["key"]
        for group in PROFILE_CAPABILITY_GROUPS
        for capability in group["capabilities"]
        for subfield in capability["subfields"]
        for view in subfield["clients"].values()
        if view.get("key")
    }
    return {
        "groups": PROFILE_CAPABILITY_GROUPS,
        "expert_field_keys": [key for key in LAZYCAT_PROFILE_SETTING_KEYS if key not in used_keys],
    }


def profile_capabilities_to_settings(
    capabilities: Mapping[str, object] | None,
    *,
    base_settings: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    normalized = normalize_lazycat_profile_settings(base_settings or {})
    if not isinstance(capabilities, Mapping):
        return normalized

    for group in PROFILE_CAPABILITY_GROUPS:
        for capability in group["capabilities"]:
            raw_capability = capabilities.get(capability["id"])
            if not isinstance(raw_capability, Mapping):
                continue
            for subfield in capability["subfields"]:
                if subfield["id"] not in raw_capability:
                    continue
                value = raw_capability[subfield["id"]]
                source_client = str(subfield["source_client"])
                clients = dict(subfield["clients"])
                source_view = dict(clients.get(source_client) or {})
                source_key = str(source_view.get("key") or "").strip()
                if source_key:
                    validate_lazycat_profile_setting_value(source_key, value)
                    normalized[source_key] = value
                for client_name, view in clients.items():
                    if client_name == source_client:
                        continue
                    view_key = str(view.get("key") or "").strip()
                    if view_key and view.get("editing_mode") == "shared":
                        validate_lazycat_profile_setting_value(view_key, value)
                        normalized[view_key] = value
    return normalize_lazycat_profile_settings(normalized)


def settings_to_profile_capabilities(
    settings: Mapping[str, object] | None,
) -> dict[str, dict[str, object]]:
    normalized = normalize_lazycat_profile_settings(settings or {})
    defaults = normalize_lazycat_profile_settings({})
    payload: dict[str, dict[str, object]] = {}
    for group in PROFILE_CAPABILITY_GROUPS:
        for capability in group["capabilities"]:
            subfield_values: dict[str, object] = {}
            for subfield in capability["subfields"]:
                source_client = str(subfield["source_client"])
                source_view = dict(subfield["clients"].get(source_client) or {})
                source_key = str(source_view.get("key") or "").strip()
                if not source_key:
                    continue
                value = normalized.get(source_key)
                if value == defaults.get(source_key):
                    shared_keys: list[str] = []
                    for view in subfield["clients"].values():
                        key = str(view.get("key") or "").strip()
                        if view.get("editing_mode") == "shared" and key and key not in shared_keys:
                            shared_keys.append(key)
                    for key in shared_keys:
                        candidate = normalized.get(key)
                        if candidate != defaults.get(key):
                            value = candidate
                            break
                subfield_values[subfield["id"]] = value
            payload[capability["id"]] = subfield_values
    return payload
