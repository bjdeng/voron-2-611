#!/usr/bin/env bash
# install-mcu-watchdog — one-shot installer for klipper-mcu-watchdog on the Pi.
#
# Idempotent: safe to re-run. Copies the script + unit from this repo to the
# system locations, reloads systemd, enables + starts the service.
#
# Run from a checked-out copy of this repo, ON THE PI (or via SSH with sudo):
#   sudo bash scripts/install-mcu-watchdog.sh
#
# See GH issue #37 for the root cause + design.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_SRC="${REPO_ROOT}/scripts/klipper-mcu-watchdog.sh"
UNIT_SRC="${REPO_ROOT}/scripts/klipper-mcu-watchdog.service"

SCRIPT_DST="/usr/local/bin/klipper-mcu-watchdog.sh"
UNIT_DST="/etc/systemd/system/klipper-mcu-watchdog.service"
STATE_DIR="/var/lib/klipper-mcu-watchdog"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERR: must run as root (use sudo)" >&2
  exit 1
fi

for f in "$SCRIPT_SRC" "$UNIT_SRC"; do
  if [[ ! -r "$f" ]]; then
    echo "ERR: required file not found: $f" >&2
    exit 1
  fi
done

echo "==> Installing $SCRIPT_DST"
install -m 0755 "$SCRIPT_SRC" "$SCRIPT_DST"

echo "==> Installing $UNIT_DST"
install -m 0644 "$UNIT_SRC" "$UNIT_DST"

echo "==> Creating state dir $STATE_DIR"
mkdir -p "$STATE_DIR"
chmod 0755 "$STATE_DIR"

echo "==> systemctl daemon-reload"
systemctl daemon-reload

echo "==> Enabling + starting klipper-mcu-watchdog"
systemctl enable klipper-mcu-watchdog
systemctl restart klipper-mcu-watchdog

echo "==> Status:"
systemctl --no-pager status klipper-mcu-watchdog || true

cat <<'EOF'

==> Done. View logs with:
    journalctl -u klipper-mcu-watchdog -f

To uninstall:
    sudo systemctl disable --now klipper-mcu-watchdog
    sudo rm /usr/local/bin/klipper-mcu-watchdog.sh
    sudo rm /etc/systemd/system/klipper-mcu-watchdog.service
    sudo rm -rf /var/lib/klipper-mcu-watchdog
    sudo systemctl daemon-reload
EOF
