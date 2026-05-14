# CI Scaffold — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GitHub Actions CI that catches Klipper config errors before they sync to the printer — by running Klipper's own parser/simulator (`test_klippy.py`) with a macro-graph smoke g-code sequence, plus a jinja2 lint and a static macro-reference check.

**Architecture:** Two parallel jobs in `.github/workflows/ci.yml`. Job 1 runs `vendor/klipper/scripts/test_klippy.py` against `tests/voron-2-611.test` (CONFIG=printer.cfg, DICTIONARY=our 5 MCUs, smoke gcode). Job 2 runs two ~80-line Python scripts (`scripts/jinja2_lint.py`, `scripts/macro_refcheck.py`) over every `[gcode_macro]` body. MCU dict files committed under `tests/dict/` (compiled once from `firmware/*.config` against `vendor/klipper`).

**Tech Stack:** GitHub Actions (ubuntu-22.04), Python 3.11, `jinja2`, `cffi`, Klipper's own test framework, `gh` CLI for remote setup, Makefile for local-run parity.

**Spec:** `docs/superpowers/specs/2026-05-13-ci-scaffold.md` (commit `80bede0`).

---

## File structure

**Modified in this repo:**

| File | Scope | Reason |
|---|---|---|
| `CLAUDE.md` | Add "## CI checks" section: how `make test` works, when to regen dicts/builtins. | Spec §5.2 |

**Created:**

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Workflow: two parallel jobs on PR + push:main. |
| `tests/voron-2-611.test` | CONFIG + multi-MCU DICTIONARY + smoke gcode. |
| `tests/dict/mcu.dict` | LPC1769 (both SKR 1.4 boards — single firmware build). |
| `tests/dict/ebb-usb.dict` | RP2040 build for the EBB SB toolhead. |
| `tests/dict/eddy.dict` | RP2040 build for the BTT Eddy probe. |
| `tests/dict/easy-brd.dict` | SAMD21 build for the ERCF EASY-BRD. |
| `tests/README.md` | Local-run + regen instructions. |
| `tests/builtins.txt` | Auto-generated list of Klipper built-in g-code commands. |
| `tests/fixtures/macros_good.cfg` | Test fixture for the lint scripts (passing case). |
| `tests/fixtures/macros_bad_jinja.cfg` | Test fixture: macro body with `{% if foo` (unclosed). |
| `tests/fixtures/macros_bad_refs.cfg` | Test fixture: macro that calls a non-existent macro. |
| `tests/test_jinja2_lint.py` | Pytest-style integration tests for `jinja2_lint.py`. |
| `tests/test_macro_refcheck.py` | Pytest-style integration tests for `macro_refcheck.py`. |
| `scripts/jinja2_lint.py` | Lint script (b). |
| `scripts/macro_refcheck.py` | Reference-check script (c). |
| `scripts/extract_builtins.py` | Regenerates `tests/builtins.txt` from `vendor/klipper`. |
| `Makefile` | `make test`, `make builtins` targets. |

**Naming note (clarification from spec §6.7 verify-on-implementation):** dict file names mirror the `firmware/*.config` files 1:1 (`mcu.config` → `mcu.dict`, etc.). The pinned `vendor/klipper`'s CI script (`ci-build.sh:61`) confirms this is Klipper's own naming convention.

---

## Pre-flight assumptions

- Working in the worktree from Task 1 (`feat/ci-scaffold` branch).
- `ssh pi@mainsailos.local` works passwordless (set up earlier).
- `gh` CLI is installed and authenticated (`gh auth status` returns OK). If not, prompt the user to run `gh auth login` interactively.
- `arm-none-eabi-gcc` and `gcc-avr` toolchains are available on the Mac for compiling MCU firmware locally (`brew install --cask gcc-arm-embedded` and `brew install avr-gcc`). The Pi alternative is in Task 2.

---

## Task 1: Set up isolated worktree

**Files:** none yet (creating the worktree).

- [ ] **Step 1: Invoke the using-git-worktrees skill**

```
Skill: superpowers:using-git-worktrees
```

Expected: skill announces, detects normal repo (not already a worktree, not a submodule), calls `EnterWorktree` with branch name `feat/ci-scaffold`.

- [ ] **Step 2: Verify**

```sh
git branch --show-current
```
Expected: `feat/ci-scaffold`

```sh
git status -sb
```
Expected: `## feat/ci-scaffold` and no other lines.

```sh
git log --oneline -1
```
Expected: same commit as `main` HEAD.

---

## Task 2: Source MCU dict files

**Files:**
- Create: `tests/dict/mcu.dict`, `tests/dict/ebb-usb.dict`, `tests/dict/eddy.dict`, `tests/dict/easy-brd.dict`

The fastest path: build them on the Pi (which already has all toolchains installed and used to flash the MCUs in the first place). One make per firmware config.

- [ ] **Step 1: Stage `firmware/*.config` on the Pi**

```sh
scp firmware/mcu.config firmware/ebb-usb.config firmware/eddy.config firmware/easy-brd.config pi@mainsailos.local:/tmp/voron-ci-dicts/
ssh pi@mainsailos.local 'mkdir -p /tmp/voron-ci-dicts && ls -la /tmp/voron-ci-dicts/'
```

Expected: four `.config` files listed on the Pi at `/tmp/voron-ci-dicts/`.

- [ ] **Step 2: Build each dict on the Pi**

```sh
ssh pi@mainsailos.local 'bash -s' <<'BUILD'
set -eux
cd ~/klipper
for CFG in /tmp/voron-ci-dicts/mcu.config /tmp/voron-ci-dicts/ebb-usb.config /tmp/voron-ci-dicts/eddy.config /tmp/voron-ci-dicts/easy-brd.config; do
  NAME=$(basename "$CFG" .config)
  make clean
  cp "$CFG" .config
  make olddefconfig
  make
  cp out/klipper.dict "/tmp/voron-ci-dicts/${NAME}.dict"
done
ls -la /tmp/voron-ci-dicts/*.dict
BUILD
```

