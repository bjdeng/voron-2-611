#!/usr/bin/env bash
# klipper-mcu-watchdog — auto-recover from USB re-enumeration races on
# Klipper FIRMWARE_RESTART.
#
# Root cause (root-caused 2026-05-15 — see GH issue #37): on this Pi the SKR Z
# (LPC1769) and EASY-BRD MMU (SAMD21) take longer to come back than the kernel's
# USB enumeration retry budget (~5s). The kernel marks their ports "unable to
# enumerate" and never retries. Devices are physically connected and electrically
# fine — they just need a hub re-scan to re-attach.
#
# This script polls Moonraker for Klipper state and, when Klipper is stuck in
# `startup` with one or more MCUs missing from /dev/serial/by-id/, unbinds and
# rebinds their parent USB hubs to force re-enumeration. The mapping from MCU
# serial → parent hub is auto-learned during healthy runs (when all MCUs ARE
# present) and persisted to /var/lib/klipper-mcu-watchdog/mcu-hub-map.
#
# Modes (invoked as subcommands):
#   daemon            run continuously, polling Moonraker (default; what
#                     the systemd service runs)
#   check             single-shot: scan state, return 0 if all MCUs present,
#                     1 if missing — no recovery action
#   recover           single-shot: detect missing MCUs and trigger rebind +
#                     firmware_restart
#   expected <cfg>    print expected MCU serial basenames from a printer.cfg
#                     (one per line; used by pytest)
#   missing           print missing MCU serial basenames (expected - present)
#   map               print known serial → hub-path mapping from the state file
#   learn             update the serial→hub state file (no-op if any MCU
#                     missing — refuses partial updates)
#   help              this help text
#
# Configuration via env vars:
#   PRINTER_CFG       path to printer.cfg (default /home/pi/printer_data/config/printer.cfg)
#   STATE_DIR         path for state file (default /var/lib/klipper-mcu-watchdog)
#   MOONRAKER_URL     Moonraker base URL (default http://localhost:7125)
#   SERIAL_BY_ID_DIR  /dev/serial/by-id directory (default /dev/serial/by-id)
#   SYSFS_USB_DIR     /sys/bus/usb (default /sys/bus/usb)
#   POLL_INTERVAL     daemon-mode loop interval, seconds (default 10)
#   STARTUP_GRACE     after Klipper enters startup state, wait this long for
#                     its own retries before intervening, seconds (default 30)
#   RECOVERY_RETRIES  max rebind+restart attempts per stuck-startup window
#                     (default 2)
#   FALLBACK_HUB      hub to rebind when state file is empty (default 1-1.3 —
#                     the known-bad internal Pi hub on this build)

set -euo pipefail

PRINTER_CFG="${PRINTER_CFG:-/home/pi/printer_data/config/printer.cfg}"
STATE_DIR="${STATE_DIR:-/var/lib/klipper-mcu-watchdog}"
STATE_FILE="${STATE_DIR}/mcu-hub-map"
MOONRAKER_URL="${MOONRAKER_URL:-http://localhost:7125}"
SERIAL_BY_ID_DIR="${SERIAL_BY_ID_DIR:-/dev/serial/by-id}"
SYSFS_USB_DIR="${SYSFS_USB_DIR:-/sys/bus/usb}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
STARTUP_GRACE="${STARTUP_GRACE:-30}"
RECOVERY_RETRIES="${RECOVERY_RETRIES:-2}"
FALLBACK_HUB="${FALLBACK_HUB:-1-1.3}"

log() {
  # Single-line tagged log to stderr. journald captures it via systemd.
  printf '[klipper-mcu-watchdog] %s\n' "$*" >&2
}

