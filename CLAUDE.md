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

## Build at a glance

- V2.4 350 mm CoreXY, milled aluminum bed, quad gantry leveling
- Stealthburner v2 + Galileo G2E (9:1 — explains `gear_ratio: 9:1`/`rotation_distance: 48.033`) + Dragon clone hotend
- BTT Eddy probe (native Klipper `[probe_eddy_current]`; migrated from `vvuk/eddy-ng` in PR #17)
- ERCF v2 MMU, 6 gates, Filametrix toolhead cutter, Blobifier purge tower
- 5 USB-attached MCUs (no CAN): 2× BTT SKR 1.4 (LPC1769), EBB SB v1.0, BTT Eddy, ERCF EASY-BRD
- 0.4 mm nozzle, 1.75 mm filament; PEI textured magnetic flex plate

Hardware history + non-obvious mods + community context: [`docs/hardware.md`](docs/hardware.md). Actual electrical specs (pins, drive currents, kinematic constants, USB serials) live in the [`config/*.cfg`](config/) files — `docs/hardware.md` is the *why* layer, not a duplicate spec.

---

## MCU map

The printer uses **5 USB-attached MCUs** (no CAN bus, despite the toolhead board name suggesting it). USB serial IDs live in [`config/printer.cfg`](config/printer.cfg)'s `[mcu]` blocks (`serial:` lines). Confirm with `ls -l /dev/serial/by-id/` on the Pi when adding/replacing hardware.

| Klipper name | Board | MCU | Role |
|---|---|---|---|
| `mcu` | BTT SKR 1.4 | LPC1769 | X/Y steppers, extruder uart-mux home (EBB connects too), main MCU. Also drives caselight, beeper, mini12864, neopixel LCD. |
| `mcu z` | BTT SKR 1.4 | LPC1769 | Four Z steppers, bed heater (SSR via z:P2.3), controller fan, bedfans, chamber heater fan, chamber thermistor |
| `mcu EBB` | BTT EBB SB v1.0 (USB mode) | RP2040 | Extruder stepper, hotend heater, part fan, hotend fan, LIS2DW accel, toolhead filament sensors |
| `mcu eddy` | BTT Eddy | RP2040 | Eddy probe (LDC1612 sensor + MCU temperature sensor) |
| `mcu mmu` | ERCF EASY-BRD | SAMD21G18A | MMU gear stepper, selector stepper, selector servo, encoder, selector endstop, sync feedback tension switch |

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
- `PRINT_START` — full start: tap_threshold guard → param validation (BED/EXTRUDER max-temp) → CLEAR_PAUSE + UI hints (M117, SET_PRINT_STATS_INFO TOTAL_LAYER) → bed + hotend partial heat NON-BLOCKING → home + QGL (cold, in parallel with heat) → wait for bed + hotend partial → chamber soak branch (`CHAMBER>0` from slicer; `CHAMBER=0` runs a `bed_stabilization_soak_seconds` G4) → optional `Z_ADJUST` → adaptive bed mesh (probed against the cold-Z reference from QGL's home — mesh values are relative shape per `zero_reference_position: 175,175`) → final `M109` → hot-nozzle `BLOBIFIER_CLEAN` → **tap-Z (hot + clean nozzle, multi-sample retry-until-consensus)**. `SET_Z_FROM_PROBE` passes `SAMPLES=3 SAMPLES_TOLERANCE=0.020 SAMPLES_TOLERANCE_RETRIES=2` so the eddy probe code (which IGNORES `samples:` config block for tap mode — see `EddyParameterHelper.get_probe_params` at `vendor/klipper/klippy/extras/probe_eddy_current.py:1014-1036`) gets the multi-sample retry behavior via gcmd args. Spec: `docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md` (+ 2026-05-21 amendment removing the pre-mesh tap). Slicer contract: `docs/slicer-templates/orcaslicer.md`. **Filament loads AFTER PRINT_START returns** — slicer's 5-step wrapper places `MMU_START_LOAD_INITIAL_TOOL` outside this macro.
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

(Pressure-advance calibration is slicer-side — OrcaSlicer Adaptive PA, see [`docs/slicer-templates/orcaslicer.md`](docs/slicer-templates/orcaslicer.md). The Frix_x `calibrate_pa.cfg` macro was removed 2026-05-28 per the [#31](https://github.com/bjdeng/voron-2-611/issues/31) survey — redundant with OrcaSlicer's pattern method.)

### `config/macros/lcd_tweaks.cfg` — Mini12864 customization
- `[display_glyph chamber]` / `[display_glyph voron]` — custom icons
- `[display_data __voron_display ...]` — replaces stock layout: extruder/bed/chamber temps, fan speed, progress bar, position. Idle row displays the literal string **`V2.611`**.
- `[menu __main __octoprint]` — disabled (Mainsail doesn't use OctoPrint API)

### `config/eddy.cfg` — probe + bed mesh + homing_override + force_move
- `[probe_eddy_current btt_eddy]` — native Klipper Eddy probe with `descend_z: 0.5`, `reg_drive_current: 15`
- `[temperature_probe btt_eddy]` — drift compensation (calibration_position 175,175,5 + `resting_z: 5`; bed/extruder targets pre-configured for `TEMPERATURE_PROBE_CALIBRATE`). The 5 mm heights make `TEMPERATURE_PROBE_CALIBRATE ... MANUAL_METHOD=tap` safe: tap has no pre-lift (`EddyTap.run_probe`, `vendor/klipper/klippy/extras/probe_eddy_current.py:893-903` at `9cb99754`) and needs a ~3–20 mm start, but the defaults would re-tap from 0.4 mm. Don't lower them.
- `[bed_mesh]` — 9×9 grid over (15, 21.42) → (335, 330), `fade_target: 0`, `zero_reference_position: 175, 175`, `adaptive_margin: 5`, `scan_overshoot: 8`
- `[force_move] enable_force_move: True` (needed when Eddy is both probe and Z endstop; also for circular-dep bootstrap)
- `SET_Z_FROM_PROBE` / `_RELOAD_Z_OFFSET_FROM_PROBE` — split-macro pattern originally from upstream's "Homing correction macros" section (`Eddy_Probe.md` at `4767a8ed`). Upstream removed that section in `5a56830a0` (2026-05) because `G28 Z` via `probe:z_virtual_endstop` is now accurate on its own (standard probe interface). We keep the pair because it **tap**-corrects Z to nozzle contact, as in the "tap" probing method example in `vendor/klipper/docs/Eddy_Probe.md`. Auto-applied via `[homing_override] axes: z` (below) on every `G28 Z`.
- `[homing_override] axes: z` — fires on `G28` and `G28 Z` (not `G28 X` / `G28 Y` alone). Replaces `[safe_z_home]` (they can't coexist) and adds the tap step: Z-hop if Z homed → conditional X+Y home → move to (175, 175) → `G28 Z` → `SET_Z_FROM_PROBE`. The removed upstream section suggested a `[homing_override]` so the correction always runs.
- `QUAD_GANTRY_LEVEL` — wraps stock with state save + bed mesh clear + 2-pass: coarse pass `METHOD=default` (Z=8, out of cal range), tight pass `METHOD=scan` (Z=2, within cal range). See [issue #22](https://github.com/bjdeng/voron-2-611/issues/22) for the path to making both passes scan.
- `BED_MESH_CALIBRATE` — renames stock to `BTT_BED_MESH_CALIBRATE` and forces `ADAPTIVE=1 METHOD=rapid_scan`

### `config/mmu/` — Happy Hare MMU
The whole MMU surface lives here. **Happy Hare v4** (v4.1.0, migrated from v3.4.2 on 2026-10-17) — v4 is configured through a Kconfig `menuconfig` installer, not by hand-editing `.cfg` files:
- **`config/mmu/.mmu_config`** — the source of truth for HH config: a full Kconfig `.config` (~590 `CONFIG_*` lines). Lines tagged `#~DEFAULT~#` are v4 defaults; the ~100 untagged assignments are the deliberate overrides (hardware/wiring, motor facts, servo angles, toolhead geometry, Filametrix cutter, parking XY, Blobifier, cancel hook). Everything else is a v4 default on purpose. It's the installer's own copy (it writes the config it built from into `mmu/`) and contains real install paths (`CONFIG_KLIPPER_CONFIG_HOME` etc.).
- **`config/mmu/base/*.cfg`** — **generated** by `~/Happy-Hare/install.sh` from `.mmu_config` (`mmu.cfg`, `mmu_hardware_mmu.cfg`, `mmu_parameters_mmu.cfg`, `mmu_macro_vars.cfg`). Real files on the Pi. Don't hand-edit — change `.mmu_config` and re-run the installer, then `/sync-from-pi`.
- **`config/mmu/macros/*.cfg`, `config/mmu/optional/*.cfg`** — symlinks into `~/Happy-Hare/config/` on the Pi (dereferenced here by `tar -h`). Upstream-owned.
- Unit name is `mmu` → `mmu_vars.cfg` calibration keys are namespaced `mmu_mmu_*` (e.g. `mmu_mmu_bowden_lengths`, `mmu_mmu_gear_rotation_distances`, `mmu_mmu_selector_offsets`, `mmu_mmu_encoder_resolution`).
- `~/printer_data/config/mmu.V3/` on the Pi is the installer's backup of the whole v3 dir (incl. v3 `mmu_vars.cfg`). Pi-only — gitignored and excluded from deploy/sync.
- **Applying a settings change on the Pi** (non-interactive; how the 2026-10-17 cancel-hook fix was applied): copy the edited file to the Pi (e.g. `~/hh.cfg`), then `cd ~/Happy-Hare && F_CFG_UPGRADE_MODE=replace ./install.sh -y -z -s ~/hh.cfg`. Flags: `-y` auto-yes, `-z` skip git self-update, `-s` **skip restarting Klipper/Moonraker** (do it yourself after checking the diff); the trailing path is the Kconfig file (the installer may normalise it and copies it into `mmu/` under its own name — delete stray copies or they'll be synced). `F_CFG_UPGRADE_MODE=replace` is required: the default `refresh` mode keeps the values already in the generated `.cfg`s, so Kconfig edits are silently ignored. Snapshot `mmu/` first and `diff -r` the generated `base/` afterwards.
- **`install.sh -t` (test mode) is NOT a safe dry run with this file.** `-t` redirects to `/tmp/mmu_test` via env vars, but `CONFIG_KLIPPER_CONFIG_HOME` / `CONFIG_KLIPPER_HOME` inside `.mmu_config` override them, so it writes to the real `~/printer_data/config` (it did on 2026-10-17 — harmless that time, values unchanged). Only use `-t` with a config file stripped of those path lines.

Key commands/macros (not exhaustive — see `config/mmu/macros/mmu_software.cfg` and `config/mmu/macros/mmu_sequence.cfg`):
- `MMU_HOME`, `MMU_CHANGE_TOOL`, `MMU_LOAD`, `MMU_UNLOAD`
- `MMU_CALIBRATE_GEAR`, `MMU_CALIBRATE_BOWDEN`, `MMU_CALIBRATE_SELECTOR`, `MMU_CALIBRATE_GATE(S)`
- `MMU_STATUS`, `MMU_TEST_*`
- `BLOBIFIER`, `BLOBIFIER_CLEAN`, `BLOBIFIER_PARK` (built into v4: `config/mmu/macros/blobifier.cfg`; the v3 `mmu/addons/` dir is gone)
- `_MMU_CUT_TIP` (Filametrix toolhead cutter, `config/mmu/macros/mmu_cut_tip.cfg`)

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
| Eddy native | freq range ~31607 Hz, Z range 0.05–4.05 mm (101 samples × 40 µm — Klipper hardcoded, see Klipper gotchas), `tap_threshold: 2711.866`, `calibration_temp: 57.92 °C` | tap_threshold from 2026-05-19 refine+verify session. Cal anchor rolled back to May-15 SAVE_CONFIG state (commit 0e48365) after re-running PROBE_EDDY_CURRENT_CALIBRATE at a different coil temp broke tap — see Klipper gotchas on native-tap drift sensitivity. Drift cal still pending — [#25](https://github.com/bjdeng/voron-2-611/issues/25). [#22](https://github.com/bjdeng/voron-2-611/issues/22) (widening cal range to cover QGL first pass at z=8) closed as won't-fix — Klipper caps cal at z=4. |

Update [`memory/tuning-log.md`](memory/tuning-log.md) whenever you re-run a calibration.

---

## Machine context beyond `~/printer_data/config/`

The Pi has additional repos (Klipper, Happy-Hare, eddy-ng, Moonraker, mainsail, crowsnest, etc.) outside `~/printer_data/config/` that configs sometimes depend on. Some require running `./install.sh` from their home directory after upgrades (eddy-ng, Happy-Hare especially — their installers create symlinks into `~/klipper/klippy/extras/` that break on Klipper version bumps).

Pi-side state inventory — repos + versions, systemd services, ModemManager masking, `klipper-mcu-watchdog.service`, active `[update_manager]` blocks: [`docs/pi-environment.md`](docs/pi-environment.md).

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

7. **Four classes of file on the Pi to be aware of when syncing:**
   - **Real files we own** — `config/printer.cfg`, everything under `config/macros/`, and the other `.cfg`/`.conf` files directly in `config/` (`eddy.cfg`, `toolhead.cfg`, `moonraker.conf`, `crowsnest.conf`, `sonar.conf`). Edit freely here.
   - **Symlinked-from-third-party** — `config/mmu/macros/*.cfg` + `config/mmu/optional/*.cfg` (Happy-Hare), `config/mainsail.cfg` (mainsail-config), `config/timelapse.cfg` (moonraker-timelapse). Editing these on the Pi mutates the upstream install dir. Edits should generally go in the third-party repo, not here.
   - **Generated by a third-party installer** — `config/mmu/base/*.cfg` (Happy-Hare v4 builds them from `config/mmu/.mmu_config`). Real files, but change `.mmu_config` + re-run HH's `install.sh` (replace mode — see MMU section), not the `.cfg`.
   - **Auto-generated (block-level)** — the `#*# SAVE_CONFIG` block at the bottom of `config/printer.cfg`. Klipper rewrites this on every `SAVE_CONFIG`. Don't merge upstream changes that touch it; always pull the Pi's current version when working with calibration values.
   - **Live Klipper state files (file-level)** — `config/mmu/mmu_vars.cfg` is the only one today. It's Klipper's `[save_variables]` file for Happy-Hare; Klipper rewrites it on every MMU operation (gate load/unload, tool change, per-gate calibration save). The Pi is canonical. `/deploy-to-pi` excludes the file from the rsync push (would otherwise clobber live calibrations with a stale snapshot) and prints a one-line drift summary so you can see when the repo's backup snapshot has fallen behind. `/sync-from-pi` continues to pull it as a periodic backup. If the Pi-side file is ever corrupted/deleted, `scp` from the repo's snapshot manually and restart Klipper. Closes [#69](https://github.com/bjdeng/voron-2-611/issues/69).

### Vendored docs
See [Vendor / submodules](#vendor--submodules) below. Update with `git submodule update --remote vendor/<name>` only when Ben asks — the pin to the Pi's installed version is intentional.

### SSH and Pi access
The Pi is at `mainsailos.local` (DHCP; 192.168.0.226 as of 2026-10-18). Since the 2026-10-18 reflash, SSH is **key-only** (password auth disabled by Raspberry Pi Imager): Ben's Mac key is `~/.ssh/id_ed25519_voron`, wired up by a `Host mainsailos.local` block in `~/.ssh/config` (User `pi`). `pi` has passwordless sudo (`/etc/sudoers.d/010_pi-nopasswd`); the `pi` account password is still the default — change it if console/local access matters. **Connect by hostname, not IP** — the `~/.ssh/config` key only applies to `mainsailos.local`. After any reflash the host key changes: `ssh-keygen -R mainsailos.local; ssh-keygen -R <ip>` then re-scan. Moonraker's HTTP API (`http://<pi>:7125`) needs no auth and covers most read-only debugging (printer state, `/server/files/klippy.log`, `/machine/peripherals/usb`, `/machine/proc_stats`).

---

## Testing

**7-layer pyramid** at a glance: pre-commit hooks (L1), `macro_refcheck.py` (L2), klippy parse + MCU load (L3), pytest (L4) — all active in CI. L5 structural assertions, L6 post-deploy smoke, and L7 behavior diff are planned per [`docs/superpowers/specs/2026-05-15-config-macros-refactor.md`](docs/superpowers/specs/2026-05-15-config-macros-refactor.md) §5.

**Running locally**: `make test-py` (macOS subset) or `make test` (Linux only — needs Klipper C extension). New macro? `make refcheck` after adding. Bumped `vendor/klipper`? `make builtins` to regen + rebuild `.dict` files on the Pi.

**What CI does NOT catch:** jinja conditionals with state, print quality, slicer-side errors. Those need L6 post-deploy smoke (`scripts/deploy_to_pi.sh --smoke`) + manual first-print testing.

**Docs-only CI lane:** `.github/workflows/ci-docs-noop.yml` reports the required check name as no-op success on docs-only paths (`CLAUDE.md`, `memory/**`, `docs/**`, `.claude/**`, `LICENSE`). Branch protection requires it because `paths-ignore` in `ci.yml` skips the real workflow.

Full pyramid table, what each layer catches, ALLOWLIST coupling rules, .dict regeneration procedure: [`tests/README.md`](tests/README.md).

---

## Known quirks (this machine's specific weirdness)

These have already tripped someone up — flag them when relevant.

- **Happy Hare v4 layout (since 2026-10-17).** `config/mmu/macros/*` and `config/mmu/optional/*` are symlinks on the Pi into `~/Happy-Hare/config/`; `config/mmu/base/*` are installer-generated real files. In this repo all are plain files (dereferenced by `tar -h` on pull); `deploy_to_pi.sh` auto-discovers and skips Pi symlinks. See [`config/mmu/`](#configmmu--happy-hare-mmu).
- **Happy Hare's Moonraker `update_manager` tracks `main`, which became v4 upstream.** The 2026-10-17 "Update all" pulled v3.4.2 → v4.1.0 without warning and Klipper failed to load (`cannot import name 'mmu_unit'`) until v4's installer was run. Future HH updates: run `~/Happy-Hare/install.sh` (non-interactive form in the MMU section) after any pull that changes `extras/`.
- **HH v4.1.0 startup race (upstream bug):** `mmu_buffer.py:136` `sync_tension_callback` dereferences `self.mmu`, which is only set in `handle_connect`. If the PA7 tension switch reports before every MCU has connected (e.g. a toolhead USB drop stalls the eddy/EBB handshake) Klipper dies with `AttributeError: 'MmuBuffer' object has no attribute 'mmu'` → "Unhandled exception during run". A plain `FIRMWARE_RESTART` with a healthy USB link clears it.
- **`config/mainsail.cfg` is a symlink** to `~/mainsail-config/mainsail.cfg`. Same caveat. (The upstream repo ships both `client.cfg` and `mainsail.cfg` as identical copies; the symlink target is the latter — verify with `ls -l` on the Pi.)
- **`config/timelapse.cfg` is a symlink** to `~/moonraker-timelapse/klipper_macro/timelapse.cfg`. Same caveat. Component installed 2026-05-18 (closes [#26](https://github.com/bjdeng/voron-2-611/issues/26)); usage is opt-in per print.
- **Toolhead cutter is Filametrix**, not EREC; eject buttons are not installed. (v3's unused `mmu/addons/mmu_erec_cutter*` / `mmu_eject_buttons*` files went away with the v4 migration.)
- **`ModemManager` must not run on this Pi.** It probes new USB-serial devices and could hold MCUs open during enumeration — a footgun on this 5-USB-MCU machine (caused the `mcu 'mmu': Unable to connect` race during the first live `/deploy-to-pi`, 2026-05-14). The MainsailOS 3.0.0 image doesn't install it at all (`systemctl is-enabled ModemManager` → `not-found`); if a future image ships it, `sudo systemctl mask --now ModemManager.service`.
- **SKR Z + EASY-BRD MMU consistently fail USB re-enumeration after `FIRMWARE_RESTART`** — root-caused as a kernel timing race, NOT ModemManager and NOT a physical disconnect. Both MCUs boot slower than the kernel's USB enumeration retry budget (~5s). dmesg pattern: `device descriptor read/64, error 2` → `device not accepting address, error -22` → `unable to enumerate USB device`. The boards are physically connected and electrically fine; the kernel just gave up. **One-shot recovery:** `sudo sh -c 'echo 1-1.3 > /sys/bus/usb/drivers/usb/unbind; sleep 2; echo 1-1.3 > /sys/bus/usb/drivers/usb/bind'`. **Permanent fix:** `klipper-mcu-watchdog.service` (GH issue #37, `scripts/klipper-mcu-watchdog.sh`).
- **No CAN bus.** The toolhead is on USB (`config/toolhead.cfg`). EBB SB v1.0 supports both modes; Ben chose USB.
- **Webcam is plugged in again** — HP Webcam HD 5210 (`03f0:cf07`) on Pi hub port 1-1.2, present in every USB capture since at least 2026-08-17 (it was unplugged in 2026-05 for "timing issues"; see [#27](https://github.com/bjdeng/voron-2-611/issues/27)). It was cleared as a cause of the toolhead USB drops below. Since 2026-10-18: crowsnest v5 in `camera-streamer` mode, 1280x720@15. Mainsail's webcam entry (Moonraker DB, not a config file) is service `mjpegstreamer-adaptive`, stream `/webcam/?action=stream`, snapshot `/webcam/?action=snapshot`; update it via `POST /server/webcams/item` (not `/post`). **WebRTC doesn't work yet:** camera-streamer produces H.264 (HW encoder `/dev/video11`), answers `/webrtc` signalling with a valid offer and advertises the right host candidate (192.168.0.226 UDP), but Mainsail 2.19 with service `webrtc-camerastreamer` shows an empty box (no spinner/error). Next step if pursued: browser devtools console with WebRTC selected — signalling-version mismatch vs ICE/network path.
- **Toolhead USB hub drops = check the XT30 at the EBB end first.** Signature: `usb 1-1.4: clear tt 1 … error -71` burst → the whole hub disconnects. 1-1.4 is the EBB SB v1.0 (SB2209 USB)'s onboard FE1.1s hub (`1a40:0101`); EBB is 1-1.4.4, **eddy plugs into the EBB's hub** (1-1.4.3), so both MCUs vanish together and Klipper shuts down ("Lost communication with MCU 'EBB'/'eddy'"). Recurring 2026-08-17 → 2026-10-17; **major contributor: the XT30 2+2 USB/power connector at the toolhead end wasn't fully pushed in** — reseating cut drops from every ~2–10 min to ~43 min but did not eliminate them (2026-10-17); the cable was hand-spliced at the 2026-06 board swap and that 480 Mb/s link is now the prime suspect — replace with an unspliced cable (power pins OK, power LED on; data/GND marginal; worse as the toolhead warmed). Ruled out on the way: EBB board, Pi power, Pi software, webcam. usbmon showed clean traffic then abrupt total loss — a contact fingerprint, not noise. If it recurs after any toolhead work, reseat that connector before anything else. On-Pi evidence: `usb-rca-monitor.service` (`/home/pi/usb-rca-monitor/`, NOT in this repo) writes captures to `~/printer_data/logs/usb-rca/incident-*`. Log: `memory/troubleshooting-log.md` 2026-10-17.
- **OS is MainsailOS 3.0.0 / Debian 13 trixie (reflashed 2026-10-18)**, kernel 6.18, Python 3.13. Replaced MainsailOS 1.0.0 / bullseye (EOL; its apt broke with `bullseye-security … 404`). Full 64 GB image of the old card: `~/Downloads/voron-bullseye-2026-10-17.img.gz` on Ben's MacBook; key files: `~/voron-pi-backup-2026-10-17/` on the Mac Claude runs on. Non-default OS tweaks applied after flashing (not in this repo's `config/` — redo after any reflash, see [`docs/pi-environment.md`](docs/pi-environment.md#fresh-pi-bootstrap)): Wi-Fi power save off (`/etc/NetworkManager/conf.d/99-wifi-powersave-off.conf`), `/dev/vcio` readable by group `video` (`/etc/udev/rules.d/99-vcio-video.rules` — without it Moonraker can't read under-voltage/throttle state), persistent journal capped at 100 MB / 1 month (`/etc/systemd/journald.conf.d/50-persistent-bounded.conf`), rotated printer logs >30 days auto-deleted (`/etc/tmpfiles.d/printer-logs-cleanup.conf`).
- **Fresh-Pi bootstrap: `/deploy-to-pi` can't do the first deploy.** Its idle gate needs Klippy running, and Klippy can't load until the config exists. Bootstrap order: restore the live `printer.cfg` (carries SAVE_CONFIG — deploy keeps the *Pi's* SAVE_CONFIG, so deploying onto an empty Pi would drop all calibration), `mmu/mmu_vars.cfg` and `mmu/.mmu_config` from backup → install add-ons → one-time rsync of `config/` with deploy's excludes (no `--delete`) → Klippy `ready` → `scripts/deploy_to_pi.sh --force` to write the deploy marker. Details in `docs/pi-environment.md`.
- **Sonar must stay disabled (`config/sonar.conf` `enable: false`).** MainsailOS 3 ships it disabled; our old v0.2 config had `enable: true`, and once deployed, a single failed ping to the router made sonar restart NetworkManager, which failed the next ping → **NetworkManager restarted every ~20 s and the Pi dropped off Wi-Fi** (2026-10-18 14:17, signal was fine at −56 dBm/5 GHz). Signature in `journalctl`: repeated `Stopping NetworkManager.service` / `Started NetworkManager.service`. NetworkManager reconnects on its own; Wi-Fi power save is off.
- **Wi-Fi flapped once more on the first-night boot (2026-10-17, before config deploy, sonar still disabled):** 4–13 s reachable bursts for ~30 min, uptime continuous, power clean; RAM-only logs, cause unknown. If it recurs: `journalctl -b -1 -u NetworkManager -u wpa_supplicant` (journal is persistent now).
- **Klipper has no update_manager block.** Klipper updates are not automated through Moonraker — likely intentional to avoid breaking the `eddy-ng` + Happy-Hare overlay (note: eddy-ng was migrated off in PR #17 but Happy-Hare overlay still relies on this).
- **SAVE_CONFIG block lives at the bottom of `config/printer.cfg`.** Klipper rewrites it on every `SAVE_CONFIG`. When syncing this repo → Pi, never overwrite the Pi's SAVE_CONFIG section.
- **The Pi's SAVE_CONFIG block can outlive section deletions.** If you delete a `[section]` from the body but the Pi still has corresponding `#*# [section]` lines, Klipper fails to start with "section must be specified". Strip stale SAVE_CONFIG entries via ssh + sed before deploying section removals. (Lesson from Eddy migration: stale `[probe_eddy_ng btt_eddy]` calibration in Pi SAVE_CONFIG had to be manually stripped after the section was removed.)
- **Microsteps 128 + interpolate:True on X/Y/Z + autotune + CRT chopper overrides** — the noise-optimized final state from #24 + #98. Phase A's microsteps:64 was reverted in PR #97 when it didn't beat baseline. Phase B's autotune defaults regressed audible noise; aligned-config PR #97 recovered to baseline. Empirical CRT tuning (PR #100) overrode TOFF/HSTRT/HEND chopper params via a `[delayed_gcode _apply_crt_chopper]` and achieved an audible improvement past baseline on X/Y/diagonal motion (13/15 tested speeds quieter). `[autotune_tmc]` blocks retained for everything autotune does besides chopper. Z motors share the same CRT combo but show no audible change (their peak was a ~3% improvement, sub-threshold).
- **chopper-resonance-tuner is Pi-only** at `~/chopper-resonance-tuner/` (no vendor submodule, matches the klippain-shaketune pattern). `chopper_tune.cfg` lives at `~/printer_data/config/chopper_tune.cfg` as a symlink; auto-excluded from rsync by `scripts/deploy_to_pi.sh`. The upstream `install.sh` has an interactive y/n prompt for the moonraker `[update_manager]` block (broke our automated install — we add the block via repo PR instead), and a `[respond]` declaration it tries to add to printer.cfg line 1 is redundant (mainsail.cfg already declares it). Re-run `install.sh` after Klipper version bumps. Also: requires a separate `apt + venv + pip` step after the y/n prompt to install the plotter venv at `~/chopper-resonance-tuner/.venv/` — if that step is skipped, FIND_VIBRATIONS/CHOPPER_TUNE will run motors but the resulting heatmaps won't be generated.
- **The 2-pass `QUAD_GANTRY_LEVEL` override is load-bearing and will stay that way.** A/B motor weight sags the rear when motors are off; a single-pass QGL would fail. First pass uses `METHOD=default` (descend) because `horizontal_move_z=8` is outside the eddy cal range, which is hardcoded to Z≤4 mm in Klipper (see Klipper gotchas). Second pass uses `METHOD=scan` at `horizontal_move_z=2`. See `memory/qgl-two-pass-intentional.md`. ([#22](https://github.com/bjdeng/voron-2-611/issues/22) closed won't-fix 2026-05-19.)
- **`config/mainsail.cfg` is "read-only" upstream.** mainsail-config's file header says don't edit. We've been pulling Ben's customizations through `[gcode_macro _CLIENT_VARIABLE]` instead. The refactor spec (Phase 2) plans to break the symlink and slim the file locally — when that happens, future mainsail-config updates won't auto-apply.
- **HH v4 settings live in `config/mmu/.mmu_config`, not in the generated `.cfg`s.** Toolhead distances, TMC currents, servo angles etc. are `CONFIG_*` lines there. Hand-edits to `config/mmu/base/*.cfg` (e.g. via Mainsail) survive a default (`refresh`) installer run but are discarded by a `replace` run — so put lasting changes in `.mmu_config`.
- **HH v4 client macros override Mainsail's PAUSE/RESUME/CANCEL_PRINT.** The installer includes `mmu/optional/client_macros.cfg` LAST in `printer.cfg` (and re-adds it there if moved), so HH's macro bodies win and `_CLIENT_VARIABLE` is no longer read. Our cancel cleanup is wired via `CONFIG_VAR_CLIENT_USER_CANCEL_EXTENSION="_CANCEL_PRINT_HOOK"` and the rear-left pause park via `CONFIG_VAR_SEQUENCE_PARK_PAUSE="10, 340, 5, 0, 2"` (both set 2026-10-17, after the first v4 install had silently dropped them). See `config/client_hooks.cfg` header.
- **`BLOBIFIER` requires `QUAD_GANTRY_LEVEL` first.** The macro parks at the purge tower at specific bed coords and won't proceed if the gantry isn't trammed — fails with a quiet `Purging...` log line but no actual extrusion. Also: a manual `G1 E30` after `MMU_LOAD` won't push filament out the nozzle — `toolhead_sensor_to_nozzle` is ~85 mm on this build, so the load ends with filament at the sensor but ~85 mm short of the nozzle. Use `BLOBIFIER PURGE_LENGTH=200` (or higher) to actually purge through the melt zone.

---

## Klipper gotchas (general — apply to any Klipper config work)

Lessons hard-won during the 2026-05-15 Eddy migration session. None of these are documented in obvious places.

- **`#` is a comment delimiter everywhere in Klipper macros — including inside string literals in `{ ... }` action blocks, and inside jinja `{# ... #}` comment blocks (single-line or multi-line).** Klipper's `configfile.py:append_fileconfig` runs `line.find('#')` per line BEFORE the gcode body reaches jinja, truncating each line at the first `#`. So `{# tag #}` becomes `{` + nothing (everything from the first `#` on is stripped), leaving jinja with an unclosed expression — fails on the next non-whitespace token, typically deep inside the macro body where the cause is unobvious. **Workaround: never use `{# ... #}` jinja comments in this codebase.** Use Klipper `# ...` line comments instead — those get stripped to whitespace per line and never reach jinja. (String-literal case caught by PR #18 after Eddy migration; full `{# #}` failure mode — even single-line — caught by PR #73 CI during the chamber control review-fixup pass. Earlier Task 3 single-line `{# #}` tags shipped without exercising klippy parse on their own because assembled-stack CI failed earlier and masked the issue.)
- **A gcode_macro template renders ONCE per macro invocation, before any commands execute.** A macro body like `PROBE METHOD=tap; SET_KINEMATIC_POSITION Z={printer.probe.last_z_result}` substitutes `last_z_result` to the PRIOR value because jinja runs before the gcode. Split into two macros (parent calls A then B; B's template renders separately after A finishes) — see `config/eddy.cfg`'s `SET_Z_FROM_PROBE`/`_RELOAD_Z_OFFSET_FROM_PROBE` pair (pattern from upstream's since-removed "Homing correction macros" section).
- **`sensor_type: temperature_mcu` is NOT supported on LPC1769.** Klipper's supported list (`vendor/klipper/klippy/extras/temperature_mcu.py`) covers rp2/sam3/sam4/samd21/samd51/stm32f1-4/stm32g0/stm32g4/stm32l4/stm32h7 only. Cannot add MCU die-temp sensors for the SKR 1.4 boards on this build.
- **MCU firmware can lag host Klipper version.** Bumping `vendor/klipper` doesn't reflash MCUs. New host features (e.g., `trigger_analog_query_state` for native Eddy) require corresponding firmware. Klipper will report version mismatch + missing commands on `RESTART`.
- **`.config` files miss new Kconfig options after Klipper bumps.** Run `make olddefconfig` after a Klipper version bump to apply new defaults (e.g., `CONFIG_WANT_TRIGGER_ANALOG=y` auto-enables when `CONFIG_WANT_LDC1612=y` exists).
- **`make flash FLASH_DEVICE=...` for RP2040 has a USB-reconnect race.** `flash_usb.py` loses track of the device after entering bootloader (reads from a stale sysfs path). Workaround: manually mount the BOOTSEL UF2 volume (`/dev/sda1` typically) and `cp` the `out/klipper.uf2` file. The RP2040 auto-reboots into Klipper mode after the UF2 lands.
- **SAMD21 boards use BOSSA, not katapult.** For the EASY-BRD MMU MCU, prefer KIAUH's flash flow over hand-driving `~/BOSSA/` — KIAUH handles the bootloader-button timing.
- **eddy native scan probing refuses out-of-calibrated-range Z, and the calibrated range is hardcoded to Z=0–4 mm.** `PROBE_EDDY_CURRENT_CALIBRATE` always samples `max_z = 4.0` in 40 µm steps regardless of the toolhead's starting Z — see `vendor/klipper/klippy/extras/probe_eddy_current.py:150-152`. Scan/rapid_scan modes error with "sensor not in valid range" above 4 mm. eddy-ng was more permissive. This is why our QGL first pass at `horizontal_move_z=8` uses `METHOD=default` instead of scan — won't change without a Klipper patch. [#22](https://github.com/bjdeng/voron-2-611/issues/22) closed 2026-05-19 as won't-fix.
- **`PROBE_EDDY_CURRENT_TAP_CALIBRATE` flow:** `TAP=guess` → `TAP=refine` → `TAP=verify` (parameter is `TAP=`, not `ACTION=`; running the command with no `TAP=` just prints diagnostic info — last tap freq/slope, current main cal — and does NOT move the toolhead). **Only `TAP=verify` saves `tap_threshold` to config.** `_refine_tap_threshold` lives in memory only; don't restart Klipper between `refine` and `verify`. Source: `vendor/klipper/klippy/extras/probe_eddy_current.py:405-439`.
- **Native tap failures after a main re-cal at a different coil temp — root cause unconfirmed.** An earlier version of this bullet said native tap has "NO signal filtering". That's wrong: `EddyTap._setup_tap` runs a 25 Hz lowpass + derivative on the MCU trigger (`vendor/klipper/klippy/extras/probe_eddy_current.py`), at both the old `4767a8ed` pin and `9cb99754`. Upstream also says tap doesn't use the main calibration and isn't subject to thermal drift (`Eddy_Probe.md` "tap" probing method). The 2026-05-22 reposition session (`docs/eddy-probe-reposition.md` "Diagnostic notes") traced the same symptom to a descent floor that was too high (`position_min: 0`, now `-5`), and that may have been the 2026-05-19 cause too. Eddy-ng's tap used a 5–25 Hz band-pass (`vendor/eddy-ng/probe_eddy_ng.py:251-254`). Symptom: `Unable to detect tap: insufficient slope delta` with `contact_slope_delta` ≤ 0 in the `PROBE_EDDY_CURRENT_TAP_CALIBRATE` (no args) diagnostic. Verified 2026-05-19: cal anchored at coil 57.9 °C, re-cal attempted at 69.2 °C → subsequent taps failed at coil temps outside ±5 °C of either anchor. Rollback procedure: splice old SAVE_CONFIG block from Klipper backups at `~/printer_data/config/printer-YYYYMMDD_*.cfg`. Real fix: [#25](https://github.com/bjdeng/voron-2-611/issues/25).
- **Happy Hare calibrations never need SAVE_CONFIG.** HH writes selector offsets, gear rotation distances, bowden lengths, encoder resolution and saved servo angles straight to `mmu/mmu_vars.cfg` (Klipper `[save_variables]`) the moment a calibration finishes. `SAVE_CONFIG` is only for Klipper's own blocks (PID, Eddy, bed mesh, input shaper).
- **"Encoder didn't report enough movement" is usually grip, not the encoder.** Diagnose in this order (2026-10-18): (1) encoder at rest + motors-only moves should count 0 (no phantom pulses); (2) hand-push filament should count; (3) `MMU_TEST_MOVE MOVE=50` measured vs commanded; (4) repeat with `MMU_TEST_CONFIG UNIT=0 servo_active_down=1` — if that fixes it, the servo arm isn't holding unpowered (worn arm / not reaching its detent / wrong down angle). Runtime `MMU_TEST_CONFIG` changes revert on restart.
- **Servo angle calibration (HH v4):** two separate commands — `MMU_SERVO ANGLE=n` (moves; no `POS`), then `MMU_SERVO POS=down|up|move SAVE=1`, which saves the servo's **current** angle (→ `mmu_vars.cfg`, overrides config). **`ANGLE=` is silently ignored when `POS=` is given**, so the HH docs' one-liner `MMU_SERVO ANGLE=128 POS=up SAVE=1` just re-saves wherever the servo already is. Read state with plain `MMU_SERVO` (check `Positions:` actually changed). **`MMU_TEST_CONFIG servo_*_angle=…` has no effect on servo positions** — the angle table is built once at startup; only `MMU_SERVO … SAVE=1` or a config change + restart moves it (`servo_active_down` *is* read live). `MMU_SERVO RESET=1` deletes the saved angles but the old ones stay in memory **until a Klipper restart** — if the pulse range changed in between, the stale angle can overdrive the arm; restart immediately. Put final angles in `.mmu_config` (survives RESET/reinstall), then RESET + restart so no `mmu_vars` override remains. Pulse range is HH's default for the SAVOX SH0255MG (0.00085–0.00240 s); angles on another range aren't comparable — convert via pulse µs. Criteria used 2026-10-18: down = holds filament with servo unpowered (`MMU_TEST_MOVE`, filament loaded — 0 mm means check the filament is still there); up = filament free + margin, not into the top stop; move = quietest back-to-back during home + gate 0→5→0, above the filament-drag angle.
- **Happy Hare toolhead parameters do NOT persist via SAVE_CONFIG.** `MMU_CALIBRATE_TOOLHEAD CLEAN=1/DIRTY=1/CUT=1` with `SAVE=1` (default) updates them in memory only. Under HH v4 the command prints `"Update mmu_hardware_<unit>.cfg to persist settings"` (`vendor/happy-hare/extras/mmu/commands/mmu_calibration_commands.py:586`), but the lasting home is the `CONFIG_PARAM_TOOLHEAD_*` lines in `config/mmu/.mmu_config` (then re-run the installer in replace mode) — a hand-edit of the generated `.cfg` is lost on the next replace-mode install.
- **`MMU_CALIBRATE_TOOLHEAD` requires extruder ≤ 70 °C.** `_probe_toolhead()` (`vendor/happy-hare/extras/mmu/commands/mmu_calibration_mixins.py:370`, `cold_temp=70`) sets target to 0 and waits for cooldown before each probe — uses collision detection against a solid (cold) heatbreak/nozzle to measure dimensions. Don't try to run it at print temps. CLEAN measurement is order-dependent: feeds filament through bowden+extruder, probes against nozzle's internal shoulder. Procedure: [`docs/mmu-toolhead-calibration.md`](docs/mmu-toolhead-calibration.md).
- **`TEMPERATURE_PROBE_CALIBRATE` takes one Z reading per STEP°C: a paper test by default, or an automatic tap with `MANUAL_METHOD=tap` (lowercase; `manual_probe.py` doesn't lowercase it).** In tap mode a single failed tap aborts the whole run and discards every sample (`AutoProbeHelper.callback` swallows the error, then `ACCEPT` finalizes with `None`). Don't jog Z between samples: `TEMPERATURE_PROBE_NEXT` taps from the current Z. With the default method, `STEP=2` → ~25 paper tests over 50°C. Quadratic LSQ fit error ≈ σ × √(3/(N−3)). STEP=2 gives ~1-2µm fit error. Higher STEP = fewer samples, worse fit. Tradeoff is real — see source comments around line 374 of `temperature_probe.py`.
- **Circular dependency on first Eddy calibration.** Native Eddy needs calibration to home Z, but calibration needs Z-homed first. Workaround: `FORCE_MOVE STEPPER=stepper_z DISTANCE=N VELOCITY=5` to manually position, then `SET_KINEMATIC_POSITION Z=20` to claim Z homed, then run `PROBE_EDDY_CURRENT_CALIBRATE` (what `docs/eddy-probe-reposition.md` Phase 2 does). Upstream's current version is in `vendor/klipper/docs/Eddy_Probe.md` §"Performing initial calibration when homing with probe": hand-position the nozzle ~20 mm up, then `SET_STEPPER_ENABLE STEPPER=stepper_z` + `SET_KINEMATIC_POSITION Z=25`. `[force_move] enable_force_move: True` is still required.
- **`deploy_to_pi.sh` drift gate compares the Pi to the *last-deployed* commit (`.last-deploy-sha`), then drops any file whose Pi copy already matches the committed `HEAD` blob (not the working tree, so an untracked local copy doesn't count; the decision is logged as `synced:<files>` in `deploy-to-pi.log`).** That second step (2026-10-23) covers the edit-on-Pi → `/sync-from-pi` → PR flow, such as HH `.mmu_config` changes. Before it, those already-synced files were "captured" into an empty commit, which failed and aborted every deploy, including `--dry-run` and `--force`. Only Pi content the repo doesn't have counts as drift.
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

**Filament calibration:** `/calibrate-filament` walks temp → flow → Adaptive PA for one filament (brand+material), writes scalars into the OrcaSlicer profile via `scripts/orca_profile_edit.py`, and logs to `memory/filaments/`. Spec: [`docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md`](docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md). Never auto-commits or deploys.

---

## Vendor / submodules

Reference docs are pinned to versions matching the Pi. Always grep these first before going to the web.

| Path | Upstream | Pin | Why |
|---|---|---|---|
| `vendor/klipper` | Klipper3d/klipper | `9cb99754` (v0.13.0-800) | Source + `docs/`. Sparse-checked to `docs/ klippy/ src/ test/ .github/ scripts/`. Host only — MCU firmware on the Pi is older (SKRs + EASY-BRD -375, EBB -688, eddy -649) and still protocol-compatible. |
| `vendor/happy-hare` | moggieuk/Happy-Hare | `f96cd374` (v4.1.0-16) | MMU control, v4 Kconfig installer (`installer/`), `config/` templates. v3 is on upstream's `v3` branch. |
| `vendor/eddy-ng` | vvuk/eddy-ng | `c7ca62e` (v0.1-73) | Third-party probe extension; **migration to native shipped PR #17, 2026-05-15**. Retained for reference + rollback ability. Eventual cleanup pending. |
| `vendor/voron-2` | VoronDesign/Voron-2 | `Voron2.4` branch tip | V2.4 manual/BOM (sparse: `Manual/ firmware/ slicer_profiles/`) |
| `vendor/mainsail-config` | mainsail-crew/mainsail-config | `ff3869a` (v1.2.1-1) | Source of `mainsail.cfg` (the actual symlink target on the Pi) |
| `vendor/moonraker` | Arksine/moonraker | `9e676eb` (v0.11.0-3) | Moonraker `docs/` |
| `vendor/btt-docs` | bigtreetech/docs | shallow `main` | BTT hardware reference (sparse: text only, no images) |
| `vendor/klipper-tmc-autotune` | andrewmcgr/klipper_tmc_autotune | `b6c7cfa` (v0.2.0-385) | TMC autotune extension — source of `[autotune_tmc]` blocks + `motor_database.cfg` (used by `config/motion.cfg`) |

Bump deliberately with `git submodule update --remote vendor/<name>` — pin updates are PRs, not auto-pulled in CI.

Non-vendored hardware references (ERCF v2, Galileo G2E, EASY-BRD, Stealthburner v2 — too CAD-heavy to vendor): see [`docs/hardware.md`](docs/hardware.md#hardware-references-not-vendored).

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
│   │   └── calibrate_flow.cfg   # Frix_x (PA calibration is slicer-side — OrcaSlicer Adaptive PA)
│   ├── mmu/                     # Happy Hare v4
│   │   ├── .mmu_config          # HH Kconfig settings — source of truth for HH config
│   │   ├── base/                # generated by HH install.sh from .mmu_config (real files on Pi)
│   │   ├── macros/              # symlinks-on-pi to ~/Happy-Hare/config/macros/ (incl. blobifier, cut_tip)
│   │   ├── optional/            # symlinks-on-pi to ~/Happy-Hare/config/optional/
│   │   └── mmu_vars.cfg         # Pi-canonical [save_variables] snapshot (keys mmu_mmu_*)
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
└── vendor/                      # 8 git submodules — see ## Vendor / submodules
```
