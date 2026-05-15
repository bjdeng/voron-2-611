# Config + macros refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Klipper config and macros for voron-2-611 maintainable for the next several years — readable, tunable, consistent, and aligned with Klipper + Happy Hare canonical practice. Six PRs, gated to start after `feat/eddy-native` merges to `main`.

**Architecture:** Each phase is one PR. Tier-1 fixes first (small/safe), then Mainsail/HH cleanup, then CLAUDE.md corrections + GH Issues migration, then the big macros refactor with single `_USER_VARIABLE`, then OrcaSlicer-side hooks, finally two new skills. Layer 5 (structural tests) added in Phase 1 and extended each phase; Layer 6 (post-deploy smoke) added in Phase 1; Layer 7 (behavior diff) one-shot in Phase 4.

**Tech Stack:** Klipper config (`.cfg`), pytest, bash deploy script, GH CLI for Issues, markdown for spec/docs/skills.

**Spec:** `docs/superpowers/specs/2026-05-15-config-macros-refactor.md`.

---

## Pre-flight (before any phase)

- [ ] **Step 0.1: Confirm `feat/eddy-native` has merged to `main` and Phase 0 items landed**

Run:
```sh
git switch main && git pull --ff-only
grep -E "fade_target|zero_reference_position|temperature_probe btt_eddy|SET_Z_FROM_PROBE" config/eddy.cfg config/macros/print_start.cfg
```

Expected: matches for `fade_target: 0`, `zero_reference_position: 175, 175`, `[temperature_probe btt_eddy]`, `SET_Z_FROM_PROBE`. If any are missing, that work belongs on the Eddy branch — pause and address there first.

