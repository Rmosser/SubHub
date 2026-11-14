from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import Request

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _request_base_url(request: Request) -> str:
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if forwarded_host:
        scheme = forwarded_proto or "https"
        return f"{scheme}://{forwarded_host}".rstrip("/")

    host_header = request.headers.get("host", "").strip()
    if host_header:
        scheme = request.url.scheme or "http"
        return f"{scheme}://{host_header}".rstrip("/")

    return str(request.base_url).rstrip("/")


def _host_port(url: str) -> tuple[str, int | None]:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").strip().lower()
    port = parsed.port
    if port is None:
        if parsed.scheme == "https":
            port = 443
        elif parsed.scheme == "http":
            port = 80
    return host, port


def resolve_base_url_context(request: Request, configured_base_url: str) -> dict[str, object]:
    request_base = _request_base_url(request)
    configured = (configured_base_url or "").strip()
    if configured:
        configured_base = configured.rstrip("/")
        conf_host, conf_port = _host_port(configured_base)
        req_host, req_port = _host_port(request_base)
        if (
            conf_host in _LOCAL_HOSTS
            and req_host
            and (conf_host != req_host or conf_port != req_port)
        ):
            reason = (
                f"APP_BASE_URL={configured_base} 与当前请求地址 {request_base} 不一致，"
                f"已自动回退为 {request_base}"
            )
            return {
                "base_url": request_base,
                "base_url_mismatch_detected": True,
                "base_url_mismatch_reason": reason,
            }
        return {
            "base_url": configured_base,
            "base_url_mismatch_detected": False,
            "base_url_mismatch_reason": "",
        }

    lazycat_domain = (os.getenv("LAZYCAT_APP_DOMAIN") or "").strip()
    if lazycat_domain:
        if lazycat_domain.startswith("http://") or lazycat_domain.startswith("https://"):
            return {
                "base_url": lazycat_domain.rstrip("/"),
                "base_url_mismatch_detected": False,
                "base_url_mismatch_reason": "",
            }
        return {
            "base_url": f"https://{lazycat_domain}".rstrip("/"),
            "base_url_mismatch_detected": False,
            "base_url_mismatch_reason": "",
        }

    return {
        "base_url": request_base,
        "base_url_mismatch_detected": False,
        "base_url_mismatch_reason": "",
    }


def resolve_base_url(request: Request, configured_base_url: str) -> str:
    return str(resolve_base_url_context(request, configured_base_url)["base_url"])


def is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url or "")
    host = (parsed.hostname or "").strip().lower()
    return host in _LOCAL_HOSTS
