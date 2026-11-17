---
name: refactor
description: Find and resolve every actionable refactoring opportunity in a specified area, or the whole codebase, using Martin Fowler's Refactoring principles.
argument-hint: "[paths, module, subsystem, or concern; defaults to the whole codebase]"
disable-model-invocation: true
---

# Refactor

Improve the design of existing code through small, behavior-preserving transformations, following Martin Fowler's *Refactoring: Improving the Design of Existing Code*, second edition.
Implement the improvements, not just an audit or a plan, unless the user explicitly requests discovery only.
Work through every actionable opportunity in scope, including minor ones, and repeat discovery after changes until a complete pass finds no new actionable opportunities.

## 1. Establish scope and safeguards

Read the repository's agent instructions, relevant documentation, and working-tree status before editing.
Preserve staged, unstaged, and untracked user work, and distinguish it from your own changes throughout.

Interpret supplied paths, a module, a subsystem, or a concern as the requested scope and resolve it to concrete files.
When no area is supplied, use the entire repository, including its first-party packages, rather than just the current subdirectory or recently changed files.
Outside Git, use the identifiable project or workspace root; ask if there is no unambiguous codebase.
Inspect callers and dependencies outside a narrow scope to understand contracts, but limit edits there to mechanically necessary integration changes and disclose them.
Ask before expanding the substantive refactor beyond the requested area.

Inventory all first-party, hand-maintained code in scope, including relevant scripts, configuration, and existing tests.
Exclude third-party and vendored code, generated files, build outputs, caches, binaries, and secrets, and record these exclusions.
Keep `CHANGELOG.md` and auto-generated files out of manual edits; use the documented generator if an output must be refreshed.
Discover the actual build, lint, type-check, and existing test commands from repository documentation and configuration.

**Done when:** the scope, exclusions, existing user changes, and available verification commands are known.

## 2. Establish the behavioral baseline

Identify the observable contracts affected by the area: public APIs, CLI arguments and exit codes, UI interactions, data formats, error behavior, side effects, ordering, persistence, and relevant performance guarantees.
Treat current quirks as behavior to preserve unless a separate bugfix is justified and authorized.
Inspect entry points, callers, existing checks, and recent history where they clarify intent.

Run the relevant existing checks before changing code.
Exercise representative normal, edge, and error paths through the running product, real CLI, or real API, using safe local or sandbox data.
Record concrete inputs and observations for comparison after refactoring.
For a web UI, use Claude in Chrome when available and inspect both the rendered result and interactions; report unavailable access instead of inventing evidence.

Use existing suites and direct verification by default.
Create automated tests, ADRs, or spec files only when the user or repository instructions explicitly require them.
Existing tests may need mechanical updates for internal moves or renames; preserve their behavioral assertions rather than weakening them to accept a regression.

Handle defects, failing checks, and flakiness as separate bugfix work under the applicable instructions, reproducing bugs end to end before fixing them.
Keep any behavior-changing fixes distinguishable from the refactoring and re-establish the baseline afterward.
If tools, permissions, or dependencies block verification, record the limitation and restrict changes to transformations whose safety can still be established.

**Done when:** the relevant contracts and baseline observations are recorded, and each failed or unavailable check has an explicit disposition.

## 3. Discover opportunities exhaustively

Read [the smell guide](references/smell-guide.md) before discovery.
Use all 24 smells as a review checklist, adapting the transformations to the language and repository rather than imposing an object-oriented design.

Review every inventoried source file and the relationships between modules.
Use searches, reference tools, existing analyzers, and history to locate candidates, then read the actual implementations and callers before deciding.
Search results, file-size rankings, and samples are discovery aids, not evidence that the whole scope was reviewed.
If read-only review is delegated, partition the inventory explicitly and reconcile every partition's findings and coverage before claiming completion.

