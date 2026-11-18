# pi portable config

This directory stores the portable part of `~/.pi/agent` for this repo.

## What is tracked

Tracked items are copied from or linked into the target pi config directory:

- `settings.json`
- `keybindings.json`
- the repository's global `skills/` directory

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
