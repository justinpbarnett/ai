# pi portable config

This directory stores the portable part of `~/.pi/agent` for this repo.

## What is tracked

Tracked items are copied from or linked into the target pi config directory:

- `settings.json`
- `keybindings.json`
- `extensions/self-compact/`
- `extensions/tool-explainer/`
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

Pi's context footer shows proactive compaction pressure and JEV state in place of `(auto)`, for example `(proactive: normal | JEV on)`.
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

## Tool explanations

By default, Pi replaces every two new tool calls with one inline line, such as `Read README.md and CONTEXT.md · ctrl+o to expand`.
A partial batch is shown when the agent finishes.
Use Pi's normal `Ctrl+O` to switch between explanations and original tool output, or `/explain-tools recent` to review earlier batches and see which writer was used.
The extension leaves existing transcript history and Pi's native inline image rendering alone.

Automatic explanations run only in trusted TUI sessions and do not block the agent's tool loop.
Pi formats file operations, recognized commands, and failures without a model.
File summaries show short paths, including files outside the current workspace, except for protected paths.
When a shell call has no clearer summary, Pi shows its recognizable command names and selected details, such as `Ran wc -l README.md | head`, without showing the full arguments or output.
For ambiguous shell commands, the selected writer can refine the line in the background.
The default Ollama writer receives short command text on loopback only, with obvious secrets and protected paths excluded.
The hosted writer receives fixed operation hints only: no raw commands, filenames, user prompts, or tool output are sent automatically.
If the writer is unavailable or times out, the initial summary stays in place.
`--offline` disables hosted writing, not local Ollama writing.

Run `/explain-tools` or `/explain-tools 1` for a more detailed explanation of the latest calls on the active branch.
Pi shows the tool text excerpts first; press `S` to send or Escape to cancel.
After approval JEV classifies the results and `google/gemini-2.5-flash-lite` writes the explanation, both through OpenRouter.
Obvious credentials and non-text results stay local, but the filter cannot guarantee redaction.
Do not approve excerpts containing sensitive or restricted material.
Manual explanations and the optional hosted writer use Pi's OpenRouter login or `OPENROUTER_API_KEY` and may incur OpenRouter charges.

Use `/explain-tools status` to see the effective settings, `/explain-tools off` to pause until reload or session replacement, or `/explain-tools on` to resume.
For persistent defaults, keep `tool-explainer.json` in the global Pi agent directory (`~/.pi/agent` unless `PI_CODING_AGENT_DIR` is set):

```json
{
  "auto": true,
  "count": 2,
  "writer": "ollama",
  "ollamaModel": "qwen3.5:2b",
  "openrouterModel": "google/gemini-2.5-flash-lite"
}
```

Set `writer` to `ollama`, `openrouter`, or `off`.
`off` keeps automatic summaries on but makes no automatic model calls.
For `ollama`, start Ollama on `127.0.0.1:11434` and run `ollama pull qwen3.5:2b`, or set `ollamaModel` to another installed local model tag.
For `openrouter`, `openrouterModel` must be a chat model available in Pi's OpenRouter catalog.
Neither model ID needs to be specified if you want the defaults above.
The count can be 1 to 10; launch with `--explain-tools-count 4` or `--explain-tools-no-auto` for one-off overrides.
The portable installer links the extension and leaves the settings file local.
Restart Pi or run `/reload` after installing or changing that file.
To try it without installation, use `pi -ne -e "$HOME/dev/ai/pi-config/extensions/tool-explainer/index.ts"`.

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
