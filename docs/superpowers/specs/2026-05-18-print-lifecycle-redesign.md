# Print lifecycle redesign — PRINT_START / PRINT_END / CANCEL_PRINT — spec

**Closes:** Inline review of `config/macros/print_start.cfg`; pairs with [#29](https://github.com/bjdeng/voron-2-611/issues/29) (OrcaSlicer per-filament profile tuning is the at-the-printer half).

**Owner:** Ben (operator-facing macro changes; needs a print test after deploy).

**Restart impact:** RESTART (gcode_macro changes only; no MCU pins, sensors, or kinematics).

---

## 1. Problem

`config/macros/print_start.cfg` was cobbled together from community examples (jontek2's pattern + Voron-community fragments). Today's flow has correctness, performance, and failure-coverage issues:

| # | Issue | Effect |
|---|---|---|
| 1 | `BLOBIFIER_CLEAN` runs **before** final `M109 S{extruder}` | Cold-nozzle wipe is ineffective at removing ooze/strings |
| 2 | No partial `M109 S150` before tap-Z + mesh | Nozzle thermal expansion not applied → Z reference is ~50µm off |
| 3 | Bed temp is the branch signal (`bed > 90`) for chamber soak | Noisy proxy — PETG at 80 bed wants no chamber, ABS at 105 wants chamber; bed temp doesn't reliably classify material |
| 4 | Chamber wait threshold hardcoded to `CHAMBER/2` | Per-material chamber settings can't live in slicer filament profiles |
| 5 | Heaters block-set with `M190` synchronously before mechanical ops | ~30s of bed-heat time wasted while gantry could be homing + QGL'ing |
| 6 | No `CLEAR_PAUSE` at start | Stale pause state from a cancelled prior print can carry over |
| 7 | No bed/extruder max-temp guard on slicer params | A misconfigured slicer profile could (in theory) command above heater max_temp; Klipper rejects it but the error is late + cryptic |
| 8 | `PRINT_WARMUP` is a parallel manual prewarm macro | Duplicates initial steps of PRINT_START; never called by slicer; confusing |
| 9 | `_CLIENT_VARIABLE` is not defined in the repo | Upstream Mainsail `CANCEL_PRINT` runs no user hook → cancel-mid-print does NOT trigger our cooldown / OFF / `_RESETSPEEDS` — same printer state as a kill-power-mid-print |
| 10 | `PRINT_END` has no XY park | Toolhead stops over the print, blocking removal |
| 11 | `PRINT_END` has no filament retract before lift | Strings stick to the part |

## 2. Goal

Rebuild `PRINT_START` and `PRINT_END`, hook `CANCEL_PRINT` into the same cleanup path, and document the slicer-side contract for OrcaSlicer.

**Non-goals:**

- Per-filament tuning (temps, speeds, retraction values, PA) — that's the at-the-printer half of #29 and not a brainstormable design.
- Per-material config dict in macros — slicer filament profiles are the right home for per-material settings (cleaner separation of concerns; matches jontek2 + the user-picked Approach B from brainstorm).
- MMU lifecycle integration in PRINT_START/END — Happy-Hare's slicer hooks already run independently; out of scope unless a sanity check surfaces as needed.
- Klipper-side timeout on `TEMPERATURE_WAIT` for chamber — Klipper's `heater_verify` catches genuine heater failures; a stuck chamber-fan would need a different mechanism. File separately if needed.
- L7 snapshot equivalence — this PR intentionally changes behavior; we'll capture a fresh L7 baseline after merge.

## 3. PRINT_START design

### 3.1 Flow (with heat-overlap optimization)

```ini
[gcode_macro PRINT_START]
description: Full print start. Validates slicer params, overlaps mechanical setup with bed/hotend warmup, taps Z with hot bed + warm nozzle, calibrates mesh, hot-wipes the nozzle.
gcode:
  # 1. Tap-threshold pre-flight (existing; keep).
  {% set probe_cfg = printer.configfile.settings['probe_eddy_current btt_eddy'] %}
  {% if probe_cfg.tap_threshold|default(0)|float <= 0 %}
    { action_raise_error("PRINT_START aborted: tap_threshold not calibrated. Run PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=guess, then TAP=refine, then TAP=verify, with SAVE_CONFIG after each.") }
  {% endif %}

  # 2. Slicer-provided params (with defaults for optional ones).
  {% set bed       = params.BED|int %}
  {% set extruder  = params.EXTRUDER|int %}
  {% set chamber   = params.CHAMBER|default(0)|int %}
  {% set material  = params.MATERIAL|default("?")|string %}
  {% set total_layer = params.TOTAL_LAYER|default(0)|int %}
  {% set z_adjust  = params.Z_ADJUST|default(0)|float %}

  # 3. Max-temp guard. Slicer profile errors should not silently risk hardware.
  {% set bed_max = printer.configfile.settings.heater_bed.max_temp|int %}
  {% set ext_max = printer.configfile.settings.extruder.max_temp|int %}
  {% if bed > bed_max or extruder > ext_max %}
    { action_raise_error("PRINT_START aborted: BED=%d or EXTRUDER=%d exceeds configured max (%d / %d)." % (bed, extruder, bed_max, ext_max)) }
  {% endif %}

  # 4. State reset (clears stale state from any prior cancelled print).
  CLEAR_PAUSE
  _RESETSPEEDS
  BED_MESH_CLEAR
  SET_PIN PIN=caselight VALUE=0.3

  # 5. UI hints (optional params — no-op if not provided).
  {% if total_layer > 0 %}
    SET_PRINT_STATS_INFO TOTAL_LAYER={total_layer}
  {% endif %}
  M117 Print: {material} bed={bed} hotend={extruder} chamber={chamber}

  # 6. Start heaters NON-BLOCKING. Bed/hotend warm while we do mechanical work.
  {% set bedfans_threshold = printer["gcode_macro _USER_VARIABLE"].bedfans_threshold|int %}
  {% if bed >= bedfans_threshold %}
    BEDFANSSLOW
  {% else %}
    BEDFANSOFF
  {% endif %}
  M140 S{bed}                                            # bed target (non-blocking)
  M104 S150                                              # hotend partial (non-blocking)

  # 7. Mechanical ops while heat ramps. Cold-bed QGL is correct: Voron 2.4
  #    gantry's thermal expansion across chamber temp range is sub-100µm and
  #    the 4 QGL probe points expand uniformly. Bed mesh (step 12) handles
  #    any residual bed-surface shape change at temp.
  _CG28
  G90
  _CQGL

  # 8. Wait for the heat we started in step 6.
  TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={bed}
  TEMPERATURE_WAIT SENSOR=extruder MINIMUM=150 MAXIMUM=170

  # 9. Chamber soak branch (slicer-driven, per-material).
  {% set soak_s = printer["gcode_macro _USER_VARIABLE"].bed_stabilization_soak_seconds|int %}
  {% if chamber > 0 %}
    # Hot material (ABS/ASA/PA-CF): chamber air circulation + wait.
    # Per Ben (2026-05-18): 30°C is a good universal start-threshold for
    # ABS/ASA/PA-CF on this build — the chamber continues warming to
    # 50-55°C from bed + part radiation during the print itself, so
    # waiting for full target chamber wastes time. Slicer should pass
    # CHAMBER=30 for those materials. CHAMBER=0 = no chamber wait.
    M106 S255                                            # PT-fan stirs chamber air
    PARKCENTER                                           # nozzle off the print zone
    TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={chamber}
  {% elif soak_s > 0 %}
    # Cold material (PLA/PETG): brief bed-mass equilibration soak.
    G4 P{(soak_s * 1000)|int}
  {% endif %}

  # 10. Tap-Z with hot bed + warm nozzle. eddy.cfg's [homing_override]
  #     automatically runs SET_Z_FROM_PROBE here.
  G28 Z

  # 11. Per-filament Z baby-step (optional). Eddy tap-Z makes this mostly
  #     unnecessary, but useful for plate-type compensation (smooth vs
  #     textured) or filaments that need a small offset for first-layer
  #     adhesion. SET_GCODE_OFFSET applies on top of the tap-Z result.
  {% if z_adjust != 0.0 %}
    SET_GCODE_OFFSET Z_ADJUST={z_adjust} MOVE=1
  {% endif %}

  # 12. Adaptive bed mesh over the actual print area.
  BED_MESH_CALIBRATE ADAPTIVE=1

  # 13. Final hotend heat + hot nozzle wipe.
  M109 S{extruder}                                       # blocking; reach print temp
  M107                                                   # part cooling fan off
  BLOBIFIER_CLEAN                                        # hot wipe = effective wipe
```

### 3.2 Slicer params

| Param | Required? | Default | Source in OrcaSlicer |
|---|---|---|---|
| `BED` | yes | — | `[first_layer_bed_temperature]` |
| `EXTRUDER` | yes | — | `[first_layer_temperature[initial_extruder]]` |
| `CHAMBER` | optional | `0` (no chamber soak) | `[chamber_temperature]` (per-filament). Set to `30` for ABS/ASA/PA-CF on this build; chamber continues warming to 50-55°C from bed/part radiation during the print. |
| `MATERIAL` | optional | `"?"` | `[filament_type]` (per-filament built-in) |
| `TOTAL_LAYER` | optional | `0` (no UI update) | `[total_layer_count]` |
| `Z_ADJUST` | optional | `0.0` (no adjust) | per-filament custom var (Filament settings → Filament G-code, e.g. `Z_ADJUST=0.02`). Eddy tap makes this mostly unnecessary; useful for plate-type compensation or filaments that want a small first-layer offset. Applied via `SET_GCODE_OFFSET Z_ADJUST=...`. |

### 3.3 What's removed

- **`PRINT_WARMUP` macro** — deleted. Prewarming before a queued print is done via direct gcode (`M140 S110`, `M104 S150`) or via `HEATSOAK T=110 C=30 MOVE=0 WAIT=0` (Ellis-style manual heatsoak).
- **`_USER_VARIABLE.chamber_wait_bed_threshold`** — no longer used; chamber branch is now driven by `CHAMBER > 0`.

## 4. PRINT_END design

```ini
[gcode_macro PRINT_END]
description: Normal end-of-print cleanup. Retracts, lifts, parks at rear-left, then defers to _PRINT_END_CLEANUP for cooldown + OFF.
gcode:
  M400                                                   # flush move buffer
  G92 E0                                                 # zero extruder
  G91                                                    # relative
  G1 E-2 F2700                                           # small retract — clean nozzle disengage
  G1 Z10 F3000                                           # lift 10mm (vs 5 today)
  G90                                                    # absolute
  G1 X{printer.toolhead.axis_minimum.x + 5} Y{printer.toolhead.axis_maximum.y - 5} F6000   # park rear-left
  TURN_OFF_HEATERS                                       # heaters off now (so cooldown is from off-state)
  M107                                                   # part fan off
  _PRINT_END_CLEANUP                                     # shared with CANCEL_PRINT hook
```

### 4.1 Why park at rear-left

- Rear-left is consistent with the Voron-default exit position used by Mainsail's `_TOOLHEAD_PARK_PAUSE_CANCEL`.
- Out of the way for print removal.
- Easy to reach the toolhead for nozzle inspection without crossing the print.

If a different park is preferred, change the inline `G1 X... Y...` line. We do not introduce `_USER_VARIABLE` knobs for park position (YAGNI — one-line edit if needed).

## 5. CANCEL_PRINT hook

Today: upstream Mainsail `CANCEL_PRINT` calls `client.user_cancel_macro` (defaulting to empty) before `CANCEL_PRINT_BASE`. We don't define `_CLIENT_VARIABLE`, so no user hook runs — cancel-mid-print stops at upstream's bare cleanup (retract + park + heaters-off).

Fix: define `_CLIENT_VARIABLE` with the hook wired to a shared cleanup macro.

```ini
[gcode_macro _CLIENT_VARIABLE]
description: Mainsail-config _CLIENT_VARIABLE — holds variables consumed by the upstream client.cfg hooks. user_cancel_macro routes CANCEL_PRINT cleanup into our _PRINT_END_CLEANUP so cancel-mid-print gets the same cooldown + OFF + _RESETSPEEDS as a normal PRINT_END.
variable_user_cancel_macro: "_PRINT_END_CLEANUP"
gcode:
  # Variables-only macro; no body. Same pattern as _USER_VARIABLE.
```

Other `_CLIENT_VARIABLE` variables (`use_custom_pos`, `custom_park_x`, etc.) are left unset — upstream defaults are correct for this build. If we later want a custom pause-park position, that's where it lives.

```ini
[gcode_macro _PRINT_END_CLEANUP]
description: Shared cleanup tail — bed mesh clear, cooldown delay, OFF, reset speeds. Called by PRINT_END (after its retract/park/heaters-off) and by upstream CANCEL_PRINT via user_cancel_macro.
gcode:
  BED_MESH_CLEAR
  {% set cooldown_ms = printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds|int * 1000 %}
  G4 P{cooldown_ms}
  OFF
  _RESETSPEEDS
```

### 5.1 Why share the cleanup tail

- Same printer state at the end of a print regardless of normal-vs-cancel path.
- Single source of truth for "what cooldown + OFF means."
- Cancel-mid-print today is a real footgun (heaters fully off but fans/lights/steppers stay engaged); shared cleanup closes it.

The cooldown delay (default 60s) applies to both paths. If you cancel a print and want immediate shutdown, that's `OFF` from the console, not `CANCEL_PRINT`.

## 6. `_USER_VARIABLE` changes

**Remove:**
```diff
- variable_chamber_wait_bed_threshold: 90
```
(No longer consulted; chamber branch is now `CHAMBER > 0` from slicer.)

**Add:**
```diff
+ variable_bed_stabilization_soak_seconds: 60  # cold-material soak after bed reaches target (0 = no extra soak)
```

`print_end_cooldown_seconds: 60` stays unchanged. Other variables (`bedfans_*`, `heatsoak_default_*`, `m109_tolerance_celsius`, `m190_tolerance_celsius`) are unaffected.

## 7. Slicer-side template

New file: `docs/slicer-templates/orcaslicer.md`. Documents the contract Orca should call.

```markdown
# OrcaSlicer hookup

## Machine start G-code

In OrcaSlicer: **Printer settings → Machine G-code → Machine start G-code**.

```
M104 S0    ; suppress OrcaSlicer's separate temp-wait sends
M140 S0
PRINT_START EXTRUDER=[first_layer_temperature[initial_extruder]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature] MATERIAL="[filament_type]" TOTAL_LAYER=[total_layer_count]
```

(If a filament profile sets `Z_ADJUST` in its custom G-code, that
gets passed through via OrcaSlicer's params automatically — no change
to Machine start G-code needed.)

## Machine end G-code

**Printer settings → Machine G-code → Machine end G-code**:

```
PRINT_END
```

## Per-filament chamber targets

Set `chamber_temperature` per filament in OrcaSlicer (Filament settings → Cooling):

| Filament | chamber_temperature | Notes |
|---|---|---|
| PLA, PETG, TPU | 0 | No chamber soak |
| ABS, ASA, PA-CF | 30 | Chamber continues warming to 50-55°C during print from bed/part radiation; 30°C is a good universal start threshold for this build |

## Optional: per-filament Z_ADJUST

Two ways to apply a per-filament Z offset baby-step, depending on what you
prefer:

### A — Pass as a PRINT_START param (via per-filament Machine start gcode)

OrcaSlicer's "Machine start G-code" can be overridden per filament in
**Filament settings → Custom G-code**. For filaments that want a Z offset,
duplicate the full Machine start gcode in the filament's start gcode and
add `Z_ADJUST=0.02`:

```
M104 S0
M140 S0
PRINT_START EXTRUDER=[first_layer_temperature[initial_extruder]] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature] MATERIAL="[filament_type]" TOTAL_LAYER=[total_layer_count] Z_ADJUST=0.02
```

### B — Inline `SET_GCODE_OFFSET` after PRINT_START (simpler)

Leave Machine start gcode alone. In Filament settings → Custom G-code, add a
small snippet that runs AFTER PRINT_START finishes:

```
SET_GCODE_OFFSET Z_ADJUST=0.02 MOVE=1
```

Same effect on print, no duplicate gcode templates. Recommended when you only
need this for a few filaments.

Either path applies on top of the Eddy tap-Z result. With Eddy native this
is rarely needed; documented for the case it is.
```

## 8. Failure-mode coverage

| Failure | Today | After |
|---|---|---|
| Tap not calibrated | Cryptic mid-PRINT_START error | Early `action_raise_error` with fix steps (existing; preserved) |
| Bed/ext target above max_temp | Klipper rejects late | Early `action_raise_error` with both values printed |
| User cancels mid-print | Heaters off, no cooldown, fans/lights/steppers still on | Full `_PRINT_END_CLEANUP` runs |
| Stale `PAUSE` state from prior cancel | Carries into next print | `CLEAR_PAUSE` upfront |
| QGL with cold bed | Done cold today (correct, kept) | Done during bed warmup; bed mesh handles thermal compensation |
| Cold-nozzle wipe | Ineffective today | Moved to after final M109 |
| Chamber never reaches target (heater fault, stuck thermistor) | Hangs forever | Same — out of scope; rely on `heater_verify`. File follow-up if encountered. |

## 9. Future enhancement (deferred)

**Material identification from MMU/Spoolman, not slicer.** Today's `MATERIAL` param is slicer-passed (per Orca's `[filament_type]`). A better long-term setup reads the active spool's material from Happy Hare (`printer["gcode_macro _MMU_CURRENT_TOOL"]` or similar) or from Spoolman's `/spoolman/spool/<id>` endpoint. Logged here as a "rewire later" — not in this spec.

