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
    body = (REPO / "config" / "printer.cfg").read_text().split(marker)[0]
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


def test_aborts_when_tree_dirty_unstaged():
    """Working tree has unstaged changes -> abort."""
    r = _run(env={"FAKE_GIT_DIRTY": "1"})
    assert r.returncode == 1, _diag(r)
    assert "not clean" in r.stderr, _diag(r)


def test_aborts_when_tree_dirty_staged():
    """Working tree has staged changes -> abort."""
    r = _run(env={"FAKE_GIT_CACHED_DIRTY": "1"})
    assert r.returncode == 1, _diag(r)
    assert "not clean" in r.stderr, _diag(r)


def test_aborts_when_local_ahead_of_origin():
    """Local main diverges from origin/main -> abort."""
    r = _run(
        env={
            "FAKE_GIT_LOCAL_SHA": "aaaa1111",
            "FAKE_GIT_REMOTE_SHA": "bbbb2222",
        }
    )
    assert r.returncode == 1, _diag(r)
    assert "not in sync with origin/main" in r.stderr, _diag(r)


def test_aborts_when_ssh_unreachable():
    """Pi unreachable via keyed SSH -> abort."""
    r = _run(env={"FAKE_SSH_REACHABLE": "0"})
    assert r.returncode == 1, _diag(r)
    assert "can't reach" in r.stderr, _diag(r)


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
    """Run still in progress: status=in_progress, conclusion="". Should refuse."""
    env = {
        "FAKE_GH_RESPONSE": "in_progress",
        "FAKE_LOG_DIR": str(fake_log),
    }
    r = _run(env=env)
    assert r.returncode == 1, _diag(r)
    assert "is in_progress" in r.stderr, _diag(r)


def test_aborts_when_ci_response_malformed():
    """gh schema change breaks the headSha/status/conclusion shape."""
    r = _run(env={"FAKE_GH_RESPONSE": "malformed"})
    assert r.returncode == 1, _diag(r)
    assert "could not parse latest CI run" in r.stderr, _diag(r)


def test_aborts_when_ci_run_is_for_different_commit():
    """gh returns a run for a different commit than HEAD (CI hasn't dispatched yet)."""
    r = _run(env={"FAKE_GH_RESPONSE": "stale"})
    assert r.returncode == 1, _diag(r)
    assert "not HEAD" in r.stderr, _diag(r)


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


def test_drift_gate_ignores_whitespace_only_differences():
    """Mainsail saves with trailing whitespace pre-commit strips here.

    The gate's intent is semantic drift, not whitespace round-trip noise.
    """
    marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
    body = (REPO / "config" / "printer.cfg").read_text().split(marker)[0]
    # Add trailing whitespace to most lines, like Mainsail does.
    body_with_ws = "\n".join(
        line + "   \t" if line.strip() else line for line in body.split("\n")
    )
    fake_pi_cfg = body_with_ws + marker + "\n#*# [heater_bed]\n"
    r = _run(env={"FAKE_PI_PRINTER_CFG": fake_pi_cfg})
    assert "drift" not in r.stderr.lower(), _diag(r)
    assert "sync-from-pi" not in r.stderr.lower(), _diag(r)


def test_chooses_firmware_restart_on_non_macro_change(fake_log):
    """A non-macro/non-archive file in the diff routes to firmware_restart."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LAST_DEPLOY_SHA": "abcd1234",
        "FAKE_GIT_DIFF_FILES": "eddy.cfg",
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env)
    assert r.returncode == 0, _diag(r)
    log = fake_log.read_text()
    assert "/printer/firmware_restart" in log, log
    assert "/printer/restart" not in log.replace("/printer/firmware_restart", ""), log


def test_corrupt_deploy_marker_defaults_to_firmware_restart(fake_log):
    """Unrecognized marker SHA -> git diff fails -> firmware_restart default."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LAST_DEPLOY_SHA": "deadbeef",
        "FAKE_GIT_DIFF_ERROR": "1",
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env)
    assert r.returncode == 0, _diag(r)
    # User must be warned that we fell back to fresh-deploy treatment.
    assert "not in git history" in r.stderr, _diag(r)
    # And the safe restart kind must have been chosen.
    log = fake_log.read_text()
    assert "/printer/firmware_restart" in log, log


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


