// sections.js — "Download this section" for the streamed client (WrathUnleashed mini slice).
//
// The streamed site serves only a slice of the game, tier by tier (slices/mini.json). Each tier's
// file list is at /data/__tier/<n>.txt (and all of them at /data/__tier/index.json), written by
// `wenilla-host --export` and gated like /data. This module lets a player download whole tiers
// ahead of time, keeps them in the browser's Cache Storage ("wu-sections-v1", persistent, counted
// against the site's quota, removable), and answers the client's reads of those files from there:
//
//   * The wasm client reads /data with *synchronous* XMLHttpRequest (benilla-formats web.rs), and
//     Chromium does not route sync XHR through service workers, so a service worker cannot serve
//     them. Instead (the same design as ownfiles.js) the page swaps XMLHttpRequest for a subclass
//     that, for a downloaded name only, posts the request to sections-worker.js and spins on a
//     SharedArrayBuffer until the worker has copied the cached body in (the page is cross-origin
//     isolated: wenilla-host sends COOP/COEP). Everything else (names not downloaded, async XHR)
//     goes to the real XMLHttpRequest and the network/HTTP cache exactly as before.
//   * fetch() of a downloaded /data name (boot.js's prefetch) is answered from the cache too.
//
// Without the tier index (own-files mode, an old slice, a plain wenilla-host), without Cache
// Storage or without cross-origin isolation, nothing is installed and the page behaves as before.
//
// Page contract: `installSections()` resolves once the shim (if any) is in place; call it before
// the client starts (index.html chains it after ensureDataSource()). `mountSectionsUi(button)`
// wires the page's "sections" button to the panel.

const CACHE = 'wu-sections-v1';
const META = '/__sections/tier/';   // synthetic cache keys: what each tier download finished
const INDEX_URL = '/data/__tier/index.json';
const CONCURRENCY = 6;
const ARENA_INITIAL = 8 * 1024 * 1024;
const SYNC_TIMEOUT_MS = 60000;

const state = {
  installed: false,
  have: new Set(),       // pathnames ('/data/<encoded name>') in the cache
  worker: null,
  ctl: null,             // Int32Array over the control SharedArrayBuffer: [state, status, length]
  ctlSab: null,
  arenaSab: null,
  index: null,           // [{tier, name, files, bytes}]
  running: null,         // the tier being downloaded
  abort: false,
};

function canRun() {
  return typeof caches !== 'undefined' && typeof SharedArrayBuffer !== 'undefined' &&
    self.crossOriginIsolated === true && typeof Worker !== 'undefined' && typeof Atomics !== 'undefined';
}

function dataPath(url) {
  let u;
  try { u = new URL(String(url), location.href); } catch (_) { return null; }
  if (u.origin !== location.origin || !u.pathname.startsWith('/data/') || u.pathname.startsWith('/data/__')) return null;
  return u.pathname;
}

/// '/data/' + encodeURIComponent(name), the URL the client and boot.js use.
export function urlOf(name) {
  return '/data/' + encodeURIComponent(name);
}

async function loadIndex() {
  try {
    const r = await fetch(INDEX_URL, { cache: 'no-cache' });
    if (!r.ok) return null;
    const v = await r.json();
    return Array.isArray(v) ? v.filter((t) => t && Number.isInteger(t.tier)) : null;
  } catch (_) {
    return null;
  }
}

async function loadHave() {
  const c = await caches.open(CACHE);
  const keys = await c.keys();
  const have = new Set();
  for (const req of keys) {
    const p = new URL(req.url).pathname;
    if (p.startsWith('/data/')) have.add(p);
  }
  return have;
}

