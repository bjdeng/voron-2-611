# Deploy Drift-Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/deploy_to_pi.sh` fail closed when it can't verify Pi state, auto-capture Pi-only edits to a review branch before any overwrite, rework `--force` so it can never lose data, and log every deploy.

**Architecture:** All changes are in one bash script (`deploy_to_pi.sh`) plus its integration tests (`tests/test_deploy_to_pi.py`, which drives the script with PATH-override fake binaries) and the skill doc. Three behavior changes layered onto the existing drift gate: (1) the gate's silent `return 0` skips become refusals unless `--force`; (2) detected drift always triggers a capture-to-branch before the gate decides; (3) a Pi-side append-only deploy log records every outcome.

**Tech Stack:** Bash, pytest with fake-binary harness (`tests/fake_bin/{ssh,scp,git,...}`, env-var-driven), git, ssh/scp to the Pi.

**Spec:** `docs/superpowers/specs/2026-05-28-deploy-drift-gate-hardening-design.md`

---

## Critical context for the executor

- The deploy script's two drift functions are **`check_no_pi_drift`** (printer.cfg body vs marker) and **`check_no_pi_drift_all_files`** (every deployed file vs the marker commit's `git archive` snapshot, by sha256). Both currently *fail open* (silently `return 0` / fall back) when they can't verify Pi state. `main()` calls them in order (after `check_ssh_reachable`, so ssh is always reachable by the time they run).
- Tests run the **whole script** with `tests/fake_bin` on `PATH`. Fakes read `FAKE_*` env vars and log every invocation to `$FAKE_LOG_DIR`. Existing helpers in `tests/test_deploy_to_pi.py`: `_run(env, args)`, `_diag(r)`, `_matching_pi_cfg()`, `_common_drift_env(extra)`, `_build_marker_tar(tmp_path, files)`, `_pi_hash_block(hashes)`. The `fake_log` pytest fixture sets `FAKE_LOG_DIR` and returns the log path (used by `test_ci_skipped_counts_as_pass` — grep it for the pattern).
- `--force` is already parsed into `FORCE` (`deploy_to_pi.sh:15,45`). `$LOCAL` holds the deploy HEAD sha (set during preflight). `$RESTART_KIND` is set by `choose_restart_kind`.
- Reference the code to change by the **surrounding text shown below**, not line numbers (they shift as you edit).
- Run tests with: `make test-py` (full macOS subset) or `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v` (just this file). Lint: `pre-commit run --all-files`.

---

## Task 1: Fail closed when the gate can't verify Pi state

**Files:**
- Modify: `scripts/deploy_to_pi.sh` (add `cant_verify_or_force` helper + `DEPLOY_RESULT` global; replace skip paths in `check_no_pi_drift` and `check_no_pi_drift_all_files`)
- Test: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_deploy_to_pi.py`:

```python
# ---------------------------------------------------------------------------
# Fail-closed: can't-verify conditions refuse unless --force
# ---------------------------------------------------------------------------

def test_drift_all_refuses_when_marker_missing(tmp_path):
    """No .last-deploy-sha on Pi → refuse (fail closed), no rsync."""
    r = _run(env=_common_drift_env({"FAKE_LAST_DEPLOY_SHA": ""}))
    assert r.returncode == 1, _diag(r)
    assert "cannot verify Pi state" in r.stderr, _diag(r)

def test_drift_all_marker_missing_proceeds_with_force(tmp_path):
    """--force overrides the can't-verify refusal."""
    r = _run(env=_common_drift_env({"FAKE_LAST_DEPLOY_SHA": ""}), args=["--yes", "--force"])
    assert "cannot verify Pi state" in r.stderr, _diag(r)
    # Proceeds past the gate (reaches restart/ready stage in fakes).
    assert r.returncode in (0, 2, 3, 4), _diag(r)

def test_drift_all_refuses_when_marker_sha_unknown(tmp_path):
    """Marker SHA not in git history → refuse (was: WARN + fall back)."""
    r = _run(env=_common_drift_env({
        "FAKE_LAST_DEPLOY_SHA": "deadbeef",
        "FAKE_GIT_MARKER_KNOWN": "0",
    }))
    assert r.returncode == 1, _diag(r)
    assert "cannot verify Pi state" in r.stderr, _diag(r)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -k "refuses_when_marker or marker_missing_proceeds or marker_sha_unknown" -v`
Expected: FAIL — currently the script silently proceeds (no "cannot verify Pi state" text; returncode not 1).

- [ ] **Step 3: Add the helper + `DEPLOY_RESULT` global**

In `deploy_to_pi.sh`, after the `FORCE=0` line in the globals block (the `# Flags` section), add:

```bash
# Set at each terminal point; consumed by the deploy log (see log_deploy).
DEPLOY_RESULT="incomplete"
```

Then add this function just above `check_no_pi_drift()`:

```bash
cant_verify_or_force() {
  # Fail-closed guard for the drift gate. $1 = human-readable reason.
  # With --force: warn and let the caller skip its check. Without: refuse.
  if [[ "$FORCE" == 1 ]]; then
    echo "WARN: drift gate cannot verify Pi state ($1); --force given, proceeding." >&2
    return 0
  fi
  echo "ERR: drift gate cannot verify Pi state: $1" >&2
  echo "Refusing to deploy (fail-closed). Fix the cause, or pass --force to override." >&2
  DEPLOY_RESULT="refused:cant-verify"
  exit 1
}
```

- [ ] **Step 4: Replace the skip paths in `check_no_pi_drift_all_files`**

Replace each silent skip. The marker-missing block:

```bash
  if [[ -z "$marker_sha" ]]; then
    return 0
  fi
```
becomes:
```bash
  if [[ -z "$marker_sha" ]]; then
    cant_verify_or_force "no deploy marker on Pi (.last-deploy-sha missing)"
    return 0
  fi
```

The unknown-SHA block:
```bash
  if ! git rev-parse --quiet --verify "${marker_sha}^{commit}" >/dev/null 2>&1; then
    echo "WARN: deploy marker SHA '$marker_sha' not in git history; skipping extended check." >&2
    return 0
  fi
```
becomes:
```bash
  if ! git rev-parse --quiet --verify "${marker_sha}^{commit}" >/dev/null 2>&1; then
    cant_verify_or_force "deploy marker SHA '$marker_sha' not in git history"
    return 0
  fi
```

Apply the same transform to the remaining four skips in this function — replace each `echo "WARN: ...skipping extended check." >&2; return 0` (and the bare `return 0` after the `git archive` / `config/`-dir checks) with `cant_verify_or_force "<reason>"; return 0`, using these reasons:
- `git archive` failure → `"git archive of marker snapshot failed"`
- no `config/` in snapshot → `"marker snapshot has no config/ dir"`
- no local hasher → `"no local sha256 tool (sha256sum/shasum)"`
- hash-enumeration empty on a side → `"could not enumerate file hashes on one side"`

- [ ] **Step 5: Replace the fallback in `check_no_pi_drift`**

Replace the whole block from `if [[ -n "$deploy_marker_raw" ]]; then` through the fallback `fi` (the section ending with the `Pi printer.cfg body has drifted from origin/main` error) with:

```bash
  if [[ -z "$deploy_marker_raw" ]]; then
    cant_verify_or_force "no deploy marker on Pi (.last-deploy-sha missing)"
    return 0
  fi
  if ! reference_body=$(git show "$deploy_marker_raw:config/printer.cfg" 2>/dev/null); then
    cant_verify_or_force "deploy marker SHA '$deploy_marker_raw' not in git history"
    return 0
  fi
  reference_body=$(printf '%s\n' "$reference_body" | sed -E "/$SAVE_CONFIG_MARKER/,\$d")
  if [[ -z "$reference_body" ]]; then
    cant_verify_or_force "marker '$deploy_marker_raw' yielded empty printer.cfg reference"
    return 0
  fi
  if ! diff -q -w -B <(printf '%s\n' "$pi_body") <(printf '%s\n' "$reference_body") >/dev/null; then
    echo "ERR: Pi printer.cfg body has drifted from the last-deployed commit ($deploy_marker_raw). Run sync-from-pi to capture changes, then re-run deploy-to-pi." >&2
    DEPLOY_RESULT="refused:pi-drift"
    exit 1
  fi
```

This removes the repo-compare fallback entirely — an unverifiable marker now fails closed instead of silently comparing against the repo.

- [ ] **Step 6: Run tests + lint, verify pass**

