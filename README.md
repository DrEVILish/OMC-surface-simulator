# OMC-surface-simulator

Operable web replicas of mixing-console control surfaces for OpenMixerControl (OMC), generated from the
consoles' drawings. Split out of OpenProSeries (`web/pro1-surface`, history kept) on 2026-10-19 and used there as a
submodule. Full description: `docs/25-omc-surface-simulator.md` (OpenProSeries).

## Common

Each surface is linked to OMC over OSC (needs OMC patch 0016). The header's model selector (or
`?model=<id>`) switches models; the PRO1 is the default. Banks are changed from the surface's own keys
(Scroll, layer, EXTEND / ALIGN, ...), which send the bank change to OMC, as on the desk; there is no bank
selector in the header.

- `gen-surface.py`  DXF -> `www/panel.svg` (line art + silkscreen) and `www/controls.json` (controls + bindings);
                    `--model <id>` -> `www/models/<id>/` (`surface_models.py`, `surface_models_more.py`)
- `dwgfill.py`      puts back the drawing blocks that LibreDWG's DXF writer drops (PRO2, M32, M32R)
- `pdf2dxf.py`      vector PDF page -> DXF in mm (X32 COMPACT, WING)
- `compose-wing.py` WING COMPACT / WING RACK from WING drawing parts and traced manual figures
- `deploy/gen-surfaces.sh`  regenerates every model from the drawings (the drawings stay local; the generated
                    `www/panel.svg`, `www/controls.json` and `www/models/` are committed, so the page works from a clone)
- `www/`            the page (index.html, surface.css, surface.js) and the generated assets
- `bridge.py`       WebSocket (/ws) <-> OSC bridge to OMC (:10032, feed on :10033)
- `deploy/`         nginx site (port 80), systemd unit, `install.sh`
- `test/`           Playwright checks against an OMC simulator (`test/models.js <url> <model id>`)

## Midas PRO series

### XL8 (`?model=xl8`)

From XL8_mcj.dwg (Bestec 2006) via dwg2dxf; PRO part classes and knobs, silkscreen legends, input-strip
template. Three 8-fader input bays (A + B + C, 24 inputs in a row), mix, matrix and VCA bays; strip
section keys and the channel keypad. Master bay: automation (ui_cmd 5-10), mute group masters, oscillator,
talk, monitor MONO / solo mode / ADD and the screen keys (docs/25 lists what stays unbound).

### PRO1 (default, `/`)

From the vendor drawing (`gen-surface.py`, output in `www/`). Two banks of eight faders: the left bank
pages the INPUT / OUTPUT layers, the right bank is the mix bay (VCA, AUX 1-8, AUX 9-16, MTX, MAST).
EXTEND puts the next eight on the right bank, ALIGN makes it carry on from the left once.

### PRO2 (`?model=pro2`)

From the PRO2 drawing (blocks restored by `dwgfill.py`). Input bays A + B page together as 16 inputs; the
mix bay starts on VCA 1-8. EXTEND / ALIGN as on the PRO1.

### PRO2C (`?model=pro2c`)

Derived from the PRO2 drawing (there is no PRO2C drawing): the PRO2 without input bay A. One input bay
of eight and the mix bay.

### PRO X (`?model=prox`)

From the PRO X drawing. Input bays A (12) + B (4) page together as 16 inputs; the output bay (10) starts
on VCA 1-8. Strip section keys and the channel keypad.

> The **PRO3, PRO6 and PRO9** control centres have the same layout as the PRO X; use the PRO X surface
> for them.

## Behringer / Midas X32 and M32

Legends from the X32 manual. A 16-fader input section paging the channel / aux / FX / bus layers and an
8-fader group section (VCA, buses, matrices); the X32 COMPACT and M32R have 8 + 8.

| id | console | source |
|---|---|---|
| `x32`  | X32         | X32.dxf (Music Group); size table `X32_RULES` |
| `x32c` | X32 COMPACT | X32 COMPACT manual p. 72, TOP view, via `pdf2dxf.py` |
| `x32r` | X32 RACK    | X32RACK.dxf; size table `X32R_RULES`; no faders |
| `m32`  | M32         | M32_Live.dwg via dwg2dxf + `dwgfill.py`; part outlines by contour |
| `m32r` | M32R        | M32R.dwg via dwg2dxf + `dwgfill.py`; part outlines by contour |

## Behringer WING

A 12-fader left section (layer keys 1-12 / 13-24 / 25-36 / aux), an 8-fader centre section (VCA, buses)
and a 4-fader right section (main / matrix) with its 4-channel knob section; custom controls and
PRESETS UP / DOWN. User keys: custom keys 1-8, the lower custom row (user layer) 9-16, F1-F3 9-11. LISTEN is
the selected channel's solo; MONO runs OMC action 54 (OSC `action` / `action_lit`).

| id | console | source |
|---|---|---|
| `wing`  | WING         | WING-Dimensional.pdf, console top, via `pdf2dxf.py` (turned 270 degrees, 870 mm wide) |
| `wingc` | WING COMPACT | no drawing: `compose-wing.py`, WING parts + traced manual figures, to scale; custom controls 1-16 |
| `wingr` | WING RACK    | no drawing: `compose-wing.py`, as above; no faders, one 4-strip bank |

`deploy/gen-surfaces.sh` makes every model (`MANUALS`, `WING_MANUAL` point at the manuals).
