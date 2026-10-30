// Headless Chromium tests (Playwright) for the game-folder layer on the streamed page (www-files/ownfiles.js,
// ownfiles-worker.js, chain.js, mpq.js, wrath-early.js, sections.js), with real (small) MPQ archives in the
// browser's private file system standing in for the player's 3.3.5a game folder:
//   * streamed play first: no folder, the page asks the portal to keep the zone limit (layer=off);
//   * "Use my game folder" in the world: the card, the folder picked, one page load ("Opening the whole
//     world…"), the folder mounted silently from the remembered handle, the portal asked to lift the limit;
//   * the files: a slice name from the server, a folder name from the folder (no request), a name in neither a
//     404 with no request, /data/__index the union (in the client's body store), a slice name the server keeps
//     failing (after wrath-early.js's retries) from the folder, async fetch, a downloaded section (Cache
//     Storage, sections.js) still served from the cache;
//   * the tab reloaded mid-game (silent remount), the permission revoked (one click, or streamed play),
//     the worker killed (it comes back; if it can't, streamed play with a message and the limit back on),
//     a second tab (the one-tab guard: it never touches the realm), a 1.12 folder refused, Firefox/Safari
//     (no folder handles: the folder input, then "drop it once more" after the page load), the in-game ask
//     (WUUI_GAMEFOLDER_ASK through the bridge), the Lua state the game sees.
//
//   node --test stream/tests/ownfiles-layer.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const F = require('./mpq-fixture.cjs');

const ROOT = path.join(__dirname, '..', 'www-files');
const SITE = fs.mkdtempSync(path.join(os.tmpdir(), 'layer-site-'));
for (const f of fs.readdirSync(ROOT)) if (fs.statSync(path.join(ROOT, f)).isFile()) fs.copyFileSync(path.join(ROOT, f), path.join(SITE, f));

// The streamed slice: three names (one the folder has too, in a newer version) and the realm's own addon.
const SLICE = {
  'Textures\\Common.blp': Buffer.from('SLICE common (lite)'),
  'Interface\\AddOns\\ForeverUI\\FUI.lua': Buffer.from('-- realm addon'),
  'DBFilesClient\\Map.dbc': Buffer.from('WDBC slice map'),
};
const TIER = Object.keys(SLICE).slice(0, 1);
const tierTxt = `# tier 1 Dalaran\t1\t${SLICE[TIER[0]].length}\n${SLICE[TIER[0]].length}\t${TIER[0]}\n`;
const GAME = F.gameFolder({ root: 'Game' });
const OLD = F.vanillaFolder('Old');
const FIXTURE = new Map([...GAME, ...OLD].map((e) => [e.path, e.data]));
// on disk too, for the folder input (Firefox/Safari path)
const DISK = fs.mkdtempSync(path.join(os.tmpdir(), 'layer-game-'));
for (const e of GAME) { fs.mkdirSync(path.join(DISK, path.dirname(e.path)), { recursive: true }); fs.writeFileSync(path.join(DISK, e.path), e.data); }

fs.writeFileSync(path.join(SITE, 'play.html'), `<!doctype html><meta charset="utf-8"><title>loading</title>
<body style="background:#000"><button id="dl" hidden>download sections</button>
<script src="/__env.js"></script>
<script src="./wrath-early.js"></script>
<script type="module">
  import { ensureDataSource } from './ownfiles.js';
  import { installSections, mountSectionsUi } from './sections.js';
  const dec = new TextDecoder();
  // The client's reads, as benilla-formats web.rs makes them: the body store first, else a blocking XHR.
  window.clientRead = (name) => {
    const x = new XMLHttpRequest();
    x.open('GET', '/data/' + encodeURIComponent(name), false);
    x.overrideMimeType('text/plain; charset=x-user-defined');
    x.send();
    const t = x.responseText || '';
    return { status: x.status, text: Array.from(t, (c) => String.fromCharCode(c.charCodeAt(0) & 0xff)).join('') };
  };
  window.clientIndex = () => {
    const m = globalThis.__wenilla_prefetch;
    const v = m && m.get('__index');
    if (v) return { from: 'store', names: JSON.parse(dec.decode(v)) };
    const r = window.clientRead('__index');
    return { from: 'xhr', status: r.status, names: r.status === 200 ? JSON.parse(r.text) : [] };
  };
  const src = await ensureDataSource({ streamUrl: '/' }).then(async (s) => {
    if (!s || s.mode === 'host') { window.__sections = await installSections(); mountSectionsUi(document.getElementById('dl')); }
    return s;
  });
  window.__src = src;
  document.title = 'ready';
</script>`);

