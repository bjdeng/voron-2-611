# Phase 4 — Macros refactor + file reorg

**Status:** draft, awaiting approval
**Date:** 2026-05-16
**Branches (when implementation starts):** `feat/refactor-phase4a-structural`, then `feat/refactor-phase4b-user-variable` (in series, not parallel)
**Skill chain:** `superpowers:brainstorming` → `superpowers:writing-plans` (next) → `superpowers:using-git-worktrees` → `pr-review-toolkit:review-pr` (before push, per CLAUDE.md)
**Supersedes:** Section "Phase 4 — Macros refactor + file reorg" of [`docs/superpowers/specs/2026-05-15-config-macros-refactor.md`](2026-05-15-config-macros-refactor.md). That master spec stays canonical for phases 1–3 (shipped) and 5–6 (deferred).

---

## 1. Goal

Finish the structural side of the config/macros refactor: rename the toolhead MCU config to reflect its role; place `[extruder]` in one file; remove duplicate status-section declarations; describe every macro we own; reorganize `printer.cfg` `[include]` order with section comments; isolate hardcoded printer-level tunables behind a single `_USER_VARIABLE` block.

**No behavior change.** Values copied verbatim. Layer 7 (behavior diff, PR-B only) is the safety net.

## 2. Scope

### In scope — two PRs in series

#### PR-A: Structural cleanup (~250–350 line diff, mostly mechanical)

1. **Rename `config/btt-ebb-sb-usb-v1.0.cfg` → `config/toolhead.cfg`.** Update path references:
   - `config/printer.cfg:68` — the `[include btt-ebb-sb-usb-v1.0.cfg]` line.
   - `tests/test_macro_refcheck.py:108`.
   - `Makefile:7`.
   - `.github/workflows/ci.yml:131`.
   - `CLAUDE.md` — four references (hardware inventory, "real files we own", quirks section, repo layout tree).
   - The master spec [`2026-05-15-config-macros-refactor.md`](2026-05-15-config-macros-refactor.md) — keep self-references current.

   `tests/voron-2-611.test` does not need an edit — its `CONFIG` line points at `printer.cfg`, which transitively pulls in the renamed file.
2. **Consolidate `[extruder]` PA + limits into `toolhead.cfg`.** Move `config/printer.cfg:231-238` (the `min_temp`/`max_temp`/`max_power`/`min_extrude_temp`/`max_extrude_only_distance`/`pressure_advance`/`pressure_advance_smooth_time` block) into `toolhead.cfg`, joining the existing `[extruder]` body that already declares stepper + heater pins. Result: one `[extruder]` declaration in our files. `[input_shaper]` stays in `printer.cfg` (system-wide; SAVE_CONFIG-bound).
3. **Remove duplicate status-section declarations.** Per [`memory/defer-to-happy-hare.md`](../../../memory/defer-to-happy-hare.md):
   - Delete `[respond]` from `config/printer.cfg:97` and `config/mainsail.cfg:39`. HH declares it in `config/mmu/base/mmu_macro_vars.cfg:50`.
   - Delete `[exclude_object]` from `config/printer.cfg:96`. HH declares it in `config/mmu/addons/blobifier.cfg:737`.
   - Delete `[pause_resume]` from `config/mainsail.cfg:32` and `[display_status]` from `config/mainsail.cfg:37`. HH declares both in `config/mmu/base/mmu_macro_vars.cfg:53-54`.
