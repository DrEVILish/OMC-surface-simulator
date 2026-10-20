// The 36 x 24 surface strip on the web surface LCDs (OMC scr_bmp, surface-lcd36.h, PLAN W12d).
//
//   The page decodes the 108-byte frame (base64; 12 row pairs x 9 bytes, rows B then A, MSB first, byte-reversed) and, with the
//   "dots" header key (or ?lcd=dots), draws it on every input strip LCD in place of the text lines.
//   Checks: the decoder against a frame built here; OMC's frame for input 1 decodes to a non-empty 36 x 24 image with
//   the path id "Ch1" area inked and the name rows inked; the dot image is shown on an input LCD and the text hidden;
//   the key turns it off again.
//
// usage: NODE_PATH=<playwright> node test/scribble-dots.js http://127.0.0.1:48180/
//        (OMC simulator, test/serve-local.py on 127.0.0.1)
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
  await A.goto(URL + (URL.includes('?') ? '&' : '?') + 'lcd=dots', { waitUntil: 'networkidle' });
  await sleep(2500);
  const status = await A.evaluate(() => document.getElementById('status').textContent);
  check('linked to OMC', status === 'linked to OMC', status);
  if (status !== 'linked to OMC') { await browser.close(); process.exit(2); }

  // the decoder: one dot at (0, 1) = B0 = the top bit of byte 8; one at (35, 0) = A35 = the low bit of byte 0
  const dec = await A.evaluate(() => {
    const b = new Array(108).fill(0);
    b[8] = 0x80; b[9 * 11] = 0x01;
    const r = lcd36Decode(btoa(String.fromCharCode(...b)));
    let n = 0;
    for (const row of r) for (const d of row) n += d ? 1 : 0;
    return { n, b0: r[1][0], a35: r[22][35], bad: lcd36Decode('xx') === null };
  });
  check('decoder: B0 of pair 0 and A35 of pair 11, nothing else', dec.n === 2 && dec.b0 && dec.a35, JSON.stringify(dec));
  check('decoder: rejects a non-frame', dec.bad);

  // OMC's frame of input 1 (wait for the watch reads to come back: a page asks for some 2000 values at start)
  for (let t = 0; t < 40; t++) {
    if (await A.evaluate(() => String(val('scr_bmp', 1, '')).length === 144)) break;
    await sleep(250);
  }
  await sleep(500);
  const img = await A.evaluate(() => {
    const r = lcd36Decode(String(val('scr_bmp', 1, '')));
    if (!r) return null;
    const ink = (y0, y1, x0, x1) => { let n = 0; for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) n += r[y][x] ? 1 : 0; return n; };
    return { top: ink(1, 5, 0, 12), name: ink(8, 16, 0, 35) };
  });
  check('OMC sends input 1 as a 36 x 24 frame', !!img, img ? '' : 'got ' + await A.evaluate(() => String(val('scr_bmp', 1, '?')).length + ' ' + JSON.stringify(String(val('scr_bmp', 1, '?')).slice(-20))));
  if (img) check('the frame has the path id and the name inked', img.top > 5 && img.name > 10, JSON.stringify(img));

  // drawn: an input strip LCD shows the dot image, its text hidden
  const shown = () => A.evaluate(() => views.filter(v => v.c.type === 'lcd' && v.c.bind && v.c.bind.kind === 'strip').map(v => {
    const im = v.el.querySelector('image');
    const texts = [...v.el.querySelectorAll('text')].filter(t => t.style.display !== 'none' && t.textContent);
    return { img: !!im && im.style.display !== 'none' && (im.getAttribute('href') || '').startsWith('data:image/png'), text: texts.length };
  }));
  let s = await shown();
  const withDots = s.filter(x => x.img).length;
  check('input strip LCDs draw the dot strip', withDots >= 8, withDots + ' of ' + s.length);
  check('their text lines are hidden', s.filter(x => x.img && x.text > 0).length === 0);
  await A.click('#dots');
  await sleep(500);
  s = await shown();
  check('the dots key turns it off', s.filter(x => x.img).length === 0);
  check('no page errors', errors.length === 0, errors.join(' | '));
  await browser.close();
  const failed = results.filter(r => !r.ok).length;
  console.log(failed ? failed + ' FAILED' : 'all ' + results.length + ' passed');
  process.exit(failed ? 1 : 0);
})();
