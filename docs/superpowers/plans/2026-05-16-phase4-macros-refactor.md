# Phase 4 — Macros refactor + file reorg — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Phase 4 of the master config/macros refactor as two PRs in series — PR-A (structural cleanup) and PR-B (`_USER_VARIABLE` migration) — with zero behavior change verified by Layer 5 tripwires (both PRs) and a Layer 7 behavior-diff snapshot (PR-B).

**Architecture:** Two PRs, each on its own worktree. PR-A is mechanical (rename, section moves, description coverage, include reorder). PR-B introduces a `_USER_VARIABLE` macro and migrates 5 files to read tunables from it. Each PR runs through worktree → TDD-style commits → `pr-review-toolkit:review-pr` → push → `/deploy-to-pi --smoke`. Layer 5 tripwires (`tests/test_config_structure.py`) are added in the same PR as the changes they protect.

**Tech Stack:** Klipper config (`.cfg`), Jinja2 macros, Python 3 pytest, Klipper's `test_klippy.py` simulator, GitHub Actions CI, bash `/deploy-to-pi` skill.

**Spec:** [`docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md`](../specs/2026-05-16-phase4-macros-refactor-design.md)

---

## Pre-flight (before PR-A)

- [ ] **Step 0.1: Confirm starting state**

```bash
git log --oneline main -3
# Expect to see (or newer): 1cbc80b docs(claude-md): Phase 3 ...
gh issue list --label future-work --limit 5
# Expect future-work issues visible (Phase 3 migration shipped).
```

- [ ] **Step 0.2: Read the spec end-to-end before starting**

Read `docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md` once now. Re-reading mid-task wastes context.

- [ ] **Step 0.3: Verify `tests/test_config_structure.py` baseline**

```bash
test -f tests/test_config_structure.py && wc -l tests/test_config_structure.py
# Expect: file exists (created in Phase 1, PR #35) with one test:
# `test_no_deprecated_klipper_config_keys`. ~77 lines.
```

If absent or shape different, stop and reconcile before continuing.

---

## PR-A: Structural cleanup

### Task A.1: Create the worktree

**Files:**
- (none — worktree creation)

- [ ] **Step 1: Create worktree from `main`**

Use the `EnterWorktree` tool (per `superpowers:using-git-worktrees`) with branch `feat/refactor-phase4a-structural` based on `main`. Work in that worktree for all PR-A tasks.

- [ ] **Step 2: Verify clean tree**

```bash
git status
# Expect: On branch feat/refactor-phase4a-structural; nothing to commit.
```

---

### Task A.2: Layer 5 tripwires — write failing tests first

**Files:**
- Modify: `tests/test_config_structure.py` (extend — file already exists from Phase 1)

- [ ] **Step 1: Read the existing file**

```bash
cat tests/test_config_structure.py
# Expect: one test (test_no_deprecated_klipper_config_keys), a _cfg_files()
# helper that excludes archive/ and HH paths, and DEPRECATED_CONFIG_KEY_PATTERNS.
```

- [ ] **Step 2: APPEND three new tests (do not remove or rewrite the existing test or helpers)**

Add this block at the END of `tests/test_config_structure.py`:

```python
# ---------------------------------------------------------------------------
# Phase 4 PR-A: macro description coverage, duplicate section, single-extruder
# ---------------------------------------------------------------------------

import glob  # noqa: E402  (kept local to PR-A block for clarity)

OWNED_MACRO_FILES = sorted(glob.glob(str(REPO_ROOT / "config/macros/*.cfg"))) + [
    str(REPO_ROOT / "config/eddy.cfg"),
]


def _parse_macros(cfg_path):
    """Yield (macro_name, body_lines, description_present_bool) tuples."""
    text = Path(cfg_path).read_text()
    section_re = re.compile(r"^\[gcode_macro\s+(\S+)\]\s*$", re.MULTILINE)
    matches = list(section_re.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        # description: must be a top-level key (no leading whitespace),
        # not just the literal string appearing inside a gcode comment.
        desc = bool(re.search(r"^description:\s*\S+", body, re.MULTILINE))
        yield name, body, desc


def test_every_owned_macro_has_description():
    """Every [gcode_macro] in config/macros/* and config/eddy.cfg has a non-empty description: field."""
    missing = []
    for cfg in OWNED_MACRO_FILES:
        for name, _body, has_desc in _parse_macros(cfg):
            if not has_desc:
                missing.append(f"{Path(cfg).relative_to(REPO_ROOT)}::{name}")
    assert not missing, (
        f"{len(missing)} macros without description: " + ", ".join(missing)
    )


def test_status_sections_declared_at_most_once():
    """[respond]/[exclude_object]/[pause_resume]/[display_status] declared at most once in owned files."""
    targets = ("respond", "exclude_object", "pause_resume", "display_status")
    sec_re = {t: re.compile(rf"^\[{t}\]\s*$", re.MULTILINE) for t in targets}
    over = []
    for t in targets:
        hits = []
        for cfg in _cfg_files():
            for _ in sec_re[t].findall(cfg.read_text()):
                hits.append(cfg.relative_to(REPO_ROOT))
        if len(hits) > 1:
            over.append(f"[{t}] declared {len(hits)}x: {hits}")
    assert not over, "; ".join(over)


def test_extruder_section_single_file():
    """[extruder] declared in exactly one owned file (HH's variable-injection block is excluded by _cfg_files())."""
    hits = [
        str(cfg.relative_to(REPO_ROOT))
        for cfg in _cfg_files()
        if re.search(r"^\[extruder\]\s*$", cfg.read_text(), re.MULTILINE)
    ]
    assert len(hits) == 1, f"[extruder] in {hits} (expect exactly one owned file)"
```

These reuse the existing `_cfg_files()` helper from Phase 1, which already excludes archive + HH paths.

- [ ] **Step 3: Run the tests; verify they fail as expected**

