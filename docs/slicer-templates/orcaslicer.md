# OrcaSlicer hookup for Voron 2.611

How OrcaSlicer should call `PRINT_START` / `PRINT_END` on this machine.

Spec: [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](../superpowers/specs/2026-05-18-print-lifecycle-redesign.md).

## Machine start G-code

In OrcaSlicer: **Printer settings → Machine G-code → Machine start G-code**.

```
M104 S0    ; suppress OrcaSlicer's separate temp-wait sends
M140 S0
PRINT_START EXTRUDER=[first_layer_temperature[initial_extruder]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature] MATERIAL="[filament_type]" TOTAL_LAYER=[total_layer_count]
```

The `M104 S0` / `M140 S0` block at the top stops OrcaSlicer from issuing its own synchronous bed/extruder temp-waits before our PRINT_START runs — PRINT_START handles the heat-overlap internally, and we don't want a duplicate `M190` blocking before our gantry can home.

## Machine end G-code

**Printer settings → Machine G-code → Machine end G-code**:

```
PRINT_END
```

That's it. All cleanup, cooldown, park, and OFF live in the macro.

## Per-filament chamber targets

Set `chamber_temperature` per filament in **Filament settings → Cooling**:

| Filament | chamber_temperature | Notes |
|---|---|---|
| PLA, PETG, TPU | 0 | No chamber soak |
| ABS, ASA, PA-CF | 30 | Chamber continues warming to 50-55°C from bed/part radiation during the print; 30°C is a good universal start threshold for this build (per Ben, 2026-05-18) |

If `chamber_temperature` is 0 (or unset), PRINT_START skips the chamber wait and instead runs a `bed_stabilization_soak_seconds` G4 dwell (default 60s; set in `config/macros/_user_variables.cfg`).

## Optional: per-filament Z_ADJUST

Eddy native tap-Z is accurate enough that per-filament Z offsets are rarely needed. If a specific filament wants one (textured-plate compensation, material-specific first-layer behavior), two ways to apply:

### A — Pass via filament-specific Machine start G-code

In **Filament settings → Custom G-code**, duplicate the Machine start G-code for that filament and add `Z_ADJUST=0.02` (or whatever value):

```
M104 S0
M140 S0
PRINT_START EXTRUDER=[first_layer_temperature[initial_extruder]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature] MATERIAL="[filament_type]" TOTAL_LAYER=[total_layer_count] Z_ADJUST=0.02
```

### B — Inline `SET_GCODE_OFFSET` after PRINT_START (simpler)

Leave Machine start G-code alone. In **Filament settings → Custom G-code → Filament start G-code**, add:

```
SET_GCODE_OFFSET Z_ADJUST=0.02 MOVE=1
```

This runs AFTER PRINT_START finishes and applies the offset on top of the tap-Z result.

## Failure modes you might hit

- **`PRINT_START aborted: tap_threshold not calibrated`** — run `PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=guess`, then `TAP=refine`, then `TAP=verify`. Save config after each. See [[eddy-first-tap-flake]] memory for related Eddy notes.
- **`PRINT_START aborted: BED=X or EXTRUDER=Y exceeds configured max`** — a slicer profile is set above `heater_bed.max_temp` (120) or `extruder.max_temp` (configured value in `config/toolhead.cfg`). Check your filament profile.

## What ELSE the slicer can do (not in PRINT_START params today)

- **`TIMELAPSE_TAKE_FRAME`** — opt-in per print, set in Filament settings → Custom G-code → Layer change G-code if you want timelapse for that filament/print. Closed [#26](https://github.com/bjdeng/voron-2-611/issues/26). Currently gated on webcam re-plug ([#27](https://github.com/bjdeng/voron-2-611/issues/27)).
- **`SET_PRESSURE_ADVANCE ADVANCE=...`** — best set in Filament settings → Custom G-code → Filament start G-code, per-filament. PRINT_START intentionally doesn't take a `PRESSURE_ADVANCE` param; the slicer's inline `SET_PRESSURE_ADVANCE` is the canonical pattern.
