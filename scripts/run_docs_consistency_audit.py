#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_doc_sync as DOC_SYNC
from check_docs import check_docs


def build_audit_report(repo_root: Path) -> dict[str, Any]:
    doc_sync_result = DOC_SYNC.evaluate_doc_sync(repo_root)
    docs_errors = check_docs(repo_root)
    matched_rules = []
    rules = DOC_SYNC.load_doc_sync_rules(repo_root)
    for rule_id in doc_sync_result.matched_rule_ids:
        rule = rules.get(rule_id)
        matched_rules.append({"id": rule_id, "required_docs": list(rule.required_docs) if rule else []})
    checks = {
        "docs_checks": {"status": "pass" if not docs_errors else "fail", "errors": list(docs_errors)},
        "doc_sync": {"status": "pass" if not doc_sync_result.errors else "fail", "errors": list(doc_sync_result.errors), "matched_rule_ids": list(doc_sync_result.matched_rule_ids), "matched_rules": matched_rules, "changed_paths": list(doc_sync_result.changed_paths)},
    }
    overall_status = "pass" if all(check["status"] == "pass" for check in checks.values()) else "fail"
    return {"generated_at": datetime.now(UTC).isoformat(), "overall_status": overall_status, "checks": checks}


def render_markdown(report: dict[str, Any]) -> str:
    checks = report["checks"]
    doc_sync = checks["doc_sync"]
    docs_checks = checks["docs_checks"]
    lines = ["# Docs Consistency Audit", "", f"- generated at: `{report['generated_at']}`", f"- overall status: `{report['overall_status']}`", f"- docs checks: `{docs_checks['status']}`", f"- doc sync: `{doc_sync['status']}`"]
    if doc_sync["matched_rule_ids"]:
        lines.append(f"- matched doc sync rules: {', '.join(doc_sync['matched_rule_ids'])}")
    else:
        lines.append("- matched doc sync rules: (none)")
    if docs_checks["errors"]:
        lines.extend(["", "## docs_checks errors"])
        lines.extend(f"- {error}" for error in docs_checks["errors"])
    if doc_sync["errors"]:
        lines.extend(["", "## doc_sync errors"])
        lines.extend(f"- {error}" for error in doc_sync["errors"])
    return "\n".join(lines).strip() + "\n"


def write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run docs structure/path checks and direct doc-sync as one audit.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="stdout format when no explicit output file is requested")
    parser.add_argument("--json-out", help="Optional file path to write the full JSON report.")
    parser.add_argument("--md-out", help="Optional file path to write the Markdown summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_audit_report(Path.cwd())
    markdown = render_markdown(report)
    json_payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        write_output(Path(args.json_out), json_payload)
    if args.md_out:
        write_output(Path(args.md_out), markdown)
    if args.format == "json":
        print(json_payload, end="")
    else:
        print(markdown, end="")
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
