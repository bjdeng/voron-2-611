# Chopper-Resonance-Tuner — design

**Status:** future-work spec, not yet scheduled
**Issue:** to-be-filed (future-work label)
**Predecessor:** [microsteps-128-to-64 + TMC Autotune (issue #24)](2026-05-20-microsteps-128-to-64.md). PR #95, #96, #97 took the printer from original 3/5 noise → louder → back to 3/5 with the autotune-aligned config (interpolate:True, microsteps:128, Z `tuning_goal:performance`, X/Y `extra_hysteresis:2`). CRT is the next lever to push *below* the original baseline.

## Goal

Reduce audible X/Y stepper noise on this Voron 2.4 below the current 3/5 baseline, using empirical accelerometer-based chopper register tuning. If X/Y session yields meaningful improvement, extend to Z motors in a separate session.

## Non-goals

- Tuning the extruder (toolhead audio is dominated by part fan + hotend fan; stepper noise is inaudible there)
- Per-Z-motor individual tuning (4 Z motors are identical hardware moving together; tune one, apply to all four)
- Auto-application of CRT values via a hook (manual PR after each session is the right friction level — keeps repo↔Pi alignment honest)
- Re-running CRT on a schedule (it's a one-shot tune per motor unless something physically changes)

## Tool

[MRX8024/chopper-resonance-tuner](https://github.com/MRX8024/chopper-resonance-tuner) — a Klipper Python extension that drives the motor at chosen speeds while sweeping TMC2209 chopper register combinations (TBL, TOFF, HSTRT, HEND, and optionally current in 25 mA steps). Records vibration on the LIS2DW accelerometer, outputs per-speed heat-maps of vibration vs register combo. Operator picks the lowest-vibration combo and codifies it.

This is methodologically different from `klippain_tmc_autotune` (already installed): autotune *calculates* values from motor datasheet specs in milliseconds at startup; CRT *measures* values empirically over ~2 hours per axis.

## Install footprint

Pi-only, **not** vendored as a submodule. Matches the existing `klippain-shaketune` pattern (per `config/system.cfg` notes). Rationale: noise tuning is infrequent; the cost of vendoring (submodule maintenance, CI symlink rules, version pin discipline) outweighs the benefit for a tool that's run once or twice and then dormant.

Pi side, `install.sh` performs:
- Clone to `~/chopper-resonance-tuner/`
- Symlink `chopper_tune.py` (and any helper modules) into `~/klipper/klippy/extras/`
- Create `~/printer_data/config/adxl_results/` for output CSVs and PNGs
- Restart Klipper

Repo side touchpoints:
- `config/printer.cfg` or `config/system.cfg`: add `[chopper_tune]` section (or equivalent) + comment block matching the shaketune pattern explaining install location, lack of vendoring, and post-Klipper-bump install.sh re-run requirement
- `config/moonraker.conf`: optional `[update_manager chopper_tune]` block so Moonraker tracks upstream
- `.gitignore`: `config/adxl_results/` — per-run output (CSVs, PNGs) stays off the repo
- `.github/workflows/ci.yml`: add a "Strip [chopper_tune] from system.cfg (or wherever it lands) — chopper-resonance-tuner not vendored" step mirroring the existing shaketune strip step

## Workflow — two sessions

### Session 1 — X/Y tuning, ~2 hours

Operator division:
- **Ben:** Mounts/cares for the printer, listens to runs, provides final ear rating
- **Claude:** Drives the `CHOPPER_TUNE` macro sequence, interprets results, decides parameter ranges between iterations

Accelerometer stays toolhead-mounted (decent fidelity for X/Y via belt coupling; not remounting per motor).

**Pre-flight (~15 min):**
1. Verify printer idle, `ACCELEROMETER_QUERY` returns valid samples, Klipper ready
2. Snapshot current `[tmc2209 stepper_x/y]` chopper values via `DUMP_TMC` — this is the runtime rollback baseline
3. Capture pre-tuning baseline: TEST_SPEED ×2 + Ben's ear rating (expected: 3/5 with current autotune-aligned config)

**Tuning loop (~90 min, X then Y):**
1. `CHOPPER_TUNE FIND_VIBRATIONS=1 STEPPER=stepper_x` — sweep 20–250 mm/s on X. Wait ~25 min, SSH-fetch the output CSV/PNG from `adxl_results/`
2. Claude looks at the vibration plot, identifies 1–3 worst-vibration speeds
3. For each bad speed: `CHOPPER_TUNE STEPPER=stepper_x MIN_SPEED=<v> MAX_SPEED=<v> TBL=0..3 TOFF=1..15 HSTRT=0..7 HEND=0..15` (~20–30 min/speed, grab heatmap)
4. Identify lowest-vibration register combo, narrow params, iterate 1–2 more times to converge
5. Repeat for stepper_y
6. Apply winning per-stepper values via `SET_TMC_FIELD` at runtime (no FIRMWARE_RESTART yet — keeps the runtime tune in place for live validation)

**Validation (~10 min):**
7. Re-home + QGL (Z homing may need the eddy-flake retry — that's a known issue, not CRT-related)
8. TEST_SPEED ×2. Ben rates noise, listens for abnormal sounds
9. Success: rating ≤ baseline AND 0 missed steps. Failure: rating > baseline OR abnormal sounds → revert via `SET_TMC_FIELD` to baseline snapshot, end session

**Post-session (~15 min):**
10. Branch + PR with tuned values codified per Section "Coexistence with autotune" below
11. Deploy, FIRMWARE_RESTART, re-run TEST_SPEED to confirm codified state matches runtime state
12. tuning-log entry: per-stepper register values, pre/post noise rating, screenshot of CRT heatmap

### Session 2 — Z motors, conditional on Session 1

**Skip if Session 1 didn't improve noise.** Don't burn 2 more hours on Z if X/Y tuning was a no-op — close the work as "CRT didn't beat autotune-aligned on this machine."

If proceeding, mechanically the same as Session 1 with two differences:
- **One axis covers all 4 Z motors.** Tune `stepper_z`, apply the winning values to `stepper_z1/z2/z3`. They're identical hardware moving together. Validate by running CRT's `FIND_VIBRATIONS` on stepper_z1 briefly — if its harmonic peaks differ from stepper_z, the single-tune-applied-everywhere assumption fails and each Z gets tuned individually
- **Slower test speeds.** Z working range is 0–15 mm/s (probing) + ~50 mm/s (travel; max_z_velocity=100). Sweep 5–80 mm/s instead of X/Y's 20–250

Z-specific validation addition: a few `G28 Z` cycles listening to the probe approach — that's where Z noise is most audible during prints.

## Coexistence with autotune

Both CRT and autotune write the same chopper registers (TBL, TOFF, HSTRT, HEND). Autotune writes at startup via `SET_TMC_FIELD` after `[tmc2209]` init, so anything in `[tmc2209] driver_TOFF/driver_TBL/...` gets overwritten by autotune.

Compare CRT's recommended values vs what autotune currently writes (visible in `~/printer_data/logs/klippy.log` via `grep 'autotune_tmc set'`). Pick the lightest-touch path:

| Comparison | Action |
|---|---|
| CRT values within ±1 step of autotune for all 4 registers | **No PR.** CRT confirms autotune. Document the validation in tuning-log, save the Pi from another deploy cycle |
| 1–3 registers diverge by >1 step | **Targeted `delayed_gcode` override.** Keep `[autotune_tmc]` intact (preserves CoolStep, PWM, IHOLDDELAY tuning). Add `[delayed_gcode _apply_crt_chopper]` with `initial_duration: 1.0` that fires `SET_TMC_FIELD` only for diverging registers. Surgical |
| All 4 registers diverge significantly | **Remove `[autotune_tmc stepper_*]` for that stepper.** Hard-code values in `[tmc2209 stepper_*]` via `driver_TBL/driver_TOFF/driver_HSTRT/driver_HEND`. Lose autotune's CoolStep + PWM + standby tuning for that stepper — comment notes which TMC fields aren't covered anymore. Most aggressive |

The middle option is the cleanest fallback because it's surgical and keeps autotune doing what it's good at. Full removal is the "trust CRT completely" path.

The plan will walk through the comparison with concrete worked examples for each branch.

## Validation, persistence, rollback

**Pass/fail criteria:**
- Session 1 X/Y: 0 missed steps in TEST_SPEED AND noise rating ≤ 3/5 baseline AND ≥1 axis shows measurable vibration improvement on the CRT heatmap. Caveat: if noise rating IS unchanged at 3/5 but CRT heatmap shows real vibration improvement, count as partial success — audible noise may be dominated by other components (belts, frame ring)
- Session 2 Z: same plus G28 Z probe-approach noise qualitatively ≤ current behavior
- **Plan-level success:** at least one of (X, Y, Z×4) improves enough to keep the values

**Persistence:**
- Tuned values land in motion.cfg via PR per the coexistence decision
- CRT output files (`adxl_results/*.csv`, `*.png`) get **screenshot-captured into tuning-log.md** as evidence. Raw CSV/PNG stay on the Pi only (gitignored — avoiding ~700 MB of vibration data)
- tuning-log entry per stepper: date, pre/post register values, pre/post noise rating, screenshot link

**Rollback paths:**
- *Mid-tuning runtime issue* (squealing, missed steps, motor heat): `SET_TMC_FIELD` revert to the pre-session DUMP_TMC snapshot, no PR, end session
- *Post-deploy regression*: revert PR + redeploy. The DUMP_TMC snapshot tells us where to land
- *CRT install fails* (Klipper won't start, syntax error, version conflict with vendored Klipper): SSH to Pi, remove the symlinks from `~/klipper/klippy/extras/`, restart Klipper service. CRT clone stays at `~/chopper-resonance-tuner/` but does nothing

## Risks and known unknowns

- **Toolhead-mounted accelerometer fidelity:** Per upstream guidance, best results come from screwing the accelerometer directly to the motor. We're trading fidelity for setup time. If X/Y results are weak, the next escalation is per-motor remounting (~45 min added per session). Z fidelity is likely worst-case toolhead-mounted because motors are mechanically distant from the toolhead — if Session 1 wins are X/Y-only, Z may need accelerometer remounting to see real gains
- **Klipper version sensitivity:** CRT install symlinks into `~/klipper/klippy/extras/`. After any Klipper version bump, the install.sh needs re-running (same issue Happy-Hare and eddy-ng have). Match the existing post-bump install.sh re-run discipline
- **TMC2209 vs newer drivers:** CRT supports TMC2240 and TMC5160 with additional fields (TPFD); on TMC2209 we're limited to TBL/TOFF/HSTRT/HEND. Less to tune, faster sessions
- **Belt tension / mechanical state confounders:** CRT measures resonance, which depends on belt tension + bearing condition. If belts have drifted since last tension check, CRT values are tuned for a state we might later "fix" by re-tensioning. Worth a quick belt-tension sanity check before Session 1
- **Squealing from prior Exp 1:** When we tried `tuning_goal:silent` on X/Y today, the A/B motors squealed. CRT-found values that put X/Y too close to stealthChop-like behavior could re-trigger that. Need to validate at full 450/10000 (TEST_SPEED) before codifying, not just at CRT's lower test speeds

## What's NOT in scope

- Extruder chopper tuning
- Per-Z-motor individual tuning (4 Z motors get the same values)
- Auto-application via startup hook (manual PR after each session preferred)
- Re-tuning trigger automation (only re-run if motor change or audible regression)
- Comparing CRT methodology against other tuners (sb-shaketune-chopper, custom scripts) — stuck with CRT or autotune for this iteration

## References

- [MRX8024/chopper-resonance-tuner](https://github.com/MRX8024/chopper-resonance-tuner)
- [chopper-resonance-tuner wiki (EN)](https://github.com/MRX8024/chopper-resonance-tuner/blob/main/wiki/EN.md)
- [chopper-resonance-tuner tuning guide](https://github.com/MRX8024/chopper-resonance-tuner/blob/main/wiki/chopper_tuning_guide_english.md)
- [VORON Design forum — Klipper TMC Autotune thread](https://forum.vorondesign.com/threads/klipper-tmc-autotune.1527/) (mentions CRT as preferred alternative)
- [andrewmcgr/klipper_tmc_autotune Issue #141 — Z stealthChop noise on slow moves](https://github.com/andrewmcgr/klipper_tmc_autotune/issues/141)
- Predecessor spec: [microsteps-128-to-64 + TMC Autotune](2026-05-20-microsteps-128-to-64.md)
