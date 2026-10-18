# Pi environment beyond `~/printer_data/config/`

Ben's note: *"on the machine some updates to klipper, happy hare and others occasionally require running ./setup.sh in their home directories and klipper configs rely on other scripts on the machine sometimes."* The config tree alone is not the whole story — this doc inventories the Pi-side state that this repo's configs depend on, and how to rebuild it on a fresh card.

## OS (reflashed 2026-10-18)

**MainsailOS 3.0.0 — Debian 13 trixie**, kernel 6.18 (`6.18.50+rpt-rpi-v8`), Python 3.13, Raspberry Pi 4 Model B Rev 1.2, Wi-Fi only (`wlan0`, SSID `huzzah`). User `pi`, key-only SSH, passwordless sudo.

Previous install (MainsailOS 1.0.0 / bullseye, kernel 6.1) is preserved as a full image on Ben's MacBook (`~/Downloads/voron-bullseye-2026-10-17.img.gz`) and as extracted key files in `~/voron-pi-backup-2026-10-17/` on the Mac Claude runs on (`pi-home.tgz`: Moonraker DB, live config, kconfigs, usb-rca-monitor; `pi-system.tgz`: systemd units, udev, boot config; `pi-reference.txt`: repo commits, pip freezes, package list).

## Repos installed on the Pi (as of 2026-10-18)

| Path | Version | Notes |
|---|---|---|
| `~/klipper` | `v0.13.0-800` (master) | Untracked files in `klippy/extras/` are add-on links (autotune, HH `mmu*`, shaketune, `gcode_shell_command.py`) — Moonraker shows them as an anomaly; expected. MCU firmware is older (SKRs + EASY-BRD -375, EBB -688, eddy -649) and still accepted. |
| `~/moonraker` | `v0.11.0-3` (master) | Untracked `components/mmu_server.py` (HH) + `timelapse.py` — expected. |
| `~/Happy-Hare` | `v4.1.0-16` (main) | Kconfig installer. Generates `config/mmu/base/*` from `config/mmu/.mmu_config`; `mmu/macros/*` + `mmu/optional/*` are symlinks into it. |
| `~/klipper_tmc_autotune` | `v0.2.0-385` | `./install.sh` (non-interactive) links into `klippy/extras/`. |
| `~/klippain_shaketune` | `v6.0.0` | `./install.sh` (non-interactive; apt + venv; adds its own update_manager block — the deployed `moonraker.conf` already has it). Writes graphs to `config/ShakeTune_results/` (excluded from deploy). |
| `~/chopper-resonance-tuner` | `V1.2.0-58` | **Do not run its `install.sh` on trixie** — it prompts y/n and requests `libatlas-base-dev`, which no longer exists. Manual steps: copy `gcode_shell_command.py` into `klippy/extras/`, `ln -srf chopper_tune.cfg ~/printer_data/config/`, `apt install python3-venv libopenblas-dev`, `python3 -m venv --system-site-packages .venv`, `.venv/bin/pip install -r wiki/requirements.txt`. The `[include chopper_tune.cfg]` + update_manager block come from this repo. |
| `~/moonraker-timelapse` | `v0.0.1-143` | Shipped with the image. Opt-in per print. |
| `~/crowsnest` | `v5.0.12` (**v5** branch) | Shipped with the image. `camera-streamer` (WebRTC) mode — see CLAUDE.md webcam quirk. |
| `~/sonar` | `v0.2.0-2` | Shipped with the image. Network keepalive. |
| `~/mainsail`, `~/mainsail-config` | Mainsail `v2.19.0`; config `v1.2.1-1` | `config/mainsail.cfg` is a symlink into mainsail-config. |
| `~/kiauh`, `~/katapult` | `v6.3.2`; `v0.0.1-115` | Tools only (install/flash). BOSSA not reinstalled — fetch again if the EASY-BRD needs reflashing. |
| `~/klippy-env`, `~/moonraker-env`, `~/crowsnest-env` | venvs | Python 3.13. |

