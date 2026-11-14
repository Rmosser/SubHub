from __future__ import annotations

from app.services.normalize import resolve_gorelay_isp


class TestResolveGorelayIsp:
    def test_explicit_label_wins(self):
        assert resolve_gorelay_isp("移动-IPv6", "「Lv1」深港 IEPL「电信联通」") == "cm"

    def test_mobile_entry_fallback(self):
        assert resolve_gorelay_isp("IPv4", "「Lv2」广东隧道「移动入口」") == "cm"

    def test_telecom_entry_fallback(self):
        assert resolve_gorelay_isp("IPv4", "「Lv2」沪日 IPLC「电信入口」") == "ct"

    def test_unicom_entry_fallback(self):
        assert resolve_gorelay_isp("IPv6", "「Lv2」沪日 IPLC「联通入口」") == "cu"

    def test_multi_isp_entry_stays_other(self):
        assert resolve_gorelay_isp("IPv4", "「Lv1」广东隧道「电信联通」") == "other"
        assert resolve_gorelay_isp("IPv4", "「Lv3」广港 IEPL「三线入口」") == "other"
