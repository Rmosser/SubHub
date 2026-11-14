from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


QUALITY_HIGH_PREMIUM = "高质量-高倍率"
QUALITY_HIGH_STANDARD = "高质量-低倍率"
QUALITY_MEDIUM = "中等质量"
QUALITY_BULK = "低质量大流量"
QUALITY_CHAIN_HOME = "链式家宽"
QUALITY_HIGH_AIRPORT = "高质量机场"
QUALITY_REJECT = "REJECT"
QUALITY_GROUPS = (
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
    QUALITY_BULK,
    QUALITY_CHAIN_HOME,
)
POOL_DIRECT = "direct"
POOL_HQ_PREMIUM = "hq_premium"
POOL_HQ_STANDARD = "hq_standard"
POOL_MEDIUM = "medium"
POOL_BULK = "bulk"
POOL_CHAIN_HOME = "chain_home"
POOL_IDS = (
    POOL_DIRECT,
    POOL_HQ_PREMIUM,
    POOL_HQ_STANDARD,
    POOL_MEDIUM,
    POOL_BULK,
    POOL_CHAIN_HOME,
)
POOL_DISPLAY_NAMES = {
    POOL_DIRECT: "直连",
    POOL_HQ_PREMIUM: QUALITY_HIGH_PREMIUM,
    POOL_HQ_STANDARD: QUALITY_HIGH_STANDARD,
    POOL_MEDIUM: QUALITY_MEDIUM,
    POOL_BULK: QUALITY_BULK,
    POOL_CHAIN_HOME: QUALITY_CHAIN_HOME,
}
LEGACY_QUALITY_TO_POOL_ID = {
    QUALITY_HIGH_PREMIUM: POOL_HQ_PREMIUM,
    QUALITY_HIGH_STANDARD: POOL_HQ_STANDARD,
    QUALITY_MEDIUM: POOL_MEDIUM,
    QUALITY_BULK: POOL_BULK,
    QUALITY_CHAIN_HOME: POOL_CHAIN_HOME,
}
POOL_ID_TO_LEGACY_QUALITY = {value: key for key, value in LEGACY_QUALITY_TO_POOL_ID.items()}
CONTRACT_DIRECT = "direct"
CONTRACT_HQ_PREMIUM = "hq_premium"
CONTRACT_HQ_STANDARD = "hq_standard"
CONTRACT_MEDIUM = "medium"
CONTRACT_BULK = "bulk"
CONTRACT_CHAIN_HOME = "chain_home"
CONTRACT_AD_BLOCK = "ad_block"

