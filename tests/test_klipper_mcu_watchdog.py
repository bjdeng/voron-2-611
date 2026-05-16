"""Tests for scripts/klipper-mcu-watchdog.sh.

Exercises the script's subcommands (`expected`, `missing`, `map`, `learn`)
via subprocess. Bash internals like the daemon loop and hub rebind aren't
testable here (they require root + a real Pi); those are exercised manually
via the install + smoke-test path documented in scripts/install-mcu-watchdog.sh
and GH issue #37.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "klipper-mcu-watchdog.sh"


def _run(args, env=None, cwd=None):
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd or REPO,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _diag(r):
    return f"rc={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


# ───────────────────────── parse_expected_serials ─────────────────────────


def test_expected_parses_single_mcu(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_lpc1769_AAA-if00
            baud: 250000
            """
        ).lstrip()
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "usb-Klipper_lpc1769_AAA-if00", _diag(r)


def test_expected_parses_multiple_mcu_sections(tmp_path):
    """[mcu], [mcu z], [mcu EBB] all yield their serial basenames."""
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_lpc1769_MAIN-if00

            [mcu z]
            serial: /dev/serial/by-id/usb-Klipper_lpc1769_ZAXIS-if00

            [printer]
            kinematics: corexy

            [mcu EBB]
            serial: /dev/serial/by-id/usb-Klipper_rp2040_TOOLHEAD-if00
            """
        ).lstrip()
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    serials = set(r.stdout.strip().splitlines())
    assert serials == {
        "usb-Klipper_lpc1769_MAIN-if00",
        "usb-Klipper_lpc1769_ZAXIS-if00",
        "usb-Klipper_rp2040_TOOLHEAD-if00",
    }, _diag(r)


def test_expected_follows_includes(tmp_path):
    """[mcu] sections in [include]d files are parsed too."""
    cfg = tmp_path / "printer.cfg"
    inc = tmp_path / "extras.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [include extras.cfg]

            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_main-if00
            """
        ).lstrip()
    )
    inc.write_text(
        textwrap.dedent(
            """
            [mcu eddy]
            serial: /dev/serial/by-id/usb-Klipper_eddy-if00
            """
        ).lstrip()
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    serials = set(r.stdout.strip().splitlines())
    assert serials == {"usb-Klipper_main-if00", "usb-Klipper_eddy-if00"}, _diag(r)


def test_expected_follows_include_globs(tmp_path):
    """[include foo/*.cfg] wildcard expansion matches Klipper's behavior."""
    cfg = tmp_path / "printer.cfg"
    (tmp_path / "mmu").mkdir()
    (tmp_path / "mmu" / "a.cfg").write_text(
        "[mcu mmu]\nserial: /dev/serial/by-id/usb-Klipper_mmu-if00\n"
    )
    (tmp_path / "mmu" / "b.cfg").write_text("[printer]\nkinematics: corexy\n")
    cfg.write_text(
        textwrap.dedent(
            """
            [include mmu/*.cfg]

            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_main-if00
            """
        ).lstrip()
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    serials = set(r.stdout.strip().splitlines())
    assert serials == {"usb-Klipper_main-if00", "usb-Klipper_mmu-if00"}, _diag(r)


def test_expected_ignores_non_mcu_serial(tmp_path):
    """A `serial:` key OUTSIDE an [mcu] section must not be picked up
    (e.g. some [extruder] / [tmc2209] sections have a `serial:` style key).
    """
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [extruder]
            serial: /dev/serial/by-id/this-is-not-an-mcu-if00

            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_real-if00
            """
        ).lstrip()
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "usb-Klipper_real-if00", _diag(r)


def test_expected_handles_inline_comment(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        "[mcu]\nserial: /dev/serial/by-id/usb-Klipper_AAA-if00   # comment here\n"
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "usb-Klipper_AAA-if00", _diag(r)


def test_expected_handles_missing_file(tmp_path):
    """Missing printer.cfg → non-zero exit + ERR on stderr."""
    r = _run(["expected", str(tmp_path / "nonexistent.cfg")])
    assert r.returncode != 0, _diag(r)
    assert "not readable" in r.stderr, _diag(r)


def test_expected_yields_one_per_mcu_section(tmp_path):
    """If an [mcu] section has multiple `serial:` lines, only the first counts."""
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_first-if00
            serial: /dev/serial/by-id/usb-Klipper_second-if00
            """
        ).lstrip()
    )
    r = _run(["expected", str(cfg)])
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "usb-Klipper_first-if00", _diag(r)


def test_expected_parses_real_repo_printer_cfg():
    """Sanity-check against the real printer.cfg in this repo.

    Confirms all 5 expected MCUs are found (main, z, EBB, eddy, mmu).
    Locks in the contract: parser handles real Klipper + Happy Hare includes.
    """
    r = _run(["expected", str(REPO / "config" / "printer.cfg")])
    assert r.returncode == 0, _diag(r)
    serials = set(r.stdout.strip().splitlines())
    # Don't hardcode the 5 serial strings; just assert count + shape.
    assert (
        len(serials) == 5
    ), f"expected 5 MCUs in real config, got {len(serials)}: {serials}"
    assert all(s.startswith("usb-Klipper_") for s in serials), serials
    assert all(s.endswith("-if00") for s in serials), serials


