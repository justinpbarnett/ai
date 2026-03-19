#!/usr/bin/env bash
# Sends a desktop notification when Claude needs user input.
# Used by the Stop and Notification hooks.

INPUT="$(cat)"

eval "$(echo "$INPUT" | python3 -c "
import sys, json, os
data = json.load(sys.stdin)

# Build a descriptive title from stop reason and working directory
stop_reason = data.get('stop_hook_reason', '')
cwd = data.get('cwd', '') or os.environ.get('CLAUDE_PROJECT_DIR', '')
project = os.path.basename(cwd) if cwd else ''

parts = ['Claude Code']
if project:
    parts.append(project)
if stop_reason and stop_reason != 'stop_invoked':
    labels = {
        'end_turn': 'done',
        'max_tokens': 'hit token limit',
        'interrupt': 'interrupted',
    }
    label = labels.get(stop_reason, stop_reason.replace('_', ' '))
    parts.append(label)

title = ' - '.join(parts)

msg = data.get('last_assistant_message', '') or data.get('message', '') or 'Finished'
msg = ' '.join(msg.split())[:120]

# Shell-escape for eval
title = title.replace(\"'\", \"'\\\"'\\\"'\")
msg = msg.replace(\"'\", \"'\\\"'\\\"'\")
print(f\"TITLE='{title}'\")
print(f\"MSG='{msg}'\")
" 2>/dev/null)"

TITLE="${TITLE:-Claude Code}"
MSG="${MSG:-Finished}"

case "$(uname)" in
  Darwin)
    osascript -e "display notification \"$MSG\" with title \"$TITLE\" sound name \"Ping\""
    ;;
  Linux)
    if command -v notify-send &>/dev/null; then
      notify-send "$TITLE" "$MSG"
    fi
    ;;
esac
