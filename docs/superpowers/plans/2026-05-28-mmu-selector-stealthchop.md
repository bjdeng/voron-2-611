# MMU Selector stealthChop (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the MMU selector stepper in stealthChop for quieter gate-change moves, at zero torque-margin cost, by adding one TMC field to `mmu_hardware.cfg`.

**Architecture:** The selector carries no filament load and homes against a physical microswitch (`mmu_sel_home`), so stealthChop costs no reliability margin. A single declarative `stealthchop_threshold: 250` keeps every selector move (max 200 mm/s) in stealthChop. The gear stepper is untouched (it needs spreadCycle torque). Two CLAUDE.md corrections capture facts verified during design.

**Tech Stack:** Klipper TMC2209 config, Happy-Hare `_MMU_TEST` selector soak commands, the repo's CI subset (`make test-py`), `/deploy-to-pi`.

**Spec:** `docs/superpowers/specs/2026-05-28-mmu-stepper-quieting-design.md`

---

## Critical context for the executor

- **CI does NOT validate this change's config parse.** `.github/workflows/ci.yml:109-129` strips the `[include mmu/...]` lines from `printer.cfg` before the klippy parse (Happy-Hare is incompatible with CI's klippy harness). So `mmu_hardware.cfg` is only seen by macro-refcheck (no macros change here) and pre-commit text hygiene. **A green CI is NOT proof the config parses.** The authoritative parse check is on the Pi at RESTART (Task 4).
- **Restart class: `RESTART`, not `FIRMWARE_RESTART`.** `stealthchop_threshold` is a TMC UART register re-sent on host config reload. A plain RESTART also avoids the EASY-BRD USB re-enumeration race that bites on FIRMWARE_RESTART.
- **`mmu_hardware.cfg` is a real file on the Pi** (verified 2026-05-28), so the normal repo→PR→`/deploy-to-pi` flow pushes it; the deploy script's symlink-exclusion does not skip it.
- **Per CLAUDE.md:** show the diff before writing any `.cfg` edit; run `pr-review-toolkit:review-pr` BEFORE pushing; use a worktree for implementation; clean up the worktree after squash-merge.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `config/mmu/base/mmu_hardware.cfg` | Modify (`[tmc2209 stepper_mmu_selector]`) | Add `stealthchop_threshold: 250` |
| `CLAUDE.md` | Modify (Known quirks + vendor table + layout count) | Correct the `mmu_hardware.cfg` symlink claim; register `vendor/klipper-tmc-autotune` |
| `memory/tuning-log.md` | Append | Record the change + soak/acoustic result |
| `docs/superpowers/specs/2026-05-28-mmu-stepper-quieting-design.md` | Modify (Status) | Mark Phase 1 shipped |

---

## Task 0: Worktree setup

- [ ] **Step 1: Create an isolated worktree**

Use the `superpowers:using-git-worktrees` skill (native `EnterWorktree`). Branch name: `feat/mmu-selector-stealthchop`. All subsequent tasks run inside that worktree.

---

## Task 1: Add stealthChop to the selector TMC driver

**Files:**
- Modify: `config/mmu/base/mmu_hardware.cfg` (the `[tmc2209 stepper_mmu_selector]` block, ~line 153-160)

- [ ] **Step 1: Show the diff, then make the edit**

In `[tmc2209 stepper_mmu_selector]`, change the `stealthchop_threshold` line. Exact replacement:

Old:
```ini
sense_resistor: 0.110
stealthchop_threshold: 0		# Stallguard "touch" movement (slower speeds) best done with stealthchop
```

New:
```ini
sense_resistor: 0.110
stealthchop_threshold: 250		# stealthChop below 250 mm/s; selector max is 200 mm/s (quiet gate changes, no filament load)
```

Leave `[tmc2209 stepper_mmu_gear]` and everything else unchanged.

- [ ] **Step 2: Run the local CI subset**

Run: `make test-py`
Expected: PASS (refcheck + pytest + pre-commit). This confirms no macro-reference or text-hygiene regression. It does NOT validate the MMU config parse — that happens in Task 4.

- [ ] **Step 3: Commit**

