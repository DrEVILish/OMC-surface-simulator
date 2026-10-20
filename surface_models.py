"""
Surfaces of the other PRO control centres for the web replica: PRO2, PRO2C (derived) and PRO X.

gen-surface.py --model <pro2|pro2c|prox> calls build() here. The PRO1 keeps its own, hand-checked
pipeline in gen-surface.py (unchanged); these models use the same steps with per-model settings:

  1. plan view   the top view of the vendor drawing (window in drawing mm), block references
                 expanded; PRO2-Control-Centre.dwg needs dwgfill.py first (LibreDWG drops its
                 panel blocks when it writes the DXF)
  2. controls    the plan view rasterised at 10 px/mm, enclosed regions classified by size, fill
                 and aspect (the PRO1 classes: the drawings share Bestec's part library), faders
                 from their slot lines, meters from their cell columns, jog wheels from circles
  3. labels      the nearest silkscreen legend of each control
  4. bindings    by silkscreen and position: fader strips are found from the faders, the controls
                 of each strip are the ones in its column; panels are found from their legends
  5. PRO2C       derived from the PRO2 (no drawing): the PRO2 without its left input bay

Bindings use the OSC paths the PRO1 surface uses (docs/25). Inputs past OMC's 32 engine channels
are the touch UI desk model's inputs, mirrored as mch_* (surface.js maps them).
"""
import json
import math
import re

import cv2
import numpy as np
from ezdxf import disassemble, path, recover

PX = 10.0
# EQ band legends as OMC names them (as gen-surface.py): the PRO X drawing prints bass / treble
LEGEND_RENAME = {'bass': 'low', 'treble': 'high', 'Bass': 'Low', 'Treble': 'High', 'BASS': 'LOW', 'TREBLE': 'HIGH'}

# ------------------------------------------------------------------------------------------------
# per-model settings
# ------------------------------------------------------------------------------------------------

MODELS = {
    'pro2': dict(
        name='PRO2', dwg='PRO2-Control-Centre.dwg', fill=True,
        # plan view window in drawing mm (x0, y0, x1, y1): the chassis outline of the top view
        window=(434.55, 1450.74, 1614.2, 2153.38),
        inputs=56, submixes=16, matrices=8,
        exclude=[(0, 0, 1180, 50), (1052, 82, 1084, 110), (1100, 150, 1180, 260)],
    ),
    'prox': dict(
        name='PRO X', dwg='PROx-Control-Centre.dwg', fill=False,
        window=(254.8, 2062.5, 1620.0, 2986.5),
        inputs=144, submixes=72, matrices=24,
    ),
}
MODELS['pro2c'] = dict(MODELS['pro2'], name='PRO2C', derived='pro2')


# ------------------------------------------------------------------------------------------------
# 1. plan view
# ------------------------------------------------------------------------------------------------

def load_plan(src, cfg):
    x0, y0, x1, y1 = cfg['window']
    W, H = x1 - x0, y1 - y0
    doc, _ = recover.readfile(src)
    polys, texts, circles = [], [], []
    for e in disassemble.recursive_decompose(doc.modelspace()):
        t = e.dxftype()
        if t in ('MTEXT', 'TEXT'):
            p = e.dxf.insert
            if not (x0 < p.x < x1 and y0 < p.y < y1):
                continue
            if t == 'MTEXT':
                s, h, ap = e.plain_text(), e.dxf.get('char_height', 2.5), e.dxf.get('attachment_point', 1)
            else:
                s, h, ap = e.dxf.text, e.dxf.get('height', 2.5), 7
            s = s.replace('\\P', '\n').strip()
            s = LEGEND_RENAME.get(s, s)
            if s:
                texts.append(dict(x=p.x - x0, y=y1 - p.y, h=h, ap=ap, rot=e.dxf.get('rotation', 0.0), s=s))
            continue
        if t in ('DIMENSION', 'HATCH', 'WIPEOUT', 'INSERT', 'SOLID', 'POINT'):
            continue
        try:
            p = path.make_path(e)
        except Exception:
            continue
        pts = np.array([(v.x - x0, y1 - v.y) for v in p.flattening(0.03)])
        if len(pts) < 2:
            continue
        if pts[:, 0].min() < -0.5 or pts[:, 0].max() > W + 0.5 or pts[:, 1].min() < -0.5 or pts[:, 1].max() > H + 0.5:
            continue
        polys.append((e.dxf.layer, pts))
        if t == 'CIRCLE':
            circles.append((e.dxf.center.x - x0, y1 - e.dxf.center.y, e.dxf.radius))
    return W, H, polys, texts, circles


def raster(polys, W, H):
    img = np.full((int(H * PX) + 1, int(W * PX) + 1), 255, np.uint8)
    for _, pts in polys:
        cv2.polylines(img, [np.round(pts * PX).astype(np.int32)], False, 0, 1, cv2.LINE_AA)
    return img


def regions(img):
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats((1 - blk).astype(np.uint8), connectivity=4)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w < 20 or h < 20 or w > 600 or h > 600:
            continue
        out.append(dict(cx=cen[i][0] / PX, cy=cen[i][1] / PX, w=w / PX, h=h / PX, fill=a / (w * h), x=x / PX, y=y / PX))
    return out


# ------------------------------------------------------------------------------------------------
# 2. controls
# ------------------------------------------------------------------------------------------------

def classify(r):
    w, h, f = r['w'], r['h'], r['fill']
    ar = w / h
    if 19 < w < 20.5 and 15 < h < 16.5 and f > 0.95:
        return 'lcd', {}
    if f > 0.9 and 8.5 < w < 15 and 4.8 < h < 13:
        return 'button', {}
    if 9 < w < 10.5 and 5.5 < h < 6.6 and 0.74 < f < 0.84:
        return 'ledbutton', {}
    if 0.74 < f < 0.82 and 0.88 < ar < 1.15 and 7.0 < w < 10.0:
        return 'knob', dict(scale=1.55, cap=round(w, 2))
    if 0.6 < f < 0.7 and 8.5 < w < 10.5 and 7.8 < h < 9.2:
        return 'pot', dict(scale=1.25)
    if 0.74 < f < 0.82 and 0.88 < ar < 1.15 and 5.5 < w < 6.6:
        return 'round', {}
    if 0.55 < f < 0.62 and 13.5 < w < 17 and 13.5 < h < 17:
        dx, dy = r['cx'] - (r['x'] + w / 2), r['cy'] - (r['y'] + h / 2)
        d = ('left' if dx > 0 else 'right') if abs(dx) > abs(dy) else ('up' if dy > 0 else 'down')
        return 'arrow', dict(dir=d)
    if 0.7 < f < 0.85 and 0.8 < ar < 1.25 and 2.4 < w < 3.6:
        return 'led', {}
    return None, None


