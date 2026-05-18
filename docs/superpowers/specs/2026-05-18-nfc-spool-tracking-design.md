# NFC-driven spool tracking + per-spool runtime tuning — spec

**Owner:** Ben (multi-phase hardware + software build; spans printer wiring, MMU firmware, Klipper macros, Moonraker integration, slicer changes).

**Restart impact (per phase):**

- Phase A (KBobine + slicer consolidation): **RESTART** (gcode_macro + Moonraker config changes; no MCU work).
- Phase B (pre-gate sensors on SKR Z + Ethernet): **RESTART** (pin assignments on existing MCU; no new firmware).
- Phase C (NFC reader + nfc2klipper): **RESTART** (Python service on Pi; no Klipper config beyond moonraker.conf entry).

**Pairs with:**

- [`docs/superpowers/specs/2026-05-18-print-lifecycle-redesign.md`](2026-05-18-print-lifecycle-redesign.md) — PRINT_START's existing `MMU_START_SETUP` flow becomes the publisher of "active spool changes" to KBobine.
- [`docs/superpowers/specs/2026-05-18-chamber-control-design.md`](2026-05-18-chamber-control-design.md) — independent; both touch Spoolman but at different layers.

---

## 1. Goal

Eliminate slicer-side per-filament profile sprawl by making **Spoolman the authoritative source for per-spool tuning data** (pressure advance, retraction, temps), with NFC tags driving the gate↔spool mapping in Happy-Hare. End state mirrors Bambu Lab's AMS workflow on a fully open-source, multi-vendor stack.

**Non-goals:**

- Per-rewinder NFC readers. Happy-Hare community has explicitly considered and rejected this (HH wiki: *"it isn't practical to build a RFID/QR code reader into every gate"*). One shared reader at a scan station + HH's `NEXT_SPOOLID` mechanism is the supported model.
- Replacing Happy-Hare's gate-map persistence. HH's `mmu_vars.cfg` stays the in-Klipper canonical store; Spoolman augments with per-spool tuning details.
- Bambu RFID tag compatibility. Bambu tags are RSA-signed; we use OpenSpool's current JSON-on-NTAG format, migrating to OpenTag3D / OpenPrintTag when those standards finalize (2025-2026).
- Auto-measuring per-spool PA. The system applies measured values; the user still runs PA tower tests once per spool.
- A new MMU board. Per Ben (2026-05-18), we use spare GPIO on the existing SKR Z board rather than replacing the EASY-BRD or adding a new MCU.

## 2. INDX context (load-bearing)

