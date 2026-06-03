# Hardware changes

Chronological record of physical changes to the printer: mods installed, parts swapped, wiring rerouted, MCUs reflashed. Newest at the top. Include the date, what changed, and any config implications.

---

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
