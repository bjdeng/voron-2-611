# Print lifecycle redesign — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `PRINT_START` / `PRINT_END` / `PRINT_WARMUP` with a heat-overlapped lifecycle, hook `CANCEL_PRINT` into a shared cleanup tail via `_CLIENT_VARIABLE`, and document the OrcaSlicer-side contract.

**Architecture:** Pure macro work in 3 .cfg files (`print_start.cfg`, `_user_variables.cfg`, `mainsail.cfg`). One new doc (`docs/slicer-templates/orcaslicer.md`). One CLAUDE.md update. No MCU/pin/sensor changes; restart impact is RESTART.

**Tech Stack:** Klipper gcode_macros (jinja2). Pre-commit + pytest + macro_refcheck + klippy parse for verification. Manual print test post-deploy.

**Source spec:** [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](../specs/2026-05-18-print-lifecycle-redesign.md)

---

## Pre-flight (worktree)

This plan assumes you're in an isolated git worktree branched from `origin/main` (`feat/print-lifecycle`). Confirm:

```bash
git status                    # clean
git log --oneline -1          # HEAD = origin/main
.venv/bin/python -c "import pytest" && echo OK   # venv present
```

## File map

| Task | Created | Modified |
|---|---|---|
| 1 | — | `config/macros/_user_variables.cfg`, `config/macros/print_start.cfg` |
| 2 | — | `config/mainsail.cfg` |
| 3 | `docs/slicer-templates/orcaslicer.md` | — |
| 4 | — | `CLAUDE.md` |
| 5 | — | — (verification only) |
| 6 | — | (push + PR + merge) |

Tests stay as-is — the existing pyramid (L2 macro_refcheck, L5 structural, L3 klippy parse in CI) already covers macro changes. No new pytest tests are needed; new gcode_macros are validated by the existing structural tests (descriptions required, `_USER_VARIABLE` refs resolve).

---

### Task 1: Macro rewrite — `_user_variables.cfg` + `print_start.cfg`

**Files:**
- Modify: `config/macros/_user_variables.cfg`
- Modify: `config/macros/print_start.cfg`

This is one atomic commit because the two files reference each other (PRINT_START reads `bed_stabilization_soak_seconds`; removing `chamber_wait_bed_threshold` from `_user_variables.cfg` is what makes the new PRINT_START not double-reference it).

- [ ] **Step 1: Update `config/macros/_user_variables.cfg`** — remove `chamber_wait_bed_threshold`, add `bed_stabilization_soak_seconds`.

Find this block:

```ini
#   chamber_wait_bed_threshold was the literal 90 in PRINT_START's bed check
#   print_end_cooldown_seconds was the 60000 in PRINT_END's G4 P60000
```

Replace with:

```ini
#   bed_stabilization_soak_seconds added 2026-05-18 — cold-material soak
#     after the bed reaches target. Replaces the unconditional 5-min G4
#     P300000 pattern from jontek2.
#   chamber_wait_bed_threshold removed 2026-05-18 — chamber soak is now
#     driven by CHAMBER>0 from the slicer (cleaner per-material control
#     in filament profiles); the bed-temp threshold proxy is gone.
#   print_end_cooldown_seconds was the 60000 in PRINT_END's G4 P60000
```

Then find:

```ini
# PRINT_START / PRINT_END pacing
variable_chamber_wait_bed_threshold: 90   # bed temp above which we wait for chamber
variable_print_end_cooldown_seconds: 60   # PRINT_END "let things circulate" delay
```

Replace with:

```ini
# PRINT_START / PRINT_END pacing
variable_bed_stabilization_soak_seconds: 60   # PRINT_START soak after bed reaches target (cold-material path; 0 = no soak)
variable_print_end_cooldown_seconds: 60       # PRINT_END "let things circulate" delay
```

- [ ] **Step 2: Replace `config/macros/print_start.cfg` in full**

Overwrite the entire file with:

