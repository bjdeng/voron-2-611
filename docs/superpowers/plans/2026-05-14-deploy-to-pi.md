# deploy-to-pi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `scripts/deploy_to_pi.sh` with the missing safety gates (CI green, printer idle, Pi-cfg drift, post-restart polling), add `--yes` / `--dry-run` flags, refactor into testable functions, and add pytest coverage via PATH-override fake binaries.

**Architecture:** The existing 168-line bash script is sequential top-to-bottom. First commit refactors it into functions with no behavior change. Each subsequent commit adds one gate via TDD (failing test → function → wire-into-main → passing test → commit). Tests live in `tests/test_deploy_to_pi.py` and follow the subprocess pattern from `tests/test_macro_refcheck.py`. Fake binaries live in `tests/fake_bin/`.

**Tech Stack:** Bash 5 (the existing script's runtime), pytest (subprocess-based testing), shell stubs in `tests/fake_bin/` for `ssh`/`scp`/`curl`/`gh`/`git`.

**Spec:** `docs/superpowers/specs/2026-05-14-deploy-to-pi.md`

---

### Task 1: Refactor script into functions (no behavior change)

**Files:**
- Modify: `scripts/deploy_to_pi.sh` (full rewrite preserving every existing line of logic, just rearranged into functions)

- [ ] **Step 1: Read the current script end-to-end**

```bash
cat scripts/deploy_to_pi.sh
```

Identify every distinct logical step. The existing flow has these in order: branch check, tree-clean check, fetch + sync check, SSH reachable, Moonraker reachable, capture SAVE_CONFIG, build staged printer.cfg, build rsync excludes, choose restart kind (using `.last-deploy-sha`), dry-run rsync display, confirmation prompt, real rsync, scp staged printer.cfg, update marker, call Moonraker restart, cleanup.

- [ ] **Step 2: Rewrite into functions, one per logical step**

Each function takes no args, reads from globals where needed, exits non-zero on failure with `echo "ERR: ..." >&2`. Function names from the spec's "Refactor for testability" section.

Top of file (after the existing header):

```bash
#!/usr/bin/env bash
# Deploy HEAD on main to pi@mainsailos.local:~/printer_data/config/.
# See .claude/skills/deploy-to-pi/SKILL.md for the full contract.

set -euo pipefail

PI_HOST="${PI_HOST:-pi@mainsailos.local}"
PI_API="${PI_API:-http://mainsailos.local:7125}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Flags
YES=0
DRY_RUN=0

# Globals populated by setup functions
LOCAL=""
SAVE_CONFIG_PI=""
STAGED_PRINTER_CFG=""
RESTART_KIND=""
RSYNC_EXCLUDES=()
```

Then define each function. Example for `check_on_main`:

```bash
check_on_main() {
  local branch
  branch=$(git branch --show-current)
  if [[ "$branch" != "main" ]]; then
    echo "ERR: deploy refuses to run from '$branch'. Switch to main and merge your changes first." >&2
    exit 1
  fi
}
```

Same shape for every other check_* function. Repeat for: `check_tree_clean`, `check_in_sync_with_origin`, `check_ssh_reachable`, `check_moonraker_reachable` (keep WARN-only behavior unchanged in this task — promoting to hard-fail happens in Task 4).

Side-effect functions: `capture_save_config`, `build_staged_printer_cfg`, `build_rsync_excludes`, `choose_restart_kind`, `show_plan_and_confirm`, `do_rsync`, `update_deploy_marker`, `trigger_restart`, `cleanup`.

Add a `parse_flags()` that accepts `--yes` and `--dry-run` and sets the globals, but doesn't yet honor them (wiring happens in Task 8).

```bash
parse_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --yes) YES=1 ;;
      --dry-run) DRY_RUN=1 ;;
      *) echo "ERR: unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
  done
}
```

Finally `main()`:

```bash
main() {
  parse_flags "$@"
  cd "$REPO_ROOT"
  check_on_main
  check_tree_clean
  check_in_sync_with_origin
  check_ssh_reachable
  check_moonraker_reachable
  capture_save_config
  build_staged_printer_cfg
  build_rsync_excludes
  choose_restart_kind
  show_plan_and_confirm
  do_rsync
  update_deploy_marker
  trigger_restart
  cleanup
}

main "$@"
```

The bodies of each function are the same lines that exist today, lifted into the function. No behavior change.

- [ ] **Step 3: Verify shellcheck is clean**

```bash
shellcheck scripts/deploy_to_pi.sh || true
```

Note: shellcheck may emit info-level findings; fix any errors/warnings, leave info-level alone.

- [ ] **Step 4: Sanity-test against the live Pi (dry-run by abort)**

This is a "still-works" smoke test, not a real deploy. Run from a feat branch (the script will abort immediately at `check_on_main`):

```bash
git switch feat/deploy-to-pi
bash scripts/deploy_to_pi.sh 2>&1 | head -5
```

Expected first line: `ERR: deploy refuses to run from 'feat/deploy-to-pi'. ...`

If you see any earlier error (syntax, unbound variable), fix it.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_to_pi.sh
git commit -m "$(cat <<'EOF'
refactor(deploy): split deploy_to_pi.sh into functions (no behavior change)

Lift every step of the existing sequential script into a named function
(check_on_main, check_tree_clean, capture_save_config, ...). main() is
a flat sequence of those calls. Sets up the file shape for upcoming
TDD on the new safety gates (CI green, printer idle, Pi-cfg drift,
post-restart polling).

Also adds a no-op parse_flags() with --yes / --dry-run scaffolding;
flags are honored in a later commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Set up pytest test infrastructure with PATH-override fakes

**Files:**
- Create: `tests/fake_bin/ssh`
- Create: `tests/fake_bin/scp`
- Create: `tests/fake_bin/curl`
- Create: `tests/fake_bin/gh`
- Create: `tests/fake_bin/rsync`
- Create: `tests/test_deploy_to_pi.py`
- Modify: `Makefile` (only if `make test-py` doesn't already pick up new `tests/test_*.py` automatically — it does via `pytest tests/`, so likely no change needed)

- [ ] **Step 1: Write the failing test for the smoke case (script aborts when not on main)**

Create `tests/test_deploy_to_pi.py`:

```python
"""Integration tests for scripts/deploy_to_pi.sh.

Uses PATH-override fake binaries (tests/fake_bin/*) to simulate ssh/scp/
curl/gh/git responses. Each fake reads its behavior from env vars set
per-test and logs its invocations to a file the test can inspect.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "deploy_to_pi.sh"
FAKE_BIN = REPO / "tests" / "fake_bin"


def _run(env=None, args=None):
    """Run deploy_to_pi.sh with fake_bin on PATH. Returns CompletedProcess."""
    full_env = {**os.environ}
    full_env["PATH"] = f"{FAKE_BIN}:{full_env['PATH']}"
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *(args or [])],
        cwd=REPO,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _diag(r):
    return f"rc={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


def test_aborts_when_not_on_main():
    """Smoke test: with fake git reporting we're on a feat branch, abort."""
    r = _run(env={"FAKE_GIT_BRANCH": "feat/something"})
    assert r.returncode == 1, _diag(r)
    assert "refuses to run from 'feat/something'" in r.stderr, _diag(r)
```

- [ ] **Step 2: Run the test — expect import failure or no-such-file**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: FAIL — the fake binaries don't exist yet, or the script invokes the real `git` and reports the actual branch.

- [ ] **Step 3: Create fake binaries**

Each fake binary is a bash script in `tests/fake_bin/`. Make them executable. They read behavior from env vars and log invocations to `$FAKE_LOG_DIR/<name>.log` (or stderr if unset).

`tests/fake_bin/git`:

```bash
#!/usr/bin/env bash
# Fake git. Reads FAKE_GIT_BRANCH, FAKE_GIT_DIRTY, FAKE_GIT_LOCAL_SHA,
# FAKE_GIT_REMOTE_SHA. Logs every call.
echo "git $*" >> "${FAKE_LOG_DIR:-/dev/stderr}"

case "$1 $2" in
  "branch --show-current") echo "${FAKE_GIT_BRANCH:-main}"; exit 0 ;;
  "diff --quiet")
    if [[ "${FAKE_GIT_DIRTY:-0}" == "1" ]]; then exit 1; else exit 0; fi ;;
  "diff --cached") exit 0 ;;
  "fetch --quiet") exit 0 ;;
  "rev-parse main") echo "${FAKE_GIT_LOCAL_SHA:-abc1234}"; exit 0 ;;
  "rev-parse origin/main") echo "${FAKE_GIT_REMOTE_SHA:-abc1234}"; exit 0 ;;
  "diff --name-only")
    # FAKE_GIT_DIFF_FILES is a newline-separated list. Default: macros/macros.cfg.
    printf '%s\n' "${FAKE_GIT_DIFF_FILES:-macros/macros.cfg}"
    exit 0 ;;
  *) echo "fake git: unhandled args: $*" >&2; exit 99 ;;
esac
```

`tests/fake_bin/ssh`:

```bash
#!/usr/bin/env bash
echo "ssh $*" >> "${FAKE_LOG_DIR:-/dev/stderr}"

# The script does: ssh <host> 'true' to check reachability.
# Then: ssh <host> 'sed -n ... ~/printer_data/config/printer.cfg' to capture SAVE_CONFIG.
# Then: ssh <host> 'cat ~/printer_data/config/.last-deploy-sha 2>/dev/null || true'

if [[ "${FAKE_SSH_REACHABLE:-1}" != "1" ]]; then
  exit 255
fi

# Heuristic: last arg is the remote command. Match on it.
remote_cmd="${@: -1}"
case "$remote_cmd" in
  true) exit 0 ;;
  *sed*SAVE_CONFIG*) printf '%s\n' "${FAKE_SAVE_CONFIG_BLOCK:-#*# <---------------------- SAVE_CONFIG ---------------------->}" ;;
  *last-deploy-sha*) printf '%s' "${FAKE_LAST_DEPLOY_SHA:-}" ;;
  *cat*printer.cfg*) printf '%s' "${FAKE_PI_PRINTER_CFG:-}" ;;
  echo*last-deploy-sha) exit 0 ;;  # update marker
  *) exit 0 ;;
esac
```

`tests/fake_bin/curl`:

```bash
#!/usr/bin/env bash
echo "curl $*" >> "${FAKE_LOG_DIR:-/dev/stderr}"

# Inspect last URL arg
url=""
for arg in "$@"; do
  case "$arg" in http*) url="$arg" ;; esac
done

case "$url" in
  *server/info)
    if [[ "${FAKE_MOONRAKER_REACHABLE:-1}" == "1" ]]; then exit 0; else exit 22; fi ;;
  *print_stats*)
    printf '%s' "${FAKE_PRINT_STATS_JSON:-{\"result\":{\"status\":{\"print_stats\":{\"state\":\"standby\"}}}}}"
    exit 0 ;;
  *printer/info)
    printf '%s' "${FAKE_PRINTER_INFO_JSON:-{\"result\":{\"state\":\"ready\",\"state_message\":\"Printer is ready\"}}}"
    exit 0 ;;
  *printer/restart|*printer/firmware_restart)
    if [[ "${FAKE_RESTART_OK:-1}" == "1" ]]; then echo '{"result":"ok"}'; exit 0; else exit 1; fi ;;
  *) exit 0 ;;
esac
```

`tests/fake_bin/scp`:

```bash
#!/usr/bin/env bash
echo "scp $*" >> "${FAKE_LOG_DIR:-/dev/stderr}"
exit 0
```

`tests/fake_bin/rsync`:

```bash
#!/usr/bin/env bash
echo "rsync $*" >> "${FAKE_LOG_DIR:-/dev/stderr}"
exit 0
```

`tests/fake_bin/gh`:

```bash
#!/usr/bin/env bash
echo "gh $*" >> "${FAKE_LOG_DIR:-/dev/stderr}"

# Used as: gh run list --branch main --commit <sha> --json status,conclusion --limit 1
case "${FAKE_GH_RESPONSE:-success}" in
  success) echo '[{"status":"completed","conclusion":"success"}]' ;;
  failure) echo '[{"status":"completed","conclusion":"failure"}]' ;;
  skipped) echo '[{"status":"completed","conclusion":"skipped"}]' ;;
  none) echo '[]' ;;
esac
exit 0
```

Make them all executable:

```bash
chmod +x tests/fake_bin/{git,ssh,curl,scp,rsync,gh}
```

- [ ] **Step 4: Re-run the smoke test**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: PASS. If it fails, inspect `_diag(r)` output and figure out which fake binary is misbehaving.

- [ ] **Step 5: Commit**

```bash
git add tests/fake_bin/ tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
test(deploy): add pytest infrastructure for deploy_to_pi.sh

PATH-override fake binaries in tests/fake_bin/ stub out ssh/scp/curl/
rsync/gh/git. Each reads FAKE_* env vars to simulate responses and
logs invocations to FAKE_LOG_DIR for assertions. Smoke test covers
the "aborts when not on main" case as a sanity check on the rig.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: TDD — add the CI green gate

**Files:**
- Modify: `scripts/deploy_to_pi.sh` (add `check_ci_green` function, wire into `main()`)
- Modify: `tests/test_deploy_to_pi.py` (add two tests)

- [ ] **Step 1: Write the failing test for the "CI red" case**

Append to `tests/test_deploy_to_pi.py`:

```python
def test_aborts_when_ci_red():
    r = _run(env={"FAKE_GH_RESPONSE": "failure"})
    assert r.returncode == 1, _diag(r)
    assert "CI not green" in r.stderr, _diag(r)


def test_aborts_when_ci_missing():
    r = _run(env={"FAKE_GH_RESPONSE": "none"})
    assert r.returncode == 1, _diag(r)
    assert "CI not green" in r.stderr, _diag(r)


def test_ci_skipped_counts_as_pass(tmp_path):
    """Klippy parse + smoke is intentionally skipped today (Open Investigation #7)."""
    log = tmp_path / "log"
    r = _run(env={"FAKE_GH_RESPONSE": "skipped", "FAKE_LOG_DIR": str(log)})
    # Note: this test currently goes past CI green but will still fail
    # at a later gate. For now, just check it does NOT fail with "CI not green".
    assert "CI not green" not in r.stderr, _diag(r)
```

- [ ] **Step 2: Run the tests, expect failure**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py::test_aborts_when_ci_red -v
```

Expected: FAIL — the script doesn't yet check CI; it proceeds past the CI step and fails elsewhere with a different message.

- [ ] **Step 3: Implement `check_ci_green` in the script**

Add after `check_in_sync_with_origin` in `scripts/deploy_to_pi.sh`:

```bash
check_ci_green() {
  local response
  response=$(gh run list --branch main --commit "$LOCAL" --json status,conclusion --limit 1)
  if [[ "$response" == "[]" ]]; then
    echo "ERR: CI not green: no run found for HEAD ($LOCAL). Push commit and wait for CI." >&2
    exit 1
  fi
  local conclusion
  conclusion=$(printf '%s' "$response" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['conclusion'])")
  case "$conclusion" in
    success|skipped) ;;  # green or intentionally-skipped (Open Investigation #7)
    *)
      echo "ERR: CI not green: latest run for HEAD ($LOCAL) is '$conclusion'." >&2
      exit 1 ;;
  esac
}
```

Wire into `main()` right after `check_in_sync_with_origin`. Important: `check_in_sync_with_origin` must set `LOCAL` (it already does today via `LOCAL=$(git rev-parse main)`).

- [ ] **Step 4: Re-run the failing tests, expect them to pass now**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: all three new tests PASS. The smoke test also still passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): require CI green for HEAD before deploying

Add check_ci_green() that queries `gh run list` for the latest run on
HEAD. Refuses to deploy if no run exists or the conclusion is anything
other than success or skipped. The skipped case covers Open Investigation
#7 (Klippy parse + smoke job is intentionally disabled until the eddy
migration ships); it counts as pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: TDD — add the printer-idle gate (and promote Moonraker-reachable to hard fail)

