# Chopper-Resonance-Tuner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install MRX8024/chopper-resonance-tuner on the Pi and run a measurement-driven tuning session for X/Y motors, with a conditional follow-up session for Z motors. Codify winning chopper register values in motion.cfg.

**Architecture:** Two sequential sessions. Session 1 installs CRT (Pi-only, no submodule), captures pre-tuning baseline, sweeps + iteratively narrows TMC2209 chopper registers (TBL/TOFF/HSTRT/HEND) for X then Y, validates with TEST_SPEED + ear rating, PRs codified values. Session 2 (conditional on Session 1 yielding measurable improvement) repeats for the 4 Z motors, treating them as one axis since the hardware is identical and they move together.

**Tech Stack:** Klipper extension (`chopper_tune.py` symlinked into klippy/extras), Moonraker (gcode/script API + update_manager), LIS2DW accelerometer (toolhead-mounted, already configured for input shaper), GitHub Actions CI (workflow at `.github/workflows/ci.yml`), `scripts/deploy_to_pi.sh` deploy skill.

**Source spec:** [`docs/superpowers/specs/2026-05-20-chopper-resonance-tuner-design.md`](../specs/2026-05-20-chopper-resonance-tuner-design.md)

**Predecessor:** [microsteps-128-to-64 + TMC Autotune (issue #24)](../plans/2026-05-20-microsteps-and-tmc-autotune.md). Current printer state post-#97: noise 3/5 (original baseline), microsteps=128 + interpolate=True + autotune-aligned (Z `tuning_goal:performance`, X/Y `extra_hysteresis:2`).

**Operator division:** Claude drives the `CHOPPER_TUNE` macro sequence + interprets vibration plots + decides parameter ranges. Ben provides ambient supervision + final ear rating + accelerometer care (no remounting — stays on toolhead). Plan assumes Claude is online and the Pi is reachable when the engineer runs through it.

---

## File Structure

**Files modified by Session 1 (X/Y):**
- `config/system.cfg` — add `[chopper_tune]` section (or `[include chopper_tune.cfg]`) plus a comment block mirroring the existing shaketune banner
- `config/moonraker.conf` — add `[update_manager chopper_tune]` block
- `config/motion.cfg` — either add `[delayed_gcode _apply_crt_chopper]` (option 2 in spec § Coexistence) OR add `driver_TBL/driver_TOFF/driver_HSTRT/driver_HEND` to `[tmc2209 stepper_x]` + `[tmc2209 stepper_y]` (option 3). Decision made post-measurement
- `.gitignore` — add `config/adxl_results/` exclusion
- `.github/workflows/ci.yml` — add "Strip [chopper_tune] from system.cfg" step BEFORE the existing shaketune strip step, mirroring its sed pattern
- `memory/tuning-log.md` — append per-stepper entry with date, pre/post register values, pre/post noise rating, screenshot reference
- `CLAUDE.md` — add a line to the Vendor / submodules section or to a "Pi-installed-only" note mentioning chopper-resonance-tuner

**Files modified by Session 2 (Z, conditional):**
- `config/motion.cfg` — same mechanism as Session 1 but for the 4 Z stepper blocks
- `memory/tuning-log.md` — append Z session entry

**Pi-side actions (not in repo):**
- `~/chopper-resonance-tuner/` — created by upstream install.sh
- `~/klipper/klippy/extras/chopper_tune.py` (+ any helper modules) — symlinks created by install.sh
- `~/printer_data/config/adxl_results/` — created by install.sh; per-run CSV/PNG outputs
- TMC register writes via `SET_TMC_FIELD` during tuning (runtime only until codified)

---

# Session 1: X/Y tuning

**Goal of session:** install CRT, capture baseline, tune X and Y motors via measurement-driven sweep + narrow, validate, codify winning values in repo via PR + deploy.

**Expected duration:** ~2.5 hours total (15 min pre-flight + 90 min tuning + 10 min validation + 30 min post-session + buffer).

**Pre-session checklist (before starting Task S1-1):**
- [ ] Pi reachable: `ssh pi@mainsailos.local "echo ok"` returns `ok`
- [ ] Printer idle: `curl -sS 'http://mainsailos.local:7125/printer/objects/query?print_stats' | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status']['print_stats']['state'])"` returns `standby`
- [ ] On `main` with clean working tree: `git status` shows nothing
- [ ] LIS2DW reachable: `curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"ACCELEROMETER_QUERY"}' http://mainsailos.local:7125/printer/gcode/script` returns `{"result":"ok"}`
- [ ] Belts not obviously loose (visual + finger pluck — proper tension measurement is out of scope here but mechanical state is a confound)

### Task S1-1: Install CRT on the Pi

**Files:** None (Pi-side install only — repo-side config additions in S1-2).

- [ ] **Step 1: SSH and run upstream install.sh**

```bash
PI_PW=$(grep '^PI_SSH_PASSWORD=' /Users/ben/code/voron-2-611/.env | cut -d= -f2-)
ssh -tt pi@mainsailos.local "echo '$PI_PW' | sudo -S -v && cd ~ && git clone https://github.com/MRX8024/chopper-resonance-tuner && bash ~/chopper-resonance-tuner/install.sh"
```

Watch for: `Cloning into 'chopper-resonance-tuner'...`, `Symlink created` (or similar), Klipper restart.

Expected exit: 0.

- [ ] **Step 2: Verify the symlink(s) and output dir**

```bash
ssh pi@mainsailos.local "ls -la ~/klipper/klippy/extras/ | grep chopper && ls -d ~/printer_data/config/adxl_results"
```

Expected:
- One or more `chopper_*.py -> ../../../chopper-resonance-tuner/...` symlinks
- `~/printer_data/config/adxl_results` directory exists

- [ ] **Step 3: Verify Klipper came back ready**

```bash
curl -sS 'http://mainsailos.local:7125/printer/objects/query?webhooks' | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status']['webhooks']['state'])"
```

Expected: `ready`.

If anything is wrong here, abort the plan — fix Pi-side issues before continuing. Rollback: `ssh pi@mainsailos.local "rm -rf ~/chopper-resonance-tuner ~/klipper/klippy/extras/chopper_*.py && sudo systemctl restart klipper"`.

### Task S1-2: Add the chopper_tune config + update_manager + gitignore + CI strip step on a feature branch

**Files:**
- Create: worktree branch `chore/install-chopper-resonance-tuner`
- Modify: `config/system.cfg` (add `[chopper_tune]` section with banner)
- Modify: `config/moonraker.conf` (add update_manager block)
- Modify: `.gitignore` (add `config/adxl_results/`)
- Modify: `.github/workflows/ci.yml` (add strip step)

- [ ] **Step 1: Create worktree + rename branch**

```bash
# In the parent dir, use the EnterWorktree tool (or):
cd /Users/ben/code/voron-2-611
git worktree add .claude/worktrees/install-chopper-resonance-tuner -b worktree-install-chopper-resonance-tuner
cd .claude/worktrees/install-chopper-resonance-tuner
git branch -m chore/install-chopper-resonance-tuner
```

If using Claude Code's `EnterWorktree` tool, name it `install-chopper-resonance-tuner` and rename the branch after entering.

- [ ] **Step 2: Add `[chopper_tune]` section to `config/system.cfg`**

Find the existing shaketune banner and add the chopper_tune banner immediately above it:

```ini
#####################################################################
#   Chopper-Resonance-Tuner (MRX8024)
#####################################################################
# Third-party Klipper extension installed at ~/chopper-resonance-tuner
# (symlinked into ~/klipper/klippy/extras/chopper_tune.py — same install
# pattern as klippain-shaketune, Happy-Hare, eddy-ng; will need re-running
# install.sh after Klipper version bumps). Provides CHOPPER_TUNE macro
# for empirical TMC chopper register tuning via accelerometer feedback.
# Defaults are fine; an empty section is enough to load the extension.
# Upstream: https://github.com/MRX8024/chopper-resonance-tuner
[chopper_tune]
```

Confirm against the actual install.sh output — if it expects a different section name or required keys, match that. Klippy parse failure on deploy will catch the mismatch.

- [ ] **Step 3: Add `[update_manager chopper_tune]` to `config/moonraker.conf`**

After the existing `[update_manager TMC_Autotune]` block (or near other update_manager git_repo entries):

```ini
[update_manager chopper_tune]
type: git_repo
path: ~/chopper-resonance-tuner
origin: https://github.com/MRX8024/chopper-resonance-tuner.git
primary_branch: main
managed_services: klipper
```

- [ ] **Step 4: Add `.gitignore` entry**

Append to `.gitignore`:

```
# Per-run output from chopper-resonance-tuner (~700 MB possible)
config/adxl_results/
```

- [ ] **Step 5: Add CI strip step to `.github/workflows/ci.yml`**

Find this existing block:

```yaml
      - name: Strip [shaketune] from system.cfg (klippain-shaketune not vendored yet)
```

Insert this NEW step IMMEDIATELY BEFORE it:

```yaml
      - name: Strip [chopper_tune] from system.cfg (chopper-resonance-tuner not vendored)
        # chopper-resonance-tuner lives at ~/chopper-resonance-tuner on the Pi
        # with a symlink into ~/klipper/klippy/extras/chopper_tune.py. Not
        # vendored — this strip step is the CI counterpart, mirroring the
        # shaketune strip pattern.
        shell: bash
        run: |
          set -euo pipefail
          sed -i '/^#   Chopper-Resonance-Tuner (MRX8024)$/,/^\[chopper_tune\]$/d' config/system.cfg
          # Also drop any blank line that section was followed by
          sed -i -e :a -e '/^[#[:space:]]*$/{$d;N;ba' -e '}' config/system.cfg
          echo "Post-strip search for chopper_tune in system.cfg:"
          grep -n chopper_tune config/system.cfg || echo "(clean — no references)"
```

If the actual section name from the install.sh differs, adjust both the banner-matching pattern and the closing-`[chopper_tune]` anchor to match.

- [ ] **Step 6: Local CI**

```bash
make refcheck && make test-py
```

Expected: refcheck passes, all 91 tests pass, pre-commit hooks pass.

- [ ] **Step 7: Commit**

```bash
git add config/system.cfg config/moonraker.conf .gitignore .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
chore: install chopper-resonance-tuner — Pi-only, repo-side config

Pi-only install (no vendor submodule, matches klippain-shaketune pattern).
Repo gains the [chopper_tune] section, [update_manager] block, gitignore
for per-run adxl_results output, and CI strip step matching the
shaketune-strip pattern.

Implements Session 1 Task S1-2 of the CRT plan
(docs/superpowers/plans/2026-05-20-chopper-resonance-tuner.md).

Restart impact: RESTART (Klipper picks up the new [chopper_tune] section
on next start; moonraker reload picks up [update_manager]).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task S1-3: Push branch, open PR, merge after CI

**Files:** None (git/GitHub operations).

- [ ] **Step 1: Push branch**

```bash
git push -u origin chore/install-chopper-resonance-tuner
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "chore: install chopper-resonance-tuner (Pi-only, repo-side config)" --body "$(cat <<'EOF'
## Summary
Repo-side companion to the Pi-side install of MRX8024/chopper-resonance-tuner. Session 1 Task S1-2 of the CRT plan (`docs/superpowers/plans/2026-05-20-chopper-resonance-tuner.md`).

## Changes
- `config/system.cfg`: `[chopper_tune]` section with banner comment block
- `config/moonraker.conf`: `[update_manager chopper_tune]` block
- `.gitignore`: exclude `config/adxl_results/`
- `.github/workflows/ci.yml`: strip step matching the shaketune pattern

## Restart impact
RESTART (Klipper picks up the new section).

## Test plan
- [x] Local CI green (refcheck + pytest + pre-commit)
- [x] Pi-side install.sh already ran (Task S1-1); Klipper came back ready
- [ ] CI strip step matches the upstream banner name
- [ ] Post-deploy: Klipper boots clean, [chopper_tune] visible in printer.objects

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch CI**

```bash
gh pr checks <PR#> --watch
```

If `Klippy parse + MCU load` fails with "Section 'chopper_tune' is not a valid config section", the CI strip step didn't match the banner — go back to Task S1-2 Step 5 and fix the pattern.

- [ ] **Step 4: Squash-merge + delete branch**

```bash
gh pr merge <PR#> --squash --delete-branch
```

Returns to main worktree (`gh pr merge` may error trying to checkout main from inside the worktree — that's cosmetic, the merge succeeds server-side. Use `ExitWorktree` tool with `action: remove`).

- [ ] **Step 5: Wait for post-merge CI on main**

```bash
until gh run list --branch main --workflow ci.yml --limit 1 --json status -q '.[0].status' | grep -q completed; do sleep 15; done
gh run list --branch main --workflow ci.yml --limit 1 --json conclusion -q '.[0].conclusion'
```

Expected: `success`.

### Task S1-4: Deploy

**Files:** None (uses `scripts/deploy_to_pi.sh`).

- [ ] **Step 1: Pull main + deploy**

```bash
cd /Users/ben/code/voron-2-611
git checkout main && git pull --ff-only
scripts/deploy_to_pi.sh --yes
```

Expected end-of-output: `==> Deploy complete. Verify printer state in Mainsail.` and `state=ready`.

- [ ] **Step 2: Confirm [chopper_tune] is loaded**

```bash
ssh pi@mainsailos.local "grep -E 'chopper_tune|chopper_tune.py' ~/printer_data/logs/klippy.log | tail -5"
```

Expected: lines indicating the section was loaded; no errors.

### Task S1-5: Pre-tuning baseline

**Files:** None (observational data collection).

- [ ] **Step 1: Home + QGL**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' http://mainsailos.local:7125/printer/gcode/script
```

If `Unable to detect tap: insufficient lift` (known eddy first-tap flake), retry the same command once.

Verify:
```bash
curl -sS 'http://mainsailos.local:7125/printer/objects/query?toolhead&quad_gantry_level' | python3 -c "import sys,json; r=json.loads(sys.stdin.read())['result']['status']; print('homed_axes:', r['toolhead']['homed_axes'], 'qgl_applied:', r.get('quad_gantry_level', {}).get('applied'))"
```

Expected: `homed_axes: xyz qgl_applied: True`.

- [ ] **Step 2: Snapshot pre-tuning DUMP_TMC for X and Y**

```bash
for s in stepper_x stepper_y; do
  curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"DUMP_TMC STEPPER=$s\"}" http://mainsailos.local:7125/printer/gcode/script >/dev/null
done
sleep 1
curl -sS 'http://mainsailos.local:7125/server/gcode_store?count=400' | python3 -c "
import sys, json
ls = json.loads(sys.stdin.read())['result']['gcode_store']
for s in ['stepper_x','stepper_y']:
    for i, l in enumerate(ls):
        if l['type'] == 'command' and f'DUMP_TMC STEPPER={s}' in l['message']:
            for j in range(i, min(i+30, len(ls))):
                if 'CHOPCONF' in ls[j]['message']:
                    print(f'=== {s} ===')
                    print(ls[j]['message'])
                    break
" > /tmp/pre-tune-dump-tmc.txt
cat /tmp/pre-tune-dump-tmc.txt
```

Save this output — it's the **rollback baseline**. Copy it into the session scratch note (or the eventual tuning-log entry).

- [ ] **Step 3: Capture autotune's currently-applied chopper values from klippy.log**

```bash
ssh pi@mainsailos.local "grep -E 'autotune_tmc set stepper_(x|y) (toff|tbl|hstrt|hend)' ~/printer_data/logs/klippy.log | tail -16" | tee /tmp/pre-tune-autotune-values.txt
```

Save this output — it's what we compare CRT's results against in Task S1-8 (coexistence decision).

- [ ] **Step 4: Baseline TEST_SPEED ×2**

```bash
for i in 1 2; do
  echo "=== Baseline run $i ==="
  curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"TEST_SPEED"}' --max-time 600 http://mainsailos.local:7125/printer/gcode/script
done
```

Each call blocks until the macro completes.

- [ ] **Step 5: Pull TEST_SPEED results + record**

```bash
curl -sS 'http://mainsailos.local:7125/server/gcode_store?count=400' | python3 -c "
import sys, json
ls = json.loads(sys.stdin.read())['result']['gcode_store']
starts = [i for i, l in enumerate(ls) if 'TEST_SPEED' in l['message'] and 'starting' in l['message']]
for n, idx in enumerate(starts[-2:], 1):
    print(f'=== Run {n} ===')
    for l in ls[idx:idx+30]:
        msg = l['message']
        if any(k in msg for k in ('TEST_SPEED','mcu:','Result:','estimate contact')):
            print(msg[:280])
    print()
" | tee /tmp/baseline-test-speed.txt
```

Verify: 0 X/Y missed steps (same `stepper_x` and `stepper_y` mcu count before/after iterations); Z probe diff < 0.1 mm.

Ben gives subjective noise rating (1–5 scale). Record in the session scratch note. Pre-tuning baseline = 3/5 expected (matches state post-#97).

### Task S1-6: Tune stepper_x

**Files:** None (runtime tuning — register state only).

- [ ] **Step 1: Run vibration sweep on X**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"CHOPPER_TUNE FIND_VIBRATIONS=1 STEPPER=stepper_x MIN_SPEED=20 MAX_SPEED=250"}' --max-time 2400 http://mainsailos.local:7125/printer/gcode/script
```

Wait ~20–30 min. The macro drives stepper_x through speeds 20–250 mm/s and records LIS2DW vibration data. Output lands in `~/printer_data/config/adxl_results/`.

If the macro syntax differs from what upstream actually exposes (check `CHOPPER_TUNE HELP` or the upstream wiki), adjust here. The wiki at `https://github.com/MRX8024/chopper-resonance-tuner/blob/main/wiki/chopper_tuning_guide_english.md` is the source of truth.

- [ ] **Step 2: Fetch the output**

```bash
ssh pi@mainsailos.local "ls -t ~/printer_data/config/adxl_results/ | head -5"
# Pick the most recent files (likely a CSV + PNG)
mkdir -p /tmp/crt-stepper_x-find
scp pi@mainsailos.local:~/printer_data/config/adxl_results/<filename>.png /tmp/crt-stepper_x-find/
scp pi@mainsailos.local:~/printer_data/config/adxl_results/<filename>.csv /tmp/crt-stepper_x-find/
```

- [ ] **Step 3: Identify 1–3 worst-vibration speeds**

Claude opens the PNG via the SendUserFile tool (or just looks at the CSV) and identifies the peaks. Record the speeds in the session scratch note.

If the plot is flat (no clear peaks), CRT has nothing to tune for X — note that and move to stepper_y. The X chopper params are already at or near optimal.

- [ ] **Step 4: Run register sweep at each problem speed**

For each problem speed `<v>`:

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"CHOPPER_TUNE STEPPER=stepper_x MIN_SPEED=<v> MAX_SPEED=<v> TBL=0..3 TOFF=1..15 HSTRT=0..7 HEND=0..15\"}" --max-time 2400 http://mainsailos.local:7125/printer/gcode/script
```

Adjust the param-sweep syntax to match upstream's actual macro signature — the values above are the default ranges in the wiki guide; the actual `CHOPPER_TUNE` macro may take a slightly different invocation. Wait ~20–30 min per speed.

- [ ] **Step 5: Fetch + analyze heatmap, narrow ranges, iterate**

```bash
ssh pi@mainsailos.local "ls -t ~/printer_data/config/adxl_results/ | head -3"
scp pi@mainsailos.local:~/printer_data/config/adxl_results/<latest-png> /tmp/crt-stepper_x-tune/
```

Claude identifies the lowest-vibration register combination from the heatmap. If the optimum is at the edge of a sweep range, run another sweep with narrower ranges centered on the optimum. Stop after 1–2 narrowing iterations (returns diminish; ~60 min total spent on X register sweeps is the ceiling).

- [ ] **Step 6: Apply winning values for stepper_x at runtime**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"SET_TMC_FIELD STEPPER=stepper_x FIELD=TOFF VALUE=<toff>\nSET_TMC_FIELD STEPPER=stepper_x FIELD=TBL VALUE=<tbl>\nSET_TMC_FIELD STEPPER=stepper_x FIELD=HSTRT VALUE=<hstrt>\nSET_TMC_FIELD STEPPER=stepper_x FIELD=HEND VALUE=<hend>\"}" http://mainsailos.local:7125/printer/gcode/script
```

- [ ] **Step 7: Verify the values landed**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"DUMP_TMC STEPPER=stepper_x"}' http://mainsailos.local:7125/printer/gcode/script >/dev/null
sleep 1
curl -sS 'http://mainsailos.local:7125/server/gcode_store?count=80' | python3 -c "
import sys, json
ls = json.loads(sys.stdin.read())['result']['gcode_store']
for l in ls[-20:]:
    if 'CHOPCONF' in l['message']:
        print(l['message'])
"
```

Confirm `toff=<toff> hstrt=<hstrt> hend=<hend> tbl=<tbl>` matches the values from Step 6.

### Task S1-7: Tune stepper_y

**Files:** None.

Repeat S1-6 verbatim with `STEPPER=stepper_y` substituted everywhere. Same speed range (20–250 mm/s for FIND_VIBRATIONS, same register sweep ranges).

- [ ] **Step 1: FIND_VIBRATIONS on stepper_y**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"CHOPPER_TUNE FIND_VIBRATIONS=1 STEPPER=stepper_y MIN_SPEED=20 MAX_SPEED=250"}' --max-time 2400 http://mainsailos.local:7125/printer/gcode/script
```

Wait ~20–30 min.

- [ ] **Step 2: Fetch + analyze, identify problem speeds**

```bash
ssh pi@mainsailos.local "ls -t ~/printer_data/config/adxl_results/ | head -3"
# scp the latest stepper_y PNG to local
```

- [ ] **Step 3–5: Register sweep, narrow, iterate** (same procedure as S1-6 Step 4–5 with `STEPPER=stepper_y`)

- [ ] **Step 6: Apply winning values for stepper_y at runtime**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"SET_TMC_FIELD STEPPER=stepper_y FIELD=TOFF VALUE=<toff>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=TBL VALUE=<tbl>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=HSTRT VALUE=<hstrt>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=HEND VALUE=<hend>\"}" http://mainsailos.local:7125/printer/gcode/script
```

- [ ] **Step 7: Verify**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"DUMP_TMC STEPPER=stepper_y"}' http://mainsailos.local:7125/printer/gcode/script >/dev/null
sleep 1
# Pull and check CHOPCONF as in S1-6 Step 7
```

### Task S1-8: Live validation at runtime

**Files:** None.

- [ ] **Step 1: Re-home + QGL**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' --max-time 600 http://mainsailos.local:7125/printer/gcode/script
```

Don't do a FIRMWARE_RESTART — that would wipe the runtime SET_TMC_FIELD changes.

- [ ] **Step 2: TEST_SPEED ×2**

```bash
for i in 1 2; do
  echo "=== Post-tune run $i ==="
  curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"TEST_SPEED"}' --max-time 600 http://mainsailos.local:7125/printer/gcode/script
