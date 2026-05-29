# calibrate-filament skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive `calibrate-filament` Claude Code skill that walks Ben through temp(verify) → flow → Adaptive PA for one filament (brand+material), writes scalar results into the OrcaSlicer profile JSON, and logs them to the repo.

**Architecture:** Approach B — a SKILL.md playbook (Claude-driven, human-in-the-loop) plus one tested helper script (`scripts/orca_profile_edit.py`) that owns the only dangerous operation: editing Ben's live OrcaSlicer filament-profile JSONs. Flow runs via the existing Klipper `FLOW_MULTIPLIER_CALIBRATION` macro over SSH/Moonraker. Per-filament history lives in `memory/filaments/<brand>-<material>.md`.

**Tech Stack:** Python 3 stdlib (argparse/json/pathlib/subprocess), pytest (L4), Klipper/Moonraker, OrcaSlicer filament JSON profiles.

**Spec:** `docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md`

---

## File structure

| Path | Responsibility |
|---|---|
| `scripts/orca_profile_edit.py` | CLI: `--find` a profile JSON, `--get`/`--set` a scalar field. Atomic write, `.bak`, re-parse guard, refuse-if-OrcaSlicer-running, preserve OrcaSlicer's list-of-string container type. |
| `tests/test_orca_profile_edit.py` | L4 subprocess tests against a fixture profile. |
| `tests/fixtures/orca/user/000/filament/Inland PLA.json` | Fixture OrcaSlicer filament profile (array-valued fields). |
| `.claude/skills/calibrate-filament/SKILL.md` | Interactive cascade playbook. Authored via `superpowers:writing-skills`. |
| `memory/filaments/TEMPLATE.md` | Per-filament log record template (RFID-aware frontmatter). |
| `memory/filaments/.gitkeep` | Ensure the dir exists in git. |
| `docs/slicer-templates/orcaslicer.md` | Cross-reference: point the per-spool workflow at the new skill. |
| `CLAUDE.md` | Cross-reference: list the new skill alongside deploy-to-pi/sync-from-pi. |

---

## Task 1: `orca_profile_edit.py --find`

**Files:**
- Create: `scripts/orca_profile_edit.py`
- Create: `tests/fixtures/orca/user/000/filament/Inland PLA.json`
- Create: `tests/test_orca_profile_edit.py`

- [ ] **Step 1: Create the fixture profile**

Create `tests/fixtures/orca/user/000/filament/Inland PLA.json` (OrcaSlicer stores scalars as single-element string arrays):

```json
{
    "type": "filament",
    "name": "Inland PLA",
    "from": "User",
    "filament_id": "GFL99",
    "nozzle_temperature": ["210"],
    "nozzle_temperature_initial_layer": ["215"],
    "filament_flow_ratio": ["0.95"]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_orca_profile_edit.py`:

```python
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
        cwd=REPO, capture_output=True, text=True, env=full,
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -v`
Expected: FAIL (script does not exist / no such file).

- [ ] **Step 4: Implement `--find`**

Create `scripts/orca_profile_edit.py`:

