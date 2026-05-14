# CI tests for voron-2-611

What runs in `make test-py` locally and on every PR/push in CI.

## Layout

```
tests/
├── README.md              this file
├── voron-2-611.test       Klipper smoke gcode + MCU dictionaries
├── builtins.txt           Klipper built-in gcode commands (regen w/ `make builtins`)
├── dict/                  Pre-compiled MCU protocol dictionaries
│   ├── mcu.dict           LPC1769 — both SKR 1.4 mainboards
│   ├── ebb-usb.dict       RP2040 — EBB SB toolhead
│   ├── eddy.dict          RP2040 — BTT Eddy probe
│   └── easy-brd.dict      SAMD21 — ERCF EASY-BRD
├── fixtures/              Minimal .cfg files for script unit tests
└── test_macro_refcheck.py Tests scripts/macro_refcheck.py
```

## Running locally

```sh
make test-py    # macOS-friendly subset (refcheck + pytest + pre-commit)
make test       # full pipeline; klippy step needs Linux
make refcheck   # macro_refcheck only
make pytest     # unit tests only
make precommit  # pre-commit hooks only
make builtins   # regenerate tests/builtins.txt
```

`make test` includes the `klippy` step which invokes `vendor/klipper/scripts/test_klippy.py`. Klipper's C extension uses Linux-only kernel headers (`sys/prctl.h`, `linux/can.h`), so this target **fails on macOS**. CI runs it on ubuntu-22.04; on macOS use `make test-py` for local iteration.

## When to regenerate

- **`tests/dict/*.dict`** — when bumping `vendor/klipper` or changing `firmware/*.config`. Build on the Pi: copy each `firmware/*.config` to `~/klipper/.config`, `make`, copy `~/klipper/out/klipper.dict` back as `tests/dict/<name>.dict`. (Done once during initial setup; see commit `a4c46ae`.)
- **`tests/builtins.txt`** — when bumping `vendor/klipper`. Run `make builtins`.

## Why these specific .dict files

Klipper's simulator (`test_klippy.py`) needs an MCU protocol dictionary per `[mcu ...]` section in `printer.cfg`. The dict mirrors what the real MCU reports on connection — command IDs, parameter formats, etc. Committing them avoids compiling firmware in CI.

A `.dict` is forward-compatible with config that uses fewer features than the firmware build expressed. As long as our config doesn't reference a feature the dict doesn't know about, parsing succeeds.

## Adding a new macro

After adding a new `[gcode_macro X]`:
1. `make refcheck` locally — should pass.
2. If `X` is called from another macro, the local run catches typos.
3. If `X` calls a Klipper command not in `tests/builtins.txt`, the script flags it. Two responses:
   - It's a Klipper command not captured by the `cmd_*_help` regex → run `make builtins` and confirm it appears, OR add to `ALLOWLIST` in `scripts/macro_refcheck.py`.
   - It's a Happy-Hare / third-party command registered by Python (e.g. `MMU_STATS`, `PROBE_EDDY_NG_TAP`) → add to the appropriate block in `ALLOWLIST` with a comment explaining provenance.

## ALLOWLIST coupling — the eddy migration acid test

`scripts/macro_refcheck.py`'s `ALLOWLIST` has a block labelled "third-party module: eddy-ng commands" containing `PROBE_EDDY_NG_TAP` and friends. **When the eddy migration removes `[probe_eddy_ng]` from `eddy.cfg`, the same PR must remove these entries from `ALLOWLIST`.** If a PR removes the section but forgets the ALLOWLIST cleanup, CI keeps passing (callers still resolve via the orphaned allowlist). If a PR removes the ALLOWLIST entries but forgets to update `macros/print_start.cfg` (still calls `PROBE_EDDY_NG_TAP`), CI flags the unresolved reference.

This coupling is deliberate. See `docs/superpowers/specs/2026-05-13-ci-scaffold.md` §7.3.

## Future enhancement

`Frix-x/klippain-shaketune`'s CI tests against a **matrix** of Klipper versions (klipper3d/klipper master + KalicoCrew/kalico + v0.13.0). We pin to a single `vendor/klipper` commit for now — matches the Pi exactly. Worth considering a matrix when we bump Klipper less conservatively.
