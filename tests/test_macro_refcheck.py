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


def test_good_cfg_exits_zero():
    r = run(str(FIXTURES / "macros_good.cfg"))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_bad_refs_flags_unknown_macro():
    r = run(str(FIXTURES / "macros_bad_refs.cfg"))
    assert r.returncode == 1
    assert "THIS_MACRO_DOES_NOT_EXIST" in r.stdout
    assert "CALLER_BAD" in r.stdout


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
    assert r.returncode == 0, f"stdout={r.stdout!r}"


def test_real_repo_passes():
    """The repo's actual configs must pass macro_refcheck."""
    import glob

    cfgs = (
        ["printer.cfg", "eddy.cfg", "btt-ebb-sb-usb-v1.0.cfg", "timelapse.cfg"]
        + sorted(glob.glob("macros/*.cfg"))
        + sorted(glob.glob("mmu/base/*.cfg"))
        + sorted(glob.glob("mmu/addons/*.cfg"))
        + sorted(glob.glob("mmu/optional/*.cfg"))
    )
    r = run(*cfgs)
    assert r.returncode == 0, f"stdout={r.stdout!r}"
