#!/usr/bin/env python3
"""
WING COMPACT and WING RACK panels for the web replica (docs/25, "WING family"). There is no drawing
of either; they are composed, to scale, from what exists:

  - the WING's own drawing (WING-Dimensional.pdf "console top", vector, through pdf2dxf.py): the
    parts the three consoles share - the 4-fader modules with the layer key column, the main display
    with its keys and touch knobs (WING COMPACT)
  - the WING user manual's figures (raster, traced here into outlines): the parts only the smaller
    consoles have - WING COMPACT's main fader section (Fig. 11) and its USB / monitor section
    (Fig. 18); WING RACK's display keys (Fig. 8) and its 4-channel section (Fig. 12)
  - the manual's dimensions (WING COMPACT 453 x 574 mm, WING RACK 486 x 183 mm front panel with
    the rack ears) and the consoles' top-view device pictures for where each part sits

Placements and figure scales are below (PARTS); the figure scale comes from a known size in it (the
10.1" display: 217.5 mm wide, as on the WING drawing; a 100 mm fader's slot), so a part is to scale
within it, while its position on the panel is good to a few millimetres only.

usage: compose-wing.py WING.dxf user-manual.pdf outdir     -> outdir/WINGC.dxf, outdir/WINGR.dxf
"""
import os
import subprocess
import sys
import tempfile

import cv2
import ezdxf
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import surface_models as sm   # noqa: E402

WING_WINDOW = (0.0, 0.0, 872.0, 585.0)

# manual figures: (page, image width, height) -> pdfimages picks it by size
FIG = {
    'fig8': (13, 1167, 664),     # main display and its keys (WING RACK's display)
    'fig10': (17, 891, 770),     # WING COMPACT left fader section (its 11 layer keys)
    'fig11': (18, 226, 786),     # WING COMPACT main fader section
    'fig12': (19, 684, 757),     # WING RACK 4-channel section
    'fig18': (24, 493, 510),     # WING COMPACT USB / monitor / talkback
}

# each console: size, and its parts. ('wing', box, dx, dy): the WING drawing's lines inside box, moved;
# ('fig', name, crop box in px or None, scale mm/px, x0, y0): a traced manual figure;
# ('rect', x0, y0, x1, y1, r): a plain outline
PARTS = {
    'WINGC': dict(size=(453.0, 574.0), parts=[
        ('rect', 0.0, 0.0, 453.0, 574.0, 8.0),
        ('rect', 12.0, 532.0, 441.0, 570.0, 4.0),                       # armrest
        ('wing', (40.0, 222.0, 358.0, 522.0), -5.0, -4.0),               # 3 x 4-fader modules
        ('fig', 'fig10', (0, 0, 72, 770), 0.39, 8.15, 220.8),          # the section's VIEW and 11 layer keys
        ('wing', (160.0, 3.0, 476.0, 216.0), -122.0, 6.0),               # main display, its keys and touch knobs
        ('fig', 'fig18', None, 88.0 / 493, 356.0, 113.0),               # USB / monitor / talkback
        ('fig', 'fig11', None, 88.0 / 226, 356.0, 216.0),               # main fader section
    ]),
    'WINGR': dict(size=(486.0, 183.0), parts=[
        ('rect', 0.0, 0.0, 486.0, 183.0, 2.0),
        ('rect', 16.0, 3.0, 470.0, 180.0, 4.0),                         # front panel between the rack ears
        ('rect', 3.0, 24.0, 11.0, 34.0, 4.0), ('rect', 3.0, 149.0, 11.0, 159.0, 4.0),     # ear slots
        ('rect', 475.0, 24.0, 483.0, 34.0, 4.0), ('rect', 475.0, 149.0, 483.0, 159.0, 4.0),
        ('fig', 'fig8', (0, 60, 110, 630), 217.5 / 853, 31.7, 0.1),    # the 7 display keys
        ('rect', 73.0, 20.0, 290.5, 156.0, 1.0),                        # the 10.1" display (217.5 mm)
        ('fig', 'fig12', None, 0.215, 302.1, 8.2),                      # CLR SOLO, meter, 4-channel section
    ]),
}


def figure(pdf, name, td):
    page, w, h = FIG[name]
    d = os.path.join(td, name)
    os.makedirs(d, exist_ok=True)
    subprocess.run(['pdfimages', '-png', '-f', str(page), '-l', str(page), pdf, os.path.join(d, 'i')], check=True,
                   stderr=subprocess.DEVNULL)
    for f in sorted(os.listdir(d)):
        im = cv2.imread(os.path.join(d, f), cv2.IMREAD_GRAYSCALE)
        if im is not None and im.shape == (h, w):
            return im
    raise SystemExit(f'{name}: no {w}x{h} image on page {page}')


def trace(gray, crop):
    """dark ink -> closed outlines (px)"""
    if crop:
        x0, y0, x1, y1 = crop
        gray = gray[y0:y1, x0:x1]
        off = (x0, y0)
    else:
        off = (0, 0)
    ink = (gray < 140).astype(np.uint8)
    cs, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        if len(c) < 6:
            continue
        c = cv2.approxPolyDP(c, 0.8, True).reshape(-1, 2).astype(float)
        out.append(np.vstack([c, c[:1]]) + off)
    return out


def rect(x0, y0, x1, y1, r):
    pts = []
    for (cx, cy, a0) in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(7):
            a = np.radians(a0 + 15 * k)
            pts.append((cx + r * np.cos(a), cy + r * np.sin(a)))
    pts.append(pts[0])
    return np.array(pts)


def main():
    wing_dxf, pdf, outdir = sys.argv[1:4]
    W, H, wpolys, _, _ = sm.load_plan(wing_dxf, dict(window=WING_WINDOW))
    with tempfile.TemporaryDirectory() as td:
        figs = {n: figure(pdf, n, td) for n in FIG}
    for model, spec in PARTS.items():
        PW, PH = spec['size']
        polys = []
        for p in spec['parts']:
            if p[0] == 'rect':
                polys.append(rect(*p[1:]))
            elif p[0] == 'wing':
                (x0, y0, x1, y1), dx, dy = p[1], p[2], p[3]
                for _, q in wpolys:
                    if q[:, 0].min() >= 431.5 and q[:, 0].max() <= 433.5:
                        continue                   # the WING drawing's centre line (dash-dot)
                    if q[:, 0].min() >= x0 and q[:, 0].max() <= x1 and q[:, 1].min() >= y0 and q[:, 1].max() <= y1:
                        polys.append(q + (dx, dy))
            else:
                _, name, crop, k, x0, y0 = p
                for q in trace(figs[name], crop):
                    polys.append(q * k + (x0, y0))
        doc = ezdxf.new('R2010')
        doc.header['$INSUNITS'] = 4
        msp = doc.modelspace()
        for q in polys:
            msp.add_lwpolyline([(x, PH - y) for x, y in q], dxfattribs={'layer': 'COMPOSED'})
        fn = os.path.join(outdir, model + '.dxf')
        doc.saveas(fn)
        print(f'{model}: {len(polys)} outlines, {PW} x {PH} mm -> {fn}')


if __name__ == '__main__':
    main()
