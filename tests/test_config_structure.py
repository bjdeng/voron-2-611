"""Structural assertions on Klipper .cfg files.

Layer 5 of the test pyramid (see docs/superpowers/specs/2026-05-15-config-macros-refactor.md §5).

These tests run in CI on every PR. They catch refactor mistakes that the
klippy parse (Layer 3) misses — things like deprecated Klipper keys,
missing description: fields (planned), orphan _USER_VARIABLE references
(planned), etc.

This file is created in Phase 1 of the refactor with one initial assertion
(no deprecated Klipper keys). Subsequent phases extend it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _cfg_files() -> list[Path]:
    """All non-archive .cfg files under config/, excluding vendored MMU symlinks.

    Excludes:
    - config/archive/ — historical configs not in active use
    - config/mmu/base/, mmu/optional/, mmu/addons/ — symlinked from Happy Hare
      install. Editing these requires HH-side changes; structural checks here
      would catch HH issues we don't own.
    """
    excluded_path_parts = {"archive", "base", "optional", "addons"}
    return [
        p for p in CONFIG_DIR.rglob("*.cfg") if not (set(p.parts) & excluded_path_parts)
    ]


# Klipper v0.13+ removed these (Config_Changes.md 2025-08-11 entry).
# Patterns are anchored to catch CONFIG-SECTION assignments, which crash at
# load time. Bare gcode-param references (e.g. ACCEL_TO_DECEL=) inside
# jinja2 {% else %} branches that guard `minimum_cruise_ratio is defined`
# are dead code on Klipper v0.13+ and don't crash — those are intentional
# cross-version compatibility in upstream macros (e.g. Ellis TEST_SPEED).
DEPRECATED_CONFIG_KEY_PATTERNS = [
    # Config-section assignment: `max_accel_to_decel: 5000` in [printer]
    # Crashes immediately at Klipper config load.
    (r"^\s*max_accel_to_decel\s*:", "max_accel_to_decel: (use minimum_cruise_ratio:)"),
]


def test_no_deprecated_klipper_config_keys() -> None:
    """No .cfg file uses a config-section key Klipper v0.13+ removed.

    Klipper removed `max_accel_to_decel` config param in v0.13 (Config_Changes.md
    2025-08-11). Use `minimum_cruise_ratio` instead.

    Only flags CONFIG-section assignments (which crash at load). Bare gcode-arg
    references like `ACCEL_TO_DECEL=` inside guarded jinja2 branches are dead
    code on v0.13+ and don't crash — upstream macros (e.g. Ellis TEST_SPEED)
    use this pattern intentionally for old/new compat.

    See vendor/klipper/docs/Config_Changes.md for full deprecation list.
    """
    offenders = []
    for cfg in _cfg_files():
        text = cfg.read_text()
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in DEPRECATED_CONFIG_KEY_PATTERNS:
                if re.search(pattern, line):
                    offenders.append(
                        f"  {cfg.relative_to(REPO_ROOT)}:{lineno}: {label}"
                    )

    assert not offenders, (
        "Deprecated Klipper config keys (removed in v0.13+) found:\n"
        + "\n".join(offenders)
    )
