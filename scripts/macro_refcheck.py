#!/usr/bin/env python3
"""Static reference check for Klipper gcode_macro bodies.

For every command invoked from a [gcode_macro] body, verify it resolves
to a defined macro, a Klipper built-in (tests/builtins.txt), or an
ALLOWLIST entry. Exit 1 with diagnostics if any reference is unknown.
"""

import re
import sys
from pathlib import Path

MACRO_HEADER = re.compile(r"^\[gcode_macro\s+(\S+)\s*\]\s*$")
DELAYED_HEADER = re.compile(r"^\[delayed_gcode\s+(\S+)\s*\]\s*$")
RENAME_FIELD = re.compile(r"^\s*rename_existing\s*:\s*(\S+)\s*$")
GCODE_FIELD = re.compile(r"^gcode\s*:\s*$")
COMMAND_LINE = re.compile(r"^[ \t]+([A-Z][A-Z0-9_]*)\b")

# G/M codes in standard ranges + Klipper internals not always captured by
# the builtins extractor.
ALLOWLIST: set[str] = set()
for _n in range(0, 100):
    ALLOWLIST.add(f"G{_n}")
for _n in range(0, 1000):
    ALLOWLIST.add(f"M{_n}")
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

# Third-party module: eddy-ng commands. Remove this block when the
# [probe_eddy_ng] section is removed from eddy.cfg (eddy migration PR).
# This coupling makes CI catch a migration that updates eddy.cfg but
# forgets to update callers of PROBE_EDDY_NG_*.
ALLOWLIST.update(
    {
        "PROBE_EDDY_NG_TAP",
        "PROBE_EDDY_NG_PROBE",
        "PROBE_EDDY_NG_CALIBRATE",
        "PROBE_EDDY_NG_STATUS",
        "PROBE_EDDY_NG_SET_TAP_OFFSET",
    }
)

# Happy-Hare runtime commands — registered by Python, not by config sections.
# These are MMU commands provided by the Happy-Hare plugin's Python code
# and are not declared as [gcode_macro] blocks anywhere in mmu/*.cfg.
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


def load_builtins(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def collect_defined(paths: list[str]) -> set[str]:
    defined: set[str] = set()
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            for pat in (MACRO_HEADER, DELAYED_HEADER):
                m = pat.match(line)
                if m:
                    defined.add(m.group(1).upper())
                    break
            m = RENAME_FIELD.match(line)
            if m:
                defined.add(m.group(1).upper())
    return defined


def each_macro_body(path: Path):
    """Yield (name, body_first_lineno, body_lines) for each [gcode_macro]."""
    lines = path.read_text().splitlines()
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


def main(paths: list[str]) -> None:
    defined = collect_defined(paths)
    builtins = load_builtins(Path("tests/builtins.txt"))
    known = defined | builtins | ALLOWLIST

    errors = 0
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue
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
