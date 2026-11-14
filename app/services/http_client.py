from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import Settings

_SYSTEM_CA_CERT_PATH = "/etc/ssl/certs/ca-certificates.crt"
_LAZYCAT_ENV_KEYS = (
    "LAZYCAT_APP_ID",
    "LZCAPP_API_GATEWAY_ADDRESS",
    "LAZYCAT_BOX_DOMAIN",
)
_LAZYCAT_IPV4_LOCAL_ADDRESS = "0.0.0.0"


def _is_lazycat_runtime() -> bool:
    return any(str(os.getenv(key, "")).strip() for key in _LAZYCAT_ENV_KEYS)


def _resolve_verify(settings: Settings) -> bool | str:
    if os.path.exists(_SYSTEM_CA_CERT_PATH):
        return _SYSTEM_CA_CERT_PATH
    return settings.verify_tls


def build_async_http_client(settings: Settings, **kwargs: Any) -> httpx.AsyncClient:
    options = dict(kwargs)
    if "transport" in options:
        return httpx.AsyncClient(**options)

    lazycat_runtime = _is_lazycat_runtime()
    verify_default = _resolve_verify(settings) if lazycat_runtime else settings.verify_tls
    verify = options.pop("verify", verify_default)
    if lazycat_runtime:
        trust_env = bool(options.get("trust_env", True))
        if trust_env:
            options["verify"] = verify
            return httpx.AsyncClient(**options)

        # Proxy mode cannot share the direct-path transport, or env proxies get bypassed.
        local_address = options.pop("local_address", _LAZYCAT_IPV4_LOCAL_ADDRESS)
        options["transport"] = httpx.AsyncHTTPTransport(
            verify=verify,
            local_address=str(local_address),
            trust_env=False,
        )
        options["trust_env"] = False
        return httpx.AsyncClient(**options)

    options["verify"] = verify
    return httpx.AsyncClient(**options)
