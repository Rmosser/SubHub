"""Tests for app.services.domain_binding_service – host parsing, multiplier hints, and reply parsing."""
from __future__ import annotations

import pytest

from app.models import GoRelayDomainBinding
from app.services.domain_binding_service import (
    ParsedBinding,
    binding_key,
    build_binding_index,
    parse_customer_reply,
    parse_entry_multiplier_hints,
    parse_host_value,
    _looks_like_placeholder,
    _normalize_multiplier,
    _strip_edge_quotes,
)


# ── _strip_edge_quotes ──────────────────────────────────────────────────────


class TestStripEdgeQuotes:
    def test_double_quotes(self):
        assert _strip_edge_quotes('"hello"') == "hello"

    def test_smart_quotes(self):
        assert _strip_edge_quotes("\u201chello\u201d") == "hello"

    def test_no_quotes(self):
        assert _strip_edge_quotes("hello") == "hello"

    def test_empty(self):
        assert _strip_edge_quotes("") == ""

    def test_none(self):
        assert _strip_edge_quotes(None) == ""


# ── _looks_like_placeholder ─────────────────────────────────────────────────


class TestLooksLikePlaceholder:
    def test_empty(self):
        assert _looks_like_placeholder("") is True

    def test_contact(self):
        assert _looks_like_placeholder("联系客服申请") is True

    def test_pending(self):
        assert _looks_like_placeholder("暂无ip") is True

    def test_real_host(self):
        assert _looks_like_placeholder("relay.example.com") is False


# ── parse_host_value ─────────────────────────────────────────────────────────


class TestParseHostValue:
    def test_normal_hostname(self):
        assert parse_host_value("relay.example.com") == "relay.example.com"

    def test_hostname_with_port(self):
        assert parse_host_value("relay.example.com:443") == "relay.example.com"

    def test_ipv6_bracketed(self):
        assert parse_host_value("[2001:db8::1]") == "2001:db8::1"

    def test_ipv6_with_port(self):
        assert parse_host_value("[2001:db8::1]:443") == "2001:db8::1"

    def test_empty(self):
        assert parse_host_value("") is None

    def test_none(self):
        assert parse_host_value(None) is None

    def test_placeholder(self):
        assert parse_host_value("联系客服申请") is None

    def test_ip_address(self):
        assert parse_host_value("192.168.1.1") == "192.168.1.1"

    def test_ip_with_port(self):
        assert parse_host_value("192.168.1.1:8080") == "192.168.1.1"

    def test_messy_text_extracts_host(self):
        # The fallback regex should still extract something.
        result = parse_host_value("connect to relay.example.com now")
        assert result is not None


# ── _normalize_multiplier ───────────────────────────────────────────────────


class TestNormalizeMultiplier:
    def test_integer(self):
        assert _normalize_multiplier("3") == "3"

    def test_decimal(self):
        assert _normalize_multiplier("1.5") == "1.5"

    def test_zero(self):
        assert _normalize_multiplier("0") is None

    def test_negative(self):
        assert _normalize_multiplier("-1") is None

    def test_empty(self):
        assert _normalize_multiplier("") is None

    def test_garbage(self):
        assert _normalize_multiplier("abc") is None


# ── parse_entry_multiplier_hints ─────────────────────────────────────────────


class TestParseEntryMultiplierHints:
    def test_chinese_label(self):
        text = "IPLC-JP 倍率: 3"
        result = parse_entry_multiplier_hints(text)
        assert len(result) >= 1
        # The key should be the entry name portion.
        assert any("3" == v for v in result.values())

    def test_x_suffix(self):
        text = "IPLC-HK 1.5x"
        result = parse_entry_multiplier_hints(text)
        assert len(result) >= 1
        assert any("1.5" == v for v in result.values())

    def test_empty_input(self):
        assert parse_entry_multiplier_hints("") == {}

    def test_multiline(self):
        text = """\
IPLC-JP 倍率: 3
IPLC-HK 倍率: 1.5
"""
        result = parse_entry_multiplier_hints(text)
        assert len(result) == 2

    def test_bullet_prefix_stripped(self):
        text = "- IPLC-JP 倍率: 3"
        result = parse_entry_multiplier_hints(text)
        assert len(result) >= 1

    def test_no_valid_hints(self):
        text = "this is just random text"
        assert parse_entry_multiplier_hints(text) == {}