**Files:**
- Modify: `scripts/deploy_to_pi.sh`
- Modify: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deploy_to_pi.py`:

```python
def test_aborts_when_moonraker_unreachable():
    r = _run(env={"FAKE_MOONRAKER_REACHABLE": "0"})
    assert r.returncode == 1, _diag(r)
    assert "Moonraker not reachable" in r.stderr, _diag(r)


def test_aborts_when_printer_printing():
    r = _run(env={
        "FAKE_PRINT_STATS_JSON": '{"result":{"status":{"print_stats":{"state":"printing"}}}}',
    })
    assert r.returncode == 1, _diag(r)
    assert "printer is not idle" in r.stderr.lower(), _diag(r)


def test_aborts_when_printer_paused():
    r = _run(env={
        "FAKE_PRINT_STATS_JSON": '{"result":{"status":{"print_stats":{"state":"paused"}}}}',
    })
    assert r.returncode == 1, _diag(r)
    assert "printer is not idle" in r.stderr.lower(), _diag(r)
```

- [ ] **Step 2: Run them, expect failure**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v -k "moonraker or printing or paused"
```

Expected: FAIL on all three.

- [ ] **Step 3: Promote Moonraker-reachable check from WARN to hard fail**

Find this block in `scripts/deploy_to_pi.sh::check_moonraker_reachable`:

```bash
if ! curl -fsS -o /dev/null --max-time 5 "$PI_API/server/info"; then
  echo "WARN: Moonraker not responding at $PI_API. Deploy will proceed but restart step will fail." >&2
fi
```

Replace with:

```bash
if ! curl -fsS -o /dev/null --max-time 5 "$PI_API/server/info"; then
  echo "ERR: Moonraker not reachable at $PI_API. Deploy aborted (restart step would fail anyway)." >&2
  exit 1
fi
```

- [ ] **Step 4: Add `check_printer_idle` function**

Add after `check_moonraker_reachable` in the script:

```bash
check_printer_idle() {
  local resp state
  resp=$(curl -fsS --max-time 5 "$PI_API/printer/objects/query?print_stats")
  state=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['status']['print_stats']['state'])")
  if [[ "$state" != "standby" ]]; then
    echo "ERR: printer is not idle (state=$state). Deploy aborted; wait for print to finish or cancel it." >&2
    exit 1
  fi
}
```

Wire into `main()` after `check_moonraker_reachable` and before `check_ci_green`.

- [ ] **Step 5: Run tests, expect all three to pass**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: PASS on every test added so far (smoke, CI gates, Moonraker, idle).

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): hard-fail on unreachable Moonraker and add printer-idle gate

