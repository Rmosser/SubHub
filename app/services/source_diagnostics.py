from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

from app.services.error_diagnostics import _SENSITIVE_QUERY_RE, error_detail, safe_error_text

if TYPE_CHECKING:
    from app.models import StandardSource

KnownSecrets = re.Pattern[str] | None


_REDACTED = "<redacted>"
_METHOD_START = re.compile(r"(?:clash|surge|shadowrocket): ")
_METHOD_BOUNDARY = re.compile(r"; (?=(?:clash|surge|shadowrocket): )")
# A left boundary prevents retrying a long scheme at every byte. Include
# malformed/long schemes in diagnostics; they can still carry credentials.
# Fixed http(s) prefixes also recognize URLs stuck to prose punctuation.
_URL_START = re.compile(
    r"https?://|(?<![A-Za-z0-9+.-])[A-Za-z0-9][A-Za-z0-9+.-]*://"
    r"|://|(?<![:/])/{2,}(?=[^/\s])",
    re.I,
)
_HTTP_START = re.compile(r"https?://", re.I)
_NONSPACE = re.compile(r"\S+")
_BARE_AUTHORITY = re.compile(r"@([^@/?#]*)")
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9_+~=-]+\Z")
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_+~=-]{10,}")
_HEX_RUN = re.compile(r"[A-Fa-f0-9]{16,}")
_UUID = re.compile(r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}\Z")
_JWT = re.compile(r"(?:eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
                  r"|[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,}){2})\Z")
_EXTENSION = re.compile(r"\.(?:yaml|yml|txt|conf|json)\Z", re.I)
_WORD_BOUNDARY = re.compile(r"[-_]|(?<=[a-z])(?=[A-Z])")
_PLAIN_PATHS = frozenset({
    "api", "v1", "v2", "client", "subscribe", "link", "sub", "s", "clash", "surge",
    "shadowrocket", "subscription-userinfo", "client_subscribe_v2", "shadowrocket-config",
    "clash-meta-config", "getSubscribeContent", "subscription-configurations",
    "client-configurations", "internationalization", "download", "config",
})


def _decode_for_detection(value: str) -> str:
    for _ in range(2):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def _token_segment(value: str) -> bool:
    """Detect credentials without rewriting ordinary path spelling.

    After at most two percent decodes: credentials/unsafe delimiters, hex runs
    (including a token glued to prose),
    UUID, JWT (eyJ header or three base64url parts >=10) and padded base64
    take priority. Version numbers and ordinary dotted names are not JWTs.
    Strip a known file extension before checking. Then preserve named paths and word-like compounds
    (>=3 lowercase/title-case letters per part, optional final vNN). Runs of
    capitals such as AAexpiredAAAA are not words. A long lowercase word needs
    35%-65% vowels. Finally hide mixed alphanumeric strings >=10 characters
    and other token-alphabet strings >=16 characters, including runs joined
    to prose punctuation in an error. Word-shaped secrets
    can be missed; short/other-alphabet secrets are outside this heuristic.
    """
    if value == _REDACTED:
        return False
    value = _EXTENSION.sub("", value)
    # A replacement can abut preserved prose when a nested URL was invalid.
    # Classify the remaining text without repeatedly absorbing the marker.
    value = value.replace(_REDACTED, "")
    if any(char in value for char in "@<>"):
        return True
    if _HEX_RUN.search(value) or _UUID.fullmatch(value) or _JWT.fullmatch(value):
        return True
    if len(value) >= 16 and value.endswith("=") and _TOKEN_CHARS.fullmatch(value):
        return True
    if value in _PLAIN_PATHS:
        return False
    words = _WORD_BOUNDARY.split(value)
    if len(words) > 1:
        if re.fullmatch(r"v\d{1,2}", words[-1]):
            words = words[:-1]
        if words and all(re.fullmatch(r"(?:[a-z]{3,}|[A-Z][a-z]{2,})", word) for word in words):
            return False
    if value.isascii() and value.isalpha() and value.islower() and len(value) > 12:
        vowel_ratio = sum(char in "aeiou" for char in value) / len(value)
        if 0.35 <= vowel_ratio <= 0.65:
            return False
    if not _TOKEN_CHARS.fullmatch(value):
        return any(_token_segment(match.group(0)) for match in _TOKEN_RUN.finditer(value))
    return len(value) >= 16 or (
        len(value) >= 10 and any(char.isalpha() for char in value) and any(char.isdigit() for char in value)
    )


