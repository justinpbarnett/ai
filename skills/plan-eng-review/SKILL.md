---
name: plan-eng-review
description: >
  Engineering Manager perspective on feature planning. Locks architecture, data flow, diagrams, edge cases, and tests. Forces hidden assumptions into the open.
  Triggers on: "eng review", "plan engineering", "technical review", "architecture review"
---

# Plan: Engineering Review

Apply engineering management thinking to validate and strengthen the technical approach.

## Variables

- `argument` -- The feature plan or design doc to review

## Instructions

### Step 0: Parse Input

If `argument` is a file path, read it. Otherwise treat as inline description.

### Step 1: Understand the System

Map out:
- What existing code/services does this touch?
- What's the data flow?
- What are the dependencies?

### Step 2: Data Flow Diagram

Create an ASCII diagram showing:
- Data sources
- Processing steps
- Storage
- External integrations
- API boundaries

### Step 3: State Machine Analysis

If there's stateful behavior, document:
- States
- Transitions
- Invalid states
- Race conditions to consider

### Step 4: Edge Cases

List:
- Network failures
- Partial failures
- Retry scenarios
- Schema evolution
- Backward compatibility
- Rate limiting
- Timeouts

### Step 5: Test Matrix

Propose test coverage:
- Unit tests for logic
- Integration tests for APIs
- E2E tests for flows
- Error case tests
- Performance tests if relevant

### Step 6: Security Considerations

Document:
- Authentication
- Authorization
- Input validation
- SQL/command injection
- Secrets handling
- Data at rest/in transit

### Step 7: Failure Modes

For each component:
- What can fail?
- How does it fail?
- What's the impact?
- How is it detected?

## Output Format

```
Engineering Review: <feature name>

Data Flow:
<ASCII diagram>

State Machine:
<states and transitions>

Edge Cases:
- <edge case> → <handling>

Test Matrix:
| Scenario | Test Type | Priority |
|----------|-----------|----------|
| ... | ... | ... |

Security:
- <consideration 1>
- <consideration 2>

Failure Modes:
| Component | Failure Mode | Impact | Detection |
|-----------|--------------|--------|-----------|
| ... | ... | ... | ... |

Hidden Assumptions:
- <assumption 1>
- <assumption 2>
```

## Cookbook

<If: you discover a significant architectural gap>
<Then: escalate to the user before proceeding - this may require redesign>

<If: there are multiple reasonable approaches>
<Then: present tradeoffs, make a recommendation, let user choose>

<If: the plan is thin on technical detail>
<Then: ask targeted questions to fill gaps before proceeding>
