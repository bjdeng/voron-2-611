# MMU calibration recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> This plan is hybrid: ~3 tasks are normal repo changes (flag flips, post-cal `mmu_vars.cfg` snapshot, optional drift cleanup); ~12 tasks are operator-driven calibration steps Claude orchestrates over SSH + Moonraker but cannot execute alone. **Operator must be present at the printer for tasks marked OPERATOR**. Claude reads logs, verifies output, and gates progress.

**Goal:** Recover MMU load/unload reliability by un-blocking gear rotation distance calibration (`skip_cal_rotation_distance: 1` → `0`, `autotune_rotation_distance: 1` → `0`), running the HH-canonical calibration sequence, and validating with `MMU_SOAKTEST_LOAD_SEQUENCE`.

**Architecture:** Two-stage merge. Stage 1: PR with the flag flips in `mmu_parameters.cfg`, deployed to the Pi via `/deploy-to-pi` (without smoke — the printer is mid-procedure). Stage 2: post-calibration `mmu_vars.cfg` snapshot captured via `sync-from-pi`, committed direct to main (post-cal mmu_vars is operator-only docs in spirit; the actual cal values are produced by HH macros, not authored). Soak validation gates the close of issue #15.

**Tech Stack:** Klipper config (`.cfg`), Happy Hare v3.4.2 macros (`MMU_*`), Moonraker REST API (`/printer/gcode/script`, `/printer/info`), SSH to `pi@mainsailos.local`, `scripts/deploy_to_pi.sh`, `scripts/sync_from_pi.sh`.

**Spec:** [`docs/superpowers/specs/2026-05-17-mmu-calibration-fix-design.md`](../specs/2026-05-17-mmu-calibration-fix-design.md)

---

## Pre-flight (before Task 1)

- [ ] **Step 0.1: Confirm operator availability**

Operator must be at the printer for: servo inspection (Task 2), gear gate-0 calibration (Task 8), toolhead cal standby (Task 11). Estimated total operator time at the printer: ~30 minutes. Other tasks can be Claude-only over SSH.

- [ ] **Step 0.2: Confirm printer is idle**

```bash
curl -s http://mainsailos.local:7125/printer/objects/query?print_stats | python3 -c "import sys, json; d = json.load(sys.stdin); print(d['result']['status']['print_stats']['state'])"
```

Expected output: `standby`. If `printing` or `paused`, abort and resume after print.

- [ ] **Step 0.3: Read the spec end-to-end**

Read `docs/superpowers/specs/2026-05-17-mmu-calibration-fix-design.md` once now. Tasks below assume familiarity with the diagnosis and section structure.

---

## Task 1: Create worktree (Claude)

**Files:** (none; worktree creation)

- [ ] **Step 1: Use `EnterWorktree` tool**

Branch name: `feat/mmu-cal-issue-15`. Base: `main`. Per `superpowers:using-git-worktrees`.

- [ ] **Step 2: Verify clean tree on the worktree**

```bash
git status
```

Expected:
```
On branch feat/mmu-cal-issue-15
nothing to commit, working tree clean
```

---

## Task 2: Servo inspection (OPERATOR)

**Files:** (none)

- [ ] **Step 1: Open the MMU enclosure**

Physical: remove the MMU panel to expose the selector cart and gear motor + servo arm.

- [ ] **Step 2: Visual inspection of servo arm + gear teeth**

Look for: visibly worn gear teeth (rounded edges), play in the servo arm at rest, cracks in the arm plastic, hairline strip marks on the drive gear.

- [ ] **Step 3: Functional engagement test**

Insert a 50mm piece of filament into gate 0's entry. From a console window:

```
MMU_SERVO POS=down
```

Then physically try to pull the filament back out by hand. Expected: hard stop (servo arm pinching filament against the drive gear should grip — manual pull should encounter resistance ≥ a few hundred grams of force).

- [ ] **Step 4: Decision point**

