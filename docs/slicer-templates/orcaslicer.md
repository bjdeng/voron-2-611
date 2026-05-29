# OrcaSlicer hookup for Voron 2.611

How OrcaSlicer should call `PRINT_START` / `PRINT_END` on this machine, integrated with the Happy-Hare MMU lifecycle.

Spec: [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](../superpowers/specs/2026-05-18-print-lifecycle-redesign.md).

Ben's actual OrcaSlicer settings live at `/Users/ben/Library/Application Support/OrcaSlicer/user/` (per [[orcaslicer-settings-path]]). This doc captures the canonical contract; the slicer is the source of truth for what's actually configured.

## Machine start G-code

In OrcaSlicer: **Printer settings → Voron v2.611 → Machine G-code → Machine start G-code**.

```
M140 S[first_layer_bed_temperature]
M104 S0

MMU_START_SETUP INITIAL_TOOL={initial_tool} REFERENCED_TOOLS=!referenced_tools! TOOL_COLORS=!colors! TOOL_TEMPS=!temperatures! TOOL_MATERIALS=!materials! FILAMENT_NAMES=!filament_names! PURGE_VOLUMES=!purge_volumes!

MMU_START_CHECK

PRINT_START EXTRUDER=[first_layer_temperature[initial_tool]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature[initial_tool]] MATERIAL="[filament_type[initial_tool]]" TOTAL_LAYER=[total_layer_count]

MMU_START_LOAD_INITIAL_TOOL
```

The five sequential calls split responsibility cleanly:

| Call | What it does |
|---|---|
| `M140 S[first_layer_bed_temperature]` | **Start bed warming immediately, non-blocking.** Runs before MMU_START_SETUP / MMU_START_CHECK so the bed has the longest possible head start — tens of seconds saved vs. waiting for PRINT_START to issue the same command. PRINT_START will re-issue this with the same target later; duplicate is idempotent. |
| `M104 S0` | Suppress OrcaSlicer's own synchronous hotend wait. PRINT_START handles hotend heat-overlap internally; a slicer-emitted `M109` here would block before our gantry can home. (No `M140 S0` — we want the bed warming, not zeroed.) |
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

Set `chamber_temperature` per filament in **Filament settings → [filament] → Cooling**. The value is the in-print setpoint the chamber control loop holds for the whole print — PRINT_START's `TEMPERATURE_WAIT` only blocks until chamber reaches HALF this value (so a cold-start ABS print doesn't wait an hour for the full 55°C).

| Filament | chamber_temperature | Notes |
|---|---|---|
| PLA, PETG, TPU | 0 | No chamber soak — PRINT_START skips to a brief `bed_stabilization_soak_seconds` G4 (default 60s). Loop runs at VOC baseline throughout. |
| ABS, ASA, PA-CF | 55 | Loop holds chamber at 55°C for the entire print: HEAT mode (BedFans=1.0, exhaust off) below 53°C, MAINTAIN/COOL above. PRINT_START waits for chamber ≥ 27°C before tap-Z, then the loop keeps driving heat as the print runs and part radiation accumulates. Clamped to `chamber_max_target` (60) inside `SET_CHAMBER_TARGET`. |

For Ben's current filament profiles (post 2026-05-19 audit):

| Profile file | Set to |
|---|---|
| `Sunlu PLA.json` | 0 |
| `Sunlu PLA+.json` | 0 |
| `Sunlu Silk PLA.json` | 0 |
| `Inland PLA+.json` | 0 |
| `Inland Silk PLA.json` | 0 |
| `Overture Transparent PETG.json` | 0 |
| `Inland ABS.json` | 55 |
| `Ambrosia ASA.json` | 55 |

## Filament profile cascade (2026-05-19 audit)

Two-level cascade. Material defaults flow down via inheritance; brand profiles override only brand-specific values.

```
Generic <Material> @System            ← OrcaFilamentLibrary, system (don't edit)
    └─ <Brand> <Material>             ← user-level, calibrated per spool
```

After the audit, every user filament profile inherits from `Generic <Material> @System` (the canonical user-level parent in OrcaSlicer 2.2+). Previously most profiles pointed at `Voron Generic <Material>` — a dead parent that no longer exists; inheritance silently fell through to whatever default the slicer picked. Overture Transparent PETG was the worst offender (inheriting from `Voron Generic PLA` — wrong material AND dead parent).

Brand profile inventory:

| File | Inherits | Material |
|---|---|---|
| `Sunlu PLA.json` | `Generic PLA @System` | PLA |
| `Sunlu PLA+.json` | `Generic PLA @System` | PLA |
| `Sunlu Silk PLA.json` | `Generic PLA Silk @System` | PLA Silk |
| `Inland PLA+.json` | `Generic PLA @System` | PLA |
| `Inland Silk PLA.json` | `Generic PLA Silk @System` | PLA Silk |
| `Overture Transparent PETG.json` | `Generic PETG @System` | PETG |
| `Inland ABS.json` | `Generic ABS @System` | ABS |
| `Ambrosia ASA.json` | `Generic ASA @System` | ASA |

