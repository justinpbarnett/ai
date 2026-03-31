---
name: plan-ceo-review
description: >
  CEO/Founder perspective on feature planning. Rethinks the problem to find the 10-star product hidden in the request. Four modes: Expansion, Selective Expansion, Hold Scope, Reduction.
  Triggers on: "ceo review", "plan ceo", "review plan", "is this the right thing to build", "rethink this"
---

# Plan: CEO Review

Apply CEO/founder thinking to challenge and refine the feature plan before any code is written.

## Variables

- `argument` -- The feature idea, requirements doc, or plan to review

## Instructions

### Step 0: Parse Input

If `argument` is a file path, read it. Otherwise treat as inline description.

### Step 1: Understand the Current Ask

Extract and summarize:
- What problem is being solved?
- For whom? (who is the user)
- What outcome does the user expect?
- What's the assumed solution approach?

### Step 2: Challenge the Framing

For each assumption, ask:
- Is this actually what the user needs?
- Are we solving the root problem or a symptom?
- Is there a simpler wedge that delivers 80% of value?

Apply one of four modes:
1. **Expansion** -- Find capabilities the user didn't realize they needed
2. **Selective Expansion** -- Add 1-2 high-leverage additions
3. **Hold Scope** -- Confirm the current scope is optimal
4. **Reduction** -- Slice down to the minimum viable wedge

### Step 3: Generate Alternatives

Produce 2-3 implementation approaches with:
- Scope difference
- Effort estimate (XS/S/M/L/XL)
- Risk profile
- Learnings value

### Step 4: Recommendation

State clearly:
- Which mode you applied
- What changed from the original ask
- The recommended approach
- Why this beats the alternatives

### Step 5: Output Design Doc

Write a refined design doc with:
- Problem statement (1-2 sentences)
- User persona
- Success criteria (measurable)
- Scope boundaries
- Alternative approaches considered

## Output Format

```
CEO Review: <feature name>

Mode Applied: <Expansion|Selective|Hold|Reduction>

Original Problem: <1-2 sentences>

Refined Problem: <1-2 sentences>

Key Challenges:
- <assumption 1> → <why it's wrong/could be wrong>
- <assumption 2> → <why it's wrong/could be wrong>

Alternatives Considered:
1. <approach> - <effort> - <when to pick>
2. <approach> - <effort> - <when to pick>

Recommendation: <approach>

Design Doc: <path or inline>
```

## Cookbook

<If: the user pushback indicates they've already considered your feedback>
<Then: acknowledge their expertise, document their reasoning, proceed with their original approach>

<If: you identify a significantly different problem worth solving>
<Then: present it as a separate recommendation, don't force it into the current plan>

<If: the scope is already minimal>
<Then: focus on execution quality, not scope reduction>
