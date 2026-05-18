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
# is sent as its own POST (see SMOKE_GCODE below for why) and exercises a
# different surface:
#   G28           — full home; runs safe_z_home → Eddy probe at runtime.
#                   Catches probe-state regressions, missing tap_threshold
#                   guards, kinematics misconfig. G28 alone exercises the
#                   probe end-to-end (descend, measure, return), so a
#                   separate QUERY_PROBE check is redundant — and native
#                   [probe_eddy_current] doesn't implement QUERY_PROBE
#                   anyway ("Probe does not support QUERY_PROBE" at runtime).
#   PARKCENTER    — exercises one of our custom park macros end-to-end.
#                   Catches macro→macro reference rot at render time.
#   OFF           — exercises the all-off shutdown sequence (heaters off,
#                   steppers off, fans off, lights off).
#   _RESETSPEEDS  — restores configured velocity/accel/SCV. Catches
#                   accidental removal of speed-management macros.
#
# Each command is POSTed separately (not as a single \n-joined batch) so
# Klipper doesn't see queue-ahead pressure across G28's tap boundary.
# G28 embeds PROBE METHOD=tap (via [homing_override]), which captures a
# fixed 160ms sample window relative to toolhead.get_last_move_time() when
# planning the retract. With downstream commands already queued, look-ahead
# can shift that timestamp vs the MCU's actual retract execution, producing
# spurious "Unable to detect tap: insufficient lift (0.000000 vs 0.350000)"
# errors. Seen on 2026-05-16 deploy of refactor Phase 4 PR-A; manual
# console G28 immediately after succeeded. See memory/eddy-first-tap-flake.md.
SMOKE_GCODE=(
  "G28"
  "PARKCENTER"
  "OFF"
  "_RESETSPEEDS"
)

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

# 2. POST each gcode command separately. Moonraker /printer/gcode/script
#    blocks until the command finishes; sending one at a time means
#    Klipper has nothing queued behind the current command and look-ahead
#    can't shift PROBE METHOD=tap's sample window timestamps. --max-time
#    120 covers a normal G28 (~30s) plus a generous buffer.
#
# The FIRST command (G28) gets a one-shot retry to absorb the
# eddy-first-tap flake: after `firmware_restart`, native
# `[probe_eddy_current]` needs the LDC1612 to settle before the first
# descend-probe is reliable. Klipper sometimes reports `state=ready`
# before that settling completes, so the first G28 fails with
# "insufficient lift" or "No trigger on stepper_z after full movement".
# An immediate retry (after a short pause) succeeds. Once the first
# probe completes the eddy is warm — subsequent commands (PARKCENTER,
# OFF, _RESETSPEEDS) are reliable, so retry applies to the first
# command ONLY. See memory/eddy-first-tap-flake.md and #65.
EDDY_RETRY_SLEEP="${EDDY_RETRY_SLEEP:-5}"

post_gcode() {
  # POST a single gcode command. Returns 0 on Moonraker accept, non-zero on reject.
  # Captures Moonraker's response body in the global `moonraker_response`.
  local cmd="$1"
  moonraker_response=$(curl -fsS -X POST "$PI_API/printer/gcode/script" \
    --data-urlencode "script=$cmd" \
    --max-time 120 \
    2>&1)
}

if [[ ${#SMOKE_GCODE[@]} -eq 0 ]]; then
  echo "ERR: SMOKE_GCODE is empty — nothing to run. This is a script bug." >&2
  exit 1
fi
echo "==> Running smoke gcode (${#SMOKE_GCODE[@]} commands; ~30-60s total)"

# First command: retry once on reject to absorb the eddy-first-tap flake.
first_cmd="${SMOKE_GCODE[0]}"
echo "    -> $first_cmd"
if ! post_gcode "$first_cmd"; then
  echo "    First '$first_cmd' rejected — likely eddy-first-tap flake (#65)."
  echo "    Retrying once after ${EDDY_RETRY_SLEEP}s for LDC1612 to settle..."
  sleep "$EDDY_RETRY_SLEEP"
  if ! post_gcode "$first_cmd"; then
    echo "ERR: smoke gcode '$first_cmd' rejected by Moonraker (twice):" >&2
    printf '  %s\n' "$moonraker_response" >&2
    exit 2
  fi
  echo "    Retry succeeded (eddy-first-tap-flake pattern)."
fi

# Remaining commands: no retry — once the Eddy is warm, they're reliable.
for cmd in "${SMOKE_GCODE[@]:1}"; do
  echo "    -> $cmd"
  if ! post_gcode "$cmd"; then
    echo "ERR: smoke gcode '$cmd' rejected by Moonraker:" >&2
    printf '  %s\n' "$moonraker_response" >&2
    exit 2
  fi
done
echo "    All commands accepted."

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
