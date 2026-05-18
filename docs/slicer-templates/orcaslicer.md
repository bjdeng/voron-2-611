# OrcaSlicer hookup for Voron 2.611

How OrcaSlicer should call `PRINT_START` / `PRINT_END` on this machine, integrated with the Happy-Hare MMU lifecycle.

Spec: [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](../superpowers/specs/2026-05-18-print-lifecycle-redesign.md).

Ben's actual OrcaSlicer settings live at `/Users/ben/Library/Application Support/OrcaSlicer/user/` (per [[orcaslicer-settings-path]]). This doc captures the canonical contract; the slicer is the source of truth for what's actually configured.

## Machine start G-code

In OrcaSlicer: **Printer settings → Voron v2.611 → Machine G-code → Machine start G-code**.

```
M104 S0
M140 S0

MMU_START_SETUP INITIAL_TOOL={initial_tool} REFERENCED_TOOLS=!referenced_tools! TOOL_COLORS=!colors! TOOL_TEMPS=!temperatures! TOOL_MATERIALS=!materials! FILAMENT_NAMES=!filament_names! PURGE_VOLUMES=!purge_volumes!

MMU_START_CHECK

PRINT_START EXTRUDER=[first_layer_temperature[initial_tool]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature[initial_tool]] MATERIAL="[filament_type[initial_tool]]" TOTAL_LAYER=[total_layer_count]

MMU_START_LOAD_INITIAL_TOOL
```

The five sequential calls split responsibility cleanly:

| Call | What it does |
|---|---|
| `M104 S0` / `M140 S0` | Suppress OrcaSlicer's own synchronous bed/extruder temp-waits. PRINT_START handles heat-overlap internally; a duplicate `M190` here would block before our gantry can home. |
| `MMU_START_SETUP` | Happy-Hare's pre-print MMU init. Consumes slicer-injected vars (`!referenced_tools!`, `!colors!`, etc. are processed by HH's slicer hook, not by Orca). Tells HH which tools the print uses, their materials, purge volumes. |
| `MMU_START_CHECK` | HH's gate-availability check. Verifies the gates the print needs have filament loaded. Fails fast (with operator prompt) if a gate is empty. |
| `PRINT_START` | Our macro. Tap-threshold guard, max-temp guard, CLEAR_PAUSE, non-blocking bed+hotend heat, home+QGL during heat, chamber soak, tap-Z, mesh, final hotend heat, hot BLOBIFIER_CLEAN. See `config/macros/print_start.cfg`. |
| `MMU_START_LOAD_INITIAL_TOOL` | HH's "load the first filament" step. Runs AFTER PRINT_START so the hotend is at print temperature when filament gets pushed in. |

The Orca slicer-variable syntax:

| Token | Resolves to |
|---|---|
| `[first_layer_temperature[initial_tool]]` | First-layer hotend temp for the active starting filament |
| `[first_layer_bed_temperature]` | First-layer bed temp for the active starting filament |
| `[chamber_temperature[initial_tool]]` | Chamber temp for the active filament (see below) |
| `[filament_type[initial_tool]]` | String — `PLA` / `ABS` / `ASA` / etc. — used for LCD display |
| `[total_layer_count]` | Layer count, passed to Mainsail progress UI |
| `{initial_tool}` | Active starting tool index (0–5) |
| `!referenced_tools!` etc. | Happy-Hare's own placeholders, processed by HH's slicer hook on the way to Klipper |

## Machine end G-code

**Printer settings → Voron v2.611 → Machine G-code → Machine end G-code**:

```
MMU_END
PRINT_END
```

`MMU_END` first: HH's end-of-print hook (default behavior — does NOT force unload, since the user might want filament loaded for the next print). Then `PRINT_END` for retract, lift, rear-left park, cooldown, OFF.

The mid-print cancel path is separately wired via `_CANCEL_PRINT_HOOK` (in `config/client_hooks.cfg`) which DOES force `MMU_END UNLOAD=1` — different policy because cancel is a "stop everything cleanly" event whereas normal end-of-print may chain into another print.

## Layer change G-code

**Printer settings → Voron v2.611 → Machine G-code → Layer change G-code** (informational; current value is correct):

```
;AFTER_LAYER_CHANGE
_MMU_UPDATE_HEIGHT
SET_PRINT_STATS_INFO CURRENT_LAYER={layer_num} ; For pause-at-layer functionality and progress UI
```

