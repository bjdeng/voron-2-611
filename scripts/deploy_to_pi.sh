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

# Polling parameters for wait_for_klipper_ready. Overridable for tests.
# READY_POLL_INTERVAL=0 is valid (POSIX sleep accepts 0); tests override to 0.
READY_POLL_INTERVAL="${READY_POLL_INTERVAL:-1}"
READY_POLL_MAX="${READY_POLL_MAX:-30}"

# ERE pattern matching the SAVE_CONFIG marker line that Klipper writes at
# the bottom of printer.cfg. Used wherever we split body from tail.
# -E across all sed sites; BSD sed (macOS) doesn't support \+ in BRE.
SAVE_CONFIG_MARKER='^#\*# <-+ SAVE_CONFIG -+>'

trap 'rm -f "${SAVE_CONFIG_PI:-}" "${STAGED_PRINTER_CFG:-}"' EXIT

# ---------------------------------------------------------------------------

parse_flags() {
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

check_ci_green() {
  # gh run list --commit <sha> filter is unreliable (returns [] even when a
  # matching run exists by ID). Query latest run on the branch and verify
  # its headSha matches HEAD locally.
  local response head_sha status conclusion
  response=$(gh run list --branch main --limit 1 --json headSha,status,conclusion)
  if [[ "$response" == "[]" ]]; then
    echo "ERR: CI not green: no run found on origin/main. Push and wait for CI." >&2
    exit 1
  fi
  read -r head_sha status conclusion < <(printf '%s' "$response" | python3 -c \
    "import json,sys; r=json.load(sys.stdin)[0]; print(r['headSha'], r['status'], r.get('conclusion') or '-')" \
    2>/dev/null) || {
    echo "ERR: could not parse latest CI run from gh output. Raw response: $response" >&2
    exit 1
  }
  if [[ "$head_sha" != "$LOCAL" ]]; then
    echo "ERR: CI not green: latest run on main is for $head_sha, not HEAD ($LOCAL). Push and wait for CI." >&2
    exit 1
  fi
  case "$status" in
    in_progress|queued|requested|waiting|pending)
      echo "ERR: CI not green: run for HEAD ($LOCAL) is $status. Wait and re-run." >&2
      exit 1 ;;
    completed) ;;
    *)
      echo "ERR: CI not green: unrecognized status '$status' for HEAD ($LOCAL)." >&2
      exit 1 ;;
  esac
  case "$conclusion" in
    success|skipped) ;;  # green or intentionally-skipped (Open Investigation #7)
    *)
      echo "ERR: CI not green: latest run for HEAD ($LOCAL) conclusion is '$conclusion'." >&2
      exit 1 ;;
  esac
}

check_ssh_reachable() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$PI_HOST" 'true' 2>/dev/null; then
    echo "ERR: can't reach $PI_HOST via keyed SSH. Set up the key or set PI_HOST." >&2
    exit 1
  fi
}

check_moonraker_reachable() {
  if ! curl -fsS -o /dev/null --max-time 5 "$PI_API/server/info"; then
    echo "ERR: Moonraker not reachable at $PI_API. Deploy aborted (restart step would fail anyway)." >&2
    exit 1
  fi
}

check_printer_idle() {
  local resp state
  resp=$(curl -fsS --max-time 5 "$PI_API/printer/objects/query?print_stats")
  state=$(printf '%s' "$resp" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d['result']['status']['print_stats']['state'])" \
    2>/dev/null) || { echo "ERR: could not parse print_stats response from Moonraker. Is Klippy running?" >&2; exit 1; }
  if [[ "$state" != "standby" ]]; then
    echo "ERR: printer is not idle (state=$state). Deploy aborted; wait for print to finish or cancel it." >&2
    exit 1
  fi
}

capture_save_config() {
  echo "==> Capturing Pi's current SAVE_CONFIG block"
  SAVE_CONFIG_PI=$(mktemp)
  # shellcheck disable=SC2029 # $SAVE_CONFIG_MARKER intentionally expands on the client side
  ssh "$PI_HOST" "sed -nE '/$SAVE_CONFIG_MARKER/,\$p' ~/printer_data/config/printer.cfg" > "$SAVE_CONFIG_PI"
  if [[ ! -s "$SAVE_CONFIG_PI" ]]; then
    echo "WARN: no SAVE_CONFIG block found in Pi's printer.cfg. Continuing without one." >&2
  fi
}

check_no_pi_drift() {
  # Compare Pi's printer.cfg body to the repo's, ignoring whitespace-only
  # differences. Mainsail saves with trailing whitespace that pre-commit
  # strips here; the gate's intent is to catch SEMANTIC edits (Mainsail
  # changes, manual SSH tweaks), not whitespace produced by the round-trip.
  local pi_full
  pi_full=$(ssh "$PI_HOST" 'cat ~/printer_data/config/printer.cfg')
  if ! diff -q -w -B \
      <(printf '%s\n' "$pi_full" | sed -E "/$SAVE_CONFIG_MARKER/,\$d") \
      <(sed -E "/$SAVE_CONFIG_MARKER/,\$d" "$REPO_ROOT/printer.cfg") \
      >/dev/null; then
    echo "ERR: Pi printer.cfg body has drifted from origin/main. Run sync-from-pi to capture changes, then re-run deploy-to-pi." >&2
    exit 1
  fi
}

