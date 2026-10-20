// OpenProSeries - PRO control surface replicas in the browser, linked to OpenMixerControl.
//
// panel.svg     the plan view of the vendor drawing (line art and silkscreen, millimetres)
// controls.json every control found in the drawing, with its binding (gen-surface.py)
//
// Models: the PRO1 (default, www/) and the PRO2, PRO2C and PRO X (www/models/<id>/, see
// surface_models.py); the XL8, X32, X32 COMPACT, X32 RACK, M32, M32R, WING, WING COMPACT and WING RACK
// (www/models/<id>/, surface_models_more.py). The model comes from ?model=<id>, else the last choice (localStorage). A
// model's controls.json carries its bank layout ("surface": layers, banks, bays; the first of each option); the PRO1
// uses the built-in layout below.
//
// The controls are drawn on top of the line art in the same millimetre space. Bound
// controls read and write OMC parameters through the bridge (/ws, OSC underneath);
// unbound ones latch locally so the whole surface can be operated.
//
// Surface logic, as on the console:
//   - the upper strip edits the selected channel (LCD keys / assignable keys / jog select)
//   - dynamics knobs edit the gate or the compressor (gate / comp keys), EQ knobs edit one
//     band (band up / down keys, band LEDs)
//   - left fader bank: INPUT (channels 1-40) / OUTPUT layers, right bank: mix bay (VCA, AUX 1-8,
//     AUX 9-16, MTX, MAST); Scroll keys page a bank (on the touch layer
//     they page OMC's bank: ui_cmd 90 / 91, W12p; a VCA member of that bank drives vca_level / vca_mute)
//   - EXTEND (toggle): the right bank shows the next eight after the left bank, and either bank's
//     Scroll keys move both; pressed again, the right bank goes back to what it showed
//   - AUX 1-16 keys in "mix sends" put that bus send on the input faders; "clear" returns

'use strict';

const NS = 'http://www.w3.org/2000/svg';

// ------------------------------------------------------------------------------------------------
// model choice: URL parameter, else localStorage (both kept in step); PRO1 when nothing is chosen
// ------------------------------------------------------------------------------------------------

const MODEL_LIST = [{ id: 'pro1', name: 'PRO1' }, { id: 'pro2', name: 'PRO2' }, { id: 'pro2c', name: 'PRO2C' }, { id: 'prox', name: 'PRO X' },
  { id: 'xl8', name: 'XL8' }, { id: 'x32', name: 'X32' }, { id: 'x32c', name: 'X32 COMPACT' }, { id: 'x32r', name: 'X32 RACK' },
  { id: 'm32', name: 'M32' }, { id: 'm32r', name: 'M32R' }, { id: 'wing', name: 'WING' }, { id: 'wingc', name: 'WING COMPACT' },
  { id: 'wingr', name: 'WING RACK' }];
