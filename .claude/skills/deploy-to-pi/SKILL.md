---
name: deploy-to-pi
description: Sync HEAD on main to ~/printer_data/config/ on pi@mainsailos.local over keyed SSH, preserving symlinked-third-party files and the Pi's current SAVE_CONFIG block, then call Moonraker's printer.restart (or firmware_restart if the diff touches MCU-impacting sections). Triggers the deploy half of the workflow that this repo is the canonical config for.
disable-model-invocation: true
---

## Why user-only (`disable-model-invocation: true`)

This skill mutates the printer. The user, not Claude, decides when to deploy. Claude can suggest "you should run /deploy-to-pi after this is merged" but cannot execute it on Claude's own initiative.

## Pre-flight

- Must be on `main` with a clean working tree and up-to-date with `origin/main`. The skill refuses to deploy from a feat branch or a dirty working tree.
- Pi must be reachable via keyed SSH (`ssh pi@mainsailos.local` works without password). The `.env` fallback (`pi:raspberry`) is supported but flagged with a warning.
- Moonraker must be running on the Pi (default API port 7125).

## What it does

1. **Sanity gate**: verify branch is main, working tree clean, `git fetch` shows no remote ahead.
2. **Pull the Pi's current SAVE_CONFIG block** from `printer.cfg` so we don't overwrite it. SAVE_CONFIG is rewritten by Klipper on every calibration command and represents truth on the printer — the repo's copy is a snapshot. (Use [sync-from-pi] first if you want the repo to absorb the Pi's current SAVE_CONFIG.)
3. **Construct the deploy file set**: everything tracked in git that lives under the repo's "real config" surface — root-level `.cfg/.conf` files, `macros/*`, `mmu/*`, `archive/*`. Explicitly excludes `vendor/`, `tests/`, `scripts/`, `docs/`, `memory/`, `firmware/`, `.github/`, `.claude/`, `Makefile`, `requirements.txt`, `.pre-commit-config.yaml`, `README.md`, `LICENSE`, `CLAUDE.md`, `.env`, `.gitignore`.
4. **Preserve symlinks on the Pi**: skip `mainsail.cfg`, `timelapse.cfg`, and the symlinked entries under `mmu/base/` — editing the repo's dereferenced copies of those would mutate the third-party install dirs on the Pi (`~/mainsail-config/`, `~/Happy-Hare/`, `~/moonraker-timelapse/`). Edits to those files belong in their respective upstream repos.
5. **rsync** the resolved file set to `pi@mainsailos.local:~/printer_data/config/`. The Pi's SAVE_CONFIG block (captured in step 2) is re-appended to the synced `printer.cfg`.
6. **Choose the restart kind**: parse the diff. If any change is in a printer-side file outside `macros/`, `archive/`, the SAVE_CONFIG block, or pure documentation, call `printer.firmware_restart` via the Moonraker API. Otherwise call `printer.restart`. Heuristic — see the script for the exact rules.
7. **Hit Moonraker** (`POST http://mainsailos.local:7125/printer/restart` or `/printer/firmware_restart`). Report success/failure.

## What it does NOT do

- Does not push to GitHub. Run `git push` separately if needed.
- Does not flash MCU firmware. That's a separate procedure on the Pi (`make` in `~/klipper` after `cp firmware/<board>.config .config`, then `make flash`).
- Does not modify the Pi's `~/eddy-ng/`, `~/Happy-Hare/`, or `~/mainsail-config/` directories. To update those, use their respective `install.sh` scripts on the Pi.
- Does not deploy from a feat branch or dirty tree. Use the merge → main flow.

## How to run

```sh
scripts/deploy_to_pi.sh
```

Or, from a Claude session, invoke the skill explicitly: `/deploy-to-pi`.

## Rollback

Klipper auto-saves a backup of `printer.cfg` named `printer-YYYYMMDD_HHMMSS.cfg` in the same directory whenever the new file fails to parse or restart fails. To roll back:

```sh
ssh pi@mainsailos.local
cd ~/printer_data/config
ls printer-2*.cfg | tail -3  # find the most recent backup
cp <backup>.cfg printer.cfg
# Then via Moonraker:
curl -X POST http://localhost:7125/printer/restart
```

## Related

- Companion skill: `sync-from-pi` (read direction).
- `CLAUDE.md` → "## Workflow & CI/CD" — describes the eventual GitHub Action that wraps this script.
- This script's existence + `sync-from-pi` together close the loop. The future deploy automation is a GitHub Actions wrapper around `scripts/deploy_to_pi.sh`.
