#!/usr/bin/env bash
#
# A wizard walks a human through a manual procedure, step by step.
# Source template for the /wizard skill.
# In a copy of this template, leave the library intact and write your steps
# below the "STAGES" marker.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""
if [[ -t 1 ]] && colors=$(tput colors 2>/dev/null) && [[ "$colors" =~ ^[0-9]+$ && "$colors" -ge 8 ]]; then
  BOLD=$(tput bold 2>/dev/null || true)
  DIM=$(tput dim 2>/dev/null || true)
  RESET=$(tput sgr0 2>/dev/null || true)
  BLUE=$(tput setaf 4 2>/dev/null || true)
  GREEN=$(tput setaf 2 2>/dev/null || true)
  YELLOW=$(tput setaf 3 2>/dev/null || true)
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
WRITTEN_SECRET=() # secret NAMEs set this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear wipes the screen only when the output terminal supports it.
_clear() {
  if [[ -t 1 ]]; then
    tput clear 2>/dev/null || true
  fi
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1" opener
  for opener in wslview explorer.exe xdg-open open; do
    command -v "$opener" >/dev/null 2>&1 || continue
    printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
    if "$opener" "$url" >/dev/null 2>&1; then
      return 0
    fi
    break
  done
  warn "couldn't open a browser; visit it manually: $url"
}

_input_ended() {
  printf '\n' >&2
  warn "Input ended before the prompt was answered." >&2
  return 1
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || _input_ended
}

# confirm "question" is a y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  if ! read -r reply; then
    _input_ended
    return 1
  fi
  [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

_ask_value() {
  # Bash resolves printf -v through local scopes. Only declare a scratch name
  # different from the destination. Arguments: key, prompt, read flag, saved value, scratch name.
  set -- "$@" "$(_existing "$1" || true)" _wizard_input
  if [[ "$1" == "$5" ]]; then
    set -- "$1" "$2" "$3" "$4" _wizard_other_input
  fi
  local "$5"
  if [[ -n "$4" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$2" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$2" "$RESET"
  fi
  if ! IFS= read -r ${3:+"$3"} "$5"; then
    _input_ended
    return 1
  fi
  if [[ "$3" == -s ]]; then
    printf '\n'
  fi
  printf -v "$1" '%s' "${!5:-$4}"
}

# ask KEY "Prompt" reads a value into $KEY. Enter keeps an existing .env value.
ask() {
  _ask_value "$1" "$2" ""
}

# ask_secret KEY "Prompt" is like ask, but input is hidden.
ask_secret() {
  _ask_value "$1" "$2" -s
}

_env_target() {
  if [[ -L "$1" || ( -e "$1" && ! -f "$1" ) ]]; then
    printf 'Cannot save to %s: expected a regular file or a new path.\n' "$1" >&2
    return 1
  fi
}

_replace_env() (
  local file="$1" key="$2" value="$3" tmp
  case "$file" in /*) ;; *) file="./$file" ;; esac
  _env_target "$file" || return 1
  tmp=$(mktemp "${file%/*}/.wizard-env.XXXXXXXX") || return 1
  trap 'rm -f -- "$tmp"' EXIT
  {
    if [[ -f "$file" ]]; then
      grep -vE "^${key}=" "$file" || [[ $? -eq 1 ]] || return 1
    fi
    printf '%s=%s\n' "$key" "$value"
  } > "$tmp" || return 1
  _env_target "$file" && mv -f -- "$tmp" "$file"
)

# write_env KEY VALUE upserts KEY=VALUE into ENV_FILE (creates it; replaces
# any existing line). Idempotent.
write_env() {
  local key="$1" value="$2"
  if [[ ! "$key" =~ ^[a-zA-Z_][a-zA-Z_0-9]*$ ]]; then
    printf 'Cannot save to %s: invalid environment variable name.\n' "$ENV_FILE" >&2
    return 1
  fi
  _replace_env "$ENV_FILE" "$key" "$value" || return 1
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_secret NAME VALUE sets a GitHub Actions repo secret via gh. Falls back
# to a warning (and records it) if gh is unavailable or unauthenticated.
set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name: gh not ready; set it later"
}

# set_var NAME VALUE sets a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES: author this section. One stage() per step the human takes.
# Replace the example below. Set TOTAL_STAGES to match the stages you write.
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=1

banner "Stripe setup"

# ── Example stage: replace with your real steps ───────────────────────────
stage "Stripe: API keys"
say "We'll grab your Stripe test keys and store them for local dev + CI."
open_url "https://dashboard.stripe.com/test/apikeys"
step "On the API keys page, copy the Publishable key (starts pk_test_)."
ask STRIPE_PUBLISHABLE_KEY "Paste the publishable key:"
step "Click 'Reveal test key' on the Secret key row, then copy it."
ask_secret STRIPE_SECRET_KEY "Paste the secret key:"
write_env STRIPE_PUBLISHABLE_KEY "$STRIPE_PUBLISHABLE_KEY"
write_env STRIPE_SECRET_KEY "$STRIPE_SECRET_KEY"
set_secret STRIPE_SECRET_KEY "$STRIPE_SECRET_KEY"   # CI needs this one
# ──────────────────────────────────────────────────────────────────────────

finish
