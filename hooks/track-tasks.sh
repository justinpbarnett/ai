#!/usr/bin/env bash
# track-tasks.sh -- TaskCompleted hook
# Tracks completed agent team tasks in project memory.
# Appends a one-line entry to:
#   ~/.claude/projects/{project-path}/memory/recent-tasks.md
# Keeps only the last 30 entries.

set -uo pipefail

INPUT=$(cat)

# Extract task info from hook input (defensive -- try multiple paths)
TASK_ID=$(echo "$INPUT" | jq -r '.task_id // .tool_input.task_id // empty' 2>/dev/null || true)
TASK_TITLE=$(echo "$INPUT" | jq -r '.title // .task_title // .tool_input.title // empty' 2>/dev/null || true)
TASK_STATUS=$(echo "$INPUT" | jq -r '.status // .task_status // "completed"' 2>/dev/null || true)

# Need at least a title to log
if [ -z "$TASK_TITLE" ] && [ -z "$TASK_ID" ]; then
  exit 0
fi

# Build a display label, sanitize to printable chars and cap length
LABEL=""
if [ -n "$TASK_ID" ] && [ -n "$TASK_TITLE" ]; then
  LABEL="${TASK_ID}: ${TASK_TITLE}"
elif [ -n "$TASK_TITLE" ]; then
  LABEL="$TASK_TITLE"
else
  LABEL="$TASK_ID"
fi
LABEL=$(printf '%s' "$LABEL" | tr -d '\000-\037\177' | head -c 200)

# Get the working directory
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
if [ -z "$CWD" ]; then
  exit 0
fi

# Validate CWD is a real absolute directory
if [[ "$CWD" != /* ]] || [ ! -d "$CWD" ]; then
  exit 0
fi

# Build the project memory path
PROJECT_PATH=$(echo "$CWD" | tr '/' '-' | sed 's/^-//')
MEMORY_DIR="$HOME/.claude/projects/-${PROJECT_PATH}/memory"
MEMORY_FILE="$MEMORY_DIR/recent-tasks.md"

# Ensure the memory directory exists
mkdir -p "$MEMORY_DIR"

# Append the new entry
DATE=$(date '+%Y-%m-%d')
echo "- ${DATE}: [${TASK_STATUS}] ${LABEL}" >> "$MEMORY_FILE"

# Trim to last 30 entries (temp file in same dir to avoid TOCTOU)
if [ -f "$MEMORY_FILE" ]; then
  LINES=$(wc -l < "$MEMORY_FILE")
  if [ "$LINES" -gt 30 ]; then
    TMPFILE=$(mktemp "${MEMORY_DIR}/.tasks.XXXXXX")
    tail -n 30 "$MEMORY_FILE" > "$TMPFILE"
    mv "$TMPFILE" "$MEMORY_FILE"
  fi
fi

exit 0
