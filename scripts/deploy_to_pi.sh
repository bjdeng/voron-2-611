#!/usr/bin/env bash
# Deploy HEAD on main to pi@mainsailos.local:~/printer_data/config/.
#
# See .claude/skills/deploy-to-pi/SKILL.md for the full contract.
# This is a starting implementation — works for the common case (rsync +
# Moonraker restart). The smarter "diff-based RESTART vs FIRMWARE_RESTART"
# heuristic is roughed in; refine before relying on it for risky changes.

set -euo pipefail

PI_HOST="${PI_HOST:-pi@mainsailos.local}"
PI_API="${PI_API:-http://mainsailos.local:7125}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"

# --- Pre-flight ---

BRANCH=$(git branch --show-current)
if [[ "$BRANCH" != "main" ]]; then
  echo "ERR: deploy refuses to run from '$BRANCH'. Switch to main and merge your changes first." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERR: working tree not clean. Commit or stash before deploying." >&2
  git status -sb >&2
  exit 1
fi

git fetch --quiet origin main
LOCAL=$(git rev-parse main)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "ERR: local main is not in sync with origin/main." >&2
  echo "  local:  $LOCAL"  >&2
  echo "  remote: $REMOTE" >&2
  echo "Run \`git pull\` or \`git push\` first." >&2
  exit 1
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; then
  echo "ERR: can't reach $PI_HOST via keyed SSH. Set up the key or set PI_HOST." >&2
  exit 1
fi

if ! curl -fsS -o /dev/null --max-time 5 "$PI_API/server/info"; then
  echo "WARN: Moonraker not responding at $PI_API. Deploy will proceed but restart step will fail." >&2
fi

# --- Preserve the Pi's current SAVE_CONFIG block ---

echo "==> Capturing Pi's current SAVE_CONFIG block"
SAVE_CONFIG_PI=$(mktemp)
ssh "$PI_HOST" 'sed -n "/^#\*# <-+ SAVE_CONFIG -\+>/,$p" ~/printer_data/config/printer.cfg' > "$SAVE_CONFIG_PI"
if [[ ! -s "$SAVE_CONFIG_PI" ]]; then
  echo "WARN: no SAVE_CONFIG block found in Pi's printer.cfg. Continuing without one." >&2
fi

# Stage repo printer.cfg minus its own SAVE_CONFIG block, then append Pi's.
STAGED_PRINTER_CFG=$(mktemp)
sed '/^#\*# <-+ SAVE_CONFIG -\+>/,$d' printer.cfg > "$STAGED_PRINTER_CFG"
if [[ -s "$SAVE_CONFIG_PI" ]]; then
  printf '\n' >> "$STAGED_PRINTER_CFG"
  cat "$SAVE_CONFIG_PI" >> "$STAGED_PRINTER_CFG"
fi

# --- Construct rsync file set ---
# Include real-config files; explicitly exclude tooling, docs, and the
# symlinked-third-party files that mustn't be overwritten.

RSYNC_EXCLUDES=(
  --exclude='/.git/'
  --exclude='/.github/'
  --exclude='/.claude/'
  --exclude='/.venv/'
  --exclude='/.worktrees/'
  --exclude='/vendor/'
  --exclude='/scripts/'
  --exclude='/tests/'
  --exclude='/docs/'
  --exclude='/memory/'
  --exclude='/firmware/'
  --exclude='/archive/'
  --exclude='.gitignore'
  --exclude='.pre-commit-config.yaml'
  --exclude='Makefile'
  --exclude='LICENSE'
  --exclude='README.md'
  --exclude='CLAUDE.md'
  --exclude='requirements.txt'
  --exclude='.env'
  --exclude='.env.example'
  # Symlinks on the Pi — don't overwrite them with our dereferenced copies
  --exclude='mainsail.cfg'
  --exclude='timelapse.cfg'
  --exclude='mmu/base/mmu_cut_tip.cfg'
  --exclude='mmu/base/mmu_form_tip.cfg'
  --exclude='mmu/base/mmu_heater_vent.cfg'
  --exclude='mmu/base/mmu_leds.cfg'
  --exclude='mmu/base/mmu_purge.cfg'
  --exclude='mmu/base/mmu_sequence.cfg'
  --exclude='mmu/base/mmu_software.cfg'
  --exclude='mmu/base/mmu_state.cfg'
  --exclude='mmu/optional/client_macros.cfg'
  --exclude='mmu/optional/mmu_menu.cfg'
  --exclude='printer.cfg'   # handled separately via SAVE_CONFIG splice
)

# --- Decide RESTART vs FIRMWARE_RESTART ---

# Look at what changed between the last deploy (recorded in a marker file
# on the Pi) and HEAD. If we have no marker, treat it as a fresh deploy
# and pick firmware_restart to be safe.
DEPLOY_MARKER_RAW=$(ssh "$PI_HOST" 'cat ~/printer_data/config/.last-deploy-sha 2>/dev/null || true')
RESTART_KIND="firmware_restart"
if [[ -n "$DEPLOY_MARKER_RAW" ]]; then
  CHANGED=$(git diff --name-only "$DEPLOY_MARKER_RAW" main 2>/dev/null || echo "")
  if [[ -n "$CHANGED" ]]; then
    # If every changed file is purely a macro or archive, soft restart is enough.
    if printf '%s\n' "$CHANGED" | grep -vE '^(macros/|archive/|printer\.cfg$)' >/dev/null; then
      RESTART_KIND="firmware_restart"
    elif printf '%s\n' "$CHANGED" | grep -qE '^(macros/|archive/|printer\.cfg$)'; then
      RESTART_KIND="restart"
    fi
  else
    RESTART_KIND="restart"
  fi
fi

echo "==> Files to sync to ${PI_HOST}:~/printer_data/config/"
rsync -av --dry-run "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/" \
  | tail -20

echo
echo "==> printer.cfg will be uploaded with the Pi's SAVE_CONFIG block re-appended."
echo "==> Restart kind chosen: $RESTART_KIND"
echo
read -r -p "Proceed? [y/N] " ANSWER
case "$ANSWER" in
  y|Y|yes|YES) ;;
  *) echo "Aborted."; exit 0 ;;
esac

# --- Execute the sync ---

rsync -av "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/"
scp -q "$STAGED_PRINTER_CFG" "${PI_HOST}:~/printer_data/config/printer.cfg"

# Record the deploy SHA so the next deploy can pick the right restart kind.
ssh "$PI_HOST" "echo '$LOCAL' > ~/printer_data/config/.last-deploy-sha"

# --- Trigger Klipper restart via Moonraker ---

echo
echo "==> Calling Moonraker /printer/$RESTART_KIND"
curl -fsS -X POST "$PI_API/printer/$RESTART_KIND" -o /tmp/restart_resp.json || {
  echo "ERR: Moonraker restart call failed. Check klippy.log on the Pi." >&2
  exit 1
}
echo "Moonraker response:"
cat /tmp/restart_resp.json
echo

rm -f "$SAVE_CONFIG_PI" "$STAGED_PRINTER_CFG" /tmp/restart_resp.json

echo
echo "==> Deploy complete. Verify printer state in Mainsail."
