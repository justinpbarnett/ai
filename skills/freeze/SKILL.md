---
name: freeze
description: >
  Lock file edits to one directory. Prevents accidental changes outside scope while debugging. Use when investigating or making focused changes.
  Triggers on: "freeze", "lock edits", "scope to", "stay in this area"
---

# Freeze

Restrict file edits to a specific directory to prevent accidental changes outside your focus area.

## Variables

- `argument` -- Directory to restrict edits to (defaults to current working directory if not specified)

## Instructions

### Step 0: Determine Scope

If `argument` is provided, use that as the frozen directory.
Otherwise, use the current working directory.

### Step 1: Set the Freeze Boundary

Store the frozen directory path in a note/file for tracking:
```
FROZEN SCOPE: <directory path>
```

### Step 2: Warn on Out-of-Scope Edits

Before any write/edit operation:
- Check if the target path is within the frozen directory
- If outside, warn the user and ask for confirmation

### Step 3: Continue Work

Proceed with the requested task within the frozen scope.

### Step 4: Document

At the end, summarize:
- What was changed within scope
- Any files that were blocked from editing

## Output Format

```
Freeze Active: <directory>

Scope: All edits restricted to this directory and subdirectories.

To remove: Run /unfreeze
```

## Cookbook

<If: the user needs to edit outside the frozen scope>
<Then: ask them to run /unfreeze first, or confirm they want to override>

<If: a write operation is attempted outside scope>
<Then: show what was blocked and ask for explicit override>
