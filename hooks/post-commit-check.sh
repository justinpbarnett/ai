#!/usr/bin/env bash
# post-commit-check.sh -- PostToolUse hook for Bash
# After a git commit, runs the project's test/lint/check suite.
# Detects the project's tooling and runs the appropriate command:
# - justfile with "check" recipe: just check
# - Makefile with "check" target: make check
# - Go project: go test ./... && go vet ./...
# - Node project: npm test (if test script exists)
# - Python project: uv run pytest or pytest (if tests/ exists)

set -uo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Only act on git commit commands
if ! echo "$COMMAND" | grep -qE 'git\s+commit'; then
  exit 0
fi

# Get the working directory
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
if [ -z "$CWD" ]; then
  exit 0
fi

# Walk up to find project root
PROJECT_ROOT=""
DIR="$CWD"
while [ "$DIR" != "/" ]; do
  if [ -f "$DIR/justfile" ] || [ -f "$DIR/Makefile" ] || [ -f "$DIR/go.mod" ] || [ -f "$DIR/package.json" ] || [ -f "$DIR/pyproject.toml" ]; then
    PROJECT_ROOT="$DIR"
    break
  fi
  DIR=$(dirname "$DIR")
done

if [ -z "$PROJECT_ROOT" ]; then
  exit 0
fi

cd "$PROJECT_ROOT"

CHECK_CMD=""
CHECK_LABEL=""

# Priority 1: justfile with "check" recipe
if [ -f "justfile" ] && grep -qE '^check\s*:' justfile; then
  CHECK_CMD="just check"
  CHECK_LABEL="just check"

# Priority 2: Makefile with "check" target
elif [ -f "Makefile" ] && grep -qE '^check\s*:' Makefile; then
  CHECK_CMD="make check"
  CHECK_LABEL="make check"

# Priority 3: Go project
elif [ -f "go.mod" ]; then
  CHECK_CMD="go test ./... 2>&1 && go vet ./... 2>&1"
  CHECK_LABEL="go test + go vet"

# Priority 4: Node project with test script
elif [ -f "package.json" ] && jq -e '.scripts.test' package.json >/dev/null 2>&1; then
  CHECK_CMD="npm test 2>&1"
  CHECK_LABEL="npm test"

# Priority 5: Python project with tests
elif [ -f "pyproject.toml" ]; then
  if [ -d "tests" ] || [ -d "test" ]; then
    if [ -f "uv.lock" ] || grep -q '\[tool\.uv\]' pyproject.toml 2>/dev/null; then
      CHECK_CMD="uv run pytest 2>&1"
      CHECK_LABEL="uv run pytest"
    elif command -v pytest &>/dev/null; then
      CHECK_CMD="pytest 2>&1"
      CHECK_LABEL="pytest"
    fi
  fi
fi

if [ -z "$CHECK_CMD" ]; then
  exit 0
fi

# Run the check suite
OUTPUT=$(eval "$CHECK_CMD" 2>&1) || {
  EXIT_CODE=$?
  # Trim output to avoid overwhelming the context
  TRIMMED=$(echo "$OUTPUT" | tail -40)
  jq -n --arg output "$TRIMMED" --arg label "$CHECK_LABEL" --arg root "$PROJECT_ROOT" '{
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: ($label + " failed in " + $root + " (exit " + ($EXIT_CODE | tostring) + "):\n" + $output)
    }
  }'
  exit 0
}

# Success -- no output needed
exit 0
