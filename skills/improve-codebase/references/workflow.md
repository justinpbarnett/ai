# Review and transformation

Read the bundled [Fowler smell guide](smell-guide.md) before discovery and use all 24 smells as investigation lenses.
If the guide is missing, report the missing capability rather than claiming Fowler coverage.

## Three independent questions

- **Smells and standards:** Apply every relevant Fowler lens, the project's real standards, and checks for shared knowledge, unclear naming and types, error handling, and state ownership.
- **Architecture:** Inspect responsibilities, callers, dependency direction, cycles, complexity hidden behind interfaces, forwarding layers, cohesion, and what has to change together.
- **Contracts:** Compare implementation and callers with recorded behavior, discovered requirements, side effects, persistence, errors, ordering, lifecycle, and performance guarantees.

A passing conventions review does not substitute for a contract review.
Investigate every assigned file and relationship, including out-of-scope callers when necessary for context.
For `unknown` input, inspect representative content to classify it safely and record its disposition; if it is code, review it semantically.
Include relevant additional inputs in the receipt; if wiring is dynamic or ambiguous, read the corresponding project partition rather than relying on an import graph.
If actual contracts or coverage cannot be determined, do not fabricate a clean receipt; split the packet or report what remains pending.

## Deepening and safe destinations

Use the deletion test: if removing the module scatters decisions across its callers, it is hiding real complexity; if removal deletes only indirection, consider inlining it.
Prefer putting decisions that change together behind a small, useful interface and placing the code where maintainers naturally look for it.
For substantial design work, compare at least two concrete destinations and check real users and shared state.
Consolidation can be better than decomposition; introducing an interface for hypothetical variation is not an improvement.
A length, nesting, or duplicate alert is a question, not an instruction to split, abstract, or shorten.

For each actionable finding, cite the actual friction, affected contracts, simplest named transformation, and verification path.
Reproduce a bug through the real CLI, API, or UI before fixing it; separate behavior changes from refactors.
Read callers before moving or renaming code; preserve exported names, data formats, execution order, mutation, resource cleanup, and async behavior.
Keep batches runnable, preserve user changes and existing assertions, and reverse only your own transformation if verification fails.
Use a small internal compatibility bridge where necessary and verify mechanically necessary changes beyond the requested scope without expanding substantive edits there.
Use existing checks and direct behavior by default; add automated suites, ADRs, or specs only when required.
Run the repository's complete documented gate and exercise actual behavior, not only builds or lint.
For UI flows use Claude in Chrome when available; otherwise record what was blocked rather than inferring pixel or interaction equivalence.

## Delegate without losing evidence

Use fresh read-only subagents for bounded packets when the host supports them.
Assign two to four workers per wave with a distinct axis, files and cross-partition relationships, relevant rules and contracts, and exact receipt inputs.
For confirmation give the fresh reviewer no score targets or earlier verdicts.
Have reviewers return compact findings, source-linked verdicts, exact coverage, and blockers; keep full logs local.
The coordinator reconciles overlaps and contradictions, imports completed packets, and requeues stale or incomplete work.
A narrative summary is not a receipt.

Delegate edits only after shared contracts, prerequisites, and baselines are known.
Give workers exclusive file ownership or isolated worktrees, a specific finding, and focused checks; shared callers, migrations, and coupled interfaces stay sequential.
Workers never write to the shared ledger or goal, and return diffs, verification observations, and blockers.
The coordinator reviews each diff, integrates in dependency order, reruns combined checks and real flows, and records resolutions on the integrated snapshot.
Without subagents, work the same bounded packets sequentially and disclose that confirmation was not independent.
Do not launch nested agent CLIs to manufacture delegation.

## Convergence

Use the queue for safe priority order, not as a quota; a low-severity confirmed issue still matters.
Mark a finding pending before rescan, then cite fresh source/caller review and behavioral evidence to resolve it.
Preserve justified dismissals unless the evidence they rely on changes.
Keep accepted risk and blocked findings visible and in debt.
Report partial with concrete reasons when capabilities, scope coverage, verification, permissions, or repeated blockers prevent clean completion.
