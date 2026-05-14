# Eddy-NG → Native Klipper Eddy Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `vvuk/eddy-ng` Klipper probe extension with upstream Klipper's native `[probe_eddy_current]` + `[ldc1612]` on Voron 2.611, preserving the tap-at-print-start workflow.

**Architecture:** In-place rewrite of `config/eddy.cfg` on a `feat/eddy-native` git worktree. Surgical two-line edit to `config/macros/print_start.cfg`. SAVE_CONFIG cleanup in `config/printer.cfg`. Deploy via `/deploy-to-pi` skill + `scripts/deploy_to_pi.sh` (8 safety gates; requires CI green on `origin/main`). Hands-on calibration at the printer (bed 60 °C, hotend 200 °C). `pr-review-toolkit:review-pr` runs before merge to `main`.

**Tech Stack:** Klipper `0.13.0-649-g4767a8ed` (master, pinned per `vendor/klipper`), Moonraker `v0.10.0-19`, Mainsail, SSH to Pi, `scripts/deploy_to_pi.sh`. No code-language tests — verification is deploy-to-pi reporting Klipper ready + calibration step success + printed-part quality.

**Spec:** `docs/superpowers/specs/2026-05-13-eddy-ng-to-native-migration.md` (commit `fc79190`).

---

## File structure (what changes, what doesn't)

**Modified in this repo (on `feat/eddy-native` worktree):**

| File | Scope of change | Reason |
|---|---|---|
| `config/eddy.cfg` | Full rewrite of the probe section. Replace `[probe_eddy_ng btt_eddy]` with `[probe_eddy_current btt_eddy]` (+ `[ldc1612 btt_eddy]` if required by the pinned Klipper commit). Preserve `[mcu eddy]`, both `[temperature_sensor]`s, `[bed_mesh]`, `[safe_z_home]`, `[force_move]`, and both `[gcode_macro ...]` overrides byte-for-byte. | Spec §5.1 |
| `config/macros/print_start.cfg` | Line 67: `PROBE_EDDY_NG_TAP` → `G28 Z METHOD=tap` (with documented fallback). Line 93: delete `PROBE_EDDY_NG_SET_TAP_OFFSET VALUE=0`. | Spec §5.2 |
| `config/printer.cfg` | Delete the `#*# [probe_eddy_ng btt_eddy]` block in SAVE_CONFIG (currently lines ~463-469). Leave every other SAVE_CONFIG entry untouched. | Spec §5.3 |
| `memory/tuning-log.md` | Append a 2026-05-13 entry with new calibration values pulled back from the Pi's `printer.cfg` after step 6. | Spec §6 verification + project convention |

**Unchanged (verified by grep for `eddy_?ng|probe_eddy_ng`):**
`config/btt-ebb-sb-usb-v1.0.cfg`, `config/mainsail.cfg`, `config/timelapse.cfg`, `config/moonraker.conf`, `config/crowsnest.conf`, `config/sonar.conf`, `config/firmware/*.config`, all of `config/mmu/*`, `config/macros/{macros,bedfans,lcd_tweaks,test_speed,calibrate_*}.cfg`.

**Pi-side state (not in repo, but mutated):**
- `~/printer_data/config/*.cfg` — overwritten by deploy-to-pi rsync from the worktree.
- `~/printer_data/logs/klippy.log` — append-only, used as the "test output."
- `~/eddy-ng/` and `~/klipper/klippy/extras/probe_eddy_ng.py` (symlink) — **untouched**. eddy-ng install dir stays in place; rollback path depends on this. Cleanup is a separate spec.

---

## Pre-flight assumptions (must hold before starting)

