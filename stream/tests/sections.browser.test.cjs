// Headless Chromium tests (Playwright) for "Download this section" (www-files/sections.js):
// the tier index, downloading a tier into Cache Storage with progress, the client's blocking XHR
// served from the cache (no server hit, exact bytes, a body bigger than the shared arena), HEAD,
// fetch(), names not downloaded going to the network, "Remove downloaded sections", the panel,
// no install without the index or without cross-origin isolation, and the streamed page
// (www-files/index.html + boot.js + ownfiles.js) with a stub client.
//
//   node --test tests/sections.browser.test.cjs          (from the stream folder)
//   WENILLA_WEB=<tree>/web  also copies wasi_stubs.js, platform.js and bridge.js from the tree for
//   the page test (otherwise small stand-ins are used).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..', 'www-files');
const SITE = fs.mkdtempSync(path.join(os.tmpdir(), 'sections-site-'));
for (const f of fs.readdirSync(ROOT)) if (fs.statSync(path.join(ROOT, f)).isFile()) fs.copyFileSync(path.join(ROOT, f), path.join(SITE, f));

// The slice: tier 2 has three files, one of them 9 MiB (bigger than the 8 MiB arena) with every byte value.
const big = Buffer.alloc(9 * 1024 * 1024);
for (let i = 0; i < big.length; i++) big[i] = (i * 7 + 3) & 0xff;
const FILES = {
  'World\\Maps\\Azeroth\\Azeroth_32_48.adt': Buffer.from([0x4d, 0x56, 0x45, 0x52, 0x80, 0xff, 0x00, 0x7f, 0xc3]),
  'Creature\\Wolf\\Wolf.m2': Buffer.from('MD20 wolf model'),
  'World\\Big\\Big.blp': big,
  'DBFilesClient\\Map.dbc': Buffer.from('WDBC map'),
};
const TIER2 = ['World\\Maps\\Azeroth\\Azeroth_32_48.adt', 'Creature\\Wolf\\Wolf.m2', 'World\\Big\\Big.blp'];
const tierTxt = `# tier 2 Northshire Valley\t${TIER2.length}\t${TIER2.reduce((a, n) => a + FILES[n].length, 0)}\n` +
  TIER2.map((n) => `${FILES[n].length}\t${n}\n`).join('');
const INDEX = JSON.stringify([{ tier: 0, name: 'base', files: 1, bytes: 8 },
  { tier: 2, name: 'Northshire Valley', files: TIER2.length, bytes: TIER2.reduce((a, n) => a + FILES[n].length, 0) }]);

fs.writeFileSync(path.join(SITE, 'harness.html'), `<!doctype html><meta charset="utf-8"><title>harness</title>
<body style="background:#000"><button id="dl" hidden>download sections</button>
<script type="module">
  import * as S from './sections.js';
  window.S = S;
  window.syncGet = (name) => {
    const x = new XMLHttpRequest();
    x.open('GET', '/data/' + encodeURIComponent(name), false);
    x.overrideMimeType('text/plain; charset=x-user-defined');
    x.send();
    const t = x.responseText || '';
    let h = 0; for (let i = 0; i < t.length; i++) h = (Math.imul(h, 31) + (t.charCodeAt(i) & 0xff)) >>> 0;
    return { status: x.status, length: t.length, hash: h, type: x.getResponseHeader('content-type') };
  };
  window.syncHead = (name) => { const x = new XMLHttpRequest(); x.open('HEAD', '/data/' + encodeURIComponent(name), false); x.send(); return x.status; };
  S.installSections().then((r) => { window.__installed = r; S.mountSectionsUi(document.getElementById('dl')); document.title = 'ready'; });
</script>`);
const hashBytes = (b) => { let h = 0; for (const v of b) h = (Math.imul(h, 31) + v) >>> 0; return h; };

