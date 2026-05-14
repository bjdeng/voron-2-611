# deploy-to-pi — sync repo to Pi after merge to main

**Status:** spec
**Date:** 2026-05-14
**Owner:** Ben

## Problem

Today the repo is the canonical source for Klipper config but there is no automated way to push merged changes to the Pi. Each merge to `main` creates drift until someone manually runs `scp` or `rsync`. The drift accumulates silently — you can be three PRs ahead in repo while the printer still runs the pre-merge config.

The reverse direction (Pi → repo) is already handled by the `sync-from-pi` skill. The forward direction is missing.

## Goal

A single command — `/deploy-to-pi` — that takes the current `origin/main` and applies it to the Pi safely: refuses if anything is unsafe, shows the diff, classifies the restart impact, and verifies Klipper comes back ready. Closes the loop on every cleanup PR with one keystroke.

Out of scope: automated trigger on merge (that's a future GH Action wrapping the same script). Out of scope for v1: non-Klipper configs (`moonraker.conf`, `crowsnest.conf`, `sonar.conf`).

## Architecture

A skill at `~/.claude/skills/deploy-to-pi/SKILL.md` wraps a Python script at `scripts/deploy_to_pi.py`. The skill provides the conversational surface (preconditions, diff, confirmation, restart classification reasoning). The script encodes the mechanical work (file collection, SAVE_CONFIG splice, scp, Moonraker calls) and is pytest-testable. The future GH Action invokes the script directly with `--yes`.

Mirror of the `sync-from-pi` skill shape. Same pattern, opposite direction.

## Preconditions

All gates must pass before any file touches the Pi. Each gate is a hard fail with a clear error message; the skill aborts and tells the user what to fix.

1. **Local repo clean.** `git status --porcelain` empty. On branch `main`. Fast-forwarded to `origin/main`.
2. **CI green on HEAD.** `gh run list --branch main --commit $(git rev-parse HEAD) --status success --limit 1` returns a run. The `Klippy parse + smoke gcode` job being `skipped` counts as pass until Open Investigation #7 (eddy migration) re-enables it — flagged in skill output so the user knows.
3. **Pi reachable.** `curl http://mainsailos.local:7125/printer/info` returns 200 and parses.
4. **Printer idle.** Moonraker reports `print_stats.state == "standby"`. Not `printing`, `paused`, `error`, or `cancelled` mid-cooldown.
5. **Pi `printer.cfg` body matches `origin/main`.** Body = everything above the `#*# <---------------------- SAVE_CONFIG ---------------------->` marker. If diverged → abort with: "Pi has uncommitted local edits. Run `sync-from-pi` first to capture them, then re-run `deploy-to-pi`."

## File scope (v1)

Klipper configs only — files reachable from `printer.cfg` via `[include]`:
- `printer.cfg`, `eddy.cfg`, `btt-ebb-sb-usb-v1.0.cfg`, `mainsail.cfg`, `timelapse.cfg`
- `macros/*.cfg`
- `mmu/base/*.cfg`, `mmu/optional/*.cfg`, `mmu/addons/*.cfg`, `mmu/mmu_vars.cfg`

**Symlink carve-out.** Before any scp, the script runs `ssh pi 'test -L <path>'` for each file. If the file is a symlink on the Pi (so: `mmu/base/*`, `mainsail.cfg`, `timelapse.cfg`), it is **skipped with a warning**: "this file is symlinked from `<third-party-repo>` on the Pi — push the change to that repo and re-run its install.sh, do not overwrite the symlink." Repo edits to symlinked files are a code smell anyway; the warning makes it visible.

Out of scope for v1: `moonraker.conf`, `crowsnest.conf`, `sonar.conf`, `firmware/*`. These need different restart semantics (Moonraker service, Crowsnest daemon, MCU re-flash) and rarely change. Manual handling until v2.

## printer.cfg splice

Special handling because the Pi owns the SAVE_CONFIG block at the bottom of `printer.cfg`.

1. `ssh pi 'cat ~/printer_data/config/printer.cfg'` → save Pi's full file in memory.
2. Find Pi's SAVE_CONFIG marker line. Everything from that line through EOF is Pi-owned and must survive.
3. Read repo's `printer.cfg`. Find its SAVE_CONFIG marker (if any). Everything above is the repo's authoritative body.
4. Build the deploy file: `<repo body> + <Pi tail>`. If repo has no SAVE_CONFIG marker (just-initialized repo), append Pi's tail as-is.
5. scp the spliced result to the Pi.

Klipper's own `printer-YYYYMMDD_HHMMSS.cfg` auto-backup runs on the Pi at parse-time, so even on the worst-case parse failure, the prior file is recoverable. The script also tars the current Pi config dir to `/tmp/deploy-to-pi-last.tar.gz` on the laptop side before any scp, as one-deep local backup.

## Restart classification

The script computes the diff between Pi's current state and the files about to be deployed (after symlink-skip and SAVE_CONFIG splice). Classification rules in order:

| Rule (first match wins) | Restart |
|---|---|
| Every changed line begins with `#` or is whitespace (comments-only) | none |
| Diff touches any of: `[mcu`, `pin:`, `kinematics:`, `sensor_type:`, `step_pin`, `dir_pin`, `enable_pin`, `endstop_pin`, `serial:` | `FIRMWARE_RESTART` |
| Anything else | `RESTART` |

After scp, the script calls the matching Moonraker endpoint: `POST /printer/restart` or `POST /printer/firmware_restart`, or skips entirely. Then polls `GET /printer/info` every 1s for up to 30s waiting for `state == "ready"`. If Klipper goes to `error` instead, the script surfaces `state_message` and exits non-zero. The user then inspects via Mainsail or `~/printer_data/logs/klippy.log`.

## Skill conversation flow

```
> /deploy-to-pi
[skill: checking preconditions...]
✓ Repo clean, on main, up to date with origin (28cb8e6 → f8db90d)
✓ CI green (run #25870066714)
✓ Pi reachable at mainsailos.local
✓ Printer idle
✓ Pi printer.cfg body matches origin/main

Files to deploy:
  btt-ebb-sb-usb-v1.0.cfg (-44 lines, comments only)

Restart classification: none (comments-only change)

Confirm? [y/N]
> y

[skill: deploying...]
✓ Tarred current Pi config to /tmp/deploy-to-pi-last.tar.gz
✓ scp btt-ebb-sb-usb-v1.0.cfg
✓ Skip restart (no functional change)
✓ Printer still ready

Done.
```

## Failure modes

| Failure | Skill behavior |
|---|---|
| Precondition fails | Abort before any Pi write; tell user what to fix; exit non-zero |
| scp fails mid-flight | Some files landed, others did not. Exit non-zero. User runs `sync-from-pi` to capture Pi state, fixes, retries. No partial rollback — too complex for v1. |
| Klipper enters `error` after restart | Surface `state_message`; point at klippy.log; exit non-zero. Klipper's auto-backup on the Pi is the rollback path. |
| Pi unreachable during restart phase | Exit non-zero; file is deployed but restart pending. User restarts manually via Mainsail. |

## Script CLI

`scripts/deploy_to_pi.py` flags:

| Flag | Meaning |
|---|---|
| (no flag) | Run preconditions, print plan, prompt for confirmation, deploy. Default for interactive use. |
| `--yes` | Skip the confirmation prompt. Preconditions still apply. For use by the skill (after user confirms in conversation) and by the future GH Action. |
| `--dry-run` | Run preconditions, print plan, exit. Never touches Pi. For previewing what a deploy would do. |

Exit codes: `0` success, `1` precondition failed, `2` deploy failed mid-flight, `3` Klipper failed to come back ready.

## Testing

**Unit tests (pytest, in `tests/test_deploy_to_pi.py`):**
- SAVE_CONFIG splice: given a repo file and a Pi file, the spliced output equals expected.
- Restart classifier: a battery of synthetic diffs, each labelled with expected classification.
- Symlink detection: mock `ssh test -L` returning various states.
- Preconditions: mock Moonraker responses for each gate, verify abort/pass.

**Integration tests:**
- Spin up an HTTP server mock fixture that imitates Moonraker's relevant endpoints. Run the full script against it. No real Pi needed in CI.

**Manual end-to-end test:**
- After v1 is built, deploy a known-safe comments-only change (re-run on a `chore: strip` PR like #3) and verify the loop closes cleanly.

## CLAUDE.md update

Add to "Workflow & CI/CD":
> **After each merge to `main` with CI green:** run `/deploy-to-pi` to sync the Pi. The skill refuses if the printer is busy or the Pi has drift; it will tell you what to do next. (Until the skill ships: manual `scp` for the changed files.)

## Open questions

None blocking v1. Future v2 considerations:
- Should the skill auto-trigger on `git fetch && origin/main moved`? Probably no — too magical, can fire mid-print.
- Should `moonraker.conf` get v2 support? Add when we first need it; rare today.
- Should there be a `--dry-run` flag that shows the plan without touching the Pi? Yes, build it in v1 alongside `--yes`. Not worth a separate doc section.
