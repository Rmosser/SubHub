from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

_logger = logging.getLogger("app.lazycat.identity")


def _first_header(headers: Mapping[str, str] | Headers, names: tuple[str, ...]) -> str:
    for name in names:
        value = str(headers.get(name, "")).strip()
        if value:
            return value
    return ""


def resolve_lazycat_identity(headers: Mapping[str, str] | Headers) -> dict[str, str]:
    user_id = _first_header(
        headers,
        ("x-hc-user-id", "x-lzc-user-id", "x-lazycat-user-id"),
    )
    user_role = _first_header(
        headers,
        ("x-hc-user-role", "x-lzc-user-role", "x-lazycat-user-role"),
    )
    user_name = _first_header(
        headers,
        (
            "x-hc-user-name",
            "x-lzc-user-name",
            "x-lazycat-user-name",
            "x-hc-user-display-name",
            "x-lzc-user-display-name",
            "x-lazycat-user-display-name",
        ),
    )
    return {
        "user_id": user_id,
        "user_role": user_role,
        "user_name": user_name,
    }


def install_lazycat_identity_middleware(app: FastAPI) -> None:
    if getattr(app.state, "_lazycat_identity_middleware_installed", False):
        return
    app.state._lazycat_identity_middleware_installed = True

    logged_missing_header = False

    @app.middleware("http")
    async def lazycat_identity_middleware(request: Request, call_next):
        nonlocal logged_missing_header
        identity = resolve_lazycat_identity(request.headers)
        request.state.lazycat_user_id = identity["user_id"]
        request.state.lazycat_user_role = identity["user_role"]
        request.state.lazycat_user_name = identity["user_name"]

        registry = getattr(app.state, "tenant_registry", None)
        if registry is not None:
            path = request.url.path
            try:
                if path == "/setup" or path.startswith("/api/setup/"):
                    if registry.settings.manage_api_require_login and not identity["user_id"]:
                        raise HTTPException(status_code=401, detail="lazycat login required")
                elif path.startswith(("/sub/", "/rules/")):
                    if not registry.status("")["instance_initialized"]:
                        raise HTTPException(status_code=503, detail="setup required")
                    parts = path.split("/")
                    subscription_id = (
                        parts[3] if path.startswith("/sub/device/") and len(parts) > 3
                        else str(request.query_params.get("token") or "")
                    )
                    services = registry.for_subscription(subscription_id)
                    if services is None:
                        raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
                    request.state.services = services
                    await registry.ensure_started(services)
                elif path.startswith("/api/") or path in {"/diagnostics", "/readyz", "/metrics"}:
                    services = registry.for_user(identity["user_id"])
                    request.state.services = services
                    await registry.ensure_started(services)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        if not identity["user_id"] and not logged_missing_header:
            _logger.debug(
                "Missing LazyCat identity headers; request allowed for local/dev compatibility."
            )
            logged_missing_header = True

        return await call_next(request)