function startWorker() {
  const w = new Worker(new URL('./sections-worker.js', import.meta.url).href);
  state.ctlSab = new SharedArrayBuffer(16);
  state.ctl = new Int32Array(state.ctlSab);
  state.arenaSab = new SharedArrayBuffer(ARENA_INITIAL);
  w.postMessage({ type: 'shared', ctl: state.ctlSab, arena: state.arenaSab, cache: CACHE });
  state.worker = w;
  return new Promise((resolve) => {
    const t = setTimeout(() => resolve(false), 10000);
    w.onmessage = (e) => {
      if (e.data && e.data.type === 'ready') { clearTimeout(t); resolve(true); }
    };
    w.onerror = () => { clearTimeout(t); resolve(false); };
    w.postMessage({ type: 'ping' });
  });
}

/// A blocking read of one downloaded file through the worker: {status, body} or null (not in the
/// cache after all, timeout: the caller falls back to the network).
function syncRead(path, method) {
  const ctl = state.ctl;
  for (let attempt = 0; attempt < 3; attempt++) {
    Atomics.store(ctl, 0, 0);
    state.worker.postMessage({ type: 'get', path, method });
    const t0 = performance.now();
    while (Atomics.load(ctl, 0) === 0) {
      if (performance.now() - t0 > SYNC_TIMEOUT_MS) return null;
    }
    const status = Atomics.load(ctl, 1);
    const len = Atomics.load(ctl, 2);
    if (status === -2) {
      // Bigger than the arena: grow it and ask again (the worker kept the body).
      let size = state.arenaSab.byteLength;
      while (size < len) size *= 2;
      state.arenaSab = new SharedArrayBuffer(size);
      state.worker.postMessage({ type: 'shared', ctl: state.ctlSab, arena: state.arenaSab, cache: CACHE });
      continue;
    }
    if (status !== 200) return null;
    const body = new Uint8Array(len);
    if (method !== 'HEAD') body.set(new Uint8Array(state.arenaSab, 0, len));
    return { status: 200, body };
  }
  return null;
}

const xud = (() => { try { return new TextDecoder('x-user-defined'); } catch (_) { return null; } })();

function contentType(path) {
  const p = path.toLowerCase();
  if (p.endsWith('.blp')) return 'image/x-blp';
  if (p.endsWith('.mp3')) return 'audio/mpeg';
  return 'application/octet-stream';
}