**This Voron will be retrofitted with Bondtech INDX when it becomes available.** Timeline is uncertain (Bondtech's founders edition launches Q1 2026 with Prusa CORE One exclusivity; Voron-port work hasn't begun). Happy-Hare INDX support is a [feature request awaiting triage](https://github.com/moggieuk/Happy-Hare/issues/853) with no roadmap.

**This drives the phase ordering:**

- **Phase A** is fully MMU-agnostic — Spoolman data, KBobine runtime macros, slicer profile consolidation. **100% survives the INDX retrofit.** Ship first.
- **Phase B** (pre-gate sensors) — hardware survives (switches and wiring are universal); the Klipper config layer (`pre_gate_switch_pin_X` → SKR Z pin aliases) will need a once-over when INDX swaps in its own tool-detection scheme. Ship second.
- **Phase C** (NFC reader hardware + tags + Spoolman data) — hardware survives; the integration software (`nfc2klipper` calling HH's `MMU_GATE_MAP NEXT_SPOOLID`) will need rework for whatever INDX exposes as its spool-ID-change API (Bondtech may ship a native daemon). Ship third.

**Investments that survive verbatim:** Spoolman per-spool tuning data; KBobine extension; slicer profile consolidation; pre-gate switches; PN532 reader; NTAG tags; tag-to-Spoolman associations.

**Investments that need software rework post-INDX:** Klipper macro hooks specific to HH (`MMU_GATE_MAP`, `MMU_START_SETUP`, etc.); nfc2klipper's HH integration. Roughly an evening of YAML + macro tweaks when INDX arrives.

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Hardware events                                                     │
│  - NFC tag near reader (Phase C)                                     │
│  - Filament inserted into gate (Phase B, triggers pre-gate sensor)   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  nfc2klipper (Python service on Pi, Phase C)                         │
│  - Reads tag via PN532 (UART to Pi)                                  │
│  - Calls Moonraker: MMU_GATE_MAP NEXT_SPOOLID=<id>                   │
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
│  - Spool detail (PA, retraction, temps) in Spoolman extra fields     │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│  KBobine (Phase A) — Klipper extension via Moonraker update_manager  │
│  - On startup AND on active_spool_id change:                         │
│    - Fetch spool detail from Spoolman                                │
│    - Populate _KBOBINE.current_settings array                        │
│    - PRINT_START macros read + apply (SET_PRESSURE_ADVANCE etc.)     │
└─────────────────────────────────────────────────────────────────────┘
```

Phases A, B, C add capability to this picture incrementally; each is independently functional.

---

## 4. Phase A — KBobine + Spoolman tuning + slicer profile consolidation

**Ship first. MMU-agnostic. Hardware cost: $0.**

### 4.1 Install KBobine

Clone [fbeauKmi/kbobine_filament_settings](https://github.com/fbeauKmi/kbobine_filament_settings) to `~/kbobine_filament_settings/` on the Pi. Run `bash install.sh -m` (minimal install) — adds a Moonraker config block, creates a Klipper include for `_KBOBINE` gcode_macro. RESTART required.

Verify after restart: `printer['gcode_macro _KBOBINE'].current_settings` is queryable from Mainsail console.

### 4.2 Spoolman extra fields

KBobine reads per-spool data from Spoolman's `extra` JSON field. Verify the deployed Spoolman version supports extra fields (Spoolman ≥0.18; check `http://192.168.0.89:7912/api/v1/info`). Current Pi Spoolman version listed in CLAUDE.md as `v0.0.1-143-gc7fff11` — needs verification before Phase A; upgrade if too old.

Per-spool extra schema:

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

The user populates these via Spoolman's UI after measuring once per spool.

### 4.3 PRINT_START hook updates

Current PRINT_START applies extruder temp via `M109 S{extruder}` only. Add a KBobine settings-read block before the existing M109:

```ini
# Per-spool runtime values from KBobine (Spoolman → Klipper at active-spool change).
{% set kb = printer['gcode_macro _KBOBINE'].current_settings|default({}) %}
{% if kb.pressure_advance is defined %}
  SET_PRESSURE_ADVANCE ADVANCE={kb.pressure_advance}
{% endif %}
{% if kb.retraction_length is defined %}
  SET_RETRACTION RETRACT_LENGTH={kb.retraction_length} RETRACT_SPEED={kb.retraction_speed|default(35)}
{% endif %}
# Note: extruder_temp / bed_temp / chamber_temp from KBobine could OVERRIDE slicer values here,
# but for now slicer values win (filament profile per-material; Spoolman per-spool just adds PA/retraction).
```

This block lives in PRINT_START step 13 (just before the existing `M109 S{extruder}` line).

### 4.4 Slicer profile consolidation

Current 12 OrcaSlicer filament profiles → consolidate to ~4 generic per-material:

| Material | Today | After Phase A |
|---|---|---|
| PLA | `PLA`, `Inland PLA+`, `Inland Silk PLA`, `Sunlu PLA`, `Sunlu PLA+`, `SUNLU Silk PLA` (6 profiles) | One generic `PLA` profile |
| ABS | `Inland ABS` (1) | One generic `ABS` profile |
| ASA | `Ambrosia ASA`, `Black`, `Planetary Blue`, `Voron Red` (4) | One generic `ASA` profile |
| PETG | `Overture Transparent PETG` (1) | One generic `PETG` profile |

Per-spool variation (PA, retraction, exact color) moves entirely into Spoolman. Color is metadata in Spoolman, not a separate slicer profile.

**Profile changes per generic:**

- Remove per-filament `pressure_advance` (KBobine applies at runtime).
- Remove per-filament `retraction_length` / `retraction_speed` (same).
- Keep per-filament temps (slicer profile temps as fallback; KBobine could override per-spool but for now stick with slicer).
- Keep `chamber_temperature` per-material (drives PRINT_START's chamber soak — slicer-driven for per-material policy).
- Keep `filament_type` (drives MATERIAL param to PRINT_START).

The OrcaSlicer Machine start gcode (Voron v2.611 → Machine G-code → Machine start G-code) is unchanged — it already passes the right params to PRINT_START.

Document the migration in `docs/slicer-templates/orcaslicer.md`.

### 4.5 Per-spool measurement workflow

For each currently-loaded spool:

1. Run a PA tower test print (slicer template + thin-walled cube; Frix-x's calibrate_pa macro already in our repo).
2. Measure best PA value visually (cleanest layer transition).
3. Run a retraction tower for that spool.
4. Open Spoolman UI → that spool → Edit → Extra → paste the JSON schema with measured values.
5. Repeat per active spool. ~15-20 min per spool.

This is the lasting work investment. Once done, that spool's values are authoritative forever.

### 4.6 Phase A deliverables

- KBobine installed, `_KBOBINE.current_settings` populated on tool change.
- PRINT_START reads + applies PA/retraction.
- 4 generic slicer profiles in place; old per-spool profiles archived (kept in Orca as inactive; deletable later).
- One spool measured + populated in Spoolman.
- Test print with the measured spool confirms PA applies correctly (visual inspection on a known-tuning-sensitive print).
- CLAUDE.md macro inventory updated.
- `docs/slicer-templates/orcaslicer.md` updated with per-material profile model.

### 4.7 Phase A independent value

- Single source of truth for per-spool tuning. No more "which Orca profile was tuned vs which wasn't."
- Slicer profile sprawl gone. Adding a new color of an existing material is a Spoolman entry, not a slicer profile clone.
- Investment 100% survives INDX migration.

---

## 5. Phase B — Pre-gate sensors via SKR Z + Ethernet cable

**Ship second. ERCF-now / INDX-later (hardware survives). Hardware cost: ~$30.**

### 5.1 Hardware: ERCF v2 gate mod

**Recommended:** [k1-801 ERCF v2 Filament Block with built-in pre-gate sensor](https://www.printables.com/model/1188732) on Printables — drop-in replacement for the stock v2 filament block with switch cutout integrated. Uses one D2F-01FL switch + one 4mm ball bearing per gate.

You do NOT need to migrate to ERCF v3 STLs. The k1-801 v2-specific mod is purpose-built and preserves your existing v2 mounting + spacing.

Alternative if k1-801 has issues: [juliusjj25/ERCF-Pregate-Sensors](https://github.com/juliusjj25/ERCF-Pregate-Sensors) (v2-specific, similar design).

### 5.2 Wiring: SKR Z + Ethernet cable

Per Ben (2026-05-18): use SKR Z spare GPIO + a Cat5e/Cat6 Ethernet cable run from the electronics bay to the MMU.

**Cable wiring (one Ethernet cable suffices):**

| Wire | Signal | Notes |
|---|---|---|
| 1-6 | Pre-gate signal, gates 0-5 | One wire per microswitch's normally-open contact |
| 7 | Common GND | All 6 microswitches share this; closing a switch shorts gate-N signal to GND |
| 8 | Spare | Reserved (future runout sensor or signal break) |

The Klipper config will use internal pullups on the LPC1769 pins, so the switches need only NO + GND (no external pullup required).

**SKR Z pin assignments (spec target — confirm during implementation):** Six free GPIO on the SKR 1.4 Z board. Likely candidates from looking at the SKR 1.4 pinout:

- E1 stepper-related GPIO (E1_DIAG, E1_STOP, E1_STEP/DIR/EN) — likely 5 free pins since we use only stepper_z/z1/z2/z3, not E1
- TFT header (P0.0, P0.1, P3.4) — typically free if no TFT display
- Servo header (P2.0) — free
- Wifi-3/Wifi-4 headers — free

Need to verify by checking `config/motion.cfg` (or whatever moved post-#63) against the SKR 1.4 schematic. Aim for pins exposed on accessible headers (not soldered-only pads).

**Klipper config changes:**

`config/mmu/base/mmu.cfg` — fill in `MMU_PRE_GATE_X` aliases (currently empty placeholders):

```
# Was: MMU_PRE_GATE_0=,
# Becomes (assignments TBD during implementation):
MMU_PRE_GATE_0=z:<pin>,
MMU_PRE_GATE_1=z:<pin>,
... etc through MMU_PRE_GATE_5
```

`config/mmu/base/mmu_hardware.cfg` — the `pre_gate_switch_pin_0..5` lines are already in place referencing those aliases. No change needed once aliases are filled.

### 5.3 BOM — Phase B

| Item | Qty | Specific part | Notes | Approx cost |
|---|---|---|---|---|
| Pre-gate microswitch | 6 | **Omron D2F-01FL** (0.1A simulated roller lever) | Specifically what the k1-801 mod is designed around. **Don't substitute different D2F variants** — different lever geometry. Order from DigiKey or Mouser for genuine parts; Amazon has counterfeit risk on Omron switches. | $3-5 ea = $18-30 |
| 4mm ball bearings | 6+ | 4mm OD steel ball bearings (loose) | Sits in the filament block; depresses switch lever when filament present. Get a bag of 50 for spares. | ~$5 for 50 |
| Cat5e or Cat6 Ethernet cable | 1 | 2-3 meter run | Electronics bay to MMU. Cat5e fine for low-speed signals. | ~$5 |
| RJ45 to screw-terminal breakouts (optional) | 2 | "RJ45 keystone with screw terminals" | One at each end. Skip if you want to solder direct to the cable. | ~$3 ea = $6 |
| Dupont jumper wires | 1 set | Female-female 20cm 40-pin set | SKR Z header → RJ45 breakout | ~$5 |
| Pre-gate sensor mounts | 6 prints | Comes with k1-801 STL pack | Your filament + your time | $0 |

**Phase B total: ~$40-50.**

### 5.4 Phase B deliverables

- 6 pre-gate sensors wired + reading correctly via `MMU_TEST_SENSORS`.
- Insertion of filament into any gate triggers correctly (no false trips, no missed insertions).
- HH gate-map auto-assignment works (manual `MMU_GATE_MAP NEXT_SPOOLID=N` + filament insert → gate gets the spool).
- CLAUDE.md hardware inventory updated.
- Memory entry recording the SKR Z pin assignments + cable wiring.

### 5.5 Phase B independent value

- Runout detection per gate (HH's existing pre-gate sensor logic).
- Hands-off gate map assignment after NFC scan (Phase C unlocks this).
- Pre-gate detection is the standard build today — Ben's MMU is currently NOT a typical HH setup without it.

### 5.6 Phase B INDX survival

- **Switches:** survive completely. Lever microswitches are universal hardware; they re-wire to whatever MCU INDX's tools route through.
- **Cable run:** survives. Same physical cable can carry the signals to whatever new endpoint.
- **SKR Z pin assignments:** may or may not survive. If INDX adopts its own MCU for tool sensing, the wiring would re-route. If INDX reuses existing SKR Z pins, no change.
- **Klipper config (`pre_gate_switch_pin_X`):** rewrites to INDX's tool-detection API. The macro layer that consumes these (HH's auto-assign-on-insertion) is replaced by INDX-equivalent. Probably 30 minutes of YAML editing.

---

## 6. Phase C — Centralized NFC reader + nfc2klipper

**Ship third. ERCF-now / INDX-later (hardware survives, software adapts). Hardware cost: ~$25.**

### 6.1 Hardware

| Item | Qty | Specific part | Notes | Approx cost |
|---|---|---|---|---|
| NFC reader | 1 | **Elechouse PN532 V3** (UART mode, 3.3V) | Verify "V3" in listing — earlier versions have weaker antenna. Connect via UART to Pi (not USB; saves a USB slot and avoids more MCU-enumeration risk per [[mcu-usb-reenumerate-race]]). | ~$10-15 |
| NFC tags | 50 | **NTAG 215 round adhesive, 25mm** | 504 bytes (plenty for OpenSpool/OpenTag3D JSON). 216 is overkill + more expensive. **Verify "100% NXP" wording in product listing** — counterfeit NTAGs are common on AliExpress and have different memory layouts that confuse OpenSpool. | ~$10-15 for 50-pack |
| Reader mount | 1 print | [Elechouse PN532 V3 holder for Voron](https://www.printables.com/model/798929-elechouse-pn532-v3-nfc-holder-for-voron-for-spoolm) | Voron-frame-mounted at the scan station position | $0 |
| Jumper wires | 4 | F-F Dupont, 3.3V GND TX RX | Reader to Pi UART | $0 (from Phase B's wire kit) |

**Phase C total: ~$25.**

**Note on Pi UART (vs USB):** the PN532 UART variant connects directly to the Pi's GPIO UART pins. Avoids adding a 6th USB MCU (current count is 5: main SKR, Z SKR, EBB, Eddy, EASY-BRD) — keeps us under the threshold that aggravates [[mcu-usb-reenumerate-race]].

### 6.2 Software: nfc2klipper

Install [bofh69/nfc2klipper](https://github.com/bofh69/nfc2klipper) as a Pi systemd service:

- Python venv at `~/nfc2klipper/`
- Config at `~/nfc2klipper/nfc2klipper.cfg` (Pi serial port, Moonraker URL)
- systemd unit `nfc2klipper.service` enabled

Service polls the PN532 every ~500ms. On tag read:

1. Decodes spool_id from the tag (Spoolman ID encoded as integer NDEF; or a UID Spoolman knows).
2. POSTs to Moonraker: `printer/gcode/script` body `MMU_GATE_MAP NEXT_SPOOLID=<id>`.
3. HH stores pending assignment with 20s timeout.
4. User inserts filament into a gate; Phase B's pre-gate sensor triggers → HH auto-assigns the pending spool.

`moonraker.conf` gets an `[update_manager nfc2klipper]` block tracking upstream changes.

### 6.3 Tag-writing workflow

For each spool:

1. Register the spool in Spoolman UI (manufacturer, material, color, etc.) — gets a spool_id.
2. Place an NTAG tag near the reader at the scan station.
3. Use nfc2klipper's web UI (or CLI) to write the spool_id to the tag.
4. Affix the tag to the spool flange.

### 6.4 New Klipper macro

Optional thin wrapper for cleaner responder messages:

```
[gcode_macro _NFC_SPOOL_SCANNED]
description: Called by nfc2klipper when a tag is read. Sets the pending spool.
gcode:
  {% set id = params.SPOOL_ID|int %}
  MMU_GATE_MAP NEXT_SPOOLID={id}
  RESPOND PREFIX="NFC:" MSG="Pending spool {id}; insert filament within 20s"
```

nfc2klipper config calls `_NFC_SPOOL_SCANNED SPOOL_ID=...` instead of `MMU_GATE_MAP` directly. Optional — nice-to-have for log readability.

### 6.5 Phase C deliverables

- nfc2klipper systemd service running.
- Tag-write workflow verified (write to tag, read back, see correct spool_id).
- End-to-end: scan tag → `MMU_GATE_MAP NEXT_SPOOLID` fires → insert filament into gate → pre-gate sensor (Phase B) auto-assigns → HH updates Spoolman gate location.
- 6 active spools have tags written + attached.
- CLAUDE.md: new hardware entry (NFC reader); new service entry (nfc2klipper).

### 6.6 Phase C INDX survival

- **PN532 reader + holder:** survives. Same hardware reads tags regardless of what MMU consumes the result.
- **NTAG tags + Spoolman entries:** survive. Tag-to-spool associations don't change with MMU choice.
- **Mount location:** may need to move depending on INDX's tool-pickup geometry. Voron-frame mount is reusable.
- **nfc2klipper service:** needs rework. Today's HH-specific `MMU_GATE_MAP NEXT_SPOOLID` becomes whatever INDX exposes (Bondtech-native daemon, or a new Klipper macro hook). The service ARCHITECTURE — Python systemd daemon, polling, Moonraker integration — stays the same.

---

## 7. MMU↔Spoolman boundary (Happy-Hare integration, unchanged from previous spec rev)

Happy-Hare owns the gate↔spool mapping. The rest of the stack treats "active spool" as a single integer published by HH.

### 7.1 Existing HH macros leveraged

- `MMU_GATE_MAP NEXT_SPOOLID=<id>` — set pending spool for next gate insertion (used by nfc2klipper).
- `MMU_GATE_MAP GATE=N SPOOLID=M` — explicit gate-to-spool mapping (for manual override).
- `MMU_UPDATE_SPOOLMAN_LOCATION` — notify Spoolman that gate N has spool M.
- `pending_spool_id_timeout` (in HH config) — assignment expiry, default 20s.
- `MMU_CHANGE_TOOL TOOL=N` — switches active tool; HH publishes the new active_spool_id.
- HH gate-map persistence in `~/printer_data/config/mmu/mmu_vars.cfg`.

### 7.2 Workflow per scenario

**Loading a new spool into gate 3:**
1. Place tag near reader.
2. nfc2klipper reads tag → `MMU_GATE_MAP NEXT_SPOOLID=12345`.
3. HH stores pending assignment with 20s timer.
4. User inserts filament into gate 3.
5. Pre-gate sensor 3 triggers → HH assigns pending spool 12345 to gate 3.
6. HH updates Spoolman: spool 12345 is at location "MMU gate 3 of Voron 2.611."

**Starting a print using gate 2 first:**
1. PRINT_START runs (OrcaSlicer's Machine start gcode passes INITIAL_TOOL=2).
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
5. PA + retraction update for the new spool.

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **SKR Z has insufficient accessible free GPIO** | Low (SKR 1.4 typically has 6+ free) | Confirm pin availability during Phase B implementation. If we need more pins, fall back to repurposing TFT header pins. |
| **Cat6 over 2m picks up EMI from chamber heater / steppers** | Low | Lever switches are slow signals (filament insertion is mechanical event); EMI tolerance high. Shielded Cat6 if needed. |
| **D2F-01FL counterfeits from Amazon** | Medium | Order from DigiKey/Mouser (~$2 more per switch but genuine). Real D2Fs have "Omron" laser-etched. |
| **Counterfeit NTAGs (relabeled chips)** | High on AliExpress, low at reputable vendors | Buy from listings that explicitly say "100% NXP." If unsure, test one tag against OpenSpool's expected memory layout before bulk-tagging spools. |
| **Spoolman extra-fields not in installed version** | Low (Spoolman ≥0.18 has them) | Check version in Phase A pre-flight. Upgrade if needed. |
| **OpenTag3D vs OpenSpool tag format churn** | Medium (OpenTag3D finalizing 2025-2026, OpenPrintTag launched late 2025) | Phase C uses OpenSpool's current format. Migration path is well-supported by the community. |
| **Pre-gate sensor false triggers** (spool tug, filament drag) | Medium | HH already has debouncing. Position the lever to actuate only on insertion-direction motion. |
| **Pi UART contention** | Low | Pi has one UART on GPIO. Bluetooth disabled by default on MainsailOS. Verify nothing else uses it. |
| **MMU↔Spoolman pending-spool race** | Low | HH's existing timeout handles gracefully — assignment voids, user re-scans. |
| **Phase A measurement work isn't done** | High (this is the user's commitment) | Without per-spool PA measurement, Phase A's value drops to "Spoolman tracks temps" — still useful but not Bambu-AMS-equivalent. Plan a measurement session per active spool. |
| **INDX retrofit makes Phases B/C software work obsolete** | Medium-long-term (post-retrofit, evening's work) | Documented in §2 + per-phase "INDX survival" subsections. Hardware investment survives entirely. |

## 9. Testing strategy

| Phase | Layer | Coverage |
|---|---|---|
| A | L2 macro_refcheck | New macro `_KBOBINE` references resolve; PRINT_START's new `SET_PRESSURE_ADVANCE` block has valid params |
| A | L3 klippy parse | KBobine include loads cleanly |
| A | L5 structural | `_KBOBINE` has description; `current_settings` reference resolves |
| A | Manual | Set spool A's PA=0.04, B's PA=0.06 in Spoolman; tool change A→B mid-print; verify `SET_PRESSURE_ADVANCE` fires with 0.06 |
| A | Slicer test | Slice with new generic profile; verify no PA setting baked into output gcode (would conflict with KBobine) |
| B | L3 klippy parse | Validates new pin assignments + `[mmu_sensors]` config still parses |
| B | Manual | `MMU_TEST_SENSORS` on Pi after install; insert filament into each gate, confirm pin reads correctly |
| B | Manual | `MMU_GATE_MAP NEXT_SPOOLID=N` + insert filament → gate map updates automatically |
| C | L3 klippy parse | No Klipper changes from nfc2klipper itself |
| C | Manual | Tag write workflow verified; scan → MMU_GATE_MAP NEXT_SPOOLID fires; insert → gate auto-assigns |
| C | Manual | End-to-end: 6 spools registered in Spoolman, 6 tags written, 6 scan-and-insert flows succeed |

Per-phase PR review via `pr-review-toolkit:review-pr` before merge.

## 10. Future work

- **Per-rewinder OpenSpool nodes** (deferred): if the centralized-reader-with-pre-gate-sensors workflow proves annoying in practice, revisit per-rewinder ESP32+PN532 nodes with MQTT. Community consensus says it's not worth the antenna detuning + cabling complexity; revisit only after lived experience.
- **OpenTag3D / OpenPrintTag migration** when standards finalize. nfc2klipper expected to support both. Re-flashing tags is the migration cost.
- **Chamber VOC sensor** (per chamber-control spec §10) — fits naturally on this system but is a separate hardware addition.
- **HH `MMU_CHECK_GATES` integration** — auto-fill gate map from Spoolman state at print start; HH already supports it; verify it's wired up after Phase C.
- **INDX retrofit** — covered in §2. When INDX-on-Voron arrives, Phases B/C macro layer rewrites; Phase A passes through unchanged.

## 11. Anti-criteria

- No fork of Happy-Hare. Use HH's existing macros + extension points only.
- No fork of Spoolman. Use stock + extra-fields capability.
- No fork of KBobine. Configure via existing knobs.
- No fork of nfc2klipper.
- No fork of OrcaSlicer.
- No new Klipper Python extensions beyond what KBobine ships.
- No new MMU board. SKR Z spare GPIO + Ethernet cable run is the wiring path.
- No new USB MCU. PN532 connects via UART to the Pi.
- No edits to mainsail.cfg or any Pi-side symlink target (per [[feedback-mainsail-cfg-symlink-trap]]).
- No replacement of the existing Spoolman server (already running on Ben's LAN).

## 12. References

- Happy-Hare Spoolman Support wiki: <https://github.com/moggieuk/Happy-Hare/wiki/Spoolman-Support>
- HH issue #853 (INDX support feature request, needs-triage): <https://github.com/moggieuk/Happy-Hare/issues/853>
- nfc2klipper: <https://github.com/bofh69/nfc2klipper>
- KBobine: <https://github.com/fbeauKmi/kbobine_filament_settings>
- OpenSpool: <https://github.com/spuder/OpenSpool>
- OpenTag3D: <https://opentag3d.info/>
- OpenPrintTag (Prusa/Prusament): <https://openprinttag.org/>
- Voron PN532 holder: <https://www.printables.com/model/798929-elechouse-pn532-v3-nfc-holder-for-voron-for-spoolm>
- k1-801 ERCF v2 Filament Block with built-in pre-gate sensor: <https://www.printables.com/model/1188732-ercf-v2-filament-block-with-builtin-pre-gate-senso>
- juliusjj25 ERCF Pregate Sensors: <https://github.com/juliusjj25/ERCF-Pregate-Sensors>
- igiannakas standalone lever-switch sensor: <https://github.com/igiannakas/Standalone-lever-switch-filament-sensor>
- Bondtech INDX product page: <https://www.bondtech.se/indx-by-bondtech/>
- Memory entries: [[mcu-usb-reenumerate-race]], [[feedback-mainsail-cfg-symlink-trap]], [[orcaslicer-settings-path]], [[indx-retrofit-intent]]