// The page's own folder in the browser's private file system (OPFS): a real FileSystemDirectoryHandle, which
// IndexedDB keeps like a picked folder and whose permission is 'granted'.
const OPFS = async (want) => {
  const root = await navigator.storage.getDirectory();
  const list = await (await fetch('/fixture/__list')).json();
  for (const p of list.filter((p) => p.split('/')[0] === want)) {
    let dir = root;
    const parts = p.split('/');
    for (const d of parts.slice(0, -1)) dir = await dir.getDirectoryHandle(d, { create: true });
    const fh = await dir.getFileHandle(parts[parts.length - 1], { create: true });
    const w = await fh.createWritable();
    await w.write(await (await fetch('/fixture/' + encodeURIComponent(p))).arrayBuffer());
    await w.close();
  }
  window.__gameDir = await root.getDirectoryHandle(want);
  window.showDirectoryPicker = async () => window.__gameDir;
  return true;
};

function startServer() {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
  const hits = {};
  const posts = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    const base = { 'cross-origin-opener-policy': 'same-origin', 'cross-origin-embedder-policy': 'require-corp',
      'cross-origin-resource-policy': 'same-origin' };
    if (url.pathname === '/__env.js') {
      res.writeHead(200, { ...base, 'content-type': 'application/javascript', 'cache-control': 'no-store' });
      return res.end(`window.__wenilla_env = ${JSON.stringify({ user: 'WR000123', pass: 'x', host: 'h', slice: 'mini', slice_tier: '4', layer: server.noLayer ? undefined : '1' })};`);
    }
    if (url.pathname === '/__gate' && req.method === 'POST') {
      let body = '';
      req.on('data', (c) => { body += c; });
      req.on('end', () => {
        const op = url.searchParams.get('layer');
        posts.push({ op, body, origin: req.headers.origin, type: req.headers['content-type'], page: req.headers.referer || '' });
        const ok = !server.realmDown && req.headers.origin === `http://127.0.0.1:${server.address().port}`;
        res.writeHead(ok ? 200 : 503, { ...base, 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok, state: ok ? (op === 'off' ? 'held' : 'lifted') : 'held' }));
      });
      return undefined;
    }
    if (url.pathname.startsWith('/fixture/')) {
      const p = decodeURIComponent(url.pathname.slice(9));
      if (p === '__list') { res.writeHead(200, { ...base, 'content-type': 'application/json' }); return res.end(JSON.stringify([...FIXTURE.keys()])); }
      const b = FIXTURE.get(p);
      res.writeHead(b ? 200 : 404, base);
      return res.end(b);
    }
    if (url.pathname.startsWith('/data/')) {
      const raw = url.pathname.slice(6);
      const name = decodeURIComponent(raw).replace(/\//g, '\\');
      hits[name] = (hits[name] || 0) + 1;
      if (raw === '__index') { res.writeHead(200, { ...base, 'content-type': 'application/json', 'cache-control': 'no-cache' }); return res.end(JSON.stringify(Object.keys(SLICE))); }
      if (raw === '__tier/index.json') { res.writeHead(200, { ...base, 'content-type': 'application/json' }); return res.end(JSON.stringify([{ tier: 1, name: 'Dalaran', files: 1, bytes: SLICE[TIER[0]].length }])); }
      if (raw === '__tier/1.txt') { res.writeHead(200, { ...base, 'content-type': 'text/plain' }); return res.end(tierTxt); }
      if (raw.startsWith('__')) { res.writeHead(404, base); return res.end(); }
      if (server.failing && server.failing.has(name)) { res.writeHead(503, base); return res.end(); }
      const body = SLICE[Object.keys(SLICE).find((k) => k.toLowerCase() === name.toLowerCase())];
      if (!body) { res.writeHead(404, base); return res.end(); }
      res.writeHead(200, { ...base, 'content-type': 'application/octet-stream', 'cache-control': 'no-store', 'content-length': body.length });
      return res.end(req.method === 'HEAD' ? undefined : body);
    }
    const file = path.join(SITE, path.normalize(url.pathname).replace(/^[/\\]+/, '') || 'play.html');
    if (!file.startsWith(SITE) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404, base); return res.end(); }
    res.writeHead(200, { ...base, 'content-type': types[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
    return res.end(fs.readFileSync(file));
  });
  server.hits = hits;
  server.posts = posts;
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(server, { query = '', init = null } = {}) {
  const ctx = await browser.newContext();
  if (init) await ctx.addInitScript(init);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  if (process.env.DBG) page.on('console', (m) => console.log('CONSOLE', m.text()));
  const base = `http://127.0.0.1:${server.address().port}`;
  await page.goto(`${base}/play.html${query}`);
  return { ctx, page, base, errors };
}
const ready = (page) => page.waitForFunction(() => document.title === 'ready', null, { timeout: 30000 });
const status = (page) => page.evaluate(() => window.__wuOwnFiles.status());
const read = (page, n) => page.evaluate((n) => window.clientRead(n), n);
const ops = (server) => server.posts.map((p) => p.op);
const NORTH = 'World\\Maps\\Northrend\\Northrend_30_30.adt';

/// Streamed play, then "Use my game folder" in the world: the card, the picker, one page load, the layer.
async function intoLayer(server, page) {
  await ready(page);
  await page.evaluate(OPFS, 'Game');
  // page.evaluate runs with a user gesture, like the in-game click: the picker opens at once (no card)
  await Promise.all([page.waitForEvent('load'), page.evaluate(() => { window.__wuOwnFiles.pick(); })]);
  await ready(page);
}

test('streamed first; "Use my game folder" in the world; the layer answers what the slice lacks', async () => {
  const server = await startServer();
  const { ctx, page, errors } = await open(server);
  try {
    await ready(page);
    let st = await status(page);
    assert.equal(st.mounted, false);
    assert.equal(st.mode, 'stream');
    assert.deepEqual(ops(server), ['off'], 'no folder: the portal keeps the zone limit');
    assert.equal(server.posts[0].type, 'application/json');
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'SLICE common (lite)');
    assert.equal((await read(page, NORTH)).status, 404, 'streamed: the slice has no Northrend');
    assert.equal(server.hits[NORTH], 1);

    await page.evaluate(OPFS, 'Game');
    // "Use my game folder" with the click's user activation live: the picker at once, then one page load
    await Promise.all([page.waitForEvent('load'), page.evaluate(() => { window.__wuOwnFiles.pick(); })]);
    await ready(page);
    st = await status(page);
    assert.equal(st.mounted, true, JSON.stringify(st));
    assert.equal(st.build, 12340);
    assert.equal(st.realm, 'lifted');
    assert.equal(st.remembered, true);
    assert.ok(st.counts.ownOnly > 3 && st.counts.slice === 3, JSON.stringify(st.counts));
    assert.deepEqual(ops(server), ['off', 'on'], 'after the page load: the folder, then the limit lifted');
    assert.equal(JSON.parse(server.posts[1].body).build, 12340);

    const idx = await page.evaluate(() => window.clientIndex());
    assert.equal(idx.from, 'store', 'the union is in the body store before the client asks');
    for (const n of [...Object.keys(SLICE), NORTH, 'World\\Big\\Huge.blp']) assert.ok(idx.names.includes(n), n);
    const before = server.hits[NORTH];
    const north = await read(page, NORTH);
    assert.deepEqual(north, { status: 200, text: 'icecrown glacier tile' });
    assert.equal(server.hits[NORTH], before, 'the folder answered: no request');
    assert.equal((await read(page, 'World\\Big\\Huge.blp')).text.length, 70000);
    const c = server.hits['Textures\\Common.blp'] || 0;
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'SLICE common (lite)', 'slice first');
    assert.equal(server.hits['Textures\\Common.blp'], c + 1);
    assert.equal((await read(page, 'Interface\\AddOns\\ForeverUI\\FUI.lua')).text, '-- realm addon');
    assert.equal((await read(page, 'Nowhere\\Nothing.m2')).status, 404);
    assert.equal(server.hits['Nowhere\\Nothing.m2'], undefined, 'in neither: no request');
    const f = await page.evaluate(async (n) => { const r = await fetch('/data/' + encodeURIComponent(n)); return [r.status, await r.text()]; }, NORTH);
    assert.deepEqual(f, [200, 'icecrown glacier tile']);
    const f2 = await page.evaluate(async () => { const r = await fetch('/data/DBFilesClient%5CMap.dbc'); return [r.status, await r.text()]; });
    assert.deepEqual(f2, [200, 'WDBC slice map']);

    // the server keeps failing a slice name: wrath-early.js retries, then the folder's copy
    server.failing = new Set(['Textures\\Common.blp']);
    const r0 = await page.evaluate(() => ({ ...window.__wuRetries }));
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'common-v4 (patch-3)');
    const r1 = await page.evaluate(() => ({ ...window.__wuRetries }));
    assert.equal(r1.retried - r0.retried, 2, 'the sync retries ran first');
    // ... and a slice name the folder lacks still says what the server said
    server.failing = new Set(['DBFilesClient\\Map.dbc']);
    assert.equal((await read(page, 'DBFilesClient\\Map.dbc')).status, 503);
    server.failing = null;

    // the tab reloaded mid-game: the folder comes back with no card
    await page.reload();
    await ready(page);
    st = await status(page);
    assert.equal(st.mounted, true);
    assert.equal(await page.isVisible('#wu-ownfiles'), false);
    assert.deepEqual(ops(server), ['off', 'on', 'on']);
    assert.equal((await read(page, NORTH)).text, 'icecrown glacier tile');
    assert.deepEqual(errors, []);
  } finally {
    await ctx.close();
    server.close();
  }
});

