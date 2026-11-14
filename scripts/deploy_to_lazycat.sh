#!/usr/bin/env bash
set -euo pipefail
# set -e alone exits without a word when a command (or a command substitution) fails; name it instead.
trap 'echo "[deploy_to_lazycat] ERROR: command failed at line ${LINENO}: ${BASH_COMMAND:0:160}" >&2' ERR

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEPLOY=0
BOX=""
CONFIRM=0
CLEANUP_OLD=0
CLEANUP_CONFIRM=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy) DEPLOY=1; shift ;;
    --box) BOX="${2:-}"; shift 2 ;;
    --confirm) CONFIRM=1; shift ;;
    --cleanup-old) CLEANUP_OLD=1; shift ;;
    --confirm-cleanup) CLEANUP_CONFIRM=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--deploy --box <box-name> --confirm [--cleanup-old --confirm-cleanup]]";
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ "$DEPLOY" == 1 && -z "$BOX" ]]; then
  echo "--deploy requires an explicit --box <box-name>" >&2
  exit 2
fi
if [[ "$DEPLOY" == 1 && "$CONFIRM" != 1 ]]; then
  echo "deployment requires --confirm" >&2
  exit 2
fi
if [[ "$DEPLOY" == 0 && "$CONFIRM" == 1 ]]; then
  echo "--confirm is only valid with --deploy" >&2
  exit 2
fi
if [[ "$CLEANUP_OLD" == 1 && ( "$DEPLOY" == 0 || "$CONFIRM" != 1 || "$CLEANUP_CONFIRM" != 1 ) ]]; then
  echo "--cleanup-old requires --deploy --confirm --confirm-cleanup after verification" >&2
  exit 2
fi
if [[ "$CLEANUP_CONFIRM" == 1 && "$CLEANUP_OLD" == 0 ]]; then
  echo "--confirm-cleanup is only valid with --cleanup-old" >&2
  exit 2
