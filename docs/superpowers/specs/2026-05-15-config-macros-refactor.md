# Klipper config + macros refactor

**Status:** draft, awaiting approval
**Date:** 2026-05-15
**Branch (when implementation starts):** TBD (after `feat/eddy-native` merges to `main`)
**Skill chain:** `superpowers:brainstorming` → `superpowers:writing-plans` (next)

---

## 1. Goal

Make the Klipper config and macros for voron-2-611 maintainable for the next several years — readable, tunable, internally consistent, and aligned with Klipper + Happy Hare canonical practice.

## 2. Scope

### In scope (6 PRs, after Eddy native ships)

1. **Tier-1 config fixes** — `test_speed.cfg` swap to current Ellis upstream (Klipper v0.13 compat), `[resonance_tester] probe_points: 175, 175, 20`.
2. **Mainsail/HH cleanup (Option B) + archive/dead-code cleanup** — strip PAUSE/RESUME/CANCEL_PRINT/SET_PAUSE_*/SET_PRINT_STATS_INFO from `config/mainsail.cfg`; delete dead `SET_ACTIVE_SPOOL`/`CLEAR_ACTIVE_SPOOL` from `config/macros/macros.cfg`; remove commented-out blocks throughout.
3. **CLAUDE.md corrections + Open Investigations → GH Issues migration** — Filametrix (not EREC), SB LEDs not installed, Eddy native migrated, addon list trimmed, missing temp sensors documented, `[update_manager]` block list updated, bed_mesh max-y typo fixed, PRINT_START/PRINT_END inventory corrected. Each Open Investigation becomes a GH Issue under `future-work` label; CLAUDE.md section slims to a one-line pointer.
4. **Macros refactor + file reorg** — new `config/macros/_user_variables.cfg` with single `_USER_VARIABLE` macro for tunables; rename `btt-ebb-sb-usb-v1.0.cfg` → `toolhead.cfg` (done in PR-A); `description:` field on every macro; consolidate `[extruder]` PA + limits into `toolhead.cfg`; resolve duplicate section declarations; reorganize `[include]` order in `printer.cfg` with section comments. No macro behavior change.
5. **OrcaSlicer-side hooks + PRINT_START harmonization** — document slicer-side `MMU_START_SETUP / MMU_START_CHECK / PRINT_START / MMU_START_LOAD_INITIAL_TOOL` 4-call pattern (lives at `docs/slicer-templates/`); update PRINT_START to consume the same params it already uses (no new params required, MMU info flows through `MMU_START_SETUP`).
6. **Two skills** — `.claude/skills/klipper-config-work/SKILL.md` and `.claude/skills/happy-hare-integration/SKILL.md`.

### Folded into the in-flight `feat/eddy-native` branch (not this spec)

These items are coupled to the Eddy native migration and land with it (or as an immediate follow-up PR) before this spec's PRs start:

- `[bed_mesh] fade_target: 0`
- `[bed_mesh] zero_reference_position: 175, 175`
- **`[temperature_probe btt_eddy]`** — native Klipper feature; thermistor is already wired (`config/eddy.cfg:23-25`). Drift compensation for QGL (which uses default probing, not tap). Replaces the prior `[temperature_sensor btt_eddy]` (same hardware pin).
- **Doc-blessed split-macro pattern for tap-Z application** (`SET_Z_FROM_PROBE` + `_RELOAD_Z_OFFSET_FROM_PROBE` in `config/eddy.cfg`) replaces an inline `PROBE METHOD=tap` + `SET_KINEMATIC_POSITION Z={...last_z_result}` pair in `PRINT_START`. The inline pair was a real bug: Klipper renders each macro template ONCE at invocation, so `{...last_z_result}` substituted before `PROBE` ran. The split-macro approach is the canonical pattern from `vendor/klipper/docs/Eddy_Probe.md:379-389`.

**Not folded in (deferred to GH `future-work` issues):**

