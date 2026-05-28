# Deploy drift-gate hardening — design

**Date:** 2026-05-28
**Status:** approved (brainstorming)
**Scope:** `scripts/deploy_to_pi.sh` — make the Pi-side drift gate fail closed, auto-capture Pi-only edits before any overwrite, rework `--force` so it can't lose data, and log every deploy.

## Background

On 2026-05-28 a `deploy_to_pi` run silently reverted Ben's gate-entry sensor config: `[mmu_sensors]` `pre_gate_switch_pin_0..5` (wired to `mcu z`, edited only on the Pi, never committed) were overwritten with the repo's empty `^mmu:` template aliases, and the 6 pre-gate filament sensors stopped registering. The pins were recovered from `klippy.log` and committed in PR #121.

**RCA of why the drift gate didn't prevent it** (`check_no_pi_drift_all_files`, added in #106): the gate *would* detect such drift (Pi file hash ≠ last-deployed-marker hash) and refuse (`exit 1`). It failed to protect the edits because:

1. **`--force` blanket-overrides** the refusal (`deploy_to_pi.sh:349-353`).
2. **Six fail-open skip paths** silently `return 0` (proceed) when the gate can't verify Pi state: missing marker (`:252`, no warning), marker SHA not in git (`:256`), `git archive` failure (`:264`), no `config/` in snapshot (`:268`), no local hasher (`:285`), hash-enumeration failure (`:330`).
3. **No deploy log** — only `.last-deploy-sha` (overwritten each run), so the clobbering deploy couldn't be pinned afterward.
4. The gate can only **refuse**, never **preserve** — Pi-only edits stay fragile until manually committed.

## Goals

- The gate **fails closed**: refuse rather than silently proceed when it cannot verify Pi state.
- A deploy **never loses Pi-only edits** — they are captured to the repo before any overwrite, even under `--force`.
- Every deploy leaves an **audit trail** sufficient to diagnose a future incident.

## Non-goals

- Periodic/background sync automation (rejected in favor of synchronous pre-deploy capture).
- Changes to `sync_from_pi.sh` (the capture is targeted and self-contained in the deploy script).
- Auto-merging captured edits or auto-committing to `main` (capture lands on a review branch only).

## Best-practice alignment

The design brings the script to the safety bar of established tools, not a novel paradigm:
- **Fail-closed** = standard fail-safe default for destructive ops.
- **Refuse-to-overwrite-unseen-remote-changes** = `git push --force-with-lease` semantics (vs blind `--force`); drift detection mirrors Terraform `plan` / Ansible `--check`.
- **Capture-before-overwrite** = `rsync --backup` / a `git stash` safety branch.

## Design

### 1. Fail closed on can't-verify

The high-value `return 0` skip paths in `check_no_pi_drift_all_files` (and the marker-resolution skips in `check_no_pi_drift`) become a **refusal** unless `--force` is given. Concretely, when the gate cannot verify Pi state — marker missing, marker SHA not in git history, `git archive` failure, no `config/` in snapshot, or no local hasher — it prints a specific reason and `exit 1`.

- `--force` overrides each (proceeds with a logged warning).
- **No first-deploy exception**: a genuine first-ever deploy (no marker) also refuses and requires a one-time `--force`. Chosen for simplicity and strictness — a missing marker is indistinguishable from a lost/corrupt one, so both fail closed.
- **Exception — empty enumeration is NOT a refusal.** The "either hash enumeration came back empty" case stays a skip (proceed), unlike the others. It's the lowest-value conversion (a real Pi-side edit surfaces as a hash *mismatch* → drift, §2, not as empty output) and the highest-friction (empty `pi_hashes` is the normal state for tooling/tests that aren't exercising drift). Refusing on it gave no incident protection — the original clobber was a missing-marker + undetected-drift failure, both still caught — and broke the test harness across platforms (`git archive` snapshot emptiness varies). So this one branch reverts to skip-on-either-empty.

