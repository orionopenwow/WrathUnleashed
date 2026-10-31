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

function page(env, { store = storage(), protocol = 'https:', host = 'wrath.example', fetch } = {}) {
  const opened = [];
  function FakeWS(url, protocols) { this.url = url; this.protocols = protocols; opened.push(url); }
  FakeWS.OPEN = 1;
  const win = { __wenilla_env: env, location: { protocol, host, href: `${protocol}//${host}/` }, localStorage: store,
                WebSocket: FakeWS, console, URL, setTimeout, clearTimeout };
  if (fetch) win.fetch = fetch;
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
  // "Back to Wrath" lands in Dalaran (the go intent, ov_go.lua h:dalaran)
  assert.equal(m.hopUrl('wrath', { home: 'https://play.example', hop: RID }), 'https://play.example/wrath?go=h:dalaran');
  assert.equal(m.hopUrl('wrath', { home: 'https://play.example', mode: 'own' }), 'https://play.example/wrath/play?mode=own&go=h:dalaran');
  assert.equal(m.hopUrl('wrath', { home: 'javascript:alert(1)//' }), 'https://play.openvanilla.app/wrath?go=h:dalaran');
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
    return { lua_g: null, chunks: [], ready: true, state: { session: { state: 'inworld' } },
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
  assert.deepEqual(gone, ['https://play.example/wrath/play?mode=own&go=h:dalaran']);
  assert.ok(h.polls >= 1 && h.taken === 'wrath');
  // the poll is the trigger (the web client never relays CHAT_MSG_ADDON to the page): no echo at all, at the glue
  // screens too, and it waits for the bridge; a failing lua call is reported, not thrown
  gone = []; w = fakeBridge(); w.state = { session: { state: 'charselect' } }; w.ready = false;
  h = m.watchHops(w, { env: {}, go: (u) => gone.push(u), pollMs: 10 });
  w.lua_g = RID;
  await new Promise((r) => setTimeout(r, 40));
  assert.deepEqual(gone, [], 'no bridge yet: no lua calls');
  assert.equal(w.chunks.length, 0);
  w.ready = true;
  await new Promise((r) => setTimeout(r, 60));
  clearInterval(h.timer);
  assert.deepEqual(gone, [`https://play.openvanilla.app/wrath?go=r:${RID}`]);
  w = fakeBridge(); w.lua = async () => { throw new Error('wenilla.lua: timed out'); };
  h = m.watchHops(w, { env: {}, go: () => {}, pollMs: 0 });
  assert.equal(await h.take(), null);
  assert.match(h.error, /timed out/);
});

test('the Wrath Unleashed: the Wrath login stays (same realm, same account), never a stored one', () => {
  const env = Object.assign(hopEnv(), { hop_name: 'Wrath Unleashed', hop_home: '1', user: 'WR000123', pass: 'Pa55word1234abcd' });
  const store = storage({ ['wu.leyline.login.' + RID]: JSON.stringify({ user: 'other1', pass: 'hunter22' }) });
  const { win, opened } = page(env, { store });
  assert.equal(win.__wuHop.state.home, true);
  assert.equal(win.__wuHop.state.login, true);
  assert.equal(env.user, 'WR000123');
  assert.equal(env.pass, 'Pa55word1234abcd');
  new win.WebSocket('wss://wrath.example/ws/3724?host=relay.example');
  assert.deepEqual(opened, [`wss://relay.example/ws/${RID}/auth`]);
  // hop_home without a usable login, or a login without hop_home: the ordinary rule (drop it)
  const e2 = Object.assign(hopEnv(), { hop_home: '1', user: 'WR000123', pass: 'has space' });
  page(e2);
  assert.equal(e2.user, undefined);
  const e3 = Object.assign(hopEnv(), { user: 'WR000123', pass: 'Pa55word1234abcd' });
  page(e3);
  assert.equal(e3.pass, undefined);
});