# These are protocol-level targets, not persisted route-contract identities.
# A user may delete or repurpose the legacy ``direct``/``ad_block`` records;
# explicit directness and blocking still need stable targets in derived policy.
ROUTE_DIRECT_ACTION = "action-direct"
ROUTE_REJECT_ACTION = "action-reject"
ROUTE_ACTION_PROXY = "proxy"
ROUTE_ACTION_DIRECT = "direct"
ROUTE_ACTION_REJECT = "reject"
ROUTE_ACTIONS = (
    ROUTE_ACTION_PROXY,
    ROUTE_ACTION_DIRECT,
    ROUTE_ACTION_REJECT,
)
# These are protocol targets emitted by subscription renderers.  They are
# deliberately separate from persisted route-contract IDs.
ROUTE_NATIVE_DIRECT_TARGET = "DIRECT"
ROUTE_NATIVE_REJECT_TARGET = "REJECT"
ROUTE_ACTION_DISPLAY_NAMES = {
    ROUTE_DIRECT_ACTION: "直连",
    ROUTE_REJECT_ACTION: "广告拦截",
}
RESERVED_ROUTE_ACTION_IDS = (ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION)
# A proxy contract must not claim one of the renderer's native group names.
# Quality pool labels themselves are intentionally absent: they are ordinary
# editable display names, while the renderer's generated helper groups carry
# the ``·自动`` suffix.
ROUTE_RENDERER_RESERVED_GROUP_NAMES = frozenset(
    {
        ROUTE_NATIVE_DIRECT_TARGET,
        ROUTE_NATIVE_REJECT_TARGET,
        "REJECT-DROP",
        "兜底代理",
        "链式入口·自动",
        *(f"{item}·自动" for item in QUALITY_GROUPS),
    }
)
SYSTEM_CONTRACT_IDS = (
    CONTRACT_DIRECT,
    CONTRACT_HQ_PREMIUM,
    CONTRACT_HQ_STANDARD,
    CONTRACT_MEDIUM,
    CONTRACT_BULK,
    CONTRACT_CHAIN_HOME,
    CONTRACT_AD_BLOCK,
)
CONTRACT_DISPLAY_NAMES = {
    CONTRACT_DIRECT: "直连",
    CONTRACT_HQ_PREMIUM: QUALITY_HIGH_PREMIUM,
    CONTRACT_HQ_STANDARD: QUALITY_HIGH_STANDARD,
    CONTRACT_MEDIUM: QUALITY_MEDIUM,
    CONTRACT_BULK: QUALITY_BULK,
    CONTRACT_CHAIN_HOME: QUALITY_CHAIN_HOME,
    CONTRACT_AD_BLOCK: "广告拦截",
}
SYSTEM_CONTRACT_DESCRIPTIONS = {
    CONTRACT_HQ_PREMIUM: (
        "纯净住宅IP + 极低延迟的 IPLC 专线。"
        "适合：AI 编程助手、实时对话 API、"
        "以及对 IP 信誉和延迟都极度敏感的服务。"
    ),
    CONTRACT_HQ_STANDARD: (
        "纯净 IP 优先，延迟要求适中。"
        "适合：Google、社交媒体、主流流媒体、金融支付、Apple/iCloud 等"
        "对 IP 信誉敏感但不需极致低延迟的业务。"
    ),
    CONTRACT_MEDIUM: (
        "通用海外访问，兼顾稳定性和成本。"
        "适合：日常海外网站、开发工具、游戏平台、通信工具等常规场景。"
    ),
    CONTRACT_BULK: (
        "带宽优先，不要求 IP 质量或低延迟。"
        "适合：下载、镜像、系统更新、P2P、模型拉取等大流量业务。"
    ),
    CONTRACT_CHAIN_HOME: (
        "链式家宽出口。"
        "适合需要住宅出口但允许更高复杂度和成本的场景。"
    ),
}
LEGACY_GROUP_TO_CONTRACT_ID = {
    "DIRECT": CONTRACT_DIRECT,
    QUALITY_REJECT: CONTRACT_AD_BLOCK,
    QUALITY_HIGH_PREMIUM: CONTRACT_HQ_PREMIUM,
    QUALITY_HIGH_STANDARD: CONTRACT_HQ_STANDARD,
    QUALITY_MEDIUM: CONTRACT_MEDIUM,
    QUALITY_BULK: CONTRACT_BULK,
    QUALITY_CHAIN_HOME: CONTRACT_CHAIN_HOME,
    CONTRACT_AD_BLOCK: CONTRACT_AD_BLOCK,
    CONTRACT_DISPLAY_NAMES[CONTRACT_AD_BLOCK]: CONTRACT_AD_BLOCK,
}
CONTRACT_ID_TO_LEGACY_GROUP = {
    CONTRACT_DIRECT: "DIRECT",
    CONTRACT_HQ_PREMIUM: QUALITY_HIGH_PREMIUM,
    CONTRACT_HQ_STANDARD: QUALITY_HIGH_STANDARD,
    CONTRACT_MEDIUM: QUALITY_MEDIUM,
    CONTRACT_BULK: QUALITY_BULK,
    CONTRACT_CHAIN_HOME: QUALITY_CHAIN_HOME,
}
CONTRACT_STRATEGY_STRICT = "strict"
CONTRACT_STRATEGY_FAILOVER = "failover"
CONTRACT_STRATEGY_LOAD_BALANCE = "load-balance"
CONTRACT_STRATEGIES = (
    CONTRACT_STRATEGY_STRICT,
    CONTRACT_STRATEGY_FAILOVER,
    CONTRACT_STRATEGY_LOAD_BALANCE,
)
CONTRACT_FAILURE_DEGRADE = "degrade"
CONTRACT_FAILURE_DIRECT = "direct"
CONTRACT_FAILURE_INTERRUPT = "interrupt"
CONTRACT_FAILURE_ACTIONS = (
    CONTRACT_FAILURE_DEGRADE,
    CONTRACT_FAILURE_DIRECT,
    CONTRACT_FAILURE_INTERRUPT,
)
DEVICE_STRATEGY_PRESET_BALANCED = "balanced"
DEVICE_STRATEGY_PRESET_CHEAP = "cheap"
DEVICE_STRATEGY_PRESET_REALTIME = "realtime"
DEVICE_STRATEGY_PRESET_STREAMING = "streaming"
DEVICE_STRATEGY_PRESET_MOBILE = "mobile"
DEVICE_STRATEGY_PRESETS = (
    DEVICE_STRATEGY_PRESET_BALANCED,
    DEVICE_STRATEGY_PRESET_CHEAP,
    DEVICE_STRATEGY_PRESET_REALTIME,
    DEVICE_STRATEGY_PRESET_STREAMING,
    DEVICE_STRATEGY_PRESET_MOBILE,
)
SURGE_PROCESS_RULE_TYPES = (
    "PROCESS-NAME",
    "PROCESS-NAME-REGEX",
    "PROCESS-PATH",
    "PROCESS-PATH-REGEX",
)
STANDARD_SOURCE_ALLOWED_GROUPS = {
    QUALITY_MEDIUM,
    QUALITY_BULK,
    QUALITY_HIGH_AIRPORT,
}
STANDARD_SOURCE_MODE_ROUTE_CONTRACT = "route_contract"
STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT = "high_quality_airport"
STANDARD_SOURCE_MODES = (
    STANDARD_SOURCE_MODE_ROUTE_CONTRACT,
    STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT,
)
STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION = "remote_subscription"
STANDARD_SOURCE_INGEST_MANUAL_NODES = "manual_nodes"
STANDARD_SOURCE_INGEST_KINDS = (
    STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION,
    STANDARD_SOURCE_INGEST_MANUAL_NODES,
)
STANDARD_SOURCE_QR_FIELDS = ("clash", "shadowrocket", "surge")
STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY = "direct_then_proxy"
STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY = "direct_only"
STANDARD_SOURCE_PULL_NETWORK_PROXY_THEN_DIRECT = "proxy_then_direct"
STANDARD_SOURCE_PULL_NETWORK_MODES = (
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    STANDARD_SOURCE_PULL_NETWORK_PROXY_THEN_DIRECT,
)
DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE = STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY
STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD = 10
VALID_TARGETS = set(QUALITY_GROUPS) | set(CONTRACT_DISPLAY_NAMES.values()) | {"REJECT", "DIRECT"}
MULTIPLIER_THRESHOLD = 3.0
HIGH_QUALITY_AIRPORT_THRESHOLD = 5.0
RULE_DIRECTNESS_DIRECT = "DIRECT"
RULE_DIRECTNESS_PROXY = "PROXY"
RULE_DIRECTNESS_CHOICES = (
    RULE_DIRECTNESS_DIRECT,
    RULE_DIRECTNESS_PROXY,
)
RULE_LOCK_SOURCE_SYSTEM = "system"
RULE_LOCK_SOURCE_MANUAL = "manual"
RULE_LOCK_SOURCES = (
    RULE_LOCK_SOURCE_SYSTEM,
    RULE_LOCK_SOURCE_MANUAL,
)
RULE_CATEGORY_TYPE_AUTO = "auto"
RULE_CATEGORY_TYPE_MANUAL = "manual"
RULE_CATEGORY_TYPES = (
    RULE_CATEGORY_TYPE_AUTO,
    RULE_CATEGORY_TYPE_MANUAL,
)
RULE_DIRECTNESS_REVIEW_STATUS_PENDING = "pending"
RULE_DIRECTNESS_REVIEW_STATUS_APPLIED = "applied"
RULE_DIRECTNESS_REVIEW_STATUS_DISMISSED = "dismissed"
RULE_DIRECTNESS_REVIEW_STATUSES = (
    RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
    RULE_DIRECTNESS_REVIEW_STATUS_APPLIED,
    RULE_DIRECTNESS_REVIEW_STATUS_DISMISSED,
)
BUSINESS_GROUP_MODE_STANDARD = "standard"
BUSINESS_GROUP_MODE_AD_BLOCK = "ad_block"
BUSINESS_GROUP_MODES = (
    BUSINESS_GROUP_MODE_STANDARD,
    BUSINESS_GROUP_MODE_AD_BLOCK,
)
CONTRACT_SCOPE_SYSTEM = "system"
CONTRACT_SCOPE_GLOBAL = "global"
CONTRACT_SCOPE_SCENARIO = "scenario"
CONTRACT_SCOPES = (
    CONTRACT_SCOPE_SYSTEM,
    CONTRACT_SCOPE_GLOBAL,
    CONTRACT_SCOPE_SCENARIO,
)
_CONTRACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def contract_display_name(contract_id: str) -> str:
    normalized = str(contract_id or "").strip()
    if normalized in ROUTE_ACTION_DISPLAY_NAMES:
        return ROUTE_ACTION_DISPLAY_NAMES[normalized]
    return CONTRACT_DISPLAY_NAMES.get(normalized, normalized)


