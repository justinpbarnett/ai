#!/bin/bash

REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck disable=SC2034
TARGET_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"

for_each_portable_path() {
  local action="$1"
  local rel

  for rel in settings.json keybindings.json extensions/inline-commands.ts extensions/prompt-stash.ts; do
    "$action" "$rel" file
  done

  for rel in skills extensions/jev-router extensions/progressive-web extensions/shared \
    extensions/tool-explainer extensions/working-summary; do
    "$action" "$rel" dir
  done
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