```ini
#####################################################################
#   Print lifecycle — PRINT_START / PRINT_END + shared cleanup tail.
#
#   Spec: docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md
#   Originally derived from jontek2's "A better print_start macro" with
#   heat-overlap optimization (bed/hotend warm in background while
#   gantry homes + QGLs).
#####################################################################

[gcode_macro PRINT_START]
description: Full print start. Validates slicer params, overlaps mechanical setup with bed/hotend warmup, taps Z with hot bed + warm nozzle, calibrates mesh, hot-wipes the nozzle.
gcode:
  # 1. Tap-threshold pre-flight. PROBE METHOD=tap fails with "Tap not
  #    configured" if tap_threshold isn't > 0 (vendor/klipper/klippy/
  #    extras/probe_eddy_current.py:683). Surface the actionable fix
  #    instead of letting Klipper's terse error fire mid-PRINT_START.
  {% set probe_cfg = printer.configfile.settings['probe_eddy_current btt_eddy'] %}
  {% if probe_cfg.tap_threshold|default(0)|float <= 0 %}
    { action_raise_error("PRINT_START aborted: tap_threshold not calibrated. Run PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=guess, then TAP=refine, then TAP=verify, with SAVE_CONFIG after each.") }
  {% endif %}

  # 2. Slicer-provided params.
  {% set bed         = params.BED|int %}
  {% set extruder    = params.EXTRUDER|int %}
  {% set chamber     = params.CHAMBER|default(0)|int %}
  {% set material    = params.MATERIAL|default("?")|string %}
  {% set total_layer = params.TOTAL_LAYER|default(0)|int %}
  {% set z_adjust    = params.Z_ADJUST|default(0)|float %}

  # 3. Max-temp guard. A misconfigured slicer profile shouldn't risk
  #    hardware. Klipper would eventually reject, but late + cryptic.
  {% set bed_max = printer.configfile.settings.heater_bed.max_temp|int %}
  {% set ext_max = printer.configfile.settings.extruder.max_temp|int %}
  {% if bed > bed_max or extruder > ext_max %}
    { action_raise_error("PRINT_START aborted: BED=%d or EXTRUDER=%d exceeds configured max (heater_bed.max_temp=%d / extruder.max_temp=%d)." % (bed, extruder, bed_max, ext_max)) }
  {% endif %}

  # 4. State reset (clears stale state from any prior cancelled print).
  CLEAR_PAUSE
  _RESETSPEEDS
  BED_MESH_CLEAR
  SET_PIN PIN=caselight VALUE=0.3

  # 5. UI hints. SET_PRINT_STATS_INFO TOTAL_LAYER drives Mainsail's
  #    progress bar accuracy. M117 is a quick LCD/Mainsail status line.
  {% if total_layer > 0 %}
    SET_PRINT_STATS_INFO TOTAL_LAYER={total_layer}
  {% endif %}
  M117 Print: {material} bed={bed} hotend={extruder} chamber={chamber}

  # 6. Start heaters NON-BLOCKING — bed warms while gantry homes + QGLs.
  #    SET_HEATER_TEMPERATURE (vs M140) is the right entry point: our
  #    bedfans.cfg override of SET_HEATER_TEMPERATURE fires BEDFANSSLOW
  #    + starts the bedfanloop delayed-gcode (ramps to BEDFANSFAST when
  #    target is reached). M140 alone would skip that wiring.
  SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={bed}
  M104 S150                                              # hotend partial (non-blocking)

  # 7. Mechanical ops while heaters ramp. Cold-bed QGL is correct on
  #    this Voron 2.4: gantry frame thermal expansion across chamber
  #    temp range is sub-100µm and the 4 QGL probe points expand
  #    uniformly. Bed mesh (step 11) handles any residual bed-surface
  #    shape change at temp.
  _CG28
  G90
  _CQGL

  # 8. Now wait for the heat we started in step 6.
  {% set bed_tol = printer["gcode_macro _USER_VARIABLE"].m190_tolerance_celsius|int %}
  TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={bed} MAXIMUM={bed + bed_tol}
  TEMPERATURE_WAIT SENSOR=extruder MINIMUM=150 MAXIMUM=170

  # 9. Chamber soak branch (slicer-driven, per-material).
  #    Hot materials (ABS/ASA/PA-CF): slicer passes CHAMBER=30 — chamber
  #    will continue heating to 50-55°C from bed + part radiation during
  #    the print itself; waiting for full target wastes time.
  #    Cold materials (PLA/PETG/TPU): slicer passes CHAMBER=0 — we run
  #    a brief bed-mass equilibration soak instead.
  {% set soak_s = printer["gcode_macro _USER_VARIABLE"].bed_stabilization_soak_seconds|int %}
  {% if chamber > 0 %}
    M106 S255                                            # PT-fan stirs chamber air
    PARKCENTER                                           # nozzle off the print zone during soak
    TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={chamber}
  {% elif soak_s > 0 %}
    G4 P{(soak_s * 1000)|int}
  {% endif %}

  # 10. Tap-Z with hot bed + warm nozzle. eddy.cfg's [homing_override]
  #     automatically runs SET_Z_FROM_PROBE here.
  G28 Z

  # 11. Per-filament Z baby-step (optional). Eddy native tap makes this
  #     mostly unnecessary; useful for plate-type compensation (smooth
  #     vs textured) or filament-specific first-layer behavior.
  {% if z_adjust != 0.0 %}
    SET_GCODE_OFFSET Z_ADJUST={z_adjust} MOVE=1
  {% endif %}

  # 12. Adaptive bed mesh over the actual print area.
  BED_MESH_CALIBRATE ADAPTIVE=1

  # 13. Final hotend heat + hot nozzle wipe. M109 (our override) waits
  #     within m109_tolerance_celsius of target.
  M109 S{extruder}
  M107                                                   # part cooling fan off
  BLOBIFIER_CLEAN                                        # hot wipe = effective wipe


[gcode_macro PRINT_END]
description: Normal end-of-print cleanup. Retracts, lifts, parks at rear-left, then defers to _PRINT_END_CLEANUP for cooldown + OFF. CANCEL_PRINT mid-print runs _PRINT_END_CLEANUP only (upstream client.cfg handles its own retract+park+heaters-off first).
gcode:
  M400                                                   # flush move buffer
  G92 E0                                                 # zero extruder
  G91                                                    # relative
  G1 E-2 F2700                                           # small retract — clean nozzle disengage
  G1 Z10 F3000                                           # lift 10mm
  G90                                                    # absolute
  G1 X{printer.toolhead.axis_minimum.x + 5} Y{printer.toolhead.axis_maximum.y - 5} F6000   # park rear-left
  TURN_OFF_HEATERS
  M107                                                   # part fan off
  _PRINT_END_CLEANUP


[gcode_macro _PRINT_END_CLEANUP]
description: Shared cleanup tail — bed mesh clear, cooldown delay, OFF, reset speeds. Called by PRINT_END (after its retract/park/heaters-off) and by upstream CANCEL_PRINT via _CLIENT_VARIABLE.user_cancel_macro.
gcode:
  BED_MESH_CLEAR
  {% set cooldown_ms = printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds|int * 1000 %}
  G4 P{cooldown_ms}
  OFF
  _RESETSPEEDS
```

