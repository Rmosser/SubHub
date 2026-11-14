#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d ".venv" ]]; then
  echo "missing .venv (create it first): python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo "missing .env (copy from .env.example first)" >&2
  exit 1
fi

set -a
source .env
set +a

echo "Starting local server for LazyCat devshell-local..."
echo "Bind: 0.0.0.0:8080 (box must reach your LAN IP)"
echo
echo "LAN IP helpers (pick one reachable by the box):"
echo "  macOS: ipconfig getifaddr en0"
echo "  Linux: hostname -I | awk '{print \$1}'"
echo
echo "Then run devshell:"
echo "  export DEV_LAN_IP=<your-lan-ip>"
echo "  lzc-cli project devshell -f -c lzc-build.devshell-local.yml --contentdir"
echo

exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --log-level debug
