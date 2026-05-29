# `calibrate-filament` skill — design

Interactive Claude Code skill that walks Ben through recalibrating a filament's print parameters and records the result. Addresses the lightweight core of [#79](https://github.com/bjdeng/voron-2-611/issues/79).

**Motivation:** The move to the Galileo G2E extruder (9:1 geared) invalidated the pre-swap pressure-advance values on every filament — PA is the most extruder-dependent parameter, and `print-profiles.md:57` already documents that the 9:1 ratio *amplifies* per-line PA sensitivity. Flow can shift modestly; temp is mostly hotend/filament-driven and likely stable. So all filaments need a recal pass, and Ben wants a repeatable guided workflow instead of a one-off manual slog.

**Restart impact:** The skill itself never deploys or restarts Klipper. The only Klipper-config-touching path (rotation_distance, normally skipped — see Step 0) goes through the normal repo → PR → `/deploy-to-pi` flow (a `[extruder]` change = **FIRMWARE_RESTART**).

**Related:**
- [#79](https://github.com/bjdeng/voron-2-611/issues/79) — parent issue (this is its v1 core; community-data + Spoolman legs deferred).
- [#32](https://github.com/bjdeng/voron-2-611/issues/32) / `docs/superpowers/specs/2026-05-21-auto-calibration-endoscope-design.md` — the *automated* webcam version. Different project; not this.
- [#72](https://github.com/bjdeng/voron-2-611/issues/72) — MMU spool tracking + Spoolman/RFID. The log frontmatter (below) is named to map onto its extra-fields later.
- `docs/slicer-templates/orcaslicer.md` — the manual workflow this skill operationalizes; profile cascade in `docs/print-profiles.md`.
- `.claude/skills/deploy-to-pi/`, `.claude/skills/sync-from-pi/` — the SKILL.md + helper-script pattern this follows.

---

## 1. Goal

A skill, invoked as `/calibrate-filament` or by saying "calibrate Inland PLA", that runs an interactive cascade — temp (verify) → flow → Adaptive PA — for one filament, writes the scalar results into the OrcaSlicer filament profile, and logs everything to a per-filament record in the repo. Resume-aware and step-addressable ("just redo PA for Inland PLA").

## 2. Scope

**In scope (v1):**
- Interactive cascade for a single filament at **brand + material** granularity (e.g. "Inland PLA"), matching the existing OrcaSlicer profile granularity (colors already collapsed).
- OrcaSlicer filament-profile JSON is the operational source of truth for calibrated values. The repo holds a per-filament markdown log (history).
- Hybrid write-back: skill auto-edits scalar fields; Adaptive PA model is guided-paste.
- Objective flow via the existing Klipper `FLOW_MULTIPLIER_CALIBRATION` macro.

**Out of scope (deferred):**
- Per-brand community starting-point data (#79's research leg).
- Spoolman / NFC / RFID per-physical-spool write-back (#72; design is RFID-*aware*, not RFID-*integrated*).
- The automated webcam/endoscope version (#32).
- Bulk auto-running all filaments unattended — every cal needs a physical print + human measurement.

## 3. Data model

- **Granularity:** brand + material. One OrcaSlicer profile, one log record.
- **Operational store:** the OrcaSlicer filament profile JSON under `~/Library/Application Support/OrcaSlicer/user` (Ben's Mac; see [[orcaslicer-settings-path]]). This is what slicing actually reads.
- **History store:** `memory/filaments/<brand>-<material>.md` in this repo.
- **Future:** values will eventually flow to Spoolman/RFID per #72; the log frontmatter field names are chosen to map cleanly then. RFID is the eventual source of truth; OrcaSlicer is the bootstrap layer.

## 4. Components

### 4.1 `.claude/skills/calibrate-filament/SKILL.md`
The interactive playbook Claude follows. Frontmatter `name` + `description` tuned for triggering on "calibrate <filament>" / `/calibrate-filament`. Sections: When to use / The cascade (§5) / Log template (§6) / How to run / What it does NOT do / Related. Authored via the skill-creation skill at implementation time (see §10).

### 4.2 `scripts/orca_profile_edit.py`
The one piece of new code — the genuinely risky operation (editing Ben's live OrcaSlicer profiles). Subcommands:

- `--find "<name>"` → resolve the profile JSON path under the OrcaSlicer user dir. Error on 0 matches or >1 ambiguous match (don't guess).
- `--get <key>` → print the current value (so the skill can show before/after).
- `--set <key>=<value>` → apply a scalar edit:
  - **Refuse if OrcaSlicer is running** (`pgrep -i orcaslicer`) — prevents Orca overwriting the edit on exit.
  - Write a `<file>.bak` first.
  - Atomic write (temp file in same dir + `os.replace`).
  - Re-parse the result to confirm valid JSON; restore from `.bak` and error if not.
  - Print `old → new`.
  - Only scalar string/number fields. Never touches the Adaptive PA model field.

The OrcaSlicer settings path is configurable (constant/env) so the test can point at a fixture dir.

### 4.3 `memory/filaments/<brand>-<material>.md`
Per-filament log record. Claude manages it directly with Write/Edit — low-risk, version-controlled, no script needed (YAGNI). Format in §6.

## 5. The cascade

Each step is labeled and resume-able; state is read from the log record. Ben can run the whole cascade or jump to one step.

**Step 0 — `rotation_distance` (filament-agnostic, normally skipped).**
`rotation_distance: 48.033` was calibrated by Ben at Galileo bring-up — it is sound, not theoretical ([[galileo-rotation-distance-calibrated]]). The skill therefore treats it as already verified (`rotation_distance_verified: galileo-bring-up`) and **skips by default**. It offers an optional manual re-check (heat, mark, `G1 E100 F60`, measure) only if Ben suspects drift. If a re-check ever finds it off, the skill *proposes* the corrected value but does not apply it — Ben takes the `config/` edit through PR → `/deploy-to-pi` (FIRMWARE_RESTART).

**Step 1 — Temp (verify-first).**
Default: confirm the profile's current `nozzle_temperature` still prints clean (the Dragon hotend likely didn't change with the extruder swap, so temp is probably stable). If Ben wants a full tower, the skill guides OrcaSlicer's temp tower; Ben picks the band; skill writes `nozzle_temperature` + `nozzle_temperature_initial_layer` via the helper. Kept in the cascade because it gates flow/PA, but lowest-priority in the Galileo context.

**Step 2 — Flow (objective, Klipper macro).**
Skill checks the printer is idle (`print_stats.state == standby`), then over SSH/Moonraker (reusing deploy-to-pi's connection patterns) runs `FLOW_MULTIPLIER_CALIBRATION` seeded with the profile's current flow ratio as the extrusion multiplier. Ben prints the thin-wall shell and measures it with calipers. Skill runs `COMPUTE_FLOW_MULTIPLIER MEASURED_THICKNESS=…`, reads the new ratio from the Moonraker gcode response, and writes `filament_flow_ratio` via the helper.

**Step 3 — Adaptive PA.**
Skill guides Ben through OrcaSlicer's Adaptive PA calibration (the flow × acceleration grid). Ben builds the model in Orca. Skill captures the measurements block into the log and guides the paste into the profile's adaptive-PA field, plus `enable_pressure_advance` + the fallback/median PA value (the guided, non-auto half of the hybrid write-back).

**Close-out.**
Skill updates `memory/filaments/<brand>-<material>.md` (new values + date + observations, appended to history) and reminds Ben to commit. It does not commit or deploy on its own.

## 6. Log format

`memory/filaments/<brand>-<material>.md` — RFID-aware YAML frontmatter (field names map onto future Spoolman/NFC extra-fields), markdown body for dated notes + history.

```yaml
---
brand: Inland
material: PLA
orca_profile: "Inland PLA"          # profile the skill edits
last_calibrated: 2026-05-28
nozzle_temp: 210
nozzle_temp_initial_layer: 215
flow_ratio: 0.98
pa_mode: adaptive                    # adaptive | static
pa_fallback: 0.030                   # median/fallback PA value
rotation_distance_verified: galileo-bring-up
---
```

Body: per-step dated notes (what was measured, observations like "stringy at 215 → dropped to 210"), and a short history list so re-cals append rather than overwrite. Grep-able by brand/material.

## 7. Safety / restraint

- **OrcaSlicer-running guard** in the helper prevents the "Orca overwrites your edit on exit" footgun.
- **Idle gate** before driving the Pi (`print_stats.state == standby`).
- **No autonomous commit or deploy.** Same restraint as `sync-from-pi`. rotation_distance changes (rare) route through the normal PR → deploy flow.
- **Resume-aware:** re-running reads the log and offers to resume at the first incomplete step.
- **`.bak` + atomic write + re-parse** on every JSON edit; restore on parse failure.

## 8. Testing

`tests/test_orca_profile_edit.py` (L4 pytest) against a fixture profile JSON:
- `--find` resolves a unique match; errors on zero / ambiguous matches.
- `--get` / `--set` round-trip a scalar.
- Atomic write leaves no partial file on simulated failure.
- Refuses when OrcaSlicer "running" (mocked `pgrep`).
- Refuses on missing profile / missing key.
- `.bak` is created; output re-parses as valid JSON.

The SKILL.md playbook itself is prose (not unit-tested), consistent with the existing skills — the dangerous write path is what gets the test.

## 9. Resolved decisions (from brainstorming)

| Question | Decision |
|---|---|
| Granularity / source of truth | Brand + material; OrcaSlicer JSON now, RFID later (#72) |
| Write-back mechanism | Hybrid — auto-edit scalars, guided-paste Adaptive PA |
| Flow method | Objective Klipper caliper macro (`FLOW_MULTIPLIER_CALIBRATION`) |
| Skill structure | SKILL.md playbook + one helper script (Approach B) |
| rotation_distance | Already verified at Galileo bring-up; skip by default |

## 10. Implementation notes

- Author `SKILL.md` via the skill-creation skill (`superpowers:writing-skills` by default; `skill-creator` if description-triggering evals are wanted) so the `description` triggers reliably and structure follows convention.
- Model `orca_profile_edit.py` CLI + error handling on the existing `scripts/` style.
- Add `memory/filaments/` with a `.gitkeep` or the first real record so the dir exists.
- Cross-reference the new skill from `docs/slicer-templates/orcaslicer.md` (replace the "manual workflow until #79 ships" note) and from CLAUDE.md's skill/macro context.
