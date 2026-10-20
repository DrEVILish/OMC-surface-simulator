// The PRO2, PRO2C, PRO X, XL8, X32, X32 COMPACT, X32 RACK, M32, M32R, WING, WING COMPACT and WING RACK
// web surfaces (docs/25, "Other models"), one model per run.
//
//   Page A operates the surface with the mouse; page B only watches, so it learns values from OMC's
//   change feed alone (the bridge does not echo).
//
//   Checks: the model loads from ?model=<id> with no page error, linked to OMC, every control drawn
//   and the bound count of controls.json; the choice is kept (URL + localStorage); every binding
//   resolves; a strip fader and a strip MUTE key of input 1-2 reach OMC (fader/1, ch_mute/2) and
//   come back on page B; the same for a desk-model input past the engine's 32 (mch_fader, mch_mute);
//   model keys: EXTEND (PRO2 /
//   PRO2C), a strip section key and the channel keypad (PRO X / XL8); X32 / M32: the layer keys, the
//   bus sends knobs and their bank keys, the EQ band keys; X32 RACK (no faders): the selected channel's
//   MUTE key; WING family: the layer keys, the 4-channel section. Writes a screenshot.
//
// usage: node test/models.js http://127.0.0.1:48383/ <model id> [out-dir]
//        (needs playwright; an OMC simulator with OMC_PRO_MODEL=PRO2 (pro2, pro2c), PROX (prox, xl8)
//        or PRO1 (the X32 / M32 / WING families) and test/serve-local.py on 127.0.0.1,
//        www/models/<id>/ generated)
const { chromium } = require('playwright');
const BASE = process.argv[2] || 'http://127.0.0.1:48383/';
const MODEL = process.argv[3] || 'pro2';
const OUT = process.argv[4] || '.';

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// per model: the input to probe past the engine's 32, how to reach it on bay A, minimum bound controls
const CFG = {
  pro2:  { name: 'PRO2', inputs: 56, minBound: 380, probe: 49, scrollA: 3 },      // A+B: 16 wide, page 4 = 49-56
  pro2c: { name: 'PRO2C', inputs: 56, minBound: 340, probe: 49, scrollA: -1 },    // 8 wide, page 7 = 49-56
  prox:  { name: 'PRO X', inputs: 144, minBound: 1090, probe: 129, scrollA: -1 },  // A+B: 16 wide, page 9 = 129-144
  // bayA: the input bay; probe: an input past the engine's 32 and how to reach it (scroll steps, or a layer key)
  xl8:   { name: 'XL8', inputs: 96, minBound: 1450, bayA: 'A', probe: 49, scrollA: 2 },             // A+B+C: 24 wide, page 3 = 49-72
  x32:   { name: 'X32', inputs: 32, minBound: 250, bayA: 'I', family: 'x32', sends: true, eq: true, layer2: ['ch2', 'Ch 17'] },
  m32:   { name: 'M32', inputs: 32, minBound: 250, bayA: 'I', family: 'x32', sends: true, eq: true, layer2: ['ch2', 'Ch 17'] },
  x32c:  { name: 'X32 COMPACT', inputs: 32, minBound: 185, bayA: 'I', family: 'x32', eq: true, layer2: ['ch4', 'Ch 25'] },
  m32r:  { name: 'M32R', inputs: 32, minBound: 178, bayA: 'I', family: 'x32', eq: true, layer2: ['ch4', 'Ch 25'] },
  x32r:  { name: 'X32 RACK', inputs: 32, minBound: 30, bayA: null, family: 'x32' },
  wing:  { name: 'WING', inputs: 40, minBound: 260, bayA: 'L', probe: 37, layerA: 'auxin', family: 'wing' },
  wingc: { name: 'WING COMPACT', inputs: 40, minBound: 120, bayA: 'L', probe: 37, layerA: 'auxin', family: 'wing' },
  wingr: { name: 'WING RACK', inputs: 40, minBound: 30, bayA: 'R', probe: 37, scrollA: 9, family: 'wing' },
}[MODEL];
const ALL_MODELS = ['pro1', 'pro2', 'pro2c', 'prox', 'xl8', 'x32', 'x32c', 'x32r', 'm32', 'm32r', 'wing', 'wingc', 'wingr'];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1900, height: 1250 } });
  const A = await ctx.newPage();
  const B = await ctx.newPage();
  const errors = [];
  for (const p of [A, B]) p.on('pageerror', e => errors.push(String(e)));
  const url = BASE + '?model=' + MODEL;
  await A.goto(url, { waitUntil: 'networkidle' });
  await B.goto(url, { waitUntil: 'networkidle' });
  await sleep(2000);
  const status = await A.evaluate(() => document.getElementById('status').textContent);
  check('linked to OMC', status === 'linked to OMC', status);
  if (status !== 'linked to OMC') { await browser.close(); process.exit(2); }

  // ---- load, controls, persistence
  const info = await A.evaluate(() => ({ views: views.length, n: model.controls.length, bound: model.controls.filter(c => c.bind).length,
    head: document.querySelector('header .model').textContent, inputs: INPUTS, stored: localStorage.getItem('surface-model'),
    url: location.search, models: [...document.getElementById('modelsel').options].map(o => o.value) }));
  check(`${CFG.name} loaded: every control drawn`, info.views === info.n && info.n > 0, `${info.views} / ${info.n}`);
  check(`bound controls >= ${CFG.minBound}`, info.bound >= CFG.minBound, `${info.bound} of ${info.n}`);
  check('header names the model', info.head.startsWith(CFG.name + (MODEL === 'pro2c' ? ' (derived)' : '')), info.head);
  check(`${CFG.inputs} inputs`, info.inputs === CFG.inputs, String(info.inputs));
  check('model choice kept: URL + localStorage', info.stored === MODEL && info.url.includes('model=' + MODEL), `${info.stored} ${info.url}`);
  check('model selector lists every model', ALL_MODELS.every(m => info.models.includes(m)), info.models.join(','));
  const bad = await A.evaluate(() => {
    const out = [];
    for (const v of views) { try { resolve(v.c.bind); isOn(v.c); describe(v.c); } catch (e) { out.push(v.c.id + ': ' + e); } }
    return out;
  });
  check('every binding resolves, lights and describes without error', bad.length === 0, bad.slice(0, 3).join('; '));

  const valB = (k) => B.evaluate((k) => S.values.get(k), k);
  const until = async (fn, ms = 4000) => { for (let t = 0; t < ms / 100; t++) { if (await fn()) return true; await sleep(100); } return !!(await fn()); };
  const find = (pred) => A.evaluate((src) => {
    const f = eval(src);
    const k = views.findIndex(v => v.c.bind && f(v.c));
    if (k < 0) return null;
    const box = views[k].el.getBoundingClientRect();
    return { k, id: views[k].c.id, x: box.x + box.width / 2, y: box.y + box.height / 2, w: box.width, h: box.height };
  }, pred);
  const key = async (pred) => { const c = await find(pred); if (!c) throw new Error('no control ' + pred); await A.mouse.click(c.x, c.y); await sleep(300); return c; };
  // what a strip shows: its LCD's lines, or (a surface without strip LCDs: the XL8) the channel's name
  const lcd = (bay, slot) => A.evaluate(([bay, slot]) => { const v = views.find(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.bank === bay && v.c.bind.slot === slot);
    return v ? [...v.el.querySelectorAll('text')].map(t => t.textContent) : [chName(stripChannel(bay, slot))]; }, [bay, slot]);
  const dragFader = async (bay, slot) => {
    const f = await find(`(c) => c.type === 'fader' && c.bind.kind === 'strip' && c.bind.bank === '${bay}' && c.bind.slot === ${slot}`);
    if (!f) {
      // a level knob in place of the fader (WING RACK): drag it up
      const k = await find(`(c) => c.bind.kind === 'strip' && c.bind.p === 'fader' && c.bind.bank === '${bay}' && c.bind.slot === ${slot}`);
      await A.mouse.move(k.x, k.y); await A.mouse.down(); await A.mouse.move(k.x, k.y - 80, { steps: 8 }); await A.mouse.up();
      return A.evaluate((i) => resolve(views[i].c.bind), k.k);
    }
    const t0 = await A.evaluate((k) => { const r = resolve(views[k].c.bind); return faderT(val(r.p, r.i, -100)); }, f.k);
    const pxmm = await A.evaluate(() => svg.getBoundingClientRect().height / model.height);
    const capY = f.y - f.h / 2 + (2 + 4.1 + t0 * 99.4) * pxmm;
    await A.mouse.move(f.x, capY); await A.mouse.down(); await A.mouse.move(f.x, capY + (t0 > 0.5 ? -70 : 70), { steps: 6 }); await A.mouse.up();
    return A.evaluate((k) => resolve(views[k].c.bind), f.k);
  };
  const roundTrip = async (label, bay, slot, ch) => {
    // fader and MUTE key of the strip at (bay, slot), expected on channel ch (1-based)
    const model = ch > 32;
    const fp = model ? 'mch_fader' : 'fader', mp = model ? 'mch_mute' : 'ch_mute';
    const f0 = (await valB(`${fp}/${ch}`)) ?? -100;
    const r = await dragFader(bay, slot);
    check(`${label}: fader -> ${fp}/${ch} on OMC, back on page B`, r && r.p === fp && r.i === ch &&
          await until(async () => { const v = await valB(`${fp}/${ch}`); return v !== undefined && Math.abs(v - f0) > 0.5; }),
          `${r && r.p}/${r && r.i}: ${f0} -> ${await valB(`${fp}/${ch}`)}`);
    await A.evaluate(([p, i, v]) => send('set', p, i, v), [fp, ch, f0]);
    const m0 = (await valB(`${mp}/${ch}`)) ?? 0;
    await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_mute' && c.bind.bank === '${bay}' && c.bind.slot === ${slot}`);
    check(`${label}: MUTE key -> ${mp}/${ch} on OMC, back on page B`,
          await until(async () => Math.abs(((await valB(`${mp}/${ch}`)) ?? 0) - (m0 >= 0.5 ? 0 : 1)) < 1e-3), `${m0} -> ${await valB(`${mp}/${ch}`)}`);
    await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_mute' && c.bind.bank === '${bay}' && c.bind.slot === ${slot}`);
    await until(async () => Math.abs(((await valB(`${mp}/${ch}`)) ?? 0) - m0) < 1e-3);
  };
  const bayA = CFG.bayA !== undefined ? CFG.bayA : MODEL === 'prox' ? 'A' : (MODEL === 'pro2c' ? 'B' : 'A');   // the PRO2C's only channel bay is the PRO2's bay B

  if (bayA === null) {
    // ---- no faders (X32 RACK): the selected channel's MUTE key and the channel select knob
    await A.evaluate(() => select(0));
    const m0 = (await valB('ch_mute/1')) ?? 0;
    await key(`(c) => c.bind.kind === 'sel' && c.bind.p === 'ch_mute'`);
    check('selected-channel MUTE key -> ch_mute/1, back on page B', await until(async () => Math.abs(((await valB('ch_mute/1')) ?? 0) - (m0 >= 0.5 ? 0 : 1)) < 1e-3));
    await key(`(c) => c.bind.kind === 'sel' && c.bind.p === 'ch_mute'`);
    const main = await A.evaluate(() => resolve(views.find(v => v.c.bind && v.c.bind.kind === 'fixed' && v.c.bind.p === 'fader').c.bind));
    check('main level knob -> fader/81 (main LR)', main && main.p === 'fader' && main.i === 81, JSON.stringify(main));
  } else {
  // ---- engine channels 1 and 2
  check('bay A starts on input 1', (await lcd(bayA, 0))[0] === 'Ch 1', JSON.stringify(await lcd(bayA, 0)));
  await roundTrip('input 1', bayA, 0, 1);
  // MUTE of input 2 (slot 1) too, as the extend-40 test does on the PRO1
  {
    const m0 = (await valB('ch_mute/2')) ?? 0;
    await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_mute' && c.bind.bank === '${bayA}' && c.bind.slot === 1`);
    check('input 2 MUTE key -> ch_mute/2, back on page B', await until(async () => Math.abs(((await valB('ch_mute/2')) ?? 0) - (m0 >= 0.5 ? 0 : 1)) < 1e-3));
    await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_mute' && c.bind.bank === '${bayA}' && c.bind.slot === 1`);
  }

  // ---- a desk-model input past the engine's 32
  if (CFG.probe) {
    if (CFG.layerA) await key(`(c) => c.bind.kind === 'layer' && c.bind.bank === '${bayA}' && c.bind.value === '${CFG.layerA}'`);
    const steps = Math.abs(CFG.scrollA || 0), dir = Math.sign(CFG.scrollA || 0);
    for (let s = 0; s < steps; s++) await key(`(c) => c.bind.kind === 'scroll' && c.bind.bank === '${bayA}' && c.bind.step === ${dir}`);
    await sleep(500);
    check(`bay A shows input ${CFG.probe}`, (await lcd(bayA, 0))[0] === 'Ch ' + CFG.probe, JSON.stringify(await lcd(bayA, 0)));
    await roundTrip(`input ${CFG.probe} (desk model)`, bayA, 0, CFG.probe);
  }
  }
  if (MODEL === 'prox') {
    // input 144, the last one: bay B's last strip in the continuous layout (OMC mirrors 1..144)
    check('bay B slot 4 shows input 144', (await lcd('B', 3))[0] === 'Ch 144', JSON.stringify(await lcd('B', 3)));
    await roundTrip('input 144 (desk model)', 'B', 3, 144);
  }
  await A.evaluate(() => { setLayout(model.surface); watch(); refresh(); });

  // ---- model keys
  if (MODEL === 'pro2' || MODEL === 'pro2c') {
    await key(`(c) => c.bind.kind === 'bay' && c.bind.value === 'extend'`);
    const want = MODEL === 'pro2' ? 'Ch 17' : 'Ch 9';
    check(`EXTEND: the mix bay continues the channel bays (${want})`, (await lcd('M', 0))[0] === want, JSON.stringify(await lcd('M', 0)));
    await key(`(c) => c.bind.kind === 'bay' && c.bind.value === 'extend'`);
    check('EXTEND off: the mix bay is back on VCA 1', (await lcd('M', 0))[0] === 'DCA 1', JSON.stringify(await lcd('M', 0)));
    // the mix sends knob of row 3 edits the selected channel's send to mix 3
    await A.evaluate(() => select(0));
    const r = await A.evaluate(() => resolve(views.find(v => v.c.bind && v.c.bind.kind === 'sendlvl' && v.c.bind.bus === 3).c.bind));
    check('mix sends row 3 knob -> ch_send03 of the selected channel', r && r.p === 'ch_send03' && r.i === 1, JSON.stringify(r));
  }
  if (CFG.family === 'x32') {
    await A.evaluate(() => select(0));
    if (CFG.sends) {
      // bus sends: knob 2 edits the send to bus 2, the 5-8 bank key moves it to bus 6
      const kn = () => A.evaluate(() => resolve(views.find(v => v.c.bind && v.c.bind.kind === 'sendlvl' && v.c.bind.bus === 2).c.bind));
      let r = await kn();
      check('bus sends knob 2 -> ch_send02 of the selected channel', r && r.p === 'ch_send02' && r.i === 1, JSON.stringify(r));
      await key(`(c) => c.bind.kind === 'sendpage' && c.bind.value === 1`);
      r = await kn();
      check('bank key 5-8: knob 2 -> ch_send06', r && r.p === 'ch_send06', JSON.stringify(r));
    }
    if (CFG.eq) {
      // EQ band keys: LOW MID -> band 2, the gain knob edits ch_eq_g2
      await key(`(c) => c.bind.kind === 'bandsel' && c.bind.value === 2`);
      const r = await A.evaluate(() => resolve(views.find(v => v.c.bind && v.c.bind.kind === 'band' && v.c.bind.p === 'ch_eq_g').c.bind));
      check('EQ band key LOW MID: the EQ gain knob -> ch_eq_g2', r && r.p === 'ch_eq_g2', JSON.stringify(r));
    }
    if (CFG.layer2) {
      await key(`(c) => c.bind.kind === 'layer' && c.bind.bank === 'I' && c.bind.value === '${CFG.layer2[0]}'`);
      check(`layer key ${CFG.layer2[0]}: the input bank starts on ${CFG.layer2[1]}`, (await lcd('I', 0))[0] === CFG.layer2[1], JSON.stringify(await lcd('I', 0)));
      await key(`(c) => c.bind.kind === 'layer' && c.bind.bank === 'G' && c.bind.value === 'bus1'`);
      check('group layer BUS 1-8: the group bank shows Bus 1', (await lcd('G', 0))[0] === 'Bus 1', JSON.stringify(await lcd('G', 0)));
    }
  }
  if (CFG.family === 'wing' && MODEL !== 'wingr') {
    await key(`(c) => c.bind.kind === 'layer' && c.bind.bank === 'L' && c.bind.value === 'in2'`);
    check('layer key 13-24: the left section starts on Ch 13', (await lcd('L', 0))[0] === 'Ch 13', JSON.stringify(await lcd('L', 0)));
  }
  if (MODEL === 'wing') {
    // the 4-channel section: GATE chooses the parameter, knob 1 edits the gate threshold of the right section's strip 1
    await key(`(c) => c.bind.kind === 'qmode' && c.bind.value === 'gate'`);
    const r = await A.evaluate(() => resolve(views.find(v => v.c.bind && v.c.bind.kind === 'qknob' && v.c.bind.slot === 0).c.bind));
    check('4-channel section GATE: knob 1 -> ch_gate_thr of the right section\'s strip 1', r && r.p === 'ch_gate_thr' && r.ch === 80, JSON.stringify(r));
  }
  if (MODEL === 'xl8') {
    await A.evaluate(() => { setLayout(model.surface); watch(); refresh(); });
    await key(`(c) => c.bind.kind === 'stripcmd' && c.bind.bank === 'A' && c.bind.slot === 2 && c.bind.value === 22`);
    check('strip 3 comp section key -> sel 2 on OMC (page B)', await until(async () => (await valB('sel/1')) === 2));
    for (const k of ['7', '3', 'E']) await key(`(c) => c.bind.kind === 'keypad' && c.bind.bank === 'A' && c.bind.key === '${k}'`);
    check('keypad 73 ENTER -> msel 73 on OMC (page B)', await until(async () => (await valB('msel/1')) === 73), String(await valB('msel/1')));
    await A.evaluate(() => select(0));
  }
  if (MODEL === 'prox') {
    // a strip's compressor section key selects that channel and opens the section on the touch UI
    await key(`(c) => c.bind.kind === 'stripcmd' && c.bind.bank === 'A' && c.bind.slot === 2 && c.bind.value === 22`);
    check('strip 3 comp section key -> sel 2 on OMC (page B)', await until(async () => (await valB('sel/1')) === 2));
    // keypad: 1 3 7 ENTER selects input 137 (desk model) and pages bay A to it
    for (const k of ['1', '3', '7', 'E']) await key(`(c) => c.bind.kind === 'keypad' && c.bind.bank === 'A' && c.bind.key === '${k}'`);
    check('keypad 137 ENTER -> msel 137 on OMC (page B)', await until(async () => (await valB('msel/1')) === 137), String(await valB('msel/1')));
    check('keypad paged bay A to input 137', JSON.stringify(await A.evaluate(() => [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15].map(k => stripChannel(k < 12 ? 'A' : 'B', k < 12 ? k : k - 12) - MODEL + 1))).includes('137'));
    await A.evaluate(() => select(0));
  }

  // ---- banks of user-defined keys (OMC user-keys.h): X32 / M32 SET A / B / C, WING PRESETS UP / DOWN,
  // WING COMPACT's 16 custom keys
  const ukeys = await A.evaluate(() => views.filter(v => v.c.bind && v.c.bind.kind === 'ukey').map(v => v.c.bind.i).sort((a, b) => a - b));
  const sets = await A.evaluate(() => views.filter(v => v.c.bind && v.c.bind.kind === 'ukbank').length);
  const steps = await A.evaluate(() => views.filter(v => v.c.bind && v.c.bind.kind === 'ukstep').length);
  if (MODEL === 'wingc') check('WING COMPACT: custom keys CC 1-16 are user keys 1-16', ukeys.join(',') === [...Array(16).keys()].map(k => k + 1).join(','), ukeys.join(','));
  if (['x32', 'm32', 'x32c', 'm32r', 'wing'].includes(MODEL)) check('assign / custom keys 1-8 are user keys 1-8', ukeys.join(',') === '1,2,3,4,5,6,7,8', ukeys.join(','));
  const bankB = async () => Math.round((await valB('ukey_bank/1')) ?? 0);
  if (sets === 3) {
    await key(`(c) => c.bind.kind === 'ukbank' && c.bind.value === 2`);
    check('SET B -> user-key bank 2 on OMC, back on page B', await until(async () => (await bankB()) === 2), String(await bankB()));
    check('SET B lit, SET A dark', await A.evaluate(() => { const f = (n) => isOn(views.find(v => v.c.bind && v.c.bind.kind === 'ukbank' && v.c.bind.value === n).c); return f(2) && !f(1); }));
    await key(`(c) => c.bind.kind === 'ukbank' && c.bind.value === 1`);
    check('SET A -> bank 1', await until(async () => (await bankB()) === 1), String(await bankB()));
  }
  if (steps === 2) {
    const b0 = await bankB(), n = Math.round((await valB('ukey_bank/2')) ?? 0);
    await key(`(c) => c.bind.kind === 'ukstep' && c.bind.value === 1`);
    check('PRESETS UP -> the next user-key bank', n > 1 && await until(async () => (await bankB()) === b0 % n + 1), `${b0} -> ${await bankB()} of ${n}`);
    await key(`(c) => c.bind.kind === 'ukstep' && c.bind.value === -1`);
    check('PRESETS DOWN -> back', await until(async () => (await bankB()) === b0), String(await bankB()));
  }
  if (ukeys.length) {
    // the label OMC publishes for the key reaches the tooltip (an empty bank: "not assigned")
    const d = await A.evaluate(() => describe(views.find(v => v.c.bind && v.c.bind.kind === 'ukey' && v.c.bind.i === Math.max(...views.filter(w => w.c.bind && w.c.bind.kind === 'ukey').map(w => w.c.bind.i))).c));
    check('user key tooltip names its bank and action', /user key \d+ of bank \S+: /.test(d), d);
  }

  await A.screenshot({ path: `${OUT}/surface-${MODEL}.png` });

  check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  const failed = results.filter(r => !r.ok).length;
  console.log(`${MODEL}: ${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
})();
