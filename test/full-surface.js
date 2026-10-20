// Operate every control of the PRO1 web surface and check the effect.
//
//   page A operates the surface; page B only watches. A control linked to an OMC parameter passes
//   when page B receives OMC's change feed for that parameter after the action (the bridge does
//   not echo sets: B can only learn the value from OMC). Surface-logic keys (layers, scroll,
//   modes, sends on faders) pass when they change the surface state they own. Indicators (LEDs,
//   meters) are checked for a binding that resolves to OMC state.
//
//   Touch-UI keys: the 8 assignable encoders ('enc') pass on OMC's feed for enc/<k> (the steps the
//   touch UI consumes), the keys under them ('enckey') on enc_key/<k>, POP keys ('cmd' + touch) on
//   ui_cmd/1 and both web fader banks switching to the 'touch' layer, LCD select keys on sel/1 and
//   ui_cmd/1 (ui_cmd 60).
//
//   State is put back after each control where it can be: toggles are pressed again and checked
//   back, knobs / faders get their old value, encoders are turned back, encoder keys pressed again,
//   and ALT (surface/63) is held off around the POP keys (ALT + POP changes POP membership) and
//   restored at the end.
//
// usage: [THEME=colour] node full-surface.js http://127.0.0.1/   (needs playwright)
//        ONLY=132,144,156 limits the run to those control ids
const { chromium } = require('playwright');
const URL = process.argv[2] || 'http://127.0.0.1/';

