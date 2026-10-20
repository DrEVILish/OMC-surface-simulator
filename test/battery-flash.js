// The wireless transmitter battery on the web surface LCDs and the low-battery flash (OpenProSeries docs/58 section 12).
//
//   OMC runs with OMC_WIRELESS_DEMO=1: inputs 1..9 are fed by receivers at 100 / 80 / 60 / 40 / 15 %, charging,
//   unknown, RF dropout, TX off. Each strip LCD of a wireless input draws a horizontal 5-segment battery (OSC wbatt):
//   lit segments = ceil(pct / 20), a bolt when charging, the outline only when unknown. Input 5 (15 %) flashes red
//   (ovl_style 1 + 1 + 8) keeping its name; the others do not flash.
//
// usage: NODE_PATH=<playwright> node test/battery-flash.js http://127.0.0.1:48180/
//        (OMC simulator with OMC_WIRELESS_DEMO=1, test/serve-local.py on 127.0.0.1)
const { chromium } = require('playwright');
const URL = process.argv[2] || 'http://127.0.0.1:48180/';

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const A = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
  const errors = [];
  A.on('pageerror', e => errors.push(String(e)));
  await A.goto(URL, { waitUntil: 'networkidle' });
  await sleep(2500);
  const status = await A.evaluate(() => document.getElementById('status').textContent);
  check('linked to OMC', status === 'linked to OMC', status);
  if (status !== 'linked to OMC') { await browser.close(); process.exit(2); }

  const want = { 1: 100, 2: 80, 3: 60, 4: 40, 5: 15, 6: 101, 7: -1 };
  for (const [n, v] of Object.entries(want)) {
    const got = await A.evaluate((i) => Math.round(val('wbatt', i, -9)), +n);
    check('wbatt input ' + n + ' = ' + v, got === v, 'got ' + got);
  }
  check('wbatt of an input with no receiver is -2', await A.evaluate(() => Math.round(val('wbatt', 20, -2))) === -2);

  // the drawn batteries of the input strips on the page: lit segments and the bolt
  const drawn = () => A.evaluate(() => views.filter(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip').map(v => {
    const ch = stripChannel(v.c.bind.bank, v.c.bind.slot);
    const g = [...v.el.querySelectorAll('g')].find(x => x.getAttribute('pointer-events') === 'none');
    if (!g || ch < 0) return null;
    const rects = [...g.querySelectorAll('rect')].slice(2);
    const lit = rects.filter(r => r.style.display !== 'none' && !['#3D4A63', '#D9D4F0'].includes(r.getAttribute('fill'))).length;
    const segs = rects.filter(r => r.style.display !== 'none').length;
    const bolt = g.querySelector('polyline').style.display !== 'none';
    return { input: inputNo(ch) + 1, shown: g.style.display !== 'none', lit, segs, bolt, fill: v.el.querySelector('rect.face').style.fill };
  }).filter(x => x));
  const d = await drawn();
  const of = (n) => d.find(x => x.input === n);
  if (!of(1)) check('input strips 1..8 are on the page', false, JSON.stringify(d.map(x => x.input)));
  else {
    check('100 %: 5 lit', of(1).shown && of(1).lit === 5, JSON.stringify(of(1)));
    check('80 %: 4 lit', of(2).lit === 4, JSON.stringify(of(2)));
    check('60 %: 3 lit', of(3).lit === 3, JSON.stringify(of(3)));
    check('40 %: 2 lit', of(4).lit === 2, JSON.stringify(of(4)));
    check('15 %: 1 lit', of(5).lit === 1, JSON.stringify(of(5)));
    check('charging: the bolt, no segments', of(6).bolt && of(6).segs === 0, JSON.stringify(of(6)));
    check('unknown: the outline only', of(7).shown && of(7).segs === 0 && !of(7).bolt, JSON.stringify(of(7)));
  }

  // the flash: input 5 alternates red / own, input 1 never turns red
  check('OMC flashes input 5 (ovl_style red + flash)', await A.evaluate(() => Math.round(val('ovl_style', 5, 0))) === 10);
  let red5 = false, own5 = false, red1 = false;
  for (let k = 0; k < 16; k++) {
    const s = await drawn();
    const f5 = (s.find(x => x.input === 5) || {}).fill || '', f1 = (s.find(x => x.input === 1) || {}).fill || '';
    if (/226, 72, 59|#e2483b/i.test(f5)) red5 = true; else own5 = true;
    if (/226, 72, 59|#e2483b/i.test(f1)) red1 = true;
    await sleep(125);
  }
  check('input 5 alternates (red / its own look)', red5 && own5);
  check('input 1 does not flash', !red1);
  check('no page errors', errors.length === 0, errors.join(' | '));
  await A.screenshot({ path: process.env.SHOT || '/tmp/battery-flash.png' });
  await browser.close();
  const failed = results.filter(r => !r.ok).length;
  console.log(failed ? failed + ' FAILED' : 'ALL PASS (' + results.length + ')');
  process.exit(failed ? 1 : 0);
})();