```python
#!/usr/bin/env python3
"""Read and safely edit scalar fields in OrcaSlicer filament-profile JSONs.

Used by the calibrate-filament skill to write calibrated values
(nozzle_temperature, filament_flow_ratio, ...) into OrcaSlicer filament
profiles. Never touches the Adaptive PA model field — that stays a guided
manual paste.

OrcaSlicer stores most filament settings as single-element arrays of
strings (e.g. "nozzle_temperature": ["210"]). --set preserves the
existing container type: list -> single-element list of the string value;
scalar -> scalar string.

Profile resolution: --file points at a JSON directly; --profile NAME
searches the OrcaSlicer user dir (ORCA_USER_DIR env, else the default
macOS path) for <NAME>.json under a filament/ subdir.

Exit codes:
  0 — success
  1 — bad usage (missing/conflicting args)
  2 — profile not found / ambiguous / key missing
  3 — refused: OrcaSlicer is running (would overwrite the edit on exit)
  4 — write failed (result did not re-parse; .bak restored)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_ORCA_DIR = (
    Path.home() / "Library" / "Application Support" / "OrcaSlicer" / "user"
)


def orca_user_dir() -> Path:
    return Path(os.environ.get("ORCA_USER_DIR", str(DEFAULT_ORCA_DIR)))


def find_profile(name: str) -> Path:
    base = orca_user_dir()
    matches = sorted(base.glob(f"**/filament/{name}.json"))
    if not matches:
        matches = sorted(base.glob(f"**/{name}.json"))
    if not matches:
        sys.stderr.write(f"profile not found: {name!r} under {base}\n")
        sys.exit(2)
    if len(matches) > 1:
        listing = "\n".join(f"  {m}" for m in matches)
        sys.stderr.write(f"ambiguous profile {name!r}: {len(matches)} matches:\n{listing}\n")
        sys.exit(2)
    return matches[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Read/edit OrcaSlicer filament profile scalars")
    ap.add_argument("--find", metavar="NAME")
    ap.add_argument("--profile", metavar="NAME")
    ap.add_argument("--file", metavar="PATH")
    ap.add_argument("--get", metavar="KEY")
    ap.add_argument("--set", metavar="KEY=VALUE")
    args = ap.parse_args()

    if args.find:
        print(find_profile(args.find))
        return

    sys.stderr.write("nothing to do: pass --find, --get, or --set\n")
    sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add scripts/orca_profile_edit.py tests/test_orca_profile_edit.py "tests/fixtures/orca/user/000/filament/Inland PLA.json"
git commit -m "feat(calibrate): orca_profile_edit.py --find"
```

---

## Task 2: `--get`

**Files:**
- Modify: `scripts/orca_profile_edit.py`
- Test: `tests/test_orca_profile_edit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_profile_edit.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -k get -v`
Expected: FAIL (exit 1 "nothing to do" — `--get` not handled).

- [ ] **Step 3: Implement `--get` + target resolution**

In `scripts/orca_profile_edit.py`, add these helpers above `main()`:

```python
def resolve_target(args) -> Path:
    if args.file:
        p = Path(args.file)
        if not p.is_file():
            sys.stderr.write(f"file not found: {p}\n")
            sys.exit(2)
        return p
    return find_profile(args.profile)


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def scalar(val):
    return (val[0] if val else "") if isinstance(val, list) else val


def do_get(p: Path, key: str) -> None:
    data = load(p)
    if key not in data:
        sys.stderr.write(f"key not found: {key}\n")
        sys.exit(2)
    print(scalar(data[key]))
```

Then replace the `main()` body after the `--find` block with:

```python
    if not (args.get or args.set):
        sys.stderr.write("nothing to do: pass --find, --get, or --set\n")
        sys.exit(1)
    if args.file and args.profile:
        sys.stderr.write("use only one of --file / --profile\n")
        sys.exit(1)
    if not (args.file or args.profile):
        sys.stderr.write("--get/--set require --file or --profile\n")
        sys.exit(1)

    target = resolve_target(args)

    if args.get:
        do_get(target, args.get)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -v`
