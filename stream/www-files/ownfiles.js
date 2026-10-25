// ownfiles.js — "Use my own game files" for the WrathUnleashed browser client (page side).
//
//   import { ensureDataSource } from './ownfiles.js';
//   const source = await ensureDataSource();   // resolves once /data/* is answerable
//
// The player drops their World of Warcraft 3.3.5a `Data` folder (or the WoW folder) on the page,
// or picks it with "Choose folder". The page checks it, hands the File references to a dedicated
// worker (ownfiles-worker.js) that opens the MPQ chain, and then answers every same-origin
// `/data/*` request the client makes — `fetch()` and XMLHttpRequest, synchronous included —
// from those local files. Nothing is uploaded; nothing is hosted.
//
// Why a page-level shim and not a service worker: the wasm client reads the chain with
// *synchronous* XMLHttpRequest (benilla-formats/src/web.rs), and Chromium does not route
// synchronous XHR through service workers (verified: Chromium 141 sends it straight to the
// network while fetch() from the same page is intercepted). So `XMLHttpRequest` and `fetch` are
// wrapped for `/data/*` only: async requests are a message round trip to the worker; a sync
// request blocks in send() spinning on a SharedArrayBuffer while the worker writes the answer
// into shared memory (the page is cross-origin isolated — COOP/COEP — which SharedArrayBuffer
// requires and wenilla's pages already are). Every other URL goes to the real XHR/fetch.
//
// Chrome/Edge: the folder handle is remembered in IndexedDB; a later visit mounts it silently
// when the browser kept the permission ("Allow on every visit"), else after one "Continue" click.
// Firefox/Safari: no persistent folder handles, so the folder is dropped (or chosen) each visit.

const DB_NAME = 'wu-ownfiles';
const STORE = 'kv';
const STREAM_URL = 'https://play.openvanilla.app/wrath/play?mini=dalaran-arenas';
const DATA_PREFIX = '/data/';
const ARENA_INITIAL = 16 * 1024 * 1024;
const SYNC_TIMEOUT_MS = 120000;

