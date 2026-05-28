# Tuning log

Running record of calibration runs (input shaper, PID, pressure advance, flow, Eddy, bed mesh, etc.). Newest at the top. Each entry: date, what was tuned, the resulting value, the command run, and any notes.

---

## 2026-05-28 — MMU selector stealthChop (#120)

PR [#120](https://github.com/bjdeng/voron-2-611/pull/120). `stepper_mmu_selector` `stealthchop_threshold` 0 → 250 in `config/mmu/base/mmu_hardware.cfg`. Goal: quieter selector gate-change moves at zero torque cost (selector carries no filament load, homes on the physical `mmu_sel_home` microswitch). Gear left in spreadCycle. Spec + plan: `docs/superpowers/{specs,plans}/2026-05-28-mmu-*`.

**Driver state confirmed** (`DUMP_TMC STEPPER=stepper_mmu_selector`): `TPWMTHRS=38` (computed from the 250 mm/s threshold; was 0/disabled), `GCONF` `en_spreadcycle` clear, `DRV_STATUS stealth=1`. No `otpw`.

**Reliability — PASS.** 24 full gate-change moves (`MMU_SELECT` sweep across all 6 gates ×4) + 2 bracketing `MMU_HOME` at the configured `selector_move_speed: 200` / `selector_max_accel: 1200`. 0 non-ok responses, 0 missed steps, no selector-recovery / "did not home" / out-of-range lines in klippy.log. Final `is_homed=True`.

**Acoustic — modest.** Real-time A/B via `SET_TMC_FIELD STEPPER=stepper_mmu_selector FIELD=en_spreadcycle VALUE=1` (spreadCycle/old) vs `VALUE=0` (stealthChop/new), same 6-gate sweep back-to-back. Ben's verdict: little audible difference on the 200 mm/s gate traverses; **only the slow homing move (`selector_homing_speed: 60`, ~90 RPM) was noticeably quieter.** Consistent with stealthChop helping most at low speed/load. Kept — small, free, zero-risk win.

**Takeaway for Phase 2:** the selector traverse is a *minor* MMU noise source. Load/unload noise is dominated by the gear (filament through the bowden at ~1000 RPM) and the servo — neither touched here. Gear autotune (Phase 2, deferred pending motor ID) and the servo are the higher-impact levers if more quieting is wanted.

**Restart class:** RESTART (TMC UART register, not FIRMWARE_RESTART). The deploy used `firmware_restart` anyway via `deploy_to_pi.sh`'s conservative heuristic (`mmu/` is outside the soft-restart allowlist); the MCU watchdog recovered cleanly and Klipper was `ready` in ~7s.

---

## 2026-05-20 — CRT chopper tuning, all 6 mainboard steppers (#98 Session 1)

PR [#99](https://github.com/bjdeng/voron-2-611/pull/99) + [#100](https://github.com/bjdeng/voron-2-611/pull/100). First successful empirical TMC2209 chopper tune via MRX8024/chopper-resonance-tuner. LIS2DW toolhead-mounted. All 6 mainboard steppers (X, Y, Z, Z1, Z2, Z3) on motor `omc-17hs19-2004s1` (17HS19-2004S1 hardware).

**Final register values (applied via `[delayed_gcode _apply_crt_chopper]` 1s after autotune):**

| Register | Pre (autotune) X/Y | Pre (autotune) Z | Post (CRT) all 6 |
|---|---|---|---|
| TBL  | 1 | 1 | 1 (unchanged) |
| TOFF | 1 | 1 | **4** |
| HSTRT | 6 | 7 | **7** (X/Y bumped; Z already matched) |
| HEND | 3 | 3 | **5** |

**CRT methodology:**
- `CHOPPER_TUNE FIND_VIBRATIONS=1 AXIS=x`: peak at 40 mm/s (mag 5168), secondary peak at 79-80 mm/s (mag 3100)
- `CHOPPER_TUNE FIND_VIBRATIONS=1 AXIS=z`: peak at 6 mm/s (mag 1282, right in probe-approach range)
- Register sweeps at the 3 peak speeds with bounded ranges (TBL 1-2, TOFF 1-4, HSTRT 4-7, HEND 2-5). 384 combinations total tested.
- (1,4,7,5) wins or ties at all three peaks. Combined sum-of-magnitudes ranking puts it #1 across X 40 + 79 mm/s peaks. At Z 6 mm/s, it ranks #3 of 128, within 1% of absolute Z optimum (2,4,4,3 at mag 909.9).

**Audible validation (custom multi-speed test, 5 back-and-forths per speed):**

| Direction | 40 | 80 | 120 | 160 | 200 mm/s |
|---|---|---|---|---|---|
| X-only | base | base | **quiet** | **quiet** | **quiet** |
| Y-only | base | **quiet** | **quiet** | **quiet** | **quiet** |
| Diagonal X+Y | **quiet** | **quiet** | **quiet** | **quiet** | **quiet** |
| Z-only (15-100 mm/s) | base across all 5 speeds (CRT predicted ~3% improvement, below audible threshold) |

13/15 X/Y/diagonal speeds audibly improved. Diagonal motion (most relevant for real prints) improved at every tested speed. 0 missed steps. No abnormal sounds.

**Coexistence with autotune (Path B from CRT plan §S1-9):** `[autotune_tmc]` blocks retained for all 6 steppers. Autotune still writes its values at handle_connect (CoolStep, PWM, IHOLDDELAY, multistep_filt, en_spreadcycle). A `[delayed_gcode _apply_crt_chopper]` with `initial_duration: 1.0` fires after autotune and overrides only the chopper fields (TOFF, HEND on all 6; HSTRT only on X/Y).

**Tool install notes:**
- MRX8024/chopper-resonance-tuner is Pi-only at `~/chopper-resonance-tuner/` (no vendor submodule, matches shaketune pattern).
- `chopper_tune.cfg` is a Pi-side symlink; auto-excluded from rsync deploy.
- Install.sh quirks: has an interactive y/n prompt (broke our automated install); also drops a redundant `[respond]` declaration on printer.cfg line 1 (mainsail.cfg already declares it). Need to also run `apt + venv + pip install` after the y/n prompt.

**Reference:** spec `docs/superpowers/specs/2026-05-20-chopper-resonance-tuner-design.md`, plan `docs/superpowers/plans/2026-05-20-chopper-resonance-tuner.md`.

---

## 2026-05-20 — microsteps 128 → 64 on X/Y/Z mainboard steppers (Phase A of #24)

PR [#95](https://github.com/bjdeng/voron-2-611/pull/95). Halved microsteps on `[stepper_x]`, `[stepper_y]`, `[stepper_z]`, `[stepper_z1]`, `[stepper_z2]`, `[stepper_z3]` from 128 to 64 to recover MCU USB step-rate headroom (LPC1769 was at ~92% of budget at max_velocity). `interpolate: False` retained on all 6 TMC2209s.

**Test plan results (2 × TEST_SPEED before, 2 × TEST_SPEED after):**

| Metric | Baseline (128) | Post-change (64) | Status |
|---|---|---|---|
| Subjective noise rating | 3/5 (moderate) | 3.5/5 ("maybe more vibration noise", no abnormal sounds) | ❌ slight regression |
| X/Y position drift | 0 mm (identical mcu count before/after, both runs) | 0 mm (same) | ✅ |
| Z probe diff at (175,175) | 0.008 mm run 1, 0.019 mm run 2 | 0.018 mm run 1, 0.007 mm run 2 | ✅ (sensor noise band) |
| `step_compress` count in klippy.log | 0 | 0 | ✅ |

Klipper docs ([TMC_Drivers.md:106-109](https://github.com/Klipper3d/klipper/blob/master/docs/TMC_Drivers.md)) predicted 64 = 128 acoustically with `interpolate: False`. Empirical result on this machine: 64 is *slightly louder*, not equal. Phase A retained despite the subjective regression because (a) position checks passed cleanly, (b) the increase was small and Ben reported no abnormal sounds, (c) Phase B (TMC Autotune) is explicitly targeting stepper noise and may compensate. Final close-out of #24 will follow Phase B.

---

## ~2020 — commissioning belt tension (historical, salvaged 2026-05-17)

Salvaged from the Voron template header in `config/printer.cfg` before that header was deleted in F1+F9 (config reorg audit). Values pre-date the repo's git history; provenance is "what was scribbled into the file when Ben commissioned the build." Almost certainly stale today — record kept for historical reference, not a current target.

- Belt tension X: 110 Hz at `X175, Y18`
- Belt tension Y: 110 Hz at `X175, Y18` (single measurement covers both A/B belts on a CoreXY)
- Belt tension Z: 140 Hz at `Z215`

If re-tensioning the belts, the [Ellis Print-Tuning-Guide belts page](https://ellis3dp.com/Print-Tuning-Guide/articles/belt_tension.html) has current target Hz ranges; don't trust these values.

---

## 2026-05-13 — initial snapshot from SAVE_CONFIG

Pulled from `config/printer.cfg` at repo-init time. Per Ben, these are likely stale and worth re-running.

- Bed PID: `Kp=44.470, Ki=1.246, Kd=396.896`
- Hotend PID: `Kp=23.507, Ki=1.059, Kd=130.460`
- Input shaper X: `mzv @ 51.4 Hz`
- Input shaper Y: `zv @ 37.4 Hz`
- Pressure advance: `0.05` (smooth time 0.040)
- Eddy NG: calibrated drive currents 15 & 16; calibration_version 5; `reg_drive_current: 15`, `tap_drive_current: 15`
- Bed mesh `default`: 9×9 over (15, 21.42) → (335, 335)
- Bed mesh `Default2`: 5×5 over (30, 30) → (320, 320)
