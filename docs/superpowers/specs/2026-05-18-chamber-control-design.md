# Active chamber temperature control — spec

**Owner:** Ben (printer-side; operator-facing macros only).

**Restart impact:** RESTART. Modifies gcode_macros, adds `_USER_VARIABLE` keys, adjusts `[temperature_fan chamber].max_temp`. No MCU pins, sensors, or kinematics change.

**Pairs with:** [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](2026-05-18-print-lifecycle-redesign.md) — this spec replaces PRINT_START's inline chamber-soak block (`M106 S255` + `TEMPERATURE_WAIT`) with a `SET_CHAMBER_TARGET` call that delegates to a continuous control loop.

---

## 1. Problem

The current chamber-thermal setup is passive and minimal:

- `[fan_generic BedFans]` (Ellis-style charcoal-filtered bed fans) is auto-ramped by the bed target ≥100°C threshold — slow during heater ramp, fast at target.
- `[temperature_fan chamber]` (PID exhaust fan) has `target_temp: 0` — off unless manually enabled.
- No active chamber temperature management. PRINT_START's hot-material soak (per print lifecycle redesign §3.1 step 9) does `M106 S255` + `TEMPERATURE_WAIT SENSOR="temperature_fan chamber"` — but `M106` is the part-cooling fan on the toolhead, not chamber circulation; the bed warmth-into-chamber transfer is incidental.
- No VOC baseline. Bedfans are off when bed is cold (or when bed target <100°C), so prints that don't need chamber heat (PLA, PETG) get zero charcoal filtration.
- Cooling is passive — opening doors is the only way to bring chamber down. The PID exhaust fan exists but isn't wired into print lifecycle.

Ben's stated requirements:

1. **VOC baseline:** Bedfans should run continuously at low speed during prints to cycle air across the charcoal filter and scrub off-gassing materials.
2. **Cooldown VOC capture:** Continue baseline circulation after print ends, while the bed (and chamber) is still warm enough to off-gas residuals.
3. **Active heat:** When the slicer specifies a chamber target (ABS/ASA/PA-CF: CHAMBER=30 per the print lifecycle spec), bedfans push bed warmth into the chamber to reach target faster.
4. **Active cool:** When chamber is above target (e.g., transitioning from an ABS print into a cool-material follow-up), exhaust fan vents hot air.
5. **Safety cap:** Don't try to drive chamber above 60°C; the build can't reliably reach more without doors closed AND chamber heater (which doesn't exist).
6. **Practical floor:** Below ~30°C is hard to reach with doors closed; cooling has limited authority. Accept this — don't promise impossible setpoints.

## 2. Goal

A continuous chamber control loop that owns BedFans and the chamber exhaust fan, driven by a single setpoint from the slicer (or manual override). PRINT_START's chamber soak becomes "set target + wait for it." PRINT_END / cancel turns active control off but bedfans keep filtering until bed cools.

**Non-goals:**

- VOC sensor integration. Future work; noted in §10.
- PID-tuned heat mode. Klipper has no built-in "fan ramps up when sensor below target" primitive; bang-bang with hysteresis is sufficient for chamber thermal mass.
- Sub-30°C chamber control. Cooling authority is limited; don't promise what hardware can't deliver.
- Per-material control policies (e.g., "PA-CF wants strict ±1°C"). Single hysteresis band suffices.
- TEMPERATURE_WAIT timeout for unreachable chambers. Same risk as today; file as followup if encountered.

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  _CHAMBER_CONTROL (state holder; gcode_macro)           │
│    variable_target: 0           (desired °C; 0 = off)   │
│    variable_target_band: 2      (hysteresis ±°C)        │
│    variable_voc_baseline: 0.1   (idle/baseline bedfan)  │
│    variable_heat_speed: 1.0     (heat-mode bedfan)      │
└─────────────────────────────────────────────────────────┘
        ▲                                ▲
        │ writes target                  │ reads
        │                                │
┌───────────────────┐         ┌──────────────────────────┐
│ SET_CHAMBER_TARGET│         │ chamber_control_loop     │
│ TARGET=<°C>       │         │ (delayed_gcode, 5s tick) │
└───────────────────┘         │                          │
        ▲                     │ reads: chamber temp,     │
        │                     │  heater_bed.temperature, │
        │                     │  print_stats.state       │
   PRINT_START                │                          │
   PRINT_END (TARGET=0)       │ writes:                  │
   _CANCEL_PRINT_HOOK         │  SET_FAN_SPEED BedFans   │
   manual console             │  SET_TEMP_FAN_TARGET     │
                              │    temperature_fan=chamber│
                              └──────────────────────────┘
```

### 3.1 State macro: `_CHAMBER_CONTROL`

Variables-only holder, same pattern as `_USER_VARIABLE`. Stores runtime mutable state (`variable_target`) updated by `SET_CHAMBER_TARGET`. Static knobs (band, speeds, thresholds) live here too for one-place tuning.

### 3.2 Setter: `SET_CHAMBER_TARGET TARGET=<°C>`

The single entry point for changing the setpoint. Clamps input to `[0, chamber_max_target]`. Updates `_CHAMBER_CONTROL.variable_target`. Kicks the control loop with `UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1` so state takes effect within ~1 second. If target > chamber_max_target, clamps and emits an `M117` warning + `RESPOND` info line — user gets feedback but the print doesn't abort.

### 3.3 Control loop: `[delayed_gcode chamber_control_loop]`

5-second tick. Reads sensor values from `printer.*`. Decides one of five states:

- **HEAT** — `target > 0` AND `chamber < target - band`: BedFans → heat_speed (1.0), `temperature_fan chamber` target → 0 (cool off).
- **COOL** — `target > 0` AND `chamber > target + band`: BedFans → voc_baseline, `temperature_fan chamber` target → target (PID exhaust).
- **MAINTAIN** — `target > 0` AND `chamber` within band: BedFans → voc_baseline, `temperature_fan chamber` target → target (PID handles minor drift).
- **VOC BASELINE** — `target == 0` AND (`printing/paused` OR `bed_temp >= voc_cooldown_threshold`): BedFans → voc_baseline, exhaust → 0. Covers active prints + cooldown VOC capture.
- **OFF** — `target == 0` AND idle AND bed cold: BedFans → 0, exhaust → 0. Loop self-terminates.

Loop re-arms (`UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=5`) except in OFF state. Re-arms on next `SET_CHAMBER_TARGET` call OR via PRINT_START's bootstrap.

### 3.4 Hooks into existing lifecycle

**PRINT_START step 9 (chamber soak branch):** replace inline soak logic.

Before (current PRINT_START, in `config/macros/print_start.cfg` §9):
```
{% if chamber > 0 %}
  M106 S255                                            # PT-fan stirs chamber air
  PARKCENTER
  TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={chamber}
  M107
{% elif soak_s > 0 %}
  G4 P{(soak_s * 1000)|int}
{% endif %}
```

After:
```
{% if chamber > 0 %}
  SET_CHAMBER_TARGET TARGET={chamber}                  # active heat via bedfans + (later) cool via exhaust
  PARKCENTER
  TEMPERATURE_WAIT SENSOR="temperature_fan chamber" MINIMUM={chamber}
{% elif soak_s > 0 %}
  G4 P{(soak_s * 1000)|int}                            # cold-material brief bed-stabilization soak
{% endif %}
```

The PRINT_START path doesn't need to call `SET_CHAMBER_TARGET TARGET=0` for the cold-material branch — `target` defaults to 0 in `_CHAMBER_CONTROL`, and the loop's VOC-baseline state covers print-time bedfan operation. Loop is bootstrapped at the start of PRINT_START (just below the existing `CLEAR_PAUSE` block):
```
UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1   # bootstrap chamber control loop
```

**PRINT_END:** add at the start of the body, before the existing `M400`:
```
SET_CHAMBER_TARGET TARGET=0
```

**`_CANCEL_PRINT_HOOK`** (in `config/client_hooks.cfg`): same — `SET_CHAMBER_TARGET TARGET=0` before the existing `MMU_END UNLOAD=1` + `_PRINT_END_CLEANUP`.

**`OFF` macro:** add a defensive `SET_FAN_SPEED FAN=BedFans SPEED=0` to ensure the "shut everything down" command terminates the control loop's writes. Currently `OFF` calls `set_temperature_fan_target temperature_fan=chamber target=0` — keep that, add the BedFans line.

## 4. Cleanup of `bedfans.cfg`

The chamber control loop is the sole writer of automatic BedFans state. Old behavior is removed:

- **Remove** bedfan logic from `[gcode_macro M190]` override — no more `BEDFANSSLOW` / `BEDFANSFAST` calls in M190. (M190 still does the TEMPERATURE_WAIT tolerance band — that's a different concern and stays.)
- **Remove** bedfan logic from `[gcode_macro SET_HEATER_TEMPERATURE]` override — same. The override stays (it still handles the M104/M99140 routing) but no longer touches BedFans.
- **Remove** `[delayed_gcode bedfanloop]` — replaced by `chamber_control_loop`.
- **Remove** `BEDFANSOFF` call from `[gcode_macro TURN_OFF_HEATERS]` override — chamber control loop handles end-of-print bedfan state.
- **Keep** `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` macros — useful for manual console override or future macro authoring, but no automatic caller.

## 5. New `_USER_VARIABLE` keys

Add to `config/macros/_user_variables.cfg`:

```
# Chamber control (chamber_control.cfg owns BedFans + temperature_fan chamber)
variable_chamber_target_band: 2          # hysteresis ±°C
variable_chamber_voc_baseline: 0.1       # bedfan speed during VOC baseline + cooldown
variable_chamber_heat_speed: 1.0         # bedfan speed in active heat mode
variable_chamber_max_target: 60          # SET_CHAMBER_TARGET clamps to this
variable_voc_cooldown_threshold: 40      # bed temp °C below which VOC baseline turns off
```

Remove (no longer consulted):
```
variable_bedfans_threshold: 100          # was: bed-target-based ramp
variable_bedfans_fast: 0.6               # replaced by chamber_heat_speed
variable_bedfans_slow: 0.2               # replaced by chamber_voc_baseline
```

`bedfans_threshold` is referenced by the (kept) `M190` override's bedfans-decision block — that block is being removed in §4 so the reference goes away cleanly.

## 6. File layout

The new control macros + state live in `config/macros/chamber_control.cfg` (new file). Included from `printer.cfg` after `macros/_user_variables.cfg`:

```
[include macros/_user_variables.cfg]
[include macros/macros.cfg]
[include macros/chamber_control.cfg]    # NEW
[include macros/test_speed.cfg]
... (rest unchanged)
```

CLAUDE.md macro inventory gets a new block for this file.

## 7. Safety

- `[temperature_fan chamber].max_temp` lowered from 70 to 60 to match the operator-stated safety cap. Klipper will raise an error if measured chamber temp exceeds 60°C — protective shutdown.
- `SET_CHAMBER_TARGET` clamps input. Negative values treated as 0. Above `chamber_max_target` (60), clamped to 60 with M117 warning.
- The control loop reads `printer.heater_bed.temperature` — if the bed thermistor disconnects (Klipper reports an error and shuts down). No need for our loop to handle this; Klipper's MCU layer does.
- `OFF` macro forces BedFans to 0 explicitly — defense in depth in case the control loop state is wedged.

## 8. Failure modes

| Mode | Today | After |
|---|---|---|
| Chamber never reaches target | `TEMPERATURE_WAIT` blocks forever | Same. File followup if it happens. |
| Bed thermistor disconnect | Klipper MCU shutdown | Same. Control loop doesn't run on shutdown state. |
| Chamber thermistor disconnect | `temperature_fan` shutdown; PID fails | Same. Klipper raises error. |
| User sets CHAMBER=100 in slicer | No clamp; M190-style hang | `SET_CHAMBER_TARGET` clamps to 60 + M117 warning. Print continues with clamped target. |
| Cancel mid-print with hot chamber | Bedfans + exhaust were never wired to lifecycle; chamber stays hot | `_CANCEL_PRINT_HOOK` calls `SET_CHAMBER_TARGET TARGET=0`. Cooldown VOC baseline runs until bed cools below threshold. |
| Power cycle mid-print | All fans off (Klipper restart from scratch) | Same. State macro re-initializes to defaults. No special handling needed. |

## 9. Testing

| Layer | Coverage |
|---|---|
| **L1** pre-commit | Text hygiene |
| **L2** macro_refcheck | New macro names (`_CHAMBER_CONTROL`, `SET_CHAMBER_TARGET`, `chamber_control_loop`) resolve; removed refs (`bedfans_threshold`, etc.) gone from any caller |
| **L3** klippy parse | CI; catches config errors (e.g., bad `max_temp` value) |
| **L4** pytest macro_refcheck tests | Cover L2 |
| **L5** test_config_structure | Description fields on new macros; `_USER_VARIABLE` refs resolve; removed `bedfans_*` keys not referenced anywhere |
| **L6** post-deploy smoke | Existing smoke (G28, PARKCENTER, OFF, _RESETSPEEDS) — `OFF` now also writes BedFans=0, smoke catches if that breaks |
| **L7** snapshot | Not applicable as gate — intentional behavior change |

**Manual print tests after deploy:**

- **PLA print** (CHAMBER=0, bed=60): expect bedfans at VOC baseline during print. Print ends → bedfans continue baseline through cooldown. Bed crosses 40°C → bedfans off. Chamber fan never runs.
- **ABS print** (CHAMBER=30, bed=110): expect chamber control loop to ramp bedfans to heat_speed during PRINT_START soak. Once chamber reaches 30°C, transitions to MAINTAIN (baseline bedfans, exhaust ready). Print ends → bedfans baseline for cooldown VOC.
- **Cancel mid-ABS**: expect `_CANCEL_PRINT_HOOK` sequence to set chamber TARGET=0, MMU unload, cleanup tail. Bedfans continue baseline through cooldown.
- **Manual `SET_CHAMBER_TARGET TARGET=80`** (above cap): expect M117 warning, target clamped to 60.

## 10. Future work

- **VOC sensor integration.** Add a chamber VOC sensor (SGP40 / SGP41 / BME680 on I²C through an MCU). Augment the control loop: when VOC concentration is above a threshold, override the baseline bedfan speed to a higher "scrubbing" level even when not actively heating. Closes the "is the air actually clean?" loop instead of inferring it from bed temperature. Per Ben (2026-05-18) — file as future-work after this baseline lands.
- **PID tuning of `temperature_fan chamber`.** Existing PID values (Kp=40, Ki=0.2, Kd=0.1) are jontek2-derived defaults. Re-tune in #25 weekend session.
- **Chamber-control-aware HEATSOAK macro.** Currently `HEATSOAK` is for bed pre-warming. Could extend to "soak chamber to N°C" with the new SET_CHAMBER_TARGET interface.
- **Adaptive heat-mode speed.** If 1.0 is too loud during late soak, implement a soft-ramp (e.g., 1.0 until within 5°C of target, then 0.7). Bang-bang with hysteresis is fine for first ship.

## 11. Anti-criteria

- No changes to `[heater_bed]`, `[heater_fan controller_fan]`, `[quad_gantry_level]`, or chamber thermistor calibration.
- No edits to `mainsail.cfg` or any Pi-side symlink target (per [[feedback-mainsail-cfg-symlink-trap]]).
- No new `[temperature_fan]` or `[fan_generic]` hardware definitions — existing `BedFans` and `chamber` are reused.
- No PID tuning here. Defer to #25.
- No slicer-side changes — the existing `CHAMBER` param contract from the print lifecycle redesign covers the setpoint flow.

## 12. References

- Print lifecycle redesign: [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](2026-05-18-print-lifecycle-redesign.md)
- Current bedfans config: `config/macros/bedfans.cfg`
- Current chamber fan: `config/bed.cfg` (`[temperature_fan chamber]`)
- [Voron Chamber Temperature & Exhaust Fan](https://docs.vorondesign.com/community/howto/alchemyEngine/chamber_temperature_exhaust_fan.html) — canonical Voron community doc
- [Ellis BedFans mod](https://mods.vorondesign.com/details/28xgztUufAtAfV4XUL5l4w) — origin of the existing macros
- [Klipper forum: chamber heat AND vent fan](https://klipper.discourse.group/t/use-chamber-heat-and-vent-fan-to-maintain-temp/19993) — confirms the dual-control pattern; specific caution about vent fan staying off during heating (addressed in §3.3's HEAT state setting exhaust TARGET=0)
- [DarkDoldier Klipper-better-BED-FANS-Macro](https://github.com/DarkDoldier/Klipper-better-BED-FANS-Macro) — closest existing community pattern (bang-bang chamber target; hardcoded setpoint instead of slicer-driven)