4. **Add `description:` field to every `[gcode_macro]` we own** in `config/macros/*.cfg` and `config/eddy.cfg`. Today (counts via `grep -n '^\[gcode_macro\|^description:'`): 32 owned macros, 6 already have a description, so 26 need one (including `_BEDFANVARS`, which PR-B deletes — adding a description in PR-A is wasted work; either deliberately skip it or accept the trivial churn). MMU macros and `mainsail.cfg` helpers excluded — HH-owned (would be wiped by `~/Happy-Hare/install.sh`) or already covered.
5. **Reorganize `[include]` order in `printer.cfg`** with section-header comments. Suggested groups:
   - MCU + hardware configs (`toolhead.cfg`)
   - Probe + bed leveling (`eddy.cfg`)
   - MMU (`mmu/base/*.cfg`, `mmu/optional/*.cfg`, `mmu/addons/blobifier.cfg`)
   - Client (Mainsail + timelapse) (`mainsail.cfg`, `timelapse.cfg`)
   - Macros (`macros/*.cfg`)

   No file moves. Only reordering + comments.
6. **Layer 5 tripwires (in `tests/test_config_structure.py`)**:
   - `test_every_owned_macro_has_description` — walks `config/macros/*.cfg` + `config/eddy.cfg`, asserts every `[gcode_macro]` has `description:` with non-empty value. Excludes `config/mmu/**`, `config/mainsail.cfg`, `config/archive/**`.
   - `test_status_sections_declared_at_most_once` — `[respond]/[exclude_object]/[pause_resume]/[display_status]` appear at most once across all `[include]`d files outside `config/mmu/**` and `config/archive/**`.
   - `test_extruder_section_single_file` — `[extruder]` is declared in exactly one of our owned files (`config/toolhead.cfg`), excluding HH's variable-injection block in `config/mmu/base/mmu_macro_vars.cfg`.

#### PR-B: `_USER_VARIABLE` migration (~150–250 line diff)

1. **Add `config/macros/_user_variables.cfg`** containing one `[gcode_macro _USER_VARIABLE]` block. Exact contents:

   ```ini
   [gcode_macro _USER_VARIABLE]
   description: Single source of truth for printer-level tunables.
   variable_bedfans_threshold: 100
   variable_bedfans_fast: 0.6
   variable_bedfans_slow: 0.2
   variable_heatsoak_default_bed_target: 110
   variable_heatsoak_default_chamber_target: 30
   variable_m109_tolerance_celsius: 1
   variable_chamber_wait_bed_threshold: 90
   variable_print_end_cooldown_seconds: 60
   gcode:
   # variables only — no body
   ```
2. **Delete `[gcode_macro _BEDFANVARS]`** from `config/macros/bedfans.cfg:2-6` after migrating its references.
3. **Migrate references** (each migration is one commit so review reads cleanly):
   - `config/macros/bedfans.cfg` — replace every `printer["gcode_macro _BEDFANVARS"].threshold|int` with `printer["gcode_macro _USER_VARIABLE"].bedfans_threshold|int`. Same for `.fast` and `.slow`. Three macros touched: `SET_HEATER_TEMPERATURE` (line 42), `M190` (line 71), `delayed_gcode bedfanloop` (line 113). Plus `BEDFANSSLOW` (line 18) and `BEDFANSFAST` (line 25) which read `.slow`/`.fast`.
   - `config/macros/macros.cfg` — `HEATSOAK` macro (line 113): replace `params.T|default(110)|int` with `params.T|default(printer["gcode_macro _USER_VARIABLE"].heatsoak_default_bed_target)|int`. Replace `params.C|default(30)|int` with `params.C|default(printer["gcode_macro _USER_VARIABLE"].heatsoak_default_chamber_target)|int`. Also `M109` (line 98): replace `MAXIMUM={s+1}` with `MAXIMUM={s + printer["gcode_macro _USER_VARIABLE"].m109_tolerance_celsius|int}`.
   - `config/macros/print_start.cfg` — `PRINT_START` (line 46): replace `{% if params.BED|int > 90 %}` with `{% if params.BED|int > printer["gcode_macro _USER_VARIABLE"].chamber_wait_bed_threshold|int %}`. `PRINT_END` (line 76): replace `G4 P60000` with `G4 P{(printer["gcode_macro _USER_VARIABLE"].print_end_cooldown_seconds * 1000)|int}`.
