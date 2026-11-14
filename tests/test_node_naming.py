"""Tests for app.services.node_naming – multiplier resolution and node name formatting."""
from __future__ import annotations

import pytest
from dataclasses import replace

from app.models import MULTIPLIER_THRESHOLD, NodeRecord, QUALITY_HIGH_PREMIUM, QUALITY_HIGH_STANDARD
from app.services.node_naming import (
    _normalize_multiplier,
    decorate_high_quality_node_name,
    extract_high_quality_airport_multiplier,
    format_gorelay_node_name,
    format_standard_node_name,
    resolve_multiplier,
    resolve_quality_group,
)


def test_node_connection_identity_keeps_source_quality_device_and_credentials() -> None:
    node = NodeRecord(
        name="Display", host="server.example", port=443, protocol="trojan", password="secret",
        source_id="source", source_type="standard", quality_group=QUALITY_HIGH_PREMIUM, device_key="mac",
        raw={"sni": "tls.example"},
    )
    assert replace(node, name="Other display").dedupe_key() == node.dedupe_key()
    for alternate in (
        replace(node, password="other"), replace(node, source_id="other"),
        replace(node, device_key="phone"), replace(node, quality_group=QUALITY_HIGH_STANDARD),
        replace(node, raw={"sni": "other.example"}), replace(node, account_id="account"),
    ):
        assert alternate.dedupe_key() != node.dedupe_key()
    assert "secret" not in node.dedupe_key()


# ── _normalize_multiplier ───────────────────────────────────────────────────


class TestNormalizeMultiplier:
    def test_integer(self):
        assert _normalize_multiplier("3") == "3"

    def test_decimal(self):
        assert _normalize_multiplier("1.5") == "1.5"

    def test_trailing_x(self):
        assert _normalize_multiplier("3x") == "3"

    def test_uppercase_x(self):
        assert _normalize_multiplier("3X") == "3"

    def test_zero_returns_question(self):
        assert _normalize_multiplier("0") == "?"

    def test_negative_returns_question(self):
        assert _normalize_multiplier("-1") == "?"

    def test_empty_returns_question(self):
        assert _normalize_multiplier("") == "?"

    def test_garbage_returns_question(self):
        assert _normalize_multiplier("abc") == "?"

    def test_trailing_zeros_stripped(self):
        assert _normalize_multiplier("1.50") == "1.5"

    def test_whole_number_with_dot_zero(self):
        assert _normalize_multiplier("3.0") == "3"


# ── resolve_multiplier ──────────────────────────────────────────────────────


class TestResolveMultiplier:
    def test_from_entry_name(self):
        assert resolve_multiplier("IPLC-JP 3x") == "3"

    def test_from_line_name(self):
        assert resolve_multiplier("something", "TestDevice 1.5x") == "1.5"

    def test_from_raw_multiplier(self):
        assert resolve_multiplier("entry", raw={"multiplier": "5x"}) == "5"

    def test_from_raw_rate(self):
        assert resolve_multiplier("entry", raw={"rate": "2x"}) == "2"

    def test_from_chinese_label(self):
        assert resolve_multiplier("IPLC-HK 倍率3") == "3"

    def test_unknown_returns_question(self):
        assert resolve_multiplier("plain entry name") == "?"

    def test_empty_input(self):
        assert resolve_multiplier("") == "?"


# ── resolve_quality_group ────────────────────────────────────────────────────


class TestResolveQualityGroup:
    def test_unknown_multiplier(self):
        assert resolve_quality_group("?") == QUALITY_HIGH_STANDARD

    def test_high_multiplier(self):
        assert resolve_quality_group("5") == QUALITY_HIGH_PREMIUM

    def test_exact_threshold(self):
        assert resolve_quality_group(str(MULTIPLIER_THRESHOLD)) == QUALITY_HIGH_PREMIUM

    def test_low_multiplier(self):
        assert resolve_quality_group("1") == QUALITY_HIGH_STANDARD

    def test_invalid_returns_standard(self):
        assert resolve_quality_group("abc") == QUALITY_HIGH_STANDARD