// --- IndexedDB ---------------------------------------------------------------------------------------
function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function kv(mode, fn) {
  const db = await idb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req && req.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
const kvGet = (k) => kv('readonly', (s) => s.get(k)).catch(() => undefined);
const kvSet = (k, v) => kv('readwrite', (s) => s.put(v, k)).catch(() => {});
const kvDel = (k) => kv('readwrite', (s) => s.delete(k)).catch(() => {});

// --- the shared reader modules (UMD; they set globalThis.WUMpq / WUChain) ----------------------------
let libs = null;
function loadLibs(base) {
  if (!libs) {
    libs = (async () => {
      await import(new URL('./mpq.js', base).href);
      await import(new URL('./chain.js', base).href);
      return globalThis.WUChain;
    })();
  }
  return libs;
}

// --- the engine: the worker, the sync channel, the async channel -------------------------------------
const CT = ['application/octet-stream', 'image/x-blp', 'audio/mpeg', 'application/json'];
const CC = ['private, max-age=31536000, immutable', 'no-cache'];
const xudDecoder = (() => {
  try { return new TextDecoder('x-user-defined'); } catch (_) { return null; }
})();

class Engine {
  constructor(base) {
    this.worker = new Worker(new URL('./ownfiles-worker.js', base).href);
    this.nextId = 1;
    this.pending = new Map();
    this.ctlSab = new SharedArrayBuffer(32);
    this.ctl = new Int32Array(this.ctlSab);
    this.arenaSab = new SharedArrayBuffer(ARENA_INITIAL);
    this.arena = new Uint8Array(this.arenaSab);
    this.worker.postMessage({ type: 'shared', ctl: this.ctlSab, arena: this.arenaSab });
    this.worker.onmessage = (e) => {
      const m = e.data || {};
      const p = this.pending.get(m.id);
      if (p) {
        this.pending.delete(m.id);
        p(m);
      }
    };
    this.stats = { sync: 0, async: 0, syncMs: 0 };
  }
  call(msg, transfer) {
    const id = this.nextId++;
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      this.worker.postMessage({ ...msg, id }, transfer || []);
    });
  }
  async mount(entries, label) {
    const r = await this.call({ type: 'mount', entries, label, warmIndex: true });
    if (!r.ok) throw new Error(r.error || 'could not open the archives');
    return r;
  }
  async mountHandle(handle, label) {
    const r = await this.call({ type: 'mount-handle', handle, label, warmIndex: true });
    if (!r.ok) throw new Error(r.error || 'could not open the archives');
    return r;
  }
  asyncRequest(method, path) {
    this.stats.async++;
    return this.call({ type: 'async', method, path }).then((m) => ({ status: m.status, headers: m.headers || {}, body: m.body }));
  }
  /// Blocks the calling (main) thread until the worker has answered. Only ever used for a
  /// synchronous XHR, which blocks the thread anyway.
  syncRequest(method, path) {
    const t0 = performance.now();
    this.stats.sync++;
    for (let attempt = 0; attempt < 4; attempt++) {
      Atomics.store(this.ctl, 0, 1);
      this.worker.postMessage({ type: 'sync', method, path });
      let spins = 0;
      while (Atomics.load(this.ctl, 0) === 1) {
        if ((++spins & 0xfffff) === 0 && performance.now() - t0 > SYNC_TIMEOUT_MS) {
          return { status: 500, headers: {}, body: null };
        }
      }
      const status = this.ctl[1], len = this.ctl[2], flags = this.ctl[3];
      if (flags === 2) {
        // Bigger than the arena: grow it (the worker parked the answer) and ask again.
        this.arenaSab = new SharedArrayBuffer(Math.ceil((len * 1.25) / 65536) * 65536);
        this.arena = new Uint8Array(this.arenaSab);
        this.worker.postMessage({ type: 'shared', ctl: this.ctlSab, arena: this.arenaSab });
        continue;
      }
      const headers = { 'content-type': CT[this.ctl[4]] || CT[0], 'content-length': String(len), 'cross-origin-resource-policy': 'same-origin' };
      if (this.ctl[5] >= 0) headers['cache-control'] = CC[this.ctl[5]];
      if (status !== 200) delete headers['content-type'];
      const body = len && method !== 'HEAD' ? this.arena.slice(0, len) : null;
      this.stats.syncMs += performance.now() - t0;
      return { status, headers, body };
    }
    return { status: 500, headers: {}, body: null };
  }
  forget() {
    return this.call({ type: 'forget' });
  }
}

let engine = null;
let shimInstalled = false;

const STATUS_TEXT = { 200: 'OK', 404: 'Not Found', 405: 'Method Not Allowed', 500: 'Internal Server Error', 503: 'Service Unavailable' };

function dataPath(url) {
  let u;
  try { u = new URL(String(url), location.href); } catch (_) { return null; }
  return u.origin === location.origin && u.pathname.startsWith(DATA_PREFIX) ? u.pathname : null;
}