```bash
make test-py 2>&1 | grep -E "test_(every_owned|status_sections|extruder)" | head
# Expect: FAILED for all three (current state has 26 macros without description,
# duplicate [respond]/[exclude_object], and [extruder] in two files).
```

If a test FAILS for a reason unrelated to the expected condition, fix the test before continuing.

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/test_config_structure.py
git commit -m "$(cat <<'EOF'
chore(tests): add Layer 5 tripwires for PR-A invariants

Tripwires for: description coverage on every owned macro; single declaration
of [respond]/[exclude_object]/[pause_resume]/[display_status] outside HH
paths; [extruder] in exactly one owned file. Tests currently fail — the
following commits make them pass.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A.3: Rename `btt-ebb-sb-usb-v1.0.cfg` → `toolhead.cfg`

**Files:**
- Rename: `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`
- Modify: `config/printer.cfg:68`
- Modify: `tests/test_macro_refcheck.py:108`
- Modify: `Makefile:7`
- Modify: `.github/workflows/ci.yml:131`
- Modify: `CLAUDE.md` (4 references)
- Modify: `docs/superpowers/specs/2026-05-15-config-macros-refactor.md` (self-references)

- [ ] **Step 1: Rename the file via `git mv`**

```bash
git mv config/btt-ebb-sb-usb-v1.0.cfg config/toolhead.cfg
git status
# Expect: renamed: config/btt-ebb-sb-usb-v1.0.cfg -> config/toolhead.cfg
```

- [ ] **Step 2: Update `config/printer.cfg`**

Find: `[include btt-ebb-sb-usb-v1.0.cfg]`
Replace with: `[include toolhead.cfg]`

- [ ] **Step 3: Update `tests/test_macro_refcheck.py:108`**

Find the line `"config/btt-ebb-sb-usb-v1.0.cfg",` inside `test_real_repo_passes()` and replace with `"config/toolhead.cfg",`.

- [ ] **Step 4: Update `Makefile:7`**

Find: `CFGS        := config/printer.cfg config/eddy.cfg config/btt-ebb-sb-usb-v1.0.cfg ...`
Replace `btt-ebb-sb-usb-v1.0.cfg` with `toolhead.cfg`.

- [ ] **Step 5: Update `.github/workflows/ci.yml:131`**

Find the analogous CFG-list line and replace `btt-ebb-sb-usb-v1.0.cfg` with `toolhead.cfg`.

- [ ] **Step 6: Update `CLAUDE.md`**

```bash
grep -n "btt-ebb-sb-usb-v1.0\|btt-ebb-sb-usb-v1\.0" CLAUDE.md
```

Update each of the 4 hits:
- `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`
- In the repo-layout tree block, also update the inline comment ("RENAMED in Phase 4" → "toolhead MCU config").

- [ ] **Step 7: Update the master spec self-reference**

```bash
grep -n "btt-ebb-sb-usb-v1.0\|btt-ebb-sb-usb-v1\.0" docs/superpowers/specs/2026-05-15-config-macros-refactor.md
```

For each hit, update path. In the master spec's "Phase 4" section, add a one-line pointer: `> **Note:** Phase 4 implementation moved to [2026-05-16-phase4-macros-refactor-design.md](2026-05-16-phase4-macros-refactor-design.md).` at the top of the Phase 4 section.

- [ ] **Step 8: Re-run macro_refcheck + CI parse check locally**

```bash
make test-py 2>&1 | tail -20
# Expect: macro_refcheck tests PASS (renamed file is found at new path).
# test_real_repo_passes — PASS.
# Layer 5 tripwires from Task A.2 — still failing (expected; not yet addressed).
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(refactor): rename btt-ebb-sb-usb-v1.0.cfg → toolhead.cfg

The board name suggests CAN ("ebb"); the file actually configures the
toolhead. Rename clarifies role. Updates references in printer.cfg,
CI configs, refcheck, Makefile, CLAUDE.md, master spec.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A.4: Consolidate `[extruder]` PA + limits into `toolhead.cfg`

**Files:**
- Modify: `config/printer.cfg:231-238` (delete)
- Modify: `config/toolhead.cfg` (append)

- [ ] **Step 1: Re-read the source block**

Open `config/printer.cfg` around lines 227-238. The block is:

```ini
#####################################################################
#   Extruder
#####################################################################
#   E0 on MCU X/Y
[extruder]
min_temp: 0
max_temp: 270
max_power: 1.0
min_extrude_temp: 170
max_extrude_only_distance: 500
pressure_advance: 0.05
pressure_advance_smooth_time: 0.040
```

- [ ] **Step 2: Append the PA + limits keys to the existing `[extruder]` block in `toolhead.cfg`**

The existing `[extruder]` block ends at line 38 (after `pullup_resistor: 2200`). Append after that line, preserving alphabetical/logical ordering:

```ini
# PA + temp limits (consolidated from printer.cfg in Phase 4 PR-A).
min_temp: 0
max_temp: 270
max_power: 1.0
min_extrude_temp: 170
max_extrude_only_distance: 500
pressure_advance: 0.05
pressure_advance_smooth_time: 0.040
```

The `[tmc2209 extruder]` section directly below stays as-is.

- [ ] **Step 3: Delete the source block from `printer.cfg`**

Remove lines 227-238 (the three `#####` comment lines + `[extruder]` header + 7 key lines). Leave a blank line where the block used to be so the surrounding section header (`# Input Shaping`) stays separated.

- [ ] **Step 4: Run CI locally**

```bash
make test-py 2>&1 | tail -15
# Expect: test_extruder_section_single_file — PASS.
# Other tripwires still failing.
```

- [ ] **Step 5: Verify Klipper parse with klippy-smoke (Linux only; skip on macOS)**

```bash
make test 2>&1 | tail -10
# Expect (on Linux): klippy parse PASS. On macOS, this step is skipped.
```

- [ ] **Step 6: Commit**

