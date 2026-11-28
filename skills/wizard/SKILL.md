---
name: wizard
description: Generate an interactive bash wizard for multi-step human-only setup (credentials, CI secrets, dashboards, migrations). For one secret, give a single ! pipe instead.
---

# Wizard

A **wizard** is a bash script walking a human step-by-step through manual tasks: opening URLs, showing what to click/copy, capturing values into `.env` or GitHub secrets, and confirming each stage.

[template.sh](template.sh) already handles UX, URL opening (including WSL), hidden secret entry, mode-600 `.env` upserts, and `gh secret`/`gh variable` writes. **Only scope the procedure and author stages below the `STAGES` marker**; never edit the library above it. Wizards are ephemeral (scratch or `scripts/`, deleted after use) unless meant as repeatable repo setup.

## Process

1. **Scope.** Inspect `.env*`, `README*`, `docker-compose*`, config, and `.github/workflows/*` (`secrets.*` / `vars.*`) or migration start/end states. Present the ordered stages and each captured value (source, destination, secret vs. public) and confirm with the user.
2. **Map each journey.** Write exact click/command paths (e.g., `Dashboard → Developers → API keys → Reveal`). Ask or check docs rather than guessing unfamiliar UIs.
3. **Author.** Copy `template.sh` to the target path, replace the example stage with one focused `stage` per step in dependency order, set `TOTAL_STAGES`, and use `stage`, `say`/`step`, `open_url`, `ask`/`ask_secret`, `write_env`, `set_secret`/`set_var`, `pause`/`confirm`. Open each URL before asking for its value, use `ask_secret` for secrets, `confirm` before irreversible steps, and note when a shared deploy account needs access to mode-600 `.env`.
4. **Verify and hand off.** Run `chmod +x` and `bash -n` (plus `shellcheck` if installed). Trace statically that every captured value lands where step 1 planned and `set_secret` names match CI `secrets.*` (do not run interactively). Tell the user to run it in their own terminal (never as a `!` command, which gets no stdin). For a single secret, skip the wizard and give one `!` clipboard/file pipe such as `pbpaste | gcloud secrets versions add NAME --data-file=-`.
