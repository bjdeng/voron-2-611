#!/usr/bin/env bash
# Deploy HEAD on main to pi@mainsailos.local:~/printer_data/config/.
# See .claude/skills/deploy-to-pi/SKILL.md for the full contract.

set -euo pipefail

PI_HOST="${PI_HOST:-pi@mainsailos.local}"
PI_API="${PI_API:-http://mainsailos.local:7125}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Flags (honored in a later task; declared here so parse_flags can set them)
YES=0
DRY_RUN=0

# Globals populated by setup functions
LOCAL=""
SAVE_CONFIG_PI=""
STAGED_PRINTER_CFG=""
RESTART_KIND=""
RSYNC_EXCLUDES=()

# ---------------------------------------------------------------------------

parse_flags() {
  # SC2034: YES/DRY_RUN are scaffolding — honored in a later task
  # shellcheck disable=SC2034
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --yes) YES=1 ;;
      --dry-run) DRY_RUN=1 ;;
      *) echo "ERR: unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
  done
}

check_on_main() {
  local branch
  branch=$(git branch --show-current)
  if [[ "$branch" != "main" ]]; then
    echo "ERR: deploy refuses to run from '$branch'. Switch to main and merge your changes first." >&2
    exit 1
  fi
}

check_tree_clean() {
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERR: working tree not clean. Commit or stash before deploying." >&2
    git status -sb >&2
    exit 1
  fi
}

check_in_sync_with_origin() {
  local remote
  git fetch --quiet origin main
  LOCAL=$(git rev-parse main)
  remote=$(git rev-parse origin/main)
  if [[ "$LOCAL" != "$remote" ]]; then
    echo "ERR: local main is not in sync with origin/main." >&2
    echo "  local:  $LOCAL" >&2
    echo "  remote: $remote" >&2
    echo "Run \`git pull\` or \`git push\` first." >&2
    exit 1
  fi
}

check_ssh_reachable() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; then
    echo "ERR: can't reach $PI_HOST via keyed SSH. Set up the key or set PI_HOST." >&2
    exit 1
  fi
}

check_moonraker_reachable() {
  if ! curl -fsS -o /dev/null --max-time 5 "$PI_API/server/info"; then
    echo "WARN: Moonraker not responding at $PI_API. Deploy will proceed but restart step will fail." >&2
  fi
}

capture_save_config() {
  echo "==> Capturing Pi's current SAVE_CONFIG block"
  SAVE_CONFIG_PI=$(mktemp)
  ssh "$PI_HOST" 'sed -n "/^#\*# <-+ SAVE_CONFIG -\+>/,$p" ~/printer_data/config/printer.cfg' > "$SAVE_CONFIG_PI"
  if [[ ! -s "$SAVE_CONFIG_PI" ]]; then
    echo "WARN: no SAVE_CONFIG block found in Pi's printer.cfg. Continuing without one." >&2
  fi
}

build_staged_printer_cfg() {
  # Stage repo printer.cfg minus its own SAVE_CONFIG block, then append Pi's.
  STAGED_PRINTER_CFG=$(mktemp)
  sed '/^#\*# <-+ SAVE_CONFIG -\+>/,$d' printer.cfg > "$STAGED_PRINTER_CFG"
  if [[ -s "$SAVE_CONFIG_PI" ]]; then
    printf '\n' >> "$STAGED_PRINTER_CFG"
    cat "$SAVE_CONFIG_PI" >> "$STAGED_PRINTER_CFG"
  fi
}

build_rsync_excludes() {
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
}

choose_restart_kind() {
  # Look at what changed between the last deploy (recorded in a marker file
  # on the Pi) and HEAD. If we have no marker, treat it as a fresh deploy
  # and pick firmware_restart to be safe.
  local deploy_marker_raw changed
  deploy_marker_raw=$(ssh "$PI_HOST" 'cat ~/printer_data/config/.last-deploy-sha 2>/dev/null || true')
  RESTART_KIND="firmware_restart"
  if [[ -n "$deploy_marker_raw" ]]; then
    changed=$(git diff --name-only "$deploy_marker_raw" main 2>/dev/null || echo "")
    if [[ -n "$changed" ]]; then
      # If every changed file is purely a macro or archive, soft restart is enough.
      if printf '%s\n' "$changed" | grep -vE '^(macros/|archive/|printer\.cfg$)' >/dev/null; then
        RESTART_KIND="firmware_restart"
      elif printf '%s\n' "$changed" | grep -qE '^(macros/|archive/|printer\.cfg$)'; then
        RESTART_KIND="restart"
      fi
    else
      RESTART_KIND="restart"
    fi
  fi
}

show_plan_and_confirm() {
  echo "==> Files to sync to ${PI_HOST}:~/printer_data/config/"
  rsync -av --dry-run "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/" \
    | tail -20

  echo
  echo "==> printer.cfg will be uploaded with the Pi's SAVE_CONFIG block re-appended."
  echo "==> Restart kind chosen: $RESTART_KIND"
  echo
  local answer
  read -r -p "Proceed? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
}

do_rsync() {
  rsync -av "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/"
  scp -q "$STAGED_PRINTER_CFG" "${PI_HOST}:~/printer_data/config/printer.cfg"
}

update_deploy_marker() {
  # Record the deploy SHA so the next deploy can pick the right restart kind.
  # $LOCAL intentionally expands on the client side before being sent to the Pi.
  # shellcheck disable=SC2029
  ssh "$PI_HOST" "echo '$LOCAL' > ~/printer_data/config/.last-deploy-sha"
}

trigger_restart() {
  echo
  echo "==> Calling Moonraker /printer/$RESTART_KIND"
  curl -fsS -X POST "$PI_API/printer/$RESTART_KIND" -o /tmp/restart_resp.json || {
    echo "ERR: Moonraker restart call failed. Check klippy.log on the Pi." >&2
    exit 1
  }
  echo "Moonraker response:"
  cat /tmp/restart_resp.json
  echo
}

cleanup() {
  rm -f "$SAVE_CONFIG_PI" "$STAGED_PRINTER_CFG" /tmp/restart_resp.json

  echo
  echo "==> Deploy complete. Verify printer state in Mainsail."
}

# ---------------------------------------------------------------------------

main() {
  parse_flags "$@"
  cd "$REPO_ROOT"
  check_on_main
  check_tree_clean
  check_in_sync_with_origin
  check_ssh_reachable
  check_moonraker_reachable
  capture_save_config
  build_staged_printer_cfg
  build_rsync_excludes
  choose_restart_kind
  show_plan_and_confirm
  do_rsync
  update_deploy_marker
  trigger_restart
  cleanup
}

main "$@"
