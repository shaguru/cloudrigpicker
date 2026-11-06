# Small 2D drawing toolkit on top of Blender's gpu + blf modules.
# Shapes are collected into layers and flushed as a handful of batches per frame.

from collections import defaultdict
from math import atan2, cos, sin, pi, sqrt

import blf
import gpu
from gpu_extras.batch import batch_for_shader

TAU = 2 * pi


# ---------------------------------------------------------------- shape builders (convex polygons)

def circle(cx, cy, r, seg=None):
    seg = seg or max(14, min(64, int(r * 1.4)))
    return [(cx + r * cos(TAU * i / seg), cy + r * sin(TAU * i / seg)) for i in range(seg)]


def ellipse(cx, cy, rx, ry, seg=None):
    seg = seg or max(20, min(72, int(max(rx, ry) * 1.2)))
    return [(cx + rx * cos(TAU * i / seg), cy + ry * sin(TAU * i / seg)) for i in range(seg)]


def capsule(x1, y1, x2, y2, r, seg=None):
    seg = seg or max(8, min(24, int(r)))
    a = atan2(y2 - y1, x2 - x1)
    pts = []
    for i in range(seg + 1):
        t = a + pi / 2 + pi * i / seg
        pts.append((x1 + r * cos(t), y1 + r * sin(t)))
    for i in range(seg + 1):
        t = a - pi / 2 + pi * i / seg
        pts.append((x2 + r * cos(t), y2 + r * sin(t)))
    return pts


def rrect(x, y, w, h, r, seg=5):
    r = max(0.0, min(r, w / 2, h / 2))
    if r < 0.5:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -pi / 2), (x + w - r, y + h - r, 0),
                       (x + r, y + h - r, pi / 2), (x + r, y + r, pi)):
        for i in range(seg + 1):
            t = a0 + (pi / 2) * i / seg
            pts.append((cx + r * cos(t), cy + r * sin(t)))
    return pts


def rdiamond(cx, cy, r, round_=0.28):
    """Rounded diamond (square rotated 45 deg) whose tips sit r from the centre."""
    hs = r / sqrt(2)
    sq = rrect(-hs, -hs, 2 * hs, 2 * hs, hs * round_ * 2)
    c, s = cos(pi / 4), sin(pi / 4)
    return [(cx + px * c - py * s, cy + px * s + py * c) for px, py in sq]


def arc(cx, cy, r, a0, a1, seg=24):
    return [(cx + r * cos(a0 + (a1 - a0) * i / seg), cy + r * sin(a0 + (a1 - a0) * i / seg))
            for i in range(seg + 1)]


def point_in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------- colour helpers

def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3)) + ((a[3] if len(a) > 3 else 1.0),)


def with_alpha(c, a):
    return (c[0], c[1], c[2], a)


def rgba(c, a=1.0):
    return (c[0], c[1], c[2], c[3] if len(c) > 3 else a)


# ---------------------------------------------------------------- canvas

class Canvas:
    """Collects fills, lines and text, then draws them in layer order."""

    def __init__(self):
        self.fills = defaultdict(lambda: defaultdict(list))   # layer -> colour -> tri verts
        self.lines = defaultdict(lambda: defaultdict(list))   # layer -> (colour, width) -> seg verts
        self.texts = []

    def fill(self, poly, color, layer=0, aa=True):
        n = len(poly)
        if n < 3:
            return
        color = tuple(round(v, 4) for v in color)
        cx = sum(p[0] for p in poly) / n
        cy = sum(p[1] for p in poly) / n
        tris = self.fills[layer][color]
        for i in range(n):
            tris += [(cx, cy), poly[i], poly[(i + 1) % n]]
        if aa:  # a thin smooth outline in the same colour hides jagged edges
            self.outline(poly, color, 1.0, layer)

    def outline(self, poly, color, width, layer=0, closed=True):
        color = tuple(round(v, 4) for v in color)
        segs = self.lines[layer][(color, round(width, 2))]
        n = len(poly)
        last = n if closed else n - 1
        for i in range(last):
            segs += [poly[i], poly[(i + 1) % n]]

    def line(self, a, b, color, width, layer=0):
        self.outline([a, b], color, width, layer, closed=False)

    def text(self, x, y, s, size, color, align="L", layer=99):
        self.texts.append((x, y, s, size, color, align, layer))

    def flush(self, vw, vh):
        gpu.state.blend_set("ALPHA")
        fs = gpu.shader.from_builtin("UNIFORM_COLOR")
        ls = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        layers = sorted(set(self.fills) | set(self.lines) | {t[6] for t in self.texts})
        for L in layers:
            for color, verts in self.fills.get(L, {}).items():
                if not verts:
                    continue
                b = batch_for_shader(fs, "TRIS", {"pos": verts})
                fs.bind()
                fs.uniform_float("color", color)
                b.draw(fs)
            for (color, width), verts in self.lines.get(L, {}).items():
                if not verts:
                    continue
                b = batch_for_shader(ls, "LINES", {"pos": verts})
                ls.bind()
                ls.uniform_float("viewportSize", (vw, vh))
                ls.uniform_float("lineWidth", width)
                ls.uniform_float("color", color)
                b.draw(ls)
            for (x, y, s, size, color, align, tl) in self.texts:
                if tl != L:
                    continue
                draw_text(x, y, s, size, color, align)
        gpu.state.blend_set("NONE")


def text_width(s, size):
    blf.size(0, size)
    return blf.dimensions(0, s)[0]


def draw_text(x, y, s, size, color, align="L"):
    fid = 0
    blf.size(fid, size)
    w, h = blf.dimensions(fid, s)
    if align == "C":
        x -= w / 2
    elif align == "R":
        x -= w
    blf.color(fid, *color)
    blf.position(fid, x, y, 0)
    blf.draw(fid, s)
