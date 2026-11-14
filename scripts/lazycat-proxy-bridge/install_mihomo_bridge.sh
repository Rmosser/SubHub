#!/usr/bin/env bash
set -euo pipefail

# These values are part of the host contract, not caller-provided routing
# controls. A target host is accepted only when it is the fixed loopback
# Mihomo listener; --target-host is an explicit confirmation of that identity.
BIND_IP="172.18.0.1"
BIND_PORT="17890"
TARGET_HOST="127.0.0.1"
TARGET_PORT="7890"
SOCKET_UNIT="mihomo-container-proxy.socket"
SERVICE_UNIT="mihomo-container-proxy.service"
SYSTEMD_PROXYD="/lib/systemd/systemd-socket-proxyd"
UNIT_DIR="/etc/systemd/system"
SOCKET_PATH="${UNIT_DIR}/${SOCKET_UNIT}"
SERVICE_PATH="${UNIT_DIR}/${SERVICE_UNIT}"
MARKER_FILE="/etc/mihomo-container-proxy.approved-host"

INSTALL=0
CONFIRM=0
REQUESTED_TARGET_HOST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) INSTALL=1; shift ;;
    --confirm) CONFIRM=1; shift ;;
    --target-host) REQUESTED_TARGET_HOST="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--install --confirm --target-host HOST]";
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ "$INSTALL" == 0 ]]; then
  echo "bridge install preview: fixed target=${TARGET_HOST}:${TARGET_PORT}, bind=${BIND_IP}:${BIND_PORT}; pass --install --confirm --target-host 127.0.0.1 on the host identified by ${MARKER_FILE}"
  exit 0
fi
if [[ "$CONFIRM" != 1 || -z "$REQUESTED_TARGET_HOST" ]]; then
  echo "bridge installation requires --install --confirm --target-host HOST" >&2
  exit 2
fi
if [[ ! -f "$MARKER_FILE" ]]; then
  echo "the fixed root-owned approved host marker file is required" >&2
  exit 2
fi
MARKER_OWNER="$(stat -c '%u' "$MARKER_FILE" 2>/dev/null || stat -f '%u' "$MARKER_FILE")"
MARKER_MODE="$(stat -c '%a' "$MARKER_FILE" 2>/dev/null || stat -f '%Lp' "$MARKER_FILE")"
if [[ "$MARKER_OWNER" != 0 || "$MARKER_MODE" != 600 && "$MARKER_MODE" != 640 && "$MARKER_MODE" != 644 ]]; then
  echo "approved host marker must be root-owned with mode 0600, 0640, or 0644" >&2
  exit 2
fi
LOCAL_HOSTNAME="$(hostname -f 2>/dev/null || hostname)"
LOCAL_MACHINE_ID="$(cat /etc/machine-id 2>/dev/null || true)"
if [[ -z "$LOCAL_HOSTNAME" || -z "$LOCAL_MACHINE_ID" ]] || ! grep -Fxq "hostname=$LOCAL_HOSTNAME" "$MARKER_FILE" || ! grep -Fxq "machine_id=$LOCAL_MACHINE_ID" "$MARKER_FILE" || ! grep -Fxq "target_host=$TARGET_HOST" "$MARKER_FILE"; then
  echo "approved host marker does not identify this host and requested target" >&2
  exit 2
fi
if [[ "$REQUESTED_TARGET_HOST" != "$TARGET_HOST" ]]; then
  echo "requested target host must be the fixed loopback Mihomo listener" >&2
  exit 2
fi
TARGET_HOST="$REQUESTED_TARGET_HOST"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if [[ ! -x "$SYSTEMD_PROXYD" ]]; then
  echo "missing ${SYSTEMD_PROXYD}" >&2
  exit 1
fi

if ! ip -brief address | grep -Fq "$BIND_IP"; then
  echo "bind ip ${BIND_IP} not found on host" >&2
  exit 1
fi

ROLLBACK_ROOT="/var/lib/mihomo-container-proxy"
install -d -m 0700 "$ROLLBACK_ROOT"
ROLLBACK_DIR="$(mktemp -d "$ROLLBACK_ROOT/rollback.XXXXXX")"
chmod 0700 "$ROLLBACK_DIR"
rollback_armed=1
for path in "$SOCKET_PATH" "$SERVICE_PATH"; do
  name="$(basename "$path")"
  if [[ -e "$path" ]]; then
    cp -p -- "$path" "$ROLLBACK_DIR/$name"
    printf 'present\t%s\n' "$name" >> "$ROLLBACK_DIR/manifest"
  else
    printf 'missing\t%s\n' "$name" >> "$ROLLBACK_DIR/manifest"
  fi
