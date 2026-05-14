# Migrate BTT Eddy probe from `vvuk/eddy-ng` to native Klipper `[probe_eddy_current]`

| | |
|---|---|
| **Spec date** | 2026-05-13 |
| **Target** | Voron 2.611 (Voron 2.4 r2, 350 mm) |
| **Status** | Awaiting user review before plan |
| **Author** | Ben + Claude (via `superpowers:brainstorming`) |
| **Implementation skill (next)** | `superpowers:writing-plans` |
| **Review skill (at PR time)** | `pr-review-toolkit:review-pr` |

---

## 1. Summary

Drop the third-party `vvuk/eddy-ng` Klipper extension and move the BTT Eddy probe onto upstream Klipper's native `[probe_eddy_current]` (verified to ship in `vendor/klipper` at commit `4767a8ed`, which is what the printer runs). The eddy-ng install directory and its Klipper symlinks stay in place after this migration; they're removed in a separate later cleanup spec once the new stack is proven stable.

## 2. Why

- **Stop running on a third-party fork.** `~/eddy-ng/install.sh` must be re-run after every Klipper update; native eliminates the dance.
- **Native covers every feature in active use** — `rapid_scan` for bed mesh, `tap` probing, drive-current calibration. Verified by reading `vendor/klipper/klippy/extras/probe_eddy_current.py` and `vendor/klipper/docs/Eddy_Probe.md`.
- **Unblocks the webcam re-enable** (separate spec). The webcam was unplugged due to a suspected timing conflict with eddy-ng's polling.

## 3. Constraints (confirmed with user)

| Constraint | Source |
|---|---|
| Always do a final tap as part of `PRINT_START` (no auto temperature compensation, no `[temperature_probe]`). | User, 2026-05-13 |
| Stay on USB for the EBB SB v1.0 toolhead. CAN migration is a separate future spec. | User, 2026-05-13 |
| Done-ness criterion: **probe parity + first test print** — no webcam, no PID/shaper re-runs. | User, 2026-05-13 (AskUserQuestion answer) |
| Cleanup strategy: **disable eddy-ng in config only** in this migration. Leave `~/eddy-ng` install on the Pi. Schedule a follow-up cleanup pass after stability. | User, 2026-05-13 (AskUserQuestion answer) |
| Approach: **in-place rewrite on a `feat/eddy-native` worktree** (not side-by-side files in `printer.cfg`). | User, 2026-05-13 |
| Preserve the **two-pass QGL** override byte-for-byte. The first pass at `horizontal_move_z=8` accommodates the V2.4's saggy rear; don't collapse it. | User, 2026-05-13 — see [[v24-saggy-rear-qgl]] memory |
| Don't worry about preserving the `[bed_mesh default]` SAVE_CONFIG block. `PRINT_START` runs adaptive mesh every print. | User, 2026-05-13 |

## 4. Architecture

### Hardware (no change)

The BTT Eddy probe board (`mcu eddy`, RP2040, USB-attached at `/dev/serial/by-id/usb-Klipper_rp2040_5044340310B85E1C-if00`) physically stays where it is. The LDC1612 inductive sensor on the toolhead, the EBB SB v1.0 USB connection, the bed, the gantry — none of these change.

### Klipper module swap

| Today (eddy-ng) | After migration (native) |
|---|---|
| `[mcu eddy]` | `[mcu eddy]` *(unchanged)* |
| `[probe_eddy_ng btt_eddy]` with `sensor_type: btt_eddy`, `tap_mode: butter`, `tap_samples_stddev: 0.3` | `[probe_eddy_current btt_eddy]` paired with an `[ldc1612 btt_eddy]` sensor block. The `tap_*` parameters are replaced by a calibrated `tap_threshold` (numeric). `descend_z: 0.5` per docs recommendation. |
| `[bed_mesh]` with `algorithm: bicubic`, `probe_count: 9, 9`, mesh range (15, 21.42)→(335, 330) | Same block, unchanged. |
| `[safe_z_home]` at (175, 175), z_hop 10 | Same, unchanged. |
| `[force_move] enable_force_move: True` | Same, unchanged. |
| `[gcode_macro QUAD_GANTRY_LEVEL]` two-pass override (saggy rear) | Same, **byte-for-byte preserved**. |
| `[gcode_macro BED_MESH_CALIBRATE]` override → `BTT_BED_MESH_CALIBRATE ADAPTIVE=1 METHOD=rapid_scan` | Same body. `METHOD=rapid_scan` is valid in native (`vendor/klipper/docs/Eddy_Probe.md:147`). |
| `position_min: -5` on `[stepper_z]` | Same, unchanged (native tap requires `≤ -1`; we already have it). |

