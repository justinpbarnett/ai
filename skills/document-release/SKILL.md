---
name: document-release
description: >
  Update all project docs to match what was just shipped. Catches stale READMEs, ARCHITECTURE, CONTRIBUTING, CLAUDE.md. Runs automatically after /ship.
  Triggers on: "update docs", "document release", "doc this", "docs need updating"
---

# Document Release

Update all project documentation to reflect what was just shipped.

## Variables

- `argument` -- What was shipped (optional, defaults to recent commits)

## Instructions

### Step 0: Identify Changes

Get recent commits:
```
git log --oneline -10
```

Extract what changed.

### Step 1: Find Doc Files

Locate documentation files:
- README.md
- ARCHITECTURE.md
- CONTRIBUTING.md
- CLAUDE.md
- API docs
- Any *.md in docs/

### Step 2: Check for Drift

For each doc file:
- Read the content
- Check if it's stale vs. what was shipped
- Note what needs updating

### Step 3: Update Docs

For each file that needs updates:
- Make minimal changes to reflect shipping
- Keep existing structure
- Update only what's stale

### Step 4: Commit

Commit doc updates with descriptive message.

## Output Format

```
Document Release: <changes>

Doc Files Checked:
- README.md: <up to date|updated>
- ARCHITECTURE.md: <up to date|updated>
- CLAUDE.md: <up to date|updated>
- ...

Updates Made:
- <file>: <change summary>

Committed: <hash>
```

## Cookbook

<If: a doc file is stale>
<Then: update it, don't just note it>

<If: a doc file is missing>
<Then: consider creating it if critical>

<If: changes are large>
<Then: commit docs separately from code>

<If: docs are already current>
<Then: confirm and exit quickly>
