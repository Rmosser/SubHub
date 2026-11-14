#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from urllib.parse import unquote


CONFIG_PATH = Path("docs/governance/docs-check-config.json")

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
RAW_PATH_RE = re.compile(
    r"(?<![\w/.$-])("
    r"(?:app|frontend|scripts|docs)/[^\s`<>()\"']+"
    r"|AGENTS\.md"
    r"|README\.md"
    r"|CONTRIBUTING\.md"
    r"|DESIGN\.md"
    r"|\.env\.example"
    r"|lzc-[^\s`<>()\"']+\.yml"
    r")"
)

REPO_LOCAL_PREFIXES = ("app/", "frontend/", "scripts/", "docs/")
REPO_LOCAL_FILES = {"AGENTS.md", "README.md", "CONTRIBUTING.md", "DESIGN.md", ".env.example"}


def load_docs_check_config(repo_root: Path) -> dict:
    return json.loads((repo_root / CONFIG_PATH).read_text(encoding="utf-8"))


def is_excluded(path: str, exclude_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude_globs)


def iter_markdown_files(repo_root: Path, exclude_globs: list[str]) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.md"):
        rel = path.relative_to(repo_root).as_posix()
        if is_excluded(rel, exclude_globs):
            continue
        files.append(path)
    return sorted(files)


def normalize_markdown_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("#"):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return None
    target = target.split("#", 1)[0].strip()
    target = unquote(target)
    return target or None


def resolve_local_target(source_file: Path, target: str, repo_root: Path) -> Path:
    if target.startswith("/"):
        return Path(target)
    return (source_file.parent / target).resolve().relative_to(repo_root.resolve()) and (source_file.parent / target).resolve()


def resolve_local_target_path(source_file: Path, target: str) -> Path:
    if target.startswith("/"):
        return Path(target)
    return (source_file.parent / target).resolve()


def extract_markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw_target in MARKDOWN_LINK_RE.findall(text):
        normalized = normalize_markdown_target(raw_target)
        if normalized:
            targets.append(normalized)
    return targets


def _candidate_is_repo_local(value: str) -> bool:
    if value in REPO_LOCAL_FILES:
        return True
    if value.startswith(REPO_LOCAL_PREFIXES):
        return True
    if value.startswith("lzc-") and value.endswith(".yml"):
        return True
    return False


def normalize_repo_candidate(raw_value: str) -> str | None:
    value = raw_value.strip().strip(",.;")
    if not value:
        return None
    value = unquote(value)
    if value.startswith(("http://", "https://", "/lzcapp/", "/Applications/", "$CODEX_HOME/")):
        return None
    if ":" in value:
        maybe_path, maybe_line = value.split(":", 1)
        if _candidate_is_repo_local(maybe_path) and re.fullmatch(r"[0-9][0-9\-,:]*", maybe_line):
            value = maybe_path
    if _candidate_is_repo_local(value):
        return value
    return None


def extract_repo_path_candidates(text: str) -> set[str]:
    candidates: set[str] = set()
    text_without_links = MARKDOWN_LINK_RE.sub("", text)
    text_without_links_or_code = INLINE_CODE_RE.sub("", text_without_links)

    for raw in RAW_PATH_RE.findall(text_without_links_or_code):
        normalized = normalize_repo_candidate(raw)
        if normalized:
            candidates.add(normalized)

    for raw in INLINE_CODE_RE.findall(text_without_links):
        normalized = normalize_repo_candidate(raw)
        if normalized:
            candidates.add(normalized)
            continue
        for token in RAW_PATH_RE.findall(raw):
            normalized = normalize_repo_candidate(token)
            if normalized:
                candidates.add(normalized)

    return candidates


def path_or_glob_exists(repo_root: Path, candidate: str) -> bool:
    if "*" in candidate:
        return any(repo_root.glob(candidate))
    return (repo_root / candidate).exists()
