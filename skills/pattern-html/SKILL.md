---
name: pattern-html
description: Style new standalone personal HTML deliverables (reports, boards, tools, Artifacts) with Justin's Pattern kit. Skip employer/client work, existing apps, and HTML email.
---

# Pattern HTML

**Pattern** is Justin's design language, based on reference board 01, which he approved on 2026 10 01.
The kit implements the look recorded in `~/dev/design/decisions.md`.
Where the kit and a decision disagree, the decision wins and the kit gets fixed.

`kit/` sits beside this file. Commands below write its path as `KIT`.

## Scope

Pattern is the default look for a new standalone personal HTML deliverable: a report, a reference board, a dashboard, a gallery, a tool, or an HTML Artifact.
Use the kit for the deliverable's visual design, including the templates and figures that give it that look.
Other skills can still supply its content and structure.
A look Justin specifies takes precedence.

- **Employer or client work** uses the organization's brand, even when Justin is the first reader.
- **Existing sites and apps, and routine edits to HTML-generating code** keep their current style.
- **HTML email** uses its own styling by default.
  If Justin explicitly requests Pattern for an email, use token colors inline and let the fonts fall back instead of using the page kit.
  Note the fallback at handover.

## 1. Start from the kit

Copy a starter into the project as `NAME.tmpl.html`, with a `fig/` folder beside it for images: `KIT/page.tmpl.html` for a page to read, `KIT/tool.tmpl.html` for a page to use. The template is the source. Every later change goes into it, followed by a rebuild.

A template or script that writes pages of its own keeps its slots and takes the look from `{{kit:style.css}}` in its `<style>`. An app that serves its own CSS takes the stylesheet that step 5 writes.

Settle three things before writing: the page's **name** (one to three words), its **job** (one sentence), and its **ask** (the one thing it wants from Justin, or that it wants nothing).

**Done when** the template sits beside its `fig/` folder and the name, the job, and the ask are settled.

## 2. Write it with the kit's parts

`KIT/specimen.tmpl.html` holds every part once, with its markup. Take markup from there. Read the reference for each branch the page reaches:

- A photograph or a screenshot, with or without pins and notes: [FIGURES.md](FIGURES.md)
- A drawing of a thing, a section, a diagram of an idea, or a chart: [DIAGRAMS.md](DIAGRAMS.md)
- Buttons, fields, a live result, or an app that serves its own CSS: [CONTROLS.md](CONTROLS.md)

A part the specimen lacks is composed from the tokens in a second `<style>` in the template: `--ground`, `--ink`, `--muted`, `--rule`, `--act`, `--ok`, `--caution`, `--fault`, and the two faces `--mark` and `--read`.

**Done when** every part on the page comes from the specimen or from the tokens, and **The look** and **Words** below hold for all of it.

## 3. Build

```
python3 KIT/build.py NAME.tmpl.html NAME.html
```

The build fills every placeholder and writes one file with its fonts, images, and drawings inside it. The docstring at the top of `KIT/build.py` lists the placeholders. Anything else in double braces passes through for another tool to fill.

**Done when** the build prints the output's path and size.

## 4. Check, then read

```
python3 KIT/check.py NAME.html --shots DIR
```

The check opens the page at 1280 and at 390 wide, tests it against the look, and photographs it in slices into `DIR`. A FAIL is a broken rule: fix it. A WARN is probably wrong: fix it, or keep it with a reason you can state. A NOTE is yours to judge.

Then Read every slice, because a page can pass every rule and still look wrong. Look for lettering that touches a line or other lettering, a pin off its target, a drawing too small to read, and text past its frame.

**Done when** the check prints PASS, every WARN is fixed or has its reason, and every slice has been read since the last build.

## 5. Hand it over

