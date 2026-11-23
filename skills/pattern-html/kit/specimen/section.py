#!/usr/bin/env python3
from draw import *

d = Drawing(600, 262, "Section through one screw that holds a Smoke sheet to the frame, six times size")
d.ground()
v = d.view(74, 78, 6)

LIP, SHEET = 10.0, 3.0
edge = LIP + 0.4
axis = edge + 9.0
run_on = 46.0

v.cut([(2, 0), (LIP, 0), (LIP, SHEET), (32, SHEET), (32, 15), (LIP, 15), (LIP, 24), (0, 24), (0, 2)])
v.datum(LIP, 0, run_on + 4, 0)

smoke = dict(fill="#9BA0A8", stroke="#C9CCD1", sw=0.3, extra='fill-opacity="0.55"')
v.poly([(edge + 0.5, 0), (axis - 3, 0), (axis - 3, SHEET), (edge + 0.5, SHEET), (edge, SHEET - 0.5), (edge, 0.5)], **smoke)
v.rect(axis + 3, 0, run_on - axis - 3, SHEET, **smoke)

v.rect(axis - 2.3, SHEET, 4.6, 5.7, "#70757D", "#A9AEB6")
v.rect(axis - 1.5, -1, 3.0, 10.0, SCREW, EDGE)
v.rect(axis - 3.5, -1, 7.0, 1.0, NEAR_BLACK, EDGE)
v.rect(axis - 2.75, -4, 5.5, 3.0, SCREW, EDGE)

v.line(run_on, -1.5, run_on, SHEET + 1.5, INK, 0.3)
v.line(-1.5, 24, LIP + 1.5, 24, INK, 0.3)

v.dim_h(edge, axis, -8, "9")

lx = 396.0
v.leader(axis + 2.75, -2.6, lx, 40, "M3 cap screw", "Black oxide · 2.5 mm hex")
v.leader(axis + 3.5, -0.5, lx, 66, "Washer", "Black nylon")
v.leader(40, 1.5, lx, 92, "Smoke", "6 mm hole · 9 mm from the edge")
v.leader(axis + 2.3, 6.4, lx, 118, "Heat set insert", "M3 × 5.7 in a 4.0 mm hole")
v.leader(28, 11, lx, 144, "Frame", "Satin · the darkest black")

v.detail(0, -3, "Outside")
v.detail(13, 21, "Inside")
d.caption(26, d.h - 22, "Section", "One screw through Smoke into the frame · 6 × size · sheet drawn 3 mm thick")
print(d.svg())
