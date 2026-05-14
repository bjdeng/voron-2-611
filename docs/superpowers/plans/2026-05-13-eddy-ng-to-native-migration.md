# Eddy-NG → Native Klipper Eddy Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `vvuk/eddy-ng` Klipper probe extension with upstream Klipper's native `[probe_eddy_current]` + `[ldc1612]` on Voron 2.611, preserving the tap-at-print-start workflow.

**Architecture:** In-place rewrite of `eddy.cfg` on a `feat/eddy-native` git worktree. Surgical two-line edit to `macros/print_start.cfg`. SAVE_CONFIG cleanup in `printer.cfg`. Manual `rsync` to the Pi at `pi@mainsailos.local` (keyed SSH already set up). Hands-on calibration at the printer (bed 60 °C, hotend 200 °C). `pr-review-toolkit:review-pr` runs before merge to `main`.

**Tech Stack:** Klipper `0.13.0-649-g4767a8ed` (master, pinned per `vendor/klipper`), Moonraker `v0.10.0-19`, Mainsail, SSH to Pi, rsync. No code-language tests — verification is Klipper RESTART success + calibration step success + printed-part quality.

**Spec:** `docs/superpowers/specs/2026-05-13-eddy-ng-to-native-migration.md` (commit `fc79190`).

---

## File structure (what changes, what doesn't)

**Modified in this repo (on `feat/eddy-native` worktree):**

| File | Scope of change | Reason |
|---|---|---|
| `eddy.cfg` | Full rewrite of the probe section. Replace `[probe_eddy_ng btt_eddy]` with `[probe_eddy_current btt_eddy]` (+ `[ldc1612 btt_eddy]` if required by the pinned Klipper commit). Preserve `[mcu eddy]`, both `[temperature_sensor]`s, `[bed_mesh]`, `[safe_z_home]`, `[force_move]`, and both `[gcode_macro ...]` overrides byte-for-byte. | Spec §5.1 |
| `macros/print_start.cfg` | Line 67: `PROBE_EDDY_NG_TAP` → `G28 Z METHOD=tap` (with documented fallback). Line 93: delete `PROBE_EDDY_NG_SET_TAP_OFFSET VALUE=0`. | Spec §5.2 |
| `printer.cfg` | Delete the `#*# [probe_eddy_ng btt_eddy]` block in SAVE_CONFIG (currently lines ~463-469). Leave every other SAVE_CONFIG entry untouched. | Spec §5.3 |
| `memory/tuning-log.md` | Append a 2026-05-13 entry with new calibration values pulled back from the Pi's `printer.cfg` after step 6. | Spec §6 verification + project convention |

**Unchanged (verified by grep for `eddy_?ng|probe_eddy_ng`):**
`btt-ebb-sb-usb-v1.0.cfg`, `mainsail.cfg`, `timelapse.cfg`, `moonraker.conf`, `crowsnest.conf`, `sonar.conf`, `firmware/*.config`, all of `mmu/*`, `macros/{macros,bedfans,lcd_tweaks,test_speed,calibrate_*}.cfg`.

**Pi-side state (not in repo, but mutated):**
- `~/printer_data/config/*.cfg` — overwritten by rsync from the worktree.
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

## Task 3: Rewrite `eddy.cfg`

**Files:**
- Modify: `eddy.cfg` (whole-file replacement of the probe section; other sections preserved byte-for-byte)

- [ ] **Step 1: Snapshot the current `eddy.cfg` for diff comparison**

```sh
cp eddy.cfg /tmp/eddy.cfg.before
```

This is for visual diff inspection during Step 4, not for rollback (git handles that).

- [ ] **Step 2: Open `eddy.cfg` and edit in place**

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

Lines 60-145 of the current `eddy.cfg` contain commented-out `# Uncomment if using Eddy as probe AND endstop AND beta z-offset control` blocks (`G28` override, `SET_Z_FROM_PROBE`, `Z_OFFSET_APPLY_PROBE`, etc). These are eddy-ng scaffolding for features native folds in automatically. Delete them in their entirety.

- [ ] **Step 4: Verify everything else in `eddy.cfg` is preserved byte-for-byte**

```sh
diff /tmp/eddy.cfg.before eddy.cfg
```

The diff should show:
- The 8-line `[probe_eddy_ng btt_eddy]` block removed
- The new `[ldc1612]` / `[probe_eddy_current]` block(s) added
- The 80+ commented-out scaffolding lines at the bottom removed
- **Nothing else changed** — `[mcu eddy]`, both `[temperature_sensor]`s, `[bed_mesh]`, `[safe_z_home]`, `[force_move]`, both `[gcode_macro ...]` overrides identical

In particular, the `QUAD_GANTRY_LEVEL` override must remain byte-for-byte (the two-pass `horizontal_move_z=8` + `horizontal_move_z=2` is the saggy-rear workaround — see `memory/v24-saggy-rear-qgl.md`).

If the diff shows changes anywhere else, undo them and re-diff before continuing.

---

## Task 4: Update `macros/print_start.cfg`

