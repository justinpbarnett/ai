---
name: design-shotgun
description: >
  Generate multiple AI design variants, open a comparison board, iterate until you approve a direction. Taste memory biases toward your preferences.
  Triggers on: "design variants", "design options", "show me options", "design exploration", "multiple designs"
---

# Design Shotgun

Generate multiple design variants for comparison and selection.

## Variables

- `argument` -- What to design (feature, page, component)

## Instructions

### Step 0: Understand the Target

Parse what needs designing:
- What is it?
- Who is it for?
- What should it accomplish?

### Step 1: Generate Variants

Create 3-5 different design approaches:
1. **Safe** - Conventional, expected pattern
2. **Creative** - Novel approach with risks
3. **Minimal** - Stripped down to essentials
4. **Bold** - High impact, may not fit all users
5. **Different** - Alternative paradigm

For each:
- Describe the approach
- Mock up the UI (ASCII or description)
- Note tradeoffs

### Step 2: Present Options

Show all variants with:
- Visual description
- Pros
- Cons
- When to pick

### Step 3: User Selection

Wait for user to:
- Pick one
- Request modifications
- Ask for more options

### Step 4: Iterate

If user wants changes:
- Modify the selected variant
- Re-present

## Output Format

```
Design Shotgun: <target>

Variants:
1. <name>: <description>
   - Pros: <...>
   - Cons: <...>

2. <name>: <description>
   - Pros: <...>
   - Cons: <...>

Selected: <variant>
```

## Cookbook

<If: user can't decide>
<Then: ask about priorities to narrow down>

<If: all variants feel wrong>
<Then: go back and understand the problem better>

<If: user likes parts of different variants>
<Then: offer to hybridize>
