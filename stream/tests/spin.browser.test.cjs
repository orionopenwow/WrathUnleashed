// Headless Chromium (Playwright): the Leyline loading logo on the game page (www-files/leyline-look.css, linked by
// wrath-early.js). With the brand ON (/__env.js brand "leyline"): <html class="ly-brand">, boot.js's overlay and the
// world-loading cover show the spinning mark (the swirl's transform changes over time, the crystal stays upright),
// none of the painted art is fetched, and with reduced motion the mark stands still. With it OFF: leyline-look.css is
// never asked for and the old look is untouched. tab.html follows the kept brand (or ?b=1) the same way.
//
//   NODE_PATH=$(npm root -g) node --test stream/tests/spin.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const WWW = path.join(__dirname, '..', 'www-files');
const TYPES = { '.js': 'text/javascript', '.html': 'text/html', '.css': 'text/css', '.webp': 'image/webp', '.png': 'image/png',
  '.woff2': 'font/woff2' };
const PAINTED = /wu-load-bg|wu-load-orion|wu-corner|wu-dragon|wu-divider|Cinzel/;
// boot.js's overlay, as it draws it (the markup wu-loading.css restyles)
const BOOT = '<div id="wenilla-boot" style="position:fixed;inset:0;display:grid;place-items:center"><div class="box">'
  + '<div class="stage">Loading…</div><div class="bar pulse"><i></i></div><div class="data"></div></div></div>';

function serve() {
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://x');
    if (u.pathname === '/game.html') {
      const env = u.searchParams.get('brand') ? '{"brand":"leyline","home_name":"Wrath Unleashed"}' : '{}';
      res.writeHead(200, { 'content-type': 'text/html' });
      return res.end(`<!doctype html><html><head><meta charset="utf-8"><title>t</title>`
        + `<script>window.__wenilla_env = ${env};</script><script src="./wrath-early.js"></script></head>`
        + `<body style="margin:0">${BOOT}</body></html>`);
    }
    const f = path.join(WWW, path.normalize(u.pathname).replace(/^([/\\])+/, ''));
    if (!f.startsWith(WWW) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'content-type': TYPES[path.extname(f)] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((ok) => srv.listen(0, '127.0.0.1', () => ok(srv)));
}

const angle = (page, sel, pseudo) => page.evaluate(([s, p]) => {
  const t = getComputedStyle(document.querySelector(s), p).transform;
  if (!t || t === 'none') return 0;
  const m = t.match(/matrix\(([^)]+)\)/)[1].split(',').map(Number);
  return Math.round(Math.atan2(m[1], m[0]) * 1800 / Math.PI) / 10;
}, [sel, pseudo]);

let srv, base, browser;
test.before(async () => { srv = await serve(); base = `http://127.0.0.1:${srv.address().port}`; browser = await chromium.launch(); });
test.after(async () => { await browser.close(); srv.close(); });

async function open(url, ctxOpts) {
  const ctx = await browser.newContext(ctxOpts || {});
  const page = await ctx.newPage();
  const asked = [];
  page.on('request', (r) => asked.push(new URL(r.url()).pathname));
  await page.goto(base + url);
  await page.waitForLoadState('networkidle').catch(() => {});
  return { ctx, page, asked };
}

test('brand on: the boot overlay and the world cover show the spinning mark, no painted art', async () => {
  const { ctx, page, asked } = await open('/game.html?brand=1');
  await page.waitForFunction(() => document.documentElement.classList.contains('ly-brand')
    && getComputedStyle(document.querySelector('#wenilla-boot .box'), '::before').animationName === 'ly-spin-turn');
  const r = await page.evaluate(() => {
    const box = document.querySelector('#wenilla-boot .box');
    const b = getComputedStyle(box, '::before'), a = getComputedStyle(box, '::after');
    return { swirl: b.backgroundImage, crystal: a.backgroundImage, bg: getComputedStyle(document.getElementById('wenilla-boot')).backgroundImage,
      line: getComputedStyle(document.querySelector('#wenilla-boot .stage'), '::after').fontFamily };
  });
  assert.match(r.swirl, /leyline-swirl-256\.webp/);
  assert.match(r.crystal, /leyline-crystal-256\.webp/);
  assert.equal(r.bg, 'none', 'a flat backdrop');
  assert.doesNotMatch(r.line, /Cinzel/);
  const a1 = await angle(page, '#wenilla-boot .box', '::before');
  await page.waitForTimeout(700);
  const a2 = await angle(page, '#wenilla-boot .box', '::before');
  assert.notEqual(a1, a2, `the swirl turns (${a1} -> ${a2})`);
  assert.equal(await angle(page, '#wenilla-boot .box', '::after'), 0, 'the crystal stays upright');
  // the world-loading cover (wu-loading.js), up
  await page.evaluate(async () => { const m = await import('/wu-loading.js'); m.installLoading(); dispatchEvent(new CustomEvent('ow:progress', { detail: 'enter' })); });
  await page.waitForFunction(() => document.querySelector('#wu-loading.on'));
  assert.match(await page.evaluate(() => getComputedStyle(document.querySelector('#wu-loading .box'), '::before').backgroundImage), /leyline-swirl/);
  await page.waitForTimeout(300);
  if (process.env.SPIN_DEBUG) console.log(await page.evaluate(() => [...document.querySelectorAll('*')].flatMap((e) => [null, '::before', '::after']
    .map((p) => [e.tagName + '#' + e.id + '.' + e.className + (p || ''), getComputedStyle(e, p).fontFamily, getComputedStyle(e, p).display, getComputedStyle(e, p).content]))
    .filter((x) => /Cinzel/.test(x[1]) && x[2] !== 'none')));
  assert.ok(asked.includes('/leyline-look.css'));
  assert.deepEqual(asked.filter((u) => PAINTED.test(u)), [], 'no painted art fetched');
  await ctx.close();
});

