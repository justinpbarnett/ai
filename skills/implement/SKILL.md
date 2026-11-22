---
name: implement
description: Build the change described by an implementation plan, verify it in use, and report the results.
argument-hint: "<path to plan or inline plan>"
disable-model-invocation: true
metadata:
  source: "TAC .claude/commands/implement.md and build.md; Arete arete/prompts/build.md"
---

# Implement a plan

Implement the plan supplied with the command, either as a file path or inline content.
If no plan is supplied or clearly identified in the conversation, ask for it before proceeding.

## Workflow

1. Read the complete plan, the repository's agent instructions, and the relevant documentation and code.
   Inspect the working tree before editing so existing changes remain distinguishable from yours.
2. Check the plan against the current code and identify its acceptance criteria, verification steps, and dependencies.
   Correct a stale implementation approach when the intended outcome is clear, and explain the deviation in the final report.
   Ask before proceeding when an unresolved decision changes the requested outcome or requires unavailable permissions or unsafe actions.
3. For a bugfix, reproduce the failure through the running product, real CLI, or real API before editing, using safe local or sandbox data.
   Record the result so the same flow can demonstrate the fix afterward.
   Report any reproduction blocker rather than presenting an unconfirmed cause as established.
4. Implement the plan in dependency order, following existing patterns and keeping the diff focused.
   Write simple, self-documenting code and preserve unrelated work.
   Add dependencies only when the plan justifies them, using the repository's dependency manager.
   Add or change automated tests or spec files only when the user or repository instructions explicitly require them.
5. Run focused checks while working, then the repository's documented full check gate before finishing.
   Discover commands from repository documentation and configuration rather than assuming a language or stack.
   Fix failures and review findings before calling the work complete.
   Respect tool and sandbox restrictions; report refused or unavailable actions instead of working around them.
6. Verify every acceptance criterion in use, as closely as possible to how the user encounters it.
   Follow the plan's verification steps and cover its edge and error cases and nearby behavior.
   For UI changes, inspect the rendered result and interactions rather than relying only on a successful build.
   Record actual observations; distinguish passed checks from checks that were blocked or not run.
7. Review the final diff for correctness, scope, secrets, and accidental churn.
   Run `git diff --check` and `git diff --stat`, distinguishing your changes from pre-existing edits.
   Account for new untracked files separately because `git diff --stat` excludes them.

Leave the changes uncommitted unless the user asks for a commit or the repository's workflow requires one.
Pushes, pull requests, and deployments require their own authorization.

## Report

Finish with a concise summary containing:

- What changed and what the user will observe.
- Files changed and the diff statistics, including new files not shown by Git's diff.
- Checks run and evidence for each acceptance criterion.
- Deviations from the plan, remaining blockers, and anything a reviewer should examine.
