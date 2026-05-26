#!/usr/bin/env python3
"""
Park-position sag experiment.

For each (park_position, trial) combination:
  1. G28 + QUAD_GANTRY_LEVEL  (establish level baseline)
  2. Move toolhead to test park position
  3. M84 Z  (release Z motors only)
  4. Sleep SETTLE_SECONDS
  5. G28 + QUAD_GANTRY_LEVEL  (measure sag via the adjustment magnitudes)
  6. SSH grep klippy.log for the first 'Making the following Z adjustments' block
     since step 3 — that's the cold-start adjustment.
  7. Write CSV row.

Output: data/park-sag-{date-time}.csv  (timestamped per run).

Stdlib only; no requests dep. Talks to Moonraker on mainsailos.local:7125.
SSH grep uses the existing keyed-login to pi@mainsailos.local.
"""

import csv
import json
import random
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

MOONRAKER_BASE = "http://mainsailos.local:7125"
PI_SSH = "pi@mainsailos.local"
KLIPPY_LOG = "~/printer_data/logs/klippy.log"

POSITIONS = [
    ("rear-left",   5,   345),
    ("rear-center", 175, 345),
    ("rear-right",  345, 345),
    ("center",      175, 175),
]
TRIALS_PER_POSITION = 3
SETTLE_SECONDS = 120  # 2 min — captures the belt-creep tail beyond the instantaneous drop


def moonraker_post(path: str, **params) -> dict:
    """POST to Moonraker, return parsed JSON. Synchronous (waits for gcode to complete)."""
    qs = urllib.parse.urlencode(params)
    url = f"{MOONRAKER_BASE}{path}?{qs}"
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=900) as resp:
        return json.loads(resp.read().decode())


def moonraker_get(path: str) -> dict:
    url = f"{MOONRAKER_BASE}{path}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def gcode(cmd: str) -> bool:
    """Send gcode. Returns True on success, False if Klipper raised an error."""
    try:
        moonraker_post("/printer/gcode/script", script=cmd)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        print(f"  ERROR running '{cmd}': HTTP {e.code} — {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ERROR running '{cmd}': {e}", file=sys.stderr)
        return False


def log_line_count() -> int:
    r = subprocess.run(
        ["ssh", PI_SSH, f"wc -l < {KLIPPY_LOG}"],
        capture_output=True, text=True, check=True,
    )
    return int(r.stdout.strip())


def first_qgl_adjustment(from_line: int):
    """
    Find the first QGL adjustment block after from_line in klippy.log.
    Returns (z, z1, z2, z3) tuple or None if not found / probe failed.
    """
    awk = (
        f"awk 'NR>={from_line}' {KLIPPY_LOG} | "
        "awk '/Making the following Z adjustments:/ {capture=1; next} "
        "capture && /stepper_z = / {z=$3} "
        "capture && /stepper_z1 = / {z1=$3} "
        "capture && /stepper_z2 = / {z2=$3} "
        "capture && /stepper_z3 = / {z3=$3; print z, z1, z2, z3; exit}'"
    )
    r = subprocess.run(["ssh", PI_SSH, awk], capture_output=True, text=True, check=True)
    parts = r.stdout.strip().split()
    if len(parts) != 4:
        return None
    return tuple(float(p) for p in parts)


def probe_failure_count(from_line: int) -> int:
    """Count 'No trigger on probe' or 'Unable to detect tap' errors since from_line."""
    r = subprocess.run(
        ["ssh", PI_SSH,
         f"awk 'NR>={from_line}' {KLIPPY_LOG} | grep -cE 'No trigger on probe|Unable to detect tap' || true"],
        capture_output=True, text=True,
    )
    return int(r.stdout.strip() or 0)


def auto_recover_via_force_move() -> bool:
    """
    One-shot auto recovery: pre-tilt gantry then retry G28 + QGL.
    Returns True if QGL succeeds after pre-tilt, False otherwise.

    Stepper map (assumed): z=FL, z1=RL, z2=RR, z3=FR.
    Pre-tilt direction assumes rear-low sag (the typical V2.4 pattern).
    Magnitudes use the empirical median (~5mm front-low/rear-high) from earlier
    cold-start data, which should recover from typical sag without compounding
    the failure (more aggressive pre-tilt could tilt the OTHER way past the
    probe budget on the opposite corners).
    """
    print("  auto recovery: FORCE_MOVE pre-tilt (rear+5, front-5), then re-home + QGL")
    if not gcode("FORCE_MOVE STEPPER=stepper_z1 DISTANCE=5 VELOCITY=5"): return False
    if not gcode("FORCE_MOVE STEPPER=stepper_z2 DISTANCE=5 VELOCITY=5"): return False
    if not gcode("FORCE_MOVE STEPPER=stepper_z DISTANCE=-5 VELOCITY=5"):  return False
    if not gcode("FORCE_MOVE STEPPER=stepper_z3 DISTANCE=-5 VELOCITY=5"): return False
    if not gcode("G28"): return False
    if not gcode("QUAD_GANTRY_LEVEL"): return False
    return True


