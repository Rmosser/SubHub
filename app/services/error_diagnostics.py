from __future__ import annotations

import re
import traceback
from collections.abc import Callable
from typing import Any


_SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:access[_-]?token|api[_-]?key|authorization|cookie|password|secret|token|webhook[_-]?secret)=)[^&#\s]+",
    re.IGNORECASE,
)
_SENSITIVE_KV_RE = re.compile(
    r"((?:access[_-]?token|api[_-]?key|authorization|cookie|password|secret|token|webhook[_-]?secret)\s*[:=]\s*)[^\s,;}&]+",
    re.IGNORECASE,
)


def safe_error_text(value: Any, limit: int = 2000) -> str:
    return _SENSITIVE_KV_RE.sub(
        r"\1<redacted>",
        _SENSITIVE_QUERY_RE.sub(r"\1<redacted>", str(value or "")),
    )[:limit]


def error_detail(
    exc: BaseException, phase: str, correlation_id: str,
    *, sanitize: Callable[[str], str] | None = None,
) -> dict[str, object]:
    def text(value: object, limit: int = 2000) -> str:
        # Public source diagnostics must clean the complete value: truncation
        # can otherwise remove the @host needed to recognize long userinfo.
        raw = str(value or "")
        return safe_error_text(sanitize(raw) if sanitize else raw, limit)

    cause = exc.__cause__ or exc.__context__
    return {
        "correlation_id": correlation_id,
        "phase": phase,
        "error_type": type(exc).__name__,
        "message": text(exc),
        "cause": text(cause) if cause else None,
        "stack": text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), 8000),
    }