- `;AFTER_LAYER_CHANGE` is a moonraker-timelapse marker. If you opt into layer-change frame capture for a print (per #26 / [[orcaslicer-settings-path]]), add `TIMELAPSE_TAKE_FRAME` here in **Filament settings → Custom G-code → Layer change G-code** rather than at the machine level — keeps timelapse opt-in per filament/print.
- `_MMU_UPDATE_HEIGHT` is HH's per-layer height tracking (used for some HH operations).
- `SET_PRINT_STATS_INFO CURRENT_LAYER=...` updates Mainsail's progress UI per layer.

## Per-filament chamber targets

Set `chamber_temperature` per filament in **Filament settings → [filament] → Cooling**:

| Filament | chamber_temperature | Notes |
|---|---|---|
| PLA, PETG, TPU | 0 | No chamber soak — PRINT_START skips to a brief `bed_stabilization_soak_seconds` G4 (default 60s) |
| ABS, ASA, PA-CF | 30 | Chamber radiates to 50-55°C from bed + part during the print; 30°C is a good universal start threshold on this build (per Ben, 2026-05-18) |

For Ben's current filament profiles (as of 2026-05-18), the values needed are:

| Profile file | Set to |
|---|---|
| `PLA.json` | 0 |
| `Inland PLA+.json` | 0 |
| `Inland Silk PLA.json` | 0 |
| `Sunlu PLA.json` | 0 |
| `Sunlu PLA+.json` | 0 |
| `SUNLU Silk PLA.json` | 0 |
| `Overture Transparent PETG.json` | 0 |
| `Inland ABS.json` | 30 |
| `Ambrosia ASA.json` | 30 |
| `Ambrosia ASA - Black.json` | 30 |
| `Ambrosia ASA - Planetary Blue.json` | 30 |
| `Ambrosia ASA -Voron Red.json` | 30 |

## Per-filament MATERIAL string

`MATERIAL` is the slicer-passed `[filament_type[initial_tool]]` — typically already correct in each filament profile (Orca's stock filament types: `PLA`, `ABS`, `ASA`, `PETG`, `TPU`, `PA`, etc.). If you've edited a profile's filament_type to something non-standard, PRINT_START will display whatever string you provided on the LCD line.

## Optional: per-filament Z_ADJUST

Eddy native tap-Z is accurate enough that per-filament Z offsets are rarely needed. If a specific filament wants one (textured-plate compensation, material-specific first-layer behavior), two ways to apply:

### A — Pass via filament-specific Machine start G-code

In **Filament settings → [filament] → Custom G-code → Machine start G-code**, override the machine-level Machine start G-code (duplicate the block above and add `Z_ADJUST=0.02`):

```
M104 S0
M140 S0

MMU_START_SETUP INITIAL_TOOL={initial_tool} REFERENCED_TOOLS=!referenced_tools! TOOL_COLORS=!colors! TOOL_TEMPS=!temperatures! TOOL_MATERIALS=!materials! FILAMENT_NAMES=!filament_names! PURGE_VOLUMES=!purge_volumes!

MMU_START_CHECK

PRINT_START EXTRUDER=[first_layer_temperature[initial_tool]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature[initial_tool]] MATERIAL="[filament_type[initial_tool]]" TOTAL_LAYER=[total_layer_count] Z_ADJUST=0.02

MMU_START_LOAD_INITIAL_TOOL
```

### B — Inline `SET_GCODE_OFFSET` after PRINT_START (simpler)

Leave Machine start G-code alone. In **Filament settings → [filament] → Custom G-code → Filament start G-code**, add:

```
SET_GCODE_OFFSET Z_ADJUST=0.02 MOVE=1
```

This runs AFTER PRINT_START finishes and applies the offset on top of the tap-Z result.

## Failure modes you might hit

- **`Unknown command:'PRINT_WARMUP'`** — your Machine start gcode is still calling the removed PRINT_WARMUP macro. Update per the block above. (PR #70 removed PRINT_WARMUP; left the slicer untouched.)
- **`PRINT_START aborted: tap_threshold not calibrated`** — run `PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=guess`, then `TAP=refine`, then `TAP=verify`. Save config after each. See [[eddy-first-tap-flake]] memory for related Eddy notes.
- **`PRINT_START aborted: BED=X or EXTRUDER=Y exceeds configured max`** — a slicer profile is set above `heater_bed.max_temp` (120) or `extruder.max_temp` (configured value in `config/toolhead.cfg`). Check your filament profile.
- **Chamber wait hangs forever** — slicer set `chamber_temperature > 30` and the chamber can't physically reach that value on this build (no chamber heater; chamber warms from bed+part radiation only). Lower the per-filament `chamber_temperature` or preheat the chamber externally before the print. Klipper has no native TEMPERATURE_WAIT timeout.

## What ELSE the slicer can do (not in PRINT_START params today)

- **`TIMELAPSE_TAKE_FRAME`** — opt-in per print, set in **Filament settings → [filament] → Custom G-code → Layer change G-code** if you want timelapse for that filament/print. Closed [#26](https://github.com/bjdeng/voron-2-611/issues/26). Currently gated on webcam re-plug ([#27](https://github.com/bjdeng/voron-2-611/issues/27)).
- **`SET_PRESSURE_ADVANCE ADVANCE=...`** — best set in **Filament settings → [filament] → Custom G-code → Filament start G-code**, per-filament. PRINT_START intentionally doesn't take a `PRESSURE_ADVANCE` param; the slicer's inline `SET_PRESSURE_ADVANCE` is the canonical pattern.

## Profile cleanup recommended (mess noted by Ben, 2026-05-18)

Stale items in the user settings dir worth deleting:

- `default/machine/Voron 2.4 350 0.4 nozzle - Copy.json` — empty shell, no real content; superseded by `Voron v2.611.json`.
- `default/process/0.20mm Standard @Voron - Copy.json` — likely accidental "Save As" remnant.
- `user/3087889866/` — looks like a stale OrcaSlicer cloud-sync user-ID dir. Only contains 4 ASA filament profiles that duplicate the canonical ones in `default/filament/`. Safe to delete if Orca doesn't actively reference it after a restart.

OrcaSlicer UI deletion path: **Printer settings → drop-down → [the stale profile] → Delete**, similar for filament and process profiles. The `3087889866/` directory can be deleted from Finder once Orca is closed.
