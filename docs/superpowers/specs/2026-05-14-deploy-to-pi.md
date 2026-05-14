# deploy-to-pi — sync repo to Pi after merge to main

**Status:** spec (v2 — revised 2026-05-14 after discovering existing implementation)
**Date:** 2026-05-14
**Owner:** Ben

## Problem

The repo is the canonical source for Klipper config but there is no fully-gated way to push merged changes to the Pi. A bash script `scripts/deploy_to_pi.sh` exists (168 lines, committed in `6f96e12`) and handles ~70% of the work, but is missing several safety gates and has zero test coverage. Each merge to `main` therefore creates drift until someone manually runs the script — and the script can run even when CI is red or a print is in progress.

The reverse direction (Pi → repo) is handled by `scripts/sync_from_pi.sh` + `sync-from-pi` skill.

## Goal

Extend the existing `scripts/deploy_to_pi.sh` with the missing safety gates, add `--yes` / `--dry-run` flags, and add test coverage so we trust it for every-merge use. Single command — `/deploy-to-pi` — closes the loop on every cleanup PR with one keystroke and refuses if anything is unsafe.

Out of scope: automated trigger on merge (future GH Action wrapping the same script). Out of scope for v1: non-Klipper configs (`moonraker.conf`, `crowsnest.conf`, `sonar.conf`). Out of scope: porting bash to Python — the existing bash works and the test pattern (PATH-override fake binaries + pytest subprocess assertions) is sound.

## Architecture

Existing: skill at `.claude/skills/deploy-to-pi/SKILL.md` + bash script at `scripts/deploy_to_pi.sh`. The skill is user-only (`disable-model-invocation: true`) — Claude can suggest deployment, only the user invokes it. Future GH Action will wrap the script with `--yes`.

Mirror of the existing `sync-from-pi` skill shape. Same pattern, opposite direction.

## What's already implemented (in `scripts/deploy_to_pi.sh`)

- Pre-flight: on `main`, clean working tree, fast-forwarded to `origin/main`, SSH reachable, Moonraker reachable (currently warn-only — promote to hard-fail).
- SAVE_CONFIG splice via `sed`: extract Pi's `#*# <-+ SAVE_CONFIG -+>` tail, append to repo's body.
- File scope: rsync with explicit symlink-exclusion list (`mainsail.cfg`, `timelapse.cfg`, `mmu/base/<symlinked-list>`, `mmu/optional/*`).
- Restart classification: uses `.last-deploy-sha` marker on Pi + `git diff <marker>..main`. If diff is `macros/`, `archive/`, or `printer.cfg`-only → `RESTART`. Else → `FIRMWARE_RESTART`.
- Confirmation prompt before any write.
- Records new `.last-deploy-sha` marker on success.
- Calls Moonraker `POST /printer/<restart_kind>`.

## What's missing (this spec's work)

