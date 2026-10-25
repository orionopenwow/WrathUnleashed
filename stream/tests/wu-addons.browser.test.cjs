// Headless Chromium test (Playwright) for "Your addons": drop an addon's zip on the page, see the
// "Drop to install addon" overlay and the result, reload, and a stub client (reading the page's
// body store the way benilla-formats web.rs does) finds the addon in /data/__index and reads its
// files; a zip with game data is refused; turning it off takes it out on the next load.
//
//   node --test tests/wu-addons.browser.test.cjs          (from the stream folder)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const zlib = require('node:zlib');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..', 'www-files');
const SITE = fs.mkdtempSync(path.join(os.tmpdir(), 'wu-addons-site-'));
for (const f of fs.readdirSync(ROOT)) if (fs.statSync(path.join(ROOT, f)).isFile()) fs.copyFileSync(path.join(ROOT, f), path.join(SITE, f));
fs.writeFileSync(path.join(SITE, 'drop.html'), `<!doctype html><meta charset="utf-8"><title>harness</title>
<body style="background:#000"><div id="ow-dock" class="open"><div id="ow-dock-panel"></div></div>
<script src="./wrath-early.js"></script>
<script type="module">
  // the stub client: starts when its download does (wrath-early.js holds it until the local addons
  // are read), then asks the body store first, as web.rs take_prefetched does
  await fetch('./wenilla_bg.wasm');
  const s = globalThis.__wenilla_prefetch;
  const read = (k) => { const b = s.get(k); return b ? new TextDecoder().decode(b) : null; };
  const names = JSON.parse(read('__index') || (await (await fetch('/data/__index')).text()));
  window.client = { names, toc: read('interface\\\\addons\\\\hello\\\\hello.toc'), lua: read('interface\\\\addons\\\\hello\\\\hello.lua') };
  document.title = 'ready';
</script>`);

function makeZip(entries) {
  const locals = [], centrals = [];
  let off = 0;
  for (const e of entries) {
    const data = Buffer.from(e.data);
    const body = zlib.deflateRawSync(data);
    const name = Buffer.from(e.name);
    const lh = Buffer.alloc(30), ch = Buffer.alloc(46);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(8, 8); lh.writeUInt32LE(zlib.crc32(data), 14);
    lh.writeUInt32LE(body.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(name.length, 26);
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(8, 10); ch.writeUInt32LE(zlib.crc32(data), 16);
    ch.writeUInt32LE(body.length, 20); ch.writeUInt32LE(data.length, 24); ch.writeUInt16LE(name.length, 28); ch.writeUInt32LE(off, 42);
    locals.push(lh, name, body); centrals.push(ch, name);
    off += 30 + name.length + body.length;
  }
  const cd = Buffer.concat(centrals), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(off, 16);
  return Buffer.concat([...locals, cd, end]);
}
const GOOD = makeZip([{ name: 'Hello/Hello.toc', data: '## Interface: 30300\n## Title: Hello\nHello.lua\n' },
  { name: 'Hello/Hello.lua', data: 'print("hello from a dropped addon")\n' }]);
const BAD = makeZip([{ name: 'Sneaky/Sneaky.toc', data: '## Interface: 30300\nSneaky.lua\n' },
  { name: 'Sneaky/Sneaky.lua', data: 'x' }, { name: 'Sneaky/Interface.blp', data: 'BLP2' }]);

function startServer() {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
  const hits = [];
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://x');
    hits.push(u.pathname);
    if (u.pathname === '/data/__index') {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify(['DBFilesClient\\Map.dbc', 'Interface\\AddOns\\WUPings\\WUPings.toc']));
    }
    if (u.pathname === '/wenilla_bg.wasm') { res.writeHead(200, { 'content-type': 'application/wasm' }); return res.end(Buffer.from([0, 0x61, 0x73, 0x6d])); }
    const p = path.join(SITE, path.normalize(u.pathname).replace(/^[/\\]+/, ''));
    if (!p.startsWith(SITE) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'content-type': types[path.extname(p)] || 'application/octet-stream' });
    res.end(fs.readFileSync(p));
  });
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r({ server, hits, url: `http://127.0.0.1:${server.address().port}` })));
}

async function drop(page, name, bytes, type = 'drop') {
  await page.evaluate(([name, b64, type]) => {
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bin], name, { type: 'application/zip' }));
    document.body.dispatchEvent(new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, [name, Buffer.from(bytes).toString('base64'), type]);
}

test('drop an addon zip: installed in this browser, the client loads it on the next page load', async (t) => {
  const { server, hits, url } = await startServer();
  const browser = await chromium.launch();
  t.after(async () => { await browser.close(); server.close(); });
  const page = await browser.newPage();
  page.on('pageerror', (e) => console.log('pageerror', e.message));
  const open = async () => {
    await page.goto(`${url}/drop.html?multitab=1&slimboot=0`);
    await page.waitForFunction(() => document.title === 'ready', null, { timeout: 15000 });
    return page.evaluate(() => window.client);
  };
  let client = await open();
  assert.ok(!client.names.some((n) => /Hello/.test(n)));
  assert.equal(client.toc, null);

  // the overlay while dragging
  await drop(page, 'Hello.zip', GOOD, 'dragenter');
  await page.waitForSelector('#wu-drop.on');
  assert.equal(await page.textContent('#wu-drop h2'), 'Drop to install addon');

  // a zip with game data in it is refused, and nothing is kept
  await drop(page, 'Sneaky.zip', BAD);
  await page.waitForSelector('#wu-addons .msg');
  const refused = await page.textContent('#wu-addons .msg');
  assert.match(refused, /Sneaky\.zip was not installed/);
  assert.match(refused, /Interface\.blp is a game texture/);
  assert.equal(await page.isVisible('#wu-drop.on'), false);

  // a good one is installed
  await drop(page, 'Hello.zip', GOOD);
  await page.waitForFunction(() => /Installed Hello/.test(document.querySelector('#wu-addons .msg')?.textContent || ''));
  assert.match(await page.textContent('#wu-addons'), /Hello.*loads next time/s);
  assert.ok(!hits.some((h) => /upload|Hello/i.test(h)), 'nothing is sent to the server');

  // next load: the client finds it in the name index and reads its files from the page's store
  client = await open();
  assert.ok(client.names.includes('Interface\\AddOns\\Hello\\Hello.toc'));
  assert.ok(client.names.includes('Interface\\AddOns\\Hello\\Hello.lua'));
  assert.match(client.toc, /## Interface: 30300/);
  assert.equal(client.lua, 'print("hello from a dropped addon")\n');
  assert.ok(!hits.some((h) => /AddOns.*Hello/i.test(decodeURIComponent(h))), 'its files never go to the server');

  // the dock's "Your addons" lists it; off, it is gone from the next load
  await page.click('#wu-addons-open');
  await page.waitForSelector('#wu-addons .row');
  assert.match(await page.textContent('#wu-addons .row'), /Hello.*loaded/s);
  await page.uncheck('#wu-addons .row input[type=checkbox]');
  await page.waitForFunction(() => /off next time/.test(document.querySelector('#wu-addons .row')?.textContent || ''));
  client = await open();
  assert.ok(!client.names.some((n) => /Hello/.test(n)));
  // remove
  await page.click('#wu-addons-open');
  await page.click('#wu-addons .row button');
  await page.waitForFunction(() => /No addons yet/.test(document.querySelector('#wu-addons')?.textContent || ''));
});
