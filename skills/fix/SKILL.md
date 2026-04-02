---
name: fix
description: >
  Small targeted change harness. Research → generate → evaluate → proof → commit.
  Stays on current branch by default. No PR unless asked.
  Use for bug fixes, typo corrections, small config changes, doc updates,
  minor refactors, anything scoped to one area and one commit.
  Triggers on: "fix this", "patch this", "correct this", "quick change",
  "update just this one thing", "tweak".
  Use /make for new features. Use /build for multi-area or unattended work.

  Flags:
    --branch    create a new branch before working
    --worktree  create an isolated git worktree
    --pr        commit and open a PR (default: commit only)
    --no-commit leave changes unstaged, no commit
---

# Fix

Small targeted change. Four agents in sequence, no loops.

## Variables

- `argument` -- description of the change, or path to a spec file

## Instructions

### Step 0: Parse

If `argument` is a `.md` file path, read it. Extract flags from the argument string.

### Step 1: Git setup

**Default (no flag):** stay on current branch.

**`--branch`:** derive a short branch name (e.g., `fix/null-check-login`). Invoke `/branch`.

**`--worktree`:** derive a branch name, then:
```
git worktree add /tmp/<branch-name> -b <branch-name>
```
Pass the worktree path to all subsequent agents.

### Step 2: Research

Invoke the `research` agent with the change description and working directory. Returns a brief: what to change, where, and why.

### Step 3: Generate

Invoke the `generator` agent with:
- The original change description or spec
- The research brief
- "Do not commit, the harness handles this"

The generator declares its contract (scope + success criteria) before coding, then implements.

### Step 4: Evaluate

Invoke the `evaluator` agent with:
- The original change description or spec
- The generator's declared contract and output summary
- Whether Playwright MCP is available (check your tool list for `mcp__plugin_playwright` tools; if present, tell the evaluator)

Single pass, no retry loop. If FAIL, stop and report. Don't proceed to proof or commit.

### Step 5: Proof

Test the change the way a user would. This is not a code review; it's running the actual result and verifying it works. Read `references/proof.md` for the full methodology.

The key distinction from evaluation: the evaluator checks code against the contract, proof checks the running result against the user's original intent.

If proof fails, stop and report what's wrong. Don't commit.

### Step 6: Git result

**Default:** invoke `commit-commands:commit`.

**`--pr`:** invoke `commit-commands:commit-push-pr`. Include proof evidence in the PR body (see `references/proof.md` for format).

**`--no-commit`:** skip. Report what changed.

**`--worktree`:** after git result, clean up: `git worktree remove /tmp/<branch-name>`

## Output

```
Fix: <description>
Branch: <name or current>

[research]  ✓ <one-line summary>
[generate]  ✓ <files changed>
[evaluate]  ✓ pass  (or ✗ <failing criteria>)
[proof]     ✓ <what was tested>  (or ✗ <what didn't match>)

Committed: <hash> <message>   (or PR: <url>)
```

## Cookbook

<If: evaluator fails>
<Then: stop and report. Don't commit partial work. The user can refine the description or switch to /make if scope is larger than expected.>

<If: evaluator fails and --worktree is set>
<Then: clean up the worktree before stopping. Don't leave orphaned worktrees.>

<If: change is purely mechanical (rename, format, delete dead code)>
<Then: research is still useful to find all affected locations. Don't skip it.>

<If: change touches authentication, encryption, input validation, or secrets handling>
<Then: consider running the `security` agent after evaluate. /fix has no built-in security step, but these areas warrant it.>

<If: --branch and --pr are both set>
<Then: create the branch, do the work, commit and open a PR from that branch.>
