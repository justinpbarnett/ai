---
name: design-html
description: >
  Takes an approved mockup and generates production-quality HTML. Text reflows on resize, heights adjust to content. Framework detection for React/Svelte/Vue.
  Triggers on: "build html", "code this design", "implement mockup", "make this real"
---

# Design HTML

Generate production-quality HTML from an approved mockup or design.

## Variables

- `argument` -- Description of the design or reference to a mockup

## Instructions

### Step 0: Understand the Design

Get the mockup/design details:
- Layout structure
- Components needed
- Responsive behavior
- Animations
- Interactive elements

### Step 1: Detect Framework

Check the project for:
- React (.jsx, .tsx)
- Svelte (.svelte)
- Vue (.vue)
- Plain HTML

Use the appropriate syntax.

### Step 2: Generate HTML

Create:
- Semantic HTML structure
- CSS for styling (or use project's CSS approach)
- Responsive layouts (flexbox/grid)
- Proper spacing and typography
- Interactive states (hover, focus, active)
- Accessibility attributes

### Step 3: Ensure Quality

- Text reflows on resize (no hardcoded heights)
- Images have proper aspect ratios
- Forms have labels and validation
- Keyboard navigation works
- Works on mobile

### Step 4: Verify

- Check for syntax errors
- Verify responsive behavior
- Test interactive elements

## Output Format

```
Design HTML: <target>

Framework: <detected>

Generated:
- File: <path>
- Components: <N>
- Lines: <N>

Checks:
- Responsive: ✓
- Accessible: ✓
- Semantic: ✓
```

## Cookbook

<If: project uses CSS-in-JS>
<Then: use that approach>

<If: project uses Tailwind>
<Then: use Tailwind classes>

<If: design is complex>
<Then: break into components>

<If: you need to iterate>
<Then: show the HTML and ask for feedback>
