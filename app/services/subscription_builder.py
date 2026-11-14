from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
import base64
import hashlib
import ipaddress
import json
import re
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlencode, urlparse

import yaml

from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BUSINESS_GROUP_MODE_STANDARD,
    CONTRACT_AD_BLOCK,
    CONTRACT_BULK,
    CONTRACT_CHAIN_HOME,
    CONTRACT_DIRECT,
    CONTRACT_FAILURE_DEGRADE,
    CONTRACT_FAILURE_DIRECT,
    CONTRACT_FAILURE_INTERRUPT,
    CONTRACT_HQ_PREMIUM,
    CONTRACT_HQ_STANDARD,
    CONTRACT_MEDIUM,
    CONTRACT_STRATEGY_FAILOVER,
    CONTRACT_STRATEGY_LOAD_BALANCE,
    ROUTE_ACTION_DIRECT,
    ROUTE_ACTION_PROXY,
    ROUTE_ACTION_REJECT,
    ROUTE_DIRECT_ACTION,
    ROUTE_REJECT_ACTION,
    DEVICE_STRATEGY_PRESET_BALANCED,
    DEVICE_STRATEGY_PRESET_CHEAP,
    DEVICE_STRATEGY_PRESET_MOBILE,
    DEVICE_STRATEGY_PRESET_REALTIME,
    DEVICE_STRATEGY_PRESET_STREAMING,
    DEVICE_STRATEGY_PRESETS,
    BusinessGroup,
    contract_display_name,
    contract_legacy_group,
    ExternalProxyProgramTemplate,
    GeneralProfile,
    MacOverlayTemplate,
    NodeRecord,
    PolicyIR,
    PolicyRuleEntry,
    QUALITY_BULK,
    QUALITY_CHAIN_HOME,
    QUALITY_GROUPS,
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
    QUALITY_REJECT,
    RenderWarning,
    ProcessRuleTemplate,
    RouteContract,
    ServiceCatalogEntry,
    SurgeProfileArtifacts,
    SURGE_PROCESS_RULE_TYPES,
    normalize_route_action,
    normalize_contract_id,
)
from app.services.render_environment import capture_local_host_aliases as _local_host_target_aliases
from app.services.configuration_intent import (
    ConfigurationIntent,
    IntentProjection,
    count_strict_contracts_rendered_as_fallback,
    derive_configuration_intent,
    project_configuration_intent,
    MIHOMO_CIDR_RULE_TYPES as _CLASH_CIDR_RULE_TYPES,
    routing_intent_diagnostics,
)
from app.services.lazycat_profile import (
    LAZYCAT_DOMAIN_SUFFIXES,
    LAZYCAT_DEFAULT_PROFILE_SETTINGS,
    LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY,
    LAZYCAT_PROFILE_CLASH_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY,
    LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY,
    LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY,
    LAZYCAT_PROFILE_CLASH_HOST_RECORDS_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY,
    LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY,
    LAZYCAT_PROFILE_CLASH_FAKE_IP_FILTER_KEY,
    LAZYCAT_PROFILE_CLASH_IPV6_KEY,
    LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY,
    LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY,
    LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY,
    LAZYCAT_PROFILE_CLASH_SECRET_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_ENABLE_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DOMAIN_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_HTTP_PORTS_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_OVERRIDE_DESTINATION_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_PARSE_PURE_IP_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_QUIC_PORTS_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_SKIP_DOMAIN_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_SKIP_DST_ADDRESS_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_SKIP_SRC_ADDRESS_KEY,
    LAZYCAT_PROFILE_CLASH_SNIFFER_TLS_PORTS_KEY,
    LAZYCAT_PROFILE_CLASH_TCP_CONCURRENT_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_AUTO_DETECT_INTERFACE_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_AUTO_ROUTE_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_ENABLE_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_EXCLUDE_PACKAGE_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_EXCLUDE_UID_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_INCLUDE_PACKAGE_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_INCLUDE_ROUTES_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_INCLUDE_UID_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_STACK_KEY,
    LAZYCAT_PROFILE_CLASH_TUN_STRICT_ROUTE_KEY,
    LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_HOST_RECORDS_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY,
    LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY,
    LAZYCAT_PROFILE_SURGE_ALWAYS_REAL_IP_KEY,
    LAZYCAT_PROFILE_SURGE_BLOCK_QUIC_KEY,
    LAZYCAT_PROFILE_SURGE_BODY_REWRITE_KEY,
    LAZYCAT_PROFILE_SURGE_DNS_SERVER_KEY,
    LAZYCAT_PROFILE_SURGE_ENCRYPTED_DNS_FOLLOW_OUTBOUND_MODE_KEY,
    LAZYCAT_PROFILE_SURGE_ENCRYPTED_DNS_SERVER_KEY,
    LAZYCAT_PROFILE_SURGE_HEADER_REWRITE_KEY,
    LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_SECRET_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_TLS_KEY,
    LAZYCAT_PROFILE_SURGE_HTTP_API_WEB_DASHBOARD_KEY,
    LAZYCAT_PROFILE_SURGE_IPV6_KEY,
    LAZYCAT_PROFILE_SURGE_JQ_BODY_REWRITE_KEY,
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
)
from app.services.skip_proxy_decomposer import decompose_skip_proxy
from app.services.subscription_contracts import (
    CLASH_PROVIDER_GROUP_BY_KEY,
    CLASH_PROVIDER_KEY_BY_GROUP,
    CLASH_UDP_SUPPORTED_PROTOCOLS,
)
from app.services.subscription_country_rules import (
    OTHER_COUNTRY as _OTHER_COUNTRY,
    country_group_name as _country_group_name,
    country_regex as _country_regex,
    country_routing_plan as _country_routing_plan,
    detect_node_country as _detect_node_country,
    international_group_name as _international_group_name,
    known_country_regex as _known_country_regex,
)

_NATIVE_RULE_TARGETS = {
    "clash": frozenset({"DIRECT", "REJECT", "REJECT-DROP"}),
    "surge": frozenset({"DIRECT", "REJECT", "REJECT-DROP", "REJECT-NO-DROP", "REJECT-TINYGIF"}),
    "shadowrocket": frozenset({
        "DIRECT", "REJECT", "REJECT-DROP", "REJECT-NO-DROP", "REJECT-TINYGIF",
        "REJECT-DICT", "REJECT-ARRAY", "REJECT-200", "REJECT-IMG", "REJECT-VIDEO",
    }),
}


def _is_native_rule_target(target: object, *, client: str) -> bool:
    return str(target or "").strip() in _NATIVE_RULE_TARGETS[client]


_RESERVED_PROXY_NAMES = set(QUALITY_GROUPS) | set(_NATIVE_RULE_TARGETS["shadowrocket"]) | {
    "直连",
    "广告拦截",
}
_SR_USERNAME_PREFIX_RE = re.compile(r"^(?:username|user|账号)\s*[:=]\s*(.+)$", re.I)
_SR_PASSWORD_PREFIX_RE = re.compile(r"^(?:password|pass|密码)\s*[:=]\s*(.+)$", re.I)
_DISPLAY_NAME_SUFFIX_RE = re.compile(
    r"\.(?:ya?ml|conf|txt|json|list|ini|cfg|profile)$",
    re.I,
)


def _safe_name(name: str) -> str:
    return str(name or "").replace(",", "-").strip() or "Unnamed"


