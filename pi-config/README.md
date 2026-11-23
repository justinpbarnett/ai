# pi portable config

This directory stores the portable part of `~/.pi/agent` for this repo.

## What is tracked

Tracked items are copied from or linked into the target pi config directory:

- `settings.json`
- `keybindings.json`
- `extensions/inline-commands.ts`
- `extensions/prompt-stash.ts`
- `extensions/jev-router/`
- `extensions/progressive-web/` (install its dependencies as its README describes; copy mode skips `node_modules/`)
- `extensions/self-compact/`
- `extensions/shared/`
- `extensions/tool-explainer/`
- `extensions/working-summary/`
- the repository's global `skills/` directory

## Prompt stash

Press `Ctrl+S` to stash the current draft and clear the editor.
Press `Ctrl+S` again to restore it, appending it below any new draft.
Submitting an interactive prompt also restores the stash to the editor for your next message.
The portable installer manages one global copy, so projects do not need their own `prompt-stash.ts`.
Pi's model and thinking selectors use `Ctrl+Alt+S` to save defaults, and the session picker uses it to change sorting.

## Inline skills and slash commands

The global `inline-commands` extension lets you invoke a command anywhere in a prompt and opens Pi's normal command-completion menu at the cursor.
Type `/`, narrow the results, then use Tab or Enter to accept a completion.
Command argument completions, file attachments, and path completions still use Pi's existing providers.

```text
Investigate the missing search results /skill:plan-bugfix
Please /skill:implement /path/to/plan.md
Review this change /review concurrency
Build the agreed feature /goal
Please /model openai/gpt-6.1-sol
Open /settings
```

`/review` in this example requires a prompt template with that name.
The first recognized, unquoted command is promoted to the beginning before Pi handles the submission.
For skills, prompt templates, and extension commands, the text before and after the command becomes its arguments in the original order.
This also means positional template arguments include any preceding prose.
Commands already at the beginning retain Pi's native behavior, and multiple commands are not executed as a chain.
Built-in controls such as `/model` and `/settings` use only the arguments after the command; preceding prose is not sent to the agent.

A slash must start a whitespace-delimited token, so URLs and multi-segment paths are not treated as commands.
Use backticks, quotes, or an escaped slash such as `\/settings` to mention a command literally.
Unknown command names and shell submissions beginning with `!` or `!!` are left alone.
In print and RPC modes, inline skills and prompt templates are supported, but interactive controls and extension-command promotion are TUI-only.
Extension-injected messages are not rewritten.

The extension uses Pi's native command catalog, expansion, and execution rather than duplicating skill loading or template substitution.
Pi 1.5.2 exposes provider composition but hardcodes the editor's natural slash trigger to the beginning of a message.
A guarded editor adapter requests the existing autocomplete menu for inline commands; if a future editor removes that hook, Pi warns and Tab completion remains available.
No installed Pi package files are patched.
Run `/reload` in an idle Pi session, or restart Pi, after installation or updates to this extension.

## JEV model routing

Select `jev/auto` (`JEV Auto`) in `/model`, or start with `pi --model jev/auto`.
JEV chooses a model tier and a thinking level on each new user turn.
For a focused task where you want to avoid downgrades between related turns, select `jev/upgrade` (`JEV Upgrade Only`) instead.
Pi clamps thinking to the chosen model's supported levels and displays the actual route in its footer.
Tool follow-ups and retries keep the physical model and effort for that request.
`JEV Upgrade Only` still asks JEV to classify each eligible turn, but only raises the model tier or thinking level during the session; it does not detect goal changes.
Select `jev/auto` or a physical model when a new goal should be allowed to downgrade.
The router does not change Pi's startup model; press `Ctrl+Alt+S` in `/model` to make a selection the default.

Edit `~/.pi/agent/jev-router.json` (or the file in `PI_CODING_AGENT_DIR`) and run `/reload` to swap any tier.
Each value is a Pi `provider/model-id`, including models on other providers.
For example, `{"B": "openrouter/moonshotai/kimi-k2.6"}` overrides just B.
The defaults are:

| Tier | Model |
| --- | --- |
| S+ | `openai/gpt-6.2-astra` |
| S | `openai/gpt-6.2-sol` |
| A | `openai/gpt-6.1-terra` |
| B | `openai/gpt-6-luna` |