- **`[homing_override]` for Z post-G28** — the doc-blessed *automation* layer (per `vendor/klipper/docs/Eddy_Probe.md:398-400`) so `SET_Z_FROM_PROBE` runs on every `G28 Z`, not just at print start. The split-macro fix above is sufficient for `PRINT_START`'s safety; `[homing_override]` is a "nice to have" that adds behavior across all G28 contexts. Deferred to a separate small PR after Eddy calibration verifies the macro pattern works.
- **`[temperature_sensor]` for SKR 1.4 MCU die temps** — **infeasible**. Klipper's `temperature_mcu` doesn't support LPC1769 (per `vendor/klipper/klippy/extras/temperature_mcu.py` supported-MCU list: rp2, sam3/4, samd21/51, stm32f/g/l/h7). Filed as a permanent limitation.

### Out of scope (tracked as GH Issues with `future-work` label)

The current "Open Investigations" section of CLAUDE.md migrates to GH Issues during Phase 3. Each numbered item becomes its own issue. Plus three new ones:

- Re-tune session (input shaper, PID, PA, Eddy calibration) — existing Open Investigation #4.
- Microsteps 128 → 64 deliberate test — existing Open Investigation #3.
- Sensorless X feasibility — existing Open Investigation #2.
- OrcaSlicer print-profile tuning — new.
- Webcam re-enable — existing Open Investigation #6.
- moonraker-timelapse removal — existing Open Investigation #5.
- CI klippy-smoke re-enable — existing Open Investigation #7 (becomes a sub-task of the Eddy migration close-out).
- Automated Pi deploy on merge — existing Open Investigation #8.
- `[temperature_probe btt_eddy]` re-evaluation (Eddy spec declined; revisit after 4-6 weeks of native-Eddy data).
- klippain-shaketune install for belt-comparison diagnostics.
- Z-axis input shaping (rolls into the re-tune session above).
- Logical reorganization of macro/config content (open-ended — audit after a quarter of living with `_USER_VARIABLE`).
- Better PA / Flow calibration macros (survey current community options vs. Frix-x v1.2/v1.6 currently in use).
- Webcam-feedback-driven auto-calibration of flow/PA/temp (substantial future project).

## 3. Constraints

- Each PR ≤ ~600 lines diff where possible (Phase 4 is the largest).
- All Klipper config changes must pass the existing CI (`klippy parse + macro_refcheck + smoke gcode + pytest`) plus the new Layer 5 structural assertions added in this spec.
- No changes to `mmu/base/*.cfg` (HH-owned, symlinked on Pi).
- No changes to `vendor/**`.
- `mmu/addons/*.cfg` files stay in place (not moved to archive) — they're likely symlinks on the Pi and would be recreated by next HH install.

## 4. Phases

After the in-flight `feat/eddy-native` branch merges to `main`, implementation proceeds in 6 phases. Each phase is one PR. Order is "small/safe first":

### Phase 1 — Tier-1 config fixes (~30 line diff)

