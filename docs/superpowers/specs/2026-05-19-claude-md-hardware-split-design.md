# Reduce CLAUDE.md size by extracting hardware reference + apply quality updates

Closes the CLAUDE.md improvement loop initiated by `/claude-md-improver` on 2026-05-19.

## Problem

`CLAUDE.md` is 560 lines (~6-8k tokens), auto-loaded into every Claude Code session on this repo. The "context cost / token efficiency" framing identifies the hardware inventory (~140 lines), MCU USB serial column (~15 lines), and BOM-level part numbers as the cleanest candidates for extraction: they're foundational orientation, not session-state, and aren't load-bearing for the workflow/conventions/gotchas content that drives session behavior.

Separately, the `/claude-md-improver` audit found six concrete content gaps from today's MMU calibration + thermal drift work that should land in the (slimmed) CLAUDE.md.

## Design

### Two coordinated changes, one commit

**Change 1: Extract reference-grade hardware content to `docs/hardware.md`.**

Move out of `CLAUDE.md`:
- Full "Hardware inventory" sub-sections — frame & motion BOM, toolhead BOM (Galileo G2E specifics, Dragon clone, BFB0524HH fan), bed BOM, chamber/bedfans BOM, display BOM, MMU hardware BOM, full "additional temperature sensors" table.
- The MCU map's USB serial ID column (the rest of the table — Klipper name, board, MCU, role — stays in `CLAUDE.md`).
- Vendor / submodules table's "Pin" column (keep the table itself in `CLAUDE.md` — it's small and frequently consulted when bumping).

Add to (top of) `CLAUDE.md`:

```markdown
## Build at a glance

- V2.4 350 mm CoreXY, milled aluminum bed
- Stealthburner v2 + Galileo G2E (9:1 — explains `gear_ratio: 9:1`/`rotation_distance: 48.033`) + Dragon clone hotend
- BTT Eddy probe (native Klipper `[probe_eddy_current]`)
- ERCF v2 MMU, 6 gates, Filametrix toolhead cutter, Blobifier purge tower
- 5 USB-attached MCUs (no CAN): 2× SKR 1.4 (LPC1769), EBB SB v1.0, BTT Eddy, ERCF EASY-BRD
- 0.4 mm nozzle, 1.75 mm filament

Full BOM-level detail in [`docs/hardware.md`](docs/hardware.md). Vendor part numbers, fan models, thermistor pullups, MCU USB serial IDs all live there.
```

Keep in `CLAUDE.md` (where they currently live):
- Printer identity (V2.611 callout) — only 15 lines, frequently relevant to orient.
- "Macro inventory" — intertwined with hardware behaviors; extracting would degrade readability.
- "Tuning record" — small, frequently consulted, often updated alongside calibration work.
- All "Known quirks" + "Klipper gotchas".
- All workflow / testing / vendor-bump procedure content.

**Change 2: Apply the six `/claude-md-improver` quality updates** (described in detail in the audit dialogue):

1. Update tuning-record row to current `tap_threshold = 2711.866` + `calibration_temp = 57.92 °C` + note about the rollback.
2. New Klipper-gotchas bullet on native tap detection's lack of signal filtering vs eddy-ng's Butterworth band-pass — explains why `TEMPERATURE_PROBE_CALIBRATE` is a hard prerequisite.
3. New Klipper-gotchas bullet on HH toolhead params not persisting via `SAVE_CONFIG` (manual `mmu_parameters.cfg` edit required).
4. New Klipper-gotchas bullet on `MMU_CALIBRATE_TOOLHEAD` requiring extruder ≤ 70 °C.
5. New Known-quirks bullet on `mmu_parameters.cfg` NOT being a Pi-side symlink (unique exception among `mmu/base/*.cfg`).
6. New Known-quirks bullet on BLOBIFIER requiring `QUAD_GANTRY_LEVEL` first + the 30 mm extrude gotcha (use `BLOBIFIER PURGE_LENGTH=200` instead).

All six land inside their respective existing sections — no new structural headings.

### File layout after the change

```
voron-2-611/
├── CLAUDE.md                  # 410 lines (down from 560)
└── docs/
    └── hardware.md            # ~160 lines (new)
```

### Cross-reference policy

`CLAUDE.md`'s "Build at a glance" block ends with a pointer at `docs/hardware.md`. No other cross-links — when Claude needs deep BOM detail, it reads the file via the standard Read tool. Same pattern the repo already uses for `docs/mmu-toolhead-calibration.md` and `docs/slicer-templates/`.

The Klipper-gotchas content that *references* hardware specifics (e.g., "no CAN", "LPC1769 doesn't support `temperature_mcu`") keeps its hardware terms inline — those references are short, gotcha-relevant, and don't require the full BOM context.

## Why not a skill

Considered making `docs/hardware.md` a `superpowers`-style auto-loading skill (Approach B in the brainstorming dialogue). Rejected because:

- Skill auto-loading is heuristic — a question like "the bed is acting weird" might not trip the trigger, leading to Claude answering without hardware context (silent failure mode).
- Hardware reference is foundational orientation, not behavior. Skills are a better fit for the latter.
- The Read-on-demand pattern is more predictable for this content profile, and the repo already establishes the precedent.

## Trade-offs

| Aspect | Win | Cost |
|---|---|---|
| Token cost per session | ~2.5-3k tokens saved | First hardware-detail question pays one `Read` round-trip |
| Maintenance | Same total content, better organized | Two files to edit instead of one when hardware changes |
| Discoverability | "Build at a glance" + explicit cross-link | Slight indirection for newcomer Claude sessions |
| Risk of silent failure | Lower than skill auto-load (Read is explicit) | Non-zero — a session could miss the cross-link |

## Acceptance criteria

- `CLAUDE.md` final line count is 400-430.
- `docs/hardware.md` exists and contains all extracted BOM content.
- No content is lost — every fact in the current "Hardware inventory" / MCU map USB column / Vendor table pins survives in one of the two files.
- The "Build at a glance" block accurately summarizes the build in ≤8 lines.
- The six quality updates land in their respective sections inside the slimmed `CLAUDE.md`.
- Pre-commit hooks pass.
- No CI changes needed (CLAUDE.md is on the docs-only no-op lane).

## Out of scope (explicitly NOT in this change)

- Trimming verbose phrasing in the sections that stay (Approach C from brainstorming — could be a later pass, not bundled here).
- Moving `Macro inventory` out of `CLAUDE.md` (rejected: too intertwined with hardware behaviors).
- Moving `Tuning record` out (rejected: small + frequently updated).
- Auto-load skill packaging (rejected: see "Why not a skill").
- Updating `.claude/skills/deploy-to-pi/SKILL.md` or any other skill content (none reference hardware deeply enough to matter).

## References

- `/claude-md-improver` quality report dialogue from 2026-05-19 session
- Prior CLAUDE.md updates from today: commits [1b1fd0d](https://github.com/bjdeng/voron-2-611/commit/1b1fd0d), [9083390](https://github.com/bjdeng/voron-2-611/commit/9083390), [0e48365](https://github.com/bjdeng/voron-2-611/commit/0e48365)
- Related: [#25](https://github.com/bjdeng/voron-2-611/issues/25) — the drift cal work that the new Klipper-gotchas bullet documents.
