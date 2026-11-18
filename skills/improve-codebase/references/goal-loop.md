# Persistent goal loop

The finding ledger resumes without a Pi goal.
Inspect focused goal state using `get_goal` if available; retrieve the full objective and verification contract before associating a run.
If the goal is absent, unrelated, paused, or cannot be inspected, use the ordinary session workflow without creating, focusing, or resuming it.
Never change runtime allowances or enable Sisyphus to keep this loop alive.

## Explicit setup

Start Pi at the actual target worktree root.
When asked to prepare a goal, give the user an objective with actual absolute paths, explicit scope and authority, and the single-line `Verification contract:` used by pi-goal-x.
Use this structure, substituting real paths and commands before submission:

```text
Improve the first-party code under <absolute root>, scoped to <paths or whole worktree>, using <absolute SKILL.md>; preserve existing work and observable contracts, and make only authorized changes.
Use <absolute state path> for finding, review, and verification evidence; continue from the ledger after interruptions.
Reproduce defects end to end before changing behavior, keep refactors separate, and exercise <actual project checks and real CLI/API/UI flows>.
Verification contract: From <absolute root>, run <absolute Python executable> <absolute scanner script> complete --root <absolute root> <exact scope/state/threshold args> --format json and require exit 0 and complete=true; inspect report with the same arguments, actual source/diff, baseline and current required checks/flows/artifacts, zero candidates and strict debt, and both complete review passes; verify no missing capabilities, hidden suppression, or unsupported scope changes.
```

Submit the objective separately via `/goal <objective>` and require human confirmation with the independent completion auditor enabled.
Do not chain it with `/skill:improve-codebase` on the same line; only the first recognized command is promoted.
Use an explicitly authorized goal creation tool only when the user asks for creation; tool-created goals may remain idle pending `/goal-resume`.

## Checkpoint and finish

On a matching active goal, checkpoint the root, exact CLI arguments, absolute state and script paths, revision, snapshot, debt, coverage, blockers, next unit or finding, and the observed verification artifacts through the host's available task/evidence tools.
Keep goal files extension-owned; do not edit them manually.
Process the next safe unit, verify it, and repeat until the gate succeeds or the host/user stops the run.
On another session, check `/goal-status verbose` and wait for the user to explicitly `/goal-focus` or `/goal-resume` as needed; use `/goal-pause` to stop.
Pi must stay running for continuation, and exhausted allowances or interruption are partial results.

Request `update_goal({status: "complete"})` only after the scanner's `complete` returns zero and all goal-specific requirements are met.
Provide exact commands and local artifact paths; the independent auditor normally lacks project skills/extensions and must be able to inspect and verify from the goal contract alone.
A rejected audit feeds supported findings back into the ledger; it does not justify weakening the completion checks.
Keep local three-cycle stall detection distinct from the host's blocker lifecycle: only request a blocked goal after the same blocker recurs on three consecutive goal turns under the installed policy.
