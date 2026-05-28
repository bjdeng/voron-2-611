# Decisions

Why things are the way they are. Use this to capture context that won't be obvious from `git blame` six months from now — design decisions, tradeoffs deliberately chosen, third-party tools deliberately picked or rejected. Newest at the top.

---

## 2026-05-28 — MMU servo noise is hardware-bound (no software fix)

Investigated as a follow-on to the MMU stepper quieting work (spec `docs/superpowers/specs/2026-05-28-mmu-stepper-quieting-design.md`). Ben reported the MMU servo is loud.

**Finding: the loud part is the SAVOX SH0255MG's own slew, not anything software-tunable.** Live A/B on 2026-05-28: 3 servo engagements with the gear buzz (`servo_buzz_gear_on_down: 1`) vs 3 with it disabled (`MMU_TEST_CONFIG SERVO_BUZZ_GEAR_ON_DOWN=0`). Ben's verdict: **identical volume**; the no-buzz set was only *faster* (skips the gear jiggle + dwell), not quieter.

**Software levers ruled out:** `servo_buzz_gear_on_down` (gear ±0.8 mm jiggle on engagement — aids tooth bite), `servo_duration`/`servo_dwell` (PWM burst/settle timing). None touch the slew sound. Klipper just commands a target angle; HH drives the servo from Python (`mmu_selector.py` `servo_up/down/move` call `servo.set_position` directly), so there's no clean way to ramp the angle gently — and a fast digital servo would snap between ramp steps anyway. **Real lever = a quieter servo (hardware swap).**

**Do NOT set `servo_buzz_gear_on_down: 0` for the speed gain.** The A/B ran with filament *unloaded*, so the buzz's actual job (helping the gear teeth grab the filament) wasn't exercised. Disabling it trades engagement reliability for ~0.5 s/toolchange — off Ben's "minimal risk" line and not where load/unload time is actually spent.

**How to apply:** if MMU servo noise comes up again, it's a hardware question (quieter servo), not config. The remaining *software* MMU-quieting lever is the gear (Phase 2 autotune, deferred — see the spec). Note: a future Bondtech INDX retrofit (long-term plan) would replace this servo/selector mechanism entirely, so don't over-invest in servo hardware.

## 2026-05-16 — Phase 2 refactor (Mainsail/HH cleanup)

### Mainsail config slim — defer PAUSE/RESUME/CANCEL_PRINT to upstream
`config/mainsail.cfg` was previously a verbatim copy of upstream `mainsail-crew/mainsail-config/mainsail.cfg` (313 lines). The Pi symlinks `~/printer_data/config/mainsail.cfg` → `~/mainsail-config/mainsail.cfg` (NOT `client.cfg`; the upstream repo ships both files as identical copies, but the symlink target is `mainsail.cfg`). The upstream definitions of `PAUSE`, `RESUME`, `CANCEL_PRINT`, `SET_PAUSE_NEXT_LAYER`, `SET_PAUSE_AT_LAYER`, and `SET_PRINT_STATS_INFO` are what actually run.

**Slimmed the repo copy to declarations + helpers only:** kept `[virtual_sdcard]`, `[pause_resume]`, `[display_status]`, `[respond]`, `_TOOLHEAD_PARK_PAUSE_CANCEL`, `_CLIENT_EXTRUDE`, `_CLIENT_RETRACT`, `_CLIENT_LINEAR_MOVE`. Stripped the 6 macros we delegate to upstream.

**Deploy behavior unchanged.** `scripts/deploy_to_pi.sh::discover_pi_symlinks()` rsync-excludes any Pi-side symlink, so our local copy never overwrites the Pi's symlink → upstream. The slim is purely a documentation + macro_refcheck win.

**Activation steps IF you ever want to override upstream (e.g. add custom PAUSE behavior):**
1. Wait for any in-flight deploy to finish (`discover_pi_symlinks` runs live; mid-swap state would confuse it).
2. SSH into the Pi: `rm ~/printer_data/config/mainsail.cfg && cp <repo>/config/mainsail.cfg ~/printer_data/config/mainsail.cfg`
3. The next deploy sees a real file, syncs our local copy normally (no `--exclude=/mainsail.cfg`).
4. Update `CLAUDE.md`'s Known quirks entry on the mainsail.cfg symlink to note it's been broken.
5. **Coupling note:** the slim depends on the upstream macro names (`_TOOLHEAD_PARK_PAUSE_CANCEL`, `_CLIENT_EXTRUDE/RETRACT/LINEAR_MOVE`) staying stable. `[update_manager mainsail-config]` in `moonraker.conf` keeps pulling upstream changes into `~/mainsail-config/` on the Pi. If upstream ever renames those helpers, our PRINT_START/PAUSE chain breaks at next mainsail-config update. Worth a vendor-bump audit before approving an upstream pin update.
6. Once the symlink is broken, future mainsail-config updates pulled by Moonraker no longer auto-apply — you'd manually merge upstream changes into our local file.

