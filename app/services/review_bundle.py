from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
from pathlib import Path
import re
from urllib.parse import urlparse

from app.services.export_artifacts import bundle_zip_bytes


REVIEW_BUNDLE_EXPECTED_FINAL = "FINAL,兜底代理,dns-failed"
_SURGE_IP_RULE_TYPES = {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR", "GEOIP", "IP-ASN"}
_REQUIREMENT_MARKER = "#!REQUIREMENT"
_MANAGED_CONFIG_PREFIX = "#!MANAGED-CONFIG "
_INCLUDE_PREFIX = "#!include "
_QUOTED_REQUIREMENT_RE = re.compile(r'^"[^"]+"$')
_OVERLAY_PLACEHOLDER_MARKERS = (
    "surge-mac-overlay-empty",
    "needs-rebind",
    "needs_rebind",
    "Open SubHub Manage > Advanced",
    "intentionally empty until",
    "none are enabled",
    "require contract rebinding",
    "setup:",
)


class ReviewBundleError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewBundleSummary:
    source_url: str
    managed_config_url: str
    overlay_source_url: str
    overlay_managed_config_url: str
    overlay_include_url: str
    profile: str
    built_at: str
    git_commit: str
    proxy_count: int
    proxy_group_definition_count: int
    unique_proxy_group_name_count: int
    rule_count: int
    process_rule_count: int
    first_dns_trigger_ip_line: int | None
    final_line: int | None
    review_gate_passed: bool
    review_gate_failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewBundleArtifacts:
    main_conf: str
    overlay_conf: str
    references_txt: str
    unicom_hits_txt: str
    localized_hits_txt: str
    zip_bytes: bytes
    summary: ReviewBundleSummary


def validate_reviewer_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReviewBundleError("base URL must be an absolute http(s) URL")
    _validate_public_host(parsed.hostname or "", context="base URL")
    return normalized


def _validate_public_host(hostname: str, *, context: str) -> None:
    host = str(hostname or "").strip().lower()
    if not host:
        raise ReviewBundleError(f"{context} is missing a hostname")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ReviewBundleError(f"{context} must not use localhost or .local hostnames")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return

    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    ):
        raise ReviewBundleError(f"{context} must not use a private, loopback, or reserved IP address")