Only JEV runs through OpenRouter by default, using Pi's OpenRouter login or `OPENROUTER_API_KEY` and `typesafe/jev-1.14`.
Eligible requests in trusted sessions send up to 2,000 characters of the new user prompt to OpenRouter and TypeSafe, which may incur charges.
The classifier does not receive conversation history, tool results, attachments, or expanded templates.
The obvious-credential filter is not a guarantee of redaction; select a physical model to avoid routing sensitive prompts through JEV.
If JEV is skipped, unavailable, or times out, the router uses tier A at medium effort.
`--offline` skips classification but does not change the provider of the dispatched chat model.
A missing or unauthenticated target reports which tier needs fixing instead of silently switching providers.
The portable installer includes the extension and leaves the tier overrides local.

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
With missing credentials, an unavailable model, or `--offline`, Pi shows `JEV off (unavailable)` without sending a request.
If a request fails or times out, JEV also switches off and stops retrying; `/self-compact jev on` lets you retry.
The agent tool and native compaction still work with JEV off.

The portable installer includes the extension; run `/reload` in a live TUI or restart Pi to discover it.
To try it without installing, run `pi -ne -e "$HOME/dev/ai/pi-config/extensions/self-compact/index.ts"`.
The uninstaller removes the managed directory symlink, not copies made with `--mode copy`.

## Tool explanations

Pi shows agent work the way Claude Code does.
Each thinking run collapses to one line that starts with `∴`, written by the local Ollama writer, such as `∴ Found that inline.ts hides every tool row except the newest and decided to read index.ts next.`
The summary is as long as the reasoning needs, from one sentence to a few wrapped lines.
While the summary is being written, the line reads `∴ Thinking…`.
A thought that fits on one short line shows as written, without markdown emphasis, with no model call.
Some models, such as OpenAI's GPT models, return only bold step titles as reasoning. Pi shows a run of titles as one plain line, such as `∴ Checking repository status, testing abort behavior`, with no model call.
If the writer fails or is not Ollama, Pi shows the last bold header in the reasoning, or `∴ Thought`.

The lines Claude Code shows between tool groups are mostly the model's own short notes, such as `● Found the bug in inline.ts; testing the fix next.`, written because its system prompt asks for them.
While summaries are on, Pi adds the same request to its prompt guidelines: one sentence before the first tool call, then one or two sentences when the model finds something, changes direction, or starts a new step.
Pi marks each assistant note with `●`, unless the note starts with a heading, list, quote, table, or code block.
This guideline is the only model context the tool explainer adds, and `/explain-tools off` drops it from the next request.

While tools run, Pi shows one compact detail row: what the most recent running call is for, then up to three dim lines of the call itself, such as the shell command or file path.
When that call finishes, Pi switches to another still-running call if there is one.
The row shows the current batch's progress, such as `Running: Shell command · 1 done · 1 failed`, and failures appear as soon as they happen.
Until its summary is ready, the row uses the tool name and target, such as `Running: File read: README.md…`.
Once tools finish, the compact rows collapse to a count, such as `Called 4 tools · ctrl+o to expand`, with a red count when any failed.
Thinking runs, assistant notes, and user messages separate collapsed groups.
File edits and writes always show as Pi draws them, with their diffs, and are never summarized or counted.
They also separate collapsed groups so each `Called N tools` line stays in order around them.

Press `Ctrl+O` to switch between the summaries and Pi's original tool rows and full reasoning.
Thinking summaries need `"hideThinkingBlock": false`, which this repo's `settings.json` sets.
`Ctrl+T` hides thinking entirely and writes that choice back to `settings.json`; press it again to bring the summaries back.
Pi saves thinking summaries with the active session branch, so they survive `/reload` and resume without rerunning the writer.
Call summaries are live only: after a reload, past calls show as `Called N tools`.
The saved records are display metadata, not model context.
Use `/explain-tools recent` to review the last 12 call summaries and which writer made each one.
Subagent calls and Pi's native inline image rendering are left alone.

