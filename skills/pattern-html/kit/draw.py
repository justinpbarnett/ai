#!/usr/bin/env python3
import hashlib
import math

from tokens import tokens

__all__ = [
    "Drawing", "INK", "MUTED", "GROUND", "ACT", "OK", "CAUTION", "FAULT", "WALL", "BENCH",
    "FRAME", "PANEL", "EDGE", "EDGE_D", "SCREW", "NEAR_BLACK", "FONT", "READ", "CAP", "PAGE",
]

PAGE = tokens()
INK = PAGE["ink"]
MUTED = PAGE["muted"]
GROUND = PAGE["ground"]
ACT = PAGE["act"]     # one line at the touch point, never a face
OK = PAGE["ok"]
CAUTION = PAGE["caution"]
FAULT = PAGE["fault"]
OK_HIGHLIGHT = "#B9F5CF"
OK_RIM = "#062B14"

# things, in tones pushed apart so black on black reads on a screen
WALL = "#5C5F62"
BENCH = "#141518"
FRAME = "#0D0E10"
PANEL = "#1D1F23"
EDGE = "#3A3D43"
EDGE_D = "#24262A"
SCREW = "#060607"
NEAR_BLACK = "#050506"
DETAIL_SIZE = 4.2
DETAIL_OPACITY = 'opacity="0.85"'

FONT = "'Routed Gothic', 'DIN Alternate', 'Arial Narrow', sans-serif"
READ = "'JetBrains Mono', ui-monospace, 'DejaVu Sans Mono', monospace"
CAP = 0.71875         # Routed Gothic's capital height as a share of its font size

HATCH = {
    "a": (3.2, 45, "#30333A", 0.7),
    "b": (2.2, -45, "#34373E", 0.6),
}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def caps(s):
    # the micro sign's capital is a Greek letter the face lacks
    return "".join(c if c == "\u00b5" else c.upper() for c in str(s))


def darker(color, share=0.2):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % (round(r * share), round(g * share), round(b * share))


