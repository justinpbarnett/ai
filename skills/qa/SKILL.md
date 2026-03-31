---
name: qa
description: >
  Test the application in a real browser, find bugs, fix them with atomic commits, re-verify. Auto-generates regression tests for every fix.
  Triggers on: "qa", "test this", "check this page", "verify this works", "browse test"
---

# QA

Test the application in a real browser, find bugs, fix them, and generate regression tests.

## Variables

- `argument` -- URL to test, or description of what to test

## Instructions

### Step 0: Parse Target

If `argument` is a URL, navigate to it.
If it's a description, derive what needs testing.

### Step 1: Set Up Test Environment

- Start the dev server if needed
- Ensure browser is available
- Clear any auth/session state if needed

### Step 2: Define Test Plan

List what to verify:
- Core user flows
- Edge cases
- Error states
- Empty states
- Responsive behavior

### Step 3: Execute Tests

For each test case:
1. Navigate to starting state
2. Perform action
3. Verify expected result
4. Screenshot on failure

### Step 4: Document Bugs

For each bug found:
- Reproduction steps
- Expected vs actual
- Screenshot/video
- Severity (blocker/major/minor)

### Step 5: Fix Bugs

For each bug:
1. Investigate the root cause
2. Make minimal fix
3. Commit with descriptive message
4. Re-verify the fix works
5. Create regression test

### Step 6: Report

Summary of:
- Tests run
- Bugs found
- Bugs fixed
- Regression tests added

## Output Format

```
QA Report: <target>

Tests Run:
- <test 1>: <pass|fail>
- <test 2>: <pass|fail>

Bugs Found:
1. <description> [<severity>]
   - Steps to reproduce
   - Fix applied

Bugs Fixed: <N>
Regression Tests: <N>

Status: <complete>
```

## Real Browser Testing

Use Playwright or similar to:
- Open actual browser
- Click through flows
- Fill forms
- Verify rendering
- Check console for errors
- Take screenshots

## Cookbook

<If: the app requires auth>
<Then: check for test credentials or use /setup-browser-cookies>

<If: bugs are found during testing>
<Then: fix them one at a time with atomic commits>

<If: a fix is made>
<Then: always re-verify before moving on>

<If: regression test can be written>
<Then: add it to the test suite>

<If: the bug is complex>
<Then: use /investigate to find root cause before fixing>