def find_controls(reg, polys, circles, W, H):
    ctl = []

    def add(kind, cx, cy, w, h, **kw):
        ctl.append(dict(type=kind, x=round(cx, 2), y=round(cy, 2), w=round(w, 2), h=round(h, 2), **kw))

    for r in reg:
        kind, kw = classify(r)
        if not kind:
            continue
        sc = kw.pop('scale', 1.0)
        w, h = (r['w'] * sc, r['h'] * sc) if kind != 'pot' else (r['w'] * sc, r['w'] * sc)
        add(kind, r['cx'], r['cy'], w, h, **kw)

    # meter ladders: columns of ~3 mm cells, split where the column has a gap
    cells = [r for r in reg if r['fill'] > 0.9 and 2.4 < r['w'] < 3.6 and 1.3 < r['h'] < 3.6]
    cols = {}
    for c in cells:
        cols.setdefault(round(c['cx'] * 2) / 2, []).append(c)
    for x, cs in cols.items():
        cs.sort(key=lambda c: c['cy'])
        runs, run = [], [cs[0]]
        for a, b in zip(cs, cs[1:]):
            if b['y'] - (a['y'] + a['h']) > 3.0:
                runs.append(run)
                run = []
            run.append(b)
        runs.append(run)
        for cs in runs:
            if len(cs) < 8:
                continue
            add('meter', x, (cs[0]['y'] + cs[-1]['y'] + cs[-1]['h']) / 2, cs[0]['w'], cs[-1]['y'] + cs[-1]['h'] - cs[0]['y'],
                cells=[round(c['cy'], 2) for c in cs], ch=round(cs[0]['h'], 2))

    # faders: pairs of vertical slot lines 2.5-3.5 mm apart (PARTS-CN), travel between their ends
    slots = {}
    for layer, pts in polys:
        if layer != 'PARTS-CN' or len(pts) != 2:
            continue
        (xa, ya), (xb, yb) = pts
        if abs(xa - xb) < 0.05 and abs(ya - yb) > 60:
            slots.setdefault((round(min(ya, yb), 0), round(max(ya, yb), 0)), []).append(xa)
    for (ya, yb), xs in slots.items():
        xs.sort()
        for i in range(0, len(xs) - 1):
            if 2.5 < xs[i + 1] - xs[i] < 3.5:
                add('fader', (xs[i] + xs[i + 1]) / 2, (ya + yb) / 2, 3.0, yb - ya, top=ya, bottom=yb)

    # jog wheels: the 44 mm wheel (22 mm circle with the 17.1 mm wheel inside), as on the PRO1
    for (x, y, r) in circles:
        if abs(r - 22.0) < 0.3:
            add('jog', x, y, 44.0, 44.0)

    faders = [c for c in ctl if c['type'] == 'fader']
    # gaps between fader scale lines are not buttons
    ctl[:] = [c for c in ctl if not (c['type'] in ('button', 'ledbutton') and any(
        abs(c['x'] - f['x']) < 14 and f['top'] - 6 < c['y'] < f['bottom'] + 6 for f in faders))]
    # screw heads (3.2-3.6 mm circles) and fader-top fixings are not LEDs
    screws = [(x, y) for (x, y, r) in circles if 3.1 < r < 3.7]
    ctl[:] = [c for c in ctl if not (c['type'] == 'led' and (
        any(abs(c['x'] - sx) < 1.0 and abs(c['y'] - sy) < 1.0 for sx, sy in screws)
        or any(abs(c['x'] - f['x']) < 3 and f['top'] - 9 < c['y'] < f['top'] for f in faders)))]
    # inside a jog wheel nothing else is a control
    jogs = [c for c in ctl if c['type'] == 'jog']
    ctl[:] = [c for c in ctl if c['type'] == 'jog' or not any(math.hypot(c['x'] - j['x'], c['y'] - j['y']) < 22 for j in jogs)]

    out = []
    for c in sorted(ctl, key=lambda c: -c['w'] * c['h']):
        if any(abs(c['x'] - o['x']) < 1.5 and abs(c['y'] - o['y']) < 1.5 and c['type'] == o['type'] for o in out):
            continue
        out.append(c)
    return out


# ------------------------------------------------------------------------------------------------
# 3. labels
# ------------------------------------------------------------------------------------------------

def attach_labels(ctl, labels):
    for c in ctl:
        if c['type'] in ('meter', 'led', 'fader'):
            continue
        best, bd = None, 1e9
        for t in labels:
            if t['h'] > 3.5:
                continue
            dx, dy = t['x'] - c['x'], t['y'] - c['y']
            inside = abs(dx) < c['w'] / 2 + 1 and abs(dy) < c['h'] / 2 + 1
            d = 0 if inside else math.hypot(dx, dy)
            if d < bd:
                best, bd = t, d
        if best is not None and bd < max(9.0, c['w']):
            c['label'] = best['s'].replace('\n', ' ')


def screen_region(img, W, H):
    """the display opening: the largest enclosed region in the upper half that is not the plate"""
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats((1 - blk).astype(np.uint8), connectivity=4)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w > 2000 and h > 1400 and w < W * PX * 0.5 and y < H * PX * 0.5 and a / (w * h) > 0.9:
            if best is None or w * h < best[2] * best[3]:
                best = (x, y, w, h)
    if best is None:
        return None
    return tuple(round(v / PX, 2) for v in best)


# ------------------------------------------------------------------------------------------------
# 4. bindings
# ------------------------------------------------------------------------------------------------

BTN = ('button', 'ledbutton', 'round', 'lcd', 'arrow')
KNOBS = ('knob', 'pot')

# PRO1 functions by number (docs/25): OSC surface/<n> (desk-model functions of the touch UI)
FN = dict(talk_in=7, meter_check=10, talk_gain=11, talk_limiter=16, mon_mute=18, monb_mute=19, talk_level=21,
          mon_dim=22, monb_co=23, talk_int=26, talk_ext=28, osc_int=31, osc_ext=36, insert=40, solo_add=48,
          solo_pfl=50, phones=52, sis=53, phones_mute=55, solo_fader=57, alt=63)
# touch UI commands (OSC ui_cmd): Channel tabs, pages
CMD = dict(input=20, gate=21, comp=22, eq=23, insert=24, main=25, assign=27, setup=30, layers=32, effects=33,
           home=11, enter=9, last=5, now=6, next=7, store=8, ok=9, cancel=10)
SCREEN_KEYS = {'automation': 8, 'effects': 4, 'routing': 3, 'inputs': 1, 'monitors': 5, "vca's": 16}


class Binder:
    def __init__(self, ctl):
        self.ctl = ctl

    def at(self, types, x, y, tol=2.5):
        best, bd = None, tol
        for c in self.ctl:
            if c['type'] in types and abs(c['x'] - x) < tol and abs(c['y'] - y) < tol:
                d = max(abs(c['x'] - x), abs(c['y'] - y))
                if d <= bd:
                    best, bd = c, d
        return best

    def B(self, types, x, y, tol=2.5, force=False, **b):
        c = self.at(types, x, y, tol)
        if c is None:
            raise SystemExit(f'no {types} near {x:.1f},{y:.1f}')
        if force or not c.get('bind'):
            c['bind'] = b
        return c

    def where(self, types=None, label=None, box=None, unbound=True):
        out = []
        for c in self.ctl:
            if types and c['type'] not in types:
                continue
            if unbound and c.get('bind'):
                continue
            if label is not None and not re.fullmatch(label, c.get('label') or '', re.I):
                continue
            if box and not (box[0] <= c['x'] <= box[2] and box[1] <= c['y'] <= box[3]):
                continue
            out.append(c)
        return sorted(out, key=lambda c: (c['y'], c['x']))

    def each(self, b, **kw):
        for c in self.where(**kw):
            c['bind'] = dict(b)


def strip_bays(ctl, gap=1.25):
    """the channel faders in left-to-right bays (a gap wider than 1.25 x the pitch starts a bay)"""
    f = sorted((c for c in ctl if c['type'] == 'fader'), key=lambda c: c['x'])
    bays, cur = [], [f[0]]
    for a, b in zip(f, f[1:]):
        pitch = cur[1]['x'] - cur[0]['x'] if len(cur) > 1 else 30
        if b['x'] - a['x'] > gap * pitch or abs(b['h'] - a['h']) > 5:
            bays.append(cur)
            cur = []
        cur.append(b)
    bays.append(cur)
    return bays


def bind_strip(bd, f, bay, slot, lcd_y=None, mute_y=None, solo_y=None, meter=True):
    """fader, LCD select key, MUTE / SOLO keys and meter ladder of one fader strip"""
    x = f['x']
    f['bind'] = dict(kind='strip', bank=bay, slot=slot, p='fader', lo=-100, hi=10, law='fader')
    col = [c for c in bd.ctl if abs(c['x'] - x) < 11 and c['y'] < f['top'] and not c.get('bind')]
    if lcd_y is not None:
        c = bd.at(('lcd',), x, lcd_y, 4)
        if c is not None:
            c['bind'] = dict(kind='strip', bank=bay, slot=slot, p='sel', select=True)
    for y, p in ((mute_y, 'ch_mute'), (solo_y, 'ch_solo')):
        if y is None:
            continue
        cs = [c for c in col if c['type'] in ('button', 'ledbutton') and abs(c['y'] - y) < 3]
        if cs:
            min(cs, key=lambda c: abs(c['x'] - x))['bind'] = dict(kind='strip', bank=bay, slot=slot, p=p, toggle=True)
    if meter:
        ms = [c for c in col if c['type'] == 'meter' and abs(c['x'] - x) < 11 and f['top'] - 120 < c['y'] < f['top']]
        if ms:
            min(ms, key=lambda c: f['top'] - c['y'])['bind'] = dict(kind='strip', bank=bay, slot=slot, p='ch_meter')