This deletes `PRINT_WARMUP` and `_RELOAD_Z_OFFSET_FROM_PROBE`-style cruft via the full-file overwrite — they were never load-bearing. `PRINT_WARMUP` was never called by the slicer.

- [ ] **Step 3: Run `make test-py`** — verify the changes parse and tests stay green.

```bash
make test-py
```

Expected: all 91 tests pass + pre-commit clean.

If `test_user_variable_refs_resolve` (in `tests/test_config_structure.py`) fails — that means a macro references a `_USER_VARIABLE.X` that doesn't exist. Either the rename is wrong (`bed_stabilization_soak_seconds` should match between the variable definition and PRINT_START's reference) or a stale reference is still in the file.

If `macro_refcheck` fails — a macro body calls a command that isn't defined. Likely culprit: `SET_HEATER_TEMPERATURE`, `BLOBIFIER_CLEAN`, `OFF`, `_RESETSPEEDS`, `_CG28`, `_CQGL`, `PARKCENTER`, `TURN_OFF_HEATERS`, `CLEAR_PAUSE`, `SET_PIN`, `SET_GCODE_OFFSET`, `M117`, `M106`, `M107`, `M104`, `M109`, `M140`, `M190`, `M400`, `M84`, `BED_MESH_CALIBRATE`, `BED_MESH_CLEAR`, `G4`, `G28`, `G90`, `G91`, `G92`, `G1`, `SET_PRINT_STATS_INFO`. All of these should be defined or built-in.

- [ ] **Step 4: Commit**

