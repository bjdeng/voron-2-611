---
name: sync-from-pi
description: Pull the live Klipper configs from pi@mainsailos.local into this repo's working tree. Preserves symlinked-third-party files (mainsail.cfg, mmu/base/*) as dereferenced files locally, excludes Klipper's auto-rotated printer-YYYYMMDD_*.cfg backups, and shows a unified diff before any write. Use when the Pi has drifted ahead of the repo — Mainsail edits, post-calibration SAVE_CONFIG rewrites, manual SSH tweaks. Do not use to push changes (that's deploy-to-pi).
---

## When to use

- After running a calibration on the printer (PID, input shaper, PA, Eddy probe) — Klipper rewrites the SAVE_CONFIG block at the bottom of `printer.cfg` and the repo is now stale.
- After someone (Ben or otherwise) used the Mainsail UI to edit a config — Mainsail saves directly to `~/printer_data/config/`.
- Before opening any PR that touches a `.cfg` file — to ensure the diff is against the actually-running config, not a stale snapshot.

## What it does

1. `ssh pi@mainsailos.local` (keyed; falls back to `.env` `PI_SSH_PASSWORD` if no key auth).
2. Tar everything under `~/printer_data/config/` except the timestamped backups, dereference symlinks (`tar -h`) so this repo has self-contained copies of `mainsail.cfg`, `timelapse.cfg`, and `mmu/base/*.cfg`.
3. Pull the tarball locally, extract to a staging dir.
4. Show `diff -r` against the current repo working tree.
5. Apply or abort based on user confirmation.

## How to run

```sh
scripts/sync_from_pi.sh
```

Pure shell — no Python deps required. Reads SSH host from the script (defaults to `pi@mainsailos.local`).

## What it does NOT do

- Does not commit. The user reviews the diff and commits manually with a `chore(sync):` semantic-prefixed message.
- Does not pull `vendor/` submodules (those are version-pinned by us, not by the Pi).
- Does not touch `~/printer_data/logs/`, `~/printer_data/gcodes/`, `~/printer_data/database/`.
- Does not pull `~/klipper/`, `~/Happy-Hare/`, `~/eddy-ng/` — those are tracked as submodules; bump deliberately with `git submodule update --remote`.
- Does not pull Klipper's `printer-YYYYMMDD_*.cfg` rotation backups (excluded by `--exclude='printer-2*.cfg'`).

## Related

- `scripts/sync_from_pi.sh` — the actual implementation.
- `CLAUDE.md` → "How to help me" → step 6 (this repo is canonical; Pi is the working copy).
- `memory/pi-ssh-access.md` (in user memory) — host + auth notes.
- Companion skill: `deploy-to-pi` (user-only) for the reverse direction.