1. **CI green gate.** Query `gh run list --branch main --commit $(git rev-parse main) --json status,conclusion --limit 1` and verify a green run exists for HEAD. If the `Klippy parse + smoke gcode` job is `skipped` (per Open Investigation #7 until eddy migration), that counts as pass — flagged in output.
2. **Printer-idle gate.** `GET /printer/objects/query?print_stats` → require `state == "standby"`. Refuse if `printing`, `paused`, or any other state.
3. **Drift gate.** Compare Pi's `printer.cfg` body (everything above the SAVE_CONFIG marker) to repo's `printer.cfg` body. If diverged → abort: "Pi has uncommitted local edits. Run `sync-from-pi` first."
4. **Post-restart ready polling.** After calling Moonraker restart, poll `GET /printer/info` every 1s for up to 30s. Verify `state == "ready"`. If `error`, surface `state_message` and exit non-zero.
5. **`--yes` flag.** Skip confirmation prompt (for the skill's pre-confirmed flow and future GH Action).
6. **`--dry-run` flag.** Print preconditions, plan, expected restart kind; touch nothing on Pi.
7. **Promote Moonraker-reachable from warn to hard-fail.** Currently a `WARN` only; should refuse to proceed because the restart step at the end would fail anyway.
8. **Tests.** pytest-driven via subprocess + PATH-override fake binaries (`ssh`, `scp`, `curl`, `gh`, `git`) — same pattern as `tests/test_macro_refcheck.py`. Each gate has a "passes" and "fails-correctly" test.

## Script CLI

`scripts/deploy_to_pi.sh` flags:

| Flag | Meaning |
|---|---|
| (no flag) | Run preconditions, print plan, prompt for confirmation, deploy. Default for interactive use. |
| `--yes` | Skip the confirmation prompt. Preconditions still apply. For use by the skill (after user confirms in conversation) and by the future GH Action. |
| `--dry-run` | Run preconditions, print plan, exit. Never touches Pi. |

Exit codes: `0` success, `1` precondition failed, `2` deploy failed mid-flight, `3` Klipper failed to come back ready.

## Refactor for testability

The current script is sequential top-to-bottom in 168 lines. To enable per-gate testing without a refactor cathedral, extract each gate and side-effect step into a bash function in the same file:

```bash
check_on_main()           # exit 1 if not on main
check_tree_clean()        # exit 1 if dirty
check_in_sync_with_origin() # exit 1 if ahead/behind
check_ssh_reachable()     # exit 1 if SSH fails
check_moonraker_reachable() # exit 1 if curl fails (NEW: hard fail)
check_ci_green()          # NEW: exit 1 if CI not green for HEAD
check_printer_idle()      # NEW: exit 1 if not standby
check_no_pi_drift()       # NEW: exit 1 if Pi cfg diverges from origin/main
capture_save_config()
build_staged_printer_cfg()
choose_restart_kind()
show_plan_and_confirm()   # respects --yes and --dry-run
do_rsync()
update_deploy_marker()
trigger_restart()
wait_for_klipper_ready()  # NEW: poll, exit 3 on timeout/error
cleanup()

main() {
  parse_flags "$@"
  check_on_main
  check_tree_clean
  check_in_sync_with_origin
  check_ssh_reachable
  check_moonraker_reachable
  check_ci_green
  check_printer_idle
  check_no_pi_drift
  capture_save_config
  build_staged_printer_cfg
  choose_restart_kind
  show_plan_and_confirm
  [[ "$DRY_RUN" == 1 ]] && { cleanup; exit 0; }
  do_rsync
  update_deploy_marker
  trigger_restart
  wait_for_klipper_ready
  cleanup
}
```

This is a true refactor — no behavior change in the first commit, just rearranged. Subsequent commits add the new gates one at a time. Each new gate is a TDD loop: failing test → function → wire-into-main → test passes → commit.

## Test infrastructure

`tests/test_deploy_to_pi.py` runs the script in a temp dir with `PATH` rewired to a `tests/fake_bin/` directory of stub binaries. Each fake binary appends its args to a log file and emits canned stdout based on env vars set per-test:

```python
def run_script(env_overrides):
    fake_bin = tmp_path / "fake_bin"
    install_fakes(fake_bin)  # ssh, scp, curl, gh, git
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", **env_overrides}
    return subprocess.run(
        [str(REPO / "scripts" / "deploy_to_pi.sh")],
        cwd=tmp_repo,
        env=env,
        capture_output=True,
        text=True,
    )

def test_aborts_when_ci_red(tmp_path):
    r = run_script({"FAKE_GH_RESPONSE": "failure"})
    assert r.returncode == 1
    assert "CI not green" in r.stderr
```

Each new gate gets two tests: passes when condition met, fails when condition not met.

## Skill conversation flow

```
> /deploy-to-pi
[skill: invoking scripts/deploy_to_pi.sh]
✓ On main, clean, up to date with origin (28cb8e6 → f8db90d)
✓ SSH reachable
✓ Moonraker reachable
✓ CI green (run #25870066714)
✓ Printer idle (standby)
✓ Pi printer.cfg body matches origin/main

Files to deploy:
  btt-ebb-sb-usb-v1.0.cfg (-44 lines)
  ...
Restart kind: restart

Proceed? [y/N] y

✓ rsync complete
✓ printer.cfg uploaded with Pi's SAVE_CONFIG re-appended
✓ POST /printer/restart
✓ Klipper state=ready after 3s

Done.
```

## Failure modes

| Failure | Behavior | Exit code |
|---|---|---|
| Precondition fails | Abort before any Pi write; tell user what to fix | 1 |
| rsync/scp fails mid-flight | Some files landed, others did not. User runs `sync-from-pi` to capture Pi state, retries | 2 |
| Klipper enters `error` after restart | Surface `state_message`, point at klippy.log | 3 |
| `wait_for_klipper_ready` times out at 30s | Klipper alive but slow — exit non-zero, user inspects | 3 |

## CLAUDE.md update

Already landed on this branch (`feat/deploy-to-pi`): the post-merge deploy step is documented in "Workflow & CI/CD" with the manual-fallback note. When this PR merges, the manual-fallback parenthetical can be removed in a follow-up commit (or as part of the merge commit).

## Open questions

None blocking v1. Future v2 considerations:
- Should the skill auto-trigger on `git fetch && origin/main moved`? Probably no — too magical, can fire mid-print.
- Should `moonraker.conf` get v2 support? Add when first needed; rare today.
- Wrap as GH Action — separate spec, after v1 ships.
