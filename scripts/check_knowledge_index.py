#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_docs_common import load_docs_check_config


def check_knowledge_index(repo_root: Path) -> list[str]:
    errors: list[str] = []
    config = load_docs_check_config(repo_root)

    docs_index_path = repo_root / "docs/index.md"
    docs_index_text = docs_index_path.read_text(encoding="utf-8")

    for target in config.get("required_index_targets", []):
        if target not in docs_index_text:
            errors.append(
                f"docs/index.md is missing required index target `{target}`"
            )

    for rule in config.get("required_discoverability", []):
        source_path = repo_root / rule["source"]
        if not source_path.exists():
            errors.append(f"discoverability source is missing: {rule['source']}")
            continue
        source_text = source_path.read_text(encoding="utf-8")
        normalized_source_text = unquote(source_text)
        for required in rule.get("must_mention_all", []):
            if required not in normalized_source_text:
                errors.append(
                    f"{rule['source']} is missing required discoverability reference `{required}`"
                )

    return errors


def main() -> int:
    errors = check_knowledge_index(Path.cwd())
    if errors:
        for error in errors:
            print(f"[knowledge-index] ERROR: {error}", file=sys.stderr)
        return 1
    print("knowledge index ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
