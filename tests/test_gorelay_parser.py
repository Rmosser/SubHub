"""Tests for app.services.collectors.gorelay_parser – pure-function text-to-rule parsing."""
from __future__ import annotations

import pytest

from app.models import CollectedRule
from app.services.collectors.gorelay_parser import (
    _clean_host,
    _looks_like_placeholder,
    _parse_host_only,
    _parse_host_port,
    _safe_port,
    parse_detail_text_to_rules,
)


# ── helpers ──────────────────────────────────────────────────────────────────

COMMON = dict(
    account_id="acc1",
    rule_id="r1",
    line_name="Test Line",
    device_name="TestDevice",
    entry_name="IPLC-JP",
)


# ── _safe_port ───────────────────────────────────────────────────────────────


class TestSafePort:
    def test_valid_port(self):
        assert _safe_port("443") == 443

    def test_none_returns_fallback(self):
        assert _safe_port(None) == 0
        assert _safe_port(None, 8080) == 8080

    def test_zero_returns_fallback(self):
        assert _safe_port("0", 100) == 100

    def test_negative_returns_fallback(self):
        assert _safe_port("-1", 100) == 100

    def test_exceeds_max_returns_fallback(self):
        assert _safe_port("70000", 100) == 100

    def test_non_numeric_returns_fallback(self):
        assert _safe_port("abc", 100) == 100

    def test_int_input(self):
        assert _safe_port(8080) == 8080


# ── _clean_host ──────────────────────────────────────────────────────────────


class TestCleanHost:
    def test_strips_brackets(self):
        assert _clean_host("[2001:db8::1]") == "2001:db8::1"

    def test_no_brackets(self):
        assert _clean_host("example.com") == "example.com"

    def test_whitespace(self):
        assert _clean_host("  example.com  ") == "example.com"


# ── _looks_like_placeholder ──────────────────────────────────────────────────


class TestLooksLikePlaceholder:
    def test_empty_string(self):
        assert _looks_like_placeholder("") is True

    def test_none(self):
        assert _looks_like_placeholder(None) is True

    def test_contact_placeholder(self):
        assert _looks_like_placeholder("联系客服申请") is True

    def test_pending_placeholder(self):
        assert _looks_like_placeholder("通报暂无") is True
        assert _looks_like_placeholder("暂无 ip") is True
        assert _looks_like_placeholder("暂无ip") is True
        assert _looks_like_placeholder("待申请") is True

    def test_real_host(self):
        assert _looks_like_placeholder("relay.example.com") is False

    def test_case_insensitive(self):
        assert _looks_like_placeholder("暂无 IP") is True


# ── _parse_host_port ─────────────────────────────────────────────────────────


class TestParseHostPort:
    def test_normal(self):
        assert _parse_host_port("relay.example.com:8443") == ("relay.example.com", 8443)

    def test_ipv6_bracket(self):
        result = _parse_host_port("[2001:db8::1]:443")
        assert result == ("2001:db8::1", 443)

    def test_empty(self):
        assert _parse_host_port("") is None

    def test_no_port(self):
        assert _parse_host_port("relay.example.com") is None

    def test_placeholder(self):
        # The regex won't match placeholders with Chinese characters anyway.
        assert _parse_host_port("联系客服申请: 443") is None


# ── _parse_host_only ─────────────────────────────────────────────────────────


class TestParseHostOnly:
    def test_hostname(self):
        assert _parse_host_only("relay.example.com") == "relay.example.com"

    def test_ipv6_bracket(self):
        assert _parse_host_only("[2001:db8::1]") == "2001:db8::1"

    def test_placeholder_returns_none(self):
        assert _parse_host_only("联系客服申请") is None

    def test_empty_returns_none(self):
        assert _parse_host_only("") is None


# ── parse_detail_text_to_rules ───────────────────────────────────────────────


class TestParseDetailTextToRules:
    """Tests for the main entry point: parse_detail_text_to_rules()."""

    def test_labeled_host_port_lines(self):
        text = """\
端口: 10443
【电信 IPv4】relay-ct.example.com:10443
【联通 IPv4】relay-cu.example.com:10443
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 2
        assert rules[0].host == "relay-ct.example.com"
        assert rules[0].port == 10443
        assert rules[0].isp == "ct"
        assert rules[0].status == "ready"
        assert rules[1].host == "relay-cu.example.com"
        assert rules[1].isp == "cu"

    def test_labeled_host_only_uses_default_port(self):
        text = """\