# ─────────────────────────────────────────────────────────────────────────
# gather_config_files <printer.cfg>
# ─────────────────────────────────────────────────────────────────────────
# Print printer.cfg's path and every transitively-included file, one per line.
# Follows `[include X]` directives with glob expansion relative to the
# including file's directory (matching Klipper's behavior — see
# vendor/klipper/klippy/configfile.py).
#
# Cycle detection: tracks already-seen paths in a sorted file passed by ref.
gather_config_files() {
  local cfg="$1"
  local seen_file="${2:-}"
  if [[ -z "$seen_file" ]]; then
    seen_file=$(mktemp)
    # Cleanup on the OUTER call only.
    trap 'rm -f "$seen_file"' RETURN
  fi
  local abs
  abs=$(_abs_path "$cfg")
  if grep -Fxq "$abs" "$seen_file" 2>/dev/null; then
    return 0
  fi
  printf '%s\n' "$abs" >> "$seen_file"
  printf '%s\n' "$abs"
  [[ -r "$abs" ]] || return 0
  local base_dir
  base_dir=$(dirname "$abs")
  # Extract [include FOO] lines, expand globs relative to base_dir.
  local raw inc_pattern
  while IFS= read -r raw; do
    inc_pattern=$(printf '%s\n' "$raw" | sed -E 's/^[[:space:]]*\[include[[:space:]]+//; s/\][[:space:]]*$//')
    [[ -z "$inc_pattern" ]] && continue
    # Glob-expand relative to base_dir. compgen -G handles wildcards.
    local matches
    matches=$(cd "$base_dir" 2>/dev/null && compgen -G "$inc_pattern" 2>/dev/null || true)
    [[ -z "$matches" ]] && continue
    local rel
    while IFS= read -r rel; do
      [[ -z "$rel" ]] && continue
      gather_config_files "${base_dir}/${rel}" "$seen_file"
    done <<< "$matches"
  done < <(grep -E '^[[:space:]]*\[include[[:space:]]+' "$abs" 2>/dev/null || true)
}

# _abs_path <path>
# Portable abspath: avoids `realpath -m` (BSD lacks it). Uses Python for
# canonical resolution since python3 is available everywhere we run.
_abs_path() {
  python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null || printf '%s\n' "$1"
}

