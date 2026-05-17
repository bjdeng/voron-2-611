# MMU calibration recovery + config drift cleanup — spec

**Closes:** [#15 — MMU load/unload failures: filament moves expected distance but doesn't reach toolhead/encoder sensor](https://github.com/bjdeng/voron-2-611/issues/15)

**Owner:** Ben (operator) — runbook is operator-driven; this spec defines the sequence + the small config-side changes.

**Restart impact:** RESTART (no MCU firmware or pin changes).

---

## 1. Problem

Multi-color prints fail at MMU load or unload meaningfully often. The pattern on load: filament has been advanced the distance Happy Hare expects to reach the toolhead sensor (`^!EBB:gpio6`), but the sensor doesn't trigger. On unload: filament has been retracted the distance expected to clear the encoder, but the encoder still reads filament present.

Cumulative stats from `config/mmu/mmu_vars.cfg` (resets pending in 3.2):

| Gate | Loads | Load fails | Load fail % | Unloads | Unload fails | Unload fail % |
|---|---|---|---|---|---|---|
| 0 | 485 | 19 | **3.9%** | 523 | 32 | 6.1% |
| 1 | 250 | 14 | **5.6%** | 267 | 15 | 5.6% |
| 2 | 474 | 69 | **14.6%** | 479 | 17 | 3.5% |
| 3 | 361 | 71 | **19.7%** | 390 | 33 | 8.5% |
| 4 | 556 | 82 | **14.7%** | 590 | 50 | 8.5% |
| 5 | 189 | 33 | **17.5%** | 213 | 34 | 16.0% |

Gates 0–1 fail at ~5%. Gates 2–5 fail at 14–20%. The pattern is too clean to be random.

## 2. Diagnosis

Three reinforcing pieces of evidence:

**A. Per-gate gear rotation distances are clustered into two groups.**
`mmu_gear_rotation_distances = [23.6262, 23.768, 23.3557, 23.3051, 23.0807, 22.9241]` — gates 0–1 at ~23.7, gates 2–5 at 22.9–23.4 (3.6% spread). The split tracks the failure-rate split exactly.

**B. The auto-correction that should fix this is dead code.**
`autotune_rotation_distance: 1` is set in our config, but `vendor/happy-hare/extras/mmu/mmu_calibration_manager.py:499` wraps the autotune branch in `if False and …` — disabled by the upstream maintainer. The flag does nothing; the saved per-gate RDs are frozen at whenever they were last manually calibrated.

**C. The path to *re-calibrate* gear RDs is also gated off.**
`skip_cal_rotation_distance: 1` in our `mmu_parameters.cfg` causes HH to refuse `MMU_CALIBRATE_GEAR`. So even a deliberate operator-driven recalibration is blocked. The HH-canonical recovery sequence (encoder → gear gate 0 → per-gate → bowden → toolhead) cannot run as-is.

**D. Encoder reports systematic over-motion.**
Per-gate `load_delta` ÷ `load_distance` is 1.4%–2.9% across all gates — encoder consistently sees more filament motion than the stepper commanded. Consistent with stepper RD baseline being slightly low (or with extruder-side syncing pulling filament past the encoder), but the magnitude alone isn't large enough to explain the gates-2–5 failure rate. The cluster split is the primary signal; the encoder bias is a secondary thing to verify during recal, not a root cause on its own.

**E. Toolhead constants may also be wrong.**
Ben reports recent toolhead work. `toolhead_extruder_to_nozzle: 102.1`, `toolhead_sensor_to_nozzle: 79.1`, `toolhead_entry_to_extruder: 9.9` haven't been verified against current hardware. If `toolhead_sensor_to_nozzle` is wrong, load fails with "sensor didn't trigger" exactly as observed — but this would affect all gates equally, not the cluster split. Likely a co-factor, not the prime cause.

**F. Servo wear is plausible.**
`mmu_statistics_counters.servo_down = 5554`, past HH's `5000` warning. Worn servo can fail to fully engage the gear drive, causing intermittent slippage that looks identical to a calibration miss. Cannot be ruled out without inspection.

**Primary hypothesis:** Per-gate RDs have drifted (or were never correctly set for gates 2–5) and HH's auto-correction is structurally unable to fix it. The fix is a clean re-calibration in HH's mandated order, with the two blocking flags flipped first. Servo wear and toolhead constants are co-factors that need verification during the same session because they'd be cheap if-correct and ruinous if-ignored.

## 3. Pre-flight

### 3.1 Servo inspection (mandatory first step)

Open the MMU. Eyeball the servo arm + gear teeth for visible wear. Run `MMU_SERVO POS=down` and confirm the gear positively grips a piece of filament (manual push-back should meet hard stall, not slip). **If the servo is degraded, stop and replace it before any calibration runs** — every cal value collected with a slipping servo is junk.

### 3.2 Reset servo + failure counters

```
MMU_STATS COUNTER=servo_down RESET=1
MMU_STATS RESET=1
```

The `servo_down` reset re-arms the 5000-warning. The full `RESET=1` clears per-gate failure counts so post-recal stats are diagnostic from zero.

### 3.3 Snapshot current state for rollback

```
ssh pi@mainsailos.local "cp ~/printer_data/config/mmu_vars.cfg ~/printer_data/config/mmu_vars.cfg.pre-cal-2026-05-17"
```

Also `sync-from-pi` locally to capture the current `mmu_vars.cfg` state in the repo before mutating anything.

### 3.4 Disable `autocal_bowden_length` during recal (runtime only)

```
MMU_TEST_CONFIG AUTOCAL_BOWDEN_LENGTH=0
```

Prevents gate-0 auto-tuning from compounding bad data while we collect new measurements. Re-enabled in 5.1.

### 3.5 Flip the two blocking flags in `mmu_parameters.cfg`

Edit `config/mmu/base/mmu_parameters.cfg`:

```diff
-skip_cal_rotation_distance: 1
+skip_cal_rotation_distance: 0
-autotune_rotation_distance: 1
+autotune_rotation_distance: 0
```

`skip_cal_rotation_distance: 0` re-enables `MMU_CALIBRATE_GEAR`. `autotune_rotation_distance: 0` removes the misleading flag (the underlying logic is dead anyway — see Diagnosis B).

Deploy via the normal `local edit → PR → merge → /deploy-to-pi` flow. **Restart impact: RESTART**.

### 3.6 Sanity baseline

```
MMU_HOME
MMU_STATUS
```

Confirm clean ready state before any cal command. Bail if anything's red.

## 4. Calibration sequence (HH-canonical order)

Run in this order — each step's correctness depends on the prior step's saved values.

The current toolhead distance triplet (`toolhead_extruder_to_nozzle: 102.1`, `toolhead_sensor_to_nozzle: 79.1`, `toolhead_entry_to_extruder: 9.9`) was measured in CAD from the current hardware. Rather than re-measure with calipers (which adds operator burden and is unlikely to be more accurate than CAD), we accept HH's auto-derived values in 4.5 as the field truth. If HH's result diverges sharply from CAD (>5mm), that's a signal that HH's cal failed, not that CAD was wrong — re-run with `REPEATS` bumped or inspect.

### 4.1 Encoder resolution

```
MMU_CALIBRATE_ENCODER LENGTH=500 REPEATS=5 SAVE=0
```

Compare the measured resolution to the saved `0.998752`. If drift is **<1%**, leave as-is. If **≥1%**, re-run with `SAVE=1`. Drift here means either wheel slip or stepper-RD baseline is off.

### 4.2 Gear rotation distance, gate 0 only

```
MMU_CALIBRATE_GEAR LENGTH=100 MEASURED=<measured_actual_mm>
```

Push 100mm of commanded filament, measure with calipers what actually came out, feed back. Gate 0 becomes the reference for all per-gate calibrations.

### 4.3 Per-gate RDs

```
MMU_CALIBRATE_GATES GATE=ALL
```

Uses the freshly-calibrated gate 0 RD + encoder resolution as the reference; sweeps each gate (1–5) and computes its RD against that reference. **Expected outcome:** the current 3.6% spread should narrow to <1%. If a particular gate still shows >1% RD deviation from gate 0 after this, that gate has a mechanical issue (drive gear lint, slipped grub screw, worn teeth) — see Section 6.

### 4.4 Bowden length

```
MMU_CALIBRATE_BOWDEN GATE=0 BOWDEN_LENGTH=1019.4 REPEATS=3
```

Current `1019.4` is a fine starting estimate; HH iterates until it converges. Saved per-gate, typically identical (bowden tube is physical and shared across gates).

### 4.5 Toolhead constants via HH

Always run — replaces the CAD values with HH's field-measured values:

```
MMU_CALIBRATE_TOOLHEAD CLEAN=1   # toolhead_extruder_to_nozzle + toolhead_sensor_to_nozzle
MMU_CALIBRATE_TOOLHEAD DIRTY=1   # toolhead_residual_filament (currently 23 — suspected high)
MMU_CALIBRATE_TOOLHEAD CUT=1     # only if Filametrix blade has moved
```

HH gates this on `CALIBRATED_GEAR_0 | CALIBRATED_ENCODER | CALIBRATED_SELECTOR | CALIBRATED_BOWDENS` — that's why it runs last.

After each step, check `mmu.log` for `Saved <constant> = <value>` confirmation and verify `mmu_vars.cfg` was rewritten.

## 5. Post-cal cleanup + validation soak

### 5.1 Re-enable `autocal_bowden_length`

```
MMU_TEST_CONFIG AUTOCAL_BOWDEN_LENGTH=1
```

Disabled in 3.4 to keep cal data clean. Now that the baseline is fresh, gate-0 slow bowden auto-tuning is back to a useful guardrail.

### 5.2 Reset failure counters again (optional, if 3.2 was already done close to here you can skip)

```
MMU_STATS RESET=1
```

Clean stats from this point onward are how we measure whether the recal worked.

### 5.3 Save state to git

`sync-from-pi` to pull the rewritten `mmu_vars.cfg` back into the repo. Commit alongside (or in the same PR as) the `mmu_parameters.cfg` flag flips from 3.5. Suggested commit title: `chore(mmu): post-recal calibration snapshot — closes #15`.

### 5.4 Two-pass validation soak

**Pass 1 — MMU-only, cheap (no heater needed):**

```
MMU_SOAKTEST_LOAD_SEQUENCE LOOP=3 RANDOM=0 FULL=0
```

3 sequential sweeps across all 6 gates × 100mm bowden moves. **Pass criterion:** zero MMU pauses and `MMU_STATS` shows ≤2% failure across the 18 sequences.

**Pass 2 — full extruder-engaged, hot, randomized:**

```
M104 S210
M109 S210
MMU_SOAKTEST_LOAD_SEQUENCE LOOP=2 RANDOM=1 FULL=1
TURN_OFF_HEATERS
```

2 randomized sweeps × 6 gates loading all the way to nozzle. **Pass criterion:** zero MMU pauses and ≤1 failure across 12 sequences. `RANDOM=1` catches any selector-ordering quirk.

If both passes are green, close issue #15 with a comment linking the recal commit + post-recal `MMU_STATS`.

## 6. What if it doesn't work (failure-class branches)

- **4.3 per-gate cal can't converge for one specific gate** → mechanical issue at that gate. Inspect drive gear (lint, slipped grub screw, worn teeth). Don't paper over with a hand-set RD.
- **4.4 bowden cal oscillates / "Bowden move outside tolerance"** → encoder is unreliable. Re-run 4.1 with more REPEATS, or inspect the encoder wheel.
- **Pass 1 fails uniformly across gates** → toolhead constants from 4.5 are wrong or HH's cal failed. Compare HH's saved triplet to the CAD values (102.1 / 79.1 / 9.9); if HH's values are sharply different (>5mm), HH cal failed — re-run 4.5 with all three phases (`CLEAN`, `DIRTY`, `CUT`) and inspect the toolhead sensor wiring. Otherwise the saved value is correct and the failure cause is elsewhere.
- **Pass 2 fails on one specific gate only** → that gate is mechanically different (selector misalignment, gate endstop drift). Run `MMU_CHECK_GATE GATE=N` to surface the discrepancy.
- **Servo failures recur after fresh inspection** → replace the servo. ERCF v2 servo arms are a known consumable.

If none of those fit, capture both `klippy.log` and `mmu.log` from a failed sequence and reopen #15 with the new error signature.

## 7. Config drift cleanup (optional, post-validation)

Once 5.4 is green, the following config oddballs in `mmu_parameters.cfg` are worth a closer look — each in a separate small commit, **not bundled** with the calibration PR:

- **`toolhead_residual_filament: 23`** — HH upstream default is 0. 23mm of residual is a lot for a cut-tip workflow. 4.5's `DIRTY=1` derives this value, so post-cal it should be whatever HH wrote.
- **`gear_from_buffer_accel: 100`** — upstream default 400; ours is unusually low. If reliability holds after recal, try bumping to 200 and measure. Out of scope for the cal fix itself.
- **`bowden_apply_correction: 1`** — enables encoder-based bowden correction. With a freshly-calibrated encoder this is fine; if the encoder bias from Diagnosis D persists post-recal, consider turning it off temporarily to see if reliability improves.

These are tuning steps, not bug fixes, and only make sense after the calibration baseline is restored.

## 8. Out of scope

- A Layer 5 tripwire enforcing per-gate RD ≤ N% deviation from gate 0. Considered and rejected — HH itself already enforces a 20% bound; a tighter bound here is structurally redundant if we keep `skip_cal_rotation_distance: 0` and re-run cal periodically. Revisit if failures recur.
- A PR upstream against `vendor/happy-hare` to either re-enable autotune or document it as removed. Worth filing eventually but not load-bearing for this fix.
- Webcam/Spoolman/timelapse changes — separate concerns tracked elsewhere.
- Refactoring `mmu_parameters.cfg` to track upstream more tightly. Most diffs are intentional customizations (servo angles, sync feedback, espooler, Filametrix wiring). The drift cleanup in section 7 is the focused subset that matters.

## 9. Restart-impact summary

| Step | Restart kind |
|---|---|
| 3.5 (flag flips in `mmu_parameters.cfg`) | RESTART |
| All other steps | Runtime (HH macros / `MMU_TEST_CONFIG` / `SAVE_CONFIG` via cal commands) |

No `FIRMWARE_RESTART`. No MCU pin changes. No kinematics changes.
