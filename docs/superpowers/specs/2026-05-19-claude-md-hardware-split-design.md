# Reduce CLAUDE.md size by extracting hardware reference + apply quality updates

Closes the CLAUDE.md improvement loop initiated by `/claude-md-improver` on 2026-05-19.

## Problem

`CLAUDE.md` is 560 lines (~6-8k tokens), auto-loaded into every Claude Code session on this repo. The "context cost / token efficiency" framing identifies the hardware inventory (~140 lines), MCU USB serial column (~15 lines), and BOM-level part numbers as the cleanest candidates for extraction: they're foundational orientation, not session-state, and aren't load-bearing for the workflow/conventions/gotchas content that drives session behavior.

Separately, the `/claude-md-improver` audit found six concrete content gaps from today's MMU calibration + thermal drift work that should land in the (slimmed) CLAUDE.md.

## Design

### Guiding principle: single source of truth

Klipper config files ARE the canonical source for hardware specs (pin assignments, drive currents, kinematic constants, sensor types, USB serials). The current `CLAUDE.md` "Hardware inventory" largely *restates* those specs — duplication that drifts. The fix isn't to move the duplication to a new file; it's to **stop duplicating**. `CLAUDE.md` and the new `docs/hardware.md` should carry the **context that isn't in config** (history, provenance, the "why") and point at config files for the actual specs.

### Two coordinated changes, one commit

**Change 1: Replace `CLAUDE.md`'s "Hardware inventory" with a short "Build at a glance" block + a context-and-pointers `docs/hardware.md`.**

Remove from `CLAUDE.md`:
- Full "Hardware inventory" sub-sections (frame & motion BOM, toolhead BOM with Galileo G2E specifics, Dragon clone, BFB0524HH fan, bed BOM, chamber/bedfans BOM, display BOM, MMU hardware BOM, "additional temperature sensors" table).
- The MCU map's USB serial ID column (the table itself stays, but with Klipper-name + board + role only — serials are in `config/printer.cfg`'s `[mcu]` blocks already).
- Inline cross-references that are pure duplication of config-file content.

Add to (top of) `CLAUDE.md`:

```markdown
## Build at a glance

- V2.4 350 mm CoreXY, milled aluminum bed
- Stealthburner v2 + Galileo G2E (9:1 — explains `gear_ratio: 9:1`/`rotation_distance: 48.033`) + Dragon clone hotend
- BTT Eddy probe (native Klipper `[probe_eddy_current]`)
- ERCF v2 MMU, 6 gates, Filametrix toolhead cutter, Blobifier purge tower
- 5 USB-attached MCUs (no CAN): 2× SKR 1.4 (LPC1769), EBB SB v1.0, BTT Eddy, ERCF EASY-BRD
- 0.4 mm nozzle, 1.75 mm filament

Hardware history + non-obvious mods + community context: [`docs/hardware.md`](docs/hardware.md). Actual electrical specs (pins, drive currents, kinematic constants, USB serials) live in the `config/*.cfg` files — `docs/hardware.md` is the *why* layer, not a duplicate spec.
```

Create `docs/hardware.md` (~50-70 lines, NOT 160). Format: one-liners of "what's there + why it's there" + pointer at the config file holding the actual spec. Example shape:

```markdown
## Toolhead

- **Stealthburner v2** body, no SB LEDs installed (only the LCD neopixel chain — see [`config/display.cfg`](../config/display.cfg) `[neopixel lcd]`).
- **Galileo G2E extruder** (9:1) — community drop-in for SBv2. Explains the unusual `gear_ratio` + `rotation_distance: 48.033` in [`config/toolhead.cfg`](../config/toolhead.cfg).
- **Dragon clone hotend** — vendor unknown, behaves Dragon-compatible. Older variant with ~10-15mm longer heatbreak than HF — affects MMU toolhead distances (see [`docs/mmu-toolhead-calibration.md`](mmu-toolhead-calibration.md)).
- **Delta BFB0524HH part fan** — community upgrade from BOM Sunon MF50151VX-A99 (slightly weaker on paper, 4.6 vs 5.4 CFM, but better build / longer-rated / 24V-native). Slicer filament-cooling profiles tuned for this fan (see [`docs/slicer-templates/orcaslicer.md`](slicer-templates/orcaslicer.md)). Wired to [`config/toolhead.cfg`](../config/toolhead.cfg) `EBB:gpio4`.
```

Each line: what's there → why it's notable → where the spec/config lives. No restating of pin numbers, drive currents, or kinematic constants — those live in the cited config file.

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
├── CLAUDE.md                  # ~410 lines (down from 560)
└── docs/
    └── hardware.md            # ~50-70 lines (new — context only, not duplicate spec)
```

Net repo size *shrinks* (the previous duplication of config-file content goes away entirely). Spec values continue to live in `config/*.cfg` files — the canonical source they already were.

### Cross-reference policy

`CLAUDE.md`'s "Build at a glance" block ends with a pointer at `docs/hardware.md`. Each `docs/hardware.md` entry ends with a pointer at the relevant `config/*.cfg` file. Three-tier navigation: at-a-glance summary → context layer → canonical spec.

The Klipper-gotchas content in `CLAUDE.md` that *references* hardware specifics (e.g., "no CAN", "LPC1769 doesn't support `temperature_mcu`") keeps its hardware terms inline — those references are short, gotcha-relevant, and don't depend on the full hardware-doc context.

## Why not a skill

Considered making `docs/hardware.md` a `superpowers`-style auto-loading skill (Approach B in the brainstorming dialogue). Rejected because:

- Skill auto-loading is heuristic — a question like "the bed is acting weird" might not trip the trigger, leading to Claude answering without hardware context (silent failure mode).
- Hardware context is foundational orientation, not behavior. Skills are a better fit for the latter.
- The Read-on-demand pattern is more predictable for this content profile, and the repo already establishes the precedent (`docs/mmu-toolhead-calibration.md`, `docs/slicer-templates/`).

## Trade-offs

| Aspect | Win | Cost |
|---|---|---|
| Token cost per session | ~2.5-3k tokens saved (no duplication loaded by default) | First hardware-detail question pays one `Read` round-trip; deep spec questions sometimes need 2 reads (hardware.md → config file) |
| Drift risk | Eliminated — config is the only source for spec values; `docs/hardware.md` carries only un-duplicable context | A future maintainer could re-introduce duplication if not careful (out of band documentation discipline) |
| Discoverability | "Build at a glance" + explicit two-step pointer chain | Slight indirection for newcomer Claude sessions |
| Maintenance | Hardware changes mean editing config + a one-line context note (if any). Today's pattern requires editing config + restating in CLAUDE.md | None — strictly easier to maintain than the duplicating status quo |

## Acceptance criteria

- `CLAUDE.md` final line count is 400-430.
- `docs/hardware.md` exists and is 50-80 lines.
- **No duplication**: every spec value (pin, drive current, kinematic constant, USB serial) that appears in `docs/hardware.md` also appears in a `config/*.cfg` file — but `docs/hardware.md` itself carries no spec values, only context with pointers.
- The "Build at a glance" block accurately summarizes the build in ≤8 lines.
- The six quality updates from `/claude-md-improver` land in their respective sections inside the slimmed `CLAUDE.md`.
- Pre-commit hooks pass.
- No CI changes needed (CLAUDE.md and docs/ are on the docs-only no-op lane).

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
