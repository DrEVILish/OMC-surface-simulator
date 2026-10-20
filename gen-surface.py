#!/usr/bin/env python3
"""
Build the flat PRO1 surface for the web replica from the vendor drawing.

  input : PRO1.dwg converted to DXF (LibreDWG: dwg2dxf -y -o pro1.dxf PRO1.dwg)
  output: panel.svg      the plan view as line art + silkscreen, millimetre units
          controls.json  every control found in the drawing, with its position, size,
                         silkscreen label and (where OMC has the function) its binding

The plan view is the 685 x 722 mm top view of the drawing set. Controls are found by
rasterising the plan view geometry at 10 px/mm and taking the enclosed regions
(buttons, knob caps, LEDs, arrows); faders, the jog wheel and the meter ladders come
from the geometry directly. Bindings are assigned by position against the silkscreen
(see BINDINGS below); the browser resolves them against the current selection, banks
and modes (surface.js).

usage: gen-surface.py pro1.dxf outdir
       gen-surface.py --model pro2|pro2c|prox <model>.dxf outdir [pro1 controls.json]
         the other control centres (surface_models.py; PRO2: run dwgfill.py on the DXF first);
         their bindings reuse the PRO1's where the part is the PRO1's, so the PRO1 is built first
"""
import json
import math
import sys

import cv2
import ezdxf
import numpy as np
from ezdxf import bbox, path, recover

# plan view window in drawing units (mm), from the 722 mm dimension and the view extents
X0, Y0, X1, Y1 = -3883.80, -730.30, -3198.34, -7.94
W, H = X1 - X0, Y1 - Y0
PX = 10.0  # raster resolution, px/mm


def to_panel(x, y):
    return x - X0, Y1 - y


def plan_entities(msp):
    for e in msp:
        try:
            b = bbox.extents([e], fast=True)
        except Exception:
            continue
        if not b.has_data:
            continue
        if b.extmin.y > -740 and b.extmax.y < 0 and b.extmax.x < -3170 and b.extmin.x > -4000:
            yield e


# ------------------------------------------------------------------------------------------------
# geometry
# ------------------------------------------------------------------------------------------------

def collect(doc):
    msp = doc.modelspace()
    polys, texts, screws = [], [], []
    for e in plan_entities(msp):
        t = e.dxftype()
        if t == 'CIRCLE' and 3.3 < e.dxf.radius < 3.6:
            screws.append(to_panel(e.dxf.center.x, e.dxf.center.y))
        if t in ('MTEXT', 'TEXT'):
            texts.append(e)
            continue
        if t in ('DIMENSION', 'HATCH', 'WIPEOUT', 'INSERT'):
            continue
        try:
            p = path.make_path(e)
        except Exception:
            continue
        pts = np.array([to_panel(v.x, v.y) for v in p.flattening(0.03)])
        if len(pts) >= 2:
            polys.append((e.dxf.layer, pts))
    return polys, texts, screws


def raster(polys):
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
        fill = a / (w * h)
        out.append(dict(cx=cen[i][0] / PX, cy=cen[i][1] / PX, w=w / PX, h=h / PX, fill=fill, x=x / PX, y=y / PX))
    return out


# ------------------------------------------------------------------------------------------------
# text
# ------------------------------------------------------------------------------------------------

# EQ band legends as OMC names them (user 2026-10-13: "BASS -> Low, Treble -> High"); the PRO X drawing prints
# bass / treble on the strip's EQ keys
LEGEND_RENAME = {'bass': 'low', 'treble': 'high', 'Bass': 'Low', 'Treble': 'High', 'BASS': 'LOW', 'TREBLE': 'HIGH'}


def label_items(texts):
    out = []
    for t in texts:
        p = t.dxf.insert
        x, y = to_panel(p.x, p.y)
        if t.dxftype() == 'MTEXT':
            s = t.plain_text()
            h = t.dxf.get('char_height', 2.5)
            ap = t.dxf.get('attachment_point', 1)
            rot = t.dxf.get('rotation', 0.0)
        else:
            s = t.dxf.text
            h = t.dxf.get('height', 2.5)
            ap = 7
            rot = t.dxf.get('rotation', 0.0)
        s = s.replace('\\P', '\n').strip()
        s = LEGEND_RENAME.get(s, s)
        if s:
            out.append(dict(x=x, y=y, h=h, ap=ap, rot=rot, s=s))
    return out


# ------------------------------------------------------------------------------------------------
# controls
# ------------------------------------------------------------------------------------------------

