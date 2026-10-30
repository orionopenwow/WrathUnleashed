// Headless Chromium (Playwright): the Leyline brand switch on the stream page files. With the brand ON (the portal's
// /__env.js sends brand + home_name), the hop bar and the join page say "Back to Dalaran Hangout" and the one-tab
// note page (tab.html) says Leyline; with it OFF (no env.brand) they say exactly what they said before.
//
//   node --test tests/brand.browser.test.cjs          (from the stream folder; needs Playwright)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const WWW = path.join(__dirname, '..', 'www-files');
const OLD = /WrathUnleashed|Wrath Unleashed|Open ?Vanilla|Back to Wrath\b/;

function serve() {
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://x');
    if (u.pathname === '/hop.html') {
      res.writeHead(200, { 'content-type': 'text/html' });
      return res.end('<!doctype html><html><head><title>t</title></head><body></body></html>');
    }
    const f = path.join(WWW, path.normalize(u.pathname).replace(/^([/\\])+/, ''));
    if (!f.startsWith(WWW) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
    const type = f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/octet-stream';
    res.writeHead(200, { 'content-type': type });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((ok) => srv.listen(0, '127.0.0.1', () => ok(srv)));
}

async function hopPage(browser, base, env) {
  const page = await browser.newPage();
  await page.goto(base + '/hop.html');
  await page.evaluate(async (env) => {
    window.__wenilla_env = env;
    window.__wuHop = { state: { home: false, login: null }, forgetLogin() {} };
    const m = await import('/wrath-page.js');
    m.hopUi(env, window.__wuHop);
  }, env);
  const text = await page.evaluate(() => document.body.innerText);
  const kept = await page.evaluate(() => localStorage.getItem('wu-brand'));
  await page.close();
  return { text, kept };
}

const hopEnv = { hop: 'abcdefghijklmnop', hop_name: 'Frost Haven', hop_ws: 'wss://relay.example/ws/abcdefghijklmnop',
  hop_join: 'about:blank?hop=1', home: 'https://play.example' };

test('brand on and off: the hop bar, the join page and the one-tab note', async () => {
  const srv = await serve();
  const base = `http://127.0.0.1:${srv.address().port}`;
  const browser = await chromium.launch();
  try {
    const on = await hopPage(browser, base, { ...hopEnv, brand: 'leyline', home_name: 'Dalaran Hangout' });
    assert.match(on.text, /Back to Dalaran Hangout/, 'on: the bar and the join page name the main realm');
    assert.doesNotMatch(on.text, OLD, 'on: no old names');
    assert.equal(on.kept, 'Dalaran Hangout', 'on: kept for tab.html');

    const off = await hopPage(browser, base, hopEnv);
    assert.match(off.text, /Back to Wrath/, 'off: the old words');
    assert.equal(off.kept, null, 'off: nothing kept');

    const tab = await browser.newPage();
    await tab.goto(base + '/tab.html');
    await tab.evaluate(() => localStorage.setItem('wu-brand', 'Dalaran Hangout'));
    await tab.goto(base + '/tab.html?m=busy&r=/');
    const t = await tab.evaluate(() => ({ title: document.title, h: document.getElementById('t').textContent }));
    assert.equal(t.title, 'Leyline');
    assert.equal(t.h, 'Leyline is already open in another tab');
    await tab.evaluate(() => localStorage.removeItem('wu-brand'));
    await tab.goto(base + '/tab.html?m=busy&r=/');
    const t0 = await tab.evaluate(() => ({ title: document.title, h: document.getElementById('t').textContent }));
    assert.deepEqual(t0, { title: 'WrathUnleashed', h: 'WrathUnleashed is already open in another tab' }, 'off: as before');
  } finally {
    await browser.close();
    srv.close();
  }
});
