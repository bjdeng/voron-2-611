# Pi environment beyond `~/printer_data/config/`

Ben's note: *"on the machine some updates to klipper, happy hare and others occasionally require running ./setup.sh in their home directories and klipper configs rely on other scripts on the machine sometimes."* The config tree alone is not the whole story — this doc inventories the Pi-side state that this repo's configs depend on.

## Repos installed on the Pi (as of 2026-05-13)

| Path | Version | Upstream | Notes |
|---|---|---|---|
| `~/klipper` | `v0.13.0-649-g4767a8ed` (master) | Klipper3d/klipper | **Has uncommitted local files** from `eddy-ng/install.sh` and `Happy-Hare/install.sh` (symlinks into `klippy/extras/`). |
| `~/Happy-Hare` | `v3.4.2-22-ga880ac0a` | moggieuk/Happy-Hare | Has `install.sh`. Owns `~/printer_data/config/mmu/base/*` (those files in this repo are dereferenced copies of symlinks). |
| `~/eddy-ng` | `v0.1-73-gc7ca62e` | vvuk/eddy-ng | Has `install.sh`. **Migrated off to native `[probe_eddy_current]` in PR #17, 2026-05-15.** Install dir retained for rollback; eventual cleanup TBD. |
| `~/moonraker` | `v0.10.0-19-g1ed102e` | Arksine/moonraker | Standard. |
| `~/moonraker-timelapse` | `v0.0.1-143-gc7fff11` | mainsail-crew/moonraker-timelapse | Installed via `make install` 2026-05-18 (closes #26). Opt-in per print; needs webcam (#27). |
| `~/mainsail` | (web release) | mainsail-crew/mainsail | Static UI files served by nginx. |
| `~/mainsail-config` | `v1.2.1-1-gff3869a` | mainsail-crew/mainsail-config | Owns `mainsail.cfg` (the actual symlink target — `client.cfg` in the same dir is an identical copy, unused by us). |
| `~/kiauh` | `v6.0.6` | dw-0/kiauh | Klipper installer/manager (interactive helper). |
| `~/crowsnest` | `v4.2.0-1-gcf936da` | mainsail-crew/crowsnest | Webcam stack. Daemon runs even though webcam is unplugged. |
| `~/sonar` | `v0.2.0-1-g0d1d7c8` | mainsail-crew/sonar | Network keepalive. Daemon runs. |
| `~/katapult` | `v0.0.1-64-g3e23332` | Arksine/katapult | MCU bootloader for safe re-flashing. |
| `~/BOSSA` | (present) | shumatech/BOSSA | SAM-BA flasher, likely used to flash the EASY-BRD SAMD21. |
| `~/klipper-kconfigs` | (saved configs) | — | Per-MCU build kconfigs. **Mirrored into `config/firmware/` in this repo.** |
| `~/klippy-env`, `~/moonraker-env` | (venvs) | — | Python virtualenvs. |

## Systemd services

Running: `klipper`, `klipper_mcu`, `moonraker`, `nginx`, `sonar`, plus the OS-level usuals.

**`ModemManager` is masked** (was active until 2026-05-14, then masked after a real USB-MCU enumeration race during the first live `/deploy-to-pi`). If a future MCU connect-error pattern returns, verify ModemManager is still masked: `systemctl is-enabled ModemManager` should print `masked`.

**`klipper-mcu-watchdog.service`** (install via `sudo bash scripts/install-mcu-watchdog.sh`): a daemon that auto-recovers from the constant USB re-enumeration race that hits SKR Z + EASY-BRD MMU after every `FIRMWARE_RESTART`. Root cause + design at [GH issue #37](https://github.com/bjdeng/voron-2-611/issues/37). Logs via `journalctl -u klipper-mcu-watchdog`.

## Install scripts that may need re-running after upgrades

- `~/eddy-ng/install.sh` — after any `~/klipper` update that might break the symlinks into `klippy/extras/`
- `~/Happy-Hare/install.sh` — same, for the `klippy/extras/mmu/` and `klippy/extras/mmu_*` files

## Moonraker update_manager

There's no `[update_manager klipper]` block in `config/moonraker.conf`, **and that's by design.** Moonraker auto-detects Klipper and manages it without an explicit block; the block is only needed to override channel/pinned_commit/refresh_interval. Documented at `vendor/moonraker/docs/configuration.md:2017-2026`.

**Active `[update_manager]` blocks** in [`config/moonraker.conf`](../config/moonraker.conf):

| Block | Manages | Notes |
|---|---|---|
| `mainsail` | Mainsail web UI | Active |
| `mainsail-config` | Upstream mainsail-config (`~/mainsail-config/`) | Active. Note: our `config/mainsail.cfg` is symlinked to it on the Pi; if we ever slim that file locally (per refactor spec Phase 2), the symlink would need to be replaced with a real file and upstream changes would no longer auto-apply |
| `timelapse` | moonraker-timelapse | Active. Component installed 2026-05-18; usage is opt-in per print (`TIMELAPSE_TAKE_FRAME` in slicer custom gcode, or `HYPERLAPSE ACTION=START` in console) and gated on webcam (#27). |
| `crowsnest` | Webcam stack | Active even though webcam unplugged — see [#27](https://github.com/bjdeng/voron-2-611/issues/27) |
| `sonar` | Network keepalive daemon | Active |
| `happy-hare` | HH Klipper extension (`~/Happy-Hare/`) | Active |
