# Eddy migration prep notes (Task 2 research)

Resolutions to the spec's §10 "Verify-on-implementation" questions, from grepping the vendored Klipper sources and cross-checking with the official BTT sample config.

## Q1. `G28 Z METHOD=tap` vs. `PROBE METHOD=tap` + `SET_KINEMATIC_POSITION`

**Answer: `G28 Z METHOD=tap` does NOT exist in native Klipper.** Grepping `vendor/klipper/` returns zero matches. The native module supports `METHOD` only on the `PROBE` command (and related `PROBE_*` calls in `probe_eddy_current.py`).

The documented pattern (from `vendor/klipper/docs/Eddy_Probe.md:180-209`):

> A "tap" probe is often used as one step during a multi-step homing/leveling process … one might deploy a macro that homes, calls `Z_TILT_ADJUST` with default probe method, heats the printer to an intermediate temperature, cleans the nozzle, performs a "tap" probe, uses `SET_KINEMATIC_POSITION` with the tap results, runs `BED_MESH_CALIBRATE` while utilizing a `zero_reference_position`, and then brings the printer to normal printing temperature.

The PRINT_START replacement is therefore three commands, not one:

```
G28 Z                                                  ; standard Z home via safe_z_home + probe descent
PROBE METHOD=tap                                       ; tap for high-precision Z reference at print temp
SET_KINEMATIC_POSITION Z={printer.probe.last_z_result} ; apply tap result
BED_MESH_CALIBRATE ADAPTIVE=1
```

The plan's "two-line surgical change" to `config/macros/print_start.cfg` becomes a **three-line replacement** of the original `PROBE_EDDY_NG_TAP` line. The `PROBE_EDDY_NG_SET_TAP_OFFSET VALUE=0` deletion in PRINT_END is unchanged.

## Q2. `[ldc1612 btt_eddy]` separate section or inline in `[probe_eddy_current btt_eddy]`?

**Answer: INLINE in `[probe_eddy_current]`.** No separate `[ldc1612]` section.

Per `vendor/klipper/docs/Config_Reference.md:2316-2365`, the native module takes `sensor_type: ldc1612` plus all sensor params (`intb_pin`, `i2c_mcu`, `i2c_bus`, etc.) inline. There's no standalone `[ldc1612]` section.

The plan's proposed structure with two separate blocks is **wrong** — it would fail at config-parse. Drop the separate block; put everything in `[probe_eddy_current btt_eddy]`.

## Q3. `intb_pin` for BTT Eddy

**Answer: OMIT it.** It's optional ("The default is to not use the INTB pin") and the BTT sample config (Q4) doesn't set it. The driver falls back to polling, which is fine for our usage pattern.

If we ever want interrupt-driven sensing for lower CPU load, the BTT Eddy's INTB is on `eddy:gpio25` per BTT wiring docs. Not needed now.

## Carry-over from eddy-ng SAVE_CONFIG

The stale `#*# [probe_eddy_ng btt_eddy]` block in `printer.cfg` had these saved values:

| eddy-ng saved | Native equivalent | Carry-over? |
|---|---|---|
| `reg_drive_current = 15` | `reg_drive_current` (same param in `[probe_eddy_current]`) | Yes. Pre-populated in eddy.cfg. Skips `LDC_CALIBRATE_DRIVE_CURRENT` in Task 8 unless probing behavior is abnormal. |
| `tap_drive_current = 15` | — | Concept gone. Native uses a single `reg_drive_current` for all modes. |
| `tap_mode: butter` + `tap_samples_stddev: 0.3` | `tap_threshold` (Hz/mm) | Different concept — eddy-ng's was a statistical butter-filter approach; native uses a frequency-derivative threshold. Must run `PROBE_EDDY_CURRENT_TAP_CALIBRATE`. |
| `calibration_15`, `calibration_16` (base64 numpy polys) | Native's internal freq→Z fit | Different binary format. Must run `PROBE_EDDY_CURRENT_CALIBRATE_AUTO`. |
| `calibration_version = 5` | — | eddy-ng internal versioning, irrelevant to native. |

Net: of the 3 expected calibration commands in Task 8, the drive-current step is now optional (only re-run if probing is flaky). The freq-mapping and tap-threshold calibrations still need to run hands-on at the printer.

## Q4. Working community reference

**Canonical BTT sample:** [`bigtreetech/Eddy` → `sample-bigtreetech-eddy.cfg`](https://github.com/bigtreetech/Eddy/blob/master/sample-bigtreetech-eddy.cfg). **Caveat: it's 17 months stale (last touched 2024-09-10, commit `e57fbf2`) vs our pinned Klipper (2026-05-04, commit `4767a8ed`).** Treat it as a *starting structure*, not as authoritative on parameter names. Specifically:

- BTT uses `z_offset: 2.5` — **deprecated** in current Klipper (`vendor/klipper/klippy/extras/probe_eddy_current.py:570` explicitly calls `config.deprecate('z_offset')`). Current API: `descend_z` (which our config uses).
- BTT predates `PROBE_EDDY_CURRENT_TAP_CALIBRATE` (added commit `ef7b13b1f`) — the calibration workflow described in BTT's docs is incomplete.
- BTT predates ~20 commits of tap algorithm improvements and the new `tap_z_offset` config parameter (commit `6c8c8d24d`).

The authoritative reference is `vendor/klipper/docs/Eddy_Probe.md` + `vendor/klipper/docs/Config_Reference.md` at our pinned commit, NOT the BTT sample.

The `[probe_eddy_current btt_eddy]` block we want to land is essentially this sample, with our specific `x_offset: 0`, `y_offset: 21.42` (which already match the sample by coincidence — both for the standard Voron X-carriage mount):

```ini
[probe_eddy_current btt_eddy]
sensor_type: ldc1612
i2c_mcu: eddy
i2c_bus: i2c0f
x_offset: 0
y_offset: 21.42
z_offset: <calibrated>     # to be set by PROBE_CALIBRATE during Task 8 (was z_offset baked into eddy-ng)
descend_z: 0.5             # docs recommendation (vendor/klipper/docs/Eddy_Probe.md:215)
# tap_threshold populated by PROBE_EDDY_CURRENT_TAP_CALIBRATE during calibration
```

Note: the BTT sample doesn't set `descend_z` but the official docs recommend 0.5mm. Adding it explicitly.

## Z endstop pairing

`config/printer.cfg:162` has `endstop_pin: probe:z_virtual_endstop` on `[stepper_z]`. Native `[probe_eddy_current]` exposes the same `probe:z_virtual_endstop` virtual endstop as eddy-ng did — no change needed to `[stepper_z]`. `[force_move] enable_force_move: True` and `[safe_z_home]` blocks also stay byte-for-byte.

## Summary of plan corrections discovered during research

| Spec said | Reality (per vendor + BTT sample) |
|---|---|
| Two blocks: `[ldc1612 btt_eddy]` + `[probe_eddy_current btt_eddy]` | One block: `[probe_eddy_current btt_eddy]` with `sensor_type: ldc1612` inline |
| `intb_pin: <VERIFY>` to fill in | Omit — optional, default polling is fine |
| `G28 Z METHOD=tap` (one-line surgical change) | Three lines: `G28 Z` + `PROBE METHOD=tap` + `SET_KINEMATIC_POSITION Z={...}` |
| Need to find INTB pin from btt-docs | Don't need it |

These corrections inform Tasks 3 and 4. They don't change Task 5 (SAVE_CONFIG strip) or the calibration flow in Tasks 8-10.
