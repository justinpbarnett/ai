# JEV compaction for Claude Code and Codex CLI

Both clients strongly recommend `/compact` when current context exceeds 150,000 tokens. The warning works with JEV offline and resets when context drops back to 150,000 or less.

Automatic compaction runs at a task boundary. From 90,000 tokens, JEV can identify a change of task. From 120,000 tokens, it can also identify a finished task. A yes with at least 0.8 confidence lets the client compact after the answer. Crossing 150,000 alone only shows the warning.

Claude Code loads the mod from the local `ai-mods` marketplace in its global settings. For Codex CLI, run these commands from the repository root, then review the plugin's hooks in `/hooks`:

```sh
codex plugin marketplace add ./mods
codex plugin add jev-compact@ai-mods
```

Codex needs Bun on the hook process's PATH. It uses the local app-server daemon to compact the same idle thread and checks that the answered turn is still the latest. Standalone sessions, including `--no-daemon`, still show the token warning.

Both clients use `arete ask`, which sends excerpts to JEV through OpenRouter. Codex compares up to 512 characters each from two user messages or from the current request and answer. Claude uses up to 12,000 characters of recent conversation and 2,000 from the new message. The hooks skip credential-like text. Arete's per-repository JEV setting controls these requests.