function store(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
function stored(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
const PARAMS = new URLSearchParams(location.search);
let MODEL_ID = PARAMS.get('model') || stored('surface-model') || 'pro1';
if (!MODEL_LIST.some(m => m.id === MODEL_ID)) MODEL_ID = 'pro1';
const ASSETS = () => (MODEL_ID === 'pro1' ? '' : 'models/' + MODEL_ID + '/');
const MODEL_NAME = () => MODEL_LIST.find(m => m.id === MODEL_ID).name;
// per-model preference keys; the PRO1 keeps its original theme key
const prefKey = (what) => (MODEL_ID === 'pro1' && what === 'theme' ? 'pro1-theme' : MODEL_ID + '-' + what);

const S = {
  values: new Map(),          // "path/index" -> value (from OMC)
  local: new Map(),           // control id -> latched state for unbound controls
  sel: 0,                     // selected vchannel (0-based)
  dyn: 'comp',                // dynamics section edits gate or comp
  band: 1,                    // EQ band 1..4
  sends: 0,                   // bus whose sends are on the faders (0 = faders)
  layer: { L: 'input', R: 'input' },
  page: { L: 0, R: 1 },
  extend: null,               // EXTEND on: the right bank's layer and page before it ({layer, page})
  base: {},                   // bank -> first layer index, when ALIGN put it between pages (unequal bank widths)
  sendPage: 0,                // mix sends keys / knobs: 0 = mixes 1-8, 1 = 9-16 (PRO2 / PRO X)
  lastSends: 1,               // the mix FLIP puts back on the faders
  keypad: '',                 // channel select keypad entry (PRO X)
  qmode: 'gain',              // WING 4-channel section: the parameter its knobs and keys edit
  ws: null,
};
const views = [];             // {c, el, update()}
// WING 4-channel section modes (qmode keys): what its 4 knobs (k) and keys (t) edit on the right section's strips
const QUAD = {
  gain: { k: 'ch_gain', lo: -18, hi: 60, unit: 'dB', t: 'ch_phantom' }, gate: { k: 'ch_gate_thr', lo: -50, hi: 25, unit: 'dB', t: 'ch_gate_on' },
  comp: { k: 'ch_comp_thr', lo: -50, hi: 25, unit: 'dB', t: 'ch_comp_on' }, filter: { k: 'ch_hpf', lo: 20, hi: 400, log: true, unit: 'Hz', t: 'ch_hpf_on' },
  pan: { k: 'ch_pan', lo: -100, hi: 100, unit: '', t: 'ch_send_lr' },
};
let model = null, svg = null, controlsLayer = null;

const key = (p, i) => p + '/' + i;
const val = (p, i, d = 0) => (S.values.has(key(p, i)) ? S.values.get(key(p, i)) : d);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// ------------------------------------------------------------------------------------------------
// vchannel layout (OMC: inputs 0-31, aux 32, fx returns 40, buses 48, matrix 64, mono 71, DCA 72, main 80)
//
// The PRO1 has 40 input channels, OMC's engine 32. Inputs 33-40 live in the touch UI's desk model;
// OMC mirrors them as mch_<fn>/<input number> (and msel for the selection), OMC model-mirror.h. A
// strip channel `ch` >= MODEL is such an input: input number ch - MODEL + 1.
// ------------------------------------------------------------------------------------------------

const OMC_INPUTS = 32, MODEL = 1000;
// a desk-model VCA master in an OMC bank (W12p): SURFACE_BANK 2000 + VCA number; its strip channel here is VCA_CH + VCA
const BANK_VCA = 2000, VCA_CH = 10000;
let INPUTS = 40;              // the model's input channels (PRO1 40, PRO2 / PRO2C 56, PRO X 144)
const inputCh = (n) => (n < 0 || n >= INPUTS ? -1 : n < OMC_INPUTS ? n : MODEL + n);   // input n (0-based) -> ch
const inputNo = (ch) => (ch >= MODEL ? ch - MODEL : ch >= 0 && ch < OMC_INPUTS ? ch : -1); // ch -> input (0-based), -1
// engine path -> its model mirror (what OMC carries for inputs 33-40): ch_<fn> -> mch_<fn>, with the
// engine's ranges, so every per-channel control has a target on a model input too
const MIRROR = { fader: 'mch_fader' };
for (const p of ['mute', 'solo', 'name', 'color', 'meter', 'gain', 'pan', 'hpf', 'hpf_on', 'phantom', 'phase',
  'eq_on', 'gate_on', 'comp_on', 'gate_thr', 'gate_range', 'gate_att', 'gate_hold', 'gate_rel',
  'comp_thr', 'comp_ratio', 'comp_att', 'comp_rel', 'comp_makeup', 'send_lr', 'send_mono', 'mono_level',
  ...[1, 2, 3, 4].flatMap(b => ['eq_f' + b, 'eq_g' + b, 'eq_q' + b, 'eq_type' + b]),
  ...Array.from({ length: 16 }, (_, k) => 'send' + String(k + 1).padStart(2, '0'))]) MIRROR['ch_' + p] = 'mch_' + p;
// the bus send of channel ch on the faders ("mix sends"), as an engine path
const sendPath = (bus) => 'ch_send' + String(bus).padStart(2, '0');
// OSC address of a per-channel path for channel ch (null: OMC has no such parameter for it)
function chAddr(p, ch) {
  if (ch < 0 || ch >= VCA_CH) return null;   // a VCA member (W12p) has no channel parameters
  if (ch < MODEL) return { p, i: ch + 1 };
  if (p === 'sel') return { p: 'msel', i: 1 };
  return MIRROR[p] ? { p: MIRROR[p], i: ch - MODEL + 1 } : null;
}
const chVal = (p, ch, d) => { const a = chAddr(p, ch); return a ? val(a.p, a.i, d) : d; };

// Bank layout. A layer is a list of channels; a bank (a group of fader slots) pages through a layer;
// a bay (the slots of one physical fader group, named in the bindings) is a bank and its first slot.
// "touch" follows OMC's bank (SURFACE_BANK 1-16 from the bank's touch base). extend = [source, target]:
// EXTEND / ALIGN put the target bank on the source's next channels.
const PRO1_SURFACE = {
  inputs: 40,
  layers: {
    input: { inputs: 40 }, output: { chs: [...Array(16).keys()].map(k => 48 + k).concat([64, 65, 66, 67, 68, 69]) },
    vca: { chs: [72, 73, 74, 75, 76, 77, 78, 79] }, aux: { chs: [48, 49, 50, 51, 52, 53, 54, 55] },
    aux2: { chs: [56, 57, 58, 59, 60, 61, 62, 63] }, mtx: { chs: [64, 65, 66, 67, 68, 69] }, mast: { chs: [80, 71] },
  },
  banks: { L: { slots: 8, layer: 'input', page: 0, touch: 1 }, R: { slots: 8, layer: 'input', page: 1, touch: 9 } },
  bays: { L: ['L', 0], R: ['R', 0] },
  extend: ['L', 'R'],
};
let SURFACE = PRO1_SURFACE, LAYERS = {}, BANKS = {}, BAYS = {}, EXT = null;
function setLayout(surface, choice = {}) {
  SURFACE = surface;
  INPUTS = surface.inputs;
  LAYERS = {};
  for (const [name, d] of Object.entries(surface.layers)) {
    // inputs (optionally a run of them: first, count) and / or other channels (chs), in that order
    let list = d.inputs ? Array.from({ length: d.count ?? d.inputs }, (_, n) => inputCh((d.first || 0) + n)) : d.chs;
    if (d.inputs && d.chs) list = list.concat(d.chs);
    LAYERS[name] = { list, count: list.length };
  }
  LAYERS.touch = { list: [], count: 0 };
  let banks = surface.banks, bays = surface.bays, ext = surface.extend;
  for (const o of surface.options || []) {
    const v = o.values.find(v => v.id === choice[o.id]) || o.values[0];
    if (v.banks) { banks = v.banks; bays = v.bays; ext = v.extend; }
  }
  BANKS = JSON.parse(JSON.stringify(banks)); BAYS = bays; EXT = ext || null;
  for (const o of surface.options || []) {
    const v = o.values.find(v => v.id === choice[o.id]) || o.values[0];
    if (o.bank && v.layer && BANKS[o.bank]) { BANKS[o.bank].layer = v.layer; BANKS[o.bank].page = v.page || 0; }
  }
  S.layer = {}; S.page = {}; S.base = {}; S.extend = null;
  for (const [b, d] of Object.entries(BANKS)) { S.layer[b] = d.layer; S.page[b] = d.page || 0; }
}
const bankOf = (bay) => BAYS[bay] || [bay, 0];
const pagesOf = (bank, layer) => Math.max(1, Math.ceil(LAYERS[layer || S.layer[bank]].count / BANKS[bank].slots));

function chName(ch) {
  if (ch < 0) return '';
  if (ch >= VCA_CH) return 'VCA ' + (ch - VCA_CH + 1);
  if (ch >= MODEL) return 'Ch ' + (ch - MODEL + 1);
  if (ch < 32) return 'Ch ' + (ch + 1);
  if (ch < 40) return 'Aux ' + (ch - 31);
  if (ch < 48) return 'FX ' + (ch - 39);
  if (ch < 64) return 'Bus ' + (ch - 47);
  if (ch < 70) return 'Mtx ' + (ch - 63);
  if (ch === 71) return 'Mono';
  if (ch < 80) return 'DCA ' + (ch - 71);
  if (ch === 80) return 'Main';
  return '#' + (ch + 1);
}

// the VCA layer's slot k (VCA k + 1) when bay shows it, else -1
function vcaSlot(bay, ch) {
  const [bank] = bankOf(bay);
  if (ch >= VCA_CH) return ch - VCA_CH;   // a VCA member of the touch UI's bank (W12p)
  return S.layer[bank] === 'vca' && ch >= 72 && ch < 80 ? ch - 72 : -1;
}

function stripChannel(bay, slot) {
  const [bank, off] = bankOf(bay), k = slot + off, B = BANKS[bank];
  if (!B || k >= B.slots) return -1;
  // "touch": the strips the touch UI put on the surface (POP spill, fader bank), OMC SURFACE_BANK:
  // vchannel + 1, or MODEL + input number for an input with no engine channel (so bank - 1 is the
  // strip channel either way); 0 = none
  if (S.layer[bank] === 'touch') {
    if (!B.touch || B.touch + k > 16) return -1;
    const v = Math.round(val('bank', B.touch + k, 0));
    return v > BANK_VCA ? VCA_CH + v - BANK_VCA - 1 : v - 1;
  }
  const L = LAYERS[S.layer[bank]];
  let idx = S.page[bank] * B.slots + k;
  if (S.extend && EXT && bank === EXT[1] && BANKS[EXT[0]].slots !== B.slots) idx = (S.page[EXT[0]] + 1) * BANKS[EXT[0]].slots + k;
  else if (S.base[bank] !== undefined) idx = S.base[bank] + k;
  return idx < L.count ? L.list[idx] : -1;   // EXTEND past the last page: blank
}

// EXTEND: the target bank on the channels after the source bank (same layer; blank past the end)
function extendFollow() {
  if (!S.extend) return;
  const [a, b] = EXT;
  S.layer[b] = S.layer[a];
  S.page[b] = S.page[a] + 1;
  delete S.base[b];
}
// a key that sets the right bank itself (mix bay layer, ALIGN, POP spill) ends EXTEND, keeping its choice
function extendOff() { S.extend = null; }

// the selected channel: OMC's sel, or the model input in msel while one is selected
function selFromOmc() {
  const m = Math.round(val('msel', 1, 0));
  return m >= 1 ? inputCh(m - 1) : Math.round(val('sel', 1, 0));
}
// step the selection: inputs 1-40 in order, then OMC's other vchannels (aux 32 .. main 80)
function selStep(ch, d) {
  const n = inputNo(ch);
  if (n >= 0) return n + d < 0 ? ch : n + d < INPUTS ? inputCh(n + d) : OMC_INPUTS;
  const c = ch + d;
  return c < OMC_INPUTS ? inputCh(INPUTS - 1) : Math.min(c, 80);
}

// a fixed fader (masters, monitor) or one of its keys that OMC gave a strip (SETUP > Surface & Controls,
// OMC assignables.h): bind.fx is the slot, OMC fixfader <fx + 1> the strip in the SURFACE_BANK encoding (vchannel + 1,
// 1000 + model input, 2000 + VCA; 0 = the default). The strip channel, or -1 while it is on its default
function fixedCh(b) {
  if (!b || b.fx === undefined) return -1;
  const t = Math.round(val('fixfader', b.fx + 1, 0));
  if (t <= 0) return -1;
  return t > BANK_VCA ? VCA_CH + t - BANK_VCA - 1 : t - 1;
}
// the parameter a fixed control writes for the strip it follows: fader / MUTE / SOLO of a channel or a VCA master
function fixedAddr(b, ch, p) {
  if (ch >= VCA_CH) {
    const vp = { fader: 'vca_level', ch_mute: 'vca_mute', ch_solo: 'vca_solo' }[p];
    return vp ? { p: vp, i: ch - VCA_CH + 1, lo: b.lo, hi: b.hi, unit: b.unit, ch, vca: ch - VCA_CH } : null;
  }
  const a = chAddr(p, ch);
  return a && { p: a.p, i: a.i, lo: b.lo, hi: b.hi, unit: b.unit, ch };
}

// ------------------------------------------------------------------------------------------------
// resolve a binding to an OSC path/index (or null)
// ------------------------------------------------------------------------------------------------

function resolve(b) {
  if (!b) return null;
  switch (b.kind) {
    case 'sel': {
      const a = chAddr(b.p, S.sel);
      return a && { p: a.p, i: a.i, lo: b.lo, hi: b.hi, log: b.log, unit: b.unit };
    }
    case 'fixed': {
      const ch = fixedCh(b);
      if (ch >= 0) return fixedAddr(b, ch, b.p === 'mon_level' ? 'fader' : b.p);
      return { p: b.p, i: b.i, lo: b.lo, hi: b.hi, unit: b.unit };
    }
    case 'strip': {
      const ch = stripChannel(b.bank, b.slot);
      if (ch < 0) return null;
      const vk = vcaSlot(b.bank, ch);
      if (vk >= 0) {
        // the VCA layer drives OMC's desk-model VCA masters (docs/55 section 6): level, mute, solo;
        // the LCD select key spills the VCA into its area (ui_cmd 70 + VCA)
        if (b.select) return { p: 'ui_cmd', i: 1, ch, vca: vk };
        const vp = { fader: 'vca_level', ch_mute: 'vca_mute', ch_solo: 'vca_solo' }[b.p];
        return vp ? { p: vp, i: vk + 1, lo: b.lo, hi: b.hi, unit: b.unit, ch, vca: vk } : null;
      }
      if (b.p === 'fader' && S.sends && inputNo(ch) >= 0) {
        const s = chAddr(sendPath(S.sends), ch);   // inputs 33-40: mch_sendNN
        return { p: s.p, i: s.i, lo: -100, hi: 10, ch };
      }
      const a = chAddr(b.p, ch);
      return a && { p: a.p, i: a.i, lo: b.lo, hi: b.hi, log: b.log, unit: b.unit, ch };
    }
    case 'stripfn': {
      const ch = stripChannel(b.bank, b.slot);
      return ch < 0 ? null : { p: 'surface', i: b.i, lo: 0, hi: 1, ch };
    }
    case 'sendlvl': {
      const a = chAddr(sendPath(b.bus + (b.pw || 8) * S.sendPage), S.sel);   // pw: knobs per bank key (X32: 4)
      return a && { p: a.p, i: a.i, lo: b.lo, hi: b.hi, unit: 'dB' };
    }
    case 'dyn': {
      const d = b[S.dyn];
      const a = d && chAddr(d[0], S.sel);
      return a && { p: a.p, i: a.i, lo: d[1], hi: d[2], log: d[3] === 'log', unit: b.unit };
    }
    case 'band': {
      const a = chAddr(b.p + S.band, S.sel);
      return a && { p: a.p, i: a.i, lo: b.lo, hi: b.hi, log: b.log, unit: b.unit };
    }
    case 'qknob': case 'qkey': {
      // WING 4-channel section: the parameter its keys chose, on that strip's channel
      const ch = stripChannel(b.bank, b.slot), q = QUAD[S.qmode];
      const a = ch >= 0 && chAddr(b.kind === 'qknob' ? q.k : q.t, ch);
      return a ? { p: a.p, i: a.i, lo: q.lo, hi: q.hi, log: q.log, unit: q.unit, ch } : null;
    }
    case 'meter':
      return { p: b.p, i: b.i };
    case 'surface': {
      const ch = fixedCh(b);   // the monitor MUTE key of a monitor fader given a strip: that strip's mute
      if (ch >= 0) return fixedAddr(b, ch, 'ch_mute');
      return { p: 'surface', i: b.i, lo: 0, hi: 1 };
    }
    case 'cmd': case 'radio':
      return { p: b.p, i: b.i || 1 };
    case 'enc':
      return { p: 'enc', i: b.i, lo: 0, hi: 1 };
    case 'enckey':
      return { p: 'enc_key', i: b.i };
    case 'uenc':
      return { p: 'uenc', i: b.i, lo: 0, hi: 1 };
    case 'ukey':
      return { p: 'ukey', i: b.i };
    case 'cycle': {
      // a model input holds bell / low shelf / high shelf: OMC turns any other type into a bell
      const a = chAddr(b.p + S.band, S.sel);
      return a && { p: a.p, i: a.i, lo: 0, hi: b.n - 1 };
    }
    default:
      return null;
  }
}

// ------------------------------------------------------------------------------------------------
// link
// ------------------------------------------------------------------------------------------------

function send(op, p, i, v) {
  if (op === 'set') { S.values.set(key(p, i), v); refresh(); }
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ op, p, i, v }));
}