# ───────────────────────── missing_serials ─────────────────────────


def test_missing_returns_diff_when_some_present(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_A-if00

            [mcu z]
            serial: /dev/serial/by-id/usb-Klipper_B-if00

            [mcu eddy]
            serial: /dev/serial/by-id/usb-Klipper_C-if00
            """
        ).lstrip()
    )
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    # Only A is "present"
    (by_id / "usb-Klipper_A-if00").touch()
    r = _run(
        ["missing"],
        env={"PRINTER_CFG": str(cfg), "SERIAL_BY_ID_DIR": str(by_id)},
    )
    assert r.returncode == 0, _diag(r)
    missing = set(r.stdout.strip().splitlines())
    assert missing == {"usb-Klipper_B-if00", "usb-Klipper_C-if00"}, _diag(r)


def test_missing_empty_when_all_present(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text("[mcu]\nserial: /dev/serial/by-id/usb-Klipper_A-if00\n")
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    (by_id / "usb-Klipper_A-if00").touch()
    r = _run(
        ["missing"],
        env={"PRINTER_CFG": str(cfg), "SERIAL_BY_ID_DIR": str(by_id)},
    )
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "", _diag(r)


def test_missing_yields_all_when_none_present(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text("[mcu]\nserial: /dev/serial/by-id/usb-Klipper_A-if00\n")
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    r = _run(
        ["missing"],
        env={"PRINTER_CFG": str(cfg), "SERIAL_BY_ID_DIR": str(by_id)},
    )
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "usb-Klipper_A-if00", _diag(r)


def test_missing_handles_absent_by_id_dir(tmp_path):
    """If /dev/serial/by-id/ doesn't exist (no USB devices), all are missing."""
    cfg = tmp_path / "printer.cfg"
    cfg.write_text("[mcu]\nserial: /dev/serial/by-id/usb-Klipper_A-if00\n")
    nonexistent = tmp_path / "nonexistent"
    r = _run(
        ["missing"],
        env={"PRINTER_CFG": str(cfg), "SERIAL_BY_ID_DIR": str(nonexistent)},
    )
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "usb-Klipper_A-if00", _diag(r)


# ───────────────────────── check subcommand (exit code) ─────────────────────────


def test_check_exits_0_when_all_present(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text("[mcu]\nserial: /dev/serial/by-id/usb-Klipper_A-if00\n")
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    (by_id / "usb-Klipper_A-if00").touch()
    r = _run(
        ["check"],
        env={"PRINTER_CFG": str(cfg), "SERIAL_BY_ID_DIR": str(by_id)},
    )
    assert r.returncode == 0, _diag(r)


def test_check_exits_1_when_some_missing(tmp_path):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        "[mcu]\nserial: /dev/serial/by-id/usb-Klipper_A-if00\n"
        "[mcu z]\nserial: /dev/serial/by-id/usb-Klipper_B-if00\n"
    )
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    (by_id / "usb-Klipper_A-if00").touch()
    r = _run(
        ["check"],
        env={"PRINTER_CFG": str(cfg), "SERIAL_BY_ID_DIR": str(by_id)},
    )
    assert r.returncode == 1, _diag(r)


# ───────────────────────── map subcommand ─────────────────────────


def test_map_prints_state_file_contents(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "mcu-hub-map"
    state_file.write_text("usb-Klipper_A-if00 1-1.3\n" "usb-Klipper_B-if00 1-1.4\n")
    r = _run(["map"], env={"STATE_DIR": str(state_dir)})
    assert r.returncode == 0, _diag(r)
    assert "usb-Klipper_A-if00 1-1.3" in r.stdout, _diag(r)
    assert "usb-Klipper_B-if00 1-1.4" in r.stdout, _diag(r)


def test_map_empty_when_state_absent(tmp_path):
    """`map` on a fresh install (no state file yet) emits nothing + exits 0."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    r = _run(["map"], env={"STATE_DIR": str(state_dir)})
    assert r.returncode == 0, _diag(r)
    assert r.stdout.strip() == "", _diag(r)


# ───────────────────────── learn / discover_hub_for_serial ─────────────────────────


def test_learn_records_correct_hub_per_serial(tmp_path):
    """End-to-end smoke test of `learn`: builds a fake /dev/serial/by-id
    tree pointing at a fake sysfs layout that mirrors what the Pi shows
    (devices at 1-1.3.X under hub 1-1.3, devices at 1-1.4.X under 1-1.4).
    Verifies the state file ends up with correct hub assignments per serial.

    This is a regression test for the bug where every serial got mapped
    to the same too-shallow hub (`1-1` instead of `1-1.3` / `1-1.4`)
    when `discover_hub_for_serial` used a fragile udevadm-path regex.
    """
    # Build fake sysfs: /sys/class/tty/ttyACM<N>/device → interface dir
    # at ../bus/usb/devices/1-1.X.Y/1-1.X.Y:1.0
    sysfs = tmp_path / "sys"
    devices_dir = sysfs / "bus" / "usb" / "devices"
    tty_dir = sysfs / "class" / "tty"
    devices_dir.mkdir(parents=True)
    tty_dir.mkdir(parents=True)
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()

    # Three MCUs across two hubs. cases: (serial, hub_path, leaf_port, tty_idx)
    layout = [
        ("usb-Klipper_lpc_A-if00", "1-1.3", "1-1.3.4", 0),
        ("usb-Klipper_samd_B-if00", "1-1.3", "1-1.3.1", 1),
        ("usb-Klipper_rp_C-if00", "1-1.4", "1-1.4.3", 2),
    ]

    for serial, hub, leaf, idx in layout:
        # Mirror sysfs hub + leaf dirs (they don't need contents).
        (devices_dir / hub).mkdir(exist_ok=True)
        leaf_dir = devices_dir / hub / leaf
        leaf_dir.mkdir(exist_ok=True)
        iface = leaf_dir / f"{leaf}:1.0"
        iface.mkdir(exist_ok=True)
        # /sys/class/tty/ttyACMN/device → the interface dir
        tty_name = f"ttyACM{idx}"
        (tty_dir / tty_name).mkdir(parents=True, exist_ok=True)
        (tty_dir / tty_name / "device").symlink_to(iface)
        # /dev/ttyACMN exists as a real file (readlink -f resolves it)
        (dev_dir / tty_name).touch()
        # /dev/serial/by-id/<serial> → /dev/ttyACMN
        (by_id / serial).symlink_to(dev_dir / tty_name)

    # printer.cfg with all three MCUs
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        textwrap.dedent(
            """
            [mcu]
            serial: /dev/serial/by-id/usb-Klipper_lpc_A-if00

            [mcu z]
            serial: /dev/serial/by-id/usb-Klipper_samd_B-if00

            [mcu eddy]
            serial: /dev/serial/by-id/usb-Klipper_rp_C-if00
            """
        ).lstrip()
    )

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # The script uses readlink -f on /sys/class/tty/<name>/device — symlinks
    # already resolve to absolute paths inside tmp_path, so we don't need to
    # remap SYS root. Just point SERIAL_BY_ID_DIR at the fake tree.
    r = _run(
        ["learn"],
        env={
            "PRINTER_CFG": str(cfg),
            "STATE_DIR": str(state_dir),
            "SERIAL_BY_ID_DIR": str(by_id),
            "TTY_CLASS_DIR": str(tty_dir),
        },
    )
    assert r.returncode == 0, _diag(r)

    state_file = state_dir / "mcu-hub-map"
    assert state_file.exists(), f"state file not created: {_diag(r)}"
    mapping = dict(line.split() for line in state_file.read_text().strip().splitlines())
    assert mapping == {
        "usb-Klipper_lpc_A-if00": "1-1.3",
        "usb-Klipper_samd_B-if00": "1-1.3",
        "usb-Klipper_rp_C-if00": "1-1.4",
    }, f"expected per-serial hub, got: {mapping}"


def test_learn_refuses_partial_mapping(tmp_path):
    """If `discover_hub_for_serial` can't resolve every expected MCU,
    `learn_mapping` must leave the existing state file intact rather
    than installing an empty/partial map.
    """
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(
        "[mcu]\nserial: /dev/serial/by-id/usb-Klipper_present-if00\n"
        "[mcu z]\nserial: /dev/serial/by-id/usb-Klipper_absent-if00\n"
    )
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    # No symlinks created → discover_hub_for_serial returns empty for both
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # Seed a good prior state
    (state_dir / "mcu-hub-map").write_text(
        "usb-Klipper_present-if00 1-1.3\nusb-Klipper_absent-if00 1-1.3\n"
    )
    r = _run(
        ["learn"],
        env={
            "PRINTER_CFG": str(cfg),
            "STATE_DIR": str(state_dir),
            "SERIAL_BY_ID_DIR": str(by_id),
        },
    )
    assert r.returncode == 0, _diag(r)
    # Existing map MUST be preserved
    contents = (state_dir / "mcu-hub-map").read_text()
    assert "usb-Klipper_present-if00 1-1.3" in contents, _diag(r)
    assert "only resolved" in r.stderr, _diag(r)


# ───────────────────────── help / unknown ─────────────────────────


def test_help_subcommand_prints_usage():
    r = _run(["help"])
    assert r.returncode == 0, _diag(r)
    assert "klipper-mcu-watchdog" in r.stdout, _diag(r)
    # Document the subcommand surface so future renames don't go unnoticed.
    for sub in ("daemon", "check", "recover", "expected", "missing", "map"):
        assert sub in r.stdout, f"help text missing '{sub}': {_diag(r)}"


def test_unknown_subcommand_exits_nonzero():
    r = _run(["frobnicate"])
    assert r.returncode != 0, _diag(r)
    assert "unknown subcommand" in r.stderr, _diag(r)
