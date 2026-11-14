#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/lzc-manifest.yml"

fail() {
  echo "[security_preflight] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

require_cmd rg
require_cmd tar

echo "[security_preflight] checking manifest placeholders..."
if rg -n "SUB_TOKEN=(?!__SETUP_REQUIRED__)" "$MANIFEST" -P >/dev/null; then
  fail "manifest contains non-placeholder SUB_TOKEN"
fi
if rg -n "DATA_ENCRYPTION_KEY=(?!__SETUP_REQUIRED__)" "$MANIFEST" -P >/dev/null; then
  fail "manifest contains non-placeholder DATA_ENCRYPTION_KEY"
fi

echo "[security_preflight] checking docs for local absolute paths..."
if rg -n "/Users/|/home/|C:\\\\Users\\\\" "$ROOT_DIR/README.md" "$ROOT_DIR/docs" >/dev/null; then
  fail "docs include absolute local paths"
fi

LATEST_LPK="$(ls -t "$ROOT_DIR"/.pkgout/*.lpk 2>/dev/null | head -n1 || true)"
if [[ -z "$LATEST_LPK" ]]; then
  fail "no lpk artifact found under .pkgout/"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[security_preflight] inspecting artifact: $LATEST_LPK"
tar -xOf "$LATEST_LPK" content.tar > "$TMP_DIR/content.tar"

if tar -tf "$LATEST_LPK" | rg -n "manifest.yml" >/dev/null; then
  tar -xOf "$LATEST_LPK" manifest.yml > "$TMP_DIR/manifest.yml"
  if rg -n "SUB_TOKEN=(?!__SETUP_REQUIRED__)" "$TMP_DIR/manifest.yml" -P >/dev/null; then
    fail "artifact manifest contains non-placeholder SUB_TOKEN"
  fi
  if rg -n "DATA_ENCRYPTION_KEY=(?!__SETUP_REQUIRED__)" "$TMP_DIR/manifest.yml" -P >/dev/null; then
    fail "artifact manifest contains non-placeholder DATA_ENCRYPTION_KEY"
  fi
fi

BLOCK_PATTERNS='(^|/)\.env$|(^|/)var/|\.db$|\.sqlite$|(^|/)__pycache__/|\.pyc$|(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?$|(^|/).*(private|secret|key)\.pem$'
if tar -tf "$TMP_DIR/content.tar" | rg -n "$BLOCK_PATTERNS" -S >/dev/null; then
  fail "artifact content contains blocked files"
fi

echo "[security_preflight] OK"