function connect() {
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  S.ws = ws;
  ws.onopen = () => {
    setStatus(true);
    watch();
    // this device's clock, for OMC's time-sync check (OMC #69)
    ws.send(JSON.stringify({ op: 'set', p: 'client_time', i: 1, v: String(Math.floor(Date.now() / 1000)) }));
  };
  ws.onclose = () => { setStatus(false); setTimeout(connect, 1500); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if ('omc' in m) setStatus(true, m.omc);
    if (m.vegas && typeof Vegas !== 'undefined') { Vegas.message(m.vegas); return; }   // Vegas mode (vegas.js, docs/45)
    if (!m.u) return;
    let rewatch = false, selMoved = false;
    for (const [p, i, v] of m.u) {
      const old = S.values.get(key(p, i));
      S.values.set(key(p, i), v);
      if (p === 'eq_band' && i === 1) {
        // the band under edit, shared with the touch UI (a touch on its EQ graph or band panel selects it)
        const b = Math.min(4, Math.max(1, Math.round(v) + 1));
        if (b !== S.band) { S.band = b; rewatch = true; }
      }
      // selected from elsewhere (touch UI, another page): the upper strip now shows that channel
      if ((p === 'sel' || p === 'msel') && i === 1) selMoved = true;
      // the touch UI changed the strips on the 'touch' layer (POP spill, bank)
      if (p === 'bank' && old !== v && (S.layer.L === 'touch' || S.layer.R === 'touch')) rewatch = true;
      if (p === 'fixfader' && old !== v) rewatch = true;
      // fader flip from the touch UI / the console's flip key (OMC sof = send target n; aux n = ch_sendNN for
      // n <= 16, matrices are not on this surface's send paths): the faders follow (docs/55 section 9)
      if (p === 'sof' && i === 1) {
        const b = Math.round(v);
        const n = b >= 1 && b <= 16 ? b : 0;
        if (n !== S.sends) { S.sends = n; if (n) S.lastSends = n; rewatch = true; }
      }
    }
    if (selMoved) {
      const s = selFromOmc();
      if (s !== S.sel) { S.sel = s; rewatch = true; }
    }
    if (rewatch) scheduleWatch();
    scheduleRefresh();
  };
}

// on: the bridge is connected; omc: OMC answers the bridge (false: nothing listens on its OSC port)
function setStatus(on, omc = true) {
  const s = document.getElementById('status');
  s.textContent = !on ? 'no link to OMC' : omc ? 'linked to OMC' : 'OMC not answering';
  s.className = 'status ' + (on && omc ? 'on' : 'off');
}

// a burst of feed updates (a bank of 16 strips) asks for one watch
let watchTimer = null;
function scheduleWatch() {
  clearTimeout(watchTimer);
  watchTimer = setTimeout(watch, 60);
}

// everything the visible surface shows: fetched once, then OMC pushes changes; meters are polled
function watch() {
  if (!S.ws || S.ws.readyState !== 1) return;
  const items = new Map(), poll = new Map();
  const add = (m, p, i) => m.set(key(p, i), [p, i]);
  add(items, 'sel', 1);
  add(items, 'msel', 1);
  add(items, 'eq_band', 1);
  for (const v of views) {
    const r = resolve(v.c.bind);
    if (!r) continue;
    if (v.c.type === 'meter') add(poll, r.p, r.i);
    else add(items, r.p, r.i);
    if (v.c.type === 'lcd' && r.ch !== undefined)
    {
      for (const p of ['ch_name', 'ch_mute', 'ch_color']) { const a = chAddr(p, r.ch); if (a) add(items, a.p, a.i); }
      const n = inputNo(r.ch);   // the wireless scribble text and alarm of a bound receiver (per input number)
      if (n >= 0) { add(items, 'wscrib', n + 1); add(items, 'wscrib_alert', n + 1); add(items, 'wbatt', n + 1); }
      if (n >= 0) { add(items, 'scr_l1', n + 1); add(items, 'scr_l2', n + 1); }   // the scribble designer's lines (docs/58 section 14)
      if (n >= 0) add(items, 'scr_bmp', n + 1);   // the 36 x 24 surface strip image (OMC surface-lcd36.h, W12d)
    }
  }
  for (let n = 0; n < INPUTS; n++) { const a = chAddr('ch_name', inputCh(n)); add(items, a.p, a.i); }
  // scribble overlays per input number (OMC ovl_text / ovl_style: the feedback detector's flash, docs/60)
  for (let n = 1; n <= INPUTS; n++) { add(items, 'ovl_text', n); add(items, 'ovl_style', n); }
  for (let k = 1; k <= 16; k++) add(items, 'bank', k);
  for (let k = 1; k <= 4; k++) add(items, 'bank_page', k);           // the touch bank's pages (W12p)
  for (let k = 1; k <= 8; k++) { add(items, 'vca_area', k); add(items, 'vca_user', k); add(items, 'vca_mute', k); }
  for (let k = 1; k <= 8; k++) { add(items, 'enc_pos', k); add(items, 'enc_lit', k); }
  // banks of user-defined keys / knobs (OMC user-keys.h): lamps, labels, the active bank, knob rings
  for (let k = 1; k <= 16; k++) add(items, 'ukey_lit', k);
  for (let k = 1; k <= 25; k++) add(items, 'ukey_label', k);
  for (let k = 1; k <= 8; k++) add(items, 'uenc_pos', k);
  add(items, 'ukey_bank', 1); add(items, 'ukey_bank', 2);
  // the fixed faders' strips (OMC assignables.h): a change re-resolves the masters / monitor controls
  for (let k = 1; k <= 8; k++) { add(items, 'fixfader', k); add(items, 'fixfader_label', k); }
  add(items, 'sof', 1);                                           // fader flip (docs/55 section 9)
  add(items, 'scr_style', 1);                                     // the scribble design's look (docs/58 section 14)
  if (S.sends) for (let n = 1; n <= INPUTS; n++) add(items, 'flip_pre', n);   // the flipped send pre / post per input
  S.ws.send(JSON.stringify({ op: 'watch', items: [...items.values()] }));
  S.ws.send(JSON.stringify({ op: 'poll', items: [...poll.values()] }));
}

// ------------------------------------------------------------------------------------------------
// laws
// ------------------------------------------------------------------------------------------------

// fader: the printed scale of the PRO1 fader (dB -> distance from the +10 mark, mm), cap at -inf
const FADER_SCALE = [[10, 0], [5, 13.0], [0, 24.5], [-5, 36.5], [-10, 48.5], [-20, 62.5], [-30, 73.5],
                     [-40, 83.5], [-50, 90.0], [-70, 95.0], [-100, 99.4]];
function faderT(db) {   // 0 (top) .. 1 (-inf)
  const s = FADER_SCALE, end = s[s.length - 1][1];
  if (db >= s[0][0]) return 0;
  for (let k = 1; k < s.length; k++)
    if (db >= s[k][0]) {
      const [d0, y0] = s[k - 1], [d1, y1] = s[k];
      return (y0 + (y1 - y0) * (db - d0) / (d1 - d0)) / end;
    }
  return 1;
}
function faderDb(t) {
  const s = FADER_SCALE, end = s[s.length - 1][1], y = clamp(t, 0, 1) * end;
  for (let k = 1; k < s.length; k++)
    if (y <= s[k][1]) {
      const [d0, y0] = s[k - 1], [d1, y1] = s[k];
      return d0 + (d1 - d0) * (y - y0) / (y1 - y0);
    }
  return -100;
}
const toPos = (v, r) => (r.log ? Math.log(v / r.lo) / Math.log(r.hi / r.lo) : (v - r.lo) / (r.hi - r.lo));
const fromPos = (p, r) => (r.log ? r.lo * Math.pow(r.hi / r.lo, clamp(p, 0, 1)) : r.lo + clamp(p, 0, 1) * (r.hi - r.lo));

function fmt(v, r) {
  if (typeof v === 'string') return v;
  if (r && r.unit === 'Hz') return v >= 1000 ? (v / 1000).toFixed(2) + ' kHz' : v.toFixed(0) + ' Hz';
  if (r && (r.p === 'fader' || r.p === 'mch_fader') || r && /send/.test(r.p)) return v <= -99.9 ? '-inf dB' : v.toFixed(1) + ' dB';
  return (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) + (r && r.unit ? ' ' + r.unit : '');
}

// ------------------------------------------------------------------------------------------------
// drawing helpers
// ------------------------------------------------------------------------------------------------