What lives at the **material layer** (set explicitly on every brand profile of that material):
- Plate temps, range_low/high, chamber_temperature, VFR cap
- Fan curves (`fan_min_speed`, `fan_max_speed`, `overhang_fan_threshold`, `overhang_fan_speed`)
- Layer-time triad (`slow_down_layer_time`, `slow_down_min_speed`, `fan_cooling_layer_time`)
- First-layer fan ramp (`close_fan_the_first_x_layers`, `full_fan_speed_layer`)
- `temperature_vitrification`, `enable_pressure_advance`, `filament_diameter`

What lives at the **brand layer** (per-spool, calibrated):
- `nozzle_temperature` / `nozzle_temperature_initial_layer` (from temp tower)
- `pressure_advance` (from PA cal)
- `filament_flow_ratio` (from flow cal)
- `filament_density` / `filament_cost` (datasheet)
- `filament_vendor`
- `filament_start_gcode` / `filament_end_gcode` (Spoolman handoff, per-filament Z_ADJUST)

## Per-material defaults (locked 2026-05-19)

These values are set explicitly on every brand profile of that material. The cascade structure makes this duplication slightly unfortunate but worth it — flat is easier to diff than an extra intermediate parent for 8 profiles.

| Setting | PLA | PETG | ABS | ASA | PLA Silk |
|---|---|---|---|---|---|
| `chamber_temperature` | 0 | 0 | **55** | **55** | 0 |
| `hot_plate_temp` | 55 | 55 | 100 | 100 | 55 |
| `hot_plate_temp_initial_layer` | 55 | 55 | 110 | 110 | 55 |
| `textured_plate_temp` | 55 | 55 | 100 | 100 | 55 |
| `textured_plate_temp_initial_layer` | 55 | 55 | 110 | 110 | 55 |
| `nozzle_temperature_range_low` | 190 | 230 | 235 | 240 | 200 |
| `nozzle_temperature_range_high` | 230 | 260 | 260 | 270 | 230 |
| `filament_max_volumetric_speed` | 18 | 12 | 14 | 14 | 7.5 |
| `fan_min_speed` | 100 | 20 | 10 | 10 | 100 |
| `fan_max_speed` | 100 | 60 | 40 | 40 | 100 |
| `overhang_fan_threshold` | 50% | 50% | 25% | 25% | 50% |
| `overhang_fan_speed` | 100 | 80 | 80 | 80 | 100 |
| `slow_down_layer_time` | 6 | 10 | 15 | 15 | 8 |
| `slow_down_min_speed` | 20 | 20 | 15 | 15 | 20 |
| `close_fan_the_first_x_layers` | 1 | 2 | 3 | 3 | 1 |
| `full_fan_speed_layer` | 2 | 4 | 5 | 5 | 2 |
| `temperature_vitrification` | 70 | 85 | 105 | 105 | 70 |

**Bed temps**: PLA/PETG at 55°C reflects empirical printer behavior on this build — 60°C bed surface temperature noticeably radiated into the toolhead's hotend cold-end zone, causing inconsistent extrusion as the heatbreak warmed. Lower bed sidesteps the issue. ABS/ASA at 100/110 unchanged (their print temps already require active hotend cooling regardless).

**`filament_max_volumetric_speed` ceiling**: 18 mm³/s for this hotend. Per-material values are below the cap by material rheology.

### Cooling values are tuned for Stealthburner v2 + Delta BFB0524HH

The part cooling fan on this build is a **Delta BFB0524HH** (24V 2-pin 5015) on `EBB:gpio4`, plugged into the EBB SB v1.0's FAN1 port (factory default: 24V output, matches the fan; verified per `vendor/btt-docs/docs/EBB SB2209 USB.md:137`). It's a community-favored upgrade from the BOM Sunon MF50151VX-A99, but datasheets (Delta + Sunon product pages, accessed 2026-05-19) confirm it delivers **comparable airflow** (Delta 4.6 CFM / 0.866 in H₂O vs. Sunon 5.4 CFM / 0.97 in H₂O) — the Delta wins on build quality and PWM linearity, not raw cooling power.

