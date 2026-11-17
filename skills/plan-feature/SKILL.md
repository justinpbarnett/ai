---
name: plan-feature
description: Create a codebase-informed implementation plan for a new feature without implementing it.
argument-hint: "<feature description or issue>"
disable-model-invocation: true
metadata:
  source: "TAC .claude/commands/feature.md; Arete arete/prompts/plan.md"
---

# Feature planning

Create a plan a separate implementer can follow without this conversation.
Use the feature description, issue details, or linked material supplied with the command.
If no feature is specified, ask for it before proceeding.

## Workflow

1. Read the repository's agent instructions and `README.md`, then follow their pointers to relevant documentation.
   Inspect the working tree and preserve existing changes.
2. Research the affected code, its callers, and existing patterns before choosing an approach.
   Discover the actual file layout, dependency manager, and check commands from the repository.
3. Define the user-visible outcome, acceptance criteria, scope, and edge cases.
   Prefer the existing architecture and dependencies; justify any additions.
   Decide reasonable unspecified details and record assumptions.
   Ask only when a missing answer prevents a sound plan.
4. Write the plan using the format below, replacing every placeholder with concrete findings.
   Name real paths, describe each proposed change, and order tasks by dependency.
   Include user-level verification with steps and expected results for every acceptance criterion, named edge and error cases, and one nearby behavior that must keep working.
   Plan new automated tests or spec files only when the user or repository instructions explicitly require them; otherwise use existing checks and direct verification.
5. Save to the user's requested path, or the repository's documented planning location.
   If neither exists, use `plan-feature-<descriptive-slug>.md` in the operating system's temporary directory rather than adding a permanent spec to the repository.
   Choose a fresh filename instead of overwriting an unrelated plan.

Planning leaves application code, dependencies, and configuration unchanged.
Record any required permissions, migrations, credentials, or human-only actions instead of performing them.

## Completion report

After saving the completed plan, report a concise summary to stdout in the final response.
Summarize the planned outcome, main implementation steps, verification approach, and any blockers.
Include a clickable Markdown link to the saved plan using its actual absolute path, for example `[Plan](/absolute/path/to/plan.md)`.

## Plan format

```md
# Feature: <feature name>

## Feature Description
<Describe the behavior, its purpose, and its value to users.>

## User Story
As a <type of user>,
I want to <action or goal>,
so that <benefit>.

## Problem Statement
<Explain the problem or opportunity, grounded in current behavior.>

## Solution Statement
<Describe the chosen approach and how it fits the existing architecture.>

## Relevant Files
- `<existing path>`: <Why it matters and exactly what changes here.>

### New Files
- `<new path>`: <Purpose, or omit this subsection if none are needed.>

## Implementation Plan
### Foundation
<Shared prerequisites, interfaces, or data changes, if needed.>

### Core Implementation
<The main behavior to add.>

### Integration
<How callers, interfaces, and existing behavior connect to the change.>

## Step by Step Tasks
### 1. <Task name>
- <Concrete action, including the file and intended behavior.>

### 2. <Next task name>
- <Continue in implementation order, with verification as the final task.>

## Verification Strategy
<Numbered steps using the running product, real CLI, or real API.>
<Give inputs, expected results, relevant edge and error cases, and a nearby regression check.>
<Identify existing automated coverage and any explicitly required test changes.>

## Acceptance Criteria
- <Specific, observable outcome that verification can demonstrate.>

## Validation Commands
- `<command from the repository's docs or configuration>`: <What it checks and the expected result.>
<Include working directories, setup, and the repository's full check gate where applicable.>
<Separate commands already run during research from commands the implementer must run.>

## Notes
<Assumptions, trade-offs, dependencies, risks, blockers, and human-only prerequisites.>
<Include issue references when supplied, and boundaries the implementer must preserve.>
```