def extract_source_secrets(clash_url: str = "", surge_url: str = "", shadowrocket_url: str = "") -> frozenset[str]:
    """Extract the literal spellings of current configuration values.

    Each value is decoded once and kept as written, decoded and encoded once
    (uppercase hex). Query values also spell "+" and space both ways; host
    labels also appear lowercased, as httpx prints them. Preserve the named
    path vocabulary even in query or userinfo. Path/query values need six
    characters, userinfo/fragment four. A token file contributes both its
    segment and extension-free token.
    """
    secrets: set[str] = set()

    def add(raw: str, minimum: int, *, token_only: bool = False, query: bool = False, host: bool = False) -> None:
        value = unquote(raw.replace("+", " ") if query else raw)
        stem = _EXTENSION.sub("", value)
        if stem.casefold() in {word.casefold() for word in _PLAIN_PATHS} or value == _REDACTED:
            return
        if len(value) < minimum or (token_only and not _token_segment(value)):
            return
        spellings = {raw, value, quote(value, safe="")}
        if stem != value and len(stem) >= minimum:
            spellings |= {_EXTENSION.sub("", raw), stem, quote(stem, safe="")}
        if query:
            spellings |= {item.replace("+", " ") for item in spellings} | {item.replace(" ", "+") for item in spellings}
        if host:
            spellings |= {item.lower() for item in spellings}
        secrets.update(spellings)

    for url in (clash_url, surge_url, shadowrocket_url):
        if not url:
            continue
        try:
            parts = urlsplit(url)
            # Keep case: parts.hostname lowercases the configured spelling.
            userinfo, at, authority = parts.netloc.rpartition("@")
            if at:
                username, colon, password = userinfo.partition(":")
                add(username, 4)
                if colon:
                    add(password, 4)
            else:
                authority = parts.netloc
            if not authority.startswith("["):
                for label in authority.partition(":")[0].split("."):
                    add(label, 6, token_only=True, host=True)
            for segment in parts.path.split("/"):
                add(segment, 6, token_only=True)
            for pair in parts.query.split("&"):
                key, equals, value = pair.partition("=")
                if equals:
                    key = _decode_for_detection(key.replace("+", " "))
                    # Reuse the existing sensitive-query key table exactly.
                    sensitive = bool(_SENSITIVE_QUERY_RE.fullmatch(f"?{key}=probe"))
                    add(value, 6, token_only=not sensitive, query=True)
            add(parts.fragment, 4)
        except ValueError:
            # Invalid URL configuration has no trustworthy component boundaries.
            # Existing URL heuristics still handle its diagnostic rendering.
            continue
    return frozenset(secrets)


def known_source_secrets(sources: Iterable[StandardSource]) -> KnownSecrets:
    """Compile one request-local matcher from this tenant's current sources.

    A case-sensitive literal alternation, longest first, with the marker among
    the alternatives: at one position the longest spelling wins, so neither a
    shorter value nor the marker splits a longer one. Literal alternatives do
    not backtrack; re's own cache keeps the compiled pattern.
    """
    spellings: set[str] = {_REDACTED}
    for source in sources:
        spellings.update(extract_source_secrets(source.clash_url, source.surge_url, source.shadowrocket_url))
    if len(spellings) == 1:
        return None
    return re.compile("|".join(re.escape(item) for item in sorted(spellings, key=lambda item: (-len(item), item))))


def _replace_known_secrets(text: str, known_secrets: KnownSecrets) -> str:
    return known_secrets.sub(_REDACTED, text) if known_secrets else text


