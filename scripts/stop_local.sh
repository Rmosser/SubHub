#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

source scripts/_lib_instance.sh
instance_parse_args "$@"

if [[ ! -f "$PID_FILE" ]]; then
  echo "no pidfile: $PID_FILE"
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
pid="${pid//[[:space:]]/}"
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
  echo "empty pidfile: $PID_FILE" >&2
  rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
  exit 0
fi

if ! kill -0 "$pid" >/dev/null 2>&1; then
  echo "process not running (pid=$pid); removing pidfile"
  rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
  exit 0
fi

if ! process_identity_matches "$pid"; then
  echo "refusing to stop pid with mismatched process identity: pid=$pid; preserving pid evidence" >&2
  exit 2
fi

echo "stopping: instance=$INSTANCE pid=$pid"
if ! kill -0 "$pid" >/dev/null 2>&1 || ! process_identity_matches "$pid"; then
  echo "pid identity changed before TERM; preserving pid evidence" >&2
  exit 2
fi
kill "$pid" >/dev/null 2>&1 || true

for _ in $(seq 1 50); do
  if kill -0 "$pid" >/dev/null 2>&1; then
    sleep 0.1
    continue
  fi
  rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
  echo "stopped: instance=$INSTANCE"
  exit 0
done

echo "still running after 5s, sending SIGKILL: pid=$pid" >&2
if ! kill -0 "$pid" >/dev/null 2>&1 || ! process_identity_matches "$pid"; then
  echo "pid identity changed before SIGKILL; preserving pid evidence" >&2
  exit 2
fi
kill -9 "$pid" >/dev/null 2>&1 || true
if ! kill -0 "$pid" >/dev/null 2>&1; then
  rm -f "$PID_FILE" "$PID_IDENTITY_FILE"
else
  echo "process still running after SIGKILL; preserving pid evidence" >&2
  exit 2
fi
echo "stopped: instance=$INSTANCE"