Maintain a coverage checklist and a finding ledger in working notes, not a permanent repository document.
For each candidate, record its location, smell, concrete maintenance problem, proposed named refactoring, affected contracts, verification approach, and status.
A candidate is actionable when it has a demonstrable design problem, a simpler behavior-preserving destination, and a credible way to verify the transformation.
Dismiss a false positive with a concrete reason; a smell is a prompt to investigate, not an automatic mandate to change code.

Prioritize enabling refactorings, widespread coupling, duplication of knowledge, and hard-to-follow logic, then work through the remaining findings.
Priority determines order, not which valid findings get fixed.
Development effort, low severity, or an arbitrary change-count target is not a reason to leave a safe, actionable improvement unresolved.

**Done when:** every inventoried file has been reviewed, cross-module smells have been considered, and every candidate is queued, justified as non-actionable, or explicitly blocked.

## 4. Transform in small, verified steps

For each queued finding:

1. Re-read the affected code and callers, choose a catalog refactoring, and state what becomes easier to understand or change.
   Prefer the simplest concrete design over speculative flexibility, pattern installation, or cosmetic churn.
2. Identify dependencies, side effects, evaluation order, mutation, async behavior, resource cleanup, and compatibility constraints before moving code.
   Preserve externally consumed names and formats; use an internal compatibility bridge when necessary.
3. Apply the smallest coherent transformation, using trusted language-aware rename or move tools where available.
   Update affected internal callers together, and keep the code runnable after each step.
   Larger improvements should emerge from a sequence of these steps rather than a rewrite.
4. Run the most focused relevant checks immediately and compare the affected real behavior with the baseline.
   On a regression, repair or reverse only your last transformation before continuing, preserving unrelated user changes.
   A build or type-check alone is not proof that runtime behavior is unchanged.
5. Inspect the diff for accidental contract changes and unnecessary complexity, mark the finding resolved with verification evidence, and add newly exposed opportunities to the ledger.

Keep feature work, dependency upgrades, broad formatting, and speculative performance changes outside the refactor.
Prefer established repository idioms and existing dependencies.
Remove an abstraction when inlining is clearer; introduce one when it captures a real responsibility or shared knowledge.
Resolve a blocked finding when a safe path becomes available, and continue independent work while genuine blockers remain.

**Done when:** every queued finding has been resolved and verified, or has a specific blocker that cannot be removed safely with the available authority and evidence.

## 5. Rescan, verify, and finish

Repeat the full discovery pass over the resulting code, including new files and moved responsibilities.
Review module relationships and nearby callers as well as edited lines; a local improvement can expose or create another smell.
Continue discovery and transformation until a complete pass adds no actionable findings and the ledger has no unblocked work remaining.
Avoid oscillating between equally valid designs: reopen a resolved finding only for new evidence of a concrete problem.

Run the repository's documented full check gate and repeat the affected end-user flows against the baseline.
Inspect rendered UI behavior where applicable, preserving the distinction between refactoring and separately justified visual or behavioral fixes.
Review the final diff for contract preservation, dead code, new duplication, secrets, and unrelated churn.
Run `git diff --check` and inspect diff statistics, accounting separately for new untracked files.
Leave commits, pushes, pull requests, and deployments to the user's request or the repository's required workflow.

**Done when:** the full rescan finds no unblocked actionable opportunities, final verification is accounted for, and every inventoried file and finding has a disposition.
A blocked finding or incomplete verification means the result is partial, not that every opportunity was resolved.
If interrupted, report the unreviewed inventory and unresolved ledger so the work can resume without pretending the sweep was exhaustive.

## Report

Finish with a concise summary of:

- Scope reviewed, coverage, and exclusions.
- Refactorings applied, grouped by design improvement and pointing to concrete files.
- Checks and end-user flows actually run, with before/after evidence and any separate bugfixes.
- Final diff statistics, including new files and necessary edits outside a narrow scope.
- Remaining blockers, unreviewed areas, or unavailable verification, or confirmation that the final complete pass found no additional actionable opportunities.