4. **Layer 5 tripwires (extends `tests/test_config_structure.py`)**:
   - `test_user_variable_refs_resolve` — every `_USER_VARIABLE.<name>` reference in any owned `[gcode_macro]` body has a corresponding `variable_<name>:` in `_user_variables.cfg`.
   - `test_user_variable_definitions_used` — every `variable_<name>:` in `_user_variables.cfg` is referenced somewhere outside its own definition file. Catches orphaned vars after a half-rolled-back migration.
5. **Layer 7 behavior diff (one-shot)**:
   - `scripts/macro_behavior_diff.py` — drives `vendor/klipper/scripts/test_klippy.py` with a fixture `.test` that invokes a fixed set of macros, captures gcode dispatcher output, writes to `tests/snapshots/macro_behavior_<label>.txt`. Fixed macros: `PARKCENTER`, `HEATSOAK BED_TEMP=110 EXTRUDER_TEMP=240`, `BEDFANSSLOW`, `BEDFANSFAST`, `M109 S240`, `M190 S110`, `M140 S110`, `TURN_OFF_HEATERS`, `OFF`, `PRINT_END`.
   - `make snapshot-before` (run on `main` at PR-B branch base), `make snapshot-after` (post-implementation). Diff must be comments/whitespace only; anything else blocks merge.

### From the master spec — explicitly NOT in this Phase 4 spec

- **`docs/slicer-templates/` / OrcaSlicer hooks** — Phase 5 in the master spec.
- **Slicer-side `MMU_START_*` documentation** — Phase 5.
- **Two skills (`klipper-config-work`, `happy-hare-integration`)** — Phase 6 in the master spec.

### Out of scope (deferred / acknowledged)

- The 47-line `# Pin Definitions` ASCII comment block at `config/printer.cfg:21-67` is stale Voron-template documentation. Leaving alone per YAGNI; no behavior impact.
- `config/macros/lcd_tweaks.cfg` has zero `[gcode_macro]` sections (only `[display_data]` / `[display_glyph]` / `[menu]`), so the description-coverage requirement does not apply to it.
- Park positions stay derived from `printer.toolhead.axis_maximum/minimum` — not pulled into `_USER_VARIABLE`. They auto-track the kinematic config.
- Park speeds (F6000/F9000/F1500/F12000) stay hardcoded — they haven't changed in years and YAGNI.
- Adding `description:` to MMU-owned macros — those files are symlinks to `~/Happy-Hare/config/base/` on the Pi; edits would be wiped by the next `~/Happy-Hare/install.sh`.

## 3. Constraints

- Each PR ≤ ~350 lines diff. PR-A is mostly mechanical (rename + section moves + descriptions); PR-B is value-copying.
- All changes pass existing CI: pre-commit (L1) + `macro_refcheck.py` (L2) + `klippy parse + smoke` (L3) + pytest (L4) + the new Layer 5 tripwires.
- No changes to `config/mmu/**` (HH-owned, symlinks on Pi).
- No changes to `vendor/**`.
- No changes to `config/archive/**` (historical, not included).
- Pi-side `~/printer_data/printer.cfg` SAVE_CONFIG block is preserved across deploy. Klipper merges `#*# [extruder]` PID values into the consolidated `[extruder]` block at runtime — `vendor/klipper/klippy/configfile.py` does this multi-file section merge unconditionally.

## 4. Test pyramid mapping (existing pyramid, what this spec adds)

| Layer | Per-PR | What this spec adds |
|---|---|---|
| 1 — pre-commit | every | nothing new |
| 2 — `macro_refcheck.py` | every | nothing new |
| 3 — `klippy parse` | every | nothing new |
| 4 — pytest | every | new tests in `test_config_structure.py` (covered under L5) |
| 5 — `test_config_structure.py` | every | **PR-A**: `test_every_owned_macro_has_description`, `test_status_sections_declared_at_most_once`, `test_extruder_section_single_file`. **PR-B**: `test_user_variable_refs_resolve`, `test_user_variable_definitions_used`. |
| 6 — post-deploy smoke | manual, after deploy | nothing new |
| 7 — behavior diff (one-shot) | PR-B only | `scripts/macro_behavior_diff.py` + `tests/snapshots/macro_behavior_{before,after}.txt`. Diff must be comments/whitespace only. |

