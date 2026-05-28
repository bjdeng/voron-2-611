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
SMOKE=0
FORCE=0

# Set at each terminal point; consumed by the deploy log (see log_deploy).
DEPLOY_RESULT="incomplete"

# Globals populated by setup functions
LOCAL=""
SAVE_CONFIG_PI=""
STAGED_PRINTER_CFG=""
RESTART_KIND=""
RSYNC_EXCLUDES=()
PI_SYMLINK_EXCLUDES=()

# Polling parameters for wait_for_klipper_ready. Overridable for tests.
# READY_POLL_INTERVAL=0 is valid (POSIX sleep accepts 0); tests override to 0.
READY_POLL_INTERVAL="${READY_POLL_INTERVAL:-1}"
READY_POLL_MAX="${READY_POLL_MAX:-60}"

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
      --smoke) SMOKE=1 ;;
      --force) FORCE=1 ;;
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

discover_pi_symlinks() {
  # Find every symlink under ~/printer_data/config/ on the Pi. rsync would
  # otherwise replace these with the source's dereferenced content, breaking
  # third-party install models (Happy-Hare, mainsail-config, moonraker-
  # timelapse all use symlinks here).
  #
  # Hard-fail on ssh/find failure: silent fallback to "no excludes" would
  # destructively overwrite every Pi-side symlink, which is exactly what
  # this function exists to prevent.
  local raw relpath
  PI_SYMLINK_EXCLUDES=()
  if ! raw=$(ssh "$PI_HOST" 'cd ~/printer_data/config && find . -type l -printf "%P\n"' 2>&1); then
    echo "ERR: could not discover Pi-side symlinks (ssh or find failed):" >&2
    printf '  %s\n' "$raw" >&2
    echo "ERR: aborting — refusing to deploy without symlink-safety excludes." >&2
    exit 1
  fi
  while IFS= read -r relpath; do
    [[ -z "$relpath" ]] && continue
    PI_SYMLINK_EXCLUDES+=(--exclude="/$relpath")
  done <<< "$raw"
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

cant_verify_or_force() {
  # Fail-closed guard for the drift gate. $1 = human-readable reason.
  # With --force: warn and let the caller skip its check. Without: refuse.
  if [[ "$FORCE" == 1 ]]; then
    echo "WARN: drift gate cannot verify Pi state ($1); --force given, proceeding." >&2
    return 0
  fi
  echo "ERR: drift gate cannot verify Pi state: $1" >&2
  echo "Refusing to deploy (fail-closed). Fix the cause, or pass --force to override." >&2
  DEPLOY_RESULT="refused:cant-verify"
  exit 1
}

check_no_pi_drift() {
  # The gate's intent: catch SEMANTIC edits on the Pi (Mainsail changes,
  # manual SSH tweaks) that weren't synced back to git. NOT to block
  # legitimate repo-ahead deploys (which is the whole point of running this).
  #
  # Compare Pi's printer.cfg body to the version AT THE LAST-DEPLOYED COMMIT
  # (recorded in ~/printer_data/config/.last-deploy-sha). Any difference =
  # the Pi has changes the repo doesn't know about → Pi-ahead drift → fail.
  #
  # Fail-closed: if the marker is missing or its SHA isn't in git history,
  # refuse unless --force.
  #
  # Mainsail saves with trailing whitespace that pre-commit strips here;
  # diff -w -B ignores whitespace-only changes either way.
  #
  # NOTE: pi_full and deploy_marker_raw come from two separate ssh calls.
  # In theory another concurrent deploy could slip between them and we'd
  # be comparing the new Pi cfg against the old marker. In practice this
  # is single-user single-printer so the window is irrelevant.
  local pi_full pi_body deploy_marker_raw reference_body
  pi_full=$(ssh "$PI_HOST" 'cat ~/printer_data/config/printer.cfg')
  pi_body=$(printf '%s\n' "$pi_full" | sed -E "/$SAVE_CONFIG_MARKER/,\$d")

  deploy_marker_raw=$(ssh "$PI_HOST" 'cat ~/printer_data/config/.last-deploy-sha 2>/dev/null || true')
  if [[ -z "$deploy_marker_raw" ]]; then
    cant_verify_or_force "no deploy marker on Pi (.last-deploy-sha missing)"
    return 0
  fi
  if ! reference_body=$(git show "$deploy_marker_raw:config/printer.cfg" 2>/dev/null); then
    cant_verify_or_force "deploy marker SHA '$deploy_marker_raw' not in git history"
    return 0
  fi
  reference_body=$(printf '%s\n' "$reference_body" | sed -E "/$SAVE_CONFIG_MARKER/,\$d")
  if [[ -z "$reference_body" ]]; then
    cant_verify_or_force "marker '$deploy_marker_raw' yielded empty printer.cfg reference"
    return 0
  fi
  if ! diff -q -w -B <(printf '%s\n' "$pi_body") <(printf '%s\n' "$reference_body") >/dev/null; then
    echo "ERR: Pi printer.cfg body has drifted from the last-deployed commit ($deploy_marker_raw). Run sync-from-pi to capture changes, then re-run deploy-to-pi." >&2
    DEPLOY_RESULT="refused:pi-drift"
    exit 1
  fi
}

check_no_pi_drift_all_files() {
  # Extended drift gate (#105): the original check_no_pi_drift only covers
  # printer.cfg. This catches Pi-side edits to ANY deployed file
  # (mmu_parameters.cfg, macros/*, eddy.cfg, etc.) by comparing each
  # against the version at the last-deployed commit.
  #
  # Approach: stage the last-deployed snapshot locally via `git archive`,
  # then `rsync -anci --checksum` it against the Pi. Any file rsync would
  # transfer (output line starting with '>f') = Pi-side drift.
  #
  # Skips:
  #   - First-deploy (no marker on Pi) — no reference to compare against
  #   - Marker SHA not in git history — same
  #   - printer.cfg — handled by check_no_pi_drift's body-only compare
  #   - Everything in RSYNC_EXCLUDES — symlinks, mmu_vars.cfg, adxl_results, etc.
  #
  # Bypassed by --force when the user genuinely wants to overwrite Pi-side
  # changes (e.g., reverting a Pi-side experiment without round-tripping
  # through /sync-from-pi).
  local marker_sha snapshot_dir drift_lines drift_files
  marker_sha=$(ssh "$PI_HOST" 'cat ~/printer_data/config/.last-deploy-sha 2>/dev/null || true')
  if [[ -z "$marker_sha" ]]; then
    cant_verify_or_force "no deploy marker on Pi (.last-deploy-sha missing)"
    return 0
  fi
  if ! git rev-parse --quiet --verify "${marker_sha}^{commit}" >/dev/null 2>&1; then
    cant_verify_or_force "deploy marker SHA '$marker_sha' not in git history"
    return 0
  fi

  snapshot_dir=$(mktemp -d)
  # shellcheck disable=SC2064 # snapshot_dir expansion at trap-set time is intentional
  trap "rm -rf '$snapshot_dir'" RETURN
  if ! git archive "$marker_sha" config/ 2>/dev/null | tar -x -C "$snapshot_dir" 2>/dev/null; then
    cant_verify_or_force "git archive of marker snapshot failed"
    return 0
  fi
  if [[ ! -d "$snapshot_dir/config" ]]; then
    cant_verify_or_force "marker snapshot has no config/ dir"
    return 0
  fi

  # Compare via SHA-256. Reasons not to use `rsync -anci --checksum`:
  #   - macOS bundles rsync 2.6.9 (2006). --checksum in --dry-run is
  #     unreliable across versions (false positives on identical content
  #     with different mtimes — observed live on 2026-05-21 incident).
  #   - sha256sum-based comparison is deterministic, one round-trip per
  #     side, version-agnostic, and survives the fresh-mtime noise that
  #     `git archive` always introduces.
  local hasher
  if command -v sha256sum >/dev/null 2>&1; then
    hasher="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    hasher="shasum -a 256"
  else
    cant_verify_or_force "no local sha256 tool (sha256sum/shasum)"
    return 0
  fi

  # Build `find` -path prune patterns mirroring RSYNC_EXCLUDES, plus the
  # dynamic symlinks from discover_pi_symlinks (their dereferenced content
  # lives in the snapshot but the Pi has them as symlinks — comparing
  # would always fire as drift).
  local -a find_prune
  find_prune=(
    -path './firmware' -o
    -path './archive' -o
    -path './printer.cfg' -o
    -path './printer-*.cfg' -o
    -path './mmu/mmu_vars.cfg' -o
    -path './mmu-*' -o
    -path './.last-deploy-sha' -o
    -path './.moonraker.conf.bkp' -o
    -path './adxl_results' -o
    -path './adxl_results/*'
  )
  local sym rel
  for sym in "${PI_SYMLINK_EXCLUDES[@]}"; do
    # Entries look like "--exclude=/relpath"; strip the prefix.
    rel="${sym#--exclude=/}"
    find_prune+=(-o -path "./$rel")
  done

  # Hash the snapshot (one local pass).
  local snapshot_hashes pi_hashes drift_files prune_expr
  snapshot_hashes=$(cd "$snapshot_dir/config" && find . \( "${find_prune[@]}" \) -prune -o -type f -print0 \
    | xargs -0 $hasher 2>/dev/null \
    | sed -E 's| +\./| |' \
    | sort)

  # Same on the Pi (one ssh round-trip). Build a quoted expression we can
  # send to the remote shell. Use printf with %q for safety.
  prune_expr=""
  local arg
  for arg in "${find_prune[@]}"; do
    prune_expr+=$(printf '%q ' "$arg")
  done
  # shellcheck disable=SC2029 # $prune_expr expands client-side intentionally
  pi_hashes=$(ssh "$PI_HOST" "cd ~/printer_data/config && find . \\( $prune_expr \\) -prune -o -type f -print0 | xargs -0 sha256sum 2>/dev/null | sed -E 's| +\\./| |' | sort" 2>/dev/null)

  # Refuse only when we couldn't read the PI side (ssh/find failed) while the
  # marker snapshot has files — that's the real "can't verify" risk. An empty
  # snapshot is benign here: a git-archive failure was already caught above, so
  # empty just means no baseline files to compare and proceeding can't clobber.
  if [[ -n "$snapshot_hashes" && -z "$pi_hashes" ]]; then
    cant_verify_or_force "could not read file hashes from the Pi"
    return 0
  fi

  # Find files where the Pi hash differs from the snapshot hash. Only
  # consider files present in BOTH sides (a snapshot-only file means the
  # Pi is missing it — rsync will create it; a Pi-only file is repo-side
  # absence — handled by the existing --delete logic).
  # Format: "HEX  PATH"; key by PATH.
  drift_files=$(awk '
    NR==FNR { snap[$2] = $1; next }
    { if ($2 in snap && snap[$2] != $1) print $2 }
  ' <(printf '%s\n' "$snapshot_hashes") <(printf '%s\n' "$pi_hashes"))

  if [[ -z "$drift_files" ]]; then
    return 0
  fi

  if [[ "$FORCE" == 1 ]]; then
    echo "==> Pi-side drift detected on the following files (--force given, proceeding):"
    printf '    %s\n' $drift_files
    return 0
  fi

  echo "ERR: Pi has changes the repo doesn't know about on these files:" >&2
  printf '    %s\n' $drift_files >&2
  echo "" >&2
  echo "Run /sync-from-pi to capture them into the repo, then re-run /deploy-to-pi." >&2
  echo "Or pass --force to overwrite Pi-side changes (only when you're sure they're wrong)." >&2
  exit 1
}

build_staged_printer_cfg() {
  # Stage repo printer.cfg minus its own SAVE_CONFIG block, then append Pi's.
  STAGED_PRINTER_CFG=$(mktemp)
  sed -E "/$SAVE_CONFIG_MARKER/,\$d" "$REPO_ROOT/config/printer.cfg" > "$STAGED_PRINTER_CFG"
  if [[ -s "$SAVE_CONFIG_PI" ]]; then
    printf '\n' >> "$STAGED_PRINTER_CFG"
    cat "$SAVE_CONFIG_PI" >> "$STAGED_PRINTER_CFG"
  fi
}

build_rsync_excludes() {
  # rsync source is config/, so tooling paths (scripts/, vendor/, tests/,
  # docs/, memory/, .github/, .claude/, Makefile, README.md, CLAUDE.md, etc.)
  # live OUTSIDE the source and don't need explicit excludes.
  #
  # Inside config/ we still exclude:
  #   firmware/ — build kconfigs aren't deployed (they're flash-time inputs)
  #   archive/  — historical configs we don't run
  #   printer.cfg — handled separately via SAVE_CONFIG splice
  #   mmu/mmu_vars.cfg — Klipper [save_variables] file. Pi is canonical.
  #                      Klipper rewrites it on every MMU operation. Repo's
  #                      copy is a backup snapshot maintained by sync-from-pi.
  #                      Never deploy. Drift summary in check_mmu_vars_drift().
  #
  # We also protect Pi-managed state from the --delete pass below.
  # rsync's --exclude protects matched paths from BOTH transfer and
  # deletion, so listing them here keeps them on the Pi even though they
  # aren't in the repo source:
  #   printer-*.cfg — Klipper SAVE_CONFIG rotations (rollback safety net,
  #                   one per SAVE_CONFIG invocation; see CLAUDE.md
  #                   ## Known quirks for why we keep these on the Pi).
  #   mmu-*         — defensive against any future Klipper rotation of
  #                   MMU state following the same name-TIMESTAMP pattern.
  #                   Already in .gitignore (line 12); preserving that intent.
  #   .last-deploy-sha   — written by this script; consulted on next
  #                        deploy to choose restart vs firmware_restart.
  #   .moonraker.conf.bkp — Moonraker's own backup of moonraker.conf,
  #                         rewritten on Moonraker restart.
  #   adxl_results/        — Klipper input_shaper + chopper-resonance-tuner
  #                         output PNGs/CSVs. .gitignored, generated on Pi
  #                         only. Deleting them on every deploy loses hours
  #                         of calibration history (closes #101).
  #
  # Plus the dynamic symlink list from discover_pi_symlinks (those are
  # symlinks pointing into upstream install dirs like ~/Happy-Hare/ and
  # ~/mainsail-config/ — deleting them would mutate the upstream repos).
  RSYNC_EXCLUDES=(
    --exclude='/firmware/'
    --exclude='/archive/'
    --exclude='/printer.cfg'
    --exclude='/printer-*.cfg'
    --exclude='/mmu/mmu_vars.cfg'
    --exclude='/mmu-*'
    --exclude='/.last-deploy-sha'
    --exclude='/.moonraker.conf.bkp'
    --exclude='/adxl_results/'
  )
  RSYNC_EXCLUDES+=("${PI_SYMLINK_EXCLUDES[@]}")
}

check_mmu_vars_drift() {
  # mmu_vars.cfg is Klipper [save_variables] state — rewritten on every MMU
  # operation. The Pi is canonical. The repo's copy is a periodic backup
  # snapshot maintained by /sync-from-pi. We never deploy it (see rsync
  # exclude above). This function reports whether the repo's backup is in
  # sync with the Pi so the user can decide whether to /sync-from-pi.
  local repo_path="$REPO_ROOT/config/mmu/mmu_vars.cfg"

  if [[ ! -f "$repo_path" ]]; then
    echo "==> mmu_vars.cfg: no repo snapshot present. Deploy skipped (Pi-managed). Run /sync-from-pi to create a backup."
    return
  fi

  local pi_exists
  pi_exists=$(ssh "$PI_HOST" 'test -f ~/printer_data/config/mmu/mmu_vars.cfg && echo yes || echo no' 2>/dev/null)
  if [[ "$pi_exists" != "yes" ]]; then
    echo "==> mmu_vars.cfg: not present on Pi (Klipper will create on first MMU [save_variables] write). Deploy skipped."
    return
  fi

  # Compare via diff -q: streams Pi content through ssh, byte-compares to
  # local file. Avoids hash-tool portability questions (macOS md5 vs Linux
  # md5sum) and the need for temp files.
  if diff -q <(ssh "$PI_HOST" 'cat ~/printer_data/config/mmu/mmu_vars.cfg' 2>/dev/null) "$repo_path" >/dev/null 2>&1; then
    echo "==> mmu_vars.cfg: Pi-managed state, deploy skipped (in sync with repo snapshot)."
  else
    echo "==> mmu_vars.cfg: Pi-managed state, deploy skipped. Repo snapshot differs from Pi — run /sync-from-pi to update the backup if desired."
  fi
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
  # If any changed file is OUTSIDE config/macros/, config/archive/, or
  # config/printer.cfg, MCU-level state may have moved — firmware_restart.
  # Otherwise soft restart is enough.
  if printf '%s\n' "$changed" | grep -vE '^config/(macros/|archive/|printer\.cfg$)' >/dev/null; then
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
    rsync -av --delete --dry-run "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/config/" "${PI_HOST}:~/printer_data/config/" \
      | tail -20 || echo "(preview unavailable; do_rsync will report the real failure)"
  fi

  echo
  echo "==> printer.cfg will be uploaded with the Pi's SAVE_CONFIG block re-appended."
  check_mmu_vars_drift
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
  # --delete + the protective excludes in build_rsync_excludes() make
  # the deploy self-cleaning: anything that lives on the Pi but isn't
  # in our source AND isn't on the protect list gets wiped. See the
  # comment block in build_rsync_excludes() for what's protected and why.
  rsync -av --delete "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/config/" "${PI_HOST}:~/printer_data/config/" || {
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

run_post_deploy_smoke() {
  # Layer 6 of the test pyramid. See scripts/printer-smoke.sh for the
  # gcode sequence + what it catches. Opt-in via --smoke because the
  # physical G28 is a real toolhead movement; users with hands inside
  # the printer need to know it's coming.
  echo
  echo "==> Running L6 post-deploy smoke (--smoke)"
  local rc=0
  PI_HOST="$PI_HOST" PI_API="$PI_API" "$REPO_ROOT/scripts/printer-smoke.sh" || rc=$?
  if (( rc != 0 )); then
    echo "ERR: post-deploy smoke FAILED (rc=$rc). Klipper is up but the deployed config" >&2
    echo "    has runtime regressions. Inspect ~/printer_data/logs/klippy.log on the Pi" >&2
    echo "    and roll back via the procedure in .claude/skills/deploy-to-pi/SKILL.md." >&2
    exit 4
  fi
}

cleanup() {
  rm -f "$SAVE_CONFIG_PI" "$STAGED_PRINTER_CFG"
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
  discover_pi_symlinks
  check_moonraker_reachable
  check_printer_idle
  capture_save_config
  check_no_pi_drift
  build_staged_printer_cfg
  build_rsync_excludes
  check_no_pi_drift_all_files
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
  if [[ "$SMOKE" == 1 ]]; then
    run_post_deploy_smoke
  fi
  cleanup
  echo
  echo "==> Deploy complete. Verify printer state in Mainsail."
}

main "$@"
