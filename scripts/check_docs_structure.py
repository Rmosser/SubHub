#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_docs_common import CONFIG_PATH, load_docs_check_config


def check_docs_structure(repo_root: Path) -> list[str]:
    errors: list[str] = []
    config = load_docs_check_config(repo_root)
    for rel_path in config.get("required_files", []):
        if not (repo_root / rel_path).exists():
            errors.append(f"missing required docs file: {rel_path}")
    docs_index = repo_root / "docs/index.md"
    if docs_index.exists():
        heading = docs_index.read_text(encoding="utf-8")
        if "# Documentation Index" not in heading:
            errors.append("docs/index.md is missing the expected title")
    else:
        errors.append("missing docs/index.md")
    for rel_path in (CONFIG_PATH.as_posix(), "docs/doc-sync-rules.json", "docs/quality.md"):
        if not (repo_root / rel_path).exists():
            errors.append(f"required docs structure target is missing: {rel_path}")
    return errors


def main() -> int:
    errors = check_docs_structure(Path.cwd())
    if errors:
        for error in errors:
            print(f"[docs-structure] ERROR: {error}", file=sys.stderr)
        return 1
    print("docs structure ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