def _public_path_segment(segment: str) -> str:
    if not segment or (len(segment) < 10 and segment.isascii() and segment.isalnum()):
        return segment
    decoded = _decode_for_detection(segment)
    # Hide the entire matrix-parameter suffix, including encoded ';'.
    if ";" in decoded:
        base = decoded.split(";", 1)[0]
        boundary = re.search(r";|%(?:25)?3b", segment, re.I)
        original_base = segment[:boundary.start()] if boundary else base
        return (
            _REDACTED if any(_token_segment(part) for part in base.split("/")) else original_base
        ) + ";" + _REDACTED
    if safe_error_text(decoded, limit=max(2000, len(decoded) * 10)) != decoded:
        return _REDACTED
    return _REDACTED if any(_token_segment(part) for part in decoded.split("/")) else segment


def _redact_single_url(text: str, *, path_authority: bool = False) -> str:
    # Parse the authority independently of the scheme. urlsplit lowercases
    # schemes and does not recognize malformed ones, both unsafe for diagnostic
    # text. Keep the original prefix, including its case and slash count.
    scheme_end = text.find("://")
    if scheme_end >= 0 and "@" not in text[:scheme_end]:
        prefix, body = text[:scheme_end + 3], text[scheme_end + 3:]
    elif text.startswith("//"):
        end = len(text) - len(text.lstrip("/"))
        prefix, body = text[:end], text[end:]
    elif "@" in text:
        prefix, body = "//", text.rsplit("@", 1)[-1]
    else:
        prefix, body = "", text
    try:
        parts = urlsplit("//" + body if prefix else body)
    except ValueError:
        return _REDACTED
    authority = parts.netloc.rsplit("@", 1)[-1]
    if not authority.startswith("["):  # IPv6 is not a list of DNS labels.
        host, colon, port = authority.partition(":")
        labels = []
        for label in host.split("."):
            decoded = _decode_for_detection(label)
            is_token = (
                decoded.isascii() and not decoded.lower().startswith("xn--") and len(decoded) >= 16
                and any(c.isalpha() for c in decoded) and any(c.isdigit() for c in decoded)
            )
            labels.append(_REDACTED if is_token else label)
        authority = ".".join(labels) + colon + port
    # Punctuation + // inside a path has two valid interpretations. Keep the
    # relative URL's credential/host/path cleaning, and also hide its authority
    # if the original bytes would be sensitive as a path segment. This union
    # can hide an ordinary host beside userinfo; privacy wins at this boundary.
    if path_authority and _public_path_segment(parts.netloc) != parts.netloc:
        authority = _REDACTED
    # Repeated segments are common in adversarial inputs. Per-call memoization
    # avoids repeating decoding/regex work; no global mutable state is shared.
    segments: dict[str, str] = {}
    path = []
    for segment in parts.path.split("/"):
        if segment not in segments:
            segments[segment] = _public_path_segment(segment)
        path.append(segments[segment])
    return prefix + authority + "/".join(path)


def _url_and_suffix(value: str) -> tuple[str, str]:
    # Count once, then peel the tail once: O(n), even with 32000 closing ')'.
    pairs = {")": "(", "]": "[", "}": "{"}
    excess = {close: value.count(close) - value.count(opening) for close, opening in pairs.items()}
    end = len(value)
    while end:
        last = value[end - 1]
        if last in ".,;'\"":
            end -= 1
        elif last in excess and excess[last] > 0:
            excess[last] -= 1
            end -= 1
        else:
            break
    return value[:end], value[end:]


def _bare_host(authority: str) -> bool:
    # A backslash can terminate a malformed authority in exception text.
    authority = authority.split("\\", 1)[0]
    # Separate glued prose before validating host/port; keep the closing IPv6
    # bracket inside the host. Empty ports have the same meaning as no port.
    close = authority.find("]") if authority.startswith("[") else -1
    end = close + 1 if close >= 0 else 0
    authority = authority[:end] + re.split(r"[;,\)\]'\"]", authority[end:], maxsplit=1)[0]
    if not authority.startswith("[") and authority.count(":") > 1:
        try:
            return ip_address(authority).version == 6
        except ValueError:
            return False
    if authority.startswith("["):
        host, close, port = authority[1:].partition("]")
        if not close or (port and not (port.startswith(":") and (not port[1:] or port[1:].isdigit()))):
            return False
    else:
        host, colon, port = authority.partition(":")
        if colon and port and not port.isdigit():
            return False
    if host.lower() == "localhost":
        return True
    try:
        ip_address(host)
        return True
    except ValueError:
        labels = host.split(".")
        return (
            len(labels) > 1 and len(labels[-1]) >= 2 and labels[-1].isalpha()
            and all(label and all(c.isalnum() or c == "-" for c in label) for label in labels)
        )


