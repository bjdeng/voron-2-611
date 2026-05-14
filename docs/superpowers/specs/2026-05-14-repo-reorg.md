# Repo reorganization — separate machine state from tooling

**Status:** spec
**Date:** 2026-05-14
**Owner:** Ben

## Problem

The repo's top-level has ~25 entries that mix two unrelated kinds of file:

- **Machine state**: 8 `.cfg`/`.conf` files at root + `macros/` + `mmu/` + `archive/` + `firmware/` — everything that describes (or supports flashing) the Voron's Klipper install.
- **Tooling**: `scripts/`, `tests/`, `vendor/`, `docs/`, `memory/`, `.claude/`, `.github/`, plus `Makefile` / `requirements.txt` / `.pre-commit-config.yaml` — the infrastructure we built around the machine.

The mix has two concrete costs:

1. **The deploy script's rsync exclude list has to enumerate every tooling path.** It currently has ~22 exclude entries (`.git/`, `.github/`, `.claude/`, `vendor/`, `scripts/`, `tests/`, `docs/`, `memory/`, `firmware/`, `archive/`, plus a dozen individual files). Every new tooling folder requires updating it; missed entries are the cause of two recent bugs (noise files leaked, symlinks overwritten).
2. **A reader can't tell at a glance what's "the printer" vs "the tools around it."** The top-level reads ambiguous: is this a Klipper config dump or a software project?

## Goal

Reorganize the repo so machine state lives in a single top-level folder (`config/`) and everything else stays at root. Top-level becomes ~11 entries that read clearly as an infrastructure-as-code project. The deploy script's exclude list shrinks to just the dynamically-discovered Pi symlinks + the SAVE_CONFIG-spliced `printer.cfg`.

## Target layout

```
voron-2-611/
├── CLAUDE.md, README.md, LICENSE        (root, unchanged)
├── Makefile, requirements.txt           (root, unchanged)
├── .pre-commit-config.yaml, .gitignore, .gitmodules, .env
├── .github/, .claude/                   (root, unchanged)
│
├── config/                              ← NEW: the entire machine surface
│   ├── printer.cfg
│   ├── eddy.cfg
│   ├── btt-ebb-sb-usb-v1.0.cfg
│   ├── mainsail.cfg
│   ├── timelapse.cfg
│   ├── moonraker.conf
│   ├── crowsnest.conf
│   ├── sonar.conf
│   ├── macros/                          (all macro .cfg files)
│   ├── mmu/                             (base/, optional/, addons/, mmu_vars.cfg)
│   ├── archive/                         (klicky/, z_calibration.cfg — historical)
│   └── firmware/                        (per-MCU build kconfigs)
│
├── docs/                                (specs, plans — unchanged location)
├── memory/                              (decisions, tuning, troubleshooting — unchanged)
├── scripts/                             (deploy_to_pi.sh, sync_from_pi.sh, macro_refcheck.py)
├── tests/                               (test_*.py, fixtures/, fake_bin/, voron-2-611.test)
└── vendor/                              (submodules, unchanged)
```

`archive/` and `firmware/` go inside `config/` even though they're not deployed — both are machine-specific state, just at different lifecycle stages (archived configs, build-time MCU inputs). Colocating them keeps the entire machine surface in one folder; someone reading just `config/` sees everything printer-related.

## Tooling updates (besides file moves)

### `scripts/deploy_to_pi.sh`