def build_surge_review_bundle(
    main_conf: str,
    *,
    source_url: str,
    overlay_conf: str,
    overlay_source_url: str,
    profile: str,
    git_commit: str,
    built_at: datetime | None = None,
) -> ReviewBundleArtifacts:
    built_ts = (built_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = summarize_surge_review_bundle(
        main_conf,
        source_url=source_url,
        overlay_conf=overlay_conf,
        overlay_source_url=overlay_source_url,
        profile=profile,
        git_commit=git_commit,
        built_at=built_ts,
    )
    references_txt = _render_references(summary)
    hits_txt = _render_unicom_hits(main_conf)
    zip_bytes = _build_zip_bytes(
        main_conf=main_conf,
        overlay_conf=overlay_conf,
        references_txt=references_txt,
        hits_txt=hits_txt,
    )
    return ReviewBundleArtifacts(
        main_conf=main_conf,
        overlay_conf=overlay_conf,
        references_txt=references_txt,
        unicom_hits_txt=hits_txt,
        localized_hits_txt=hits_txt,
        zip_bytes=zip_bytes,
        summary=summary,
    )


def summarize_surge_review_bundle(
    main_conf: str,
    *,
    source_url: str,
    overlay_conf: str,
    overlay_source_url: str,
    profile: str,
    git_commit: str,
    built_at: str,
) -> ReviewBundleSummary:
    lines = main_conf.splitlines()
    overlay_lines = overlay_conf.splitlines()
    section = ""
    proxy_count = 0
    proxy_group_definition_count = 0
    proxy_group_names: set[str] = set()
    proxy_group_lines: list[tuple[int, str, str]] = []
    rule_lines: list[tuple[int, str]] = []

    for line_no, raw_line in enumerate(lines, 1):
        text = raw_line.strip()
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1]
            continue
        if not text:
            continue
        proxy_group_line = _extract_proxy_group_line(text)
        if section == "Proxy" and " = " in text and not text.startswith("#"):
            proxy_count += 1
        elif section == "Proxy Group" and proxy_group_line:
            group_name, payload = proxy_group_line
            proxy_group_definition_count += 1
            proxy_group_names.add(group_name)
            proxy_group_lines.append((line_no, group_name, payload))
        elif section == "Rule" and not text.startswith("#"):
            rule_lines.append((line_no, text))

    process_rule_count = sum(1 for _, text in rule_lines if text.startswith("PROCESS-"))
    first_dns_trigger_ip_line = _first_dns_trigger_ip_line(rule_lines)
    final_line = next((line_no for line_no, text in reversed(rule_lines) if text.startswith("FINAL,")), None)
    managed_config_url = _managed_config_url(lines)
    overlay_managed_config_url = _managed_config_url(overlay_lines)
    overlay_include_url = _include_url(overlay_lines)

    review_gate_failures = _review_gate_failures(
        lines,
        rule_lines=rule_lines,
        managed_config_url=managed_config_url,
        first_dns_trigger_ip_line=first_dns_trigger_ip_line,
        final_line=final_line,
        process_rule_count=process_rule_count,
        proxy_group_names=proxy_group_names,
        proxy_group_lines=proxy_group_lines,
    )
    review_gate_failures.extend(
        _overlay_review_gate_failures(
            overlay_lines,
            overlay_source_url=overlay_source_url,
            overlay_managed_config_url=overlay_managed_config_url,
            overlay_include_url=overlay_include_url,
            main_managed_config_url=managed_config_url,
        )
    )

    return ReviewBundleSummary(
        source_url=source_url,
        managed_config_url=managed_config_url,
        overlay_source_url=overlay_source_url,
        overlay_managed_config_url=overlay_managed_config_url,
        overlay_include_url=overlay_include_url,
        profile=profile,
        built_at=built_at,
        git_commit=git_commit,
        proxy_count=proxy_count,
        proxy_group_definition_count=proxy_group_definition_count,
        unique_proxy_group_name_count=len(proxy_group_names),
        rule_count=len(rule_lines),
        process_rule_count=process_rule_count,
        first_dns_trigger_ip_line=first_dns_trigger_ip_line,
        final_line=final_line,
        review_gate_passed=not review_gate_failures,
        review_gate_failures=review_gate_failures,
    )


def write_surge_review_bundle(
    artifacts: ReviewBundleArtifacts,
    out_path: str | Path,
    *,
    require_review_ready: bool = True,
) -> Path:
    if require_review_ready and not artifacts.summary.review_gate_passed:
        raise ReviewBundleError(
            "review gate failed: " + "; ".join(artifacts.summary.review_gate_failures)
        )

    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(artifacts.zip_bytes)
    return destination


def _directive_url(lines: list[str], prefix: str) -> str:
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith(prefix):
            continue
        return stripped.removeprefix(prefix).split(" ", 1)[0].strip()
    return ""


def _extract_proxy_group_line(text: str) -> tuple[str, str] | None:
    candidate = str(text or "").strip()
    if not candidate or " = " not in candidate:
        return None
    if candidate.startswith(_REQUIREMENT_MARKER):
        content = candidate[len(_REQUIREMENT_MARKER) :].strip()
        if not content:
            return None
        if content.startswith('"'):
            quote_end = content.find('"', 1)
            if quote_end == -1:
                return None
            candidate = content[quote_end + 1 :].strip()
        else:
            parts = content.split(None, 1)
            if len(parts) != 2:
                return None
            candidate = parts[1].strip()
    if " = " not in candidate:
        return None
    group_name, payload = candidate.split(" = ", 1)
    return group_name, payload


def _managed_config_url(lines: list[str]) -> str:
    return _directive_url(lines, _MANAGED_CONFIG_PREFIX)


def _include_url(lines: list[str]) -> str:
    return _directive_url(lines, _INCLUDE_PREFIX)