def normalize_contract_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in SYSTEM_CONTRACT_IDS:
        return text
    for contract_id, display_name in CONTRACT_DISPLAY_NAMES.items():
        if text == display_name:
            return contract_id
    legacy = LEGACY_GROUP_TO_CONTRACT_ID.get(text, "")
    if legacy:
        return legacy
    if _CONTRACT_ID_PATTERN.fullmatch(text):
        return text.lower()
    return ""


def normalize_route_action(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in ROUTE_ACTIONS else ROUTE_ACTION_PROXY


def resolve_legacy_route_target(value: object) -> str:
    """Resolve a legacy rule target without treating record IDs as actions.

    Old rule rows only had a display target.  Their protocol-level native
    targets must survive deletion or repurposing of the historical ``direct``
    and ``ad_block`` records.  An explicit lower-case record ID remains a
    record reference.
    """
    text = str(value or "").strip()
    if text == ROUTE_NATIVE_DIRECT_TARGET:
        return ROUTE_DIRECT_ACTION
    if text in {ROUTE_NATIVE_REJECT_TARGET, QUALITY_REJECT}:
        return ROUTE_REJECT_ACTION
    if text in RESERVED_ROUTE_ACTION_IDS:
        return text
    return normalize_contract_id(text)


def contract_legacy_group(contract_id: str) -> str:
    normalized = str(contract_id or "").strip()
    if normalized == ROUTE_DIRECT_ACTION:
        return RULE_DIRECTNESS_DIRECT
    if normalized == ROUTE_REJECT_ACTION:
        return QUALITY_REJECT
    return CONTRACT_ID_TO_LEGACY_GROUP.get(normalized, "")


def contract_description(contract_id: str) -> str:
    normalized = str(contract_id or "").strip()
    return SYSTEM_CONTRACT_DESCRIPTIONS.get(normalized, "")


def resolve_contract_id(
    value: object,
    *,
    display_name_map: Mapping[str, str] | None = None,
) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Native protocol targets and primitive action IDs are never aliases for
    # a persisted record, even if a current record happens to use that label.
    if text == ROUTE_NATIVE_DIRECT_TARGET:
        return ROUTE_DIRECT_ACTION
    if text == ROUTE_NATIVE_REJECT_TARGET:
        return ROUTE_REJECT_ACTION
    if text in RESERVED_ROUTE_ACTION_IDS:
        return text
    if display_name_map is not None:
        # Persisted IDs are authoritative.  A custom label equal to another
        # record's ID must not reinterpret an existing stored reference.
        for contract_id in display_name_map:
            candidate = str(contract_id or "").strip()
            if text == candidate:
                return candidate
        for contract_id, display_name in display_name_map.items():
            if text == str(display_name or "").strip():
                return str(contract_id or "").strip()
        normalized = normalize_contract_id(text)
        return normalized if normalized in display_name_map else ""

    normalized = normalize_contract_id(text)
    if normalized:
        return normalized
    if not text:
        return ""
    return ""


def normalize_standard_source_mode(value: object) -> str:
    text = str(value or "").strip()
    return text if text in STANDARD_SOURCE_MODES else STANDARD_SOURCE_MODE_ROUTE_CONTRACT


def normalize_standard_source_ingest_kind(value: object) -> str:
    text = str(value or "").strip()
    return (
        text
        if text in STANDARD_SOURCE_INGEST_KINDS
        else STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION
    )


def pool_display_name(pool_id: str) -> str:
    normalized = str(pool_id or "").strip()
    return POOL_DISPLAY_NAMES.get(normalized, normalized)


def effective_contract_id(
    *,
    stored_contract_id: object = "",
    catalog_group_mode: object = "",
    current_directness: object = RULE_DIRECTNESS_PROXY,
) -> str:
    normalized_mode = str(catalog_group_mode or "").strip()
    if normalized_mode == BUSINESS_GROUP_MODE_AD_BLOCK:
        return ROUTE_REJECT_ACTION

    normalized_directness = str(current_directness or "").strip().upper()
    if normalized_directness == RULE_DIRECTNESS_DIRECT:
        return ROUTE_DIRECT_ACTION

    normalized_stored = normalize_contract_id(stored_contract_id)
    if normalized_stored:
        return normalized_stored

    return ""


def effective_contract_source(
    *,
    stored_contract_id: object = "",
    catalog_group_mode: object = "",
    current_directness: object = RULE_DIRECTNESS_PROXY,
) -> str:
    normalized_mode = str(catalog_group_mode or "").strip()
    if normalized_mode == BUSINESS_GROUP_MODE_AD_BLOCK:
        return "ad_block_group"

    normalized_directness = str(current_directness or "").strip().upper()
    if normalized_directness == RULE_DIRECTNESS_DIRECT:
        return "directness"

    normalized_stored = normalize_contract_id(stored_contract_id)
    if normalized_stored:
        return "stored_contract"

    return "none"


@dataclass
class GoRelaySource:
    id: str
    name: str
    login_url: str
    gorelay_username: str
    gorelay_password: str
    proxy_username: str = ""
    proxy_password: str = ""
    selectors_json: str = "{}"
    enabled: bool = True
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["has_gorelay_password"] = bool(self.gorelay_password)
        payload["has_proxy_password"] = bool(self.proxy_password)
        payload.pop("gorelay_password", None)
        payload.pop("proxy_password", None)
        return payload


@dataclass
class GoRelayAccount:
    id: str
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
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["has_gorelay_password"] = bool(self.gorelay_password)
        payload["has_proxy_password_default"] = bool(self.proxy_password_default)
        payload["has_auth_header"] = bool(self.auth_header)
        payload.pop("gorelay_password", None)
        payload.pop("proxy_password_default", None)
        payload.pop("auth_header", None)
        return payload


@dataclass
class StandardSource:
    id: str
    name: str
    clash_url: str = ""
    shadowrocket_url: str = ""
    surge_url: str = ""
    login_url: str = ""
    # Route-contract sources must carry an explicit target.  Empty values are
    # retained for legacy/high-quality-airport records and are rejected by the
    # management/core resolver when a route contract is required.
    quality_group: str = ""
    target_contract_id: str = ""
    source_mode: str = STANDARD_SOURCE_MODE_ROUTE_CONTRACT
    ingest_kind: str = STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION
    manual_nodes_text: str = ""
    enabled: bool = True
    last_pull_attempt_at: str | None = None
    last_success_at: str | None = None
    last_pull_ok: bool | None = None
    last_pull_method: str = ""
    last_pull_node_count: int = 0
    last_pull_error: str = ""
    # Public reasons recorded with a failed pull: method, code, url, message.
    last_pull_reasons: list[dict[str, str]] = field(default_factory=list)
    pull_network_mode: str = DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE
    auto_pull_consecutive_failures: int = 0
    auto_pull_expired: bool = False
    auto_pull_expired_at: str | None = None
    last_success_config_fingerprint: str = ""
    updated_at: str = ""

    def resolved_source_mode(self) -> str:
        normalized = normalize_standard_source_mode(self.source_mode)
        if normalized == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
            return normalized
        if str(self.quality_group or "").strip() == QUALITY_HIGH_AIRPORT:
            return STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT
        return STANDARD_SOURCE_MODE_ROUTE_CONTRACT

    def resolved_ingest_kind(self) -> str:
        return normalize_standard_source_ingest_kind(self.ingest_kind)

    def resolved_target_contract_id(self) -> str:
        if self.resolved_source_mode() == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
            return ""
        normalized = normalize_contract_id(self.target_contract_id)
        if normalized:
            return normalized
        return normalize_contract_id(self.quality_group)

    def display_quality_group(self) -> str:
        if self.resolved_source_mode() == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
            return QUALITY_HIGH_AIRPORT
        return contract_display_name(self.resolved_target_contract_id())

    def export_config_dict(self) -> dict[str, Any]:
        return {
            "name": str(self.name or "").strip(),
            "clash_url": str(self.clash_url or "").strip(),
            "shadowrocket_url": str(self.shadowrocket_url or "").strip(),
            "surge_url": str(self.surge_url or "").strip(),
            "login_url": str(self.login_url or "").strip(),
            "quality_group": self.display_quality_group(),
            "target_contract_id": self.resolved_target_contract_id(),
            "source_mode": self.resolved_source_mode(),
            "ingest_kind": self.resolved_ingest_kind(),
            "manual_nodes_text": str(self.manual_nodes_text or "").strip(),
            "enabled": bool(self.enabled),
            "pull_network_mode": str(self.pull_network_mode or "").strip(),
        }

    def config_fingerprint(self) -> str:
        payload = json.dumps(
            self.export_config_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quality_group"] = self.display_quality_group()
        payload["target_contract_id"] = self.resolved_target_contract_id()
        payload["target_contract_display_name"] = contract_display_name(self.resolved_target_contract_id())
        payload["source_mode"] = self.resolved_source_mode()
        payload["ingest_kind"] = self.resolved_ingest_kind()
        payload["manual_nodes_text"] = str(self.manual_nodes_text or "").strip()
        payload["config_fingerprint"] = self.config_fingerprint()
        payload["export_config"] = self.export_config_dict()
        return payload


@dataclass
class StandardSourceWarning:
    code: str
    message: str
    field: str
    expected_method: str
    actual_variant: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StandardSourceQrAsset:
    source_id: str
    field: str
    file_relpath: str
    mime_type: str
    detected_url: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleCategory:
    name: str
    assigned_group: str = ""
    rule_count: int = 0
    rule_source: str = ""
    category_type: str = RULE_CATEGORY_TYPE_AUTO
    custom_rule_count: int = 0
    updated_at: str = ""
    locked: bool = False
    system_directness: str = RULE_DIRECTNESS_PROXY
    system_default_group: str = ""
    system_default_locked: bool = False
    override_group: str = ""
    override_active: bool = False
    directness_override: str = ""
    lock_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleCategoryDirectnessReview:
    id: str
    category_name: str
    proposed_decision: str
    confidence: str = ""
    reason: str = ""
    source: str = "llm-import"
    status: str = RULE_DIRECTNESS_REVIEW_STATUS_PENDING
    created_at: str = ""
    decided_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CustomRule:
    id: str
    rule_type: str
    value: str
    target_contract_id: str = ""
    target_group: str = ""
    category_name: str = ""
    created_at: str = ""

    def resolved_target_contract_id(self) -> str:
        normalized = resolve_legacy_route_target(self.target_contract_id)
        if normalized:
            return normalized
        return resolve_legacy_route_target(self.target_group)

    def display_target_group(self) -> str:
        normalized = self.resolved_target_contract_id()
        if normalized:
            if normalized == ROUTE_DIRECT_ACTION:
                return ROUTE_NATIVE_DIRECT_TARGET
            if normalized == ROUTE_REJECT_ACTION:
                return ROUTE_NATIVE_REJECT_TARGET
            return contract_display_name(normalized)
        return str(self.target_group or "").strip()

    def to_line(self, target_group: str | None = None) -> str:
        target = target_group if target_group is not None else self.display_target_group()
        return f"{self.rule_type},{self.value},{target}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_contract_id"] = self.resolved_target_contract_id()
        payload["target_group"] = self.display_target_group()
        payload["target_contract_display_name"] = self.display_target_group()
        return payload


@dataclass
class DeviceSubscription:
    id: str
    device_key: str
    device_name: str
    token: str
    public_id: str = ""
    enabled: bool = True
    last_seen_at: str | None = None
    last_seen_ip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NodeRecord:
    name: str
    host: str
    port: int
    protocol: str
    username: str = ""
    password: str = ""
    quality_group: str = ""
    source_id: str = ""
    source_type: str = ""  # gorelay | standard
    account_id: str = ""
    device_key: str = ""
    device_name: str = ""
    multiplier: str = ""
    source_rule_id: str = ""
    source_entry_name: str = ""
    source_entry_tag: str = ""
    source_isp: str = ""
    source_ip_version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dedupe_key(self) -> str:
        raw = self.raw or {}
        if raw.get("chain_home"):
            rear_target = str(raw.get("chain_rear_target", "") or "").strip().lower()
            if not rear_target:
                rear_target = f"{self.host}:{self.port}".lower()
            account_id = str(self.account_id or self.source_id or "").strip().lower()
            identity = {
                "protocol": self.protocol, "account_id": account_id,
                "rear_target": rear_target, "username": self.username, "password": self.password,
                "source_id": self.source_id, "source_type": self.source_type,
                "device_key": self.device_key, "quality_group": self.quality_group,
            }
            encoded = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            return "chain:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        # Display labels do not change a connection; credentials, transport,
        # and the owning source/device/quality pool do. Hash the identity so
        # credentials cannot leak through diagnostic dedupe keys.
        connection_raw = {
            key: value for key, value in raw.items()
            if key not in {"name", "server", "port", "source_uri", "original_query"}
        }
        identity = {
            "protocol": self.protocol.lower(), "host": self.host.lower(), "port": self.port,
            "username": self.username, "password": self.password, "raw": connection_raw,
            "source_id": self.source_id, "source_type": self.source_type,
            "account_id": self.account_id, "device_key": self.device_key,
            "quality_group": self.quality_group,
        }
        encoded = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        return "node:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class HubRuntime:
    last_refresh_at: str | None = None
    last_error: str | None = None
    source_status: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Compatibility adapter for existing GoRelayApiCollector.
@dataclass
class RelayAccount:
    id: str
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

    @classmethod
    def from_source(cls, source: GoRelaySource) -> RelayAccount:
        return cls(
            id=source.id,
            name=source.name,
            login_url=source.login_url,
            rules_url=source.login_url,
            gorelay_username=source.gorelay_username,
            gorelay_password=source.gorelay_password,
            proxy_username_default=source.proxy_username,
            proxy_password_default=source.proxy_password,
            selectors_json=source.selectors_json,
            enabled=source.enabled,
        )

    @classmethod
    def from_account(cls, account: GoRelayAccount) -> RelayAccount:
        return cls(
            id=account.id,
            name=account.name,
            login_url=account.login_url,
            rules_url=account.rules_url or account.login_url,
            gorelay_username=account.gorelay_username,
            gorelay_password=account.gorelay_password,
            proxy_username_default=account.proxy_username_default,
            proxy_password_default=account.proxy_password_default,
            selectors_json=account.selectors_json,
            mcp_url=account.mcp_url,
            auth_header=account.auth_header,
            login_tool=account.login_tool,
            nodes_tool=account.nodes_tool,
            login_args_json=account.login_args_json,
            nodes_args_json=account.nodes_args_json,
            enabled=account.enabled,
        )


# Compatibility model used by GoRelayApiCollector response.
@dataclass
class CollectedRule:
    account_id: str
    rule_id: str
    device_name: str
    line_name: str
    entry_name: str
    isp: str
    ip_version: str
    port: int
    host: str = ""
    status: str = "ready"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectedOutbound:
    account_id: str
    rule_id: str
    device_name: str
    line_name: str
    outbound_group_id: str
    outbound_group_name: str
    multiplier: str = ""
    targets: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoRelayDeviceProfile:
    account_id: str
    device_key: str
    device_name: str
    proxy_username_override: str = ""
    proxy_password_override: str = ""
    strategy_preset: str = DEVICE_STRATEGY_PRESET_BALANCED
    enabled: bool = True
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoRelayDeviceSubscription:
    id: str
    account_id: str
    device_key: str
    device_name: str
    token: str
    public_id: str = ""
    enabled: bool = True
    last_seen_at: str | None = None
    last_seen_ip: str | None = None
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoRelayDomainBinding:
    id: str
    account_id: str
    entry_name: str
    isp: str
    ip_version: str
    host_value: str
    source: str
    status: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoRelayDomainImportHistory:
    id: str
    account_id: str
    raw_text: str
    parsed_count: int
    changed_count: int
    multiplier_hint_count: int
    applied_bindings: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoRelayAccountSnapshot:
    account_id: str
    snapshot_id: str
    created_at: str
    node_count: int
    device_count: int
    status: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoRelayAccountSnapshotPayload:
    account: GoRelayAccountSnapshot
    collected_rules: list[CollectedRule]
    device_nodes: dict[str, list[NodeRecord]]
    device_names: dict[str, str]
    pending_bindings: list[dict[str, Any]]
    source_status: dict[str, Any]
    collected_outbounds: list[CollectedOutbound] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict(),
            "collected_rules": [item.__dict__ for item in self.collected_rules],
            "collected_outbounds": [item.__dict__ for item in self.collected_outbounds],
            "device_nodes": {
                key: [node.to_dict() for node in nodes]
                for key, nodes in self.device_nodes.items()
            },
            "device_names": self.device_names,
            "pending_bindings": self.pending_bindings,
            "source_status": self.source_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoRelayAccountSnapshotPayload":
        account_raw = dict(payload.get("account", {}))
        account = GoRelayAccountSnapshot(
            account_id=str(account_raw.get("account_id", "")),
            snapshot_id=str(account_raw.get("snapshot_id", "")),
            created_at=str(account_raw.get("created_at", "")),
            node_count=int(account_raw.get("node_count", 0)),
            device_count=int(account_raw.get("device_count", 0)),
            status=str(account_raw.get("status", "unknown")),
            error=(
                str(account_raw.get("error"))
                if account_raw.get("error") not in (None, "")
                else None
            ),
        )
        collected_rules = [
            CollectedRule(
                account_id=str(item.get("account_id", "")),
                rule_id=str(item.get("rule_id", "")),
                device_name=str(item.get("device_name", "")),
                line_name=str(item.get("line_name", "")),
                entry_name=str(item.get("entry_name", "")),
                isp=str(item.get("isp", "")),
                ip_version=str(item.get("ip_version", "")),
                port=int(item.get("port", 0)),
                host=str(item.get("host", "")),
                status=str(item.get("status", "ready")),
                raw=dict(item.get("raw", {})),
            )
            for item in payload.get("collected_rules", [])
            if isinstance(item, dict)
        ]
        collected_outbounds = [
            CollectedOutbound(
                account_id=str(item.get("account_id", "")),
                rule_id=str(item.get("rule_id", "")),
                device_name=str(item.get("device_name", "")),
                line_name=str(item.get("line_name", "")),
                outbound_group_id=str(item.get("outbound_group_id", "")),
                outbound_group_name=str(item.get("outbound_group_name", "")),
                multiplier=str(item.get("multiplier", "")),
                targets=[str(target) for target in list(item.get("targets") or []) if str(target).strip()],
                raw=dict(item.get("raw", {})),
            )
            for item in payload.get("collected_outbounds", [])
            if isinstance(item, dict)
        ]
        device_nodes: dict[str, list[NodeRecord]] = {}
        for key, nodes in dict(payload.get("device_nodes", {})).items():
            device_nodes[str(key)] = [
                NodeRecord(**dict(node))
                for node in list(nodes or [])
                if isinstance(node, dict)
            ]
        return cls(
            account=account,
            collected_rules=collected_rules,
            device_nodes=device_nodes,
            device_names={
                str(key): str(value)
                for key, value in dict(payload.get("device_names", {})).items()
            },
            pending_bindings=list(payload.get("pending_bindings", [])),
            source_status=dict(payload.get("source_status", {})),
            collected_outbounds=collected_outbounds,
        )


@dataclass
class GoRelayEntryMultiplierOverride:
    account_id: str
    entry_key: str
    multiplier: str
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BusinessGroup:
    name: str
    sort_order: int = 0
    category_names: list[str] = field(default_factory=list)
    pool_names: list[str] = field(default_factory=list)
    mode: str = BUSINESS_GROUP_MODE_STANDARD
    created_by_system: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PoolDefinition:
    id: str
    display_name: str
    sort_order: int = 0
    pseudo: bool = False
    editable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PoolStatus:
    id: str
    display_name: str
    node_count: int = 0
    renderable_node_count: int = 0
    last_refresh_at: str = ""
    sources: dict[str, int] = field(default_factory=dict)
    pseudo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RouteContract:
    id: str
    display_name: str
    description: str = ""
    strategy_type: str = CONTRACT_STRATEGY_STRICT
    primary_pools: list[str] = field(default_factory=list)
    fallback_pools: list[str] = field(default_factory=list)
    failure_action: str = CONTRACT_FAILURE_INTERRUPT
    routing_action: str = ROUTE_ACTION_PROXY
    editable: bool = True
    enabled: bool = True
    sort_order: int = 0
    is_system: bool = False
    owner_scenario_id: str = ""
    llm_routing_intent: str = ""
    is_default: bool = False
    updated_at: str = ""

    def scope(self) -> str:
        if self.is_system:
            return CONTRACT_SCOPE_SYSTEM
        if str(self.owner_scenario_id or "").strip():
            return CONTRACT_SCOPE_SCENARIO
        return CONTRACT_SCOPE_GLOBAL

    def primary_legacy_group(self) -> str:
        action = normalize_route_action(self.routing_action)
        if action == ROUTE_ACTION_DIRECT:
            return RULE_DIRECTNESS_DIRECT
        if action == ROUTE_ACTION_REJECT:
            return QUALITY_REJECT
        for pool_name in self.primary_pools:
            normalized = str(pool_name or "").strip()
            if normalized in POOL_ID_TO_LEGACY_QUALITY:
                return POOL_ID_TO_LEGACY_QUALITY[normalized]
        return ""

    def can_bind_standard_source(self) -> bool:
        return (
            bool(self.enabled)
            and normalize_route_action(self.routing_action) == ROUTE_ACTION_PROXY
            and len(self.primary_pools) == 1
            and str(self.primary_pools[0] or "").strip()
            in {POOL_HQ_PREMIUM, POOL_HQ_STANDARD, POOL_MEDIUM, POOL_BULK}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "scope": self.scope(),
            "can_bind_standard_source": self.can_bind_standard_source(),
            "primary_pool_display_names": [pool_display_name(item) for item in self.primary_pools],
            "fallback_pool_display_names": [pool_display_name(item) for item in self.fallback_pools],
        }


@dataclass
class RouteContractView:
    scenario_id: str
    contract_id: str
    display_name: str = ""
    description: str = ""
    llm_routing_intent: str = ""
    enabled: bool = True
    sort_order: int = 0
    is_default: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceCatalogEntry:
    category_name: str
    catalog_group: str = ""
    contract_id: str = ""
    sort_order: int = 0
    source: str = "migrated"
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "contract_display_name": contract_display_name(self.contract_id),
            "pin_group": self.catalog_group,
        }


