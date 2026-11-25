# JEV compaction for Claude Code and Codex CLI

After an answered turn, JEV reads the current request, the reply, and the preceding request when available. It looks for a finished objective or an explicit handoff. Open questions, pending checks, decisions, and ongoing exploration keep the conversation intact. A new topic can still be in the middle of a discussion.

From 90,000 context tokens, a clearly independent task switch can qualify. From 120,000, a natural stopping point on the same task can also qualify. When JEV approves with at least 0.8 confidence, the client can compact at the idle boundary. Above 150,000 tokens the same verdict also shows a strong recommendation. If JEV is offline, uncertain, or lacks a shareable exchange, the plugin stays quiet and the client's native context limit still applies.

Claude Code loads the mod from the local `ai-mods` marketplace in its global settings. For Codex CLI, run these commands from the repository root, then review the plugin's hooks in `/hooks`:

```sh
codex plugin marketplace add ./mods
codex plugin add jev-compact@ai-mods
```

Codex needs Bun on the hook process's PATH. It uses the local app-server daemon to compact the same idle thread and checks that the answered turn is still the latest. Standalone sessions, including `--no-daemon`, can show the JEV recommendation using their local transcript.

Both clients use `arete ask`, which sends up to 512 characters per excerpt to JEV through OpenRouter. The ends of long replies are included so JEV can see outstanding questions. The hooks skip credential-like text. Arete's per-repository JEV setting controls these requests.
