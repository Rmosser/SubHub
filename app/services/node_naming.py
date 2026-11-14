from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models import MULTIPLIER_THRESHOLD, QUALITY_HIGH_PREMIUM, QUALITY_HIGH_STANDARD
from app.services.normalize import normalize_entry_name, normalize_isp

_CARRIER_NAMES = {
    "ct": "电信",
    "cu": "联通",
    "cm": "移动",
    "other": "双线",
}
_STANDARD_SOURCE_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")
_HIGH_QUALITY_AIRPORT_MULTIPLIER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX](?![A-Za-z0-9])")
_HIGH_QUALITY_GROUPS = {QUALITY_HIGH_PREMIUM, QUALITY_HIGH_STANDARD}
_US_MARKER_RE = re.compile(r"(?:🇺🇸|美国|美國|\bUS\b|\bUSA\b|\bUnited States\b)", re.I)
_US_NODE_PREFIX = "🇺🇸 美国 · "


def _normalize_multiplier(raw: str) -> str:
    text = str(raw or "").strip().lower().replace("x", "")
    if not text:
        return "?"
    try:
        value = Decimal(text)
    except InvalidOperation:
        return "?"
    if value <= 0:
        return "?"
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "?"


def resolve_multiplier(entry_name: str, line_name: str = "", raw: dict[str, Any] | None = None) -> str:
    payload = raw or {}
    for candidate in (
        payload.get("multiplier"),
        payload.get("rate"),
        payload.get("x"),
        entry_name,
        line_name,
    ):
        text = str(candidate or "")
        for token in text.replace("：", ":").split():
            if token.lower().endswith("x"):
                parsed = _normalize_multiplier(token)
                if parsed != "?":
                    return parsed
        if "倍率" in text:
            parts = text.split("倍率")
            if len(parts) > 1:
                parsed = _normalize_multiplier(parts[-1])
                if parsed != "?":
                    return parsed
    return "?"


def resolve_quality_group(multiplier: str) -> str:
    if multiplier == "?":
        return QUALITY_HIGH_STANDARD
    try:
        value = float(multiplier)
    except ValueError:
        return QUALITY_HIGH_STANDARD
    if value >= MULTIPLIER_THRESHOLD:
        return QUALITY_HIGH_PREMIUM
    return QUALITY_HIGH_STANDARD


def extract_high_quality_airport_multiplier(
    node_name: str,
    raw: dict[str, Any] | None = None,
) -> str | None:
    candidates: list[str] = []
    payload = raw or {}
    raw_name = str(payload.get("name") or "").strip()
    if raw_name:
        candidates.append(raw_name)

    normalized_name = _STANDARD_SOURCE_PREFIX_RE.sub("", str(node_name or "").strip())
    if normalized_name:
        candidates.append(normalized_name)

    for text in candidates:
        for match in _HIGH_QUALITY_AIRPORT_MULTIPLIER_RE.finditer(text):
            parsed = _normalize_multiplier(match.group(1))
            if parsed != "?":
                return parsed
    return None


def format_gorelay_node_name(
    *,
    entry_name: str,
    isp: str,
    multiplier: str,
) -> str:
    carrier = _CARRIER_NAMES.get(normalize_isp(isp), _CARRIER_NAMES["other"])
    route = normalize_entry_name(entry_name) or "线路"
    return f"{carrier} · {multiplier}x · {route}"


def format_standard_node_name(source_name: str, node_name: str) -> str:
    prefix = str(source_name or "").strip() or "标准源"
    name = str(node_name or "").strip() or "Unnamed"
    return f"[{prefix}] {name}"


def decorate_high_quality_node_name(node_name: str, quality_group: str) -> str:
    full_name = str(node_name or "").strip() or "Unnamed"
    if quality_group not in _HIGH_QUALITY_GROUPS:
        return full_name

    prefix = ""
    visible_name = full_name
    match = _STANDARD_SOURCE_PREFIX_RE.match(full_name)
    if match:
        prefix = match.group(0)
        visible_name = full_name[match.end() :].strip() or "Unnamed"

    if _US_MARKER_RE.search(visible_name):
        return f"{prefix}{visible_name}".strip()
    return f"{prefix}{_US_NODE_PREFIX}{visible_name}".strip()
