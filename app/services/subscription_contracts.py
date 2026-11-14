from __future__ import annotations

from app.models import (
    QUALITY_BULK,
    QUALITY_CHAIN_HOME,
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
)

CLASH_PROVIDER_KEY_BY_GROUP = {
    QUALITY_HIGH_PREMIUM: "high-premium",
    QUALITY_HIGH_STANDARD: "high-standard",
    QUALITY_MEDIUM: "medium",
    QUALITY_BULK: "bulk",
    QUALITY_CHAIN_HOME: "chain-home",
}

CLASH_PROVIDER_GROUP_BY_KEY = {
    provider_key: quality_group
    for quality_group, provider_key in CLASH_PROVIDER_KEY_BY_GROUP.items()
}

CLASH_PROVIDER_KEYS = tuple(CLASH_PROVIDER_GROUP_BY_KEY.keys())
CLASH_BUNDLE_ROOT_FILES = ("AUDIT.md", "README.txt", "clash.yaml", "manifest.json")
CLASH_BUNDLE_PROVIDER_PATHS = tuple(f"providers/{provider_key}.yaml" for provider_key in CLASH_PROVIDER_KEYS)
CLASH_BUNDLE_FILES = CLASH_BUNDLE_ROOT_FILES + CLASH_BUNDLE_PROVIDER_PATHS

CLASH_UDP_SUPPORTED_PROTOCOLS = frozenset(
    {
        "ss",
        "socks5",
        "wireguard",
        "trojan",
        "vmess",
        "vless",
        "anytls",
        "hysteria2",
        "tuic",
    }
)

CLASH_BLOCKER_CODES = (
    "clash-referenced-empty-contract",
    "clash-cidr-overlap-blocker",
    "clash-provider-health-check-missing",
    "clash-use-group-empty-fallback-missing",
)
SURGE_BLOCKER_CODES = ("surge-referenced-empty-contract", "surge-cidr-overlap-blocker")

SUBSCRIPTION_WARNING_CODES = (
    "clash-cidr-overlap-pruned",
    "clash-cidr-overlap-split",
    "clash-cidr-autofixed",
    "clash-domain-ip-autofixed",
    "clash-rule-dropped-invalid",
    "conflicting-rule-target",
    "duplicate-ip-rule",
    "empty-contract",
    "empty-pool",
    "invalid-rule-dropped",
    "mac-only-rule-ignored",
    "surge-cidr-overlap-pruned",
    "surge-cidr-overlap-split",
    "surge-unsupported-node",
)

SHADOWROCKET_MAIN_CONFIG_MODE = "inline-proxies"