test('a downloaded section still comes from Cache Storage with the layer on', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server);
  try {
    await intoLayer(server, page);
    await page.evaluate(async () => {
      const c = await caches.open('wu-sections-v1');
      await c.put('/data/' + encodeURIComponent('Textures\\Common.blp'), new Response('CACHED section copy'));
    });
    await page.reload();
    await ready(page);
    assert.equal((await page.evaluate(() => window.__sections)).installed, true);
    const before = server.hits['Textures\\Common.blp'] || 0;
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'CACHED section copy');
    assert.equal(server.hits['Textures\\Common.blp'] || 0, before, 'no request');
    assert.equal((await read(page, NORTH)).text, 'icecrown glacier tile', 'the layer under it still answers');
  } finally {
    await ctx.close();
    server.close();
  }
});

test('the worker dies: it comes back; when it cannot, streamed play with a message and the limit back on', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server);
  try {
    await intoLayer(server, page);
    await page.evaluate(() => { const T = window.__wuOwnFiles.TIMING; T.deadMs = 800; T.restartWaitMs = 50; });
    await page.evaluate(() => window.__wuOwnFiles._engine().worker.terminate());
    const t0 = Date.now();
    const r = await read(page, NORTH);
    assert.ok(Date.now() - t0 < 10000, 'the blocked read gave up on the dead worker');
    assert.equal(r.status, 404, 'meanwhile: passed to the server');
    await page.waitForFunction(() => window.__wuOwnFiles.status().dead === null && window.__wuOwnFiles.status().stats.restarts === 1);
    assert.match(await page.textContent('#wu-layer-toast'), /Your game folder is back/);
    assert.equal((await read(page, NORTH)).text, 'icecrown glacier tile');
    // now the restart fails too
    await page.evaluate(() => { const e = window.__wuOwnFiles._engine(); e.restart = async () => false; e.worker.terminate(); });
    await read(page, NORTH);
    await page.waitForFunction(() => window.__wuOwnFiles.status().mounted === false);
    await page.waitForFunction(() => /Back to streamed play/.test(document.getElementById('wu-layer-toast')?.textContent || ''));
    assert.ok(ops(server).slice(-1)[0] === 'off', 'the zone limit asked back: ' + ops(server));
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'SLICE common (lite)', 'the slice still plays');
  } finally {
    await ctx.close();
    server.close();
  }
});

