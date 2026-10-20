// The scribble-strip designer on the web surface LCDs (OpenProSeries docs/58 section 14).
//
//   OMC runs with a console preference file whose scribble design is SOURCE FIRST in the BAR colour style:
//     openproseries-console 1
//     scribble inputs c=bar sep=0 ab=0 src=1l.n.0 name=1l.n.1 icon=side.n.0 num=2l.s.0 batt=2r.s.0
//   and OMC_FEEDBACK_SIM=<input> (a simulated ring on that input). OMC sends the design's look (OSC scr_style =
//   1 + colour mode + 4 when the battery is placed) and per input number the designed lines (scr_l1 / scr_l2) and
//   the PRO surface's 13-character text (scr_lcd). Each input strip LCD must draw line 1 = scr_l1 (the source code
//   first: "A1 ..." with the simulator's default patch), line 2 = scr_l2, a channel-colour bar; the feedback overlay must win over the design (its
//   text on the top line, the bar hidden, the red backlight), alternating with the designed look.
//
// usage: NODE_PATH=<playwright> node test/scribble-design.js http://127.0.0.1:48180/ [input]
//        (OMC simulator as above, test/serve-local.py on 127.0.0.1)
const { chromium } = require('playwright');
const URL = process.argv[2] || 'http://127.0.0.1:48180/';
const INPUT = parseInt(process.argv[3] || '4', 10);

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const CODE = /^(LCL\d{1,2}|[A-F]\d{1,2}|AES\d|DN\d{1,2}|TB|--)(\/\S+)? /;

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

  // the feed
  const style = await A.evaluate(() => Math.round(val('scr_style', 1, -1)));
  check('scr_style = 1 + BAR (1) + battery placed (4) = 6', style === 6, 'got ' + style);
  // scr_lcd is for the PRO surface output (the page does not watch it): ask for it
  await A.evaluate(() => [1, 2, 3, 6].forEach(n => send('get', 'scr_lcd', n)));
  await sleep(1000);
  const feed = await A.evaluate(() => [1, 2, 3, 6].map(n => ({ n, l1: String(val('scr_l1', n, '')), l2: String(val('scr_l2', n, '')), lcd: String(val('scr_lcd', n, '')) })));
  for (const f of feed) {
    check('input ' + f.n + ': line 1 leads with its source code', CODE.test(f.l1), JSON.stringify(f));
    check('input ' + f.n + ': line 2 is the number', /^Inp \d+/.test(f.l2), JSON.stringify(f));
    check('input ' + f.n + ': the PRO surface text fits 13 characters', f.lcd.length > 0 && f.lcd.length <= 13, JSON.stringify(f.lcd));
  }
  check('input 1 is fed by AES50 A input 1 (the simulator\'s default patch): A1', feed[0].l1.startsWith('A1 '), feed[0].l1);
  check('input 1: the PRO surface text is source + name', feed[0].lcd.startsWith('A1 '), feed[0].lcd);

  // the drawn LCDs of the input strips
  const drawn = () => A.evaluate(() => views.filter(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip').map(v => {
    const ch = stripChannel(v.c.bind.bank, v.c.bind.slot);
    if (ch < 0 || inputNo(ch) < 0) return null;
    const texts = [...v.el.querySelectorAll('text')];
    const bar = [...v.el.querySelectorAll('rect')].find(r => r.getAttribute('width') === '1.1');
    return { input: inputNo(ch) + 1, t1: texts[0].textContent, t2: texts[1].textContent,
             bar: !!bar && bar.style.display !== 'none', fill: v.el.querySelector('rect.face').style.fill };
  }).filter(x => x));
  const d = await drawn();
  const of = (n) => d.find(x => x.input === n);
  if (!of(1)) check('input strips are on the page', false, JSON.stringify(d.map(x => x.input)));
  else {
    for (const n of [1, 2, 3]) {
      const f = feed.find(x => x.n === n);
      check('input ' + n + ': LCD line 1 = scr_l1', of(n).t1 === f.l1.slice(0, 14), JSON.stringify(of(n)));
      check('input ' + n + ': LCD line 2 = scr_l2', of(n).t2 === f.l2.slice(0, 14), JSON.stringify(of(n)));
      check('input ' + n + ': the BAR style draws the colour bar', of(n).bar, JSON.stringify(of(n)));
    }
  }

  // the feedback overlay wins over the design: its text on line 1, the bar hidden, the red backlight; then the design again
  let fb = false, own = false, barDuringFb = false;
  for (let k = 0; k < 40 && !(fb && own); k++) {
    const s = (await drawn()).find(x => x.input === INPUT) || {};
    if (/^FB/.test(s.t1 || '')) { fb = true; if (s.bar) barDuringFb = true; }
    else if (CODE.test((s.t1 || '') + ' ') || CODE.test(s.t1 || '')) own = true;
    await sleep(125);
  }
  check('input ' + INPUT + ': the feedback overlay text shows over the design', fb);
  check('input ' + INPUT + ': the design shows in the off phase', own);
  check('input ' + INPUT + ': no design bar while the overlay shows', fb && !barDuringFb);
  check('no page errors', errors.length === 0, errors.join(' | '));
  await A.screenshot({ path: process.env.SHOT || '/tmp/scribble-design.png' });
  await browser.close();
  const failed = results.filter(r => !r.ok).length;
  console.log(failed ? failed + ' FAILED' : 'ALL PASS (' + results.length + ')');
  process.exit(failed ? 1 : 0);
})();