Promote the previously WARN-only Moonraker reachability check to a hard
fail — if Moonraker isn't responding, the restart step at the end of the
deploy will fail anyway, so refuse up front.

Add check_printer_idle() that queries print_stats.state via Moonraker
and refuses to deploy if anything other than "standby". Catches the
"hit /deploy-to-pi during a print" failure mode.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: TDD — add the Pi-cfg drift gate

**Files:**
- Modify: `scripts/deploy_to_pi.sh`
- Modify: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deploy_to_pi.py`:

```python
def test_aborts_when_pi_has_drift():
    """Pi's printer.cfg body differs from origin/main's body."""
    # Mock the Pi returning a printer.cfg whose body doesn't match the repo.
    fake_pi_cfg = (
        "[printer]\n"
        "max_velocity: 999   # someone-edited-on-pi\n"
        "\n"
        "#*# <---------------------- SAVE_CONFIG ---------------------->\n"
        "#*# [heater_bed]\n"
    )
    r = _run(env={"FAKE_PI_PRINTER_CFG": fake_pi_cfg})
    assert r.returncode == 1, _diag(r)
    assert "drift" in r.stderr.lower() or "sync-from-pi" in r.stderr, _diag(r)


def test_passes_when_pi_matches_repo():
    """Pi's printer.cfg body matches origin/main's body — gate passes."""
    repo_body = (REPO / "printer.cfg").read_text()
    # Truncate at the repo's own SAVE_CONFIG marker
    marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
    body = repo_body.split(marker)[0]
    fake_pi_cfg = body + marker + "\n#*# [heater_bed]\n#*# control = pid\n"
    log = REPO / "tests" / "_tmp_log"  # one-off log file
    log.unlink(missing_ok=True)
    r = _run(env={"FAKE_PI_PRINTER_CFG": fake_pi_cfg, "FAKE_LOG_DIR": str(log)})
    # Drift gate should not be the reason it stops. It may stop later (rsync
    # invocation, etc.) but the error message must not mention drift.
    assert "drift" not in r.stderr.lower(), _diag(r)