done
```

- [ ] **Step 3: Compare position + Z drift vs baseline**

Pull TEST_SPEED output (same procedure as S1-5 Step 5). Verify:
- 0 X/Y missed steps (mcu counts identical before/after in each run)
- Z probe diff < 0.1 mm (sensor noise band)

If position drift > 0.1 mm OR missed steps appear: **abort, revert runtime values** using the Step 4 fallback below.

- [ ] **Step 4: Ben noise rating**

Ben rates 1–5 scale against the baseline from S1-5 Step 5. Record.

Decision:
- Rating ≤ baseline AND 0 missed steps → success path, proceed to S1-9
- Rating > baseline OR abnormal sounds → **revert via SET_TMC_FIELD** to the pre-tuning DUMP_TMC values from S1-5 Step 2, end session. Document the no-win in tuning-log. The repo-side install changes from S1-2/S1-3/S1-4 stay (low-cost residual; just an unused extension). Skip the rest of S1.

```bash
# Revert example (substitute the <toff_baseline>, etc. from S1-5 Step 2):
curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"SET_TMC_FIELD STEPPER=stepper_x FIELD=TOFF VALUE=<toff_baseline>\nSET_TMC_FIELD STEPPER=stepper_x FIELD=TBL VALUE=<tbl_baseline>\nSET_TMC_FIELD STEPPER=stepper_x FIELD=HSTRT VALUE=<hstrt_baseline>\nSET_TMC_FIELD STEPPER=stepper_x FIELD=HEND VALUE=<hend_baseline>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=TOFF VALUE=<y_toff_baseline>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=TBL VALUE=<y_tbl_baseline>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=HSTRT VALUE=<y_hstrt_baseline>\nSET_TMC_FIELD STEPPER=stepper_y FIELD=HEND VALUE=<y_hend_baseline>\"}" http://mainsailos.local:7125/printer/gcode/script
```

### Task S1-9: Coexistence decision (CRT vs autotune compare)

**Files:** None (decision only).

Compare CRT-tuned values (from S1-6 Step 6 and S1-7 Step 6) against autotune-applied values (from S1-5 Step 3).

- [ ] **Step 1: Tabulate per stepper, per register**

For each of `stepper_x` and `stepper_y`, for each of `TBL`, `TOFF`, `HSTRT`, `HEND`:
- `crt` = winning CRT value
- `autotune` = value from `/tmp/pre-tune-autotune-values.txt`
- `diff` = `|crt - autotune|`

- [ ] **Step 2: Pick the coexistence path**

| Condition | Path |
|---|---|
| All `diff ≤ 1` for both steppers | **Path A — no PR.** CRT is confirming autotune. Document the validation outcome in tuning-log; skip to Task S1-11. The repo install from S1-2 stays (the extension is now available for future re-runs). |
| 1–3 of the 8 registers have `diff > 1` | **Path B — `delayed_gcode` override.** Keep `[autotune_tmc]` intact. Add a `[delayed_gcode _apply_crt_chopper]` that fires `SET_TMC_FIELD` only for the diverging registers. |
| Most (≥5 of 8) registers have `diff > 1` | **Path C — remove `[autotune_tmc stepper_x/y]`** for both steppers. Hard-code values via `[tmc2209 stepper_x/y] driver_TBL/driver_TOFF/driver_HSTRT/driver_HEND`. Accept the loss of autotune's CoolStep + PWM_GRAD + multistep_filt + IHOLDDELAY tuning. |

Record the choice in the session scratch note. The implementation branches diverge here.

### Task S1-10: Codify CRT values in motion.cfg (path B or C)

**Files:**
- Modify: `config/motion.cfg`

If Path A (no PR), skip to Task S1-11.

#### Path B: `delayed_gcode` override

- [ ] **Step 1: Create worktree + branch**

```bash
cd /Users/ben/code/voron-2-611
git checkout main && git pull --ff-only
git worktree add .claude/worktrees/codify-crt-xy -b worktree-codify-crt-xy
cd .claude/worktrees/codify-crt-xy
git branch -m chore/codify-crt-xy
```

- [ ] **Step 2: Append the delayed_gcode block to `config/motion.cfg`**

Add at the END of motion.cfg (after the existing `[autotune_tmc stepper_z3]` block):

```ini

