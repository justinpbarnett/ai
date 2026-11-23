# Fowler smell guide

Use these 24 smells from the second edition as an investigation checklist, not as quotas or mandatory design patterns.
The remedies below are starting points from Fowler's catalog, summarized in original wording rather than reproduced book text.
Select the transformation that improves this code's actual responsibilities and preserves its contracts.

## Names, duplication, and comprehensibility

| Smell | What to investigate | Candidate refactorings |
| --- | --- | --- |
| Mysterious Name | Names obscure intent, units, domain meaning, or side effects. | Change Function Declaration, Rename Variable, Rename Field. |
| Duplicated Code | Multiple implementations encode the same knowledge and must change together. | Extract Function, Slide Statements, Pull Up Method. |
| Long Function | A function mixes intentions or requires tracing implementation details to understand its purpose. | Extract Function, Replace Temp with Query, Split Phase, Decompose Conditional, Replace Nested Conditional with Guard Clauses. |
| Comments | Commentary compensates for obscure names, tangled control flow, or unexplained responsibilities. | Extract Function, Change Function Declaration, Replace Magic Literal, Introduce Assertion; delete the comment once the code says it, keeping only what the comment keep list in [lean-rules.md](lean-rules.md) names. |

## Data and state

| Smell | What to investigate | Candidate refactorings |
| --- | --- | --- |
| Long Parameter List | Callers must reconstruct context, pass control flags, or coordinate many related arguments. | Preserve Whole Object, Introduce Parameter Object, Replace Parameter with Query, Remove Flag Argument. |
| Global Data | Shared state can be changed far from the code that depends on it. | Encapsulate Variable; narrow ownership and access after tracing all readers and writers. |
| Mutable Data | Uncontrolled mutation, aliases, or stored derived values make state hard to reason about. | Encapsulate Variable, Split Variable, Separate Query from Modifier, Remove Setting Method, Replace Derived Variable with Query. |
| Data Clumps | The same related values repeatedly travel together across fields, calls, or functions. | Extract Class, Introduce Parameter Object, Preserve Whole Object. |
| Primitive Obsession | Raw strings, numbers, or type codes repeatedly carry domain rules that should have one home. | Replace Primitive with Object, Replace Magic Literal, Replace Type Code with Subclasses, Introduce Parameter Object. |
| Temporary Field | Fields make sense only during particular operations or states, leaving objects partly meaningful. | Extract Class, Replace Function with Command, Introduce Special Case. |
| Data Class | Other modules repeatedly interpret and manipulate a record's data, scattering behavior that belongs together. | Encapsulate Record, Encapsulate Collection, Move Function. |

## Responsibility and coupling

| Smell | What to investigate | Candidate refactorings |
| --- | --- | --- |
| Divergent Change | One module changes for several unrelated reasons or mixes processing phases. | Split Phase, Extract Class, Move Function. |
| Shotgun Surgery | One conceptual change requires coordinated edits across many modules. | Move Function, Move Field, Combine Functions into Class, Combine Functions into Transform, Inline Function, Inline Class. |
| Feature Envy | A function relies more on another module's data than on its current home's responsibilities. | Move Function, Extract Function; respect deliberate boundary strategies. |
| Insider Trading | Modules reach into each other's internals or exchange excessive private knowledge. | Move Function, Move Field, Hide Delegate, Replace Superclass with Delegate. |
| Message Chains | Callers navigate several objects and depend on the intermediate structure. | Hide Delegate, Extract Function, Move Function. |
| Middle Man | A layer mostly forwards calls without a useful boundary or responsibility. | Remove Middle Man, Inline Function, Replace Superclass with Delegate. |
| Large Class | A class or analogous module contains several separable responsibilities or unrelated data groups. | Extract Class, Extract Superclass, Replace Type Code with Subclasses. |
| Alternative Classes with Different Interfaces | Implementations of the same role expose unnecessarily inconsistent APIs. | Change Function Declaration, Move Function, Extract Superclass. |
| Refused Bequest | A subtype cannot honor its parent's contract or inherits irrelevant responsibilities. | Push Down Method, Push Down Field, Replace Subclass with Delegate, Replace Superclass with Delegate. |

## Control flow and unnecessary machinery

| Smell | What to investigate | Candidate refactorings |
| --- | --- | --- |
| Repeated Switches | Type-dependent branching repeats across operations and new variants require coordinated edits. | Replace Conditional with Polymorphism; use only when variation actually warrants it. |
| Loops | Iteration obscures a transformation or combines independent jobs. | Replace Loop with Pipeline, Split Loop, Extract Function. |
| Lazy Element | A function, class, or hierarchy adds indirection without enough meaning or work. | Inline Function, Inline Class, Collapse Hierarchy. |
| Speculative Generality | Unused extension points, parameters, branches, or abstractions serve hypothetical requirements. | Collapse Hierarchy, Inline Function, Inline Class, Change Function Declaration, Remove Dead Code. |

## Judgment and safety

- Choose by intent rather than fixed function lengths, parameter counts, or complexity scores.
- Unify duplicated knowledge, not merely similar syntax; independent concepts may need to evolve separately.
- Preserve simple records, loops, conditionals, and delegation when they communicate intent better than the proposed alternative.
- Prefer clear names and explicit responsibilities over extra layers, flag-driven helpers, or universal abstractions.
- Trace aliases and all mutation sites before replacing stored state with queries or values; preserve identity, caching behavior, evaluation frequency, and side effects.
- Check dynamic lookup, reflection, plugin registration, framework conventions, serialized names, and external consumers before renaming or declaring code dead.
- Treat API-changing catalog moves, including changes to errors or construction, as internal refactorings only when external contracts remain intact.
- Respect performance requirements when considering extra passes, allocations, queries, or indirection; measure an affected critical path instead of assuming equivalence.
- Preserve an intentional boundary even if it resembles a smell; record the actual reason that makes the candidate non-actionable.

## Sources

- [Refactoring: Improving the Design of Existing Code, second edition](https://martinfowler.com/books/refactoring.html): book, scope, and small behavior-preserving transformations.
- [Refactoring home and definition](https://refactoring.com/): observable behavior, incremental restructuring, and frequent verification.
- [Official catalog of refactorings](https://refactoring.com/catalog/): transformation names and summaries, including inverse moves for different contexts.
- [Refactoring Malapropism](https://martinfowler.com/bliki/RefactoringMalapropism.html): the distinction between refactoring and general restructuring.

The public catalog supplies summaries rather than the book's complete mechanics.
When a transformation is unfamiliar or risky, read its official catalog entry and any available authorized book material before applying it.
The smell guide and exhaustive-sweep workflow are practical adaptations; the whole-codebase sweep is the user's requested scope, not a claim that Fowler prescribes repository-wide cleanup campaigns.
