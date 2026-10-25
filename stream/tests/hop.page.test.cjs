// Realm hopping in the page layer, in node (no browser): wrath-early.js's leyline-hop block (the client's
// /ws/<port> rewritten to the relay bridge, the realm's own login filled in from this browser's storage, never
// the Wrath one) and wrath-page.js's hop helpers (the Join cue from the game, where a hop goes, the join
// page's login message checks).
//
//   node --test tests/hop.page.test.cjs          (from the stream folder)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { pathToFileURL } = require('node:url');

const WWW = path.join(__dirname, '..', 'www-files');
const early = fs.readFileSync(path.join(WWW, 'wrath-early.js'), 'utf8');
const HOP_SRC = early.slice(early.indexOf('// >>> leyline-hop'), early.indexOf('// <<< leyline-hop'));
const RID = 'abcdefghijklmnop';

function storage(init = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), m };
}

function page(env, { store = storage(), protocol = 'https:', host = 'wrath.example' } = {}) {
  const opened = [];
  function FakeWS(url, protocols) { this.url = url; this.protocols = protocols; opened.push(url); }
  FakeWS.OPEN = 1;
  const win = { __wenilla_env: env, location: { protocol, host }, localStorage: store, WebSocket: FakeWS, console };
  win.window = win;
  vm.runInNewContext(HOP_SRC, win);
  return { win, opened, FakeWS };
}

const hopEnv = () => ({ hop: RID, hop_name: 'Frost Haven', hop_ws: `wss://relay.example/ws/${RID}`,
  hop_join: `https://relay.example/join/${RID}?hop=1`, host: 'relay.example', home: 'https://play.example' });

test('a hop session points the client at the bridge: auth and world', () => {
  const { win, opened, FakeWS } = page(hopEnv());
  assert.equal(win.__wuHop.state.id, RID);
  const a = new win.WebSocket('wss://wrath.example/ws/3724?host=relay.example');
  const w = new win.WebSocket('wss://wrath.example/ws/40001?host=relay.example', ['binary']);
  assert.deepEqual(opened, [`wss://relay.example/ws/${RID}/auth`, `wss://relay.example/ws/${RID}/world`]);
  assert.ok(a instanceof FakeWS && a instanceof win.WebSocket, 'instanceof still holds (web-sys dyn_into)');
  assert.deepEqual(w.protocols, ['binary']);
  assert.equal(win.WebSocket.OPEN, 1);
  new win.WebSocket('wss://elsewhere.example/ws/3724');   // only this page's own /ws/<port>
  new win.WebSocket('wss://wrath.example/other');
  assert.deepEqual(opened.slice(2), ['wss://elsewhere.example/ws/3724', 'wss://wrath.example/other']);
});

test('the realm login comes from this browser only; the Wrath one never goes there', () => {
  const env = Object.assign(hopEnv(), { user: 'WR000123', pass: 'Pa55word1234abcd' });   // should never be sent, but
  const { win } = page(env);
  assert.equal(win.__wuHop.state.login, false);
  assert.equal(env.user, undefined);
  assert.equal(env.pass, undefined);
  const store = storage({ ['wu.leyline.login.' + RID]: JSON.stringify({ user: 'friend1', pass: 'hunter22' }) });
  const env2 = hopEnv();
  const p2 = page(env2, { store });
  assert.equal(p2.win.__wuHop.state.login, true);
  assert.equal(env2.user, 'FRIEND1');
  assert.equal(env2.pass, 'hunter22');
  // another realm's login is not this one's
  const env3 = Object.assign(hopEnv(), { hop: 'qrstuvwxyz234567', hop_ws: 'wss://relay.example/ws/qrstuvwxyz234567' });
  page(env3, { store });
  assert.equal(env3.user, undefined);
});

test('save, junk and forget', () => {
  const { win } = page(hopEnv());
  const s = storage();
  const H = win.__wuHop;
  assert.equal(H.saveLogin(s, RID, 'friend1', 'hunter22'), true);
  assert.equal(JSON.stringify(H.savedLogin(s, RID)), JSON.stringify({ user: "FRIEND1", pass: "hunter22" }));
  assert.equal(H.saveLogin(s, RID, 'x', 'hunter22'), false);
  assert.equal(H.saveLogin(s, '../x', 'friend1', 'hunter22'), false);
  assert.equal(H.saveLogin(s, RID, 'friend1', 'has space'), false);
  s.setItem('wu.leyline.login.' + RID, '{not json');
  assert.equal(H.savedLogin(s, RID), null);
  H.saveLogin(s, RID, 'friend1', 'hunter22');
  H.forgetLogin(s, RID);
  assert.equal(H.savedLogin(s, RID), null);
});

test('no hop, or a bad relay address: nothing changes', () => {
  const env = { user: 'WR000123', pass: 'Pa55word1234abcd', host: 'play.example' };
  const p = page(env);
  assert.equal(p.win.__wuHop.state, null);
  assert.equal(env.user, 'WR000123');
  new p.win.WebSocket('wss://wrath.example/ws/3724');
  assert.deepEqual(p.opened, ['wss://wrath.example/ws/3724']);
  for (const bad of ['wss://relay.example/ws/qrstuvwxyz234567', 'wss://relay.example/r/x', 'javascript:alert(1)',
    `ws://relay.example/ws/${RID}`]) {   // another realm's bridge, not a bridge, not a URL, ws: on an https page
    const q = page(Object.assign(hopEnv(), { hop_ws: bad }));
    assert.equal(q.win.__wuHop.state, null, bad);
    new q.win.WebSocket('wss://wrath.example/ws/3724');
    assert.deepEqual(q.opened, ['wss://wrath.example/ws/3724'], bad);
  }
  const dev = page(Object.assign(hopEnv(), { hop_ws: `ws://127.0.0.1:8080/ws/${RID}` }), { protocol: 'http:', host: '127.0.0.1:8090' });
  assert.ok(dev.win.__wuHop.state, 'ws: is fine on a plain-http dev page');
});