#####################################################################
#   CRT chopper overrides (X/Y) — applied AFTER autotune at startup
#####################################################################
# Runtime-validated TMC2209 chopper register values from a CRT (MRX8024
# chopper-resonance-tuner) tuning session on YYYY-MM-DD. Autotune still
# writes its computed values at handle_connect; this delayed_gcode fires
# 1 second later to override ONLY the diverging registers with CRT's
# measurement-driven optimums. CoolStep, PWM, IHOLDDELAY, multistep_filt
# still come from autotune.
#
# Reference: docs/superpowers/specs/2026-05-20-chopper-resonance-tuner-design.md
# Baseline (autotune-computed) values are in the predecessor PR's klippy.log
# under `autotune_tmc set stepper_x/y …`.

[delayed_gcode _apply_crt_chopper]
initial_duration: 1.0
gcode:
  # Only include lines for registers where CRT diverged from autotune by >1 step.
  # Example (REPLACE with measured values + only diverging registers):
  # SET_TMC_FIELD STEPPER=stepper_x FIELD=TOFF VALUE=4
  # SET_TMC_FIELD STEPPER=stepper_x FIELD=HSTRT VALUE=5
  # SET_TMC_FIELD STEPPER=stepper_y FIELD=TOFF VALUE=5
  # SET_TMC_FIELD STEPPER=stepper_y FIELD=HSTRT VALUE=4