def _is_bare_authority(chunk: str) -> bool:
    # Round 4 decision: inspect every @ (not just the last). A path after the
    # host, a slash-anchored block, or password-like userinfo + a recognizable
    # host is sufficient. Otherwise preserve prose and plain email addresses.
    first_colon = chunk.find(":")
    first_slash = chunk.find("/")
    for match in _BARE_AUTHORITY.finditer(chunk):
        at = match.start()
        if not at:  # userinfo must be nonempty
            continue
        authority = match.group(1)
        if chunk.startswith("/") or (authority and chunk[match.end():match.end() + 1] == "/"):
            return True
        if 0 <= first_colon < at and 0 <= first_slash < at:
            # Hidden-example priority also covers /path/u:p@h stuck to a
            # punctuation/encoded prefix in the required round 3 generator.
            return True
        if 0 <= first_colon < at and (_bare_host(authority) or not authority):
            # Keep the old malformed empty-host case (u:p@) hidden as required
            # by the decision's explicit hidden-example priority.
            return True
    return False


def _has_url_path(text: str) -> bool:
    scheme_end = text.find("://")
    body = text[scheme_end + 3:] if scheme_end >= 0 else text.lstrip("/")
    return "/" in re.split(r"[?#]", body, maxsplit=1)[0]


def _rewrite_urls(text: str, *, omit: bool = False) -> str:
    def rewrite_chunk(match: re.Match[str]) -> str:
        chunk = match.group(0)
        starts = []
        path_authorities: set[int] = set()
        for match in _URL_START.finditer(chunk):
            start = match.start()
            # A generic scheme must not swallow a preceding path token glued
            # to https://. Leave that prefix in the previous URL's path.
            http = _HTTP_START.search(match.group(0))
            if http:
                start += http.start()
            elif match.group(0).endswith("://") and _token_segment(match.group(0)[:-3]) and (
                starts or "@" in chunk[:start]
            ):
                start = match.end() - 3  # Hide the ambiguous original path segment.
            elif chunk[start] == "/" and starts:
                if chunk[start - 1] not in ",;'\"":
                    continue  # Empty path segments are not relative URL boundaries.
                if starts[-1] in path_authorities or _has_url_path(chunk[starts[-1]:start]):
                    path_authorities.add(start)
            starts.append(start)
        boundary = starts[0] if starts else len(chunk)
        bare_start = len(chunk) - len(chunk.lstrip("('\\\"[{,;"))
        bare, _ = _url_and_suffix(chunk[bare_start:boundary])
        # A relative-URL match may actually be the first two slashes of a bare
        # authority's path. Retain that evidence for the host-followed-by-/ rule.
        bare_candidate = bare + ("/" if chunk[boundary:boundary + 1] == "/" else "")
        if "@" in bare and _is_bare_authority(bare_candidate):
            starts.insert(0, bare_start)
        if not starts:
            return chunk
        result = [chunk[:starts[0]]]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(chunk)
            url, suffix = _url_and_suffix(chunk[start:end])
            public_url = _REDACTED if omit else _redact_single_url(url, path_authority=start in path_authorities)
            result.append(public_url + suffix)
        return "".join(result)

    return _NONSPACE.sub(rewrite_chunk, text)


