from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.i18n import resolve_locale

router = APIRouter(tags=["setup"])
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _user_id(request: Request) -> str:
    user_id = str(getattr(request.state, "lazycat_user_id", "") or "").strip()
    registry = request.app.state.tenant_registry
    if registry.settings.manage_api_require_login and not user_id:
        raise HTTPException(status_code=401, detail="lazycat login required")
    return user_id


@router.get("/api/setup/status")
async def setup_status(request: Request) -> dict[str, Any]:
    status = request.app.state.tenant_registry.status(_user_id(request))
    return {**status, "initialized": not status["setup_required"]}


@router.post("/api/setup/init")
async def setup_init(request: Request) -> dict[str, Any]:
    services = request.app.state.tenant_registry.initialize(_user_id(request))
    await request.app.state.tenant_registry.ensure_started(services)
    devices = services.repo.list_device_subscriptions()
    device = next((item for item in devices if item.device_key == "default"), devices[0] if devices else None)
    return {
        "ok": True,
        "setup_required": False,
        "initialized": True,
        "device_token": device.token if device else "",
        "device_public_id": device.public_id if device else "",
    }


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    status = request.app.state.tenant_registry.status(_user_id(request))
    if not status["setup_required"]:
        return RedirectResponse("/manage", status_code=302)
    return _templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"english": resolve_locale(request) == "en-US"},
    )