def transfer_pro1(bd, pro1, region, off, labels_only=False, tol=2.5):
    """copy the PRO1's bindings onto the same part at an offset (the PRO2 reuses PRO1 modules)"""
    n = 0
    for a in pro1:
        if not (region[0] < a['x'] < region[2] and region[1] < a['y'] < region[3]) or not a.get('bind'):
            continue
        if a['type'] == 'meter':
            continue
        c = bd.at((a['type'],), a['x'] + off[0], a['y'] + off[1], tol)
        if c is None or c.get('bind'):
            continue
        if labels_only and c.get('label') != a.get('label'):
            continue
        b = dict(a['bind'])
        if b.get('kind') == 'mirror':
            continue                      # LEDs are re-paired with their keys below
        c['bind'] = b
        if a.get('tint'):
            c['tint'] = a['tint']
        c['from'] = 'PRO1'
        n += 1
    return n


def transfer_by_label(bd, pro1, region1, box, off):
    """copy PRO1 detail-area bindings by legend (+ type); a legend used twice goes to the nearer one"""
    src = [a for a in pro1 if region1[0] < a['x'] < region1[2] and region1[1] < a['y'] < region1[3]
           and a.get('bind') and a['type'] not in ('led', 'meter')]
    n = 0
    for c in bd.where(box=box):
        if c['type'] in ('led', 'meter', 'fader'):
            continue
        cand = [a for a in src if a['type'] == c['type'] and (a.get('label') or None) == (c.get('label') or None)]
        if not cand:
            continue
        a = min(cand, key=lambda a: math.hypot(a['x'] + off[0] - c['x'], a['y'] + off[1] - c['y']))
        if not c.get('label') and math.hypot(a['x'] + off[0] - c['x'], a['y'] + off[1] - c['y']) > 8:
            continue                      # an unlabelled part only where the PRO1 has the same part
        c['bind'] = dict(a['bind'])
        if a.get('tint'):
            c['tint'] = a['tint']
        c['from'] = 'PRO1'
        n += 1
    return n


def leds(bd, band_box=None):
    keys = [c for c in bd.ctl if c['type'] in ('button', 'ledbutton', 'round') and c.get('bind')]
    for c in bd.ctl:
        if c['type'] != 'led' or c.get('bind'):
            continue
        if band_box and band_box[0] < c['x'] < band_box[2] and band_box[1] < c['y'] < band_box[3]:
            c['bind'] = dict(kind='bandled')
            continue
        if not keys:
            continue
        k = min(keys, key=lambda k: abs(k['x'] - c['x']) + abs(k['y'] - c['y']))
        if abs(k['x'] - c['x']) + abs(k['y'] - c['y']) < 16:
            c['bind'] = dict(kind='mirror', x=k['x'], y=k['y'])


def output_strips(bd, box, rows, what):
    """the output strip grid (TALK / MUTE / SOLO / select key + meter per bus or matrix):
    rows = [(row y range, [vchannel per column])]"""
    for (y0, y1), chans in rows:
        cols = sorted({round(c['x']) for c in bd.where(types=('meter',), box=(box[0], y0, box[2], y1))})
        for k, mx in enumerate(cols):
            v = chans[k] if k < len(chans) else -1
            if v < 0:
                continue
            col = [c for c in bd.ctl if abs(c['x'] - mx) < 12 and y0 <= c['y'] <= y1 and not c.get('bind')]
            for c in col:
                lab = (c.get('label') or '').upper()
                if c['type'] == 'meter' and abs(c['x'] - mx) < 1:
                    c['bind'] = dict(kind='meter', p='ch_meter', i=v + 1, what=f'{what(v)} meter')
                elif c['type'] in ('button', 'ledbutton') and lab == 'MUTE' and c['x'] < mx:
                    c['bind'] = dict(kind='fixed', p='ch_mute', i=v + 1, toggle=True, what=f'{what(v)} mute')
                elif c['type'] in ('button', 'ledbutton') and lab == 'SOLO' and c['x'] < mx:
                    c['bind'] = dict(kind='fixed', p='ch_solo', i=v + 1, toggle=True, what=f'{what(v)} solo')
                elif c['type'] in ('button', 'ledbutton', 'lcd') and lab in ('SELECT', 'TALK') and (
                        lab == 'SELECT' or c['type'] == 'lcd'):
                    c['bind'] = dict(kind='radio', p='sel', i=1, value=v, what=f'select {what(v)}')


def vch_name(v):
    if v < 32:
        return f'input {v + 1}'
    if v < 48:
        return f'return {v - 31}'
    if v < 64:
        return f'bus {v - 47}'
    if v < 70:
        return f'matrix {v - 63}'
    return {71: 'mono', 80: 'main'}.get(v, f'DCA {v - 71}' if v < 80 else f'#{v}')


