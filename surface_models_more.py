"""
More surfaces for the web replica: the XL8, the X32 family (X32, X32 COMPACT, X32 RACK), the M32
family (M32, M32R) and the WING family (WING, WING COMPACT, WING RACK).

gen-surface.py --model <id> calls surface_models.build(), which hands these ids to build() here.
The steps are the PRO models' (surface_models.py), with per-model settings:

  1. plan view   a window of the drawing in real millimetres (DXF from the vendor DWG through
                 LibreDWG, from a vector PDF page through pdf2dxf.py, or composed by
                 compose-wing.py), block references expanded
  2. controls    the plan view rasterised at 10 px/mm; enclosed regions classified by size, fill
                 and aspect with each drawing's own size table (RULES): the Music Tribe and the
                 2012+ Bestec drawings use other part libraries than the PRO series. Faders come
                 from their slot (the long thin region, split by the cap where the cap is drawn),
                 meters from their LED strips, knobs from their rings
  3. labels      these drawings carry their legends as outlines (or not at all): every bound
                 control is given its legend here, from the consoles' manuals
  4. bindings    by section and position, as on the PRO models: OMC's generic channel / bus / FX /
                 scene addresses (docs/25); the fader banks and their layer keys mirror the console
  5. SVG         the PRO writer, with the fader caps the drawing shows mid-travel taken out

The XL8 drawing is a Bestec G2 drawing like the PRO1's, so its parts go through the PRO classes
(surface_models.find_controls) plus its knobs.
"""
import json
import math
import re

import cv2
import numpy as np

import surface_models as sm
from surface_models import BTN, CMD, FN, KNOBS, Binder

PX = sm.PX

# touch UI pages (OMC MidasUi::Page; OSC "screen" / SURFACE_SCREEN): the screen keys of these consoles
PAGE = dict(home=0, channel=1, buses=2, routing=3, effects=4, monitor=5, scenes=7, show=8, meters=10, setup=11,
            groups=16, vcas=25, flip=32, automutes=33, eventio=37, naming=38, library=47, recorder=54)

# OMC's action list (OMC assignables.h Act; OSC action <n> runs it, action_lit <n> is its lamp): the keys OMC has no
# parameter of their own for
ACT = dict(osc=4, mon_dim=53, mon_mono=54, mon_cut=55, mute_group1=28)


def _act(a, what):
    return dict(kind='action', a=a, what=what)


# ------------------------------------------------------------------------------------------------
# per-model settings
# ------------------------------------------------------------------------------------------------
# rules: (type, (w lo, hi), (h lo, hi), (fill lo, hi), extra); extra: size= the control's drawn size
# (w, h) when the region is only a part of it, cap= knob cap diameter. First match wins.

X32_RULES = [
    ('lcd', (17.5, 20.5), (12.5, 15.5), (0.95, 1.01), {}),
    ('button', (10.5, 13.5), (8.8, 11.0), (0.9, 1.01), {}),
    ('button', (9.0, 11.5), (2.4, 3.6), (0.9, 1.01), {}),                 # display soft keys (thin)
    ('button', (22.0, 26.0), (6.0, 10.0), (0.9, 1.01), {}),               # category keys right of the display
    ('button', (6.8, 8.8), (5.4, 7.2), (0.9, 1.01), {}),                  # VIEW and other small keys
    ('button', (10.0, 12.0), (7.0, 9.0), (0.9, 1.01), {}),
    ('button', (13.0, 15.0), (9.0, 11.0), (0.9, 1.01), {}),
    ('button', (6.5, 10.5), (6.0, 9.5), (0.9, 1.01), {}),
    ('button', (4.8, 5.8), (3.0, 3.8), (0.9, 1.01), dict(size=(7.0, 5.5))),   # the light window of a small VIEW key (X32 COMPACT)
    ('meter', (4.8, 7.0), (28.0, 34.0), (0.7, 0.9), dict(cells=8)),
    ('knob', (23.5, 27.0), (22.5, 26.0), (0.25, 0.5), dict(size=(22.0, 22.0), cap=14.0)),
    ('knob', (14.0, 16.5), (15.0, 18.0), (0.7, 0.9), dict(size=(15.0, 15.0), cap=11.0)),   # display encoders
    ('slot', (1.2, 3.2), (25.0, 130.0), (0.9, 1.01), {}),
]

M32_RULES = [
    ('lcdstrip', (180.0, 200.0), (25.0, 36.0), (0.85, 1.01), dict(n=8)),
    ('lcdstrip', (115.0, 135.0), (25.0, 36.0), (0.85, 1.01), dict(n=4)),
    ('lcd', (27.0, 36.0), (25.0, 35.0), (0.95, 1.01), {}),
    ('button', (14.5, 17.5), (11.5, 14.0), (0.8, 1.0), {}),
    ('button', (14.0, 16.5), (14.0, 16.5), (0.7, 0.85), dict(size=(12.0, 12.0))),   # round SELECT keys
    ('button', (15.0, 17.5), (8.0, 10.0), (0.85, 1.0), {}),               # upper panel keys (seen tilted)
    ('button', (13.5, 16.0), (9.0, 11.0), (0.72, 0.9), {}),                # round VIEW keys
    ('button', (23.0, 27.0), (8.0, 10.0), (0.85, 1.0), {}),               # category keys right of the display
    ('knob', (23.0, 27.0), (12.0, 16.0), (0.3, 0.5), dict(size=(16.0, 16.0), cap=12.0, dy=10.0)),   # ring of a knob seen tilted
    ('knob', (23.0, 27.0), (23.0, 27.0), (0.5, 0.85), dict(size=(20.0, 20.0), cap=13.0)),   # assign knobs
    ('meter', (5.0, 8.0), (30.0, 35.0), (0.9, 1.01), dict(cells=8)),
    ('meter', (5.0, 8.0), (19.0, 24.0), (0.9, 1.01), dict(cells=8)),
    ('slot', (2.0, 4.0), (25.0, 130.0), (0.9, 1.01), {}),
]

M32R_RULES = [
    ('lcdstrip', (180.0, 200.0), (25.0, 36.0), (0.85, 1.01), dict(n=8)),
    ('lcd', (27.0, 36.0), (25.0, 35.0), (0.95, 1.01), {}),
    ('button', (14.5, 17.5), (10.0, 14.0), (0.78, 1.0), {}),
    ('button', (14.0, 16.5), (14.0, 16.5), (0.7, 0.85), dict(size=(12.0, 12.0))),   # round SEL keys
    ('button', (9.0, 11.0), (8.0, 10.0), (0.7, 0.9), {}),                    # number keys 1-8 (round)
    ('button', (19.0, 22.0), (8.0, 10.0), (0.85, 1.0), {}),                  # display side keys
    ('knob', (24.0, 27.5), (21.0, 24.5), (0.6, 0.85), dict(size=(20.0, 20.0), cap=13.0)),
    ('pot', (13.0, 15.5), (18.0, 21.5), (0.7, 0.9), dict(size=(13.0, 13.0))),
    ('meter', (5.0, 8.0), (30.0, 35.0), (0.9, 1.01), dict(cells=8)),
    ('meter', (5.0, 8.0), (26.0, 30.0), (0.9, 1.01), dict(cells=8)),
    ('slot', (2.0, 4.0), (25.0, 130.0), (0.9, 1.01), {}),
]

X32R_RULES = [
    ('lcd', (26.0, 30.0), (46.0, 52.0), (0.9, 1.01), {}),
    ('button', (11.0, 13.0), (8.8, 10.0), (0.95, 1.01), {}),
    ('button', (16.0, 17.5), (6.0, 7.5), (0.95, 1.01), {}),                 # display keys
    ('button', (13.0, 15.0), (8.0, 9.5), (0.75, 0.88), {}),                 # 4-way key: up / down
    ('button', (8.0, 9.5), (16.5, 18.5), (0.7, 0.82), {}),                  # 4-way key: left / right
    ('knob', (24.0, 26.0), (24.0, 26.0), (0.35, 0.45), dict(size=(24.0, 24.0), cap=14.0)),
    ('knob', (14.5, 15.6), (14.5, 15.6), (0.72, 0.82), dict(size=(15.0, 15.0), cap=11.0)),
]

WING_RULES = [
    ('lcdstrip', (90.0, 100.0), (18.0, 40.0), (0.9, 1.01), dict(n=4)),      # a module's 4 scribble displays
    ('meterblock', (86.0, 91.0), (28.0, 35.0), (0.9, 1.01), dict(n=4, cells=8)),   # a module's meter window
    ('button', (11.0, 15.0), (7.0, 9.0), (0.95, 1.01), {}),
    ('button', (7.0, 9.0), (7.0, 9.0), (0.95, 1.01), {}),
    ('knob', (15.0, 17.0), (15.0, 17.0), (0.1, 0.3), dict(size=(15.0, 15.0), cap=11.0)),   # double-ring knobs
    ('knob', (9.5, 13.0), (9.5, 13.0), (0.7, 0.85), dict(size=(12.0, 12.0), cap=9.0)),
    ('jog', (55.0, 60.0), (55.0, 60.0), (0.6, 0.8), {}),
    ('slot', (1.5, 3.5), (30.0, 130.0), (0.85, 1.01), {}),
]

MODELS = {
    'x32': dict(name='X32', family='x32', window=(535.0, 2040.0, 1440.0, 2590.0), rules=X32_RULES,
                inputs=32, exclude=[(0, 0, 905, 22)],            # rear connector cut-outs seen from above
                screen_box=(470, 40, 760, 220)),
    'x32c': dict(name='X32 COMPACT', family='x32c', window=(20.0, 5.0, 660.0, 530.0), rules=X32_RULES,
                 inputs=32, screen_box=(300, 50, 540, 160), exclude=[(0, 0, 660, 12)]),
    'm32r': dict(name='M32R', family='m32r', window=(1075.0, 990.0, 1566.0, 1616.0), rules=M32R_RULES, contours=True,
                 inputs=32, screen_box=(250, 50, 480, 140), exclude=[(0, 240, 491, 262)]),
    'x32r': dict(name='X32 RACK', family='x32r', window=(250.0, 685.0, 755.0, 850.0), rules=X32R_RULES,
                 inputs=32, screen_box=(175, 25, 330, 110)),
    'wing': dict(name='WING', family='wing', window=(0.0, 0.0, 872.0, 585.0), rules=WING_RULES, big=120.0,
                 inputs=40, screen_box=(200, 20, 440, 175), capw=14.0,
                 drop=[(431.5, 0, 433.5, 585)]),           # the drawing's centre line (dash-dot)
    'wingc': dict(name='WING COMPACT', family='wingc', window=(0.0, 0.0, 453.0, 574.0), rules=WING_RULES + [
                      ('button', (9.0, 17.0), (6.0, 13.0), (0.6, 1.01), {}),          # traced keys (Fig. 11, 18)
                      ('knob', (8.0, 11.5), (8.0, 11.5), (0.55, 0.9), dict(size=(10.0, 10.0), cap=7.0))],
                  big=120.0, inputs=40, screen_box=(40, 10, 360, 180), capw=14.0,
                  exclude=[(395, 125, 415, 140), (420, 460, 440, 490)],
                  source='composed (compose-wing.py): WING drawing parts + traced WING manual figures 11 and 18'),
    'wingr': dict(name='WING RACK', family='wingr', window=(0.0, 0.0, 486.0, 183.0), rules=[
                      ('lcdstrip', (55.0, 75.0), (12.0, 22.0), (0.5, 1.01), dict(n=4)),
                      ('button', (6.0, 17.0), (5.0, 13.0), (0.6, 1.01), {}),
                      ('knob', (8.5, 14.0), (8.5, 14.0), (0.6, 0.9), dict(size=(11.0, 11.0), cap=8.0))],
                  big=120.0, inputs=40, screen_box=(60, 10, 300, 170),
                  exclude=[(0, 0, 16, 183), (470, 0, 486, 183), (335, 145, 365, 165)],
                  source='composed (compose-wing.py): traced WING manual figures 8 and 12, display to scale'),
    'xl8': dict(name='XL8', family='xl8', window=(410.0, 1966.0, 2288.0, 3023.0), bestec=True, knob_r=(5.0, 9.5),
                inputs=96, screen_box=(820, 90, 1130, 220), caps=False),
    'm32': dict(name='M32', family='m32', window=(766.0, 1846.0, 1662.0, 2462.0), rules=M32_RULES, contours=True,
                inputs=32, screen_box=(470, 110, 700, 220), exclude=[(810, 120, 840, 145)]),
}


# ------------------------------------------------------------------------------------------------
# 1. plan view
# ------------------------------------------------------------------------------------------------

def load(src, cfg):
    W, H, polys, texts, circles = sm.load_plan(src, cfg)
    for (x0, y0, x1, y1) in cfg.get('drop', ()):
        polys = [(l, p) for (l, p) in polys if not (p[:, 0].min() >= x0 and p[:, 0].max() <= x1 and
                                                     p[:, 1].min() >= y0 and p[:, 1].max() <= y1)]
    return W, H, polys, texts, circles


# ------------------------------------------------------------------------------------------------
# 2. controls
# ------------------------------------------------------------------------------------------------

def regions(img, hi=60.0):
    """surface_models.regions with a larger upper size (the WING's scribble displays are ~100 mm)"""
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats((1 - blk).astype(np.uint8), connectivity=4)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w < 20 or h < 20 or w > hi * PX or h > hi * PX:
            continue
        out.append(dict(cx=cen[i][0] / PX, cy=cen[i][1] / PX, w=w / PX, h=h / PX, fill=a / (w * h), x=x / PX, y=y / PX))
    return out