function el(name, attrs, parent) {
  const e = document.createElementNS(NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}

const LIGHT = {
  ch_mute: '#ff3b2f', ch_solo: '#ffd21a', ch_phantom: '#ff3b2f', ch_phase: '#4fb3ff', solo_clear: '#ffd21a',
  ch_comp_on: '#3ddc4a', ch_gate_on: '#3ddc4a', ch_eq_on: '#3ddc4a', ch_hpf_on: '#3ddc4a',
};
// full-colour finish (PRO1 photographs): unlit cap / lit cap per key colour, knob cap colours, and the
// RGB backlight of the channel LCD keys per OMC channel colour (black red green yellow blue pink cyan white)
const PALETTE = {
  red:    ['#8a2c33', '#ff4b4b'], green:  ['#2d5e40', '#5dff8a'], yellow: ['#9c8420', '#ffe44d'],
  blue:   ['#2c5285', '#5cabff'], violet: ['#3f4080', '#a99cff'], amber:  ['#9a6114', '#ffb53d'],
  grey:   ['#5c6169', '#dfe3ea'], light:  ['#b8c2c0', '#ffffff'], dark:   ['#2f3338', '#9aa0aa'],
  lilac:  ['#5f6b86', '#5b9bff'], purple: ['#5d5895', '#b0a4ff'],
};
const KNOB_CAP = { grey: '#4e5259', green: '#2f6e4f', violet: '#3d4290', red: '#9a3a3a', cyan: '#4a90c0', orange: '#c8642a' };
// wireless scribble alarms (OMC wscrib_alert, docs/58 section 11): TX off, RF dropout, low battery, interference
const SCRIBBLE_ALERT = [null, ['TX OFF', '#6e7380'], ['RF DROPOUT', '#d8322b'], ['LOW BATT', '#f08c1a'], ['INTERFERENCE', '#c04ad0']];
// the horizontal transmitter battery on a wireless strip's LCD (OMC wbatt: -2 none, -1 unknown, 0..100 %, 101 charging;
// battery-level.h, docs/58 section 12): 5 segments, lit = ceil(pct / 20), semantic level colours
const BATT_LEVEL = ['#F05A5A', '#F68B2C', '#FFB400', '#CFC722', '#9ED83A'];
function addBattery(g, x, y, w, h) {
  const nw = w * 0.09, bw = w - nw, b = el('g', { 'pointer-events': 'none' }, g);
  const body = el('rect', { x, y, width: bw, height: h, rx: 0.35, fill: 'none', 'stroke-width': 0.3 }, b);
  const nub = el('rect', { x: x + bw, y: y + h * 0.28, width: nw, height: h * 0.44 }, b);
  const segs = [], pad = 0.45, sw = (bw - 2 * pad - 4 * 0.25) / 5;
  for (let k = 0; k < 5; k++) segs.push(el('rect', { x: x + pad + k * (sw + 0.25), y: y + pad, width: sw, height: h - 2 * pad }, b));
  const bolt = el('polyline', { points: [[0.58, 0.12], [0.36, 0.55], [0.6, 0.45], [0.4, 0.88]].map(([u, v]) => `${x + u * bw},${y + v * h}`).join(' '),
                                fill: 'none', stroke: '#F05A5A', 'stroke-width': 0.35, 'stroke-linejoin': 'round' }, b);
  return (code, dark) => {
    b.style.display = code <= -2 ? 'none' : '';
    if (code <= -2) return;
    const edge = dark ? '#ffffff' : '#1B2550';
    body.setAttribute('stroke', edge); nub.setAttribute('fill', edge);
    const known = code >= 0 && code <= 100, lit = known && code > 0 ? Math.min(5, Math.ceil(code / 20)) : 0;
    segs.forEach((r, k) => {
      r.style.display = known ? '' : 'none';
      r.setAttribute('fill', k < lit ? BATT_LEVEL[lit - 1] : (dark ? '#3D4A63' : '#D9D4F0'));
    });
    bolt.style.display = code >= 101 ? '' : 'none';
  };
}
const LCD_RGB = ['#2a2d31', '#e2483b', '#7be05a', '#e6e83a', '#4a7df0', '#d06ad8', '#61d6e6', '#e8eef0'];
let colourTheme = false;
const themed = (c) => colourTheme && c.tint;

function lightColour(c) {
  const b = c.bind;
  if (!b) return '#f0a020';
  if (b.p && LIGHT[b.p]) return LIGHT[b.p];
  if (b.kind === 'sends' || b.kind === 'layer' || b.kind === 'mode') return '#4fb3ff';
  return '#3ddc4a';
}

// ------------------------------------------------------------------------------------------------
// controls
// ------------------------------------------------------------------------------------------------

function isOn(c) {
  const b = c.bind;
  if (!b) return !!S.local.get(c.id);
  switch (b.kind) {
    case 'mode':
      return b.mode === 'dyn' ? S.dyn === b.value : false;
    case 'sends':
      return b.bus === 0 ? false : S.sends === b.bus + (b.page ? 8 * S.sendPage : 0);
    case 'layer':
      return S.layer[bankOf(b.bank)[0]] === b.value;
    case 'bay': {
      // EXTEND lights while it is on; ALIGN while the right bank continues the left (and EXTEND is off)
      if (b.value === 'extend') return !!S.extend;
      if (!EXT || S.extend) return false;
      const [a, t] = EXT;
      if (S.layer[t] !== S.layer[a]) return false;
      const next = (S.page[a] + 1) % pagesOf(a);
      return BANKS[a].slots === BANKS[t].slots ? S.page[t] === next && S.base[t] === undefined : S.base[t] === next * BANKS[a].slots;
    }
    case 'stripfn':
      return stripChannel(b.bank, b.slot) === S.sel && stripChannel(b.bank, b.slot) >= 0 && val('surface', b.i, 0) >= 0.5;
    case 'flip':
      return !!S.sends;
    case 'enckey':   // lit when OMC says so (SQ1D panel: the unit the encoders drive)
      return val('enc_lit', b.i, 0) >= 0.5;
    case 'ukey':     // a user key: its action is on (talkback, isolate ...)
      return val('ukey_lit', b.i, 0) >= 0.5;
    case 'ukbank':   // X32 SET A / B / C: lit while its bank is the active one
      return Math.round(val('ukey_bank', 1, 1)) === b.value;
    case 'sendpage':   // an absolute bank key (X32 1-4 / 5-8 ...) lights while its bank is on the knobs
      return b.value !== undefined && S.sendPage === b.value;
    case 'bandsel':
      return S.band === b.value;
    case 'qmode':
      return S.qmode === b.value;
    case 'scroll': case 'selstep': case 'cycle': case 'cmd': case 'stripcmd': case 'keypad':
      return false;
    case 'radio': {
      const ch = fixedCh(b);   // a master's select key given a strip: lit while that strip is selected
      if (ch >= 0) return ch < VCA_CH && ch === S.sel;
      return Math.round(val(b.p, b.i, -1)) === b.value;
    }
    default: {
      const r = resolve(b);
      if (!r) return false;
      if (b.select) return r.vca === undefined && r.ch === S.sel;
      return val(r.p, r.i) >= 0.5;
    }
  }
}

function press(c) {
  const b = c.bind;
  if (!b) { S.local.set(c.id, !S.local.get(c.id)); refresh(); return; }
  switch (b.kind) {
    case 'mode':
      if (b.mode === 'dyn') S.dyn = b.value;
      else {
        S.band = clamp(S.band + (b.value === 'up' ? 1 : -1), 1, 4);
        send('set', 'eq_band', 1, S.band - 1);   // the touch UI follows (OMC SURFACE_EQ_BAND)
      }
      break;
    case 'sends': {
      const bus = b.bus && b.page ? b.bus + 8 * S.sendPage : b.bus;
      S.sends = (bus === 0 || S.sends === bus) ? 0 : bus;
      if (S.sends) S.lastSends = S.sends;
      send('set', 'sof', 1, S.sends);   // the console's fader flip follows (docs/55 section 9)
      info(S.sends ? `AUX ${S.sends} sends on faders` : 'faders');
      break;
    }
    case 'sendpage':
      if (b.value !== undefined) { S.sendPage = b.value; info(b.what || ''); break; }
      S.sendPage = b.step > 0 ? 1 : 0;
      info(`mix sends ${S.sendPage ? '9-16' : '1-8'}`);
      break;
    case 'qmode':
      S.qmode = b.value;
      info(b.what || '');
      break;
    case 'bandsel':   // an EQ band key (X32 / M32 / WING: LOW .. HIGH): the EQ knobs edit that band
      S.band = b.value;
      send('set', 'eq_band', 1, S.band - 1);   // the touch UI follows (OMC SURFACE_EQ_BAND)
      info(b.what || '');
      break;
    case 'flip':
      S.sends = S.sends ? 0 : S.lastSends;
      send('set', 'sof', 1, S.sends);
      info(S.sends ? `AUX ${S.sends} sends on faders` : 'faders');
      break;
    case 'layer': {
      const bank = bankOf(b.bank)[0];
      if (EXT && bank === EXT[1]) extendOff();  // the right bank chosen by hand
      S.layer[bank] = b.value; S.page[bank] = 0; delete S.base[bank];
      extendFollow();                           // INPUT / OUTPUT with EXTEND on: the right bank follows
      break;
    }
    case 'bay': {
      if (!EXT) { info('this bank layout has no EXTEND / ALIGN'); break; }
      const [a, t] = EXT;
      if (b.value === 'extend') {
        // EXTEND toggles: on, the right bank shows the next eight after the left and the Scroll keys
        // of either bank move both; off, the right bank goes back to its layer and page
        if (S.extend) {
          S.layer[t] = S.extend.layer; S.page[t] = S.extend.page; S.extend = null;
          info('EXTEND off');
        } else {
          S.extend = { layer: S.layer[t], page: S.page[t] };
          extendFollow();
          info(b.what);
        }
      } else {
        // ALIGN: the right bank carries on from the left (next eight), once
        extendOff();
        S.layer[t] = S.layer[a];
        const next = (S.page[a] + 1) % pagesOf(a);
        if (BANKS[a].slots === BANKS[t].slots) { S.page[t] = next; delete S.base[t]; }
        else { S.page[t] = 0; S.base[t] = next * BANKS[a].slots; }
        info(b.what);
      }
      break;
    }
    case 'scroll': {
      if (S.extend) {
        // EXTEND: both banks move together, the right one stays the left + 1
        const a = EXT[0], n = pagesOf(a);
        S.page[a] = (S.page[a] + b.step + n) % n;
        extendFollow();
        break;
      }
      const bank = bankOf(b.bank)[0], n = pagesOf(bank);
      if (S.layer[bank] === 'touch') {
        // the touch UI's bank (bank, POP spill): OMC pages it, 16 faders at a time (ui_cmd 90 / 91, W12p)
        send('set', 'ui_cmd', 1, b.step < 0 ? 90 : 91);
        const p = Math.round(val('bank_page', 1, 0)), ps = Math.round(val('bank_page', 2, 0));
        info(ps > 1 ? `touch bank page ${Math.min(ps, Math.max(1, p + b.step))}/${ps}` : 'touch bank: one page');
        break;
      }
      if (S.base[bank] !== undefined) { S.page[bank] = Math.floor(S.base[bank] / BANKS[bank].slots); delete S.base[bank]; }
      S.page[bank] = (S.page[bank] + b.step + n) % n;
      break;
    }
    case 'keypad': {
      // channel select keypad: digits, * clears, ENTER selects input n and pages its bay to it
      if (b.key === '*') S.keypad = '';
      else if (b.key !== 'E') S.keypad = (S.keypad + b.key).slice(-3);
      else {
        const n = parseInt(S.keypad, 10);
        S.keypad = '';
        if (n >= 1 && n <= INPUTS) {
          const bank = bankOf(b.bank)[0];
          if (EXT && bank === EXT[1]) extendOff();
          S.layer[bank] = 'input'; S.page[bank] = Math.floor((n - 1) / BANKS[bank].slots); delete S.base[bank];
          extendFollow();
          select(inputCh(n - 1), true);
          return;
        }
      }
      info(S.keypad ? 'channel ' + S.keypad : 'channel select');
      return;
    }
    case 'stripcmd': {
      // a section key of a strip: that channel is selected and the touch UI opens the section
      const ch = stripChannel(b.bank, b.slot);
      if (ch < 0) return;
      select(ch);
      if (b.band) { S.band = b.band; send('set', 'eq_band', 1, b.band - 1); }
      send('set', 'ui_cmd', 1, b.value);
      info(chName(ch) + ': ' + (b.what || ''));
      return;
    }
    case 'stripfn': {
      // a strip key whose function the touch UI holds for the selected strip: select it, then toggle
      const ch = stripChannel(b.bank, b.slot);
      if (ch < 0) return;
      const on = isOn(c);
      if (ch !== S.sel) select(ch);
      send('set', 'surface', b.i, on ? 0 : 1);
      info(chName(ch) + ': ' + (b.what || ''));
      return;
    }
    case 'selstep':
      select(selStep(S.sel, b.step));
      return;
    case 'cmd':
      send('set', b.p, 1, b.value);
      if (b.touch) {
        extendOff();
        for (const [k, d] of Object.entries(BANKS)) if (d.touch) { S.layer[k] = 'touch'; S.page[k] = 0; delete S.base[k]; }
        watch(); refresh();
      }
      info(b.what || '');
      return;
    case 'enckey':
      send('set', 'enc_key', b.i, 1);
      info(b.what || '');
      return;
    case 'ukey':
      send('set', 'ukey', b.i, 1);
      info(describe(c));
      return;
    case 'ukbank':
      send('set', 'ukey_bank', 1, b.value);
      info(b.what || '');
      return;
    case 'ukstep':
      send('set', 'ukey_step', 1, b.value);
      info(b.what || '');
      return;
    case 'radio': {
      const ch = fixedCh(b);
      if (ch >= VCA_CH) { send('set', 'ui_cmd', 1, 70 + ch - VCA_CH); info(chName(ch)); return; }   // a VCA: spill it
      if (ch >= 0) { select(ch); info(chName(ch)); return; }
      send('set', b.p, b.i, b.value);
      info(b.what || '');
      return;
    }
    case 'cycle': {
      const r = resolve(b);
      if (!r) return;
      const v = (Math.round(val(r.p, r.i, 0)) + 1) % b.n;
      send('set', r.p, r.i, v);
      info(`EQ band ${S.band} type ${v}`);
      return;
    }
    default: {
      const r = resolve(b);
      if (!r) return;
      if (b.select && r.vca !== undefined) {
        // VCA spill: the bank of the VCA's area (A = left, B = right) follows the touch UI's bank
        send('set', 'ui_cmd', 1, 70 + r.vca);
        const bank = val('vca_area', r.vca + 1, 0) >= 0.5 ? 'R' : 'L';
        if (BANKS[bank]) { extendOff(); S.layer[bank] = 'touch'; S.page[bank] = 0; delete S.base[bank]; }
        info(`VCA ${r.vca + 1}: spill to area ${bank === 'R' ? 'B' : 'A'}`);
        break;
      }
      if (b.select) { select(r.ch, true); return; }
      send('set', r.p, r.i, isOn(c) ? 0 : 1);
      return;
    }
  }
  watch();
  refresh();
}

function select(ch, press = false) {
  S.sel = ch;
  if (ch >= MODEL) send('set', 'msel', 1, ch - MODEL + 1);   // a desk-model input (33-40)
  else {
    // back from a model input: msel 0 first, so the touch UI follows even if OMC's sel is unchanged
    if (val('msel', 1, 0) >= 1) send('set', 'msel', 1, 0);
    send('set', 'sel', 1, ch);
  }
  // an LCD-select key is a press, not only a value: the touch UI opens / follows the channel (docs/26)
  if (press) send('set', 'ui_cmd', 1, 60);
  info('selected ' + chName(ch) + ' ' + (chVal('ch_name', ch, '') || ''));
  watch();
  refresh();
}

function info(t) { document.getElementById('info').textContent = t; }

function addButton(c, g) {
  const x = c.x - c.w / 2, y = c.y - c.h / 2;
  if (c.type === 'round') {
    var face = el('circle', { cx: c.x, cy: c.y, r: c.w / 2, class: 'face' }, g);
    var glow = el('circle', { cx: c.x, cy: c.y, r: c.w / 2 - 0.9, class: 'glow' }, g);
  } else if (c.type === 'arrow') {
    const d = c.dir, hw = c.w / 2 - 0.6, hh = c.h / 2 - 0.6, X = c.x, Y = c.y;
    const pts = d === 'left' ? [[X - hw, Y], [X + hw, Y - hh], [X + hw, Y + hh]]
      : d === 'right' ? [[X + hw, Y], [X - hw, Y - hh], [X - hw, Y + hh]]
      : d === 'up' ? [[X, Y - hh], [X - hw, Y + hh], [X + hw, Y + hh]]
      : [[X, Y + hh], [X - hw, Y - hh], [X + hw, Y - hh]];
    var face = el('polygon', { points: pts.map(p => p.join(',')).join(' '), class: 'face' }, g);
    var glow = el('polygon', { points: pts.map(p => p.join(',')).join(' '), class: 'glow', transform: `translate(${X} ${Y}) scale(0.6) translate(${-X} ${-Y})` }, g);
  } else {
    var face = el('rect', { x, y, width: c.w, height: c.h, rx: 0.8, class: 'face' }, g);
    if (c.type === 'ledbutton') {
      el('rect', { x: x + c.w - 2.6, y: y + 1.0, width: 1.4, height: c.h - 2.0, rx: 0.5, class: 'slot' }, g);
      var glow = el('rect', { x: x + c.w - 2.45, y: y + 1.15, width: 1.1, height: c.h - 2.3, rx: 0.45, class: 'glow' }, g);
    } else {
      var glow = el('rect', { x: x + 0.9, y: y + 0.9, width: c.w - 1.8, height: c.h - 1.8, rx: 0.5, class: 'glow', opacity: 0.85 }, g);
    }
  }
  const colour = lightColour(c);
  const momentary = c.bind && ['scroll', 'selstep', 'cycle', 'cmd', 'enckey', 'ukey', 'ukbank', 'ukstep', 'stripcmd', 'keypad', 'sendpage'].includes(c.bind.kind) || (c.bind && c.bind.kind === 'mode' && c.bind.mode === 'band');
  g.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    g.classList.add('pressed');
    if (momentary) glow.style.fill = themed(c) ? (PALETTE[c.tint] || PALETTE.grey)[1] : colour;
    press(c);
  });
  const up = () => { g.classList.remove('pressed'); if (momentary) refresh(); };
  g.addEventListener('pointerup', up);
  g.addEventListener('pointerleave', up);
  return () => {
    const on = isOn(c);
    if (themed(c)) {
      // full colour: the key is a translucent coloured cap that lights up
      const [off, lit] = PALETTE[c.tint] || PALETTE.grey;
      face.style.fill = on ? lit : off;
      glow.style.fill = on ? lit : 'transparent';
    } else {
      face.style.fill = '';
      glow.style.fill = on ? colour : 'transparent';
    }
  };
}

