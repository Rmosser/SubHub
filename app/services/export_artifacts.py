from __future__ import annotations

import io
import re
import zipfile
from typing import Any

from app.services.subscription_builder import build_clash_audit_markdown


def ascii_filename(name: str, suffix: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "-", str(name or "").strip())
    stem = re.sub(r"-{2,}", "-", stem).strip("-.")
    if not stem:
        stem = "subhub"
    return f"{stem}{suffix}"


def bundle_zip_bytes(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(path, files[path])
    return output.getvalue()


def attach_clash_bundle_audit(
    bundle: dict[str, Any],
    *,
    profile: str,
    base_url: str,
    warnings: list[object] | None = None,
    blockers: list[object] | None = None,
) -> dict[str, Any]:
    output = dict(bundle)
    files = dict(output.get("files") or {})
    files["AUDIT.md"] = build_clash_audit_markdown(
        output,
        profile=profile,
        base_url=base_url,
        warnings=list(warnings or output.get("warnings") or []),
        blockers=list(blockers or output.get("blockers") or []),
    )
    output["files"] = files
    return output