- **If servo passes (filament grips firmly):** proceed to Task 3.
- **If servo slips (filament pulls out easily) or visible wear:** STOP. Replace the servo before proceeding. All calibration data collected with a slipping servo is invalid. (Note: this might mean ordering a replacement servo; the plan resumes at Task 3 after the replacement.)

---

## Task 3: Stats baseline + state snapshot (Claude)

**Files:**
- Snapshot on Pi: `~/printer_data/config/mmu_vars.cfg.pre-cal-2026-05-17`

- [ ] **Step 1: Reset the servo wear counter**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_STATS COUNTER=servo_down RESET=1"}'
```

Expected response: `{"result":"ok"}`.

- [ ] **Step 2: Reset all failure stats**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_STATS RESET=1"}'
```

Expected response: `{"result":"ok"}`. Per-gate `load_failures`/`unload_failures` are now zero.

- [ ] **Step 3: Snapshot the current `mmu_vars.cfg` on the Pi for rollback**

```bash
ssh pi@mainsailos.local "cp ~/printer_data/config/mmu_vars.cfg ~/printer_data/config/mmu_vars.cfg.pre-cal-2026-05-17 && ls -la ~/printer_data/config/mmu_vars.cfg.pre-cal-2026-05-17"
```

Expected: file listed with non-zero size.

- [ ] **Step 4: Pull current `mmu_vars.cfg` into the repo as a snapshot baseline**

In Claude session: invoke `/sync-from-pi`. Inspect the diff; if Pi-side stats reset propagated, accept. Do NOT commit yet — Task 16 commits the post-cal version.

---

## Task 4: Flag flips PR (Claude)

**Files:**
- Modify: `config/mmu/base/mmu_parameters.cfg` (two lines near 668 and 671)

- [ ] **Step 1: Find and read the current state of both flags**

```bash
grep -nE "^skip_cal_rotation_distance|^autotune_rotation_distance" config/mmu/base/mmu_parameters.cfg
```

Expected output:
```
670:skip_cal_rotation_distance: 1	# Skip rotation distance calibration (MMU_CALIBRATE_GEAR), 1=skip, 0=require
671:autotune_rotation_distance: 1	# Automated gate calibration/tuning. 1=automatic, 0=manual/off
```

- [ ] **Step 2: Flip `skip_cal_rotation_distance: 1` → `0`**

Use the Edit tool. Old:
```
skip_cal_rotation_distance: 1	# Skip rotation distance calibration (MMU_CALIBRATE_GEAR), 1=skip, 0=require
```

New:
```
skip_cal_rotation_distance: 0	# Skip rotation distance calibration (MMU_CALIBRATE_GEAR), 1=skip, 0=require (re-enabled 2026-05-17 to allow MMU_CALIBRATE_GEAR for issue #15)
```

- [ ] **Step 3: Flip `autotune_rotation_distance: 1` → `0`**

Use the Edit tool. Old:
```
autotune_rotation_distance: 1	# Automated gate calibration/tuning. 1=automatic, 0=manual/off
```

New:
```
autotune_rotation_distance: 0	# Automated gate calibration/tuning. 1=automatic, 0=manual/off (set 0 because HH source wraps the autotune branch in `False and` at mmu_calibration_manager.py:499 — the flag was misleading)
```

- [ ] **Step 4: Run macOS-friendly CI subset locally**

```bash
make test-py
```

Expected: all tests pass, pre-commit clean.

- [ ] **Step 5: Commit**

