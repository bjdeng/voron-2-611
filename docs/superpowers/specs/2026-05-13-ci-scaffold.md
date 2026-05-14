# CI scaffold for the Voron 2.611 Klipper config repo

| | |
|---|---|
| **Spec date** | 2026-05-13 |
| **Target** | This repo (`voron-2-611`) |
| **Status** | Awaiting user review before plan |
| **Author** | Ben + Claude (via `superpowers:brainstorming`) |
| **Implementation skill (next)** | `superpowers:writing-plans` |
| **Review skill (at PR time)** | `pr-review-toolkit:review-pr` |

---

## 1. Summary

Add GitHub Actions CI that catches Klipper config errors before they're synced to the printer. Three checks: (a) Klipper's own parser runs against `printer.cfg` with all 5 MCUs simulated and a smoke g-code sequence that exercises the macro call graph; (b) every `[gcode_macro]` body is parsed as a jinja2 template; (c) every g-code command referenced in macro bodies resolves to either a Klipper built-in or a `[gcode_macro]` defined somewhere in the included config tree.

The eddy migration (spec `2026-05-13-eddy-ng-to-native-migration.md`) is the first PR this CI will gate.

## 2. Why

- The printer is the prod environment. Today there is no "staging" — every config change goes straight to the Pi and gets validated by Klipper booting (or failing to boot). The blast radius of a bad commit is a downed printer mid-print.
- Klipper itself ships a regression-test framework (`vendor/klipper/scripts/test_klippy.py`) that simulates MCUs and replays g-code. We can lift this directly — no custom parser, no Klipper-internals coupling beyond what's already in the vendored submodule.
- The eddy migration changes `PRINT_START` to call a different probe command. Static + runtime checks catch the "I renamed something but forgot to update a caller" class.

## 3. Constraints (confirmed with user)

| Constraint | Source |
|---|---|
| **Where:** GitHub Actions on a public personal repo (free tier). | User, 2026-05-13 |
| **Trigger:** `pull_request` + `push` to `main`. | User, 2026-05-13 |
| **MVP scope:** (a) Klipper parse with smoke g-code + (b) jinja2 lint + (c) static reference check. | User, 2026-05-13 |
| **MCU dict files:** committed as binaries under `tests/dict/`, not compiled-in-CI. Regenerate when bumping `vendor/klipper` or `firmware/*.config`. | User, 2026-05-13 |
| Local-run affordance via `make test` mirrors what CI does. | Spec author |
| `pr-review-toolkit:review-pr` runs on the PR that ships this scaffold before merge. | User memory `use-superpowers-and-pr-review` |
| Implementation done on a `feat/ci-scaffold` worktree (per `superpowers:using-git-worktrees`). | User memory `use-worktrees-for-implementation` |

## 4. Architecture

```
        ┌─────────────────────────────────┐
        │ GitHub push / pull_request      │
        └────────────────┬────────────────┘
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
  ┌─────────────────┐            ┌─────────────────┐
  │ Job: klippy     │            │ Job: lint       │
  │ (parse + smoke) │            │ (jinja2 + refs) │
  └────────┬────────┘            └────────┬────────┘
           │                              │
           │ test_klippy.py               │ jinja2_lint.py
           │   ↓                          │ macro_refcheck.py
           │ klippy.py with               │
           │   -d <dicts>                 │
           │   -i <test.gcode>            │
           │   -o <output>                │
           │                              │
           ▼                              ▼
    Klipper parses all                Every [gcode_macro] body
    included .cfg files,              parses as valid jinja2.
    loads 5 MCUs from                 Every gcode command
    committed .dict stubs,            referenced in any macro
    runs smoke g-code                 resolves to a defined
    through PRINT_START,              [gcode_macro] or a known
    PRINT_END, OFF, MMU_STATUS,       Klipper built-in.
    parking macros.
```

Two **parallel** jobs in the workflow. Failure of either fails the check. No artifact passing between jobs (each is self-contained).

## 5. Files (final list)

### 5.1 New

