# Lean rules

Three standing rules for every run that may edit: prune tests to business rules, let the code replace its comments, and arrange folders by what changes together.
In audit-only mode, triage and report them like any other finding.

The scanner raises a candidate per test file (`tests`), per file with removable comments (`comments`), and per layout signal (`generic-folder`, `single-importer`, `folder-cycle`, `wide-folder`, `change-coupling`).
Triage each one: promote it with its transformation, or dismiss it as `false_positive` with the keep reason from this file as evidence.

**Order.** Comment work and other refactors run first. Folder moves run in their own batches. Test pruning runs last, after every refactor and move is verified, because the tests are the net under those changes.

## Tests

**Rule.** Keep a test only when it names a business rule the product must obey and no other kept test protects that rule. Delete the rest: tests of trivial code, wiring, framework behavior, private structure, mock interactions, snapshots, and duplicate cases.

A test is **necessary** when all of these hold:

- Its name or body states a rule in domain words: a limit, a price, a permission, a state transition, an invariant, a calculation.
- Breaking the rule makes it fail, and a refactor that keeps behavior does not (resistance to refactoring).
- The code under test is domain logic or an algorithm, not trivial code or a thin controller.
- It is the only kept test that catches the rule, and the reviewer can name the harm if the rule breaks.

Also keep:

- A regression test for a real business rule bug that no other kept test catches.
- The boundary cases where the outcome changes; one ordinary input per rule is enough.
- One integration or end to end check per critical flow, when no kept test would catch a wiring failure.
- An interaction assertion when the interaction is the requirement (charge once, notify once).
- Fixtures and helpers that kept tests use, and tests the user has not committed.
- Tests the documented gate or a published contract requires: report these instead of pruning them, since removing them changes the gate.

When a unit test and an integration test protect the same rule, keep the one that fails only on behavior change and runs faster, and name the choice in the finding.

**Detect.** The `tests` candidate lists each case with flags `no_assertion`, `interaction_heavy`, `snapshot`, and `skipped`; a `support` file holds fixtures or helpers, and an `unparsed` file needs its cases read by hand. Duplicate candidates on test paths mark copied cases. Whether a rule is a real business rule is review judgment: check the domain code, tickets, and docs.

**Validate.** A pruned test lowers the net on purpose, so record each one as a deliberate removal, not a behavior preserving refactor.

1. Before pruning: the full gate is green; record per file test counts and coverage of the domain files (`coverage json`, `c8 --reporter=json-summary`, `dotnet test --collect:"XPlat Code Coverage"`); record the mutation score of the domain files when the project has Stryker, mutmut, or PIT; write the rule to test list in the receipt evidence, one business rule per kept test.
2. After pruning: the full gate is green; every rule on the list still has a test; domain coverage and mutation score have not dropped (a drop on trivial code is expected, so report the two separately); real flows pass.
3. Report test count, test lines, and suite time before and after.

## Comments

**Rule.** Make the code say it, then delete the comment. Rename, extract a named function, introduce a type, a named constant, or an assertion. Narration, banners, change history, author tags, commented out code, unowned TODOs, and comments that restate a name or type all go.

Keep:

- Comments a tool reads: shebangs, encodings, lint and type pragmas, compiler and bundler directives. The scanner classes these as `directive` and never counts them.
- License, copyright, and SPDX headers (class `legal`, never counted) and generated file banners. A marker or commented code inside or right under such a header still counts.
- Doc comments that a doc generator, CLI help, doctest, or API schema consumes, on public API only. Check the project config for Sphinx, mkdocs, typedoc, DocFX, `GenerateDocumentationFile`, and frameworks that read docstrings.
- A reason the code cannot express: a workaround, an ordering or compatibility constraint, a security check that cleanup might remove, a link to the spec or bug behind a constant. The dismissal names the constraint and what breaks without it.
- TODO markers only where the repository tracks them as work.

**Detect.** The `comments` candidate counts removable comments and lists them by class: `doc`, `commented-code`, `marker`, `banner`, `note`. The class is a hint; the reviewer decides whether a name, type, or extraction fully replaces each comment.

**Validate.**

1. A pure deletion: the diff removes only comment lines. For Python docstrings, `ast.dump` of each changed file matches the original with docstrings stripped, and no `__doc__` consumer reads them.
2. A rename or extraction that replaced a comment is a refactor: read callers and verify it like any other.
3. The gate, linters, type checker, and any doc build are green; directive counts are unchanged; CLI `--help` and generated docs match the baseline.
4. A rescan shows `removable` falling, and every remaining removable comment is dismissed with its keep reason.

## Layout

**Rule.** Group files by what changes together. Name folders for the domain features they hold, not for file types or generic words. Put a file beside the code that uses it.

**Easy to understand** means:

- The root listing tells a newcomer what the system does (screaming architecture).
- A typical change touches one folder: files that change together share a folder.
- Most import edges stay inside the folder that owns them, and a folder with one importer lives beside it.
- No generic folder collects unrelated features, no folders import each other in a cycle, and no folder is too wide to scan.

Keep, as hard limits:

- Paths a framework or tool reads by convention: Rails `app/`, Django apps and `migrations/`, Next.js `app/` and `pages/`, Python `src/` layout, Go `cmd/` and `internal/`, `.github/`, and test roots that runner config names.
- Paths named in build, release, CI, Docker, `CODEOWNERS`, `tsconfig` paths, package `exports`, and entry points.
- Public import paths of a published library, unless the user asks.
- Migrations whose names order history, and generated, vendored, and lock files.
- Deliberate ownership boundaries recorded in `CODEOWNERS` or project docs.
- A small app's declared layer layout when change coupling shows no scatter.
- Files with uncommitted user changes.

Choose between feature and layer folders by this repository's change coupling and import cohesion, and compare at least two destinations. For Go, follow the Go team's "Organizing a Go module"; `golang-standards/project-layout` is not an official standard.

**Detect.** `generic-folder`, `single-importer`, `folder-cycle`, `wide-folder`, and `change-coupling`, alongside `dependency-cycle` and `large-file`. The scan also reports layout locality: mean directories per commit and the share of commits inside one directory, over recent history mapped forward to current paths. Read the wiring partition before moving anything that runtime loaders, plugin folders, or string imports reach. Dismiss `wide-folder` on generated output, such as migration metadata, as a false positive.

**Transform.**

1. Write the move list, old path to new path, and search every config and doc for each old path (`rg -F`).
2. Move with `git mv` in a batch that edits no file contents, so `git diff -M` shows pure renames and `git log --follow` keeps history.
3. Update imports and references in the next batch. A move may change internal import paths; it keeps exported names, published import paths, and framework paths.

**Validate.**

1. The full gate passes, which proves imports and entry points resolve.
2. A rescan shows no new `dependency-cycle` or `folder-cycle` and no rise in unresolved edges.
3. Layout locality improves against the baseline scan: mean directories per commit falls, or the single directory share rises. If neither moves, the new layout is not better.
4. The touched folders lose their `generic-folder`, `single-importer`, and `change-coupling` candidates, and CI, Docker, and release config point at real paths.
5. Report files moved and the paths kept by the keep list.
