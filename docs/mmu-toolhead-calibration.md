# Happy Hare toolhead calibration — `MMU_CALIBRATE_TOOLHEAD`

The canonical procedure for measuring toolhead parameters that govern MMU load/unload behavior on this build (Voron 2.611, Stealthburner v2 + Galileo G2E + Dragon clone hotend + Filametrix cutter + EBB SB v1.0 toolhead board).

## Why calibrate (vs trust physical measurements)

Physical measurements (CAD numbers, ruler) describe geometry. Calibrated values describe **operational state** — including filament backlash through the Galileo gears, the actual position of the toolhead sensor, the real residual material left in the nozzle after a cutter unload, and so on. The calibrated values matter more because they're what HH actually uses for load/unload distance calculations.

Re-run when:
- Toolhead hardware changes (hotend swap, extruder swap, sensor relocation)
- Filametrix mechanics change (blade replacement, mount adjustment)
- Persistent clog runouts or under-load symptoms in normal printing
- After a full re-flash or a major Happy-Hare version bump

## The three modes (from `MMU_CALIBRATE_TOOLHEAD` source)

| Flag | What it measures | When the extruder must be |
|---|---|---|
| `CLEAN=1` | `toolhead_extruder_to_nozzle`, `toolhead_sensor_to_nozzle`, `toolhead_entry_to_extruder` | Clean (post cold-pull) |
| `DIRTY=1` | `toolhead_residual_filament`, `toolhead_entry_to_extruder` | Dirty (post-print, post-cutter-unload, cool) |
| `CUT=1` | `variable_blade_pos`, `variable_retract_length` (= blade_pos − 5) | Empty (no filament past gate), with cutter blade **manually held closed** |

The order matters — `DIRTY` and `CUT` both reference `toolhead_sensor_to_nozzle` from a recent `CLEAN` measurement.

## Hard prerequisites (HH source enforces these)

- Printer is **homed**
- Gate is **selected** (the desired gate)
- Filament is **unloaded** from the toolhead (HH loads/unloads internally during probe)
- Gate, encoder, selector, and bowden are **already calibrated**
- **Toolhead sensor** must exist (we have it at `EBB:gpio21`)
- HH not in bypass mode, MMU not disabled

If any of these fail, the command rejects with a clear error.

## Full phased procedure

### Phase 0 — Pre-flight

```
MMU_STATUS
```

Verify:
- Selector at desired gate (typically gate 5 for the most-used spool)
- Filament unloaded from extruder/toolhead
- Filament present in the gate (preloaded)
- All upstream calibrations done (gate, encoder, selector, bowdens). If any are missing, `MMU_CALIBRATE_TOOLHEAD` rejects with a specific error pointing at the missing one.

```
G28                       # Home all axes if not already
```

### Phase 1 — Cold pull (for CLEAN measurement)

Goal: completely empty the extruder/heatbreak/nozzle of all material. Residue ruins the CLEAN measurement.

Standard "atomic pull" with PLA (nylon works better for stubborn debris):

```
M104 S240
TEMPERATURE_WAIT SENSOR=extruder MINIMUM=235

MMU_HOME TOOL=5                       # Load gate 5

G92 E0
M83
G1 E50 F100                           # Extrude 50mm clean material

M104 S90
TEMPERATURE_WAIT SENSOR=extruder MAXIMUM=95
```

While extruder cools through 90°C, **manually pull the filament out at the gate** — pull hard, fast, straight. The strand should come out with a cone tip carrying residue.

Inspect the cone:
- Clean cone, no debris → done
- Brown/black flecks → repeat (reload, extrude, cool to 90, pull) until clean
- Mushroomed/ragged → fragment may be stuck; bump temp to 250°C next pass

Once clean, ensure filament is unloaded from the extruder/toolhead path (still loaded into gate, but not past the extruder gears).

### Phase 2 — CLEAN measurement

```
MMU_CALIBRATE_TOOLHEAD CLEAN=1
```

HH internally:
1. Loads filament from gate through bowden
2. Homes to extruder
3. Probes the empty toolhead (uses collision detection against the heatbreak/nozzle internal shoulder)
4. Reports measurements
5. Unloads filament back to gate

Expected output:
```
-----------------------------------------------
Calibration Results (clean nozzle):
> toolhead_extruder_to_nozzle: <new> (currently: 102.1)
> toolhead_sensor_to_nozzle: <new> (currently: 79.1)
-----------------------------------------------
```