/// Wrap XMLHttpRequest and fetch so same-origin `/data/*` is answered by the engine.
function installShim(eng) {
  if (shimInstalled) return;
  shimInstalled = true;
  const RealXHR = window.XMLHttpRequest;
  const realFetch = window.fetch.bind(window);

  class OwnFilesXHR extends RealXHR {
    open(method, url, async, ...rest) {
      const path = dataPath(url);
      if (!path) {
        this._own = null;
        return arguments.length < 3 ? super.open(method, url) : super.open(method, url, async, ...rest);
      }
      const rt = super.responseType;
      this._own = { method: String(method).toUpperCase(), path, async: async === undefined || !!async, mime: null,
        readyState: 1, status: 0, headers: {}, body: null, responseType: rt, aborted: false };
      this._fire('readystatechange');
    }
    overrideMimeType(mime) {
      if (this._own) { this._own.mime = String(mime); return; }
      return super.overrideMimeType(mime);
    }
    setRequestHeader(k, v) {
      if (this._own) return;
      return super.setRequestHeader(k, v);
    }
    send(body) {
      const o = this._own;
      if (!o) return super.send(body);
      if (!o.async) return this._finish(eng.syncRequest(o.method, o.path));
      eng.asyncRequest(o.method, o.path).then((r) => this._finish(r), () => this._finish({ status: 0, headers: {}, body: null, failed: true }));
    }
    abort() {
      if (this._own) { this._own.aborted = true; this._own.readyState = 0; this._fire('abort'); return; }
      return super.abort();
    }
    _finish(r) {
      const o = this._own;
      if (o.aborted) return;
      o.status = r.status;
      o.headers = r.headers || {};
      o.body = r.body;
      o.readyState = 4;
      this._fire('readystatechange');
      this._fire(r.failed ? 'error' : 'load');
      this._fire('loadend');
    }
    _fire(type) {
      try { this.dispatchEvent(new Event(type)); } catch (_) {}
    }
    get readyState() { return this._own ? this._own.readyState : super.readyState; }
    get status() { return this._own ? this._own.status : super.status; }
    get statusText() { return this._own ? (this._own.readyState === 4 ? STATUS_TEXT[this._own.status] || '' : '') : super.statusText; }
    get responseURL() { return this._own ? (this._own.readyState === 4 ? new URL(this._own.path, location.href).href : '') : super.responseURL; }
    get responseType() { return this._own ? this._own.responseType : super.responseType; }
    set responseType(v) { if (this._own) this._own.responseType = v; else super.responseType = v; }
    get responseText() {
      const o = this._own;
      if (!o) return super.responseText;
      if (!o.body || o.readyState !== 4) return '';
      if (o.mime && /x-user-defined/i.test(o.mime)) {
        if (xudDecoder) return xudDecoder.decode(o.body);
        let s = '';
        for (let i = 0; i < o.body.length; i += 32768) s += String.fromCharCode.apply(null, o.body.subarray(i, i + 32768));
        return s;
      }
      return new TextDecoder().decode(o.body);
    }
    get response() {
      const o = this._own;
      if (!o) return super.response;
      if (o.readyState !== 4) return o.responseType === '' || o.responseType === 'text' ? '' : null;
      const bytes = o.body || new Uint8Array(0);
      switch (o.responseType) {
        case 'arraybuffer': return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length);
        case 'blob': return new Blob([bytes], { type: o.headers['content-type'] || '' });
        case 'json': try { return JSON.parse(new TextDecoder().decode(bytes)); } catch (_) { return null; }
        default: return this.responseText;
      }
    }
    getResponseHeader(name) {
      if (!this._own) return super.getResponseHeader(name);
      if (this._own.readyState !== 4) return null;
      const v = this._own.headers[String(name).toLowerCase()];
      return v === undefined ? null : v;
    }
    getAllResponseHeaders() {
      if (!this._own) return super.getAllResponseHeaders();
      if (this._own.readyState !== 4) return '';
      return Object.entries(this._own.headers).map(([k, v]) => `${k}: ${v}\r\n`).join('');
    }
  }
  window.XMLHttpRequest = OwnFilesXHR;

  window.fetch = function fetch(input, init) {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input && input.url;
    const path = url ? dataPath(url) : null;
    if (!path) return realFetch(input, init);
    const method = String((init && init.method) || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const signal = (init && init.signal) || (input instanceof Request ? input.signal : null);
    if (signal && signal.aborted) return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
    return eng.asyncRequest(method, path).then((r) => {
      if (signal && signal.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
      return new Response(method === 'HEAD' || !r.body ? null : r.body, { status: r.status, statusText: STATUS_TEXT[r.status] || '', headers: r.headers });
    });
  };
  window.__ownfiles = { stats: eng.stats };
}

/// Does the page's own origin already serve the Data URL scheme (wenilla-host)?
async function hostServesData() {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 8000);
  try {
    const r = await fetch(DATA_PREFIX + '__index', { signal: ac.signal, cache: 'no-store' });
    const ok = r.ok && /json/i.test(r.headers.get('content-type') || '');
    ac.abort();
    return ok;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(t);
  }
}