(async () => {
  const browser = await chromium.launch();
  const A = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
  const B = await browser.newPage({ viewport: { width: 800, height: 800 } });
  // THEME=colour runs the test in the full-colour finish
  if (process.env.THEME === 'colour')
    for (const p of [A, B]) await p.addInitScript(() => { try { localStorage.setItem('pro1-theme', 'colour'); } catch (e) {} });
  const errors = [];
  for (const p of [A, B]) p.on('pageerror', e => errors.push(String(e)));
  await A.goto(URL, { waitUntil: 'networkidle' });
  await B.goto(URL, { waitUntil: 'networkidle' });
  await A.waitForTimeout(1500);
  // the bridge reports whether OMC answers on its OSC port; without it every check fails
  const status = await A.evaluate(() => document.getElementById('status').textContent);
  if (status !== 'linked to OMC') {
    console.log(JSON.stringify({ total: 0, passed: 0, failed: 0, abort: 'surface status: ' + status }));
    await browser.close();
    process.exit(2);
  }
  await B.evaluate(() => {
    window.__seen = new Map();
    const orig = S.ws.onmessage;
    S.ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      for (const [p, i] of m.u || []) window.__seen.set(p + '/' + i, (window.__seen.get(p + '/' + i) || 0) + 1);
      orig(ev);
    };
  });

  const n = await A.evaluate(() => views.length);
  const results = [], warnings = [];
  const seenB = (key) => B.evaluate((key) => (window.__seen.get(key) || 0), key);
  const valB = (key) => B.evaluate((key) => S.values.get(key), key);
  const until = async (fn, ms = 2000) => {
    for (let t = 0; t < ms / 100; t++) { if (await fn()) return true; await A.waitForTimeout(100); }
    return !!(await fn());
  };
  const near = (a, b) => a !== undefined && b !== undefined && (typeof a === 'string' || typeof b === 'string' ? a === b : Math.abs(a - b) < 1e-3);
  // ALT (surface/63): an ALT left on makes a POP key change POP membership instead of spilling
  const ALT = 'surface/63';
  const setAlt = async (v) => {
    await A.evaluate((v) => send('set', 'surface', 63, v), v);
    return until(async () => near(await valB(ALT), v));
  };
  await until(async () => (await valB(ALT)) !== undefined);
  const altStart = (await valB(ALT)) ?? 0;
  if (altStart >= 0.5) { warnings.push('ALT was on at start: turned off for the run'); await setAlt(0); }
  const reset = () => A.evaluate(() => {
    S.layer = { L: 'input', R: 'input' }; S.page = { L: 0, R: 1 }; S.extend = null; S.sends = 0; S.dyn = 'comp'; S.band = 1; watch(); refresh();
  });

  const only = process.env.ONLY ? new Set(process.env.ONLY.split(',').map(Number)) : null;
  for (let k = 0; k < n; k++) {
    if (only && !only.has(await A.evaluate((k) => views[k].c.id, k))) continue;
    await reset();
    const info = await A.evaluate((k) => {
      const v = views[k], c = v.c, b = c.bind || {};
      let r = resolve(b);
      // the dynamics knobs that only exist for one processor are tested in that mode
      if (!r && b.kind === 'dyn') { S.dyn = b.comp ? 'comp' : 'gate'; r = resolve(b); }
      // a mode key must find the other mode set, or pressing it changes nothing
      if (b.kind === 'mode') { if (b.mode === 'dyn') S.dyn = b.value === 'gate' ? 'comp' : 'gate'; else S.band = 2; }
      if (b.kind === 'bay') { S.layer.R = 'vca'; S.page.R = 0; }
      const box = v.el.getBoundingClientRect();
      return { type: c.type, kind: b.kind || 'none', label: c.label || '', x: box.x + box.width / 2, y: box.y + box.height / 2,
               w: box.width, h: box.height, key: r ? r.p + '/' + r.i : null, id: c.id,
               touch: !!b.touch, select: !!b.select, enc: b.kind === 'enc' ? b.i : 0,
               state: JSON.stringify([S.layer, S.page, S.sends, S.dyn, S.band]) };
    }, k);
    const res = { id: info.id, type: info.type, kind: info.kind, label: info.label, key: info.key };

    if (info.type === 'led' || info.type === 'meter') {
      res.ok = info.kind === 'meter' || info.kind === 'strip' ? !!info.key : ['mirror', 'bandled'].includes(info.kind);
      res.how = 'indicator bound';
      if (info.type === 'meter' && res.ok) {
        // meters must move: OMC's level for it has to rise above the floor (audio, or OMC_TEST_SIGNAL)
        let v = -120;
        for (let t = 0; t < 20 && !(v > -110); t++) { await A.waitForTimeout(100); v = await A.evaluate((key) => S.values.get(key), info.key); }
        res.ok = v > -110; res.after = v; res.how = 'meter level from OMC';
      }
      results.push(res); continue;
    }

    // a POP key must spill, not edit membership
    if (info.touch && (await valB(ALT)) >= 0.5) { warnings.push(`ALT on before ${info.id}: turned off`); await setAlt(0); }
    const before = await seenB(info.key);
    const selBefore = await seenB('sel/1');
    const cmdBefore = await seenB('ui_cmd/1');
    // OMC's value before the action (page B), to put it back afterwards
    const vPrev = info.key ? await valB(info.key) : undefined;
    const encPrev = info.enc ? await valB('enc_pos/' + info.enc) : undefined;
    // what OMC holds when the control is operated (page A's view, the one the press is computed from)
    const vBefore = info.kind === 'surface' ? await A.evaluate((key) => S.values.get(key), info.key) : null;
    // act
    let dragPx = 0;
    if (info.type === 'knob' || info.type === 'pot') {
      // turn towards the side with room left (an encoder: the position OMC reports for what it drives)
      const pos = await A.evaluate((k) => {
        const b = views[k].c.bind;
        if (b && b.kind === 'enc') return clamp(val('enc_pos', b.i, 0), 0, 1);
        const r = resolve(b); return r ? clamp(toPos(val(r.p, r.i, r.lo), r), 0, 1) : 0.5;
      }, k);
      dragPx = pos > 0.5 ? 25 : -25;
      await A.mouse.move(info.x, info.y); await A.mouse.down();
      await A.mouse.move(info.x, info.y + dragPx, { steps: 5 }); await A.mouse.up();
    } else if (info.type === 'fader') {
      const t = await A.evaluate((k) => { const c = views[k].c; const r = resolve(c.bind); return r ? faderT(val(r.p, r.i, -100)) : 1; }, k);
      const pxmm = await A.evaluate(() => svg.getBoundingClientRect().height / model.height);
      const capY = info.y - info.h / 2 + (2 + 4.1 + t * 99.4) * pxmm;
      await A.mouse.move(info.x, capY); await A.mouse.down();
      await A.mouse.move(info.x, capY + (t > 0.5 ? -40 : 40), { steps: 6 }); await A.mouse.up();
    } else if (info.type === 'jog') {
      const r = Math.min(info.w, info.h) * 0.4;
      await A.mouse.move(info.x, info.y - r); await A.mouse.down();
      for (let a = 0; a <= 80; a += 10) await A.mouse.move(info.x + r * Math.sin(a * Math.PI / 180), info.y - r * Math.cos(a * Math.PI / 180));
      await A.mouse.up();
    } else {
      await A.mouse.click(info.x, info.y);
    }
    await A.waitForTimeout(350);

    if (['layer', 'scroll', 'mode', 'sends', 'bay'].includes(info.kind)) {
      const after = await A.evaluate(() => JSON.stringify([S.layer, S.page, S.sends, S.dyn, S.band]));
      res.ok = after !== info.state || (info.kind === 'sends');   // AUX/clear: checked below
      if (info.kind === 'sends') {
        const s = await A.evaluate(() => S.sends);
        res.ok = info.label === 'clear' ? s === 0 : s > 0;
      }
      if (info.kind === 'layer' && after === info.state) res.ok = await A.evaluate((k) => isOn(views[k].c), k);
      res.how = 'surface state';
    } else if (['selstep', 'jog'].includes(info.kind) || (info.key && info.key.startsWith('sel/'))) {
      const after = await seenB('sel/1');
      res.ok = after > selBefore; res.how = 'OMC feed sel';
      if (info.select) {
        // an LCD select key is also a press for the touch UI (ui_cmd 60)
        res.ok = res.ok && (await seenB('ui_cmd/1')) > cmdBefore;
        res.how += ' + ui_cmd';
      }
    } else {
      const after = await seenB(info.key);
      res.ok = !!info.key && after > before; res.how = 'OMC feed ' + info.key;
      if (info.enc && res.ok && encPrev > 0) {
        // the touch UI applied the steps to the knob it drives: its position (enc_pos) must move
        const ePos = 'enc_pos/' + info.enc;
        await until(async () => { const v = await valB(ePos); return v !== undefined && Math.abs(v - encPrev) > 1e-3; });
        res.before = encPrev; res.after = await valB(ePos);
        res.ok = Math.abs(res.after - encPrev) > 1e-3; res.how += ' + ' + ePos;
      }
      if (info.touch) {
        // POP: the touch UI spills the group; both web banks follow the touch UI's bank
        const L = await A.evaluate(() => [S.layer.L, S.layer.R]);
        res.ok = res.ok && L[0] === 'touch' && L[1] === 'touch';
        res.how += ' + layer ' + L.join('/');
      }
      if (info.kind === 'surface') {
        // the touch UI applies it to its desk model and writes the model's value back: page B (fed only
        // by OMC) must settle on the new value
        const toggle = info.type !== 'knob' && info.type !== 'pot';
        let vAfter;
        for (let t = 0; t < 20; t++) {
          vAfter = await B.evaluate((key) => S.values.get(key), info.key);
          const moved = vAfter !== undefined && Math.abs(vAfter - (vBefore ?? 0)) > 1e-3;
          if (moved && (!toggle || info.id === undefined || Math.abs(vAfter - (vBefore >= 0.5 ? 0 : 1)) < 1e-3 || vBefore === 0.5 || vAfter === 0.5)) break;
          await A.waitForTimeout(100);
        }
        res.before = vBefore; res.after = vAfter;
        res.ok = res.ok && vAfter !== undefined && Math.abs(vAfter - (vBefore ?? 0)) > 1e-3;
        res.how = 'desk model via OMC ' + info.key;
      }
    }
    // put toggles back: press again and check OMC went back
    if (res.ok && info.kind !== 'mode' && ['button', 'ledbutton', 'round', 'lcd'].includes(info.type) &&
        !['scroll', 'layer', 'sends', 'selstep', 'cycle', 'cmd', 'radio', 'bay'].includes(info.kind) && !(info.key || '').startsWith('sel/')) {
      if (info.kind === 'enckey') {
        // the encoder key toggles the focused row: wait for OMC to consume the first press, press again
        if (!await until(async () => near(await valB(info.key), 0))) warnings.push(`${info.id} ${info.key}: OMC did not reset the key`);
        await A.mouse.click(info.x, info.y);
        await until(async () => near(await valB(info.key), 0));
      } else {
        await A.mouse.click(info.x, info.y);
        if (vPrev !== undefined && !await until(async () => near(await valB(info.key), vPrev))) {
          await A.mouse.click(info.x, info.y);   // a press lost on the way: once more
          if (!await until(async () => near(await valB(info.key), vPrev)))
            warnings.push(`${info.id} ${info.key}: not restored (was ${vPrev}, now ${await valB(info.key)})`);
        }
      }
      await A.waitForTimeout(150);
    }
    // put continuous controls back
    if (info.enc) {
      // relative encoder: turn back by the same amount
      await A.mouse.move(info.x, info.y); await A.mouse.down();
      await A.mouse.move(info.x, info.y - dragPx, { steps: 5 }); await A.mouse.up();
      const ePos = 'enc_pos/' + info.enc;
      if (encPrev !== undefined && !await until(async () => { const v = await valB(ePos); return v !== undefined && Math.abs(v - encPrev) < 0.015; }))
        warnings.push(`${info.id} ${ePos}: not restored (was ${encPrev}, now ${await valB(ePos)})`);
    } else if (['knob', 'pot', 'fader'].includes(info.type) && info.key && typeof vPrev === 'number') {
      await A.evaluate(([p, i, v]) => send('set', p, i, v), [info.key.slice(0, info.key.lastIndexOf('/')), +info.key.slice(info.key.lastIndexOf('/') + 1), vPrev]);
      if (!await until(async () => { const v = await valB(info.key); return v !== undefined && Math.abs(v - vPrev) < 0.01 * (1 + Math.abs(vPrev)); }))
        warnings.push(`${info.id} ${info.key}: not restored (was ${vPrev}, now ${await valB(info.key)})`);
    }
    results.push(res);
  }

  // ALT off at the end (the state the run started from, or off if it found ALT stuck on)
  if (!await setAlt(0)) warnings.push('ALT: could not turn off at the end');

  const failed = results.filter(r => !r.ok);
  const byType = {};
  for (const r of results) { byType[r.type] = byType[r.type] || [0, 0]; byType[r.type][r.ok ? 0 : 1]++; }
  console.log(JSON.stringify({ total: results.length, passed: results.length - failed.length, failed: failed.length, byType }, null, 0));
  for (const f of failed) console.log('FAIL', JSON.stringify(f));
  for (const w of warnings) console.log('WARN', w);
  console.log('page errors', errors.length ? errors : 'none');
  require('fs').writeFileSync('full-surface-results.json', JSON.stringify(results, null, 1));
  await browser.close();
  process.exit(failed.length || errors.length ? 1 : 0);
})();
