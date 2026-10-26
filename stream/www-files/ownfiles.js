// ownfiles.js — the player's own 3.3.5a game folder, read in this browser tab (page side).
//
//   import { ensureDataSource } from './ownfiles.js';
//   const source = await ensureDataSource();   // resolves once /data/* is answerable
//
// Two uses of the same engine:
//
//   * Own mode ("Play with my own game files", /?ownfiles=1, the server sends no /data): the player
//     picks their 3.3.5a game folder (or its Data folder) and it answers every /data name.
//   * The layer (the streamed page, the default): streamed play stays as it is. Any time the player
//     drops their 3.3.5a game folder on the page (at character select or in the world), picks it
//     from the page menu or from the game (Esc > Mods & Workshop > Leyline realms > Use my game
//     folder), it becomes a layer: the streamed slice answers first, the player's own archives answer
//     every name the slice lacks, and /data/__index is the union (the client decides "not in patch
//     chain" from that index, read once per page: benilla-formats chain.rs `Chain::index`). The page
//     then asks the portal (POST /__gate?layer=on) to lift the realm's zone limit for the account (the
//     same SOAP clear as own mode); without the folder the next page load asks for it back
//     (layer=off), and a lease the page renews runs out by itself when the tab is gone (the portal
//     re-marks the account), so the realm never strands a streamed player where they can't load.
//     A folder chosen after the client has read its index needs one page load: the page keeps the
//     session, shows "Opening the whole world…", and seats the same character again.
//
// The folder is checked before anything else: the build is read from the files (component.wow-
// data.txt or the game's exe; 3.3.5a = 12340), and a 1.12, 2.4.3 or newer folder is refused.
//
// Why a page-level shim and not a service worker: the wasm client reads the chain with
// *synchronous* XMLHttpRequest (benilla-formats/src/web.rs), and Chromium does not route
// synchronous XHR through service workers. So `XMLHttpRequest` and `fetch` are wrapped for
// `/data/*` only: async requests are a message round trip to the worker; a sync request blocks in
// send() spinning on a SharedArrayBuffer while the worker writes the answer into shared memory (the
// page is cross-origin isolated). A name the worker answers "pass" goes on to the real
// XHR/fetch: wrath-early.js's retries and sections.js's downloaded sections stay in that path.
//
// Chrome/Edge: the folder handle is remembered in IndexedDB; a later visit mounts it silently when
// the browser kept the permission, else after one click. Firefox/Safari: no persistent folder
// handles, so the folder is dropped (or chosen) each visit. Nothing is ever uploaded.

const DB_NAME = 'wu-ownfiles';
const STORE = 'kv';
const STREAM_URL = 'https://play.openvanilla.app/wrath/play?mini=mini';
export const HELP_URL = 'https://play.openvanilla.app/wrath/docs/play#use-your-own-game-folder-to-go-anywhere';
const DATA_PREFIX = '/data/';
const ARENA_INITIAL = 16 * 1024 * 1024;
const RELOAD_KEY = 'wu-layer';         // sessionStorage: a folder was chosen, the page reloads to use it
const RELOAD_FRESH_MS = 10 * 60 * 1000;
const BEAT_MS = 4 * 60 * 1000;          // the realm lease (the portal keeps it 15 min)
const ASK_WAIT_MS = 20000;              // the one-click card at boot: then streamed play starts by itself

// Tunables (tests shorten them): the sync wait, and how long a silent worker counts as dead.
export const TIMING = { syncTimeoutMs: 120000, deadMs: 20000, asyncTimeoutMs: 60000, restartWaitMs: 1000 };

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

