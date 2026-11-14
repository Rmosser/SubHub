from __future__ import annotations

import base64
import binascii
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from inspect import signature
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import yaml

from app.config import Settings
from app.models import (
    DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    STANDARD_SOURCE_PULL_NETWORK_MODES,
    STANDARD_SOURCE_PULL_NETWORK_PROXY_THEN_DIRECT,
    NodeRecord,
    StandardSource,
    StandardSourceWarning,
)
from app.services.http_client import build_async_http_client
from app.services.node_naming import format_standard_node_name
from app.services.source_diagnostics import (
    KnownSecrets,
    known_source_secrets,
    public_source_status,
    redact_source_url,
    public_pull_reasons,
    sanitize_source_error,
    summarize_pull_errors,
    unsupported_protocol_reason,
)

_SR_PROXY_LINE = re.compile(r"^\s*([^#][^=]+?)\s*=\s*([a-zA-Z0-9_-]+)\s*,\s*(.+)$")
_SURGE_PROXY_LINE = re.compile(r"^\s*([^#][^=]+?)\s*=\s*([a-zA-Z0-9_-]+)\s*,\s*(.+)$")

_CLASH_USER_AGENTS = (
    "ClashforWindows/0.20.39",
    "clash-verge/2.0",
    "mihomo/1.19.0",
)
_METHOD_USER_AGENTS = {
    "clash": _CLASH_USER_AGENTS[0],
    "surge": "Surge iOS/3867 SurgeCore/6010000",
    "shadowrocket": "Shadowrocket/3488 CFNetwork/3896.200.61 Darwin/27.2.0 iPhone18,1",
}

_PROTOCOL_ALIASES = {
    "socks": "socks5",
    "hy2": "hysteria2",
    "hysteria": "hysteria2",
}

_SUPPORTED_PROTOCOLS = {
    "http",
    "https",
    "socks5",
    "ss",
    "trojan",
    "vmess",
    "vless",
    "anytls",
    "hysteria2",
    "tuic",
    "wireguard",
}

_CANONICAL_RAW_KEYS = (
    "password",
    "uuid",
    "token",
    "tuic_version",
    "sni",
    "alpn",
    "insecure",
    "client_fingerprint",
    "flow",
    "packet_encoding",
    "reality_opts",
    "plugin",
    "plugin-opts",
    "obfs",
    "obfs_password",
    "congestion_controller",
    "udp_relay_mode",
    "reduce_rtt",
)

_TECHNICAL_NODE_REASON = "filtered technical node"
_TECHNICAL_KEYWORDS_EN = (
    "traffic",
    "flow",
    "quota",
    "remaining",
    "used",
    "expire",
    "reset",
    "urltest",
    "speedtest",
)
_TECHNICAL_KEYWORDS_ZH = (
    "流量",
    "剩余",
    "到期",
    "套餐",
    "订阅信息",
    "测速",
    "公告",
    "客服",
    "官网",
    "重置",
)
_TECHNICAL_DATE_KEYWORDS_EN = ("expire", "reset")
_TECHNICAL_DATE_KEYWORDS_ZH = ("到期", "重置")
_TRAFFIC_UNIT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:kb|mb|gb|tb|pb)\b", re.I)
_TRAFFIC_QUOTA_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:kb|mb|gb|tb|pb)\s*[/|｜]\s*\d+(?:\.\d+)?\s*(?:kb|mb|gb|tb|pb)\b",
    re.I,
)
_TECHNICAL_DATE_RE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b")
_TECHNICAL_STATUS_RE = re.compile(r"^\s*status\s*[:=]", re.I)
_TECHNICAL_FIELD_ASSIGN_RE = re.compile(r"[:：=]\s*\S")
_URLTEST_MARKER_RE = re.compile(r"(?:^|\W)urltest(?:\W|$)", re.I)
_SEMANTIC_WARNING_CODES = {
    "clash": "standard-source-clash-url-format-mismatch",
    "shadowrocket": "standard-source-shadowrocket-url-format-mismatch",
    "surge": "standard-source-surge-url-format-mismatch",
}
_SEMANTIC_WARNING_FIELDS = {
    "clash": "clash_url",
    "shadowrocket": "shadowrocket_url",
    "surge": "surge_url",
}
_SEMANTIC_NATIVE_VARIANTS = {
    "clash": {"format:clash-yaml"},
    "shadowrocket": {"format:ini", "format:uri-plain", "format:base64-uri"},
    "surge": {"format:ini"},
}
_SEMANTIC_DEFAULT_VARIANTS = {
    "clash": "format:clash-yaml",
    "shadowrocket": "format:ini",
    "surge": "format:ini",
}


@dataclass
class SourcePullAttempt:
    method: str
    ok: bool
    node_count: int
    error: str = ""
    url: str = ""
    network_path: str = ""
    request_variant: str = ""
    parsed_protocol_counts: dict[str, int] = field(default_factory=dict)
    skip_reasons: list[str] = field(default_factory=list)
    # Stable reason code and the failure in plain words, without the
    # "(method, url)" trailer that `error` carries for the summary text.
    code: str = ""
    message: str = ""

    def to_dict(self, known_secrets: KnownSecrets = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "method": self.method,
            "ok": self.ok,
            "node_count": int(self.node_count),
            "error": self.error,
            "url": self.url,
            "network_path": self.network_path,
        }
        if self.request_variant:
            payload["request_variant"] = self.request_variant
        if self.parsed_protocol_counts:
            payload["parsed_protocol_counts"] = {
                key: int(value)
                for key, value in sorted(self.parsed_protocol_counts.items())
                if int(value) > 0
            }
        if self.skip_reasons:
            payload["skip_reasons"] = list(self.skip_reasons)
        return public_source_status(payload, known_secrets)


@dataclass
class SourcePullResult:
    ok: bool
    method: str = ""
    node_count: int = 0
    nodes: list[NodeRecord] = field(default_factory=list)
    attempts: list[SourcePullAttempt] = field(default_factory=list)
    error: str = ""
    warnings: list[StandardSourceWarning] = field(default_factory=list)
    filtered_technical_count: int = 0
    filtered_technical_examples: list[str] = field(default_factory=list)

    def to_dict(self, *, include_nodes: bool = False, known_secrets: KnownSecrets = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "method": self.method,
            "node_count": int(self.node_count),
            "attempts": [item.to_dict(known_secrets) for item in self.attempts],
            "error": summarize_pull_errors(self.error, known_secrets) if self.error else "",
            "warning_count": len(self.warnings),
            "warnings": [item.to_dict() for item in self.warnings],
            "filtered_technical_count": int(self.filtered_technical_count),
            "filtered_technical_examples": list(self.filtered_technical_examples),
        }
        payload = public_source_status(payload, known_secrets)
        if include_nodes:
            payload["nodes"] = [item.to_dict() for item in self.nodes]
        return payload

    def failure_reasons(self, known_secrets: KnownSecrets = None) -> list[dict[str, str]]:
        """One public reason per distinct failed attempt; empty when the pull succeeded."""
        if self.ok:
            return []
        reasons = public_pull_reasons([
            {"method": item.method, "code": item.code, "url": item.url, "message": item.message or item.error}
            for item in self.attempts
            if not item.ok and item.error
        ], known_secrets)
        if reasons:
            return reasons
        return [{
            "method": "",
            "code": "unclassified" if self.error else "all_methods_failed",
            "url": "",
            "message": summarize_pull_errors(self.error, known_secrets),
        }]


@dataclass
class ParsePayload:
    nodes: list[NodeRecord] = field(default_factory=list)
    parsed_protocol_counts: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)
    filtered_technical_count: int = 0
    filtered_technical_examples: list[str] = field(default_factory=list)

    def skip_reasons(self) -> list[str]:
        if not self.reason_counts:
            return []
        items = sorted(self.reason_counts.items(), key=lambda item: (-item[1], item[0]))
        return [f"{reason} x{count}" if count > 1 else reason for reason, count in items]


@dataclass
class FetchPayload:
    nodes: list[NodeRecord] = field(default_factory=list)
    request_variant: str = ""
    parsed_protocol_counts: dict[str, int] = field(default_factory=dict)
    skip_reasons: list[str] = field(default_factory=list)
    attempts: list[SourcePullAttempt] = field(default_factory=list)
    filtered_technical_count: int = 0
    filtered_technical_examples: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self):
        return iter(self.nodes)


@dataclass
class _VariantFetchResult:
    request_variant: str
    nodes: list[NodeRecord] = field(default_factory=list)
    parsed_protocol_counts: dict[str, int] = field(default_factory=dict)
    skip_reasons: list[str] = field(default_factory=list)
    error: str = ""
    filtered_technical_count: int = 0
    filtered_technical_examples: list[str] = field(default_factory=list)
    code: str = ""


class SourceFetcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse_manual_nodes(self, source: StandardSource) -> SourcePullResult:
        text = str(source.manual_nodes_text or "").strip()
        if not text:
            attempt = SourcePullAttempt(
                method="manual_nodes",
                ok=False,
                node_count=0,
                error="manual_nodes_text is required",
                request_variant="format:uri-plain",
                code="manual_nodes_missing",
            )
            return SourcePullResult(
                ok=False,
                method="manual_nodes",
                node_count=0,
                nodes=[],
                attempts=[attempt],
                error=attempt.error,
            )

        parsed = self._parse_uri_subscription_text(text, source)
        nodes = self._dedupe(parsed.nodes)
        attempt = SourcePullAttempt(
            method="manual_nodes",
            ok=bool(nodes),
            node_count=len(nodes),
            error="" if nodes else self._format_zero_node_error(parsed.skip_reasons()),
            request_variant="format:uri-plain",
            parsed_protocol_counts=parsed.parsed_protocol_counts,
            skip_reasons=parsed.skip_reasons(),
            code="" if nodes else "no_valid_nodes",
        )
        return SourcePullResult(
            ok=bool(nodes),
            method="manual_nodes" if nodes else "",
            node_count=len(nodes),
            nodes=nodes,
            attempts=[attempt],
            error=attempt.error,
            warnings=self._parse_warnings(parsed.skip_reasons(), method="manual_nodes"),
            filtered_technical_count=int(parsed.filtered_technical_count),
            filtered_technical_examples=list(parsed.filtered_technical_examples),
        )

    async def fetch_source(self, source: StandardSource) -> SourcePullResult:
        known_secrets = known_source_secrets([source])
        methods = (
            ("clash", source.clash_url, self._fetch_clash),
            ("surge", source.surge_url, self._fetch_surge),
            ("shadowrocket", source.shadowrocket_url, self._fetch_shadowrocket),
        )
        attempts: list[SourcePullAttempt] = []
        network_paths = self._network_paths_for_mode(source.pull_network_mode)

        for method, raw_url, fetcher in methods:
            url = str(raw_url or "").strip()
            safe_url = redact_source_url(url, known_secrets)
            if not url:
                attempts.append(
                    SourcePullAttempt(
                        method=method,
                        ok=False,
                        node_count=0,
                        error="url not configured",
                        url=safe_url,
                        code="url_not_configured",
                    )
                )
                continue

            for network_path in network_paths:
                trust_env = network_path == "proxy"
                try:
                    fetched = await self._call_fetcher(fetcher, source, trust_env=trust_env)
                    payload = self._coerce_fetch_payload(fetched)
                except Exception as exc:
                    code, message = self._classify_fetch_error(exc, known_secrets)
                    attempts.append(
                        SourcePullAttempt(
                            method=method,
                            ok=False,
                            node_count=0,
                            error=self._sanitize_fetch_error(method, safe_url, exc, known_secrets),
                            url=safe_url,
                            network_path=network_path,
                            code=code,
                            message=message,
                        )
                    )
                    continue

                contextual_attempts = self._contextualize_attempts(
                    payload.attempts,
                    method=method,
                    safe_url=safe_url,
                    network_path=network_path,
                    known_secrets=known_secrets,
                )
                if contextual_attempts:
                    attempts.extend(contextual_attempts)
                else:
                    attempts.append(
                        SourcePullAttempt(
                            method=method,
                            ok=bool(payload.nodes),
                            node_count=len(payload.nodes),
                            error=(
                                ""
                                if payload.nodes
                                else sanitize_source_error(self._format_zero_node_error(payload.skip_reasons), known_secrets)
                            ),
                            url=safe_url,
                            network_path=network_path,
                            request_variant=payload.request_variant,
                            parsed_protocol_counts=payload.parsed_protocol_counts,
                            skip_reasons=[sanitize_source_error(reason, known_secrets) for reason in payload.skip_reasons],
                            code="" if payload.nodes else "no_valid_nodes",
                        )
                    )

                nodes = self._dedupe(payload.nodes)
                if nodes:
                    return SourcePullResult(
                        ok=True,
                        method=method,
                        node_count=len(nodes),
                        nodes=nodes,
                        attempts=attempts,
                        error="",
                        warnings=self._semantic_warnings_for_success(
                            method=method,
                            request_variant=payload.request_variant,
                        ) + self._parse_warnings(payload.skip_reasons, method=method),
                        filtered_technical_count=int(payload.filtered_technical_count),
                        filtered_technical_examples=list(payload.filtered_technical_examples),
                    )

        error = summarize_pull_errors("; ".join(
            f"{item.method}: {item.error}" for item in attempts if not item.ok and item.error
        ), known_secrets)
        return SourcePullResult(
            ok=False,
            method="",
            node_count=0,
            nodes=[],
            attempts=attempts,
            error=error,
            warnings=[],
            filtered_technical_count=0,
            filtered_technical_examples=[],
        )

    @staticmethod
    def _parse_warnings(skip_reasons: list[str], *, method: str) -> list[StandardSourceWarning]:
        if not skip_reasons:
            return []
        # Parser reasons can contain an untrusted protocol label. Do not copy
        # source text or arbitrary labels into the management warning surface.
        reasons = []
        for reason in skip_reasons:
            safe_reason = str(reason)
            if safe_reason.startswith("unsupported protocol "):
                safe_reason = "unsupported protocol"
            if not re.fullmatch(r"[a-z0-9 /_-]{1,80}", safe_reason):
                safe_reason = "invalid subscription entry"
            reasons.append(safe_reason)
        return [StandardSourceWarning(
            code="source-parse-rejected",
            message="Some subscription entries were rejected: " + "; ".join(reasons),
            field="manual_nodes_text" if method == "manual_nodes" else _SEMANTIC_WARNING_FIELDS.get(method, method),
            expected_method=method,
            actual_variant="parse-rejected",
        )]

    @staticmethod
    def _actual_variant_for_request(method: str, request_variant: str) -> str:
        for part in reversed(str(request_variant or "").split("|")):
            value = str(part or "").strip()
            if value.startswith("format:"):
                return value
        return _SEMANTIC_DEFAULT_VARIANTS.get(method, "")

    def _semantic_warnings_for_success(
        self,
        *,
        method: str,
        request_variant: str,
    ) -> list[StandardSourceWarning]:
        actual_variant = self._actual_variant_for_request(method, request_variant)
        expected_variants = _SEMANTIC_NATIVE_VARIANTS.get(method, set())
        if actual_variant in expected_variants:
            return []
        expected_text = ", ".join(sorted(item.removeprefix("format:") for item in expected_variants))
        actual_text = actual_variant.removeprefix("format:") or "unknown"
        return [
            StandardSourceWarning(
                code=_SEMANTIC_WARNING_CODES[method],
                message=(
                    f"{_SEMANTIC_WARNING_FIELDS[method]} parsed as {actual_text}; "
                    f"expected {expected_text}"
                ),
                field=_SEMANTIC_WARNING_FIELDS[method],
                expected_method=method,
                actual_variant=actual_variant,
            )
        ]

    @staticmethod
    def _network_paths_for_mode(mode: str) -> tuple[str, ...]:
        value = str(mode or "").strip()
        if value not in STANDARD_SOURCE_PULL_NETWORK_MODES:
            value = DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE
        if value == STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY:
            return ("direct",)
        if value == STANDARD_SOURCE_PULL_NETWORK_PROXY_THEN_DIRECT:
            return ("proxy", "direct")
        if value == STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY:
            return ("direct", "proxy")
        return ("direct", "proxy")

    @staticmethod
    async def _call_fetcher(fetcher, source: StandardSource, *, trust_env: bool) -> object:
        params = signature(fetcher).parameters
        if "trust_env" in params:
            return await fetcher(source, trust_env=trust_env)
        return await fetcher(source)

    @staticmethod
    def _coerce_fetch_payload(value: object) -> FetchPayload:
        if isinstance(value, FetchPayload):
            return value
        if isinstance(value, list):
            nodes = [item for item in value if isinstance(item, NodeRecord)]
            return FetchPayload(
                nodes=nodes,
                filtered_technical_count=0,
                filtered_technical_examples=[],
            )
        return FetchPayload(nodes=[])

    @staticmethod
    def _contextualize_attempts(
        raw_attempts: list[SourcePullAttempt],
        *,
        method: str,
        safe_url: str,
        network_path: str,
        known_secrets: KnownSecrets = None,
    ) -> list[SourcePullAttempt]:
        output: list[SourcePullAttempt] = []
        for item in raw_attempts:
            copied = SourcePullAttempt(
                method=item.method or method,
                ok=bool(item.ok),
                node_count=int(item.node_count),
                error=sanitize_source_error(item.error, known_secrets),
                url=redact_source_url(item.url or safe_url, known_secrets),
                network_path=item.network_path or network_path,
                request_variant=str(item.request_variant or ""),
                parsed_protocol_counts=dict(item.parsed_protocol_counts or {}),
                skip_reasons=[sanitize_source_error(reason, known_secrets) for reason in (item.skip_reasons or [])],
                code=item.code,
                message=sanitize_source_error(item.message, known_secrets) if item.message else "",
            )
            output.append(copied)
        return output

    @staticmethod
    def _redact_url(raw_url: str) -> str:
        return redact_source_url(raw_url)

    @staticmethod
    def _classify_fetch_error(exc: Exception, known_secrets: KnownSecrets = None) -> tuple[str, str]:
        """The stable reason code and public message for an exception raised by a fetch."""
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code if exc.response else "unknown"
            return "http_status", f"HTTP {status}"
        if isinstance(exc, httpx.TimeoutException):
            return "timeout", "timeout"
        if isinstance(exc, httpx.RequestError):
            return "request_failed", "request failed"
        message = sanitize_source_error(str(exc), known_secrets).strip()
        if isinstance(exc, ValueError):
            return "invalid_payload", message or "invalid payload"
        return "fetch_failed", message or exc.__class__.__name__

    @classmethod
    def _sanitize_fetch_error(
        cls, method: str, safe_url: str, exc: Exception, known_secrets: KnownSecrets = None,
    ) -> str:
        safe_url = redact_source_url(safe_url, known_secrets)
        code, message = cls._classify_fetch_error(exc, known_secrets)
        if code == "invalid_payload":
            return f"{message} ({method})"
        return f"{message} ({method}, {safe_url})"

    @staticmethod
    def _method_headers(method: str, *, user_agent: str = "") -> dict[str, str]:
        ua = str(user_agent or _METHOD_USER_AGENTS.get(method, "")).strip()
        if not ua:
            return {}
        return {"User-Agent": ua}

    @staticmethod
    def _normalize_protocol(proto: str) -> str:
        text = str(proto or "").strip().lower()
        return _PROTOCOL_ALIASES.get(text, text)

    @staticmethod
    def _format_zero_node_error(skip_reasons: list[str]) -> str:
        if not skip_reasons:
            return "0 valid nodes parsed"
        headline = "; ".join(skip_reasons[:3])
        return sanitize_source_error(f"0 valid nodes parsed; {headline}")

    @staticmethod
    def _record_filtered_technical_node(
        node_name: str,
        *,
        reason_counts: dict[str, int],
        filtered_examples: list[str],
    ) -> None:
        SourceFetcher._reason(reason_counts, _TECHNICAL_NODE_REASON)
        clean_name = str(node_name or "").strip()
        if clean_name and clean_name not in filtered_examples and len(filtered_examples) < 5:
            filtered_examples.append(clean_name)

    @staticmethod
    def _is_technical_node_name(name: str) -> bool:
        text = str(name or "").strip()
        if not text:
            return False
        lowered = text.lower()
        has_keyword = any(token in lowered for token in _TECHNICAL_KEYWORDS_EN) or any(
            token in text for token in _TECHNICAL_KEYWORDS_ZH
        )
        if not has_keyword:
            return False
        if _TRAFFIC_QUOTA_RE.search(text):
            return True
        if _TRAFFIC_UNIT_RE.search(text):
            return True
        if _TECHNICAL_STATUS_RE.search(text):
            return True
        if _URLTEST_MARKER_RE.search(text):
            return True
        if _TECHNICAL_FIELD_ASSIGN_RE.search(text):
            return True
        if _TECHNICAL_DATE_RE.search(text):
            has_date_keyword = any(token in lowered for token in _TECHNICAL_DATE_KEYWORDS_EN) or any(
                token in text for token in _TECHNICAL_DATE_KEYWORDS_ZH
            )
            if has_date_keyword:
                return True
        return False

    @staticmethod
    def _reason(counts: dict[str, int], text: str) -> None:
        key = str(text or "").strip()
        if not key:
            return
        counts[key] = int(counts.get(key, 0)) + 1

    @staticmethod
    def _bool_value(raw: Any) -> bool | None:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return None

    @staticmethod
    def _list_value(raw: Any) -> list[str]:
        if isinstance(raw, list):
            output: list[str] = []
            for item in raw:
                text = str(item or "").strip()
                if text:
                    output.append(text)
            return output
        text = str(raw or "").strip()
        if not text:
            return []
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        if "|" in text:
            return [part.strip() for part in text.split("|") if part.strip()]
        return [text]

    @staticmethod
    def _finalize_raw(raw: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(raw)
        output: dict[str, Any] = {}
        for key in _CANONICAL_RAW_KEYS:
            value = normalized.get(key)
            if value in (None, "", []):
                continue
            output[key] = value
        for key, value in normalized.items():
            if key in output:
                continue
            if value in (None, "", []):
                continue
            output[key] = value
        return output

    @staticmethod
    def _normalize_mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        output: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = str(key or "").strip()
            if not clean_key or item in (None, "", [], {}):
                continue
            output[clean_key] = item
        return output

    @staticmethod
    def _int_value(raw: Any) -> int | None:
        if raw in (None, ""):
            return None
        try:
            return int(str(raw).strip())
        except Exception:
            return None

    @staticmethod
    def _reality_opts_from_query(query: dict[str, list[str]]) -> dict[str, str]:
        reality_opts: dict[str, str] = {}
        key_aliases = {
            "public-key": ("public-key", "public_key", "pbk"),
            "short-id": ("short-id", "short_id", "sid"),
            "spider-x": ("spider-x", "spider_x", "spx"),
        }
        for canonical_key, aliases in key_aliases.items():
            for alias in aliases:
                value = str((query.get(alias) or [""])[0]).strip()
                if value:
                    reality_opts[canonical_key] = value
                    break
        return reality_opts

    @staticmethod
    def _reality_opts_from_kv(kv: dict[str, str]) -> dict[str, str]:
        reality_opts: dict[str, str] = {}
        for key, value in kv.items():
            clean_key = str(key or "").strip().lower()
            clean_value = str(value or "").strip()
            if not clean_value:
                continue
            if clean_key in {"reality-opts.public-key", "reality_opts.public-key", "reality_opts.public_key"}:
                reality_opts["public-key"] = clean_value
            elif clean_key in {"reality-opts.short-id", "reality_opts.short-id", "reality_opts.short_id"}:
                reality_opts["short-id"] = clean_value
            elif clean_key in {"reality-opts.spider-x", "reality_opts.spider-x", "reality_opts.spider_x"}:
                reality_opts["spider-x"] = clean_value
        return reality_opts

    @staticmethod
    def _http_like_credentials(parts: list[str]) -> tuple[str, str]:
        username = parts[0] if len(parts) >= 1 else ""
        password = parts[1] if len(parts) >= 2 else ""
        return username.strip(), password.strip()

    @staticmethod
    def _parse_line_extras(extras: Iterable[str]) -> tuple[list[str], dict[str, str]]:
        plain: list[str] = []
        kv: dict[str, str] = {}
        for item in extras:
            text = str(item or "").strip()
            if not text:
                continue
            if "=" in text:
                key, value = text.split("=", 1)
                kv[key.strip().lower()] = value.strip()
            else:
                plain.append(text)
        return plain, kv

    def _build_node(
        self,
        *,
        source: StandardSource,
        name: str,
        host: str,
        port: int,
        protocol: str,
        username: str = "",
        password: str = "",
        raw: dict[str, Any] | None = None,
    ) -> NodeRecord | None:
        final_protocol = self._normalize_protocol(protocol)
        if final_protocol not in _SUPPORTED_PROTOCOLS:
            return None
        safe_name = str(name or "").strip() or f"{final_protocol}-{host}:{port}"
        safe_host = str(host or "").strip()
        if not safe_host:
            return None
        try:
            safe_port = int(port)
        except Exception:
            return None
        if safe_port <= 0 or safe_port > 65535:
            return None

        raw_payload = self._finalize_raw(raw or {})
        if final_protocol in {"vmess", "vless", "tuic"} and not username:
            username = str(raw_payload.get("uuid", "")).strip()
        if final_protocol in {"anytls", "hysteria2", "trojan", "ss", "tuic"} and not password:
            password = str(raw_payload.get("password", "")).strip()

        return NodeRecord(
            name=format_standard_node_name(source.name, safe_name),
            host=safe_host,
            port=safe_port,
            protocol=final_protocol,
            username=str(username or "").strip(),
            password=str(password or "").strip(),
            quality_group=source.quality_group,
            source_id=source.id,
            source_type="standard",
            raw=raw_payload,
        )

    async def _fetch_clash(self, source: StandardSource, *, trust_env: bool = True) -> FetchPayload:
        if not source.clash_url.strip():
            return FetchPayload(nodes=[])

        variants: list[_VariantFetchResult] = []
        for ua in _CLASH_USER_AGENTS:
            request_variant = f"ua:{ua}"
            try:
                async with build_async_http_client(self.settings, trust_env=trust_env) as client:
                    resp = await client.get(
                        source.clash_url,
                        timeout=self.settings.request_timeout_seconds,
                        headers=self._method_headers("clash", user_agent=ua),
                    )
                    resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else "unknown"
                variants.append(_VariantFetchResult(request_variant=request_variant, error=f"HTTP {status}", code="http_status"))
                continue
            except httpx.TimeoutException:
                variants.append(_VariantFetchResult(request_variant=request_variant, error="timeout", code="timeout"))
                continue
            except httpx.RequestError:
                variants.append(_VariantFetchResult(request_variant=request_variant, error="request failed", code="request_failed"))
                continue
            except Exception as exc:
                text = sanitize_source_error(str(exc)).strip() or exc.__class__.__name__
                variants.append(_VariantFetchResult(request_variant=request_variant, error=text, code="fetch_failed"))
                continue

            parsed, format_tag = self._best_effort_parse_for_clash(resp.text, source)
            if format_tag != "format:clash-yaml":
                request_variant = f"{request_variant}|{format_tag}"

            variants.append(
                _VariantFetchResult(
                    request_variant=request_variant,
                    nodes=parsed.nodes,
                    parsed_protocol_counts=parsed.parsed_protocol_counts,
                    skip_reasons=parsed.skip_reasons(),
                    error="" if parsed.nodes else self._format_zero_node_error(parsed.skip_reasons()),
                    filtered_technical_count=int(parsed.filtered_technical_count),
                    filtered_technical_examples=list(parsed.filtered_technical_examples),
                    code="" if parsed.nodes else "no_valid_nodes",
                )
            )

        if not variants:
            return FetchPayload(nodes=[])

        best = max(variants, key=lambda item: len(item.nodes))
        attempts = [
            SourcePullAttempt(
                method="",
                ok=bool(item.nodes),
                node_count=len(item.nodes),
                error="" if item.nodes else item.error,
                request_variant=item.request_variant,
                parsed_protocol_counts=item.parsed_protocol_counts,
                skip_reasons=item.skip_reasons,
                code="" if item.nodes else item.code,
                message="" if item.nodes else item.error,
            )
            for item in variants
        ]

        return FetchPayload(
            nodes=self._dedupe(best.nodes),
            request_variant=best.request_variant,
            parsed_protocol_counts=dict(best.parsed_protocol_counts),
            skip_reasons=list(best.skip_reasons),
            attempts=attempts,
            filtered_technical_count=int(best.filtered_technical_count),
            filtered_technical_examples=list(best.filtered_technical_examples),
        )

    @staticmethod
    def _payload_score(payload: ParsePayload) -> tuple[int, int]:
        return len(payload.nodes), sum(int(v) for v in payload.reason_counts.values())

    def _reason_payload(self, reason: str) -> ParsePayload:
        reason_counts: dict[str, int] = {}
        self._reason(reason_counts, reason)
        return ParsePayload(nodes=[], parsed_protocol_counts={}, reason_counts=reason_counts)

    def _best_effort_parse_for_clash(
        self,
        text: str,
        source: StandardSource,
    ) -> tuple[ParsePayload, str]:
        candidates: list[tuple[str, ParsePayload]] = []

        try:
            payload = self._parse_clash_payload(text, source)
        except ValueError as exc:
            payload = self._reason_payload(str(exc))
        candidates.append(("format:clash-yaml", payload))
        if payload.nodes:
            return payload, "format:clash-yaml"

        uri_payload = self._parse_uri_subscription_text(text, source)
        candidates.append(("format:uri-plain", uri_payload))
        if uri_payload.nodes:
            return uri_payload, "format:uri-plain"

        decoded = self._decode_base64_payload(text)
        if decoded:
            base64_uri_payload = self._parse_uri_subscription_text(decoded, source)
            candidates.append(("format:base64-uri", base64_uri_payload))
            if base64_uri_payload.nodes:
                return base64_uri_payload, "format:base64-uri"

        sr_payload = self._parse_shadowrocket_ini(text, source)
        candidates.append(("format:ini-shadowrocket", sr_payload))
        if sr_payload.nodes:
            return sr_payload, "format:ini-shadowrocket"

        best_format, best_payload = max(
            candidates,
            key=lambda item: self._payload_score(item[1]),
        )
        return best_payload, best_format

    def _parse_clash_payload(self, text: str, source: StandardSource) -> ParsePayload:
        if not str(text or "").strip():
            raise ValueError("empty clash payload")
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError("invalid clash yaml") from exc

        if not isinstance(payload, dict):
            raise ValueError("invalid clash payload")
        proxies = payload.get("proxies")
        if not isinstance(proxies, list):
            raise ValueError("invalid clash payload: missing proxies")

        nodes: list[NodeRecord] = []
        parsed_protocol_counts: dict[str, int] = defaultdict(int)
        reason_counts: dict[str, int] = {}
        filtered_technical_count = 0
        filtered_technical_examples: list[str] = []

        for item in proxies:
            if not isinstance(item, dict):
                self._reason(reason_counts, "invalid clash proxy entry")
                continue
            node, reason = self._node_from_clash_proxy_with_reason(item, source)
            if not node:
                self._reason(reason_counts, reason or "invalid clash proxy")
                continue
            if self._is_technical_node_name(node.name):
                filtered_technical_count += 1
                self._record_filtered_technical_node(
                    node.name,
                    reason_counts=reason_counts,
                    filtered_examples=filtered_technical_examples,
                )
                continue
            nodes.append(node)
            parsed_protocol_counts[node.protocol] += 1

        return ParsePayload(
            nodes=self._dedupe(nodes),
            parsed_protocol_counts=dict(parsed_protocol_counts),
            reason_counts=reason_counts,
            filtered_technical_count=filtered_technical_count,
            filtered_technical_examples=filtered_technical_examples,
        )

    def _node_from_clash_proxy(
        self,
        proxy: dict[str, Any],
        source: StandardSource,
    ) -> NodeRecord | None:
        node, _ = self._node_from_clash_proxy_with_reason(proxy, source)
        return node

    def _node_from_clash_proxy_with_reason(
        self,
        proxy: dict[str, Any],
        source: StandardSource,
    ) -> tuple[NodeRecord | None, str]:
        name = str(proxy.get("name") or "").strip()
        host = str(proxy.get("server") or "").strip()
        port_raw = proxy.get("port")
        raw_protocol = str(proxy.get("type") or "").strip()
        protocol = self._normalize_protocol(raw_protocol)

        if not name:
            return None, "missing proxy name"
        if not host:
            return None, "missing proxy host"

        try:
            port = int(port_raw)
        except Exception:
            return None, "invalid proxy port"

        if port <= 0 or port > 65535:
            return None, "invalid proxy port"

        if protocol not in _SUPPORTED_PROTOCOLS:
            return None, unsupported_protocol_reason(raw_protocol or "unknown", known_source_secrets([source]))

        raw = dict(proxy)
        username = str(proxy.get("username") or "").strip()
        password = str(proxy.get("password") or "").strip()

        uuid = str(proxy.get("uuid") or proxy.get("id") or "").strip()
        if uuid:
            raw["uuid"] = uuid
        if protocol in {"vmess", "vless", "tuic"}:
            username = username or uuid
        if protocol in {"ss", "trojan", "anytls", "hysteria2", "tuic"}:
            password = password or str(raw.get("password") or "").strip()

        if protocol == "vless":
            flow = str(proxy.get("flow") or "").strip()
            if flow:
                raw["flow"] = flow
            packet_encoding = str(
                proxy.get("packet-encoding")
                or proxy.get("packet_encoding")
                or proxy.get("packetEncoding")
                or ""
            ).strip()
            if packet_encoding:
                raw["packet_encoding"] = packet_encoding
            reality_opts = self._normalize_mapping(
                proxy.get("reality-opts")
                if proxy.get("reality-opts") is not None
                else proxy.get("reality_opts")
            )
            if reality_opts:
                raw["reality_opts"] = reality_opts

        if protocol == "tuic":
            token = str(proxy.get("token") or "").strip()
            if token:
                raw["token"] = token
                if not password and username == token:
                    username = ""
            tuic_version = self._int_value(proxy.get("version"))
            if tuic_version in {4, 5}:
                raw["tuic_version"] = tuic_version
            elif token:
                raw["tuic_version"] = 4
            elif username and password:
                raw["tuic_version"] = 5
            reduce_rtt = self._bool_value(
                proxy.get("reduce-rtt")
                if proxy.get("reduce-rtt") is not None
                else proxy.get("reduce_rtt")
            )
            if reduce_rtt is not None:
                raw["reduce_rtt"] = reduce_rtt

        sni = str(
            proxy.get("sni") or proxy.get("servername") or proxy.get("server_name") or proxy.get("peer") or ""
        ).strip()
        if sni:
            raw["sni"] = sni

        alpn = self._list_value(proxy.get("alpn"))
        if alpn:
            raw["alpn"] = alpn

        insecure = self._bool_value(
            proxy.get("insecure")
            if proxy.get("insecure") is not None
            else proxy.get("skip-cert-verify")
        )
        if insecure is not None:
            raw["insecure"] = insecure
        udp_enabled = self._bool_value(
            proxy.get("udp")
            if proxy.get("udp") is not None
            else proxy.get("udp-enabled")
        )
        if udp_enabled is not None:
            raw["udp"] = udp_enabled

        client_fp = str(
            proxy.get("client-fingerprint")
            or proxy.get("client_fingerprint")
            or proxy.get("fingerprint")
            or ""
        ).strip()
        if client_fp:
            raw["client_fingerprint"] = client_fp

        obfs = str(proxy.get("obfs") or "").strip()
        if obfs:
            raw["obfs"] = obfs

        obfs_password = str(
            proxy.get("obfs-password")
            or proxy.get("obfs_password")
            or proxy.get("obfsPassword")
            or ""
        ).strip()
        if obfs_password:
            raw["obfs_password"] = obfs_password

        plugin = str(proxy.get("plugin") or "").strip()
        if plugin:
            raw["plugin"] = plugin

        plugin_opts = self._normalize_mapping(
            proxy.get("plugin-opts")
            if proxy.get("plugin-opts") is not None
            else proxy.get("plugin_opts")
            if proxy.get("plugin_opts") is not None
            else proxy.get("pluginOpts")
        )
        raw.pop("plugin_opts", None)
        raw.pop("pluginOpts", None)
        if plugin_opts:
            raw["plugin-opts"] = plugin_opts
        else:
            raw.pop("plugin-opts", None)

        congestion_controller = str(
            proxy.get("congestion-controller")
            or proxy.get("congestion_controller")
            or proxy.get("congestionControl")
            or ""
        ).strip()
        if congestion_controller:
            raw["congestion_controller"] = congestion_controller

        udp_relay_mode = str(
            proxy.get("udp-relay-mode")
            or proxy.get("udp_relay_mode")
            or proxy.get("udpRelayMode")
            or ""
        ).strip()
        if udp_relay_mode:
            raw["udp_relay_mode"] = udp_relay_mode

        node = self._build_node(
            source=source,
            name=name,
            host=host,
            port=port,
            protocol=protocol,
            username=username,
            password=password,
            raw=raw,
        )
        if not node:
            return None, "invalid clash proxy"
        return node, ""

    async def _fetch_shadowrocket(
        self,
        source: StandardSource,
        *,
        trust_env: bool = True,
    ) -> FetchPayload:
        if not source.shadowrocket_url.strip():
            return FetchPayload(nodes=[])

        async with build_async_http_client(self.settings, trust_env=trust_env) as client:
            resp = await client.get(
                source.shadowrocket_url,
                timeout=self.settings.request_timeout_seconds,
                headers=self._method_headers("shadowrocket"),
            )
            resp.raise_for_status()

        raw_text = str(resp.text or "")
        parsed, format_tag = self._best_effort_parse_for_shadowrocket(raw_text, source)
        return FetchPayload(
            nodes=parsed.nodes,
            request_variant=format_tag,
            parsed_protocol_counts=parsed.parsed_protocol_counts,
            skip_reasons=parsed.skip_reasons(),
            filtered_technical_count=parsed.filtered_technical_count,
            filtered_technical_examples=parsed.filtered_technical_examples,
        )

    def _best_effort_parse_for_shadowrocket(
        self,
        text: str,
        source: StandardSource,
    ) -> tuple[ParsePayload, str]:
        candidates: list[tuple[str, ParsePayload]] = []

        ini_payload = self._parse_shadowrocket_ini(text, source)
        candidates.append(("format:ini", ini_payload))
        if ini_payload.nodes:
            return ini_payload, "format:ini"

        uri_payload = self._parse_uri_subscription_text(text, source)
        candidates.append(("format:uri-plain", uri_payload))
        if uri_payload.nodes:
            return uri_payload, "format:uri-plain"

        decoded = self._decode_base64_payload(text)
        if decoded:
            base64_uri_payload = self._parse_uri_subscription_text(decoded, source)
            candidates.append(("format:base64-uri", base64_uri_payload))
            if base64_uri_payload.nodes:
                return base64_uri_payload, "format:base64-uri"

        try:
            clash_payload = self._parse_clash_payload(text, source)
        except ValueError as exc:
            clash_payload = self._reason_payload(str(exc))
        candidates.append(("format:clash-yaml", clash_payload))
        if clash_payload.nodes:
            return clash_payload, "format:clash-yaml"

        surge_payload = self._parse_surge_ini(text, source)
        candidates.append(("format:ini-surge", surge_payload))
        if surge_payload.nodes:
            return surge_payload, "format:ini-surge"

        best_format, best_payload = max(
            candidates,
            key=lambda item: self._payload_score(item[1]),
        )
        return best_payload, best_format

    async def _fetch_surge(self, source: StandardSource, *, trust_env: bool = True) -> FetchPayload:
        if not source.surge_url.strip():
            return FetchPayload(nodes=[])
        async with build_async_http_client(self.settings, trust_env=trust_env) as client:
            resp = await client.get(
                source.surge_url,
                timeout=self.settings.request_timeout_seconds,
                headers=self._method_headers("surge"),
            )
            resp.raise_for_status()

        parsed = self._parse_surge_ini(resp.text, source)
        return FetchPayload(
            nodes=parsed.nodes,
            request_variant="format:ini",
            parsed_protocol_counts=parsed.parsed_protocol_counts,
            skip_reasons=parsed.skip_reasons(),
            filtered_technical_count=parsed.filtered_technical_count,
            filtered_technical_examples=parsed.filtered_technical_examples,
        )

    @staticmethod
    def _decode_base64_payload(text: str) -> str:
        compact = "".join(str(text or "").split())
        if len(compact) < 24 or len(compact) % 4 == 1:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
            return ""
        padded = compact + "=" * ((4 - len(compact) % 4) % 4)
        try:
            decoded = base64.b64decode(padded, validate=False)
        except (binascii.Error, ValueError):
            return ""
        try:
            text_out = decoded.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        return text_out.strip()

    def _parse_shadowrocket_ini(self, text: str, source: StandardSource) -> ParsePayload:
        nodes: list[NodeRecord] = []
        parsed_protocol_counts: dict[str, int] = defaultdict(int)
        reason_counts: dict[str, int] = {}
        filtered_technical_count = 0
        filtered_technical_examples: list[str] = []
        in_proxy = False

        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_proxy = line.lower() == "[proxy]"
                continue
            if not in_proxy:
                continue
            node, reason = self._node_from_shadowrocket_line_with_reason(line, source)
            if not node:
                self._reason(reason_counts, reason or "invalid shadowrocket line")
                continue
            if self._is_technical_node_name(node.name):
                filtered_technical_count += 1
                self._record_filtered_technical_node(
                    node.name,
                    reason_counts=reason_counts,
                    filtered_examples=filtered_technical_examples,
                )
                continue
            nodes.append(node)
            parsed_protocol_counts[node.protocol] += 1

        return ParsePayload(
            nodes=self._dedupe(nodes),
            parsed_protocol_counts=dict(parsed_protocol_counts),
            reason_counts=reason_counts,
            filtered_technical_count=filtered_technical_count,
            filtered_technical_examples=filtered_technical_examples,
        )

    def _parse_surge_ini(self, text: str, source: StandardSource) -> ParsePayload:
        nodes: list[NodeRecord] = []
        parsed_protocol_counts: dict[str, int] = defaultdict(int)
        reason_counts: dict[str, int] = {}
        filtered_technical_count = 0
        filtered_technical_examples: list[str] = []
        in_proxy = False

        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_proxy = line.lower() == "[proxy]"
                continue
            if not in_proxy:
                continue
            node, reason = self._node_from_surge_line_with_reason(line, source)
            if not node:
                self._reason(reason_counts, reason or "invalid surge line")
                continue
            if self._is_technical_node_name(node.name):
                filtered_technical_count += 1
                self._record_filtered_technical_node(
                    node.name,
                    reason_counts=reason_counts,
                    filtered_examples=filtered_technical_examples,
                )
                continue
            nodes.append(node)
            parsed_protocol_counts[node.protocol] += 1

        return ParsePayload(
            nodes=self._dedupe(nodes),
            parsed_protocol_counts=dict(parsed_protocol_counts),
            reason_counts=reason_counts,
            filtered_technical_count=filtered_technical_count,
            filtered_technical_examples=filtered_technical_examples,
        )

    def _parse_uri_subscription_text(self, text: str, source: StandardSource) -> ParsePayload:
        nodes: list[NodeRecord] = []
        parsed_protocol_counts: dict[str, int] = defaultdict(int)
        reason_counts: dict[str, int] = {}
        filtered_technical_count = 0
        filtered_technical_examples: list[str] = []

        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.upper().startswith("STATUS="):
                continue
            if line.startswith("//"):
                continue
            node, reason = self._node_from_uri_line(line, source)
            if not node:
                self._reason(reason_counts, reason or "invalid uri line")
                continue
            if self._is_technical_node_name(node.name):
                filtered_technical_count += 1
                self._record_filtered_technical_node(
                    node.name,
                    reason_counts=reason_counts,
                    filtered_examples=filtered_technical_examples,
                )
                continue
            nodes.append(node)
            parsed_protocol_counts[node.protocol] += 1

        return ParsePayload(
            nodes=self._dedupe(nodes),
            parsed_protocol_counts=dict(parsed_protocol_counts),
            reason_counts=reason_counts,
            filtered_technical_count=filtered_technical_count,
            filtered_technical_examples=filtered_technical_examples,
        )

    def _node_from_uri_line(self, line: str, source: StandardSource) -> tuple[NodeRecord | None, str]:
        try:
            lower = line.lower()
            if lower.startswith("vmess://"):
                return self._node_from_vmess_uri(line, source)
            if lower.startswith("ss://"):
                return self._node_from_ss_uri(line, source)
            return self._node_from_generic_uri(line, source)
        except (ValueError, TypeError, UnicodeError, binascii.Error):
            # Never include the offending URI or exception text: both can
            # contain credentials. One malformed line must not abort a source.
            return None, "invalid uri field"

    @staticmethod
    def _uri_transport_fields(query: dict[str, list[str]]) -> tuple[dict[str, Any], str]:
        network = str((query.get("type") or query.get("network") or ["tcp"])[0]).lower()
        if network not in {"tcp", "ws"}:
            return {}, "unsupported uri transport"
        security = str((query.get("security") or ["none"])[0]).lower()
        if security not in {"none", "tls", "reality"}:
            return {}, "unsupported uri security"
        if any(query.get(key) for key in ("ech", "pcs", "vcn", "pqv", "spx", "fm")):
            return {}, "unsupported uri security extension"
        if (query.get("headerType") or ["none"])[0] != "none":
            return {}, "unsupported uri transport header"
        raw: dict[str, Any] = {"network": network, "tls": security != "none"}
        if network == "ws":
            path = str((query.get("path") or ["/"])[0])
            if not path:
                return {}, "invalid websocket path"
            ws_opts: dict[str, Any] = {"path": path}
            host = str((query.get("host") or [""])[0]).strip()
            if host:
                ws_opts["headers"] = {"Host": host}
            raw["ws-opts"] = ws_opts
        return raw, ""

    def _node_from_vmess_uri(self, line: str, source: StandardSource) -> tuple[NodeRecord | None, str]:
        raw_payload = str(line or "")[8:]
        if "@" in raw_payload:
            return self._node_from_generic_uri(line, source)

        decoded = self._decode_base64_payload(raw_payload)
        if not decoded:
            return None, "invalid vmess uri"
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            return None, "invalid vmess json"
        if not isinstance(payload, dict):
            return None, "invalid vmess json"

        host = str(payload.get("add") or payload.get("host") or "").strip()
        port_raw = payload.get("port")
        try:
            port = int(port_raw)
        except Exception:
            return None, "invalid vmess port"

        uuid = str(payload.get("id") or payload.get("uuid") or "").strip()
        if not uuid:
            return None, "missing vmess uuid"

        name = str(payload.get("ps") or payload.get("name") or "").strip() or f"vmess-{host}:{port}"
        raw: dict[str, Any] = {
            "uuid": uuid,
            "cipher": str(payload.get("scy") or "auto"),
            "alterId": self._int_value(payload.get("aid")) or 0,
        }
        transport, reason = self._uri_transport_fields({
            "type": [str(payload.get("net") or "tcp")],
            "security": [str(payload.get("tls") or "none")],
            "path": [str(payload.get("path") or "/")],
            "host": [str(payload.get("host") or "")],
            "headerType": [str(payload.get("type") or "none")],
        })
        if reason:
            return None, reason
        raw.update(transport)
        if str(payload.get("tls") or "none").lower() not in {"none", "tls"}:
            return None, "unsupported vmess json security"
        client_fp = str(payload.get("fp") or payload.get("fingerprint") or "").strip()
        if client_fp:
            raw["client_fingerprint"] = client_fp

        sni = str(payload.get("sni") or payload.get("host") or "").strip()
        if sni:
            raw["sni"] = sni

        insecure = self._bool_value(payload.get("allowInsecure"))
        if insecure is not None:
            raw["insecure"] = insecure

        alpn = self._list_value(payload.get("alpn"))
        if alpn:
            raw["alpn"] = alpn

        node = self._build_node(
            source=source,
            name=name,
            host=host,
            port=port,
            protocol="vmess",
            username=uuid,
            raw=raw,
        )
        if not node:
            return None, "invalid vmess node"
        return node, ""

    def _node_from_ss_uri(self, line: str, source: StandardSource) -> tuple[NodeRecord | None, str]:
        text = str(line or "").strip()
        if not text.lower().startswith("ss://"):
            return None, "invalid ss uri"

        scheme_payload = text[5:]
        if "#" in scheme_payload:
            payload_part, fragment = scheme_payload.split("#", 1)
            name = unquote(fragment).strip()
        else:
            payload_part = scheme_payload
            name = ""

        query = ""
        if "?" in payload_part:
            payload_part, query = payload_part.split("?", 1)

        if "@" not in payload_part:
            decoded = self._decode_base64_payload(payload_part)
            if not decoded or "@" not in decoded:
                return None, "invalid ss uri"
            payload_part = decoded

        if "://" in payload_part:
            payload_part = payload_part.split("://", 1)[1]

        parts = urlsplit(f"ss://{payload_part}")
        host = str(parts.hostname or "").strip()
        port = parts.port
        if not host or not port:
            return None, "invalid ss host/port"

        username = unquote(parts.username or "").strip()
        password = unquote(parts.password or "").strip()

        if not password and username:
            decoded_cred = self._decode_base64_payload(username)
            if decoded_cred and ":" in decoded_cred:
                method, pwd = decoded_cred.split(":", 1)
                username = method.strip()
                password = pwd.strip()

        cipher = username.strip()
        if not cipher or not password:
            return None, "invalid ss credentials"

        raw: dict[str, Any] = {"cipher": cipher, "password": password}
        q = parse_qs(query)
        plugin_value = str((q.get("plugin") or [""])[0])
        if plugin_value:
            fields: list[str] = []
            current: list[str] = []
            escaped = False
            for character in plugin_value:
                if escaped:
                    current.append(character)
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == ";":
                    fields.append("".join(current))
                    current = []
                else:
                    current.append(character)
            if escaped:
                return None, "invalid ss plugin escape"
            fields.append("".join(current))
            plugin = fields[0].strip()
            if plugin not in {"simple-obfs", "obfs-local", "obfs", "v2ray-plugin"}:
                return None, "unsupported ss plugin"
            options: dict[str, Any] = {}
            aliases = {"obfs": "mode", "obfs-host": "host", "obfs-uri": "path"}
            for field in fields[1:]:
                key, separator, value = field.partition("=")
                key = aliases.get(key, key)
                if key not in {"mode", "host", "path", "tls", "mux", "skip-cert-verify"}:
                    return None, "unsupported ss plugin option"
                options[key] = value if separator else True
            if plugin in {"simple-obfs", "obfs-local", "obfs"} and options.get("mode") not in {"http", "tls"}:
                return None, "unsupported ss obfs mode"
            if plugin == "v2ray-plugin":
                options.setdefault("mode", "websocket")
                if options["mode"] != "websocket":
                    return None, "unsupported ss plugin transport"
                for key in ("tls", "mux", "skip-cert-verify"):
                    if key in options:
                        converted = self._bool_value(options[key])
                        if converted is None:
                            return None, "invalid ss plugin boolean"
                        options[key] = converted
            raw["plugin"] = "obfs" if plugin in {"simple-obfs", "obfs-local"} else plugin
            raw["plugin-opts"] = options
            raw["source_uri"] = text
        sni = str((q.get("sni") or q.get("peer") or [""])[0]).strip()
        if sni:
            raw["sni"] = sni

        node = self._build_node(
            source=source,
            name=name or f"ss-{host}:{port}",
            host=host,
            port=port,
            protocol="ss",
            password=password,
            raw=raw,
        )
        if not node:
            return None, "invalid ss node"
        return node, ""

    def _node_from_generic_uri(self, line: str, source: StandardSource) -> tuple[NodeRecord | None, str]:
        try:
            parsed = urlsplit(line)
        except Exception:
            return None, "invalid uri"

        protocol = self._normalize_protocol(parsed.scheme)
        if protocol not in _SUPPORTED_PROTOCOLS:
            return None, unsupported_protocol_reason(
                line.strip().partition(":")[0] if parsed.scheme else "unknown", known_source_secrets([source]),
            )

        host = str(parsed.hostname or "").strip()
        port = parsed.port
        if not host or not port:
            return None, "invalid uri host/port"

        username = unquote(parsed.username or "").strip()
        password = unquote(parsed.password or "").strip()

        query = parse_qs(parsed.query)

        raw: dict[str, Any] = {}
        if protocol in {"vmess", "vless", "trojan"}:
            if any(len(values) != 1 for values in query.values()):
                return None, "duplicate uri query field"
            transport, reason = self._uri_transport_fields(query)
            if reason:
                return None, reason
            if protocol == "trojan" and (query.get("security") or ["tls"])[0] != "tls":
                return None, "unsupported trojan security"
            if (query.get("security") or [""])[0] == "reality":
                if protocol != "vless":
                    return None, "unsupported uri reality protocol"
                if not self._reality_opts_from_query(query).get("public-key"):
                    return None, "missing vless reality public key"
            # Trojan's TLS is intrinsic when no transport security is given.
            if protocol == "trojan" and "security" not in query:
                transport["tls"] = True
            raw.update(transport)
            raw["source_uri"] = line
            if protocol == "vmess":
                raw["cipher"] = str((query.get("encryption") or ["auto"])[0])
            if protocol == "vless" and (query.get("encryption") or ["none"])[0] != "none":
                return None, "unsupported vless encryption"
            raw["original_query"] = query
            known_keys = {
                "type", "network", "security", "encryption", "path", "host", "headerType",
                "uuid", "id", "username", "password", "flow", "packet-encoding", "packet_encoding",
                "public-key", "public_key", "pbk", "short-id", "short_id", "sid",
                "sni", "peer", "servername", "server_name", "alpn", "alpn[]",
                "insecure", "allowInsecure", "fp", "client-fingerprint", "udp", "udp-enabled", "udp_enabled",
                "remarks", "group",
            }
            if any(key not in known_keys for key in query):
                return None, "unsupported uri query field"
        uuid = str(
            (query.get("uuid") or query.get("id") or query.get("username") or [""])[0]
        ).strip()
        if uuid:
            raw["uuid"] = uuid

        if protocol in {"vmess", "vless", "tuic"}:
            username = username or uuid

        if protocol in {"trojan", "anytls", "hysteria2"} and not password and username:
            password = username
            username = ""

        if protocol in {"anytls", "hysteria2", "tuic", "trojan", "ss"}:
            password = password or str((query.get("password") or [""])[0]).strip()
            if password:
                raw["password"] = password

        if protocol == "vless":
            flow = str((query.get("flow") or [""])[0]).strip()
            if flow:
                raw["flow"] = flow
            packet_encoding = str(
                (query.get("packet-encoding") or query.get("packet_encoding") or [""])[0]
            ).strip()
            if packet_encoding:
                raw["packet_encoding"] = packet_encoding
            reality_opts = self._reality_opts_from_query(query)
            if reality_opts:
                raw["reality_opts"] = reality_opts

        if protocol == "tuic":
            token = str((query.get("token") or [""])[0]).strip()
            if not token and username and not password:
                token = username
                username = ""
            if token:
                raw["token"] = token
            tuic_version = self._int_value((query.get("version") or query.get("ver") or [""])[0])
            if tuic_version in {4, 5}:
                raw["tuic_version"] = tuic_version
            elif token:
                raw["tuic_version"] = 4
            elif username and password:
                raw["tuic_version"] = 5
            reduce_rtt = self._bool_value((query.get("reduce-rtt") or query.get("reduce_rtt") or [""])[0])
            if reduce_rtt is not None:
                raw["reduce_rtt"] = reduce_rtt

        sni = str(
            (
                query.get("sni")
                or query.get("peer")
                or query.get("servername")
                or query.get("server_name")
                or [""]
            )[0]
        ).strip()
        if sni:
            raw["sni"] = sni

        alpn = self._list_value(
            (query.get("alpn") or query.get("alpn[]") or [""])[0]
        )
        if alpn:
            raw["alpn"] = alpn

        insecure = self._bool_value((query.get("insecure") or query.get("allowInsecure") or [""])[0])
        if insecure is not None:
            raw["insecure"] = insecure

        client_fp = str((query.get("fp") or query.get("client-fingerprint") or [""])[0]).strip()
        if client_fp:
            raw["client_fingerprint"] = client_fp

        obfs = str((query.get("obfs") or [""])[0]).strip()
        if obfs:
            raw["obfs"] = obfs

        obfs_password = str((query.get("obfs-password") or query.get("obfs_password") or [""])[0]).strip()
        if obfs_password:
            raw["obfs_password"] = obfs_password

        congestion_controller = str(
            (query.get("congestion-controller") or query.get("congestion_controller") or [""])[0]
        ).strip()
        if congestion_controller:
            raw["congestion_controller"] = congestion_controller

        udp_relay_mode = str((query.get("udp-relay-mode") or query.get("udp_relay_mode") or [""])[0]).strip()
        if udp_relay_mode:
            raw["udp_relay_mode"] = udp_relay_mode
        udp_enabled = self._bool_value(
            (query.get("udp") or query.get("udp-enabled") or query.get("udp_enabled") or [""])[0]
        )
        if udp_enabled is not None:
            raw["udp"] = udp_enabled

        name = unquote(parsed.fragment or "").strip() or f"{protocol}-{host}:{port}"
        node = self._build_node(
            source=source,
            name=name,
            host=host,
            port=port,
            protocol=protocol,
            username=username,
            password=password,
            raw=raw,
        )
        if not node:
            return None, "invalid uri node"
        return node, ""

    def _node_from_shadowrocket_line(
        self,
        line: str,
        source: StandardSource,
    ) -> NodeRecord | None:
        node, _ = self._node_from_shadowrocket_line_with_reason(line, source)
        return node

    def _node_from_shadowrocket_line_with_reason(
        self,
        line: str,
        source: StandardSource,
    ) -> tuple[NodeRecord | None, str]:
        match = _SR_PROXY_LINE.match(line)
        if not match:
            return None, "invalid shadowrocket line"

        name = match.group(1).strip()
        raw_protocol = match.group(2).strip()
        protocol = self._normalize_protocol(raw_protocol)
        if protocol not in _SUPPORTED_PROTOCOLS:
            return None, unsupported_protocol_reason(raw_protocol or "unknown", known_source_secrets([source]))

        parts = [item.strip() for item in match.group(3).split(",")]
        if len(parts) < 2:
            return None, "invalid shadowrocket host/port"

        host = parts[0]
        try:
            port = int(parts[1])
        except Exception:
            return None, "invalid shadowrocket port"

        plain, kv = self._parse_line_extras(parts[2:])
        username = ""
        password = ""
        raw: dict[str, Any] = {}

        if protocol in {"http", "https", "socks5"}:
            username, password = self._http_like_credentials(plain)
        elif protocol == "ss":
            cipher = kv.get("encrypt-method") or kv.get("method") or (plain[0] if plain else "")
            password = kv.get("password") or (plain[1] if len(plain) >= 2 else "")
            if not cipher or not password:
                return None, "invalid ss credentials"
            raw["cipher"] = cipher
            raw["password"] = password
        elif protocol in {"vmess", "vless"}:
            username = kv.get("username") or kv.get("uuid") or (plain[0] if plain else "")
            if not username:
                return None, f"missing {protocol} uuid"
            raw["uuid"] = username
            if protocol == "vless":
                flow = kv.get("flow", "")
                if flow:
                    raw["flow"] = flow
                packet_encoding = kv.get("packet-encoding") or kv.get("packet_encoding") or ""
                if packet_encoding:
                    raw["packet_encoding"] = packet_encoding
                reality_opts = self._reality_opts_from_kv(kv)
                if reality_opts:
                    raw["reality_opts"] = reality_opts
        elif protocol == "tuic":
            token = kv.get("token") or ""
            username = kv.get("uuid") or kv.get("username") or ""
            password = kv.get("password") or ""
            if not token and not username and len(plain) >= 1 and len(plain) < 2:
                token = plain[0]
            if not token and not username and plain:
                username = plain[0]
            if not token and not password and len(plain) >= 2:
                password = plain[1]
            if token:
                raw["token"] = token
                raw["tuic_version"] = 4
            elif username and password:
                raw["uuid"] = username
                raw["password"] = password
                raw["tuic_version"] = 5
            else:
                return None, "invalid tuic credentials"
            reduce_rtt = self._bool_value(kv.get("reduce-rtt") or kv.get("reduce_rtt"))
            if reduce_rtt is not None:
                raw["reduce_rtt"] = reduce_rtt
        else:
            password = kv.get("password") or (plain[0] if plain else "")
            if protocol in {"trojan", "anytls", "hysteria2"} and not password:
                return None, f"missing {protocol} password"
            if password:
                raw["password"] = password

        sni = kv.get("sni") or kv.get("servername") or kv.get("server_name")
        if sni:
            raw["sni"] = sni

        alpn = self._list_value(kv.get("alpn", ""))
        if alpn:
            raw["alpn"] = alpn

        insecure = self._bool_value(kv.get("insecure", kv.get("skip-cert-verify", "")))
        if insecure is not None:
            raw["insecure"] = insecure

        client_fp = kv.get("client-fingerprint") or kv.get("client_fingerprint") or kv.get("fp")
        if client_fp:
            raw["client_fingerprint"] = client_fp

        if kv.get("obfs"):
            raw["obfs"] = kv.get("obfs", "")
        if kv.get("obfs-password") or kv.get("obfs_password"):
            raw["obfs_password"] = kv.get("obfs-password") or kv.get("obfs_password") or ""
        if kv.get("congestion-controller") or kv.get("congestion_controller"):
            raw["congestion_controller"] = kv.get("congestion-controller") or kv.get("congestion_controller") or ""
        if kv.get("udp-relay-mode") or kv.get("udp_relay_mode"):
            raw["udp_relay_mode"] = kv.get("udp-relay-mode") or kv.get("udp_relay_mode") or ""
        udp_enabled = self._bool_value(kv.get("udp") or kv.get("udp-enabled") or kv.get("udp_enabled") or kv.get("udp-relay"))
        if udp_enabled is not None:
            raw["udp"] = udp_enabled

        node = self._build_node(
            source=source,
            name=name,
            host=host,
            port=port,
            protocol=protocol,
            username=username,
            password=password,
            raw=raw,
        )
        if not node:
            return None, "invalid shadowrocket node"
        return node, ""

    def _node_from_surge_line(
        self,
        line: str,
        source: StandardSource,
    ) -> NodeRecord | None:
        node, _ = self._node_from_surge_line_with_reason(line, source)
        return node

    def _node_from_surge_line_with_reason(
        self,
        line: str,
        source: StandardSource,
    ) -> tuple[NodeRecord | None, str]:
        match = _SURGE_PROXY_LINE.match(line)
        if not match:
            return None, "invalid surge line"

        name = match.group(1).strip()
        raw_protocol = match.group(2).strip()
        protocol = self._normalize_protocol(raw_protocol)
        if protocol == "vless":
            return None, "unsupported protocol vless"
        if protocol not in _SUPPORTED_PROTOCOLS:
            return None, unsupported_protocol_reason(raw_protocol or "unknown", known_source_secrets([source]))

        parts = [item.strip() for item in match.group(3).split(",")]
        if len(parts) < 2:
            return None, "invalid surge host/port"

        host = parts[0]
        try:
            port = int(parts[1])
        except Exception:
            return None, "invalid surge port"

        plain, kv = self._parse_line_extras(parts[2:])
        username = ""
        password = ""
        raw: dict[str, Any] = {}

        if protocol in {"http", "https", "socks5"}:
            username, password = self._http_like_credentials(plain)
        elif protocol == "ss":
            cipher = kv.get("encrypt-method") or kv.get("method") or (plain[0] if plain else "")
            password = kv.get("password") or (plain[1] if len(plain) >= 2 else "")
            if not cipher or not password:
                return None, "invalid ss credentials"
            raw["cipher"] = cipher
            raw["password"] = password
        elif protocol in {"vmess", "vless"}:
            username = kv.get("username") or kv.get("uuid") or (plain[0] if plain else "")
            if not username:
                return None, f"missing {protocol} uuid"
            raw["uuid"] = username
            if protocol == "vless":
                flow = kv.get("flow", "")
                if flow:
                    raw["flow"] = flow
                packet_encoding = kv.get("packet-encoding") or kv.get("packet_encoding") or ""
                if packet_encoding:
                    raw["packet_encoding"] = packet_encoding
                reality_opts = self._reality_opts_from_kv(kv)
                if reality_opts:
                    raw["reality_opts"] = reality_opts
        elif protocol == "tuic":
            token = kv.get("token") or ""
            username = kv.get("uuid") or kv.get("username") or ""
            password = kv.get("password") or ""
            if not token and not username and len(plain) >= 1 and len(plain) < 2:
                token = plain[0]
            if not token and not username and plain:
                username = plain[0]
            if not token and not password and len(plain) >= 2:
                password = plain[1]
            if token:
                raw["token"] = token
                raw["tuic_version"] = 4
            elif username and password:
                raw["uuid"] = username
                raw["password"] = password
                raw["tuic_version"] = 5
            else:
                return None, "invalid tuic credentials"
            reduce_rtt = self._bool_value(kv.get("reduce-rtt") or kv.get("reduce_rtt"))
            if reduce_rtt is not None:
                raw["reduce_rtt"] = reduce_rtt
        else:
            password = kv.get("password") or (plain[0] if plain else "")
            if protocol in {"trojan", "anytls", "hysteria2"} and not password:
                return None, f"missing {protocol} password"
            if password:
                raw["password"] = password

        sni = kv.get("sni") or kv.get("servername") or kv.get("server_name")
        if sni:
            raw["sni"] = sni

        alpn = self._list_value(kv.get("alpn", ""))
        if alpn:
            raw["alpn"] = alpn

        insecure = self._bool_value(kv.get("insecure", kv.get("skip-cert-verify", "")))
        if insecure is not None:
            raw["insecure"] = insecure

        client_fp = kv.get("client-fingerprint") or kv.get("client_fingerprint") or kv.get("fp")
        if client_fp:
            raw["client_fingerprint"] = client_fp

        if kv.get("obfs"):
            raw["obfs"] = kv.get("obfs", "")
        if kv.get("obfs-password") or kv.get("obfs_password"):
            raw["obfs_password"] = kv.get("obfs-password") or kv.get("obfs_password") or ""
        if kv.get("congestion-controller") or kv.get("congestion_controller"):
            raw["congestion_controller"] = kv.get("congestion-controller") or kv.get("congestion_controller") or ""
        if kv.get("udp-relay-mode") or kv.get("udp_relay_mode"):
            raw["udp_relay_mode"] = kv.get("udp-relay-mode") or kv.get("udp_relay_mode") or ""
        udp_enabled = self._bool_value(kv.get("udp") or kv.get("udp-enabled") or kv.get("udp_enabled") or kv.get("udp-relay"))
        if udp_enabled is not None:
            raw["udp"] = udp_enabled

        node = self._build_node(
            source=source,
            name=name,
            host=host,
            port=port,
            protocol=protocol,
            username=username,
            password=password,
            raw=raw,
        )
        if not node:
            return None, "invalid surge node"
        return node, ""

    def _dedupe(self, nodes: list[NodeRecord]) -> list[NodeRecord]:
        seen: set[str] = set()
        output: list[NodeRecord] = []
        for node in nodes:
            key = node.dedupe_key()
            if key in seen:
                continue
            seen.add(key)
            output.append(node)
        return output
