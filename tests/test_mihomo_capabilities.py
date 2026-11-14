from __future__ import annotations

import pytest
import yaml

from app.models import CONTRACT_HQ_PREMIUM, NodeRecord, PolicyRuleEntry, QUALITY_MEDIUM
from app.services.subscription_builder import (
    build_clash_config,
    build_clash_profile_artifacts,
    build_policy_ir,
)


def _base_nodes() -> list[NodeRecord]:
    return [
        NodeRecord(
            name="n1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]


def _base_rules() -> list[str]:
    return ["DOMAIN-SUFFIX,example.com,中等质量"]


def _render_mihomo(
    *,
    nodes: list[NodeRecord] | None = None,
    rules: list[str] | None = None,
    profile: str = "lazycat",
    profile_settings: dict[str, object] | None = None,
    policy_ir=None,
):
    text, skipped, diagnostics = build_clash_profile_artifacts(
        _base_nodes() if nodes is None else nodes,
        _base_rules() if rules is None else rules,
        profile=profile,
        profile_settings=profile_settings,
        policy_ir=policy_ir,
    )
    return yaml.safe_load(text), skipped, [item.to_dict() for item in diagnostics]


def _xfail_if_missing(payload: dict[str, object], path: tuple[str, ...], reason: str) -> None:
    current: object = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            pytest.xfail(reason)
        current = current[part]


def _attach_mihomo_rule_providers(policy_ir, providers: dict[str, dict[str, object]]) -> None:
    # Support either a direct field or a nested IR shape as the renderer evolves.
    policy_ir.rule_providers = providers
    policy_ir.providers = {"rule_providers": providers}


def test_mihomo_renders_confirmed_profile_and_control_api_fields() -> None:
    payload, skipped, warnings = _render_mihomo(
        profile_settings={
            "clash_ipv6": True,
            "clash_profile_store_selected": True,
            "clash_profile_store_fake_ip": True,
            "clash_external_controller": "127.0.0.1:9090",
            "clash_secret": "api-secret-01",
            "clash_external_ui": "ui",
            "clash_external_ui_name": "metacube",
            "clash_external_ui_url": "https://example.com/ui.tgz",
        }
    )

    assert skipped == []
    assert payload["ipv6"] is True
    _xfail_if_missing(
        payload,
        ("profile",),
        "pending Mihomo profile/control field implementation",
    )
    _xfail_if_missing(
        payload,
        ("external-controller",),
        "pending Mihomo profile/control field implementation",
    )

    assert payload["profile"] == {
        "store-selected": True,
        "store-fake-ip": True,
    }
    assert payload["external-controller"] == "127.0.0.1:9090"
    assert payload["secret"] == "api-secret-01"
    assert payload["external-ui"] == "ui"
    assert payload["external-ui-name"] == "metacube"
    assert payload["external-ui-url"] == "https://example.com/ui.tgz"


def test_mihomo_renders_confirmed_dns_tun_and_sniffer_fields() -> None:
    payload, skipped, warnings = _render_mihomo(
        profile_settings={
            "clash_dns_enhanced_mode": "fake-ip",
            "clash_dns_fake_ip_range": "198.18.0.1/16",
            "clash_dns_fake_ip_filter_mode": "rule",
            "clash_dns_proxy_server_nameserver": ["https://doh.pub/dns-query"],
            "clash_dns_direct_nameserver": ["223.5.5.5"],
            "clash_dns_respect_rules": True,
            "clash_tun_enable": True,
            "clash_tun_include_uid": [1000, 1001],
            "clash_tun_exclude_uid": [0],
            "clash_tun_include_package": ["com.example.browser"],
            "clash_tun_exclude_package": ["com.example.games"],
            "clash_sniffer_enable": True,
            "clash_sniffer_force_dns_mapping": True,
            "clash_sniffer_parse_pure_ip": False,
            "clash_sniffer_override_destination": False,
            "clash_sniffer_http_ports": [80, "8080-8880"],
            "clash_sniffer_tls_ports": [443, 8443],
            "clash_sniffer_quic_ports": [443, 8443],
            "clash_sniffer_force_domain": ["+.v2ex.com"],
            "clash_sniffer_skip_domain": ["Mijia Cloud"],
            "clash_sniffer_skip_src_address": ["10.0.0.0/8"],
            "clash_sniffer_skip_dst_address": ["192.168.0.0/16"],
        }
    )

    assert skipped == []
    _xfail_if_missing(
        payload,
        ("dns", "fake-ip-range"),
        "pending Mihomo dns/tun/sniffer implementation",
    )
    _xfail_if_missing(
        payload,
        ("tun", "include-uid"),
        "pending Mihomo dns/tun/sniffer implementation",
    )
    _xfail_if_missing(
        payload,
        ("sniffer",),
        "pending Mihomo dns/tun/sniffer implementation",
    )

    assert payload["dns"]["fake-ip-range"] == "198.18.0.1/16"
    assert payload["dns"]["fake-ip-filter-mode"] == "rule"
    assert payload["dns"]["proxy-server-nameserver"] == ["https://doh.pub/dns-query"]
    assert payload["dns"]["direct-nameserver"] == ["223.5.5.5"]
    assert payload["dns"]["respect-rules"] is True

    assert payload["tun"]["enable"] is True
    assert payload["tun"]["include-uid"] == [1000, 1001]
    assert payload["tun"]["exclude-uid"] == [0]
    assert payload["tun"]["include-package"] == ["com.example.browser"]
    assert payload["tun"]["exclude-package"] == ["com.example.games"]

    assert payload["sniffer"] == {
        "enable": True,
        "force-dns-mapping": True,
        "parse-pure-ip": False,
        "override-destination": False,
        "sniff": {
            "http": {"ports": [80, "8080-8880"]},
            "tls": {"ports": [443, 8443]},
            "quic": {"ports": [443, 8443]},
        },
        "force-domain": ["+.v2ex.com"],
        "skip-domain": ["Mijia Cloud"],
        "skip-src-address": ["10.0.0.0/8"],
        "skip-dst-address": ["192.168.0.0/16"],
    }


def test_mihomo_default_lazycat_path_uses_redir_host_without_tun_or_fake_ip_fields() -> None:
    payload, skipped, warnings = _render_mihomo()

    assert skipped == []
    assert payload["dns"]["enhanced-mode"] == "redir-host"
    assert payload["dns"]["use-hosts"] is True
    assert payload["dns"]["respect-rules"] is True
    assert "fake-ip-range" not in payload["dns"]
    assert "fake-ip-filter-mode" not in payload["dns"]
    assert "fake-ip-filter" not in payload["dns"]
    assert "tun" not in payload
    assert "sniffer" not in payload


def test_mihomo_renders_rule_providers_and_ruleset_rules() -> None:
    policy_ir = build_policy_ir(
        [],
        [],
        rule_entries=[
            PolicyRuleEntry(
                target_contract_id=CONTRACT_HQ_PREMIUM,
                rule_type="RULE-SET",
                value="streaming",
                source_kind="custom",
                category_name="streaming",
            ),
        ],
    )
    _attach_mihomo_rule_providers(
        policy_ir,
        {
            "streaming": {
                "type": "http",
                "behavior": "domain",
                "format": "mrs",
                "url": "https://example.com/rules/streaming.mrs",
                "path": "./ruleset/streaming.mrs",
                "interval": 86400,
            }
        },
    )

    payload, skipped, warnings = _render_mihomo(policy_ir=policy_ir, nodes=[], rules=[])

    assert skipped == []
    _xfail_if_missing(
        payload,
        ("rule-providers",),
        "pending Mihomo rule-provider implementation",
    )

    assert payload["rule-providers"] == {
        "streaming": {
            "type": "http",
            "behavior": "domain",
            "format": "mrs",
            "url": "https://example.com/rules/streaming.mrs",
            "path": "./ruleset/streaming.mrs",
            "interval": 86400,
            "proxy": "DIRECT",
        }
    }
    assert "RULE-SET,streaming,高质量-高倍率" in payload["rules"]


def test_mihomo_safe_renderer_does_not_silently_emit_pending_fields() -> None:
    payload, skipped, warnings = _render_mihomo(
        profile_settings={
            "clash_profile_store_selected": True,
            "clash_sniffer_enable": True,
            "clash_always_real_ip": ["*.pending.example"],
            "clash_ipv6": True,
            "clash_tcp_concurrent": True,
        }
    )

    assert skipped == []
    _xfail_if_missing(
        payload,
        ("profile",),
        "pending Mihomo safe-field gating implementation",
    )
    _xfail_if_missing(
        payload,
        ("sniffer",),
        "pending Mihomo safe-field gating implementation",
    )

    dns_payload = payload.get("dns") if isinstance(payload.get("dns"), dict) else {}
    assert "render-warnings" not in payload

    assert payload["ipv6"] is True
    assert "tcp-concurrent" not in payload
    assert "always-real-ip" not in dns_payload
    assert warnings, "pending/unsupported Mihomo keys should produce render diagnostics"
    assert all(item.get("code") != "clash-ipv6-pending-validation" for item in warnings)


def test_mihomo_skip_proxy_decomposition_defaults_to_direct_rules_without_fake_ip() -> None:
    """skip-proxy patterns should keep DIRECT rules even when the mainline is redir-host."""
    payload, skipped, warnings = _render_mihomo(
        profile_settings={
            "surge_skip_proxy": ["example.com", "10.0.0.0/8", "*.local"],
        }
    )

    assert skipped == []
    assert "fake-ip-filter" not in payload["dns"]
    assert payload["tun"]["enable"] is False
    assert "10.0.0.0/8" in payload["tun"]["route-exclude-address"]
    warning_codes = {item["code"] for item in warnings}
    assert "clash-skip-proxy-cidr-requires-tun" in warning_codes

    rules = payload["rules"]
    assert "DOMAIN-SUFFIX,example.com,DIRECT" in rules
    assert "DOMAIN-SUFFIX,local,DIRECT" in rules
    # DIRECT rules should appear before MATCH
    match_idx = next(i for i, r in enumerate(rules) if r.startswith("MATCH,"))
    for rule in ["DOMAIN-SUFFIX,example.com,DIRECT", "DOMAIN-SUFFIX,local,DIRECT"]:
        assert rules.index(rule) < match_idx


def test_mihomo_skip_proxy_fake_ip_mode_merges_dns_filter_and_tun_routes_without_duplicates() -> None:
    """fake-ip mode keeps the legacy skip-proxy DNS/TUN decomposition behavior."""
    payload, skipped, warnings = _render_mihomo(
        profile_settings={
            "clash_dns_enhanced_mode": "fake-ip",
            "clash_tun_enable": True,
            "surge_skip_proxy": ["example.com", "10.0.0.0/8"],
            "clash_fake_ip_filter": ["+.example.com"],
        }
    )

    assert skipped == []
    fake_ip_filter = payload["dns"]["fake-ip-filter"]
    assert fake_ip_filter.count("DOMAIN-SUFFIX,example.com,real-ip") == 1
    assert "10.0.0.0/8" in payload["tun"]["route-exclude-address"]


def test_mihomo_rejects_invalid_rule_provider_format_combinations() -> None:
    policy_ir = build_policy_ir(
        [],
        [],
        rule_entries=[
            PolicyRuleEntry(
                target_contract_id=CONTRACT_HQ_PREMIUM,
                rule_type="RULE-SET",
                value="classical-bad",
                source_kind="custom",
                category_name="classical-bad",
            ),
        ],
    )
    _attach_mihomo_rule_providers(
        policy_ir,
        {
            "classical-bad": {
                "type": "http",
                "behavior": "classical",
                "format": "mrs",
                "url": "https://example.com/rules/classical-bad.mrs",
                "path": "./ruleset/classical-bad.mrs",
                "interval": 3600,
            }
        },
    )

    text, skipped, warnings = build_clash_profile_artifacts(
        [],
        [],
        profile="lazycat",
        policy_ir=policy_ir,
    )
    payload = yaml.safe_load(text)

    assert skipped == []
    _xfail_if_missing(
        payload,
        ("rule-providers",),
        "pending Mihomo rule-provider validation implementation",
    )

    assert "classical-bad" not in payload["rule-providers"]
    assert "RULE-SET,classical-bad,高质量-高倍率" not in payload["rules"]
    assert any(
        ("mrs" in item.message.lower() or "classical" in item.message.lower())
        and item.bucket in {"refused", "downgraded", "pending_validation"}
        for item in warnings
    )