function getEngine(base) {
  if (!engine) engine = new Engine(base);
  return engine;
}

async function mountEntries(base, entries, label) {
  const eng = getEngine(base);
  const r = await eng.mount(entries, label);
  installShim(eng);
  return r;
}

async function mountHandle(base, handle, label) {
  const eng = getEngine(base);
  const r = await eng.mountHandle(handle, label);
  installShim(eng);
  return r;
}

// --- folder intake ---------------------------------------------------------------------------------

/// Firefox/Safari (and Chrome when no handle is offered): walk FileSystemEntry trees.
async function entriesFromEntries(list) {
  const out = [];
  const readAll = (dirEntry) =>
    new Promise((resolve, reject) => {
      const reader = dirEntry.createReader();
      const acc = [];
      const step = () =>
        reader.readEntries((batch) => {
          if (!batch.length) resolve(acc);
          else { acc.push(...batch); step(); }
        }, reject);
      step();
    });
  const fileOf = (fe) => new Promise((resolve, reject) => fe.file(resolve, reject));
  const eqi = (a, b) => a.toLowerCase() === b.toLowerCase();
  const walkData = async (dir, prefix) => {
    for (const e of await readAll(dir)) {
      if (e.isFile) out.push({ path: prefix + e.name, file: await fileOf(e) });
      else if (e.isDirectory) for (const e2 of await readAll(e)) if (e2.isFile) out.push({ path: `${prefix}${e.name}/${e2.name}`, file: await fileOf(e2) });
    }
  };
  const walkAll = async (dir, prefix, depth) => {
    if (depth > 12) return;
    for (const e of await readAll(dir)) {
      if (e.name.startsWith('.')) continue;
      if (e.isFile) out.push({ path: prefix + e.name, file: await fileOf(e) });
      else await walkAll(e, prefix + e.name + '/', depth + 1);
    }
  };
  if (list.length === 1 && list[0].isDirectory) {
    const root = list[0];
    const top = await readAll(root);
    const hasCommon = top.some((e) => e.isFile && eqi(e.name, 'common.MPQ'));
    const data = top.find((e) => e.isDirectory && eqi(e.name, 'Data'));
    if (!hasCommon && data) {
      await walkData(data, 'Data/');
      const iface = top.find((e) => e.isDirectory && eqi(e.name, 'Interface'));
      if (iface) await walkAll(iface, 'Interface/', 0);
    } else {
      await walkData(root, '');
    }
    return { entries: out, label: root.name };
  }
  // Several items: the Data folder's contents were selected and dropped.
  for (const e of list) {
    if (e.isFile) out.push({ path: e.name, file: await fileOf(e) });
    else if (e.isDirectory) for (const e2 of await readAll(e)) if (e2.isFile) out.push({ path: `${e.name}/${e2.name}`, file: await fileOf(e2) });
  }
  return { entries: out, label: 'Data' };
}

/// `<input webkitdirectory>`: every file under the chosen folder, with its relative path.
function entriesFromInput(files) {
  const list = [...files].map((f) => ({ path: f.webkitRelativePath || f.name, file: f }));
  const first = list[0] && list[0].path.split('/')[0];
  return { entries: list, label: first || 'Data' };
}

// --- the UI ------------------------------------------------------------------------------------------

