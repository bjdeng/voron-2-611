# Hardware changes

Chronological record of physical changes to the printer: mods installed, parts swapped, wiring rerouted, MCUs reflashed. Newest at the top. Include the date, what changed, and any config implications.

---

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