```bash
git add config/mmu/base/mmu_parameters.cfg
git commit -m "$(cat <<'EOF'
fix(mmu): unblock MMU_CALIBRATE_GEAR — flip skip_cal_rotation_distance + autotune_rotation_distance

Per issue #15 diagnosis: per-gate gear RDs are stuck because
skip_cal_rotation_distance: 1 actively blocks MMU_CALIBRATE_GEAR,
and autotune_rotation_distance is dead code upstream (False and-guard
at mmu_calibration_manager.py:499 in HH v3.4.2). Flip both to 0.

The flag flips alone don't fix the failures — they enable the operator
runbook to actually run the HH-canonical recalibration (see
docs/superpowers/specs/2026-05-17-mmu-calibration-fix-design.md
section 4). Calibration values produced by that procedure land in a
follow-up commit to mmu_vars.cfg.

Restart impact: RESTART (no MCU/pin changes).

Refs: #15

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push the branch**

```bash
git push -u origin feat/mmu-cal-issue-15
```

- [ ] **Step 7: Run pr-review-toolkit before opening PR**

Invoke the `pr-review-toolkit:review-pr` skill. For a 2-line config change, the code-reviewer + klipper-cfg-reviewer agents are sufficient. Address any blocking findings.

- [ ] **Step 8: Open PR**

```bash
gh pr create --title "fix(mmu): unblock MMU_CALIBRATE_GEAR for issue #15" --body "$(cat <<'EOF'
## Summary

Two-line config change in `config/mmu/base/mmu_parameters.cfg` that unblocks
the HH-canonical MMU recalibration described in the spec:

- `skip_cal_rotation_distance: 1` → `0` (was actively blocking `MMU_CALIBRATE_GEAR`)
- `autotune_rotation_distance: 1` → `0` (was a misleading flag — the upstream branch is `False and …`-guarded in `mmu_calibration_manager.py:499`)

This PR alone does not fix the failures. It enables the operator-driven
recalibration procedure in the spec (section 4) to actually run. The post-cal
`mmu_vars.cfg` snapshot lands in a follow-up commit direct to main.

Spec: `docs/superpowers/specs/2026-05-17-mmu-calibration-fix-design.md`
Plan: `docs/superpowers/plans/2026-05-17-mmu-calibration-fix.md`

Restart impact: RESTART only.

## Test plan

- [x] `make test-py` — green
- [x] `pr-review-toolkit:review-pr` — no blocking findings
- [ ] CI green
- [ ] Post-merge: `/deploy-to-pi` (without `--smoke` — printer is mid-procedure)
- [ ] Post-deploy: `MMU_CALIBRATE_GEAR` is no longer rejected with "skip_cal_rotation_distance is set" (verified in Task 8)

Refs: #15

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 9: Wait for CI green and merge**

```bash
gh pr checks
gh pr merge --squash --delete-branch
```

- [ ] **Step 10: Deploy to Pi (without smoke)**

In Claude session: invoke `/deploy-to-pi`. **Do NOT pass `--smoke`** — the printer is mid-calibration; G28 + park sequences run by smoke could disturb the operator's setup.

Expected: deploy completes with `Klipper state=ready`. Restart impact is RESTART; the Pi re-loads `mmu_parameters.cfg` with the new flag values.

---

## Task 5: Disable `autocal_bowden_length` at runtime (Claude)

