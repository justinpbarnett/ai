---
name: make
description: >
  Standard feature harness. Research → generate → evaluate → proof → security →
  simplify → commit → PR. Creates a branch and opens a PR by default.
  Use for new features, moderate changes, anything that warrants its own PR.
  Triggers on: "make", "add this", "implement this feature", "create a new",
  "add support for", "add a feature".
  Use /fix for small targeted changes. Use /build for complex multi-sprint work.

  Flags:
    --current   stay on current branch (no new branch created)
    --worktree  create an isolated git worktree
    --no-pr     commit only, skip PR
---

# Make

Standard feature harness. Single sprint: research → generate → evaluate → proof → security → simplify. Branches and PRs by default.

## Variables

- `argument` -- spec file path or inline feature description

## Instructions

### Step 0: Parse

If `argument` is a `.md` file path, read it. Otherwise treat as inline description. Extract flags.

State intent before starting:
```
Make: <feature summary>
```

### Step 1: Git setup

**Default:** derive a branch name from the spec (e.g., `feat/dark-mode-toggle`). Invoke `/branch`.

**`--current`:** stay on current branch.

**`--worktree`:** derive a branch name, then:
```
git worktree add /tmp/<branch-name> -b <branch-name>
```
Pass the worktree path to all subsequent agents.

### Step 2: Research

Invoke the `research` agent with the spec and working directory. Returns a brief: relevant files, patterns, conventions, and anything the generator needs to match the project's style.

### Step 3: Generate

Invoke the `generator` agent with:
- The full spec
- The research brief
- "Do not commit, the harness handles this"

The generator declares its contract (scope + success criteria) before coding, then implements.

### Step 4: Evaluate

Invoke the `evaluator` agent with:
- The original spec
- The generator's declared contract and output summary
- Whether Playwright MCP is available (check your tool list for `mcp__plugin_playwright` tools; if present, tell the evaluator)

Single pass, no loop. If FAIL, stop and report. Don't run proof, security, or simplify on broken output.

### Step 5: Proof

Test the feature the way a user would. Read `references/proof.md` for the full methodology (project type table, capture instructions, review criteria).

The evaluator checks code against the contract. Proof checks the running result against the user's original spec. For multi-step features, capture evidence at each step.

If proof fails, stop and report. Don't proceed to security or commit.

### Step 6: Security

Invoke the `security` agent on the diff. If critical issues are found:
- Invoke the `generator` once more with only those issues
- Re-run the `evaluator` on the security fixes

Non-critical findings are noted in the report but don't block.

### Step 7: Simplify

Invoke `/simplify` on the changed files.

### Step 8: Git result

**Default:** invoke `commit-commands:commit-push-pr`. Include proof evidence in the PR body (see `references/proof.md` for format).

**`--no-pr`:** invoke `commit-commands:commit` only.

**`--worktree`:** after PR is open, clean up: `git worktree remove /tmp/<branch-name>`

## Output

```
Make: <feature name>
Branch: <name>

[research]  ✓
[generate]  ✓ <files changed>
[evaluate]  ✓ / ✗ <result>
[proof]     ✓ <what was tested>  (or ✗ <what didn't match>)
[security]  ✓ / ⚠ <N findings>
[simplify]  ✓

PR: <url>   (or Committed: <hash>)
```

## Cookbook

<If: evaluate returns FAIL>
<Then: stop. Report the failing criteria. The user should fix the spec or switch to /build for iterative refinement.>

<If: spec is too large to implement in one session>
<Then: stop at Step 3 and tell the user. Suggest /build with the same spec.>

<If: security finds a critical issue the generator can't fix without touching unrelated code>
<Then: note it as a blocker, open the PR as a draft, and flag for manual review.>

<If: --current and --no-pr are both set>
<Then: work in place, commit only. Useful for committing a feature to an existing branch mid-session.>
