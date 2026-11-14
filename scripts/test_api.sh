#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mark_expr="api"
if [[ "${1:-}" == "-m" && $# -ge 2 ]]; then
  mark_expr="api and (${2})"
  shift 2
fi

./.venv/bin/python -m pytest -m "$mark_expr" "$@"
