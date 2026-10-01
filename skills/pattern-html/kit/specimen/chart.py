#!/usr/bin/env python3
"""Two charts of the page's own contrast, drawn to show the chart style: ink on the page, no color.

Every value is worked out here from the colors in style.css, so the charts cannot drift from the page.
"""
import re
from pathlib import Path

from draw import *

css = (Path(__file__).resolve().parent.parent / "style.css").read_text(encoding="utf-8")
TOKEN = dict(re.findall(r"--(ground|ink|muted|rule|act|ok|fault):\s*(#[0-9A-Fa-f]{6})", css))


def light(color):
    """Relative luminance, as WCAG 2.2 defines it."""
    c = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    x, y = light(a), light(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def grey(g):
    return "#%02X%02X%02X" % (g, g, g)


d = Drawing(600, 236, "Two charts. Left: the contrast of grey lettering on the ground and on ink, as the grey goes "
                      "from black to white. Right: the contrast of each of the page's colors on the ground")

# ---- lines: one scale for both, a name at the end of each ----
x0, x1, y0, y1 = 44.0, 300.0, 190.0, 28.0          # the plot's left, right, bottom, and top


def X(g):
    return x0 + g / 255 * (x1 - x0)


def Y(r):
    return y0 - (r - 1) / 20 * (y0 - y1)


d.line(x0, y1, x0, y0, INK, 0.3)
d.line(x0, y0, x1, y0, INK, 0.3)
for r in (1, 4.5, 7, 10, 15, 20):
    d.line(x0 - 2.4, Y(r), x0, Y(r), INK, 0.3)
    d.num(x0 - 4.5, Y(r) + 1.6, f"{r:g}", anchor="end")
for g in (0x00, 0x40, 0x80, 0xC0, 0xFF):
    d.line(X(g), y0, X(g), y0 + 2.4, INK, 0.3)
    d.num(X(g), y0 + 8.6, "%02X" % g, anchor="middle")
for r, name in ((4.5, "Reading text"), (7, "Strictest")):
    d.datum(x0, Y(r), x1, Y(r))                    # a level to clear is a dashed line with its name on it
    d.text(x1, Y(r) - 2.6, name, 4.2, INK, "end", extra='opacity="0.85"')

greys = range(0, 256, 3)
d.run([(X(g), Y(ratio(grey(g), TOKEN["ground"]))) for g in greys], INK, 1.0)
d.run([(X(g), Y(ratio(grey(g), TOKEN["ink"]))) for g in greys], INK, 0.6, 'stroke-dasharray="3.2 2"')
d.text(x1 + 5, Y(ratio(grey(255), TOKEN["ground"])) + 1.9, "On ground")
d.text(x0 + 7, Y(ratio(grey(0), TOKEN["ink"])) - 5, "On ink")

# ---- bars: a frame each, and the one the chart is about filled ----
bx, by, pitch, tall, unit = 404.0, 40.0, 22.0, 10.0, 8.0    # bars start here; row pitch; bar height; width of 1 of ratio


def BX(r):
    return bx + (r - 1) * unit


bars = sorted(((ratio(TOKEN[n], TOKEN["ground"]), n) for n in ("ink", "muted", "rule", "act", "ok", "fault")), reverse=True)
foot = by + len(bars) * pitch - (pitch - tall) + 6
d.datum(BX(4.5), by - 6, BX(4.5), foot)
d.text(BX(4.5), by - 9, "Reading text", 4.2, INK, "middle", extra='opacity="0.85"')
for i, (r, name) in enumerate(bars):
    y = by + i * pitch
    d.text(bx - 6, y + tall / 2 + 1.95, name, 5.4, INK, "end")
    d.rect(bx, y, BX(r) - bx, tall, INK if name == "ink" else GROUND, INK, 0.3)
    d.num(BX(r) + 3, y + tall / 2 + 1.6, f"{r:.2f}")
d.line(bx, foot, BX(21), foot, INK, 0.3)
for r in (1, 4.5, 7, 15, 20):
    d.line(BX(r), foot, BX(r), foot + 2.4, INK, 0.3)
    d.num(BX(r), foot + 8.6, f"{r:g}", anchor="middle")

d.caption(x0, 214, "Grey lettering", "Contrast ratio by the grey of the lettering, black to white")
d.caption(bx - 26, 214, "The page's colors", "Each on the ground · filled: the color text is set in")
print(d.svg())
