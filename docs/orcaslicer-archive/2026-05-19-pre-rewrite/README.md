# OrcaSlicer state archive — 2026-05-19, pre-rewrite

Snapshot of `~/Library/Application Support/OrcaSlicer/user/` taken on 2026-05-19, immediately before the comprehensive process-profile audit + filament-profile cascade fix described in [`docs/print-profiles.md`](../../print-profiles.md) and [`docs/slicer-templates/orcaslicer.md`](../../slicer-templates/orcaslicer.md).

## Why this exists

The audit replaces:
- 4 process profiles (Fast / Match SS / PLA / Copy) → 3 (Speed / Strength / Quality)
- 12 filament profiles with broken inheritance chains (`inherits: "Voron Generic X"` — a parent that no longer exists in OrcaSlicer system presets) → 6-7 corrected brand profiles with valid 2-level cascade (`Generic <Material> @System` → `<Brand> <Material>`)
- 1 machine profile with a known `machine_start_gcode` bug (line breaks orphaning `PURGE_VOLUMES=!purge_volumes!` from `MMU_START_SETUP` and `TOTAL_LAYER=[total_layer_count]` from `PRINT_START`) → fixed version with SBv2/G2E clearance numbers (65/36/140)

This archive is the rollback point. If anything in the new spec turns out wrong, drop these files back into `~/Library/Application Support/OrcaSlicer/user/default/` (and the cloud-sync dir back to `~/Library/Application Support/OrcaSlicer/user/3087889866/`).

## What's preserved

| Path | Notes |
|---|---|
| `machine/Voron v2.611.json` | The active machine profile. Has the line-break bug (search lines 4-5, 9-10 of `machine_start_gcode`). |
| `machine/Voron 2.4 350 0.4 nozzle - Copy.json` | Empty shell — slated for deletion |
| `process/0.20mm Standard @Voron - Fast.json` | The most-recently-used process (per `OrcaSlicer.conf` orca_presets) |
| `process/0.20mm Standard @Voron - Match SS.json` | SuperSlicer compatibility experiment — slated for deletion |
| `process/0.20mm Standard @Voron - PLA.json` | Material-specific process (wrong axis) — slated for deletion |
| `process/0.20mm Standard @Voron - Copy.json` | Accidental Save-As remnant — slated for deletion |
| `filament/*.json` | All 12 brand filament profiles. ABS/ASA variants have `chamber_temperature: 30` (wrong; should be 55 for the active chamber control loop). Several inherit from `Voron Generic X` which is a dead parent. |
| `cloud-sync-3087889866/` | OrcaSlicer cloud-sync directory with 4 duplicated ASA profiles (chamber_temperature: 60 — over the clamp). Slated for deletion. |

## How to restore (rollback)

```bash
# 1. Close OrcaSlicer
# 2. Restore files:
cp machine/*.json "$HOME/Library/Application Support/OrcaSlicer/user/default/machine/"
cp process/*.json "$HOME/Library/Application Support/OrcaSlicer/user/default/process/"
cp filament/*.json "$HOME/Library/Application Support/OrcaSlicer/user/default/filament/"
mkdir -p "$HOME/Library/Application Support/OrcaSlicer/user/3087889866"
cp -r cloud-sync-3087889866/* "$HOME/Library/Application Support/OrcaSlicer/user/3087889866/"
# 3. Reopen OrcaSlicer
```

## Pre-archive context (for posterity)

- OrcaSlicer.conf last-active machine: `Voron v2.611`
- OrcaSlicer.conf orca_presets shows recent activity on both `Voron v2.611` and `Voron 2.4 350 0.4 nozzle - Copy` — the audit consolidates onto the v2.611 profile only.
- Most-recent 3mf used: `Blob Lab_Zorble V1.3mf` with `printer_settings_id: Voron v2.611`, `print_settings_id: 0.20mm Standard @Voron`, filaments mix of user (Sunlu PLA, Inland PLA+, Sunlu PLA+) and system (Generic ABS @System).
- Pre-existing draft of `docs/print-profiles.md` from earlier in the audit session — the final spec supersedes the draft.
