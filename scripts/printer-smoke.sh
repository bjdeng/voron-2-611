#!/usr/bin/env bash
# printer-smoke — Layer 6 post-deploy smoke test.
#
# Runs a fixed gcode sequence on the live printer via Moonraker, then
# checks klippy.log for any `!!` error lines emitted during the run.
# Catches runtime regressions that L3 (Klippy parse + MCU load in CI)
# cannot — e.g. macros that reference undefined commands at render time,
# invalid pin lookups inside conditional jinja, calibration-state bugs.
#
# Called by deploy_to_pi.sh --smoke. Can also run standalone:
#   PI_HOST=pi@mainsailos.local scripts/printer-smoke.sh
#
# Exit codes:
#   0 — pass
#   1 — local error (can't reach Pi, can't read log)
#   2 — Moonraker rejected the gcode script (Klipper not ready, etc.)
#   3 — klippy.log shows new `!!` errors after smoke ran
#
# Requires: ssh (keyed), curl, the Pi at $PI_HOST with Moonraker reachable
# at $PI_API. Printer should already be in `ready` state — deploy_to_pi.sh
# verifies that before invoking this.

set -euo pipefail

PI_HOST="${PI_HOST:-pi@mainsailos.local}"
PI_API="${PI_API:-http://mainsailos.local:7125}"

# Gcode sequence — short on purpose so deploys finish in <90s. Each command
# exercises a different surface:
#   G28           — full home; runs safe_z_home → Eddy probe at runtime.
#                   Catches probe-state regressions, missing tap_threshold
#                   guards, kinematics misconfig.
#   QUERY_PROBE   — sanity-checks the probe object is defined and queryable.
#   PARKCENTER    — exercises one of our custom park macros end-to-end.
#                   Catches macro→macro reference rot at render time.
#   OFF           — exercises the all-off shutdown sequence (heaters off,
#                   steppers off, fans off, lights off).
#   _RESETSPEEDS  — restores configured velocity/accel/SCV. Catches
#                   accidental removal of speed-management macros.
#
# Joined with \n; Moonraker /printer/gcode/script runs the whole batch
# atomically and only returns once every line completes (or one errors).
SMOKE_GCODE='G28
QUERY_PROBE
PARKCENTER
OFF
_RESETSPEEDS'

# Klipper reserves `!! ` as the runtime-error prefix in klippy.log and the
# gcode response stream. Matching any `^!! ` line is the right gate — an
# allowlist of known suffixes would silently pass new failure shapes
# (TMC errors, MCU shutdowns, "Timer too close", probe-sample tolerance,
# heater verify failures, etc.). False positives are essentially nil on
# a healthy run.
ERROR_PATTERN='^!! '

# shellcheck disable=SC2088  # tilde intentionally NOT expanded locally;
# we want the Pi's shell to expand it server-side (it'd point to a Pi-side
# path nonexistent on the deployer's machine).
KLIPPY_LOG='~/printer_data/logs/klippy.log'

# 1. Snapshot klippy.log: line count AND inode. Anything appearing after
#    this point is attributable to our smoke run — provided the log
#    doesn't rotate (Klipper rotates klippy.log on every restart, and the
#    SKR-Z/EASY-BRD re-enumeration race can trigger a mid-deploy reconnect
#    that bumps the inode). If the inode changes between snapshot and read,
#    `tail -n +N+1` would skip into a fresh file with the wrong offset,
#    producing false negatives. Inode check below catches that case.
echo "==> Snapshot klippy.log line count + inode on $PI_HOST"
# shellcheck disable=SC2029  # $KLIPPY_LOG intentionally expands client-side
# to the literal `~/printer_data/logs/klippy.log` string; Pi's shell tilde-
# expands it server-side.
snapshot=$(ssh "$PI_HOST" "stat -c '%i' $KLIPPY_LOG && wc -l < $KLIPPY_LOG" 2>/dev/null)
before_inode=$(printf '%s\n' "$snapshot" | sed -n '1p')
before_lines=$(printf '%s\n' "$snapshot" | sed -n '2p')
if ! [[ "$before_inode" =~ ^[0-9]+$ && "$before_lines" =~ ^[0-9]+$ ]]; then
  echo "ERR: could not snapshot klippy.log on $PI_HOST (got inode='$before_inode' lines='$before_lines')" >&2
  exit 1
fi
echo "    klippy.log: inode=$before_inode lines=$before_lines"

# 2. POST the gcode sequence. Moonraker /printer/gcode/script blocks until
#    every command finishes. --max-time 120 covers a normal G28 (~30s) +
#    park moves + a generous buffer.
echo "==> Running smoke gcode (G28 + parks; ~30-60s)"
moonraker_response=$(curl -fsS -X POST "$PI_API/printer/gcode/script" \
  --data-urlencode "script=$SMOKE_GCODE" \
  --max-time 120 \
  2>&1) || {
    echo "ERR: smoke gcode rejected by Moonraker:" >&2
    printf '  %s\n' "$moonraker_response" >&2
    exit 2
}
echo "    Moonraker: $moonraker_response"

# 3. Read what got logged since the snapshot. Re-check inode first — if it
#    changed, the log rotated mid-smoke (Klipper restart, log rotation
#    daemon) and the line-offset comparison is meaningless. Treat that as
#    inconclusive (rc=1, not rc=3) so the user inspects manually.
echo "==> Checking klippy.log for new errors since smoke started"
# shellcheck disable=SC2029  # same as snapshot — KLIPPY_LOG expands client-side.
after_inode=$(ssh "$PI_HOST" "stat -c '%i' $KLIPPY_LOG" 2>/dev/null)
if [[ "$after_inode" != "$before_inode" ]]; then
  echo "ERR: klippy.log rotated during smoke (inode $before_inode → $after_inode)." >&2
  echo "    Line-offset comparison is invalid. Inspect klippy.log manually." >&2
  exit 1
fi

# tail -n +N is 1-indexed → `+$((before_lines + 1))` gives the first NEW
# line. grep -c counts matches and returns 1 on no-match → `|| true`
# tolerates the zero case. ERROR_PATTERN is fixed; no need to escape.
# shellcheck disable=SC2029  # KLIPPY_LOG + ERROR_PATTERN expand client-side.
new_errors=$(ssh "$PI_HOST" "tail -n +$((before_lines + 1)) $KLIPPY_LOG | grep -E '$ERROR_PATTERN' || true")
if [[ -n "$new_errors" ]]; then
  err_count=$(printf '%s\n' "$new_errors" | grep -cE "$ERROR_PATTERN")
  echo "ERR: smoke detected $err_count new error(s) in klippy.log:" >&2
  printf '  %s\n' "$new_errors" >&2
  exit 3
fi

echo "==> Smoke test passed: no new errors in klippy.log"