```

Fill in the actual `SET_TMC_FIELD` lines from Task S1-9 Step 1, ONLY for registers where `diff > 1`. Do NOT include lines for registers where autotune already lands within ±1 of CRT's choice — that's just noise in the override.

- [ ] **Step 3: Local CI**

```bash
make refcheck && make test-py
```

Expected: all green. The `[delayed_gcode _apply_crt_chopper]` is parsed; the macro_refcheck will verify SET_TMC_FIELD is a builtin.

- [ ] **Step 4: Commit + push**

```bash
git add config/motion.cfg
git commit -m "$(cat <<'EOF'
chore: codify CRT X/Y chopper overrides via delayed_gcode

Path B from CRT plan Task S1-9: keep [autotune_tmc] intact for CoolStep/
PWM/IHOLDDELAY tuning; override only the chopper registers (TBL/TOFF/
HSTRT/HEND) that CRT measured as meaningfully different from autotune's
computed values. Runtime-validated TEST_SPEED + ear rating in session
notes.

Restart impact: RESTART (delayed_gcode is a Klipper-side macro).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push -u origin chore/codify-crt-xy
```

- [ ] **Step 5: PR + CI + merge + deploy**

```bash
gh pr create --title "chore: codify CRT X/Y chopper overrides via delayed_gcode" --body "Path B from CRT plan Task S1-9. Runtime-validated noise rating: [N]/5 vs baseline [M]/5. See tuning-log entry."
gh pr checks <PR#> --watch
gh pr merge <PR#> --squash --delete-branch
# Use ExitWorktree, then:
cd /Users/ben/code/voron-2-611 && git checkout main && git pull --ff-only
scripts/deploy_to_pi.sh --yes
```

- [ ] **Step 6: Post-deploy verification**

After FIRMWARE_RESTART completes:

```bash
sleep 5  # delayed_gcode initial_duration: 1.0 + slack
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"DUMP_TMC STEPPER=stepper_x"}' http://mainsailos.local:7125/printer/gcode/script >/dev/null
# Pull CHOPCONF, confirm values match CRT-tuned (not autotune defaults)
```

If the values match runtime values from S1-7 Step 7: success. If they match autotune defaults: the delayed_gcode didn't fire — investigate via klippy.log.

#### Path C: remove `[autotune_tmc]` + `[tmc2209]` driver overrides

- [ ] **Step 1: Create worktree + branch** (same as Path B Step 1, branch name `chore/codify-crt-xy-full`)

- [ ] **Step 2: Comment out the X/Y `[autotune_tmc]` blocks in `config/motion.cfg`**

Replace the existing X/Y blocks:

```ini
[autotune_tmc stepper_x]
motor: omc-17hs19-2004s1
voltage: 24
extra_hysteresis: 2

