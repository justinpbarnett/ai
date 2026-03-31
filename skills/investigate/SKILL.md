---
name: investigate
description: >
  Systematic root-cause debugging. Iron Law: no fixes without investigation. Traces data flow, tests hypotheses, stops after 3 failed fixes.
  Triggers on: "debug", "investigate", "find the bug", "why is this broken", "root cause"
---

# Investigate

Systematic debugging with a 4-phase root cause process. Iron Law: no fixes without investigation.

## Variables

- `argument` -- Description of the bug or issue to investigate

## Instructions

### Step 0: Understand the Symptom

Extract:
- What should happen?
- What's actually happening?
- When did it start?
- What's the reproduction steps?

### Step 1: Gather Evidence

Before making any changes:
- Read relevant code
- Check logs
- Look at recent changes (git diff)
- Reproduce the issue if possible

Document what you found:
- Files examined
- Data observed
- Patterns noticed

### Step 2: Form Hypotheses

Generate 2-3 possible root causes based on evidence.
For each hypothesis:
- Explain the mechanism
- Predict what you'd see if this is the cause

### Step 3: Test Hypotheses

For each hypothesis:
- Design a test to verify/disprove
- Run the test
- Document results

Stop after 3 failed fix attempts. Escalate to user with findings.

### Step 4: Root Cause Found

Once confirmed:
- State the root cause clearly
- Explain why it causes the symptom
- Propose the fix

### Step 5: Apply Fix

After root cause is confirmed:
- Make the minimal fix
- Verify it works
- Add regression test if possible

### Step 6: Document

Write up:
- Symptom
- Root cause
- Fix applied
- How to detect earlier next time

## Output Format

```
Investigate: <issue summary>

Symptom: <what's broken>

Evidence Gathered:
- <finding 1>
- <finding 2>

Hypotheses:
1. <hypothesis> → <test result>
2. <hypothesis> → <test result>
3. <hypothesis> → <test result>

Root Cause: <cause>

Fix Applied: <what was changed>

Prevention: <how to detect earlier>
```

## Iron Law

**No fixes without investigation.** If asked to fix something:
1. First investigate to understand the root cause
2. Don't apply band-aids
3. Stop after 3 failed fix attempts and escalate

## Cookbook

<If: user asks to fix without investigation>
<Then: explain the Iron Law, offer to investigate first>

<If: 3 fix attempts fail>
<Then: stop, summarize findings, ask for user's help>

<If: the issue is unclear>
<Then: ask for more reproduction details before proceeding>

<If: you find multiple related issues>
<Then: note them but focus on the primary symptom first>