**Files:** (none; runtime-only change. Must run AFTER Task 4's deploy — the deploy `RESTART`s Klipper which would otherwise revert this runtime change.)

- [ ] **Step 1: Disable autocal**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_TEST_CONFIG AUTOCAL_BOWDEN_LENGTH=0"}'
```

Expected: `{"result":"ok"}`. Klipper's runtime config now has the flag off; the saved value in `mmu_parameters.cfg` is unchanged (will be re-enabled by `MMU_TEST_CONFIG AUTOCAL_BOWDEN_LENGTH=1` in Task 12).

---

## Task 6: Sanity baseline (Claude)

**Files:** (none; observation only)

- [ ] **Step 1: Home the MMU**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_HOME"}'
```

Expected: `{"result":"ok"}` after ~10s. Selector cart returns to home position.

- [ ] **Step 2: Read MMU status**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_STATUS"}'
sleep 1
ssh pi@mainsailos.local "tail -30 ~/printer_data/logs/mmu.log"
```

Expected output in `mmu.log`: clean status display, no pauses, no errors, all 6 gates available. If any gate shows red or "unknown", inspect that gate before proceeding.

---

## Task 7: Encoder resolution verification (Claude)

**Files:** (none; runtime cal command, mmu_vars.cfg potentially rewritten)

- [ ] **Step 1: Dry-run encoder cal (verify only)**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_ENCODER LENGTH=500 REPEATS=5 SAVE=0"}'
```

Expected: `{"result":"ok"}` after ~2 minutes (it physically moves filament). Operator should be standing by in case filament jams.

- [ ] **Step 2: Read the measured value from mmu.log**

```bash
ssh pi@mainsailos.local "tail -50 ~/printer_data/logs/mmu.log | grep -iE 'encoder|resolution'"
```

Expected: a line like `Encoder resolution: 0.9988 (measured) vs 0.998752 (saved). Drift: 0.0%`.

- [ ] **Step 3: Decision — save or skip**

- **Drift < 1%:** skip Step 4; encoder resolution is good as-is.
- **Drift ≥ 1%:** proceed to Step 4.

- [ ] **Step 4 (conditional): Re-run with SAVE=1**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_ENCODER LENGTH=500 REPEATS=5 SAVE=1"}'
```

Klipper will trigger `SAVE_CONFIG` and restart automatically. Wait for `/printer/info` to report `state=ready` before proceeding to Task 8.

---

## Task 8: Gear rotation distance, gate 0 (OPERATOR)

**Files:** (none; cal command rewrites mmu_vars.cfg)

- [ ] **Step 1: Select gate 0**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_SELECT GATE=0"}'
```

Wait for completion (~5s).

- [ ] **Step 2: Operator marks filament at the gate entry point**

Before any move: with the filament loaded into gate 0 and visible at the MMU entry, mark the filament with a felt-tip pen exactly at the point where it enters the MMU body. This mark is the reference for the post-move measurement.

- [ ] **Step 3: Run `MMU_CALIBRATE_GEAR` (does the 100mm move AND prompts for measurement)**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_GEAR LENGTH=100"}'
```

HH performs a 100mm filament push and logs the commanded distance to `mmu.log`. Wait ~5s for the move to complete.

- [ ] **Step 4: Operator measures actual distance moved**

With calipers, measure the distance from the original ink mark to where the filament now enters the MMU. **This is the actual mm of filament that moved** during the commanded 100mm push. Record the number (e.g., `103.4`).

- [ ] **Step 5: Feed measured value back to save the corrected RD**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_GEAR LENGTH=100 MEASURED=<measured_mm> SAVE=1"}'
```

Replace `<measured_mm>` with the actual measurement from Step 4. HH computes the corrected `mmu_gear_rotation_distances[0]` and triggers `SAVE_CONFIG`.

- [ ] **Step 6: Verify the new gate-0 RD was saved**

```bash
ssh pi@mainsailos.local "grep mmu_gear_rotation_distances ~/printer_data/config/mmu_vars.cfg"
```

Expected: the first entry in the list has changed from `23.6262` to a new value reflecting the calibration.

---

## Task 9: Per-gate RDs (Claude)

**Files:** (none; cal command rewrites mmu_vars.cfg)

- [ ] **Step 1: Run the per-gate sweep**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_GATES GATE=ALL"}'
```

This sweeps each gate 1–5 against gate 0's reference + encoder. Each gate takes ~30s; total ~3 minutes. Operator stands by.

- [ ] **Step 2: Verify the new per-gate RDs were saved**

```bash
ssh pi@mainsailos.local "grep mmu_gear_rotation_distances ~/printer_data/config/mmu_vars.cfg"
```

Expected: all 6 entries reflect fresh measurements. Compute the spread: `(max - min) / gate_0`. Expected: **<1%** spread (vs the pre-cal 3.6%).

- [ ] **Step 3: Decision — proceed or branch**

- **Spread <1%:** proceed to Task 10.
- **Spread ≥1% with one specific gate as the outlier:** that gate has a mechanical issue (see spec section 6). Stop and inspect that gate physically (drive gear teeth, grub screw, lint).
- **Spread ≥1% uniformly:** encoder is unreliable. Return to Task 7 with `REPEATS=10`, or inspect the encoder wheel.

---

## Task 10: Bowden length (Claude)

**Files:** (none; cal command rewrites mmu_vars.cfg)

- [ ] **Step 1: Run bowden calibration at gate 0**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_BOWDEN GATE=0 BOWDEN_LENGTH=1019.4 REPEATS=3"}'
```

3 iterations; total ~3 minutes. HH converges on a bowden length.

- [ ] **Step 2: Verify the saved length**

```bash
ssh pi@mainsailos.local "grep mmu_calibration_bowden_lengths ~/printer_data/config/mmu_vars.cfg"
```

Expected: a list of 6 values close to each other (HH typically writes the same value to all gates). If they differ wildly, the encoder is unreliable — return to Task 7.

---

## Task 11: Toolhead constants via HH (OPERATOR + Claude)

**Files:** (none; cal command rewrites mmu_vars.cfg)

Always run. HH's auto-derived values replace the current CAD-based saved triplet (`102.1` / `79.1` / `9.9`). Per spec section 4: if HH's result diverges sharply (>5mm) from CAD, the cal failed — re-run.

- [ ] **Step 1: Preheat hotend (toolhead cal needs filament in extruder)**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"M104 S210"}'
```

Wait ~3 minutes for hotend to reach 210 °C.

- [ ] **Step 2: Run the CLEAN phase**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_TOOLHEAD CLEAN=1"}'
```

