// HUD smoke test: loads the page in headless Chromium and fails on any script error.
// usage: node tests/hud_check.js URL [shot.png]   (serve hud/ first: cd hud && python3 -m http.server 8811)
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = [];
  p.on('pageerror', e => errs.push('PAGEERROR ' + (e.stack || e.message).split('\n').slice(0, 3).join(' | ')));
  p.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE ' + m.text()); });
  p.on('requestfailed', r => errs.push('REQFAIL ' + r.url()));
  p.on('response', r => { if (r.status() >= 400) errs.push('HTTP ' + r.status() + ' ' + r.url()); });
  await p.goto(process.argv[2]);
  await p.waitForTimeout(+(process.env.WAIT || 6000));
  if (process.env.EVAL) { try { console.log('EVAL', JSON.stringify(await p.evaluate(process.env.EVAL))); } catch (e) { errs.push('EVALERR ' + e.message); } await p.waitForTimeout(3000); }
  if (process.argv[3]) await p.screenshot({ path: process.argv[3] });
  const bad = errs.filter(e => !/WebSocket|404|manifest/.test(e));   // no voice service and no media in CI: expected
  console.log(errs.length ? errs.join('\n') : 'NO ERRORS');
  await b.close();
  process.exit(bad.length ? 1 : 0);
})();