| Path | Purpose | Size |
|---|---|---|
| `.github/workflows/ci.yml` | Workflow definition. Two jobs, parallel. Triggers on `pull_request` + `push: main`. | ~30 lines |
| `tests/voron-2-611.test` | Klipper `.test` file. `CONFIG`, multi-MCU `DICTIONARY`, inline smoke g-code. | ~30 lines |
| `tests/dict/lpc176x.dict` | MCU protocol dictionary for both SKR 1.4 mainboards. | ~50 KB binary |
| `tests/dict/rp2040.dict` | MCU protocol dictionary for EBB SB toolhead + BTT Eddy probe. | ~50 KB binary |
| `tests/dict/samd21.dict` | MCU protocol dictionary for ERCF EASY-BRD. | ~50 KB binary |
| `tests/README.md` | One-paragraph: how to run locally; when to regen the .dict files. | ~25 lines |
| `scripts/jinja2_lint.py` | Parses every `[gcode_macro X]` body with `jinja2.Environment().parse()`. Reports `TemplateSyntaxError` with file:line. | ~50 lines |
| `scripts/macro_refcheck.py` | Static reference check (see §6.3). | ~80 lines |
| `scripts/extract_builtins.py` | Regenerates `tests/builtins.txt` from `vendor/klipper/klippy/extras/*.py:register_command(`. Run manually when bumping vendor/klipper. | ~30 lines |
| `tests/builtins.txt` | Cached list of Klipper built-in commands. Used by `macro_refcheck.py`. Regenerated by `extract_builtins.py`. | ~3 KB text |
| `Makefile` | `make test` and `make builtins` targets. | ~15 lines |

### 5.2 Modified

| Path | Change |
|---|---|
| `CLAUDE.md` | Add "CI checks" section pointing to `tests/` and `scripts/`. Add note: regenerate .dict files when bumping `vendor/klipper`; regenerate `tests/builtins.txt` via `make builtins` when bumping `vendor/klipper`. |

### 5.3 Unchanged

All printer configs (`printer.cfg`, `eddy.cfg`, `btt-ebb-sb-usb-v1.0.cfg`, `macros/*`, `mmu/*`, `*.conf`), `firmware/`, `archive/`, `memory/`, all `vendor/*`.

## 6. Implementation details

### 6.1 `tests/voron-2-611.test`

```
# Voron 2.611 — parse + macro-graph smoke under simulated MCUs.
# Run by `python scripts/test_klippy.py -d tests/dict tests/voron-2-611.test`
# from the vendor/klipper checkout.

CONFIG ../../printer.cfg
DICTIONARY lpc176x.dict z=lpc176x.dict EBB=rp2040.dict eddy=rp2040.dict mmu=samd21.dict

# --- Boot + leveling smoke ---
G28
QUAD_GANTRY_LEVEL
BED_MESH_CALIBRATE METHOD=rapid_scan

# --- Macro graph smoke ---
# Exercises PRINT_START → BLOBIFIER_CLEAN, G28 Z, eddy tap, mesh, etc.
# Exercises PRINT_END → PROBE_EDDY_*_SET_TAP_OFFSET (or its replacement), OFF.
PRINT_WARMUP BED=60 EXTRUDER=200
HEATSOAK T=60 C=30 MOVE=1 WAIT=0
PRINT_START BED=60 EXTRUDER=200 CHAMBER=0
PRINT_END
OFF

# --- MMU surface ---
MMU_STATUS

# --- Parking macros (touch each one once) ---
PARKCENTER
PARKFRONT
PARKREAR
PARKBED
```

The relative path `../../printer.cfg` is because `test_klippy.py` resolves `CONFIG` relative to the .test file's directory.

### 6.2 `scripts/jinja2_lint.py`