```bash
git add config/macros/print_start.cfg config/macros/_user_variables.cfg
git commit -m "$(cat <<'EOF'
feat(macros): redesign PRINT_START / PRINT_END lifecycle — spec 2026-05-18

PRINT_START gains heat-overlap (bed + hotend partial start non-blocking
while gantry homes + QGLs), partial M109 S150 before tap-Z for accurate
Z reference, slicer-driven chamber soak (CHAMBER>0 branch instead of
bed>90 threshold), hot-nozzle BLOBIFIER_CLEAN (was cold), CLEAR_PAUSE
upfront, and a bed/extruder max-temp guard.

New optional slicer params: MATERIAL (LCD display), TOTAL_LAYER
(Mainsail progress UI), Z_ADJUST (per-filament baby-step; mostly
unnecessary with Eddy tap).

PRINT_END gains a small retract, 10mm lift (vs 5), and rear-left park.
Cleanup tail factored into _PRINT_END_CLEANUP.

PRINT_WARMUP removed — duplicated PRINT_START init; never called by
slicer. Prewarming pre-print is `M140 S110` + `M104 S150` from console
or `HEATSOAK` macro.

_USER_VARIABLE: drop chamber_wait_bed_threshold (bed-temp proxy
replaced by CHAMBER>0 branch), add bed_stabilization_soak_seconds.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Wire `_CLIENT_VARIABLE` into `config/mainsail.cfg`

**Files:**
- Modify: `config/mainsail.cfg`

Today's repo references `_CLIENT_VARIABLE` via `printer['gcode_macro _CLIENT_VARIABLE']|default({})` (graceful absence). Defining it activates the upstream `user_cancel_macro` hook so `CANCEL_PRINT` mid-print runs our cleanup.

- [ ] **Step 1: Add `_CLIENT_VARIABLE` macro**

Open `config/mainsail.cfg`. Find the block:

```
##### PAUSE / RESUME / CANCEL_PRINT / SET_PAUSE_* / SET_PRINT_STATS_INFO #####
# DELEGATED to upstream mainsail-crew/mainsail-config. Pi has a symlink to
# ~/mainsail-config/client.cfg; the upstream definitions are what actually
# run. Do NOT add overrides here unless you also coordinate breaking the
# Pi-side symlink (see memory/decisions.md, 2026-05-16 "Mainsail config slim").
```

Append (after that comment block, before any subsequent section) a new section:

```ini

##### _CLIENT_VARIABLE — hooks consumed by upstream client.cfg #####
# Upstream Mainsail client.cfg looks up these variables via
# `printer['gcode_macro _CLIENT_VARIABLE']|default({})` and calls
# user_cancel_macro / user_pause_macro / user_resume_macro at the right
# moments. Without _CLIENT_VARIABLE defined, the hooks default to empty
# strings — cancel-mid-print runs only upstream's bare retract+park+
# heaters-off, NOT our cooldown / OFF / _RESETSPEEDS.
#
# Wiring user_cancel_macro to _PRINT_END_CLEANUP gives cancel the same
# cleanup tail as a normal PRINT_END. See spec 2026-05-18 §5.
#
# Other variables (use_custom_pos, custom_park_x, etc.) are left unset
# — upstream defaults park at the bed's max-edge corners, which is the
# right behavior for this build.

[gcode_macro _CLIENT_VARIABLE]
description: Holds variables consumed by the upstream Mainsail client.cfg hooks. user_cancel_macro is the load-bearing one.
variable_user_cancel_macro: "_PRINT_END_CLEANUP"
gcode:
  # Variables-only macro; no body. Same pattern as _USER_VARIABLE.
```

- [ ] **Step 2: Run `make test-py`**

```bash
make test-py
```

Expected: all 91 tests pass + pre-commit clean. `test_every_owned_macro_has_description` covers the new description.

- [ ] **Step 3: Commit**

```bash
git add config/mainsail.cfg
git commit -m "$(cat <<'EOF'
feat(macros): wire _CLIENT_VARIABLE.user_cancel_macro to _PRINT_END_CLEANUP

Closes the cancel-mid-print cleanup gap. Today upstream Mainsail
CANCEL_PRINT calls client.user_cancel_macro|default("") — since we
don't define _CLIENT_VARIABLE, the hook default is empty and cancel
runs only upstream's retract+park+heaters-off. Fans, lights, steppers,
and _RESETSPEEDS were skipped.

Defining _CLIENT_VARIABLE with user_cancel_macro: "_PRINT_END_CLEANUP"
routes cancel into the same cleanup tail as PRINT_END.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Create OrcaSlicer template — `docs/slicer-templates/orcaslicer.md`