def find_controls(reg, polys, screws):
    ctl = []

    def add(kind, cx, cy, w, h, **kw):
        ctl.append(dict(type=kind, x=round(cx, 2), y=round(cy, 2), w=round(w, 2), h=round(h, 2), **kw))

    for r in reg:
        w, h, f, cx, cy = r['w'], r['h'], r['fill'], r['cx'], r['cy']
        ar = w / h
        # LCD keys: 19.6 x 15.6 window inside a 22.6 x 21.6 frame
        if 19 < w < 20.5 and 15 < h < 16.5 and f > 0.95:
            add('lcd', cx, cy, w, h)
        # square/rect push buttons
        elif f > 0.9 and 8.5 < w < 15 and 4.8 < h < 13 and not (cy > 500 and h > 12):
            add('button', cx, cy, w, h)
        # buttons with an LED slot (rounded 9.8 x 6 outline with the slot cut out)
        elif 9 < w < 10.5 and 5.5 < h < 6.6 and 0.74 < f < 0.84:
            add('ledbutton', cx, cy, w, h)
        # knob caps
        elif 0.74 < f < 0.82 and 0.88 < ar < 1.15 and 7.0 < w < 10.0:
            add('knob', cx, cy, w * 1.55, h * 1.55, cap=round(w, 2))
        # pointer knobs (talk mic gain, levels, phones)
        elif 0.6 < f < 0.7 and 8.5 < w < 10.5 and 7.8 < h < 9.2:
            add('pot', cx, cy, w * 1.25, w * 1.25)
        # round push buttons
        elif 0.74 < f < 0.82 and 0.88 < ar < 1.15 and 5.5 < w < 6.6:
            add('round', cx, cy, w, h)
        # arrows (triangles)
        elif 0.55 < f < 0.62 and 13.5 < w < 17 and 13.5 < h < 17:
            # the centroid of a triangle sits away from its apex
            dx, dy = cx - (r['x'] + w / 2), cy - (r['y'] + h / 2)
            d = ('left' if dx > 0 else 'right') if abs(dx) > abs(dy) else ('up' if dy > 0 else 'down')
            add('arrow', cx, cy, w, h, dir=d)
        # LEDs
        elif 0.7 < f < 0.85 and 0.8 < ar < 1.25 and 2.4 < w < 3.6:
            add('led', cx, cy, w, h)

    # meter ladders: columns of ~3 mm cells
    cells = [r for r in reg if r['fill'] > 0.9 and 2.4 < r['w'] < 3.6 and 1.3 < r['h'] < 3.6]
    cols = {}
    for c in cells:
        key = (round(c['cx'] * 2) / 2, 0 if c['cy'] < 350 else 1)
        cols.setdefault(key, []).append(c)
    for (x, _), cs in cols.items():
        if len(cs) < 8:
            continue
        cs.sort(key=lambda c: c['cy'])
        add('meter', x, (cs[0]['y'] + cs[-1]['y'] + cs[-1]['h']) / 2, cs[0]['w'], cs[-1]['y'] + cs[-1]['h'] - cs[0]['y'],
            cells=[round(c['cy'], 2) for c in cs], ch=round(cs[0]['h'], 2))

    # faders: pairs of slot lines (PARTS-CN), travel between their ends
    slots = {}
    for layer, pts in polys:
        if layer != 'PARTS-CN' or len(pts) != 2:
            continue
        (xa, ya), (xb, yb) = pts
        if abs(xa - xb) < 0.05 and abs(ya - yb) > 80:
            slots.setdefault((round(min(ya, yb), 0), round(max(ya, yb), 0)), []).append(xa)
    for (ya, yb), xs in slots.items():
        xs.sort()
        for i in range(0, len(xs) - 1):
            if 2.5 < xs[i + 1] - xs[i] < 3.5:
                add('fader', (xs[i] + xs[i + 1]) / 2, (ya + yb) / 2, 3.0, yb - ya, top=ya, bottom=yb)

    # jog wheel
    add('jog', 342.0, 610.5, 44.0, 44.0)

    # the gaps between fader scale lines are not buttons; screw heads are not LEDs
    faders = [c for c in ctl if c['type'] == 'fader']
    ctl[:] = [c for c in ctl if not (c['type'] == 'button' and any(
        abs(c['x'] - f['x']) < 14 and f['top'] - 6 < c['y'] < f['bottom'] + 6 for f in faders))]
    ctl[:] = [c for c in ctl if not (c['type'] == 'led' and any(
        abs(c['x'] - sx) < 1.0 and abs(c['y'] - sy) < 1.0 for sx, sy in screws))]
    # off the top plate (rear handle screws) and the talk mic XLR's fixing holes are not LEDs
    ctl[:] = [c for c in ctl if not (c['type'] == 'led' and (c['y'] < 70 or (600 < c['x'] < 632 and 92 < c['y'] < 125)
              or c['x'] < 50 or c['x'] > 635 or 344 < c['y'] < 353
              or any(abs(c['x'] - f['x']) < 3 and f['top'] - 9 < c['y'] < f['top'] for f in faders)))]

    # nested duplicates (knob ring + cap etc.): keep one per position and type family
    out = []
    for c in sorted(ctl, key=lambda c: -c['w'] * c['h']):
        if any(abs(c['x'] - o['x']) < 1.5 and abs(c['y'] - o['y']) < 1.5 and c['type'] == o['type'] for o in out):
            continue
        out.append(c)
    return out