### 2. Auto-capture Pi drift before overwrite

When `check_no_pi_drift_all_files` finds drifted files (`drift_files`, computed at `:340-343`), the gate **captures them into the repo before doing anything else**, regardless of flags:

1. Create a capture branch `pi-drift-capture-<UTC-timestamp>` from current `HEAD`.
2. `scp` each drifted file from the Pi into the repo working tree at its `config/<path>`.
3. Commit them on the capture branch with a message naming the files and the deploy that triggered capture.
4. Return to the original branch.

The capture covers exactly the files the gate already identified as drifted — no broader pull. This guarantees the Pi edits exist in version control (on a branch) before any rsync overwrite can run.

### 3. `--force` reworked: capture always, force only gates proceed-vs-abort

Capture (§2) is **unconditional** on detected drift — `--force` does not skip it. `--force` only decides what happens *after* capture:

- **Without `--force`:** after capturing, **abort** (`exit 1`) with: "Pi edits captured to branch `pi-drift-capture-<ts>` — review/merge them, then re-deploy."
- **With `--force`:** after capturing, **proceed** with the deploy. The Pi is overwritten by the repo, but the captured branch preserves the edits, so nothing is lost — only set aside for review.

Result: `--force` can no longer cause data loss; it can only let a deploy continue past a refusal, with the Pi state safely captured first.

### 4. Deploy logging

Append one line per deploy to `~/printer_data/logs/deploy-to-pi.log` on the Pi (alongside `klippy.log`/`moonraker.log`, visible in Mainsail, `pi`-readable without sudo). Written at deploy completion (and on refusal/abort). Fields, tab- or space-delimited:

- ISO-8601 UTC timestamp
- deployed HEAD short SHA
- flags (`--yes` / `--force` / `--dry-run` / `--smoke`, as applicable)
- restart kind (`restart` / `firmware_restart` / `none`)
- drift outcome: `none` | `captured:<branch>` | `forced:<branch>`
- result: `success` | `refused:<reason>` | `failed:<stage>`

The log stays Pi-side (operational audit trail); the repo's `.last-deploy-sha` marker + git history remain the source of truth. `/sync-from-pi` does not pull it.

## Control flow (revised gate sequence)

1. Resolve marker. Cannot verify → **refuse** unless `--force`. *(§1)*
2. Compute `drift_files` (Pi vs marker snapshot) — existing logic.
3. If `drift_files` non-empty → **capture** them to `pi-drift-capture-<ts>` branch + commit. *(§2, always)*
   - No `--force` → **abort** ("captured to <branch>; review, then re-deploy"). *(§3)*
   - `--force` → proceed. *(§3)*
4. Proceed with rsync + restart (unchanged).
5. Log the outcome. *(§4)*

## Testing

Extend `tests/test_deploy_to_pi.py` (PATH-override fakes for ssh/scp/git, env-driven). New cases:

- Unverifiable marker (missing / not-in-git / archive-fail) **without** `--force` → `exit 1`, no rsync, log line `refused:<reason>`.
- Same **with** `--force` → proceeds; log records `--force`.
- Drift detected, **no** `--force` → capture branch created + committed (assert via fake `git`/`scp` invocation log), deploy aborts, log `captured:<branch>`.
- Drift detected, **`--force`** → capture happens AND rsync proceeds, log `forced:<branch>`.
- Clean state → no capture, deploy proceeds, log `none` + `success`.

Live behaviors not unit-testable (actual scp content, real branch contents, real restart) are covered by a manual smoke deploy after implementation.

## Files touched

- `scripts/deploy_to_pi.sh` — fail-closed skips (§1), capture routine (§2), `--force` semantics (§3), logging (§4).
- `tests/test_deploy_to_pi.py` — new gate-decision cases.
- `.claude/skills/deploy-to-pi/SKILL.md` — document the new fail-closed behavior, capture branches, reworked `--force`, and the deploy log.
