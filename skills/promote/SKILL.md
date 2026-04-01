# Promote (Multi-Agent with Tools)

Converts git worktrees to regular branches using parallel validation agents and deterministic tools. Multiple agents verify: worktree state, PR status, test readiness, and orchestrator sync before promoting. Uses git tools for precise git operations.

## Trigger

"promote", "promote <identifier>", "ready to test", "convert worktree"

## Input

One of:
- A branch name or identifier (e.g., `feat/PTP-15978`, `PTP-15978`, `my-feature`)
- A worktree path
- If nothing provided, list active worktrees and ask which to promote

## Process

### Step 1: Discover Worktrees

List all worktrees using bash:
```bash
git worktree list
```

Or use `git_status` tool if checking a specific worktree.

For multi-repo projects, scan all repos.

### Step 2: Launch Parallel Validation Agents

For each worktree to promote, spawn 3-4 agents in parallel:

```
@worktree-validator
Validate worktree state:
- Use git_status tool to check for uncommitted changes
- Use git_diff to confirm no merge conflicts
- Verify all tests pass (if test suite exists)
- Check for required files (tests, docs)

Tools: git_status, git_diff
Report: is_ready, blockers_list, uncommitted_changes
```

```
@pr-status-checker
Check PR status and readiness:
- Find associated PRs via gh cli
- Check if PR is draft
- Verify CI checks are passing
- Confirm reviews if required

Report: pr_url, is_draft, ci_status, ready_for_review
```

```
@orchestrator-sync-agent
Sync with orchestrator state if applicable:
- Check passion-state.json for ticket status
- Check embers-tasks.json for task status  
- Verify orchestrator temp files exist
- Prepare state update

Report: orchestrator_found, current_status, can_promote
```

```
@promotion-planner
Plan the promotion steps:
- Determine commit order if uncommitted changes exist
- Identify any dependent worktrees that should promote together
- Plan cleanup steps
- Estimate time required

Report: promotion_steps, estimated_duration, dependencies
```

### Step 3: Review Validation Results

Combine all agent reports:

**If any agent reports blockers:**
- List all blockers
- Suggest fixes
- Ask user to resolve before promoting

**If all agents approve:**
- Proceed with promotion

### Step 4: Execute Promotion

```bash
# Commit uncommitted changes if any
# Or use git_add and git_commit tools:
git_add({ files: [] })  # stage all
git_commit({ message: "wip: uncommitted changes before promote", type: "chore" })

# Remove worktree (keeps branch and commits)
git worktree remove <worktree_path>

# Checkout branch in main repo using git_createBranch or bash
git checkout <branch_name>
```

### Step 5: Mark PR Ready

If draft PRs exist:
```bash
gh pr ready <PR_NUMBER>
```

### Step 6: Update Orchestrator State

If orchestrator-sync-agent found state files:
```bash
# Update passion-state.json or embers-tasks.json
# Set status to "promoted"
```

### Step 7: Cleanup and Summary

Remove temp files:
```bash
rm -f /tmp/passion-task-<KEY>.txt /tmp/passion-run-<KEY>.sh
```

**Report to user:**
```
Promoted: {branch_name}

Validation Results:
- Worktree State: {ready/not ready} (@worktree-validator)
- PR Status: {url} (@pr-status-checker)
- Orchestrator: {synced/not applicable} (@orchestrator-sync-agent)

Actions Taken:
✓ Committed uncommitted changes (if any)
✓ Removed worktree
✓ Checked out branch in main repo
✓ Marked PR ready for review (if was draft)
✓ Updated orchestrator state

Next Steps:
1. Smoke test the feature
2. Review and approve PR
3. Merge when ready
```

## Cookbook

<If: worktree-validator finds failing tests>
<Then: report as blocker; suggest fixing tests before promoting.>

<If: pr-status-checker finds failing CI>
<Then: warn user but don't block; they may want to fix CI first.>

<If: orchestrator-sync-agent finds mismatched state>
<Then: log warning but proceed; state will be updated during promotion.>

<If: multiple worktrees for same feature>
<Then: promote them all together; agents should validate each.>

<If: --worktree flag used but no worktree exists>
<Then: just checkout the branch if it exists on remote.>

## Notes

- Worktree state validation prevents promoting broken code
- PR status checking ensures proper GitHub workflow
- Orchestrator sync keeps build automation up to date
- Parallel validation agents complete in ~10-15 seconds vs 30-60 sequential