@dataclass
class GeneralProfile:
    id: str
    name: str
    settings: dict[str, Any] = field(default_factory=dict)
    editor_state: dict[str, Any] = field(default_factory=dict)
    is_system_default: bool = True
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "settings": dict(self.settings),
            "editor_state": dict(self.editor_state),
            "is_system_default": self.is_system_default,
            "updated_at": self.updated_at,
        }


@dataclass
class ScenarioProfile:
    id: str
    slug: str
    name: str
    description: str = ""
    enabled: bool = True
    sort_order: int = 0
    settings: dict[str, Any] = field(default_factory=dict)
    editor_state: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "sort_order": self.sort_order,
            "settings": dict(self.settings),
            "editor_state": dict(self.editor_state),
            "updated_at": self.updated_at,
        }


@dataclass
class RenderWarning:
    code: str
    message: str
    target: str = ""
    severity: str = "warning"
    bucket: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RENDER_DIAGNOSTIC_BUCKETS = (
    "supported",
    "downgraded",
    "refused",
    "pending_validation",
)


@dataclass
class RendererDiagnostics:
    supported: list[RenderWarning] = field(default_factory=list)
    downgraded: list[RenderWarning] = field(default_factory=list)
    refused: list[RenderWarning] = field(default_factory=list)
    pending_validation: list[RenderWarning] = field(default_factory=list)

    def add(self, warning: RenderWarning) -> None:
        bucket = str(getattr(warning, "bucket", "") or "").strip()
        if bucket not in RENDER_DIAGNOSTIC_BUCKETS:
            if warning.severity in {"error", "fatal"}:
                bucket = "refused"
            else:
                bucket = "downgraded"
        getattr(self, bucket).append(warning)

    def extend(self, warnings: list[RenderWarning]) -> None:
        for warning in warnings:
            self.add(warning)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": [item.to_dict() for item in self.supported],
            "downgraded": [item.to_dict() for item in self.downgraded],
            "refused": [item.to_dict() for item in self.refused],
            "pending_validation": [item.to_dict() for item in self.pending_validation],
        }