// ------------------------------------------------------------------------------------------------
// the 36 x 24 surface strip (OMC scr_bmp, surface-lcd36.h, PLAN W12d): OMC's own strip layout as the real strips on
// the XL8 / PRO1 / PRO2 / PRO3/6/9 / PRO X would show it (about 1:1 there). The frame: 12 row pairs x 9 bytes; for rows
// A = 2k and B = 2k + 1, the dots B0..B35 then A0..A35 are an MSB-first bit stream stored byte-reversed. The "dots"
// header key shows it on every input strip LCD in place of the text lines.
// ------------------------------------------------------------------------------------------------

let lcdDots = false;
/// the frame in base64 (144 characters, OSC scr_bmp) -> 24 rows of 36 booleans (null when it is not a frame)
function lcd36Decode(text) {
  if (typeof text !== 'string' || text.length !== 144 || /[^A-Za-z0-9+/]/.test(text)) return null;
  let bin;
  try { bin = atob(text); } catch (e) { return null; }
  if (bin.length !== 108) return null;
  const rows = [];
  for (let y = 0; y < 24; y++) rows.push(new Array(36).fill(false));
  for (let k = 0; k < 12; k++) {
    const s = [];
    for (let i = 0; i < 9; i++) s[8 - i] = bin.charCodeAt(k * 9 + i);
    for (let i = 0; i < 72; i++) {
      if (!(s[i >> 3] & (0x80 >> (i & 7)))) continue;
      if (i < 36) rows[2 * k + 1][i] = true; else rows[2 * k][i - 36] = true;
    }
  }
  return rows;
}
const lcd36Cache = new Map();   // frame + ink -> data URL
function lcd36Url(text, ink) {
  const k = text + ink;
  if (lcd36Cache.has(k)) return lcd36Cache.get(k);
  const rows = lcd36Decode(text);
  if (!rows) return null;
  const cv = document.createElement('canvas');
  cv.width = 36 * 4; cv.height = 24 * 4;
  const cx = cv.getContext('2d');
  for (let y = 0; y < 24; y++)
    for (let x = 0; x < 36; x++) {
      cx.fillStyle = ink;
      cx.globalAlpha = rows[y][x] ? 1 : 0.08;
      cx.fillRect(x * 4, y * 4, 3, 3);          // a dot with a one-pixel gap: the glass's grid
    }
  const url = cv.toDataURL('image/png');
  if (lcd36Cache.size > 400) lcd36Cache.clear();
  lcd36Cache.set(k, url);
  return url;
}

