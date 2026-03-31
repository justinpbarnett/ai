---
name: retro
description: >
  Weekly team retro. Per-person breakdowns, shipping streaks, test health trends. Works across multiple projects with "retro global".
  Triggers on: "retro", "weekly retro", "what shipped", "team summary", "how did we do"
---

# Retro

Run a weekly retrospective. Get per-person breakdowns, shipping stats, and growth opportunities.

## Variables

- `argument` -- Optional: project name or "global" for all projects

## Instructions

### Step 0: Determine Scope

If `argument` is "global" or not provided:
- Check multiple projects
- Aggregate stats across all

If specific project:
- Focus on that project only

### Step 1: Gather Stats

For each person/project:
- Commits this week
- Lines added/removed
- PRs merged
- Features shipped
- Tests added

### Step 2: Calculate Metrics

- Shipping velocity
- Test coverage trend
- Bug counts
- Review turnaround

### Step 3: Identify Patterns

- What's working well?
- What's slowing down?
- Blockers
- Recurring issues

### Step 4: Growth Opportunities

- Skills to develop
- Process improvements
- Tooling needs

## Output Format

```
Retro: <period>

Summary:
- Total commits: <N>
- Lines added: <N>
- Lines removed: <N>
- PRs merged: <N>

Per-Person:
| Person | Commits | Lines | PRs | Notes |
|--------|---------|-------|-----|-------|
| ... | ... | ... | ... | ... |

Shipping Streak: <N> days

Test Health:
- Tests added: <N>
- Coverage: <X>%

What's Working:
- <item>

What's Slowing:
- <item>

Action Items:
1. <action>
```

## Cookbook

<If: running on single project>
<Then: focus on project-specific patterns>

<If: running global>
<Then: aggregate across all projects>

<If: numbers are down>
<Then: investigate why - vacation, complexity, blockers?>

<If: patterns repeat>
<Then: add to action items for next retro>