**Files:**
- Create: `docs/slicer-templates/orcaslicer.md`

- [ ] **Step 1: Confirm parent dir exists or create it**

```bash
mkdir -p docs/slicer-templates
ls docs/slicer-templates/
```

If `orcaslicer.md` is already there from a prior change, abort — investigate before overwriting.

- [ ] **Step 2: Create `docs/slicer-templates/orcaslicer.md`**

Write the file with this exact content:

````markdown
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
````

- [ ] **Step 3: Commit**

```bash
git add docs/slicer-templates/orcaslicer.md
git commit -m "$(cat <<'EOF'
docs(slicer): OrcaSlicer hookup template — PRINT_START/END contract

New doc at docs/slicer-templates/orcaslicer.md documenting the
contract: what params PRINT_START expects, what the Machine start/end
G-code blocks should look like in OrcaSlicer, per-filament
chamber_temperature recommendations, Z_ADJUST application paths, and
known failure-mode error strings.

Companion to spec 2026-05-18 (print lifecycle redesign).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Update CLAUDE.md macro inventory

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Find the print_start macro inventory entry**

```bash
grep -n "print_start.cfg\|PRINT_WARMUP\|PRINT_START\|PRINT_END\|chamber_wait_bed_threshold" CLAUDE.md
```

Look for the existing `### config/macros/print_start.cfg` block under `## Macro inventory`.

- [ ] **Step 2: Update the entry**

Find this block:

```markdown
### `config/macros/print_start.cfg` — print sequence (jontek2 pattern)
- `PRINT_WARMUP` — pre-heat without printing (caselight on, BED_MESH_CLEAR, home, QGL, start bed+ext heating)
- `PRINT_START` — full start: tap_threshold guard → home → QGL → bed heat + chamber wait (if bed > 90 °C) → `BLOBIFIER_CLEAN` → re-home Z (auto-applies tap via `[homing_override]`) → adaptive bed mesh → heat hotend
- `PRINT_END` — cool, clear mesh, wait 60 s, `OFF`, `_RESETSPEEDS`
```

Replace with:

```markdown
### `config/macros/print_start.cfg` — print lifecycle (heat-overlap, post-2026-05-18 redesign)
- `PRINT_START` — full start: tap_threshold guard → param validation → CLEAR_PAUSE + UI hints → bed + hotend partial heat NON-BLOCKING → home + QGL (cold, in parallel with heat) → wait for bed + hotend partial → chamber soak branch (CHAMBER>0 from slicer) → tap-Z → optional Z_ADJUST → adaptive bed mesh → final M109 → hot-nozzle BLOBIFIER_CLEAN. Spec: `docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`.
- `PRINT_END` — flush buffer, retract 2mm, lift 10mm, park rear-left, heaters off, then `_PRINT_END_CLEANUP`.
- `_PRINT_END_CLEANUP` — shared cleanup tail (BED_MESH_CLEAR, G4 cooldown, OFF, _RESETSPEEDS). Called by both `PRINT_END` and the upstream `CANCEL_PRINT` via `_CLIENT_VARIABLE.user_cancel_macro`.
- (removed 2026-05-18) `PRINT_WARMUP` — was a separate manual prewarm macro; never called by slicer. Prewarming pre-print is now direct gcode (`M140 S110` + `M104 S150`) or `HEATSOAK`.

Slicer-side contract: `docs/slicer-templates/orcaslicer.md`.
```

- [ ] **Step 3: Find and update the `config/mainsail.cfg` macro entry**

```bash
grep -n "mainsail.cfg\|_CLIENT_VARIABLE" CLAUDE.md | head -10
```

Find the existing `### config/mainsail.cfg` block under `## Macro inventory`.

Replace it with the version below (adds `_CLIENT_VARIABLE` to the macro list):