function addLcd(c, g) {
  const x = c.x - c.w / 2, y = c.y - c.h / 2;
  el('rect', { x: x - 1.5, y: y - 3, width: c.w + 3, height: c.h + 6, rx: 0.6, fill: '#1a1b1f', stroke: '#0a0a0c', 'stroke-width': 0.3 }, g);
  const lcdFace = el('rect', { x, y, width: c.w, height: c.h, rx: 1.2, class: 'face' }, g);
  const t1 = el('text', { x: c.x, y: y + 4.3, 'font-size': 3.1, 'text-anchor': 'middle' }, g);
  const t2 = el('text', { x: c.x, y: y + 9.4, 'font-size': 3.3, 'text-anchor': 'middle' }, g);
  const t3 = el('text', { x: c.x, y: y + 14.0, 'font-size': 2.4, 'text-anchor': 'middle' }, g);
  const batt = addBattery(g, x + c.w - 6.6, y + 1.0, 5.8, 2.7);   // top-right; the top line moves left while it shows
  // the scribble designer's BAR style (docs/58 section 14): a channel-colour bar at the left edge, hidden otherwise
  const bar = el('rect', { x: x + 0.3, y: y + 0.6, width: 1.1, height: c.h - 1.2, rx: 0.3, 'pointer-events': 'none' }, g);
  bar.style.display = 'none';
  // the dot image (36 x 24, 3:2): as large as the face allows, centred
  const dw = Math.min(c.w - 1.6, (c.h - 1.2) * 1.5), dh = dw / 1.5;
  const dots = el('image', { x: c.x - dw / 2, y: y + (c.h - dh) / 2, width: dw, height: dh, preserveAspectRatio: 'none', 'pointer-events': 'none' }, g);
  dots.style.imageRendering = 'pixelated';
  dots.style.display = 'none';
  const t1Mid = () => { t1.setAttribute('x', c.x); t1.setAttribute('text-anchor', 'middle'); };
  g.addEventListener('pointerdown', (e) => { e.preventDefault(); press(c); });
  return () => {
    batt(-2); t1Mid(); bar.style.display = 'none'; t1.style.fill = t2.style.fill = '';
    dots.style.display = 'none'; t1.style.display = t2.style.display = t3.style.display = '';
    const b = c.bind || { kind: 'none' };   // an unbound LCD key (PRO X) latches like any key
    if (b.kind !== 'strip') {
      // DCA spill / surface keys: caption and state from OMC
      const on = isOn(c);
      lcdFace.style.fill = colourTheme ? (on ? '#ffd23d' : '#8fa3b8') : '';
      const fch = fixedCh(b);   // a master's select LCD given a strip: its name (OMC fixfader_label)
      t1.textContent = (fch >= 0 ? val('fixfader_label', b.fx + 1, '') || chName(fch) : b.caption) || c.label || ''; t2.textContent = on ? (b.p && b.p.startsWith('dca_spill') ? 'SPILL' : 'ON') : ''; t3.textContent = '';
      g.classList.toggle('sel', on);
      return;
    }
    const ch = stripChannel(b.bank, b.slot);
    const vk = vcaSlot(b.bank, ch);
    if (vk >= 0) {
      // a desk-model VCA master: its number, area and user mode, mute
      lcdFace.style.fill = colourTheme ? '#8fa3b8' : '';
      lcdFace.style.opacity = '';
      t1.textContent = 'VCA ' + (vk + 1);
      t2.textContent = 'AREA ' + (val('vca_area', vk + 1, 0) >= 0.5 ? 'B' : 'A') + (val('vca_user', vk + 1, 0) >= 0.5 ? ' U' : '');
      t3.textContent = val('vca_mute', vk + 1, 0) >= 0.5 ? 'MUTE' : '';
      g.classList.remove('sel');
      return;
    }
    // full colour: RGB backlight in the channel's colour (OMC ch_color), dimmed when not selected
    lcdFace.style.fill = colourTheme && ch >= 0 ? LCD_RGB[Math.round(chVal('ch_color', ch, 3)) & 7] : '';
    lcdFace.style.opacity = colourTheme && ch >= 0 && ch !== S.sel ? 0.82 : '';
    t1.textContent = chName(ch);
    t2.textContent = ch >= 0 ? String(chVal('ch_name', ch, '')).slice(0, 8) : '';
    if (ch >= 0 && S.sends && inputNo(ch) >= 0) {
      const v = chVal(sendPath(S.sends), ch, -100);
      t3.textContent = 'A' + S.sends + ' ' + (v <= -99.9 ? '-inf' : v.toFixed(1)) + (val('flip_pre', inputNo(ch) + 1, 0) >= 0.5 ? ' PRE' : '');
    } else t3.textContent = ch >= 0 ? (chVal('ch_mute', ch, 0) >= 0.5 ? 'MUTE' : '') : '';
    // the scribble designer (OMC scr_style / scr_l1 / scr_l2, docs/58 section 14): the designed lines replace the top two lines;
    // style = 1 + colour mode (0 fill, 1 bar, 2 inverse) + 4 when the battery is placed; 0 = the default look
    const wn = inputNo(ch);
    const ds = wn >= 0 ? Math.round(val('scr_style', 1, 0)) : 0;
    if (ds > 0) {
      t1.textContent = String(val('scr_l1', wn + 1, '') || '').slice(0, 14);
      t2.textContent = String(val('scr_l2', wn + 1, '') || '').slice(0, 14);
      const mode = (ds - 1) & 3, rgb = LCD_RGB[Math.round(chVal('ch_color', ch, 3)) & 7];
      if (mode === 1) { bar.style.display = ''; bar.setAttribute('fill', rgb); }
      if (mode >= 1 && colourTheme) { lcdFace.style.fill = ''; lcdFace.style.opacity = ''; }
      if (mode === 2) t1.style.fill = t2.style.fill = rgb;
    }
    // a wireless channel: the scribble text on the bottom line (MUTE keeps priority); an alarm colours the
    // backlight and names itself (docs/58 section 11)
    if (wn >= 0 && !(S.sends && wn >= 0)) {
      const txt = String(val('wscrib', wn + 1, '') || '');
      const al = SCRIBBLE_ALERT[Math.round(val('wscrib_alert', wn + 1, 0))] || null;
      if (al) { lcdFace.style.fill = al[1]; lcdFace.style.opacity = ''; bar.style.display = 'none'; t1.style.fill = t2.style.fill = ''; }
      if (t3.textContent !== 'MUTE' && !(ds > 0 && !al)) t3.textContent = (al ? al[0] : txt).slice(0, 14);   // a design places the wireless items itself
      const bc = ds > 0 && !(ds & 4) ? -2 : Math.round(val('wbatt', wn + 1, -2));
      batt(bc, !colourTheme || !!al);
      if (bc > -2) { t1.setAttribute('x', x + 1.0); t1.setAttribute('text-anchor', 'start'); }
    }
    // a scribble overlay (OMC ovl_text / ovl_style = 1 + palette index + 8 when flashing; scribble-overlay.h) is
    // above the wireless display: the feedback detector's "FB 2.5k" on the top line, the backlight in its colour,
    // alternating with the channel's own look at 4 Hz when it flashes (docs/60)
    const ov = ch >= 0 ? ovlLook(inputNo(ch)) : null;
    if (ov) {
      lcdFace.style.fill = LCD_RGB[ov.pal]; lcdFace.style.opacity = '';
      bar.style.display = 'none'; t1.style.fill = t2.style.fill = '';   // an overlay wins over the designed colours (docs/58 section 14)
      if (ov.text) t1.textContent = ov.text.slice(0, 12);
    }
    // the 36 x 24 surface strip (W12d) in place of the text lines and the battery, in the LCD's ink colour
    if (lcdDots && wn >= 0 && !(S.sends && wn >= 0)) {
      const url = lcd36Url(String(val('scr_bmp', wn + 1, '') || ''), getComputedStyle(t1).fill || '#9fd0ff');
      if (url) {
        dots.setAttribute('href', url);
        dots.style.display = '';
        t1.style.display = t2.style.display = t3.style.display = 'none';
        batt(-2);
      }
    }
    g.classList.toggle('sel', ch >= 0 && ch === S.sel);
  };
}

function dragValue(g, c, onDelta, onStart) {
  let last = null;
  g.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    g.setPointerCapture(e.pointerId);
    last = e.clientY;
    if (onStart) onStart(e);
  });
  g.addEventListener('pointermove', (e) => {
    if (last === null) return;
    const dy = last - e.clientY;
    last = e.clientY;
    onDelta(dy, e);
  });
  const end = () => { last = null; };
  g.addEventListener('pointerup', end);
  g.addEventListener('pointercancel', end);
  g.addEventListener('wheel', (e) => { e.preventDefault(); onDelta(-e.deltaY / 4, e); }, { passive: false });
}

function addKnob(c, g) {
  const R = c.w / 2, cap = (c.cap || c.w / 1.55) / 2;
  const pot = c.type === 'pot';
  const arc = el('path', { class: 'arc' }, g);
  let capFace, ptr, fin;
  if (!pot) {
    // round knob (reference 3): black body with a knurled skirt, coloured cap top (full colour),
    // white pointer line
    el('circle', { cx: c.x, cy: c.y, r: R * 0.93, fill: 'url(#knobbody)', stroke: '#000', 'stroke-width': 0.3 }, g);
    el('circle', { cx: c.x, cy: c.y, r: R * 0.80, fill: 'none', stroke: '#8d9097', 'stroke-width': R * 0.12,
                   'stroke-dasharray': `${(R * 0.16).toFixed(2)} ${(R * 0.16).toFixed(2)}`, opacity: 0.55 }, g);
    capFace = el('circle', { cx: c.x, cy: c.y, r: cap, class: 'capface' }, g);
    el('ellipse', { cx: c.x - cap * 0.25, cy: c.y - cap * 0.35, rx: cap * 0.55, ry: cap * 0.3, fill: '#ffffff', opacity: 0.12 }, g);
    ptr = el('line', { class: 'pointer' }, g);
  } else {
    // pointer pot (references 1 and 2): round body with a fin pointer across it
    capFace = el('circle', { cx: c.x, cy: c.y, r: R * 0.78, class: 'potbody' }, g);
    el('ellipse', { cx: c.x - R * 0.2, cy: c.y - R * 0.3, rx: R * 0.45, ry: R * 0.25, fill: '#ffffff', opacity: 0.1 }, g);
    fin = el('g', {}, g);
    el('rect', { x: c.x - R * 0.13, y: c.y - R * 0.86, width: R * 0.26, height: R * 1.15, rx: R * 0.12, class: 'potfin' }, fin);
    el('line', { x1: c.x, y1: c.y - R * 0.8, x2: c.x, y2: c.y - R * 0.45, stroke: '#1a1a1a', 'stroke-width': 0.35, 'stroke-linecap': 'round' }, fin);
  }
  g.classList.add('knob');
  let local = 0.5;
  const enc = c.bind && (c.bind.kind === 'enc' || c.bind.kind === 'uenc');   // relative: page encoders / user knobs
  const encP = c.bind && c.bind.kind === 'uenc' ? 'uenc' : 'enc';
  const selKnob = c.bind && c.bind.kind === 'selknob';   // X32 RACK channel select: steps the selection
  let encAcc = 0;
  const pos = () => {
    if (enc) return clamp(val(encP + '_pos', c.bind.i, 0), 0, 1);
    const r = resolve(c.bind);
    if (!r) return local;
    return clamp(toPos(val(r.p, r.i, r.lo), r), 0, 1);
  };
  dragValue(g, c, (dy, e) => {
    if (selKnob) {
      encAcc += dy * 0.08;
      const steps = Math.trunc(encAcc);
      if (steps) { encAcc -= steps; local = (local + 0.05 * steps + 1) % 1; select(selStep(S.sel, Math.sign(steps))); }
      return;
    }
    if (enc) {
      // relative encoder: whole steps (1 step = 1 % of the focused knob)
      encAcc += dy * (e.shiftKey ? 0.15 : 0.6);
      const steps = Math.trunc(encAcc);
      if (steps) { encAcc -= steps; send('change', encP, c.bind.i, steps); }
      return;
    }
    const r = resolve(c.bind);
    const step = (e.shiftKey ? 0.0015 : 0.006) * dy;
    if (!r) { local = clamp(local + step, 0, 1); refresh(); return; }
    const v = fromPos(pos() + step, r);
    send('set', r.p, r.i, v);
    tip(c, fmt(v, r));
  });
  g.addEventListener('dblclick', () => {
    const r = resolve(c.bind);
    if (r && /ch_pan|_g\d|ch_gain/.test(r.p)) send('set', r.p, r.i, 0);
  });
  return () => {
    const p = pos(), a = (-135 + 270 * p) * Math.PI / 180;
    if (!pot) {
      capFace.style.fill = themed(c) ? (KNOB_CAP[c.tint] || KNOB_CAP.grey) : '';
      const r0 = cap * 0.25, r1 = cap * 0.95;
      ptr.setAttribute('x1', c.x + r0 * Math.sin(a)); ptr.setAttribute('y1', c.y - r0 * Math.cos(a));
      ptr.setAttribute('x2', c.x + r1 * Math.sin(a)); ptr.setAttribute('y2', c.y - r1 * Math.cos(a));
    } else {
      capFace.style.fill = colourTheme ? '#c8b48a' : '';
      fin.setAttribute('transform', `rotate(${(-135 + 270 * p).toFixed(1)} ${c.x} ${c.y})`);
    }
    const ra = R * 0.99, a0 = -135 * Math.PI / 180;
    if (c.bind && p > 0.002) {
      const large = (a - a0) > Math.PI ? 1 : 0;
      arc.setAttribute('d', `M ${c.x + ra * Math.sin(a0)} ${c.y - ra * Math.cos(a0)} A ${ra} ${ra} 0 ${large} 1 ${c.x + ra * Math.sin(a)} ${c.y - ra * Math.cos(a)}`);
    } else arc.setAttribute('d', '');
  };
}

