# Troubleshooting log

Symptoms encountered, root cause when found, and the fix that worked. Newest at the top. Use this to recognize recurring failure modes before they bite again.

---

## Open

### moonraker-timelapse — never functional
- **Symptom:** Ben has never gotten timelapse to record/produce video.
- **Status:** unconfirmed root cause. Could be ffmpeg config, camera path, frame-trigger, or upstream bug.
- **Plan:** decide whether to debug or remove the `[include timelapse.cfg]` + `[update_manager timelapse]` + `[timelapse]` sections.
- **Logs to check first:** `~/printer_data/logs/moonraker.log` for `timelapse` entries.

### Webcam timing issues
- **Symptom:** webcam streaming was interfering with print timing.
- **Mitigation:** Ben unplugged the webcam. Crowsnest + Sonar services still run with nothing to serve.
- **Plan:** re-enable after `eddy-ng` → native Klipper Eddy migration (the suspicion is the eddy-ng polling loop conflicts with the webcam pipeline).

---

## Resolved

### 2026-05-13 — Moonraker missing `[update_manager klipper]` block (non-issue)
- **Concern:** Initial repo-init review flagged the absence of `[update_manager klipper]` from `moonraker.conf` as a potential quirk.
- **Resolution:** Verified against Moonraker docs (`vendor/moonraker/docs/configuration.md:2017-2026`). Moonraker auto-detects Klipper; the explicit block is only for overriding update channel, pinned commit, or refresh interval. Current behavior is correct.