done
for unit in "$SOCKET_UNIT" "$SERVICE_UNIT"; do
  if systemctl is-active --quiet "$unit"; then state=active; else state=inactive; fi
  printf '%s\n' "$state" > "$ROLLBACK_DIR/$(basename "$unit").active"
  if systemctl is-enabled --quiet "$unit"; then state=enabled; else state=disabled; fi
  printf '%s\n' "$state" > "$ROLLBACK_DIR/$(basename "$unit").enabled"
done

rollback() {
  local status=$?
  if [[ "$rollback_armed" == 1 ]]; then
    systemctl stop "$SOCKET_UNIT" "$SERVICE_UNIT" >/dev/null 2>&1 || true
    while IFS=$'\t' read -r state name; do
      case "$state" in
        present) cp -p -- "$ROLLBACK_DIR/$name" "$UNIT_DIR/$name" ;;
        missing) rm -f -- "$UNIT_DIR/$name" ;;
        *) echo "invalid rollback manifest" >&2; status=1 ;;
      esac
    done < "$ROLLBACK_DIR/manifest"
    systemctl daemon-reload >/dev/null 2>&1 || true
    for unit in "$SOCKET_UNIT" "$SERVICE_UNIT"; do
      if [[ "$(cat "$ROLLBACK_DIR/$(basename "$unit").enabled")" == enabled ]]; then
        systemctl enable "$unit" >/dev/null 2>&1 || status=1
      else
        systemctl disable "$unit" >/dev/null 2>&1 || true
      fi
      if [[ "$(cat "$ROLLBACK_DIR/$(basename "$unit").active")" == active ]]; then
        systemctl start "$unit" >/dev/null 2>&1 || status=1
      else
        systemctl stop "$unit" >/dev/null 2>&1 || true
      fi
    done
    echo "bridge installation failed; original units restored from $ROLLBACK_DIR" >&2
  fi
  exit "$status"
}
trap rollback EXIT

SOCKET_TMP="$(mktemp "$UNIT_DIR/.mihomo-container-proxy.socket.XXXXXX")"
SERVICE_TMP="$(mktemp "$UNIT_DIR/.mihomo-container-proxy.service.XXXXXX")"
cleanup_temps() { rm -f -- "$SOCKET_TMP" "$SERVICE_TMP"; }
trap 'cleanup_temps; rollback' EXIT

cat >"$SOCKET_TMP" <<EOF
[Unit]
Description=Internal-only mihomo proxy socket for LazyCat containers

[Socket]
ListenStream=${BIND_IP}:${BIND_PORT}
Accept=no
NoDelay=true
BindIPv6Only=both

[Install]
WantedBy=sockets.target
EOF

cat >"$SERVICE_TMP" <<EOF
[Unit]
Description=Forward LazyCat internal proxy socket to mihomo
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${SYSTEMD_PROXYD} ${TARGET_HOST}:${TARGET_PORT}
StandardInput=socket
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

chmod 0644 "$SOCKET_TMP" "$SERVICE_TMP"
mv -f -- "$SOCKET_TMP" "$SOCKET_PATH"
mv -f -- "$SERVICE_TMP" "$SERVICE_PATH"
systemctl daemon-reload
systemctl enable --now "$SOCKET_UNIT"
systemctl restart "$SOCKET_UNIT"

if ! systemctl is-enabled --quiet "${SOCKET_UNIT}" || ! systemctl is-active --quiet "${SOCKET_UNIT}"; then
  echo "socket unit did not become enabled and active" >&2
  exit 1
fi
SOCKET_LISTEN="$(systemctl show "$SOCKET_UNIT" --property=Listen --value 2>/dev/null || true)"
if [[ "$SOCKET_LISTEN" != *"${BIND_IP}:${BIND_PORT}"* ]] || ! ss -ltn | grep -Fq "${BIND_IP}:${BIND_PORT}"; then
  echo "socket readback does not match ${BIND_IP}:${BIND_PORT}" >&2
  exit 1
fi
SERVICE_TARGET="$(systemctl show "$SERVICE_UNIT" --property=ExecStart --value 2>/dev/null || true)"
if [[ "$SERVICE_TARGET" != *"${TARGET_HOST}:${TARGET_PORT}"* ]]; then
  echo "service readback does not match the approved forwarding target" >&2
  exit 1
fi

echo "installed ${BIND_IP}:${BIND_PORT} -> ${TARGET_HOST}:${TARGET_PORT}"
echo "verified socket/service readback for ${BIND_IP}:${BIND_PORT} -> ${TARGET_HOST}:${TARGET_PORT}"
rollback_armed=0
trap - EXIT
cleanup_temps