def attach_labels(ctl, labels):
    """the silkscreen legend of each control: text inside it, else the nearest legend close by"""
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


# ------------------------------------------------------------------------------------------------
# bindings: what each control does (resolved in the browser)
# ------------------------------------------------------------------------------------------------

def bind(ctl):
    def near(types, x, y, tol=2.5):
        best = None
        for c in ctl:
            if c['type'] in types and abs(c['x'] - x) < tol and abs(c['y'] - y) < tol:
                best = c
        if best is None:
            raise SystemExit(f'no {types} near {x},{y}')
        return best

    def B(types, x, y, **b):
        near(types, x, y)['bind'] = b

    btn = ('button', 'ledbutton', 'round', 'lcd', 'arrow')

    # ---- selected-channel strip (upper centre)
    B(btn, 414.1, 101.8, kind='sel', p='ch_mute', toggle=True)
    B(btn, 414.1, 131.3, kind='sel', p='ch_phantom', toggle=True)
    B(btn, 414.1, 140.6, kind='sel', p='ch_phase', toggle=True)
    B(('knob',), 470.6, 135.6, kind='sel', p='ch_gain', lo=-18, hi=60, unit='dB')
    B(('knob',), 430.9, 135.6, kind='sel', p='ch_hpf', lo=20, hi=400, log=True, unit='Hz')
    B(btn, 430.9, 151.3, kind='sel', p='ch_hpf_on', toggle=True)
    B(btn, 414.1, 172.1, kind='sel', p='ch_comp_on', toggle=True)
    B(btn, 414.2, 205.0, kind='sel', p='ch_gate_on', toggle=True)
    B(btn, 475.8, 200.5, kind='mode', mode='dyn', value='gate')
    B(btn, 475.8, 218.9, kind='mode', mode='dyn', value='comp')
    B(('knob',), 452.6, 195.9, kind='dyn', gate=['ch_gate_thr', -50, 25], comp=['ch_comp_thr', -50, 25], unit='dB')
    B(('knob',), 431.6, 206.8, kind='dyn', gate=['ch_gate_range', 0, 100], comp=['ch_comp_ratio', 1, 25, 'log'], unit='')
    B(('knob',), 431.6, 184.7, kind='dyn', gate=['ch_gate_att', 0.02, 20, 'log'], comp=['ch_comp_att', 0.2, 20, 'log'], unit='ms')
    B(('knob',), 452.6, 173.6, kind='dyn', gate=['ch_gate_rel', 2, 2000, 'log'], comp=['ch_comp_rel', 50, 3000, 'log'], unit='ms')
    B(('knob',), 473.6, 184.6, kind='dyn', gate=['ch_gate_hold', 2, 2000, 'log'], comp=None, unit='ms')
    B(('knob',), 452.6, 218.0, kind='dyn', gate=None, comp=['ch_comp_makeup', 0, 24], unit='dB')
    B(btn, 414.1, 264.7, kind='sel', p='ch_eq_on', toggle=True)
    B(btn, 475.6, 266.4, kind='mode', mode='band', value='up')
    B(btn, 475.6, 289.0, kind='mode', mode='band', value='down')
    B(('knob',), 440.2, 266.6, kind='band', p='ch_eq_f', lo=20, hi=20000, log=True, unit='Hz')
    B(('knob',), 457.4, 282.4, kind='band', p='ch_eq_g', lo=-15, hi=15, unit='dB')
    B(('knob',), 432.9, 289.1, kind='band', p='ch_eq_q', lo=0.3, hi=10, log=True, unit='')
    B(('knob',), 469.1, 325.6, kind='sel', p='ch_pan', lo=-100, hi=100, unit='')

    # ---- mix sends: AUX 1-16 put that bus send on the faders, "clear" returns to faders
    aux_x = (494.2, 512.9)
    aux_y = (102.2, 114.3, 126.0, 138.0, 155.6, 167.2, 179.3, 190.9)
    for r, y in enumerate(aux_y):
        for k, x in enumerate(aux_x):
            n = r * 2 + k + 1
            B(btn, x, y, kind='sends', bus=n)
    B(btn, 512.9, 260.4, kind='sends', bus=0)

    # ---- masters (main L/R = vchannel 81, mono/centre = 72) and monitor
    B(btn, 538.0, 164.6, kind='fixed', p='ch_mute', i=81, toggle=True)
    B(btn, 552.0, 164.6, kind='fixed', p='ch_mute', i=72, toggle=True)
    B(btn, 537.9, 177.4, kind='fixed', p='ch_solo', i=81, toggle=True)
    B(btn, 551.9, 177.4, kind='fixed', p='ch_solo', i=72, toggle=True)
    B(('fader',), 544.7, 251.3, kind='fixed', p='fader', i=81, lo=-100, hi=10, law='fader')
    B(('fader',), 581.4, 251.3, kind='fixed', p='mon_level', i=1, lo=-100, hi=10, law='fader')
    # master meters: main L/R; the monitor meters follow main L/R (OMC has no monitor meter)
    for c in ctl:
        if c['type'] == 'meter' and c['y'] < 200 and 530 < c['x'] < 605:
            left = c['x'] < 545 or 565 < c['x'] < 582
            c['bind'] = dict(kind='meter', p='main_meter_l' if left else 'main_meter_r', i=1)
    B(btn, 617.4, 245.8, kind='fixed', p='solo_clear', i=1, toggle=True)

    # ---- channel faders: two banks of eight
    left = [95.0, 121.7, 148.1, 174.8, 201.0, 227.6, 254.1, 280.5]
    right = [404.7, 431.1, 457.8, 484.0, 510.7, 537.3, 563.9, 590.5]
    for bank, xs in (('L', left), ('R', right)):
        for k, x in enumerate(xs):
            B(('fader',), x, 551.9, kind='strip', bank=bank, slot=k, p='fader', lo=-100, hi=10, law='fader')
            B(btn, x - 6.5, 454.7, kind='strip', bank=bank, slot=k, p='ch_mute', toggle=True)
            B(btn, x - 6.5, 476.4, kind='strip', bank=bank, slot=k, p='ch_solo', toggle=True)
            B(('lcd',), x, 428.4, kind='strip', bank=bank, slot=k, p='sel', select=True)
            for c in ctl:
                if c['type'] == 'meter' and c['y'] > 350 and abs(c['x'] - (x + 6.0)) < 3.5 and 440 < c['y'] < 490:
                    c['bind'] = dict(kind='strip', bank=bank, slot=k, p='ch_meter')
    # scroll arrows: bank paging
    B(btn, 72.4, 428.3, kind='scroll', bank='L', step=-1)
    B(btn, 303.2, 428.3, kind='scroll', bank='L', step=1)
    B(btn, 382.0, 428.3, kind='scroll', bank='R', step=-1)
    B(btn, 612.8, 428.5, kind='scroll', bank='R', step=1)
    # input / output layer for the left bank, mix bay for the right bank
    B(btn, 314.2, 460.6, kind='layer', bank='L', value='input')
    B(btn, 314.2, 474.4, kind='layer', bank='L', value='output')
    B(btn, 617.1, 460.8, kind='layer', bank='R', value='vca')
    B(btn, 617.1, 474.8, kind='layer', bank='R', value='aux')
    B(btn, 617.1, 488.6, kind='layer', bank='R', value='aux2')
    B(btn, 617.1, 502.3, kind='layer', bank='R', value='mtx')
    B(btn, 617.1, 516.4, kind='layer', bank='R', value='mast')

    # ---- assignable controls: the eight encoders under the screen follow the knob focused on the
    # touch UI (docs/26: tap a knob, the encoders drive that row across the 8 strips); the keys under
    # them are that row's toggles (OMC SURFACE_ENCODER / SURFACE_ENC_KEY / SURFACE_ENC_POS)
    for k, x in enumerate([95.0, 121.5, 148.2, 174.6, 201.2, 227.5, 254.2, 280.8]):
        B(('knob',), x, 385.1, kind='enc', i=k + 1, what=f'encoder {k + 1}: the focused row, strip {k + 1}')
        B(btn, [95.0, 121.8, 148.3, 174.7, 201.2, 227.4, 254.2, 281.1][k], 403.1, kind='enckey', i=k + 1,
          what=f'toggle of the focused row, strip {k + 1}')

    # ---- navigation: the jog wheel steps the selected channel; the four arrows move the cursor
    # and the round centre keys pick touch-UI screens, both driving the touch UI (OMC SURFACE_COMMAND "ui_cmd" / SURFACE_SCREEN "screen")
    near(('jog',), 342.0, 610.5)['bind'] = dict(kind='jog')
    for c in ctl:
        if c['type'] == 'arrow' and 320 < c['x'] < 365 and c['y'] < 420:
            c['bind'] = dict(kind='cmd', p='ui_cmd', value={'left': 1, 'right': 2, 'up': 3, 'down': 4}[c['dir']], what='cursor ' + c['dir'])
    # touch UI pages: OVERVIEW 0, CHANNEL 1, BUSES 2, ROUTING 3, EFFECTS 4, MONITOR 5, AUTOMIX 6, SCENES 7, SHOW 8 ... GROUPS 16
    screen_keys = [(500.8, 8, 'automation / filing'), (512.0, 4, 'effects / graphics'), (523.2, 3, 'routing / metering'),
                   (534.4, 1, 'inputs / outputs'), (545.6, 5, 'monitors / preferences'), (556.8, 16, "vca's / assignable controls: VCA / mute / POP assignment")]
    for y, page, what in screen_keys:
        B(btn, 319.5, y, kind='radio', p='screen', i=1, value=page, what=what)
    # automation: Last / Now / Next / Store / OK / Cancel -> cue list and scenes on the touch UI
    for x, y, v, what in [(560.8, 384.9, 5, 'Last cue'), (577.0, 384.9, 6, 'Now: recall scene'), (593.0, 384.9, 7, 'Next cue'),
                          (559.6, 400.6, 8, 'Store scene'), (576.1, 400.6, 9, 'OK: commit preview'), (592.2, 400.6, 10, 'Cancel: discard preview')]:
        B(btn, x, y, kind='cmd', p='ui_cmd', value=v, what=what)

    # population keys: POP groups 1-6 spill onto the faders (docs/26); mute group keys 1-6: masters
    pop = sorted((c for c in ctl if c['type'] == 'lcd' and c['y'] < 400), key=lambda c: c['x'])
    for k, c in enumerate(pop):
        c['bind'] = dict(kind='cmd', p='ui_cmd', value=50 + k, touch=True, caption=f'POP {k + 1}',
                         what=f'POP {k + 1}: spill onto the faders and the touch UI')
    for k, (x, y) in enumerate([(494.2, 283.8), (512.9, 283.7), (494.2, 296.8), (512.9, 296.8), (494.2, 311.4), (512.9, 311.4)]):
        B(btn, x, y, kind='fixed', p=f'mute_group{k + 1}', i=1, toggle=True)
    # SHAPE: cycles the type of the EQ band being edited
    B(btn, 457.4, 264.5, kind='cycle', p='ch_eq_type', n=8)

    # the rest of the PRO1 keys and pots, by what they do in OMC:
    #  fn  -> a desk-model function of the touch UI (SURFACE_STATE slot, OSC "surface/<fn>", MidasUi)
    #  cmd -> a touch-UI command (OSC "ui_cmd"); sel -> select an OMC channel; eng -> an engine parameter
    FUNCS = [
        (430.9, 102.2, 'fn', 1, 'safe: EQ'), (450.6, 102.2, 'fn', 2, 'safe: dynamics'), (470.4, 102.2, 'fn', 3, 'safe: mic amp'),
        (430.9, 111.3, 'fn', 4, 'safe: automation'), (450.6, 111.3, 'fn', 5, 'safe: mute'), (470.4, 111.3, 'fn', 6, 'safe: fader'),
        (414.1, 122.0, 'fn', 7, 'input talk'), (430.9, 122.2, 'fn', 8, 'high pass slope 6/12'),
        (448.9, 122.2, 'fn', 9, 'low pass slope 6/12'), (475.6, 122.2, 'fn', 10, 'meter check (input meter point)'),
        (617.4, 134.1, 'fnk', 11, 'talk mic gain'), (448.8, 135.6, 'fnk', 12, 'low pass frequency'),
        (448.8, 151.3, 'fn', 14, 'low pass in'), (475.6, 151.2, 'fn', 15, 'stage box 30 Hz filter'),
        (617.4, 153.1, 'fnk', 16, 'talk limiter'), (475.6, 161.4, 'fn', 17, 'processing order C/O'),
        (574.6, 164.6, 'fn', 18, 'monitor mute'), (588.6, 164.6, 'fn', 19, 'monitor B mute'),
        (431.6, 172.4, 'fn', 20, 'compressor mode (style)'), (617.3, 172.1, 'fnk', 21, 'talk level'),
        (573.9, 177.7, 'fn', 22, 'monitor dim'), (587.9, 177.7, 'fn', 23, 'monitor B C/O'),
        (616.6, 189.7, 'fn', 26, 'talk internal'), (616.5, 201.2, 'fn', 28, 'talk external'),
        (616.6, 213.0, 'fn', 31, 'oscillator internal'), (616.5, 225.1, 'fn', 36, 'oscillator external'),
        (431.6, 221.7, 'fn', 34, 'compressor knee hard/soft'), (457.4, 235.4, 'fn', 39, 'side chain filter in'),
        (414.1, 235.5, 'fn', 40, 'insert in'), (473.6, 239.3, 'fnk', 41, 'side chain frequency'),
        (431.6, 245.2, 'fn', 45, 'gate listen'), (457.4, 245.2, 'fn', 47, 'side chain width'),
        (616.7, 259.0, 'fn', 48, 'solo ADD'), (616.5, 268.7, 'fn', 50, 'solo PFL / AFL'),
        (617.3, 296.9, 'fnk', 52, 'phones level'), (434.9, 312.2, 'fn', 53, 'feed SIS'),
        (617.4, 314.6, 'fn', 55, 'phones mute'), (616.7, 325.3, 'fn', 57, 'solo to fader'), (73.0, 402.8, 'fn', 63, 'ALT'),
        (414.1, 150.8, 'cmd', 20, 'select: input section'), (414.1, 191.2, 'cmd', 22, 'select: compressor'),
        (414.1, 224.2, 'cmd', 21, 'select: gate'), (414.1, 244.8, 'cmd', 24, 'select: insert / direct out'),
        (414.1, 295.2, 'cmd', 23, 'select: EQ'), (414.1, 331.4, 'cmd', 25, 'select: masters / pan'),
        (444.4, 245.2, 'cmd', 22, 'side chain menu'), (495.0, 260.5, 'cmd', 27, 'mute group / assign'),
        (513.0, 331.2, 'cmd', 27, 'assign'), (73.0, 385.2, 'cmd', 11, 'view (home)'),
        (302.8, 385.1, 'cmd', 30, 'assignable controls setup'), (302.4, 402.9, 'cmd', 32, 'user layers'),
        (617.1, 530.5, 'cmd', 33, 'GEQ / effects'), (328.2, 573.9, 'cmd', 11, 'home'), (355.9, 574.0, 'cmd', 9, 'enter / OK'),
        (538.1, 189.3, 'sel', 80, 'select main L/R'), (551.7, 189.1, 'sel', 71, 'select mono'),
        (451.6, 312.1, 'eng', 'ch_send_lr', 'send to main (ST)'), (451.6, 325.6, 'eng', 'ch_send_mono', 'send to mono (MON)'),
        (434.8, 325.4, 'engk', 'ch_mono_level', 'mono level'),
        (342.4, 464.4, 'bay', 'align', 'ALIGN: right bank continues the left'),
        (364.1, 464.6, 'bay', 'extend', 'EXTEND: right bank on the next eight channels (toggle; Scroll moves both banks)'),
    ]
    for k, (x, y) in enumerate([(494.2, 208.5), (512.2, 208.5), (494.2, 220.7), (512.2, 220.7),
                                (494.2, 232.3), (512.2, 232.3), (494.2, 244.0), (512.2, 244.0)]):
        FUNCS.append((x, y, 'cmd', 41 + k, f'select matrix {k + 1}'))
    for x, y, kind, v, what in FUNCS:
        types = ('knob', 'pot') if kind in ('fnk', 'engk') else btn
        if kind in ('fn', 'fnk'):
            B(types, x, y, kind='surface', i=v, toggle=kind == 'fn', what=what)
        elif kind == 'cmd':
            B(types, x, y, kind='cmd', p='ui_cmd', value=v, what=what)
        elif kind == 'sel':
            B(types, x, y, kind='radio', p='sel', i=1, value=v, what=what)
        elif kind == 'eng':
            B(types, x, y, kind='sel', p=v, toggle=True, what=what)
        elif kind == 'engk':
            B(types, x, y, kind='sel', p=v, lo=-100, hi=10, unit='dB', what=what)
        elif kind == 'bay':
            B(types, x, y, kind='bay', value=v, what=what)
    left = [c for c in ctl if not c.get('bind') and c['type'] not in ('led', 'meter')]
    if left:
        raise SystemExit('controls without a function: ' + ', '.join(f"{c['type']}@{c['x']:.1f},{c['y']:.1f}" for c in left))

    # LEDs: the four at the EQ band keys show the band; every other LED shows its key
    keys = [c for c in ctl if c['type'] in ('button', 'ledbutton', 'round')]
    for c in ctl:
        if c['type'] != 'led':
            continue
        if 470 < c['x'] < 482 and 255 < c['y'] < 300:
            c['bind'] = dict(kind='bandled')
            continue
        k = min(keys, key=lambda k: (abs(k['x'] - c['x']) + abs(k['y'] - c['y'])))
        c['bind'] = dict(kind='mirror', x=k['x'], y=k['y'])
    for c in ctl:
        c.setdefault('bind', None)


