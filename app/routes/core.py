from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.routes.management import _require_login_if_needed, _services

router = APIRouter(prefix="/api/core", tags=["core"])


class CoreSyncPayload(BaseModel):
    target: Literal["all", "rules", "source"]
    source_id: str = ""
    rule_catalog_mode: Literal["incremental", "full"] = "incremental"


@router.get("/state")
async def get_core_state(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return _services(request).core_facade.build_state()


@router.post("/preview")
async def preview_core_patch(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _require_login_if_needed(request)
    return _services(request).core_facade.preview_patch(payload)


@router.post("/apply")
async def apply_core_patch(request: Request, payload: dict[str, object]) -> dict[str, object]:
    _require_login_if_needed(request)
    return _services(request).core_facade.apply_patch(payload)


@router.get("/explain/domain")
async def explain_core_domain(
    request: Request,
    domain: str = Query(...),
    device: str = Query(...),
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return await _services(request).core_facade.explain_domain(domain, device_token=device)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/explain/category")
async def explain_core_category(
    request: Request,
    name: str = Query(...),
    device: str = Query(...),
) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return await _services(request).core_facade.explain_category(name, device_token=device)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/diagnose/egress")
async def diagnose_core_egress(request: Request) -> dict[str, object]:
    _require_login_if_needed(request)
    return await _services(request).core_facade.diagnose_egress()


@router.get("/diagnose/source/{source_id}")
async def diagnose_core_source(request: Request, source_id: str) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        return await _services(request).core_facade.diagnose_source(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sync")
async def sync_core(request: Request, payload: CoreSyncPayload) -> dict[str, object]:
    _require_login_if_needed(request)
    try:
        result = await _services(request).core_facade.sync(
            target=payload.target,
            source_id=payload.source_id,
            rule_catalog_mode=payload.rule_catalog_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("ok") is False:
        return JSONResponse(status_code=502, content=result)
    return result