fi
# How long to wait after install for the release container before the readback gives up, and how often to retry.
READBACK_TIMEOUT_SECONDS="${DEPLOY_READBACK_TIMEOUT_SECONDS:-180}"
READBACK_INTERVAL_SECONDS="${DEPLOY_READBACK_INTERVAL_SECONDS:-5}"
if [[ ! "$READBACK_TIMEOUT_SECONDS" =~ ^[0-9]+$ || ! "$READBACK_INTERVAL_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "DEPLOY_READBACK_TIMEOUT_SECONDS and DEPLOY_READBACK_INTERVAL_SECONDS must be whole seconds" >&2
  exit 2
fi

PACKAGE_DIR=".pkgout"
PACKAGE_ID="$(awk '$1 == "package:" { print $2; exit }' lzc-manifest.yml)"
PACKAGE_VERSION="$(awk '$1 == "version:" { print $2; exit }' lzc-manifest.yml)"
if [[ -z "$PACKAGE_ID" || -z "$PACKAGE_VERSION" ]]; then
  echo "[deploy_to_lazycat] ERROR: package/version missing from lzc-manifest.yml" >&2
  exit 1
fi

echo "[deploy_to_lazycat] building package..."
lzc-cli project build

LATEST_LPK="$(ls -t "${PACKAGE_DIR}"/*.lpk 2>/dev/null | head -n1 || true)"
if [[ -z "${LATEST_LPK}" ]]; then
  echo "[deploy_to_lazycat] ERROR: no .lpk found under ${PACKAGE_DIR}/" >&2
  exit 1
fi
OLDER_LPKS=()
while IFS= read -r pkg; do
  [[ "$pkg" == "$LATEST_LPK" ]] && continue
  OLDER_LPKS+=("$pkg")
done < <(ls -t "${PACKAGE_DIR}"/*.lpk 2>/dev/null)

if [[ "$DEPLOY" == 0 ]]; then
  echo "[deploy_to_lazycat] build complete; no box was selected, so install was skipped: ${LATEST_LPK}"
  exit 0
fi

ORIGINAL_BOX="$(lzc-cli box default 2>&1 | tr -d '\r')"
[[ "$ORIGINAL_BOX" =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "[deploy_to_lazycat] ERROR: could not read the current default box" >&2
  exit 1
}
BOX_SWITCHED=0
restore_original_box() {
  if [[ "$BOX_SWITCHED" == 1 ]]; then
    if ! lzc-cli box switch "$ORIGINAL_BOX" >/dev/null 2>&1; then
      echo "[deploy_to_lazycat] ERROR: failed to restore original box $ORIGINAL_BOX" >&2
      return 1
    fi
    local restored
    restored="$(lzc-cli box default 2>&1 | tr -d '\r')"
    if [[ "$restored" != "$ORIGINAL_BOX" ]]; then
      echo "[deploy_to_lazycat] ERROR: box restore readback mismatch: $restored" >&2
      return 1
    fi
    BOX_SWITCHED=0
  fi
}
on_exit() {
  local status=$?
  restore_original_box || status=1
  exit "$status"
}

echo "[deploy_to_lazycat] switching to approved box: ${BOX}"
lzc-cli box switch "${BOX}"
BOX_SWITCHED=1
trap on_exit EXIT
CURRENT_BOX="$(lzc-cli box default 2>&1 | tr -d '\r')"
if [[ "$CURRENT_BOX" != "$BOX" ]]; then
  echo "[deploy_to_lazycat] ERROR: box default readback mismatch: ${CURRENT_BOX}" >&2
  exit 1
fi
echo "[deploy_to_lazycat] installing package: ${LATEST_LPK}"
lzc-cli app install "${LATEST_LPK}" --apk n
# Why an lzc-cli call failed: the last error line other than its generic `Error: exit status N`
# (so a command's own error inside the container wins), else `health failed`, else the last line.
lzc_reason() {
  local reason
  reason="$(grep -E 'Error:|error:' <<<"$1" | grep -Ev '^Error: exit status [0-9]+$' | tail -n1 || true)"
  [[ -n "$reason" ]] || reason="$(grep -m1 -Fx 'health failed' <<<"$1" || tail -n1 <<<"$1")"
  echo "${reason:-no output}"
}
APP_STATUS="$(lzc-cli app status "${PACKAGE_ID}" 2>&1)" || true
if ! grep -Eiq '(installed|running)' <<<"$APP_STATUS" || grep -Eiq '(failed|error|crashloop)' <<<"$APP_STATUS"; then
  echo "[deploy_to_lazycat] ERROR: package status readback failed: $(lzc_reason "$APP_STATUS")" >&2
  exit 1
fi
PROJECT_INFO="$(lzc-cli project info --release 2>&1)" || true
if ! grep -Fq "${PACKAGE_ID}" <<<"$PROJECT_INFO" || ! grep -Fq "${PACKAGE_VERSION}" <<<"$PROJECT_INFO" || ! grep -Eiq 'Deployed version:.*' <<<"$PROJECT_INFO"; then
  echo "[deploy_to_lazycat] ERROR: package/version readback failed: $(lzc_reason "$PROJECT_INFO")" >&2
  exit 1
fi
CONTENT_DIR="$(awk '$1 == "contentdir:" { print $2; exit }' lzc-build.yml)"
if [[ -z "$CONTENT_DIR" || ! -d "$CONTENT_DIR" ]]; then
  echo "[deploy_to_lazycat] ERROR: configured package content directory is missing" >&2
  exit 1
fi
CONTENT_DIGEST="$(cd "$CONTENT_DIR" && find . -type f -print0 | sort -z | while IFS= read -r -d '' file; do sha256sum "$file"; done | sha256sum | awk '{print $1}')"

# `app install` returns while the release containers are still being recreated, and until the new web
# container is up `project exec` fails with `Service "web" is not running`. Keep reading back until the
# installed content matches and the app answers, or the wait runs out; a real mismatch still fails.
READBACK_DEADLINE=$((SECONDS + READBACK_TIMEOUT_SECONDS))
while :; do
  REMOTE_OUTPUT="$(lzc-cli project exec --release -s web --tty=false -- /bin/sh -c 'set -eu; cd /workspace; find . -type f -print0 | sort -z | while IFS= read -r -d "" file; do sha256sum "$file"; done | sha256sum' 2>&1)" || true
  REMOTE_CONTENT_DIGEST="$(tail -n1 <<<"$REMOTE_OUTPUT" | awk '{print $1}')"
  if [[ ! "$REMOTE_CONTENT_DIGEST" =~ ^[0-9a-f]{64}$ ]]; then
    READBACK_PROBLEM="could not read the installed content digest ($(lzc_reason "$REMOTE_OUTPUT"))"
  elif [[ "$REMOTE_CONTENT_DIGEST" != "$CONTENT_DIGEST" ]]; then
    READBACK_PROBLEM="installed content digest does not match the built package content"
  else
    HEALTH_READBACK="$(lzc-cli project exec --release -s web --tty=false -- /workspace/runtime/python/bin/python3 -c 'import json,sys; from urllib.request import urlopen; r=urlopen("http://127.0.0.1:8000/healthz", timeout=3); payload=json.load(r); print("health ok" if r.status == 200 and payload.get("ok") is True else "health failed"); sys.exit(0 if r.status == 200 and payload.get("ok") is True else 1)' 2>&1)" || true
    if grep -Fxq "health ok" <<<"$HEALTH_READBACK"; then
      break
    fi
    READBACK_PROBLEM="in-container health readback failed ($(lzc_reason "$HEALTH_READBACK"))"
  fi
  if (( SECONDS >= READBACK_DEADLINE )); then
    echo "[deploy_to_lazycat] ERROR: ${READBACK_PROBLEM}; gave up after ${READBACK_TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  echo "[deploy_to_lazycat] waiting for the release container: ${READBACK_PROBLEM}"
  sleep "$READBACK_INTERVAL_SECONDS"
done
echo "[deploy_to_lazycat] verified ${PACKAGE_ID} ${PACKAGE_VERSION} on ${BOX}: status, version, content digest, in-container health"

if [[ "$CLEANUP_OLD" == 1 && "${#OLDER_LPKS[@]}" -gt 0 ]]; then
  printf "[deploy_to_lazycat] removing old build artifacts (%d):\n" "${#OLDER_LPKS[@]}"
  printf '  %s\n' "${OLDER_LPKS[@]}"
  printf '%s\0' "${OLDER_LPKS[@]}" | xargs -0 rm -f
elif [[ "${#OLDER_LPKS[@]}" -gt 0 ]]; then
  printf "[deploy_to_lazycat] retaining old build artifacts until explicit cleanup (%d):\n" "${#OLDER_LPKS[@]}"
  printf '  %s\n' "${OLDER_LPKS[@]}"
else
  echo "[deploy_to_lazycat] no old artifacts to remove."
fi

if [[ "$CLEANUP_OLD" == 1 ]]; then
  echo "[deploy_to_lazycat] explicitly approved old build artifact cleanup completed."
else
  echo "[deploy_to_lazycat] old build artifacts retained; pass --cleanup-old --confirm-cleanup after a verified deploy to remove them."
fi

restore_original_box
trap - EXIT
