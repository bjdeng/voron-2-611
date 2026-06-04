# Non-blocking end-of-print cooldown (2026-06-03)

Closes [#126](https://github.com/bjdeng/voron-2-611/issues/126). Builds on the
VEFACH exhaust cooldown (`2026-06-03-vefach-exhaust-cooldown-decouple.md`).

## Problem

`_PRINT_END_CLEANUP` runs a **blocking** `G4 P{print_end_cooldown_seconds}` for
the post-print cooldown — now 900 s (15 min) after the VEFACH dwell bump. While
that `G4` runs, the printer is held "busy", so:

- A `CANCEL_PRINT` right after print start still forces you to wait out the
  *entire* cooldown before the printer is usable.
- Clicking PAUSE/CANCEL in the UI is a no-op against the running macro.

The 15-min dwell makes this much more painful than the original 5 min.

## Design

**Stop blocking. Turn everything off immediately *except* the chamber exhaust,
and defer only the exhaust-stop to a `delayed_gcode`.**

The printer returns to idle the instant cleanup finishes; the VEFACH exhaust
keeps running in the background for the cooldown window. Because the only
deferred action is "stop a fan", it cannot disrupt anything that happens later
(a new print, a jog, a HEATSOAK) — which removes nearly all the edge-case
plumbing the issue anticipated.

### Why "only the exhaust" and not "defer the whole OFF"

Deferring the *whole* `OFF` would keep lights/motors on through the cooldown like
today, but a deferred full `OFF` is destructive if it fires during later activity
(it would kill heaters/motors mid-new-print), forcing every "start activity"
macro (PRINT_START, OFF, HEATSOAK) to explicitly cancel the pending timer.
Deferring *only* the exhaust-stop makes the deferred action idempotent and
harmless, so those cancels become unnecessary. The cost is a behavior change:
lights + motors go off at print-end rather than after the cooldown (accepted —
the print is done, the toolhead is parked, heaters are already off).

### idle_timeout is not a factor

`[idle_timeout]` is 7200 s (2 h) on this build — far longer than the 900 s
cooldown — so it will not fire mid-cooldown and prematurely stop the exhaust.

## Components

### `[delayed_gcode _COOLDOWN_EXHAUST_OFF]` — new, `config/macros/print_start.cfg`

The single deferred action. No `initial_duration` (must not fire at boot);
armed only via `UPDATE_DELAYED_GCODE`.

```
[delayed_gcode _COOLDOWN_EXHAUST_OFF]
gcode:
  SET_FAN_SPEED FAN=chamber_exhaust SPEED=0
```

### `_OFF_EXCEPT_EXHAUST` — new, `config/macros/macros.cfg`

The shared "off sequence" minus the exhaust line. Extracted so `OFF` and
`_PRINT_END_CLEANUP` share one source of truth for what "off" means.

```
[gcode_macro _OFF_EXCEPT_EXHAUST]
description: Internal: the OFF sequence minus the chamber exhaust (so the cooldown can keep it running). Not for direct use — call OFF.
gcode:
    M84                                  ; steppers off
    TURN_OFF_HEATERS                     ; bed / hotend / chamber heater (BedFans) off
    SET_GCODE_VARIABLE MACRO=_CHAMBER_CONTROL VARIABLE=active_target VALUE=0   ; clear recorded chamber target
    M107                                 ; part cooling fan off
    CASELIGHT_OFF                        ; case light off
```

### `OFF` — refactored, `config/macros/macros.cfg`

Calls `_OFF_EXCEPT_EXHAUST`, then stops the exhaust, then cancels any pending
cooldown timer (so a manual `OFF` during cooldown leaves no orphaned timer).
Net behavior identical to today's `OFF`, plus the timer-cancel.

```
[gcode_macro OFF]
description: Shut everything off (steppers, heaters, part fan, chamber exhaust, case light).
gcode:
    _OFF_EXCEPT_EXHAUST
    SET_FAN_SPEED FAN=chamber_exhaust SPEED=0                       ; exhaust off
    UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF DURATION=0        ; cancel any pending cooldown stop
```

### `_PRINT_END_CLEANUP` — rewritten, `config/macros/print_start.cfg`

Drops the blocking `G4`, the `OFF` call, **and the entire `in_cleanup` re-entry
guard + `variable_in_cleanup`** (the guard only existed to prevent a second
blocking `G4` when cancel landed mid-cooldown; with no blocking window, re-arming
the timer is idempotent, so it is obsolete).

```
[gcode_macro _PRINT_END_CLEANUP]
description: Shared cleanup tail — bed mesh clear, off-except-exhaust, reset speeds, then arm the non-blocking cooldown that stops the chamber exhaust after print_end_cooldown_seconds. Called by PRINT_END and by upstream CANCEL_PRINT via _CLIENT_VARIABLE.user_cancel_macro. Returns immediately; the printer is idle during the cooldown.
gcode:
  BED_MESH_CLEAR
  _OFF_EXCEPT_EXHAUST
  _RESETSPEEDS
  # Non-blocking cooldown: leave the VEFACH exhaust running (started by
  # PRINT_END / _CANCEL_PRINT_HOOK for chamber prints) and schedule it to stop
  # after the cooldown window. For PLA (no exhaust started) the deferred
  # SET_FAN_SPEED=0 is a harmless no-op.
  UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF DURATION={printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds|int}
```

### `PRINT_START` step 4 — `config/macros/print_start.cfg`

Replace the obsolete `in_cleanup` reset with: cancel the pending cooldown timer
and stop any lingering cooldown exhaust from a previous print. This is the one
guard that matters — it prevents a prior print's exhaust from bleeding into (and
venting the heat-up of) a new chamber print.

