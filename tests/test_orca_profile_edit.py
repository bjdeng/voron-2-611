"""Integration tests for scripts/orca_profile_edit.py."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "orca_profile_edit.py"
ORCA_DIR = REPO / "tests" / "fixtures" / "orca" / "user"


def run(*args, env=None):
    full = dict(os.environ)
    full["ORCA_USER_DIR"] = str(ORCA_DIR)
    if env:
        full.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=full,
    )


def _diag(r):
    return f"rc={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


def test_find_unique():
    r = run("--find", "Inland PLA")
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip().endswith("filament/Inland PLA.json"), _diag(r)


def test_find_missing_errors():
    r = run("--find", "No Such Filament")
    assert r.returncode == 2, _diag(r)
    assert "not found" in r.stderr, _diag(r)