### Defer Spoolman activation to Happy Hare
Deleted `SET_ACTIVE_SPOOL` and `CLEAR_ACTIVE_SPOOL` from `config/macros/macros.cfg`. Both called `spoolman_set_active_spool` via Moonraker's remote-method API — but Happy Hare already does this automatically via its `spoolman_support: push` config (see `config/mmu/base/mmu.cfg` and `vendor/happy-hare/.../mmu.py`). Every tool change publishes the active spool to Spoolman without needing a Klipper macro.

The custom macros were dead code: nothing in our config tree called them. Removing them follows the [Defer to Happy Hare](../.claude/projects/-Users-ben-code-voron-2-611/memory/defer-to-happy-hare.md) rule.

### Dead-commented-code sweep in print_start.cfg
Removed ~30 lines of commented-out alternative paths from PRINT_START/PRINT_END/PRINT_WARMUP: an unused `HEATSOAK` branch, an unused prime-line block, redundant `BED_MESH_CLEAR`/`SET_PIN`/`M140` lines (already done in `PRINT_WARMUP`), and a few `# G1 ... # ; park nozzle at rear`-style dangling alternatives.

These weren't load-bearing — `PRINT_WARMUP` and `PRINT_START` already do the right work via the uncommented paths. The git history retains the alternatives if anyone wants to resurrect them.

---

## 2026-05-16 — Defer status sections to Happy Hare

`[respond]`, `[exclude_object]`, `[pause_resume]`, `[display_status]` now have a
single declaration in HH-owned files (`config/mmu/base/mmu_macro_vars.cfg`
and `config/mmu/addons/blobifier.cfg`) — our copies in `config/printer.cfg`
and `config/mainsail.cfg` are removed.

**Why:** Defer-to-HH rule from `memory/defer-to-happy-hare.md`. Reduces
duplicate-declaration noise; matches one-canonical-home discipline.

**How to apply:** If HH is ever disabled (`mmu/base/*.cfg` includes commented
out), Klipper load breaks until these declarations are restored in
`config/printer.cfg` / `config/mainsail.cfg`. Acceptable trade because HH is
structurally load-bearing on this build.

See `docs/superpowers/specs/2026-05-16-phase4-macros-refactor-design.md` for design rationale.

---

## 2026-05-13 — repo initialized

### Chose USB over CAN for toolhead
The EBB SB v1.0 supports both USB and CAN modes. Currently USB (`config/toolhead.cfg`); no `can0` interface on the Pi. **Reason (per Ben, 2026-05-13):** when he got the EBB, USB was the only mode that supported rapid bed scanning, temperature-offset-2 calibration, and touch sensing on the BTT Eddy. CAN support for those features lagged. This couples the USB choice to the [eddy-ng → native] migration: re-evaluate USB-vs-CAN once Eddy is on native Klipper.

### eddy-ng (vvuk/eddy-ng) chosen over native [probe_eddy_current]
At install time, native Klipper Eddy didn't support tap or had limited scanning features. As of Klipper `4767a8ed` (2026-05-04, the version on the Pi), the native module **covers every feature eddy-ng provides and adds one eddy-ng deliberately omits** (per investigation 2026-05-13):

- **Rapid scanning:** native `[probe_eddy_current]` has both `scan` and `rapid_scan` methods (`vendor/klipper/klippy/extras/probe_eddy_current.py:936-996`, `EddyScanningProbe._rapid_lookahead_cb`).
- **Tap sensing:** native implements `EddyTap` class (lines 650-933) with `PROBE_EDDY_CURRENT_TAP_CALIBRATE` (lines 332-439). Equivalent to eddy-ng's `PROBE_EDDY_NG_TAP`.
- **Temperature compensation:** native has `[temperature_probe]` (`vendor/klipper/klippy/extras/temperature_probe.py`, 721 lines) with `TEMPERATURE_PROBE_CALIBRATE`. **Eddy-ng explicitly omits this** (its README calls temp comp "guesswork at best" and instead recommends taking a tap at print-temp before every print).
- **USB-vs-CAN does not affect Eddy.** The original reason for choosing USB on the EBB was timeline-dependent (CAN support for these Eddy features lagged when Ben built the machine). The probe itself talks I²C to the EBB MCU regardless; CAN-vs-USB is purely about the EBB↔Pi link.

