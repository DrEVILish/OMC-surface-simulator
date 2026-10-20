// The PRO1 web surface's fader flip shared with OMC (OpenProSeries docs/55 section 9).
//
//   Page A operates the surface; page B only watches OMC's change feed.
//
//   Checks: a sends key for AUX 2 -> OMC sof = 2 (seen on page B); the input faders resolve to ch_send02;
//   sof set from outside (as the touch UI / the console's flip key / OSC do) -> the faders follow
//   (ch_send03), sof = 0 -> the faders are channel faders again; flip_pre/1 = 1 -> the LCD of input 1
//   shows PRE; bus_prepost/2 = 1 (all contributions of aux 2 pre-fade) -> OMC takes it (back to 0) and
//   flip_pre follows on the flipped bus (post, then pre as the template had it). State is put back.
//
// usage: node test/flip-sync.js http://127.0.0.1:48180/   (needs playwright; OMC simulator +
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
  await B.evaluate(() => {
    const it = [['sof', 1], ['bus_prepost', 2]];
    for (let n = 1; n <= 4; n++) it.push(['flip_pre', n]);
    S.ws.send(JSON.stringify({ op: 'watch', items: it }));
  });
  const valB = (k) => B.evaluate((k) => S.values.get(k), k);
  const until = async (fn, ms = 3000) => { for (let t = 0; t < ms / 100; t++) { if (await fn()) return true; await sleep(100); } return !!(await fn()); };
  const find = (pred) => A.evaluate((src) => {
    const f = eval(src);
    const k = views.findIndex(v => v.c.bind && f(v.c));
    if (k < 0) return null;
    const box = views[k].el.getBoundingClientRect();
    return { k, x: box.x + box.width / 2, y: box.y + box.height / 2 };
  }, pred);
  const key = async (pred) => { const c = await find(pred); if (!c) return null; await A.mouse.click(c.x, c.y); await sleep(300); return c; };
  const fader1 = () => A.evaluate(() => {
    const v = views.find(v => v.c.type === 'fader' && v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.bank === 'L' && v.c.bind.slot === 0);
    const r = v && resolve(v.c.bind);
    return r ? r.p : null;
  });
  const lcd1 = () => A.evaluate(() => {
    const v = views.find(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip' && v.c.bind.bank === 'L' && v.c.bind.slot === 0);
    return v ? [...v.el.querySelectorAll('text')].map(t => t.textContent) : [];
  });

  // a sends key (AUX 2) on the surface -> OMC's flip
  const k2 = await key(`(c) => c.bind.kind === 'sends' && c.bind.bus === 2`);
  check('AUX 2 sends key found', !!k2);
  check('AUX 2 sends on faders -> sof = 2 on OMC', await until(async () => Math.round((await valB('sof/1')) ?? 0) === 2), String(await valB('sof/1')));
  check('input fader 1 -> ch_send02', (await fader1()) === 'ch_send02', await fader1());

  // from outside (touch UI / flip key / OSC): sof = 3, then off
  await B.evaluate(() => send('set', 'sof', 1, 3));
  check('sof = 3 from outside -> fader 1 is ch_send03', await until(async () => (await fader1()) === 'ch_send03'), await fader1());
  // the flipped send's pre / post on the LCD
  await B.evaluate(() => send('set', 'flip_pre', 1, 1));
  check('flip_pre/1 = 1 -> input 1 LCD shows PRE', await until(async () => (await lcd1()).join(' ').includes('PRE')), JSON.stringify(await lcd1()));
  await B.evaluate(() => send('set', 'flip_pre', 1, 0));
  check('flip_pre/1 = 0 -> PRE goes', await until(async () => !(await lcd1()).join(' ').includes('PRE')), JSON.stringify(await lcd1()));
  // set all contributions of aux 3 (the flipped bus) pre-fade: OMC consumes the one-shot, flip_pre follows
  // (aux 3 starts pre-fade on the PRO1 template: post first, then pre again, as it was)
  await B.evaluate(() => send('set', 'bus_prepost', 3, 2));
  check('bus_prepost/3 = 2 -> every input post on the flipped bus (flip_pre/2 = 0)', await until(async () => (await valB('flip_pre/2')) === 0), String(await valB('flip_pre/2')));
  await B.evaluate(() => send('set', 'bus_prepost', 3, 1));
  check('bus_prepost/3 = 1 -> pre again (flip_pre/2 = 1)', await until(async () => (await valB('flip_pre/2')) >= 0.5), String(await valB('flip_pre/2')));

  await B.evaluate(() => send('set', 'sof', 1, 0));
  check('sof = 0 -> channel faders', await until(async () => (await fader1()) === 'fader'), await fader1());
  check('no page errors', errors.length === 0, errors.join(' | '));
  const fail = results.filter(r => !r.ok).length;
  console.log(`${results.length - fail} / ${results.length} passed`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
