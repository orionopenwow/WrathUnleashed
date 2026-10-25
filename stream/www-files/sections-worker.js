// sections-worker.js — answers the page's blocking reads of downloaded sections (sections.js)
// from Cache Storage. The page's main thread is spinning in a sync XMLHttpRequest send(): this
// worker copies the cached body into the shared arena and flips the state word, so the page never
// has to run anything for the read to complete.
//
// ctl (Int32Array over a SharedArrayBuffer): [0] state (0 waiting, 1 answered), [1] status (200,
// 404 = not in the cache, -2 = bigger than the arena: the page grows it and asks again, the body
// is kept for that retry), [2] body length.

let ctl = null;
let arena = null;
let cacheName = 'wu-sections-v1';
let cache = null;
let parked = null; // { path, bytes } too big for the arena

async function open() {
  if (!cache) cache = await caches.open(cacheName);
  return cache;
}

function answer(status, len) {
  Atomics.store(ctl, 1, status);
  Atomics.store(ctl, 2, len);
  Atomics.store(ctl, 0, 1);
  Atomics.notify(ctl, 0);
}

self.onmessage = async (e) => {
  const m = e.data || {};
  if (m.type === 'shared') {
    ctl = new Int32Array(m.ctl);
    arena = new Uint8Array(m.arena);
    if (m.cache) cacheName = m.cache;
    return;
  }
  if (m.type === 'ping') {
    self.postMessage({ type: 'ready' });
    return;
  }
  if (m.type !== 'get' || !ctl) return;
  try {
    let bytes;
    if (parked && parked.path === m.path) {
      bytes = parked.bytes;
      parked = null;
    } else {
      const r = await (await open()).match(m.path);
      if (!r) return answer(404, 0);
      bytes = new Uint8Array(await r.arrayBuffer());
    }
    if (bytes.length > arena.length) {
      parked = { path: m.path, bytes };
      return answer(-2, bytes.length);
    }
    if (m.method !== 'HEAD') arena.set(bytes, 0);
    answer(200, bytes.length);
  } catch (err) {
    answer(404, 0);
  }
};