const CSS = `
#wu-ownfiles { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center;
  background: rgba(0,0,0,.94); color: #ddd; font: 15px/1.45 system-ui, sans-serif; }
#wu-ownfiles .card { width: min(560px, calc(100vw - 32px)); background: #111; border: 1px solid #2a2a2a;
  border-radius: 10px; padding: 22px 24px; box-shadow: 0 10px 40px rgba(0,0,0,.6); }
#wu-ownfiles h1 { margin: 0 0 4px; font-size: 19px; color: #f0e2b0; font-weight: 600; }
#wu-ownfiles .sub { margin: 0 0 16px; color: #999; font-size: 13px; }
#wu-ownfiles .zone { border: 2px dashed #3a3a3a; border-radius: 8px; padding: 26px 16px; text-align: center;
  transition: border-color .15s, background .15s; }
#wu-ownfiles .zone.over { border-color: #c9a227; background: rgba(201,162,39,.07); }
#wu-ownfiles .zone p { margin: 0 0 12px; }
#wu-ownfiles button { font: inherit; cursor: pointer; border-radius: 6px; padding: 7px 14px; }
#wu-ownfiles button.primary { background: #c9a227; color: #111; border: 0; font-weight: 600; }
#wu-ownfiles button.primary:hover { background: #d8b23a; }
#wu-ownfiles button.ghost { background: transparent; color: #bbb; border: 1px solid #444; }
#wu-ownfiles button.ghost:hover { border-color: #777; color: #eee; }
#wu-ownfiles button.link { background: none; border: 0; color: #9aa7c7; padding: 0; text-decoration: underline; font-size: 13px; }
#wu-ownfiles .privacy { display: flex; gap: 8px; margin: 14px 0 0; padding: 10px 12px; background: #161a14;
  border: 1px solid #263021; border-radius: 6px; font-size: 13px; color: #b9c9a8; }
#wu-ownfiles .checks { list-style: none; margin: 14px 0 0; padding: 0; font-size: 13px; }
#wu-ownfiles .checks li { padding: 2px 0; }
#wu-ownfiles .checks .y::before { content: "✓ "; color: #7fc46b; }
#wu-ownfiles .checks .n::before { content: "✗ "; color: #e07070; }
#wu-ownfiles .msg { margin: 12px 0 0; font-size: 13px; }
#wu-ownfiles .msg.err { color: #e07070; }
#wu-ownfiles .msg.warn { color: #d9b45a; }
#wu-ownfiles .row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 16px; }
#wu-ownfiles .or { color: #777; font-size: 13px; margin: 14px 0 8px; text-align: center; }
#wu-ownfiles .hidden { display: none !important; }
`;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}

function createUi(opts) {
  const style = el('style');
  style.textContent = CSS;
  const input = el('input', { type: 'file', class: 'hidden', webkitdirectory: '', multiple: '' });
  const chooseBtn = el('button', { class: 'primary', type: 'button', 'data-act': 'choose' }, 'Choose folder');
  const zone = el('div', { class: 'zone', 'data-zone': '' },
    el('p', {}, 'Drop your 3.3.5a game ', el('b', {}, 'Data'), ' folder here'),
    el('div', {}, chooseBtn));
  const continueBtn = el('button', { class: 'primary hidden', type: 'button', 'data-act': 'continue' }, 'Continue');
  const forgetBtn = el('button', { class: 'link hidden', type: 'button', 'data-act': 'forget' }, 'Forget my folder');
  const streamBtn = el('button', { class: 'ghost hidden', type: 'button', 'data-act': 'stream' }, 'Stream a mini version instead');
  const checks = el('ul', { class: 'checks hidden' });
  const msg = el('div', { class: 'msg hidden' });
  const card = el('div', { class: 'card', role: 'dialog', 'aria-labelledby': 'wu-ownfiles-title' },
    el('h1', { id: 'wu-ownfiles-title' }, 'Use my own game files'),
    el('p', { class: 'sub' }, 'Play with the 3.3.5a (12340) game files already on this computer.'),
    zone,
    el('div', { class: 'privacy' }, el('span', {}, '🔒'),
      el('span', {}, 'Your game files stay on this computer. Nothing is uploaded: this browser tab reads the MPQ files straight from your disk.')),
    checks,
    msg,
    el('div', { class: 'row' }, continueBtn, streamBtn, el('span', { style: 'flex:1' }), forgetBtn),
    input);
  const root = el('div', { id: 'wu-ownfiles' }, style, card);
  (opts.mount || document.body).appendChild(root);

  const ui = {
    root, zone, input, chooseBtn, continueBtn, forgetBtn, streamBtn,
    setChecks(report) {
      checks.replaceChildren();
      if (!report) return checks.classList.add('hidden');
      for (const c of report.checks) checks.append(el('li', { class: c.ok ? 'y' : 'n' }, c.name));
      if (report.build) checks.append(el('li', { class: report.build.build === 12340 ? 'y' : 'n' }, `build ${report.build.version || report.build.build}`));
      checks.classList.remove('hidden');
    },
    message(text, kind = '') {
      msg.className = 'msg' + (kind ? ' ' + kind : '') + (text ? '' : ' hidden');
      msg.replaceChildren();
      for (const line of [].concat(text || [])) msg.append(el('div', {}, line));
    },
    busy(on) {
      chooseBtn.disabled = on;
      continueBtn.disabled = on;
      zone.style.opacity = on ? '.6' : '';
    },
    remove() { root.remove(); },
  };
  return ui;
}

