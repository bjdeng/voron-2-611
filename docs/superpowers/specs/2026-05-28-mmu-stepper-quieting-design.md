# MMU stepper quieting — design

**Date:** 2026-05-28
**Status:** Phase 1 shipped 2026-05-28 (PR #120); Phase 2 (gear autotune) deferred — see `memory/tuning-log.md`. Acoustic result: modest (only slow homing audibly quieter); gear + servo are the real noise sources.
**Scope:** quieter Happy-Hare MMU operation, minimal reliability risk, speeds unchanged.

## Goal

Make the MMU's load/unload/gate-change motion quieter without giving up
reliability margin and without changing load/unload speeds. Two TMC2209
steppers on the EASY-BRD (SAMD21): `stepper_mmu_gear` and
`stepper_mmu_selector`, both currently spreadCycle-always
(`stealthchop_threshold: 0`), `interpolate: True`, `microsteps: 16`,
`run_current: 0.6`.

## Decisions that bound the design

- **Minimal reliability risk.** No quiet lever may reduce torque margin
  anywhere filament is under load. This rules out lowering the gear's
  `run_current` and rules out putting the gear in stealthChop (its load
  moves run ~1000 RPM, where stealthChop torque collapses).
- **Speeds unchanged.** `gear_from_buffer_speed` / `gear_from_spool_speed`
  / `gear_unload_speed` stay at 100 mm/s; `selector_move_speed` stays at
  200 mm/s. Faster load/unload is a separate future project (it interacts
  with the encoder's ~450 mm/s ceiling and bowden correction).
- **chopper-resonance-tuner (CRT) is dropped.** Confirmed inapplicable:
  `config/chopper_tune.cfg`'s `_chop_workflow` only drives cartesian
  X/Y/Z via G1 moves (lines 140-158). The MMU steppers are Happy-Hare
  manual-steppers, not G-code axes, and there is no accelerometer on the
  ERCF. CRT physically cannot measure these motors.

## Phasing

| Phase | Change | Risk | This spec |
|---|---|---|---|
| 1 | Selector → stealthChop | none (no filament load, physical-endstop home) | **implement** |
| 2 | tmc-autotune on the gear (spreadCycle, chopper-only) | low (torque-neutral) | **document + defer** |

## Deploy-path finding (verified on the Pi)

`config/mmu/base/mmu_hardware.cfg` is a **real file** on the Pi
(`-rw-r--r--`), not a symlink — same status as `mmu_parameters.cfg`.
Verified 2026-05-28 via `ls -l ~/printer_data/config/mmu/base/`. This
matters because:

- `scripts/deploy_to_pi.sh` excludes every Pi-side symlink from the rsync
  push. A real file is **not** excluded, so a normal repo edit to
  `mmu_hardware.cfg` deploys cleanly via `/deploy-to-pi`.
- Happy-Hare's `install.sh` never wholesale-overwrites `mmu_hardware.cfg`
  on update — `upgrade_mmu_hardware()` only applies targeted `sed`
  migrations (section renames, deprecated-key removal). User edits to
  `run_current` / `stealthchop_threshold` survive HH updates.

CLAUDE.md's "Known quirks" currently claims `mmu_hardware.cfg` is a
Pi-side symlink. That claim is **wrong** and is corrected as part of this
work (see Phase 1 tasks).

## Phase 1 — Selector → stealthChop (implement)

### The change

One line added to `[tmc2209 stepper_mmu_selector]` in
`config/mmu/base/mmu_hardware.cfg`:

```ini
stealthchop_threshold: 250    # was 0 (spreadCycle always)
```

Chosen via the declarative config field, not a runtime `SET_TMC_FIELD`
delayed_gcode. The runtime approach (the `_apply_crt_chopper` pattern)
would only be justified if the file were symlink-clobber-prone; it is a
real file, so the declarative one-liner is simpler and deploys normally.

### Why 250

Klipper runs stealthChop **below** `stealthchop_threshold` (mm/s) and
spreadCycle above it. The selector's fastest move is
`selector_move_speed: 200 mm/s` (homing is 60). 250 keeps every selector
move in stealthChop with margin, and leaves a sane spreadCycle fallback if
anyone later raises the move speed past 250. At `rotation_distance: 40`,
200 mm/s is ~300 RPM on a lightly-loaded carriage — comfortably inside
stealthChop's range.

### What does NOT change

`run_current: 0.6`, `microsteps`, `interpolate`, and the entire
`stepper_mmu_gear` / `[tmc2209 stepper_mmu_gear]` config. No torque margin
is surrendered anywhere filament is loaded.

### Restart impact

`RESTART`, **not** `FIRMWARE_RESTART`. `stealthchop_threshold` is a TMC
UART register (TPWMTHRS + spreadCycle bit) re-sent on host config reload.
A plain RESTART also sidesteps the EASY-BRD USB re-enumeration race that
bites on FIRMWARE_RESTART.

### Validation protocol

Run with the **MMU fully unloaded** (no filament in any gate). The
selector tests move only the carriage — `selector.move()` /
`selector.homing_move()` — and never feed filament, so no gate needs
loading. Running unloaded also isolates selector noise from gear/encoder
noise for a clean A/B and guarantees nothing is jammed across the selector
path.

1. **Reliability (objective, self-reporting).** The selector's physical
   `mmu_sel_home` microswitch is ground truth. Bracket the soak with
   `MMU_HOME` on both ends, then run at the real operating point:
   ```
   _MMU_TEST SEL_HOMING_MOVE=1 MOVE=-100 SPEED=200 ACCEL=1200 ENDSTOP=mmu_sel_home LOOP=50
   _MMU_TEST SEL_MOVE=1 MOVE=80 SPEED=200 ACCEL=1200 LOOP=50
   ```
   `SEL_HOMING_MOVE` logs `homed` / `DID NOT HOME` and off-target delta per
   iteration; `SEL_MOVE` logs `Off target position by: X`. A lost step
   surfaces as off-target or a failed home — it cannot hide.
   - **Do NOT use `SEL_LOAD_TEST`.** It randomly invokes touch-homing
     against `mmu_sel_touch`, which is not configured on this build (no
     selector stallguard), so it throws errors unrelated to the test.
   - **Missed-step watch:** tail `klippy.log` over SSH during the soak,
     grep for `DID NOT HOME`, `Off target`, and TMC flags; run
     `DUMP_TMC STEPPER=stepper_mmu_selector` before/after to check `otpw`
     (overtemp) and open-load flags.
2. **Acoustic.** A/B the same command sequence before/after, rated on the
   established noise scale, listening to gate-change moves.
3. **Real print.** One babysat multi-tool print to confirm tool changes
   still seat the selector correctly.

### Rollback

Revert the one line to `stealthchop_threshold: 0`, `RESTART`. Fully
reversible.

### Phase 1 task list

- Edit `config/mmu/base/mmu_hardware.cfg`: add `stealthchop_threshold: 250`
  to `[tmc2209 stepper_mmu_selector]`.
- Correct CLAUDE.md: `mmu_hardware.cfg` is a real file, not a symlink
  (Known quirks section).
- Add `vendor/klipper-tmc-autotune` to the CLAUDE.md vendor/submodules
  table (currently missing).
- Deploy + run the validation protocol above.

## Phase 2 — tmc-autotune on the gear (document + defer)

**Not implemented in this spec.** Recorded here so the path is clear.

**Goal:** torque-neutral chopper optimization on the gear via
`[autotune_tmc stepper_mmu_gear]` with `tuning_goal: performance` (forces
spreadCycle, so current/mode/torque are preserved; only chopper registers
are computed from motor specs). This is the only quiet lever left for the
loud motor that respects minimal-risk.

**Prerequisites (the gates keeping this out of Phase 1):**
1. Phase 1 shipped and validated.
2. **Identify the exact motors.** The vendored DB
   (`vendor/klipper-tmc-autotune/motor_database.cfg`, 201 entries) carries
   ERCF-relevant entries — an "ERCF v1.1 kit motor (NEMA 17)", LDO-36STH
   and OMC-14HS NEMA14 pancakes. This is a self-sourced ERCF, so match by
   reading the physical motor labels (or the build BOM), not by
   assumption. No exact match → use the closest pancake entry or add a
   custom entry from the datasheet.

**Validation (heavier than Phase 1):** the gear path needs filament —
load/unload/cut reliability soak, plus a motor-temperature check (autotune
can shift heat) and by-ear A/B. Confirm via `DUMP_TMC` that `run_current`
is not being dynamically backed off under load in a way that risks the
gear.

**Restart impact:** adding an `[autotune_tmc]` section → `RESTART`
(registers written at connect over UART).

**Deliverable:** Phase 2 likely earns its own spec + plan.

## Out of scope

- Faster load/unload speeds (separate future project).
- The selector servo's PWM buzz (not a stepper lever; often the loudest
  MMU sound, but outside "improve the steppers").
- Gear `run_current` reduction and gear stealthChop (rejected under
  minimal-risk).
- Any chopper-resonance-tuner work on the MMU motors (inapplicable).
