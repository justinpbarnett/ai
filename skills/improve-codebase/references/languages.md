# Analysis coverage

A parser provides structural evidence, not type resolution, proof of unused code, or a behavioral verdict.
`doctor` reports local grammar availability and installed versions; `scan` reports how the grammars actually handled the project's inputs.
No grammar downloads or project tool invocations happen while scanning.

| Surface | Mechanical signals | Semantic limitations |
| --- | --- | --- |
| Python | Functions, classes, explicit parameters, estimated branching/nesting, literal-preserving duplicates, and local source-layout imports. | Import hooks, namespace packages, re-exports, reflection, and runtime consumers need review. |
| C# | Methods, constructors, lambdas, types, branching, nesting, duplicate tokens, and literal `.csproj` `ProjectReference` edges. | Namespace `using` does not identify files; conditional MSBuild and partial types need semantic review. |
| JavaScript, TypeScript, TSX | Named and anonymous callables, classes, branching, nesting, duplicate tokens, relative imports/re-exports, and simple local aliases. | The resolver does not evaluate runtime loaders, executable configs, JSONC/extends/workspace config chains, or package exports. |
| Vue SFC | Outer SFC plus independent script, script-setup, template and style analysis; maps embedded ranges to the original file. | Vue directive expressions, component resolution, scoped cascade, dynamic imports, slots, emits and reactivity are contract review, not proof of usage. |
| HTML | Element/subtree size and nesting, repeated exact subtrees, and local script/stylesheet edges. | Keep accessibility, attribute/text semantics, and script execution order in human review. |
| CSS and SCSS | Declaration counts, repeated ordered groups, selector term/ID counts, rule nesting, and local imports. | Specificity is a hint, not standards-complete evaluation of selectors; preserve cascade, ordering, scoping and variable resolution. |
| Other first-party files | Sizes, repeated exact substantive line blocks, and Git hotspots where available. | Explicit generic-only mode still requires all three semantic review axes. |

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

The scanner retains exact or explicitly unresolved dependency edges and derives strongly connected components from resolved paths only.
Review receipts depend on source hashes, graph context, applicable rules and reviewer-declared supporting inputs.
When static resolution cannot bound a relationship, use the partition wiring unit, and declare any supporting inputs not already in its context.
Do not claim complete coverage behind a missing parser or unreviewed wiring unit.
A new language without a syntax adapter uses the generic path; add an adapter only when it delivers useful evidence with documented limits and direct verification.
