---
brand: Ambrosia
material: ASA
orca_profile: "Ambrosia ASA"
last_calibrated: 2026-05-19
nozzle_temp: 240
nozzle_temp_initial_layer: 245
flow_ratio: 0.983
pa_mode: static
pa_fallback: 0.035
rotation_distance_verified: galileo-bring-up
---

# Ambrosia ASA

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

Also from the OrcaSlicer profile: bed 100 °C (110 initial), max volumetric
speed 14 mm³/s. Inherits `Generic ASA @System`.

## History

### 2026-05-19
- Snapshotted into the repo 2026-11-15 from the live OrcaSlicer profile; the
  date is the profile file's mtime, not a recorded calibration session.
- Temp: 240 °C (245 initial layer)
- Flow: 0.983
- PA: 0.035 (static per-filament override)
- Bed: 100 °C (110 initial); max volumetric 14 mm³/s