```bash
git add config/printer.cfg config/toolhead.cfg
git commit -m "$(cat <<'EOF'
refactor(toolhead): consolidate [extruder] PA + limits into toolhead.cfg

[extruder] was split: stepper/heater pins in btt-ebb-sb-usb-v1.0.cfg (now
toolhead.cfg) and PA + temp limits in printer.cfg. Move the printer.cfg
half into toolhead.cfg so [extruder] has one home in our owned files.

Klipper merges multi-file sections at parse time — runtime config is
identical. SAVE_CONFIG #*# [extruder] PID values still merge as before.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A.5: Remove duplicate status sections

**Files:**
- Modify: `config/printer.cfg:96-97`
- Modify: `config/mainsail.cfg:32-39`
- Modify: `memory/decisions.md` (append)

- [ ] **Step 1: Delete `[exclude_object]` from `config/printer.cfg:96`**

Find:
```ini
[exclude_object]
[respond]
```
Replace with: (delete both lines; HH's mmu/addons/blobifier.cfg and mmu/base/mmu_macro_vars.cfg declare them).

- [ ] **Step 2: Delete `[pause_resume]`, `[display_status]`, `[respond]` from `config/mainsail.cfg`**

Lines 28-39 currently read:

```ini
[virtual_sdcard]
path: ~/printer_data/gcodes
on_error_gcode: CANCEL_PRINT

[pause_resume]
#recover_velocity: 50.
#   When capture/restore is enabled, the speed at which to return to
#   the captured position (in mm/s). Default is 50.0 mm/s.

[display_status]

[respond]
```

Keep `[virtual_sdcard]` (HH does not declare it). Delete `[pause_resume]`, `[display_status]`, `[respond]` blocks (12 lines total). The file's preamble comment block (lines 1-26) already explains the slim-copy strategy.

- [ ] **Step 3: Append rationale entry to `memory/decisions.md`**

Append the following section at the end of `memory/decisions.md` (preserving its existing structure):

```markdown
## 2026-05-16 — Defer status sections to Happy Hare

[respond], [exclude_object], [pause_resume], [display_status] now have a
single declaration in HH-owned files (config/mmu/base/mmu_macro_vars.cfg
and config/mmu/addons/blobifier.cfg) — our copies in config/printer.cfg
and config/mainsail.cfg are removed.

**Why:** Defer-to-HH rule from memory/defer-to-happy-hare.md. Reduces
duplicate-declaration noise; matches one-canonical-home discipline.

