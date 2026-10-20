// Vegas mode: vegas.js's render() against the table OMC's doctest checks Vegas::Render with
// (src/vegas-test.cpp, "Render matches the shared table"). Both must agree, or the page and the
// console would show different frames.   usage: node test/vegas-render.js
const V = require('../www/vegas.js');
const T = [
  [0, 0, 0.1, 0.2, 0.206107, 0, 16742912], [0, 37, 0.53, 0.8, 0.984292, 1, 37375],
  [0, 250, 0.97, 0.05, 0.593691, 1, 10944767], [0, 1001, 0.33, 0.66, 0.035112, 0, 6618880],
  [1, 0, 0.1, 0.2, 0, 0, 16711680], [1, 37, 0.53, 0.8, 0, 0, 58367],
  [1, 250, 0.97, 0.05, 0, 0, 65535], [1, 1001, 0.33, 0.66, 0, 0, 16717056],
  [1, 10, 0.95, 0.5, 0.366667, 0, 16766464], [1, 0, 0.97, 0.5, 0.9, 1, 16711680],
  [2, 0, 0.1, 0.2, 0.885257, 1, 16766464], [2, 37, 0.53, 0.8, 0.996806, 1, 6618880],
  [2, 250, 0.97, 0.05, 0.798952, 1, 16751616], [2, 1001, 0.33, 0.66, 0.648521, 1, 65462],
  [3, 0, 0.1, 0.2, 0.024472, 0, 4054090], [3, 37, 0.53, 0.8, 0.043654, 0, 4054090],
  [3, 250, 0.97, 0.05, 0.997781, 1, 16721950], [3, 1001, 0.33, 0.66, 0.155443, 0, 4054090],
  [4, 0, 0.1, 0.2, 0.5, 0, 16724160], [4, 37, 0.53, 0.8, 0.85383, 1, 2150655],
  [4, 250, 0.97, 0.05, 0.665656, 1, 16724160], [4, 1001, 0.33, 0.66, 0.083715, 0, 16724160],
];
let bad = 0;
for (const [p, f, x, y, level, on, rgb] of T) {
  const r = V.render(p, f, 0, x, y);
  const want = [(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255];
  const ok = Math.abs(r.level - level) < 1e-5 && (r.on ? 1 : 0) === on && r.colour.every((c, i) => Math.abs(c - want[i]) <= 1);
  if (!ok) { bad++; console.log('FAIL', p, f, x, y, r); }
}
console.log(`${T.length - bad} / ${T.length} match`);
process.exit(bad ? 1 : 0);
