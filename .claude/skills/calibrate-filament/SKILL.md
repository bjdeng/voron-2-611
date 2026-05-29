---
name: calibrate-filament
description: Use when dialing in a new spool or brand, recalibrating after a hardware swap (e.g. Galileo extruder), or when print quality suggests flow or PA drift. Triggered by "calibrate Inland PLA", "recalibrate this filament", "dial in a new spool", "/calibrate-filament", or "filament needs tuning".
---

## When to use

- New spool or brand being added to the printer for the first time.
- After the Galileo G2E extruder swap — PA values are extruder-dependent and were invalidated; flow may have shifted.
- Print quality signals: over/under-extrusion, stringing, poor layer adhesion, PA artifacts at corners.
- Periodic re-calibration when a filament's profile feels off after a long gap.

## The cascade

Cascade runs **temp (verify) → flow → Adaptive PA** for one filament at brand + material granularity (e.g. "Inland PLA"). Each step is labeled and resume-aware — re-running reads `memory/filaments/<brand>-<material>.md` and offers to skip already-complete steps or jump to a specific one. One filament at a time.

### Step 0 — `rotation_distance` (normally skipped)

`rotation_distance: 48.033` was calibrated by Ben at Galileo G2E bring-up and is sound. The skill marks it `rotation_distance_verified: galileo-bring-up` in the log and **skips this step by default**.

Optional manual re-check if Ben suspects drift:
1. Heat to print temp, mark filament 120 mm above extruder entrance.
2. `G1 E100 F60` (feed 100 mm).
3. Measure remaining distance to mark; compute `actual_extruded = 100 - remaining`.
4. `new_rotation_distance = current_rotation_distance * (actual_extruded / 100)`.

If re-check finds it off: **propose** the corrected value as a `config/motion.cfg` diff for review. Do NOT auto-apply. Ben takes the edit through the normal PR → `/deploy-to-pi` flow (this is a `[extruder]` change — requires **FIRMWARE_RESTART**).

### Step 1 — Temp (verify-first)

Default: confirm the profile's current `nozzle_temperature` still prints clean. The Dragon hotend is hotend/filament-driven and likely unchanged by the extruder swap — verification is usually a quick visual confirm.

If a full tower is needed:
1. Guide Ben to use OrcaSlicer's built-in temperature tower calibration.
2. Ben identifies the cleanest band.
3. Skill writes the result — **quit OrcaSlicer first** (the helper refuses if it detects OrcaSlicer running):

```sh
python scripts/orca_profile_edit.py --set nozzle_temperature=<T> --profile "Inland PLA"
python scripts/orca_profile_edit.py --set nozzle_temperature_initial_layer=<T_first> --profile "Inland PLA"
```

Verify with `--get` before and after to show the diff.

### Step 2 — Flow (objective, Klipper macro)

1. **Idle gate:** confirm `printer.print_stats.state == standby` via Moonraker before touching the printer. Never run flow cal during or immediately after a print.
2. Read the current flow ratio from the profile:
   ```sh
   python scripts/orca_profile_edit.py --get filament_flow_ratio --profile "Inland PLA"
   ```
3. Over SSH/Moonraker (same connection approach as `/deploy-to-pi` — `ssh pi@mainsailos.local`, Moonraker at `http://mainsailos.local:7125`), run the macro with the current ratio as seed:
   ```
   FLOW_MULTIPLIER_CALIBRATION EXTRUSION_MULTIPLIER=<current_ratio>
   ```
4. Ben prints the thin-wall test shell and measures the wall with calipers. Don't aim for a fixed number — the macro prints its own `THEORIC SHELL THICKNESS` (it depends on the perimeter count, default 2), and `COMPUTE_FLOW_MULTIPLIER` compares your measured value against that theoretical one to derive the new ratio. Just record what the calipers read.
5. Run the compute macro:
   ```
   COMPUTE_FLOW_MULTIPLIER MEASURED_THICKNESS=<caliper_reading>
   ```
