#!/usr/bin/env python3
"""Layer 7 (one-shot) macro behavior snapshot.

Drives Klipper's `scripts/test_klippy.py` against `config/printer.cfg` with
a fixed gcode sequence and captures the dispatcher output for diffing
before vs. after a refactor.

Usage (typically via Docker on darwin hosts):
    python scripts/macro_behavior_diff.py before
    python scripts/macro_behavior_diff.py after

Writes `tests/snapshots/macro_behavior_<label>.txt`. Diff the two; any
non-whitespace, non-comment delta indicates a behavior change.

Mirrors the CI klippy-smoke setup: copies `config/printer.cfg` to a temp
location with MMU includes stripped (Happy-Hare's mmu.py crashes under
test_klippy.py — see .github/workflows/ci.yml for the rationale).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO / "tests/snapshots"
KLIPPER_DIR = REPO / "vendor/klipper"
DICT_DIR = REPO / "tests/dict"

# Fixed gcode set. Picked to exercise every macro PR-B touches plus a
# representative slice of unchanged macros so the diff also acts as a
# control (these should not change between runs).
GCODE_SEQUENCE = [
    "PARKCENTER",
    "BEDFANSSLOW",
    "BEDFANSFAST",
    "BEDFANSOFF",
    "M140 S110",
    "M190 S110",
    "M109 S240",
    "TURN_OFF_HEATERS",
    "HEATSOAK T=110 C=30 MOVE=0 WAIT=0",
    "PRINT_END",
    "OFF",
]


# Per-run varying lines we don't want polluting the diff.
_NOISE_PATTERNS = [
    (re.compile(r"/tmp/layer7-[A-Za-z0-9_]+"), "/tmp/layer7-NORMALIZED"),
    (
        re.compile(r"^Start printer at .*$", re.MULTILINE),
        "Start printer at NORMALIZED",
    ),
]


def _normalize(text: str) -> str:
    for pat, repl in _NOISE_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _strip_mmu_includes(src: Path, dst: Path) -> None:
    """Copy `src` to `dst`, dropping `[include mmu/...]` lines.

    Matches the CI klippy-smoke job (.github/workflows/ci.yml). Happy-Hare's
    mmu.py crashes at handle_connect under test_klippy.py.
    """
    if not src.exists():
        raise FileNotFoundError(f"Expected printer config at {src} (REPO root: {REPO})")
    lines = src.read_text().splitlines(keepends=True)
    filtered = [ln for ln in lines if not ln.startswith("[include mmu/")]
    dst.write_text("".join(filtered))


def _build_test_file(staging: Path, printer_cfg: Path) -> Path:
    """Create a .test file driving test_klippy.py against the staged config."""
    # test_klippy.py resolves CONFIG / DICTIONARY paths relative to the
    # .test file's directory. We put the .test file in staging/ alongside
    # the staged printer.cfg; dictionaries live in tests/dict.
    lines = [
        f"CONFIG {printer_cfg.name}",
        "DICTIONARY mcu.dict z=mcu.dict EBB=ebb-usb.dict eddy=eddy.dict mmu=easy-brd.dict",
        *GCODE_SEQUENCE,
    ]
    out = staging / "_layer7.test"
    out.write_text("\n".join(lines) + "\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=["before", "after"])
    args = parser.parse_args()

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    test_klippy = KLIPPER_DIR / "scripts/test_klippy.py"
    if not test_klippy.exists():
        print(
            "vendor/klipper not initialized — run `git submodule update --init vendor/klipper`",
            file=sys.stderr,
        )
        return 2

    # test_klippy.py leaves _test_.log / _test_output* behind on failure,
    # and Klipper's logger appends rather than truncates — without cleanup
    # the snapshot grows with each run. Clear stale artifacts. missing_ok
    # tolerates the race where a concurrent `before`/`after` run unlinks
    # the same path between glob and unlink (concurrent invocations are
    # still not safe overall — they share the cwd — but at least the
    # cleanup doesn't crash).
    for stale in KLIPPER_DIR.glob("_test_*"):
        stale.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="layer7-") as tmp:
        staging = Path(tmp)
        staged_cfg = staging / "printer.cfg"
        _strip_mmu_includes(REPO / "config/printer.cfg", staged_cfg)
        # test_klippy.py looks for [include] paths relative to the CONFIG
        # file. Copy the rest of config/ next to the staged printer.cfg so
        # those includes resolve.
        for child in (REPO / "config").iterdir():
            if child.name == "printer.cfg":
                continue
            dst = staging / child.name
            if child.is_dir():
                shutil.copytree(child, dst, symlinks=False)
            else:
                shutil.copy2(child, dst)
        test_file = _build_test_file(staging, staged_cfg)

        cmd = [
            sys.executable,
            str(test_klippy),
            "-d",
            str(DICT_DIR),
            str(test_file),
        ]
        proc = subprocess.run(
            cmd, cwd=KLIPPER_DIR, capture_output=True, text=True, check=False
        )

    out = SNAPSHOT_DIR / f"macro_behavior_{args.label}.txt"
    stdout = _normalize(proc.stdout)
    stderr = _normalize(proc.stderr)
    snapshot = (
        f"# Layer 7 macro behavior snapshot — {args.label}\n"
        f"# gcode: {GCODE_SEQUENCE}\n"
        f"# exit={proc.returncode}\n"
        f"-- STDOUT --\n{stdout}\n"
        f"-- STDERR --\n{stderr}\n"
    )
    out.write_text(snapshot)
    print(f"Wrote {out} (test_klippy exit={proc.returncode})")
    # Distinguish "gcode failed mid-execution" (expected — no calibration
    # data in CI) from "klippy never started" (test_klippy.py / docker /
    # vendor/klipper unhealthy). A successful start always emits "Start
    # printer at " on stdout; if that marker is missing, the snapshot is
    # near-empty and would falsely diff clean against another bad run.
    if "Start printer at" not in proc.stdout:
        print(
            "ERROR: klippy did not reach start — snapshot is unusable. "
            "Check test_klippy.py output above.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