test('the permission is gone on the next visit: one click, or streamed play', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server);
  try {
    await intoLayer(server, page);
    // the browser no longer grants it (and refuses when asked)
    await ctx.addInitScript(() => {
      const P = FileSystemHandle.prototype;
      P.queryPermission = async () => 'prompt';
      P.requestPermission = async () => 'denied';
    });
    await page.reload();
    await page.waitForSelector('#wu-ownfiles [data-act="continue"]');
    assert.match(await page.textContent('#wu-ownfiles'), /Your browser asks once more/);
    assert.match(await page.textContent('#wu-ownfiles [data-act="stream"]'), /Play streamed \(\d+ s\)/);
    await page.click('#wu-ownfiles [data-act="continue"]');
    await page.waitForFunction(() => /did not allow reading the folder/.test(document.querySelector('#wu-ownfiles .msg').textContent));
    await page.click('#wu-ownfiles [data-act="stream"]');
    await ready(page);
    assert.equal((await status(page)).mounted, false);
    assert.equal(ops(server).slice(-1)[0], 'off');
  } finally {
    await ctx.close();
    server.close();
  }
});

test('a second tab never touches the realm (the one-tab guard)', async () => {
  const server = await startServer();
  const { ctx, page, base } = await open(server);
  try {
    await intoLayer(server, page);
    const n = server.posts.length;
    const two = await ctx.newPage();
    await two.goto(`${base}/play.html`);
    await two.waitForURL(/tab\.html\?m=busy/);
    await new Promise((r) => setTimeout(r, 1500));
    assert.equal(server.posts.length, n, 'no layer=off from the tab that gave way: ' + ops(server));
    assert.equal((await status(page)).mounted, true);
  } finally {
    await ctx.close();
    server.close();
  }
});

