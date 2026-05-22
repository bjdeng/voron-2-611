# Eddy Probe Reposition + Recalibration Procedure

Reference for restoring probe function after physical reposition (e.g., after a bed-debris crash shifted the coil PCB or its mount).

Authored 2026-05-22 during diagnosis of "No trigger on stepper_z after full movement" failures. Specific context in `memory/troubleshooting-log.md` once that's updated; commit history under `887ec78` (sync) and prior `fix(motion)` / `fix(eddy)` commits show the in-session safety changes.

---

## When to use this

The probe coil has been physically displaced (loose mount, crash impact, deliberate reposition for height adjustment) and the cal table no longer matches reality. Symptoms include:
- `No trigger on stepper_z after full movement` errors during G28 Z
- Probe descending past expected trigger point and crashing the bed
- `MCU 'eddy' shutdown: ADC out of range` during probe sweeps
- Successful homing in some operating conditions but not others

Do NOT use this for thermal drift problems (those need `TEMPERATURE_PROBE_CALIBRATE` only — see issue #25).

---

## Critical safety constraint

**Do NOT run G28 Z, QUAD_GANTRY_LEVEL, BED_MESH_CALIBRATE, or any probe-using command between physical reposition and step 5 of this procedure.** The existing cal table predicts trigger behavior for the OLD coil position; using it after reposition will crash the bed.

Use `FORCE_MOVE` for any Z motion in phases 1–3.

## Required config: `position_min: -5` on `[stepper_z]`

This printer needs `[stepper_z] position_min: -5` (not the doc-blessed `-1` from `vendor/klipper/docs/Eddy_Probe.md:281`). Reason: the V2.4 front-rear gantry sag (CLAUDE.md "Known quirks" → "V2.4 saggy rear & QGL") means QGL probing at corners needs more downward kinematic room than tap-compression alone calls for. With `position_min: -1`, tap works at bed center but QGL fails with "No trigger on probe after full movement" at the high (front) corners — the descent runs out of kinematic room before the freq reaches the trigger threshold. `-5` is the legacy value (pre-Eddy era, Voron Tap install) and is empirically correct for this machine. Confirm before starting:

```sh
ssh pi@mainsailos.local "grep -A6 '^\[stepper_z\]' ~/printer_data/config/motion.cfg | grep position_min"
# should print: position_min: -5
```

---

## Pre-flight

Already done if you're following from a `/sync-from-pi` session:

```sh
# Verify the working tree captures the current Pi state
git status   # should be clean, or only have changes you intend
```

Snapshot the current cal table on the Pi as a rollback point:

```sh
ssh pi@mainsailos.local "cp ~/printer_data/config/printer.cfg ~/printer_data/config/printer.cfg.pre-recal-\$(date +%Y%m%d_%H%M%S)"
```

(The repo already holds the pre-recal cal as committed history — this is belt-and-suspenders for the Pi side.)

---

## Phase 1 — Physical reposition

Standard mechanical work. Power off the printer if it makes access easier; power-on Klipper isn't needed until Phase 2.

1. Loosen the probe mount screws on the X carriage.
2. Position the coil bottom face **2.5 mm above the nozzle tip** (BTT spec: 2–3 mm, 2.5 mm optimal, per `vendor/btt-docs/docs/Eddy.md:52`). Use calipers or a 2.5 mm gauge.
3. Tighten the screws. Verify no PCB tilt and no play when nudged. If the mount has any wobble, that's the underlying cause of recurring shifts — fix it.
4. Inspect for collateral damage: anything bent, scored, or loose on the toolhead.

BTT spec footnotes (from the FAQ in the same doc):
- "Below 2 mm" if you observe errors at high coil temperatures.
- "Slightly raise" if errors during QGL.

---

## Phase 2 — Bootstrap Z without the probe

After power-on, Z is unhomed and the old cal table is invalid. Use the doc-blessed `FORCE_MOVE` workaround from `vendor/klipper/docs/Eddy_Probe.md:402-450`:

```gcode
FORCE_MOVE STEPPER=stepper_z DISTANCE=30 VELOCITY=5
SET_KINEMATIC_POSITION Z=30
G28 X Y
```

X and Y homing don't involve the probe, so they're safe. The `SET_KINEMATIC_POSITION Z=30` lets Klipper allow subsequent moves without complaining that Z is unhomed.

---

## Phase 3 — Heat to cal anchor temperature

Pick the temperature regime you print at most. The cal anchor matters because native Klipper's tap detection has no signal filter, so tap is most reliable within ~±5 °C of the anchor temp (see CLAUDE.md "Klipper gotchas" and issue #25).

- **PLA / PETG (most common):** bed 60–65 °C
- **ABS / ASA:** bed 100–110 °C

```gcode
M140 S60         ; or your typical bed temp
PARKCENTER       ; move toolhead over bed center
; Wait ~15 min for the coil to reach thermal equilibrium
```

Watch `temperature_probe btt_eddy` in Mainsail. The coil reaches a steady-state somewhere below the bed temperature (radiative + convective heating from the bed). Wait until it stops climbing.

---

## Phase 4 — Main frequency calibration

Lower the toolhead to about 10 mm above the bed first so the paper-test step doesn't have far to descend:

```gcode
G0 Z10 F600
PROBE_EDDY_CURRENT_CALIBRATE CHIP=btt_eddy
```

Mainsail will show the paper-test dialog. Lower the nozzle in 0.05 mm steps until the paper has gentle drag — **use the same press you always paper-test with**, consistency matters across cal sessions. Click ACCEPT.

The sweep runs automatically: 100 samples at z=0.05 to z=4.05 in 40 µm steps. Takes about a minute.

```gcode
SAVE_CONFIG    ; auto-restarts Klipper; new cal table is live after restart
```

---

## Phase 5 — Verify

After the restart, G28 Z should work normally:

```gcode
G28 Z          ; descends, triggers smoothly at ~0.5 mm, lifts, retries, settles
QUAD_GANTRY_LEVEL
G28 Z          ; re-home after QGL (sequence per [homing_override] in eddy.cfg)
```

**If G28 Z fails here**, STOP — the physical reposition didn't fully address the issue, and we go back to mount inspection. Don't push forward into tap cal until G28 Z is clean.

---

## Phase 6 — Tap calibration (3-step, ~10 min)

The existing drift polynomials should still be valid — they describe the coil's freq-vs-temperature behavior, which is a property of the coil itself rather than the mounting position. As long as the new cal anchor temp falls within the polynomial training range (currently ~38–66 °C, per `drift_calibration_min_temp = 38.43`), you can skip a fresh drift cal here. If you anchored Phase 3 outside that range, do the optional drift cal in Phase 7 first.

```gcode
G28
M104 S220       ; hot nozzle required for tap
M109 S220
BLOBIFIER_CLEAN ; clean tip so plastic doesn't dampen the inflection
PROBE_EDDY_CURRENT_TAP_CALIBRATE CHIP=btt_eddy TAP=guess
SAVE_CONFIG    ; restarts
```

After restart:

```gcode
M109 S220
BLOBIFIER_CLEAN
PROBE_EDDY_CURRENT_TAP_CALIBRATE CHIP=btt_eddy TAP=refine
; CRITICAL: do NOT SAVE_CONFIG between refine and verify.
; The refined threshold lives only in memory; a restart discards it.

PROBE_EDDY_CURRENT_TAP_CALIBRATE CHIP=btt_eddy TAP=verify
SAVE_CONFIG    ; saves tap_threshold, restarts
```

If `refine` or `verify` fails with `Unable to detect tap: insufficient slope delta`, that's the known native-tap thermal-sensitivity issue (CLAUDE.md). It usually means the coil temp drifted from the cal anchor between the steps. Workarounds:
- Wait for the coil to re-equilibrate at the anchor temp before retrying
- Drop the cal anchor temp closer to "typical print-start" so tap happens near anchor naturally
- Do the optional drift cal (Phase 7) and try again

The `PROBE_EDDY_CURRENT_TAP_CALIBRATE CHIP=btt_eddy` command with NO `TAP=` argument is a non-moving diagnostic that prints contact_slope_delta and current state — useful between steps if something looks off.

---

## Diagnostic notes from the 2026-05-22 first run

Hard-won lessons that aren't obvious from the source or doc:

- **Bootstrap kinematic offset doesn't need a "trick" if `position_min` is correct.** The SET_KINEMATIC_POSITION Z=N value can match the FORCE_MOVE distance (e.g., Z=30 after FORCE_MOVE +30). Paper test descends freely down to bed contact thanks to `position_min: -5`. (The Z=5 trick we improvised mid-session was a workaround for `position_min: 0` being too tight — not needed with the correct value.)
- **`Unable to detect tap: insufficient lift (X vs 0.350)`** during G28 means the tap descent hit `position_min` before nozzle contact. Caused by `position_min` being too high (≥ 0). Lowering to `-5` is the fix.
- **`Unable to detect tap: insufficient slope delta (negative vs threshold)`** means the algorithm couldn't separate compression from free-air on the lift curve — also caused by descent floor being too high. Same fix.
- **`LIFT_SPEED` on `PROBE METHOD=tap` is a red herring.** Bumping `LIFT_SPEED=20` changes the apparent failure mode from "insufficient lift" to "insufficient slope delta" but doesn't fix the root cause (descent room). Default `LIFT_SPEED=5` is fine.
- **`No trigger on probe after full movement` during QGL** means a corner can't descend enough to reach bed. Either gantry tilt is large (rare without manual asymmetric FORCE_MOVE), or `position_min` is too tight relative to sag — second is far more common.

## Phase 7 — Drift calibration (optional, ~1.5 hr)

**Skip if:** the existing drift polynomials cover your operating range and Phase 6 tap cal succeeded cleanly.

**Run if:** you want to operate the probe at temps outside the current 38–66 °C training range (e.g., post-print homing at coil 75–95 °C), or Phase 6 tap cal is failing due to thermal-drift sensitivity.

```gcode
G28
G0 Z5 F600
SET_IDLE_TIMEOUT TIMEOUT=36000
M104 S220       ; hotend hot helps drive coil temp up
TEMPERATURE_PROBE_CALIBRATE PROBE=btt_eddy TARGET=90 STEP=4
```

`TARGET=90` extends training above the prior 66 °C ceiling to cover ABS-regime post-print operation (the original failure scenario today was at coil 95 °C — well outside the old training range). `STEP=4` gives ~13 samples; default `STEP=2` doubles the count and slightly improves fit at the cost of doubling the runtime.

Klipper heats the bed to maximum, samples freq at 9 z-positions for each STEP °C interval, and pops a paper-test prompt at every step. Plan for ~15 paper tests over ~1.5 hours. Use the same paper-test press every time.

Caveats from CLAUDE.md "Klipper gotchas":
- Extruder temperature must be ≤ 70 °C between probe samples (the macro turns it off and waits — don't override)
- Use the same paper-test pinch press consistently across samples
- Don't end the session early unless absolutely necessary; partial cals are less accurate than no cal

When all samples complete:

```gcode
SAVE_CONFIG
```

After Phase 7, redo Phase 6 (tap cal) since the cal_temp anchor may have shifted slightly during the drift sweep.

---

## Phase 8 — End-to-end verification

```gcode
G28
QUAD_GANTRY_LEVEL
G28
PARKCENTER
PROBE_ACCURACY    ; multiple probes — check standard deviation
```

`PROBE_ACCURACY` should report sub-10 µm std dev on a healthy probe. Higher than that hints at residual mount play or surface contamination.

Then run a test print using your normal `PRINT_START`. Watch for:
- Tap completing without retries
- Bed mesh values looking sensible (no NaN, no extreme outliers)
- First layer adhesion at the usual settings

---

## Post-procedure — capture the new state

After everything verifies, sync the new cal back into the repo and commit:

```sh
/sync-from-pi
git add config/printer.cfg
git commit -m "chore(sync): capture post-reposition recal — cal_temp=<NEW>°C"
```

Or, more rigorously, open a PR documenting what changed and why. The history will then show:
1. The pre-recal baseline (commit `887ec78`)
2. The fix commits from this session
3. The post-recal state

---

## Reference

- BTT Eddy mount spec: `vendor/btt-docs/docs/Eddy.md:52` (2–3 mm, 2.5 mm optimal)
- Klipper Eddy probe docs: `vendor/klipper/docs/Eddy_Probe.md` (especially §"Calibration" and §"First time setup")
- Trigger mechanism source: `vendor/klipper/klippy/extras/probe_eddy_current.py:578-585`
- Drift compensation source: `vendor/klipper/klippy/extras/temperature_probe.py:680-714`
- FORCE_MOVE bootstrap pattern: `vendor/klipper/docs/Eddy_Probe.md:402-450`
- Prior tap-failure incident: CLAUDE.md "Klipper gotchas" → "Native Klipper's tap detection has NO signal filtering"
- Open work on extending drift training range: issue #25