def build_subscription_display_name(device_name: str) -> str:
    text = str(device_name or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = _DISPLAY_NAME_SUFFIX_RE.sub("", text).strip()
    if not text:
        return "SubHub"
    return f"SubHub for {text}"


def build_shadowrocket_subscription_name(device_name: str) -> str:
    return build_subscription_display_name(device_name)


def build_subscription_download_name(device_name: str) -> str:
    return build_subscription_display_name(device_name)


def _sr_normalize_credential(raw: str, *, is_password: bool) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    pattern = _SR_PASSWORD_PREFIX_RE if is_password else _SR_USERNAME_PREFIX_RE
    match = pattern.match(text)
    if match:
        return str(match.group(1) or "").strip()
    return text


def _uniqueify_names(names: list[str], reserved: set[str], *, case_insensitive: bool = False) -> list[str]:
    key = str.casefold if case_insensitive else str
    used = {key(name) for name in reserved}
    output: list[str] = []
    for raw in names:
        base = str(raw or "").strip() or "Unnamed"
        candidate = base
        if key(candidate) in used:
            n = 2
            candidate = f"{base} ({n})"
            while key(candidate) in used:
                n += 1
                candidate = f"{base} ({n})"
        used.add(key(candidate))
        output.append(candidate)
    return output


def _first_raw(raw: dict[str, Any], keys: tuple[str, ...], fallback: str = "") -> str:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return fallback


def _first_raw_bool(raw: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return None


def _first_raw_list(raw: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            output: list[str] = []
            for item in value:
                text = str(item or "").strip()
                if text:
                    output.append(text)
            if output:
                return output
            continue
        text = str(value).strip()
        if not text:
            continue
        if "," in text:
            output = [part.strip() for part in text.split(",") if part.strip()]
            if output:
                return output
        if "|" in text:
            output = [part.strip() for part in text.split("|") if part.strip()]
            if output:
                return output
        return [text]
    return []


def _first_raw_mapping(raw: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        output: dict[str, Any] = {}
        for item_key, item_value in value.items():
            clean_key = str(item_key or "").strip()
            if not clean_key or item_value in (None, "", [], {}):
                continue
            output[clean_key] = item_value
        if output:
            return output
    return {}


def _first_raw_int(raw: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            return int(str(value).strip())
        except Exception:
            continue
    return None


def _resolve_tuic_identity(raw: dict[str, Any], node: NodeRecord) -> tuple[dict[str, Any] | None, str]:
    token = _first_raw(raw, ("token",))
    uuid = _first_raw(raw, ("uuid", "id", "userId", "userid"), node.username)
    password = _first_raw(raw, ("password",), node.password)
    version = _first_raw_int(raw, ("tuic_version", "version"))
    reduce_rtt = _first_raw_bool(raw, ("reduce_rtt", "reduce-rtt"))

    if version not in {4, 5}:
        if token and not uuid and not password:
            version = 4
        elif not token and uuid and password:
            version = 5
        else:
            version = 0

    if token and (uuid or password):
        return None, "mixed tuic v4/v5 credentials"
    if version == 4:
        if not token:
            return None, "missing tuic token"
        return {"version": 4, "token": token, "reduce-rtt": reduce_rtt}, ""
    if version == 5:
        if not uuid or not password:
            return None, "missing tuic uuid/password"
        return {
            "version": 5,
            "uuid": uuid,
            "password": password,
            "reduce-rtt": reduce_rtt,
        }, ""
    if token:
        return {"version": 4, "token": token, "reduce-rtt": reduce_rtt}, ""
    if uuid and password:
        return {
            "version": 5,
            "uuid": uuid,
            "password": password,
            "reduce-rtt": reduce_rtt,
        }, ""
    return None, "invalid tuic credentials"


def derive_protocol_diagnostics(
    nodes: list[NodeRecord],
    skipped: list[str],
    *,
    target: str,
) -> list[RenderWarning]:
    skipped_names = {str(item or "").strip() for item in skipped if str(item or "").strip()}
    diagnostics: list[RenderWarning] = []
    for node in nodes:
        name = str(node.name or "").strip()
        if not name:
            continue
        protocol = str(node.protocol or "").strip().lower()
        raw = node.raw or {}
        is_skipped = name in skipped_names
        if target == "shadowrocket" and protocol == "wireguard":
            ip, ipv6, _ = _wireguard_addresses(raw)
            if is_skipped:
                diagnostics.append(RenderWarning(code="shadowrocket-wireguard-refused", message=f"{name}: WireGuard requires source keys, address and DNS", target=name, severity="warning", bucket="refused"))
            elif ip and ipv6:
                diagnostics.append(RenderWarning(code="shadowrocket-wireguard-family-omitted", message=f"{name}: verified inline syntax carries one IP; IPv4 selected, IPv6 address omitted", target=name, severity="warning", bucket="downgraded"))
        if protocol == "wireguard":
            _, _, dropped = _wireguard_addresses(raw)
            if dropped:
                diagnostics.append(RenderWarning(code=f"{target}-wireguard-addresses-dropped", message=f"{name}: only the first address per family is rendered; extra/invalid addresses omitted", target=name, severity="warning", bucket="downgraded"))
        if target == "shadowrocket" and _is_chain_home_node(node):
            diagnostics.append(RenderWarning(code="shadowrocket-forwarding-proxy-pending-validation", message=f"{name}: forwarding-proxy is unverified; if ignored the rear residential proxy may be contacted directly", target=name, severity="warning", bucket="pending_validation"))
        if target == "shadowrocket" and not is_skipped:
            fields = [key for key in ("alpn", "client_fingerprint", "client-fingerprint", "fp", "udp_relay_mode", "udp-relay-mode", "reduce_rtt", "reduce-rtt", "congestion_controller", "congestion-controller", "obfs", "obfs_password") if raw.get(key)]
            if fields:
                diagnostics.append(RenderWarning(code="shadowrocket-unverified-fields-omitted", message=f"{name}: unverified inline fields omitted ({', '.join(fields)}); TLS/transport connectivity must be checked", target=name, severity="warning", bucket="pending_validation"))
            if _first_raw_bool(raw, ("insecure", "skip-cert-verify")):
                diagnostics.append(RenderWarning(code="shadowrocket-insecure-explicit", message=f"{name}: explicit allowInsecure=1 disables certificate verification; only Trojan TCP is verified", target=name, severity="warning", bucket="pending_validation"))
        if target == "surge" and is_skipped and protocol in {"vmess", "trojan"} and _raw_transport_type(raw) not in {"", "tcp", "ws"}:
            diagnostics.append(RenderWarning(
                code="surge-transport-refused", message=f"Surge skipped {name}: unsupported transport",
                target=name, severity="warning", bucket="refused",
            ))
            continue
        if target == "shadowrocket" and is_skipped:
            inline_reason = _shadowrocket_inline_unsupported_reason(node)
            if inline_reason:
                diagnostics.append(RenderWarning(
                    code="shadowrocket-inline-unsupported", message=f"Shadowrocket skipped {name}: {inline_reason}",
                    target=name, severity="warning", bucket="refused",
                ))
                continue

        if target == "surge" and is_skipped and protocol == "vless":
            diagnostics.append(
                RenderWarning(
                    code="surge-vless-refused",
                    message=f"Surge skipped {name}: VLESS is not supported in this renderer",
                    target=name,
                    severity="error",
                    bucket="refused",
                )
            )
            continue

        if protocol == "tuic":
            identity, reason = _resolve_tuic_identity(raw, node)
            if is_skipped and reason:
                diagnostics.append(
                    RenderWarning(
                        code=f"{target}-tuic-refused",
                        message=f"{target} skipped {name}: {reason}",
                        target=name,
                        severity="error",
                        bucket="refused",
                    )
                )
                continue
            if target == "shadowrocket" and is_skipped and identity and identity["version"] == 4:
                diagnostics.append(
                    RenderWarning(
                        code="shadowrocket-tuic-v4-pending-validation",
                        message=(
                            f"Shadowrocket skipped {name}: TUIC v4 token rendering is not verified and remains pending validation"
                        ),
                        target=name,
                        severity="warning",
                        bucket="pending_validation",
                    )
                )
                continue

        if target == "shadowrocket" and protocol == "vless" and _first_raw(raw, ("packet_encoding", "packet-encoding")):
            has_vless_extensions = bool(
                _first_raw(raw, ("flow", "packet_encoding", "packet-encoding"))
                or _first_raw_mapping(raw, ("reality_opts", "reality-opts"))
            )
            if has_vless_extensions:
                diagnostics.append(
                    RenderWarning(
                        code="shadowrocket-vless-extension-pending-validation",
                        message=(
                            f"Shadowrocket node URI preserves {name}'s VLESS extensions; client runtime support remains pending validation"
                        ),
                        target=name,
                        severity="warning",
                        bucket="pending_validation",
                    )
                )
    return diagnostics


def _sanitize_skip_proxy_entries(
    values: list[str] | tuple[str, ...] | None,
    *,
    excluded_routes: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    normalized_excluded = {
        str(item or "").strip().strip(",")
        for item in (excluded_routes or [])
        if str(item or "").strip().strip(",")
    }
    output: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = str(item or "").strip().strip(",")
        if not text or text in seen or text in normalized_excluded:
            continue
        seen.add(text)
        output.append(text)
    return output


def derive_shadowrocket_profile_diagnostics(
    profile_settings: Mapping[str, object] | None,
    *, local_host_aliases: frozenset[str] | None = None,
) -> list[RenderWarning]:
    normalized = normalize_lazycat_profile_settings(profile_settings or {})
    diagnostics: list[RenderWarning] = [
        *derive_lazycat_host_record_diagnostics(profile_settings, target="shadowrocket", local_host_aliases=local_host_aliases)
    ]
    if "*" in normalized.get(LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY, []):
        diagnostics.append(RenderWarning(code="shadowrocket-mitm-global-refused", message="Global MITM hostname * omitted; use explicit hosts", target="mitm.hostname", severity="warning", bucket="refused"))
    if normalized.get(LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY):
        diagnostics.append(
            RenderWarning(
                code="shadowrocket-always-real-ip-direct-access-validated",
                message=(
                    "Shadowrocket always-real-ip is validated for subscription refresh and retained text export, "
                    "while current routing evidence only covers the bounded LAN probe where it is paired with skip-proxy"
                ),
                target=LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY,
                severity="warning",
                bucket="downgraded",
            )
        )
    if not normalized.get(LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY, True):
        diagnostics.append(RenderWarning(code="shadowrocket-ipv6-disable-ineffective", message="Shadowrocket 2.2.93 ipv6=false does not disable IPv6 at runtime; use explicit rules to restrict it", target="shadowrocket_ipv6", severity="warning", bucket="downgraded"))
    if normalized.get(LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY):
        diagnostics.append(
            RenderWarning(
                code="shadowrocket-map-local-intercept-only",
                message=(
                    "Shadowrocket Map Local is omitted because tested forms intercept but fail to deliver; "
                    "inline data delivery remains unreliable, so use Script for response mocking"
                ),
                target=LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY,
                severity="warning",
                bucket="downgraded",
            )
        )
    return diagnostics


def derive_mihomo_pending_profile_diagnostics(
    profile_settings: Mapping[str, object] | None,
    *, local_host_aliases: frozenset[str] | None = None,
) -> list[RenderWarning]:
    raw = profile_settings or {}
    normalized = normalize_lazycat_profile_settings(raw)
    diagnostics: list[RenderWarning] = [
        *derive_lazycat_host_record_diagnostics(profile_settings, target="clash", local_host_aliases=local_host_aliases)
    ]
    for key in (LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY, LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY, LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY):
        if key in raw and not normalized[key]:
            diagnostics.append(RenderWarning(code="clash-dns-empty-defaulted", message=f"{key} was empty; restored the documented default DNS servers", target=key, severity="warning", bucket="downgraded"))
    if normalized.get(LAZYCAT_PROFILE_CLASH_TUN_ENABLE_KEY) and not normalized.get(LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY):
        diagnostics.append(RenderWarning(code="clash-tun-dns-hijack-defaulted", message="TUN requires DNS hijacking; restored any:53 and tcp://any:53", target="tun.dns-hijack", severity="warning", bucket="downgraded"))
    pending_keys = [
        (LAZYCAT_PROFILE_CLASH_TCP_CONCURRENT_KEY, "clash-tcp-concurrent-pending-validation"),
        (LAZYCAT_PROFILE_CLASH_ALWAYS_REAL_IP_KEY, "clash-always-real-ip-pending-validation"),
    ]
    for setting_key, code in pending_keys:
        if setting_key not in raw:
            continue
        value = normalized.get(setting_key)
        enabled = bool(value) if not isinstance(value, list) else bool(list(value))
        if not enabled:
            continue
        diagnostics.append(
            RenderWarning(
                code=code,
                message=f"Mihomo setting {setting_key} is not emitted as a confirmed-safe field",
                target=setting_key,
                severity="warning",
                bucket="pending_validation",
            )
        )
    return diagnostics


def _lazycat_domain_match(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    normalized = re.sub(r"^[+*.]+", "", text)
    return any(
        normalized == suffix or normalized.endswith(f".{suffix}")
        for suffix in LAZYCAT_DOMAIN_SUFFIXES
    )


def _lazycat_host_target_warning(host: object, target: object, *, local_aliases: set[str]) -> str:
    host_text = str(host or "").strip()
    target_text = str(target or "").strip()
    if not host_text or not target_text or not _lazycat_domain_match(host_text):
        return ""
    normalized_target = target_text.lower()
    if normalized_target in {"localhost", "127.0.0.1", "::1"}:
        return (
            f"LazyCat host record {host_text} -> {target_text} points to localhost. "
            "That usually hijacks the remote microservice entry back to the current machine."
        )
    if normalized_target in local_aliases:
        return (
            f"LazyCat host record {host_text} -> {target_text} points to the current machine. "
            "That can hijack the remote microservice entry instead of reaching the box-side service."
        )
    return ""


def derive_lazycat_host_record_diagnostics(
    profile_settings: Mapping[str, object] | None,
    *,
    target: str,
    local_host_aliases: frozenset[str] | None = None,
) -> list[RenderWarning]:
    normalized = normalize_lazycat_profile_settings(profile_settings or {})
    if target == "surge":
        host_records_key = LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY
    elif target == "shadowrocket":
        host_records_key = LAZYCAT_PROFILE_SHADOWROCKET_HOST_RECORDS_KEY
    elif target == "clash":
        host_records_key = LAZYCAT_PROFILE_CLASH_HOST_RECORDS_KEY
    else:
        return []
    host_records = normalized.get(host_records_key)
    if not isinstance(host_records, Mapping):
        return []
    local_aliases = _local_host_target_aliases() if local_host_aliases is None else local_host_aliases
    diagnostics: list[RenderWarning] = []
    for host, value in host_records.items():
        message = _lazycat_host_target_warning(host, value, local_aliases=local_aliases)
        if not message:
            continue
        diagnostics.append(
            RenderWarning(
                code=f"{target}-lazycat-host-record-local-target",
                message=message,
                target=f"{host_records_key}.{str(host).strip()}",
                severity="warning",
                bucket="downgraded",
            )
        )
    return diagnostics


def _host_is_local_or_private(host: str) -> bool:
    normalized = str(host or "").strip().lower().strip("[]")
    if not normalized:
        return False
    if normalized in _local_host_target_aliases():
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
    )


def resolve_preferred_surge_base_url(
    app_base_url: str,
    profile_settings: Mapping[str, object] | None,
) -> str:
    normalized_base = str(app_base_url or "").strip().rstrip("/")
    if not normalized_base:
        return ""
    parsed = urlparse(normalized_base)
    if not _host_is_local_or_private(parsed.hostname or ""):
        return normalized_base

    normalized_settings = normalize_lazycat_profile_settings(profile_settings or {})
    host_records = normalized_settings.get(LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY, {})
    if not isinstance(host_records, Mapping):
        return normalized_base

    candidates = [
        str(host).strip().lower()
        for host, target in host_records.items()
        if str(host).strip()
        and str(target).strip()
        and _lazycat_domain_match(host)
    ]
    if not candidates:
        return normalized_base

    chosen_host = sorted(candidates, key=lambda item: (0 if item.startswith("subhub.") else 1, item))[0]
    return f"https://{chosen_host}"


def _ss_plugin_config(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    plugin = _first_raw(raw, ("plugin",)).lower()
    plugin_opts = _first_raw_mapping(raw, ("plugin-opts", "plugin_opts"))
    return plugin, plugin_opts


def _escape_sip002_plugin_part(value: str) -> str:
    text = str(value or "")
    for char in ("\\", ";", "=", ":"):
        text = text.replace(char, f"\\{char}")
    return text


def _surge_ss_plugin_fields(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    plugin, plugin_opts = _ss_plugin_config(raw)
    if not plugin:
        return {}, ""
    if plugin not in {"obfs", "obfs-local"}:
        return {}, f"unsupported ss plugin {plugin}"
    mode = str(plugin_opts.get("mode") or "").strip()
    if not mode:
        return {}, "obfs plugin missing mode"
    payload: dict[str, Any] = {"obfs": mode}
    host = str(plugin_opts.get("host") or "").strip()
    if host:
        payload["obfs-host"] = host
    path = str(plugin_opts.get("path") or "").strip()
    if path:
        payload["obfs-uri"] = path
    return payload, ""


def _shadowrocket_ss_plugin_value(raw: dict[str, Any]) -> str:
    plugin, plugin_opts = _ss_plugin_config(raw)
    if plugin == "v2ray-plugin":
        parts = [plugin]
        for key, value in sorted(plugin_opts.items()):
            if value is True:
                parts.append(_escape_sip002_plugin_part(key))
            elif value is not False:
                parts.append(f"{_escape_sip002_plugin_part(key)}={_escape_sip002_plugin_part(str(value))}")
        return ";".join(parts)
    if plugin not in {"obfs", "obfs-local"}:
        return ""
    mode = str(plugin_opts.get("mode") or "").strip()
    if not mode:
        return ""
    parts = ["obfs-local", f"obfs={_escape_sip002_plugin_part(mode)}"]
    host = str(plugin_opts.get("host") or "").strip()
    if host:
        parts.append(f"obfs-host={_escape_sip002_plugin_part(host)}")
    path = str(plugin_opts.get("path") or "").strip()
    if path:
        parts.append(f"obfs-uri={_escape_sip002_plugin_part(path)}")
    return ";".join(parts)


def _clash_udp_value(raw: dict[str, Any], protocol: str, *, udp_default_enabled: bool) -> bool | None:
    explicit = _first_raw_bool(raw, ("udp", "udp_enabled", "udp-enabled", "udp-relay"))
    if explicit is not None:
        return explicit
    if protocol not in CLASH_UDP_SUPPORTED_PROTOCOLS:
        return None
    return bool(udp_default_enabled)


def _with_clash_udp(
    payload: dict[str, Any],
    raw: dict[str, Any],
    protocol: str,
    *,
    udp_default_enabled: bool,
) -> dict[str, Any]:
    udp_value = _clash_udp_value(raw, protocol, udp_default_enabled=udp_default_enabled)
    if udp_value is not None:
        payload["udp"] = udp_value
    return payload


def _is_chain_home_node(node: NodeRecord) -> bool:
    return node.quality_group == QUALITY_CHAIN_HOME or bool((node.raw or {}).get("chain_home"))


def _chain_front_binding_key(node: NodeRecord) -> str:
    raw = node.raw or {}
    return str(raw.get("chain_front_dedupe_key", "") or "").strip()


def _resolved_chain_proxy_name(
    node: NodeRecord,
    *,
    front_name_by_key: dict[str, str] | None,
) -> str:
    if not _is_chain_home_node(node):
        return ""
    binding_key = _chain_front_binding_key(node)
    if not binding_key or not front_name_by_key:
        return ""
    return str(front_name_by_key.get(binding_key, "") or "").strip()


def _with_chain_proxy(
    payload: dict[str, Any],
    node: NodeRecord,
    *,
    client: str,
    front_name_by_key: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not _is_chain_home_node(node):
        return payload
    if client == "clash":
        payload["dialer-proxy"] = _CHAIN_INGRESS_GROUP_NAME
    elif client == "shadowrocket":
        payload["forwarding-proxy"] = _CHAIN_INGRESS_GROUP_NAME
    elif client == "surge":
        payload["underlying-proxy"] = _CHAIN_INGRESS_GROUP_NAME
    return payload


def _raw_transport_type(raw: Mapping[str, Any]) -> str:
    transport = str(_first_raw(raw, ("network", "transport")) or "").strip().lower()
    if transport:
        return transport
    candidate = str(raw.get("type") or "").strip().lower()
    # Native Clash's type is the proxy protocol, not its transport.
    return candidate if candidate in {"tcp", "ws", "grpc", "http", "h2", "quic", "httpupgrade", "xhttp"} else ""


def _raw_ws_opts(raw: Mapping[str, Any]) -> dict[str, Any]:
    ws_opts = _first_raw_mapping(raw, ("ws-opts", "ws_opts"))
    path = str(
        ws_opts.get("path")
        or _first_raw(raw, ("ws-path", "path"))
        or ""
    ).strip()
    headers = ws_opts.get("headers")
    if not isinstance(headers, dict):
        headers = _first_raw_mapping(raw, ("ws-headers", "ws_headers"))
    payload: dict[str, Any] = {}
    if path:
        payload["path"] = path
    if isinstance(headers, dict) and headers:
        payload["headers"] = {
            str(key).strip(): str(value).strip()
            for key, value in headers.items()
            if str(key).strip()
        }
    return payload


def _wireguard_addresses(raw: dict[str, Any]) -> tuple[str, str, list[str]]:
    families: dict[int, list[str]] = {4: [], 6: []}
    invalid: list[str] = []
    for key in ("ip", "address", "ip6", "ipv6"):
        for value in _first_raw_list(raw, (key,)):
            try:
                address = ipaddress.ip_interface(value).ip
            except ValueError:
                invalid.append(value)
                continue
            text = str(address)
            if text not in families[address.version]:
                families[address.version].append(text)
    return (
        next(iter(families[4]), ""), next(iter(families[6]), ""),
        [*families[4][1:], *families[6][1:], *invalid],
    )


def _clash_proxy(
    node: NodeRecord,
    *,
    udp_default_enabled: bool = True,
    front_name_by_key: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    protocol = node.protocol.lower()
    raw = node.raw or {}
    if protocol in {"vmess", "vless", "trojan"} and _raw_transport_type(raw) not in {"", "tcp", "ws", "grpc"}:
        return None
    base = {
        "name": _safe_name(node.name),
        "server": node.host,
        "port": int(node.port),
    }

    if protocol in {"http", "https"}:
        payload = {**base, "type": "http"}
        if protocol == "https":
            payload["tls"] = True
        if node.username:
            payload["username"] = node.username
        if node.password:
            payload["password"] = node.password
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol == "socks5":
        payload = {**base, "type": "socks5"}
        if node.username:
            payload["username"] = node.username
        if node.password:
            payload["password"] = node.password
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol == "ss":
        cipher = _first_raw(raw, ("cipher", "method", "encrypt-method"))
        password = _first_raw(raw, ("password", "passwd"), node.password)
        if not cipher or not password:
            return None
        payload = {**base, "type": "ss", "cipher": cipher, "password": password}
        plugin = _first_raw(raw, ("plugin",))
        if plugin:
            payload["plugin"] = plugin
        plugin_opts = _first_raw_mapping(raw, ("plugin-opts", "plugin_opts"))
        if plugin_opts:
            payload["plugin-opts"] = plugin_opts
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol == "trojan":
        password = _first_raw(raw, ("password", "passwd"), node.password)
        if not password:
            return None
        payload = {**base, "type": "trojan", "password": password, "skip-cert-verify": False}
        sni = _first_raw(raw, ("sni", "servername", "server_name"))
        if sni:
            payload["sni"] = sni
        insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
        if insecure is not None:
            payload["skip-cert-verify"] = insecure
        alpn = _first_raw_list(raw, ("alpn",))
        if alpn:
            payload["alpn"] = alpn
        client_fp = _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp"))
        if client_fp:
            payload["client-fingerprint"] = client_fp
        if _raw_transport_type(raw) == "ws":
            payload["network"] = "ws"
            ws_opts = _raw_ws_opts(raw)
            if ws_opts:
                payload["ws-opts"] = ws_opts
        elif _raw_transport_type(raw) == "grpc":
            payload["network"] = "grpc"
            payload["grpc-opts"] = _first_raw_mapping(raw, ("grpc-opts", "grpc_opts"))
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol in {"vmess", "vless"}:
        uuid = _first_raw(raw, ("uuid", "id", "userId", "userid"), node.username)
        if not uuid:
            return None
        payload = {**base, "type": protocol, "uuid": uuid}
        tls_enabled = _first_raw_bool(raw, ("tls",))
        if tls_enabled is not None:
            payload["tls"] = tls_enabled
        servername = _first_raw(raw, ("sni", "servername", "server_name"))
        if servername:
            payload["servername"] = servername
        alpn = _first_raw_list(raw, ("alpn",))
        if alpn:
            payload["alpn"] = alpn
        payload["skip-cert-verify"] = bool(_first_raw_bool(raw, ("insecure", "skip-cert-verify")) or False)
        client_fp = _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp"))
        if client_fp:
            payload["client-fingerprint"] = client_fp
        if protocol == "vmess":
            payload["alterId"] = int(raw.get("alterId", 0))
            payload["cipher"] = _first_raw(raw, ("cipher",), "auto")
        else:
            flow = _first_raw(raw, ("flow",))
            if flow:
                payload["flow"] = flow
            packet_encoding = _first_raw(raw, ("packet_encoding", "packet-encoding"))
            if packet_encoding:
                payload["packet-encoding"] = packet_encoding
            reality_opts = _first_raw_mapping(raw, ("reality_opts", "reality-opts"))
            if reality_opts:
                payload["reality-opts"] = reality_opts
        if _raw_transport_type(raw) == "ws":
            payload["network"] = "ws"
            ws_opts = _raw_ws_opts(raw)
            if ws_opts:
                payload["ws-opts"] = ws_opts
        elif _raw_transport_type(raw) == "grpc":
            payload["network"] = "grpc"
            payload["grpc-opts"] = _first_raw_mapping(raw, ("grpc-opts", "grpc_opts"))
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol in {"anytls", "hysteria2"}:
        password = _first_raw(raw, ("password",), node.password)
        if not password:
            return None
        payload = {**base, "type": protocol, "password": password}
        sni = _first_raw(raw, ("sni", "servername", "server_name"))
        if sni:
            payload["sni"] = sni
        alpn = _first_raw_list(raw, ("alpn",))
        if alpn:
            payload["alpn"] = alpn
        insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
        payload["skip-cert-verify"] = bool(insecure) if insecure is not None else False
        client_fp = _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp"))
        if client_fp:
            payload["client-fingerprint"] = client_fp
        if protocol == "hysteria2":
            obfs = _first_raw(raw, ("obfs",))
            if obfs:
                payload["obfs"] = obfs
            obfs_password = _first_raw(raw, ("obfs_password", "obfs-password"))
            if obfs_password:
                payload["obfs-password"] = obfs_password
            up = _first_raw(raw, ("up", "up_mbps", "upmbps"))
            if up:
                payload["up"] = str(up)
            down = _first_raw(
                raw,
                ("down", "down_mbps", "downmbps", "download-bandwidth"),
            )
            if down:
                payload["down"] = str(down)
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol == "tuic":
        identity, _ = _resolve_tuic_identity(raw, node)
        if not identity:
            return None
        payload = {
            **base,
            "type": "tuic",
        }
        if identity["version"] == 4:
            payload["token"] = identity["token"]
        else:
            payload["uuid"] = identity["uuid"]
            payload["password"] = identity["password"]
        sni = _first_raw(raw, ("sni", "servername", "server_name"))
        if sni:
            payload["sni"] = sni
        alpn = _first_raw_list(raw, ("alpn",))
        if alpn:
            payload["alpn"] = alpn
        insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
        payload["skip-cert-verify"] = bool(insecure) if insecure is not None else False
        reduce_rtt = identity.get("reduce-rtt")
        if reduce_rtt is not None:
            payload["reduce-rtt"] = reduce_rtt
        congestion_controller = _first_raw(
            raw,
            ("congestion_controller", "congestion-controller"),
        )
        if congestion_controller:
            payload["congestion-controller"] = congestion_controller
        udp_relay_mode = _first_raw(raw, ("udp_relay_mode", "udp-relay-mode"))
        if udp_relay_mode:
            payload["udp-relay-mode"] = udp_relay_mode
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node,
            client="clash",
            front_name_by_key=front_name_by_key,
        )

    if protocol == "wireguard":
        private_key = _first_raw(raw, ("private-key", "private_key"))
        public_key = _first_raw(raw, ("public-key", "public_key"))
        ip, ipv6, _ = _wireguard_addresses(raw)
        if not private_key or not public_key or not (ip or ipv6):
            return None
        payload = {
            **base,
            "type": "wireguard",
            "private-key": private_key,
            "public-key": public_key,
        }
        if ip:
            payload["ip"] = ip
        if ipv6:
            payload["ipv6"] = ipv6
        dns = _first_raw_list(raw, ("dns",))
        if dns:
            payload["dns"] = dns
        mtu = _first_raw(raw, ("mtu",))
        if mtu:
            try:
                payload["mtu"] = int(str(mtu))
            except ValueError:
                pass
        return _with_chain_proxy(
            _with_clash_udp(payload, raw, protocol, udp_default_enabled=udp_default_enabled),
            node, client="clash", front_name_by_key=front_name_by_key,
        )

    return None


def _shadowrocket_proxy_payload(
    node: NodeRecord,
    *,
    front_name_by_key: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    raw = node.raw or {}
    proto = node.protocol.lower()
    if proto == "wireguard":
        private_key = _first_raw(raw, ("private-key", "private_key"))
        public_key = _first_raw(raw, ("public-key", "public_key"))
        ip, ipv6, _ = _wireguard_addresses(raw)
        dns = _first_raw_list(raw, ("dns",))
        if not private_key or not public_key or not (ip or ipv6) or not dns:
            return None
        return _with_chain_proxy({
            "proto": proto, "host": node.host, "port": node.port,
            "privateKey": private_key, "publicKey": public_key,
            "ip": ip or ipv6, "mtu": _first_raw_int(raw, ("mtu",)) or 1420,
            "dns": dns,
        }, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto in {"http", "https"}:
        return _with_chain_proxy({
            "proto": proto,
            "host": node.host,
            "port": node.port,
            "username": _sr_normalize_credential(node.username, is_password=False),
            "password": _sr_normalize_credential(node.password, is_password=True),
        }, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto == "socks5":
        return _with_chain_proxy({
            "proto": "socks5",
            "host": node.host,
            "port": node.port,
            "username": _sr_normalize_credential(node.username, is_password=False),
            "password": _sr_normalize_credential(node.password, is_password=True),
        }, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto == "ss":
        cipher = _first_raw(raw, ("cipher", "method", "encrypt-method"))
        password = _first_raw(raw, ("password", "passwd"), node.password)
        if not cipher or not password:
            return None
        payload = {
            "proto": "ss",
            "host": node.host,
            "port": node.port,
            "cipher": cipher,
            "password": password,
        }
        plugin_value = _shadowrocket_ss_plugin_value(raw)
        if plugin_value:
            payload["plugin"] = plugin_value
        if raw.get("source_uri"):
            payload["source_uri"] = raw["source_uri"]
        return _with_chain_proxy(payload, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto == "trojan":
        password = _first_raw(raw, ("password", "passwd"), node.password)
        if not password:
            return None
        payload = {
            "proto": "trojan",
            "host": node.host,
            "port": node.port,
            "password": password,
            "sni": _first_raw(raw, ("sni", "servername", "server_name")),
            "insecure": False,
            "network": _raw_transport_type(raw) or "tcp",
            "ws-opts": _raw_ws_opts(raw),
        }
        insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
        if insecure is not None:
            payload["insecure"] = insecure
        if raw.get("source_uri"):
            payload["source_uri"] = raw["source_uri"]
        return _with_chain_proxy(payload, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto in {"vmess", "vless"}:
        uuid = _first_raw(raw, ("uuid", "id", "userId", "userid"), node.username)
        if not uuid:
            return None
        payload = {
            "proto": proto,
            "host": node.host,
            "port": node.port,
            "uuid": uuid,
            "cipher": _first_raw(raw, ("cipher",), "auto"),
            "alterId": raw.get("alterId", 0),
            "tls": bool(_first_raw_bool(raw, ("tls",)) or False),
            "sni": _first_raw(raw, ("sni", "servername", "server_name")),
            "alpn": _first_raw_list(raw, ("alpn",)),
            "insecure": bool(_first_raw_bool(raw, ("insecure", "skip-cert-verify")) or False),
            "network": _raw_transport_type(raw) or "tcp",
            "ws-opts": _raw_ws_opts(raw),
            "flow": _first_raw(raw, ("flow",)),
            "packet_encoding": _first_raw(raw, ("packet_encoding", "packet-encoding")),
            "reality_opts": _first_raw_mapping(raw, ("reality_opts", "reality-opts")),
            "client_fingerprint": _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp")),
        }
        if raw.get("source_uri"):
            payload["source_uri"] = raw["source_uri"]
        return _with_chain_proxy(payload, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto in {"anytls", "hysteria2"}:
        password = _first_raw(raw, ("password",), node.password)
        if not password:
            return None
        payload: dict[str, Any] = {
            "proto": proto,
            "host": node.host,
            "port": node.port,
            "password": password,
        }
        sni = _first_raw(raw, ("sni", "servername", "server_name"))
        if sni:
            payload["sni"] = sni
        alpn = _first_raw_list(raw, ("alpn",))
        if alpn:
            payload["alpn"] = alpn
        insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
        payload["insecure"] = bool(insecure) if insecure is not None else False
        client_fp = _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp"))
        if client_fp:
            payload["client_fingerprint"] = client_fp
        if proto == "hysteria2":
            obfs = _first_raw(raw, ("obfs",))
            if obfs:
                payload["obfs"] = obfs
            obfs_password = _first_raw(raw, ("obfs_password", "obfs-password"))
            if obfs_password:
                payload["obfs_password"] = obfs_password
        return _with_chain_proxy(payload, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    if proto == "tuic":
        identity, _ = _resolve_tuic_identity(raw, node)
        if not identity:
            return None
        if identity["version"] == 4:
            return None
        payload = {
            "proto": "tuic",
            "host": node.host,
            "port": node.port,
        }
        payload["uuid"] = identity["uuid"]
        payload["password"] = identity["password"]
        sni = _first_raw(raw, ("sni", "servername", "server_name"))
        if sni:
            payload["sni"] = sni
        alpn = _first_raw_list(raw, ("alpn",))
        if alpn:
            payload["alpn"] = alpn
        insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
        payload["insecure"] = bool(insecure) if insecure is not None else False
        reduce_rtt = identity.get("reduce-rtt")
        if reduce_rtt is not None:
            payload["reduce_rtt"] = reduce_rtt
        congestion_controller = _first_raw(
            raw,
            ("congestion_controller", "congestion-controller"),
        )
        if congestion_controller:
            payload["congestion_controller"] = congestion_controller
        udp_relay_mode = _first_raw(raw, ("udp_relay_mode", "udp-relay-mode"))
        if udp_relay_mode:
            payload["udp_relay_mode"] = udp_relay_mode
        return _with_chain_proxy(payload, node, client="shadowrocket", front_name_by_key=front_name_by_key)
    return None


def _append_kv_pairs(base: str, payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    text = base
    for key in keys:
        value = payload.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, bool):
            text += f", {key}={'true' if value else 'false'}"
            continue
        if isinstance(value, list):
            joined = "|".join(str(item).strip() for item in value if str(item).strip())
            if not joined:
                continue
            text += f", {key}={joined}"
            continue
        text += f", {key}={value}"
    return text


def _shadowrocket_node_export_name(node: NodeRecord) -> str:
    quality_group = node.quality_group if node.quality_group in QUALITY_GROUPS else QUALITY_MEDIUM
    return f"{quality_group} | {_safe_name(node.name)}"


def _uri_authority_host(host: str) -> str:
    text = str(host or "").strip()
    if not text:
        return ""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return text
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{text}]"
    return text


def _shadowrocket_proxy_uri(name: str, payload: dict[str, Any]) -> str | None:
    proto = str(payload.get("proto", "")).strip().lower()
    host = str(payload.get("host", "")).strip()
    authority_host = _uri_authority_host(host)
    port = int(payload.get("port", 0))
    fragment = quote(name, safe="")
    if not proto or not host or port <= 0:
        return None
    source_uri = str(payload.get("source_uri") or "")
    if source_uri.lower().startswith(f"{proto}://"):
        return source_uri.split("#", 1)[0] + "#" + fragment

    if proto in {"http", "https", "socks5"}:
        auth = ""
        username = str(payload.get("username", "") or "").strip()
        password = str(payload.get("password", "") or "").strip()
        if username:
            auth = quote(username, safe="")
            if password:
                auth += f":{quote(password, safe='')}"
            auth += "@"
        return f"{proto}://{auth}{authority_host}:{port}#{fragment}"

    if proto == "ss":
        cipher = str(payload.get("cipher", "") or "").strip()
        password = str(payload.get("password", "") or "").strip()
        if not cipher or not password:
            return None
        credentials = base64.b64encode(f"{cipher}:{password}".encode("utf-8")).decode("ascii")
        plugin = str(payload.get("plugin", "") or "").strip()
        if plugin:
            query = urlencode({"plugin": plugin})
            return f"ss://{credentials}@{authority_host}:{port}/?{query}#{fragment}"
        return f"ss://{credentials}@{authority_host}:{port}#{fragment}"

    if proto == "vmess":
        uuid = str(payload.get("uuid", "") or "").strip()
        if not uuid:
            return None
        vmess_payload: dict[str, Any] = {
            "v": "2",
            "ps": name,
            "add": host,
            "port": str(port),
            "id": uuid,
            "aid": str(payload.get("alterId", 0)),
            "scy": str(payload.get("cipher", "") or "auto"),
            "net": str(payload.get("network") or "tcp"),
            "type": "none",
            "host": str((payload.get("ws-opts") or {}).get("headers", {}).get("Host") or ""),
            "path": str((payload.get("ws-opts") or {}).get("path") or ""),
            "tls": "tls" if payload.get("tls") else "",
        }
        if payload.get("sni"):
            vmess_payload["sni"] = str(payload.get("sni"))
        if payload.get("client_fingerprint"):
            vmess_payload["fp"] = str(payload["client_fingerprint"])
        insecure = payload.get("insecure")
        if insecure is not None:
            vmess_payload["allowInsecure"] = bool(insecure)
        alpn = payload.get("alpn")
        if isinstance(alpn, list) and alpn:
            vmess_payload["alpn"] = list(alpn)
        encoded = base64.b64encode(
            json.dumps(vmess_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        return f"vmess://{encoded}"

    if proto in {"trojan", "vless", "anytls", "hysteria2"}:
        if proto == "vless":
            username = str(payload.get("uuid", "") or "").strip()
        else:
            username = str(payload.get("password", "") or "").strip()
        if not username:
            return None
        query: dict[str, str] = {}
        if proto == "vless":
            query["type"] = str(payload.get("network") or "tcp")
            reality = payload.get("reality_opts") or {}
            query["security"] = "reality" if reality else "tls" if payload.get("tls") else "none"
            if payload.get("flow"):
                query["flow"] = str(payload["flow"])
            if payload.get("packet_encoding"):
                query["packet-encoding"] = str(payload["packet_encoding"])
            for key, target in (("public-key", "pbk"), ("short-id", "sid")):
                if reality.get(key):
                    query[target] = str(reality[key])
            ws = payload.get("ws-opts") or {}
            if ws.get("path"):
                query["path"] = str(ws["path"])
            ws_host = (ws.get("headers") or {}).get("Host")
            if ws_host:
                query["host"] = str(ws_host)
        sni = str(payload.get("sni", "") or "").strip()
        if sni:
            query["sni"] = sni
        alpn = payload.get("alpn")
        if isinstance(alpn, list):
            joined = ",".join(str(item).strip() for item in alpn if str(item).strip())
            if joined:
                query["alpn"] = joined
        insecure = payload.get("insecure")
        if insecure is not None:
            query["insecure"] = "1" if bool(insecure) else "0"
        client_fp = str(payload.get("client_fingerprint", "") or "").strip()
        if client_fp:
            query["fp"] = client_fp
        obfs = str(payload.get("obfs", "") or "").strip()
        if obfs:
            query["obfs"] = obfs
        obfs_password = str(payload.get("obfs_password", "") or "").strip()
        if obfs_password:
            query["obfs-password"] = obfs_password
        query_suffix = f"?{urlencode(query)}" if query else ""
        return f"{proto}://{quote(username, safe='')}@{authority_host}:{port}{query_suffix}#{fragment}"

    if proto == "tuic":
        query: dict[str, str] = {}
        token = str(payload.get("token", "") or "").strip()
        uuid = str(payload.get("uuid", "") or "").strip()
        password = str(payload.get("password", "") or "").strip()
        if token:
            authority = quote(token, safe="")
        else:
            if not uuid or not password:
                return None
            authority = f"{quote(uuid, safe='')}:{quote(password, safe='')}"
        sni = str(payload.get("sni", "") or "").strip()
        if sni:
            query["sni"] = sni
        alpn = payload.get("alpn")
        if isinstance(alpn, list):
            joined = "|".join(str(item).strip() for item in alpn if str(item).strip())
            if joined:
                query["alpn"] = joined
        insecure = payload.get("insecure")
        if insecure is not None:
            query["insecure"] = "1" if bool(insecure) else "0"
        reduce_rtt = payload.get("reduce_rtt")
        if reduce_rtt is not None:
            query["reduce-rtt"] = "1" if bool(reduce_rtt) else "0"
        congestion_controller = str(payload.get("congestion_controller", "") or "").strip()
        if congestion_controller:
            query["congestion-controller"] = congestion_controller
        udp_relay_mode = str(payload.get("udp_relay_mode", "") or "").strip()
        if udp_relay_mode:
            query["udp-relay-mode"] = udp_relay_mode
        query_suffix = f"?{urlencode(query)}" if query else ""
        return f"tuic://{authority}@{authority_host}:{port}{query_suffix}#{fragment}"

    return None


def _build_shadowrocket_node_lines(
    nodes: list[NodeRecord],
    *,
    front_name_by_key: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    payloads: list[dict[str, Any]] = []
    export_bases: list[str] = []
    skipped: list[str] = []
    for node in nodes:
        if _is_chain_home_node(node):
            continue
        if _shadowrocket_node_uri_unsupported_reason(node):
            skipped.append(node.name)
            continue
        payload = _shadowrocket_proxy_payload(node, front_name_by_key=front_name_by_key)
        if not payload:
            skipped.append(node.name)
            continue
        payloads.append(payload)
        export_bases.append(_shadowrocket_node_export_name(node))
    if not payloads:
        return [], skipped

    names = _uniqueify_names(export_bases, _RESERVED_PROXY_NAMES, case_insensitive=True)
    lines: list[str] = []
    for payload, name in zip(payloads, names):
        line = _shadowrocket_proxy_uri(name, payload)
        if not line:
            skipped.append(name)
            continue
        lines.append(line)
    return lines, skipped


def build_shadowrocket_nodes_subscription(nodes: list[NodeRecord]) -> tuple[str, list[str]]:
    projection = project_configuration_intent(
        derive_configuration_intent(build_policy_ir(nodes, []), None, profile=""), "shadowrocket",
    )
    lines, skipped = _build_shadowrocket_node_lines(projection.policy.nodes)
    canonical = "\n".join(lines)
    encoded = base64.b64encode(canonical.encode("utf-8")).decode("ascii") if canonical else ""
    return encoded, skipped


def _shadowrocket_http_pipeline_note_lines(settings: Mapping[str, Any]) -> list[str]:
    url_rewrite = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY, []) or [])
    map_local = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY, []) or [])
    script_request = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY, []) or [])
    script_response = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY, []) or [])
    mitm_hostnames = [host for host in list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY, []) or []) if host != "*"]
    if not any((url_rewrite, map_local, script_request, script_response, mitm_hostnames)):
        return []
    return [
        "# Shadowrocket 2.2.93: Rewrite activates after download; MITM also supports explicit host:8443.",
        "# MITM: generate/install a CA in the client, enable full system trust, then enable HTTPS decryption, save and restart VPN; test an allowlisted host.",
        *(["# SubHub warning [shadowrocket-map-local-intercept-only]: Map Local omitted: verified forms intercept but fail to deliver; use an http-response Script."] if map_local else []),
    ]


def _shadowrocket_http_pipeline_section_lines(settings: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    url_rewrite = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_URL_REWRITE_KEY, []) or [])
    if url_rewrite:
        lines.extend(["[URL Rewrite]", *url_rewrite, ""])
    map_local = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_MAP_LOCAL_KEY, []) or [])
    script_request = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_REQUEST_KEY, []) or [])
    script_response = list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_SCRIPT_RESPONSE_KEY, []) or [])
    if script_request or script_response:
        lines.append("[Script]")
        lines.extend(script_request)
        lines.extend(script_response)
        lines.append("")
    mitm_hostnames = [host for host in list(settings.get(LAZYCAT_PROFILE_SHADOWROCKET_MITM_HOSTNAME_KEY, []) or []) if host != "*"]
    if mitm_hostnames:
        lines.extend([
            "[MITM]",
            "enable = true",
            f"hostname = {', '.join(mitm_hostnames)}",
            "",
        ])
    return lines


def _shadowrocket_proxy_line(name: str, payload: dict[str, Any]) -> str:
    proto = str(payload.get("proto", "")).lower()
    text = f"{name} = {proto}, {payload.get('host', '')}, {int(payload.get('port', 0))}"
    if proto in {"http", "https", "socks5"}:
        if payload.get("username") and payload.get("password"):
            text += f", {payload['username']}, {payload['password']}"
    elif proto == "wireguard":
        return _append_kv_pairs(text, payload, ("privateKey", "publicKey", "ip", "mtu", "dns", "forwarding-proxy"))
    elif proto == "tuic":
        text += f", uuid={payload.get('uuid', '')}, password={payload.get('password', '')}, version=5"
    elif proto in {"vmess", "vless"}:
        text += f", password={payload.get('uuid', '')}"
        if proto == "vmess":
            text += ", alterId=0, method=auto"
    else:
        text += f", password={payload.get('password', '')}"
        if proto == "ss":
            text += f", method={payload.get('cipher', '')}"
    if payload.get("tls") or payload.get("reality_opts"):
        text += ", tls=true"
    if payload.get("sni"):
        text += f", peer={payload['sni']}"
    if payload.get("network") == "ws":
        ws = payload.get("ws-opts") or {}
        text += f", obfs=websocket, obfs-uri={ws.get('path') or '/'}"
        headers = ws.get("headers") or {}
        host = next((value for key, value in headers.items() if key.lower() == "host"), "")
        if host:
            text += f", obfs-host={host}"
    reality = payload.get("reality_opts") or {}
    text = _append_kv_pairs(text, {"publicKey": reality.get("public-key"), "shortId": reality.get("short-id")}, ("publicKey", "shortId"))
    if payload.get("flow") == "xtls-rprx-vision":
        text += ", flow=xtls-rprx-vision"
    if payload.get("insecure"):
        text += ", allowInsecure=1"
    # udp is an integer switch in the verified Shadowrocket profile grammar.
    if "udp" in payload:
        text += f", udp={1 if payload['udp'] else 0}"
    return _append_kv_pairs(text, payload, ("forwarding-proxy",))


def _surge_proxy_payload(
    node: NodeRecord,
    *,
    front_name_by_key: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if node.protocol.lower() in {"vmess", "trojan"} and _raw_transport_type(node.raw or {}) not in {"", "tcp", "ws"}:
        return None
    if node.protocol.lower() == "vmess" and (_first_raw_int(node.raw or {}, ("alterId", "alter-id")) or 0) > 0:
        return None
    if node.protocol.lower() == "vless":
        return None
    if node.protocol.lower() == "wireguard":
        raw = node.raw or {}
        private_key = _first_raw(raw, ("private-key", "private_key"))
        public_key = _first_raw(raw, ("public-key", "public_key"))
        ip, ipv6, _ = _wireguard_addresses(raw)
        dns = _first_raw_list(raw, ("dns",))
        if not private_key or not public_key or not (ip or ipv6) or not dns:
            return None
        payload = {
            "proto": "wireguard",
            "host": node.host,
            "port": node.port,
            "private-key": private_key,
            "public-key": public_key,
            "ip": ip,
            "ipv6": ipv6,
            "mtu": _first_raw_int(raw, ("mtu",)) or 1280,
            "allowed-ips": _first_raw_list(raw, ("allowed-ips", "allowed_ips")) or ["0.0.0.0/0", "::/0"],
        }
        dns = _first_raw_list(raw, ("dns",))
        if dns:
            payload["dns"] = dns
        return _with_chain_proxy(payload, node, client="surge", front_name_by_key=front_name_by_key)
    if node.protocol.lower() == "tuic":
        raw = node.raw or {}
        identity, _ = _resolve_tuic_identity(raw, node)
        if identity and identity["version"] == 4:
            payload: dict[str, Any] = {
                "proto": "tuic",
                "host": node.host,
                "port": node.port,
                "token": identity["token"],
                "skip-cert-verify": False,
            }
            sni = _first_raw(raw, ("sni", "servername", "server_name"))
            if sni:
                payload["sni"] = sni
            alpn = _first_raw_list(raw, ("alpn",))
            if alpn:
                payload["alpn"] = alpn
            insecure = _first_raw_bool(raw, ("insecure", "skip-cert-verify"))
            if insecure is not None:
                payload["skip-cert-verify"] = insecure
            reduce_rtt = identity.get("reduce-rtt")
            if reduce_rtt is not None:
                payload["reduce-rtt"] = reduce_rtt
            congestion_controller = _first_raw(
                raw,
                ("congestion_controller", "congestion-controller"),
            )
            if congestion_controller:
                payload["congestion-controller"] = congestion_controller
            udp_relay_mode = _first_raw(raw, ("udp_relay_mode", "udp-relay-mode"))
            if udp_relay_mode:
                payload["udp-relay-mode"] = udp_relay_mode
            port_hopping = _first_raw(raw, ("port-hopping", "port_hopping"))
            if port_hopping:
                payload["port-hopping"] = port_hopping
            port_hopping_interval = _first_raw(
                raw,
                ("port-hopping-interval", "port_hopping_interval"),
            )
            if port_hopping_interval:
                payload["port-hopping-interval"] = port_hopping_interval
            return _with_chain_proxy(payload, node, client="surge", front_name_by_key=front_name_by_key)
    payload = _shadowrocket_proxy_payload(node, front_name_by_key=front_name_by_key)
    if not payload:
        return None
    if str(payload.get("proto", "")).strip().lower() == "vless":
        return None
    if str(payload.get("proto", "")).strip().lower() == "ss":
        if _surge_ss_removed_cipher(node.raw or {}):
            return None
        ss_plugin_fields, skip_reason = _surge_ss_plugin_fields(node.raw or {})
        if skip_reason:
            return None
        payload.update(ss_plugin_fields)
    proto = str(payload.get("proto", "")).strip().lower()
    if "insecure" in payload:
        payload["skip-cert-verify"] = bool(payload.pop("insecure"))
    elif proto in {"trojan", "anytls", "hysteria2", "tuic"}:
        payload["skip-cert-verify"] = False
    if "client_fingerprint" in payload:
        payload["client-fingerprint"] = payload.pop("client_fingerprint")
    if "obfs_password" in payload:
        payload["obfs-password"] = payload.pop("obfs_password")
    if "congestion_controller" in payload:
        payload["congestion-controller"] = payload.pop("congestion_controller")
    if "udp_relay_mode" in payload:
        payload["udp-relay-mode"] = payload.pop("udp_relay_mode")
    if "reduce_rtt" in payload:
        payload["reduce-rtt"] = payload.pop("reduce_rtt")
    raw = node.raw or {}
    if proto in {"trojan", "vmess"} and _raw_transport_type(raw) == "ws":
        payload["ws"] = True
        ws_opts = _raw_ws_opts(raw)
        if ws_opts.get("path"):
            payload["ws-path"] = ws_opts["path"]
        if ws_opts.get("headers"):
            header_text = "|".join(
                f"{key}:{value}"
                for key, value in ws_opts["headers"].items()
            )
            if header_text:
                payload["ws-headers"] = header_text
    if proto == "vmess":
        payload["tls"] = bool(_first_raw_bool(raw, ("tls",)) or False)
        payload["skip-cert-verify"] = bool(_first_raw_bool(raw, ("insecure", "skip-cert-verify")) or False)
        cipher = _first_raw(raw, ("cipher",), "auto")
        if cipher not in {"auto", "aes-128-gcm", "chacha20-ietf-poly1305"}:
            return None
        payload["encrypt-method"] = "aes-128-gcm" if cipher == "auto" else cipher
        if raw.get("alpn") or _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp")):
            return None
        payload["vmess-aead"] = True
    if proto == "hysteria2":
        down = _first_raw(raw, ("download-bandwidth", "down", "downmbps", "down_mbps"))
        if down:
            payload["download-bandwidth"] = down
    cert_pin = _first_raw(
        raw,
        ("server-cert-fingerprint-sha256", "server_cert_fingerprint_sha256"),
    )
    if cert_pin:
        payload["server-cert-fingerprint-sha256"] = cert_pin
    payload.pop("forwarding-proxy", None)
    return _with_chain_proxy(payload, node, client="surge", front_name_by_key=front_name_by_key)


def _surge_proxy_line(name: str, payload: dict[str, Any]) -> str:
    proto = str(payload.get("proto", "")).strip().lower()
    host = str(payload.get("host", "")).strip()
    port = int(payload.get("port", 0))
    if proto == "wireguard":
        return _append_kv_pairs(f"{name} = wireguard, section-name={name}", payload, ("underlying-proxy",))
    if proto in {"http", "https", "socks5"}:
        text = f"{name} = {proto}, {host}, {port}"
        username = str(payload.get("username", "") or "").strip()
        password = str(payload.get("password", "") or "").strip()
        if username:
            text += f", {username}"
            if password:
                text += f", {password}"
        return _append_kv_pairs(text, payload, ("udp-relay", "underlying-proxy",))
    if proto == "ss":
        return _append_kv_pairs((
            f"{name} = ss, {host}, {port}, "
            f"encrypt-method={payload.get('cipher', '')}, password={payload.get('password', '')}"
        ), payload, ("udp-relay", "obfs", "obfs-host", "obfs-uri", "underlying-proxy"))
    if proto == "trojan":
        text = f"{name} = trojan, {host}, {port}, password={payload.get('password', '')}"
        sni = str(payload.get("sni", "") or "").strip()
        if sni:
            text += f", sni={sni}"
        return _append_kv_pairs(
            text,
            payload,
            (
                "ws",
                "ws-path",
                "ws-headers",
                "skip-cert-verify",
                "server-cert-fingerprint-sha256",
                "underlying-proxy",
            ),
        )
    if proto == "vmess":
        return _append_kv_pairs(
            f"{name} = vmess, {host}, {port}, username={payload.get('uuid', '')}",
            payload,
            ("tls", "sni", "skip-cert-verify", "encrypt-method", "ws", "ws-path", "ws-headers", "vmess-aead", "underlying-proxy"),
        )
    if proto in {"anytls", "hysteria2"}:
        text = f"{name} = {proto}, {host}, {port}, password={payload.get('password', '')}"
        return _append_kv_pairs(
            text,
            payload,
            (
                "sni",
                "alpn",
                "skip-cert-verify",
                "client-fingerprint",
                "obfs",
                "obfs-password",
                "download-bandwidth",
                "server-cert-fingerprint-sha256",
                "underlying-proxy",
            ),
        )
    if proto == "tuic":
        token = str(payload.get("token", "") or "").strip()
        if token:
            text = f"{name} = tuic, {host}, {port}, token={token}"
        else:
            text = (
                f"{name} = tuic-v5, {host}, {port}, "
                f"uuid={payload.get('uuid', '')}, password={payload.get('password', '')}"
            )
        return _append_kv_pairs(
            text,
            payload,
            (
                "sni",
                "alpn",
                "skip-cert-verify",
                "reduce-rtt",
                "congestion-controller",
                "udp-relay-mode",
                "port-hopping",
                "port-hopping-interval",
                "server-cert-fingerprint-sha256",
                "underlying-proxy",
            ),
        )
    return _append_kv_pairs(f"{name} = {proto}, {host}, {port}", payload, ("udp-relay", "underlying-proxy",))


def _surge_wireguard_section_lines(name: str, payload: dict[str, Any]) -> list[str]:
    lines = [f"[WireGuard {name}]", f"private-key = {payload['private-key']}"]
    for key, source in (("self-ip", "ip"), ("self-ip-v6", "ipv6")):
        if payload.get(source):
            lines.append(f"{key} = {payload[source]}")
    lines += [f"dns-server = {', '.join(payload['dns'])}", f"mtu = {payload['mtu']}"]
    endpoint = f"{_uri_authority_host(payload['host'])}:{payload['port']}"
    allowed_ips = ", ".join(payload["allowed-ips"])
    if len(payload["allowed-ips"]) > 1:
        allowed_ips = f'"{allowed_ips}"'
    lines.append(f"peer = (public-key = {payload['public-key']}, allowed-ips = {allowed_ips}, endpoint = {endpoint})")
    return lines


def _surge_ss_removed_cipher(raw: dict[str, Any]) -> bool:
    cipher = _first_raw(raw, ("cipher", "method", "encrypt-method")).lower()
    return cipher in {"bf-cfb", "cast5-cfb", "des-cfb", "idea-cfb", "rc2-cfb", "seed-cfb"} or bool(re.fullmatch(r"camellia-\d+-cfb", cipher))


def _surge_unsupported_node_message(node: NodeRecord) -> str:
    if node.protocol.lower() == "wireguard" and not _first_raw_list(node.raw or {}, ("dns",)):
        return f"Surge skipped WireGuard node {node.name}: source DNS is required"
    if node.protocol.lower() == "vmess" and (_first_raw_int(node.raw or {}, ("alterId", "alter-id")) or 0) > 0:
        return f"Surge skipped VMess node {node.name}: legacy alterId > 0 cannot be converted to AEAD"
    if node.protocol.lower() == "ss" and _surge_ss_removed_cipher(node.raw or {}):
        return f"Surge skipped ss node {node.name}: removed stream cipher"
    if node.protocol.lower() != "ss":
        return f"Surge skipped unsupported node {node.name}"
    _, skip_reason = _surge_ss_plugin_fields(node.raw or {})
    if skip_reason:
        return f"Surge skipped ss node {node.name}: {skip_reason}"
    return f"Surge skipped unsupported node {node.name}"


def _group_nodes(nodes: list[NodeRecord]) -> dict[str, list[NodeRecord]]:
    grouped = {group: [] for group in QUALITY_GROUPS}
    for node in nodes:
        group = node.quality_group if node.quality_group in grouped else QUALITY_MEDIUM
        grouped[group].append(node)
    return grouped


def _merge_unique_str_list(base: list[str], extra: list[str]) -> list[str]:
    merged = list(base)
    seen = set(merged)
    for item in extra:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _profile_list(values: object) -> list[str]:
    if isinstance(values, list):
        raw_values = values
    elif isinstance(values, tuple):
        raw_values = list(values)
    else:
        raw_values = []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _render_clash_fake_ip_filter_entries(values: object, *, mode: str) -> list[str]:
    entries = _profile_list(values)
    if str(mode or "").strip().lower() != "rule":
        return entries

    output: list[str] = []
    seen: set[str] = set()
    for item in entries:
        text = str(item or "").strip()
        if not text:
            continue

        if "," in text:
            rendered = text
        else:
            domain = text
            for prefix in ("+.", "*.", "."):
                if domain.startswith(prefix):
                    domain = domain[len(prefix):]
                    break
            domain = domain.strip()
            if not domain:
                continue
            rendered = f"DOMAIN-SUFFIX,{domain},real-ip"

        if rendered in seen:
            continue
        seen.add(rendered)
        output.append(rendered)
    return output


def _profile_ports(values: object) -> list[int | str]:
    output: list[int | str] = []
    for item in _profile_list(values):
        if item.isdigit():
            output.append(int(item))
        else:
            output.append(item)
    return output


def _profile_uid_list(values: object) -> list[int | str]:
    output: list[int | str] = []
    for item in _profile_list(values):
        if item.isdigit():
            output.append(int(item))
        else:
            output.append(item)
    return output


def _copy_policy_ir(policy_ir: PolicyIR) -> PolicyIR:
    return PolicyIR(
        nodes=list(policy_ir.nodes),
        pools={key: list(value) for key, value in policy_ir.pools.items()},
        business_groups=list(policy_ir.business_groups),
        rule_lines=list(policy_ir.rule_lines),
        default_group_name=policy_ir.default_group_name,
        default_contract_id=policy_ir.default_contract_id,
        device_strategy_preset=policy_ir.device_strategy_preset,
        metadata=dict(policy_ir.metadata),
        rule_entries=list(policy_ir.rule_entries),
        contracts=list(policy_ir.contracts),
        catalog_bindings=list(policy_ir.catalog_bindings),
        general_profile=policy_ir.general_profile,
        dns=dict(policy_ir.dns),
        tun=dict(policy_ir.tun),
        sniffer=dict(policy_ir.sniffer),
        http_processing=dict(policy_ir.http_processing),
        rule_providers={key: dict(value) for key, value in policy_ir.rule_providers.items()},
        process_rules=list(policy_ir.process_rules),
        external_proxy_programs=list(policy_ir.external_proxy_programs),
        warnings=list(policy_ir.warnings),
    )


def _version_floor(current: object, minimum: str) -> str:
    text = str(current or "")
    parts = re.findall(r"\d+", text)
    required = tuple(int(part) for part in minimum.split("."))
    return text if len(parts) >= 3 and tuple(int(part) for part in parts[:3]) >= required else minimum


def _enrich_policy_ir_for_target(
    policy_ir: PolicyIR,
    *,
    target: str,
    profile: str,
    normalized_settings: Mapping[str, object],
) -> PolicyIR:
    ir = _copy_policy_ir(policy_ir)
    metadata = dict(ir.metadata)
    version_constraints = dict(metadata.get("version_constraints") or {})
    if target == "clash":
        version_constraints["mihomo"] = _version_floor(version_constraints.get("mihomo"), "1.19.28")
        metadata["version_constraints"] = version_constraints
        if profile in {"lazycat", "raw"}:
            clash_dns_enhanced_mode = str(
                normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_ENHANCED_MODE_KEY, "") or ""
            ).strip()
            clash_fake_ip_filter_mode = str(
                normalized_settings.get(
                    LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_FILTER_MODE_KEY,
                    "",
                )
                or ""
            ).strip()
            ir.metadata = metadata
            ir.metadata["profile"] = {
                "store-selected": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_PROFILE_STORE_SELECTED_KEY, False)
                ),
                "store-fake-ip": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_PROFILE_STORE_FAKE_IP_KEY, False)
                ),
            }
            ir.metadata["control"] = {
                "external-controller": str(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_EXTERNAL_CONTROLLER_KEY, "") or ""
                ).strip(),
                "secret": str(normalized_settings.get(LAZYCAT_PROFILE_CLASH_SECRET_KEY, "") or "").strip(),
                "external-ui": str(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_KEY, "") or ""
                ).strip(),
                "external-ui-name": str(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_NAME_KEY, "") or ""
                ).strip(),
                "external-ui-url": str(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_EXTERNAL_UI_URL_KEY, "") or ""
                ).strip(),
            }
            ir.dns = {
                "enable": bool(normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_ENABLE_KEY, False)),
                "listen": str(normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_LISTEN_KEY, "") or "").strip(),
                "enhanced-mode": clash_dns_enhanced_mode,
                "default-nameserver": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY, [])
                ),
                "nameserver": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY, [])
                ),
                "fallback": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_FALLBACK_KEY, [])
                ),
                "nameserver-policy": dict(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_POLICY_KEY, {}) or {}
                ),
                "respect-rules": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_RESPECT_RULES_KEY, False)
                ),
                "proxy-server-nameserver": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY, [])
                ),
                "direct-nameserver": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_DIRECT_NAMESERVER_KEY, [])
                ),
            }
            if clash_dns_enhanced_mode == "fake-ip":
                ir.dns["fake-ip-range"] = str(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_FAKE_IP_RANGE_KEY, "") or ""
                ).strip()
                ir.dns["fake-ip-filter-mode"] = clash_fake_ip_filter_mode
                ir.dns["fake-ip-filter"] = _render_clash_fake_ip_filter_entries(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_FAKE_IP_FILTER_KEY, []),
                    mode=clash_fake_ip_filter_mode,
                )
            if clash_dns_enhanced_mode == "redir-host":
                ir.dns["use-hosts"] = bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_DNS_USE_HOSTS_KEY, False)
                )
            ir.tun = {
                "enable": bool(normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_ENABLE_KEY, False)),
                "stack": str(normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_STACK_KEY, "") or "").strip(),
                "auto-route": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_AUTO_ROUTE_KEY, False)
                ),
                "auto-detect-interface": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_AUTO_DETECT_INTERFACE_KEY, False)
                ),
                "dns-hijack": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_DNS_HIJACK_KEY, [])
                ),
                "strict-route": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_STRICT_ROUTE_KEY, False)
                ),
                "route-exclude-address": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY, [])
                ),
                "route-address": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_INCLUDE_ROUTES_KEY, [])
                ),
                "include-uid": _profile_uid_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_INCLUDE_UID_KEY, [])
                ),
                "exclude-uid": _profile_uid_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_EXCLUDE_UID_KEY, [])
                ),
                "include-package": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_INCLUDE_PACKAGE_KEY, [])
                ),
                "exclude-package": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_TUN_EXCLUDE_PACKAGE_KEY, [])
                ),
            }
            ir.sniffer = {
                "enable": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_ENABLE_KEY, False)
                ),
                "force-dns-mapping": bool(
                    normalized_settings.get(
                        LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DNS_MAPPING_KEY,
                        False,
                    )
                ),
                "parse-pure-ip": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_PARSE_PURE_IP_KEY, False)
                ),
                "override-destination": bool(
                    normalized_settings.get(
                        LAZYCAT_PROFILE_CLASH_SNIFFER_OVERRIDE_DESTINATION_KEY,
                        False,
                    )
                ),
                "sniff": {
                    "http": {"ports": _profile_ports(
                        normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_HTTP_PORTS_KEY, [])
                    )},
                    "tls": {"ports": _profile_ports(
                        normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_TLS_PORTS_KEY, [])
                    )},
                    "quic": {"ports": _profile_ports(
                        normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_QUIC_PORTS_KEY, [])
                    )},
                },
                "force-domain": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_FORCE_DOMAIN_KEY, [])
                ),
                "skip-domain": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_SKIP_DOMAIN_KEY, [])
                ),
                "skip-src-address": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_SKIP_SRC_ADDRESS_KEY, [])
                ),
                "skip-dst-address": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_CLASH_SNIFFER_SKIP_DST_ADDRESS_KEY, [])
                ),
            }
            # Intent-level decomposition: Surge skip-proxy → Mihomo DNS/TUN/Rules
            surge_skip_proxy = _profile_list(
                normalized_settings.get(LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY, [])
            )
            if surge_skip_proxy:
                decomp = decompose_skip_proxy(surge_skip_proxy)
                if decomp.fake_ip_filter_entries and clash_dns_enhanced_mode == "fake-ip":
                    existing_filter = list(ir.dns.get("fake-ip-filter") or [])
                    existing_set = set(existing_filter)
                    for entry in _render_clash_fake_ip_filter_entries(
                        decomp.fake_ip_filter_entries,
                        mode=clash_fake_ip_filter_mode,
                    ):
                        if entry not in existing_set:
                            existing_filter.append(entry)
                            existing_set.add(entry)
                    ir.dns["fake-ip-filter"] = existing_filter
                if decomp.route_exclude_entries:
                    existing_routes = list(ir.tun.get("route-exclude-address") or [])
                    existing_set = set(existing_routes)
                    for entry in decomp.route_exclude_entries:
                        if entry not in existing_set:
                            existing_routes.append(entry)
                            existing_set.add(entry)
                    ir.tun["route-exclude-address"] = existing_routes
                if decomp.direct_rules:
                    ir.skip_proxy_direct_rules = decomp.direct_rules
        return ir

    if target == "surge":
        surge_versions = dict(version_constraints.get("surge") or {})
        surge_versions["min_ios"] = _version_floor(surge_versions.get("min_ios"), "5.23.0")
        surge_versions["min_macos"] = _version_floor(surge_versions.get("min_macos"), "6.0.0")
        version_constraints["surge"] = surge_versions
        metadata["version_constraints"] = version_constraints
        ir.metadata = metadata
        ir.http_processing = {
            **dict(ir.http_processing or {}),
            "group-timeout": int(
                normalized_settings.get(LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TIMEOUT_KEY, 5) or 5
            ),
            "group-tolerance": int(
                normalized_settings.get(LAZYCAT_PROFILE_SURGE_PROXY_GROUP_TOLERANCE_KEY, 50) or 50
            ),
        }
        if profile == "lazycat":
            ir.dns = {
                "dns-server": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_DNS_SERVER_KEY, [])
                ),
                "encrypted-dns-server": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_ENCRYPTED_DNS_SERVER_KEY, [])
                ),
                "encrypted-dns-follow-outbound-mode": bool(
                    normalized_settings.get(
                        LAZYCAT_PROFILE_SURGE_ENCRYPTED_DNS_FOLLOW_OUTBOUND_MODE_KEY,
                        False,
                    )
                ),
                "host-records": dict(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_HOST_RECORDS_KEY, {}) or {}
                ),
                "loglevel": str(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_LOGLEVEL_KEY, "") or ""
                ).strip(),
                "block-quic": str(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_BLOCK_QUIC_KEY, "") or ""
                ).strip(),
                "http-api-tls": bool(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_HTTP_API_TLS_KEY, False)
                ),
                "http-api-web-dashboard": bool(
                    normalized_settings.get(
                        LAZYCAT_PROFILE_SURGE_HTTP_API_WEB_DASHBOARD_KEY,
                        False,
                    )
                ),
            }
            ir.http_processing = {
                **dict(ir.http_processing or {}),
                "mitm": {
                    "hostname": _profile_list(
                        normalized_settings.get(LAZYCAT_PROFILE_SURGE_MITM_HOSTNAME_KEY, [])
                    ),
                    "skip-server-cert-verify": bool(
                        normalized_settings.get(
                            LAZYCAT_PROFILE_SURGE_MITM_SKIP_SERVER_CERT_VERIFY_KEY,
                            False,
                        )
                    ),
                    "h2": bool(
                        normalized_settings.get(LAZYCAT_PROFILE_SURGE_MITM_H2_KEY, False)
                    ),
                    "tcp-connection": bool(
                        normalized_settings.get(
                            LAZYCAT_PROFILE_SURGE_MITM_TCP_CONNECTION_KEY,
                            False,
                        )
                    ),
                },
                "url-rewrite": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_URL_REWRITE_KEY, [])
                ),
                "header-rewrite": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_HEADER_REWRITE_KEY, [])
                ),
                "body-rewrite": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_BODY_REWRITE_KEY, [])
                ),
                "jq-body-rewrite": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_JQ_BODY_REWRITE_KEY, [])
                ),
                "map-local": _profile_list(
                    normalized_settings.get(LAZYCAT_PROFILE_SURGE_MAP_LOCAL_KEY, [])
                ),
            }
        return ir

    return ir


