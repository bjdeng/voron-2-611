---
brand: Sunlu
material: PLA Silk
orca_profile: "Sunlu Silk PLA"
last_calibrated: 2026-05-19
nozzle_temp: 200
nozzle_temp_initial_layer: 210
flow_ratio: 0.975
pa_mode: static
pa_fallback: 0.04
rotation_distance_verified: galileo-bring-up
---

# Sunlu Silk PLA

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

Also from the OrcaSlicer profile: bed 55 °C, max volumetric speed 7.5 mm³/s.
Inherits `Generic PLA Silk @System`.

## History

### 2026-05-19
- Snapshotted into the repo 2026-11-15 from the live OrcaSlicer profile; the
  date is the profile file's mtime, not a recorded calibration session.
- Temp: 200 °C (210 initial layer)
- Flow: 0.975
- PA: 0.04 (static per-filament override)
- Bed: 55 °C; max volumetric 7.5 mm³/s
