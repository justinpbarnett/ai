# CLAUDE.md Template

Use this structure when generating a project's CLAUDE.md. Adapt sections to the project -- omit sections that don't apply, add project-specific sections as needed.

## Template

```md
# <Project Name>

<One-line description of what the project does.>

## Stack

- <Language version, framework, key libraries>
- <ORM + database>
- <Deployment target>
- <Package manager>

## Key commands

```bash
<task_runner> <command>    # <description>
<task_runner> <command>    # <description>
<task_runner> <command>    # <description>
```

## Architecture

- `<dir>/` -- <purpose, inferred from actual contents>
- `<dir>/` -- <purpose>
- `<dir>/` -- <purpose>

### Key patterns

- Entry points: <where the app starts -- main.go, src/index.ts, etc.>
- Routes/API: <where HTTP handlers or API definitions live>
- Data layer: <models, schema, database access>
- Config: <where configuration lives, env var patterns>

## Testing

- <test framework> (`<test directory>`)
- <e2e framework if applicable>
- <how to run: `just test`, `make test`, `pnpm test`, etc.>

## Domain rules

- <project-specific conventions, naming, tone, constraints>
```

## How to generate

Build the CLAUDE.md from actual codebase analysis, not guesswork:

1. **Project description**: read README.md (first 30 lines) or package manifest (name/description fields)
2. **Stack**: detected from manifest files (go.mod, package.json, pyproject.toml, etc.)
3. **Commands**: from the task runner directly. Run `just --list` for justfile, read Makefile targets, read package.json scripts. Copy-pasteable, not paraphrased.
4. **Architecture**: `ls` the root, then glob for key patterns (routes, models, tests, config). Infer directory purposes from what's actually inside them, not just naming.
5. **Key patterns**: glob results from entry points, routes/handlers, models/schema, tests, config. Only include patterns that exist.
6. **Domain rules**: visible from linting config, CI setup, existing conventions. Ask the user if unclear.

## Notes

- Keep it under 100 lines. CLAUDE.md is loaded into every conversation -- brevity matters.
- Commands should be copy-pasteable. Use the actual task runner (just, make, pnpm, etc.).
- Architecture section should cover top-level directories only. Don't go deeper than 2 levels.
- Key patterns section gives Claude the "where to look" context that a knowledge graph would provide. Only include patterns the project actually uses.
- Domain Rules captures things that aren't obvious from the code: business logic constraints, naming conventions, tone guidelines, external API quirks.
- If the project has an ADW/automation system, add a brief section for it.
- If the project has integrations with external services, list them.
