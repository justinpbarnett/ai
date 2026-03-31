---
name: guard
description: >
  Maximum safety mode: combines /careful (warns on destructive commands) + /freeze (locks edits to one directory). Use for production work or risky operations.
  Triggers on: "guard", "max safety", "production mode", "be extra careful"
---

# Guard

Activate maximum safety: combines /careful warnings with /freeze scope locking.

## Variables

- `argument` -- Directory to restrict edits to (optional, defaults to current working directory)

## Instructions

### Step 0: Determine Scope

If `argument` is provided, use that as the guarded directory.
Otherwise, use the current working directory.

### Step 1: Activate Careful Mode

Set up warnings for destructive commands:
- rm -rf
- DROP TABLE
- force push
- git reset --hard
- Any command that permanently destroys data

For each, prompt for confirmation before execution.

### Step 2: Activate Freeze Mode

Store the guarded directory:
```
GUARDED SCOPE: <directory>
All edits restricted. Destructive commands require confirmation.
```

### Step 3: Proceed with Task

Execute the requested work with full safety measures in place.

## Output Format

```
Guard Active: Maximum Safety Mode

Careful: Destructive commands require confirmation
Freeze: Edits restricted to <directory>

To remove: Run /unfreeze
```

## Cookbook

<If: user wants to override>
<Then: warn about risks, then proceed if confirmed>

<If: multiple safety layers are too much>
<Then: suggest /careful or /freeze individually>
