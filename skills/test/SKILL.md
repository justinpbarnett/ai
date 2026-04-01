---
name: test
description: >
  Comprehensive behavioral testing using parallel specialist agents and tools.
  Spawns multiple testers simultaneously: happy-path-tester, edge-case-tester,
  regression-tester, and integration-tester. Uses start_dev and start_stop 
  tools for server management. Each focuses on different test categories, 
  then combines findings into a unified test report. Triggers on "test this", 
  "validate the app", "run real tests", "test my changes", "smoke test".
---

# Test (Multi-Agent with Tools)

Uses parallel specialist testers to validate the application from multiple angles: happy paths, edge cases, regressions, and integrations. Uses tools for deterministic operations.

## Ground Rules

**Test like a human. No shortcuts.**

Each agent acts as a human QA tester. Run real commands, click real buttons, use real config and data from the local environment.

**NEVER run unit test commands.** This is behavioral testing only. Unit tests (`go test`, `npm test`, etc.) are run separately.

**NEVER create mocks or fakes.** Test against real services, real databases, real APIs.

## Tools for Testing

**Use these deterministic tools instead of bash commands:**

- `start_detect` - Detect project type and available start commands
- `start_dev` - Start development server (background by default)
- `start_stop` - Stop the running dev server
- `start_restart` - Restart the dev server

**For integration testing:**
- `jira_get` - Verify JIRA connections
- `rock_search` - Verify Rock RMS connectivity
- `email_inbox` - Verify email integration
- `slack_channels` - Verify Slack connectivity

## Instructions

### Step 1: Analyze Changes and Plan

**Use git tools to analyze changes:**
- `git_diff` (staged or unstaged) to see what changed
- `git_log` to understand recent direction

**Detect app type** (CLI, Web, API, Library)

**Build test plan categories:**
- Happy paths: Normal usage flows
- Edge cases: Boundary conditions, errors
- Regression: Previously working features
- Integration: External service interactions

### Step 2: Start Server if Needed

**For Web/API projects:**
1. Use `start_detect` to identify the project type
2. Use `start_dev` to start the server in background
3. Wait for server to be ready (check with curl or browser)

### Step 3: Launch Parallel Test Agents

Spawn 4 specialist testers simultaneously:

```
@happy-path-tester
Test all expected usage scenarios:
- For CLI: Common commands with typical args
- For Web: Primary user flows (login → action → logout)
- For API: Standard request sequences
- For Library: Normal API usage patterns

Tools to use:
- start_dev / start_stop for server management
- Use Playwright MCP if available for web testing

Report: tests_run, passed, failed, findings
```

```
@edge-case-tester
Test boundary conditions and error handling:
- Empty inputs, max lengths, special characters
- Invalid arguments, missing required fields
- Auth failures, permission errors
- Concurrent usage, race conditions
- Resource limits (large files, many requests)

Tools to use:
- start_restart to test recovery scenarios
- Try to break things in creative ways

Report: edge_cases_tested, issues_found, severity
```

```
@regression-tester
Verify previously working features still work:
- Core functionality unrelated to recent changes
- Features that might be affected indirectly
- Common workflows users depend on
- Integration points with other features

Focus on "did we break anything else?"

Report: regression_tests, new_issues, safe_areas
```

```
@integration-tester
Test interactions with external systems:
- Database read/write operations
- API calls to external services
- File system operations
- Message queues, webhooks, events
- Third-party integrations (Slack, email, etc.)

Tools to use:
- jira_get, rock_search, email_inbox, slack_channels
- Verify real connections work end-to-end

Report: integrations_tested, failures, config_issues
```

### Step 4: Synthesize Results

Wait for all testers to return. Combine findings:

**Test Summary:**
- Total tests run across all agents
- Pass/fail counts by category
- Critical issues (blocking)
- Warnings (non-blocking but notable)

**Issues Found:**
- Happy path failures (most critical)
- Edge case vulnerabilities
- Regressions (unexpected breakages)
- Integration problems (config, connectivity)

### Step 5: Stop Server

Use `start_stop` to clean up the dev server after testing.

### Step 6: Fix Critical Issues (Optional)

If issues found and user wants them fixed:

```
@generator
Fix the issues reported by testers:
- Prioritize happy-path failures first
- Address security issues from edge-case-tester
- Fix any data corruption risks
- Maintain existing patterns

Report: fixes_applied, verification_needed
```

### Step 7: Generate Final Report

**JSON Output:**
```json
{
  "test_run_id": "timestamp-branch",
  "summary": {
    "total_tests": 47,
    "passed": 42,
    "failed": 5,
    "critical": 2
  },
  "by_agent": {
    "happy-path-tester": { "tests": 12, "passed": 10, "failed": 2 },
    "edge-case-tester": { "tests": 15, "passed": 14, "failed": 1 },
    "regression-tester": { "tests": 14, "passed": 13, "failed": 1 },
    "integration-tester": { "tests": 6, "passed": 5, "failed": 1 }
  },
  "findings": [
    {
      "agent": "happy-path-tester",
      "severity": "critical",
      "description": "Login flow fails with valid credentials",
      "reproduction": "steps..."
    }
  ],
  "fixes_applied": 3,
  "recommendations": ["Investigate auth service", "Add rate limiting"]
}
```

**Human Summary:**
```
Test Results: {branch_name}

Happy Paths: 10/12 passed (@happy-path-tester)
Edge Cases: 14/15 passed (@edge-case-tester)
Regression: 13/14 passed (@regression-tester)
Integration: 5/6 passed (@integration-tester)

Critical Issues: 2
- Login flow broken (happy-path-tester)
- Database connection fails under load (integration-tester)

Warnings: 3
- Edge case: special characters in username not handled
- Regression: minor UI layout shift on mobile
- Integration: Slow API response from third-party

Fixes Applied: 3
Remaining Issues: 2 (require manual investigation)
```

## Cookbook

<If: app has both web UI and API>
<Then: all 4 agents test both surfaces.>

<If: test agents find environment issues (missing config, credentials)>
<Then: report as findings, don't try to work around.>

<If: edge-case-tester finds many issues>
<Then: prioritize by severity; not all edge cases need immediate fixing.>

<If: regression-tester finds unexpected breakages>
<Then: flag as high priority; recent changes had unintended side effects.>

<If: integration-tester finds config issues>
<Then: check local environment setup; may not be code problems.>

<If: happy-path-tester fails on core flow>
<Then: this is blocking; stop and fix before other testing.>

## Agent Specialization

Each agent focuses on their domain:
- **happy-path-tester**: Core functionality, typical usage
- **edge-case-tester**: Security, robustness, stress testing
- **regression-tester**: Stability, backward compatibility
- **integration-tester**: External dependencies, real connections

Parallel execution provides comprehensive coverage in ~1/4 the time.
