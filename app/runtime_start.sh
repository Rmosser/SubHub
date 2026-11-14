#!/bin/sh
set -eu

VENV_DIR="/lzcapp/cache/venv"
REQ_FILE="/workspace/requirements.txt"
REQ_HASH_FILE="/lzcapp/cache/requirements.sha256"
VENV_SITE_PACKAGES_MARKER="/lzcapp/cache/venv.system-site-packages"
VENV_PYTHON_VERSION_FILE="/lzcapp/cache/venv.python-version"
PACKAGED_PYTHON_BIN="/workspace/runtime/python/bin/python3"
WHEEL_DIR="/workspace/wheels"

PYTHON_BIN=""
if [ -x "$PACKAGED_PYTHON_BIN" ]; then
  PYTHON_BIN="$PACKAGED_PYTHON_BIN"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "runtime bootstrap failed: no usable Python interpreter found (packaged or system)" >&2
  exit 1
fi

if [ ! -f "$REQ_FILE" ]; then
  echo "runtime bootstrap failed: missing requirement lock file $REQ_FILE" >&2
  exit 1
fi

if [ ! -d "$WHEEL_DIR" ]; then
  echo "runtime bootstrap failed: missing wheel directory $WHEEL_DIR" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
  echo "runtime bootstrap failed: python -m venv is unavailable for $PYTHON_BIN" >&2
  exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

if [ ! -x "$VENV_DIR/bin/python3" ] || [ ! -f "$VENV_SITE_PACKAGES_MARKER" ] || [ ! -f "$VENV_PYTHON_VERSION_FILE" ] || [ "$(cat "$VENV_PYTHON_VERSION_FILE")" != "$PYTHON_VERSION" ]; then
  rm -rf "$VENV_DIR"
  if ! "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"; then
    echo "runtime bootstrap failed: unable to create virtualenv at $VENV_DIR" >&2
    exit 1
  fi
  rm -f "$REQ_HASH_FILE"
  touch "$VENV_SITE_PACKAGES_MARKER"
  echo "$PYTHON_VERSION" > "$VENV_PYTHON_VERSION_FILE"
fi

REQ_HASH="$(sha256sum "$REQ_FILE" | cut -d ' ' -f1)"
if [ ! -f "$REQ_HASH_FILE" ] || [ "$(cat "$REQ_HASH_FILE")" != "$REQ_HASH" ] || ! "$VENV_DIR/bin/python3" -c 'import uvicorn' >/dev/null 2>&1; then
  if ! "$VENV_DIR/bin/python3" -m pip --version >/dev/null 2>&1; then
    echo "runtime bootstrap failed: pip is unavailable inside $VENV_DIR" >&2
    exit 1
  fi
  "$VENV_DIR/bin/python3" -m pip install --no-cache-dir --no-index --find-links "$WHEEL_DIR" -r "$REQ_FILE"
  echo "$REQ_HASH" > "$REQ_HASH_FILE"
fi

exec "$VENV_DIR/bin/python3" -m uvicorn app.main:app --app-dir /workspace --host 0.0.0.0 --port 8000