test('a 1.12 folder on the 3.3.5a page is refused, with no page load', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server);
  try {
    await ready(page);
    await page.evaluate(OPFS, 'Old');
    // from a timer: the card, and its Choose folder button
    await page.evaluate(() => { setTimeout(() => window.__wuOwnFiles.pick(), 6000); });
    await page.waitForSelector('#wu-ownfiles [data-act="choose"]', { timeout: 15000 });
    assert.match(await page.textContent('#wu-ownfiles'), /Streamed play covers Dalaran, the capitals and the starting areas/);
    assert.match(await page.textContent('#wu-ownfiles'), /Nothing is uploaded/);
    assert.equal(await page.getAttribute('#wu-ownfiles a.help', 'href'), 'https://play.openvanilla.app/wrath/docs/play#use-your-own-game-folder-to-go-anywhere');
    await page.click('#wu-ownfiles [data-act="choose"]');
    await page.waitForFunction(() => /1\.12 game folder/.test(document.querySelector('#wu-ownfiles .msg').textContent));
    const t = await page.textContent('#wu-ownfiles .msg');
    assert.match(t, /needs a 3\.3\.5a game folder \(build 12340\)/);
    assert.doesNotMatch(await page.textContent('#wu-ownfiles'), /warcraft|blizzard|lich king|\bwow\b/i);
    await page.click('#wu-ownfiles [data-act="stream"]');
    assert.equal((await status(page)).mounted, false);
    assert.deepEqual(ops(server), ['off']);
  } finally {
    await ctx.close();
    server.close();
  }
});

test('Firefox/Safari (no folder handles): the folder input, one page load, then the folder once more', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server, { init: () => { delete window.showDirectoryPicker; delete DataTransferItem.prototype.getAsFileSystemHandle; } });
  try {
    await ready(page);
    page.evaluate(() => { window.__wuOwnFiles.pick(); });
    await page.waitForSelector('#wu-ownfiles [data-act="choose"]');
    assert.equal((await status(page)).keepsFolders, false);
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('#wu-ownfiles [data-act="choose"]')]);
    await Promise.all([page.waitForEvent('load'), chooser.setFiles(path.join(DISK, 'Game'))]);
    await page.waitForSelector('#wu-ownfiles [data-act="choose"]');
    assert.match(await page.textContent('#wu-ownfiles h1'), /Drop your game folder once more/);
    const [chooser2] = await Promise.all([page.waitForEvent('filechooser'), page.click('#wu-ownfiles [data-act="choose"]')]);
    await chooser2.setFiles(path.join(DISK, 'Game'));
    await ready(page);
    const st = await status(page);
    assert.equal(st.mounted, true, JSON.stringify(st));
    assert.equal(st.build, 12340);
    assert.equal((await read(page, NORTH)).text, 'icecrown glacier tile');
    assert.deepEqual(ops(server), ['off', 'on']);
    // the next visit: these browsers ask each time (with a countdown into streamed play)
    await page.reload();
    await page.waitForSelector('#wu-ownfiles');
    assert.match(await page.textContent('#wu-ownfiles'), /Firefox and Safari ask for the folder on each visit/);
    assert.match(await page.textContent('#wu-ownfiles [data-act="stream"]'), /Play streamed \(\d+ s\)/);
  } finally {
    await ctx.close();
    server.close();
  }
});