def test_fails_when_klipper_never_returns_ready(fake_log):
    """Klipper stays in 'startup' state past the poll deadline -> exit 3."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_PRINTER_INFO_JSON": '{"result":{"state":"startup","state_message":"still starting"}}',
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "2",
    }
    r = _run(env=env)
    assert r.returncode == 3, _diag(r)
    assert "did not reach 'ready'" in r.stderr, _diag(r)


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
    # And the "Deploy complete" message must not appear in --dry-run output
    assert "Deploy complete" not in r.stdout, _diag(r)


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


def test_exit_code_2_on_rsync_failure(fake_log):
    """rsync fails partway through -> exit 2 with mid-deploy message."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "FAKE_RSYNC_OK": "0",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 2, _diag(r)
    assert "rsync failed mid-deploy" in r.stderr, _diag(r)


def test_exit_code_2_on_scp_failure(fake_log):
    """scp of staged printer.cfg fails -> exit 2."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "FAKE_SCP_OK": "0",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 2, _diag(r)
    assert "scp of staged printer.cfg failed" in r.stderr, _diag(r)


def test_exit_code_2_on_marker_write_failure(fake_log):
    """ssh write of .last-deploy-sha fails -> exit 2."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "FAKE_MARKER_WRITE_OK": "0",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 2, _diag(r)
    assert "failed to write deploy marker" in r.stderr, _diag(r)


def test_deploy_excludes_noise_files(fake_log, tmp_path):
    """rsync source is config/ — firmware/ and archive/ must be excluded, printer.cfg handled separately."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 0, _diag(r)
    log = fake_log.read_text()
    # Inside config/ these three paths must always be excluded
    assert "--exclude=/firmware/" in log, log
    assert "--exclude=/archive/" in log, log
    assert "--exclude=printer.cfg" in log, log


def test_aborts_when_pi_symlink_discovery_fails():
    """ssh/find failure must hard-fail, not silently deploy without excludes.

    Falling back to "no excludes" would destructively overwrite every
    symlink under ~/printer_data/config/ — exactly what discover_pi_symlinks
    exists to prevent.
    """
    r = _run(env={"FAKE_SSH_FIND_OK": "0", "FAKE_PI_PRINTER_CFG": _matching_pi_cfg()})
    assert r.returncode == 1, _diag(r)
    assert "could not discover Pi-side symlinks" in r.stderr, _diag(r)


def test_deploy_excludes_pi_side_symlinks(fake_log):
    """Symlinks discovered on the Pi must be added to rsync excludes."""
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
        "FAKE_PI_SYMLINKS": "mmu/base/mmu_cut_tip.cfg\nmainsail.cfg\nmmu/base/some_new_symlink.cfg",
        "READY_POLL_INTERVAL": "0",
        "READY_POLL_MAX": "3",
    }
    r = _run(env=env, args=["--yes"])
    assert r.returncode == 0, _diag(r)
    log = fake_log.read_text()
    assert "--exclude=/mmu/base/mmu_cut_tip.cfg" in log, log
    assert "--exclude=/mainsail.cfg" in log, log
    # Pi symlinks that don't appear in any static list (drift-resistant)
    assert "--exclude=/mmu/base/some_new_symlink.cfg" in log, log


def test_dry_run_does_not_print_deploy_complete(fake_log):
    env = {
        "FAKE_PI_PRINTER_CFG": _matching_pi_cfg(),
        "FAKE_LOG_DIR": str(fake_log),
    }
    r = _run(env=env, args=["--dry-run"])
    assert r.returncode == 0, _diag(r)
    assert "Deploy complete" not in r.stdout, _diag(r)
