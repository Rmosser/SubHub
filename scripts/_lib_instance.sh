#!/usr/bin/env bash
set -euo pipefail

_instance_repo_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  (cd "$here/.." && pwd)
}

_instance_default_name() {
  basename "$(pwd)"
}

instance_parse_args() {
  INSTANCE="$(_instance_default_name)"
  HOST="127.0.0.1"
  PORT="8080"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --instance)
        INSTANCE="${2:-}"
        shift 2
        ;;
      --host)
        HOST="${2:-}"
        shift 2
        ;;
      --port)
        PORT="${2:-}"
        shift 2
        ;;
      -h|--help)
        echo "Usage: $0 [--instance <name>] [--host <host>] [--port <port>]" >&2
        exit 0
        ;;
      *)
        echo "Unknown arg: $1" >&2
        exit 2
        ;;
    esac
  done

  if [[ -z "${INSTANCE}" ]]; then
    echo "--instance cannot be empty" >&2
    exit 2
  fi
  if ! [[ "${INSTANCE}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$ ]]; then
    echo "--instance must be a short slug (letters, digits, '_' or '-'); refusing path traversal" >&2
    exit 2
  fi
  if [[ -z "${HOST}" ]]; then
    echo "--host cannot be empty" >&2
    exit 2
  fi
  if ! [[ "${PORT}" =~ ^[0-9]+$ ]]; then
    echo "--port must be an integer, got: ${PORT}" >&2
    exit 2
  fi
  if (( PORT < 1 || PORT > 65535 )); then
    echo "--port must be between 1 and 65535" >&2
    exit 2
  fi

  LOG_DIR="$(_instance_repo_root)/var/logs"
  LOG_FILE="${LOG_DIR}/${INSTANCE}-app.log"
  PID_FILE="${LOG_DIR}/${INSTANCE}-app.pid"
  PID_IDENTITY_FILE="${PID_FILE}.identity"
}

process_start_time() {
  ps -o lstart= -p "$1" 2>/dev/null | sed -e 's/^ *//' | head -n 1
}

process_command_hash() {
  local command
  command="$(ps -o command= -p "$1" 2>/dev/null | sed -e 's/^ *//' | head -n 1)"
  [[ -n "$command" ]] || return 1
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$command" | shasum -a 256 | awk '{print $1}'
  else
    printf '%s' "$command" | sha256sum | awk '{print $1}'
  fi
}

write_process_identity() {
  local pid="$1" start_time command_hash
  start_time="$(process_start_time "$pid")"
  command_hash="$(process_command_hash "$pid")"
  [[ -n "$start_time" && -n "$command_hash" ]] || return 1
  umask 077
  local tmp_file="${PID_IDENTITY_FILE}.tmp.$$"
  printf 'pid_start_time=%s\npid_command_hash=%s\n' "$start_time" "$command_hash" >"$tmp_file"
  mv -f "$tmp_file" "$PID_IDENTITY_FILE"
}

process_identity_matches() {
  local pid="$1" expected_start expected_hash
  [[ -f "$PID_IDENTITY_FILE" ]] || return 1
  expected_start="$(sed -n 's/^pid_start_time=//p' "$PID_IDENTITY_FILE" | head -n 1)"
  expected_hash="$(sed -n 's/^pid_command_hash=//p' "$PID_IDENTITY_FILE" | head -n 1)"
  [[ -n "$expected_start" && -n "$expected_hash" ]] || return 1
  [[ "$expected_start" == "$(process_start_time "$pid")" ]] || return 1
  [[ "$expected_hash" == "$(process_command_hash "$pid")" ]]
}