# ── parse_customer_reply ─────────────────────────────────────────────────────


class TestParseCustomerReply:
    def test_standard_reply(self):
        text = """\
「IPLC-JP」
【电信 IPv4】ct-relay.example.com
【联通 IPv4】cu-relay.example.com
【移动 IPv4】cm-relay.example.com
"""
        result = parse_customer_reply(text)
        assert len(result) == 3
        assert result[0].entry_name  # Should be non-empty.
        assert result[0].host_value == "ct-relay.example.com"
        assert result[0].isp == "ct"
        assert result[1].isp == "cu"
        assert result[2].isp == "cm"

    def test_multiple_entries(self):
        text = """\
「IPLC-JP」
【电信 IPv4】ct-jp.example.com

「IPLC-HK」
【电信 IPv4】ct-hk.example.com
"""
        result = parse_customer_reply(text)
        assert len(result) == 2
        # First entry should be IPLC-JP
        assert "JP" in result[0].entry_name
        # Second entry should be IPLC-HK
        assert "HK" in result[1].entry_name

    def test_ipv6_host(self):
        text = """\
「IPLC-JP」
【电信 IPv6】[2001:db8::1]
"""
        result = parse_customer_reply(text)
        assert len(result) == 1
        assert result[0].host_value == "2001:db8::1"
        assert result[0].ip_version == "ipv6"

    def test_empty_input(self):
        assert parse_customer_reply("") == []

    def test_skips_preamble_lines(self):
        text = """\
申请开通 IPLC 线路
官网账号: test@example.com
用途场景: streaming
「IPLC-JP」
【电信 IPv4】relay.example.com
"""
        result = parse_customer_reply(text)
        assert len(result) == 1
        assert result[0].host_value == "relay.example.com"

    def test_placeholder_host_skipped(self):
        text = """\
「IPLC-JP」
【电信 IPv4】联系客服申请
"""
        result = parse_customer_reply(text)
        assert result == []

    def test_generic_ip_label_falls_back_to_entry_isp(self):
        text = """\
「Lv2」广东隧道「移动入口」
【IPv6】[2409:8c54:1841:2008:0:1:0:1e5]
"""
        result = parse_customer_reply(text)
        assert len(result) == 1
        assert result[0].isp == "cm"
        assert result[0].ip_version == "ipv6"

    def test_no_entry_header_no_bindings(self):
        """Without a 「...」 header, labelled lines should be skipped."""
        text = "【电信 IPv4】relay.example.com"
        result = parse_customer_reply(text)
        assert result == []


# ── binding_key ──────────────────────────────────────────────────────────────


class TestBindingKey:
    def test_normal(self):
        key = binding_key("acc1", "IPLC-JP", "ct", "ipv4")
        assert "acc1" in key
        assert "ct" in key
        assert "ipv4" in key

    def test_case_insensitive(self):
        k1 = binding_key("acc1", "IPLC-JP", "CT", "IPv4")
        k2 = binding_key("acc1", "IPLC-JP", "ct", "ipv4")
        # Both should normalize to the same isp/ip_version.
        assert k1 == k2


# ── build_binding_index ─────────────────────────────────────────────────────


class TestBuildBindingIndex:
    def test_basic(self):
        b = GoRelayDomainBinding(
            id="b1", account_id="acc1", entry_name="IPLC-JP",
            isp="ct", ip_version="ipv4", host_value="relay.example.com",
            source="import", status="approved", updated_at="2025-01-01",
        )
        index = build_binding_index([b])
        key = binding_key("acc1", "IPLC-JP", "ct", "ipv4")
        assert key in index
        assert index[key].host_value == "relay.example.com"

    def test_empty(self):
        assert build_binding_index([]) == {}
