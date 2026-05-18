"""Integration tests for scripts/macro_refcheck.py."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RC = REPO / "scripts" / "macro_refcheck.py"
FIXTURES = REPO / "tests" / "fixtures"


def run(*args):
    return subprocess.run(
        [sys.executable, str(RC), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def _diag(r):
    return f"rc={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


def test_good_cfg_exits_zero():
    r = run(str(FIXTURES / "macros_good.cfg"))
    assert r.returncode == 0, _diag(r)


def test_bad_refs_flags_unknown_macro():
    r = run(str(FIXTURES / "macros_bad_refs.cfg"))
    assert r.returncode == 1, _diag(r)
    assert "THIS_MACRO_DOES_NOT_EXIST" in r.stdout, _diag(r)
    assert "CALLER_BAD" in r.stdout, _diag(r)
    # Diagnostic includes the file:line where the bad reference is
    assert "macros_bad_refs.cfg:" in r.stdout, _diag(r)


def test_no_args_is_error():
    """Empty arg list must not silently pass."""
    r = run()
    assert r.returncode == 2, _diag(r)
    assert "no files specified" in r.stderr


def test_nonexistent_path_is_error():
    """A missing file must not silently pass — it's almost always a typo."""
    r = run("does_not_exist.cfg")
    assert r.returncode == 2, _diag(r)
    assert "file not found" in r.stderr
    assert "does_not_exist.cfg" in r.stderr


def test_rename_existing_is_treated_as_defining(tmp_path):
    """rename_existing: Y -> Y becomes callable."""
    cfg = tmp_path / "rename_chain.cfg"
    cfg.write_text(
        "[gcode_macro M109]\n"
        "rename_existing: M99109\n"
        "gcode:\n"
        "    G4 P1\n"
        "\n"
        "[gcode_macro CALLER]\n"
        "gcode:\n"
        "    M99109\n"
    )
    r = run(str(cfg))
    assert r.returncode == 0, _diag(r)


def test_builtins_has_expected_klipper_commands():
    """tests/builtins.txt sanity-check after `make builtins`.

    The shell one-liner that generates this file has no test of its own,
    so this guards against a future Klipper refactor that breaks the
    cmd_<NAME>_help regex (e.g., type-annotated declarations) silently
    producing an empty or partial builtins list.
    """
    builtins_txt = REPO / "tests" / "builtins.txt"
    assert builtins_txt.exists()
    builtins = {
        line.strip()
        for line in builtins_txt.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    expected = {
        "BED_MESH_CALIBRATE",
        "PROBE",
        "QUAD_GANTRY_LEVEL",
        "TEMPERATURE_WAIT",
        "SAVE_CONFIG",
    }
    missing = expected - builtins
    assert not missing, (
        f"tests/builtins.txt is missing expected commands: {sorted(missing)}. "
        "Likely a regression in the `make builtins` shell extractor."
    )


def test_real_repo_passes():
    """The repo's actual configs must pass macro_refcheck."""
    import glob

    cfgs = (
        sorted(glob.glob("config/*.cfg"))
        + sorted(glob.glob("config/macros/*.cfg"))
        + sorted(glob.glob("config/mmu/base/*.cfg"))
        + sorted(glob.glob("config/mmu/addons/*.cfg"))
        + sorted(glob.glob("config/mmu/optional/*.cfg"))
    )
    assert any(c.endswith("printer.cfg") for c in cfgs), (
        "config/*.cfg glob did not match printer.cfg — directory renamed?"
    )
    r = run(*cfgs)
    assert r.returncode == 0, f"stdout={r.stdout!r}"
