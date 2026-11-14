"""Consistency checks for design/client-ui-replica (client settings UI inventory + HTML replicas).

These do not need Chrome or the local reference captures: they check that the committed
inventory and replica data are what the generators produce, that the vocabulary is closed,
and that obvious secrets did not slip into tracked files.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "design" / "client-ui-replica"
APPS = {
    "shadowrocket": "shadowrocket.py",
    "surge": "surge.py",
    "clash": "clash.py",
    "clash-mi": "clash_mi.py",
}
SUBHUB = {
    "writes": "写入",
    "partial": "只写一部分",
    "none": "不写",
    "device": "只在手机本机",
    "unverified": "还没核对",
    "na": "不适用（动作/导航）",
}
LAYERS = {"profile", "app", "action"}
SENSITIVE_LABEL = re.compile(r"secret|密码|password|uuid|口令|hwid|控制器密钥", re.I)
TRACKED_SUFFIXES = {".json", ".js", ".md", ".py", ".html", ".css", ".sh"}


def _rows(doc):
    for screen in doc["screens"]:
        for group in screen["groups"]:
            for row in group["rows"]:
                yield screen["id"], row


def _load(app: str):
    return json.loads((ROOT / "inventory" / f"{app}.json").read_text())


@pytest.mark.parametrize("app", sorted(APPS))
def test_inventory_vocabulary_is_closed(app):
    doc = _load(app)
    ids = [s["id"] for s in doc["screens"]]
    assert len(ids) == len(set(ids)), "screen ids must be unique"
    for screen_id, row in _rows(doc):
        where = f"{app}:{screen_id}:{row['label']}"
        assert row["subhub"] in SUBHUB, where
        assert row["subhub_zh"] == SUBHUB[row["subhub"]], where
        assert row["layer"] in LAYERS, where


@pytest.mark.parametrize("app", sorted(APPS))
def test_sensitive_rows_are_redacted(app):
    for screen_id, row in _rows(_load(app)):
        if SENSITIVE_LABEL.search(row["label"]) and row["control"] not in ("button", "toggle") and "value" in row:
            value = str(row["value"])
            assert "<redacted>" in value or value.startswith("空"), f"{app}:{screen_id}:{row['label']}"


def test_no_obvious_secrets_in_tracked_files():
    uuid = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
    email = re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
    sub_url = re.compile(r"https?://[^\s\"']*(token|sub\?|/sub/)[^\s\"']*", re.I)
    for path in ROOT.rglob("*"):
        if path.suffix not in TRACKED_SUFFIXES or "screens" in path.parts or "out" in path.parts:
            continue
        text = path.read_text()
        rel = path.relative_to(ROOT)
        assert not uuid.search(text), f"UUID-like value in {rel}"
        assert not email.search(text), f"email-like value in {rel}"
        assert not sub_url.search(text), f"subscription-like URL in {rel}"


def test_generators_reproduce_committed_inventory(tmp_path):
    env = {**os.environ, "UI_REPLICA_INVENTORY_OUT": str(tmp_path)}
    for app, script in APPS.items():
        subprocess.run([sys.executable, script], cwd=ROOT / "tools", env=env, check=True, capture_output=True)
        assert json.loads((tmp_path / f"{app}.json").read_text()) == _load(app), (
            f"inventory/{app}.json is stale: run `cd design/client-ui-replica/tools && ../../../.venv/bin/python {script}`"
        )


def test_build_data_reproduces_committed_replica_data(tmp_path):
    env = {**os.environ, "UI_REPLICA_DATA_OUT": str(tmp_path)}
    subprocess.run([sys.executable, str(ROOT / "replica" / "build_data.py")], env=env, check=True, capture_output=True)
    committed = sorted(p.name for p in (ROOT / "replica" / "data").glob("*.js"))
    assert sorted(p.name for p in tmp_path.glob("*.js")) == committed
    for name in committed:
        assert (tmp_path / name).read_text() == (ROOT / "replica" / "data" / name).read_text(), (
            f"replica/data/{name} is stale: run `./.venv/bin/python design/client-ui-replica/replica/build_data.py`"
        )
        page = ROOT / "replica" / name.replace(".js", ".html")
        assert page.exists(), f"missing replica page for {name}"
        ref = json.loads(re.sub(r"^window.REPLICA=|;\s*$", "", (ROOT / "replica" / "data" / name).read_text().strip()))[
            "reference"
        ]
        assert ref.startswith("../screens/"), "references must point at the local-only screens/ folder"
