#!/usr/bin/env bash
set -euo pipefail

tool="${1:-}"
case "$tool" in
  query|build|catalog|browser) shift ;;
  *) echo "usage: rock.sh <query|build|catalog|browser> [args...]" >&2; exit 64 ;;
esac
if ! command -v uv >/dev/null; then
  echo "Install uv to run the Rock skill (on macOS: brew install uv)." >&2
  exit 1
fi

umask 077
runtime="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROCK_HOME="${ROCK_HOME:-$HOME/.local/share/passion-rock}"
export UV_PROJECT_ENVIRONMENT="$ROCK_HOME/.venv"
mkdir -p "$ROCK_HOME"
run=(uv run --frozen --project "$runtime")
if [[ "${ROCK_WITH_BROWSER:-}" == 1 || -f "$ROCK_HOME/.browser" ]]; then
  run+=(--group browser)
  if [[ "${ROCK_WITH_BROWSER:-}" == 1 || "$tool" == browser ]]; then
    "${run[@]}" playwright install chromium
    touch "$ROCK_HOME/.browser"
  fi
fi

export ROCK_ALLOW_WRITES=1
exec "${run[@]}" python -B "$runtime/scripts/rock_$tool.py" "$@"