[autotune_tmc stepper_y]
motor: omc-17hs19-2004s1
voltage: 24
extra_hysteresis: 2
```

With:

```ini
# [autotune_tmc stepper_x] and stepper_y removed YYYY-MM-DD — CRT-measured
# chopper values diverge from autotune's choices on all 4 registers (TBL,
# TOFF, HSTRT, HEND); see Task S1-9 Path C. CoolStep, PWM, IHOLDDELAY,
# multistep_filt no longer tuned for X/Y — accept this loss in exchange
# for the noise improvement validated in tuning-log.md YYYY-MM-DD entry.
```

- [ ] **Step 3: Add `driver_*` keys to `[tmc2209 stepper_x]` and `[tmc2209 stepper_y]`**

Modify the existing blocks (find them near line 46 / 70 in motion.cfg):

```ini
[tmc2209 stepper_x]
uart_pin: P1.10
interpolate: True
run_current: 0.8
sense_resistor: 0.110
stealthchop_threshold: 0
# CRT-tuned chopper registers (YYYY-MM-DD); replace with measured values:
driver_TBL: <tbl_x>
driver_TOFF: <toff_x>
driver_HSTRT: <hstrt_x>
driver_HEND: <hend_x>
```

Same for `[tmc2209 stepper_y]`.

- [ ] **Step 4: Local CI**

```bash
make refcheck && make test-py
```

Verify: klippy parse picks up the new driver_* fields without error. If it errors with `Option 'driver_tbl' is not valid in section 'tmc2209 stepper_x'`, the field names are misspelled — check vendor/klipper/klippy/extras/tmc2209.py for the actual config-key names (Klipper uses `driver_TOFF`/`driver_TBL`/`driver_HSTRT`/`driver_HEND` with uppercase per the Config_Reference; some users see lowercase work too).

- [ ] **Step 5: Commit + PR + merge + deploy** (same pattern as Path B Step 4–6 but with the Path C commit message)

```bash
git add config/motion.cfg
git commit -m "$(cat <<'EOF'
chore: codify CRT X/Y chopper values + remove [autotune_tmc] for X/Y

