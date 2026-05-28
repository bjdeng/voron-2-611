# Chamber cooldown: hold the print target (2026-05-28)

**Supersedes** the VOC-baseline cooldown mechanism from
`2026-05-22-chamber-heater-generic-pid.md`. Folds in PR #116 (toothless
verify_heater).

## Problem

Post-print VOC capture used `voc_baseline_temp` (50 °C) as a chamber target,
driven by `chamber_control_loop` (a delayed_gcode state machine). Four issues:

1. **Wrong fan profile.** The baseline (50) sits *below* the print target
   (~55). At PRINT_END the chamber is ≈55 — above the VOC target — so the PID
   idles BedFans until the chamber falls below 50, then ramps them toward 100%
   as it keeps cooling. Circulation is off-then-spiking, not steady; and the
   spike trends to 100% exactly when the chamber is coldest.
2. **Fragile coupling.** Maintaining VOC during PRINT_END depends on a
   delayed_gcode firing inside a 5-minute `G4` dwell. Loop-vs-dwell timing is
   subtle and easy to get wrong.
3. **PLA gets heated.** With `user_target == 0` and `print_active`, the loop
   drives VOC (target 50) *during PLA prints* — heating a chamber that PLA
   wants cool.
4. **verify_heater trips.** Holding an unreachable target long enough elapses
   `check_gain_time` → "not heating at expected rate" → shutdown (killed a
   successful 4h52m ASA print, 2026-05-27).

## Design

**VOC cooldown = keep the print's own chamber target for the cooldown window,
then turn everything off.**

- `PRINT_END` turns off the bed + hotend only and **leaves
  `[heater_generic chamber]` at the print target**. The bed's large residual
  mass keeps the chamber *reachable* for the few minutes that matter, so the
  PID holds BedFans at the same moderate speed they ran during the print —
  steady circulation through the under-bed carbon filter, not a 100% spike.
- After the 5-minute `G4` (`print_end_cooldown_seconds`), `OFF` zeroes the
  chamber → BedFans stop.
- `chamber_control_loop` and `_CHAMBER_CONTROL.user_target` are **removed**.
  The `[heater_generic chamber]` PID is the entire chamber controller.
  `SET_CHAMBER_TARGET` just clamps to `[0, chamber_max_target]` and sets the
  heater directly for all targets.
- **PLA/PETG** (print target 0) get no cooldown circulation — correct (see
  proxy below). The PID is simply off whenever the target is 0.

This is more robust than the loop: the PID runs autonomously regardless of the
`G4` dwell, so there is no delayed_gcode/dwell race.

## Why "chamber target > 0" is a sound VOC proxy

VOC/UFP emission correlates with **extrusion temperature**, which is also what
drives the chamber-temperature requirement (hot amorphous polymers warp and
need an enclosure). So the materials that ask for a heated chamber are the same
ones that off-gas the styrene / caprolactam / UFPs a carbon filter targets:

| Material | Chamber | Emissions |
|---|---|---|
| ABS / ASA / PC | 50-80 °C | high (styrene, etc.) |
| PETG | ~ambient | low-moderate |
| PLA | none | low |

So gating cooldown circulation on "the print used a heated chamber" captures
exactly the prints that benefit, and skips the low-emission ones.

## verify_heater (folds in #116)

Kept effectively toothless (`max_error`/`check_gain_time` = 99999). A fan-as-
heater can't thermal-runaway, and "can't reach/hold target" is *normal*: the
chamber can plateau below target during a print (passive bed radiation only) or
while the bed cools at PRINT_END. `[heater_generic chamber] max_temp = 70`
remains the real overtemp guard.

## Files

- `config/macros/chamber_control.cfg` — remove `chamber_control_loop` +
  `_CHAMBER_CONTROL`; simplify `SET_CHAMBER_TARGET`.
- `config/macros/print_start.cfg` — `PRINT_END` holds the chamber target
  (bed+hotend off only); fix stale loop/VOC comments in steps 4/6/9/13.
- `config/macros/macros.cfg` — `OFF` drops the loop-cancel + user_target lines.
- `config/client_hooks.cfg` — `_CANCEL_PRINT_HOOK` chamber sync simplified.
- `config/macros/bedfans.cfg` — chamber routing comment updated.
- `config/macros/_user_variables.cfg` — remove `voc_baseline_temp`,
  `voc_cooldown_threshold`.
- `config/bed.cfg` — `[verify_heater chamber]` toothless.

## Restart impact

`RESTART` (macro + gcode_macro + verify_heater body changes; no MCU/pin/kinematic
changes).

## Follow-up

Decouple VOC *evacuation* from chamber *heating*: add carbon to the chamber
exhaust housing (VEFACH) so the `chamber_exhaust` fan (z:P2.7) can own
cooldown/evacuation independently of BedFans. Tracked in its own issue.

## Out of scope

Chamber PID re-cal, Eddy thermal drift cal (#25).
