// Channels 33-40 and the EXTEND toggle on the PRO1 web surface (docs/25, "Revision: 40 channels").
//
//   The engine carries inputs 1-32; inputs 33-40 are the touch UI's desk-model strips, mirrored by OMC
//   as mch_<fn>/<input> and msel (OMC model-mirror.h). Page A operates the surface with the mouse;
//   page B only watches, so it learns values from OMC's change feed alone (the bridge does not echo).
//
//   Checks: the INPUT layer pages 1-40 (5 pages, no aux / FX returns), names from OMC; fader, mute,
//   solo, LCD select and the upper-strip keys of a model input reach OMC and come back on page B;
//   meters are polled; an OSC write from outside reaches the page. Scroll moves a bank one fader
//   (no wrap). EXTEND: on, the right bank is the eight after the left's last channel and lit; either
//   bank's Scroll keys move both by one fader; blank past channel 40; off, the right bank goes back;
//   a mix-bay key or ALIGN ends it. The touch layer (OMC's surface halves): EXTEND = ui_cmd 94 (lit
//   from bank_page/5), Scroll = ui_cmd 95-98, one fader. Model input 37, both ways (page A's mouse and
//   outside OSC): gate / comp knobs, EQ band knobs and type, ST / MON, mono level, AUX sends on
//   faders; the untouched colour reads as 3; a POP spill with ch 37 reaches the touch layer. Writes a screenshot with 33-40 on the left bank
//   and EXTEND on.
//
// usage: node test/extend-40.js http://127.0.0.1:48180/ [out-dir]   (needs playwright; OMC simulator
//        + test/serve-local.py on 127.0.0.1; OMC_OSC_PORT=<omc osc port> for the outside-write check)
const { chromium } = require('playwright');
const dgram = require('dgram');
const URL = process.argv[2] || 'http://127.0.0.1:48180/';
const OUT = process.argv[3] || '.';
const OMC_PORT = +(process.env.OMC_OSC_PORT || 0);

const results = [];
let s;   // bank state
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function oscString(s) { const b = Buffer.from(s + '\0'); return Buffer.concat([b, Buffer.alloc((4 - b.length % 4) % 4)]); }
function oscSend(path, v) {
  return new Promise((res) => {
    const msg = typeof v === 'string' ? Buffer.concat([oscString(path), oscString(',s'), oscString(v)])
      : Buffer.concat([oscString(path), oscString(',f'), (() => { const b = Buffer.alloc(4); b.writeFloatBE(v); return b; })()]);
    const s = dgram.createSocket('udp4');
    s.send(msg, OMC_PORT, '127.0.0.1', () => { s.close(); res(); });
  });
}

