// wrath-early.js game-file retries: fetch and sync XHR /data/ reads retried on 5xx and network errors, never on 404 or other paths. Run: node stream/tests/retry.page.test.cjs
const path = require('path').join(__dirname, '..', 'www-files', 'wrath-early.js');
const quiet = console.error; console.error = () => {};
let calls = 0, plan = [];
global.window = global; global.location = { href: 'https://x.test/', pathname: '/', search: '?multitab=1', hash: '' };
global.navigator = {}; global.document = { addEventListener(){}, createElement(){ return { setAttribute(){}, addEventListener(){} } }, head: { appendChild(){} }, documentElement: { appendChild(){} }, currentScript: null, querySelector(){ return null } };
global.fetch = async (u) => { calls++; const s = plan.shift(); if (s === 'net') throw new Error('net'); if (s === 'abort') { const e = new Error('aborted'); e.name = 'AbortError'; throw e; } return { status: s, ok: s < 300 }; };
class FakeXHR { open(m,u,a){ this.u=u; } send(){ calls++; const s = plan.shift(); if (s === 'net') throw new Error('net'); this.status = s; this.responseText = 'body'+s; } getResponseHeader(){ return 'h'; } getAllResponseHeaders(){ return ''; } overrideMimeType(){} }
global.XMLHttpRequest = FakeXHR;
global.setTimeout = (f) => { f(); return 0; };
try { require(path); } catch (e) { console.log('load error', e.message); }
(async () => {
  const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
  plan = [502, 200]; calls = 0; let r = await fetch('https://x.test/data/World%5Cfoo.wmo'); ok(r.status === 200 && calls === 2, 'fetch 502 then 200 recovers');
  plan = [404]; calls = 0; r = await fetch('https://x.test/data/a.blp'); ok(r.status === 404 && calls === 1, '404 not retried');
  plan = [503, 503, 503, 503]; calls = 0; r = await fetch('https://x.test/data/a.blp'); ok(r.status === 503 && calls === 4, 'gives up after 3 retries');
  plan = ['net', 200]; calls = 0; r = await fetch('https://x.test/data/a.blp'); ok(r.status === 200 && calls === 2, 'network error retried');
  plan = ['abort']; calls = 0; try { await fetch('https://x.test/data/a.wav'); ok(false, 'abort rethrown'); } catch (e) { ok(e.name === 'AbortError' && calls === 1, 'a cancelled read is not retried'); }
  plan = [502]; calls = 0; r = await fetch('https://x.test/__env.js'); ok(r.status === 502 && calls === 1, 'non-data untouched');
  plan = [502]; calls = 0; r = await fetch('https://x.test/data/__index'); ok(calls === 1, '__index untouched');
  plan = [502, 200]; calls = 0; let x = new XMLHttpRequest(); x.open('GET', '/data/a.blp', false); x.send(); ok(x.status === 200 && x.responseText === 'body200' && calls === 2, 'sync 502 then 200 recovers');
  plan = ['net', 200]; calls = 0; x = new XMLHttpRequest(); x.open('GET', '/data/a.blp', false); x.send(); ok(x.status === 200 && calls === 2, 'sync network error recovers');
  plan = [404]; calls = 0; x = new XMLHttpRequest(); x.open('GET', '/data/a.blp', false); x.send(); ok(x.status === 404 && calls === 1, 'sync 404 not retried');
  plan = [200]; calls = 0; x = new XMLHttpRequest(); x.open('GET', '/data/a.blp', true); x.send(); ok(calls === 1, 'async xhr untouched');
  console.error = quiet; console.log(JSON.stringify(window.__wuRetries));
  process.exit(process.exitCode || 0);
})();