// fader cap colour by what the fader controls (touch UI v2 colour code): white mono input, blue
// stereo input / returns, green pre-fade aux, yellow post-fade aux, orange group / DCA, red main,
// grey matrix. OMC vchannels: inputs 0-31, aux returns 32-47, buses 48-63 (12 pre + 4 post),
// matrix 64-69, mono 71, DCA 72-79, main 80.
function capColour(c) {
  const r = resolve(c.bind);
  if (!r) return '#9aa0a6';
  if (r.p === 'mon_level') return '#e8ecef';
  let ch = r.ch !== undefined ? r.ch : (r.i - 1);
  const sm = /^m?ch_send(\d+)$/.exec(r.p);
  if (sm) ch = 47 + parseInt(sm[1], 10);   // a send: colour of its bus
  else if (ch >= MODEL) return '#e8ecef';   // a desk-model input: mono input
  if (ch < 32) return '#e8ecef';
  if (ch < 48) return '#2f7cf6';
  if (ch < 60) return '#2fd24a';
  if (ch < 64) return '#f2d21b';
  if (ch < 70) return '#9aa0a6';
  if (ch === 71 || ch === 80) return '#e23a2a';
  if (ch < 80) return '#f08a1c';
  return '#9aa0a6';
}

function addFader(c, g) {
  // cap travel: +10 mark 4.1 mm below the slot top, -inf with the cap 10.4 mm past the slot end
  // (channel faders; the masters are the same law on their shorter slot)
  const isMaster = c.h < 90;
  const top = c.top + 4.1, bottom = c.bottom + (isMaster ? 9.65 : 10.4);
  // cap after the PRO fader cap: black contoured body (wide top and bottom lobes, waisted middle),
  // gloss on the lobes, and a coloured centre band + disc that shows what the fader controls
  const cap = el('g', {}, g);
  const X = c.x, hw = 6.5, wy = 5.2;   // half width, half height of the waist
  el('path', { class: 'capbody', d:
    `M ${X - hw + 1.2} -15 L ${X + hw - 1.2} -15 Q ${X + hw} -15 ${X + hw} -13.2 L ${X + hw} -${wy + 3} ` +
    `Q ${X + hw - 1.6} -${wy} ${X + hw - 1.6} 0 Q ${X + hw - 1.6} ${wy} ${X + hw} ${wy + 3} L ${X + hw} 13.2 ` +
    `Q ${X + hw} 15 ${X + hw - 1.2} 15 L ${X - hw + 1.2} 15 Q ${X - hw} 15 ${X - hw} 13.2 L ${X - hw} ${wy + 3} ` +
    `Q ${X - hw + 1.6} ${wy} ${X - hw + 1.6} 0 Q ${X - hw + 1.6} -${wy} ${X - hw} -${wy + 3} L ${X - hw} -13.2 ` +
    `Q ${X - hw} -15 ${X - hw + 1.2} -15 Z` }, cap);
  el('ellipse', { cx: X, cy: -10.5, rx: hw - 1.4, ry: 3.2, fill: 'url(#capgloss)' }, cap);
  el('ellipse', { cx: X, cy: 10.5, rx: hw - 1.4, ry: 3.2, fill: 'url(#capgloss)', opacity: 0.7 }, cap);
  const band = el('rect', { x: X - hw + 1.2, y: -1.3, width: 2 * hw - 2.4, height: 2.6, rx: 0.8 }, cap);
  const disc = el('circle', { cx: X, cy: 0, r: 3.6, stroke: '#0a0a0a', 'stroke-width': 0.35 }, cap);
  el('ellipse', { cx: X - 0.8, cy: -1.3, rx: 2.0, ry: 1.0, fill: '#ffffff', opacity: 0.35 }, cap);
  el('rect', { x: c.x - 8, y: c.top - 2, width: 16, height: bottom - c.top + 18, class: 'hit' }, g);
  let local = 1, t0 = 0, y0 = 0;
  const tOf = () => {
    const r = resolve(c.bind);
    if (!r) return local;
    if (r.p === 'mon_level' || r.p === 'fader' || r.p === 'mch_fader' || /send/.test(r.p)) return faderT(val(r.p, r.i, -100));
    return 1 - toPos(val(r.p, r.i, r.lo), r);
  };
  const mmPerPx = () => model.height / svg.getBoundingClientRect().height;
  g.addEventListener('pointerdown', (e) => {
    e.preventDefault(); g.setPointerCapture(e.pointerId);
    y0 = e.clientY; t0 = tOf();
    // click on the slot away from the cap: jump there
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const m = pt.matrixTransform(svg.getScreenCTM().inverse());
    const tc = top + t0 * (bottom - top);
    if (Math.abs(m.y - tc) > 16) { t0 = clamp((m.y - top) / (bottom - top), 0, 1); apply(t0); }
  });
  const apply = (t) => {
    const r = resolve(c.bind);
    if (!r) { local = t; refresh(); return; }
    const db = Math.round(faderDb(t) * 10) / 10;
    send('set', r.p, r.i, db);
    tip(c, chName(r.ch ?? -1) + ' ' + fmt(db, r));
  };
  g.addEventListener('pointermove', (e) => {
    if (!g.hasPointerCapture(e.pointerId)) return;
    const dt = (e.clientY - y0) * mmPerPx() / (bottom - top);
    apply(clamp(t0 + dt * (e.shiftKey ? 0.25 : 1), 0, 1));
  });
  g.addEventListener('wheel', (e) => { e.preventDefault(); apply(clamp(tOf() + e.deltaY / 2000, 0, 1)); }, { passive: false });
  return () => {
    const col = capColour(c);
    band.style.fill = col; disc.style.fill = col;
    cap.setAttribute('transform', `translate(0 ${top + tOf() * (bottom - top)})`);
  };
}

function addMeter(c, g) {
  const cells = c.cells.map(cy => el('rect', { x: c.x - c.w / 2 + 0.25, y: cy - c.ch / 2 + 0.25, width: c.w - 0.5, height: c.ch - 0.5 }, g));
  const n = cells.length;
  // strip meters: +18 .. -30 dBu legends (0 dBFS = +18 dBu), masters: 0 .. -60 dBFS
  const strip = c.scale ? c.scale === 'strip' : c.y > 350;
  const thr = cells.map((_, k) => strip ? [0, -3, -6, -9, -12, -15, -18, -22, -28, -36, -48, -60][k] ?? -60 : -60 * k / (n - 1));
  return () => {
    const r = resolve(c.bind);
    const v = r ? val(r.p, r.i, -120) : -120;
    cells.forEach((e, k) => {
      const lit = v >= thr[k] && v > -119;
      const col = k / n < 0.15 ? '#ff3b2f' : k / n < 0.4 ? '#ffd21a' : '#3ddc4a';
      e.style.fill = lit ? col : '#1b1c1f';
    });
  };
}

function addLed(c, g) {
  const e = el('circle', { cx: c.x, cy: c.y, r: Math.min(c.w, c.h) / 2 - 0.15, fill: '#2a1c12' }, g);
  const b = c.bind || {};   // an LED with no key nearby (PRO2 / PRO X) stays dark
  // band LEDs: top = band 4 ... bottom = band 1; other LEDs show the state of their key
  const bandLeds = b.kind === 'bandled' ? model.controls.filter(o => o.bind && o.bind.kind === 'bandled').sort((p, q) => p.y - q.y) : null;
  const key = b.kind === 'mirror' ? model.controls.find(o => Math.abs(o.x - b.x) < 0.05 && Math.abs(o.y - b.y) < 0.05) : null;
  return () => {
    const on = bandLeds ? bandLeds.indexOf(c) === 4 - S.band : (key ? isOn(key) : false);
    e.style.fill = on ? '#ff9a1f' : '#2a1c12';
  };
}

function addJog(c, g) {
  el('circle', { cx: c.x, cy: c.y, r: 22, class: 'ring' }, g);
  el('circle', { cx: c.x, cy: c.y, r: 17.1, class: 'wheel' }, g);
  const dim = el('circle', { r: 2.6, class: 'dimple' }, g);
  let angle = 0, acc = 0, a0 = null;
  const ang = (e) => {
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const m = pt.matrixTransform(svg.getScreenCTM().inverse());
    return Math.atan2(m.x - c.x, -(m.y - c.y));
  };
  g.addEventListener('pointerdown', (e) => { e.preventDefault(); g.setPointerCapture(e.pointerId); a0 = ang(e); });
  g.addEventListener('pointermove', (e) => {
    if (a0 === null) return;
    let a = ang(e), d = a - a0;
    if (d > Math.PI) d -= 2 * Math.PI;
    if (d < -Math.PI) d += 2 * Math.PI;
    a0 = a; angle += d; acc += d;
    const det = Math.PI / 6;
    while (acc > det) { acc -= det; select(selStep(S.sel, 1)); }
    while (acc < -det) { acc += det; select(selStep(S.sel, -1)); }
    refresh();
  });
  g.addEventListener('pointerup', () => { a0 = null; });
  g.addEventListener('wheel', (e) => { e.preventDefault(); select(selStep(S.sel, e.deltaY > 0 ? 1 : -1)); }, { passive: false });
  return () => {
    dim.setAttribute('cx', c.x + 12.5 * Math.sin(angle));
    dim.setAttribute('cy', c.y - 12.5 * Math.cos(angle));
  };
}

// ------------------------------------------------------------------------------------------------
// tooltips
// ------------------------------------------------------------------------------------------------

