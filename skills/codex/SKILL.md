---
name: codex
description: >
  Get a second opinion from a different AI model. Independent code review from OpenAI Codex CLI. Three modes: review (pass/fail gate), adversarial challenge, and open consultation.
  Triggers on: "codex", "second opinion", "different ai review", "cross model", "get another view"
---

# Codex

Get an independent code review from a different AI model. Uses OpenAI Codex CLI or similar for cross-model analysis.

## Variables

- `argument` -- What to review (defaults to current changes if not specified)
- `mode` -- review|challenge|consult (optional, defaults to review)

## Instructions

### Step 0: Determine Mode

- **review**: Pass/fail gate, looks for blockers
- **challenge**: Adversarial, actively tries to break the code
- **consult**: Open discussion, session continuity

### Step 1: Prepare Code for Review

Get the current diff:
```
git diff HEAD
```

Or if a specific file is mentioned, prepare that file.

### Step 2: Run Second Opinion

Invoke Codex or alternative AI:
- Pass the code/diff
- Specify the mode
- Request specific focus areas

### Step 3: Parse Results

Extract:
- Issues found
- Severity
- Recommendations

### Step 4: Cross-Model Analysis

If both this review and a previous review exist:
- Compare findings
- Note overlapping issues
- Note unique findings from each model

### Step 5: Present Results

Format the findings clearly with severity levels.

## Output Format

```
Codex Review: <target>

Mode: <review|challenge|consult>

Issues Found:
- <issue> [<severity>] - <explanation>
- <issue> [<severity>] - <explanation>

Cross-Model Analysis (if applicable):
- Overlapping: <N> issues
- Claude unique: <N> issues  
- Codex unique: <N> issues

Verdict: <PASS|FAIL|CONDITIONAL>
```

## Severity Levels

- **blocker**: Must fix before merge
- **major**: Should fix, reason about
- **minor**: Consider fixing
- **nit**: Style/preference

## Cookbook

<If: mode is not specified>
<Then: default to review mode (pass/fail gate)>

<If: issues are blockers>
<Then: prioritize fixing before continuing>

<If: different AIs found different issues>
<Then: this is valuable - merge both sets of feedback>

<If: no issues found>
<Then: good sign, but still review for any missed items>