Run: `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v`
Expected: the three new tests PASS. The existing `test_drift_gate_falls_back_to_repo_compare_when_marker_unresolvable` and `test_drift_gate_falls_back_when_reference_body_empty_after_strip` will now FAIL (they assert the old fallback behavior) — **update them**: rename to `..._refuses_when_marker_unresolvable` / `..._refuses_when_reference_body_empty`, assert `r.returncode == 1` and `"cannot verify Pi state" in r.stderr`. Re-run until green.
Run: `pre-commit run --all-files` → PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
fix(deploy): fail closed when drift gate can't verify Pi state

The drift gate silently proceeded (return 0) on missing/unknown marker,
git-archive failure, etc. — the hole that let a deploy clobber Pi-only edits.
Now each can't-verify condition refuses unless --force.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Auto-capture Pi drift to a review branch + rework --force

**Files:**
- Modify: `scripts/deploy_to_pi.sh` (add `capture_pi_drift` + `DRIFT_OUTCOME`/`CAPTURE_BRANCH` globals; rework the drift-detected block in `check_no_pi_drift_all_files`)
- Modify: `tests/fake_bin/git` (handle `checkout`/`add`/`commit`)
- Test: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_deploy_to_pi.py`:

```python
def test_drift_captures_to_branch_then_aborts(tmp_path, fake_log):
    """Detected drift, no --force → capture to branch, commit, then abort."""
    files = {"mmu/base/mmu_parameters.cfg": "x: 0\n"}
    tar_path, _ = _build_marker_tar(tmp_path, files)
    pi_block = "00" * 32 + "  mmu/base/mmu_parameters.cfg"
    r = _run(env=_common_drift_env({
        "FAKE_MARKER_TAR_PATH": str(tar_path),
        "FAKE_PI_FILE_HASHES": pi_block,
    }))
    assert r.returncode == 1, _diag(r)
    assert "Captured" in r.stderr and "pi-drift-capture-" in r.stderr, _diag(r)
    log = fake_log.read_text()
    assert "git checkout -b pi-drift-capture-" in log, log
    assert "scp" in log and "mmu/base/mmu_parameters.cfg" in log, log
    assert "git commit" in log, log

def test_drift_captures_then_proceeds_with_force(tmp_path, fake_log):
    """Detected drift WITH --force → capture happens AND deploy proceeds."""
    files = {"mmu/base/mmu_parameters.cfg": "x: 0\n"}
    tar_path, _ = _build_marker_tar(tmp_path, files)
    pi_block = "00" * 32 + "  mmu/base/mmu_parameters.cfg"
    r = _run(env=_common_drift_env({
        "FAKE_MARKER_TAR_PATH": str(tar_path),
        "FAKE_PI_FILE_HASHES": pi_block,
    }), args=["--yes", "--force"])
    log = fake_log.read_text()
    assert "git checkout -b pi-drift-capture-" in log, log   # capture still ran
    assert r.returncode in (0, 2, 3, 4), _diag(r)            # proceeded past gate
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -k "captures_to_branch or captures_then_proceeds" -v`
Expected: FAIL — no capture branch is created today (drift just refuses, or `--force` skips silently).

- [ ] **Step 3: Teach the fake git the capture verbs**

In `tests/fake_bin/git`, add these cases to the `case "$1 $2" in` block (before the `*)` catch-all):

```bash
  "checkout "*) exit 0 ;;
  "add "*) exit 0 ;;
  "commit "*) exit 0 ;;