Operator stands by; this fires `G28` and moves filament. Measures `toolhead_extruder_to_nozzle` + `toolhead_sensor_to_nozzle`.

- [ ] **Step 3: Sanity-check the CLEAN result**

```bash
ssh pi@mainsailos.local "grep -E 'toolhead_extruder_to_nozzle|toolhead_sensor_to_nozzle' ~/printer_data/config/printer.cfg ~/printer_data/config/mmu_parameters.cfg | tail -10"
```

Compare HH's new values to CAD (`extruder_to_nozzle: 102.1`, `sensor_to_nozzle: 79.1`).

- **Within 5mm of CAD:** accept HH's values; proceed to Step 4.
- **Diverged >5mm from CAD:** HH's cal probably failed. Re-run Step 2 once more. If second run also diverges, stop and inspect the toolhead sensor wiring before continuing.

- [ ] **Step 4: Run the DIRTY phase**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_TOOLHEAD DIRTY=1"}'
```

Measures `toolhead_residual_filament`. Compare result to current `23` — this was flagged as suspect in the spec drift-audit (HH upstream default 0). Note the new value.

- [ ] **Step 5 (optional): Run the CUT phase**

Only if the Filametrix blade has been moved or replaced recently. Otherwise skip.

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_CALIBRATE_TOOLHEAD CUT=1"}'
```

- [ ] **Step 6: Cool hotend**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"TURN_OFF_HEATERS"}'
```

---

## Task 12: Re-enable `autocal_bowden_length` (Claude)

**Files:** (none; runtime change)

- [ ] **Step 1: Re-enable**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_TEST_CONFIG AUTOCAL_BOWDEN_LENGTH=1"}'
```

Expected: `{"result":"ok"}`. Klipper runtime config back in sync with `mmu_parameters.cfg`.

---

## Task 13: Reset failure stats (Claude)

**Files:** (none; runtime change)

- [ ] **Step 1: Reset**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_STATS RESET=1"}'
```

Per-gate failure counts are now zero. Fresh stats starting from the validation soak in Task 14.

---

## Task 14: Validation soak — Pass 1, MMU-only (Claude)

**Files:** (none; runtime command)

- [ ] **Step 1: Verify printer is in ready state**

```bash
curl -s http://mainsailos.local:7125/printer/info | python3 -c "import sys, json; print(json.load(sys.stdin)['result']['state'])"
```

Expected: `ready`.

- [ ] **Step 2: Run the cheap soak (no heater)**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_SOAKTEST_LOAD_SEQUENCE LOOP=3 RANDOM=0 FULL=0"}'
```

