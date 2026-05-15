#!/usr/bin/env python3
"""Static reference check for Klipper gcode_macro bodies.

For every command invoked from a [gcode_macro] body, verify it resolves
to a defined macro (in any passed .cfg), a Klipper built-in (loaded from
tests/builtins.txt), or an ALLOWLIST entry. Catches typos in macro-to-
macro calls, references to deleted macros, and missing ALLOWLIST entries
after removing a third-party Klipper module.

Exit codes:
  0 — clean, no unknown references
  1 — at least one unknown reference (diagnostics printed to stdout)
  2 — invalid invocation: no files passed, or a passed file is missing
"""

import re
import sys
from pathlib import Path

MACRO_HEADER = re.compile(r"^\[gcode_macro\s+(\S+)\s*\]\s*$")
RENAME_FIELD = re.compile(r"^\s*rename_existing\s*:\s*(\S+)\s*$")
GCODE_FIELD = re.compile(r"^[Gg][Cc][Oo][Dd][Ee]\s*:\s*$")
COMMAND_LINE = re.compile(r"^[ \t]+([A-Z][A-Z0-9_]*)\b")

BUILTINS_PATH = Path(__file__).resolve().parent.parent / "tests" / "builtins.txt"

# Allow any GNN / MNNN token unconditionally. Klipper's gcode parser
# accepts arbitrary G/M numbers (it dispatches by registered handler),
# and tightening this to a curated list would just add false positives
# for vendor-specific codes (e.g. M150 RGB on some MCUs).
ALLOWLIST: set[str] = set()
for _n in range(0, 100):
    ALLOWLIST.add(f"G{_n}")
for _n in range(0, 1000):
    ALLOWLIST.add(f"M{_n}")

# Klipper internals not always captured by tests/builtins.txt (typically
# because their `register_command` call spans multiple lines, or the
# command name is built dynamically in Python).
ALLOWLIST.update(
    {
        "SAVE_GCODE_STATE",
        "RESTORE_GCODE_STATE",
        "SET_GCODE_OFFSET",
        "SET_GCODE_VARIABLE",
        "SET_VELOCITY_LIMIT",
        "SET_PRESSURE_ADVANCE",
        "SET_KINEMATIC_POSITION",
        "TEMPERATURE_WAIT",
        "SET_PIN",
        "SET_FAN_SPEED",
        "UPDATE_DELAYED_GCODE",
        "SET_IDLE_TIMEOUT",
        "BED_MESH_CLEAR",
        "RESPOND",
        "SET_DISPLAY_TEXT",
        "PROBE",
        "BED_MESH_CALIBRATE",
        "QUAD_GANTRY_LEVEL",
        "GET_POSITION",
        "STATUS",
        "HELP",
        "QUERY_ENDSTOPS",
        "ACCEPT",
        "ABORT",
        "CANCEL_PRINT",
        "PAUSE",
        "RESUME",
        "BED_SCREWS_ADJUST",
        "PROBE_EDDY_CURRENT_CALIBRATE",
        "PROBE_EDDY_CURRENT_TAP_CALIBRATE",
        "LDC_CALIBRATE_DRIVE_CURRENT",
        "Z_OFFSET_APPLY_PROBE",
    }
)

# Happy-Hare runtime commands — registered by Python (vendor/happy-hare),
# not by [gcode_macro] blocks in mmu/*.cfg. These are not coupled to any
# [section] in printer.cfg; they're stable for as long as Happy-Hare is
# installed on the host.
ALLOWLIST.update(
    {
        "MMU_HOME",
        "MMU_LOAD",
        "MMU_EJECT",
        "MMU_CHANGE_TOOL",
        "MMU_PAUSE",
        "MMU_RECOVER",
        "MMU_SERVO",
        "MMU_SELECT",
        "MMU_SELECT_BYPASS",
        "MMU_STATUS",
        "MMU_STATISTICS",
        "MMU_SENSORS",
        "MMU_TEST_GRIP",
        "MMU_TEST_LOAD",
        "MMU_TEST_MOVE",
        "MMU_TEST_HOMING_MOVE",
        "MMU_TEST_CONFIG",
        "MMU_SOAKTEST_SERVO",
        "MMU_SOAKTEST_LOAD_SEQUENCE",
        "MMU_ENCODER_RUNOUT",
        "MMU_ENCODER_INSERT",
        "MMU_FORM_TIP",
        "MMU_UNLOCK",
        "MMU_RESET",
        "MMU_RESET_STATS",
        "MMU_ENABLE",
        "MMU_DISABLE",
        "MMU_REMAP_TTG",
        "MMU_ENDLESS_SPOOL",
        "MMU_CHECK_GATE",
        "MMU_GATE_MAP",
        "MMU_TOOL_OVERRIDES",
        "MMU_PRELOAD",
        "MMU_PRINT_START",
        "MMU_PRINT_END",
        "MMU_LOG_LEVEL",
        "MMU_SET_GATE_MAP",
        "MMU_CALIBRATE_GEAR",
        "MMU_CALIBRATE_ENCODER",
        "MMU_CALIBRATE_SELECTOR",
        "MMU_CALIBRATE_BOWDEN",
        "MMU_CALIBRATE_GATES",
        "_MMU_SAVE_TOOLHEAD_POSITION",
        "_MMU_RESTORE_TOOLHEAD_POSITION",
        "_MMU_STEP_LOAD_GATE",
        "_MMU_STEP_UNLOAD_GATE",
        "_MMU_STEP_LOAD_TOOLHEAD",
        "_MMU_STEP_UNLOAD_TOOLHEAD",
        "_MMU_STEP_HOME_EXTRUDER",
        "_MMU_STEP_MOVE",
        "_MMU_STEP_HOMING_MOVE",
        "_MMU_AUTO_HOME",
        "_MMU_SYNC_GEAR_MOTOR",
        "BLOBIFIER",
        "BLOBIFIER_CLEAN",
        "BLOBIFIER_PARK",
        "BLOBIFIER_PURGE",
        "BLOBIFIER_POOP",
        # Happy-Hare Python-registered commands not in mmu_software.cfg headers
        "MMU_LOG",
        "MMU_STATS",
        "MMU_UNLOAD",
        "MMU_TTG_MAP",
        "MMU_SLICER_TOOL_MAP",
        "MMU_SYNC_FEEDBACK",
        "MMU_TEST_FORM_TIP",
    }
)


