# voron-2-611

Klipper configuration for **Voron 2.4 r2 (community serial 2.611)** — a self-sourced V2.4 r2 commissioned ~2020, currently running with:

- 2× BTT SKR 1.4 mainboards (LPC1769)
- BTT EBB SB v1.0 toolhead (RP2040, USB)
- BTT Eddy probe (RP2040)
- ERCF v2 + EASY-BRD (SAMD21)
- Stealthburner v2 + Galileo extruder
- Happy Hare MMU + Blobifier + EREC cutter

Full hardware inventory, macro map, MCU map, and known quirks live in [`CLAUDE.md`](CLAUDE.md). Specs and plans for individual changes live under [`docs/superpowers/`](docs/superpowers/).

## Repo intent

This repo is the **canonical source of truth** for the printer's Klipper config. The on-printer copy at `~/printer_data/config/` is the working version. Edits flow `local branch → PR → merge to main → sync to printer`.

## CI

Every PR and push to `main` runs:
- Klipper's own `test_klippy.py` simulator against `printer.cfg` with a smoke g-code sequence (covers config parsing, jinja2 syntax in `[gcode_macro]` bodies, MCU pin clashes, and macro runtime errors reachable from `PRINT_START`).
- `pre-commit` (text hygiene + ruff for Python)
- `scripts/macro_refcheck.py` — static reference check for every gcode command invoked from a macro.

Local run: `make test-py` (macOS-friendly subset) or `make test` (full pipeline, requires Linux for the klippy step). See [`tests/README.md`](tests/README.md).

## Safety / contributor notes

- The `.env` file is **gitignored**. The legacy Pi default credentials (`pi:raspberry`) are still functional but key-based SSH is preferred — see the project's `memory/pi-ssh-access.md` (not in git; Claude Code internal). Anyone forking this repo for their own Voron should rotate the Pi password before exposing it on a LAN with strangers.
- **No printer-side automation runs from this repo (yet).** CI only validates; nothing pushes to the printer. A future deploy spec will cover that.

## License

[GPL-3.0](LICENSE) — matches Klipper itself, the Voron Design project, Happy-Hare, and most of the Klipper-adjacent community.