# ── extract_high_quality_airport_multiplier ─────────────────────────────────


class TestExtractHighQualityAirportMultiplier:
    def test_parse_10x(self):
        assert extract_high_quality_airport_multiplier("双线 · 10x · 广港 IEPL") == "10"

    def test_parse_2_3x(self):
        assert extract_high_quality_airport_multiplier("电信 · 2.3x · 广东隧道") == "2.3"

    def test_parse_with_suffix_index(self):
        assert extract_high_quality_airport_multiplier("联通 · 2.3x · 广东隧道 (2)") == "2.3"

    def test_parse_after_standard_prefix(self):
        assert extract_high_quality_airport_multiplier("[机场A] 双线 · 10x · 广港 IEPL") == "10"

    def test_parse_from_raw_name_first(self):
        assert (
            extract_high_quality_airport_multiplier(
                "[机场A] 未标倍率",
                raw={"name": "联通 · 2.3x · 广东隧道"},
            )
            == "2.3"
        )

    def test_unknown_returns_none(self):
        assert extract_high_quality_airport_multiplier("双线 · 广港 IEPL") is None


# ── format_gorelay_node_name ────────────────────────────────────────────────


class TestFormatGorelayNodeName:
    def test_ct(self):
        name = format_gorelay_node_name(entry_name="IPLC-JP", isp="ct", multiplier="3")
        assert "电信" in name
        assert "3x" in name
        assert "IPLC-JP" in name

    def test_cu(self):
        name = format_gorelay_node_name(entry_name="IPLC-JP", isp="cu", multiplier="1.5")
        assert "联通" in name
        assert "1.5x" in name

    def test_cm(self):
        name = format_gorelay_node_name(entry_name="IPLC-JP", isp="cm", multiplier="2")
        assert "移动" in name

    def test_other(self):
        name = format_gorelay_node_name(entry_name="IPLC-JP", isp="other", multiplier="?")
        assert "双线" in name

    def test_unknown_isp_falls_back_to_other(self):
        name = format_gorelay_node_name(entry_name="IPLC-JP", isp="xyz", multiplier="1")
        assert "双线" in name


# ── format_standard_node_name ────────────────────────────────────────────────


class TestFormatStandardNodeName:
    def test_normal(self):
        assert format_standard_node_name("Source", "NodeA") == "[Source] NodeA"

    def test_empty_source(self):
        assert format_standard_node_name("", "NodeA") == "[标准源] NodeA"

    def test_empty_name(self):
        assert format_standard_node_name("Source", "") == "[Source] Unnamed"

    def test_both_empty(self):
        assert format_standard_node_name("", "") == "[标准源] Unnamed"


# ── decorate_high_quality_node_name ─────────────────────────────────────────


class TestDecorateHighQualityNodeName:
    def test_high_quality_adds_us_marker(self):
        assert (
            decorate_high_quality_node_name("移动 · 10x · 广港 IEPL", QUALITY_HIGH_PREMIUM)
            == "🇺🇸 美国 · 移动 · 10x · 广港 IEPL"
        )

    def test_non_high_quality_keeps_original_name(self):
        assert (
            decorate_high_quality_node_name("[机场A] Tokyo-01", "中等质量")
            == "[机场A] Tokyo-01"
        )

    def test_standard_source_prefix_stays_first(self):
        assert (
            decorate_high_quality_node_name("[机场A] 双线 · 10x · 广港 IEPL", QUALITY_HIGH_STANDARD)
            == "[机场A] 🇺🇸 美国 · 双线 · 10x · 广港 IEPL"
        )

    @pytest.mark.parametrize(
        "name",
        [
            "🇺🇸 美国 · 移动 · 10x · 广港 IEPL",
            "[机场A] 美国-洛杉矶-03",
            "[机场A] US-01",
            "[机场A] USA Premium",
            "[机场A] United States West",
        ],
    )
    def test_existing_us_marker_is_not_duplicated(self, name):
        assert decorate_high_quality_node_name(name, QUALITY_HIGH_STANDARD) == name