```

(`git checkout -b <branch>`, `git checkout <orig>`, `git add config/<f>`, `git commit -q -m ...` — all logged by the fake's top-of-file `echo "git $*"`, return success.)

- [ ] **Step 4: Add `capture_pi_drift` + globals**

In `deploy_to_pi.sh` globals block, add:

```bash
DRIFT_OUTCOME="none"
CAPTURE_BRANCH=""
```

Add this function above `check_no_pi_drift_all_files`:

```bash
capture_pi_drift() {
  # Pull the drifted Pi files into a review branch before any overwrite,
  # so the Pi-only edits are preserved in git regardless of --force.
  # $1 = newline/space-separated list of drifted paths (relative to config/).
  local files="$1" orig_branch f
  orig_branch=$(git branch --show-current)
  CAPTURE_BRANCH="pi-drift-capture-$(date -u +%Y%m%dT%H%M%SZ)"
  if ! git checkout -b "$CAPTURE_BRANCH" >/dev/null 2>&1; then
    echo "ERR: failed to create capture branch '$CAPTURE_BRANCH'; aborting before any overwrite." >&2
    DEPLOY_RESULT="failed:capture-branch"
    exit 2
  fi
  for f in $files; do
    if ! scp -q "${PI_HOST}:~/printer_data/config/$f" "$REPO_ROOT/config/$f"; then
      echo "ERR: failed to scp '$f' from Pi during capture; aborting." >&2
      git checkout "$orig_branch" >/dev/null 2>&1 || true
      DEPLOY_RESULT="failed:capture-scp"
      exit 2
    fi
    git add "config/$f"
  done
  git commit -q -m "capture: Pi-side edits to $(printf '%s ' $files)" >/dev/null 2>&1 || true
  git checkout "$orig_branch" >/dev/null 2>&1 || true
  echo "==> Captured Pi-side drift to branch $CAPTURE_BRANCH" >&2
}
```

- [ ] **Step 5: Rework the drift-detected block in `check_no_pi_drift_all_files`**

Replace the existing tail (from `if [[ -z "$drift_files" ]]; then` through the final `exit 1` of that function) with:

```bash
  if [[ -z "$drift_files" ]]; then
    return 0
  fi

  # Pi-side drift detected. Capture it to a review branch BEFORE any
  # overwrite — unconditionally, even under --force, so edits are never lost.
  capture_pi_drift "$drift_files"

  if [[ "$FORCE" == 1 ]]; then
    DRIFT_OUTCOME="forced:$CAPTURE_BRANCH"
    echo "==> --force: proceeding; Pi edits preserved on $CAPTURE_BRANCH (will be overwritten on the Pi)." >&2
    return 0
  fi

  DRIFT_OUTCOME="captured:$CAPTURE_BRANCH"
  DEPLOY_RESULT="refused:pi-drift"
  echo "ERR: Pi has uncommitted edits the repo doesn't know about:" >&2
  printf '    %s\n' $drift_files >&2
  echo "" >&2
  echo "Captured to branch $CAPTURE_BRANCH. Review/merge it, then re-run /deploy-to-pi." >&2
  echo "Or pass --force to overwrite the Pi (the capture branch keeps your edits)." >&2
  exit 1
```

- [ ] **Step 6: Run tests + lint, verify pass**

Run: `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v`
Expected: the two new tests PASS. The existing `test_drift_all_gate_fires_when_pi_has_modified_file` asserts only that the gate fires (`returncode`/stderr) — confirm it still passes (it should: returncode 1 + drift message). If it asserted the *old* "--force given, proceeding" wording, update it to the new capture wording.
Run: `pre-commit run --all-files` → PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/fake_bin/git tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): auto-capture Pi drift to a review branch before overwrite

Detected Pi-side drift now always scp's the drifted files onto a
pi-drift-capture-<ts> branch and commits them, before the gate decides.
Without --force the deploy aborts for review; with --force it proceeds but
the edits are preserved on the branch. --force can no longer lose data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Append-only deploy log on the Pi

**Files:**
- Modify: `scripts/deploy_to_pi.sh` (add `log_deploy`; call it at terminal points)
- Test: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write failing tests**

```python
def test_deploy_log_written_on_success(tmp_path, fake_log):
    """A clean deploy appends a 'success' line to the Pi deploy log."""
    files = {"mmu/base/mmu_parameters.cfg": "x: 0\n"}
    tar_path, hashes = _build_marker_tar(tmp_path, files)
    _run(env=_common_drift_env({
        "FAKE_MARKER_TAR_PATH": str(tar_path),
        "FAKE_PI_FILE_HASHES": _pi_hash_block(hashes),
    }), args=["--yes"])
    log = fake_log.read_text()
    assert "deploy-to-pi.log" in log, log
    assert "success" in log, log