def contour_regions(img, lo=1.5, hi=220.0):
    """the outer outlines of the parts (contours of the line art), as regions: for drawings whose keys
    carry their legend as geometry inside, which splits the enclosed area into pieces"""
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(blk, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        x, y, w, h = cv2.boundingRect(c)
        if w < lo * PX or h < lo * PX or w > hi * PX or h > hi * PX:
            continue
        a = cv2.contourArea(c)
        out.append(dict(cx=(x + w / 2) / PX, cy=(y + h / 2) / PX, w=w / PX, h=h / PX, fill=a / (w * h), x=x / PX, y=y / PX))
    return out


def classify(r, rules):
    for (t, (w0, w1), (h0, h1), (f0, f1), ex) in rules:
        if w0 <= r['w'] <= w1 and h0 <= r['h'] <= h1 and f0 <= r['fill'] <= f1:
            return t, ex
    return None, None


def detect(reg, cfg, W, H):
    """regions -> controls with the model's size table; slots -> faders; strips -> meters"""
    ctl, slots, caps = [], [], []

    def add(kind, cx, cy, w, h, **kw):
        ctl.append(dict(type=kind, x=round(cx, 2), y=round(cy, 2), w=round(w, 2), h=round(h, 2), **kw))
    for r in reg:
        t, ex = classify(r, cfg['rules'])
        if t is None:
            continue
        if t == 'slot':
            slots.append(r)
            continue
        if t == 'cap':
            caps.append(r)
            continue
        w, h = ex.get('size', (r['w'], r['h']))
        if t == 'lcdstrip':
            # one glass for n strips (M32): an LCD key per strip
            n = ex['n']
            pw = r['w'] / n
            for k in range(n):
                add('lcd', r['x'] + pw * (k + 0.5), r['cy'], pw - 1.0, r['h'] * 0.8)
            continue
        if t == 'meterblock':
            # one window for n strips' meters (WING): a meter per strip
            n, nc = ex['n'], ex['cells']
            pw, pitch = r['w'] / n, (r['h'] - 4.0) / nc
            for k in range(n):
                add('meter', r['x'] + pw * (k + 0.5), r['cy'], 3.0, r['h'] - 4.0,
                    cells=[round(r['y'] + 2.0 + pitch * (j + 0.5), 2) for j in range(nc)], ch=round(pitch * 0.7, 2))
            continue
        if t == 'meter':
            n = ex.get('cells', 8)
            pitch = r['h'] / n
            cells = [round(r['y'] + pitch * (k + 0.5), 2) for k in range(n)]
            add('meter', r['cx'], r['cy'], r['w'] * 0.6, r['h'], cells=cells, ch=round(pitch * 0.7, 2))
            continue
        kw = {k: v for k, v in ex.items() if k in ('cap', 'dir')}
        add(t, r['cx'] + ex.get('dx', 0.0), r['cy'] + ex.get('dy', 0.0), w, h, **kw)
    # faders: the slot parts on one x (the cap splits a slot in two) joined; the cap travels 100 mm
    # around the slot's middle (the browser's fader law: top + 4.1 .. bottom + 10.4, docs/25)
    cols = {}
    for s in slots:
        cols.setdefault(round(s['cx']), []).append(s)
    travel = cfg.get('travel', 100.0)
    for x, ss in cols.items():
        top = min(s['y'] for s in ss)
        bot = max(s['y'] + s['h'] for s in ss)
        if bot - top < cfg.get('min_slot', 80):
            continue
        xc = sum(s['cx'] for s in ss) / len(ss)
        mid = (top + bot) / 2
        ft, fb = mid - travel / 2 - 4.1, mid + travel / 2 - 10.4
        add('fader', xc, (ft + fb) / 2, 3.0, fb - ft, top=round(ft, 2), bottom=round(fb, 2),
            slot=[round(top, 2), round(bot, 2), round(max(s['w'] for s in ss), 2)],
            pieces=sorted([round(s['y'], 2), round(s['y'] + s['h'], 2)] for s in ss))
    # a knob's cap or skirt is not a key
    knobs = [c for c in ctl if c['type'] in ('knob', 'pot')]
    ctl[:] = [c for c in ctl if c['type'] != 'button' or not any(math.hypot(c['x'] - k['x'], c['y'] - k['y']) < k['w'] / 2 for k in knobs)]
    # nested duplicates: keep the largest per position and type
    out = []
    for c in sorted(ctl, key=lambda c: -c['w'] * c['h']):
        tol = {'knob': 6.0, 'lcd': 5.0}.get(c['type'], 1.5)
        if any(abs(c['x'] - o['x']) < tol and abs(c['y'] - o['y']) < tol and c['type'] == o['type'] for o in out):
            continue
        out.append(c)
    return out


def detect_bestec(reg, polys, circles, W, H, cfg):
    """the XL8 (Bestec G2 drawing, the PRO1's part library): the PRO classes, plus its knobs (plain circles)"""
    ctl = sm.find_controls(reg, polys, circles, W, H)
    for (x, y, r) in circles:
        if cfg['knob_r'][0] <= r <= cfg['knob_r'][1] and not any(c['type'] == 'knob' and abs(c['x'] - x) < 2 and abs(c['y'] - y) < 2 for c in ctl):
            ctl.append(dict(type='knob', x=round(x, 2), y=round(y, 2), w=round(2 * r * 1.15, 2), h=round(2 * r * 1.15, 2), cap=round(2 * r * 0.8, 2)))
    # a knob's outline is not a round key
    knobs = [c for c in ctl if c['type'] == 'knob']
    ctl[:] = [c for c in ctl if c['type'] == 'knob' or not any(math.hypot(c['x'] - k['x'], c['y'] - k['y']) < k['w'] / 2 for k in knobs)]
    return ctl


def find_screen(img, box):
    """the display opening: the largest enclosed region (fill > 0.9) inside box (panel mm)"""
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats((1 - blk).astype(np.uint8), connectivity=4)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if x >= box[0] * PX and y >= box[1] * PX and x + w <= box[2] * PX and y + h <= box[3] * PX and a / (w * h) > 0.9:
            if best is None or w * h > best[2] * best[3]:
                best = (x, y, w, h)
    return tuple(round(float(v) / PX, 2) for v in best) if best else None


def cap_boxes(reg, ctl, cfg):
    """the fader caps the drawing shows: where a cap is drawn it hides the slot, so it fills the gap
    between the slot's pieces (cap width from the model's settings)"""
    boxes = []
    cw = cfg.get('capw', 14.0)
    for f in (c for c in ctl if c['type'] == 'fader'):
        ps = f.get('pieces') or []
        gaps = [(b[0] - a[1], a[1], b[0]) for a, b in zip(ps, ps[1:])]
        if not gaps:
            continue
        g, y0, y1 = max(gaps)
        if g < 4:
            continue
        m = cfg.get('capm', 3.0)
        boxes.append((f['x'] - cw / 2, y0 - m, f['x'] + cw / 2, y1 + m))
    return boxes


# ------------------------------------------------------------------------------------------------
# 4. bindings: helpers
# ------------------------------------------------------------------------------------------------

def row(bd, types, box, n=None, key=lambda c: c['x']):
    cs = sorted(bd.where(types=types, box=box, unbound=False), key=key)
    if n is not None:
        assert len(cs) == n, (types, box, n, [(c['x'], c['y']) for c in cs])
    return cs


def put(c, label, **b):
    c['label'] = label
    c['bind'] = b
    return c


def strips(bd, faders, bank, rows, lcd=True, meter=True, slot0=0, tol=8.0):
    """fader strips: fader + the keys / LCD / meter above it (rows: [(y, p, label)])"""
    for k, f in enumerate(faders):
        s = slot0 + k
        f['bind'] = dict(kind='strip', bank=bank, slot=s, p='fader', lo=-100, hi=10, law='fader')
        for (y, p, lab) in rows:
            c = bd.at(('button',), f['x'], y, tol)
            if c is None:
                raise SystemExit(f'strip {bank}{s}: no {lab} key near {f["x"]:.1f},{y:.1f}')
            put(c, lab, kind='strip', bank=bank, slot=s, p=p, toggle=True)
            if p == 'sel':
                c['bind'] = dict(kind='strip', bank=bank, slot=s, p='sel', select=True)
        if lcd:
            c = bd.at(('lcd',), f['x'], lcd, 12.0) if not isinstance(lcd, bool) else None
            if c is not None:
                put(c, 'scribble strip', kind='strip', bank=bank, slot=s, p='sel', select=True)
        if meter:
            m = bd.at(('meter',), f['x'], meter, 12.0) if not isinstance(meter, bool) else None
            if m is not None:
                put(m, 'meter', kind='strip', bank=bank, slot=s, p='ch_meter')


def fixed_strip(bd, f, v, rows, lcd=None, meter=None, side='main'):
    f['bind'] = dict(kind='fixed', p='fader', i=v + 1, lo=-100, hi=10, law='fader', what=f'{side} fader')
    f['label'] = side
    for (y, p, lab) in rows:
        c = bd.at(('button',), f['x'], y, 8.0)
        if c is None:
            raise SystemExit(f'{side}: no {lab} key near {f["x"]:.1f},{y:.1f}')
        if p == 'sel':
            put(c, lab, kind='radio', p='sel', i=1, value=v, what=f'select {side}')
        elif p == 'solo_clear':
            put(c, lab, kind='fixed', p='solo_clear', i=1, toggle=True, what='clear solo')
        else:
            put(c, lab, kind='fixed', p=p, i=v + 1, toggle=True, what=f'{side} {lab.lower()}')
    if lcd is not None:
        c = bd.at(('lcd',), f['x'], lcd, 12.0)
        if c is not None:
            put(c, 'scribble strip', kind='radio', p='sel', i=1, value=v, what=f'select {side}', caption=side)
    if meter is not None:
        for m, s in zip(sorted(bd.where(types=('meter',), box=(f['x'] - 12, meter - 20, f['x'] + 12, meter + 20)),
                               key=lambda c: c['x']), ('l', 'r')):
            put(m, f'{side} meter', kind='meter', p='main_meter_' + s, i=1)


def unlabelled(ctl):
    return [c for c in ctl if not c.get('bind') and c['type'] not in ('led',)]


# ------------------------------------------------------------------------------------------------
# 4. bindings: roles. A role is what a control does on the console, as OMC carries it; the model
# tables below say where each role sits. The X32 / M32 / WING channel strip edits the selected
# channel, as the PRO1's selected-channel strip does.
# ------------------------------------------------------------------------------------------------

def _sel(p, **kw):
    return dict(kind='sel', p=p, **kw)


ROLES = {
    # preamp / config
    'gain': ('GAIN', _sel('ch_gain', lo=-18, hi=60, unit='dB')),
    'trim': ('TRIM', _sel('ch_gain', lo=-18, hi=60, unit='dB')),
    'lowcut_f': ('LOW CUT FREQUENCY', _sel('ch_hpf', lo=20, hi=400, log=True, unit='Hz')),
    'phantom': ('48V', _sel('ch_phantom', toggle=True)),
    'phase': ('\u00d8', _sel('ch_phase', toggle=True)),
    'lowcut': ('LOW CUT', _sel('ch_hpf_on', toggle=True)),
    'pre_meter': ('LEVEL', dict(kind='sel', p='ch_meter')),
    # dynamics
    'gate_thr': ('GATE THRESHOLD', _sel('ch_gate_thr', lo=-50, hi=25, unit='dB')),
    'gate_on': ('GATE', _sel('ch_gate_on', toggle=True)),
    'comp_thr': ('DYNAMICS THRESHOLD', _sel('ch_comp_thr', lo=-50, hi=25, unit='dB')),
    'comp_on': ('COMP', _sel('ch_comp_on', toggle=True)),
    # EQ: the knobs edit the band the band keys choose
    'eq_q': ('Q', dict(kind='band', p='ch_eq_q', lo=0.3, hi=10, log=True, unit='')),
    'eq_f': ('FREQ', dict(kind='band', p='ch_eq_f', lo=20, hi=20000, log=True, unit='Hz')),
    'eq_g': ('GAIN', dict(kind='band', p='ch_eq_g', lo=-15, hi=15, unit='dB')),
    'eq_mode': ('MODE', dict(kind='cycle', p='ch_eq_type', n=8, what='EQ band type')),
    'eq_on': ('EQUALIZER', _sel('ch_eq_on', toggle=True)),
    'band4': ('HIGH', dict(kind='bandsel', value=4, what='EQ band: high')),
    'band3': ('HIGH MID', dict(kind='bandsel', value=3, what='EQ band: high mid')),
    'band2': ('LOW MID', dict(kind='bandsel', value=2, what='EQ band: low mid')),
    'band1': ('LOW', dict(kind='bandsel', value=1, what='EQ band: low')),
    # main bus
    'mono_level': ('MONO LEVEL', _sel('ch_mono_level', lo=-100, hi=10, unit='dB')),
    'mono_bus': ('MONO BUS', _sel('ch_send_mono', toggle=True)),
    'pan': ('PAN / BAL', _sel('ch_pan', lo=-100, hi=100, unit='')),
    'lr_bus': ('STEREO BUS', _sel('ch_send_lr', toggle=True)),
    # section VIEW keys: the touch UI's channel page at that section (ui_cmd 20-27)
    'view_input': ('VIEW', dict(kind='cmd', p='ui_cmd', value=CMD['input'], what='CHANNEL > INPUT')),
    'view_gate': ('VIEW', dict(kind='cmd', p='ui_cmd', value=CMD['gate'], what='CHANNEL > gate')),
    'view_comp': ('VIEW', dict(kind='cmd', p='ui_cmd', value=CMD['comp'], what='CHANNEL > dynamics')),
    'view_eq': ('VIEW', dict(kind='cmd', p='ui_cmd', value=CMD['eq'], what='CHANNEL > EQ')),
    'view_sends': ('VIEW', dict(kind='radio', p='screen', i=1, value=PAGE['buses'], what='BUSES (OMC decodes no ui_cmd for CHANNEL > SENDS)')),
    'view_main': ('VIEW', dict(kind='cmd', p='ui_cmd', value=CMD['main'], what='CHANNEL > MAIN')),
    'view_usb': ('VIEW', dict(kind='radio', p='screen', i=1, value=PAGE['recorder'], what='UTILITY > Recorder')),
    'view_mon': ('VIEW', dict(kind='radio', p='screen', i=1, value=PAGE['monitor'], what='MONITOR')),
    'view_talk': ('VIEW', dict(kind='radio', p='screen', i=1, value=28, what='MONITOR > Talk Groups')),
    'view_scenes': ('VIEW', dict(kind='radio', p='screen', i=1, value=PAGE['scenes'], what='SCENES')),
    'view_assign': ('VIEW', dict(kind='cmd', p='ui_cmd', value=CMD['setup'], what='SETUP > Custom Controls')),
    # screen (category) keys
    'home': ('HOME', dict(kind='radio', p='screen', i=1, value=PAGE['home'], what='HOME')),
    'meters': ('METERS', dict(kind='radio', p='screen', i=1, value=PAGE['meters'], what='METERS')),
    'routing': ('ROUTING', dict(kind='radio', p='screen', i=1, value=PAGE['routing'], what='ROUTING')),
    'setup': ('SETUP', dict(kind='radio', p='screen', i=1, value=PAGE['setup'], what='SETUP')),
    'library': ('LIBRARY', dict(kind='radio', p='screen', i=1, value=PAGE['library'], what='LIBRARY')),
    'effects': ('EFFECTS', dict(kind='radio', p='screen', i=1, value=PAGE['effects'], what='EFFECTS')),
    'mutegrp': ('MUTE GRP', dict(kind='radio', p='screen', i=1, value=PAGE['automutes'], what='HOME > Automutes')),
    'utility': ('UTILITY', dict(kind='radio', p='screen', i=1, value=PAGE['naming'], what='UTILITY')),
    'monitor': ('MONITOR', dict(kind='radio', p='screen', i=1, value=PAGE['monitor'], what='MONITOR')),
    'scenes': ('SCENES', dict(kind='radio', p='screen', i=1, value=PAGE['scenes'], what='SCENES')),
    'page_l': ('PAGE \u25c0', dict(kind='cmd', p='ui_cmd', value=1, what='page select: previous tab')),
    'page_r': ('PAGE \u25b6', dict(kind='cmd', p='ui_cmd', value=2, what='page select: next tab')),
    'layer_up': ('LAYER \u25b2', dict(kind='cmd', p='ui_cmd', value=3, what='layer up (cursor up)')),
    'layer_dn': ('LAYER \u25bc', dict(kind='cmd', p='ui_cmd', value=4, what='layer down (cursor down)')),
    # monitor / talkback
    'mon_level': ('MONITOR LEVEL', dict(kind='fixed', p='mon_level', i=1, lo=-100, hi=10, unit='dB', what='monitor level')),
    'phones': ('PHONES LEVEL', dict(kind='surface', i=FN['phones'], what='phones level')),
    'talk_level': ('TALK LEVEL', dict(kind='surface', i=FN['talk_level'], what='talk level')),
    'mon_dim': ('DIM', dict(kind='surface', i=FN['mon_dim'], toggle=True, what='monitor dim')),
    'talk_a': ('TALK A', dict(kind='surface', i=FN['talk_int'], toggle=True, what='talk A (talk internal)')),
    'talk_b': ('TALK B', dict(kind='surface', i=FN['talk_ext'], toggle=True, what='talk B (talk external)')),
    # scenes
    'prev': ('PREV', dict(kind='cmd', p='ui_cmd', value=CMD['last'], what='previous scene / cue')),
    'next': ('NEXT', dict(kind='cmd', p='ui_cmd', value=CMD['next'], what='next scene / cue')),
    'undo': ('UNDO', dict(kind='cmd', p='ui_cmd', value=CMD['cancel'], what='Cancel: discard preview')),
    'go': ('GO', dict(kind='cmd', p='ui_cmd', value=CMD['now'], what='GO: recall the scene')),
    # bank / mixing
    'sof': ('SENDS ON FADER', dict(kind='flip', what="sends on faders: the last mix's sends on the input faders")),
    'clear_solo': ('CLEAR SOLO', dict(kind='fixed', p='solo_clear', i=1, toggle=True, what='clear solo')),
}


def role(c, name, **extra):
    lab, b = ROLES[name]
    b = dict(b, **extra)
    return put(c, lab, **b)


def ensure(bd, t, x, y, w, h, why, tol=2.5, **kw):
    """the control at (x, y), or one added there when the drawing leaves its outline open"""
    c = bd.at((t,), x, y, tol)
    if c is None:
        c = dict(type=t, x=round(x, 2), y=round(y, 2), w=w, h=h, derived=why, **kw)
        bd.ctl.append(c)
    return c


def place(bd, table, tol=2.5):
    """table: [(role, type, x, y)] -> bind each (a missing control is an error)"""
    for (r, t, x, y) in table:
        c = bd.at((t,) if isinstance(t, str) else t, x, y, tol)
        if c is None:
            raise SystemExit(f'{r}: no {t} near {x:.1f},{y:.1f}')
        role(c, r)


def sends(bd, knobs, keys, view=None, pw=4):
    """bus sends of the selected channel: pw knobs, the bank keys page them (1-4, 5-8, ...)"""
    for k, c in enumerate(knobs):
        put(c, f'BUS SEND {k + 1}', kind='sendlvl', bus=k + 1, pw=pw, lo=-100, hi=10, unit='dB',
            what=f'send to bus {k + 1} (+{pw} per bank key)')
    for k, c in enumerate(keys):
        put(c, f'{k * pw + 1}-{(k + 1) * pw}', kind='sendpage', value=k, what=f'bus sends {k * pw + 1}-{(k + 1) * pw} on the knobs')


# ------------------------------------------------------------------------------------------------
# 4. bindings: X32 (X32.dxf, Music Group drawing; legends from the X32 manual, section 2)
# ------------------------------------------------------------------------------------------------

def bind_x32(ctl, cfg):
    bd = Binder(ctl)
    # ---- channel strip: config / preamp, gate, dynamics, equalizer, bus sends, main bus
    place(bd, [('gain', 'knob', 99.4, 105.8), ('lowcut_f', 'knob', 162.9, 105.8), ('pre_meter', 'meter', 131.1, 106.3),
               ('phantom', 'button', 87.4, 133.4), ('phase', 'button', 111.5, 133.4), ('lowcut', 'button', 163.0, 133.4),
               ('view_input', 'button', 185.2, 138.4),
               ('gate_thr', 'knob', 99.4, 169.6), ('gate_on', 'button', 99.5, 197.2), ('view_gate', 'button', 121.7, 202.1),
               ('comp_thr', 'knob', 162.9, 169.6), ('comp_on', 'button', 163.0, 197.2), ('view_comp', 'button', 185.2, 202.1),
               ('eq_mode', 'button', 227.1, 133.4), ('eq_q', 'knob', 255.0, 106.0), ('eq_f', 'knob', 280.0, 143.0),
               ('eq_g', 'knob', 239.0, 170.0), ('eq_on', 'button', 239.0, 197.0), ('view_eq', 'button', 333.0, 202.0),
               ('band4', 'button', 315.0, 117.0), ('band3', 'button', 315.0, 139.0), ('band2', 'button', 315.0, 160.0),
               ('band1', 'button', 315.0, 182.0), ('view_sends', 'button', 404.0, 202.0),
               ('mono_level', 'knob', 439.0, 106.0), ('mono_bus', 'button', 439.0, 133.0), ('pan', 'knob', 439.0, 163.0),
               ('lr_bus', 'button', 439.0, 191.0), ('view_main', 'button', 454.0, 202.0), ('view_usb', 'button', 454.0, 74.0)], tol=3)
    sends(bd, [bd.at(('knob',), 362, y, 3) for y in (106, 135, 163, 192)], [bd.at(('button',), 392, y, 3) for y in (117, 139, 160, 182)])
    # ---- display: 6 push encoders, 8 category keys, layer and page select
    for k, c in enumerate(row(bd, ('knob',), (495, 170, 650, 190), 6)):
        put(c, f'ENCODER {k + 1}', kind='enc', i=k + 1, what=f'push encoder {k + 1}: the touch UI\'s focused row, knob {k + 1}')
    open_ = 'completed: the drawing leaves this key\'s outline open'
    for k, r in enumerate(('home', 'meters', 'routing', 'setup', 'library', 'effects', 'mutegrp', 'utility')):
        role(ensure(bd, 'button', 715.1, 81.9 + 12.07 * k, 23.6, 8.7, open_, tol=3), r)
    role(ensure(bd, 'button', 681.8, 172.7, 8.3, 4.9, 'the layer key pair drawn as one part', tol=2), 'layer_up')
    role(ensure(bd, 'button', 681.8, 182.4, 8.3, 4.9, 'the layer key pair drawn as one part', tol=2), 'layer_dn')
    place(bd, [('page_l', 'button', 707.0, 177.0), ('page_r', 'button', 723.0, 177.0)], tol=3)
    # ---- monitor / talkback
    for (r, x, y) in (('mon_level', 776.0, 99.1), ('phones', 776.0, 136.6), ('talk_level', 825.6, 136.6)):
        role(ensure(bd, 'pot', x, y, 13.7, 13.7, 'pointer pot (drawn as a knob outline)', tol=2), r)
    bd.at(('button',), 776.0, 170.0, 3)['label'] = 'MONO'          # monitor mono: OMC has none (latches on the page)
    place(bd, [('mon_dim', 'button', 776.0, 191.0), ('view_mon', 'button', 791.0, 202.0),
               ('talk_a', 'button', 826.0, 170.0), ('talk_b', 'button', 826.0, 191.0), ('view_talk', 'button', 841.0, 202.0)], tol=3)
    # ---- scenes, assign, mute groups
    place(bd, [('prev', 'button', 738.0, 237.0), ('next', 'button', 760.0, 237.0), ('undo', 'button', 784.0, 236.0),
               ('go', 'button', 815.0, 236.0), ('view_scenes', 'button', 841.0, 245.0), ('view_assign', 'button', 841.0, 384.0)], tol=3)
    for k, c in enumerate(row(bd, ('knob',), (725, 262, 845, 286), 4)):
        put(c, f'ASSIGN {k + 1}', kind='uenc', i=k + 1, what=f'custom assign knob {k + 1}: user knob {k + 1} of the active bank')
    for k, c in enumerate(row(bd, ('lcd',), (725, 290, 845, 314), 4)):
        put(c, 'ASSIGN DISPLAY', kind='cmd', p='ui_cmd', value=CMD['setup'], caption=f'ASSIGN {k + 1}', what='SETUP > Custom Controls')
    keys = row(bd, ('button',), (725, 315, 845, 335), 4) + row(bd, ('button',), (725, 337, 845, 357), 4)
    for k, c in enumerate(keys):
        put(c, f'ASSIGN {k + 5}', kind='ukey', i=k + 1, what=f'custom assign key {k + 5}: user key {k + 1} of the active bank')
    for k, c in enumerate(row(bd, ('button',), (740, 362, 830, 380), 3)):
        put(c, 'SET ' + 'ABC'[k], kind='ukbank', value=k + 1, what=f'assign set {"ABC"[k]}: user-key bank {k + 1}')
    for k, (x, y) in enumerate(((735.0, 412.0), (758.0, 412.0), (735.0, 434.0), (758.0, 434.0), (735.0, 455.4), (758.3, 455.4))):
        c = ensure(bd, 'button', x, y, 12.1, 9.8, open_, tol=3)
        put(c, f'MUTE GROUP {k + 1}', kind='fixed', p=f'mute_group{k + 1}', i=1, toggle=True, what=f'mute group {k + 1}')
    # ---- input bank (16) and group / bus bank (8), main
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    assert len(fs) == 25, len(fs)
    rows_ = [(229.0, 'sel', 'SELECT'), (283.0, 'ch_solo', 'SOLO'), (325.0, 'ch_mute', 'MUTE')]
    strips(bd, fs[:16], 'I', rows_, lcd=302.0, meter=256.0)
    strips(bd, fs[16:24], 'G', rows_, lcd=302.0, meter=256.0)
    fixed_strip(bd, fs[24], 80, [(229.0, 'sel', 'SELECT'), (283.0, 'ch_solo', 'SOLO'), (325.0, 'ch_mute', 'MUTE'),
                                 (263.0, 'solo_clear', 'CLEAR SOLO')], lcd=302.0, side='main LR')
    m = bd.at(('meter',), fs[24]['x'], 256.0, 12)
    if m is not None:
        put(m, 'main meter', kind='meter', p='main_meter_l', i=1)
    for (y, v, lab) in ((331.0, 'ch1', 'CH 1-16'), (355.0, 'ch2', 'CH 17-32'), (380.0, 'auxfx', 'AUX IN / USB, FX RETURNS'), (404.0, 'busm', 'BUS MASTER')):
        put(bd.at(('button',), 80.0, y, 3), lab, kind='layer', bank='I', value=v)
    for (y, v, lab) in ((331.0, 'vca', 'GROUP DCA 1-8'), (355.0, 'bus1', 'BUS 1-8'), (380.0, 'bus2', 'BUS 9-16'), (404.0, 'mtx', 'MATRIX 1-6, MAIN C')):
        put(bd.at(('button',), 484.0, y, 3), lab, kind='layer', bank='G', value=v)
    role(bd.at(('button',), 484.0, 235.0, 3), 'sof')
    c = bd.at(('button',), 80.0, 235.0, 3)
    c['label'] = 'REMOTE (DAW)'
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: M32 (M32_Live.dwg, Bestec 2014 drawing, blocks put back by dwgfill.py). The upper
# panel is drawn tilted (its knobs and keys seen obliquely, keys partly behind the knobs): its parts
# are placed from the drawing by position, the ones a knob hides completed at their visible outline.
# ------------------------------------------------------------------------------------------------

def m32_upper(bd, dx=0.0, dy=0.0):
    """the M32 / M32R channel strip, display and monitor parts (positions on the M32; dx, dy move them)"""
    hid = 'completed: partly hidden behind the knob above it in the drawing\'s tilted view'
    K, Bt = ('knob',), ('button',)

    def knob(r, x, y):
        role(ensure(bd, 'knob', x + dx, y + dy, 16.0, 16.0, 'knob seen tilted', tol=6.0, cap=12.0), r)

    def key(r, x, y, w=16.0, h=9.0, why=hid):
        role(ensure(bd, 'button', x + dx, y + dy, w, h, why, tol=3.0), r)
    for (r, x, y) in (('gain', 79, 136), ('lowcut_f', 144, 136), ('gate_thr', 79, 186), ('comp_thr', 144, 186),
                      ('eq_q', 231, 136), ('eq_f', 231, 161), ('eq_g', 231, 186), ('mono_level', 404, 161), ('pan', 404, 186)):
        knob(r, x, y)
    for (r, x, y) in (('phantom', 67, 147), ('phase', 91, 147), ('lowcut', 142.8, 148.5), ('gate_on', 79, 198.5),
                      ('comp_on', 142.8, 198.5), ('eq_on', 231, 197.5), ('eq_mode', 200, 187),
                      ('band4', 275, 144), ('band3', 275, 158), ('band2', 275, 172), ('band1', 275, 187),
                      ('mono_bus', 446, 158), ('lr_bus', 446, 183)):
        key(r, x, y)
    for (r, x, y) in (('view_input', 164, 155), ('view_gate', 99, 204), ('view_comp', 164, 204), ('view_eq', 275, 204),
                      ('view_sends', 360, 204), ('view_usb', 446, 130), ('view_main', 446, 204)):
        key(r, x, y, 13.0, 9.0, 'round VIEW key')
    for k, y in enumerate((136, 161, 186, 211)):
        ensure(bd, 'knob', 319 + dx, y + dy, 16.0, 16.0, 'knob seen tilted', tol=6.0, cap=12.0)
    sends(bd, [bd.at(K, 319 + dx, y + dy, 6) for y in (136, 161, 186, 211)],
          [ensure(bd, 'button', 360 + dx, y + dy, 16.0, 9.0, hid, tol=3.0) for y in (144, 158, 172, 187)])
    # display: 6 push encoders, 8 category keys, the 4-way page / layer key
    for k in range(6):
        c = ensure(bd, 'knob', 496.1 + 25.32 * k + dx, 213.0 + dy, 12.0, 12.0, 'encoder seen tilted', tol=6.0, cap=10.0)
        put(c, f'ENCODER {k + 1}', kind='enc', i=k + 1, what=f'push encoder {k + 1}: the touch UI\'s focused row, knob {k + 1}')
    for k, r in enumerate(('home', 'meters', 'routing', 'setup', 'library', 'effects', 'mutegrp', 'utility')):
        role(ensure(bd, 'button', 707.0 + dx, 129.4 + 10.6 * k + dy, 20.0, 7.0, 'category key', tol=3.0), r)
    four = 'the 4-way navigation key, drawn as one part'
    role(ensure(bd, 'button', 665.6 + dx, 198.3 + dy, 10.0, 4.0, four, tol=1.5), 'layer_up')
    role(ensure(bd, 'button', 665.6 + dx, 207.5 + dy, 10.0, 4.0, four, tol=1.5), 'layer_dn')
    role(ensure(bd, 'button', 653.0 + dx, 202.8 + dy, 5.0, 8.0, four, tol=1.5), 'page_l')
    role(ensure(bd, 'button', 678.2 + dx, 202.8 + dy, 5.0, 8.0, four, tol=1.5), 'page_r')
    # monitor / talkback
    for (r, x, y) in (('mon_level', 764.4, 139.0), ('phones', 764.4, 168.0), ('talk_level', 824.6, 168.5)):
        role(ensure(bd, 'pot', x + dx, y + dy, 13.0, 13.0, 'pot seen tilted', tol=4.0), r)
    ensure(bd, 'button', 764.4 + dx, 182.5 + dy, 12.0, 7.5, hid, tol=3.0)['label'] = 'MONO'   # OMC has no monitor mono
    for (r, x, y, w) in (('mon_dim', 764.4, 192.7, 16.0), ('talk_a', 824.6, 183.0, 12.0), ('talk_b', 824.6, 192.7, 16.0)):
        key(r, x, y, w, 8.0)
    key('view_mon', 780.0, 204.5, 13.0, 9.0, 'round VIEW key')
    key('view_talk', 840.2, 204.5, 13.0, 9.0, 'round VIEW key')


def m32_right(bd, x0, y0, dx=0.0, dy=0.0):
    """scenes, assign and mute groups: the M32's right column (x0, y0: its scene PREV key)"""
    ox, oy = x0 - 742.0, y0 - 257.0
    place(bd, [(r, 'button', x + ox, y + oy) for (r, x, y) in
               (('prev', 742, 257), ('next', 768, 257), ('undo', 794, 257), ('go', 819, 257), ('view_scenes', 840, 272),
                ('view_assign', 840, 444))], tol=3)
    for k, c in enumerate(row(bd, ('knob',), (725 + ox, 295 + oy, 850 + ox, 320 + oy), 4)):
        put(c, f'ASSIGN {k + 1}', kind='uenc', i=k + 1, what=f'custom assign knob {k + 1}: user knob {k + 1} of the active bank')
    for k, c in enumerate(row(bd, ('lcd',), (725 + ox, 330 + oy, 850 + ox, 356 + oy), 4)):
        put(c, 'ASSIGN DISPLAY', kind='cmd', p='ui_cmd', value=CMD['setup'], caption=f'ASSIGN {k + 1}', what='SETUP > Custom Controls')
    keys = row(bd, ('button',), (725 + ox, 362 + oy, 850 + ox, 380 + oy), 4) + row(bd, ('button',), (725 + ox, 390 + oy, 850 + ox, 410 + oy), 4)
    for k, c in enumerate(keys):
        put(c, f'ASSIGN {k + 5}', kind='ukey', i=k + 1, what=f'custom assign key {k + 5}: user key {k + 1} of the active bank')
    for k, c in enumerate(row(bd, ('button',), (745 + ox, 420 + oy, 830 + ox, 438 + oy), 3)):
        put(c, 'SET ' + 'ABC'[k], kind='ukbank', value=k + 1, what=f'assign set {"ABC"[k]}: user-key bank {k + 1}')
    mg = row(bd, ('button',), (745 + ox, 470 + oy, 830 + ox, 486 + oy), 3) + row(bd, ('button',), (745 + ox, 498 + oy, 830 + ox, 516 + oy), 3)
    for k, c in enumerate(mg):
        put(c, f'MUTE GROUP {k + 1}', kind='fixed', p=f'mute_group{k + 1}', i=1, toggle=True, what=f'mute group {k + 1}')


def m32_banks(bd, ctl, ys, xl, xg, horiz=False):
    """input (16) and group (8) fader banks + main, with their layer keys (ys: SEL, meter, SOLO, LCD, MUTE)"""
    ysel, ymet, ysolo, ylcd, ymute = ys
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    assert len(fs) == 25, len(fs)
    rows_ = [(ysel, 'sel', 'SEL'), (ysolo, 'ch_solo', 'SOLO'), (ymute, 'ch_mute', 'MUTE')]
    strips(bd, fs[:16], 'I', rows_, lcd=ylcd, meter=ymet)
    strips(bd, fs[16:24], 'G', rows_, lcd=ylcd, meter=ymet)
    return fs


def m32_layers(bd, xl, xg, ys, sof, remote=None):
    for (y, v, lab) in zip(ys, ('ch1', 'ch2', 'auxfx', 'busm'), ('INPUTS 1-16', 'INPUTS 17-32', 'AUX IN / USB, FX RETURNS', 'BUS MASTER')):
        put(bd.at(('button',), xl, y, 3), lab, kind='layer', bank='I', value=v)
    for (y, v, lab) in zip(ys, ('vca', 'bus1', 'bus2', 'mtx'), ('GROUP DCA 1-8', 'BUS 1-8', 'BUS 9-16', 'MATRIX 1-6, MAIN C')):
        put(bd.at(('button',), xg, y, 3), lab, kind='layer', bank='G', value=v)
    role(bd.at(('button',), *sof, 3), 'sof')
    if remote:
        bd.at(('button',), *remote, 3)['label'] = 'REMOTE (DAW)'


def bind_m32(ctl, cfg):
    bd = Binder(ctl)
    m32_upper(bd)
    bd.at(('meter',), 111, 137, 4) and role(bd.at(('meter',), 111, 137, 4), 'pre_meter')
    fs = m32_banks(bd, ctl, (257.0, 286.0, 314.0, 343.0, 371.0), 56.0, 471.0)
    fixed_strip(bd, fs[24], 80, [(257.0, 'sel', 'SEL'), (314.0, 'ch_solo', 'SOLO'), (371.0, 'ch_mute', 'MUTE'),
                                 (294.0, 'solo_clear', 'CLR SOLO')], lcd=343.0, side='main LR')
    m32_layers(bd, 56.0, 471.0, (423.0, 448.0, 474.0, 499.0), (471.0, 286.0), remote=(56.0, 286.0))
    m32_right(bd, 742.0, 257.0)
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: X32 COMPACT (the X32 COMPACT manual's dimensioned top view, vector, via pdf2dxf.py;
# legends from the manual's callouts, section 2)
# ------------------------------------------------------------------------------------------------

def bind_x32c(ctl, cfg):
    bd = Binder(ctl)
    place(bd, [('talk_a', 'button', 71.0, 69.0), ('talk_b', 'button', 90.0, 69.0), ('mon_dim', 'button', 197.8, 68.8),
               ('view_mon', 'button', 249.2, 73.4), ('view_usb', 'button', 293.7, 73.4),
               ('gain', 'knob', 81.0, 102.0), ('lowcut_f', 'knob', 130.0, 102.0), ('pre_meter', 'meter', 106.0, 103.0),
               ('phantom', 'button', 71.0, 133.0), ('phase', 'button', 90.0, 133.0), ('lowcut', 'button', 121.0, 133.0),
               ('view_input', 'button', 143.2, 137.8),
               ('gate_thr', 'knob', 81.0, 167.0), ('gate_on', 'button', 71.0, 198.0), ('view_gate', 'button', 96.2, 202.8),
               ('comp_thr', 'knob', 130.0, 167.0), ('comp_on', 'button', 121.0, 198.2), ('view_comp', 'button', 143.2, 202.8),
               ('eq_q', 'knob', 198.0, 102.0), ('eq_f', 'knob', 209.0, 142.0), ('eq_g', 'knob', 183.0, 167.0),
               ('band4', 'button', 242.0, 112.0), ('band3', 'button', 242.0, 133.0), ('band2', 'button', 242.0, 155.0),
               ('band1', 'button', 242.0, 176.0), ('eq_on', 'button', 173.0, 198.0), ('eq_mode', 'button', 192.0, 198.0),
               ('view_eq', 'button', 249.2, 202.8),
               ('view_sends', 'button', 293.7, 100.1), ('mono_level', 'knob', 281.0, 120.0), ('mono_bus', 'button', 271.0, 145.0),
               ('pan', 'knob', 281.0, 167.0), ('lr_bus', 'button', 271.4, 198.2), ('view_main', 'button', 293.7, 202.8)], tol=3)
    bd.at(('button',), 293.7, 100.1, 3)['label'] = 'MIX BUS SENDS'
    for (r, x) in (('talk_level', 116.7), ('mon_level', 171.9), ('phones', 224.0)):
        role(ensure(bd, 'pot', x, 61.0, 11.0, 11.0, 'pointer pot (its outline is open in the drawing)', tol=3), r)
    # display: 6 push encoders, 8 category keys, layer and page select
    for k in range(6):
        c = ensure(bd, 'knob', 349.3 + 25.4 * k, 177.0, 12.0, 12.0, 'encoder (its outline is open in the drawing)', tol=4, cap=9.0)
        put(c, f'ENCODER {k + 1}', kind='enc', i=k + 1, what=f'push encoder {k + 1}: the touch UI\'s focused row, knob {k + 1}')
    for k, r in enumerate(('home', 'meters', 'routing', 'setup', 'library', 'effects', 'mutegrp', 'utility')):
        role(ensure(bd, 'button', 555.6, 65.9 + 12.19 * k, 22.4, 6.5, 'category key (outline open in the drawing)', tol=3), r)
    place(bd, [('layer_up', 'button', 522.3, 166.4), ('layer_dn', 'button', 522.3, 181.4),
               ('page_l', 'button', 547.5, 173.9), ('page_r', 'button', 563.8, 173.9)], tol=3)
    # input bank (8) with 8 layers, group / bus bank (8), main
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    assert len(fs) == 17, len(fs)
    rows_ = [(226.0, 'sel', 'SELECT'), (280.0, 'ch_solo', 'SOLO'), (321.0, 'ch_mute', 'MUTE')]
    strips(bd, fs[:8], 'I', rows_, lcd=298.0, meter=252.0)
    strips(bd, fs[8:16], 'G', rows_, lcd=298.0, meter=252.0)
    fixed_strip(bd, fs[16], 80, [(226.0, 'sel', 'SELECT'), (280.0, 'ch_solo', 'SOLO'), (321.0, 'ch_mute', 'MUTE'),
                                 (260.0, 'solo_clear', 'CLEAR SOLO')], lcd=298.0, side='main LR')
    for (y, v, lab) in zip((238, 263, 287, 312, 336, 361, 385, 410), ('ch1', 'ch2', 'ch3', 'ch4', 'aux', 'fxret', 'bus1', 'bus2'),
                           ('CH 1-8', 'CH 9-16', 'CH 17-24', 'CH 25-32', 'AUX IN 1-6 / USB REC', 'EFFECTS RETURNS',
                            'BUS 1-8 MASTER', 'BUS 9-16 MASTER')):
        put(bd.at(('button',), 70.0, y, 3), lab, kind='layer', bank='I', value=v)
    for (y, v, lab) in ((336, 'vca', 'GROUP DCA 1-8'), (361, 'bus1', 'BUS 1-8'), (385, 'bus2', 'BUS 9-16'), (410, 'mtx', 'MATRIX 1-6, MAIN C')):
        put(bd.at(('button',), 285.0, y, 3), lab, kind='layer', bank='G', value=v)
    role(bd.at(('button',), 285.0, 287.0, 3), 'sof')
    bd.at(('button',), 285.0, 238.0, 3)['label'] = 'DAW REMOTE'
    # scenes, assign keys 1-8, mute groups
    place(bd, [('undo', 'button', 541.0, 236.0), ('go', 'button', 564.0, 236.0), ('prev', 'button', 541.3, 255.3),
               ('next', 'button', 564.2, 255.3), ('view_scenes', 'button', 571.8, 278.0), ('view_assign', 'button', 571.8, 387.8)], tol=3)
    keys = [bd.at(('button',), x, y, 3) for y in (307, 327, 347, 366) for x in (541, 564)]
    for k, c in enumerate(keys):
        put(c, f'ASSIGN {k + 1}', kind='ukey', i=k + 1, what=f'custom assign key {k + 1}: user key {k + 1} of the active bank')
    mg = [bd.at(('button',), x, y, 3) for y in (417, 437, 456) for x in (541, 564)]
    for k, c in enumerate(mg):
        put(c, f'MUTE GROUP {k + 1}', kind='fixed', p=f'mute_group{k + 1}', i=1, toggle=True, what=f'mute group {k + 1}')
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: M32R (M32R.dwg, Bestec drawing, the plan view that is not turned; its keys carry their
# legends as outlines, read off the drawing)
# ------------------------------------------------------------------------------------------------

def bind_m32r(ctl, cfg):
    bd = Binder(ctl)
    place(bd, [('talk_a', 'button', 44, 89), ('talk_b', 'button', 68, 89), ('talk_level', 'pot', 106, 86),
               ('mon_level', 'pot', 142, 86), ('mon_dim', 'button', 166, 89), ('phones', 'pot', 189, 86),
               ('view_mon', 'button', 211, 94), ('view_usb', 'button', 236, 122),
               ('gain', 'knob', 56, 124), ('lowcut_f', 'knob', 106, 124), ('pre_meter', 'meter', 81, 124),
               ('phantom', 'button', 44, 151), ('phase', 'button', 68, 151), ('lowcut', 'button', 94, 151),
               ('view_input', 'button', 117, 156),
               ('gate_thr', 'knob', 56, 186), ('gate_on', 'button', 44, 213), ('view_gate', 'button', 71, 225),
               ('comp_thr', 'knob', 106, 186), ('comp_on', 'button', 94, 213), ('view_comp', 'button', 117, 225),
               ('eq_mode', 'button', 142, 186), ('eq_q', 'knob', 179, 124), ('eq_f', 'knob', 179, 155), ('eq_g', 'knob', 179, 186),
               ('eq_on', 'button', 179, 213), ('band4', 'button', 211, 131), ('band3', 'button', 211, 150),
               ('band2', 'button', 211, 169), ('band1', 'button', 211, 188), ('view_eq', 'button', 211, 225),
               ('mono_level', 'knob', 304, 186), ('pan', 'knob', 342, 186), ('mono_bus', 'button', 304, 213),
               ('lr_bus', 'button', 330, 213), ('view_main', 'button', 354, 224)], tol=4)
    bd.at(('button',), 304, 213, 4)['label'] = 'MONO CENTER'
    bd.at(('button',), 330, 213, 4)['label'] = 'MAIN STEREO'
    role(bd.at(('button',), 236, 148, 4), 'view_scenes')
    # the 8 number keys: custom assign keys 1-8, their VIEW
    for k, (x, y) in enumerate((x, y) for y in (172, 189, 207, 224) for x in (233, 254)):
        put(bd.at(('button',), x, y, 4), str(k + 1), kind='ukey', i=k + 1, what=f'custom assign key {k + 1}: user key {k + 1} of the active bank')
    role(bd.at(('button',), 278, 225, 4), 'view_assign')
    # display: 10 category keys, 6 push encoders, the 4-way page / layer key
    for k, r in enumerate(('home', 'meters', 'routing', 'library', 'effects')):
        role(ensure(bd, 'button', 270.0, 79.6 + 10.95 * k, 18.0, 7.0, 'category key (outline open in the drawing)', tol=3), r)
    for k, r in enumerate(('setup', 'monitor', 'scenes', 'mutegrp', 'utility')):
        role(ensure(bd, 'button', 439.0, 79.6 + 10.95 * k, 18.0, 7.0, 'category key (outline open in the drawing)', tol=3), r)
    for k, x in enumerate((277.7, 303.2, 328.3, 353.7, 378.8, 404.1)):
        c = ensure(bd, 'knob', x, 147.3, 13.0, 13.0, 'encoder (its outline is open in the drawing)', tol=4, cap=10.0)
        put(c, f'ENCODER {k + 1}', kind='enc', i=k + 1, what=f'push encoder {k + 1}: the touch UI\'s focused row, knob {k + 1}')
    four = 'the 4-way navigation key, drawn as one part'
    role(ensure(bd, 'button', 430.6, 139.5, 9.0, 4.0, four, tol=1.5), 'layer_up')
    role(ensure(bd, 'button', 430.6, 151.0, 9.0, 4.0, four, tol=1.5), 'layer_dn')
    role(ensure(bd, 'button', 421.0, 145.0, 4.0, 8.0, four, tol=1.5), 'page_l')
    role(ensure(bd, 'button', 440.0, 145.0, 4.0, 8.0, four, tol=1.5), 'page_r')
    # layer keys: input bank (8 layers), group bank (4), REM, FADER FLIP
    for (x, y, v, lab) in ((378, 174, 'ch1', 'INPUTS 1-8'), (399, 174, 'ch2', 'INPUTS 9-16'), (378, 190, 'ch3', 'INPUTS 17-24'),
                           (399, 190, 'ch4', 'INPUTS 25-32'), (378, 207, 'aux', 'AUX IN / USB'), (399, 206, 'fxret', 'FX RET'),
                           (378, 223, 'bus1', 'BUS 1-8'), (399, 223, 'bus2', 'BUS 9-16')):
        put(bd.at(('button',), x, y, 4), lab, kind='layer', bank='I', value=v)
    for (y, v, lab) in ((174, 'vca', 'GROUP DCA 1-8'), (190, 'bus1', 'BUS 1-8'), (207, 'bus2', 'BUS 9-16'), (223, 'mtx', 'MATRIX, MAIN C')):
        put(bd.at(('button',), 443, y, 4), lab, kind='layer', bank='G', value=v)
    bd.at(('button',), 421, 182, 4)['label'] = 'REM (DAW remote)'
    role(bd.at(('button',), 421, 215, 4), 'sof')
    bd.at(('button',), 421, 215, 4)['label'] = 'FADER FLIP'
    # fader banks: 8 + 8 + main
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    assert len(fs) == 17, len(fs)
    rows_ = [(284.0, 'sel', 'SEL'), (342.0, 'ch_solo', 'SOLO'), (398.0, 'ch_mute', 'MUTE')]
    strips(bd, fs[:8], 'I', rows_, lcd=370.0, meter=313.0)
    strips(bd, fs[8:16], 'G', rows_, lcd=370.0, meter=313.0)
    fixed_strip(bd, fs[16], 80, [(284.0, 'sel', 'SEL'), (342.0, 'ch_solo', 'SOLO'), (398.0, 'ch_mute', 'MUTE'),
                                 (321.0, 'solo_clear', 'CLR SOLO')], lcd=370.0, side='main LR')
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: X32 RACK (X32RACK.dxf, Music Group drawing, the front view; no legends in the drawing:
# the X32 RACK's front panel, with the 10-key display module of the X32 PRODUCER / M32R)
# ------------------------------------------------------------------------------------------------

def bind_x32r(ctl, cfg):
    bd = Binder(ctl)
    c = bd.at(('lcd',), 124.1, 46.5, 3)
    put(c, 'CHANNEL DISPLAY', kind='cmd', p='ui_cmd', value=60, caption='CHANNEL', what='the selected channel: open it on the touch UI')
    c = bd.at(('knob',), 124.1, 122.4, 3)
    put(c, 'CHANNEL SELECT', kind='selknob', what='channel select: steps the selected channel')
    c = bd.at(('knob',), 124.1, 72.8, 3)
    c.update(type='button', w=12.0, h=12.0)
    put(c, 'VIEW', kind='cmd', p='ui_cmd', value=CMD['input'], what='CHANNEL page of the selected channel')
    role(bd.at(('button',), 68.6, 94.4, 3), 'view_usb')
    put(bd.at(('button',), 111.4, 94.4, 3), 'MUTE', **_sel('ch_mute', toggle=True, what='mute of the selected channel'))
    put(bd.at(('button',), 136.8, 94.4, 3), 'SOLO', **_sel('ch_solo', toggle=True, what='solo of the selected channel'))
    for k, r in enumerate(('home', 'meters', 'routing', 'library', 'effects')):
        role(bd.at(('button',), 167.0, 45.9 + 12.7 * k, 3), r)
    for k, r in enumerate(('setup', 'monitor', 'scenes', 'mutegrp', 'utility')):
        role(bd.at(('button',), 336.6, 45.9 + 12.7 * k, 3), r)
    for k, c in enumerate(row(bd, ('knob',), (165, 115, 310, 130), 6)):
        put(c, f'ENCODER {k + 1}', kind='enc', i=k + 1, what=f'push encoder {k + 1}: the touch UI\'s focused row, knob {k + 1}')
    place(bd, [('layer_up', 'button', 330.8, 114.0), ('layer_dn', 'button', 330.8, 124.4),
               ('page_l', 'button', 320.7, 119.2), ('page_r', 'button', 340.9, 119.2)], tol=2)
    c = bd.at(('knob',), 379.4, 41.0, 3)
    role(c, 'talk_level')
    c['type'] = 'pot'
    c = bd.at(('knob',), 435.0, 40.5, 3)
    role(c, 'phones')
    c['type'] = 'pot'
    role(bd.at(('button',), 379.4, 68.7, 3), 'talk_a')
    bd.at(('button',), 379.4, 68.7, 3)['label'] = 'TALK'
    put(bd.at(('button',), 379.4, 94.4, 3), 'MAIN MUTE', kind='fixed', p='ch_mute', i=81, toggle=True, what='main LR mute')
    c = bd.at(('knob',), 379.4, 122.4, 3)
    put(c, 'MAIN LEVEL', kind='fixed', p='fader', i=81, lo=-100, hi=10, unit='dB', what='main LR level')
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: WING (WING-Dimensional.pdf, the "console top" view, vector, via pdf2dxf.py; a simplified
# view without legends: they come from the WING user manual, section 4)
# ------------------------------------------------------------------------------------------------

WING_FKEY0 = 9        # F1-F3 of the 4-channel section: user keys 9-11 (custom-control keys 1-8, the user layer 9-16)
QUAD = [('gain', 'GAIN / 48V'), ('gate', 'GATE'), ('comp', 'COMP'), ('filter', 'FILTER'), (None, 'F1'), (None, 'F2'),
        (None, 'F3'), ('pan', 'PAN / MAIN')]


def wing_strips(bd, ctl, banks, lcd_y, meter_y, rows_):
    """the fader sections: banks = [(bank, faders)]"""
    for bank, fs in banks:
        strips(bd, fs, bank, rows_, lcd=lcd_y, meter=meter_y)


def wing_layer_keys(bd, x, y0, pitch, keys, bank):
    for k, (v, lab) in enumerate(keys):
        c = bd.at(('button',), x, y0 + pitch * k, 3)
        if c is None:
            raise SystemExit(f'no layer key {lab} near {x},{y0 + pitch * k}')
        if v in ('-1', '+1'):
            put(c, lab, kind='scroll', bank=bank, step=int(v), what='scroll the section by a page')
        elif v == 'user':
            put(c, lab, kind='cmd', p='ui_cmd', value=CMD['layers'], what='user layers: the next user bank')
        elif v == 'sof':
            role(c, 'sof')
            c['label'] = lab
        else:
            put(c, lab, kind='layer', bank=bank, value=v)


WING_LEFT = [('in1', '1-12'), ('in2', '13-24'), ('in3', '25-36'), ('auxin', '37-40 AUX IN'), ('busm', 'BUS MASTER'),
             ('user', 'USER 1'), ('user', 'USER 2'), ('-1', '\u25c04'), ('+1', '4\u25b6')]
WING_MID = [('sof', 'SOF FLIP'), ('vca', 'DCA'), ('mainmtx', 'MAIN MATRIX'), ('auxin', 'AUX IN'), ('busm', 'BUS MASTER'),
            ('user', 'USER 1'), ('user', 'USER 2'), ('-1', '\u25c04'), ('+1', '4\u25b6')]
WING_RIGHT = [('mainmtx', 'MAIN MATRIX'), ('vca', 'DCA'), ('inputs', 'INPUTS'), ('auxin', 'AUX IN'), ('busm', 'BUS MASTER'),
              ('user', 'USER 1'), ('user', 'USER 2'), ('-1', '\u25c04'), ('+1', '4\u25b6')]


def wing_display(bd, x_keys, y_keys, pitch, enc, enc_y=None, right=None):
    """the main display: 7 screen keys, the 6 touch knobs under it, the right column"""
    for k, r in enumerate(('home', 'effects', 'meters', 'routing', 'setup', 'library', 'utility')):
        c = bd.at(('button',), x_keys, y_keys + pitch * k, 4)
        if c is None:
            raise SystemExit(f'display key {r}: none near {x_keys},{y_keys + pitch * k:.1f}')
        role(c, r)
    for k, c in enumerate(enc):
        put(c, f'TOUCH KNOB {k + 1}', kind='enc', i=k + 1, what=f'touch knob {k + 1}: the touch UI\'s focused row, knob {k + 1}')
    if right:
        clr, knob, key = right
        role(bd.at(('button',), *clr, 3), 'clear_solo')
        bd.at(('button',), *clr, 3)['label'] = 'CLR SOLO'


def wing_monitor(bd, view, knobs, keys):
    role(bd.at(('knob', 'button'), *view, 3), 'view_mon')
    for r, (x, y) in zip(('talk_level', 'phones', 'mon_level'), knobs):
        c = bd.at(('knob',), x, y, 3)
        role(c, r)
    for r, (x, y) in zip(('talk_a', 'talk_b', 'mon_dim', None), keys):
        c = bd.at(('button', 'knob'), x, y, 3)
        c.update(type='button')
        if r:
            role(c, r)
        else:
            put(c, 'MONO', **_act(ACT['mon_mono'], 'monitor mono (OMC action list)'))


def wing_quad(bd, keys, lcds, knobs, onkeys, bank):
    """the 4-channel section: a parameter key chooses what the 4 knobs and keys edit on the 4 strips"""
    for c, (m, lab) in zip(keys, QUAD):
        if m:
            put(c, lab, kind='qmode', value=m, what=f'4-channel section: the knobs edit {lab.lower()}')
        else:
            # F1-F3: user keys 9-11 of the active bank (the custom-control keys are 1-8)
            k = WING_FKEY0 + int(lab[1:]) - 1
            put(c, lab, kind='ukey', i=k, what=f'function key {lab}: user key {k} of the active bank')
    for k, c in enumerate(lcds):
        put(c, 'scribble strip', kind='strip', bank=bank, slot=k, p='sel', select=True)
    for k, c in enumerate(knobs):
        put(c, f'CHANNEL {k + 1}', kind='qknob', bank=bank, slot=k, what='the chosen parameter of this strip')
    for k, c in enumerate(onkeys):
        put(c, f'CHANNEL {k + 1} ON', kind='qkey', bank=bank, slot=k, what='on / off of the chosen parameter')


def bind_wing(ctl, cfg):
    bd = Binder(ctl)
    # ---- USB / monitor / talkback
    wing_monitor(bd, (30, 127), ((58, 170), (93, 170), (129, 170)), ((46, 196), (70, 196), (117, 196), (140, 196)))
    # ---- main display
    wing_display(bd, 182.0, 32.0, 20.9, row(bd, ('knob',), (215, 180, 420, 198), 6), right=((453.4, 32), None, None))
    bd.at(('knob',), 453.4, 136.7, 3)['label'] = 'display knob'
    bd.at(('button',), 453.4, 157.4, 3)['label'] = 'display key'
    # ---- channel strip section (selected channel)
    put(bd.at(('knob',), 494, 106, 3), 'VIEW', kind='radio', p='screen', i=1, value=PAGE['channel'], what='CHANNEL page')
    bd.at(('knob',), 494, 106, 3).update(type='button', w=11.0, h=11.0)
    k1 = row(bd, ('knob',), (505, 104, 715, 120), 6)
    for c, r in zip(k1, ('gain', 'lowcut_f', 'gate_thr', 'comp_thr', None, 'pan')):
        if r:
            role(c, r)
        else:
            c['label'] = 'INSERT'
    for c, (lab, b) in zip(row(bd, ('button',), (505, 132, 715, 146), 6),
                           (('INPUT', dict(kind='cmd', p='ui_cmd', value=CMD['input'], what='CHANNEL > INPUT')),
                            ('FILTER', _sel('ch_hpf_on', toggle=True)), ('GATE', _sel('ch_gate_on', toggle=True)),
                            ('COMP', _sel('ch_comp_on', toggle=True)),
                            ('INSERT', dict(kind='cmd', p='ui_cmd', value=CMD['insert'], what='CHANNEL > INS / OUT')),
                            ('MAIN', dict(kind='cmd', p='ui_cmd', value=CMD['main'], what='CHANNEL > MAIN')))):
        put(c, lab, **b)
    bd.at(('button',), 518, 170, 3)['label'] = 'SHIFT'
    eq = row(bd, ('knob',), (540, 162, 715, 178), 5)
    for k, c in enumerate(eq[:4]):
        put(c, f'EQ BAND {k + 1}', kind='sel', p=f'ch_eq_g{k + 1}', lo=-15, hi=15, unit='dB', what=f'EQ band {k + 1} gain')
    eq[4]['label'] = 'BLEND / MIX'
    role(bd.at(('button',), 518, 196, 3), 'eq_on')
    for (x, lab) in ((587, 'GAIN'), (610, 'WIDTH'), (634, 'FREQ')):
        put(bd.at(('button',), x, 196, 3), lab, kind='cmd', p='ui_cmd', value=CMD['eq'], what='CHANNEL > EQ')
    put(bd.at(('button',), 702, 196, 3), 'LISTEN', **_sel('ch_solo', toggle=True, what="listen: the selected channel's solo (PFL / AFL as OMC's solo mode)"))
    # ---- fader sections: left 12, middle 8, right 4
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    assert len(fs) == 24, len(fs)
    rows_ = [(286.0, 'sel', 'SELECT'), (304.0, 'ch_solo', 'SOLO'), (360.0, 'ch_mute', 'MUTE')]
    wing_strips(bd, ctl, (('L', fs[:12]), ('M', fs[12:20]), ('R', fs[20:])), 244.0, 332.0, rows_)
    wing_layer_keys(bd, 30.0, 295.0, 19.0, WING_LEFT, 'L')
    wing_layer_keys(bd, 372.0, 295.0, 19.0, WING_MID, 'M')
    wing_layer_keys(bd, 733.0, 295.0, 19.0, WING_RIGHT, 'R')
    for (x, b) in ((30, 'L'), (372, 'M'), (733, 'R')):
        put(bd.at(('knob',), x, 244, 3), 'VIEW', kind='radio', p='screen', i=1, value=PAGE['home'], what='HOME: this section\'s strips')
        bd.at(('knob',), x, 244, 3).update(type='button', w=11.0, h=11.0)
    # ---- 4-channel section (top right): the right section's strips
    wing_quad(bd, row(bd, ('button',), (750, 80, 845, 92), 4) + row(bd, ('button',), (750, 98, 845, 112), 4),
              row(bd, ('lcd',), (745, 120, 850, 150), 4), row(bd, ('knob',), (750, 160, 845, 180), 4),
              row(bd, ('button',), (750, 188, 845, 204), 4), 'R')
    # ---- custom controls, presets, transport, DAW, navigation, jog
    for k, c in enumerate(row(bd, ('knob',), (620, 280, 715, 295), 4)):
        put(c, f'CUSTOM {k + 1}', kind='uenc', i=k + 1, what=f'custom control knob {k + 1}: user knob {k + 1} of the active bank')
    cc = row(bd, ('button',), (620, 308, 715, 320), 4) + row(bd, ('button',), (620, 326, 715, 340), 4)
    for k, c in enumerate(cc):
        put(c, f'CUSTOM {k + 1}', kind='ukey', i=k + 1, what=f'custom control key {k + 1}: user key {k + 1} of the active bank')
    for k, c in enumerate(row(bd, ('lcd',), (615, 234, 720, 254), 4)):
        put(c, 'CC DISPLAY', kind='cmd', p='ui_cmd', value=CMD['setup'], caption=f'CUSTOM {k + 1}', what='SETUP > Custom Controls')
    for k, c in enumerate(row(bd, ('lcd',), (615, 375, 720, 395), 4)):
        put(c, 'CC DISPLAY', kind='cmd', p='ui_cmd', value=CMD['setup'], caption=f'CC {k + 1}', what='SETUP > Custom Controls')
    for (x, y, lab, b) in ((604, 314, 'PRESETS UP', dict(kind='ukstep', value=1, what='custom controls: the next user-key bank')),
                           (604, 333, 'PRESETS DOWN', dict(kind='ukstep', value=-1, what='custom controls: the previous user-key bank')),
                           (604, 360, 'USER', dict(kind='cmd', p='ui_cmd', value=CMD['setup'], what='SETUP > Custom Controls')),
                           (632, 360, '2-TRACK TRANSP', dict(kind='radio', p='screen', i=1, value=PAGE['recorder'], what='UTILITY > Recorder')),
                           (655, 360, 'MULTI TRANSP', dict(kind='radio', p='screen', i=1, value=PAGE['recorder'], what='UTILITY > Recorder')),
                           (679, 360, 'MUTE GROUPS', dict(kind='radio', p='screen', i=1, value=PAGE['automutes'], what='HOME > Automutes')),
                           (702, 360, 'SHOW CNTRL', dict(kind='radio', p='screen', i=1, value=PAGE['scenes'], what='SCENES'))):
        put(bd.at(('button',), x, y, 3), lab, **b)
    bd.at(('button',), 604, 429, 3)['label'] = 'DAW (remote control)'
    # the lower custom keys (the user layer; DAW is their other layer): user keys 9-16, as WING COMPACT's CC 9-16
    for k, c in enumerate(row(bd, ('button',), (620, 412, 715, 446), 8, key=lambda c: (round(c['y']), c['x']))):
        put(c, f'CUSTOM {k + 9}', kind='ukey', i=k + 9, what=f'custom control key {k + 9} (user layer): user key {k + 9} of the active bank')
    put(bd.at(('knob',), 604, 244, 3), 'VIEW', kind='cmd', p='ui_cmd', value=CMD['setup'], what='SETUP > Custom Controls')
    bd.at(('knob',), 604, 244, 3).update(type='button', w=11.0, h=11.0)
    put(bd.at(('knob',), 604, 385, 3), 'VIEW', kind='cmd', p='ui_cmd', value=CMD['setup'], what='SETUP > Custom Controls')
    bd.at(('knob',), 604, 385, 3).update(type='button', w=11.0, h=11.0)
    place(bd, [('layer_up', 'button', 617, 465), ('layer_dn', 'button', 617, 492), ('page_l', 'button', 604, 479),
               ('page_r', 'button', 631, 479)], tol=3)
    for c in bd.where(types=('jog',)):
        put(c, 'JOG', kind='jog')
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: WING COMPACT and WING RACK (composed by compose-wing.py; see there)
# ------------------------------------------------------------------------------------------------

WINGC_LEFT = [('in1', '1-12'), ('in2', '13-24'), ('in3', '25-36'), ('auxin', '37-48 AUX IN'), ('busm', 'BUS MASTER'),
              ('mainmtx', 'MAIN MATRIX'), ('vca', 'DCA'), ('user', 'USER 1'), ('user', 'USER 2'), ('-1', '\u25c04'), ('+1', '4\u25b6')]


def view_key(bd, x, y, b, why='round VIEW key (traced from the manual figure)'):
    c = ensure(bd, 'button', x, y, 10.0, 10.0, why, tol=3)
    put(c, 'VIEW', **b)
    return c


def bind_wingc(ctl, cfg):
    bd = Binder(ctl)
    home = dict(kind='radio', p='screen', i=1, value=PAGE['home'], what="HOME: this section's strips")
    # ---- display (the WING's part)
    wing_display(bd, 60.0, 38.0, 20.85, row(bd, ('knob',), (95, 185, 300, 203), 6), right=((331.0, 38.0), None, None))
    bd.at(('knob',), 331, 143, 3)['label'] = 'display knob'
    bd.at(('button',), 331, 163, 3)['label'] = 'display key'
    # ---- USB / monitor / talkback (Fig. 18)
    view_key(bd, 372.0, 130.0, dict(ROLES['view_mon'][1]))
    wing_monitor(bd, (372.0, 130.0), ((374, 161), (400, 161), (426, 161)), ((367, 189), (389, 188), (411, 188), (433, 189)))
    # ---- left fader section: 12 strips (the WING's modules) and its 11 layer keys (Fig. 10)
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    assert len(fs) == 12, len(fs)
    rows_ = [(282.0, 'sel', 'SELECT'), (300.0, 'ch_solo', 'SOLO'), (356.0, 'ch_mute', 'MUTE')]
    strips(bd, fs, 'L', rows_, lcd=240.0, meter=328.0)
    wing_layer_keys(bd, 22.0, 291.0, 19.2, WINGC_LEFT, 'L')
    view_key(bd, 25.0, 240.0, home)
    # ---- main fader section (Fig. 11): layer keys, display, SELECT / SOLO / meter / MUTE, 16 keys, fader
    for (x, y, v, lab) in ((372, 228, 'busm', 'BUS'), (392, 228, 'vca', 'DCA'), (372, 248, 'mainmtx', 'MAIN MATRIX')):
        put(bd.at(('button',), x, y, 3), lab, kind='layer', bank='C', value=v)
    put(bd.at(('button',), 392, 248, 3), 'USER', kind='cmd', p='ui_cmd', value=CMD['layers'], what='user layers: the next user bank')
    view_key(bd, 427.0, 239.0, home)
    traced = 'traced from the manual figure (its outline is filled ink there)'
    lcd = ensure(bd, 'lcd', 382.0, 302.0, 38.0, 50.0, traced, tol=4)
    put(lcd, 'scribble strip', kind='strip', bank='C', slot=0, p='sel', select=True)
    f = dict(type='fader', x=428.5, y=round(441.0 - 7.15, 2), w=3.0, h=93.7, top=round(441.0 - 54.1, 2), bottom=round(441.0 + 39.6, 2),
             derived=traced)
    ctl.append(f)
    m = dict(type='meter', x=428.0, y=327.0, w=3.0, h=26.0, cells=[round(315.5 + 3.2 * k, 2) for k in range(8)], ch=2.2, derived=traced)
    ctl.append(m)
    strips(bd, [f], 'C', [(280.0, 'sel', 'SELECT'), (299.0, 'ch_solo', 'SOLO'), (355.0, 'ch_mute', 'MUTE')], lcd=302.0, meter=327.0)
    cc = [bd.at(('button',), x, y, 3) for y in (347, 366, 385, 404, 424, 443, 462, 481) for x in (372, 392)]
    for k, c in enumerate(cc):            # all 16: a user-key bank has 16 keys (OMC user-keys.h)
        put(c, f'CC {k + 1}', kind='ukey', i=k + 1, what=f'custom control key {k + 1}: user key {k + 1} of the active bank')
    sm.leds(bd)
    return bd


WINGR_KEYS = [('inputaux', 'INPUT AUX'), ('busmain', 'BUSES MAIN'), ('vca', 'DCA MUTE')]


def bind_wingr(ctl, cfg):
    bd = Binder(ctl)
    wing_display(bd, 46.0, 25.0, 20.85, [], right=((314.0, 25.0), None, None))
    traced = 'traced from the manual figure (Fig. 12)'
    lcds = [ensure(bd, 'lcd', x, 35.3, 20.0, 15.0, traced, tol=3) for x in (345.3, 368.5, 391.2, 414.0)]
    for k, c in enumerate(lcds):
        put(c, 'scribble strip', kind='strip', bank='R', slot=k, p='sel', select=True)
    for k, x in enumerate((345, 368, 391, 414)):
        put(bd.at(('knob',), x, 70, 3), f'CHANNEL {k + 1}', kind='strip', bank='R', slot=k, p='fader', lo=-100, hi=10,
            unit='dB', what='level of this strip')
        put(bd.at(('button',), x, 92, 3), 'MUTE', kind='strip', bank='R', slot=k, p='ch_mute', toggle=True)
        put(bd.at(('button',), x, 110, 3), 'SOLO', kind='strip', bank='R', slot=k, p='ch_solo', toggle=True)
    put(bd.at(('button',), 436, 92, 3), '\u25c04', kind='scroll', bank='R', step=-1, what='the previous 4')
    put(bd.at(('button',), 436, 110, 3), '4\u25b6', kind='scroll', bank='R', step=1, what='the next 4')
    for (x, (v, lab)) in zip((345, 368, 391), WINGR_KEYS):
        put(bd.at(('button',), x, 132, 3), lab, kind='layer', bank='R', value=v)
    put(bd.at(('button',), 413, 132, 3), 'CUST TRANS', kind='cmd', p='ui_cmd', value=CMD['setup'], what='SETUP > Custom Controls')
    put(bd.at(('button',), 436, 132, 3), 'VIEW', kind='radio', p='screen', i=1, value=PAGE['home'], what='HOME')
    c = bd.at(('knob', 'button'), 414, 154, 3)
    role(c, 'phones')
    c.update(type='pot', label='LEVEL (phones)')
    for (x, y) in ((314, 132), (314, 154)):
        c = bd.at(('knob', 'button'), x, y, 4)
        c['label'] = 'knob (no legend in the manual)'
    sm.leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# 4. bindings: XL8 (XL8_mcj.dwg, Bestec 2006: control centre plan view with its silkscreen). Three
# input bays (DL401 / DL403, 8 full channel strips each), the mix bay (DL411: 2 x 16 mix strips,
# stereo / mono masters, 12 lower faders) and the master bay (DL421: monitor, talk, automation)
# ------------------------------------------------------------------------------------------------

# an XL8 input strip, top to bottom: (type, dx from its fader, y, binding); measured on strip 1
XL8_STRIP = [
    ('button', -6.92, 319.55, dict(p='ch_phantom', toggle=True)),
    ('button', 7.08, 319.55, dict(kind='stripfn', i=FN['talk_in'], what='input talk')),
    ('knob', 0.0, 333.8, dict(p='ch_gain', lo=-18, hi=60, unit='dB')),
    ('round', 10.51, 350.3, dict(p='sel', select=True)),
    ('round', 10.51, 367.8, dict(kind='stripcmd', value=CMD['insert'], what='direct out')),
    ('button', -6.92, 367.85, dict(kind='stripcmd', value=CMD['insert'], what='direct out (mute)')),
    ('button', 8.08, 383.85, dict(p='ch_comp_on', toggle=True)),
    ('knob', -6.0, 390.8, dict(p='ch_comp_thr', lo=-50, hi=25, unit='dB')),
    ('round', 10.51, 397.8, dict(kind='stripcmd', value=CMD['comp'], what='compressor')),
    ('button', 8.08, 411.85, dict(p='ch_gate_on', toggle=True)),
    ('knob', -6.0, 418.8, dict(p='ch_gate_thr', lo=-50, hi=25, unit='dB')),
    ('round', 10.51, 425.8, dict(kind='stripcmd', value=CMD['gate'], what='gate')),
    ('round', 10.51, 449.8, dict(kind='stripcmd', value=CMD['insert'], what='insert')),
    ('button', -6.92, 449.85, dict(kind='stripfn', i=FN['insert'], what='insert in')),
    ('round', 10.51, 466.05, dict(kind='stripcmd', value=CMD['eq'], band=4, what='EQ high')),
    ('round', 10.51, 478.55, dict(kind='stripcmd', value=CMD['eq'], band=3, what='EQ hi mid')),
    ('button', -6.92, 485.55, dict(p='ch_eq_on', toggle=True)),
    ('round', 10.51, 492.55, dict(kind='stripcmd', value=CMD['eq'], band=2, what='EQ lo mid')),
    ('round', 10.51, 505.05, dict(kind='stripcmd', value=CMD['eq'], band=1, what='EQ low')),
    ('button', -8.42, 524.35, dict(kind='stripcmd', value=CMD['assign'], what='mix: sends')),
    ('knob', 5.5, 530.3, dict(p='ch_send01', lo=-100, hi=10, unit='dB')),
    ('button', -8.42, 549.85, dict(kind='stripcmd', value=CMD['assign'], what='mix: sends')),
    ('knob', 5.5, 555.8, dict(p='ch_send02', lo=-100, hi=10, unit='dB')),
    ('button', -8.42, 604.05, dict(kind='stripfn', i=FN['solo_pfl'], what='AFL')),
    ('round', 10.51, 604.05, dict(kind='stripcmd', value=CMD['main'], what='stereo / masters')),
    ('button', -5.92, 622.35, dict(kind='stripfn', i=FN['sis'], what='feed SIS')),
    ('button', 8.58, 622.35, dict(p='ch_send_lr', toggle=True)),
    ('knob', -6.0, 635.3, dict(p='ch_mono_level', lo=-100, hi=10, unit='dB')),
    ('button', 8.58, 635.35, dict(p='ch_send_mono', toggle=True)),
    ('knob', 0.0, 657.8, dict(p='ch_pan', lo=-100, hi=100, unit='')),
    ('button', -6.92, 704.05, dict(p='ch_mute', toggle=True)),
    ('button', -6.92, 782.35, dict(p='ch_solo', toggle=True)),
]


def bind_xl8(ctl, pro1):
    bd = Binder(ctl)
    ctl[:] = [c for c in ctl if c['type'] != 'fader' or c['h'] > 85]   # meter ladders drawn on the slot layer
    fs = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    low = [f for f in fs if f['y'] > 700]
    up = [f for f in fs if f['y'] < 700]
    inA, inB, vca, mon, inC = low[:8], low[8:16], low[16:28], low[28], low[28 + 1:]
    assert (len(inA), len(inB), len(vca), len(inC), len(up)) == (8, 8, 12, 8, 35), (len(low), len(up))
    # ---- input strips (3 bays of 8)
    for bank, bay in (('A', inA), ('B', inB), ('C', inC)):
        for k, f in enumerate(bay):
            f['bind'] = dict(kind='strip', bank=bank, slot=k, p='fader', lo=-100, hi=10, law='fader')
            f['label'] = 'fader'
            for (t, dx, y, b) in XL8_STRIP:
                c = bd.at((t,), f['x'] + dx, y, 2.5)
                if c is None:
                    continue
                b = dict(b)
                b.setdefault('kind', 'strip')
                b.update(bank=bank, slot=k)
                c['bind'] = b
    # ---- mix bay: 2 x 16 mix strips, stereo (left / right) and mono masters
    mixM = [f for f in up if f['x'] < 1020]
    mixN = [f for f in up if f['x'] > 1200]
    mst = [f for f in up if 1100 < f['x'] < 1200]
    assert (len(mixM), len(mixN), len(mst)) == (16, 16, 3), (len(mixM), len(mixN), len(mst))
    for bank, bay in (('M', mixM), ('N', mixN)):
        for k, f in enumerate(bay):
            f['bind'] = dict(kind='strip', bank=bank, slot=k, p='fader', lo=-100, hi=10, law='fader')
            for (y, b) in ((392.35, dict(p='ch_mute', toggle=True)), (422.85, dict(p='ch_solo', toggle=True)),
                           (331.35, dict(kind='stripcmd', value=CMD['comp'], what='dynamics')),
                           (345.85, dict(kind='stripcmd', value=CMD['eq'], what='EQ'))):
                c = bd.at(('button',), f['x'] + 0.55, y, 2.5)
                if c is not None:
                    b = dict(b); b.setdefault('kind', 'strip'); b.update(bank=bank, slot=k)
                    c['bind'] = b
            c = bd.at(('round',), f['x'], 439.3, 3.0)
            if c is not None:
                c['bind'] = dict(kind='strip', bank=bank, slot=k, p='sel', select=True)
    for f, v, side in zip(mst, (80, 80, 71), ('stereo left', 'stereo right', 'mono')):
        f['bind'] = dict(kind='fixed', p='fader', i=v + 1, lo=-100, hi=10, law='fader', what=f'master {side}')
        for (y, p) in ((392.35, 'ch_mute'), (422.85, 'ch_solo')):
            c = bd.at(('button',), f['x'] + 0.55, y, 2.5)
            if c is not None:
                c['bind'] = dict(kind='fixed', p=p, i=v + 1, toggle=True, what=f'master {side} {p[3:]}')
        c = bd.at(('round',), f['x'], 439.3, 3.0)
        if c is not None:
            c['bind'] = dict(kind='radio', p='sel', i=1, value=v, what=f'select master {side}')
    # ---- the 12 lower mix-bay faders: VCA (OMC has 8) with MUTE / SOLO
    for k, f in enumerate(vca):
        f['bind'] = dict(kind='strip', bank='V', slot=k, p='fader', lo=-100, hi=10, law='fader')
        for (y, p) in ((704.05, 'ch_mute'), (782.35, 'ch_solo')):
            c = bd.at(('button',), f['x'] - 6.4, y, 2.5)
            if c is not None:
                c['bind'] = dict(kind='strip', bank='V', slot=k, p=p, toggle=True)
    # ---- monitor fader with DIM / MUTE
    mon['bind'] = dict(kind='fixed', p='mon_level', i=1, lo=-100, hi=10, law='fader', what='monitor level')
    for (x, y, fn, what) in ((1389.95, 771.35, 'mon_dim', 'monitor dim'), (1389.95, 782.35, 'mon_mute', 'monitor mute'),
                             (1403.95, 782.35, 'monb_mute', 'monitor B mute')):
        c = bd.at(('button',), x, y, 2.5)
        if c is not None:
            c['bind'] = dict(kind='surface', i=FN[fn], toggle=True, what=what)
    # ---- the selected-channel part of the mix bay by legend: the PRO1's selected-channel strip (same Bestec
    # part library and legends); only the selected-channel functions are taken over
    sm.transfer_by_label(bd, pro1, (400, 90, 490, 340), (1025, 255, 1115, 640), (625, 165))
    for c in ctl:
        if c.get('from') and (c.get('bind') or {}).get('kind') in ('strip', 'layer', 'scroll', 'bay', 'sends', 'fixed'):
            c['bind'] = None
            del c['from']
    # ---- input bays: scroll by 8, channel select keypad, the jog wheels
    for bank, dx in (('A', 0.0), ('B', 346.0), ('C', 1382.5)):
        for (x, step) in ((364.0, -1), (386.0, 1)):
            c = bd.at(('button',), x + dx, 796.35, 2.5)
            if c is not None:
                c['bind'] = dict(kind='scroll', bank=bank, step=step, what='input select: scroll by 8')
        for r, y in enumerate((813.85, 828.85, 843.85, 858.85)):
            for k in range(3):
                key = '123456789*0E'[r * 3 + k]
                c = bd.at(('button',), 360.25 + 15.0 * k + dx, y, 2.5)
                if c is not None:
                    c['label'] = {'E': 'ENTER'}.get(key, key)
                    c['bind'] = dict(kind='keypad', key=key, bank=bank,
                                     what='ENTER: select the input typed' if key == 'E' else 'clear' if key == '*' else f'digit {key}')
    for c in bd.where(types=('jog',)):
        c['bind'] = dict(kind='jog')
    xl8_master_bay(bd)
    sm.leds(bd)
    return bd


# the XL8 master bay (DL421) by legend and position: automation, mute group masters, oscillator, talk, monitor / solo,
# screen keys. What OMC has no function for stays unbound (docs/25): intercom (CALL / TALK / channel), the generator's
# type / frequency / level, talk and oscillator routing (ALL / INPUT / AUX / MTX, 1-4), the second talk mic, monitor
# sources (A / B / ST / EXT / MON / LEFT), monitor B's row, the second DIM / MUTE pair, the mute groups' SELECT keys
XL8_SCREEN = {'automation': PAGE['show'], 'inputs': PAGE['channel'], 'outputs': PAGE['buses'], 'effects': PAGE['effects'],
              'graphics': 23, 'metering': PAGE['meters'], 'monitors': PAGE['monitor'], 'filing': 42}   # 23 EFFECTS > GEQ, 42 LIBRARY > Shows


def xl8_master_bay(bd):
    def key(x, y, types=('button',), tol=2.5):
        c = bd.at(types, x, y, tol)
        if c is None:
            raise SystemExit(f'XL8 master bay: no {types} near {x},{y}')
        return c
    # ---- automation: LAST NOW NEXT STORE OK CANCEL as on the PRO surfaces (ui_cmd 5..10; remappable in OMC)
    for (x, y, v, what) in ((1138.2, 853.3, 'last', 'Last cue'), (1159.2, 853.3, 'now', 'Now: recall scene'),
                            (1138.2, 817.3, 'store', 'Store scene'), (1138.2, 835.3, 'ok', 'OK: commit preview'),
                            (1159.2, 835.3, 'cancel', 'Cancel: discard preview')):
        c = key(x, y)
        c['bind'] = dict(kind='cmd', p='ui_cmd', value=CMD[v], what=what)
    c = key(1159.2, 817.3)          # the block's sixth key carries no legend in the drawing
    put(c, 'next', kind='cmd', p='ui_cmd', value=CMD['next'], what='Next cue')
    c['derived'] = 'no legend in the drawing: the automation block\'s sixth key, taken as NEXT'
    # ---- the 8 mute group masters (OMC's desk-model masters, the action list's MUTE GROUP 1-8)
    for k, x in enumerate((1134.0, 1149.0, 1164.0, 1179.0, 1194.0, 1209.0, 1224.0, 1239.0)):
        c = key(x, 782.4)
        c['bind'] = _act(ACT['mute_group1'] + k, f'mute group {k + 1} master')
        c['tint'] = 'red'
    # ---- oscillator / talk (the PRO1's functions)
    for (x, y, fn, what) in ((1181.5, 698.5, 'osc_int', 'oscillator internal'), (1195.5, 698.5, 'osc_ext', 'oscillator external'),
                             (1271.0, 698.5, 'talk_int', 'talk internal'), (1285.0, 698.5, 'talk_ext', 'talk external')):
        key(x, y)['bind'] = dict(kind='surface', i=FN[fn], toggle=True, what=what)
    for (x, y, fn, what) in ((1300.7, 698.5, 'talk_level', 'talk level'), (1318.7, 698.5, 'talk_limiter', 'talk limiter'),
                             (1336.7, 698.5, 'talk_gain', 'talk mic gain'), (1213.2, 817.8, 'phones', 'phones level')):
        key(x, y, KNOBS)['bind'] = dict(kind='surface', i=FN[fn], what=what)
    # ---- monitor / solo: MONO (monitor A's row), solo mode PFL / AFL, solo ADD
    key(1328.0, 778.4)['bind'] = _act(ACT['mon_mono'], 'monitor mono (OMC action list)')
    key(1365.5, 814.0)['bind'] = dict(kind='surface', i=FN['solo_pfl'], toggle=True, what='solo mode: PFL / AFL')
    key(1258.2, 788.4)['bind'] = dict(kind='surface', i=FN['solo_add'], toggle=True, what='solo ADD')
    # ---- screen keys
    for c in bd.where(types=('round',), box=(1260, 880, 1272, 948)):
        page = XL8_SCREEN.get(c.get('label') or '')
        if page is not None:
            c['bind'] = dict(kind='radio', p='screen', i=1, value=page, what=c['label'])


BINDERS = {'xl8': bind_xl8, 'wingc': bind_wingc, 'wingr': bind_wingr, 'wing': bind_wing, 'x32': bind_x32, 'm32': bind_m32, 'x32c': bind_x32c, 'm32r': bind_m32r, 'x32r': bind_x32r}


# ------------------------------------------------------------------------------------------------
# 5. SVG: the PRO writer without the caps the drawing shows mid-travel
# ------------------------------------------------------------------------------------------------

def drop_caps(polys, boxes, ctl=()):
    """the line art without the caps the drawing shows; the slot runs on where a cap hid it"""
    def inside(pts, b):
        return pts[:, 0].min() >= b[0] and pts[:, 0].max() <= b[2] and pts[:, 1].min() >= b[1] and pts[:, 1].max() <= b[3]
    out = [(l, p) for (l, p) in polys if not any(inside(p, b) for b in boxes)]
    for f in (c for c in ctl if c['type'] == 'fader' and c.get('slot')):
        hw = f['slot'][2] / 2
        for b in boxes:
            if b[0] < f['x'] < b[2] and f['slot'][0] - 5 < (b[1] + b[3]) / 2 < f['slot'][1] + 5:
                for x in (f['x'] - hw, f['x'] + hw):
                    out.append(('SLOT', np.array([(x, b[1]), (x, b[3])])))
    return out


def write_svg(polys, labels, ctl, screen, W, H, fn):
    # the PRO writer's own cap rule (below a PRO slot) must not touch these drawings: its faders have
    # no 'bottom' cap zone here, so hand it controls without faders and draw the faders' slots as is
    sm.write_svg(polys, labels, [c for c in ctl if c['type'] != 'fader'], screen, W, H, fn)


# ------------------------------------------------------------------------------------------------
# bank layouts (surface.js): layers are channel lists ({inputs, first, count} and / or {chs})
# ------------------------------------------------------------------------------------------------

def surface_config(model, cfg):
    s = dict(model=cfg['name'], id=model, inputs=cfg['inputs'])
    s.update(LAYOUTS[cfg['family']](cfg))
    return s


def layout_x32(cfg):
    return dict(
        layers=dict(ch1=dict(inputs=cfg['inputs'], first=0, count=16), ch2=dict(inputs=cfg['inputs'], first=16, count=16),
                    auxfx=dict(chs=list(range(32, 48))), busm=dict(chs=list(range(48, 64))),
                    vca=dict(chs=list(range(72, 80))), bus1=dict(chs=list(range(48, 56))), bus2=dict(chs=list(range(56, 64))),
                    mtx=dict(chs=list(range(64, 70)) + [71]), input=dict(inputs=cfg['inputs'])),
        banks=dict(I=dict(slots=16, layer='ch1'), G=dict(slots=8, layer='vca')),
        bays=dict(I=['I', 0], G=['G', 0]),
        extend=None,
    )


def layout_x32c(cfg):
    return dict(
        layers=dict(ch1=dict(inputs=32, first=0, count=8), ch2=dict(inputs=32, first=8, count=8),
                    ch3=dict(inputs=32, first=16, count=8), ch4=dict(inputs=32, first=24, count=8),
                    aux=dict(chs=list(range(32, 40))), fxret=dict(chs=list(range(40, 48))),
                    bus1=dict(chs=list(range(48, 56))), bus2=dict(chs=list(range(56, 64))),
                    vca=dict(chs=list(range(72, 80))), mtx=dict(chs=list(range(64, 70)) + [71]), input=dict(inputs=32)),
        banks=dict(I=dict(slots=8, layer='ch1'), G=dict(slots=8, layer='vca')),
        bays=dict(I=['I', 0], G=['G', 0]),
        extend=None,
    )


def layout_none(cfg):
    """no faders (X32 RACK): the layers exist for the touch UI's banks only"""
    return dict(layers=dict(input=dict(inputs=cfg['inputs'])), banks={}, bays={}, extend=None)


def layout_wing(cfg):
    n = cfg['inputs']
    auxin = dict(inputs=n, first=36, count=n - 36, chs=list(range(32, 40)))
    return dict(
        layers=dict(in1=dict(inputs=n, first=0, count=12), in2=dict(inputs=n, first=12, count=12),
                    in3=dict(inputs=n, first=24, count=12), auxin=auxin, busm=dict(chs=list(range(48, 64))),
                    vca=dict(chs=list(range(72, 80))), mainmtx=dict(chs=[80, 71] + list(range(64, 70))),
                    inputs=dict(inputs=n), input=dict(inputs=n)),
        banks=dict(L=dict(slots=12, layer='in1'), M=dict(slots=8, layer='vca'), R=dict(slots=4, layer='mainmtx')),
        bays=dict(L=['L', 0], M=['M', 0], R=['R', 0]),
        extend=None,
    )


def layout_wingc(cfg):
    d = layout_wing(cfg)
    d['banks'] = dict(L=dict(slots=12, layer='in1'), C=dict(slots=1, layer='mainmtx'))
    d['bays'] = dict(L=['L', 0], C=['C', 0])
    return d


def layout_wingr(cfg):
    d = layout_wing(cfg)
    n = cfg['inputs']
    d['layers'].update(inputaux=dict(inputs=n, chs=list(range(32, 40))), busmain=dict(chs=list(range(48, 64)) + [80, 71] + list(range(64, 70))))
    d['banks'] = dict(R=dict(slots=4, layer='inputaux'))
    d['bays'] = dict(R=['R', 0])
    return d


def layout_xl8(cfg):
    return dict(
        layers=dict(input=dict(inputs=cfg['inputs']), aux=dict(chs=list(range(48, 64))),
                    mtx=dict(chs=list(range(64, 70)) + [80, 71]), vca=dict(chs=list(range(72, 80))), ret=dict(chs=list(range(32, 48)))),
        options=[dict(id='bays', label='input bays', values=[
            dict(id='joined', label='A + B + C: 24 inputs in a row', banks=dict(
                L=dict(slots=24, layer='input', touch=1), M=dict(slots=16, layer='aux'), N=dict(slots=16, layer='mtx'),
                V=dict(slots=12, layer='vca')), bays=dict(A=['L', 0], B=['L', 8], C=['L', 16], M=['M', 0], N=['N', 0], V=['V', 0]),
                extend=None),
            dict(id='split', label='A, B and C page separately', banks=dict(
                A=dict(slots=8, layer='input', touch=1), B=dict(slots=8, layer='input', page=1, touch=9),
                C=dict(slots=8, layer='input', page=2), M=dict(slots=16, layer='aux'), N=dict(slots=16, layer='mtx'),
                V=dict(slots=12, layer='vca')), bays=dict(A=['A', 0], B=['B', 0], C=['C', 0], M=['M', 0], N=['N', 0], V=['V', 0]),
                extend=['A', 'B'])])],
        banks=dict(L=dict(slots=24, layer='input', touch=1)), bays=dict(A=['L', 0], B=['L', 8], C=['L', 16]), extend=None,
    )


LAYOUTS = {'xl8': layout_xl8, 'wingc': layout_wingc, 'wingr': layout_wingr, 'wing': layout_wing, 'x32': layout_x32, 'm32': layout_x32, 'x32c': layout_x32c, 'm32r': layout_x32c, 'x32r': layout_none}


# ------------------------------------------------------------------------------------------------
# build
# ------------------------------------------------------------------------------------------------

def build(model, src, outdir, pro1_controls):
    cfg = MODELS[model]
    W, H, polys, texts, circles = load(src, cfg)
    img = sm.raster(polys, W, H)
    reg = contour_regions(img) if cfg.get('contours') else (regions(img, cfg['big']) if cfg.get('big') else sm.regions(img))
    ctl = detect_bestec(reg, polys, circles, W, H, cfg) if cfg.get('bestec') else detect(reg, cfg, W, H)
    if cfg.get('bestec'):
        sm.attach_labels(ctl, texts)
    boxes = cap_boxes(reg, ctl, cfg)
    for b in boxes:   # parts of a drawn cap are not controls
        ctl[:] = [c for c in ctl if c['type'] == 'fader' or not (b[0] <= c['x'] <= b[2] and b[1] <= c['y'] <= b[3])]
    for (x0, y0, x1, y1) in cfg.get('exclude', ()):
        ctl[:] = [c for c in ctl if not (x0 < c['x'] < x1 and y0 < c['y'] < y1)]
    screen = find_screen(img, cfg['screen_box']) if cfg.get('screen_box') else cfg.get('screen')
    BINDERS[cfg['family']](ctl, pro1_controls if cfg.get('bestec') else cfg)
    sm.colour(ctl)
    for c in ctl:
        c.setdefault('bind', None)
        if c['type'] == 'meter':
            b = c['bind'] or {}
            c['scale'] = 'strip' if b.get('p') == 'ch_meter' and b.get('kind') == 'strip' else 'master'
    for i, c in enumerate(sorted(ctl, key=lambda c: (round(c['y']), c['x']))):
        c['id'] = i
    ctl.sort(key=lambda c: c['id'])
    art = drop_caps(polys, boxes, ctl)
    for c in ctl:
        c.pop('slot', None)
        c.pop('pieces', None)
    if cfg.get('bestec'):
        sm.write_svg(polys, texts, ctl, screen, W, H, f'{outdir}/panel.svg')   # the PRO writer: caps below the slot
    else:
        write_svg(art, texts, ctl, screen, W, H, f'{outdir}/panel.svg')
    surface = surface_config(model, cfg)
    surface['plate'] = None
    if cfg.get('source'):
        surface['source'] = cfg['source']
    with open(f'{outdir}/controls.json', 'w') as f:
        json.dump(dict(width=round(W, 2), height=round(H, 2), screen=[round(v, 2) for v in screen] if screen else None,
                       surface=surface, controls=ctl), f, indent=0)
    kinds = {}
    for c in ctl:
        kinds[c['type']] = kinds.get(c['type'], 0) + 1
    bound = sum(1 for c in ctl if c['bind'])
    print(cfg['name'], 'controls', len(ctl), kinds, 'bound', bound, 'unbound', len(ctl) - bound, 'screen', screen)
    return ctl