def bind_pro2(ctl, pro1):
    """PRO2 control centre (PRO2-Control-Centre.dwg). Sections, left to right: channel bay A (8),
    channel bay B (8) under the screen with the assignable row and the centre keys, the selected
    channel strip and mix sends right of the screen, 24 output strips, talk / monitor column, mix bay
    (8), masters left / right / mono and monitor"""
    bd = Binder(ctl)
    # the selected-channel strip is the PRO1's part (same positions to 0.2 mm, 67 of 68 parts)
    transfer_pro1(bd, pro1, (400, 90, 490, 340), (320.94, -10.8))
    # centre keys: screen keys, home / enter, cursor arrows, jog wheel (PRO1 centre section)
    transfer_pro1(bd, pro1, (300, 370, 380, 620), (340.5, -4.3))

    bays = strip_bays(ctl)
    names = ['A', 'B', 'M', 'mast', 'mon']
    assert [len(b) for b in bays] == [8, 8, 8, 3, 1], [len(b) for b in bays]
    for name, bay in zip(names[:3], bays[:3]):
        for k, f in enumerate(bay):
            bind_strip(bd, f, name, k, lcd_y=424.05, mute_y=450.5, solo_y=470.5)
    # masters: OMC's main is one LCR bus (vchannel 80) - master left and right both drive it; mono = 71
    for f, v, side in zip(bays[3], (80, 80, 71), ('left', 'right', 'mono')):
        f['bind'] = dict(kind='fixed', p='fader', i=v + 1, lo=-100, hi=10, law='fader', what=f'master {side}', fx={'left': 0, 'right': 1, 'mono': 2}[side])
        bd.B(('lcd',), f['x'], 424.05, 4, kind='radio', p='sel', i=1, value=v, what=f'select master {side}', fx={'left': 0, 'right': 1, 'mono': 2}[side],
             caption={'left': 'Main L', 'right': 'Main R', 'mono': 'Mono'}[side])
        bd.B(('button',), f['x'] - 5.5, 450.5, 4, kind='fixed', p='ch_mute', i=v + 1, toggle=True, what=f'master {side} mute', fx={'left': 0, 'right': 1, 'mono': 2}[side])
        bd.B(('button',), f['x'] - 5.5, 470.5, 4, kind='fixed', p='ch_solo', i=v + 1, toggle=True, what=f'master {side} solo', fx={'left': 0, 'right': 1, 'mono': 2}[side])
        m = bd.at(('meter',), f['x'] + 4.7, 460.5, 4)
        if m is not None:
            m['bind'] = dict(kind='meter', p={'left': 'main_meter_l', 'right': 'main_meter_r'}.get(side, 'ch_meter'),
                             i=1 if side != 'mono' else 72)
    mon = bays[4][0]
    mon['bind'] = dict(kind='fixed', p='mon_level', i=1, lo=-100, hi=10, law='fader', what='monitor level', fx=3)
    for m, side in zip(sorted(bd.where(types=('meter',), box=(1050, 380, 1085, 440)), key=lambda c: c['x']), 'lr'):
        m['bind'] = dict(kind='meter', p='main_meter_' + side, i=1)        # OMC has no monitor meter
    bd.B(BTN, 1061.75, 450.6, kind='surface', i=FN['mon_mute'], toggle=True, what='monitor mute', fx=3)
    bd.B(BTN, 1075.75, 450.6, kind='surface', i=FN['monb_mute'], toggle=True, what='monitor B mute')
    bd.B(BTN, 1061.55, 468.55, kind='surface', i=FN['mon_dim'], toggle=True, what='monitor dim')
    bd.B(BTN, 1075.55, 468.55, kind='surface', i=FN['monb_co'], toggle=True, what='monitor C/O')

    # bank keys: Scroll per bay, INPUT / OUTPUT for the channel bays, VCA / OUTPUT for the mix bay, EXTEND
    bd.B(BTN, 95.93, 424.04, force=True, kind='scroll', bank='A', step=-1)
    bd.B(BTN, 347.57, 424.05, force=True, kind='scroll', bank='A', step=1)
    bd.B(BTN, 393.44, 424.02, force=True, kind='scroll', bank='B', step=-1)
    bd.B(BTN, 645.06, 423.99, force=True, kind='scroll', bank='B', step=1)
    bd.B(BTN, 718.76, 424.01, force=True, kind='scroll', bank='M', step=-1)
    bd.B(BTN, 654.55, 456.55, force=True, kind='layer', bank='A', value='input')
    bd.B(BTN, 654.55, 470.55, force=True, kind='layer', bank='A', value='output')
    bd.B(BTN, 704.55, 460.55, force=True, kind='bay', value='extend', what='EXTEND: the mix bay continues the channel bays (toggle)')
    bd.B(BTN, 953.75, 456.55, force=True, kind='layer', bank='M', value='vca')
    bd.B(BTN, 953.75, 470.65, force=True, kind='layer', bank='M', value='output')

    # assignable controls: 8 encoders and their keys over channel bay B (OMC enc / enc_key), view, ALT
    encs = sorted(bd.where(types=('knob',), box=(400, 370, 640, 392)), key=lambda c: c['x'])
    keys = sorted(bd.where(types=('button',), box=(400, 392, 640, 405)), key=lambda c: c['x'])
    assert len(encs) == 8 and len(keys) == 8, (len(encs), len(keys))
    for k, (e, b) in enumerate(zip(encs, keys)):
        e['bind'] = dict(kind='enc', i=k + 1, what=f'encoder {k + 1}: the focused row, strip {k + 1}')
        b['bind'] = dict(kind='enckey', i=k + 1, what=f'toggle of the focused row, strip {k + 1}')
    bd.B(BTN, 393.05, 381.15, kind='cmd', p='ui_cmd', value=CMD['home'], what='view (home)')
    bd.B(BTN, 393.05, 398.65, kind='surface', i=FN['alt'], toggle=True, what='ALT')
    bd.B(BTN, 645.55, 381.05, kind='cmd', p='ui_cmd', value=CMD['setup'], what='assignable controls setup')
    bd.B(BTN, 645.5, 398.54, kind='cmd', p='ui_cmd', value=CMD['layers'], what='user layers')

    # population: POP 1-6 LCD keys and the 6 mute group keys; automation
    pops = sorted(bd.where(types=('lcd',), box=(730, 380, 890, 397)), key=lambda c: c['x'])
    for k, c in enumerate(pops[:6]):
        c['bind'] = dict(kind='cmd', p='ui_cmd', value=50 + k, touch=True, caption=f'POP {k + 1}',
                         what=f'POP {k + 1}: spill onto the faders and the touch UI')
    for k, c in enumerate(bd.where(types=('button',), label='MUTE', box=(890, 375, 935, 400))):
        c['bind'] = dict(kind='fixed', p=f'mute_group{k + 1}', i=1, toggle=True, what=f'mute group {k + 1}')
        c['tint'] = 'red'
    for lab, v in (('Last', 'last'), ('Now', 'now'), ('Next', 'next'), ('Store', 'store'), ('OK', 'ok'), ('Cancel', 'cancel')):
        for c in bd.where(types=BTN, label=lab, box=(970, 375, 1045, 400)):
            c['bind'] = dict(kind='cmd', p='ui_cmd', value=CMD[v], what={'last': 'Last cue', 'now': 'Now: recall scene',
                             'next': 'Next cue', 'store': 'Store scene', 'ok': 'OK: commit preview', 'cancel': 'Cancel: discard preview'}[v])

    # mix sends of the selected channel: 8 rows of ON / PRE / level; the ↑↓ keys switch 1-8 / 9-16
    knobs = sorted(bd.where(types=('knob',), box=(830, 90, 845, 285)), key=lambda c: c['y'])
    ons = sorted(bd.where(types=('button',), label='ON', box=(812, 88, 826, 280)), key=lambda c: c['y'])
    pres = sorted(bd.where(types=('button',), label='PRE', box=(812, 98, 826, 290)), key=lambda c: c['y'])
    assert len(knobs) == 8 and len(ons) == 8, (len(knobs), len(ons))
    for k, (kn, on) in enumerate(zip(knobs, ons)):
        kn['bind'] = dict(kind='sendlvl', bus=k + 1, lo=-100, hi=10, unit='dB', what=f'send to mix {k + 1} / {k + 9}')
        on['bind'] = dict(kind='sends', bus=k + 1, page=True, what=f'mix {k + 1} / {k + 9} sends on the faders')
    bd.B(BTN, 836.95, 299.99, kind='sendpage', step=-1, what='mix sends 1-8')
    bd.B(BTN, 837.05, 318.81, kind='sendpage', step=1, what='mix sends 9-16')

    # 24 output strips: rows buses 1-8, buses 9-16, matrices 1-8 (OMC has 6 matrices)
    output_strips(bd, (850, 0, 1045, 0), [((80, 140), list(range(48, 56))), ((155, 215), list(range(56, 64))),
                                          ((230, 290), [64, 65, 66, 67, 68, 69, -1, -1])], vch_name)
    bd.B(BTN, 867.05, 318.8, kind='flip', what='FLIP: the last mix\'s sends on the faders')
    bd.B(BTN, 915.05, 318.75, kind='cmd', p='ui_cmd', value=CMD['effects'], what='FX: effects')
    bd.B(BTN, 963.05, 318.8, kind='cmd', p='ui_cmd', value=CMD['effects'], what='GEQ / effects')
    bd.B(BTN, 1011.05, 318.8, kind='cmd', p='ui_cmd', value=CMD['assign'], what='MCA: mute group / assign')

    # talk / oscillator / solo / phones column (the PRO1's functions)
    bd.B(KNOBS, 1068.67, 120.61, kind='surface', i=FN['talk_gain'], what='talk mic gain')
    bd.B(KNOBS, 1068.66, 139.67, kind='surface', i=FN['talk_limiter'], what='talk limiter')
    bd.B(KNOBS, 1068.59, 158.57, kind='surface', i=FN['talk_level'], what='talk level')
    bd.B(KNOBS, 1068.64, 275.39, kind='surface', i=FN['phones'], what='phones level')
    for (x, y, fn, what) in ((1061.55, 176.2, 'talk_int', 'talk internal'), (1075.55, 176.2, 'talk_ext', 'talk external'),
                             (1061.55, 191.0, 'osc_int', 'oscillator internal'), (1075.55, 191.05, 'osc_ext', 'oscillator external'),
                             (1061.55, 254.05, 'solo_pfl', 'solo PFL / AFL'), (1075.55, 254.1, 'solo_add', 'solo ADD'),
                             (1061.55, 292.8, 'phones_mute', 'phones mute'), (1075.55, 291.2, 'solo_fader', 'solo to fader (C/O)')):
        bd.B(BTN, x, y, kind='surface', i=FN[fn], toggle=True, what=what)
    bd.B(BTN, 1068.55, 242.0, kind='fixed', p='solo_clear', i=1, toggle=True, what='solo CLEAR')
    leds(bd, band_box=(788, 245, 800, 290))
    return bd


