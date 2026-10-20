// The feedback detector's flash on the web surface LCDs (OpenProSeries docs/60).
//
//   OMC runs with OMC_FEEDBACK_SIM=<input> (a simulated ring on that input, 2 s after start-up). Its scribble
//   overlay reaches the page as ovl_text / ovl_style per input number; the LCD of that input's strip must show
//   "FB..." on its top line with a red backlight, alternating with the channel's own look (4 Hz flash), and the
//   other strips must not. After DISMISS (OSC is not involved: the test clears it by waiting for the hold, or
//   a second run) nothing is checked here; the touch UI's doctests cover the timeouts.
//
// usage: NODE_PATH=<playwright> node test/feedback-flash.js http://127.0.0.1:48180/ [input]
//        (OMC simulator with OMC_FEEDBACK_SIM=<input>, test/serve-local.py on 127.0.0.1)
const { chromium } = require('playwright');
const URL = process.argv[2] || 'http://127.0.0.1:48180/';
const INPUT = parseInt(process.argv[3] || '4', 10);

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const A = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
  const errors = [];
  A.on('pageerror', e => errors.push(String(e)));
  await A.goto(URL, { waitUntil: 'networkidle' });
  await sleep(1500);
  const status = await A.evaluate(() => document.getElementById('status').textContent);
  check('linked to OMC', status === 'linked to OMC', status);
  if (status !== 'linked to OMC') { await browser.close(); process.exit(2); }

  // the LCD views of the input strips: top line, backlight
  const lcds = () => A.evaluate(() => views.filter(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip').map(v => {
    const ch = stripChannel(v.c.bind.bank, v.c.bind.slot);
    const t = v.el.querySelectorAll('text');
    const face = v.el.querySelector('rect.face');
    return { input: ch >= 0 ? inputNo(ch) + 1 : 0, top: t[0] ? t[0].textContent : '', fill: face ? face.style.fill : '' };
  }));

  // wait for the flag (the ring starts 2 s after OMC's start and needs about a second to be sure)
  let style = 0;
  for (let k = 0; k < 150 && style <= 0; k++) {
    style = await A.evaluate((n) => Math.round(val('ovl_style', n, 0)), INPUT);
    if (style <= 0) await sleep(100);
  }
  check('OMC flags input ' + INPUT + ' (ovl_style flashing red)', style === 1 + 1 + 8, 'ovl_style ' + style);
  const text = await A.evaluate((n) => String(val('ovl_text', n, '')), INPUT);
  check('ovl_text names the frequency', /^FB\??( [0-9.]+k?)?$/.test(text), JSON.stringify(text));

  // sample the LCDs for 2 s: the flagged strip alternates, the others never show FB
  let sawFb = false, sawOwn = false, others = false, red = false;
  for (let k = 0; k < 20; k++) {
    for (const l of await lcds()) {
      if (l.input === INPUT) {
        if (l.top.startsWith('FB')) { sawFb = true; if (/rgb\(226, 72, 59\)|#e2483b/i.test(l.fill)) red = true; }
        else sawOwn = true;
      } else if (l.top.startsWith('FB')) others = true;
    }
    await sleep(100);
  }
  check('the flagged strip shows FB on its LCD', sawFb);
  check('... with the red backlight', red);
  check('... alternating with its own name (flash)', sawOwn);
  check('no other strip shows FB', !others);
  check('no page errors', errors.length === 0, errors.join(' | '));
  await browser.close();
  const failed = results.filter(r => !r.ok).length;
  console.log(failed ? `${failed} FAILED` : 'ALL PASS');
  process.exit(failed ? 1 : 0);
})();