```python
#!/usr/bin/env python3
"""
Parse every [gcode_macro X] body in the given .cfg files as a jinja2 template.
Exit 1 on any TemplateSyntaxError, with file:line context.
"""
import re, sys
from pathlib import Path
from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError

MACRO_HEADER = re.compile(r'^\[gcode_macro\s+(\S+)\s*\]\s*$')
GCODE_FIELD  = re.compile(r'^gcode\s*:\s*$')

def each_macro_body(path: Path):
    """Yield (macro_name, start_line_of_body, body_text) for each macro."""
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        m = MACRO_HEADER.match(lines[i])
        if not m:
            i += 1; continue
        name = m.group(1)
        # Scan forward for "gcode:" within the section (until next [section] header)
        j = i + 1
        while j < len(lines) and not lines[j].startswith('['):
            if GCODE_FIELD.match(lines[j]):
                # Body is the indented lines following
                body_start = j + 1
                k = body_start
                while k < len(lines) and (lines[k].startswith((' ', '\t')) or lines[k].strip() == ''):
                    k += 1
                yield name, body_start + 1, '\n'.join(l.lstrip() for l in lines[body_start:k])
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
                # e.lineno is relative to the body; offset by where the body started
                abs_line = lineno + (e.lineno or 1) - 1
                print(f"{path}:{abs_line}: [gcode_macro {name}] {e.message}")
                errors += 1
    sys.exit(1 if errors else 0)

if __name__ == '__main__':
    main(sys.argv[1:])
```

### 6.3 `scripts/macro_refcheck.py`

Two passes. Pass 1: build `defined = set()` of all gcode commands the printer accepts. Pass 2: walk macro bodies, extract referenced command tokens, flag unknowns.

```python
#!/usr/bin/env python3
"""
Static reference check: for every gcode command invoked from a [gcode_macro]
body, verify it resolves to either a defined macro or a Klipper built-in.
"""
import re, sys
from pathlib import Path

MACRO_HEADER     = re.compile(r'^\[gcode_macro\s+(\S+)\s*\]\s*$')
RENAME_FIELD     = re.compile(r'^rename_existing\s*:\s*(\S+)\s*$')
GCODE_FIELD      = re.compile(r'^gcode\s*:\s*$')
DELAYED_HEADER   = re.compile(r'^\[delayed_gcode\s+(\S+)\s*\]\s*$')
# A line that "looks like" a gcode command: indented, starts with [A-Z_],
# not a jinja2 control, not a comment.
COMMAND_LINE     = re.compile(r'^\s+([A-Z][A-Z0-9_]*)\b')

# Tokens we trust without verification: G/M codes in standard ranges + Klipper
# fundamentals + jinja2 helpers that look like commands.
ALLOWLIST = {
    # Standard g/m codes that always work
    *(f"G{n}" for n in range(0, 93)),
    *(f"M{n}" for n in range(0, 1000)),
    # Common Klipper internals that don't always show up cleanly in extras/
    "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE",
    "SET_GCODE_OFFSET", "SET_GCODE_VARIABLE",
    "SET_VELOCITY_LIMIT", "SET_PRESSURE_ADVANCE",
    "SET_KINEMATIC_POSITION",
    "TEMPERATURE_WAIT", "SET_PIN", "SET_FAN_SPEED",
    "UPDATE_DELAYED_GCODE", "SET_IDLE_TIMEOUT",
    "BED_MESH_CLEAR", "RESPOND",
    "SET_DISPLAY_TEXT",
}

def load_builtins(path: Path) -> set[str]:
    """Read tests/builtins.txt produced by scripts/extract_builtins.py."""
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')}

def collect_defined(paths):
    defined = set()
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            m = MACRO_HEADER.match(line) or DELAYED_HEADER.match(line)
            if m:
                defined.add(m.group(1).upper())
                continue
            m = RENAME_FIELD.match(line.strip())
            if m:
                defined.add(m.group(1).upper())
    return defined

def each_macro_body(path: Path):
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        m = MACRO_HEADER.match(lines[i])
        if not m:
            i += 1; continue
        name = m.group(1)
        j = i + 1
        while j < len(lines) and not lines[j].startswith('['):
            if GCODE_FIELD.match(lines[j]):
                k = j + 1
                while k < len(lines) and (lines[k].startswith((' ', '\t')) or lines[k].strip() == ''):
                    k += 1
                yield name, j + 2, lines[j+1:k]
                j = k
                continue
            j += 1
        i = j

def extract_commands(body_lines):
    for offset, line in enumerate(body_lines):
        # Skip jinja2 control / comments / empty
        stripped = line.lstrip()
        if not stripped or stripped.startswith('#') or stripped.startswith('{%') or stripped.startswith('{{'):
            continue
        m = COMMAND_LINE.match(line)
        if m:
            yield offset, m.group(1).upper()

def main(paths):
    defined = collect_defined(paths)
    builtins = load_builtins(Path('tests/builtins.txt'))
    known = defined | builtins | ALLOWLIST

    errors = 0
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue
        for macro_name, body_start, body in each_macro_body(path):
            for offset, cmd in extract_commands(body):
                if cmd not in known:
                    print(f"{path}:{body_start + offset}: [gcode_macro {macro_name}] references unknown command '{cmd}'")
                    errors += 1
    if errors:
        print(f"\n{errors} unknown reference(s). If a flagged command is valid,"
              " add it to ALLOWLIST in scripts/macro_refcheck.py or to tests/builtins.txt.")
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main(sys.argv[1:])
```

