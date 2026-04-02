# Proof methodology

Proof is distinct from evaluation. The evaluator checks whether the code meets its declared contract. Proof checks whether the running result actually does what the user asked for, the way a user would verify it. Think of it as the difference between "does the code look right" and "does the thing work when I use it."

## How to prove by project type

| Project type | Method |
|---|---|
| Web app (Playwright available) | Start dev server if needed. Navigate to the affected pages, interact with the feature (click, fill, submit), screenshot each key state. |
| Web app (no Playwright) | Start dev server. Use curl or Bash to hit endpoints. Capture request/response output. |
| CLI tool | Run the actual command with realistic inputs. Capture terminal output. |
| API | Start the server if needed. Hit affected endpoints with curl. Capture request/response pairs. |
| Library / config | Run consuming code or test suite. Capture output showing the change works. |
| Data / script | Execute with real or representative data. Capture output. |
| Game | Run the game, exercise the feature, capture logs or screenshots. |

## Capture

- **Web projects with Playwright:** use the Playwright MCP tools to navigate, interact, and screenshot. Save screenshots to `/tmp/proof/`.
- **Everything else:** run the relevant commands via Bash and capture output.
- Capture at least one piece of evidence per key behavior. For multi-step flows, capture each step.

## Review

Read the screenshots (the Read tool can display images) or review command output. Compare against the original intent (the user's description or spec, not the generator's contract). Ask:

1. Does this do what was requested?
2. For UI: is it visually correct (layout, content, state)?
3. For CLI/API: does the output match expectations?
4. Any obvious breakage?

If proof doesn't confirm completion, **stop**. Report what's wrong. Don't proceed to commit.

## When proof can't run

If the app won't start, dependencies are missing, or there's nothing observable to test (pure config with no consumer), note this in the report. Never skip proof silently. Explain why it couldn't be captured and what manual verification the user should do.

## Including proof in PRs

When a PR is created, include a **Proof** section in the body:
- What was tested and how
- Screenshot paths or pasted terminal output
- Confirmation that proof was reviewed against the original intent