test('__wuHop.status(): the hop, the rewritten sockets, the watcher; never a password', () => {
  const env = Object.assign(hopEnv(), { hop_home: '1', user: 'WR000123', pass: 'Pa55word1234abcd' });
  const { win } = page(env);
  new win.WebSocket('wss://wrath.example/ws/3724?host=relay.example');
  new win.WebSocket('wss://wrath.example/ws/8085?host=relay.example');
  win.__wuHop.watch = { polls: 3, taken: null, gone: null, error: null };
  const st = win.__wuHop.status();
  assert.equal(st.page, 'wrath.example');
  assert.deepEqual(JSON.parse(JSON.stringify(st.hop)), { id: RID, name: 'Frost Haven', base: `wss://relay.example/ws/${RID}`, login: true, home: true });
  assert.equal(st.envHop, RID);
  assert.equal(st.signedIn, true);
  assert.deepEqual(JSON.parse(JSON.stringify(st.sockets.map((x) => [x.from, x.to]))), [
    ['wss://wrath.example/ws/3724', `wss://relay.example/ws/${RID}/auth`],
    ['wss://wrath.example/ws/8085', `wss://relay.example/ws/${RID}/world`]]);
  assert.equal(st.watch.polls, 3);
  assert.ok(!JSON.stringify(st).includes('Pa55word'), 'no password in the status');
  const plain = page({ user: 'WR000123', pass: 'x' }).win.__wuHop.status();
  assert.equal(plain.hop, null);
  assert.deepEqual(Array.from(plain.sockets), []);
});

// ---- Hero Key sign-in (docs/HERO-KEY-SSO.md; the site's herokey_sso flag): the env carries hop_sso and a one-time
// login; the page redeems it at the relay before the client starts, with no join page and nothing kept.
const SIG = 'ab'.repeat(64);
const ssoEnv = (over = {}) => Object.assign(hopEnv(), {
  user: 'HKABCDEFGHIJKLMN', pass: 'Q7W8E9R2T3Y4U5I6',
  hop_sso: { assertion: { aud: RID, sub: 'x'.repeat(26), nonce: '00' }, sig: SIG,
             redeem: `https://relay.example/api/realms/${RID}/herokey` } }, over);

function fakeFetch(answer) {
  const calls = [];
  const f = (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).endsWith('/herokey')) return answer();
    return Promise.resolve({ ok: true, url: String(url), wasm: true });
  };
  f.calls = calls;
  return f;
}
const ok = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
const refuse = (status, code) => () => Promise.resolve({ ok: false, status, json: () => Promise.resolve({ code }) });

test('hero key: redeemed at the relay before the client starts; the one-time login, nothing kept', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const f = fakeFetch(() => gate.then(ok));
  const store = storage({ ['wu.leyline.login.' + RID]: JSON.stringify({ user: 'friend1', pass: 'hunter22' }) });
  const env = ssoEnv();
  const { win } = page(env, { fetch: f, store });
  const H = win.__wuHop;
  assert.equal(H.state.login, true, 'no join page while it is redeemed');
  assert.equal(H.state.sso, 'pending');
  assert.equal(env.hop_sso, undefined, 'the assertion is not left for the client');
  assert.equal(env.user, 'HKABCDEFGHIJKLMN', 'the one-time login, not the kept one');
  const post = f.calls[0];
  assert.equal(post.url, `https://relay.example/api/realms/${RID}/herokey`);
  assert.equal(post.init.method, 'POST');
  assert.equal(post.init.credentials, 'omit');
  assert.deepEqual(Object.keys(JSON.parse(post.init.body)).sort(), ['assertion', 'sig']);
  assert.ok(!post.init.body.includes('Q7W8E9R2T3Y4U5I6'), 'the password never goes to the relay');
  // the client's wasm waits for the realm's answer
  let started = false;
  const wasm = win.fetch('https://wrath.example/wenilla_bg.wasm').then(() => { started = true; });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(started, false);
  const other = await win.fetch('https://wrath.example/data/x');   // nothing else waits
  assert.ok(other.ok);
  release();
  await wasm;
  assert.equal(started, true);
  assert.equal(H.state.sso, 'ok');
  assert.equal(env.pass, 'Q7W8E9R2T3Y4U5I6');
  assert.equal(store.m.get('wu.leyline.login.' + RID), JSON.stringify({ user: 'friend1', pass: 'hunter22' }), 'storage untouched');
  assert.equal(store.m.size, 1);
  assert.ok(!JSON.stringify(H.status()).includes('Q7W8E9R2T3Y4U5I6'), 'no password in the status');
  assert.equal(H.status().hop.sso, 'ok');
});

