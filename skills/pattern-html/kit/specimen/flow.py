#!/usr/bin/env python3
"""How a page is built: a diagram of an idea, so it takes no ground and no tones, only ink."""
from draw import *

d = Drawing(600, 150, "How the kit builds a page: template, stylesheet, images, and drawings go into build.py, one HTML file comes out, and check.py reads it")

bw, bh = 100.0, 30.0
x_in, x_build, x_out, x_check = 25.0, 171.0, 323.0, 475.0

# what goes in, stacked on the left
ins = [("Template", "Your words and slots"), ("Style.css", "Type and color"), ("Images", "Any you name"), ("Drawings", "Scripts that print SVG")]
for i, (name, sub) in enumerate(ins):
    y = 12 + i * 32
    d.block(x_in, y, bw, 26, name, sub)
    d.line(x_in + bw, y + 13, x_in + bw + 20, y + 13, INK, 0.3)
spine = x_in + bw + 20
d.line(spine, 12 + 13, spine, 12 + 3 * 32 + 13, INK, 0.3)

mid = 12 + (3 * 32 + 26) / 2
d.arrow(spine, mid, x_build, mid)
d.block(x_build, mid - bh / 2, bw, bh, "Build.py", "Fills every slot")
d.arrow(x_build + bw, mid, x_out, mid)
d.block(x_out, mid - bh / 2, bw, bh, "One HTML file", "Nothing beside it")
d.arrow(x_out + bw, mid, x_check, mid)
d.block(x_check, mid - bh / 2, bw, bh, "Check.py", "Both widths")
print(d.svg())
