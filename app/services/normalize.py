"""Pure normalization utilities extracted from the former domain_binding_service.py."""
from __future__ import annotations

import re

_ENTRY_MULTIPLIER_TRAILER = re.compile(
    r"\s*倍率\s*[:：]?\s*\d+(?:\.\d+)?(?:[xX])?\s*$", re.I
)
_ENTRY_X_TRAILER = re.compile(r"\s+\d+(?:\.\d+)?\s*[xX]\s*$")
_GORELAY_SINGLE_ISP_ENTRY_HINTS = (
    ("移动入口", "cm"),
    ("电信入口", "ct"),
    ("联通入口", "cu"),
)
_GORELAY_MULTI_ISP_ENTRY_HINTS = ("电信联通", "三线入口")


def normalize_entry_name(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_entry_key(value: str) -> str:
    text = normalize_entry_name(value)
    if not text:
        return ""
    text = _ENTRY_MULTIPLIER_TRAILER.sub("", text).strip()
    text = _ENTRY_X_TRAILER.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_isp(value: str) -> str:
    text = str(value or "").strip().lower()
    if any(token in text for token in ("电信", "telecom", "ct")):
        return "ct"
    if any(token in text for token in ("联通", "unicom", "cu")):
        return "cu"
    if any(token in text for token in ("移动", "mobile", "cm")):
        return "cm"
    return "other"


def resolve_gorelay_isp(value: str, entry_name: str) -> str:
    normalized = normalize_isp(value)
    if normalized != "other":
        return normalized

    entry = normalize_entry_name(entry_name)
    if not entry:
        return "other"

    for token, isp in _GORELAY_SINGLE_ISP_ENTRY_HINTS:
        if token in entry:
            return isp

    if any(token in entry for token in _GORELAY_MULTI_ISP_ENTRY_HINTS):
        return "other"

    return "other"


def normalize_ip_version(value: str) -> str:
    text = str(value or "").strip().lower()
    if "6" in text:
        return "ipv6"
    if "4" in text:
        return "ipv4"
    return "unknown"


def infer_ip_version_from_host(host_value: str) -> str:
    host = str(host_value or "").strip()
    if ":" in host and "." not in host:
        return "ipv6"
    if host:
        return "ipv4"
    return "unknown"