**Files:**
- Modify: `macros/print_start.cfg:67` and `macros/print_start.cfg:93`

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
grep -nE "PROBE_EDDY|METHOD=tap|SET_KINEMATIC" macros/print_start.cfg
```

Expected: matches only on the new lines from Step 1. No `PROBE_EDDY_NG_*` references remain.

```sh
grep -rin "PROBE_EDDY_NG" --include='*.cfg' .
```

Expected: only matches in `archive/` (which is intentionally not included by `printer.cfg`).

---

## Task 5: Strip stale SAVE_CONFIG block from `printer.cfg`

**Files:**
- Modify: `printer.cfg` (the SAVE_CONFIG section at the bottom)

- [ ] **Step 1: Locate the stale block**

```sh
grep -n "#\*# \[probe_eddy_ng" printer.cfg
```

Expected: a line number around 463. Note the line number; the block starts there.

- [ ] **Step 2: Find the end of the block**

```sh
awk '/^#\*# \[probe_eddy_ng/,/^#\*# \[/{print NR": "$0}' printer.cfg | head -20
```

The block ends just before the next `#*# [` section header. Note both line numbers.

- [ ] **Step 3: Delete the block**

Edit `printer.cfg` and delete lines from the `#*# [probe_eddy_ng btt_eddy]` header through the last line of its content (the base64 `calibration_16 = ...` line). Stop before the next `#*# [<section>]` header.

- [ ] **Step 4: Confirm the rest of SAVE_CONFIG is intact**

```sh
grep -nE "^#\*# \[" printer.cfg
```

Expected to remain (no `probe_eddy_ng`):
- `#*# [heater_bed]`
- `#*# [extruder]`
- `#*# [input_shaper]`
- `#*# [bed_mesh Default2]`
- `#*# [bed_mesh default]`

If any of those are missing, undo the edit and try again — only the `probe_eddy_ng` block should be removed.

---

## Task 6: First commit and sync to Pi

**Files:**
- Commit on `feat/eddy-native` branch
- Sync `~/printer_data/config/{eddy.cfg, macros/print_start.cfg, printer.cfg}` on the Pi

- [ ] **Step 1: Review the diff**

```sh
git diff --stat
git diff eddy.cfg macros/print_start.cfg printer.cfg
```

Read the full diff. Confirm:
- `eddy.cfg`: probe section replaced, scaffolding deleted, nothing else touched
- `macros/print_start.cfg`: exactly 2 line changes (one replace, one delete)
- `printer.cfg`: only the `probe_eddy_ng` SAVE_CONFIG block removed

- [ ] **Step 2: Stage and commit**

```sh
git add eddy.cfg macros/print_start.cfg printer.cfg docs/superpowers/plans/eddy-prep-notes.md
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

- [ ] **Step 3: Dry-run the rsync to the Pi**

```sh
rsync -avzn --delete-after \
  eddy.cfg macros/print_start.cfg printer.cfg \
  pi@mainsailos.local:~/printer_data/config/
```

The `-n` is dry-run. Read the output: it should list exactly 3 file transfers (preserving the `macros/` directory structure for `print_start.cfg`). No deletions. If anything else is listed for transfer or deletion, stop.

Note: the rsync target preserves `macros/print_start.cfg` as `~/printer_data/config/macros/print_start.cfg` because rsync preserves relative paths when source paths have a leading directory. Verify the dry-run output reflects this.

- [ ] **Step 4: Real rsync**

```sh
rsync -avz \
  eddy.cfg macros/print_start.cfg printer.cfg \
  pi@mainsailos.local:~/printer_data/config/
```

(Drop the `-n`; do NOT use `--delete-after` for the live run — we only want to overwrite the three named files.)

Expected: three file transfers reported. No errors.

- [ ] **Step 5: Verify file contents on the Pi**

```sh
ssh pi@mainsailos.local 'head -20 ~/printer_data/config/eddy.cfg; echo "---"; sed -n "60,75p" ~/printer_data/config/macros/print_start.cfg; echo "---"; tail -30 ~/printer_data/config/printer.cfg'
```

Confirm:
- `eddy.cfg` head shows the new `[probe_eddy_current]` block
- `print_start.cfg` lines 60-75 show the new `G28 Z METHOD=tap` (or fallback)
- `printer.cfg` tail SAVE_CONFIG no longer mentions `probe_eddy_ng`

---

## Task 7: Config syntax smoke (Klipper RESTART succeeds)

**Files:** none modified — running and observing on the Pi.

- [ ] **Step 1: Restart Klipper via Moonraker**

```sh
curl -sf -X POST http://mainsailos.local:7125/printer/firmware_restart \
  || ssh pi@mainsailos.local 'sudo systemctl restart klipper'
