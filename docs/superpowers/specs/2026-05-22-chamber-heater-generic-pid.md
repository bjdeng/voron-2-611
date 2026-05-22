# Chamber Heater via `[heater_generic]` PID on BedFans

## Problem

Today's chamber control loop is a bang-bang state machine: BedFans run at `chamber_heat_speed` (100%) until chamber reaches target, then snap to `chamber_voc_baseline` (15%). The `[temperature_fan chamber]` PID then independently fights overshoot by running the exhaust fan. The two controllers race each other: BedFans 100% → overshoot → exhaust kicks in → undershoot → BedFans 100% again. Cycle period is tens of minutes for a chamber thermal mass this size, but it's annoying and visible. PR #110's hysteresis fix narrowed the boundary but didn't eliminate the underlying coupling.

## Solution

Replace the bang-bang + dual-PID architecture with a single Klipper `[heater_generic]` block that owns the BedFans PWM pin and runs a continuous PID loop using the chamber thermistor as feedback. The exhaust fan loses its automated controller and becomes a manually-driven `[fan_generic]`. The custom `chamber_control_loop` shrinks to a narrow VOC/OFF state machine that only runs when the user has not set an explicit chamber target.

Net effect:

- No more race — there is no second PID to race against.
- BedFans speed continuously tapers near setpoint instead of snapping at target.
- Post-print VOC capture happens naturally: the chamber target stays set through PRINT_END, the bed cools, the PID can no longer maintain target, BedFans ramp to 100% to circulate air through the under-bed filter. No new logic required.

## Architecture

### Config blocks

**New:**

```ini
[heater_generic chamber]
heater_pin: z:P2.5                    ; BedFans PWM pin (was [fan_generic BedFans])
sensor_type: 10k_thermistor
sensor_pin: z:P0.24                   ; chamber thermistor (sole consumer now)
control: pid
pid_Kp: 40                            ; placeholder; PID_CALIBRATE overwrites via SAVE_CONFIG
pid_Ki: 5
pid_Kd: 0
max_power: 1.0
min_temp: 0
max_temp: 70                          ; sensor-shutdown ceiling (was on [temperature_fan chamber])
pwm_cycle_time: 0.05                  ; 20Hz, matches the prior fan_generic default

[verify_heater chamber]
max_error: 300                        ; permissive — fan-only heater can't thermal-runaway
check_gain_time: 1800                 ; 30 min window
heating_gain: 1
hysteresis: 5

[fan_generic chamber_exhaust]
pin: z:P2.7                           ; was [temperature_fan chamber] pin
```

**Removed:**

- `[fan_generic BedFans]` — pin owned by heater_generic now
- `[temperature_fan chamber]` — dropped entirely; exhaust is manual via the new `[fan_generic chamber_exhaust]`
- `[duplicate_pin_override]` — not needed; the chamber thermistor has only one consumer

### Macros

`SET_CHAMBER_TARGET` becomes a direct setpoint writer for the common case, with the loop reserved for state-derived VOC/OFF transitions:

```jinja
[gcode_macro _CHAMBER_CONTROL]
variable_user_target: 0
gcode:

[gcode_macro SET_CHAMBER_TARGET]
description: Set chamber heater target. Clamps to chamber_max_target.
gcode:
  {% set chamber_max_target = printer["gcode_macro _USER_VARIABLE"].chamber_max_target|float %}
  {% set target = [[params.TARGET|default(0)|float, 0]|max, chamber_max_target]|min %}
  SET_GCODE_VARIABLE MACRO=_CHAMBER_CONTROL VARIABLE=user_target VALUE={target}
  {% if target > 0 %}
    SET_HEATER_TEMPERATURE HEATER=chamber TARGET={target}
  {% else %}
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=1
  {% endif %}

[delayed_gcode chamber_control_loop]
gcode:
  {% set user_target          = printer["gcode_macro _CHAMBER_CONTROL"].user_target|float %}
  {% set voc_baseline_temp    = printer["gcode_macro _USER_VARIABLE"].voc_baseline_temp|float %}
  {% set voc_cooldown_bed     = printer["gcode_macro _USER_VARIABLE"].voc_cooldown_bed|float %}
  {% set bed_temp             = printer.heater_bed.temperature|float %}
  {% set state                = printer.print_stats.state|string %}
  {% set print_active         = state in ("printing", "paused") %}
  {% if user_target > 0 %}
    # User has set explicit chamber target via SET_CHAMBER_TARGET. heater_generic
    # PID handles it continuously. Loop self-terminates.
  {% elif print_active or bed_temp >= voc_cooldown_bed %}
    SET_HEATER_TEMPERATURE HEATER=chamber TARGET={voc_baseline_temp}
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=30
  {% else %}
    SET_HEATER_TEMPERATURE HEATER=chamber TARGET=0
    UPDATE_DELAYED_GCODE ID=chamber_control_loop DURATION=60
  {% endif %}
```