- rsync source: `$REPO_ROOT/` → `$REPO_ROOT/config/`.
- `RSYNC_EXCLUDES` shrinks dramatically. The rsync source is now `config/`, so every tooling path (which lives OUTSIDE `config/`) is already excluded by virtue of not being in the source. Delete these now-unneeded entries: `/.git/`, `/.github/`, `/.claude/`, `/.venv/`, `/.worktrees/`, `/vendor/`, `/scripts/`, `/tests/`, `/docs/`, `/memory/`, `.gitignore`, `.pre-commit-config.yaml`, `Makefile`, `LICENSE`, `README.md`, `CLAUDE.md`, `requirements.txt`, `.env`, `.env.example`, `.gitmodules`, `.pytest_cache/`, `.ruff_cache/`.
- Final static excludes (all rooted relative to the new `config/` source): `/firmware/` (build kconfigs aren't deployed), `/archive/` (historical configs aren't deployed), and `printer.cfg` (SAVE_CONFIG-spliced separately, not rsync'd as-is). Plus the dynamic symlink list from `discover_pi_symlinks`.
- `check_no_pi_drift` reads `$REPO_ROOT/config/printer.cfg` (was `$REPO_ROOT/printer.cfg`).
- `build_staged_printer_cfg` reads `config/printer.cfg`.

### `scripts/sync_from_pi.sh`

- rsync destination: `./` → `./config/`. The Pi-side path doesn't change.

### `tests/voron-2-611.test`

- The `CONFIG` line that points at `printer.cfg` becomes `config/printer.cfg`.

### `Makefile`

- The `macro_refcheck.py` invocation's file globs become `config/*.cfg config/macros/*.cfg config/mmu/**/*.cfg`. (Verify glob syntax against the existing target.)

### `.github/workflows/ci.yml`

- `paths-ignore` patterns still work since `**/*.md` and friends are repo-relative.
- Add the new no-op success job for docs paths (planned separately after this reorg merges, but the workflow file gets touched here so an inline note is fine).

### `printer.cfg`'s own `[include]` directives

- All relative paths (`[include macros/macros.cfg]`, `[include mmu/base/*.cfg]`, etc.) keep working because `printer.cfg` and its includes move together. No edits to `printer.cfg` needed.

### `CLAUDE.md`

- Lots of inline path references (`macros/lcd_tweaks.cfg:126`, `mmu/base/*`, `firmware/ebb-usb.config`, etc.) need `config/` prefix. Bulk find-replace via `sed -i` or careful editing.
- Same for `scripts/deploy_to_pi.sh`'s comment references.
- Don't update paths inside spec/plan docs that describe historical state (`docs/superpowers/specs/*`) — those are dated and refer to the layout at the time the spec was written. Add a note at the top of THIS spec linking to it as the moment the layout changed.

### `memory/*.md`

- Path references may need updating (`macros/decisions.md`, etc.). Same find-replace pattern.

## What does NOT change

- The Pi-side directory: `~/printer_data/config/` stays the rsync destination. From the Pi's perspective, nothing changes.
- The skill at `.claude/skills/deploy-to-pi/SKILL.md` describes WHAT the script does, not file paths in this repo. Only the "How to run" example (`scripts/deploy_to_pi.sh`) stays the same.
- The skill at `.claude/skills/sync-from-pi/SKILL.md` — same, unchanged.
- `vendor/` content — unchanged.
- Test suite logic — unchanged. Only path constants update.
- `.last-deploy-sha` marker handling — same.

## Migration approach

**Single PR, atomic move.** Reasons:

- Tests can't pass partway through: if files moved but `Makefile`/`tests/voron-2-611.test` didn't update, refcheck and klippy-parse break.
- Git tracks renames cleanly (`git mv` → renames in the diff), so the PR stays reviewable despite touching ~30 files.
- The tooling updates are small and tightly coupled to the moves; splitting them adds rework without benefit.

PR sequence:

1. `git mv` each top-level machine file and each top-level machine directory into `config/`. (`printer.cfg`, `eddy.cfg`, `btt-ebb-sb-usb-v1.0.cfg`, `mainsail.cfg`, `timelapse.cfg`, `moonraker.conf`, `crowsnest.conf`, `sonar.conf`, `macros/`, `mmu/`, `archive/`, `firmware/`.)
2. Update `scripts/deploy_to_pi.sh` (rsync source path + exclude list pruning + `check_no_pi_drift` + `build_staged_printer_cfg` + comments).
3. Update `scripts/sync_from_pi.sh` (destination path).
4. Update `tests/voron-2-611.test` (`CONFIG` line).
5. Update `Makefile` (`macro_refcheck.py` invocation globs).
6. Update `CLAUDE.md` (bulk path-reference replacement).
7. Update `memory/*.md` (same).
8. `make test-py` passes. shellcheck clean.
9. Run `bash scripts/deploy_to_pi.sh --dry-run` against the real Pi as the e2e verification. All gates should pass (drift, CI green, symlink discovery, etc.). The dry-run preview should show the rsync source as `config/`.
10. Commit + PR.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `git mv` of a directory loses history if any file inside gets modified concurrently | Do all the `git mv` calls in a single commit with no content changes; tooling updates land in subsequent commits on the same PR. Or one commit total with both — let `git log --follow` handle the rest. |
| `[include]` path inside printer.cfg accidentally absolute or `..`-relative | Pre-check: `grep "^\[include\]" printer.cfg` shows no absolute paths today, but verify before/after the move. |
| Hidden hardcoded path in a script or test | `make test-py` after each tooling update step. The macro_refcheck unit tests (`test_real_repo_passes` etc.) exercise the actual file layout. |
| The deploy script's `rsync` exclude list is partially wrong post-reorg (e.g., we forget to add `/firmware/` exclude inside the new source root) | The e2e dry-run against the real Pi (step 9) catches this — if `firmware/` accidentally syncs, it'll show up in the rsync preview. |
| Path references in `docs/superpowers/specs/*` and `memory/*` become misleading without updates | Bulk find-replace, but exempt the historical specs and plans (they describe past state). Add a "post-reorg" note pointing readers at this spec as the inflection point. |

## Testing

- `make test-py` (macOS subset: macro_refcheck + pytest + pre-commit) passes after every commit on the branch.
- pytest count should be unchanged (33 deploy + 8 refcheck = 41).
- Run `bash scripts/deploy_to_pi.sh --dry-run` from main (after merge) and verify:
  - All gates pass
  - rsync preview shows `config/` as the source (or at least clearly shows files relative to `config/`)
  - No `firmware/`, `archive/`, or tooling files in the preview
  - Restart kind classification still works (this tests `git diff --name-only` against `.last-deploy-sha`)

## Out of scope

- Pi-side directory structure (stays `~/printer_data/config/`).
- Renaming any individual file inside `config/` — only moves.
- Editing skill / spec / plan content other than path references.
- The CI workflow no-op-success-on-docs-paths fix (planned separately, after this lands, to unblock PR #9).
- Adding a `vendor/` entry for Galileo / EASY-BRD (separate task; URL references already in CLAUDE.md per PR #9).
