# Rules research: tests, comments, structure

Research for three rules to add to the improve-codebase skill. Each claim names its source. Sources marked **(primary)** are the author's own writing, official docs, tool docs, or specs. Sources marked **(secondary)** are the knowledge base answer or commentary. Claims I could not fetch and read this session are marked **(not re-read)** and rest on the cited book or page; verify before quoting.

## What the scanner can measure now

Read from `scripts/health/` (`detectors.py`, `inventory.py`, `syntax_tree.py`, `dependency_graph.py`, `scanning.py`):

- Callable complexity, nesting, parameter count, class and callable ranges (tree-sitter walk in `syntax_tree.py`).
- Duplicate blocks from rolling anchors over significant tokens, and exact line blocks for generic files (`detectors.py`).
- `large-file` finding from nonblank line count, which includes comment lines (`file_metric_findings`).
- Resolved local import edges and strongly connected components (cycles) for Python, JS/TS, CSS, and C# `ProjectReference` (`dependency_graph.py`, `cycle_findings`).
- Git hotspots: touch count per file over the last 100 commits, with `--no-renames` (`inventory.hotspots`). It stores one counter per file. It does not keep per commit file sets, so it cannot compute change coupling between files.
- Comment nodes are skipped on purpose: `syntax_tree.py` does `if "comment" in kind: continue`. So token streams ignore comments, and no comment inventory exists.
- Nothing classifies a file as test or production, finds test functions, reads coverage, or runs mutation tools. Path and name based classification does not exist.

Labels used below:

- `mechanical now`: the current scanner computes it.
- `new detector`: needs new code. The needed inputs are named.
- `review judgment`: a reviewer decides. No script should decide it.

Where a new detector only needs data the scanner already holds (paths, resolved edges, the parse tree), it still counts as `new detector`, but it is cheap.

---

## Rule 1: Tests

### Definition

**Rule statement (paste into skill):** Keep a test only if it names a business rule that the product must obey and that no other kept test already protects. Delete every other test, including tests of trivial code, wiring, framework behavior, private structure, and mock interactions.

Testable meaning of "necessary business rule":

1. The test name or body states a rule in domain words (a limit, a price, a permission, a state transition, an invariant, a calculation), not a method name.
2. A change to the rule in production code makes this test fail, and a pure refactor that keeps behavior does not (resistance to refactoring).
3. The code under test sits in Khorikov's domain model and algorithms quadrant: nontrivial logic with few collaborators. Trivial code and thin controllers fall outside it.
4. The test is the only kept test that kills at least one mutant of that rule, or the only one that covers a line or branch of it. Another kept test already covering the same rule makes this one redundant.
5. A reviewer can say what customer or business harm follows if the rule breaks. If not, the test is a candidate for removal.

Why this definition:

- Khorikov scores a test on four pillars: protection against regressions, resistance to refactoring, fast feedback, maintainability. He treats resistance to refactoring as nearly binary, so a test that breaks on a behavior keeping change is a false alarm and has negative value. His code type quadrants say to unit test the domain model and algorithms, give controllers only a few integration tests, refactor overcomplicated code, and skip trivial code. Source: Khorikov, *Unit Testing Principles, Practices, and Patterns* (Manning) (primary, book, not re-read), https://www.manning.com/books/unit-testing.
- Beck frames the amount of testing by confidence. His Stack Overflow answer says he is paid for code that works, so he tests as little as possible to reach a given level of confidence (not re-read: the page blocked automated fetch; wording is from memory). https://stackoverflow.com/questions/153234/how-deep-are-your-unit-tests/153565#153565 (primary, author's own answer).
- Beck's Test Desiderata lists twelve properties a test can have and says to choose how to trade them off, not to maximize all. https://testdesiderata.com/ (primary; the page text I read confirms the trade off framing, the list of twelve is from the original essay and was not re-read).
- Google's testing chapters say to test behaviors, not methods: "write a test for each behavior", where a behavior is a guarantee the system makes about its response to inputs. They say a brittle test fails on an unrelated change to production code, and that interaction tests are more brittle than state tests. https://abseil.io/resources/swe-book/html/ch12.html (primary, *Software Engineering at Google*, ch. 12, "Unit Testing").
- Google's Testing on the Toilet episode "Change Detector Tests Considered Harmful" names the failure mode: tests that restate the implementation and fail on every change. The post body did not load for me, only the title and comments. https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html (primary, body not re-read).

### Keep list

Keep these even when they look redundant or low level:

- A test that encodes a business rule as defined above. This is the whole point of the rule.
- A regression test for a real bug in a business rule, when no other kept test would have caught it. Fowler: when a high level test exposes a bug, replicate it with a unit test so the bug stays dead. https://martinfowler.com/bliki/TestPyramid.html (primary).
- The smallest set of boundary cases where outcome changes (at the limit, just over, empty input when it takes another path). Several ordinary inputs for one rule are redundant. Source for the criterion: Khorikov's behavior focus above.
- One broad integration or end to end check per critical user flow, when no kept unit test would catch a wiring failure. Dodds: "Write tests. Not too many. Mostly integration." https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications (primary). Fowler's practical pyramid also keeps a few high level tests: https://martinfowler.com/articles/practical-test-pyramid.html (primary).
- A mock interaction assertion when the interaction is itself a requirement (send the notification once, charge the card once). Google accepts interaction tests where the interaction is the behavior (ch. 13 covers when, not re-read). https://abseil.io/resources/swe-book/html/ch13.html (primary).
- Tests that tools or the project's verification gate need to run, such as a contract test against a published schema, and tests the repository's documented full gate requires. Removing these is a gate change, not a test prune. Report it instead of doing it.
- Tests a user wrote in the working tree and has not committed. Do not delete uncommitted user work.
- Fixtures, helpers, and config used by any kept test.