def _first_dns_trigger_ip_line(rule_lines: list[tuple[int, str]]) -> int | None:
    for line_no, text in rule_lines:
        parts = [item.strip() for item in text.split(",")]
        rule_type = parts[0]
        if rule_type not in _SURGE_IP_RULE_TYPES:
            continue
        if rule_type in {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR", "IP-ASN"} and "no-resolve" in parts[3:]:
            continue
        return line_no
    return None


def _review_gate_failures(
    lines: list[str],
    *,
    rule_lines: list[tuple[int, str]],
    managed_config_url: str,
    first_dns_trigger_ip_line: int | None,
    final_line: int | None,
    process_rule_count: int,
    proxy_group_names: set[str],
    proxy_group_lines: list[tuple[int, str, str]],
) -> list[str]:
    failures: list[str] = []
    if not managed_config_url:
        failures.append("missing managed config self-reference")
    else:
        parsed = urlparse(managed_config_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            failures.append("managed config self-reference is not an absolute http(s) URL")
        else:
            try:
                _validate_public_host(parsed.hostname or "", context="managed config self-reference")
            except ReviewBundleError as exc:
                failures.append(str(exc))

    for line_no, raw_line in enumerate(lines, 1):
        text = raw_line.strip()
        if text.startswith(_REQUIREMENT_MARKER) and " = " not in text:
            failures.append(f"line {line_no} uses standalone #!REQUIREMENT syntax")
        expression_failure = _validate_requirement_expression(text)
        if expression_failure:
            failures.append(f"line {line_no} {expression_failure}")

    failures.extend(
        _smart_group_nested_failures(
            proxy_group_names=proxy_group_names,
            proxy_group_lines=proxy_group_lines,
        )
    )

    if final_line is None:
        failures.append("missing FINAL rule")
    else:
        final_text = lines[final_line - 1].strip()
        if final_text != REVIEW_BUNDLE_EXPECTED_FINAL:
            failures.append(f"FINAL rule must be {REVIEW_BUNDLE_EXPECTED_FINAL}")

    if process_rule_count:
        failures.append("main Surge config still contains PROCESS-NAME rules")

    if first_dns_trigger_ip_line is not None:
        after_first_trigger = [
            text
            for line_no, text in rule_lines
            if line_no > first_dns_trigger_ip_line
            and (text.startswith("DOMAIN") or text.startswith("PROCESS-"))
        ]
        if after_first_trigger:
            failures.append("domain or process rules appear after the first DNS-triggering IP rule")

    if any(raw_line.strip() == "# Render warnings" for raw_line in lines):
        failures.append("main Surge config still includes render warnings trailer")
    if any("needs-rebind" in raw_line for raw_line in lines):
        failures.append("main Surge config still includes needs-rebind warnings")
    return failures


def _overlay_review_gate_failures(
    lines: list[str],
    *,
    overlay_source_url: str,
    overlay_managed_config_url: str,
    overlay_include_url: str,
    main_managed_config_url: str,
) -> list[str]:
    failures: list[str] = []
    if not overlay_managed_config_url:
        failures.append("overlay is missing managed config self-reference")
    elif overlay_managed_config_url != overlay_source_url:
        failures.append("overlay managed config self-reference must point to the overlay URL itself")
    else:
        try:
            parsed = urlparse(overlay_managed_config_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                failures.append("overlay managed config self-reference is not an absolute http(s) URL")
            else:
                _validate_public_host(parsed.hostname or "", context="overlay managed config self-reference")
        except ReviewBundleError as exc:
            failures.append(str(exc))

    if not overlay_include_url:
        failures.append("overlay is missing #!include target")
    elif overlay_include_url != main_managed_config_url:
        failures.append("overlay #!include must point to the main Surge managed config URL")
    else:
        try:
            parsed = urlparse(overlay_include_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                failures.append("overlay #!include target is not an absolute http(s) URL")
            else:
                _validate_public_host(parsed.hostname or "", context="overlay #!include target")
        except ReviewBundleError as exc:
            failures.append(str(exc))

    for line_no, raw_line in enumerate(lines, 1):
        text = raw_line.strip()
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in _OVERLAY_PLACEHOLDER_MARKERS):
            failures.append(f"overlay line {line_no} still contains placeholder or blocked-publish text")
        expression_failure = _validate_requirement_expression(text)
        if expression_failure:
            failures.append(f"overlay line {line_no} {expression_failure}")
    return failures


def _smart_group_nested_failures(
    *,
    proxy_group_names: set[str],
    proxy_group_lines: list[tuple[int, str, str]],
) -> list[str]:
    failures: list[str] = []
    for line_no, group_name, payload in proxy_group_lines:
        if not payload.startswith("smart,"):
            continue
        content = payload.removeprefix("smart,").strip()
        if content.startswith('include-other-group="') and content.endswith('"'):
            failures.append(
                f"line {line_no} smart group {group_name} uses include-other-group"
            )
            members = [
                item.strip()
                for item in content.removeprefix('include-other-group="').removesuffix('"').split(",")
                if item.strip()
            ]
        else:
            members = [
                item.strip()
                for item in content.split(",")
                if item.strip() and "=" not in item
            ]
        nested_groups = [item for item in members if item in proxy_group_names and item != group_name]
        if nested_groups:
            failures.append(
                f"line {line_no} smart group {group_name} nests policy group {nested_groups[0]}"
            )
    return failures


def _validate_requirement_expression(text: str) -> str | None:
    expression = _extract_requirement_expression(text)
    if not expression:
        return None
    if _QUOTED_REQUIREMENT_RE.fullmatch(expression):
        return None
    if any(char.isspace() for char in expression):
        return "uses unquoted spaced #!REQUIREMENT expression"
    if not any(operator in expression for operator in ("==", "!=", ">=", "<=", ">", "<")):
        return "uses malformed #!REQUIREMENT expression"
    return None


def _extract_requirement_expression(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith(_REQUIREMENT_MARKER):
        content = stripped[len(_REQUIREMENT_MARKER) :].strip()
        if not content:
            return ""
        if content.startswith('"'):
            quote_end = content.find('"', 1)
            if quote_end == -1:
                return content
            return content[: quote_end + 1]
        return content.split(None, 1)[0]
    suffix_marker = f"//!{_REQUIREMENT_MARKER.removeprefix('#!')}"
    if suffix_marker in stripped:
        return stripped.split(suffix_marker, 1)[1].strip()
    return ""


def _render_references(summary: ReviewBundleSummary) -> str:
    review_status = "pass" if summary.review_gate_passed else "fail"
    failure_lines = summary.review_gate_failures or ["none"]
    lines = [
        f"Main config source: {summary.source_url}",
        f"Managed config self-reference: {summary.managed_config_url or '-'}",
        f"Overlay source: {summary.overlay_source_url}",
        f"Overlay managed config self-reference: {summary.overlay_managed_config_url or '-'}",
        f"Overlay include target: {summary.overlay_include_url or '-'}",
        f"Built at: {summary.built_at}",
        f"Git commit: {summary.git_commit or 'unknown'}",
        f"Profile: {summary.profile}",
        "",
        "Audit summary:",
        f"- proxies: {summary.proxy_count}",
        f"- proxy_group_definitions: {summary.proxy_group_definition_count}",
        f"- unique_proxy_group_names: {summary.unique_proxy_group_name_count}",
        f"- rules: {summary.rule_count}",
        f"- process_rules_in_main: {summary.process_rule_count}",
        f"- first_dns_trigger_ip_line: {summary.first_dns_trigger_ip_line or '-'}",
        f"- final_line: {summary.final_line or '-'}",
        "",
        f"Review gate: {review_status}",
        *[f"- {item}" for item in failure_lines],
        "",
    ]
    return "\n".join(lines)


def _render_unicom_hits(main_conf: str) -> str:
    hits: list[str] = []
    for line_no, raw_line in enumerate(main_conf.splitlines(), 1):
        lowered = raw_line.lower()
        if "联通" in raw_line or "unicom" in lowered:
            hits.append(f"{line_no}:{raw_line}")
    return "\n".join(hits) + ("\n" if hits else "")


def _build_zip_bytes(
    *,
    main_conf: str,
    overlay_conf: str,
    references_txt: str,
    hits_txt: str,
) -> bytes:
    return bundle_zip_bytes(
        {
            "surge/lzcbox-surge-mac-overlay.conf": overlay_conf,
            "surge/lzcbox-surge.conf": main_conf,
            "surge/references.txt": references_txt,
            "surge/unicom-hits.txt": hits_txt,
            "surge/联通命中.txt": hits_txt,
        }
    )