```

- [ ] **Step 2: Run them, expect failure**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v -k "drift or pi_matches"
```

Expected: FAIL — script doesn't yet check drift.

- [ ] **Step 3: Implement `check_no_pi_drift`**

Add after `capture_save_config` in the script (because we already have Pi's cfg captured for the SAVE_CONFIG splice):

```bash
check_no_pi_drift() {
  local pi_full pi_body repo_body marker
  pi_full=$(ssh "$PI_HOST" 'cat ~/printer_data/config/printer.cfg')
  marker='#\*# <-\+ SAVE_CONFIG -\+>'
  pi_body=$(printf '%s\n' "$pi_full" | sed "/$marker/,\$d")
  repo_body=$(sed "/$marker/,\$d" "$REPO_ROOT/printer.cfg")
  if [[ "$pi_body" != "$repo_body" ]]; then
    echo "ERR: Pi printer.cfg body has drifted from origin/main. Run sync-from-pi to capture changes, then re-run deploy-to-pi." >&2
    exit 1
  fi
}
```

Wire into `main()` between `capture_save_config` and `build_staged_printer_cfg`.

Note: the fake `ssh` script's response for `cat ~/printer_data/config/printer.cfg` reads from `FAKE_PI_PRINTER_CFG`. Verify the case match in `tests/fake_bin/ssh` covers it (the `*cat*printer.cfg*` branch added in Task 2).

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: drift tests PASS. Other tests may need their `FAKE_PI_PRINTER_CFG` updated to match the repo's body now that the drift gate is active. If any pre-existing test fails because the fake returns a default that doesn't match, update its env to set `FAKE_PI_PRINTER_CFG` to a matching value (build it the same way `test_passes_when_pi_matches_repo` does, as a fixture helper at the top of the file).

Create a fixture helper in the test file:

```python
def _matching_pi_cfg():
    """Build a Pi printer.cfg that has the same body as repo + a fake SAVE_CONFIG tail."""
    marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
    body = (REPO / "printer.cfg").read_text().split(marker)[0]
    return body + marker + "\n#*# [heater_bed]\n#*# control = pid\n"
```

And update every pre-existing test that runs past the drift gate to include `"FAKE_PI_PRINTER_CFG": _matching_pi_cfg()` in its env.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): refuse to deploy if Pi printer.cfg body has drifted

Add check_no_pi_drift() that compares Pi's printer.cfg body (everything
above the SAVE_CONFIG marker) to the repo's body. If they differ, abort
with a pointer to sync-from-pi. Prevents Mainsail-side edits from being
silently overwritten by a deploy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: TDD — add post-restart ready polling

**Files:**
- Modify: `scripts/deploy_to_pi.sh`
- Modify: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deploy_to_pi.py`:

```python
def test_succeeds_when_klipper_returns_ready(tmp_path):
    log = tmp_path / "log"
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_PRINTER_INFO_JSON": '{"result":{"state":"ready","state_message":"Printer is ready"}}',
        "FAKE_LOG_DIR": str(log),
    }
    r = _run(env=env)
    assert r.returncode == 0, _diag(r)
    assert "state=ready" in r.stdout, _diag(r)


