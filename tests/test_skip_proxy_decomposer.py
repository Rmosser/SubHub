from __future__ import annotations

import pytest

from app.services.skip_proxy_decomposer import (
    classify_skip_proxy_pattern,
    decompose_skip_proxy,
)


class TestClassifyPattern:
    def test_plain_domain(self) -> None:
        assert classify_skip_proxy_pattern("example.com") == "domain"

    def test_wildcard_domain(self) -> None:
        assert classify_skip_proxy_pattern("*.local") == "domain"

    def test_dot_prefix_domain(self) -> None:
        assert classify_skip_proxy_pattern(".example.com") == "domain"

    def test_plus_dot_domain(self) -> None:
        assert classify_skip_proxy_pattern("+.example.com") == "domain"

    def test_subdomain(self) -> None:
        assert classify_skip_proxy_pattern("api.example.com") == "domain"

    def test_ipv4_cidr(self) -> None:
        assert classify_skip_proxy_pattern("10.0.0.0/8") == "cidr"

    def test_ipv6_cidr(self) -> None:
        assert classify_skip_proxy_pattern("fd00::/8") == "cidr"

    def test_ipv4_address(self) -> None:
        assert classify_skip_proxy_pattern("127.0.0.1") == "ip"

    def test_ipv6_address(self) -> None:
        assert classify_skip_proxy_pattern("::1") == "ip"

    def test_empty_string(self) -> None:
        assert classify_skip_proxy_pattern("") == "unrecognized"

    def test_whitespace_only(self) -> None:
        assert classify_skip_proxy_pattern("   ") == "unrecognized"

    def test_ipv4_private_cidr(self) -> None:
        assert classify_skip_proxy_pattern("192.168.0.0/16") == "cidr"

    def test_ipv4_single_host_cidr(self) -> None:
        assert classify_skip_proxy_pattern("192.168.1.1/32") == "cidr"


class TestDecomposeSkipProxy:
    def test_empty_list(self) -> None:
        result = decompose_skip_proxy([])
        assert result.fake_ip_filter_entries == []
        assert result.route_exclude_entries == []
        assert result.direct_rules == []
        assert result.warnings == []

    def test_domain_only(self) -> None:
        result = decompose_skip_proxy(["example.com"])
        assert result.fake_ip_filter_entries == ["+.example.com"]
        assert result.direct_rules == ["DOMAIN-SUFFIX,example.com,DIRECT"]
        assert result.route_exclude_entries == []
        assert result.warnings == []

    def test_wildcard_domain_normalized(self) -> None:
        result = decompose_skip_proxy(["*.local"])
        assert result.fake_ip_filter_entries == ["+.local"]
        assert result.direct_rules == ["DOMAIN-SUFFIX,local,DIRECT"]

    def test_cidr_only(self) -> None:
        result = decompose_skip_proxy(["10.0.0.0/8"])
        assert result.route_exclude_entries == ["10.0.0.0/8"]
        assert result.fake_ip_filter_entries == []
        assert result.direct_rules == []

    def test_ip_becomes_host_cidr(self) -> None:
        result = decompose_skip_proxy(["127.0.0.1"])
        assert result.route_exclude_entries == ["127.0.0.1/32"]

    def test_ipv6_becomes_host_cidr(self) -> None:
        result = decompose_skip_proxy(["::1"])
        assert result.route_exclude_entries == ["::1/128"]

    def test_mixed_patterns(self) -> None:
        result = decompose_skip_proxy([
            "example.com",
            "10.0.0.0/8",
            "*.local",
        ])
        assert "+.example.com" in result.fake_ip_filter_entries
        assert "+.local" in result.fake_ip_filter_entries
        assert "10.0.0.0/8" in result.route_exclude_entries
        assert "DOMAIN-SUFFIX,example.com,DIRECT" in result.direct_rules
        assert "DOMAIN-SUFFIX,local,DIRECT" in result.direct_rules
        assert result.warnings == []

    def test_dedup_domains(self) -> None:
        result = decompose_skip_proxy(["example.com", "*.example.com"])
        assert result.fake_ip_filter_entries == ["+.example.com"]
        assert len(result.direct_rules) == 1

    def test_dedup_cidrs(self) -> None:
        result = decompose_skip_proxy(["10.0.0.0/8", "10.0.0.0/8"])
        assert result.route_exclude_entries == ["10.0.0.0/8"]

    def test_empty_and_whitespace_entries_skipped(self) -> None:
        result = decompose_skip_proxy(["", "  ", "example.com"])
        assert result.fake_ip_filter_entries == ["+.example.com"]
        assert result.warnings == []

    def test_full_integration_scenario(self) -> None:
        """Mimics the verification plan: example.com, 10.0.0.0/8, *.local."""
        result = decompose_skip_proxy(["example.com", "10.0.0.0/8", "*.local"])

        assert "+.example.com" in result.fake_ip_filter_entries
        assert "+.local" in result.fake_ip_filter_entries
        assert "10.0.0.0/8" in result.route_exclude_entries
        assert "DOMAIN-SUFFIX,example.com,DIRECT" in result.direct_rules
        assert "DOMAIN-SUFFIX,local,DIRECT" in result.direct_rules
        assert result.warnings == []
