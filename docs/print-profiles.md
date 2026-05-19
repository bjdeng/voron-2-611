# Print process profiles for Voron 2.611

The OrcaSlicer process-profile spec for this machine, audited against authoritative sources on 2026-05-19. Companion to [`docs/slicer-templates/orcaslicer.md`](./slicer-templates/orcaslicer.md) (the start/end gcode contract) and `CLAUDE.md` (hardware context).

## Optimization rubric

Three axes of optimization + one constraint floor:

| | Type | Meaning |
|---|---|---|
| **Speed** | Optimization axis | Minimize total print time |
| **Strength** | Optimization axis | Maximize mechanical properties |
| **Quality** | Optimization axis | Maximize surface finish + dimensional accuracy |
| **Reliability** | **Floor (non-negotiable)** | "This print won't fail mid-way." First-layer adhesion, min layer time, bridge integrity |

Every setting in every profile is tagged with one of:

| Tag | Meaning |
|---|---|
| `[speed]` / `[strength]` / `[quality]` | Profile-axis optimization (value varies per profile) |
| `[reliability]` | Constraint floor (all 3 profiles converge on same value) |
| `[new-default]` | Better baseline than OrcaSlicer/Voron-common default for this hardware (all 3 converge) |
| `[default-inherits]` | OrcaSlicer/Voron-common default is correct (no override) |

## The set: 3 profiles

| Name | Use case | Tree of design intent |
|---|---|---|
| **Speed** (0.20mm) | Daily driver, non-load-bearing | "Print done fast, looks fine" — 3 walls, 15% cubic |
| **Strength** (0.20mm) | Load-bearing functional parts | "Survives use" — 4 walls, 30% cubic, 5/4 shells |
| **Quality** (0.12mm) | Cosmetic / detailed display | "Looks immaculate" — slower outer, ironing, tree support |

All inherit from system base `0.20mm Standard @Voron` (which inherits from `fdm_process_voron_common`), with each profile setting `compatibility_condition: "printer_model==\"Voron v2.611\""`.

---

## Settings — full annotated spec

Cross-setting interactions are listed in a single map at the end of this doc; individual rows don't repeat them. Sources cited in the rationale column.

### Layer & shells

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `layer_height` | 0.20 | 0.20 | 0.12 | [speed]/[quality] | Profile axis. Quality doubles vertical resolution at ~1.6× the time |
| `initial_layer_print_height` | 0.20 | 0.20 | 0.20 | [reliability] | Forgiving on textured PEI; Eddy tap handles squish accurately |
| `wall_loops` | 3 | 4 | 3 | [speed]/[strength]/[quality] | Strength gets 4th wall for load distribution; Quality 3 keeps detail sharp |
| `top_shell_layers` | 4 | 4 | 6 | [reliability]/[quality] | `top_shell_thickness: 0.8` floor auto-upgrades Quality to 7 layers at 0.12mm |
| `top_shell_thickness` | 0.8 | 0.8 | 0.8 | [reliability] | Floor. Whichever yields more layers wins — auto-upgrades Quality to 7 layers |
| `bottom_shell_layers` | 3 | 5 | 4 | [reliability]/[strength] | Strength 5 for floor stiffness on load-bearing parts |
| `bottom_shell_thickness` | 0 | 0 | 0 | [reliability] | Layers control; thickness=0 makes layer-count the source of truth |

### Wall settings

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `wall_generator` | classic | classic | classic | [new-default] | Arachne fights Galileo 9:1 PA (per-line PA changes amplify under high gear ratio). Voron community standard. |
| `wall_sequence` | inner-outer-inner | inner-outer-inner | inner-outer-inner | [new-default] | Best finish + dim accuracy at ≥3 walls. OrcaSlicer default Inner/Outer; this is the upgrade. |
| `only_one_wall_top` | 1 | 1 | 1 | [new-default] | Single top wall = cleaner top fill. OrcaSlicer default off. |
| `only_one_wall_first_layer` | 0 | 0 | 0 | [default-inherits] | First-layer adhesion needs full wall stack |
| `precise_outer_wall` | 0 | 0 | 0 | [reliability] | Force-disabled by inner-outer-inner sequence; explicit to avoid future confusion |
| `precise_z_height` | 0 | 0 | 0 | [default-inherits] | Experimental; Eddy gives Z accuracy already |
| `detect_overhang_wall` | 1 | 1 | 1 | [reliability] | Required for the overhang-speed ladder |
| `detect_thin_wall` | 0 | 0 | 0 | [default-inherits] | OrcaSlicer tooltip warns low quality (open-loop perimeters) |
| `staggered_inner_seams` | 1 | 1 | 1 | [new-default] | Zigzags inner-wall seams across layers. Free strength + watertightness win. OrcaSlicer default off. |