## 5. Restart classification

| Change | Restart impact |
|---|---|
| Rename `btt-ebb-sb-usb-v1.0.cfg` → `toolhead.cfg` | `RESTART` (config-file path change, no MCU change) |
| Consolidate `[extruder]` | `RESTART` (Klipper merges multi-file sections at parse time; moving the body to one file produces the same parsed config) |
| Remove duplicate `[respond]/[exclude_object]/[pause_resume]/[display_status]` | `RESTART` (no MCU change) |
| Add `description:` fields | `RESTART` (macro re-parse) |
| Reorganize `[include]` order in `printer.cfg` | `RESTART` (parser re-orders include resolution; final merged config is identical) |
| `_USER_VARIABLE` introduction + migration | `RESTART` (macro re-parse) |

No `FIRMWARE_RESTART` required for any change in this spec. No MCU `.config` flags touched.

## 6. Rollback

| PR | Rollback | Pi-side risk |
|---|---|---|
| PR-A | `git revert <sha>` then `/deploy-to-pi --smoke` | Low — the toolhead.cfg → btt-ebb file is a `git mv` so revert is clean. SAVE_CONFIG `#*# [extruder] control = pid` block is untouched throughout. |
| PR-B | `git revert <sha>` then `/deploy-to-pi --smoke` | Low — values restored verbatim by revert. Layer 7 snapshot is the assurance that the values are byte-equivalent. |

No destructive Pi operations. No need to re-run any calibration.

## 7. Risks

