// OpenProSeries - Vegas mode on the PRO1 web surface (docs/45-vegas-mode.md).
//
// OMC drives Vegas; this page is one of its surfaces ("web"):
//   demo        OMC sends the pattern clock (/vegas/frame: pattern, frame, speed) and every control
//               renders render(pattern, frame, kind, x, y), a line-for-line port of
//               Vegas::Render in OMC src/vegas.cpp, so the page and every other surface show the
//               same frame. Touching any control stops it.
// Vegas is surface only (docs/45, "Surface only"): the controls animate, the display opening (the touch
// screen's place on the drawing) never does, and the page lists no 'screen' element.
//   diagnostic  OMC drives single elements (/vegas/drive), blanks (/vegas/blank) and prompts the
//               operator; the page reports its inventory and every press / touch / move / turn
//               (/vegas/in). Faders emulate a motor: they travel to the driven position and report
//               where they are (echo), so OMC can measure deviation and settle time.
// While Vegas runs, the controls never send their normal bindings: a capture-phase listener takes
// every pointer and wheel event first. surface.js's refresh() is paused; on exit it repaints every
// control from the live values the page kept receiving all along.
//
// Fault injection for tests: ?vegasStuck=<control id> keeps that fader's motor from moving.

'use strict';

const Vegas = (() => {
  const FRAME_MS = 40;
  const TAU = 6.283185307179586, PI = 3.141592653589793;
  const KINDS = ['fader', 'button', 'led', 'encoder', 'meter', 'lcd', 'screen'];
  const PATTERNS = ['wave', 'chase', 'rainbow', 'cascade', 'dance'];
  const frac = (v) => v - Math.floor(v);

  function hue(h) {
    const h6 = frac(h) * 6, i = Math.floor(h6) % 6, f = h6 - Math.floor(h6), q = 1 - f;
    const c = [[1, f, 0], [q, 1, 0], [0, 1, f], [0, q, 1], [f, 0, 1], [1, 0, q]][i];
    return c.map(v => Math.round(v * 255));
  }

  // keep in step with Vegas::Render (src/vegas.cpp): same constants, same order
  function render(p, frame, kind, x, y) {
    const t = frame * (FRAME_MS / 1000);
    let level = 0, on = false, colour = [0, 0, 0];
    switch (p) {
      case 0: // wave
        level = 0.5 + 0.5 * Math.sin(TAU * (t * 0.5 - x)); on = level > 0.5; colour = hue(x * 0.8 + t * 0.1); break;
      case 1: { // chase
        const head = frac(t * 0.35), d = frac(head - x);
        level = d < 0.3 ? 1 - d / 0.3 : 0; on = d < 0.06; colour = hue(head); break;
      }
      case 2: { // rainbow
        const h = frac(x * 0.6 + y * 0.4 - t * 0.25);
        colour = hue(h); on = true; level = 0.5 + 0.5 * Math.sin(TAU * h); break;
      }
      case 3: { // meter cascade
        const s = Math.sin(PI * (t * 0.9 - x * 0.5));
        level = s * s; on = (1 - y) <= level;
        colour = level > 0.85 ? [255, 40, 30] : level > 0.6 ? [255, 210, 26] : [61, 220, 74]; break;
      }
      case 4: { // fader dance
        const k = Math.min(15, Math.max(0, Math.floor(x * 16))), odd = k % 2;
        level = 0.5 + 0.45 * Math.sin(TAU * (t * 0.7 + odd * 0.5 + Math.floor(k / 2) * 0.08));
        on = level > 0.5; colour = odd ? [255, 48, 192] : [32, 208, 255]; break;
      }
    }
    return { level, on, colour };
  }

  if (typeof window === 'undefined') return { render, hue };   // node: the shared-render test

  const st = { mode: 0, pattern: 2, speed: 1, prompt: '', drive: new Map(), elems: [], byEl: new Map(), motors: new Map() };
  const stuck = new URLSearchParams(location.search).get('vegasStuck');
  const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
  const hex = (n) => [(n >> 16) & 255, (n >> 8) & 255, n & 255];

  function kindOf(c) {
    switch (c.type) {
      case 'button': case 'ledbutton': case 'round': case 'arrow': return 'button';
      case 'lcd': return 'lcd';
      case 'knob': case 'pot': case 'jog': return 'encoder';
      case 'fader': return 'fader';
      case 'meter': return 'meter';
      case 'led': return 'led';
      default: return null;
    }
  }

  function elements() {
    if (st.elems.length || !model) return st.elems;
    for (const v of views) {
      const kind = kindOf(v.c);
      if (!kind || kind === 'screen') continue;   // surface only: never the display
      const e = { id: 'c' + v.c.id, kind, x: v.c.x / model.width, y: v.c.y / model.height, label: (v.c.label || v.c.type) + ' #' + v.c.id, v };
      st.elems.push(e);
      st.byEl.set(v.el, e);
    }
    return st.elems;
  }

  // ---- link
  function out(a, f, v) {
    if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ op: 'vegas', a, f, v }));
  }
  const input = (type, e, value = 0) => out('in', 'ssf', [type, e.id, value]);

  function message([addr, args]) {
    const cmd = addr.split('/')[2];
    if (cmd === 'mode') {
      const was = st.mode;
      [st.mode, st.pattern, st.speed] = args;
      st.drive.clear();
      if (st.mode === 2) {
        // diagnostic: tell OMC what this surface has (flags: 1 press, 2 position read-back, 4 touch)
        for (const e of elements()) {
          const flags = (['button', 'lcd'].includes(e.kind) ? 1 : 0) | (e.kind === 'fader' ? 2 | 4 : 0);
          out('inv', 'sssffi', [e.kind, e.id, e.label, e.x, e.y, flags]);
        }
        out('inv_end', 'i', [st.elems.length]);
        blank();
      }
      if (!st.mode && was) restore();
      banner();
    } else if (cmd === 'frame') {
      if (!st.mode) { st.mode = 1; banner(); }   // joined a running demo
      st.pattern = args[0];
      frame(args[0], args[1]);
    } else if (cmd === 'drive') {
      const [id, level, on, colour] = args;
      const e = elements().find(o => o.id === id);
      if (e) drive(e, { level, on: !!on, colour: hex(colour) });
    } else if (cmd === 'fill') {
      const [kinds, level, on, colour] = args, ks = kinds.split(',');
      for (const e of elements()) if (ks.includes(e.kind)) show(e, { level, on: !!on, colour: hex(colour) });
    } else if (cmd === 'blank') {
      blank();
    } else if (cmd === 'prompt') {
      st.prompt = args[0];
      banner();
    }
  }

  // ---- drawing (the same DOM surface.js built; refresh() puts it back)
  function show(e, look) {
    const c = e.v.c, g = e.v.el;
    switch (e.kind) {
      case 'fader': {
        const cap = g.querySelector('g');
        const top = c.top + 4.1, bottom = c.bottom + (c.h < 90 ? 9.65 : 10.4);
        cap.setAttribute('transform', `translate(0 ${top + (1 - look.level) * (bottom - top)})`);
        const col = look.on ? rgb(look.colour) : '#d8dade';
        cap.querySelector('rect').style.fill = col;
        cap.querySelector('circle').style.fill = col;
        break;
      }
      case 'button': {
        const glow = g.querySelector('.glow'), face = g.querySelector('.face');
        glow.style.fill = look.on ? rgb(look.colour) : 'transparent';
        face.style.fill = look.on ? rgb(look.colour) : '#1b1c1f';
        break;
      }
      case 'lcd': {
        const face = g.querySelector('.face');
        face.style.fill = look.on ? rgb(look.colour) : rgb(look.colour.map(v => v >> 2));
        face.style.opacity = '';
        const t = g.querySelectorAll('text');
        if (t.length >= 3) { t[0].textContent = ''; t[1].textContent = st.mode === 1 ? 'VEGAS' : ''; t[2].textContent = ''; }
        break;
      }
      case 'encoder': {
        const arc = g.querySelector('.arc');
        if (!arc) break;
        const R = c.w / 2 * 0.99, a0 = -135 * Math.PI / 180, a = (-135 + 270 * look.level) * Math.PI / 180;
        arc.setAttribute('d', look.level > 0.002 ?
          `M ${c.x + R * Math.sin(a0)} ${c.y - R * Math.cos(a0)} A ${R} ${R} 0 ${(a - a0) > Math.PI ? 1 : 0} 1 ${c.x + R * Math.sin(a)} ${c.y - R * Math.cos(a)}` : '');
        arc.style.stroke = rgb(look.colour);
        break;
      }
      case 'meter': {
        const cells = g.querySelectorAll('rect'), n = cells.length, lit = Math.round(look.level * n);
        cells.forEach((r, k) => { r.style.fill = k >= n - lit ? rgb(look.colour) : '#1b1c1f'; });
        break;
      }
      case 'led':
        g.querySelector('circle').style.fill = look.on ? rgb(look.colour) : '#2a1c12';
        break;
    }
  }

  function frame(p, f) {
    st.frame = f;
    for (const e of elements()) show(e, render(p, f, KINDS.indexOf(e.kind), e.x, e.y));
  }

  function blank() {
    for (const e of elements()) if (e.kind !== 'fader') show(e, { level: 0, on: false, colour: [0, 0, 0] });
  }

  function drive(e, look) {
    if (e.kind !== 'fader') { show(e, look); return; }
    // motor emulation: travel at about one full stroke in 400 ms, report the position as it goes
    const m = st.motors.get(e.id) || { pos: 1 - faderNow(e), timer: null };
    st.motors.set(e.id, m);
    clearInterval(m.timer);
    const target = look.level, t0 = performance.now(), p0 = m.pos;
    const dur = 60 + 400 * Math.abs(target - p0);
    m.timer = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / dur);
      if (stuck !== e.id.slice(1)) m.pos = p0 + (target - p0) * k;
      show(e, { level: m.pos, on: look.on, colour: look.colour });
      input('echo', e, m.pos);
      if (k >= 1) { clearInterval(m.timer); m.timer = null; }
    }, 50);
  }

  function faderNow(e) {
    const tr = e.v.el.querySelector('g').getAttribute('transform') || '';
    const y = parseFloat((tr.match(/translate\(0 ([-\d.]+)\)/) || [])[1]);
    const c = e.v.c, top = c.top + 4.1, bottom = c.bottom + (c.h < 90 ? 9.65 : 10.4);
    return isNaN(y) ? 1 : (y - top) / (bottom - top);
  }

  function restore() {
    for (const m of st.motors.values()) clearInterval(m.timer);
    st.motors.clear();
    for (const e of elements()) {
      const arc = e.v.el.querySelector('.arc');
      if (arc) arc.style.stroke = '';
      if (e.kind === 'button') e.v.el.querySelector('.face').style.fill = '';
    }
    st.prompt = '';
    refresh();
    watch();   // and ask OMC again for everything shown, in case a value was missed
  }

  // ---- banner with the operator keys
  function banner() {
    let b = document.getElementById('vegas');
    if (!st.mode) { if (b) b.remove(); return; }
    if (!b) {
      b = document.createElement('div');
      b.id = 'vegas';
      document.body.appendChild(b);
    }
    b.className = st.mode === 1 ? 'demo' : 'diag';
    b.innerHTML = '';
    const t = document.createElement('span');
    t.textContent = st.mode === 1
      ? `VEGAS MODE - ${PATTERNS[st.pattern] || ''} - touch any control to stop - audio unaffected`
      : `VEGAS HARDWARE TEST - ${st.prompt || '...'}`;
    b.appendChild(t);
    if (st.mode === 2)
      for (const k of ['pass', 'fail', 'next', 'skip', 'stop']) {
        const x = document.createElement('button');
        x.textContent = k.toUpperCase();
        x.className = 'vk ' + k;
        x.onclick = () => out('op', 's', [k]);
        b.appendChild(x);
      }
  }

  // ---- input: the controls' own handlers never see an event while Vegas runs
  function hook(layer) {
    const find = (target) => {
      for (let n = target; n && n !== layer; n = n.parentNode) if (st.byEl.has(n)) return st.byEl.get(n);
      return null;
    };
    let drag = null;   // { e, y, acc }
    const take = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
    layer.addEventListener('pointerdown', (ev) => {
      if (!st.mode) return;
      take(ev);
      elements();
      const e = find(ev.target);
      if (!e) return;
      if (st.mode === 1) { input('press', e); return; }   // demo: any touch stops it
      if (e.kind === 'button' || e.kind === 'lcd') input('press', e);
      else if (e.kind === 'fader') input('touch', e);
      drag = { e, y: ev.clientY, acc: 0 };
      try { layer.setPointerCapture(ev.pointerId); } catch (x) { /* not capturable */ }
    }, true);
    layer.addEventListener('pointermove', (ev) => {
      if (!st.mode || !drag) return;
      take(ev);
      const dy = drag.y - ev.clientY;
      drag.y = ev.clientY;
      if (drag.e.kind === 'encoder') {
        drag.acc += dy * 0.6;
        const s = Math.trunc(drag.acc);
        if (s) { drag.acc -= s; input('turn', drag.e, s); }
      } else if (drag.e.kind === 'fader') {
        const k = model.height / svg.getBoundingClientRect().height, c = drag.e.v.c;
        const span = c.bottom + (c.h < 90 ? 9.65 : 10.4) - (c.top + 4.1);
        const m = st.motors.get(drag.e.id) || { pos: 1 - faderNow(drag.e), timer: null };
        st.motors.set(drag.e.id, m);
        m.pos = Math.max(0, Math.min(1, m.pos + dy * k / span));
        show(drag.e, { level: m.pos, on: true, colour: [0, 255, 0] });
        input('move', drag.e, m.pos);
      }
    }, true);
    const up = (ev) => {
      if (!st.mode) return;
      take(ev);
      if (drag && st.mode === 2) {
        if (drag.e.kind === 'button' || drag.e.kind === 'lcd') input('release', drag.e);
        else if (drag.e.kind === 'fader') input('untouch', drag.e);
      }
      drag = null;
    };
    layer.addEventListener('pointerup', up, true);
    layer.addEventListener('pointercancel', up, true);
    layer.addEventListener('wheel', (ev) => {
      if (!st.mode) return;
      take(ev);
      const e = find(ev.target);
      if (!e) return;
      if (st.mode === 1) { input('press', e); return; }
      if (e.kind === 'encoder') input('turn', e, ev.deltaY < 0 ? 1 : -1);
    }, { capture: true, passive: false });
    layer.addEventListener('dblclick', (ev) => { if (st.mode) take(ev); }, true);
  }

  // controls are built asynchronously by surface.js: hook the layer once it exists
  const wait = setInterval(() => {
    const layer = document.getElementById('controls');
    if (layer) { clearInterval(wait); hook(layer); }
  }, 100);

  return { render, hue, message, active: () => st.mode !== 0, state: st };
})();

if (typeof module !== 'undefined') module.exports = Vegas;
