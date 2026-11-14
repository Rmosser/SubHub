#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

source scripts/_lib_instance.sh
instance_parse_args "$@"

BASE_URL="http://${HOST}:${PORT}"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "missing .venv python: .venv/bin/python" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "missing curl" >&2
  exit 1
fi

req_id="doctor-${INSTANCE}-$(date -u +%Y%m%dT%H%M%SZ)-$$"

tmp_ready="$(mktemp)"
tmp_diag="$(mktemp)"
tmp_metrics="$(mktemp)"
trap 'rm -f "$tmp_ready" "$tmp_diag" "$tmp_metrics"' EXIT

ready_code="$(
  curl -sS -H "X-Request-Id: ${req_id}" -o "$tmp_ready" -w "%{http_code}" \
    "${BASE_URL}/readyz" || true
)"

if [[ "$ready_code" != "200" ]]; then
  echo "/readyz returned ${ready_code}" >&2
  cat "$tmp_ready" >&2 || true
  echo >&2
  echo "GET /diagnostics:" >&2
  curl -sS -o "$tmp_diag" "${BASE_URL}/diagnostics" || true
  cat "$tmp_diag" >&2 || true
  exit 2
fi

.venv/bin/python -c '
import json, sys
instance = sys.argv[1]
path = sys.argv[2]
payload = json.load(open(path, "r", encoding="utf-8"))
assert payload.get("ok") is True, payload
assert payload.get("service") == "subhub", payload
assert payload.get("instance") == instance, payload
assert "server_time_utc" in payload, payload
checks = payload.get("checks") or {}
assert "storage_root_writable" in checks, payload
assert checks["storage_root_writable"].get("ok") is True, payload
print("readyz ok")
' "$INSTANCE" "$tmp_ready"

curl -sS -o "$tmp_diag" "${BASE_URL}/diagnostics" >/dev/null
curl -sS -o "$tmp_metrics" "${BASE_URL}/metrics" >/dev/null

if ! rg -q "subhub_http_requests_total" "$tmp_metrics"; then
  echo "missing metric: subhub_http_requests_total" >&2
  head -n 60 "$tmp_metrics" >&2 || true
  exit 3
fi

if [[ ! -f "$LOG_FILE" ]]; then
  echo "missing log file: $LOG_FILE" >&2
  exit 4
fi

tail -n 500 "$LOG_FILE" | .venv/bin/python -c '
import json, sys
req_id = sys.argv[1]
for raw in sys.stdin:
    line = raw.strip()
    if not line.startswith("{"):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    if obj.get("request_id") == req_id:
        assert obj.get("path") == "/readyz", obj
        assert obj.get("status_code") == 200, obj
        print("log json ok")
        raise SystemExit(0)
raise SystemExit(1)
' "$req_id"

echo "doctor ok: instance=$INSTANCE host=$HOST port=$PORT"