### `PRINT_START` contract preserved

Today's `PRINT_START` (in `macros/print_start.cfg`) calls, after bed heat:

```
BLOBIFIER_CLEAN
G28 Z              ; re-home Z after QGL
PROBE_EDDY_NG_TAP  ; the tap-at-print-start that Ben wants to keep
BED_MESH_CALIBRATE ADAPTIVE=1
```

After migration:

```
BLOBIFIER_CLEAN
G28 Z METHOD=tap   ; native equivalent — homes Z directly off a tap
BED_MESH_CALIBRATE ADAPTIVE=1
```

The `G28 Z METHOD=tap` form is the documented native idiom (`vendor/klipper/docs/Eddy_Probe.md:197-209`). It collapses the previous two-step "tap then re-home" into a single homing operation that uses tap. **Verify-on-implementation:** if `G28 Z METHOD=tap` syntax requires Klipper > our pinned commit, fall back to the explicit `PROBE METHOD=tap` + `SET_KINEMATIC_POSITION Z={result}` pattern from the same docs section.

The `PROBE_EDDY_NG_SET_TAP_OFFSET VALUE=0` call in `PRINT_END` is **deleted** (no native equivalent — native doesn't accumulate a runtime tap offset).

## 5. Config diff (file-by-file)

### 5.1 `eddy.cfg` — full rewrite

The entire `[probe_eddy_ng btt_eddy]` block is replaced with native-equivalent blocks. Other sections (`[mcu eddy]`, `[temperature_sensor btt_eddy_mcu]`, `[temperature_sensor btt_eddy]`, `[bed_mesh]`, `[safe_z_home]`, `[force_move]`, and both `[gcode_macro …]` overrides) **stay**.

Indicative target structure (exact parameter values land during implementation after reading `vendor/klipper/klippy/extras/ldc1612.py` and `Config_Reference.md`):

```ini
[mcu eddy]
serial: /dev/serial/by-id/usb-Klipper_rp2040_5044340310B85E1C-if00
restart_method: command

[temperature_sensor btt_eddy_mcu]
sensor_type: temperature_mcu
sensor_mcu: eddy
min_temp: 10
max_temp: 100

[temperature_sensor btt_eddy]
sensor_type: Generic 3950
sensor_pin: eddy:gpio26

[ldc1612 btt_eddy]
intb_pin: <VERIFY>            # see §10 — read from vendor/btt-docs/docs/Eddy.md
i2c_mcu: eddy
i2c_bus: i2c0f

[probe_eddy_current btt_eddy]
sensor_type: ldc1612
x_offset: 0
y_offset: 21.42
descend_z: 0.5
# tap_threshold is populated by PROBE_EDDY_CURRENT_TAP_CALIBRATE

[bed_mesh]
horizontal_move_z: 2
speed: 200
mesh_min: 15, 21.42
mesh_max: 335, 330
probe_count: 9, 9
algorithm: bicubic
fade_start: 0.26
fade_end: 5
adaptive_margin: 5
scan_overshoot: 8

[safe_z_home]
home_xy_position: 175, 175
z_hop: 10
z_hop_speed: 25
speed: 200

[force_move]
enable_force_move: True

[gcode_macro QUAD_GANTRY_LEVEL]
rename_existing: _QUAD_GANTRY_LEVEL
gcode:
  SAVE_GCODE_STATE NAME=STATE_QGL
  BED_MESH_CLEAR
  {% if not printer.quad_gantry_level.applied %}
    _QUAD_GANTRY_LEVEL horizontal_move_z=8 retry_tolerance=1
  {% endif %}
  _QUAD_GANTRY_LEVEL horizontal_move_z=2
  RESTORE_GCODE_STATE NAME=STATE_QGL

[gcode_macro BED_MESH_CALIBRATE]
rename_existing: BTT_BED_MESH_CALIBRATE
gcode:
 BTT_BED_MESH_CALIBRATE ADAPTIVE=1 METHOD=rapid_scan
```

The `# Uncomment this if you are using Eddy as the probe…` commented blocks at the bottom of the current `eddy.cfg` (G28 override, SET_Z_FROM_PROBE, Z_OFFSET_APPLY_PROBE, etc.) are **deleted** — they're eddy-ng-specific scaffolding for features that are folded into native automatically.

### 5.2 `macros/print_start.cfg` — two-line surgical change

| Line | Today | After |
|---|---|---|
| 67 | `PROBE_EDDY_NG_TAP` | `G28 Z METHOD=tap` (verify-on-implementation; fallback noted in §4) |
| 93 | `PROBE_EDDY_NG_SET_TAP_OFFSET VALUE=0` | *(deleted)* |

### 5.3 `printer.cfg` — strip stale SAVE_CONFIG

The SAVE_CONFIG block at the bottom of `printer.cfg` currently contains a `#*# [probe_eddy_ng btt_eddy]` section (lines ~463-469 in the 2026-05-13 snapshot) holding base64-encoded eddy-ng calibration polynomials. **Delete that block.** All other SAVE_CONFIG entries (`[heater_bed]`, `[extruder]`, `[input_shaper]`, `[bed_mesh Default2]`, `[bed_mesh default]`) **stay untouched** — Klipper will replace `[bed_mesh default]` on first adaptive scan after migration, but it's harmless until then.

No change to the top-section `[include eddy.cfg]` line in `printer.cfg` — we rewrite `eddy.cfg` in place, not replace the include.

### 5.4 No changes (confirmed by grep)

`btt-ebb-sb-usb-v1.0.cfg`, `mainsail.cfg`, `timelapse.cfg`, `moonraker.conf`, `crowsnest.conf`, `sonar.conf`, `firmware/*.config`, all of `mmu/*`, and `macros/{macros,bedfans,lcd_tweaks,test_speed,calibrate_*}.cfg` are untouched. The `mmu/` tree has zero references to `probe_eddy_ng` or `PROBE_EDDY_NG_*` (verified by `grep -rin "eddy_?ng|probe_eddy_ng" --include='*.cfg' --include='*.conf' . | grep -v vendor/`).

## 6. Calibration sequence

Hands-on at the printer, ~45–60 min including warmup. Each step ends with `SAVE_CONFIG` (which restarts Klipper) before the next.

**Run the whole calibration at printing temperature.** The BTT Eddy is sensitive to coil/electronics temperature; calibrating cold and printing hot causes measurable drift. Hold the bed and hotend at the values below for steps 1–5. Bed at **60 °C** (per Ben — typical first-print bed temp; well above ambient so the bed plate is dimensionally settled), hotend at **200 °C** (typical PLA print temp; primary requirement is consistent thermal expansion of the toolhead and probe holder, not the specific filament). Keep the part-cooling fan off during calibration unless `Eddy_Probe.md` instructs otherwise.

0. **Warmup.** `M140 S60` + `M104 S200`. Soak ~5 min after both reach target so the gantry and bed plate thermally equilibrate. **Park toolhead near center, sensor 20 mm above bed** while soaking.
1. **Drive current calibration.** Toolhead centered, sensor ~20 mm above bed. `LDC_CALIBRATE_DRIVE_CURRENT CHIP=btt_eddy` → wait a few seconds → `SAVE_CONFIG`.
2. **Z-height calibration (paper test).** Toolhead centered, paper between nozzle and bed. `PROBE_EDDY_CURRENT_CALIBRATE CHIP=btt_eddy`, perform the paper test as prompted (per `vendor/klipper/docs/Bed_Level.md` "the paper test"), `ACCEPT`. Tool runs ~2 min of frequency-to-Z mapping. → `SAVE_CONFIG`. Inspect "noise / MAD_Hz" output against expected ranges in `Eddy_Probe.md`. Re-confirm the bed and hotend are still at target before continuing.
3. **Tap guess.** Toolhead centered, nozzle 3–10 mm above bed, **clean nozzle** (cold-pull or brush — important for tap accuracy), **finger on M112**. `PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=guess`. → `SAVE_CONFIG`.
4. **Tap refine.** Same starting position, same temperatures. `PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=refine`. → `SAVE_CONFIG`.
5. **Tap verify.** Same starting position, same temperatures. `PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=verify` — 5 taps in a row. → `SAVE_CONFIG` if stable.

Troubleshooting reference: `vendor/klipper/docs/Eddy_Probe.md:344+`.

## 7. Verification (done criteria)

### 7.1 Smoke (immediate, ~5 min after calibration completes)

1. `G28` — full home succeeds without error.
2. `QUAD_GANTRY_LEVEL` — converges within `retry_tolerance: 0.05` after at most the configured 5 retries.
3. `BED_MESH_CALIBRATE METHOD=rapid_scan` — full bed scan completes; output mesh has no NaN values, no spikes >0.3 mm.

### 7.2 First-print test

Slice and print a known-good reference G-code from the user's library. **Acceptance:**
- First-layer adhesion qualitatively at least as good as the most recent successful print of the same G-code.
- No missed-step or stutter mid-print.
- Print completes without abort.

Quantitative regression tests are out of scope.

## 8. Rollback procedure

Implementation runs on a `feat/eddy-native` git worktree (per `superpowers:using-git-worktrees`, using the native `EnterWorktree` tool — not `git worktree add`). `main` on the Pi is untouched until merge.

| Failure mode | Rollback action |
|---|---|
| Klipper errors on `RESTART` after first sync of new `eddy.cfg` (config syntax / unknown section / pin clash). | `git checkout main` → rsync to Pi → `RESTART`. eddy-ng install is still in place; the old config works immediately. |
| Calibration step fails mid-sequence. | Same. Half-written native SAVE_CONFIG entries become harmless once `[probe_eddy_ng]` is the active block again. |
| Smoke test fails (probe works during calibration but not at print start). | Same one-line rollback. Investigate `klippy.log` after rollback; iterate on the worktree. |
| First-print quality regression. | Same. Optional: re-run `PROBE_EDDY_CURRENT_TAP_CALIBRATE TAP=verify` with a hand-adjusted `tap_threshold` before rolling back. |

No destructive operations against the Pi. `~/eddy-ng/` directory and its Klipper symlinks are untouched.

## 9. Out of scope (intentional)

- **Webcam re-enable** — separate spec, depends on this one succeeding.
- **EBB USB → CAN migration** — separate spec.
- **`~/eddy-ng/` uninstall and Klipper symlink cleanup** — separate "cleanup" spec scheduled "after stability."
- **Re-running PID / input shaper / pressure advance / flow calibration** — separate spec ("stale tuning" sweep).
- **CI / config-validation scaffold** — separate spec (queued).
- **Sensorless X investigation** — separate, deferred.
- **Replacing the `BTT_BED_MESH_CALIBRATE ADAPTIVE=1` override** — preserved as-is; only the `METHOD=` token is verified against native semantics.
- **`[temperature_probe]` drift compensation** — explicitly **declined** by user; eddy-ng's "tap at every print start" philosophy is preferred.

## 10. Verify-on-implementation

Items to resolve during plan execution against the vendored sources, not blocking spec approval:

- `G28 Z METHOD=tap` vs. `PROBE METHOD=tap` + `SET_KINEMATIC_POSITION` (§4, §5.2). Cross-check `vendor/klipper/klippy/extras/probe.py` and `Eddy_Probe.md:197-209`.
- Whether `[ldc1612 btt_eddy]` is a required separate section in our pinned Klipper commit, or whether `[probe_eddy_current btt_eddy]` accepts the sensor params inline. Resolved by reading `vendor/klipper/klippy/extras/ldc1612.py` and `Config_Reference.md`.
- The correct value for `intb_pin` on the BTT Eddy board — find in `vendor/btt-docs/docs/Eddy.md` or community configs.
- Reference a working Voron 2.4 + BTT Eddy + native `[probe_eddy_current]` community config on GitHub; cite the repo and commit in the plan and the eventual commit message. (Per user 2026-05-13: scan popular community repos for working examples before writing from docs alone.)

## 11. References

- `vendor/klipper/docs/Eddy_Probe.md` — native module documentation (authoritative for our pinned commit).
- `vendor/klipper/klippy/extras/probe_eddy_current.py` — native module source.
- `vendor/klipper/klippy/extras/ldc1612.py` — sensor chip module.
- `vendor/klipper/docs/Bed_Level.md` — "the paper test" procedure for §6 step 2.
- `vendor/eddy-ng/probe_eddy_ng.py` + `vendor/eddy-ng/README.md` — current behavior we're replacing.
- `vendor/btt-docs/docs/Eddy.md` — BTT Eddy hardware reference.
- `CLAUDE.md` §Open investigations item 1 — original migration brief.
- `memory/decisions.md` — calibration carry-over decisions and tap-philosophy rationale.
- `memory/v24-saggy-rear-qgl.md` — why the two-pass QGL is preserved byte-for-byte.

---

*Next step after user review: invoke `superpowers:writing-plans` to produce the implementation plan.*
