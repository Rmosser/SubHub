#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

source scripts/_lib_instance.sh
instance_parse_args "$@"

bash scripts/stop_local.sh "$@"

# Best-effort: show remaining listeners (if any).
lsof -nP -iTCP:"$PORT" -sTCP:LISTEN || true
