#!/usr/bin/env python3
"""Front and side of a test box, drawn to show the drawing style. It is not a product."""
from draw import *

W, H, D = 260.0, 140.0, 120.0     # the box
LIP = 10.0                        # frame width around each opening
ox, oy = 60.0, 40.0               # front view origin
sx = ox + W + 84.0                # side view origin
base = oy + H

d = Drawing(600, 228, "Front and side views of a black test box: a frame carrying a Smoke panel and an off black panel")
d.ground(base=base)

# ---- front ----
d.cham(ox, oy, W, H, 2, FRAME)

# Smoke panel: what is inside shows as soft shapes
lx, ly, lw, lh = ox + LIP, oy + LIP, 150.0, H - 2 * LIP


def inside():
    # the ledge the sheet sits on, seen through it
    d.add(f'<path d="M{lx},{ly}h{lw}v{lh}h{-lw}z M{lx + 14},{ly + 14}v{lh - 28}h{lw - 28}v{-(lh - 28)}z" '
          f'fill="#020202" fill-rule="evenodd"/>')
    bx, by = lx + 24, ly + 22
    d.rect(bx, by, 102, 56, "#1B1D20", "#4A4E55", 0.5)                    # board, matte black soldermask
    for px, py in ((bx + 5, by + 5), (bx + 97, by + 5), (bx + 5, by + 51), (bx + 97, by + 51)):
        d.circle(px, py, 2.6, "#050506", "#5A5E66", 0.4)                   # standoffs
    d.rect(bx + 14, by + 9, 30, 24, "#050506", "#6A6F77", 0.5)             # module
    d.rect(bx + 52, by + 9, 20, 20, "#2B2E33", "#7A7F87", 0.5)             # heat sink
    for i in range(6):
        d.line(bx + 54, by + 11.5 + i * 3.0, bx + 70, by + 11.5 + i * 3.0, "#5E636B", 0.7)
    for i in range(8):
        d.rect(bx + 14 + i * 5, by + 41, 2.6, 8, "#8F949C", "none", 0)     # header pins
    for i, n in enumerate((24, 17, 21, 11)):
        d.line(bx + 52, by + 35 + i * 2.4, bx + 52 + n, by + 35 + i * 2.4, "#C9CCD1", 0.5)       # white silkscreen
    d.lamp(bx + 88, by + 16, OK, behind=True)
    d.rect(lx + 86, ly + 86, 40, 16, "#15171A", "#565A62", 0.5)            # supply
    # wiring: straight and square, black and red
    d.run([(lx + 34, by + 56), (lx + 34, ly + 98), (lx + 86, ly + 98)], "#C0272D")
    d.run([(lx + 42, by + 56), (lx + 42, ly + 90), (lx + 86, ly + 90)], "#020202")


d.smoke(lx, ly, lw, lh, inside)
for px in (lx + 9, lx + lw / 2, lx + lw - 9):
    for py in (ly + 9, ly + lh - 9):
        d.screw(px, py, washer=True)

# off black panel
rx, ry, rw, rh = lx + lw + LIP, oy + LIP, W - 3 * LIP - lw, H - 2 * LIP
d.rect(rx, ry, rw, rh, PANEL, EDGE_D)
for px in (rx + 7, rx + rw - 7):
    for py in (ry + 7, ry + rh - 7):
        d.screw(px, py)
lamp = (rx + rw / 2, ry + 44)
d.mark(lamp[0], lamp[1] - 8, "OK")
d.lamp(*lamp)
ux, uy = rx + rw / 2 - 6, ry + 78
d.mark(ux + 6, uy - 3, "USB C")
d.add(f'<rect x="{ux}" y="{uy}" width="12" height="5" rx="2.5" fill="#000" stroke="{EDGE}" stroke-width="0.3"/>')

# ---- side ----
d.cham(sx, oy, D, H, 2, FRAME)
px0, py0, pw, ph = sx + LIP, oy + LIP, D - 2 * LIP, H - 2 * LIP
d.rect(px0, py0, pw, ph, PANEL, EDGE_D)
for px in (px0 + 7, px0 + pw - 7):
    for py in (py0 + 7, py0 + ph / 2, py0 + ph - 7):
        d.screw(px, py)

# ---- captions and tags ----
d.caption(ox - 3, base + 20, "Front", "Test box · 260 × 140 × 120 mm · drawn to show the style, not a product")
d.caption(sx - 3, base + 20, "Side")
d.tag(1, ox - 26, oy + 30, ox + 5, oy + 30)                  # frame
d.tag(2, ox - 26, ly + lh - 30, lx + 22, ly + lh - 30)       # Smoke
d.tag(3, lx + lw / 2, oy - 20, lx + lw / 2, ly + 5.4)        # screw on a washer
d.tag(4, rx + rw + 36, ry + 96, rx + rw - 14, ry + 96)       # panel
d.tag(5, rx + rw + 36, lamp[1], lamp[0] + 4.6, lamp[1])      # light
print(d.svg())