def resolve_clash_provider_quality_group(provider_key: str) -> str | None:
    return CLASH_PROVIDER_GROUP_BY_KEY.get(str(provider_key or "").strip())


def _clash_provider_key(group_name: str) -> str:
    return CLASH_PROVIDER_KEY_BY_GROUP[group_name]


def _clash_provider_revision(provider_key: str, provider_proxies: list[dict[str, Any]]) -> str:
    payload = {
        "provider_key": provider_key,
        "proxies": provider_proxies,
    }
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _clash_provider_url(base_url: str, subscription_id: str, provider_key: str, revision: str = "") -> str:
    normalized_base = str(base_url or "").strip().rstrip("/") or "http://127.0.0.1"
    normalized_subscription_id = str(subscription_id or "default").strip() or "default"
    url = f"{normalized_base}/sub/device/{normalized_subscription_id}/clash/providers/{provider_key}.yaml"
    normalized_revision = str(revision or "").strip()
    if normalized_revision:
        return f"{url}?rev={quote(normalized_revision, safe='')}"
    return url


def _clash_provider_cache_path(token: str, provider_key: str, revision: str = "") -> str:
    token_hash = hashlib.sha1(str(token or "default").encode("utf-8")).hexdigest()[:12]
    return f"./providers/subhub-{token_hash}-{provider_key}.yaml"


def _clash_provider_export_path(provider_key: str) -> str:
    return f"./providers/{provider_key}.yaml"


def _build_clash_provider_proxies(
    nodes: list[NodeRecord],
    *,
    udp_default_enabled: bool = True,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    payloads: list[dict[str, Any]] = []
    name_keys: list[str] = []
    skipped: list[str] = []
    for node in nodes:
        payload = _clash_proxy(node, udp_default_enabled=udp_default_enabled)
        if not payload:
            skipped.append(node.name)
            continue
        payloads.append(payload)
        name_keys.append(node.dedupe_key())
    if not payloads:
        return [], skipped, {}
    names = _uniqueify_names([str(item.get("name", "")) for item in payloads], _RESERVED_PROXY_NAMES)
    name_map: dict[str, str] = {}
    for index, new_name in enumerate(names):
        payloads[index]["name"] = new_name
        name_map[name_keys[index]] = new_name
    return payloads, skipped, name_map


_DEFAULT_GROUP_NAME = "兜底代理"
_SURGE_DEFAULT_GROUP_NAME = "兜底代理"
_CHAIN_INGRESS_GROUP_NAME = "链式入口·自动"
_SMART_REQUIREMENT = "CORE_VERSION>=22"
_POOL_ORDER_BY_PRESET: dict[str, list[str]] = {
    DEVICE_STRATEGY_PRESET_BALANCED: [
        QUALITY_HIGH_STANDARD,
        QUALITY_MEDIUM,
        QUALITY_BULK,
        QUALITY_HIGH_PREMIUM,
    ],
    DEVICE_STRATEGY_PRESET_CHEAP: [
        QUALITY_MEDIUM,
        QUALITY_BULK,
        QUALITY_HIGH_STANDARD,
        QUALITY_HIGH_PREMIUM,
    ],
    DEVICE_STRATEGY_PRESET_REALTIME: [
        QUALITY_HIGH_PREMIUM,
        QUALITY_HIGH_STANDARD,
        QUALITY_MEDIUM,
        QUALITY_BULK,
    ],
    DEVICE_STRATEGY_PRESET_STREAMING: [
        QUALITY_HIGH_PREMIUM,
        QUALITY_HIGH_STANDARD,
        QUALITY_MEDIUM,
        QUALITY_BULK,
    ],
    DEVICE_STRATEGY_PRESET_MOBILE: [
        QUALITY_MEDIUM,
        QUALITY_HIGH_STANDARD,
        QUALITY_BULK,
        QUALITY_HIGH_PREMIUM,
    ],
}


def _clash_front_name_map(
    grouped_nodes: dict[str, list[NodeRecord]],
    *,
    udp_default_enabled: bool,
) -> dict[str, str]:
    front_name_by_key: dict[str, str] = {}
    for group in (QUALITY_HIGH_PREMIUM, QUALITY_HIGH_STANDARD, QUALITY_MEDIUM, QUALITY_BULK):
        _, _, name_map = _build_clash_provider_proxies(
            grouped_nodes[group],
            udp_default_enabled=udp_default_enabled,
        )
        front_name_by_key.update(name_map)
    return front_name_by_key


def _inline_front_name_map(
    grouped_nodes: dict[str, list[NodeRecord]],
    *,
    client: str,
) -> dict[str, str]:
    if client == "surge":
        used_names: set[str] = set(_RESERVED_PROXY_NAMES) | {_SURGE_DEFAULT_GROUP_NAME}
        payload_builder = _surge_proxy_payload
    else:
        used_names = set(_RESERVED_PROXY_NAMES)
        payload_builder = _shadowrocket_proxy_payload

    front_name_by_key: dict[str, str] = {}
    for group in (QUALITY_HIGH_PREMIUM, QUALITY_HIGH_STANDARD, QUALITY_MEDIUM, QUALITY_BULK):
        nodes_to_name: list[NodeRecord] = []
        names: list[str] = []
        for node in grouped_nodes[group]:
            if payload_builder(node) is None:
                continue
            nodes_to_name.append(node)
            names.append(_safe_name(node.name))
        for node, rendered_name in zip(nodes_to_name, _uniqueify_names(names, used_names)):
            front_name_by_key[node.dedupe_key()] = rendered_name
            used_names.add(rendered_name)
    return front_name_by_key


def _normalize_strategy_preset(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in DEVICE_STRATEGY_PRESETS else DEVICE_STRATEGY_PRESET_BALANCED


def _pool_order_for_preset(preset: str) -> list[str]:
    normalized = _normalize_strategy_preset(preset)
    return list(_POOL_ORDER_BY_PRESET[normalized])


def _pool_mode_names(pool_name: str) -> dict[str, str]:
    return {
        "auto": f"{pool_name}·自动",
    }


def _legacy_quality_pool_name(value: object) -> str:
    """Adapt the explicit pool contract to the renderer's legacy group names."""
    text = str(value or "").strip()
    if text in QUALITY_GROUPS:
        return text
    return contract_legacy_group(normalize_contract_id(text))


_COUNTRY_ROUTED_QUALITY_GROUPS = {QUALITY_MEDIUM, QUALITY_BULK}
_ENTRY_GROUP_ORDER = {
    QUALITY_HIGH_PREMIUM: 0,
    QUALITY_HIGH_STANDARD: 1,
    QUALITY_MEDIUM: 2,
    QUALITY_BULK: 3,
    QUALITY_CHAIN_HOME: 4,
    _DEFAULT_GROUP_NAME: 5,
    _SURGE_DEFAULT_GROUP_NAME: 5,
    contract_display_name(CONTRACT_DIRECT): 6,
    contract_display_name(CONTRACT_AD_BLOCK): 7,
}


def _country_buckets(nodes: list[NodeRecord]) -> dict[str, list[NodeRecord]]:
    buckets: dict[str, list[NodeRecord]] = {}
    for node in nodes:
        country = _detect_node_country(node.name)
        buckets.setdefault(country, []).append(node)
    return buckets


def _business_group_sort_key(group: BusinessGroup) -> tuple[int, int, str]:
    display_name = _business_group_display_name(group.name)
    return (_ENTRY_GROUP_ORDER.get(display_name, 99), group.sort_order, display_name)


def _ordered_business_groups(policy_ir: PolicyIR) -> list[BusinessGroup]:
    return sorted(policy_ir.business_groups, key=_business_group_sort_key)


def _business_group_display_name(name: str) -> str:
    text = str(name or "").strip()
    return text or _DEFAULT_GROUP_NAME


def _default_contract(policy_ir: PolicyIR) -> RouteContract | None:
    normalized = normalize_contract_id(policy_ir.default_contract_id)
    if not normalized:
        return None
    for contract in policy_ir.contracts:
        if contract.id == normalized and bool(contract.enabled):
            return contract
    return None


def _contract_by_id(policy_ir: PolicyIR, contract_id: object) -> RouteContract | None:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return None
    return next((item for item in policy_ir.contracts if item.id == normalized), None)


def _route_action(contract: RouteContract | None) -> str:
    if contract is None:
        return ROUTE_ACTION_PROXY
    return normalize_route_action(getattr(contract, "routing_action", ROUTE_ACTION_PROXY))


def _route_action_for_target(policy_ir: PolicyIR, contract_id: object) -> str:
    normalized = normalize_contract_id(contract_id)
    if normalized == ROUTE_DIRECT_ACTION:
        return ROUTE_ACTION_DIRECT
    if normalized == ROUTE_REJECT_ACTION:
        return ROUTE_ACTION_REJECT
    contract = _contract_by_id(policy_ir, normalized)
    if contract is not None:
        return _route_action(contract)
    # Legacy helper callers represented protocol targets with the historical
    # IDs.  Keep those inputs readable only when no explicit contract catalog
    # was supplied; once a catalog is explicit, a missing ID is a real broken
    # reference and must fail closed.
    if not _is_contracts_explicit(policy_ir):
        if normalized == CONTRACT_DIRECT:
            return ROUTE_ACTION_DIRECT
        if normalized == CONTRACT_AD_BLOCK:
            return ROUTE_ACTION_REJECT
    return ROUTE_ACTION_PROXY


def _contract_target_name(
    policy_ir: PolicyIR,
    contract_id: object,
    *,
    client: str = "",
) -> str:
    normalized = normalize_contract_id(contract_id)
    if _is_native_rule_target(contract_id, client=client or "shadowrocket"):
        return str(contract_id)
    contract = _contract_by_id(policy_ir, normalized)
    # A disabled persisted contract is an unavailable target.  Keep primitive
    # actions available even when no corresponding record exists.
    if contract is not None and not bool(contract.enabled):
        return QUALITY_REJECT
    action = _route_action_for_target(policy_ir, normalized)
    if action == ROUTE_ACTION_DIRECT:
        return "DIRECT"
    if action == ROUTE_ACTION_REJECT:
        return QUALITY_REJECT
    display_name = str(contract.display_name or "").strip() if contract else ""
    return display_name or contract_display_name(normalized)


def _is_contracts_explicit(policy_ir: PolicyIR) -> bool:
    return bool(dict(policy_ir.metadata or {}).get("contracts_explicit"))


def _split_rule_parts(line: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(line):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(line[start:index].strip())
            start = index + 1
    parts.append(line[start:].strip())
    return parts


def _parse_rule_target(line: str) -> str:
    parts = _split_rule_parts(str(line or ""))
    if len(parts) >= 3:
        return parts[2]
    return ""


def _default_business_groups_from_rules(
    rule_lines: list[str],
    preset: str,
) -> list[BusinessGroup]:
    target_to_pools: dict[str, set[str]] = {}
    for group in QUALITY_GROUPS:
        target_to_pools[group] = {group}
    for line in rule_lines:
        target = _parse_rule_target(line)
        if not target or target in {"DIRECT", QUALITY_REJECT} or target.startswith("REJECT-"):
            continue
        pools = target_to_pools.setdefault(target, set())
        if target in QUALITY_GROUPS:
            pools.add(target)
            continue
        # Legacy rule lines carry a quality-group target, not a pool contract.
        # Only the known legacy values can be translated here.  Custom groups
        # must arrive with an explicit BusinessGroup.pool_names contract;
        # guessing from the display name changes routing semantics.

    items: list[BusinessGroup] = []
    for index, (name, pools) in enumerate(target_to_pools.items()):
        items.append(
            BusinessGroup(
                name=name,
                sort_order=index,
                pool_names=[pool for pool in _pool_order_for_preset(preset) if pool in pools],
                created_by_system=True,
            )
        )
    return items


def build_policy_ir(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    *,
    rule_entries: list[PolicyRuleEntry] | None = None,
    business_groups: list[BusinessGroup] | None = None,
    device_strategy_preset: str = DEVICE_STRATEGY_PRESET_BALANCED,
    contracts: list[RouteContract] | None = None,
    catalog_bindings: list[ServiceCatalogEntry] | None = None,
    general_profile: GeneralProfile | None = None,
    process_rules: list[ProcessRuleTemplate] | None = None,
    external_proxy_programs: list[ExternalProxyProgramTemplate] | None = None,
    default_group_name: str = _DEFAULT_GROUP_NAME,
    default_contract_id: str = "",
) -> PolicyIR:
    preset = _normalize_strategy_preset(device_strategy_preset)
    grouped_nodes = _group_nodes(nodes)
    pools: dict[str, list[str]] = {
        group: [item.name for item in grouped_nodes[group]]
        for group in QUALITY_GROUPS
    }
    contracts_explicit = contracts is not None
    # A non-empty contract catalog still needs compatibility business groups
    # when callers use this helper directly.  An explicitly empty catalog is
    # different: it must not synthesize the historical route topology.
    groups = list(
        business_groups
        if business_groups is not None
        else (
            _default_business_groups_from_rules(rule_lines, preset)
            if contracts is None or bool(contracts)
            else []
        )
    )
    seen_names = {item.name for item in groups}
    if contracts is None or bool(contracts):
        for group_name in QUALITY_GROUPS:
            if group_name not in seen_names:
                groups.append(
                    BusinessGroup(
                        name=group_name,
                        sort_order=len(groups),
                        pool_names=[group_name],
                        created_by_system=True,
                    )
                )
    if default_group_name not in seen_names:
        groups.append(
            BusinessGroup(
                name=default_group_name,
                sort_order=len(groups),
                pool_names=[QUALITY_CHAIN_HOME] if contracts is None else [],
                created_by_system=True,
            )
        )
    normalized_default_contract_id = normalize_contract_id(default_contract_id)
    if contracts_explicit:
        contract_ids = {str(item.id or "").strip() for item in list(contracts or [])}
        if (
            normalized_default_contract_id not in contract_ids
            and normalized_default_contract_id not in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}
        ):
            normalized_default_contract_id = ""
    elif not normalized_default_contract_id:
        normalized_default_contract_id = CONTRACT_CHAIN_HOME
    return PolicyIR(
        nodes=list(nodes),
        pools=pools,
        business_groups=groups,
        rule_lines=list(rule_lines),
        default_group_name=default_group_name,
        default_contract_id=normalized_default_contract_id,
        device_strategy_preset=preset,
        rule_entries=list(rule_entries or []),
        contracts=list(contracts or []),
        catalog_bindings=list(catalog_bindings or []),
        general_profile=general_profile,
        process_rules=list(process_rules or []),
        external_proxy_programs=list(external_proxy_programs or []),
        metadata={"contracts_explicit": contracts_explicit},
        warnings=[],
    )


def _build_business_group_members(policy_ir: PolicyIR, group: BusinessGroup) -> list[str]:
    preset_order = _pool_order_for_preset(policy_ir.device_strategy_preset)
    requested_pools = [
        pool_name
        for pool_name in (_legacy_quality_pool_name(item) for item in (group.pool_names or []))
        if pool_name
    ]
    ordered_pools = [pool for pool in preset_order if pool in requested_pools]
    members: list[str] = []
    for pool_name in ordered_pools:
        names = _pool_mode_names(pool_name)
        members.append(names["auto"])
    if group.name == policy_ir.default_group_name:
        members.append("DIRECT")
    elif members:
        members.append("DIRECT")
    else:
        # An unbound business group must fail closed.  In particular, do not
        # infer pools from its display name or silently turn it into DIRECT.
        members.append(QUALITY_REJECT)
    return members


def _route_contract_for_group(policy_ir: PolicyIR, group: BusinessGroup) -> RouteContract | None:
    display_name = _business_group_display_name(group.name)
    for contract in policy_ir.contracts:
        if display_name == contract.display_name:
            return contract
    return None


def _contract_group_type(contract: RouteContract | None) -> str:
    if not contract:
        return "select"
    if _route_action(contract) in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT}:
        return "select"
    if contract.strategy_type == CONTRACT_STRATEGY_LOAD_BALANCE:
        return "load-balance"
    return "fallback"


def _terminal_member_for_contract(contract: RouteContract | None) -> str:
    if not contract:
        return "DIRECT"
    if _route_action(contract) == ROUTE_ACTION_DIRECT:
        return "DIRECT"
    if _route_action(contract) == ROUTE_ACTION_REJECT:
        return QUALITY_REJECT
    if contract.failure_action == CONTRACT_FAILURE_DIRECT:
        return "DIRECT"
    return QUALITY_REJECT


def _contract_members(policy_ir: PolicyIR, contract: RouteContract, *, client: str) -> list[str]:
    action = _route_action(contract)
    if not bool(contract.enabled):
        return ["REJECT-DROP", QUALITY_REJECT] if client == "surge" else [QUALITY_REJECT]
    if action == ROUTE_ACTION_DIRECT:
        return ["DIRECT"]
    if action == ROUTE_ACTION_REJECT:
        return ["REJECT-DROP", QUALITY_REJECT, "DIRECT"] if client == "surge" else [QUALITY_REJECT]

    mode_key = "auto"
    members: list[str] = []

    def _append_pool_members(pool_ids: list[str]) -> None:
        for pool_id in pool_ids:
            legacy_group = contract_legacy_group(pool_id)
            if legacy_group not in QUALITY_GROUPS:
                continue
            helper_name = _pool_mode_names(legacy_group)[mode_key]
            if helper_name not in members:
                members.append(helper_name)

    _append_pool_members(list(contract.primary_pools or []))
    if contract.strategy_type == CONTRACT_STRATEGY_FAILOVER:
        _append_pool_members(list(contract.fallback_pools or []))
    elif contract.failure_action == CONTRACT_FAILURE_DEGRADE:
        _append_pool_members(list(contract.fallback_pools or []))

    terminal = _terminal_member_for_contract(contract)
    if terminal not in members:
        members.append(terminal)
    return members


def _business_group_members(policy_ir: PolicyIR, group: BusinessGroup, *, client: str) -> list[str]:
    if group.name == policy_ir.default_group_name:
        default_contract = _default_contract(policy_ir)
        if default_contract:
            return _contract_members(policy_ir, default_contract, client=client)
        default_id = normalize_contract_id(policy_ir.default_contract_id)
        persisted_default = _contract_by_id(policy_ir, default_id)
        default_action = (
            _route_action_for_target(policy_ir, default_id)
            if default_id in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}
            or (persisted_default is not None and bool(persisted_default.enabled))
            else ""
        )
        if default_action == ROUTE_ACTION_DIRECT:
            return ["DIRECT"]
        if default_action == ROUTE_ACTION_REJECT:
            return ["REJECT-DROP", QUALITY_REJECT, "DIRECT"] if client == "surge" else [QUALITY_REJECT]
        if _is_contracts_explicit(policy_ir):
            return ["REJECT-DROP", QUALITY_REJECT] if client == "surge" else [QUALITY_REJECT]
    contract = _route_contract_for_group(policy_ir, group)
    if contract:
        return _contract_members(policy_ir, contract, client=client)
    if group.mode == BUSINESS_GROUP_MODE_AD_BLOCK:
        return ["REJECT-DROP", QUALITY_REJECT, "DIRECT"] if client == "surge" else [QUALITY_REJECT]
    if _is_contracts_explicit(policy_ir):
        return ["REJECT-DROP", QUALITY_REJECT] if client == "surge" else [QUALITY_REJECT]
    return _build_business_group_members(policy_ir, group)


