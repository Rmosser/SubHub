#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

source scripts/_lib_instance.sh
instance_parse_args "$@"

if [[ ! -f ".env" ]]; then
  echo "missing .env (copy from .env.example first)" >&2
  exit 1
fi

# Guard: APP_NAME with spaces must be quoted to be source-able.
if rg -n '^APP_NAME=[^"\047].* .+' .env >/dev/null 2>&1; then
  echo "invalid .env: APP_NAME contains spaces but is not quoted." >&2
  echo "fix: APP_NAME=\"LZC Relay Subscription\"" >&2
  exit 1
fi

bash scripts/local_stop.sh "$@" >/dev/null 2>&1 || true

existing_listener_pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"
if [[ -n "${existing_listener_pids//[[:space:]]/}" ]]; then
  echo "port ${PORT} is already occupied by another process:" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  echo "please stop it first, then rerun scripts/local_start.sh" >&2
  exit 3
fi

bash scripts/run_local.sh "$@"

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
pid="${pid//[[:space:]]/}"

max_wait_seconds=30
root_code="000"
manage_code="000"

for _ in $(seq 1 "$max_wait_seconds"); do
  if [[ -z "$pid" ]] || ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "startup failed: process exited before becoming ready (pid=${pid:-unknown})" >&2
    echo "tail ${LOG_FILE}:" >&2
    tail -n 120 "$LOG_FILE" >&2 || true
    exit 2
  fi

  root_code="$(curl -s --max-time 2 -o /dev/null -w "%{http_code}" "http://${HOST}:${PORT}/" || true)"
  manage_code="$(curl -s --max-time 2 -o /dev/null -w "%{http_code}" "http://${HOST}:${PORT}/manage" || true)"
  if [[ "$manage_code" == "200" ]] && [[ "$root_code" == "200" || "$root_code" == "302" ]]; then
    break
  fi
  sleep 1
done

echo "GET / -> ${root_code}"
echo "GET /manage -> ${manage_code}"
if [[ "$manage_code" != "200" ]] || [[ "$root_code" != "200" && "$root_code" != "302" ]]; then
  echo "startup timeout after ${max_wait_seconds}s" >&2
  echo "tail ${LOG_FILE}:" >&2
  tail -n 120 "$LOG_FILE" >&2 || true
  exit 2
fi