```bash
git add config/mmu/base/mmu_hardware.cfg
git commit -m "$(cat <<'EOF'
feat(mmu): selector stealthChop for quieter gate changes

stealthchop_threshold 0 -> 250 on stepper_mmu_selector. Selector max move
is 200 mm/s with no filament load and physical-endstop homing, so
stealthChop costs no torque margin. Gear stepper unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Correct CLAUDE.md (symlink claim + vendor registration)

**Files:**
- Modify: `CLAUDE.md` (Known quirks line ~237, exception bullet ~252, vendor table, layout submodule count)

- [ ] **Step 1: Soften the blanket symlink claim (Known quirks)**

Old:
```markdown
- **MMU `config/mmu/base/*.cfg` are symlinks on the Pi** to `~/Happy-Hare/config/base/*`. In this repo they're files (dereferenced by `tar -h` on pull). If you push this repo back to the Pi without preserving symlinks, you'll break Happy-Hare's update model.
```

New:
```markdown
- **MMU `config/mmu/base/*.cfg` are *mostly* symlinks on the Pi** to `~/Happy-Hare/config/base/*` (two real-file exceptions: `mmu_parameters.cfg` and `mmu_hardware.cfg` — see below). In this repo they're files (dereferenced by `tar -h` on pull). If you push this repo back to the Pi without preserving symlinks, you'll break Happy-Hare's update model.
```

- [ ] **Step 2: Add the `mmu_hardware.cfg` exception bullet**

Find the existing `mmu_parameters.cfg is NOT a Pi-side symlink` bullet. Immediately after it, add a new bullet:

```markdown
- **`config/mmu/base/mmu_hardware.cfg` is also NOT a Pi-side symlink** — like `mmu_parameters.cfg`, HH writes it as a real file at install and never wholesale-overwrites it on update (`install.sh`'s `upgrade_mmu_hardware()` only applies targeted `sed` migrations). So TMC edits (`run_current`, `stealthchop_threshold`, etc.) deploy via the normal repo→PR→`/deploy-to-pi` flow and survive HH updates. Verified 2026-05-28 by `ls -l` on the Pi showing a regular file. (Corrects an earlier claim that all `mmu/base/*.cfg` are symlinked.) One residual risk: a *fresh* HH reinstall would regenerate this file from template, silently reverting the edit — `/sync-from-pi` drift detection is the backstop.
```

- [ ] **Step 3: Register the autotune submodule in the vendor table**

In the `## Vendor / submodules` table, add a row after the `vendor/btt-docs` row:

```markdown
| `vendor/klipper-tmc-autotune` | andrewmcgr/klipper_tmc_autotune | `57eda7f` (v0.2.0-363) | TMC autotune extension — source of `[autotune_tmc]` blocks + `motor_database.cfg` (used by `config/motion.cfg`) |
```

- [ ] **Step 4: Bump the submodule count in the repo-layout tree**

Old:
```
└── vendor/                      # 7 git submodules — see ## Vendor / submodules
```

New:
```
└── vendor/                      # 8 git submodules — see ## Vendor / submodules
```

- [ ] **Step 5: Run text-hygiene hook + commit**

Run: `make test-py`
Expected: PASS.

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: correct mmu_hardware.cfg symlink claim, register tmc-autotune vendor

Verified mmu_hardware.cfg is a real file on the Pi (not a symlink), same as
mmu_parameters.cfg. Adds the klipper-tmc-autotune submodule to the vendor
table (8th submodule) and bumps the layout count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Pre-push review and PR

- [ ] **Step 1: Run the PR review toolkit BEFORE pushing**

Invoke `Skill: pr-review-toolkit:review-pr` against the branch diff (`git diff main...HEAD`). This is a hard requirement per repo memory — no "trivial" exemption.

- [ ] **Step 2: Address any findings**

Fix issues as fixup commits on the branch (do NOT amend). Re-run `make test-py` after fixes.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/mmu-selector-stealthchop
gh pr create --title "feat(mmu): selector stealthChop for quieter gate changes" --body "$(cat <<'EOF'
## Summary
- Selector stepper -> stealthChop (`stealthchop_threshold` 0→250). No filament load, physical-endstop home, so no torque-margin cost. Quiets gate-change moves.
- Gear stepper untouched (needs spreadCycle torque).
- Docs: correct the `mmu_hardware.cfg` symlink claim (it's a real file) and register the `klipper-tmc-autotune` vendor submodule.

Spec: `docs/superpowers/specs/2026-05-28-mmu-stepper-quieting-design.md` (Phase 1).

## Restart impact
`RESTART` (not `FIRMWARE_RESTART`) — TMC UART register.

## Note
CI strips MMU includes before the klippy parse, so CI does NOT validate this config's parse. Parse + behavior are validated on the Pi post-merge (see plan Task 4).

## Test plan
- [ ] `make test-py` green
- [ ] Pi RESTART parses clean (klippy.log "Klipper ready")
- [ ] Selector soak: no `DID NOT HOME` / `Off target`, TMC flags clean
- [ ] Acoustic A/B improvement on gate changes
- [ ] Babysat multi-tool print seats selector correctly
EOF
)"
```

- [ ] **Step 4: Squash-merge after approval**, then clean up the worktree (`git worktree remove` + `git branch -D feat/mmu-selector-stealthchop`) per repo memory.

---

## Task 4: Deploy and validate on hardware (post-merge, operational)

Run from `main` after the squash-merge. **Confirm the printer is idle first** (`printer.print_stats.state` — never assume idle from history).

- [ ] **Step 1: Deploy**

Invoke `/deploy-to-pi`. It refuses if CI isn't green, the printer is busy, or the Pi has drift — follow its guidance.

- [ ] **Step 2: RESTART and confirm the config parses**

In the Mainsail/Klipper console: `RESTART`. Because CI never parsed the MMU config, this is the real parse gate. Confirm Klipper reaches "Klipper ready" and check the log over SSH:
```bash
ssh pi@mainsailos.local 'tail -n 60 ~/printer_data/logs/klippy.log'
```
Expected: no config errors, no "must be specified" / unknown-field errors on `stepper_mmu_selector`.

- [ ] **Step 3: Capture the before/after driver state**

```
DUMP_TMC STEPPER=stepper_mmu_selector
```
Expected: confirms the driver is reachable; note `otpw`/open-load flags are clear. (Optional baseline: this also shows `tpwmthrs` now reflects the 250 threshold.)

- [ ] **Step 4: Reliability soak — MMU UNLOADED, no filament in any gate**

Confirm the MMU is unloaded first. Bracket with homing, then exercise the selector at the real operating point. While running, tail the log in another shell:
```bash
ssh pi@mainsailos.local "tail -f ~/printer_data/logs/klippy.log | grep -iE 'DID NOT HOME|Off target|tracking error|otpw|shutdown'"
```
Console commands:
```
MMU_HOME
_MMU_TEST SEL_HOMING_MOVE=1 MOVE=-100 SPEED=200 ACCEL=1200 ENDSTOP=mmu_sel_home LOOP=50
_MMU_TEST SEL_MOVE=1 MOVE=80 SPEED=200 ACCEL=1200 LOOP=50
MMU_HOME
```
Expected: every `SEL_HOMING_MOVE` iteration logs `homed` (never `DID NOT HOME`); `Off target position by` deltas stay ~0; the closing `MMU_HOME` succeeds with normal travel. Do NOT use `SEL_LOAD_TEST` — it randomly invokes touch-homing against the unconfigured `mmu_sel_touch` endstop and will throw unrelated errors.

- [ ] **Step 5: Acoustic A/B**

Re-run the same command block and rate gate-change noise on the established scale, comparing against memory of the spreadCycle baseline. Expected: quieter or equal.

- [ ] **Step 6: Real print check**

Run one babysat multi-tool print; confirm tool changes seat the selector correctly (no mis-gate, no homing fault mid-print).

---

## Task 5: Record outcome

**Files:**
- Modify: `memory/tuning-log.md` (append)
- Modify: `docs/superpowers/specs/2026-05-28-mmu-stepper-quieting-design.md` (Status line)

- [ ] **Step 1: Append a tuning-log entry**

Add a dated entry to `memory/tuning-log.md` recording: the change (`stepper_mmu_selector stealthchop_threshold 0→250`), the soak result (loops run, any off-target/home failures), the acoustic rating delta, and motor-temp/TMC-flag observations.

- [ ] **Step 2: Mark the spec Phase 1 shipped**

In the spec, change `**Status:** approved (brainstorming)` to `**Status:** Phase 1 shipped YYYY-MM-DD; Phase 2 deferred`.

- [ ] **Step 3: Commit (docs-only, may go direct to main per repo memory)**

```bash
git add memory/tuning-log.md docs/superpowers/specs/2026-05-28-mmu-stepper-quieting-design.md
git commit -m "$(cat <<'EOF'
docs: record MMU selector stealthChop soak result, mark Phase 1 shipped

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** Phase 1 change (Task 1), both CLAUDE.md corrections (Task 2), validation protocol incl. unloaded-MMU + `SEL_HOMING_MOVE`/`SEL_MOVE` + missed-step watch + avoid `SEL_LOAD_TEST` (Task 4), rollback (documented in spec; revert one line + RESTART). Phase 2 is explicitly out of this plan. Covered.
- **Restart class** stated consistently as `RESTART` in Task 1 commit context and Task 4.
- **No structural regression test added:** intentional — `tests/test_config_structure.py` excludes `config/mmu/base/`, so a guard there would fight the existing design and exceed approved scope. Silent-revert risk (fresh HH reinstall) is documented in the CLAUDE.md bullet instead.
- **Placeholder scan:** the only `YYYY-MM-DD` tokens are date-stamps the executor fills at run time (tuning-log entry, spec status) — intentional, not unspecified logic.