function installShim() {
  const RealXHR = window.XMLHttpRequest;
  const realFetch = window.fetch.bind(window);

  class SectionsXHR extends RealXHR {
    open(method, url, async, ...rest) {
      const path = dataPath(url);
      const m = String(method).toUpperCase();
      const sync = async === false;
      this._sec = null;
      if (path && sync && (m === 'GET' || m === 'HEAD') && state.have.has(path)) {
        this._sec = { method: m, path, mime: null, readyState: 1, status: 0, body: null, url, rest };
        return;
      }
      return arguments.length < 3 ? super.open(method, url) : super.open(method, url, async, ...rest);
    }
    overrideMimeType(mime) {
      if (this._sec) this._sec.mime = String(mime);
      return this._sec ? undefined : super.overrideMimeType(mime);
    }
    setRequestHeader(k, v) {
      if (this._sec) return;
      return super.setRequestHeader(k, v);
    }
    send(body) {
      const o = this._sec;
      if (!o) return super.send(body);
      const r = syncRead(o.path, o.method);
      if (!r) {
        // Not served from the cache after all: the real request, as if nothing happened.
        state.have.delete(o.path);
        this._sec = null;
        super.open(o.method, o.url, false);
        if (o.mime) super.overrideMimeType(o.mime);
        return super.send(body);
      }
      o.status = r.status;
      o.body = r.body;
      o.readyState = 4;
      try { this.dispatchEvent(new Event('readystatechange')); this.dispatchEvent(new Event('load')); this.dispatchEvent(new Event('loadend')); } catch (_) {}
    }
    get readyState() { return this._sec ? this._sec.readyState : super.readyState; }
    get status() { return this._sec ? this._sec.status : super.status; }
    get statusText() { return this._sec ? (this._sec.readyState === 4 ? 'OK' : '') : super.statusText; }
    get responseURL() { return this._sec ? new URL(this._sec.url, location.href).href : super.responseURL; }
    get responseText() {
      const o = this._sec;
      if (!o) return super.responseText;
      if (!o.body || o.readyState !== 4) return '';
      if (o.mime && /x-user-defined/i.test(o.mime)) {
        if (xud) return xud.decode(o.body);
        let s = '';
        for (let i = 0; i < o.body.length; i += 32768) {
          s += String.fromCharCode.apply(null, Array.from(o.body.subarray(i, i + 32768), (b) => (b < 0x80 ? b : 0xf700 + b)));
        }
        return s;
      }
      return new TextDecoder().decode(o.body);
    }
    get response() {
      if (!this._sec) return super.response;
      return this.responseText;   // a sync XHR's responseType is always ''
    }
    getResponseHeader(name) {
      if (!this._sec) return super.getResponseHeader(name);
      if (this._sec.readyState !== 4) return null;
      const n = String(name).toLowerCase();
      if (n === 'content-type') return contentType(this._sec.path);
      if (n === 'content-length') return String(this._sec.body.length);
      if (n === 'cache-control') return 'private, max-age=31536000, immutable';
      return null;
    }
    getAllResponseHeaders() {
      if (!this._sec) return super.getAllResponseHeaders();
      if (this._sec.readyState !== 4) return '';
      return `content-type: ${contentType(this._sec.path)}\r\ncontent-length: ${this._sec.body.length}\r\n`;
    }
  }
  window.XMLHttpRequest = SectionsXHR;

  window.fetch = function fetch(input, init) {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input && input.url;
    const path = url ? dataPath(url) : null;
    const method = String((init && init.method) || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (!path || method !== 'GET' || !state.have.has(path)) return realFetch(input, init);
    return caches.open(CACHE)
      .then((c) => c.match(path))
      .then((r) => r || realFetch(input, init), () => realFetch(input, init));
  };
  state.installed = true;
}

/// Install the cache-backed reads when this origin streams a slice with tier lists. Never throws.
export async function installSections() {
  try {
    if (state.installed || window.__ownfiles || !canRun()) return { installed: false };
    const index = await loadIndex();
    if (!index) return { installed: false };
    state.index = index;
    state.have = await loadHave();
    if (!(await startWorker())) return { installed: false };
    installShim();
    return { installed: true, files: state.have.size };
  } catch (e) {
    console.warn('sections:', e);
    return { installed: false };
  }
}

// --- downloading -------------------------------------------------------------------------------

/// The names and sizes of a tier: lines of `<bytes>\t<name>` after a `# tier` header.
export function parseTierList(text) {
  const out = [];
  for (const line of String(text).split('\n')) {
    if (!line || line.startsWith('#')) continue;
    const tab = line.indexOf('\t');
    if (tab < 0) continue;
    const bytes = Number(line.slice(0, tab));
    const name = line.slice(tab + 1).replace(/\r$/, '');
    if (name && Number.isFinite(bytes)) out.push({ name, bytes });
  }
  return out;
}

async function tierMeta(c, n) {
  const r = await c.match(META + n);
  if (!r) return null;
  try { return await r.json(); } catch (_) { return null; }
}

/// What is downloaded per tier: {tier: {files, bytes, done}}.
export async function sectionsStatus() {
  const out = {};
  if (typeof caches === 'undefined') return out;
  const c = await caches.open(CACHE);
  for (const t of state.index || []) {
    const m = await tierMeta(c, t.tier);
    if (m) out[t.tier] = m;
  }
  return out;
}

/// Download one tier into the cache. onProgress({doneFiles, files, doneBytes, bytes}).
export async function downloadTier(n, onProgress = () => {}) {
  if (state.running !== null) throw new Error('a download is already running');
  state.running = n;
  state.abort = false;
  try {
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
    const r = await fetch(`/data/__tier/${n}.txt`, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`the server has no file list for this section (HTTP ${r.status})`);
    const list = parseTierList(await r.text());
    const total = list.reduce((a, f) => a + f.bytes, 0);
    if (navigator.storage && navigator.storage.estimate) {
      const est = await navigator.storage.estimate().catch(() => null);
      if (est && est.quota && est.usage !== undefined && est.quota - est.usage < total * 1.05) {
        throw new Error(`not enough browser storage: ${mb(total)} MB needed, ${mb(est.quota - est.usage)} MB free`);
      }
    }
    const c = await caches.open(CACHE);
    const queue = list.slice();
    let doneFiles = 0, doneBytes = 0, failed = 0;
    const report = () => onProgress({ doneFiles, files: list.length, doneBytes, bytes: total, failed });
    report();
    async function worker() {
      for (;;) {
        if (state.abort) return;
        const f = queue.shift();
        if (!f) return;
        const path = urlOf(f.name);
        if (!state.have.has(path)) {
          try {
            const resp = await fetch(path);
            if (resp.ok) {
              await c.put(path, resp);
              state.have.add(path);
            } else failed++;
          } catch (_) {
            failed++;
          }
        }
        doneFiles++;
        doneBytes += f.bytes;
        report();
      }
    }
    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    const done = !state.abort && failed === 0;
    await c.put(META + n, new Response(JSON.stringify({ files: list.length, bytes: total, done, failed, at: Date.now() }),
      { headers: { 'content-type': 'application/json' } }));
    if (state.abort) throw new Error('stopped');
    return { files: list.length, bytes: total, failed };
  } finally {
    state.running = null;
  }
}

export function stopDownload() { state.abort = true; }

/// Remove every downloaded section: the cache goes, reads go back to the network.
export async function removeSections() {
  state.abort = true;
  state.have.clear();
  if (typeof caches !== 'undefined') await caches.delete(CACHE);
}

function mb(b) { return (b / (1024 * 1024)).toFixed(b < 10 * 1024 * 1024 ? 1 : 0); }

// --- the panel ---------------------------------------------------------------------------------

const CSS = `
#wu-sections{position:fixed;top:2.2rem;right:.5rem;z-index:30;width:min(25rem,calc(100vw - 1rem));max-height:calc(100vh - 3rem);
  overflow:auto;background:#12151f;color:#e9e4d4;border:1px solid #3a3322;border-radius:8px;padding:12px 14px;
  font:13px/1.45 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.6);box-sizing:border-box}
#wu-sections h2{margin:0 0 4px;font-size:15px;color:#f2c96b}
#wu-sections .fine{color:#8a8473;font-size:12px;margin:0 0 8px}
#wu-sections .row{display:flex;align-items:center;gap:8px;padding:5px 0;border-top:1px solid #222838}
#wu-sections .name{flex:1;min-width:0}
#wu-sections .size{color:#a59f8f;font-variant-numeric:tabular-nums;white-space:nowrap}
#wu-sections button{background:#2a2f3e;color:#e9e4d4;border:0;border-radius:5px;padding:4px 9px;font:inherit;cursor:pointer}
#wu-sections button.go{background:#f2c96b;color:#1a1408;font-weight:600}
#wu-sections button:disabled{opacity:.5;cursor:default}
#wu-sections .ok{color:#8fd18f;white-space:nowrap}
#wu-sections .bar{height:6px;background:#222;border-radius:3px;overflow:hidden;margin:6px 0 2px}
#wu-sections .bar>i{display:block;height:100%;width:0;background:#c9a227}
#wu-sections .err{color:#ff8f8f}
#wu-sections .foot{display:flex;justify-content:space-between;align-items:center;margin-top:10px;gap:8px;flex-wrap:wrap}
`;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k);
  return e;
}

