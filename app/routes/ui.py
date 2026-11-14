from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

router = APIRouter(tags=["ui"])

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "static" / "frontend" / "dist"
# The shell names the current hashed bundles.  Make browsers revalidate it on
# every load (it is under 1 KB) so they never keep serving an old shell whose
# lazy chunks a later deploy has already removed.
_SHELL_HEADERS = {"Cache-Control": "no-cache"}


def _fallback_manage_shell() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>SubHub Console</title>
  </head>
  <body>
    <main>
      <h1>SubHub Console</h1>
      <p>The frontend bundle is not available in this environment yet.</p>
      <p>Build it with <code>cd frontend && npm install && npm run build</code>.</p>
      <p>When built, static assets are served from <code>/manage/assets/</code>.</p>
    </main>
  </body>
</html>
""".strip(),
        status_code=200,
        headers=_SHELL_HEADERS,
    )


@router.get("/", response_class=HTMLResponse)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/manage", status_code=302)


@router.get("/manage/{path:path}", response_class=HTMLResponse)
@router.get("/manage", response_class=HTMLResponse)
async def manage_spa(path: str = "") -> HTMLResponse:
    index = _FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html", headers=_SHELL_HEADERS)
    return _fallback_manage_shell()