let tipTimer = null;
function describe(c) {
  const b = c.bind;
  const lab = (c.label ? c.label : c.type) + (c.derived ? '  [derived: ' + c.derived + ']' : '');
  if (!b) return MODEL_ID === 'pro1' ? lab : lab + '  (no OMC function: latches on the page only)';
  if (b.kind === 'cmd' || b.kind === 'radio' || b.kind === 'enc' || b.kind === 'enckey') return `${lab}  →  touch UI: ${b.what}`;
  if (b.kind === 'ukey' || b.kind === 'uenc') {
    const t = String(val('ukey_label', b.kind === 'ukey' ? b.i : 16 + b.i, '') || 'not assigned');
    return `${lab}  →  user ${b.kind === 'ukey' ? 'key' : 'knob'} ${b.i} of bank ${val('ukey_label', 25, '') || '?'}: ${t}`;
  }
  if (b.kind === 'ukbank' || b.kind === 'ukstep') return `${lab}  →  ${b.what}  (bank ${val('ukey_label', 25, '') || '?'} of ${Math.round(val('ukey_bank', 2, 0))})`;
  if (b.kind === 'stripcmd' || b.kind === 'stripfn') return `${lab}  →  ${chName(stripChannel(b.bank, b.slot))}: ${b.what}`;
  if (b.kind === 'keypad' || b.kind === 'sendpage' || b.kind === 'flip' || b.kind === 'bandsel' || b.kind === 'selknob' || b.kind === 'qmode') return `${lab}  →  ${b.what}`;
  if (b.kind === 'surface') return `${lab}  →  ${b.what || 'surface'} (touch UI desk model, OMC surface/${b.i} = ${val('surface', b.i, 0).toFixed(2)})`;
  if (b.kind === 'bay') return `${lab}  →  ${b.what}`;
  if (b.kind === 'cycle') { const r = resolve(b); return r ? `${lab}  →  EQ band ${S.band} type ${val(r.p, r.i, 0)} (${r.p})` : lab; }
  const r = resolve(b);
  switch (b.kind) {
    case 'mode': return b.mode === 'dyn' ? `dynamics: edit ${b.value}` : `EQ band ${b.value} (band ${S.band})`;
    case 'sends': return b.bus ? `AUX ${b.bus} sends on faders` : 'faders (clear sends on faders)';
    case 'layer': return MODEL_ID === 'pro1' ? `${b.bank === 'L' ? 'left' : 'right'} bank: ${b.value}` : `bay ${b.bank}: ${b.value}`;
    case 'scroll': return MODEL_ID === 'pro1' ? `scroll ${b.bank === 'L' ? 'left' : 'right'} bank` : `scroll bay ${b.bank}`;
    case 'selstep': return 'select previous / next channel';
    case 'jog': return 'jog: select channel';
  }
  if (!r) return lab + ' (unused on this layer)';
  const v = val(r.p, r.i, null);
  return `${lab}  →  ${r.p} ${r.ch !== undefined ? chName(r.ch) : (b.kind === 'sel' || b.kind === 'dyn' || b.kind === 'band') ? chName(S.sel) : r.i}` +
         (v === null || v === undefined ? '' : '  =  ' + fmt(v, r));
}
function tip(c, text, ev) {
  const t = document.getElementById('tip');
  t.textContent = text || describe(c);
  t.style.display = 'block';
  if (ev) { t.style.left = (ev.clientX + 14) + 'px'; t.style.top = (ev.clientY + 14) + 'px'; }
  clearTimeout(tipTimer);
  tipTimer = setTimeout(() => { t.style.display = 'none'; }, 2500);
}

// ------------------------------------------------------------------------------------------------
// build
// ------------------------------------------------------------------------------------------------

// scribble overlays (docs/60): the look an input number shows now, null for its own (the off phase of a flash)
function ovlLook(n) {
  if (n < 0) return null;
  const st = Math.round(val('ovl_style', n + 1, 0));
  if (st <= 0) return null;
  if (st - 1 >= 8 && Math.floor(Date.now() / 250) % 2 !== 0) return null;
  return { pal: (st - 1) & 7, text: String(val('ovl_text', n + 1, '') || '') };
}
// a flashing overlay repaints at 4 Hz without waiting for a value change
setInterval(() => {
  for (let n = 1; n <= INPUTS; n++) if (Math.round(val('ovl_style', n, 0)) > 8) { scheduleRefresh(); return; }
}, 125);

let refreshPending = false;
function scheduleRefresh() {
  if (refreshPending) return;
  refreshPending = true;
  requestAnimationFrame(() => { refreshPending = false; refresh(); });
}
function refresh() {
  if (typeof Vegas !== 'undefined' && Vegas.active()) return;   // Vegas mode owns the controls (vegas.js); repaints on exit
  for (const v of views) v.update();
}

async function build() {
  let svgText, ctl;
  try {
    [svgText, ctl] = await Promise.all([fetch(ASSETS() + 'panel.svg').then(r => { if (!r.ok) throw r.status; return r.text(); }),
                                         fetch(ASSETS() + 'controls.json').then(r => { if (!r.ok) throw r.status; return r.json(); })]);
  } catch (e) {
    if (MODEL_ID === 'pro1') throw e;
    // that model is not installed here: back to the PRO1
    store('surface-model', null);
    PARAMS.delete('model');
    location.replace(location.pathname + (PARAMS.toString() ? '?' + PARAMS : ''));
    return;
  }
  model = ctl;
  setLayout(model.surface || PRO1_SURFACE);
  header();
  const host = document.getElementById('surface');
  host.innerHTML = svgText;
  svg = host.querySelector('svg');
  svg.removeAttribute('width'); svg.removeAttribute('height');

  // flat finish under the line art: chassis and top plate
  const defs = el('defs', {}, null);
  defs.innerHTML = '<linearGradient id="capgrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#0b0b0c"/>' +
    '<stop offset="0.35" stop-color="#2c2d30"/><stop offset="0.55" stop-color="#3a3b3f"/><stop offset="1" stop-color="#0b0b0c"/></linearGradient>' +
    '<radialGradient id="knobbody" cx="0.4" cy="0.35" r="0.75"><stop offset="0" stop-color="#3d3f44"/>' +
    '<stop offset="1" stop-color="#0c0c0d"/></radialGradient>' +
    '<radialGradient id="capgloss" cx="0.5" cy="0.35" r="0.6"><stop offset="0" stop-color="#9a9da3" stop-opacity="0.75"/>' +
    '<stop offset="1" stop-color="#2a2b2e" stop-opacity="0"/></radialGradient>';
  svg.insertBefore(defs, svg.firstChild);
  const base = el('g', {}, null);
  el('rect', { x: 0.5, y: 1.9, width: model.width - 1, height: model.height - 2.4, rx: 14, class: 'chassis' }, base);
  if (!model.surface) el('rect', { x: 35.0, y: 55.3, width: 614.3, height: 617.5, rx: 6, class: 'plate' }, base);
  svg.insertBefore(base, defs.nextSibling);

  // controls above the line art; the screen opening stays blank (the display covers it)
  controlsLayer = el('g', { id: 'controls' }, svg);
  for (const c of model.controls) {
    const g = el('g', { class: `ctl ${c.type} ${c.bind ? 'bound' : 'unbound'}` }, controlsLayer);
    let update;
    switch (c.type) {
      case 'button': case 'ledbutton': case 'round': case 'arrow': update = addButton(c, g); break;
      case 'lcd': update = addLcd(c, g); break;
      case 'knob': case 'pot': update = addKnob(c, g); break;
      case 'fader': update = addFader(c, g); break;
      case 'meter': g.classList.remove('ctl'); update = addMeter(c, g); break;
      case 'led': g.classList.remove('ctl'); update = addLed(c, g); break;
      case 'jog': update = addJog(c, g); break;
      default: continue;
    }
    if (c.type !== 'meter' && c.type !== 'led') {
      g.addEventListener('pointerenter', (e) => tip(c, null, e));
      g.addEventListener('pointermove', (e) => { const t = document.getElementById('tip'); t.style.left = (e.clientX + 14) + 'px'; t.style.top = (e.clientY + 14) + 'px'; });
    }
    views.push({ c, el: g, update });
  }
  const scr = svg.querySelector('#screen');
  if (scr) svg.appendChild(scr);   // keep the display opening on top and empty
  refresh();
  fit();
  connect();
}

// ------------------------------------------------------------------------------------------------
// view
// ------------------------------------------------------------------------------------------------

let mode = stored(prefKey('zoom')) === '1:1' ? '1:1' : 'fit';
function fit() {
  const stage = document.getElementById('stage'), host = document.getElementById('surface');
  if (!model) return;
  if (mode === 'fit') {
    const k = Math.min(stage.clientWidth / model.width, stage.clientHeight / model.height);
    host.style.width = (model.width * k) + 'px';
  } else host.style.width = (model.width * 96 / 25.4) + 'px';
  document.getElementById('fit').classList.toggle('on', mode === 'fit');
  document.getElementById('zoom').classList.toggle('on', mode !== 'fit');
}
window.addEventListener('resize', fit);
document.getElementById('fit').onclick = () => { mode = 'fit'; store(prefKey('zoom'), mode); fit(); };
document.getElementById('zoom').onclick = () => { mode = '1:1'; store(prefKey('zoom'), mode); fit(); };
function setTheme(on) {
  colourTheme = on;
  document.body.classList.toggle('colour', on);
  const b = document.getElementById('theme');
  b.textContent = on ? 'classic' : 'full colour';
  b.classList.toggle('on', on);
  store(prefKey('theme'), on ? 'colour' : 'classic');
  refresh();
}
document.getElementById('theme').onclick = () => setTheme(!colourTheme);
colourTheme = stored(prefKey('theme')) === 'colour';
document.body.classList.toggle('colour', colourTheme);
document.getElementById('theme').textContent = colourTheme ? 'classic' : 'full colour';
function setLegend(on) {
  document.body.classList.toggle('show-legend', on);
  document.getElementById('labels').classList.toggle('on', on);
}
document.getElementById('labels').onclick = () => {
  const on = !document.body.classList.contains('show-legend');
  setLegend(on);
  store(prefKey('legend'), on ? '1' : null);
};
setLegend(stored(prefKey('legend')) === '1');
// the strip LCDs as OMC's 36 x 24 surface strip (scr_bmp) instead of text
function setDots(on) {
  lcdDots = on;
  document.getElementById('dots').classList.toggle('on', on);
  store(prefKey('lcd'), on ? 'dots' : null);
  refresh();
}
document.getElementById('dots').onclick = () => setDots(!lcdDots);
lcdDots = stored(prefKey('lcd')) === 'dots' || PARAMS.get('lcd') === 'dots';
document.getElementById('dots').classList.toggle('on', lcdDots);

// ------------------------------------------------------------------------------------------------
// model selector (persisted: URL parameter + localStorage); banks change from the desk's own keys
// ------------------------------------------------------------------------------------------------

function syncUrl() {
  if (MODEL_ID === 'pro1' && !PARAMS.has('model')) return;   // the PRO1 default keeps a bare URL
  PARAMS.set('model', MODEL_ID);
  history.replaceState(null, '', location.pathname + '?' + PARAMS);
}
function header() {
  const name = MODEL_NAME() + (model.surface && model.surface.derived ? ' (derived)' : '');
  document.querySelector('header .model').textContent = name + ' control surface';
  document.querySelector('header .model').title = (model.surface && model.surface.derived) || '';
  document.title = MODEL_NAME() + ' Surface';
  store('surface-model', MODEL_ID);
  syncUrl();
  const sel = document.getElementById('modelsel');
  if (sel) {
    sel.innerHTML = '';
    for (const m of MODEL_LIST) {
      if (m.id !== 'pro1' && AVAILABLE && !AVAILABLE.includes(m.id) && m.id !== MODEL_ID) continue;
      const o = document.createElement('option');
      o.value = m.id; o.textContent = m.name; o.selected = m.id === MODEL_ID;
      sel.appendChild(o);
    }
    sel.onchange = () => {
      store('surface-model', sel.value);
      const q = new URLSearchParams();
      if (sel.value !== 'pro1') q.set('model', sel.value);
      location.assign(location.pathname + (q.toString() ? '?' + q : ''));
    };
  }
}
// the models installed next to the PRO1 (deploy/install.sh writes models/index.json)
let AVAILABLE = null;
fetch('models/index.json').then(r => (r.ok ? r.json() : null)).catch(() => null).then((list) => {
  AVAILABLE = Array.isArray(list) ? list : [];
  if (model) header();
});
build();
