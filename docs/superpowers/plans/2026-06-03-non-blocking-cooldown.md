# Non-blocking End-of-Print Cooldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the post-print cooldown non-blocking — turn everything off immediately at print-end except the chamber exhaust, and stop the exhaust via a `delayed_gcode` after `print_end_cooldown_seconds`, so the printer returns to idle at once (fast cancel).

**Architecture:** Replace the blocking `G4` in `_PRINT_END_CLEANUP` with `UPDATE_DELAYED_GCODE`. Extract `_OFF_EXCEPT_EXHAUST` (the `OFF` body minus the exhaust line) so cleanup can turn everything off but leave the exhaust running. A new `[delayed_gcode _COOLDOWN_EXHAUST_OFF]` is the single deferred action. The `in_cleanup` re-entry guard is removed (obsolete with no blocking window); `PRINT_START` gains a guard that cancels a stale timer + stops a lingering exhaust.

**Tech Stack:** Klipper `gcode_macro` / `delayed_gcode` (Jinja2 + gcode), `UPDATE_DELAYED_GCODE` builtin, the repo's `_USER_VARIABLE` pattern, `scripts/macro_refcheck.py`, pytest (`tests/test_config_structure.py`).

**Spec:** `docs/superpowers/specs/2026-06-03-non-blocking-cooldown-design.md` (closes #126).

---

## File Structure

| File | Change |
|---|---|
| `config/macros/print_start.cfg` | Add `[delayed_gcode _COOLDOWN_EXHAUST_OFF]`; rewrite `_PRINT_END_CLEANUP` (non-blocking, no guard); update `PRINT_START` step-4 guard |
| `config/macros/macros.cfg` | Add `_OFF_EXCEPT_EXHAUST`; refactor `OFF` to reuse it + cancel the timer |
| `config/macros/_user_variables.cfg` | Update `print_end_cooldown_seconds` comment (delayed-gcode duration, not a G4) |

**Restart impact:** `RESTART`. **Note for the engineer:** `delayed_gcode` `DURATION` is in **seconds**; the old `G4 P` was in **milliseconds** — do NOT multiply by 1000. Local gate is `make test-py` (refcheck + structural pytest + pre-commit); klippy parse (L3) is CI-only.

**Pre-flight:**
- [ ] Confirm clean baseline. Run: `make test-py` → expect PASS on the current branch before editing.
- [ ] Confirm nothing else references the guard variable. Run: `grep -rn "in_cleanup" config/` → expect only `config/macros/print_start.cfg` (the two sites this plan edits). If anything else appears, STOP and report.

---

### Task 1: Add the deferred exhaust-stop timer

**Files:**
- Modify: `config/macros/print_start.cfg` (add a new `[delayed_gcode]` after the `_PRINT_END_CLEANUP` macro)

- [ ] **Step 1: Add the `[delayed_gcode _COOLDOWN_EXHAUST_OFF]` section.**

In `config/macros/print_start.cfg`, the file currently ends with `_PRINT_END_CLEANUP` (its `{% endif %}` is the last line, ~line 256). Append this new section at the end of the file:

```
[delayed_gcode _COOLDOWN_EXHAUST_OFF]
# Non-blocking cooldown: stops the VEFACH chamber exhaust after the cooldown
# window. Armed by _PRINT_END_CLEANUP via UPDATE_DELAYED_GCODE; cancelled by
# OFF and by PRINT_START. No initial_duration — must never fire at boot.
gcode:
  SET_FAN_SPEED FAN=chamber_exhaust SPEED=0
```

- [ ] **Step 2: Verify refcheck + parse-safety.**

Run: `make refcheck`
Expected: PASS — no unresolved references. (`SET_FAN_SPEED FAN=chamber_exhaust` is the known-good pattern from `OFF`.)

- [ ] **Step 3: Commit.**

```bash
git add config/macros/print_start.cfg
git commit -m "feat: add _COOLDOWN_EXHAUST_OFF delayed_gcode (#126)

The single deferred action for the non-blocking cooldown: stop the
chamber exhaust after the cooldown window. Wired up in following commits.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Extract `_OFF_EXCEPT_EXHAUST` and refactor `OFF`

**Files:**
- Modify: `config/macros/macros.cfg:43-51` (the `OFF` macro)

- [ ] **Step 1: Replace the `OFF` macro with `_OFF_EXCEPT_EXHAUST` + a slimmed `OFF`.**

The current `OFF` macro (lines 43-51) is exactly:

```
[gcode_macro OFF]
description: Shut everything off (steppers, heaters, part fan, chamber exhaust, case light).
gcode:
    M84                                  ; turn steppers off
    TURN_OFF_HEATERS                     ; turn bed / hotend / chamber heater (BedFans) off
    SET_GCODE_VARIABLE MACRO=_CHAMBER_CONTROL VARIABLE=active_target VALUE=0   ; clear recorded chamber target
    M107                                 ; turn print cooling fan off
    SET_FAN_SPEED FAN=chamber_exhaust SPEED=0   ; exhaust fan off — also stops the PRINT_END / _CANCEL_PRINT_HOOK cooldown run
    CASELIGHT_OFF                        ; turn case light off
```

Replace those 9 lines with:

```
[gcode_macro _OFF_EXCEPT_EXHAUST]
description: Internal helper: the OFF sequence MINUS the chamber exhaust, so the non-blocking cooldown can leave the exhaust running. Don't call directly — use OFF.
gcode:
    M84                                  ; turn steppers off
    TURN_OFF_HEATERS                     ; turn bed / hotend / chamber heater (BedFans) off
    SET_GCODE_VARIABLE MACRO=_CHAMBER_CONTROL VARIABLE=active_target VALUE=0   ; clear recorded chamber target
    M107                                 ; turn print cooling fan off
    CASELIGHT_OFF                        ; turn case light off

[gcode_macro OFF]
description: Shut everything off (steppers, heaters, part fan, chamber exhaust, case light).
gcode:
    _OFF_EXCEPT_EXHAUST
    SET_FAN_SPEED FAN=chamber_exhaust SPEED=0                    ; exhaust fan off
    UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF DURATION=0     ; cancel any pending cooldown stop (manual OFF mid-cooldown leaves no orphan timer)
```

- [ ] **Step 2: Run refcheck.**

Run: `make refcheck`
Expected: PASS — `_OFF_EXCEPT_EXHAUST` resolves (now defined), `OFF` resolves it, and the `_COOLDOWN_EXHAUST_OFF` id exists (Task 1).

- [ ] **Step 3: Commit.**

```bash
git add config/macros/macros.cfg
git commit -m "refactor: extract _OFF_EXCEPT_EXHAUST; OFF cancels cooldown timer (#126)

Split the OFF body so the cooldown path can turn everything off but
leave the chamber exhaust running. OFF == _OFF_EXCEPT_EXHAUST + exhaust
off + cancel the pending _COOLDOWN_EXHAUST_OFF timer. Net OFF behavior
unchanged plus the timer cancel.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Make `_PRINT_END_CLEANUP` non-blocking and update the `PRINT_START` guard

These two edits are coupled: removing `variable_in_cleanup` from `_PRINT_END_CLEANUP` requires removing the `SET_GCODE_VARIABLE ... in_cleanup` line in `PRINT_START`, or Klipper errors at runtime. Do both in one task.

**Files:**
- Modify: `config/macros/print_start.cfg:237-256` (`_PRINT_END_CLEANUP`)
- Modify: `config/macros/print_start.cfg:58-61` (`PRINT_START` step 4)

- [ ] **Step 1: Rewrite `_PRINT_END_CLEANUP`.**

The current macro (lines 237-256) is exactly:

```
[gcode_macro _PRINT_END_CLEANUP]
description: Shared cleanup tail — bed mesh clear, cooldown delay, OFF, reset speeds. Called by PRINT_END (after its retract/park/heaters-off) and by upstream CANCEL_PRINT via _CLIENT_VARIABLE.user_cancel_macro. Guarded against re-entry so a cancel-during-cooldown-G4 doesn't trigger a second 5-minute G4.
variable_in_cleanup: 0
gcode:
  {% set in_cleanup = printer["gcode_macro _PRINT_END_CLEANUP"].in_cleanup %}
  {% if in_cleanup %}
    # Re-entered while a prior cleanup is still in its G4. Skip — the
    # outer cleanup will complete the OFF + _RESETSPEEDS path. Without
    # this guard, cancel-during-G4 → _CANCEL_PRINT_HOOK → _PRINT_END_CLEANUP
    # would queue a second 5-minute G4 behind the first.
    RESPOND TYPE=echo MSG="_PRINT_END_CLEANUP already running; skipping re-entry"
  {% else %}
    SET_GCODE_VARIABLE MACRO=_PRINT_END_CLEANUP VARIABLE=in_cleanup VALUE=1
    BED_MESH_CLEAR
    {% set cooldown_ms = printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds|int * 1000 %}
    G4 P{cooldown_ms}
    OFF
    _RESETSPEEDS
    SET_GCODE_VARIABLE MACRO=_PRINT_END_CLEANUP VARIABLE=in_cleanup VALUE=0
  {% endif %}
```

Replace the entire macro with:

```
[gcode_macro _PRINT_END_CLEANUP]
description: Shared cleanup tail — bed mesh clear, off-except-exhaust, reset speeds, then arm the non-blocking cooldown that stops the chamber exhaust after print_end_cooldown_seconds. Called by PRINT_END (after its retract/park/heaters-off) and by upstream CANCEL_PRINT via _CLIENT_VARIABLE.user_cancel_macro. Returns immediately — the printer is idle during the cooldown.
gcode:
  BED_MESH_CLEAR
  # Turn everything off NOW except the chamber exhaust, which PRINT_END /
  # _CANCEL_PRINT_HOOK left running for chamber (VOC) prints. The printer is
  # idle the instant this returns — no blocking G4. (Lights + motors off here,
  # not after the cooldown.)
  _OFF_EXCEPT_EXHAUST
  _RESETSPEEDS
  # Non-blocking cooldown: stop the exhaust after the window via delayed_gcode.
  # DURATION is in SECONDS (the old G4 P was milliseconds). For PLA (no exhaust
  # running) the deferred SET_FAN_SPEED=0 is a harmless no-op. A re-entry (e.g.
  # cancel landing here twice) just re-arms the single timer — idempotent, which
  # is why the old in_cleanup guard is gone.
  UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF DURATION={printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds|int}
```

- [ ] **Step 2: Update `PRINT_START` step 4.**

In `config/macros/print_start.cfg`, the current step-4 guard (lines 58-61) is exactly:

```
  # Reset cleanup re-entry guard. If a prior _PRINT_END_CLEANUP errored mid-G4
  # the guard would be stuck at 1; clearing it here ensures the next PRINT_END
  # runs cleanup normally. Cheaper than chasing every error-path manually.
  SET_GCODE_VARIABLE MACRO=_PRINT_END_CLEANUP VARIABLE=in_cleanup VALUE=0
```

Replace those 4 lines with:

```
  # Cancel any pending cooldown from a previous print and stop its lingering
  # exhaust, so a prior cooldown can't fire mid-print or vent this print's
  # chamber heat-up. (Replaces the old in_cleanup guard reset, now obsolete.)
  UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF DURATION=0
  SET_FAN_SPEED FAN=chamber_exhaust SPEED=0
```

- [ ] **Step 3: Verify the guard variable is fully gone.**

Run: `grep -rn "in_cleanup" config/`
Expected: NO output (every reference removed). If any remain, fix them before continuing.

- [ ] **Step 4: Run the full local gate.**

Run: `make test-py`
Expected: PASS — refcheck + pytest (incl. `test_config_structure.py`; `print_end_cooldown_seconds` is still referenced via the `UPDATE_DELAYED_GCODE DURATION`, so `test_user_variable_definitions_used` stays green) + pre-commit.

- [ ] **Step 5: Commit.**

```bash
git add config/macros/print_start.cfg
git commit -m "feat: non-blocking cooldown via delayed_gcode; drop in_cleanup guard (#126)

_PRINT_END_CLEANUP now turns everything off except the exhaust and arms
_COOLDOWN_EXHAUST_OFF (seconds, not ms) instead of blocking on G4 — the
printer returns to idle immediately, so cancel is fast. PRINT_START
cancels a stale timer + stops a lingering exhaust. The in_cleanup
re-entry guard is removed (obsolete with no blocking window).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Refresh the `print_end_cooldown_seconds` comment + final verification

**Files:**
- Modify: `config/macros/_user_variables.cfg` (the `print_end_cooldown_seconds` line)

- [ ] **Step 1: Update the inline comment.**

In `config/macros/_user_variables.cfg`, find this exact current line:

```
variable_print_end_cooldown_seconds: 900      # post-print cooldown G4; also the VEFACH exhaust runtime on chamber prints. 15 min: the carbon+HEPA stack flows little air through the stock axial exhaust fan, so VOC clearance needs time, not speed (speed pinned at 1.0). NB: this is a BLOCKING dwell — holds the printer busy the whole time; see #126 to make it interruptible.
```

Replace it with (drops the now-false "BLOCKING dwell" note; it's a non-blocking delayed-gcode duration now):

```
variable_print_end_cooldown_seconds: 900      # VEFACH exhaust runtime on chamber prints (seconds; armed as a non-blocking delayed_gcode, so the printer is idle during it). 15 min: the carbon+HEPA stack flows little air through the stock axial exhaust fan, so VOC clearance needs time, not speed (speed pinned at 1.0).
```

- [ ] **Step 2: Run the full local gate.**

Run: `make test-py`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add config/macros/_user_variables.cfg
git commit -m "docs: print_end_cooldown_seconds is a non-blocking duration now (#126)

Drop the stale 'BLOCKING dwell' note; it's a delayed_gcode duration in
seconds and the printer is idle during the cooldown.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Pre-PR review.**

Per CLAUDE.md, before pushing:
- Dispatch the `klipper-cfg-reviewer` agent on `git diff main -- config/` (focus: delayed_gcode correctness, DURATION-seconds-vs-G4-ms, the `_OFF_EXCEPT_EXHAUST`/`OFF` refactor, removal of `in_cleanup`, the PRINT_START guard, RESTART classification, refs resolve).
- Run `Skill: pr-review-toolkit:review-pr`.
Address findings as fixup commits.

- [ ] **Step 5: Deploy note for Ben.**

On merge: `/deploy-to-pi` then **`RESTART`**. Smoke (manual): finish a chamber print → printer idle immediately (no 15-min busy), motors/lights off, `chamber_exhaust` keeps running, stops ~15 min later. `CANCEL_PRINT` mid-chamber-print → returns after the MMU unload (~1–2 min), exhaust runs in background. New print during the window → exhaust stops before heating. PLA → no exhaust, idle immediately.

---

## Self-Review

**Spec coverage:**
- `[delayed_gcode _COOLDOWN_EXHAUST_OFF]` → Task 1. ✓
- `_OFF_EXCEPT_EXHAUST` + `OFF` refactor (+ timer cancel) → Task 2. ✓
- `_PRINT_END_CLEANUP` non-blocking, drop `G4`/`OFF`/`in_cleanup` guard → Task 3 Step 1. ✓
- `PRINT_START` step-4 guard (cancel timer + stop exhaust) → Task 3 Step 2. ✓
- `print_end_cooldown_seconds` comment refresh → Task 4. ✓
- DURATION-in-seconds correctness → called out in File Structure note + Task 3 comment. ✓
- Restart = RESTART → File Structure + Task 4 Step 5. ✓

**Placeholder scan:** No TBD/TODO; every edit shows complete before/after text; exact commands + expected output. ✓

**Name consistency:** `_COOLDOWN_EXHAUST_OFF` (delayed_gcode id), `_OFF_EXCEPT_EXHAUST` (macro), `print_end_cooldown_seconds` (var), `chamber_exhaust` (fan) — identical across Tasks 1–4 and matched to the spec. The `UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF` id in OFF (Task 2), `_PRINT_END_CLEANUP` (Task 3), and PRINT_START (Task 3) all match the section name defined in Task 1. ✓
