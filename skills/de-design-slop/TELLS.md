# The catalogue

Walk this against the page, loudest section first. Each entry is a median choice: what a model reaches for when it has no brief. Presence is not proof on its own, since any one of these can be the right call for a particular page. A stack of them is what gives a page away.

**This list goes stale.** The median moves as the escape routes get crowded, which is why half the fonts below were the recommended fix two years ago. Add what you find, and treat the median test in `SKILL.md` as the real detector.

## Colour

- **Indigo to violet gradient.** The loudest tell there is. Tailwind `indigo-500`, `violet-500`, `purple-600` (v3 anchors `#6366f1`, `#8b5cf6`; v4 shifted the values, same family). It traces to Tailwind UI defaulting every button to `bg-indigo-500`, which Adam Wathan has publicly apologised for, and which then flooded the tutorials the models trained on.
- **Violet to cyan on near black**, with the accent repeated as a glow.
- **Gradient text on the headline** (`bg-clip-text text-transparent`), which also wrecks scannability.
- **Gradient applied to large stat numbers.**
- **Radial glow or spotlight halo** behind a dark hero.
- **Purple orbs or blurred blobs** floating behind the fold.
- **Warm cream or beige page background**, the current default "tasteful" surface and the second median.
- **Pure `#fff` and `#000`**, and pure black body text.
- **Monotone palette** with no dominant colour and no accent, or an accent used on everything.
- **Grey text on a coloured background.**

## Type

- **Inter.** The single most common tell, especially Inter with a system fallback and no other typographic decision anywhere.
- **The rest of the rotation:** Geist, Poppins, Space Grotesk, Plus Jakarta Sans, DM Sans, Satoshi, Instrument Serif, Playfair Display, Bricolage Grotesque. Note how many of these are prescribed as the cure for Inter. Reaching for one because it is the known escape is the same move as reaching for Inter.
- **One typeface doing headings, body, labels and buttons.**
- **A single italic serif word** dropped into a sans headline for "personality".
- **Tracked uppercase eyebrow** above the heading, and the **pill badge above the H1** ("✨ Introducing…").
- **Oversized full sentence hero headline** eating the first viewport.
- **Crushed tracking** applied globally, past the point where characters separate.
- **Flat hierarchy**, type steps too close to read as levels. Want a ratio of about 1.25 and up.
- **All caps for body length passages**, and decorative monospace worn as a costume.

## Surface and effect

- **Glassmorphism** used as decoration rather than to show layering.
- **Permanent dark mode** chosen by reflex rather than for the content.
- **Glowing coloured box shadows** standing in for borders.
- **Decorative grid lines or dot grid** over a surface that is not a canvas, map or measurement.
- **Repeating gradient stripes.**
- **A 1px hairline border and a wide diffuse shadow on the same element**, two separation methods doing one job.

## Card and border

- **A thick colour strip down one side of a rounded card.** Widely called the most recognisable single tell of generated UI. Shows up on feature grids, metrics and pricing callouts.
- **Untouched shadcn defaults**, `rounded-2xl shadow-lg p-6` repeated everywhere.
- **Radius past 24px**, which rounds cards into featureless blobs. 12 to 16px is the usable range.
- **One radius value on every element** regardless of size or role.
- **Cards inside cards inside cards.**
- **Flat 1px grey borders** on everything, where whitespace, a few percent of background lightness, or elevation would separate better.

## Layout and skeleton

- **The skeleton itself:** hero, logo wall, three cards, testimonials, three tier pricing, FAQ accordion, CTA band, four column footer, in that order. Recognisable before a single pixel is read.
- **Everything centered**, hero and subhead and section headings alike, with no asymmetry anywhere.
- **Exactly three feature cards**, equal width, equal height, copy padded to equal length.
- **Perfect 2x2 or 3x3 symmetry.**
- **Numbered step rows**, 01 02 03 beside the headings.
- **Horizontal stat banner:** one big number, small label, three across.
- **A bento grid** used because bento grids are what pages have now.
- **Monotonous spacing**, the same `py-24` on every section, so nothing groups and nothing separates.
- **Line length past 80 characters.** 65 to 75 reads better.

