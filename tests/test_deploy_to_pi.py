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