@dataclass
class OverlayStatus:
    available: bool
    reason_code: str = ""
    reason: str = ""
    renderable_process_rule_count: int = 0
    renderable_external_proxy_program_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessRuleTemplate:
    id: str
    contract_id: str
    contract_display_name: str
    match_type: str
    value: str
    sort_order: int = 0
    enabled: bool = True
    migration_warning: str = ""

    @property
    def business_group(self) -> str:
        return self.contract_display_name

    @property
    def needs_rebind(self) -> bool:
        return self.migration_warning == "needs_rebind"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["business_group"] = self.contract_display_name
        payload["needs_rebind"] = self.needs_rebind
        return payload


@dataclass
class ExternalProxyProgramTemplate:
    id: str
    contract_id: str
    contract_display_name: str
    program_path: str
    args: list[str] = field(default_factory=list)
    local_port: int = 0
    name: str = ""
    sort_order: int = 0
    enabled: bool = True
    migration_warning: str = ""

    @property
    def business_group(self) -> str:
        return self.contract_display_name

    @property
    def needs_rebind(self) -> bool:
        return self.migration_warning == "needs_rebind"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["business_group"] = self.contract_display_name
        payload["needs_rebind"] = self.needs_rebind
        return payload


@dataclass
class PolicyRuleEntry:
    target_contract_id: str
    rule_type: str
    value: str
    extras: list[str] = field(default_factory=list)
    source_kind: str = "catalog"
    category_name: str = ""
    platform_scope: str = "any"

    def target_display_name(self) -> str:
        normalized = resolve_legacy_route_target(self.target_contract_id)
        if normalized == ROUTE_DIRECT_ACTION:
            return ROUTE_NATIVE_DIRECT_TARGET
        if normalized == ROUTE_REJECT_ACTION:
            return ROUTE_NATIVE_REJECT_TARGET
        return contract_display_name(normalized)

    def to_line(self, *, target_name: str | None = None) -> str:
        target = target_name if target_name is not None else self.target_display_name()
        return ",".join([self.rule_type, self.value, target, *[item for item in self.extras if item]])

    def to_ruleset_line(self) -> str:
        # The referencing RULE-SET chooses the policy. Only predicate options
        # belong in an asset; preserve their spelling and no-resolve presence.
        match_options = {"no-resolve", "src", "extended-matching"}
        return ",".join([
            self.rule_type,
            self.value,
            *(item for item in self.extras if item and item.strip().casefold() in match_options),
        ])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyIR:
    nodes: list[NodeRecord]
    pools: dict[str, list[str]]
    business_groups: list[BusinessGroup]
    rule_lines: list[str]
    default_group_name: str
    default_contract_id: str = ""
    device_strategy_preset: str = DEVICE_STRATEGY_PRESET_BALANCED
    metadata: dict[str, Any] = field(default_factory=dict)
    rule_entries: list[PolicyRuleEntry] = field(default_factory=list)
    contracts: list[RouteContract] = field(default_factory=list)
    catalog_bindings: list[ServiceCatalogEntry] = field(default_factory=list)
    general_profile: GeneralProfile | None = None
    dns: dict[str, Any] = field(default_factory=dict)
    tun: dict[str, Any] = field(default_factory=dict)
    sniffer: dict[str, Any] = field(default_factory=dict)
    http_processing: dict[str, Any] = field(default_factory=dict)
    rule_providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    process_rules: list[ProcessRuleTemplate] = field(default_factory=list)
    external_proxy_programs: list[ExternalProxyProgramTemplate] = field(default_factory=list)
    skip_proxy_direct_rules: list[str] = field(default_factory=list)
    warnings: list[RenderWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [item.to_dict() for item in self.nodes],
            "pools": {key: list(value) for key, value in self.pools.items()},
            "business_groups": [item.to_dict() for item in self.business_groups],
            "rule_lines": list(self.rule_lines),
            "default_group_name": self.default_group_name,
            "default_contract_id": self.default_contract_id,
            "device_strategy_preset": self.device_strategy_preset,
            "metadata": dict(self.metadata),
            "rule_entries": [item.to_dict() for item in self.rule_entries],
            "contracts": [item.to_dict() for item in self.contracts],
            "catalog_bindings": [item.to_dict() for item in self.catalog_bindings],
            "general_profile": self.general_profile.to_dict() if self.general_profile else None,
            "dns": dict(self.dns),
            "tun": dict(self.tun),
            "sniffer": dict(self.sniffer),
            "http_processing": dict(self.http_processing),
            "rule_providers": {
                key: dict(value)
                for key, value in self.rule_providers.items()
            },
            "process_rules": [item.to_dict() for item in self.process_rules],
            "external_proxy_programs": [item.to_dict() for item in self.external_proxy_programs],
            "warnings": [item.to_dict() for item in self.warnings],
        }