def redact_source_url(value: str, known_secrets: KnownSecrets = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return sanitize_source_error(text, known_secrets) if known_secrets else sanitize_source_error(text)


def _clean_source_error_once(text: str, known_secrets: KnownSecrets = None) -> str:
    text = _rewrite_urls(_replace_known_secrets(text, known_secrets))
    # No summary length limit: all distinct errors must remain visible.
    return _rewrite_urls(safe_error_text(text, limit=max(2000, len(text) * 10)))


def sanitize_source_error(value: str, known_secrets: KnownSecrets = None) -> str:
    text = str(value or "")
    # KV replacements can expose another URL boundary. Settle those boundaries
    # inside this public call, rather than changing text on the next API read.
    for _ in range(3):
        previous = text
        text = _clean_source_error_once(text, known_secrets)
        if text == previous:
            return text
    following = _clean_source_error_once(text, known_secrets)
    if following == text:
        return text
    # Three changing passes are not a fixed-point proof. Hide the changing
    # span, expanded to whitespace boundaries so a partial URL/KV cannot be
    # exposed. Stable surrounding prose remains intact. Verify the result;
    # a cross-boundary dependency falls back to hiding the diagnostic as a
    # whole. Both returned forms are fixed points, with bounded work.
    start = 0
    while start < min(len(text), len(following)) and text[start] == following[start]:
        start += 1
    end, other_end = len(text), len(following)
    while end > start and other_end > start and text[end - 1] == following[other_end - 1]:
        end -= 1
        other_end -= 1
    while start and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    candidate = text[:start] + _REDACTED + text[end:]
    return candidate if _clean_source_error_once(candidate, known_secrets) == candidate else _REDACTED


def source_error_signal(public_error: str) -> str:
    """State keywords come from public prose, never URL hosts/paths or secrets."""
    return _rewrite_urls(public_error, omit=True).lower()


def source_error_detail(
    exc: BaseException, phase: str, correlation_id: str, known_secrets: KnownSecrets = None,
) -> dict[str, object]:
    """Clean full exception fields before applying the existing display limits."""
    detail = public_source_status(error_detail(
        exc, phase, correlation_id, sanitize=lambda value: sanitize_source_error(value, known_secrets),
    ), known_secrets)
    for field, limit in (("message", 2000), ("cause", 2000), ("stack", 8000)):
        value = detail.get(field)
        if isinstance(value, str) and len(value) > limit:
            # Cleaning a cut URL can complete its redaction marker. Keep the
            # display limit without leaving half a marker (or a matrix suffix
            # that would grow another marker on the next public read).
            start = value.rfind(_REDACTED)
            end = start if 0 <= start < limit < start + len(_REDACTED) else limit
            detail[field] = value[:end].rstrip(";")
    return detail


def unsupported_protocol_reason(protocol: str, known_secrets: KnownSecrets = None) -> str:
    # Known values first: the display cut below must not leave half of one.
    public = sanitize_source_error(protocol, known_secrets)
    if len(public) > 64:
        # Do not cut a URL or a redaction marker in half at the display limit.
        public = _rewrite_urls(public, omit=True)
        prefix = public[:64]
        if prefix.rfind("<") > prefix.rfind(">"):
            prefix = prefix[:prefix.rfind("<")]
        public = prefix + "…"
    return f"unsupported protocol {public}"


def summarize_pull_errors(value: str, known_secrets: KnownSecrets = None) -> str:
    """Deduplicate whole public method errors, preserving their first order."""
    text = sanitize_source_error(value, known_secrets) if known_secrets else sanitize_source_error(value)
    if not text.strip():
        return "all methods failed"
    seen: set[str] = set()
    entries: list[str] = []
    # Parser reasons containing '; ' stay in the preceding method entry.
    for entry in _METHOD_BOUNDARY.split(text):
        if _METHOD_START.match(entry):
            if entry in seen:
                continue
            seen.add(entry)
        entries.append(entry)
    return "; ".join(entries)


# Stable reason codes for a failed pull attempt; `docs/api/http-api.md` lists
# what each means. Any other value reads as `unclassified`.
PULL_REASON_CODES = frozenset({
    "url_not_configured",  # the method has no subscription URL
    "http_status",  # the upstream answered with an HTTP error status
    "timeout",
    "request_failed",  # connection, DNS or TLS failure
    "invalid_payload",  # the response could not be read as a subscription
    "no_valid_nodes",  # the response parsed but held no usable node
    "fetch_failed",  # any other error while fetching
    "manual_nodes_missing",
    "refresh_failed",  # the refresh itself raised before a result existed
    "all_methods_failed",  # the pull failed without a recorded attempt error
    "unclassified",  # stored before reasons were recorded, or not classified
})


def public_pull_reasons(value: object, known_secrets: KnownSecrets = None) -> list[dict[str, str]]:
    """Clean stored or fresh pull reasons for a public read.

    Each reason is one failed attempt: `method`, a stable `code`, the redacted
    `url` and the public `message`. Text is cleaned again on every read, like
    `last_pull_error`; identical reasons appear once, in first order.
    """
    if not isinstance(value, list):
        return []
    reasons: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        reason = {
            "method": str(item.get("method") or ""),
            "code": code if (code := str(item.get("code") or "")) in PULL_REASON_CODES else "unclassified",
            "url": redact_source_url(str(item.get("url") or ""), known_secrets),
            "message": sanitize_source_error(str(item.get("message") or ""), known_secrets).strip(),
        }
        key = tuple(reason.values())
        if key not in seen:
            seen.add(key)
            reasons.append(reason)
    return reasons


def source_pull_reasons(source: StandardSource, known_secrets: KnownSecrets = None) -> list[dict[str, str]]:
    """The public reasons for a source's last pull; empty unless that pull failed.

    A failure stored before reasons were recorded is one `unclassified`
    reason carrying the whole summary, so readers need only this field.
    """
    if source.last_pull_ok is not False:
        return []
    reasons = public_pull_reasons(source.last_pull_reasons, known_secrets)
    if reasons:
        return reasons
    return [{
        "method": "",
        "code": "unclassified" if source.last_pull_error else "all_methods_failed",
        "url": "",
        "message": summarize_pull_errors(source.last_pull_error, known_secrets),
    }]


def summarize_hub_error(value: str | None, source_errors: object, known_secrets: KnownSecrets = None) -> str | None:
    if not value:
        return value
    if isinstance(source_errors, list) and all(isinstance(error, str) for error in source_errors):
        summary = "; ".join(summarize_pull_errors(error, known_secrets) for error in source_errors)
        if value in ("; ".join(source_errors), summary):
            return summary
    # Without source boundaries, do not merge possibly distinct sources.
    return sanitize_source_error(value, known_secrets)


def public_source_status(value: dict[str, object], known_secrets: KnownSecrets = None) -> dict[str, object]:
    """Deep-copy diagnostic values; never modify stored/runtime objects."""
    def clean(item: object, field: str = "") -> object:
        if isinstance(item, dict):
            return {key: clean(child, str(key)) for key, child in item.items()}
        if isinstance(item, list):
            return [clean(child, field) for child in item]
        if isinstance(item, str):
            if field in {"clash_url", "surge_url", "shadowrocket_url"}:
                return item  # Editable configuration is not a diagnostic.
            # Only text fields carry diagnostics; enums and ids stay as stored.
            if field == "url":
                return redact_source_url(item, known_secrets)
            if field in {"error", "last_pull_error", "errors"}:
                return summarize_pull_errors(item, known_secrets) if item else item
            if field in {"last_error", "skip_reasons", "message", "cause", "stack"}:
                return sanitize_source_error(item, known_secrets)
        return deepcopy(item)

    return clean(value)  # type: ignore[return-value]


def public_runtime(value: dict[str, object], known_secrets: KnownSecrets = None) -> dict[str, object]:
    source_status = value.get("source_status") or {}
    aggregate = source_status.get("aggregate") if isinstance(source_status, dict) else None
    source_errors = aggregate.get("errors") if isinstance(aggregate, dict) else None
    payload = public_source_status(value, known_secrets)
    if "last_error" in value:
        payload["last_error"] = summarize_hub_error(value.get("last_error"), source_errors, known_secrets)
    return payload
