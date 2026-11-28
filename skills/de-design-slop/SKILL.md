---
name: de-design-slop
description: Strip AI design tells from a website and restyle it from a sourced brand direction.
disable-model-invocation: true
---

# De-design-slop

AI design tells all share one root: **the median**—the unbriefed average of training data (indigo gradient, Inter, three rounded cards, centered hero, soft shadow).

> **Median test:** for any choice on the page, ask what a model with no brief would pick. If the page picked that, it is a tell.

Avoid trading one median for another (e.g. indigo to teal, Inter to Space Grotesk or Instrument Serif). A replacement holds only when it is **sourced** from something true about this business that a competitor could not claim. Copy goes to `humanize`.

## 1. See the page

Screenshot every distinct page at desktop and phone widths using the project's browser driver (Playwright, Puppeteer) or a headless run. If no browser is reachable, read stylesheet and markup and note that a source-only pass misses visual tells.

## 2. Inventory the tells

Check [TELLS.md](TELLS.md) and apply the median test to everything else. Separate **tells** (costume: emoji tiles above identical two-line blurbs) from **conventions** (structure: three-column feature grid, right-aligned nav CTA). Record every present tell by `file:line`.

## 3. Source a direction

Read the business's copy, README, docs, product, and customers to find real material (its trade, tools, era, photos, numbers); ask the user for what the repo cannot answer.

Commit to concrete tokens traced to that material: display/body type, palette (dominant, neutral, accent), radius, spacing, elevation, motion. Write them to `DESIGN.md` at the repo root. Confirm the direction with the user and collect peer comparison sites before editing stylesheets.

## 4. Strip, loudest first

Work down by signal: palette → type → surface effects → cards/layout → icons/imagery/motion.

- **Delete before replacing.** Restraint reads as decided; remove gradients, glows, grid lines, eyebrow badges, and icon tiles instead of swapping ornaments.
- **Edit tokens, not components.** Fix CSS variables or theme files globally rather than per-component overrides.
- **Keep substance.** Restyle real sections; flag and remove invented content (fake testimonials, stock logo walls) rather than restyling lies.

## 5. Prove it

- **The lineup.** Screenshot peer sites beside the page and blur/shrink until only shape and color remain; the page must stand out, or return to step 3 (report if peers couldn't be captured).
- **Nothing broke.** Existing tests/build pass; both widths render with zero console errors, no horizontal overflow, and no lost real content.
- **The floor holds.** Contrast, tap targets, focus states, and heading order are no worse than baseline.

Report what you removed, what you kept and why, and any tells blocked on a user decision.