**Recommendation:** migrate to native `[probe_eddy_current]`. The choice between native's `[temperature_probe]` workflow and eddy-ng's "tap at print temp" workflow is a philosophy question; native is more automated, eddy-ng is more deterministic. Both produce comparable results. Picking native also frees us from re-running `~/eddy-ng/install.sh` after every Klipper update. **This unblocks investigation of the webcam re-enable** (the unplug was tied to suspected eddy-ng polling timing).

### Sensorless X — feasible but low ROI on this build
Investigation 2026-05-13. TMC2209 supports stallguard via DIAG; Klipper's sensorless-homing path is well-trodden (`vendor/klipper/docs/TMC_Drivers.md:117-260`, `Sensorless_Homing.md`). For Voron 2.4 r2 + dual SKR 1.4 + TMC2209 + Stealthburner v2: technically viable.

- **DIAG pin is not pre-wired on the SKR 1.4** — needs a jumper/wire from the X TMC2209 DIAG pad to an available MCU GPIO. No board-level mod, just a wire.
- "Harmful" concern is largely mythical with proper tuning. Real risks: StallGuard sensitivity to current/speed/temperature requires careful `driver_SGTHRS` tuning; the standard ≥2-second pause before homing is mandatory (clears the stall flag).
- Minimum diff: route DIAG → MCU pin, add `diag_pin: ^P1.0` (or wherever it's wired) + `driver_SGTHRS: <tuned>` to `[tmc2209 stepper_x]`, change `endstop_pin` to `tmc2209_stepper_x:virtual_endstop`, add a `SENSORLESS_HOME_X` macro.
- Practical assessment: physical X endstop currently works fine. The only material benefit is removing the EBB→X-endstop dependency (eliminates a toolhead-USB-state failure mode for homing). Net effort vs net benefit: low priority.

**Recommendation:** defer unless we're already touching toolhead wiring (e.g., during the eddy-ng → native migration or a CAN exploration). Not urgent.

### Missing `[update_manager klipper]` in config/moonraker.conf — by design
Investigation 2026-05-13. Ben's hypothesis was correct. Moonraker's docs (`vendor/moonraker/docs/configuration.md:2017-2026`) state:

> "Configuration is automatically detected for Moonraker and Klipper, however it is possible to override the `channel`, `pinned_commit`, and `refresh_interval` options on a per application basis for each."

Both Klipper and Moonraker are **auto-detected** by the update_manager. An explicit `[update_manager klipper]` block is only needed when overriding the channel (`stable`/`beta`/`dev`), pinning to a specific commit, or changing refresh interval. Klipper's update behavior on this Pi is whatever Moonraker's default is (dev channel, default refresh window) — not a config omission.

**How to apply:** treat the absence of `[update_manager klipper]` as normal. Add the block only if we deliberately want to pin or change update behavior (e.g., pinning to a known-good commit while the eddy-ng / Happy-Hare overlays are still in place).

### Stealthburner v2 + Galileo over v1 + CW2
Standard mod path. Galileo's 9:1 gear ratio explains the unusual `gear_ratio: 9:1` + `rotation_distance: 48.033` in `config/toolhead.cfg`.

### Self-printed ERCF v2 over commercial MMU (e.g. BoxTurtle, Tradrack, AMS)
Reason: Ben chose to print and build it himself. No buffer (Filamentalist rewinders instead).

### microsteps 128 on X/Y/Z
**Followed advice rather than firmly chosen.** Per Ben (2026-05-13): *"I'm just going by what some guy wrote online. I want the printer quiet but don't want to skip steps."* The values came from third-party advice, not from a deliberate analysis of this hardware. **Worth exploring.** Klipper has improved its handling of step rates over the years; the real goal is "quiet without losing steps." The right value for this printer's TMC2209 + LPC1769 step rate budget could be lower (16/32/64) or the same — needs measurement. See [Open investigations] #3.

### Dual SKR 1.4 mainboards (USB)
**Original Voron 2.4 r2 reference spec** — not a discretionary choice. Don't propose consolidation to a single board / CAN bus without explicit reason.

### `klipper_mcu.service` running with no [mcu host] block
Artifact from an old CAN bus Klipper mod Ben no longer uses (per Ben, 2026-05-13). Safe to disable.

### Macro lineage: Andrew Ellis v2.247_backup_klipper_config
The macro set (Ellis-style `OFF`, `PARK*`, `HEATSOAK`, M109/M190 overrides) traces back to Andrew Ellis's V2.4 profile. Modifications since are minor.
