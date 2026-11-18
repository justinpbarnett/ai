# pi portable config

This directory stores the portable part of `~/.pi/agent` for this repo.

## What is tracked

Tracked items are copied from or linked into the target pi config directory:

- `settings.json`
- `keybindings.json`
- `extensions/self-compact/`
- the repository's global `skills/` directory

## Self-compaction

The `self_compact` tool lets the coding agent request a background checkpoint with a short handoff.
When context reaches the notice threshold, Pi can also prepare one checkpoint in the background using the active chat model, without waiting for JEV or for the summary to finish.
At a later turn boundary, Pi applies a ready checkpoint after a tool request, a confident JEV task switch, or when context reaches the warning threshold.
The checkpoint replaces only the older history before the original cut, not the history through the point of application.
All messages and tool results added while it ran are kept verbatim, as is the handoff supplied to the tool.
If the result finishes while Pi is idle, it waits for the next completed turn; it does not start a turn on its own.
Pi discards an unsafe or stale result, including after a model or branch switch, a context edit, or native compaction.
Native `/compact`, threshold compaction, and overflow recovery still work; if Pi reaches its cutoff before the background job is ready, it does not wait for it.

`/self-compact status` shows context usage, thresholds, background progress, the last checkpoint source, and JEV mode.
`/self-compact now [focus]` uses Pi's normal manual compaction and only runs while idle.
The model tool also works in print and RPC sessions when active.
An unfinished checkpoint is discarded when Pi exits; one-shot print mode does not wait for it.

By default, the model gets a notice at 60% and a warning at 80% **of the native cutoff** (`context window - reserveTokens`).
Override these with `--self-compact-notice-at` and `--self-compact-warn-at`, using whole tokens (`6000`), `k` shorthand (`6k`), or a percentage **of the context window** (`60%`).
Require `0 < notice < warning < native cutoff`; an invalid pair disables extension automation without disabling the tool or changing Pi's native settings.
Turning off Pi's automatic compaction also disables proactive background work and notices; the explicit tool still works.

**JEV is on by default in trusted TUI sessions** when Pi has OpenRouter credentials and the `typesafe/jev-1.14` classifier is available.
Under context pressure, Pi can send up to 512 characters each from two consecutive new user prompts to OpenRouter and its upstream model provider.
Use Pi's OpenRouter login or `OPENROUTER_API_KEY`; no direct TypeSafe credentials are needed.
JEV checks for an independent task switch, not what to put in the summary.
Pi skips queued prompts, commands, attachments and obvious credentials, but that filter is not a guarantee of redaction.
For work that cannot send prompt excerpts off-machine, start Pi with `--no-self-compact-jev`, or run `/self-compact jev off` before submitting prompts.
The command clears stored excerpts and turns JEV off for the loaded extension; the launch flag keeps it off by default across reloads.
With missing credentials or an unavailable model, Pi shows `JEV off (unavailable)` without sending a request.
If a request fails or times out, JEV also switches off and stops retrying; `/self-compact jev on` lets you retry.
The agent tool and native compaction still work with JEV off.

The portable installer includes the extension; run `/reload` in a live TUI or restart Pi to discover it.
To try it without installing, run `pi -ne -e "$HOME/dev/ai/pi-config/extensions/self-compact/index.ts"`.
The uninstaller removes the managed directory symlink, not copies made with `--mode copy`.

## Improve a codebase

Use `/skill:improve-codebase` in Pi or `/improve-codebase` in Claude Code, with a path or concern if you want a narrower scope.
Add `audit only` to inspect and save findings without changing application files.
Install the isolated parser bundle once with `uv sync --project ~/dev/ai/skills/improve-codebase --locked --extra parsers --group dev`.
Plain Python can run core inventory and reporting; missing syntax coverage for priority languages makes a run partial.

The skill scans first, reviews the results and module relationships, then verifies improvements against real behavior.
It keeps findings and completed investigations in the target worktree's ignored `.improve-codebase/` directory, so a later run can focus on new, changed, or pending work.
The debt score counts confirmed unresolved work, including accepted risk; zero alone does not prove completion.
See the [CLI reference](../skills/improve-codebase/references/cli.md) for scan, status, refresh, and evidence commands.

To continue across turns, ask the skill to prepare a goal and submit its self-contained objective through `/goal` separately.
Confirm the scope and enable the auditor; the skill does not start or resume goals on its own.
The [goal recipe](../skills/improve-codebase/references/goal-loop.md) covers the verification contract, pause/resume, and evidence the auditor can inspect independently.
This replaces `/skill:refactor` in Pi and `/refactor` in Claude Code; the Fowler checklist is bundled with the new skill.
Run `/reload` in Pi or start a new Claude Code session to refresh command discovery.

## What stays local

These are intentionally excluded and should be created on each machine as needed:

- `auth.json`
- `sessions/`
- `git/`
- `bin/`
- `pi-debug.log`
- `node_modules/`

## Install on another machine

Clone this repo, then run:

```bash
cd ~/dev/ai/pi-config
./install.sh
```

By default this links the portable config into `~/.pi/agent`.

To target a different location:

```bash
PI_CODING_AGENT_DIR=/path/to/pi/agent ./install.sh
```

To copy files instead of linking them:

```bash
./install.sh --mode copy
```

The installer creates missing directories and preserves local state that is not managed here.

## Link this repo on the current machine

```bash
cd ~/dev/ai/pi-config
./link-local.sh
```

This is a small wrapper around `install.sh --mode symlink`.
In symlink mode, `~/dev/ai/pi-config` is the source of truth.
Pi's global settings, keybindings, and skills point back to this repo, while local-only files remain under `~/.pi/agent`.

If an existing managed file or directory needs to be replaced, it is moved into a timestamped backup directory under:

```bash
~/.local/state/pi-config-backups/
```

## Unlink this repo from global pi config

```bash
cd ~/dev/ai/pi-config
./uninstall.sh
```

The uninstall script removes only symlinks in `~/.pi/agent` that point into this repo.
It does not remove local auth, sessions, or package state.

Preview first with:

```bash
./uninstall.sh --dry-run
```

## Secrets and auth

After bootstrapping on a new machine, sign in to Pi so it creates `auth.json` locally.

Do not commit local secrets or session data from `~/.pi/agent`.