- **Pi SAVE_CONFIG drift.** The Pi rewrites `#*# [extruder] control = pid ...` on every `SAVE_CONFIG`. Phase 4's `[extruder]` consolidation does not touch the SAVE_CONFIG block. Verification: Layer 6 post-deploy smoke succeeds after PR-A merge.
- **Duplicate-section removal under future HH-disabled scenario.** Removing `[respond]/[exclude_object]/[pause_resume]/[display_status]` from our files means a future MMU disable (commenting out `mmu/base/*.cfg` includes) breaks Klipper load until the declarations are restored. This trade-off is intentional and recorded in `memory/decisions.md`. HH is structurally load-bearing on this build; the failure mode is unlikely and recoverable.
- **bedfans.cfg M140/M190/TURN_OFF_HEATERS overrides** are exercised by Layer 7's fixed macro set, so any behavior delta from the migration is caught.
- **`[homing_override]` references in `config/eddy.cfg`** include hardcoded `X175 Y175` and `Z10 F1500` z-hop. These are NOT migrated to `_USER_VARIABLE` (they're tightly coupled to `zero_reference_position: 175, 175` in `[bed_mesh]` and the prior `safe_z_home: 175, 175`). Decision recorded in this section so future readers don't try to extract them.

## 8. Sequencing within each PR

### PR-A commits (suggested)

1. `chore(refactor): rename btt-ebb-sb-usb-v1.0.cfg → toolhead.cfg`
2. `refactor(toolhead): consolidate [extruder] PA + limits into toolhead.cfg`
3. `refactor(includes): remove duplicate [respond]/[exclude_object]/[pause_resume]/[display_status]`
4. `refactor(macros): add description: to every owned [gcode_macro]`
5. `refactor(includes): reorganize printer.cfg include order with section comments`
6. `chore(tests): add Layer 5 tripwires for PR-A invariants`

### PR-B commits (suggested)

1. `chore(tests): add scripts/macro_behavior_diff.py + snapshot-before target`
2. `feat(macros): introduce _user_variables.cfg with bedfans + heatsoak + tolerance vars`
3. `refactor(bedfans): read from _USER_VARIABLE; delete _BEDFANVARS`
4. `refactor(macros): HEATSOAK + M109 read tunables from _USER_VARIABLE`
5. `refactor(print_start): chamber-wait threshold + PRINT_END cooldown read from _USER_VARIABLE`
6. `chore(tests): generate snapshot-after; verify diff is whitespace-only`
7. `chore(tests): add Layer 5 tripwires for _USER_VARIABLE invariants`

## 9. Acceptance criteria

PR-A:
- [ ] All six PR-A scope items merged in commits (rename, `[extruder]` consolidation, duplicate-section removal, descriptions, include reorder, Layer 5 tripwires).
- [ ] CI green (all of L1-L5).
- [ ] `pr-review-toolkit:review-pr` run pre-push with no blocking findings.
- [ ] `klipper-cfg-reviewer` (project-specific agent) run on `.cfg` diffs with no blocking findings.
- [ ] `/deploy-to-pi --smoke` succeeds; Klipper boots to `printer.state == "ready"`; smoke gcode sequence (`G28`, `PARKCENTER`, `OFF`, `_RESETSPEEDS`) runs without `^!! ` in `klippy.log`.
- [ ] Master spec [`2026-05-15-config-macros-refactor.md`](2026-05-15-config-macros-refactor.md) Phase 4 section updated with a pointer to this spec.

PR-B:
- [ ] All five PR-B scope items merged in commits (`_user_variables.cfg`, `_BEDFANVARS` deletion, reference migration, Layer 5 tripwires, Layer 7 behavior diff).
- [ ] CI green (all of L1-L5).
- [ ] Layer 7: `diff -w tests/snapshots/macro_behavior_{before,after}.txt` returns no non-comment-non-whitespace differences. Snapshots committed.
- [ ] `pr-review-toolkit:review-pr` + `klipper-cfg-reviewer` run pre-push, no blocking findings.
- [ ] `/deploy-to-pi --smoke` succeeds.
- [ ] First real print after deploy completes without behavior anomaly (manual check; ack'd in PR comment).

## 10. References

- [`docs/superpowers/specs/2026-05-15-config-macros-refactor.md`](2026-05-15-config-macros-refactor.md) — master spec; this doc supersedes its Phase 4 section.
- `vendor/klipper/docs/Command_Templates.md` — `printer["gcode_macro X"].variable_Y` accessor syntax for `_USER_VARIABLE` reads.
- `vendor/klipper/klippy/configfile.py` — multi-file section merge semantics for `[extruder]`.
- `vendor/happy-hare/config/base/mmu_macro_vars.cfg` — canonical (upstream) declarations for `[respond]`, `[pause_resume]`, `[display_status]`, `[extruder]` (HH variable injection block); the on-Pi symlink at `config/mmu/base/mmu_macro_vars.cfg` resolves here.
- `vendor/happy-hare/config/addons/blobifier.cfg` — canonical (upstream) declaration for `[exclude_object]`; the on-Pi symlink at `config/mmu/addons/blobifier.cfg` resolves here.
- [`memory/defer-to-happy-hare.md`](../../../memory/defer-to-happy-hare.md) — overlap-resolution rule.
- [`memory/qgl-two-pass-intentional.md`](../../../memory/qgl-two-pass-intentional.md) — why hardcoded XY in `homing_override`/QGL is intentional and stays out of `_USER_VARIABLE`.
- CLAUDE.md `## Testing` — pyramid layer descriptions.
- PR #43 — Layer 6 post-deploy smoke (already shipped).
- PR #47 — `[homing_override]` adoption (already shipped, anchors why `eddy.cfg` is in scope for descriptions).

---

*Next step: `superpowers:writing-plans` to produce the implementation plan for PR-A and PR-B (per goal: "after you create and self-review the spec, the planning is approved").*