```markdown
### `config/mainsail.cfg` — Mainsail client.cfg (symlink target on Pi)
- `[gcode_macro PAUSE]` / `RESUME` / `CANCEL_PRINT` / `_CLIENT_*` — standard Mainsail pause/cancel with park behavior. **Note: defined upstream in `~/mainsail-config/client.cfg`** (Pi-side symlink); do not override locally.
- `_CLIENT_VARIABLE` — holds hook variables consumed by upstream `client.cfg`. `user_cancel_macro: "_PRINT_END_CLEANUP"` routes cancel-mid-print into our cleanup tail. Defined locally (2026-05-18).
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude-md): macro inventory — print lifecycle redesign

Reflect the 2026-05-18 print lifecycle redesign:
- PRINT_START's new flow (heat-overlap, chamber-driven soak, hot wipe)
- PRINT_END's new park + retract + lift
- _PRINT_END_CLEANUP added as shared cleanup tail
- PRINT_WARMUP removed
- _CLIENT_VARIABLE now defined locally (wires user_cancel_macro to
  _PRINT_END_CLEANUP)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Final integration verification

**Files:** none modified (verification only).

- [ ] **Step 1: Full local test pyramid**

```bash
make test-py
```

Expected: all 91 tests pass + pre-commit clean. If anything fails here that wasn't failing after Tasks 1-2, something downstream broke (likely a CLAUDE.md edit introducing a markdown lint trip).

- [ ] **Step 2: Sanity-grep for stale references**

```bash
grep -rn "PRINT_WARMUP\|chamber_wait_bed_threshold" config/ CLAUDE.md
```

Expected: empty output. If anything matches in `config/` or `CLAUDE.md`, it's a missed reference — fix and re-commit.

```bash
grep -rn "_PRINT_END_CLEANUP" config/
```

Expected: exactly THREE occurrences — the definition in `print_start.cfg`, the call from `PRINT_END` in `print_start.cfg`, and the `user_cancel_macro: "_PRINT_END_CLEANUP"` in `mainsail.cfg`.

```bash
grep -rn "_CLIENT_VARIABLE" config/
```

Expected: the definition in `mainsail.cfg` + the existing references in `mainsail.cfg`'s pause/resume helpers (those already use `printer['gcode_macro _CLIENT_VARIABLE']|default({})`). No new references introduced by this PR.

---

### Task 6: Push, open PR, watch CI

**Files:** none modified.

- [ ] **Step 1: Pre-push commit list**

```bash
git log --oneline origin/main..HEAD
```

Expected: 4 commits (Task 1, 2, 3, 4) referencing the spec.

- [ ] **Step 2: pr-review-toolkit before push**

Per [[feedback_pr_review_toolkit]]:

```bash
# In the Claude session:
Skill: pr-review-toolkit:review-pr
```

Address any Critical/Important findings as fixup commits before pushing.

- [ ] **Step 3: Push + open PR**

```bash
git push -u origin HEAD:feat/print-lifecycle
gh pr create --base main --head feat/print-lifecycle \
  --title "feat(macros): redesign PRINT_START/END lifecycle + CANCEL_PRINT hook" \
  --body "$(cat <<'EOF'
## Summary

Closes the issues found in spec [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md):

