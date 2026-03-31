---
name: plan-design-review
description: >
  Senior Designer perspective on feature planning. Rates each design dimension 0-10, explains what a 10 looks like, then edits the plan to get there. AI slop detection.
  Triggers on: "design review", "plan design", "design audit", "look at this design"
---

# Plan: Design Review

Apply senior designer thinking to audit and improve the design aspect of feature plans.

## Variables

- `argument` -- The feature plan, design doc, or requirements to review

## Instructions

### Step 0: Parse Input

If `argument` is a file path, read it. Otherwise treat as inline description.

### Step 1: Identify Design Dimensions

For the given plan, identify relevant design dimensions:
- Visual hierarchy
- UX flow / user journey
- Information architecture
- Accessibility
- Responsive/adaptive behavior
- Animation/transitions
- Error states
- Empty states
- Loading states
- Mobile-first considerations

### Step 2: Rate Each Dimension

For each dimension:
- Give a score 0-10
- Explain what a 10/10 looks like
- Explain what's missing for a 10

### Step 3: AI Slop Detection

Flag common AI design patterns that feel generic:
- Overused gradients
- Generic illustrations
- Cookie-cutter layouts
- Missing personality
- No consideration of brand

### Step 4: Ask Stakeholder Questions

For each design choice that needs confirmation, ask one clear question.

### Step 5: Produce Edits

Update the design doc with specific improvements for any dimension rated <8.

## Output Format

```
Design Review: <feature name>

Dimensions Rated:
| Dimension | Score | What's Missing for 10 |
|-----------|-------|---------------------|
| ... | ... | ... |

AI Slop Flags:
- <flag 1>
- <flag 2>

Questions for You:
1. <question>

Proposed Improvements:
- <improvement 1>
- <improvement 2>
```

## Cookbook

<If: the plan has no visual/UI component>
<Then: focus on UX flow, information architecture, and interaction patterns>

<If: you see the same generic pattern used everywhere>
<Then: flag as AI slop and suggest something more distinctive>

<If: the stakeholder answers a question>
<Then: incorporate their answer into the design doc and proceed>