### Line widths

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `line_width` | 0.42 | 0.42 | 0.42 | [new-default] | 105% nozzle, community-tuned. Voron base 0.40. |
| `inner_wall_line_width` | 0.45 | 0.45 | 0.45 | [new-default] | Wider inner walls bond stronger to infill |
| `outer_wall_line_width` | 0.42 | 0.42 | **0.40** | [new-default]/[quality] | Quality narrower = sharper detail. May invalidate PA cal on Quality — re-tune. |
| `top_surface_line_width` | 0.40 | 0.40 | 0.40 | [reliability] | Narrower = smoother top finish |
| `internal_solid_infill_line_width` | 0.45 | 0.45 | 0.45 | [new-default] | Voron Prusa value (system base 0.40 is too narrow) |
| `initial_layer_line_width` | 0.50 | 0.50 | 0.50 | [reliability] | 125% nozzle for best adhesion |
| `sparse_infill_line_width` | 0.45 | 0.45 | 0.45 | [default-inherits] | Voron base |
| `support_line_width` | 0.40 | 0.40 | 0.40 | [default-inherits] | 1× nozzle |

### Infill

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `sparse_infill_density` | 15% | 30% | 15% | [strength]/[speed]/[quality] | Walls dominate strength; infill = compressive only |
| `sparse_infill_pattern` | cubic | cubic | gyroid | [speed]/[strength]/[quality] | Cubic 10-15% faster; gyroid wins on small Quality parts (shear) |
| `infill_direction` | 45° | 45° | 45° | [default-inherits] | Offsets from 0/90° walls |
| `sparse_infill_anchor` | 2 mm | 2 mm | 2 mm | [new-default] | Pin absolute |
| `sparse_infill_anchor_max` | 12 mm | 12 mm | 12 mm | [new-default] | OrcaSlicer default 20 mm scars outer walls |
| `infill_combination` | 0 | 0 | 0 | [default-inherits] | Not worth at 0.12/0.20 layer |
| `internal_solid_infill_pattern` | monotonic | monotonic | monotonic | [default-inherits] | Universal best for strength |
| `top_surface_pattern` | monotonicline | monotonicline | monotonic | [default-inherits]/[quality] | Quality pairs better with ironing |
| `bottom_surface_pattern` | monotonic | monotonic | monotonic | [default-inherits] | Voron base |
| `filter_out_gap_fill` | 0.5 | 0.5 | 0.2 | [reliability]/[quality] | Drops micro-segments that cause Benchy-hull-line PA hunting |
| `minimum_sparse_infill_area` | 15 mm² | 15 mm² | 15 mm² | [default-inherits] | Small islands → solid |
| `gap_fill_target` | nowhere | topbottom | topbottom | [speed] | Speed disables to avoid Benchy-hull-line PA hunting; Strength/Quality use Ellis's top/bottom-only setting |
| `gap_infill_speed` | 60 | 60 | 60 | [reliability] | Override Voron-common 100 — Galileo PA tracking |
| `infill_wall_overlap` | 15% | 15% | 15% | [default-inherits] | Override Voron-common 25% — over-extrudes with gap_fill on |
| `bridge_density` | 100% | 100% | 100% | [default-inherits] | External bridges solid |
| `internal_bridge_density` | 100% | 100% | 90% | [default-inherits]/[quality] | Quality 90% prevents pillowing under 6 top shells |
| `detect_narrow_internal_solid_infill` | 1 | 1 | 1 | [default-inherits] | Auto-concentric on narrow regions |
| `ensure_vertical_shell_thickness` | ensure_critical_only | ensure_all | ensure_all | [speed]/[strength]/[quality] | Strength/Quality fill sloped shells |
| `small_area_infill_flow_compensation` | 1 | 1 | 1 | [new-default] | Compensates under-extrusion on accel-limited small segments. OrcaSlicer default off in your version. |
| `small_area_infill_flow_compensation_model` | (default) | (default) | (default) | [default-inherits] | Use OrcaSlicer's shipped curve |

