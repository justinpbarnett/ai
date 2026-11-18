---
name: improve-codebase
description: Find, prioritize, and verify codebase improvements with a resumable scan and review loop.
argument-hint: "[paths or concern; audit only; prepare a goal]"
disable-model-invocation: true
---

# Improve codebase

Drive the workflow with `scripts/improve_codebase.py` relative to this skill's directory, not the project directory.
The CLI tracks evidence and computes progress; you judge findings, change code when authorized, and verify behavior.

1. **Scope.** Read repo instructions and status; resolve the requested area to root-relative paths, or use the whole first-party worktree.
   Preserve existing work and inspect callers outside a narrow scope without broadening edits.
   Audit-only means no application edits; the scanner may write ignored local state.
   For an explicit goal request or a potentially matching focused goal, read [goal-loop.md](references/goal-loop.md) before attaching any work.
2. **Scan.** Read [cli.md](references/cli.md) for setup, commands, state, and evidence inputs.
   Run `doctor` and `scan`, then use `next` and `review prepare` instead of rediscovering the scope from chat history.
   Inspect incomplete capabilities and exclusions using [languages.md](references/languages.md); restore supported coverage or report partial.
   Continue from valid evidence on resume; use `--full` only for a requested or justified fresh investigation.
3. **Baseline and review.** Read [workflow.md](references/workflow.md) for the three review axes, Fowler reference, architecture judgment, and delegation rules.
   Declare the verification manifest from actual project commands and interfaces and exercise representative behavior before editing.
   Review the queued packets, import exact coverage, and triage scanner candidates by observed maintenance impact, not metrics alone.
   **Ready to edit:** discovery coverage and relevant real behavior are accounted for, and the next finding is actionable with a safe verification path.
   In audit-only mode, stop before edits and report findings, debt, reused coverage, gaps, and next actions.
4. **Transform and verify.** Pick dependency-ready findings and work in small coherent batches; use parallel workers only for independent changes.
   Mark work pending verification, rescan, and confirm through current checks, real user flows, and source/caller review before closing findings.
   Separate end-to-end reproduced bugs from behavior-preserving transformations.
   Continue independent safe work when another finding is blocked; do not fix by disabling checks or moving code outside scope.
5. **Converge.** Repeat discovery for affected inputs, then run the distinct confirmation review for units still due.
   After a genuine fix/review cycle use `scan --checkpoint`; after three no-progress cycles, report the blocker rather than oscillating.
   Re-run the documented full gate and affected product behavior; record the final diff review.
   **Done:** `complete` returns zero for the current scope and source, or the report explicitly says partial and names all unmet gates.

Report verified improvements, score and coverage, real before/after results, diff statistics including untracked files, and any unresolved findings or unavailable checks.
Report sequential confirmation if independent reviewers were unavailable.
Leave commits, pushes, pull requests, deployments, and goal lifecycle controls to the user or explicitly authorized workflow.