**Dropped in the reflash:** `~/eddy-ng` (migrated off in PR #17), `~/usb-rca-monitor` (diagnosed the 2026-10 toolhead USB drops; files kept in the Mac backup — reinstall if the drops return), `~/BOSSA`.

## Systemd services

Running: `klipper`, `moonraker`, `nginx`, `crowsnest`, `sonar`, `klipper-mcu-watchdog`, plus the OS-level usuals. `ModemManager` is not installed on this image (keep it that way — see CLAUDE.md).

**`klipper-mcu-watchdog.service`** (install: copy `scripts/{install-mcu-watchdog.sh,klipper-mcu-watchdog.sh,klipper-mcu-watchdog.service}` to the Pi under a `scripts/` dir and `sudo bash scripts/install-mcu-watchdog.sh`): auto-recovers the SKR Z + EASY-BRD USB re-enumeration race after `FIRMWARE_RESTART`. Root cause + design: [GH issue #37](https://github.com/bjdeng/voron-2-611/issues/37). Logs: `journalctl -u klipper-mcu-watchdog`.

## OS tweaks applied after flashing (not part of `config/`)

| File | Why |
|---|---|
| `/etc/sudoers.d/010_pi-nopasswd` | `pi ALL=(ALL) NOPASSWD:ALL` — deploy/installer scripts assume it. |
| `/etc/NetworkManager/conf.d/99-wifi-powersave-off.conf` | `[connection] wifi.powersave = 2` — Pi Wi-Fi power saving can drop inbound traffic. |
| `/etc/udev/rules.d/99-vcio-video.rules` | `KERNEL=="vcio", GROUP="video", MODE="0660"` — trixie image ships `/dev/vcio` root-only, so Moonraker can't read under-voltage/throttle flags (`PermissionError: '/dev/vcio'`). |
| `/etc/systemd/journald.conf.d/50-persistent-bounded.conf` | `Storage=persistent`, `SystemMaxUse=100M`, `SystemMaxFileSize=10M`, `SystemKeepFree=2G`, `MaxRetentionSec=1month` — the image's journal is RAM-only. |
| `/etc/tmpfiles.d/printer-logs-cleanup.conf` | `e /home/pi/printer_data/logs - - - 30d` — Klipper/Moonraker/crowsnest rotate daily but never delete old logs. Runs via `systemd-tmpfiles-clean.timer`. |
| `iw` package | For `iw dev wlan0 get power_save`. |

## Fresh-Pi bootstrap (how the 2026-10-18 rebuild was done)

`/deploy-to-pi` can't do the first deploy: its idle gate needs Klippy running, and Klippy can't load until the config exists. Order matters:

1. **Flash** with Raspberry Pi Imager: hostname `mainsailos`, user `pi`, **set a password** (Imager can leave it empty → account locked → no sudo), Wi-Fi, SSH public key. After first boot it reboots once.
2. **Basics:** passwordless sudo, OS tweaks above, `apt full-upgrade`, reboot into the new kernel.
3. **Restore state from backup** (not from the repo): the live `printer.cfg` — it carries the SAVE_CONFIG block, and deploy keeps the *Pi's* SAVE_CONFIG, so deploying onto an empty Pi silently drops all calibration — plus `mmu/mmu_vars.cfg` and `mmu/.mmu_config`.
4. **Add-ons:** clone Happy-Hare, klipper_tmc_autotune, klippain_shaketune, chopper-resonance-tuner, kiauh, katapult; run autotune + ShakeTune installers; chopper tuner manually (above); HH: `cd ~/Happy-Hare && F_CFG_UPGRADE_MODE=replace ./install.sh -y -z -s <copy-of-.mmu_config>` (pass a *copy* — the installer copies its input into `mmu/`), then delete the stray copy it leaves in `mmu/`.
5. **One-time config push:** rsync `config/` with the same excludes as `deploy_to_pi.sh` (`build_rsync_excludes` + every Pi-side symlink from `find ~/printer_data/config -type l`), **without `--delete`**, then `systemctl restart moonraker crowsnest klipper` → Klippy `ready`.
6. **Real deploy:** `scripts/deploy_to_pi.sh --force --yes` (once — writes the deploy marker; later deploys need no `--force`).
7. **Watchdog** (above), then **Moonraker DB**: stop Moonraker, back up the fresh DB, `ATTACH` the old `moonraker-sql.db` and copy `job_history`, `job_totals` and the `mainsail`, `maintenance`, `webcams`, `lane_data` namespaces (leave `moonraker`/`database`/`update_manager` — they hold install-specific state). Check `table_registry` versions match first.
8. **Update manager:** after moving repos, force `POST /machine/update/refresh` — Moonraker otherwise shows cached "invalid" status for up to a week.
9. **Verify:** 5 MCUs, `ready`, `mmu.log` "Loaded saved …" lines, cancel hook / pause park vars, Spoolman connected, webcam snapshot.

## Install scripts that may need re-running after upgrades

- `~/Happy-Hare/install.sh` — after every Happy-Hare pull (Moonraker's update manager tracks `main`) and any Klipper update that breaks `klippy/extras/mmu*` links. Non-interactive + replace mode — see CLAUDE.md MMU section (a bare `./install.sh` refresh ignores Kconfig edits).
- `~/klipper_tmc_autotune/install.sh`, `~/klippain_shaketune/install.sh` — after a Klipper reinstall (re-creates their `klippy/extras/` links).

## Moonraker update_manager

There's no `[update_manager klipper]` block in `config/moonraker.conf`, **and that's by design.** Moonraker auto-detects Klipper and manages it without an explicit block; the block is only needed to override channel/pinned_commit/refresh_interval.

**Active `[update_manager]` blocks** in [`config/moonraker.conf`](../config/moonraker.conf):

| Block | Manages | Notes |
|---|---|---|
| `mainsail` | Mainsail web UI | Active |
| `mainsail-config` | Upstream mainsail-config (`~/mainsail-config/`) | Active. Our `config/mainsail.cfg` is symlinked to it on the Pi. |
| `timelapse` | moonraker-timelapse | Active; opt-in per print. |
| `crowsnest` | Webcam stack | **v5**: `primary_branch: v5` + venv/requirements (copied from the MainsailOS 3.0.0 stock block). Without `primary_branch: v5` Moonraker reports "Repo not on official remote/branch". |
| `sonar` | Network keepalive daemon | `system_dependencies` form (MainsailOS 3.0.0 stock block). |
| `happy-hare` | HH Klipper extension (`~/Happy-Hare/`) | Active |
| `TMC_Autotune`, `Klippain-ShakeTune`, `chopper-resonance-tuner` | add-ons | Active |