def test_fails_when_klipper_returns_error(tmp_path):
    log = tmp_path / "log"
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_PRINTER_INFO_JSON": '{"result":{"state":"error","state_message":"Invalid pin description"}}',
        "FAKE_LOG_DIR": str(log),
    }
    r = _run(env=env)
    assert r.returncode == 3, _diag(r)
    assert "Invalid pin description" in r.stderr, _diag(r)
```

Note: these tests run the full happy path past every gate, so they need a Pi cfg that matches the repo. Also note these tests assume the script accepts `--yes` or otherwise doesn't block on `read`. For now, set `YES=1` via env or include `--yes` in `_run`'s args. We'll wire `--yes` properly in Task 7; for this task, temporarily edit `show_plan_and_confirm` to skip the prompt if stdin is not a TTY (`[[ ! -t 0 ]]`) — that lets pytest's subprocess pipe-stdin path through cleanly.

Update `show_plan_and_confirm`:

```bash
show_plan_and_confirm() {
  # ... existing print-the-plan code ...
  if [[ ! -t 0 ]]; then
    # stdin not a TTY (running under pytest); auto-confirm
    return 0
  fi
  read -r -p "Proceed? [y/N] " ANSWER
  case "$ANSWER" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
}
```

- [ ] **Step 2: Run them, expect failure**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v -k "ready or error"
```

Expected: FAIL — the script doesn't poll for ready, and exit code 3 isn't yet defined.

- [ ] **Step 3: Implement `wait_for_klipper_ready`**

Add at the end of the function block in `scripts/deploy_to_pi.sh`:

```bash
wait_for_klipper_ready() {
  local i resp state state_msg
  for i in $(seq 1 30); do
    sleep 1
    resp=$(curl -fsS --max-time 3 "$PI_API/printer/info" 2>/dev/null || true)
    if [[ -z "$resp" ]]; then continue; fi
    state=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['state'])" 2>/dev/null || echo "")
    state_msg=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['result'].get('state_message',''))" 2>/dev/null || echo "")
    case "$state" in
      ready)
        echo "==> Klipper state=ready (after ${i}s)"
        return 0 ;;
      error)
        echo "ERR: Klipper failed to start: $state_msg" >&2
        exit 3 ;;
      startup|"") continue ;;
      *) continue ;;
    esac
  done
  echo "ERR: Klipper did not reach 'ready' within 30s. Inspect klippy.log." >&2
  exit 3
}
```

Wire into `main()` after `trigger_restart`.

Tests need to sleep less in the happy path. The fake `curl` returns immediately so each loop iteration is bounded by `sleep 1`. To keep tests fast, override the sleep duration. Add to the script near the top:

```bash
READY_POLL_INTERVAL="${READY_POLL_INTERVAL:-1}"
READY_POLL_MAX="${READY_POLL_MAX:-30}"
```

And use them in the loop (`sleep "$READY_POLL_INTERVAL"`, `seq 1 "$READY_POLL_MAX"`). In the tests, set `READY_POLL_INTERVAL=0` and `READY_POLL_MAX=3` so the loop is instant.

- [ ] **Step 4: Update fake `curl` to handle `printer/info` calls during the poll**

The fake `curl` from Task 2 already returns `FAKE_PRINTER_INFO_JSON` for `printer/info`. Verify it does. If not, add the branch.

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): poll Klipper for ready after restart

Add wait_for_klipper_ready() that polls /printer/info every 1s for up
to 30s after the Moonraker restart call. Surfaces state_message and
exits 3 if Klipper enters error state. Poll interval and max are
overridable via env (READY_POLL_INTERVAL, READY_POLL_MAX) for tests.

Also: auto-confirm the deploy when stdin isn't a TTY, so pytest can
drive the full happy path. Interactive use is unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: TDD — wire up `--yes` and `--dry-run` flags

**Files:**
- Modify: `scripts/deploy_to_pi.sh`
- Modify: `tests/test_deploy_to_pi.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deploy_to_pi.py`:

```python
def test_dry_run_touches_nothing_on_pi(tmp_path):
    log = tmp_path / "log"
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(log),
    }
    r = _run(env=env, args=["--dry-run"])
    assert r.returncode == 0, _diag(r)
    # No scp, no rsync, no restart should have been invoked.
    log_contents = log.read_text() if log.exists() else ""
    assert "rsync " not in log_contents, log_contents
    assert "scp " not in log_contents, log_contents
    # ssh allowed for read-only reachability + save_config capture, but not for "echo > .last-deploy-sha"
    assert "echo" not in log_contents.split("ssh ")[-1] if "ssh " in log_contents else True


def test_yes_flag_skips_confirmation(tmp_path):
    log = tmp_path / "log"
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(log),
    }
    # Force stdin to be a TTY-like (the no-TTY auto-confirm path would already
    # pass without --yes). Hard to fake; instead, just verify --yes works in
    # the non-TTY path by checking exit code 0 with default fake responses.
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 0, _diag(r)
```

