---
name: build
description: >
  Complex multi-sprint harness. Planner expands the spec into sprint contracts,
  then loops generator→evaluator per sprint (up to 3 cycles each) until all
  criteria pass. Ends with proof, security scan, simplify, and PR. Creates a
  branch by default. Use for large features, multi-area work, or anything too
  complex for a single implementation session.
  Triggers on: "build this", "use the harness", "multi-sprint", "complex feature",
  "big change", "planner generator evaluator".
  Use /fix for small targeted changes. Use /make for standard single-session features.

  Flags:
    --current   stay on current branch
    --worktree  create an isolated git worktree (best for unattended builds)
    --no-pr     commit only, skip PR
---

# Build

Complex feature harness. Planner defines sprint contracts, then generator→evaluator loop per sprint, then proof of completion. Branches and PRs by default.

## Variables

- `argument` -- spec file path or inline description

## Instructions

### Step 0: Parse

If `argument` is a `.md` file path, read it. Otherwise treat as inline description. Extract flags.

State intent before starting:
```
Build: <spec summary>
```

### Step 1: Git setup

**Default:** derive a branch name from the spec (e.g., `feat/auth-system`). Invoke `/branch`.

**`--current`:** stay on current branch.

**`--worktree`:** derive a branch name, then:
```
git worktree add /tmp/<branch-name> -b <branch-name>
```
Pass the worktree path to all subsequent agents. Best option for unattended builds.

### Step 2: Plan

Invoke the `planner` agent with the spec and working directory. Returns: project type, stack, build commands, and numbered sprints each with scope + success criteria (the sprint contract).

Print the full plan. If it has more than 6 sprints, confirm scope with the user before continuing.

### Step 3: Sprint loop

For each sprint, run up to 3 generator→evaluator cycles:

#### 3a. Generate

Invoke the `generator` agent with:
- This sprint's contract (goal, scope, success criteria)
- The full plan (context)
- All evaluator feedback from previous cycles of this sprint, accumulated

#### 3b. Evaluate

Invoke the `evaluator` agent with:
- The original spec (source of truth for intent)
- This sprint's contract from the planner
- Generator output summary
- Whether Playwright MCP is available (check your tool list for `mcp__plugin_playwright` tools; if present, tell the evaluator)

#### 3c. Verdict

- **PASS:** print `[sprint N/total] ✓ <name>` and advance
- **FAIL:** print failing criteria and feedback, return to 3a (up to 3 cycles)
- **3 cycles exhausted:** stop the build. Report which criteria are failing. Don't continue to later sprints with a broken foundation.

#### 3d. Commit gate

After each sprint passes, check the generator's output summary for a commit hash. If none, retry from 3a with: "your previous output did not include a commit. Commit your work and return the hash."

### Step 4: Proof

After all sprints pass, test the full integrated build the way a user would. Read `references/proof.md` for the full methodology (project type table, capture instructions, review criteria).

This is an end-to-end check of the complete feature, not per-sprint. Compare against the original spec (not sprint contracts). The sprints should work together as an integrated whole.

If proof fails, stop and report. Don't proceed to security or commit.

### Step 5: Security

Invoke the `security` agent on the full diff. If critical issues are found:
- Invoke the `generator` with only those issues
- Re-run the `evaluator` on the changed files
- One fix cycle only. If still critical, note in report and continue.

### Step 6: Simplify

Invoke `/simplify` on all changed files.

### Step 7: Git result

**Default:** invoke `commit-commands:commit-push-pr`. Include proof evidence in the PR body (see `references/proof.md` for format).

**`--no-pr`:** invoke `commit-commands:commit` only.

**`--worktree`:** after PR is open, clean up: `git worktree remove /tmp/<branch-name>`

## Output

```
Build: <spec name>
Branch: <name>

Plan: <N> sprints

[sprint 1/N] ✓ <name>  (1 cycle)
[sprint 2/N] ✓ <name>  (3 cycles)
...

[proof]     ✓ <what was tested>  (or ✗ <what didn't match>)
[security]  ✓ / ⚠ <N findings>
[simplify]  ✓

PR: <url>   (or Committed: <hash>)
```

## Cookbook

<If: evaluator fails 3 cycles on a sprint>
<Then: stop. Report the failing criteria, the last generator output, and what the evaluator said. The sprint contract may be too large, the spec ambiguous, or there's a codebase blocker. Don't carry a broken sprint forward.>

<If: spec is small enough for one sprint>
<Then: planner returns a single sprint. The loop runs once. Still valuable for the evaluator refinement loop.>

<If: project is a web app with Playwright available>
<Then: tell the evaluator it can use Playwright tools in every evaluator invocation.>

<If: a later sprint depends on an earlier one that failed>
<Then: stop at the failure. Later sprints that build on broken foundations will fail too.>

<If: evaluator notes issues outside the sprint contract>
<Then: those go in "Other observations" and don't affect the verdict. The contract is the only pass/fail gate. Accumulate and surface in the final report.>

<If: --worktree is set and a sprint fails after 3 cycles>
<Then: clean up the worktree before exiting. Don't leave orphaned worktrees.>

<If: spec has vague success criteria after planning>
<Then: surface the planner's criteria to the user before generating sprint 1. Ambiguous criteria are the most common cause of evaluator loops that never converge.>
