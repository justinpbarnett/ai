# Analysis coverage

A parser provides structural evidence, not type resolution, proof of unused code, or a behavioral verdict.
`doctor` reports local grammar availability and installed versions; `scan` reports how the grammars actually handled the project's inputs.
No grammar downloads or project tool invocations happen while scanning.

| Surface | Mechanical signals | Semantic limitations |
| --- | --- | --- |
| Python | Functions, classes, explicit parameters, estimated branching/nesting, literal-preserving duplicates, and local source-layout imports, comments and docstrings, and test cases with assertion counts. | Import hooks, namespace packages, re-exports, reflection, and runtime consumers need review. |
| C# | Methods, constructors, lambdas, types, branching, nesting, duplicate tokens, and literal `.csproj` `ProjectReference` edges, comments, and xUnit, NUnit and MSTest cases. | Namespace `using` does not identify files; conditional MSBuild and partial types need semantic review. |
| JavaScript, TypeScript, TSX | Named and anonymous callables, classes, branching, nesting, duplicate tokens, relative imports/re-exports, simple local aliases, comments, and test cases from describe, it, test and each forms. | The resolver does not evaluate runtime loaders, executable configs, JSONC/extends/workspace config chains, or package exports. |
| Vue SFC | Outer SFC plus independent script, script-setup, template and style analysis; maps embedded ranges to the original file. Top level template comments are recorded. | Vue directive expressions, component resolution, scoped cascade, dynamic imports, slots, emits and reactivity are contract review, not proof of usage. |
| HTML | Element/subtree size and nesting, repeated exact subtrees, and local script/stylesheet edges. | Inline script and style bodies are opaque to comment and test signals. Keep accessibility, attribute/text semantics, and script execution order in human review. |
| CSS and SCSS | Declaration counts, repeated ordered groups, selector term/ID counts, rule nesting, and local imports. | Specificity is a hint, not standards-complete evaluation of selectors; preserve cascade, ordering, scoping and variable resolution. |
| Other first-party files | Sizes, repeated exact substantive line blocks, and Git hotspots where available. | Explicit generic-only mode still requires all three semantic review axes. No comment or test parsing; those signals are absent, not clean. |

Ranges are 1-based Unicode columns, with exclusive end coordinates.
Vue ranges use original SFC bytes before translating to line/column; CRLF and preceding non-ASCII text do not shift the reported location.
Unsupported preprocessors, parser errors, and missing priority grammars remain visible as scanner gaps, separate from findings.
For unquoted CSS WOFF2 data URLs with `{{font:NAME.woff2}}` payloads, the scanner can retry with same-length base64 bytes and reports the fallback in its limitations.
Ranges and hashes still use the original source; verify the actual fonts with the project's build.
Check whether the project's compiler or runtime accepts the input before treating a parser failure as a product defect.
If the project accepts it, keep the source unchanged and report the scanner limitation unless there is a separate, verified reason to change the source.
Unresolved references are reported as limitations, not guessed edges; unresolved Vue external blocks are capability gaps.
In a supported `tsconfig.json` or `jsconfig.json`, `paths` targets are relative to the config directory unless it sets `baseUrl`.
An unmatched bare specifier is only tried directly under an explicit `baseUrl`.

## Signals and refresh

Nonblank lines include comments; compare sizes as hotspots rather than rules on file shape.
Callable complexity starts at one; Python counts conditionals, comprehensions, loops, handlers, cases and boolean nodes; C# counts conditions, loops, catches, switch sections/arms and boolean short-circuit operators; JS/TS counts conditions, loops, catches, cases, ternaries and short-circuit operators.
Branch metrics exclude bodies of nested callables from their enclosing callable's counts.
Duplicate matching uses bounded rolling anchors over significant tokens with literal values intact, or indentation-preserving exact lines for generic sources.
The default rolling window samples anchors of 50 tokens, guaranteeing a shared anchor within a 61-token exact sequence; shorter repeated blocks can remain for semantic discovery.
Grouped occurrences are candidates, not evidence that their responsibilities should be merged.

Comments are classified as directive or legal (kept, never removable) or as doc (doc comments and docstrings), marker, banner, commented-code or note (removable candidates, grouped per file under `comments`, with a `lines` count when one group spans several lines).
Adjacent line comments merge into one group, and a group that mixes prose and code is split into runs.
A comment that looks like code is judged by parsing it, so short prose can still be misclassified; the reviewer decides.
Test files get one `tests` candidate per file with case counts and flags for no assertion, interaction heavy, snapshot and skipped cases.
Assertion counts include interaction checks. A file with zero detected cases in a parsed language reports `support`, which means the extractor found no cases, not that the file is clean; a test file in a language without a case extractor, such as Go, reports `unparsed` and needs a manual case count.
Test detection follows path and name conventions, and the same conventions exclude test files from layout rules.

Layout rules work on directories of authored non-test files: `generic-folder` for catch-all names, `single-importer` for a folder imported by exactly one other folder, `folder-cycle` for strongly connected folders, and `wide-folder` above `folder_files`.
They use resolved edges only, so unresolved imports hide cycles and importers.
`change-coupling` pairs files that changed together in at least `coupling_revisions` commits with a degree of at least `coupling_degree`, where degree is shared commits divided by the mean of each file's commits.
The history window is the latest 500 commits, and commits over 30 files are skipped as bulk edits.
Historical paths follow renames committed in history and staged renames in the working tree; an unstaged move (a delete plus an untracked file) is not detected, and its old history stays under the old path.
Without Git history the scan records a limitation and skips coupling and locality.
Layout locality (mean directories per commit and the share of single directory commits) is reported with `mapped_paths`, and it is a metric, never a candidate.

The scanner retains exact or explicitly unresolved dependency edges and derives strongly connected components from resolved paths only.
Review receipts depend on source hashes, graph context, applicable rules and reviewer-declared supporting inputs.
When static resolution cannot bound a relationship, use the partition wiring unit, and declare any supporting inputs not already in its context.
Do not claim complete coverage behind a missing parser or unreviewed wiring unit.
A new language without a syntax adapter uses the generic path; add an adapter only when it delivers useful evidence with documented limits and direct verification.