## Icon and imagery

- **Emoji as functional icons.** 🚀 for speed, 💡 for smart, ✨ for premium. The fastest possible path from generation to deploy, and they do not scale, inherit colour, or survive dark mode.
- **Lucide or Heroicons at default stroke**, one centered in a rounded square tile above each card heading.
- **Floating 3D abstract blobs**, plastic over-smooth illustration, Stripe style isometric scenes.
- **Stock photography of a diverse group at laptops in a bright office.**
- **AI generated people**, flawless skin, glassy eyes, symmetric faces.
- **Shape assembled SVG** that reads as clip art, or a crude hand coded mascot.
- **Broken or placeholder images**, empty `src`, missing files.

## Motion

- **The same fade up on every section** as it scrolls in.
- **`transition: all`.**
- **Bounce or elastic overshoot** on dialogs and cards. Ease out quart, quint or expo instead.
- **A pulsing status dot** that reports nothing, and a blinking cursor faking a terminal in non editable copy.
- **Auto scrolling logo marquee** the reader cannot stop.
- **Inert hover states**, and buttons that snap instead of easing.
- **Animating width, height, padding or margin** rather than transform and opacity.

## Content shaped tells

These are content problems wearing design clothes. Fix the content, do not restyle it.

- **Fabricated testimonials**, statistically common names (Sarah Johnson, Michael Brown, Alex Miller) with vague titles, praising a workflow transformation.
- **A "trusted by" logo wall** of companies that are not customers.
- **Vague aspirational headline.** "Build the future", "Your all-in-one platform", "Scale without limits". Compare Stripe's "Financial infrastructure for the internet" or Linear's "Plan and build products", both of which could not belong to anyone else.
- **The same filler sentence repeated** across card slots.
- **Placeholder survivors:** lorem ipsum, "Your Company", `hello@example.com`.
- **Curly quotes** pasted straight out of a chat window into copy that is otherwise straight quoted.

Buzzwords, em dash cadence and rule of three belong to `humanize`, not here.

## The floor

Not tells, and not what makes a page generic, but they cluster with the tells and the same pass should clear them. A distinctive page that fails these is a worse page than the one you started with.

- Contrast under WCAG AA, 4.5:1 body and 3:1 large. APCA `Lc` 75 body, 45 large, 30 for non text UI.
- Body text under 14px, 16 is the target. Functional text under 11px.
- Line height under 1.3, where body wants 1.5 to 1.7. Letter spacing over 0.05em on body.
- Padding under 8px from a container edge, 12 to 16 reads right. Body text flush to the viewport edge.
- Justified text with no hyphenation.
- Skipped heading levels.
- Content stuck invisible at rest because reveal code left it at opacity 0.
- Uncaught script errors on load, and `overflow: hidden` clipping tooltips and menus.
- Horizontal overflow at any breakpoint.

## Sources

Refresh this catalogue from the current discourse when it starts to feel dated.

- [Impeccable, Slop](https://impeccable.style/slop/), a taxonomy of roughly sixty patterns, the backbone of the sections above
- [925 Studios, AI slop design tells](https://www.925studios.co/blog/ai-slop-design-tells) and [the full guide](https://www.925studios.co/blog/ai-slop-web-design-guide), source of the lineup test
- [Vibecodekit, AI slop design](https://vibecodekit.dev/ai-slop-design)
- [Why your AI keeps building the same purple gradient website](https://prg.sh/ramblings/Why-Your-AI-Keeps-Building-the-Same-Purple-Gradient-Website), on the mechanism
- [Sikora, Top 10 signs a website was built by AI](https://sikora.software/blog/ai-website-design)
- [SmoothUI, AI design slop](https://smoothui.dev/blog/ai-design-slop)