class Space:
    def __init__(self, sheet, x0=0.0, y0=0.0, k=1.0):
        self.sheet = sheet
        self.x0, self.y0, self.k = float(x0), float(y0), float(k)

    def P(self, x, y):
        return (self.x0 + self.k * x, self.y0 + self.k * y)

    def view(self, x0, y0, k):
        px, py = self.P(x0, y0)
        return Space(self.sheet, px, py, self.k * k)

    def add(self, s):
        self.sheet.out.append(s)


    def rect(self, x, y, w, h, fill, stroke=EDGE, sw=0.3, extra=""):
        px, py = self.P(x, y)
        self.add(f'<rect x="{px:.2f}" y="{py:.2f}" width="{self.k * w:.2f}" height="{self.k * h:.2f}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>')

    def poly(self, points, fill, stroke=EDGE, sw=0.3, extra=""):
        pts = " ".join("%.2f,%.2f" % self.P(x, y) for x, y in points)
        self.add(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
                 f'stroke-linejoin="miter" {extra}/>')

    def cham(self, x, y, w, h, c, fill, stroke=EDGE, sw=0.3, extra=""):
        self.poly([(x + c, y), (x + w - c, y), (x + w, y + c), (x + w, y + h - c),
                   (x + w - c, y + h), (x + c, y + h), (x, y + h - c), (x, y + c)], fill, stroke, sw, extra)

    def line(self, x1, y1, x2, y2, stroke=INK, sw=0.25, extra=""):
        (ax, ay), (bx, by) = self.P(x1, y1), self.P(x2, y2)
        self.add(f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{bx:.2f}" y2="{by:.2f}" '
                 f'stroke="{stroke}" stroke-width="{sw}" {extra}/>')

    def run(self, points, stroke, sw=2.0, extra=""):
        pts = " ".join("%.2f,%.2f" % self.P(x, y) for x, y in points)
        self.add(f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{sw}" '
                 f'stroke-linejoin="miter" {extra}/>')

    def circle(self, x, y, r, fill, stroke="none", sw=0.3, extra=""):
        px, py = self.P(x, y)
        self.add(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{self.k * r:.2f}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}" {extra}/>')


    def text(self, x, y, s, size=5.4, fill=INK, anchor="start", extra="", spacing=0.12):
        px, py = self.P(x, y)
        self.add(f'<text x="{px:.2f}" y="{py:.2f}" font-family="{FONT}" font-size="{size:.3f}" fill="{fill}" '
                 f'text-anchor="{anchor}" letter-spacing="{spacing}em" {extra}>{esc(caps(s))}</text>')

    def detail(self, x, y, s, anchor="start", fill=INK):
        self.text(x, y, s, DETAIL_SIZE, fill, anchor, extra=DETAIL_OPACITY)

    def mark(self, x, y, s, cap=3.0, anchor="middle", fill=INK, spacing=0.12):
        self.text(x, y, s, cap * self.k / CAP, fill, anchor, spacing=spacing)

    def num(self, x, y, s, size=4.6, fill=INK, anchor="start", extra=""):
        px, py = self.P(x, y)
        self.add(f'<text x="{px:.2f}" y="{py:.2f}" font-family="{READ}" font-size="{size:.3f}" fill="{fill}" '
                 f'text-anchor="{anchor}" {extra}>{esc(s)}</text>')


    def screw(self, x, y, size=3, washer=False):
        head, hexr, wash = {3: (2.75, 1.45, 3.6), 4: (3.5, 1.73, 4.5)}[size]
        if washer:
            self.circle(x, y, wash, NEAR_BLACK, EDGE_D, 0.25)
        self.circle(x, y, head, SCREW, EDGE, 0.3)
        self.poly([(x + hexr * math.cos(math.radians(a)), y + hexr * math.sin(math.radians(a)))
                   for a in range(0, 360, 60)], "#000", EDGE_D, 0.2)

    def lamp(self, x, y, color=OK, behind=False):
        if behind:
            self.circle(x, y, 5.5, color, extra='opacity="0.35"')
            self.circle(x, y, 2.1, OK_HIGHLIGHT if color == OK else INK)
        else:
            self.circle(x, y, 4.4, color, extra='opacity="0.28"')
            self.circle(x, y, 2.0, color, OK_RIM if color == OK else darker(color), 0.3)

    def smoke(self, x, y, w, h, internals=None):
        sheet = self.sheet
        (px, py), pw, ph = self.P(x, y), self.k * w, self.k * h
        clip = sheet.uid("clip")
        sheet.defs.append(f'<clipPath id="{clip}"><rect x="{px:.2f}" y="{py:.2f}" width="{pw:.2f}" height="{ph:.2f}"/></clipPath>')
        self.add(f'<g clip-path="url(#{clip})">')
        self.rect(x, y, w, h, "#08090A", "none", 0)
        if internals:
            self.add(f'<g filter="url(#{sheet.soft()})">')
            internals()
            self.add("</g>")
        self.rect(x, y, w, h, "#A3A8AF", "none", 0, 'opacity="0.27"')
        self.add("</g>")
        self.rect(x, y, w, h, "none", EDGE, 0.3)

    def shadow(self, x, y, w, h):
        (px, py), pw, ph = self.P(x, y), self.k * w, self.k * h
        for bx, by in ((px + pw, py + 0.5), (px + 0.5, py + ph)):
            self.add(f'<line x1="{px + 0.5:.2f}" y1="{py + 0.5:.2f}" x2="{bx:.2f}" y2="{by:.2f}" '
                     f'stroke="#000" stroke-width="1.0" opacity="0.8"/>')


    def cut(self, points, fill=FRAME, hatch="a"):
        self.poly(points, fill, EDGE, 0.35)
        self.poly(points, f"url(#{self.sheet.hatch(hatch)})", "none", 0)

    def datum(self, x1, y1, x2, y2):
        self.line(x1, y1, x2, y2, INK, 0.25, 'stroke-dasharray="2.2 1.6" opacity="0.7"')


    def tag(self, n, x, y, tx, ty):
        px, py = self.P(tx, ty)
        s = self.sheet
        s.add(f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{px:.2f}" y2="{py:.2f}" stroke="{INK}" stroke-width="0.22" opacity="0.75"/>')
        s.add(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="0.9" fill="{INK}"/>')
        s.add(f'<rect x="{x - 4.2:.2f}" y="{y - 4.2:.2f}" width="8.4" height="8.4" fill="{GROUND}" stroke="{INK}" stroke-width="0.3"/>')
        s.text(x, y + 1.85, str(n), 5.2, INK, "middle", spacing=0)

    def leader(self, x, y, lx, ly, label, sub=None, side="right"):
        px, py = self.P(x, y)
        s = self.sheet
        anchor = "start" if side == "right" else "end"
        ex = lx - 3 if side == "right" else lx + 3
        s.add(f'<line x1="{px:.2f}" y1="{py:.2f}" x2="{ex:.2f}" y2="{ly - 1.8:.2f}" stroke="{INK}" stroke-width="0.22" opacity="0.75"/>')
        s.add(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="0.9" fill="{INK}"/>')
        s.text(lx, ly, label, 5.4, INK, anchor)
        if sub:
            s.detail(lx, ly + 6.6, sub, anchor)

    def dim_v(self, x, y1, y2, label):
        (ax, ay), (bx, by) = self.P(x, y1), self.P(x, y2)
        s = self.sheet
        s.line(ax, ay, bx, by, INK, 0.3)
        for qx, qy in ((ax, ay), (bx, by)):
            s.line(qx - 2.4, qy, qx + 2.4, qy, INK, 0.3)
        s.text(ax + 4, (ay + by) / 2 + 1.7, label, 4.8, INK)

    def dim_h(self, x1, x2, y, label):
        (ax, ay), (bx, by) = self.P(x1, y), self.P(x2, y)
        s = self.sheet
        s.line(ax, ay, bx, by, INK, 0.3)
        for qx, qy in ((ax, ay), (bx, by)):
            s.line(qx, qy - 2.4, qx, qy + 2.4, INK, 0.3)
        s.text((ax + bx) / 2, ay - 3.2, label, 4.8, INK, "middle")


    def block(self, x, y, w, h, label, sub=None):
        self.rect(x, y, w, h, GROUND, INK, 0.3)
        (cx, cy) = self.P(x + w / 2, y + h / 2)
        s = self.sheet
        if sub:
            s.text(cx, cy - 1.4, label, 5.4, INK, "middle")
            s.detail(cx, cy + 5.4, sub, "middle")
        else:
            s.text(cx, cy + 1.95, label, 5.4, INK, "middle")

    def arrow(self, x1, y1, x2, y2):
        (ax, ay), (bx, by) = self.P(x1, y1), self.P(x2, y2)
        d = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / d, (by - ay) / d
        hx, hy = bx - ux * 3.6, by - uy * 3.6
        s = self.sheet
        s.line(ax, ay, hx, hy, INK, 0.3)
        s.add(f'<polygon points="{bx:.2f},{by:.2f} {hx - uy * 1.2:.2f},{hy + ux * 1.2:.2f} '
              f'{hx + uy * 1.2:.2f},{hy - ux * 1.2:.2f}" fill="{INK}"/>')


class Drawing(Space):
    def __init__(self, w, h, label, key=None):
        super().__init__(self)
        self.w, self.h, self.label = float(w), float(h), label
        self.out, self.defs = [], []
        self._pre = "d" + hashlib.sha1((key or label).encode("utf-8")).hexdigest()[:6]
        self._n = 0
        self._soft = None
        self._hatch = {}

    def uid(self, name):
        self._n += 1
        return f"{self._pre}{name}{self._n}"

    def soft(self):
        if not self._soft:
            self._soft = self.uid("soft")
            self.defs.append(f'<filter id="{self._soft}" x="-5%" y="-5%" width="110%" height="110%">'
                             '<feGaussianBlur stdDeviation="1.5"/></filter>')
        return self._soft

    def hatch(self, which="a"):
        if which not in self._hatch:
            step, turn, color, sw = HATCH[which]
            self._hatch[which] = self.uid("hatch")
            self.defs.append(
                f'<pattern id="{self._hatch[which]}" width="{step}" height="{step}" patternUnits="userSpaceOnUse" '
                f'patternTransform="rotate({turn})"><line x1="0" y1="0" x2="0" y2="{step}" stroke="{color}" '
                f'stroke-width="{sw}"/></pattern>')
        return self._hatch[which]

    def ground(self, base=None, wall=WALL):
        self.rect(0, 0, self.w, self.h, wall, "none", 0)
        if base is not None:
            self.rect(0, base, self.w, self.h - base, BENCH, "none", 0)
            self.line(0, base, self.w, base, "#000", 0.4)

    def caption(self, x, y, title, sub=None):
        self.text(x, y, title, 5.4, INK)
        if sub:
            self.detail(x, y + 9, sub)

    def svg(self):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w:g} {self.h:g}" '
                f'role="img" aria-label="{esc(self.label).replace(chr(34), "&quot;")}">')
        defs = ["<defs>" + "".join(self.defs) + "</defs>"] if self.defs else []
        return "\n".join([head] + defs + self.out + ["</svg>"])
