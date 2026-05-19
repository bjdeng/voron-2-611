# Voron 2.611 — Klipper config repo

This repo is the canonical source of truth for the Klipper/Mainsail/Happy-Hare configuration of Ben's Voron 2.4. The on-printer filesystem at `~/printer_data/config/` is the working copy; this repo is where changes are reviewed and tracked. The workflow is: **edit here → PR → merge to `main` → `/deploy-to-pi` to sync to the printer**. The deploy step is currently a manual skill invocation; full automation on merge is tracked in [#28](https://github.com/bjdeng/voron-2-611/issues/28). Machine state (the files that deploy to the Pi) lives under `config/`; tooling around it (scripts/, tests/, docs/, vendor/, memory/, CI) lives at root.

---

## Printer identity

- **Model:** Voron 2.4 r2
- **Build size:** 350 mm
- **Community serial:** **2.611** (rendered on the LCD via `config/macros/lcd_tweaks.cfg:126`; not a date or kit number)
- **Commissioned:** ~2020 (≈6 years in service as of 2026)
- **Build origin:** self-sourced from the original V2.4 r2 BOM, heavily modified since
- **Macro lineage:** Andrew Ellis's `v2.247_backup_klipper_config` (visible in `BJD 9/16/2020`-era comments)

The machine has years of trial-and-error baked into it. **Do not assume the current state is intentional or that every installed piece of software is needed.** Investigate before "tidying" — see [Known quirks](#known-quirks).

---

## Hardware inventory

### Frame & motion
- 350 × 350 × ~300 mm build volume (Z position_max = 330, used max ≈ 335 per mesh)
- CoreXY kinematics, quad gantry leveling (QGL — not Z-tilt; this is a V2, not a Trident)
- **MGN12 X carriage** (upgraded from stock MGN9)
- Beefy idlers mod

### Toolhead
- **Stealthburner v2** body (no SB LEDs installed — only the LCD neopixel chain in `[neopixel lcd]`)
- **Galileo extruder** — explains the unusual `gear_ratio: 9:1` + `rotation_distance: 48.033` in `config/toolhead.cfg`
- **Dragon clone hotend** (vendor unknown; behaves Dragon-compatible)
- 0.4 mm nozzle, 1.75 mm filament (Generic 3950 thermistor, pullup 2200 Ω)
- **LIS2DW** accelerometer on toolhead (for resonance testing); `axes_map: z,x,y`

### Probe
- **BTT Eddy** running Klipper's native `[probe_eddy_current btt_eddy]` (migrated from `vvuk/eddy-ng` in PR #17, 2026-05-15)
- Linked `[temperature_probe btt_eddy]` for thermal drift compensation (shares the postfix; same NTC on `eddy:gpio26`)
- `reg_drive_current: 15` (carried over from prior eddy-ng calibration; same LDC1612 register)
- Probe offset: `x_offset: 0`, `y_offset: 21.42`
- `[bed_mesh] fade_target: 0` + `zero_reference_position: 175, 175` paired with tap workflow (matches the homing_override's Z-home XY position)
- Tap-Z application uses the doc-blessed split-macro pattern: `SET_Z_FROM_PROBE` (runs `PROBE METHOD=tap`) then `_RELOAD_Z_OFFSET_FROM_PROBE` (applies the result via `SET_KINEMATIC_POSITION`). Two macros because jinja templates render once per macro — see [Klipper gotchas](#klipper-gotchas).
- Tap-Z auto-applies via `[homing_override] axes: z` in `config/eddy.cfg` — every `G28 Z` (or full `G28`) runs `SET_Z_FROM_PROBE` automatically, including ad-hoc homes from the Mainsail console. `G28 X` / `G28 Y` alone bypass the override.

### Bed
- Textured PEI **magnetic flex plate**
- Silicone heater (NTC 100K MGB18-104F39050L32 thermistor)
- **SSR** for bed heater (max_power 0.8)
- Ellis-style **BedFans** with a modified housing including a **charcoal filter** (https://www.printables.com/model/334276-the-filter-for-voron-24); threshold 100 °C, fast=0.6, slow=0.2

### Chamber
- Active control via `[temperature_fan chamber]` on `z:P2.7` with a 10k_thermistor on `z:P0.24` (custom temperature/resistance table)

### Display & lighting
- fysetc Mini12864 (EXP1/EXP2 on the XYE SKR 1.4)
- 3-LED Neopixel chain on the display
- **Caselight** (PWM output_pin on `P2.5` on the XYE board)

### MMU (Multi-Material Unit)
- **Self-printed ERCF v2** (Enraged Rabbit Carrot Feeder, community edition v2.0)
- 6 gates, BTT EASY-BRD MCU (SAMD21G18A)
- LinearSelector + selector servo + Binky-style encoder
- **No buffer** — spools sit on **Filamentalist rewinders**
- Add-ons enabled: **Blobifier** (purge tower). **Filametrix** is the toolhead filament cutter ([Carrot-collective/Filametrix](https://github.com/Carrot-collective/Filametrix)) — driven via `_MMU_CUT_TIP` which Happy Hare invokes during toolchange (`config/mmu/base/mmu_cut_tip.cfg`, with cutter pin location in `config/mmu/base/mmu_macro_vars.cfg::_MMU_CUT_TIP_VARS`).
- **Files present but NOT active:** `config/mmu/addons/mmu_erec_cutter.cfg` and `mmu_eject_buttons.cfg` are not `[include]`d from `config/printer.cfg`. EREC is NOT used (Filametrix is); eject buttons are NOT installed.
- Toolhead/extruder filament sensors on the EBB board (gpio6, gpio21)
- Sync feedback: tension switch on `mmu:PA7` (compression switch not connected)

### Additional temperature sensors (worth knowing about)

Beyond `[heater_bed]` + `[extruder]` + `[temperature_fan chamber]`, these sensors are wired and active for diagnostics:

| Section | Source | Notes |
|---|---|---|
| `[temperature_probe btt_eddy]` | Generic 3950 NTC on `eddy:gpio26` | Coil-adjacent; linked to `[probe_eddy_current btt_eddy]` for drift comp |
| `[temperature_sensor btt_eddy_mcu]` | RP2040 die temp | MCU temperature for the Eddy board |
| `[temperature_sensor EBB_NTC]` | Generic 3950 NTC on `EBB:gpio27` | NTC on the EBB toolhead board |
| `[temperature_sensor raspberry_pi]` | `temperature_host` | Pi SoC temperature |

**`sensor_type: temperature_mcu` is NOT supported on LPC1769** (per `vendor/klipper/klippy/extras/temperature_mcu.py` supported list: rp2/sam3/sam4/samd21/samd51/stm32f1-4/stm32g0/stm32g4/stm32l4/stm32h7). Cannot add die-temp sensors for the two SKR 1.4 boards; the Eddy MCU temp sensor works because it's an RP2040.

### Installed but **not** in active use (per Ben, 2026-05-13)
- **moonraker-timelapse** — installed 2026-05-18 (closed #26; missed install step had left the Moonraker component dormant since initial setup). Active but **opt-in per print**: Ben does not have `TIMELAPSE_TAKE_FRAME` wired into OrcaSlicer's layer-change gcode by default. Two ways to invoke: (a) add `TIMELAPSE_TAKE_FRAME` to a specific print's slicer custom gcode, or (b) `HYPERLAPSE ACTION=START [CYCLE=30]` in the Mainsail console before starting a print, `HYPERLAPSE ACTION=STOP` after. Both require a webcam (currently unplugged — see below + #27).
- **Webcam** — physically unplugged because of timing/streaming issues. Crowsnest + Sonar daemons still run. Plan: re-enable after Eddy NG → native Klipper Eddy migration.
- **Spoolman** — Moonraker is configured against an external Spoolman at [`spoolman-server`](../.claude/projects/-Users-ben-code-voron-2-611/memory/spoolman-server.md) (http://192.168.0.89:7912 on Ben's LAN), but Ben isn't fully using it.

---

## MCU map

The printer uses **5 USB-attached MCUs** (no CAN bus, despite the toolhead board name suggesting it). Always confirm USB serials with `ls -l /dev/serial/by-id/` on the Pi when adding/replacing hardware.

| Klipper name | Board | MCU | Serial | Role |
|---|---|---|---|---|
| `mcu` | BTT SKR 1.4 | LPC1769 | `usb-Klipper_lpc1769_05E0FF1627903CAF12CA6D5CC62000F5-if00` | X/Y steppers, extruder uart-mux home (EBB connects too), main MCU. Also drives caselight, beeper, mini12864, neopixel LCD. |
| `mcu z` | BTT SKR 1.4 | LPC1769 | `usb-Klipper_lpc1769_1560011845084AAF45F07F5DC52000F5-if00` | Four Z steppers, bed heater (SSR via z:P2.3), controller fan, bedfans, chamber heater fan, chamber thermistor |
| `mcu EBB` | BTT EBB SB v1.0 (USB mode) | RP2040 | `usb-Klipper_rp2040_5044340310C4D61C-if00` | Extruder stepper, hotend heater, part fan, hotend fan, LIS2DW accel, toolhead filament sensors |
| `mcu eddy` | BTT Eddy | RP2040 | `usb-Klipper_rp2040_5044340310B85E1C-if00` | Eddy probe (LDC1612 sensor + MCU temperature sensor) |
| `mcu mmu` | ERCF EASY-BRD | SAMD21G18A | `usb-Klipper_samd21g18a_B8D81297503854512020204E2F1C13FF-if00` | MMU gear stepper, selector stepper, selector servo, encoder, selector endstop, sync feedback tension switch |

**Firmware build kconfigs are vendored in `config/firmware/`** (pulled from `~/klipper-kconfigs/` on the Pi):
- `config/firmware/mcu.config` — both SKR 1.4 boards (LPC1769 with USB)
- `config/firmware/ebb-usb.config` — EBB SB v1.0 (RP2040 with USB, not CAN)
- `config/firmware/eddy.config` — BTT Eddy (RP2040 with USB; loaded by eddy-ng)
- `config/firmware/easy-brd.config` — ERCF EASY-BRD (SAMD21G18A)

When recompiling a board's firmware, drop the matching file into `~/klipper/.config` before `make`.

---

## Macro inventory

Every active macro and where it lives. One-liner per macro; deeper context belongs in the file itself or in [`memory/decisions.md`](memory/decisions.md).

### `config/macros/macros.cfg` — Ellis-derived utilities
- `_CG28` — `G28` only if not already homed
- `_CQGL` — `QUAD_GANTRY_LEVEL` only if not already applied
- `CASELIGHT_ON` / `CASELIGHT_OFF` — case light helpers (default ON brightness 0.3, overridable with `VALUE=`). Match the `BEDFANS*` pattern. Added 2026-05-18.
- `OFF` — shut everything off (steppers, heaters, part fan, chamber fan, bed fan, calls `CASELIGHT_OFF`)
- `SHUTDOWN` — `OFF` + tell Moonraker to power off the host
- `PARKFRONT` / `PARKFRONTLOW` / `PARKREAR` / `PARKCENTER` / `PARKBED` — toolhead parking positions
- `_RESETSPEEDS` — revert velocity/accel/SCV to configured maxima
- `M109` (renames original to `M99109`) — wait for hotend within ±1 °C of target
- `DELAYED_OFF` — delayed-gcode wrapper around `OFF`
- `HEATSOAK` — heat bed (+ optional chamber wait) + park center
- `SET_ACTIVE_SPOOL` / `CLEAR_ACTIVE_SPOOL` — Spoolman handoff via Moonraker remote method

### `config/macros/print_start.cfg` — print lifecycle (heat-overlap, post-2026-05-18 redesign)
- `PRINT_START` — full start: tap_threshold guard → param validation (BED/EXTRUDER max-temp) → CLEAR_PAUSE + UI hints (M117, SET_PRINT_STATS_INFO TOTAL_LAYER) → bed + hotend partial heat NON-BLOCKING → home + QGL (cold, in parallel with heat) → wait for bed + hotend partial → chamber soak branch (`CHAMBER>0` from slicer; `CHAMBER=0` runs a `bed_stabilization_soak_seconds` G4) → tap-Z → optional `Z_ADJUST` → adaptive bed mesh → final `M109` → hot-nozzle `BLOBIFIER_CLEAN`. Spec: `docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`. Slicer contract: `docs/slicer-templates/orcaslicer.md`.
- `PRINT_END` — flush buffer, retract 2mm, lift 10mm, park rear-left, heaters off, then `_PRINT_END_CLEANUP`.
- `_PRINT_END_CLEANUP` — shared cleanup tail (`BED_MESH_CLEAR`, `G4` cooldown, `OFF`, `_RESETSPEEDS`). Called by both `PRINT_END` and `_CANCEL_PRINT_HOOK`.
- (removed 2026-05-18) `PRINT_WARMUP` — was a separate manual prewarm macro; never called by slicer. Prewarming pre-print is now direct gcode (`M140 S110` + `M104 S150`) or `HEATSOAK`.

### `config/macros/bedfans.cfg` — BedFans hardware + manual aliases
- `[fan_generic BedFans]` — hardware definition (PWM pin `z:P2.5`)
- `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` — manual console aliases; no automatic callers (the chamber control loop in `chamber_control.cfg` owns BedFans state automatically). BEDFANSSLOW reads `chamber_voc_baseline`; BEDFANSFAST reads `chamber_heat_speed`.
- `SET_HEATER_TEMPERATURE` override — routes `HEATER=heater_bed` → `M99140` so M140 / Mainsail / SET_HEATER_TEMPERATURE all route the same way. No bedfan side-effects.
- `M140` alias — calls `SET_HEATER_TEMPERATURE`
- `M190` override — uses `TEMPERATURE_WAIT` with `m190_tolerance_celsius` band; no bedfan side-effects

### `config/macros/chamber_control.cfg` — active chamber control
- `_CHAMBER_CONTROL` — state holder (`variable_target`); single source of the live setpoint
- `SET_CHAMBER_TARGET TARGET=<°C>` — only mutator of the setpoint; clamps to `[0, chamber_max_target]` with symmetric M117/RESPOND warnings on either side; kicks the loop with 1s delay
- `chamber_control_loop` — delayed_gcode tick (5s in active states, 30s when fully idle so the loop wakes up if the bed is reheated outside SET_CHAMBER_TARGET). State machine over (target, chamber_temp, bed_temp, print_state) writes BedFans speed + temperature_fan chamber target. Five labeled branches — HEAT / COOL / MAINTAIN / VOC BASELINE / OFF — but COOL and MAINTAIN emit identical gcode (PID handles bang-bang internally; branches kept separate for future tuning). Called from PRINT_START (bootstrap + setter), PRINT_END (TARGET=0), `_CANCEL_PRINT_HOOK` (TARGET=0), `OFF` macro (TARGET=0). Sole automatic writer of BedFans after the bedfans.cfg overrides were stripped (PR for spec 2026-05-18-chamber-control-design).

### `config/macros/test_speed.cfg`
- `TEST_SPEED` — home, snapshot position, throw the toolhead around in a configurable pattern, re-home, compare positions to detect skipped steps

### `config/macros/calibrate_flow.cfg` — Frix_x v1.6
- `FLOW_MULTIPLIER_CALIBRATION` — print thin-wall test shell
- `COMPUTE_FLOW_MULTIPLIER` — accepts caliper measurement, prints the new multiplier
- `_FLOW_CALIB_VARIABLES` — internal state holder

### `config/macros/calibrate_pa.cfg` — Frix_x v1.2
- `PRESSURE_ADVANCE_CALIBRATION` — bands of varying PA at different speeds

### `config/macros/lcd_tweaks.cfg` — Mini12864 customization
- `[display_glyph chamber]` / `[display_glyph voron]` — custom icons
- `[display_data __voron_display ...]` — replaces stock layout: extruder/bed/chamber temps, fan speed, progress bar, position. Idle row displays the literal string **`V2.611`**.
- `[menu __main __octoprint]` — disabled (Mainsail doesn't use OctoPrint API)

### `config/eddy.cfg` — probe + bed mesh + homing_override + force_move
- `[probe_eddy_current btt_eddy]` — native Klipper Eddy probe with `descend_z: 0.5`, `reg_drive_current: 15`
- `[temperature_probe btt_eddy]` — drift compensation (calibration_position 175,175,3; bed/extruder targets pre-configured for `TEMPERATURE_PROBE_CALIBRATE`)
- `[bed_mesh]` — 9×9 grid over (15, 21.42) → (335, 330), `fade_target: 0`, `zero_reference_position: 175, 175`, `adaptive_margin: 5`, `scan_overshoot: 8`
- `[force_move] enable_force_move: True` (needed when Eddy is both probe and Z endstop; also for circular-dep bootstrap)
- `SET_Z_FROM_PROBE` / `_RELOAD_Z_OFFSET_FROM_PROBE` — doc-blessed split-macro pattern from `vendor/klipper/docs/Eddy_Probe.md:379-389`. Auto-applied via `[homing_override] axes: z` (below) on every `G28 Z`.
- `[homing_override] axes: z` — fires on `G28` and `G28 Z` (not `G28 X` / `G28 Y` alone). Replaces `[safe_z_home]` (they can't coexist) and adds the tap step: Z-hop if Z homed → conditional X+Y home → move to (175, 175) → `G28 Z` → `SET_Z_FROM_PROBE`. Doc-blessed per `vendor/klipper/docs/Eddy_Probe.md:391-400`.
- `QUAD_GANTRY_LEVEL` — wraps stock with state save + bed mesh clear + 2-pass: coarse pass `METHOD=default` (Z=8, out of cal range), tight pass `METHOD=scan` (Z=2, within cal range). See [issue #22](https://github.com/bjdeng/voron-2-611/issues/22) for the path to making both passes scan.
- `BED_MESH_CALIBRATE` — renames stock to `BTT_BED_MESH_CALIBRATE` and forces `ADAPTIVE=1 METHOD=rapid_scan`

### `config/mmu/` — Happy Hare MMU
The whole MMU surface lives here. `config/mmu/base/*.cfg` are mostly **symlinks to `~/Happy-Hare/config/base/*`** on the Pi (preserved as files in this repo when pulled via `tar -h`). Don't edit the symlinked-source files in this repo unless you also push the change back into the Happy-Hare install dir.

Key macros from Happy Hare (not exhaustive — see `config/mmu/base/mmu_software.cfg` and `config/mmu/base/mmu_sequence.cfg`):
- `MMU_HOME`, `MMU_CHANGE_TOOL`, `MMU_LOAD`, `MMU_UNLOAD`
- `MMU_CALIBRATE_GEAR`, `MMU_CALIBRATE_BOWDEN`, `MMU_CALIBRATE_SELECTOR`
- `MMU_STATUS`, `MMU_TEST_*`
- `BLOBIFIER_CLEAN` (from `config/mmu/addons/blobifier.cfg`)
- `_MMU_CUT_TIP` (Filametrix toolhead cutter, from `config/mmu/base/mmu_cut_tip.cfg` — file header explicitly says "Filametrix style toolhead cutters")

### `config/mainsail.cfg` — Mainsail client.cfg (symlink target on Pi)
- `[gcode_macro PAUSE]` / `RESUME` / `CANCEL_PRINT` / `_CLIENT_*` — standard Mainsail pause/cancel with park behavior. **Defined upstream in `~/mainsail-config/client.cfg`** (Pi-side symlink); never override locally. Any macros added to this file get excluded from deploy by `scripts/deploy_to_pi.sh`'s symlink-discovery — `client_hooks.cfg` is where Mainsail-hook customizations live.

### `config/client_hooks.cfg` — Mainsail hook variables + cancel handler
- `_CLIENT_VARIABLE` — holds hook variables consumed by upstream `client.cfg`. `user_cancel_macro: "_CANCEL_PRINT_HOOK"` routes cancel-mid-print into our cleanup tail. Added 2026-05-18.
- `_CANCEL_PRINT_HOOK` — runs when CANCEL_PRINT fires mid-print, AFTER upstream commands heaters off but BEFORE base cancel. Calls `MMU_END UNLOAD=1` (HH re-heats extruder via `_ensure_safe_extruder_temperature`, unloads filament) then defers to `_PRINT_END_CLEANUP`. Cancel takes ~1-2 min total. Added 2026-05-18.
- (PR #71 moved these from `mainsail.cfg` to `client_hooks.cfg` after discovering the symlink-exclusion footgun made PR #70's deploy inert.)

### `config/archive/` — historical, **not included in config/printer.cfg**
- `config/archive/klicky/` — pre-Eddy probe (Klicky) macros: bed mesh calibrate, QGL, klicky macros
- `config/archive/klicky-variables.cfg` — Klicky positioning variables
- `config/archive/z_calibration.cfg` — Klicky-based automatic Z calibration

---

## Tuning record (as of pull on 2026-05-13)

From the SAVE_CONFIG block at the bottom of `config/printer.cfg`. Per Ben: **assume stale, worth re-running** — there have been significant improvements in Klipper's auto-tuning since these were captured.

| Parameter | Value | Notes |
|---|---|---|
| Bed PID | Kp 44.470, Ki 1.246, Kd 396.896 | from `PID_CALIBRATE HEATER=heater_bed` |
| Hotend PID | Kp 23.507, Ki 1.059, Kd 130.460 | from `PID_CALIBRATE HEATER=extruder` |
| Input shaper X | mzv @ 51.4 Hz | LIS2DW measurement |
| Input shaper Y | zv @ 37.4 Hz | LIS2DW measurement |
| Pressure advance | 0.05 (smooth time 0.040) | from `pressure_advance` in `[extruder]` defaults |
| Bed mesh `default` | 9×9, (15, 21.42) → (335, 334.94) | bicubic, full bed |
| Bed mesh `Default2` | 5×5, (30, 30) → (320, 320) | smaller fallback |
| Eddy native | `reg_drive_current: 15`, freq range ~31607 Hz, Z range 0.25–3 mm, `tap_threshold: 2419.384` | from 2026-05-15 calibration session (post-migration). Thermal drift cal pending — see [#25](https://github.com/bjdeng/voron-2-611/issues/25). Re-run with toolhead higher to widen Z range and resolve [#22](https://github.com/bjdeng/voron-2-611/issues/22) at the same time |

Update [`memory/tuning-log.md`](memory/tuning-log.md) whenever you re-run a calibration.

---

## Machine context beyond `~/printer_data/config/`

Ben's note: *"on the machine some updates to klipper, happy hare and others occasionally require running ./setup.sh in their home directories and klipper configs rely on other scripts on the machine sometimes."* So the config tree alone is not the whole story.

**Repos installed on the Pi (as of 2026-05-13):**

| Path | Version | Upstream | Notes |
|---|---|---|---|
| `~/klipper` | `v0.13.0-649-g4767a8ed` (master) | Klipper3d/klipper | **Has uncommitted local files** from `eddy-ng/install.sh` and `Happy-Hare/install.sh` (symlinks into `klippy/extras/`). |
| `~/Happy-Hare` | `v3.4.2-22-ga880ac0a` | moggieuk/Happy-Hare | Has `install.sh`. Owns `~/printer_data/config/mmu/base/*` (those files in this repo are dereferenced copies of symlinks). |
| `~/eddy-ng` | `v0.1-73-gc7ca62e` | vvuk/eddy-ng | Has `install.sh`. **Migrated off to native `[probe_eddy_current]` in PR #17, 2026-05-15.** Install dir retained for rollback; eventual cleanup TBD. |
| `~/moonraker` | `v0.10.0-19-g1ed102e` | Arksine/moonraker | Standard. |
| `~/moonraker-timelapse` | `v0.0.1-143-gc7fff11` | mainsail-crew/moonraker-timelapse | Installed via `make install` 2026-05-18 (closes #26). Opt-in per print; needs webcam (#27). |
| `~/mainsail` | (web release) | mainsail-crew/mainsail | Static UI files served by nginx. |
| `~/mainsail-config` | `v1.2.1-1-gff3869a` | mainsail-crew/mainsail-config | Owns `mainsail.cfg` (the actual symlink target — `client.cfg` in the same dir is an identical copy, unused by us). |
| `~/kiauh` | `v6.0.6` | dw-0/kiauh | Klipper installer/manager (interactive helper). |
| `~/crowsnest` | `v4.2.0-1-gcf936da` | mainsail-crew/crowsnest | Webcam stack. Daemon runs even though webcam is unplugged. |
| `~/sonar` | `v0.2.0-1-g0d1d7c8` | mainsail-crew/sonar | Network keepalive. Daemon runs. |
| `~/katapult` | `v0.0.1-64-g3e23332` | Arksine/katapult | MCU bootloader for safe re-flashing. |
| `~/BOSSA` | (present) | shumatech/BOSSA | SAM-BA flasher, likely used to flash the EASY-BRD SAMD21. |
| `~/klipper-kconfigs` | (saved configs) | — | Per-MCU build kconfigs. **Mirrored into `config/firmware/` in this repo.** |
| `~/klippy-env`, `~/moonraker-env` | (venvs) | — | Python virtualenvs. |

**Systemd services running:** `klipper`, `klipper_mcu`, `moonraker`, `nginx`, `sonar`, plus the OS-level usuals. **`ModemManager` is masked** (was active until 2026-05-14, then masked after a real USB-MCU enumeration race during the first live `/deploy-to-pi`). If a future MCU connect-error pattern returns, verify ModemManager is still masked.

**`klipper-mcu-watchdog.service`** (Pi-side, install via `sudo bash scripts/install-mcu-watchdog.sh`): a daemon that auto-recovers from the constant USB re-enumeration race that hits SKR Z + EASY-BRD MMU after every `FIRMWARE_RESTART`. Root cause + design at GH issue #37. Logs via `journalctl -u klipper-mcu-watchdog`.

**Install/setup scripts that may need re-running after upgrades:**
- `~/eddy-ng/install.sh` — after any `~/klipper` update that might break the symlinks into `klippy/extras/`
- `~/Happy-Hare/install.sh` — same, for the `klippy/extras/mmu/` and `klippy/extras/mmu_*` files

There's no `[update_manager klipper]` block in `config/moonraker.conf`, **and that's by design.** Moonraker auto-detects Klipper and manages it without an explicit block; the block is only needed to override channel/pinned_commit/refresh_interval. Documented at `vendor/moonraker/docs/configuration.md:2017-2026`.

**Active `[update_manager]` blocks in `config/moonraker.conf`:**

| Block | Manages | Notes |
|---|---|---|
| `mainsail` | Mainsail web UI | Active |
| `mainsail-config` | Upstream mainsail-config (`~/mainsail-config/`) | Active. Note: our `config/mainsail.cfg` is symlinked to it on the Pi; if we ever slim that file locally (per refactor spec Phase 2), the symlink would need to be replaced with a real file and upstream changes would no longer auto-apply |
| `timelapse` | moonraker-timelapse | Active. Component installed 2026-05-18; usage is opt-in per print (`TIMELAPSE_TAKE_FRAME` in slicer custom gcode, or `HYPERLAPSE ACTION=START` in console) and gated on webcam (#27). |
| `crowsnest` | Webcam stack | Active even though webcam unplugged — see [#27](https://github.com/bjdeng/voron-2-611/issues/27) |
| `sonar` | Network keepalive daemon | Active |
| `happy-hare` | HH Klipper extension (`~/Happy-Hare/`) | Active |

---

## How to help me (instructions for future Claude sessions)

### Before changing anything
1. **Always grep the vendored docs first** before web-searching for Klipper / Voron / Happy-Hare / Eddy facts:
   ```sh
   grep -rin "<topic>" vendor/klipper/docs/ vendor/klipper/klippy/extras/
   grep -rin "<topic>" vendor/voron-2/Manual/
   grep -rin "<topic>" vendor/happy-hare/
   grep -rin "<topic>" vendor/eddy-ng/
   grep -rin "<topic>" vendor/moonraker/docs/
   ```
   The vendored sources are pinned to versions running on the Pi — authoritative for this machine.

   For **BTT hardware-specific** docs (SKR 1.4 jumpers, EBB pinouts, Eddy probe wiring, firmware build flags): the BTT wiki is mirrored on GitHub and vendored here:
   ```sh
   grep -rin "<topic>" vendor/btt-docs/
   ```
   Web version (same content): https://global.bttwiki.com/BIGTREETECH_ViViD.html. Grep the vendored copy first.

2. **Never edit `config/printer.cfg` (or any tracked `.cfg`) without showing the diff first.** Propose the change, show the unified diff, and wait for Ben to confirm before writing.

3. **Flag the restart impact of every change.** When proposing an edit to a `.cfg`, state explicitly whether the change needs:
   - `RESTART` — soft-reload Klipper (Python-side changes: macros, gcode_macro, timeline updates, bed_mesh, etc.)
   - `FIRMWARE_RESTART` — full MCU reset (changes to `[mcu]`, pins, kinematics, stepper config, sensor types, anything touching MCU build config, or anything that emits the "this requires FIRMWARE_RESTART" message in the Klipper logs)
   - `restart_method: command` (for the eddy MCU) is set; physical USB replug may still be needed if the MCU disappears.

### About the messy state
4. **Don't assume things on this machine are configured the way they should be.** Six years of upgrades mean orphaned configs, stale tuning, and installed-but-unused software. When something looks off:
   - Investigate root cause before "fixing" or removing
   - Bring it up with Ben before silently changing it
   - Examples of "looks weird but is intentional": the 9:1 extruder gear ratio (Galileo), the chamber heater PID on a `[temperature_fan]`, dual SKR 1.4s on USB instead of CAN, microsteps 128 on X/Y/Z.

5. **Don't auto-delete things even if unused.** `config/archive/klicky/`, the chamber thermistor cal table, abandoned-looking macros — leave alone unless Ben asks. Tag them as candidates in `memory/decisions.md` instead. (Cautionary tale: moonraker-timelapse looked unused for years but the real issue was a missed install step — see #26.)

### About this repo as canonical source
6. **This repo is the canonical config; the Pi is the working copy.** Eventually changes flow `local edit → PR → main → sync to Pi`. Until that CI/CD is built, manual sync is fine, but **never overwrite the Pi's files without confirming** — Mainsail can also edit configs directly and the Pi may be ahead.

7. **Three classes of file on the Pi to be aware of when syncing:**
   - **Real files we own** — `config/printer.cfg`, everything under `config/macros/`, and the other `.cfg`/`.conf` files directly in `config/` (`eddy.cfg`, `toolhead.cfg`, `moonraker.conf`, `crowsnest.conf`, `sonar.conf`). Edit freely here.
   - **Symlinked-from-third-party** — `config/mmu/base/*.cfg` (Happy-Hare), `config/mainsail.cfg` (mainsail-config), `config/timelapse.cfg` (moonraker-timelapse). Editing these on the Pi mutates the upstream install dir. Edits should generally go in the third-party repo, not here.
   - **Auto-generated** — the `#*# SAVE_CONFIG` block at the bottom of `config/printer.cfg`. Klipper rewrites this on every `SAVE_CONFIG`. Don't merge upstream changes that touch it; always pull the Pi's current version when working with calibration values.

### Vendored docs
See [Vendor / submodules](#vendor--submodules) below. Update with `git submodule update --remote vendor/<name>` only when Ben asks — the pin to the Pi's installed version is intentional.

### SSH and Pi access
The Pi is at `mainsailos.local` (current IP 192.168.0.227). Keyed SSH was set up 2026-05-13; `ssh pi@mainsailos.local` should work without password. The `pi:raspberry` defaults in `.env` are the legacy fallback. Rotate when convenient.

---

## Testing

A 7-layer test pyramid (6 standard + 1 for refactor PRs). New work should add to or extend these rather than inventing new validation patterns ad-hoc.

| Layer | What | Where | Runs | Status |
|---|---|---|---|---|
| 1 | Pre-commit hooks (trailing-whitespace, end-of-file-fixer, mixed-line-ending, ruff format + lint on Python) | `.pre-commit-config.yaml` | every commit + CI | active |
| 2 | `macro_refcheck.py` — every gcode command in a `[gcode_macro]` body resolves to a defined macro or an entry in `tests/builtins.txt` / `ALLOWLIST` | `scripts/macro_refcheck.py` | CI | active |
| 3 | Klippy parse + MCU load — `vendor/klipper/scripts/test_klippy.py` loads `config/printer.cfg` with the 4 non-MMU MCUs simulated (MMU stripped at CI time; see Known quirks) and verifies Klipper reaches steady state. No gcode is executed — calibration state required by `G28`/QGL/PRINT_START doesn't exist in CI, and macro→macro reference rot is already covered by L2. | `tests/voron-2-611.test` + `.github/workflows/ci.yml` | CI | active (PR #34) |
| 4 | pytest — `scripts/macro_refcheck.py` unit tests, real-repo regression tests, ALLOWLIST-coupling tripwires | `tests/test_*.py` | CI | active |
| 5 | Structural assertions on `.cfg` files (no deprecated Klipper keys; `[gcode_macro]` description fields; `_USER_VARIABLE.X` references resolve; `[include]` order; `params.X` has default or guard; PAUSE/RESUME/CANCEL_PRINT defined once) | `tests/test_config_structure.py` | CI | **planned** in refactor Phase 1 (`docs/superpowers/specs/2026-05-15-config-macros-refactor.md`) |
| 6 | Post-deploy smoke (a fixed gcode sequence runs on the Pi after deploy + grep `klippy.log` for `!! Unknown command` / `!! Internal error`) | `scripts/deploy_to_pi.sh --smoke` + `scripts/printer-smoke.sh` on Pi | manual after deploy | **planned** in refactor Phase 1 |
| 7 (one-shot) | Behavior diff — dump expanded gcode for fixed macro invocations before/after; assert diff is comments/whitespace only | `scripts/macro_behavior_diff.py` + `tests/snapshots/` | manual, before merging refactor PRs | **planned** for refactor Phase 4 only |

### What each catches
- **L1:** text-hygiene drift, Python lint regressions
- **L2:** macro calls that reference renamed/deleted commands
- **L3:** Klipper config syntax errors, unknown sections, pin clashes, unsupported sensor types (the LPC1769 `temperature_mcu` trap), jinja2 template parse errors. Does NOT execute any gcode — runtime behavior is L6's job.
- **L4:** regressions in the testing infrastructure itself
- **L5:** structural invariants Klipper's own loader misses
- **L6:** runtime behavior on the actual machine (conditional branches, MCU-specific quirks)
- **L7:** refactor behavior preservation — proves "values copied verbatim, no behavior change"

### Not covered
- Conditional branches inside jinja2 with varied state (mitigated by L6 + L7 for refactor PRs)
- Print quality / mechanical regression (manual first-print test after each deploy)
- Slicer-side template errors (lives in OrcaSlicer, not the repo)

### Running locally

```sh
make test-py    # macOS-friendly subset: pre-commit + macro_refcheck + pytest + Layer 5 (when built)
make test       # Adds the klippy step (Linux only — Klipper C extension uses sys/prctl.h and linux/can.h)
```

### Regenerating cached data
- `tests/dict/*.dict` — after bumping `vendor/klipper` or modifying `config/firmware/*.config`. Build on the Pi.
- `tests/builtins.txt` — after bumping `vendor/klipper`. Run `make builtins`.

### Docs-only CI lane
A companion workflow `.github/workflows/ci-docs-noop.yml` reports the same required check name as a no-op success on docs-only paths (`CLAUDE.md`, `memory/**`, `docs/**`, `.claude/**`, `LICENSE`). Without it, branch protection would block any docs-only PR because `paths-ignore` skips `ci.yml` entirely. For any push, exactly one of the two workflows runs.

### Coupled allowlists (tripwire patterns)
The **eddy-ng** block in `scripts/macro_refcheck.py`'s `ALLOWLIST` was keyed to `[probe_eddy_ng]` in `config/eddy.cfg`. When PR #17 removed that section, the same PR had to delete those entries. `tests/test_macro_refcheck.py::test_eddy_ng_allowlist_coupling` was the tripwire that enforced this — now satisfied and the tripwire was removed in PR #17. The **Happy-Hare** block in the same ALLOWLIST is NOT coupled this way; those commands are registered by Python and survive any `.cfg` change.

See [`tests/README.md`](tests/README.md) for full mechanics. Test pyramid rationale lives in `docs/superpowers/specs/2026-05-15-config-macros-refactor.md` Section 5.

---

## Known quirks (this machine's specific weirdness)

These have already tripped someone up — flag them when relevant.

- **MMU `config/mmu/base/*.cfg` are symlinks on the Pi** to `~/Happy-Hare/config/base/*`. In this repo they're files (dereferenced by `tar -h` on pull). If you push this repo back to the Pi without preserving symlinks, you'll break Happy-Hare's update model.
- **`config/mainsail.cfg` is a symlink** to `~/mainsail-config/mainsail.cfg`. Same caveat. (The upstream repo ships both `client.cfg` and `mainsail.cfg` as identical copies; the symlink target is the latter — verify with `ls -l` on the Pi.)
- **`config/timelapse.cfg` is a symlink** to `~/moonraker-timelapse/klipper_macro/timelapse.cfg`. Same caveat. Component installed 2026-05-18 (closes [#26](https://github.com/bjdeng/voron-2-611/issues/26)); usage is opt-in per print.
- **`mmu/addons/mmu_erec_cutter*.cfg` and `mmu_eject_buttons*.cfg` are NOT included** from `printer.cfg` but the files remain (likely symlinked from `~/Happy-Hare/config/addons/`). Don't move them to `archive/` — HH install would recreate them. Toolhead cutter is **Filametrix**, not EREC. Eject buttons are not installed.
- **`ModemManager` is masked on this Pi (2026-05-14).** It probes new USB-serial devices and could hold MCUs open during enumeration — a footgun on this 5-USB-MCU machine. Caused the `mcu 'mmu': Unable to connect` race during the first live `/deploy-to-pi`. Fixed via `sudo systemctl mask --now ModemManager.service`. Verify with `systemctl is-enabled ModemManager` (should print `masked`).
- **SKR Z + EASY-BRD MMU consistently fail USB re-enumeration after `FIRMWARE_RESTART`** — root-caused as a kernel timing race, NOT ModemManager and NOT a physical disconnect. Both MCUs boot slower than the kernel's USB enumeration retry budget (~5s). dmesg pattern: `device descriptor read/64, error 2` → `device not accepting address, error -22` → `unable to enumerate USB device`. The boards are physically connected and electrically fine; the kernel just gave up. **One-shot recovery:** `sudo sh -c 'echo 1-1.3 > /sys/bus/usb/drivers/usb/unbind; sleep 2; echo 1-1.3 > /sys/bus/usb/drivers/usb/bind'`. **Permanent fix:** `klipper-mcu-watchdog.service` (GH issue #37, `scripts/klipper-mcu-watchdog.sh`).
- **No CAN bus.** The toolhead is on USB (`config/toolhead.cfg`). EBB SB v1.0 supports both modes; Ben chose USB.
- **Webcam is unplugged.** Crowsnest + Sonar still run but have nothing to stream ([#27](https://github.com/bjdeng/voron-2-611/issues/27)).
- **Klipper has no update_manager block.** Klipper updates are not automated through Moonraker — likely intentional to avoid breaking the `eddy-ng` + Happy-Hare overlay (note: eddy-ng was migrated off in PR #17 but Happy-Hare overlay still relies on this).
- **SAVE_CONFIG block lives at the bottom of `config/printer.cfg`.** Klipper rewrites it on every `SAVE_CONFIG`. When syncing this repo → Pi, never overwrite the Pi's SAVE_CONFIG section.
- **The Pi's SAVE_CONFIG block can outlive section deletions.** If you delete a `[section]` from the body but the Pi still has corresponding `#*# [section]` lines, Klipper fails to start with "section must be specified". Strip stale SAVE_CONFIG entries via ssh + sed before deploying section removals. (Lesson from Eddy migration: stale `[probe_eddy_ng btt_eddy]` calibration in Pi SAVE_CONFIG had to be manually stripped after the section was removed.)
- **Microsteps 128 on X/Y/Z** (atypically high), plus `interpolate: False` on the TMC2209s. Followed third-party online advice rather than analyzed for this hardware. Real goal: quiet without losing steps. Don't change blindly ([#24](https://github.com/bjdeng/voron-2-611/issues/24) tracks deliberate investigation).
- **The 2-pass `QUAD_GANTRY_LEVEL` override is load-bearing.** A/B motor weight sags the rear when motors are off; a single-pass QGL would fail. First pass uses `METHOD=default` (descend) because `horizontal_move_z=8` is outside the calibrated eddy freq→Z range; second pass uses `METHOD=scan` at `horizontal_move_z=2`. See `memory/qgl-two-pass-intentional.md` and [#22](https://github.com/bjdeng/voron-2-611/issues/22).
- **`config/mainsail.cfg` is "read-only" upstream.** mainsail-config's file header says don't edit. We've been pulling Ben's customizations through `[gcode_macro _CLIENT_VARIABLE]` instead. The refactor spec (Phase 2) plans to break the symlink and slim the file locally — when that happens, future mainsail-config updates won't auto-apply.

---

## Klipper gotchas (general — apply to any Klipper config work)

Lessons hard-won during the 2026-05-15 Eddy migration session. None of these are documented in obvious places.

- **`#` is a comment delimiter everywhere in Klipper macros — including inside string literals in `{ ... }` action blocks, and inside jinja `{# ... #}` comment blocks (single-line or multi-line).** Klipper's `configfile.py:append_fileconfig` runs `line.find('#')` per line BEFORE the gcode body reaches jinja, truncating each line at the first `#`. So `{# tag #}` becomes `{` + nothing (everything from the first `#` on is stripped), leaving jinja with an unclosed expression — fails on the next non-whitespace token, typically deep inside the macro body where the cause is unobvious. **Workaround: never use `{# ... #}` jinja comments in this codebase.** Use Klipper `# ...` line comments instead — those get stripped to whitespace per line and never reach jinja. (String-literal case caught by PR #18 after Eddy migration; full `{# #}` failure mode — even single-line — caught by PR #73 CI during the chamber control review-fixup pass. Earlier Task 3 single-line `{# #}` tags shipped without exercising klippy parse on their own because assembled-stack CI failed earlier and masked the issue.)
- **A gcode_macro template renders ONCE per macro invocation, before any commands execute.** A macro body like `PROBE METHOD=tap; SET_KINEMATIC_POSITION Z={printer.probe.last_z_result}` substitutes `last_z_result` to the PRIOR value because jinja runs before the gcode. Split into two macros (parent calls A then B; B's template renders separately after A finishes) — see `vendor/klipper/docs/Eddy_Probe.md:379-389` and `config/eddy.cfg`'s `SET_Z_FROM_PROBE`/`_RELOAD_Z_OFFSET_FROM_PROBE` pair.
- **`sensor_type: temperature_mcu` is NOT supported on LPC1769.** Klipper's supported list (`vendor/klipper/klippy/extras/temperature_mcu.py`) covers rp2/sam3/sam4/samd21/samd51/stm32f1-4/stm32g0/stm32g4/stm32l4/stm32h7 only. Cannot add MCU die-temp sensors for the SKR 1.4 boards on this build.
- **MCU firmware can lag host Klipper version.** Bumping `vendor/klipper` doesn't reflash MCUs. New host features (e.g., `trigger_analog_query_state` for native Eddy) require corresponding firmware. Klipper will report version mismatch + missing commands on `RESTART`.
- **`.config` files miss new Kconfig options after Klipper bumps.** Run `make olddefconfig` after a Klipper version bump to apply new defaults (e.g., `CONFIG_WANT_TRIGGER_ANALOG=y` auto-enables when `CONFIG_WANT_LDC1612=y` exists).
- **`make flash FLASH_DEVICE=...` for RP2040 has a USB-reconnect race.** `flash_usb.py` loses track of the device after entering bootloader (reads from a stale sysfs path). Workaround: manually mount the BOOTSEL UF2 volume (`/dev/sda1` typically) and `cp` the `out/klipper.uf2` file. The RP2040 auto-reboots into Klipper mode after the UF2 lands.
- **SAMD21 boards use BOSSA, not katapult.** For the EASY-BRD MMU MCU, prefer KIAUH's flash flow over hand-driving `~/BOSSA/` — KIAUH handles the bootloader-button timing.
- **eddy native scan probing refuses out-of-calibrated-range Z.** `PROBE_EDDY_CURRENT_CALIBRATE` covers a Z range; scan/rapid_scan modes error with "sensor not in valid range" outside it. eddy-ng was more permissive. To use scan at higher Z, re-run `PROBE_EDDY_CURRENT_CALIBRATE` with the toolhead positioned higher. See [#22](https://github.com/bjdeng/voron-2-611/issues/22).
- **`PROBE_EDDY_CURRENT_TAP_CALIBRATE` flow:** `guess` → `refine` → `verify`. **Only `verify` saves to config.** `_refine_tap_threshold` lives in memory only; don't restart Klipper between `refine` and `verify`.
- **`TEMPERATURE_PROBE_CALIBRATE` requires a paper test at every STEP°C.** Default `STEP=2` → ~25 paper tests over 50°C. Quadratic LSQ fit error ≈ σ × √(3/(N−3)). STEP=2 gives ~1-2µm fit error. Higher STEP = fewer samples, worse fit. Tradeoff is real — see source comments around line 374 of `temperature_probe.py`.
- **Circular dependency on first Eddy calibration.** Native Eddy needs calibration to home Z, but calibration needs Z-homed first. Workaround: `FORCE_MOVE STEPPER=stepper_z DISTANCE=N VELOCITY=5` to manually position, then `SET_KINEMATIC_POSITION Z=20` to claim Z homed, then run `PROBE_EDDY_CURRENT_CALIBRATE`. Documented at `vendor/klipper/docs/Eddy_Probe.md:402-450`.
- **`deploy_to_pi.sh` drift gate can't distinguish Pi-ahead from repo-ahead.** When the repo has changes the Pi doesn't have yet, the gate fires anyway. Workaround: temporarily disable the gate (or use the fix from [#19](https://github.com/bjdeng/voron-2-611/issues/19)).
- **`_USER_VARIABLE` only reaches `[gcode_macro]` templates, not Klipper config sections.** The pattern works because jinja in macro bodies is rendered lazily at invocation. Klipper config sections like `[idle_timeout].timeout`, `[printer].max_velocity`, `[heater_bed].max_power`, `[stepper_*].microsteps` are parsed once at startup and CANNOT reference `printer["gcode_macro _USER_VARIABLE"].X`. Don't try to migrate the wrong tunables — they'll silently parse the literal string. (See `docs/superpowers/audits/2026-05-17-config-reorg-audit.md` F12.)

---

## Designing non-trivial changes

For anything bigger than a single-file edit:
1. **`Skill: superpowers:brainstorming`** to produce a spec. Let the skill decide where it lives.
2. **`Skill: superpowers:writing-plans`** to produce a task-by-task implementation plan. Same — let the skill place it.
3. **`Skill: superpowers:using-git-worktrees`** (native `EnterWorktree` tool) before any implementation.
4. **`Skill: pr-review-toolkit:review-pr`** **BEFORE** pushing — not after. (Lesson from 2026-05-14: a Codex P1 silent-failure would have been caught pre-push by the toolkit.)

---

## First-time setup

After cloning:

```sh
git submodule update --init --recursive   # pulls vendored Klipper / Happy-Hare / eddy-ng / Voron-2 / btt-docs / …
make venv                                  # creates .venv with pytest, pre-commit, ruff
make test-py                               # runs the macOS-compatible CI subset locally
pre-commit install                         # (optional) auto-run hooks on every commit
```

To re-pull configs from the Pi when it drifts ahead (Mainsail edits, SAVE_CONFIG rewrites):

```sh
bash scripts/sync_from_pi.sh   # handles diff + prompt + correct destination (config/) for you
```

---

## Open investigations

All open investigations are tracked as GitHub Issues with the [`future-work`](https://github.com/bjdeng/voron-2-611/labels/future-work) label. Use `gh issue list --label future-work` for the current list. Active highlights worth knowing about today: **[#25] weekend re-tune session** (shaper + PID + PA + Eddy thermal drift), **[#42] Layer 6 post-deploy smoke** (mostly shipped via PR #43 — gating on real-world soak), **[#45] deploy/watchdog race** (discovered during PR #43's live validation), **[#15] MMU load/unload calibration failures** (actual bug, not future-work).

Browsing the full label view in GitHub is the authoritative way to see what's open — this section is intentionally not exhaustive to avoid drift between repo state and CLAUDE.md.

### Recently resolved (historical log)

- ~~Bed-target-driven BedFans automation~~ — replaced 2026-05-18 by the active chamber control loop in `config/macros/chamber_control.cfg`. Spec: `docs/superpowers/specs/2026-05-18-chamber-control-design.md`.
- ~~`eddy-ng` → native Klipper Eddy migration~~ — shipped PR #17, 2026-05-15. Calibration session completed (main + tap); thermal drift cal deferred to [#25].
- ~~Initial calibration deploy bugs~~ — `#` in macro strings (PR #18), LPC1769 temp sensors crash (caught by review), tap jinja expansion order (split-macro pattern). All landed.
- ~~Missing `[update_manager klipper]`~~ — by design; Moonraker auto-detects (`vendor/moonraker/docs/configuration.md:2017-2026`).
- ~~CI klippy-smoke disabled~~ — being re-enabled (was Open Investigation #7; closes via dedicated PR).
- ~~TDD-equivalent for Klipper configs~~ — landed via the CI scaffold; pyramid expanded in [Testing](#testing).
- ~~`ModemManager` USB-MCU footgun~~ — masked on the Pi 2026-05-14.
- ~~Top-level mixed machine state + tooling~~ — machine state moved into `config/` 2026-05-14.

---

## Workflow & CI/CD

**Today:** edit locally on a `feat/*` (or `chore/*`, `fix/*`, `docs/*`) branch → PR → CI gate → squash-merge to `main`. CI is built (`.github/workflows/ci.yml` — see [## Testing](#testing)).

**After every merge to `main`:** run `/deploy-to-pi` to sync the Pi. The skill refuses if CI isn't green, the printer is busy, or the Pi has drift; it tells you what to do next. See [`.claude/skills/deploy-to-pi/SKILL.md`](.claude/skills/deploy-to-pi/SKILL.md) for the full contract (gates, flags, exit codes).

---

## Vendor / submodules

Reference docs are pinned to versions matching the Pi. Always grep these first before going to the web.

| Path | Upstream | Pin | Why |
|---|---|---|---|
| `vendor/klipper` | Klipper3d/klipper | `4767a8ed` | Source + `docs/`. Sparse-checked to `docs/ klippy/ src/ test/ .github/ scripts/`. |
| `vendor/happy-hare` | moggieuk/Happy-Hare | `a880ac0a` (v3.4.2-22) | MMU control + `mmu/*` config templates |
| `vendor/eddy-ng` | vvuk/eddy-ng | `c7ca62e` (v0.1-73) | Third-party probe extension; **migration to native shipped PR #17, 2026-05-15**. Retained for reference + rollback ability. Eventual cleanup pending. |
| `vendor/voron-2` | VoronDesign/Voron-2 | `Voron2.4` branch tip | V2.4 manual/BOM (sparse: `Manual/ firmware/ slicer_profiles/`) |
| `vendor/mainsail-config` | mainsail-crew/mainsail-config | `ff3869a` (v1.2.1-1) | Source of `mainsail.cfg` (the actual symlink target on the Pi) |
| `vendor/moonraker` | Arksine/moonraker | `1ed102e` (v0.10.0-19) | Moonraker `docs/` |
| `vendor/btt-docs` | bigtreetech/docs | shallow `main` | BTT hardware reference (sparse: text only, no images) |

Bump deliberately with `git submodule update --remote vendor/<name>` — pin updates are PRs, not auto-pulled in CI.

### Hardware references (not vendored — too heavy)

These hardware projects ship with CAD / STLs / heavy assets that aren't worth vendoring (the ERCF v2 repo alone is 1.3 GB on a fresh clone). Use the URLs below when troubleshooting; they're the canonical upstreams for the hardware on this build.

| Hardware | Upstream | Why we don't vendor |
|---|---|---|
| **ERCF v2** (MMU) | [Carrot-collective/ERCF_v2](https://github.com/Carrot-collective/ERCF_v2) | 1.3 GB — CAD + STLs + recommended-mods assets. `Documentation/` alone is 91 MB. |
| **Galileo 2** (extruder; 9:1 ratio matches our `config/toolhead.cfg`) | [JaredC01/Galileo2](https://github.com/JaredC01/Galileo2) | CAD-heavy. The Voron Stealthburner drop-in (G2E) is what's on this build. The original (7.5:1) lives at [JaredC01/Galileo](https://github.com/JaredC01/Galileo) — not what we have. |
| **EASY-BRD** (ERCF SAMD21 MCU) | [Tircown/ERCF-easy-brd](https://github.com/Tircown/ERCF-easy-brd) | Schematic + KiCad files + reference configs. Probably small enough to vendor if we ever need to dig in — check size first. |
| **Stealthburner v2** (toolhead) | [VoronDesign/Voron-Stealthburner](https://github.com/VoronDesign/Voron-Stealthburner) | CAD + STLs + assembly manual. Separate from `vendor/voron-2` (the main Voron 2 repo doesn't include the SB toolhead). |

If we ever need to troubleshoot one of these and the URL isn't enough, clone it ad-hoc into `~/scratch/` rather than committing it as a submodule.

---

## Repo layout

Files under `config/` use one of two organizing axes:

- **By feature or MCU** — `eddy.cfg`, `toolhead.cfg`, `mainsail.cfg`, `mmu/*`, `macros/*`. One coherent subsystem per file (the probe, the toolhead board, the UI client, the MMU, etc.). Replacing the underlying hardware = one file diff.
- **By function** — `motion.cfg`, `bed.cfg`, `display.cfg`, `system.cfg`. For mainboard-resident sections that don't form a coherent feature on their own. Introduced by [#63](https://github.com/bjdeng/voron-2-611/issues/63).

When adding a new section: prefer the feature axis if the section forms or extends a self-contained subsystem; fall back to the function axis only for "this is another mainboard fan / sensor / output_pin" cases.

```
voron-2-611/
├── CLAUDE.md                    # this file
├── README.md                    # brief intro + safety notes; points here
├── LICENSE                      # GPL-3.0 (matches Klipper / Voron Design)
├── .env                         # SSH creds (gitignored)
├── .gitignore                   # excludes .env, .venv/, .worktrees/, dict backups, logs
├── .pre-commit-config.yaml      # text hygiene + ruff hooks (runs in CI too)
├── Makefile                     # `make test-py` (macOS) / `make test` (Linux); see ## Testing
├── requirements.txt             # tooling deps (pytest, pre-commit) — pinned
│
├── config/                      # everything that deploys to the Pi
│   ├── printer.cfg              # 2× [mcu] + [include]s + SAVE_CONFIG (Klipper's entry point)
│   ├── motion.cfg               # [printer] + 6 steppers + 6 TMCs + [input_shaper]
│   ├── bed.cfg                  # heater_bed + chamber thermal + QGL + controller fan
│   ├── display.cfg              # mini12864 LCD: board_pins, display, beeper, neopixel
│   ├── system.cfg               # raspberry_pi temp, caselight, idle_timeout
│   ├── eddy.cfg                 # Eddy probe + bed mesh + temperature_probe + SET_Z_FROM_PROBE pair
│   ├── toolhead.cfg             # toolhead MCU config (RP2040 EBB SB v1.0, USB mode)
│   ├── mainsail.cfg             # slimmed local copy (Phase 2); Pi symlink → ~/mainsail-config/mainsail.cfg means our copy doesn't deploy
│   ├── timelapse.cfg            # symlink target on Pi; opt-in per print, needs webcam #27
│   ├── moonraker.conf
│   ├── crowsnest.conf
│   ├── sonar.conf
│   ├── macros/                  # printer-specific macros
│   │   ├── macros.cfg           # Ellis-derived utility macros
│   │   ├── print_start.cfg      # PRINT_START / PRINT_END / _PRINT_END_CLEANUP
│   │   ├── bedfans.cfg          # BedFans with M140/M190 overrides
│   │   ├── lcd_tweaks.cfg       # Mini12864 display group (renders "V2.611")
│   │   ├── test_speed.cfg
│   │   ├── calibrate_flow.cfg   # Frix_x
│   │   └── calibrate_pa.cfg     # Frix_x
│   ├── mmu/                     # Happy Hare configs (base/optional/addons)
│   │   ├── base/                # symlinks-on-pi to ~/Happy-Hare/config/base/
│   │   ├── optional/            # symlinks-on-pi to ~/Happy-Hare/config/optional/
│   │   ├── addons/              # Blobifier, EREC, eject_buttons
│   │   └── mmu_vars.cfg
│   ├── archive/                 # historical, not included
│   │   ├── klicky/              # pre-Eddy probe configs
│   │   ├── klicky-variables.cfg
│   │   └── z_calibration.cfg
│   └── firmware/                # saved per-MCU build kconfigs (mirror of ~/klipper-kconfigs)
│       ├── mcu.config           # SKR 1.4 (both XYE + Z)
│       ├── ebb-usb.config       # EBB SB v1.0
│       ├── eddy.config          # BTT Eddy
│       └── easy-brd.config      # ERCF EASY-BRD
│
├── tests/                       # CI: smoke .test, fixtures, builtins.txt, dict/, pytest
├── scripts/                     # macro_refcheck.py, deploy_to_pi.sh, sync_from_pi.sh
├── .github/workflows/ci.yml     # GitHub Actions (two parallel jobs)
├── docs/superpowers/            # specs/ and plans/ for non-trivial changes
│   ├── specs/                   # design docs (eddy migration, CI scaffold, reorg, …)
│   └── plans/                   # implementation plans matched to specs
│
├── memory/                      # running logs (this repo's, not Claude's global)
│   ├── tuning-log.md
│   ├── troubleshooting-log.md
│   ├── hardware-changes.md
│   └── decisions.md
│
└── vendor/                      # 7 git submodules — see ## Vendor / submodules
```
