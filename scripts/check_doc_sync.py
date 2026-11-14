#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MATRIX_PATH = Path("docs/doc-sync-rules.json")


@dataclass(frozen=True)
class DocSyncRule:
    rule_id: str
    changed_paths: tuple[str, ...]
    required_docs: tuple[str, ...]


@dataclass(frozen=True)
class DocSyncResult:
    changed_paths: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    errors: tuple[str, ...]


class DocSyncError(Exception):
    pass


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        raise DocSyncError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _resolve_base_ref(repo_root: Path) -> str | None:
    explicit = os.environ.get("SUBHUB_DIFF_BASE_REF", "").strip()
    github_base = os.environ.get("GITHUB_BASE_REF", "").strip()
    env_candidates: list[str] = []
    for value in (explicit, github_base):
        if not value:
            continue
        if value.startswith("origin/"):
            env_candidates.append(value)
        else:
            env_candidates.extend((f"origin/{value}", value))
    for candidate in env_candidates:
        result = subprocess.run(["git", "rev-parse", "--verify", candidate], cwd=repo_root, check=False, text=True, capture_output=True)
        if result.returncode == 0:
            return candidate
    for candidate in ("origin/main", "main"):
        result = subprocess.run(["git", "rev-parse", "--verify", candidate], cwd=repo_root, check=False, text=True, capture_output=True)
        if result.returncode == 0:
            return candidate
    return None


def collect_changed_tracked_files(repo_root: Path, base_ref: str | None = None) -> tuple[str, ...]:
    changed: set[str] = set()
    resolved_base = base_ref or _resolve_base_ref(repo_root)
    if resolved_base is not None:
        merge_base = _run_git(repo_root, "merge-base", "HEAD", resolved_base).strip()
        for raw in _run_git(repo_root, "diff", "--name-only", f"{merge_base}...HEAD").splitlines():
            path = raw.strip()
            if path:
                changed.add(path)
    for args in (("diff", "--name-only", "--cached"), ("diff", "--name-only")):
        for raw in _run_git(repo_root, *args).splitlines():
            path = raw.strip()
            if path:
                changed.add(path)
    return tuple(sorted(changed))


def load_doc_sync_rules(repo_root: Path) -> dict[str, DocSyncRule]:
    payload = json.loads((repo_root / MATRIX_PATH).read_text(encoding="utf-8"))
    rules: dict[str, DocSyncRule] = {}
    for item in payload.get("rules", []):
        rule = DocSyncRule(rule_id=str(item["id"]), changed_paths=tuple(str(pattern) for pattern in item["changed_paths"]), required_docs=tuple(str(path) for path in item["required_docs"]))
        rules[rule.rule_id] = rule
    return rules


def _pattern_variants(pattern: str) -> tuple[str, ...]:
    variants = {pattern}
    collapsed = pattern
    while "/**/" in collapsed:
        collapsed = collapsed.replace("/**/", "/")
        variants.add(collapsed)
    if pattern.endswith("/**"):
        variants.add(pattern[:-3] + "/*")
    return tuple(sorted(variants))


def _matches_pattern(path: str, pattern: str) -> bool:
    return any(fnmatch.fnmatchcase(path, variant) for variant in _pattern_variants(pattern))


def match_rule_ids(changed_paths: tuple[str, ...], rules: dict[str, DocSyncRule]) -> tuple[str, ...]:
    matched: list[str] = []
    for rule_id, rule in rules.items():
        if any(_matches_pattern(path, pattern) for path in changed_paths for pattern in rule.changed_paths):
            matched.append(rule_id)
    return tuple(sorted(matched))


def evaluate_doc_sync(repo_root: Path) -> DocSyncResult:
    changed_paths = collect_changed_tracked_files(repo_root)
    rules = load_doc_sync_rules(repo_root)
    matched_rule_ids = match_rule_ids(changed_paths, rules)
    errors: list[str] = []
    changed_set = set(changed_paths)
    for rule_id in matched_rule_ids:
        rule = rules[rule_id]
        for required_doc in rule.required_docs:
            if required_doc not in changed_set:
                errors.append(f"rule `{rule_id}` requires synchronized doc `{required_doc}` to change in the same diff")
    return DocSyncResult(changed_paths=changed_paths, matched_rule_ids=matched_rule_ids, errors=tuple(errors))


def main() -> int:
    try:
        result = evaluate_doc_sync(Path.cwd())
    except (DocSyncError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[doc-sync] ERROR: {exc}", file=sys.stderr)
        return 1
    if result.errors:
        for error in result.errors:
            print(f"[doc-sync] ERROR: {error}", file=sys.stderr)
        return 1
    if result.matched_rule_ids:
        print(f"doc sync ok: matched rules = {', '.join(result.matched_rule_ids)}")
    else:
        print("doc sync ok: no rules matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
