# VEFACH carbon exhaust owns end-of-print cooldown (2026-06-03)

Closes [#117](https://github.com/bjdeng/voron-2-611/issues/117). **Supersedes** the
VOC-capture mechanism in `2026-05-28-chamber-cooldown-hold-target.md` (the
"hold the print's chamber target through the cooldown G4" hack). The
chamber-heating design from that spec is unchanged.

## Background

The BedFans (`z:P2.5`, driven by `[heater_generic chamber]` PID) currently do
**two coupled jobs**:

1. **Chamber heating** — PID against the chamber thermistor holds an in-print
   chamber temp for ABS/ASA.
2. **VOC capture** — recirculating chamber air through the under-bed charcoal
   filter ([printables 334276](https://www.printables.com/model/334276-the-filter-for-voron-24/files)).

Because the BedFans are a `heater_pin`, the only way to spin them is via a
temperature target. The 2026-05-28 cooldown design exploited this by leaving the
chamber heater at the print's target through `PRINT_END`'s cooldown `G4`, so the
BedFans kept circulating while off-gassing was highest. It worked, but the VOC
job was entangled with the heating job — there was no clean way to "just run the
filter for N minutes."

The **VEFACH** mod ([VoronUsers/KevinAkaSam/VEFACH](https://github.com/VoronDesign/VoronUsers/tree/main/printer_mods/KevinAkaSam/VEFACH))
is now printed and installed: carbon filtration on the chamber **exhaust**
housing, routed **exhaust-to-room** (chamber air → carbon → room; fresh room air
drawn in). That fan (`chamber_exhaust`, `z:P2.7`) was already a plain
`[fan_generic]` with no automated caller. With carbon in its path and an
exhaust-to-room route, it can now **actively cool the chamber while filtering
VOCs** — which is exactly what an end-of-print cooldown wants.

## Design

**Decouple the two jobs.**

- **During a print — unchanged.** BedFans (`[heater_generic chamber]` PID) own
  chamber heating *and* in-print VOC recirculation through the under-bed filter.
- **At print end — new.** The chamber heater turns *off*, and the VEFACH carbon
  exhaust runs for the cooldown window: active cooling + VOC evacuation to the
  room, independent of any temperature target.

### Termination model: fixed timer

Run the exhaust for a fixed duration (`print_end_cooldown_seconds`, currently
300 s), then off. No temperature threshold, no VOC sensor.

Rationale: two things decay after a print — (1) off-gassing *source strength*,
which falls as the part + nozzle cool, and (2) VOCs *already suspended* in the
chamber air, cleared by air exchange (`CFM × time`). The exhaust's actual job is
(2), which is fundamentally a time process; a fixed timer targets it directly and
covers (1) implicitly (the source has cooled by the time the fan has run a few
minutes). A temperature threshold would only address (1) and gives no guarantee
the air volume turned over. Fixed-time is also the dominant Voron/Nevermore
community pattern. If a VOC sensor is ever added, threshold control can supersede
this.

### Gate: `chamber > 0` prints only

The cooldown exhaust fires only for prints that used a heated chamber
(ABS/ASA/PC). PLA/PETG (chamber target 0) get nothing — they off-gas little, and
this keeps the low-temp path zero-overhead. This is the same VOC proxy the
codebase already uses ("chamber-target > 0").

The gate signal is `_CHAMBER_CONTROL.active_target` — the clamped setpoint
recorded by `SET_CHAMBER_TARGET`. `PRINT_END` takes no params (the slicer calls
it bare), so it cannot read `CHAMBER=`; `active_target` is the in-band signal.

## Components

### `config/macros/print_start.cfg` — `PRINT_END`

Capture the chamber target at macro entry, turn the chamber heater off, then
start the exhaust for VOC materials:

```
{% set chamber_target = printer["gcode_macro _CHAMBER_CONTROL"].active_target|float %}
M400
G92 E0
G91
G1 E-2 F2700
G1 Z10 F3000
G90
G1 X{...} Y{...} F6000     # park rear-left (unchanged)
G1 Z1 F600
M104 S0                    # hotend off
M140 S0                    # bed off
SET_CHAMBER_TARGET TARGET=0   # NEW: chamber heater / BedFans off cleanly (no hold-target)
M107                       # part fan off
{% if chamber_target > 0 %}
  SET_FAN_SPEED FAN=chamber_exhaust SPEED={chamber_exhaust_cooldown_speed}   # NEW
{% endif %}
_PRINT_END_CLEANUP
```

The whole macro template renders once at invocation, so `chamber_target` binds to
`active_target`'s value *before* the runtime `SET_CHAMBER_TARGET TARGET=0` zeroes
it. The `{% if chamber_target > 0 %}` gate therefore sees the print's real
target. (This is the render-once Jinja behaviour working in our favour — the same
behaviour that bites elsewhere; see CLAUDE.md "Klipper gotchas".)

`SET_CHAMBER_TARGET TARGET=0` is added so the BedFans stop immediately at
`PRINT_END` rather than recirculating through the cooldown (which would fight the
exhaust's cooling and is no longer needed for VOC).

### `config/macros/print_start.cfg` — `_PRINT_END_CLEANUP`

**Unchanged.** Its `G4 P{print_end_cooldown_seconds}` is now the exhaust runtime;
its `OFF` already calls `SET_FAN_SPEED FAN=chamber_exhaust SPEED=0` and zeroes
`active_target` — the backstop that stops the fan at the end of cooldown.

### `config/client_hooks.cfg` — `_CANCEL_PRINT_HOOK`

Swap the "re-assert chamber target" block for "start the exhaust if a chamber
target was active." Upstream `CANCEL_PRINT` already turned the chamber heater
off before this hook runs; we no longer re-assert it (the old behaviour resumed
BedFans recirculation — now superseded by the exhaust):

```
{% set active_target = printer["gcode_macro _CHAMBER_CONTROL"].active_target|float %}
{% if active_target > 0 %}
  SET_FAN_SPEED FAN=chamber_exhaust SPEED={chamber_exhaust_cooldown_speed}
{% endif %}
MMU_END UNLOAD=1
_PRINT_END_CLEANUP
```

Cancel-parity with `PRINT_END` is preserved: a cancelled ABS print gets the same
exhaust cooldown; `_PRINT_END_CLEANUP`'s `OFF` stops the fan.

### `config/macros/_user_variables.cfg`

- **Add** `variable_chamber_exhaust_cooldown_speed: 1.0` — exhaust fan speed
  during the end-of-print cooldown (full speed = maximum air exchange; range
  0.0–1.0).
- **Reuse** `print_end_cooldown_seconds: 300` as the cooldown dwell / exhaust
  runtime — value unchanged, comment updated (it no longer describes BedFans
  holding the chamber target).

### Comment / doc-string updates (no behaviour change)

- `config/bed.cfg` — `[fan_generic chamber_exhaust]` header now has an automated
  caller (PRINT_END / cancel cooldown via VEFACH carbon). Update the "manual
  control only" note (lines ~13-14 and ~82-85).
- `config/macros/chamber_control.cfg` — header block (lines ~11-16) describes VOC
  cooldown as "PRINT_END holds the print's chamber target through the G4." Update
  to "PRINT_END turns the chamber heater off and runs the VEFACH carbon exhaust
  for the cooldown window." `_CHAMBER_CONTROL.active_target` is still recorded and
  still consumed — now by PRINT_END / cancel to gate the exhaust rather than to
  restore the heater target.

## Data flow

```
PRINT_START (chamber>0)         SET_CHAMBER_TARGET TARGET=N  → active_target = N
  ...print runs...              [heater_generic chamber] PID → BedFans heat + VOC recirc
PRINT_END                       capture chamber_target = N (active_target)
                                bed/hotend off
                                SET_CHAMBER_TARGET TARGET=0  → BedFans off, active_target = 0
                                chamber_target>0 → SET_FAN_SPEED chamber_exhaust = 1.0
  _PRINT_END_CLEANUP            G4 P300000 (exhaust runs, chamber cools + clears)
                                OFF → chamber_exhaust SPEED=0, active_target=0
```

PLA/PETG path: `active_target` is 0 throughout → `chamber_target > 0` is false →
no exhaust, identical to today.

## Error handling / edge cases

- **Re-entry guard.** `_PRINT_END_CLEANUP`'s existing `in_cleanup` guard still
  prevents a cancel-during-cooldown from queuing a second `G4`. The exhaust is
  started by the *caller* (PRINT_END / cancel hook) before `_PRINT_END_CLEANUP`,
  so a skipped re-entry doesn't restart the fan — and `OFF` from the *outer*
  cleanup stops it. No double-start, no orphaned fan.
- **Abort mid-PRINT_START.** If a print aborts before step 13 commits the full
  chamber target, `active_target` is the step-6 half-target (>0 for chamber
  prints) or 0 (PLA). A non-zero half-target still correctly triggers a (short,
  low-VOC) exhaust cooldown; PLA still skips. Acceptable — erring toward
  evacuating is harmless.
- **Fan left on if cleanup errors.** If `_PRINT_END_CLEANUP` errors before `OFF`,
  the exhaust would keep running. Same existing risk class as the heaters; the
  manual `OFF` macro (and the `in_cleanup=0` reset in PRINT_START step 4) recover
  it. No new guard added — matches the codebase's current cleanup posture.

## Testing

- **L2/L3 CI** — `macro_refcheck.py` + klippy parse must stay green:
  `SET_FAN_SPEED`, `FAN=chamber_exhaust`, `chamber_exhaust_cooldown_speed`
  reference resolution; render-once capture of `chamber_target`.
- **L4 pytest** — extend chamber/cooldown coverage if structural assertions exist
  for PRINT_END's heater-off + exhaust sequence.
- **L6 post-deploy smoke** — manual: run a short ABS print (or a
  `SET_CHAMBER_TARGET TARGET=40` + `PRINT_END` dry-run), confirm at PRINT_END the
  BedFans stop, the `chamber_exhaust` fan spins at full, the chamber temp falls,
  and `OFF` stops the fan after the dwell. Confirm a PLA print (CHAMBER=0) starts
  no exhaust. Confirm `CANCEL_PRINT` mid-ABS starts the exhaust.

## Restart impact

`RESTART` — macro + gcode_macro bodies + comments only. No `[mcu]`, pin,
kinematic, or sensor-type changes; the `[fan_generic chamber_exhaust]` section
(`z:P2.7`) already exists.

## Follow-up (out of scope here)

- **Interruptible cooldown.** Today the cooldown is a *blocking* `G4` in
  `_PRINT_END_CLEANUP`, so the printer is held "busy" for the full dwell — a
  cancel right after print start still makes you wait out the whole cooldown
  before you can do anything. The fix is to make the cooldown non-blocking
  (schedule `OFF` + exhaust-stop via a `[delayed_gcode]`, like the existing
  `DELAYED_OFF`, so the printer returns to idle immediately and a new print or a
  manual `OFF` can abort the pending cooldown). This restructures the cleanup
  control-flow (and the `in_cleanup` re-entry guard), so it's its own
  issue/PR, not folded in here.

## Out of scope

- Temperature-threshold or VOC-sensor exhaust control (revisit only if a VOC
  sensor is added).
- Exhaust cooldown for PLA/PETG turnaround (gated to `chamber > 0`).
- Chamber PID re-cal, Eddy thermal drift cal ([#25](https://github.com/bjdeng/voron-2-611/issues/25)).
- VEFACH ducting / hardware mounting (already installed).