### Detection

| Signal | Label | What it needs |
| --- | --- | --- |
| Test file classification (path patterns `test`, `tests`, `__tests__`, `*.spec.*`, `*_test.*`, `*Tests.cs`) | `new detector` | Path rules in inventory. Prerequisite for every other test signal. |
| Test inventory: test function count per file | `new detector` | tree-sitter. Python: `function_definition` named `test_*` and `class_definition` named `Test*`. JS/TS: `call_expression` whose callee is `it`, `test`, `describe`. C#: `method_declaration` with `attribute_list` containing `Fact`, `Theory`, `Test`, `TestMethod`. |
| Duplicate test bodies (copy pasted cases that should be one parametrized test or none) | `mechanical now` | `duplicates` already finds repeated blocks. Filter its candidates to test paths. |
| Test with no assertion | `new detector` | tree-sitter: Python no `assert_statement` and no `assert*` or `pytest.raises` call; JS no `expect(` chain; C# no `Assert.` or `Should` call. |
| Mock interaction heavy test (change detector) | `new detector` | Count verification calls (`assert_called*`, `toHaveBeenCalled*`, `Received(`, `Verify(`) against state assertions in the same test. Flag tests where verification calls outnumber state assertions. Source of the criterion: Google ch. 12 (interaction tests are more brittle). |
| Large snapshot assertions (`toMatchSnapshot`, `match_snapshot`, `Verify`) | `new detector` | tree-sitter call names plus snapshot file size. Snapshots detect change, not rules. |
| Test reaches private names (`_name` in Python, `private` made internal, `__tests__` importing non exported symbols) | `new detector` | Resolved test to source edges from the existing dependency graph, then check imported symbol names for a leading underscore. Partial: needs resolved edges, which exist for Python and JS/TS. |
| Test covers only trivial code (callable complexity 1, no branches, getters, passthroughs) | `new detector` | Needs the test to unit map (below). Callable complexity itself is `mechanical now`. This applies Khorikov's trivial code quadrant. |
| Test to unit map and redundancy: tests whose covered lines are a subset of another kept test's lines | `new detector` | Per test coverage. Python: coverage.py dynamic contexts, `dynamic_context = "test_function"`, then query the `.coverage` SQLite database or use `coverage html --show-contexts`. https://coverage.readthedocs.io/en/latest/contexts.html (primary). JS: c8 and Istanbul have no per test context; run each test file with `c8 --reporter=json` and compare. https://github.com/bcoe/c8 (primary). C#: coverlet collects per run, so run per test with `dotnet test --filter` and merge. https://github.com/coverlet-coverage/coverlet (primary, per test claim is my inference). |
| Tests that are never the sole killer of any mutant | `new detector` | Run mutation testing with per test attribution. Stryker `coverageAnalysis: perTest` and the report fields `killedBy` and `coveredBy`. https://stryker-mutator.io/docs/stryker-js/configuration/ and https://raw.githubusercontent.com/stryker-mutator/mutation-testing-elements/master/packages/report-schema/src/mutation-testing-report-schema.json (primary). PIT (Java) and mutmut (Python) report killing tests or survivors: https://pitest.org/quickstart/basic_concepts/ and https://mutmut.readthedocs.io/en/latest/ (primary). Mutation runs are slow, so run on the domain files only. |
| Flaky or skipped tests (`skip`, `xfail`, `Ignore`, `pending`) | `new detector` | tree-sitter decorator and call names. Skipped tests are cheap deletion candidates after a check that the reason is not a live bug. |
| Test names that state a rule versus a method (`test_calculate`) | `review judgment` | Reviewer reads names. A name that cannot be said as a rule is a candidate. |
| Is the rule a real business rule | `review judgment` | Check tickets, docs, domain model code, and the Khorikov quadrant of the code under test. The scanner cannot know. |
| Does another kept test protect the same rule | `review judgment` when no coverage data, otherwise follows from the redundancy rows above | Name the defect each test would catch. If one existing check catches it reliably, the other is a candidate. |

Coverage is only for finding gaps and redundancy. Fowler says coverage is "a useful tool for finding untested parts of a codebase" but "of little use as a numeric statement of how good your tests are." https://martinfowler.com/bliki/TestCoverage.html (primary).

### Validation

Order matters. Tests are the safety net for the refactors this skill also makes, so prune tests in a separate final batch after refactors are verified, and keep it one revertable commit boundary (the skill leaves committing to the user).

Before deleting:

1. Run the full documented gate. It must be green. A red suite means you cannot tell which failures are real.
2. Record line and branch coverage and per file test counts. Python: `coverage run -m pytest` then `coverage json`. JS: `c8 --reporter=json-summary npm test`. C#: `dotnet test --collect:"XPlat Code Coverage"`.
3. For domain model files, record mutation score before. Stryker defines score as detected mutants over total, where survivors and no coverage mutants count as undetected. https://stryker-mutator.io/docs/General/faq/ (primary).
4. Write the rule to test list: each kept test with the one line business rule it protects. A kept test with no rule is a failure of the check.

After deleting:

1. The full gate is still green.
2. Coverage on domain model and algorithm files did not drop. Coverage on trivial code and controllers may drop. Report both numbers separately.
3. Mutation score on the domain files did not drop beyond a stated tolerance. A drop means a deleted test was the sole killer of a rule mutant, so restore it or write the rule's test. A drop on trivial code mutants is expected and acceptable.
4. Every business rule in the rule to test list still has at least one test.
5. Real behavior check: exercise the product through its real CLI, API, or UI as the skill already requires, since fewer tests means less automated protection.
6. Improvement metrics: test count, test lines, suite wall time, and the count of tests that failed during the refactor batch for no behavior reason (change detector failures). All should fall.

A deleted test is not a behavior keeping transformation. It lowers the net by design. The proof of safety is the evidence in steps above, plus git history for restore.

### Conflicts

Current text in `references/workflow.md`: "Keep batches runnable, preserve user changes and existing assertions, and reverse only your own transformation if verification fails." This collides with deleting tests.

Proposed replacement: "Keep batches runnable, preserve user changes, and reverse only your own transformation if verification fails. Preserve an existing test or assertion that protects a business rule. Remove any other test only in the final test pruning batch, after the checks in the tests rule pass."

Current text: "Use existing checks and direct behavior by default; add automated suites, ADRs, or specs only when required." This mostly agrees with the rule but leaves room to add suites.

Proposed replacement: "Use existing checks and direct behavior. Do not add suites, ADRs, or specs. Add or keep a single test only when it names a business rule that no kept test protects."

Also: SKILL.md step 4 says to confirm through "current checks, real user flows, and source/caller review". Keep that. Fewer tests make the real flow check carry more weight.

### Disagreement and recommendation

- The user's rule is stricter than every source read. Fowler says self testing code is the base that makes refactoring safe and expects coverage in the upper 80s or 90s, while being suspicious of 100%. https://martinfowler.com/bliki/SelfTestingCode.html and https://martinfowler.com/bliki/TestCoverage.html (primary). Beck, Khorikov, Google, and Dodds all say "fewer, higher value tests", but none says delete to the minimum.
- Pyramid versus trophy: Fowler and Google favor many small unit tests and few high level ones. Dodds favors mostly integration tests. This changes which tests to keep when two overlap: the pyramid keeps the unit test, the trophy keeps the integration test.
- Recommendation: treat the user's rule as the controlling policy and use Khorikov's quadrant and resistance to refactoring as the test for "necessary". Where a unit test and an integration test protect the same rule, keep the one that fails only on behavior changes and runs faster, and name the choice in the report. Do not treat Fowler's coverage band as a floor.

### Sources

- Khorikov, *Unit Testing Principles, Practices, and Patterns*, Manning (primary, book): https://www.manning.com/books/unit-testing
- Beck, Stack Overflow answer on how deep to test (primary, not re-read): https://stackoverflow.com/questions/153234/how-deep-are-your-unit-tests/153565#153565
- Beck, Test Desiderata (primary): https://testdesiderata.com/
- Fowler, Test Pyramid (primary): https://martinfowler.com/bliki/TestPyramid.html
- Fowler, Practical Test Pyramid, Vocke (primary for the pyramid detail): https://martinfowler.com/articles/practical-test-pyramid.html
- Fowler, Mocks Aren't Stubs (primary, not re-read; classicist versus mockist): https://martinfowler.com/articles/mocksArentStubs.html
- Fowler, Self Testing Code (primary): https://martinfowler.com/bliki/SelfTestingCode.html
- Fowler, Test Coverage (primary): https://martinfowler.com/bliki/TestCoverage.html
- Software Engineering at Google, ch. 12 (primary): https://abseil.io/resources/swe-book/html/ch12.html
- Software Engineering at Google, ch. 13 (primary, not re-read): https://abseil.io/resources/swe-book/html/ch13.html
- Google Testing Blog, change detector tests (primary, body not re-read): https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html
- Dodds, Testing Trophy (primary): https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications
- Stryker FAQ, configuration, report schema (primary): https://stryker-mutator.io/docs/General/faq/ , https://stryker-mutator.io/docs/stryker-js/configuration/ , https://raw.githubusercontent.com/stryker-mutator/mutation-testing-elements/master/packages/report-schema/src/mutation-testing-report-schema.json
- PIT (primary, not re-read): https://pitest.org/quickstart/basic_concepts/
- mutmut (primary, not re-read): https://mutmut.readthedocs.io/en/latest/
- coverage.py contexts (primary): https://coverage.readthedocs.io/en/latest/contexts.html
- c8 (primary, not re-read): https://github.com/bcoe/c8
- coverlet (primary, not re-read): https://github.com/coverlet-coverage/coverlet

---

## Rule 2: Comments

### Definition

**Rule statement (paste into skill):** Remove every comment that a reader can recover from the code. Make the code say it first: rename, extract a function, add a type, or add an assertion. Keep only comments that a tool reads, that the law or a doc generator requires, or that record a reason or constraint the code cannot express.

"Self documenting" in testable terms:

1. A comment is removed only after one of these replaced it: a better name, an extracted function with a name, a type or enum, a named constant, or an assertion. If none fits, the comment stays and falls under the keep list.
2. Removing the comment does not change the program. For deletions, the token stream and syntax tree without comments are identical before and after.
3. A reviewer who reads only the code can state what each function does and why a nonobvious branch exists. A branch that still needs a reason falls under the keep list.
4. No commented out code remains. Commented out code is dead code (ruff ERA001 docs: "Commented-out code is dead code, and is often included inadvertently. It should be removed."). https://docs.astral.sh/ruff/rules/commented-out-code/ (primary).