The loop runs only when `user_target == 0` AND a state-derived chamber action is needed (VOC during prints, OFF after bed cools). When `user_target > 0`, the loop literally does not poll — Klipper's PID is the entire controller.

### Lifecycle

**PRINT_START** is unchanged. It already calls `SET_CHAMBER_TARGET TARGET={chamber}` with the slicer-provided value. For ABS (CHAMBER=55), the new SET_CHAMBER_TARGET writes 55 to the heater directly. For PLA (CHAMBER=0), it kicks the loop, which enters VOC mode when the print starts.

**PRINT_END** changes one line: remove the immediate `SET_CHAMBER_TARGET TARGET=0` call from the macro body. Chamber target persists through the post-print cooldown window.

```jinja
[gcode_macro PRINT_END]
gcode:
  # SET_CHAMBER_TARGET TARGET=0 removed here — chamber target persists through
  # the cooldown window for VOC capture. Bed cools → PID can't maintain target
  # without bed heat → BedFans ramp to 100%, circulating air through the
  # under-bed filter. OFF (called from _PRINT_END_CLEANUP) zeros it at the end.
  M400
  ; ... retract, lift, park, TURN_OFF_HEATERS, M107 ...
  _PRINT_END_CLEANUP
```

`_PRINT_END_CLEANUP`'s G4 (currently `print_end_cooldown_seconds`) becomes the post-print VOC window. Tunable via `_USER_VARIABLE`. Recommend bumping from current value to 300-600 s (5-10 min) for ABS prints.

`_CANCEL_PRINT_HOOK` follows the same pattern: chamber target stays set, MMU unloads, then `_PRINT_END_CLEANUP` G4 + OFF.

### State machine

| State | Trigger | Heater target | Exhaust |
|---|---|---|---|
| Explicit heat | user_target > 0 (`SET_CHAMBER_TARGET TARGET=N`) | N | manual |
| VOC mode | user_target == 0 AND (print_active OR bed_temp ≥ voc_cooldown_bed) | voc_baseline_temp (e.g. 30) | manual |
| OFF | user_target == 0 AND not print_active AND bed_temp < voc_cooldown_bed | 0 | manual |

## Tuning

### PID_CALIBRATE workflow (once, post-deploy)

The chamber plant (BedFans circulating bed-warmed air) is non-trivial — Klipper's Ziegler-Nichols may or may not converge to good values. Cal at representative conditions:

```gcode
M140 S110                                            ; warm bed to typical ABS temp
G28
G0 X175 Y175 Z10 F3000                               ; toolhead at bed center
; Wait ~15-20 min for chamber thermal equilibrium

PID_CALIBRATE HEATER=chamber TARGET=55 WRITE_FILE=1  ; ~30-60 min; writes /tmp/heattest.txt
SAVE_CONFIG
```

If the auto-cal values produce large oscillation in a real ABS print, fall back to manual tuning starting from the placeholder Kp=40, Ki=5, Kd=0:

- Slow to reach target → increase Kp
- Oscillates around target → decrease Kp, increase Kd
- Steady-state error → increase Ki (small steps)

### verify_heater tuning

Permissive starting values (`max_error: 300`, `check_gain_time: 1800`, `heating_gain: 1`). After a few ABS prints, audit `klippy.log` for `verify_heater chamber` trip warnings. Real trips → raise further. No trips → leave alone.

### `_USER_VARIABLE` changes

Removed (obsolete with PID-driven control):

- `chamber_voc_baseline` (fan speed, replaced by `voc_baseline_temp`)
- `chamber_heat_speed` (fan speed, PID picks speed now)
- `chamber_target_band` (hysteresis no longer applicable)
- `variable_heating` flag (state no longer needed)

Added:

- `voc_baseline_temp: 30` — chamber heater target during VOC mode

Kept:

- `chamber_max_target` (60) — SET_CHAMBER_TARGET clamp
- `voc_cooldown_bed` (40) — bed temp threshold for entering VOC mode after print
- `print_end_cooldown_seconds` — already exists; recommend bump to 300-600 s

## Migration plan

Single PR off main. Branch: `feat/chamber-heater-generic-pid`.