## 10. Testing strategy

| Layer | What it covers |
|---|---|
| **L1** pre-commit | Text hygiene |
| **L2** macro_refcheck | New macros (`_CLIENT_VARIABLE`, `_PRINT_END_CLEANUP`) and removed macro (`PRINT_WARMUP`) — every gcode call must resolve |
| **L3** klippy parse | Catches config errors (e.g., `_CLIENT_VARIABLE` syntax) |
| **L4** pytest macro_refcheck | Tests of L2 |
| **L5** test_config_structure | Every gcode_macro has description; `_USER_VARIABLE.bed_stabilization_soak_seconds` is referenced; removed `chamber_wait_bed_threshold` is no longer referenced |
| **L6** post-deploy smoke | Existing smoke (G28 + PARKCENTER + OFF + _RESETSPEEDS) still passes — these are touched by our cleanup path |
| **L7** snapshot diff | **Not applicable as a gate** — this PR intentionally changes behavior. Capture a fresh baseline after merge for future regression checks. |

Manual verification post-deploy:
- Cold-material short test print (PLA, CHAMBER=0): confirms heat-overlap timing, mesh, end-of-print park at rear-left.
- Hot-material short test print (ABS, CHAMBER=40): confirms chamber soak path.
- Mid-print CANCEL_PRINT: confirms `_PRINT_END_CLEANUP` runs (caselight off, fans off, _RESETSPEEDS).