3 sequential sweeps × 6 gates × 100mm bowden move. Expected duration: ~5–8 minutes. Operator stands by in case filament jams.

- [ ] **Step 3: Read stats after Pass 1**

```bash
ssh pi@mainsailos.local "grep -E 'mmu_statistics_gate_[0-5]' ~/printer_data/config/mmu_vars.cfg"
```

Compute: total load failures across 18 sequences (3 loops × 6 gates).

- [ ] **Step 4: Decision**

- **0 failures:** proceed to Task 15.
- **1–2 failures (≤2% of 18):** proceed to Task 15. Pass 1 met criterion.
- **≥3 failures, one specific gate dominates:** see spec section 6 branch "Pass 1 fails uniformly across gates" → false alarm; the branch for one-gate-dominant is "that gate is mechanically different (selector misalignment, gate endstop drift)" — run `MMU_CHECK_GATE GATE=N`.
- **≥3 failures, uniform across gates:** toolhead constants from Task 11 are wrong or HH's cal failed. Re-run Task 11 with all three phases (`CLEAN`, `DIRTY`, `CUT`); compare HH's output against CAD (102.1/79.1/9.9).

---

## Task 15: Validation soak — Pass 2, full hot extruder-engaged (Claude + OPERATOR)

**Files:** (none; runtime command)

- [ ] **Step 1: Preheat**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"M104 S210"}'
sleep 5
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"M109 S210"}'
```

Wait ~3 minutes for hotend to reach 210 °C.

- [ ] **Step 2: Run the full soak (randomized order)**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"MMU_SOAKTEST_LOAD_SEQUENCE LOOP=2 RANDOM=1 FULL=1"}'
```

2 randomized sweeps × 6 gates, loading all the way to nozzle. Expected duration: ~12–15 minutes. Operator stands by.

- [ ] **Step 3: Cool hotend**

```bash
curl -X POST 'http://mainsailos.local:7125/printer/gcode/script' \
  -H 'Content-Type: application/json' \
  -d '{"script":"TURN_OFF_HEATERS"}'
```

- [ ] **Step 4: Read stats after Pass 2**

```bash
ssh pi@mainsailos.local "grep -E 'mmu_statistics_gate_[0-5]' ~/printer_data/config/mmu_vars.cfg"
```

- [ ] **Step 5: Decision**

- **≤1 failure across 12 sequences:** Pass 2 met criterion. Proceed to Task 16.
- **>1 failure:** branch per spec section 6.

---

## Task 16: Commit post-cal `mmu_vars.cfg` to main (Claude)

**Files:**
- Modify (will be rewritten by sync): `config/mmu/mmu_vars.cfg`
- Append: `memory/troubleshooting-log.md` (post-cal stats summary)

- [ ] **Step 1: Switch back to main (exit the worktree if still in it)**

The flag flips already merged via Task 4. The post-cal `mmu_vars.cfg` snapshot is operator-only (no behavior change in macros) — direct-to-main per `memory/docs-direct-to-main.md`.

If in the worktree, exit:
- Use `ExitWorktree` with `action: keep` if you want to preserve the worktree for later cleanup
- Or `action: remove` if all commits on the branch are landed on main

Then in the main worktree:

```bash
git checkout main && git pull --ff-only
```

- [ ] **Step 2: Pull fresh `mmu_vars.cfg` from the Pi**

In Claude session: invoke `/sync-from-pi`. The skill will diff Pi vs repo; expect changes only to `config/mmu/mmu_vars.cfg` (the gear RDs, encoder resolution if updated, bowden lengths, and possibly toolhead constants).

- [ ] **Step 3: Append post-cal summary to `memory/troubleshooting-log.md`**