Where the sources start:

- Fowler lists Comments as a smell: a comment is often a deodorant for bad code, and the first move is to refactor so the comment is unneeded. He still keeps comments that say why, and ones that flag doubt. *Refactoring*, 2nd ed., ch. 3 (primary, book, not re-read). https://refactoring.com/catalog/ and https://martinfowler.com/books/refactoring.html .
- Martin, *Clean Code* ch. 4: "In every case a comment is a failure of our ability to use our languages to express our intent." Quoted in the Ousterhout and Martin exchange. https://github.com/johnousterhout/aposd-vs-clean-code (primary for both writers; the book is not re-read). Martin also lists good comments (legal, intent, warning of consequences, TODO, public API docs) in the same chapter (not re-read).
- Google Python style guide: comment "tricky parts of the code", and "never describe the code. Assume the person reading the code knows Python". https://google.github.io/styleguide/pyguide.html (primary).

### Keep list

Keep these. Each reason is listed so the reviewer can check it.

Comments that a tool reads (removing them changes behavior or build output):

- Shebangs (`#!/usr/bin/env python`): the OS reads them.
- Encoding declarations (`# -*- coding: utf-8 -*-`, PEP 263) and Dockerfile parser directives (`# syntax=docker/dockerfile:1`). Not re-read, from the language and Docker docs.
- Lint and type pragmas: `# noqa`, `# type: ignore`, `# pyright: ignore`, `# pragma: no cover`, `# fmt: off`, `// eslint-disable*`, `// @ts-expect-error`, `// @ts-ignore`, `// prettier-ignore`, `#pragma warning`, `// ReSharper disable`. Ruff documents `noqa` as a suppression directive. https://docs.astral.sh/ruff/rules/blanket-noqa/ (primary). ESLint config comments: https://eslint.org/docs/latest/use/configure/rules (primary).
- Compiler and build directives: Go `//go:build`, `//go:generate`, `//go:embed`. The Go doc says a directive matches `//(line |extern |export |[a-z0-9]+:[a-z0-9])` and is omitted from rendered docs. https://go.dev/doc/comment (primary). C# `#region`, `#pragma`, `#nullable` and the other preprocessor directives: https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/preprocessor-directives (primary). TypeScript triple slash references (`/// <reference ... />`) (not re-read).
- Bundler and test magic comments: `/* webpackChunkName */`, `/** @jest-environment jsdom */` docblock pragmas (not re-read).
- Conditional or processed markup comments in HTML and templates, and `<!-- prettier-ignore -->`.
- Vue and framework template pragmas and CSS `/*! ... */` preserved comments, `@charset`, `/* stylelint-disable */`.

Comments the law or a standard requires:

- License headers and copyright notices, SPDX identifiers. Spec: https://spdx.github.io/spdx-spec/ and REUSE https://reuse.software/spec/ (primary).
- Generated file banners (`// Code generated ... DO NOT EDIT.`). The Go convention is documented with `go generate` (not re-read).

Doc comments that a doc generator or schema consumes (public API only):

- Go doc comments on every exported name: complete sentences that start with the declared name, read by `go doc`, pkg.go.dev, and gopls. https://go.dev/doc/comment (primary).
- C# XML doc comments (`///`) when `GenerateDocumentationFile` is on. https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/xmldoc/ (primary).
- JSDoc and TSDoc that feed typed JS (`checkJs`), generated docs, or OpenAPI.
- Python docstrings that a tool shows or runs: public API docstrings read by Sphinx, help text for CLIs built on docstrings, `__doc__` consumers, doctests, and API frameworks that copy them into an OpenAPI description. PEP 257 defines docstring conventions. https://peps.python.org/pep-0257/ (primary). Google style: a docstring should give enough information to write a call without reading the code. https://google.github.io/styleguide/pyguide.html (primary).
- Keep a doc comment only where the signature leaves behavior open: units, ordering, error behavior, ownership, concurrency. Go's guide says do not describe the implementation. https://go.dev/doc/comment .

Comments that record what code cannot say (the narrow exception to the rule):

- Why a choice looks wrong but is right: a workaround, a compatibility quirk, an ordering requirement, a security check that cleanup might remove.
- A link to an external spec, bug, or ticket that explains a constant.
- A warning of consequences ("slow, do not call in a loop").
- A `TODO` or `FIXME` only when the user's repo uses them as tracked work. Otherwise convert to an issue or remove. ESLint `no-warning-comments` flags `todo`, `fixme`, `xxx` by default. https://eslint.org/docs/latest/rules/no-warning-comments (primary).

Everything else goes: narration of the next line, section banners, change history, author tags, closing brace labels, commented out code, TODOs with no owner, and comments restating a name or a type.

### Detection