# PRO X input strip, top to bottom: (type, dx from the fader, y, binding). Measured on strip 4; the
# 16 input strips are the same part. A part the drawing leaves open on a strip (48V / TALK on strips
# 1-3) is completed from the template and marked "derived".
PROX_STRIP = [
    ('meter', -6.8, 202.1, dict(p='ch_meter')),
    ('button', -6.3, 295.55, dict(p='ch_phantom', toggle=True)),
    ('button', 6.4, 295.55, dict(kind='stripfn', i=FN['talk_in'], what='input talk')),
    ('knob', 0.0, 308.35, dict(p='ch_gain', lo=-18, hi=60, unit='dB')),
    ('button', -6.3, 325.45, dict(p='ch_phase', toggle=True)),
    ('round', 8.1, 325.44, dict(kind='stripcmd', value=CMD['input'], what='input section')),
    ('button', -6.3, 347.45, dict(kind='stripcmd', value=CMD['insert'], what='direct out')),
    ('round', 8.1, 347.44, dict(kind='stripcmd', value=CMD['insert'], what='direct out')),
    ('button', -6.3, 366.75, dict(p='ch_comp_on', toggle=True)),
    ('round', 8.1, 373.09, dict(kind='stripcmd', value=CMD['comp'], what='compressor')),
    ('button', -6.3, 392.75, dict(p='ch_gate_on', toggle=True)),
    ('round', 8.1, 399.13, dict(kind='stripcmd', value=CMD['gate'], what='gate')),
    ('button', -6.3, 423.95, dict(kind='stripfn', i=FN['insert'], what='insert in')),
    ('round', 8.1, 423.93, dict(kind='stripcmd', value=CMD['insert'], what='insert')),
    ('round', 8.1, 437.3, dict(kind='stripcmd', value=CMD['eq'], band=4, what='EQ high')),
    ('round', 8.1, 450.54, dict(kind='stripcmd', value=CMD['eq'], band=3, what='EQ hi mid')),
    ('button', -6.3, 457.25, dict(p='ch_eq_on', toggle=True)),
    ('round', 8.1, 463.8, dict(kind='stripcmd', value=CMD['eq'], band=2, what='EQ lo mid')),
    ('round', 8.1, 477.04, dict(kind='stripcmd', value=CMD['eq'], band=1, what='EQ low')),
    ('button', -6.3, 495.45, dict(kind='stripcmd', value=CMD['assign'], what='mix: sends')),
    ('button', -6.3, 506.45, dict(kind='stripcmd', value=CMD['assign'], what='mix: pre')),
    ('round', 8.1, 517.47, dict(kind='stripcmd', value=CMD['assign'], what='mix')),
    ('button', -6.3, 517.55, dict(kind='stripfn', i=FN['solo_pfl'], what='AFL')),
    ('button', -6.3, 533.95, dict(kind='stripfn', i=FN['sis'], what='feed SIS')),
    ('button', 6.4, 533.95, dict(p='ch_send_lr', toggle=True)),
    ('button', 6.4, 545.05, dict(p='ch_send_mono', toggle=True)),
    ('knob', 0.0, 562.84, dict(p='ch_pan', lo=-100, hi=100, unit='')),
    ('lcd', 0.1, 595.75, dict(p='sel', select=True)),
    ('button', -5.6, 616.45, dict(p='ch_mute', toggle=True)),
    ('button', -5.6, 641.05, dict(p='ch_solo', toggle=True)),
]


