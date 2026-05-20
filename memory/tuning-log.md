# Tuning log

Running record of calibration runs (input shaper, PID, pressure advance, flow, Eddy, bed mesh, etc.). Newest at the top. Each entry: date, what was tuned, the resulting value, the command run, and any notes.

---

## 2026-05-20 — microsteps 128 → 64 on X/Y/Z mainboard steppers (Phase A of #24)

PR [#95](https://github.com/bjdeng/voron-2-611/pull/95). Halved microsteps on `[stepper_x]`, `[stepper_y]`, `[stepper_z]`, `[stepper_z1]`, `[stepper_z2]`, `[stepper_z3]` from 128 to 64 to recover MCU USB step-rate headroom (LPC1769 was at ~92% of budget at max_velocity). `interpolate: False` retained on all 6 TMC2209s.

**Test plan results (2 × TEST_SPEED before, 2 × TEST_SPEED after):**

| Metric | Baseline (128) | Post-change (64) | Status |
|---|---|---|---|
| Subjective noise rating | 3/5 (moderate) | 3.5/5 ("maybe more vibration noise", no abnormal sounds) | ❌ slight regression |
| X/Y position drift | 0 mm (identical mcu count before/after, both runs) | 0 mm (same) | ✅ |
| Z probe diff at (175,175) | 0.008 mm run 1, 0.019 mm run 2 | 0.018 mm run 1, 0.007 mm run 2 | ✅ (sensor noise band) |
| `step_compress` count in klippy.log | 0 | 0 | ✅ |

Klipper docs ([TMC_Drivers.md:106-109](https://github.com/Klipper3d/klipper/blob/master/docs/TMC_Drivers.md)) predicted 64 = 128 acoustically with `interpolate: False`. Empirical result on this machine: 64 is *slightly louder*, not equal. Phase A retained despite the subjective regression because (a) position checks passed cleanly, (b) the increase was small and Ben reported no abnormal sounds, (c) Phase B (TMC Autotune) is explicitly targeting stepper noise and may compensate. Final close-out of #24 will follow Phase B.

---

## ~2020 — commissioning belt tension (historical, salvaged 2026-05-17)

Salvaged from the Voron template header in `config/printer.cfg` before that header was deleted in F1+F9 (config reorg audit). Values pre-date the repo's git history; provenance is "what was scribbled into the file when Ben commissioned the build." Almost certainly stale today — record kept for historical reference, not a current target.

- Belt tension X: 110 Hz at `X175, Y18`
- Belt tension Y: 110 Hz at `X175, Y18` (single measurement covers both A/B belts on a CoreXY)
- Belt tension Z: 140 Hz at `Z215`

If re-tensioning the belts, the [Ellis Print-Tuning-Guide belts page](https://ellis3dp.com/Print-Tuning-Guide/articles/belt_tension.html) has current target Hz ranges; don't trust these values.

---

## 2026-05-13 — initial snapshot from SAVE_CONFIG

Pulled from `config/printer.cfg` at repo-init time. Per Ben, these are likely stale and worth re-running.

- Bed PID: `Kp=44.470, Ki=1.246, Kd=396.896`
- Hotend PID: `Kp=23.507, Ki=1.059, Kd=130.460`
- Input shaper X: `mzv @ 51.4 Hz`
- Input shaper Y: `zv @ 37.4 Hz`
- Pressure advance: `0.05` (smooth time 0.040)
- Eddy NG: calibrated drive currents 15 & 16; calibration_version 5; `reg_drive_current: 15`, `tap_drive_current: 15`
- Bed mesh `default`: 9×9 over (15, 21.42) → (335, 335)
- Bed mesh `Default2`: 5×5 over (30, 30) → (320, 320)