| Signal | Label | What it needs |
| --- | --- | --- |
| Comment inventory: every comment node with range, text, and the node that follows it | `new detector` | tree-sitter `comment` node types (Python `comment`, JS `comment`, C# `comment`, CSS `comment`, HTML `comment`). `syntax_tree.py` currently skips them, so add an extraction pass before the skip. |
| Comment density (comment lines over nonblank lines) per file | `new detector` | Needs the inventory. The existing nonblank line count includes comments, so the denominator is `mechanical now`. |
| Keep list classifier (shebang on line 1, directive regexes, license header at file top, `///` and `/**` doc comments on declarations, Python docstring as first statement string) | `new detector` | Regex set plus node position. Python docstrings are `expression_statement` with a `string` child at the start of a body, not `comment` nodes. |
| Commented out code | `new detector` | Parse the comment text with the file's own tree-sitter grammar. If it parses with no error nodes and holds statements or calls, flag it. Cross check with ruff ERA001 (https://docs.astral.sh/ruff/rules/commented-out-code/, which lists false positives) and Sonar's commented out code rule (S125, on the Sonar rules index https://www.sonarsource.com/products/sonarqube/rules/ ; the rule page redirected, so I could not read it). Project tooling is the cheap `mechanical now` option when the project already has it. |
| Narration: comment directly above a statement shares most of its identifier words with that statement | `new detector` | Inventory plus identifier token overlap between comment words and the next sibling node. A heuristic. Treat hits as candidates. |
| Comment inside a long or complex callable that labels a block ("# validate", "# build result") | `new detector` | Inventory joined with callable ranges and complexity. Complexity and ranges are `mechanical now`. These comments mark extract function candidates (Fowler: Extract Function). |
| Section banner comments (`# ----`, `// ====`, `#region` that wraps a large block) | `new detector` | Regex on comment text. `#region` is on the keep list when tooling reads it. Prefer file split, not banners. |
| Author, date, and change history tags | `new detector` | Regex. |
| Stale comment (names a parameter or symbol that no longer exists) | `new detector` | Identifier tokens in comment text that match no identifier in the file. Heuristic. |
| TODO, FIXME, HACK, XXX markers | `new detector` | Regex. Project tooling: ESLint `no-warning-comments`. |
| Does a name, type, or extraction fully replace the comment | `review judgment` | The reviewer decides. |
| Is a "why" comment a real constraint, or a hedge | `review judgment` | The reviewer must name the constraint and what breaks if it is dropped. |
| Dynamic consumers of docstrings or comments (doc generators, CLI help, OpenAPI) | `review judgment` | Search project config for Sphinx, mkdocs, typedoc, DocFX, `GenerateDocumentationFile`, and frameworks that read docstrings. |

### Validation

Before:

1. Record the comment inventory counts by class: tool read, legal, doc, why, removable.
2. Record a per file hash of the comment free token stream. The scanner already builds this stream without comments, so a pure comment deletion keeps the hash.
3. Run the full documented gate and the project's linters and type checker. Run any doc build, so you have a baseline.

After:

1. Comment free token hash is equal for every file where only comments were removed. Python docstring deletions change the tree. For those files compare `ast.dump` with docstrings stripped, and check `__doc__` consumers (step 4).
2. For files where a rename or extract replaced a comment, this is a refactor. Verify it the usual way: full gate, callers read, real behavior.
3. Full gate, linters, and type checker are green. Suppression comments must not have been removed: count of `noqa`, `type: ignore`, `eslint-disable`, `go:build`, `#pragma`, and `#region` directives is unchanged or lower only by a justified deletion.
4. Docs build and CLI help output match the baseline. Run `--help` for a CLI built on docstrings and diff the output. Run `go doc ./...` and diff for Go. Run the doc generator for C# and TypeScript.
5. Improvement metrics: comment density down, commented out code count at zero, ERA001 and `no-warning-comments` counts at zero or lower, no keep list item lost, and every removed narration comment either replaced by a better name or extraction or shown redundant.

### Conflicts

Current text in `references/smell-guide.md`, Comments row: "Commentary compensates for obscure names, tangled control flow, or unexplained responsibilities." with remedies "Extract Function, Change Function Declaration; preserve comments explaining genuine constraints and reasons."

Proposed replacement for the remedy cell: "Extract Function, Rename, Introduce type or assertion; delete the comment once the code says it. Keep only comments that a tool reads, that the law or a doc generator requires, or that record a constraint the code cannot express."

The Judgment and safety list has no comment line. Add: "Remove every comment on the removable list. Never remove a directive, license header, or doc comment that a tool consumes."

Conflict with Ousterhout: see the next section. The proposed wording keeps a narrow why category, so it does not violate the existing guard in spirit. It narrows it to constraints the code cannot express, and it makes removal the default.

### Disagreement and recommendation

Ousterhout and Martin disagree openly and did not resolve it. https://github.com/johnousterhout/aposd-vs-clean-code (primary for both).

- Ousterhout: "Comments are crucially important and add enormous value to software." He writes that missing comments cost "10-100x" what incorrect comments cost. He wants interface comments that describe abstractions in English, since code cannot express them. His book: *A Philosophy of Software Design* (primary, book, not re-read), https://web.stanford.edu/~ouster/cgi-bin/book.php .
- Martin: "Comments are always failures"; "I look at every comment as potential misinformation"; "I prefer long names to comments." He accepts interface comments for public APIs and says he is not hostile to comments in general, only to gratuitous ones.

Where they overlap: both agree on removing comments that restate code, and Martin accepts why and public API comments. The real disagreement is about the middle: abstraction level comments on internal interfaces. Ousterhout wants them. Martin does not.

Recommendation: the user's rule sides with Martin as policy, so use it, but keep Ousterhout's strongest case inside the keep list: public API doc comments and why comments for constraints. Do not write new internal interface comments. This is a policy choice by the user, not a research result. If a project's maintainers follow Ousterhout, the user's explicit rule still wins. Report that this raises the cost when a constraint is lost, which is Ousterhout's point.

### Sources

- Ousterhout and Martin exchange, both positions in their own words (primary): https://github.com/johnousterhout/aposd-vs-clean-code
- Ousterhout, *A Philosophy of Software Design* (primary, book): https://web.stanford.edu/~ouster/cgi-bin/book.php
- Fowler, *Refactoring* 2nd ed., Comments smell (primary, book): https://martinfowler.com/books/refactoring.html and https://refactoring.com/catalog/
- Martin, *Clean Code* ch. 4 (primary, book; access page blocked): quoted via the exchange above
- Google Python style guide, comments and docstrings (primary): https://google.github.io/styleguide/pyguide.html
- Google JavaScript style guide, comments (primary, not re-read): https://google.github.io/styleguide/jsguide.html
- Google C++ style guide, comments (primary, not re-read): https://google.github.io/styleguide/cppguide.html
- PEP 8 (primary, not re-read): https://peps.python.org/pep-0008/
- PEP 257 (primary, not re-read): https://peps.python.org/pep-0257/
- Go doc comments (primary): https://go.dev/doc/comment
- C# XML documentation and preprocessor directives (primary): https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/xmldoc/ , https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/preprocessor-directives
- ruff ERA001 and blanket noqa (primary): https://docs.astral.sh/ruff/rules/commented-out-code/ , https://docs.astral.sh/ruff/rules/blanket-noqa/
- ESLint `no-warning-comments` (primary): https://eslint.org/docs/latest/rules/no-warning-comments
- Sonar commented out code rule S125, rules index (primary, rule page not read): https://www.sonarsource.com/products/sonarqube/rules/
- SPDX and REUSE (primary, not re-read): https://spdx.github.io/spdx-spec/ , https://reuse.software/spec/

---

## Rule 3: File and folder structure

### Definition

**Rule statement (paste into skill):** Group files by what changes together, name folders for the domain features they hold, and keep a file next to the code that uses it. Remove generic dumping folders and layer folders that scatter one feature. Move files with `git mv` and prove that imports, build, and cycles are no worse.

"Easy to understand" in testable terms:

1. Top level names say what the system does (Martin's screaming architecture test: a newcomer can tell what the system does from the listing). https://blog.cleancoder.com/uncle-bob/2011/09/30/Screaming-Architecture.html (primary).
2. A typical change touches one or two folders. Change coupling between files is high inside a folder and low across folders (Tornhill: modules that tend to change together are logically coupled). https://github.com/adamtornhill/code-maat (primary) and *Your Code as a Crime Scene* https://pragprog.com/titles/atcrime2/your-code-as-a-crime-scene-second-edition/ (primary, book, not re-read).
3. Most import edges stay inside the folder that owns them. A folder imported from only one other place belongs next to that place. Dodds: "Place code as close to where it's relevant as possible", and "Things that change together should be located as close as reasonable" (Abramov). https://kentcdodds.com/blog/colocation (primary).
4. No generic folder (`utils`, `helpers`, `common`, `misc`, `shared`, `lib`, `core`) holds unrelated features' code. Dodds adds that a shared utility can outlive the component that needed it, and a doc left in a separate folder drifts. Same source as above.
5. No import cycles between folders, and the depth and breadth of the tree stay small enough to scan (no folder with dozens of unrelated files, no chain of single child folders).
6. The layout follows the framework's mandatory conventions where the framework reads paths (Rails, Django, Next.js app router). Next.js: https://nextjs.org/docs/app/getting-started/project-structure (primary, not re-read). Django: https://docs.djangoproject.com/en/stable/intro/reusable-apps/ (primary, not re-read).

Where the sources start:

- Parnas: split modules by design decisions likely to change, hidden behind an interface, not by processing steps. "On the Criteria To Be Used in Decomposing Systems into Modules" (1972). https://www.win.tue.nl/~wstomv/edu/2ip30/references/criteria_for_modularization.pdf (primary, not re-read).
- Angular style guide: "Organize your project into subdirectories based on the features of your application", and avoid subdirectories based on the type of code. Prefer files focused on a single concept. https://angular.dev/style-guide (primary). The page I read did not mention LIFT. LIFT is from the older style guide (not re-read).
- Feature-Sliced Design: layers (App, Pages, Widgets, Features, Entities, Shared), slices by business domain, segments by technical purpose (`ui`, `api`, `model`, `lib`, `config`). A module imports only from layers below, and slices on one layer do not import each other. https://feature-sliced.design/docs/get-started/overview (primary).
- Go: start with the simplest layout. Add `internal/` when supporting code appears, `cmd/` for multiple commands, and split modules only for sharing. https://go.dev/doc/modules/layout (primary).
- Python packaging: the src layout keeps import packages apart from the project root, so tests run against the installed code and editable installs import only what is meant to be importable. Trade off: you must install before running. https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/ (primary).
- Simon Brown, package by component: bundle a component's logic and data access in one package with a small public interface. https://www.codingthearchitecture.com/2015/03/08/package_by_component_and_architectural_violations.html (primary, not re-read).
- Bogard, vertical slice architecture: organize by request or feature, not layers. https://www.jimmybogard.com/vertical-slice-architecture/ (primary, not re-read).
- Conway: a system's structure copies its organization's communication structure. https://www.melconway.com/Home/Committees_Paper.html (primary, not re-read). Use this as a caution: folder boundaries may mirror team boundaries on purpose.

### Keep list

Do not move or rename:

- Paths a framework, tool, or platform reads by convention: Rails `app/models`, Django `apps.py` and `migrations/`, Next.js `app/` and `pages/`, `src/` for Python src layout, `cmd/` and `internal/` in Go, `.github/`, `.vscode/`, `tests/` where the runner config points.
- Paths named in build and release config: `package.json` `main`, `exports`, `files`; `pyproject.toml` entry points and package data; `tsconfig` `paths` and `include`; `.csproj` references; Dockerfile `COPY`; CI workflows; `CODEOWNERS`; `.gitignore`; `.gitattributes`.
- Public import paths of a published library. A move is an API change, so leave it unless the user asks.
- Generated, vendored, and lock files, and migrations whose names order history.
- A layer folder that is the project's declared architecture and holds a small app. Go's guide and Brown's article both accept simple layouts at small scale.
- Files with uncommitted user changes. Move them only after the user commits or says so.
- Dynamic imports built from strings, plugin directories, and registries. The scanner cannot see them. Read the wiring partition first, as `workflow.md` already says.

### Detection

| Signal | Label | What it needs |
| --- | --- | --- |
| Import cycles between files | `mechanical now` | `cycle_findings` over resolved edges. Group the components by folder to find cycles between folders (a small new reducer, `new detector`). |
| Large files that mix several concepts | `mechanical now` | `large-file` finding. Pair with the Angular "single concept per file" criterion (review judgment). |
| Hot files by recent touches | `mechanical now` | `hotspots` (last 100 commits, per file counts). It cannot show which files move together. |
| Generic folder names (`utils`, `helpers`, `common`, `misc`, `shared`, `lib`, `core`, `base`, `stuff`, `general`, `manager`) | `new detector` | Path segments from the inventory. Cheap. Report file count and the number of distinct importer folders. |
| Folder cohesion: share of import edges that stay inside the folder, from the resolved edge list | `new detector` | Resolved edges from `dependency_graph.resolve_edges`. For each directory: internal edges divided by internal plus outgoing plus incoming edges. Low cohesion is a candidate. Unresolved edges stay unknown, so report coverage. |
| Single importer folder: a directory under a generic folder whose files are imported from one folder only | `new detector` | Same edges. Candidate to move next to its only user (colocation). |
| Layer folders in a feature heavy app (`controllers`, `models`, `views`, `services`, `repositories`, `components`, `hooks`, `types` at the top level, with one change touching many of them) | `new detector` | Path names, plus the change coupling signal below to confirm. |
| Change coupling: pairs of files that change in the same commit | `new detector` | `git log --name-only --no-renames --format=%H` into per commit file sets, ignore commits over a size cap, count pairs, and compute degree (share of changes with the other file) like code-maat. Code-maat's recipe is `git log --all --numstat --date=short --pretty=format:'--%h--%ad--%aN' --no-renames --after=YYYY-MM-DD > logfile.log` and `-a coupling`, where `degree` is a percent and `average-revs` is the mean revisions of the pair. https://github.com/adamtornhill/code-maat (primary). The scanner's `hotspots` already runs `git log --name-only`, so this extends it. |
| Co change across folders: average distinct top level folders per commit | `new detector` | Same per commit sets. High values mean a feature is spread out. |
| Depth and breadth: directory depth, files per directory, single child chains | `new detector` | Path counts from the inventory. Use as questions, not limits, like the existing metric alerts. |
| Test files far from the code they test | `new detector` | Needs test classification from Rule 1. Mirror trees are a convention in Python and Java, colocated in JS and Go. Follow the project's convention. |
| Does the top level name the domain (screaming test) | `review judgment` | Read the root listing as a newcomer. |
| Is a folder boundary a deliberate team or ownership boundary (Conway) | `review judgment` | Check `CODEOWNERS` and repo docs. |
| Does a framework convention require this path | `review judgment` | Read config and framework docs. |
| Which grouping is better when two are plausible | `review judgment` | The skill already says to compare at least two destinations. |

### Validation

Before:

1. Run the full gate and record the build, type check, and test results.
2. Save scanner output: cycle findings, large files, count of unresolved edges, folder cohesion table.
3. Compute change locality on the last N commits (for example 500): mean distinct directories per commit and share of commits whose files sit in one top level folder.
4. Build the move list as old path to new path. Search every config and doc file for the old paths (`rg -F old/path`), and list string based imports.

During the move:

1. Use `git mv old new` so history follows. Do not rewrite a file and move it in the same commit; move first, edit imports second. `git diff -M --stat` then shows pure renames at 100 percent similarity, and `git log --follow -- new/path` reaches old history.
2. Update imports and every config reference found in step 4.

After:

1. The full gate passes: build, type check, tests, lint. This proves imports and entry points still resolve.
2. Scanner rescan shows no new cycles and no rise in unresolved edges. Compare cycle findings and unresolved count with the baseline.
3. Re-run change locality on the same commits, mapping old file paths in history to new paths through the move list (`git log -M` or the explicit map). Mean distinct directories per commit should fall, and the share of single folder commits should rise. If neither moves, the new layout is not better, even if it looks neater.
4. Folder cohesion rises for the folders you changed, generic folder file counts fall, and the single importer count falls.
5. Real behavior check of the product, and a check that CI, Docker, and release config still point at real paths.
6. Report the number of files moved, depth and breadth changes, and any paths kept because of the keep list.

### Conflicts

Current text in `references/workflow.md`: "Prefer putting decisions that change together behind a small, useful interface and placing the code where maintainers naturally look for it." This agrees with the rule but has no operational test.

Proposed addition: "Place a file with the code that uses it. Name folders for domain features, not file types or generic words. Judge a layout by import cohesion, cycles, and how many folders a typical change touches. Move with `git mv`, then verify with the full gate and a rescan."

Current text in `SKILL.md` and `workflow.md`: "preserve exported names, data formats, execution order" and "Keep batches runnable". Moving files changes import paths. State the exception: "A move may change internal import paths. It must not change an exported name, a published import path, or a framework mandated path unless the user asked."

Current text in `languages.md`: the resolver does not evaluate runtime loaders, executable configs, workspace chains, or package exports. This is a limit on safe moves. Add to the rule: "Moving a file in a project that uses runtime loaders or package exports needs the wiring partition read first."

### Disagreement and recommendation

- Feature folders versus layers: Angular, Martin, Dodds, Bogard, and Brown say feature or component first. Rails and Django conventions are layer first by default and tools expect them. Feature Sliced Design combines both: layers on top, slices by domain inside. Go's guide has no feature rule at all and favors the least structure that works. No source measures that one layout is better.
- `golang-standards/project-layout` is not an official Go standard. Its README says: "This is NOT an official standard defined by the core Go dev team", and it points to Go's own "Organizing a Go module". https://github.com/golang-standards/project-layout (primary). Do not apply its folder list as a rule. Use the Go team's page.
- Python src versus flat: the packaging guide recommends the src layout for tests against the installed code, with the trade off that you must install first. Moving a flat layout to src is a larger change than a folder cleanup, so do it only when asked.
- Recommendation: choose by evidence on this repo: change coupling and import cohesion decide, with framework conventions and the keep list as hard limits. Prefer feature or component folders when change coupling shows files from different layer folders moving together. Do not impose a layout the framework does not expect.

### Sources

- Parnas 1972 (primary, not re-read): https://www.win.tue.nl/~wstomv/edu/2ip30/references/criteria_for_modularization.pdf
- Martin, Screaming Architecture (primary): https://blog.cleancoder.com/uncle-bob/2011/09/30/Screaming-Architecture.html
- Brown, package by component (primary, not re-read): https://www.codingthearchitecture.com/2015/03/08/package_by_component_and_architectural_violations.html
- Bogard, vertical slice architecture (primary, not re-read): https://www.jimmybogard.com/vertical-slice-architecture/
- Dodds, colocation (primary): https://kentcdodds.com/blog/colocation
- Angular style guide (primary): https://angular.dev/style-guide
- Feature Sliced Design (primary): https://feature-sliced.design/docs/get-started/overview
- Go, Organizing a Go module (primary): https://go.dev/doc/modules/layout
- golang-standards/project-layout README (primary): https://github.com/golang-standards/project-layout
- Python Packaging Guide, src layout versus flat layout (primary): https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
- Django reusable apps (primary, not re-read): https://docs.djangoproject.com/en/stable/intro/reusable-apps/
- Next.js project structure (primary, not re-read): https://nextjs.org/docs/app/getting-started/project-structure
- Rails guides (primary, not re-read): https://guides.rubyonrails.org/getting_started.html
- Tornhill, code-maat (primary): https://github.com/adamtornhill/code-maat
- Tornhill, *Your Code as a Crime Scene*, 2nd ed. (primary, book, not re-read): https://pragprog.com/titles/atcrime2/your-code-as-a-crime-scene-second-edition/
- Conway, "How Do Committees Invent?" (primary, not re-read): https://www.melconway.com/Home/Committees_Paper.html

---

## Proposed skill wording (all three rules)

Applied in `lean-rules.md`, with the conflicting lines in `workflow.md` and `smell-guide.md` rewritten to point at it. The original proposals follow for the record.

**Tests.** Keep a test only if it names a business rule that the product must obey and that no other kept test already protects. Delete every other test, including tests of trivial code, wiring, framework behavior, private structure, and mock interactions. Prune tests in a final separate batch, after refactors are verified. Before deleting, record a green gate, domain file coverage, and mutation score. After deleting, the gate is green, domain coverage and mutation score have not dropped, and every kept rule still has a test.

**Comments.** Remove every comment a reader can recover from the code. Replace it first with a better name, an extracted function, a type, a named constant, or an assertion. Keep only comments that a tool reads (shebangs, pragmas, directives, type and lint suppressions), that the law or a standard requires (licenses, generated banners), that a doc generator or API schema consumes (public doc comments), and that record a reason or constraint the code cannot express. Prove a pure deletion by an equal comment free token stream, then rerun the gate, linters, and doc builds.

**Structure.** Group files by what changes together. Name folders for the domain features they hold, not for file types or generic words. Keep a file next to the code that uses it. Remove or split `utils`, `helpers`, `common`, and layer folders that scatter one feature, unless a framework or published API requires the path. Move with `git mv` without editing in the same step, update imports and config references, then verify with the full gate, a rescan with no new cycles, and change locality measured on the same history before and after.

**Replacements for conflicting text.**

- `workflow.md`: "preserve user changes and existing assertions" becomes "preserve user changes. Preserve a test or assertion that protects a business rule. Remove any other test only in the final test pruning batch."
- `workflow.md`: "add automated suites, ADRs, or specs only when required" becomes "Do not add suites, ADRs, or specs. Add or keep one test only when it names a business rule no kept test protects."
- `smell-guide.md`: "preserve comments explaining genuine constraints and reasons" becomes "delete the comment once the code says it. Keep only comments that a tool reads, that the law or a doc generator requires, or that record a constraint the code cannot express."