def manual_recovery_prompt() -> bool:
    """
    Operator-in-the-loop recovery: drop Z motors, prompt user to adjust,
    loop until G28+QGL succeeds or user aborts. Used as fallback after
    auto recovery fails (so we don't compound the problem with more
    FORCE_MOVE attempts).
    """
    print("  manual recovery needed — releasing Z motors")
    gcode("M84 Z")
    while True:
        print()
        print("  Adjust the gantry by hand until roughly level by eye.")
        print("  (Failure means sag exceeded probe range — push the high corner DOWN")
        print("   or the low corner UP. For typical rear-sag, push front DOWN.)")
        resp = input("  Press Enter to retry G28 + QGL, or type 'abort' to exit. > ").strip().lower()
        if resp == "abort":
            return False
        if gcode("G28") and gcode("QUAD_GANTRY_LEVEL"):
            print("  ✓ manual recovery succeeded")
            return True
        print("  ✗ still failing — try more adjustment, or type 'abort'.")


def recover(label: str = "recovery") -> bool:
    """Try auto recovery exactly once; if it fails, fall back to manual prompt."""
    print(f"\n  ⚠ {label}: QGL failed")
    if auto_recover_via_force_move():
        print("  ✓ auto recovery succeeded")
        return True
    print("  auto recovery didn't work — falling back to manual")
    return manual_recovery_prompt()


def verify_idle() -> None:
    d = moonraker_get("/printer/objects/query?print_stats")
    state = d["result"]["status"]["print_stats"]["state"]
    if state not in ("standby", "complete", "cancelled"):
        print(f"REFUSE: printer state is '{state}'. Need standby/complete/cancelled.", file=sys.stderr)
        sys.exit(1)
    print(f"Printer state: {state} ✓")


def main() -> None:
    verify_idle()

    # Build randomized trial list
    trials = []
    for trial_n in range(1, TRIALS_PER_POSITION + 1):
        for label, x, y in POSITIONS:
            trials.append((trial_n, label, x, y))
    random.shuffle(trials)

    est_min = len(trials) * (SETTLE_SECONDS + 180) / 60  # 3 min per trial overhead
    print(f"Running {len(trials)} trials (~{est_min:.0f} min total). Settle: {SETTLE_SECONDS}s.\n")

    out_path = Path(__file__).parent.parent / "data" / f"park-sag-{time.strftime('%Y-%m-%d-%H%M')}.csv"
    out_path.parent.mkdir(exist_ok=True)
    print(f"Output: {out_path}\n")

    with out_path.open("w") as f:
        w = csv.writer(f)
        w.writerow([
            "trial_n", "position", "x", "y", "settle_s",
            "z_FL", "z_RL", "z_RR", "z_FR", "front_avg", "rear_avg",
            "probe_failures", "status",
        ])

        for i, (trial_n, label, x, y) in enumerate(trials, 1):
            print(f"[{i}/{len(trials)}] trial {trial_n}: {label} ({x},{y})")

            # Establish baseline level. Each trial must start from level — otherwise
            # the measurement is contaminated by prior-trial sag.
            print("  baseline: G28 + QGL")
            if not gcode("G28") or not gcode("QUAD_GANTRY_LEVEL"):
                if not recover(label="baseline"):
                    print("  ABORT requested. Exiting experiment.")
                    sys.exit(2)

            # Move + release Z
            print(f"  parking at ({x},{y}) + M84 Z")
            if not gcode(f"G1 X{x} Y{y} F6000"):
                w.writerow([trial_n, label, x, y, SETTLE_SECONDS, "", "", "", "", "", "", "", "park-move-fail"])
                f.flush()
                continue
            before = log_line_count()
            gcode("M84 Z")

            print(f"  settling {SETTLE_SECONDS}s")
            time.sleep(SETTLE_SECONDS)

            # Measure
            print("  measure: G28 + QGL")
            home_ok = gcode("G28")
            qgl_ok = gcode("QUAD_GANTRY_LEVEL") if home_ok else False
            fail_count = probe_failure_count(before)

            if not home_ok or not qgl_ok:
                print(f"  PROBE FAIL during measure (probe-failure-count={fail_count}) — "
                      f"this IS the data point: position+settle produced sag exceeding probe range")
                w.writerow([trial_n, label, x, y, SETTLE_SECONDS, "", "", "", "", "", "",
                            fail_count, "severe-sag-unmeasurable"])
                f.flush()
                # Next trial needs a level baseline — get operator to recover.
                if not recover(label="post-measure"):
                    print("  ABORT requested. Exiting.")
                    sys.exit(2)
                continue

            adj = first_qgl_adjustment(before)
            if adj is None:
                print(f"  WARN: no adjustment block found (probe-failure-count={fail_count})")
                w.writerow([trial_n, label, x, y, SETTLE_SECONDS, "", "", "", "", "", "",
                            fail_count, "no-adjustment-block"])
                f.flush()
                continue

            z_fl, z_rl, z_rr, z_fr = adj
            front_avg = (z_fl + z_fr) / 2
            rear_avg = (z_rl + z_rr) / 2
            print(f"  result: FL={z_fl:+.2f} RL={z_rl:+.2f} RR={z_rr:+.2f} FR={z_fr:+.2f}"
                  f"  | front_avg={front_avg:+.2f}, rear_avg={rear_avg:+.2f}, failures={fail_count}")
            w.writerow([trial_n, label, x, y, SETTLE_SECONDS,
                        z_fl, z_rl, z_rr, z_fr, front_avg, rear_avg, fail_count, "ok"])
            f.flush()

    # Final: leave in known-good state
    print("\nFinal: G28 + QGL to leave printer level.")
    gcode("G28")
    gcode("QUAD_GANTRY_LEVEL")
    print(f"\nDone. Results in {out_path}")


if __name__ == "__main__":
    main()
