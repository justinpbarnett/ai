---
name: prime
description: >
  Fast project orientation. Scans recent activity, identifies key files, and
  summarizes current state. Use on "prime", "get context", "orient yourself",
  "catch me up", or "what does this project do". Do NOT use when already primed.
---

# Prime

Fast orientation for any project. CLAUDE.md already covers structure and rules. Prime adds: what's happening now, what's the stack, and where to look.

## Trigger

"prime", "get context", "orient yourself", "catch me up", "what does this project do"

## Process

### 1. Current state (parallel)

```bash
git log --oneline -10
```
```bash
git status
```
```bash
git diff main...HEAD --stat  # skip if on main
```

### 2. Read CLAUDE.md

Read `CLAUDE.md` or `.claude/CLAUDE.md` if it exists. This is the primary context source -- it has structure, conventions, and domain rules. If it covers the project well, skip step 3.

### 3. Identify the project (only if no CLAUDE.md)

Read the first file that exists: `README.md`, `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`. Just enough to know what the project is, what stack it uses, and how to run it.

### 4. Active work

If a `specs/` directory exists, list files by modification time. Read the first 40 lines of the most recent spec to understand current direction.

## Output

Concise. Adapt length to project size, but bias toward short.

```
[Project name]: [one-line description]
Stack: [languages, frameworks, key deps]
State: [branch, uncommitted changes, recent direction]
Run: [key commands -- build, test, dev server]
```

For projects with CLAUDE.md, skip anything it already covers. Just surface what's live (branch, recent commits, active spec).

## Cookbook

- Already primed this session? Just `git status` + `git log --oneline -5`. Skip everything else.
- Not a git repo? `ls -la` and read whatever docs exist.
- Monorepo? Top-level structure only. Read sub-packages on demand.
