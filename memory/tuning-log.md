# Tuning log

Running record of calibration runs (input shaper, PID, pressure advance, flow, Eddy, bed mesh, etc.). Newest at the top. Each entry: date, what was tuned, the resulting value, the command run, and any notes.

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
