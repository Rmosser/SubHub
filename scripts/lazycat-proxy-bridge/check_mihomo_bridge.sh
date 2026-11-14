#!/usr/bin/env bash
set -euo pipefail

BIND_IP="${BIND_IP:-172.18.0.1}"
BIND_PORT="${BIND_PORT:-17890}"
TARGET_URL="${TARGET_URL:-https://api.openai.com/v1/models}"
SOCKET_UNIT="${SOCKET_UNIT:-mihomo-container-proxy.socket}"
SERVICE_UNIT="${SERVICE_UNIT:-mihomo-container-proxy.service}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

echo "[1/4] systemd units"
systemctl is-enabled "${SOCKET_UNIT}" >/dev/null
systemctl is-active "${SOCKET_UNIT}" >/dev/null
systemctl status "${SOCKET_UNIT}" --no-pager | sed -n '1,12p'
systemctl status "${SERVICE_UNIT}" --no-pager | sed -n '1,12p' || true

echo "[2/4] listener"
ss -ltnp | grep -F "${BIND_IP}:${BIND_PORT}"
if ss -ltnp | grep -Eq "0\\.0\\.0\\.0:${BIND_PORT}\\b"; then
  echo "BAD: bridge exposed on 0.0.0.0:${BIND_PORT}" >&2
  exit 1
fi

echo "[3/4] upstream proxy probe"
code="$(curl -sS -o /dev/null -w '%{http_code}' -I -x "http://${BIND_IP}:${BIND_PORT}" "${TARGET_URL}")"
echo "HTTP ${code} via bridge"
if [[ "${code}" == "000" ]]; then
  echo "BAD: bridge reachable but upstream proxy probe failed" >&2
  exit 1
fi

echo "[4/4] recovery hint"
echo "if broken: systemctl restart ${SOCKET_UNIT}"
echo "if still broken: verify mihomo upstream listens on 127.0.0.1:7890 or reinstall bridge"
