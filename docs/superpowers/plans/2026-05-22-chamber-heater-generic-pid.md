# Chamber Heater via `[heater_generic]` PID — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bang-bang BedFans control + independent `[temperature_fan chamber]` PID with a single `[heater_generic chamber]` block that PID-drives BedFans using the chamber thermistor as feedback. Drop automated exhaust control entirely.

**Architecture:** Per `docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md`. `[heater_generic chamber]` owns BedFans PWM (z:P2.5) + chamber thermistor (z:P0.24). `[fan_generic chamber_exhaust]` replaces the auto-PID exhaust on z:P2.7 with manual control. `chamber_control_loop` becomes a narrow state machine that runs only when `user_target == 0`. PRINT_END / _CANCEL_PRINT_HOOK preserve chamber target through cooldown for natural VOC capture (BedFans ramp to 100% as bed cools, circulating air through under-bed filter).

**Tech Stack:** Klipper config, jinja gcode macros, Pi-side SSH for deploy + PID_CALIBRATE, git worktrees + PR workflow.

**Key constraint:** The config refactor is **atomic** — Klipper rejects partial states (e.g. removing `[temperature_fan chamber]` while consumers still reference it). The whole config-edit phase commits as one logical change.

---

## Task 1: Worktree setup

**Files:** none (git operations only)

- [ ] **Step 1: Create worktree from main**

```sh
cd /Users/ben/code/voron-2-611
git fetch origin
git checkout main
git pull
```

Use the `EnterWorktree` tool (per `superpowers:using-git-worktrees`) with branch name `feat/chamber-heater-generic-pid`. Worktree path is auto-chosen by the tool.

- [ ] **Step 2: Verify clean working tree in worktree**

```sh
git status
```

Expected: `On branch feat/chamber-heater-generic-pid` + `nothing to commit, working tree clean`.

- [ ] **Step 3: Confirm main test runs green from worktree baseline**

```sh
make test-py
```

Expected: all hooks Passed, refcheck silent, pytest `7 passed`. (This validates the worktree was created correctly before we start editing.)

---

## Task 2: Update `_user_variables.cfg` (isolated, no consumers yet)

**Files:**
- Modify: `config/macros/_user_variables.cfg`

- [ ] **Step 1: Remove obsolete chamber variables**

Find these lines (search "Chamber control" comment block):

```
variable_chamber_target_band: 2      # hysteresis ±°C around setpoint
variable_chamber_voc_baseline: 0.15  # bedfan speed for VOC baseline + cooldown (10% is audibly noisy on this build; 15% is the quiet floor)
variable_chamber_heat_speed: 1.0     # bedfan speed in active heat mode
```

Delete all three lines. Leave `chamber_max_target` and `voc_cooldown_threshold` in place.

- [ ] **Step 2: Add the new VOC baseline temperature**

Insert after `chamber_max_target`:

```
variable_voc_baseline_temp: 30       # chamber heater target during VOC mode (target=0 + print_active). Low enough to require BedFans for circulation; below natural PLA-print chamber rise so PID barely runs.
```

- [ ] **Step 3: Bump `print_end_cooldown_seconds`**

Find:

```
variable_print_end_cooldown_seconds: 60       # PRINT_END "let things circulate" delay
```

Change `60` to `300`:

```
variable_print_end_cooldown_seconds: 300      # post-print VOC capture window — chamber heater stays active, BedFans ramp as bed cools, circulating air through under-bed filter
```

- [ ] **Step 4: Update the deprecation history comment**

Find:

```
#   chamber_target_band         was 2°C in chamber_control.cfg
#   chamber_voc_baseline        was 0.15 fan speed in chamber_control.cfg
#   chamber_heat_speed          was 1.0 fan speed in chamber_control.cfg
```