// --- the flow ------------------------------------------------------------------------------------

/// Resolve when the client can boot: `{ mode: 'own' | 'host' }` (choosing the streaming version
/// navigates away). `opts`: `{ base, mount, streamUrl, probeHost }`.
///   `?data=host`    trust the origin's /data (wenilla-host), never show the chooser
///   `?ownfiles=1`   show the chooser even when the origin serves /data or a folder is remembered
export async function ensureDataSource(opts = {}) {
  const base = opts.base || import.meta.url;
  const q = new URLSearchParams(location.search);
  if (q.get('data') === 'host') return { mode: 'host' };
  const forceUi = q.get('ownfiles') === '1';
  if (!forceUi && opts.probeHost !== false && (await hostServesData())) return { mode: 'host' };
  const supported = typeof Worker === 'function' && typeof SharedArrayBuffer === 'function' && window.crossOriginIsolated === true;
  if (!supported) return chooser(opts, base, { unsupported: true });
  const rec = await kvGet('source');
  if (rec && rec.kind === 'handle' && rec.handle && !forceUi) {
    let perm = 'prompt';
    try { perm = await rec.handle.queryPermission({ mode: 'read' }); } catch (_) {}
    if (perm === 'granted') {
      try {
        const r = await mountHandle(base, rec.handle, rec.label);
        return { mode: 'own', archives: r.archives, label: rec.label };
      } catch (_) { /* the folder moved or changed: offer it again below */ }
    }
    return chooser(opts, base, { regrant: rec });
  }
  return chooser(opts, base, { redrop: rec && rec.kind === 'files' ? rec : null });
}

/// Forget the remembered folder: the IndexedDB handle and the mounted chain.
export async function forgetFolder() {
  await kvDel('source');
  if (engine) await engine.forget();
}

/// Requests answered so far (sync = the client's blocking XHRs), for diagnostics.
export function ownFilesStats() {
  return engine ? { ...engine.stats } : null;
}