def bind_prox(ctl, pro1):
    """PRO X control centre (PROx-Control-Centre.dwg). Bays, left to right: input bay A (12 strips),
    centre-left (detail area A, mix sends, 24 output strips, population keys, output bay of 10),
    centre-right (masters, assignables, monitor / talk, automation, screen keys, two jog wheels,
    detail area B) and input bay B (4 strips)"""
    bd = Binder(ctl)
    bays = strip_bays(ctl)
    assert [len(b) for b in bays] == [4, 4, 4, 10, 3, 1, 1, 4], [len(b) for b in bays]
    inputs = bays[0] + bays[1] + bays[2]
    # ---- input strips (A: 12, B: 4)
    ref = {}
    for f in inputs + bays[7]:
        for (t, dx, y, _b) in PROX_STRIP:
            c = bd.at((t,), f['x'] + dx, y, 2.5)
            if c is not None:
                ref[(t, dx, y)] = c
    for bay, fs in (('A', inputs), ('B', bays[7])):
        for k, f in enumerate(fs):
            f['bind'] = dict(kind='strip', bank=bay, slot=k, p='fader', lo=-100, hi=10, law='fader')
            for (t, dx, y, b) in PROX_STRIP:
                c = bd.at((t,), f['x'] + dx, y, 2.5)
                if c is None:
                    r = ref[(t, dx, y)]
                    c = {kk: vv for kk, vv in r.items() if kk not in ('bind', 'id', 'label')}
                    c.update(x=round(f['x'] + dx, 2), y=y, derived='completed from the strip template (the drawing leaves this part open)')
                    if r.get('label'):
                        c['label'] = r['label']
                    ctl.append(c)
                b = dict(b)
                b.setdefault('kind', 'strip')
                b.update(bank=bay, slot=k)
                c['bind'] = b
    # ---- output bay (10): VCA / buses / matrices / masters, by the channel type keys
    for k, f in enumerate(bays[3]):
        bind_strip(bd, f, 'O', k, lcd_y=595.75, mute_y=618.15, solo_y=641.05, meter=False)
    # ---- masters left / right / mono (OMC: main LCR = 80, mono = 71) and the monitor faders
    for f, v, side in zip(bays[4], (80, 80, 71), ('left', 'right', 'mono')):
        f['bind'] = dict(kind='fixed', p='fader', i=v + 1, lo=-100, hi=10, law='fader', what=f'master {side}', fx={'left': 0, 'right': 1, 'mono': 2}[side])
        for lab, p in (('MUTE', 'ch_mute'), ('SOLO', 'ch_solo')):
            for c in bd.where(types=('button',), label=lab, box=(f['x'] - 3, 430, f['x'] + 3, 490)):
                c['bind'] = dict(kind='fixed', p=p, i=v + 1, toggle=True, what=f'master {side} {lab.lower()}', fx={'left': 0, 'right': 1, 'mono': 2}[side])
        for c in bd.where(types=('round',), box=(f['x'] - 3, 488, f['x'] + 3, 499)):
            c['bind'] = dict(kind='radio', p='sel', i=1, value=v, what=f'select master {side}', fx={'left': 0, 'right': 1, 'mono': 2}[side])
        for c in bd.where(types=('meter',), box=(f['x'] - 3, 290, f['x'] + 3, 330)):
            c['bind'] = dict(kind='meter', p={'left': 'main_meter_l', 'right': 'main_meter_r'}.get(side, 'ch_meter'),
                             i=1 if side != 'mono' else 72)
    for f, what, fx in ((bays[5][0], 'monitor A level', 3), (bays[6][0], 'monitor B level (OMC has one monitor level)', 4)):
        f['bind'] = dict(kind='fixed', p='mon_level', i=1, lo=-100, hi=10, law='fader', what=what, fx=fx)
    for c, side in zip(sorted(bd.where(types=('meter',), box=(880, 290, 1010, 330)), key=lambda c: c['x']), 'lrlrlr'):
        c['bind'] = dict(kind='meter', p='main_meter_' + side, i=1)        # OMC has no monitor meter
    # ---- detail areas A and B: the PRO1's selected-channel functions, by legend
    transfer_by_label(bd, pro1, (400, 90, 490, 340), (440, 260, 530, 520), (37.55, 170.55))
    transfer_by_label(bd, pro1, (400, 90, 490, 340), (1075, 240, 1160, 520), (656.65, 170.65))
    # the round section keys of the detail areas open that section of the selected channel (PRO1: the
    # round keys of its selected-channel strip): input, dynamics, EQ, masters / pan
    for xr in (454.3, 1145.6):
        for y, v, what in ((324.83, 'input', 'select: input section'), (425.18, 'comp', 'select: dynamics'),
                           (480.5, 'eq', 'select: EQ'), (515.9, 'main', 'select: masters / pan')):
            c = bd.at(('round',), xr, y, 2.5)
            if c is not None and not c.get('bind'):
                c['bind'] = dict(kind='cmd', p='ui_cmd', value=CMD[v], what=what)
    for x0, x1 in ((440, 530), (1075, 1160)):
        for lab, v in (('comp', 'comp'), ('gate', 'gate')):
            for c in bd.where(types=('button',), label=lab, box=(x0, 370, x1, 400), unbound=False):
                c['bind'] = dict(kind='mode', mode='dyn', value=v)
    # ---- bank keys: channel type (layer), scroll, align, extend
    for lab, bank, value in (('EXTAND', 'A', None), ('RET', 'A', 'ret'), ('AUX', 'A', 'aux'), ('MTX', 'A', 'mtx'), ('MAS', 'A', 'mast')):
        for c in bd.where(types=BTN, label=lab, box=(465, 790, 515, 820)):
            c['bind'] = dict(kind='bay', value='extend', what='EXTEND: input bay B continues bay A (toggle)') if value is None \
                else dict(kind='layer', bank=bank, value=value)
    for lab, value in (('INPUT', 'input'), ('RET', 'ret'), ('AUX', 'aux'), ('MTX', 'mtx'), ('MAS', 'mast')):
        for c in bd.where(types=BTN, label=lab, box=(1085, 790, 1130, 820)):
            c['bind'] = dict(kind='layer', bank='B', value=value)
    bd.B(BTN, 479.14, 559.05, kind='scroll', bank='A', step=-1, what='input select: scroll by 8')
    bd.B(BTN, 501.16, 559.05, kind='scroll', bank='A', step=1, what='input select: scroll by 8')
    bd.B(BTN, 478.54, 618.35, kind='scroll', bank='A', step=-1)
    bd.B(BTN, 500.56, 618.35, kind='scroll', bank='A', step=1)
    bd.B(BTN, 479.15, 641.05, kind='bay', value='align', what='ALIGN: bay B continues bay A')
    bd.B(BTN, 1065.05, 559.16, kind='scroll', bank='B', step=-1, what='input select: scroll')
    bd.B(BTN, 1098.24, 559.15, kind='scroll', bank='B', step=1, what='input select: scroll')
    bd.B(BTN, 1097.64, 618.55, kind='scroll', bank='B', step=-1)
    bd.B(BTN, 1119.66, 618.55, kind='scroll', bank='B', step=1)
    bd.B(BTN, 1098.25, 641.15, kind='bay', value='align', what='ALIGN B: bay B continues bay A')
    bd.B(BTN, 758.24, 516.45, kind='scroll', bank='O', step=-1)
    bd.B(BTN, 779.56, 516.45, kind='scroll', bank='O', step=1)
    # ---- channel select keypads: digits, * clears, ENTER selects input n and pages its bay to it
    for x0, bank in ((475.15, 'A'), (1093.65, 'B')):
        for r, y in enumerate((719.65, 734.65, 749.65, 764.65)):
            for k in range(3):
                key = '123456789*0E'[r * 3 + k]
                c = bd.at(BTN, x0 + 15 * k, y, 2.5)
                if c is not None and not c.get('bind'):
                    c['bind'] = dict(kind='keypad', key=key, bank=bank,
                                     what='ENTER: select the input typed' if key == 'E' else 'clear' if key == '*' else f'digit {key}')
    # ---- mix sends of the selected channel (left and right of the output strips): ON / PRE / level
    for x_on, x_kn in ((534.85, 550.63), (1045.95, 1061.73)):
        kn = sorted(bd.where(types=('knob',), box=(x_kn - 2, 270, x_kn + 2, 480)), key=lambda c: c['y'])
        on = sorted(bd.where(types=('button',), label='ON', box=(x_on - 2, 270, x_on + 2, 480)), key=lambda c: c['y'])
        for k, c in enumerate(kn[:8]):
            c['bind'] = dict(kind='sendlvl', bus=k + 1, lo=-100, hi=10, unit='dB', what=f'send to mix {k + 1} / {k + 9}')
        for k, c in enumerate(on[:8]):
            c['bind'] = dict(kind='sends', bus=k + 1, page=True, what=f'mix {k + 1} / {k + 9} sends on the faders')
    for x, y, step in ((534.85, 538.84, -1), (553.95, 538.84, 1), (1045.95, 538.94, -1), (1065.05, 538.94, 1)):
        bd.B(BTN, x, y, kind='sendpage', step=step, what='mix sends 1-8 / 9-16')
    # ---- 24 output strips: buses 1-8 / 9-16 / matrices (OMC has 6)
    output_strips(bd, (575, 0, 790, 0), [((270, 330), list(range(48, 56))), ((350, 410), list(range(56, 64))),
                                         ((432, 492), [64, 65, 66, 67, 68, 69, -1, -1])], vch_name)
    for (x, what, v) in ((584.25, "FLIP: the last mix's sends on the faders", None), (623.45, 'FX: effects', CMD['effects']),
                         (673.85, 'GEQ / effects', CMD['effects']), (713.95, 'MCA: mute group / assign', CMD['assign'])):
        bd.B(BTN, x, 516.65, kind='flip', what=what) if v is None else bd.B(BTN, x, 516.65, kind='cmd', p='ui_cmd', value=v, what=what)
    # ---- population keys over the output bay: POP 1-6
    for k, c in enumerate(sorted(bd.where(types=('lcd',), box=(580, 550, 790, 568)), key=lambda c: c['x'])[:6]):
        c['bind'] = dict(kind='cmd', p='ui_cmd', value=50 + k, touch=True, caption=f'POP {k + 1}',
                         what=f'POP {k + 1}: spill onto the faders and the touch UI')
    # ---- assignable controls: 8 encoders over the masters and their keys
    encs = sorted(bd.where(types=('knob',), box=(825, 350, 980, 366)), key=lambda c: c['x'])
    keys = sorted(bd.where(types=('button',), box=(825, 368, 980, 380)), key=lambda c: c['x'])
    for k, c in enumerate(encs[:8]):
        c['bind'] = dict(kind='enc', i=k + 1, what=f'encoder {k + 1}: the focused row, strip {k + 1}')
    for k, c in enumerate(keys[:8]):
        c['bind'] = dict(kind='enckey', i=k + 1, what=f'toggle of the focused row, strip {k + 1}')
    # ---- automation, auto mute groups, screen access keys, jog wheels
    for lab, v in (('store', 'store'), ('ok', 'ok'), ('cancel', 'cancel'), ('last', 'last'), ('now', 'now')):
        for c in bd.where(types=BTN, label=lab, box=(825, 710, 870, 760)):
            c['bind'] = dict(kind='cmd', p='ui_cmd', value=CMD[v], what=v)
    bd.B(('lcd',), 846.64, 778.95, kind='cmd', p='ui_cmd', value=CMD['next'], what='Next cue', caption='next')
    for k, c in enumerate(sorted(bd.where(types=('button',), label='MUTE', box=(900, 700, 1045, 715)), key=lambda c: c['x'])[:6]):
        c['bind'] = dict(kind='fixed', p=f'mute_group{k + 1}', i=1, toggle=True, what=f'mute group {k + 1}')
        c['tint'] = 'red'
    for c in bd.where(types=('round',), box=(955, 755, 970, 825)):
        for word, page in SCREEN_KEYS.items():
            if (c.get('label') or '').startswith(word):
                c['bind'] = dict(kind='radio', p='screen', i=1, value=page, what=c['label'])
    for c in bd.where(types=('jog',)):
        c['bind'] = dict(kind='jog')
    # ---- monitor / talk / oscillator / solo (the PRO1's functions)
    bd.B(BTN, 891.65, 461.35, kind='surface', i=FN['mon_dim'], toggle=True, what='monitor A dim')
    bd.B(BTN, 905.65, 461.35, kind='surface', i=FN['monb_co'], toggle=True, what='monitor A C/O')
    bd.B(BTN, 891.65, 477.85, kind='surface', i=FN['mon_mute'], toggle=True, what='monitor A mute')
    bd.B(BTN, 905.65, 477.85, kind='surface', i=FN['monb_mute'], toggle=True, what='monitor B mute')
    bd.B(BTN, 993.65, 461.15, kind='surface', i=FN['mon_dim'], toggle=True, what='monitor dim')
    bd.B(BTN, 1007.65, 461.15, kind='surface', i=FN['monb_co'], toggle=True, what='monitor C/O')
    bd.B(BTN, 993.65, 478.25, kind='surface', i=FN['mon_mute'], toggle=True, what='monitor mute')
    bd.B(BTN, 1007.65, 478.25, kind='surface', i=FN['monb_mute'], toggle=True, what='monitor B mute')
    for x, y, fn, what in ((940.45, 430.55, 'osc_int', 'oscillator internal'), (960.45, 430.55, 'osc_ext', 'oscillator external'),
                           (940.45, 524.75, 'talk_int', 'talk internal'), (960.45, 524.75, 'talk_ext', 'talk external'),
                           (928.45, 574.25, 'solo_pfl', 'solo PFL / AFL'), (959.45, 574.25, 'solo_pfl', 'solo PFL / AFL'),
                           (928.45, 584.25, 'solo_add', 'solo ADD'), (959.45, 584.25, 'solo_add', 'solo ADD')):
        bd.B(BTN, x, y, kind='surface', i=FN[fn], toggle=True, what=what)
    for x in (941.45, 972.45):
        bd.B(BTN, x, 579.25, kind='fixed', p='solo_clear', i=1, toggle=True, what='solo CLEAR')
    bd.B(KNOBS, 969.59, 505.62, kind='surface', i=FN['talk_gain'], what='talk mic gain')
    bd.B(KNOBS, 950.59, 505.62, kind='surface', i=FN['talk_limiter'], what='talk limiter')
    bd.B(KNOBS, 931.59, 505.62, kind='surface', i=FN['talk_level'], what='talk level')
    bd.B(KNOBS, 950.59, 550.15, kind='surface', i=FN['phones'], what='phones level')
    leds(bd)
    return bd


