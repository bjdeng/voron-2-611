# Repo Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every file that deploys to the Pi (machine state) into a single `config/` folder, leaving tooling at root. Shrink the deploy script's exclude list by relying on the directory boundary instead of enumeration.

**Architecture:** Single PR. One commit moves + updates all test-touching tooling atomically (so tests pass on every commit). Follow-up commits update docs (CLAUDE.md, memory/) that don't affect tests. Final manual e2e dry-run against the real Pi verifies the rsync source path actually changed and no machine files were missed.

**Tech Stack:** Bash 5 (deploy/sync scripts), Python 3 + pytest (refcheck + deploy-script tests), GitHub Actions (CI), Klipper config (.cfg/.conf includes are relative paths so they ride along with their files).

**Spec:** `docs/superpowers/specs/2026-05-14-repo-reorg.md`

**Branch:** `feat/repo-reorg` (already exists with the spec committed at `77ed1bc`)

**Critical git-safety rules:**
- **Never `git reset`, `git rebase`, or `git commit --amend`.** Create new commits only.
- Use `git mv` for every move so Git tracks renames properly.
- Verify `make test-py` is green AT THE END of every commit before moving on.

---

### Task 1: Move all machine state into `config/` and update test-touching tooling

This is the load-bearing commit. After it lands, `make test-py` passes and the repo's top-level reflects the new structure. All subsequent tasks are docs polish or post-merge verification.

**Files moved (12 `git mv` calls):**
- `printer.cfg` → `config/printer.cfg`
- `eddy.cfg` → `config/eddy.cfg`
- `btt-ebb-sb-usb-v1.0.cfg` → `config/btt-ebb-sb-usb-v1.0.cfg`
- `mainsail.cfg` → `config/mainsail.cfg`
- `timelapse.cfg` → `config/timelapse.cfg`
- `moonraker.conf` → `config/moonraker.conf`
- `crowsnest.conf` → `config/crowsnest.conf`
- `sonar.conf` → `config/sonar.conf`
- `macros/` → `config/macros/`
- `mmu/` → `config/mmu/`
- `archive/` → `config/archive/`
- `firmware/` → `config/firmware/`

**Tooling files modified in the same commit:**
- `Makefile` (CFGS list)
- `tests/voron-2-611.test` (CONFIG line)
- `tests/test_deploy_to_pi.py` (REPO / "printer.cfg" paths)
- `scripts/deploy_to_pi.sh` (multiple: rsync source, excludes, drift check, splice, restart classifier)
- `scripts/sync_from_pi.sh` (destination)
- `.github/workflows/ci.yml` (macro_refcheck glob)

- [ ] **Step 1: Confirm starting state**

```bash
git branch --show-current   # must be feat/repo-reorg
git status --short          # must show only "? vendor/klipper" (submodule untracked content)
ls config/ 2>/dev/null      # must NOT exist yet (we create it)
make test-py | tail -5
```

Expected: `make test-py` ends with "passed" + pre-commit hooks green. If anything else, stop and report.

- [ ] **Step 2: Create `config/` and move all 12 machine paths**

```bash
mkdir config
git mv printer.cfg config/printer.cfg
git mv eddy.cfg config/eddy.cfg
git mv btt-ebb-sb-usb-v1.0.cfg config/btt-ebb-sb-usb-v1.0.cfg
git mv mainsail.cfg config/mainsail.cfg
git mv timelapse.cfg config/timelapse.cfg
git mv moonraker.conf config/moonraker.conf
git mv crowsnest.conf config/crowsnest.conf
git mv sonar.conf config/sonar.conf
git mv macros config/macros
git mv mmu config/mmu
git mv archive config/archive
git mv firmware config/firmware
git status --short
```

Expected: `git status --short` shows `R` (rename) lines for the 8 root files and the 4 directories. No `M` (modified) lines yet.

- [ ] **Step 3: Update `Makefile` CFGS list**

Open `Makefile`. Find:

```make
CFGS        := printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg mainsail.cfg timelapse.cfg \
               $(wildcard macros/*.cfg) \
               $(wildcard mmu/base/*.cfg) \
               $(wildcard mmu/addons/*.cfg) \
               $(wildcard mmu/optional/*.cfg)
```

Replace with:

```make
CFGS        := config/printer.cfg config/eddy.cfg config/btt-ebb-sb-usb-v1.0.cfg config/mainsail.cfg config/timelapse.cfg \
               $(wildcard config/macros/*.cfg) \
               $(wildcard config/mmu/base/*.cfg) \
               $(wildcard config/mmu/addons/*.cfg) \
               $(wildcard config/mmu/optional/*.cfg)
```

- [ ] **Step 4: Update `tests/voron-2-611.test` CONFIG path**

Open `tests/voron-2-611.test`. Find:

```
CONFIG ../printer.cfg
```

Replace with:

```
CONFIG ../config/printer.cfg
```

No other changes to this file. (The `..` is relative to `vendor/klipper/`, where `test_klippy.py` is run from.)

- [ ] **Step 5: Update `tests/test_deploy_to_pi.py` printer.cfg paths**

Open `tests/test_deploy_to_pi.py`. There are two occurrences of `(REPO / "printer.cfg")` — both in helpers that read the real repo file to build a "matching Pi cfg" body:

Line ~42 in `_matching_pi_cfg()`:

```python
body = (REPO / "printer.cfg").read_text().split(marker)[0]
```

Replace with:

```python
body = (REPO / "config" / "printer.cfg").read_text().split(marker)[0]
```

Line ~213 in `test_drift_gate_ignores_whitespace_only_differences()`:

```python
body = (REPO / "printer.cfg").read_text().split(marker)[0]
```

Replace with:

```python
body = (REPO / "config" / "printer.cfg").read_text().split(marker)[0]
```

