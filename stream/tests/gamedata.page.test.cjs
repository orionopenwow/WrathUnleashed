// The game data killswitch in the page (stream/server/gamedata-switch.sh, docs/GAME-DATA-ON-OUR-SERVER.md):
//   * wrath-early.js: a /data read answered 410 Gone is never retried (fetch or sync XHR), and the page says once
//     "This realm needs your own game folder" with a link to the game-folder page (no endless retries, no black screen);
//   * ownfiles.js: a 410 from /data/__index means "the server serves no /data" (the own-folder chooser), and with
//     WU_GAMEDATA_OFF (the portal's /__env.js) the page never asks /data at all, ignores ?data=host, hides
//     "Stream a mini version" and tells the player to drop their 3.3.5a game folder.
// Run: node stream/tests/gamedata.page.test.cjs
'use strict';
const path = require('path');
const { pathToFileURL } = require('url');
const WWW = path.join(__dirname, '..', 'www-files');

// --- a tiny DOM: enough for wrath-early.js's note and ownfiles.js's folder card
function fakeEl(tag) {
  const e = {
    tag, attrs: {}, kids: [], listeners: {}, style: {}, textContent: '', className: '', disabled: false,
    classList: {
      get list() { return e.className.split(/\s+/).filter(Boolean); },
      add(c) { if (!this.list.includes(c)) e.className = this.list.concat(c).join(' '); },
      remove(c) { e.className = this.list.filter((x) => x !== c).join(' '); },
      toggle(c, on) { if (on === undefined ? !this.contains(c) : on) this.add(c); else this.remove(c); },
      contains(c) { return this.list.includes(c); },
    },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    append(...k) { for (const x of k) this.kids.push(x); },
    appendChild(x) { this.kids.push(x); return x; },
    replaceChildren(...k) { this.kids = k; },
    remove() { this.removed = true; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {},
  };
  return e;
}
function textOf(e) {
  if (e == null) return '';
  if (typeof e === 'string') return e;
  return (e.textContent || '') + ' ' + (e.kids || []).map(textOf).join(' ');
}
function findId(e, id) {
  if (!e || typeof e === 'string') return null;
  if (e.id === id) return e;
  for (const k of e.kids || []) { const f = findId(k, id); if (f) return f; }
  return null;
}
const body = fakeEl('body');
const head = fakeEl('head');
global.window = global;
global.document = {
  body, head, documentElement: fakeEl('html'), currentScript: null,
  createElement: fakeEl,
  getElementById: (id) => findId(body, id) || findId(head, id),
  addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
};
global.location = { href: 'https://wrath.example/', origin: 'https://wrath.example', pathname: '/', search: '?multitab=1', hash: '' };
Object.defineProperty(global, 'navigator', { value: {}, configurable: true, writable: true });
global.setTimeout = (f) => { f(); return 0; };

let calls = [], plan = [];
global.fetch = async (u) => {
  calls.push(String(u));
  const s = plan.shift();
  return { status: s, ok: s >= 200 && s < 300, headers: { get: () => 'application/json' }, json: async () => ({}) };
};
class FakeXHR { open(m, u) { this.u = u; } send() { calls.push(this.u); this.status = plan.shift(); this.responseText = ''; } getResponseHeader() { return ''; } getAllResponseHeaders() { return ''; } overrideMimeType() {} }
global.XMLHttpRequest = FakeXHR;

// wrath-early.js goes on to load the rest of the page layer, which this fake browser can't run: its complaints are muted.
console.error = () => {}; console.warn = () => {};
require(path.join(WWW, 'wrath-early.js'));
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  // --- wrath-early.js
  plan = [410]; calls = [];
  let r = await fetch('https://wrath.example/data/World%5Cfoo.wmo');
  ok(r.status === 410 && calls.length === 1, '410: fetch not retried');
  ok(window.__wuGamedataOff === true, '410: __wuGamedataOff set');
  const note = findId(body, 'wu-gamedata-off');
  ok(!!note && /needs your own game folder/.test(textOf(note)) && /3\.3\.5a game folder/.test(textOf(note)), '410: the page says what it needs');
  ok(!!note && JSON.stringify(note).includes('/?ownfiles=1'), '410: the note links to the game-folder page');
  plan = [410]; calls = [];
  const x = new XMLHttpRequest(); x.open('GET', '/data/a.blp', false); x.send();
  ok(x.status === 410 && calls.length === 1, '410: sync XHR not retried');
  plan = [410, 410]; calls = [];
  await fetch('https://wrath.example/data/b.blp'); await fetch('https://wrath.example/data/c.blp');
  ok(body.kids.filter((k) => k.id === 'wu-gamedata-off').length === 1, '410 many times: one note');
  plan = [502, 200]; calls = [];
  r = await fetch('https://wrath.example/data/d.blp');
  ok(r.status === 200 && calls.length === 2, 'a 5xx is still retried as before');

  // --- ownfiles.js
  window.__wuGamedataOff = false;
  const of = await import(pathToFileURL(path.join(WWW, 'ownfiles.js')).href);
  plan = [410]; calls = [];
  ok((await of.hostServesData()) === false && calls[0] === '/data/__index', 'ownfiles: /data/__index 410 -> no host data (own folder)');
  plan = [200]; calls = [];
  ok((await of.hostServesData()) === true, 'ownfiles: /data/__index 200 JSON -> host data (streaming as before)');
  ok(of.gamedataOff() === false, 'ownfiles: gamedataOff() false by default');
  window.WU_GAMEDATA_OFF = true;
  ok(of.gamedataOff() === true, 'ownfiles: gamedataOff() from the page env');
  // WU_GAMEDATA_OFF and ?data=host: no /data request, the folder card (this fake browser has no Worker: the
  // "cannot read local files" card, which is the same card)
  global.location.search = '?data=host';
  window.WU_STREAM_AVAILABLE = true;
  plan = []; calls = [];
  const pending = of.ensureDataSource({ probeHost: true });
  let settled = false; pending.then(() => { settled = true; });
  await new Promise((res) => setImmediate(res));
  ok(!calls.some((u) => u.includes('/data')), 'ownfiles: killswitch: /data is never asked');
  ok(!settled, 'ownfiles: killswitch: ?data=host does not start a streamed client');
  const card = findId(body, 'wu-ownfiles');
  ok(!!card && /needs your own game folder/.test(textOf(card)) && /3\.3\.5a game folder/.test(textOf(card)), 'ownfiles: the card says to drop the 3.3.5a game folder');
  const stream = (function find(e) { if (!e || typeof e === 'string') return null; if (e.attrs && e.attrs['data-act'] === 'stream') return e; for (const k of e.kids || []) { const f = find(k); if (f) return f; } return null; })(card);
  ok(!!stream && stream.classList.contains('hidden'), 'ownfiles: killswitch: no "Stream a mini version" offer');
  for (const w of ['World of Warcraft', 'Warcraft', 'Blizzard', 'Lich King']) ok(!textOf(card).includes(w) && !textOf(note).includes(w), `no ${w} on the page`);
  process.exit(process.exitCode || 0);
})().catch((e) => { console.log('FAIL threw ' + (e && e.stack || e)); process.exit(1); });
