from __future__ import annotations

import re

from app.models import CollectedRule
from app.services.normalize import (
    infer_ip_version_from_host,
    normalize_entry_name,
    normalize_ip_version,
    resolve_gorelay_isp,
)

_PORT_RE = re.compile(r"(?:端口|port)\s*[:：]\s*(\d{2,5})", re.I)
_LABEL_VALUE_RE = re.compile(r"^【\s*([^】]+?)\s*】\s*(.+?)\s*$")
_HOST_PORT_RE = re.compile(r"^\s*(\[[0-9a-fA-F:]+\]|[A-Za-z0-9._-]+):(\d{2,5})\s*$")
_BRACKET_IPV6_RE = re.compile(r"^\s*\[([0-9a-fA-F:]+)\]\s*$")
_HOST_ONLY_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*$")
_CONTACT_RE = re.compile(r"联系客服申请\s*[:：]\s*(\d{2,5})")
_PLACEHOLDER_TEXTS = (
    "联系客服申请",
    "通报暂无",
    "暂无 ip",
    "暂无ip",
    "待申请",
)


def _clean_host(raw: str) -> str:
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        return text[1:-1]
    return text


def _safe_port(raw: str | int | None, fallback: int = 0) -> int:
    if raw is None:
        return fallback
    try:
        value = int(str(raw).strip())
    except ValueError:
        return fallback
    if value <= 0 or value > 65535:
        return fallback
    return value


def _looks_like_placeholder(raw: str) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return True
    return any(token in text for token in _PLACEHOLDER_TEXTS)


def _parse_host_port(raw: str) -> tuple[str, int] | None:
    match = _HOST_PORT_RE.match(str(raw or "").strip())
    if not match:
        return None
    host = _clean_host(match.group(1))
    port = _safe_port(match.group(2))
    if not host or not port:
        return None
    return host, port


def _parse_host_only(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text or _looks_like_placeholder(text):
        return None
    match_v6 = _BRACKET_IPV6_RE.match(text)
    if match_v6:
        return match_v6.group(1).strip()
    match_host = _HOST_ONLY_RE.match(text)
    if match_host:
        return match_host.group(1).strip()
    return None


def parse_detail_text_to_rules(
    *,
    account_id: str,
    rule_id: str,
    line_name: str,
    device_name: str,
    entry_name: str,
    detail_text: str,
) -> list[CollectedRule]:
    default_port = 0
    output: list[CollectedRule] = []
    normalized_entry = normalize_entry_name(entry_name or line_name)

    for match in _PORT_RE.finditer(detail_text):
        port = _safe_port(match.group(1))
        if port:
            default_port = port
            break

    for raw_line in detail_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        label_match = _LABEL_VALUE_RE.match(line)
        if label_match:
            label = label_match.group(1).strip()
            value = label_match.group(2).strip()
            label_isp = resolve_gorelay_isp(label, normalized_entry)
            label_ip = normalize_ip_version(label)
            raw_meta = {"line": line, "label": label, "value": value}

            contact = _CONTACT_RE.search(value)
            if contact or _looks_like_placeholder(value):
                pending_port = _safe_port(contact.group(1), default_port) if contact else default_port
                if pending_port:
                    output.append(
                        CollectedRule(
                            account_id=account_id,
                            rule_id=rule_id,
                            device_name=device_name,
                            line_name=line_name,
                            entry_name=normalized_entry,
                            isp=label_isp,
                            ip_version=(label_ip if label_ip != "unknown" else "ipv4"),
                            port=pending_port,
                            host="",
                            status="pending_domain",
                            raw=raw_meta,
                        )
                    )
                continue

            parsed = _parse_host_port(value)
            if parsed:
                host, port = parsed
                ip_version = label_ip if label_ip != "unknown" else infer_ip_version_from_host(host)
                output.append(
                    CollectedRule(
                        account_id=account_id,
                        rule_id=rule_id,
                        device_name=device_name,
                        line_name=line_name,
                        entry_name=normalized_entry,
                        isp=label_isp,
                        ip_version=ip_version,
                        port=port,
                        host=host,
                        status="ready",
                        raw=raw_meta,
                    )
                )
                continue

            # Value might be host only; use default port.
            host = _parse_host_only(value)
            if host and default_port:
                ip_version = label_ip if label_ip != "unknown" else infer_ip_version_from_host(host)
                output.append(
                    CollectedRule(
                        account_id=account_id,
                        rule_id=rule_id,
                        device_name=device_name,
                        line_name=line_name,
                        entry_name=normalized_entry,
                        isp=label_isp,
                        ip_version=ip_version,
                        port=default_port,
                        host=host,
                        status="ready",
                        raw=raw_meta,
                    )
                )
                continue

            if default_port:
                output.append(
                    CollectedRule(
                        account_id=account_id,
                        rule_id=rule_id,
                        device_name=device_name,
                        line_name=line_name,
                        entry_name=normalized_entry,
                        isp=label_isp,
                        ip_version=(label_ip if label_ip != "unknown" else "ipv4"),
                        port=default_port,
                        host="",
                        status="pending_domain",
                        raw=raw_meta,
                    )
                )
            continue

        # Fallback for plain host:port lines.
        contact = _CONTACT_RE.search(line)
        if contact or _looks_like_placeholder(line):
            pending_port = _safe_port(contact.group(1), default_port) if contact else default_port
            if pending_port:
                output.append(
                    CollectedRule(
                        account_id=account_id,
                        rule_id=rule_id,
                        device_name=device_name,
                        line_name=line_name,
                        entry_name=normalized_entry,
                        isp=resolve_gorelay_isp("other", normalized_entry),
                        ip_version="ipv4",
                        port=pending_port,
                        host="",
                        status="pending_domain",
                        raw={"line": line},
                    )
                )
            continue

        parsed = _parse_host_port(line)
        if parsed:
            host, port = parsed
            output.append(
                CollectedRule(
                    account_id=account_id,
                    rule_id=rule_id,
                    device_name=device_name,
                    line_name=line_name,
                    entry_name=normalized_entry,
                    isp=resolve_gorelay_isp("other", normalized_entry),
                    ip_version=infer_ip_version_from_host(host),
                    port=port,
                    host=host,
                    status="ready",
                    raw={"line": line},
                )
            )
            continue

        host = _parse_host_only(line)
        if host and default_port:
            output.append(
                CollectedRule(
                    account_id=account_id,
                    rule_id=rule_id,
                    device_name=device_name,
                    line_name=line_name,
                    entry_name=normalized_entry,
                    isp=resolve_gorelay_isp("other", normalized_entry),
                    ip_version=infer_ip_version_from_host(host),
                    port=default_port,
                    host=host,
                    status="ready",
                    raw={"line": line},
                )
            )

    return output