def test_deploy_log_written_on_cant_verify_refusal(tmp_path, fake_log):
    """A fail-closed refusal still records 'refused:cant-verify'."""
    _run(env=_common_drift_env({"FAKE_LAST_DEPLOY_SHA": ""}))
    log = fake_log.read_text()
    assert "deploy-to-pi.log" in log and "refused:cant-verify" in log, log
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -k "deploy_log_written" -v`
Expected: FAIL — nothing writes `deploy-to-pi.log` yet.

- [ ] **Step 3: Add `log_deploy`**

Add above `main()`:

```bash
log_deploy() {
  # Append one line to the Pi's deploy log. $1 = result string.
  # Best-effort: never fail the deploy on a logging error.
  local ts flags line
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  flags=""
  [[ "$YES" == 1 ]] && flags+="yes,"
  [[ "$FORCE" == 1 ]] && flags+="force,"
  [[ "$DRY_RUN" == 1 ]] && flags+="dry-run,"
  [[ "$SMOKE" == 1 ]] && flags+="smoke,"
  flags="${flags%,}"; flags="${flags:--}"
  printf -v line '%s\t%s\t%s\t%s\t%s\t%s' \
    "$ts" "${LOCAL:--}" "$flags" "${RESTART_KIND:-none}" "${DRIFT_OUTCOME:-none}" "$1"
  printf '%s\n' "$line" | ssh "$PI_HOST" 'cat >> ~/printer_data/logs/deploy-to-pi.log' 2>/dev/null || true
}
```

- [ ] **Step 4: Call `log_deploy` at terminal points**

1. In `cant_verify_or_force`, immediately before `exit 1`, add: `log_deploy "refused:cant-verify"`.
2. In `check_no_pi_drift`'s drift `exit 1` block (the `DEPLOY_RESULT="refused:pi-drift"` one), add before `exit 1`: `log_deploy "refused:pi-drift"`.
3. In `check_no_pi_drift_all_files`'s drift-abort block, add before its `exit 1`: `log_deploy "refused:pi-drift"`.
4. In `main()`, immediately before the final `echo "==> Deploy complete..."`, add: `log_deploy "success"`.

(The `--force`-proceed path falls through to the success log with `DRIFT_OUTCOME=forced:<branch>` already set — no separate call needed.)

- [ ] **Step 5: Run tests + lint, verify pass**

Run: `.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v`
Expected: both new tests PASS; all prior tests still green.
Run: `pre-commit run --all-files` → PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): append-only deploy log on the Pi

Every deploy now records timestamp, HEAD, flags, restart kind, drift outcome,
and result to ~/printer_data/logs/deploy-to-pi.log — so a future Pi-side
clobber is diagnosable (the gap that made the 2026-05-28 RCA hard).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Document the new behavior in the skill

**Files:**
- Modify: `.claude/skills/deploy-to-pi/SKILL.md`

- [ ] **Step 1: Update the SKILL.md**

In the **Pre-flight** section, change the drift-gate bullets to state the new fail-closed behavior: when the gate cannot verify Pi state (missing/unknown marker, git-archive/hash failure) it **refuses** unless `--force` (no first-deploy exception).

In **What it does**, add a step describing auto-capture: detected Pi-side drift is scp'd onto a `pi-drift-capture-<timestamp>` branch and committed before any overwrite; without `--force` the deploy aborts telling you to review/merge that branch, with `--force` it proceeds (Pi overwritten, edits preserved on the branch).

Update the **`--force`** description: it no longer blanket-overwrites — capture always runs first, so `--force` only decides proceed-vs-abort and can't lose data.

Add a line under **Post-deploy** (or a new short section): every run appends to `~/printer_data/logs/deploy-to-pi.log` (timestamp, HEAD, flags, restart kind, drift outcome, result).

- [ ] **Step 2: Verify + commit**

Run: `pre-commit run --all-files` → PASS (markdown hygiene).

```bash
git add .claude/skills/deploy-to-pi/SKILL.md
git commit -m "$(cat <<'EOF'
docs(deploy): document fail-closed gate, drift auto-capture, reworked --force, deploy log

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** §1 fail-closed → Task 1. §2 auto-capture → Task 2. §3 `--force` rework (capture-always, force gates proceed-vs-abort) → Task 2 Step 5. §4 deploy logging → Task 3. SKILL.md → Task 4. Control flow (revised gate sequence) realized across Tasks 1-3. Testing section → tests in Tasks 1-3. All covered.
- **Type/name consistency:** globals `DEPLOY_RESULT` (Task 1), `DRIFT_OUTCOME` + `CAPTURE_BRANCH` (Task 2) defined once, consumed by `log_deploy` (Task 3); helper names `cant_verify_or_force`, `capture_pi_drift`, `log_deploy` used consistently.
- **No first-deploy exception:** intentional per the brainstorm — a missing marker refuses (needs one-time `--force`), matching "refuse all, --force to override."
- **Not unit-testable live:** real scp content, real branch contents, real restart, and the real Pi log file — covered by a manual smoke deploy after merge (deploy a trivial change, confirm `deploy-to-pi.log` gets a line; then simulate drift by hand-editing a Pi file and confirm capture+abort).
- **Placeholder scan:** none — every step has concrete bash/pytest and exact commands.
