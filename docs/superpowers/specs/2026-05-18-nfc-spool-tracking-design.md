# NFC-driven spool tracking + per-spool runtime tuning — spec

**Owner:** Ben (multi-phase hardware + software build; spans printer wiring, MMU firmware, Klipper macros, Moonraker integration, slicer changes).

**Restart impact (per phase):**
- Phase 1 (pre-gate sensors + possible board swap): **FIRMWARE_RESTART** if a new MCU is added; **RESTART** if pins are added to existing SKR Z.
- Phase 2 (NFC reader + nfc2klipper): **RESTART** (Python service install on Pi; no Klipper config beyond moonraker.conf).
- Phase 3 (KBobine + slicer PA strip): **RESTART** (gcode_macro changes only).

**Pairs with:**
- [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](2026-05-18-print-lifecycle-redesign.md) — PRINT_START's existing `MMU_START_SETUP` flow becomes the publisher of "active spool changes" to KBobine.
- [`docs/superpowers/specs/2026-05-18-chamber-control-design.md`](2026-05-18-chamber-control-design.md) — independent; both touch Spoolman but at different layers.
- Future-work issue (file separately): chamber-VOC sensor — noted in chamber-control spec §10.

---

## 1. Goal

Eliminate slicer-side per-filament profile sprawl by making **Spoolman the authoritative source for per-spool tuning data** (pressure advance, retraction, temps), with NFC tags driving the gate↔spool mapping in Happy-Hare. End state mirrors Bambu Lab's AMS workflow on a fully open-source, multi-vendor stack.

**Non-goals:**

- Per-rewinder NFC readers. The HH community has explicitly considered and rejected this as impractical (HH wiki: *"it isn't practical to build a RFID/QR code reader into every gate"*). One shared reader at a scan station + HH's `NEXT_SPOOLID` mechanism is the supported model.
- Replacing Happy-Hare's gate-map persistence. HH's `mmu_vars.cfg` stays the in-Klipper canonical store for gate↔spool; Spoolman augments with the per-spool tuning details.
- Bambu RFID tag compatibility. Bambu tags are RSA-signed; we use OpenSpool's current JSON-on-NTAG format, migrating to OpenTag3D when it finalizes (~2025).
- Auto-measuring per-spool PA. The system applies measured values; the user still runs PA tower tests once per spool.

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Hardware events                                                     │
│  - NFC tag near reader                                               │
│  - Filament inserted into gate (triggers pre-gate sensor)            │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  nfc2klipper (Python service on Pi)                                  │
│  - Reads tag via PN532 (UART to Pi)                                  │
│  - Calls Moonraker: MMU_GATE_MAP NEXT_SPOOLID=<id>                   │
│  - Tag may contain spool_id, filament_id, OR a UID Spoolman knows    │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Happy-Hare MMU layer                                                │
│  - Stores pending spool_id (timeout: pending_spool_id_timeout = 20s) │
│  - On pre-gate sensor trigger → assigns pending_spool to that gate   │
│  - On MMU_CHANGE_TOOL → publishes active_spool_id via Moonraker      │
│  - Existing macros: MMU_GATE_MAP, MMU_PRELOAD, MMU_UPDATE_SPOOLMAN_*  │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Moonraker + Spoolman integration                                    │
│  - active_spool_id tracked centrally                                 │
│  - Spool detail (PA, retraction, temps) lives in Spoolman extra      │
│    fields                                                            │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  KBobine (Klipper extension via Moonraker update_manager)            │
│  - On startup AND on active_spool_id change:                         │
│    - Fetch spool detail from Spoolman                                │
│    - Populate _KBOBINE.current_settings array                        │
│    - Macros applying values (SET_PRESSURE_ADVANCE etc.) fire         │
│      automatically                                                    │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Print starts with correct runtime values for the active gate's      │
│  loaded spool — without slicer profile per-spool sprawl.             │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. Phase 1 — Pre-gate sensors

### 3.1 Hardware requirement

Six lever microswitches, one per gate, triggered by filament insertion at the entry of each gate. Each sensor returns digital high/low; Klipper polls via `pre_gate_switch_pin_X` config in `mmu_hardware.cfg` (HH built-in API; placeholders already exist in our config).

### 3.2 Board decision (OPEN)

The current EASY-BRD (SAMD21G18A) uses 11 GPIO and has at most 1-2 spare. Three options:

| Option | Hardware cost | Risk |
|---|---|---|
| **A — Replace EASY-BRD with BTT MMB CAN V1.0** | ~$50 board + ~$15 CAN HAT for Pi | Adds CAN bus to a USB-only build; introduces a new failure mode but solves USB-enumerate-race [[mcu-usb-reenumerate-race]] for the MMU |
| **B — Wire pre-gate sensors to spare SKR Z GPIO** | ~$0 (just sensors + microswitches ~$30) | Long cable run from MMU area to electronics bay; SKR Z has plenty of free GPIO but cable management is uglier; introduces no new MCU |
| **C — Add a dedicated small USB MCU** (BTT Pico, ~$10) | ~$10 + sensors | Adds a 6th USB MCU. Compounds [[mcu-usb-reenumerate-race]] risk. Lowest hardware cost but worst architectural fit. |

**Recommendation:** decide A vs B during Phase 1 implementation. C is dispreferred due to the existing USB-enumerate footgun.

A is the cleaner long-term answer (purpose-built board, CAN-ready, native pre-gate support); B is the pragmatic "use what we have" answer with cable-management cost.

### 3.3 Mechanical

- 6× microswitch holders printed per gate (use [the Printables filament sensor design](https://www.printables.com/model/1053284) or a derivative).
- Lever oriented so filament insertion depresses the switch.
- Wiring to whatever MCU was chosen in 3.2.

### 3.4 Klipper config

Update `config/mmu/base/mmu_hardware.cfg` (Pi-symlinked from `~/Happy-Hare/`) to set the pre-gate pin aliases. The placeholders exist:

```
pre_gate_switch_pin_0: ^mmu:MMU_PRE_GATE_0
... through pre_gate_switch_pin_5
```

`MMU_PRE_GATE_X` aliases in `mmu/base/mmu.cfg` get filled with actual pins (e.g., `MMU_PRE_GATE_0=PA12,` if EASY-BRD survives Phase 1; OR routed through the new board's GPIO names if replaced).

### 3.5 Phase 1 deliverables

- 6 pre-gate sensors wired and triggering correctly per `MMU_TEST_SENSORS`.
- Filament insertion + pre-gate detection works through HH's gate-map auto-assignment (without NFC yet — manual `MMU_GATE_MAP NEXT_SPOOLID=N` triggers + insert verifies the auto-detect path).
- CLAUDE.md hardware inventory updated.
- Memory entry `[[pre-gate-sensors-installed]]` documenting the choice + wiring.

### 3.6 Phase 1 independent value (without phases 2-3)

Even without NFC, pre-gate sensors give HH proper runout detection per gate (existing `pre_gate_switch_pin_X` infrastructure). Useful in its own right; would ship as a standalone PR before the NFC work begins.

## 4. Phase 2 — Centralized NFC reader

### 4.1 Hardware

| Item | Cost |
|---|---|
| 1× PN532 V3 NFC reader (UART variant) | ~$15 |
| 1× [Elechouse PN532 holder for Voron](https://www.printables.com/model/798929-elechouse-pn532-v3-nfc-holder-for-voron-for-spoolm) | One print |
| 50-pack NTAG 215 tags | ~$10 |
| 4× jumper wires (3.3V, GND, TX, RX) | $0 |

Reader connects to **Pi UART** (3.3V — never 5V, would damage Pi GPIOs over time). Mount in a "scan station" position near the gate loading area.

### 4.2 Software

Install [bofh69/nfc2klipper](https://github.com/bofh69/nfc2klipper) as a systemd service on the Pi:

- Python venv at `~/nfc2klipper/`
- Config at `~/nfc2klipper/nfc2klipper.cfg` (Pi serial port, Moonraker URL)
- systemd unit `nfc2klipper.service` enabled and started

Service polls the PN532; on tag read:

1. Reads the spool_id from the tag (encoded as a simple integer or as a URL pointing into Spoolman).
2. Calls Moonraker `POST /printer/gcode/script` with `MMU_GATE_MAP NEXT_SPOOLID=<id>`.
3. HH stores the pending assignment with a 20s timeout (`pending_spool_id_timeout` in HH's config).
4. User inserts filament into a gate; pre-gate sensor (from Phase 1) triggers the auto-assignment.

### 4.3 Tag-writing workflow

A new spool needs a tag written once. Options documented (not all need to be supported):

1. **Web UI on the Pi** (nfc2klipper ships one) — held over the reader, browser-side click.
2. **Mobile app** — any NTAG NDEF writer can write a simple JSON or numeric ID.
3. **CLI tool** on the Pi — `nfc2klipper-write --spool-id N`.

### 4.4 Klipper-side config

`config/mmu/base/mmu_parameters.cfg` gets the pending-spool timeout set (probably already defaults to 20s; verify).

`moonraker.conf` may need an `[update_manager nfc2klipper]` block to track upstream changes.

### 4.5 Phase 2 deliverables

- Tag write/read workflow functional via Mainsail console (manual `MMU_GATE_MAP NEXT_SPOOLID=N` confirmed working).
- nfc2klipper systemd service running stable.
- Tagging a spool + scanning + inserting into a gate auto-assigns in HH gate map.
- Spoolman registers the gate→spool mapping via HH's existing `MMU_UPDATE_SPOOLMAN_LOCATION`.
- CLAUDE.md updated (new hardware: NFC reader; new service: nfc2klipper).
- Test plan for the integration end-to-end.

### 4.6 Phase 2 independent value (without Phase 3)

Even without KBobine, NFC scanning gives a faster spool-registration workflow + accurate gate↔spool tracking in Spoolman. The runtime PA tuning piece is the Phase 3 layer; Phase 2 is "Spoolman knows what's where."

## 5. Phase 3 — KBobine per-spool runtime tuning

### 5.1 Software

Install [fbeauKmi/kbobine_filament_settings](https://github.com/fbeauKmi/kbobine_filament_settings):

- Clone to `~/kbobine_filament_settings/`
- Run `bash install.sh -m` (minimal install) — adds Moonraker config block, creates Klipper include
- Klipper restart loads the `_KBOBINE` macro that exposes `current_settings`

### 5.2 Spoolman data model

KBobine reads per-spool data from Spoolman's `extra` field (JSON). Verify the deployed Spoolman version supports extra fields (Spoolman ≥0.18 does; check `http://192.168.0.89:7912/api/v1/info`).

Schema for spool extra:

```json
{
  "pressure_advance": 0.045,
  "retraction_length": 0.5,
  "retraction_speed": 35,
  "extruder_temp": 245,
  "bed_temp": 110,
  "chamber_temp": 30
}
```

Per spool. Initially the user populates these manually (after one-time PA tower measurement per spool).

### 5.3 Klipper macro hooks

PRINT_START currently has:
```
M109 S{extruder}
```

Becomes (after Phase 3):
```
{% set kb = printer['gcode_macro _KBOBINE'].current_settings|default({}) %}
M109 S{kb.extruder_temp|default(extruder)}
{% if kb.pressure_advance is defined %}
  SET_PRESSURE_ADVANCE ADVANCE={kb.pressure_advance}
{% endif %}
{% if kb.retraction_length is defined %}
  SET_RETRACTION RETRACT_LENGTH={kb.retraction_length} RETRACT_SPEED={kb.retraction_speed|default(35)}
{% endif %}
```

KBobine populates `current_settings` automatically on every active-spool-change event, so by the time PRINT_START runs, the right values are in place. The macro reads them as a safety net.

### 5.4 OrcaSlicer profile changes

Per-filament profile changes needed once KBobine takes over PA:

- **Remove** per-filament `pressure_advance` values (or set to 0 to signal "use runtime").
- **Remove** per-filament retraction_length values.
- Keep temps (Spoolman is the source of truth, but the slicer profile temps stay as a fallback if KBobine fails).

Profiles consolidate from "ASA-Black, ASA-Blue, ASA-Red, ASA-base, ABS, PLA, PLA+, Silk PLA, etc." into generic "ASA, ABS, PLA, PETG" base profiles. Color and per-spool variation live entirely in Spoolman.

Document the migration in `docs/slicer-templates/orcaslicer.md`.

### 5.5 Phase 3 deliverables

- KBobine installed and applying per-spool values on tool change.
- One ASA spool measured (PA tower, retraction tune) + values stored in Spoolman extra.
- One PLA spool similarly.
- Test prints confirm runtime values applied correctly.
- OrcaSlicer profiles consolidated to generic-per-material; per-spool tuning lives in Spoolman.

## 6. MMU↔Spoolman boundary (Happy-Hare integration)

Happy-Hare owns the gate↔spool mapping. The rest of the stack treats "active spool" as a single integer published by HH.

### 6.1 Existing HH macros leveraged

- `MMU_GATE_MAP NEXT_SPOOLID=<id>` — set pending spool for next gate insertion (used by nfc2klipper).
- `MMU_GATE_MAP GATE=N SPOOLID=M` — explicit gate-to-spool mapping (for manual override).
- `MMU_UPDATE_SPOOLMAN_LOCATION` — notify Spoolman that gate N has spool M.
- `pending_spool_id_timeout` (variable in HH config) — how long after scan before the assignment expires.
- `MMU_CHANGE_TOOL TOOL=N` — switches active tool; HH publishes the new active_spool_id.
- HH gate-map persistence in `~/printer_data/config/mmu/mmu_vars.cfg`.

### 6.2 New macros (optional, Phase 2)

Wrapper for NFC scan flow:
```
[gcode_macro _NFC_SPOOL_SCANNED]
description: Called by nfc2klipper when a tag is read. Sets the pending spool.
gcode:
  {% set id = params.SPOOL_ID|int %}
  MMU_GATE_MAP NEXT_SPOOLID={id}
  RESPOND PREFIX="NFC:" MSG="Pending spool {id}; insert filament within 20s"
```

nfc2klipper calls this instead of `MMU_GATE_MAP` directly so the responder message is consistent.

### 6.3 Workflow per scenario

**Loading a new spool into gate 3:**
1. Place tag near reader.
2. nfc2klipper reads tag → `MMU_GATE_MAP NEXT_SPOOLID=12345` (where 12345 is the Spoolman spool ID).
3. HH stores pending assignment with 20s timer.
4. User inserts filament into gate 3.
5. Pre-gate sensor 3 triggers → HH assigns pending spool 12345 to gate 3.
6. HH updates Spoolman: spool 12345 is at location "MMU gate 3 of Voron 2.611."

**Starting a print using gate 2 first:**
1. PRINT_START runs (via OrcaSlicer's machine start gcode, with INITIAL_TOOL=2).
2. `MMU_START_SETUP INITIAL_TOOL=2 ...` — HH knows tool 2 will be used.
3. `MMU_START_LOAD_INITIAL_TOOL` runs.
4. HH selects gate 2, publishes active_spool_id = gate-2's mapped spool to Moonraker.
5. Moonraker fires the spool-change event.
6. KBobine fetches gate-2-spool's extra fields from Spoolman.
7. KBobine populates `_KBOBINE.current_settings`.
8. PRINT_START continues; subsequent `SET_PRESSURE_ADVANCE` etc. fire with correct values.

**Tool change mid-print (gate 2 → gate 4):**
1. Slicer emits `T4` or `MMU_CHANGE_TOOL TOOL=4`.
2. HH unloads gate 2, loads gate 4.
3. HH publishes active_spool_id = gate-4's mapped spool.
4. KBobine refreshes current_settings.
5. SET_PRESSURE_ADVANCE etc. fire automatically (KBobine's update macros).

## 7. Slicer-side changes (Phase 3)

OrcaSlicer profile consolidation:

| Today | After Phase 3 |
|---|---|
| 12 filament profiles, one per filament+color | ~4 base profiles per material (PLA, ABS, ASA, PETG) |
| Per-filament `pressure_advance` baked in | Removed (or set to 0) — runtime value from KBobine |
| Per-filament `retraction_length` | Same — runtime value from KBobine |
| Per-filament `chamber_temperature` | Stays — drives PRINT_START's chamber soak (independent of KBobine) |
| Per-filament `filament_type` | Stays — drives MATERIAL param to PRINT_START |

The 8 color/brand variants of ASA collapse to "ASA" — color is metadata in Spoolman, not a separate slicer profile.

`docs/slicer-templates/orcaslicer.md` gets a new section documenting the consolidated profile model.

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **EASY-BRD has insufficient free GPIO** | High (already confirmed) | Phase 1's board decision (3.2). Most likely needs BTT MMB CAN or SKR Z pin reuse. |
| **NFC tag rewriting risks** (accidentally clobbering a tag) | Low | Locking bits on the NTAG after first write (NDEF protection). Document the write procedure. |
| **Spoolman extra-fields version mismatch** | Low | Check Spoolman version in Phase 3 before installing KBobine. If too old, upgrade. |
| **OpenTag3D vs OpenSpool tag format churn** | Medium (OpenTag3D finalizing in 2025) | Phase 2 uses OpenSpool's current format. Migration path documented when OpenTag3D ships. |
| **Pre-gate sensor false triggers** (e.g., spool tug) | Medium | HH already has debouncing. If issues, add a per-sensor `pulldown` or `pullup` adjustment in mmu_hardware.cfg. |
| **Pi UART contention** (other services using the Pi's UART) | Low | The Pi has one UART exposed via GPIO; verify nothing else uses it. Bluetooth disabled by default on MainsailOS. |
| **MMU↔Spoolman pending-spool race** (user scans tag, doesn't insert filament in 20s) | Low | HH's existing timeout handles this gracefully (assignment voids; user re-scans). |
| **Adding USB-MCU compounds [[mcu-usb-reenumerate-race]]** | High if Option C is taken in Phase 1 | Avoid Option C; favor A (board replace) or B (SKR Z pin reuse). |

## 9. Testing strategy

| Phase | Layer | Coverage |
|---|---|---|
| 1 | L3 klippy parse | Validates new MCU + pre-gate pin assignments |
| 1 | Manual | `MMU_TEST_SENSORS` on the Pi after install; insert filament into each gate, confirm pin reads |
| 2 | L3 klippy parse | nfc2klipper doesn't add Klipper macros (Python service) so L3 unaffected |
| 2 | Manual | Tag write workflow; scan → `MMU_GATE_MAP NEXT_SPOOLID=N` fires; insert → gate map updates |
| 2 | Manual | End-to-end: 6 spools registered in Spoolman, 6 tags written, 6 scan-and-insert flows succeed |
| 3 | L3 klippy parse | KBobine installs a `_KBOBINE` gcode_macro; verify it loads |
| 3 | Manual | Set spool A's PA=0.04 in Spoolman, B's PA=0.06; switch active spool A→B; verify `SET_PRESSURE_ADVANCE` fires with 0.06 |
| 3 | Manual | Test print using spool A first, then tool change to spool B mid-print; verify PA updates |

Per-phase PR review via `pr-review-toolkit:review-pr` before each merge.

## 10. Future work

- **Per-rewinder OpenSpool nodes** (deferred): if the centralized-reader-with-pre-gate-sensors workflow proves operationally annoying, revisit per-rewinder ESP32+PN532 nodes with MQTT. Community consensus says it's not worth it; revisit after lived experience.
- **OpenTag3D migration** when standard finalizes (~2025). nfc2klipper updates planned to support.
- **Chamber VOC sensor** (per chamber-control spec §10) — fits naturally on this system but is a separate hardware addition.
- **HH `MMU_CHECK_GATES` integration** — auto-fill gate map from Spoolman state at print start (already in HH; verify it's wired up after Phase 2).
- **Slicer-side filament_type → chamber_temperature defaults** living in Spoolman — currently lives in OrcaSlicer per-profile. Could centralize in Spoolman if KBobine extends to chamber.

## 11. Anti-criteria

- No fork of Happy-Hare. Use HH's existing macros + extension points only.
- No fork of Spoolman. Use stock + extra-fields capability.
- No fork of KBobine. Configure via `_USER_VARIABLE`-style hooks.
- No fork of nfc2klipper. Customize via its config file only.
- No fork of OrcaSlicer. Profile JSON edits via slicer UI; macro changes via PRINT_START hooks.
- No new Klipper Python extensions beyond what KBobine ships.
- No replacement of the existing Spoolman server (already running on Ben's LAN; we use it as-is).
- No edits to mainsail.cfg or any Pi-side symlink target (per [[feedback-mainsail-cfg-symlink-trap]]).

## 12. References

- Happy-Hare Spoolman Support wiki: <https://github.com/moggieuk/Happy-Hare/wiki/Spoolman-Support>
- nfc2klipper: <https://github.com/bofh69/nfc2klipper>
- KBobine: <https://github.com/fbeauKmi/kbobine_filament_settings>
- OpenSpool: <https://github.com/spuder/OpenSpool>
- Voron PN532 holder: <https://www.printables.com/model/798929-elechouse-pn532-v3-nfc-holder-for-voron-for-spoolm>
- Standalone pre-gate filament sensor (Printables): <https://www.printables.com/model/1053284-standalone-filament-sensor-happy-hare-ercf-tradrac>
- OpenTag3D: <https://github.com/OpenTag3D/OpenTag3D>
- BTT MMB CAN documentation: <https://github.com/bigtreetech/MMB>
- Memory entries: [[mcu-usb-reenumerate-race]], [[feedback-mainsail-cfg-symlink-trap]], [[orcaslicer-settings-path]]
