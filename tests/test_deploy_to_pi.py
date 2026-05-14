"""Integration tests for scripts/deploy_to_pi.sh.

Uses PATH-override fake binaries (tests/fake_bin/*) to simulate ssh/scp/
curl/gh/git responses. Each fake reads its behavior from env vars set
per-test and logs its invocations to a file the test can inspect.
"""

import os
import subprocess
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


def _matching_pi_cfg():
    """Build a Pi printer.cfg whose body matches repo's body + a fake SAVE_CONFIG tail."""
    marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
    body = (REPO / "printer.cfg").read_text().split(marker)[0]
    return body + marker + "\n#*# [heater_bed]\n#*# control = pid\n"


@pytest.fixture
def fake_log(tmp_path):
    """A temp file the fakes append their invocations to.

    Tests inject this into `_run(env=...)` via FAKE_LOG_DIR and inspect
    the resulting log to verify which calls the script made.
    """
    log_path = tmp_path / "fake_invocations.log"
    log_path.touch()
    return log_path


def test_aborts_when_not_on_main():
    """Smoke test: with fake git reporting we're on a feat branch, abort."""
    r = _run(env={"FAKE_GIT_BRANCH": "feat/something"})
    assert r.returncode == 1, _diag(r)
    assert "refuses to run from 'feat/something'" in r.stderr, _diag(r)


def test_aborts_when_ci_red():
    r = _run(env={"FAKE_GH_RESPONSE": "failure"})
    assert r.returncode == 1, _diag(r)
    assert "CI not green" in r.stderr, _diag(r)


def test_aborts_when_ci_missing():
    r = _run(env={"FAKE_GH_RESPONSE": "none"})
    assert r.returncode == 1, _diag(r)
    assert "CI not green" in r.stderr, _diag(r)


def test_ci_skipped_counts_as_pass(fake_log):
    """Klippy parse + smoke is intentionally skipped today (Open Investigation #7)."""
    r = _run(
        env={
            "FAKE_GH_RESPONSE": "skipped",
            "FAKE_LOG_DIR": str(fake_log),
            "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        }
    )
    # CI gate must NOT have been the reason for any non-zero exit.
    assert "CI not green" not in r.stderr, _diag(r)
    # The gate WAS exercised: fake gh was invoked.
    log = fake_log.read_text()
    assert "gh run list" in log, log


def test_aborts_when_ci_in_progress(fake_log):
    """Run still in progress: conclusion is null, message should say in progress."""
    # Override the gh fake to return an in-progress run.
    env = {
        "FAKE_GH_RESPONSE": "in_progress",
        "FAKE_LOG_DIR": str(fake_log),
    }
    r = _run(env=env)
    assert r.returncode == 1, _diag(r)
    assert "still in progress" in r.stderr, _diag(r)


def test_aborts_when_moonraker_unreachable():
    r = _run(env={"FAKE_MOONRAKER_REACHABLE": "0"})
    assert r.returncode == 1, _diag(r)
    assert "Moonraker not reachable" in r.stderr, _diag(r)


def test_aborts_when_printer_printing():
    r = _run(
        env={
            "FAKE_PRINT_STATS_JSON": '{"result":{"status":{"print_stats":{"state":"printing"}}}}',
        }
    )
    assert r.returncode == 1, _diag(r)
    assert "printer is not idle" in r.stderr.lower(), _diag(r)


def test_aborts_when_printer_paused():
    r = _run(
        env={
            "FAKE_PRINT_STATS_JSON": '{"result":{"status":{"print_stats":{"state":"paused"}}}}',
        }
    )
    assert r.returncode == 1, _diag(r)
    assert "printer is not idle" in r.stderr.lower(), _diag(r)


def test_aborts_when_print_stats_malformed():
    """Moonraker returns JSON without the expected key path -- defensive fallback."""
    r = _run(env={"FAKE_PRINT_STATS_JSON": '{"result":{"status":{}}}'})
    assert r.returncode == 1, _diag(r)
    assert "could not parse print_stats" in r.stderr.lower(), _diag(r)


def test_aborts_when_pi_has_drift():
    """Pi's printer.cfg body differs from origin/main's body."""
    fake_pi_cfg = (
        "[printer]\n"
        "max_velocity: 999   # someone-edited-on-pi\n"
        "\n"
        "#*# <---------------------- SAVE_CONFIG ---------------------->\n"
        "#*# [heater_bed]\n"
    )
    r = _run(env={"FAKE_PI_PRINTER_CFG": fake_pi_cfg})
    assert r.returncode == 1, _diag(r)
    combined = (r.stderr + r.stdout).lower()
    assert "drift" in combined or "sync-from-pi" in combined, _diag(r)


def test_drift_gate_passes_when_pi_matches_repo():
    """Pi's printer.cfg body matches origin/main's body — gate passes."""
    r = _run(env={"FAKE_PI_PRINTER_CFG": _matching_pi_cfg()})
    # Drift gate must not be the reason for any non-zero exit.
    assert "drift" not in r.stderr.lower(), _diag(r)
    assert "sync-from-pi" not in r.stderr.lower(), _diag(r)


def test_succeeds_when_klipper_returns_ready(fake_log):
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_PRINTER_INFO_JSON": '{"result":{"state":"ready","state_message":"Printer is ready"}}',
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env)
    assert r.returncode == 0, _diag(r)
    assert "state=ready" in r.stdout, _diag(r)


def test_fails_when_klipper_returns_error(fake_log):
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_PRINTER_INFO_JSON": '{"result":{"state":"error","state_message":"Invalid pin description"}}',
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env)
    assert r.returncode == 3, _diag(r)
    assert "Invalid pin description" in r.stderr, _diag(r)


def test_dry_run_touches_nothing_on_pi(fake_log):
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
    }
    r = _run(env=env, args=["--dry-run"])
    assert r.returncode == 0, _diag(r)
    log_contents = fake_log.read_text() if fake_log.exists() else ""
    # Plan summary should be printed even in dry-run mode
    assert "--dry-run" in r.stdout.lower() or "dry-run" in r.stdout.lower(), _diag(r)
    # But no rsync/scp invocations should have hit the (fake) Pi
    assert "rsync " not in log_contents, log_contents
    assert "scp " not in log_contents, log_contents


def test_yes_flag_skips_confirmation(fake_log):
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 0, _diag(r)
    # Prove the --yes branch was taken, not just the non-TTY auto-confirm fallback.
    assert "--yes given" in r.stdout, _diag(r)


def test_exit_code_2_on_mid_flight_restart_failure(fake_log):
    """Moonraker restart call fails -> exit 2 (mid-flight, not precondition)."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "FAKE_RESTART_OK": "0",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 2, _diag(r)
    assert "Moonraker restart call failed" in r.stderr, _diag(r)
