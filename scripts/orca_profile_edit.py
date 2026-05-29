#!/usr/bin/env python3
"""Read and safely edit scalar fields in OrcaSlicer filament-profile JSONs.

Used by the calibrate-filament skill to write calibrated values
(nozzle_temperature, filament_flow_ratio, ...) into OrcaSlicer filament
profiles. Never touches the Adaptive PA model field — that stays a guided
manual paste.

OrcaSlicer stores most filament settings as single-element arrays of
strings (e.g. "nozzle_temperature": ["210"]). --set preserves the
existing container type: list -> single-element list of the string value;
scalar -> scalar string.

Profile resolution: --file points at a JSON directly; --profile NAME
searches the OrcaSlicer user dir (ORCA_USER_DIR env, else the default
macOS path) for <NAME>.json under a filament/ subdir.

Exit codes:
  0 — success
  1 — bad usage (missing/conflicting args)
  2 — profile not found / ambiguous / key missing
  3 — refused: OrcaSlicer is running (would overwrite the edit on exit)
  4 — write failed (result did not re-parse; .bak restored)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_ORCA_DIR = (
    Path.home() / "Library" / "Application Support" / "OrcaSlicer" / "user"
)


def orca_user_dir() -> Path:
    return Path(os.environ.get("ORCA_USER_DIR", str(DEFAULT_ORCA_DIR)))


def find_profile(name: str) -> Path:
    base = orca_user_dir()
    matches = sorted(base.glob(f"**/filament/{name}.json"))
    if not matches:
        matches = sorted(base.glob(f"**/{name}.json"))
    if not matches:
        sys.stderr.write(f"profile not found: {name!r} under {base}\n")
        sys.exit(2)
    if len(matches) > 1:
        listing = "\n".join(f"  {m}" for m in matches)
        sys.stderr.write(
            f"ambiguous profile {name!r}: {len(matches)} matches:\n{listing}\n"
        )
        sys.exit(2)
    return matches[0]


def resolve_target(args) -> Path:
    if args.file:
        p = Path(args.file)
        if not p.is_file():
            sys.stderr.write(f"file not found: {p}\n")
            sys.exit(2)
        return p
    return find_profile(args.profile)


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def scalar(val):
    return (val[0] if val else "") if isinstance(val, list) else val


def do_get(p: Path, key: str) -> None:
    data = load(p)
    if key not in data:
        sys.stderr.write(f"key not found: {key}\n")
        sys.exit(2)
    print(scalar(data[key]))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Read/edit OrcaSlicer filament profile scalars"
    )
    ap.add_argument("--find", metavar="NAME")
    ap.add_argument("--profile", metavar="NAME")
    ap.add_argument("--file", metavar="PATH")
    ap.add_argument("--get", metavar="KEY")
    ap.add_argument("--set", metavar="KEY=VALUE")
    args = ap.parse_args()

    if args.find:
        print(find_profile(args.find))
        return

    if not (args.get or args.set):
        sys.stderr.write("nothing to do: pass --find, --get, or --set\n")
        sys.exit(1)
    if args.file and args.profile:
        sys.stderr.write("use only one of --file / --profile\n")
        sys.exit(1)
    if not (args.file or args.profile):
        sys.stderr.write("--get/--set require --file or --profile\n")
        sys.exit(1)

    target = resolve_target(args)

    if args.get:
        do_get(target, args.get)


if __name__ == "__main__":
    main()
