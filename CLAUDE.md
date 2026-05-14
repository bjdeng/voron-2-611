# Voron 2.611 — Klipper config repo

This repo is the canonical source of truth for the Klipper/Mainsail/Happy-Hare configuration of Ben's Voron 2.4. The on-printer filesystem at `~/printer_data/config/` is the working copy; this repo is where changes are reviewed and tracked. The eventual workflow is: **edit here → PR → merge to `main` → sync to printer**, but that automation is not built yet (see [Workflow & CI/CD](#workflow--cicd)).

---

## Printer identity

- **Model:** Voron 2.4 r2
- **Build size:** 350 mm
- **Community serial:** **2.611** (rendered on the LCD via `macros/lcd_tweaks.cfg:126`; not a date or kit number)
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
- **Stealthburner v2** body
- **Galileo extruder** — explains the unusual `gear_ratio: 9:1` + `rotation_distance: 48.033` in `btt-ebb-sb-usb-v1.0.cfg`
- **Dragon clone hotend** (vendor unknown; behaves Dragon-compatible)
- 0.4 mm nozzle, 1.75 mm filament (Generic 3950 thermistor, pullup 2200 Ω)
- **LIS2DW** accelerometer on toolhead (for resonance testing); `axes_map: z,x,y`

### Probe
- **BTT Eddy** running the `vvuk/eddy-ng` Klipper extension (`[probe_eddy_ng btt_eddy]` with butter tap mode)
- Calibrated drive currents 15 & 16; current `reg_drive_current: 15`, `tap_drive_current: 15`
- Probe offset: `x_offset: 0`, `y_offset: 21.42`
- **Open question:** much of eddy-ng is now reportedly in upstream Klipper (`[probe_eddy_current]`) — there's a likely migration off the fork. See [Open investigations](#open-investigations).

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
- Add-ons enabled: **Blobifier** (purge tower), **EREC** (toolhead filament cutter), **mmu_eject_buttons**
- Toolhead/extruder filament sensors on the EBB board (gpio6, gpio21)
- Sync feedback: tension switch on `mmu:PA7` (compression switch not connected)

### Installed but **not** in active use (per Ben, 2026-05-13)
- **moonraker-timelapse** — never used. Included via `[include timelapse.cfg]` and `[update_manager timelapse]` is in `moonraker.conf`, but it's effectively dead code. Candidate for removal.
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

**Firmware build kconfigs are vendored in `firmware/`** (pulled from `~/klipper-kconfigs/` on the Pi):
- `firmware/mcu.config` — both SKR 1.4 boards (LPC1769 with USB)
- `firmware/ebb-usb.config` — EBB SB v1.0 (RP2040 with USB, not CAN)
- `firmware/eddy.config` — BTT Eddy (RP2040 with USB; loaded by eddy-ng)
- `firmware/easy-brd.config` — ERCF EASY-BRD (SAMD21G18A)

When recompiling a board's firmware, drop the matching file into `~/klipper/.config` before `make`.

---

## Macro inventory

Every active macro and where it lives. One-liner per macro; deeper context belongs in the file itself or in [`memory/decisions.md`](memory/decisions.md).

### `macros/macros.cfg` — Ellis-derived utilities
- `_CG28` — `G28` only if not already homed
- `_CQGL` — `QUAD_GANTRY_LEVEL` only if not already applied
- `OFF` — shut everything off (steppers, heaters, part fan, chamber fan, bed fan, case light)
- `SHUTDOWN` — `OFF` + tell Moonraker to power off the host
- `PARKFRONT` / `PARKFRONTLOW` / `PARKREAR` / `PARKCENTER` / `PARKBED` — toolhead parking positions
- `_RESETSPEEDS` — revert velocity/accel/SCV to configured maxima
- `M109` (renames original to `M99109`) — wait for hotend within ±1 °C of target
- `DELAYED_OFF` — delayed-gcode wrapper around `OFF`
- `HEATSOAK` — heat bed (+ optional chamber wait) + park center
- `FIRST_LAYER_Z_TEST` — print N parallel lines at incrementing Z-offsets to dial in squish
- `SET_ACTIVE_SPOOL` / `CLEAR_ACTIVE_SPOOL` — Spoolman handoff via Moonraker remote method

