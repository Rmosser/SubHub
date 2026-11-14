#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

source scripts/_lib_instance.sh
instance_parse_args "$@"

FRONTEND_DIR="$ROOT/frontend"
FRONTEND_DIST_DIR="$ROOT/app/static/frontend/dist"
FRONTEND_DIST_INDEX="$FRONTEND_DIST_DIR/index.html"

mkdir -p "$(dirname "$LOG_FILE")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "missing .venv (create it first): python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Keep both for compatibility with different runtimes.
export INSTANCE="$INSTANCE"
export LZCTOCLASH_INSTANCE="$INSTANCE"

frontend_inputs_newer_than_dist() {
  local dist_index="$1"

  if [[ -d "$FRONTEND_DIR/src" ]] && [[ -n "$(find "$FRONTEND_DIR/src" -type f -newer "$dist_index" -print -quit)" ]]; then
    return 0
  fi

  if [[ -n "$(find "$FRONTEND_DIR" -maxdepth 1 -type f \( \
    -name 'package.json' -o \
    -name 'package-lock.json' -o \
    -name 'vite.config.ts' -o \
    -name 'tsconfig*.json' \
  \) -newer "$dist_index" -print -quit)" ]]; then
    return 0
  fi

  return 1
}

ensure_frontend_dist() {
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "missing frontend/node_modules (run: cd frontend && npm install)" >&2
    exit 1
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "missing npm (install Node.js/npm first)" >&2
    exit 1
  fi

  if ! command -v node >/dev/null 2>&1; then
    echo "missing node (install Node.js 24 first)" >&2
    exit 1
  fi

  required_node_major="$(tr -d '[:space:]' < "$ROOT/.nvmrc")"
  current_node_major="$(node -p 'process.versions.node.split(".")[0]')"
  if [[ "$current_node_major" != "$required_node_major" ]]; then
    echo "node version mismatch: expected $(cat "$ROOT/.nvmrc"), got $(node -v)" >&2
    echo "hint: nvm install $(cat "$ROOT/.nvmrc") && nvm use" >&2
    exit 1
  fi

  if [[ ! -f "$FRONTEND_DIST_INDEX" ]]; then
    echo "frontend dist missing, building..."
    (cd "$FRONTEND_DIR" && npm run build)
    return
  fi

  if frontend_inputs_newer_than_dist "$FRONTEND_DIST_INDEX"; then
    echo "frontend sources newer than dist, rebuilding..."
    (cd "$FRONTEND_DIR" && npm run build)
    return
  fi

  echo "frontend dist up to date, skipping build"
}

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    if ! process_identity_matches "$old_pid"; then
      echo "refusing to reuse pidfile with mismatched process identity: $PID_FILE" >&2
      exit 2
    fi
    echo "instance already running: $INSTANCE (pid=$old_pid)" >&2
    echo "log: $LOG_FILE" >&2
    exit 0
  else
    rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
  fi
fi

ensure_frontend_dist

nohup .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info >"$LOG_FILE" 2>&1 < /dev/null &
pid="$!"
echo "$pid" >"$PID_FILE"
if ! write_process_identity "$pid"; then
  kill "$pid" >/dev/null 2>&1 || true
  rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
  echo "unable to record process identity" >&2
  exit 2
fi

echo "started: instance=$INSTANCE host=$HOST port=$PORT pid=$pid"
echo "log: $LOG_FILE"

# Fail fast if child exits immediately.
sleep 0.2
if ! kill -0 "$pid" >/dev/null 2>&1; then
  echo "startup failed: process exited early (pid=$pid)" >&2
  rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
  tail -n 120 "$LOG_FILE" >&2 || true
  exit 2
fi
