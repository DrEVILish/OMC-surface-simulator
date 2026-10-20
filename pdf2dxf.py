#!/usr/bin/env python3
"""
One page of a vector PDF -> DXF, for the surfaces whose only drawing is a PDF (docs/25, "X32 / M32 /
WING family"): the X32 COMPACT manual's dimensioned top view, WING-Dimensional.pdf's "console top".

The page goes through poppler's SVG writer (pdftocairo -svg). Every path (stroke or fill) becomes an
LWPOLYLINE, Bezier segments flattened to 0.05 mm; text that the PDF keeps as text comes from
pdftotext -bbox as TEXT entities (most of these drawings carry their legends as outlines, which then
are line art like the rest). Coordinates are converted to millimetres of the real console:

    mm = (pt - origin) * scale       scale = real mm per PDF point, from a dimension of the drawing

and the view can be turned by a multiple of 90 degrees first (WING's top view is drawn sideways).
Y points up in the DXF, as in the vendor DWGs, so surface_models.load_plan reads it the same way.

usage: pdf2dxf.py in.pdf page out.dxf --scale S [--rotate 0|90|180|270] [--clip x0 y0 x1 y1]
       (--clip: the view's box in PDF points, y down as pdftocairo writes it; the rest is dropped)
"""
import argparse
import math
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import ezdxf

NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def mat_mul(a, b):
    """affine 2x3 (a, b, c, d, e, f) as SVG: x' = a x + c y + e, y' = b x + d y + f; returns a * b"""
    a0, a1, a2, a3, a4, a5 = a
    b0, b1, b2, b3, b4, b5 = b
    return (a0 * b0 + a2 * b1, a1 * b0 + a3 * b1, a0 * b2 + a2 * b3, a1 * b2 + a3 * b3,
            a0 * b4 + a2 * b5 + a4, a1 * b4 + a3 * b5 + a5)


def parse_transform(s):
    m = (1, 0, 0, 1, 0, 0)
    for name, args in re.findall(r'(\w+)\s*\(([^)]*)\)', s or ''):
        v = [float(x) for x in NUM.findall(args)]
        if name == 'matrix':
            t = tuple(v)
        elif name == 'translate':
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == 'scale':
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == 'rotate':
            r = math.radians(v[0])
            t = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
        else:
            continue
        m = mat_mul(m, t)
    return m


def apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def path_polys(d, tol_pt):
    """SVG path data -> list of point lists (absolute M L H V C Q Z, and relative forms)"""
    toks = re.findall(r'[MmLlHhVvCcSsQqTtZzAa]|' + NUM.pattern, d)
    polys, cur, i, cmd = [], [], 0, None
    x = y = sx = sy = 0.0

    def nums(n):
        nonlocal i
        v = [float(t) for t in toks[i:i + n]]
        i += n
        return v
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in 'Zz':
                if cur:
                    cur.append((sx, sy))
                    polys.append(cur)
                cur = []
                x, y = sx, sy
                continue
        rel = cmd.islower()
        c = cmd.upper()
        if c == 'M':
            px, py = nums(2)
            if rel:
                px, py = px + x, py + y
            if len(cur) > 1:
                polys.append(cur)
            cur = [(px, py)]
            x, y, sx, sy = px, py, px, py
            cmd = 'l' if rel else 'L'
        elif c == 'L':
            px, py = nums(2)
            if rel:
                px, py = px + x, py + y
            cur.append((px, py))
            x, y = px, py
        elif c == 'H':
            px = nums(1)[0] + (x if rel else 0)
            cur.append((px, y))
            x = px
        elif c == 'V':
            py = nums(1)[0] + (y if rel else 0)
            cur.append((x, py))
            y = py
        elif c in 'CQ':
            n = 6 if c == 'C' else 4
            v = nums(n)
            if rel:
                v = [v[k] + (x if k % 2 == 0 else y) for k in range(n)]
            pts = [(x, y)] + [(v[k], v[k + 1]) for k in range(0, n, 2)]
            ln = sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(len(pts) - 1))
            steps = max(2, min(64, int(math.sqrt(ln / max(tol_pt, 1e-6)) + 1)))
            for s in range(1, steps + 1):
                u = s / steps
                if c == 'C':
                    p0, p1, p2, p3 = pts
                    bx = (1 - u) ** 3 * p0[0] + 3 * (1 - u) ** 2 * u * p1[0] + 3 * (1 - u) * u * u * p2[0] + u ** 3 * p3[0]
                    by = (1 - u) ** 3 * p0[1] + 3 * (1 - u) ** 2 * u * p1[1] + 3 * (1 - u) * u * u * p2[1] + u ** 3 * p3[1]
                else:
                    p0, p1, p2 = pts
                    bx = (1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * p1[0] + u * u * p2[0]
                    by = (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * p1[1] + u * u * p2[1]
                cur.append((bx, by))
            x, y = pts[-1]
        else:                       # S T A: not written by cairo; skip their numbers
            i += {'S': 4, 'T': 2, 'A': 7}[c]
    if len(cur) > 1:
        polys.append(cur)
    return polys


def walk(node, m, out, defs_skip):
    tag = node.tag.split('}')[-1]
    if tag in ('defs', 'clipPath', 'mask', 'symbol'):
        return
    if tag == 'use':                # glyphs: the PDF's real text comes from pdftotext
        return
    m = mat_mul(m, parse_transform(node.get('transform')))
    if tag == 'path' and node.get('d'):
        out.append((m, node.get('d'), node.get('fill', node.get('style', '')), node.get('stroke-width')))
    elif tag == 'rect':
        x, y = float(node.get('x', 0)), float(node.get('y', 0))
        w, h = float(node.get('width', 0)), float(node.get('height', 0))
        out.append((m, f'M {x} {y} L {x + w} {y} L {x + w} {y + h} L {x} {y + h} Z', '', None))
    for ch in node:
        walk(ch, m, out, defs_skip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('page', type=int)
    ap.add_argument('out')
    ap.add_argument('--scale', type=float, required=True, help='real mm per PDF point')
    ap.add_argument('--rotate', type=int, default=0, choices=(0, 90, 180, 270))
    ap.add_argument('--clip', type=float, nargs=4, default=None)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as td:
        svg = f'{td}/p.svg'
        subprocess.run(['pdftocairo', '-svg', '-f', str(a.page), '-l', str(a.page), a.pdf, svg], check=True,
                       stderr=subprocess.DEVNULL)
        root = ET.parse(svg).getroot()
        html = subprocess.run(['pdftotext', '-bbox', '-f', str(a.page), '-l', str(a.page), a.pdf, '-'],
                              check=True, capture_output=True, text=True).stdout
    H = float(NUM.findall(root.get('viewBox', '0 0 0 0'))[3])
    W = float(NUM.findall(root.get('viewBox', '0 0 0 0'))[2])
    items = []
    walk(root, (1, 0, 0, 1, 0, 0), items, None)
    cx0, cy0, cx1, cy1 = a.clip or (0, 0, W, H)

    def to_mm(px, py):
        # page points (y down) -> view-local points, turned, -> mm with y up
        u, v = px - cx0, py - cy0
        w, h = cx1 - cx0, cy1 - cy0
        if a.rotate == 90:          # turn the view clockwise
            u, v = h - v, u
        elif a.rotate == 180:
            u, v = w - u, h - v
        elif a.rotate == 270:
            u, v = v, w - u
        hh = w if a.rotate in (90, 270) else h
        return u * a.scale, (hh - v) * a.scale

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    doc.layers.add('PDF')
    doc.layers.add('PDF-TEXT')
    msp = doc.modelspace()
    n = 0
    tol = 0.05 / a.scale
    for m, d, fill, sw in items:
        for poly in path_polys(d, tol):
            pts = [apply(m, x, y) for x, y in poly]
            if a.clip and not all(cx0 - 0.5 <= x <= cx1 + 0.5 and cy0 - 0.5 <= y <= cy1 + 0.5 for x, y in pts):
                continue
            q = [to_mm(x, y) for x, y in pts]
            q = [p for k, p in enumerate(q) if k == 0 or math.hypot(p[0] - q[k - 1][0], p[1] - q[k - 1][1]) > 1e-4]
            if len(q) < 2:
                continue
            msp.add_lwpolyline(q, dxfattribs={'layer': 'PDF'})
            n += 1
    t = 0
    for wm in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', html):
        x0, y0, x1, y1 = map(float, wm.groups()[:4])
        s = wm.group(5).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        if a.clip and not (cx0 <= x0 and x1 <= cx1 and cy0 <= y0 and y1 <= cy1):
            continue
        (ax, ay), (bx, by) = to_mm(x0, y1), to_mm(x1, y0)
        hgt = abs(y1 - y0) * a.scale * 0.72
        msp.add_text(s, dxfattribs={'layer': 'PDF-TEXT', 'insert': (min(ax, bx), min(ay, by)), 'height': hgt})
        t += 1
    doc.saveas(a.out)
    print(f'{n} polylines, {t} words -> {a.out}')


if __name__ == '__main__':
    main()
