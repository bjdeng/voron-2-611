---
brand: Inland
material: PLA Silk
orca_profile: "Inland Silk PLA"
last_calibrated: 2026-05-19
nozzle_temp: 210
nozzle_temp_initial_layer: 215
flow_ratio: 0.965
pa_mode: static
pa_fallback: 0.06
rotation_distance_verified: galileo-bring-up
---

# Inland Silk PLA

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

Also from the OrcaSlicer profile: bed 55 °C, max volumetric speed 7.5 mm³/s.
Inherits `Generic PLA Silk @System`.

## History

### 2026-05-19
- Snapshotted into the repo 2026-11-15 from the live OrcaSlicer profile; the
  date is the profile file's mtime, not a recorded calibration session.
- Temp: 210 °C (215 initial layer)
- Flow: 0.965
- PA: 0.06 (static per-filament override)
- Bed: 55 °C; max volumetric 7.5 mm³/s