function session(get, value) {
  try {
    if (get) return JSON.parse(sessionStorage.getItem(RELOAD_KEY) || 'null');
    if (value === null) sessionStorage.removeItem(RELOAD_KEY);
    else sessionStorage.setItem(RELOAD_KEY, JSON.stringify(value));
  } catch (_) { /* storage blocked */ }
  return null;
}

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
  constructor(base, opts = {}) {
    this.base = base;
    this.layer = !!opts.layer;
    this.onDead = opts.onDead || null;
    this.ctlSab = new SharedArrayBuffer(32);
    this.ctl = new Int32Array(this.ctlSab);
    this.arenaSab = new SharedArrayBuffer(ARENA_INITIAL);
    this.arena = new Uint8Array(this.arenaSab);
    this.nextId = 1;
    this.pending = new Map();
    this.source = null;          // what was mounted, for a restart: {type, entries|handle, label, slice, locale}
    this.dead = null;            // why the worker stopped answering, or null
    this.failures = 0;           // own reads that failed in a row (a revoked permission, a changed file)
    this.stats = { sync: 0, async: 0, syncMs: 0, pass: 0, own: 0, restarts: 0 };
    this.spawn();
  }
  spawn() {
    this.worker = new Worker(new URL('./ownfiles-worker.js', this.base).href);
    this.worker.postMessage({ type: 'shared', ctl: this.ctlSab, arena: this.arenaSab });
    this.worker.onmessage = (e) => {
      const m = e.data || {};
      const p = this.pending.get(m.id);
      if (p) {
        this.pending.delete(m.id);
        clearTimeout(p.timer);
        p.resolve(m);
      }
    };
    this.worker.onerror = (e) => { try { e.preventDefault(); } catch (_) {} this.markDead('the worker failed'); };
  }
  markDead(why) {
    if (this.dead) return;
    this.dead = why;
    for (const [id, p] of this.pending) { clearTimeout(p.timer); p.resolve({ id, dead: true }); }
    this.pending.clear();
    try { this.worker.terminate(); } catch (_) {}
    if (this.onDead) setTimeout(() => this.onDead(why), 0);
  }
  /// A fresh worker, the same folder mounted again. Resolves true when it answers again.
  async restart() {
    if (!this.source) return false;
    this.stats.restarts++;
    try { this.worker.terminate(); } catch (_) {}
    Atomics.store(this.ctl, 6, 0);
    this.spawn();
    this.dead = null;
    this.failures = 0;
    try {
      await this.mountSource(this.source);
      return true;
    } catch (e) {
      this.dead = 'restart failed: ' + ((e && e.message) || e);
      return false;
    }
  }
  call(msg, transfer, timeoutMs = 0) {
    const id = this.nextId++;
    return new Promise((resolve) => {
      const p = { resolve, timer: 0 };
      if (timeoutMs) p.timer = setTimeout(() => { this.pending.delete(id); resolve({ id, timeout: true }); }, timeoutMs);
      this.pending.set(id, p);
      try { this.worker.postMessage({ ...msg, id }, transfer || []); } catch (e) { this.pending.delete(id); resolve({ id, dead: true }); }
    });
  }
  async mountSource(src) {
    const msg = src.type === 'handle'
      ? { type: 'mount-handle', handle: src.handle, label: src.label }
      : { type: 'mount', entries: src.entries, label: src.label };
    const r = await this.call({ ...msg, layer: this.layer, slice: src.slice ? src.slice.slice(0) : null, locale: src.locale, warmIndex: true },
      null, 0);
    if (r.dead) throw new Error(this.dead || 'the worker stopped');
    if (!r.ok) throw new Error(r.error || 'could not open the archives');
    this.source = src;
    return r;
  }
  mount(entries, label, extra = {}) { return this.mountSource({ type: 'files', entries, label, ...extra }); }
  mountHandle(handle, label, extra = {}) { return this.mountSource({ type: 'handle', handle, label, ...extra }); }
  noteOwn(status) {
    if (status >= 500) {
      if (++this.failures >= 3) this.markDead('your game folder could not be read (moved, changed, or the browser took back its permission)');
    } else this.failures = 0;
  }
  async asyncRequest(method, path, own) {
    this.stats.async++;
    if (this.dead) return this.layer ? { pass: true } : { status: 503, headers: {}, body: null };
    const m = await this.call({ type: 'async', method, path, own }, null, TIMING.asyncTimeoutMs);
    if (m.timeout) { this.markDead('the worker stopped answering'); return this.layer ? { pass: true } : { status: 503, headers: {}, body: null }; }
    if (m.dead) return this.layer ? { pass: true } : { status: 503, headers: {}, body: null };
    if (m.pass) { this.stats.pass++; return { pass: true }; }
    this.stats.own++;
    this.noteOwn(m.status);
    return { status: m.status, headers: m.headers || {}, body: m.body };
  }
  /// Blocks the calling (main) thread until the worker has answered. Only ever used for a
  /// synchronous XHR, which blocks the thread anyway. A worker that stops beating for
  /// TIMING.deadMs (killed, crashed) is given up on: the layer then passes every name to the
  /// server, own mode answers 503.
  syncRequest(method, path, own) {
    const t0 = performance.now();
    this.stats.sync++;
    const fail = () => (this.layer ? { pass: true } : { status: 503, headers: {}, body: null });
    if (this.dead) return fail();
    for (let attempt = 0; attempt < 4; attempt++) {
      Atomics.store(this.ctl, 0, 1);
      try { this.worker.postMessage({ type: 'sync', method, path, own }); } catch (_) { this.markDead('the worker is gone'); return fail(); }
      let spins = 0, beat = Atomics.load(this.ctl, 6), beatAt = t0;
      while (Atomics.load(this.ctl, 0) === 1) {
        if ((++spins & 0x3ffff) === 0) {
          const t = performance.now();
          const b = Atomics.load(this.ctl, 6);
          if (b !== beat) { beat = b; beatAt = t; }
          if (t - beatAt > TIMING.deadMs) { this.markDead('the worker stopped answering'); return fail(); }
          if (t - t0 > TIMING.syncTimeoutMs) return this.layer ? { pass: true } : { status: 500, headers: {}, body: null };
        }
      }
      const status = this.ctl[1], len = this.ctl[2], flags = this.ctl[3];
      if (flags === 3) { this.stats.pass++; return { pass: true }; }
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
      this.stats.own++;
      this.noteOwn(status);
      return { status, headers, body };
    }
    return this.layer ? { pass: true } : { status: 500, headers: {}, body: null };
  }
  forget() {
    this.source = null;
    return this.call({ type: 'forget' }, null, 5000);
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

/// Wrap XMLHttpRequest and fetch so same-origin `/data/*` is answered by the engine (or, for a
/// name the engine passes, by the real XHR/fetch underneath: the retries, the server).
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
      this._own = { method: String(method).toUpperCase(), path, url, rest, async: async === undefined || !!async, mime: null,
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
    /// The real request for a name the engine passed: the same object, so the caller's
    /// listeners and getters see it as if nothing happened.
    _pass(o, body) {
      this._own = null;
      super.open(o.method, o.url, o.async, ...o.rest);
      if (o.mime) super.overrideMimeType(o.mime);
      if (o.async && o.responseType) { try { super.responseType = o.responseType; } catch (_) {} }
      return super.send(body);
    }
    send(body) {
      const o = this._own;
      if (!o) return super.send(body);
      if (!o.async) {
        const r = eng.syncRequest(o.method, o.path, false);
        if (!r.pass) return this._finish(r);
        let thrown = null;
        try { this._pass(o, body); } catch (e) { thrown = e; }
        // The server failed a slice name even after the retries: the folder may have it.
        const bad = thrown || super.status === 0 || super.status >= 500;
        if (bad && eng.layer && !eng.dead) {
          const own = eng.syncRequest(o.method, o.path, true);
          if (!own.pass && own.status === 200) { this._own = o; return this._finish(own); }
        }
        if (thrown) throw thrown;
        return undefined;
      }
      eng.asyncRequest(o.method, o.path, false).then((r) => (r.pass ? this._pass(o, body) : this._finish(r)),
        () => this._finish({ status: 0, headers: {}, body: null, failed: true }));
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
    return eng.asyncRequest(method, path, false).then((r) => {
      if (r.pass) return realFetch(input, init);
      if (signal && signal.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
      return new Response(method === 'HEAD' || !r.body ? null : r.body, { status: r.status, statusText: STATUS_TEXT[r.status] || '', headers: r.headers });
    });
  };
  if (!eng.layer) window.__ownfiles = { stats: eng.stats };   // sections.js stays off in own mode
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
  if (!engine) engine = new Engine(base, { onDead: ownDied });
  return engine;
}

/// Own mode: the worker died. One restart; else say so (there is no stream to fall back to here).
async function ownDied(why) {
  layerState.error = why;
  await new Promise((r) => setTimeout(r, TIMING.restartWaitMs));
  if (engine && (await engine.restart())) { toast('Your game folder is back.'); return; }
  layerState.mounted = false;
  toast(`The game cannot read your game folder any more: ${why}. Reload the page to choose it again.`, { ms: 0, help: true });
}

async function mountEntries(base, entries, label) {
  const eng = getEngine(base);
  const r = await eng.mount(entries, label, { locale: preferredLocale() });
  installShim(eng);
  return r;
}

async function mountHandle(base, handle, label) {
  const eng = getEngine(base);
  const r = await eng.mountHandle(handle, label, { locale: preferredLocale() });
  installShim(eng);
  return r;
}

/// The player's language as a locale folder name (en-GB -> enGB), for a folder with several.
function preferredLocale() {
  try {
    const m = /^([a-z]{2})-([A-Z]{2})/.exec(navigator.language || '');
    return m ? m[1] + m[2] : null;
  } catch (_) { return null; }
}

function userActive() {
  try { return !!(navigator.userActivation && navigator.userActivation.isActive); } catch (_) { return false; }
}

function browserKeepsFolders() {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function';
}

// --- folder intake ---------------------------------------------------------------------------------

const readAllEntries = (dirEntry) =>
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

/// Firefox/Safari (and Chrome when no handle is offered): walk FileSystemEntry trees. Only
/// `file()` is called: File references, no bytes read.
async function entriesFromEntries(list) {
  const out = [];
  const fileOf = (fe) => new Promise((resolve, reject) => fe.file(resolve, reject));
  const eqi = (a, b) => a.toLowerCase() === b.toLowerCase();
  const walkData = async (dir, prefix) => {
    for (const e of await readAllEntries(dir)) {
      if (e.isFile) out.push({ path: prefix + e.name, file: await fileOf(e) });
      else if (e.isDirectory) for (const e2 of await readAllEntries(e)) if (e2.isFile) out.push({ path: `${prefix}${e.name}/${e2.name}`, file: await fileOf(e2) });
    }
  };
  const walkAll = async (dir, prefix, depth) => {
    if (depth > 12) return;
    for (const e of await readAllEntries(dir)) {
      if (e.name.startsWith('.')) continue;
      if (e.isFile) out.push({ path: prefix + e.name, file: await fileOf(e) });
      else await walkAll(e, prefix + e.name + '/', depth + 1);
    }
  };
  if (list.length === 1 && list[0].isDirectory) {
    const root = list[0];
    const top = await readAllEntries(root);
    const hasCommon = top.some((e) => e.isFile && eqi(e.name, 'common.MPQ'));
    const data = top.find((e) => e.isDirectory && eqi(e.name, 'Data'));
    if (!hasCommon && data) {
      await walkData(data, 'Data/');
      for (const e of top) if (e.isFile && /\.exe$/i.test(e.name)) out.push({ path: e.name, file: await fileOf(e) });
      const iface = top.find((e) => e.isDirectory && eqi(e.name, 'Interface'));
      if (iface) await walkAll(iface, 'Interface/', 0);
    } else {
      await walkData(root, '');
    }
    return { entries: out, label: root.name };
  }
  // Several items: the Data folder's contents were selected and dropped (or loose archives).
  for (const e of list) {
    if (e.isFile) out.push({ path: e.name, file: await fileOf(e) });
    else if (e.isDirectory) for (const e2 of await readAllEntries(e)) if (e2.isFile) out.push({ path: `${e.name}/${e2.name}`, file: await fileOf(e2) });
  }
  return { entries: out, label: 'Data' };
}

/// `<input webkitdirectory>`: every file under the chosen folder, with its relative path.
function entriesFromInput(files) {
  const list = [...files].map((f) => ({ path: f.webkitRelativePath || f.name, file: f }));
  const first = list[0] && list[0].path.split('/')[0];
  return { entries: list, label: first || 'Data' };
}

/// A drop, captured synchronously inside the drop event (the browser empties dataTransfer after
/// it): { handles: [Promise<handle>|null], entries: [FileSystemEntry|null], files: [File] }.
export function snapshotDrop(dt) {
  const items = [...((dt && dt.items) || [])].filter((i) => i.kind === 'file');
  return {
    handles: items.map((i) => (typeof i.getAsFileSystemHandle === 'function' ? i.getAsFileSystemHandle().catch(() => null) : null)),
    entries: items.map((i) => (typeof i.webkitGetAsEntry === 'function' ? i.webkitGetAsEntry() : null)),
    files: [...((dt && dt.files) || [])],
  };
}

/// 'game' | 'addon' | 'unknown' for a snapshot: the names at its top, one level down for folders.
export async function classifySnapshot(snap) {
  const Chain = await loadLibs(import.meta.url);
  const top = [];
  const entries = (snap.entries || []).filter(Boolean);
  if (entries.length) {
    for (const e of entries.slice(0, 64)) {
      if (e.isDirectory) {
        let kids = [];
        try { kids = (await readAllEntries(e)).slice(0, 400).map((k) => k.name); } catch (_) {}
        top.push({ name: e.name, dir: true, kids });
      } else top.push({ name: e.name, dir: false });
    }
  } else {
    for (const f of snap.files || []) top.push({ name: f.name, dir: false });
  }
  return Chain.classifyDrop(top);
}

// --- the UI ------------------------------------------------------------------------------------------

const CSS = `
#wu-ownfiles { position: fixed; inset: 0; z-index: 70; display: grid; place-items: center;
  background: rgba(0,0,0,.94); color: #ddd; font: 15px/1.45 system-ui, sans-serif; }
#wu-ownfiles.soft { background: rgba(0,0,0,.72); }
#wu-ownfiles .card { position: relative; width: min(560px, calc(100vw - 32px)); background: #111; border: 1px solid #2a2a2a;
  border-radius: 10px; padding: 22px 24px; box-shadow: 0 10px 40px rgba(0,0,0,.6); box-sizing: border-box; }
#wu-ownfiles h1 { margin: 0 0 4px; font-size: 19px; color: #f0e2b0; font-weight: 600; padding-right: 28px; }
#wu-ownfiles .sub { margin: 0 0 16px; color: #999; font-size: 13px; }
#wu-ownfiles .help { position: absolute; top: 16px; right: 18px; width: 24px; height: 24px; border-radius: 50%;
  display: grid; place-items: center; border: 1px solid #555; color: #ccc; text-decoration: none; font-weight: 600; font-size: 14px; }
#wu-ownfiles .help:hover { border-color: #c9a227; color: #f0e2b0; }
#wu-ownfiles .zone { border: 2px dashed #3a3a3a; border-radius: 8px; padding: 22px 16px; text-align: center;
  transition: border-color .15s, background .15s; }
#wu-ownfiles .zone.over { border-color: #c9a227; background: rgba(201,162,39,.07); }
#wu-ownfiles .zone p { margin: 0 0 6px; }
#wu-ownfiles .zone .where { color: #8d8d8d; font-size: 12px; margin: 0 0 12px; }
#wu-ownfiles button { font: inherit; cursor: pointer; border-radius: 6px; padding: 7px 14px; }
#wu-ownfiles button.primary { background: #c9a227; color: #111; border: 0; font-weight: 600; }
#wu-ownfiles button.primary:hover { background: #d8b23a; }
#wu-ownfiles button.ghost { background: transparent; color: #bbb; border: 1px solid #444; }
#wu-ownfiles button.ghost:hover { border-color: #777; color: #eee; }
#wu-ownfiles button.link { background: none; border: 0; color: #9aa7c7; padding: 0; text-decoration: underline; font-size: 13px; }
#wu-ownfiles button:disabled { opacity: .5; cursor: default; }
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
#wu-ownfiles .hidden { display: none !important; }
#wu-layer-cover { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center;
  background: radial-gradient(120% 90% at 50% 45%, #14223a 0%, #070b14 60%, #020306 100%);
  color: #d8e6f5; font: 600 clamp(15px, 2.4vh, 22px) Georgia, serif; letter-spacing: .08em; text-align: center; }
#wu-layer-cover small { display: block; margin-top: 10px; font: 13px system-ui, sans-serif; letter-spacing: 0; color: #9fb3c9; }
#wu-layer-toast { position: fixed; left: 10px; bottom: 44px; z-index: 75; max-width: min(460px, calc(100vw - 20px));
  padding: 8px 30px 8px 12px; border-radius: 8px; background: rgba(10,8,18,.92); border: 1px solid rgba(201,162,39,.55);
  color: #e8e2d0; font: 13px/1.4 system-ui, sans-serif; box-shadow: 0 4px 16px rgba(0,0,0,.5); }
#wu-layer-toast button { all: unset; position: absolute; top: 4px; right: 8px; cursor: pointer; color: #9a917f; font-size: 15px; }
#wu-layer-toast a { color: #f3d179; }
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

function css() {
  if (document.getElementById('wu-ownfiles-css')) return;
  const style = el('style', { id: 'wu-ownfiles-css' });
  style.textContent = CSS;
  (document.head || document.documentElement).append(style);
}

const WHERE = 'The folder you start the 3.3.5a game from: it holds a "Data" folder with common.MPQ and lichking.MPQ (the Data folder itself works too).';

/// The folder card. `opts.text`: { title, sub, stream } override the own-mode words.
function createUi(opts) {
  css();
  const t = opts.text || {};
  const input = el('input', { type: 'file', class: 'hidden', webkitdirectory: '', multiple: '' });
  const chooseBtn = el('button', { class: 'primary', type: 'button', 'data-act': 'choose' }, 'Choose folder');
  const zone = el('div', { class: 'zone', 'data-zone': '' },
    el('p', {}, 'Drop your 3.3.5a game folder here'),
    el('p', { class: 'where' }, WHERE),
    el('div', {}, chooseBtn));
  const continueBtn = el('button', { class: 'primary hidden', type: 'button', 'data-act': 'continue' }, 'Continue');
  const forgetBtn = el('button', { class: 'link hidden', type: 'button', 'data-act': 'forget' }, 'Forget my folder');
  const streamBtn = el('button', { class: 'ghost hidden', type: 'button', 'data-act': 'stream' }, t.stream || 'Stream a mini version instead');
  const checks = el('ul', { class: 'checks hidden' });
  const msg = el('div', { class: 'msg hidden', role: 'status' });
  const card = el('div', { class: 'card', role: 'dialog', 'aria-labelledby': 'wu-ownfiles-title' },
    el('a', { class: 'help', href: HELP_URL, target: '_blank', rel: 'noopener', title: 'Help: using your own game folder', 'aria-label': 'Help' }, '?'),
    el('h1', { id: 'wu-ownfiles-title' }, t.title || 'Use my own game files'),
    el('p', { class: 'sub' }, t.sub || 'Play with the 3.3.5a (12340) game files already on this computer.'),
    zone,
    el('div', { class: 'privacy' }, el('span', {}, '🔒'),
      el('span', {}, 'Your game files stay on this computer. Nothing is uploaded: this browser tab reads the MPQ files straight from your disk.')),
    checks,
    msg,
    el('div', { class: 'row' }, continueBtn, streamBtn, el('span', { style: 'flex:1' }), forgetBtn),
    input);
  const root = el('div', { id: 'wu-ownfiles', class: opts.soft ? 'soft' : '' }, card);
  (opts.mount || document.body).appendChild(root);
  // keys typed here are for the card, not the game
  root.addEventListener('keydown', (e) => e.stopPropagation(), true);
  root.addEventListener('keyup', (e) => e.stopPropagation(), true);

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

/// Wire a card's intake (choose, the folder input, drops on the zone, a game-folder drop routed
/// here from the page's drop target) to `accept(entriesPromise, handle|null)`.
function wireIntake(ui, accept, base) {
  const L = loadLibs(base);
  const fromHandle = async (handle) => {
    const Chain = await L;
    return { entries: await Chain.entriesFromHandle(handle), label: handle.name };
  };
  ui.chooseBtn.addEventListener('click', async () => {
    if (window.showDirectoryPicker) {
      let h;
      try {
        h = await window.showDirectoryPicker({ id: 'game-335a-data', mode: 'read' });
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
  const takeSnapshot = async (snap) => {
    if (snap.handles.length === 1 && snap.handles[0]) {
      const h = await snap.handles[0];
      if (h && h.kind === 'directory') return accept(fromHandle(h), h);
    }
    const list = snap.entries.filter(Boolean);
    if (list.length) return accept(entriesFromEntries(list), null);
    ui.message('Drop the folder itself (not individual files).', 'err');
    return null;
  };
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
    takeSnapshot(snapshotDrop(e.dataTransfer));
  });
  return { fromHandle, takeSnapshot };
}

let activeCard = null;   // { takeSnapshot } while a folder card is open: the page's drops go there

function toast(text, opts = {}) {
  if (typeof document === 'undefined' || !document.body) return null;
  css();
  const old = document.getElementById('wu-layer-toast');
  if (old) old.remove();
  const box = el('div', { id: 'wu-layer-toast', role: 'status' }, text);
  if (opts.help) box.append(' ', el('a', { href: HELP_URL, target: '_blank', rel: 'noopener' }, 'Help'));
  box.append(el('button', { type: 'button', 'aria-label': 'Dismiss', onclick: () => box.remove() }, '×'));
  document.body.append(box);
  if (opts.ms !== 0) setTimeout(() => box.remove(), opts.ms || 12000);
  return box;
}

function cover(text, sub) {
  css();
  const c = el('div', { id: 'wu-layer-cover', role: 'status' }, el('div', {}, text, sub ? el('small', {}, sub) : null));
  document.body.append(c);
  return c;
}

// --- own mode ------------------------------------------------------------------------------------

/// Resolve when the client can boot: `{ mode: 'own' | 'host', layer? }` (choosing the streaming
/// version navigates away). `opts`: `{ base, mount, streamUrl, probeHost, layer }`.
///   `?data=host`    trust the origin's /data (wenilla-host), never show the chooser
///   `?ownfiles=1`   show the chooser even when the origin serves /data or a folder is remembered
///   `?layer=0`      the streamed page without the game-folder layer this visit
export async function ensureDataSource(opts = {}) {
  const base = opts.base || import.meta.url;
  const q = new URLSearchParams(location.search);
  if (q.get('data') === 'host') return { mode: 'host' };
  const forceUi = q.get('ownfiles') === '1';
  if (!forceUi && opts.probeHost !== false && (await hostServesData())) {
    let layer = null;
    if (opts.layer !== false && q.get('layer') !== '0') {
      try { layer = await bootLayer(opts, base); } catch (e) { console.warn('game folder layer:', e); }
    }
    layerState.phase = 'started';
    return { mode: 'host', layer };
  }
  layerState.mode = 'own';
  const supported = typeof Worker === 'function' && typeof SharedArrayBuffer === 'function' && window.crossOriginIsolated === true;
  if (!supported) return chooser(opts, base, { unsupported: true });
  const rec = await kvGet('source');
  if (rec && rec.kind === 'handle' && rec.handle && !forceUi) {
    let perm = 'prompt';
    try { perm = await rec.handle.queryPermission({ mode: 'read' }); } catch (_) {}
    if (perm === 'granted') {
      try {
        const r = await mountHandle(base, rec.handle, rec.label);
        ownMounted(r, rec.label);
        return { mode: 'own', archives: r.archives, label: rec.label };
      } catch (_) { /* the folder moved or changed: offer it again below */ }
    }
    return chooser(opts, base, { regrant: rec });
  }
  return chooser(opts, base, { redrop: rec && rec.kind === 'files' ? rec : null });
}

function ownMounted(r, label) {
  layerState.mounted = true;
  layerState.label = label;
  layerState.locale = r.locale || null;
  layerState.archives = r.archives || [];
}

/// Forget the remembered folder: the IndexedDB handle and the mounted chain.
export async function forgetFolder() {
  await kvDel('source');
  session(false, null);
  if (engine) await engine.forget();
}

/// Requests answered so far (sync = the client's blocking XHRs), for diagnostics.
export function ownFilesStats() {
  return engine ? { ...engine.stats } : null;
}

function chooser(opts, base, state) {
  return new Promise((resolve) => {
    const ui = createUi(opts);
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
      ui.message('This browser cannot remember folders between visits. Drop your game folder again (or choose it).');
    }

    const finish = (r, label) => {
      activeCard = null;
      ui.remove();
      ownMounted(r, label);
      resolve({ mode: 'own', archives: r.archives, label });
    };

    // One path for every intake: validate in the page, then hand the File references over.
    const accept = async (entriesP, handle) => {
      ui.busy(true);
      ui.message('Checking your folder…');
      try {
        const { entries, label } = await entriesP;
        const Chain = await loadLibs(base);
        const report = await Chain.validate(entries, label, { locale: preferredLocale() });
        ui.setChecks(report);
        if (!report.ok) {
          ui.message(report.errors, 'err');
          return;
        }
        if (report.warnings.length) ui.message(report.warnings, 'warn');
        layerState.build = report.build ? report.build.build : null;
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
    const intake = wireIntake(ui, accept, base);
    activeCard = intake;

    ui.continueBtn.addEventListener('click', async () => {
      const h = state.regrant.handle;
      let perm = 'denied';
      try { perm = await h.requestPermission({ mode: 'read' }); } catch (e) { ui.message(String(e), 'err'); }
      if (perm === 'granted') accept(intake.fromHandle(h), h);
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
  });
}

// --- the layer (streamed page) -------------------------------------------------------------------

/// What the page and the game see (window.__wuOwnFiles.status(), the Lua global the page sets).
export const layerState = {
  mode: 'stream',        // 'stream' (the streamed page) or 'own'
  phase: 'boot',         // 'boot' until the client starts, then 'started' (a new folder needs a page load)
  mounted: false,        // a folder answers names now
  label: null,
  build: null,
  locale: null,
  archives: [],
  counts: null,          // { slice, own, ownOnly }: names in the slice, the folder, the folder only
  realm: 'unknown',      // 'lifted' (whole world), 'held' (streamed places), 'unknown', 'failed'
  remembered: false,     // a handle is kept in this browser (Chrome/Edge)
  error: null,
  note: null,
};

function env() { return (typeof window !== 'undefined' && window.__wenilla_env) || {}; }

/// Whether this page may offer the layer: a streamed session whose portal knows the layer route
/// (env.layer "1"), or ?layer=1 on a dev page. Never in a hop (another realm) or a guest pass.
export function layerAllowed(e = env(), search = (typeof location !== 'undefined' ? location.search : '')) {
  if (/[?&]layer=0\b/.test(search)) return false;
  if (e.hop || e.demo === '1' || e.mode === 'own') return false;
  return e.layer === '1' || /[?&]layer=1\b/.test(search);
}

function supportedHere() {
  return typeof Worker === 'function' && typeof SharedArrayBuffer === 'function' && window.crossOriginIsolated === true;
}

/// The realm's zone limit for this account: POST /__gate?layer=on|off|beat (wrath_portal.py).
/// Resolves { ok, state } and never throws.
export async function realmLayer(op, info = {}) {
  if (!layerAllowed()) return { ok: false, state: 'n/a' };
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 8000);
  try {
    const r = await fetch('/__gate?layer=' + encodeURIComponent(op), {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: ac.signal,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ build: info.build || null, names: info.names || 0 }),
    });
    let d = null;
    try { d = await r.json(); } catch (_) {}
    const ok = r.ok && !!(d && d.ok);
    const state = (d && d.state) || (ok ? (op === 'off' ? 'held' : 'lifted') : 'failed');
    if (op !== 'beat' || !ok) layerState.realm = ok ? state : 'failed';
    return { ok, state };
  } catch (_) {
    if (op !== 'beat') layerState.realm = 'failed';
    return { ok: false, state: 'failed' };
  } finally {
    clearTimeout(t);
  }
}

let beatTimer = 0;
function startBeat() {
  if (beatTimer || typeof setInterval !== 'function') return;
  const beat = () => { if (layerState.mounted) realmLayer('beat', { build: layerState.build }).then((r) => { if (!r.ok) realmLayer('on', { build: layerState.build }); }); };
  beatTimer = setInterval(beat, BEAT_MS);
  try { document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') beat(); }); } catch (_) {}
}

/// The streamed page before the client starts: a remembered folder (silently, or with one click),
/// a folder chosen just before this page load (Firefox: dropped once more), else streamed play
/// with the realm's limit back on. Resolves the layer's state or null.
async function bootLayer(opts, base) {
  if (!layerAllowed()) return null;
  // One game per browser (wrath-early.js): a tab that is about to give way must not touch the realm.
  if (window.__wuTabLock) {
    const held = await Promise.race([window.__wuTabLock, new Promise((r) => setTimeout(() => r(true), 3000))]);
    if (!held || window.__wuStopped) return null;
  }
  if (!supportedHere()) { await realmLayer('off'); return null; }
  const want = session(true);
  const fresh = want && Date.now() - (want.at || 0) < RELOAD_FRESH_MS ? want : null;
  const rec = await kvGet('source');
  layerState.remembered = !!(rec && rec.kind === 'handle' && rec.handle);
  let result = null;
  if (layerState.remembered) {
    let perm = 'prompt';
    try { perm = await rec.handle.queryPermission({ mode: 'read' }); } catch (_) {}
    if (perm === 'granted') {
      const c = fresh ? cover('Opening the whole world…', 'Reading your 3.3.5a game folder. Nothing is uploaded.') : null;
      try {
        result = await mountLayer(base, { type: 'handle', handle: rec.handle, label: rec.label });
      } catch (e) {
        layerState.error = String((e && e.message) || e);
      } finally {
        if (c) c.remove();
      }
      if (!result) result = await layerCard(opts, base, { regrant: rec, again: !!fresh, wait: fresh ? 0 : ASK_WAIT_MS });
    } else {
      result = await layerCard(opts, base, { regrant: rec, again: !!fresh, wait: fresh ? 0 : ASK_WAIT_MS });
    }
  } else if (fresh) {
    result = await layerCard(opts, base, { redrop: true, wait: 0 });
  } else if (rec && rec.kind === 'files') {
    // Firefox/Safari: the folder was used before, and these browsers ask on each visit.
    result = await layerCard(opts, base, { files: rec, wait: ASK_WAIT_MS });
  }
  session(false, null);
  if (!result) {
    await realmLayer('off');
    return null;
  }
  return result;
}

/// Mount a folder as the layer: the slice's own index from the server, the worker, the union index
/// handed to the client's body store (wrath-early.js reads window.__wuLayerIndex), the shim, then the
/// realm's limit lifted. Throws on a folder that will not open.
async function mountLayer(base, src) {
  let slice = null;
  try {
    const r = await fetch('/data/__index', { cache: 'no-store' });
    if (r.ok) slice = await r.arrayBuffer();
  } catch (_) { /* unknown slice: every name the folder lacks goes to the server */ }
  if (!engine) engine = new Engine(base, { layer: true, onDead: layerDied });
  const r = await engine.mountSource({ ...src, slice, locale: preferredLocale() });
  if (r.index) {
    window.__wuLayerIndex = r.index;
    try {
      const store = window.__wenilla_prefetch;
      if (store && !(window.__wuAddonLayer && window.__wuAddonLayer.store === store)) Map.prototype.set.call(store, '__index', r.index);
    } catch (_) {}
  }
  installShim(engine);
  layerState.mounted = true;
  layerState.label = src.label || (src.handle && src.handle.name) || 'Data';
  layerState.locale = r.locale || null;
  layerState.archives = r.archives || [];
  layerState.counts = r.counts || null;
  layerState.error = null;
  if (src.build) layerState.build = src.build;
  else if (layerState.build == null && src.type === 'handle') layerState.build = await buildOfHandle(base, src.handle).catch(() => null);
  const realm = await realmLayer('on', { build: layerState.build, names: (r.counts && r.counts.ownOnly) || 0 });
  if (!realm.ok) {
    layerState.note = 'The realm did not confirm: for now you stay in the streamed places. Reload the page to try again.';
    toast(layerState.note, { help: true });
  }
  startBeat();
  return { ...layerStatus() };
}

async function buildOfHandle(base, handle) {
  const Chain = await loadLibs(base);
  const entries = await Chain.entriesFromHandle(handle);
  const b = await Chain.detectBuild(entries);
  return b ? b.build : null;
}

/// The worker died (or the folder became unreadable): one restart, else streamed play again,
/// with the realm's limit back, and a plain message.
async function layerDied(why) {
  layerState.error = why;
  await new Promise((r) => setTimeout(r, TIMING.restartWaitMs));
  if (engine && (await engine.restart())) {
    layerState.mounted = true;
    toast('Your game folder is back.');
    return;
  }
  layerState.mounted = false;
  await realmLayer('off');
  toast(`Back to streamed play (Dalaran, the capitals, the starting areas): ${why}. Reload the page to use your game folder again.`, { ms: 0, help: true });
}

/// The layer's card: at boot (one click for a remembered folder, or "drop it once more"), or in
/// the game (the page menu, the in-game button, a refused drop). Resolves the layer state or null.
function layerCard(opts, base, state = {}) {
  return new Promise((resolve) => {
    const keeps = browserKeepsFolders();
    const ui = createUi({ ...opts, soft: layerState.phase === 'started', text: {
      title: state.redrop ? 'Drop your game folder once more' : 'Use your 3.3.5a game folder',
      sub: state.redrop
        ? 'This browser cannot keep a folder across a page load, so it needs it once more to open the whole world.'
        : 'Streamed play covers Dalaran, the capitals and the starting areas. Your own game folder opens the rest of the world, on the same realm and characters.',
      stream: layerState.phase === 'started' ? 'Not now' : 'Play streamed',
    } });
    ui.streamBtn.classList.remove('hidden');
    let timer = 0, settled = false;
    const done = (v) => {
      if (settled) return;
      settled = true;
      clearInterval(timer);
      activeCard = null;
      ui.remove();
      resolve(v);
    };
    ui.streamBtn.addEventListener('click', () => done(null));
    if (state.regrant) {
      ui.forgetBtn.classList.remove('hidden');
      ui.continueBtn.textContent = 'Use my game folder';
      ui.continueBtn.classList.remove('hidden');
      ui.message(state.again ? 'One click to read your folder.' : `Your browser asks once more before this page reads “${state.regrant.label || state.regrant.handle.name}”.`);
    } else if (state.files) {
      ui.forgetBtn.classList.remove('hidden');
      ui.message('Firefox and Safari ask for the folder on each visit: drop it here (or choose it) to open the whole world.');
    } else if (!keeps && layerState.phase !== 'started') {
      ui.message('Firefox and Safari ask for the folder on each visit.');
    }
    if (state.wait) {
      let left = Math.round(state.wait / 1000);
      const tick = () => { ui.streamBtn.textContent = `Play streamed (${left} s)`; if (left-- <= 0) done(null); };
      tick();
      timer = setInterval(tick, 1000);
      ui.root.addEventListener('pointerdown', () => { clearInterval(timer); ui.streamBtn.textContent = 'Play streamed'; }, { once: true });
    }
    const accept = async (entriesP, handle) => {
      clearInterval(timer);
      ui.streamBtn.textContent = layerState.phase === 'started' ? 'Not now' : 'Play streamed';
      ui.busy(true);
      ui.message('Checking your folder…');
      try {
        const { entries, label } = await entriesP;
        const Chain = await loadLibs(base);
        const report = await Chain.validate(entries, label, { locale: preferredLocale() });
        ui.setChecks(report);
        if (!report.ok) { ui.message(report.errors, 'err'); return; }
        const build = report.build ? report.build.build : null;
        layerState.build = build;
        if (handle) await kvSet('source', { kind: 'handle', handle, label });
        else await kvSet('source', { kind: 'files', label });
        if (layerState.phase === 'started') {
          // The client read its name index at start: one page load, the same session and character.
          ui.message('Opening the whole world…');
          await reloadIntoLayer(handle ? 'handle' : 'files');
          return;
        }
        ui.message((report.warnings.length ? report.warnings.concat(['']) : []).concat(['Opening the whole world…']), report.warnings.length ? 'warn' : '');
        const src = handle ? { type: 'handle', handle, label, build } : { type: 'files', entries, label, build };
        const r = await mountLayer(base, src);
        done(r);
      } catch (e) {
        ui.message(`Could not use this folder: ${e && e.message ? e.message : e}`, 'err');
      } finally {
        ui.busy(false);
      }
    };
    const intake = wireIntake(ui, accept, base);
    activeCard = intake;
    ui.continueBtn.addEventListener('click', async () => {
      const h = state.regrant.handle;
      let perm = 'denied';
      try { perm = await h.requestPermission({ mode: 'read' }); } catch (e) { perm = 'denied'; }
      if (perm === 'granted') accept(intake.fromHandle(h), h);
      else ui.message('The browser did not allow reading the folder. Choose it again, or play streamed.', 'err');
    });
    ui.forgetBtn.addEventListener('click', async () => {
      await forgetFolder();
      layerState.remembered = false;
      ui.forgetBtn.classList.add('hidden');
      ui.continueBtn.classList.add('hidden');
      ui.message('Forgotten. This site no longer has access to your folder.');
    });
    if (state.snapshot) intake.takeSnapshot(state.snapshot);
    // From a click (the page menu, the in-game button): while the click's user activation is
    // still live, open the browser's own picker (or its permission prompt) at once.
    else if (state.direct && userActive()) {
      if (state.regrant) ui.continueBtn.click();
      else if (browserKeepsFolders()) ui.chooseBtn.click();
    }
  });
}

/// One page load into the layer, keeping the session: the reason in sessionStorage (with the
/// character in the world, which wrath-early.js seats again), a cover, then the reload.
async function reloadIntoLayer(kind) {
  let char = null;
  try {
    const w = window.wenilla;
    if (w && typeof w.lua === 'function' && w.state && w.state.session && w.state.session.state === 'inworld') {
      const [n] = (await Promise.race([w.lua('return UnitName("player")', 1500), new Promise((r) => setTimeout(() => r([]), 1600))])) || [];
      if (typeof n === 'string' && /^[A-Za-zÀ-ɏ]{2,12}$/.test(n)) char = n;
    }
  } catch (_) {}
  session(false, { kind, at: Date.now(), char });
  cover('Opening the whole world…', kind === 'files'
    ? 'The page loads once more. This browser asks for the folder again then.'
    : 'The page loads once more with your game folder.');
  setTimeout(() => location.reload(), 300);
}

/// Open the folder picker (the page menu, the in-game "Use my game folder"). With a user gesture
/// still live, the browser's picker opens at once; otherwise the card with its Choose button.
export async function pickFolder(opts = {}) {
  const base = opts.base || import.meta.url;
  if (layerState.mode === 'own') return { ok: false, why: 'own' };
  if (!layerAllowed()) { toast('Your game folder works on the streamed page after you sign in.', { help: true }); return { ok: false, why: 'not here' }; }
  if (!supportedHere()) { toast('This browser cannot read a local game folder here.', { help: true }); return { ok: false, why: 'unsupported' }; }
  if (layerState.mounted) { toast(`Your game folder “${layerState.label}” is in use: the whole world is open.`); return { ok: true, already: true }; }
  if (activeCard) return { ok: false, why: 'open' };
  const rec = await kvGet('source');
  const regrant = rec && rec.kind === 'handle' && rec.handle ? rec : null;
  const r = await layerCard(opts, base, { regrant, direct: true });
  return { ok: !!r };
}

/// A drop the page's drop target found to be a game folder (wu-addons.js routes it here).
export async function acceptDrop(snap, opts = {}) {
  const base = opts.base || import.meta.url;
  if (activeCard) return activeCard.takeSnapshot(snap);
  if (layerState.mode === 'own') return null;
  if (layerState.mounted) { toast(`Your game folder “${layerState.label}” is already in use: the whole world is open.`); return null; }
  if (!layerAllowed() || !supportedHere()) {
    toast('Your game folder works on the streamed page after you sign in (or use "Play in the browser with my game folder" on the account page).', { help: true });
    return null;
  }
  return layerCard(opts, base, { snapshot: snap });
}

/// window.__wuOwnFiles.status(): what the page uses now (no paths, no names).
export function layerStatus() {
  return {
    mode: layerState.mode, phase: layerState.phase, mounted: layerState.mounted, label: layerState.label,
    build: layerState.build, locale: layerState.locale, archives: layerState.archives.length,
    counts: layerState.counts, realm: layerState.realm, remembered: layerState.remembered,
    keepsFolders: browserKeepsFolders(), dead: engine ? engine.dead : null, error: layerState.error,
    stats: engine ? { ...engine.stats } : null,
  };
}

if (typeof window !== 'undefined') {
  window.__wuOwnFiles = {
    status: layerStatus,
    pick: (o) => pickFolder(o),
    acceptDrop: (s, o) => acceptDrop(s, o),
    forget: async () => { await forgetFolder(); layerState.remembered = false; },
    allowed: () => layerAllowed(),
    _engine: () => engine,
    TIMING,
  };
}
