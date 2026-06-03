# VEFACH Exhaust-Driven Cooldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At end of print, turn the chamber heater off and run the VEFACH carbon exhaust for the cooldown window — decoupling VOC evacuation from chamber heating now that carbon is installed on the `chamber_exhaust` fan.

**Architecture:** Config-only macro change. `PRINT_END` and `_CANCEL_PRINT_HOOK` gate on `_CHAMBER_CONTROL.active_target > 0` (the existing VOC proxy), turn `[heater_generic chamber]` off, and start `[fan_generic chamber_exhaust]` (`z:P2.7`) at a new `chamber_exhaust_cooldown_speed`. The existing `_PRINT_END_CLEANUP` `G4` dwell is the exhaust runtime; its `OFF` stops the fan. No new control-flow, no MCU/pin changes.

**Tech Stack:** Klipper `gcode_macro` (Jinja2), the repo's `_USER_VARIABLE` single-source-of-truth pattern, pytest structural assertions (`tests/test_config_structure.py`), `scripts/macro_refcheck.py`.

**Spec:** `docs/superpowers/specs/2026-06-03-vefach-exhaust-cooldown-decouple.md` (closes #117).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/macros/_user_variables.cfg` | Tunable single-source-of-truth | Add `chamber_exhaust_cooldown_speed`; update `print_end_cooldown_seconds` + header comments |
| `config/macros/print_start.cfg` | `PRINT_END` lifecycle | Capture chamber target, turn chamber heater off, start exhaust for chamber prints |
| `config/client_hooks.cfg` | `_CANCEL_PRINT_HOOK` cancel parity | Start exhaust (not re-assert heater) for chamber prints |
| `config/bed.cfg` | `[fan_generic chamber_exhaust]` definition | Comment-only: now has an automated caller |
| `config/macros/chamber_control.cfg` | `SET_CHAMBER_TARGET` / `_CHAMBER_CONTROL` | Comment-only: cooldown VOC is now exhaust-driven |

**Restart impact:** `RESTART` only (macro/gcode_macro/comment changes; the `chamber_exhaust` pin already exists). Flag this to Ben at deploy time.

**Pre-flight (run once before Task 1):**

- [ ] Confirm a clean baseline. Run: `make test-py`
  Expected: PASS (refcheck + pytest + pre-commit all green) on the current branch before any edit.

---

### Task 1: PRINT_END runs the carbon exhaust for chamber prints

This task is the core behavior change. It adds the `_USER_VARIABLE` reference (in `PRINT_END`) and the matching definition together, because `tests/test_config_structure.py` enforces ref↔def consistency in both directions.

**Files:**
- Modify: `config/macros/print_start.cfg:203-228` (`PRINT_END`)
- Modify: `config/macros/_user_variables.cfg:45-47` (add variable)
- Test: `tests/test_config_structure.py` (existing `test_user_variable_refs_resolve`, `test_user_variable_definitions_used`)

- [ ] **Step 1: Edit `PRINT_END` to capture the chamber target, turn the chamber heater off, and start the exhaust.**

In `config/macros/print_start.cfg`, replace the `PRINT_END` body. The current body (lines 205-228) is:

```
gcode:
  M400                                                   # flush move buffer
  G92 E0                                                 # zero extruder
  G91                                                    # relative
  G1 E-2 F2700                                           # small retract — clean nozzle disengage
  G1 Z10 F3000                                           # lift 10mm
  G90                                                    # absolute
  G1 X{printer.toolhead.axis_minimum.x + 10} Y{printer.toolhead.axis_maximum.y - 15} F6000   # park rear-left, inset (10, 340) on this build
  G1 Z1 F600                                             # descend to Z=1 so bed catches the gantry on motors-off sag — limits sag depth to (1mm + whatever the nozzle compresses PEI). Park spot at (10, 340) is in skirt area, so PEI wear here doesn't affect print area.
  M104 S0                                                # hotend heater off
  M140 S0                                                # bed heater off
  M107                                                   # part fan off
  # Cooldown VOC capture: bed + hotend off above, but [heater_generic chamber]
  # is INTENTIONALLY left at the print's chamber target (set in step 13). With
  # the bed heater now off, the bed's large residual mass keeps the chamber
  # reachable at that target for the few minutes that matter — so the PID holds
  # BedFans at the same moderate speed they ran during the print (NOT pinned at
  # 100% chasing an unreachable lower baseline), circulating air through the
  # under-bed carbon filter while off-gassing is highest. _PRINT_END_CLEANUP's
  # OFF zeroes the chamber after the G4, stopping BedFans. For PLA/PETG the
  # print target is 0, so there's no cooldown circulation — correct, since
  # chamber-target>0 is the VOC proxy (low-temp materials off-gas little).
  # Spec: docs/superpowers/specs/2026-05-28-chamber-cooldown-hold-target.md
  _PRINT_END_CLEANUP
```

Replace it with:

```
gcode:
  # Capture the print's chamber target NOW, at macro entry. The whole template
  # renders once before any gcode runs, so this binds to active_target BEFORE
  # the SET_CHAMBER_TARGET TARGET=0 below zeroes it — the {% if %} gate then
  # sees the real print target. (Render-once Jinja working in our favour; see
  # CLAUDE.md "Klipper gotchas".)
  {% set chamber_target = printer["gcode_macro _CHAMBER_CONTROL"].active_target|float %}
  M400                                                   # flush move buffer
  G92 E0                                                 # zero extruder
  G91                                                    # relative
  G1 E-2 F2700                                           # small retract — clean nozzle disengage
  G1 Z10 F3000                                           # lift 10mm
  G90                                                    # absolute
  G1 X{printer.toolhead.axis_minimum.x + 10} Y{printer.toolhead.axis_maximum.y - 15} F6000   # park rear-left, inset (10, 340) on this build
  G1 Z1 F600                                             # descend to Z=1 so bed catches the gantry on motors-off sag — limits sag depth to (1mm + whatever the nozzle compresses PEI). Park spot at (10, 340) is in skirt area, so PEI wear here doesn't affect print area.
  M104 S0                                                # hotend heater off
  M140 S0                                                # bed heater off
  SET_CHAMBER_TARGET TARGET=0                            # chamber heater (BedFans) off — no more hold-target; VEFACH owns cooldown now
  M107                                                   # part fan off
  # Cooldown / VOC evacuation (VEFACH). bed + hotend + chamber heater off above.
  # For chamber (VOC) prints, run the VEFACH carbon exhaust (chamber_exhaust,
  # z:P2.7) for the cooldown window: active cooling + VOC evacuation to room,
  # decoupled from the BedFans. chamber_target was captured at macro entry.
  # _PRINT_END_CLEANUP's G4 is the runtime; its OFF stops the fan. PLA/PETG
  # (target 0) skip it — chamber-target>0 is the VOC proxy.
  # Spec: docs/superpowers/specs/2026-06-03-vefach-exhaust-cooldown-decouple.md
  {% if chamber_target > 0 %}
    SET_FAN_SPEED FAN=chamber_exhaust SPEED={printer["gcode_macro _USER_VARIABLE"].chamber_exhaust_cooldown_speed}
  {% endif %}
  _PRINT_END_CLEANUP
```

- [ ] **Step 2: Run the structural test to verify it FAILS (ref without def).**

Run: `.venv/bin/pytest tests/test_config_structure.py::test_user_variable_refs_resolve -v`
Expected: FAIL — `_USER_VARIABLE refs without matching variable_X: ['chamber_exhaust_cooldown_speed']`

(If `.venv` is missing, run `make venv` first.)

- [ ] **Step 3: Add the `chamber_exhaust_cooldown_speed` variable definition.**

In `config/macros/_user_variables.cfg`, find the `print_end_cooldown_seconds` line (currently line 47):

```
variable_print_end_cooldown_seconds: 300      # post-print cooldown G4 — chamber heater holds the print's target (BedFans circulate through the under-bed carbon filter) before OFF zeroes everything
```

Replace that single line with these two lines (updates the stale comment + adds the new var):

```
variable_print_end_cooldown_seconds: 300      # post-print cooldown G4 — runtime of the VEFACH carbon exhaust (chamber prints) before OFF zeroes everything
variable_chamber_exhaust_cooldown_speed: 1.0  # VEFACH carbon exhaust (chamber_exhaust, z:P2.7) speed during the end-of-print cooldown; 0.0–1.0, full = max air exchange
```

- [ ] **Step 4: Run the structural tests to verify they PASS.**

Run: `.venv/bin/pytest tests/test_config_structure.py -v -k user_variable`
Expected: PASS — `test_user_variable_refs_resolve` and `test_user_variable_definitions_used` both green (the new var is now defined and referenced).

- [ ] **Step 5: Run macro_refcheck to verify the macro call graph still resolves.**

Run: `make refcheck`
Expected: PASS — no unresolved macro references. (`SET_FAN_SPEED FAN=chamber_exhaust` already appears in the `OFF` macro, so this pattern is known-good.)

- [ ] **Step 6: Commit.**

```bash
git add config/macros/print_start.cfg config/macros/_user_variables.cfg
git commit -m "feat: PRINT_END runs VEFACH carbon exhaust for chamber-print cooldown

Turn the chamber heater off at PRINT_END and run chamber_exhaust for the
cooldown window instead of holding the print's chamber target to keep
BedFans recirculating. Gated on the chamber-target>0 VOC proxy via
_CHAMBER_CONTROL.active_target. Adds chamber_exhaust_cooldown_speed.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Cancel parity — _CANCEL_PRINT_HOOK runs the exhaust

**Files:**
- Modify: `config/client_hooks.cfg:55-74` (`_CANCEL_PRINT_HOOK`)

- [ ] **Step 1: Replace the chamber re-assert block with an exhaust start.**

In `config/client_hooks.cfg`, the current `_CANCEL_PRINT_HOOK` (lines 55-74) has this `description:` and body opening:

```
[gcode_macro _CANCEL_PRINT_HOOK]
description: Runs when CANCEL_PRINT fires mid-print, AFTER upstream commands heaters off but BEFORE base cancel. Re-asserts the print's chamber target for cooldown VOC, calls MMU_END UNLOAD=1 (HH re-heats extruder as needed and unloads filament) then defers to _PRINT_END_CLEANUP for cooldown + OFF + _RESETSPEEDS. Total cancel runtime is ~1–2 min; trades speed for a clean-printer state.
gcode:
  # Upstream CANCEL_PRINT already called TURN_OFF_HEATERS before this hook, so
  # the bed, hotend, and [heater_generic chamber] (BedFans) are all off. Re-
  # assert the print's chamber target (recorded in _CHAMBER_CONTROL) so cancel
  # gets the same cooldown VOC circulation as a normal PRINT_END: the bed's
  # residual heat keeps it reachable through MMU_END + the cleanup G4, and
  # _PRINT_END_CLEANUP's OFF zeroes it at the end. Skipped if no chamber target
  # was active (e.g. PLA), matching PRINT_END's PLA behavior.
  {% set active_target = printer["gcode_macro _CHAMBER_CONTROL"].active_target|float %}
  {% if active_target > 0 %}
    SET_CHAMBER_TARGET TARGET={active_target}
  {% endif %}
```

Replace the `description:` line and that whole comment+`{% if %}` block with:

```
[gcode_macro _CANCEL_PRINT_HOOK]
description: Runs when CANCEL_PRINT fires mid-print, AFTER upstream commands heaters off but BEFORE base cancel. Starts the VEFACH carbon exhaust for cooldown VOC (chamber prints), calls MMU_END UNLOAD=1 (HH re-heats extruder as needed and unloads filament) then defers to _PRINT_END_CLEANUP for cooldown + OFF + _RESETSPEEDS. Total cancel runtime is ~1–2 min; trades speed for a clean-printer state.
gcode:
  # Upstream CANCEL_PRINT already called TURN_OFF_HEATERS before this hook, so
  # the bed, hotend, and [heater_generic chamber] (BedFans) are all off. For a
  # chamber (VOC) print, start the VEFACH carbon exhaust so cancel gets the same
  # cooldown VOC evacuation as a normal PRINT_END; _PRINT_END_CLEANUP's OFF stops
  # the fan at the end. active_target (recorded in _CHAMBER_CONTROL) is untouched
  # by TURN_OFF_HEATERS, so it still reflects the print's target here. Skipped if
  # no chamber target was active (e.g. PLA), matching PRINT_END's PLA behavior.
  {% set active_target = printer["gcode_macro _CHAMBER_CONTROL"].active_target|float %}
  {% if active_target > 0 %}
    SET_FAN_SPEED FAN=chamber_exhaust SPEED={printer["gcode_macro _USER_VARIABLE"].chamber_exhaust_cooldown_speed}
  {% endif %}
```

Leave the rest of the macro (`MMU_END UNLOAD=1` and `_PRINT_END_CLEANUP`) unchanged.

- [ ] **Step 2: Run refcheck + structural tests.**

Run: `make refcheck`
Expected: PASS — no unresolved macro references.

Run: `.venv/bin/pytest tests/test_config_structure.py -v -k user_variable`
Expected: PASS — the new var now has a second resolved reference; still no orphans.

- [ ] **Step 3: Commit.**

```bash
git add config/client_hooks.cfg
git commit -m "feat: cancel-mid-print runs VEFACH exhaust for cooldown parity

_CANCEL_PRINT_HOOK starts chamber_exhaust (chamber prints) instead of
re-asserting the chamber heater target, matching the new PRINT_END
cooldown path. Upstream already turned the chamber heater off.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Comment/doc sync (no behavior change)

Update the stale comments that still describe cooldown VOC as "BedFans hold the chamber target." Pure documentation — no gcode changes.

**Files:**
- Modify: `config/bed.cfg:13-14`, `config/bed.cfg:82-85`
- Modify: `config/macros/chamber_control.cfg:11-16`
- Modify: `config/macros/_user_variables.cfg:33-36` (header comment)

- [ ] **Step 1: Update `bed.cfg` header docstring for `chamber_exhaust`.**

In `config/bed.cfg`, replace lines 13-14:

```
## - [fan_generic chamber_exhaust] Chamber exhaust on z:P2.7. Manual control
##                                 only; no automated controller.
```

with:

```
## - [fan_generic chamber_exhaust] VEFACH carbon exhaust on z:P2.7. Run by
##                                 PRINT_END / _CANCEL_PRINT_HOOK for the end-of-
##                                 print cooldown (active cooling + VOC evac).
##                                 Also manual via SET_FAN_SPEED.
```

- [ ] **Step 2: Update the `[fan_generic chamber_exhaust]` block comment in `bed.cfg`.**

In `config/bed.cfg`, replace lines 82-85:

```
# Chamber exhaust fan is now a plain [fan_generic] — no automated controller.
# Available for manual SET_FAN_SPEED FAN=chamber_exhaust SPEED=N from macros
# or console. We rely on BedFans driving VOC capture through the under-bed
# filter instead of exhausting to the room.
```

with:

```
# Chamber exhaust fan: VEFACH carbon filter, exhaust-to-room. Run automatically
# by PRINT_END / _CANCEL_PRINT_HOOK for the end-of-print cooldown window (active
# cooling + VOC evacuation), decoupled from the BedFans (which own chamber
# heating + in-print VOC recirc through the under-bed filter). Also available for
# manual SET_FAN_SPEED FAN=chamber_exhaust SPEED=N.
# Spec: docs/superpowers/specs/2026-06-03-vefach-exhaust-cooldown-decouple.md
```

- [ ] **Step 3: Update the `chamber_control.cfg` header block.**

In `config/macros/chamber_control.cfg`, replace lines 11-16:

```
#   VOC capture during cooldown is handled by PRINT_END holding the print's
#   own chamber target through the cooldown G4 (see print_start.cfg). On a
#   mid-print CANCEL, upstream CANCEL_PRINT zeroes all heaters before our hook
#   runs, so _CANCEL_PRINT_HOOK re-asserts the recorded target to get the same
#   cooldown circulation. Spec:
#   docs/superpowers/specs/2026-05-28-chamber-cooldown-hold-target.md
```

with:

```
#   VOC evacuation during cooldown is handled by PRINT_END turning the chamber
#   heater off and running the VEFACH carbon exhaust (chamber_exhaust, z:P2.7)
#   for the cooldown window — decoupled from the BedFans. active_target lets
#   PRINT_END / _CANCEL_PRINT_HOOK gate the exhaust on "was this a chamber (VOC)
#   print." Spec:
#   docs/superpowers/specs/2026-06-03-vefach-exhaust-cooldown-decouple.md
```

- [ ] **Step 4: Update the `_user_variables.cfg` chamber header comment.**

In `config/macros/_user_variables.cfg`, replace lines 33-36:

```
# Chamber control ([heater_generic chamber] in bed.cfg owns BedFans PWM via PID;
# chamber_control.cfg's SET_CHAMBER_TARGET clamps + sets the heater. VOC cooldown
# = PRINT_END holds the print's chamber target for the cooldown G4 — see
# docs/superpowers/specs/2026-05-28-chamber-cooldown-hold-target.md)
```

with:

```
# Chamber control ([heater_generic chamber] in bed.cfg owns BedFans PWM via PID;
# chamber_control.cfg's SET_CHAMBER_TARGET clamps + sets the heater. VOC cooldown
# = PRINT_END turns the chamber heater off and runs the VEFACH carbon exhaust —
# see docs/superpowers/specs/2026-06-03-vefach-exhaust-cooldown-decouple.md)
```

- [ ] **Step 5: Run the full macOS test subset.**

Run: `make test-py`
Expected: PASS — refcheck + pytest (incl. `test_config_structure.py`) + pre-commit all green.

- [ ] **Step 6: Commit.**

```bash
git add config/bed.cfg config/macros/chamber_control.cfg config/macros/_user_variables.cfg
git commit -m "docs: sync chamber-exhaust/cooldown comments to VEFACH design

Update bed.cfg, chamber_control.cfg, and _user_variables.cfg comments
that still described cooldown VOC as 'BedFans hold the chamber target'.
No behavior change.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Pre-PR review + verification

**Files:** none (review only)

- [ ] **Step 1: Run the full local gate one more time.**

Run: `make test-py`
Expected: PASS.

- [ ] **Step 2: Eyeball the rendered diff for the render-once gate.**

Run: `git diff main -- config/macros/print_start.cfg`
Confirm: the `{% set chamber_target = ... %}` line sits ABOVE `SET_CHAMBER_TARGET TARGET=0`, and the `{% if chamber_target > 0 %}` exhaust line sits BELOW it. (If `SET_CHAMBER_TARGET TARGET=0` rendered before the capture, the gate would always see 0 — but Jinja renders the whole template first, so order in the file is what matters for readability, not correctness. Verify visually anyway.)

- [ ] **Step 3: Domain + general review before pushing.**

Per CLAUDE.md, run the Klipper-domain reviewer and the PR-review toolkit on the diff BEFORE pushing:
- Dispatch the `klipper-cfg-reviewer` agent on the diff vs `main`.
- Invoke `Skill: pr-review-toolkit:review-pr`.

Address any P1/P2 findings as fixup commits.

- [ ] **Step 4: Note the deploy requirements for Ben.**

When this merges, `/deploy-to-pi` then a **`RESTART`** (not `FIRMWARE_RESTART`) applies it. First post-deploy smoke (manual): start a short ABS/chamber print (or `SET_CHAMBER_TARGET TARGET=40` then `PRINT_END`), confirm at PRINT_END the BedFans stop, `chamber_exhaust` spins at full, chamber temp falls, and the fan stops after the cooldown dwell. Confirm a PLA print (`CHAMBER=0`) starts no exhaust, and a mid-ABS `CANCEL_PRINT` starts the exhaust.

---

## Self-Review

**Spec coverage:**
- "During a print — unchanged" → no task touches heating; verified (only PRINT_END/cancel tails change). ✓
- "At print end — chamber heater off + exhaust" → Task 1. ✓
- Fixed-timer termination (reuse `print_end_cooldown_seconds`) → Task 1 Step 3 keeps the existing `G4`; comment updated. ✓
- Gate on `chamber > 0` via `active_target` → Task 1 (PRINT_END) + Task 2 (cancel). ✓
- New `chamber_exhaust_cooldown_speed: 1.0` → Task 1 Step 3. ✓
- `SET_CHAMBER_TARGET TARGET=0` to stop BedFans → Task 1 Step 1. ✓
- Cancel parity → Task 2. ✓
- Comment updates in `bed.cfg` + `chamber_control.cfg` → Task 3. ✓
- `_PRINT_END_CLEANUP` unchanged (its `OFF` is the fan backstop) → no task touches it; relied upon. ✓
- Restart impact = RESTART → noted in File Structure + Task 4 Step 4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete before/after text; exact commands with expected output. ✓

**Type/name consistency:** Variable is `chamber_exhaust_cooldown_speed` in every reference (Task 1 PRINT_END, Task 2 cancel hook) and its definition (Task 1 Step 3). Fan name `chamber_exhaust` and macro `SET_CHAMBER_TARGET` / `SET_FAN_SPEED` match the existing `OFF` macro usage. `_CHAMBER_CONTROL.active_target` matches the existing recorded variable. ✓