# ─────────────────────────────────────────────────────────────────────────
# parse_expected_serials <printer.cfg>
# ─────────────────────────────────────────────────────────────────────────
# Walks printer.cfg and every transitively-included file. Extracts the
# basename of every `serial:` path under any `[mcu...]` section. Yields one
# basename per line (deduplicated, sorted).
#
# Per-file implementation: a simple awk line-state machine. Inside an
# [mcu...] section, capture the first `serial:` line. A section ends when
# the next [section] header appears (or EOF).
parse_expected_serials() {
  local cfg="$1"
  if [[ ! -r "$cfg" ]]; then
    log "ERR: printer.cfg not readable at $cfg"
    return 1
  fi
  local file
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    [[ -r "$file" ]] || continue
    awk '
      /^\[/ {
        in_mcu = 0
        if ($0 ~ /^\[mcu( [^]]+)?\]/) in_mcu = 1
        next
      }
      in_mcu && /^[[:space:]]*serial[[:space:]]*:/ {
        sub(/^[[:space:]]*serial[[:space:]]*:[[:space:]]*/, "")
        sub(/[[:space:]]*#.*$/, "")
        sub(/[[:space:]]+$/, "")
        n = split($0, parts, "/")
        print parts[n]
        in_mcu = 0
      }
    ' "$file"
  done < <(gather_config_files "$cfg") | sort -u
}

# ─────────────────────────────────────────────────────────────────────────
# present_serials
# ─────────────────────────────────────────────────────────────────────────
# Lists serial basenames currently in /dev/serial/by-id/.
present_serials() {
  if [[ ! -d "$SERIAL_BY_ID_DIR" ]]; then
    # If the dir doesn't exist, no devices are enumerated.
    return 0
  fi
  ls -1 "$SERIAL_BY_ID_DIR" 2>/dev/null | sort
}

# ─────────────────────────────────────────────────────────────────────────
# missing_serials
# ─────────────────────────────────────────────────────────────────────────
# Set-difference: expected − present. Output is sorted, one per line.
missing_serials() {
  comm -23 \
    <(parse_expected_serials "$PRINTER_CFG" | sort -u) \
    <(present_serials | sort -u)
}

# ─────────────────────────────────────────────────────────────────────────
# discover_hub_for_serial <serial>
# ─────────────────────────────────────────────────────────────────────────
# Given a serial basename (e.g. usb-Klipper_rp2040_xxx-if00), return its
# PARENT USB hub sysfs name (e.g. 1-1.3). Returns empty if not enumerated.
#
# The serial-by-id symlink resolves into /sys/.../ttyACM<N> which lives under
# the cdc_acm interface dir, whose parent's parent is the USB device dir
# (e.g. /sys/bus/usb/devices/1-1.3.4). Stripping the last `.N` gives the hub.
discover_hub_for_serial() {
  local serial="$1"
  local link target device port_id hub_id
  link="${SERIAL_BY_ID_DIR}/${serial}"
  [[ -L "$link" ]] || return 0
  target=$(readlink -f "$link") || return 0
  # target is /dev/ttyACM<N> — but readlink -f resolves dev nodes; we want sysfs.
  # Use udevadm to get the chain.
  device=$(udevadm info -q path -n "$target" 2>/dev/null) || return 0
  # device looks like /devices/.../usb1/1-1/1-1.3/1-1.3.4/1-1.3.4:1.0/tty/ttyACM1
  # Extract the last hop that matches NN-N.N.N pattern (USB device path).
  port_id=$(printf '%s\n' "$device" | grep -oE '/[0-9]+-[0-9]+(\.[0-9]+)+(/|$)' | tail -1 | tr -d '/')
  [[ -n "$port_id" ]] || return 0
  # Hub is the parent: strip the last `.N` component.
  hub_id="${port_id%.*}"
  printf '%s\n' "$hub_id"
}

# ─────────────────────────────────────────────────────────────────────────
# learn_mapping
# ─────────────────────────────────────────────────────────────────────────
# When all expected MCUs are present, walk them and record serial→hub.
# Atomic write (.tmp → mv) so a concurrent read never sees a half-written
# file. Refuses to install a partial mapping (would clobber a good map
# with bad data on a transient sysfs hiccup): the new mapping must cover
# every expected serial, else discard.
learn_mapping() {
  mkdir -p "$STATE_DIR"
  local tmp serial hub expected_count learned_count
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")"
  expected_count=0
  learned_count=0
  while IFS= read -r serial; do
    [[ -z "$serial" ]] && continue
    expected_count=$((expected_count + 1))
    hub=$(discover_hub_for_serial "$serial") || true
    if [[ -n "$hub" ]]; then
      printf '%s %s\n' "$serial" "$hub" >> "$tmp"
      learned_count=$((learned_count + 1))
    fi
  done < <(parse_expected_serials "$PRINTER_CFG")
  if (( expected_count > 0 && learned_count == expected_count )); then
    mv "$tmp" "$STATE_FILE"
  else
    log "learn_mapping: only resolved $learned_count/$expected_count serials; leaving existing $STATE_FILE intact"
    rm -f "$tmp"
  fi
}

# ─────────────────────────────────────────────────────────────────────────
# hubs_to_rebind <missing-serials...>
# ─────────────────────────────────────────────────────────────────────────
# Given a list of missing serials, return unique hub IDs to rebind. Looked
# up from the state file. If a serial isn't in the state file, fall back
# to FALLBACK_HUB so first-ever recovery still works on this build.
hubs_to_rebind() {
  local missing=("$@")
  local serial hub
  local hubs=()
  for serial in "${missing[@]}"; do
    hub=""
    if [[ -r "$STATE_FILE" ]]; then
      hub=$(awk -v s="$serial" '$1 == s { print $2; exit }' "$STATE_FILE" || true)
    fi
    if [[ -z "$hub" ]]; then
      hub="$FALLBACK_HUB"
      log "WARN: no recorded hub for $serial; falling back to $FALLBACK_HUB"
    fi
    hubs+=("$hub")
  done
  # Unique-ify, preserve sort.
  printf '%s\n' "${hubs[@]}" | sort -u
}

# ─────────────────────────────────────────────────────────────────────────
# rebind_hub <hub-id>
# ─────────────────────────────────────────────────────────────────────────
# Unbind+rebind a USB hub by writing to /sys/bus/usb/drivers/usb. Requires
# root (the systemd service runs as root; manual invocation needs sudo).
rebind_hub() {
  local hub="$1"
  local driver_dir="${SYSFS_USB_DIR}/drivers/usb"
  if [[ ! -e "${driver_dir}/${hub}" ]]; then
    log "ERR: hub '$hub' not bound to usb driver; cannot rebind"
    return 1
  fi
  log "rebinding hub $hub (unbind → sleep 2 → bind)"
  printf '%s\n' "$hub" > "${driver_dir}/unbind" || {
    log "ERR: unbind failed for $hub"
    return 1
  }
  sleep 2
  printf '%s\n' "$hub" > "${driver_dir}/bind" || {
    log "ERR: bind failed for $hub"
    return 1
  }
}

# ─────────────────────────────────────────────────────────────────────────
# klipper_state
# ─────────────────────────────────────────────────────────────────────────
# Query Moonraker for Klipper state. Returns one of: ready, startup, error,
# shutdown, disconnected, unknown.
klipper_state() {
  local resp
  resp=$(curl -fsS --max-time 5 "${MOONRAKER_URL}/printer/info" 2>/dev/null) || {
    printf 'disconnected\n'
    return 0
  }
  printf '%s' "$resp" | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("result", {}).get("state", "unknown"))
except Exception:
    print("unknown")
' 2>/dev/null || printf 'unknown\n'
}

