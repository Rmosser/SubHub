from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


STRUCTURE = _load_module("check_docs_structure", SCRIPTS_DIR / "check_docs_structure.py")
LINKS = _load_module("check_docs_links", SCRIPTS_DIR / "check_docs_links.py")
INDEX = _load_module("check_knowledge_index", SCRIPTS_DIR / "check_knowledge_index.py")
ORCHESTRATOR = _load_module("check_docs", SCRIPTS_DIR / "check_docs.py")
AUDIT = _load_module("run_docs_consistency_audit", SCRIPTS_DIR / "run_docs_consistency_audit.py")
CONFIG = {"required_files": ["AGENTS.md", "README.md", "docs/index.md", "docs/quality.md", "docs/api/http-api.md", "docs/doc-sync-rules.json", "docs/plans/template.md", "docs/governance/docs-check-config.json"], "required_index_targets": ["README.md", "docs/quality.md", "docs/api/http-api.md", "docs/plans/template.md"], "required_discoverability": [{"source": "README.md", "must_mention_all": ["docs/index.md"]}, {"source": "AGENTS.md", "must_mention_all": ["docs/index.md", "docs/quality.md"]}], "path_consistency_docs": ["README.md", "AGENTS.md", "docs/index.md", "docs/quality.md"], "exclude_globs": ["docs/history/**"]}


def _write(repo_root: Path, relative_path: str, content: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    files = {"AGENTS.md": "# AGENTS\n`docs/index.md`\n`docs/quality.md`\n", "README.md": "# README\n`docs/index.md`\n", "docs/index.md": "# Documentation Index\n- `README.md`\n- `docs/quality.md`\n- `docs/api/http-api.md`\n- `docs/plans/template.md`\n", "docs/quality.md": "# Quality\n", "docs/api/http-api.md": "# API\n", "docs/plans/template.md": "# Optional Task Plan\n", "docs/doc-sync-rules.json": "{\"version\": 2, \"rules\": []}\n", "docs/governance/docs-check-config.json": json.dumps(CONFIG, ensure_ascii=False, indent=2) + "\n"}
    for path, content in files.items():
        _write(repo_root, path, content)
    return repo_root


def test_structure_requires_context_first_targets(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    (repo_root / "docs/quality.md").unlink()
    errors = STRUCTURE.check_docs_structure(repo_root)
    assert "missing required docs file: docs/quality.md" in errors
    assert "required docs structure target is missing: docs/quality.md" in errors


def test_links_reject_missing_local_target(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _write(repo_root, "README.md", "# README\n[missing](docs/missing.md)\n")
    errors = LINKS.check_docs_links(repo_root)
    assert any("links to missing local target `docs/missing.md`" in error for error in errors)


def test_index_requires_configured_targets(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _write(repo_root, "docs/index.md", "# Documentation Index\n- `README.md`\n")
    errors = INDEX.check_knowledge_index(repo_root)
    assert any("docs/quality.md" in error for error in errors)


def test_orchestrator_passes_for_valid_context_map(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    assert ORCHESTRATOR.check_docs(repo_root) == []


def test_audit_reports_direct_doc_sync_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(AUDIT.DOC_SYNC, "evaluate_doc_sync", lambda repo_root: AUDIT.DOC_SYNC.DocSyncResult(changed_paths=("README.md",), matched_rule_ids=(), errors=()))
    monkeypatch.setattr(AUDIT.DOC_SYNC, "load_doc_sync_rules", lambda repo_root: {})
    monkeypatch.setattr(AUDIT, "check_docs", lambda repo_root: [])
    report = AUDIT.build_audit_report(tmp_path)
    assert report["overall_status"] == "pass"
    assert report["checks"]["doc_sync"]["status"] == "pass"


def test_audit_reports_direct_doc_sync_failure(monkeypatch, tmp_path: Path) -> None:
    rule = AUDIT.DOC_SYNC.DocSyncRule(rule_id="api-surface", changed_paths=("app/routes/**/*.py",), required_docs=("docs/api/http-api.md",))
    monkeypatch.setattr(AUDIT.DOC_SYNC, "evaluate_doc_sync", lambda repo_root: AUDIT.DOC_SYNC.DocSyncResult(changed_paths=("app/routes/management.py",), matched_rule_ids=("api-surface",), errors=("missing synchronized doc",)))
    monkeypatch.setattr(AUDIT.DOC_SYNC, "load_doc_sync_rules", lambda repo_root: {"api-surface": rule})
    monkeypatch.setattr(AUDIT, "check_docs", lambda repo_root: [])
    report = AUDIT.build_audit_report(tmp_path)
    assert report["overall_status"] == "fail"
    assert report["checks"]["doc_sync"]["errors"] == ["missing synchronized doc"]
