#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_docs_common import (
    extract_markdown_targets,
    extract_repo_path_candidates,
    load_docs_check_config,
    path_or_glob_exists,
    resolve_local_target_path,
)


def check_docs_paths(repo_root: Path) -> list[str]:
    errors: list[str] = []
    config = load_docs_check_config(repo_root)

    for rel_path in config.get("path_consistency_docs", []):
        path = repo_root / rel_path
        if not path.exists():
            errors.append(f"path consistency source is missing: {rel_path}")
            continue

        text = path.read_text(encoding="utf-8")

        for target in extract_markdown_targets(text):
            if target.startswith(("http://", "https://", "/lzcapp/", "/Applications/", "$CODEX_HOME/")):
                continue
            resolved = resolve_local_target_path(path, target)
            if not resolved.exists():
                errors.append(
                    f"{rel_path} references missing local markdown target `{target}`"
                )

        for candidate in sorted(extract_repo_path_candidates(text)):
            if not path_or_glob_exists(repo_root, candidate):
                errors.append(
                    f"{rel_path} references missing repo path `{candidate}`"
                )

    return errors


def main() -> int:
    errors = check_docs_paths(Path.cwd())
    if errors:
        for error in errors:
            print(f"[docs-paths] ERROR: {error}", file=sys.stderr)
        return 1
    print("docs paths ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