(async () => {
  const browser = await chromium.launch();
  const A = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
  const B = await browser.newPage({ viewport: { width: 800, height: 800 } });
  const errors = [];
  for (const p of [A, B]) p.on('pageerror', e => errors.push(String(e)));
  await A.goto(URL, { waitUntil: 'networkidle' });
  await B.goto(URL, { waitUntil: 'networkidle' });
  await sleep(1500);
  const status = await A.evaluate(() => document.getElementById('status').textContent);
  check('linked to OMC', status === 'linked to OMC', status);
  if (status !== 'linked to OMC') { await browser.close(); process.exit(2); }

  const valB = (k) => B.evaluate((k) => S.values.get(k), k);
  const until = async (fn, ms = 3000) => { for (let t = 0; t < ms / 100; t++) { if (await fn()) return true; await sleep(100); } return !!(await fn()); };
  // controls by binding
  const find = (pred) => A.evaluate((src) => {
    const f = eval(src);
    const k = views.findIndex(v => v.c.bind && f(v.c));
    if (k < 0) return null;
    const box = views[k].el.getBoundingClientRect();
    return { k, id: views[k].c.id, x: box.x + box.width / 2, y: box.y + box.height / 2, w: box.width, h: box.height };
  }, pred);
  const key = async (pred) => { const c = await find(pred); await A.mouse.click(c.x, c.y); await sleep(250); return c; };
  const scroll = (bank, step) => key(`(c) => c.bind.kind === 'scroll' && c.bind.bank === '${bank}' && c.bind.step === ${step}`);
  const EXTEND = `(c) => c.bind.kind === 'bay' && c.bind.value === 'extend'`;
  const ALIGN = `(c) => c.bind.kind === 'bay' && c.bind.value === 'align'`;
  const lcds = (bank) => A.evaluate((bank) => views.filter(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.bank === bank)
    .sort((a, b) => a.c.bind.slot - b.c.bind.slot).map(v => [...v.el.querySelectorAll('text')].map(t => t.textContent)), bank);
  const state = () => A.evaluate(() => ({ layer: { ...S.layer }, page: { ...S.page }, extend: !!S.extend }));
  const lit = (pred) => A.evaluate((src) => { const f = eval(src); return isOn(views.find(v => v.c.bind && f(v.c)).c); }, pred);
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, k) => 'Ch ' + (a + k));

  // ---- the input layer: 1-40 in 5 pages
  await A.evaluate(() => { S.layer = { L: 'input', R: 'input' }; S.page = { L: 0, R: 1 }; S.extend = null; watch(); refresh(); });
  const pages = [];
  const goPage = (p) => A.evaluate((p) => { S.page.L = p; delete S.base.L; refresh(); }, p);
  for (let p = 0; p < 5; p++) { await goPage(p); pages.push((await lcds('L')).map(t => t[0])); }
  check('INPUT layer: 5 pages, channels 1-40', JSON.stringify(pages) === JSON.stringify([range(1, 8), range(9, 16), range(17, 24), range(25, 32), range(33, 40)]), JSON.stringify(pages[4]));
  await goPage(0);
  await scroll('L', 1);
  check('Scroll moves the bank one fader (2-9)', JSON.stringify((await lcds('L')).map(t => t[0])) === JSON.stringify(range(2, 9)));
  await scroll('L', -1); await scroll('L', -1);
  check('Scroll back stops at channel 1 (no wrap)', JSON.stringify((await lcds('L')).map(t => t[0])) === JSON.stringify(range(1, 8)));
  await goPage(4);
  for (let k = 0; k < 9; k++) await scroll('L', 1);
  check('Scroll stops with channel 40 on the first fader (no aux / FX returns, no wrap)', (await lcds('L')).map(t => t[0]).join() === ['Ch 40', '', '', '', '', '', '', ''].join());
  await goPage(4);
  await sleep(800);
  const names = (await lcds('L')).map(t => t[1]);
  const omcNames = [];
  for (let n = 33; n <= 40; n++) omcNames.push(String((await valB('mch_name/' + n)) ?? ''));
  check('names of 33-40 come from OMC (mch_name)', names.every(n => n) && JSON.stringify(names) === JSON.stringify(omcNames.map(n => n.slice(0, 8))), JSON.stringify(names));

  // ---- strip controls of a model input reach OMC and come back through its feed (page B)
  const fader = await find(`(c) => c.type === 'fader' && c.bind.kind === 'strip' && c.bind.bank === 'L' && c.bind.slot === 0`);
  const f0 = await valB('mch_fader/33');
  const t0 = await A.evaluate((k) => { const r = resolve(views[k].c.bind); return faderT(val(r.p, r.i, -100)); }, fader.k);
  const pxmm = await A.evaluate(() => svg.getBoundingClientRect().height / model.height);
  const capY = fader.y - fader.h / 2 + (2 + 4.1 + t0 * 99.4) * pxmm;
  await A.mouse.move(fader.x, capY); await A.mouse.down(); await A.mouse.move(fader.x, capY + (t0 > 0.5 ? -60 : 60), { steps: 6 }); await A.mouse.up();
  const fRes = await A.evaluate((k) => resolve(views[k].c.bind), fader.k);
  check('ch 33 fader -> mch_fader/33 on OMC', fRes.p === 'mch_fader' && fRes.i === 33 &&
        await until(async () => { const v = await valB('mch_fader/33'); return v !== undefined && Math.abs(v - (f0 ?? -100)) > 0.5; }),
        `${f0} -> ${await valB('mch_fader/33')}`);
  await A.evaluate((v) => send('set', 'mch_fader', 33, v), f0 ?? -100);

  for (const [p, slot, n] of [['ch_mute', 1, 34], ['ch_solo', 2, 35]]) {
    const was = (await valB(`${p.replace('ch_', 'mch_')}/${n}`)) ?? 0;
    await key(`(c) => c.bind.kind === 'strip' && c.bind.p === '${p}' && c.bind.bank === 'L' && c.bind.slot === ${slot}`);
    const k = `${p.replace('ch_', 'mch_')}/${n}`;
    check(`ch ${n} ${p.slice(3)} key -> ${k}`, await until(async () => Math.abs(((await valB(k)) ?? 0) - (was >= 0.5 ? 0 : 1)) < 1e-3), `${was} -> ${await valB(k)}`);
    if (p === 'ch_mute') check('ch 34 LCD shows MUTE', (await lcds('L'))[1][2] === 'MUTE');
    await key(`(c) => c.bind.kind === 'strip' && c.bind.p === '${p}' && c.bind.bank === 'L' && c.bind.slot === ${slot}`);
    await until(async () => Math.abs(((await valB(k)) ?? 0) - was) < 1e-3);
  }

  // LCD select of a model input: OMC msel, the touch UI follows (ui_cmd 60), page B sees the selection
  await key(`(c) => c.type === 'lcd' && c.bind.kind === 'strip' && c.bind.bank === 'L' && c.bind.slot === 3`);
  check('select ch 36 -> msel 36 on OMC, page B follows', await until(async () => (await valB('msel/1')) === 36 &&
        (await B.evaluate(() => S.sel)) === (await B.evaluate(() => MODEL + 35))), `msel ${await valB('msel/1')}`);
  check('upper strip edits ch 36 (MUTE -> mch_mute/36, gain -> mch_gain/36)',
        await A.evaluate(() => { const m = views.find(v => v.c.bind && v.c.bind.kind === 'sel' && v.c.bind.p === 'ch_mute');
          const g = views.find(v => v.c.bind && v.c.bind.kind === 'sel' && v.c.bind.p === 'ch_gain');
          const a = resolve(m.c.bind), b = resolve(g.c.bind); return a.p === 'mch_mute' && a.i === 36 && b.p === 'mch_gain' && b.i === 36; }));
  const ph0 = (await valB('mch_phantom/36')) ?? 0;
  await key(`(c) => c.bind.kind === 'sel' && c.bind.p === 'ch_phantom'`);
  check('48V on the selected model input -> mch_phantom/36', await until(async () => Math.abs(((await valB('mch_phantom/36')) ?? 0) - (ph0 >= 0.5 ? 0 : 1)) < 1e-3));
  await key(`(c) => c.bind.kind === 'sel' && c.bind.p === 'ch_phantom'`);
  check('EQ band knobs target the model mirror on a model input', await A.evaluate(() => { const r = resolve(views.find(v => v.c.bind && v.c.bind.kind === 'band').c.bind); return !!r && /^mch_eq_[fgq]\d$/.test(r.p) && r.i === 36; }));
  // back to an engine channel
  await A.evaluate(() => select(2, true));
  check('select ch 3 -> msel 0, sel 2', await until(async () => (await valB('msel/1')) === 0 && (await valB('sel/1')) === 2));

  // meters of model inputs are polled
  check('ch 33 meter polled (mch_meter/33)', await until(async () => (await A.evaluate(() => S.values.get('mch_meter/33'))) !== undefined));

  // OMC -> page: a write from another OSC client
  if (OMC_PORT) {
    await oscSend('/set/mch_name/37', 'Vox 37');
    check('outside OSC write mch_name/37 shows on the LCD', await until(async () => (await lcds('L'))[4][1] === 'Vox 37'));
  }

  // ---- the full control set on model input 37, both ways: dynamics knobs (gate and comp), EQ band
  //      knobs and type, ST / MON, mono level, AUX sends on faders; a POP spill on the touch layer
  await A.evaluate(() => { S.layer = { L: 'input', R: 'input' }; S.page = { L: 4, R: 1 }; S.extend = null; S.dyn = 'comp'; S.sends = 0; watch(); refresh(); });
  await key(`(c) => c.type === 'lcd' && c.bind.kind === 'strip' && c.bind.bank === 'L' && c.bind.slot === 4`);
  check('select ch 37 -> msel 37', await until(async () => (await valB('msel/1')) === 37 && (await B.evaluate(() => S.sel)) === (await B.evaluate(() => MODEL + 36))));
  // page B shows the same surface state (gate / comp, band, sends on faders), so it watches the same paths
  const syncB = async () => { const st = await A.evaluate(() => [S.dyn, S.band, S.sends]);
    await B.evaluate(([d, b, s]) => { S.dyn = d; S.band = b; S.sends = s; watch(); refresh(); }, st); await sleep(300); };
  const addrOf = (pred) => A.evaluate((src) => { const f = eval(src); const v = views.find(v => v.c.bind && f(v.c)); const r = resolve(v.c.bind); return r ? r.p + '/' + r.i : null; }, pred);
  // a knob dragged on page A: OMC has the new value and keeps it (the desk model took it: OMC writes the model's value back)
  const knobBothWays = async (name, pred, want, oscValue) => {
    const k = await addrOf(pred);
    if (!k || !k.startsWith(want + '/')) { check(`${name}: target ${want}/37`, false, String(k)); return; }
    await syncB();
    const before = await valB(k);
    const c = await find(pred);
    const p0 = await A.evaluate((src) => { const f = eval(src); const v = views.find(v => v.c.bind && f(v.c)); const r = resolve(v.c.bind); return toPos(val(r.p, r.i, r.lo), r); }, pred);
    // towards the middle (a surface range can be wider than OMC's: a value at OMC's end would not move)
    const dy = p0 > 0.5 ? 40 : -40;
    // the last value page A sent (its S.values can briefly hold an older value from OMC's change feed)
    await A.evaluate(() => { window.__sent = {}; if (!window.__send0) { window.__send0 = send; send = (op, p, i, v) => { if (op === 'set') window.__sent[p + '/' + i] = v; window.__send0(op, p, i, v); }; } });
    await A.mouse.move(c.x, c.y); await A.mouse.down(); await A.mouse.move(c.x, c.y + dy, { steps: 6 }); await A.mouse.up();
    const moved = await until(async () => { const v = await valB(k); return v !== undefined && before !== undefined && Math.abs(v - before) > 1e-3; });
    const sent = await A.evaluate((k) => window.__sent[k], k);
    await sleep(600);
    const kept = sent !== undefined && Math.abs((await valB(k)) - sent) < Math.max(1e-3, Math.abs(sent) * 1e-3);
    check(`${name} -> ${k} on OMC, kept by the desk model`, moved && kept, `${before} -> ${sent} (OMC ${await valB(k)})`);
    if (OMC_PORT) {
      const [p, i] = k.split('/');
      await oscSend(`/set/${p}/${i}`, oscValue);
      check(`${name}: OSC ${k} = ${oscValue} shows on the knob`, await until(async () => Math.abs((await A.evaluate((k) => S.values.get(k), k)) - oscValue) < 1e-2 &&
            Math.abs((await valB(k)) - oscValue) < 1e-2), `${await A.evaluate((k) => S.values.get(k), k)}`);
    }
  };
  const dynKnob = (p) => `(c) => c.bind.kind === 'dyn' && ((c.bind[S.dyn] || [])[0] === '${p}')`;
  // compressor (S.dyn = comp)
  await knobBothWays('comp threshold', dynKnob('ch_comp_thr'), 'mch_comp_thr', -17);
  await knobBothWays('comp ratio', dynKnob('ch_comp_ratio'), 'mch_comp_ratio', 6);
  await knobBothWays('comp attack', dynKnob('ch_comp_att'), 'mch_comp_att', 4);
  await knobBothWays('comp release', dynKnob('ch_comp_rel'), 'mch_comp_rel', 250);
  await knobBothWays('comp make up', dynKnob('ch_comp_makeup'), 'mch_comp_makeup', 5);
  // gate
  await key(`(c) => c.bind.kind === 'mode' && c.bind.mode === 'dyn' && c.bind.value === 'gate'`);
  await knobBothWays('gate threshold', dynKnob('ch_gate_thr'), 'mch_gate_thr', -42);
  await knobBothWays('gate range', dynKnob('ch_gate_range'), 'mch_gate_range', 30);
  await knobBothWays('gate attack', dynKnob('ch_gate_att'), 'mch_gate_att', 1);
  await knobBothWays('gate hold', dynKnob('ch_gate_hold'), 'mch_gate_hold', 80);
  await knobBothWays('gate release', dynKnob('ch_gate_rel'), 'mch_gate_rel', 300);
  await key(`(c) => c.bind.kind === 'mode' && c.bind.mode === 'dyn' && c.bind.value === 'comp'`);
  // EQ: band 1, then band 2 (the band key moves OMC's eq_band too)
  const BAND = (p) => `(c) => c.bind.kind === 'band' && c.bind.p === '${p}'`;
  await knobBothWays('EQ band 1 freq', BAND('ch_eq_f'), 'mch_eq_f1', 150);
  await knobBothWays('EQ band 1 gain', BAND('ch_eq_g'), 'mch_eq_g1', 3);
  await knobBothWays('EQ band 1 width', BAND('ch_eq_q'), 'mch_eq_q1', 1.2);
  await key(`(c) => c.bind.kind === 'mode' && c.bind.mode === 'band' && c.bind.value === 'up'`);
  await knobBothWays('EQ band 2 freq', BAND('ch_eq_f'), 'mch_eq_f2', 700);
  await knobBothWays('EQ band 2 gain', BAND('ch_eq_g'), 'mch_eq_g2', -2.5);
  await knobBothWays('EQ band 2 width', BAND('ch_eq_q'), 'mch_eq_q2', 4);
  // EQ type (SHAPE steps the type; the model holds bell 1 / low shelf 2 / high shelf 3: others turn into a bell)
  await syncB();
  const SHAPE = `(c) => c.bind.kind === 'cycle'`;
  check('EQ type key targets mch_eq_type2/37', (await addrOf(SHAPE)) === 'mch_eq_type2/37');
  const types = [];
  for (let n = 0; n < 4; n++) {
    await key(SHAPE);
    await sleep(500);
    types.push(await valB('mch_eq_type2/37'));
  }
  const ty0 = types[0];
  check('EQ type steps bell -> low shelf -> high shelf -> bell on the model', new Set(types).size === 3 && types.every(t => [1, 2, 3].includes(t)) &&
        types[3] === ty0 && (await A.evaluate(() => S.values.get('mch_eq_type2/37'))) === types[3], JSON.stringify(types));
  if (OMC_PORT) {
    await oscSend('/set/mch_eq_type2/37', 3);
    check('EQ type: OSC mch_eq_type2/37 = 3 (high shelf) shows on the page', await until(async () => (await A.evaluate(() => S.values.get('mch_eq_type2/37'))) === 3));
    await oscSend('/set/mch_eq_type2/37', 1);
  }
  await key(`(c) => c.bind.kind === 'mode' && c.bind.mode === 'band' && c.bind.value === 'down'`);
  // ST / MON keys
  for (const [lab, p] of [['ST', 'ch_send_lr'], ['MON', 'ch_send_mono']]) {
    const pred = `(c) => c.bind.kind === 'sel' && c.bind.p === '${p}'`;
    const k = await addrOf(pred);
    const was = (await valB(k)) ?? 0;
    await key(pred);
    const flipped = await until(async () => Math.abs(((await valB(k)) ?? -1) - (was >= 0.5 ? 0 : 1)) < 1e-3);
    await sleep(500);
    check(`${lab} key -> ${k} on OMC, kept by the desk model`, k === 'm' + p + '/37' && flipped && Math.abs((await valB(k)) - (was >= 0.5 ? 0 : 1)) < 1e-3, `${was} -> ${await valB(k)}`);
    if (OMC_PORT) {
      await oscSend(`/set/m${p}/37`, was);
      check(`${lab}: OSC m${p}/37 = ${was} lights the key`, await until(async () => (await A.evaluate((src) => { const f = eval(src); return isOn(views.find(v => v.c.bind && f(v.c)).c); }, pred)) === (was >= 0.5)));
    }
  }
  await knobBothWays('mono level', `(c) => c.bind.kind === 'sel' && c.bind.p === 'ch_mono_level'`, 'mch_mono_level', -12);
  // AUX 3 sends on faders: the ch 37 fader is its send to bus 3
  await key(`(c) => c.bind.kind === 'sends' && c.bind.bus === 3`);
  await syncB();
  const F37 = `(c) => c.type === 'fader' && c.bind.kind === 'strip' && c.bind.bank === 'L' && c.bind.slot === 4`;
  check('AUX 3 on faders: the ch 37 fader targets mch_send03/37', (await addrOf(F37)) === 'mch_send03/37');
  {
    const fd = await find(F37);
    const before = (await valB('mch_send03/37')) ?? -100;
    const t = await A.evaluate((k) => { const r = resolve(views[k].c.bind); return faderT(val(r.p, r.i, -100)); }, fd.k);
    const capY = fd.y - fd.h / 2 + (2 + 4.1 + t * 99.4) * pxmm;
    await A.evaluate(() => { window.__sent = {}; });
    await A.mouse.move(fd.x, capY); await A.mouse.down(); await A.mouse.move(fd.x, capY + (t > 0.5 ? -80 : 80), { steps: 6 }); await A.mouse.up();
    const moved = await until(async () => Math.abs(((await valB('mch_send03/37')) ?? before) - before) > 0.5);
    const sent = await A.evaluate(() => window.__sent['mch_send03/37']);
    await sleep(600);
    check('AUX 3 send of ch 37 -> mch_send03/37, kept by the desk model', moved && Math.abs((await valB('mch_send03/37')) - sent) < 0.05, `${before} -> ${sent}`);
    check('the ch 37 LCD shows the send level', /^A3 /.test((await lcds('L'))[4][2]), (await lcds('L'))[4][2]);
    if (OMC_PORT) {
      await oscSend('/set/mch_send03/37', -20);
      check('AUX 3: OSC mch_send03/37 = -20 moves the fader', await until(async () => Math.abs((await A.evaluate((k) => { const r = resolve(views[k].c.bind); return val(r.p, r.i, 0); }, fd.k)) + 20) < 0.05 &&
            (await lcds('L'))[4][2] === 'A3 -20.0'));
    }
  }
  await key(`(c) => c.bind.kind === 'sends' && c.bind.bus === 0`);
  await syncB();
  // default colour: an untouched model input reads as the engine default (3, yellow), not blue (4)
  check('untouched model input 39 has colour 3 (engine default)', (await A.evaluate(() => S.values.get('mch_color/39'))) === 3, String(await A.evaluate(() => S.values.get('mch_color/39'))));
  // POP spill with a model input: ALT + POP 6 puts the selected ch 37 in POP 6, POP 6 spills it to the
  // touch layer as bank = 1000 + 37
  const POP6 = `(c) => c.bind.kind === 'cmd' && c.bind.p === 'ui_cmd' && c.bind.value === 55`;
  await A.evaluate(() => send('set', 'surface', 63, 1)); await sleep(400);
  await key(POP6); await sleep(400);
  await A.evaluate(() => send('set', 'surface', 63, 0)); await sleep(400);
  await key(POP6);
  check('POP spill with ch 37: bank/1 = 1037', await until(async () => (await valB('bank/1')) === 1037), String(await valB('bank/1')));
  s = await state();
  check('touch layer shows ch 37 (LCD) and its fader targets mch_fader/37', s.layer.L === 'touch' &&
        await until(async () => (await lcds('L'))[0][0] === 'Ch 37') && (await addrOf(`(c) => c.type === 'fader' && c.bind.kind === 'strip' && c.bind.bank === 'L' && c.bind.slot === 0`)) === 'mch_fader/37',
        JSON.stringify((await lcds('L'))[0]));
  // take ch 37 out of POP 6 again
  await A.evaluate(() => send('set', 'surface', 63, 1)); await sleep(400);
  await key(POP6); await sleep(400);
  await A.evaluate(() => send('set', 'surface', 63, 0)); await sleep(400);
  await A.evaluate(() => select(2, true));
  await until(async () => (await valB('msel/1')) === 0);

  // ---- EXTEND
  await A.evaluate(() => { S.layer = { L: 'input', R: 'input' }; S.page = { L: 0, R: 1 }; S.extend = null; watch(); refresh(); });
  await key(`(c) => c.bind.kind === 'layer' && c.bind.value === 'vca'`);
  await key(EXTEND);
  s = await state();
  const L8 = async () => (await lcds('L')).map(t => t[0]), R8 = async () => (await lcds('R')).map(t => t[0]);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  check('EXTEND on: right bank = inputs 9-16, key lit', s.extend && s.layer.R === 'input' && await lit(EXTEND) && same(await R8(), range(9, 16)));
  check('ALIGN not lit while EXTEND is on', !(await lit(ALIGN)));
  await scroll('L', 1);
  check('left Scroll moves both by one fader (left 2-9, right 10-17)', same(await L8(), range(2, 9)) && same(await R8(), range(10, 17)));
  await scroll('R', 1);
  check('right Scroll moves both by one fader (left 3-10, right 11-18)', same(await L8(), range(3, 10)) && same(await R8(), range(11, 18)));
  await scroll('R', -1);
  check('right Scroll back moves both (left 2-9, right 10-17)', same(await L8(), range(2, 9)) && same(await R8(), range(10, 17)));
  await A.evaluate(() => { S.page.L = 3; delete S.base.L; refresh(); });
  check('left 25-32, right 33-40 (model inputs)', same(await R8(), range(33, 40)));
  await A.evaluate(() => { S.page.L = 4; delete S.base.L; refresh(); });
  const blank = (await lcds('R')).every(t => t[0] === '');
  check('left 33-40, right blank past the end', blank && same(await L8(), range(33, 40)));
  check('right faders unbound past the end', await A.evaluate(() => views.filter(v => v.c.type === 'fader' && v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.bank === 'R').every(v => resolve(v.c.bind) === null)));
  await A.mouse.move(5, 5);
  await A.evaluate(() => { document.getElementById('tip').style.display = 'none'; });
  await sleep(600);
  await A.screenshot({ path: require('path').join(OUT, 'extend-40.png') });
  await scroll('R', 1);
  check('Scroll at 33-40 moves on to 34-40 (no wrap)', (await L8())[0] === 'Ch 34' && (await L8())[7] === '');
  await key(EXTEND);
  s = await state();
  check('EXTEND off: right bank back to VCA, key unlit', !s.extend && s.layer.R === 'vca' && s.page.R === 0 && !(await lit(EXTEND)));
  await scroll('L', 1);
  s = await state();
  check('EXTEND off: Scroll moves one bank only', (await L8())[0] === 'Ch 35' && s.layer.R === 'vca' && s.page.R === 0);
  // OUTPUT with EXTEND on: the right bank follows the left layer
  await key(EXTEND);
  await key(`(c) => c.bind.kind === 'layer' && c.bind.value === 'output'`);
  s = await state();
  check('OUTPUT with EXTEND on: right = output page 2', s.extend && s.layer.R === 'output' && s.page.L === 0 && s.page.R === 1);
  await key(`(c) => c.bind.kind === 'layer' && c.bind.value === 'aux'`);
  s = await state();
  check('a mix-bay key ends EXTEND and keeps its choice', !s.extend && s.layer.R === 'aux' && !(await lit(EXTEND)));
  await key(`(c) => c.bind.kind === 'layer' && c.bind.value === 'input' && c.bind.bank === 'L'`);
  await key(EXTEND);
  await key(ALIGN);
  s = await state();
  check('ALIGN ends EXTEND (right = left + 1, once)', !s.extend && s.layer.R === 'input' && s.page.R === 1 && await lit(ALIGN));


  // ---- the touch layer: OMC's surface halves (Ch 1-8 left, Ch 9-16 right by default)
  await A.evaluate(() => { S.layer = { L: 'touch', R: 'touch' }; S.page = { L: 0, R: 0 }; S.base = {}; S.extend = null; watch(); refresh(); });
  const bankA = (i) => A.evaluate((i) => Math.round(S.values.get('bank/' + i) || 0), i);
  await sleep(600);
  if ((await A.evaluate(() => S.values.get('bank_page/5'))) >= 0.5) await key(EXTEND);   // EXTEND off on OMC first
  for (const c of [95, 95, 95, 95, 95, 95, 95, 95, 97, 97, 97, 97, 97, 97, 97, 97]) { await A.evaluate((c) => send('set', 'ui_cmd', 1, c), c); await sleep(60); }   // both halves on their first member
  await until(async () => (await bankA(1)) === 1);
  await scroll('L', 1);
  check('touch layer: the left Scroll moves OMC\'s left half one fader (Ch 2 first)', await until(async () => (await bankA(1)) === 2), String(await bankA(1)));
  await scroll('R', 1);
  check('touch layer: the right Scroll moves the right half only (Ch 10 first)', await until(async () => (await bankA(9)) === 10 && (await bankA(1)) === 2), String(await bankA(9)));
  await key(EXTEND);
  check('touch layer: EXTEND (ui_cmd 94) puts the channels after the left half on the right (Ch 9), key lit',
        await until(async () => (await bankA(9)) === 9) && await until(async () => await lit(EXTEND)), String(await bankA(9)));
  await scroll('R', 1);
  check('touch layer: with EXTEND the right Scroll moves both (Ch 3 left)', await until(async () => (await bankA(1)) === 3 && (await bankA(9)) === 9));
  await key(EXTEND);
  check('touch layer: EXTEND off brings the right half back (Ch 10), key unlit', await until(async () => (await bankA(9)) === 10) && await until(async () => !(await lit(EXTEND))));
  await scroll('L', -1); await scroll('L', -1); await scroll('R', -1);

  check('no page errors', errors.length === 0, errors.join(' | '));
  const failed = results.filter(r => !r.ok).length;
  console.log(JSON.stringify({ total: results.length, passed: results.length - failed, failed }));
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
