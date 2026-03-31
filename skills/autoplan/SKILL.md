---
name: autoplan
description: >
  Automatically run CEO → Design → Engineering review in sequence. Surfaces only taste decisions for user approval.
  Triggers on: "autoplan", "run all reviews", "full review", "plan everything"
---

# Autoplan

Automatically run the full planning review pipeline: CEO → Design → Engineering.

## Variables

- `argument` -- Feature idea or requirements to review

## Instructions

### Step 0: Parse Input

If `argument` is a file path, read it. Otherwise treat as inline description.

### Step 1: CEO Review

Invoke `/plan-ceo-review`:
- Rethink the problem
- Find the 10-star product
- Refine scope

Wait for user confirmation if scope changed significantly.

### Step 2: Design Review

Invoke `/plan-design-review`:
- Rate design dimensions
- Flag AI slop
- Identify improvements

Wait for user confirmation on design choices.

### Step 3: Engineering Review

Invoke `/plan-eng-review`:
- Data flow diagrams
- Edge cases
- Security considerations
- Test matrix

### Step 4: Synthesize

Combine all three into a unified plan:
- Scope (from CEO)
- Design (from Design)
- Technical approach (from Engineering)
- Action items

### Step 5: Present for Approval

Surface only:
- Key decisions that need user input
- Tradeoffs that require judgment

Everything else is handled automatically.

## Output Format

```
Autoplan Complete

CEO Review:
- Mode: <...>
- Refinements: <...>

Design Review:
- Rated dimensions: <...>
- Improvements: <...>

Engineering Review:
- Data flow: <...>
- Edge cases: <...>
- Security: <...>

Unified Plan:
<summary>

Decisions Needed:
1. <decision>
```

## Cookbook

<If: CEO review significantly changes scope>
<Then: pause and get user confirmation before design review>

<If: design review identifies major changes>
<Then: present to user before engineering review>

<If: all reviews pass with no decisions needed>
<Then: proceed to implementation>

<If: user rejects something>
<Then: iterate on that specific phase>