Expected: PASS (all get + find tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/orca_profile_edit.py tests/test_orca_profile_edit.py
git commit -m "feat(calibrate): orca_profile_edit.py --get"
```

---

## Task 3: `--set` (type-preserving, atomic, .bak, re-parse guard)

**Files:**
- Modify: `scripts/orca_profile_edit.py`
- Test: `tests/test_orca_profile_edit.py`

The `--set` tests must be deterministic regardless of whether real OrcaSlicer is running on the dev machine, so they shim `pgrep` via PATH to report "not running". They also copy the fixture into `tmp_path` so the real fixture is never mutated.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_profile_edit.py`:

```python
import shutil


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
    assert _j.loads(bak.read_text())["filament_flow_ratio"] == ["0.95"], "bak holds old value"


def test_set_bad_format_errors(tmp_path):
    path = _copy_fixture(tmp_path)
    env = _fake_pgrep(tmp_path, found=False)
    r = run("--set", "nozzle_temperature", "--file", str(path), env=env)
    assert r.returncode == 1, _diag(r)
    assert "KEY=VALUE" in r.stderr, _diag(r)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -k set -v`
Expected: FAIL (`--set` not handled).

- [ ] **Step 3: Implement `--set`**

Add to `scripts/orca_profile_edit.py` above `main()`:

```python
def is_orca_running() -> bool:
    try:
        r = subprocess.run(
            ["pgrep", "-i", "orcaslicer"], capture_output=True, text=True
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def do_set(p: Path, key: str, value: str) -> None:
    if is_orca_running():
        sys.stderr.write("refused: OrcaSlicer is running; quit it first\n")
        sys.exit(3)
    data = load(p)
    old = data.get(key)
    data[key] = [value] if isinstance(old, list) else value
    backup = p.with_suffix(p.suffix + ".bak")
    shutil.copy2(p, backup)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    try:
        json.loads(p.read_text())
    except json.JSONDecodeError:
        shutil.copy2(backup, p)
        sys.stderr.write("write failed: result did not re-parse; restored from .bak\n")
        sys.exit(4)
    print(f"{key}: {scalar(old)!r} -> {value!r}  ({p})")
```

Then in `main()`, after the `do_get` block, add:

```python
    if args.set:
        if "=" not in args.set:
            sys.stderr.write("--set must be KEY=VALUE\n")
            sys.exit(1)
        key, _, value = args.set.partition("=")
        do_set(target, key, value)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/orca_profile_edit.py tests/test_orca_profile_edit.py
git commit -m "feat(calibrate): orca_profile_edit.py --set (atomic, type-preserving)"
```

---

## Task 4: `--set` refuses while OrcaSlicer is running

**Files:**
- Test: `tests/test_orca_profile_edit.py` (guard already implemented in Task 3; this task proves it)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orca_profile_edit.py`:

```python
def test_set_refused_when_orca_running(tmp_path):
    path = _copy_fixture(tmp_path)
    env = _fake_pgrep(tmp_path, found=True)  # simulate OrcaSlicer running
    r = run("--set", "nozzle_temperature=205", "--file", str(path), env=env)
    assert r.returncode == 3, _diag(r)
    assert "OrcaSlicer is running" in r.stderr, _diag(r)
    # file unchanged
    import json as _j
    assert _j.loads(path.read_text())["nozzle_temperature"] == ["210"], "must not edit"
```

- [ ] **Step 2: Run to verify it passes**

The guard exists from Task 3, so this test should pass immediately — it locks the behavior in.
Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py::test_set_refused_when_orca_running -v`
Expected: PASS.

- [ ] **Step 3: Run the full file + refcheck-adjacent checks**

Run: `.venv/bin/python -m pytest tests/test_orca_profile_edit.py -v`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add tests/test_orca_profile_edit.py
git commit -m "test(calibrate): lock OrcaSlicer-running refusal guard"
```

---

## Task 5: `memory/filaments/` scaffold + log template

**Files:**
- Create: `memory/filaments/.gitkeep`
- Create: `memory/filaments/TEMPLATE.md`

- [ ] **Step 1: Create the directory keeper**

Create `memory/filaments/.gitkeep` (empty file).

- [ ] **Step 2: Create the template**

Create `memory/filaments/TEMPLATE.md`:

```markdown
---
brand: <Brand>
material: <PLA|PETG|ABS|ASA|PLA Silk>
orca_profile: "<exact OrcaSlicer profile name>"
last_calibrated: YYYY-MM-DD
nozzle_temp: <int>
nozzle_temp_initial_layer: <int>
flow_ratio: <float>
pa_mode: <adaptive|static>
pa_fallback: <float>
rotation_distance_verified: galileo-bring-up
---

# <Brand> <Material>

Per-filament calibration log. Frontmatter is the current state; the body
is dated history (newest first). Field names mirror future Spoolman/RFID
extra-fields (see #72) so this record can seed them later.

## History

### YYYY-MM-DD
- Temp: <result + note, e.g. "verified 210 still clean">
- Flow: <old → new ratio, e.g. "0.95 → 0.98 (shell measured 0.41/0.40)">
- Adaptive PA: <model summary / fallback value>
- Notes: <observations>
```

- [ ] **Step 3: Verify nothing breaks**

Run: `make test-py`
Expected: PASS (no test references these files; this confirms the new files don't trip pre-commit/structure checks).

- [ ] **Step 4: Commit**

```bash
git add memory/filaments/.gitkeep memory/filaments/TEMPLATE.md
git commit -m "feat(calibrate): memory/filaments log scaffold + template"
```

---

## Task 6: Author `SKILL.md` via writing-skills

**Files:**
- Create: `.claude/skills/calibrate-filament/SKILL.md`

This task is prose, not TDD. Use the `superpowers:writing-skills` skill to author it.

- [ ] **Step 1: Invoke the skill-authoring skill**

Invoke `superpowers:writing-skills` with this brief: author `.claude/skills/calibrate-filament/SKILL.md` for the voron-2-611 repo, modeled structurally on `.claude/skills/sync-from-pi/SKILL.md` and `.claude/skills/deploy-to-pi/SKILL.md`. It must implement the cascade in `docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md` §5.

- [ ] **Step 2: Verify the SKILL.md meets acceptance criteria**

The file must contain:

- **Frontmatter** `name: calibrate-filament` and a `description` that triggers on phrases like "calibrate Inland PLA", "recalibrate this filament", "/calibrate-filament", and "dial in a new spool". Keep it specific (what + when to use), per writing-skills guidance.
- **When to use** — new spool/brand; after the Galileo swap; when print quality suggests flow/PA drift.
- **The cascade** (§5), each step labeled and resume-aware:
  - Step 0 rotation_distance — note it's verified at Galileo bring-up ([[galileo-rotation-distance-calibrated]]); **skip by default**, offer optional manual re-check; if ever off, propose the `config/` edit for the normal PR → `/deploy-to-pi` flow (FIRMWARE_RESTART), never auto-apply.
  - Step 1 temp — verify-first; full OrcaSlicer tower on request; write `nozzle_temperature` + `nozzle_temperature_initial_layer` via `scripts/orca_profile_edit.py --set ... --profile "<name>"`.
  - Step 2 flow — check `print_stats.state == standby` first; run `FLOW_MULTIPLIER_CALIBRATION` on the Pi over SSH/Moonraker (reuse deploy-to-pi connection patterns), seed with current flow; Ben calipers; `COMPUTE_FLOW_MULTIPLIER MEASURED_THICKNESS=…`; read new ratio from the Moonraker gcode response; write `filament_flow_ratio` via the helper.
  - Step 3 Adaptive PA — guide OrcaSlicer's flow×accel calibration; capture the measurements block into the log; **guided paste** of the model + `enable_pressure_advance` + fallback PA into the profile (NOT auto-edited).
  - Close-out — update `memory/filaments/<brand>-<material>.md` from `memory/filaments/TEMPLATE.md`; remind Ben to commit.
- **How to run** — `/calibrate-filament` or "calibrate <brand> <material>"; uses `scripts/orca_profile_edit.py`.
- **What it does NOT do** — never auto-commits; never deploys; never edits the Adaptive PA model field directly; doesn't touch Klipper config except proposing a rotation_distance change for the normal flow; one filament at a time.
- **Related** — the spec, #79, #72, orcaslicer.md, the two sibling skills.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/calibrate-filament/SKILL.md
git commit -m "feat(calibrate): calibrate-filament SKILL.md playbook"
```

---

## Task 7: Cross-reference the skill from docs

**Files:**
- Modify: `docs/slicer-templates/orcaslicer.md:251-253`
- Modify: `CLAUDE.md` (Workflow & CI/CD section)

- [ ] **Step 1: Update the orcaslicer.md workflow intro**

In `docs/slicer-templates/orcaslicer.md`, replace:

```markdown
Tracked in [#79](https://github.com/bjdeng/voron-2-611/issues/79) — a planned skill that walks through temp → flow → PA per spool with logging. Until that ships, manual workflow:
```

with:

```markdown
Use the **`/calibrate-filament`** skill (`.claude/skills/calibrate-filament/`) — it walks this cascade interactively and logs results to `memory/filaments/`. The manual steps below are what it automates / the fallback if you run it by hand:
```

- [ ] **Step 2: Add the skill to CLAUDE.md**

In `CLAUDE.md`, in the "## Workflow & CI/CD" section, after the `/deploy-to-pi` description paragraph, add:

```markdown
**Filament calibration:** `/calibrate-filament` walks temp → flow → Adaptive PA for one filament (brand+material), writes scalars into the OrcaSlicer profile via `scripts/orca_profile_edit.py`, and logs to `memory/filaments/`. Spec: [`docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md`](docs/superpowers/specs/2026-05-28-calibrate-filament-skill-design.md). Never auto-commits or deploys.
```

- [ ] **Step 3: Verify docs build clean**

Run: `.venv/bin/pre-commit run --files docs/slicer-templates/orcaslicer.md CLAUDE.md`
Expected: PASS (trailing-whitespace / EOF hooks).

- [ ] **Step 4: Commit**

```bash
git add docs/slicer-templates/orcaslicer.md CLAUDE.md
git commit -m "docs(calibrate): cross-reference calibrate-filament skill"
```

---

## Task 8: Full verification + PR

**Files:** none (verification + integration)

- [ ] **Step 1: Run the full macOS test subset**

Run: `make test-py`
Expected: PASS (refcheck + pytest incl. `test_orca_profile_edit.py` + pre-commit). Note the new test count is higher than baseline 106.

- [ ] **Step 2: Smoke the helper end-to-end against the fixture**

```bash
ORCA_USER_DIR=tests/fixtures/orca/user .venv/bin/python scripts/orca_profile_edit.py --find "Inland PLA"
ORCA_USER_DIR=tests/fixtures/orca/user .venv/bin/python scripts/orca_profile_edit.py --get nozzle_temperature --profile "Inland PLA"
```
Expected: prints the fixture path, then `210`.

- [ ] **Step 3: PR review toolkit (pre-push, no trivial exemption)**

Invoke `pr-review-toolkit:review-pr` on the branch (include the klipper-cfg-reviewer is NOT needed — no `.cfg` changes; use code-reviewer + the comment/test analyzers). Address findings.

- [ ] **Step 4: Push + open PR**

```bash
git push -u origin HEAD:feat/calibrate-filament-skill
gh pr create --base main --title "feat: calibrate-filament skill (#79 v1)" --body "<summary + test plan; closes the v1 core of #79>"
```

---

## Self-review

- **Spec coverage:** §4.1 SKILL.md → Task 6; §4.2 helper (find/get/set, atomic, .bak, re-parse, running-guard, type-preserve) → Tasks 1-4; §4.3 + §6 log → Task 5; §8 testing → Tasks 1-4; §10 cross-refs → Task 7; writing-skills authoring → Task 6. Covered.
- **Out-of-scope respected:** no Spoolman/RFID write-back, no community data, no webcam — none appear as tasks.
- **Type consistency:** `find_profile`, `resolve_target`, `load`, `scalar`, `is_orca_running`, `do_get`, `do_set` are defined once and reused; CLI flags `--find/--profile/--file/--get/--set` consistent across tasks; exit codes (0/1/2/3/4) consistent with the script docstring.
- **Determinism:** `--set` tests shim `pgrep` via PATH and operate on a `tmp_path` copy, so they pass whether or not real OrcaSlicer is running and never mutate the committed fixture.
