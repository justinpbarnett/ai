#!/usr/bin/env bash
# teammate-idle-lint.sh -- TeammateIdle hook
# Runs project-appropriate linter on files changed by a teammate when it goes idle.
# Based on post-edit-lint.sh patterns.

set -euo pipefail

INPUT=$(cat)

# Try multiple field paths since TeammateIdle input format may vary
CWD=$(echo "$INPUT" | jq -r '.cwd // .tool_input.cwd // empty' 2>/dev/null || true)

if [ -z "$CWD" ]; then
  exit 0
fi

# Validate CWD is a real absolute directory
if [[ "$CWD" != /* ]] || [ ! -d "$CWD" ]; then
  exit 0
fi

# Walk up to find project root from CWD
PROJECT_ROOT=""
DIR="$CWD"
while [ "$DIR" != "/" ]; do
  if [ -f "$DIR/go.mod" ] || [ -f "$DIR/package.json" ] || [ -f "$DIR/pyproject.toml" ]; then
    PROJECT_ROOT="$DIR"
    break
  fi
  DIR=$(dirname "$DIR")
done

if [ -z "$PROJECT_ROOT" ]; then
  exit 0
fi

# Get list of changed files (staged + unstaged)
cd "$PROJECT_ROOT" || exit 0
CHANGED_FILES=$(git diff --name-only HEAD 2>/dev/null || true)
if [ -z "$CHANGED_FILES" ]; then
  CHANGED_FILES=$(git diff --name-only 2>/dev/null || true)
fi

if [ -z "$CHANGED_FILES" ]; then
  exit 0
fi

ISSUES=""

# Go project: run go vet on changed packages
if [ -f "$PROJECT_ROOT/go.mod" ]; then
  GO_PKGS=$(echo "$CHANGED_FILES" | grep '\.go$' | xargs -I{} dirname {} 2>/dev/null | sort -u || true)
  if [ -n "$GO_PKGS" ]; then
    while IFS= read -r PKG; do
      [[ "$PKG" == *".."* ]] && continue
      VET_OUTPUT=$(go vet "./$PKG" 2>&1) || true
      if [ -n "$VET_OUTPUT" ]; then
        ISSUES="${ISSUES}go vet ($PKG):\n${VET_OUTPUT}\n\n"
      fi
    done <<< "$GO_PKGS"
  fi
fi

# Python project: run ruff on changed .py files
if [ -f "$PROJECT_ROOT/pyproject.toml" ] || [ -f "$PROJECT_ROOT/setup.py" ]; then
  PY_FILES=$(echo "$CHANGED_FILES" | grep '\.py$' || true)
  if [ -n "$PY_FILES" ] && command -v ruff &>/dev/null; then
    while IFS= read -r PY_FILE; do
      if [ -f "$PY_FILE" ]; then
        LINT_OUTPUT=$(ruff check --no-fix "$PY_FILE" 2>&1) || true
        if [ -n "$LINT_OUTPUT" ] && ! echo "$LINT_OUTPUT" | grep -q "All checks passed"; then
          ISSUES="${ISSUES}ruff ($PY_FILE):\n${LINT_OUTPUT}\n\n"
        fi
      fi
    done <<< "$PY_FILES"
  fi
fi

# Node project: run eslint on changed JS/TS files
if [ -f "$PROJECT_ROOT/package.json" ] && [ -f "$PROJECT_ROOT/node_modules/.bin/eslint" ]; then
  JS_FILES=$(echo "$CHANGED_FILES" | grep -E '\.(ts|tsx|js|jsx)$' || true)
  if [ -n "$JS_FILES" ]; then
    while IFS= read -r JS_FILE; do
      if [ -f "$JS_FILE" ]; then
        LINT_OUTPUT=$(npx eslint --no-error-on-unmatched-pattern "$JS_FILE" 2>&1) || true
        ERROR_LINES=$(echo "$LINT_OUTPUT" | grep -E 'error' | head -10 || true)
        if [ -n "$ERROR_LINES" ]; then
          ISSUES="${ISSUES}eslint ($JS_FILE):\n${ERROR_LINES}\n\n"
        fi
      fi
    done <<< "$JS_FILES"
  fi
fi

# Report issues back to the model if any found
if [ -n "$ISSUES" ]; then
  TRIMMED=$(printf '%b' "$ISSUES" | head -30)
  jq -n --arg output "$TRIMMED" '{
    hookSpecificOutput: {
      hookEventName: "TeammateIdle",
      additionalContext: ("Lint issues found in teammate changes:\n" + $output)
    }
  }'
fi

exit 0
