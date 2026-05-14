#!/usr/bin/env bash
# Sync configs from pi@mainsailos.local into this repo's working tree.
#
# - Pulls everything under ~/printer_data/config/ that isn't a timestamped
#   Klipper backup (printer-YYYYMMDD_*.cfg, mmu-YYYYMMDD_*).
# - Dereferences symlinks with `tar -h` so this repo has self-contained
#   copies of mainsail.cfg, timelapse.cfg, mmu/base/*.cfg.
# - Shows a unified diff vs the current working tree, then prompts to apply.
#
# Does NOT commit. The user reviews the diff and commits manually.

set -euo pipefail

PI_HOST="${PI_HOST:-pi@mainsailos.local}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING="${REPO_ROOT}/.sync-staging-$$"
TARBALL="/tmp/voron-pi-sync-$$.tar.gz"

cleanup() {
  rm -rf "$STAGING" "$TARBALL"
  ssh -o BatchMode=yes "$PI_HOST" "rm -f /tmp/voron-pi-sync.tar.gz" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Syncing from ${PI_HOST}"
echo

# 1. Tar on the Pi, exclude rotation backups, dereference symlinks.
ssh "$PI_HOST" bash -s <<'REMOTE'
set -euo pipefail
cd ~/printer_data/config
tar \
  --exclude='printer-2*.cfg' \
  --exclude='mmu-2*' \
  --exclude='__pycache__' \
  -czhf /tmp/voron-pi-sync.tar.gz .
REMOTE

# 2. Pull the tarball.
scp -q "${PI_HOST}:/tmp/voron-pi-sync.tar.gz" "$TARBALL"

# 3. Extract to staging.
mkdir -p "$STAGING"
tar -xzf "$TARBALL" -C "$STAGING"

# 4. Diff.
echo "==> Diff vs working tree (additions on the Pi shown as +; lines removed shown as -):"
echo
DIFF_EXCLUDES=(
  # Repo-only dirs that don't exist on the Pi — preserve via diff exclude.
  --exclude='firmware'
  --exclude='archive'
)
if diff -ruN "${DIFF_EXCLUDES[@]}" "$REPO_ROOT/config" "$STAGING"; then
  echo
  echo "==> Repo matches the Pi. Nothing to sync."
  exit 0
fi

echo
read -r -p "==> Apply these changes to the working tree? [y/N] " ANSWER
case "$ANSWER" in
  y|Y|yes|YES) ;;
  *) echo "Aborted."; exit 0 ;;
esac

# 5. Apply via rsync (deletes files the Pi removed; preserves repo-only paths via excludes).
# Destination is REPO_ROOT/config/, so tooling at the repo root is naturally
# out-of-scope. Only excludes here are paths that DO live under config/ and
# either belong to the repo (don't delete) or belong to the Pi's per-session
# state (don't import).
rsync -av \
  --exclude='/firmware/' \
  --exclude='/archive/' \
  --exclude='moonraker.asvc' \
  --delete \
  "$STAGING/" "$REPO_ROOT/config/"

echo
echo "==> Sync applied. Review with \`git status\` + \`git diff\`."
echo "==> Commit with a chore(sync): prefix, e.g.:"
echo "    git commit -am 'chore(sync): pull post-calibration SAVE_CONFIG from Pi'"
