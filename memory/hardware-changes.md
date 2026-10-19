# Hardware changes

Chronological record of physical changes to the printer: mods installed, parts swapped, wiring rerouted, MCUs reflashed. Newest at the top. Include the date, what changed, and any config implications.

---

## 2026-10-18 — ERCF selector servo arm replaced; servo pulse range reset to HH default; angles re-calibrated

- **Symptom:** gate loads failing with "Couldn't pick up filament at gate (encoder didn't report enough movement)"; looked like an encoder problem.
- **Root cause:** the worn servo arm no longer reached the recess (detent) that locks it in the down position. Happy Hare drops the servo PWM after positioning (`servo_active_down: 0`), so the lever relaxed and the gear slipped: `MMU_TEST_MOVE MOVE=50` measured **8.7 mm**. With `servo_active_down=1` (runtime test) it measured 50.4 — proving encoder, gear calibration and selector were fine. Replaced the arm with a spare.
- **Servo pulse range:** `maximum_pulse_width` 0.00215 (written by the HH v3 installer years ago, never deliberately set) → **0.00240, the HH v4 default for the SAVOX SH0255MG**. One "degree" is a different physical rotation between the two ranges, so angles were converted by pulse width (µs) to keep physical positions.
- **Final angles (0.00240 range): down 65 · move 118 · up 130** — in `config/mmu/.mmu_config`, no `mmu_vars.cfg` overrides.
  - **Down 65:** verified to grip fully after a restart with 65 in config (`MMU_TEST_MOVE` 50 → 49.5 / 50.4 mm, servo unpowered). ⚠️ An earlier "down sweep 63–67 all 100%" was **invalid** — it set angles with `MMU_TEST_CONFIG servo_down_angle=…`, which never changes the live servo angle table (built once at startup), so every run was really 63; the "0%" readings at 60–62/68 were the test filament having been removed. The real grip window was not measured.
  - **Up 130:** filament releases at ~112–113 (filament traps removed, so drag barely changes); 130 keeps clean gear meshing/release with ~17° margin and 8° less lift than the first eyeballed 138. Spread up−down = 65°, close to HH's ERCF v2 Thumper-blocks preset (70°; standard preset 110°).
  - **Move 118:** back-to-back listening runs (home + gate 0→5→0) at 130/126/122/118/114 — 130 loudest, 126 rubbing, 118 and 114 quietest; below ~112 the arm drags filament. 118 = quiet with ~5° above the drag point.
- **Soak 2026-10-19 (bowden reconnected, spools loaded on gates 0/1/3/4/5; gate 2 empty):** every gate picks up and re-parks cleanly. Moves away from park measure 50.4/49.5 of 50 mm with the servo unpowered; holding it powered (`servo_active_down=1`) and slowing to 20 mm/s changed nothing → no slip at down 65. The apparent ~78 % in +100/−100 shuttles was the park offset (see CLAUDE.md Klipper gotchas), not grip.
- **`servo_down` wear counter reset to 0** for the new arm (`MMU_STATS COUNTER=servo_down RESET=1`; only that counter). Note the saved counter shows `limit: -1`, so the configured 5000-cycle wear warning isn't attached — not yet investigated.

## 2026-10-18 — Toolhead XT30 USB cable replaced; Pi reflashed to MainsailOS 3.0.0

- **XT30 2+2 USB/power cable to the EBB replaced with an unspliced one.** The old cable had been hand-spliced at the 2026-06 board swap and was the prime suspect for the recurring `usb 1-1.4 … error -71` toolhead hub drops (see `memory/troubleshooting-log.md`). Fully seated at both ends. Soak test (Klipper `ready`, idle) started 2026-10-18 ~11:52 MDT; old-cable baseline was a drop every 25–45 min.
- **Pi SD card reflashed** from MainsailOS 1.0.0 / bullseye (EOL) to **MainsailOS 3.0.0 / Debian 13 trixie** (kernel 6.18, Python 3.13). Same card; a full image of the old one is kept off-Pi. Rebuild procedure + OS tweaks: `docs/pi-environment.md`. MCU firmware unchanged (no reflash needed for Klipper v0.13.0-800).
- **Printer was laid on its side** for the cable work; no mechanical changes beyond the cable.

## 2026-06-04 — EBB toolhead board replaced (RP2040 USB serial changed)