def _chain_ingress_members(
    *,
    available_medium: bool,
    available_bulk: bool,
    mode_key: str,
) -> list[str]:
    members: list[str] = []
    if available_medium:
        members.append(_pool_mode_names(QUALITY_MEDIUM)[mode_key])
    if available_bulk:
        members.append(_pool_mode_names(QUALITY_BULK)[mode_key])
    return members


def _referenced_helper_group_names(
    policy_ir: PolicyIR,
    *,
    client: str,
    available_pools: set[str],
    has_chain_nodes: bool,
) -> set[str]:
    referenced: set[str] = set()
    known_helper_names: set[str] = {
        _CHAIN_INGRESS_GROUP_NAME,
    }
    for pool_name in QUALITY_GROUPS:
        known_helper_names.update(_pool_mode_names(pool_name).values())

    for group in _ordered_business_groups(policy_ir):
        if group.mode == BUSINESS_GROUP_MODE_AD_BLOCK:
            continue
        referenced.update(_business_group_members(policy_ir, group, client=client))

    if has_chain_nodes:
        referenced.add(_CHAIN_INGRESS_GROUP_NAME)
        if QUALITY_MEDIUM in available_pools:
            referenced.add(_pool_mode_names(QUALITY_MEDIUM)["auto"])
        if QUALITY_BULK in available_pools:
            referenced.add(_pool_mode_names(QUALITY_BULK)["auto"])

    return referenced & known_helper_names


def _referenced_pool_mode_keys(referenced_helper_names: set[str], pool_name: str) -> set[str]:
    mode_names = _pool_mode_names(pool_name)
    return {
        mode_key
        for mode_key, helper_name in mode_names.items()
        if helper_name in referenced_helper_names
    }


def _business_group_mode_map(policy_ir: PolicyIR) -> dict[str, str]:
    return {
        _business_group_display_name(group.name): str(group.mode or "").strip()
        or BUSINESS_GROUP_MODE_STANDARD
        for group in policy_ir.business_groups
    }


def _lower_rule_target_for_client(
    target: str,
    *,
    policy_ir: PolicyIR,
    client: str,
    contract_id: object = "",
) -> str:
    if client not in {"clash", "shadowrocket"}:
        return target
    if contract_id:
        contract = _contract_by_id(policy_ir, contract_id)
        if contract is not None and not bool(contract.enabled):
            return QUALITY_REJECT
        action = _route_action_for_target(policy_ir, contract_id)
        if action == ROUTE_ACTION_DIRECT:
            return "DIRECT"
        if action == ROUTE_ACTION_REJECT:
            return QUALITY_REJECT
        if contract is not None:
            # An explicit proxy contract owns its action, including when its
            # display name happens to match a historical action/group label.
            return target
    normalized_target = str(target or "").strip()
    if normalized_target in {
        QUALITY_REJECT,
        contract_display_name(CONTRACT_AD_BLOCK),
        contract_display_name(ROUTE_REJECT_ACTION),
    }:
        return QUALITY_REJECT
    mode = _business_group_mode_map(policy_ir).get(normalized_target, "")
    if mode == BUSINESS_GROUP_MODE_AD_BLOCK:
        return QUALITY_REJECT
    return target


def _lower_rule_condition(
    rule_type: str,
    value: str,
    extras: list[str],
    *,
    client: str,
    supported: set[str] | None,
) -> tuple[str, str, list[str]]:
    """Translate predicates structurally; never rewrite text inside regex values."""
    original_type = rule_type
    # DeviceSubscription has no trusted target OS. Neither a device label nor
    # the server OS proves that the consumer supports Linux/Android UID rules.
    if rule_type == "UID":
        raise ValueError("UID requires a verified Linux/Android target; target OS is unknown")
    mapping = {"DEST-PORT": "DST-PORT", "PROTOCOL": "NETWORK"} if client == "clash" else {"DST-PORT": "DEST-PORT"}
    if client == "surge":
        mapping["NETWORK"] = "PROTOCOL"
    rule_type = mapping.get(rule_type, rule_type)
    if supported is not None and rule_type not in supported:
        raise ValueError(f"unsupported condition {original_type}")
    if original_type in {"NETWORK", "PROTOCOL"} and original_type != rule_type:
        if value.upper() not in {"TCP", "UDP"}:
            raise ValueError(f"no equivalent condition for {original_type},{value}")
        value = value.upper()
    if rule_type in {"AND", "OR", "NOT"}:
        children_text = value[1:-1] if value.startswith("((") and value.endswith("))") else value
        children = _split_rule_parts(children_text)
        if not children or (rule_type == "NOT" and len(children) != 1):
            raise ValueError("invalid logical condition")
        rendered_children: list[str] = []
        for child in children:
            if not child.startswith("(") or not child.endswith(")"):
                raise ValueError("logical condition must be parenthesized")
            parts = _split_rule_parts(child[1:-1])
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise ValueError("empty logical condition")
            child_type, child_value, child_extras = _lower_rule_condition(
                parts[0], parts[1], parts[2:], client=client, supported=supported,
            )
            rendered_children.append("(" + ",".join([child_type, child_value, *child_extras]) + ")")
        value = "(" + ",".join(rendered_children) + ")"
    return rule_type, value, list(extras)


def _lower_policy_entries_for_client(
    entries: list[PolicyRuleEntry], *, client: str,
) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
    lowered: list[PolicyRuleEntry] = []
    warnings: list[RenderWarning] = []
    surge_types = {
        "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD", "DOMAIN-SET", "RULE-SET",
        "IP-CIDR", "IP-CIDR6", "IP-ASN", "GEOIP", "DEST-PORT", "PROTOCOL", "USER-AGENT",
        "URL-REGEX", "SUBNET", "HOSTNAME-TYPE", "AND", "OR", "NOT", *_SURGE_MAC_ONLY_RULE_TYPES,
    }
    supported = surge_types if client == "surge" else _CLASH_KNOWN_RULE_TYPES if client == "clash" else None
    for entry in entries:
        try:
            rule_type, value, extras = _lower_rule_condition(
                entry.rule_type, entry.value, entry.extras, client=client, supported=supported,
            )
        except ValueError as error:
            warnings.append(RenderWarning(
                code=f"{client}-rule-unsupported",
                message=(f"Dropped {client} rule {entry.rule_type},{entry.value}: {error}; "
                         "routing condition cannot be represented. Stored rules are unchanged; "
                         "migrate to a supported condition or remove the stored rule."),
                target=entry.value, severity="warning", bucket="refused",
            ))
            continue
        target = entry.target_contract_id
        if _is_native_rule_target(target, client="shadowrocket") and not _is_native_rule_target(target, client=client):
            warnings.append(RenderWarning(
                code=f"{client}-reject-downgraded",
                message=f"{target} mapped to REJECT; HTTP placeholder response is unavailable",
                target=target, severity="warning", bucket="downgraded",
            ))
            target = "REJECT"
        lowered.append(replace(entry, rule_type=rule_type, value=value, target_contract_id=target, extras=extras))
    return lowered, warnings


def _client_rule_lines(
    policy_ir: PolicyIR,
    *,
    client: str,
    compiled_entries: list[PolicyRuleEntry] | None = None,
) -> list[str]:
    entries = compiled_entries if compiled_entries is not None else _compiled_policy_rule_entries(policy_ir)[0]
    entries, _ = _lower_policy_entries_for_client(entries, client=client)
    lowered: list[str] = []
    for entry in entries:
        target = _lower_rule_target_for_client(
            _contract_target_name(policy_ir, entry.target_contract_id, client=client),
            policy_ir=policy_ir,
            client=client,
            contract_id=entry.target_contract_id,
        )
        lowered.append(entry.to_line(target_name=target))
    return lowered


def _rule_lines_with_default(
    policy_ir: PolicyIR,
    *,
    client: str = "clash",
    compiled_entries: list[PolicyRuleEntry] | None = None,
) -> list[str]:
    return _client_rule_lines(policy_ir, client=client, compiled_entries=compiled_entries) + [
        f"MATCH,{policy_ir.default_group_name}"
    ]


def _final_rule_lines_with_default(
    policy_ir: PolicyIR,
    *,
    client: str,
    compiled_entries: list[PolicyRuleEntry] | None = None,
) -> list[str]:
    return _client_rule_lines(policy_ir, client=client, compiled_entries=compiled_entries) + [
        f"FINAL,{policy_ir.default_group_name}"
    ]


def _surge_rule_lines_with_default(policy_ir: PolicyIR) -> list[str]:
    return _final_rule_lines_with_default(policy_ir, client="surge")


