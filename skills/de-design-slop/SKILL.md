---
name: de-design-slop
description: |
  Strip the AI design tells out of a website, so the page reads as deliberately designed
  instead of averaged out of training data. Use when a site looks AI generated or like
  design slop, or when another skill needs an existing page restyled.
---

# De-design-slop

Every AI design tell is one thing wearing different clothes: **the median**. A model asked for a page returns the average of every page it trained on, and that average has a look. Indigo gradient, Inter, three rounded cards, centered hero, soft shadow. None of it is a mistake. Each choice is individually defensible, which is exactly why it gives the page away. It is what a page looks like when nobody decided.

So [TELLS.md](TELLS.md) is a starting set, not the boundary. The general detector is the **median test**, and it catches tells the catalogue never listed:

> For any choice on the page, ask what a model with no brief would have picked. If the page picked that, it is a tell.

**The trap is trading one median for another.** Indigo gradient to teal gradient, Inter to Space Grotesk, drop shadow to neon glow: lateral moves, still undecided, just less common for now. Space Grotesk and Instrument Serif were the recommended escape two years ago and are catalogued tells today. The median moves, so anything picked because it is currently fashionable moves with it. A replacement holds only when it is **sourced**: traceable to something true about this business that a competitor could not claim.

Words are a separate job with its own skill. Work the design here, and hand the copy to `humanize`.

## 1. See the page

Render it. Tells live in things source does not show: the rhythm of the spacing, the sameness of the cards, the glow behind the hero.

Screenshot every distinct page at a desktop and a phone width, using whatever browser driver the project already has (Playwright, Puppeteer) or one you can run headless. Where no browser is reachable, read the stylesheet and the markup and say so in your inventory, because a source-only pass will miss the visual tells.

**Done when** you have looked at every distinct page and breakpoint, or named the ones you could not and why.

## 2. Inventory the tells

Walk [TELLS.md](TELLS.md) against what you saw, then apply the median test to everything it does not cover.

Separate a **tell** from a **convention**. A three column feature grid is a convention, and so is a nav with a CTA on the right. The tell is what the convention is wearing: three identical cards, each an emoji in a rounded square above a two line sentence of the same length. Conventions are load bearing and stay. Costume goes.

Record each hit as a file and line, so step 4 has somewhere to go.

**Done when** every entry in the catalogue has a verdict against this site, present with a location or absent, plus any median choices you found that the catalogue does not list.

## 3. Source a direction

A page reverts to the median when fixes are made one at a time. Decide the whole direction first, from the site's own material.

Read what the business actually is: its copy, its README, its docs, its product, its customers, what it sells and to whom. Look for the material a design can be built out of. The trade it works in, the tool its customers hold, the era it belongs to, a real photograph, a real number, the physical thing behind the software. Ask the user for anything the repo cannot tell you.

Then commit to one direction and write it down as concrete tokens: type (display and body), palette (one dominant, one neutral, one accent), radius, spacing scale, elevation, motion. Every token traces to the material. "Warm cream, Instrument Serif" is not a direction, it is a mood board of the current median. "The palette is the safety yellow and machine grey of the equipment their customers already own" is a direction.

Put it in `DESIGN.md` at the project root when the site lives in a repo, so the next generated page starts from the direction instead of the median.

Show the user the direction and confirm it before touching a stylesheet. It is their brand, and a wrong direction wastes every edit after it. Collect the sites they measure themselves against in the same breath, since step 5 needs them for the lineup.

**Done when** one direction is written down, every token traces to something true about this business, and the user has confirmed it.

## 4. Strip, loudest first

Work down from the tells that carry the most signal: palette, then type, then surface effects, then card and layout treatment, then icons, imagery, motion.

**Reach for deletion first.** Most tells are decoration doing no work, and the fix is removing the gradient, the glow, the grid lines, the badge above the headline, the icon tile. Restraint reads as decided. A cleverer ornament in the same slot is the median again with a new accent.

Change tokens, not components. Edit the CSS variables, the Tailwind theme, or the theme file so the fix holds everywhere. A per component override is a signal you are patching a symptom the token still generates.

Substance stays. Where a section is real but its presentation is a tell, restyle it. Where the content itself is invented, a fabricated testimonial or a stock logo wall, say so and take it out rather than restyling a lie. Never quietly delete real content because its wrapper looked generic.

**Done when** every tell marked present is either gone or kept with a stated reason, and none is silently left.

## 5. Prove it

Three checks, all of them:

- **The lineup.** Screenshot the peer sites from step 3, stand the page beside them, and shrink the row small or blur it until only shape and colour survive. The page passes when you can pick it out. If it still hides in the row, the direction was not sourced, so return to step 3. Where the peers cannot be captured, say the lineup went unrun rather than reporting a verdict you did not see.
- **Nothing broke.** The project's own tests and build pass, the page renders at both widths with no console errors, no horizontal overflow, and no content lost against the diff.
- **The floor holds.** Contrast, tap targets, focus states, and heading order are no worse than when you started. Distinctive and unreadable is a worse page, not a better one.

**Done when** all three pass and you can name the element that makes the page pick itself out.

Report what you removed, what you kept and why, and the tells you could not fix without a decision only the user can make.