端口: 20000
【电信 IPv4】relay-ct.example.com
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].host == "relay-ct.example.com"
        assert rules[0].port == 20000

    def test_placeholder_value_creates_pending(self):
        text = """\
端口: 10443
【联通 IPv4】联系客服申请
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].status == "pending_domain"
        assert rules[0].host == ""
        assert rules[0].port == 10443

    def test_placeholder_with_contact_port(self):
        text = """\
端口: 10443
【移动 IPv4】联系客服申请: 20000
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].status == "pending_domain"
        assert rules[0].port == 20000

    def test_generic_ip_labels_fall_back_to_entry_isp(self):
        text = """\
端口: 10443
【IPv4】联系客服申请
【IPv6】[2409:8c54:1841:2008:0:1:0:1e5]
"""
        rules = parse_detail_text_to_rules(
            **{
                **COMMON,
                "entry_name": "「Lv2」广东隧道「移动入口」",
            },
            detail_text=text,
        )
        assert len(rules) == 2
        assert {rule.isp for rule in rules} == {"cm"}
        ready = next(rule for rule in rules if rule.status == "ready")
        assert ready.ip_version == "ipv6"

    def test_explicit_label_keeps_priority_over_entry_name(self):
        text = """\
端口: 10443
【移动-IPv6】[2409:8c54:810:a05:3914:2101:0:1013]
"""
        rules = parse_detail_text_to_rules(
            **{
                **COMMON,
                "entry_name": "「Lv1」深港 IEPL「电信联通」",
            },
            detail_text=text,
        )
        assert len(rules) == 1
        assert rules[0].isp == "cm"

    def test_ipv6_host_port_in_label(self):
        text = """\
端口: 443
【电信 IPv6】[2001:db8::1]:443
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].host == "2001:db8::1"
        assert rules[0].port == 443
        assert rules[0].ip_version == "ipv6"

    def test_empty_input(self):
        rules = parse_detail_text_to_rules(**COMMON, detail_text="")
        assert rules == []

    def test_whitespace_only_input(self):
        rules = parse_detail_text_to_rules(**COMMON, detail_text="   \n\n  ")
        assert rules == []

    def test_plain_host_port_fallback(self):
        """Lines without 【labels】 should still be parsed as host:port."""
        text = "relay.example.com:8443"
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].host == "relay.example.com"
        assert rules[0].port == 8443
        assert rules[0].isp == "other"

    def test_plain_host_only_with_default_port(self):
        text = """\
端口: 30000
relay.example.com
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].host == "relay.example.com"
        assert rules[0].port == 30000
        assert rules[0].isp == "other"

    def test_mixed_ready_and_pending(self):
        text = """\
端口: 10443
【电信 IPv4】relay-ct.example.com:10443
【联通 IPv4】暂无ip
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 2
        ready = [r for r in rules if r.status == "ready"]
        pending = [r for r in rules if r.status == "pending_domain"]
        assert len(ready) == 1
        assert len(pending) == 1

    def test_label_without_host_uses_pending(self):
        """A labeled line with unparseable value but a default port should become pending_domain."""
        text = """\
端口: 10443
【电信 IPv4】一些无法解析的文字
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].status == "pending_domain"
        assert rules[0].port == 10443

    def test_accounts_and_ids_propagated(self):
        text = "relay.example.com:443"
        rules = parse_detail_text_to_rules(
            account_id="myacc",
            rule_id="rule42",
            line_name="my-line",
            device_name="mydev",
            entry_name="IPLC-HK",
            detail_text=text,
        )
        assert rules[0].account_id == "myacc"
        assert rules[0].rule_id == "rule42"
        assert rules[0].device_name == "mydev"

    def test_port_extracted_from_port_label_english(self):
        text = """\
port: 12345
【电信 IPv4】relay.example.com
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].port == 12345

    def test_fallback_placeholder_line_with_default_port(self):
        """Plain placeholder line (no label) should create pending_domain if a port exists."""
        text = """\
端口: 10443
通报暂无
"""
        rules = parse_detail_text_to_rules(**COMMON, detail_text=text)
        assert len(rules) == 1
        assert rules[0].status == "pending_domain"
        assert rules[0].port == 10443