/// Show the page's sections button (hidden until a tier index exists) and open the panel on click.
export function mountSectionsUi(button) {
  if (!button) return;
  const show = () => { button.hidden = false; };
  if (state.index) show();
  else loadIndex().then((i) => { if (i && i.length) { state.index = i; show(); } });
  let panel = null;
  button.addEventListener('click', async () => {
    if (panel) { panel.remove(); panel = null; return; }
    panel = await renderPanel(() => { panel && panel.remove(); panel = null; });
    document.body.append(panel);
  });
}

async function renderPanel(close) {
  if (!document.getElementById('wu-sections-css')) {
    document.head.append(el('style', { id: 'wu-sections-css' }, CSS));
  }
  const root = el('div', { id: 'wu-sections', role: 'dialog', 'aria-label': 'Download sections' });
  const status = await sectionsStatus().catch(() => ({}));
  const usage = el('span', { class: 'fine' });
  const refreshUsage = () => {
    if (navigator.storage && navigator.storage.estimate) {
      navigator.storage.estimate().then((e) => {
        usage.textContent = `browser storage in use: ${mb(e.usage || 0)} MB of ${mb(e.quota || 0)} MB`;
      }).catch(() => {});
    }
  };
  refreshUsage();
  const msg = el('div', { class: 'fine' });
  const bar = el('div', { class: 'bar', hidden: '' }, el('i'));
  root.append(
    el('h2', {}, 'Download this section'),
    el('p', { class: 'fine' }, 'Download a whole part of the game now, so it loads instantly later and costs no ' +
      'more data. It stays in this browser until you remove it.'),
  );
  const buttons = [];
  for (const t of state.index || []) {
    const m = status[t.tier];
    const mark = m && m.done ? el('span', { class: 'ok' }, '✓ downloaded') : m ? el('span', { class: 'size' }, 'partly') : '';
    const b = el('button', { class: m && m.done ? '' : 'go', type: 'button' }, m && m.done ? 'Again' : 'Download');
    buttons.push(b);
    b.addEventListener('click', async () => {
      buttons.forEach((x) => (x.disabled = true));
      bar.hidden = false;
      msg.className = 'fine';
      const fill = bar.firstChild;
      try {
        const r = await downloadTier(t.tier, (p) => {
          fill.style.width = (p.bytes ? Math.floor((p.doneBytes / p.bytes) * 100) : 100) + '%';
          msg.textContent = `${t.name || 'tier ' + t.tier}: ${mb(p.doneBytes)} of ${mb(p.bytes)} MB, ` +
            `${p.doneFiles} of ${p.files} files${p.failed ? `, ${p.failed} failed` : ''}`;
        });
        msg.textContent = `${t.name || 'tier ' + t.tier}: downloaded, ${mb(r.bytes)} MB` + (r.failed ? ` (${r.failed} files failed: try again)` : '');
        if (typeof mark !== 'string') mark.textContent = r.failed ? 'partly' : '✓ downloaded';
        else b.before(el('span', { class: r.failed ? 'size' : 'ok' }, r.failed ? 'partly' : '✓ downloaded'));
        if (!r.failed) { b.textContent = 'Again'; b.className = ''; }
      } catch (e) {
        msg.className = 'err';
        msg.textContent = String((e && e.message) || e);
      } finally {
        buttons.forEach((x) => (x.disabled = false));
        refreshUsage();
      }
    });
    root.append(el('div', { class: 'row' },
      el('span', { class: 'name' }, t.name || `tier ${t.tier}`),
      el('span', { class: 'size' }, `${mb(t.bytes)} MB`),
      mark, b));
  }
  if (!(state.index || []).length) root.append(el('p', { class: 'fine' }, 'This server has no sections to download.'));
  root.append(bar, msg);
  const remove = el('button', { type: 'button' }, 'Remove downloaded sections');
  remove.addEventListener('click', async () => {
    await removeSections();
    msg.className = 'fine';
    msg.textContent = 'Removed. The game loads its files from the server again.';
    root.querySelectorAll('.ok, .row .size + .size').forEach((x) => x.remove());
    buttons.forEach((x) => { x.textContent = 'Download'; x.className = 'go'; });
    refreshUsage();
  });
  const stop = el('button', { type: 'button' }, 'Stop');
  stop.addEventListener('click', stopDownload);
  root.append(el('div', { class: 'foot' }, usage, el('span', {}, stop, ' ', remove, ' ',
    el('button', { type: 'button', onclick: close }, 'Close'))));
  return root;
}

export const _test = { state, dataPath, parseTierList };
