---
name: plan-bugfix
description: Reproduce a reported bug, investigate its root cause, and create a surgical fix plan without implementing it.
argument-hint: "<bug description or issue>"
disable-model-invocation: true
metadata:
  source: "TAC .claude/commands/bug.md; Arete arete/prompts/plan.md"
---

# Bugfix planning

Create a root-cause fix plan a separate implementer can follow without this conversation.
Use the symptoms, issue details, or linked material supplied with the command.
If no bug is specified, ask for it before proceeding.

## Workflow

1. Read the repository's agent instructions and `README.md` to find how to run the product.
   Inspect the working tree and preserve existing changes.
2. Start the investigation by reproducing the reported failure as closely as possible to an end user's experience, using safe local or sandbox data.
   Use the real browser flow for a web UI, the real command for a CLI, or real requests for an API.
   Record the exact setup, inputs, expected result, actual result, and evidence.
   If reproduction is blocked, record what is missing and distinguish hypotheses from confirmed findings.
3. Trace the observed failure through the relevant code and callers to identify its root cause.
   Explain why the failure occurs, not just where the symptom appears.
   Propose the smallest coherent change that fixes the cause and preserves neighboring behavior.
4. Write the plan using the format below, replacing every placeholder with concrete findings.
   Name real paths and exact changes, and order tasks by dependency.
   Include replaying the original reproduction after the fix, named edge and error cases, and a nearby regression check.
   Use the repository's actual check commands.
   Plan new automated tests or spec files only when the user or repository instructions explicitly require them; otherwise use existing checks and direct verification.
5. Save to the user's requested path, or the repository's documented planning location.
   If neither exists, use `plan-bugfix-<descriptive-slug>.md` in the operating system's temporary directory rather than adding a permanent spec to the repository.
   Choose a fresh filename instead of overwriting an unrelated plan.

Planning leaves application code, dependencies, and configuration unchanged.
Record assumptions and human-only prerequisites; ask only when a missing answer prevents a sound plan.

## Completion report

After saving the completed plan, report a concise summary to stdout in the final response.
Summarize the planned outcome, main implementation steps, verification approach, and any blockers.
Include a clickable Markdown link to the saved plan using its actual absolute path, for example `[Plan](/absolute/path/to/plan.md)`.

## Plan format

```md
# Bugfix: <bugfix name>

## Bug Description
<Describe symptoms, impact, expected behavior, and actual behavior.>

## Problem Statement
<Define the specific failure and the conditions that trigger it.>

## Steps to Reproduce
1. <Exact setup and user action or command.>
2. <Expected result, actual result, and captured evidence.>
<Mark whether reproduction succeeded, and record blockers if it did not.>

## Root Cause Analysis
<Explain the causal path with relevant code references and observed evidence.>
<Label any unconfirmed explanation as a hypothesis.>

## Solution Statement
<Describe the surgical fix and why it resolves the cause.>

## Relevant Files
- `<existing path>`: <Why it matters and exactly what changes here.>

### New Files
- `<new path>`: <Purpose, or omit this subsection if none are needed.>

## Step by Step Tasks
### 1. <Task name>
- <Concrete action, including the file and intended behavior.>

### 2. <Next task name>
- <Continue in dependency order, with verification as the final task.>

## Acceptance Criteria
- <Observable outcome that proves the reported failure is fixed.>

## Verification
1. <Replay the original reproduction with its expected corrected result.>
2. <Exercise relevant edge and error cases with expected results.>
3. <Exercise a nearby behavior that must remain unchanged.>
<Identify existing automated coverage and any explicitly required test changes.>

## Validation Commands
- `<reproduction command or user flow>`: <Observed before-fix failure and expected after-fix result.>
- `<command from the repository's docs or configuration>`: <What it checks and the expected result.>
<Include working directories, setup, and the repository's full check gate where applicable.>
<Separate commands already run during investigation from commands the implementer must run.>

## Notes
<Assumptions, risks, blockers, human-only prerequisites, and boundaries to preserve.>
<Include issue references when supplied.>
```
