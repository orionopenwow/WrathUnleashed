// Headless Chromium (Playwright): the first hop to a Beacon frames that realm's join page from the relay inside the
// game page, and the game page is cross-origin isolated (COOP same-origin + COEP require-corp, as wu-play serves it).
// The REAL relay (hosting/relay/wurelay, a python process) serves /join/<id> with COEP require-corp, CORP
// cross-origin and frame-ancestors <play origins>; the REAL page layer (www-files/wrath-early.js + wrath-page.js
// hopUi) frames it. Checked: the page stays crossOriginIsolated, the frame loads in hop mode, the login it hands
// back (postMessage to the game page only) is kept for that realm and the page reloads signed in, with no frame;
// a game page on an origin the relay doesn't list can't frame it; and without the relay's COEP/CORP headers the
// isolated game page refuses the frame (so those headers are what make the framed join page work).
//
//   node --test tests/hop-frame.browser.test.cjs          (from the stream folder; needs python3 and Playwright)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const WWW = path.join(__dirname, '..', 'www-files');
const HOSTING = path.join(__dirname, '..', '..', 'hosting');
const RID = 'abcdefghijklmnop';

function relay(playOrigins) {
  // the relay alone (no realm is needed to serve its join page), on a free port it prints
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hop-frame-relay-'));
  const code = `
import asyncio, os, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from wurelay import relay as r
async def main():
    rl = await r.Relay(r.Config(name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=0,
                               port_min=0, port_max=1, state_file=os.path.join(sys.argv[3], "state.json"),
                               play_origins=sys.argv[4].split(","), listing=False)).start()
    print(rl.http_port(), flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
`;
  const p = spawn('python3', ['-I', '-c', code, path.join(HOSTING, 'kit', 'tools'), path.join(HOSTING, 'relay'), tmp, playOrigins.join(',')],
    { stdio: ['ignore', 'pipe', 'inherit'] });
  return new Promise((resolve, reject) => {
    p.stdout.once('data', (d) => resolve({ port: Number(String(d).trim()), stop: () => p.kill() }));
    p.once('exit', (c) => reject(new Error('relay exited ' + c)));
  });
}

function gamePage(envRef) {
  // the stream site's shape: every response cross-origin isolated, like wu-play's static site. envRef.env is read per
  // request (the env names the relay's port, and the relay must know this page's origin first)
  const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' };
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://x');
    const h = { 'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp', 'Cache-Control': 'no-store' };
    if (u.pathname === '/' || u.pathname === '/index.html') {
      res.writeHead(200, { ...h, 'Content-Type': 'text/html' });
      return res.end(`<!doctype html><meta charset="utf-8"><title>game</title><body style="background:#000">
<script>window.__wenilla_env = ${JSON.stringify(envRef.env)};</script>
<script src="./wrath-early.js"></script>`);
    }
    const f = path.join(WWW, path.basename(u.pathname));
    if (fs.existsSync(f) && fs.statSync(f).isFile()) {
      res.writeHead(200, { ...h, 'Content-Type': types[path.extname(f)] || 'application/octet-stream' });
      return res.end(fs.readFileSync(f));
    }
    res.writeHead(404, h); res.end();
  });
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve({ port: srv.address().port, stop: () => srv.close() })));
}

const hopEnv = (relayPort) => ({ hop: RID, hop_name: 'Frost Haven', hop_ws: `ws://127.0.0.1:${relayPort}/ws/${RID}`,
  hop_join: `http://127.0.0.1:${relayPort}/join/${RID}?hop=1`, host: '127.0.0.1', home: 'https://play.example', slice: 'mini' });

