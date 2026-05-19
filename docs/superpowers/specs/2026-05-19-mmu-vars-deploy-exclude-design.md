# `/deploy-to-pi` must stop clobbering `mmu_vars.cfg`

Closes [#69](https://github.com/bjdeng/voron-2-611/issues/69).

## Problem

`/deploy-to-pi` rsyncs the repo's `config/mmu/mmu_vars.cfg` over the Pi's live `~/printer_data/config/mmu/mmu_vars.cfg` on every deploy. The repo's copy is a point-in-time snapshot from whenever `/sync-from-pi` last ran. The Pi's copy is live state that Klipper rewrites on every MMU operation (gate load/unload, tool change, calibration save). They drift continuously.

Each deploy potentially resets MMU calibrations (gear rotation distances, encoder cal, bowden length, selector offsets) to stale values. Confirmed 2026-05-18 by md5 comparison showing repo and Pi versions differ.

`/sync-from-pi` already pulls this file in the correct direction (Pi → repo) and works as intended. The bug is only in the deploy direction.

## Why this file is special

`mmu_vars.cfg` is **100% Klipper `[save_variables]` content** — a single `[Variables]` section with key=value lines that Klipper's `[save_variables]` mechanism rewrites atomically on each `SAVE_VARIABLE` invocation. Happy Hare persists nearly all of its runtime state through this file: per-gate gear calibration, encoder constants, bowden length, gate filament names, counters, statistics.

There is no static user-authored section. Splice-style merging (analogous to `printer.cfg`'s SAVE_CONFIG block) degenerates to "use the Pi's version entirely" — no body to preserve.

The file is unique among repo `config/` contents in that the **Pi is the canonical source of truth**, not the repo. Same direction-of-truth as `printer.cfg`'s SAVE_CONFIG block, but file-level rather than block-level.

## Design

**Exclude `config/mmu/mmu_vars.cfg` from the `/deploy-to-pi` rsync push. Add a drift summary line to the deploy output so the user can see when the repo's snapshot has fallen behind the Pi's live state.**

### Behavioral specification

1. **`scripts/deploy_to_pi.sh`**:
   - Add `config/mmu/mmu_vars.cfg` to the file-set exclusion list (`build_rsync_excludes()` or equivalent).
   - Before rsync runs, compute md5 of (a) the repo's `config/mmu/mmu_vars.cfg` and (b) the Pi's `~/printer_data/config/mmu/mmu_vars.cfg`.
   - If md5s match: print `==> mmu_vars.cfg: Pi-managed state, deploy skipped (in sync with repo snapshot)`.
   - If md5s differ: print `==> mmu_vars.cfg: Pi-managed state, deploy skipped. Repo snapshot differs from Pi. Run /sync-from-pi to update the repo backup if desired.`
   - If the Pi's file doesn't exist: print `==> mmu_vars.cfg: not present on Pi. Klipper will create on first MMU operation.`
   - Both messages go to stderr (matches the existing `==>` step indicators in the script).
   - Drift detection happens regardless of `--dry-run` or `--yes`. The check is read-only.

2. **`scripts/sync_from_pi.sh`**: no change. Continues to pull `mmu_vars.cfg` from Pi to repo (correct direction).

3. **`config/mmu/mmu_vars.cfg`**: stays tracked in git. The repo's copy is a recovery snapshot, refreshed by `/sync-from-pi` at the user's discretion.

4. **Documentation updates**:
   - `CLAUDE.md` — the "Three classes of file on the Pi to be aware of when syncing" section becomes four classes. Add:
     - **Live Klipper state files** — Klipper rewrites these continuously via `[save_variables]`. Pi is canonical. `/deploy-to-pi` excludes them; `/sync-from-pi` pulls them as backups. Today this is just `mmu/mmu_vars.cfg`.
   - `.claude/skills/deploy-to-pi/SKILL.md` — add a section documenting the exclusion + drift-summary behavior, plus the recovery procedure.

### Recovery procedure (documented, no tooling)

If the Pi's `mmu_vars.cfg` is corrupted or deleted (rare):

```sh
scp config/mmu/mmu_vars.cfg pi@mainsailos.local:~/printer_data/config/mmu/mmu_vars.cfg
ssh pi@mainsailos.local 'curl -X POST http://localhost:7125/printer/restart'
```

Then re-run any per-gate calibrations that have happened since the repo snapshot was last refreshed.

### Edge cases

| Case | Behavior |
|---|---|
| First-time deploy on a fresh Pi without the file | rsync skips the file; HH creates it on first `[save_variables]` call. Klipper will print a warning at startup if no save_variables file exists; not a fatal error. |
| Pi's file present but unreadable (permissions) | md5 fails on Pi side; deploy script falls back to printing `==> mmu_vars.cfg: Pi-managed state, deploy skipped (couldn't read Pi version)`. Deploy still proceeds. |
| Repo's file present but unreadable (local permissions) | md5 fails on local side; deploy script prints `==> mmu_vars.cfg: deploy skipped (couldn't read repo version)`. Deploy still proceeds. |
| `--dry-run` mode | Drift check runs, drift summary printed. No mutation. |
| CI | Doesn't deploy; not affected. Klippy parse still validates the repo's snapshot as valid Klipper syntax. |
| User deletes `config/mmu/mmu_vars.cfg` from repo | Subsequent `/sync-from-pi` re-creates it. Deploy script sees no repo copy; prints `==> mmu_vars.cfg: no repo snapshot present. Deploy skipped. Run /sync-from-pi to create one.` |

### Acceptance criteria

- `/deploy-to-pi` never overwrites the Pi's `mmu_vars.cfg`. Verified by md5 comparison of Pi's file before/after a deploy that touched non-mmu files.
- `/sync-from-pi` still pulls `mmu_vars.cfg` correctly (no regression).
- Drift summary line appears on every deploy, accurate to the actual md5 comparison.
- `--dry-run` shows what would happen, including the drift summary, without mutating anything.
- CLAUDE.md and the deploy-to-pi skill doc reflect the new behavior.

### Out of scope (explicitly NOT in this design)

- Automatic `/sync-from-pi` invocation when drift detected (would push toward "perfunctory acknowledgment that doesn't actually inform"). User decides when to refresh the backup.
- Periodic cron-based snapshotting. Could be added later if drift visibility proves insufficient; not needed for MVP.
- Tooling for the recovery procedure (rare enough to be a manual `scp`).
- Touching the `mmu/base/*.cfg` symlinks-on-Pi (different mechanism, different bug, different file class).

## Implementation

Single PR. Estimated touch:

- `scripts/deploy_to_pi.sh`: ~20 lines added (drift detection + summary + exclude)
- `scripts/sync_from_pi.sh`: no change
- `CLAUDE.md`: 1 paragraph added to the "classes of file" section
- `.claude/skills/deploy-to-pi/SKILL.md`: 1 paragraph added
- Tests: a pytest case verifying the drift detection logic if it lives in a Python helper, OR a bash test if the logic is inline (the existing deploy script is bash, so likely the latter)

Pre-push review per the established discipline (code-reviewer for the deploy script, comment-analyzer for the doc updates).

## References

- [#69](https://github.com/bjdeng/voron-2-611/issues/69) — the bug
- [PR #68](https://github.com/bjdeng/voron-2-611/pull/68) — `fix(deploy): self-cleaning rsync with --delete` — context for the existing exclusion mechanism in the script
- `scripts/deploy_to_pi.sh` — existing SAVE_CONFIG splice pattern at lines ~168-235 is the model for "Pi is canonical for this content"; this design extends the same principle to `mmu_vars.cfg` at file scope instead of block scope.
- Klipper docs: `[save_variables]` mechanism — `vendor/klipper/docs/Config_Reference.md` (search "save_variables")
- Happy Hare wiki: per-gate calibration variables live in `mmu_vars.cfg` via `[save_variables]`.
