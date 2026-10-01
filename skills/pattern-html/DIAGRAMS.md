# Diagrams

A **drawing** is a Python script that builds one `Drawing` with `kit/draw.py` and prints one SVG. The build runs the script wherever the template says `{{draw:PATH}}`. Each kind of drawing has a script to start from in `kit/specimen/`:

| Kind | Ground | Start from |
|------|--------|------------|
| **A thing**, seen from outside | wall grey, with a bench under it | `front.py` |
| **A thing, cut through** | wall grey | `section.py` |
| **An idea**: a flow, a structure, a sequence | the page's own ground | `flow.py` |
| **A chart** of numbers | the page's own ground | `chart.py` |

A thing is drawn in black parts with a lighter edge and lettered in white capitals. An idea or a chart is ink lines on the page, with no wall and no tones.

The docstrings in `kit/draw.py` are the reference for every method. This file holds what they leave out.

## 1. Lay out the sheet

Copy the nearest specimen script beside the template and start from `Drawing(600, HEIGHT, LABEL)`. A sheet 600 units wide fills the page at about 1.9 px per unit. `LABEL` says what the drawing shows, for a reader who cannot see it.

Draw a thing in millimetres. `d.view(x0, y0, k)` gives a second space at another scale, for a detail drawn larger than life. Line weights, lettering, tags, and ticks are in sheet units and never scale with a view, so every drawing on a page carries the same line and the same letter.

Lettering sizes, in sheet units:

| Size | Job | Method |
|------|-----|--------|
| 5.4 | a name | `text()`, `caption()`, `block()`, `leader()` |
| 4.2 at 85 percent | a detail under a name | the same, as `sub` |
| 4.8 | a dimension's figure | `dim_h()`, `dim_v()` |
| 5.2 | a tag's number | `tag()` |
| 4.6 in the reading face | a chart's figure | `num()` |
| by cap height, in the thing's units | lettering on the thing itself | `mark()` |

Lettering never wraps, so count it before placing it. Capitals run about 0.72 of their size per character: 3.9 units at 5.4 and 3.0 at 4.2. A block 100 wide holds about 25 characters of name or 33 of detail. A figure set with `num()` runs 0.6 of its size per character.

**Done when** every part and every line of lettering has a place on the sheet that the count says it fits.

## 2. Draw

**A thing.**

- Tones stand for finishes: `FRAME` for satin, the darkest; `PANEL` for matte, a step lighter; `smoke()` for a Smoke sheet with soft shapes behind it. `EDGE` is the highlight every black part carries, and `EDGE_D` the quieter one for a part inside another. The tones are pushed apart so black on black reads on a screen. They are not paint values.
- `cham()` is the only edge break: a corner cut at 45 degrees.
- `screw()`, `lamp()`, and `shadow()` draw the small parts. Lettering on the thing goes through `mark()`.
- Name many parts with `tag()`: a numbered square on the sheet with a leader to the part, and a `ul.legend` under the drawing that names each number.
- Name a few parts with `leader()`: a written label with a detail under it. Stack the labels in one column, 26 apart, in the order the parts stack.
- A section cuts parts with `cut()`. Neighbouring parts take `hatch="b"` so the two read apart. `datum()` carries a plane on as a dashed line, and `dim_h()` and `dim_v()` put a figure between two ticks.
- `ACT` appears at most once, as one line at the point a hand goes. A status color appears only as a lit `lamp()` with its word lettered beside it.
- Every mark is true: a dimension, a part name, or a label on the drawing is a real value of the thing.

**An idea.** `block()` is a named box, `line()` and `run()` join boxes, and `arrow()` gives a direction. Keep every run square. Ink only.

**A chart.**

- One scale places every mark, tick, and label. Define `X()` and `Y()` once, as `chart.py` does, and compute every position through them from the data.
- Lines are told apart by weight, by dashes, and by a name at the end of each line. Color carries no meaning.
- A bar is a frame. The one bar the chart is about is filled with ink.
- A level to clear is a `datum()` with its name lettered on it.
- Tick values and bar values go through `num()`, which sets them in the reading face, where 1 and 0 cannot pass for I and O.
- Every label names a value the chart really reaches.
- The script runs in its own folder, so it can read a data file that sits beside it.

**Done when** the script prints one `<svg>` and every value on the drawing comes from the thing or from the data.

## 3. Place it

```html
<div class="mock wide">{{draw:PATH}}</div>
```

- `mock wide` holds the drawing at 960 px or more and lets a phone scroll it sideways. Every drawing with lettering takes it. A drawing with no lettering takes `class="mock"` and shrinks with the page.
- `{{draw:PATH#ARG}}` runs the script with `ARG` as its first argument, so one script can draw several views.
- A legend goes straight after the drawing:

```html
<ul class="legend">
  <li><span>1</span><div><b>Frame</b>Satin black, the darkest step.</div></li>
</ul>
```

- Two drawings on one page need different labels, or a `key` each, so their inner ids stay apart.
- `{{svg:PATH}}` inlines an SVG written by hand. Give it the same two faces and the token colors.

**Done when** the template names every drawing, and each lettered drawing sits in `mock wide`.

## 4. Look at it

```
python3 KIT/build.py --draw DRAWING.py OUT.html
python3 KIT/check.py OUT.html --shots DIR
```

That builds the drawing alone on a bare page. Read its 1280 slice. The bare page's phone slice is too small to judge, so judge the phone view in the built page.

**Done when**, in the slices, lettering stays clear of every line, part, and other lettering; every tag has its legend entry and every leader ends on its part; and in the built page at 390 the drawing reads by scrolling.