6. Read the new ratio from the Moonraker gcode response (it prints the recommended multiplier).
7. **Quit OrcaSlicer first**, then write:
   ```sh
   python scripts/orca_profile_edit.py --set filament_flow_ratio=<new_ratio> --profile "Inland PLA"
   ```

### Step 3 — Adaptive PA

OrcaSlicer's Adaptive PA calibration builds a flow × acceleration grid model for the filament.

1. Guide Ben to run OrcaSlicer's Adaptive PA calibration (Calibration → Adaptive Pressure Advance).
2. Ben evaluates the printed grid and selects values in OrcaSlicer's calibration UI to build the PA model.
3. Skill captures the resulting measurements block (the JSON/text OrcaSlicer generates) into the history log.
4. **Guided paste** — the Adaptive PA model field is a structured blob that the helper does not edit directly. Guide Ben to:
   - Open the filament profile in OrcaSlicer's UI.
   - Paste the model into the Adaptive PA field.
   - Enable pressure advance (`enable_pressure_advance = 1`) and adaptive PA (`adaptive_pressure_advance = 1`).
   - Set the fallback/median PA value in the `pressure_advance` scalar (used when the adaptive model can't interpolate).

   The helper can write the `pressure_advance` scalar fallback (`--set pressure_advance=<value>`), but the adaptive-model paste must be done manually in the OrcaSlicer UI.

### Close-out

1. Skill updates (or creates) `memory/filaments/<brand>-<material>.md` — appends a new dated history entry with all results:
   - Temp: result + note.
   - Flow: old → new ratio + caliper measurement.
   - Adaptive PA: model summary / fallback value + observations.
   - Updates YAML frontmatter to reflect current state.
2. Skill reminds Ben to commit: `git add memory/filaments/ && git commit -m "chore(filaments): calibrate <brand> <material> <date>"`.
3. Skill does NOT commit or deploy on its own.

## How to run

```
/calibrate-filament
```

or say: `"calibrate Inland PLA"` / `"recalibrate this filament"` / `"dial in [brand] [material]"`.

To resume at a specific step: `"redo PA for Inland PLA"` / `"re-run flow for Inland PLA"`.

**Helper script interface** (`scripts/orca_profile_edit.py`):

| Flag | Purpose |
|---|---|
| `--find "<name>"` | Resolve the profile JSON path; errors on 0 or >1 matches |
| `--get <key> --profile "<name>"` | Print current value (or use `--file <path>`) |
| `--set <key>=<value> --profile "<name>"` | Write scalar; refuses if OrcaSlicer running (exit 3); atomic + `.bak` |

Exit codes: 0 success, 1 bad usage, 2 not found/key missing, 3 OrcaSlicer running, 4 write failed.

**OrcaSlicer must be quit** before any `--set` call — OrcaSlicer overwrites profile JSON on exit and would clobber the edit.

## What it does NOT do

- Never auto-commits changes to the repo.
- Never deploys to the Pi or restarts Klipper.
- Never edits the Adaptive PA model field directly — that is a guided manual paste in OrcaSlicer's UI.
- Does not touch `config/` files autonomously; a `rotation_distance` correction (rare) is proposed as a diff for Ben to take through PR → `/deploy-to-pi`.
- Does not calibrate more than one filament per invocation.
- Does not write to Spoolman or RFID (deferred to [#72](https://github.com/bjdeng/voron-2-611/issues/72)).

## Related

- Spec: `docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md`
- [#79](https://github.com/bjdeng/voron-2-611/issues/79) — parent issue (this is the v1 core; community-data + Spoolman legs deferred)
- [#72](https://github.com/bjdeng/voron-2-611/issues/72) — MMU spool tracking + Spoolman/RFID (log frontmatter field names are chosen to map onto its extra-fields later)
- `docs/slicer-templates/orcaslicer.md` — the manual workflow this skill operationalizes
- `memory/filaments/TEMPLATE.md` — per-filament log record template
- `.claude/skills/deploy-to-pi/SKILL.md` — connection patterns reused for Moonraker calls
- `.claude/skills/sync-from-pi/SKILL.md` — companion read-direction skill