_CLASH_KNOWN_RULE_TYPES = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "DOMAIN-WILDCARD",
    "DOMAIN-REGEX",
    "IP-CIDR",
    "IP-CIDR6",
    "IP-SUFFIX",
    "IP-ASN",
    "SRC-IP-CIDR",
    "GEOIP",
    "GEOSITE",
    "DST-PORT",
    "SRC-PORT",
    "IN-PORT",
    "IN-TYPE",
    "IN-NAME",
    "IN-USER",
    "PROCESS-NAME",
    "PROCESS-PATH",
    "NETWORK",
    "DSCP",
    "RULE-SET",
    "SUB-RULE",
    "AND",
    "OR",
    "NOT",
    "MATCH",
}
_CLASH_COMPLEX_RULE_TYPES = {"AND", "OR", "NOT"}
_SURGE_DOMAIN_RULE_TYPES = {"DOMAIN", "DOMAIN-SUFFIX"}
_SURGE_CIDR_RULE_TYPES = {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"}
_SURGE_IP_RULE_TYPES = {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR", "GEOIP", "IP-ASN"}
_SURGE_MAC_ONLY_RULE_TYPES = {
    "PROCESS-NAME",
    "PROCESS-NAME-REGEX",
    "PROCESS-PATH",
    "PROCESS-PATH-REGEX",
}
_CLASH_PROVIDER_HEALTH_CHECK_URL = "https://cp.cloudflare.com/generate_204"
_CLASH_PROVIDER_HEALTH_CHECK_INTERVAL = 300
_POLICY_RULE_SOURCE_ORDER = {
    "system": 0,
    "custom": 1,
    "catalog": 2,
}
_POLICY_RULE_TARGET_ORDER = {
    CONTRACT_HQ_PREMIUM: 0,
    CONTRACT_HQ_STANDARD: 1,
    CONTRACT_MEDIUM: 2,
    CONTRACT_BULK: 3,
    CONTRACT_DIRECT: 4,
    ROUTE_DIRECT_ACTION: 4,
    ROUTE_REJECT_ACTION: -1,
}
_SURGE_TARGET_ORDER = dict(_POLICY_RULE_TARGET_ORDER)


def _policy_rule_identity(entry: PolicyRuleEntry) -> tuple[str, str, tuple[str, ...]]:
    if entry.rule_type in _SURGE_CIDR_RULE_TYPES:
        normalized_value, _ = _normalize_clash_cidr_value(entry.rule_type, entry.value)
        return (entry.rule_type, normalized_value or str(entry.value or "").strip(), tuple())
    return (entry.rule_type, entry.value, tuple(entry.extras))


def _policy_rule_plane_rank(
    entry: PolicyRuleEntry,
    *,
    policy_ir: PolicyIR | None = None,
) -> int:
    if policy_ir is not None:
        return 0 if _route_action_for_target(policy_ir, entry.target_contract_id) == ROUTE_ACTION_REJECT else 1
    return 0 if entry.target_contract_id in {CONTRACT_AD_BLOCK, ROUTE_REJECT_ACTION} else 1


def _policy_rule_source_rank(entry: PolicyRuleEntry) -> int:
    return _POLICY_RULE_SOURCE_ORDER.get(str(entry.source_kind or "").strip(), 99)


def _policy_rule_target_rank(
    entry: PolicyRuleEntry,
    *,
    policy_ir: PolicyIR | None = None,
) -> int:
    if policy_ir is not None:
        action = _route_action_for_target(policy_ir, entry.target_contract_id)
        if action == ROUTE_ACTION_REJECT:
            return -1
        if action == ROUTE_ACTION_DIRECT:
            return 4
        contract = _contract_by_id(policy_ir, entry.target_contract_id)
        if contract is not None:
            return int(contract.sort_order)
        # Once a policy carries an explicit contract catalog, an unresolved
        # target is only an unresolved target.  Do not let its historical ID
        # accidentally inherit the compatibility ordering of a preset.  The
        # legacy helper path still uses the old IDs for backwards-compatible
        # rule ordering.
        if _is_contracts_explicit(policy_ir):
            return 99
    if entry.target_contract_id in {CONTRACT_AD_BLOCK, ROUTE_REJECT_ACTION}:
        return -1
    return _POLICY_RULE_TARGET_ORDER.get(entry.target_contract_id, 99)


def _policy_rule_family_rank(entry: PolicyRuleEntry) -> int:
    if entry.rule_type in _SURGE_DOMAIN_RULE_TYPES:
        return 0
    if entry.rule_type in _SURGE_IP_RULE_TYPES:
        return 2
    return 1


def _policy_rule_conflict_rank(
    entry: PolicyRuleEntry,
    first_seen_index: int,
    *,
    policy_ir: PolicyIR | None = None,
) -> tuple[int, int, int, int, int]:
    return (
        _policy_rule_plane_rank(entry, policy_ir=policy_ir),
        _policy_rule_source_rank(entry),
        _policy_rule_target_rank(entry, policy_ir=policy_ir),
        _policy_rule_family_rank(entry),
        first_seen_index,
    )


def _policy_rule_sort_key(
    entry: PolicyRuleEntry,
    first_seen_index: int,
    *,
    policy_ir: PolicyIR | None = None,
) -> tuple[int, int, int, int]:
    return (
        _policy_rule_plane_rank(entry, policy_ir=policy_ir),
        _policy_rule_source_rank(entry),
        _policy_rule_family_rank(entry),
        first_seen_index,
    )


def merge_policy_rule_entries(
    entries: list[PolicyRuleEntry | None],
    *,
    policy_ir: PolicyIR | None = None,
) -> tuple[list[PolicyRuleEntry], list[RenderWarning], int]:
    merged_by_identity: dict[tuple[str, str, tuple[str, ...]], PolicyRuleEntry] = {}
    first_seen_indices: dict[tuple[str, str, tuple[str, ...]], int] = {}
    warnings: list[RenderWarning] = []
    dropped_invalid_count = 0

    for index, entry in enumerate(entries):
        if not entry:
            dropped_invalid_count += 1
            continue

        identity = _policy_rule_identity(entry)
        existing = merged_by_identity.get(identity)
        if existing is None:
            merged_by_identity[identity] = entry
            first_seen_indices[identity] = index
            continue

        if existing.target_contract_id == entry.target_contract_id:
            if entry.rule_type in _SURGE_IP_RULE_TYPES:
                warnings.append(
                    RenderWarning(
                        code="duplicate-ip-rule",
                        message=f"Duplicate IP rule {entry.rule_type},{entry.value} ignored",
                        target=entry.category_name or entry.value,
                        severity="warning",
                    )
                )
            continue

        first_seen_index = first_seen_indices[identity]
        existing_rank = _policy_rule_conflict_rank(existing, first_seen_index, policy_ir=policy_ir)
        candidate_rank = _policy_rule_conflict_rank(entry, index, policy_ir=policy_ir)
        kept = existing
        dropped = entry
        if candidate_rank < existing_rank:
            kept = entry
            dropped = existing
            merged_by_identity[identity] = entry

        identity_text = ",".join([dropped.rule_type, dropped.value, *[item for item in dropped.extras if item]])
        warnings.append(
            RenderWarning(
                code="conflicting-rule-target",
                message=(
                    f"Conflict on {identity_text}: kept {kept.target_display_name()}, "
                    f"dropped {dropped.target_display_name()} from {dropped.source_kind}"
                ),
                target=dropped.category_name or dropped.value,
                severity="warning",
            )
        )

    merged = list(merged_by_identity.values())
    merged.sort(
        key=lambda item: _policy_rule_sort_key(
            item,
            first_seen_indices[_policy_rule_identity(item)],
            policy_ir=policy_ir,
        )
    )
    return merged, warnings, dropped_invalid_count


def _normalize_clash_cidr_value(rule_type: str, value: str) -> tuple[str | None, bool]:
    text = str(value or "").strip()
    if not text:
        return None, False
    if "/" in text:
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            return None, False
        if rule_type == "IP-CIDR" and isinstance(network, ipaddress.IPv6Network):
            return None, False
        if rule_type == "IP-CIDR6" and isinstance(network, ipaddress.IPv4Network):
            return None, False
        return text, False

    try:
        ip_value = ipaddress.ip_address(text)
    except ValueError:
        return None, False
    if rule_type == "IP-CIDR" and isinstance(ip_value, ipaddress.IPv6Address):
        return None, False
    if rule_type == "IP-CIDR6" and isinstance(ip_value, ipaddress.IPv4Address):
        return None, False
    if isinstance(ip_value, ipaddress.IPv4Address):
        return f"{ip_value.compressed}/32", True
    return f"{ip_value.compressed}/128", True


def _clash_cidr_network(
    rule_type: str,
    value: str,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    normalized_value, _ = _normalize_clash_cidr_value(rule_type, value)
    if not normalized_value:
        return None
    try:
        network = ipaddress.ip_network(normalized_value, strict=False)
    except ValueError:
        return None
    if rule_type == "IP-CIDR" and network.version != 4:
        return None
    if rule_type == "IP-CIDR6" and network.version != 6:
        return None
    if rule_type == "SRC-IP-CIDR" and network.version not in {4, 6}:
        return None
    return network


def _normalize_clash_cidr_rule_lines(
    rule_lines: list[str],
) -> tuple[list[str], list[RenderWarning]]:
    normalized: list[str] = []
    diagnostics: list[RenderWarning] = []
    accepted_by_plane: dict[str, list[tuple[int, int]]] = {}

    for raw_line in rule_lines:
        text = str(raw_line or "").strip()
        if not text:
            continue
        parts = [item.strip() for item in text.split(",")]
        rule_type = parts[0].upper() if parts else ""
        if rule_type not in _CLASH_CIDR_RULE_TYPES or len(parts) < 3:
            normalized.append(text)
            continue

        value = parts[1]
        target = parts[2]
        extras = [item for item in parts[3:] if item]
        network = _clash_cidr_network(rule_type, value)
        if network is None:
            normalized.append(text)
            continue

        plane = _cidr_plane(rule_type, network)
        occupied = accepted_by_plane.setdefault(plane, [])
        start, end = _surge_network_bounds(network)
        remaining_intervals = _subtract_surge_interval(start, end, occupied)
        if not remaining_intervals:
            diagnostics.append(
                RenderWarning(
                    code="clash-cidr-overlap-pruned",
                    message=(
                        f"{rule_type},{network.compressed} for {target} "
                        "is fully covered by earlier Clash CIDR rules"
                    ),
                    target=target or network.compressed,
                )
            )
            continue

        remaining_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for interval_start, interval_end in remaining_intervals:
            remaining_networks.extend(
                _surge_interval_to_networks(network.version, interval_start, interval_end)
            )
            _insert_surge_interval(occupied, interval_start, interval_end)

        if len(remaining_networks) != 1 or remaining_networks[0] != network:
            diagnostics.append(
                RenderWarning(
                    code="clash-cidr-overlap-split",
                    message=(
                        f"{rule_type},{network.compressed} for {target} "
                        f"was normalized to {', '.join(item.compressed for item in remaining_networks)}"
                    ),
                    target=target or network.compressed,
                )
            )
        for item in remaining_networks:
            normalized.append(",".join([rule_type, item.compressed, target, *extras]))
    return normalized, diagnostics


def _unchanged_rule_text(text: str) -> str:
    # Default quote_rule for callers whose rules were not rewritten by the
    # compatibility projection, so the rendered text is already the user's.
    return text


def _normalize_clash_policy_rule_entries(
    compiled_entries: list[PolicyRuleEntry],
    *,
    quote_rule: Callable[[str], str] = _unchanged_rule_text,
) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
    normalized_entries: list[PolicyRuleEntry] = []
    warnings: list[RenderWarning] = []
    accepted_by_plane: dict[str, list[tuple[int, int]]] = {}

    for entry in compiled_entries:
        rule_type = str(entry.rule_type or "").strip().upper()
        value = str(entry.value or "").strip()
        extras = [str(item).strip() for item in entry.extras if str(item).strip()]
        target = entry.target_display_name()
        if not rule_type or not value:
            warnings.append(
                RenderWarning(
                    code="clash-rule-dropped-invalid",
                    message=f"Skipped invalid Clash rule entry: {quote_rule(entry.to_line())}",
                    target=entry.category_name or value or target,
                )
            )
            continue
        if rule_type not in _CLASH_KNOWN_RULE_TYPES:
            warnings.append(
                RenderWarning(
                    code="clash-rule-dropped-invalid",
                    message=f"Skipped unsupported Clash rule type {rule_type}: {quote_rule(entry.to_line())}",
                    target=entry.category_name or value or target,
                )
            )
            continue

        if rule_type == "DOMAIN":
            try:
                ip_value = ipaddress.ip_address(value)
            except ValueError:
                ip_value = None
            if ip_value is not None:
                original_value = value
                if isinstance(ip_value, ipaddress.IPv4Address):
                    rule_type = "IP-CIDR"
                    value = f"{ip_value.compressed}/32"
                else:
                    rule_type = "IP-CIDR6"
                    value = f"{ip_value.compressed}/128"
                warnings.append(
                    RenderWarning(
                        code="clash-domain-ip-autofixed",
                        message=f"Autofixed DOMAIN,{original_value} to {rule_type},{value}",
                        target=original_value,
                        severity="info",
                    )
                )
        elif rule_type in _CLASH_CIDR_RULE_TYPES:
            normalized_value, autofixed = _normalize_clash_cidr_value(rule_type, value)
            if not normalized_value:
                warnings.append(
                    RenderWarning(
                        code="clash-rule-dropped-invalid",
                        message=f"Skipped invalid Clash CIDR rule: {quote_rule(entry.to_line())}",
                        target=entry.category_name or value or target,
                    )
                )
                continue
            value = normalized_value
            extras = list(extras)
            if autofixed:
                warnings.append(
                    RenderWarning(
                        code="clash-cidr-autofixed",
                        message=f"Normalized Clash CIDR rule {quote_rule(entry.to_line())} to {value}",
                        target=entry.category_name or value or target,
                        severity="info",
                    )
                )

        normalized_entry = PolicyRuleEntry(
            target_contract_id=entry.target_contract_id,
            rule_type=rule_type,
            value=value,
            extras=extras,
            source_kind=entry.source_kind,
            category_name=entry.category_name,
            platform_scope=entry.platform_scope,
        )

        if rule_type not in _CLASH_CIDR_RULE_TYPES:
            normalized_entries.append(normalized_entry)
            continue

        network = _clash_cidr_network(rule_type, value)
        if network is None:
            normalized_entries.append(normalized_entry)
            continue

        plane = _cidr_plane(rule_type, network)
        occupied = accepted_by_plane.setdefault(plane, [])
        start, end = _surge_network_bounds(network)
        remaining_intervals = _subtract_surge_interval(start, end, occupied)
        if not remaining_intervals:
            warnings.append(
                RenderWarning(
                    code="clash-cidr-overlap-pruned",
                    message=(
                        f"{rule_type},{network.compressed} for {target} "
                        "is fully covered by earlier Clash CIDR rules"
                    ),
                    target=target or network.compressed,
                )
            )
            continue

        remaining_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for interval_start, interval_end in remaining_intervals:
            remaining_networks.extend(
                _surge_interval_to_networks(network.version, interval_start, interval_end)
            )
            _insert_surge_interval(occupied, interval_start, interval_end)

        if len(remaining_networks) != 1 or remaining_networks[0] != network:
            warnings.append(
                RenderWarning(
                    code="clash-cidr-overlap-split",
                    message=(
                        f"{rule_type},{network.compressed} for {target} "
                        f"was normalized to {', '.join(item.compressed for item in remaining_networks)}"
                    ),
                    target=target or network.compressed,
                )
            )

        for item in remaining_networks:
            normalized_entries.append(
                PolicyRuleEntry(
                    target_contract_id=entry.target_contract_id,
                    rule_type=rule_type,
                    value=item.compressed,
                    extras=list(extras),
                    source_kind=entry.source_kind,
                    category_name=entry.category_name,
                    platform_scope=entry.platform_scope,
                )
            )

    return normalized_entries, warnings


def _sanitize_clash_rule_lines(
    rule_lines: list[str],
    *,
    quote_rule: Callable[[str], str] = _unchanged_rule_text,
) -> tuple[list[str], list[RenderWarning]]:
    sanitized: list[str] = []
    warnings: list[RenderWarning] = []
    identity_targets: dict[tuple[str, str, tuple[str, ...]] | tuple[str, str], str] = {}
    seen_lines: set[str] = set()

    for raw_line in rule_lines:
        text = str(raw_line or "").strip()
        if not text:
            continue
        parts = [item.strip() for item in text.split(",")]
        rule_type = parts[0].upper() if parts else ""

        if rule_type == "MATCH":
            if len(parts) != 2 or not parts[1]:
                warnings.append(
                    RenderWarning(
                        code="clash-rule-dropped-invalid",
                        message=f"Skipped invalid Clash rule: {quote_rule(text)}",
                        target=quote_rule(text),
                    )
                )
                continue
            normalized_line = f"MATCH,{parts[1]}"
            identity = ("MATCH", parts[1], tuple())
            target = parts[1]
        else:
            if rule_type in _CLASH_COMPLEX_RULE_TYPES:
                rest = text[len(rule_type) + 1 :]
                if "," not in rest:
                    warnings.append(
                        RenderWarning(
                            code="clash-rule-dropped-invalid",
                            message=f"Skipped invalid Clash rule: {quote_rule(text)}",
                            target=quote_rule(text),
                        )
                    )
                    continue
                value, target = [item.strip() for item in rest.rsplit(",", 1)]
                extras: list[str] = []
                if not value or not target:
                    warnings.append(
                        RenderWarning(
                            code="clash-rule-dropped-invalid",
                            message=f"Skipped invalid Clash rule: {quote_rule(text)}",
                            target=quote_rule(text),
                        )
                    )
                    continue
            elif len(parts) < 3 or not parts[1] or not parts[2]:
                warnings.append(
                    RenderWarning(
                        code="clash-rule-dropped-invalid",
                        message=f"Skipped invalid Clash rule: {quote_rule(text)}",
                        target=quote_rule(text),
                    )
                )
                continue
            if rule_type not in _CLASH_KNOWN_RULE_TYPES:
                warnings.append(
                    RenderWarning(
                        code="clash-rule-dropped-invalid",
                        message=f"Skipped unsupported Clash rule type {rule_type}: {quote_rule(text)}",
                        target=quote_rule(text),
                    )
                )
                continue

            if rule_type not in _CLASH_COMPLEX_RULE_TYPES:
                value = parts[1]
                target = parts[2]
                extras = [item for item in parts[3:] if item]

            if rule_type == "DOMAIN":
                try:
                    ip_value = ipaddress.ip_address(value)
                except ValueError:
                    ip_value = None
                if ip_value is not None:
                    original_value = value
                    if isinstance(ip_value, ipaddress.IPv4Address):
                        rule_type = "IP-CIDR"
                        value = f"{ip_value.compressed}/32"
                    else:
                        rule_type = "IP-CIDR6"
                        value = f"{ip_value.compressed}/128"
                    warnings.append(
                        RenderWarning(
                            code="clash-domain-ip-autofixed",
                            message=(
                                f"Autofixed DOMAIN,{original_value} to {rule_type},{value}"
                            ),
                            target=original_value,
                            severity="info",
                        )
                    )
            elif rule_type in _CLASH_CIDR_RULE_TYPES:
                normalized_value, autofixed = _normalize_clash_cidr_value(rule_type, value)
                if not normalized_value:
                    warnings.append(
                        RenderWarning(
                            code="clash-rule-dropped-invalid",
                            message=f"Skipped invalid Clash CIDR rule: {quote_rule(text)}",
                            target=quote_rule(text),
                        )
                    )
                    continue
                value = normalized_value
                extras = list(extras)
                if autofixed:
                    warnings.append(
                        RenderWarning(
                            code="clash-cidr-autofixed",
                            message=f"Normalized Clash CIDR rule {quote_rule(text)} to {value}",
                            target=quote_rule(text),
                            severity="info",
                        )
                    )

            normalized_line = ",".join([rule_type, value, target, *extras])
            if rule_type in _CLASH_CIDR_RULE_TYPES:
                identity = (rule_type, value)
            else:
                identity = (rule_type, value, tuple(extras))

        previous_target = identity_targets.get(identity)
        if previous_target is not None and previous_target != target:
            warnings.append(
                RenderWarning(
                    code="conflicting-rule-target",
                    message=(
                        f"Conflict on normalized Clash rule {identity[0]},{identity[1]}: "
                        f"kept {previous_target}, dropped {target}"
                    ),
                    target=quote_rule(text),
                    severity="warning",
                )
            )
            continue
        if normalized_line in seen_lines:
            continue
        identity_targets[identity] = target
        seen_lines.add(normalized_line)
        sanitized.append(normalized_line)
    return sanitized, warnings


def _fail_closed_clash_udp_rules(rule_lines: list[str]) -> list[str]:
    """A failed UDP policy must not fall through to a different route or DIRECT.

    Mihomo skips a matching rule whose selected proxy cannot carry UDP. The
    following guard matches the same condition only after that skip. Explicit
    DIRECT/reject routes keep their behavior. MATCH stays the final rule.
    """
    output: list[str] = []
    for line in rule_lines:
        parts = _split_rule_parts(line)
        target_index = 1 if parts[0] == "MATCH" else 2
        target = parts[target_index]
        if target in {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "PASS-RULE"}:
            output.append(line)
        elif parts[0] == "MATCH":
            output.extend([f"NETWORK,UDP,{target}", "NETWORK,UDP,REJECT", line])
        else:
            condition = ",".join([*parts[:2], *parts[3:]])
            output.extend([line, f"AND,(({condition}),(NETWORK,UDP)),REJECT"])
    return output


def _legacy_rule_text_table(
    originals: list[PolicyRuleEntry],
    projected: list[PolicyRuleEntry],
    policy_ir: PolicyIR,
) -> dict[str, str]:
    """Map projected Clash rule text back to the rule text the user wrote."""
    table: dict[str, str] = {}
    for source, rendered in zip(originals, projected):
        # Entry-level warnings quote PolicyRuleEntry.to_line().
        table[rendered.to_line()] = source.to_line()
        # Line-level warnings quote the rendered Clash rule line.
        source_lines = _client_rule_lines(policy_ir, client="clash", compiled_entries=[source])
        rendered_lines = _client_rule_lines(policy_ir, client="clash", compiled_entries=[rendered])
        if source_lines and rendered_lines:
            table[rendered_lines[0]] = source_lines[0]
    return table


class _LegacyRuleQuoter:
    """Quote rules in the existing Clash warnings as the user wrote them.

    The compatibility projection may rewrite IP rule options, for example by
    adding no-resolve. The existing warnings keep quoting the original rule,
    so their call sites pass the projected text through quote(). The table
    renders every rule twice, so it is built on the first quote only; most
    renders never produce one of these warnings.
    """

    def __init__(
        self,
        originals: list[PolicyRuleEntry],
        projected: list[PolicyRuleEntry],
        policy_ir: PolicyIR,
    ) -> None:
        self._originals = originals
        self._projected = projected
        self._policy_ir = policy_ir
        self._table: dict[str, str] | None = None

    def quote(self, text: str) -> str:
        if self._table is None:
            self._table = _legacy_rule_text_table(self._originals, self._projected, self._policy_ir)
        return self._table.get(text, text)


def build_clash_profile_artifacts(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    *,
    policy_ir: PolicyIR | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
    intent: ConfigurationIntent | None = None,
    provider_base_url: str = "",
    subscription_token: str = "",
    subscription_public_id: str = "",
    provider_url_builder: Callable[[str, str], str] | None = None,
    rule_provider_url_builder: Callable[[str, str], str] | None = None,
    render_mode: str = "subscription",
) -> tuple[str, list[str], list[RenderWarning]]:
    profile = intent.profile if intent is not None else profile
    base_ir = policy_ir or build_policy_ir(nodes, rule_lines)
    provider_payloads: dict[str, dict[str, Any]] = {}
    provider_has_nodes: dict[str, bool] = {}
    skipped: list[str] = []
    desired = intent or derive_configuration_intent(
        base_ir, profile_settings, profile=profile,
    )
    projection = project_configuration_intent(desired, "clash")
    base_ir = projection.policy
    normalized_settings = projection.settings
    requested_settings = projection.requested_settings
    for key in (LAZYCAT_PROFILE_CLASH_DNS_NAMESERVER_KEY, LAZYCAT_PROFILE_CLASH_DNS_DEFAULT_NAMESERVER_KEY, LAZYCAT_PROFILE_CLASH_DNS_PROXY_SERVER_NAMESERVER_KEY):
        if not normalized_settings[key]:
            normalized_settings[key] = list(LAZYCAT_DEFAULT_PROFILE_SETTINGS[key])
    ir = _enrich_policy_ir_for_target(base_ir, target="clash", profile=profile, normalized_settings=normalized_settings)
    if ir.dns.get("fallback"):
        ir.dns["fallback-lazy-query"] = True
    if ir.tun.get("enable") and not ir.tun.get("dns-hijack"):
        ir.tun["dns-hijack"] = ["any:53", "tcp://any:53"]
    lazycat_settings = normalized_settings
    compiled_entries, compile_warnings = projection.compiled_rules()
    intent_rule_entries = list(compiled_entries)
    compiled_entries = projection.project_rules(compiled_entries)
    legacy_rule_quoter = _LegacyRuleQuoter(intent_rule_entries, compiled_entries, ir)
    compiled_entries, dialect_warnings = _lower_policy_entries_for_client(compiled_entries, client="clash")
    compile_warnings.extend(dialect_warnings)
    grouped_nodes = _group_nodes(ir.nodes)
    udp_default_enabled = bool(
        normalized_settings.get(LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY, True)
    )
    is_export = render_mode == "export"
    front_name_by_key = _clash_front_name_map(grouped_nodes, udp_default_enabled=udp_default_enabled)

    for group in QUALITY_GROUPS:
        provider_key = _clash_provider_key(group)
        if group == QUALITY_CHAIN_HOME:
            provider_proxies = []
            provider_skipped = []
            for node in grouped_nodes[group]:
                payload = _clash_proxy(
                    node,
                    udp_default_enabled=udp_default_enabled,
                    front_name_by_key=front_name_by_key,
                )
                if not payload:
                    provider_skipped.append(node.name)
                    continue
                provider_proxies.append(payload)
            if provider_proxies:
                names = _uniqueify_names(
                    [str(item.get("name", "")) for item in provider_proxies],
                    _RESERVED_PROXY_NAMES,
                )
                for index, new_name in enumerate(names):
                    provider_proxies[index]["name"] = new_name
        else:
            provider_proxies, provider_skipped, _ = _build_clash_provider_proxies(
                grouped_nodes[group],
                udp_default_enabled=udp_default_enabled,
            )
        skipped.extend(provider_skipped)
        provider_has_nodes[group] = bool(provider_proxies)
        provider_revision = _clash_provider_revision(provider_key, provider_proxies)
        provider_payloads[provider_key] = _clash_provider_payload(
            provider_key,
            is_export=is_export,
            provider_base_url=provider_base_url,
            subscription_token=subscription_token,
            subscription_public_id=subscription_public_id,
            provider_url_builder=provider_url_builder,
            provider_revision=provider_revision,
        )

    manual_rule_providers, manual_rule_provider_warnings = _validated_clash_rule_providers(ir)
    rule_provider_payloads: dict[str, dict[str, Any]] = dict(manual_rule_providers)
    provider_rule_lines: list[str] = []
    rule_provider_diagnostics: list[RenderWarning] = []
    if not manual_rule_providers:
        rule_provider_assets, rule_provider_order, rule_provider_diagnostics = (
            ({}, [], [])
            if is_export
            else _build_clash_rule_provider_assets(
                compiled_entries,
                policy_ir=ir,
                quote_rule=legacy_rule_quoter.quote,
            )
        )
        for asset_key in rule_provider_order:
            asset = rule_provider_assets.get(asset_key)
            if not asset:
                continue
            content = str(asset.get("content") or "")
            if not content.strip():
                continue
            provider_revision = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
            rule_provider_payloads[asset_key] = _clash_rule_provider_payload(
                asset_key,
                behavior=str(asset.get("behavior") or "classical"),
                is_export=is_export,
                provider_base_url=provider_base_url,
                subscription_token=subscription_token,
                subscription_public_id=subscription_public_id,
                rule_provider_url_builder=rule_provider_url_builder,
                provider_revision=provider_revision,
            )
            provider_rule_lines.append(f"RULE-SET,{asset_key},{asset.get('target')}")

    system_rule_lines = [
        entry.to_line(
            target_name=_lower_rule_target_for_client(
                _contract_target_name(ir, entry.target_contract_id, client="clash"),
                policy_ir=ir,
                client="clash",
                contract_id=entry.target_contract_id,
            )
        )
        for entry in compiled_entries
        if entry.source_kind == "system"
    ]
    rendered_rule_lines = (
        _rule_lines_with_default(ir, client="clash", compiled_entries=compiled_entries)
        if is_export or manual_rule_providers
        else [*system_rule_lines, *provider_rule_lines, f"MATCH,{ir.default_group_name}"]
    )
    # Inject DIRECT rules from skip-proxy decomposition before MATCH
    if ir.skip_proxy_direct_rules:
        match_idx = next(
            (i for i, line in enumerate(rendered_rule_lines) if line.startswith("MATCH,")),
            len(rendered_rule_lines),
        )
        existing_set = set(rendered_rule_lines)
        new_rules = [r for r in ir.skip_proxy_direct_rules if r not in existing_set]
        rendered_rule_lines = (
            rendered_rule_lines[:match_idx] + new_rules + rendered_rule_lines[match_idx:]
        )
    clash_rules, clash_warnings = _sanitize_clash_rule_lines(
        rendered_rule_lines,
        quote_rule=legacy_rule_quoter.quote,
    )
    clash_rules, clash_cidr_diagnostics = _normalize_clash_cidr_rule_lines(clash_rules)
    clash_rules = _fail_closed_clash_udp_rules(clash_rules)
    warnings = [
        *_clash_pool_diagnostics(provider_has_nodes),
        *derive_protocol_diagnostics(ir.nodes, skipped, target="clash"),
        *derive_mihomo_pending_profile_diagnostics(requested_settings if profile == "lazycat" else None, local_host_aliases=local_host_aliases),
        *ir.warnings,
        *compile_warnings,
        *manual_rule_provider_warnings,
        *rule_provider_diagnostics,
        *clash_warnings,
        *clash_cidr_diagnostics,
    ]
    configured_tun_route_excludes = _profile_list(
        normalized_settings.get(LAZYCAT_PROFILE_TUN_EXCLUDED_ROUTES_KEY, [])
    )
    configured_tun_route_exclude_set = set(configured_tun_route_excludes)
    decomposed_skip_proxy_route_excludes = [
        str(entry).strip()
        for entry in list(ir.tun.get("route-exclude-address") or [])
        if str(entry).strip() and str(entry).strip() not in configured_tun_route_exclude_set
    ]
    if decomposed_skip_proxy_route_excludes and not ir.tun.get("enable"):
        warnings.append(
            RenderWarning(
                code="clash-skip-proxy-cidr-requires-tun",
                message=(
                    "skip-proxy CIDR/IP entries were kept in tun.route-exclude-address, "
                    "but Mihomo TUN is disabled so those direct-route exclusions stay inactive until tun.enable is turned on"
                ),
                target=LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY,
                severity="warning",
                bucket="downgraded",
            )
        )
    referenced_helper_names = _referenced_helper_group_names(
        ir,
        client="clash",
        available_pools={group for group in QUALITY_GROUPS if provider_has_nodes.get(group)},
        has_chain_nodes=provider_has_nodes.get(QUALITY_CHAIN_HOME, False),
    )
    proxy_groups = _clash_group_payloads(ir, provider_has_nodes, grouped_nodes, referenced_helper_names)
    payload = {
        "mode": "rule",
        "allow-lan": bool(normalized_settings.get(LAZYCAT_PROFILE_CLASH_ALLOW_LAN_KEY, False)),
        "log-level": str(normalized_settings.get(LAZYCAT_PROFILE_CLASH_LOG_LEVEL_KEY, "info")),
        "proxy-providers": provider_payloads,
        "rule-providers": rule_provider_payloads,
        "proxy-groups": proxy_groups,
        "rules": clash_rules,
    }
    if profile in {"lazycat", "raw"}:
        payload["ipv6"] = bool(normalized_settings.get(LAZYCAT_PROFILE_CLASH_IPV6_KEY, False))
        payload["mixed-port"] = int(normalized_settings[LAZYCAT_PROFILE_CLASH_MIXED_PORT_KEY])
    if profile == "lazycat":
        if ir.metadata.get("profile"):
            payload["profile"] = dict(ir.metadata["profile"])
        control_payload = {
            key: value
            for key, value in dict(ir.metadata.get("control") or {}).items()
            if value not in ("", None) and value != [] and value != {}
        }
        payload.update(control_payload)
        if ir.dns:
            payload["dns"] = dict(ir.dns)
        host_records = {
            str(host).strip(): str(target).strip()
            for host, target in dict(
                normalized_settings.get(LAZYCAT_PROFILE_CLASH_HOST_RECORDS_KEY, {}) or {}
            ).items()
            if str(host).strip() and str(target).strip()
        }
        if host_records:
            payload["hosts"] = host_records
        if ir.tun and (ir.tun.get("enable") or decomposed_skip_proxy_route_excludes):
            payload["tun"] = dict(ir.tun)
        if ir.sniffer and ir.sniffer.get("enable"):
            payload["sniffer"] = dict(ir.sniffer)
    warnings.extend(projection.diagnostics)
    warnings.extend(routing_intent_diagnostics(
        intent_rule_entries, target="clash", default_action=_route_action_for_target(ir, ir.default_contract_id),
        ip_resolution=projection.ip_resolution, projection=projection,
    ))
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), skipped, warnings


def _surge_asset_base_url(managed_subscription_url: str) -> str:
    base = str(managed_subscription_url or "").split("?", 1)[0].rstrip("/")
    suffix = "/surge.conf"
    if base.endswith(suffix):
        return f"{base[:-len(suffix)]}/surge"
    return f"{base}/surge"


def _surge_subscription_metadata(
    *,
    managed_subscription_url: str,
    asset_base_url: str,
    revision: str = "",
    domain_set_count: int = 0,
    rule_set_count: int = 0,
) -> dict[str, Any]:
    base_url = str(asset_base_url or "").rsplit("/sub/device/", 1)[0].rstrip("/")
    return {
        "managed_url": str(managed_subscription_url or "").strip(),
        "include_url": str(managed_subscription_url or "").strip(),
        "asset_base_url": str(asset_base_url or "").strip(),
        "base_url": base_url,
        "revision": str(revision or "").strip(),
        "domain_set_count": int(domain_set_count),
        "rule_set_count": int(rule_set_count),
    }


def _surge_subscription_metadata_lines(metadata: dict[str, Any]) -> list[str]:
    return [
        f"# SubHub base-url: {str(metadata.get('base_url', '') or '').strip()}",
        f"# SubHub managed-url: {str(metadata.get('managed_url', '') or '').strip()}",
        f"# SubHub asset-base-url: {str(metadata.get('asset_base_url', '') or '').strip()}",
        f"# SubHub artifact-revision: {str(metadata.get('revision', '') or '').strip()}",
        (
            "# SubHub asset-counts: "
            f"domain-sets={int(metadata.get('domain_set_count', 0) or 0)}, "
            f"rule-sets={int(metadata.get('rule_set_count', 0) or 0)}"
        ),
    ]


def _surge_asset_url(asset_base_url: str, kind: str, asset_key: str) -> str:
    suffix = "txt" if kind == "domain-set" else "list"
    return f"{asset_base_url.rstrip('/')}/{kind}/{asset_key}.{suffix}"


def _surge_target_name(contract_id: str, *, policy_ir: PolicyIR | None = None) -> str:
    normalized = str(contract_id or "").strip()
    if _is_native_rule_target(normalized, client="surge"):
        return normalized
    if normalized == ROUTE_DIRECT_ACTION:
        return "DIRECT"
    if normalized == ROUTE_REJECT_ACTION:
        return QUALITY_REJECT
    if policy_ir is not None:
        return _contract_target_name(policy_ir, normalized, client="surge")
    return contract_display_name(normalized)


def _policy_rule_entry_from_line(
    raw_line: str,
    *,
    policy_ir: PolicyIR | None = None,
) -> PolicyRuleEntry | None:
    parts = _split_rule_parts(str(raw_line or ""))
    if len(parts) < 3:
        return None
    target = parts[2]
    if not target:
        return None
    contract_target_id = ""
    if policy_ir is not None:
        for contract in policy_ir.contracts:
            if str(contract.display_name or "").strip() == target:
                contract_target_id = contract.id
                break
    if contract_target_id:
        target_contract_id = contract_target_id
    elif _is_native_rule_target(target, client="shadowrocket") and target not in {"DIRECT", "REJECT"}:
        target_contract_id = target
    elif target in {QUALITY_REJECT, "REJECT", contract_display_name(ROUTE_REJECT_ACTION)}:
        target_contract_id = ROUTE_REJECT_ACTION
    elif target == "DIRECT":
        target_contract_id = ROUTE_DIRECT_ACTION
    else:
        target_contract_id = normalize_contract_id(target)
    if not target_contract_id:
        return None
    return PolicyRuleEntry(
        target_contract_id=target_contract_id,
        rule_type=parts[0].upper(),
        value=parts[1],
        extras=[item for item in parts[3:] if item],
        source_kind="catalog",
        category_name="",
        platform_scope="any",
    )


def _compiled_policy_rule_entries(policy_ir: PolicyIR) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
    entries: list[PolicyRuleEntry | None]
    if policy_ir.rule_entries:
        entries = list(policy_ir.rule_entries)
    else:
        entries = [
            _policy_rule_entry_from_line(line, policy_ir=policy_ir)
            for line in policy_ir.rule_lines
        ]

    compiled_entries, warnings, dropped_invalid_count = merge_policy_rule_entries(
        entries,
        policy_ir=policy_ir,
    )
    if dropped_invalid_count:
        warnings.append(
            RenderWarning(
                code="invalid-rule-dropped",
                message=f"{dropped_invalid_count} invalid rule lines were dropped during compilation",
                target="rule-compiler",
                severity="warning",
            )
        )
    return compiled_entries, warnings


def _surge_asset_sort_key(asset_key: str) -> tuple[int, int, str]:
    if asset_key == "reject-domains":
        return (0, -1, asset_key)
    if asset_key == "reject-rules":
        return (1, -1, asset_key)
    if asset_key.startswith("manual-domains-"):
        target = asset_key.removeprefix("manual-domains-")
        return (2, _SURGE_TARGET_ORDER.get(target, 99), asset_key)
    if asset_key.startswith("catalog-domains-"):
        target = asset_key.removeprefix("catalog-domains-")
        return (3, _SURGE_TARGET_ORDER.get(target, 99), asset_key)
    if asset_key.startswith("manual-rules-"):
        target = asset_key.removeprefix("manual-rules-")
        return (4, _SURGE_TARGET_ORDER.get(target, 99), asset_key)
    if asset_key.startswith("catalog-rules-"):
        target = asset_key.removeprefix("catalog-rules-")
        return (5, _SURGE_TARGET_ORDER.get(target, 99), asset_key)
    if asset_key.startswith("ip-rules-"):
        target = asset_key.removeprefix("ip-rules-")
        return (6, _SURGE_TARGET_ORDER.get(target, 99), asset_key)
    return (99, 99, asset_key)


def _surge_asset_policy(asset_key: str, *, policy_ir: PolicyIR | None = None) -> str:
    if asset_key in {"reject-domains", "reject-rules"}:
        return QUALITY_REJECT
    target = asset_key.split("-", 2)[-1]
    if asset_key.startswith("manual-domains-") or asset_key.startswith("catalog-domains-"):
        target = asset_key.removeprefix("manual-domains-")
        target = target.removeprefix("catalog-domains-")
    elif asset_key.startswith("manual-rules-") or asset_key.startswith("catalog-rules-"):
        target = asset_key.removeprefix("manual-rules-")
        target = target.removeprefix("catalog-rules-")
    elif asset_key.startswith("ip-rules-"):
        target = asset_key.removeprefix("ip-rules-")
    return _surge_target_name(target, policy_ir=policy_ir)


def _surge_domain_set_value(entry: PolicyRuleEntry) -> str:
    if entry.rule_type == "DOMAIN-SUFFIX":
        return f".{str(entry.value or '').lstrip('.')}"
    return str(entry.value or "").strip()


def _surge_cidr_network(
    entry: PolicyRuleEntry,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    try:
        network = ipaddress.ip_network(str(entry.value or "").strip(), strict=False)
    except ValueError:
        return None
    if entry.rule_type == "IP-CIDR" and network.version != 4:
        return None
    if entry.rule_type == "IP-CIDR6" and network.version != 6:
        return None
    if entry.rule_type == "SRC-IP-CIDR" and network.version not in {4, 6}:
        return None
    return network


def _cidr_plane(rule_type: str, network: ipaddress._BaseNetwork) -> str:
    prefix = "src" if rule_type == "SRC-IP-CIDR" else "dst"
    suffix = "v4" if network.version == 4 else "v6"
    return f"{prefix}-{suffix}"


def _surge_cidr_plane(entry: PolicyRuleEntry, network: ipaddress._BaseNetwork) -> str:
    return _cidr_plane(entry.rule_type, network)


def _subtract_surge_network(
    candidate: ipaddress._BaseNetwork,
    occupied: ipaddress._BaseNetwork,
) -> list[ipaddress._BaseNetwork]:
    if not candidate.overlaps(occupied):
        return [candidate]
    if candidate.subnet_of(occupied) or candidate == occupied:
        return []
    if occupied.subnet_of(candidate):
        return list(candidate.address_exclude(occupied))
    return [candidate]


def _surge_network_bounds(network: ipaddress._BaseNetwork) -> tuple[int, int]:
    return int(network.network_address), int(network.broadcast_address)


def _surge_interval_to_networks(
    version: int,
    start: int,
    end: int,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    address_cls = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
    return list(ipaddress.summarize_address_range(address_cls(start), address_cls(end)))


def _subtract_surge_interval(
    start: int,
    end: int,
    occupied: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not occupied:
        return [(start, end)]

    remaining: list[tuple[int, int]] = []
    cursor = start
    index = bisect_left(occupied, (start, -1))
    if index > 0:
        index -= 1

    while index < len(occupied):
        occupied_start, occupied_end = occupied[index]
        if occupied_end < cursor:
            index += 1
            continue
        if occupied_start > end:
            break
        if occupied_start > cursor:
            remaining.append((cursor, min(end, occupied_start - 1)))
        cursor = max(cursor, occupied_end + 1)
        if cursor > end:
            break
        index += 1

    if cursor <= end:
        remaining.append((cursor, end))
    return remaining


def _insert_surge_interval(
    occupied: list[tuple[int, int]],
    start: int,
    end: int,
) -> None:
    index = bisect_left(occupied, (start, -1))
    merged_start = start
    merged_end = end

    if index > 0 and occupied[index - 1][1] + 1 >= start:
        index -= 1

    while index < len(occupied) and occupied[index][0] <= merged_end + 1:
        merged_start = min(merged_start, occupied[index][0])
        merged_end = max(merged_end, occupied[index][1])
        occupied.pop(index)

    occupied.insert(index, (merged_start, merged_end))


def _normalize_surge_cidr_entries(
    entries: list[PolicyRuleEntry],
    *,
    policy_ir: PolicyIR | None = None,
) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
    diagnostics: list[RenderWarning] = []
    accepted_by_plane: dict[str, list[tuple[int, int]]] = {}
    passthrough: list[PolicyRuleEntry] = []
    cidr_candidates: list[tuple[tuple[int, int, int, int, int], int, PolicyRuleEntry]] = []

    for index, entry in enumerate(entries):
        if entry.rule_type not in _SURGE_CIDR_RULE_TYPES:
            passthrough.append(entry)
            continue
        cidr_candidates.append(
            (_policy_rule_conflict_rank(entry, index, policy_ir=policy_ir), index, entry)
        )

    cidr_entries: list[PolicyRuleEntry] = []
    for _, _, entry in sorted(cidr_candidates, key=lambda item: item[0]):
        network = _surge_cidr_network(entry)
        if network is None:
            passthrough.append(entry)
            continue
        plane = _surge_cidr_plane(entry, network)
        occupied_networks = accepted_by_plane.setdefault(plane, [])
        start, end = _surge_network_bounds(network)
        remaining_intervals = _subtract_surge_interval(start, end, occupied_networks)
        if not remaining_intervals:
            diagnostics.append(
                RenderWarning(
                    code="surge-cidr-overlap-pruned",
                    message=(
                        f"{entry.rule_type},{entry.value} for {entry.target_display_name()} "
                        "is fully covered by higher-priority Surge CIDR rules"
                    ),
                    target=entry.category_name or entry.value,
                )
            )
            continue

        remaining_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for interval_start, interval_end in remaining_intervals:
            remaining_networks.extend(
                _surge_interval_to_networks(network.version, interval_start, interval_end)
            )
            _insert_surge_interval(occupied_networks, interval_start, interval_end)

        if len(remaining_networks) != 1 or remaining_networks[0] != network:
            diagnostics.append(
                RenderWarning(
                    code="surge-cidr-overlap-split",
                    message=(
                        f"{entry.rule_type},{entry.value} for {entry.target_display_name()} "
                        f"was normalized to {', '.join(item.compressed for item in remaining_networks)}"
                    ),
                    target=entry.category_name or entry.value,
                )
            )
        for item in remaining_networks:
            cidr_entries.append(
                PolicyRuleEntry(
                    target_contract_id=entry.target_contract_id,
                    rule_type=entry.rule_type,
                    value=item.compressed,
                    extras=list(entry.extras),
                    source_kind=entry.source_kind,
                    category_name=entry.category_name,
                    platform_scope=entry.platform_scope,
                )
            )
    return passthrough + cidr_entries, diagnostics


def _surge_referenced_contracts(
    policy_ir: PolicyIR,
    entries: list[PolicyRuleEntry],
    *,
    client: str = "surge",
) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    contracts_by_id = {item.id: item for item in policy_ir.contracts}

    def _ensure(contract_id: str) -> dict[str, Any] | None:
        if _is_native_rule_target(contract_id, client=client):
            return None
        normalized = normalize_contract_id(contract_id)
        if normalized in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}:
            return None
        if (
            not _is_contracts_explicit(policy_ir)
            and (
                contract_legacy_group(normalized) in QUALITY_GROUPS
                or normalized in {CONTRACT_DIRECT, CONTRACT_AD_BLOCK}
            )
        ):
            return None
        contract = contracts_by_id.get(normalized)
        if (
            contract is not None
            and bool(contract.enabled)
            and _route_action(contract) in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT}
        ):
            return None
        reference_id = normalized or str(contract_id or "").strip()
        if not reference_id:
            return None
        payload = references.get(reference_id)
        if payload is None:
            payload = {
                "id": reference_id,
                "display_name": (
                    str(contract.display_name or "").strip()
                    if contract is not None
                    else contract_display_name(reference_id)
                ),
                "primary_pools": list(contract.primary_pools or []) if contract is not None else [],
                "fallback_pools": list(contract.fallback_pools or []) if contract is not None else [],
                "rule_entry_count": 0,
                "process_rule_count": 0,
                "external_proxy_program_count": 0,
                "referenced_by": [],
            }
            references[reference_id] = payload
        return payload

    for entry in entries:
        payload = _ensure(entry.target_contract_id)
        if payload is None:
            continue
        payload["rule_entry_count"] += 1
        if "rule" not in payload["referenced_by"]:
            payload["referenced_by"].append("rule")

    for item in policy_ir.process_rules:
        if not item.enabled or not item.contract_id:
            continue
        payload = _ensure(item.contract_id)
        if payload is None:
            continue
        payload["process_rule_count"] += 1
        if "process-rule" not in payload["referenced_by"]:
            payload["referenced_by"].append("process-rule")

    for item in policy_ir.external_proxy_programs:
        if not item.enabled or not item.contract_id:
            continue
        payload = _ensure(item.contract_id)
        if payload is None:
            continue
        payload["external_proxy_program_count"] += 1
        if "external-proxy-program" not in payload["referenced_by"]:
            payload["referenced_by"].append("external-proxy-program")

    return references


def _surge_build_blockers(
    policy_ir: PolicyIR,
    *,
    available_contracts: dict[str, bool],
    referenced_contracts: dict[str, dict[str, Any]],
) -> tuple[list[RenderWarning], list[dict[str, Any]]]:
    contracts_by_id = {item.id: item for item in policy_ir.contracts}
    blockers: list[RenderWarning] = []
    referenced_summaries: list[dict[str, Any]] = []

    default_id = normalize_contract_id(policy_ir.default_contract_id)
    default_contract = contracts_by_id.get(default_id)
    default_action = (
        _route_action_for_target(policy_ir, default_id)
        if default_id in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}
        or (default_contract is not None and bool(default_contract.enabled))
        else ""
    )
    if _is_contracts_explicit(policy_ir) and default_action not in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT} and (
        not default_id or default_contract is None or not bool(default_contract.enabled)
    ):
        reason = "missing" if not default_id or default_contract is None else "disabled"
        blockers.append(
            RenderWarning(
                code=f"surge-default-contract-{reason}",
                message=(
                    "No enabled default route contract is available"
                    if reason == "missing"
                    else f"Default route contract {default_contract.display_name} is disabled"
                ),
                target=default_id or "default",
                severity="error",
            )
        )

    for contract_id, reference in referenced_contracts.items():
        contract = contracts_by_id.get(contract_id)
        if contract is None:
            referenced_summaries.append(dict(reference))
            blockers.append(
                RenderWarning(
                    code="surge-referenced-missing-contract",
                    message=f"Referenced route contract {reference['display_name']} does not exist",
                    target=reference["display_name"],
                    severity="error",
                )
            )
            continue
        if not bool(contract.enabled):
            referenced_summaries.append({**reference, "strategy_type": contract.strategy_type, "failure_action": contract.failure_action})
            blockers.append(
                RenderWarning(
                    code="surge-referenced-disabled-contract",
                    message=f"Referenced route contract {contract.display_name} is disabled",
                    target=contract.display_name,
                    severity="error",
                )
            )
            continue
        if _route_action(contract) in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT}:
            continue
        if available_contracts.get(contract_id, True):
            continue
        summary = {
            **reference,
            "strategy_type": contract.strategy_type,
            "failure_action": contract.failure_action,
        }
        referenced_summaries.append(summary)
        blockers.append(
            RenderWarning(
                code="surge-referenced-empty-contract",
                message=(
                    f"{contract.display_name} has no renderable primary pools; "
                    f"referenced by rules={reference['rule_entry_count']}, "
                    f"process-rules={reference['process_rule_count']}, "
                    f"external-proxy-programs={reference['external_proxy_program_count']}"
                ),
                target=contract.display_name,
                severity="error",
            )
        )
    return blockers, referenced_summaries