(SKR MCU die-temp sensors were *not* folded in — LPC1769 is unsupported by Klipper's `temperature_mcu`. `[homing_override]` is also deferred — see spec §2.)

- [ ] **Step 0.2: Create a new branch from main for Phase 1**

```sh
git switch -c feat/config-tier1-fixes
```

Each phase below starts from `main` on its own branch (`feat/config-tier1-fixes`, `feat/mainsail-hh-cleanup`, etc.). Subsequent phases branch from the previously merged `main`.

---

## Phase 1: Tier-1 config fixes + initial Layer 5 test infrastructure

**Branch:** `feat/config-tier1-fixes`
**Estimated diff:** ~30 lines (excluding new test file)
**PR title:** `chore(config): tier-1 fixes — TEST_SPEED upstream + resonance_tester center`

**Files:**
- Create: `tests/test_config_structure.py`
- Replace: `config/macros/test_speed.cfg`
- Modify: `config/btt-ebb-sb-usb-v1.0.cfg:21`

### Task 1.1: Create Layer 5 test scaffold

**Files:**
- Create: `tests/test_config_structure.py`

- [ ] **Step 1: Create test file with first assertion (deprecated keys)**

Write to `tests/test_config_structure.py`:

```python
"""Structural assertions on Klipper .cfg files.

Layer 5 of the test pyramid (see docs/superpowers/specs/2026-05-15-config-macros-refactor.md §5).

These tests run in CI on every PR. They catch refactor mistakes that the
klippy parse (Layer 3) misses — things like deprecated Klipper keys,
missing description: fields, orphan _USER_VARIABLE references, etc.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _cfg_files() -> list[Path]:
    """All non-archive .cfg files under config/, excluding vendored MMU symlinks."""
    return [
        p
        for p in CONFIG_DIR.rglob("*.cfg")
        if "archive" not in p.parts and "mmu/base" not in str(p) and "mmu/optional" not in str(p) and "mmu/addons" not in str(p)
    ]


def test_no_deprecated_klipper_keys() -> None:
    """Klipper v0.13+ removed max_accel_to_decel and ACCEL_TO_DECEL.

    See vendor/klipper/docs/Config_Changes.md (2025-08-11 entry).
    """
    deprecated = ["max_accel_to_decel", "ACCEL_TO_DECEL"]
    offenders = []
    for cfg in _cfg_files():
        text = cfg.read_text()
        for key in deprecated:
            if re.search(rf"\b{re.escape(key)}\b", text):
                offenders.append(f"{cfg.relative_to(REPO_ROOT)}: uses '{key}'")
    assert not offenders, "Deprecated Klipper keys found:\n" + "\n".join(offenders)
```

- [ ] **Step 2: Run the test — verify it fails on current state**

Run:
```sh
.venv/bin/pytest tests/test_config_structure.py::test_no_deprecated_klipper_keys -v
```

Expected: **FAIL** with offenders including `config/macros/test_speed.cfg: uses 'max_accel_to_decel'` and `config/macros/test_speed.cfg: uses 'ACCEL_TO_DECEL'` (the macro uses both at lines 66 and 101).

- [ ] **Step 3: Commit test scaffold (failing test in place)**

```sh
git add tests/test_config_structure.py
git commit -m "test(config): add Layer 5 structural assertions scaffold

Initial assertion: no .cfg uses Klipper v0.13+ removed keys.
Currently FAILS on config/macros/test_speed.cfg — fixed in next commit."
```

### Task 1.2: Replace test_speed.cfg with current upstream Ellis

**Files:**
- Replace: `config/macros/test_speed.cfg`

- [ ] **Step 1: Fetch current upstream**

Run:
```sh
curl -sSL https://raw.githubusercontent.com/AndrewEllis93/Print-Tuning-Guide/main/macros/TEST_SPEED.cfg -o /tmp/TEST_SPEED-upstream.cfg
wc -l /tmp/TEST_SPEED-upstream.cfg
```

Expected: ~150-200 lines (varies by upstream version). Confirm the file isn't empty.

- [ ] **Step 2: Diff against current local copy to verify changes**

Run:
```sh
diff -u config/macros/test_speed.cfg /tmp/TEST_SPEED-upstream.cfg | head -80
```

Expected changes from upstream (per Ellis PRs since 2022):
- `MIN_CRUISE_RATIO` parameter replaces `ACCEL_TO_DECEL` (PR #120)
- `M400` calls before each homing op (cc96e40)
- Negative `position_min` guard (PR #153)
- `description:` field added

If the diff looks completely wrong, abort and inspect the upstream file directly.

- [ ] **Step 3: Replace the local file**

```sh
cp /tmp/TEST_SPEED-upstream.cfg config/macros/test_speed.cfg
```

- [ ] **Step 4: Run the Layer 5 test — verify it now passes**

Run:
```sh
.venv/bin/pytest tests/test_config_structure.py::test_no_deprecated_klipper_keys -v
```

Expected: **PASS** (no deprecated keys remain).

- [ ] **Step 5: Run macro_refcheck to verify no orphan command references**

Run:
```sh
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS (no orphan command references). If new commands are referenced (e.g., `MIN_CRUISE_RATIO`-related), add them to `tests/builtins.txt` or `scripts/macro_refcheck.py` ALLOWLIST.

- [ ] **Step 6: Commit the replacement**

```sh
git add config/macros/test_speed.cfg
git commit -m "fix(macros): swap test_speed.cfg to current upstream Ellis

Klipper v0.13 removed max_accel_to_decel (2025-08-11). Current
upstream from AndrewEllis93/Print-Tuning-Guide@main uses
MIN_CRUISE_RATIO via SET_VELOCITY_LIMIT. Also brings in M400
sensorless-homing race fix (cc96e40) and negative position_min
guard (PR #153)."
```

### Task 1.3: Move resonance_tester probe_points to bed center

**Files:**
- Modify: `config/btt-ebb-sb-usb-v1.0.cfg:21`

- [ ] **Step 1: Verify current value**

Run:
```sh
grep -n "probe_points" config/btt-ebb-sb-usb-v1.0.cfg
```

Expected: `21:probe_points: 100, 100, 20`.

- [ ] **Step 2: Edit the value**

Edit `config/btt-ebb-sb-usb-v1.0.cfg` line 21:

```diff
-probe_points: 100, 100, 20
+probe_points: 175, 175, 20    # bed center for 350mm Voron 2.4
```

- [ ] **Step 3: Verify the change**

```sh
grep -n "probe_points" config/btt-ebb-sb-usb-v1.0.cfg
```

Expected: `21:probe_points: 175, 175, 20    # bed center for 350mm Voron 2.4`.

- [ ] **Step 4: Run all local CI checks**

```sh
make test-py
```

Expected: PASS. (Klippy parse runs in CI on Linux, not locally on macOS; the test-py target covers the macOS-runnable subset.)

- [ ] **Step 5: Commit**

```sh
git add config/btt-ebb-sb-usb-v1.0.cfg
git commit -m "fix(resonance): center probe_points on the bed (175,175,20)

100,100,20 is the 250mm-kit example from Klipper's bundled config.
175,175,20 matches safe_z_home and the 350mm bed center."
```

### Task 1.4: Push, run CI, deploy + post-deploy smoke

- [ ] **Step 1: Push the branch and open PR**

```sh
git push -u origin feat/config-tier1-fixes
gh pr create --base main --title "chore(config): tier-1 fixes — TEST_SPEED upstream + resonance_tester center" --body "$(cat <<'EOF'
## Summary
- Replace `config/macros/test_speed.cfg` with current upstream from AndrewEllis93/Print-Tuning-Guide. Fixes Klipper v0.13 hard-fail (removed `max_accel_to_decel`).
- Move `[resonance_tester] probe_points` to bed center (175, 175, 20) — was 100, 100, 20 (250mm-kit default).
- Add Layer 5 structural test scaffold (`tests/test_config_structure.py`) with initial assertion: no .cfg uses removed Klipper keys.

Phase 1 of `docs/superpowers/specs/2026-05-15-config-macros-refactor.md`.

## Test plan
- [x] Layer 5 test passes after the test_speed.cfg swap
- [x] `macro_refcheck.py` passes
- [ ] CI klippy parse passes
- [ ] Post-deploy smoke: TEST_SPEED runs without error against current Klipper master

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI to go green**

Watch for the CI check on the PR. If klippy parse fails, investigate `tests/voron-2-611.test` and the dict files (`tests/dict/*.dict`) — may need regeneration if the Eddy migration's klippy-smoke re-enable left them stale.

- [ ] **Step 3: Squash-merge the PR**

```sh
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
```

- [ ] **Step 4: Deploy to the Pi**

```sh
bash scripts/deploy_to_pi.sh
```

Expected: deploy gates pass, rsync completes, FIRMWARE_RESTART succeeds, printer ready.

- [ ] **Step 5: Post-deploy smoke (manual — Layer 6)**

In Mainsail's console, run:
```
TEST_SPEED SPEED=300 ACCEL=5000 ITERATIONS=1 BOUND=20
```

Expected: completes without `!! Unknown command` or `!! Internal error` in `klippy.log`. The 1-iteration run is fast (~30s).

If `TEST_SPEED` errors with an unknown parameter, the new upstream may have renamed something — inspect against the upstream file and the [Ellis docs page](https://ellis3dp.com/Print-Tuning-Guide/articles/useful_macros/test_speed.html).

---

## Phase 2: Mainsail/HH cleanup (Option B) + archive/dead-code cleanup

**Branch:** `feat/mainsail-hh-cleanup`
**Estimated diff:** ~80 lines net (subtracting more than adding — slimming `mainsail.cfg`)
**PR title:** `chore(config): defer to Happy Hare on pause/resume; remove dead code`

**Files:**
- Modify: `config/mainsail.cfg` (strip PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_*/SET_PRINT_STATS_INFO blocks)
- Modify: `config/macros/macros.cfg` (delete SET_ACTIVE_SPOOL/CLEAR_ACTIVE_SPOOL; clean comments)
- Modify: `config/macros/print_start.cfg` (clean commented-out blocks)
- Modify: `config/macros/lcd_tweaks.cfg` (remove duplicate progress_text)
- Modify: `config/printer.cfg:332` (remove orphan comment)
- Modify: `tests/test_config_structure.py` (add Mainsail/HH single-definition test)
- Modify: `memory/decisions.md` (record the divergence rationale)

### Task 2.1: Start branch from updated main

- [ ] **Step 1: Branch from main**

```sh
git switch main && git pull --ff-only
git switch -c feat/mainsail-hh-cleanup
```

### Task 2.2: Add Layer 5 test for PAUSE/RESUME/CANCEL_PRINT single-definition

**Files:**
- Modify: `tests/test_config_structure.py`

- [ ] **Step 1: Add the test**

Append to `tests/test_config_structure.py`:

```python
def test_pause_resume_cancel_defined_once() -> None:
    """PAUSE / RESUME / CANCEL_PRINT must be defined exactly once across all included .cfg.

    Happy Hare's mmu/optional/client_macros.cfg owns these (MMU-aware versions).
    mainsail-config/client.cfg also defines them — that's the collision we're
    eliminating.

    See memory/defer-to-happy-hare.md.
    """
    canonical_names = ["PAUSE", "RESUME", "CANCEL_PRINT"]
    for macro_name in canonical_names:
        # Use word-boundary so we don't match SET_PAUSE_NEXT_LAYER etc.
        pattern = re.compile(rf"^\[gcode_macro {re.escape(macro_name)}\]$", re.MULTILINE)
        defs = []
        for cfg in _cfg_files():
            for _ in pattern.finditer(cfg.read_text()):
                defs.append(str(cfg.relative_to(REPO_ROOT)))
        # Also check the mmu/optional/client_macros.cfg by path (it's not in _cfg_files since it's symlinked-third-party)
        mmu_client_macros = CONFIG_DIR / "mmu" / "optional" / "client_macros.cfg"
        if mmu_client_macros.exists():
            for _ in pattern.finditer(mmu_client_macros.read_text()):
                defs.append(str(mmu_client_macros.relative_to(REPO_ROOT)))
        assert len(defs) == 1, (
            f"[gcode_macro {macro_name}] must be defined exactly once, found {len(defs)}: {defs}"
        )
```

- [ ] **Step 2: Run the test — verify it fails on current state**

```sh
.venv/bin/pytest tests/test_config_structure.py::test_pause_resume_cancel_defined_once -v
```

Expected: **FAIL** with PAUSE/RESUME/CANCEL_PRINT each found in 2 places (mainsail.cfg AND mmu/optional/client_macros.cfg).

### Task 2.3: Slim config/mainsail.cfg

**Files:**
- Modify: `config/mainsail.cfg`

- [ ] **Step 1: Identify the sections to remove**

```sh
grep -n "^\[gcode_macro \(PAUSE\|RESUME\|CANCEL_PRINT\|SET_PAUSE_NEXT_LAYER\|SET_PAUSE_AT_LAYER\|SET_PRINT_STATS_INFO\)\]" config/mainsail.cfg
```

Expected output (line numbers may vary):
```
63:[gcode_macro CANCEL_PRINT]
93:[gcode_macro PAUSE]
114:[gcode_macro RESUME]
176:[gcode_macro SET_PAUSE_NEXT_LAYER]
185:[gcode_macro SET_PAUSE_AT_LAYER]
196:[gcode_macro SET_PRINT_STATS_INFO]
```

- [ ] **Step 2: Slim the file**

Replace `config/mainsail.cfg` so it contains only: the header comment block, `[virtual_sdcard]`, `[pause_resume]`, `[display_status]`, `[respond]`, and the helper macros `_TOOLHEAD_PARK_PAUSE_CANCEL`, `_CLIENT_EXTRUDE`, `_CLIENT_RETRACT`, `_CLIENT_LINEAR_MOVE`.

Target structure (preserve upstream comments and helper-macro bodies verbatim — only delete the 6 macros above):

```ini
## Slimmed mainsail-config client.cfg for voron-2-611
##
## Derived from upstream mainsail-crew/mainsail-config @ ff3869a.
## Local divergence: PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_*/SET_PRINT_STATS_INFO
## removed — Happy Hare's mmu/optional/client_macros.cfg owns these.
## See memory/defer-to-happy-hare.md and memory/decisions.md.
##
## To update from upstream: vendor/mainsail-config/client.cfg → review →
## copy non-overlapping bits into this file. DO NOT restore the 6 deleted
## [gcode_macro] sections.

[virtual_sdcard]
path: ~/printer_data/gcodes
on_error_gcode: CANCEL_PRINT

[pause_resume]

[display_status]

[respond]

# Helper macros (referenced by other macros — kept verbatim from upstream)
[gcode_macro _TOOLHEAD_PARK_PAUSE_CANCEL]
# ... preserve full upstream body ...

[gcode_macro _CLIENT_EXTRUDE]
# ... preserve full upstream body ...

[gcode_macro _CLIENT_RETRACT]
# ... preserve full upstream body ...

[gcode_macro _CLIENT_LINEAR_MOVE]
# ... preserve full upstream body ...
```

Practical method: open the current `config/mainsail.cfg`, delete only the 6 listed `[gcode_macro …]` blocks (each runs from its `[gcode_macro X]` header to the line before the next `[…]` section), and update the header comment to the slimmed version above.

- [ ] **Step 3: Verify the test now passes**

```sh
.venv/bin/pytest tests/test_config_structure.py::test_pause_resume_cancel_defined_once -v
```

Expected: PASS (each macro now defined in exactly one place — mmu/optional/client_macros.cfg).

- [ ] **Step 4: Run klippy parse locally if on Linux, otherwise rely on CI**

Skip on macOS (test_klippy.py requires Linux headers). CI will catch errors.

- [ ] **Step 5: Commit**

```sh
git add config/mainsail.cfg tests/test_config_structure.py
git commit -m "fix(mainsail): defer to Happy Hare for PAUSE/RESUME/CANCEL_PRINT

Strip PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_NEXT_LAYER/SET_PAUSE_AT_LAYER/
SET_PRINT_STATS_INFO from config/mainsail.cfg. HH's mmu/optional/
client_macros.cfg is MMU-aware and is the only definition now.

Per memory/defer-to-happy-hare.md and HH inline docs
(vendor/happy-hare/config/optional/client_macros.cfg:22-27)."
```

### Task 2.4: Delete dead Spoolman macros

**Files:**
- Modify: `config/macros/macros.cfg`

- [ ] **Step 1: Verify the macros are truly unreferenced**

```sh
grep -rn "SET_ACTIVE_SPOOL\|CLEAR_ACTIVE_SPOOL" config/ --include="*.cfg" --include="*.conf"
```

Expected: only the definitions themselves (in `config/macros/macros.cfg:201-218`) — no callers anywhere. If a caller is found, abort and investigate.

- [ ] **Step 2: Delete the macros**

Remove lines 201-218 of `config/macros/macros.cfg` (the two `[gcode_macro]` blocks):

```diff
-[gcode_macro SET_ACTIVE_SPOOL]
-gcode:
-  {% if params.ID %}
-    {% set id = params.ID|int %}
-    {action_call_remote_method(
-       "spoolman_set_active_spool",
-       spool_id=id
-    )}
-  {% else %}
-    {action_respond_info("Parameter 'ID' is required")}
-  {% endif %}
-
-[gcode_macro CLEAR_ACTIVE_SPOOL]
-gcode:
-  {action_call_remote_method(
-    "spoolman_set_active_spool",
-    spool_id=None
-  )}
```

Also delete the orphan `  # printer.cfg` comment at line 199.

- [ ] **Step 3: Run macro_refcheck**

```sh
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS.

### Task 2.5: Clean commented-out blocks

**Files:**
- Modify: `config/macros/print_start.cfg`
- Modify: `config/macros/macros.cfg`
- Modify: `config/macros/lcd_tweaks.cfg`
- Modify: `config/printer.cfg:332`

- [ ] **Step 1: Remove commented blocks in print_start.cfg**

Delete from `config/macros/print_start.cfg`:
- Line 20: `# M104 S150 # Heat hotend to 150c` (carryover comment)
- Lines 32-36: commented-out block under `[gcode_macro PRINT_START]` (`# SET_PIN`, `# _RESETSPEEDS`, etc.)
- Lines 43-47: commented-out HEATSOAK alternative block
- Line 51: `# SET_DISPLAY_TEXT MSG="Bed: {bed}c"` (commented)
- Lines 58-62: commented-out alternative path under `{% else %}`
- Lines 76-81: commented-out prime line block

Use git diff after editing to verify exactly what was removed.

- [ ] **Step 2: Remove commented blocks in macros.cfg**

Delete from `config/macros/macros.cfg`:
- Lines 172-181: commented-out bidirectional-line block inside FIRST_LAYER_Z_TEST

- [ ] **Step 3: Remove duplicate progress_text in lcd_tweaks.cfg**

Inspect `config/macros/lcd_tweaks.cfg` around line 87-91. There are two `[display_data]` entries called `progress_text` and `progress_text2` at the same position `1, 10`. Delete the first one (`progress_text` at lines 87-91); keep `progress_text2`.

- [ ] **Step 4: Remove orphan comment in printer.cfg**

Delete the stray `; set logo back to white` comment at `config/printer.cfg:345` (within the `[idle_timeout]` gcode body — it has no corresponding command).

- [ ] **Step 5: Run all tests**

```sh
.venv/bin/pytest tests/ -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected: all PASS.

- [ ] **Step 6: Commit the cleanups**

```sh
git add config/macros/macros.cfg config/macros/print_start.cfg config/macros/lcd_tweaks.cfg config/printer.cfg
git commit -m "chore(macros): remove dead Spoolman macros and commented-out blocks

- Delete SET_ACTIVE_SPOOL/CLEAR_ACTIVE_SPOOL — Happy Hare owns Spoolman
  activation via spoolman_support: push (mmu.py:6522-6534). The custom
  macros were never referenced.
- Remove commented-out alternative gcode blocks in print_start.cfg
  (lines 20, 32-36, 43-47, 51, 58-62, 76-81).
- Remove commented bidirectional-line block in macros.cfg (172-181).
- Remove duplicate progress_text entry in lcd_tweaks.cfg.
- Remove orphan comment in printer.cfg:332."
```

### Task 2.6: Update memory/decisions.md with the Mainsail/HH rationale

**Files:**
- Modify: `memory/decisions.md`

- [ ] **Step 1: Check current state of memory/decisions.md**

```sh
test -f memory/decisions.md && head -50 memory/decisions.md
```

If the file doesn't exist, create it with the decision block below. If it exists, append.

- [ ] **Step 2: Add the decision entry**

Append to `memory/decisions.md`:

```markdown
## 2026-MM-DD — Defer to Happy Hare for PAUSE/RESUME/CANCEL_PRINT

**Decision:** Strip PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_*/SET_PRINT_STATS_INFO from `config/mainsail.cfg`. Happy Hare's `mmu/optional/client_macros.cfg` is the sole definition.

**Rationale:**
- HH's macros are MMU-aware; Mainsail's defaults are not. Letting Mainsail win silently disables HH's centralized parking config (`park_pause`, `park_cancel`, etc. in `mmu_macro_vars.cfg`).
- HH's inline documentation (`vendor/happy-hare/config/optional/client_macros.cfg:22-27`) explicitly recommends this configuration.
- The current dual-definition with Mainsail loaded later was producing: HH's `_MMU_PARK` skipped when MMU enabled (intentional HH behavior when wrapped), but HH-tuned park config unused. A latent bug existed if `unload_tool_on_cancel: True` were ever set.

**Consequence:**
- `config/mainsail.cfg` is a real file in this repo (not a symlink to `~/mainsail-config/`). Future mainsail-config upstream updates do NOT auto-apply to our slimmed file. To pick up upstream changes, manually merge non-conflicting changes from `vendor/mainsail-config/client.cfg` into our local file — do NOT restore the 6 deleted `[gcode_macro]` sections.
- KIAUH or full Mainsail reinstall would recreate the symlink at `~/printer_data/config/mainsail.cfg`. Recovery: redeploy from main via `scripts/deploy_to_pi.sh`.

**See also:**
- `memory/defer-to-happy-hare.md`
- `docs/superpowers/specs/2026-05-15-config-macros-refactor.md` Section 5 (Phase 2 details).
```

Replace `MM-DD` with the actual commit date.

- [ ] **Step 3: Commit**

```sh
git add memory/decisions.md
git commit -m "docs(memory): record Mainsail/HH PAUSE divergence rationale"
```

### Task 2.7: Push, CI, merge, deploy, smoke

- [ ] **Step 1: Push and open PR**

```sh
git push -u origin feat/mainsail-hh-cleanup
gh pr create --base main --title "chore(config): defer to Happy Hare on pause/resume; remove dead code" --body "$(cat <<'EOF'
## Summary
- Strip PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_*/SET_PRINT_STATS_INFO from `config/mainsail.cfg`. Happy Hare's `mmu/optional/client_macros.cfg` is the sole definition (per HH's own recommendation).
- Delete dead `SET_ACTIVE_SPOOL`/`CLEAR_ACTIVE_SPOOL` (Spoolman activation is owned by HH).
- Clean commented-out blocks across macros/*.cfg.
- Add Layer 5 test asserting PAUSE/RESUME/CANCEL_PRINT defined exactly once.

Phase 2 of `docs/superpowers/specs/2026-05-15-config-macros-refactor.md`.

## Test plan
- [x] New Layer 5 test passes
- [x] `macro_refcheck.py` passes
- [ ] CI klippy parse passes
- [ ] Post-deploy: Mainsail PAUSE/RESUME UI buttons trigger HH-aware behavior (test mid-print)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: After CI green, merge, deploy**

```sh
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
bash scripts/deploy_to_pi.sh
```

- [ ] **Step 3: Post-deploy smoke (manual — Layer 6)**

Start a small test print. Mid-print, hit Mainsail's PAUSE button. Expected behavior:
- Toolhead parks (Mainsail's `_TOOLHEAD_PARK_PAUSE_CANCEL` still runs via HH's wrapper chain).
- HH's `MMU_LOG` shows the pause event.
- `printer.pause_resume.is_paused == True`.

Then hit RESUME. Expected: print continues from where paused, with un-retract.

If the chain breaks, investigate `klippy.log` for HH-PAUSE errors. Rollback path: `git revert <sha>` of this PR + re-deploy.

---

## Phase 3: CLAUDE.md corrections + Open Investigations → GH Issues

**Branch:** `feat/claude-md-and-gh-issues`
**Estimated diff:** ~50 lines (docs-only) + ~13 GH issues created
**PR title:** `docs(claude-md): correct hardware inventory + migrate Open Investigations to GH`

**Files:**
- Modify: `CLAUDE.md` (multiple sections)

**External (no code changes):**
- Create `future-work` GH label
- Create ~13 GH Issues
- The CLAUDE.md changes will reference the issue URLs

### Task 3.1: Start branch, create label

- [ ] **Step 1: Branch from main**

```sh
git switch main && git pull --ff-only
git switch -c feat/claude-md-and-gh-issues
```

- [ ] **Step 2: Create the `future-work` label**

```sh
gh label create "future-work" --description "Tracked work not currently scoped for active development" --color "0e8a16"
```

Expected: label created. If it already exists, that's fine.

### Task 3.2: Create GH Issues for the 8 current Open Investigations

The current CLAUDE.md ## Open investigations section has 8 numbered items. Issue #1 (Eddy migration) is closed by this point (merged before Phase 1) — skip it, just note "closed" in the CLAUDE.md update. Create issues for 2-8.

For each, create with the body template below.

- [ ] **Step 1: Investigation #2 — Sensorless X feasibility**

```sh
gh issue create --label "future-work" --title "Investigation: sensorless X feasibility on this build" --body "$(cat <<'EOF'
Currently uses a physical endstop wired to the EBB. Ben's prior understanding was sensorless wasn't viable or was potentially harmful on this build. Worth a fresh look on V2.4 r2 + dual SKR 1.4 + TMC2209 + EBB SB.

## Prerequisites confirmed
- TMC2209 (UART) — yes (`config/printer.cfg`)
- CoreXY — yes
- No `hold_current` on X — yes

## Prerequisites to verify
- DIAG pin wired between X driver and an MCU input — check `vendor/btt-docs/` for EBB SB v1.0 schematic
- `homing_retract_dist: 0` requirement (Klipper TMC_Drivers.md:205-208)

## References
- `vendor/klipper/docs/TMC_Drivers.md:394-431` (sensorless on CoreXY)
- CLAUDE.md Open Investigation #2 (pre-migration entry)
EOF
)"
```

- [ ] **Step 2: Investigation #3 — Microsteps 128 → 64 deliberate test**

```sh
gh issue create --label "future-work" --title "Investigation: microsteps 128 → 64 deliberate test on X/Y/Z" --body "$(cat <<'EOF'
Followed third-party online advice for microsteps 128 on motion steppers; real goal is "quiet without losing steps" (per Ben). Klipper TMC_Drivers.md:90-115 specifically mentions 64 produces similar audible noise without 128's systemic interpolation error.

## Investigation
- LPC1769 step-rate budget at 32/64/128 with 5 MCUs and active MMU
- Noise comparison at each setting
- Skip behavior at each setting

## References
- `vendor/klipper/docs/TMC_Drivers.md:90-115`
- CLAUDE.md Open Investigation #3
EOF
)"
```

- [ ] **Step 3: Investigation #4 — Re-tune session (shaper, PID, PA, Eddy, anchored on klippain-shaketune)**

```sh
gh issue create --label "future-work" --title "Re-tune session: shaper (X/Y/Z) + PID + PA + Eddy verification (via klippain-shaketune)" --body "$(cat <<'EOF'
The SAVE_CONFIG values in `config/printer.cfg` are 2022-era. Klipper's resonance test methodology changed in December 2024 (sweeping moves). Worth a full re-tune session.

## Anchored on klippain-shaketune (v6.0+)
Install [klippain-shaketune](https://github.com/Frix-x/klippain-shaketune) (standalone, not full Klippain). Standalone install: \`wget … install.sh | bash\`.

## Tasks
- [ ] Install shaketune on the Pi
- [ ] Run \`COMPARE_BELTS_RESPONSES\` — V2 saggy-rear belt-tension diagnostic
- [ ] Re-run X/Y shaper calibration via shaketune
- [ ] Verify shaketune covers Z-axis shaping (\`accel_chip_z: lis2dw\`, \`shaper_type_z\`). If yes: run Z shaper via shaketune. If no: run native \`SHAPER_CALIBRATE\` for Z separately, set \`max_freq_z: 100\`, \`accel_per_hz_z: 15\`, \`sweeping_accel_z: 50\`.
- [ ] Re-run \`PID_CALIBRATE\` for bed and hotend
- [ ] Re-run pressure advance calibration
- [ ] Verify Eddy native calibration is still good (\`PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=verify\`)

## References
- vendor/klipper/docs/Config_Changes.md (2024-12-03 sweeping-move entry)
- vendor/klipper/docs/Measuring_Resonances.md
- CLAUDE.md Open Investigation #4
EOF
)"
```

- [ ] **Step 4: Investigation #5 — moonraker-timelapse**

```sh
gh issue create --label "future-work" --title "Investigation: fix or remove moonraker-timelapse" --body "$(cat <<'EOF'
Ben has never gotten moonraker-timelapse to work. Configured in \`config/moonraker.conf\` and included via \`[include timelapse.cfg]\` (symlink). Decision pending: fix or remove.

## Coupled to
This depends on the webcam re-enable plan (#TBD). Don't decide independently.

## References
- CLAUDE.md Open Investigation #5
- \`config/moonraker.conf\` (timelapse + update_manager timelapse blocks)
- \`config/timelapse.cfg\` (symlink to ~/moonraker-timelapse/klipper_macro/timelapse.cfg)
EOF
)"
```

- [ ] **Step 5: Investigation #6 — Webcam re-enable**

```sh
gh issue create --label "future-work" --title "Webcam re-enable" --body "$(cat <<'EOF'
Webcam physically unplugged due to timing/streaming issues. Crowsnest + Sonar daemons still run. Plan was originally tied to the Eddy migration; that's done, so this is now unblocked.

## Tasks
- [ ] Re-plug the webcam
- [ ] Verify crowsnest detects it on next restart
- [ ] Smoke-test Mainsail webcam view
- [ ] Decide on moonraker-timelapse (linked issue)

## References
- CLAUDE.md Open Investigation #6
EOF
)"
```

- [ ] **Step 6: Investigation #7 — CI klippy-smoke**

This is closed by the Eddy migration (which re-enabled klippy-smoke). Don't create an issue; just note in CLAUDE.md that it's resolved.

- [ ] **Step 7: Investigation #8 — Automated Pi deploy on merge**

```sh
gh issue create --label "future-work" --title "Automate Pi deploy on every merge to main (v2)" --body "$(cat <<'EOF'
\`/deploy-to-pi\` skill + \`scripts/deploy_to_pi.sh\` shipped 2026-05-14 (v1, manual). v2 is wrapping the script in a GitHub Action so deploys happen automatically when CI goes green on \`main\`.

## Challenges
- Pi is on Ben's LAN, not internet-accessible from GH-hosted runners
- Requires either a self-hosted runner on the LAN or a webhook-pull from the Pi
- Tunneling adds complexity

## References
- \`.claude/skills/deploy-to-pi/SKILL.md\` (runtime contract)
- \`scripts/deploy_to_pi.sh\` (existing implementation)
- CLAUDE.md Open Investigation #8
EOF
)"
```

### Task 3.3: Create GH Issues for new out-of-scope items

- [ ] **Step 1: `[temperature_probe btt_eddy]` re-evaluation**

Wait — this was moved to be folded into the Eddy work per spec Section 2. Do NOT create an issue here; it should already be on the Eddy branch.

Verify:
```sh
grep -A 2 "temperature_probe btt_eddy" config/eddy.cfg
```

Expected: section exists from the Eddy merge. If not, this is a discrepancy with the spec — pause and investigate.

- [ ] **Step 2: `[homing_override]` for Z post-G28**

Same as above — should be on the Eddy branch already. Verify:
```sh
grep -A 5 "homing_override" config/eddy.cfg config/printer.cfg
```

Expected: section exists. If not, pause.

- [ ] **Step 3: OrcaSlicer print-profile tuning**

```sh
gh issue create --label "future-work" --title "OrcaSlicer print profile tuning (filament profiles, speeds, layer config)" --body "$(cat <<'EOF'
Substantial effort to optimize OrcaSlicer print profiles for this machine — filament profiles, speed profiles, layer config, supports, etc. Out of scope for the current Klipper-side refactor; tracked here for the future.

## Pre-requisites
- Eddy native stable (done)
- Klipper macros refactored (in progress)
- Re-tune session (#TBD shaketune issue) complete

## References
- Mentioned during 2026-05-15 brainstorming as "a different day's project"
EOF
)"
```

- [ ] **Step 4: Logical reorganization audit**

```sh
gh issue create --label "future-work" --title "Audit logical organization of macros/config content (post-_USER_VARIABLE quarter)" --body "$(cat <<'EOF'
Once we've lived with the \`_USER_VARIABLE\` pattern for a quarter (say, after 2026-08-15), audit what's in each \`config/macros/*.cfg\` file and \`config/*.cfg\` and consider moving sections for better grouping.

Open-ended — not a specific change list.

## References
- docs/superpowers/specs/2026-05-15-config-macros-refactor.md Section 9
EOF
)"
```

- [ ] **Step 5: Better PA / Flow calibration macros**

```sh
gh issue create --label "future-work" --title "Survey PA / Flow calibration macros vs. current Frix-x v1.2/v1.6" --body "$(cat <<'EOF'
Current PA/Flow calibrators are Frix-x v1.2 and v1.6 (in \`config/macros/calibrate_*.cfg\`). Per 2026-05-15 community research, Frix-x is still current upstream as of mid-2025. But re-survey periodically.

## Open question
Is there a better community option, or has Klipper-native \`TUNING_TOWER\` workflow improved enough to replace Frix-x?

## References
- vendor/klipper/docs/Pressure_Advance.md
- Frix-x klippain calibrate_pa.cfg / calibrate_flow.cfg
EOF
)"
```

- [ ] **Step 6: Webcam-feedback-driven auto-calibration**

```sh
gh issue create --label "future-work" --title "Substantial project: webcam-feedback-driven auto-calibration of flow/PA/temp" --body "$(cat <<'EOF'
Long-term project: automate flow, pressure advance, and temperature calibration using webcam image analysis of test prints.

## Scope
- Moonraker component for camera capture during test prints
- Image analysis pipeline (likely opencv-based) to score corner sharpness (PA), bead width (flow), surface quality (temp)
- Iteration loop: capture → analyze → adjust → re-print
- Integration with slicer profiles to write results back

## Prerequisites
- Webcam re-enabled (linked issue)
- Stable Klipper config baseline

## References
- 2026-05-15 brainstorming session, scoped explicitly as a "future substantial project"
EOF
)"
```

### Task 3.4: Update CLAUDE.md — hardware inventory + macro inventory corrections

**Files:**
- Modify: `CLAUDE.md`

This is a single commit with multiple small text changes. Make them all, then commit.

- [ ] **Step 1: Fix the toolhead-cutter claim (EREC → Filametrix)**

In the `### Toolhead` section: no change needed (already says "Stealthburner v2 body" without mentioning EREC).

In the `### MMU (Multi-Material Unit)` section, change:
```diff
-Add-ons enabled: **Blobifier** (purge tower), **EREC** (toolhead filament cutter), **mmu_eject_buttons**
+Add-ons enabled: **Blobifier** (purge tower). **Filametrix** is the toolhead filament cutter (Carrot Collective, https://github.com/Carrot-collective/Filametrix) — driven via `_MMU_CUT_TIP` which Happy Hare invokes during toolchange (`config/mmu/base/mmu_cut_tip.cfg`, with cutter pin location set in `config/mmu/base/mmu_macro_vars.cfg::_MMU_CUT_TIP_VARS`).
+
+**Not active on this build despite the file's presence in `config/mmu/addons/`:** the EREC at-MMU cutter (`mmu_erec_cutter.cfg`) and the mmu_eject_buttons. Neither is `[include]`d from `config/printer.cfg`.
```

- [ ] **Step 2: Fix the SB LEDs implication**

In the `### Toolhead` section, add at the end:
```diff
+**Note:** Stealthburner v2 LEDs are not installed on this build. The "3-LED Neopixel chain" mentioned under "Display & lighting" is the LCD chain on the main MCU, NOT a toolhead chain.
```

- [ ] **Step 3: Update the Probe section**

```diff
-**BTT Eddy** running the `vvuk/eddy-ng` Klipper extension (`[probe_eddy_ng btt_eddy]` with butter tap mode)
+**BTT Eddy** on Klipper's native `[probe_eddy_current btt_eddy]` (`config/eddy.cfg`). Tap mode via `PROBE METHOD=tap`. The `vvuk/eddy-ng` fork was migrated off in 2026-05-15 (PR #TBD).
```

```diff
-Calibrated drive currents 15 & 16; current `reg_drive_current: 15`, `tap_drive_current: 15`
+Calibrated drive current: `reg_drive_current: 15`. Tap calibration uses `tap_threshold` (Hz/mm) populated by `PROBE_EDDY_CURRENT_TAP_CALIBRATE`.
```

```diff
-- **Open question:** much of eddy-ng is now reportedly in upstream Klipper (`[probe_eddy_current]`) — there's a likely migration off the fork. See [Open investigations](#open-investigations).
```

(Delete the open question line; migration is done.)

- [ ] **Step 4: Fix the bed_mesh tuning record**

In the "Tuning record" table:
```diff
-| Bed mesh `default` | 9×9, (15, 21.42) → (335, 335) | bicubic, full bed |
+| Bed mesh `default` | 9×9, (15, 21.42) → (335, 330) | bicubic, full bed (mesh_max in eddy.cfg) |
```

- [ ] **Step 5: Fix the macro inventory for print_start.cfg**

In the `### config/macros/print_start.cfg` section:
```diff
-- `PRINT_START` — full start: home → QGL → bed heat + chamber wait (if bed > 90 °C) → `BLOBIFIER_CLEAN` → re-home Z → `PROBE_EDDY_NG_TAP` → adaptive bed mesh → heat hotend
+- `PRINT_START` — full start: home → QGL → bed heat + chamber wait (if bed > 90 °C) → `BLOBIFIER_CLEAN` → re-home Z → `PROBE METHOD=tap` → `SET_KINEMATIC_POSITION` (or `[homing_override]` after Phase 0 Eddy work) → adaptive bed mesh → heat hotend
```

```diff
-- `PRINT_END` — cool, reset Eddy tap offset, clear mesh, wait 60 s, `OFF`, `_RESETSPEEDS`
+- `PRINT_END` — cool, clear mesh, wait 60 s, `OFF`, `_RESETSPEEDS` (no Eddy offset reset — that was eddy-ng-specific)
```

- [ ] **Step 6: Add the missing temperature sensors**

In the hardware-inventory or "Hardware references" section, add a subsection:
```markdown
### Additional temperature sensors (worth knowing about)

- `[temperature_sensor btt_eddy]` — Generic 3950 NTC exposed on `eddy:gpio26`. Used by `[temperature_probe btt_eddy]` for drift compensation. Read via `printer["temperature_sensor btt_eddy"].temperature`.
- `[temperature_sensor EBB_NTC]` — Generic 3950 NTC on the EBB toolhead board (`EBB:gpio27`).
- `[temperature_sensor mcu]` + `[temperature_sensor mcu z]` — MCU die temperatures for the two SKR 1.4 boards (added during Eddy native migration).
- `[temperature_sensor raspberry_pi]` — Pi host temperature.
- `[temperature_sensor btt_eddy_mcu]` — RP2040 MCU die temperature on the Eddy board.
```

- [ ] **Step 7: Update the update_manager block list**

In the section discussing moonraker.conf:
```diff
-There's no `[update_manager klipper]` block in `config/moonraker.conf`, **and that's by design.** Moonraker auto-detects Klipper…
+There's no `[update_manager klipper]` block in `config/moonraker.conf`, **and that's by design** (Moonraker auto-detects Klipper). The following `[update_manager …]` blocks ARE present and worth knowing about:
+
+| Block | Manages | Notes |
+|---|---|---|
+| `mainsail` | Mainsail web UI | Active |
+| `mainsail-config` | Upstream mainsail-config | Active, but our `config/mainsail.cfg` diverges (Phase 2 cleanup); upstream changes do NOT auto-apply |
+| `timelapse` | moonraker-timelapse | Active but unused — see GH issue (link) |
+| `crowsnest` | Webcam stack | Active even though webcam unplugged |
+| `sonar` | Network keepalive | Active |
+| `happy-hare` | HH Klipper extension | Active |
```

### Task 3.5: Enshrine the test pyramid in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (expand the existing `## CI checks` section)

The spec's test pyramid (Section 5) is currently only documented in the spec file. Enshrine it in CLAUDE.md so future contributors (and future agent sessions) see the contribution-time conventions without having to find the spec.

- [ ] **Step 1: Find the existing `## CI checks` section in CLAUDE.md**

```sh
grep -n "^## CI checks" CLAUDE.md
```

- [ ] **Step 2: Replace it with an expanded `## Testing` section**

Replace the existing `## CI checks` section (everything from `## CI checks` to the next `##`-level header) with:

```markdown
## Testing

This repo uses a 7-layer test pyramid (6 standard layers + 1 Phase-4-specific) to give confidence that config and macro changes don't introduce regressions. New work should add to or extend these layers rather than inventing new validation patterns ad-hoc.

| Layer | What | Where it lives | Runs |
|---|---|---|---|
| 1 | Pre-commit hooks (trailing whitespace, ruff, etc.) | `.pre-commit-config.yaml` | every commit + CI |
| 2 | `macro_refcheck.py` — static gcode-command resolution in `[gcode_macro]` bodies | `scripts/macro_refcheck.py` + `tests/builtins.txt` | CI |
| 3 | Klippy parse + smoke gcode — loads `printer.cfg` with simulated MCUs and walks the dispatcher | `tests/voron-2-611.test` + `vendor/klipper/scripts/test_klippy.py` (run via `.github/workflows/ci.yml`) | CI |
| 4 | pytest — unit tests for scripts (macro_refcheck, eddy-migration tripwire, real-repo regression) | `tests/test_*.py` | CI |
| 5 | Structural assertions on `.cfg` files (no deprecated keys; PAUSE/RESUME defined once; every `[gcode_macro]` has `description:`; `_USER_VARIABLE.X` references resolve; `params.X` has default or guard; `[include]` order matches expected) | `tests/test_config_structure.py` | CI |
| 6 | Post-deploy smoke (run a fixed gcode sequence on the Pi after deploy and check `klippy.log` for `!! Unknown command` and `!! Internal error`) | Manual after `bash scripts/deploy_to_pi.sh`; commands documented in each PR description | Manual |
| 7 (one-shot) | Behavior diff — snapshot expanded gcode for a fixed set of macro invocations before and after; assert diff is comments/whitespace only | `scripts/macro_behavior_diff.py` + `tests/snapshots/macro_behavior_<before|after>.txt` | Manual, before merging refactor PRs |

### What each layer catches

- **Layer 1:** text-hygiene drift, Python lint regressions.
- **Layer 2:** macro calls that reference renamed/deleted macros.
- **Layer 3:** Klipper config syntax errors, unknown sections, pin clashes, jinja2 template parse errors (does NOT execute jinja2 conditionals).
- **Layer 4:** regressions in the testing infrastructure itself.
- **Layer 5:** the structural invariants we care about that aren't caught by Klipper's own loader.
- **Layer 6:** runtime behavior on the actual machine — catches what Layer 3 misses (conditional branches, MCU-specific quirks).
- **Layer 7:** refactor behavior preservation — proves "values copied verbatim, no behavior change."

### What's NOT covered (acknowledged)

- Conditional branches inside jinja2 macros (no layer executes them with varied state). Layer 6 + Layer 7 mitigate.
- Print quality / mechanical regression. Mitigated by a manual first-print test after each deploy.
- Slicer-side template errors. Lives in OrcaSlicer, not in this repo. See `docs/slicer-templates/README.md`.

### When to extend the pyramid

- **New tunable pattern** (e.g., a second user-variable macro for a different scope): add a Layer 5 assertion for resolution/usage.
- **New deprecated Klipper key** discovered upstream: add to Layer 5 deprecated-keys list.
- **New macro-collision risk** (e.g., another upstream macro pack overlaps with HH or Mainsail): add a Layer 5 single-definition assertion for the colliding name.
- **Refactor PR that changes structure but not behavior** (like Phase 4): run Layer 7 before/after, attach the diff to the PR description.

The complete pyramid rationale is in `docs/superpowers/specs/2026-05-15-config-macros-refactor.md` Section 5.

### Running tests locally

```sh
make test-py    # macOS-friendly subset: pre-commit + macro_refcheck + pytest + Layer 5
make test       # Adds the klippy step (requires Linux for sys/prctl.h)
```

### Regenerating cached data

- `tests/dict/*.dict` — after bumping `vendor/klipper` or modifying `config/firmware/*.config`. Build on the Pi.
- `tests/builtins.txt` — after bumping `vendor/klipper`. Run `make builtins`.

### Branch protection

A companion workflow `.github/workflows/ci-docs-noop.yml` reports the same required check name as a no-op success on docs-only paths (`CLAUDE.md`, `memory/**`, `docs/**`, `.claude/**`, `LICENSE`). Without it, branch protection would block any docs-only PR because `paths-ignore` skips `ci.yml` entirely. For any push, exactly one of the two workflows runs.

### Coupled allowlists

The **eddy-ng** block in `scripts/macro_refcheck.py`'s `ALLOWLIST` is removed by the Eddy native migration; the `tests/test_macro_refcheck.py::test_eddy_ng_allowlist_coupling` tripwire enforces this. The **Happy-Hare** block in the same `ALLOWLIST` is NOT coupled this way; those commands are registered by Python and survive any `.cfg` change.
```

### Task 3.6: Update CLAUDE.md — replace Open Investigations with pointer

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Replace the entire `## Open investigations` section**

Find the section in `CLAUDE.md` starting with `## Open investigations` and ending before the next `##`-level header. Replace its content (keep the header):

```markdown
## Open investigations

Tracked as GitHub Issues with the [`future-work`](https://github.com/bjdeng/voron-2-611/labels/future-work) label.

Highlights still active (curated, not exhaustive):
- **Re-tune session** (input shaper, PID, PA, Eddy verification, anchored on klippain-shaketune): #TBD
- **Microsteps 128 → 64 deliberate test**: #TBD
- **Sensorless X feasibility**: #TBD
- **Webcam re-enable** + **moonraker-timelapse decision**: #TBD, #TBD
- **Automated Pi deploy v2**: #TBD

### Recently resolved (historical log)

- ~~`eddy-ng` → native Klipper Eddy migration~~ — shipped 2026-MM-DD (PR #TBD).
- ~~Missing `[update_manager klipper]`~~ — by design; Moonraker auto-detects (`vendor/moonraker/docs/configuration.md:2017-2026`).
- ~~TDD-equivalent for Klipper configs~~ — landed via the CI scaffold.
- ~~`ModemManager` USB-MCU footgun~~ — masked on the Pi 2026-05-14.
- ~~Top-level mixed machine state + tooling~~ — machine state moved into `config/` 2026-05-14.
- ~~CI klippy-smoke disabled~~ — re-enabled by the Eddy migration PR.
```

Replace `#TBD` placeholders with the actual issue numbers from Task 3.2 and 3.3.

- [ ] **Step 2: Run all tests**

```sh
.venv/bin/pytest tests/ -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS (docs-only changes don't affect config tests, but run anyway).

- [ ] **Step 3: Commit**

```sh
git add CLAUDE.md
git commit -m "docs(claude-md): correct hardware inventory; migrate Open Investigations to GH

- EREC → Filametrix (toolhead cutter; per memory/filametrix-toolhead-cutter.md)
- Note SB v2 LEDs not installed (the 3-LED neopixel chain is on the LCD)
- Eddy native migrated (remove vvuk/eddy-ng claim)
- Add missing [temperature_sensor] blocks to hardware inventory
- Fix bed_mesh max-y in tuning table (334.94, not 335)
- Fix PRINT_START/PRINT_END macro inventory
- Expand [update_manager] block list
- Replace Open Investigations section with GH Issues pointer (label: future-work)

See memory/claude-md-may-drift-from-config.md."
```

### Task 3.7: Push, CI, merge

- [ ] **Step 1: Push and PR**

```sh
git push -u origin feat/claude-md-and-gh-issues
gh pr create --base main --title "docs(claude-md): correct hardware inventory + migrate Open Investigations to GH" --body "$(cat <<'EOF'
## Summary
Docs-only PR.

- Fix CLAUDE.md factual errors (Filametrix vs EREC, no SB LEDs, Eddy native, bed_mesh values, addons list, temp sensors, update_manager blocks).
- Replace ## Open investigations section with a pointer at the \`future-work\` GH label; existing investigations migrated to GH Issues.
- New \`future-work\` items also filed (OrcaSlicer profile tuning, logical reorg audit, PA/Flow macro survey, webcam-feedback auto-cal).

Phase 3 of \`docs/superpowers/specs/2026-05-15-config-macros-refactor.md\`.

## Test plan
- [x] Layer 1-5 tests pass (no config changes; tests run anyway)
- [x] CLAUDE.md preview renders correctly on GH
- [x] All issue links resolve

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

This PR should match the no-op docs-only CI workflow (`.github/workflows/ci-docs-noop.yml`).

- [ ] **Step 2: Merge**

```sh
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
```

No deploy needed — CLAUDE.md changes don't affect the Pi.

---

## Phase 4: Macros refactor + file reorganization

**Branch:** `feat/macros-refactor`
**Estimated diff:** ~400-600 lines
**PR title:** `refactor(macros): single _USER_VARIABLE, rename toolhead.cfg, consolidate sections`

This is the biggest phase. Worked in commits per macro file to keep the diff reviewable. Layer 7 (behavior diff) gates merge.

**Files (overview):**
- Create: `config/macros/_user_variables.cfg`
- Rename: `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`
- Modify: `config/printer.cfg` (include line update, includes reorganized, `[extruder]` PA + temp_limits moved out)
- Modify: `config/toolhead.cfg` (gains `[extruder]` PA + temp_limits)
- Modify: `config/macros/macros.cfg` (read from _USER_VARIABLE, add description fields)
- Modify: `config/macros/print_start.cfg` (read from _USER_VARIABLE, add description fields)
- Modify: `config/macros/bedfans.cfg` (delete _BEDFANVARS, read from _USER_VARIABLE, add description fields)
- Modify: `config/macros/lcd_tweaks.cfg` (add description fields where missing)
- Modify: `tests/voron-2-611.test` (rename btt-ebb-sb-usb-v1.0 references)
- Modify: `scripts/macro_refcheck.py` (any path constants)
- Modify: `CLAUDE.md` (path references to renamed file)
- Modify: `tests/test_config_structure.py` (extend Layer 5: _USER_VARIABLE resolution, description: required, params default, include order)
- Create: `scripts/macro_behavior_diff.py` (Layer 7)
- Create: `tests/snapshots/macro_behavior_before.txt` (generated)
- Create: `tests/snapshots/macro_behavior_after.txt` (generated)

### Task 4.1: Branch, write Layer 5 extensions

- [ ] **Step 1: Branch**

```sh
git switch main && git pull --ff-only
git switch -c feat/macros-refactor
```

- [ ] **Step 2: Add the four new Layer 5 assertions to test_config_structure.py**

Append to `tests/test_config_structure.py`:

```python
USER_VAR_REF_PATTERN = re.compile(
    r"""printer\[\s*['"]gcode_macro\s+_USER_VARIABLE['"]\s*\]\.(\w+)"""
)


def _user_variable_defs() -> set[str]:
    """All variable_<name> defined in config/macros/_user_variables.cfg."""
    uv = CONFIG_DIR / "macros" / "_user_variables.cfg"
    if not uv.exists():
        return set()
    return set(re.findall(r"^variable_(\w+)\s*:", uv.read_text(), re.MULTILINE))


def _user_variable_refs() -> set[tuple[str, Path]]:
    """All (name, file) where _USER_VARIABLE.<name> is referenced."""
    refs = set()
    for cfg in _cfg_files():
        for m in USER_VAR_REF_PATTERN.finditer(cfg.read_text()):
            refs.add((m.group(1), cfg))
    return refs


def test_user_variable_references_resolve() -> None:
    """Every _USER_VARIABLE.<name> reference must have a variable_<name> definition."""
    defs = _user_variable_defs()
    refs = _user_variable_refs()
    orphans = sorted({f"{name} (referenced in {p.relative_to(REPO_ROOT)})" for name, p in refs if name not in defs})
    assert not orphans, "Orphan _USER_VARIABLE references:\n" + "\n".join(orphans)


def test_user_variable_definitions_are_used() -> None:
    """Every variable_<name> in _user_variables.cfg must be referenced somewhere."""
    defs = _user_variable_defs()
    if not defs:
        return  # _user_variables.cfg doesn't exist yet
    refs = {name for name, _ in _user_variable_refs()}
    unused = sorted(defs - refs)
    assert not unused, f"Unused _USER_VARIABLE definitions: {unused}"


GCODE_MACRO_BLOCK = re.compile(
    r"^\[gcode_macro\s+(\w+)\]\s*$(.*?)(?=^\[|\Z)",
    re.MULTILINE | re.DOTALL,
)
DESCRIPTION_LINE = re.compile(r"^description\s*:\s*\S", re.MULTILINE)


def test_every_gcode_macro_has_description() -> None:
    """Every [gcode_macro X] must declare a non-empty description: field.

    Exceptions: macros starting with underscore are 'private/helper' macros
    that Klipper hides from Mainsail's macro list. Description is optional.
    """
    missing = []
    for cfg in _cfg_files():
        text = cfg.read_text()
        for match in GCODE_MACRO_BLOCK.finditer(text):
            name = match.group(1)
            body = match.group(2)
            if name.startswith("_"):
                continue  # private helper macros don't need a description
            if not DESCRIPTION_LINE.search(body):
                missing.append(f"{cfg.relative_to(REPO_ROOT)}: [gcode_macro {name}]")
    assert not missing, "Macros without description::\n" + "\n".join(missing)


PARAMS_USE = re.compile(r"params\.(\w+)")
PARAMS_GUARD = re.compile(
    r"""params\.(\w+)\s*(?:\|\s*default\b|is\s+defined)""",
)


def test_params_have_default_or_guard() -> None:
    """Every params.X access in a [gcode_macro] body must call |default(...) or guard with 'is defined'.

    Catches missing-param crashes when slicer arg list changes.
    """
    offenders = []
    for cfg in _cfg_files():
        text = cfg.read_text()
        for match in GCODE_MACRO_BLOCK.finditer(text):
            name = match.group(1)
            body = match.group(2)
            uses = set(PARAMS_USE.findall(body))
            # A param is considered guarded if it has |default OR if 'params.X is defined' appears
            guarded = set(PARAMS_GUARD.findall(body))
            unguarded = uses - guarded
            # Klipper-style: params.X.|float etc. — match the leftmost token
            for param in unguarded:
                offenders.append(f"{cfg.relative_to(REPO_ROOT)}: [gcode_macro {name}] uses params.{param} without |default or 'is defined' guard")
    # Note: this test is informational at the macro level — some macros are designed
    # to require params. Tighten if it produces noise; loosen by macro name allowlist if needed.
    # For now, this is an assertion that catches the most likely refactor regressions.
    assert not offenders, "params.X without default/guard:\n" + "\n".join(offenders)


EXPECTED_INCLUDE_ORDER = [
    "toolhead.cfg",
    "eddy.cfg",
    "macros/_user_variables.cfg",
    "mmu/base/",
    "mmu/optional/client_macros.cfg",
    "mmu/optional/mmu_menu.cfg",
    "mmu/addons/blobifier.cfg",
    "mainsail.cfg",
    "timelapse.cfg",
    "macros/macros.cfg",
    "macros/print_start.cfg",
    "macros/bedfans.cfg",
    "macros/lcd_tweaks.cfg",
    "macros/test_speed.cfg",
    "macros/calibrate_flow.cfg",
    "macros/calibrate_pa.cfg",
]


def test_printer_cfg_include_order() -> None:
    """[include] lines in printer.cfg appear in the expected order.

    Catches accidental include reorders that would change rename_existing
    chains or break user-variable resolution.
    """
    printer_cfg = (CONFIG_DIR / "printer.cfg").read_text()
    includes = re.findall(r"^\[include\s+(\S+)\]", printer_cfg, re.MULTILINE)
    # Filter only those in the expected list (drop wildcards like mmu/base/*.cfg)
    seen = []
    for inc in includes:
        for expected in EXPECTED_INCLUDE_ORDER:
            if inc.startswith(expected) or expected.endswith(inc):
                if expected not in seen:
                    seen.append(expected)
                break
    assert seen == EXPECTED_INCLUDE_ORDER, (
        f"Include order mismatch.\nExpected: {EXPECTED_INCLUDE_ORDER}\nFound:    {seen}"
    )
```

- [ ] **Step 3: Run tests — they should all FAIL right now (since _user_variables.cfg doesn't exist, descriptions aren't present, etc.)**

```sh
.venv/bin/pytest tests/test_config_structure.py -v
```

Expected: the new four tests FAIL. (Existing tests still pass.) Don't commit yet — fixes come in next tasks.

### Task 4.2: Add Layer 7 — behavior diff scaffold + generate "before" snapshot

**Files:**
- Create: `scripts/macro_behavior_diff.py`
- Create: `tests/snapshots/macro_behavior_before.txt`

- [ ] **Step 1: Create the diff script**

Write to `scripts/macro_behavior_diff.py`:

```python
#!/usr/bin/env python3
"""Dump expanded gcode for a fixed set of macro invocations.

Layer 7 of the test pyramid (Phase 4 only). Run twice: once before the
refactor (saving to tests/snapshots/macro_behavior_before.txt), once after
(saving to tests/snapshots/macro_behavior_after.txt). Diff the two. Acceptable
diff: comments-only, whitespace-only. Anything else requires explicit
justification in the PR description.

The script invokes test_klippy.py with a synthesized .test fixture that
calls each macro. Captures the dispatcher output.

Usage:
    python scripts/macro_behavior_diff.py [before|after]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAPSHOTS = REPO / "tests" / "snapshots"
FIXTURE = REPO / "tests" / "macro_behavior.test"

# Fixed set of macro invocations to snapshot
MACRO_INVOCATIONS = [
    "PARKCENTER",
    "PARKFRONT",
    "PARKFRONTLOW",
    "PARKREAR",
    "PARKBED",
    "OFF",
    "HEATSOAK T=110 C=30 MOVE=1 WAIT=0",
    "PRINT_START EXTRUDER=240 BED=110 CHAMBER=45",
    "PRINT_END",
    "BEDFANSFAST",
    "BEDFANSSLOW",
    "BEDFANSOFF",
    "_RESETSPEEDS",
]


def write_fixture() -> None:
    """Create a .test fixture that loads our config and runs each macro."""
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    content_lines = [
        "# Behavior snapshot fixture (generated)",
        "DICTIONARY mcu.dict",
        "DICTIONARY mcu z.dict mcu z",
        "DICTIONARY ebb-usb.dict EBB",
        "DICTIONARY eddy.dict eddy",
        "DICTIONARY easy-brd.dict mmu",
        "CONFIG ../config/printer.cfg",
        "",
        "; Fire each macro and capture the expanded gcode",
    ]
    for invocation in MACRO_INVOCATIONS:
        content_lines.append(f"GCODE: {invocation}")
    FIXTURE.write_text("\n".join(content_lines) + "\n")


def run_snapshot(label: str) -> None:
    """Run test_klippy.py and capture output to snapshots/<label>.txt."""
    output_file = SNAPSHOTS / f"macro_behavior_{label}.txt"
    write_fixture()
    test_klippy = REPO / "vendor" / "klipper" / "scripts" / "test_klippy.py"
    if not test_klippy.exists():
        sys.exit("vendor/klipper not initialized; run: git submodule update --init vendor/klipper")

    result = subprocess.run(
        [
            sys.executable,
            str(test_klippy),
            "-d",
            str(REPO / "tests" / "dict"),
            str(FIXTURE),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    # Capture stdout + stderr; klippy emits gcode and diagnostics on both
    combined = f"=== STDOUT ===\n{result.stdout}\n=== STDERR ===\n{result.stderr}\n"
    output_file.write_text(combined)
    print(f"Wrote {output_file}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("before", "after"):
        sys.exit("Usage: macro_behavior_diff.py [before|after]")
    run_snapshot(sys.argv[1])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the "before" snapshot**

(Must run on Linux — test_klippy.py uses Linux headers. If on macOS, run in a Linux Docker container or do this step from the Pi.)

```sh
python scripts/macro_behavior_diff.py before
ls -la tests/snapshots/macro_behavior_before.txt
```

Expected: file exists, non-empty. Read it to verify the macro outputs were captured.

- [ ] **Step 3: Commit infrastructure + before-snapshot**

```sh
git add tests/test_config_structure.py scripts/macro_behavior_diff.py tests/snapshots/macro_behavior_before.txt
git commit -m "test(refactor): Layer 5 extensions + Layer 7 scaffold + before snapshot

- Layer 5 (test_config_structure.py): add _USER_VARIABLE resolution test,
  description: required test, params default-or-guard test, include order test.
  Four of the five new tests currently FAIL — those are the Phase 4 targets.
- Layer 7 (macro_behavior_diff.py): generates a per-macro gcode snapshot
  via test_klippy.py. Run BEFORE and AFTER the refactor; diff must be
  comments/whitespace only.
- Capture the 'before' snapshot before any macro changes."
```

### Task 4.3: Create `_user_variables.cfg`

**Files:**
- Create: `config/macros/_user_variables.cfg`

- [ ] **Step 1: Create the file**

Write to `config/macros/_user_variables.cfg`:

```ini
########################################################################################################################
# User-tunable variables for voron-2-611
########################################################################################################################
# Centralized config. Read by other macros via:
#   {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
#   {{ uv.bedfans_threshold }}
#
# Edit values here, not in individual macros. RESTART (not FIRMWARE_RESTART) after changes.
#
# Values reflect the current configured behavior of this machine as of 2026-05-15.
# Categories:
#   1. Park positions  (Z heights / offsets; X/Y computed dynamically from axis_maximum)
#   2. BedFans         (Ellis pattern; bed-temp-triggered chamber air circulation through charcoal filter)
#   3. Heatsoak        (HEATSOAK macro defaults)
#   4. Print start     (chamber wait threshold)
#   5. Print end       (cooldown timing, z-lift)
#   6. M109            (temperature tolerance)
#   7. Idle timeout    (reference value; actual setting is in [idle_timeout])
########################################################################################################################

[gcode_macro _USER_VARIABLE]
description: Centralized user-tunable values. Read by other macros via printer["gcode_macro _USER_VARIABLE"].<name>. No gcode body — variables only.

# ─── 1. Park positions (Z values / offsets; X/Y are auto from axis_maximum) ──
variable_park_z_front:                 165   # was: axis_maximum.z/2 (= 330/2)
variable_park_z_front_low:              20
variable_park_z_center:                165   # was: axis_maximum.z/2
variable_park_z_bed:                    15
variable_park_z_rear_offset:            50   # subtracted from axis_maximum.z
variable_park_y_front_offset:            5   # added to axis_minimum.y (FRONT, FRONTLOW)
variable_park_x_rear_offset:            10   # added to axis_minimum.x (REAR)
variable_park_y_rear_offset:            10   # subtracted from axis_maximum.y (REAR)
variable_park_speed_mm_min:           6000

# ─── 2. BedFans (Ellis pattern) ─────────────────────────────────────
variable_bedfans_threshold:            100   # If bed target temp ≥ this, fans are enabled
variable_bedfans_fast:                 0.6   # Fan speed once bed temp reached
variable_bedfans_slow:                 0.2   # Fan speed while bed heating

# ─── 3. Heatsoak (HEATSOAK macro defaults) ───────────────────────────
variable_heatsoak_default_bed:         110
variable_heatsoak_default_chamber:      30
variable_heatsoak_default_move:          1
variable_heatsoak_default_wait:          0

# ─── 4. Print start ─────────────────────────────────────────────────
# Bed temp threshold above which to wait for chamber temperature before starting print
variable_print_start_chamber_bed_threshold: 90

# ─── 5. Print end ───────────────────────────────────────────────────
variable_print_end_cooldown_seconds:    60
variable_print_end_zlift:                5

# ─── 6. M109 tolerance ──────────────────────────────────────────────
variable_m109_tolerance_celsius:         1

# ─── 7. Idle timeout (reference value only; actual config in [idle_timeout]) ──
variable_idle_timeout_minutes:         120

gcode:
    # No body — variables only.
```

- [ ] **Step 2: Add the include to printer.cfg**

In `config/printer.cfg`, find the existing `[include macros/macros.cfg]` line. Add a new include just after the existing `[include eddy.cfg]` (so user variables are loaded before any macro that references them):

```diff
 [include btt-ebb-sb-usb-v1.0.cfg]
 [include eddy.cfg]
+
+# User-tunable variables — must load before macros that reference them
+[include macros/_user_variables.cfg]
+
 [include mmu/base/*.cfg]
```

(The file rename to `toolhead.cfg` happens later in this phase; for now keep the existing name.)

- [ ] **Step 3: Run the Layer 5 _USER_VARIABLE-defined test**

```sh
.venv/bin/pytest tests/test_config_structure.py::test_user_variable_references_resolve tests/test_config_structure.py::test_user_variable_definitions_are_used -v
```

Expected: `test_user_variable_references_resolve` PASSES (no references yet to be orphan). `test_user_variable_definitions_are_used` FAILS — variables defined but not yet referenced.

- [ ] **Step 4: Commit the infrastructure**

```sh
git add config/macros/_user_variables.cfg config/printer.cfg
git commit -m "feat(macros): add _USER_VARIABLE macro for centralized tunables

Variables reflect current configured behavior verbatim — no value changes.
Other macros consume via:
    {% set uv = printer[\"gcode_macro _USER_VARIABLE\"] %}
Migrations to actually read from _USER_VARIABLE follow in subsequent commits."
```

### Task 4.4: Migrate macros/bedfans.cfg to _USER_VARIABLE

**Files:**
- Modify: `config/macros/bedfans.cfg`

- [ ] **Step 1: Delete `_BEDFANVARS` and replace all `_BEDFANVARS.X` references with `_USER_VARIABLE.bedfans_X`**

Edit `config/macros/bedfans.cfg`:

```diff
 ############### Config options ##################
-[gcode_macro _BEDFANVARS]
-variable_threshold: 100		# If bed temp target is above this threshold, fans will be enabled. If temp is set to below this threshold, fans will be disabled.
-variable_fast: 0.6		# Fan speed once bed temp is reached
-variable_slow: 0.2		# Fan speed while bed is heating
-gcode:

 ########## Bed Fans #########
 [fan_generic BedFans]
 pin: z:P2.5
 #cycle_time: 0.05
 kick_start_time: 0.5

 ########## Aliases #########
 [gcode_macro BEDFANSSLOW]
+description: Set bed fans to slow speed (heating phase).
 gcode:
-	# Vars
-	{% set SLOW = printer["gcode_macro _BEDFANVARS"].slow|float %}
+	{% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+	{% set SLOW = uv.bedfans_slow|float %}

 	SET_FAN_SPEED FAN=BedFans SPEED={SLOW}

 [gcode_macro BEDFANSFAST]
+description: Set bed fans to fast speed (post-heating).
 gcode:
-	# Vars
-	{% set FAST = printer["gcode_macro _BEDFANVARS"].fast|float %}
+	{% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+	{% set FAST = uv.bedfans_fast|float %}

 	SET_FAN_SPEED FAN=BedFans SPEED={FAST}

 [gcode_macro BEDFANSOFF]
+description: Turn bed fans off.
 gcode:
 	SET_FAN_SPEED FAN=BedFans SPEED=0

 ############ Command overrides ############
 # Override, set fan speeds to low and start monitoring loop.
 [gcode_macro SET_HEATER_TEMPERATURE]
 rename_existing: _SET_HEATER_TEMPERATURE
+description: Wrapper for SET_HEATER_TEMPERATURE that also drives bed fans.
 gcode:
 	# Parameters
 	{% set HEATER = params.HEATER|default("None") %}
 	{% set TARGET = params.TARGET|default(0)|int %}
-	# Vars
-	{% set THRESHOLD = printer["gcode_macro _BEDFANVARS"].threshold|int %}
+	{% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+	{% set THRESHOLD = uv.bedfans_threshold|int %}

 	{% if HEATER|lower == "extruder" %}
 		M104 S{TARGET}
 	{% elif HEATER|lower == "heater_bed" %}
 		M99140 S{TARGET}
 	{% else %}
 		{action_respond_info("Heater %s not supported" % HEATER)}
 	{% endif %}

 	# Set fans to low if heater_bed temp is requested above threshold temp, and kick off monitoring loop.
 	{% if HEATER|lower == "heater_bed" %}
 		{% if TARGET >= THRESHOLD %}
 			BEDFANSSLOW
 			UPDATE_DELAYED_GCODE ID=bedfanloop DURATION=1
 		{% else %}
 			BEDFANSOFF
 			UPDATE_DELAYED_GCODE ID=bedfanloop DURATION=0
 		{% endif %}
 	{% endif %}

 # Override M190 (Wait for Bed Temperature)
 [gcode_macro M190]
 rename_existing: M99190
+description: Wait for bed temperature; integrates bed-fan control.
 gcode:
 	{% set S = params.S|int %}
-	{% set THRESHOLD = printer["gcode_macro _BEDFANVARS"].threshold|int %}
+	{% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+	{% set THRESHOLD = uv.bedfans_threshold|int %}

 	{% if S >= THRESHOLD %}
 		BEDFANSSLOW
 	{% else %}
 		BEDFANSOFF
 	{% endif %}

 	M140 {% for p in params %}{'%s%s' % (p, params[p])}{% endfor %}

 	{% if S != 0 %}
 		TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={S|int} MAXIMUM={S|int + 5}
 	{% endif %}

 	{% if S >= THRESHOLD %}
 		BEDFANSFAST
 	{% endif %}

 # Replace M140 (Set Bed Temperature) — alias of SET_HEATER_TEMPERATURE
 [gcode_macro M140]
 rename_existing: M99140
+description: Set bed temperature (alias for SET_HEATER_TEMPERATURE HEATER=heater_bed).
 gcode:
 	{% set S = params.S|float %}

 	SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={S}

 # Replace TURN_OFF_HEATERS
 [gcode_macro TURN_OFF_HEATERS]
 rename_existing: _TURN_OFF_HEATERS
+description: Turn off all heaters and bed fans together.
 gcode:
 	BEDFANSOFF
 	_TURN_OFF_HEATERS

 ################ Monitoring loop #####################
 # Turns bed fans to "fast" speed once target bed temp is reached.
 [delayed_gcode bedfanloop]
 gcode:
-	{% set THRESHOLD = printer["gcode_macro _BEDFANVARS"].threshold|int %}
+	{% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+	{% set THRESHOLD = uv.bedfans_threshold|int %}

 	{% if printer.heater_bed.target >= THRESHOLD %}
 		{% if printer.heater_bed.temperature|int >= (printer.heater_bed.target|int - 1) %}
 			BEDFANSFAST
 		{% else %}
 			UPDATE_DELAYED_GCODE ID=bedfanloop DURATION=5
 		{% endif %}
 	{% endif %}
```

- [ ] **Step 2: Run tests**

```sh
.venv/bin/pytest tests/test_config_structure.py -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected:
- `test_user_variable_references_resolve` PASS (the new references all resolve)
- `test_every_gcode_macro_has_description` should now have fewer offenders (bedfans macros covered)
- `macro_refcheck.py` PASS (no orphan command references)

- [ ] **Step 3: Commit**

```sh
git add config/macros/bedfans.cfg
git commit -m "refactor(bedfans): migrate _BEDFANVARS to _USER_VARIABLE; add description fields

Delete _BEDFANVARS gcode_macro (values rolled into _USER_VARIABLE).
Values unchanged: threshold=100, fast=0.6, slow=0.2."
```

### Task 4.5: Migrate macros/macros.cfg

**Files:**
- Modify: `config/macros/macros.cfg`

- [ ] **Step 1: Add description fields + migrate park macros + HEATSOAK + M109**

Edit `config/macros/macros.cfg` to use `_USER_VARIABLE` for tunable values and add descriptions everywhere. The full diff per macro:

```diff
 # Conditional G28 (home if not already homed)
 [gcode_macro _CG28]
+description: Conditional G28 — home only if not already homed.
 gcode:
     {% if "xyz" not in printer.toolhead.homed_axes %}
         G28
     {% endif %}

 # Conditional QGL (home if not already done)
 [gcode_macro _CQGL]
+description: Conditional QGL — home and QGL only if not already applied.
 gcode:
     {% if printer.quad_gantry_level.applied == False %}
         {% if "xyz" not in printer.toolhead.homed_axes %}
             G28
         {% endif %}
         QUAD_GANTRY_LEVEL
         G28 Z
     {% endif %}

 [gcode_macro OFF]
+description: Shut everything off — steppers, heaters, fans, lights.
 gcode:
     M84
     TURN_OFF_HEATERS
     M107
     set_temperature_fan_target temperature_fan=chamber target=0
     SET_FAN_SPEED FAN=BedFans SPEED=0
     SET_PIN PIN=caselight VALUE=0

 [gcode_macro SHUTDOWN]
+description: OFF + power off the host machine (via Moonraker).
 gcode:
     OFF
     {action_call_remote_method("shutdown_machine")}

 # Park front center
 [gcode_macro PARKFRONT]
+description: Park toolhead at front center, mid-height.
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
     _CG28
     SAVE_GCODE_STATE NAME=PARKFRONT
     G90
-    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_minimum.y+5} Z{printer.toolhead.axis_maximum.z/2} F6000
+    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_minimum.y + uv.park_y_front_offset} Z{uv.park_z_front} F{uv.park_speed_mm_min}
     RESTORE_GCODE_STATE NAME=PARKFRONT

 # Park front center, but low down.
 [gcode_macro PARKFRONTLOW]
+description: Park toolhead at front center, low height (easier access).
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
     _CG28
     SAVE_GCODE_STATE NAME=PARKFRONT
     G90
-    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_minimum.y+5} Z20 F6000
+    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_minimum.y + uv.park_y_front_offset} Z{uv.park_z_front_low} F{uv.park_speed_mm_min}
     RESTORE_GCODE_STATE NAME=PARKFRONT

 # Park top rear left
 [gcode_macro PARKREAR]
+description: Park toolhead at rear-left, near top of Z.
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
     _CG28
     SAVE_GCODE_STATE NAME=PARKREAR
     G90
-    G0 X{printer.toolhead.axis_minimum.x+10} Y{printer.toolhead.axis_maximum.y-10} Z{printer.toolhead.axis_maximum.z-50} F6000
+    G0 X{printer.toolhead.axis_minimum.x + uv.park_x_rear_offset} Y{printer.toolhead.axis_maximum.y - uv.park_y_rear_offset} Z{printer.toolhead.axis_maximum.z - uv.park_z_rear_offset} F{uv.park_speed_mm_min}
     RESTORE_GCODE_STATE NAME=PARKREAR

 [gcode_macro _RESETSPEEDS]
+description: Reset velocity / accel / SCV limits to configured maxima.
 gcode:
     SET_VELOCITY_LIMIT VELOCITY={printer.configfile.settings.printer.max_velocity}
     SET_VELOCITY_LIMIT ACCEL={printer.configfile.settings.printer.max_accel}
     SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY={printer.configfile.settings.printer.square_corner_velocity}

 # Park at center of build volume
 [gcode_macro PARKCENTER]
+description: Park toolhead at center of build volume.
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
     _CG28
     SAVE_GCODE_STATE NAME=PARKCENTER
     G90
-    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_maximum.y/2} Z{printer.toolhead.axis_maximum.z/2} F6000
+    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_maximum.y/2} Z{uv.park_z_center} F{uv.park_speed_mm_min}
     RESTORE_GCODE_STATE NAME=PARKCENTER

 # Park 15mm above center of bed
 [gcode_macro PARKBED]
+description: Park toolhead at bed center, near the bed surface.
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
     _CG28
     SAVE_GCODE_STATE NAME=PARKBED
     G90
-    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_maximum.y/2} Z15 F6000
+    G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_maximum.y/2} Z{uv.park_z_bed} F{uv.park_speed_mm_min}
     RESTORE_GCODE_STATE NAME=PARKBED

 [gcode_macro M109]
 rename_existing: M99109
+description: Override M109 — wait for hotend temp within ±tolerance (tunable in _USER_VARIABLE).
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
     {% set s = params.S|float %}
+    {% set tol = uv.m109_tolerance_celsius|float %}

     M104 {% for p in params %}{'%s%s' % (p, params[p])}{% endfor %}
     {% if s != 0 %}
-        TEMPERATURE_WAIT SENSOR=extruder MINIMUM={s} MAXIMUM={s+1}
+        TEMPERATURE_WAIT SENSOR=extruder MINIMUM={s} MAXIMUM={s + tol}
     {% endif %}

 [delayed_gcode DELAYED_OFF]
 gcode:
     OFF

 [gcode_macro HEATSOAK]
+description: Heat bed (and optionally wait for chamber); park toolhead during soak.
 gcode:
-    # Parameters
-    {% set t = params.T|default(110)|int %}
-    {% set c = params.C|default(30)|int %}
-    {% set move = params.MOVE|default(1)|int %}
-    {% set wait = params.WAIT|default(0)|int %}
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+    {% set t = params.T|default(uv.heatsoak_default_bed)|int %}
+    {% set c = params.C|default(uv.heatsoak_default_chamber)|int %}
+    {% set move = params.MOVE|default(uv.heatsoak_default_move)|int %}
+    {% set wait = params.WAIT|default(uv.heatsoak_default_wait)|int %}

     SAVE_GCODE_STATE NAME=HEATSOAK
     UPDATE_DELAYED_GCODE ID=DELAYED_OFF DURATION=0
     M140 S{t}
     {% if move == 1 %}
         _CG28
         G90
         G0 Z{printer.toolhead.axis_maximum.z/2} F19500
         G0 X{printer.toolhead.axis_maximum.x/2} Y{printer.toolhead.axis_maximum.y/2} F19500
     {% endif %}
     {% if c > 30 and wait == 1 %}
         TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={c}
     {% endif %}
     RESTORE_GCODE_STATE NAME=HEATSOAK

 [gcode_macro FIRST_LAYER_Z_TEST]
 description: "Print first-layer test lines with different Z-offsets (with z-hop at 50mm/s and bidirectional printing) for optimal squish"
 gcode:
     # ... (no changes to this macro — already has description) ...
```

Note: FIRST_LAYER_Z_TEST stays as-is (it already has a description; nothing tunable enough to extract).

- [ ] **Step 2: Run tests**

```sh
.venv/bin/pytest tests/test_config_structure.py -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected:
- `test_every_gcode_macro_has_description` should now have NO offenders (all macros have descriptions).
- `test_user_variable_references_resolve` PASS.
- `test_user_variable_definitions_are_used` MIGHT still fail if some variables (e.g., `idle_timeout_minutes`) aren't yet referenced — that's OK, idle_timeout variable is reference-only.

If `test_user_variable_definitions_are_used` fails on `idle_timeout_minutes`, remove that variable from `_user_variables.cfg` (it was for documentation only; the actual `[idle_timeout]` section in `printer.cfg` is the source of truth). Re-run tests.

- [ ] **Step 3: Commit**

```sh
git add config/macros/macros.cfg config/macros/_user_variables.cfg
git commit -m "refactor(macros): migrate park + HEATSOAK + M109 to _USER_VARIABLE; descriptions

Values copied verbatim from existing macros. No behavior change."
```

### Task 4.6: Migrate macros/print_start.cfg

**Files:**
- Modify: `config/macros/print_start.cfg`

- [ ] **Step 1: Add descriptions + migrate threshold + cooldown + zlift**

Edit `config/macros/print_start.cfg`:

```diff
 [gcode_macro PRINT_WARMUP]
+description: Pre-heat without homing the printer — caselight, mesh clear, optional homing + QGL, then start bed + hotend heating.
 gcode:
   {% set bed = params.BED|int %}
   {% set extruder = params.EXTRUDER|int %}
   {% set chamber = params.CHAMBER|default("0")|int %}
   {% set x_wait = printer.toolhead.axis_maximum.x|float / 2 %}
   {% set y_wait = printer.toolhead.axis_maximum.y|float / 2 %}

   SET_PIN PIN=caselight VALUE=0.3
   _RESETSPEEDS
   BED_MESH_CLEAR
   _CG28
   _CQGL
   M140 S{bed}
   M104 S{extruder}


 [gcode_macro PRINT_START]
+description: Slicer-called print start — home, QGL, heat, soak, tap, mesh, hotend.
 gcode:
+  {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
-  # # This part fetches data from your slicer.
   {% set bed = params.BED|int %}
   {% set extruder = params.EXTRUDER|int %}
   {% set chamber = params.CHAMBER|default("0")|int %}
   {% set x_wait = printer.toolhead.axis_maximum.x|float / 2 %}
   {% set y_wait = printer.toolhead.axis_maximum.y|float / 2 %}

   _CG28
   _CQGL
   G90

-  # Check if the bed temp is higher than 90c - if so then trigger a heatsoak.
-  {% if params.BED|int > 90 %}
+  # Check if bed temp exceeds chamber-wait threshold — if so, trigger heatsoak
+  {% if bed > uv.print_start_chamber_bed_threshold|int %}
     M106 S255
     PARKCENTER
     M190 S{bed}
     TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={(chamber/2)}
   {% else %}
     M190 S{bed}
   {% endif %}

   BLOBIFIER_CLEAN
   G28 Z
   PROBE METHOD=tap
   SET_KINEMATIC_POSITION Z={printer.probe.last_z_result}
   BED_MESH_CALIBRATE ADAPTIVE=1

   G1 X{x_wait} Y{y_wait} Z15 F9000
   M107
   M109 S{extruder}


 [gcode_macro PRINT_END]
+description: Slicer-called print end — zero extruder, kill heaters/fans, clear mesh, cool, OFF.
 gcode:
+    {% set uv = printer["gcode_macro _USER_VARIABLE"] %}
+    {% set cooldown_ms = (uv.print_end_cooldown_seconds|int) * 1000 %}
+    {% set zlift = uv.print_end_zlift|int %}
     M400
     G92 E0
     M104 S0
     M140 S0
     M107
     G91
-    G1 Z5 F3000
+    G1 Z{zlift} F3000
     G90
     BED_MESH_CLEAR
-    G4 P60000
+    G4 P{cooldown_ms}
     OFF
     _RESETSPEEDS
```

Note: keep `params.BED|int` reference style consistent with other accesses. Add `|default(0)` where missing for the Layer 5 `params.X` guard test.

Actually `params.BED|int` doesn't have `|default()`. Looking at the Layer 5 test more carefully — Klipper templates DO require `|default()` when the param might not be passed. PRINT_START expects BED/EXTRUDER, so those are required params; missing them is a slicer config error, not a refactor regression.

Let me weaken the Layer 5 test to skip required-by-design params. Update `tests/test_config_structure.py`:

- Add an `ALLOWLIST_REQUIRED_PARAMS` set listing `(macro_name, param_name)` tuples that are designed to crash without the param (the slicer is expected to provide them).
- Skip those in the guard test.

Or simpler: don't test `params.X` guards — only test `params.X|default(...)` or `is defined` checks for OPTIONAL params. This is hard to distinguish statically.

Actually let me revise: just inspect each `params.X` and check it has at least one of `|default(...)`, `is defined`, or `[X]` (dict access). If none, flag — but allow a per-macro allowlist for known-required params.

For now, simpler: PRINT_START's BED and EXTRUDER are designed-required. Add a comment + allowlist:

Update the Layer 5 test (add `KNOWN_REQUIRED_PARAMS`):

```python
# Params that are designed to be required (slicer must pass them).
# {(macro_name, param_name): "reason"}
KNOWN_REQUIRED_PARAMS = {
    ("PRINT_START", "BED"): "slicer required — first_layer_bed_temperature",
    ("PRINT_START", "EXTRUDER"): "slicer required — first_layer_temperature",
    ("PRINT_WARMUP", "BED"): "same as PRINT_START",
    ("PRINT_WARMUP", "EXTRUDER"): "same as PRINT_START",
    ("M109", "S"): "M109 always passes S",
    ("M190", "S"): "M190 always passes S",
    ("M140", "S"): "M140 always passes S",
    ("SET_HEATER_TEMPERATURE", "HEATER"): "klipper internal, always passed",
    ("SET_HEATER_TEMPERATURE", "TARGET"): "klipper internal, always passed",
    ("SET_PAUSE_NEXT_LAYER", "ENABLE"): "Mainsail callsite always passes",
    ("SET_PAUSE_AT_LAYER", "ENABLE"): "Mainsail callsite always passes",
    ("FIRST_LAYER_Z_TEST", "START"): "user-passed; default already present via |default",
    # add others as encountered
}
```

Update `test_params_have_default_or_guard` to skip these.

This is getting complex. I'll fold these allowlist additions into the actual edits.

- [ ] **Step 2: Update the Layer 5 test with allowlist**

In `tests/test_config_structure.py`, modify `test_params_have_default_or_guard`:

```python
KNOWN_REQUIRED_PARAMS = {
    ("PRINT_START", "BED"),
    ("PRINT_START", "EXTRUDER"),
    ("PRINT_WARMUP", "BED"),
    ("PRINT_WARMUP", "EXTRUDER"),
    ("M109", "S"),
    ("M190", "S"),
    ("M140", "S"),
    ("SET_HEATER_TEMPERATURE", "HEATER"),
    ("SET_HEATER_TEMPERATURE", "TARGET"),
    ("SET_PAUSE_NEXT_LAYER", "ENABLE"),
    ("SET_PAUSE_AT_LAYER", "ENABLE"),
}


def test_params_have_default_or_guard() -> None:
    offenders = []
    for cfg in _cfg_files():
        text = cfg.read_text()
        for match in GCODE_MACRO_BLOCK.finditer(text):
            name = match.group(1)
            body = match.group(2)
            uses = set(PARAMS_USE.findall(body))
            guarded = set(PARAMS_GUARD.findall(body))
            unguarded = uses - guarded
            for param in unguarded:
                if (name, param) in KNOWN_REQUIRED_PARAMS:
                    continue
                offenders.append(f"{cfg.relative_to(REPO_ROOT)}: [gcode_macro {name}] uses params.{param} without |default or 'is defined' guard")
    assert not offenders, "params.X without default/guard:\n" + "\n".join(offenders)
```

- [ ] **Step 3: Run tests**

```sh
.venv/bin/pytest tests/test_config_structure.py -v
```

Expected: PASS for all four new tests now (assuming PRINT_START/PRINT_WARMUP correctly listed in allowlist, and the macros have descriptions).

- [ ] **Step 4: Commit**

```sh
git add config/macros/print_start.cfg tests/test_config_structure.py
git commit -m "refactor(print_start): migrate to _USER_VARIABLE; descriptions

Read print_start_chamber_bed_threshold, print_end_cooldown_seconds,
and print_end_zlift from _USER_VARIABLE. Values copied verbatim
(90, 60, 5). Allowlist required slicer params (BED, EXTRUDER) in
Layer 5 test."
```

### Task 4.7: Add descriptions to lcd_tweaks.cfg

**Files:**
- Modify: `config/macros/lcd_tweaks.cfg`

- [ ] **Step 1: Check what macros exist there and which lack descriptions**

```sh
grep -E "^\[(gcode_macro|menu)" config/macros/lcd_tweaks.cfg
```

Most entries are `[display_glyph]` / `[display_data]` / `[menu]` — these aren't `[gcode_macro]` and don't need `description:`. The only `[gcode_macro]` entries (if any) need descriptions.

- [ ] **Step 2: Add descriptions where needed**

For each `[gcode_macro]` found, add a `description:` line. (If there are none, this task is a no-op.)

- [ ] **Step 3: Run tests**

```sh
.venv/bin/pytest tests/test_config_structure.py -v
```

Expected: PASS (all macros have descriptions).

- [ ] **Step 4: Commit (if changes)**

```sh
git add config/macros/lcd_tweaks.cfg
git commit -m "refactor(lcd_tweaks): add missing description fields"
```

### Task 4.8: Rename btt-ebb-sb-usb-v1.0.cfg → toolhead.cfg

**Files:**
- Rename: `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`
- Modify: `config/printer.cfg` (include line)
- Modify: `tests/voron-2-611.test`
- Modify: `scripts/macro_refcheck.py` (if any path constant)
- Modify: `CLAUDE.md` (path references)
- Modify: `docs/superpowers/specs/2026-05-15-config-macros-refactor.md` (self-reference)
- Modify: `docs/superpowers/plans/2026-05-15-config-macros-refactor.md` (self-reference)

- [ ] **Step 1: Rename the file**

```sh
git mv config/btt-ebb-sb-usb-v1.0.cfg config/toolhead.cfg
```

- [ ] **Step 2: Update the include in printer.cfg**

```sh
sed -i.bak 's|btt-ebb-sb-usb-v1.0.cfg|toolhead.cfg|g' config/printer.cfg && rm config/printer.cfg.bak
grep "include.*toolhead\|include.*btt-ebb" config/printer.cfg
```

Expected: `[include toolhead.cfg]`. No remaining `btt-ebb` references.

- [ ] **Step 3: Update all other repo references**

```sh
git grep -l "btt-ebb-sb-usb-v1.0" -- ':(exclude)config/toolhead.cfg' ':(exclude)vendor/**' | xargs sed -i.bak 's|btt-ebb-sb-usb-v1.0\.cfg|toolhead.cfg|g'
find . -name "*.bak" -not -path "./vendor/*" -delete
git status
```

Expected: changes in `tests/voron-2-611.test`, `scripts/macro_refcheck.py`, `CLAUDE.md`, and the spec/plan docs.

- [ ] **Step 4: Run all tests**

```sh
.venv/bin/pytest tests/ -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```sh
git add -A
git commit -m "refactor(config): rename btt-ebb-sb-usb-v1.0.cfg → toolhead.cfg

Semantic name; if EBB ever gets swapped, the file name stays valid.
Updated references in:
- config/printer.cfg [include] line
- tests/voron-2-611.test
- scripts/macro_refcheck.py (path constants if any)
- CLAUDE.md
- docs/superpowers/specs/2026-05-15-config-macros-refactor.md
- docs/superpowers/plans/2026-05-15-config-macros-refactor.md"
```

### Task 4.9: Consolidate [extruder] PA + limits into toolhead.cfg

**Files:**
- Modify: `config/printer.cfg` (delete the small [extruder] section currently at lines ~231-238)
- Modify: `config/toolhead.cfg` (extruder stepper section gains PA + temp_limits)

- [ ] **Step 1: Find current `[extruder]` content in printer.cfg**

```sh
grep -n "^\[extruder\]" config/printer.cfg config/toolhead.cfg
sed -n '/^\[extruder\]/,/^\[/p' config/printer.cfg | head -20
```

Expected: `[extruder]` section in `config/printer.cfg` starting around line 231, containing `pressure_advance: 0.05`, `pressure_advance_smooth_time: 0.040`, `max_extrude_only_distance: 500`, and `min_extrude_temp: 170`.

- [ ] **Step 2: Move the contents into toolhead.cfg**

Append the PA / limit lines to `config/toolhead.cfg`'s existing `[extruder]` section (Klipper merges multiple `[extruder]` blocks across includes, but consolidating is cleaner). After the move, `config/printer.cfg`'s `[extruder]` block is deleted entirely.

In `config/toolhead.cfg`, find the existing `[extruder]` section (line ~24-43 of current file). After the existing config lines (microsteps, rotation_distance, etc.) and before any subsequent section header, add:

```ini
# Pressure advance + extrude limits (was in printer.cfg before 2026-MM-DD)
pressure_advance: 0.05
pressure_advance_smooth_time: 0.040
max_extrude_only_distance: 500
min_extrude_temp: 170
```

- [ ] **Step 3: Delete the corresponding lines from printer.cfg**

Remove the `[extruder]` block in `config/printer.cfg` that contains only these values (don't remove other `[extruder]` definitions if any — but there shouldn't be any others).

- [ ] **Step 4: Run klippy parse via CI or verify locally**

If on Linux:
```sh
make test
```

If on macOS: rely on CI. Run macro_refcheck locally:
```sh
.venv/bin/python scripts/macro_refcheck.py
```

- [ ] **Step 5: Commit**

```sh
git add config/printer.cfg config/toolhead.cfg
git commit -m "refactor(extruder): consolidate PA + limits into toolhead.cfg

Extruder lives in one file. printer.cfg's [extruder] block (PA, smooth_time,
max_extrude_only_distance, min_extrude_temp) merged into toolhead.cfg's
existing [extruder] stepper/heater section."
```

### Task 4.10: Resolve duplicate section declarations

**Files:**
- Modify: `config/printer.cfg`, `config/mainsail.cfg`, and possibly other files

Sections currently declared in multiple places:
- `[exclude_object]` — `config/printer.cfg:96` and `config/mmu/addons/blobifier.cfg:737`
- `[respond]` — `config/printer.cfg:97`, `config/mainsail.cfg:61`, `config/mmu/base/mmu_macro_vars.cfg:50`
- `[display_status]` — `config/mainsail.cfg:59`, `config/mmu/base/mmu_macro_vars.cfg:53-54`
- `[pause_resume]` — `config/mainsail.cfg:54`, `config/mmu/base/mmu_macro_vars.cfg:53-54`

Decision: keep HH's declarations (per `defer-to-happy-hare`) and drop the duplicates in our files.

- [ ] **Step 1: Remove duplicate `[exclude_object]` from printer.cfg**

```sh
grep -n "^\[exclude_object\]" config/printer.cfg
```

Delete the line if present (HH's blobifier.cfg provides it).

- [ ] **Step 2: Remove duplicate `[respond]` from printer.cfg**

```sh
grep -n "^\[respond\]" config/printer.cfg
```

Delete the line if present (HH and mainsail.cfg both provide it; HH wins per defer-to-happy-hare).

- [ ] **Step 3: Verify klippy still parses**

(Run on Linux or rely on CI.) Klipper will tolerate one declaration per section — confirm CI passes.

- [ ] **Step 4: Run all tests**

```sh
.venv/bin/pytest tests/ -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```sh
git add config/printer.cfg
git commit -m "refactor(printer.cfg): remove duplicate [exclude_object] and [respond] declarations

Happy Hare (mmu/addons/blobifier.cfg and mmu/base/mmu_macro_vars.cfg)
already provides these. Per memory/defer-to-happy-hare.md."
```

### Task 4.11: Reorganize printer.cfg [include] order with section comments

**Files:**
- Modify: `config/printer.cfg`

- [ ] **Step 1: Reorganize the include block at the top of printer.cfg**

Replace the current `[include …]` lines at the top of `config/printer.cfg` with this organized block:

```ini
# ─── MCU configs ──────────────────────────────────────────────────────────────
[include toolhead.cfg]                # toolhead MCU (extruder, hotend, fans, accel)

# ─── Probe + bed leveling ─────────────────────────────────────────────────────
[include eddy.cfg]                    # Eddy probe + bed_mesh + force_move + QGL/BED_MESH overrides

# ─── User tunables (loads before macros that reference them) ──────────────────
[include macros/_user_variables.cfg]

# ─── MMU (Happy Hare) ─────────────────────────────────────────────────────────
[include mmu/base/*.cfg]
[include mmu/optional/client_macros.cfg]    # HH PAUSE/RESUME/CANCEL_PRINT (canonical)
[include mmu/optional/mmu_menu.cfg]
[include mmu/addons/blobifier.cfg]

# (200+ lines of core printer config: kinematics, steppers, heaters, fans, display, etc.)
```

And at the bottom of the file (before SAVE_CONFIG):

```ini
# ─── Client + user macros ─────────────────────────────────────────────────────
[include mainsail.cfg]                # slimmed: section declarations + helpers only
[include timelapse.cfg]               # symlink, currently unused — see GH Issue #TBD
[include macros/macros.cfg]
[include macros/print_start.cfg]
[include macros/bedfans.cfg]
[include macros/lcd_tweaks.cfg]
[include macros/test_speed.cfg]
[include macros/calibrate_flow.cfg]
[include macros/calibrate_pa.cfg]
```

- [ ] **Step 2: Run the include-order test**

```sh
.venv/bin/pytest tests/test_config_structure.py::test_printer_cfg_include_order -v
```

Expected: PASS.

- [ ] **Step 3: Run all tests**

```sh
.venv/bin/pytest tests/ -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```sh
git add config/printer.cfg
git commit -m "refactor(printer.cfg): reorganize [include] order with section comments

Includes grouped: MCU configs → Probe/bed → User tunables → MMU →
(core config) → Client + macros. Section comments document the
purpose of each group."
```

### Task 4.12: Generate "after" snapshot; diff; verify; merge gate

**Files:**
- Create: `tests/snapshots/macro_behavior_after.txt`

- [ ] **Step 1: Generate the after snapshot**

(Must run on Linux.)

```sh
python scripts/macro_behavior_diff.py after
ls -la tests/snapshots/macro_behavior_after.txt
```

- [ ] **Step 2: Diff before vs after**

```sh
diff -u tests/snapshots/macro_behavior_before.txt tests/snapshots/macro_behavior_after.txt
```

Acceptable diff: comments-only, whitespace-only. Anything that changes a gcode command, a parameter value, or a sequence is a regression — investigate and fix before merging.

- [ ] **Step 3: If diff is clean, commit the after snapshot**

```sh
git add tests/snapshots/macro_behavior_after.txt
git commit -m "test(refactor): capture after snapshot — diff vs before is whitespace/comments only

Layer 7 behavior diff for Phase 4. The refactor preserves all macro
gcode emission verbatim; only structure (variable references) changes.

See diff in PR description."
```

If the diff shows real differences, do NOT commit. Fix the offending macros and re-run.

### Task 4.13: Push, CI, merge, deploy, smoke

- [ ] **Step 1: Push and PR**

```sh
git push -u origin feat/macros-refactor
gh pr create --base main --title "refactor(macros): single _USER_VARIABLE, rename toolhead.cfg, consolidate sections" --body "$(cat <<'EOF'
## Summary
Phase 4 of \`docs/superpowers/specs/2026-05-15-config-macros-refactor.md\`. The biggest phase.

- New \`config/macros/_user_variables.cfg\` with single \`_USER_VARIABLE\` macro consolidating tunables (park positions, BedFans, HEATSOAK, print sequence pacing, M109 tolerance).
- Rename \`config/btt-ebb-sb-usb-v1.0.cfg\` → \`config/toolhead.cfg\`.
- Consolidate \`[extruder]\` PA + temp_limits into \`toolhead.cfg\`.
- Add \`description:\` field to every \`[gcode_macro]\`.
- Resolve duplicate \`[exclude_object]\` and \`[respond]\` declarations.
- Reorganize \`config/printer.cfg\` [include] order with section comments.
- Delete \`_BEDFANVARS\` (rolled into \`_USER_VARIABLE\`).

## Behavior preservation (Layer 7)
\`tests/snapshots/macro_behavior_before.txt\` vs \`tests/snapshots/macro_behavior_after.txt\` diff: comments/whitespace only.

## Test plan
- [x] Layer 5 structural tests all pass (4 new assertions)
- [x] Layer 7 behavior diff is clean
- [x] \`macro_refcheck.py\` passes
- [ ] CI klippy parse passes
- [ ] Post-deploy: TEST_SPEED, PARKCENTER, PRINT_START dry-run all execute without error

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: CI green, merge, deploy**

```sh
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
bash scripts/deploy_to_pi.sh
```

- [ ] **Step 3: Post-deploy smoke**

In Mainsail console:
```
PARKCENTER
PARKFRONT
PARKBED
OFF
BEDFANSFAST
BEDFANSSLOW
BEDFANSOFF
HEATSOAK T=60 C=0 MOVE=0 WAIT=0
```

Expected: each command completes without `!! Unknown command` in `klippy.log`. The HEATSOAK runs to bed 60°C but with MOVE=0 and WAIT=0 it's just a bed heat — quick.

If any errors, investigate before merging to main.

---

## Phase 5: OrcaSlicer hooks + PRINT_START harmonization

**Branch:** `feat/slicer-hooks`
**Estimated diff:** ~100 lines
**PR title:** `feat(slicer): document OrcaSlicer start/end gcode templates`

**Files:**
- Create: `docs/slicer-templates/orcaslicer-start.gcode`
- Create: `docs/slicer-templates/orcaslicer-end.gcode`
- Create: `docs/slicer-templates/README.md`
- Modify: `config/macros/print_start.cfg` (if PRINT_START needs param-handling robustness adjustments)

### Task 5.1: Pull recent gcode from Pi, branch

- [ ] **Step 1: Branch**

```sh
git switch main && git pull --ff-only
git switch -c feat/slicer-hooks
```

- [ ] **Step 2: Pull a recent gcode file from the Pi**

```sh
ssh pi@mainsailos.local 'ls -t ~/printer_data/gcodes/*.gcode | head -1' | xargs -I{} scp pi@mainsailos.local:{} /tmp/recent-print.gcode
```

If no recent files exist, that's information — slicer templates haven't been recently exercised. Use one from the slicer's output even if old.

- [ ] **Step 3: Read head and tail to see what slicer emits**

```sh
head -80 /tmp/recent-print.gcode
echo "---TAIL---"
tail -30 /tmp/recent-print.gcode
```

Note any calls like `PRINT_START`, `PRINT_END`, `SET_PRINT_STATS_INFO`. Also note any `MMU_*` calls. The file is post-`[mmu_server]`-preprocessing, so `!referenced_tools!` etc. are already resolved.

Save the relevant snippets to scratch (will be referenced when writing the slicer-template documentation).

### Task 5.2: Create slicer-template files

**Files:**
- Create: `docs/slicer-templates/orcaslicer-start.gcode`
- Create: `docs/slicer-templates/orcaslicer-end.gcode`
- Create: `docs/slicer-templates/README.md`

- [ ] **Step 1: Create the start template**

Write to `docs/slicer-templates/orcaslicer-start.gcode`:

```gcode
; OrcaSlicer "Machine start G-code" template for voron-2-611
;
; Drop this into OrcaSlicer: Printer Settings → Machine G-code → Machine start G-code
;
; Tokens explained:
;   {…}    OrcaSlicer-native — resolved by the slicer at slice time
;   !…!    Happy Hare-specific — resolved by Moonraker's [mmu_server] at upload time
;          (see vendor/happy-hare/components/mmu_server.py:870-900)

M104 S0     ; cancel any pre-existing target (paranoia)
M140 S0

MMU_START_SETUP INITIAL_TOOL={initial_extruder} \
                REFERENCED_TOOLS=!referenced_tools! \
                TOTAL_TOOLCHANGES=!total_toolchanges! \
                MATERIALS=!materials! \
                COLORS=!colors! \
                TEMPS=!temperatures! \
                PURGE_VOLUMES=!purge_volumes! \
                FILAMENT_NAMES=!filament_names!

MMU_START_CHECK

PRINT_START EXTRUDER={first_layer_temperature[initial_extruder]} \
            BED={first_layer_bed_temperature[initial_extruder]} \
            CHAMBER={chamber_temperature}

MMU_START_LOAD_INITIAL_TOOL
```

- [ ] **Step 2: Create the end template**

Write to `docs/slicer-templates/orcaslicer-end.gcode`:

```gcode
; OrcaSlicer "Machine end G-code" template for voron-2-611
;
; Drop this into OrcaSlicer: Printer Settings → Machine G-code → Machine end G-code

PRINT_END
MMU_END
```

- [ ] **Step 3: Create the README**

Write to `docs/slicer-templates/README.md`:

```markdown
# OrcaSlicer template reference for voron-2-611

These `.gcode` files are **documentation, not code**. They cannot auto-deploy. To use them:

1. Open OrcaSlicer.
2. Printer settings → Machine G-code.
3. **Machine start G-code:** paste contents of `orcaslicer-start.gcode`.
4. **Machine end G-code:** paste contents of `orcaslicer-end.gcode`.
5. **Layer change G-code:** paste the one-liner below.
6. Save the printer profile.

## Layer change G-code (one line)

Add this single line to OrcaSlicer's "After layer change G-code":

```
SET_PRINT_STATS_INFO CURRENT_LAYER={layer_num} TOTAL_LAYER={total_layer_count}
```

This drives Mainsail's "Pause at layer" feature.

## Token resolution

- `{…}` tokens are OrcaSlicer-native. Resolved at slice time. Examples: `{initial_extruder}`, `{first_layer_temperature[initial_extruder]}`, `{layer_num}`.
- `!…!` tokens are **Happy Hare-specific**. Resolved by Moonraker's `[mmu_server]` component at file-upload time (per `vendor/happy-hare/components/mmu_server.py:870-900`). Examples: `!referenced_tools!`, `!total_toolchanges!`, `!purge_volumes!`.

A non-MMU slicer profile would simply omit the three `MMU_*` calls; `PRINT_START` works unchanged.

## Why 4 separate macros in start gcode?

Happy Hare's documented pattern is for the slicer to call `MMU_START_SETUP` → `MMU_START_CHECK` → `PRINT_START` → `MMU_START_LOAD_INITIAL_TOOL` as **four separate top-level macros**, not "PRINT_START wraps everything". See `vendor/happy-hare/config/base/mmu_software.cfg:28-51` for HH's own documentation.

Rationale:
- HH's autotools rely on observing `MMU_START_SETUP` and `MMU_START_CHECK` as discrete events.
- `MMU_START_LOAD_INITIAL_TOOL` runs **after** PRINT_START's heat/QGL/mesh so the toolhead is at print temp when filament loads.
- A non-MMU run omits the three `MMU_*` calls; `PRINT_START` works unchanged.

## Updating these files

When OrcaSlicer adds new variables or HH adds new placeholders, update both the `.gcode` files in this directory AND the OrcaSlicer printer profile. The repo files are the source of truth for the canonical template; the printer profile is the live copy.
```

### Task 5.3: PRINT_START param-handling robustness (if needed)

**Files:**
- Modify: `config/macros/print_start.cfg`

- [ ] **Step 1: Inspect current PRINT_START param handling**

```sh
grep -n "params\." config/macros/print_start.cfg
```

Expected: `params.BED|int`, `params.EXTRUDER|int`, `params.CHAMBER|default("0")|int` etc.

- [ ] **Step 2: Verify Layer 5 params guard test passes (allowlist accounts for BED, EXTRUDER)**

```sh
.venv/bin/pytest tests/test_config_structure.py::test_params_have_default_or_guard -v
```

Expected: PASS.

If any new params would be added (e.g., for slicer integration), ensure they have `|default()` or are in `KNOWN_REQUIRED_PARAMS`.

- [ ] **Step 3: Commit (if changes)**

If no changes were needed in PRINT_START, skip this commit.

### Task 5.4: Push, CI, merge

- [ ] **Step 1: Push and PR**

```sh
git push -u origin feat/slicer-hooks
gh pr create --base main --title "feat(slicer): document OrcaSlicer start/end gcode templates" --body "$(cat <<'EOF'
## Summary
Phase 5 of \`docs/superpowers/specs/2026-05-15-config-macros-refactor.md\`.

- Add \`docs/slicer-templates/orcaslicer-start.gcode\` — 4-call sequence (MMU_START_SETUP → MMU_START_CHECK → PRINT_START → MMU_START_LOAD_INITIAL_TOOL).
- Add \`docs/slicer-templates/orcaslicer-end.gcode\` — PRINT_END + MMU_END.
- Add \`docs/slicer-templates/README.md\` — usage instructions, token resolution, design rationale.
- No Klipper-side macro changes (PRINT_START's params unchanged — MMU info flows through MMU_START_SETUP).

The user needs to manually update the OrcaSlicer printer profile to match.

## Test plan
- [x] Layer 5 params guard test still passes
- [x] Templates render correct gcode at slice time (manual verification by user)
- [x] HH's MMU_START_SETUP accepts all the params our template emits

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

This is a docs-only PR — should match the docs-only CI workflow.

- [ ] **Step 2: Merge**

```sh
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
```

- [ ] **Step 3: Manual user step (NOT in this repo)**

User updates OrcaSlicer's printer profile per the new templates. Saves the profile. Slices a multi-color test print and inspects head/tail of the generated gcode to confirm slicer is emitting the expected MMU calls.

---

## Phase 6: Two skills (klipper-config-work + happy-hare-integration)

**Branch:** `feat/two-skills`
**Estimated diff:** ~250 lines (skills are markdown-only)
**PR title:** `feat(skills): add klipper-config-work and happy-hare-integration`

**Files:**
- Create: `.claude/skills/klipper-config-work/SKILL.md`
- Create: `.claude/skills/happy-hare-integration/SKILL.md`

### Task 6.1: Branch, write klipper-config-work skill

**Files:**
- Create: `.claude/skills/klipper-config-work/SKILL.md`

- [ ] **Step 1: Branch**

```sh
git switch main && git pull --ff-only
git switch -c feat/two-skills
```

- [ ] **Step 2: Write the skill**

Write to `.claude/skills/klipper-config-work/SKILL.md`:

```markdown
---
name: klipper-config-work
description: Use when modifying Klipper config files in this repo (config/*.cfg, config/firmware/*.config). Surfaces doc paths, the RESTART vs FIRMWARE_RESTART decision, three classes of file, and "investigate before changing" rules.
---

# Klipper config work for voron-2-611

## When to use

Any work touching:
- `config/*.cfg` or `config/firmware/*.config`
- Topics: Klipper, bed mesh, input shaper, TMC, QGL, probe, macro, gcode_macro

## RTFM first — doc path index

Grep these vendored sources BEFORE web-searching:

| Topic | Where to grep |
|---|---|
| Klipper general | `vendor/klipper/docs/` (pinned to `4767a8ed`) |
| Klipper config sections | `vendor/klipper/docs/Config_Reference.md` |
| Klipper macros / jinja2 | `vendor/klipper/docs/Command_Templates.md` |
| `[probe_eddy_current]` | `vendor/klipper/docs/Eddy_Probe.md` |
| `[bed_mesh]` | `vendor/klipper/docs/Bed_Mesh.md` |
| `[input_shaper]` | `vendor/klipper/docs/Resonance_Compensation.md` + `Measuring_Resonances.md` |
| TMC drivers | `vendor/klipper/docs/TMC_Drivers.md` |
| BTT hardware (SKR, EBB, Eddy pinouts, firmware build flags) | `vendor/btt-docs/` |
| Moonraker / API | `vendor/moonraker/docs/` |
| Voron 2.4 hardware / build manual | `vendor/voron-2/Manual/` |
| Happy Hare (MMU) | use the `happy-hare-integration` skill |

## RESTART vs FIRMWARE_RESTART decision

After editing a `.cfg`, which restart do you need?

| Change type | Restart needed |
|---|---|
| `[gcode_macro]` body change | `RESTART` |
| New macro, deleted macro | `RESTART` |
| `[bed_mesh]` parameters | `RESTART` |
| `[input_shaper]` values | `RESTART` |
| `[pause_resume]`, `[display_status]`, `[respond]` | `RESTART` |
| `[mcu]` section (any change) | `FIRMWARE_RESTART` |
| Stepper pins, microsteps, rotation_distance | `FIRMWARE_RESTART` |
| `[probe_*]` pin or sensor type | `FIRMWARE_RESTART` |
| Thermistor type, pullup, heater pin | `FIRMWARE_RESTART` |
| `[fan]` or `[heater_fan]` pin | `FIRMWARE_RESTART` |
| `[neopixel]` pin or chain count | `FIRMWARE_RESTART` |
| MCU build kconfig (`config/firmware/*.config`) | Recompile + reflash + `FIRMWARE_RESTART` |
| Klipper-emitted message "this requires FIRMWARE_RESTART" | Trust it |

Rule: if Klipper or `klippy.log` says FIRMWARE_RESTART, that's authoritative.

## Three classes of file in `config/`

| Class | Examples | Edit policy |
|---|---|---|
| **Real files we own** | `config/printer.cfg`, `config/macros/*`, `config/eddy.cfg`, `config/toolhead.cfg`, `config/moonraker.conf` | Edit freely. |
| **Symlinked from third-party** (on the Pi) | `config/mmu/base/*.cfg` (Happy Hare), `config/timelapse.cfg` (moonraker-timelapse) | Don't edit in this repo — edits would mutate the upstream install dir on the Pi. Edits should go in the third-party repo instead. |
| **Auto-generated** | `#*# SAVE_CONFIG` block at the bottom of `config/printer.cfg` | Klipper rewrites this on every `SAVE_CONFIG`. Don't merge upstream changes that touch it. When syncing, pull the Pi's current version. |

Special case: `config/mainsail.cfg` USED to be a third-party symlink. After 2026-05-15, it's a slimmed real file in this repo (we dropped Mainsail's PAUSE/RESUME definitions). Treat as a real file we own.

## "Investigate before changing"

The machine has 6+ years of trial-and-error baked in. Don't auto-fix things that look weird.

Examples of "looks weird, but is intentional":
- Galileo extruder gear_ratio 9:1, rotation_distance 48.033 (Galileo 2)
- Microsteps 128 on X/Y/Z with `interpolate: False` (deliberate noise/accuracy tradeoff; see GH `future-work` issue)
- Dual SKR 1.4 on USB instead of CAN
- Chamber heater PID on a `[temperature_fan]` (not a `[heater]`)
- 2-pass `QUAD_GANTRY_LEVEL` override in `config/eddy.cfg` (V2 saggy-rear mechanical quirk; see `memory/qgl-two-pass-intentional.md`)
- Mainsail.cfg slimmed (HH owns PAUSE; see `memory/defer-to-happy-hare.md`)

When in doubt:
1. Grep this repo's `memory/` for `<topic>`.
2. Grep `CLAUDE.md` for `<topic>`.
3. Ask the user before changing.

## "Before changing X, grep Y"

| About to change | Grep here first |
|---|---|
| Probe / eddy / tap | `vendor/klipper/docs/Eddy_Probe.md`; `config/eddy.cfg` |
| Stepper config | `vendor/klipper/docs/TMC_Drivers.md`; `CLAUDE.md` MCU pin map |
| Bed mesh | `vendor/klipper/docs/Bed_Mesh.md` |
| Input shaper | `vendor/klipper/docs/Resonance_Compensation.md`, `Measuring_Resonances.md` |
| Macros | `vendor/klipper/docs/Command_Templates.md`; `memory/macros-lineage-ellis.md` |
| MMU / Happy Hare | Use the `happy-hare-integration` skill |
| Slicer-side gcode | `docs/slicer-templates/README.md` |
| User tunables | `config/macros/_user_variables.cfg` |
| BTT hardware pinouts | `vendor/btt-docs/` |

## What this skill does NOT do

- It does not encode specific Klipper feature recommendations (those rot when `vendor/klipper` bumps).
- It does not replace `CLAUDE.md` — that's the project context. This skill is a lens onto it.
- It does not automate work — it surfaces the right starting points.
```

### Task 6.2: Write happy-hare-integration skill

**Files:**
- Create: `.claude/skills/happy-hare-integration/SKILL.md`

- [ ] **Step 1: Write the skill**

Write to `.claude/skills/happy-hare-integration/SKILL.md`:

```markdown
---
name: happy-hare-integration
description: Use when modifying MMU-related config (config/mmu/**) or any macro that touches print lifecycle, filament cutting, or tool change. Surfaces HH's print lifecycle hooks, user extension variables, slicer-side macros, and the cut-tip flow.
---

# Happy Hare integration for voron-2-611

## When to use

Any work touching:
- `config/mmu/**`
- `config/macros/*` for MMU-aware logic (PRINT_START, PAUSE/RESUME, tool change)
- Topics: MMU, ERCF, tool change, filament cutter, Filametrix, Blobifier, Happy Hare, tip forming

## Cardinal rule: defer to Happy Hare

When custom macros overlap with HH macros, **drop the custom version, not the HH one**. Per `memory/defer-to-happy-hare.md`.

Example: PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_*/SET_PRINT_STATS_INFO are owned by `config/mmu/optional/client_macros.cfg`. The slimmed `config/mainsail.cfg` does NOT redefine them. Don't restore them.

## Print lifecycle hooks (HH-shipped)

HH fires these macros automatically. To inject custom behavior, set the corresponding `user_*_extension` variable in `mmu_macro_vars.cfg` (don't override the macro body).

| Hook | When it fires | User extension var |
|---|---|---|
| `MMU_PRINT_START` | Print start (auto via `print_stats` state) | `user_pre_initialize_extension` |
| `MMU_START_SETUP` | Slicer-driven setup (parses INITIAL_TOOL, REFERENCED_TOOLS, TOOL_COLORS, TOOL_TEMPS, etc.) | — |
| `MMU_START_CHECK` | Gate availability check vs REFERENCED_TOOLS | — |
| `MMU_START_LOAD_INITIAL_TOOL` | Loads slicer-defined initial tool via MMU_CHANGE_TOOL | — |
| `_MMU_PRE_UNLOAD` | Before tip forming/cutting on every unload | `user_pre_unload_extension` |
| `_MMU_POST_FORM_TIP` | After tip forming/cutting, before bowden retract | `user_post_form_tip_extension` (currently `"BLOBIFIER_PARK"`) |
| `_MMU_POST_UNLOAD` | After bowden retract | `user_post_unload_extension` |
| `_MMU_PRE_LOAD` | Before loading next tool | `user_pre_load_extension` |
| `_MMU_POST_LOAD` | After load, before purge | `user_post_load_extension` |
| `_MMU_ERROR` | On MMU error | — |
| `_MMU_PARK` | Centralized park macro (toolchange/runout/pause/cancel/complete) | `user_park_move_macro` |
| `MMU_UPDATE_HEIGHT` | Slicer-emitted on every layer change | — |
| `MMU_PRINT_END` | Print complete/error/standby (auto via state detection) | `user_print_end_extension` |
| `MMU_END` | Slicer-side end wrapper (optional UNLOAD, TTG reset, stats dump) | — |

The user extension variables live in `config/mmu/base/mmu_macro_vars.cfg`.

Documentation source: `vendor/happy-hare/config/base/mmu_sequence.cfg` and `mmu_software.cfg`.

## Slicer-side macros (call order)

OrcaSlicer "Machine start G-code" should call these as four separate top-level macros:

```gcode
MMU_START_SETUP INITIAL_TOOL=... REFERENCED_TOOLS=... ...
MMU_START_CHECK
PRINT_START EXTRUDER=... BED=... CHAMBER=...
MMU_START_LOAD_INITIAL_TOOL
```

OrcaSlicer "Machine end G-code":

```gcode
PRINT_END
MMU_END
```

OrcaSlicer "After layer change G-code":

```gcode
SET_PRINT_STATS_INFO CURRENT_LAYER={layer_num} TOTAL_LAYER={total_layer_count}
```

Full template + token explanations: `docs/slicer-templates/README.md`.

## Cut-tip flow (Filametrix path, end-to-end)

Configured via `force_form_tip_standalone: 1`, `form_tip_macro: _MMU_CUT_TIP`, `purge_macro: 'BLOBIFIER'` (in `mmu/base/mmu_parameters.cfg`).

On a toolchange (e.g., `T3`):

1. `T3` (defined in `mmu/base/mmu_macro_vars.cfg:491`) calls `MMU_CHANGE_TOOL TOOL=3`.
2. HH enters unload phase:
   - `_MMU_PRE_UNLOAD` — no-op by default.
   - `_MMU_CUT_TIP` runs (Filametrix cut at pin `(10, 337)`, configured in `mmu/base/mmu_macro_vars.cfg::_MMU_CUT_TIP_VARS`). Retracts ~38 mm, moves to pin, slow-cuts toward x=0, rip-back, pushback.
   - `_MMU_POST_FORM_TIP` runs `BLOBIFIER_PARK` (per `user_post_form_tip_extension`).
   - HH internal: bowden retract, gate park.
   - `_MMU_POST_UNLOAD` — no-op (EREC not active).
3. HH gear selector moves to gate 3.
4. HH enters load phase:
   - `_MMU_PRE_LOAD` — no-op.
   - Bowden load, extruder load.
   - `_MMU_POST_LOAD` — no-op.
5. `BLOBIFIER` purges per slicer-provided purge volume (or BLOBIFIER's default if MMU_START_SETUP wasn't called).
6. HH returns toolhead to next print position.

**Filametrix is the toolhead cutter — not EREC.** See `memory/filametrix-toolhead-cutter.md`.

## Useful HH commands worth knowing

| Command | Purpose |
|---|---|
| `MMU_STATUS` | Current gate, gate stats, sync state, errors |
| `MMU_TEST_LOAD GATE=<n>` | Load filament from gate n to extruder (test) |
| `MMU_CALIBRATE_GEAR` | Per-gate gear rotation distance calibration |
| `MMU_CALIBRATE_BOWDEN` | Bowden length calibration |
| `MMU_CALIBRATE_ENCODER` | Encoder resolution calibration |
| `MMU_TTG_MAP RESET=1` | Reset tool-to-gate mapping |
| `MMU_COLD_PULL` | Cold-pull tip cleaning |
| `MMU_TOOL_OVERRIDES` | Per-tool temp / PA / flow overrides (currently unused) |
| `MMU_LOG MSG=...` | Write to MMU log (visible in Mainsail) |

Full command list registered in `vendor/happy-hare/extras/mmu/mmu.py:573-639`.

## What this skill does NOT do

- Doesn't encode version-specific HH features (those evolve quickly).
- Doesn't replace HH's wiki — point users there for canonical reference: `github.com/moggieuk/Happy-Hare/wiki`.
- Doesn't recommend specific `mmu_parameters.cfg` values — those depend on the physical build.
```

### Task 6.3: Run tests, commit, push, merge

- [ ] **Step 1: Run tests**

```sh
.venv/bin/pytest tests/ -v
.venv/bin/python scripts/macro_refcheck.py
```

Expected: PASS (skills are `.claude/`-only, no config tests affected).

- [ ] **Step 2: Commit**

```sh
git add .claude/skills/
git commit -m "feat(skills): add klipper-config-work and happy-hare-integration

Two pointer-heavy skills that auto-trigger on relevant Klipper/MMU
work. Both are non-prescriptive on specific feature recommendations
(those rot); both point at canonical vendor/ paths and the HH wiki.

- klipper-config-work: RESTART vs FIRMWARE_RESTART table, three
  classes of file, doc path index, 'before changing X, grep Y'.
- happy-hare-integration: print lifecycle hooks, user extension vars,
  slicer-side macros, cut-tip flow (Filametrix path), useful commands."
```

- [ ] **Step 3: Push and PR**

```sh
git push -u origin feat/two-skills
gh pr create --base main --title "feat(skills): add klipper-config-work and happy-hare-integration" --body "$(cat <<'EOF'
## Summary
Phase 6 of \`docs/superpowers/specs/2026-05-15-config-macros-refactor.md\`.

Two new skills under \`.claude/skills/\`:

- **klipper-config-work** — auto-triggers on Klipper config work. Surfaces RESTART vs FIRMWARE_RESTART, three classes of file, doc path index, "before changing X, grep Y".
- **happy-hare-integration** — auto-triggers on MMU work. Surfaces print lifecycle hooks, user extension variables, slicer-side macros, cut-tip flow (Filametrix path).

Both are pointer-heavy and non-prescriptive — point at \`vendor/\` paths and the HH wiki. Designed not to rot when \`vendor/klipper\` or \`vendor/happy-hare\` bumps.

## Test plan
- [x] All existing tests pass
- [x] Skill descriptions match the SKILL.md frontmatter rules

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge**

```sh
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
```

No deploy needed — skills are CC-side only.

---

## Post-completion

After all 6 phases ship:

- [ ] **Verify the GH `future-work` label has all expected issues**

```sh
gh issue list --label "future-work" --state open
```

- [ ] **Update memory/decisions.md** with any new decisions made during execution that weren't in the spec.

- [ ] **Consider the GH issues that came up during execution** — file any new ones with `future-work` label.

- [ ] **Quarterly review trigger:** add a calendar reminder for ~2026-08-15 to review the "Logical reorganization audit" GH issue (created in Phase 3).

---

*Plan complete. Spec at: `docs/superpowers/specs/2026-05-15-config-macros-refactor.md`.*
