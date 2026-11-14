from __future__ import annotations

import asyncio
from pathlib import Path

from app.routes import ui


def test_manage_spa_falls_back_to_backend_shell_when_frontend_dist_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ui, "_FRONTEND_DIST", tmp_path / "missing-dist")

    response = asyncio.run(ui.manage_spa())

    assert response.status_code == 200
    assert b"SubHub Console" in response.body
    assert b"/manage/assets/" in response.body
    assert b"frontend bundle is not available" in response.body
    assert response.headers["cache-control"] == "no-cache"


def test_manage_spa_shell_is_revalidated_on_every_load(client, monkeypatch, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<script type="module" src="/manage/assets/index-abc123.js"></script>')
    monkeypatch.setattr(ui, "_FRONTEND_DIST", dist)

    response = client.get("/manage/catalog")

    assert response.status_code == 200
    assert "/manage/assets/index-abc123.js" in response.text
    # A cached shell would keep requesting lazy chunks that a later deploy removed.
    assert response.headers["cache-control"] == "no-cache"
