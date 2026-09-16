#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
DRY_RUN=0

TOP_LEVEL_FILES=(
  settings.json
  keybindings.json
)

TOP_LEVEL_DIRS=(
  skills
)

usage() {
  cat <<'EOF'
Usage: uninstall.sh [--dry-run]

Environment:
  PI_CODING_AGENT_DIR   Target pi agent dir. Default: ~/.pi/agent

Removes only symlinks in the target pi agent dir that point into this repo's
pi-config directory. Local secrets and state are never removed.
EOF
}

log() {
  printf '%s\n' "$*"
}

is_managed_link() {
  local target="$1"

  [ -L "$target" ] || return 1

  local dest
  dest="$(readlink "$target")"
  case "$dest" in
    "$SCRIPT_DIR"|"$SCRIPT_DIR"/*|"$REPO_DIR/skills"|"$REPO_DIR/skills"/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

remove_link() {
  local rel="$1"
  local target="$TARGET_DIR/$rel"

  if ! is_managed_link "$target"; then
    return
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    log "WOULD REMOVE $rel -> $(readlink "$target")"
    return
  fi

  rm "$target"
  log "REMOVE $rel"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log "Repo:   $SCRIPT_DIR"
log "Target: $TARGET_DIR"

for rel in "${TOP_LEVEL_FILES[@]}"; do
  remove_link "$rel"
done

for rel in "${TOP_LEVEL_DIRS[@]}"; do
  remove_link "$rel"
done