# ------------------------------------------------------------------------------------------------
# finish: key colours by function (the PRO1 photographs' scheme; parts taken over from the PRO1
# keep the PRO1's colour). No photographs of the PRO2 / PRO X were used: unknown keys are grey.
# ------------------------------------------------------------------------------------------------

def colour(ctl):
    for c in ctl:
        if c.get('tint'):
            continue
        b = c.get('bind') or {}
        t, p, lab = c['type'], str(b.get('p', '')), (c.get('label') or '').upper()
        if t in ('knob', 'pot'):
            c['tint'] = {'ch_pan': 'red', 'ch_gain': 'grey'}.get(p, 'grey')
        elif t == 'arrow':
            c['tint'] = 'light'
        elif t in ('button', 'ledbutton', 'round'):
            c['tint'] = 'grey'
            if p == 'ch_mute' or lab == 'MUTE' or p.startswith('mute_group'):
                c['tint'] = 'red'
            elif p == 'ch_solo' or lab == 'SOLO':
                c['tint'] = 'amber'
            elif b.get('kind') == 'layer':
                c['tint'] = 'lilac'
            elif b.get('kind') == 'bay':
                c['tint'] = 'purple'
            elif p == 'ch_phantom':
                c['tint'] = 'red'
            elif p == 'ch_phase' or p in ('ch_comp_on', 'ch_gate_on'):
                c['tint'] = 'blue'
            elif p == 'ch_eq_on':
                c['tint'] = 'red'
            elif lab == 'TALK':
                c['tint'] = 'green'


# ------------------------------------------------------------------------------------------------
# SVG (as gen-surface.py's PRO1 writer, without the PRO1's white inset panels)
# ------------------------------------------------------------------------------------------------

def write_svg(polys, labels, ctl, screen, W, H, fn):
    caps = [(c['x'], c['bottom'] - 6.5, c['bottom'] + 27.5) for c in ctl if c['type'] == 'fader']

    def is_cap(pts):
        mn, mx = pts.min(0), pts.max(0)
        return any(mn[0] > x - 8 and mx[0] < x + 8 and mn[1] > ya and mx[1] < yb for (x, ya, yb) in caps)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.2f} {H:.2f}" width="{W:.2f}mm" height="{H:.2f}mm">',
           '<g class="insets"></g>', '<g class="lines" fill="none" stroke-linecap="round" stroke-linejoin="round">']
    bylayer = {}
    for layer, pts in polys:
        if len(pts) < 2 or is_cap(pts):
            continue
        if len(pts) > 3:
            # the PRO2's mouldings and bezel are splines flattened at 0.03 mm: 0.05 mm is invisible
            pts = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), 0.05, False).reshape(-1, 2)
        bylayer.setdefault(layer, []).append('M' + ' '.join(f'{x:.2f} {y:.2f}' for x, y in pts))
    for i, (layer, ds) in enumerate(sorted(bylayer.items())):
        out.append(f'<path class="L{i}" data-layer="{layer}" d="{" ".join(ds)}"/>')
    out.append('</g>')
    out.append('<g class="legend">')
    for t in labels:
        anchor = {1: 'start', 4: 'start', 7: 'start', 2: 'middle', 5: 'middle', 8: 'middle'}.get(t['ap'], 'end')
        lines = t['s'].split('\n')
        dy0 = {1: 0.8, 2: 0.8, 3: 0.8, 4: 0.35 - 0.5 * (len(lines) - 1), 5: 0.35 - 0.5 * (len(lines) - 1),
               6: 0.35 - 0.5 * (len(lines) - 1)}.get(t['ap'], -(len(lines) - 1))
        rot = f' transform="rotate({-t["rot"]:.1f} {t["x"]:.2f} {t["y"]:.2f})"' if abs(t['rot']) > 0.5 else ''
        esc = [l.replace('&', '&amp;').replace('<', '&lt;') for l in lines]
        spans = ''.join(f'<tspan x="{t["x"]:.2f}" dy="{(dy0 if k == 0 else 1.15):.2f}em">{l}</tspan>' for k, l in enumerate(esc))
        out.append(f'<text x="{t["x"]:.2f}" y="{t["y"]:.2f}" font-size="{t["h"]:.2f}" text-anchor="{anchor}"{rot}>{spans}</text>')
    out.append('</g>')
    if screen:
        x, y, w, h = screen
        out.append(f'<rect id="screen" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/>')
    out.append('</svg>')
    with open(fn, 'w') as f:
        f.write('\n'.join(out))


# ------------------------------------------------------------------------------------------------
# 5. PRO2C: the PRO2 without its left input bay (derived; there is no PRO2C drawing)
# ------------------------------------------------------------------------------------------------

# The PRO2's channel bay A spans panel x 83.5 .. 381.1: its Scroll ◀ key (95.9) to bay B's Scroll ◀
# key (393.4), a pitch of 297.6 mm, the same as the strip-to-strip offset between the bays (LCD keys
# 118.6 -> 416.0). Cutting it leaves 1179.6 - 297.6 = 882.0 mm, the PRO2C's published width (882 mm).
PRO2C_CUT = (83.5, 381.1)


