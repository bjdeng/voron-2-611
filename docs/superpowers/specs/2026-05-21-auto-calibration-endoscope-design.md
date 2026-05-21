# Automated per-spool temp/flow/PA calibration via toolhead endoscope — spec

**Owner:** Ben (printer-side macros + Python helper script + Moonraker write-back; operator-facing macros only after Phase 0).

**Restart impact:** Phase 0 = FIRMWARE_RESTART (new `/dev/videoN` over the EBB hub may need a `udev` rule; toolhead mount mechanical). Phases 1-4 = RESTART (gcode_macros + delayed_gcode + Python install). No MCU pin or kinematics changes.

**Closes:** [#32](https://github.com/bjdeng/voron-2-611/issues/32) (webcam-feedback-driven auto-calibration). Original issue scoped this as "chamber-cam-driven, opencv-based, end-to-end auto"; research showed the chamber-cam path is dead-end for fine extrusion features and that a toolhead-mounted endoscope is the only hobbyist-grade path with shipped prior art.

**Depends on:** [#72](https://github.com/bjdeng/voron-2-611/issues/72) — MMU spool tracking + per-spool runtime tuning (Spoolman extra-fields write-back). This spec ASSUMES that work is complete and Spoolman is queryable per spool_id via Moonraker.

**Files separate future issues for:** first-layer squish CV (same hardware), nozzle-view die-swell flow pre-screen (same hardware, Phase 5+ stretch), DIY laser-triangulation lidar upgrade (different hardware, indefinite future).

---

## 1. Problem

Calibrating a new spool today is manual and tedious:

- **Temp:** print a temp tower from the slicer, eyeball it, pick a band, edit the slicer filament profile. ~30 min.
- **Flow:** run `FLOW_MULTIPLIER_CALIBRATION` (Frix_x macro at `config/macros/calibrate_flow.cfg`), measure shell thickness with calipers, call `COMPUTE_FLOW_MULTIPLIER MEASURED_THICKNESS=…`, write the result into the slicer. ~15 min.
- **PA:** run `PRESSURE_ADVANCE_CALIBRATION` (Frix_x macro at `config/macros/calibrate_pa.cfg`), eyeball bands, pick winner, run `SET_PRESSURE_ADVANCE` for that print, edit slicer profile. ~15 min.
- **All three:** ~1 hour of attention per new spool, no historical record per spool, results scattered across slicer profiles and Klipper state.

With INDX retrofit on the horizon ([memory/indx-retrofit-intent.md](../../../memory/indx-retrofit-intent.md)) the calibration tax scales linearly with spool count. The MMU + RFID stack ([#72](https://github.com/bjdeng/voron-2-611/issues/72)) wants per-spool calibration data; today there's no clean way to capture it.

The chamber cam at 3 px/mm bed-wide cannot resolve the features needed for these measurements (a 0.4 mm bead is ~1.2 px). Prior art (undingen/PressureAdvanceCamera, furrysalamander/rubedo) moved the camera to the toolhead specifically to escape this limit.

## 2. Goal

A single macro — `DIAL_IN_FILAMENT SPOOL_ID=<id>` — that runs a temp → flow → PA cascade end-to-end with no operator interaction beyond starting the print and (for temp) clicking a winner in a Mainsail photo montage. Converged values write back to Spoolman extra fields per spool, then automatically apply on PRINT_START whenever that spool is loaded.

Hardware: a single USB endoscope mounted at 45° on the Stealthburner toolhead, plugged into one of the BTT EBB SB2209 USB v1.0's three onboard USB hub ports, sharing the existing XT30 USB cable to the Pi. Only powered/streamed during calibration runs (software gating; not added to crowsnest's normal stream config).

**Non-goals:**

- Real-time in-print monitoring (failure detection, etc.) — the chamber cam keeps its existing job; this is a different cam for a different job.
- Continuous nozzle-view monitoring during prints — thermal load + spatter + lens fouling rule out a $20 endoscope at that proximity continuously.
- Slicer profile write-back — converged values live in Spoolman + Klipper save_variables; PRINT_START applies them per loaded spool. The slicer's filament profile stays the "starting point" only.
- Lidar / DIY laser triangulation — surveyed; rubedo exists but author calls it brittle; Bambu's micro-lidar isn't sold aftermarket. Deferred indefinitely.
- Bayesian optimization across joint (PA, flow, temp). Cascaded 1-D golden-section search is the right tool for hobbyist scale.
- Cloud ML inference. undingen's project uses fal.ai-hosted BiRefNet; we run local OpenCV only.
- First-layer squish calibration (separate future issue, same hardware).

## 3. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  HARDWARE                                                      │
│                                                                │
│   Stealthburner toolhead                                       │
│     ├── EBB SB2209 USB v1.0 (existing)                         │
│     │     └── USB hub: 3 downstream ports (1 used)             │
│     │           └── USB endoscope (NEW)                        │
│     │                 └── 45° down-forward mount (printed)     │
│     │                                                          │
│     └── XT30 USB cable to Pi (existing) — carries Klipper      │
│           traffic + endoscope MJPEG/YUYV stream                │
│                                                                │
│   Pi (mainsailos.local)                                        │
│     ├── /dev/videoN ← endoscope (NOT in crowsnest config)      │
│     ├── /dev/video0 ← chamber cam (existing crowsnest stream)  │
│     └── ~/printer_data/scripts/calibrate_endoscope/  (NEW)     │
│           ├── capture.py        (v4l2 + OpenCV capture+correct)│
│           ├── score_pa.py       (PA line uniformity scorer)    │
│           ├── score_flow.py     (top-surface variance scorer)  │
│           ├── narrow.py         (golden-section iterator)      │
│           ├── spoolman.py       (Moonraker → Spoolman client)  │
│           ├── seed.py           (3dfilamentprofiles lookup +   │
│           │                     local cache; best-effort)      │
│           └── calibrate.py      (orchestrator entrypoint)      │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CONFIG (NEW: config/calibrate_endoscope.cfg)                  │
│                                                                │
│   [gcode_shell_command calibrate_endoscope]                    │
│     command: /home/pi/printer_data/scripts/calibrate_endoscope │
│                /calibrate.py                                   │
│     timeout: 1800.0                                            │
│                                                                │
│   [gcode_macro DIAL_IN_FILAMENT]                               │
│     params: SPOOL_ID, [SKIP_TEMP=0], [SKIP_FLOW=0], [SKIP_PA=0]│
│     → cascade: prints temp tower → calls scorer (human pick    │
│       for temp) → SET temp → prints flow grid → CV pick →      │
│       SET flow → prints PA grid → CV pick → SET PA →           │
│       writes all three to Spoolman                             │
│                                                                │
│   [gcode_macro APPLY_SPOOL_CALIBRATION]                        │
│     called from PRINT_START; reads Spoolman per spool_id,      │
│     issues SET_PRESSURE_ADVANCE / M221 / M104, logs applied    │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

Data flow per calibration phase:

```
Klipper macro              Python helper               Spoolman
─────────────              ─────────────               ────────
PRINT_TEMP_TOWER  ──────►  (sleep until done)
                            capture.py ──► save frames
                            score → render montage in Mainsail
                            ◄── user clicks winner
                                                 ─────► PATCH spool extras
SET_TEMP_FROM_RESULT ◄──────  result back

PRINT_FLOW_GRID   ──────►  (sleep until done)
                            capture.py + score_flow.py
                            narrow.py → next params
                            (loop until converged or maxed)
                                                 ─────► PATCH spool extras
SET_FLOW_FROM_RESULT ◄──────  result back

(same shape for PA)
```

## 4. Phase plan

Each phase ships independently and proves itself end-to-end before the next starts. **Order is not negotiable** — Phase 0 de-risks the entire project; PA before Flow because prior art exists; Temp last because it's the most novel UI piece.

**Implementation note:** this spec spans 4 phases that each warrant their own implementation plan. Execute via `superpowers:writing-plans` *per phase* (`2026-05-21-auto-calibration-phase-0-hardware.md`, etc.) rather than one monolithic plan. Phase N's plan starts only after Phase N-1's gate is met on real hardware.

| Phase | Scope | Deliverable | Gate to next |
|---|---|---|---|
| **0. Hardware + capture pipeline** | Endoscope, 45° Stealthburner mount, USB to EBB, udev rule, perspective-correction via ChArUco fiducial, exposure/WB lock, end-to-end "take a clean repeatable in-focus image of a test print." NO scoring. Includes verifying the as-shipped endoscope's actual focal range matches the chosen toolhead-Z parking position (3-8 cm spec claim from listing is unverified until in hand; if actual focal is shifted, adjust mount geometry or accept narrower Z parking range). | Working `capture.py` returning a perspective-corrected PNG of a flat known-position artifact, repeatable across sessions to ±2 px. | Sample images visually identical session-to-session at the same artifact. |
| **1. PA calibration** | Fork [undingen/PressureAdvanceCamera](https://github.com/undingen/PressureAdvanceCamera), de-cloud (replace fal.ai BiRefNet with local classical segmentation), add perspective-correction step, wrap iterative narrowing, write back to Spoolman. | `CALIBRATE_PA SPOOL_ID=X` macro converges in ≤3 iterations on a known-good filament, persists result. | Two consecutive runs on the same spool converge to within ±0.005 PA. |
| **2. Flow calibration** | Same chassis as Phase 1; novel CV — SuperSlicer-style top-surface uniformity (Laplacian variance + edge-gap detection) on a 3-5 cube grid. | `CALIBRATE_FLOW SPOOL_ID=X` macro converges in ≤3 iterations, persists result. | Two consecutive runs on the same spool converge to within ±2% flow. |
| **3. Temp calibration (human-in-loop)** | Same chassis, no scoring CV. Captures a standardized photo of each band of a temp tower (re-parking toolhead per band for focus), renders a montage in Mainsail with a click-to-pick UI, persists chosen temp. | `CALIBRATE_TEMP SPOOL_ID=X` macro prints tower, presents montage, persists selection. | Used end-to-end on 2 different filaments with clear picks. |
| **4. Orchestration** | `DIAL_IN_FILAMENT SPOOL_ID=X` runs Seed → Temp → Flow → PA cascade. `seed.py` resolves starting-point hierarchy (Spoolman spool → Spoolman filament → 3dfilamentprofiles → defaults per §9.1), auto-populates Spoolman filament records from 3dfilamentprofiles when missing (§9.2). `APPLY_SPOOL_CALIBRATION` called from PRINT_START reads Spoolman and issues `SET_PRESSURE_ADVANCE` + `M221` + `M104` per loaded spool. | One-shot dial-in of a new spool with no operator interaction beyond starting it + one temp-pick click. | End-to-end run completes (Temp → Flow → PA → all three persisted to Spoolman) with no manual intervention beyond the temp click. Wall time ~1.5-3 hours expected; not gated. |

## 5. Calibration test artifacts and bed layout

All three tests fit in one corner of the bed (~150×150 mm), leaving the rest free for normal prints. The cascade reuses the *same* corner across phases because the camera mount's perspective-correction calibration is anchored to a specific XY region.

```
Bed (350×350, looking down)
┌──────────────────────────────────────────────┐
│                                              │
│                                              │
│                                              │
│                                              │
│       ┌──────────────────┐                   │  (rest of bed
│       │ Flow grid        │                   │   free for
│       │ 5 cubes 20×20    │  100 mm           │   normal prints)
│       │ in a row         │                   │
│       ├──────────────────┤                   │
│       │ PA pattern       │  60 mm            │
│       │ Ellis-style      │                   │
│       │ 5 line variants  │                   │
│       ├──────────────────┤                   │
│       │ Temp tower       │  100 mm tall      │
│       │ 40×40 footprint  │  (only during     │
│       │ 5 bands × 20mm   │   Phase 3 runs)   │
│       └──────────────────┘                   │
│        ChArUco fiducial printed below tests  │
│        (or permanently affixed to bed)       │
│                                              │
└──────────────────────────────────────────────┘
```

**PA pattern**: 5 horizontal lines at 5 different PA values, each ~40 mm long, ~10 mm apart, printed as 2nd or 3rd layer over a thin known-good base patch (avoids first-layer adhesion noise per research findings). Standard Klipper-doc PA test geometry.

**Flow grid**: 5 small (20×20×3 mm) thin-walled cubes in a row at 5 different flow multipliers. Top surface inspected for gaps (under-extrusion) or ridges (over-extrusion). SuperSlicer-style.

**Temp tower**: standard banded tower with stringing pillars + small overhangs per band. 5 bands × 20 mm tall = 100 mm. Each band gets photographed separately (toolhead re-parks at that band's Z to keep it in focus given the 3-8 cm focal range).

**ChArUco fiducial**: a 100×100 mm printed marker pattern below the test area (or printed once and adhered semi-permanently). Used per-session by `capture.py` to compute the perspective transform — eliminates mount drift, slight toolhead positioning variance, and tilt errors.

## 6. Image capture pipeline

`capture.py` is the only module that touches v4l2 / OpenCV / the camera. Single responsibility: given a `(parking_x, parking_y, parking_z)`, return a clean perspective-corrected PNG of what the camera sees.

Sequence per capture:

1. **Move toolhead** to parking position (caller's responsibility; `capture.py` only requires position be reached + stable for ≥500 ms).
2. **Open `/dev/videoN`** (V4L2 device, NOT through crowsnest).
3. **Force MJPEG → YUYV** if possible (raw avoids high-frequency compression artifacts per research). Fall back to MJPEG with quality=highest if YUYV unsupported.
4. **Lock auto-exposure + auto-WB** via `v4l2-ctl --set-ctrl=exposure_auto=1,white_balance_temperature_auto=0`. Set fixed exposure + WB based on per-mount calibration constants (determined in Phase 0).
5. **Discard first 3 frames** (cam stabilization after exposure change).
6. **Capture frame N** (4th frame onward) at native resolution.
7. **Close device.**
8. **Locate ChArUco fiducial** in the frame (`cv2.aruco.detectMarkers`).
9. **Compute perspective transform** from detected fiducial corners to known canonical positions.
10. **Apply transform** (`cv2.warpPerspective`) → output is a top-down equivalent of the artifact region.
11. **Save** to `~/printer_data/scripts/calibrate_endoscope/captures/<spool_id>/<phase>/<iteration>/<variant>.png`.

`capture.py` does NOT score. Scoring modules consume PNGs from the captures directory.

**LED handling**: endoscope's built-in LEDs are turned OFF before capture (`v4l2-ctl --set-ctrl=led_mode=0` if supported, else accept). Lighting is provided by chamber caselight at fixed brightness (set via existing `CASELIGHT_ON VALUE=...` macro from `config/macros/macros.cfg`).

**Failure modes** at this layer:
- Device not found → exit code 10, macro reports "endoscope not detected; check USB cable to EBB hub."
- ChArUco not detected → exit code 11, macro reports "fiducial not visible; check mount position and lighting."
- Frame capture timeout → exit code 12, retry once before giving up.

## 7. Scoring algorithms

### PA (Phase 1)
**Fork of [undingen/PressureAdvanceCamera](https://github.com/undingen/PressureAdvanceCamera) `analyze.py`** with these modifications:

1. **De-cloud:** replace BiRefNet (fal.ai-hosted) with local classical OpenCV — adaptive thresholding (`cv2.adaptiveThreshold`) + contour finding to isolate each line. Filament color/contrast permitting; fall back to manual region-of-interest selection in the worst case.
2. **Add perspective-correction input:** consume the already-warped PNGs from `capture.py`, not raw camera frames.
3. **Scoring metric (unchanged from upstream):** for each line, sample N transverse profiles along its length; compute thickness at each profile; score = standard deviation of thickness. Lower = more uniform = better PA.
4. **Output:** ranked list of (variant_index, score) tuples, written as JSON to stdout.

### Flow (Phase 2)
Novel CV, no prior art. For each top surface of the N flow cubes:

1. **Isolate top surface ROI** from the warped capture using known cube positions (computed from print plan).
2. **Compute Laplacian variance** (`cv2.Laplacian(roi, cv2.CV_64F).var()`) → texture roughness proxy. Under-extruded surfaces have gaps → high variance. Over-extruded surfaces have ridges → also high variance. Well-tuned surface is smooth → low variance.
3. **Sanity check via edge detection:** Canny edges within the ROI. Many edges = visible gaps or ridges → confirms variance signal.
4. **Score = inverse of Laplacian variance** (so higher score = smoother = better). Sanity-check by edge count: if variance is low but edges are present, flag suspicious result.
5. **Output:** ranked list of (variant_index, score, [warnings]).

**Risk:** the Laplacian-variance signal is sensitive to filament color contrast against itself (a glossy black surface has near-zero variance regardless of actual smoothness). Mitigation: per-spool exposure calibration in Phase 0 + sanity-check warnings; if all variants score within 5% of each other, flag "indeterminate" and fall back to human pick.

### Temp (Phase 3)
**No CV scoring.** Sheen/texture scoring was considered and rejected: variation by material chemistry, pigment, moisture, and lighting overwhelms the signal (see research notes; Bambu also chose not to auto-cal temp).

Instead: capture one clean photo per temp band, render a montage in Mainsail with band-temperature labels overlaid, user clicks the best one. The iterative-narrowing logic still applies (chosen winner becomes the center of the next iteration's narrower band) but the *intelligence* is in the operator's eyes.

Future enhancement (filed as separate issue if it ever happens): geometric-defect scoring — count strings in the gap between stringing pillars (`cv2.HoughLinesP` in a known ROI), measure bridge sag via edge detection on overhang undersides. Robust to material variation in a way sheen isn't. Out of scope for this spec.

## 8. Iterative narrowing algorithm

Same algorithm for PA and Flow (Temp uses the same band-narrowing but operator picks the winner each round).

**Per phase:**

```
band = (param_min, param_max)         # e.g., PA: (0.0, 0.1)
variants_per_iter = 5
max_iter = 3
convergence_threshold = configurable per phase
                                       # PA: ±0.005
                                       # Flow: ±0.02 multiplier

for iter in range(max_iter):
    variants = linspace(band[0], band[1], variants_per_iter)
    # print all 5 variants on bed at known positions
    PRINT_TEST_PATTERN(variants=variants)
    # capture all 5 in one pass
    for v in variants:
        capture.py at known position
    # score
    ranked = score_module(captures)
    winner = ranked[0].variant
    second = ranked[1].variant
    spread = abs(winner - second)
    if spread <= convergence_threshold:
        return winner   # converged
    # narrow band around winner: halve the band width, recenter
    band_width = (band[1] - band[0]) / 2
    band = (winner - band_width/2, winner + band_width/2)
    # clamp to physical limits
    band = clamp(band, PHYSICAL_MIN, PHYSICAL_MAX)

return winner   # max_iter reached; return best so far + warning
```

**Stop conditions:**
- Converged (`spread <= threshold`): return winner, success.
- Max iterations reached: return current best with a warning logged + reported to operator.
- All variants score within 5% of each other (indeterminate): return current best with `INDETERMINATE` warning; operator must confirm before persistence.
- Capture pipeline failure (exit code from `capture.py`): abort, leave Spoolman unchanged.

**Per-phase parameters (initial values; tunable in `config/calibrate_endoscope.cfg` after Phase 4 ships):**

| Phase | Param range | Variants/iter | Max iter | Convergence |
|---|---|---|---|---|
| PA | 0.0 – 0.1 | 5 | 3 | ±0.005 |
| Flow | 0.85 – 1.15 | 5 | 3 | ±0.02 |
| Temp | manufacturer ±20°C | 5 (20°C bands narrowing to 4°C) | 3 | operator picks |

## 9. Persistence + starting points (Spoolman + 3dfilamentprofiles)

### 9.1 Starting-point hierarchy

When `DIAL_IN_FILAMENT SPOOL_ID=X` runs, the initial band for each parameter is centered on the best starting point we can find, queried in this order (first hit wins):

1. **Spoolman per-spool calibration** (`spool.extra.calibration`) — if this spool was previously calibrated, use those values. Narrow initial band tightly (±10% of the convergence threshold). Use case: re-verify after a Klipper version bump or hardware change.
2. **Spoolman per-filament defaults** (`filament.extra.calibration_defaults`) — if another spool of this same filament was previously calibrated, inherit. Narrow initial band moderately. Use case: second spool of a known filament; biggest practical win since it skips the seed lookup entirely.
3. **3dfilamentprofiles.com lookup** (best-effort scrape) — if filament+brand matches a profile on the community site, use those values as seed. Wider initial band (default range × 0.5).
4. **Slicer defaults** (last resort) — full default band. Use case: brand-new unfamiliar filament with no community data.

Each phase logs which starting-point source it used, so the operator can audit (and re-run with wider bands if a stale starting point led the cascade astray).

### 9.2 Spoolman filament-record auto-population

If the loaded `SPOOL_ID` points to a Spoolman spool whose `filament` field is null OR points to a filament record missing core fields (manufacturer, material, color, density, diameter), and 3dfilamentprofiles has a match: auto-create or auto-update the Spoolman filament record with the looked-up metadata. This is one-time per filament (subsequent spools find a populated record).

Fields populated when available from the lookup: `manufacturer`, `material`, `name`, `color_hex`, `density`, `diameter`, `price` (informational), `comment` (link back to the 3dfilamentprofiles entry).

Operator can override any auto-populated field via Spoolman's UI before or after.

### 9.3 3dfilamentprofiles client (`seed.py`)

- **One lookup per `DIAL_IN_FILAMENT` invocation**, not per phase. Result is held in memory for the cascade duration.
- **Rate-limit self-imposed**: max 1 request per 5 seconds, with exponential backoff on 429.
- **Cache**: successful lookups stored locally at `~/printer_data/scripts/calibrate_endoscope/seed_cache/<brand>-<material>-<color>.json` for 90 days. Cache hit = no network call.
- **Failure is non-fatal**: on 429 / timeout / parse failure, log and skip — cascade falls back to hierarchy step 4 (slicer defaults). Never blocks calibration.
- **Future improvement**: if the upstream ever ships a bulk JSON export or REST API (file as enhancement issue), swap the scraper for the structured source. Architecture keeps scraping isolated to `seed.py` so this swap is local.

**Scraping etiquette**: lookups happen at most once per new spool registration, so worst case is one request per spool added to the printer. Not a load problem in practice.

### 9.4 Spoolman schema (existing convention extended)

Per-spool calibration data lives in Spoolman's extra-fields per spool. Schema (extends [#72](https://github.com/bjdeng/voron-2-611/issues/72)):

```json
{
  "extra": {
    "calibration": {
      "pressure_advance": 0.045,
      "pressure_advance_calibrated_at": "2026-05-21T14:30:00Z",
      "pressure_advance_calibration_conditions": {
        "temp": 240,
        "flow": 0.98,
        "speed_mm_s": 100,
        "klipper_version": "..."
      },
      "flow_multiplier": 0.98,
      "flow_calibrated_at": "...",
      "flow_calibration_conditions": {"temp": 240, ...},
      "extruder_temp": 240,
      "temp_calibrated_at": "...",
      "temp_calibration_method": "human-pick"
    }
  }
}
```

PA + Flow calibration conditions are recorded because both optima shift with the other parameters (research note: "PA optimum shifts with speed, accel, line width, layer height" — store the conditions so future logic can decide whether to re-calibrate).

**`APPLY_SPOOL_CALIBRATION SPOOL_ID=X`** (called from PRINT_START):
1. Query Moonraker for spool details (`GET /server/spoolman/proxy?request_method=GET&path=/api/v1/spool/{id}`).
2. Read `extra.calibration` field.
3. If missing → log "spool not calibrated; using slicer defaults" and exit (don't fail PRINT_START).
4. If present:
   - `SET_PRESSURE_ADVANCE ADVANCE={pressure_advance}`
   - `M221 S{flow_multiplier * 100}`
   - `M104 S{extruder_temp}` ONLY if PRINT_START's `EXTRUDER=` param matches calibrated temp ±10°C (don't override slicer's deliberate choice).
5. Log applied values to console + persistent log file.

## 10. Orchestration macro

`DIAL_IN_FILAMENT SPOOL_ID=X [SKIP_TEMP=0] [SKIP_FLOW=0] [SKIP_PA=0] [SKIP_SEED=0]`

```
Phase 0: SEED LOOKUP  (unless SKIP_SEED=1)
   → resolve starting-point hierarchy per §9.1
   → if Spoolman filament record missing fields, populate from
     3dfilamentprofiles (§9.2)
   → store seed values + source in memory for the cascade
Phase 1: CALIBRATE_TEMP  (unless SKIP_TEMP=1)
   → initial band centered on seed value (or default if no seed)
   → human pick → SET extruder target → persist
Phase 2: CALIBRATE_FLOW at chosen temp
   → initial band centered on seed
   → CV pick → SET M221 → persist
Phase 3: CALIBRATE_PA at chosen temp + flow
   → initial band centered on seed
   → CV pick → SET_PRESSURE_ADVANCE → persist
   → final report to console (including seed source per phase)
```

Total wall time on a brand-new spool: ~1.5-3 hours, walk-away (except for one click during temp pick). Operator pre-loads the spool, runs `DIAL_IN_FILAMENT SPOOL_ID=42`, comes back.

The cascade can be interrupted at any phase boundary; partial results persist (e.g., temp + flow done but PA failed → those two values stay in Spoolman; PA can be re-run later via `CALIBRATE_PA SPOOL_ID=42`).

## 11. Failure modes + recovery

| Failure | Symptom | Recovery |
|---|---|---|
| Endoscope cable loose / not detected | `/dev/videoN` missing | Operator re-seats USB at toolhead. `capture.py` exit 10; macro aborts cleanly. |
| ChArUco fiducial not visible | Marker detection fails | Operator checks bed for fiducial (re-print if abraded); lighting check. |
| All variants score equally (indeterminate) | Score spread <5% across variants | Warning surfaced; operator confirms or re-runs with wider band. |
| First-layer adhesion noise dominates | PA scoring noisy | (Already mitigated: PA test prints as 2nd-3rd layer over base patch. If still noisy, increase base patch thickness.) |
| Filament color too dark (no contrast) | All PA/Flow scores cluster low | Surface as warning at score time; operator can override or skip phase. Document known-bad filament categories per spool in Spoolman. |
| Spoolman unreachable | Moonraker proxy call fails | Cascade still runs; results buffer locally to `~/printer_data/scripts/calibrate_endoscope/pending_writes/`; retry on next macro invocation. |
| Print fails mid-test (Eddy probe error, etc.) | Klipper aborts print | Cascade aborts; partial captures preserved; no Spoolman write. Re-run after fixing root cause. |
| Endoscope LEDs interfere with lighting | Glare in captures | Disable LEDs in `capture.py` (Phase 0 deliverable). |
| Chamber temp soak above endoscope rating | Cam degrades over months | Document expected lifespan; treat as $20 consumable; replace yearly if used heavily. |

## 12. Risks + open questions

**Resolution risk (PRIMARY).** Research consensus is that toolhead endoscopes work for PA; flow is novel; temp is intractable. We're betting on flow scoring working at ~21 px/mm with Laplacian-variance. Phase 2 might land "doesn't work reliably" and need either better CV or admit-and-fall-back-to-human-pick. Acceptable outcome: Phase 2 ships as human-pick like Phase 3 if CV fails. Risk → acknowledged, not blocking.

**Depth-of-field risk.** At 45° with ~5-8 cm working distance, DOF is ~10-30 mm. A 40 mm PA line tilted 45° spans ~28 mm depth — at the edge. Phase 0 must verify in-focus capture across the full artifact, not just at center. If DOF is the binding constraint, shrink artifact size (smaller PA lines, smaller flow cubes).

**Mount drift.** Toolhead-mounted cam sees small position drift from toolhead Z homing variance + slight mount flex. Per-session ChArUco recalibration mitigates. Phase 0 must confirm session-to-session repeatability ≤ ±2 px.

**Filament color failure modes.** Black-on-bed and translucent filaments are known dragons for CV scoring (per research + general OpenCV experience). Document expected failure cases up-front; per-spool exposure tuning in extra fields if needed.

**EBB USB bandwidth contention.** XT30 USB 2.0 carries Klipper traffic + endoscope. During calibration, capture is brief (single frames, not streams). Should be no contention. Phase 0 must verify no `MCU 'EBB' rescheduled' errors during capture.

**Heat budget on toolhead cam.** Chamber soak at 50-60 °C is at/above cheap endoscope rating. Plan: $20 consumable, ~yearly replacement. Mount slightly offset from nozzle to keep optics out of direct IR path.

**Cloud-dependency in PressureAdvanceCamera fork.** Upstream uses fal.ai BiRefNet — we strip this and use classical OpenCV. If classical seg doesn't work for some filament/lighting combo, optional fallback: local Pi U-Net (slower but offline). Don't ship cloud as a fallback.

**Convergence non-monotonicity.** Golden-section assumes monotonic scoring around the winner. If the response is multi-modal (could happen at filament-edge conditions), convergence may oscillate. Max-iter cap + INDETERMINATE warning catches it.

**Slicer profile divergence.** This system persists per-spool calibration to Spoolman; the slicer's filament profile still has its own values. If the operator manually changes the slicer profile, the runtime override from `APPLY_SPOOL_CALIBRATION` will still win at print time, but the slicer's preview shows wrong values. Acceptable; document.

**3dfilamentprofiles scraper brittleness.** No public API; HTML scraping is fragile to markup changes and rate-limited (we confirmed 429s during research). Mitigations: best-effort only (never blocks cascade), 90-day local cache, 1 request per 5s self-imposed rate limit, isolated to `seed.py` so swapping to a future API is local. If the upstream ships a bulk JSON export, switch immediately. Worst case: scraper breaks, all seed lookups return empty, cascade falls back to slicer defaults — calibration still works, just slower for unfamiliar filaments.

**Stale seed values.** A community-submitted PA/flow value may be wrong for our specific setup (different extruder, different hotend, different nozzle wear). Mitigation: seed only centers the *initial* band; iterative narrowing still validates empirically. If narrowing diverges, the cascade catches it via INDETERMINATE warning. Document that "seed = starting point, not gospel."

## 13. Out of scope (file as separate issues)

- **First-layer squish calibration.** Same endoscope at 45° can view bead-bed interface during first-layer. Pairs with Eddy probe tap calibration. File: "First-layer squish CV alongside Eddy tap."
- **Nozzle-view die-swell flow pre-screen.** Could augment Phase 2 with a faster first-pass flow estimate from a static extrusion test. Marginal value if Phase 2 works; file as stretch.
- **Geometric-defect temp scoring.** Replace human-pick in Phase 3 with stringing-pillar gap detection + bridge sag measurement. Material-robust per research. File as Phase 3 enhancement.
- **Auto-calibration on spool change.** Detect new spool via HH / Spoolman, auto-trigger `DIAL_IN_FILAMENT` if no calibration data exists. Requires Phase 4 working + good failure handling. File as orchestration enhancement.
- **DIY laser-triangulation lidar upgrade.** rubedo-style hardware retrofit. Indefinite future; revisit when hobbyist landscape ships packaged solutions.
- **Inverse use of endoscope: continuous in-print monitoring.** Thermal + spatter + lens fouling rule this out for a $20 cam; would need a thermally-isolated industrial cam. Not scoping.

## 14. Testing

Per the [`tests/README.md`](../../../tests/README.md) pyramid:

- **L1 pre-commit:** Python files run through ruff (existing hook).
- **L2 macro_refcheck:** new `DIAL_IN_FILAMENT`, `APPLY_SPOOL_CALIBRATION`, `CALIBRATE_PA/FLOW/TEMP` macros pass cross-reference check.
- **L3 klippy parse + MCU load:** the new `config/calibrate_endoscope.cfg` must load cleanly in CI's smoke test.
- **L4 pytest:** `scripts/calibrate_endoscope/` modules get unit tests for:
  - `narrow.py` golden-section logic (synthetic scores → expected convergence)
  - `score_pa.py` / `score_flow.py` against fixture PNG images (golden outputs)
  - `spoolman.py` against a mocked Moonraker proxy
  - `capture.py` against pre-recorded V4L2 frames (no live camera in CI)
  - `seed.py` against fixture HTML pages (no live 3dfilamentprofiles in CI; cache hit + miss + 429 fallback paths)
- **L5 structural:** spec says Phase 0 must verify session-to-session repeatability ≤ ±2 px on the same artifact. Quantitative gate.
- **L6 post-deploy smoke:** new macros surface in `MACRO_LIST`; `CALIBRATE_PA SPOOL_ID=test-spool DRY_RUN=1` reaches scoring without printing. Adds to `scripts/deploy_to_pi.sh --smoke`.
- **L7 live calibration:** running `DIAL_IN_FILAMENT SPOOL_ID=X` on a known-good filament converges to within ±5% of the previously-validated manual calibration. Done once per phase ship.

CI does NOT cover: the camera itself, the scoring quality, convergence on real prints. Those are post-deploy validation per phase.

## 15. References

**Prior art (use these as starting points, not blank slates):**
- [undingen/PressureAdvanceCamera](https://github.com/undingen/PressureAdvanceCamera) — Phase 1 forks this. GPL-3.0, compatible with our repo license.
- [furrysalamander/rubedo](https://github.com/furrysalamander/rubedo) — DIY laser triangulation, brittle but informative.
- [Frix_x's calibrate_pa.cfg / calibrate_flow.cfg](https://github.com/Frix-x/klippain) — already in our `config/macros/`; the manual workflows we're automating.

**Research findings driving this spec:**
- Bambu micro-lidar: toolhead-mounted, stores K per filament (not per spool) — we go finer with per-spool.
- AM ARES (Deneault et al., MRS Bulletin 2021): Bayesian opt on extrusion printing; academic-grade closed-loop. We're explicitly NOT doing Bayesian opt at hobbyist scale.
- BTT EBB SB2209 USB v1.0 docs (vendored at `vendor/btt-docs/docs/EBB SB2209 USB.md`): onboard hub, 3 USB ports, 1A 5V budget, 1080p cam recommended.

**Hardware references:**
- DEPSTECH USB Endoscope 2.0 MP IP67 (Amazon B0749BQG1B) — primary endoscope candidate, 3-8 cm focal range.
- BTT EBB SB2209 USB v1.0 — existing toolhead board with hub.

**Community data:**
- [3dfilamentprofiles.com](https://3dfilamentprofiles.com/) — community-curated DB of ~27k filaments / 1k brands. Used by `seed.py` as best-effort starting-point source. No public API as of 2026-05; scraped opportunistically with local cache.
- [MarksMakerSpace/filament-profiles (GitHub)](https://github.com/MarksMakerSpace/filament-profiles) — upstream repo for bug reports + brand logo contributions. File enhancement request here if/when a bulk export becomes worthwhile.

**Internal:**
- [`config/macros/calibrate_pa.cfg`](../../../config/macros/calibrate_pa.cfg) — Frix_x PA macro we're augmenting (NOT replacing).
- [`config/macros/calibrate_flow.cfg`](../../../config/macros/calibrate_flow.cfg) — Frix_x flow macro we're augmenting.
- [`memory/indx-retrofit-intent.md`](../../../memory/indx-retrofit-intent.md) — why per-spool matters.
- [#27](https://github.com/bjdeng/voron-2-611/issues/27) (webcam re-enable, CLOSED) — chamber cam is back; this project uses a DIFFERENT cam on the toolhead.
- [#28](https://github.com/bjdeng/voron-2-611/issues/28) — deploy-to-pi automation; Phase 0 udev rule + scripts/ install hook to wire in.
- [#42](https://github.com/bjdeng/voron-2-611/issues/42) — Layer 6 post-deploy smoke; calibrate_endoscope adds to its checks.
- [#72](https://github.com/bjdeng/voron-2-611/issues/72) — MMU spool tracking / Spoolman extras; HARD DEPENDENCY for Phase 4.
- [#79](https://github.com/bjdeng/voron-2-611/issues/79) — Filament calibration skill (manual); this spec's manual fallback paths reuse #79's logging format.
