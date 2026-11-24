---
brand: Sunlu
material: PLA
orca_profile: "Sunlu PLA+"
last_calibrated: 2026-05-21
nozzle_temp: 190
nozzle_temp_initial_layer: 195
flow_ratio: 0.965
pa_mode: inherited
pa_fallback: none
rotation_distance_verified: galileo-bring-up
---

# Sunlu PLA+

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

PA is enabled but no per-filament `pressure_advance` override is stored — it
inherits the value from `Generic PLA @System`. Also from the profile: max
volumetric speed 18 mm³/s.

## History

### 2026-05-21
- Snapshotted into the repo 2026-11-15 from the live OrcaSlicer profile; the
  date is the profile file's mtime, not a recorded calibration session.
- Temp: 190 °C (195 initial layer)
- Flow: 0.965
- PA: enabled, no per-filament override (inherits Generic PLA)
- Max volumetric 18 mm³/s