### 6.4 `scripts/extract_builtins.py`

```python
#!/usr/bin/env python3
"""
Regenerate tests/builtins.txt from vendor/klipper/klippy/extras/*.py and
vendor/klipper/klippy/gcode.py by grepping for register_command(...) calls.
Run manually when bumping vendor/klipper.
"""
import re, sys
from pathlib import Path

REGISTER = re.compile(r"register(?:_mux)?_command\s*\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]")

def main():
    root = Path("vendor/klipper/klippy")
    paths = [root / "gcode.py"] + list((root / "extras").glob("*.py"))
    cmds = set()
    for p in paths:
        for m in REGISTER.finditer(p.read_text()):
            cmds.add(m.group(1))
    out = Path("tests/builtins.txt")
    out.write_text(
        "# Auto-generated by scripts/extract_builtins.py from vendor/klipper.\n"
        "# Run `make builtins` to regenerate.\n"
        + '\n'.join(sorted(cmds)) + '\n'
    )
    print(f"Wrote {len(cmds)} commands to {out}")

if __name__ == '__main__':
    main()
```

### 6.5 `.github/workflows/ci.yml`

```yaml
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
        with: { submodules: recursive }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
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
        with: { submodules: recursive }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install jinja2
      - name: jinja2 syntax of every [gcode_macro] body
        run: python scripts/jinja2_lint.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/**/*.cfg
      - name: Reference-check every macro call
        run: python scripts/macro_refcheck.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/**/*.cfg
```

### 6.6 `Makefile`

```makefile
.PHONY: test builtins
test:
	cd vendor/klipper && python scripts/test_klippy.py -d ../../tests/dict ../../tests/voron-2-611.test
	python scripts/jinja2_lint.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/**/*.cfg
	python scripts/macro_refcheck.py printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg macros/*.cfg mmu/**/*.cfg

builtins:
	python scripts/extract_builtins.py
```

### 6.7 MCU dict procurement

`.dict` files are emitted by `make` when compiling Klipper firmware. They live at `~/klipper/out/klipper.dict` immediately after each board's `make`. Since the Pi has already built and flashed all 5 MCUs, the .dict for each is recoverable from the Pi (re-run `make` with the appropriate `.config` from `firmware/` and copy the result). The implementation plan covers this as a discrete task.

**Verify-on-implementation:** confirm that LPC1769 MCU build emits a `lpc176x.dict` (the LPC176x family name) — Klipper uses family names for the .dict, not specific chip names. Likewise `rp2040.dict` covers both EBB SB and BTT Eddy.

## 7. Verification (done criteria)

### 7.1 Local smoke

After all files are in place, on the implementer's machine:

```sh
make test
```

