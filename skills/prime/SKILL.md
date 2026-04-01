---
name: prime
description: >
  Quick project orientation using git tools. Surfaces real-time git status and 
  recent activity to supplement the existing AGENTS.md/CLAUDE.md context. Uses
  git_status, git_log, and git_branch tools for fast, deterministic results.
  Triggers: "prime", "get context", "catch me up", "what changed", "what's new".
---

# Prime

Fast real-time status check using git tools. Shows current branch, recent commits, and uncommitted changes. Supplements (doesn't replace) the project context files.

## When to Use

At the start of a session to see what's live since the context files were written:
- "prime", "catch me up", "what's new", "what changed"

## What It Does

1. Uses `git_branch` to show current branch
2. Uses `git_log` to show recent commits
3. Uses `git_status` to show uncommitted files
4. Notes if on a feature branch vs main
5. Checks for specs/ directory (lists recent specs if exists)

## Tools to Use

**Instead of bash commands, use these deterministic tools:**
- `git_branch` - Get current branch name
- `git_log` - Show recent commits (use count=5, oneline=true)
- `git_status` - Check for uncommitted changes

## Output

**Single line format (most cases):**
```
[branch-name]: [last commit message] | [+X/-Y uncommitted files]
```

**With uncommitted changes:**
```
[branch-name]: [last commit]
Uncommitted: [file1, file2, file3]
```

**On feature branch:**
```
feat/something: Add new feature | +3/-0 uncommitted
```

**With active spec:**
```
main: Latest commit message
Specs: specs/feat-user-auth.md (2h ago)
Uncommitted: 0
```

## Rules

- **Never read CLAUDE.md or AGENTS.md** - they're already loaded into context
- **Use tools, not bash** - git_status, git_log, git_branch for deterministic results
- **Keep it under 10 lines** - this is a quick status check
- **Skip if already primed this session** - just run git tools, skip full prime
- **Not a git repo?** - Just run `ls -la` and note what files exist

## Example Outputs

**Clean, on main:**
```
main: feat: add dark mode toggle
```

**Feature branch with work:**
```
feat/dashboard-v2: WIP: add chart components
Uncommitted: src/components/Chart.tsx, src/lib/data.ts
```

**With active spec:**
```
feat/auth: feat: implement JWT middleware
Spec: specs/feat-auth-flow.md (active)
Uncommitted: 0
```

## Cookbook

<If: user says "prime" and context already shows recent changes>
<Then: just use git_status and git_log tools. Skip full prime.>

<If: not a git repo>
<Then: run `ls -la` and report what exists. Very brief.>

<If: uncommitted changes are just lockfiles (package-lock, etc.)>
<Then: mention them but don't list individually.>