The EBB SB v1.0 toolhead board was swapped for a new one after the original's RP2040 began coming up in **BOOTSEL/DFU mode on every boot** (kernel saw it as "RP2 Boot", VID 2e8a / PID 0003, on hub 1-1.4) instead of running Klipper. Suspected root cause: a cable physically pressing the BOOTSEL/DFU button after the 2026-06-03 hotend cartridge swap — it stayed invisible until the board's first reboot (a `firmware_restart` during the #126 deploy), which surfaced it. Replaced rather than debugged in place.

- New board flashed with the EBB Klipper firmware (`config/firmware/ebb-usb.config` → `~/klipper`, `make`, UF2 copied to the `RPI-RP2` boot drive at `/dev/sda1`). Build: Klipper v0.13.0-688-gb7c0329f, rp2040 USB.
- **USB serial changed** `5044340310C4D61C` → `5044505938479E1C` (RP2040 serial = flash-chip UID, so a new board = new serial). `config/toolhead.cfg` `[mcu EBB] serial:` updated on both the Pi and the repo.
- Toolhead **not fully re-wired** at swap time — Klipper will emergency-shutdown on the missing hotend thermistor until wiring is finished. The eddy probe (also RP2040, chains through the EBB onboard hub) is absent until the install completes.
- Deploy footgun exposed: `deploy_to_pi.sh` chose `firmware_restart` for a comment-only `client_hooks.cfg` change (a root `.cfg`), which triggered the SKR/EBB re-enumeration race that started this whole episode. Follow-up: make the restart-kind heuristic treat gcode_macro/comment-only root-`.cfg` changes as `RESTART`-eligible.

## 2026-06-03 — VEFACH carbon exhaust installed; Filametrix blade + hotend cartridge swapped

- **VEFACH carbon exhaust housing** ([VoronUsers/KevinAkaSam/VEFACH](https://github.com/VoronDesign/VoronUsers/tree/main/printer_mods/KevinAkaSam/VEFACH)) printed and installed on the `chamber_exhaust` fan (`z:P2.7`), routed **exhaust-to-room** through carbon. Decouples VOC evacuation from chamber heating — the exhaust can now own end-of-print cooldown independently of the BedFans. Config: see spec `docs/superpowers/specs/2026-06-03-vefach-exhaust-cooldown-decouple.md` (closes #117). RESTART-class macro change, not yet deployed at time of this note.
- **Filametrix cutting blade replaced** (alongside the hotend cartridge swap below). Fresh blade → expect cleaner tip cuts. No config change required, but if MMU tip-cut quality changes (incomplete cuts, blade drag), the new blade is a variable — verify with a `_MMU_CUT_TIP` test cut; re-check cutter geometry via `MMU_CALIBRATE_TOOLHEAD CUT=1` only if cuts are actually failing. Cut settings live in `config/mmu/base/mmu_parameters.cfg` (real file on Pi — see CLAUDE.md).
- **Hotend heater cartridge replaced.** If the wattage is unchanged (40W → 40W) no config change is needed, but a fresh cartridge can shift the hotend thermal response slightly — re-run `PID_CALIBRATE HEATER=extruder` and SAVE_CONFIG if you see temperature hunting on the first prints. If this was the 40W → 50W upgrade tracked in #125, that needs its own change (max_power review + PID re-cal) — confirm which it was.

## 2026-05-13 — repo initialized

Snapshot of state at the time of repo creation (not a change, just a baseline):

- Frame: Voron 2.4 r2 350 mm, self-sourced original BOM, ~2020 commissioning
- Motion: MGN12 X carriage (upgraded from stock MGN9), beefy idlers mod
- Toolhead: Stealthburner v2 + Galileo extruder + Dragon-clone hotend, LIS2DW accel
- Bed: textured PEI magnetic flex plate, SSR-controlled silicone heater
- Probe: BTT Eddy (running vvuk/eddy-ng — migration to native Klipper Eddy pending)
- Display: fysetc Mini12864
- Bed cooling/filtration: Ellis BedFans with charcoal filter mod (https://www.printables.com/model/334276-the-filter-for-voron-24)
- MMU: self-printed ERCF v2, 6 gates, EASY-BRD MCU, Blobifier + EREC + eject buttons, Filamentalist rewinders (no buffer)
- Webcam: physically unplugged (timing issues)
