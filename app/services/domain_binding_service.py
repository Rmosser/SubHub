from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.models import GoRelayDomainBinding
from app.services.normalize import (
    infer_ip_version_from_host,
    normalize_entry_key,
    normalize_entry_name,
    normalize_ip_version,
    normalize_isp,
    resolve_gorelay_isp,
)

_BRACKET_LINE = re.compile(r"^【\s*([^】]+)\s*】\s*(.+?)\s*$")
_IPV6_HOST_PORT = re.compile(r"^\[([0-9a-fA-F:]+)\](?::\d+)?$")
_HOST_PORT = re.compile(r"^([A-Za-z0-9._-]+)(?::\d+)?$")
_ENTRY_PREFIX_RE = re.compile(r"^\s*(?:[-*•·]\s*|\d+[.)、]\s*|入口\s*[:：]\s*)+")
_MULTIPLIER_LABEL_RE = re.compile(r"倍率\s*[:：]?\s*(\d+(?:\.\d+)?)", re.I)
_MULTIPLIER_X_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\b")
_QUOTE_CHARS = '"\'“”‘’`'
_PLACEHOLDER_TEXTS = (
    "联系客服申请",
    "通报暂无",
    "暂无 ip",
    "暂无ip",
    "待申请",
)


@dataclass
class ParsedBinding:
    entry_name: str
    isp: str
    ip_version: str
    host_value: str


def _strip_edge_quotes(value: str) -> str:
    text = str(value or "").strip()
    while text and text[0] in _QUOTE_CHARS:
        text = text[1:].lstrip()
    while text and text[-1] in _QUOTE_CHARS:
        text = text[:-1].rstrip()
    return text.strip()


def _looks_like_placeholder(raw: str) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return True
    return any(token in text for token in _PLACEHOLDER_TEXTS)


def parse_host_value(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if _looks_like_placeholder(text):
        return None
    match_v6 = _IPV6_HOST_PORT.match(text)
    if match_v6:
        return match_v6.group(1)
    match_host = _HOST_PORT.match(text)
    if match_host:
        return match_host.group(1)
    token_match = re.search(r"\[?[0-9a-fA-F:.]+\]?|[A-Za-z0-9._-]+", text)
    if not token_match:
        return None
    token = token_match.group(0).strip("[]")
    return token or None


def _normalize_multiplier(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or None


def parse_entry_multiplier_hints(text: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = _strip_edge_quotes(raw_line)
        if not line:
            continue
        cleaned = _ENTRY_PREFIX_RE.sub("", line).strip()
        cleaned = _strip_edge_quotes(cleaned)
        if not cleaned:
            continue

        match = _MULTIPLIER_LABEL_RE.search(cleaned)
        if not match:
            match = _MULTIPLIER_X_RE.search(cleaned)
        if not match:
            continue

        multiplier = _normalize_multiplier(match.group(1))
        if not multiplier:
            continue

        entry_part = cleaned[: match.start()].strip(" ：:;-")
        entry_part = _strip_edge_quotes(entry_part)
        if not entry_part:
            continue
        entry_key = normalize_entry_key(entry_part)
        if not entry_key:
            continue
        output[entry_key] = multiplier
    return output


def parse_customer_reply(text: str) -> list[ParsedBinding]:
    current_entry = ""
    output: list[ParsedBinding] = []

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("申请开通") or line.startswith("官网账号") or line.startswith("用途场景"):
            continue
        if line.startswith("宽带类型") or line.startswith("所在城市"):
            continue
        if "所需线路" in line:
            continue

        if line.startswith("「") and "」" in line:
            current_entry = normalize_entry_name(line)
            continue

        bracket = _BRACKET_LINE.match(line)
        if not bracket:
            continue

        label = bracket.group(1)
        host_raw = bracket.group(2)
        host = parse_host_value(host_raw)
        if not host or not current_entry:
            continue

        ip_version = normalize_ip_version(label)
        if ip_version == "unknown":
            ip_version = infer_ip_version_from_host(host)
        isp = resolve_gorelay_isp(label, current_entry)

        output.append(
            ParsedBinding(
                entry_name=current_entry,
                isp=isp,
                ip_version=ip_version,
                host_value=host,
            )
        )

    return output


def binding_key(account_id: str, entry_name: str, isp: str, ip_version: str) -> str:
    return (
        f"{account_id}|{normalize_entry_key(entry_name)}|{normalize_isp(isp)}|{normalize_ip_version(ip_version)}"
    ).lower()


def build_binding_index(bindings: list[GoRelayDomainBinding]) -> dict[str, GoRelayDomainBinding]:
    output: dict[str, GoRelayDomainBinding] = {}
    for item in bindings:
        output[binding_key(item.account_id, item.entry_name, item.isp, item.ip_version)] = item
    return output