- **A file.** Give the built page's path and its link on Justin's private network, which his MacBook serves: in `~/dev/workshop`, `just share PATH` links the page into the share and prints the link. Pass a name after the path when the file's own name says little. A rebuilt page keeps its link, and `just unshare NAME` takes one down. The workshop's `docs/infrastructure.md` covers the share.
- **An Artifact.** `python3 KIT/build.py --artifact NAME.tmpl.html NAME.artifact.html` leaves off the document skeleton, which the Artifact tool adds itself. Run step 4 on that file, then load `artifact-design` for the publish contract. The kit meets it as a page that commits to one dark look.
- **An app that serves its own CSS.** `python3 KIT/build.py --css OUT.css` writes the stylesheet with its fonts inside. [CONTROLS.md](CONTROLS.md) covers the rest.

A page that holds someone else's photographs or film images stays a local file, shared on his private network only. It never becomes an Artifact or a doc, and it never enters a public repo.

**Done when** Justin has the path or the link, and the reply says in one line what the page asks of him.

## The look

- **Two faces, split by job.** Routed Gothic in capitals for marks and titles: `h1` to `h4`, `.kicker`, `.tag`, `.figno`, `dt`, `th`, and the lettering in a drawing. JetBrains Mono in mixed case for anything read at length or updated live. The stylesheet sets the capitals, so write titles in sentence case.
- **Ink on one ground.** `--ink` for everything read, `--muted` for the second voice (credits, dates, asides), and `--rule` for lines only.
- **One Act.** Yellow is one 2 px line on the one thing the page asks for: `.ask` on a page to read, `.act` on the primary button of a page to use, once per page. A page that asks nothing has no yellow.
- **States show their word.** Green, yellow, and red appear only as `.state.ok`, `.state.caution`, and `.state.fault`, lettered OK, CAUTION, and FAULT. The detail goes in the sentence beside the state.
- **Square and flat.** Square corners and 1 px rules. A part stands out by its frame, or by a fill of ink.
- **One file.** Everything the page needs travels inside it, so it opens anywhere and looks the same.
- **Every mark is true.** A number, a part name, or a state on the page is real. A sample says that it is a sample.

## Words

- `h1` is the page's name in one to three words. The sentence that explains it goes in `.sub`.
- `<title>` is a name of two to four words.
- `.kicker` says whose page it is and what kind: `Pattern 26 · Reference board 01`.
- `.status` opens with the date written as `2026 10 01`, then says where the page stands in one line.
- Sections are numbered: `<h2><span class="n">01</span>Name</h2>`.
- ` · ` separates the parts of a line.
- Between words, a comma, a period, a colon, or parentheses does the work a dash would. A hyphen belongs inside a true compound word, an official designation such as MIL-STD-810H, or code.
- `header` and `footer` appear once each.

## Glyph traps

The check's `glyph` WARN catches each of these. Writing them right the first time saves a round.

- Routed Gothic has no ellipsis, no Greek, and none of ≤ ≥ ≈ ✓. Anything set in capitals spells them out: "at most", "about", "ohm".
- Capitals turn µ into a Greek letter the face lacks. Keep µ in reading text, or in a drawing label, which `draw.py` leaves as written.
- JetBrains Mono has no ⌀. Write Ø.
- Routed Gothic's 1 and 0 read close to I and O. A figure that has to be read exactly goes in reading text, and `.nb` keeps it on one line.

## Beside other skills

When Pattern applies, `de-design-slop` and `artifact-design` defer to its dark ground, monospace reading face, tracked capitals, numbered sections, and 1 px rules.
Justin recorded those decisions on 2026 09 24.

## Keeping the kit

- Part 1 of `KIT/style.css` is the approved stylesheet, word for word. It changes only when a decision in `decisions.md` changes.
- A part that a second page would need goes into Part 2, with a sample in `KIT/specimen.tmpl.html` tagged New.
- After any change to the kit, rebuild and check `specimen.tmpl.html` and `tool.tmpl.html`, read their slices, and run `python3 KIT/regress.py`. It redraws the approved page with the kit and compares the two slice by slice, and it has to print PASS.
- The specimen and the tool page that Justin reads are built copies in `~/dev/design/specimen/`. After a change to the kit, `sh ~/dev/design/specimen/build.sh` refreshes them.
- `KIT/fonts/README.md` covers adding a character to a face.
- The repo that holds this skill is public, so the kit carries only its own drawings and its own test card.