test('brand on with reduced motion: the mark stands still', async () => {
  const { ctx, page } = await open('/game.html?brand=1', { reducedMotion: 'reduce' });
  await page.waitForFunction(() => /leyline-swirl/.test(getComputedStyle(document.querySelector('#wenilla-boot .box'), '::before').backgroundImage));
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('#wenilla-boot .box'), '::before').animationName), 'none');
  const a1 = await angle(page, '#wenilla-boot .box', '::before');
  await page.waitForTimeout(500);
  assert.equal(await angle(page, '#wenilla-boot .box', '::before'), a1);
  await ctx.close();
});

test('brand off: the page as before (no leyline-look.css, no class, the old art)', async () => {
  const { ctx, page, asked } = await open('/game.html');
  await page.waitForFunction(() => document.getElementById('wu-loading-css'));
  await page.waitForTimeout(400);
  assert.equal(await page.evaluate(() => document.documentElement.className), '');
  assert.ok(!asked.includes('/leyline-look.css'));
  assert.ok(!asked.some((u) => /leyline-/.test(u)), asked.join(' '));
  assert.ok(asked.some((u) => /wu-load-bg\.webp/.test(u)), 'the old backdrop');
  await ctx.close();
});

test('tab.html follows the kept brand', async () => {
  const on = await open('/tab.html');
  await on.page.evaluate(() => localStorage.setItem('wu-brand', 'Wrath Unleashed'));
  on.asked.length = 0;
  await on.page.goto(base + '/tab.html?m=busy&r=/');
  await on.page.waitForLoadState('networkidle');
  assert.equal(await on.page.evaluate(() => document.documentElement.className), 'ly-brand');
  assert.ok(!on.asked.some((u) => PAINTED.test(u)), on.asked.join(' '));
  await on.page.evaluate(() => localStorage.removeItem('wu-brand'));
  on.asked.length = 0;
  await on.page.goto(base + '/tab.html?m=busy&r=/');
  await on.page.waitForLoadState('networkidle');
  assert.equal(await on.page.evaluate(() => document.documentElement.className), '');
  assert.ok(on.asked.some((u) => /wu-load-orion/.test(u)) && !on.asked.includes('/leyline-look.css'));
  await on.ctx.close();
});

test('tab.html with ?b=1 (wrath-early.js adds it while the switch is on): flat even with nothing kept', async () => {
  const { ctx, page, asked } = await open('/tab.html?m=busy&b=1&r=/');
  assert.equal(await page.evaluate(() => localStorage.getItem('wu-brand')), null);
  assert.equal(await page.evaluate(() => document.documentElement.className), 'ly-brand');
  assert.equal(await page.evaluate(() => document.title), 'Leyline');
  assert.ok(!asked.some((u) => PAINTED.test(u)), asked.join(' '));
  await ctx.close();
});

test('wrath-early.js: the note page address carries b=1 only while the switch is on', () => {
  const src = fs.readFileSync(path.join(WWW, 'wrath-early.js'), 'utf8');
  assert.match(src, /var lyOn = \(window\.__wenilla_env \|\| \{\}\)\.brand === 'leyline';/);
  assert.match(src, /'\.\/tab\.html\?m=' \+ m \+ \(lyOn \? '&b=1' : ''\) \+ '&r='/);
});
