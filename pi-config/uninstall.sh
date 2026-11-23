#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=portable.sh
source "$SCRIPT_DIR/portable.sh"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: uninstall.sh [--dry-run]

Environment:
  PI_CODING_AGENT_DIR   Target pi agent dir. Default: ~/.pi/agent

Removes only symlinks in the target pi agent dir that point into this repo's
pi-config directory. Local secrets and state are never removed.
EOF
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

for_each_portable_path remove_link
