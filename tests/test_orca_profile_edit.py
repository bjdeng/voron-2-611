"""Integration tests for scripts/orca_profile_edit.py."""

import os
import shutil
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


def test_get_scalar_from_array_value():
    r = run("--get", "nozzle_temperature", "--profile", "Inland PLA")
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "210", _diag(r)


def test_get_via_file():
    path = ORCA_DIR / "000" / "filament" / "Inland PLA.json"
    r = run("--get", "filament_flow_ratio", "--file", str(path))
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "0.95", _diag(r)


def test_get_missing_key_errors():
    r = run("--get", "no_such_key", "--profile", "Inland PLA")
    assert r.returncode == 2, _diag(r)
    assert "key not found" in r.stderr, _diag(r)


def _fake_pgrep(tmp_path, found: bool):
    """Return an env dict whose PATH front-loads a fake pgrep.

    found=False -> pgrep exits 1 (not running); found=True -> exits 0.
    """
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    pg = d / "pgrep"
    pg.write_text("#!/bin/sh\nexit %d\n" % (0 if found else 1))
    pg.chmod(0o755)
    return {"PATH": f"{d}{os.pathsep}{os.environ['PATH']}"}


def _copy_fixture(tmp_path):
    dst = tmp_path / "Inland PLA.json"
    shutil.copy2(ORCA_DIR / "000" / "filament" / "Inland PLA.json", dst)
    return dst


def test_set_preserves_array_container(tmp_path):
    path = _copy_fixture(tmp_path)
    env = _fake_pgrep(tmp_path, found=False)
    r = run("--set", "nozzle_temperature=205", "--file", str(path), env=env)
    assert r.returncode == 0, _diag(r)
    import json as _j

    data = _j.loads(path.read_text())
    assert data["nozzle_temperature"] == ["205"], data
    # untouched keys preserved
    assert data["filament_flow_ratio"] == ["0.95"], data


def test_set_writes_backup(tmp_path):
    path = _copy_fixture(tmp_path)
    env = _fake_pgrep(tmp_path, found=False)
    r = run("--set", "filament_flow_ratio=0.98", "--file", str(path), env=env)
    assert r.returncode == 0, _diag(r)
    bak = path.with_suffix(".json.bak")
    assert bak.is_file(), "expected .bak file"
    import json as _j

    assert _j.loads(bak.read_text())["filament_flow_ratio"] == [
        "0.95"
    ], "bak holds old value"


def test_set_bad_format_errors(tmp_path):
    path = _copy_fixture(tmp_path)
    env = _fake_pgrep(tmp_path, found=False)
    r = run("--set", "nozzle_temperature", "--file", str(path), env=env)
    assert r.returncode == 1, _diag(r)
    assert "KEY=VALUE" in r.stderr, _diag(r)