ABS/ASA-specific tuning: per [Ellis Print Tuning Guide — Cooling and Layer Times](https://ellis3dp.com/Print-Tuning-Guide/articles/cooling_and_layer_times.html) on his AB-BN (Delta-class 5015) build at 63°C chamber, ABS sweet spot is 40-50% fan_max. Our 40% in a 55°C chamber matches this — tune up if you see overhang sag, tune down if you see ABS delam at corners.

The `overhang_fan_threshold: 25%` (vs OrcaSlicer's stock 95% for PETG / 50% PLA-baseline) is the more surprising knob: with ABS/ASA general fan capped low (10-40%), overhang regions need the fan to *trigger sooner* to catch mild overhangs that would otherwise sag. Pairing 25% threshold with `overhang_fan_speed: 80` (vs the 40% general max) means overhangs get nearly 2× the baseline airflow.

**Minimum PWM threshold note**: 5015 blowers (both Sunon and Delta) may stall below ~15-20% PWM. Klipper's default `kick_start_time: 0.1s` (per `vendor/klipper/docs/Config_Reference.md:3244`) typically gets the impeller spinning, then it settles at the commanded PWM. If you ever see "fan commanded but no air" at low % during a print, **add** a `kick_start_time: 0.5` line to `config/toolhead.cfg`'s `[fan]` block at line 52 (the block currently only has `pin:` uncommented — `kick_start_time` is not present, you'd be adding it).

### What about `M106 P3` / auxiliary fan / air filtration?

OrcaSlicer can emit `M106 P3 S<n>` commands for an auxiliary fan and `M106 P<aux>` for active filtration. **Neither maps to anything on this build.** The chamber control loop in `config/macros/chamber_control.cfg` owns BedFans + `[temperature_fan chamber]` (which drives the exhaust hardware via PID; there's no separate `[fan_generic]` aux fan wired). Every brand profile sets:

```json
"additional_cooling_fan_speed": ["0"],
"during_print_exhaust_fan_speed": ["0"],
"complete_print_exhaust_fan_speed": ["0"],
"activate_air_filtration": ["0"]
```

These prevent `M106 P3` lines from being emitted into the gcode (where they'd be silent no-ops cluttering the output).

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

## Profile cleanup (status 2026-05-19)

The 2026-05-18 audit identified these as stale; the 2026-05-19 audits resolved them in two PRs:

**Resolved by PR #78 (process-profile audit):**
- ~~`default/machine/Voron 2.4 350 0.4 nozzle - Copy.json`~~ — empty machine shell, deleted
- ~~`default/process/0.20mm Standard @Voron - Copy.json`~~ — accidental Save-As, deleted
- ~~`default/process/0.20mm Standard @Voron - Fast/Match SS/PLA.json`~~ — 3 process variants, deleted; replaced by Speed/Strength/Quality

**Resolved by filament audit (this work):**
- ~~`default/filament/PLA.json`~~ — generic, no brand attached, deleted
- ~~`default/filament/Ambrosia ASA - <color>.json` (3 variants)~~ — collapsed to single `Ambrosia ASA.json`
- `user/3087889866/` — interactive delete prompt in filament apply.sh; leave or delete per session

All deletions are preserved in `docs/orcaslicer-archive/2026-05-19-pre-rewrite/` as a rollback point.

## Calibration workflow (per spool)

Tracked in [#79](https://github.com/bjdeng/voron-2-611/issues/79) — a planned skill that walks through temp → flow → PA per spool with logging. Until that ships, manual workflow:

1. Pick the existing brand profile in OrcaSlicer (NOT `Generic @System` — that bypasses your calibration)
2. Run temp tower in OrcaSlicer Calibration menu → update `nozzle_temperature` / `_initial_layer`
3. Run flow Pass 1 + Pass 2 → update `filament_flow_ratio`. (For an objective cross-check, run the `FLOW_MULTIPLIER_CALIBRATION` Klipper macro instead — caliper-measured shell thickness, more precise than Orca's visual pass.)
4. Run **Pressure Advance** in OrcaSlicer Calibration menu (Pattern method — it's the Ellis pattern test; pick the direct-drive variant in the DDE/Bowden dialog) → update `pressure_advance`. *Optional upgrade:* OrcaSlicer **Adaptive PA** builds a PA-vs-(flow × acceleration) model that you paste into the filament profile — worth it for this high-flow Galileo G2E / CoreXY setup, but note it's still a configured calibration (run the cal, set `enable_pressure_advance` + the adaptive-model fields per profile), not an automatic/live feature. (The old Frix_x `PRESSURE_ADVANCE_CALIBRATION` macro was removed 2026-05-28 — redundant with Orca's pattern test; see [#31](https://github.com/bjdeng/voron-2-611/issues/31).)
5. Run Max Volumetric Speed → confirm `filament_max_volumetric_speed` (should be at or below the per-material default)

Anomaly currently flagged (kept as-is pending re-cal): **`Inland PLA+.json: filament_flow_ratio=1.1`** — unusually high; verify via flow Pass 2.
