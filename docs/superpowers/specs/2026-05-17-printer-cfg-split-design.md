# Split `printer.cfg` by subsystem — spec

**Closes:** [#63 — Split printer.cfg by subsystem (motion / bed / display / system)](https://github.com/bjdeng/voron-2-611/issues/63)

**Source finding:** F2 from the [2026-05-17 config reorg audit](../audits/2026-05-17-config-reorg-audit.md).

**Restart impact:** RESTART (no MCU firmware, pin, or sensor type changes; pure structural move of `[section]` blocks between files).

---

## 1. Problem

`config/printer.cfg` mixes at least five distinct subsystems in ~404 lines of config plus a 60-line SAVE_CONFIG block:

| Subsystem | Sections present |
|---|---|
| MCU declarations | `[mcu]`, `[mcu z]` |
| Motion | `[printer]` kinematics, 6× `[stepper_*]` + 6× `[tmc2209 stepper_*]`, `[input_shaper]` |
| Bed + chamber thermal | `[heater_bed]`, `[thermistor 10k_thermistor]`, `[temperature_fan chamber]`, `[heater_fan controller_fan]` |
| Z-leveling | `[quad_gantry_level]` |
| Display | `[board_pins]`, `[display]`, `[output_pin beeper]`, `[neopixel lcd]` |
| System / housekeeping | `[temperature_sensor raspberry_pi]`, `[output_pin caselight]`, `[idle_timeout]` |
| Includes | 12× `[include]` |
| Klipper-owned | SAVE_CONFIG block |

To find any section you scroll past every other subsystem. New contributors (and Claude sessions) re-read the whole file to locate one block.

## 2. Goal

Split `printer.cfg` into four function-organized siblings. `printer.cfg` shrinks to MCU declarations, `[include]` statements, and the SAVE_CONFIG block.

**Non-goals:**

- No behavior changes. Pure structural move of `[section]` blocks.
- No tuning value updates. Those belong in [#25 weekend re-tune session](https://github.com/bjdeng/voron-2-611/issues/25).
- No section additions, deletions, or renames.
- No edits to existing feature/MCU files (`eddy.cfg`, `toolhead.cfg`, `mainsail.cfg`, `mmu/*`, `macros/*`).

## 3. Design

### 3.1 Two organizing axes — explicit

The repo's `config/` directory uses two axes simultaneously. Make the rule explicit:

- **By feature or MCU.** One coherent subsystem per file. Examples: `eddy.cfg` (probe + bed mesh + Z homing override + force_move + override macros), `toolhead.cfg` (the EBB SB v1.0 MCU and every section pinned to it), `mainsail.cfg`, `mmu/*`, `macros/*.cfg`.
- **By function.** For mainboard-resident sections that don't form a coherent feature on their own. Introduced by this spec: `motion.cfg`, `bed.cfg`, `display.cfg`, `system.cfg`.

When adding a new section: prefer the feature axis if the section forms or extends a self-contained subsystem; fall back to the function axis only for "this is just another mainboard fan / sensor / output_pin" cases.

Rationale for not also splitting `eddy.cfg` and `toolhead.cfg` by function: splitting `toolhead.cfg` would scatter the EBB pin map across three or four files and lose the "swap the toolhead board = one file diff" property. Splitting `eddy.cfg` would fragment one tightly coupled probing subsystem (probe, thermal drift compensation, bed mesh, homing override, force_move, override macros) into bed/motion/macros pieces; the 2-pass QGL rationale and tap-Z split-macro pattern stop being readable as a unit.

### 3.2 File layout (target)

```
config/
  printer.cfg            # 2× [mcu] + includes + SAVE_CONFIG (~30 LOC + ~60 LOC SAVE_CONFIG)
  motion.cfg             # [printer] + 6 steppers + 6 TMCs + [input_shaper]
  bed.cfg                # [heater_bed], [thermistor 10k_thermistor],
                         # [temperature_fan chamber], [heater_fan controller_fan],
                         # [quad_gantry_level]
  display.cfg            # [board_pins], [display], [output_pin beeper], [neopixel lcd]
  system.cfg             # [temperature_sensor raspberry_pi], [output_pin caselight],
                         # [idle_timeout]
  # unchanged:
  eddy.cfg
  toolhead.cfg
  mainsail.cfg
  timelapse.cfg
  moonraker.conf
  crowsnest.conf
  sonar.conf
  macros/...
  mmu/...
  firmware/...
  archive/...
```

### 3.3 Section assignments

| Section | Destination | Rationale |
|---|---|---|
| `[mcu]`, `[mcu z]` | `printer.cfg` | Entry-point pin-aliases consumed by every other file. Stay at the top of the file Klipper boots from. |
| `[printer]` (kinematics) | `motion.cfg` | The defining "what kind of printer am I" knob. Belongs with steppers it drives. |
| `[stepper_x/y/z/z1/z2/z3]` | `motion.cfg` | Motion. |
| `[tmc2209 stepper_*]` (×6) | `motion.cfg` | Each TMC sits next to its stepper. |
| `[input_shaper]` | `motion.cfg` | Per-axis resonance compensation. Motion. |
| `[heater_bed]` | `bed.cfg` | Thermal. |
| `[thermistor 10k_thermistor]` | `bed.cfg` | Defines the type used by `[temperature_fan chamber]`. Must live in the same file (or be included before it) — keeping them adjacent is least surprising. |
| `[temperature_fan chamber]` | `bed.cfg` | Chamber thermal management. Consumes the 10k thermistor type above. |
| `[heater_fan controller_fan]` | `bed.cfg` | Triggered by `heater: heater_bed` at 45°C — semantically slaved to the bed. Boundary call documented in the file header. |
| `[quad_gantry_level]` | `bed.cfg` | Bed-relative Z-leveling routine. The `QUAD_GANTRY_LEVEL` macro override lives in `eddy.cfg`; that arrangement is preserved. |
| `[board_pins]` (mini12864 EXP1/EXP2) | `display.cfg` | Pin aliases consumed only by `[display]`, `[output_pin beeper]`, `[neopixel lcd]`. |
| `[display]`, `[output_pin beeper]`, `[neopixel lcd]` | `display.cfg` | LCD assembly. |
| `[temperature_sensor raspberry_pi]` | `system.cfg` | Host SoC temperature — diagnostic. |
| `[output_pin caselight]` | `system.cfg` | Chamber lighting. Could plausibly live in `display.cfg` (it's a light) but is unrelated to the LCD assembly; placing it with other housekeeping is the audit's call. |
| `[idle_timeout]` | `system.cfg` | Behavior on idle. |

### 3.4 New `printer.cfg` (target shape)

```ini
## Voron 2.611 — top-level config.
##
## This file is the entry point Klipper loads. It contains:
##   1. The two [mcu] declarations (X/Y/E main board + Z board).
##   2. [include]s for every other config file. Order is for readability;
##      Klipper resolves cross-references after all files load.
##   3. The SAVE_CONFIG block (Klipper-owned, auto-rewritten — do not edit).
##
## All hardware/feature config lives in the included files. See CLAUDE.md
## `## Repo layout` for the map.

[mcu]
serial: /dev/serial/by-id/usb-Klipper_lpc1769_05E0FF1627903CAF12CA6D5CC62000F5-if00

[mcu z]
serial: /dev/serial/by-id/usb-Klipper_lpc1769_1560011845084AAF45F07F5DC52000F5-if00

# Mainboard-resident subsystems (function-organized)
[include motion.cfg]      # kinematics + steppers + TMCs + input shaping
[include bed.cfg]         # bed heater + chamber thermal + QGL + controller fan
[include display.cfg]     # mini12864 LCD, beeper, neopixel
[include system.cfg]      # raspberry pi temp, caselight, idle timeout

# Toolhead MCU (EBB SB v1.0 on USB)
[include toolhead.cfg]

# Probe + bed mesh + Z homing override
[include eddy.cfg]

# MMU (Happy Hare)
[include mmu/base/*.cfg]
[include mmu/optional/client_macros.cfg]
[include mmu/optional/mmu_menu.cfg]
[include mmu/addons/blobifier.cfg]

# Client (Mainsail + timelapse)
[include mainsail.cfg]
[include timelapse.cfg]

# User tunables — first by convention so they're easy to find.
[include macros/_user_variables.cfg]

# Macros
[include macros/macros.cfg]
[include macros/test_speed.cfg]
[include macros/lcd_tweaks.cfg]
[include macros/bedfans.cfg]
[include macros/print_start.cfg]
[include macros/calibrate_flow.cfg]
[include macros/calibrate_pa.cfg]

#*# <---------------------- SAVE_CONFIG ---------------------->
... (unchanged, Klipper-owned)
```

### 3.5 Header style for new files

Each new file gets a short comment header (~5 lines) listing what it owns and the rationale for any non-obvious placements. Example for `bed.cfg`:

```ini
## Bed + chamber thermal subsystem.
##
## - [heater_bed]                  SSR-driven bed heater (z:P2.3, PID-tuned)
## - [thermistor 10k_thermistor]   Chamber thermistor type (calibration table)
## - [temperature_fan chamber]     Chamber heater fan (PID, z:P2.7)
## - [heater_fan controller_fan]   Electronics-bay fan, triggered by heater_bed
## - [quad_gantry_level]           Pre-print Z leveling. The QUAD_GANTRY_LEVEL
##                                 macro override (2-pass) lives in eddy.cfg.
```

The boundary-call rationale (why `controller_fan` is in `bed.cfg` not `system.cfg`; why `quad_gantry_level` is here not in `motion.cfg`) lives in the header so future readers don't have to relitigate it.

### 3.6 Include order rationale

Order: bottom-up — foundational/physical first, feature/logical later, user-facing/macros last. Klipper resolves cross-references after every file is loaded, so order is purely a readability choice. Two specifics worth calling out:

- `bed.cfg` (defines `[quad_gantry_level]`) is included **before** `eddy.cfg` (defines the `QUAD_GANTRY_LEVEL` gcode_macro wrapper). Klipper handles either order, but "define the section, then wrap it" reads top-to-bottom.
- `macros/_user_variables.cfg` stays first among macros — established convention from PR #62.

### 3.7 SAVE_CONFIG behavior

SAVE_CONFIG always writes to the file Klipper was started with (`printer.cfg`). Confirmed in `vendor/klipper/klippy/configfile.py:358`: `cfgname = self.printer.get_start_args()['config_file']`. The autosave block contains tuning for `[heater_bed]` (moved to `bed.cfg`), `[extruder]` (in `toolhead.cfg`), `[input_shaper]` (moved to `motion.cfg`), and two `[bed_mesh]` profiles (defined in `eddy.cfg`); Klipper merges the autosave values onto whichever section in the included files they belong to. No behavior change.

`_disallow_include_conflicts` (configfile.py:339) raises if an option is set in *both* the SAVE_CONFIG block and a regular include. Today, no section body in `printer.cfg` sets the autosaved options (PID for bed/extruder, shaper params, mesh points are all only in SAVE_CONFIG). Moving the section bodies to new files preserves this — none of the new files will declare any autosaved option, so no conflict.

## 4. Testing strategy

| Layer | Behavior for this PR | Action |
|---|---|---|
| **L1** pre-commit | Trailing whitespace / EOL hygiene | Automatic |
| **L2** macro_refcheck | No macro changes | Passes unchanged |
| **L3** klippy parse | Primary structural gate: parse `printer.cfg` with includes resolved, with 4 of 5 MCUs simulated (MMU stripped at CI time). Catches section-name collisions, missing sections, unsupported sensor types. | **Must pass before push** |
| **L4** pytest macro_refcheck | Tests for L2 | Unchanged |
| **L5** test_config_structure | `_cfg_files()` uses `rglob` — auto-picks-up new siblings. Deprecated-key scan, macro descriptions, `[extruder]` uniqueness checks all keep working. | No changes |
| **L6** post-deploy smoke | Runtime errors after `/deploy-to-pi` | Required post-deploy |
| **L7** snapshot diff | The behavior-preservation proof. Run `macro_behavior_diff.py before` on `origin/main`, then `after` on the worktree. Expected delta: zero non-whitespace, non-comment lines. | **Mandatory for this PR.** Exactly the use case L7 was built for. |

L3 + L7 are the load-bearing gates. L3 proves the config still parses; L7 proves the merged result is byte-equivalent.

## 5. Touch points outside `config/`

Six files. All small edits.

| File | Change | Notes |
|---|---|---|
| `.github/workflows/ci.yml` | Replace the literal file list in the `macro_refcheck against all .cfg files` step with `config/*.cfg config/macros/*.cfg config/mmu/base/*.cfg config/mmu/addons/*.cfg config/mmu/optional/*.cfg` | The current literal list has grown by hand; switching to a glob means the next split (if any) doesn't need a CI edit. |
| `tests/test_macro_refcheck.py` | Same glob substitution in the `test_real_repo_passes` fixture (line ~106) | Match CI exactly. |
| `CLAUDE.md` | Add the 4 new files to `## Repo layout`. Add the dual-axis (feature/MCU vs function) paragraph. | Macro inventory unchanged (no macros moved). |
| `tests/voron-2-611.test` | No change | Entry point is `CONFIG ../config/printer.cfg`; klippy follows includes. |
| `scripts/deploy_to_pi.sh` | No change | rsync source is `config/`; new files inherit the implicit include. Existing excludes (`/firmware/`, `/archive/`, `/printer.cfg`) are unaffected. |
| `scripts/macro_refcheck.py` | No change | Path constants live in the callers (CI + pytest), not the script. |

## 6. PR strategy

**One atomic PR.** Reasons:

- A partial split (e.g., motion-only first) leaves `printer.cfg` in an inconsistent intermediate state — half the sections moved, half still inline. Worse to read than either endpoint.
- The diff is mechanical: section-block moves with no edits inside the section bodies. L7 proves zero behavior change in one shot.
- Total surface: 4 file creations, 1 file shrunk, 2 file edits in CI/tests, 1 CLAUDE.md edit. Manageable in one review.

**Sequencing:** ship after PRs #59–#62 (all merged 2026-05-17) so the diff stays purely structural. ✓ already satisfied.

## 7. Anti-criteria

- No tuning value changes (defer to [#25](https://github.com/bjdeng/voron-2-611/issues/25)).
- 2-pass `QUAD_GANTRY_LEVEL` override in `eddy.cfg` not touched ([[qgl-two-pass-intentional]]).
- SAVE_CONFIG block stays in `printer.cfg`.
- No section additions, deletions, or renames.
- No edits to `eddy.cfg`, `toolhead.cfg`, `mainsail.cfg`, `timelapse.cfg`, `macros/*`, `mmu/*`.

## 8. Validation playbook (for the implementer)

Before pushing:

1. `make test-py` — L1, L2, L4, L5 pass locally on macOS.
2. `python scripts/macro_behavior_diff.py before` on `origin/main`; `python scripts/macro_behavior_diff.py after` on the worktree. `diff tests/snapshots/macro_behavior_{before,after}.txt` — expected delta: empty (or whitespace/path-noise only). This is the L7 proof of zero behavior change.
3. Push; CI runs L3 (klippy-smoke) automatically.

Post-merge:

4. `/deploy-to-pi`. The skill runs L6 (printer-smoke) on the Pi after sync; verify it returns green.
5. Spot-check on the printer: `G28`, `QUAD_GANTRY_LEVEL`, `BED_MESH_CALIBRATE`, then `RESTART`. All four should run as before.

## 9. References

- Issue: [#63](https://github.com/bjdeng/voron-2-611/issues/63)
- Audit: [`docs/superpowers/audits/2026-05-17-config-reorg-audit.md`](../audits/2026-05-17-config-reorg-audit.md) F2
- Audit umbrella issue: [#30](https://github.com/bjdeng/voron-2-611/issues/30)
- LDO multi-cfg guide: <https://docs.ldomotors.com/en/guides/klipper_multi_cfg_guide>
- Klippain layout (community reference): <https://github.com/Frix-x/klippain/tree/main/config>
- zellneralex V2.660 layout (community reference): <https://github.com/zellneralex/klipper_config>
- Klipper SAVE_CONFIG implementation: `vendor/klipper/klippy/configfile.py:346`