# ------------------------------------------------------------------------------------------------
# SVG
# ------------------------------------------------------------------------------------------------

CAP_SKIP = []  # fader caps are drawn by the browser at the live position


def is_cap(pts):
    mn, mx = pts.min(0), pts.max(0)
    for (x, ya, yb) in CAP_SKIP:
        if mn[0] > x - 8 and mx[0] < x + 8 and mn[1] > ya and mx[1] < yb:
            return True
    return False


def write_svg(polys, labels, ctl, screen, fn, panels=()):
    for c in ctl:
        if c['type'] == 'fader':
            CAP_SKIP.append((c['x'], c['bottom'] - 6.5, c['bottom'] + 27.5))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.2f} {H:.2f}" width="{W:.2f}mm" height="{H:.2f}mm">']
    # white inset panels of the processing sections (PRO1 photographs), under the line art
    out.append('<g class="insets">')
    for poly in panels:
        out.append('<path d="M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in poly) + ' Z"/>')
    out.append('</g>')
    out.append('<g class="lines" fill="none" stroke-linecap="round" stroke-linejoin="round">')
    bylayer = {}
    for layer, pts in polys:
        if is_cap(pts):
            continue
        bylayer.setdefault(layer, []).append('M' + ' '.join(f'{x:.2f} {y:.2f}' for x, y in pts))
    for i, (layer, ds) in enumerate(sorted(bylayer.items())):
        out.append(f'<path class="L{i}" data-layer="{layer}" d="{" ".join(ds)}"/>')
    out.append('</g>')
    out.append('<g class="legend">')
    for t in labels:
        anchor = {1: 'start', 4: 'start', 7: 'start', 2: 'middle', 5: 'middle', 8: 'middle'}.get(t['ap'], 'end')
        lines = t['s'].split('\n')
        dy0 = {1: 0.8, 2: 0.8, 3: 0.8, 4: 0.35 - 0.5 * (len(lines) - 1), 5: 0.35 - 0.5 * (len(lines) - 1), 6: 0.35 - 0.5 * (len(lines) - 1)}.get(t['ap'], -(len(lines) - 1))
        rot = f' transform="rotate({-t["rot"]:.1f} {t["x"]:.2f} {t["y"]:.2f})"' if abs(t['rot']) > 0.5 else ''
        esc = [l.replace('&', '&amp;').replace('<', '&lt;') for l in lines]
        spans = ''.join(f'<tspan x="{t["x"]:.2f}" dy="{(dy0 if k == 0 else 1.15):.2f}em">{l}</tspan>' for k, l in enumerate(esc))
        dark = any(cv2.pointPolygonTest(np.array(p, np.float32), (float(t['x']), float(t['y'])), False) >= 0 for p in panels)
        cls = ' class="dark"' if dark else ''
        out.append(f'<text x="{t["x"]:.2f}" y="{t["y"]:.2f}" font-size="{t["h"]:.2f}" text-anchor="{anchor}"{rot}{cls}>{spans}</text>')
    out.append('</g>')
    x, y, w, h = screen
    out.append(f'<rect id="screen" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/>')
    out.append('</svg>')
    open(fn, 'w').write('\n'.join(out))


# ------------------------------------------------------------------------------------------------
# finish: key and knob colours and the white inset panels, from the PRO1 photographs (Bestec PRO1
# brochure). Keys carry a translucent colour cap that lights up; knobs have a coloured cap.
# ------------------------------------------------------------------------------------------------

def colour(ctl):
    def at(x, y, tol=2.5):
        return [c for c in ctl if abs(c['x'] - x) < tol and abs(c['y'] - y) < tol and c['type'] not in ('led', 'meter')]

    def put(x, y, cap):
        for c in at(x, y):
            c['tint'] = cap

    for c in ctl:
        b = c.get('bind') or {}
        t = c['type']
        if t in ('knob', 'pot'):
            c['tint'] = 'grey'
        elif t == 'arrow':
            c['tint'] = 'light'
        elif t in ('button', 'ledbutton', 'round'):
            c['tint'] = 'grey'
        if b.get('kind') == 'strip' and b.get('p') == 'ch_mute':
            c['tint'] = 'red'
        if b.get('kind') == 'strip' and b.get('p') == 'ch_solo':
            c['tint'] = 'amber'
        if str(b.get('p', '')).startswith('mute_group'):
            c['tint'] = 'red'
        if b.get('kind') == 'layer':
            c['tint'] = 'lilac'
    # channel safes EQ DYN MIC / AUTO MUTE FADER (also the offline editor's PRO1 safes artwork)
    for (x, y), cap in {(430.9, 102.2): 'red', (450.6, 102.2): 'violet', (470.4, 102.2): 'grey',
                        (430.9, 111.3): 'amber', (450.6, 111.3): 'red', (470.4, 111.3): 'green'}.items():
        put(x, y, cap)
    # selected-channel strip keys
    for (x, y), cap in {(414.1, 101.8): 'red', (414.1, 122.0): 'green', (414.1, 131.3): 'red', (414.1, 140.6): 'blue',
                        (475.6, 161.4): 'blue', (414.1, 172.1): 'blue', (414.2, 205.0): 'blue', (414.1, 235.5): 'blue',
                        (457.4, 235.4): 'blue', (431.6, 245.2): 'yellow', (414.1, 264.7): 'red', (457.4, 264.5): 'dark',
                        (475.8, 200.5): 'light', (475.8, 218.9): 'light', (475.6, 266.4): 'light', (475.6, 289.0): 'light',
                        (434.9, 312.2): 'red', (451.6, 312.1): 'red', (451.6, 325.6): 'yellow'}.items():
        put(x, y, cap)
    # mix sends: AUX / MTX key pairs by row: red, green, yellow, blue
    rows = [102.2, 114.3, 126.0, 138.0, 155.6, 167.2, 179.3, 190.9, 208.5, 220.7, 232.3, 244.0]
    for k, y in enumerate(rows):
        for x in (494.2, 512.5):
            put(x, y, ['red', 'green', 'yellow', 'blue'][k % 4])
    # masters / monitor: MUTE red, SOLO amber
    for x, y in [(538.0, 164.6), (552.0, 164.6), (574.6, 164.6), (588.6, 164.6), (617.4, 314.6)]:
        put(x, y, 'red')
    for x, y in [(537.9, 177.4), (551.9, 177.4)]:
        put(x, y, 'amber')
    # automation: LAST red, NOW amber, NEXT grey; store yellow, ok green, cancel red
    for (x, y), cap in {(560.8, 384.9): 'red', (577.0, 384.9): 'amber', (593.0, 384.9): 'grey',
                        (559.6, 400.6): 'yellow', (576.1, 400.6): 'green', (592.2, 400.6): 'red'}.items():
        put(x, y, cap)
    put(364.1, 464.6, 'purple')     # EXTEND
    put(342.4, 464.4, 'purple')     # ALIGN
    # knob caps: dynamics green, threshold and ratio/range violet, make-up red; EQ light blue;
    # mono level orange, pan red
    for (x, y), cap in {(431.6, 184.7): 'green', (452.6, 173.6): 'green', (473.6, 184.6): 'green',
                        (452.6, 195.9): 'violet', (431.6, 206.8): 'violet', (452.6, 218.0): 'red',
                        (440.2, 266.6): 'cyan', (457.4, 282.4): 'cyan', (432.9, 289.1): 'cyan',
                        (434.8, 325.4): 'orange', (469.1, 325.6): 'red'}.items():
        put(x, y, cap)


def white_panels(img):
    """outlines of the white processing panels: flood the drawing's own outline from a seed inside"""
    seeds = [(424.0, 196.0), (424.0, 277.0), (408.5, 186.0), (408.5, 219.0), (408.5, 281.0)]
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats((1 - blk).astype(np.uint8), connectivity=4)
    out = []
    for x, y in seeds:
        l = lab[int(y * PX), int(x * PX)]
        if l == 0:
            continue
        mask = (lab == l).astype(np.uint8) * 255
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        c = cv2.approxPolyDP(c, 1.5, True)
        out.append([(p[0][0] / PX, p[0][1] / PX) for p in c])
    return out


def find_screen(reg):
    # the display opening: the largest enclosed region in the top-left quarter
    best = max((r for r in reg if r['cx'] < 400 and r['cy'] < 350), key=lambda r: r['w'] * r['h'])
    return best['x'], best['y'], best['w'], best['h']


def screen_region(img):
    blk = cv2.dilate((img < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats((1 - blk).astype(np.uint8), connectivity=4)
    cands = [st[i] for i in range(1, n) if st[i][0] < 1000 and 1000 < st[i][1] < 1500 and st[i][2] > 2500 and st[i][3] > 1800]
    x, y, w, h, _ = min(cands, key=lambda s: s[2] * s[3])
    return x / PX, y / PX, w / PX, h / PX


def main():
    if sys.argv[1] == '--model':
        # PRO2 / PRO2C / PRO X: own module (this file's directory; python -I leaves it off sys.path)
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import surface_models
        model, src, outdir = sys.argv[2], sys.argv[3], sys.argv[4]
        pro1 = sys.argv[5] if len(sys.argv) > 5 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www', 'controls.json')
        surface_models.build(model, src, outdir, json.load(open(pro1))['controls'])
        return
    src, outdir = sys.argv[1], sys.argv[2]
    doc, _ = recover.readfile(src)
    polys, texts, screws = collect(doc)
    img = raster(polys)
    reg = regions(img)
    ctl = find_controls(reg, polys, screws)
    labels = label_items(texts)
    attach_labels(ctl, labels)
    bind(ctl)
    colour(ctl)
    panels = white_panels(img)
    screen = screen_region(img)
    for i, c in enumerate(sorted(ctl, key=lambda c: (round(c['y']), c['x']))):
        c['id'] = i
    ctl.sort(key=lambda c: c['id'])
    write_svg(polys, labels, ctl, screen, f'{outdir}/panel.svg', panels)
    json.dump(dict(width=round(W, 2), height=round(H, 2), screen=[round(v, 2) for v in screen], controls=ctl),
              open(f'{outdir}/controls.json', 'w'), indent=0)
    kinds = {}
    for c in ctl:
        kinds[c['type']] = kinds.get(c['type'], 0) + 1
    print('controls', len(ctl), kinds, 'bound', sum(1 for c in ctl if c['bind']), 'screen', screen)


if __name__ == '__main__':
    main()
