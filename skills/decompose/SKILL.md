---
name: decompose
description: >
  Analyzes a feature spec and decomposes it into smaller, focused sub-tasks
  using multiple parallel analysis agents. Each agent examines a different
  dimension: data flow, UI components, API surface, testing needs, and 
  dependencies. Produces a task graph with mini-specs for each sub-task.
  Use when a user wants to break down a large feature, decompose a spec, 
  split into subtasks, or when a spec is too big to implement in one pass.
  Triggers on "decompose this spec", "break this down", "split into subtasks",
  "this is too big". Do NOT use for implementing features (use implement skill).
  Do NOT use for creating specs (use spec skill).
---

# Decompose (Multi-Agent)

Uses parallel specialist agents to analyze a feature from multiple angles, then synthesizes their findings into a comprehensive task graph.

## Variables

- `argument` -- Two space-separated values: `{spec_file_path} {task_id}` (e.g., `specs/feat-user-auth.md AUTH-042`). If no task_id provided, derive one from the spec filename.

## Instructions

### Step 1: Read the Spec

Read the full feature spec file. Identify the high-level goal and implementation steps.

### Step 2: Launch Parallel Analysis Agents

Spawn 4-5 specialist agents to analyze different dimensions of the feature:

```
@data-flow-analyzer
Analyze data models, state management, and persistence needs:
- New data models or schema changes needed
- State management approach (local, global, server)
- Database migrations required
- Data validation and transformation layers
- API contracts for data operations

Report: data_models, state_approach, migrations_needed, api_contracts
```

```
@ui-component-analyzer
Analyze UI structure and component needs:
- Pages/screens required
- Reusable components needed
- Component hierarchy and props
- State lifting or context needs
- Styling approach consistency

Report: pages, components, component_hierarchy, styling_approach
```

```
@api-surface-analyzer
Analyze API endpoints and external interfaces:
- New REST/GraphQL endpoints needed
- Request/response schemas
- Authentication/authorization requirements
- Rate limiting or caching considerations
- Third-party integrations

Report: endpoints, schemas, auth_requirements, integrations
```

```
@testing-strategy-analyzer
Analyze testing approach and coverage needs:
- Unit tests for business logic
- Integration tests for APIs
- E2E tests for critical flows
- Component tests for UI
- Edge cases and error scenarios

Report: test_levels, coverage_areas, critical_paths, edge_cases
```

```
@dependency-analyzer
Analyze dependencies and sequencing:
- What must be built first (foundations)
- What can be built in parallel
- External dependencies (APIs, libraries, teams)
- Blocking factors or risks
- Integration points between components

Report: dependencies, parallel_groups, blockers, integration_points
```

### Step 3: Synthesize Task Graph

Combine all analyzer reports to build the task graph:

1. **Group related work** into focused sub-tasks:
   - **Foundation** (Stage 1): Data models, migrations, core APIs
   - **Services** (Stage 2): Business logic, integrations
   - **UI** (Stage 3): Components, pages (can parallelize if independent)
   - **Integration** (Stage 4): Wiring everything together
   - **Testing** (Stage 5): Comprehensive test coverage

2. **Assign stages** based on dependencies:
   - Stage 1: No dependencies (data layer)
   - Stage 2: Depends on Stage 1 (services)
   - Stage 3: Can run parallel, may depend on Stage 2
   - Stage 4: Depends on all prior stages
   - Stage 5: Final verification

3. **Create mini-specs** at `specs/subtasks/{task_id}/{sub_task_id}.md`

### Step 4: Output Task Graph JSON

```json
{
  "parent_spec": "{spec_file_path}",
  "task_id": "{task_id}",
  "is_decomposed": true,
  "analysis_summary": {
    "complexity": "high/medium/low",
    "estimated_sprints": 3,
    "risk_areas": ["list from analyzers"]
  },
  "tasks": [
    {
      "id": "task-1-data-model",
      "title": "Add user data model and migration",
      "stage": 1,
      "spec_file": "specs/subtasks/{task_id}/task-1-data-model.md",
      "depends_on": [],
      "files_owned": ["src/models/user.go", "migrations/001_add_users.sql"],
      "status": "pending",
      "analysis_source": "data-flow-analyzer"
    }
  ]
}
```

## Cookbook

<If: feature is small enough for single task>
<Then: output single-task graph with is_decomposed: false. Don't create mini-specs.>

<If: analyzers disagree on complexity>
<Then: prefer the most conservative (highest complexity) assessment.>

<If: data-flow and ui-component both need the same files>
<Then: assign them to different stages to avoid conflicts.>

<If: feature has clear layering (data → service → route → UI)>
<Then: decompose by layer, each in successive stages.>

<If: multiple independent UI components>
<Then: assign them the same stage so they can run in parallel.>

<If: decomposing for agent team execution>
<Then: verify no two tasks in same stage share files_owned entries.>

## Validation

- Task graph JSON is valid and parseable
- All spec_file paths will exist after creation
- Stage numbering starts at 1
- No circular dependencies
- Analysis reports are cited in task metadata