## 11. Anti-criteria

- No changes to `eddy.cfg`'s `[homing_override]` Z-tap pattern ([[qgl-two-pass-intentional]] — the 2-pass override there is unrelated).
- No changes to `_USER_VARIABLE` other than the one removal + one addition above.
- No introduction of `[skew_correction]`, `[firmware_retraction]`, or `[exclude_object]` — not in scope.
- No edits to `mainsail.cfg` body — that's the symlinked client.cfg's territory. We add `_CLIENT_VARIABLE` separately.
- No Klipper-side timeout on `TEMPERATURE_WAIT` — out of scope (would file as follow-up if chamber heater issue surfaces).

## 12. References

- `config/macros/print_start.cfg` (current)
- `config/macros/macros.cfg` (M109/M190 overrides, OFF, PARKCENTER, HEATSOAK, _CG28, _CQGL)
- `config/macros/bedfans.cfg` (M190 override + bedfans)
- `config/mainsail.cfg` (Mainsail _TOOLHEAD_PARK_PAUSE_CANCEL — preserved as-is)
- Upstream Mainsail [client.cfg hooks](https://github.com/mainsail-crew/mainsail-config/blob/master/client.cfg) (user_cancel_macro / user_pause_macro / user_resume_macro)
- [jontek2 A-better-print_start-macro](https://github.com/jontek2/A-better-print_start-macro) (canonical Voron pattern; original PRINT_START upstream)
- [Frix-x klippain start_print.cfg](https://github.com/Frix-x/klippain/blob/main/macros/base/start_print.cfg) (modular pattern; inspiration for slicer-passed params, not adopted wholesale)
- Related GitHub issues: [#29](https://github.com/bjdeng/voron-2-611/issues/29) (Orca filament profile tuning — the at-the-printer half).

---

## 2026-05-21 amendment — pre-mesh tap-Z removed

**Change:** Removed the pre-mesh `G28 Z` (originally step 10 in `print_start.cfg`, between chamber soak and `BED_MESH_CALIBRATE`). The two-tap pattern is now a one-tap pattern — only the post-`BLOBIFIER_CLEAN` tap remains.

**Why the pre-mesh tap was redundant:**

Klipper's `bed_mesh` stores per-XY Z offsets *relative* to the `zero_reference_position` (set to `175, 175` in `config/eddy.cfg`). The mesh describes bed surface SHAPE, not absolute Z values. When kinematic Z=0 is rebased later via another `G28 Z`, the mesh's anchor point follows; the relative shape compensation stays correct against the new reference.

The Eddy probe in scan mode also doesn't require a print-accurate Z=0 to probe — it measures distance-to-bed directly via LDC1612 frequency. As long as the toolhead is within the calibrated 0-4 mm scan range (which the cold-Z reference from step 7's `_CG28` satisfies easily — cold/hot bed delta is ~50 µm, well under 4 mm), the mesh is accurate regardless of when Z was last tapped.

So the original three-tap chain (cold tap in step 7's `_CG28` → warm tap in step 10 → hot tap in step 14) was over-cautious. The cold tap homes Z so QGL + mesh can run; the hot tap establishes the print-authoritative Z=0. The warm middle tap contributed no information not already captured by the other two.

**Savings:** ~10-15 seconds per print.

**Order clarification:** Filament loading via `MMU_START_LOAD_INITIAL_TOOL` happens AFTER PRINT_START returns (slicer's outer wrapper, per `docs/slicer-templates/orcaslicer.md`). The final `G28 Z` in PRINT_START is before filament load and remains the print-authoritative Z reference; loading filament doesn't affect Z calibration.

**Test plan:** one PLA short-print to confirm first-layer quality is unchanged from the pre-amendment baseline. If a first-layer regression appears, revert and re-investigate (the analysis above would be wrong about something specific — likely the mesh anchor behavior under non-default settings).

**Doc sync:**
- `config/macros/print_start.cfg` step comments rewritten to reflect single-tap pattern; old steps 11→10, 12→11, 13+14 merged into 12.
- `CLAUDE.md` PRINT_START description in `## Macro inventory` updated (dropped the "first tap-Z" reference).