Automatic summaries run only in trusted TUI sessions and do not block the agent's tool loop.
On loopback only, the default Ollama writer receives the assistant's reasoning for thinking summaries, clipped to 6,000 characters.
For call summaries it receives selected tool arguments, a short excerpt of the user request and of the assistant's visible note, and the end of its reasoning.
Pi excludes tool output and obvious secrets and protected paths from call requests, but its filters do not guarantee redaction.
The optional hosted writer receives fixed operation hints for call summaries only and never writes thinking summaries, so no reasoning, raw commands, filenames, prompts, notes, or tool output are sent automatically.
If the writer fails or returns an unusable summary, Pi tries once more with a narrower ask, without blocking the agent.
`--offline` disables hosted writing, not local Ollama writing, and recent history records `writer disabled offline` for skipped hosted summaries.
A manual `/explain-tools` still sends after you approve its preview, because `--offline` stops only automatic network activity.

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
  "count": 3,
  "writer": "ollama",
  "ollamaModel": "qwen3.5:2b",
  "openrouterModel": "google/gemini-2.5-flash-lite"
}
```

Set `writer` to `ollama`, `openrouter`, or `off`.
`off` keeps the collapsed views but makes no automatic model calls: thinking shows its header or `∴ Thought`, and calls show what ran.
For `ollama`, start Ollama on `127.0.0.1:11434` and run `ollama pull qwen3.5:2b`, or set `ollamaModel` to another installed local model tag.
For `openrouter`, `openrouterModel` must be a chat model available in Pi's OpenRouter catalog.
Neither model ID needs to be specified if you want the defaults above.
`count` sets how many recent calls a bare `/explain-tools` explains, from 1 to 10.
Launch with `--explain-tools-count 4` or `--explain-tools-no-auto` to override either for one session.
The portable installer links the extension and leaves the settings file local.
Restart Pi or run `/reload` after installing or changing that file.
To try it without installation, use `pi -ne -e "$HOME/dev/ai/pi-config/extensions/tool-explainer/index.ts"`.

## Working summaries

Pi shows two labels in the existing editor-border indicator while it works: `⠋ Working · Saved search UX  |  Fix default sort`.
The first describes the session topic, and the second is a short preview that changes when Pi starts processing a new user prompt, not when you queue it.
Each label uses at most six words, and the one-line bar can still clip it if the terminal is too narrow.
When work finishes, the labels stay in the editor's top border, matching its color and without a spinner.
Both labels are on by default, with Ollama's `qwen3.5:2b` as the writer, just like the tool explainer.
Pi shows a fallback immediately and replaces it when the model finishes in the background.
Ollama titles the session from its first eligible request, such as `improve-codebase skill walkthrough`, and summarizes the latest eligible request separately.
Later requests update the session title when they start independent work or replace the main deliverable.
Follow-ups, refinements, verification, and wrap-up keep the current title.
Pi saves the active title on its conversation branch so it survives reopening the session.
Start Ollama on `127.0.0.1:11434` and run `ollama pull qwen3.5:2b` if the model isn't installed.
The local writer uses loopback, rejects cloud models, and works with `--offline`.
If Ollama is unavailable or times out, the fallback stays visible.
Model summaries run in the background only in trusted interactive sessions.
The extension skips attachments, fenced code, and obvious credentials, but these filters are not a guarantee of redaction.
Expanded prompt template text can look like ordinary prompt text and may be included.

```text
/working-summary status
/working-summary session off
/working-summary prompt off
/working-summary ollama off
/working-summary jev on
/working-summary remote on
```

Use `on` or `off` for each switch independently.
`status` shows the selected writer and whether each label came from a model or the fallback.
Commands apply to the loaded session until reload or session replacement.
For persistent defaults, save `working-summary.json` in the Pi agent directory (`~/.pi/agent` unless `PI_CODING_AGENT_DIR` is set).
These are the defaults:

```json
{
  "session": true,
  "prompt": true,
  "ollama": true,
  "ollamaModel": "qwen3.5:2b",
  "jev": false,
  "remote": false
}
```

Set `ollamaModel` to another installed local model tag, or keep both `ollama` and `remote` off to use only the fallback.
With `jev` on, OpenRouter's `typesafe/jev-1.14` checks for mission changes on new prompts while Ollama still writes both labels.
This opt-in can send the current title and two excerpts of up to 384 characters each to OpenRouter and TypeSafe and may incur charges.
If JEV is unavailable or Pi is offline, Ollama checks for mission changes instead.
When reopening a session, Pi restores the saved mission title without contacting JEV.
Setting `remote` to `true` uses OpenRouter instead of Ollama for the full summary, independently of the `jev` switch.
OpenRouter uses Pi's OpenRouter login or `OPENROUTER_API_KEY`.
OpenRouter and its providers can receive up to four 384-character excerpts from the active branch: TypeSafe's `typesafe/jev-1.14` classifies the request and Google's `google/gemini-2.5-flash-lite` writes the labels.
Both calls can incur charges.
OpenRouter uses only the latest prompt when the session label is off.
When the session label is on, new prompts can still be used as topic evidence even if the prompt label is off.
Keep `remote` and `jev` off when prompt excerpts must stay local for this feature.
`--offline` blocks OpenRouter; if the full `remote` writer is selected, that leaves only the fallback.
Missing credentials, provider failures, and timeouts leave the fallback available without interrupting the foreground agent.

The portable installer includes the extension and leaves the preferences file local.
Restart Pi or run `/reload` to load it or apply changed file defaults.
To try it without installing, run `pi -ne -e "$HOME/dev/ai/pi-config/extensions/working-summary/index.ts"`.

## Planning and implementation commands

These commands are available globally in Pi:

```text
/skill:plan-feature Add saved searches for the current user
/skill:plan-chore Update the project's lint configuration
/skill:plan-bugfix Search results disappear after clearing a filter
/skill:implement /path/to/plan.md
```

The planning commands investigate the repository and write a plan without implementing it.
Plans use the requested path or the repository's documented planning location, falling back to the operating system's temporary directory.
`/skill:implement` builds a supplied plan and verifies the result in use.

Each skill lives in `skills/<name>/SKILL.md` and uses Pi's native skill commands.
Claude Code exposes the same skills as `/plan-feature`, `/plan-chore`, `/plan-bugfix`, and `/implement`.
Run `/reload` in an existing Pi session to discover new commands.

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

## Goal mode

Goal mode is available globally through the pinned [`pi-goal-x@0.34.1`](https://github.com/tmonk/pi-goal-x/tree/v0.34.1) package in `settings.json`.
Run `/reload` in an idle Pi session, or restart Pi, after installation.

```text
/goal Implement the agreed saved-search feature, verify every acceptance criterion in use, preserve unrelated changes, and follow repository instructions. Do not add automated tests, ADRs, or spec files unless explicitly required.
/goal-status
/goal-pause
/goal-resume
```

`/goal <outcome>` discusses the outcome, constraints, optional tasks, and completion requirements before asking for confirmation.
No implementation should begin until you confirm the proposal.
Choose the completion auditor when confirming so a separate agent inspects the result before accepting completion.
Use `/goal-direct <objective>` only when the complete objective is already agreed and you want execution to start immediately without drafting.
If a goal created through the model's `create_goal` tool remains idle, run `/goal-resume` explicitly.
Make success criteria self-contained when deriving a goal from a plan in a temporary file.

| Command | Purpose |
| --- | --- |
| `/goal-status verbose` | Inspect the objective, usage, effective settings, and storage location. |
| `/goal-status health` | Check goal storage and runtime coherence, not completion. |
| `/goal-list` | List the current project's open goals. |
| `/goal-pause` | Pause the focused goal and stop its turn. |
| `/goal-resume` | Resume explicitly and renew its autonomous-run allowance. |
| `/goal-focus` | Select an existing goal for this session. |
| `/goal-unfocus` | Detach this session without closing the goal. |
| `/goal-tweak <change>` | Review and confirm changes, including a lifetime token budget. |
| `/goal-clear` | Archive the goal after confirmation; cancelling leaves it unchanged. |
| `/goal-cancel` | Discard an unconfirmed draft. |
| `/goal-settings` | Edit machine-global or project-specific preferences. |

Use `/goal-clear`, not `/goal clear`.
Escape during work pauses the goal and stops its turn with the default controls.
An open dialog or expanded dashboard owns Escape first.
`Ctrl+Shift+T` expands the dashboard; `Ctrl+Shift+A` toggles the focused goal's auditor, so leave it enabled when independent completion review is required.
Pi must remain running for automatic continuation; there is no background daemon.

### Machine-local defaults

On another machine, create `${PI_CODING_AGENT_DIR:-~/.pi/agent}/pi-goal-x-settings.json` as a **regular file**, preferably mode `0600`, before using goal mode:

```json
{
  "maxAutonomousRuns": 20,
  "idleContinuationBackoff": true,
  "networkRecovery": {
    "maxAttempts": 3,
    "maxDelayMs": 60000
  },
  "autoSelectSingleGoal": false,
  "hideUnfocusedPrompt": true,
  "hideUnfocusedBanner": true,
  "disabled": false,
  "auditorProjectResources": false
}
```

Merge these preferences if the file already exists instead of overwriting unrelated settings.
Do not symlink this file: the extension's settings editor refuses symlink targets.
The installers therefore leave it local, while the package declaration remains portable in the tracked Pi settings.
Install the exact release with `pi install npm:pi-goal-x@0.34.1` and confirm it with `pi list`.

These defaults allow twenty extension-started runs per creation/resume period and three extension-level provider recovery attempts, with repeated idle replies slowed down.
Unset run allowances and zero recovery attempts mean unlimited execution/recovery respectively; `maxAutonomousRuns: 0` instead disables automatic continuation.
A run can contain many model requests and tool calls, and native retries and separate completion audits are not a strict request or financial cap.
An optional per-goal token budget is a total lifetime allowance checked at accounting boundaries and may overshoot an in-flight request.
Use a provider-enforced spending limit when a hard financial ceiling is required.

`disabled: false` keeps the completion auditor enabled by default; this setting controls the auditor, not the entire extension.
The auditor uses the current model and authentication in a separate session, without project skills/extensions by default.
It can inspect files and run `bash`, so its read-only instructions are **not an operating-system sandbox**.
Project `.pi/pi-goal-x-settings.json` leaves and supported `PI_GOAL_*` environment overrides can supersede global defaults.
Use `/goal-status verbose` to inspect the effective values and `/goal-refresh` after external preference edits.

### Storage and upgrades

Global availability does not mean a shared cross-project goal pool.
Goals, progress, archives, and the ledger live under `<cwd>/.pi/goals/`, with nearby generated pool snapshots; start Pi at the intended project root.
Leave `goalsRoot` and `PI_GOAL_ROOT` unset to keep projects separate.
Fresh sessions do not automatically focus or resume old goals with these defaults.
Focus is session/branch-local, but goal files are shared by sessions using the same pool, and another session requires explicit resume to take execution ownership.
`/tree` restores focus, not historical goal files or application files.

Treat goal records as local runtime state, not feature specs, and do not edit their generated metadata by hand.
If a project needs Git exclusions, exclude the actual goal runtime paths narrowly; do not ignore all of `.pi/`, which may contain tracked configuration or extensions.
The package is intentionally pinned, so upgrading means reviewing a release, changing the exact version, and repeating live goal/auditor verification.

To remove goal mode without deleting records or sessions:

```bash
pi remove npm:pi-goal-x@0.34.1
```

Then run `/reload` or restart Pi.
The regular extension preference file can remain for a later reinstall.

## What stays local

These are intentionally excluded and should be created on each machine as needed:

- `auth.json`
- `sessions/`
- `git/`
- `bin/`
- `pi-debug.log`
- `node_modules/`
- `pi-goal-x-settings.json` (regular machine-local goal preferences)

## Install on another machine

Clone this repo, then run:

```bash
cd ~/dev/ai/pi-config
./install.sh
```

By default this links the portable config into `~/.pi/agent`.
The root `./install.sh all` and `just sync` run this script in symlink mode, and the root uninstall runs `uninstall.sh`.

To target a different location:

```bash
PI_CODING_AGENT_DIR=/path/to/pi/agent ./install.sh
```

To copy files instead of linking them:

```bash
./install.sh --mode copy
```

Copy mode uses `rsync` to merge managed directories without deleting local files and excludes machine-local files such as extension `.env` files and package caches.
If a target is a symlink or has the wrong file type, copy mode backs it up before installing the replacement.

## Link this repo on the current machine

```bash
cd ~/dev/ai/pi-config
./link-local.sh
```

This is a small wrapper around `install.sh --mode symlink`.
In symlink mode, `~/dev/ai/pi-config` is the source of truth.
Pi's global settings, keybindings, and skills point back to this repo, while local-only files remain under `~/.pi/agent`.

In symlink mode, an existing file or directory that must be replaced is moved into a unique timestamped backup directory under:

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
