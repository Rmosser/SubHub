from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.i18n import localize_egress_payload, resolve_locale
from app.services.runtime_observability import REQUIRED_RUNTIME_TASKS
from app.services.tenant_registry import request_services

router = APIRouter(tags=["internal"])

SERVICE_NAME = "subhub"

# Keep the internal service label explicit in health payloads.


def _services(request: Request):
    return request_services(request)


def _instance_name() -> str:
    return str(os.getenv("SUBHUB_INSTANCE", "") or os.getenv("INSTANCE", "")).strip()


def _is_storage_root_writable(storage_root: str) -> bool:
    try:
        root = Path(storage_root)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(root), prefix=".writable_check_", delete=True):
            pass
        return True
    except Exception:
        return False


def _process_rss_mb() -> float | None:
    try:
        content = Path("/proc/self/statm").read_text(encoding="utf-8").strip()
        parts = content.split()
        if len(parts) < 2:
            return None
        rss_pages = int(parts[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round((rss_pages * page_size) / (1024 * 1024), 2)
    except Exception:
        return None


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "tenant_registry", None)
    # In tenant mode healthz is public.  Keep anonymous requests to instance
    # liveness, while an authenticated request may receive the selected
    # service's sanitized runtime projection.
    if (
        registry is not None
        and registry.settings.manage_api_require_login
        and not str(getattr(request.state, "lazycat_user_id", "") or "").strip()
    ):
        return {
            "ok": True,
            "service": SERVICE_NAME,
            "instance": _instance_name(),
            "server_time_utc": datetime.now(timezone.utc).isoformat(),
            "setup_required": not registry.status("")["instance_initialized"],
            "access_mode": registry.status("")["access_mode"],
        }
    services = _services(request)
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "instance": _instance_name(),
        "process_rss_mb": _process_rss_mb(),
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_tasks": services.runtime_monitor.public_snapshot(),
        "runtime_alerts": services.runtime_alerts.readiness(),
        # healthz is anonymous; never expose the authenticated management
        # projection, which includes the configured repository URL and
        # diagnostic text.
        "policy_backup": services.policy_backup.status().to_public_dict(),
    }


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, Any]:
    payload = await _ready_payload(request)
    if payload["ok"]:
        return payload
    return JSONResponse(payload, status_code=503)


async def _ready_payload(request: Request) -> dict[str, Any]:
    services = _services(request)
    storage_ok = _is_storage_root_writable(services.settings.storage_root)
    try:
        # SQLite checkpoint/integrity work can involve an old reader or a
        # large database.  Keep it off the event loop so /readyz cannot stop
        # resident heartbeats while the storage check is in progress.
        database = await asyncio.to_thread(services.repo.database_integrity)
    except Exception as exc:
        database = {"ok": False, "error": str(exc)}
    runtime = services.runtime_monitor.readiness(REQUIRED_RUNTIME_TASKS)
    alerts = services.runtime_alerts.readiness()
    policy_status = services.policy_backup.status().to_dict()
    policy_ok = (
        not bool(policy_status["enabled"])
        or (
            bool(policy_status["configured"])
            and not bool(policy_status["reconciliation_required"])
        )
    )
    payload = {
        "ok": bool(
            storage_ok
            and database.get("ok")
            and runtime.get("ok")
            and policy_ok
            and alerts.get("ok")
        ),
        "service": SERVICE_NAME,
        "instance": _instance_name(),
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "storage_root_writable": {
                "ok": storage_ok,
                "path": str(services.settings.storage_root),
            },
            "database": database,
            "runtime_tasks": runtime,
            "runtime_alerts": alerts,
            "policy_backup": {
                "ok": policy_ok,
                "item": policy_status,
            },
        },
    }
    return payload


@router.get("/diagnostics")
async def diagnostics(request: Request) -> dict[str, Any]:
    services = _services(request)
    locale = resolve_locale(request)
    egress = await services.egress_diagnostics.get_status(
        gorelay_source_count=len(services.gorelay_service.list_accounts()),
        force=True,
    )
    proxy_bridge = dict(egress.get("proxy_bridge") or {})
    egress["proxy_bridge"] = localize_egress_payload(proxy_bridge, locale)
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "instance": _instance_name(),
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "health": {
            **(await healthz(request)),
            "hub": services.hub_service.public_runtime(),
            "egress": egress,
        },
        # Keep diagnostics JSON-serializable even when /readyz returns a 503
        # response object to its HTTP caller.
        "ready": await _ready_payload(request),
    }


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
