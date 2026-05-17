# Config logical reorganization audit — 2026-05-17

**Spec:** [`docs/superpowers/specs/2026-05-17-config-reorg-audit-design.md`](../specs/2026-05-17-config-reorg-audit-design.md)
**Tracking issue:** [#30](https://github.com/bjdeng/voron-2-611/issues/30)
**Author:** Claude (Opus 4.7) in session with Ben
**Auditor stance:** Phase 4 PR-B shipped 2026-05-16 (1 day ago). Findings skew toward shape over lived-with friction; that trade was made consciously per spec §1.

---

## 1. Method

Single-pass read of every in-scope file (~2,000 LOC across 13 files), scored against the four criteria below. Only sections that hit at least one criterion became findings. Anti-criteria (intentional quirks documented in `memory/`, SAVE_CONFIG, behavior changes / tuning value updates) were skipped per spec §3.

`_USER_VARIABLE` cross-reference: every `variable_*` definition has at least one consumer site; every consumer reference resolves. Inventory is internally consistent.

## 2. Scope (as audited)

| File | LOC | In-scope reason | Verdict |
|---|---:|---|---|
| `config/printer.cfg` | 466 | top-level | findings present |
| `config/eddy.cfg` | 164 | top-level | findings present |
| `config/toolhead.cfg` | 64 | top-level | clean |
| `config/mainsail.cfg` | 138 | top-level | clean (Phase 2 already slimmed) |
| `config/macros/_user_variables.cfg` | 37 | macros + retrospective | clean inventory |
| `config/macros/macros.cfg` | 152 | macros | findings present |
| `config/macros/print_start.cfg` | 81 | macros | clean |
| `config/macros/bedfans.cfg` | 123 | macros | finding present |
| `config/macros/lcd_tweaks.cfg` | 133 | macros | finding present |
| `config/macros/test_speed.cfg` | 133 | macros | clean (third-party verbatim) |
| `config/macros/calibrate_flow.cfg` | 266 | macros | clean (third-party verbatim) |
| `config/macros/calibrate_pa.cfg` | 258 | macros | clean (third-party verbatim) |
| `config/moonraker.conf` | 106 | service config | finding present (blocked) |
| `config/crowsnest.conf` | 43 | service config | no change justified |
| `config/sonar.conf` | 18 | service config | no change justified |

## 3. Criteria + bar (from spec §3)

A section is flagged when at least one applies:

- **Cognitive load** — file too large or mixes too many concerns.
- **Concept duplication** — same concept lives in 2+ files without a documented reason.
- **Edit-frequency mismatch** — tunables buried, stable config in hot-edit files.
- **Pattern inconsistency** — missing `description:`, hardcoded value that fits an existing `_USER_VARIABLE` category, divergent style.

Service configs additionally require an articulated benefit before any change ships.

---

## 4. Findings

### F1 — Dead commented-out section declarations in `printer.cfg`
- **Location:** `config/printer.cfg:87-88`
- **Criterion:** pattern-inconsistency
- **Severity:** P3
- **Observation:** Lines 87-88 are `# [pause_resume]` and `# [display_status]` — leftover from the Phase 4 deferral to Happy Hare (see `memory/decisions.md` 2026-05-16 "Defer status sections to Happy Hare"). Two lines of dead text.
- **Recommendation:** Delete. The decision is captured in `memory/decisions.md`; the commented-out declarations don't add information.
- **Action:** `PR` — bundle with **F9** (same file).
- **Notes:** Zero risk.

### F2 — `printer.cfg` mixes ≥5 distinct subsystems
- **Location:** `config/printer.cfg` (whole file, ~404 LOC of config + 60 LOC SAVE_CONFIG)
- **Criterion:** cognitive-load
- **Severity:** P2
- **Observation:** The file contains, in order: MCU definitions (2), `[printer]` kinematics, 6 stepper sections + 6 TMC sections, `[input_shaper]`, `[heater_bed]`, `[thermistor 10k_thermistor]`, `[temperature_fan chamber]`, `[heater_fan controller_fan]`, `[temperature_sensor raspberry_pi]`, `[output_pin caselight]`, `[idle_timeout]`, `[quad_gantry_level]`, `[board_pins]`, `[display]`, `[output_pin beeper]`, `[neopixel lcd]`, then 12 `[include]`s, then SAVE_CONFIG. That's at least 5 distinct subsystems (motion, bed/chamber, lighting, display, leveling) interleaved. To find anything you scroll past everything.
- **Recommendation:** Split into:
  - `config/motion.cfg` — `[printer]`, 6 steppers + 6 TMCs, `[input_shaper]`
  - `config/bed.cfg` — `[heater_bed]`, `[thermistor 10k_thermistor]`, `[temperature_fan chamber]`, `[heater_fan controller_fan]`, `[quad_gantry_level]`
  - `config/display.cfg` — `[board_pins]`, `[display]`, `[output_pin beeper]`, `[neopixel lcd]`
  - `config/system.cfg` — `[temperature_sensor raspberry_pi]`, `[output_pin caselight]`, `[idle_timeout]`
  - `printer.cfg` shrinks to: 2 `[mcu]` declarations + `[include]`s + SAVE_CONFIG block.
  No behavior change; pure structural move.
- **Action:** `issue` — file as `future-work`, **needs its own `superpowers:brainstorming` cycle** before implementation (per spec §6 "non-trivial findings"). It's a 5-file refactor that touches Layer 3 (`tests/voron-2-611.test`), Layer 5 (`tests/test_config_structure.py` `[include]` order assertions), CLAUDE.md repo-layout section, and `scripts/macro_refcheck.py` path constants.
- **Notes:** High-yield. Likely the single biggest readability win in the audit. Do **after** F1 + F9 ship so the diff for this split is just structural, not also cleanup.

### F5 — `M190` bed-wait tolerance hardcoded, while `M109` uses `_USER_VARIABLE`
- **Location:** `config/macros/bedfans.cfg:84` vs `config/macros/macros.cfg:118`
- **Criterion:** pattern-inconsistency, concept-duplication
- **Severity:** P2
- **Observation:** `bedfans.cfg:84` uses `MAXIMUM={S|int + 5}` (hardcoded 5°C tolerance band). `macros.cfg:118` uses `MAXIMUM={s + tol}` where `tol` is `printer["gcode_macro _USER_VARIABLE"].m109_tolerance_celsius`. Two tolerance bands for two heaters, with two different mechanisms. The 5°C vs 1°C difference is likely intentional (bed has more thermal mass / PID overshoot), but the pattern divergence means a future tunable change requires touching two unrelated files.
- **Recommendation:** Add `variable_m190_tolerance_celsius: 5` to `_user_variables.cfg`; change `bedfans.cfg:84` to read from it. Default 5 preserves current behavior. Update CLAUDE.md "Macro inventory" entry for bedfans.cfg to note the new var.
- **Action:** `PR`
- **Notes:** Layer 5 (`tests/test_config_structure.py`) should auto-pass once the variable is defined and referenced.

### F6 — Duplicate `[display_data __voron_display progress_text*]` in `lcd_tweaks.cfg`
- **Location:** `config/macros/lcd_tweaks.cfg:87-92` (text-style) AND `lcd_tweaks.cfg:93-97` (progress bar)
- **Criterion:** concept-duplication, pattern-inconsistency
- **Severity:** P2
- **Observation:** Two `[display_data __voron_display progress_text*]` blocks both at `position: 1, 10`. They overlap on the LCD. Klipper takes the last-loaded (the bar at lines 93-97); the text-style version at lines 87-92 is dead. The Phase 4 spec called this out for removal (`docs/superpowers/specs/2026-05-15-config-macros-refactor.md` §6 target tree: "lcd_tweaks.cfg — duplicate progress_text removed") but the cleanup didn't ship.
- **Recommendation:** Delete the text-style block at `lcd_tweaks.cfg:87-92`. Keep `progress_text2` (the bar).
- **Action:** `PR`
- **Notes:** Zero behavior change — the dead block already isn't rendering.

### F7 — Stale `[update_manager timelapse]` + `[timelapse]` in `moonraker.conf`
- **Location:** `config/moonraker.conf:57-72`
- **Criterion:** edit-frequency-mismatch (rarely-touched config for an unused feature)
- **Severity:** P3
- **Observation:** moonraker-timelapse is wired up (`[update_manager timelapse]`, `[timelapse]`, plus the include in `printer.cfg:389`), but per CLAUDE.md "Installed but not in active use" + issue [#26](https://github.com/bjdeng/voron-2-611/issues/26), Ben has never used it. The "Don't forget to include timelapse.cfg" stale comment at line 57-59 actively misdirects.
- **Recommendation:** No action **here** — defer to issue [#26](https://github.com/bjdeng/voron-2-611/issues/26)'s resolution. When #26 closes (decision: keep or remove), the related blocks + the `[include timelapse.cfg]` in printer.cfg + the comment can be swept together as one PR.
- **Action:** `no-action` (blocked on #26)
- **Notes:** Service-config "justify-or-skip" rule: any change needs justification. The justification is "user doesn't use this feature" — that lives in #26.

### F8 — `macros.cfg` interleaves park / speed / shutdown sections
- **Location:** `config/macros/macros.cfg` (whole-file ordering)
- **Criterion:** cognitive-load
- **Severity:** P3
- **Observation:** Current order: `_CG28` → `_CQGL` → `OFF` → `SHUTDOWN` → `PARKFRONT` → `PARKFRONTLOW` → `PARKREAR` → `_RESETSPEEDS` → `PARKCENTER` → `PARKBED` → `M109` → `DELAYED_OFF` → `HEATSOAK`. `_RESETSPEEDS` interrupts the park sequence; `DELAYED_OFF` (a shutdown helper) is sandwiched between `M109` and `HEATSOAK`. A reader scanning for "where are the parks" gets bounced around.
- **Recommendation:** Reorder to: home helpers (`_CG28`, `_CQGL`) → shutdown (`OFF`, `SHUTDOWN`, `DELAYED_OFF`) → parks (5 contiguous, in order `PARKCENTER`, `PARKBED`, `PARKFRONT`, `PARKFRONTLOW`, `PARKREAR`) → speed (`_RESETSPEEDS`) → heater overrides (`M109`) → multi-step (`HEATSOAK`). Add `# ---- section ----` header comments between groups.
- **Action:** `PR`
- **Notes:** Cosmetic. Zero behavior change. Layer 7 snapshot diff (if re-run) shows comment/whitespace-only.

### F9 — Stale Voron-template header in `printer.cfg` (lines 1-67)
- **Location:** `config/printer.cfg:1-67`
- **Criterion:** cognitive-load, edit-frequency-mismatch
- **Severity:** P2
- **Observation:** Lines 1-19 are stock Voron template header ("THINGS TO CHANGE/CHECK" + "Adjust belts at X175, Y18, Z215 / XY: 110HZ / Z: 140HZ") — useful when commissioning the printer in 2020, dated now. Lines 21-67 duplicate every stepper / extruder / heater / fan / probe pin definition as comments — the same pins appear in the actual `[stepper_*]` and other sections below. If a pin ever changes, the comments drift silently. Total: 60+ lines of cruft that adds nothing but forces scrolling.
- **Recommendation:** Delete lines 1-67 (keep `## Voron Design VORON2 250/300/350mm SKR 1.4 TMC2209 UART config` header at line 1 — one-line repo identifier — and the `## Klipper Config docs:` link). Bundle with **F1** in the same PR.
- **Action:** `PR` (combined with F1)
- **Notes:** Net delete of ~65 lines from printer.cfg. Should be ordered **before** F2 (the split) so F2's diff stays clean.

### F13 — `(175, 175)` bed center duplicated in `eddy.cfg`
- **Location:** `config/eddy.cfg:53` (`zero_reference_position: 175, 175`) and `config/eddy.cfg:126` (`G1 X175 Y175 F12000` inside `[homing_override]`)
- **Criterion:** concept-duplication
- **Severity:** P3
- **Observation:** Bed-center coordinate (175, 175) is hardcoded in two places in the same file. Klipper config sections can't reference each other directly; `[homing_override].gcode` could read from `_USER_VARIABLE` (lazy gcode template), but `[bed_mesh].zero_reference_position` is parsed at startup and can't. So any deduplication would mean keeping `zero_reference_position` hardcoded and reading the value into `_USER_VARIABLE`, then referencing it from the homing_override gcode. That's still two definitions, just with documented coupling.
- **Recommendation:** Leave as-is (no-action). Two sites, single file, paired comments would suffice if drift were a real risk. Document the duplication in `memory/decisions.md` so this isn't re-discovered.
- **Action:** `no-action`
- **Notes:** Could revisit if the bed-center location ever moves (highly unlikely on a 350mm Voron 2).

---

## 5. PR queue

Order picked so cleanup ships before structural moves (small PRs lower the surface for F2).

| F# | Title | Severity | Action | Linked PR/issue |
|---:|---|:---:|:---:|---|
| **F9 + F1** | Delete printer.cfg leading cruft + dead `# [pause_resume]` / `# [display_status]` | P2 | PR | _pending_ |
| **F6** | Remove duplicate `progress_text` display_data | P2 | PR | _pending_ |
| **F5** | Add `m190_tolerance_celsius` variable, replace hardcoded `+5` in bedfans.cfg | P2 | PR | _pending_ |
| **F8** | Reorder `macros.cfg` section ordering (home → shutdown → parks → speed → heater → soak) | P3 | PR | _pending_ |
| **F2** | Split `printer.cfg` by subsystem (motion / bed / display / system) | P2 | issue → brainstorm | _pending GH issue_ |
| **F7** | Drop `[update_manager timelapse]` + `[timelapse]` blocks | P3 | blocked | depends on [#26](https://github.com/bjdeng/voron-2-611/issues/26) |
| **F13** | Bed-center `(175, 175)` duplication in eddy.cfg | P3 | no-action | document in `memory/decisions.md` |

**Suggested ship order:** F9+F1 → F6 → F5 → F8 → file F2 as a GH issue → wait on #26 for F7. Each PR follows `commit-push-pr` + `pr-review-toolkit:review-pr`.

---

## 6. No-action appendix

Findings considered and rejected, with reasons:

| F# | Title | Why no-action |
|---:|---|---|
| F3 | `[idle_timeout].gcode` contains an `OFF` call inline | Works fine, low value to extract; idle_timeout is rarely tuned. |
| F4 | Park macros hardcode `F6000` (×5), `Z=15`, `Z=20`, `axis_max.z-50` | Per YAGNI: these aren't actively tuned per-machine knobs, they're just constants. Adding ~6 variables to `_user_variables.cfg` would dilute the file. The current 7-var inventory is well-chosen; keep it focused. |
| F7 | `moonraker.conf` timelapse blocks | Blocked on [#26](https://github.com/bjdeng/voron-2-611/issues/26) — sweep together when that closes. |
| F10 | Hardcoded `initial_RED/GREEN/BLUE: 0.4` for `[neopixel lcd]` | Set-once-and-forget. Not a tunable; no recurring edit pressure. |
| F11 | `caselight` brightness `0.3` hardcoded in `PRINT_WARMUP` | Single literal in one site. YAGNI. |
| F12 | `idle_timeout: 7200` not in `_USER_VARIABLE` | **Architecturally infeasible.** `_USER_VARIABLE` only works for tunables that `[gcode_macro]` bodies reference (lazy jinja). Klipper config sections like `[idle_timeout]`, `[printer].max_velocity`, `[heater_bed].max_power` are parsed once at startup and cannot read from a `gcode_macro` variable. This is a fundamental limit of the `_USER_VARIABLE` pattern. Worth documenting in CLAUDE.md so future maintainers don't try. |
| F13 | `(175, 175)` bed center duplicated in eddy.cfg | Only 2 sites, same file. YAGNI. |
| F14 | "Adjust belts at X175, Y18, Z215" header in printer.cfg | Folded into F9. |
| F15 | Mixed `#####` vs `##====` ASCII separator styles | Bikeshed. |
| — | calibrate_flow.cfg / calibrate_pa.cfg / test_speed.cfg are >250 LOC | Third-party verbatim (Frix_x, Andrew Ellis). Restructuring loses the ability to bump upstream cleanly. Not worth touching. |
| — | `[delayed_gcode DELAYED_OFF]` / `[delayed_gcode bedfanloop]` lack `description:` | `description:` is a `[gcode_macro]` field per Klipper docs; `[delayed_gcode]` doesn't take it. Not a finding. |

---

## 7. `_USER_VARIABLE` retrospective

**Inventory after 1 day:** 7 variables, all defined and all consumed. No dead references, no orphaned variables.

| Variable | Consumers | Status |
|---|---|---|
| `bedfans_threshold` | bedfans.cfg (3 sites: SET_HEATER_TEMPERATURE, M190, bedfanloop) | actively read |
| `bedfans_fast` | bedfans.cfg BEDFANSFAST | actively read |
| `bedfans_slow` | bedfans.cfg BEDFANSSLOW | actively read |
| `heatsoak_default_bed_target` | macros.cfg HEATSOAK | actively read |
| `heatsoak_default_chamber_target` | macros.cfg HEATSOAK | actively read |
| `m109_tolerance_celsius` | macros.cfg M109 | actively read |
| `chamber_wait_bed_threshold` | print_start.cfg PRINT_START | actively read |
| `print_end_cooldown_seconds` | print_start.cfg PRINT_END | actively read |

**Missing tunables that arguably belong:** see F5 (the only one shipping as a PR). Other candidates were rejected per F4/F10/F11 — the discipline is "real tunables only, not every magic number," and the current inventory holds that line well.

**Architectural limit:** see F12. `_USER_VARIABLE` only reaches gcode-template contexts; Klipper config sections (`[idle_timeout]`, kinematics limits, heater limits) cannot read from it. Worth adding a one-liner to CLAUDE.md's `_USER_VARIABLE` section so future maintainers don't try to migrate the wrong things.

**Naming:** all variables use `<concept>_<axis>` or `<feature>_<purpose>` consistently. No renames recommended.

**Bottom line:** the pattern is healthy after 1 day. The August 2026 follow-up audit (optional per spec §1) can re-evaluate with real lived-with-it data.

---

## 8. Intentional-quirk cross-check

Confirmed no finding contradicts:

- [[qgl-two-pass-intentional]] — 2-pass QGL override in `eddy.cfg:134-158` left alone.
- [[defer-to-happy-hare]] — F1 only removes commented-out re-declarations; HH owns the live sections.
- `homing_override` Z-tap split-macro pattern — F13 only flags coordinate duplication, not the pattern itself.
- SAVE_CONFIG block at `printer.cfg:405-466` — untouched.
- Microsteps 128 on X/Y/Z — untouched (tracked in [#24](https://github.com/bjdeng/voron-2-611/issues/24)).
- Galileo 9:1 gear ratio in `toolhead.cfg` — untouched.
- `[homing_override]` instead of `[safe_z_home]` — preserved.

---

## 9. References

- [`docs/superpowers/specs/2026-05-17-config-reorg-audit-design.md`](../specs/2026-05-17-config-reorg-audit-design.md) — this audit's method spec.
- [`docs/superpowers/specs/2026-05-15-config-macros-refactor.md`](../specs/2026-05-15-config-macros-refactor.md) — Phase 1-6 refactor that introduced `_USER_VARIABLE`.
- [`docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md`](../specs/2026-05-16-phase4-macros-refactor-design.md) — Phase 4 PR-A/PR-B that just shipped.
- `memory/decisions.md` — 2026-05-16 entries on Mainsail slim + HH deferral (origin of F1).
- CLAUDE.md `## Macro inventory`, `## Repo layout` — surfaces that will need a paragraph each updated when F2 ships.
