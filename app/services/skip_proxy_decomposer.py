"""Intent-level decomposition of skip-proxy patterns for Mihomo.

Surge/Shadowrocket skip-proxy accepts domains, CIDRs, and IPs in a flat list.
Mihomo has no skip-proxy field; the same intent must be split across:
  - rules  (DOMAIN-SUFFIX → DIRECT, for each domain)
  - tun.route-exclude-address  (CIDRs/IPs)
  - dns.fake-ip-filter  (domains, +.domain format) only when fake-ip mode is enabled
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field

PatternKind = str  # "domain" | "cidr" | "ip" | "unrecognized"


def classify_skip_proxy_pattern(pattern: str) -> PatternKind:
    """Classify a single skip-proxy entry.

    Returns one of: "domain", "cidr", "ip", "unrecognized".
    """
    pattern = pattern.strip()
    if not pattern:
        return "unrecognized"

    # CIDR notation: 10.0.0.0/8, 192.168.0.0/16, fd00::/8
    if "/" in pattern:
        try:
            ipaddress.ip_network(pattern, strict=False)
            return "cidr"
        except ValueError:
            pass

    # Bare IP address: 127.0.0.1, ::1, 192.168.1.1
    try:
        ipaddress.ip_address(pattern)
        return "ip"
    except ValueError:
        pass

    # Domain-like: example.com, *.local, .example.com, +.example.com
    if re.match(r"^[\w.*+-]+(\.\w+)+$", pattern) or pattern.startswith("."):
        return "domain"

    # Wildcard-only patterns like *.local
    if re.match(r"^\*\.\w+$", pattern):
        return "domain"

    # Single-label hosts like localhost, printer, nas
    if re.match(r"^[A-Za-z0-9_-]+$", pattern):
        return "domain"

    return "unrecognized"


def _normalize_domain(pattern: str) -> str:
    """Strip leading wildcard/dot prefixes to get the base domain.

    e.g. *.local → local, .example.com → example.com, +.foo.com → foo.com
    """
    p = pattern.strip()
    if p.startswith("*."):
        p = p[2:]
    elif p.startswith("+."):
        p = p[2:]
    elif p.startswith("."):
        p = p[1:]
    return p


@dataclass
class SkipProxyDecomposition:
    """Result of decomposing skip-proxy patterns for Mihomo."""

    # Canonical domain / host intent kept in Surge / Shadowrocket skip-proxy.
    direct_intent_patterns: list[str] = field(default_factory=list)

    # Entries for dns.fake-ip-filter, in +.domain format
    fake_ip_filter_entries: list[str] = field(default_factory=list)

    # Entries for tun.route-exclude-address
    route_exclude_entries: list[str] = field(default_factory=list)

    # DIRECT rules: DOMAIN-SUFFIX,domain,DIRECT
    direct_rules: list[str] = field(default_factory=list)

    # Patterns that could not be classified
    warnings: list[str] = field(default_factory=list)


def decompose_skip_proxy(patterns: list[str]) -> SkipProxyDecomposition:
    """Decompose a list of skip-proxy patterns for Mihomo rendering.

    Domains → DIRECT rules, plus fake-ip-filter candidates for fake-ip mode
    CIDRs → tun.route-exclude-address entries
    IPs → tun.route-exclude-address entries (as /32 or /128)
    Unrecognized → warnings
    """
    result = SkipProxyDecomposition()
    seen_direct_patterns: set[str] = set()
    seen_domains: set[str] = set()
    seen_cidrs: set[str] = set()

    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            continue
        kind = classify_skip_proxy_pattern(pattern)

        if kind == "domain":
            if pattern not in seen_direct_patterns:
                seen_direct_patterns.add(pattern)
                result.direct_intent_patterns.append(pattern)
            base = _normalize_domain(pattern)
            if base and base not in seen_domains:
                seen_domains.add(base)
                result.fake_ip_filter_entries.append(f"+.{base}")
                result.direct_rules.append(f"DOMAIN-SUFFIX,{base},DIRECT")

        elif kind == "cidr":
            normalized = str(ipaddress.ip_network(pattern, strict=False))
            if normalized not in seen_cidrs:
                seen_cidrs.add(normalized)
                result.route_exclude_entries.append(normalized)

        elif kind == "ip":
            addr = ipaddress.ip_address(pattern)
            if isinstance(addr, ipaddress.IPv4Address):
                cidr = f"{addr}/32"
            else:
                cidr = f"{addr}/128"
            if cidr not in seen_cidrs:
                seen_cidrs.add(cidr)
                result.route_exclude_entries.append(cidr)

        else:
            result.warnings.append(pattern)

    return result