# ─────────────────────────────────────────────────────────────────────────
# trigger_firmware_restart
# ─────────────────────────────────────────────────────────────────────────
# Best-effort POST to Moonraker. Logs on failure (Moonraker may reject if
# Klipper is in 'shutdown' or 'error' state — manual `/printer/restart`
# needed in those cases) but never aborts the daemon.
trigger_firmware_restart() {
  local rc=0
  curl -fsS -X POST --max-time 10 "${MOONRAKER_URL}/printer/firmware_restart" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    log "trigger_firmware_restart: curl exited $rc (Moonraker may have rejected; check /printer/info state)"
  fi
}

# ─────────────────────────────────────────────────────────────────────────
# recover_once
# ─────────────────────────────────────────────────────────────────────────
# One iteration of: detect missing MCUs, rebind their hubs, optionally
# trigger Klipper firmware_restart. Returns 0 if all MCUs present after
# the recovery attempt; 1 if some still missing.
recover_once() {
  local trigger_restart="${1:-1}"
  local missing
  mapfile -t missing < <(missing_serials)
  if [[ "${#missing[@]}" -eq 0 || ( "${#missing[@]}" -eq 1 && -z "${missing[0]}" ) ]]; then
    return 0
  fi
  log "missing MCUs: ${missing[*]}"
  local hub
  while IFS= read -r hub; do
    [[ -z "$hub" ]] && continue
    rebind_hub "$hub" || true
  done < <(hubs_to_rebind "${missing[@]}")
  sleep 5
  mapfile -t missing < <(missing_serials)
  if [[ "${#missing[@]}" -ne 0 && -n "${missing[0]}" ]]; then
    log "still missing after rebind: ${missing[*]}"
    return 1
  fi
  log "recovery succeeded"
  if [[ "$trigger_restart" == "1" ]]; then
    log "triggering Klipper firmware_restart"
    trigger_firmware_restart
  fi
  return 0
}

# ─────────────────────────────────────────────────────────────────────────
# daemon
# ─────────────────────────────────────────────────────────────────────────
# Main loop. Poll Moonraker. When Klipper sits in non-ready state past the
# startup grace window AND MCUs are missing, recover. Otherwise update the
# learned mapping (when state is ready and all MCUs present).
daemon() {
  log "starting (printer.cfg=$PRINTER_CFG; poll=${POLL_INTERVAL}s; grace=${STARTUP_GRACE}s)"
  local state stuck_since now retries backoff_logged
  stuck_since=0
  retries=0
  backoff_logged=0
  while true; do
    state=$(klipper_state)
    now=$(date +%s)
    case "$state" in
      ready)
        stuck_since=0
        retries=0
        backoff_logged=0
        # Refresh learned mapping while everything is healthy.
        learn_mapping
        ;;
      startup|error|disconnected|unknown)
        if [[ "$stuck_since" -eq 0 ]]; then
          stuck_since="$now"
          backoff_logged=0
          log "Klipper state=$state; starting ${STARTUP_GRACE}s grace window"
        elif (( now - stuck_since >= STARTUP_GRACE )); then
          if (( retries < RECOVERY_RETRIES )); then
            retries=$((retries + 1))
            log "Klipper still $state after grace; recovery attempt $retries/${RECOVERY_RETRIES}"
            if recover_once 1; then
              # Restart the grace window — Klipper will need some seconds
              # to come up after firmware_restart.
              stuck_since="$now"
            fi
          elif [[ "$backoff_logged" -eq 0 ]]; then
            # Log once when we exhaust retries; skip future polls until
            # state recovers (which resets backoff_logged via the `ready` case).
            log "max recovery retries reached for current stuck-startup window; backing off (will stop trying until Klipper recovers on its own)"
            backoff_logged=1
          fi
        fi
        ;;
      shutdown)
        # User-initiated; not our problem.
        stuck_since=0
        retries=0
        backoff_logged=0
        ;;
    esac
    sleep "$POLL_INTERVAL"
  done
}

# ─────────────────────────────────────────────────────────────────────────
# CLI dispatch
# ─────────────────────────────────────────────────────────────────────────
main() {
  local subcommand="${1:-daemon}"
  case "$subcommand" in
    daemon)     daemon ;;
    check)      missing_serials | grep -q . && exit 1 || exit 0 ;;
    recover)    recover_once 1 ;;
    expected)   parse_expected_serials "${2:-$PRINTER_CFG}" ;;
    missing)    missing_serials ;;
    map)        cat "$STATE_FILE" 2>/dev/null || true ;;
    learn)      learn_mapping ;;
    help|-h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      ;;
    *)
      log "unknown subcommand: $subcommand (try 'help')"
      exit 2
      ;;
  esac
}

main "$@"