Must exit 0. Specifically:
- `test_klippy.py` reports `=============== Finished tests/voron-2-611.test` with no failures
- `jinja2_lint.py` exits 0 (no `TemplateSyntaxError` in any macro body)
- `macro_refcheck.py` exits 0 (no unknown references)

If any check fails on the **current** `printer.cfg`/macros, that's a real bug the spec just discovered — fix it in the same PR or open a follow-up issue.

### 7.2 Remote first-run

After pushing the `feat/ci-scaffold` branch to GitHub:

- The Actions run for that push shows both jobs green
- The Actions run on the **PR** (when opened) also shows both jobs green
- The status check is registered as required for the `main` branch (Settings → Branches → branch protection rules, optional but recommended)

### 7.3 The eddy-migration acid test

After the CI scaffold is merged, when the **eddy-ng migration PR** opens (per spec `2026-05-13-eddy-ng-to-native-migration.md`), CI must:

- **Fail** during an intermediate state where `print_start.cfg` still references `PROBE_EDDY_NG_TAP` but `eddy.cfg` already defines `[probe_eddy_current]` (the rename inconsistency).
- **Pass** once both files are updated in sync.

If CI doesn't catch the intermediate state, that's a real gap in the design — log it and revisit.

## 8. Rollback procedure

This spec adds files; it doesn't modify the printer configs. Rollback is `git revert` of the CI-scaffold merge commit. No printer impact.

If the workflow file itself misbehaves (e.g., infinite loop, runaway minute usage), disable the workflow in GitHub UI (Actions tab → workflow → "Disable workflow") while debugging.

## 9. Out of scope

- **Pre-commit hooks** — separate spec if local feedback proves too slow.
- **Compile MCU dicts in CI from `firmware/*.config`** — v2 spec if .dict drift becomes a problem.
- **Klipper `--import-test`** smoke (just `python klippy/klippy.py --import-test`) — redundant with what `test_klippy.py` does for us.
- **Multiple Klipper versions** — we test only the pinned `vendor/klipper` commit.
- **Macro variable cross-checks** (`printer["gcode_macro X"].some_var` references) — not in (a/b/c); v2 if useful.
- **action_call_remote_method target validation** — needs a list of Moonraker remote methods; v2.
- **Deploy automation** (merge → rsync → RESTART on Pi) — separate spec.
- **Branch protection rules / required status checks** — recommend setting up via GitHub UI after first green CI run; not a workflow-file change.

## 10. Verify-on-implementation

- The LPC1769 build emits a `.dict` named `lpc176x.dict` (or whatever Klipper's `make` produces — confirm before committing).
- `MMU_STATUS` is a valid Happy-Hare command in the test's smoke g-code (likely yes — it's standard — but confirm against `mmu/base/*.cfg`).
- `test_klippy.py` succeeds against the **current** (pre-eddy-migration) config. If it fails because eddy-ng's third-party module choke on simulator mode, the workaround is: temporarily stub `[probe_eddy_ng]` in the smoke gcode to skip eddy-related calls, or accept that the CI scaffold ships **after** the eddy migration as a follow-up PR. The plan addresses this branch.

## 11. References

- `vendor/klipper/scripts/test_klippy.py` — the regression test runner we lift.
- `vendor/klipper/scripts/ci-build.sh` — Klipper's own CI; pattern we mirror.
- `vendor/klipper/.github/workflows/build-test.yaml` — Klipper's Actions workflow; pattern for ours.
- `vendor/klipper/test/klippy/eddy.test` — example of the .test format we copy. Tests `[probe_eddy_current]` natively.
- `docs/superpowers/specs/2026-05-13-eddy-ng-to-native-migration.md` — the first PR this CI will gate.
- `memory/stop-waffling.md` — make calls in tool-call-units, not human-hours.
- `memory/use-superpowers-and-pr-review.md` — invoke `pr-review-toolkit:review-pr` before the CI scaffold merge.
- `memory/use-worktrees-for-implementation.md` — implementation on a `feat/ci-scaffold` worktree.

---

*Next step after user review: invoke `superpowers:writing-plans` to produce the implementation plan.*