```

We use `firmware_restart` (not just `restart`) because we changed `[mcu]`-impacting config (the new `[ldc1612]` / `[probe_eddy_current]` sections involve the Eddy MCU).

- [ ] **Step 2: Wait for Klipper to come up and check status**

```sh
sleep 6
ssh pi@mainsailos.local 'tail -30 ~/printer_data/logs/klippy.log'
```

Expected: lines ending in `Klipper state: Ready` or similar. **No** stack traces, **no** `Unknown config option`, **no** `pin clash`, **no** `Probe is required but missing`.

If errors appear, stop and read the full log:

```sh
ssh pi@mainsailos.local 'tail -200 ~/printer_data/logs/klippy.log'
```

Common failures:
- `Unknown config object 'ldc1612'` → revisit Task 2 Step 2 (the inline-vs-separate question)
- `Pin XXX used multiple times in config` → check the `intb_pin` value from Task 2 Step 1
- `Probe requires .. method ...` → revisit Task 4 Step 1 (the G28 METHOD=tap form)

If any error: **do not proceed**. Fix in worktree, re-run Task 6 Steps 4-5, then retry this step.

- [ ] **Step 3: Confirm probe is recognized in Mainsail / Moonraker**

```sh
curl -s http://mainsailos.local:7125/printer/objects/query?probe | python3 -m json.tool | head -30
```

Expected: a JSON object with a `result.status.probe` key (possibly with `last_z_result: null` since no probe has run yet).

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
scp pi@mainsailos.local:~/printer_data/config/printer.cfg ./printer.cfg
git diff printer.cfg
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

- [ ] **Step 6: Commit the printer.cfg SAVE_CONFIG sync and the tuning log entry**

```sh
git add printer.cfg memory/tuning-log.md
git commit -m "$(cat <<'EOF'
feat(eddy): record native Eddy calibration results

- printer.cfg SAVE_CONFIG now contains [probe_eddy_current btt_eddy]
  values from on-machine calibration at bed 60°C / hotend 200°C
- memory/tuning-log.md updated with the new values for future reference

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: PR review and merge

**Files:**
- Remove: `docs/superpowers/plans/eddy-prep-notes.md` (scratchpad cleanup)

- [ ] **Step 1: Remove the prep-notes scratchpad**

The temporary notes from Task 2 are no longer needed.

```sh
git rm docs/superpowers/plans/eddy-prep-notes.md
git commit -m "chore(eddy): remove prep scratchpad after successful migration"
```

- [ ] **Step 2: Invoke pr-review-toolkit on the branch diff**

```
Skill: pr-review-toolkit:review-pr
```

Pass the branch diff context: `feat/eddy-native` vs `main`. The toolkit will dispatch its sub-reviewers (code-reviewer, comment-analyzer, silent-failure-hunter, type-design-analyzer, pr-test-analyzer, code-simplifier). Treat its output as gating — address any high-priority findings before merging.

Note: most pr-review-toolkit findings will be about code, not Klipper configs. The most relevant sub-skills for a config-only PR are `code-reviewer` (catches structural issues, e.g., a section we should have preserved but didn't) and `comment-analyzer` (the spec/plan/commit messages are heavy with prose).

- [ ] **Step 3: Address any review findings**

If the toolkit flags issues:
- High-priority: fix on the branch, re-commit, re-run Task 11 Step 2.
- Low-priority / nits: optionally fix; document deferrals in `memory/decisions.md` if you skip.

- [ ] **Step 4: Merge `feat/eddy-native` into `main`**

Per Ben's git conventions (CLAUDE.md global): squash merge preferred. Since the repo has no GitHub remote yet, this is a local merge.

```sh
# Find the parent repo (the worktree is a linked working tree)
PARENT=$(git rev-parse --path-format=absolute --git-common-dir | xargs dirname)
echo "Parent repo: $PARENT"

# Step into parent repo and switch to main
git -C "$PARENT" checkout main

# Squash-merge feat/eddy-native into main
git -C "$PARENT" merge --squash feat/eddy-native
git -C "$PARENT" commit -m "$(cat <<'EOF'
feat(eddy): migrate from vvuk/eddy-ng to native [probe_eddy_current]

Squash-merge of feat/eddy-native. Replaces third-party probe extension
with upstream Klipper's native module. Tap-at-print-start preserved.
Calibration values captured in printer.cfg SAVE_CONFIG and memory/tuning-log.md.

Spec: docs/superpowers/specs/2026-05-13-eddy-ng-to-native-migration.md
Plan: docs/superpowers/plans/2026-05-13-eddy-ng-to-native-migration.md
References: <community repo from Task 2 step 4>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Exit the worktree**

Use the native tool counterpart to `EnterWorktree`:

```
ExitWorktree
```

(Or, if not available: `git worktree remove <path>` after `git branch -D feat/eddy-native`.)

- [ ] **Step 6: Verify the Pi matches main**

```sh
cd /Users/ben/code/voron-2-611
git checkout main
rsync -avzn eddy.cfg macros/print_start.cfg printer.cfg pi@mainsailos.local:~/printer_data/config/
```

Expected: dry-run reports **zero file transfers** — the Pi is already in sync with `main` because Task 6 already pushed the changes and Task 10 pulled the SAVE_CONFIG back.

If anything transfers, real-rsync it and `RESTART` Klipper.

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
