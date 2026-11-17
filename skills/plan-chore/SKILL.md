---
name: plan-chore
description: Create a precise implementation plan for maintenance, refactoring, tooling, or dependency work without implementing it.
argument-hint: "<chore description or issue>"
disable-model-invocation: true
metadata:
  source: "TAC .claude/commands/chore.md; Arete arete/prompts/plan.md"
---

# Chore planning

Create a focused maintenance plan a separate implementer can follow without this conversation.
Use the chore description, issue details, or linked material supplied with the command.
If no chore is specified, ask for it before proceeding.

## Workflow

1. Read the repository's agent instructions and `README.md`, then the documentation and code relevant to the chore.
   Inspect the working tree and preserve existing changes.
   Discover the actual file layout, dependency manager, and check commands from the repository.
2. Establish what must change and what behavior must remain unchanged.
   Identify affected callers, configuration, generated artifacts, and operational prerequisites.
   Prefer a focused change that follows existing conventions over unrelated cleanup.
3. Write the plan using the format below, replacing every placeholder with concrete findings.
   Name real paths and exact edits, order tasks by dependency, and make verification the final task.
   For dependency or tooling changes, include compatibility and lockfile implications.
   For stateful or operational changes, include a safe rollout and recovery approach.
   Plan new automated tests or spec files only when the user or repository instructions explicitly require them; otherwise use existing checks and direct verification.
4. Save to the user's requested path, or the repository's documented planning location.
   If neither exists, use `plan-chore-<descriptive-slug>.md` in the operating system's temporary directory rather than adding a permanent spec to the repository.
   Choose a fresh filename instead of overwriting an unrelated plan.

Planning leaves application code, dependencies, and configuration unchanged.
Record assumptions and human-only prerequisites; ask only when a missing answer prevents a sound plan.

## Completion report

After saving the completed plan, report a concise summary to stdout in the final response.
Summarize the planned outcome, main implementation steps, verification approach, and any blockers.
Include a clickable Markdown link to the saved plan using its actual absolute path, for example `[Plan](/absolute/path/to/plan.md)`.

## Plan format

```md
# Chore: <chore name>

## Chore Description
<Describe the maintenance work, why it is needed, and its intended outcome.>

## Scope and Invariants
<Define the change boundary and behavior or interfaces that must remain unchanged.>

## Relevant Files
- `<existing path>`: <Why it matters and exactly what changes here.>

### New Files
- `<new path>`: <Purpose, or omit this subsection if none are needed.>

## Step by Step Tasks
### 1. <Task name>
- <Concrete action, including the file and intended result.>

### 2. <Next task name>
- <Continue in dependency order, with verification as the final task.>

## Acceptance Criteria
- <Specific, observable outcome that proves the chore is complete.>

## Verification
<Numbered steps to exercise the changed tooling or behavior as its user would.>
<Give inputs and expected results, and demonstrate that the invariants still hold.>

## Validation Commands
- `<command from the repository's docs or configuration>`: <What it checks and the expected result.>
<Include working directories, setup, and the repository's full check gate where applicable.>
<Separate commands already run during research from commands the implementer must run.>

## Notes
<Assumptions, compatibility concerns, risks, blockers, human-only prerequisites, and recovery steps where relevant.>
<Include issue references when supplied.>
```
