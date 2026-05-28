# Troubleshooting log

Symptoms encountered, root cause when found, and the fix that worked. Newest at the top. Use this to recognize recurring failure modes before they bite again.

---

## Open

### moonraker-timelapse — never functional
- **Symptom:** Ben has never gotten timelapse to record/produce video.
- **Status:** unconfirmed root cause. Could be ffmpeg config, camera path, frame-trigger, or upstream bug.
- **Plan:** decide whether to debug or remove the `[include timelapse.cfg]` + `[update_manager timelapse]` + `[timelapse]` sections.
- **Logs to check first:** `~/printer_data/logs/moonraker.log` for `timelapse` entries.

### Webcam timing issues
- **Symptom:** webcam streaming was interfering with print timing.
- **Mitigation:** Ben unplugged the webcam. Crowsnest + Sonar services still run with nothing to serve.
- **Plan:** re-enable after `eddy-ng` → native Klipper Eddy migration (the suspicion is the eddy-ng polling loop conflicts with the webcam pipeline).

### CI klippy-smoke job is disabled
- **Symptom:** `test_klippy.py` against `config/printer.cfg` fails with `mcu 'eddy': Unknown command: ldc1612_ng_start_stop`.
- **Root cause:** the committed `tests/dict/eddy.dict` was built on the Pi without eddy-ng's `src/sensor_ldc1612_ng.c` firmware patch applied. `vendor/eddy-ng/ldc1612_ng.py` hardcodes calls to those MCU commands. The Pi's actually-running Eddy firmware is also missing them (the .c file existed but the Makefile patch didn't), so on the Pi too `[probe_eddy_ng]` couldn't be using the ng-specific commands — needs investigation alongside the migration.
- **Was hidden by:** missing `set -o pipefail` in the workflow (Codex P1, fixed in d9f53f4). Before the pipefail fix, `tee` swallowed the non-zero exit code from `test_klippy.py` and CI reported green. Multiple "green" CI runs in this session were silently failing.
- **Mitigation:** `klippy-smoke` job disabled with `if: false` in `.github/workflows/ci.yml`. Lint+refcheck job remains active and works.
- **Plan:** re-enable after the eddy migration removes `[probe_eddy_ng]` and switches to upstream `[probe_eddy_current]`, which uses vanilla `ldc1612_*` commands that ARE in eddy.dict. The eddy migration plan (docs/superpowers/plans/2026-05-13-eddy-ng-to-native-migration.md) has been cross-referenced with this requirement.

---

## Resolved

### 2026-05-28 — MMU gate-entry sensors + endless-spool grouping wiped by a deploy
- **Symptoms:** the 6 pre-gate filament sensors stopped showing/registering; endless spool stopped pairing gates. klippy.log showed `MMU: Filament sensor mmu_pre_gate_0..5 is not defined in [mmu_sensors]`.
- **Root cause:** the `[mmu_sensors]` `pre_gate_switch_pin_0..5` pins (wired to `mcu z`: `^z:P1.24/.25/.26/.29/.28` and `^z:P0.10`) were edited **only on the Pi and never committed**. Since `deploy_to_pi.sh` mirrors the repo, a deploy rsync'd the repo's stock template (`^mmu:MMU_PRE_GATE_*`, empty aliases) over them — HH silently skips sensors whose pins resolve to nothing. Separately, the live `endless_spool_groups` in `mmu_vars.cfg` had reverted to identity `[0,1,2,3,4,5]`, overriding the configured `0,0,1,1,2,2` in `mmu_parameters.cfg`.
- **Recovery — the reusable trick:** **Klipper writes the full resolved config into `klippy.log` at every startup.** Pi-only config lost to a clobber is recoverable from a pre-incident boot: `grep -a "pre_gate_switch_pin" ~/printer_data/logs/klippy.log*` surfaced the exact `^z:` pins from the last good startup. Rotated logs are `klippy.log.YYYY-MM-DD`.
- **Fix:** PR #121 — committed the z: pins to `config/mmu/base/mmu_hardware.cfg` (so deploys now preserve them), set `gate_autoload: 0` (sensors present but no auto-load-on-insert per Ben), deployed (FIRMWARE_RESTART), confirmed all 6 `mmu_pre_gate_*` registered, then `MMU_ENDLESS_SPOOL RESET=1` to re-apply the `0,0,1,1,2,2` grouping to the live state + persist it.
- **Gotchas hit:**
  - The reset command is **`MMU_ENDLESS_SPOOL RESET=1`** — `MMU_ENDLESS_SPOOL_GROUPS RESET=1` (as the `mmu_parameters.cfg:786` comment suggests) is an **Unknown command** on this HH version. Moonraker `/printer/gcode/script` returns `{"result":"ok"}` even for unknown commands, so verify the *effect* (query the `mmu` object), not the HTTP response.
  - `endless_spool_groups` keeps a **live value in `mmu_vars.cfg`** that overrides the `mmu_parameters.cfg` default at load (HH `mmu.py:1195`). Editing the cfg alone does nothing; `MMU_ENDLESS_SPOOL RESET=1` (or `GROUPS=…`) re-applies and persists it.
- **Forensics access (this Pi):** `/var/log/auth.log*` is readable **without** sudo (`pi` is in the `adm` group) — clustered `Accepted publickey for pi` bursts there are the signature of a `deploy_to_pi` run. `journalctl` / `journalctl --list-boots` need sudo; the password is in the repo's gitignored `.env` (`PI_SSH_PASSWORD`), usable as `... | ssh pi@… 'sudo -S …'`. Pi clock is **Europe/London (BST, UTC+1)** — all log timestamps are BST, not UTC.
- **Systemic fix:** the deploy drift gate failed *open* (silently clobbered Pi-only edits — it should have refused). Hardened in PR #122: fail-closed on can't-verify, auto-capture Pi-only edits to a `pi-drift-capture-<ts>` branch before any overwrite, and a Pi-side `deploy-to-pi.log`. **Lesson: any config edited only on the Pi will be clobbered by the next deploy — commit it to the repo.**

### 2026-05-17 — MMU load/unload failures (issue #15) — calibration drift
- **Symptoms:** load failure rates 3.9%–19.7% across gates. Gates 0–1 at ~5%; gates 2–5 at 14–20%. Pattern tracked a 3.6% spread in `mmu_gear_rotation_distances` (gates 0–1 clustered at ~23.7, gates 2–5 at 22.9–23.4) — too clean to be random.
- **Diagnosis:** per-gate gear RDs had drifted (or were never accurately set for gates 2–5) and HH's auto-correction was structurally inactive: `autotune_rotation_distance: 1` was set but the upstream branch is `False and …`-guarded at `mmu_calibration_manager.py:499`. Re-cal was also blocked: `skip_cal_rotation_distance: 1` was rejecting `MMU_CALIBRATE_GEAR`.
- **Fix:** PR #57 flipped both flags to 0, then ran the full HH-canonical recalibration sequence: encoder (cal'd against gate 0's caliper-measured RD as the anchor), per-gate gear RDs, bowden length. Encoder resolution corrected from 0.998752 → 0.9699 (-2.9%). Per-gate RDs converged with cal ratios all in 0.9699–0.9724 (very tight).
- **Validation soak (post-recal stats reset → fresh):**
  - Pass 1 (`MMU_SOAKTEST_LOAD_SEQUENCE LOOP=3 RANDOM=0 FULL=0`): 0 failures / 18 sequences, quality 98.4%–101.4%, slippage within ±2.3%.
  - Pass 2 (`LOOP=2 RANDOM=1 FULL=1`, full toolchange w/ cut-tip): 0 failures / 12 sequences, quality 99.2%–100.7%, slippage within ±1.7%.
  - Combined: 0 failures across 30 sequences (target was ≤2 + ≤1 = ≤3).
- **Toolhead cal sidebar:** `MMU_CALIBRATE_TOOLHEAD CLEAN=1` ran but the cold-push procedure measured ~21.9–27.7mm for `toolhead_sensor_to_nozzle` regardless of priming attempts — systematic bias unrelated to nozzle position (likely measures to the Filametrix blade rest position, or to wherever cold filament physically stops at 70°C). CAD-derived values (102.1 / 79.1 / 9.9 / 23) kept; HH's cal procedure isn't trustworthy for this toolhead geometry without proper cold-pull conditioning. Revisit only if a real print exposes a load/unload distance symptom.
- **Open follow-up:** drift cleanup PR (Task 17 of plan, deferred) — only `toolhead_residual_filament: 23` is a candidate, but the DIRTY cal gave a clearly biased 51.4mm so we kept 23 until natural print residue gives us a better measurement.

### 2026-05-13 — Moonraker missing `[update_manager klipper]` block (non-issue)
- **Concern:** Initial repo-init review flagged the absence of `[update_manager klipper]` from `config/moonraker.conf` as a potential quirk.
- **Resolution:** Verified against Moonraker docs (`vendor/moonraker/docs/configuration.md:2017-2026`). Moonraker auto-detects Klipper; the explicit block is only for overriding update channel, pinned commit, or refresh interval. Current behavior is correct.

### 2026-05-13 — CI scaffold eddy-migration acid test
- **Goal:** Verify `scripts/macro_refcheck.py`'s ALLOWLIST coupling catches an eddy migration that updates `config/eddy.cfg` without cleaning up callers of `PROBE_EDDY_NG_*`.
- **Method:** On a scratch branch, removed the eddy-ng block from `ALLOWLIST` while leaving `config/macros/print_start.cfg` untouched, ran refcheck.
- **Result: PASS** — refcheck flagged:
  - `config/macros/print_start.cfg:67: [gcode_macro PRINT_START] references unknown command 'PROBE_EDDY_NG_TAP'`
  - `config/macros/print_start.cfg:93: [gcode_macro PRINT_END] references unknown command 'PROBE_EDDY_NG_SET_TAP_OFFSET'`
- **Implication for the eddy migration:** the migration PR must update `config/eddy.cfg`, remove the eddy-ng entries from `scripts/macro_refcheck.py`'s ALLOWLIST, AND update `config/macros/print_start.cfg` — in a single PR (or atomic sequence). If any are out of sync, CI catches it.
