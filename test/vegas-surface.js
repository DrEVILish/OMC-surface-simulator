// Vegas mode through the PRO1 web surface (docs/45): demo patterns in sync with OMC's pattern clock,
// the full hardware test driven from the page, and the page back on the live state afterwards.
//
// Needs an OMC simulator started with OMC_VEGAS_REMOTE=1 (the test starts Vegas over /vegas/start;
// on a console Vegas is entered on the touch UI) and test/serve-local.py (or the console's nginx
// + bridge). Bind everything to 127.0.0.1.
//
// usage: node test/vegas-surface.js http://127.0.0.1:48080/ [out-dir]     (needs playwright)
//        STUCK=<control id> makes that fader's emulated motor stick (the report must fail it)
const { chromium } = require('playwright');
const fs = require('fs');
const URL = process.argv[2] || 'http://127.0.0.1:48080/';
const OUT = process.argv[3] || '.';

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok, info }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(URL + (process.env.STUCK ? '?vegasStuck=' + process.env.STUCK : ''), { waitUntil: 'networkidle' });
  await sleep(2000);
  check('page linked to OMC', (await page.evaluate(() => document.getElementById('status').textContent)) === 'linked to OMC');

  const vegas = (a, f, v) => page.evaluate(([a, f, v]) => S.ws.send(JSON.stringify({ op: 'vegas', a, f, v })), [a, f, v]);
  const live = () => page.evaluate(() => {
    const o = {};
    for (const [k, v] of S.values) if (/^(fader|ch_mute|ch_solo|ch_gain|ch_name)\//.test(k)) o[k] = v;
    const caps = views.filter(v => v.c.type === 'fader').map(v => v.el.querySelector('g').getAttribute('transform'));
    return { o, caps };
  });
  const before = await live();

  // ---- demo: frames arrive from OMC and every control shows render(pattern, frame)
  await vegas('start', 'iif', [1, 2, 1.0]);   // demo, rainbow, 1x
  await sleep(1500);
  const demo = await page.evaluate(() => ({ mode: Vegas.state.mode, banner: (document.getElementById('vegas') || {}).textContent || '' }));
  check('demo running on the page', demo.mode === 1, demo.banner);
  // sync: record the frame numbers the page receives for one second
  const frames = await page.evaluate(async () => {
    const got = [];
    const ws = S.ws;
    const h = (ev) => { const m = JSON.parse(ev.data); if (m.vegas && m.vegas[0] === '/vegas/frame') got.push([performance.now(), m.vegas[1][1]]); };
    ws.addEventListener('message', h);
    await new Promise(r => setTimeout(r, 1000));
    ws.removeEventListener('message', h);
    return got;
  });
  const n = frames.length, span = n > 1 ? frames[n - 1][1] - frames[0][1] : 0;
  check('pattern clock ~25 frames/s at 1x', n >= 20 && span >= 20 && span <= 28, `${n} messages, frames ${frames[0] && frames[0][1]}..${frames[n - 1] && frames[n - 1][1]}`);
  // the drawn state equals render() of the frame the page drew last
  const drawn = await page.evaluate(() => {
    const p = Vegas.state.pattern, f = Vegas.state.frame;
    let bad = 0, n = 0;
    for (const v of views) {
      if (v.c.type !== 'fader') continue;
      const r = Vegas.render(p, f, 0, v.c.x / model.width, v.c.y / model.height);
      const top = v.c.top + 4.1, bottom = v.c.bottom + (v.c.h < 90 ? 9.65 : 10.4);
      const want = top + (1 - r.level) * (bottom - top);
      const got = parseFloat(v.el.querySelector('g').getAttribute('transform').match(/translate\(0 ([-\d.]+)\)/)[1]);
      n++; if (Math.abs(got - want) > 0.01) bad++;
    }
    return { n, bad, f };
  });
  check('every fader cap at render(pattern, frame)', drawn.n === 18 && drawn.bad === 0, `${drawn.n} faders, frame ${drawn.f}`);
  await page.screenshot({ path: OUT + '/vegas-web-demo.png' });

  // a touch on any control stops the demo, and the page goes back to the live values
  const knob = await page.evaluate(() => { const v = views.find(v => v.c.type === 'button'); const r = v.el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; });
  await page.mouse.click(knob[0], knob[1]);
  await sleep(1200);
  check('touch on a key ends the demo', (await page.evaluate(() => Vegas.state.mode)) === 0);
  const after = await live();
  check('live values unchanged by the demo', JSON.stringify(after.o) === JSON.stringify(before.o), Object.keys(after.o).length + ' values');
  check('fader caps back where they were', JSON.stringify(after.caps) === JSON.stringify(before.caps));

  // ---- hardware test, driven from the page
  await vegas('start', 'iif', [2, 0, 1.0]);
  const step = () => page.evaluate(() => (document.getElementById('vegas') || {}).textContent || '');
  const op = (k) => vegas('op', 's', [k]);
  const waitFor = async (re, ms = 15000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { const s = await step(); if (re.test(s)) return s; await sleep(100); } return await step(); };
  let s = await waitFor(/touch each fader/i, 20000);   // motors (emulated, with echo) run first
  check('fader motor step finished with read-back', /touch each fader/i.test(s), s.slice(0, 80));
  const faders = await page.evaluate(() => views.filter(v => v.c.type === 'fader').map(v => { const r = v.el.querySelector('g').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }));
  for (const [x, y] of faders.slice(0, 16)) { await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.up(); await sleep(40); }
  await op('next');   // two masters left untouched on purpose
  s = await waitFor(/lit red/i);
  check('LED colour step', /lit red/i.test(s), s.slice(0, 80));
  await page.screenshot({ path: OUT + '/vegas-web-diag-red.png' });
  for (let i = 0; i < 4; i++) { await op('pass'); await sleep(150); }
  s = await waitFor(/walk/i);
  await sleep(1000);
  await op('next');
  s = await waitFor(/Press every key/i);
  check('key step', /Press every key/i.test(s));
  const keys = await page.evaluate(() => views.filter(v => ['button', 'ledbutton', 'round', 'arrow', 'lcd'].includes(v.c.type)).map(v => { const r = v.el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }));
  for (const [x, y] of keys.slice(0, 40)) { await page.mouse.click(x, y); await sleep(15); }
  await sleep(300);
  await page.screenshot({ path: OUT + '/vegas-web-diag-keys.png' });
  await op('next');
  s = await waitFor(/Turn every encoder/i);
  check('encoder step', /Turn every encoder/i.test(s));
  const encs = await page.evaluate(() => views.filter(v => ['knob', 'pot'].includes(v.c.type)).map(v => { const r = v.el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }));
  for (const [x, y] of encs.slice(0, 10)) { await page.mouse.move(x, y); await page.mouse.wheel(0, -120); await sleep(30); }
  await page.mouse.move(encs[10][0], encs[10][1]); await page.mouse.wheel(0, 120);   // one turned the wrong way
  await sleep(300);
  await op('next');
  s = await waitFor(/test card/i);
  for (let i = 0; i < 7; i++) { await op('next'); await sleep(80); }
  await op('pass');
  s = await waitFor(/Meters run/i);
  await sleep(800);
  await page.screenshot({ path: OUT + '/vegas-web-diag-meters.png' });
  await op('pass');
  s = await waitFor(/complete/i);
  check('test complete', /complete/i.test(s), s.slice(0, 60));
  await op('stop');
  await sleep(1500);
  check('page back on the live state after the test', (await page.evaluate(() => Vegas.state.mode)) === 0);
  const end = await live();
  check('live values unchanged by the test', JSON.stringify(end.o) === JSON.stringify(before.o));
  check('fader caps restored after the test', JSON.stringify(end.caps) === JSON.stringify(before.caps));
  check('no page errors', errors.length === 0, errors.join(' | '));
  await page.screenshot({ path: OUT + '/vegas-web-restored.png' });
  await browser.close();
  const failed = results.filter(r => !r.ok).length;
  fs.writeFileSync(OUT + '/vegas-surface-result.json', JSON.stringify({ total: results.length, failed, results }, null, 1));
  process.exit(failed ? 1 : 0);
})();