Path C from CRT plan Task S1-9: CRT-measured values diverged from
autotune's calculations on 5+ of 8 chopper registers across X and Y.
Remove [autotune_tmc] for those steppers and hard-code values in
[tmc2209]. Accept loss of autotune's CoolStep/PWM/IHOLDDELAY tuning
for X/Y in exchange for measurement-validated noise improvement
(rating [N]/5 vs autotune baseline [M]/5, validated TEST_SPEED 0 missed
steps).

Restart impact: RESTART.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Post-deploy verification**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"DUMP_TMC STEPPER=stepper_x"}' http://mainsailos.local:7125/printer/gcode/script >/dev/null
# Pull CHOPCONF, confirm values match Path C driver_* fields
```

### Task S1-11: Post-session documentation

**Files:**
- Modify: `memory/tuning-log.md`
- Modify: `CLAUDE.md` (if not already mentioned in Path B / C PR description)

- [ ] **Step 1: Append tuning-log entry**

Edit `memory/tuning-log.md`, add at the TOP of the entries (newest first):

```markdown
## YYYY-MM-DD — CRT X/Y chopper tuning (Session 1 of chopper-resonance-tuner plan)

PR [#NN](https://github.com/bjdeng/voron-2-611/pull/NN). Empirical TMC2209 chopper tuning via MRX8024/chopper-resonance-tuner, accelerometer toolhead-mounted.

**stepper_x (omc-17hs19-2004s1, run_current 0.8 A):**
| Register | autotune (pre) | CRT (post) | Diff |
|---|---|---|---|
| TBL | <pre_tbl_x> | <post_tbl_x> | <diff> |
| TOFF | <pre_toff_x> | <post_toff_x> | <diff> |
| HSTRT | <pre_hstrt_x> | <post_hstrt_x> | <diff> |
| HEND | <pre_hend_x> | <post_hend_x> | <diff> |

**stepper_y (omc-17hs19-2004s1, run_current 0.8 A):**
| Register | autotune (pre) | CRT (post) | Diff |
|---|---|---|---|
| TBL | <pre_tbl_y> | <post_tbl_y> | <diff> |
| TOFF | <pre_toff_y> | <post_toff_y> | <diff> |
| HSTRT | <pre_hstrt_y> | <post_hstrt_y> | <diff> |
| HEND | <pre_hend_y> | <post_hend_y> | <diff> |

**Coexistence path chosen:** Path A / B / C (per Task S1-9 of the plan).

**Validation:**
- Pre-tuning noise rating: 3/5 (autotune-aligned baseline from #97)
- Post-tuning noise rating: [N]/5
- Position drift: 0 mm (X/Y mcu counts identical before/after both TEST_SPEED runs)
- Z probe diff: [X.X] mm run 1, [Y.Y] mm run 2 (sensor noise band)
- Abnormal sounds: [none / describe]
- Test print (deferred): [pending / Y X first real print]

**CRT vibration heatmaps:** stored at `~/printer_data/config/adxl_results/` on the Pi (not in repo per `.gitignore`). Screenshots saved to session scratch note.

**Notes:** [any session-specific observations — e.g., FIND_VIBRATIONS plot showed flat response for X above 100 mm/s, the chopper was already near-optimal there]
```

Fill in all `<placeholder>` values from the actual session data.

- [ ] **Step 2: Update `CLAUDE.md` "Vendor / submodules" section** (if it wasn't already mentioned in the Path B/C PR)

In the "Vendor / submodules" or adjacent "Machine context beyond ~/printer_data/config/" area, add:

```markdown
- **chopper-resonance-tuner** — Pi-installed at `~/chopper-resonance-tuner`, NOT vendored (matches shaketune pattern). Provides `CHOPPER_TUNE` macro for empirical TMC2209 chopper tuning via LIS2DW accelerometer. Used YYYY-MM-DD for X/Y; see [tuning-log entry](memory/tuning-log.md). Will need install.sh re-run after Klipper version bumps.
```

- [ ] **Step 3: Commit (docs-only direct to main per CLAUDE.md memory)**

```bash
git add memory/tuning-log.md CLAUDE.md
git commit -m "docs: record CRT X/Y tuning Session 1 outcome (PR #NN)"
git push
```

### Task S1-12: Decision point — proceed to Session 2?

**Files:** None (decision only).

- [ ] **Step 1: Evaluate against Session 2 prerequisite**

Was Session 1 noise rating improvement meaningful (≥0.5/5 below baseline, OR CRT heatmaps showed real vibration improvement on at least one of X/Y)?

- **Yes:** Proceed to Session 2 (Z motors) in a separate working session. Schedule as a calendar block.
- **No:** Close the work. CRT didn't beat autotune-aligned on this machine. Document the no-op result, close the GitHub issue with that conclusion. The Pi install + repo config stays (low maintenance burden, useful for future motor changes).

---

# Session 2: Z motor tuning (conditional)

**Goal of session:** Apply the same measurement-driven approach to the 4 Z motors, treating them as one axis since they're identical hardware moving together. PR + deploy the winning Z chopper values.

**Prerequisite:** Session 1 yielded a meaningful X/Y improvement (per Task S1-12). If not, skip this session entirely.

**Expected duration:** ~2 hours (similar to Session 1 but slightly faster: lower max speed = shorter FIND_VIBRATIONS, and tuning one Z then applying to all 4).

### Task S2-1: Pre-session checklist

- [ ] **Step 1: Verify Session 1 state is in place**

```bash
git log --oneline -10  # confirm Session 1 PRs are on main
curl -sS 'http://mainsailos.local:7125/printer/objects/query?print_stats' | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status']['print_stats']['state'])"  # expect: standby
```

- [ ] **Step 2: Home + QGL**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' --max-time 600 http://mainsailos.local:7125/printer/gcode/script
```

(Retry once if the eddy first-tap flake hits.)

- [ ] **Step 3: Snapshot pre-tuning DUMP_TMC for all 4 Z steppers**

```bash
for s in stepper_z stepper_z1 stepper_z2 stepper_z3; do
  curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"DUMP_TMC STEPPER=$s\"}" http://mainsailos.local:7125/printer/gcode/script >/dev/null
done
sleep 1
curl -sS 'http://mainsailos.local:7125/server/gcode_store?count=600' | python3 -c "
import sys, json
ls = json.loads(sys.stdin.read())['result']['gcode_store']
for s in ['stepper_z','stepper_z1','stepper_z2','stepper_z3']:
    for i, l in enumerate(ls):
        if l['type'] == 'command' and f'DUMP_TMC STEPPER={s}' in l['message']:
            for j in range(i, min(i+30, len(ls))):
                if 'CHOPCONF' in ls[j]['message']:
                    print(f'=== {s} ===')
                    print(ls[j]['message'])
                    break
" | tee /tmp/pre-tune-z-dump-tmc.txt
```

Save as the Z rollback baseline.

- [ ] **Step 4: Capture autotune Z values from klippy.log**

```bash
ssh pi@mainsailos.local "grep -E 'autotune_tmc set stepper_(z|z1|z2|z3) (toff|tbl|hstrt|hend)' ~/printer_data/logs/klippy.log | tail -32" | tee /tmp/pre-tune-z-autotune-values.txt
```

- [ ] **Step 5: Baseline TEST_SPEED + G28 Z noise rating**

Same TEST_SPEED ×2 procedure as S1-5 Step 4. Plus: 3 cycles of `G28 Z` listening for probe-approach noise.

Ben records: TEST_SPEED noise rating + G28 Z noise rating + 0 missed steps confirmation.

### Task S2-2: FIND_VIBRATIONS on stepper_z

**Files:** None.

- [ ] **Step 1: Run FIND_VIBRATIONS at Z's speed range**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"CHOPPER_TUNE FIND_VIBRATIONS=1 STEPPER=stepper_z MIN_SPEED=5 MAX_SPEED=80"}' --max-time 2400 http://mainsailos.local:7125/printer/gcode/script
```

Z's working range: probing ~3 mm/s, second_homing_speed 3.0, homing_speed 15.0, max_z_velocity 100. The 5–80 sweep covers the practical band. Wait ~15–25 min.

- [ ] **Step 2: Spot-check stepper_z1 for similar harmonic peaks**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"CHOPPER_TUNE FIND_VIBRATIONS=1 STEPPER=stepper_z1 MIN_SPEED=5 MAX_SPEED=80"}' --max-time 2400 http://mainsailos.local:7125/printer/gcode/script
```

Wait ~15–25 min. Goal: confirm the 4 Z motors behave similarly enough to share one tune.

- [ ] **Step 3: Fetch + compare both heatmaps**

```bash
ssh pi@mainsailos.local "ls -t ~/printer_data/config/adxl_results/ | head -4"
# scp the latest stepper_z and stepper_z1 PNGs
```

Claude inspects both. If peaks are at the same speeds with comparable amplitudes (within ~30%), proceed with single-tune-applied-to-all. If they differ significantly, escalate: each Z gets tuned individually (multiplies Session 2 time by ~3.5×).

### Task S2-3: Tune stepper_z

**Files:** None.

Same procedure as S1-6 Steps 4–7, with `STEPPER=stepper_z` and the Z speed range:

- [ ] Run register sweep at problem speeds identified in S2-2
- [ ] Fetch heatmap, identify winning combo, narrow if needed
- [ ] Apply via SET_TMC_FIELD on stepper_z
- [ ] Verify via DUMP_TMC

### Task S2-4: Apply winning values to all 4 Z steppers

**Files:** None.

- [ ] **Step 1: Apply same values to z1, z2, z3 via SET_TMC_FIELD**

```bash
for s in stepper_z1 stepper_z2 stepper_z3; do
  curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"SET_TMC_FIELD STEPPER=$s FIELD=TOFF VALUE=<toff_z>\nSET_TMC_FIELD STEPPER=$s FIELD=TBL VALUE=<tbl_z>\nSET_TMC_FIELD STEPPER=$s FIELD=HSTRT VALUE=<hstrt_z>\nSET_TMC_FIELD STEPPER=$s FIELD=HEND VALUE=<hend_z>\"}" http://mainsailos.local:7125/printer/gcode/script
done
```

- [ ] **Step 2: Verify all 4 Z steppers via DUMP_TMC**

```bash
for s in stepper_z stepper_z1 stepper_z2 stepper_z3; do
  curl -sS -X POST -H 'Content-Type: application/json' -d "{\"script\":\"DUMP_TMC STEPPER=$s\"}" http://mainsailos.local:7125/printer/gcode/script >/dev/null
done
sleep 1
curl -sS 'http://mainsailos.local:7125/server/gcode_store?count=600' | python3 -c "
import sys, json, re
ls = json.loads(sys.stdin.read())['result']['gcode_store']
for s in ['stepper_z','stepper_z1','stepper_z2','stepper_z3']:
    for i, l in enumerate(ls):
        if l['type'] == 'command' and f'DUMP_TMC STEPPER={s}' in l['message']:
            for j in range(i, min(i+30, len(ls))):
                if 'CHOPCONF' in ls[j]['message']:
                    # Extract the 4 registers
                    m = re.search(r'toff=(\d+).*tbl=(\d+).*hstrt=(\d+).*hend=(\d+)', ls[j]['message'])
                    if m:
                        print(f'{s}: TOFF={m.group(1)} TBL={m.group(2)} HSTRT={m.group(3)} HEND={m.group(4)}')
                    break
"
```

All 4 should print the same values matching CRT's tuned numbers.

### Task S2-5: Live validation

**Files:** None.

- [ ] **Step 1: Re-home + QGL** (do NOT FIRMWARE_RESTART)

```bash
curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"G28\nQUAD_GANTRY_LEVEL"}' --max-time 600 http://mainsailos.local:7125/printer/gcode/script
```

- [ ] **Step 2: TEST_SPEED ×2 + G28 Z ×3**

```bash
for i in 1 2; do
  curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"TEST_SPEED"}' --max-time 600 http://mainsailos.local:7125/printer/gcode/script
done

for i in 1 2 3; do
  curl -sS -X POST -H 'Content-Type: application/json' -d '{"script":"G28 Z"}' --max-time 120 http://mainsailos.local:7125/printer/gcode/script
done
```

- [ ] **Step 3: Validation**

- 0 X/Y missed steps (X/Y unaffected by Z tuning so should match baseline)
- Z mcu counts identical before/after iterations
- Ben rates G28 Z probe-approach noise vs baseline from S2-1 Step 5
- Ben rates TEST_SPEED noise (should be similar to Session 1 result since X/Y haven't changed)

Decision: same logic as S1-8 Step 4. Success → S2-6; failure → revert via SET_TMC_FIELD using `/tmp/pre-tune-z-dump-tmc.txt` baseline, end session.

### Task S2-6: Coexistence decision + codify (Z motors)

**Files:**
- Modify: `config/motion.cfg`

Same 3-way decision (Path A / B / C) as S1-9, applied to the 4 Z motors collectively.

- [ ] **Step 1: Tabulate** (per S1-9 Step 1, but for 4 Z steppers × 4 registers = 16 cells)

- [ ] **Step 2: Pick path**

| Condition | Path |
|---|---|
| All `diff ≤ 1` | A — no PR |
| 1–3 of 16 cells `diff > 1` | B — extend the `[delayed_gcode _apply_crt_chopper]` from Session 1 (if it exists) or create it, add Z SET_TMC_FIELD lines |
| ≥4 cells `diff > 1` | C — remove `[autotune_tmc stepper_z/z1/z2/z3]`, add `driver_*` keys to `[tmc2209 stepper_z*]` |

- [ ] **Step 3: Implement chosen path**

Same mechanics as S1-10 (Path B or C). The delayed_gcode body grows; the `[tmc2209]` driver_* additions get applied to 4 steppers instead of 2.

- [ ] **Step 4: PR + CI + merge + deploy + post-deploy verify**

Same pattern as S1-10 Steps 5–6. PR title: `chore: codify CRT Z chopper overrides`.

### Task S2-7: Post-session documentation

**Files:**
- Modify: `memory/tuning-log.md`

- [ ] **Step 1: Append Z tuning entry** (same template as S1-11 Step 1, but for 4 Z steppers)

- [ ] **Step 2: Commit + push**

```bash
git add memory/tuning-log.md
git commit -m "docs: record CRT Z tuning Session 2 outcome"
git push
```

### Task S2-8: Close the work

**Files:** None.

- [ ] **Step 1: Close the CRT GitHub issue**

```bash
gh issue close <issue#> --comment "$(cat <<'EOF'
CRT plan complete. Session 1 (X/Y) outcome: [summary]. Session 2 (Z) outcome: [summary]. Tuning-log entries in memory/tuning-log.md. Final chopper values codified in motion.cfg via PR #[A] (X/Y) and PR #[B] (Z).
EOF
)"
```

- [ ] **Step 2: Optional: update CLAUDE.md** with the final state if anything changed re: how chopper params are managed

---

## Self-review checklist

Run through this before kicking off implementation:

- [ ] **Spec coverage:** Each section of the spec maps to one or more tasks (install footprint → S1-1 + S1-2, X/Y workflow → S1-5 to S1-8, coexistence decision → S1-9/S1-10 + S2-6, Z workflow → S2-1 to S2-5, validation/persistence/rollback → S1-8 Step 4 + S1-11 + S2-7)
- [ ] **Placeholder scan:** All `<placeholder>` markers in the plan are inside code-block templates that the operator MUST fill in from measurement data (CRT-tuned values, autotune comparison values, dates, PR numbers). These are intentional, not lazy plan failures — they encode "this data isn't knowable until the session runs."
- [ ] **Type consistency:** `SET_TMC_FIELD` field names (TOFF, TBL, HSTRT, HEND, uppercase) consistent across S1-6/S1-7/S2-3/S2-4. `[autotune_tmc stepper_x]` section names consistent. `driver_TBL/driver_TOFF/...` config keys consistent in Path C (matches Klipper's Config_Reference; verify against vendor/klipper if the local-CI klippy parse rejects).
- [ ] **Decision points are explicit:** Tasks S1-9 and S2-6 have ALL/PASS truth tables, not "use judgment." S1-8 Step 4 has explicit revert procedure. S1-12 has the proceed-to-Session-2 decision.
- [ ] **Rollback paths complete:** Mid-tuning revert via DUMP_TMC snapshot (S1-5 Step 2, S2-1 Step 3). Post-deploy revert via PR. CRT install rollback (S1-1 Step 3 note). All concrete commands, not "revert the change."
- [ ] **Upstream macro syntax may differ:** Plan repeatedly notes "adjust to match upstream wiki/CHOPPER_TUNE HELP if syntax differs" (S1-6 Step 4, S1-7 Step 1). This is the only legitimate unknown — the actual CRT macro signatures aren't fully specified in the wiki excerpts we have. Operator should run `CHOPPER_TUNE HELP` after install to confirm.