- Ben is at the printer or can be within ~10 minutes for the calibration session.
- `ssh pi@mainsailos.local` works without password (set up 2026-05-13).
- Current `printer.cfg` on the Pi matches what's in this repo at `main` HEAD. If divergent, **stop and resync repo from Pi first** (one-time `scp pi@mainsailos.local:'~/printer_data/config/*' /tmp/voron-snap/` and diff).
- `main` branch is clean (`git status -sb` reports no working-tree changes and a clean staging area).

---

## Task 1: Set up isolated worktree

**Files:** none yet (creating the worktree).

- [ ] **Step 1: Invoke the `using-git-worktrees` skill**

The skill is required before any implementation. It will detect existing isolation, use the native `EnterWorktree` tool, and verify clean baseline.

```
Skill: superpowers:using-git-worktrees
```

Expected: the skill announces "I'm using the using-git-worktrees skill...", detects we're in a normal repo (not already a worktree, not a submodule), calls `EnterWorktree` (or its plugin-namespaced equivalent) with branch name `feat/eddy-native`.

- [ ] **Step 2: Verify the worktree is on the new branch**

```sh
git branch --show-current
```
Expected: `feat/eddy-native`

```sh
git log --oneline -1
```
Expected: same commit as `main` HEAD (the worktree starts from main).

- [ ] **Step 3: Verify clean baseline**

```sh
git status -sb
```
Expected: `## feat/eddy-native` and **no other lines** (clean working tree).

The "tests" for this domain don't exist as code — there's no `npm test` or `pytest` to run. Baseline cleanliness is the closest equivalent.

- [ ] **Step 4: Confirm SSH to Pi still works from the worktree**

```sh
ssh pi@mainsailos.local 'hostname && uptime'
```
Expected: `mainsailos` + a recent uptime line, **no password prompt**.

If a password is prompted, stop and fix SSH key auth before proceeding.

---

## Task 2: Resolve "verify-on-implementation" questions from the spec

**Files:** none modified — this is research that informs Task 3.

- [ ] **Step 1: Find the correct `intb_pin` value for the BTT Eddy board**

```sh
grep -rin "intb\|probe_eddy_current\|BTT Eddy" vendor/btt-docs/docs/Eddy.md vendor/btt-docs/docs/
```

Expected: at least one match like `intb_pin: eddy:gpio10` (or similar) with surrounding context. Note the exact pin name for Task 3.

If `vendor/btt-docs/docs/Eddy.md` doesn't include a Klipper config example, fall back to the eddy-ng config we're replacing (look at `vendor/klipper/klippy/extras/ldc1612.py` for the parameter name) and grep the Klipper docs:

```sh
grep -rin "intb_pin" vendor/klipper/docs/ vendor/klipper/klippy/extras/ldc1612.py
```

- [ ] **Step 2: Determine if `[ldc1612 btt_eddy]` is required separately**

```sh
grep -nE "^class .*config|register.*ldc1612" vendor/klipper/klippy/extras/ldc1612.py
grep -nE "ldc1612|sensor_type" vendor/klipper/klippy/extras/probe_eddy_current.py | head -20
```

Look at how `probe_eddy_current.py` references the sensor. Two possibilities:
- It accepts `sensor_type: ldc1612` inline (single section, no separate `[ldc1612]`)
- It requires a separate `[ldc1612 <name>]` section by the same name

Document which one the pinned commit uses. The spec's §5.1 example shows both blocks; this step confirms whether that's required or optional.

- [ ] **Step 3: Verify `G28 Z METHOD=tap` syntax works in our pinned Klipper**

```sh
grep -nE "METHOD|cmd_G28|register.*G28" vendor/klipper/klippy/extras/probe.py vendor/klipper/klippy/extras/homing.py | head -20
grep -nE "METHOD=tap|method.*tap" vendor/klipper/docs/Eddy_Probe.md vendor/klipper/docs/Probe.md 2>/dev/null | head -10
```

Look for whether `G28` accepts a `METHOD` parameter. If it does, `G28 Z METHOD=tap` is fine. If not, the spec's fallback applies:

```
PROBE METHOD=tap
SET_KINEMATIC_POSITION Z={printer.probe.last_z_result}
```

Document which form is correct for our pinned commit.

- [ ] **Step 4: Find one working community config to reference**

Per Ben's "look for popular working examples" guidance, find a Voron 2.4 + BTT Eddy + native `[probe_eddy_current]` config on GitHub. Use WebSearch or WebFetch:

```
WebSearch: voron 2.4 "probe_eddy_current btt_eddy" filetype:cfg site:github.com
```

Pick one well-starred / well-maintained user config. Open it. Note:
- The exact section headers they use (`[probe_eddy_current ...]`, `[ldc1612 ...]`)
- Their `intb_pin` value (cross-check with Step 1)
- Their `descend_z` and `tap_threshold` initial values
- Their PRINT_START tap pattern

Record the source repo URL + commit hash. This citation goes into the eventual commit message ("References: github.com/<user>/<repo>@<sha>").

- [ ] **Step 5: Record findings**

Write a temporary scratchpad to `docs/superpowers/plans/eddy-prep-notes.md` (this file is committed at end of Task 6 as part of the work, then removed before merge). Use this format:

```markdown
# Eddy migration prep notes (delete before merge)

- intb_pin value: `<value>`  (source: vendor/btt-docs/docs/<file>:<line>)
- [ldc1612 btt_eddy] required separately?: yes/no  (source: vendor/klipper/klippy/extras/probe_eddy_current.py:<line>)
- G28 Z METHOD=tap supported?: yes/no  (source: vendor/klipper/klippy/extras/probe.py:<line>)
- Community reference: https://github.com/<user>/<repo>/blob/<sha>/eddy.cfg
- Notes from community config:
  - <observation 1>
  - <observation 2>
```

---

## Task 3: Rewrite `config/eddy.cfg`

**Files:**
- Modify: `config/eddy.cfg` (whole-file replacement of the probe section; other sections preserved byte-for-byte)

- [ ] **Step 1: Snapshot the current `config/eddy.cfg` for diff comparison**

```sh
cp config/eddy.cfg /tmp/eddy.cfg.before
```

This is for visual diff inspection during Step 4, not for rollback (git handles that).

- [ ] **Step 2: Open `config/eddy.cfg` and edit in place**

Replace the entire `[probe_eddy_ng btt_eddy]` block (currently lines 5-12) with the native equivalent. Use the values you recorded in Task 2.

Replacement block — substitute `<intb_pin>` with the value from Task 2 Step 1, and include or omit the `[ldc1612 btt_eddy]` block per Task 2 Step 2:

```ini
[ldc1612 btt_eddy]
intb_pin: <intb_pin>
i2c_mcu: eddy
i2c_bus: i2c0f

[probe_eddy_current btt_eddy]
sensor_type: ldc1612
x_offset: 0
y_offset: 21.42
descend_z: 0.5
# tap_threshold gets written by PROBE_EDDY_CURRENT_TAP_CALIBRATE
```

If Task 2 Step 2 determined `[ldc1612 btt_eddy]` is NOT a separate section in our pinned commit, drop the `[ldc1612 ...]` block and use whatever inline form the source confirmed.

- [ ] **Step 3: Delete the eddy-ng-only commented blocks at the bottom**

Lines 60-145 of the current `config/eddy.cfg` contain commented-out `# Uncomment if using Eddy as probe AND endstop AND beta z-offset control` blocks (`G28` override, `SET_Z_FROM_PROBE`, `Z_OFFSET_APPLY_PROBE`, etc). These are eddy-ng scaffolding for features native folds in automatically. Delete them in their entirety.

- [ ] **Step 4: Verify everything else in `config/eddy.cfg` is preserved byte-for-byte**

```sh
diff /tmp/eddy.cfg.before config/eddy.cfg
```

The diff should show:
- The 8-line `[probe_eddy_ng btt_eddy]` block removed
- The new `[ldc1612]` / `[probe_eddy_current]` block(s) added
- The 80+ commented-out scaffolding lines at the bottom removed
- **Nothing else changed** — `[mcu eddy]`, both `[temperature_sensor]`s, `[bed_mesh]`, `[safe_z_home]`, `[force_move]`, both `[gcode_macro ...]` overrides identical

In particular, the `QUAD_GANTRY_LEVEL` override must remain byte-for-byte (the two-pass `horizontal_move_z=8` + `horizontal_move_z=2` is the saggy-rear workaround — see `memory/v24-saggy-rear-qgl.md`).

If the diff shows changes anywhere else, undo them and re-diff before continuing.

---

## Task 4: Update `config/macros/print_start.cfg`

**Files:**
- Modify: `config/macros/print_start.cfg:67` and `config/macros/print_start.cfg:93`

- [ ] **Step 1: Replace the tap call on line 67**

Current line 67:
```
  PROBE_EDDY_NG_TAP
```

Replace with the form determined in Task 2 Step 3.

If `G28 Z METHOD=tap` is supported:
```
  G28 Z METHOD=tap
```

If the fallback applies:
```
  PROBE METHOD=tap
  SET_KINEMATIC_POSITION Z={printer.probe.last_z_result}
```

- [ ] **Step 2: Delete the obsolete `SET_TAP_OFFSET` call on line 93**

Current line 93 (inside `PRINT_END`):
```
    PROBE_EDDY_NG_SET_TAP_OFFSET VALUE=0
```

Delete this line. Native doesn't accumulate a runtime tap offset, so there's nothing to zero.

- [ ] **Step 3: Verify the surrounding flow still parses as expected**

```sh
grep -nE "PROBE_EDDY|METHOD=tap|SET_KINEMATIC" config/macros/print_start.cfg
```

Expected: matches only on the new lines from Step 1. No `PROBE_EDDY_NG_*` references remain.

```sh
grep -rin "PROBE_EDDY_NG" --include='*.cfg' .
```

Expected: only matches in `archive/` (which is intentionally not included by `config/printer.cfg`).

---

## Task 5: Strip stale SAVE_CONFIG block from `config/printer.cfg`

**Files:**
- Modify: `config/printer.cfg` (the SAVE_CONFIG section at the bottom)

- [ ] **Step 1: Locate the stale block**

```sh
grep -n "#\*# \[probe_eddy_ng" config/printer.cfg
```

Expected: a line number around 463. Note the line number; the block starts there.

- [ ] **Step 2: Find the end of the block**

```sh
awk '/^#\*# \[probe_eddy_ng/,/^#\*# \[/{print NR": "$0}' config/printer.cfg | head -20
```

The block ends just before the next `#*# [` section header. Note both line numbers.

- [ ] **Step 3: Delete the block**

Edit `config/printer.cfg` and delete lines from the `#*# [probe_eddy_ng btt_eddy]` header through the last line of its content (the base64 `calibration_16 = ...` line). Stop before the next `#*# [<section>]` header.

- [ ] **Step 4: Confirm the rest of SAVE_CONFIG is intact**

```sh
grep -nE "^#\*# \[" config/printer.cfg
```

Expected to remain (no `probe_eddy_ng`):
- `#*# [heater_bed]`
- `#*# [extruder]`
- `#*# [input_shaper]`
- `#*# [bed_mesh Default2]`
- `#*# [bed_mesh default]`

If any of those are missing, undo the edit and try again — only the `probe_eddy_ng` block should be removed.

---

## Task 6: First commit, PR + merge, then deploy via deploy-to-pi

> **Workflow change vs original plan:** The `/deploy-to-pi` skill (added 2026-05-14 via PRs #5–#8) requires CI green on `origin/main` HEAD before it will push to the Pi. This means the `feat/eddy-native` branch **must be merged to `main` before the deploy step** — unlike the old raw-rsync flow which could push directly from a feature branch. The merge is step 4 of this task; deploy is steps 6–7.

**Files:**
- Commit on `feat/eddy-native` branch
- PR open + CI green + squash merge to `main`
- Deploy `config/` to Pi via `scripts/deploy_to_pi.sh`

- [ ] **Step 1: Review the diff**

```sh
git diff --stat
git diff config/eddy.cfg config/macros/print_start.cfg config/printer.cfg
```

Read the full diff. Confirm:
- `config/eddy.cfg`: probe section replaced, scaffolding deleted, nothing else touched
- `config/macros/print_start.cfg`: exactly 2 line changes (one replace, one delete)
- `config/printer.cfg`: only the `probe_eddy_ng` SAVE_CONFIG block removed

- [ ] **Step 2: Stage and commit**

```sh
git add config/eddy.cfg config/macros/print_start.cfg config/printer.cfg docs/superpowers/plans/eddy-prep-notes.md
git commit -m "$(cat <<'EOF'
feat(eddy): migrate from vvuk/eddy-ng to native [probe_eddy_current]

Replace third-party probe extension with upstream Klipper's native module.
Tap-at-print-start workflow preserved (G28 Z METHOD=tap or fallback per
prep notes). [mcu eddy], temperature sensors, bed_mesh, safe_z_home,
force_move, QUAD_GANTRY_LEVEL (two-pass saggy-rear preserved) and
BED_MESH_CALIBRATE overrides untouched.

Calibration to follow per docs/superpowers/specs/2026-05-13-eddy-ng-to-native-migration.md.

References:
- vendor/klipper/docs/Eddy_Probe.md
- vendor/klipper/klippy/extras/probe_eddy_current.py
- vendor/btt-docs/docs/Eddy.md
- Community: <repo URL from prep notes>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push the feat branch and open a draft PR**

```sh
git push -u origin feat/eddy-native
gh pr create --base main --head feat/eddy-native --draft \
  --title "feat(eddy): migrate from vvuk/eddy-ng to native [probe_eddy_current]" \
  --body "Replaces third-party probe extension with upstream Klipper's native module. See spec and prep notes for details."
```

Wait for CI to run and go green. The deploy-to-pi script requires CI green on `origin/main`, so CI must pass here before we can proceed.

- [ ] **Step 4: Merge to main (squash)**

Once CI is green on the draft PR, mark it ready and squash-merge:

```sh
gh pr merge --squash --delete-branch
```

- [ ] **Step 5: Sync local main**

```sh
git switch main && git pull --ff-only
```

- [ ] **Step 6: Dry-run the deploy**

```sh
bash scripts/deploy_to_pi.sh --dry-run
```

Verify all 8 gates pass against the real Pi. Confirm:
- The 3 changed files (`config/eddy.cfg`, `config/macros/print_start.cfg`, `config/printer.cfg`) appear in the rsync preview.
- Drift gate passes (since `main` now has the new versions).
- Restart kind = `firmware_restart` (the eddy migration touches MCU-impacting sections via `[ldc1612]` / `[probe_eddy_current]`).

If any gate fails, fix the reported issue before proceeding to the live deploy.

- [ ] **Step 7: Real deploy**

```sh
bash scripts/deploy_to_pi.sh --yes
```

The script will:
1. Capture the Pi's current SAVE_CONFIG block and splice it into the new `config/printer.cfg`.
2. rsync `config/` to the Pi (symlink-safe, no noise files).
3. Write `.last-deploy-sha` on the Pi.
4. Call `printer/firmware_restart` via Moonraker.
5. Poll `/printer/info` until `state=ready` (timeout 60 s; exits 3 on timeout).

If the script exits non-zero, check the error message — it surfaces the specific gate or Moonraker call that failed.

---

## Task 7: Verify Klipper parsed the new config successfully

**Files:** none modified — observation only.

> **Note:** The firmware_restart and ready-polling were already performed by `deploy-to-pi` in Task 6 Step 7. If `deploy-to-pi` exited 0, Klipper is already up and parsing the new config.

- [ ] **Step 1: Confirm deploy-to-pi exited 0**

If Task 6 Step 7 reported success (exit 0), Klipper is parsing the new config. If it exited 3 (timeout), Klipper failed to come back — see klippy.log immediately.

- [ ] **Step 2: Tail klippy.log for warnings about the new sections**

```sh
ssh pi@mainsailos.local 'tail -60 ~/printer_data/logs/klippy.log'
```

Expected: no stack traces, no `Unknown config option`, no `pin clash`, no `Probe is required but missing`. Pay particular attention to the `[probe_eddy_current]` and `[ldc1612]` section loads.

Common failures:
- `Unknown config object 'ldc1612'` → revisit Task 2 Step 2 (the inline-vs-separate question)
- `Pin XXX used multiple times in config` → check the `intb_pin` value from Task 2 Step 1
- `Probe requires .. method ...` → revisit Task 4 Step 1 (the G28 METHOD=tap form)

If any error: **do not proceed**. Fix on a new `fix/eddy-*` branch, re-run Task 6's merge+deploy cycle, then retry this step.

- [ ] **Step 3: Verify all 5 MCUs are connected**

```sh
curl -s http://mainsailos.local:7125/printer/objects/query?mcu | python3 -m json.tool | grep '"state"'
```

Expected: 5 entries all showing `"state": "ready"` (for `mcu`, `z`, `EBB`, `eddy`, `mmu`).

---

## Task 8: Calibration session (hands-on at the printer)

**Files:** none in repo. SAVE_CONFIG entries appended to `~/printer_data/config/printer.cfg` on the Pi by each step.

**Pre-conditions:** Ben at the printer. Bed and toolhead clean. Filament unloaded or able to be retracted to clear the nozzle.

This is one task with sub-steps because the substeps are all interactive at the machine. Ben must confirm each substep before the next.

- [ ] **Step 1: Warmup**

In Mainsail console (or via SSH `echo 'M140 S60' | ...`):

```
M140 S60
M104 S200
```

Wait ~5 min for thermal equilibrium. While waiting, home the printer and park near center, sensor 20 mm above bed:

```
G28
G0 X175 Y175 Z20 F6000
```

Confirm both temperatures stable at target (±2 °C) before proceeding.

- [ ] **Step 2: Drive-current calibration**

```
LDC_CALIBRATE_DRIVE_CURRENT CHIP=btt_eddy
```

Wait ~5 seconds for completion. Expected output: a message reporting the chosen drive current value.

```
SAVE_CONFIG
```

Klipper restarts. Wait for ready (~6 sec). Re-park if needed:

```
G0 X175 Y175 Z20 F6000
```

- [ ] **Step 3: Z-height calibration (paper test)**

Re-confirm bed 60 °C, hotend 200 °C. Place a single sheet of paper between nozzle and bed.

```
PROBE_EDDY_CURRENT_CALIBRATE CHIP=btt_eddy
```

Follow the prompts (move the toolhead down with `TESTZ Z=-0.1`, etc.) until paper just barely catches — see `vendor/klipper/docs/Bed_Level.md` "the paper test". When the paper test is correct, run:

```
ACCEPT
```

Tool now runs ~2 min of automated frequency-to-Z mapping. Expected output ends with a line like:

```
probe_eddy_current: noise 0.000642mm, MAD_Hz=11.314 in 2525 queries
```

Note the `noise` and `MAD_Hz` values. If `noise > 0.005mm` or `MAD_Hz > 50`, the calibration is questionable — see `Eddy_Probe.md` troubleshooting and re-run.

```
SAVE_CONFIG
```

Klipper restarts. Re-park.

- [ ] **Step 4: Tap "guess"**

Re-confirm temperatures. Verify nozzle is clean (cold-pull or brush). Toolhead near center, nozzle 3–10 mm above bed. **Finger on M112 / EMERGENCY STOP in Mainsail.**

```
PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=guess
```

Probe descends, contacts bed, lifts away, reports a result. If probe rams into the bed without stopping, **press M112 immediately**.

```
SAVE_CONFIG
```

- [ ] **Step 5: Tap "refine"**

Re-park (sensor over center, 3-10 mm above bed). Confirm temps. **Finger on M112.**

```
PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=refine
```

Same protocol as guess.

```
SAVE_CONFIG
```

- [ ] **Step 6: Tap "verify"**

Re-park. **Finger on M112.**

```
PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=verify
```

This runs 5 taps in a row. Expected output: 5 z-result values close to each other (within ~0.005 mm of each other). If any of the 5 fails or stddev is poor, re-run from Step 4 with manual adjustments per `Eddy_Probe.md:344+`.

```
SAVE_CONFIG
```

- [ ] **Step 7: Note the saved values**

```sh
ssh pi@mainsailos.local 'awk "/^#\*# \[probe_eddy_current/,/^#\*# \\[/" ~/printer_data/config/printer.cfg | head -30'
```

Note the values written: `reg_drive_current`, `calibration` polynomial entries, `tap_threshold`. These get logged in `memory/tuning-log.md` at Task 10.

---

## Task 9: Smoke test (homes, levels, scans)

**Files:** none modified.

- [ ] **Step 1: Home all axes**

```
G28
```

Expected: completes without error. Z home uses the new Eddy probe.

- [ ] **Step 2: Quad gantry level**

```
QUAD_GANTRY_LEVEL
```

Expected: 2-pass behavior (first pass `horizontal_move_z=8` rough, then `horizontal_move_z=2` fine) converges within `retry_tolerance: 0.05` after ≤5 retries. Output shows "Gantry leveled" or equivalent.

- [ ] **Step 3: Rapid bed mesh scan**

```
BED_MESH_CALIBRATE METHOD=rapid_scan
```

Expected: completes a 9×9 scan in well under 1 minute, produces a mesh with no NaN values and no spikes >0.3 mm peak-to-peak (relative). Inspect via Mainsail's Bed Mesh visualization.

```
BED_MESH_CLEAR
```

- [ ] **Step 4: Inspect klippy.log for warnings**

```sh
ssh pi@mainsailos.local 'tail -100 ~/printer_data/logs/klippy.log | grep -iE "warn|error|fail"'
```

Expected: no probe-related errors or warnings. Some unrelated harmless warnings (e.g., `temperature_fan`) may appear; that's fine.

---

## Task 10: First-print test

**Files:**
- Modify: `memory/tuning-log.md` (after print succeeds)

- [ ] **Step 1: Pick the reference G-code**

Use Ben's usual quality-check part (the test print he prints when validating tuning changes). Standard candidates: a Voron test cube, calibration tower, recent successful print from history.

```sh
ssh pi@mainsailos.local 'ls -lt ~/printer_data/gcodes/*.gcode | head -10'
```

- [ ] **Step 2: Start the print via Mainsail**

Use Mainsail's web UI. Standard PRINT_START parameters per Ben's slicer profile.

- [ ] **Step 3: Observe the first layer**

Acceptance (Spec §7.2):
- First-layer adhesion qualitatively at least as good as the most recent successful print of the same G-code.
- No missed-step / stutter mid-print.
- Print completes without abort.

If first layer is noticeably worse: pause via Mainsail, check `klippy.log` for probe-related entries, and consider re-running Task 8 Step 6 with hand-adjusted `tap_threshold`.

- [ ] **Step 4: After print completes, pull updated SAVE_CONFIG back into the repo**

```sh
scp pi@mainsailos.local:~/printer_data/config/printer.cfg ./config/printer.cfg
git diff config/printer.cfg
```

Expected diff: SAVE_CONFIG section has new `[probe_eddy_current btt_eddy]` block with calibration values. No other lines changed.

- [ ] **Step 5: Update `memory/tuning-log.md`**

Prepend a new entry under `## 2026-05-13 — initial snapshot ...`:

```markdown
## 2026-05-NN — Eddy migration calibration (native [probe_eddy_current])

Migrated from vvuk/eddy-ng to upstream Klipper [probe_eddy_current]. Calibrated at bed 60 °C / hotend 200 °C.

- LDC drive current (auto): `<value>` from `LDC_CALIBRATE_DRIVE_CURRENT`
- Z-frequency map: noise `<value>` mm, MAD_Hz `<value>` (acceptable: noise < 0.005mm, MAD_Hz < 50)
- Tap threshold (after verify): `<value>`
- 5-tap verify stddev: `<value>` mm
- First-print quality vs last reference print: matches / better / worse — (commentary)

Old eddy-ng calibration removed from SAVE_CONFIG; the eddy-ng install directory at ~/eddy-ng remains on the Pi (cleanup is a separate spec).
```

Replace the angle-bracket placeholders with the real values you noted in Task 8 Step 7 and Task 10 Step 3.

- [ ] **Step 6: Commit the config/printer.cfg SAVE_CONFIG sync and the tuning log entry**

```sh
git add config/printer.cfg memory/tuning-log.md
git commit -m "$(cat <<'EOF'
feat(eddy): record native Eddy calibration results

- config/printer.cfg SAVE_CONFIG now contains [probe_eddy_current btt_eddy]
  values from on-machine calibration at bed 60°C / hotend 200°C
- memory/tuning-log.md updated with the new values for future reference

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Confirm migration end-to-end and close out

**Files:**
- Remove: `docs/superpowers/plans/eddy-prep-notes.md` (scratchpad cleanup, if not already done in Task 6 merge)

> **Note:** The PR-and-merge work already happened in Task 6. This task confirms the migration succeeded end-to-end after calibration, handles any post-calibration commits, and does final cleanup.

- [ ] **Step 1: Remove the prep-notes scratchpad (if still present)**

If `docs/superpowers/plans/eddy-prep-notes.md` was included in the Task 6 merge commit it's already gone. If it's still present:

```sh
git rm docs/superpowers/plans/eddy-prep-notes.md
git commit -m "chore(eddy): remove prep scratchpad after successful migration"
```

Push and open a follow-up PR (or include in the Task 10 commit above if timing allows).

- [ ] **Step 2: Push calibration commit(s) and merge**

The Task 10 Step 6 commit (SAVE_CONFIG sync + tuning log) needs to reach `main` via the same PR flow:

```sh
git push -u origin <branch>
gh pr create --base main ...
gh pr merge --squash --delete-branch
git switch main && git pull --ff-only
```

Optionally run `bash scripts/deploy_to_pi.sh --dry-run` after merge — it should report zero drift (Pi already has the calibration values from Task 8).

- [ ] **Step 3: Verify the migration succeeded**

```sh
bash scripts/deploy_to_pi.sh --dry-run
```

Expected: drift gate reports no config drift (Pi already in sync with `main`).

- [ ] **Step 4: Final klippy.log scan**

```sh
ssh pi@mainsailos.local 'grep -c "probe_eddy_ng" ~/printer_data/logs/klippy.log'
```

Expected: 0 (or only lines from the session before the migration — those are historical).

---

## Open follow-ups for separate specs (not done here)

These are explicitly out of scope per Spec §9, but worth noting for future work:

1. Cleanup pass: `~/eddy-ng/install.sh --uninstall` + remove `~/eddy-ng/` + verify `~/klipper/klippy/extras/` symlinks are gone.
2. Webcam re-enable (the original motivation behind unplugging it).
3. Re-running PID / input shaper / pressure advance / flow calibration ("stale tuning sweep").
4. CI / config-validation scaffold (already brainstormed separately).
5. Sensorless X investigation.
6. EBB USB → CAN migration.
7. Microsteps reassessment ("quiet without losing steps" — per Ben).

---

## Note added 2026-05-13 by ci-scaffold plan

The eddy migration must also remove these entries from
`scripts/macro_refcheck.py` ALLOWLIST (added by the ci-scaffold work)
in the same PR that removes the `[probe_eddy_ng]` block:

```python
"PROBE_EDDY_NG_TAP",
"PROBE_EDDY_NG_PROBE",
"PROBE_EDDY_NG_CALIBRATE",
"PROBE_EDDY_NG_STATUS",
"PROBE_EDDY_NG_SET_TAP_OFFSET",
```

If this step is skipped, the new CI scaffold will flag the unresolved
callers in `config/macros/print_start.cfg` — see acid test result in
`memory/troubleshooting-log.md` under "Resolved" (2026-05-13).

## Note added 2026-05-14 by ci-scaffold execution

While the CI scaffold was being implemented, the `klippy-smoke` job
was disabled (`if: false` in `.github/workflows/ci.yml`) because
`test_klippy.py` fails against `config/printer.cfg` while `[probe_eddy_ng]`
is active. Root cause: the committed `tests/dict/eddy.dict` doesn't
include `ldc1612_ng_*` MCU commands (the eddy-ng C extension wasn't
fully applied to the Pi's firmware build).

**The eddy migration PR must re-enable klippy-smoke**:
1. Remove `if: false` from the `klippy-smoke` job in `.github/workflows/ci.yml`.
2. Verify the new `[probe_eddy_current]` config uses vanilla `ldc1612_*`
   MCU commands which ARE present in eddy.dict.
3. If CI fails for any other reason after re-enable, investigate
   per `memory/troubleshooting-log.md` 2026-05-14.

## Note added 2026-05-14 by repo-reorg + deploy-to-pi shift

This plan was refreshed on 2026-05-14 after two major infrastructure changes landed:

1. **PR #10 (repo reorganization):** machine state moved from root-level into `config/`. All path references in this plan were prefixed accordingly.
2. **PRs #5–#8 (deploy-to-pi v1):** a real `/deploy-to-pi` skill + script with 8 safety gates is now the canonical sync mechanism. Task 6 was rewritten to use it instead of raw rsync; Task 7 was simplified because deploy-to-pi handles the firmware_restart + ready-polling internally.

The original Task 6/7 content is preserved in git history at commit `503c85c` if needed for reference (run `git log -- docs/superpowers/plans/2026-05-13-eddy-ng-to-native-migration.md` to find it).

Calibration tasks (8, 9, 10) are unchanged — they require Ben physically at the printer and aren't affected by the tooling refresh.
