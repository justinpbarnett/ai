---
name: unfreeze
description: >
  Remove the /freeze boundary, allowing edits to all files again.
  Triggers on: "unfreeze", "unlock", "stop freezing", "done with freeze"
---

# Unfreeze

Remove the freeze boundary and return to normal editing.

## Instructions

### Step 0: Check Status

If no freeze is active, note that.

### Step 1: Remove Boundary

Clear the frozen scope:
```
FROZEN SCOPE: None
```

### Step 2: Confirm

```
Freeze Removed

Editing is no longer restricted.
```

## Cookbook

<If: freeze was never activated>
<Then: confirm and exit>

<If: there were blocked edits during freeze>
<Then: summarize what was blocked>