@dataclass
class DiffResult:
    key: str
    diff_type: str  # "added" | "removed" | "changed"
    primary_value: Any
    target_value: Any


@dataclass
class ReviewAnnotation:
    key: str
    diff_type: str
    primary_value: str  # JSON-serialized
    target_value: str  # JSON-serialized
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SurgeProfileArtifacts:
    main_conf: str
    domain_sets: dict[str, str] = field(default_factory=dict)
    rule_sets: dict[str, str] = field(default_factory=dict)
    subscription_metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[RenderWarning] = field(default_factory=list)
    blockers: list[RenderWarning] = field(default_factory=list)
    blocked: bool = False
    referenced_contracts: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_conf": self.main_conf,
            "domain_sets": dict(self.domain_sets),
            "rule_sets": dict(self.rule_sets),
            "subscription_metadata": dict(self.subscription_metadata),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "blockers": [item.to_dict() for item in self.blockers],
            "blocked": bool(self.blocked),
            "referenced_contracts": [dict(item) for item in self.referenced_contracts],
            "skipped": list(self.skipped),
        }


@dataclass
class MacOverlayTemplate:
    managed_url: str
    include_url: str
    process_rules: list[ProcessRuleTemplate] = field(default_factory=list)
    external_proxy_programs: list[ExternalProxyProgramTemplate] = field(default_factory=list)
    overlay_status: OverlayStatus | None = None
    warnings: list[RenderWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "managed_url": self.managed_url,
            "include_url": self.include_url,
            "process_rules": [item.to_dict() for item in self.process_rules],
            "external_proxy_programs": [item.to_dict() for item in self.external_proxy_programs],
            "overlay_status": self.overlay_status.to_dict() if self.overlay_status else None,
            "warnings": [item.to_dict() for item in self.warnings],
        }