### Speed (mm/s)

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `outer_wall_speed` | 200 | 180 | 100 | [speed]/[strength]/[quality] | Small parts accel-limited anyway |
| `inner_wall_speed` | 240 | 240 | 200 | [new-default]/[quality] | Under volumetric ceiling |
| `top_surface_speed` | 120 | 120 | 100 | [new-default]/[quality] | Last visible pass |
| `bottom_surface_speed` | 120 | 120 | 100 | [new-default]/[quality] | Hidden by textured PEI — match top |
| `internal_solid_infill_speed` | 240 | 240 | 200 | [new-default]/[quality] | Matches inner wall |
| `sparse_infill_speed` | 240 | 240 | 200 | [new-default]/[quality] | Open-air, no surface quality cost |
| `gap_infill_speed` | 60 | 60 | 60 | [reliability] | (See Infill section) |
| `support_speed` | 150 | 150 | 150 | [new-default] | (canonical row in Support section) |
| `support_interface_speed` | 80 | 80 | 80 | [new-default] | (canonical row in Support section) |
| `bridge_speed` | 25 | 20 | 20 | [speed] | Speed bumps to Voron-stock 25; Strength/Quality at safer 20 (Ellis 20-40). Don't go below 20 |
| `internal_bridge_speed` | 150 | 100 | 80 | [speed]/[quality] | Hidden by top shells — push fast |
| `ironing_speed` | (off) | (off) | 30 | [default-inherits] | Quality only; Voron base |
| `initial_layer_speed` | 50 | 50 | 30 | [reliability]/[quality] | First-layer adhesion |
| `initial_layer_infill_speed` | 105 | 105 | 80 | [default-inherits]/[quality] | Voron base |
| `initial_layer_travel_speed` | 100% | 100% | 100% | [default-inherits] | Multiplier of travel_speed |
| `travel_speed` | 450 | 450 | 450 | [new-default] | Matches Klipper `max_velocity: 450`. Bump after belt/shaper retune (#25) + TEST_SPEED |
| `skirt_speed` | 50 | 50 | 50 | [reliability] | Matches initial layer (though skirt is off) |

### Overhang speed ladder

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `enable_overhang_speed` | 1 | 1 | 1 | [reliability] | Master toggle |
| `overhang_1_4_speed` (10-25%) | 80% | 80% | 70% | [default-inherits]/[quality] | Mild slowdown for fan ramp |
| `overhang_2_4_speed` (25-50%) | 50 | 50 | 30 | [default-inherits]/[quality] | Absolute mm/s; bridge territory |
| `overhang_3_4_speed` (50-75%) | 30 | 30 | 20 | [default-inherits]/[quality] | Scary tier |
| `overhang_4_4_speed` (75-100%) | 10 | 10 | 10 | [reliability] | Mini-bridge |
| `overhang_speed_classic` | 0 | 0 | 0 | [new-default] | Use newer arc-aware detector |
| `overhang_threshold_participating_cooling` | 95% | 95% | 95% | [default-inherits] | Wall-line slicing threshold |

### Acceleration (mm/s²)

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `default_acceleration` | 5000 | 5000 | 4000 | [new-default]/[quality] | Below mzv smoothing threshold |
| `outer_wall_acceleration` | 3000 | 4000 | 2500 | [speed]/[strength]/[quality] | Voron-community baseline 3000 |
| `inner_wall_acceleration` | 5400 | 5400 | 5400 | [default-inherits] | All converge |
| `top_surface_acceleration` | 5000 | 5000 | 3000 | [new-default]/[quality] | Quality lower for ringing visibility on flattest plane |
| `bottom_surface_acceleration` | 5000 | 5000 | 3000 | [new-default]/[quality] | Match top |
| `bridge_acceleration` | 3000 | 2000 | 2000 | [speed] | Speed at Voron Prusa baseline 3000; Strength/Quality reduce to 2000 to limit anchor pullout |
| `sparse_infill_acceleration` | 5000 | 5000 | 4000 | [new-default]/[quality] | Reach 240 mm/s in 50mm span |
| `internal_solid_infill_acceleration` | 5000 | 5000 | 4000 | [new-default]/[quality] | Same |
| `travel_acceleration` | 10000 | 10000 | 10000 | [new-default] | Equals Klipper `max_accel: 10000` |
| `initial_layer_acceleration` | 500 | 500 | 500 | [reliability] | Bed adhesion |

### Jerk (mm/s — Klipper translates to SCV; effective cap is SCV=5)

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `default_jerk` | 9 | 9 | 9 | [default-inherits] | Voron base; Klipper SCV is real cap |
| `outer_wall_jerk` | 7 | 7 | 5 | [default-inherits]/[quality] | Quality 5 = Klipper SCV exactly (no speculative cornering) |
| `inner_wall_jerk` | 7 | 7 | 7 | [default-inherits] | Voron base |
| `top_surface_jerk` | 9 | 9 | 9 | [default-inherits] | Monotonic-line, no sharp corners |
| `infill_jerk` | 12 | 12 | 12 | [default-inherits] | Hidden |
| `initial_layer_jerk` | 9 | 9 | 9 | [default-inherits] | Accel=500 makes jerk irrelevant |
| `travel_jerk` | 12 | 12 | 12 | [default-inherits] | Voron base |

### Bridging

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `bridge_flow` | 0.95 | 0.92 | 0.90 | [speed]/[strength]/[quality] | Voron stock 0.95; Ellis 0.90-0.95 — per-profile across the range |
| `internal_bridge_flow` | 1.0 | 1.0 | 1.0 | [default-inherits] | Full flow to seal over sparse infill |
| `thick_bridges` | 0 | 0 | 0 | [reliability] | Smoother visual surface; flow=0.92 carries enough |
| `thick_internal_bridges` | 1 | 1 | 1 | [reliability] | Internal bridges hide under top shells |
| `bridge_no_support` | 0 | 0 | 0 | [default-inherits] | Auto-detect handles short bridges |
| `max_bridge_length` | 0 | 0 | 0 | [default-inherits] | Unlimited |
| `bridge_angle` | 0 | 0 | 0 | [default-inherits] | Auto = shortest span |
| `internal_bridge_angle` | 0 | 0 | 0 | [default-inherits] | Auto |

### Cooling (process-scope — most cooling is filament-scope)

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `slow_down_for_layer_cooling` | 1 | 1 | 1 | [reliability] | Always on |
| `fan_speedup_time` | 0.5 | 0.5 | 1.0 | [quality] | Quality 1.0s for crisp overhang onset |
| `fan_speedup_overhangs` | 1 | 1 | 1 | [quality] | Restricts lookahead to overhangs |
| `full_fan_speed_layer` | 4 | 4 | 3 | [quality] | Quality ramps fan in 1 layer sooner; linear ramp from close_fan_first_x to N |

Note: `slow_down_layer_time`, `slow_down_min_speed`, `fan_cooling_layer_time`, `close_fan_the_first_x_layers`, `overhang_fan_threshold`, `overhang_fan_speed`, `dont_slow_down_outer_wall`, `reduce_fan_stop_start_freq`, `additional_cooling_fan_speed` are **filament-scope** (`coFloats`/`coInts` per-extruder arrays) in OrcaSlicer's data model. They live in filament profiles, not process. See [`docs/slicer-templates/orcaslicer.md`](./slicer-templates/orcaslicer.md) and the filament audit (separate work).

### Travel & retraction

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `travel_speed` | 450 | 450 | 450 | [new-default] | (Speed section) |
| `travel_acceleration` | 10000 | 10000 | 10000 | [new-default] | (Accel section) |
| `reduce_infill_retraction` | 1 | 1 | 1 | [default-inherits] | Direct-drive primes fast; infill stringing invisible |
| `avoid_crossing_walls` | 0 | 0 | 1 | [quality] | Quality only — eliminates travel scarring |
| `avoid_crossing_walls_max_detour` | 0 | 0 | 0 | [default-inherits] | No cap; falls back to crossing when forced |
| `reduce_crossing_wall` | 0 | 0 | 0 | [default-inherits] | Redundant with hard toggle |
| `max_travel_detour_distance` | 0 | 0 | 0 | [default-inherits] | None |
| `ramping_lift` | 0 | 0 | 0 | [reliability] | Defer until Eddy interaction validated |
| `retract_on_layer_change` | 1 | 1 | 1 | [reliability] | Cheap insurance |
| `retract_lift_below` | 0 | 0 | 0 | [reliability] | Lift always (0.2mm cost trivial) |
| `z_hop` | 0.2 | 0.2 | 0.2 | [reliability] | Ellis: >0.3 strings |
| `z_hop_types` | Normal Lift | Normal Lift | Normal Lift | [reliability] | **Override current "Auto Lift" — Bowden-era optimization** |
| `retract_before_wipe` | 0% | 0% | 0% | [default-inherits-from-machine] | Override-from-machine; document for resync survival |
| `wipe` | 1 | 1 | 1 | [reliability] | Major stringing reduction direct-drive |
| `wipe_distance` | 2 mm | 2 mm | 2 mm | [reliability] | Enough scrub; doesn't drag into next seam |
| `wipe_speed` | 80% | 80% | 80% | [default-inherits] | Of travel_speed |
| `wipe_on_loops` | 0 | 0 | 0 | [reliability] | Not needed with aligned seam + Filametrix |
| `role_based_wipe_speed` | 1 | 1 | 1 | [reliability] | Syncs wipe to feature speed |
| `pre_start_fan_time` | 0 | 0 | 0 | [default-inherits] | Not retraction-related |
| `standby_temperature_delta` | -5 | -5 | -5 | [default-inherits] | Stock Voron; harmless with Filametrix |

### Seam

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `seam_position` | aligned | aligned | aligned | [reliability] | Voron stock; scarf operates on aligned (when enabled) |
| `seam_gap` | 10% | 10% | 5% | [quality] | Quality tighter — calibrated PA makes bulge small |
| `staggered_inner_seams` | 1 | 1 | 1 | [new-default] | (Wall section) |
| `seam_slope_*` (scarf) | (off) | (off) | (off) | [parked] | Parked: [#75] — scarf seam tuning project |

### Support / Brim / Skirt / Raft

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `enable_support` | 0 | 0 | 0 | [default-inherits] | Per-print decision |
| `support_type` | normal(auto) | normal(auto) | tree(auto) | [quality] | Quality tree for cosmetic — fewer contact points |
| `support_style` | default | default | organic | [quality] | **Unified: no `snug`** — keep supports relaxed for clean removal |
| `support_threshold_angle` | 45 | 45 | 45 | [new-default] | **Unified permissive** (was 40/45/30); trust Voron overhang |
| `support_on_build_plate_only` | 0 | 0 | 1 | [quality] | Quality: no internal scars (geometric, not "snugness") |
| `support_critical_regions_only` | 0 | 0 | 0 | [default-inherits] | Default fine |
| `support_remove_small_overhang` | 1 | 1 | 1 | [reliability] | Skip vestigial |
| `support_filament` | 0 | 0 | 0 | [default-inherits] | All ERCF gates PLA today |
| `support_interface_filament` | 0 | 0 | 0 | [default-inherits] | Future: dedicate PETG gate for ABS support |
| `support_top_z_distance` | 0.2 | 0.2 | 0.2 | [default-inherits] | 1× layer height (scale at 0.12) |
| `support_bottom_z_distance` | 0.2 | 0.2 | 0.2 | [new-default] | Make explicit; Voron leaves unset |
| `support_base_pattern` | default | default | default | [default-inherits] | Adaptive per slice |
| `support_base_pattern_spacing` | 2.5 | 2.5 | 2.5 | [default-inherits] | Voron standard |
| `support_speed` | 150 | 150 | 150 | [new-default] | **Unified**; supports are throwaway |
| `support_acceleration` | (inherit outer-wall) | (inherit outer-wall) | (inherit outer-wall) | [default-inherits] | Tied to outer-wall |
| `support_angle` | 0 | 0 | 0 | [default-inherits] | Auto-rotate per layer |
| `support_object_xy_distance` | 0.5 | 0.5 | 0.5 | [new-default] | **Unified**; clearance for clean removal across the board |
| `support_object_first_layer_gap` | 0.3 | 0.3 | 0.3 | [new-default] | **Unified**; clean bed edge across the board |
| `support_interface_pattern` | rectilinear | rectilinear | rectilinear | [new-default] | **Unified**; predictable scar texture |
| `support_interface_top_layers` | 2 | 2 | 2 | [new-default] | **Unified**; was 2/3/3 |
| `support_interface_bottom_layers` | 2 | 2 | 2 | [default-inherits] | Voron base |
| `support_interface_spacing` | 0.5 | 0.5 | 0.5 | [new-default] | **Unified relaxed** (was 0.5/0.2/0); not too snug |
| `support_interface_speed` | 80 | 80 | 80 | [new-default] | **Unified** |
| `support_line_width` | 0.4 | 0.4 | 0.4 | [default-inherits] | 1× nozzle |
| `tree_support_branch_angle` | 45 | 45 | 45 | [default-inherits] | **Unified to default**; not too snug |
| `tree_support_branch_distance` | 5 | 5 | 5 | [default-inherits] | **Unified to default** |
| `tree_support_branch_diameter` | 2 | 2 | 2 | [default-inherits] | **Unified to default** |
| `tree_support_branch_diameter_angle` | 5 | 5 | 5 | [default-inherits] | Default balanced |
| `tree_support_tip_diameter` | 0.8 | 0.8 | 0.8 | [default-inherits] | **Unified to default**; bigger tip, easier removal |
| `tree_support_with_infill` | 0 | 0 | 0 | [default-inherits] | Bloats slice time |
| `tree_support_adaptive_layer_height` | 1 | 1 | 1 | [reliability] | Faster, no quality cost |
| `tree_support_auto_brim` | 1 | 1 | 1 | [reliability] | Tall branches need brim |
| `tree_support_wall_count` | 0 | 0 | 0 | [default-inherits] | Fastest |
| **`brim_type`** | **no_brim** | **no_brim** | **no_brim** | [reliability] | Off by default; enable per-print when needed |
| `brim_width` | 8 | 8 | 8 | [new-default] | Populates when brim enabled per-print (warp resistance on functional parts) |
| `brim_object_gap` | 0.1 | 0.1 | 0.1 | [default-inherits] | Textured PEI tight gap |
| `enforce_support_brims` | 1 | 1 | 1 | [reliability] | Tall support stability |
| `skirt_loops` | 0 | 0 | 0 | [default-inherits] | Blobifier replaces skirt-prime |
| `skirt_height` | 1 | 1 | 1 | [default-inherits] | Unused |
| `skirt_distance` | 2 | 2 | 2 | [default-inherits] | Unused |
| `min_skirt_length` | 0 | 0 | 0 | [default-inherits] | Off |
| `draft_shield` | disabled | disabled | disabled | [default-inherits] | Enclosed chamber |
| `raft_layers` | 0 | 0 | 0 | [default-inherits] | Brim is the tool |
| `raft_first_layer_density` | 90% | 90% | 90% | [default-inherits] | Unused |
| `raft_first_layer_expansion` | 2 | 2 | 2 | [default-inherits] | Unused |
| `raft_contact_distance` | 0.1 | 0.1 | 0.1 | [default-inherits] | Unused |

### Ironing

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `ironing_type` | no ironing | no ironing | top_surfaces | [quality] | Quality only |
| `ironing_pattern` | concentric | concentric | concentric | [quality] | Avoids artifact transitions |
| `ironing_speed` | 30 | 30 | 30 | [default-inherits] | Voron base; don't push above 40 |
| `ironing_flow` | 10% | 10% | 10% | [default-inherits] | Voron base sweet spot |
| `ironing_spacing` | 0.15 | 0.15 | 0.10 | [quality] | Quality finer pattern |
| `ironing_inset` | 0.21 | 0.21 | 0.21 | [default-inherits] | Half line-width |
| `ironing_direction` | 45 | 45 | 45 | [default-inherits] | Matches infill direction |
| `ironing_angle` | -1 | -1 | -1 | [default-inherits] | Use ironing_direction |

### MMU / Multimaterial

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `single_extruder_multi_material` | 1 | 1 | 1 | [new-default] | ERCF requires |
| `multimaterial_print_with_filament_change_unload` | 1 | 1 | 1 | [new-default] | Required for ERCF flow |
| `machine_load_filament_time` | 30 | 30 | 30 | [default-inherits] | ETA only; HH owns reality |
| `machine_unload_filament_time` | 30 | 30 | 30 | [default-inherits] | ETA only |
| `machine_change_filament_gcode` | (empty) | (empty) | (empty) | [new-default] | HH inserts via post-process |
| `machine_filament_change_action` | Pause | Pause | Pause | [default-inherits] | UI label only |
| `machine_pause_gcode` | PAUSE | PAUSE | PAUSE | [default-inherits] | Upstream Mainsail PAUSE |

### Prime Tower (disabled; explicit values are defensive)

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `enable_prime_tower` | 0 | 0 | 0 | [new-default] | **CRITICAL** — Voron-common defaults to 1; must override |
| `prime_tower_width` | 0 | 0 | 0 | [new-default] | Defensive |
| `prime_volume` | 0 | 0 | 0 | [new-default] | Defensive |
| `prime_tower_brim_width` | -1 | -1 | -1 | [default-inherits] | Unused |
| `prime_tower_extra_rib_length` | 0 | 0 | 0 | [default-inherits] | Unused |
| `prime_tower_max_speed` | 90 | 90 | 90 | [default-inherits] | Unused |
| `prime_tower_rib_width` | 8 | 8 | 8 | [default-inherits] | Unused |
| `prime_tower_skip_points` | 0 | 0 | 0 | [default-inherits] | Unused |
| `prime_tower_lift_height` | -1 | -1 | -1 | [default-inherits] | Unused |
| `wipe_tower_no_sparse_layers` | 0 | 0 | 0 | [default-inherits] | Unused |
| `purge_in_prime_tower` | 0 | 0 | 0 | [new-default] (machine-side) | Critical guard; Blobifier owns purges |

### Compensation

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `elefant_foot_compensation` | 0.15 | 0.15 | 0.15 | [new-default] | Textured PEI squish; validate with chamfered cube |
| `xy_hole_compensation` | 0.03 | 0.03 | 0.03 | [new-default] | M3 tight-fit; validate with calipers |
| `xy_contour_compensation` | 0 | 0 | 0 | [default-inherits] | Within measurement noise |
| `print_flow_ratio` | 1.0 | 1.0 | 1.0 | [default-inherits] | Flow tuning is filament-side |

### Advanced

| Setting | Speed | Strength | Quality | Tag | Rationale |
|---|---|---|---|---|---|
| `resolution` | 0.012 | 0.012 | 0.008 | [quality] | Quality finer for smoother curves |
| `gcode_label_objects` | klipper | klipper | klipper | [new-default] | Mainsail per-object cancel |
| `gcode_add_line_number` | 0 | 0 | 0 | [default-inherits] | Bloats gcode |
| `filename_format` | (Voron base) | (Voron base) | (Voron base) | [default-inherits] | Sensible |
| `print_settings_id` | "Voron2.611 Speed" | "Voron2.611 Strength" | "Voron2.611 Quality" | [new-default] | One per profile |
| `compatibility_condition` | `printer_model=="Voron v2.611"` | same | same | [new-default] | Locks profile to this machine |
| `spiral_mode` | 0 | 0 | 0 | [default-inherits] | Incompatible with MMU |
| `timelapse_type` | none | none | none | [default-inherits] | Webcam unplugged ([#27]) |
| `emit_machine_limits_to_gcode` | 0 | 0 | 0 | [new-default] | Klipper enforces |
| `machine_limits_usage` | ignore | ignore | ignore | [new-default] | Trust Klipper |
| `arc_fitting` | 1 | 1 | 1 | [new-default] | Klipper `[gcode_arcs]` already enabled via `config/macros/calibrate_flow.cfg` (Frix_x v1.6 bundles it at `resolution: 0.1`). Closes [#76]. |
| `support_chamber_temp_control` | 0 | 0 | 0 | [default-inherits] | Chamber is Klipper-side |
| `emit_thumbnails_to_gcode` | 1 | 1 | 1 | [new-default] | Mainsail print preview |
| `thumbnails` | `32x32/PNG, 400x300/PNG` | same | same | [new-default] | Mainsail format |
| `slicing_mode` | regular | regular | regular | [default-inherits] | Even-odd is for airplanes |
| `print_extrusion_multiplier` | 1.0 | 1.0 | 1.0 | [default-inherits] | Flow tuning is filament-side |

### Machine-side limits (advisory only when `gcode_flavor: klipper`)

| Setting | Value | Tag | Rationale |
|---|---|---|---|
| `enable_machine_limits` | 0 | [default-inherits] | Klipper authoritative |
| `machine_max_acceleration_x/y` | 20000 | [default-inherits] | Slicer ETA only |
| `machine_max_acceleration_z` | 500 | [default-inherits] | Slicer ETA only |
| `machine_max_acceleration_e` | 5000 | [default-inherits] | Slicer ETA only |
| `machine_max_speed_x/y` | 500 | [default-inherits] | Slicer ETA (caps at Klipper 450) |
| `machine_max_speed_z` | 12 | [default-inherits] | Legacy Marlin-flavor |
| `machine_max_speed_e` | 25 | [default-inherits] | ~22 mm³/s ceiling |
| `machine_max_jerk_x/y` | 12 | [default-inherits] | Klipper uses SCV |
| `machine_max_jerk_z` | 0.4 | [default-inherits] | — |
| `machine_max_jerk_e` | 2.5 | [default-inherits] | — |

---

## Machine profile fixes (`Voron v2.611.json`)

Three changes:

### 1. Line-break bug in `machine_start_gcode`

**Current (broken):**
```
MMU_START_SETUP INITIAL_TOOL=... ... FILAMENT_NAMES=!filament_names!
PURGE_VOLUMES=!purge_volumes!     ← orphaned, dropped as unknown gcode

PRINT_START EXTRUDER=... ... MATERIAL="..."
TOTAL_LAYER=[total_layer_count]    ← orphaned
```

**Fixed:**
```
MMU_START_SETUP INITIAL_TOOL=... ... FILAMENT_NAMES=!filament_names! PURGE_VOLUMES=!purge_volumes!

PRINT_START EXTRUDER=... ... MATERIAL="..." TOTAL_LAYER=[total_layer_count]
```

Impact of fix: HH receives per-pair purge volumes from OrcaSlicer (Blobifier no longer falls back to default); Mainsail progress UI shows accurate layer count.

### 2. Extruder clearance (Stealthburner + Galileo G2E)

OrcaSlicer-authoritative values (used in shipped Voron machine profiles):

```
extruder_clearance_radius: 65
extruder_clearance_height_to_rod: 36
extruder_clearance_height_to_lid: 140
```

The Voron PrusaSlicer profile's 20/20 numbers are Afterburner-era and stale. Galileo G2E doesn't extend the SB envelope.

### 3. Other machine-profile values (no change)

- `retraction_length: 0.5` ✓ (Galileo G2E direct-drive community-converged)
- `z_hop: 0.2` ✓ (Ellis: >0.3 strings)
- `z_hop_types: Normal Lift` ✓ (override from "Auto Lift")
- `purge_in_prime_tower: 0` ✓ (Blobifier)
- `enable_filament_ramming: 0` ✓ (Filametrix)

---

## Cross-setting interaction map (for future-you to reason about)

Things that move as a group — don't change one without checking the others.

| Group | Settings | Why |
|---|---|---|
| Speed-accel coupling | `outer_wall_speed` ↔ `outer_wall_acceleration` | Small parts (<150 mm linear) accel-limited regardless of speed setting |
| Bridge triad | `bridge_speed` ↔ `bridge_flow` ↔ `bridge_acceleration` | Failed bridges fail prints; move as group |
| Layer time floor | `top_shell_thickness` ↔ `top_shell_layers` ↔ `layer_height` | Auto-recalculates layers from thickness/layer_height |
| Cooling triad | `min_layer_time` (filament) ↔ `fan_speed` (filament) ↔ `slow_down_min_speed` (filament) | All filament-scope |
| Stringing prevention | `retract_on_layer_change` ↔ `z_hop` ↔ `wipe` ↔ `retract_lift_below` | Defense-in-depth |
| Travel optimization | `avoid_crossing_walls` ↔ `travel_speed` ↔ `retract_length` (machine) | Quality detours cost time |
| MMU purge | `purge_in_prime_tower` (machine) ↔ `enable_prime_tower` (process) ↔ Blobifier | Multiple disable points; verify all |
| Top surface quality | `top_shell_layers` ↔ `top_surface_pattern` ↔ `only_one_wall_top` ↔ ironing | Stacked quality levers |
| First-layer adhesion | `initial_layer_speed` ↔ `initial_layer_acceleration` ↔ `initial_layer_line_width` ↔ `elefant_foot_compensation` | All-converge values |

---

## Per-object overrides — when one profile isn't enough

When a single print needs to deviate from its profile, use OrcaSlicer's per-object override (right-click object in slice view → Edit object settings). Examples:

| Situation | Override |
|---|---|
| Part needs extra strength on Speed profile | `wall_loops: 5`, `sparse_infill_density: 30%` |
| Compressive-load part on Strength | `sparse_infill_density: 50%`, `infill pattern: cubic` |
| Visible cosmetic on a utility print | `wall_sequence: inner-outer-inner`, slower outer wall |
| Bed-adhesion-risky small footprint | `brim_type: outer_only`, `brim_width: 5` |
| Tight-tolerance hole that's coming out small | per-object `xy_hole_compensation` increase |

This keeps the profile count at 3 while preserving the ability to tune individual parts.

---

## RFID/NFC spool integration (alignment with future plans)

The 2-level slicer cascade (Material → Brand) is the right boundary for the planned NFC/RFID spool tracking work. Source of truth split:

| Layer | Lives in | Source of truth at |
|---|---|---|
| Material defaults (PLA = X°C, fan rules) | Slicer profile (system Generic) | Slice time |
| Brand calibration (Inland ABS PA, flow, chamber) | Slicer profile (user brand) | Slice time |
| Spool-specific overrides (PA, flow, weight) | NFC/RFID tag | Runtime (load time) |

Slicer never needs to know which physical spool is on which gate — it slices for "Inland ABS" generically. The tag system handles per-spool detail at print time via a Klipper macro that reads the tag and applies overrides (`SET_PRESSURE_ADVANCE`, `SET_FLOW_RATIO`). This decoupling means:

- Per-spool calibration drift doesn't bloat the slicer profile list
- INDX retrofit compatibility preserved — slicer cascade stays the same regardless of runtime mechanism

**Do not remove** `pressure_advance` / `filament_flow_ratio` from filament profiles once RFID is online — they remain the bootstrap/fallback when a spool has no tag yet.

---

## Filament selection still matters

Process profile is half the picture. The other half is filament — see [`docs/slicer-templates/orcaslicer.md`](./slicer-templates/orcaslicer.md) "Per-filament chamber targets" and the per-spool calibration workflow.

**Daily reminder when slicing: pick the brand-specific filament profile, not `Generic <material> @System`.** The Generic system profiles have empty `chamber_temperature`, empty `pressure_advance`, and a generic `filament_max_volumetric_speed: 12`. Selecting them silently bypasses every per-spool calibration in your user profiles.

`filament_max_volumetric_speed` ceiling for this hotend: **18 mm³/s** (set on each brand filament profile).

---

## Migration from current four-variant mess

| Current file | Disposition |
|---|---|
| `0.20mm Standard @Voron - Fast.json` | Delete; replaced by `0.20mm Speed @Voron 2.611` |
| `0.20mm Standard @Voron - Match SS.json` | Delete; SuperSlicer experiment |
| `0.20mm Standard @Voron - PLA.json` | Delete; material is filament-side |
| `0.20mm Standard @Voron - Copy.json` | Delete; accidental Save-As |

New profiles:
- `0.20mm Speed @Voron 2.611.json`
- `0.20mm Strength @Voron 2.611.json`
- `0.12mm Quality @Voron 2.611.json`

The apply script archives current state, drops in the new JSONs, and prompts for OrcaSlicer restart.

---

## What this intentionally doesn't do

- **Filament profile cascade fix** — separate from this audit; covered in [`docs/slicer-templates/orcaslicer.md`](./slicer-templates/orcaslicer.md). Six brand profiles need their `inherits` chain rewired from dead `Voron Generic X` parents to live `Generic <Material> @System`, plus `chamber_temperature: 30 → 55` on ABS/ASA.
- **Scarf seam tuning** — parked to [#75](https://github.com/bjdeng/voron-2-611/issues/75)
- **`max_velocity` 450→500 bump** — wait until belt + shaper re-cal ([#25](https://github.com/bjdeng/voron-2-611/issues/25)) + microstepping research ([#24](https://github.com/bjdeng/voron-2-611/issues/24)) + TEST_SPEED validation
- **Per-filament tuning re-cal** — for new Galileo era; covered in slicer-templates doc

---

## Validation checklist post-deploy

Tracked as a live checklist in [#77](https://github.com/bjdeng/voron-2-611/issues/77) so it doesn't rot. After applying the new profiles, work through that issue's checklist — Benchy hull line, chamfered cube, M3 hole calipers, multi-tool MMU layer count + purge volumes, Mainsail per-object cancel + thumbnails, profile-specific load + surface tests.