build_staged_printer_cfg() {
  # Stage repo printer.cfg minus its own SAVE_CONFIG block, then append Pi's.
  STAGED_PRINTER_CFG=$(mktemp)
  sed -E "/$SAVE_CONFIG_MARKER/,\$d" printer.cfg > "$STAGED_PRINTER_CFG"
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
  # on the Pi) and HEAD. Default to firmware_restart whenever we can't be
  # sure — this includes a missing marker (fresh deploy) and an unrecognized
  # SHA (corrupt marker, from another repo, etc.).
  local deploy_marker_raw changed
  deploy_marker_raw=$(ssh "$PI_HOST" 'cat ~/printer_data/config/.last-deploy-sha 2>/dev/null || true')
  RESTART_KIND="firmware_restart"
  if [[ -z "$deploy_marker_raw" ]]; then
    return
  fi
  if ! changed=$(git diff --name-only "$deploy_marker_raw" main 2>/dev/null); then
    echo "WARN: deploy marker SHA '$deploy_marker_raw' not in git history. Treating as fresh deploy (firmware_restart)." >&2
    return
  fi
  if [[ -z "$changed" ]]; then
    # Marker matches HEAD: nothing changed. Soft restart is fine.
    RESTART_KIND="restart"
    return
  fi
  # If any changed file is OUTSIDE macros/ / archive/ / printer.cfg, MCU-level
  # state may have moved — firmware_restart. Otherwise soft restart is enough.
  if printf '%s\n' "$changed" | grep -vE '^(macros/|archive/|printer\.cfg$)' >/dev/null; then
    RESTART_KIND="firmware_restart"
  else
    RESTART_KIND="restart"
  fi
}

show_plan_and_confirm() {
  echo "==> Files to sync to ${PI_HOST}:~/printer_data/config/"
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "(--dry-run: skipping rsync preview; no network calls to Pi will be made)"
  else
    # Preview is informational. If it fails (e.g., transient network), let
    # do_rsync's hard-fail-and-exit-2 path be the authoritative failure.
    rsync -av --dry-run "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/" \
      | tail -20 || echo "(preview unavailable; do_rsync will report the real failure)"
  fi

  echo
  echo "==> printer.cfg will be uploaded with the Pi's SAVE_CONFIG block re-appended."
  echo "==> Restart kind chosen: $RESTART_KIND"
  echo
  if [[ "$YES" == 1 ]]; then
    echo "(--yes given, proceeding without prompt)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    # stdin not a TTY (running under pytest); auto-confirm
    return 0
  fi
  local answer
  read -r -p "Proceed? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
}

do_rsync() {
  rsync -av "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "${PI_HOST}:~/printer_data/config/" || {
    echo "ERR: rsync failed mid-deploy. Pi state may be partially updated; run sync-from-pi to inspect." >&2
    exit 2
  }
  scp -q "$STAGED_PRINTER_CFG" "${PI_HOST}:~/printer_data/config/printer.cfg" || {
    echo "ERR: scp of staged printer.cfg failed mid-deploy. Pi state may be partially updated; run sync-from-pi to inspect." >&2
    exit 2
  }
}

update_deploy_marker() {
  # Record the deploy SHA so the next deploy can pick the right restart kind.
  # $LOCAL intentionally expands on the client side before being sent to the Pi.
  # shellcheck disable=SC2029
  ssh "$PI_HOST" "echo '$LOCAL' > ~/printer_data/config/.last-deploy-sha" || {
    echo "ERR: failed to write deploy marker on Pi. Files synced; next deploy will treat this as a fresh deploy." >&2
    exit 2
  }
}

trigger_restart() {
  echo
  echo "==> Calling Moonraker /printer/$RESTART_KIND"
  local restart_resp
  restart_resp=$(curl -fsS -X POST "$PI_API/printer/$RESTART_KIND") || {
    echo "ERR: Moonraker restart call failed. Files are synced but Klipper was not restarted. Check klippy.log on the Pi." >&2
    exit 2
  }
  echo "Moonraker response:"
  printf '%s\n' "$restart_resp"
  echo
}

wait_for_klipper_ready() {
  local i resp state state_msg
  for i in $(seq 1 "$READY_POLL_MAX"); do
    sleep "$READY_POLL_INTERVAL"
    resp=$(curl -fsS --max-time 3 "$PI_API/printer/info" 2>/dev/null || true)
    if [[ -z "$resp" ]]; then continue; fi
    state=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['state'])" 2>/dev/null || echo "")
    state_msg=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['result'].get('state_message',''))" 2>/dev/null || echo "")
    case "$state" in
      ready)
        echo "==> Klipper state=ready (after ${i} poll(s))"
        return 0 ;;
      error)
        echo "ERR: Klipper failed to start: $state_msg" >&2
        exit 3 ;;
      startup|"") continue ;;
      *) continue ;;
    esac
  done
  echo "ERR: Klipper did not reach 'ready' within ${READY_POLL_MAX}s. Inspect klippy.log." >&2
  exit 3
}

cleanup() {
  rm -f "$SAVE_CONFIG_PI" "$STAGED_PRINTER_CFG"

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
  check_ci_green                   # ← NEW
  check_ssh_reachable
  check_moonraker_reachable
  check_printer_idle
  capture_save_config
  check_no_pi_drift
  build_staged_printer_cfg
  build_rsync_excludes
  choose_restart_kind
  show_plan_and_confirm
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "==> --dry-run: no changes made to Pi."
    cleanup
    exit 0
  fi
  do_rsync
  update_deploy_marker
  trigger_restart
  wait_for_klipper_ready
  cleanup
}

main "$@"
