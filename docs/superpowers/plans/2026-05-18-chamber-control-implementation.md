# Chamber Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bed-target-driven BedFans automation with a continuous chamber control loop that owns both BedFans and `temperature_fan chamber`, driven by a single setpoint set via `SET_CHAMBER_TARGET TARGET=<°C>`.

**Architecture:** New `config/macros/chamber_control.cfg` adds a `_CHAMBER_CONTROL` state holder, a `SET_CHAMBER_TARGET` setter, and a `chamber_control_loop` delayed_gcode that ticks every 5s. The loop reads chamber temp + bed temp + print state and writes BedFans speed + chamber fan target across five states: HEAT, COOL, MAINTAIN, VOC BASELINE, OFF. PRINT_START, PRINT_END, and `_CANCEL_PRINT_HOOK` call `SET_CHAMBER_TARGET`; the old per-call bedfan ramps in `bedfans.cfg` (M190/SET_HEATER_TEMPERATURE/bedfanloop overrides) are stripped. `[temperature_fan chamber].max_temp` drops 70→60 to match the operator safety cap.

**Tech Stack:** Klipper jinja2 gcode_macros + delayed_gcode. Test layers L1 (pre-commit), L2 (macro_refcheck), L3 (CI klippy parse), L5 (config structure pytest), L6 (post-deploy smoke + manual material tests).

**Reference spec:** [`docs/superpowers/specs/2026-05-18-chamber-control-design.md`](../specs/2026-05-18-chamber-control-design.md)

---

## File map

**Create:**
- `config/macros/chamber_control.cfg` — `_CHAMBER_CONTROL` state holder, `SET_CHAMBER_TARGET` setter, `chamber_control_loop` delayed_gcode.

**Modify:**
- `config/printer.cfg` — add `[include macros/chamber_control.cfg]` after the bedfans include (line 52 area).
- `config/macros/_user_variables.cfg` — add 5 chamber-control keys; remove 3 obsolete bedfans keys.
- `config/macros/bedfans.cfg` — strip M190 bedfan branches (keep TEMPERATURE_WAIT tolerance), strip SET_HEATER_TEMPERATURE bedfan branches (keep M104/M99140 routing), remove `[delayed_gcode bedfanloop]`, remove the `TURN_OFF_HEATERS` override entirely (its only purpose was BEDFANSOFF). Keep `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` aliases as manual console commands. Keep the M140 override (still an alias to SET_HEATER_TEMPERATURE, useful for slicer compatibility).
- `config/macros/print_start.cfg` — add chamber-loop bootstrap after `CASELIGHT_ON` (step 4); replace inline chamber soak (step 9) with `SET_CHAMBER_TARGET TARGET={chamber}`; add `SET_CHAMBER_TARGET TARGET=0` to PRINT_END.
- `config/client_hooks.cfg` — add `SET_CHAMBER_TARGET TARGET=0` to top of `_CANCEL_PRINT_HOOK`.
- `config/bed.cfg` — `[temperature_fan chamber].max_temp` 70 → 60.
- `CLAUDE.md` — add `chamber_control.cfg` block under "Macro inventory"; cross-link from `bedfans.cfg` entry; note in "Recently resolved".

**No-op (spec already satisfied):**
- `config/macros/macros.cfg` — `OFF` macro already has `SET_FAN_SPEED FAN=BedFans SPEED=0` at line 51. Spec §3.4 calls this out as "add"; verify and skip.

---

## Pre-flight

### Task 0: Create isolated worktree

- [ ] **Step 1: Create the worktree via `superpowers:using-git-worktrees`**

The skill creates a worktree under `.worktrees/<branch>/` and switches into it.

Branch name: `feat/chamber-control`

- [ ] **Step 2: Verify location**

```bash
pwd
git branch --show-current
```

Expected: cwd inside `.worktrees/feat-chamber-control/` (or equivalent), branch `feat/chamber-control`.

- [ ] **Step 3: Confirm test pyramid runs cleanly on `main` before any edits**

```bash
make test-py
```

Expected: all green. Establishes baseline so any later failure is attributable to a specific task.

---

## Implementation

### Task 1: ~~Add new `_USER_VARIABLE` keys~~ — DROPPED during execution

**Status:** Removed. The original plan added all 5 chamber-control vars in a standalone commit, but `tests/test_config_structure.py::test_user_variable_definitions_used` rejects orphan definitions. Restructured so each var lands in the same commit as its first consumer:

- `chamber_max_target` → Task 2 commit (consumed by `SET_CHAMBER_TARGET`'s clamp).
- `chamber_target_band`, `chamber_voc_baseline`, `chamber_heat_speed`, `voc_cooldown_threshold` → Task 3 commit (consumed by `chamber_control_loop`'s body).

No work in this task.

---

### Task 2: Create `chamber_control.cfg` with state holder + setter

**Files:**
- Create: `config/macros/chamber_control.cfg`
- Modify: `config/macros/_user_variables.cfg` (add `chamber_max_target` only — the SET_CHAMBER_TARGET clamp's only `_USER_VARIABLE` read)
- Modify: `config/printer.cfg` (add `[include]`)

Loop body comes in Task 3; this task lands the state macro, the entry-point setter, the include wiring, and the single var the setter reads. After this task, `SET_CHAMBER_TARGET` is callable from the Mainsail console and updates `variable_target` — but no consumer reads `target` yet, so behavior is unchanged.

- [ ] **Step 1: Add `chamber_max_target` to `_USER_VARIABLE`**

Edit `config/macros/_user_variables.cfg`. Insert a new section after the `variable_bedfans_slow: 0.2` line (line 33), before the `# HEATSOAK defaults` comment:

```
# Chamber control (chamber_control.cfg owns BedFans + temperature_fan chamber)
variable_chamber_max_target: 60          # SET_CHAMBER_TARGET clamps to this
```

The remaining 4 chamber vars land in Task 3 with the loop body that consumes them.

- [ ] **Step 2: Create `config/macros/chamber_control.cfg` with state holder + setter**

```
#####################################################################
#   Chamber control — single owner of BedFans + temperature_fan chamber
#
#   Spec: docs/superpowers/specs/2026-05-18-chamber-control-design.md
#
#   _CHAMBER_CONTROL holds the live setpoint + tuning knobs.
#   SET_CHAMBER_TARGET is the only entry point that mutates the setpoint
#   (PRINT_START, PRINT_END, _CANCEL_PRINT_HOOK, or manual console).
#   chamber_control_loop ticks every 5s and writes fan state based on
#   {target, chamber temp, bed temp, print state}.
#####################################################################

[gcode_macro _CHAMBER_CONTROL]
description: State holder for chamber control. variable_target is the live setpoint; the loop reads it each tick. Static knobs live in _USER_VARIABLE.
variable_target: 0
gcode:
  # Variables-only macro; no body. Same pattern as _USER_VARIABLE.


[gcode_macro SET_CHAMBER_TARGET]
description: Set the chamber temperature setpoint. TARGET=0 disables active control (loop runs only for VOC baseline / cooldown). Clamped to [0, chamber_max_target].
gcode:
  {% set req = params.TARGET|default(0)|float %}
  {% set cap = printer["gcode_macro _USER_VARIABLE"].chamber_max_target|float %}
  {% if req < 0 %}
    {% set target = 0 %}
  {% elif req > cap %}
    {% set target = cap %}
    M117 chamber target {req|int} clamped to {cap|int}
    RESPOND TYPE=echo MSG="SET_CHAMBER_TARGET: requested {req|int} exceeds chamber_max_target ({cap|int}); clamped."
  {% else %}
    {% set target = req %}
  {% endif %}
  SET_GCODE_VARIABLE MACRO=_CHAMBER_CONTROL VARIABLE=target VALUE={target}
  UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1
```

- [ ] **Step 3: Wire the include**

Edit `config/printer.cfg`. Find line 52:

```
[include macros/bedfans.cfg]
```

Insert immediately after:

```
[include macros/chamber_control.cfg]
```

Resulting macro-include block (line 49 onward):

```
[include macros/macros.cfg]
[include macros/test_speed.cfg]
[include macros/lcd_tweaks.cfg]
[include macros/bedfans.cfg]
[include macros/chamber_control.cfg]
[include macros/print_start.cfg]
[include macros/calibrate_flow.cfg]
[include macros/calibrate_pa.cfg]
```

- [ ] **Step 4: Run pre-commit + tests**

```bash
pre-commit run --files config/macros/_user_variables.cfg config/macros/chamber_control.cfg config/printer.cfg
make test-py
```

Expected: all green. `chamber_max_target` now has a consumer (the setter) so the orphan check passes.

Note: `chamber_control_loop` is not yet defined; `UPDATE_DELAYED_GCODE ID=chamber_control_loop` is unresolved at runtime (Klipper logs a warning but doesn't fail). `macro_refcheck.py` only resolves invoked **macros**, not delayed_gcode IDs, so L2 doesn't fail. L3 (CI klippy parse) tolerates the unresolved ID as well (it's checked at runtime, not parse). Loop definition lands in Task 3 — keep the gap small.

- [ ] **Step 5: Commit**

```bash
git add config/macros/_user_variables.cfg config/macros/chamber_control.cfg config/printer.cfg
git commit -m "feat(chamber): add _CHAMBER_CONTROL state + SET_CHAMBER_TARGET setter"
```

---

### Task 3: Add `chamber_control_loop` delayed_gcode

**Files:**
- Modify: `config/macros/chamber_control.cfg` (append the delayed_gcode block)
- Modify: `config/macros/_user_variables.cfg` (add the 4 remaining chamber vars consumed by the loop)

State machine: HEAT / COOL / MAINTAIN / VOC BASELINE / OFF (per spec §3.3). Loop re-arms in every state except OFF; the setter bootstraps it on `target` changes; PRINT_START's `UPDATE_DELAYED_GCODE` (Task 5) bootstraps it for VOC baseline on cold-material prints.

- [ ] **Step 1: Add the 4 remaining vars to `_user_variables.cfg`**

Edit `config/macros/_user_variables.cfg`. Extend the "Chamber control" section added in Task 2 by adding 4 lines immediately after `variable_chamber_max_target: 60`:

```
variable_chamber_target_band: 2          # hysteresis ±°C around setpoint
variable_chamber_voc_baseline: 0.1       # bedfan speed for VOC baseline + cooldown
variable_chamber_heat_speed: 1.0         # bedfan speed in active heat mode
variable_voc_cooldown_threshold: 40      # bed temp °C below which VOC baseline turns off
```

Resulting "Chamber control" block (5 vars in this order):

```
# Chamber control (chamber_control.cfg owns BedFans + temperature_fan chamber)
variable_chamber_max_target: 60          # SET_CHAMBER_TARGET clamps to this
variable_chamber_target_band: 2          # hysteresis ±°C around setpoint
variable_chamber_voc_baseline: 0.1       # bedfan speed for VOC baseline + cooldown
variable_chamber_heat_speed: 1.0         # bedfan speed in active heat mode
variable_voc_cooldown_threshold: 40      # bed temp °C below which VOC baseline turns off
```

- [ ] **Step 2: Append the loop block to `chamber_control.cfg`**

Add at the bottom of `config/macros/chamber_control.cfg`:

```
[delayed_gcode chamber_control_loop]
gcode:
  {% set target           = printer["gcode_macro _CHAMBER_CONTROL"].target|float %}
  {% set band             = printer["gcode_macro _USER_VARIABLE"].chamber_target_band|float %}
  {% set baseline_speed   = printer["gcode_macro _USER_VARIABLE"].chamber_voc_baseline|float %}
  {% set heat_speed       = printer["gcode_macro _USER_VARIABLE"].chamber_heat_speed|float %}
  {% set voc_cooldown_bed = printer["gcode_macro _USER_VARIABLE"].voc_cooldown_threshold|float %}
  {% set chamber_temp     = printer["temperature_fan chamber"].temperature|float %}
  {% set bed_temp         = printer.heater_bed.temperature|float %}
  {% set state            = printer.print_stats.state|string %}
  {% set print_active     = state in ("printing", "paused") %}

  {% if target > 0 %}
    {# Active control: HEAT / COOL / MAINTAIN #}
    {% if chamber_temp < target - band %}
      SET_FAN_SPEED FAN=BedFans SPEED={heat_speed}
      SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET=0
    {% elif chamber_temp > target + band %}
      SET_FAN_SPEED FAN=BedFans SPEED={baseline_speed}
      SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET={target}
    {% else %}
      SET_FAN_SPEED FAN=BedFans SPEED={baseline_speed}
      SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET={target}
    {% endif %}
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=5
  {% elif print_active or bed_temp >= voc_cooldown_bed %}
    {# VOC baseline: filtration during prints + cooldown #}
    SET_FAN_SPEED FAN=BedFans SPEED={baseline_speed}
    SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET=0
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=5
  {% else %}
    {# OFF: idle + bed cold #}
    SET_FAN_SPEED FAN=BedFans SPEED=0
    SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET=0
  {% endif %}
```

Two notes on the body:

1. The COOL and MAINTAIN branches set the same fan state — kept as separate `elif`/`else` for spec parity and so future tuning (e.g., bumping exhaust hard during COOL) doesn't have to refactor the branch structure. Three-way bang-bang is the spec's intent.
2. `printer["temperature_fan chamber"].temperature` is the canonical accessor for `temperature_fan` sensor readings (confirmed against `vendor/klipper/klippy/extras/temperature_fan.py:get_status`).

- [ ] **Step 3: Pre-commit + tests**

```bash
pre-commit run --files config/macros/_user_variables.cfg config/macros/chamber_control.cfg
make test-py
```

Expected: all green. L2 verifies `SET_FAN_SPEED`, `SET_TEMPERATURE_FAN_TARGET`, `UPDATE_DELAYED_GCODE` resolve (all in `tests/builtins.txt`). The 4 new vars now have a consumer (the loop) so the orphan check passes.

- [ ] **Step 4: Commit**

```bash
git add config/macros/_user_variables.cfg config/macros/chamber_control.cfg
git commit -m "feat(chamber): add chamber_control_loop state machine"
```

---

### Task 4: Wire PRINT_END + `_CANCEL_PRINT_HOOK` to clear the target

**Files:**
- Modify: `config/macros/print_start.cfg`
- Modify: `config/client_hooks.cfg`

PRINT_END and cancel must release active control so the loop drops into VOC-baseline / OFF as the bed cools. Done before PRINT_START changes so both end paths are safe before we start arming the loop in normal flow.

- [ ] **Step 1: Add `SET_CHAMBER_TARGET TARGET=0` to PRINT_END**

Edit `config/macros/print_start.cfg`. Find PRINT_END body (line 116):

```
gcode:
  M400                                                   # flush move buffer
```

Insert one line immediately before `M400`:

```
gcode:
  SET_CHAMBER_TARGET TARGET=0                            # release active control; loop continues VOC baseline until bed cools
  M400                                                   # flush move buffer
```

- [ ] **Step 2: Add `SET_CHAMBER_TARGET TARGET=0` to `_CANCEL_PRINT_HOOK`**

Edit `config/client_hooks.cfg`. Find the body of `_CANCEL_PRINT_HOOK` (line 47):

```
gcode:
  # MMU_END is Happy-Hare's canonical end-of-print hook. UNLOAD=1 forces
  # filament unload from the toolhead. The macro internally checks
  # printer.mmu.enabled, so it's safe to call unconditionally — non-MMU
  # builds will no-op.
  MMU_END UNLOAD=1
  _PRINT_END_CLEANUP
```

Insert one line as the first statement (before the comment block is fine; or directly before `MMU_END UNLOAD=1`). Keep the existing MMU comment intact. Final:

```
gcode:
  SET_CHAMBER_TARGET TARGET=0
  # MMU_END is Happy-Hare's canonical end-of-print hook. UNLOAD=1 forces
  # filament unload from the toolhead. The macro internally checks
  # printer.mmu.enabled, so it's safe to call unconditionally — non-MMU
  # builds will no-op.
  MMU_END UNLOAD=1
  _PRINT_END_CLEANUP
```

- [ ] **Step 3: Pre-commit + tests**

```bash
pre-commit run --files config/macros/print_start.cfg config/client_hooks.cfg
make test-py
```

Expected: all green. L2 confirms `SET_CHAMBER_TARGET` resolves (defined in Task 2).

- [ ] **Step 4: Commit**

```bash
git add config/macros/print_start.cfg config/client_hooks.cfg
git commit -m "feat(chamber): release chamber target on PRINT_END and CANCEL_PRINT"
```

---

### Task 5: Wire PRINT_START — bootstrap loop + replace inline chamber soak

**Files:**
- Modify: `config/macros/print_start.cfg`

Two edits in this file:

1. Bootstrap `chamber_control_loop` near step 4 so VOC baseline runs from the moment a print starts.
2. Replace the inline chamber-soak block in step 9 with a `SET_CHAMBER_TARGET` call. The existing `M106 S255` was a PT-fan workaround for "stir the chamber"; replacement is the chamber loop driving BedFans. **Keep `PARKCENTER` + `TEMPERATURE_WAIT` + `M107` (defensive)** — `PARKCENTER` parks the nozzle off the print zone; `TEMPERATURE_WAIT` blocks until the chamber reaches target; `M107` is removed because no `M106 S255` precedes it now.

- [ ] **Step 1: Add bootstrap line after `CASELIGHT_ON` (step 4)**

Find line 43:

```
  CLEAR_PAUSE
  _RESETSPEEDS
  BED_MESH_CLEAR
  CASELIGHT_ON
```

Insert immediately after `CASELIGHT_ON`:

```
  UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1    # bootstrap chamber control (VOC baseline until SET_CHAMBER_TARGET runs)
```

Resulting block:

```
  CLEAR_PAUSE
  _RESETSPEEDS
  BED_MESH_CLEAR
  CASELIGHT_ON
  UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1    # bootstrap chamber control (VOC baseline until SET_CHAMBER_TARGET runs)
```

- [ ] **Step 2: Replace inline chamber soak (step 9)**

Find lines 76–90 (the `# 9. Chamber soak branch …` block). Replace the entire `{% if chamber > 0 %} … {% endif %}` body so the spec's redesign §3.4 lands cleanly.

Before:

```
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
    M107                                                 # PT-fan off BEFORE probing — toolhead vibration from M106 S255 corrupts tap-Z and rapid_scan mesh
  {% elif soak_s > 0 %}
    G4 P{(soak_s * 1000)|int}
  {% endif %}
```

After:

```
  # 9. Chamber soak branch (slicer-driven, per-material).
  #    Hot materials (ABS/ASA/PA-CF): slicer passes CHAMBER=30 — chamber
  #    will continue heating to 50-55°C from bed + part radiation during
  #    the print itself; waiting for full target wastes time.
  #    Cold materials (PLA/PETG/TPU): slicer passes CHAMBER=0 — we run
  #    a brief bed-mass equilibration soak instead.
  #    Active heat now comes from the chamber control loop driving BedFans
  #    (see config/macros/chamber_control.cfg) — no more M106 S255 PT-fan
  #    workaround.
  {% set soak_s = printer["gcode_macro _USER_VARIABLE"].bed_stabilization_soak_seconds|int %}
  {% if chamber > 0 %}
    SET_CHAMBER_TARGET TARGET={chamber}                  # active heat via BedFans; loop will drive PID exhaust if chamber overshoots
    PARKCENTER                                           # nozzle off the print zone during soak
    TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={chamber}
  {% elif soak_s > 0 %}
    G4 P{(soak_s * 1000)|int}
  {% endif %}
```

- [ ] **Step 3: Pre-commit + tests**

```bash
pre-commit run --files config/macros/print_start.cfg
make test-py
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add config/macros/print_start.cfg
git commit -m "feat(chamber): wire PRINT_START to chamber control loop"
```

---

### Task 6: Strip automatic-write paths from `bedfans.cfg`

**Files:**
- Modify: `config/macros/bedfans.cfg`

After this task, the chamber control loop is the **sole automatic writer** of BedFans state. The `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` aliases stay as manual console commands (no automatic callers).

Specifically:
- Remove the bedfans branches from the `SET_HEATER_TEMPERATURE` override (lines 51–60). Keep the M104/M99140 heater routing (it has independent value — slicer M140 still works).
- Remove the bedfans branches from the `M190` override (the `if S >= THRESHOLD` blocks at lines 74–78 and 89–91). Keep the TEMPERATURE_WAIT tolerance-band block.
- Remove `[delayed_gcode bedfanloop]` (lines 111–124) entirely.
- Remove the `TURN_OFF_HEATERS` override (lines 103–109) entirely — its only purpose was the `BEDFANSOFF` call; stripping it would leave a no-op pass-through wrapper. Without the override, stock TURN_OFF_HEATERS runs directly. The `OFF` macro already calls `SET_FAN_SPEED FAN=BedFans SPEED=0` (`macros.cfg:51`) so end-of-print cleanup is still safe.

- [ ] **Step 1: Rewrite the `SET_HEATER_TEMPERATURE` override body**

Before (lines 33–60):

```
[gcode_macro SET_HEATER_TEMPERATURE]
description: Override of stock SET_HEATER_TEMPERATURE — integrates bed-fan logic.
rename_existing: _SET_HEATER_TEMPERATURE
gcode:
	# Parameters
	{% set HEATER = params.HEATER|default("None") %}
	{% set TARGET = params.TARGET|default(0)|int %}
	# Vars
	{% set THRESHOLD = printer["gcode_macro _USER_VARIABLE"].bedfans_threshold|int %}

	{% if HEATER|lower == "extruder" %}
		M104 S{TARGET}
	{% elif HEATER|lower == "heater_bed" %}
		M99140 S{TARGET}
	{% else %}
		{action_respond_info("Heater %s not supported" % HEATER)}
	{% endif %}

	# Set fans to low if heater_bed temp is requested above threshold temp, and kick off monitoring loop.
	{% if HEATER|lower == "heater_bed" %}
		{% if TARGET >= THRESHOLD %}
			BEDFANSSLOW
			UPDATE_DELAYED_GCODE ID=bedfanloop DURATION=1
		{% else %}
			BEDFANSOFF
			UPDATE_DELAYED_GCODE ID=bedfanloop DURATION=0 #	Cancel bed fan loop if it's running
		{% endif %}
	{% endif %}
```

After:

```
[gcode_macro SET_HEATER_TEMPERATURE]
description: Override of stock SET_HEATER_TEMPERATURE — routes heater_bed via M99140 so the M140 alias and Mainsail's set-bed-temp button both route the same way.
rename_existing: _SET_HEATER_TEMPERATURE
gcode:
	# Parameters
	{% set HEATER = params.HEATER|default("None") %}
	{% set TARGET = params.TARGET|default(0)|int %}

	{% if HEATER|lower == "extruder" %}
		M104 S{TARGET}
	{% elif HEATER|lower == "heater_bed" %}
		M99140 S{TARGET}
	{% else %}
		{action_respond_info("Heater %s not supported" % HEATER)}
	{% endif %}
```

- [ ] **Step 2: Rewrite the `M190` override body**

Before (lines 62–91):

```
# Override M190 (Wait for Bed Temperature)
# As a bonus, use TEMPERATURE_WAIT so we don't have to wait for PID to level off.
[gcode_macro M190]
description: Override of stock M190 — uses TEMPERATURE_WAIT and triggers bed fans.
rename_existing: M99190
gcode:
	# Parameters
	{% set S = params.S|int %}
	# Vars
	{% set THRESHOLD = printer["gcode_macro _USER_VARIABLE"].bedfans_threshold|int %}
	{% set TOL = printer["gcode_macro _USER_VARIABLE"].m190_tolerance_celsius|int %}

	{% if S >= THRESHOLD %}
		BEDFANSSLOW																# >= Threshold temp: Low speed fans while heating
	{% else %}
		BEDFANSOFF																# < Threshold temp: Turn bed fans off
	{% endif %}

	M140 {% for p in params
	  %}{'%s%s' % (p, params[p])}{%
	  endfor %}																	# Set bed temp

	{% if S != 0 %}
		TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={S|int} MAXIMUM={S|int + TOL}	# Wait for bed temp within tolerance
	{% endif %}

	# Post-heating fan speeds
	{% if S >= THRESHOLD %}
		BEDFANSFAST																# >= Threshold temp: Higher speed fans after heating finished
	{% endif %}
```

After:

```
# Override M190 (Wait for Bed Temperature)
# Use TEMPERATURE_WAIT with a tolerance band so we don't wait for PID to level off.
[gcode_macro M190]
description: Override of stock M190 — uses TEMPERATURE_WAIT with a tolerance band to avoid waiting for PID overshoot to settle.
rename_existing: M99190
gcode:
	# Parameters
	{% set S = params.S|int %}
	# Vars
	{% set TOL = printer["gcode_macro _USER_VARIABLE"].m190_tolerance_celsius|int %}

	M140 {% for p in params
	  %}{'%s%s' % (p, params[p])}{%
	  endfor %}																	# Set bed temp

	{% if S != 0 %}
		TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={S|int} MAXIMUM={S|int + TOL}	# Wait for bed temp within tolerance
	{% endif %}
```

- [ ] **Step 3: Remove the `TURN_OFF_HEATERS` override block**

Before (lines 103–109):

```
# Replace TURN_OFF_HEATERS
[gcode_macro TURN_OFF_HEATERS]
description: Override of stock TURN_OFF_HEATERS — also turns bed fans off.
rename_existing: _TURN_OFF_HEATERS
gcode:
	BEDFANSOFF
	_TURN_OFF_HEATERS
```

After: delete entirely. The line `# Replace TURN_OFF_HEATERS` is also removed.

- [ ] **Step 4: Remove the `bedfanloop` delayed_gcode block**

Before (lines 111–124, including the section header banner):

```
################ Monitoring loop #####################
# Turns bed fans to "fast" speed once target bed temp is reached.
[delayed_gcode bedfanloop]
gcode:
	# Vars
	{% set THRESHOLD = printer["gcode_macro _USER_VARIABLE"].bedfans_threshold|int %}

	{% if printer.heater_bed.target >= THRESHOLD %}								# Continue only if target temp greater than threshold.
		{% if printer.heater_bed.temperature|int >= (printer.heater_bed.target|int - 1) %}
			BEDFANSFAST															# If within 1 degree of target temp: Higher speed fans
		{% else %}
			UPDATE_DELAYED_GCODE ID=bedfanloop DURATION=5						# If temp not reached yet: loop again
		{% endif %}
	{% endif %}
```

After: delete entirely (the `################ Monitoring loop #####################` banner too).

- [ ] **Step 5: Verify the file's final shape**

`config/macros/bedfans.cfg` should now contain (in order):

1. The `[fan_generic BedFans]` hardware block
2. `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` alias macros
3. `SET_HEATER_TEMPERATURE` override (M104/M99140 routing only)
4. `M190` override (TEMPERATURE_WAIT tolerance only)
5. `M140` alias to `SET_HEATER_TEMPERATURE`

No delayed_gcode, no TURN_OFF_HEATERS override.

- [ ] **Step 6: Pre-commit + tests**

```bash
pre-commit run --files config/macros/bedfans.cfg
make test-py
```

Expected: all green. L2 may flag `bedfans_threshold` / `bedfans_fast` / `bedfans_slow` as **unused** if there's an unused-variable check — there isn't one today, so they pass. They get removed in Task 7.

- [ ] **Step 7: Commit**

```bash
git add config/macros/bedfans.cfg
git commit -m "chore(macros): strip bed-target-driven bedfan automation"
```

---

### Task 7: Remove obsolete `_USER_VARIABLE` keys + repoint aliases

**Files:**
- Modify: `config/macros/_user_variables.cfg`
- Modify: `config/macros/bedfans.cfg`

Post-Task-6 state: `bedfans_threshold` is orphan (no consumers). `bedfans_fast` and `bedfans_slow` are still consumed by `BEDFANSFAST` / `BEDFANSSLOW` manual aliases. Spec §5 wants all 3 keys gone — so update those aliases to read the new chamber-prefixed vars (`chamber_heat_speed` and `chamber_voc_baseline`), which is exactly the spec's intent (§5 inline comment: "replaced by chamber_heat_speed / chamber_voc_baseline"). Aliases stay callable; speeds shift to the new design's values (0.1 / 1.0 instead of 0.2 / 0.6).

- [ ] **Step 1: Confirm what's left referencing the bedfans_* keys**

```bash
grep -rn "bedfans_threshold\|bedfans_fast\|bedfans_slow" config/ tests/ scripts/
```

Expected matches: definitions in `_user_variables.cfg`, plus `bedfans_slow` in `BEDFANSSLOW` body and `bedfans_fast` in `BEDFANSFAST` body in `bedfans.cfg`. Nothing else.

- [ ] **Step 2: Repoint `BEDFANSSLOW` and `BEDFANSFAST` to the new chamber vars**

Edit `config/macros/bedfans.cfg`. In the `BEDFANSSLOW` macro body, change:

```
{% set SLOW = printer["gcode_macro _USER_VARIABLE"].bedfans_slow|float %}
```

to:

```
{% set SLOW = printer["gcode_macro _USER_VARIABLE"].chamber_voc_baseline|float %}
```

In the `BEDFANSFAST` macro body, change:

```
{% set FAST = printer["gcode_macro _USER_VARIABLE"].bedfans_fast|float %}
```

to:

```
{% set FAST = printer["gcode_macro _USER_VARIABLE"].chamber_heat_speed|float %}
```

(Optional but recommended) Update the `BEDFANSSLOW` / `BEDFANSFAST` description fields to reflect that the speed values now come from the chamber-control knobs.

- [ ] **Step 3: Delete the 3 obsolete keys + the `# Bed fans` header comment**

Edit `config/macros/_user_variables.cfg`. Delete the `# Bed fans` section comment plus the 3 `variable_bedfans_*` lines (they become orphan once Step 2's repointing lands).

- [ ] **Step 4: Update the file header comment**

Remove the line `#   bedfans_*                  was [_BEDFANVARS] in bedfans.cfg` from the mapping table near the top of `_user_variables.cfg`.

- [ ] **Step 5: Pre-commit + tests**

```bash
pre-commit run --files config/macros/_user_variables.cfg config/macros/bedfans.cfg
make test-py
```

Expected: all green. The orphan check in `test_user_variable_definitions_used` now passes — the chamber vars are consumed by both the loop AND the manual aliases.

- [ ] **Step 6: Commit**

```bash
git add config/macros/_user_variables.cfg config/macros/bedfans.cfg
git commit -m "chore(macros): drop bedfans_* keys; aliases now read chamber_* vars"
```

---

### Task 8: Lower `[temperature_fan chamber].max_temp` 70 → 60

**Files:**
- Modify: `config/bed.cfg`

Operator safety cap (spec §7). Klipper will trigger a protective shutdown if the chamber sensor exceeds 60°C; matches the `chamber_max_target` clamp.

- [ ] **Step 1: Edit `config/bed.cfg`**

Find line 51:

```
max_temp: 70
```

In the `[temperature_fan chamber]` block (between lines 42–61). Change to:

```
max_temp: 60
```

- [ ] **Step 2: Pre-commit + tests**

```bash
pre-commit run --files config/bed.cfg
make test-py
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add config/bed.cfg
git commit -m "fix(chamber): lower temperature_fan chamber max_temp 70 -> 60 to match safety cap"
```

---

### Task 9: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Two updates: macro inventory entry + a line under "Recently resolved".

- [ ] **Step 1: Add a new macro inventory block**

Find the "Macro inventory" section in `CLAUDE.md`. After the `### config/macros/bedfans.cfg — Ellis BedFans automation` block, insert:

```markdown
### `config/macros/chamber_control.cfg` — active chamber control
- `_CHAMBER_CONTROL` — state holder (`variable_target`); single source of the live setpoint
- `SET_CHAMBER_TARGET TARGET=<°C>` — only mutator of the setpoint; clamps to `[0, chamber_max_target]` with M117/RESPOND warning above cap; kicks the loop with 1s delay
- `chamber_control_loop` — 5-second delayed_gcode tick; state machine over (target, chamber_temp, bed_temp, print_state) writes BedFans speed + temperature_fan chamber target. Five states: HEAT / COOL / MAINTAIN / VOC BASELINE / OFF (self-terminating). Called from PRINT_START (bootstrap + setter), PRINT_END (TARGET=0), `_CANCEL_PRINT_HOOK` (TARGET=0). Sole automatic writer of BedFans after the bedfans.cfg overrides were stripped (PR for spec 2026-05-18-chamber-control-design).
```

- [ ] **Step 2: Update the bedfans inventory block**

Find the `### config/macros/bedfans.cfg — Ellis BedFans automation` section. Replace its body with the post-cleanup state:

Before (whatever is currently there for `bedfans.cfg`):

```
### `config/macros/bedfans.cfg` — Ellis BedFans automation
- `_BEDFANVARS` — config (threshold, fast, slow speeds)
- `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` — direct controls
- Overrides: `SET_HEATER_TEMPERATURE`, `M140`, `M190`, `TURN_OFF_HEATERS` (all integrate bed-fan logic)
- `bedfanloop` — delayed-gcode that ramps to fast speed once target is reached
```

After:

```
### `config/macros/bedfans.cfg` — BedFans hardware + manual aliases
- `[fan_generic BedFans]` — hardware definition (PWM pin `z:P2.5`)
- `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` — manual console aliases; no automatic callers (the chamber control loop in `chamber_control.cfg` owns BedFans state automatically — see that file's inventory entry)
- `SET_HEATER_TEMPERATURE` override — routes `HEATER=heater_bed` → `M99140` so M140 / Mainsail / SET_HEATER_TEMPERATURE all route the same way. No bedfan side-effects.
- `M140` alias — calls `SET_HEATER_TEMPERATURE`
- `M190` override — uses `TEMPERATURE_WAIT` with `m190_tolerance_celsius` band; no bedfan side-effects
```

- [ ] **Step 3: Add a "Recently resolved" log entry**

Find the "Recently resolved (historical log)" section. Insert at the top of the list:

```markdown
- ~~Bed-target-driven BedFans automation~~ — replaced 2026-05-18 by the active chamber control loop in `config/macros/chamber_control.cfg`. Spec: `docs/superpowers/specs/2026-05-18-chamber-control-design.md`.
```

- [ ] **Step 4: Pre-commit (CLAUDE.md is docs only, no make test-py needed)**

```bash
pre-commit run --files CLAUDE.md
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): note chamber_control.cfg + bedfans cleanup"
```

---

### Task 10: Final integration pass

**Files:** none directly; verifies cross-file integrity.

- [ ] **Step 1: Full repo grep for dead refs**

```bash
grep -rn "bedfans_threshold\|bedfans_fast\|bedfans_slow\|bedfanloop\|BEDFANVARS" config/ tests/ scripts/ docs/
```

Expected: zero matches in `config/` and `scripts/`. Matches in `docs/superpowers/specs/` are fine (specs are historical). Matches in `tests/` should also be zero unless an old assertion exists — if so, fix the test.

- [ ] **Step 2: Full test pyramid run**

```bash
make test-py
```

Expected: all green. Confirms the post-cleanup state is internally consistent.

- [ ] **Step 3: Smoke-grep the new contract**

```bash
grep -n "SET_CHAMBER_TARGET\|chamber_control_loop\|_CHAMBER_CONTROL" config/
```

Expected output (sanity check):
- `chamber_control.cfg`: defines `_CHAMBER_CONTROL`, `SET_CHAMBER_TARGET`, `chamber_control_loop`
- `print_start.cfg`: `UPDATE_DELAYED_GCODE ID=chamber_control_loop` (bootstrap) + `SET_CHAMBER_TARGET TARGET={chamber}` (step 9) + `SET_CHAMBER_TARGET TARGET=0` (PRINT_END)
- `client_hooks.cfg`: `SET_CHAMBER_TARGET TARGET=0` (_CANCEL_PRINT_HOOK)

If any of those are missing, fix and re-test.

- [ ] **Step 4: Verify no commit-message style drift**

```bash
git log --oneline main..HEAD
```

Expected: all commit subjects use one of `feat:` / `fix:` / `chore:` / `docs:` (with scopes). No `refactor:` or other unsanctioned prefixes (CLAUDE.md "Git Conventions").

---

## Review + ship

### Task 11: Pre-push review via `pr-review-toolkit:review-pr`

- [ ] **Step 1: Run the toolkit before pushing**

Per memory `[[feedback_pr_review_toolkit]]` (no "trivial" exemption). The toolkit reviews the working branch against `main`.

```bash
# In Claude Code:
# Skill: pr-review-toolkit:review-pr
```

- [ ] **Step 2: Address findings**

Fix any P0/P1 findings inline (fresh commits, no `--amend` — per memory `[[feedback_subagent_no_amend]]`). Re-run the toolkit if architectural changes resulted.

- [ ] **Step 3: Push + open PR**

```bash
git push -u origin feat/chamber-control
gh pr create --title "feat(chamber): active chamber temperature control" --body "$(cat <<'EOF'
## Summary
- Replaces bed-target-driven BedFans automation with a continuous chamber control loop owning both BedFans and `temperature_fan chamber`.
- `SET_CHAMBER_TARGET TARGET=<°C>` is the single entry point; PRINT_START / PRINT_END / `_CANCEL_PRINT_HOOK` call it. Manual console use also supported.
- VOC baseline runs whenever a print is active or the bed is above `voc_cooldown_threshold` (40°C default), so charcoal filtration covers cooldown.
- `[temperature_fan chamber].max_temp` lowered 70 → 60 to match the operator-stated safety cap.

Spec: `docs/superpowers/specs/2026-05-18-chamber-control-design.md`
Plan: `docs/superpowers/plans/2026-05-18-chamber-control-implementation.md`

## Restart impact
RESTART (gcode_macro / delayed_gcode / `_USER_VARIABLE` / `temperature_fan.max_temp`). No MCU pin changes; no FIRMWARE_RESTART needed.

## Test plan
- [x] L1 pre-commit clean
- [x] L2 macro_refcheck — new refs resolve, removed refs absent
- [x] L4 pytest clean
- [ ] L3 klippy CI green (on PR)
- [ ] L6 post-deploy smoke (after merge + /deploy-to-pi)
- [ ] Manual PLA print: bedfans run at voc_baseline during print + cooldown; off below 40°C bed
- [ ] Manual ABS print: bedfans ramp to heat_speed during PRINT_START soak; MAINTAIN once chamber reaches 30°C
- [ ] Manual `SET_CHAMBER_TARGET TARGET=80` from console: clamped to 60 with M117 warning
- [ ] Manual cancel mid-ABS: `_CANCEL_PRINT_HOOK` clears target, MMU unloads, bedfans VOC-baseline until bed cools

EOF
)"
```

- [ ] **Step 4: Address CI failures + post-merge deploy**

If CI fails on L3 klippy parse, debug locally (the dict files mock the MCU; failures point to config-level issues). After merge:

```bash
# In Claude Code:
# /deploy-to-pi
```

The skill gates on CI green + Pi-idle + no drift. After deploy, run the manual material tests above to validate L6.

---

## Self-review pass

**Spec coverage check:**

| Spec section | Plan task |
|---|---|
| §3.1 `_CHAMBER_CONTROL` state holder | Task 2 |
| §3.2 `SET_CHAMBER_TARGET` setter | Task 2 |
| §3.3 `chamber_control_loop` state machine | Task 3 |
| §3.4 PRINT_START step 9 swap + bootstrap | Task 5 |
| §3.4 PRINT_END `SET_CHAMBER_TARGET TARGET=0` | Task 4 |
| §3.4 `_CANCEL_PRINT_HOOK` `SET_CHAMBER_TARGET TARGET=0` | Task 4 |
| §3.4 `OFF` macro BedFans=0 line | No-op — already present at `macros.cfg:51` (documented at top of plan) |
| §4 bedfans.cfg cleanup (4 bullets) | Task 6 |
| §5 new `_USER_VARIABLE` keys (5) | Task 1 |
| §5 obsolete `_USER_VARIABLE` keys (3) | Task 7 |
| §6 new file include in printer.cfg | Task 2 |
| §6 CLAUDE.md macro inventory block | Task 9 |
| §7 `[temperature_fan chamber].max_temp` 70 → 60 | Task 8 |
| §7 `SET_CHAMBER_TARGET` clamping | Task 2 (clamp logic in setter body) |
| §9 L1–L5 covered by `make test-py` | Each task |
| §9 L6 post-deploy smoke + manual material tests | Task 11 |

**Placeholder scan:** none — every step has exact paths, exact line numbers, exact code, exact commands.

**Type consistency:** macro names (`_CHAMBER_CONTROL`, `SET_CHAMBER_TARGET`, `chamber_control_loop`) and `_USER_VARIABLE` key names (`chamber_target_band`, `chamber_voc_baseline`, `chamber_heat_speed`, `chamber_max_target`, `voc_cooldown_threshold`) are used consistently across Tasks 1–9. The `temperature_fan` accessor is `printer["temperature_fan chamber"].temperature` everywhere it appears.
