---
name: document
description: >
  Generates comprehensive markdown documentation using parallel specialist 
  agents. Spawns: technical-writer, api-docs-agent, usage-example-generator,
  and architecture-visualizer to produce complete feature documentation.
  Creates docs in docs/ with technical details, API references, usage examples,
  and architecture diagrams. Use when a user wants to document a feature, 
  generate feature docs, write up what was built, create implementation 
  documentation. Triggers on "document this feature", "generate docs", 
  "write up what was built", "create feature documentation".
---

# Document (Multi-Agent)

Uses parallel specialist agents to document a feature from multiple perspectives: technical deep-dive, API reference, usage guide, and architecture overview.

## Variables

- `argument` -- Feature name or identifier, optionally with spec path (e.g., `user-auth specs/feat-user-auth.md`). If omitted, derives from current branch.

## Instructions

### Step 1: Collect Inputs and Analyze Changes

**Collect inputs:**
- feature_name: From argument or derive from branch
- spec_path: Optional path to feature spec
- base_branch: Detect via `git remote show origin` or default to main

**Analyze code changes:**
```bash
git diff origin/<base-branch> --stat
git diff origin/<base-branch> --name-only
```

For files with significant changes (>50 lines), read the diff to understand implementation.

### Step 2: Launch Parallel Documentation Agents

Spawn 4 specialist agents simultaneously:

```
@technical-writer
Write the technical implementation section:
- What was built and why
- Key architectural decisions
- Technical implementation details
- Files modified/created with explanations
- Configuration changes required

Target audience: Other developers on the team
Output: technical_section.md
```

```
@api-docs-agent  
Generate API documentation if the feature has API changes:
- New endpoints added
- Request/response schemas
- Authentication requirements
- Example requests and responses
- Error handling and status codes

If no API changes: return "No API changes detected"
Output: api_section.md
```

```
@usage-example-generator
Create practical usage examples:
- Common use cases and workflows
- Code examples showing how to use the feature
- CLI commands if applicable
- Screenshots or UI walkthroughs if provided
- Troubleshooting common issues

Target audience: End users of the feature
Output: usage_section.md
```

```
@architecture-visualizer
Describe the system architecture changes:
- How this feature fits into the overall system
- Data flow diagrams (text-based)
- Component interactions
- Integration points with existing systems
- Performance considerations

Output: architecture_section.md
```

### Step 3: Synthesize Documentation

Wait for all agents to return their sections. Combine into a single document:

**Create docs/ directory if needed:**
```bash
mkdir -p docs
```

**Generate final document at:** `docs/feature-{feature-name}.md`

**Structure:**
```markdown
# Feature: {Feature Name}

## Overview
Brief description of what was built and why.

## Technical Implementation
[From @technical-writer]

## API Reference (if applicable)
[From @api-docs-agent, or omit if no API changes]

## Usage Guide
[From @usage-example-generator]

## Architecture
[From @architecture-visualizer]

## Deployment/Configuration
Any setup required to use this feature.
```

### Step 4: Review and Finalize

Have @evaluator agent review the combined documentation:
- Check for completeness
- Verify technical accuracy
- Ensure consistency across sections
- Confirm all agents' outputs are incorporated

### Step 5: Return Result

Return the path to the documentation file and a summary of what each agent contributed.

## Output

```
Documented: {feature_name}
Path: docs/feature-{feature-name}.md

Sections:
- Technical Implementation (@technical-writer)
- API Reference (@api-docs-agent)
- Usage Guide (@usage-example-generator)
- Architecture (@architecture-visualizer)

Reviewed by: @evaluator
```

## Cookbook

<If: feature has no API changes>
<Then: api-docs-agent returns empty; omit API section from final doc.>

<If: screenshots provided>
<Then: copy to docs/assets/ and reference from usage section.>

<If: feature is purely internal (no user-facing changes)>
<Then: technical-writer and architecture-visualizer are primary; usage section can be brief.>

<If: spec file provided>
<Then: pass to all agents as reference for original requirements.>

<If: documentation already exists for this feature>
<Then: have agents suggest updates rather than full rewrite.>

## Validation

- All 4 agents completed their sections
- Final document combines all sections coherently
- File paths are relative to docs/
- Technical accuracy verified by evaluator
