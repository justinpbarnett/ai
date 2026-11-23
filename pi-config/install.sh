#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=portable.sh
source "$SCRIPT_DIR/portable.sh"
MODE="symlink"
BACKUP_ROOT="${PI_CONFIG_BACKUP_DIR:-$HOME/.local/state/pi-config-backups}"
BACKUP_DIR=""

usage() {
  cat <<'EOF'
Usage: install.sh [--mode symlink|copy]

Environment:
  PI_CODING_AGENT_DIR   Target pi agent dir. Default: ~/.pi/agent
  PI_CONFIG_BACKUP_DIR  Backup root for replaced links and incompatible targets.
                        Default: ~/.local/state/pi-config-backups

Notes:
  Copy mode requires rsync and excludes machine-local auth, sessions, git,
  bin, .env files, local skills, and dependency environments and caches.
EOF
}

ensure_backup_dir() {
  if [ -z "$BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_ROOT"
    BACKUP_DIR="$(mktemp -d "$BACKUP_ROOT/$(date +%Y%m%d%H%M%S).XXXXXX")"
  fi
}

backup_target() {
  local target="$1"
  local rel="$2"

  if [ ! -e "$target" ] && [ ! -L "$target" ]; then
    return
  fi

  ensure_backup_dir
  mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
  mv "$target" "$BACKUP_DIR/$rel"
  log "BACKUP $rel -> $BACKUP_DIR/$rel"
}

matches_type() {
  case "$2" in
    file) [ -f "$1" ] ;;
    dir) [ -d "$1" ] ;;
  esac
}

install_link() {
  local rel="$1" source="$2" target="$3"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
    log "KEEP $rel"
    return
  fi

  backup_target "$target" "$rel"
  ln -s "$source" "$target"
  log "LINK $rel -> $source"
}

copy_entry() {
  local rel="$1" source="$2" target="$3" kind="$4"
  if [ -L "$target" ] || { [ -e "$target" ] && ! matches_type "$target" "$kind"; }; then
    backup_target "$target" "$rel"
  fi

  if [ "$kind" = file ]; then
    cp -a "$source" "$target"
    log "COPY $rel"
  else
    local filters=(
      --exclude=auth.json --exclude=sessions/ --exclude=git/ --exclude=.git/
      --exclude=bin/ --exclude=pi-debug.log --exclude=pi-goal-x-settings.json
      --exclude=.env --exclude='.env.*' --exclude=.npm/ --exclude=node_modules/
      --exclude=.venv/ --exclude=__pycache__/ --exclude=.pytest_cache/ --exclude=.ruff_cache/
    )
    if [ "$rel" = skills ]; then
      # Keep these roots aligned with the machine-local skill entries in .gitignore.
      filters+=(--exclude=/synced --exclude=/.trash --exclude=/.sync-manifest.json
        --exclude=/omarchy --exclude=/hey --exclude='/twg*')
    fi
    mkdir -p "$target"
    rsync -a --safe-links "${filters[@]}" "$source/" "$target/"
    log "SYNC $rel"
  fi
}

install_entry() {
  local rel="$1" kind="$2"
  local source="$SCRIPT_DIR/$rel" target="$TARGET_DIR/$rel"
  if [ "$rel" = skills ] && ! matches_type "$source" "$kind"; then
    source="$REPO_DIR/skills"
  fi

  if ! matches_type "$source" "$kind"; then
    if is_managed_link "$target"; then
      rm "$target"
      log "REMOVE $rel"
    fi
    return
  fi

  mkdir -p "$(dirname "$target")"
  if [ "$MODE" = symlink ]; then
    install_link "$rel" "$source" "$target"
  else
    copy_entry "$rel" "$source" "$target" "$kind"
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)
      if [[ $# -lt 2 || "$2" == -* ]]; then
        echo "Missing value for --mode (expected symlink or copy)." >&2
        usage >&2
        exit 1
      fi
      MODE="$2"
      shift 2
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

case "$MODE" in
  symlink)
    ;;
  copy)
    if ! command -v rsync >/dev/null 2>&1; then
      echo "Copy mode requires rsync." >&2
      exit 1
    fi
    ;;
  *)
    echo "Invalid mode: $MODE" >&2
    exit 1
    ;;
esac

mkdir -p "$TARGET_DIR"

log "Repo:   $SCRIPT_DIR"
log "Target: $TARGET_DIR"
log "Mode:   $MODE"

for_each_portable_path install_entry

if [ -n "$BACKUP_DIR" ]; then
  log "Backups: $BACKUP_DIR"
else
  log "Backups: none"
fi
