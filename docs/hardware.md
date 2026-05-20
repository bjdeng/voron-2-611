# Hardware reference — Voron 2.611

Context for the non-obvious mods, community parts, and provenance choices on this build. **Spec values (pins, drive currents, kinematic constants, USB serial IDs) live in [`config/*.cfg`](../config/) — this doc is the *why* layer.** Each entry below points at the config file holding the actual spec.

For a one-screen orientation, see [CLAUDE.md → Build at a glance](../CLAUDE.md). For Klipper/Voron/HH docs, grep [`vendor/`](../vendor/) first per CLAUDE.md's "How to help me" rules.

## Frame & motion

- **350 × 350 build volume.** Z used max ≈ 335 per mesh, position_max = 330. See [`config/motion.cfg`](../config/motion.cfg) `[printer]` + steppers.
- **CoreXY** kinematics with **quad gantry leveling** (QGL — not Z-tilt; this is a V2, not a Trident). QGL macro override is load-bearing — see [Known quirks in CLAUDE.md](../CLAUDE.md#known-quirks-this-machines-specific-weirdness) for the 2-pass rationale.
- **MGN12 X carriage** — upgraded from stock MGN9. Affects toolhead weight + accel envelope.
- **Beefy idlers mod** — community stiffening upgrade.

## Toolhead

- **Stealthburner v2** body, no SB LEDs installed. Only neopixel chain on this build is the LCD one ([`config/display.cfg`](../config/display.cfg) `[neopixel lcd]`).
- **Galileo G2E extruder** (9:1 ratio) — community drop-in for SBv2. Explains the unusual `gear_ratio` + `rotation_distance: 48.033` in [`config/toolhead.cfg`](../config/toolhead.cfg). Original Galileo (non-G2E) is 7.5:1 — *we don't have that one*.
- **Dragon clone hotend** — vendor unknown, behaves Dragon-compatible. Older variant with ~10-15 mm longer heatbreak than the HF version. This affects MMU toolhead distances — see [`docs/mmu-toolhead-calibration.md`](mmu-toolhead-calibration.md) for the calibrated values.
- **Delta BFB0524HH** 24V 5015 part fan — community upgrade from BOM Sunon MF50151VX-A99. Slightly weaker on paper (4.6 vs 5.4 CFM) but better build, longer-rated, native 24V (matches EBB FAN1 factory-default output). Filament cooling profiles are tuned for this fan — see [`docs/slicer-templates/orcaslicer.md`](slicer-templates/orcaslicer.md). Wired pin in [`config/toolhead.cfg`](../config/toolhead.cfg).
- **0.4 mm nozzle, 1.75 mm filament** (Generic 3950 thermistor). Sizes baked into [`config/toolhead.cfg`](../config/toolhead.cfg).
- **LIS2DW accelerometer** for resonance testing — `axes_map` orientation in [`config/toolhead.cfg`](../config/toolhead.cfg).

## Probe

- **BTT Eddy** running Klipper native `[probe_eddy_current]` (migrated from `vvuk/eddy-ng` in [PR #17](https://github.com/bjdeng/voron-2-611/pull/17), 2026-05-15). The native algorithm has stricter calibration requirements than eddy-ng's Butterworth-filtered tap — see [Klipper gotchas in CLAUDE.md](../CLAUDE.md#klipper-gotchas-general--apply-to-any-klipper-config-work).
- Linked `[temperature_probe btt_eddy]` for thermal drift compensation (shares the postfix). Drift calibration itself still pending — [#25](https://github.com/bjdeng/voron-2-611/issues/25).
- Tap-Z workflow + bed-mesh integration: see [`config/eddy.cfg`](../config/eddy.cfg).

## Bed

- **Textured PEI magnetic flex plate** on milled aluminum bed (the aluminum is rigid; the silicone heater + thumb-screw mount stack has some compliance).
- **Silicone heater** (NTC 100K **MGB18-104F39050L32** thermistor — that specific part matters for the thermistor table). Driven via SSR. See [`config/bed.cfg`](../config/bed.cfg).
- **Ellis-style BedFans** with a modified housing including a **charcoal filter** (from [printables.com/model/334276](https://www.printables.com/model/334276-the-filter-for-voron-24)). Speed thresholds + behavior in [`config/macros/bedfans.cfg`](../config/macros/bedfans.cfg); active control loop in [`config/macros/chamber_control.cfg`](../config/macros/chamber_control.cfg).

## Chamber

- **Active control** via `[temperature_fan chamber]` (a non-standard use of `[temperature_fan]` — see [Klipper gotchas](../CLAUDE.md#klipper-gotchas-general--apply-to-any-klipper-config-work)). 10k_thermistor with a **custom temperature/resistance table** because the standard thermistor types didn't match. Pins + control loop in [`config/bed.cfg`](../config/bed.cfg) + [`config/macros/chamber_control.cfg`](../config/macros/chamber_control.cfg).

## Display & lighting

- **fysetc Mini12864** on EXP1/EXP2 of the XYE SKR 1.4. Custom display layout in [`config/macros/lcd_tweaks.cfg`](../config/macros/lcd_tweaks.cfg) (renders the "V2.611" community serial idle string).
- **3-LED neopixel** chain on the display.
- **Caselight** PWM output_pin. Pin + macros in [`config/system.cfg`](../config/system.cfg) + [`config/macros/macros.cfg`](../config/macros/macros.cfg).

## MMU (Multi-Material Unit)

- **Self-printed ERCF v2** (Enraged Rabbit Carrot Feeder, community edition v2.0). 6 gates, BTT EASY-BRD MCU. LinearSelector + selector servo + Binky-style encoder.
- **No buffer** — spools sit on **Filamentalist rewinders**. Plan: retrofit to Bondtech INDX when available. Design all MMU/spool work to be INDX-survivable.
- **Filametrix** is the toolhead filament cutter ([Carrot-collective/Filametrix](https://github.com/Carrot-collective/Filametrix)) — invoked via `_MMU_CUT_TIP` during HH toolchange. Macro: [`config/mmu/base/mmu_cut_tip.cfg`](../config/mmu/base/mmu_cut_tip.cfg). Cutter pin in [`config/mmu/base/mmu_macro_vars.cfg`](../config/mmu/base/mmu_macro_vars.cfg) `_MMU_CUT_TIP_VARS`.
- **Blobifier** (purge tower) — [`config/mmu/addons/blobifier.cfg`](../config/mmu/addons/blobifier.cfg). Requires QGL first (see Known quirks).
- **Files present but NOT active**: `config/mmu/addons/mmu_erec_cutter*.cfg` and `mmu_eject_buttons*.cfg` — leftover from HH install, not `[include]`d. **EREC is NOT used (Filametrix is); eject buttons are NOT installed.** Don't move them to `archive/` — HH install would recreate them.
- **Sync feedback**: tension switch wired (compression switch not connected). Pin in MMU MCU config.
- **Calibration values** (toolhead distances, blade position, residual filament) — see [`docs/mmu-toolhead-calibration.md`](mmu-toolhead-calibration.md) for the calibration procedure. Values themselves live in [`config/mmu/base/mmu_parameters.cfg`](../config/mmu/base/mmu_parameters.cfg) (which is NOT a Pi-side symlink, unlike other `mmu/base/*.cfg` files — see Known quirks).

## Additional temperature sensors

Beyond bed + extruder + chamber, these are wired and active for diagnostics:

- `[temperature_probe btt_eddy]` — coil-adjacent NTC, linked to the probe for drift comp. See [`config/eddy.cfg`](../config/eddy.cfg).
- `[temperature_sensor btt_eddy_mcu]` — RP2040 die temp.
- `[temperature_sensor EBB_NTC]` — NTC on the EBB toolhead board.
- `[temperature_sensor raspberry_pi]` — Pi SoC temperature.

`sensor_type: temperature_mcu` is **not** supported on LPC1769 (the two SKR 1.4 boards) — see [Klipper gotchas](../CLAUDE.md#klipper-gotchas-general--apply-to-any-klipper-config-work).

## Installed but not in active use

- **moonraker-timelapse** — opt-in per print (no slicer wire-up by default); needs the webcam ([#27](https://github.com/bjdeng/voron-2-611/issues/27)).
- **Webcam** — physically unplugged due to timing/streaming issues. Crowsnest + Sonar daemons still run.
- **Spoolman** — Moonraker is configured against an external server but not in active use day-to-day.

## MCU board details

Klipper-name + role table lives in [CLAUDE.md → MCU map](../CLAUDE.md#mcu-map). USB serial IDs (only matter when re-flashing or replacing) live in [`config/printer.cfg`](../config/printer.cfg)'s `[mcu]` blocks — `serial:` lines.

Firmware build kconfigs are vendored per board in [`config/firmware/`](../config/firmware/). Drop the matching file into `~/klipper/.config` before `make` when recompiling.

## Hardware references not vendored

Heavy hardware projects with large CAD/STL repos (not worth submodule-pinning). Use ad-hoc clones to `~/scratch/` when needed:

- **ERCF v2 MMU** — [Carrot-collective/ERCF_v2](https://github.com/Carrot-collective/ERCF_v2) (1.3 GB CAD-heavy)
- **Galileo 2 extruder** — [JaredC01/Galileo2](https://github.com/JaredC01/Galileo2). Original (7.5:1) at [JaredC01/Galileo](https://github.com/JaredC01/Galileo) — *not* on this build.
- **EASY-BRD MMU MCU** — [Tircown/ERCF-easy-brd](https://github.com/Tircown/ERCF-easy-brd)
- **Stealthburner v2 toolhead** — [VoronDesign/Voron-Stealthburner](https://github.com/VoronDesign/Voron-Stealthburner) (separate from main Voron-2 repo)
