from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_doc_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_doc_sync", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()
MATRIX_PAYLOAD = {"version": 2, "rules": [{"id": "api-surface", "changed_paths": ["app/routes/**/*.py", "app/cli/**/*.py"], "required_docs": ["docs/api/http-api.md"]}, {"id": "subscription-contract", "changed_paths": ["app/services/subscription_builder.py"], "required_docs": ["docs/api/subscription-output-contract.md"]}]}


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True)


def _write(repo_root: Path, relative_path: str, content: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.name", "Test User")
    _git(repo_root, "config", "user.email", "test@example.com")
    files = {"docs/doc-sync-rules.json": json.dumps(MATRIX_PAYLOAD, ensure_ascii=False, indent=2) + "\n", "app/routes/management.py": "ROUTE = 'v1'\n", "docs/api/http-api.md": "# HTTP API\n", "app/services/subscription_builder.py": "BUILDER = 'v1'\n", "docs/api/subscription-output-contract.md": "# Output Contract\n"}
    for path, content in files.items():
        _write(repo_root, path, content)
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "baseline")
    return repo_root


def test_doc_sync_passes_when_required_doc_changes(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _write(repo_root, "app/routes/management.py", "ROUTE = 'v2'\n")
    _write(repo_root, "docs/api/http-api.md", "# HTTP API v2\n")
    result = MODULE.evaluate_doc_sync(repo_root)
    assert result.matched_rule_ids == ("api-surface",)
    assert result.errors == ()


def test_doc_sync_fails_when_required_doc_does_not_change(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _write(repo_root, "app/routes/management.py", "ROUTE = 'v2'\n")
    result = MODULE.evaluate_doc_sync(repo_root)
    assert any("requires synchronized doc `docs/api/http-api.md`" in error for error in result.errors)


def test_doc_sync_requires_all_docs_for_multiple_rules(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _write(repo_root, "app/routes/management.py", "ROUTE = 'v2'\n")
    _write(repo_root, "app/services/subscription_builder.py", "BUILDER = 'v2'\n")
    _write(repo_root, "docs/api/http-api.md", "# HTTP API v2\n")
    result = MODULE.evaluate_doc_sync(repo_root)
    assert result.matched_rule_ids == ("api-surface", "subscription-contract")
    assert any("docs/api/subscription-output-contract.md" in error for error in result.errors)


def test_doc_sync_passes_for_docs_only_change(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _write(repo_root, "docs/api/http-api.md", "# HTTP API docs only\n")
    result = MODULE.evaluate_doc_sync(repo_root)
    assert result.matched_rule_ids == ()
    assert result.errors == ()


def test_collect_changed_tracked_files_honors_explicit_base(tmp_path: Path, monkeypatch) -> None:
    repo_root = _init_repo(tmp_path)
    _git(repo_root, "checkout", "-b", "feature")
    _write(repo_root, "app/routes/management.py", "ROUTE = 'v2'\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "feature")
    _write(repo_root, "docs/api/http-api.md", "# HTTP API v2\n")
    monkeypatch.setenv("SUBHUB_DIFF_BASE_REF", "main")
    changed = MODULE.collect_changed_tracked_files(repo_root)
    assert "app/routes/management.py" in changed
    assert "docs/api/http-api.md" in changed


def test_match_rule_ids_supports_double_star_patterns() -> None:
    rules = {"api": MODULE.DocSyncRule(rule_id="api", changed_paths=("app/routes/**/*.py",), required_docs=("docs/api/http-api.md",))}
    assert MODULE.match_rule_ids(("app/routes/management.py",), rules) == ("api",)
    assert MODULE.match_rule_ids(("app/routes/admin/users.py",), rules) == ("api",)