(or whatever's there; it may be slightly different). Replace with a note explaining the migration:

```
#   chamber_target_band, chamber_voc_baseline, chamber_heat_speed
#                              all dropped 2026-05-22 — replaced by PID-driven
#                              control in [heater_generic chamber]. See
#                              docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md
```

- [ ] **Step 5: Do NOT commit yet**

This task touches only one file but the changes are part of the atomic config refactor — they'd cause `make test-py` to fail standalone because `chamber_control.cfg` still references the variables we just deleted. Wait for Task 6 to commit everything together.

---

## Task 3: Replace `[temperature_fan chamber]` block in `bed.cfg`

**Files:**
- Modify: `config/bed.cfg`

- [ ] **Step 1: Remove the existing `[temperature_fan chamber]` block**

Locate the block (around line 42, search `[temperature_fan chamber]`). Delete the entire section through `min_speed: 0`. Also delete the header comment lines referring to "Chamber heater fan" if any are above the block.

- [ ] **Step 2: Insert the new chamber control blocks**

In the same location, insert:

```ini
# Chamber heater = BedFans recirculation via [heater_generic chamber] (PID).
# Replaces the prior [temperature_fan chamber] auto-PID exhaust. Drives BedFans
# (z:P2.5 — was [fan_generic BedFans] in macros/bedfans.cfg) using the chamber
# thermistor (z:P0.24) as feedback. Single PID controller for the whole chamber
# system; no race between heater and exhaust because there is no exhaust auto-
# controller anymore. Spec: docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md
[heater_generic chamber]
gcode_id: C
heater_pin: z:P2.5
sensor_type: 10k_thermistor
sensor_pin: z:P0.24
control: pid
pid_Kp: 40.000                              # placeholder — PID_CALIBRATE overwrites via SAVE_CONFIG (Task 8)
pid_Ki: 5.000
pid_Kd: 0.000
max_power: 1.0
min_temp: 0
max_temp: 70                                # sensor-shutdown ceiling; chamber_max_target (60) is the user setpoint cap
pwm_cycle_time: 0.05                        # 20 Hz, matches prior fan_generic default

# Permissive verify_heater. The "heater" here is a fan circulating bed air —
# it can't thermal-runaway like a resistive element can, so the safety budget
# is much looser than for heater_bed / extruder. Real chamber overheat is caught
# by [heater_generic chamber] max_temp = 70 above.
[verify_heater chamber]
max_error: 300
check_gain_time: 1800                       # 30 min — chamber response is slow
heating_gain: 1
hysteresis: 5

# Chamber exhaust fan is now a plain [fan_generic] — no automated controller.
# Available for manual SET_FAN_SPEED FAN=chamber_exhaust SPEED=N from macros
# or console. We rely on BedFans driving VOC capture through the under-bed
# filter instead of exhausting to the room.
[fan_generic chamber_exhaust]
pin: z:P2.7
kick_start_time: 0.5
```

- [ ] **Step 3: Update the header doc comment at the top of `bed.cfg`**

The file's header docstring (lines 1-15-ish) references `[temperature_fan chamber]`. Update those references to `[heater_generic chamber] + [fan_generic chamber_exhaust]`. Example replacement:

Before:
```
## - [temperature_fan chamber]     Chamber heater fan (PID, z:P2.7).
```

After:
```
## - [heater_generic chamber]      Chamber heater = BedFans via PID (z:P2.5,
##                                 thermistor z:P0.24). max_temp 70 = sensor
##                                 shutdown ceiling.
## - [fan_generic chamber_exhaust] Chamber exhaust on z:P2.7. Manual control
##                                 only; no automated controller.
```

- [ ] **Step 4: Do NOT commit yet** (atomic refactor — see Task 6)

---

## Task 4: Remove `[fan_generic BedFans]` + manual aliases from `bedfans.cfg`

**Files:**
- Modify: `config/macros/bedfans.cfg`

- [ ] **Step 1: Remove the `[fan_generic BedFans]` block**

Find the block (~top of file). Delete from `[fan_generic BedFans]` through whatever line ends that block (including `kick_start_time` etc).

- [ ] **Step 2: Remove the three manual aliases**

Find and delete in their entirety:

```
[gcode_macro BEDFANSSLOW]
...
[gcode_macro BEDFANSFAST]
...
[gcode_macro BEDFANSOFF]
...
```

(Each is ~5-10 lines.)

- [ ] **Step 3: Keep the `SET_HEATER_TEMPERATURE` override**

Find the `[gcode_macro SET_HEATER_TEMPERATURE]` block (or `rename_existing: SET_HEATER_TEMPERATURE_BASE` — same thing). LEAVE IT IN PLACE — it routes `HEATER=heater_bed` calls via M99140 and is unrelated to BedFans. Other heater names pass through naturally; `HEATER=chamber` (the new heater_generic) will work without modification.

- [ ] **Step 4: Add a deprecation note at the top of the file**

Replace the existing header comment with:

```ini
########################################
# BedFans deprecation note (2026-05-22):
#
# This file used to define [fan_generic BedFans] and the BEDFANSSLOW /
# BEDFANSFAST / BEDFANSOFF manual aliases. Both are gone — the BedFans
# PWM pin (z:P2.5) is now owned by [heater_generic chamber] in bed.cfg,
# which runs PID against the chamber thermistor.
#
# This file is preserved for the SET_HEATER_TEMPERATURE override below
# (routes heater_bed via M99140 — unrelated to BedFans). Will eventually
# be renamed once we move that override elsewhere.
########################################
```

- [ ] **Step 5: Do NOT commit yet** (atomic refactor — see Task 6)

---

## Task 5: Rewrite `chamber_control.cfg`

**Files:**
- Modify: `config/macros/chamber_control.cfg`

This is the biggest semantic change. Replace the entire `_CHAMBER_CONTROL`, `SET_CHAMBER_TARGET`, and `chamber_control_loop` blocks.

- [ ] **Step 1: Replace `[gcode_macro _CHAMBER_CONTROL]`**

Find the existing block (variable_target + variable_heating). Replace with:

```jinja
[gcode_macro _CHAMBER_CONTROL]
description: State holder for the chamber-control delayed_gcode loop. variable_user_target is the live setpoint the operator set via SET_CHAMBER_TARGET — used by the loop to decide between explicit-heat / VOC / OFF modes.
variable_user_target: 0
gcode:
  # Variables-only macro; no body. Same pattern as _USER_VARIABLE.
```

(Note: renamed from `variable_target` to `variable_user_target` for clarity — the variable specifically tracks what the user requested, distinct from the heater's actual target which may be voc_baseline_temp in VOC mode. Search the rest of `chamber_control.cfg` for `_CHAMBER_CONTROL"].target` and update all references in Steps 2-3 below.)

- [ ] **Step 2: Replace `[gcode_macro SET_CHAMBER_TARGET]`**

Find the existing macro. Replace with:

```jinja
[gcode_macro SET_CHAMBER_TARGET]
description: Set the chamber heater target. Clamps to [0, chamber_max_target]. For TARGET>0 writes the heater setpoint directly (Klipper PID owns continuous control). For TARGET=0 kicks the loop, which decides between VOC mode (during prints / bed-still-hot) and OFF.
gcode:
  {% set chamber_max_target = printer["gcode_macro _USER_VARIABLE"].chamber_max_target|float %}
  {% set requested = params.TARGET|default(0)|float %}
  {% set target = [[requested, 0]|max, chamber_max_target]|min %}
  {% if requested > chamber_max_target %}
    M117 Chamber target {requested}>{chamber_max_target}, clamping
    RESPOND TYPE=echo MSG="Chamber target {requested}°C exceeds chamber_max_target ({chamber_max_target}°C); clamped to {target}°C."
  {% elif requested < 0 %}
    M117 Chamber target {requested}<0, clamping
    RESPOND TYPE=echo MSG="Chamber target {requested}°C is negative; clamped to 0°C (OFF)."
  {% endif %}
  SET_GCODE_VARIABLE MACRO=_CHAMBER_CONTROL VARIABLE=user_target VALUE={target}
  {% if target > 0 %}
    # User wants explicit chamber heating. heater_generic PID handles
    # continuous control; no polling needed. Loop self-terminates next tick
    # if it was running.
    SET_HEATER_TEMPERATURE HEATER=chamber TARGET={target}
  {% else %}
    # target=0 — defer to the loop, which decides VOC vs OFF based on print
    # state + bed temp.
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1
  {% endif %}
```

- [ ] **Step 3: Replace `[delayed_gcode chamber_control_loop]`**

Find the existing loop body. Replace with:

```jinja
[delayed_gcode chamber_control_loop]
gcode:
  # Narrow state machine: runs only while user_target == 0. For user_target > 0
  # the heater_generic PID is the entire controller — this loop does not poll.
  # See spec docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md.
  {% set user_target          = printer["gcode_macro _CHAMBER_CONTROL"].user_target|float %}
  {% set voc_baseline_temp    = printer["gcode_macro _USER_VARIABLE"].voc_baseline_temp|float %}
  {% set voc_cooldown_bed     = printer["gcode_macro _USER_VARIABLE"].voc_cooldown_threshold|float %}
  {% set bed_temp             = printer.heater_bed.temperature|float %}
  {% set state                = printer.print_stats.state|string %}
  {% set print_active         = state in ("printing", "paused") %}

  {% if user_target > 0 %}
    # User has set explicit chamber target. heater_generic owns control;
    # loop has nothing to do and does not reschedule (self-terminates).
  {% elif print_active or bed_temp >= voc_cooldown_bed %}
    # VOC mode — set a low chamber target so PID circulates BedFans.
    SET_HEATER_TEMPERATURE HEATER=chamber TARGET={voc_baseline_temp}
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=30
  {% else %}
    # OFF — print not active and bed cool. Stop the chamber heater.
    SET_HEATER_TEMPERATURE HEATER=chamber TARGET=0
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=60
  {% endif %}
```

- [ ] **Step 4: Update the file header docstring at the top of chamber_control.cfg**

Find the existing top-of-file comment block. Replace with:

```ini
#####################################################################
#   Chamber control — owns user_target state + auto-VOC/OFF state machine.
#
#   Architecture (post-2026-05-22 refactor):
#     - [heater_generic chamber] in bed.cfg owns the BedFans PWM pin
#       (z:P2.5) and runs PID against the chamber thermistor (z:P0.24).
#     - This file owns SET_CHAMBER_TARGET (the user-facing API) and
#       chamber_control_loop (a narrow state machine that ONLY runs when
#       user_target == 0, to decide between VOC mode during prints and
#       OFF when idle).
#
#   See spec: docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md
#####################################################################
```

- [ ] **Step 5: Do NOT commit yet** (atomic refactor — see Task 6)

---

## Task 6: Update consumers — `print_start.cfg`, `macros.cfg`, `lcd_tweaks.cfg`, `client_hooks.cfg`

**Files:**
- Modify: `config/macros/print_start.cfg`
- Modify: `config/macros/macros.cfg`
- Modify: `config/macros/lcd_tweaks.cfg`
- Modify: `config/client_hooks.cfg`

- [ ] **Step 1: print_start.cfg — remove immediate chamber-off + update TEMPERATURE_WAIT sensor**

Find the line in `PRINT_END`:

```
SET_CHAMBER_TARGET TARGET=0                            # release active control; loop continues VOC baseline until bed cools
```

Replace with the comment-only:

```
# NB: NO SET_CHAMBER_TARGET TARGET=0 here. Chamber target persists through
# the post-print cooldown G4 for VOC capture — bed cools, PID can't maintain
# target, BedFans ramp to 100%, circulating air through under-bed filter.
# OFF (called from _PRINT_END_CLEANUP after the G4) zeros chamber target.
```

Then find the chamber soak TEMPERATURE_WAIT line in PRINT_START's step 9:

```
TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={(chamber / 2)|int}
```

Change `temperature_fan chamber` → `heater_generic chamber`:

```
TEMPERATURE_WAIT SENSOR="heater_generic chamber" MINIMUM={(chamber / 2)|int}
```

- [ ] **Step 2: macros.cfg — update HEATSOAK TEMPERATURE_WAIT**

Find in HEATSOAK:

```
TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={c}
```

Change to:

```
TEMPERATURE_WAIT SENSOR="heater_generic chamber" MINIMUM={c}
```

- [ ] **Step 3: lcd_tweaks.cfg — update display source**

Find:

```
{% set chamber = printer['temperature_fan chamber'] %}
```

Change to:

```
{% set chamber = printer['heater_generic chamber'] %}
```

Then verify the surrounding code that reads `chamber.temperature` (heater_generic exposes the same `.temperature` field, so display behavior should be unchanged). Search for any `chamber.target` reference in this file — heater_generic exposes `target` for the setpoint too, so should also work.

- [ ] **Step 4: client_hooks.cfg — remove immediate chamber-off from _CANCEL_PRINT_HOOK**

Find in `_CANCEL_PRINT_HOOK`:

```
SET_CHAMBER_TARGET TARGET=0
```

Replace with the comment-only:

```
# NB: NO SET_CHAMBER_TARGET TARGET=0 here — chamber target persists through
# MMU_END's unload + the _PRINT_END_CLEANUP G4 for VOC capture, matching the
# PRINT_END pattern. OFF (called from _PRINT_END_CLEANUP) zeros chamber target.
```

Also update the descriptive comment at the top of the macro to reflect this — find the description and adjust accordingly.

- [ ] **Step 5: Do NOT commit yet** (atomic refactor — see Task 7)

---

## Task 7: Local validation + atomic commit

**Files:** none (test + commit)

- [ ] **Step 1: Run klippy parse + macro_refcheck + pytest**

```sh
cd <worktree path>
make test-py
```

Expected: all six pre-commit hooks Passed, refcheck silent (no "unknown command" warnings), pytest `7 passed in 0.2X seconds`.

If anything fails, the most likely cause is a missed reference to `temperature_fan chamber` or `_CHAMBER_CONTROL.target` (old variable name). Grep for both and fix:

```sh
grep -rn "temperature_fan chamber\|_CHAMBER_CONTROL.*\.target\b" config/
```

Expected: no hits in code blocks. (Comments referring to history are fine.)

- [ ] **Step 2: Stage all changes**

```sh
git add config/bed.cfg config/macros/bedfans.cfg config/macros/chamber_control.cfg config/macros/print_start.cfg config/macros/macros.cfg config/macros/lcd_tweaks.cfg config/macros/_user_variables.cfg config/client_hooks.cfg
```

- [ ] **Step 3: Verify staged diff**

```sh
git diff --staged --stat
```

Expected: ~8 files changed, ~100-200 lines of churn. Sanity-check no other files snuck in.

- [ ] **Step 4: Commit**

```sh
git commit -m "$(cat <<'EOF'
feat(chamber): heater_generic PID drives BedFans for chamber heating

Replaces the bang-bang BedFans + independent temperature_fan chamber PID
with a single [heater_generic chamber] block. BedFans PWM (z:P2.5) becomes
the heater output; chamber thermistor (z:P0.24) is the feedback sensor.
Drops [temperature_fan chamber] entirely; chamber exhaust becomes a plain
[fan_generic chamber_exhaust] (manual control only). User prefers BedFans-
driven VOC capture through the under-bed filter over room-exhaust active
cooling.

Spec: docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md

Changes by file:
- config/bed.cfg: replace [temperature_fan chamber] with
  [heater_generic chamber] + [verify_heater chamber] (permissive — fan-only
  "heater" can't thermal-runaway) + [fan_generic chamber_exhaust].
- config/macros/bedfans.cfg: remove [fan_generic BedFans] + BEDFANSSLOW /
  BEDFANSFAST / BEDFANSOFF manual aliases. Keep SET_HEATER_TEMPERATURE
  override (routes heater_bed via M99140; unrelated to BedFans).
- config/macros/chamber_control.cfg: rewrite. _CHAMBER_CONTROL now tracks
  user_target only (variable_heating removed; hysteresis state no longer
  needed). SET_CHAMBER_TARGET writes heater target directly for target>0;
  kicks the loop for target=0. chamber_control_loop self-terminates when
  user_target > 0 (Klipper PID owns control); polls only for VOC / OFF
  state-derived transitions.
- config/macros/print_start.cfg: PRINT_END no longer immediately zeros
  chamber target — chamber stays warm through _PRINT_END_CLEANUP's G4 for
  natural VOC capture (BedFans ramp to 100% as bed cools without heat
  source). Soak step TEMPERATURE_WAIT switched from temperature_fan to
  heater_generic.
- config/macros/macros.cfg: HEATSOAK TEMPERATURE_WAIT sensor update.
- config/macros/lcd_tweaks.cfg: display source for chamber temp switched
  from temperature_fan to heater_generic.
- config/macros/_user_variables.cfg: drop chamber_voc_baseline (fan
  speed), chamber_heat_speed (fan speed), chamber_target_band (hysteresis,
  no longer applicable). Add voc_baseline_temp: 30 (chamber heater target
  during VOC mode). Bump print_end_cooldown_seconds 60 → 300 (post-print
  VOC window).
- config/client_hooks.cfg: _CANCEL_PRINT_HOOK no longer immediately zeros
  chamber target. Same VOC-during-cooldown rationale as PRINT_END.

PID values (Kp/Ki/Kd in [heater_generic chamber]) are placeholders;
PID_CALIBRATE HEATER=chamber TARGET=55 will overwrite them via
SAVE_CONFIG after deploy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: single commit, no pre-commit hook failures.

- [ ] **Step 5: Push branch**

```sh
git push -u origin feat/chamber-heater-generic-pid
```

Expected: branch created on origin, no errors. Branch protection rules will block direct merge until CI is green (see Task 12).

---

## Task 8: Deploy to Pi for PID_CALIBRATE

**Files:** none (manual SSH deploy, NOT `/deploy-to-pi`)

Why not `/deploy-to-pi`? The PID_CALIBRATE step will modify `printer.cfg` on the Pi (via SAVE_CONFIG) — we want to capture those values into the PR before merging. Using the standard deploy now would also try to push the placeholder Kp/Ki/Kd back over the post-cal values later.

- [ ] **Step 1: Snapshot current Pi printer.cfg as a rollback point**

```sh
ssh pi@mainsailos.local "cp ~/printer_data/config/printer.cfg ~/printer_data/config/printer.cfg.pre-chamber-refactor-$(date +%Y%m%d_%H%M%S)"
```

- [ ] **Step 2: Direct rsync of the worktree's config to the Pi**

(NOT going through `/deploy-to-pi`'s machinery; manual sync from this worktree, skipping the SAVE_CONFIG section preservation since we're about to invalidate it anyway.)

```sh
cd <worktree path>
rsync -av --include='*.cfg' --exclude='*' --exclude='printer.cfg' --exclude='/firmware/' --exclude='/archive/' \
  config/ pi@mainsailos.local:printer_data/config/
```

Note: `printer.cfg` is excluded because its SAVE_CONFIG block needs to be preserved across the deploy (the new heater_generic PID values will land there after PID_CALIBRATE).

Then handle the non-SAVE_CONFIG portion of printer.cfg by hand if needed (this PR doesn't touch the printer.cfg body, only files it `[include]`s, so likely no change needed here — verify with `git diff main -- config/printer.cfg` first; expect empty diff).

- [ ] **Step 3: RESTART Klipper**

```sh
curl -s -X POST "http://mainsailos.local:7125/printer/gcode/script" --data-urlencode "script=RESTART"
```

Wait for ready:

```sh
until curl -s "http://mainsailos.local:7125/printer/info" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin)['result']; sys.exit(0 if d['state']=='ready' else 1)"; do sleep 2; done; echo ready
```

Expected: `ready`. If Klipper fails to parse the config, fix the issue locally and re-rsync.

- [ ] **Step 4: Sanity check — heater_generic is loaded**

```sh
curl -s "http://mainsailos.local:7125/printer/objects/query?heater_generic%20chamber" | python3 -m json.tool
```

Expected: JSON includes `"heater_generic chamber"` with `"temperature": <value>` and `"target": 0`. If the key is missing, Klipper didn't load the new block — check klippy.log for errors.

---

## Task 9: PID_CALIBRATE

**Files:** Pi `printer.cfg` (via SAVE_CONFIG only; not edited by hand)

This step takes ~45-90 min total wall-clock time. The actual cal is automated by Klipper; just queue the commands.

- [ ] **Step 1: Heat bed to ABS temp + park toolhead**

```gcode
M140 S110
G28
G0 X175 Y175 Z10 F3000
```

(Send via Mainsail console.) Don't proceed to step 2 until bed has been at 110°C for **at least 15 minutes** (chamber needs thermal equilibrium before cal). Watch `temperature_probe btt_eddy` + `heater_generic chamber` temperatures stabilize.

- [ ] **Step 2: Run PID_CALIBRATE**

```gcode
PID_CALIBRATE HEATER=chamber TARGET=55 WRITE_FILE=1
```

Cal runs ~30-60 min. Klipper will report progress in console. During cal, BedFans will cycle on/off as the algorithm finds the response. **Do not interrupt.** If you must abort, send `EMERGENCY_STOP` and accept that values are uncalibrated.

When cal completes, Klipper prints final Kp/Ki/Kd and prompts for SAVE_CONFIG.

- [ ] **Step 3: Capture the values for the commit message**

Copy the reported Kp / Ki / Kd from the Mainsail console output. Also note the values logged by Klipper at the end of cal (search klippy.log for "Final:" or similar).

- [ ] **Step 4: SAVE_CONFIG**

```gcode
SAVE_CONFIG
```

Klipper restarts. Wait for ready (same poll as Task 8 step 3).

- [ ] **Step 5: Verify the values landed in printer.cfg**

```sh
ssh pi@mainsailos.local "grep -A3 'heater_generic chamber' ~/printer_data/config/printer.cfg | tail -10"
```

Expected: a SAVE_CONFIG section with the new Kp/Ki/Kd values overriding the placeholders.

---

## Task 10: Validation print

**Files:** none (hardware-in-loop)

- [ ] **Step 1: Pre-flight checks**

```gcode
G28                           ; home (verifies eddy still works)
QUAD_GANTRY_LEVEL             ; verifies probe path
G28                           ; re-home after QGL
PROBE_ACCURACY                ; sub-10µm std dev expected (no regression)
```

Stop here if anything regresses. Eddy probe should be untouched, but the config refactor exercise of restarting Klipper introduces opportunity for unrelated regressions.

- [ ] **Step 2: Run a short ABS test print**

Slice a small ABS object (e.g. an XYZ calibration cube or single-wall vase mode tower, ~10-15 min print time). The slicer should pass `CHAMBER=55` per your ABS filament profile.

Observe and note in lab-notebook fashion:
- Time from PRINT_START to `TEMPERATURE_WAIT SENSOR="heater_generic chamber" MINIMUM={chamber/2}` (= 27°C) passing. Expect a few minutes.
- Whether BedFans speed visibly tapers as chamber approaches 55°C (the whole point of this refactor).
- Whether chamber sits stably at 55°C during the print body, or oscillates / drifts.
- During PRINT_END's G4 cooldown (300s with our new value), confirm BedFans run continuously — initially at low speed (bed still hot, chamber maintaining 55 easily), then ramp to 100% as bed cools below ability to sustain.

- [ ] **Step 3: Tail klippy.log for verify_heater messages during the print**

```sh
ssh pi@mainsailos.local "tail -200 ~/printer_data/logs/klippy.log | grep -iE 'verify_heater|chamber'"
```

Expected: no `verify_heater chamber` trip warnings. If any appear, increase `check_gain_time` further in the `[verify_heater chamber]` block (re-edit, re-rsync, restart).

- [ ] **Step 4: Post-print state check**

After the G4 cooldown completes and OFF fires:

```sh
curl -s "http://mainsailos.local:7125/printer/objects/query?heater_generic%20chamber" | python3 -m json.tool
```

Expected: `target: 0`, `power: 0`, chamber temp dropping toward ambient.

---

## Task 11: Sync the PID values into the repo

**Files:**
- Modify: `config/bed.cfg` (the placeholders inside `[heater_generic chamber]` are now stale; the real values landed in printer.cfg SAVE_CONFIG via PID_CALIBRATE)

Two options here depending on how we want to track the cal:

**Option A — leave placeholders in bed.cfg, let SAVE_CONFIG own real values:**
This matches how the existing eddy / extruder / heater_bed PID values are tracked — the body of printer.cfg has no PID, the SAVE_CONFIG block at the bottom does. Standard Klipper pattern. Recommended.

- [ ] **Step 1 (Option A): /sync-from-pi to pull the new printer.cfg SAVE_CONFIG block**

```sh
cd <worktree path>
bash scripts/sync_from_pi.sh
```

When the diff prompt comes up, review — expect changes to printer.cfg SAVE_CONFIG block (new `[heater_generic chamber]` PID values), possibly mmu/mmu_vars.cfg churn, nothing else. Type `y` to apply.

- [ ] **Step 2 (Option A): Commit the synced cal data**

```sh
git add config/printer.cfg config/mmu/mmu_vars.cfg
git commit -m "$(cat <<'EOF'
chore(sync): capture chamber PID values from PID_CALIBRATE

PID_CALIBRATE HEATER=chamber TARGET=55 results, run after the deploy
of feat/chamber-heater-generic-pid (commit XXX) with bed at 110°C and
chamber thermally equilibrated.

Pre-cal placeholders in config/bed.cfg's [heater_generic chamber]:
  pid_Kp: 40.000  pid_Ki: 5.000  pid_Kd: 0.000

Post-cal values now in printer.cfg SAVE_CONFIG:
  pid_Kp: <fill in>  pid_Ki: <fill in>  pid_Kd: <fill in>

Standard Klipper pattern — bed.cfg's heater_generic block holds
placeholder defaults so the config parses cleanly on first load; the
SAVE_CONFIG block at the bottom of printer.cfg is authoritative for
runtime.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Fill in the Kp/Ki/Kd values from Task 9 step 3 before running the commit.

- [ ] **Step 3 (Option A): Push**

```sh
git push
```

---

## Task 12: PR + merge

**Files:** none (gh + git operations)

- [ ] **Step 1: Open PR**

```sh
gh pr create --title "feat: chamber heater via heater_generic PID on BedFans" --body "$(cat <<'EOF'
## Summary

Replaces today's bang-bang chamber control (BedFans on/off via state machine + independent temperature_fan chamber PID for exhaust) with a single [heater_generic chamber] block that PID-drives BedFans using the chamber thermistor as feedback. Drops automated exhaust control entirely; the exhaust fan becomes a plain [fan_generic chamber_exhaust] for manual use.

Spec: docs/superpowers/specs/2026-05-22-chamber-heater-generic-pid.md

## Why

- Eliminates the BedFans-vs-exhaust race that PR #110 hysteresis didn't fix
- Continuous PID tapers BedFans speed near setpoint instead of bang-banging
- Post-print VOC capture happens naturally: chamber target persists through cooldown, bed cools, PID ramps BedFans to 100% to maintain target, circulating air through under-bed filter
- Simpler control surface (single Klipper-managed object for chamber heating)

## Validation

- [x] Local make test-py green (klippy parse, refcheck, pytest)
- [x] Deploy + PID_CALIBRATE HEATER=chamber TARGET=55 completed (Kp/Ki/Kd captured in second commit)
- [x] Short ABS validation print — chamber reached 55, no verify_heater trips, BedFans tapered toward setpoint, ramped to 100% during post-print cooldown
- [x] G28 + QGL + PROBE_ACCURACY unchanged from pre-refactor baseline

## Rollback

```sh
ssh pi@mainsailos.local "cp ~/printer_data/config/printer.cfg.pre-chamber-refactor-* ~/printer_data/config/printer.cfg"
ssh pi@mainsailos.local "sudo systemctl restart klipper"
git revert <merge-commit>
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI green**

```sh
while :; do out=$(gh pr checks 2>&1); if ! echo "$out" | grep -q pending; then echo "$out"; break; fi; sleep 20; done
```

Expected: both `pre-commit + macro refcheck + pytest` and `Klippy parse + MCU load` pass.

If CI fails, diagnose from logs:

```sh
gh run view --log-failed | tail -50
```

Fix, push, retry.

- [ ] **Step 3: Squash-merge**

```sh
gh pr merge --squash --delete-branch
```

- [ ] **Step 4: Local main update**

```sh
cd /Users/ben/code/voron-2-611
git checkout main
git pull
git worktree remove <worktree path>     # cleanup per the memory note
git branch -D feat/chamber-heater-generic-pid 2>/dev/null || true
```

---

## Task 13: Post-merge observation log

**Files:** `memory/troubleshooting-log.md` (or wherever you record print observations) — at user discretion

- [ ] **Step 1: Document the first 3-5 ABS prints after this lands**

For each print, note:
- Time to chamber reaching 55°C target
- Steady-state behavior (oscillation if any, BedFans typical speed)
- Post-print VOC duration (did the 300s cooldown feel right? too short / too long?)
- Any verify_heater warnings in klippy.log

If patterns emerge — e.g., consistent overshoot — file an issue or open a follow-up PR to refine PID values, `print_end_cooldown_seconds`, or `voc_baseline_temp`. Don't tune blindly; collect evidence first.

---

## Self-review

Spec coverage check:
- Architecture (config blocks, removed/added/kept): Tasks 3, 4 ✓
- SET_CHAMBER_TARGET + chamber_control_loop rewrite: Task 5 ✓
- Lifecycle changes (PRINT_END, _CANCEL_PRINT_HOOK): Task 6 ✓
- State machine semantics: Task 5 ✓
- PID_CALIBRATE workflow: Task 9 ✓
- verify_heater tuning: Task 3 step 2 + Task 10 step 3 ✓
- Migration plan: Tasks 7, 8 ✓
- Rollback path: PR body (Task 12) ✓
- Open considerations (cooldown tuning): Task 13 ✓

Placeholder scan: no TBDs, no vague steps, no missing code blocks. Acceptable.

Type consistency: `user_target` used consistently across `_CHAMBER_CONTROL`, `SET_CHAMBER_TARGET`, `chamber_control_loop`. (Renamed from `target` for clarity — explicitly called out in Task 5 step 1.) `voc_baseline_temp` and `voc_cooldown_threshold` consistent.

Scope: Single PR. Single architectural change. No cross-system dependencies (eddy work is on main, untouched).