def load_builtins() -> set[str]:
    """Read tests/builtins.txt (anchored to this script's location).

    Exits with code 2 if the file is missing — without it, real Klipper
    builtins would be silently flagged as unknown commands.
    """
    if not BUILTINS_PATH.exists():
        print(
            f"macro_refcheck: missing {BUILTINS_PATH} — run `make builtins`",
            file=sys.stderr,
        )
        sys.exit(2)
    return {
        line.strip()
        for line in BUILTINS_PATH.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def collect_defined(paths: list[Path]) -> set[str]:
    """Build the set of macro names that are callable from gcode.

    Includes: [gcode_macro X] headers, rename_existing: Y targets.
    Excludes: [delayed_gcode X] IDs — those are NOT directly callable
    commands; they're triggered by UPDATE_DELAYED_GCODE ID=X. Treating
    them as callable creates false negatives (a macro typo that happens
    to match a delayed_gcode ID would pass refcheck but fail at runtime).
    Codex flagged this — P2.
    """
    defined: set[str] = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = MACRO_HEADER.match(line)
            if m:
                defined.add(m.group(1).upper())
                continue
            m = RENAME_FIELD.match(line)
            if m:
                defined.add(m.group(1).upper())
    return defined


def each_macro_body(path: Path):
    """Yield (name, body_first_lineno, body_lines) for each [gcode_macro]
    that has a gcode: field. body_first_lineno is the 1-based line number
    of the first body line (used for error messages). Macros with no
    gcode: field are silently skipped (they're rare and harmless).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        m = MACRO_HEADER.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        j = i + 1
        while j < len(lines) and not lines[j].startswith("["):
            if GCODE_FIELD.match(lines[j]):
                # body starts at j+1; collect until next non-indented line
                k = j + 1
                while k < len(lines) and (
                    lines[k].startswith((" ", "\t")) or lines[k].strip() == ""
                ):
                    k += 1
                # body_first_lineno is 1-based line number of lines[j+1]
                yield name, j + 2, lines[j + 1 : k]
                j = k
                continue
            j += 1
        i = j


def extract_commands(body_lines: list[str]):
    for offset, line in enumerate(body_lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("{%") or stripped.startswith("{{"):
            continue
        m = COMMAND_LINE.match(line)
        if m:
            yield offset, m.group(1).upper()


def validate_inputs(path_strs: list[str]) -> list[Path]:
    """Reject empty arg list and missing files. Exits 2 on failure."""
    if not path_strs:
        print("macro_refcheck: no files specified", file=sys.stderr)
        sys.exit(2)
    paths = [Path(p) for p in path_strs]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        for m in missing:
            print(f"macro_refcheck: file not found: {m}", file=sys.stderr)
        sys.exit(2)
    return paths


def main(path_strs: list[str]) -> None:
    paths = validate_inputs(path_strs)
    defined = collect_defined(paths)
    builtins = load_builtins()
    known = defined | builtins | ALLOWLIST

    errors = 0
    for path in paths:
        for macro_name, body_start, body in each_macro_body(path):
            for offset, cmd in extract_commands(body):
                if cmd not in known:
                    print(
                        f"{path}:{body_start + offset}: "
                        f"[gcode_macro {macro_name}] "
                        f"references unknown command '{cmd}'"
                    )
                    errors += 1
    if errors:
        print(
            f"\n{errors} unknown reference(s). "
            "If a flagged command is legitimate, add it to ALLOWLIST in "
            "scripts/macro_refcheck.py or to tests/builtins.txt."
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