test('hero key: a realm that refuses it falls back to the kept login, else the join page', async () => {
  const store = storage({ ['wu.leyline.login.' + RID]: JSON.stringify({ user: 'friend1', pass: 'hunter22' }) });
  const env = ssoEnv();
  const { win } = page(env, { fetch: fakeFetch(refuse(403, 'off')), store });
  assert.equal(await win.__wuHop.state.ssoPending, false);
  assert.equal(win.__wuHop.state.sso, 'failed:off');
  assert.equal(win.__wuHop.state.login, true);
  assert.equal(env.user, 'FRIEND1');
  assert.equal(env.pass, 'hunter22');
  const env2 = ssoEnv();
  const p2 = page(env2, { fetch: fakeFetch(() => Promise.reject(new Error('down'))) });
  assert.equal(await p2.win.__wuHop.state.ssoPending, false);
  assert.equal(p2.win.__wuHop.state.sso, 'failed:network');
  assert.equal(p2.win.__wuHop.state.login, false, 'the join page shows');
  assert.equal(env2.user, undefined);
  assert.equal(env2.pass, undefined);
});

test('hero key: "Use another account" declines it for this realm; a bad ticket is ignored', () => {
  const store = storage();
  const f = fakeFetch(ok);
  const { win } = page(ssoEnv(), { fetch: f, store });
  win.__wuHop.setSso(store, RID, false);
  assert.equal(store.m.get('wu.leyline.sso.off.' + RID), '1');
  const env = ssoEnv();
  const f2 = fakeFetch(ok);
  const p = page(env, { fetch: f2, store });
  assert.equal(f2.calls.length, 0, 'declined: not redeemed');
  assert.equal(p.win.__wuHop.state.login, false);
  assert.equal(p.win.__wuHop.state.ssoOffer, true, 'the join page offers it back');
  assert.equal(env.user, undefined);
  win.__wuHop.setSso(store, RID, true);
  assert.equal(store.m.has('wu.leyline.sso.off.' + RID), false);
  // tickets that don't fit this hop: another realm, another relay, a non-HK login, a bad signature field
  for (const over of [
    { hop_sso: Object.assign(ssoEnv().hop_sso, { redeem: 'https://evil.example/api/realms/' + RID + '/herokey' }) },
    { hop_sso: Object.assign(ssoEnv().hop_sso, { assertion: { aud: 'qrstuvwxyz234567' } }) },
    { hop_sso: Object.assign(ssoEnv().hop_sso, { sig: 'nope' }) },
    { user: 'WR000123' },
  ]) {
    const e = ssoEnv(over);
    const f3 = fakeFetch(ok);
    const q = page(e, { fetch: f3 });
    assert.equal(f3.calls.length, 0, JSON.stringify(over));
    assert.equal(q.win.__wuHop.state.login, false);
    assert.equal(e.user, undefined);
  }
});

test('hero key off (no hop_sso): exactly the old hop', () => {
  const f = fakeFetch(ok);
  const env = hopEnv();
  const { win } = page(env, { fetch: f });
  assert.equal(f.calls.length, 0);
  assert.equal(win.__wuHop.state.sso, null);
  assert.equal(win.__wuHop.state.ssoPending, null);
  assert.equal(win.__wuHop.state.login, false);
  assert.equal(win.fetch, f, 'fetch not wrapped');
});
