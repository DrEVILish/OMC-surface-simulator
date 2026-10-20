#!/usr/bin/env python3
"""
Restore block contents that LibreDWG's DXF writer drops.

dwg2dxf 0.14 writes some BLOCK definitions of PRO2-Control-Centre.dwg empty (the panel's group
blocks: front-panel line art, the silkscreen MTEXT and the nested block references that place the
fader strips), although the DWG holds them and `dwgread -O JSON` decodes them. This copies the
entities of every block that is empty in the DXF from the JSON dump into the DXF, so the plan view
is complete. Geometry is taken as decoded: LINE, ARC, CIRCLE, LWPOLYLINE, POLYLINE_2D, SPLINE,
MTEXT, TEXT and INSERT.

usage: dwgread -O JSON -o x.json X.dwg; dwg2dxf -y -o x.dxf X.dwg
       dwgfill.py x.dxf x.json out.dxf
"""
import json
import math
import sys

from ezdxf import recover


def main():
    src, js, dst = sys.argv[1:4]
    doc, _ = recover.readfile(src)
    objs = json.load(open(js, encoding='utf-8'))['OBJECTS']
    byh = {o['handle'][-1]: o for o in objs if 'handle' in o}
    name_of = {o['handle'][-1]: o.get('name') for o in objs if o.get('object') in ('LAYER', 'BLOCK_HEADER')}
    filled = added = 0
    for bh in (o for o in objs if o.get('object') == 'BLOCK_HEADER'):
        name = bh.get('name')
        if not name or name.startswith('*'):
            continue
        blk = doc.blocks.get(name)
        ents = bh.get('entities') or []
        if blk is None or len(blk) or not ents:
            continue
        filled += 1
        for ref in ents:
            o = byh.get(ref[-1])
            if o and add(blk, o, byh, name_of, doc):
                added += 1
    doc.saveas(dst)
    print(f'filled {filled} blocks, {added} entities')


def P(v):
    return (v[0], v[1]) if isinstance(v, list) else (v['x'], v['y'])


def add(blk, o, byh, name_of, doc):
    t = o.get('entity')
    la = name_of.get((o.get('layer') or [0])[-1]) or '0'
    if la not in doc.layers:
        doc.layers.add(la)
    at = {'layer': la}
    if t == 'LINE':
        blk.add_line(P(o['start']), P(o['end']), dxfattribs=at)
    elif t == 'CIRCLE':
        blk.add_circle(P(o['center']), o['radius'], dxfattribs=at)
    elif t == 'ARC':
        blk.add_arc(P(o['center']), o['radius'], math.degrees(o['start_angle']), math.degrees(o['end_angle']), dxfattribs=at)
    elif t == 'LWPOLYLINE':
        pts, bul = o.get('points') or [], o.get('bulges') or []
        if len(pts) < 2:
            return False
        blk.add_lwpolyline([(p[0], p[1], 0, 0, bul[k] if k < len(bul) else 0) for k, p in enumerate(pts)],
                           format='xyseb', close=bool(o.get('flag', 0) & 512), dxfattribs=at)
    elif t == 'POLYLINE_2D':
        vs = [byh.get(v[-1]) for v in o.get('vertex') or []]
        pts = [(v['point'][0], v['point'][1], 0, 0, v.get('bulge', 0)) for v in vs if v and 'point' in v]
        if len(pts) < 2:
            return False
        blk.add_lwpolyline(pts, format='xyseb', close=bool(o.get('flag', 0) & 1), dxfattribs=at)
    elif t == 'SPLINE':
        deg = o.get('degree', 3)
        if o.get('ctrl_pts'):
            cp = [P(p) for p in o['ctrl_pts']]
            if o.get('rational') or o.get('weighted'):
                w = [p.get('w', 1.0) for p in o['ctrl_pts']]
                blk.add_rational_spline(cp, w, degree=deg, knots=o.get('knots'), dxfattribs=at)
            else:
                s = blk.add_open_spline(cp, degree=deg, knots=o.get('knots'), dxfattribs=at)
        elif o.get('fit_pts'):
            blk.add_spline([P(p) for p in o['fit_pts']], degree=deg, dxfattribs=at)
        else:
            return False
    elif t == 'MTEXT':
        x = o.get('x_axis_dir') or [1, 0, 0]
        blk.add_mtext(o.get('text', ''), dxfattribs=dict(at, insert=P(o['ins_pt']), char_height=o.get('text_height', 2.5),
                      attachment_point=o.get('attachment', 1), rotation=math.degrees(math.atan2(x[1], x[0])),
                      width=o.get('rect_width', 0) or 0))
    elif t == 'TEXT':
        blk.add_text(o.get('text_value', ''), dxfattribs=dict(at, insert=P(o['ins_pt']), height=o.get('height', 2.5),
                     rotation=math.degrees(o.get('rotation', 0))))
    elif t == 'INSERT':
        bn = name_of.get(o['block_header'][-1])
        if not bn or bn not in doc.blocks:
            return False
        s = o.get('scale') or [1, 1, 1]
        blk.add_blockref(bn, P(o['ins_pt']), dxfattribs=dict(at, xscale=s[0], yscale=s[1], zscale=s[2],
                         rotation=math.degrees(o.get('rotation', 0))))
    else:
        return False
    return True


if __name__ == '__main__':
    main()