Expected: four `.dict` files emitted, ~50 KB each. If any board's build fails, **stop** and triage — likely a Klipper version mismatch between this repo's pinned `vendor/klipper` and the Pi's `~/klipper`. The dicts must match Klipper's protocol, not the firmware features, so any recent-enough klipper will do — but they must be from a klipper compatible with our pinned vendor commit.

Quick compatibility check after the build:

```sh
ssh pi@mainsailos.local 'cd ~/klipper && git log -1 --format=%H'
```

If this returns `4767a8ed97c57e4bb2ecf60fd72e345f58dfa3fc` (our pinned vendor/klipper commit), the dicts will be exact-match. If it returns a different commit, the dicts will work for parsing but may have feature additions; that's fine for our purposes.

- [ ] **Step 3: Restore the original `.config` on the Pi**

The build sequence overwrote `~/klipper/.config` with the last loop iteration's value (`easy-brd.config`). Restore from the actual board's saved config (the Pi's main board is the LPC1769 SKR 1.4 XYE board):

```sh
ssh pi@mainsailos.local 'cd ~/klipper && cp /tmp/voron-ci-dicts/mcu.config .config && make olddefconfig'
```

Expected: command exits 0. The Pi's `~/klipper/.config` is back to the main-board build config. (We deliberately do NOT re-run `make` and `make flash` — that's a deploy operation outside this plan's scope.)

- [ ] **Step 4: Pull the dicts into the worktree**

```sh
mkdir -p tests/dict
scp 'pi@mainsailos.local:/tmp/voron-ci-dicts/*.dict' tests/dict/
ls -la tests/dict/
```

Expected: four `.dict` files in `tests/dict/`, ~50 KB each.

- [ ] **Step 5: Clean up the Pi's staging dir**

```sh
ssh pi@mainsailos.local 'rm -rf /tmp/voron-ci-dicts'
```

Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```sh
git add tests/dict/
git commit -m "ci: vendor MCU dict files for the 5 boards on Voron 2.611

Built on the Pi from firmware/*.config against the printer's installed
Klipper. Sizes match Klipper's emitted klipper.dict format. Used by
tests/voron-2-611.test via DICTIONARY directive."
```

---

## Task 3: Verify test_klippy.py runs against the current config

This is the spec §10 viability gate. If `test_klippy.py` errors on the current `[probe_eddy_ng]` config (third-party module under simulator), we choose between stubbing or deferring.

**Files:** none modified (probe only).

- [ ] **Step 1: Create a minimal probe .test file (parse-only)**

```sh
cat > /tmp/probe-voron-2-611.test <<'EOF'
# Minimal viability probe — config parses, MCUs load, no g-code.
CONFIG ../../printer.cfg
DICTIONARY mcu.dict z=mcu.dict EBB=ebb-usb.dict eddy=eddy.dict mmu=easy-brd.dict
EOF
```

- [ ] **Step 2: Run it**

```sh
cd vendor/klipper
python scripts/test_klippy.py -d ../../tests/dict /tmp/probe-voron-2-611.test 2>&1 | tee /tmp/probe-result.log
cd ../..
```

Expected outcomes:

- **Pass** (`Finished /tmp/probe-voron-2-611.test`): proceed with Task 4 as written.
- **Fail with parse error**: probably means a vendor mismatch or include path issue. Debug — likely fixable by adjusting CONFIG path or dict naming.
- **Fail with "Unable to import module probe_eddy_ng"** or "ldc1612_ng": the third-party module isn't loadable in simulator. Choose:
  - **(a) Stub strategy:** in Task 4, the .test file will declare `[probe_eddy_ng]` and the related blocks via a stub-include shim. Add a follow-up sub-task here to write `tests/stubs/eddy_ng.cfg` that satisfies the simulator without exercising the actual module.
  - **(b) Defer strategy:** stop this plan, document in `memory/troubleshooting-log.md` that the CI scaffold is blocked until eddy-ng is removed (i.e., until the eddy migration ships), and resume there.

- [ ] **Step 3: Record decision**

In either pass or fail case, append a note to `memory/troubleshooting-log.md` under "Resolved":

```
### 2026-05-13 — CI viability probe (current eddy-ng config)
- Result: [PASS | FAIL with <error>]
- Decision: [continue with smoke test as written | stub eddy-ng in tests/stubs/ | defer CI scaffold until eddy migration]
```

- [ ] **Step 4: Commit memory note + (if pass) move on. If fail-and-defer, halt.**

```sh
git add memory/troubleshooting-log.md
git commit -m "ci: record viability probe for test_klippy.py against current config"
```

If "fail-and-defer" path was chosen, **stop here**. The plan is paused.

---

## Task 4: Write the smoke .test file

**Files:**
- Create: `tests/voron-2-611.test`

- [ ] **Step 1: Write the .test file**

```sh
mkdir -p tests
cat > tests/voron-2-611.test <<'EOF'
# Voron 2.611 — parse + macro-graph smoke under simulated MCUs.
# Run via: cd vendor/klipper && python scripts/test_klippy.py \
#           -d ../../tests/dict ../../tests/voron-2-611.test

CONFIG ../../printer.cfg
DICTIONARY mcu.dict z=mcu.dict EBB=ebb-usb.dict eddy=eddy.dict mmu=easy-brd.dict

# --- Boot + leveling smoke ---
G28
QUAD_GANTRY_LEVEL
BED_MESH_CALIBRATE METHOD=rapid_scan

# --- Macro graph smoke (exercises PRINT_START → all sub-macros) ---
PRINT_WARMUP BED=60 EXTRUDER=200
HEATSOAK T=60 C=30 MOVE=1 WAIT=0
PRINT_START BED=60 EXTRUDER=200 CHAMBER=0
PRINT_END
OFF

# --- MMU surface ---
MMU_STATUS

# --- Parking macros (one of each) ---
PARKCENTER
PARKFRONT
PARKREAR
PARKBED
EOF
```

- [ ] **Step 2: Run it locally**

```sh
cd vendor/klipper
python scripts/test_klippy.py -d ../../tests/dict ../../tests/voron-2-611.test
cd ../..
```

Expected: `Finished tests/voron-2-611.test` (the run prints `Starting tests/voron-2-611.test (printer.cfg)` and ends successfully).

If it fails, the error message points at a specific gcode line in the smoke sequence. The fix is usually: trim the offending line until the .test passes. Examples of likely failures:
- `MMU_STATUS` may need MMU homing first → add `MMU_HOME` (or remove the line if it can't be simulated)
- `HEATSOAK` may try to `TEMPERATURE_WAIT` for a chamber temp that never arrives in sim → check its body; trim from .test if needed.

For any line removed, **note it in `tests/README.md`** (Task 13) so future-you knows why.

- [ ] **Step 3: Commit**

```sh
git add tests/voron-2-611.test
git commit -m "ci: tests/voron-2-611.test — smoke gcode for klippy parse"
```

---

## Task 5: Write `scripts/jinja2_lint.py` with TDD

**Files:**
- Create: `tests/fixtures/macros_good.cfg`
- Create: `tests/fixtures/macros_bad_jinja.cfg`
- Create: `tests/test_jinja2_lint.py`
- Create: `scripts/jinja2_lint.py`

- [ ] **Step 1: Write the fixture files**

```sh
mkdir -p tests/fixtures
cat > tests/fixtures/macros_good.cfg <<'EOF'
# Fixture: every macro body parses as valid jinja2.

[gcode_macro CG28_OK]
gcode:
    {% if "xyz" not in printer.toolhead.homed_axes %}
        G28
    {% endif %}

[gcode_macro PARK_OK]
description: park toolhead
gcode:
    SAVE_GCODE_STATE NAME=PARK
    G90
    G0 X{printer.toolhead.axis_maximum.x/2} Y0 F6000
    RESTORE_GCODE_STATE NAME=PARK
EOF

cat > tests/fixtures/macros_bad_jinja.cfg <<'EOF'
# Fixture: BROKEN — unclosed {% if %} block.

[gcode_macro BROKEN_IF]
gcode:
    {% if printer.toolhead.homed_axes
        G28
    G0 X10 Y10
EOF
```

- [ ] **Step 2: Write the failing tests**

```sh
cat > tests/test_jinja2_lint.py <<'EOF'
"""Integration tests for scripts/jinja2_lint.py."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LINT = REPO / "scripts" / "jinja2_lint.py"
FIXTURES = REPO / "tests" / "fixtures"


def run(*args):
    return subprocess.run(
        [sys.executable, str(LINT), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def test_good_cfg_exits_zero():
    r = run(str(FIXTURES / "macros_good.cfg"))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_bad_jinja_exits_one_and_names_macro():
    r = run(str(FIXTURES / "macros_bad_jinja.cfg"))
    assert r.returncode == 1
    assert "BROKEN_IF" in r.stdout
    assert "macros_bad_jinja.cfg:" in r.stdout
EOF
```

- [ ] **Step 3: Run tests to verify they fail**

```sh
python -m pytest tests/test_jinja2_lint.py -v
```

Expected: both tests FAIL with `FileNotFoundError` or similar — `scripts/jinja2_lint.py` does not exist yet.

If pytest is not installed:

```sh
pip install pytest jinja2
```

- [ ] **Step 4: Write the script**

```sh
mkdir -p scripts
cat > scripts/jinja2_lint.py <<'EOF'
#!/usr/bin/env python3
"""
Parse every [gcode_macro X] body in the given .cfg files as a jinja2 template.
Exit 1 on any TemplateSyntaxError; print one diagnostic per error.
"""
import re
import sys
from pathlib import Path

from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError

MACRO_HEADER = re.compile(r"^\[gcode_macro\s+(\S+)\s*\]\s*$")
GCODE_FIELD = re.compile(r"^gcode\s*:\s*$")


def each_macro_body(path):
    """Yield (macro_name, body_first_line_no, body_text) for each [gcode_macro] block."""
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
                body_first = j + 1
                k = body_first
                while k < len(lines) and (
                    lines[k].startswith((" ", "\t")) or lines[k].strip() == ""
                ):
                    k += 1
                body = "\n".join(line.lstrip() for line in lines[body_first:k])
                yield name, body_first + 1, body
                j = k
                continue
            j += 1
        i = j


def main(paths):
    env = Environment()
    errors = 0
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue
        for name, lineno, body in each_macro_body(path):
            try:
                env.parse(body)
            except TemplateSyntaxError as e:
                abs_line = lineno + (e.lineno or 1) - 1
                print(f"{path}:{abs_line}: [gcode_macro {name}] {e.message}")
                errors += 1
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
EOF
chmod +x scripts/jinja2_lint.py
```

- [ ] **Step 5: Run tests to verify they pass**

```sh
python -m pytest tests/test_jinja2_lint.py -v
```

Expected: both tests PASS.

- [ ] **Step 6: Run against the real repo configs**

```sh
python scripts/jinja2_lint.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/base/*.cfg mmu/addons/*.cfg mmu/optional/*.cfg
echo "exit: $?"
```

Expected: exit 0 (no errors). If any real macro body has a jinja2 issue, that's a real bug — investigate and fix in a separate commit before continuing.

- [ ] **Step 7: Commit**

```sh
git add tests/fixtures/macros_good.cfg tests/fixtures/macros_bad_jinja.cfg \
        tests/test_jinja2_lint.py scripts/jinja2_lint.py
git commit -m "ci: jinja2 lint for [gcode_macro] bodies with tests"
```

---

## Task 6: Write `scripts/extract_builtins.py` and generate `tests/builtins.txt`

**Files:**
- Create: `scripts/extract_builtins.py`
- Create: `tests/builtins.txt` (generated)

This script is run manually when bumping `vendor/klipper`, not in CI. Tests are minimal — the script's correctness is checkable by inspecting its output.

- [ ] **Step 1: Write the script**

```sh
cat > scripts/extract_builtins.py <<'EOF'
#!/usr/bin/env python3
"""
Regenerate tests/builtins.txt from vendor/klipper/klippy/extras/*.py and
vendor/klipper/klippy/gcode.py by grepping for register_command(...) calls.
Run manually when bumping vendor/klipper.
"""
import re
import sys
from pathlib import Path

REGISTER = re.compile(
    r"register(?:_mux)?_command\s*\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
)


def main():
    root = Path("vendor/klipper/klippy")
    if not root.exists():
        sys.stderr.write(f"error: {root} not found (run from repo root)\n")
        sys.exit(2)
    paths = [root / "gcode.py"] + sorted((root / "extras").glob("*.py"))
    cmds = set()
    for p in paths:
        if not p.exists():
            continue
        for m in REGISTER.finditer(p.read_text()):
            cmds.add(m.group(1))
    out = Path("tests/builtins.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# Auto-generated by scripts/extract_builtins.py from vendor/klipper.\n"
        "# Regenerate via `make builtins` after bumping vendor/klipper.\n"
        + "\n".join(sorted(cmds))
        + "\n"
    )
    print(f"Wrote {len(cmds)} commands to {out}")


if __name__ == "__main__":
    main()
EOF
chmod +x scripts/extract_builtins.py
```

- [ ] **Step 2: Run it to generate `tests/builtins.txt`**

```sh
python scripts/extract_builtins.py
head -20 tests/builtins.txt
wc -l tests/builtins.txt
```

Expected: prints `Wrote NNN commands to tests/builtins.txt`. `wc -l` should be >100 (Klipper has many built-in g-code commands). `head` should show familiar names like `BED_MESH_CALIBRATE`, `PROBE`, `SET_GCODE_OFFSET`.

- [ ] **Step 3: Smoke-check the output**

```sh
grep -E '^BED_MESH_CALIBRATE$|^PROBE$|^G28$' tests/builtins.txt
```

`G28` will NOT appear — it's registered differently in Klipper's gcode.py (as a `register_mux_command` for the homing module via the `cmd_G28_help` pattern). That's fine — `G28` lives in our `ALLOWLIST` in `macro_refcheck.py` (Task 7).

`BED_MESH_CALIBRATE` and `PROBE` should both appear.

- [ ] **Step 4: Commit**

```sh
git add scripts/extract_builtins.py tests/builtins.txt
git commit -m "ci: extract Klipper builtin command list from vendor/klipper"
```

---

## Task 7: Write `scripts/macro_refcheck.py` with TDD

**Files:**
- Create: `tests/fixtures/macros_bad_refs.cfg`
- Create: `tests/test_macro_refcheck.py`
- Create: `scripts/macro_refcheck.py`

- [ ] **Step 1: Write the fixture**

```sh
cat > tests/fixtures/macros_bad_refs.cfg <<'EOF'
# Fixture: macro that calls a non-existent macro.

[gcode_macro CALLER_BAD]
gcode:
    G28
    THIS_MACRO_DOES_NOT_EXIST
    G0 X10 Y10
EOF
```

- [ ] **Step 2: Write the failing tests**

```sh
cat > tests/test_macro_refcheck.py <<'EOF'
"""Integration tests for scripts/macro_refcheck.py."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RC = REPO / "scripts" / "macro_refcheck.py"
FIXTURES = REPO / "tests" / "fixtures"


def run(*args):
    return subprocess.run(
        [sys.executable, str(RC), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def test_good_cfg_exits_zero():
    # macros_good.cfg uses SAVE_GCODE_STATE (allowlist), G28/G90/G0 (gcode prefix)
    r = run(str(FIXTURES / "macros_good.cfg"))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_bad_refs_flags_unknown_macro():
    r = run(str(FIXTURES / "macros_bad_refs.cfg"))
    assert r.returncode == 1
    assert "THIS_MACRO_DOES_NOT_EXIST" in r.stdout
    assert "CALLER_BAD" in r.stdout


def test_rename_existing_is_treated_as_defining():
    # Macro A renames M99109 → M99109 is defined; B calls M99109 → OK.
    cfg = REPO / "tests" / "fixtures" / "_rename_chain.cfg"
    cfg.write_text(
        "[gcode_macro M109]\n"
        "rename_existing: M99109\n"
        "gcode:\n"
        "    G4 P1\n"
        "\n"
        "[gcode_macro CALLER]\n"
        "gcode:\n"
        "    M99109\n"
    )
    try:
        r = run(str(cfg))
        assert r.returncode == 0, f"stdout={r.stdout!r}"
    finally:
        cfg.unlink(missing_ok=True)
EOF
```

- [ ] **Step 3: Run tests to verify they fail**

```sh
python -m pytest tests/test_macro_refcheck.py -v
```

Expected: all three FAIL because `scripts/macro_refcheck.py` doesn't exist yet.

- [ ] **Step 4: Write the script**

```sh
cat > scripts/macro_refcheck.py <<'EOF'
#!/usr/bin/env python3
"""
Static reference check: for every gcode command invoked from a [gcode_macro]
body, verify it resolves to a defined macro, a known Klipper built-in
(tests/builtins.txt), or an entry in ALLOWLIST.
"""
import re
import sys
from pathlib import Path

MACRO_HEADER = re.compile(r"^\[gcode_macro\s+(\S+)\s*\]\s*$")
RENAME_FIELD = re.compile(r"^\s*rename_existing\s*:\s*(\S+)\s*$")
GCODE_FIELD = re.compile(r"^gcode\s*:\s*$")
DELAYED_HEADER = re.compile(r"^\[delayed_gcode\s+(\S+)\s*\]\s*$")
COMMAND_LINE = re.compile(r"^\s+([A-Z][A-Z0-9_]*)\b")

# G/M-codes in standard ranges + Klipper internals not always captured cleanly
# by extract_builtins.py.
ALLOWLIST = set()
for n in range(0, 100):
    ALLOWLIST.add(f"G{n}")
for n in range(0, 1000):
    ALLOWLIST.add(f"M{n}")
ALLOWLIST.update({
    "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE",
    "SET_GCODE_OFFSET", "SET_GCODE_VARIABLE",
    "SET_VELOCITY_LIMIT", "SET_PRESSURE_ADVANCE",
    "SET_KINEMATIC_POSITION",
    "TEMPERATURE_WAIT", "SET_PIN", "SET_FAN_SPEED",
    "UPDATE_DELAYED_GCODE", "SET_IDLE_TIMEOUT",
    "BED_MESH_CLEAR", "RESPOND",
    "SET_DISPLAY_TEXT",
    "PROBE", "BED_MESH_CALIBRATE", "QUAD_GANTRY_LEVEL",
    "GET_POSITION", "STATUS", "HELP", "QUERY_ENDSTOPS",
    "ACCEPT", "ABORT",  # interactive helpers
    "CANCEL_PRINT", "PAUSE", "RESUME",  # mainsail-config provides these
    "BED_SCREWS_ADJUST",
    "PROBE_EDDY_CURRENT_CALIBRATE", "PROBE_EDDY_CURRENT_TAP_CALIBRATE",
    "LDC_CALIBRATE_DRIVE_CURRENT", "Z_OFFSET_APPLY_PROBE",
})

# Third-party modules currently loaded by printer.cfg. Each entry is keyed
# to a module — remove the entry when the corresponding [module ...] section
# leaves printer.cfg. This coupling makes CI catch the intermediate state of
# a module migration (e.g., section removed but a macro still calls the
# module's commands).
#
# eddy-ng (vendor/eddy-ng/probe_eddy_ng.py) — remove with the eddy migration PR
ALLOWLIST.update({
    "PROBE_EDDY_NG_TAP",
    "PROBE_EDDY_NG_PROBE",
    "PROBE_EDDY_NG_CALIBRATE",
    "PROBE_EDDY_NG_STATUS",
    "PROBE_EDDY_NG_SET_TAP_OFFSET",
})


def load_builtins(path):
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def collect_defined(paths):
    defined = set()
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


def each_macro_body(path):
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
                k = j + 1
                while k < len(lines) and (
                    lines[k].startswith((" ", "\t")) or lines[k].strip() == ""
                ):
                    k += 1
                yield name, j + 2, lines[j + 1:k]
                j = k
                continue
            j += 1
        i = j


def extract_commands(body_lines):
    for offset, line in enumerate(body_lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("{%") or stripped.startswith("{{"):
            continue
        m = COMMAND_LINE.match(line)
        if m:
            yield offset, m.group(1).upper()


def main(paths):
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
EOF
chmod +x scripts/macro_refcheck.py
```

- [ ] **Step 5: Run tests to verify they pass**

```sh
python -m pytest tests/test_macro_refcheck.py -v
```

Expected: all three PASS.

- [ ] **Step 6: Run against the real repo configs**

```sh
python scripts/macro_refcheck.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/base/*.cfg mmu/addons/*.cfg mmu/optional/*.cfg
echo "exit: $?"
```

Expected outcomes:
- **Exit 0**: no unknown references. Great.
- **Exit 1 with output**: the script flagged commands it doesn't recognize. For each:
  1. Is it a real bug? (Macro X calls something that genuinely doesn't exist.) → fix it as a separate commit.
  2. Is it a legitimate command the script doesn't know about? (A Happy-Hare macro defined in a file we forgot to pass to the script; a Klipper command not captured by `extract_builtins.py`'s regex; a slicer-injected variable name.) → add to `ALLOWLIST` in `scripts/macro_refcheck.py` OR include the missing config file in the argument list.

The Happy-Hare config files at `mmu/base/*.cfg`, `mmu/addons/*.cfg`, `mmu/optional/*.cfg` define many `MMU_*` macros — make sure they're all in the argument list.

- [ ] **Step 7: Add `tests/test_macro_refcheck.py::test_real_repo_clean`**

After the real-repo run is exit-0, add a test that locks in the regression-free state:

```sh
cat >> tests/test_macro_refcheck.py <<'EOF'


def test_real_repo_passes():
    """The repo's actual configs must pass macro_refcheck."""
    import glob

    cfgs = (
        ["printer.cfg", "eddy.cfg", "btt-ebb-sb-usb-v1.0.cfg"]
        + sorted(glob.glob("macros/*.cfg"))
        + sorted(glob.glob("mmu/base/*.cfg"))
        + sorted(glob.glob("mmu/addons/*.cfg"))
        + sorted(glob.glob("mmu/optional/*.cfg"))
    )
    r = run(*cfgs)
    assert r.returncode == 0, f"stdout={r.stdout!r}"
EOF
```

Same addition for `tests/test_jinja2_lint.py`:

```sh
cat >> tests/test_jinja2_lint.py <<'EOF'


def test_real_repo_passes():
    """The repo's actual configs must pass jinja2_lint."""
    import glob

    cfgs = (
        ["printer.cfg", "eddy.cfg", "btt-ebb-sb-usb-v1.0.cfg"]
        + sorted(glob.glob("macros/*.cfg"))
        + sorted(glob.glob("mmu/base/*.cfg"))
        + sorted(glob.glob("mmu/addons/*.cfg"))
        + sorted(glob.glob("mmu/optional/*.cfg"))
    )
    r = run(*cfgs)
    assert r.returncode == 0, f"stdout={r.stdout!r}"
EOF
```

Run both:

```sh
python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```sh
git add tests/fixtures/macros_bad_refs.cfg tests/test_macro_refcheck.py \
        tests/test_jinja2_lint.py scripts/macro_refcheck.py
git commit -m "ci: macro_refcheck with tests; regression tests for real repo configs"
```

---

## Task 8: Add Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write the Makefile**

```sh
cat > Makefile <<'EOF'
.PHONY: test klippy lint refcheck pytest builtins

CFGS = printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg $(wildcard macros/*.cfg) $(wildcard mmu/base/*.cfg) $(wildcard mmu/addons/*.cfg) $(wildcard mmu/optional/*.cfg)

test: klippy lint refcheck pytest

klippy:
	cd vendor/klipper && python scripts/test_klippy.py -d ../../tests/dict ../../tests/voron-2-611.test

lint:
	python scripts/jinja2_lint.py $(CFGS)

refcheck:
	python scripts/macro_refcheck.py $(CFGS)

pytest:
	python -m pytest tests/ -v

builtins:
	python scripts/extract_builtins.py
EOF
```

- [ ] **Step 2: Run `make test`**

```sh
make test
```

Expected: all four targets pass in sequence. If anything fails, fix at the source — don't proceed to the workflow file with a red local run.

- [ ] **Step 3: Commit**

```sh
git add Makefile
git commit -m "ci: Makefile mirrors what GitHub Actions runs (\`make test\`)"
```

---

## Task 9: Write `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

```sh
mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'EOF'
name: CI
on:
  pull_request:
  push:
    branches: [main]

jobs:
  klippy-smoke:
    name: Klippy parse + smoke
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install klippy deps
        run: pip install cffi jinja2
      - name: Run test_klippy
        working-directory: vendor/klipper
        run: |
          python scripts/test_klippy.py -d ../../tests/dict ../../tests/voron-2-611.test

  lint:
    name: Macro jinja2 + refcheck
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        run: pip install jinja2 pytest
      - name: Pytest (script unit tests)
        run: python -m pytest tests/ -v
      - name: jinja2 syntax of every [gcode_macro] body
        run: python scripts/jinja2_lint.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/base/*.cfg mmu/addons/*.cfg mmu/optional/*.cfg
      - name: Reference-check every macro call
        run: python scripts/macro_refcheck.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/base/*.cfg mmu/addons/*.cfg mmu/optional/*.cfg
EOF
```

- [ ] **Step 2: Validate yaml syntax locally**

```sh
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
echo "exit: $?"
```

Expected: exit 0 (no output unless syntax error).

- [ ] **Step 3: Commit**

```sh
git add .github/workflows/ci.yml
git commit -m "ci: GitHub Actions workflow — two parallel jobs on PR + push:main"
```

---

## Task 10: Write `tests/README.md` + update `CLAUDE.md`

**Files:**
- Create: `tests/README.md`
- Modify: `CLAUDE.md` (add "## CI checks" section)

- [ ] **Step 1: Write `tests/README.md`**

```sh
cat > tests/README.md <<'EOF'
# CI tests for voron-2-611

What runs in `make test` and on every PR/push.

## Layout

```
tests/
├── README.md              this file
├── voron-2-611.test       Klipper smoke gcode + MCU dictionaries
├── builtins.txt           Klipper built-in gcode commands (regen w/ `make builtins`)
├── dict/                  Pre-compiled MCU protocol dictionaries
│   ├── mcu.dict           LPC1769 — both SKR 1.4 mainboards
│   ├── ebb-usb.dict       RP2040 — EBB SB toolhead
│   ├── eddy.dict          RP2040 — BTT Eddy probe
│   └── easy-brd.dict      SAMD21 — ERCF EASY-BRD MCU
├── fixtures/              Minimal .cfg files for script unit tests
├── test_jinja2_lint.py    Tests scripts/jinja2_lint.py
└── test_macro_refcheck.py Tests scripts/macro_refcheck.py
```

## Running locally

```sh
make test       # full pipeline (same as CI)
make klippy     # klippy parse + smoke gcode only
make lint       # jinja2 lint of macros only
make refcheck   # static reference-check only
make pytest     # python unit tests for the scripts only
```

## When to regenerate

- **`tests/dict/*.dict`** — when bumping `vendor/klipper` or changing `firmware/*.config`.
  Build on the Pi: copy each `firmware/*.config` to `~/klipper/.config`, `make`, copy `~/klipper/out/klipper.dict` back as `tests/dict/<name>.dict`.
- **`tests/builtins.txt`** — when bumping `vendor/klipper`. Run `make builtins`.

## Why these specific .dict files

Klipper's simulator (`test_klippy.py`) needs an MCU protocol dictionary per `[mcu ...]` section in `printer.cfg`. The dict file mirrors what the real MCU reports on connection — command IDs, parameter formats, etc. By committing them, we avoid compiling the firmware in CI.

A `.dict` is forward-compatible with config that uses fewer features than the firmware build expressed. So as long as our config doesn't reference a feature the dict doesn't know about, parsing succeeds.

## Adding a new macro

After adding a new `[gcode_macro X]`:
1. Run `make refcheck` locally — it should pass.
2. If `X` is called from another macro and that call is the first one, the local run will catch any typo.
3. If `X` calls a brand-new Klipper command not in `tests/builtins.txt`, run `make builtins` to regenerate (only needed after `vendor/klipper` bumps).
EOF
```

- [ ] **Step 2: Add "## CI checks" section to `CLAUDE.md`**

Insert immediately before the "## Known quirks" section:

```sh
# Find the line number of "## Known quirks"
grep -n "^## Known quirks" CLAUDE.md
```

Edit `CLAUDE.md` to insert a new section before it:

```markdown
---

## CI checks

GitHub Actions runs on every PR and push to `main` (`.github/workflows/ci.yml`). Two parallel jobs:

- **Klippy parse + smoke** — `vendor/klipper/scripts/test_klippy.py` runs against `tests/voron-2-611.test`, which loads `printer.cfg` with all five MCUs simulated and replays a smoke g-code sequence covering `G28`, `QUAD_GANTRY_LEVEL`, `BED_MESH_CALIBRATE`, `PRINT_START`, `PRINT_END`, `OFF`, `MMU_STATUS`, and the parking macros. Catches: section/pin/parameter errors, missing modules, and any runtime macro-reference error reachable from the smoke graph.
- **Macro jinja2 + refcheck** — `scripts/jinja2_lint.py` parses every `[gcode_macro]` body as a jinja2 template. `scripts/macro_refcheck.py` statically verifies every gcode command referenced in a macro body resolves to either a defined macro, a Klipper built-in (`tests/builtins.txt`), or the `ALLOWLIST` inside the script.

Run locally with `make test`. See `tests/README.md` for details.

**When to regenerate the cached data:**
- `tests/dict/*.dict` — after bumping `vendor/klipper` or modifying `firmware/*.config`. Build on the Pi (instructions in `tests/README.md`).
- `tests/builtins.txt` — after bumping `vendor/klipper`. Run `make builtins`.
```

Use the Edit tool to insert before `## Known quirks`.

- [ ] **Step 3: Verify the edit landed**

```sh
grep -B1 -A2 "## CI checks" CLAUDE.md | head -5
```

Expected: shows the new section header.

- [ ] **Step 4: Commit**

```sh
git add tests/README.md CLAUDE.md
git commit -m "docs: tests/README.md + CLAUDE.md \"## CI checks\" section"
```

---

## Task 11: Eddy-migration acid test (spec §7.3)

This task verifies the spec's hardest claim: that `macro_refcheck.py` catches the intermediate state of the eddy migration. The mechanism: the ALLOWLIST in `macro_refcheck.py` has a section keyed to "modules currently loaded by printer.cfg." When the eddy migration removes `[probe_eddy_ng]`, the same PR is expected to remove the `PROBE_EDDY_NG_*` entries from ALLOWLIST. If only one of those two changes lands without the other, refcheck flags it.

**Files:** none modified — this is a manual dry-run on a scratch branch.

- [ ] **Step 1: Simulate the "ALLOWLIST cleaned up but print_start.cfg not yet updated" intermediate state**

```sh
git checkout -b scratch/eddy-acid-test
```

Edit `scripts/macro_refcheck.py`: delete the five `PROBE_EDDY_NG_*` entries from the eddy-ng block of ALLOWLIST (as the migration PR would). Save. Don't touch `macros/print_start.cfg` — it still calls `PROBE_EDDY_NG_TAP`.

- [ ] **Step 2: Run refcheck**

```sh
python scripts/macro_refcheck.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/base/*.cfg mmu/addons/*.cfg mmu/optional/*.cfg
```

Expected: exit 1 with output flagging `PROBE_EDDY_NG_TAP` in `[gcode_macro PRINT_START]` and `PROBE_EDDY_NG_SET_TAP_OFFSET` in `[gcode_macro PRINT_END]`.

If refcheck did NOT catch these: the spec's ALLOWLIST-coupling pattern is broken. **Stop** and investigate. Most likely cause: a typo in the ALLOWLIST entries or the regex in `extract_commands` not matching the actual usage.

- [ ] **Step 3: Restore state, drop the scratch branch**

```sh
git checkout -- scripts/macro_refcheck.py
git checkout feat/ci-scaffold
git branch -D scratch/eddy-acid-test
```

- [ ] **Step 4: Record the result**

Append to `memory/troubleshooting-log.md` under "Resolved":

```
### 2026-05-13 — CI eddy-migration acid test
- Result: [PASS — refcheck flagged the unaligned migration state | FAIL — refcheck did NOT catch it; investigated and fixed: <fix>]
- Implication: the eddy migration PR will get a red CI status until ALLOWLIST entries and print_start.cfg are updated in sync.
- Memo to the eddy migration plan: §6 step that touches macros/print_start.cfg must ALSO remove the PROBE_EDDY_NG_* entries from scripts/macro_refcheck.py's ALLOWLIST.
```

- [ ] **Step 5: Cross-reference into the eddy migration plan**

The eddy migration plan at `docs/superpowers/plans/2026-05-13-eddy-ng-to-native-migration.md` needs a step to remove the eddy-ng entries from ALLOWLIST as part of its config diff task. Append to its open follow-ups (don't edit any other section):

```sh
PLAN=docs/superpowers/plans/2026-05-13-eddy-ng-to-native-migration.md
cat >> "$PLAN" <<'EOF'

---

## Note added 2026-05-13 by ci-scaffold plan

The eddy migration must also remove these entries from
`scripts/macro_refcheck.py` ALLOWLIST (added by the ci-scaffold work)
in the same commit that removes the `[probe_eddy_ng]` block:

```python
"PROBE_EDDY_NG_TAP",
"PROBE_EDDY_NG_PROBE",
"PROBE_EDDY_NG_CALIBRATE",
"PROBE_EDDY_NG_STATUS",
"PROBE_EDDY_NG_SET_TAP_OFFSET",
```

If this step is skipped, refcheck will keep silently accepting calls to
the removed commands. The acid test in the ci-scaffold plan (2026-05-13)
validates this coupling.
EOF
```

- [ ] **Step 6: Commit the memory note + plan cross-ref**

```sh
git add memory/troubleshooting-log.md docs/superpowers/plans/2026-05-13-eddy-ng-to-native-migration.md
git commit -m "ci: record eddy-migration acid test + cross-ref into eddy plan"
```

---

## Task 12: Create GitHub remote and push

**Files:** none in the worktree change.

- [ ] **Step 1: Verify `gh` is authenticated**

```sh
gh auth status
```

Expected: `Logged in to github.com as <username>`. If not, the user runs `gh auth login` interactively.

- [ ] **Step 2: Create the public repo**

```sh
gh repo create voron-2-611 --public --description "Voron 2.4 r2 Klipper configuration — community serial 2.611" --source=$(git rev-parse --show-toplevel) --remote=origin
```

Note: `--source` points at the **parent repo** (not the worktree). The worktree shares its remote with the parent automatically.

Expected: `Created repository <user>/voron-2-611 on GitHub` and `origin` added.

If the command fails with "repository already exists" (Ben previously created it manually), instead run:

```sh
PARENT=$(git rev-parse --path-format=absolute --git-common-dir | xargs dirname)
git -C "$PARENT" remote add origin git@github.com:<user>/voron-2-611.git
```

(Replace `<user>` with the GitHub username from `gh auth status`.)

- [ ] **Step 3: Push main first**

```sh
PARENT=$(git rev-parse --path-format=absolute --git-common-dir | xargs dirname)
git -C "$PARENT" push -u origin main
```

Expected: branch pushed, tracking origin/main.

- [ ] **Step 4: Push the feature branch**

```sh
git push -u origin feat/ci-scaffold
```

Expected: branch pushed.

- [ ] **Step 5: Open a draft PR**

```sh
gh pr create \
  --title "ci: add CI scaffold (parse + smoke + jinja2 + refcheck)" \
  --body "$(cat <<'EOF'
Implements `docs/superpowers/specs/2026-05-13-ci-scaffold.md`.

## What this adds

- `.github/workflows/ci.yml` — two parallel jobs (klippy parse + smoke, lint + refcheck)
- `tests/voron-2-611.test` — smoke g-code through `PRINT_START` and friends
- `tests/dict/` — pre-compiled MCU dicts for the five boards
- `scripts/jinja2_lint.py`, `scripts/macro_refcheck.py`, `scripts/extract_builtins.py`
- `Makefile` mirrors CI for local runs (`make test`)
- `tests/README.md`, CLAUDE.md updates

## Validation

- `make test` passes locally
- Acid test (Task 11): refcheck flagged the simulated intermediate eddy-migration state, per spec §7.3

## Out of scope (separate specs)

- Pre-commit hooks
- Compile dicts in CI
- Deploy automation
- Eddy migration (separate spec, this CI gates that PR)
EOF
)"
```

Expected: PR URL printed.

- [ ] **Step 6: Wait for the first CI run**

```sh
gh pr checks --watch
```

Expected: both `klippy-smoke` and `lint` jobs go to ✓ within ~2-3 minutes. If either fails:

- **`klippy-smoke` fail**: the cause is almost always (1) a dict file that doesn't match the pinned Klipper, or (2) a smoke gcode line the simulator rejects. Read the failure log, fix locally, force-push the branch.
- **`lint` fail**: same triage as the local run from Task 7 step 6.

- [ ] **Step 7: Commit any fixes inline; do NOT amend**

If you needed to fix something:

```sh
git add <files>
git commit -m "ci: fix <whatever the issue was>"
git push
gh pr checks --watch
```

---

## Task 13: PR review + merge

**Files:** none modified (review only).

- [ ] **Step 1: Invoke `pr-review-toolkit:review-pr`**

```
Skill: pr-review-toolkit:review-pr
```

The skill will dispatch review subagents (code-reviewer, silent-failure-hunter, comment-analyzer, type-design-analyzer, pr-test-analyzer). Apply any blocker feedback before merge. Save non-blocker feedback as comments on the PR.

- [ ] **Step 2: Address feedback, commit, push**

For each blocker:

```sh
# fix the issue
git add <files>
git commit -m "ci: address review feedback — <what changed>"
git push
gh pr checks --watch  # verify CI still green
```

- [ ] **Step 3: Mark PR ready (if it was draft)**

```sh
gh pr ready
```

- [ ] **Step 4: Squash-merge (per Ben's git conventions, CLAUDE.md global)**

```sh
gh pr merge --squash --delete-branch
```

Expected: PR merged, `feat/ci-scaffold` branch deleted on origin.

- [ ] **Step 5: Verify CI is green on `main`**

```sh
PARENT=$(git rev-parse --path-format=absolute --git-common-dir | xargs dirname)
git -C "$PARENT" checkout main
git -C "$PARENT" pull
gh run watch  # watches the most recent run on main
```

Expected: green ✓.

- [ ] **Step 6: Clean up the worktree**

```sh
# Use the native ExitWorktree if available; otherwise:
PARENT=$(git rev-parse --path-format=absolute --git-common-dir | xargs dirname)
WORKTREE=$(pwd)
cd "$PARENT"
git worktree remove "$WORKTREE"
```

---

## Task 14: Recommend branch protection (manual, not scripted)

**Files:** none — this is a GitHub UI action.

- [ ] **Step 1: Open repo settings**

```sh
gh repo view --web
# Navigate to: Settings → Branches → Branch protection rules → Add rule
```

- [ ] **Step 2: Configure rule for `main`**

Recommended settings:
- **Branch name pattern:** `main`
- ✓ **Require a pull request before merging**
  - ✓ Require approvals: 0 (Ben is the only contributor for now; bump to 1 if collaborators join)
  - ✓ Dismiss stale pull request approvals when new commits are pushed
- ✓ **Require status checks to pass before merging**
  - Required: `Klippy parse + smoke`
  - Required: `Macro jinja2 + refcheck`
- ✓ **Require branches to be up to date before merging**
- ✓ **Do not allow bypassing the above settings** (uncheck if you want emergency override)

This is a one-time setup. The rule is automatically applied to all future PRs.

- [ ] **Step 3: Document in CLAUDE.md**

Add to the "## CI checks" section:

```markdown
Branch protection is enabled on `main`: both CI jobs are required to pass before merge. Configure at GitHub → Settings → Branches.
```

Commit on `main` directly (small docs-only change):

```sh
git add CLAUDE.md
git commit -m "docs: note branch protection setup for main"
git push
```

---

## Self-review notes (already applied)

- **Spec coverage:** every requirement in spec §3, §5, §6, §7 has a corresponding task.
- **Placeholder scan:** no "TBD" / "implement later" — every step has runnable commands or complete code.
- **Type consistency:** `mcu.dict` / `ebb-usb.dict` / `eddy.dict` / `easy-brd.dict` used consistently across .test file, workflow yml, Makefile, README.

## Open follow-ups (out of scope for THIS plan)

- Pre-commit hook (`scripts/pre-commit` symlink to a thin shell that runs `make lint refcheck`). Separate small spec.
- Deploy automation (merge → rsync → RESTART) — separate spec.
- v2 of refcheck: variable-reference tracking, `action_call_remote_method` validation. Separate spec when needed.
- Compile dicts in CI from `firmware/*.config` — v2 if local-build drift becomes a problem.
