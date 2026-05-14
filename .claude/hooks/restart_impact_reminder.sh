#!/usr/bin/env bash
# PostToolUse hook: when a tracked .cfg file is edited or written, post
# a one-line reminder to classify the change's restart impact per the
# rule in CLAUDE.md ("Flag the restart impact of every change").
#
# Passive — never blocks. The whole point is to keep the policy sticky
# for fresh Claude sessions that haven't deeply absorbed CLAUDE.md.

set -euo pipefail

PAYLOAD=$(cat)

# Fail-silent on bad JSON — a buggy reminder shouldn't surface noise.
if ! TOOL_NAME=$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))' 2>/dev/null); then
  exit 0
fi
FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null || echo "")

case "$TOOL_NAME" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

case "$FILE_PATH" in
  *.cfg) ;;
  *) exit 0 ;;
esac

# Skip archive/, fixtures/, and vendor/ — those don't go to the printer.
case "$FILE_PATH" in
  */archive/*|*/tests/fixtures/*|*/vendor/*) exit 0 ;;
esac

cat >&2 <<MSG
ℹ️  Reminder: classify this .cfg change before proposing the diff:
   • RESTART          — most Python-side changes (macros, gcode_macro, bed_mesh, timing)
   • FIRMWARE_RESTART — [mcu], pins, kinematics, stepper config, sensor types,
                        anything that emits "requires FIRMWARE_RESTART" in klippy.log
   See CLAUDE.md → "## How to help me" → step 3.
MSG

exit 0