**Decision point**:
- New values within ±1mm of current → geometry is consistent. Continue.
- New values differ by >2mm → operational state diverges from physical. Trust the calibrated values for load/unload math going forward. Update config files in Phase 5.

### Phase 3 — DIRTY measurement

Goal: measure `toolhead_residual_filament` — the material left in the nozzle/heatbreak path after a Filametrix cutter unload.

The melt zone needs to be **fully primed with fresh material** before the cutter unload, otherwise the residual measurement is meaningless. Use `BLOBIFIER PURGE_LENGTH=200` (not a 30 mm `G1 E` extrude — that's less than `toolhead_sensor_to_nozzle` after MMU_LOAD, so filament reaches the sensor but never gets pushed the remaining ~85 mm to the nozzle, and no material flows out).

**`BLOBIFIER` requires QGL first** — the macro positions the toolhead over the purge tower at specific bed coordinates and refuses if the bed plane hasn't been trammed.

```
QUAD_GANTRY_LEVEL                     # required by BLOBIFIER

M104 S220
TEMPERATURE_WAIT SENSOR=extruder MINIMUM=215

MMU_LOAD                              # gate 5 already selected
BLOBIFIER PURGE_LENGTH=200            # purges 200mm onto the purge tower

MMU_UNLOAD SKIP_TIP=1                 # cutter cut, no tip forming

M104 S0
TEMPERATURE_WAIT SENSOR=extruder MAXIMUM=50
```

Watch the purge tower during the BLOBIFIER step — if no blob forms, the load path didn't push filament to the nozzle and you need to debug that before any DIRTY measurement is meaningful. Wait until the nozzle is fully cool. Residue solidifies; that solid stub is what HH measures against on the next push.

```
MMU_CALIBRATE_TOOLHEAD DIRTY=1
```

Expected output:
```
-----------------------------------------------
Calibration Results (dirty nozzle):
> toolhead_residual_filament: <new> (currently: 23.0)
-----------------------------------------------
```

This is the load-side answer. If `<new>` is materially different from current, you've found a calibration drift that explains under-load (new tip parked too high) or over-load (new tip oozing).

### Phase 4 — CUT measurement (optional)

Skip if you trust `blade_pos`. Run if you've changed cutter mechanics or have evidence the value is wrong.

```
G28
MMU_HOME TOOL=5
```

**Physically hold the Filametrix blade closed** (manually engage the cutter mechanism). The next command will push filament into the blocked blade, sensing where resistance hits.

```
MMU_CALIBRATE_TOOLHEAD CUT=1
```

Expected output:
```
-----------------------------------------------
Calibration Results (cut tip):
> variable_blade_pos: <new> (currently: 60.3)
> variable_retract_length: <range>, recommend: <new> (currently: 38.3)
-----------------------------------------------
```

The HH source has a sanity check: if measurement < `toolhead_residual_filament + toolchange_retract`, it errors with `"Measurements did not make sense. Looks like probing went past the blade pos! Are you holding the blade closed or have cut filament in the extruder?"`. Two possible causes per the error: grip slipped, OR there's stale cut-fragment filament still inside the extruder. If you see this error, check both before re-running.

### Phase 5 — Persist results

`MMU_CALIBRATE_TOOLHEAD` with default `SAVE=1` writes into Klipper's running state but does **not** persist to config files. To survive a restart:

For values that changed, edit:

- `config/mmu/base/mmu_parameters.cfg`:
  - `toolhead_extruder_to_nozzle`
  - `toolhead_sensor_to_nozzle`
  - `toolhead_residual_filament`
  - `toolhead_entry_to_extruder` — **NOT USED on this build**. Source (`mmu.py:2786, 2804`) only persists this when an extruder-entry sensor exists (`SENSOR_EXTRUDER_ENTRY`). Our EBB SB v1.0 has only the toolhead sensor (gpio21), no separate extruder-entry sensor. `MMU_CALIBRATE_TOOLHEAD` won't report or persist this value.

- `config/mmu/base/mmu_macro_vars.cfg`:
  - `variable_blade_pos`
  - `variable_retract_length`

**Note on `mmu_parameters.cfg`**: Unlike the other `mmu/base/*.cfg` files (which are Pi-side symlinks into `~/Happy-Hare/config/base/`), `mmu_parameters.cfg` is a **real file** at `~/printer_data/config/mmu/base/mmu_parameters.cfg` — HH copies it from its template at install time to allow per-printer customization. Verified 2026-05-19: `ls -l` shows two separate inodes (Pi-side file dated 2026-05-17 vs `~/Happy-Hare/config/base/mmu_parameters.cfg` dated 2026-02-15 with stock defaults). Edit directly on the Pi at `~/printer_data/config/mmu/base/mmu_parameters.cfg`, then `RESTART` Klipper, then `/sync-from-pi` to update the repo snapshot.

**Why not SAVE_CONFIG?** Klipper's `SAVE_CONFIG` mechanism only persists values that plugins explicitly register via `configfile.set()`. HH never calls `configfile.set()` for toolhead parameters (grep confirmed) — `MMU_CALIBRATE_TOOLHEAD` with `SAVE=1` only updates Python module attributes in memory. They reset on the next restart unless persisted via manual `mmu_parameters.cfg` edit. The calibration command itself prints `"Update mmu_parameters.cfg to persist settings"` for this reason.

**`mmu_macro_vars.cfg`** (used for Phase 4 CUT values) **IS** a Pi-side symlink to `~/Happy-Hare/config/base/`. Same caveats as the other symlinked HH files — edits to the dereferenced repo copy mutate the upstream install dir if deployed without `--preserve-symlinks`. Safer to edit the Pi-side symlink target directly.

## Pitfalls

| Problem | Likely cause | Fix |
|---|---|---|
| `MMU_CALIBRATE_TOOLHEAD CLEAN=1` returns numbers but they're way off (15-20mm low/high) | Residue still in nozzle | Re-do cold pull, escalate temp to 250°C, use nylon |
| `DIRTY=1` returns near-zero residual | Cutter-unload didn't run / no residue formed | Verify `MMU_UNLOAD SKIP_TIP=1` actually invoked the cutter (`MMU_LOG`); confirm filament was extruded before unload |
| `CUT=1` errors "Are you holding the blade closed?" | Your grip slipped during probe, or `toolhead_residual_filament` is too high (false-positive guard) | Re-do with firmer grip; if recurring, check `toolhead_residual_filament` first |
| Calibration command rejects with "filament loaded" | Toolhead/extruder sensor shows filament present | `MMU_EJECT` to fully unload, then retry |
| Calibration command rejects with "must be homed" | Lost homing during prior failure | `G28` first |

## Reference (where these values are stored)

| Variable | File | Default (HH stock) | Our build's pre-recal value |
|---|---|---|---|
| `toolhead_extruder_to_nozzle` | `mmu_parameters.cfg` | varies (typ. 70-72 for SBv2) | **102.1** |
| `toolhead_sensor_to_nozzle` | `mmu_parameters.cfg` | typ. 62-64 | **79.1** |
| `toolhead_entry_to_extruder` | `mmu_parameters.cfg` | (sensor-dependent) | 9.9 — but **inactive** on this build (no extruder-entry sensor) |
| `toolhead_residual_filament` | `mmu_parameters.cfg` | typ. 3-5 | **23** |
| `variable_blade_pos` | `mmu_macro_vars.cfg` | typ. 37.5 (HH default) | **60.3** |
| `variable_retract_length` | `mmu_macro_vars.cfg` | blade_pos − 5 | **38.3** |

The "currently" values for this build are higher than HH's defaults because:
- Longer Dragon heatbreak (older variant, ~10-15mm longer than HF)
- Galileo G2E inserts more material above the gear than a stock SB-CW2
- Filametrix mount geometry on this specific install

These are physical reality on this build, not errors — but the calibrated values are what govern actual load/unload math, so they take precedence over the physical numbers when there's drift.

## Related

- HH wiki: [Calibration](https://github.com/moggieuk/Happy-Hare/wiki/Calibration), [Blobbing-and-Stringing](https://github.com/moggieuk/Happy-Hare/wiki/Blobbing-and-Stringing)
- HH source: `vendor/happy-hare/extras/mmu/mmu.py:2717-2818` (`cmd_MMU_CALIBRATE_TOOLHEAD`)
- Cut tip macro: `config/mmu/base/mmu_cut_tip.cfg`
- Cut tip variables: `config/mmu/base/mmu_macro_vars.cfg`, `[gcode_macro _MMU_CUT_TIP_VARS]` section