test('the join page frames inside the isolated game page and hands the login back', async () => {
  // the game page on localhost:<port>, the relay on 127.0.0.1:<port>: two origins, as wrath.* and relay.* are
  const envRef = { env: {} };
  const site = await gamePage(envRef);
  const gameOrigin = `http://localhost:${site.port}`;
  const rl = await relay([gameOrigin]);
  envRef.env = hopEnv(rl.port);
  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const logs = [];
    page.on('console', (m) => logs.push(m.text()));
    await page.goto(`${gameOrigin}/?multitab=1`);
    await page.waitForSelector('#wu-hop-join iframe', { timeout: 15000 });
    assert.equal(await page.evaluate(() => self.crossOriginIsolated), true, 'the game page stays cross-origin isolated');
    let frame = null;
    for (let i = 0; i < 100 && !frame; i++) {
      frame = page.frames().find((f) => f.url().includes(`/join/${RID}`));
      if (!frame) await page.waitForTimeout(100);
    }
    assert.ok(frame, 'the join frame exists');
    await frame.waitForFunction(() => window.__wuHop && typeof window.__wuHop.handBack === 'function', null, { timeout: 15000 });
    assert.equal(await frame.evaluate(() => window.__wuHop.hop), true, 'hop mode: framed by an allowed game origin');
    // (the frame itself is not isolated: Chrome isolates a cross-origin frame only with allow="cross-origin-isolated",
    // and the join page needs no shared memory. What matters is that it loads at all: see the stripped-headers test.)
    // the player signs in (or makes an account) there: the frame posts the login to the game page only
    const nav = page.waitForNavigation({ timeout: 15000 });
    await frame.evaluate(() => window.__wuHop.handBack('frostfan1', 'Ab1!x9yz'));
    await nav;
    await page.waitForFunction(() => window.__wuHop && window.__wuHop.state, null, { timeout: 15000 });
    const st = await page.evaluate(() => ({ s: window.__wuHop.status(), kept: localStorage.getItem('wu.leyline.login.abcdefghijklmnop'),
      user: window.__wenilla_env.user, frame: !!document.querySelector('#wu-hop-join') }));
    assert.equal(st.s.hop.login, true);
    assert.equal(st.user, 'FROSTFAN1');
    assert.deepEqual(JSON.parse(st.kept), { user: 'FROSTFAN1', pass: 'Ab1!x9yz' });
    await page.waitForTimeout(500);
    assert.equal(await page.evaluate(() => !!document.querySelector('#wu-hop-join')), false, 'no join frame once a login is kept');
    assert.equal(await page.evaluate(() => !!document.querySelector('#wu-hop-bar')), true, 'the Back to Wrath bar');
  } finally {
    await browser.close();
    site.stop();
    rl.stop();
  }
});

test('a game page on an origin the relay does not list cannot frame the join page', async () => {
  const rl = await relay(['https://wrath.openvanilla.app']);
  const site = await gamePage({ env: hopEnv(rl.port) });
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(`http://localhost:${site.port}/?multitab=1`);
    await page.waitForSelector('#wu-hop-join iframe', { timeout: 15000 });
    await page.waitForTimeout(1500);
    const frame = page.frames().find((f) => f.url().includes(`/join/${RID}`));
    let hop = null;
    if (frame) { try { hop = await frame.evaluate(() => window.__wuHop && window.__wuHop.hop); } catch { hop = null; } }
    assert.notEqual(hop, true, 'frame-ancestors keeps the join page out of an unlisted page');
  } finally {
    await browser.close();
    site.stop();
    rl.stop();
  }
});

test('without the relay\'s COEP + CORP headers, the isolated game page blocks the frame', async () => {
  const envRef = { env: {} };
  const site = await gamePage(envRef);
  const gameOrigin = `http://localhost:${site.port}`;
  const rl = await relay([gameOrigin]);
  // a proxy in front of the relay that drops the two headers (what a CDN or a misconfigured Caddy could do)
  const proxy = http.createServer((req, res) => {
    const up = http.request({ host: '127.0.0.1', port: rl.port, path: req.url, method: req.method, headers: req.headers }, (r) => {
      const h = { ...r.headers };
      delete h['cross-origin-embedder-policy'];
      delete h['cross-origin-resource-policy'];
      res.writeHead(r.statusCode, h);
      r.pipe(res);
    });
    req.pipe(up);
  });
  await new Promise((r) => proxy.listen(0, '127.0.0.1', r));
  envRef.env = Object.assign(hopEnv(rl.port), { hop_join: `http://127.0.0.1:${proxy.address().port}/join/${RID}?hop=1` });
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(`${gameOrigin}/?multitab=1`);
    await page.waitForSelector('#wu-hop-join iframe', { timeout: 15000 });
    await page.waitForTimeout(1500);
    const frame = page.frames().find((f) => f.url().includes(`/join/${RID}`));
    let hop = null;
    if (frame) { try { hop = await frame.evaluate(() => window.__wuHop && window.__wuHop.hop); } catch { hop = null; } }
    assert.notEqual(hop, true, 'COEP require-corp on the game page blocks a frame without COEP/CORP');
  } finally {
    await browser.close();
    proxy.close();
    site.stop();
    rl.stop();
  }
});