No other changes needed in this file (FAKE_PI_SYMLINKS test values reference Pi-side paths under `~/printer_data/config/`, which doesn't move).

- [ ] **Step 6: Update `.github/workflows/ci.yml` macro_refcheck glob**

Open `.github/workflows/ci.yml`. Find the macro_refcheck step (around line 134):

```yaml
          python scripts/macro_refcheck.py \
            printer.cfg eddy.cfg btt-ebb-sb-usb-v1.0.cfg mainsail.cfg timelapse.cfg \
            macros/*.cfg mmu/base/*.cfg mmu/addons/*.cfg mmu/optional/*.cfg
```

Replace with:

```yaml
          python scripts/macro_refcheck.py \
            config/printer.cfg config/eddy.cfg config/btt-ebb-sb-usb-v1.0.cfg config/mainsail.cfg config/timelapse.cfg \
            config/macros/*.cfg config/mmu/base/*.cfg config/mmu/addons/*.cfg config/mmu/optional/*.cfg
```

- [ ] **Step 7: Update `scripts/deploy_to_pi.sh` — five changes**

Open `scripts/deploy_to_pi.sh`.

**7a. `check_no_pi_drift` reads from `config/printer.cfg`** — find:

```bash
      <(sed -E "/$SAVE_CONFIG_MARKER/,\$d" "$REPO_ROOT/printer.cfg") \
```

Replace with:

```bash
      <(sed -E "/$SAVE_CONFIG_MARKER/,\$d" "$REPO_ROOT/config/printer.cfg") \
```

**7b. `build_staged_printer_cfg` reads from `config/printer.cfg`** — find:

```bash
  sed -E "/$SAVE_CONFIG_MARKER/,\$d" printer.cfg > "$STAGED_PRINTER_CFG"
```

Replace with:

```bash
  sed -E "/$SAVE_CONFIG_MARKER/,\$d" config/printer.cfg > "$STAGED_PRINTER_CFG"
```

**7c. `choose_restart_kind` regex matches `config/` prefix** — find:

```bash
  if printf '%s\n' "$changed" | grep -vE '^(macros/|archive/|printer\.cfg$)' >/dev/null; then
```

Replace with:

```bash
  if printf '%s\n' "$changed" | grep -vE '^config/(macros/|archive/|printer\.cfg$)' >/dev/null; then
```

**7d. `build_rsync_excludes` shrinks dramatically** — find the entire `build_rsync_excludes()` function body. The current `RSYNC_EXCLUDES=( ... )` array has many entries. Replace the whole function with:

```bash
build_rsync_excludes() {
  # rsync source is config/, so tooling paths (scripts/, vendor/, tests/,
  # docs/, memory/, .github/, .claude/, Makefile, README.md, CLAUDE.md, etc.)
  # live OUTSIDE the source and don't need explicit excludes.
  #
  # Inside config/ we still exclude:
  #   firmware/ — build kconfigs aren't deployed (they're flash-time inputs)
  #   archive/  — historical configs we don't run
  #   printer.cfg — handled separately via SAVE_CONFIG splice
  #
  # Plus the dynamic symlink list from discover_pi_symlinks (preserves
  # third-party symlinks like mmu/base/* → ~/Happy-Hare/config/base/*).
  RSYNC_EXCLUDES=(
    --exclude='/firmware/'
    --exclude='/archive/'
    --exclude='printer.cfg'
  )
  RSYNC_EXCLUDES+=("${PI_SYMLINK_EXCLUDES[@]}")
}
```

**7e. `show_plan_and_confirm` and `do_rsync` rsync source** — find the two `rsync` calls. Both currently use `"$REPO_ROOT/"`. Find:

```bash
    rsync -av --dry-run "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/" \
```

Replace with:

```bash
    rsync -av --dry-run "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/config/" "${PI_HOST}:~/printer_data/config/" \
```

Find:

```bash
  rsync -av "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/" || {
```

Replace with:

```bash
  rsync -av "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/config/" "${PI_HOST}:~/printer_data/config/" || {
```

- [ ] **Step 8: Update `scripts/sync_from_pi.sh` destination**

Open `scripts/sync_from_pi.sh`. Find the rsync invocation that pulls FROM the Pi (look for `pi@mainsailos.local:~/printer_data/config/` on the source side and `./` on the destination side).

Change the destination from `./` (or whatever it currently is) to `./config/`. Specifically: anywhere the script writes Pi files into the local repo's root, redirect to `./config/`.

If the script uses a `REPO_ROOT` variable, the destination becomes `"$REPO_ROOT/config/"`.

If the script has a hardcoded list of files/dirs to sync into specific local paths (e.g., `rsync ... :~/printer_data/config/printer.cfg ./printer.cfg`), update each path to `./config/<filename>`.

Save and verify the script still parses: `bash -n scripts/sync_from_pi.sh`.

- [ ] **Step 9: Run `make test-py`. All tests must pass.**

```bash
make test-py
```

Expected: macro_refcheck passes (it now scans `config/*.cfg`), pytest passes (33 deploy + 8 refcheck = 41), pre-commit passes (whitespace + ruff).

If any test fails:
- macro_refcheck failure → confirm Step 3 (Makefile CFGS) used `config/` prefix correctly.
- pytest failure on `_matching_pi_cfg()` or `test_drift_gate_ignores_whitespace_only_differences` → confirm Step 5 paths.
- pytest failure on any deploy test → re-check Step 7 changes to `scripts/deploy_to_pi.sh`.

Do not commit until tests pass.

- [ ] **Step 10: Run `shellcheck` on both scripts**

```bash
shellcheck scripts/deploy_to_pi.sh scripts/sync_from_pi.sh
```

Expected: exit 0, no findings.

- [ ] **Step 11: Sanity-check the smoke path**

```bash
bash scripts/deploy_to_pi.sh 2>&1 | head -3
```

Expected first line: `ERR: deploy refuses to run from 'feat/repo-reorg'. Switch to main and merge your changes first.`

This confirms the script still parses and aborts at the branch check after all the edits.

- [ ] **Step 12: Commit**

```bash
git add -A
git status --short  # verify only renames + the tooling files modified
git commit -m "$(cat <<'EOF'
feat(reorg): move all machine state into config/

12 git mv: every .cfg/.conf at root + macros/ + mmu/ + archive/ +
firmware/ now lives under config/. Tooling (scripts/, tests/, vendor/,
docs/, memory/, .github/, .claude/, Makefile, etc.) stays at root.
Top-level reads as "infra-as-code project with a config/ payload"
instead of an ambiguous mix.

Tooling updated atomically so tests pass on every commit:
  - Makefile CFGS list
  - tests/voron-2-611.test CONFIG path
  - tests/test_deploy_to_pi.py _matching_pi_cfg paths
  - .github/workflows/ci.yml macro_refcheck globs
  - scripts/deploy_to_pi.sh: rsync source path, shrunk RSYNC_EXCLUDES
    (now 3 static excludes inside config/ + dynamic symlinks),
    check_no_pi_drift, build_staged_printer_cfg, choose_restart_kind
    regex
  - scripts/sync_from_pi.sh: destination path

Pi-side directory (~/printer_data/config/) is unchanged. Skill prose,
CLAUDE.md path references, and memory/*.md updates land in follow-up
commits on this branch.

Spec: docs/superpowers/specs/2026-05-14-repo-reorg.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Update CLAUDE.md path references

`CLAUDE.md` has dozens of inline path references that point at the old root locations. Bulk-update with `config/` prefix, then read through the file to spot anything the find/replace missed.

**File modified:** `CLAUDE.md` only.

- [ ] **Step 1: Survey the references**

```bash
grep -nE '\b(printer\.cfg|eddy\.cfg|btt-ebb-sb-usb-v1\.0\.cfg|mainsail\.cfg|timelapse\.cfg|moonraker\.conf|crowsnest\.conf|sonar\.conf|macros/|mmu/|archive/|firmware/)\b' CLAUDE.md | head -40
```

Read the output. Each line is a candidate for `config/` prefix, BUT:
- Lines quoting Klipper's own `[include]` directives (like `[include macros/macros.cfg]`) describe CONTENT of printer.cfg, where the path is relative to printer.cfg's own location — these stay as-is.
- Lines describing the ON-PI location (`~/printer_data/config/...`) don't change.
- Lines describing the IN-REPO location should get the `config/` prefix.

- [ ] **Step 2: Update each reference**

Open `CLAUDE.md`. For each in-repo path reference, prepend `config/`. Examples:

| Old | New |
|---|---|
| ``Community serial: **2.611** (rendered on the LCD via `macros/lcd_tweaks.cfg:126`)`` | ``...via `config/macros/lcd_tweaks.cfg:126`)`` |
| ``Galileo extruder — explains the unusual `gear_ratio: 9:1` + `rotation_distance: 48.033` in `btt-ebb-sb-usb-v1.0.cfg``` | ``...in `config/btt-ebb-sb-usb-v1.0.cfg``` |
| ``Firmware build kconfigs are vendored in `firmware/``` | ``...vendored in `config/firmware/``` |
| ``Active control via `[temperature_fan chamber]` on `z:P2.7` `` | unchanged (Klipper section ref, not file path) |
| ``MMU `mmu/base/*.cfg` are symlinks`` | ``MMU `config/mmu/base/*.cfg` are symlinks`` |
| ``[macros/macros.cfg](macros/macros.cfg) markdown links`` | ``[config/macros/macros.cfg](config/macros/macros.cfg)`` |

Also update the "Repo layout" tree section (the ASCII tree) to reflect the new top-level shape — copy from the spec's "Target layout" section.

- [ ] **Step 3: Verify no broken in-repo links**

```bash
grep -nE '\[[^]]*\]\(([^)]*\.cfg|[^)]*\.conf|macros/|mmu/|archive/|firmware/)' CLAUDE.md
```

Every markdown link to an in-repo path should now start with `config/` or be a Klipper-include reference. Spot any that aren't.

- [ ] **Step 4: Update the first paragraph + "Repo layout" tree**

The opening paragraph says "edit here → PR → merge to main → /deploy-to-pi to sync to the printer." That's still true post-reorg. But the implicit "edit here" now means `config/` for machine state. Consider a one-line note in the opening paragraph: ``Machine state lives under `config/`; tooling around it lives at root.``

The "Repo layout" subsection should be replaced wholesale with the spec's "Target layout" tree.

- [ ] **Step 5: Verify markdown still renders cleanly**

```bash
git diff CLAUDE.md | head -100
```

Sanity check: look for accidentally-doubled prefixes (`config/config/...`), broken table formatting, broken links.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(reorg): update CLAUDE.md path references for config/ layout

Bulk-prefix in-repo paths with config/ following the move in the
previous commit. Klipper [include] references (relative to printer.cfg
itself) and Pi-side paths (~/printer_data/config/...) are unchanged.
The Repo Layout section now shows the new top-level shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Update `memory/*.md` path references

The local `memory/` directory has notes that reference in-repo paths. Update them the same way as CLAUDE.md.

**Files modified:** various under `memory/`. Identify by grep first.

Note: `memory/` is the LOCAL repo's `memory/`. Claude's global memory at `/Users/ben/.claude/projects/-Users-ben-code-voron-2-611/memory/` is a separate concern — references there are about Claude behaviors, not repo paths. Don't touch.

- [ ] **Step 1: Find references**

```bash
grep -rnE '\b(printer\.cfg|eddy\.cfg|btt-ebb-sb-usb-v1\.0\.cfg|mainsail\.cfg|timelapse\.cfg|moonraker\.conf|crowsnest\.conf|sonar\.conf|macros/|mmu/|archive/|firmware/)\b' memory/ 2>/dev/null
```

If the output is empty, this task is a no-op — go to Step 4 (commit skipped, document in the PR description).

- [ ] **Step 2: Apply same prefixing rules**

For each match, add `config/` prefix UNLESS:
- It's a Klipper-include reference (relative path inside a file body).
- It's a Pi-side path (`~/printer_data/config/...`).

- [ ] **Step 3: Verify**

```bash
git diff memory/
```

Visual check: no doubled prefixes, no broken markdown.

- [ ] **Step 4: Commit (skip if no changes)**

```bash
if ! git diff --quiet memory/; then
  git add memory/
  git commit -m "$(cat <<'EOF'
docs(reorg): update memory/ path references for config/ layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
fi
```

---

### Task 4: Push, open PR, wait for CI

**Files:** none modified.

- [ ] **Step 1: Push**

```bash
git push -u origin feat/repo-reorg
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/repo-reorg \
  --title "feat: reorganize repo (machine state into config/)" \
  --body "$(cat <<'EOF'
## Summary

Move every file that deploys to the Pi (8 root `.cfg/.conf` files + `macros/` + `mmu/` + `archive/` + `firmware/`) into a single `config/` folder. Tooling (scripts/, tests/, vendor/, docs/, memory/, .github/, .claude/, Makefile, etc.) stays at root.

**Top-level goes from ~25 mixed entries to ~11 that read clearly:** infra-as-code project with a `config/` payload.

**Deploy script's RSYNC_EXCLUDES shrinks from ~22 entries to 3** because the new rsync source (`config/`) naturally excludes everything outside it.

Spec: `docs/superpowers/specs/2026-05-14-repo-reorg.md`.

## What's NOT in this PR

- Pi-side directory structure (stays `~/printer_data/config/`).
- File renames (only moves).
- CI workflow no-op-pass-on-docs-paths fix (next, unblocks PR #9).

## Test plan

- [x] `make test-py` green (41 tests + pre-commit clean)
- [x] `shellcheck` clean on both scripts
- [x] Script aborts cleanly at branch check from feat branch
- [ ] CI: pre-commit + macro refcheck + pytest
- [ ] Post-merge: `bash scripts/deploy_to_pi.sh --dry-run` against real Pi confirms `config/` is the rsync source and no machine files are missed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for CI**

```bash
until gh pr checks $(gh pr view --json number --jq .number) 2>&1 | grep -qE '^pre-commit.*	(pass|fail)	'; do sleep 10; done
gh pr checks $(gh pr view --json number --jq .number)
```

Expected: `pre-commit + macro refcheck + pytest` passes. If it fails, read the run log, fix on a new commit on this branch, push again, wait.

- [ ] **Step 4: Run pr-review-toolkit before merging**

Per memory `feedback_pr_review_toolkit.md`: run the toolkit before pushing-to-merge, no "trivial" exemption.

```
Skill: pr-review-toolkit:review-pr <PR-number>
```

Address any Critical or Important findings on the same branch with new commits. Re-run CI + toolkit until clean.

- [ ] **Step 5: Merge**

```bash
gh pr merge $(gh pr view --json number --jq .number) --squash --delete-branch
git switch main && git pull --ff-only
git log --oneline -3
```

---

### Task 5: Post-merge e2e dry-run against real Pi

Final verification: from `main` after merge, run the deploy script's `--dry-run` against the actual Pi. Confirms the new rsync source path works and no machine files were missed.

**Files:** none modified (verification only).

- [ ] **Step 1: Verify the printer is idle**

```bash
curl -s "http://mainsailos.local:7125/printer/objects/query?print_stats" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['status']['print_stats']['state'])"
```

Expected: `standby`. If anything else, wait and re-check.

- [ ] **Step 2: Run the dry-run**

```bash
bash scripts/deploy_to_pi.sh --dry-run 2>&1 | grep -v "post-quantum\|store now, decrypt"
```

Expected output includes:
- All preconditions pass (✓ markers or no ERR lines).
- "Files to sync" section shows file paths RELATIVE to `config/` (e.g., just `macros/macros.cfg`, not `config/macros/macros.cfg`) — rsync renders paths relative to the source root.
- No `firmware/`, `archive/`, `scripts/`, `tests/`, `docs/`, `memory/`, `vendor/`, `.claude/`, `.github/`, `CLAUDE.md`, `Makefile`, etc. in the file list.
- Restart kind chosen: probably `firmware_restart` (because `.last-deploy-sha` from previous deploy is from before the reorg, and the diff `<old-sha>..main` will contain files outside `config/macros/` / `config/archive/` / `config/printer.cfg`).
- Final line: "==> --dry-run: no changes made to Pi."

- [ ] **Step 3: Spot-check `find` doesn't show any leaked tooling on the Pi**

The dry-run only PREVIEWS; nothing actually changed on the Pi. But we can sanity-check that no tooling crept in during prior deploys:

```bash
ssh pi@mainsailos.local 'ls -la ~/printer_data/config/ | grep -E "\.(py|sh|md|yml|toml)$|^d.*\.(git|venv|github|claude|pytest|ruff|vendor|scripts|tests|docs|memory)"' 2>&1 | grep -v "post-quantum\|store now\|See https"
```

Expected: empty output (no tooling files on Pi).

- [ ] **Step 4: Document the outcome**

If everything looks clean, no action. If anything surprises you (e.g., the rsync preview shows a tooling file, or a machine file is missing), capture in `memory/troubleshooting-log.md` with date + root cause + fix.

---

## Self-Review

**Spec coverage:**
- Spec §"Target layout" → Task 1 Step 2 (the 12 moves) ✓
- Spec §"Tooling updates — deploy_to_pi.sh" → Task 1 Step 7 (all 5 sub-changes) ✓
- Spec §"Tooling updates — sync_from_pi.sh" → Task 1 Step 8 ✓
- Spec §"Tooling updates — voron-2-611.test" → Task 1 Step 4 ✓
- Spec §"Tooling updates — Makefile" → Task 1 Step 3 ✓
- Spec §"Tooling updates — CI workflow" → Task 1 Step 6 ✓
- Spec §"Tooling updates — printer.cfg [include]" — confirmed no edits needed (relative paths ride along) ✓
- Spec §"Tooling updates — CLAUDE.md" → Task 2 ✓
- Spec §"Tooling updates — memory/*.md" → Task 3 ✓
- Spec §"Migration approach — single PR" → Tasks 1–3 are commits on the same branch; Task 4 opens PR ✓
- Spec §"Risks and mitigations — git mv history loss" → Task 1 Steps 2 + 12 (one commit) and visual diff in Step 12 ✓
- Spec §"Risks and mitigations — [include] absolute paths" → Task 1 Step 1 (precondition state check, which also runs the test suite which would catch this) ✓
- Spec §"Risks and mitigations — partial wrong rsync excludes" → Task 5 (e2e dry-run) ✓
- Spec §"Testing" → Task 1 Step 9 (`make test-py`) + Task 5 (e2e) ✓

No gaps.

**Placeholder scan:** No TBDs, TODOs, or vague instructions. Every code change has exact before/after snippets. Every command has expected output.

**Type / path consistency:** `config/` prefix used consistently across all tasks. The 12 source paths in Task 1 Step 2 match the 12 destination paths used in Tasks 2 and 3 grep patterns. Function names (`check_no_pi_drift`, `build_staged_printer_cfg`, `choose_restart_kind`, `build_rsync_excludes`) match between Task 1 Step 7 and the actual script.

**One potentially-subtle issue I want to flag explicitly:** Task 1 Step 7d replaces the WHOLE `build_rsync_excludes()` function. The current function defines its own `RSYNC_EXCLUDES=( ... )` from scratch — confirm before editing that no caller relies on accumulation from outside. Looking at the script: `RSYNC_EXCLUDES=()` is initialized at top, and `build_rsync_excludes` reassigns it. The `+=("${PI_SYMLINK_EXCLUDES[@]}")` at the end matches the existing pattern. Safe to replace wholesale.