1. **Edit configs:**
   - `config/bed.cfg`: remove `[temperature_fan chamber]`; add `[heater_generic chamber]` + `[verify_heater chamber]` + `[fan_generic chamber_exhaust]`. Update header doc comments.
   - `config/macros/bedfans.cfg`: remove `[fan_generic BedFans]` + `BEDFANSSLOW/FAST/OFF`. Keep `SET_HEATER_TEMPERATURE` override (routes bed heater via M99140 — unrelated, stays).
   - `config/macros/chamber_control.cfg`: rewrite `_CHAMBER_CONTROL`, `SET_CHAMBER_TARGET`, `chamber_control_loop` per Architecture section. The temperature read source changes from `printer["temperature_fan chamber"].temperature` to `printer["heater_generic chamber"].temperature`.
   - `config/macros/print_start.cfg`: (a) remove the immediate `SET_CHAMBER_TARGET TARGET=0` from PRINT_END; (b) update `TEMPERATURE_WAIT SENSOR="temperature_fan chamber"` → `SENSOR="heater_generic chamber"` in the chamber soak step.
   - `config/macros/macros.cfg`: update HEATSOAK's `TEMPERATURE_WAIT SENSOR="temperature_fan chamber"` → `SENSOR="heater_generic chamber"`.
   - `config/macros/lcd_tweaks.cfg`: update display `printer['temperature_fan chamber']` → `printer['heater_generic chamber']`.
   - `config/macros/_user_variables.cfg`: variable changes per Tuning section.
   - `config/client_hooks.cfg`: `_CANCEL_PRINT_HOOK` — remove its immediate `SET_CHAMBER_TARGET TARGET=0` to match the PRINT_END pattern. Chamber stays warm through MMU_END's unload + the G4 cooldown for VOC capture. The eventual `OFF` inside `_PRINT_END_CLEANUP` zeros it. ABS cancels benefit from VOC capture as much as graceful ABS ends do.
2. **Local tests** — `make test-py` (klippy parse, refcheck, pytest) must be green before deploy.
3. **Manual deploy to Pi** (no `/deploy-to-pi` yet — we want to PID_CALIBRATE first, which will modify the cal table on the Pi side). Stage via direct SSH edits on a separate Pi-side branch, RESTART.
4. **PID_CALIBRATE session** — bed to 110, wait, run cal, SAVE_CONFIG. Capture the Kp/Ki/Kd values for the commit message.
5. **Validation print** — short ABS test object. Observe: time to target, overshoot magnitude, BedFans behavior throughout, PRINT_END VOC ramp-up.
6. **PR creation + CI** — push branch, open PR. Once green, squash-merge to main.
7. **/sync-from-pi → commit final cal values to repo.**

### Rollback

If validation reveals broken behavior:

```sh
ssh pi@mainsailos.local "cp ~/printer_data/config/printer.cfg.pre-chamber-refactor ~/printer_data/config/printer.cfg"
ssh pi@mainsailos.local "sudo systemctl restart klipper"
git revert <pr-merge-commit>
```

The pre-refactor cal data + tap_threshold sit at the current main HEAD (PR #109's chore(sync) commit). Today's eddy reposition work is not at risk.

## Open considerations

- **PID_CALIBRATE result variance.** Ziegler-Nichols on a fan plant is uncertain. First validation print is the real test. Manual tuning fallback documented above.
- **Verify_heater values may need iteration.** Start permissive, tighten if real trips don't occur. Loose verify_heater for a fan-only "heater" is fine because there's no resistive element to runaway.
- **`print_end_cooldown_seconds` tuning.** Current value is **60 seconds**. With this refactor it becomes the post-print VOC window — recommend bumping to **300-600 s** (5-10 min) for ABS. Could split into per-material values later if needed.
- **Per-filament chamber target persistence.** Each ABS filament profile in OrcaSlicer already sets `chamber_temperature: 55`. The new architecture relies on this — no new slicer-side work.
- **HEATSOAK macro** still calls SET_CHAMBER_TARGET. Works transparently.

## Out of scope

- Extending eddy drift cal range (separate work — issue #25)
- MMU gate temperature behavior (user dropped earlier this session)
- Per-filament VOC baseline temperatures (not yet justified)
- Exhaust fan automation (post-deploy decision — observe whether passive cooling is sufficient before re-adding any auto-trigger)
- VOC floor enforcement on BedFans during `user_target > 0` mode (deferred — user accepts this is probably moot since PID will be driving BedFans most of the time in heated-chamber mode)

## References

- `vendor/klipper/docs/Config_Reference.md#heater_generic`
- `vendor/klipper/docs/Config_Reference.md#verify_heater`
- `vendor/klipper/docs/Command_Templates.md#delayed_gcode`
- Current architecture: `config/macros/chamber_control.cfg` (post-PR #110)
- Lifecycle spec: `docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`
- Research (community patterns): brainstorming session 2026-05-22, findings noted in this spec's Problem and Architecture sections
