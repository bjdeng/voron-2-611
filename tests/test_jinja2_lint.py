"""Integration tests for scripts/jinja2_lint.py."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LINT = REPO / "scripts" / "jinja2_lint.py"
FIXTURES = REPO / "tests" / "fixtures"


def run(*args):
    return subprocess.run(
        [sys.executable, str(LINT), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def test_good_cfg_exits_zero():
    r = run(str(FIXTURES / "macros_good.cfg"))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_bad_jinja_exits_one_and_names_macro():
    r = run(str(FIXTURES / "macros_bad_jinja.cfg"))
    assert r.returncode == 1
    assert "BROKEN_IF" in r.stdout
    assert "macros_bad_jinja.cfg:" in r.stdout


def test_real_repo_passes():
    """The repo's actual configs must pass jinja2_lint."""
    import glob

    cfgs = (
        ["printer.cfg", "eddy.cfg", "btt-ebb-sb-usb-v1.0.cfg"]
        + sorted(glob.glob("macros/*.cfg"))
        + sorted(glob.glob("mmu/base/*.cfg"))
        + sorted(glob.glob("mmu/addons/*.cfg"))
        + sorted(glob.glob("mmu/optional/*.cfg"))
    )
    r = run(*cfgs)
    assert r.returncode == 0, f"stdout={r.stdout!r}"