Current:
```
  SET_GCODE_VARIABLE MACRO=_PRINT_END_CLEANUP VARIABLE=in_cleanup VALUE=0
```
Replace with:
```
  UPDATE_DELAYED_GCODE ID=_COOLDOWN_EXHAUST_OFF DURATION=0    ; cancel any pending cooldown
  SET_FAN_SPEED FAN=chamber_exhaust SPEED=0                   ; stop a prior print's lingering cooldown exhaust
```

## Data flow

```
PRINT_END / _CANCEL_PRINT_HOOK
  (chamber>0) SET_FAN_SPEED chamber_exhaust = speed     # exhaust ON
  _PRINT_END_CLEANUP
    BED_MESH_CLEAR
    _OFF_EXCEPT_EXHAUST                                  # motors/heaters/lights/partfan OFF; exhaust untouched
    _RESETSPEEDS
    UPDATE_DELAYED_GCODE _COOLDOWN_EXHAUST_OFF DURATION=900
  -> returns immediately; printer idle, exhaust running
  ...900 s later (or never, if pre-empted)...
  _COOLDOWN_EXHAUST_OFF -> SET_FAN_SPEED chamber_exhaust = 0

New print within the window:
  PRINT_START step 4 -> cancel timer + exhaust OFF       # clean slate
```

## Edge cases

| Scenario | Outcome |
|---|---|
| Manual `OFF` during cooldown | `OFF` stops exhaust + cancels timer. Clean. |
| HEATSOAK during cooldown | Pending `exhaust=0` later is a no-op (HEATSOAK doesn't use the exhaust). |
| New print during cooldown | PRINT_START step 4 cancels timer + stops exhaust before heating. |
| Cancel mid-print | `_CANCEL_PRINT_HOOK` returns in ~1–2 min (MMU unload only), not 15 min; exhaust runs its window in the background. **The payoff.** |
| Two cooldowns overlap | `UPDATE_DELAYED_GCODE` re-arms the single timer to the latest; only one timer ever exists. |
| Re-enter `_PRINT_END_CLEANUP` | Idempotent (re-runs `_OFF_EXCEPT_EXHAUST`, re-arms timer). No guard needed. |
| PLA print (no exhaust) | Timer still armed; deferred `exhaust=0` is a no-op. |
| Stray `exhaust=0` fires during a print | Harmless — the exhaust is only ever ON during a cooldown; off during printing (BedFans own in-print VOC). |

## Testing

- **L2 `macro_refcheck.py`** — `_OFF_EXCEPT_EXHAUST`, `_COOLDOWN_EXHAUST_OFF`,
  `UPDATE_DELAYED_GCODE`, `SET_FAN_SPEED` references resolve.
- **L3 klippy parse** (CI) — `[delayed_gcode _COOLDOWN_EXHAUST_OFF]` parses; the
  rewritten macros load.
- **L4 pytest** — `_user_variables` structural tests stay green
  (`print_end_cooldown_seconds` still referenced, now as the delayed-gcode
  `DURATION`).
- **L6 post-deploy smoke** (manual): finish a chamber print → at PRINT_END the
  printer returns to idle *immediately* (no 15-min busy), motors/lights off,
  `chamber_exhaust` keeps running, and stops ~15 min later. `CANCEL_PRINT`
  mid-chamber-print → returns after the MMU unload, exhaust runs in background.
  Start a new print during the window → exhaust stops before heating. PLA print
  → no exhaust, returns to idle immediately.

## Restart impact

`RESTART` — macro bodies + one new `[delayed_gcode]`. No `[mcu]`/pin/kinematic
changes.

## Out of scope

- Auto-returning `print_stats` to `standby` after a print (the deploy idle-gate
  fix already handles the deploy symptom; resetting print_stats is a separate,
  fragile lever — see the discussion in #126's thread).
- Per-material cooldown durations.
- CLAUDE.md macro-inventory wording refresh (follow-up doc edit).