```markdown

### Post-cal stats (Task 14 + 15)

- Pass 1 (LOOP=3 FULL=0): <N> failures across 18 sequences (<rate>%)
- Pass 2 (LOOP=2 FULL=1 RANDOM=1): <N> failures across 12 sequences (<rate>%)
- Gear RD spread (post-cal): <max - min> mm / <gate-0> = <pct>% (was 3.6%)
- Issue #15 status: CLOSED / OPEN with note "<note>"
```

Fill in actuals.

- [ ] **Step 4: Commit + push direct to main**

```bash
git add config/mmu/mmu_vars.cfg memory/troubleshooting-log.md
git commit -m "$(cat <<'EOF'
chore(mmu): post-cal mmu_vars.cfg snapshot — closes #15

Cumulative result of the operator-driven HH-canonical recalibration
described in docs/superpowers/specs/2026-05-17-mmu-calibration-fix-design.md
and docs/superpowers/plans/2026-05-17-mmu-calibration-fix.md.

Validation soak (MMU_SOAKTEST_LOAD_SEQUENCE) passed both passes:
- Pass 1 (LOOP=3 FULL=0): <N> failures across 18 sequences
- Pass 2 (LOOP=2 FULL=1 RANDOM=1): <N> failures across 12 sequences

Per-gate gear RD spread tightened from 3.6% to <new>%.

Closes #15.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

(Direct-to-main works because `enforce_admins: false` on the protection rule — `memory/docs-direct-to-main.md`.)

- [ ] **Step 5: Close issue #15 with the summary**

```bash
gh issue close 15 --comment "Closed by <commit-sha>. Two-pass validation soak green; per-gate failure rates tracked in memory/troubleshooting-log.md going forward. Drift-cleanup follow-up (toolhead_residual_filament + gear_from_buffer_accel) tracked separately per spec section 7."
```

---

## Task 17 (optional, deferrable): Drift cleanup (Claude)

Defer this until at least one successful multi-color print has shipped post-cal. Treat as a separate PR.

**Files:**
- Modify: `config/mmu/base/mmu_parameters.cfg`

- [ ] **Step 1: Read the post-cal `toolhead_residual_filament` value**

Task 11's `DIRTY=1` step derives a fresh value for `toolhead_residual_filament`. Compare HH's saved value to the original `23`:

```bash
grep "^toolhead_residual_filament:" config/mmu/base/mmu_parameters.cfg
```

If the cal-derived value differs from `23`, update `mmu_parameters.cfg` to match.

- [ ] **Step 2: Update `toolhead_residual_filament`**

Use the Edit tool to set the new value with a comment noting the cal date.

- [ ] **Step 3: Commit on a fresh `chore/mmu-drift-cleanup` branch**

```bash
git checkout -b chore/mmu-drift-cleanup
git add config/mmu/base/mmu_parameters.cfg
git commit -m "chore(mmu): align toolhead_residual_filament with post-cal value"
git push -u origin chore/mmu-drift-cleanup
gh pr create --title "chore(mmu): align toolhead_residual_filament with post-cal value" --body "Drift cleanup follow-up to #15. Spec section 7."
```

(Do NOT bundle `gear_from_buffer_accel` bump in the same PR — that's a tuning step that should be measured separately.)

---

## Summary

17 tasks. Of those:

- **3 are normal repo changes:** Task 4 (flag flips PR), Task 16 (post-cal mmu_vars.cfg + memory log commit direct-to-main), Task 17 (optional drift cleanup PR).
- **3 are operator-physical / standby:** Task 2 (servo inspection), Task 8 (gear gate-0 cal mark + measure), Task 11 (toolhead cal — operator standby while HH runs).
- **The rest are Claude-orchestrated Moonraker + SSH + sync-from-pi steps.**

Estimated wall-clock time: ~75 minutes if everything passes first try (45 minutes operator-at-printer, 30 minutes monitoring).

Hard failure-class branches all return to spec section 6 for guidance.
