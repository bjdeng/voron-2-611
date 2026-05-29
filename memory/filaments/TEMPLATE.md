---
brand: <Brand>
material: <PLA|PETG|ABS|ASA|PLA Silk>
orca_profile: "<exact OrcaSlicer profile name>"
last_calibrated: YYYY-MM-DD
nozzle_temp: <int>
nozzle_temp_initial_layer: <int>
flow_ratio: <float>
pa_mode: <adaptive|static>
pa_fallback: <float>
rotation_distance_verified: galileo-bring-up
---

# <Brand> <Material>

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

## History

### YYYY-MM-DD
- Temp: <result + note, e.g. "verified 210 still clean">
- Flow: <old → new ratio, e.g. "0.95 → 0.98 (shell measured 0.41/0.40)">
- Adaptive PA: <model summary / fallback value>
- Notes: <observations>