function startServer({ isolated = true, tiers = true } = {}) {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm' };
  const hits = {};
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    const base = isolated ? { 'cross-origin-opener-policy': 'same-origin', 'cross-origin-embedder-policy': 'require-corp',
      'cross-origin-resource-policy': 'same-origin' } : {};
    if (url.pathname.startsWith('/data/')) {
      const raw = url.pathname.slice(6);
      hits[raw] = (hits[raw] || 0) + 1;
      if (raw === '__tier/index.json' && tiers) { res.writeHead(200, { ...base, 'content-type': 'application/json', 'cache-control': 'no-cache' }); return res.end(INDEX); }
      if (raw === '__tier/2.txt' && tiers) { res.writeHead(200, { ...base, 'content-type': 'text/plain', 'cache-control': 'no-cache' }); return res.end(tierTxt); }
      if (raw.startsWith('__')) { res.writeHead(404, base); return res.end(); }
      const name = decodeURIComponent(raw).replace(/\//g, '\\');
      const body = FILES[name];
      if (!body || server.dataDown) { res.writeHead(server.dataDown ? 503 : 404, base); return res.end(); }
      // no-store here, so a hit the test does not expect cannot come from the HTTP cache either
      res.writeHead(200, { ...base, 'content-type': 'application/octet-stream', 'cache-control': 'no-store', 'content-length': body.length });
      return res.end(req.method === 'HEAD' ? undefined : body);
    }
    const file = path.join(SITE, path.normalize(url.pathname).replace(/^[/\\]+/, '') || 'index.html');
    if (!file.startsWith(SITE) || !fs.existsSync(file)) { res.writeHead(404, base); return res.end(); }
    res.writeHead(200, { ...base, 'content-type': types[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
    res.end(fs.readFileSync(file));
  });
  server.hits = hits;
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(server, page0 = 'harness.html') {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const base = `http://127.0.0.1:${server.address().port}`;
  await page.goto(`${base}/${page0}`);
  return { ctx, page, base, errors };
}
const enc = (n) => encodeURIComponent(n);

test('download a section, then the client reads it from the cache', async () => {
  const server = await startServer();
  const { ctx, page, errors } = await open(server);
  try {
    await page.waitForFunction(() => document.title === 'ready');
    assert.equal((await page.evaluate(() => window.__installed)).installed, true);
    assert.equal(await page.isVisible('#dl'), true, 'the button shows when the server lists tiers');
    const progress = await page.evaluate(async () => {
      const seen = [];
      const r = await window.S.downloadTier(2, (p) => seen.push(p));
      return { r, first: seen[0], last: seen[seen.length - 1], n: seen.length };
    });
    assert.equal(progress.r.files, 3);
    assert.equal(progress.r.failed, 0);
    assert.equal(progress.first.doneBytes, 0);
    assert.equal(progress.last.doneBytes, progress.last.bytes);
    assert.equal(progress.last.bytes, TIER2.reduce((a, n) => a + FILES[n].length, 0));
    const status = await page.evaluate(() => window.S.sectionsStatus());
    assert.equal(status[2].done, true);
    // From here the server's /data is down: everything downloaded must come from the cache.
    server.dataDown = true;
    const before = { ...server.hits };
    for (const n of TIER2) {
      const r = await page.evaluate((n) => window.syncGet(n), n);
      assert.equal(r.status, 200, n);
      assert.equal(r.length, FILES[n].length, n);
      assert.equal(r.hash, hashBytes(FILES[n]), n);
    }
    assert.equal(await page.evaluate((n) => window.syncHead(n), TIER2[1]), 200);
    const t = await page.evaluate((n) => window.syncGet(n).type, TIER2[2]);
    assert.equal(t, 'image/x-blp');
    const f = await page.evaluate(async (u) => { const r = await fetch(u); return [r.status, (await r.arrayBuffer()).byteLength]; }, '/data/' + enc(TIER2[1]));
    assert.deepEqual(f, [200, FILES[TIER2[1]].length]);
    assert.deepEqual(server.hits, before, 'no request reached the server');
    // A name not downloaded still goes to the network (down: 503).
    assert.equal((await page.evaluate(() => window.syncGet('DBFilesClient\\Map.dbc'))).status, 503);
    server.dataDown = false;
    assert.equal((await page.evaluate(() => window.syncGet('DBFilesClient\\Map.dbc'))).status, 200);
    // Survives a reload (Cache Storage, not memory).
    await page.reload();
    await page.waitForFunction(() => document.title === 'ready');
    server.dataDown = true;
    assert.equal((await page.evaluate((n) => window.syncGet(n), TIER2[0])).hash, hashBytes(FILES[TIER2[0]]));
    // Remove downloaded sections: the cache goes, reads go to the network again.
    await page.evaluate(() => window.S.removeSections());
    assert.equal(await page.evaluate(() => caches.has('wu-sections-v1')), false);
    assert.equal((await page.evaluate((n) => window.syncGet(n), TIER2[0])).status, 503);
    server.dataDown = false;
    assert.equal((await page.evaluate((n) => window.syncGet(n), TIER2[0])).status, 200);
    assert.deepEqual(errors, []);
  } finally {
    await ctx.close();
    server.close();
  }
});

test('the panel: sizes, progress, downloaded mark, remove', async () => {
  const server = await startServer();
  const { ctx, page, errors } = await open(server);
  try {
    await page.waitForFunction(() => document.title === 'ready');
    await page.click('#dl');
    await page.waitForSelector('#wu-sections');
    const text = await page.textContent('#wu-sections');
    assert.match(text, /Northshire Valley/);
    assert.match(text, /9\.0 MB/);
    assert.match(text, /browser storage in use/);
    const rows = await page.$$('#wu-sections .row');
    await rows[1].$('button').then((b) => b.click());
    await page.waitForFunction(() => /downloaded, /.test(document.querySelector('#wu-sections').textContent), null, { timeout: 30000 });
    assert.match(await page.textContent('#wu-sections'), /✓ downloaded/);
    assert.equal(await page.$eval('#wu-sections .bar > i', (e) => e.style.width), '100%');
    await page.screenshot({ path: path.join(os.tmpdir(), 'sections-panel.png') });
    await page.click('text=Remove downloaded sections');
    await page.waitForFunction(() => /Removed\./.test(document.querySelector('#wu-sections').textContent));
    assert.doesNotMatch(await page.textContent('#wu-sections'), /✓ downloaded/);
    assert.equal(await page.evaluate(() => caches.has('wu-sections-v1')), false);
    assert.deepEqual(errors, []);
  } finally {
    await ctx.close();
    server.close();
  }
});

test('no tier index (own files, an old slice): nothing installed, no button', async () => {
  const server = await startServer({ tiers: false });
  const { ctx, page } = await open(server);
  try {
    await page.waitForFunction(() => document.title === 'ready');
    assert.equal((await page.evaluate(() => window.__installed)).installed, false);
    assert.equal(await page.isVisible('#dl'), false);
    assert.equal(await page.evaluate(() => XMLHttpRequest.name), 'XMLHttpRequest');
  } finally {
    await ctx.close();
    server.close();
  }
});

test('a page without cross-origin isolation: nothing installed', async () => {
  const server = await startServer({ isolated: false });
  const { ctx, page } = await open(server);
  try {
    await page.waitForFunction(() => document.title === 'ready');
    assert.equal((await page.evaluate(() => window.__installed)).installed, false);
    assert.equal(await page.evaluate(() => XMLHttpRequest.name), 'XMLHttpRequest');
  } finally {
    await ctx.close();
    server.close();
  }
});

test('the streamed page (index.html + boot.js + ownfiles.js + sections.js) boots a stub client from the cache', async () => {
  const WEB = process.env.WENILLA_WEB;
  if (WEB) {
    for (const f of ['wasi_stubs.js', 'platform.js', 'bridge.js']) fs.copyFileSync(path.join(WEB, f), path.join(SITE, f));
  } else {
    fs.writeFileSync(path.join(SITE, 'wasi_stubs.js'), 'export function bind() {}\n');
    fs.writeFileSync(path.join(SITE, 'platform.js'), 'export function requestPersistentStorage() {} export function installFullscreenToggle() {}\n');
    fs.writeFileSync(path.join(SITE, 'bridge.js'), 'export const wenilla = { notify: { enabled: false } };\n');
  }
  fs.writeFileSync(path.join(SITE, 'boot-manifest.json'), JSON.stringify({ names: ['DBFilesClient\\Map.dbc'] }));
  fs.writeFileSync(path.join(SITE, 'world-manifest.json'), JSON.stringify({ names: [] }));
  fs.writeFileSync(path.join(SITE, 'wenilla_bg.wasm'), Buffer.from([0, 0x61, 0x73, 0x6d, 1, 0, 0, 0]));
  fs.writeFileSync(path.join(SITE, 'wenilla.js'), `export default async function init({ module_or_path }) {
  const x = (n) => { const r = new XMLHttpRequest(); r.open('GET', location.origin + '/data/' + encodeURIComponent(n), false);
    r.overrideMimeType('text/plain; charset=x-user-defined'); r.send(); return r; };
  const a = x(${JSON.stringify(TIER2[0])});
  window.__stub = { module: module_or_path instanceof WebAssembly.Module, status: a.status, len: a.responseText.length,
    shim: XMLHttpRequest.name };
  setTimeout(() => window.__wenilla_progress && window.__wenilla_progress('ready'), 0);
  return { memory: new WebAssembly.Memory({ initial: 1 }) };
}`);
  // a wenilla-host origin: /data/__index answers JSON, so ownfiles stays out of the way
  FILES.__index = Buffer.from('[]');
  const server = await startServer();
  const origHandler = server.listeners('request')[0];
  server.removeAllListeners('request');
  server.on('request', (req, res) => {
    if (req.url === '/data/__index') {
      res.writeHead(200, { 'content-type': 'application/json', 'cross-origin-resource-policy': 'same-origin' });
      return res.end('[]');
    }
    return origHandler(req, res);
  });
  // first visit: download the tier from the harness, then open the real page with /data down
  const { ctx, page } = await open(server);
  try {
    await page.waitForFunction(() => document.title === 'ready');
    await page.evaluate(() => window.S.downloadTier(2));
    server.dataDown = true;
    await page.goto(page.url().replace('harness.html', 'index.html'));
    await page.waitForFunction(() => window.__stub, null, { timeout: 30000 });
    const stub = await page.evaluate(() => window.__stub);
    assert.deepEqual(stub, { module: true, status: 200, len: FILES[TIER2[0]].length, shim: 'SectionsXHR' });
    assert.equal(await page.isVisible('#dl'), true, 'the page shows "download sections"');
    assert.equal(await page.$('#wu-ownfiles'), null, 'no own-files chooser on a streamed origin');
  } finally {
    await ctx.close();
    server.close();
  }
});