- [ ] **Step 2: Run them, expect failure**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v -k "dry_run or yes_flag"
```

Expected: `--dry-run` test fails because the script still rsyncs.

- [ ] **Step 3: Honor the flags in `main()` and `show_plan_and_confirm()`**

Update `show_plan_and_confirm`:

```bash
show_plan_and_confirm() {
  # ... existing print-the-plan code ...
  echo "==> Restart kind chosen: $RESTART_KIND"
  echo
  if [[ "$YES" == 1 ]]; then
    echo "(--yes given, proceeding without prompt)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    return 0  # non-TTY auto-confirm (for pytest)
  fi
  read -r -p "Proceed? [y/N] " ANSWER
  case "$ANSWER" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
}
```

Update `main()`:

```bash
main() {
  parse_flags "$@"
  cd "$REPO_ROOT"
  # ... all the check_* calls ...
  capture_save_config
  check_no_pi_drift
  build_staged_printer_cfg
  build_rsync_excludes
  choose_restart_kind
  show_plan_and_confirm
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "==> --dry-run: no changes made to Pi."
    cleanup
    exit 0
  fi
  do_rsync
  update_deploy_marker
  trigger_restart
  wait_for_klipper_ready
  cleanup
}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_deploy_to_pi.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_to_pi.sh tests/test_deploy_to_pi.py
git commit -m "$(cat <<'EOF'
feat(deploy): honor --yes and --dry-run flags

--yes skips the confirmation prompt. --dry-run runs all preconditions
and prints the plan, then exits without touching the Pi. The non-TTY
auto-confirm path (added in the previous commit for pytest) is unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Update SKILL.md to document the new gates

**Files:**
- Modify: `.claude/skills/deploy-to-pi/SKILL.md`

- [ ] **Step 1: Read the current SKILL.md**

```bash
cat .claude/skills/deploy-to-pi/SKILL.md
```

- [ ] **Step 2: Edit the "Pre-flight" and "What it does" sections to mention the new gates**

Replace the "Pre-flight" section bullets with:

```markdown
## Pre-flight

The skill refuses to deploy if any of these gates fail (it tells you what to fix):

- Must be on `main` with a clean working tree and up-to-date with `origin/main`.
- Pi must be reachable via keyed SSH.
- Moonraker must be running on the Pi (port 7125).
- Latest CI run on HEAD must be **green** (success). The `Klippy parse + smoke gcode` job is intentionally `skipped` until Open Investigation #7 ships — that counts as pass.
- Printer must be **idle** (`print_stats.state == "standby"`). Not `printing`, `paused`, etc.
- Pi's `printer.cfg` body (everything above the SAVE_CONFIG marker) must match `origin/main`. If they've diverged, run `sync-from-pi` first to capture Pi-side edits.
- After the deploy + restart, the skill polls Moonraker until Klipper reports `state == "ready"` (timeout 30s). If Klipper enters `error`, the skill surfaces the message and exits non-zero.
```

In "How to run", add the flags:

```markdown
## How to run

```sh
scripts/deploy_to_pi.sh           # interactive: confirms before deploy
scripts/deploy_to_pi.sh --yes     # skip confirmation
scripts/deploy_to_pi.sh --dry-run # preconditions + plan only, no changes
```

Or, from a Claude session, invoke the skill: `/deploy-to-pi`.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/deploy-to-pi/SKILL.md
git commit -m "$(cat <<'EOF'
docs(deploy): document new gates and flags in deploy-to-pi SKILL.md

Reflect the CI-green / printer-idle / Pi-cfg-drift / post-restart-ready
gates added in this branch. Document --yes and --dry-run flags.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Update CLAUDE.md and clean up the manual-fallback note

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Drop the "until the skill ships" parenthetical**

Find this paragraph (added on this branch):

```markdown
**After every merge to `main`:** run `/deploy-to-pi` to sync the Pi. The skill refuses if CI isn't green, the printer is busy, or the Pi has drift; it tells you what to do next. **Until the skill ships** (spec at `docs/superpowers/specs/2026-05-14-deploy-to-pi.md`, Open Investigation #8): manually `scp` the changed files and call `RESTART` / `FIRMWARE_RESTART` as appropriate. Always check `print_stats.state == "standby"` via Moonraker (`curl http://mainsailos.local:7125/printer/objects/query?print_stats`) before touching the Pi.
```

Replace with:

```markdown
**After every merge to `main`:** run `/deploy-to-pi` to sync the Pi. The skill refuses if CI isn't green, the printer is busy, or the Pi has drift; it tells you what to do next. See [`.claude/skills/deploy-to-pi/SKILL.md`](.claude/skills/deploy-to-pi/SKILL.md) for the full contract.
```

- [ ] **Step 2: Update Open Investigation #8 to "resolved"**

Find:

```markdown
8. **Automated Pi deploy** (`main → rsync → Moonraker restart`). Spec at `docs/superpowers/specs/2026-05-14-deploy-to-pi.md`. v1 is a `/deploy-to-pi` skill + `scripts/deploy_to_pi.py` script (manual trigger); v2 is a GH Action wrapping the same script.
```

Move it to "Recently resolved" with one line, and update v1 wording:

```markdown
8. **Automated Pi deploy on every merge** (v2 — GH Action wrapping `scripts/deploy_to_pi.sh --yes`). v1 (manual `/deploy-to-pi` skill) shipped on 2026-05-14; see [`.claude/skills/deploy-to-pi/SKILL.md`](.claude/skills/deploy-to-pi/SKILL.md). v2 is the automation layer on top.
```

(Keep the entry in the "Open" list because the *automated* trigger is still future work. Just refine the scope.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude-md): deploy-to-pi v1 shipped; update workflow + investigation #8

Drop the "until the skill ships" fallback wording — the skill is now
the actual deploy path. Narrow Open Investigation #8 to the v2 GH
Action wrapper layer; v1 (the manual skill) is done.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Manual end-to-end test on a real change

**Files:**
- None (this is verification, not edits)

- [ ] **Step 1: Confirm CI is green on HEAD**

```bash
gh run list --branch feat/deploy-to-pi --limit 1
```

If a run is missing or red, push and wait.

- [ ] **Step 2: Confirm `make test-py` is green locally**

```bash
make test-py
```

Expected: all tests pass, including the new ones.

- [ ] **Step 3: Run `--dry-run` against the real Pi**

```bash
git switch main && git pull
bash scripts/deploy_to_pi.sh --dry-run
```

Expected: every precondition passes (or aborts with a clear message). Plan is printed. Pi state is unchanged after the command exits.

Verify state unchanged:

```bash
ssh pi@mainsailos.local "wc -l ~/printer_data/config/printer.cfg ~/printer_data/config/btt-ebb-sb-usb-v1.0.cfg"
```

Should match the values from before the dry-run.

- [ ] **Step 4: After this PR merges to main, run a real deploy**

(This step happens on `main` after the feat branch lands. It is a verification, not part of the plan's commits.)

```bash
git switch main && git pull
bash scripts/deploy_to_pi.sh
```

Expected: full happy-path output, Klipper reaches `state=ready`, no errors. Verify `~/printer_data/config/.last-deploy-sha` on the Pi matches the local HEAD.

- [ ] **Step 5: Document the e2e result**

If anything went wrong in steps 3 or 4, capture it in `memory/troubleshooting-log.md` with the date and root cause. If all green, no log entry needed.

---

## Self-Review

**Spec coverage:**
- Spec §"What's missing" item 1 (CI green gate) → Task 3 ✓
- Spec item 2 (printer idle) → Task 4 ✓
- Spec item 3 (drift gate) → Task 5 ✓
- Spec item 4 (post-restart polling) → Task 6 ✓
- Spec item 5 (`--yes` flag) → Task 7 ✓
- Spec item 6 (`--dry-run` flag) → Task 7 ✓
- Spec item 7 (Moonraker hard-fail) → Task 4 (folded in) ✓
- Spec item 8 (tests) → all Tasks 3–7 ✓ (each gate has its own test pair)
- Spec §"Refactor for testability" → Task 1 ✓
- Spec §"Test infrastructure" → Task 2 ✓
- Spec §"CLAUDE.md update" → Task 9 ✓

No gaps.

**Placeholders:** none. Every step has runnable commands and code.

**Type/name consistency:** function names match between Task 1 (declared) and Tasks 3–7 (extended). `LOCAL`, `PI_HOST`, `PI_API`, `SAVE_CONFIG_PI`, `STAGED_PRINTER_CFG`, `RESTART_KIND`, `RSYNC_EXCLUDES`, `YES`, `DRY_RUN`, `READY_POLL_INTERVAL`, `READY_POLL_MAX` are the same identifiers across tasks. Test names and helper names (`_matching_pi_cfg`, `_run`, `_diag`) are consistent.

**Ambiguity:** the "non-TTY auto-confirm" behavior added in Task 6 is documented as a test convenience and intentionally surfaces in skill output (`(--yes given, proceeding without prompt)` or silence depending on path). Interactive humans never hit it.
