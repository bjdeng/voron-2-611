# Config logical reorganization audit

**Status:** draft, awaiting approval
**Date:** 2026-05-17
**Tracking issue:** [#30](https://github.com/bjdeng/voron-2-611/issues/30)
**Branch:** `main` for the spec + audit report (docs-only, per [[docs-direct-to-main]]); separate `chore/` or `fix/` branches per fixup PR
**Skill chain:** `superpowers:brainstorming` → audit execution (this session) → per-finding fixup PRs

---

## 1. Goal

Audit the post-Phase-4 Klipper config tree and surface any sections where **cognitive load**, **concept duplication**, **edit-frequency mismatch**, or **pattern inconsistency** would benefit from a fixup. Produce a single committed audit document; each actionable finding becomes a small focused PR through the normal `commit-push-pr` + `pr-review-toolkit` flow.

The original framing in [#30](https://github.com/bjdeng/voron-2-611/issues/30) targeted ~2026-08-15 ("after ~3 months of living with `_USER_VARIABLE`"). Phase 4 PR-B shipped 2026-05-16, so we're 1 day in. We accept that most findings will skew toward shape rather than lived-with friction; the trade is having the context and bandwidth now versus deferring three months. The August date doesn't preclude a second, shorter audit later if pattern-fatigue surfaces.

## 2. Scope

### In scope

- `config/macros/*.cfg` (8 files, ~1,150 LOC)
  - `_user_variables.cfg`, `bedfans.cfg`, `calibrate_flow.cfg`, `calibrate_pa.cfg`, `lcd_tweaks.cfg`, `macros.cfg`, `print_start.cfg`, `test_speed.cfg`
- Top-level Klipper configs (~830 LOC)
  - `config/printer.cfg`, `config/eddy.cfg`, `config/toolhead.cfg`, `config/mainsail.cfg`
- **The `_USER_VARIABLE` pattern itself** — what landed there, what's still hardcoded elsewhere that arguably belongs, what's named badly or never read.
- Service configs — `config/moonraker.conf`, `config/crowsnest.conf`, `config/sonar.conf` — **with a justify-or-skip rule**: any proposed change must include a concrete reason (specific behavior gained or risk avoided). Default for these files is "leave as Moonraker/Crowsnest/Sonar defaults."

### Out of scope

- `config/mmu/**` — Happy Hare owned, symlinked on the Pi.
- `config/archive/**` — historical, intentionally untouched.
- `config/firmware/*.config` — kconfigs, not Klipper config.
- `config/timelapse.cfg` — symlink target on Pi; editing breaks the moonraker-timelapse update model (removal is tracked in [#26](https://github.com/bjdeng/voron-2-611/issues/26)).

## 3. Criteria + finding bar

A section is flagged when at least one applies:

| Criterion | What raises a flag |
|---|---|
| Cognitive load | File forces you to scroll past unrelated concepts to find what you want, **or** single file > ~300 LOC mixing multiple subsystems. |
| Concept duplication | Same concept (bed-related, extruder-related, etc.) lives in 2+ files without a documented reason. |
| Edit-frequency mismatch | Frequently-tuned setting buried in a stable file, **or** rarely-touched config in a hot-edit file. |
| Pattern inconsistency | Macro missing a `description:`, hardcoded value fitting an existing `_USER_VARIABLE` category, gcode style / jinja idiom diverging from neighbors. |

Service configs additionally require an articulated benefit before any change ships.

**Anti-criteria (do NOT flag):**

- Anything documented as intentional in `memory/` (e.g., [[qgl-two-pass-intentional]], [[defer-to-happy-hare]], the 2-pass QGL override, microsteps 128, the `homing_override` Z-tap split-macro pattern).
- Behavior changes — this is reorganization, not redesign. Findings that propose tuning value changes belong in [#25](https://github.com/bjdeng/voron-2-611/issues/25) (re-tune session), not here.
- Anything in the SAVE_CONFIG block at the bottom of `printer.cfg` (Klipper-owned).

## 4. Method

The audit happens in this session, in the main thread, directly — total in-scope is ~2,000 LOC across ~12 files, well within a single reading pass. No subagent.

1. **Read every in-scope file end-to-end.** Note section/macro counts and what concerns each file mixes.
2. **Build a cross-reference for `_USER_VARIABLE`** — every `variable_*` in `_user_variables.cfg` vs. every consumer site (grep `printer["gcode_macro _USER_VARIABLE"]` and `uv.<name>`), plus a separate scan for hardcoded values elsewhere that look like tunable knobs (park positions, fan thresholds, temperatures, distances) and aren't yet variables.
3. **Score each file × criterion.** Only sections that hit at least one criterion become a finding — no "everything's fine" entries.
4. **Write each finding** against the template in §5.
5. **Spot-check against memory + CLAUDE.md** — confirm no finding contradicts a documented intentional quirk.

## 5. Output

Single committed document: **`docs/superpowers/audits/2026-05-17-config-reorg-audit.md`**

The audit is self-contained — readable without this spec. It includes:

- Method, Scope, Criteria + bar (carried over from this spec)
- **Findings** — numbered list, per-finding template:
  ```
  ### F<N> — <short title>
  - Location: <file:line(s) | pattern>
  - Criterion: <one or more of cognitive-load / duplication / edit-frequency / pattern>
  - Severity: P1 | P2 | P3
  - Observation: <what's there>
  - Recommendation: <what to change>
  - Action: PR | issue | no-action
  - Notes (optional): <intentional quirk check, downstream impact, blockers>
  ```
- **PR queue** — table sorted P1 → P3, columns: `F#` | title | severity | action | linked PR/issue (filled in as work lands).
- **No-action appendix** — findings considered and rejected, with a one-line reason. Keeps decisions in the same doc instead of in commit messages.

## 6. Per-finding flow

### Severity

- **P1** — ship before the next print session. Latent bug, broken pattern with print-time risk.
- **P2** — ship this quarter. Small targeted PR, normal flow.
- **P3** — file as `future-work` GH issue, not necessarily acted on.

### PR flow

Approved audit serves as the bulk brainstorm/spec gate for everything tagged `PR`. Each fixup PR:

1. Worktree per PR if non-trivial (per [[use-worktrees-for-implementation]]).
2. Implementation.
3. `Skill: pr-review-toolkit:review-pr` **before push** (per [[feedback_pr_review_toolkit]] — no "trivial" exemption).
4. `Skill: commit-commands:commit-push-pr`.
5. After squash-merge: cleanup per [[feedback_cleanup_worktrees]].

Non-trivial findings (rare here — e.g., splitting `printer.cfg` into multiple files) get their own `superpowers:brainstorming` cycle before implementation.

`issue`-tagged findings become GH issues labeled `future-work`, linked from the PR queue.

## 7. Risks / acknowledged limits

- **Only ~1 day of post-`_USER_VARIABLE` living.** Findings skew toward shape over lived-with friction. We accept this trade-off; a second audit later is cheap if friction surfaces.
- **All four criteria are interpretive.** The "every finding cites a criterion + observation + recommendation" template keeps the bar visible. Bikeshedding risk is real but bounded by the no-behavior-change rule and the anti-criteria list in §3.
- **Coordination:** working tree is clean, no open PRs, [#58](https://github.com/bjdeng/voron-2-611/issues/58) is in `config/mmu/` (out of scope). MMU calibration session just closed. No concurrent work to coordinate.
- **Spec-as-bulk-approval** trusts the audit author's judgment per finding. If a P1 finding is mis-classified, the cost is a small reverted PR — acceptable.

## 8. Out of scope (deferred / explicitly not this audit)

- **Behavior changes / tuning value updates** — see [#25](https://github.com/bjdeng/voron-2-611/issues/25) (re-tune session).
- **MMU config reorganization** — Happy Hare owns `mmu/base/*`; structural changes need to flow upstream, not here.
- **Test pyramid extensions** — Layer 5 structural assertions are tracked in the Phase 4 spec. If the audit surfaces a missing assertion (e.g., "every `_USER_VARIABLE.X` reference resolves"), file as its own issue rather than expanding scope here.
- **Skill / docs reorganization** — `.claude/skills/` and `docs/` are not Klipper config. Out of scope.
- **A second audit at ~2026-08-15** — left as an optional follow-up if the first audit's findings raise lived-with-it questions that we can't answer with 1 day of data.

## 9. References

- [#30](https://github.com/bjdeng/voron-2-611/issues/30) — tracking issue.
- `docs/superpowers/specs/2026-05-15-config-macros-refactor.md` §9 — origin of the `_USER_VARIABLE` quarter framing.
- `docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md` — Phase 4 PR-A/PR-B (the refactor whose post-quarter we're auditing).
- `memory/qgl-two-pass-intentional.md`, `memory/defer-to-happy-hare.md`, `memory/claude-md-may-drift-from-config.md` — intentional-quirk references for the anti-criteria list.
- CLAUDE.md `## Repo layout` — current target file tree.
- CLAUDE.md `## Macro inventory` — current macro-by-file enumeration to cross-reference findings against.

---

*Next step after user review: execute the audit (read all in-scope files, produce `docs/superpowers/audits/2026-05-17-config-reorg-audit.md`).*