**How to apply:** If HH is ever disabled (mmu/base/*.cfg includes commented
out), Klipper load breaks until these declarations are restored in
config/printer.cfg / config/mainsail.cfg. Acceptable trade because HH is
structurally load-bearing on this build.

Refs: PR-A of Phase 4 (docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md).
```

- [ ] **Step 4: Run tripwire test**

```bash
pytest tests/test_config_structure.py::test_status_sections_declared_at_most_once -v
# Expect: PASS.
```

- [ ] **Step 5: Commit**

```bash
git add config/printer.cfg config/mainsail.cfg memory/decisions.md
git commit -m "$(cat <<'EOF'
refactor(includes): drop duplicate [respond]/[exclude_object]/[pause_resume]/[display_status]

These sections are also declared by Happy Hare:
- [respond], [pause_resume], [display_status] → config/mmu/base/mmu_macro_vars.cfg
- [exclude_object] → config/mmu/addons/blobifier.cfg

Per memory/defer-to-happy-hare.md, prefer HH's declarations. Documented
trade-off in memory/decisions.md (Klipper load breaks if HH is disabled
without restoring these — accepted given HH is load-bearing here).

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A.6: Add `description:` to every owned `[gcode_macro]`

**Files:**
- Modify: `config/macros/macros.cfg` (12 macros)
- Modify: `config/macros/bedfans.cfg` (8 macros)
- Modify: `config/macros/print_start.cfg` (3 macros)
- Modify: `config/macros/calibrate_flow.cfg` (1 macro — `_FLOW_CALIB_VARIABLES`)
- Modify: `config/eddy.cfg` (2 macros — `QUAD_GANTRY_LEVEL`, `BED_MESH_CALIBRATE`)

- [ ] **Step 1: List all targets**

```bash
grep -rEn "^\[gcode_macro|^description:" config/macros/ config/eddy.cfg \
  | grep -v "^description:" | sort -u
```

Cross-check against the file list above: 26 macros expected to need `description:`.

- [ ] **Step 2: Add descriptions in `config/macros/macros.cfg`**

For each macro listed, add `description: <text>` as the first line under the `[gcode_macro X]` header. Use these exact descriptions:

```ini
[gcode_macro _CG28]
description: Internal helper: G28 only if not already homed.

[gcode_macro _CQGL]
description: Internal helper: QUAD_GANTRY_LEVEL only if not already applied.

[gcode_macro OFF]
description: Shut everything off (steppers, heaters, part fan, chamber fan, bed fans, case light).

[gcode_macro SHUTDOWN]
description: OFF + tell Moonraker to power off the host.

[gcode_macro PARKFRONT]
description: Park toolhead at front center, mid-height.

[gcode_macro PARKFRONTLOW]
description: Park toolhead at front center, low Z.

[gcode_macro PARKREAR]
description: Park toolhead at rear left, near top.

[gcode_macro _RESETSPEEDS]
description: Internal helper: revert velocity/accel/SCV to configured maxima.

[gcode_macro PARKCENTER]
description: Park toolhead at center of build volume.

[gcode_macro PARKBED]
description: Park toolhead 15mm above center of bed.

[gcode_macro M109]
description: Wait for hotend within ±1 °C of target (renames stock to M99109).

[gcode_macro HEATSOAK]
description: Heat bed (+ optional chamber wait) and park center for soak.
```

- [ ] **Step 3: Add descriptions in `config/macros/bedfans.cfg`**

```ini
[gcode_macro _BEDFANVARS]
description: Internal: BedFans config (threshold, fast/slow speeds). Removed in PR-B (rolled into _USER_VARIABLE).

[gcode_macro BEDFANSSLOW]
description: Set bed fans to "slow" speed (while heater is ramping).

[gcode_macro BEDFANSFAST]
description: Set bed fans to "fast" speed (after target reached).

[gcode_macro BEDFANSOFF]
description: Turn bed fans off.

[gcode_macro SET_HEATER_TEMPERATURE]
description: Override of stock SET_HEATER_TEMPERATURE — integrates bed-fan logic.

[gcode_macro M190]
description: Override of stock M190 — uses TEMPERATURE_WAIT and triggers bed fans.

[gcode_macro M140]
description: Alias to SET_HEATER_TEMPERATURE so bed-fan logic fires on M140 too.

[gcode_macro TURN_OFF_HEATERS]
description: Override of stock TURN_OFF_HEATERS — also turns bed fans off.
```

- [ ] **Step 4: Add descriptions in `config/macros/print_start.cfg`**

```ini
[gcode_macro PRINT_WARMUP]
description: Pre-heat without printing (caselight on, BED_MESH_CLEAR, home, QGL, start bed+ext heating).

[gcode_macro PRINT_START]
description: Full print start: tap-threshold guard → home → QGL → bed heat + chamber wait → BLOBIFIER_CLEAN → re-home Z → adaptive bed mesh → heat hotend.

[gcode_macro PRINT_END]
description: Cool, clear mesh, wait 60s, OFF, _RESETSPEEDS.
```

- [ ] **Step 5: Add description in `config/macros/calibrate_flow.cfg`**

The 3rd macro (`_FLOW_CALIB_VARIABLES` at line 33) lacks description:

```ini
[gcode_macro _FLOW_CALIB_VARIABLES]
description: Internal state holder for FLOW_MULTIPLIER_CALIBRATION / COMPUTE_FLOW_MULTIPLIER.
```

- [ ] **Step 6: Add descriptions in `config/eddy.cfg`**

```ini
[gcode_macro QUAD_GANTRY_LEVEL]
description: Two-pass QGL override (coarse METHOD=default then tight METHOD=scan); saggy-rear-V2 quirk requires both passes.

[gcode_macro BED_MESH_CALIBRATE]
description: Wrap stock BED_MESH_CALIBRATE to force ADAPTIVE=1 METHOD=rapid_scan.
```

- [ ] **Step 7: Run tripwire test**

```bash
pytest tests/test_config_structure.py::test_every_owned_macro_has_description -v
# Expect: PASS.
```

- [ ] **Step 8: Commit**

```bash
git add config/macros/*.cfg config/eddy.cfg
git commit -m "$(cat <<'EOF'
refactor(macros): add description: field to every owned [gcode_macro]

26 macros across config/macros/* and config/eddy.cfg now carry a
description: field. Layer 5 tripwire enforces this going forward.
MMU-owned macros excluded (symlinks to ~/Happy-Hare/config/base/).

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A.7: Reorganize `[include]` order in `printer.cfg`

**Files:**
- Modify: `config/printer.cfg:68-73`, `config/printer.cfg:397-405`

- [ ] **Step 1: Read current state**

```bash
grep -n "^\[include\|^#####\|^# ----\|^#---" config/printer.cfg
```

Currently includes are split between two locations (top and bottom). The reorg consolidates them under one block near the bottom (just before `SAVE_CONFIG`), grouped with section comments.

- [ ] **Step 2: Define the target block**

Insert this block at the position currently occupied by lines 396-405 (the existing bottom-of-file includes), and DELETE the includes at lines 68-73 (the top block). The block:

```ini
#####################################################################
#   File includes
#####################################################################
# MCU + hardware
[include toolhead.cfg]

# Probe + bed leveling + homing override
[include eddy.cfg]

# MMU (Happy Hare)
[include mmu/base/*.cfg]
[include mmu/optional/client_macros.cfg]
[include mmu/optional/mmu_menu.cfg]
[include mmu/addons/blobifier.cfg]

# Client (Mainsail + timelapse)
[include mainsail.cfg]
[include timelapse.cfg]

# Macros
[include macros/macros.cfg]
[include macros/test_speed.cfg]
[include macros/lcd_tweaks.cfg]
[include macros/bedfans.cfg]
[include macros/print_start.cfg]
[include macros/calibrate_flow.cfg]
[include macros/calibrate_pa.cfg]
```

- [ ] **Step 3: Verify Klipper parses (Linux)**

```bash
make test 2>&1 | tail -10
# Expect: klippy parse PASS.
```

On macOS, run `make test-py` and review the diff manually.

- [ ] **Step 4: Verify macro_refcheck still resolves**

```bash
pytest tests/test_macro_refcheck.py -v
# Expect: ALL PASS.
```

- [ ] **Step 5: Commit**

```bash
git add config/printer.cfg
git commit -m "$(cat <<'EOF'
refactor(includes): reorganize printer.cfg include order with section comments

Previously: 6 includes near the top + 7 near the bottom (no grouping).
Now: one consolidated block with comments grouping by concern (MCU,
probe/leveling, MMU, client, macros).

Final merged config is identical (Klipper resolves includes order-
independently for non-overriding sections).

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A.8: Local CI + review-pr + push + PR

- [ ] **Step 1: Run the full local test suite**

```bash
make test-py 2>&1 | tail -30
# Expect: ALL PASS (including all new Layer 5 tripwires).
```

On a Linux box (or via CI), also run:

```bash
make test 2>&1 | tail -10
# Expect: klippy parse PASS.
```

- [ ] **Step 2: Run `pr-review-toolkit:review-pr`**

```bash
# In Claude Code: /review-pr
```

Address any blocking findings before pushing.

- [ ] **Step 3: Run `klipper-cfg-reviewer` on the .cfg diffs**

```bash
git diff main -- "config/*.cfg" "config/macros/*.cfg" > /tmp/phase4a-cfg-diff.patch
# In Claude Code, dispatch the klipper-cfg-reviewer subagent on the diff.
```

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/refactor-phase4a-structural
gh pr create --title "feat(refactor): Phase 4 PR-A — structural cleanup (toolhead rename, [extruder] consolidate, descriptions, includes)" --body "$(cat <<'EOF'
## Summary

- Rename `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`
- Consolidate `[extruder]` PA + limits from `printer.cfg` into `toolhead.cfg`
- Drop duplicate `[respond]/[exclude_object]/[pause_resume]/[display_status]` (HH owns)
- Add `description:` to every owned `[gcode_macro]` (26 macros)
- Reorganize `printer.cfg` includes with section-comment groups
- Three Layer 5 tripwires guard the invariants

No behavior change. PR-B (next) introduces `_USER_VARIABLE` and migrates
tunables to it; this PR is the structural prerequisite.

Spec: `docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md`

## Test plan

- [x] `make test-py` — green locally (pre-commit + macro_refcheck + pytest + Layer 5)
- [x] `make test` (klippy parse on Linux CI) — green
- [x] `pr-review-toolkit:review-pr` — no blocking findings
- [x] `klipper-cfg-reviewer` — no blocking findings
- [ ] Post-merge: `/deploy-to-pi --smoke` — passes (G28, PARKCENTER, OFF, _RESETSPEEDS without `^!! ` in klippy.log)
- [ ] Post-merge: First print runs to completion without regression

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: After CI green + merge, run deploy + smoke**

In Claude Code: `/deploy-to-pi --smoke`. Confirm Pi reaches `printer.state == "ready"` and the smoke gcode sequence runs clean.

- [ ] **Step 6: Clean up the PR-A worktree**

Use `ExitWorktree` (per `superpowers:using-git-worktrees`) once the PR is merged and deploy is verified.

---

## PR-B: `_USER_VARIABLE` migration

### Task B.1: Create the worktree

- [ ] **Step 1: Pull main locally (PR-A must be merged before starting)**

```bash
git fetch origin
git log origin/main -3
# Expect: PR-A merge commit visible.
```

- [ ] **Step 2: Create worktree from `main`**

Use `EnterWorktree` with branch `feat/refactor-phase4b-user-variable` based on `main`.

---

### Task B.2: Add Layer 5 tripwires for `_USER_VARIABLE`

**Files:**
- Modify: `tests/test_config_structure.py` (extend)

- [ ] **Step 1: Append two failing tests**

```python
# Append to tests/test_config_structure.py

USER_VAR_FILE = REPO_ROOT / "config/macros/_user_variables.cfg"
USER_VAR_REF_RE = re.compile(r'_USER_VARIABLE"?\]\.(\w+)')


def _user_variable_definitions():
    """Return set of `variable_X` names defined in _user_variables.cfg."""
    if not USER_VAR_FILE.exists():
        return set()
    text = USER_VAR_FILE.read_text()
    return set(re.findall(r"^variable_(\w+):", text, re.MULTILINE))


def _user_variable_refs():
    """Return set of `variable_X` names referenced anywhere in our owned macros."""
    refs = set()
    for cfg in OWNED_MACRO_FILES + [str(REPO_ROOT / "config/macros/_user_variables.cfg")]:
        if not Path(cfg).exists():
            continue
        for m in USER_VAR_REF_RE.finditer(Path(cfg).read_text()):
            refs.add(m.group(1))
    return refs


def test_user_variable_refs_resolve():
    """Every _USER_VARIABLE.X reference resolves to a variable_X: definition."""
    defs = _user_variable_definitions()
    refs = _user_variable_refs()
    unresolved = refs - defs
    assert not unresolved, f"_USER_VARIABLE refs without matching variable_X: {sorted(unresolved)}"


def test_user_variable_definitions_used():
    """Every variable_X: definition is referenced somewhere (no orphans)."""
    defs = _user_variable_definitions()
    if not defs:
        return  # _user_variables.cfg doesn't exist yet — skip this PR-B-only test
    refs = _user_variable_refs()
    orphans = defs - refs
    assert not orphans, f"Orphan variable_X definitions: {sorted(orphans)}"
```

- [ ] **Step 2: Run; verify behavior**

```bash
pytest tests/test_config_structure.py::test_user_variable_refs_resolve tests/test_config_structure.py::test_user_variable_definitions_used -v
# Expect: BOTH PASS (no refs yet, no defs yet — both sets are empty).
```

The tests are PASSING-trivially right now; they'll catch real issues once the migration starts.

- [ ] **Step 3: Commit**

```bash
git add tests/test_config_structure.py
git commit -m "$(cat <<'EOF'
chore(tests): add Layer 5 tripwires for _USER_VARIABLE invariants

Two tripwires: _USER_VARIABLE.X references resolve to a definition; every
defined variable is referenced (no orphans). Pass trivially now; gain
teeth once PR-B starts adding refs.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.3: Add `scripts/macro_behavior_diff.py` + `make snapshot-before`

**Files:**
- Create: `scripts/macro_behavior_diff.py`
- Modify: `Makefile`
- Create: `tests/snapshots/.gitkeep`

- [ ] **Step 1: Create the snapshot directory**

```bash
mkdir -p tests/snapshots
touch tests/snapshots/.gitkeep
```

- [ ] **Step 2: Create `scripts/macro_behavior_diff.py`**

```python
#!/usr/bin/env python3
"""Layer 7 (one-shot) — drive test_klippy.py with a fixed macro set and capture the expanded gcode.

Usage:
  python scripts/macro_behavior_diff.py before   # writes tests/snapshots/macro_behavior_before.txt
  python scripts/macro_behavior_diff.py after    # writes tests/snapshots/macro_behavior_after.txt

The script writes a temporary .test file containing the fixed macro invocations,
runs `vendor/klipper/scripts/test_klippy.py` on it, and captures the dispatcher
output (the gcode emitted by each macro after Jinja expansion).

Diff `before` vs `after`; non-comment, non-whitespace differences fail the merge gate.
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO / "tests/snapshots"

# Macros exercised by the diff. Picked to cover every site that PR-B touches.
MACROS = [
    "PARKCENTER",
    "HEATSOAK BED_TEMP=110 EXTRUDER_TEMP=240",
    "BEDFANSSLOW",
    "BEDFANSFAST",
    "M109 S240",
    "M190 S110",
    "M140 S110",
    "TURN_OFF_HEATERS",
    "OFF",
    "PRINT_END",
]


def build_test_file(out_path: Path) -> None:
    """Write a .test file that loads printer.cfg and runs each macro."""
    lines = [
        "CONFIG ../config/printer.cfg",
        "DICTIONARY mcu.dict z=mcu.dict EBB=ebb-usb.dict eddy=eddy.dict mmu=easy-brd.dict",
    ]
    for m in MACROS:
        lines.append(m)
    out_path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=["before", "after"])
    args = parser.parse_args()

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    test_file = SNAPSHOT_DIR / f"_layer7_{args.label}.test"
    build_test_file(test_file)

    out = SNAPSHOT_DIR / f"macro_behavior_{args.label}.txt"
    klipper_dir = REPO / "vendor/klipper"
    test_klippy = klipper_dir / "scripts/test_klippy.py"
    dict_dir = REPO / "tests/dict"

    if not test_klippy.exists():
        sys.exit("vendor/klipper not initialized; run `git submodule update --init` first.")

    cmd = [
        sys.executable,
        str(test_klippy),
        "-d", str(dict_dir),
        str(test_file),
    ]
    proc = subprocess.run(cmd, cwd=klipper_dir, capture_output=True, text=True)
    # test_klippy.py writes a per-test log; capture stdout+stderr as the snapshot.
    snapshot = (
        f"# Layer 7 macro behavior snapshot — {args.label}\n"
        f"# Generated from: {' '.join(MACROS)}\n"
        f"# exit={proc.returncode}\n"
        f"-- STDOUT --\n{proc.stdout}\n"
        f"-- STDERR --\n{proc.stderr}\n"
    )
    out.write_text(snapshot)
    print(f"Wrote {out}")
    if proc.returncode != 0:
        print("WARNING: test_klippy.py exit != 0 — review snapshot before trusting it.", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add Makefile targets**

Append to `Makefile`:

```makefile
.PHONY: snapshot-before snapshot-after snapshot-diff
snapshot-before:
	python scripts/macro_behavior_diff.py before

snapshot-after:
	python scripts/macro_behavior_diff.py after

snapshot-diff:
	diff -w tests/snapshots/macro_behavior_before.txt tests/snapshots/macro_behavior_after.txt
```

- [ ] **Step 4: Capture the "before" snapshot**

```bash
make snapshot-before
ls -la tests/snapshots/
# Expect: macro_behavior_before.txt exists.
```

This step requires Linux (Klipper's chelper); if working on macOS, run it via Docker or a Linux CI environment. The plan assumes Linux availability at this step — flag as a prerequisite.

- [ ] **Step 5: Commit**

```bash
git add scripts/macro_behavior_diff.py Makefile tests/snapshots/.gitkeep tests/snapshots/macro_behavior_before.txt
git commit -m "$(cat <<'EOF'
chore(tests): add Layer 7 behavior-diff scaffold + snapshot-before

scripts/macro_behavior_diff.py drives test_klippy.py with a fixed macro set
and captures dispatcher output. `make snapshot-{before,after}` produces a
pair of snapshots to diff; `make snapshot-diff` validates whitespace-only
delta.

Snapshot-before captured against pre-_USER_VARIABLE state.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.4: Add `config/macros/_user_variables.cfg`

**Files:**
- Create: `config/macros/_user_variables.cfg`
- Modify: `config/printer.cfg` (add include)

- [ ] **Step 1: Create the file**

```ini
# Single source of truth for printer-level tunables (Phase 4 PR-B).
# Edit values here; consumers read via printer["gcode_macro _USER_VARIABLE"].X.
#
# Convention: include this BEFORE any macro file that reads from it. The
# render-once-per-macro Jinja rule (see CLAUDE.md "Klipper gotchas") doesn't
# bite us here because each consuming macro reads at its own invocation —
# the value is fresh each time.

[gcode_macro _USER_VARIABLE]
description: Single source of truth for printer-level tunables.
# Bed fans (was [_BEDFANVARS] in bedfans.cfg, identical semantics)
variable_bedfans_threshold: 100
variable_bedfans_fast: 0.6
variable_bedfans_slow: 0.2
# Heatsoak defaults (HEATSOAK macro in macros.cfg)
variable_heatsoak_default_bed_target: 110
variable_heatsoak_default_chamber_target: 30
# Hotend wait tolerance (M109 override in macros.cfg)
variable_m109_tolerance_celsius: 1
# Print sequence pacing (print_start.cfg)
variable_chamber_wait_bed_threshold: 90      # bed temp above which we wait for chamber
variable_print_end_cooldown_seconds: 60      # PRINT_END "let things circulate" delay
gcode:
# variables only — no body
```

- [ ] **Step 2: Add the include line to `config/printer.cfg`**

In the reorganized `[include]` block from PR-A, add a new group ABOVE "Macros":

```ini
# User tunables (must be loaded before macros that read from _USER_VARIABLE)
[include macros/_user_variables.cfg]
```

- [ ] **Step 3: Run the test_user_variable_definitions_used tripwire**

```bash
pytest tests/test_config_structure.py::test_user_variable_definitions_used -v
# Expect: FAIL — eight variables defined, none referenced yet.
```

This is the expected failing state. Subsequent tasks add references; this test goes green when migration is complete.

- [ ] **Step 4: Run macro_refcheck**

```bash
pytest tests/test_macro_refcheck.py -v
# Expect: PASS — the new file has no macro references to resolve.
```

- [ ] **Step 5: Commit**

```bash
git add config/macros/_user_variables.cfg config/printer.cfg
git commit -m "$(cat <<'EOF'
feat(macros): introduce _user_variables.cfg with printer-level tunables

Single [gcode_macro _USER_VARIABLE] block. Values are duplicates of what's
currently hardcoded in bedfans.cfg/_BEDFANVARS (threshold/fast/slow),
macros.cfg HEATSOAK defaults + M109 tolerance, and print_start.cfg's
chamber-wait threshold + PRINT_END cooldown.

Subsequent commits migrate readers from the old hardcoded values to
_USER_VARIABLE.X. Layer 5 tripwire test_user_variable_definitions_used
fails now and will pass when migration completes.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.5: Migrate `bedfans.cfg`

**Files:**
- Modify: `config/macros/bedfans.cfg`

- [ ] **Step 1: Read current state**

```bash
grep -n "_BEDFANVARS" config/macros/bedfans.cfg
```

Expected: 5 reads of `printer["gcode_macro _BEDFANVARS"].threshold|.fast|.slow|int|float`, plus the definition at lines 2-6.

- [ ] **Step 2: Replace all `_BEDFANVARS` reads with `_USER_VARIABLE` reads**

In `config/macros/bedfans.cfg`:

- `BEDFANSSLOW` (line 18): replace `printer["gcode_macro _BEDFANVARS"].slow|float` → `printer["gcode_macro _USER_VARIABLE"].bedfans_slow|float`
- `BEDFANSFAST` (line 25): replace `printer["gcode_macro _BEDFANVARS"].fast|float` → `printer["gcode_macro _USER_VARIABLE"].bedfans_fast|float`
- `SET_HEATER_TEMPERATURE` (line 42): replace `printer["gcode_macro _BEDFANVARS"].threshold|int` → `printer["gcode_macro _USER_VARIABLE"].bedfans_threshold|int`
- `M190` (line 71): same threshold replacement.
- `delayed_gcode bedfanloop` (line 113): same threshold replacement.

- [ ] **Step 3: Delete the `[gcode_macro _BEDFANVARS]` block (lines 2-6)**

Lines 1-6 currently:

```ini
############### Config options ##################
[gcode_macro _BEDFANVARS]
variable_threshold: 100		# ...
variable_fast: 0.6		# ...
variable_slow: 0.2		# ...
gcode:
```

Replace with a single comment line:

```ini
############### Config options now live in _user_variables.cfg ##################
```

- [ ] **Step 4: Run tripwires**

```bash
pytest tests/test_config_structure.py -v
# Expect: test_user_variable_refs_resolve PASS;
# test_user_variable_definitions_used — still FAIL (only 3/8 vars referenced);
# Other tests — PASS.
```

- [ ] **Step 5: Run macro_refcheck**

```bash
pytest tests/test_macro_refcheck.py -v
# Expect: PASS — _BEDFANVARS not referenced (renamed in template).
```

- [ ] **Step 6: Commit**

```bash
git add config/macros/bedfans.cfg
git commit -m "$(cat <<'EOF'
refactor(bedfans): read tunables from _USER_VARIABLE; delete _BEDFANVARS

5 read sites migrated from printer["gcode_macro _BEDFANVARS"].X to
printer["gcode_macro _USER_VARIABLE"].bedfans_X. _BEDFANVARS definition
deleted (values now live in _user_variables.cfg).

Values copied verbatim — Layer 7 behavior diff (later commit) is the
proof.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.6: Migrate `macros.cfg` (HEATSOAK + M109)

**Files:**
- Modify: `config/macros/macros.cfg`

- [ ] **Step 1: Migrate HEATSOAK defaults**

Find (line 116):
```ini
    {% set t = params.T|default(110)|int %}
    {% set c = params.C|default(30)|int %}
```

Replace with:
```ini
    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
    {% set t = params.T|default(uv.heatsoak_default_bed_target)|int %}
    {% set c = params.C|default(uv.heatsoak_default_chamber_target)|int %}
```

- [ ] **Step 2: Migrate M109 tolerance**

Find (line 106 area):
```ini
        TEMPERATURE_WAIT SENSOR=extruder MINIMUM={s} MAXIMUM={s+1}   ; Wait for hotend temp (within 1 degree)
```

Replace with:
```ini
        {% set tol = printer["gcode_macro _USER_VARIABLE"].m109_tolerance_celsius|int %}
        TEMPERATURE_WAIT SENSOR=extruder MINIMUM={s} MAXIMUM={s + tol}   ; Wait for hotend temp (within tolerance)
```

- [ ] **Step 3: Run tripwires**

```bash
pytest tests/test_config_structure.py -v
# Expect: test_user_variable_refs_resolve PASS; definitions_used still
# FAIL (5/8 vars referenced).
```

- [ ] **Step 4: Commit**

```bash
git add config/macros/macros.cfg
git commit -m "$(cat <<'EOF'
refactor(macros): HEATSOAK + M109 read tunables from _USER_VARIABLE

HEATSOAK default bed_target (110) and chamber_target (30) now read from
_USER_VARIABLE.heatsoak_default_bed_target / .heatsoak_default_chamber_target.
M109's ±1°C tolerance reads from .m109_tolerance_celsius.

Values copied verbatim.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.7: Migrate `print_start.cfg`

**Files:**
- Modify: `config/macros/print_start.cfg`

- [ ] **Step 1: Migrate the chamber-wait threshold**

Find (line 46):
```ini
  {% if params.BED|int > 90 %}
```

Replace with:
```ini
  {% if params.BED|int > printer["gcode_macro _USER_VARIABLE"].chamber_wait_bed_threshold|int %}
```

- [ ] **Step 2: Migrate PRINT_END cooldown**

Find (line 76):
```ini
    G4 P60000 ;wait 5 min to let things circulate and cool down
```

Replace with:
```ini
    G4 P{(printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds * 1000)|int} ;wait to let things circulate and cool down
```

(Note: the previous comment claimed "5 min" but the actual value is 60s. Comment also updated.)

- [ ] **Step 3: Run all Layer 5 tripwires**

```bash
pytest tests/test_config_structure.py -v
# Expect: ALL PASS — test_user_variable_definitions_used now passes
# (all 8 vars referenced); other tripwires green.
```

- [ ] **Step 4: Run macro_refcheck**

```bash
pytest tests/test_macro_refcheck.py -v
# Expect: PASS.
```

- [ ] **Step 5: Commit**

```bash
git add config/macros/print_start.cfg
git commit -m "$(cat <<'EOF'
refactor(print_start): chamber-wait threshold + cooldown read from _USER_VARIABLE

PRINT_START's bed > 90 check now reads chamber_wait_bed_threshold; PRINT_END's
G4 P60000 reads print_end_cooldown_seconds (also fixed misleading comment —
60s, not 5 min as the comment claimed).

All eight _USER_VARIABLE variables now referenced. Migration complete.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.8: Generate "after" snapshot; verify diff

**Files:**
- Create: `tests/snapshots/macro_behavior_after.txt`

- [ ] **Step 1: Capture the "after" snapshot**

```bash
make snapshot-after
ls -la tests/snapshots/
# Expect: both before and after files present.
```

(Linux required, same as Task B.3 Step 4.)

- [ ] **Step 2: Diff**

```bash
make snapshot-diff > /tmp/layer7.diff 2>&1
echo "exit=$?"
```

- [ ] **Step 3: Manually classify diff content**

The diff MUST contain only:
- Comment changes (lines starting with `#` after `;` or in `# ...` form)
- Whitespace differences (already stripped by `diff -w`)
- The `# variables only — no body` line introduced by `_USER_VARIABLE`

Any other delta is a behavior regression. Investigate and fix; do NOT proceed to push.

Expected diff content (illustrative — exact bytes depend on klippy version):
- Maybe a new `_USER_VARIABLE` block in the macro-loading section.
- No changes in the emitted gcode for `PARKCENTER`, `HEATSOAK`, `BEDFANSSLOW`, `BEDFANSFAST`, `M109`, `M190`, `M140`, `TURN_OFF_HEATERS`, `OFF`, `PRINT_END`.

- [ ] **Step 4: Commit the snapshot**

```bash
git add tests/snapshots/macro_behavior_after.txt
git commit -m "$(cat <<'EOF'
chore(tests): generate Layer 7 snapshot-after; verify whitespace-only diff

Diff vs snapshot-before is comments + whitespace only — no behavior change.
Both snapshots committed for audit trail.

Refs: docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B.9: Local CI + review-pr + push + PR

- [ ] **Step 1: Full local test run**

```bash
make test-py 2>&1 | tail -30
# Expect: ALL PASS.
```

- [ ] **Step 2: Run `pr-review-toolkit:review-pr`**

```bash
# In Claude Code: /review-pr
```

- [ ] **Step 3: Run `klipper-cfg-reviewer` on the .cfg diffs**

```bash
git diff main -- "config/*.cfg" "config/macros/*.cfg" > /tmp/phase4b-cfg-diff.patch
# Dispatch klipper-cfg-reviewer on the diff.
```

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin feat/refactor-phase4b-user-variable
gh pr create --title "feat(refactor): Phase 4 PR-B — _USER_VARIABLE migration" --body "$(cat <<'EOF'
## Summary

- Add `config/macros/_user_variables.cfg` with a single `[gcode_macro _USER_VARIABLE]` holding 8 tunables
- Migrate `bedfans.cfg`, `macros.cfg`, `print_start.cfg` to read from `_USER_VARIABLE`
- Delete `[gcode_macro _BEDFANVARS]`
- Two new Layer 5 tripwires enforce reference resolution + no-orphans
- Layer 7 behavior-diff snapshot pair committed; diff is whitespace-only

No behavior change. Spec: `docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md`.

## Test plan

- [x] `make test-py` — green (all Layer 5 tripwires)
- [x] `make snapshot-diff` — whitespace-only delta
- [x] `pr-review-toolkit:review-pr` — no blocking findings
- [x] `klipper-cfg-reviewer` — no blocking findings
- [ ] Post-merge: `/deploy-to-pi --smoke` — passes
- [ ] Post-merge: first print runs to completion without regression

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: After CI green + merge, deploy + smoke**

In Claude Code: `/deploy-to-pi --smoke`.

- [ ] **Step 6: Clean up the PR-B worktree**

Use `ExitWorktree`.

---

## Post-completion

- [ ] **Step 1: Update CLAUDE.md repo-layout tree**

After both PRs merge, edit `CLAUDE.md` to reflect:
- `toolhead.cfg` (replaced `btt-ebb-sb-usb-v1.0.cfg`)
- `_user_variables.cfg` (new file under `macros/`)
- Remove the "(rename to toolhead.cfg planned in refactor Phase 4)" inline comment.

This is a small docs-only follow-up commit on `main` (per `memory/docs-direct-to-main.md` — docs-only changes can bypass PR).

- [ ] **Step 2: Update master spec status**

In `docs/superpowers/specs/2026-05-15-config-macros-refactor.md`, mark Phase 4 as **shipped** with links to the two PRs and this plan.

- [ ] **Step 3: Memory record**

If anything surprising came up during implementation (a Klipper quirk, an unexpected dependency, a test-infra gotcha), capture it as a memory file. Otherwise no memory update is needed — the spec and decisions.md cover the design rationale.

---

## Summary

Two PRs, in series:

- **PR-A — Structural cleanup.** Rename `btt-ebb-sb-usb-v1.0.cfg` → `toolhead.cfg`; consolidate `[extruder]`; drop four duplicate status sections; add `description:` to 26 macros; reorganize `[include]` order. Three Layer 5 tripwires guard the result.
- **PR-B — `_USER_VARIABLE` migration.** Introduce `_user_variables.cfg` with 8 tunables; migrate `bedfans.cfg` + `macros.cfg` + `print_start.cfg` to read from it; delete `_BEDFANVARS`. Two Layer 5 tripwires + one Layer 7 behavior-diff snapshot pair prove zero behavior change.

Spec: `docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md`.
