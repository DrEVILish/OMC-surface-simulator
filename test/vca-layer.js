// The PRO1 web surface's VCA layer on OMC's desk-model VCA masters (OpenProSeries docs/55 section 6).
//
//   Page A operates the surface with the mouse; page B only watches, so it learns values from OMC's
//   change feed alone (the bridge does not echo).
//
//   Checks: the right bank's VCA key shows VCA 1-8 on the LCDs (AREA A); fader 1 -> vca_level/1, MUTE 2
//   -> vca_mute/2 (LCD MUTE), both seen on page B; vca_area/3 set from outside -> the LCD shows AREA B;
//   SOLO 4 -> vca_solo/4 reaches OMC, which drops it again (VCA 4 has no members); LCD select of VCA 3
//   (area B) -> ui_cmd 70 + 2 and the right bank goes to the touch layer, of VCA 1 (area A) -> the left.
//   State is put back.
//
// usage: node test/vca-layer.js http://127.0.0.1:48180/   (needs playwright; OMC simulator +
//        test/serve-local.py on 127.0.0.1)
const { chromium } = require('playwright');
const URL = process.argv[2] || 'http://127.0.0.1:48180/';

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

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
  // page B watches the VCA parameters
  await B.evaluate(() => {
    const it = [];
    for (let k = 1; k <= 8; k++) for (const p of ['vca_level', 'vca_mute', 'vca_solo', 'vca_area']) it.push([p, k]);
    it.push(['ui_cmd', 1]);
    S.ws.send(JSON.stringify({ op: 'watch', items: it }));
  });
  const valB = (k) => B.evaluate((k) => S.values.get(k), k);
  const until = async (fn, ms = 3000) => { for (let t = 0; t < ms / 100; t++) { if (await fn()) return true; await sleep(100); } return !!(await fn()); };
  const find = (pred) => A.evaluate((src) => {
    const f = eval(src);
    const k = views.findIndex(v => v.c.bind && f(v.c));
    if (k < 0) return null;
    const box = views[k].el.getBoundingClientRect();
    return { k, x: box.x + box.width / 2, y: box.y + box.height / 2, w: box.width, h: box.height };
  }, pred);
  const key = async (pred) => { const c = await find(pred); await A.mouse.click(c.x, c.y); await sleep(300); return c; };
  const lcds = (bank) => A.evaluate((bank) => views.filter(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.bank === bank)
    .sort((a, b) => a.c.bind.slot - b.c.bind.slot).map(v => [...v.el.querySelectorAll('text')].map(t => t.textContent)), bank);

  await key(`(c) => c.bind.kind === 'layer' && c.bind.bank === 'R' && c.bind.value === 'vca'`);
  await sleep(500);
  let l = await lcds('R');
  check('VCA layer: LCDs show VCA 1-8, area A', l.map(t => t[0]).join() === [1, 2, 3, 4, 5, 6, 7, 8].map(k => 'VCA ' + k).join() && l[0][1] === 'AREA A',
        JSON.stringify(l[0]));

  // fader 1 -> vca_level/1
  const fader = await find(`(c) => c.type === 'fader' && c.bind.kind === 'strip' && c.bind.bank === 'R' && c.bind.slot === 0`);
  const r0 = await A.evaluate((k) => resolve(views[k].c.bind), fader.k);
  const f0 = (await valB('vca_level/1')) ?? 0;
  const t0 = await A.evaluate((k) => { const r = resolve(views[k].c.bind); return faderT(val(r.p, r.i, 0)); }, fader.k);
  const pxmm = await A.evaluate(() => svg.getBoundingClientRect().height / model.height);
  const capY = fader.y - fader.h / 2 + (2 + 4.1 + t0 * 99.4) * pxmm;
  await A.mouse.move(fader.x, capY); await A.mouse.down(); await A.mouse.move(fader.x, capY + 60, { steps: 6 }); await A.mouse.up();
  check('VCA 1 fader -> vca_level/1 on OMC', r0.p === 'vca_level' && r0.i === 1 &&
        await until(async () => Math.abs(((await valB('vca_level/1')) ?? 0) - f0) > 0.5), `${f0} -> ${await valB('vca_level/1')}`);
  await A.evaluate((v) => send('set', 'vca_level', 1, v), f0);

  // MUTE 2
  await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_mute' && c.bind.bank === 'R' && c.bind.slot === 1`);
  check('VCA 2 MUTE -> vca_mute/2 on OMC', await until(async () => (await valB('vca_mute/2')) >= 0.5));
  check('VCA 2 LCD shows MUTE', await until(async () => (await lcds('R'))[1][2] === 'MUTE'));
  await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_mute' && c.bind.bank === 'R' && c.bind.slot === 1`);
  check('VCA 2 MUTE off again', await until(async () => !((await valB('vca_mute/2')) >= 0.5)));

  // area B on VCA 3 (as the touch UI or OSC sets it)
  await B.evaluate(() => send('set', 'vca_area', 3, 1));
  check('vca_area/3 = 1 -> VCA 3 LCD shows AREA B', await until(async () => (await lcds('R'))[2][1] === 'AREA B'));

  // SOLO 4: OMC takes it and drops it (no members)
  await key(`(c) => c.bind.kind === 'strip' && c.bind.p === 'ch_solo' && c.bind.bank === 'R' && c.bind.slot === 3`);
  const soloRes = await A.evaluate(() => resolve(views.find(v => v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.p === 'ch_solo' && v.c.bind.bank === 'R' && v.c.bind.slot === 3).c.bind));
  check('VCA 4 SOLO resolves to vca_solo/4; OMC drops it (no members)', soloRes.p === 'vca_solo' && soloRes.i === 4 &&
        await until(async () => (await valB('vca_solo/4')) === 0));

  // LCD select spills into the VCA's area
  await key(`(c) => c.type === 'lcd' && c.bind.kind === 'strip' && c.bind.bank === 'R' && c.bind.slot === 2`);
  let st = await A.evaluate(() => ({ ...S.layer }));
  check('VCA 3 select (area B) -> right bank on the touch layer', st.R === 'touch' && st.L !== 'touch', JSON.stringify(st));
  await key(`(c) => c.bind.kind === 'layer' && c.bind.bank === 'R' && c.bind.value === 'vca'`);
  await key(`(c) => c.type === 'lcd' && c.bind.kind === 'strip' && c.bind.bank === 'R' && c.bind.slot === 0`);
  st = await A.evaluate(() => ({ ...S.layer }));
  check('VCA 1 select (area A) -> left bank on the touch layer', st.L === 'touch' && st.R === 'vca', JSON.stringify(st));

  await B.evaluate(() => send('set', 'vca_area', 3, 0));
  await sleep(300);
  check('no page errors', errors.length === 0, errors.join(' | '));
  const fail = results.filter(r => !r.ok).length;
  console.log(`${results.length - fail} / ${results.length} passed`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
