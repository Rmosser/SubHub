#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_docs_links import check_docs_links
from check_docs_paths import check_docs_paths
from check_docs_structure import check_docs_structure
from check_knowledge_index import check_knowledge_index


def check_docs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    checks = [("docs-structure", check_docs_structure), ("docs-links", check_docs_links), ("knowledge-index", check_knowledge_index), ("docs-paths", check_docs_paths)]
    for name, fn in checks:
        for error in fn(repo_root):
            errors.append(f"[{name}] {error}")
    return errors


def main() -> int:
    errors = check_docs(Path.cwd())
    if errors:
        for error in errors:
            print(f"[docs-checks] ERROR: {error}", file=sys.stderr)
        return 1
    print("docs checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