function chooser(opts, base, state) {
  return new Promise((resolve) => {
    const ui = createUi(opts);
    const L = loadLibs(base);
    const streamUrl = opts.streamUrl || STREAM_URL;
    if (window.WU_STREAM_AVAILABLE) ui.streamBtn.classList.remove('hidden');
    ui.streamBtn.addEventListener('click', () => { location.href = streamUrl; });

    if (state.unsupported) {
      ui.message('This page cannot read local game files: it needs Web Workers and SharedArrayBuffer, i.e. a cross-origin-isolated page (served with COOP: same-origin and COEP: require-corp) over https or localhost.', 'err');
      ui.zone.classList.add('hidden');
      return; // only the stream option (if any) remains
    }
    if (state.regrant) {
      ui.forgetBtn.classList.remove('hidden');
      ui.continueBtn.textContent = `Continue with “${state.regrant.label || state.regrant.handle.name}”`;
      ui.continueBtn.classList.remove('hidden');
      ui.message('Your browser needs your OK once more to read the folder you chose last time.');
    }
    if (state.redrop) {
      ui.forgetBtn.classList.remove('hidden');
      ui.message('This browser cannot remember folders between visits. Drop your Data folder again (or choose it).');
    }

    const finish = (r, label) => {
      ui.remove();
      resolve({ mode: 'own', archives: r.archives, label });
    };

    // One path for every intake: validate in the page, then hand the File references over.
    const accept = async (entriesP, handle) => {
      ui.busy(true);
      ui.message('Checking your folder…');
      try {
        const { entries, label } = await entriesP;
        const Chain = await L;
        const report = await Chain.validate(entries, label);
        ui.setChecks(report);
        if (!report.ok) {
          ui.message(report.errors, 'err');
          return;
        }
        if (report.warnings.length) ui.message(report.warnings, 'warn');
        if (handle) await kvSet('source', { kind: 'handle', handle, label });
        else await kvSet('source', { kind: 'files', label });
        ui.message((report.warnings.length ? report.warnings.concat(['']) : []).concat(['Opening the archives…']), report.warnings.length ? 'warn' : '');
        const r = await mountEntries(base, entries, label);
        finish(r, label);
      } catch (e) {
        ui.message(`Could not use this folder: ${e && e.message ? e.message : e}`, 'err');
      } finally {
        ui.busy(false);
      }
    };
    const fromHandle = async (handle) => {
      const Chain = await L;
      return { entries: await Chain.entriesFromHandle(handle), label: handle.name };
    };

    ui.continueBtn.addEventListener('click', async () => {
      const h = state.regrant.handle;
      let perm = 'denied';
      try { perm = await h.requestPermission({ mode: 'read' }); } catch (e) { ui.message(String(e), 'err'); }
      if (perm === 'granted') accept(fromHandle(h), h);
      else ui.message('Permission was not granted. Choose the folder again, or allow access.', 'err');
    });
    ui.forgetBtn.addEventListener('click', async () => {
      await forgetFolder();
      ui.forgetBtn.classList.add('hidden');
      ui.continueBtn.classList.add('hidden');
      ui.setChecks(null);
      ui.message('Forgotten. This site no longer has access to your folder.');
      state.regrant = null;
    });
    ui.chooseBtn.addEventListener('click', async () => {
      if (window.showDirectoryPicker) {
        let h;
        try {
          h = await window.showDirectoryPicker({ id: 'wow-335a-data', mode: 'read' });
        } catch (e) {
          if (e && e.name === 'AbortError') return;
          ui.input.click(); // e.g. a sandboxed frame: fall back to the plain folder input
          return;
        }
        accept(fromHandle(h), h);
      } else {
        ui.input.click();
      }
    });
    ui.input.addEventListener('change', () => {
      if (ui.input.files && ui.input.files.length) accept(Promise.resolve(entriesFromInput(ui.input.files)), null);
    });

    const zone = ui.zone;
    const over = (on) => (e) => {
      e.preventDefault();
      if (on && e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      zone.classList.toggle('over', on);
    };
    zone.addEventListener('dragenter', over(true));
    zone.addEventListener('dragover', over(true));
    zone.addEventListener('dragleave', over(false));
    // Dropping outside the zone must not navigate the tab to the file.
    ui.root.addEventListener('dragover', (e) => e.preventDefault());
    ui.root.addEventListener('drop', (e) => e.preventDefault());
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.remove('over');
      const items = [...(e.dataTransfer ? e.dataTransfer.items : [])].filter((i) => i.kind === 'file');
      // Both APIs must be called synchronously, inside the drop event.
      const handles = items.map((i) => (typeof i.getAsFileSystemHandle === 'function' ? i.getAsFileSystemHandle() : null));
      const entries = items.map((i) => (typeof i.webkitGetAsEntry === 'function' ? i.webkitGetAsEntry() : null));
      (async () => {
        if (handles.length === 1 && handles[0]) {
          const h = await handles[0].catch(() => null);
          if (h && h.kind === 'directory') return accept(fromHandle(h), h);
        }
        const list = entries.filter(Boolean);
        if (list.length) return accept(entriesFromEntries(list), null);
        ui.message('Drop the folder itself (not individual files).', 'err');
      })();
    });
  });
}
