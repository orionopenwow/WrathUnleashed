// ownfiles-worker.js — the dedicated worker behind "Use my own game files".
//
// It owns the player's File references (or the FileSystemDirectoryHandle they came from), the
// opened 3.3.5a patch chain (archive tables parsed once) and an LRU of decompressed files, and
// answers the Data URL scheme for the page (`GET|HEAD /data/{name}`, `GET /data/__index`) —
// byte-for-byte what wenilla-host would answer, from the local MPQs, read with File.slice.
// Nothing is uploaded.
//
// Two answer paths:
//   * async (`fetch()` / async XHR in the page): a message reply, the body transferred.
//   * sync (the wasm client's blocking XMLHttpRequest, benilla-formats/src/web.rs): the page's
//     main thread is blocked in send(), spinning on a SharedArrayBuffer; this worker writes the
//     status, length and body into shared memory and flips the state word. The page never has to
//     run anything for a request to complete, so there is nothing to deadlock on.
//
// Classic worker (importScripts) so it runs everywhere module workers do not.
/* global WUMpq, WUChain */
importScripts('./mpq.js', './chain.js');

let server = null;
let mounting = null;
let ctl = null; // Int32Array over the control SharedArrayBuffer
let arena = null; // Uint8Array over the body SharedArrayBuffer
let parked = null; // a response too big for the arena, kept for the page's retry

const CT = ['application/octet-stream', 'image/x-blp', 'audio/mpeg', 'application/json'];
const CC = ['private, max-age=31536000, immutable', 'no-cache'];

async function mount(entries, label) {
  const listing = WUChain.listingFromFiles(entries, label);
  const chain = await WUChain.Chain.open(listing);
  server = new WUChain.DataServer(chain);
  parked = null;
  return { ok: true, archives: chain.order, locale: chain.locale, label: listing.label };
}

async function answer(method, path) {
  if (!server) return { status: 503, headers: {}, body: null };
  return server.handle(method, path, '/data/');
}

self.onmessage = async (event) => {
  const m = event.data || {};
  switch (m.type) {
    case 'mount':
    case 'mount-handle': {
      const work = (async () =>
        m.type === 'mount'
          ? mount(m.entries, m.label)
          : mount(await WUChain.entriesFromHandle(m.handle), m.label || m.handle.name))();
      mounting = work;
      try {
        const r = await work;
        if (m.warmIndex) server.index().catch(() => {}); // /data/__index ready before the client asks
        self.postMessage({ type: 'mounted', id: m.id, ...r });
      } catch (e) {
        self.postMessage({ type: 'mounted', id: m.id, ok: false, error: String((e && e.message) || e) });
      }
      return;
    }
    case 'shared':
      ctl = new Int32Array(m.ctl);
      if (m.arena) arena = new Uint8Array(m.arena);
      return;
    case 'sync': {
      let r;
      if (parked && parked.method === m.method && parked.path === m.path) {
        r = parked.r;
        parked = null;
      } else {
        try {
          if (mounting) await mounting.catch(() => {});
          r = await answer(m.method, m.path);
        } catch (e) {
          r = { status: 500, headers: {}, body: null, error: e };
        }
      }
      if (r.error) console.error('ownfiles:', m.path, r.error);
      const len = r.body ? r.body.length : 0;
      ctl[1] = r.status;
      ctl[2] = len;
      ctl[4] = Math.max(0, CT.indexOf(r.headers['content-type'] || 'application/octet-stream'));
      ctl[5] = r.headers['cache-control'] ? CC.indexOf(r.headers['cache-control']) : -1;
      if (len > arena.length) {
        parked = { method: m.method, path: m.path, r };
        ctl[3] = 2; // the page grows the arena and asks again
      } else {
        if (len) arena.set(r.body, 0);
        ctl[3] = 1;
      }
      Atomics.store(ctl, 0, 2);
      Atomics.notify(ctl, 0);
      return;
    }
    case 'async': {
      let r;
      try {
        if (mounting) await mounting.catch(() => {});
        r = await answer(m.method, m.path);
      } catch (e) {
        r = { status: 500, headers: {}, body: null, error: e };
      }
      if (r.error) console.error('ownfiles:', m.path, r.error);
      // Copy out of the LRU's buffer before transferring it.
      const body = r.body ? r.body.slice() : null;
      self.postMessage({ type: 'async', id: m.id, status: r.status, headers: r.headers, body }, body ? [body.buffer] : []);
      return;
    }
    case 'forget':
      server = null;
      parked = null;
      self.postMessage({ type: 'forgotten', id: m.id });
      return;
  }
};