### `macros/print_start.cfg` — print sequence (jontek2 pattern)
- `PRINT_WARMUP` — pre-heat without printing (caselight on, BED_MESH_CLEAR, home, QGL, start bed+ext heating)
- `PRINT_START` — full start: home → QGL → bed heat + chamber wait (if bed > 90 °C) → `BLOBIFIER_CLEAN` → re-home Z → `PROBE_EDDY_NG_TAP` → adaptive bed mesh → heat hotend
- `PRINT_END` — cool, reset Eddy tap offset, clear mesh, wait 60 s, `OFF`, `_RESETSPEEDS`

### `macros/bedfans.cfg` — Ellis BedFans automation
- `_BEDFANVARS` — config (threshold, fast, slow speeds)
- `BEDFANSSLOW` / `BEDFANSFAST` / `BEDFANSOFF` — direct controls
- Overrides: `SET_HEATER_TEMPERATURE`, `M140`, `M190`, `TURN_OFF_HEATERS` (all integrate bed-fan logic)
- `bedfanloop` — delayed-gcode that ramps to fast speed once target is reached

### `macros/test_speed.cfg`
- `TEST_SPEED` — home, snapshot position, throw the toolhead around in a configurable pattern, re-home, compare positions to detect skipped steps

### `macros/calibrate_flow.cfg` — Frix_x v1.6
- `FLOW_MULTIPLIER_CALIBRATION` — print thin-wall test shell
- `COMPUTE_FLOW_MULTIPLIER` — accepts caliper measurement, prints the new multiplier
- `_FLOW_CALIB_VARIABLES` — internal state holder

### `macros/calibrate_pa.cfg` — Frix_x v1.2
- `PRESSURE_ADVANCE_CALIBRATION` — bands of varying PA at different speeds