test('wrath-page.js: the Join cue, where a hop goes, the login message', async () => {
  globalThis.window = { __wenilla_env: {} };
  const m = await import(pathToFileURL(path.join(WWW, 'wrath-page.js')).href);
  assert.equal(m.hopTarget('wrath'), 'wrath');
  assert.equal(m.hopTarget(RID), RID);
  assert.equal(m.hopTarget('ABCDEFGHIJKLMNOP'), null);
  assert.equal(m.hopTarget('https://evil'), null);

  assert.equal(m.hopUrl(RID, {}), `https://play.openvanilla.app/wrath?go=r:${RID}`);
  assert.equal(m.hopUrl(RID, { mode: 'own' }), `https://play.openvanilla.app/wrath/play?mode=own&go=r:${RID}`);
  assert.equal(m.hopUrl('wrath', { home: 'https://play.example', hop: RID }), 'https://play.example/wrath');
  assert.equal(m.hopUrl('wrath', { home: 'https://play.example', mode: 'own' }), 'https://play.example/wrath/play?mode=own');
  assert.equal(m.hopUrl('wrath', { home: 'javascript:alert(1)//' }), 'https://play.openvanilla.app/wrath');
  assert.equal(m.hopUrl('nope', {}), null);

  assert.equal(m.hopEcho(['WULY', `H:${RID}`, 'WHISPER', 'Tester']), RID);
  assert.equal(m.hopEcho({ args: ['WULY', 'H:wrath', 'WHISPER', 'Tester'] }), 'wrath');
  assert.equal(m.hopEcho(['WULY', 'L', 'WHISPER', 'Tester']), null);
  assert.equal(m.hopEcho(['WULY', `H:${RID}`, 'GUILD', 'Tester']), null);
  assert.equal(m.hopEcho(['OTHER', `H:${RID}`, 'WHISPER', 'Tester']), null);

  const env = hopEnv();
  const ok = { origin: 'https://relay.example', data: { type: 'leyline-login', realm: RID, user: 'friend1', pass: 'hunter22' } };
  assert.deepEqual(m.hopLoginMessage(ok, env), { user: 'friend1', pass: 'hunter22' });
  assert.equal(m.hopLoginMessage(Object.assign({}, ok, { origin: 'https://evil.example' }), env), null);
  assert.equal(m.hopLoginMessage({ origin: ok.origin, data: Object.assign({}, ok.data, { realm: 'qrstuvwxyz234567' }) }, env), null);
  assert.equal(m.hopLoginMessage({ origin: ok.origin, data: Object.assign({}, ok.data, { pass: '' }) }, env), null);
});

test('wrath-page.js watchHops: the global is the authority, the echo is the cue', async () => {
  globalThis.window = { __wenilla_env: {} };
  const m = await import(pathToFileURL(path.join(WWW, 'wrath-page.js')).href);
  function fakeBridge() {
    const on = {};
    return { lua_g: null, chunks: [], state: { session: { state: 'inworld' } },
      on(name, cb) { (on[name] = on[name] || []).push(cb); },
      fire(name, p) { for (const cb of on[name] || []) cb(p); },
      async lua(chunk) { this.chunks.push(chunk); const v = this.lua_g; this.lua_g = null; return [v]; } };
  }
  // on Wrath: Join -> the echo -> the page takes the global and goes
  let gone = [];
  let w = fakeBridge();
  let h = m.watchHops(w, { env: {}, go: (u) => gone.push(u), pollMs: 0 });
  w.fire('CHAT_MSG_ADDON', ['WULY', `H:${RID}`, 'WHISPER', 'Someone']);   // a whisper alone does nothing
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(gone, []);
  assert.equal(w.chunks[0], m.HOP_TAKE);
  w.lua_g = RID;   // the player clicked Join
  w.fire('CHAT_MSG_ADDON', ['WULY', `H:${RID}`, 'WHISPER', 'Tester']);
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(gone, [`https://play.openvanilla.app/wrath?go=r:${RID}`]);
  // "wrath" on Wrath, junk: nothing
  gone = []; w = fakeBridge(); h = m.watchHops(w, { env: {}, go: (u) => gone.push(u), pollMs: 0 });
  w.lua_g = 'wrath'; await h.take();
  w.lua_g = '../../x'; await h.take();
  assert.deepEqual(gone, []);
  // on a community realm: the poll finds the global (that realm doesn't echo) and goes home
  gone = []; w = fakeBridge();
  h = m.watchHops(w, { env: Object.assign(hopEnv(), { mode: 'own' }), go: (u) => gone.push(u), pollMs: 20 });
  w.lua_g = 'wrath';
  await new Promise((r) => setTimeout(r, 80));
  clearInterval(h.timer);
  assert.deepEqual(gone, ['https://play.example/wrath/play?mode=own']);
});
