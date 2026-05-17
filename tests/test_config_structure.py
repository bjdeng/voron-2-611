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

import glob
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


OWNED_MACRO_FILES = sorted(glob.glob(str(REPO_ROOT / "config/macros/*.cfg"))) + [
    str(REPO_ROOT / "config/eddy.cfg"),
    str(REPO_ROOT / "config/mainsail.cfg"),
]


def _parse_macros(cfg_path):
    text = Path(cfg_path).read_text()
    section_re = re.compile(r"^\[gcode_macro\s+(\S+)\]\s*$", re.MULTILINE)
    matches = list(section_re.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        # description: must be a top-level key (no leading whitespace),
        # not just the literal string appearing inside a gcode comment.
        desc = bool(re.search(r"^description:[^\S\n]*\S", body, re.MULTILINE))
        yield name, body, desc


def test_every_owned_macro_has_description():
    """Every [gcode_macro] in config/macros/* and config/eddy.cfg has a non-empty description: field."""
    assert len(OWNED_MACRO_FILES) >= 8, (
        f"OWNED_MACRO_FILES has {len(OWNED_MACRO_FILES)} entries; expected "
        f"≥8 (7 macros/*.cfg + eddy.cfg + mainsail.cfg). Path drift?"
    )
    missing = []
    for cfg in OWNED_MACRO_FILES:
        for name, _body, has_desc in _parse_macros(cfg):
            if not has_desc:
                missing.append(f"{Path(cfg).relative_to(REPO_ROOT)}::{name}")
    assert not missing, f"{len(missing)} macros without description: " + ", ".join(
        missing
    )


def test_status_sections_declared_at_most_once():
    """[respond]/[exclude_object]/[pause_resume]/[display_status] declared at most once in owned files."""
    targets = ("respond", "exclude_object", "pause_resume", "display_status")
    sec_re = {t: re.compile(rf"^\[{t}\]\s*$", re.MULTILINE) for t in targets}
    over = []
    for t in targets:
        hits = []
        for cfg in _cfg_files():
            for _ in sec_re[t].findall(cfg.read_text()):
                hits.append(cfg.relative_to(REPO_ROOT))
        if len(hits) > 1:
            over.append(f"[{t}] declared {len(hits)}x: {hits}")
    assert not over, "; ".join(over)


def test_extruder_section_single_file():
    """[extruder] declared in exactly one owned file (HH's variable-injection block is excluded by _cfg_files())."""
    hits = [
        str(cfg.relative_to(REPO_ROOT))
        for cfg in _cfg_files()
        if re.search(r"^\[extruder\]\s*$", cfg.read_text(), re.MULTILINE)
    ]
    assert len(hits) == 1, f"[extruder] in {hits} (expect exactly one owned file)"


# ---------------------------------------------------------------------------
# Phase 4 PR-B: _USER_VARIABLE reference + definition coherence
# ---------------------------------------------------------------------------

USER_VAR_FILE = REPO_ROOT / "config/macros/_user_variables.cfg"
# Matches printer["gcode_macro _USER_VARIABLE"].name and the single-quote
# variant. `\s*` tolerates hand-formatted whitespace before `]` (legal
# Jinja). The optional quote class covers both idioms; the closing `]`
# anchors to the dict subscript so we don't false-match a literal mention
# of the macro name in a comment.
USER_VAR_REF_RE = re.compile(r"""_USER_VARIABLE['"]?\s*\]\.(\w+)""")

# Catches the bare-alias pattern (`{% set uv = printer["gcode_macro
# _USER_VARIABLE"] %}`) that would bypass USER_VAR_REF_RE — aliased reads
# (`uv.bedfans_slow`) are invisible to the simple regex above, which would
# let typos and orphans slip through both tripwires. The negative
# lookahead `(?!\s*\.)` allows the inline form
# `set SLOW = printer["gcode_macro _USER_VARIABLE"].bedfans_slow`
# (which IS visible to USER_VAR_REF_RE) but forbids the alias form.
USER_VAR_ALIAS_RE = re.compile(
    r"""set\s+\w+\s*=\s*printer\s*\[\s*['"]gcode_macro\s+_USER_VARIABLE['"]\s*\](?!\s*\.)"""
)


def _user_variable_definitions():
    """Return set of `variable_X` names defined in _user_variables.cfg."""
    if not USER_VAR_FILE.exists():
        return set()
    text = USER_VAR_FILE.read_text()
    return set(re.findall(r"^variable_(\w+):", text, re.MULTILINE))


def _user_variable_refs():
    """Return set of `variable_X` names referenced anywhere in our owned macros.

    Skips Klipper `#` config-style comments line-by-line so docstring
    examples in cfg files (e.g. "consumers read via _USER_VARIABLE.X")
    don't false-trigger the tripwire. Jinja-side references inside macro
    bodies still resolve normally — they live before any `#`.

    Raises FileNotFoundError on missing OWNED_MACRO_FILES entries — a
    silent skip on a renamed/moved file would let regressions through.
    """
    refs = set()
    # _user_variables.cfg is excluded so the file's own header comment
    # ("consumers read via _USER_VARIABLE.X") can't self-satisfy
    # test_user_variable_definitions_used.
    for cfg in OWNED_MACRO_FILES:
        path = Path(cfg)
        if not path.exists():
            raise FileNotFoundError(f"OWNED_MACRO_FILES references missing path: {cfg}")
        for raw in path.read_text().splitlines():
            non_comment = raw.split("#", 1)[0]
            for m in USER_VAR_REF_RE.finditer(non_comment):
                refs.add(m.group(1))
    return refs


def test_user_variable_refs_resolve():
    """Every _USER_VARIABLE.X reference resolves to a variable_X: definition."""
    defs = _user_variable_definitions()
    refs = _user_variable_refs()
    unresolved = refs - defs
    assert (
        not unresolved
    ), f"_USER_VARIABLE refs without matching variable_X: {sorted(unresolved)}"


def test_user_variable_definitions_used():
    """Every variable_X: definition is referenced somewhere (no orphans)."""
    defs = _user_variable_definitions()
    if not defs:
        return  # _user_variables.cfg doesn't exist yet — skip this PR-B-only test
    refs = _user_variable_refs()
    orphans = defs - refs
    assert not orphans, f"Orphan variable_X definitions: {sorted(orphans)}"


def test_no_user_variable_alias_pattern():
    """No macro aliases _USER_VARIABLE to a local var.

    The simple USER_VAR_REF_RE regex looks for `_USER_VARIABLE"].X` directly
    — it can't follow aliases like `{% set uv = printer["gcode_macro
    _USER_VARIABLE"] %}` then `uv.X`. Forbidding the alias keeps the regex
    sound. If you genuinely need shorter references, inline the lookup or
    extend USER_VAR_REF_RE to chase aliases (and update this test).
    """
    offenders = []
    for cfg in OWNED_MACRO_FILES + [str(USER_VAR_FILE)]:
        path = Path(cfg)
        if not path.exists():
            continue  # USER_VAR_FILE absent is the pre-PR-B state; OK.
        for lineno, raw in enumerate(path.read_text().splitlines(), 1):
            non_comment = raw.split("#", 1)[0]
            if USER_VAR_ALIAS_RE.search(non_comment):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {raw.strip()}"
                )
    assert not offenders, (
        "Aliasing _USER_VARIABLE bypasses Layer 5 ref tripwires:\n  "
        + "\n  ".join(offenders)
    )