def _validate_surge_cidr_overlaps(entries: list[PolicyRuleEntry]) -> list[RenderWarning]:
    blockers: list[RenderWarning] = []
    seen_by_plane: dict[
        str,
        list[tuple[int, int, ipaddress._BaseNetwork, PolicyRuleEntry]],
    ] = {}

    for entry in entries:
        if entry.rule_type not in _SURGE_CIDR_RULE_TYPES:
            continue
        network = _surge_cidr_network(entry)
        if network is None:
            continue
        plane = _surge_cidr_plane(entry, network)
        start, end = _surge_network_bounds(network)
        seen_by_plane.setdefault(plane, []).append((start, end, network, entry))

    for plane, bucket in seen_by_plane.items():
        if len(bucket) < 2:
            continue
        bucket.sort(key=lambda item: (item[0], item[1]))
        previous_start, previous_end, previous_network, previous_entry = bucket[0]
        for start, end, network, entry in bucket[1:]:
            if start <= previous_end:
                blockers.append(
                    RenderWarning(
                        code="surge-cidr-overlap-blocker",
                        message=(
                            f"Residual Surge CIDR overlap in {plane}: "
                            f"{entry.rule_type},{network.compressed} ({entry.target_display_name()}) overlaps "
                            f"{previous_entry.rule_type},{previous_network.compressed} "
                            f"({previous_entry.target_display_name()})"
                        ),
                        target=entry.category_name or network.compressed,
                        severity="error",
                    )
                )
                if end > previous_end:
                    previous_start, previous_end, previous_network, previous_entry = (
                        start,
                        end,
                        network,
                        entry,
                    )
                continue
            previous_start, previous_end, previous_network, previous_entry = (
                start,
                end,
                network,
                entry,
            )
    return blockers


def surge_blocked_detail(artifacts: SurgeProfileArtifacts) -> dict[str, object]:
    return {
        "code": "surge-build-blocked",
        "blockers": [item.to_dict() for item in artifacts.blockers],
        "warnings": [item.to_dict() for item in artifacts.diagnostics],
        "asset_counts": {
            "domain_sets": len(artifacts.domain_sets),
            "rule_sets": len(artifacts.rule_sets),
        },
        "referenced_contracts": [dict(item) for item in artifacts.referenced_contracts],
    }


def _surge_requirement_group_line(requirement: str, config_line: str) -> str:
    return f"#!REQUIREMENT {requirement} {config_line}"


def _surge_requirement_suffix_line(config_line: str, requirement: str) -> str:
    return f"{config_line} //!REQUIREMENT {requirement}"


def _clash_provider_has_nodes(policy_ir: PolicyIR) -> dict[str, bool]:
    grouped_nodes = _group_nodes(policy_ir.nodes)
    return {group: bool(grouped_nodes[group]) for group in QUALITY_GROUPS}


def _clash_pool_diagnostics(provider_has_nodes: dict[str, bool]) -> list[RenderWarning]:
    diagnostics: list[RenderWarning] = []
    for pool_name in QUALITY_GROUPS:
        if provider_has_nodes.get(pool_name, False):
            continue
        diagnostics.append(
            RenderWarning(
                code="empty-pool",
                message=f"{pool_name} has no renderable proxies",
                target=pool_name,
                severity="error",
            )
        )
    return diagnostics


def _clash_provider_health_check_payload() -> dict[str, Any]:
    return {
        "enable": True,
        "url": _CLASH_PROVIDER_HEALTH_CHECK_URL,
        "interval": _CLASH_PROVIDER_HEALTH_CHECK_INTERVAL,
    }


def _clash_provider_payload(
    provider_key: str,
    *,
    is_export: bool,
    provider_base_url: str,
    subscription_token: str,
    subscription_public_id: str,
    provider_url_builder: Callable[[str, str], str] | None,
    provider_revision: str,
) -> dict[str, Any]:
    url = "" if is_export else (
        provider_url_builder(provider_key, provider_revision)
        if provider_url_builder
        else _clash_provider_url(
            provider_base_url,
            subscription_public_id or subscription_token,
            provider_key,
            revision=provider_revision,
        )
    )
    payload: dict[str, Any] = {
        "type": "file" if is_export else "http",
        "path": (
            _clash_provider_export_path(provider_key)
            if is_export
            else _clash_provider_cache_path(
                f"{subscription_token}|{urlparse(url).path}",
                provider_key,
                revision=provider_revision,
            )
        ),
        "proxy": "DIRECT",
    }
    if is_export:
        return payload
    payload["url"] = url
    payload["interval"] = 1800
    return payload


def _clash_rule_provider_cache_path(subscription_token: str, asset_key: str, *, revision: str = "") -> str:
    token_hash = hashlib.sha1(str(subscription_token or "default").encode("utf-8")).hexdigest()[:12]
    return f"./rules/subhub-{token_hash}-{_safe_name(asset_key or 'default')}.list"


def _clash_rule_provider_export_path(asset_key: str) -> str:
    return f"rules/{_safe_name(asset_key or 'default')}.list"


def _clash_rule_provider_url(base_url: str, subscription_id: str, asset_key: str, revision: str = "") -> str:
    normalized_base = str(base_url or "").strip().rstrip("/") or "http://127.0.0.1"
    normalized_subscription_id = str(subscription_id or "default").strip() or "default"
    url = f"{normalized_base}/sub/device/{normalized_subscription_id}/clash/rules/{asset_key}.list"
    normalized_revision = str(revision or "").strip()
    if normalized_revision:
        url = f"{url}?rev={quote(normalized_revision, safe='')}"
    return url


def _clash_rule_provider_payload(
    asset_key: str,
    *,
    behavior: str,
    is_export: bool,
    provider_base_url: str,
    subscription_token: str,
    subscription_public_id: str,
    rule_provider_url_builder: Callable[[str, str], str] | None,
    provider_revision: str,
) -> dict[str, Any]:
    url = "" if is_export else (
        rule_provider_url_builder(asset_key, provider_revision)
        if rule_provider_url_builder
        else _clash_rule_provider_url(
            provider_base_url,
            subscription_public_id or subscription_token,
            asset_key,
            revision=provider_revision,
        )
    )
    payload: dict[str, Any] = {
        "type": "file" if is_export else "http",
        "behavior": behavior,
        "proxy": "DIRECT",
        "format": "text",
        "path": (
            _clash_rule_provider_export_path(asset_key)
            if is_export
            else _clash_rule_provider_cache_path(
                f"{subscription_token}|{urlparse(url).path}",
                asset_key,
                revision=provider_revision,
            )
        ),
    }
    if is_export:
        return payload
    payload["url"] = url
    payload["interval"] = 1800
    return payload


def _build_clash_rule_provider_assets(
    compiled_entries: list[PolicyRuleEntry],
    policy_ir: PolicyIR | None = None,
    *,
    quote_rule: Callable[[str], str] = _unchanged_rule_text,
) -> tuple[dict[str, dict[str, Any]], list[str], list[RenderWarning]]:
    normalized_entries, warnings = _normalize_clash_policy_rule_entries(
        compiled_entries,
        quote_rule=quote_rule,
    )
    assets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in normalized_entries:
        if entry.source_kind == "system":
            continue
        source_prefix = "manual" if entry.source_kind == "custom" else "catalog"
        target_action = (
            _route_action_for_target(policy_ir, entry.target_contract_id)
            if policy_ir is not None
            else (
                ROUTE_ACTION_REJECT
                if entry.target_contract_id in {CONTRACT_AD_BLOCK, ROUTE_REJECT_ACTION}
                else ROUTE_ACTION_PROXY
            )
        )
        asset_contract_id = (
            CONTRACT_AD_BLOCK
            if target_action == ROUTE_ACTION_REJECT
            else CONTRACT_DIRECT
            if target_action == ROUTE_ACTION_DIRECT
            else entry.target_contract_id
        )
        asset_key = f"{source_prefix}-rules-{asset_contract_id}"
        payload = assets.get(asset_key)
        if payload is None:
            payload = {
                "behavior": "classical",
                "target": (
                    QUALITY_REJECT
                    if target_action == ROUTE_ACTION_REJECT
                    else _contract_target_name(policy_ir, entry.target_contract_id)
                    if policy_ir is not None
                    else entry.target_display_name()
                ),
                "lines": [],
            }
            assets[asset_key] = payload
            order.append(asset_key)
        payload["lines"].append(entry.to_ruleset_line())
    rendered = {
        key: {
            "behavior": str(value.get("behavior") or "classical"),
            "target": str(value.get("target") or ""),
            "content": "\n".join(str(item) for item in value.get("lines", []) if str(item).strip()) + "\n",
        }
        for key, value in assets.items()
        if value.get("lines")
    }
    return rendered, order, warnings


def _validated_clash_rule_providers(policy_ir: PolicyIR) -> tuple[dict[str, dict[str, Any]], list[RenderWarning]]:
    raw_providers = dict(policy_ir.rule_providers or {})
    nested = getattr(policy_ir, "providers", None)
    if not raw_providers and isinstance(nested, dict):
        raw_providers = dict(nested.get("rule_providers") or {})
    validated: dict[str, dict[str, Any]] = {}
    warnings: list[RenderWarning] = []
    for name, payload in raw_providers.items():
        if not isinstance(payload, dict):
            continue
        normalized = {str(key): value for key, value in payload.items() if str(key).strip()}
        normalized.setdefault("proxy", "DIRECT")
        behavior = str(normalized.get("behavior") or "").strip().lower()
        format_name = str(normalized.get("format") or "").strip().lower()
        if behavior == "classical" and format_name == "mrs":
            warnings.append(
                RenderWarning(
                    code="clash-rule-provider-invalid-format",
                    message=(
                        f"Rule provider {name} uses unsupported format combination behavior=classical format=mrs"
                    ),
                    target=str(name),
                    severity="warning",
                    bucket="refused",
                )
            )
            continue
        validated[str(name)] = normalized
    return validated, warnings


def _validate_clash_cidr_overlaps(rule_lines: list[str]) -> list[RenderWarning]:
    blockers: list[RenderWarning] = []
    seen_by_plane: dict[str, list[tuple[int, int, ipaddress._BaseNetwork, str, str]]] = {}

    for raw_line in rule_lines:
        text = str(raw_line or "").strip()
        if not text:
            continue
        parts = [item.strip() for item in text.split(",")]
        rule_type = parts[0].upper() if parts else ""
        if rule_type not in _CLASH_CIDR_RULE_TYPES or len(parts) < 3:
            continue
        network = _clash_cidr_network(rule_type, parts[1])
        if network is None:
            continue
        plane = _cidr_plane(rule_type, network)
        start, end = _surge_network_bounds(network)
        seen_by_plane.setdefault(plane, []).append((start, end, network, rule_type, parts[2]))

    for plane, bucket in seen_by_plane.items():
        if len(bucket) < 2:
            continue
        bucket.sort(key=lambda item: (item[0], item[1]))
        previous_start, previous_end, previous_network, previous_rule_type, previous_target = bucket[0]
        for start, end, network, rule_type, target in bucket[1:]:
            if start <= previous_end:
                blockers.append(
                    RenderWarning(
                        code="clash-cidr-overlap-blocker",
                        message=(
                            f"Residual Clash CIDR overlap in {plane}: "
                            f"{rule_type},{network.compressed} ({target}) overlaps "
                            f"{previous_rule_type},{previous_network.compressed} ({previous_target})"
                        ),
                        target=target or network.compressed,
                        severity="error",
                    )
                )
                if end > previous_end:
                    previous_start, previous_end, previous_network, previous_rule_type, previous_target = (
                        start,
                        end,
                        network,
                        rule_type,
                        target,
                    )
                continue
            previous_start, previous_end, previous_network, previous_rule_type, previous_target = (
                start,
                end,
                network,
                rule_type,
                target,
            )
    return blockers


def _clash_group_can_be_empty(group: Mapping[str, Any]) -> bool:
    return any(group.get(key) for key in (
        "use", "include-all", "include-all-proxies", "include-all-providers",
        "exclude-filter", "exclude-type",
    )) or bool(group.get("filter") and not group.get("proxies"))


def _normalized_health_check_url(value: object) -> tuple | None:
    """Compare HTTP request destinations without guessing at invalid URLs."""
    try:
        parsed = urlparse(str(value or "").strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            return None
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None
    return (scheme, parsed.hostname.lower(), port, parsed.username, parsed.password,
            parsed.path or "/", parsed.params, parsed.query)


def _clash_provider_health_check_findings(
    proxy_providers: dict[str, dict[str, Any]],
    proxy_groups: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[RenderWarning]]:
    use_groups_by_provider: dict[str, list[str]] = {}
    use_group_count = 0
    groups_without_empty_fallback: list[str] = []
    for group in proxy_groups:
        group_name = str(group.get("name") or "").strip() or "Unnamed"
        if _clash_group_can_be_empty(group) and not str(group.get("empty-fallback") or "").strip():
            groups_without_empty_fallback.append(group_name)
        uses = [str(item).strip() for item in list(group.get("use") or []) if str(item).strip()]
        if not uses:
            continue
        use_group_count += 1
        for provider_key in uses:
            use_groups_by_provider.setdefault(provider_key, []).append(group_name)

    providers_missing_health_check: list[str] = []
    uncovered_use_groups: list[str] = []
    duplicate_probe_groups: set[str] = set()
    groups = {str(group.get("name")): group for group in proxy_groups}
    for provider_key, group_names in sorted(use_groups_by_provider.items()):
        health = dict(proxy_providers.get(provider_key, {}).get("health-check") or {})
        provider_checked = bool(health.get("enable") and health.get("url") and int(health.get("interval") or 0) > 0)
        provider_url = _normalized_health_check_url(health.get("url"))
        for name in group_names:
            group = groups[name]
            automatic = group.get("type") in {"url-test", "fallback", "load-balance"}
            group_checked = bool(automatic and group.get("url") and int(group.get("interval") or 0) > 0)
            group_url = _normalized_health_check_url(group.get("url"))
            # E-M-019 measured distinct URLs. v1.19.33 deduplicates the same
            # URL in the local review probe; other uncertain cases stay silent.
            if group_checked and provider_checked and provider_url and group_url and provider_url != group_url:
                duplicate_probe_groups.add(name)
            if automatic and not provider_checked and not group_checked:
                uncovered_use_groups.append(name)
                providers_missing_health_check.append(provider_key)
    providers_missing_health_check = sorted(set(providers_missing_health_check))

    details = {
        "use_group_count": use_group_count,
        "used_provider_count": len(use_groups_by_provider),
        "providers_missing_health_check": providers_missing_health_check,
        "use_groups_without_provider_health_check": sorted(set(uncovered_use_groups)),
        "use_groups_with_duplicate_health_check": sorted(duplicate_probe_groups),
        "groups_without_empty_fallback": sorted(set(groups_without_empty_fallback)),
    }
    blockers: list[RenderWarning] = []
    if providers_missing_health_check:
        blockers.append(
            RenderWarning(
                code="clash-provider-health-check-missing",
                message=(
                    "Automatic Clash use-groups lack both group-level probing and provider health-check: "
                    f"{', '.join(providers_missing_health_check)}"
                ),
                target="proxy-providers",
                severity="error",
            )
        )
    if groups_without_empty_fallback:
        blockers.append(RenderWarning(
            code="clash-use-group-empty-fallback-missing",
            message=("Clash groups whose membership can become empty require empty-fallback "
                     "(use REJECT to fail closed); otherwise COMPATIBLE sends traffic DIRECT: "
                     + ", ".join(details["groups_without_empty_fallback"])),
            target="proxy-groups",
            severity="error",
        ))
    return details, blockers


def _clash_build_blockers(
    policy_ir: PolicyIR,
    *,
    provider_has_nodes: dict[str, bool],
    referenced_contracts: dict[str, dict[str, Any]],
) -> tuple[list[RenderWarning], list[dict[str, Any]]]:
    contracts_by_id = {item.id: item for item in policy_ir.contracts}
    blockers: list[RenderWarning] = []
    referenced_summaries: list[dict[str, Any]] = []

    default_id = normalize_contract_id(policy_ir.default_contract_id)
    default_contract = contracts_by_id.get(default_id)
    default_action = (
        _route_action_for_target(policy_ir, default_id)
        if default_id in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}
        or (default_contract is not None and bool(default_contract.enabled))
        else ""
    )
    if _is_contracts_explicit(policy_ir) and default_action not in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT} and (
        not default_id or default_contract is None or not bool(default_contract.enabled)
    ):
        reason = "missing" if not default_id or default_contract is None else "disabled"
        blockers.append(
            RenderWarning(
                code=f"clash-default-contract-{reason}",
                message=(
                    "No enabled default route contract is available"
                    if reason == "missing"
                    else f"Default route contract {default_contract.display_name} is disabled"
                ),
                target=default_id or "default",
                severity="error",
            )
        )

    for contract_id, reference in referenced_contracts.items():
        contract = contracts_by_id.get(contract_id)
        if contract is None:
            referenced_summaries.append(dict(reference))
            blockers.append(
                RenderWarning(
                    code="clash-referenced-missing-contract",
                    message=f"Referenced route contract {reference['display_name']} does not exist",
                    target=reference["display_name"],
                    severity="error",
                )
            )
            continue
        if not bool(contract.enabled):
            referenced_summaries.append({**reference, "strategy_type": contract.strategy_type, "failure_action": contract.failure_action})
            blockers.append(
                RenderWarning(
                    code="clash-referenced-disabled-contract",
                    message=f"Referenced route contract {contract.display_name} is disabled",
                    target=contract.display_name,
                    severity="error",
                )
            )
            continue
        if _route_action(contract) in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT}:
            continue
        available_primary = False
        for pool_id in list(contract.primary_pools or []):
            legacy_group = contract_legacy_group(pool_id)
            if legacy_group in QUALITY_GROUPS and provider_has_nodes.get(legacy_group, False):
                available_primary = True
                break
        if available_primary:
            continue

        summary = {
            **reference,
            "strategy_type": contract.strategy_type,
            "failure_action": contract.failure_action,
        }
        referenced_summaries.append(summary)
        blockers.append(
            RenderWarning(
                code="clash-referenced-empty-contract",
                message=(
                    f"{contract.display_name} has no renderable primary pools; "
                    f"referenced by rules={reference['rule_entry_count']}, "
                    f"process-rules={reference['process_rule_count']}, "
                    f"external-proxy-programs={reference['external_proxy_program_count']}"
                ),
                target=contract.display_name,
                severity="error",
            )
        )
    return blockers, referenced_summaries


def build_clash_blocked_detail(
    policy_ir: PolicyIR,
    *,
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    provider_base_url: str = "",
    subscription_token: str = "",
    subscription_public_id: str = "",
    provider_url_builder: Callable[[str, str], str] | None = None,
    render_mode: str = "subscription",
    rendered_content: str | None = None,
    rendered_warnings: list[RenderWarning] | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
) -> dict[str, object]:
    compiled_entries, _ = _compiled_policy_rule_entries(policy_ir)
    compiled_entries, _ = _lower_policy_entries_for_client(compiled_entries, client="clash")
    provider_has_nodes = _clash_provider_has_nodes(policy_ir)
    referenced_contracts = _surge_referenced_contracts(policy_ir, compiled_entries, client="clash")
    blockers, referenced_summaries = _clash_build_blockers(
        policy_ir,
        provider_has_nodes=provider_has_nodes,
        referenced_contracts=referenced_contracts,
    )
    content = rendered_content
    diagnostics = list(rendered_warnings or [])
    if content is None:
        # The host-record warnings compare targets with the local host
        # aliases. Rendering here must use the aliases the HTTP boundary
        # captured, or those warnings disappear from the blocked detail.
        content, _, diagnostics = build_clash_profile_artifacts(
            policy_ir.nodes,
            list(policy_ir.rule_lines),
            profile=profile,
            profile_settings=profile_settings,
            policy_ir=policy_ir,
            local_host_aliases=local_host_aliases,
            provider_base_url=provider_base_url,
            subscription_token=subscription_token,
            subscription_public_id=subscription_public_id,
            provider_url_builder=provider_url_builder,
            render_mode=render_mode,
        )
    payload = yaml.safe_load(content) or {}
    proxy_providers = {
        str(key): dict(value or {})
        for key, value in dict(payload.get("proxy-providers") or {}).items()
    }
    proxy_groups = [dict(item or {}) for item in list(payload.get("proxy-groups") or [])]
    provider_health_details, provider_health_blockers = _clash_provider_health_check_findings(
        proxy_providers,
        proxy_groups,
    )
    blockers.extend(provider_health_blockers)
    blockers.extend(_validate_clash_cidr_overlaps(list(payload.get("rules") or [])))
    return {
        "code": "clash-build-blocked",
        "blockers": [item.to_dict() for item in blockers],
        "warnings": [item.to_dict() for item in diagnostics],
        "referenced_contracts": [dict(item) for item in referenced_summaries],
        "provider_health": provider_health_details,
    }


def _surge_auto_group_lines(
    name: str,
    members: list[str],
    *,
    timeout: int = 5,
    tolerance: int = 50,
) -> list[str]:
    return [
        _surge_requirement_group_line(
            _SMART_REQUIREMENT,
            f"{name} = smart, {', '.join(members)}",
        ),
        _surge_requirement_suffix_line(
            (
                f"{name} = url-test, {', '.join(members)}, "
                f"interval=300, timeout={timeout}, tolerance={tolerance}"
            ),
            "CORE_VERSION<22",
        ),
    ]


def _surge_international_group_members(
    plan: dict[str, object],
    country_members: dict[str, list[str]],
) -> list[str]:
    members: list[str] = []
    for country in list(plan["countries"]):
        if country == "美国":
            continue
        for node_name in list(country_members.get(str(country), [])):
            if node_name not in members:
                members.append(node_name)
    return members


def _surge_country_routed_pool_lines(
    pool_name: str,
    country_members: dict[str, list[str]],
    referenced_mode_keys: set[str],
    *,
    timeout: int,
    tolerance: int,
) -> tuple[list[str], list[str], bool]:
    helper_lines: list[str] = []
    country_lines: list[str] = []
    mode_names = _pool_mode_names(pool_name)
    plan = _country_routing_plan(pool_name, country_members)
    country_groups = list(plan["country_groups"])
    fallback_groups = list(plan["fallback_groups"])
    if not country_groups:
        if "auto" in referenced_mode_keys:
            helper_lines.append(f"{mode_names['auto']} = select, {QUALITY_REJECT}")
        return helper_lines, country_lines, False

    if referenced_mode_keys:
        for country in plan["countries"]:
            country_lines.extend(
                _surge_auto_group_lines(
                    _country_group_name(pool_name, str(country)),
                    list(country_members.get(str(country), [])),
                    timeout=timeout,
                    tolerance=tolerance,
                )
            )

        international_group = str(plan["international_group"] or "")
        if international_group:
            international_members = _surge_international_group_members(plan, country_members)
            country_lines.append(
                _surge_requirement_group_line(
                    _SMART_REQUIREMENT,
                    f"{international_group} = smart, {', '.join(international_members)}",
                )
            )
            country_lines.append(
                _surge_requirement_suffix_line(
                    (
                        f"{international_group} = url-test, {', '.join(international_members)}, "
                        f"interval=300, timeout={timeout}, tolerance={tolerance}"
                    ),
                    "CORE_VERSION<22",
                )
            )

    if "auto" in referenced_mode_keys:
        helper_lines.append(
            (
                f"{mode_names['auto']} = fallback, {', '.join([*fallback_groups, QUALITY_REJECT])}, "
                f"interval=300, timeout={timeout}"
            )
        )
    return helper_lines, country_lines, True


def _surge_pool_group_lines(
    group_names: dict[str, list[str]],
    country_group_names: dict[str, dict[str, list[str]]],
    referenced_helper_names: set[str],
    *,
    timeout: int,
    tolerance: int,
) -> tuple[list[str], dict[str, bool], list[RenderWarning]]:
    helper_lines: list[str] = []
    country_lines: list[str] = []
    available: dict[str, bool] = {}
    diagnostics: list[RenderWarning] = []
    for pool_name in QUALITY_GROUPS:
        referenced_mode_keys = _referenced_pool_mode_keys(referenced_helper_names, pool_name)
        if pool_name in _COUNTRY_ROUTED_QUALITY_GROUPS:
            routed_helper_lines, routed_country_lines, routed_available = _surge_country_routed_pool_lines(
                pool_name,
                country_group_names.get(pool_name, {}),
                referenced_mode_keys,
                timeout=timeout,
                tolerance=tolerance,
            )
            available[pool_name] = routed_available
            if not routed_available:
                diagnostics.append(
                    RenderWarning(
                        code="empty-pool",
                        message=f"{pool_name} has no renderable Surge nodes",
                        target=pool_name,
                        severity="error",
                    )
                )
            helper_lines.extend(routed_helper_lines)
            country_lines.extend(routed_country_lines)
            continue
        members = list(group_names.get(pool_name) or [])
        mode_names = _pool_mode_names(pool_name)
        if not referenced_mode_keys:
            available[pool_name] = bool(members)
            if not members:
                diagnostics.append(
                    RenderWarning(
                        code="empty-pool",
                        message=f"{pool_name} has no renderable Surge nodes",
                        target=pool_name,
                        severity="error",
                    )
                )
            continue
        if members:
            available[pool_name] = True
            if "auto" in referenced_mode_keys:
                helper_lines.extend(
                    _surge_auto_group_lines(
                        mode_names["auto"],
                        members,
                        timeout=timeout,
                        tolerance=tolerance,
                    )
                )
            continue

        available[pool_name] = False
        diagnostics.append(
            RenderWarning(
                code="empty-pool",
                message=f"{pool_name} has no renderable Surge nodes",
                target=pool_name,
                severity="error",
            )
        )
        if "auto" in referenced_mode_keys:
            helper_lines.append(f"{mode_names['auto']} = select, {QUALITY_REJECT}")
    if _CHAIN_INGRESS_GROUP_NAME in referenced_helper_names:
        chain_auto_members = _chain_ingress_members(
            available_medium=available.get(QUALITY_MEDIUM, False),
            available_bulk=available.get(QUALITY_BULK, False),
            mode_key="auto",
        )
        if chain_auto_members:
            helper_lines.append(
                (
                    f"{_CHAIN_INGRESS_GROUP_NAME} = fallback, {', '.join(chain_auto_members)}, "
                    f"interval=300, timeout={timeout}"
                )
            )
        else:
            helper_lines.append(f"{_CHAIN_INGRESS_GROUP_NAME} = select, {QUALITY_REJECT}")
    return [*helper_lines, *country_lines], available, diagnostics


def _surge_contract_group_lines(
    policy_ir: PolicyIR,
    *,
    pool_available: dict[str, bool],
    timeout: int,
) -> tuple[list[str], dict[str, bool], list[RenderWarning]]:
    lines: list[str] = []
    available_contracts: dict[str, bool] = {}
    diagnostics: list[RenderWarning] = []
    ad_block_group_names = {
        _business_group_display_name(group.name)
        for group in policy_ir.business_groups
        if group.mode == BUSINESS_GROUP_MODE_AD_BLOCK
    }
    for contract in sorted(policy_ir.contracts, key=lambda item: (item.sort_order, item.display_name, item.id)):
        # Ad-block business groups are rule planes, not selectable proxy
        # groups.  Their persisted contract record may share the historical
        # display name, but the business-group mode remains authoritative.
        if _business_group_display_name(contract.display_name) in ad_block_group_names:
            continue
        action = _route_action(contract)
        if action == ROUTE_ACTION_REJECT:
            available_contracts[contract.id] = bool(contract.enabled)
            if not bool(contract.enabled):
                diagnostics.append(
                    RenderWarning(
                        code="disabled-contract",
                        message=f"{contract.display_name} is disabled",
                        target=contract.display_name,
                        severity="error",
                    )
                )
            lines.append(f"{contract.display_name} = select, {QUALITY_REJECT}")
            continue
        if action == ROUTE_ACTION_DIRECT:
            available_contracts[contract.id] = True
            if bool(contract.enabled):
                lines.append(f"{contract.display_name} = select, DIRECT")
            else:
                available_contracts[contract.id] = False
                diagnostics.append(
                    RenderWarning(
                        code="disabled-contract",
                        message=f"{contract.display_name} is disabled",
                        target=contract.display_name,
                        severity="error",
                    )
                )
                lines.append(f"{contract.display_name} = select, {QUALITY_REJECT}")
            continue

        mode_key = "auto"
        primary_members: list[str] = []
        fallback_members: list[str] = []

        for pool_id in list(contract.primary_pools or []):
            legacy_group = contract_legacy_group(pool_id)
            if legacy_group in QUALITY_GROUPS and pool_available.get(legacy_group):
                primary_members.append(_pool_mode_names(legacy_group)[mode_key])
        for pool_id in list(contract.fallback_pools or []):
            legacy_group = contract_legacy_group(pool_id)
            if legacy_group in QUALITY_GROUPS and pool_available.get(legacy_group):
                fallback_members.append(_pool_mode_names(legacy_group)[mode_key])

        if not primary_members:
            available_contracts[contract.id] = False
            diagnostics.append(
                RenderWarning(
                    code="empty-contract",
                    message=f"{contract.display_name} has no renderable primary pools",
                    target=contract.display_name,
                    severity="error",
                )
            )
            lines.append(f"{contract.display_name} = select, {QUALITY_REJECT}")
            continue

        members = list(primary_members)
        if contract.strategy_type == CONTRACT_STRATEGY_FAILOVER:
            members.extend(item for item in fallback_members if item not in members)
        elif contract.failure_action == CONTRACT_FAILURE_DEGRADE:
            members.extend(item for item in fallback_members if item not in members)
        terminal = _terminal_member_for_contract(contract)
        if terminal not in members:
            members.append(terminal)
        available_contracts[contract.id] = True
        surge_group_type = _contract_group_type(contract)
        if surge_group_type == "load-balance":
            lines.append(f"{contract.display_name} = load-balance, {', '.join(members)}, persistent=1")
        elif surge_group_type == "fallback":
            lines.append(
                (
                    f"{contract.display_name} = fallback, {', '.join(members)}, "
                    f"interval=300, timeout={timeout}"
                )
            )
        else:
            lines.append(f"{contract.display_name} = {surge_group_type}, {', '.join(members)}")
    return lines, available_contracts, diagnostics


def _surge_tail_group_line(
    policy_ir: PolicyIR,
    *,
    available_contracts: dict[str, bool],
    pool_available: dict[str, bool],
) -> str:
    default_contract = _default_contract(policy_ir)
    if default_contract and available_contracts.get(default_contract.id):
        return (
            f"{_SURGE_DEFAULT_GROUP_NAME} = {_contract_group_type(default_contract)}, "
            f"{', '.join(_contract_members(policy_ir, default_contract, client='surge'))}"
        )
    default_id = normalize_contract_id(policy_ir.default_contract_id)
    persisted_default = _contract_by_id(policy_ir, default_id)
    default_action = (
        _route_action_for_target(policy_ir, default_id)
        if default_id in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}
        or (persisted_default is not None and bool(persisted_default.enabled))
        else ""
    )
    if _is_contracts_explicit(policy_ir):
        if default_action == ROUTE_ACTION_DIRECT:
            return f"{_SURGE_DEFAULT_GROUP_NAME} = select, DIRECT"
        return f"{_SURGE_DEFAULT_GROUP_NAME} = select, {QUALITY_REJECT}"
    members = [QUALITY_REJECT]
    if pool_available.get(QUALITY_CHAIN_HOME):
        members = [_pool_mode_names(QUALITY_CHAIN_HOME)["auto"], QUALITY_REJECT]
    return f"{_SURGE_DEFAULT_GROUP_NAME} = select, {', '.join(members)}"


