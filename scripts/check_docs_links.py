#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_docs_common import extract_markdown_targets, iter_markdown_files, load_docs_check_config, resolve_local_target_path


def check_docs_links(repo_root: Path) -> list[str]:
    errors: list[str] = []
    config = load_docs_check_config(repo_root)
    exclude_globs = list(config.get("exclude_globs", []))

    for doc_path in iter_markdown_files(repo_root, exclude_globs):
        rel_doc_path = doc_path.relative_to(repo_root).as_posix()
        text = doc_path.read_text(encoding="utf-8")
        for target in extract_markdown_targets(text):
            resolved = resolve_local_target_path(doc_path, target)
            if not resolved.exists():
                errors.append(
                    f"{rel_doc_path} links to missing local target `{target}`"
                )

    return errors


def main() -> int:
    errors = check_docs_links(Path.cwd())
    if errors:
        for error in errors:
            print(f"[docs-links] ERROR: {error}", file=sys.stderr)
        return 1
    print("docs links ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
