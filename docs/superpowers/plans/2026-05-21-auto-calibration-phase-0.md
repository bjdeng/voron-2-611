# Auto-Calibration Phase 0: Hardware + Capture Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the toolhead-mounted USB endoscope and a Python capture pipeline (`scripts/calibrate_endoscope/`) that returns clean, perspective-corrected, repeatable PNG images of a known-position artifact. **No scoring; no Klipper macros beyond a single test-capture entry point.** This phase de-risks the entire #32 project — if Phase 0 can't return reproducible images, no later phase can work.

**Architecture:** New Python package at `scripts/calibrate_endoscope/` with three pure-Python modules (`fiducial.py`, `v4l2_helpers.py`, `capture.py`) and a CLI. ChArUco-based perspective correction normalizes for mount drift and toolhead positioning variance. V4L2 controls (exposure / WB) locked before capture. Klipper integration is one new config file with one shell-command-backed macro for triggering captures. Hardware install (endoscope, 45° Stealthburner mount, USB pigtail to EBB, fiducial print) happens in parallel with code; only Task 9 requires the hardware to be live.

**Tech Stack:** Python 3.11 (Pi's `python3`), opencv-python ≥4.7 (modern aruco API), numpy, v4l2-ctl (subprocess). Klipper gcode_shell_command. Tests via pytest; OpenCV operations on synthetic fixtures (no live camera required in CI).

**Reference spec:** [`docs/superpowers/specs/2026-05-21-auto-calibration-endoscope-design.md`](../specs/2026-05-21-auto-calibration-endoscope-design.md) (Phase 0 row in §4 phase plan)

---

## File map

**Create:**
- `scripts/calibrate_endoscope/__init__.py` — empty package marker.
- `scripts/calibrate_endoscope/fiducial.py` — ChArUco board generation, detection, perspective-transform computation.
- `scripts/calibrate_endoscope/v4l2_helpers.py` — wraps `v4l2-ctl` (subprocess) for setting exposure/WB controls + querying available devices.
- `scripts/calibrate_endoscope/capture.py` — orchestrator: open device → set controls → discard warm-up frames → grab frame → detect fiducial → warp → save PNG.
- `scripts/calibrate_endoscope/cli.py` — argparse entrypoint. Two subcommands: `gen-fiducial` (outputs a PDF for Ben to print) and `capture` (single-frame capture; output path required).
- `scripts/calibrate_endoscope/generate_fiducial.py` — one-shot script that produces `scripts/calibrate_endoscope/fiducial.pdf` and `scripts/calibrate_endoscope/fiducial_canonical_corners.json`. Run once, output committed.
- `scripts/calibrate_endoscope/fiducial.pdf` — generated artifact, committed. Ben prints this 1:1.
- `scripts/calibrate_endoscope/fiducial_canonical_corners.json` — generated; ChArUco corner coordinates in mm used for the perspective transform target.
- `scripts/calibrate_endoscope/README.md` — installation + usage notes for the Pi (venv setup, udev rule, manual capture test).
- `scripts/install_endoscope_udev.sh` — installer script that writes `/etc/udev/rules.d/99-endoscope.rules` based on detected USB vendor/product IDs (run after the endoscope is plugged in).
- `config/calibrate_endoscope.cfg` — Klipper config: `[gcode_shell_command capture_endoscope_frame]` + `[gcode_macro CAPTURE_ENDOSCOPE_FRAME]` test macro.
- `tests/calibrate_endoscope/__init__.py` — empty package marker.
- `tests/calibrate_endoscope/test_fiducial.py` — unit tests on synthesized fiducial images.
- `tests/calibrate_endoscope/test_v4l2_helpers.py` — unit tests with mocked subprocess.
- `tests/calibrate_endoscope/test_capture.py` — orchestrator tests with mocked VideoCapture + fixture frames.
- `tests/calibrate_endoscope/conftest.py` — pytest fixtures (synthetic fiducial image generator).

**Modify:**
- `config/printer.cfg` — add `[include calibrate_endoscope.cfg]` (RESTART impact).
- `requirements.txt` — add `opencv-python>=4.7` and `numpy` (CI installs).
- `scripts/deploy_to_pi.sh` — add `scripts/calibrate_endoscope/.venv/` to rsync excludes (per-Pi venv, like chopper-resonance-tuner pattern).
- `tests/README.md` — document the new `tests/calibrate_endoscope/` directory and "no live camera in CI" stance under L4.
- `CLAUDE.md` — add brief entry under "Macro inventory" for `CAPTURE_ENDOSCOPE_FRAME`; note `calibrate_endoscope.cfg` exists; add Phase 0 deliverable to Recently-resolved when done.

**Not modified in Phase 0** (deferred to later phases):
- `config/macros/print_start.cfg` — no PRINT_START integration yet (Phase 4).
- Any Spoolman client code — Phase 4.
- Any scoring code — Phase 1/2/3.

---

## Prerequisites (Ben does, can happen in parallel with code Tasks 1-8)

These don't block the code work; only Task 9 (live verification) needs them done.

- [ ] **P1. Order endoscope.** Spec §15 recommends DEPSTECH B0749BQG1B (~$25) with the spec checklist in mind. Verify on receipt: 1080p capable, UVC, **3-8 cm focal range** (not 7-40 cm — that's the wrong DEPSTECH model), flexible cable. If wrong, return and try Swrisnt B01M12LQ99.
- [ ] **P2. Design + 3D print 45° Stealthburner mount.** Mount holds endoscope at 45° forward-down on Stealthburner's front face. Reference [undingen/PressureAdvanceCamera](https://github.com/undingen/PressureAdvanceCamera) mount as a starting point (it's for Ender 3 but the geometry transfers). Avoid blocking the nozzle's airflow or LEDs. Leave ~5mm clearance around lens.
- [ ] **P3. Crimp PH2.0 4-pin pigtail.** USB-A (from endoscope) → PH2.0 (EBB USB header). Wires: D+, D-, +5V, GND. Standard USB pinout.
- [ ] **P4. Install endoscope on toolhead.** Plug PH2.0 into one of EBB's 3 USB ports. Route cable in the existing toolhead cable chain.
- [ ] **P5. Print fiducial (after Task 2 lands `fiducial.pdf`).** Print `scripts/calibrate_endoscope/fiducial.pdf` on regular paper at 1:1 scale (verify dimensions with calipers — should be 100×100 mm overall). Adhere to the bed in a fixed corner (suggest front-left, well clear of the print area). Cover with clear tape or laminate to survive bed temperature cycles.
- [ ] **P6. Note USB vendor/product IDs.** Once endoscope is plugged in (`ssh pi@mainsailos.local lsusb`), record the vendor:product ID (e.g., `0c45:6362`). Needed for the udev rule in Task 7.

---

## Pre-flight

### Task 0: Create isolated worktree

- [ ] **Step 1: Create the worktree via `superpowers:using-git-worktrees`**

The skill creates a worktree under `.worktrees/<branch>/` and switches into it.

Branch name: `feat/auto-cal-phase-0-capture`

- [ ] **Step 2: Verify location**

```bash
pwd
git branch --show-current
```

Expected: cwd inside `.worktrees/feat-auto-cal-phase-0-capture/` (or equivalent), branch `feat/auto-cal-phase-0-capture`.

- [ ] **Step 3: Confirm test pyramid runs cleanly on `main` before any edits**

```bash
make test-py
```

Expected: all green. Establishes baseline.

---

## Implementation

### Task 1: Module skeleton + opencv dependency

**Files:**
- Create: `scripts/calibrate_endoscope/__init__.py`
- Create: `scripts/calibrate_endoscope/README.md`
- Create: `tests/calibrate_endoscope/__init__.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Create empty package markers**

```bash
mkdir -p scripts/calibrate_endoscope tests/calibrate_endoscope
touch scripts/calibrate_endoscope/__init__.py tests/calibrate_endoscope/__init__.py
```

- [ ] **Step 2: Create `scripts/calibrate_endoscope/README.md`**

```markdown
# Endoscope capture pipeline

Phase 0 deliverable for [#32](https://github.com/bjdeng/voron-2-611/issues/32) — see spec at
`docs/superpowers/specs/2026-05-21-auto-calibration-endoscope-design.md`.

## What this does

Returns clean, perspective-corrected PNG images of a known-position artifact
on the bed, using a USB endoscope mounted at 45° on the Stealthburner toolhead.
No scoring (that's Phases 1-3); just "give me a repeatable image."

## Pi-side install

```sh
# One-time venv setup (Pi)
cd ~/printer_data/scripts/calibrate_endoscope
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Install udev rule (after endoscope is plugged in)
sudo bash ~/printer_data/scripts/install_endoscope_udev.sh
```

## Manual capture test

```sh
~/printer_data/scripts/calibrate_endoscope/.venv/bin/python \
  -m calibrate_endoscope.cli capture --output /tmp/test.png
```

Or from Mainsail: `CAPTURE_ENDOSCOPE_FRAME OUTPUT=/tmp/test.png`.
```

- [ ] **Step 3: Add deps to `requirements.txt`**

Open `requirements.txt`. Add at the end:

```
# Endoscope capture pipeline (see scripts/calibrate_endoscope/)
opencv-python>=4.7
numpy
```

- [ ] **Step 4: Verify deps install locally**

```bash
make venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import cv2; print(cv2.__version__); import numpy; print(numpy.__version__)"
```

Expected: prints two version strings, ≥4.7.x for cv2.

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrate_endoscope/ tests/calibrate_endoscope/ requirements.txt
git commit -m "chore(calibrate-endoscope): module skeleton + opencv dep (#32 Phase 0)"
```

---

### Task 2: ChArUco fiducial generation

**Files:**
- Create: `scripts/calibrate_endoscope/fiducial.py`
- Create: `scripts/calibrate_endoscope/generate_fiducial.py`
- Create: `scripts/calibrate_endoscope/fiducial.pdf` (generated)
- Create: `scripts/calibrate_endoscope/fiducial_canonical_corners.json` (generated)
- Create: `tests/calibrate_endoscope/test_fiducial.py`
- Create: `tests/calibrate_endoscope/conftest.py`

ChArUco (chessboard + ArUco markers) gives sub-pixel corner accuracy — needed for the ±2 px session-to-session repeatability gate. Board parameters: 5×5 squares of 20 mm each = 100×100 mm total, with 15 mm ArUco markers inside the white squares. Uses `cv2.aruco.DICT_4X4_50`.

- [ ] **Step 1: Write the failing test — fiducial generator returns a board with known dimensions**

Create `tests/calibrate_endoscope/test_fiducial.py`:

```python
"""Tests for fiducial.py — ChArUco board generation, detection, perspective correction."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from calibrate_endoscope import fiducial


def test_create_board_returns_expected_dimensions():
    board = fiducial.create_board()
    # 5x5 squares, 20mm square size → 100mm × 100mm
    size = board.getChessboardSize()
    assert size == (5, 5)
    sq_len = board.getSquareLength()
    assert sq_len == pytest.approx(0.020)  # 20mm in meters
    mk_len = board.getMarkerLength()
    assert mk_len == pytest.approx(0.015)  # 15mm in meters


def test_canonical_corners_returns_25_points_in_mm():
    corners = fiducial.canonical_corners_mm()
    # 5x5 board has 4x4 = 16 inner chessboard corners
    assert corners.shape == (16, 2)
    # Bottom-left corner is at (20, 20) mm; top-right at (80, 80) mm
    assert corners[0].tolist() == pytest.approx([20.0, 20.0])
    assert corners[-1].tolist() == pytest.approx([80.0, 80.0])
```

Add `pytest.ini` or `pyproject.toml` config if not present — but check first; the repo may already configure pytest.

- [ ] **Step 2: Add pytest path config**

Check if `tests/conftest.py` or `pyproject.toml` already adds `scripts/` to `sys.path`. If not, create `tests/calibrate_endoscope/conftest.py`:

```python
"""Pytest config for calibrate_endoscope tests — adds scripts/ to path so imports resolve."""
import sys
from pathlib import Path

# Make `import calibrate_endoscope.foo` resolve from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_fiducial.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'calibrate_endoscope.fiducial'`.

- [ ] **Step 4: Implement minimal `fiducial.py`**

Create `scripts/calibrate_endoscope/fiducial.py`:

```python
"""ChArUco fiducial: board geometry, detection, perspective transform.

The fiducial is a 5x5 ChArUco board (DICT_4X4_50), 100mm x 100mm overall,
with 20mm chessboard squares and 15mm ArUco markers inside the white squares.
It's printed once and adhered to the bed in a fixed location; each capture
detects it and computes a perspective transform to a canonical top-down view.
"""
from __future__ import annotations

import cv2
import numpy as np

SQUARES_X = 5
SQUARES_Y = 5
SQUARE_LENGTH_M = 0.020  # 20mm
MARKER_LENGTH_M = 0.015  # 15mm
ARUCO_DICT = cv2.aruco.DICT_4X4_50


def create_board() -> cv2.aruco.CharucoBoard:
    """Return the canonical ChArUco board geometry."""
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    return cv2.aruco.CharucoBoard(
        (SQUARES_X, SQUARES_Y),
        SQUARE_LENGTH_M,
        MARKER_LENGTH_M,
        dictionary,
    )


def canonical_corners_mm() -> np.ndarray:
    """Return the (N, 2) array of inner ChArUco corners in canonical mm coordinates.

    A 5x5 board has 4x4 = 16 inner corners (chessboard corner detection
    only picks up the inner intersections, not the outer edge).
    """
    # Inner corners are at multiples of square_length (in mm), offset by one square
    sq_mm = SQUARE_LENGTH_M * 1000.0  # 20mm
    pts = []
    for j in range(1, SQUARES_Y):
        for i in range(1, SQUARES_X):
            pts.append([i * sq_mm, j * sq_mm])
    return np.array(pts, dtype=np.float64)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_fiducial.py -v`

Expected: 2 PASSED.

- [ ] **Step 6: Add fiducial render → PDF generator**

Append to `tests/calibrate_endoscope/test_fiducial.py`:

```python
def test_render_board_image_has_expected_pixel_size():
    img = fiducial.render_board_image(px_per_mm=10)
    # 100mm × 10 px/mm = 1000 × 1000
    assert img.shape == (1000, 1000)
    assert img.dtype == np.uint8
    # Image should be mostly black/white (binary chessboard); check pixel value spread
    assert img.min() == 0
    assert img.max() == 255
```

- [ ] **Step 7: Run new test, verify failure, then implement**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_fiducial.py -v`

Expected: 1 FAILED (`render_board_image` missing).

Append to `scripts/calibrate_endoscope/fiducial.py`:

```python
def render_board_image(px_per_mm: int = 10) -> np.ndarray:
    """Render the ChArUco board to a binary grayscale image.

    Default 10 px/mm → 1000x1000 px. Use a higher value for print-quality PDFs.
    """
    board = create_board()
    size_mm = SQUARES_X * SQUARE_LENGTH_M * 1000  # 100mm
    size_px = int(size_mm * px_per_mm)
    img = board.generateImage((size_px, size_px))
    return img
```

Run tests again — expect all 3 PASS.

- [ ] **Step 8: Add the generator script**

Create `scripts/calibrate_endoscope/generate_fiducial.py`:

```python
"""One-shot script to generate the printable fiducial PDF + canonical-corners JSON.

Run this once; commit the outputs. The PDF is what Ben prints (1:1 scale) and
adheres to the bed; the JSON encodes the corner positions used at runtime for
the perspective transform target.

Usage:
    python -m calibrate_endoscope.generate_fiducial
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from calibrate_endoscope import fiducial

OUTPUT_DIR = Path(__file__).resolve().parent
PDF_PATH = OUTPUT_DIR / "fiducial.pdf"
JSON_PATH = OUTPUT_DIR / "fiducial_canonical_corners.json"

# Print at 300 DPI → 11.81 px/mm. Use 12 for clean math.
PX_PER_MM_FOR_PRINT = 12


def main() -> None:
    # Render high-res image
    img = fiducial.render_board_image(px_per_mm=PX_PER_MM_FOR_PRINT)
    # Convert grayscale → BGR for PDF embedding
    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # Save as PNG first (cv2 can't write PDF directly)
    png_tmp = OUTPUT_DIR / "_fiducial_tmp.png"
    cv2.imwrite(str(png_tmp), img_bgr)

    # Use PIL to wrap PNG in a PDF page
    from PIL import Image
    Image.open(png_tmp).convert("RGB").save(PDF_PATH, "PDF", resolution=300.0)
    png_tmp.unlink()

    # Write canonical corners as JSON
    corners_mm = fiducial.canonical_corners_mm()
    JSON_PATH.write_text(json.dumps({
        "description": "Inner ChArUco corners in mm relative to fiducial bottom-left",
        "px_per_mm_at_print": PX_PER_MM_FOR_PRINT,
        "corners_mm": corners_mm.tolist(),
    }, indent=2))

    print(f"Wrote {PDF_PATH} and {JSON_PATH}")
    print(f"Print PDF at 1:1 (do NOT scale to fit). Verify with calipers: should be 100×100mm.")


if __name__ == "__main__":
    main()
```

Add `Pillow` to `requirements.txt` for PDF output:

```
Pillow
```

- [ ] **Step 9: Generate and commit the fiducial outputs**

```bash
.venv/bin/pip install Pillow
.venv/bin/python -m calibrate_endoscope.generate_fiducial
```

Verify: `ls scripts/calibrate_endoscope/fiducial.pdf scripts/calibrate_endoscope/fiducial_canonical_corners.json` — both exist.

- [ ] **Step 10: Commit**

```bash
git add scripts/calibrate_endoscope/fiducial.py scripts/calibrate_endoscope/generate_fiducial.py \
        scripts/calibrate_endoscope/fiducial.pdf scripts/calibrate_endoscope/fiducial_canonical_corners.json \
        tests/calibrate_endoscope/conftest.py tests/calibrate_endoscope/test_fiducial.py \
        requirements.txt
git commit -m "feat(calibrate-endoscope): ChArUco fiducial generation (#32 Phase 0)"
```

---

### Task 3: ChArUco detection + perspective transform

**Files:**
- Modify: `scripts/calibrate_endoscope/fiducial.py`
- Modify: `tests/calibrate_endoscope/test_fiducial.py`

Synthesize a test image of the fiducial that's been "viewed" through a known perspective transform; verify our detector finds the corners and our `compute_transform()` recovers the inverse warp such that applying it produces a top-down view with the corners back at canonical positions.

- [ ] **Step 1: Write the failing test — detect corners in a synthetic frame**

Append to `tests/calibrate_endoscope/test_fiducial.py`:

```python
def _synthesize_warped_fiducial(
    canonical_img: np.ndarray, warp_matrix: np.ndarray, output_size: tuple[int, int]
) -> np.ndarray:
    """Apply a known perspective warp to the canonical fiducial image."""
    return cv2.warpPerspective(canonical_img, warp_matrix, output_size)


def test_detect_corners_on_undistorted_fiducial():
    """Detection on the canonical (unwarped) board image should find all 16 inner corners."""
    img = fiducial.render_board_image(px_per_mm=10)
    detected = fiducial.detect_corners(img)
    assert detected is not None
    corners_px, ids = detected
    assert corners_px.shape == (16, 2)
    assert ids.shape == (16,)
    # IDs should be 0..15 in some order
    assert sorted(ids.tolist()) == list(range(16))


def test_compute_transform_recovers_known_warp():
    """Given a synthetic warped image, compute_transform should produce the inverse."""
    canonical = fiducial.render_board_image(px_per_mm=10)  # 1000x1000

    # Define a known perspective: tilt the right edge 30% closer (foreshortening)
    src = np.array([[0, 0], [1000, 0], [1000, 1000], [0, 1000]], dtype=np.float32)
    dst = np.array([[100, 50], [900, 200], [900, 800], [100, 950]], dtype=np.float32)
    warp = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(canonical, warp, (1000, 1000))

    # Detect corners in the warped image, compute transform back
    transform = fiducial.compute_transform(warped, output_size_px=1000, px_per_mm=10)
    assert transform is not None

    # Apply transform — result should look like the canonical board again
    recovered = cv2.warpPerspective(warped, transform, (1000, 1000))

    # Detect corners in recovered image; they should be ≈ at the canonical positions
    detected = fiducial.detect_corners(recovered)
    assert detected is not None
    corners_px, ids = detected
    canon_mm = fiducial.canonical_corners_mm()  # (16, 2) in mm
    canon_px = canon_mm * 10  # 10 px/mm

    # Match by ID
    for px, id_ in zip(corners_px, ids):
        expected = canon_px[id_]
        # Allow ±3 px tolerance for cumulative warp/anti-aliasing error
        np.testing.assert_allclose(px, expected, atol=3.0, err_msg=f"id={id_}")
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_fiducial.py -v`

Expected: 2 FAILED (`detect_corners` and `compute_transform` missing).

- [ ] **Step 3: Implement `detect_corners` and `compute_transform`**

Append to `scripts/calibrate_endoscope/fiducial.py`:

```python
def detect_corners(
    img: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Detect ChArUco inner corners in a frame.

    Returns (corners_px, ids) where:
      - corners_px is shape (N, 2) of detected corner pixel positions
      - ids is shape (N,) of corner IDs (0-indexed, matches canonical_corners_mm order)
    Returns None if detection fails (no fiducial visible, etc.).
    """
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    board = create_board()
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    detector_params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(dictionary, detector_params)
    marker_corners, marker_ids, _ = detector.detectMarkers(gray)
    if marker_ids is None or len(marker_ids) == 0:
        return None

    n_corners, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
        marker_corners, marker_ids, gray, board
    )
    if n_corners <= 0 or charuco_corners is None:
        return None

    corners_px = charuco_corners.reshape(-1, 2)
    ids = charuco_ids.flatten()
    return corners_px, ids


def compute_transform(
    img: np.ndarray, output_size_px: int, px_per_mm: float
) -> np.ndarray | None:
    """Compute a perspective transform from `img` to a canonical top-down view.

    output_size_px: output image will be this dimension in both axes.
    px_per_mm: scale factor (output pixels per millimeter in canonical space).

    Returns the 3x3 transform matrix, or None if the fiducial cannot be detected.
    """
    detected = detect_corners(img)
    if detected is None:
        return None
    corners_px, ids = detected
    if len(corners_px) < 4:
        return None  # need at least 4 points for a perspective transform

    canon_mm = canonical_corners_mm()  # all 16, in mm
    # Pick the corresponding canonical positions for the detected IDs
    src_pts = corners_px.astype(np.float32)
    dst_pts = (canon_mm[ids] * px_per_mm).astype(np.float32)

    # Use findHomography (RANSAC) — more robust than getPerspectiveTransform with N>4
    transform, _ = cv2.findHomography(src_pts, dst_pts, method=cv2.RANSAC)
    return transform
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_fiducial.py -v`

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrate_endoscope/fiducial.py tests/calibrate_endoscope/test_fiducial.py
git commit -m "feat(calibrate-endoscope): ChArUco detection + perspective transform (#32 Phase 0)"
```

---

### Task 4: V4L2 control helpers

**Files:**
- Create: `scripts/calibrate_endoscope/v4l2_helpers.py`
- Create: `tests/calibrate_endoscope/test_v4l2_helpers.py`

`v4l2-ctl` is a system binary on the Pi (`apt install v4l-utils`). We call it via subprocess to lock exposure + WB before capture. Tests mock subprocess; live behavior is verified in Task 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/calibrate_endoscope/test_v4l2_helpers.py`:

```python
"""Tests for v4l2_helpers.py — subprocess-mocked control setting."""
from unittest.mock import patch, MagicMock

import pytest

from calibrate_endoscope import v4l2_helpers


def test_lock_exposure_calls_v4l2ctl_with_manual_mode():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        v4l2_helpers.lock_exposure("/dev/video1", exposure_absolute=250)
    # First call sets exposure_auto=1 (manual mode); second sets the value
    calls = mock_run.call_args_list
    assert len(calls) >= 1
    cmd = calls[0].args[0]
    assert "v4l2-ctl" in cmd[0]
    assert "-d" in cmd
    assert "/dev/video1" in cmd
    # All control settings should appear in the command joined or split
    joined = " ".join(cmd)
    assert "exposure_auto=1" in joined or "auto_exposure=1" in joined
    assert "exposure_absolute=250" in joined or "exposure_time_absolute=250" in joined


def test_lock_white_balance_disables_auto_and_sets_temperature():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        v4l2_helpers.lock_white_balance("/dev/video1", temperature=4500)
    cmd = mock_run.call_args_list[0].args[0]
    joined = " ".join(cmd)
    assert "white_balance_temperature_auto=0" in joined or "white_balance_automatic=0" in joined
    assert "white_balance_temperature=4500" in joined or "white_balance_temperature_absolute=4500" in joined


def test_lock_exposure_raises_on_v4l2ctl_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="device not found")
        with pytest.raises(v4l2_helpers.V4L2ControlError, match="device not found"):
            v4l2_helpers.lock_exposure("/dev/video99", exposure_absolute=250)


def test_find_device_returns_first_matching_by_vendor_product():
    fake_output = (
        "Bus 001 Device 005: ID 0c45:6362 Microdia\n"
        "Bus 001 Device 002: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output)
        # Should find Microdia (the endoscope)
        present = v4l2_helpers.is_device_present("0c45:6362")
    assert present is True


def test_find_device_returns_false_if_not_present():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Bus 001 Device 002: ID 1d6b:0002\n")
        present = v4l2_helpers.is_device_present("0c45:6362")
    assert present is False
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_v4l2_helpers.py -v`

Expected: 5 FAILED (`v4l2_helpers` module missing).

- [ ] **Step 3: Implement `v4l2_helpers.py`**

Create `scripts/calibrate_endoscope/v4l2_helpers.py`:

```python
"""Subprocess wrappers around v4l2-ctl and lsusb for endoscope control.

We use system binaries rather than python-v4l2 bindings because:
  - v4l2-ctl handles control-name fallbacks (exposure_auto vs auto_exposure)
    gracefully via its own logic; we don't have to track kernel-version drift.
  - Subprocess calls are easy to mock in tests.
  - The control surface we need is tiny (set 3-4 controls per session).
"""
from __future__ import annotations

import subprocess


class V4L2ControlError(RuntimeError):
    """Raised when a v4l2-ctl invocation fails."""


def _run_v4l2_ctl(device: str, controls: dict[str, int]) -> None:
    """Set one or more controls. Tries each control name; ignores per-control failures.

    Some kernels expose `exposure_auto`; others `auto_exposure`. v4l2-ctl errors
    if the name is wrong, so we try each and accept partial success — at least
    one of the aliases should match the running kernel.
    """
    setlist = ",".join(f"{k}={v}" for k, v in controls.items())
    cmd = ["v4l2-ctl", "-d", device, f"--set-ctrl={setlist}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise V4L2ControlError(
            f"v4l2-ctl failed for {device}: {result.stderr.strip() or result.stdout.strip()}"
        )


def lock_exposure(device: str, exposure_absolute: int) -> None:
    """Switch the cam to manual exposure and set the absolute value.

    exposure_absolute is in cam-specific units (typically 0-10000).
    Determine the right value empirically per cam during Phase 0 setup.
    """
    # Try both control name conventions in one call — v4l2-ctl may accept
    # either; if a name is unknown the call fails entirely, so do them as
    # two separate calls and accept that one will fail.
    for ctrl_auto, ctrl_val in [
        ({"exposure_auto": 1}, {"exposure_absolute": exposure_absolute}),
        ({"auto_exposure": 1}, {"exposure_time_absolute": exposure_absolute}),
    ]:
        try:
            _run_v4l2_ctl(device, {**ctrl_auto, **ctrl_val})
            return
        except V4L2ControlError as exc:
            last_exc = exc
            continue
    raise last_exc


def lock_white_balance(device: str, temperature: int) -> None:
    """Switch the cam to manual white balance and set the temperature.

    temperature is in kelvin (typically 2800-6500).
    """
    for ctrl_auto, ctrl_val in [
        ({"white_balance_temperature_auto": 0}, {"white_balance_temperature": temperature}),
        ({"white_balance_automatic": 0}, {"white_balance_temperature_absolute": temperature}),
    ]:
        try:
            _run_v4l2_ctl(device, {**ctrl_auto, **ctrl_val})
            return
        except V4L2ControlError as exc:
            last_exc = exc
            continue
    raise last_exc


def is_device_present(vendor_product: str) -> bool:
    """Check if a USB device with the given vendor:product ID is plugged in.

    vendor_product is the 4-hex-digit colon-separated form, e.g. '0c45:6362'.
    Uses lsusb output.
    """
    result = subprocess.run(["lsusb"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return vendor_product.lower() in result.stdout.lower()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_v4l2_helpers.py -v`

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrate_endoscope/v4l2_helpers.py tests/calibrate_endoscope/test_v4l2_helpers.py
git commit -m "feat(calibrate-endoscope): v4l2-ctl + lsusb subprocess wrappers (#32 Phase 0)"
```

---

### Task 5: capture.py orchestrator

**Files:**
- Create: `scripts/calibrate_endoscope/capture.py`
- Create: `tests/calibrate_endoscope/test_capture.py`

Orchestrates the full capture pipeline: lock controls → open VideoCapture → discard warm-up frames → grab frame → detect fiducial → warp → save PNG. Returns an exit code (0 = success, 10 = device missing, 11 = fiducial missing, 12 = capture failure).

- [ ] **Step 1: Write the failing tests**

Create `tests/calibrate_endoscope/test_capture.py`:

```python
"""Tests for capture.py — orchestrator with mocked VideoCapture."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import cv2
import numpy as np
import pytest

from calibrate_endoscope import capture, fiducial


@pytest.fixture
def synthetic_fiducial_frame():
    """Return a frame that contains a slightly-warped fiducial — detectable."""
    canonical = fiducial.render_board_image(px_per_mm=10)
    # Embed in a larger 1920x1080 frame at known position, with slight warp
    frame = np.full((1080, 1920, 3), 64, dtype=np.uint8)  # dark grey background
    # Place the 1000x1000 canonical in the center
    cx, cy = 1920 // 2, 1080 // 2
    h, w = canonical.shape
    frame[cy - h // 2 : cy + h // 2, cx - w // 2 : cx + w // 2] = cv2.cvtColor(
        canonical, cv2.COLOR_GRAY2BGR
    )
    return frame


def test_capture_success(tmp_path, synthetic_fiducial_frame):
    """Happy path: device opens, frame contains fiducial, output PNG saved."""
    output = tmp_path / "out.png"

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, synthetic_fiducial_frame)
    mock_cap.set.return_value = True
    mock_cap.release.return_value = None

    with patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("calibrate_endoscope.v4l2_helpers.lock_exposure"), \
         patch("calibrate_endoscope.v4l2_helpers.lock_white_balance"):
        exit_code = capture.capture_frame(
            device="/dev/video1",
            output_path=output,
            exposure=250,
            wb_kelvin=4500,
            output_size_px=1000,
            px_per_mm=10,
        )
    assert exit_code == 0
    assert output.exists()
    # Loaded PNG should be the expected canonical size
    loaded = cv2.imread(str(output))
    assert loaded.shape == (1000, 1000, 3)


def test_capture_device_not_openable_returns_10(tmp_path):
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    with patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("calibrate_endoscope.v4l2_helpers.lock_exposure"), \
         patch("calibrate_endoscope.v4l2_helpers.lock_white_balance"):
        exit_code = capture.capture_frame(
            device="/dev/video99",
            output_path=tmp_path / "out.png",
        )
    assert exit_code == 10


def test_capture_no_fiducial_returns_11(tmp_path):
    """Frame is captured but doesn't contain a fiducial."""
    blank = np.full((1080, 1920, 3), 128, dtype=np.uint8)

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, blank)
    mock_cap.set.return_value = True

    with patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("calibrate_endoscope.v4l2_helpers.lock_exposure"), \
         patch("calibrate_endoscope.v4l2_helpers.lock_white_balance"):
        exit_code = capture.capture_frame(
            device="/dev/video1",
            output_path=tmp_path / "out.png",
        )
    assert exit_code == 11


def test_capture_frame_read_fails_returns_12(tmp_path):
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (False, None)
    mock_cap.set.return_value = True

    with patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("calibrate_endoscope.v4l2_helpers.lock_exposure"), \
         patch("calibrate_endoscope.v4l2_helpers.lock_white_balance"):
        exit_code = capture.capture_frame(
            device="/dev/video1",
            output_path=tmp_path / "out.png",
        )
    assert exit_code == 12
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_capture.py -v`

Expected: 4 FAILED (`capture` module missing).

- [ ] **Step 3: Implement `capture.py`**

Create `scripts/calibrate_endoscope/capture.py`:

```python
"""Endoscope capture orchestrator.

Sequence:
  1. Lock exposure + WB via v4l2-ctl (subprocess).
  2. Open /dev/videoN via cv2.VideoCapture(... CAP_V4L2).
  3. Set MJPG fourcc + 1920x1080 resolution.
  4. Discard N warm-up frames (cam stabilization after exposure change).
  5. Grab one frame.
  6. Detect ChArUco fiducial.
  7. Compute perspective transform → top-down canonical image.
  8. Save PNG.

Exit codes:
  0  success
  10 device not openable (cable, udev, EBB hub issue)
  11 fiducial not detected (lighting, occlusion, mount drift)
  12 frame read failed (device opened but returned no frame)
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from calibrate_endoscope import fiducial, v4l2_helpers

EXIT_OK = 0
EXIT_DEVICE_NOT_OPEN = 10
EXIT_NO_FIDUCIAL = 11
EXIT_FRAME_READ_FAILED = 12

WARMUP_FRAMES = 3
DEFAULT_OUTPUT_SIZE_PX = 1000
DEFAULT_PX_PER_MM = 10


def capture_frame(
    device: str,
    output_path: Path,
    exposure: int = 250,
    wb_kelvin: int = 4500,
    width: int = 1920,
    height: int = 1080,
    output_size_px: int = DEFAULT_OUTPUT_SIZE_PX,
    px_per_mm: float = DEFAULT_PX_PER_MM,
) -> int:
    """Capture a single perspective-corrected frame. Returns an exit code."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Lock controls (best-effort; if cam doesn't support, capture still works)
    try:
        v4l2_helpers.lock_exposure(device, exposure)
        v4l2_helpers.lock_white_balance(device, wb_kelvin)
    except v4l2_helpers.V4L2ControlError as exc:
        print(f"warning: v4l2-ctl failed (continuing with auto): {exc}")

    # 2. Open device
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return EXIT_DEVICE_NOT_OPEN

    try:
        # 3. Configure format
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # 4. Discard warm-up frames
        for _ in range(WARMUP_FRAMES):
            ok, _ = cap.read()
            if not ok:
                return EXIT_FRAME_READ_FAILED

        # 5. Grab target frame
        ok, frame = cap.read()
        if not ok or frame is None:
            return EXIT_FRAME_READ_FAILED
    finally:
        cap.release()

    # 6 + 7. Detect fiducial + compute transform
    transform = fiducial.compute_transform(frame, output_size_px, px_per_mm)
    if transform is None:
        return EXIT_NO_FIDUCIAL

    # 7. Apply warp
    warped = cv2.warpPerspective(frame, transform, (output_size_px, output_size_px))

    # 8. Save
    cv2.imwrite(str(output_path), warped)
    return EXIT_OK
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_capture.py -v`

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrate_endoscope/capture.py tests/calibrate_endoscope/test_capture.py
git commit -m "feat(calibrate-endoscope): capture orchestrator with exit codes (#32 Phase 0)"
```

---

### Task 6: CLI entrypoint

**Files:**
- Create: `scripts/calibrate_endoscope/cli.py`
- Modify: `tests/calibrate_endoscope/test_capture.py` (add CLI test)

Argparse wrapper so the Klipper shell_command can call `python -m calibrate_endoscope.cli capture --device /dev/videoN --output /tmp/out.png`.

- [ ] **Step 1: Write the failing test**

Append to `tests/calibrate_endoscope/test_capture.py`:

```python
def test_cli_capture_invokes_capture_frame(tmp_path, synthetic_fiducial_frame):
    """`cli.py capture --device X --output Y` calls capture_frame and exits 0."""
    output = tmp_path / "cli_out.png"

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, synthetic_fiducial_frame)
    mock_cap.set.return_value = True

    with patch("cv2.VideoCapture", return_value=mock_cap), \
         patch("calibrate_endoscope.v4l2_helpers.lock_exposure"), \
         patch("calibrate_endoscope.v4l2_helpers.lock_white_balance"):
        from calibrate_endoscope import cli
        exit_code = cli.main(["capture", "--device", "/dev/video1", "--output", str(output)])
    assert exit_code == 0
    assert output.exists()
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/calibrate_endoscope/test_capture.py::test_cli_capture_invokes_capture_frame -v`

Expected: FAIL (`cli` missing).

- [ ] **Step 3: Implement `cli.py`**

Create `scripts/calibrate_endoscope/cli.py`:

```python
"""CLI entrypoint for the endoscope capture pipeline.

Usage:
    python -m calibrate_endoscope.cli capture --device /dev/video1 --output /tmp/out.png
    python -m calibrate_endoscope.cli gen-fiducial   (regenerates the fiducial PDF)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from calibrate_endoscope import capture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibrate_endoscope")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cap_p = sub.add_parser("capture", help="Capture a single perspective-corrected frame.")
    cap_p.add_argument("--device", required=True, help="V4L2 device path (e.g. /dev/video1)")
    cap_p.add_argument("--output", required=True, type=Path, help="Output PNG path")
    cap_p.add_argument("--exposure", type=int, default=250)
    cap_p.add_argument("--wb-kelvin", type=int, default=4500)
    cap_p.add_argument("--output-size-px", type=int, default=capture.DEFAULT_OUTPUT_SIZE_PX)
    cap_p.add_argument("--px-per-mm", type=float, default=capture.DEFAULT_PX_PER_MM)

    sub.add_parser("gen-fiducial", help="Regenerate the printable fiducial PDF.")

    args = parser.parse_args(argv)

    if args.cmd == "capture":
        return capture.capture_frame(
            device=args.device,
            output_path=args.output,
            exposure=args.exposure,
            wb_kelvin=args.wb_kelvin,
            output_size_px=args.output_size_px,
            px_per_mm=args.px_per_mm,
        )
    if args.cmd == "gen-fiducial":
        from calibrate_endoscope import generate_fiducial
        generate_fiducial.main()
        return 0

    parser.error(f"unknown subcommand: {args.cmd}")  # raises


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/calibrate_endoscope/ -v`

Expected: all PASS (previous 11 + new 1 = 12).

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrate_endoscope/cli.py tests/calibrate_endoscope/test_capture.py
git commit -m "feat(calibrate-endoscope): argparse CLI entrypoint (#32 Phase 0)"
```

---

### Task 7: udev rule + udev installer

**Files:**
- Create: `scripts/install_endoscope_udev.sh`

A stable `/dev/endoscope` symlink is more reliable than `/dev/video1` (which changes if a USB device enumerates differently). The installer detects the endoscope's vendor:product ID from `lsusb` and writes the rule.

- [ ] **Step 1: Create the installer**

Create `scripts/install_endoscope_udev.sh`:

```bash
#!/usr/bin/env bash
# Install a udev rule that creates /dev/endoscope -> /dev/videoN for the
# endoscope plugged into the EBB hub. Detects the vendor:product ID from
# lsusb. Run AFTER the endoscope is plugged in.
#
# Usage:
#   sudo bash install_endoscope_udev.sh             # interactive: lists USB devices, prompts
#   sudo bash install_endoscope_udev.sh 0c45:6362   # non-interactive: pass vendor:product
set -euo pipefail

RULE_PATH=/etc/udev/rules.d/99-endoscope.rules

if [[ $EUID -ne 0 ]]; then
  echo "Must be run as root (use sudo)." >&2
  exit 1
fi

VENDOR_PRODUCT="${1:-}"

if [[ -z "$VENDOR_PRODUCT" ]]; then
  echo "USB devices currently plugged in:"
  lsusb
  echo
  read -rp "Enter the endoscope's vendor:product (e.g. 0c45:6362): " VENDOR_PRODUCT
fi

if [[ ! "$VENDOR_PRODUCT" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$ ]]; then
  echo "Invalid format. Expected XXXX:XXXX (4 hex digits each)." >&2
  exit 2
fi

VENDOR="${VENDOR_PRODUCT%:*}"
PRODUCT="${VENDOR_PRODUCT#*:}"

cat > "$RULE_PATH" <<EOF
# /dev/endoscope → first /dev/videoN device matching vendor:product
# Installed by scripts/install_endoscope_udev.sh; safe to delete + reinstall.
SUBSYSTEM=="video4linux", ATTRS{idVendor}=="$VENDOR", ATTRS{idProduct}=="$PRODUCT", ATTR{index}=="0", SYMLINK+="endoscope"
EOF

echo "Wrote $RULE_PATH:"
cat "$RULE_PATH"
echo
echo "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger
sleep 1
if [[ -e /dev/endoscope ]]; then
  echo "Success: /dev/endoscope -> $(readlink /dev/endoscope)"
else
  echo "Warning: /dev/endoscope not yet present. Unplug + replug the endoscope and check again." >&2
fi
```

- [ ] **Step 2: Make executable + verify shellcheck (if installed)**

```bash
chmod +x scripts/install_endoscope_udev.sh
# Optional: shellcheck if you have it
shellcheck scripts/install_endoscope_udev.sh 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add scripts/install_endoscope_udev.sh
git commit -m "feat(calibrate-endoscope): udev rule installer for /dev/endoscope (#32 Phase 0)"
```

---

### Task 8: Klipper config integration

**Files:**
- Create: `config/calibrate_endoscope.cfg`
- Modify: `config/printer.cfg`
- Modify: `scripts/deploy_to_pi.sh` (add venv exclude)
- Modify: `CLAUDE.md`
- Modify: `tests/README.md`

A single test macro `CAPTURE_ENDOSCOPE_FRAME OUTPUT=/tmp/test.png` for live verification, plus `gcode_shell_command` plumbing. RESTART impact (new section in printer.cfg's include graph).

- [ ] **Step 1: Verify `gcode_shell_command` is already available**

```bash
grep -r "gcode_shell_command" config/ 2>&1 | head -5
```

If empty: Ben's stack uses `gcode_shell_command` extension via Kiauh / chopper-resonance-tuner pattern. Check `~/printer_data/config/` on the Pi for an existing `gcode_shell_command.py` install. If not present, this task adds the install step (Ben runs the installer).

For this plan, assume it IS available (chopper-resonance-tuner already uses it per CLAUDE.md). If grep returns nothing in this repo, add a one-line note to README; don't block.

- [ ] **Step 2: Create `config/calibrate_endoscope.cfg`**

```ini
#####################################################################
#   Endoscope capture pipeline — Phase 0 (#32)
#
#   Spec: docs/superpowers/specs/2026-05-21-auto-calibration-endoscope-design.md
#
#   This file ONLY adds a manual test-capture macro. No PRINT_START
#   integration; no scoring; no Spoolman. Those land in later phases.
#####################################################################

[gcode_shell_command capture_endoscope_frame]
command: /home/pi/printer_data/scripts/calibrate_endoscope/.venv/bin/python
   -m calibrate_endoscope.cli capture
   --device /dev/endoscope
   --output /tmp/endoscope_capture.png
timeout: 30.0
verbose: True


[gcode_macro CAPTURE_ENDOSCOPE_FRAME]
description: Capture one perspective-corrected frame to /tmp/endoscope_capture.png. Test macro for Phase 0; not for PRINT_START use.
gcode:
  RUN_SHELL_COMMAND CMD=capture_endoscope_frame
  RESPOND TYPE=command MSG="Endoscope capture done; see /tmp/endoscope_capture.png"
```

- [ ] **Step 3: Add include to `config/printer.cfg`**

Find the `[include]` block area (likely near the top after `[mcu]`s and before macros). Add:

```
[include calibrate_endoscope.cfg]
```

Match the formatting of nearby includes (alphabetical or by-feature).

- [ ] **Step 4: Update `scripts/deploy_to_pi.sh` rsync excludes**

Find the rsync exclude section (existing `--exclude` flags). Add:

```
--exclude='scripts/calibrate_endoscope/.venv/'
--exclude='scripts/calibrate_endoscope/__pycache__/'
```

Same pattern as the chopper-resonance-tuner exclude (per CLAUDE.md "Known quirks").

- [ ] **Step 5: Update `CLAUDE.md`**

In the "Macro inventory" section, add under a new `### `config/calibrate_endoscope.cfg` — endoscope capture pipeline (Phase 0)` heading:

```markdown
### `config/calibrate_endoscope.cfg` — Endoscope capture (#32 Phase 0)
- `CAPTURE_ENDOSCOPE_FRAME` — captures one perspective-corrected frame from the toolhead endoscope to `/tmp/endoscope_capture.png`. Phase 0 deliverable; not for PRINT_START use yet. Backend is `scripts/calibrate_endoscope/` Python package (venv at `~/printer_data/scripts/calibrate_endoscope/.venv/`, excluded from rsync).
```

In the "Known quirks" section, add:

```markdown
- **Endoscope venv is Pi-only** at `~/printer_data/scripts/calibrate_endoscope/.venv/` (matches chopper-resonance-tuner pattern). Auto-excluded from rsync by `scripts/deploy_to_pi.sh`. After Klipper version bumps or fresh installs, run: `cd ~/printer_data/scripts/calibrate_endoscope && python3 -m venv .venv && .venv/bin/pip install -r ../../../requirements.txt`. The `/dev/endoscope` symlink requires `install_endoscope_udev.sh` to have been run.
```

- [ ] **Step 6: Update `tests/README.md`**

Under the "Layout" section, add a row to the tests table or directory listing for `tests/calibrate_endoscope/`. Brief: "Tests for the endoscope capture pipeline (#32 Phase 0). No live camera in CI; uses synthesized fiducial fixtures."

- [ ] **Step 7: Run full local test pyramid**

```bash
make test-py
```

Expected: all green, including new `tests/calibrate_endoscope/` tests.

- [ ] **Step 8: Run klippy parse smoke (L3 mirror)**

The CI's L3 layer loads `config/printer.cfg`. To pre-validate locally, run the test that does:

```bash
.venv/bin/pytest tests/test_config_structure.py -v 2>&1 | head -30
```

Verify nothing breaks from the new include.

- [ ] **Step 9: Commit**

```bash
git add config/calibrate_endoscope.cfg config/printer.cfg \
        scripts/deploy_to_pi.sh CLAUDE.md tests/README.md
git commit -m "feat(calibrate-endoscope): Klipper integration + deploy excludes + docs (#32 Phase 0)"
```

---

### Task 9: Live hardware verification (operator-driven)

**Files:** (none modified; observations recorded in `memory/`)

This task can't be TDD'd — it requires the physical hardware (prerequisites P1-P6). Run after the previous tasks land + the PR merges + `/deploy-to-pi` syncs to the printer.

- [ ] **Step 1: Pi venv setup (one-time)**

SSH to the Pi:

```bash
ssh pi@mainsailos.local
cd ~/printer_data/scripts/calibrate_endoscope
python3 -m venv .venv
.venv/bin/pip install -r ~/printer_data/requirements.txt  # or wherever it deploys
```

Verify: `.venv/bin/python -c "import cv2; print(cv2.__version__)"` prints ≥4.7.

- [ ] **Step 2: Install the udev rule**

```bash
lsusb | grep -i -E "microdia|depstech|camera|video|uvc"  # find the endoscope
# Once you have its vendor:product ID:
sudo bash ~/printer_data/scripts/install_endoscope_udev.sh 0c45:6362  # example
```

Verify: `ls -l /dev/endoscope` shows a symlink to a `/dev/videoN`.

- [ ] **Step 3: Manual capture test (no Klipper)**

Park the toolhead manually so the endoscope's view covers the fiducial (operator does this via Mainsail's controls; record the parking XYZ for future use). Then from the Pi:

```bash
~/printer_data/scripts/calibrate_endoscope/.venv/bin/python \
  -m calibrate_endoscope.cli capture \
  --device /dev/endoscope \
  --output /tmp/test1.png
```

Verify: exit code 0, `/tmp/test1.png` exists, opens cleanly in Mainsail's file browser. Image should be roughly 1000×1000 px and recognizably a top-down view of the fiducial area.

- [ ] **Step 4: Klipper-side test**

From Mainsail console:

```
CAPTURE_ENDOSCOPE_FRAME
```

Verify: `RESPOND` echoes the success message; `/tmp/endoscope_capture.png` is written.

- [ ] **Step 5: Repeatability test (the Phase 0 gate)**

Park toolhead at the same XYZ. Capture 5 times across at least 5 minutes (let the chamber + toolhead settle):

```bash
for i in 1 2 3 4 5; do
  .venv/bin/python -m calibrate_endoscope.cli capture \
    --device /dev/endoscope --output /tmp/repeat_$i.png
  sleep 60
done
```

Optional analysis (manual): visually overlay any two of the captures; the fiducial should match to within ±2 px. If you have a quick way to diff (e.g., `compare /tmp/repeat_1.png /tmp/repeat_5.png /tmp/diff.png` from ImageMagick), use it.

- [ ] **Step 6: Record results in `memory/`**

Append to `memory/tuning-log.md` (or create `memory/endoscope-phase-0-log.md` if cleaner):

```markdown
## 2026-MM-DD — Endoscope Phase 0 verification (#32)
- Endoscope model: <actual model purchased>
- USB vendor:product: <e.g. 0c45:6362>
- /dev/endoscope symlink working: yes/no
- Optimal toolhead parking for fiducial view: X=___ Y=___ Z=___
- Optimal exposure value: ___
- Optimal WB kelvin: ___
- Session-to-session repeatability (±px): ___ over 5 captures spanning N minutes
- DOF observation: ___ (in-focus across whole artifact? edge softness?)
- Phase 0 gate met: yes/no
```

- [ ] **Step 7: If repeatability >2 px**: investigate root cause before declaring Phase 0 done.
  - Toolhead mount flex → reinforce
  - Cam exposure drift → tighten lock or shorten warm-up
  - Fiducial print stretched/skewed → reprint at 1:1
  - Lighting variation → fix caselight brightness

Re-run Step 5 until gate is met.

- [ ] **Step 8: Final commit (memory log)**

```bash
git add memory/tuning-log.md   # or memory/endoscope-phase-0-log.md
git commit -m "docs(memory): record endoscope Phase 0 verification (#32)"
```

---

## Wrap-up

### Task 10: Open PR + update issue

- [ ] **Step 1: Push branch + open PR**

```bash
git push -u origin feat/auto-cal-phase-0-capture
gh pr create --title "feat(calibrate-endoscope): Phase 0 — capture pipeline (#32)" --body "$(cat <<'EOF'
## Summary
- Phase 0 deliverable for [#32](https://github.com/bjdeng/voron-2-611/issues/32): toolhead-mounted USB endoscope + Python capture pipeline returning perspective-corrected images of a known-position artifact.
- New `scripts/calibrate_endoscope/` Python package with full unit-test coverage on synthesized fiducial fixtures.
- One Klipper test macro `CAPTURE_ENDOSCOPE_FRAME` for live verification; no PRINT_START integration yet.

## Spec
- `docs/superpowers/specs/2026-05-21-auto-calibration-endoscope-design.md` (Phase 0 row in §4 phase plan)

## Test plan
- [x] L1-L4 CI passes (unit tests, ruff, macro_refcheck, klippy parse)
- [ ] Hardware install: endoscope, mount, USB pigtail, fiducial printed + adhered
- [ ] Pi-side venv install + udev rule
- [ ] Manual `cli.py capture` returns exit 0 with valid PNG
- [ ] `CAPTURE_ENDOSCOPE_FRAME` from Mainsail console succeeds
- [ ] Session-to-session repeatability ≤ ±2 px over 5 captures spanning ≥5 min
- [ ] Results logged in `memory/`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Comment on #32 with phase progress**

```bash
gh issue comment 32 --body "Phase 0 in flight: see PR. Phases 1-4 each get their own writing-plans pass after Phase 0 lands + live verification gate is met."
```

---

## Self-review checklist

- [x] Spec coverage: every Phase 0 requirement from §4 phase plan (endoscope, 45° mount, USB to EBB, udev rule, ChArUco perspective correction, exposure/WB lock, focal-range verification) has a task above.
- [x] Capture pipeline modules match §6 of spec: `capture.py` orchestrates, `fiducial.py` does ChArUco, `v4l2_helpers.py` does control locking.
- [x] Exit codes match spec §6: 10 = device, 11 = fiducial, 12 = frame.
- [x] No placeholders, no "implement appropriate error handling"-style hand-waves.
- [x] Each task ends with a commit.
- [x] Test fixtures synthesize from canonical fiducial — no live camera needed in CI.
- [x] Hardware prerequisites listed up front, marked as parallel work; only Task 9 blocks on them.
- [x] Files/method names consistent throughout (`fiducial.create_board`, `capture.capture_frame`, `v4l2_helpers.lock_exposure`, CLI `capture` subcommand).