- **PRINT_START** — heat overlap (bed + hotend partial start non-blocking during home + QGL), partial M109 S150 before tap-Z for accurate Z reference, slicer-driven chamber soak (`CHAMBER>0` from filament profile, not `bed>90` proxy), hot-nozzle `BLOBIFIER_CLEAN`, `CLEAR_PAUSE` upfront, bed/extruder max-temp guard.
- **PRINT_END** — small retract, 10mm lift, rear-left park, factored cleanup.
- **CANCEL_PRINT** — wired via `_CLIENT_VARIABLE.user_cancel_macro` into the same `_PRINT_END_CLEANUP` tail. Was a real gap: cancel-mid-print previously skipped cooldown / fans-off / lights-off / `_RESETSPEEDS`.
- **PRINT_WARMUP** removed (duplicated PRINT_START init; never called by slicer).
- **New PRINT_START params:** `MATERIAL`, `TOTAL_LAYER`, `Z_ADJUST`.
- **`docs/slicer-templates/orcaslicer.md`** documents the slicer-side contract — pairs with [#29](https://github.com/bjdeng/voron-2-611/issues/29) (per-filament profile tuning is the at-the-printer half).

## Test plan

- [x] `make test-py` — 91/91 pass, pre-commit clean.
- [ ] CI green (L1/L2/L4/L5 + L3 klippy parse).
- [ ] Post-merge: `/deploy-to-pi` + manual short PLA test print (CHAMBER=0 path).
- [ ] Post-merge: short ABS test print if available (CHAMBER=30 path).
- [ ] Post-merge: mid-print `CANCEL_PRINT` — verify `_PRINT_END_CLEANUP` runs (caselight off, fans off, _RESETSPEEDS).

## Slicer-side TODO (outside this PR)

Update OrcaSlicer Machine start G-code per `docs/slicer-templates/orcaslicer.md`. Per-filament `chamber_temperature` values are also documented there. Bigger profile-tuning work tracked at [#29](https://github.com/bjdeng/voron-2-611/issues/29).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI**

```bash
gh pr checks --watch
```

Expected: all green. L3 (klippy parse) is the load-bearing structural gate.

- [ ] **Step 5: Squash-merge once green + approved**

```bash
gh pr merge --squash --delete-branch
```

---

### Task 7: Post-merge — deploy + manual print test

**Files:** none modified.

- [ ] **Step 1: Switch to main, pull, clean up worktree**

```bash
cd /Users/ben/code/voron-2-611    # main checkout
git pull --ff-only origin main
# Exit worktree via ExitWorktree(action=remove) — see [[feedback_cleanup_worktrees]].
```

- [ ] **Step 2: Deploy to Pi with smoke**

```bash
scripts/deploy_to_pi.sh --yes --smoke
```

Expected: deploy completes; smoke runs (G28, PARKCENTER, OFF, _RESETSPEEDS — all accepted); no new `!!` errors in klippy.log.

- [ ] **Step 3: Manual short print test**

Slicer-side update (one-time):
1. OrcaSlicer → Printer settings → Machine G-code → Machine start G-code: paste the block from `docs/slicer-templates/orcaslicer.md`.
2. Machine end G-code: `PRINT_END`.
3. Per-filament: set `chamber_temperature` per the table in the slicer template doc.

Then queue a short test print (a small PLA part — chamber=0 path) and watch:
- `M117` line in Mainsail console matches `Print: PLA bed=60 hotend=210 chamber=0` (or whatever).
- `SET_PRINT_STATS_INFO TOTAL_LAYER=N` fires (progress bar updates).
- Bed heat + home + QGL overlap (gantry moves while bed is mid-heat).
- Mesh runs, hotend reaches final temp, BLOBIFIER_CLEAN wipes nozzle hot.
- Print starts.

If anything is off, file as a follow-up — don't roll back the macro change unless something genuinely breaks.

- [ ] **Step 4: Mid-print CANCEL_PRINT test (optional)**

During a test print, click Cancel in Mainsail. Verify:
- Toolhead retracts + parks (upstream behavior).
- Heaters turn off (upstream behavior).
- Cooldown delay then OFF runs (our hook): caselight goes off, bed fans go off, steppers disengage.

If `_PRINT_END_CLEANUP` doesn't fire, the `_CLIENT_VARIABLE` definition didn't take effect — check `printer['gcode_macro _CLIENT_VARIABLE'].user_cancel_macro` in the Mainsail console.

---

## References

- Spec: [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](../specs/2026-05-18-print-lifecycle-redesign.md)
- Related issue: [#29](https://github.com/bjdeng/voron-2-611/issues/29) — OrcaSlicer per-filament profile tuning (the at-the-printer half)
- Upstream Mainsail client.cfg hooks: <https://github.com/mainsail-crew/mainsail-config/blob/master/client.cfg>
- jontek2 reference: <https://github.com/jontek2/A-better-print_start-macro>

## Self-review notes

- **Spec coverage:** Every spec section maps. §3 (PRINT_START) → Task 1. §4 (PRINT_END) → Task 1. §5 (`_CLIENT_VARIABLE` + `_PRINT_END_CLEANUP`) → Tasks 1+2. §6 (`_USER_VARIABLE` changes) → Task 1. §7 (slicer template) → Task 3. §8 (failure modes) → enforced by Task 1's PRINT_START body. §9 (MMU/Spoolman deferred) → not a task by design. §10 (testing strategy) → Task 5. §11 (anti-criteria) → enforced by what the tasks do NOT touch.
- **Placeholder scan:** No TBDs, TODOs, or "add appropriate X" — every step has exact code or an exact command + expected outcome.
- **Type consistency:** Variable name `bed_stabilization_soak_seconds` is consistent between `_user_variables.cfg` definition (Task 1) and PRINT_START's reference (Task 1). `_PRINT_END_CLEANUP` name is consistent across `print_start.cfg` definition + call (Task 1) and `mainsail.cfg`'s `user_cancel_macro` string (Task 2).
