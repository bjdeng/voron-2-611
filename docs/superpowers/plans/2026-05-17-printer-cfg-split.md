# Split `printer.cfg` by subsystem — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the body of `config/printer.cfg` (everything except MCU declarations and the SAVE_CONFIG block) into four function-organized siblings: `motion.cfg`, `bed.cfg`, `display.cfg`, `system.cfg`. Behavior must not change.

**Architecture:** Pure structural move. Each `[section]` block relocates verbatim to its new file with no edits to the body. `printer.cfg` shrinks to two `[mcu]` declarations, `[include]` statements, and the SAVE_CONFIG block. Klipper's `_strip_duplicates` + `_disallow_include_conflicts` (configfile.py:340) keep autosave merging intact because no section body declares any option that the SAVE_CONFIG block sets.

**Tech Stack:** Klipper config files. Plain text moves. Verification via existing test pyramid (L1 pre-commit, L2/L4 macro_refcheck, L5 structural pytest, L3 klippy parse in CI, L7 snapshot diff via Docker).

**Source spec:** [`docs/superpowers/specs/2026-05-17-printer-cfg-split-design.md`](../specs/2026-05-17-printer-cfg-split-design.md)

**Closes:** [#63](https://github.com/bjdeng/voron-2-611/issues/63)

---

## Pre-flight (worktree)

This plan assumes you are working in an isolated git worktree branched from `origin/main` (e.g., `feat/printer-cfg-split`). If not, stop and create one — the L7 "before" snapshot in Task 1 must capture `origin/main`'s behavior, so no edits may exist when Task 1 runs.

Confirm the starting state:

```bash
git status                               # should be clean (modulo untracked .claude/ noise)
git log --oneline -1                     # HEAD should match origin/main
docker --version                         # Docker is required for L7 (Klipper C extension needs Linux headers)
```

## File map

| Task | Created | Modified |
|---|---|---|
| 1 | `tests/snapshots/macro_behavior_before.txt` (overwritten) | — |
| 2 | `config/motion.cfg` | `config/printer.cfg` |
| 3 | `config/bed.cfg` | `config/printer.cfg` |
| 4 | `config/display.cfg` | `config/printer.cfg` |
| 5 | `config/system.cfg` | `config/printer.cfg` |
| 6 | — | `.github/workflows/ci.yml`, `tests/test_macro_refcheck.py`, `Makefile` |
| 7 | — | `CLAUDE.md` |
| 8 | — | — (test run only) |
| 9 | `tests/snapshots/macro_behavior_after.txt` (overwritten) | — |
| 10 | — | (commit snapshots + push) |

---

### Task 1: Capture pre-refactor L7 baseline

**Files:**
- Overwrite: `tests/snapshots/macro_behavior_before.txt`

This snapshot is the ground truth `origin/main` behavior. Capture it before any edits.

- [ ] **Step 1: Build the Layer 7 Docker image (one-time, ~2 minutes first run)**

```bash
make snapshot-image
```

Expected: `docker build` completes with `Successfully tagged voron-2-611-layer7:py311`.

- [ ] **Step 2: Capture the before-snapshot**

```bash
make snapshot-before
```

Expected output ends with something like `Wrote tests/snapshots/macro_behavior_before.txt (test_klippy exit=0)`.

- [ ] **Step 3: Verify the snapshot is non-empty and has the fixed gcode sequence**

```bash
wc -l tests/snapshots/macro_behavior_before.txt
grep -c "PARKCENTER\|BEDFANSSLOW\|HEATSOAK\|PRINT_END\|OFF" tests/snapshots/macro_behavior_before.txt
```

Expected: line count well above zero (typically several hundred); the grep count is at least 5 (one per fixed gcode invocation).

- [ ] **Step 4: Commit the baseline snapshot**

```bash
git add tests/snapshots/macro_behavior_before.txt
git commit -m "chore(test): capture L7 before-snapshot for printer.cfg split — #63"
```

---

### Task 2: Move motion sections to `config/motion.cfg`

**Files:**
- Create: `config/motion.cfg`
- Modify: `config/printer.cfg` (remove lines for `[printer]`, 6 steppers + 6 TMCs, `[input_shaper]`; add `[include motion.cfg]`)

- [ ] **Step 1: Create `config/motion.cfg` with the moved sections verbatim**

Create the file with this exact content:

```ini
## Motion subsystem.
##
## - [printer]                     CoreXY kinematics + global velocity/accel/SCV
## - [stepper_x] + [tmc2209 stepper_x]
## - [stepper_y] + [tmc2209 stepper_y]
## - [stepper_z*] + [tmc2209 stepper_z*]  (4 Z motors: front-left, rear-left,
##                                          rear-right, front-right)
## - [input_shaper]                Per-axis resonance compensation (values in
##                                 SAVE_CONFIG block in printer.cfg)

[printer]
kinematics: corexy
max_velocity: 450
max_accel: 10000
minimum_cruise_ratio: 0.5    # this is the klipper default
max_z_velocity: 100			 # Max 15 for 12V TMC Drivers, can increase for 24V
max_z_accel: 350   			 # Max ?
square_corner_velocity: 5.0  # Can experiment with 8.0, default 5.0

#####################################################################
#   X/Y Stepper Settings
#####################################################################
##  Connected to X on mcu_xye (B Motor)
[stepper_x]
step_pin: P2.2
dir_pin: !P2.6
enable_pin: !P2.1
rotation_distance: 40
microsteps: 128
full_steps_per_rotation: 200
endstop_pin: ^EBB:gpio13
position_min: 0
position_endstop: 350
position_max: 350
homing_speed: 80
second_homing_speed: 15
homing_retract_dist: 5
homing_positive_dir: true

[tmc2209 stepper_x]
uart_pin: P1.10
interpolate: False
run_current: 0.8
sense_resistor: 0.110
stealthchop_threshold: 0

##  Connected to Y on mcu_xye (A Motor)
[stepper_y]
step_pin: P0.19
dir_pin: !P0.20
enable_pin: !P2.8
rotation_distance: 40
microsteps: 128
full_steps_per_rotation:200
endstop_pin: P1.29
position_min: 0
position_endstop: 355
position_max: 355
homing_speed: 80
second_homing_speed: 15
homing_retract_dist: 5
homing_positive_dir: true

[tmc2209 stepper_y]
uart_pin: P1.9
interpolate: False
run_current: 0.8
sense_resistor: 0.110
stealthchop_threshold: 0

#####################################################################
#   Z Stepper Settings
#####################################################################
## Z MCU - In X Position
## Z0 Stepper - Front Left
[stepper_z]
step_pin: z:P2.2
dir_pin: !z:P2.6
enable_pin: !z:P2.1
rotation_distance: 40
gear_ratio: 80:16
microsteps: 128
endstop_pin: probe:z_virtual_endstop
position_max: 330
position_min: -5
homing_speed: 15.0
second_homing_speed: 3.0
homing_retract_dist: 2.0

[tmc2209 stepper_z]
uart_pin: z:P1.10
interpolate: False
run_current: 0.6
sense_resistor: 0.110
stealthchop_threshold: 0

##  Z MCU - In Y Position
##  Z1 Stepper - Rear Left
[stepper_z1]
step_pin: z:P0.19
dir_pin: z:P0.20
enable_pin: !z:P2.8
rotation_distance: 40
gear_ratio: 80:16
microsteps: 128

[tmc2209 stepper_z1]
uart_pin: z:P1.9
interpolate: False
run_current: 0.6
sense_resistor: 0.110
stealthchop_threshold: 0

##  Z MCU - In Z Position
##  Z2 Stepper - Rear Right
[stepper_z2]
step_pin: z:P0.22
dir_pin: !z:P2.11
enable_pin: !z:P0.21
rotation_distance: 40
gear_ratio: 80:16
microsteps: 128

[tmc2209 stepper_z2]
uart_pin: z:P1.8
interpolate: False
run_current: 0.6
sense_resistor: 0.110
stealthchop_threshold: 0

##  Z MCU - In E0 Position
##  Z3 Stepper - Front Right
[stepper_z3]
step_pin: z:P2.13
dir_pin: z:P0.11
enable_pin: !z:P2.12
rotation_distance: 40
gear_ratio: 80:16
microsteps: 128

[tmc2209 stepper_z3]
uart_pin: z:P1.4
interpolate: False
run_current: 0.6
sense_resistor: 0.110
stealthchop_threshold: 0

#####################################################################
# 	Input Shaping
#####################################################################
[input_shaper]
shaper_type: mzv
```

The body is byte-identical to `printer.cfg:16-157` (use `git show HEAD:config/printer.cfg | sed -n '16,157p'` to confirm if needed).

- [ ] **Step 2: Edit `config/printer.cfg` to remove the moved sections and add the include**

Open `config/printer.cfg`. Delete lines covering `[printer]` through the end of `[input_shaper]` (the original lines 16–157, ending just before the `# Bed Heater` divider). Insert the `[include motion.cfg]` line in the include block (Step 3) and leave a single blank line where the deleted content used to be — that area now looks like:

```ini
##  MCU for Z steppers
[mcu z]
serial: /dev/serial/by-id/usb-Klipper_lpc1769_1560011845084AAF45F07F5DC52000F5-if00

#####################################################################
#   Bed Heater
#####################################################################
##  SSR Pin - Z board, Fan Pin
[heater_bed]
...
```

(`[heater_bed]` still lives inline in `printer.cfg` after this task — it moves in Task 3.)

- [ ] **Step 3: Add `[include motion.cfg]` to the include block in `printer.cfg`**

Locate the comment `# MCU + hardware` (immediately above `[include toolhead.cfg]`). Replace it and the line after with:

```ini
# Mainboard-resident subsystems (function-organized — see CLAUDE.md `## Repo layout`)
[include motion.cfg]      # kinematics + steppers + TMCs + input shaping

# Toolhead MCU (EBB SB v1.0 on USB)
[include toolhead.cfg]
```

- [ ] **Step 4: Commit**

```bash
git add config/motion.cfg config/printer.cfg
git commit -m "chore(config): move motion sections to motion.cfg — #63"
```

---

### Task 3: Move bed sections to `config/bed.cfg`

**Files:**
- Create: `config/bed.cfg`
- Modify: `config/printer.cfg`

- [ ] **Step 1: Create `config/bed.cfg` with the moved sections verbatim**

```ini
## Bed + chamber thermal subsystem.
##
## - [heater_bed]                  SSR-driven bed heater (z:P2.3). PID values
##                                 live in printer.cfg's SAVE_CONFIG block.
## - [thermistor 10k_thermistor]   Defines the chamber thermistor type
##                                 (custom T/R calibration table). Must stay
##                                 in the same file as [temperature_fan chamber]
##                                 which consumes it.
## - [temperature_fan chamber]     Chamber heater fan (PID, z:P2.7).
## - [heater_fan controller_fan]   Electronics-bay fan, triggered by
##                                 heater: heater_bed at 45 °C. Semantically
##                                 slaved to the bed → lives here, not in system.cfg.
## - [quad_gantry_level]           Pre-print Z leveling. The QUAD_GANTRY_LEVEL
##                                 macro override (2-pass, intentional —
##                                 see memory/qgl-two-pass-intentional.md)
##                                 lives in eddy.cfg.

#####################################################################
#   Bed Heater
#####################################################################
##  SSR Pin - Z board, Fan Pin
[heater_bed]
heater_pin: z:P2.3
sensor_type: NTC 100K MGB18-104F39050L32
sensor_pin: z:P0.25
max_power: 0.8
min_temp: 0
max_temp: 120

#####################################################################
# 	Chamber Temp
#####################################################################
[thermistor 10k_thermistor]
temperature1: 25
resistance1: 10000
temperature2: 45
resistance2: 4367
temperature3: 75
resistance3: 1480

[temperature_fan chamber]
pin: z:P2.7
max_power: 0.6
shutdown_speed: 0
kick_start_time: 0.5
cycle_time: 0.03
sensor_type: 10k_thermistor
sensor_pin: z:P0.24
min_temp: 0
max_temp: 70
target_temp: 0
max_speed: 1.0
min_speed: 0
control: pid
hardware_pwm: false
pid_Kp: 40
pid_Ki: 0.2
pid_Kd: 0.1
pid_deriv_time: 2.0
gcode_id: C

#####################################################################
#   Fan Control
#####################################################################
##  Controller fan - Z board, HE1 Connector
[heater_fan controller_fan]
pin: z:P2.4
max_power: 1.0        # BJD 9/16/2020 quiet these down but keep enough airflow to cool the steppers
cycle_time: 0.025     # 0.03 # BJD 9/16/2020 seems to be a god compromise with this speed to minimize whining defailt is 0.010
kick_start_time: 0.5
heater: heater_bed
heater_temp: 45.0
fan_speed: 0.25       # 0.2 #BJD 9/16/2020 quiet these down but keep enough airflow to cool the steppers
shutdown_speed: 1

#####################################################################
#   Quad Gantry Level
#####################################################################
[quad_gantry_level]
gantry_corners:
	-60, 5
	410, 425
points:
	50, 25
	50, 275
	300, 275
	300, 25
speed: 450
horizontal_move_z: 10
retries: 5
retry_tolerance: 0.05
max_adjust: 10
```

Bodies are byte-identical to the originals in `printer.cfg` (heater_bed lines 163-169; chamber thermal 174-201; controller_fan 207-215; quad_gantry_level 255-268). Section divider comments preserved.

- [ ] **Step 2: Remove the moved sections from `config/printer.cfg`**

Delete the following spans from `printer.cfg`:
- The `# Bed Heater` divider through the end of `[heater_bed]` (original lines ~159-169)
- The `# Chamber Temp` divider through the end of `[temperature_fan chamber]` (original lines ~171-201)
- The `# Fan Control` divider through the end of `[heater_fan controller_fan]` (original lines ~203-215)
- The `# Homing and Gantry Adjustment Routines` divider line and the `[quad_gantry_level]` block (original lines ~240-268, **but NOT `[idle_timeout]` lines 243-253** — that moves in Task 5).

If the `# Homing and Gantry Adjustment Routines` divider directly precedes `[idle_timeout]`, keep the divider for now (Task 5 will remove it together with `[idle_timeout]`). The exact divider placement doesn't affect Klipper.

- [ ] **Step 3: Add `[include bed.cfg]` to the include block in `printer.cfg`**

Append immediately after `[include motion.cfg]`:

```ini
[include bed.cfg]         # bed heater + chamber thermal + QGL + controller fan
```

- [ ] **Step 4: Commit**

```bash
git add config/bed.cfg config/printer.cfg
git commit -m "chore(config): move bed + chamber + QGL sections to bed.cfg — #63"
```

---

### Task 4: Move display sections to `config/display.cfg`

**Files:**
- Create: `config/display.cfg`
- Modify: `config/printer.cfg`

- [ ] **Step 1: Create `config/display.cfg` with the moved sections verbatim**

```ini
## Display subsystem — fysetc Mini12864 on the main MCU's EXP1/EXP2 headers.
##
## - [board_pins]                  EXP1/EXP2 pin aliases (consumed only by
##                                 the sections below).
## - [display]                     uc1701 LCD; encoder + click; renders the
##                                 __voron_display group from lcd_tweaks.cfg.
## - [output_pin beeper]
## - [neopixel lcd]                3-LED chain on the display backboard.
##
## SB-LED chain on the toolhead is NOT here — there is no SB-LED on this build
## (only the LCD neopixels above).

#####################################################################
#   Displays
#####################################################################
# BJD 9/8/2020 per https://discord.com/channels/460117602945990666/460172848565190667/724803977790750750
# Code for mini12864 display on SKR1.4
[board_pins]
aliases:
    # EXP1 header
    EXP1_1=P1.30, EXP1_3=P1.18, EXP1_5=P1.20, EXP1_7=P1.22, EXP1_9=<GND>,
    EXP1_2=P0.28, EXP1_4=P1.19, EXP1_6=P1.21, EXP1_8=P1.23, EXP1_10=<5V>,
    # EXP2 header
    EXP2_1=P0.17, EXP2_3=P3.26, EXP2_5=P3.25, EXP2_7=P1.31, EXP2_9=<GND>,
    EXP2_2=P0.15, EXP2_4=P0.16, EXP2_6=P0.18, EXP2_8=<RST>, EXP2_10=<NC>

[display]
lcd_type: uc1701
cs_pin: EXP1_3
a0_pin: EXP1_4
rst_pin: EXP1_5
contrast: 63
encoder_pins: ^EXP2_5, ^EXP2_3
click_pin: ^!EXP1_2
display_group: __voron_display
menu_timeout: 60

[output_pin beeper]
pin: EXP1_1

# fysetc_mini12864
[neopixel lcd]
pin: EXP1_6
chain_count: 3
color_order: RGB
initial_RED: 0.4 ;0.0
initial_GREEN: 0.4 ;0.0
initial_BLUE: 0.4 ; 0.0
```

Body is byte-identical to `printer.cfg:270-305` (preserves the discord-link reference comment).

- [ ] **Step 2: Remove the moved sections from `config/printer.cfg`**

Delete the `# Displays` divider through the end of `[neopixel lcd]` (original lines ~270-305).

- [ ] **Step 3: Add `[include display.cfg]` to the include block in `printer.cfg`**

Append immediately after `[include bed.cfg]`:

```ini
[include display.cfg]     # mini12864 LCD, beeper, neopixel
```

- [ ] **Step 4: Commit**

```bash
git add config/display.cfg config/printer.cfg
git commit -m "chore(config): move display sections to display.cfg — #63"
```

---

### Task 5: Move system sections to `config/system.cfg`

**Files:**
- Create: `config/system.cfg`
- Modify: `config/printer.cfg`

- [ ] **Step 1: Create `config/system.cfg` with the moved sections verbatim**

```ini
## System / housekeeping subsystem.
##
## - [temperature_sensor raspberry_pi]    Pi SoC temperature (diagnostic).
## - [output_pin caselight]               Chamber light PWM (P2.5, on the main
##                                        MCU's bed-temp connector).
## - [idle_timeout]                       Custom Ellis-style idle handler that
##                                        parks the toolhead and powers down.
##
## NOTE: temperature_mcu is NOT supported on lpc1769 (per
## vendor/klipper/klippy/extras/temperature_mcu.py — only rp2, sam3/4,
## samd21/51, stm32f/g/l/h7 are supported). We cannot add die-temp sensors
## for the two SKR 1.4 boards. The Eddy MCU temp sensor at
## [temperature_sensor btt_eddy_mcu] in config/eddy.cfg works because the
## BTT Eddy is an RP2040.

[temperature_sensor raspberry_pi]
sensor_type: temperature_host
min_temp: 0
max_temp: 100

#####################################################################
#   LED Control
#####################################################################
# Chamber Lighting - Bed Connector (Optional)
[output_pin caselight]
pin: P2.5
pwm: True
shutdown_value: 0
value: 0
cycle_time: 0.001

#####################################################################
#   Idle Timeout
#####################################################################
[idle_timeout]
# custom used in andrew ellis' profile. default is just "timeout: 1800"
gcode:
    {% if "xyz" in printer.toolhead.homed_axes %}
        G91                                                                                                 ; relative positioning
        G1 Z5 F18000.0                                                                                      ; move up 5mm
        G90                                                                                                 ; absolute positioning
        G1 X{printer.toolhead.axis_maximum.x} Y{printer.toolhead.axis_maximum.y} F18000.0                   ; park nozzle at rear
    {% endif %}
    OFF                                                                                                     ; turn everything off                                                                                     ; set logo back to white
timeout: 7200 ; 2 hrs
```

Bodies are byte-identical to the originals: `[temperature_sensor raspberry_pi]` lines 217-220; the `temperature_mcu` note lines 222-227 (slightly reformatted as the file header above); `[output_pin caselight]` lines 233-238; `[idle_timeout]` lines 243-253. **Verify the gcode template inside `[idle_timeout]` has not been re-indented or trailing whitespace stripped** — Klipper jinja2 is whitespace-sensitive in surprising ways. The cleanest way is to use a multi-line copy from `git show HEAD:config/printer.cfg` rather than re-typing.

- [ ] **Step 2: Remove the moved sections from `config/printer.cfg`**

Delete from `printer.cfg`:
- `[temperature_sensor raspberry_pi]` (original lines ~217-220)
- The `temperature_mcu`-not-supported note (original lines ~222-227)
- The `# LED Control` divider through the end of `[output_pin caselight]` (original lines ~229-238)
- The `# Homing and Gantry Adjustment Routines` divider (if still present after Task 3) and the `[idle_timeout]` block (original lines ~240-253).

After this task, `printer.cfg` body between `[mcu z]` and the include block should contain **only blank line(s)** — every Klipper config section has moved.

- [ ] **Step 3: Add `[include system.cfg]` to the include block in `printer.cfg`**

Append immediately after `[include display.cfg]`:

```ini
[include system.cfg]      # raspberry pi temp, caselight, idle timeout
```

- [ ] **Step 4: Verify `printer.cfg` shape**

```bash
grep -nE "^\[" config/printer.cfg
```

Expected: only `[mcu]`, `[mcu z]`, and twelve `[include ...]` lines (no other `[section]` blocks above the SAVE_CONFIG marker). If anything else appears, a section was missed in Tasks 2-5 — fix before moving on.

- [ ] **Step 5: Commit**

```bash
git add config/system.cfg config/printer.cfg
git commit -m "chore(config): move system sections to system.cfg — #63"
```

---

### Task 6: Replace literal cfg file list with globs in CI + pytest fixture + Makefile

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_macro_refcheck.py`
- Modify: `Makefile`

Today three files enumerate `config/printer.cfg config/eddy.cfg config/toolhead.cfg config/mainsail.cfg config/timelapse.cfg` by hand. Replacing with `config/*.cfg` survives this split and any future ones.

- [ ] **Step 1: Update `.github/workflows/ci.yml`**

Find the block (around line 130):

```yaml
          python scripts/macro_refcheck.py \
            config/printer.cfg config/eddy.cfg config/toolhead.cfg config/mainsail.cfg config/timelapse.cfg \
            config/macros/*.cfg config/mmu/base/*.cfg config/mmu/addons/*.cfg config/mmu/optional/*.cfg
```

Replace with:

```yaml
          python scripts/macro_refcheck.py \
            config/*.cfg \
            config/macros/*.cfg config/mmu/base/*.cfg config/mmu/addons/*.cfg config/mmu/optional/*.cfg
```

The surrounding `shopt -s failglob` (line 129) catches accidental directory renames that empty the glob.

- [ ] **Step 2: Update `tests/test_macro_refcheck.py`**

Find (around lines 101-115):

```python
def test_real_repo_passes():
    """The repo's actual configs must pass macro_refcheck."""
    import glob

    cfgs = (
        [
            "config/printer.cfg",
            "config/eddy.cfg",
            "config/toolhead.cfg",
            "config/mainsail.cfg",
            "config/timelapse.cfg",
        ]
        + sorted(glob.glob("config/macros/*.cfg"))
        + sorted(glob.glob("config/mmu/base/*.cfg"))
        + sorted(glob.glob("config/mmu/addons/*.cfg"))
        + sorted(glob.glob("config/mmu/optional/*.cfg"))
    )
```

Replace with:

```python
def test_real_repo_passes():
    """The repo's actual configs must pass macro_refcheck."""
    import glob

    cfgs = (
        sorted(glob.glob("config/*.cfg"))
        + sorted(glob.glob("config/macros/*.cfg"))
        + sorted(glob.glob("config/mmu/base/*.cfg"))
        + sorted(glob.glob("config/mmu/addons/*.cfg"))
        + sorted(glob.glob("config/mmu/optional/*.cfg"))
    )
    assert any(c.endswith("printer.cfg") for c in cfgs), (
        "config/*.cfg glob did not match printer.cfg — directory renamed?"
    )
```

The added assertion replaces the (implicit) safety the literal list provided: if a directory rename empties the glob, the test fails loudly instead of silently testing nothing. (CI's `shopt -s failglob` does the same job on the workflow side.)

- [ ] **Step 3: Update `Makefile`**

Find (around line 7):

```make
CFGS        := config/printer.cfg config/eddy.cfg config/toolhead.cfg config/mainsail.cfg config/timelapse.cfg \
               $(wildcard config/macros/*.cfg) \
               $(wildcard config/mmu/base/*.cfg) \
               $(wildcard config/mmu/addons/*.cfg) \
               $(wildcard config/mmu/optional/*.cfg)
```

Replace with:

```make
CFGS        := $(wildcard config/*.cfg) \
               $(wildcard config/macros/*.cfg) \
               $(wildcard config/mmu/base/*.cfg) \
               $(wildcard config/mmu/addons/*.cfg) \
               $(wildcard config/mmu/optional/*.cfg)
```

- [ ] **Step 4: Run the pytest target and `make refcheck` locally**

```bash
make refcheck
.venv/bin/python -m pytest tests/test_macro_refcheck.py::test_real_repo_passes -v
```

Both must pass. If `make refcheck` reports unknown commands, a section was moved into a file with a macro body referencing a now-renamed identifier — investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/test_macro_refcheck.py Makefile
git commit -m "chore(ci): switch macro_refcheck cfg list to config/*.cfg glob — #63"
```

---

### Task 7: Update CLAUDE.md (repo layout + dual-axis paragraph)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the `## Repo layout` tree to list the new files**

Find the existing block (around line 488):

```
├── config/                      # everything that deploys to the Pi
│   ├── printer.cfg              # top-level Klipper config (includes everything below)
│   ├── eddy.cfg                 # Eddy probe + bed mesh + temperature_probe + SET_Z_FROM_PROBE pair
│   ├── toolhead.cfg             # toolhead MCU config (RP2040 EBB SB v1.0, USB mode)
│   ├── mainsail.cfg             # slimmed local copy (Phase 2); Pi symlink → ~/mainsail-config/mainsail.cfg means our copy doesn't deploy
│   ├── timelapse.cfg            # symlink target on Pi (unused per Ben)
```

Replace with:

```
├── config/                      # everything that deploys to the Pi
│   ├── printer.cfg              # 2× [mcu] + [include]s + SAVE_CONFIG (Klipper's entry point)
│   ├── motion.cfg               # [printer] + 6 steppers + 6 TMCs + [input_shaper]
│   ├── bed.cfg                  # heater_bed + chamber thermal + QGL + controller fan
│   ├── display.cfg              # mini12864 LCD: board_pins, display, beeper, neopixel
│   ├── system.cfg               # raspberry_pi temp, caselight, idle_timeout
│   ├── eddy.cfg                 # Eddy probe + bed mesh + temperature_probe + SET_Z_FROM_PROBE pair
│   ├── toolhead.cfg             # toolhead MCU config (RP2040 EBB SB v1.0, USB mode)
│   ├── mainsail.cfg             # slimmed local copy (Phase 2); Pi symlink → ~/mainsail-config/mainsail.cfg means our copy doesn't deploy
│   ├── timelapse.cfg            # symlink target on Pi (unused per Ben)
```

Also fix the stray blank line at line ~492 in the original (between mainsail.cfg and timelapse.cfg) — drop it as part of this edit so the tree stays clean.

- [ ] **Step 2: Add the dual-axis paragraph between the `## Repo layout` heading and the tree**

Find:

```
## Repo layout

```
voron-2-611/
```

Replace with:

```
## Repo layout

Files under `config/` use one of two organizing axes:

- **By feature or MCU** — `eddy.cfg`, `toolhead.cfg`, `mainsail.cfg`, `mmu/*`, `macros/*`. One coherent subsystem per file (the probe, the toolhead board, the UI client, the MMU, etc.). Replacing the underlying hardware = one file diff.
- **By function** — `motion.cfg`, `bed.cfg`, `display.cfg`, `system.cfg`. For mainboard-resident sections that don't form a coherent feature on their own. Introduced by [#63](https://github.com/bjdeng/voron-2-611/issues/63).

When adding a new section: prefer the feature axis if the section forms or extends a self-contained subsystem; fall back to the function axis only for "this is another mainboard fan / sensor / output_pin" cases.

```
voron-2-611/
```

(Yes, the heading should still read `## Repo layout` and the tree should still follow — the dual-axis paragraph sits between the heading and the tree.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): repo-layout — motion/bed/display/system + dual-axis rule — #63"
```

---

### Task 8: Run the local test pyramid (L1, L2, L4, L5)

**Files:** none modified (verification only).

- [ ] **Step 1: Run `make test-py`**

```bash
make test-py
```

This runs pre-commit (L1), macro_refcheck against the actual repo (L2), and the pytest suite (L4 + L5). All must pass.

Expected: zero failures. The structural-assertions test (`tests/test_config_structure.py`) auto-picks-up the four new files via `rglob`; no edits needed there.

If `test_extruder_declared_once` (in `test_config_structure.py`) fails: it means `[extruder]` ended up declared in more than one owned file. Re-check that you did NOT move it into `motion.cfg` — `[extruder]` stays in `toolhead.cfg`.

If `test_no_deprecated_klipper_config_keys` fails on one of the new files: you accidentally re-introduced a deprecated key while copy-pasting. Compare against `git show HEAD~6:config/printer.cfg`.

- [ ] **Step 2: If `make test-py` failed**

Fix the failure (no commit yet), re-run `make test-py`. Only proceed when it's clean. **Do not** commit "fixes" as separate commits in the snapshot/verification chain — fold them into the Task whose change introduced the issue using `git commit --fixup=<sha>` and squash before pushing.

---

### Task 9: Capture L7 after-snapshot and confirm zero behavior change

**Files:**
- Overwrite: `tests/snapshots/macro_behavior_after.txt`

- [ ] **Step 1: Capture the after-snapshot**

```bash
make snapshot-after
```

Expected: `Wrote tests/snapshots/macro_behavior_after.txt (test_klippy exit=0)`.

- [ ] **Step 2: Diff before/after (whitespace-insensitive)**

```bash
make snapshot-diff
```

Expected: **empty output (exit 0)**. A whitespace-insensitive diff of `before` vs `after` should produce zero lines — every macro renders the same gcode dispatcher output regardless of which file the underlying section was declared in.

- [ ] **Step 3: Interpreting any diff**

If `make snapshot-diff` produces output, the refactor introduced a behavior change. Most likely causes:

- A section moved into a file but a key was edited (typo, missing line, indentation change inside a jinja2 template).
- A section was duplicated (e.g., still present in `printer.cfg` AND a new file). Klipper takes the last-loaded definition silently — runtime is fine, but options that interact via lookup may differ.
- `[input_shaper]` body moved but the SAVE_CONFIG block tries to merge against the old name. Check `printer.cfg`'s SAVE_CONFIG block is untouched.

Fix the offending file, re-run `make snapshot-after`, re-diff. **Do not push until the diff is empty.**

- [ ] **Step 4: Commit the after-snapshot**

```bash
git add tests/snapshots/macro_behavior_after.txt
git commit -m "chore(test): capture L7 after-snapshot — empty diff vs before — #63"
```

---

### Task 10: Push, open PR, monitor CI

**Files:** none modified.

- [ ] **Step 1: Pre-push sanity check**

```bash
git log --oneline origin/main..HEAD
```

Expected: ~8 commits in this branch (snapshot-before; 4× section moves; CI glob; CLAUDE.md; snapshot-after). All commits should reference `#63`.

- [ ] **Step 2: Run pr-review-toolkit locally**

Invoke `Skill: pr-review-toolkit:review-pr` against the branch. Address any findings inline (preferably as `--fixup` commits squashed before push, per [[feedback_subagent_no_amend]]).

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin HEAD
gh pr create --title "Split printer.cfg by subsystem (motion / bed / display / system) — #63" \
  --body "$(cat <<'EOF'
## Summary
- Split `config/printer.cfg` into `motion.cfg` / `bed.cfg` / `display.cfg` / `system.cfg`. Pure structural move; no behavior change.
- `printer.cfg` shrinks to the two `[mcu]` declarations, the include block, and the SAVE_CONFIG block.
- Documents the repo's two organizing axes (feature/MCU vs function) in CLAUDE.md `## Repo layout`.
- Replaces the literal cfg file list in CI + `tests/test_macro_refcheck.py` with `config/*.cfg` so future splits don't need CI edits.

Closes #63. Source spec: `docs/superpowers/specs/2026-05-17-printer-cfg-split-design.md`.

## Test plan
- [ ] L1 pre-commit (CI)
- [ ] L2 macro_refcheck (CI; now globs config/*.cfg)
- [ ] L3 klippy parse (CI; the gate that proves the config still loads)
- [ ] L4/L5 pytest (CI)
- [ ] L7 snapshot diff (local; whitespace-insensitive diff of tests/snapshots/macro_behavior_{before,after}.txt is empty — committed to this branch)
- [ ] Post-merge: /deploy-to-pi runs L6 (post-deploy smoke). G28, QUAD_GANTRY_LEVEL, BED_MESH_CALIBRATE, RESTART all succeed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI**

```bash
gh pr checks --watch
```

Expected: every job green. L3 (klippy-smoke) is the gate that fails loudly if any section was missed during the moves.

- [ ] **Step 5: Squash-merge once green and PR is approved**

After merge, on `main`:

```bash
/deploy-to-pi
```

The skill runs L6 (post-deploy printer smoke) on the Pi. If smoke fails, roll back via `git revert` on `main` and re-deploy — the change is purely structural so revert is safe.

---

## Self-review notes

- **Spec coverage:** Every section of the spec maps to a task. §3.1 (dual-axis paragraph) → Task 7. §3.2 (file layout) → Tasks 2-5. §3.3 (section assignments) → Tasks 2-5 (verbatim). §3.4 (new printer.cfg shape) → Tasks 2-5 incrementally + Task 5 Step 4 grep verification. §3.5 (headers) → Tasks 2-5 Step 1. §3.6 (include order) → Tasks 2-5 Step 3 (motion/bed/display/system go in that order; the existing toolhead/eddy/mmu/mainsail/timelapse/macros block is preserved). §3.7 (SAVE_CONFIG behavior) → no explicit task; the bodies in Tasks 2-5 deliberately don't declare any autosaved option so `_disallow_include_conflicts` stays satisfied. §4 (testing) → Tasks 1, 8, 9. §5 (touch points) → Tasks 6, 7. §6 (PR strategy) → Task 10. §7 (anti-criteria) → enforced by L7 snapshot diff in Task 9.
- **Placeholder scan:** No TBDs, TODOs, or "add appropriate error handling" — every step has either exact code or an exact command and expected output.
- **Type consistency:** N/A (no code interfaces; only file content moves).

## References

- Spec: [`docs/superpowers/specs/2026-05-17-printer-cfg-split-design.md`](../specs/2026-05-17-printer-cfg-split-design.md)
- Issue: [#63](https://github.com/bjdeng/voron-2-611/issues/63)
- L7 harness Makefile targets: `snapshot-image`, `snapshot-before`, `snapshot-after`, `snapshot-diff`
- Klipper SAVE_CONFIG semantics: `vendor/klipper/klippy/configfile.py:339-345` (_disallow_include_conflicts), `:358` (cfgname resolution)
