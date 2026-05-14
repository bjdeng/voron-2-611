# Tuning log

Running record of calibration runs (input shaper, PID, pressure advance, flow, Eddy, bed mesh, etc.). Newest at the top. Each entry: date, what was tuned, the resulting value, the command run, and any notes.

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
