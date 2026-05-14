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


def test_eddy_ng_allowlist_coupling():
    """Tripwire for the eddy migration.

    The eddy-ng commands live in scripts/macro_refcheck.py's ALLOWLIST
    in a block keyed to the [probe_eddy_ng] section in eddy.cfg. When
    that section is removed by the eddy migration PR, the ALLOWLIST
    block must be deleted in the same PR; otherwise refcheck silently
    keeps approving callers of PROBE_EDDY_NG_* that no longer resolve.

    This test asserts the coupling is intact: (a) the ALLOWLIST contains
    the eddy-ng commands, (b) macros/print_start.cfg actually calls one
    of them. If (a) is removed without removing (b), refcheck will flag
    the unresolved caller and CI fails. If both are removed together
    (the correct migration), this test will need to be deleted too
    (which forces the migration author to think about the coupling).
    """
    # Load the script module to inspect its ALLOWLIST.
    import importlib.util

    spec = importlib.util.spec_from_file_location("rc", RC)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    eddy_cmds = {
        "PROBE_EDDY_NG_TAP",
        "PROBE_EDDY_NG_PROBE",
        "PROBE_EDDY_NG_CALIBRATE",
        "PROBE_EDDY_NG_STATUS",
        "PROBE_EDDY_NG_SET_TAP_OFFSET",
    }
    assert (
        eddy_cmds <= mod.ALLOWLIST
    ), "eddy-ng ALLOWLIST block has drifted from expected commands"

    # Confirm callers exist — removing ALLOWLIST without these would be a real bug
    print_start = (REPO / "macros" / "print_start.cfg").read_text()
    assert "PROBE_EDDY_NG_TAP" in print_start, (
        "macros/print_start.cfg no longer calls PROBE_EDDY_NG_TAP — "
        "if this is the eddy migration, also remove eddy_cmds from "
        "scripts/macro_refcheck.py ALLOWLIST and delete this test."
    )


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
        [
            "printer.cfg",
            "eddy.cfg",
            "btt-ebb-sb-usb-v1.0.cfg",
            "mainsail.cfg",
            "timelapse.cfg",
        ]
        + sorted(glob.glob("macros/*.cfg"))
        + sorted(glob.glob("mmu/base/*.cfg"))
        + sorted(glob.glob("mmu/addons/*.cfg"))
        + sorted(glob.glob("mmu/optional/*.cfg"))
    )
    r = run(*cfgs)
    assert r.returncode == 0, f"stdout={r.stdout!r}"
