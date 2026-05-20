# Microsteps 128→64 + TMC Autotune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce stepper noise via two independent levers — microsteps 128→64 (Phase A) and TMC Autotune installation (Phase B) — with empirical validation at each phase.

**Architecture:** Sequential two-phase rollout. Phase A is a single-file edit (motion.cfg) following the standard branch → PR → CI → deploy → verify cycle. Phase B layers on top of Phase A's outcome and is more involved: vendor submodule + Pi install.sh + repo config additions for moonraker update_manager + per-stepper config blocks. Each phase has independent success criteria and rollback. Phase B prerequisite: Phase A complete (success OR rollback).

**Tech Stack:** Klipper config (motion.cfg, moonraker.conf), GitHub Actions CI (workflow at .github/workflows/ci.yml), `scripts/deploy_to_pi.sh` deploy skill, klippain_tmc_autotune (third-party Klipper extension).

**Source spec:** [docs/superpowers/specs/2026-05-20-microsteps-128-to-64.md](../specs/2026-05-20-microsteps-128-to-64.md)

**Closes:** [#24](https://github.com/bjdeng/voron-2-611/issues/24)

---

## File Structure (Phases A + B)

**Files modified by Phase A:**
- `config/motion.cfg` — change `microsteps: 128` → `microsteps: 64` in 6 stepper sections

**Files modified by Phase B (if Phase A succeeds and we proceed):**
- `config/moonraker.conf` — add `[update_manager TMC_Autotune]` block
- `config/motion.cfg` — add `[autotune_tmc stepper_*]` blocks for 6 mainboard steppers
- `.gitmodules` — register `vendor/klipper-tmc-autotune` submodule
- `vendor/klipper-tmc-autotune/` — new submodule directory

**Files possibly modified after success (either phase):**
- `CLAUDE.md` — update "Known quirks" entry about microsteps 128
- `memory/tuning-log.md` — record the outcome with date + measurements

**Pi-side actions (not in repo):**
- `~/klippain_tmc_autotune/` — cloned by install.sh
- `~/klipper/klippy/extras/autotune_tmc.py` — symlink created by install.sh

---

# Phase A: Microsteps 128 → 64

### Task A1: Capture baseline (BEFORE any change)

**Files:** None — observational data collection only.

- [ ] **Step 1: Confirm printer is homed + QGL'd**

```bash
curl -sS 'http://mainsailos.local:7125/printer/objects/query?toolhead' | python3 -c "
import sys, json
t = json.loads(sys.stdin.read())['result']['status']['toolhead']
print('homed_axes:', t['homed_axes'])
"
```

Expected: `homed_axes: xyz`. If empty/partial, run:

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' \
  http://mainsailos.local:7125/printer/gcode/script
```

- [ ] **Step 2: Run TEST_SPEED twice; record observations**

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"script":"TEST_SPEED"}' \
  http://mainsailos.local:7125/printer/gcode/script
```

Wait for first run to complete (~2-3 min — listen for it to stop), then re-run. After each, record in a scratch note:
- Subjective noise rating (1-5, where 5 = loudest)
- Any abnormal sounds (clunks, screeches, missed-step clicks)
- TEST_SPEED's reported final position diff (check Mainsail console output)

- [ ] **Step 3: Capture step_compress baseline**

```bash
ssh pi@mainsailos.local "grep -c step_compress ~/printer_data/logs/klippy.log"
```

Expected: `0` (matches current observation). Record this as the baseline.

### Task A2: Branch + edit motion.cfg

**Files:**
- Modify: `config/motion.cfg` — 6 lines

- [ ] **Step 1: Branch off main**

```bash
git checkout main && git pull --ff-only
git checkout -b chore/microsteps-128-to-64
```

- [ ] **Step 2: Edit motion.cfg**

The 6 microsteps lines are at lines 35, 59, 88, 111, 128, 145. Find each `microsteps: 128` line under a `[stepper_x]`, `[stepper_y]`, `[stepper_z]`, `[stepper_z1]`, `[stepper_z2]`, `[stepper_z3]` section and change to `microsteps: 64`. No other changes.

```bash
sed -i.bak 's/^microsteps: 128$/microsteps: 64/' config/motion.cfg
diff config/motion.cfg.bak config/motion.cfg
rm config/motion.cfg.bak
```

Expected diff: 6 `< microsteps: 128` lines vs 6 `> microsteps: 64` lines.

If sed matches more or fewer than 6, manual edit required — check that each match is under one of the 6 stepper sections, not under a TMC block.

- [ ] **Step 3: Commit**

```bash
git add config/motion.cfg
git commit -m "$(cat <<'EOF'
chore: microsteps 128 → 64 on mainboard steppers (Phase A of issue #24)

Per spec docs/superpowers/specs/2026-05-20-microsteps-128-to-64.md.
Halves X/Y MCU step rate (was ~92% of LPC1769 USB budget at
max_velocity) for the same audible noise per Klipper docs
(TMC_Drivers.md:106-109). Validates the long-standing forum-advice
config empirically on this machine.

Restart impact: RESTART (Python-side stepper config + TMC register
writes).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task A3: Local CI gates

**Files:** None — runs against working tree.

- [ ] **Step 1: Run refcheck + pytest**

```bash
make refcheck && make test-py
```

Expected: macro_refcheck passes; 91 tests pass; pre-commit hooks pass.

- [ ] **Step 2: If anything fails, fix and re-commit; do not push**

If pre-commit auto-fixes formatting, run `git add -u && git commit --amend --no-edit` before push. (Note: amend is OK here because the commit is not yet pushed.)

### Task A4: Push branch + open PR

**Files:** None — git/GitHub operations.

- [ ] **Step 1: Push branch**

```bash
git push -u origin chore/microsteps-128-to-64
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "chore: microsteps 128 → 64 (Phase A of issue #24)" --body "$(cat <<'EOF'
## Summary
Phase A of the noise-reduction effort spec'd in [docs/superpowers/specs/2026-05-20-microsteps-128-to-64.md](docs/superpowers/specs/2026-05-20-microsteps-128-to-64.md). Drops 6 mainboard steppers (X, Y, Z, Z1, Z2, Z3) from microsteps:128 to 64. Closes [#24](https://github.com/bjdeng/voron-2-611/issues/24) after deploy + validation.

## Why
- Klipper docs (TMC_Drivers.md:106-109) say 64 = 128 acoustically with interpolate:False
- Frees ~50% LPC1769 USB step-rate budget at max_velocity (currently ~92% utilized)
- Tests the long-standing forum-advice config empirically on this machine

## Restart impact
RESTART (Python-side stepper config + TMC register writes; no MCU pin / kinematics change).

## Test plan
Per spec § Phase A Test sequence:
- [x] Baseline TEST_SPEED + step_compress capture (Task A1)
- [ ] Post-deploy: re-run TEST_SPEED; verify equal-or-quieter noise + zero position drift
- [ ] Quick test print: small benchy / Voron cube; visual inspection
- [ ] Re-check step_compress count (expect 0)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Record the PR number from the output (e.g. `#NN`).

### Task A5: Wait for CI, then squash-merge

**Files:** None.

- [ ] **Step 1: Watch CI to completion**

```bash
gh pr checks <PR#> --watch
```

Expected: both `Klippy parse + MCU load` and `pre-commit + macro refcheck + pytest` end as `pass`.

- [ ] **Step 2: Squash-merge + delete branch**

```bash
gh pr merge <PR#> --squash --delete-branch
git checkout main && git pull --ff-only
```

- [ ] **Step 3: Wait for post-merge CI on main**

```bash
until gh run list --branch main --workflow ci.yml --limit 1 --json status -q '.[0].status' | grep -q completed; do sleep 15; done
gh run list --branch main --workflow ci.yml --limit 1 --json conclusion -q '.[0].conclusion'
```

Expected: `success`. If the post-merge run didn't trigger (yaml-only edge case), use `gh workflow run ci.yml --ref main` to force one.

### Task A6: Deploy

**Files:** None — uses scripts/deploy_to_pi.sh.

- [ ] **Step 1: Deploy via the script**

```bash
scripts/deploy_to_pi.sh --yes
```

Expected end-of-output: `==> Deploy complete. Verify printer state in Mainsail.` and `state=ready` from the Klipper poll.

If deploy errors with "CI not green": verify the post-merge CI completed (Task A5 Step 3). If "drift detected": run `scripts/sync_from_pi.sh` first to capture Pi-side state.

### Task A7: Post-change TEST_SPEED verification

**Files:** None — observational.

- [ ] **Step 1: Home + QGL (firmware restart cleared homing state)**

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' \
  http://mainsailos.local:7125/printer/gcode/script
```

- [ ] **Step 2: Run TEST_SPEED twice; record observations**

Same procedure as Task A1 Step 2. Record noise rating + position diff per run.

- [ ] **Step 3: Compare against baseline**

| Metric | Baseline (A1) | Post-change (A7) | Status |
|---|---|---|---|
| Noise rating | _____ | _____ | _____ |
| Position diff run 1 | _____ | _____ | _____ |
| Position diff run 2 | _____ | _____ | _____ |
| Abnormal sounds | _____ | _____ | _____ |

If noise is worse OR position diff > 0.1mm OR new abnormal sounds: STOP, go to Task A10 (rollback).

### Task A8: Test print + visual inspection

**Files:** None — physical print + visual observation.

- [ ] **Step 1: Slice and print a small test object**

Use the `0.20mm Speed @Voron 2.611` process profile. Recommended models:
- Voron cube (~30 min print, well-known reference)
- Small benchy (~25 min, exercises overhangs + bridges)

Slicer accel/speed already updated per today's audit — no slicer changes needed.

- [ ] **Step 2: Inspect surface quality**

Compare to a recent print at the prior 128 microsteps setting. Look for:
- New ringing / ghosting on walls (Y-direction more likely than X based on shaper smoothing characteristics)
- Layer adhesion regressions
- Visible step quantization artifacts (very unlikely)

If any new artifacts appear: STOP, go to Task A10 (rollback).

### Task A9: Check klippy.log for step_compress

**Files:** None — log inspection.

- [ ] **Step 1: Grep klippy.log**

```bash
ssh pi@mainsailos.local "grep -c step_compress ~/printer_data/logs/klippy.log"
```

Expected: `0` (same as baseline). If non-zero: investigate the specific events — the test print may have hit MCU rate limits despite the headroom gain (unlikely but possible if input shaper schedules unusually dense bursts).

### Task A10: Phase A decision point

**Files:** None — decision only.

- [ ] **Step 1: Evaluate against success criteria (all must pass)**

| Criterion | Pass threshold | Actual | Pass? |
|---|---|---|---|
| TEST_SPEED skip check | Position diff < 0.1 mm | | |
| Subjective noise | ≤ baseline rating | | |
| Test print surface | No new artifacts | | |
| MCU step rate | Zero `step_compress` warnings | | |

- [ ] **Step 2: Pick path**

**All pass → SUCCESS path:** Proceed to Task A11 (update docs), then optionally Phase B.

**Any fail → ROLLBACK path:** Proceed to Task A11-revert.

### Task A11 (SUCCESS): Update docs

**Files:**
- Modify: `CLAUDE.md` — "Known quirks" section
- Modify: `memory/tuning-log.md` — record outcome

- [ ] **Step 1: Update CLAUDE.md Known quirks entry**

Find the entry that begins "**Microsteps 128 on X/Y/Z** (atypically high)" and update to reflect the new state. Replace with text like:

```markdown
- **Microsteps 64 on X/Y/Z mainboard steppers** (was 128 from prior forum advice; validated 2026-MM-DD via test plan #24). `interpolate: False` retained. Empirically confirmed: ≥ baseline quietness, no missed steps, zero step_compress warnings. Recovered ~50% LPC1769 USB step rate budget at max_velocity.
```

- [ ] **Step 2: Update memory/tuning-log.md**

Append an entry with the date, baseline observations, post-change observations, and the merged PR number.

- [ ] **Step 3: Commit + push (docs-only direct to main per CLAUDE.md memory)**

```bash
git add CLAUDE.md memory/tuning-log.md
git commit -m "docs: record microsteps 128→64 outcome (closes #24 Phase A)"
git push
```

- [ ] **Step 4: Close issue #24 with the outcome**

```bash
gh issue close 24 --comment "Phase A complete (microsteps 128→64). Validated per the test plan: [link to merged PR]. Phase B (TMC Autotune) is a separate follow-up — open as needed."
```

### Task A11-revert (FAILURE): Roll back

**Files:**
- Modify: `config/motion.cfg` — restore 6 microsteps lines to 128

- [ ] **Step 1: Branch + revert**

```bash
git checkout main && git pull --ff-only
git checkout -b chore/revert-microsteps-128-to-64
sed -i.bak 's/^microsteps: 64$/microsteps: 128/' config/motion.cfg
rm config/motion.cfg.bak
git add config/motion.cfg
git commit -m "revert: restore microsteps:128 — Phase A of #24 failed validation"
git push -u origin chore/revert-microsteps-128-to-64
```

- [ ] **Step 2: PR + merge**

```bash
gh pr create --title "revert: restore microsteps:128 — Phase A of #24 failed" --body "Test plan failed [specific criterion]. Reverting per spec rollback procedure."
# wait for CI
gh pr checks <PR#> --watch
gh pr merge <PR#> --squash --delete-branch
```

- [ ] **Step 3: Deploy**

```bash
git checkout main && git pull --ff-only
scripts/deploy_to_pi.sh --yes
```

- [ ] **Step 4: Close issue #24 with the empirical evidence**

```bash
gh issue close 24 --comment "Phase A test plan failed: [criterion + measurement]. Reverted. Keeping microsteps:128 as the empirically validated choice for this machine."
```

If Phase A reverted, you can still proceed to Phase B independently — TMC Autotune layers on whatever microstep setting is in place.

---

# Phase B: TMC Autotune installation + tuning

**Prerequisite:** Phase A complete (success or rollback). Phase B should run AFTER Phase A's printer state is final.

### Task B1: Identify motor models

**Files:** None — physical inspection.

- [ ] **Step 1: Identify the actual stepper motors on the printer**

Either:
- Physically inspect the steppers — model number printed on the side
- Check the original BOM / order receipts for X, Y, Z motors
- Most Voron 2.4 r2 builds default to LDO-42STH48-2504AC for X/Y and LDO-42STH48-2004MAH for Z, but CLAUDE.md notes Ben self-sourced from BOM and may differ

Record the model per stepper:
- X: omc-17HS19-2004S1
- Y: omc-17HS19-2004S1
- Z (all 4 should be identical): omc-17HS19-2004S1

- [ ] **Step 2: Verify motor models exist in TMC Autotune motor database**

```bash
# After install (Task B5), check; or check upstream beforehand:
curl -s https://raw.githubusercontent.com/andrewmcgr/klipper_tmc_autotune/main/motor_database.cfg | grep -i "ldo-42sth48"
```

Expected: matching entries for both motor models. If not in database, custom motor specs are required — see upstream README.

### Task B2: Capture post-Phase-A baseline

**Files:** None — observational.

- [ ] **Step 1: Run TEST_SPEED twice; record current noise rating**

Same procedure as Task A1. Record:
- Subjective noise rating (this becomes the Phase B baseline)
- Position diff (sanity check)

### Task B3: Vendor klippain_tmc_autotune as submodule

**Files:**
- Create: `vendor/klipper-tmc-autotune/` (submodule)
- Modify: `.gitmodules`

- [ ] **Step 1: Branch**

```bash
git checkout main && git pull --ff-only
git checkout -b chore/vendor-tmc-autotune
```

- [ ] **Step 2: Add submodule**

```bash
git submodule add https://github.com/andrewmcgr/klipper_tmc_autotune.git vendor/klipper-tmc-autotune
```

- [ ] **Step 3: Verify .gitmodules updated**

```bash
cat .gitmodules | grep -A 2 tmc-autotune
```

Expected output:
```
[submodule "vendor/klipper-tmc-autotune"]
        path = vendor/klipper-tmc-autotune
        url = https://github.com/andrewmcgr/klipper_tmc_autotune.git
```

### Task B4: Add update_manager block to moonraker.conf

**Files:**
- Modify: `config/moonraker.conf`

- [ ] **Step 1: Find a good location**

The existing `[update_manager *]` blocks are clustered together. Find them:

```bash
grep -n "^\[update_manager" config/moonraker.conf
```

Insert the new block after the last existing one (alphabetical-ish order is fine).

- [ ] **Step 2: Append the block**

Add this exact block to `config/moonraker.conf`:

```ini
[update_manager TMC_Autotune]
type: git_repo
path: ~/klippain_tmc_autotune
origin: https://github.com/andrewmcgr/klipper_tmc_autotune.git
managed_services: klipper
primary_branch: main
```

The `path` MUST be `~/klippain_tmc_autotune` (the upstream install.sh clones there; matching this lets moonraker keep it updated).

### Task B5: Run install.sh on the Pi

**Files:** None — Pi-side action.

- [ ] **Step 1: Confirm sudo password is in .env**

```bash
grep PI_SSH_PASSWORD .env
```

- [ ] **Step 2: Run upstream install.sh with sudo via stdin pattern**

```bash
ssh -tt pi@mainsailos.local "echo 'raspberry' | sudo -S -v && wget -qO - https://raw.githubusercontent.com/andrewmcgr/klipper_tmc_autotune/main/install.sh | bash"
```

Watch for:
- "Cloning" / "Installation successful" messages
- Symlink creation into `~/klipper/klippy/extras/`
- Klipper service restart

Expected: install.sh exits 0. Pi will have:
- `~/klippain_tmc_autotune/` directory
- `~/klipper/klippy/extras/autotune_tmc.py` (symlink)
- Probably an appended `[update_manager TMC_Autotune]` in PI's moonraker.conf — about to be overwritten by Task B7 deploy, but Task B4 made sure our repo's moonraker.conf has the same block

### Task B6: Add [autotune_tmc] config blocks to motion.cfg

**Files:**
- Modify: `config/motion.cfg` — append 6 blocks

- [ ] **Step 1: Find the TMC sections to anchor against**

```bash
grep -n "^\[tmc2209 stepper_" config/motion.cfg
```

Expected: 6 lines, one per stepper.

- [ ] **Step 2: Add a section block for autotune**

Append to the end of `config/motion.cfg` (after the existing `[input_shaper]` block):

```ini

#####################################################################
#   TMC Autotune (per-motor chopper tuning)
#####################################################################
# Replace `<motor_model>` below with the actual motor model identified
# in Phase B Task B1. Common Voron defaults: LDO-42STH48-2504AC for X/Y
# and LDO-42STH48-2004MAH for Z. Motor model must match an entry in
# `vendor/klipper-tmc-autotune/motor_database.cfg`.

[autotune_tmc stepper_x]
motor: <motor_model>
voltage: 24

[autotune_tmc stepper_y]
motor: <motor_model>
voltage: 24

[autotune_tmc stepper_z]
motor: <motor_model>
voltage: 24

[autotune_tmc stepper_z1]
motor: <motor_model>
voltage: 24

[autotune_tmc stepper_z2]
motor: <motor_model>
voltage: 24

[autotune_tmc stepper_z3]
motor: <motor_model>
voltage: 24
```

Replace `<motor_model>` with the actual values from Task B1. Z motors share a model so all four get the same value.

### Task B7: Local CI gates

**Files:** None.

- [ ] **Step 1: Run refcheck + pytest**

```bash
make refcheck && make test-py
```

Expected: all green. The L3 klippy parse in CI will fail (autotune_tmc isn't in vanilla klippy/extras/), but that's not run locally on macOS via `make test-py`.

- [ ] **Step 2: Predict the CI failure mode**

`Klippy parse + MCU load` in CI will see `[autotune_tmc stepper_x]` and error with "Section 'autotune_tmc stepper_x' is not a valid config section" — same pattern as the shaketune issue resolved in PR #86. Two options:

**Option (a):** Add a CI strip step in `.github/workflows/ci.yml` (mirror the shaketune pattern). This is the right long-term answer.

**Option (b):** Add a symlink-into-vendor-klipper step in CI that uses the vendored `klipper-tmc-autotune` submodule.

Option (b) is cleaner — we vendored the submodule for exactly this case. The shaketune CI strip was a workaround because we didn't vendor it (and that's tracked as a follow-up).

- [ ] **Step 3: Add the symlink step to ci.yml**

Find the `Strip [shaketune] from system.cfg` step in `.github/workflows/ci.yml`. Add a NEW step BEFORE it:

```yaml
      - name: Symlink TMC Autotune extension into vendor/klipper
        # We vendored klipper-tmc-autotune (Phase B Task B3). Symlink its
        # autotune_tmc.py into vendor/klipper/klippy/extras/ so the klippy
        # parse step recognizes the [autotune_tmc] sections.
        run: |
          ln -sf ${{ github.workspace }}/vendor/klipper-tmc-autotune/autotune_tmc.py vendor/klipper/klippy/extras/autotune_tmc.py
          ln -sf ${{ github.workspace }}/vendor/klipper-tmc-autotune/motor_database.cfg vendor/klipper/klippy/extras/motor_database.cfg
```

Note: confirm the exact file paths match upstream's repo layout before relying on this — `ls vendor/klipper-tmc-autotune/` after Task B3 will show the actual file names.

### Task B8: Commit + push branch

**Files:** None — git operations.

- [ ] **Step 1: Stage and commit**

```bash
git add .gitmodules vendor/klipper-tmc-autotune config/moonraker.conf config/motion.cfg .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
chore: install TMC Autotune (Phase B of issue #24)

Adds klippain_tmc_autotune as a vendored submodule (consistent with
happy-hare/eddy-ng/shaketune pattern) plus the per-stepper
[autotune_tmc] config blocks in motion.cfg. Auto-tunes TMC2209 chopper
parameters (TOFF, TBL, HEND, HSTRT, PWM_FREQ) from motor specs;
community reports 5-15% noise reduction on spreadCycle TMC2209 setups.

moonraker.conf gets the [update_manager TMC_Autotune] block in the
repo (avoids the deploy footgun from #87 where install.sh's
moonraker.conf addition gets wiped on next deploy).

CI gains a symlink step so klippy parse sees the [autotune_tmc] sections.

Restart impact: RESTART (Python extension load + TMC register writes
via UART).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push -u origin chore/vendor-tmc-autotune
```

### Task B9: Open PR + wait for CI + merge

**Files:** None.

- [ ] **Step 1: Open PR**

```bash
gh pr create --title "chore: install TMC Autotune (Phase B of issue #24)" --body "$(cat <<'EOF'
## Summary
Phase B of the noise-reduction effort spec'd in [docs/superpowers/specs/2026-05-20-microsteps-128-to-64.md](docs/superpowers/specs/2026-05-20-microsteps-128-to-64.md). Vendors `klippain_tmc_autotune` (matches the existing happy-hare/eddy-ng/shaketune install pattern), adds per-stepper `[autotune_tmc]` config blocks, and adds the moonraker `[update_manager]` block to the repo so it survives deploys (per [#87](https://github.com/bjdeng/voron-2-611/issues/87)).

## What it does
TMC Autotune computes optimal TMC2209 chopper parameters (TOFF, TBL, HEND, HSTRT, PWM_FREQ, PWM_GRAD) from motor specs (rated current, inductance, resistance) and machine config (max_velocity, max_accel). Runs at startup, writes computed values to driver registers via UART.

## Restart impact
RESTART (Python extension load + TMC register writes; no MCU pin / kinematics change).

## Test plan
Per spec § Phase B Test sequence:
- [x] Motor models identified: X=____, Y=____, Z=____  (Task B1)
- [x] Vendor submodule added; verified motor models in motor_database.cfg
- [ ] Post-deploy: klippy.log shows successful autotune for all 6 steppers
- [ ] TEST_SPEED noise ≤ Phase A baseline
- [ ] Test print: no new artifacts

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Watch CI**

```bash
gh pr checks <PR#> --watch
```

If `Klippy parse + MCU load` fails with "autotune_tmc not a valid config section": the symlink step didn't work — re-check Task B7 Step 3 against actual file paths in `vendor/klipper-tmc-autotune/`.

- [ ] **Step 3: Squash-merge**

```bash
gh pr merge <PR#> --squash --delete-branch
git checkout main && git pull --ff-only
```

- [ ] **Step 4: Wait for post-merge CI**

```bash
until gh run list --branch main --workflow ci.yml --limit 1 --json status -q '.[0].status' | grep -q completed; do sleep 15; done
gh run list --branch main --workflow ci.yml --limit 1 --json conclusion -q '.[0].conclusion'
```

Expected: `success`. Force with `gh workflow run ci.yml --ref main` if not triggered.

### Task B10: Deploy

**Files:** None.

- [ ] **Step 1: Deploy**

```bash
scripts/deploy_to_pi.sh --yes
```

Expected: deploy succeeds, Klipper comes back ready.

### Task B11: Verify autotune ran successfully

**Files:** None — log inspection.

- [ ] **Step 1: Check klippy.log for autotune startup messages**

```bash
ssh pi@mainsailos.local "grep -A 1 'autotune_tmc' ~/printer_data/logs/klippy.log | tail -30"
```

Expected: lines confirming autotune wrote registers for all 6 steppers, no errors.

If errors appear ("motor not in database", "invalid current", etc.): adjust the motor model name in motion.cfg or add custom motor specs per upstream README.

### Task B12: TEST_SPEED comparison

**Files:** None.

- [ ] **Step 1: Home + QGL**

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' \
  http://mainsailos.local:7125/printer/gcode/script
```

- [ ] **Step 2: Run TEST_SPEED twice; record observations**

Same procedure as previous TEST_SPEED tasks.

- [ ] **Step 3: Compare**

| Metric | Phase B baseline (B2) | Post-change (B12) | Status |
|---|---|---|---|
| Noise rating | _____ | _____ | _____ |
| Position diff run 1 | _____ | _____ | _____ |
| Position diff run 2 | _____ | _____ | _____ |

### Task B13: Test print

**Files:** None — physical print.

- [ ] **Step 1: Print the same test object used in Task A8**

Direct A/B comparison — same model, same slicer profile, same filament if possible.

- [ ] **Step 2: Inspect**

Compare the new print to the Phase A test print. Look for:
- New artifacts (unlikely — autotune doesn't change kinematics)
- Surface texture differences (autotune CAN smooth out high-freq stepper noise translation)

### Task B14: Phase B decision point + close issue

**Files:**
- Modify: `CLAUDE.md` — add TMC Autotune note (if kept)
- Modify: `memory/tuning-log.md` — record outcome

- [ ] **Step 1: Evaluate success criteria**

| Criterion | Pass threshold | Actual | Pass? |
|---|---|---|---|
| Autotune startup | klippy.log shows no register-write errors; all 6 steppers tuned | | |
| TEST_SPEED skip check | Position diff < 0.1 mm | | |
| Subjective noise | ≤ Phase A baseline | | |
| Test print surface | No new artifacts vs Phase A test print | | |

- [ ] **Step 2: Document outcome (success path)**

Update CLAUDE.md to mention TMC Autotune is installed (brief note in "Vendor / submodules" section + a line in "Machine context beyond `~/printer_data/config/`"). Add a tuning-log entry.

```bash
git add CLAUDE.md memory/tuning-log.md
git commit -m "docs: record TMC Autotune outcome (closes #24 Phase B)"
git push
```

- [ ] **Step 3: Document outcome (failure path)**

If autotune doesn't help or makes things worse: see spec § Phase B rollback. Remove the `[autotune_tmc]` blocks from motion.cfg and the `[update_manager]` block from moonraker.conf (single PR). Optionally drop the submodule in a follow-up.

```bash
git checkout -b chore/revert-tmc-autotune
# (manually remove the blocks)
git add -u
git commit -m "revert: remove TMC Autotune — Phase B of #24 didn't help"
git push -u origin chore/revert-tmc-autotune
gh pr create ...
```

- [ ] **Step 4: Close issue #24**

```bash
# Success path:
gh issue close 24 --comment "Phase A + Phase B complete. Microsteps 128→64 + TMC Autotune both validated. Noise reduction: [N units measured]. Closes the empirical question raised in this issue."

# Or failure path:
gh issue close 24 --comment "Phase A: [outcome]. Phase B: [outcome]. Final config: [microsteps + autotune state]. Documented in tuning-log.md."
```

---

## Self-review checklist

Run through this before kicking off implementation:

- [ ] **Spec coverage:** Each section of the spec maps to one or more tasks
- [ ] **Placeholder scan:** No "TBD", "TODO", "fill in", "implement later" left in any task. (The `<motor_model>` placeholder in Task B6 is intentional — it MUST be filled in from Task B1's output, with explicit instructions.)
- [ ] **Type consistency:** Config section names match between motion.cfg additions (`[autotune_tmc stepper_x]`) and the CI symlink target (`autotune_tmc.py`)
- [ ] **Decision points are explicit:** Tasks A10 and B14 have ALL/PASS truth tables, not "use judgment"
- [ ] **Rollback paths complete:** A11-revert and B14 failure path both have concrete commands, not just "revert the change"