def _surge_inline_system_rules(
    entries: list[PolicyRuleEntry],
    *,
    policy_ir: PolicyIR | None = None,
) -> list[str]:
    lines: list[str] = ["RULE-SET,SYSTEM,DIRECT"]
    for entry in entries:
        target = _surge_target_name(entry.target_contract_id, policy_ir=policy_ir)
        lines.append(entry.to_line(target_name=target))
    return lines


def _build_surge_rule_assets(
    compiled_entries: list[PolicyRuleEntry],
    policy_ir: PolicyIR | None = None,
) -> tuple[dict[str, str], dict[str, str], list[RenderWarning]]:
    domain_sets: dict[str, list[str]] = {}
    rule_sets: dict[str, list[str]] = {}
    diagnostics: list[RenderWarning] = []
    seen_rule_identities: set[tuple[str, str, tuple[str, ...]]] = set()

    for entry in compiled_entries:
        if entry.platform_scope == "mac" or entry.rule_type in _SURGE_MAC_ONLY_RULE_TYPES:
            diagnostics.append(
                RenderWarning(
                    code="mac-only-rule-ignored",
                    message=f"{entry.rule_type} is rendered only in surge-mac-overlay.conf",
                    target=entry.category_name or entry.value,
                    severity="info",
                )
            )
            continue

        if entry.source_kind == "system":
            continue

        identity = (entry.rule_type, entry.value, tuple(entry.extras))
        if entry.rule_type in _SURGE_IP_RULE_TYPES:
            if identity in seen_rule_identities:
                diagnostics.append(
                    RenderWarning(
                        code="duplicate-ip-rule",
                        message=f"Duplicate IP rule {entry.rule_type},{entry.value} ignored",
                        target=entry.category_name or entry.value,
                        severity="warning",
                    )
                )
                continue
            seen_rule_identities.add(identity)

        target_action = (
            _route_action_for_target(policy_ir, entry.target_contract_id)
            if policy_ir is not None
            else (
                ROUTE_ACTION_REJECT
                if entry.target_contract_id in {CONTRACT_AD_BLOCK, ROUTE_REJECT_ACTION}
                else ROUTE_ACTION_PROXY
            )
        )
        if target_action == ROUTE_ACTION_REJECT:
            if entry.rule_type in _SURGE_DOMAIN_RULE_TYPES:
                asset_key = "reject-domains"
                domain_sets.setdefault(asset_key, []).append(_surge_domain_set_value(entry))
            else:
                asset_key = "reject-rules"
                rule_sets.setdefault(asset_key, []).append(entry.to_ruleset_line())
            continue

        source_prefix = "manual" if entry.source_kind == "custom" else "catalog"
        asset_contract_id = (
            CONTRACT_DIRECT
            if target_action == ROUTE_ACTION_DIRECT
            else entry.target_contract_id
        )
        if entry.rule_type in _SURGE_DOMAIN_RULE_TYPES:
            asset_key = f"{source_prefix}-domains-{asset_contract_id}"
            domain_sets.setdefault(asset_key, []).append(_surge_domain_set_value(entry))
            continue
        if entry.rule_type in _SURGE_IP_RULE_TYPES:
            asset_key = f"ip-rules-{asset_contract_id}"
            rule_sets.setdefault(asset_key, []).append(entry.to_ruleset_line())
            continue
        asset_key = f"{source_prefix}-rules-{asset_contract_id}"
        rule_sets.setdefault(asset_key, []).append(entry.to_ruleset_line())

    rendered_domain_sets = {
        key: "\n".join(sorted({item for item in values if item})) + "\n"
        for key, values in domain_sets.items()
        if values
    }
    rendered_rule_sets = {
        key: "\n".join(values) + "\n"
        for key, values in rule_sets.items()
        if values
    }
    return rendered_domain_sets, rendered_rule_sets, diagnostics


def build_surge_profile_artifacts(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    managed_subscription_url: str,
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    *,
    policy_ir: PolicyIR | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
    intent: ConfigurationIntent | None = None,
    revision: str = "",
    asset_url_builder: Callable[[str, str], str] | None = None,
) -> SurgeProfileArtifacts:
    profile = intent.profile if intent is not None else profile
    base_ir = policy_ir or build_policy_ir(nodes, rule_lines, default_group_name=_SURGE_DEFAULT_GROUP_NAME)
    desired = intent or derive_configuration_intent(
        base_ir, profile_settings, profile=profile,
    )
    projection = project_configuration_intent(desired, "surge")
    base_ir = projection.policy
    surge_normalized = projection.settings
    ir = _enrich_policy_ir_for_target(
        base_ir,
        target="surge",
        profile=profile,
        normalized_settings=surge_normalized,
    )
    compiled_entries, compile_warnings = projection.compiled_rules()
    intent_rule_entries = list(compiled_entries)
    compiled_entries = projection.project_rules(compiled_entries)
    compiled_entries, dialect_warnings = _lower_policy_entries_for_client(compiled_entries, client="surge")
    compile_warnings.extend(dialect_warnings)
    surge_entries, cidr_diagnostics = _normalize_surge_cidr_entries(
        compiled_entries,
        policy_ir=ir,
    )
    grouped_nodes = _group_nodes(ir.nodes)
    surge_ipv6 = surge_normalized.get(LAZYCAT_PROFILE_SURGE_IPV6_KEY, True)
    lines = [
        f"#!MANAGED-CONFIG {managed_subscription_url} interval=1800 strict=false",
        "[General]",
        f"ipv6 = {'true' if surge_ipv6 else 'false'}",
        "proxy-test-url = https://cp.cloudflare.com/generate_204",
        "udp-policy-not-supported-behaviour = REJECT",
    ]
    if ir.dns.get("loglevel"):
        lines.append(f"loglevel = {ir.dns['loglevel']}")
    if ir.dns.get("block-quic"):
        lines.append(f"block-quic = {ir.dns['block-quic']}")
    if ir.dns.get("dns-server"):
        lines.append(f"dns-server = {', '.join(ir.dns['dns-server'])}")
    if ir.dns.get("encrypted-dns-server"):
        lines.append(f"encrypted-dns-server = {', '.join(ir.dns['encrypted-dns-server'])}")
    if "encrypted-dns-follow-outbound-mode" in ir.dns:
        lines.append(
            "encrypted-dns-follow-outbound-mode = "
            f"{'true' if ir.dns['encrypted-dns-follow-outbound-mode'] else 'false'}"
        )
    if profile == "lazycat":
        http_api = str(surge_normalized.get(LAZYCAT_PROFILE_SURGE_HTTP_API_KEY, "") or "").strip()
        http_api_secret = str(
            surge_normalized.get(LAZYCAT_PROFILE_SURGE_HTTP_API_SECRET_KEY, "") or ""
        ).strip()
        if http_api:
            http_api_value = f"{http_api_secret}@{http_api}" if http_api_secret else http_api
            lines.append(f"http-api = {http_api_value}")
            lines.append(
                "http-api-tls = "
                f"{'true' if ir.dns.get('http-api-tls') else 'false'}"
            )
            lines.append(
                "http-api-web-dashboard = "
                f"{'true' if ir.dns.get('http-api-web-dashboard') else 'false'}"
            )
    if profile == "lazycat":
        lazycat_settings = surge_normalized
        lines.append(
            "# lazycat profile: best-effort; set TUN bypass manually if client ignores these fields"
        )
        if lazycat_settings[LAZYCAT_PROFILE_SURGE_ALWAYS_REAL_IP_KEY]:
            lines.append(
                f"always-real-ip = {','.join(lazycat_settings[LAZYCAT_PROFILE_SURGE_ALWAYS_REAL_IP_KEY])}"
            )
        if lazycat_settings[LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY]:
            lines.append(
                f"tun-excluded-routes = {','.join(lazycat_settings[LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY])}"
            )
        skip_proxy = _sanitize_skip_proxy_entries(
            lazycat_settings.get(LAZYCAT_PROFILE_SURGE_SKIP_PROXY_KEY, []),
            excluded_routes=lazycat_settings.get(LAZYCAT_PROFILE_SURGE_TUN_EXCLUDED_ROUTES_KEY, []),
        )
        if skip_proxy:
            lines.append(f"skip-proxy = {', '.join(skip_proxy)}")
    host_records = {
        str(host).strip(): str(target).strip()
        for host, target in dict(ir.dns.get("host-records") or {}).items()
        if str(host).strip() and str(target).strip()
    }
    if host_records:
        lines.extend(["", "[Host]"])
        for host, target in host_records.items():
            lines.append(f"{host} = {target}")
    lines.extend(["", "[Proxy]"])

    skipped: list[str] = []
    diagnostics = [
        *derive_lazycat_host_record_diagnostics(
            projection.settings if profile == "lazycat" else None,
            target="surge",
            local_host_aliases=local_host_aliases,
        ),
        *ir.warnings,
        *compile_warnings,
        *cidr_diagnostics,
    ]
    blockers: list[RenderWarning] = []
    mac_only_rule_count = sum(
        1
        for item in ir.process_rules
        if item.enabled and item.contract_id and item.match_type in _SURGE_MAC_ONLY_RULE_TYPES
    )
    if mac_only_rule_count:
        diagnostics.append(
            RenderWarning(
                code="mac-only-rule-ignored",
                message=f"{mac_only_rule_count} macOS-only process rules render only in surge-mac-overlay.conf",
                target="surge-mac-overlay",
                severity="info",
            )
        )
    group_names: dict[str, list[str]] = {group: [] for group in QUALITY_GROUPS}
    country_group_names: dict[str, dict[str, list[str]]] = {group: {} for group in QUALITY_GROUPS}
    used_names: set[str] = set(_RESERVED_PROXY_NAMES) | {_SURGE_DEFAULT_GROUP_NAME}
    front_name_by_key = _inline_front_name_map(grouped_nodes, client="surge")
    wireguard_sections: list[str] = []

    for group in QUALITY_GROUPS:
        payloads: list[dict[str, Any]] = []
        names: list[str] = []
        renderable_nodes: list[NodeRecord] = []
        for node in grouped_nodes[group]:
            payload = _surge_proxy_payload(node, front_name_by_key=front_name_by_key)
            if not payload:
                skipped.append(node.name)
                diagnostics.append(
                    RenderWarning(
                        code="surge-unsupported-node",
                        message=_surge_unsupported_node_message(node),
                        target=node.protocol,
                        severity="warning",
                    )
                )
                continue
            udp = _clash_udp_value(node.raw or {}, node.protocol.lower(), udp_default_enabled=bool(
                surge_normalized.get(LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY, True)))
            if udp is not None:
                payload["udp-relay"] = udp
            payloads.append(payload)
            names.append(_safe_name(node.name))
            renderable_nodes.append(node)

        for idx, node_name in enumerate(_uniqueify_names(names, used_names)):
            payload = payloads[idx]
            if str(payload.get("proto", "")).strip().lower() == "wireguard":
                lines.append(_surge_proxy_line(node_name, payload))
                wireguard_sections.extend(["", *_surge_wireguard_section_lines(node_name, payload)])
            else:
                lines.append(_surge_proxy_line(node_name, payload))
            group_names[group].append(node_name)
            used_names.add(node_name)
            if group in _COUNTRY_ROUTED_QUALITY_GROUPS:
                country = _detect_node_country(renderable_nodes[idx].name)
                country_group_names[group].setdefault(country, []).append(node_name)

    diagnostics.extend(derive_protocol_diagnostics(ir.nodes, skipped, target="surge"))
    if wireguard_sections:
        lines.extend(wireguard_sections)

    lines.extend(["", "[Proxy Group]"])
    contract_lines, available_contracts, contract_diagnostics = _surge_contract_group_lines(
        ir,
        pool_available={group: bool(group_names.get(group)) for group in QUALITY_GROUPS},
        timeout=int(ir.http_processing.get("group-timeout") or 5),
    )
    diagnostics.extend(contract_diagnostics)
    # A contract without renderable primary pools is written as
    # "select, REJECT"; the others use their contract group type.
    fallback_contract_ids = {
        contract.id
        for contract in ir.contracts
        if available_contracts.get(contract.id) and _contract_group_type(contract) == "fallback"
    }
    referenced_helper_names = _referenced_helper_group_names(
        ir,
        client="surge",
        available_pools={group for group in QUALITY_GROUPS if group_names.get(group)},
        has_chain_nodes=bool(group_names.get(QUALITY_CHAIN_HOME)),
    )
    pool_lines, pool_available, pool_diagnostics = _surge_pool_group_lines(
        group_names,
        country_group_names,
        referenced_helper_names,
        timeout=int(ir.http_processing.get("group-timeout") or 5),
        tolerance=int(ir.http_processing.get("group-tolerance") or 50),
    )
    lines.extend(contract_lines)
    lines.append(_surge_tail_group_line(ir, available_contracts=available_contracts, pool_available=pool_available))
    lines.extend(pool_lines)
    diagnostics.extend(pool_diagnostics)

    asset_base_url = _surge_asset_base_url(managed_subscription_url)
    domain_sets, rule_sets, asset_diagnostics = _build_surge_rule_assets(surge_entries, policy_ir=ir)
    diagnostics.extend(asset_diagnostics)

    system_entries = [
        entry
        for entry in surge_entries
        if entry.source_kind == "system"
        and entry.rule_type not in _SURGE_MAC_ONLY_RULE_TYPES
    ]
    system_domain_entries = [entry for entry in system_entries if entry.rule_type in _SURGE_DOMAIN_RULE_TYPES]
    system_rule_entries = [
        entry
        for entry in system_entries
        if entry.rule_type not in _SURGE_DOMAIN_RULE_TYPES and entry.rule_type not in _SURGE_MAC_ONLY_RULE_TYPES
    ]

    referenced_contracts = _surge_referenced_contracts(ir, surge_entries)
    contract_blockers, referenced_contract_summaries = _surge_build_blockers(
        ir,
        available_contracts=available_contracts,
        referenced_contracts=referenced_contracts,
    )
    blockers.extend(contract_blockers)
    blockers.extend(_validate_surge_cidr_overlaps(surge_entries))

    lines.extend(["", "[Rule]"])
    for asset_key in sorted(domain_sets, key=_surge_asset_sort_key):
        if asset_key == "reject-domains":
            asset_url = asset_url_builder("domain-set", asset_key) if asset_url_builder else _surge_asset_url(asset_base_url, "domain-set", asset_key)
            lines.append(f"DOMAIN-SET,{asset_url},{QUALITY_REJECT},pre-matching")
    for asset_key in sorted(rule_sets, key=_surge_asset_sort_key):
        if asset_key == "reject-rules":
            asset_url = asset_url_builder("rule-set", asset_key) if asset_url_builder else _surge_asset_url(asset_base_url, "rule-set", asset_key)
            lines.append(f"RULE-SET,{asset_url},{QUALITY_REJECT},pre-matching")
    lines.extend(_surge_inline_system_rules(system_domain_entries + system_rule_entries, policy_ir=ir))
    for asset_key in sorted(domain_sets, key=_surge_asset_sort_key):
        if asset_key == "reject-domains":
            continue
        asset_url = asset_url_builder("domain-set", asset_key) if asset_url_builder else _surge_asset_url(asset_base_url, "domain-set", asset_key)
        lines.append(
            f"DOMAIN-SET,{asset_url},{_surge_asset_policy(asset_key, policy_ir=ir)}"
        )
    for asset_key in sorted(rule_sets, key=_surge_asset_sort_key):
        if asset_key == "reject-rules":
            continue
        asset_url = asset_url_builder("rule-set", asset_key) if asset_url_builder else _surge_asset_url(asset_base_url, "rule-set", asset_key)
        lines.append(
            f"RULE-SET,{asset_url},{_surge_asset_policy(asset_key, policy_ir=ir)}"
        )
    lines.append(f"FINAL,{_SURGE_DEFAULT_GROUP_NAME},dns-failed")
    lines.append("")

    if profile == "lazycat":
        url_rewrite = list(ir.http_processing.get("url-rewrite") or [])
        if url_rewrite:
            lines.extend(["[URL Rewrite]", *url_rewrite, ""])
        header_rewrite = list(ir.http_processing.get("header-rewrite") or [])
        if header_rewrite:
            lines.extend(["[Header Rewrite]", *header_rewrite, ""])
        body_rewrite = list(ir.http_processing.get("body-rewrite") or [])
        jq_body_rewrite = list(ir.http_processing.get("jq-body-rewrite") or [])
        if body_rewrite or jq_body_rewrite:
            lines.extend(["[Body Rewrite]", *body_rewrite, *jq_body_rewrite, ""])
        map_local = list(ir.http_processing.get("map-local") or [])
        if map_local:
            lines.extend(["[Map Local]", *map_local, ""])
        mitm_payload = dict(ir.http_processing.get("mitm") or {})
        mitm_hostnames = list(mitm_payload.get("hostname") or [])
        if "*" in mitm_hostnames:
            diagnostics.append(RenderWarning(code="surge-mitm-global-refused", message="Global MITM hostname * omitted; use explicit hosts", target="mitm.hostname", severity="warning", bucket="refused"))
            mitm_hostnames = [host for host in mitm_hostnames if host != "*"]
        if (
            mitm_hostnames
            or "skip-server-cert-verify" in mitm_payload
            or "h2" in mitm_payload
            or "tcp-connection" in mitm_payload
        ):
            lines.append("[MITM]")
            if mitm_hostnames:
                lines.append(f"hostname = {', '.join(mitm_hostnames)}")
            if "skip-server-cert-verify" in mitm_payload:
                lines.append(
                    "skip-server-cert-verify = "
                    f"{'true' if mitm_payload['skip-server-cert-verify'] else 'false'}"
                )
            if "h2" in mitm_payload:
                lines.append(f"h2 = {'true' if mitm_payload['h2'] else 'false'}")
            if "tcp-connection" in mitm_payload:
                lines.append(
                    "tcp-connection = "
                    f"{'true' if mitm_payload['tcp-connection'] else 'false'}"
                )
            lines.append("")

    subscription_metadata = _surge_subscription_metadata(
        managed_subscription_url=managed_subscription_url,
        asset_base_url=asset_base_url,
        revision=revision,
        domain_set_count=len(domain_sets),
        rule_set_count=len(rule_sets),
    )
    lines[1:1] = [*_surge_subscription_metadata_lines(subscription_metadata), ""]

    # The strict warning describes fallback groups, so it must not count the
    # strict contracts that this config writes as "select, REJECT".
    diagnostics.extend(count_strict_contracts_rendered_as_fallback(
        projection.diagnostics, projection.policy, "surge", fallback_contract_ids,
    ))
    diagnostics.extend(routing_intent_diagnostics(
        intent_rule_entries, target="surge", default_action=_route_action_for_target(ir, ir.default_contract_id),
        ip_resolution=projection.ip_resolution, projection=projection,
    ))
    return SurgeProfileArtifacts(
        main_conf="\n".join(lines),
        domain_sets=domain_sets,
        rule_sets=rule_sets,
        subscription_metadata=subscription_metadata,
        diagnostics=diagnostics,
        blockers=blockers,
        blocked=bool(blockers),
        referenced_contracts=referenced_contract_summaries,
        skipped=skipped,
    )


def _clash_country_group_payloads(
    pool_name: str,
    *,
    provider_key: str,
    nodes: list[NodeRecord],
    referenced_mode_keys: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    helper_payloads: list[dict[str, Any]] = []
    country_payloads: list[dict[str, Any]] = []
    mode_names = _pool_mode_names(pool_name)
    plan = _country_routing_plan(pool_name, _country_buckets(nodes))
    country_groups = list(plan["country_groups"])
    fallback_groups = list(plan["fallback_groups"])
    if not country_groups:
        if "auto" in referenced_mode_keys:
            helper_payloads.append({"name": mode_names["auto"], "type": "select", "proxies": [QUALITY_REJECT]})
        return helper_payloads, country_payloads

    if referenced_mode_keys:
        for country in plan["countries"]:
            payload: dict[str, Any] = {
                "name": _country_group_name(pool_name, str(country)),
                "type": "url-test",
                "use": [provider_key],
                "url": "https://cp.cloudflare.com/generate_204",
                "interval": 300,
                "tolerance": 50,
            }
            if country == _OTHER_COUNTRY:
                payload["exclude-filter"] = _known_country_regex()
            else:
                payload["filter"] = _country_regex(str(country))
            country_payloads.append(payload)

        international_group = str(plan["international_group"] or "")
        if international_group:
            country_payloads.append(
                {
                    "name": international_group,
                    "type": "url-test",
                    "proxies": list(plan["non_preferred_groups"]),
                    "url": "https://cp.cloudflare.com/generate_204",
                    "interval": 300,
                    "tolerance": 50,
                }
            )

    if "auto" in referenced_mode_keys:
        helper_payloads.append(
            {
                "name": mode_names["auto"],
                "type": "fallback",
                "proxies": [*fallback_groups, QUALITY_REJECT],
                "url": "https://cp.cloudflare.com/generate_204",
                "interval": 300,
            }
        )
    return helper_payloads, country_payloads


def _clash_group_payloads(
    policy_ir: PolicyIR,
    provider_has_nodes: dict[str, bool],
    grouped_nodes: dict[str, list[NodeRecord]],
    referenced_helper_names: set[str],
) -> list[dict[str, Any]]:
    entry_payloads: list[dict[str, Any]] = []
    helper_payloads: list[dict[str, Any]] = []
    country_payloads: list[dict[str, Any]] = []
    for group in _ordered_business_groups(policy_ir):
        if group.mode == BUSINESS_GROUP_MODE_AD_BLOCK:
            continue
        contract = _route_contract_for_group(policy_ir, group)
        group_type = _contract_group_type(contract)
        group_payload = {
            "name": _business_group_display_name(group.name),
            "type": group_type,
            "proxies": _business_group_members(policy_ir, group, client="clash"),
        }
        if group_type == "load-balance":
            group_payload["strategy"] = "consistent-hashing"
            group_payload["url"] = "https://cp.cloudflare.com/generate_204"
            group_payload["interval"] = 300
        entry_payloads.append(group_payload)
    for pool_name in QUALITY_GROUPS:
        mode_names = _pool_mode_names(pool_name)
        referenced_mode_keys = _referenced_pool_mode_keys(referenced_helper_names, pool_name)
        if not referenced_mode_keys:
            continue
        if provider_has_nodes.get(pool_name):
            provider_key = _clash_provider_key(pool_name)
            if pool_name in _COUNTRY_ROUTED_QUALITY_GROUPS:
                helper_items, country_items = _clash_country_group_payloads(
                    pool_name,
                    provider_key=provider_key,
                    nodes=grouped_nodes.get(pool_name, []),
                    referenced_mode_keys=referenced_mode_keys,
                )
                helper_payloads.extend(helper_items)
                country_payloads.extend(country_items)
                continue
            if "auto" in referenced_mode_keys:
                helper_payloads.append(
                    {
                        "name": mode_names["auto"],
                        "type": "url-test",
                        "use": [provider_key],
                        "url": "https://cp.cloudflare.com/generate_204",
                        "interval": 300,
                        "tolerance": 50,
                    }
                )
            continue
        if "auto" in referenced_mode_keys:
            helper_payloads.append(
                {
                    "name": mode_names["auto"],
                    "type": "select",
                    "proxies": [QUALITY_REJECT],
                }
            )
    if _CHAIN_INGRESS_GROUP_NAME in referenced_helper_names:
        chain_auto_members = _chain_ingress_members(
            available_medium=provider_has_nodes.get(QUALITY_MEDIUM, False),
            available_bulk=provider_has_nodes.get(QUALITY_BULK, False),
            mode_key="auto",
        )
        helper_payloads.append(
            {
                "name": _CHAIN_INGRESS_GROUP_NAME,
                "type": "url-test" if chain_auto_members else "select",
                "proxies": chain_auto_members or [QUALITY_REJECT],
                **(
                    {
                        "url": "https://cp.cloudflare.com/generate_204",
                        "interval": 300,
                        "tolerance": 50,
                    }
                    if chain_auto_members
                    else {}
                ),
            }
        )
    groups = [*entry_payloads, *helper_payloads, *country_payloads]
    for group in groups:
        if _clash_group_can_be_empty(group):
            group["empty-fallback"] = "REJECT"
    return groups


def build_clash_config(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    *,
    policy_ir: PolicyIR | None = None,
    provider_base_url: str = "",
    subscription_token: str = "",
    subscription_public_id: str = "",
    provider_url_builder: Callable[[str, str], str] | None = None,
    rule_provider_url_builder: Callable[[str, str], str] | None = None,
) -> tuple[str, list[str]]:
    content, skipped, _ = build_clash_profile_artifacts(
        nodes,
        rule_lines,
        profile=profile,
        profile_settings=profile_settings,
        policy_ir=policy_ir,
        provider_base_url=provider_base_url,
        subscription_token=subscription_token,
        subscription_public_id=subscription_public_id,
        provider_url_builder=provider_url_builder,
        rule_provider_url_builder=rule_provider_url_builder,
    )
    return content, skipped


def build_clash_provider_config(
    nodes: list[NodeRecord],
    provider_key: str,
    *,
    policy_ir: PolicyIR | None = None,
    udp_default_enabled: bool = True,
) -> tuple[str, list[str]]:
    ir = policy_ir or build_policy_ir(nodes, [])
    projection = project_configuration_intent(
        derive_configuration_intent(
            ir, {LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY: udp_default_enabled}, profile="lazycat",
        ), "clash",
    )
    ir = projection.policy
    udp_default_enabled = bool(projection.settings[LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY])
    quality_group = resolve_clash_provider_quality_group(provider_key)
    if not quality_group:
        raise ValueError("invalid clash provider key")
    grouped_nodes = _group_nodes(ir.nodes)
    if quality_group == QUALITY_CHAIN_HOME:
        front_name_by_key = _clash_front_name_map(
            grouped_nodes,
            udp_default_enabled=udp_default_enabled,
        )
        proxies = []
        skipped = []
        for node in grouped_nodes[quality_group]:
            payload = _clash_proxy(
                node,
                udp_default_enabled=udp_default_enabled,
                front_name_by_key=front_name_by_key,
            )
            if not payload:
                skipped.append(node.name)
                continue
            proxies.append(payload)
        if proxies:
            names = _uniqueify_names(
                [str(item.get("name", "")) for item in proxies],
                _RESERVED_PROXY_NAMES,
            )
            for index, new_name in enumerate(names):
                proxies[index]["name"] = new_name
    else:
        proxies, skipped, _ = _build_clash_provider_proxies(
            grouped_nodes[quality_group],
            udp_default_enabled=udp_default_enabled,
        )
    return yaml.safe_dump({"proxies": proxies}, allow_unicode=True, sort_keys=False), skipped


def build_clash_rule_provider_config(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    asset_key: str,
    *,
    policy_ir: PolicyIR | None = None,
    profile: str = "lazycat",
    profile_settings: dict[str, object] | None = None,
    intent: ConfigurationIntent | None = None,
) -> str:
    profile = intent.profile if intent is not None else profile
    base_ir = policy_ir or build_policy_ir(nodes, rule_lines)
    desired = intent or derive_configuration_intent(
        base_ir, profile_settings, profile=profile,
    )
    projection = project_configuration_intent(desired, "clash")
    base_ir = projection.policy
    normalized_settings = projection.settings
    ir = _enrich_policy_ir_for_target(
        base_ir,
        target="clash",
        profile=profile,
        normalized_settings=normalized_settings,
    )
    compiled_entries, _ = projection.compiled_rules()
    compiled_entries = projection.project_rules(compiled_entries)
    compiled_entries, _ = _lower_policy_entries_for_client(compiled_entries, client="clash")
    assets, _, _ = _build_clash_rule_provider_assets(compiled_entries, policy_ir=ir)
    payload = assets.get(asset_key)
    if not payload:
        raise ValueError("invalid clash rule provider key")
    return str(payload.get("content") or "")


def build_clash_export_bundle(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    *,
    device_name: str,
    device_key: str,
    subscription_token: str,
    subscription_public_id: str = "",
    profile: str = "lazycat",
    profile_settings: dict[str, object] | None = None,
    policy_ir: PolicyIR | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
    generated_at: str = "",
) -> dict[str, Any]:
    ir = policy_ir or build_policy_ir(nodes, rule_lines)
    normalized_settings = (
        normalize_lazycat_profile_settings(profile_settings)
        if profile in {"lazycat", "raw"}
        else {}
    )
    content, skipped, warnings = build_clash_profile_artifacts(
        nodes,
        rule_lines,
        profile=profile,
        profile_settings=normalized_settings or profile_settings,
        policy_ir=ir,
        local_host_aliases=local_host_aliases,
        subscription_token=subscription_token,
        subscription_public_id=subscription_public_id,
        render_mode="export",
    )
    udp_default_enabled = bool(
        normalized_settings.get(LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY, True)
    )
    provider_files: dict[str, str] = {}
    provider_keys: list[str] = []
    provider_node_counts: dict[str, int] = {}
    total_nodes = 0
    for group in QUALITY_GROUPS:
        provider_key = _clash_provider_key(group)
        provider_text, _ = build_clash_provider_config(
            nodes,
            provider_key,
            policy_ir=ir,
            udp_default_enabled=udp_default_enabled,
        )
        provider_files[f"providers/{provider_key}.yaml"] = provider_text
        provider_keys.append(provider_key)
        provider_payload = yaml.safe_load(provider_text) or {}
        provider_count = len(provider_payload.get("proxies", []))
        provider_node_counts[provider_key] = provider_count
        total_nodes += provider_count

    # Delivery metadata is an explicit input, sampled by the HTTP boundary.
    # An omitted stamp stays empty, so offline rendering is reproducible too.
    final_generated_at = str(generated_at).strip()
    manifest = {
        "generated_at": final_generated_at,
        "device_name": device_name,
        "device_key": device_key,
        "subscription_id": subscription_public_id,
        "provider_count": len(provider_keys),
        "node_count": total_nodes,
        "rule_line_count": len(ir.rule_lines),
        "skipped_count": len(skipped),
        "provider_keys": provider_keys,
        "kernel_target": "mihomo-meta",
        "compatibility_note": "This export targets Mihomo / Clash Meta only.",
    }
    readme_text = "\n".join(
        [
            f"{device_name} Clash 导出包",
            "",
            f"device_name: {device_name}",
            f"device_key: {device_key}",
            f"subscription_id: {subscription_public_id}",
            f"generated_at: {final_generated_at}",
            f"provider_count: {len(provider_keys)}",
            f"node_count: {total_nodes}",
            "compatibility: Mihomo / Clash Meta only",
            "compatibility_note: 不承诺通用 Clash 内核兼容",
            "",
            "内容：",
            "- clash.yaml",
            *[f"- providers/{provider_key}.yaml" for provider_key in provider_keys],
            "- manifest.json",
        ]
    )
    files = {
        "README.txt": readme_text,
        "clash.yaml": content,
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        **provider_files,
    }
    return {
        "files": files,
        "manifest": manifest,
        "readme_text": readme_text,
        "warnings": warnings,
        "skipped": skipped,
        "provider_node_counts": provider_node_counts,
    }


def build_clash_audit_markdown(
    bundle: dict[str, Any],
    *,
    profile: str,
    base_url: str = "",
    warnings: list[RenderWarning] | None = None,
    blockers: list[RenderWarning] | None = None,
) -> str:
    files = dict(bundle.get("files") or {})
    manifest = dict(bundle.get("manifest") or {})
    clash_payload = yaml.safe_load(files.get("clash.yaml", "")) or {}
    provider_paths = {}
    for provider_key in manifest.get("provider_keys") or []:
        provider_paths[str(provider_key)] = f"./providers/{provider_key}.yaml"
    actual_provider_paths = {
        str(key): str((value or {}).get("path") or "")
        for key, value in dict(clash_payload.get("proxy-providers") or {}).items()
    }
    provider_paths_ok = actual_provider_paths == provider_paths
    mixed_port_expected = profile in {"lazycat", "raw"}
    mixed_port_ok = "mixed-port" in clash_payload

    udp_missing: list[str] = []
    for path, content in files.items():
        if not path.startswith("providers/") or not path.endswith(".yaml"):
            continue
        payload = yaml.safe_load(content) or {}
        for proxy in list(payload.get("proxies") or []):
            protocol = str(proxy.get("type") or "").strip().lower()
            if protocol not in CLASH_UDP_SUPPORTED_PROTOCOLS:
                continue
            if not isinstance(proxy.get("udp"), bool):
                udp_missing.append(str(proxy.get("name") or "Unnamed"))
    udp_explicit_ok = not udp_missing

    # Stage-one intent diagnostics are management-only. Keep the downloadable
    # audit file byte-compatible with the existing delivery contract too.
    warning_items = [
        item for item in (warnings if warnings is not None else bundle.get("warnings") or [])
        if not item.code.startswith("intent-")
    ]
    provider_health_details, provider_health_blockers = _clash_provider_health_check_findings(
        {
            str(key): dict(value or {})
            for key, value in dict(clash_payload.get("proxy-providers") or {}).items()
        },
        [dict(item or {}) for item in list(clash_payload.get("proxy-groups") or [])],
    )
    cidr_blockers = _validate_clash_cidr_overlaps(list(clash_payload.get("rules") or []))
    blocker_items = [*(blockers or []), *provider_health_blockers, *cidr_blockers]
    warning_codes = [item.code for item in warning_items]
    blocker_codes = [item.code for item in blocker_items]

    lines = [
        "# Clash Bundle Audit",
        "",
        "## Metadata",
        f"- generated_at: {manifest.get('generated_at', '')}",
        f"- base_url: {str(base_url or '').strip() or '(server-side export)'}",
        f"- profile: {profile}",
        f"- device_name: {manifest.get('device_name', '')}",
        f"- device_key: {manifest.get('device_key', '')}",
        f"- subscription_id: {manifest.get('subscription_id', '')}",
        f"- provider_count: {manifest.get('provider_count', 0)}",
        f"- node_count: {manifest.get('node_count', 0)}",
        f"- rule_line_count: {manifest.get('rule_line_count', 0)}",
        "",
        "## Providers",
    ]
    for provider_key, count in sorted((bundle.get("provider_node_counts") or {}).items()):
        lines.append(f"- {provider_key}: {count}")
    lines.extend(
        [
            "",
            "## Checks",
            f"- render-warnings stripped: {'yes' if 'render-warnings' not in clash_payload else 'no'}",
            f"- file-provider paths consistent: {'yes' if provider_paths_ok else 'no'}",
            f"- mixed-port present: {'yes' if mixed_port_ok else ('no' if mixed_port_expected else 'n/a')}",
            f"- UDP explicit on supported proxies: {'yes' if udp_explicit_ok else 'no'}",
            (
                "- group health-check coverage present: "
                f"{'yes' if not provider_health_details['providers_missing_health_check'] else 'no'}"
            ),
            (
                "- use-groups covered by group or provider health-check: "
                f"{'yes' if not provider_health_details['use_groups_without_provider_health_check'] else 'no'}"
            ),
            (
                "- different-URL duplicate group/provider health-check absent: "
                f"{'yes' if not provider_health_details['use_groups_with_duplicate_health_check'] else 'no'}"
            ),
            (
                "- empty-fallback present on potentially empty groups: "
                f"{'yes' if not provider_health_details['groups_without_empty_fallback'] else 'no'}"
            ),
            f"- residual CIDR overlap count: {len(cidr_blockers)}",
            "",
            "## Diagnostics",
            f"- blocker_count: {len(blocker_items)}",
            f"- warning_count: {len(warning_items)}",
            f"- blocker_codes: {', '.join(blocker_codes) if blocker_codes else '(none)'}",
            f"- warning_codes: {', '.join(warning_codes) if warning_codes else '(none)'}",
            f"- use_group_count: {provider_health_details['use_group_count']}",
        ]
    )
    if udp_missing:
        lines.append(f"- udp_missing: {', '.join(sorted(udp_missing))}")
    for warning in warning_items:
        if warning.bucket == "refused":
            lines.append(f"- {warning.code}: {warning.message}")
    if provider_health_details["providers_missing_health_check"]:
        lines.append(
            "- providers_missing_health_check: "
            + ", ".join(provider_health_details["providers_missing_health_check"])
        )
    if provider_health_details["use_groups_without_provider_health_check"]:
        lines.append(
            "- use_groups_without_provider_health_check: "
            + ", ".join(provider_health_details["use_groups_without_provider_health_check"])
        )
    for finding in ("use_groups_with_duplicate_health_check", "groups_without_empty_fallback"):
        if provider_health_details[finding]:
            lines.append(f"- {finding}: " + ", ".join(provider_health_details[finding]))
    lines.extend(
        [
            "",
            "## Re-audit Workflow",
            "1. 解压 zip，审核 `clash.yaml` 与 `AUDIT.md`，不要把在线订阅和离线包混审。",
            "2. 复核 `proxy-providers` 路径是否全部指向 `./providers/*.yaml`。",
            "3. 复核所有支持 UDP 的节点是否显式带 `udp: true|false`。",
            "4. 复核 `use` 型自动组是否有组级测速，或由 provider health-check 覆盖。",
            "5. 仅将 use 组和 provider 均启用有效测速且规范化 URL 不同报告为重复；同 URL 或无法静态确定的不报告。默认保留组级测速。",
            "6. 复核成员可能为空的组是否显式写 empty-fallback: REJECT。",
            "7. 复核 `rules` 中是否仍有同网段、不同目标组的残留 CIDR 冲突。",
        ]
    )
    return "\n".join(lines) + "\n"


def _shadowrocket_country_routed_pool_lines(
    pool_name: str,
    country_members: dict[str, list[str]],
    referenced_mode_keys: set[str],
) -> tuple[list[str], list[str], bool]:
    helper_lines: list[str] = []
    country_lines: list[str] = []
    mode_names = _pool_mode_names(pool_name)
    plan = _country_routing_plan(pool_name, country_members)
    country_groups = list(plan["country_groups"])
    fallback_groups = list(plan["fallback_groups"])
    if not country_groups:
        if "auto" in referenced_mode_keys:
            helper_lines.append(f"{mode_names['auto']} = select, {QUALITY_REJECT}")
        return helper_lines, country_lines, False

    if referenced_mode_keys:
        for country in plan["countries"]:
            country_lines.append(
                f"{_country_group_name(pool_name, str(country))} = url-test, {', '.join(country_members.get(str(country), []))}, url=https://cp.cloudflare.com/generate_204, interval=300"
            )

        international_group = str(plan["international_group"] or "")
        if international_group:
            country_lines.append(
                f"{international_group} = url-test, {', '.join(plan['non_preferred_groups'])}, url=https://cp.cloudflare.com/generate_204, interval=300"
            )

    if "auto" in referenced_mode_keys:
        helper_lines.append(
            f"{mode_names['auto']} = fallback, {', '.join([*fallback_groups, QUALITY_REJECT])}, url=https://cp.cloudflare.com/generate_204, interval=300"
        )
    return helper_lines, country_lines, True


def _shadowrocket_proxy_group_lines(
    policy_ir: PolicyIR,
    group_names: dict[str, list[str]],
    country_group_names: dict[str, dict[str, list[str]]],
    referenced_helper_names: set[str],
) -> list[str]:
    entry_lines: list[str] = []
    helper_lines: list[str] = []
    country_lines: list[str] = []
    for group in _ordered_business_groups(policy_ir):
        if group.mode == BUSINESS_GROUP_MODE_AD_BLOCK:
            continue
        display_name = _business_group_display_name(group.name)
        contract = _route_contract_for_group(policy_ir, group)
        sr_group_type = _contract_group_type(contract)
        sr_members = ', '.join(_business_group_members(policy_ir, group, client='shadowrocket'))
        if sr_group_type == "load-balance":
            entry_lines.append(f"{display_name} = load-balance, {sr_members}, persistent=1")
        else:
            entry_lines.append(f"{display_name} = {sr_group_type}, {sr_members}")
    for pool_name in QUALITY_GROUPS:
        mode_names = _pool_mode_names(pool_name)
        referenced_mode_keys = _referenced_pool_mode_keys(referenced_helper_names, pool_name)
        if not referenced_mode_keys:
            continue
        if pool_name in _COUNTRY_ROUTED_QUALITY_GROUPS:
            routed_helper_lines, routed_country_lines, _ = _shadowrocket_country_routed_pool_lines(
                pool_name,
                country_group_names.get(pool_name, {}),
                referenced_mode_keys,
            )
            helper_lines.extend(routed_helper_lines)
            country_lines.extend(routed_country_lines)
            continue
        members = group_names[pool_name] if group_names[pool_name] else [QUALITY_REJECT]
        if "auto" in referenced_mode_keys:
            helper_lines.append(
                f"{mode_names['auto']} = url-test, {', '.join(members)}, url=https://cp.cloudflare.com/generate_204, interval=300"
            )
    if _CHAIN_INGRESS_GROUP_NAME in referenced_helper_names:
        chain_auto_members = _chain_ingress_members(
            available_medium=bool(group_names.get(QUALITY_MEDIUM)),
            available_bulk=bool(group_names.get(QUALITY_BULK)),
            mode_key="auto",
        )
        if chain_auto_members:
            helper_lines.append(
                f"{_CHAIN_INGRESS_GROUP_NAME} = url-test, {', '.join(chain_auto_members)}, url=https://cp.cloudflare.com/generate_204, interval=300"
            )
        else:
            helper_lines.append(f"{_CHAIN_INGRESS_GROUP_NAME} = select, {QUALITY_REJECT}")
    return [*entry_lines, *helper_lines, *country_lines]


def _shadowrocket_node_uri_unsupported_reason(node: NodeRecord) -> str:
    raw = node.raw or {}
    if node.protocol.lower() in {"vmess", "vless", "trojan"} and _raw_transport_type(raw) not in {"", "tcp", "ws"}:
        return "transport parameters are unsupported by the node URI renderer"
    if node.protocol.lower() == "trojan" and not raw.get("source_uri") and (
        _raw_transport_type(raw) == "ws" or raw.get("alpn") or
        _first_raw(raw, ("client_fingerprint", "client-fingerprint", "fp"))
    ):
        return "native Trojan transport or TLS fields are unsupported by the node URI renderer"
    return ""


def _shadowrocket_inline_unsupported_reason(node: NodeRecord) -> str:
    raw = node.raw or {}
    if node.protocol.lower() == "ss" and raw.get("plugin"):
        return "SS plugin parameters require node URI import"
    if node.protocol.lower() in {"vmess", "vless", "trojan"} and _raw_transport_type(raw) not in {"", "tcp", "ws"}:
        return "transport parameters require node URI import"
    if node.protocol.lower() == "vmess" and (_first_raw_int(raw, ("alterId", "alter-id")) or 0) > 0:
        return "legacy alterId > 0 is not verified for inline rendering"
    if _first_raw(raw, ("packet_encoding", "packet-encoding")):
        return "unverified packet encoding requires node URI import"
    if node.protocol.lower() == "vless" and _first_raw(raw, ("flow",)) not in {"", "xtls-rprx-vision"}:
        return "unverified VLESS flow requires node URI import"
    return ""


def _shadowrocket_available_contracts(policy_ir: PolicyIR) -> dict[str, bool]:
    grouped_nodes = _group_nodes(policy_ir.nodes)
    available: dict[str, bool] = {}
    for contract in policy_ir.contracts:
        if not bool(contract.enabled):
            available[contract.id] = False
            continue
        action = _route_action(contract)
        if action in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT}:
            available[contract.id] = True
            continue
        renderable = False
        for pool_id in list(contract.primary_pools or []):
            quality_group = contract_legacy_group(pool_id)
            if quality_group not in QUALITY_GROUPS:
                continue
            for node in grouped_nodes.get(quality_group, []):
                if _shadowrocket_inline_unsupported_reason(node):
                    continue
                if _shadowrocket_proxy_payload(node):
                    renderable = True
                    break
            if renderable:
                break
        available[contract.id] = renderable
    return available


