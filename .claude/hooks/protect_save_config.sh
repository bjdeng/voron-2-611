#!/usr/bin/env bash
# PreToolUse hook: block edits that would write into printer.cfg's
# SAVE_CONFIG block.
#
# Klipper rewrites the `#*# <-- SAVE_CONFIG -->` section at the bottom
# of printer.cfg every time it runs SAVE_CONFIG (PID calibrations, input
# shaper, bed mesh, probe calibration, etc.). Manual edits there get
# silently overwritten the next time Klipper saves — and worse, a hand
# edit can desync the repo's view of calibration values from what's
# actually on the printer.
#
# This hook blocks Edit/Write tool calls whose target is `printer.cfg`
# AND whose new content touches a `#*#` marker line (the SAVE_CONFIG
# block prefix). All non-SAVE_CONFIG edits to printer.cfg pass through.
#
# Tested against Claude Code's PreToolUse hook contract:
#   - Reads tool-call JSON on stdin
#   - Exit 0 → allow
#   - Exit 2 → deny with stderr as the reason

set -euo pipefail

PAYLOAD=$(cat)

# Fail-open on bad JSON — a buggy hook shouldn't block all edits.
if ! TOOL_NAME=$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))' 2>/dev/null); then
  exit 0
fi
FILE_PATH=$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null || echo "")

case "$TOOL_NAME" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

case "$FILE_PATH" in
  */printer.cfg|printer.cfg) ;;
  *) exit 0 ;;
esac

# Check whether the proposed content contains a SAVE_CONFIG block marker.
# (Heredoc-for-source + piped-stdin can't coexist on the same python3
# invocation — stdin would be consumed by the heredoc and json.load would
# get nothing. Use -c with the full source instead.)
TOUCHES_SAVE_CONFIG=$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
p = json.load(sys.stdin)
i = p.get("tool_input", {})
chunks = []
for k in ("new_string", "content"):
    v = i.get(k)
    if isinstance(v, str):
        chunks.append(v)
edits = i.get("edits")
if isinstance(edits, list):
    for e in edits:
        for k in ("new_string", "content"):
            v = e.get(k) if isinstance(e, dict) else None
            if isinstance(v, str):
                chunks.append(v)
blob = "\n".join(chunks)
print("1" if "#*#" in blob else "0")
' 2>/dev/null || echo "0")

if [[ "$TOUCHES_SAVE_CONFIG" == "1" ]]; then
  cat >&2 <<'MSG'
HOOK BLOCKED: this Edit/Write would change printer.cfg's SAVE_CONFIG block.

The `#*# <-- SAVE_CONFIG -->` block at the bottom of printer.cfg is
managed by Klipper itself (rewritten on every SAVE_CONFIG command).
Manual edits get silently overwritten and desync calibration values
between the repo and the printer.

If you need to update calibration values, do it on the printer
(PID_CALIBRATE / SHAPER_CALIBRATE / PROBE_EDDY_CURRENT_CALIBRATE / etc.,
followed by SAVE_CONFIG), then `sync-from-pi` to bring the new block
into the repo.

To bypass this hook deliberately (e.g., a clean rewrite of the SAVE_CONFIG
section after a calibration session), invoke the edit with `--no-verify`
semantics or disable this hook in .claude/settings.json.
MSG
  exit 2
fi

exit 0
