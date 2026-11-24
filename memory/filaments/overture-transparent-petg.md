---
brand: Overture
material: PETG
orca_profile: "Overture Transparent PETG"
last_calibrated: 2026-05-19
nozzle_temp: 235
nozzle_temp_initial_layer: 240
flow_ratio: 1.01
pa_mode: static
pa_fallback: 0.045
rotation_distance_verified: galileo-bring-up
---

# Overture Transparent PETG

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

Also from the OrcaSlicer profile: bed 55 °C, max volumetric speed 12 mm³/s.
Inherits `Generic PETG @System`.

## History

### 2026-05-19
- Snapshotted into the repo 2026-11-15 from the live OrcaSlicer profile; the
  date is the profile file's mtime, not a recorded calibration session.
- Temp: 235 °C (240 initial layer)
- Flow: 1.01
- PA: 0.045 (static per-filament override)
- Bed: 55 °C; max volumetric 12 mm³/s
