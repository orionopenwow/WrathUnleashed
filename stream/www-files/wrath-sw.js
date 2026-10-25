// wrath-sw.js — the WrathUnleashed page's service worker: keeps the world data a player has
// downloaded, so the next visit loads it from disk instead of the network, and keeps it through
// the browser's HTTP-cache churn. A port of Open Vanilla's 1.12 ow/sw.js, cut to what the 3.3.5a
// streamed page can use. Registered by sw-register.js at scope "/" (it is served from the site
// root, so no Service-Worker-Allowed header is needed). Off unless switched on (sw-register.js).
//
// What it touches:
//   /data/<name>        GET fetches of the client's ASYNC reads (benilla-assets web_read.rs and its
//                       asset reader: terrain, models, world textures, sounds), cache-first in Cache
//                       Storage ("wu-data-v1"), for names under the world-data folders below.
//                       wu-play serves /data immutable (wenilla-host data.rs).
//   everything else     not touched: the page, the scripts, the wasm, /data/__index, /data/__tier/*,
//                       /ws, /__env.js, /__gate, and every name under Interface\ or DBFilesClient\
//                       (a new slice or a Forever UI update can change those under the same name).
//
// Not reachable from here, by design of the browser: the client's SYNCHRONOUS reads (the chain's
// sync XMLHttpRequest, benilla-formats web.rs). Chromium never routes a sync XHR through a service
// worker; those stay with the HTTP cache (boot.js warms it) and with "Download this section"
// (sections.js keeps whole tiers in Cache Storage and answers them in the page).
//
// Kill switches: ?nosw=1 on the page (that browser), or {"sw": "off"} in /sw-config.json
// (everyone: the worker unregisters itself and deletes its cache on its next check).

const CACHE = 'wu-data-v1';
const CONFIG_URL = new URL('./sw-config.json', self.location).href;
const CHECK_MS = 60_000;
// world data that never changes under its name in a slice (lower case, '/' separators)
const KEEP = ['world/', 'creature/', 'character/', 'item/', 'spells/', 'sound/', 'dungeons/', 'environments/', 'tileset/', 'textures/', 'xtextures/', 'particles/'];
const TRIM_HIGH = 0.8, TRIM_LOW = 0.7;   // fractions of the origin's quota

let disabled = false;
let checked = 0;
let puts = 0;
const inflight = new Map();

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith('wu-data-v') && k !== CACHE) await caches.delete(k);
  await self.clients.claim();
  await check(true);
})()));

self.addEventListener('message', (e) => {
  const m = e.data || {};
  if (m.type === 'disable') { disabled = true; e.waitUntil(caches.delete(CACHE)); }
  else if (m.type === 'clear') e.waitUntil(caches.delete(CACHE));
  else if (m.type === 'status') e.waitUntil(status().then((s) => e.source?.postMessage({ type: 'status', status: s })));
});

/** The archive name a /data URL asks for, lower case with '/' separators; null when not ours. */
function keptName(pathname) {
  if (!pathname.startsWith('/data/') || pathname.startsWith('/data/__')) return null;
  let n;
  try { n = decodeURIComponent(pathname.slice(6)); } catch { return null; }
  n = n.replace(/\\/g, '/').toLowerCase();
  return KEEP.some((p) => n.startsWith(p)) ? n : null;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (disabled || req.method !== 'GET' || req.headers.has('range')) return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !keptName(url.pathname)) return;
  e.respondWith(answer(req, url));
});

async function answer(req, url) {
  check(false);
  const cache = await caches.open(CACHE);
  const hit = await cache.match(url.href, { ignoreVary: true });
  if (hit) return hit;
  let p = inflight.get(url.href);
  if (!p) {
    p = fetch(req).then((res) => {
      if (res.ok && res.status === 200 && res.type === 'basic' && !(res.headers.get('content-type') || '').startsWith('text/html')) {
        cache.put(url.href, res.clone()).then(() => { if (++puts % 200 === 0) trim().catch(() => {}); }).catch(() => {});
      }
      return res;
    });
    inflight.set(url.href, p);
    p.finally(() => inflight.delete(url.href)).catch(() => {});
  }
  return p.then((res) => res.clone());
}

async function check(force) {
  if (!force && Date.now() - checked < CHECK_MS) return;
  checked = Date.now();
  try {
    const r = await fetch(CONFIG_URL, { cache: 'no-store', credentials: 'same-origin' });
    const j = r.ok ? await r.json() : {};
    if (j && j.sw === 'off') {
      disabled = true;
      await caches.delete(CACHE);
      await self.registration.unregister();
    }
  } catch { /* no file, offline: keep going */ }
}

// No size cap: past 80% of the origin's quota the oldest-stored files go until it is under 70%.
async function trim() {
  if (!navigator.storage?.estimate) return;
  for (let round = 0; round < 8; round++) {
    const { usage = 0, quota = 0 } = await navigator.storage.estimate();
    if (!quota || usage < quota * (round ? TRIM_LOW : TRIM_HIGH)) return;
    const cache = await caches.open(CACHE);
    const keys = await cache.keys();
    if (!keys.length) return;
    for (const k of keys.slice(0, Math.max(1, Math.ceil(keys.length * 0.1)))) await cache.delete(k);
  }
}

async function status() {
  const out = { cache: CACHE, entries: (await (await caches.open(CACHE)).keys()).length, disabled };
  if (navigator.storage?.estimate) {
    const { usage, quota } = await navigator.storage.estimate();
    out.usageMB = Math.round((usage || 0) / 1048576);
    out.quotaMB = Math.round((quota || 0) / 1048576);
  }
  return out;
}