- Replace `config/macros/test_speed.cfg` with current upstream from [AndrewEllis93/Print-Tuning-Guide](https://github.com/AndrewEllis93/Print-Tuning-Guide) `macros/TEST_SPEED.cfg`. Current copy will fail at runtime on Klipper v0.13 (uses removed `max_accel_to_decel`).
- Change `[resonance_tester] probe_points` in `config/toolhead.cfg:21` from `100, 100, 20` to `175, 175, 20`.

### Phase 2 — Mainsail/HH cleanup (Option B) + archive cleanup (~80 line diff)

- Strip from `config/mainsail.cfg`: `[gcode_macro PAUSE]`, `[gcode_macro RESUME]`, `[gcode_macro CANCEL_PRINT]`, `[gcode_macro SET_PAUSE_NEXT_LAYER]`, `[gcode_macro SET_PAUSE_AT_LAYER]`, `[gcode_macro SET_PRINT_STATS_INFO]`.
- Keep in `config/mainsail.cfg`: `[virtual_sdcard]`, `[pause_resume]`, `[display_status]`, `[respond]`, `_TOOLHEAD_PARK_PAUSE_CANCEL`, `_CLIENT_EXTRUDE`, `_CLIENT_RETRACT`, `_CLIENT_LINEAR_MOVE`.
- Delete `SET_ACTIVE_SPOOL` and `CLEAR_ACTIVE_SPOOL` from `config/macros/macros.cfg` (HH owns Spoolman activation via `spoolman_support: push`).
- Remove commented-out blocks: `print_start.cfg:20`, `print_start.cfg:32-36, 43-47, 51, 58-62, 76-81`; `macros.cfg:172-181, 199`; `lcd_tweaks.cfg:87-91`; `printer.cfg:332`.
- Save the Mainsail/HH divergence rationale to `memory/decisions.md`.

### Phase 3 — CLAUDE.md corrections + Open Investigations migration + test pyramid enshrining (~80 line diff, docs-only)

- **Fix factual errors** in CLAUDE.md:
  - "EREC (toolhead filament cutter)" → **Filametrix** ([Carrot-collective/Filametrix](https://github.com/Carrot-collective/Filametrix)).
  - "Stealthburner v2 body" — clarify "no SB LEDs wired."
  - "BTT Eddy running vvuk/eddy-ng" → "BTT Eddy on native `[probe_eddy_current]`" (after Eddy migration ships).
  - "Add-ons enabled: …EREC…, mmu_eject_buttons" → just Blobifier (the others are present but not included).
  - "PRINT_START calls PROBE_EDDY_NG_TAP" → "calls PROBE METHOD=tap"; remove "PRINT_END resets Eddy tap offset" claim.
  - "Bed mesh `default` 9×9 (15, 21.42) → (335, 335)" → fix to actual values.
  - Add: `[temperature_sensor btt_eddy]` (Generic 3950 NTC on `eddy:gpio26`); `[temperature_sensor EBB_NTC]`; full `[update_manager]` block list (mainsail, mainsail-config, crowsnest, sonar, happy-hare in addition to the noted timelapse).
- **Migrate Open Investigations to GH Issues:**
  - Create `future-work` GH label.
  - File one issue per current Open Investigation (8 items), each linking back to the relevant CLAUDE.md context.
  - Replace the CLAUDE.md `## Open investigations` section with a one-line pointer: "Tracked as GitHub Issues with the `future-work` label: <link>". Keep the "Recently resolved" sub-section as a historical log.
  - Add the new "out of scope" items from Section 2 as additional issues (`[temperature_probe]` revisit, shaketune install, Z-axis shaping, logical reorganization audit, PA/Flow macro survey, webcam-feedback auto-calibration).
- **Enshrine the test pyramid in CLAUDE.md:** expand the existing `## CI checks` section into a full `## Testing` section that documents the 6+1 test pyramid layers, what each catches, when to extend, how to run locally. The spec's Section 5 stays the source of truth for rationale; CLAUDE.md's section is the contributor-facing summary.

### Phase 4 — Macros refactor + file reorg (~400-600 line diff — the largest)

> **Note:** Phase 4 implementation moved to [`2026-05-16-phase4-macros-refactor-design.md`](2026-05-16-phase4-macros-refactor-design.md) and split into PR-A (structural) + PR-B (`_USER_VARIABLE` migration).

- **Rename `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`** (and update references in `config/printer.cfg`, `tests/voron-2-611.test`, `scripts/macro_refcheck.py`, CLAUDE.md, this spec).
- **Add `config/macros/_user_variables.cfg`** with a single `[gcode_macro _USER_VARIABLE]` block. Variables grouped by category:
  - Park positions (`park_center`, `park_front`, `park_front_low`, `park_rear`, `park_bed`, `park_print_end`), park speeds (`park_speed_xy`, `park_speed_z`), park z-hop default (`park_zhop`).
  - Heatsoak / chamber wait (`heatsoak_bed_temp_threshold`, `heatsoak_default_minutes`).
  - BedFans (`bedfans_threshold`, `bedfans_fast`, `bedfans_slow`).
  - Print sequence pacing (`print_end_cooldown_seconds`, `m109_tolerance_celsius`).
  - Idle timeout (`idle_timeout_minutes`).
  - Empty `gcode:` block (variables only — no body).
- **Migrate each macro that uses a hardcoded tunable** to read from `_USER_VARIABLE` via `{% set uv = printer["gcode_macro _USER_VARIABLE"] %}` at the top. Values copied verbatim from current usage; no value changes.
- **Delete `_BEDFANVARS`** in `bedfans.cfg`; roll its three variables into `_USER_VARIABLE`.
- **Add `description:` field** to every `[gcode_macro]` lacking one.
- **Consolidate `[extruder]`** PA + temp limits into `config/toolhead.cfg` (extruder lives in one file, not split with `printer.cfg`).
- **Resolve duplicate section declarations** (`[exclude_object]`, `[respond]`, `[display_status]`, `[pause_resume]`) — one canonical home each. Per `defer-to-happy-hare`, prefer HH's version where overlap exists.
- **Reorganize `[include]` order in `printer.cfg`** into logical groups with section-header comments (MCU configs → Probe + bed leveling → User tunables → MMU → core printer config → Client + macros).

### Phase 5 — OrcaSlicer hooks + PRINT_START harmonization (~100 line diff)

- **Pull a recent gcode file from the Pi** (`scp pi@mainsailos.local:~/printer_data/gcodes/<recent>.gcode /tmp/`) and read head/tail to document the current slicer-emitted start/end gcode.
- **Add `docs/slicer-templates/`** with:
  - `orcaslicer-start.gcode` — target Machine Start G-code template (4-call sequence: `MMU_START_SETUP` → `MMU_START_CHECK` → `PRINT_START` → `MMU_START_LOAD_INITIAL_TOOL`).
  - `orcaslicer-end.gcode` — `PRINT_END` + `MMU_END`.
  - `README.md` — explains the templates are documentation only (manually copied into OrcaSlicer printer profile); also documents the layer-change one-liner `SET_PRINT_STATS_INFO CURRENT_LAYER={layer_num} TOTAL_LAYER={total_layer_count}`.
- **Update `config/macros/print_start.cfg`** if needed for param-handling robustness (e.g., add `|default()` to every `params.*` access). PRINT_START does not need new params — MMU info flows through `MMU_START_SETUP` and HH stores it on `printer.mmu.slicer_tool_map`.

### Phase 6 — Two skills (~250 line diff, `.claude/`-only)

- **`.claude/skills/klipper-config-work/SKILL.md`** (~120 lines) — doc-path index, RESTART vs FIRMWARE_RESTART decision table, three classes of file, "investigate before changing" mantra, "before changing X, grep Y" mini-map.
- **`.claude/skills/happy-hare-integration/SKILL.md`** (~150 lines) — print lifecycle hooks table, user-extension variables, slicer-side macros, cut-tip flow end-to-end (Filametrix path), the defer-to-HH rule.

Neither skill encodes specific Klipper feature flags or HH version-specific notes — both point at canonical `vendor/` paths and the HH wiki.

## 5. Test pyramid

Six layers applied to every PR, plus one layer specifically for Phase 4. Existing layers (1-4) stay as-is.

| Layer | Description | Per-PR | Where it lives |
|---|---|---|---|
| 1 | Pre-commit hooks (trailing whitespace, ruff, etc.) | every | `.pre-commit-config.yaml` |
| 2 | `macro_refcheck.py` — static gcode-command resolution | every | `scripts/macro_refcheck.py` + `tests/builtins.txt` |
| 3 | Klippy parse + smoke gcode (`test_klippy.py`) | every (non-docs) | `tests/voron-2-611.test` + `.github/workflows/ci.yml` |
| 4 | pytest — unit tests for scripts | every | `tests/test_*.py` |
| 5 (NEW) | Structural assertions on `.cfg` files | every | `tests/test_config_structure.py` (new) |
| 6 (NEW) | Post-deploy smoke (Pi-side) | every (manual, after deploy) | `scripts/deploy_to_pi.sh --smoke` flag + `scripts/printer-smoke.sh` on Pi |
| 7 (NEW, one-shot) | Behavior diff (before/after) | Phase 4 only | `scripts/macro_behavior_diff.py` + `tests/snapshots/` |

**Layer 5 assertions:**

- Every `_USER_VARIABLE.<name>` reference in any `[gcode_macro]` body has a corresponding `variable_<name>:` in `_user_variables.cfg`.
- Every `variable_<name>:` in `_user_variables.cfg` is actually referenced somewhere.
- Every `[gcode_macro]` has a non-empty `description:` field.
- No `.cfg` uses removed Klipper keys (`max_accel_to_decel`, `ACCEL_TO_DECEL`).
- `PAUSE` / `RESUME` / `CANCEL_PRINT` defined exactly once across all included `.cfg` files.
- `printer.cfg` `[include …]` lines appear in the expected section order (declared in test).
- Every `[gcode_macro]` using `params.X` either calls `params.X|default(...)` or guards with `params.X is defined`.

**Layer 6 implementation:**

`scripts/deploy_to_pi.sh --smoke` (default on after successful deploy). After Pi reports `printer.state == "ready"`:

```sh
ssh pi@mainsailos.local /home/pi/printer_data/printer-smoke.sh
```

`scripts/printer-smoke.sh` (new, deployed to Pi):

1. POST to Moonraker `printer.gcode.script`: `G28`, `PARKCENTER`, `OFF`, `_RESETSPEEDS`. (Originally included `QUERY_PROBE` — dropped 2026-05-16 because native `[probe_eddy_current]` doesn't implement it; G28 already exercises the probe end-to-end.)
2. After each command, `grep` `~/printer_data/logs/klippy.log` for `^!! ` (Klipper's runtime-error prefix).
3. Exit non-zero on any error.

**Layer 7 (Phase 4 only):**

Before refactor + after refactor:

1. For a fixed set of macro invocations (`PARKCENTER`, `HEATSOAK BED_TEMP=110 EXTRUDER_TEMP=240`, `PRINT_START EXTRUDER=240 BED=110 CHAMBER=45`, `OFF`, `PRINT_END`), dump expanded gcode using `test_klippy.py` and capture dispatcher output.
2. Save to `tests/snapshots/macro_behavior_<before|after>.txt`.
3. Diff. Acceptable: comments/whitespace only. Anything else requires explicit justification in PR description.

**Not covered by any layer (acknowledged):**

- Conditional branches inside jinja2 (mitigated by Layer 6 + Layer 7 for Phase 4).
- Print quality / mechanical regression (manual first-print test after each deploy).
- Slicer-side template errors (those live in OrcaSlicer, not in this repo).

## 6. Target file tree (post-Phase 4)

```
config/
├── printer.cfg                       # reorganized [include] order with section comments
├── eddy.cfg                          # unchanged except Phase 0 fade_target + zero_reference_position
├── toolhead.cfg                      # RENAMED from btt-ebb-sb-usb-v1.0.cfg; now contains [extruder] PA + limits too
├── mainsail.cfg                      # SLIMMED: [virtual_sdcard], [pause_resume], [display_status], [respond], helpers only
├── moonraker.conf
├── crowsnest.conf
├── sonar.conf
├── macros/
│   ├── _user_variables.cfg           # NEW: single [gcode_macro _USER_VARIABLE]
│   ├── macros.cfg                    # SET_ACTIVE_SPOOL/CLEAR_ACTIVE_SPOOL deleted; comment-cleaned
│   ├── print_start.cfg               # comment-cleaned; reads from _USER_VARIABLE
│   ├── bedfans.cfg                   # _BEDFANVARS rolled into _USER_VARIABLE
│   ├── lcd_tweaks.cfg                # duplicate progress_text removed
│   ├── test_speed.cfg                # REPLACED with current upstream Ellis
│   ├── calibrate_flow.cfg            # unchanged (Frix-x v1.6, still current)
│   └── calibrate_pa.cfg              # unchanged (Frix-x v1.2, still current)
├── mmu/                              # untouched (HH-owned)
├── archive/                          # unchanged (klicky/ + z_calibration.cfg stay)
└── firmware/                         # unchanged
docs/
└── slicer-templates/                 # NEW
    ├── README.md
    ├── orcaslicer-start.gcode
    └── orcaslicer-end.gcode
.claude/
└── skills/
    ├── klipper-config-work/
    │   └── SKILL.md                  # NEW
    └── happy-hare-integration/
        └── SKILL.md                  # NEW
tests/
├── test_config_structure.py          # NEW (Layer 5)
├── snapshots/                        # NEW (Layer 7, Phase 4 only)
│   ├── macro_behavior_before.txt
│   └── macro_behavior_after.txt
└── (existing files unchanged)
scripts/
├── deploy_to_pi.sh                   # add --smoke flag (Layer 6)
├── macro_behavior_diff.py            # NEW (Layer 7)
└── (existing files unchanged)
```

Pi-side new file (not in repo):
- `~/printer_data/printer-smoke.sh` — deployed via `deploy_to_pi.sh`.

## 7. Implementation notes per phase

### Phase 4 — design considerations

- **Migration is mechanical and reviewable per-macro.** Each commit within Phase 4 touches one macro file at a time, replacing hardcoded values with `_USER_VARIABLE.X` references and adding the new `variable_X:` to `_user_variables.cfg`.
- **Behavior preserved.** Values copied verbatim. Layer 7 (behavior diff) catches any accidental semantic change before merge.
- **Include order matters for documentation, not function.** Klipper resolves `printer["gcode_macro _USER_VARIABLE"].foo` at macro-call time. So `_user_variables.cfg` can technically be included anywhere; we put it early in `printer.cfg` so a reader sees it before the macros that reference it.
- **The 2-pass QGL override stays as-is.** Per [[qgl-two-pass-intentional]], the saggy-rear V2 quirk makes this load-bearing. Documented in the macro's `description:` field as part of Phase 4.
- **Filename rename touches a few non-config files:**
  - `config/printer.cfg` — the `[include toolhead.cfg]` line.
  - `tests/voron-2-611.test` — any path references.
  - `scripts/macro_refcheck.py` — any path constants.
  - `CLAUDE.md` — hardware section + macro section + ## CI checks section.
  - This spec (self-reference) — updated as part of the same PR.

### Phase 5 — slicer-side caveats

- **The `.gcode` templates in `docs/slicer-templates/` are documentation, not code.** They cannot auto-deploy; OrcaSlicer reads its templates from the printer profile inside the application. Update the printer profile manually after merging.
- **`{…}` tokens** are resolved by OrcaSlicer at slice time (placeholders for its own variables).
- **`!…!` tokens** (e.g., `!referenced_tools!`) are resolved by Moonraker's `[mmu_server]` at file-upload time (per `vendor/happy-hare/components/mmu_server.py`).
- A non-MMU slicer profile would simply omit the three `MMU_*` calls; `PRINT_START` works unchanged.
- During implementation, the head/tail of a recent gcode file confirms current OrcaSlicer template state. Differences from target → PR description includes manual-update instructions.

### Phase 6 — skill maintenance

- Both skills point at `vendor/` paths and the HH wiki for canonical detail. When `vendor/klipper` or `vendor/happy-hare` bumps, the skill text should not need changes — only the linked content updates.
- Skills are non-prescriptive about specific feature recommendations. Those go in `memory/` (e.g., `[[qgl-two-pass-intentional]]`, `[[defer-to-happy-hare]]`).

## 8. Rollback procedure

Each PR is independent and revertible. Per-PR rollback:

| Phase | Rollback |
|---|---|
| 1 | `git revert <sha>` — config-only; no Pi-side state change beyond reverting deploy. |
| 2 | Same — Mainsail PAUSE/RESUME definitions restored if rolled back; HH definitions take over again. Net: same as today. |
| 3 | Docs-only; trivial to revert. GH Issues stay open (just close-and-recreate if reverting). |
| 4 | `git revert <sha>` — restores all hardcoded tunables. Layer 7 snapshot diff is the safety net here. |
| 5 | Klipper-side: `git revert <sha>`. Slicer-side: revert manual edit to OrcaSlicer printer profile (user action). |
| 6 | `.claude/skills/` deletion; no runtime impact. |

No destructive Pi operations. `~/eddy-ng/` already removed by the Eddy migration. `~/Happy-Hare/` untouched.

## 9. Deferred items (not in this spec)

Tracked as GH Issues with `future-work` label after Phase 3:

- **Re-tune session, anchored on klippain-shaketune** — install [klippain-shaketune](https://github.com/Frix-x/klippain-shaketune) (v6.0+, standalone install, not full Klippain). Run shaketune's `COMPARE_BELTS_RESPONSES` for belt-tension diagnostics (V2 saggy-rear); rebuild X/Y shaper calibration via shaketune's flow; verify shaketune covers Z-axis shaping (`accel_chip_z: lis2dw` + `shaper_type_z`) — if it does, that supersedes a standalone Z-shaper rebuild; if it doesn't, run native `SHAPER_CALIBRATE` for Z separately. Also in this session: PID re-tune, pressure advance, Eddy native calibration verification.
- Microsteps re-evaluation (128 → 64 deliberate test).
- Sensorless X feasibility.
- OrcaSlicer print-profile tuning.
- Webcam re-enable.
- moonraker-timelapse removal.
- Logical reorganization audit (after living with `_USER_VARIABLE` for a quarter).
- Better PA / Flow calibration macros (survey of community options vs. current Frix-x v1.2/v1.6).
- Webcam-feedback-driven auto-calibration (flow / PA / temp from camera observation of test prints).

## 10. References

- `vendor/klipper/docs/Command_Templates.md` — jinja2 macro idioms, `printer.*` accessors.
- `vendor/klipper/docs/Eddy_Probe.md` — probing-method semantics, tap workflow.
- `vendor/klipper/docs/Bed_Mesh.md:263-293` — `zero_reference_position`.
- `vendor/klipper/docs/Config_Changes.md` — Klipper v0.13+ removed keys (`max_accel_to_decel`).
- `vendor/happy-hare/config/optional/client_macros.cfg` — canonical PAUSE/RESUME/CANCEL_PRINT.
- `vendor/happy-hare/config/base/mmu_software.cfg` — slicer-side `MMU_START_*` macros.
- `vendor/happy-hare/config/base/mmu_sequence.cfg` — print lifecycle hooks.
- `vendor/mainsail-config/client.cfg` — upstream Mainsail PAUSE/RESUME (the version we're slimming).
- [AndrewEllis93/Print-Tuning-Guide](https://github.com/AndrewEllis93/Print-Tuning-Guide) — `TEST_SPEED.cfg` current upstream.
- [Carrot-collective/Filametrix](https://github.com/Carrot-collective/Filametrix) — the toolhead cutter on this build.
- [moggieuk/Happy-Hare wiki](https://github.com/moggieuk/Happy-Hare/wiki) — HH canonical docs.
- `memory/qgl-two-pass-intentional.md` — saggy-rear V2 quirk.
- `memory/defer-to-happy-hare.md` — overlap-resolution rule.
- `memory/filametrix-toolhead-cutter.md` — Filametrix correction.
- `memory/claude-md-may-drift-from-config.md` — CLAUDE.md/config drift discipline.
- CLAUDE.md `## Open investigations` — current list being migrated to GH Issues.
- `docs/superpowers/specs/2026-05-13-eddy-ng-to-native-migration.md` — preceding work this spec ships after.

---

*Next step after user review: invoke `superpowers:writing-plans` to produce the implementation plan.*