def cut_x(x, cut):
    a, b = cut
    return x if x <= a else (x - (b - a) if x >= b else a)


def derive_pro2c(W, H, polys, texts, ctl, screen):
    a, b = PRO2C_CUT
    w = b - a
    P = []
    for layer, pts in polys:
        inside = (pts[:, 0] > a + 0.01) & (pts[:, 0] < b - 0.01)
        if inside.all():
            continue
        q = pts.copy()
        q[:, 0] = [cut_x(x, PRO2C_CUT) for x in pts[:, 0]]
        # a part with some points in the cut: keep the runs outside it (a line across stays joined)
        if inside.any():
            runs, run = [], []
            for k in range(len(q)):
                if inside[k]:
                    if len(run) >= 2:
                        runs.append(np.array(run))
                    run = []
                else:
                    run.append(q[k])
            if len(run) >= 2:
                runs.append(np.array(run))
            P.extend((layer, r) for r in runs)
        else:
            P.append((layer, q))
    T = [dict(t, x=cut_x(t['x'], PRO2C_CUT)) for t in texts if not (a < t['x'] < b)]
    C = []
    for c in ctl:
        if a < c['x'] < b:
            continue
        c = dict(c, x=round(cut_x(c['x'], PRO2C_CUT), 2))
        bnd = c.get('bind')
        if bnd and bnd.get('kind') == 'mirror':
            c['bind'] = dict(bnd, x=round(cut_x(bnd['x'], PRO2C_CUT), 2))
        C.append(c)
    # bay B is the PRO2C's only channel bay; bay A's INPUT / OUTPUT keys (between bays B and M) stay
    sx, sy, sw, sh = screen
    return W - w, H, P, T, C, (cut_x(sx, PRO2C_CUT), sy, sw, sh)


# ------------------------------------------------------------------------------------------------
# bank layouts (surface.js): layers are channel lists, banks page through a layer, bays are the
# physical fader groups shown by a bank (bank, first slot). Options pick one of several layouts.
# ------------------------------------------------------------------------------------------------

def layers(cfg):
    return dict(
        input=dict(inputs=cfg['inputs']),
        output=dict(chs=list(range(48, 64)) + list(range(64, 70))),
        ret=dict(chs=list(range(32, 48))),
        aux=dict(chs=list(range(48, 64))),
        mtx=dict(chs=list(range(64, 70))),
        vca=dict(chs=list(range(72, 80))),
        mast=dict(chs=[80, 71]),
    )


def surface_config(model, cfg):
    s = dict(model=cfg['name'], id=model, inputs=cfg['inputs'], layers=layers(cfg))
    if model == 'pro2':
        s['options'] = [
            dict(id='bays', label='channel bays', values=[
                dict(id='joined', label='A + B: 16 inputs', banks=dict(L=dict(slots=16, layer='input', touch=1), R=dict(slots=8, layer='vca')),
                     bays=dict(A=['L', 0], B=['L', 8], M=['R', 0]), extend=['L', 'R']),
                dict(id='split', label='A and B page separately', banks=dict(
                    L=dict(slots=8, layer='input', touch=1), C=dict(slots=8, layer='input', page=1, touch=9), R=dict(slots=8, layer='vca')),
                     bays=dict(A=['L', 0], B=['C', 0], M=['R', 0]), extend=['C', 'R'])]),
            dict(id='mixbay', label='mix bay', bank='R', values=[
                dict(id='vca', label='VCA 1-8', layer='vca'), dict(id='output', label='mixes / matrices', layer='output'),
                dict(id='input', label='inputs', layer='input', page=2)]),
        ]
    elif model == 'pro2c':
        s['options'] = [
            dict(id='mixbay', label='mix bay', bank='R', values=[
                dict(id='vca', label='VCA 1-8', layer='vca'), dict(id='output', label='mixes / matrices', layer='output'),
                dict(id='input', label='inputs 9-16', layer='input', page=1)]),
        ]
        s['banks'] = dict(L=dict(slots=8, layer='input', touch=1), R=dict(slots=8, layer='vca', touch=9))
        s['bays'] = dict(A=['L', 0], B=['L', 0], M=['R', 0])
        s['extend'] = ['L', 'R']
    elif model == 'prox':
        s['options'] = [
            dict(id='bays', label='input bays', values=[
                dict(id='continuous', label='A + B: 16 inputs in a row', banks=dict(
                    L=dict(slots=16, layer='input', touch=1), O=dict(slots=10, layer='vca')),
                     bays=dict(A=['L', 0], B=['L', 12], O=['O', 0]), extend=None),
                dict(id='independent', label='A (12) and B (4) page separately', banks=dict(
                    L=dict(slots=12, layer='input', touch=1), B=dict(slots=4, layer='input', page=3, touch=13), O=dict(slots=10, layer='vca')),
                     bays=dict(A=['L', 0], B=['B', 0], O=['O', 0]), extend=['L', 'B'])]),
            dict(id='outbay', label='output bay', bank='O', values=[
                dict(id='vca', label='VCA 1-8', layer='vca'), dict(id='aux', label='mixes 1-16', layer='aux'),
                dict(id='mtx', label='matrices', layer='mtx'), dict(id='mast', label='masters', layer='mast')]),
        ]
    return s


# ------------------------------------------------------------------------------------------------
# build
# ------------------------------------------------------------------------------------------------

def build(model, src, outdir, pro1_controls):
    if model not in MODELS:
        # the XL8 and the X32 / M32 / WING families (surface_models_more.py)
        import surface_models_more
        return surface_models_more.build(model, src, outdir, pro1_controls)
    cfg = MODELS[model]
    W, H, polys, texts, circles = load_plan(src, cfg)
    img = raster(polys, W, H)
    reg = regions(img)
    ctl = find_controls(reg, polys, circles, W, H)
    attach_labels(ctl, texts)
    # not controls: the lamp sockets on the PRO2's handles, the talk mic XLR's pins
    for (x0, y0, x1, y1) in cfg.get('exclude', ()):
        ctl[:] = [c for c in ctl if not (x0 < c['x'] < x1 and y0 < c['y'] < y1 and c['type'] in ('button', 'led'))]
    screen = screen_region(img, W, H)
    if model in ('pro2', 'pro2c'):
        bind_pro2(ctl, pro1_controls)
    else:
        bind_prox(ctl, pro1_controls)
    if model == 'pro2c':
        W, H, polys, texts, ctl, screen = derive_pro2c(W, H, polys, texts, ctl, screen)
    colour(ctl)
    for c in ctl:
        c.setdefault('bind', None)
        if c['type'] == 'meter':
            b = c['bind'] or {}
            c['scale'] = 'strip' if b.get('p') == 'ch_meter' and b.get('kind') == 'strip' else 'master'
    for i, c in enumerate(sorted(ctl, key=lambda c: (round(c['y']), c['x']))):
        c['id'] = i
    ctl.sort(key=lambda c: c['id'])
    write_svg(polys, texts, ctl, screen, W, H, f'{outdir}/panel.svg')
    surface = surface_config(model, cfg)
    surface['plate'] = None
    if cfg.get('derived'):
        surface['derived'] = (f"derived from the {MODELS[cfg['derived']]['name']} drawing: channel bay A "
                              f"(panel x {PRO2C_CUT[0]}-{PRO2C_CUT[1]} mm) removed; no {cfg['name']} drawing exists")
    with open(f'{outdir}/controls.json', 'w') as f:
        json.dump(dict(width=round(W, 2), height=round(H, 2), screen=[round(v, 2) for v in screen] if screen else None,
                       surface=surface, controls=ctl), f, indent=0)
    kinds = {}
    for c in ctl:
        kinds[c['type']] = kinds.get(c['type'], 0) + 1
    bound = sum(1 for c in ctl if c['bind'])
    print(cfg['name'], 'controls', len(ctl), kinds, 'bound', bound, 'unbound', len(ctl) - bound, 'screen', screen)
    return ctl
