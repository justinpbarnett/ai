---
name: careful
description: >
  Safety guardrails that warn before destructive commands. Say "be careful" to activate. Override any warning.
  Triggers on: "be careful", "careful", "warn me", "safety mode"
---

# Careful

Activate safety warnings for destructive commands without restricting edits.

## Instructions

### Step 0: Activate Careful Mode

Note the activation:
```
CAREFUL MODE: Active
Warnings enabled for destructive operations
```

### Step 1: Watch for Destructive Commands

For each of these commands, warn before executing:
- `rm -rf *` or `rm -rf .*` (recursive delete)
- `DROP TABLE` (database)
- `DELETE FROM` without WHERE (database)
- `git push --force` or `git push -f`
- `git reset --hard`
- `chmod -R 777`
- Any command that permanently destroys data

### Step 2: Warn and Wait

When a destructive command is detected:
1. State what the command will do
2. Explain the risk
3. Wait for confirmation
4. Execute only after user confirms

### Step 3: Document

After each blocked command:
- Note what was warned about
- Note whether it was executed or aborted

## Output Format

```
Careful Mode: Active

Watching for:
- Recursive deletes (rm -rf)
- Database destructive ops (DROP, DELETE without WHERE)
- Force pushes (git push -f)
- Hard resets (git reset --hard)
- Permission escalations (chmod 777)

To remove: Say "stop being careful" or "done being cautious"
```

## Cookbook

<If: the user confirms>
<Then: execute the command and note it was performed after warning>

<If: the user says "do it anyway" or overrides>
<Then: execute and document the override>

<If: the user says "stop being careful">
<Then: deactivate and confirm>