test('the game sees the layer, and its "Use my game folder" opens the card', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server);
  try {
    await intoLayer(server, page);
    const seen = await page.evaluate(async () => {
      const m = await import('./wrath-page.js');
      const chunks = [];
      const stub = { ready: true, state: {}, lua: async (c) => { chunks.push(c); return [null]; } };
      const h = m.watchGameFolder(stub, { pollMs: 0 });
      await h.tick();
      return chunks[0];
    });
    assert.match(seen, /WUUI_GAMEFOLDER = \{ page = true, on = true, build = 12340, label = "Game", ownOnly = \d+, realm = "lifted", keeps = true, allowed = true \}/);
    assert.match(seen, /WUUI_GAMEFOLDER_ASK = nil/);
    await page.evaluate(() => window.__wuOwnFiles.forget());
  } finally {
    await ctx.close();
    server.close();
  }
  // streamed, the game asks: the card opens
  const server2 = await startServer();
  const o = await open(server2);
  try {
    await ready(o.page);
    await o.page.evaluate(async () => {
      const m = await import('./wrath-page.js');
      const stub = { ready: true, state: {}, lua: async () => ['pick'] };
      await m.watchGameFolder(stub, { pollMs: 0 }).tick();
    });
    await o.page.waitForSelector('#wu-ownfiles [data-act="choose"]');
  } finally {
    await o.ctx.close();
    server2.close();
  }
});

test('no layer route in the env (an older portal): streamed play exactly as before', async () => {
  const server = await startServer();
  server.noLayer = true;
  const { ctx, page } = await open(server);
  try {
    await ready(page);
    assert.deepEqual(ops(server), []);
    assert.equal((await page.evaluate(() => window.__wuOwnFiles.allowed())), false);
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'SLICE common (lite)');
  } finally {
    await ctx.close();
    server.close();
  }
});

test('own mode (?ownfiles=1) still plays from the folder alone, and refuses a wrong build', async () => {
  const server = await startServer();
  const { ctx, page } = await open(server, { query: '?ownfiles=1' });
  try {
    await page.waitForSelector('#wu-ownfiles [data-act="choose"]');
    assert.match(await page.textContent('#wu-ownfiles h1'), /Use my own game files/);
    await page.evaluate(OPFS, 'Old');
    await page.click('#wu-ownfiles [data-act="choose"]');
    await page.waitForFunction(() => /1\.12 game folder/.test(document.querySelector('#wu-ownfiles .msg').textContent));
    await page.evaluate(OPFS, 'Game');
    await page.click('#wu-ownfiles [data-act="choose"]');
    await ready(page);
    const st = await status(page);
    assert.equal(st.mode, 'own');
    assert.equal(st.mounted, true);
    const before = { ...server.hits };
    assert.equal((await read(page, 'Textures\\Common.blp')).text, 'common-v4 (patch-3)', 'own mode: the folder, not the slice');
    assert.equal((await read(page, NORTH)).text, 'icecrown glacier tile');
    assert.deepEqual(server.hits, before, 'own mode: no /data request at all');
    const idx = await page.evaluate(() => window.clientIndex());
    assert.ok(idx.names.includes(NORTH) && !idx.names.includes('Interface\\AddOns\\ForeverUI\\FUI.lua'));
    assert.deepEqual(ops(server), [], 'own mode never posts the layer');
    assert.equal((await page.evaluate(() => window.__sections)), undefined, 'sections stay off in own mode');
  } finally {
    await ctx.close();
    server.close();
  }
});