def _shadowrocket_rule_artifacts(
    policy_ir: PolicyIR, managed_subscription_url: str,
    *, intent_projection: IntentProjection | None = None,
) -> tuple[list[str], dict[str, object]]:
    """Compile rules, subscription diagnostics and blockers together."""
    compiled_entries, diagnostics = intent_projection.compiled_rules() if intent_projection is not None else _compiled_policy_rule_entries(policy_ir)
    if intent_projection is not None:
        compiled_entries = intent_projection.project_rules(compiled_entries)
    compiled_entries, dialect_warnings = _lower_policy_entries_for_client(compiled_entries, client="shadowrocket")
    diagnostics.extend(dialect_warnings)
    final_rules, subscription_warnings = _shadowrocket_rules_with_subscription_fallback(
        policy_ir, compiled_entries, managed_subscription_url,
    )
    diagnostics.extend(subscription_warnings)
    referenced_contracts = _surge_referenced_contracts(policy_ir, compiled_entries, client="shadowrocket")
    blockers, referenced_summaries = _surge_build_blockers(
        policy_ir,
        available_contracts=_shadowrocket_available_contracts(policy_ir),
        referenced_contracts=referenced_contracts,
    )
    shadowrocket_blockers = [
        RenderWarning(
            code=item.code.replace("surge-", "shadowrocket-", 1)
            if item.code.startswith("surge-")
            else item.code,
            message=item.message,
            target=item.target,
            severity=item.severity,
            bucket=item.bucket,
        )
        for item in blockers
    ]
    return final_rules, {
        "code": "shadowrocket-build-blocked",
        "blockers": [item.to_dict() for item in shadowrocket_blockers],
        "warnings": [item.to_dict() for item in diagnostics],
        "referenced_contracts": [dict(item) for item in referenced_summaries],
    }


def shadowrocket_blocked_detail(
    policy_ir: PolicyIR, managed_subscription_url: str = "",
) -> dict[str, object]:
    """Return actionable blockers and warnings, including the managed host."""
    return _shadowrocket_rule_artifacts(policy_ir, managed_subscription_url)[1]


def _shadowrocket_subscription_rule(managed_url: str) -> str:
    """Build a host-wide fallback, never an override of existing user rules."""
    hostname = urlparse(managed_url).hostname
    if not hostname:
        return ""
    hostname = hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return f"DOMAIN,{hostname},DIRECT"
    kind = "IP-CIDR6" if address.version == 6 else "IP-CIDR"
    return f"{kind},{address.compressed}/{address.max_prefixlen},DIRECT,no-resolve"


def _shadowrocket_rules_with_subscription_fallback(
    policy_ir: PolicyIR, entries: list[PolicyRuleEntry], managed_url: str,
) -> tuple[list[str], list[RenderWarning]]:
    def rejects(target_id: str) -> bool:
        if _is_native_rule_target(target_id, client="shadowrocket"):
            return target_id.strip() != "DIRECT"
        # ROUTE_REJECT_ACTION is the parser's canonical native REJECT action.
        # Other IDs require an actual contract with an explicit reject action.
        return target_id == ROUTE_REJECT_ACTION or _route_action(
            _contract_by_id(policy_ir, target_id)
        ) == ROUTE_ACTION_REJECT

    # Keep target identity beside the rendered line. Display names are never
    # interpreted as actions, even when they begin with REJECT-.
    rule_lines = [entry.to_line(target_name=_lower_rule_target_for_client(
        _contract_target_name(policy_ir, entry.target_contract_id, client="shadowrocket"),
        policy_ir=policy_ir, client="shadowrocket", contract_id=entry.target_contract_id,
    )) for entry in entries]
    rule_lines.append(f"FINAL,{policy_ir.default_group_name}")
    subscription_rule = _shadowrocket_subscription_rule(managed_url)
    if not subscription_rule:
        return rule_lines, []
    subscription_parts = _split_rule_parts(subscription_rule)
    hostname = subscription_parts[1]
    address = None
    if subscription_parts[0] in {"IP-CIDR", "IP-CIDR6"}:
        address = ipaddress.ip_network(hostname).network_address
        hostname = str(address)
    for entry, line in zip(entries, rule_lines[:-1]):
        kind, value = entry.rule_type, entry.value.lower().rstrip(".")
        matches = False
        if address is None:
            if kind == "DOMAIN":
                matches = hostname == value
            elif kind == "DOMAIN-SUFFIX":
                matches = hostname == value or hostname.endswith("." + value)
        elif kind in {"IP-CIDR", "IP-CIDR6"} and "src" not in {part.lower() for part in entry.extras}:
            try:
                matches = address in ipaddress.ip_network(value, strict=False)
            except ValueError:
                pass
        # Keywords, GEOIP, remote sets, logical/port rules and DNS results are
        # deliberately not evaluated. They retain their earlier precedence.
        if not matches:
            continue
        if rejects(entry.target_contract_id):
            return rule_lines, [RenderWarning(
                code="shadowrocket-subscription-host-rejected",
                message=(f"规则 {line} 显式拒绝订阅主机 {hostname}；命中该规则时，"
                         "Shadowrocket 连接时无法更新这份配置。请将该主机的规则改为可用代理或 DIRECT，"
                         "或断开 VPN 后更新；服务端保留原规则。"),
                target=hostname, severity="warning", bucket="downgraded",
            )]
        return rule_lines, []
    # Explicit default contracts carry their action in IR. Legacy callers may
    # supply a native FINAL token; classify only exact platform-native targets.
    default_contract = _default_contract(policy_ir)
    if default_contract is not None:
        final_rejects = _route_action(default_contract) == ROUTE_ACTION_REJECT
    elif policy_ir.default_contract_id in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}:
        final_rejects = rejects(policy_ir.default_contract_id)
    else:
        final_rejects = (
            _is_native_rule_target(policy_ir.default_group_name, client="shadowrocket")
            and policy_ir.default_group_name.strip() != "DIRECT"
        )
    if final_rejects:
        return [*rule_lines[:-1], subscription_rule, rule_lines[-1]], []
    return rule_lines, []


@dataclass
class ShadowrocketProfileArtifacts:
    content: str
    skipped: list[str]
    diagnostics: list[RenderWarning]
    blocked_detail: dict[str, object]


def build_shadowrocket_profile_artifacts(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    managed_subscription_url: str,
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    *,
    policy_ir: PolicyIR | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
    intent: ConfigurationIntent | None = None,
) -> ShadowrocketProfileArtifacts:
    profile = intent.profile if intent is not None else profile
    base_ir = policy_ir or build_policy_ir(nodes, rule_lines)
    desired = intent or derive_configuration_intent(
        base_ir, profile_settings, profile=profile,
    )
    projection = project_configuration_intent(desired, "shadowrocket")
    ir = projection.policy
    final_rules, blocked_detail = _shadowrocket_rule_artifacts(ir, managed_subscription_url, intent_projection=projection)
    blockers = list(blocked_detail.get("blockers") or [])
    grouped_nodes = _group_nodes(ir.nodes)
    front_name_by_key = _inline_front_name_map(grouped_nodes, client="shadowrocket")
    sr_normalized = projection.settings
    sr_ipv6 = sr_normalized.get(LAZYCAT_PROFILE_SHADOWROCKET_IPV6_KEY, True)
    lines = [
        f"#!MANAGED-CONFIG {managed_subscription_url} interval=1800 strict=false",
        "# canonical inline proxy contract",
        "[General]",
        f"ipv6 = {'true' if sr_ipv6 else 'false'}",
    ]
    if blockers:
        lines.extend(
            [
                "# SubHub build blocked: shadowrocket-build-blocked",
                *[f"# SubHub blocker: {item.get('code', 'unknown')}" for item in blockers],
            ]
        )
    if profile == "lazycat":
        lazycat_settings = sr_normalized
        lines.append(
            "# lazycat profile: best-effort; set TUN bypass manually if client ignores these fields"
        )
        if lazycat_settings[LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY]:
            lines.append(
                f"always-real-ip = {','.join(lazycat_settings[LAZYCAT_PROFILE_SHADOWROCKET_ALWAYS_REAL_IP_KEY])}"
            )
        if lazycat_settings[LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY]:
            lines.append(
                f"tun-excluded-routes = {','.join(lazycat_settings[LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY])}"
            )
        skip_proxy = _sanitize_skip_proxy_entries(
            lazycat_settings.get(LAZYCAT_PROFILE_SHADOWROCKET_SKIP_PROXY_KEY, []),
            excluded_routes=lazycat_settings.get(LAZYCAT_PROFILE_SHADOWROCKET_TUN_EXCLUDED_ROUTES_KEY, []),
        )
        if skip_proxy:
            lines.append(f"skip-proxy = {', '.join(skip_proxy)}")
        lines.extend(_shadowrocket_http_pipeline_note_lines(lazycat_settings))
        host_records = {
            str(host).strip(): str(target).strip()
            for host, target in dict(
                lazycat_settings.get(LAZYCAT_PROFILE_SHADOWROCKET_HOST_RECORDS_KEY, {}) or {}
            ).items()
            if str(host).strip() and str(target).strip()
        }
        if host_records:
            lines.extend(["", "[Host]"])
            for host, target in host_records.items():
                lines.append(f"{host} = {target}")
    warning_index = len(lines)
    lines.extend(["", "[Proxy]"])

    skipped: list[str] = []
    group_names: dict[str, list[str]] = {group: [] for group in QUALITY_GROUPS}
    country_group_names: dict[str, dict[str, list[str]]] = {group: {} for group in QUALITY_GROUPS}
    used_names = {name.casefold() for name in _RESERVED_PROXY_NAMES}
    used_names.update(_business_group_display_name(g.name).casefold() for g in _ordered_business_groups(ir))
    used_names.update(_pool_mode_names(pool)["auto"].casefold() for pool in QUALITY_GROUPS)
    used_names.add(_CHAIN_INGRESS_GROUP_NAME.casefold())
    for pool in _COUNTRY_ROUTED_QUALITY_GROUPS:
        plan = _country_routing_plan(pool, _country_buckets(grouped_nodes[pool]))
        used_names.update(name.casefold() for name in plan["country_groups"])
        if plan["international_group"]:
            used_names.add(str(plan["international_group"]).casefold())

    for group in QUALITY_GROUPS:
        payloads: list[dict[str, Any]] = []
        names: list[str] = []
        renderable_nodes: list[NodeRecord] = []
        for node in grouped_nodes[group]:
            inline_reason = _shadowrocket_inline_unsupported_reason(node)
            if inline_reason:
                skipped.append(node.name)
                lines.append(f"# SubHub warning [shadowrocket-inline-unsupported]: {_safe_name(node.name)}: {inline_reason}")
                continue
            payload = _shadowrocket_proxy_payload(node, front_name_by_key=front_name_by_key)
            if not payload:
                skipped.append(node.name)
                lines.append(f"# SubHub warning [shadowrocket-node-refused]: {_safe_name(node.name)}: missing required or unsupported protocol fields")
                continue
            udp = _clash_udp_value(node.raw or {}, node.protocol.lower(), udp_default_enabled=bool(
                sr_normalized.get(LAZYCAT_PROFILE_CLASH_UDP_DEFAULT_ENABLED_KEY, True)))
            if udp is not None:
                payload["udp"] = udp
            payloads.append(payload)
            names.append(_safe_name(node.name))
            renderable_nodes.append(node)

        unique_names: list[str] = []
        for base in names:
            candidate = base
            n = 2
            while candidate.casefold() in used_names:
                candidate = f"{base} ({n})"
                n += 1
            used_names.add(candidate.casefold())
            unique_names.append(candidate)

        for idx, payload in enumerate(payloads):
            node_name = unique_names[idx]
            lines.append(_shadowrocket_proxy_line(node_name, payload))
            group_names[group].append(node_name)
            if group in _COUNTRY_ROUTED_QUALITY_GROUPS:
                country = _detect_node_country(renderable_nodes[idx].name)
                country_group_names[group].setdefault(country, []).append(node_name)

    referenced_helper_names = _referenced_helper_group_names(
        ir,
        client="shadowrocket",
        available_pools={group for group in QUALITY_GROUPS if group_names.get(group)},
        has_chain_nodes=bool(group_names.get(QUALITY_CHAIN_HOME)),
    )
    lines.extend(["", "[Proxy Group]"])
    lines.extend(
        _shadowrocket_proxy_group_lines(
            ir,
            group_names,
            country_group_names,
            referenced_helper_names,
        )
    )
    lines.extend(["", "[Rule]"])
    lines.extend(final_rules)
    lines.append("")

    if profile == "lazycat":
        lines.extend(_shadowrocket_http_pipeline_section_lines(sr_normalized))

    rule_warnings = [RenderWarning(**item) for item in blocked_detail["warnings"]]
    rendering_warnings = [
        *derive_protocol_diagnostics(ir.nodes, skipped, target="shadowrocket"),
        *derive_shadowrocket_profile_diagnostics(projection.requested_settings if profile == "lazycat" else None, local_host_aliases=local_host_aliases),
    ]
    diagnostics = [*ir.warnings, *rule_warnings, *rendering_warnings]
    # Preserve existing Shadowrocket warning comments and expose the same
    # warning objects to management previews and blocked responses.
    comment_warnings = [
        item for item in rule_warnings
        if item.bucket == "refused" or item.code == "shadowrocket-subscription-host-rejected"
    ]
    lines[warning_index:warning_index] = [
        f"# SubHub warning [{warning.code}]: {warning.message}"
        for warning in [*comment_warnings, *rendering_warnings]
    ]
    entries, _ = projection.compiled_rules()
    diagnostics.extend(projection.diagnostics)
    diagnostics.extend(routing_intent_diagnostics(
        entries, target="shadowrocket", default_action=_route_action_for_target(ir, ir.default_contract_id),
        ip_resolution=projection.ip_resolution, projection=projection,
    ))
    blocked_detail["warnings"] = [item.to_dict() for item in diagnostics]
    return ShadowrocketProfileArtifacts("\n".join(lines), skipped, diagnostics, blocked_detail)


def build_shadowrocket_config(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    managed_subscription_url: str,
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    *,
    policy_ir: PolicyIR | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
) -> tuple[str, list[str]]:
    artifacts = build_shadowrocket_profile_artifacts(
        nodes, rule_lines, managed_subscription_url,
        profile=profile, profile_settings=profile_settings, policy_ir=policy_ir,
        local_host_aliases=local_host_aliases,
    )
    return artifacts.content, artifacts.skipped


def build_surge_config(
    nodes: list[NodeRecord],
    rule_lines: list[str],
    managed_subscription_url: str,
    profile: str = "",
    profile_settings: dict[str, object] | None = None,
    *,
    policy_ir: PolicyIR | None = None,
    local_host_aliases: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"}),
) -> tuple[str, list[str]]:
    artifacts = build_surge_profile_artifacts(
        nodes,
        rule_lines,
        managed_subscription_url,
        profile=profile,
        profile_settings=profile_settings,
        policy_ir=policy_ir,
        local_host_aliases=local_host_aliases,
    )
    return artifacts.main_conf, artifacts.skipped


def build_surge_mac_overlay(
    overlay: MacOverlayTemplate,
    *,
    profile_name: str = "SubHub Mac Overlay",
) -> str:
    projection = project_configuration_intent(derive_configuration_intent(
        build_policy_ir([], [], process_rules=overlay.process_rules,
                        external_proxy_programs=overlay.external_proxy_programs),
        None, profile="",
    ), "surge")
    renderable_external_proxy_programs = [
        item
        for item in sorted(projection.policy.external_proxy_programs, key=lambda entry: (entry.sort_order, entry.name, entry.id))
        if item.enabled and item.contract_id and item.program_path and int(item.local_port or 0) > 0
    ]
    renderable_process_rules = [
        item
        for item in sorted(projection.policy.process_rules, key=lambda entry: (entry.sort_order, entry.value, entry.id))
        if item.enabled and item.contract_id and item.value
    ]
    lines = [
        f"#!MANAGED-CONFIG {overlay.managed_url} interval=1800 strict=false",
        f"#!include {overlay.include_url}",
        "#!MACOS-ONLY",
        "",
    ]
    if renderable_external_proxy_programs:
        lines.extend(["[Proxy]"])
        for item in renderable_external_proxy_programs:
            display_name = item.name or f"{item.contract_display_name} External"
            args = ", ".join(item.args)
            lines.append(
                f"{display_name} = external, exec={item.program_path}, args={args}, local-port={item.local_port}"
            )
        lines.append("")
    if renderable_process_rules:
        lines.extend(["[Rule]"])
        for item in renderable_process_rules:
            rule_type = item.match_type if item.match_type in SURGE_PROCESS_RULE_TYPES else "PROCESS-NAME"
            lines.append(f"{rule_type},{item.value},{item.contract_display_name}")
        lines.append("")
    lines.append(f"# {profile_name}")
    lines.append("")
    return "\n".join(lines)


def shadowrocket_config_filename(subscription_id: str, scenario_slug: str = "") -> str:
    identity = json.dumps([subscription_id, scenario_slug], ensure_ascii=True, separators=(",", ":"))
    return f"shadowrocket-{hashlib.sha256(identity.encode()).hexdigest()[:16]}.conf"


def build_device_import_links(
    app_base_url: str,
    device_name: str,
    subscription_id: str,
    *,
    scenario_slug: str | None = None,
    surge_base_url: str | None = None,
) -> dict[str, str]:
    base = app_base_url.rstrip("/")
    surge_base = str(surge_base_url or base).rstrip("/")
    safe_scenario_slug = str(scenario_slug or "").strip()
    quoted_slug = quote(safe_scenario_slug, safe="")
    scenario_path = f"/{quoted_slug}" if quoted_slug else ""
    clash_url = f"{base}/sub/device/{subscription_id}{scenario_path}/clash.yaml"
    sr_url = f"{base}/sub/device/{subscription_id}{scenario_path}/{shadowrocket_config_filename(subscription_id, safe_scenario_slug)}"
    sr_nodes_url = f"{base}/sub/device/{subscription_id}{scenario_path}/shadowrocket-nodes.txt"
    surge_url = f"{surge_base}/sub/device/{subscription_id}{scenario_path}/surge.conf"
    surge_mac_overlay_url = f"{surge_base}/sub/device/{subscription_id}{scenario_path}/surge-mac-overlay.conf"
    encoded_clash = quote(clash_url, safe="")
    encoded_surge = quote(surge_url, safe="")
    encoded_surge_overlay = quote(surge_mac_overlay_url, safe="")
    display_name = f"{device_name}-{safe_scenario_slug}" if safe_scenario_slug else device_name
    safe_name = quote(build_subscription_display_name(display_name), safe="")
    return {
        "clash_url": clash_url,
        "shadowrocket_url": sr_url,
        "shadowrocket_nodes_url": sr_nodes_url,
        "surge_url": surge_url,
        "surge_mac_overlay_url": surge_mac_overlay_url,
        "clash_scheme": f"clash://install-config?url={encoded_clash}&name={safe_name}",
        "shadowrocket_scheme": f"shadowrocket://config/add/{sr_url}",
        "surge_scheme": f"surge:///install-config?url={encoded_surge}&name={safe_name}",
        "surge_mac_overlay_scheme": f"surge:///install-config?url={encoded_surge_overlay}&name={safe_name}%20Mac%20Overlay",
    }


def build_device_import_links_for_scenario(
    app_base_url: str,
    device_name: str,
    subscription_id: str,
    scenario_slug: str,
    *,
    surge_base_url: str | None = None,
) -> dict[str, str]:
    return build_device_import_links(
        app_base_url,
        device_name,
        subscription_id,
        scenario_slug=scenario_slug,
        surge_base_url=surge_base_url,
    )
