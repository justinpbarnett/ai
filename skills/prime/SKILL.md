---
name: prime
description: >
  Fast project orientation. Scans recent activity, identifies key files, and
  summarizes current state. Generates CLAUDE.md for projects that don't have one.
  Use on "prime", "get context", "orient yourself", "catch me up", or "what does
  this project do". Do NOT use when already primed this session.
---

# Prime

Fast orientation for any project. Two modes: if CLAUDE.md exists, surface what's live right now. If it doesn't, generate one from the codebase.

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

Also check: does `CLAUDE.md` or `.claude/CLAUDE.md` exist?

### 2a. CLAUDE.md exists -- surface what's live

CLAUDE.md is already loaded into context at session start. Don't re-read it. Instead, focus on what's changed since last session -- that's the value prime adds for established projects.

**Respect progressive disclosure.** If CLAUDE.md has a context index (a table pointing to files with "Read when" triggers), those files are on-demand. Don't read them during prime. Mention the index exists so future queries know where to look, but don't front-load context that isn't needed yet. The whole point of progressive disclosure is that context loads when a task demands it, not at session start.

Skip to step 3.

### 2b. No CLAUDE.md -- generate one

This is the core value of prime on unfamiliar codebases. Build a CLAUDE.md that gives Claude full architectural context.

**Detection (parallel):**

Scan project root for stack signals:

| File | Indicates |
|---|---|
| `go.mod` | Go (read for module name + deps) |
| `package.json` | Node/TS (read for name, scripts, deps, framework) |
| `pyproject.toml` / `requirements.txt` | Python (read for project name, deps, framework) |
| `Cargo.toml` | Rust (read for name, deps) |
| `Gemfile` | Ruby |

Also detect in parallel:
- **Task runner**: `justfile`, `Makefile`, `package.json` scripts
- **Package manager**: `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`, `package-lock.json`, `go.sum`, `uv.lock`
- **README.md**: read first 20 lines for project description
- **Top-level directory listing**: `ls -1` for architecture mapping

**Structure mapping:**

Glob for key patterns to understand how the code is organized:
- Entry points: `main.go`, `cmd/`, `src/index.*`, `src/main.*`, `app.py`, `manage.py`, `src/App.*`
- Routes/handlers: `**/routes/**`, `**/handlers/**`, `**/controllers/**`, `**/api/**`
- Models/data: `**/models/**`, `**/schema*`, `**/types/**`, `**/entities/**`
- Tests: `**/*_test.*`, `**/*.test.*`, `**/*.spec.*`, `**/test/**`, `**/tests/**`
- Config: `**/config/**`, `.env.example`, `docker-compose.*`

Don't read these files. Just note which patterns exist and where.

**Write CLAUDE.md:**

Generate a concise CLAUDE.md (under 80 lines) at the project root:

```md
# <Project Name>

<One-line description from README or package manifest.>

## Stack

- <Language, framework, key deps>
- <Database/ORM if detected>
- <Package manager>

## Key commands

<From task runner -- list actual commands with descriptions. If justfile, run `just --list`. If Makefile, read targets. If package.json, list scripts.>

## Architecture

- `<dir>/` -- <purpose, inferred from contents and naming>

## Testing

- <test framework> (`<test directory>`)

## Domain rules

- <Any conventions visible from the codebase: linting config, CI setup, etc.>
```

Tell the user you generated it and suggest they review/edit it. Do NOT run `/setup` -- that's a separate, heavier operation.

### 3. Active work

Check for active work signals (in parallel where possible):

- `specs/` directory -- list by modification time, read first 40 lines of most recent
- Feature branches -- if not on main, note the branch name and what's changed
- Uncommitted changes -- summarize what's staged/unstaged from git status
- Recent commit direction -- from the git log, identify the area of the codebase that's been active (e.g., "last 5 commits touch daily brief pipeline" or "recent work on auth module")

## Output

Concise. Adapt length to project size, but bias toward short. The goal is orientation, not a tour.

**With existing CLAUDE.md:**
```
[Project name]: [one-line description]
State: [branch, clean/dirty, recent direction from commits]
```

That's it for clean, on-main repos. Add more only if there's something to surface:
- Uncommitted changes? Summarize them.
- On a feature branch? Note what it's for.
- Recent spec or active initiative? Mention it.

Don't repeat anything CLAUDE.md already covers. Don't read on-demand context files. Just surface what's live.

**After generating CLAUDE.md:**
```
Generated CLAUDE.md for [project name].
Stack: [languages, frameworks, key deps]
State: [branch, uncommitted changes, recent direction]
Run: [key commands]

Review the generated CLAUDE.md -- edit anything that's wrong or missing.
```

## Cookbook

- Already primed this session? Just `git status` + `git log --oneline -5`. Skip everything else.
- Not a git repo? `ls -la` and read whatever docs exist. Still generate CLAUDE.md if missing.
- Monorepo? Top-level structure only. Note sub-packages in architecture section. Read sub-packages on demand.
- CLAUDE.md exists but looks stale/thin? Leave it alone. Suggest the user run `/setup update` if they want a refresh.
- Large project (50+ top-level files)? Focus on `src/`, `cmd/`, `app/`, `lib/` -- skip config noise in the architecture section.
- CLAUDE.md has a context index? Note it in your output (e.g., "6 context files available on-demand") so the user knows the system is there. Don't enumerate them.
