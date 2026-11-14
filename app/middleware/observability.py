from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from prometheus_client import Counter

from app.services.error_diagnostics import error_detail

_logger = logging.getLogger("app.request")


HTTP_REQUESTS_TOTAL = Counter(
    "subhub_http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "path", "status_code"),
)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    return str(path) if path else request.url.path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def install_observability_middleware(app: FastAPI) -> None:
    if getattr(app.state, "_observability_middleware_installed", False):
        return
    app.state._observability_middleware_installed = True

    # Ensure JSON request logs go to the same stdout/stderr stream captured by uvicorn/nohup,
    # without depending on the uvicorn access log formatter.
    if not getattr(app.state, "_observability_request_logger_configured", False):
        app.state._observability_request_logger_configured = True
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        if not any(getattr(h, "_lzctoclash_json_handler", False) for h in _logger.handlers):
            handler = logging.StreamHandler(stream=sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler._lzctoclash_json_handler = True  # type: ignore[attr-defined]
            _logger.addHandler(handler)

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        request_id = str(request.headers.get("x-request-id", "")).strip() or uuid.uuid4().hex
        request.state.request_id = request_id

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            path = _route_path(request)
            diagnostic = error_detail(exc, "http_request", request_id)
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method, path=path, status_code=str(status_code)
            ).inc()
            _logger.info(
                json.dumps(
                    {
                        "ts_utc": _utc_now_iso(),
                        "request_id": request_id,
                        "method": request.method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "error_type": diagnostic["error_type"],
                        "error": diagnostic["message"],
                        "error_detail": diagnostic,
                        "client_ip": getattr(request.client, "host", ""),
                        "user_agent": request.headers.get("user-agent", ""),
                    }
                )
            )
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)
        path = _route_path(request)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=path, status_code=str(status_code)
        ).inc()
        _logger.info(
            json.dumps(
                {
                    "ts_utc": _utc_now_iso(),
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": getattr(request.client, "host", ""),
                    "user_agent": request.headers.get("user-agent", ""),
                }
            )
        )

        response.headers["X-Request-Id"] = request_id
        return response