### `macros/lcd_tweaks.cfg` — Mini12864 customization
- `[display_glyph chamber]` / `[display_glyph voron]` — custom icons
- `[display_data __voron_display ...]` — replaces stock layout: extruder/bed/chamber temps, fan speed, progress bar, position. Idle row displays the literal string **`V2.611`**.
- `[menu __main __octoprint]` — disabled (Mainsail doesn't use OctoPrint API)

### `eddy.cfg` — probe + bed mesh + safe_z_home + force_move
- `[probe_eddy_ng btt_eddy]` — Eddy probe in butter tap mode
- `[bed_mesh]` — 9×9 grid over (15, 21.42) → (335, 330), adaptive_margin 5, scan_overshoot 8
- `[safe_z_home]` at (175, 175) with 10 mm z-hop
- `[force_move] enable_force_move: True` (needed when Eddy is both probe and Z endstop)
- `QUAD_GANTRY_LEVEL` — wraps stock with state save + bed mesh clear + 2-pass tighten
- `BED_MESH_CALIBRATE` — renames stock to `BTT_BED_MESH_CALIBRATE` and forces `ADAPTIVE=1 METHOD=rapid_scan`

### `mmu/` — Happy Hare MMU
The whole MMU surface lives here. `mmu/base/*.cfg` are mostly **symlinks to `~/Happy-Hare/config/base/*`** on the Pi (preserved as files in this repo when pulled via `tar -h`). Don't edit the symlinked-source files in this repo unless you also push the change back into the Happy-Hare install dir.

Key macros from Happy Hare (not exhaustive — see `mmu/base/mmu_software.cfg` and `mmu/base/mmu_sequence.cfg`):
- `MMU_HOME`, `MMU_CHANGE_TOOL`, `MMU_LOAD`, `MMU_UNLOAD`
- `MMU_CALIBRATE_GEAR`, `MMU_CALIBRATE_BOWDEN`, `MMU_CALIBRATE_SELECTOR`
- `MMU_STATUS`, `MMU_TEST_*`
- `BLOBIFIER_CLEAN` (from `mmu/addons/blobifier.cfg`)
- `MMU_CUT_TIP` (EREC cutter, from `mmu/base/mmu_cut_tip.cfg`)

### `mainsail.cfg` — Mainsail client.cfg (symlink target on Pi)
- `[gcode_macro PAUSE]` / `RESUME` / `CANCEL_PRINT` / `_CLIENT_*` — standard Mainsail pause/cancel with park behavior

### `archive/` — historical, **not included in printer.cfg**
- `klicky/` — pre-Eddy probe (Klicky) macros: bed mesh calibrate, QGL, klicky macros
- `klicky-variables.cfg` — Klicky positioning variables
- `z_calibration.cfg` — Klicky-based automatic Z calibration

---

## Tuning record (as of pull on 2026-05-13)

From the SAVE_CONFIG block at the bottom of `printer.cfg`. Per Ben: **assume stale, worth re-running** — there have been significant improvements in Klipper's auto-tuning since these were captured.

| Parameter | Value | Notes |
|---|---|---|
| Bed PID | Kp 44.470, Ki 1.246, Kd 396.896 | from `PID_CALIBRATE HEATER=heater_bed` |
| Hotend PID | Kp 23.507, Ki 1.059, Kd 130.460 | from `PID_CALIBRATE HEATER=extruder` |
| Input shaper X | mzv @ 51.4 Hz | LIS2DW measurement |
| Input shaper Y | zv @ 37.4 Hz | LIS2DW measurement |
| Pressure advance | 0.05 (smooth time 0.040) | from `pressure_advance` in `[extruder]` defaults |
| Bed mesh `default` | 9×9, (15, 21.42) → (335, 335) | bicubic, full bed |
| Bed mesh `Default2` | 5×5, (30, 30) → (320, 320) | smaller fallback |
| Eddy NG calibration | drive currents 15 & 16, calibration_version 5 | from `[probe_eddy_ng btt_eddy]` in SAVE_CONFIG |

Update [`memory/tuning-log.md`](memory/tuning-log.md) whenever you re-run a calibration.

---

## Machine context beyond `~/printer_data/config/`

Ben's note: *"on the machine some updates to klipper, happy hare and others occasionally require running ./setup.sh in their home directories and klipper configs rely on other scripts on the machine sometimes."* So the config tree alone is not the whole story.

**Repos installed on the Pi (as of 2026-05-13):**

| Path | Version | Upstream | Notes |
|---|---|---|---|
| `~/klipper` | `v0.13.0-649-g4767a8ed` (master) | Klipper3d/klipper | **Has uncommitted local files** from `eddy-ng/install.sh` and `Happy-Hare/install.sh` (symlinks into `klippy/extras/`). |
| `~/Happy-Hare` | `v3.4.2-22-ga880ac0a` | moggieuk/Happy-Hare | Has `install.sh`. Owns `~/printer_data/config/mmu/base/*` (those files in this repo are dereferenced copies of symlinks). |
| `~/eddy-ng` | `v0.1-73-gc7ca62e` | vvuk/eddy-ng | Has `install.sh`. Likely **migratable to native Klipper Eddy** — see [Open investigations](#open-investigations). |
| `~/moonraker` | `v0.10.0-19-g1ed102e` | Arksine/moonraker | Standard. |
| `~/moonraker-timelapse` | `v0.0.1-143-gc7fff11` | mainsail-crew/moonraker-timelapse | Configured but unused. |
| `~/mainsail` | (web release) | mainsail-crew/mainsail | Static UI files served by nginx. |
| `~/mainsail-config` | `v1.2.1-1-gff3869a` | mainsail-crew/mainsail-config | Owns the `client.cfg` that `mainsail.cfg` symlinks to. |
| `~/kiauh` | `v6.0.6` | dw-0/kiauh | Klipper installer/manager (interactive helper). |
| `~/crowsnest` | `v4.2.0-1-gcf936da` | mainsail-crew/crowsnest | Webcam stack. Daemon runs even though webcam is unplugged. |
| `~/sonar` | `v0.2.0-1-g0d1d7c8` | mainsail-crew/sonar | Network keepalive. Daemon runs. |
| `~/katapult` | `v0.0.1-64-g3e23332` | Arksine/katapult | MCU bootloader for safe re-flashing. |
| `~/BOSSA` | (present) | shumatech/BOSSA | SAM-BA flasher, likely used to flash the EASY-BRD SAMD21. |
| `~/klipper-kconfigs` | (saved configs) | — | Per-MCU build kconfigs. **Mirrored into `firmware/` in this repo.** |
| `~/klippy-env`, `~/moonraker-env` | (venvs) | — | Python virtualenvs. |

**Systemd services running:** `klipper`, `klipper_mcu`, `moonraker`, `nginx`, `sonar`, plus the OS-level usuals. Notably **`ModemManager` is active** — that's the well-known troublemaker that can hold open USB-serial devices when an MCU first appears. If MCUs go missing on boot, that's the first suspect.

**Install/setup scripts that may need re-running after upgrades:**
- `~/eddy-ng/install.sh` — after any `~/klipper` update that might break the symlinks into `klippy/extras/`
- `~/Happy-Hare/install.sh` — same, for the `klippy/extras/mmu/` and `klippy/extras/mmu_*` files

There's no `[update_manager klipper]` block in `moonraker.conf`, **and that's by design.** Moonraker auto-detects Klipper and manages it without an explicit block; the block is only needed to override channel/pinned_commit/refresh_interval. Documented at `vendor/moonraker/docs/configuration.md:2017-2026`.

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

2. **Never edit `printer.cfg` (or any tracked `.cfg`) without showing the diff first.** Propose the change, show the unified diff, and wait for Ben to confirm before writing.

3. **Flag the restart impact of every change.** When proposing an edit to a `.cfg`, state explicitly whether the change needs:
   - `RESTART` — soft-reload Klipper (Python-side changes: macros, gcode_macro, timeline updates, bed_mesh, etc.)
   - `FIRMWARE_RESTART` — full MCU reset (changes to `[mcu]`, pins, kinematics, stepper config, sensor types, anything touching MCU build config, or anything that emits the "this requires FIRMWARE_RESTART" message in the Klipper logs)
   - `restart_method: command` (for the eddy MCU) is set; physical USB replug may still be needed if the MCU disappears.

### About the messy state
4. **Don't assume things on this machine are configured the way they should be.** Six years of upgrades mean orphaned configs, stale tuning, and installed-but-unused software. When something looks off:
   - Investigate root cause before "fixing" or removing
   - Bring it up with Ben before silently changing it
   - Examples of "looks weird but is intentional": the 9:1 extruder gear ratio (Galileo), the chamber heater PID on a `[temperature_fan]`, dual SKR 1.4s on USB instead of CAN, microsteps 128 on X/Y/Z.

5. **Don't auto-delete things even if unused.** `archive/klicky/`, `moonraker-timelapse`, the chamber thermistor cal table — leave alone unless Ben asks. Tag them as candidates in `memory/decisions.md` instead.

### About this repo as canonical source
6. **This repo is the canonical config; the Pi is the working copy.** Eventually changes flow `local edit → PR → main → sync to Pi`. Until that CI/CD is built, manual sync is fine, but **never overwrite the Pi's files without confirming** — Mainsail can also edit configs directly and the Pi may be ahead.

7. **Three classes of file on the Pi to be aware of when syncing:**
   - **Real files we own** — `printer.cfg`, everything under `macros/`, root-level `.cfg/.conf` files. Edit freely here.
   - **Symlinked-from-third-party** — `mmu/base/*.cfg` (Happy-Hare), `mainsail.cfg` (mainsail-config), `timelapse.cfg` (moonraker-timelapse). Editing these on the Pi mutates the upstream install dir. Edits should generally go in the third-party repo, not here.
   - **Auto-generated** — the `#*# SAVE_CONFIG` block at the bottom of `printer.cfg`. Klipper rewrites this on every `SAVE_CONFIG`. Don't merge upstream changes that touch it; always pull the Pi's current version when working with calibration values.

### Vendored docs
See [Vendor / submodules](#vendor--submodules) below. Update with `git submodule update --remote vendor/<name>` only when Ben asks — the pin to the Pi's installed version is intentional.

### SSH and Pi access
The Pi is at `mainsailos.local` (current IP 192.168.0.227). Keyed SSH was set up 2026-05-13; `ssh pi@mainsailos.local` should work without password. The `pi:raspberry` defaults in `.env` are the legacy fallback. Rotate when convenient.

---

## CI checks

GitHub Actions (`.github/workflows/ci.yml`) runs on every `pull_request` and `push` to `main`. Two parallel jobs:

- **Klippy parse + smoke gcode** — runs `vendor/klipper/scripts/test_klippy.py` against `tests/voron-2-611.test`, which loads `printer.cfg` with all five MCUs simulated and walks the gcode dispatcher for a smoke sequence (G28, QGL, `BED_MESH_CALIBRATE METHOD=rapid_scan`, `PRINT_START`, `PRINT_END`, `OFF`, `MMU_STATUS`, parking macros). Catches: syntax errors, unknown sections, pin clashes, missing modules, every jinja2 template error in any `[gcode_macro]` body, and unknown-command errors reachable from the smoke graph. Klipper's `gcode_macro.py` parses every macro template eagerly at config-load (see `env.from_string` in `GCodeMacro.__init__`), so this single step covers most reasons CI would fail. Note: `test_klippy.py` does NOT execute jinja2 bodies at runtime — conditional branches inside macros are not exercised, only the static command graph.
- **pre-commit + macro refcheck + pytest** — `.pre-commit-config.yaml` runs text hygiene (trailing-whitespace, end-of-file-fixer, mixed-line-ending) plus `ruff` (format + lint) on Python. `scripts/macro_refcheck.py` statically verifies every gcode command referenced in a `[gcode_macro]` body resolves to either a defined macro or an entry in `tests/builtins.txt` / the script's `ALLOWLIST`. `pytest tests/` covers the script's unit tests, the eddy-migration acid-test tripwire, and a real-repo regression test.

Local run: `make test-py` (macOS-friendly subset). `make test` adds the klippy step (needs Linux because Klipper's C extension uses `sys/prctl.h` and `linux/can.h`).

See [`tests/README.md`](tests/README.md) for full mechanics. **When to regenerate** cached data:
- `tests/dict/*.dict` — after bumping `vendor/klipper` or modifying `firmware/*.config`. Build on the Pi.
- `tests/builtins.txt` — after bumping `vendor/klipper`. Run `make builtins`.

The **eddy-ng** block in `scripts/macro_refcheck.py`'s `ALLOWLIST` is keyed to `[probe_eddy_ng]` in `eddy.cfg` — when the eddy migration removes that section, the same PR must delete those entries. `tests/test_macro_refcheck.py::test_eddy_ng_allowlist_coupling` is a tripwire that fails if one half of this coupling is removed without the other. (The Happy-Hare block in the same ALLOWLIST is **not** coupled this way; those commands are registered by Python and survive any `.cfg` change.)

---

## Known quirks

These have already tripped someone up — flag them when relevant.

- **MMU `mmu/base/*.cfg` are symlinks on the Pi** to `~/Happy-Hare/config/base/*`. In this repo they're files (dereferenced by `tar -h` on pull). If you push this repo back to the Pi without preserving symlinks, you'll break Happy-Hare's update model.
- **`mainsail.cfg` is a symlink** to `~/mainsail-config/client.cfg`. Same caveat.
- **`timelapse.cfg` is a symlink** to `~/moonraker-timelapse/klipper_macro/timelapse.cfg`. Same caveat — but Ben says he never used moonraker-timelapse and it may be broken; it's a removal candidate.
- **`ModemManager` runs on the Pi — this is bad for Klipper.** ModemManager probes any new USB-serial device that appears, which can hold MCUs open and prevent Klipper from connecting cleanly, especially with 5 USB MCUs as on this machine. It doesn't always cause visible problems, but it's a latent footgun. Recommended fix (idempotent, reversible): `sudo systemctl mask --now ModemManager.service`. Verify with `sudo systemctl status ModemManager` after. This is not currently confirmed to be causing issues here, just a known class of problem.
- **No CAN bus.** The toolhead is on USB (`btt-ebb-sb-usb-v1.0.cfg`). EBB SB v1.0 supports both modes; Ben chose USB.
- **Webcam is unplugged.** Crowsnest + Sonar still run but have nothing to stream.
- **Klipper has no update_manager block.** Klipper updates are not automated through Moonraker — likely intentional to avoid breaking the `eddy-ng` + Happy-Hare overlay.
- **SAVE_CONFIG block lives at the bottom of `printer.cfg`.** Klipper rewrites it on every `SAVE_CONFIG`. When syncing this repo → Pi, never overwrite the Pi's SAVE_CONFIG section.
- **Microsteps 128 on X/Y/Z** (atypically high), plus `interpolate: False` on the TMC2209s. Followed third-party online advice rather than analyzed for this hardware (per Ben). Real goal: quiet without losing steps. Don't change blindly, but this is **worth a deliberate investigation** with current Klipper — the right value could be 16/32/64. See [Open investigations](#open-investigations).

---

## Open investigations

Items Ben has flagged as worth digging into. Track progress in [`memory/troubleshooting-log.md`](memory/troubleshooting-log.md) and [`memory/decisions.md`](memory/decisions.md).

1. **`eddy-ng` → native Klipper Eddy migration.** Upstream Klipper has `[probe_eddy_current]` with tap support. Verify it covers all eddy-ng features in use, particularly: rapid bed scanning, temperature-offset-2 calibration, and touch sensing — these were USB-mode-only on the EBB SB v1.0 when Ben built the printer, which is why the toolhead is on USB instead of CAN. Tracked as task #12.
2. **Sensorless X feasibility on this build.** Currently uses a physical endstop wired to the EBB. Ben's prior understanding was this wasn't viable or was potentially harmful. Worth a fresh look on V2.4 r2 + dual SKR 1.4 + TMC2209.
3. **Microsteps 128 — is this still the right value?** Followed third-party online advice; real goal is "quiet without losing steps" (per Ben). Investigate step-rate budget of LPC1769 + TMC2209 in current Klipper and measure noise/skip behavior at 32/64/128 to decide.
4. **Stale tuning values.** Re-run input shaper / PID / PA / Eddy calibration on current Klipper.
5. **`moonraker-timelapse` is broken.** Ben has never gotten it to work. Decision pending: fix, or remove the include + update_manager entry.
6. **Webcam re-enable.** Currently unplugged due to timing issues. Plan tied to #1 (Eddy migration).
7. ~~**Is there a reason there's no `[update_manager klipper]`?**~~ **Resolved 2026-05-13:** Ben was right; it's by design. Moonraker auto-detects Klipper and Moonraker (`vendor/moonraker/docs/configuration.md:2017-2026`). The block is only needed to override channel / pinned_commit / refresh_interval. See [`memory/decisions.md`](memory/decisions.md).
8. **TDD-equivalent for Klipper configs.** Build a CI pipeline that (a) parses `printer.cfg` with Klipper's own parser, (b) lints jinja2 in `gcode_macro` blocks, (c) reference-checks `M*` rename chains and gcode_macro cross-calls, (d) optionally runs Klipper `--debug` against a recorded `.gcode` print. Lives alongside the deploy automation. Confirmed worth doing.

---

## Workflow & CI/CD

**Today (manual):** edit on the Pi via Mainsail or SSH; periodically `rsync` into this repo. Working but not durable.

**Goal:** edit locally → PR → merge `main` → automated sync to `~/printer_data/config/` on the Pi → `RESTART`/`FIRMWARE_RESTART` as appropriate.

**Sketch (not built yet):**
- GitHub Action on push to `main`:
  - `rsync` only the **non-symlinked, non-SAVE_CONFIG-portion** of files to the Pi over SSH (use the keyed login set up 2026-05-13)
  - Read the current Pi `printer.cfg` SAVE_CONFIG block; re-append it to the synced version before writing
  - Trigger a Moonraker API `printer.restart` (or `printer.firmware_restart` if the diff touches MCU-impacting sections — heuristic: any change outside `macros/`, `archive/`, `mmu/`, top of `printer.cfg`)
  - On failure, the previous file is preserved via Klipper's auto-backup mechanism (`printer-YYYYMMDD_HHMMSS.cfg`)
- Preview/PR workflow: open a PR, CI runs `klipper --validate-config printer.cfg` against a vendored Klipper checkout (this gives a syntactic "test" — see next).

**"Tests" for a Klipper config (TDD-equivalent):**
There's no real unit-test framework for `.cfg` files, but several things are testable on PR:
1. `klippy` config syntax validation (parse the config with Klipper's own parser; catches typos and unknown sections)
2. Macro template lint (jinja2 parse-ability via a small script)
3. `gcode_macro` reference check (every `M*` rename, every `{action_call_remote_method(...)}`, every `[gcode_macro X]` referenced by another)
4. A "smoke test" by running Klipper in `--debug` against a real `.gcode` file (skip when no MCU is connected)

These are good candidates for a `tests/` directory and a GitHub Action. None of this exists yet.

---

## Vendor / submodules

Reference docs are pinned to versions matching the Pi. Always grep these first before going to the web.

**Planned vendored repos** (commands shown below — not run yet; Ben to approve):

| Path | Upstream | Pin | Why |
|---|---|---|---|
| `vendor/klipper` | https://github.com/Klipper3d/klipper | commit `4767a8ed` (matches Pi as of 2026-05-13) | Klipper source + `docs/` |
| `vendor/happy-hare` | https://github.com/moggieuk/Happy-Hare | `v3.4.2-22-ga880ac0a` (matches Pi) | MMU control, mmu/* config templates, README |
| `vendor/eddy-ng` | https://github.com/vvuk/eddy-ng | `c7ca62e` (matches Pi) | While we still depend on it; investigate migration to native Klipper |
| `vendor/voron-2-docs` | https://github.com/VoronDesign/Voron-2 | latest tag (TBD) | V2.4 manual, BOM, sourcing guide |
| `vendor/mainsail-config` | https://github.com/mainsail-crew/mainsail-config | `v1.2.1-1-gff3869a` (matches Pi) | Source of the `client.cfg` symlinked from `mainsail.cfg` |
| `vendor/moonraker` | https://github.com/Arksine/moonraker | `v0.10.0-19-g1ed102e` (matches Pi) | Moonraker docs (under `docs/`) |

Update with:
```sh
git submodule update --remote vendor/<name>
```

(Pin updates should be committed deliberately, not auto-pulled in CI.)

---

## Repo layout

```
voron-2-611/
├── CLAUDE.md                    # this file
├── README.md                    # (not yet written — same content as CLAUDE.md until ready)
├── .env                         # SSH creds (gitignored)
├── .gitignore
│
├── printer.cfg                  # top-level Klipper config (includes everything below)
├── mainsail.cfg                 # symlink target on Pi (→ ~/mainsail-config/client.cfg)
├── timelapse.cfg                # symlink target on Pi (unused per Ben)
├── btt-ebb-sb-usb-v1.0.cfg      # toolhead MCU config
├── eddy.cfg                     # Eddy probe + bed mesh
├── moonraker.conf
├── crowsnest.conf
├── sonar.conf
│
├── macros/                      # printer-specific macros
│   ├── macros.cfg               # Ellis-derived utility macros
│   ├── print_start.cfg          # PRINT_START / PRINT_END / PRINT_WARMUP
│   ├── bedfans.cfg              # BedFans with M140/M190 overrides
│   ├── lcd_tweaks.cfg           # Mini12864 display group (renders "V2.611")
│   ├── test_speed.cfg
│   ├── calibrate_flow.cfg       # Frix_x
│   └── calibrate_pa.cfg         # Frix_x
│
├── mmu/                         # Happy Hare configs (base/optional/addons)
│   ├── base/                    # symlinks-on-pi to ~/Happy-Hare/config/base/
│   ├── optional/                # symlinks-on-pi to ~/Happy-Hare/config/optional/
│   ├── addons/                  # Blobifier, EREC, eject_buttons
│   └── mmu_vars.cfg
│
├── firmware/                    # saved per-MCU build kconfigs (mirror of ~/klipper-kconfigs)
│   ├── mcu.config               # SKR 1.4 (both XYE + Z)
│   ├── ebb-usb.config           # EBB SB v1.0
│   ├── eddy.config              # BTT Eddy
│   └── easy-brd.config          # ERCF EASY-BRD
│
├── archive/                     # historical, not included
│   ├── klicky/                  # pre-Eddy probe configs
│   ├── klicky-variables.cfg
│   └── z_calibration.cfg
│
├── memory/                      # running logs (this repo's, not Claude's global)
│   ├── tuning-log.md
│   ├── troubleshooting-log.md
│   ├── hardware-changes.md
│   └── decisions.md
│
└── vendor/                      # git submodules (TBD — see Vendor section)
```
