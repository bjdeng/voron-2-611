---
name: deploy-to-pi
description: Sync HEAD on main to ~/printer_data/config/ on pi@mainsailos.local over keyed SSH, preserving symlinked-third-party files and the Pi's current SAVE_CONFIG block, then call Moonraker's printer.restart (or firmware_restart if the diff touches MCU-impacting sections). Triggers the deploy half of the workflow that this repo is the canonical config for.
disable-model-invocation: true
---

## Why user-only (`disable-model-invocation: true`)

This skill mutates the printer. The user, not Claude, decides when to deploy. Claude can suggest "you should run /deploy-to-pi after this is merged" but cannot execute it on Claude's own initiative.

## Pre-flight

The skill refuses to deploy if any of these gates fail (it tells you what to fix):

- Must be on `main`.
- Working tree must be clean (no staged or unstaged changes).
- Local `main` must be in sync with `origin/main` (fast-forwarded; not ahead, not behind).
- Latest CI run on HEAD must be **green** (success). The `Klippy parse + smoke gcode` job is intentionally `skipped` until Open Investigation #7 ships — that counts as pass. An in-progress run is rejected with a clear message.
- Pi must be reachable via keyed SSH (`ssh pi@mainsailos.local` works without password).
- Moonraker must be running on the Pi (default API port 7125). Unreachable Moonraker is a hard fail — the restart step would fail anyway.
- Printer must be **idle** (`print_stats.state == "standby"`). Not `printing`, `paused`, etc.
- Pi's `printer.cfg` body (everything above the SAVE_CONFIG marker) must match `origin/main`. If they've diverged, run `sync-from-pi` first to capture Pi-side edits.

## What it does

1. **Sanity gate**: every pre-flight check above.
2. **Pull the Pi's current SAVE_CONFIG block** from `printer.cfg` so we don't overwrite it. SAVE_CONFIG is rewritten by Klipper on every calibration command and represents truth on the printer — the repo's copy is a snapshot. (Use `sync-from-pi` first if you want the repo to absorb the Pi's current SAVE_CONFIG.)
3. **Construct the deploy file set**: root-level `.cfg/.conf` files, `macros/*`, and `mmu/*` (minus the symlinked entries — see step 4). Explicitly excludes `vendor/`, `tests/`, `scripts/`, `docs/`, `memory/`, `firmware/`, `archive/`, `.github/`, `.claude/`, `Makefile`, `requirements.txt`, `.pre-commit-config.yaml`, `README.md`, `LICENSE`, `CLAUDE.md`, `.env`, `.gitignore`.
4. **Preserve symlinks on the Pi**: skip `mainsail.cfg`, `timelapse.cfg`, the symlinked entries under `mmu/base/`, and `mmu/optional/client_macros.cfg` + `mmu/optional/mmu_menu.cfg` — editing the repo's dereferenced copies of those would mutate the third-party install dirs on the Pi (`~/mainsail-config/`, `~/Happy-Hare/`, `~/moonraker-timelapse/`). Edits to those files belong in their respective upstream repos.
5. **rsync** the resolved file set to `pi@mainsailos.local:~/printer_data/config/`. The Pi's SAVE_CONFIG block (captured in step 2) is re-appended to the synced `printer.cfg`.
6. **Choose the restart kind** from the diff between the last deploy's marker (`.last-deploy-sha` on the Pi) and current HEAD: if every changed file matches `macros/`, `archive/`, or `printer.cfg`, call `printer.restart`. Otherwise call `printer.firmware_restart`. If no marker exists, or the marker is unrecognized, defaults to `firmware_restart` (the safe choice).
7. **Hit Moonraker** (`POST http://mainsailos.local:7125/printer/restart` or `/printer/firmware_restart`).

## Post-deploy

After the deploy + restart, the skill polls Moonraker (`GET /printer/info`) every second for up to 30 seconds, waiting for `state == "ready"`. If Klipper enters `error`, the skill surfaces the `state_message` and exits non-zero (rc=3). If the timeout elapses without a `ready` state, exits 3 with a pointer at klippy.log.

## What it does NOT do

- Does not push to GitHub. Run `git push` separately if needed.
- Does not flash MCU firmware. That's a separate procedure on the Pi (`make` in `~/klipper` after `cp firmware/<board>.config .config`, then `make flash`).
- Does not modify the Pi's `~/eddy-ng/`, `~/Happy-Hare/`, or `~/mainsail-config/` directories. To update those, use their respective `install.sh` scripts on the Pi.
- Does not deploy from a feat branch or dirty tree. Use the merge → main flow.

## How to run

```sh
scripts/deploy_to_pi.sh           # interactive: confirms before deploy
scripts/deploy_to_pi.sh --yes     # skip confirmation
scripts/deploy_to_pi.sh --dry-run # preconditions + plan only, no changes
```

Or, from a Claude session, invoke the skill explicitly: `/deploy-to-pi`.

Exit codes:
- `0` — success (deploy complete and Klipper is ready, or `--dry-run` finished cleanly)
- `1` — precondition failed (told you what to fix)
- `2` — deploy failed mid-flight (rsync/scp/marker-write/restart-call errored)
- `3` — Klipper failed to come back ready (poll timed out, or state went to `error`)

## Rollback

**Klipper's auto-backup is created during `SAVE_CONFIG`, not on parse failure or restart failure.** That means if you deploy a bad config that Klipper can't parse, there is no automatic `printer-YYYYMMDD_HHMMSS.cfg` from this deploy — only whatever the most recent prior `SAVE_CONFIG` left behind. **Take a manual safety copy before any risky deploy:**

```sh
ssh pi@mainsailos.local "cp ~/printer_data/config/printer.cfg ~/printer_data/config/printer.cfg.pre-deploy"
```

If a deploy goes bad, roll back via:

```sh
ssh pi@mainsailos.local
cd ~/printer_data/config
ls printer-2*.cfg printer.cfg.pre-deploy 2>/dev/null | tail -3   # find a good source
cp printer.cfg.pre-deploy printer.cfg                            # or the dated backup
curl -X POST http://localhost:7125/printer/restart
```

Alternatively, the `--dry-run` flag will run all preconditions and print the plan without touching the Pi — use it to spot-check anything risky.

## Related

- Companion skill: `sync-from-pi` (read direction).
- `CLAUDE.md` → "## Workflow & CI/CD" — describes the eventual GitHub Action that wraps this script.
- This script's existence + `sync-from-pi` together close the loop. The future deploy automation (Open Investigation #8 v2) is a GitHub Actions wrapper around `scripts/deploy_to_pi.sh`.
