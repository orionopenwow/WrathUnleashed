// ownfiles-worker.js — the dedicated worker behind "Use my own game files" and the game-folder layer.
//
// It owns the player's File references (or the FileSystemDirectoryHandle they came from), the
// opened 3.3.5a patch chain (archive tables parsed once) and an LRU of decompressed files, and
// answers the Data URL scheme for the page (`GET|HEAD /data/{name}`, `GET /data/__index`) —
// byte-for-byte what wenilla-host would answer, from the local MPQs, read with File.slice
// (only the bytes a read needs ever leave the disk; no archive is copied whole). Nothing is uploaded.
//
// Two modes:
//   * own (the "Play with my own game files" page): every /data name comes from the folder.
//   * layer (a folder dropped on the streamed page): WUChain.LayerServer. A name in the streamed
//     slice is answered `pass` (the page sends it to the server, through the retries and the
//     downloaded sections); the folder answers every other name; /data/__index is the union.
//
// Two answer paths:
//   * async (`fetch()` / async XHR in the page): a message reply, the body transferred.
//   * sync (the wasm client's blocking XMLHttpRequest, benilla-formats/src/web.rs): the page's
//     main thread is blocked in send(), spinning on a SharedArrayBuffer; this worker writes the
//     status, length and body into shared memory and flips the state word. The page never has to
//     run anything for a request to complete, so there is nothing to deadlock on.
// ctl (Int32Array over 32 bytes): [0] state (1 asked, 2 answered), [1] status, [2] length,
// [3] flags (1 body in the arena, 2 grow the arena and ask again, 3 pass: the server answers),
// [4] content type, [5] cache-control, [6] heartbeat (counts up while this worker is alive: the
// page tells a dead worker from a slow one by it).
//
// Classic worker (importScripts) so it runs everywhere module workers do not.
/* global WUMpq, WUChain */
importScripts('./mpq.js', './chain.js');

let server = null;
let mounting = null;
let ctl = null; // Int32Array over the control SharedArrayBuffer
let arena = null; // Uint8Array over the body SharedArrayBuffer
let parked = null; // a response too big for the arena, kept for the page's retry
let beat = 0;

const CT = ['application/octet-stream', 'image/x-blp', 'audio/mpeg', 'application/json'];
const CC = ['private, max-age=31536000, immutable', 'no-cache'];

async function mount(entries, label, opts) {
  const listing = WUChain.listingFromFiles(entries, label, { locale: opts.locale });
  const chain = await WUChain.Chain.open(listing);
  parked = null;
  if (opts.layer) {
    server = new WUChain.LayerServer(chain, opts.slice || null);
    const index = await server.index(); // the union, ready before the client asks
    return { ok: true, archives: chain.order, locale: chain.locale, label: listing.label, layer: true,
             counts: server.counts, index: index.slice().buffer };
  }
  server = new WUChain.DataServer(chain);
  return { ok: true, archives: chain.order, locale: chain.locale, label: listing.label };
}

async function answer(method, path, own) {
  if (!server) return { status: 503, headers: {}, body: null };
  if (server instanceof WUChain.LayerServer) return server.handle(method, path, { own });
  return server.handle(method, path, '/data/');
}

function startBeat() {
  if (beat) return;
  beat = setInterval(() => { if (ctl) Atomics.add(ctl, 6, 1); }, 200);
}

self.onmessage = async (event) => {
  const m = event.data || {};
  switch (m.type) {
    case 'mount':
    case 'mount-handle': {
      const opts = { layer: !!m.layer, slice: m.slice || null, locale: m.locale || null };
      const work = (async () =>
        m.type === 'mount'
          ? mount(m.entries, m.label, opts)
          : mount(await WUChain.entriesFromHandle(m.handle), m.label || m.handle.name, opts))();
      mounting = work;
      try {
        const r = await work;
        if (m.warmIndex && !opts.layer) server.index().catch(() => {}); // /data/__index ready before the client asks
        self.postMessage({ type: 'mounted', id: m.id, ...r }, r.index ? [r.index] : []);
      } catch (e) {
        self.postMessage({ type: 'mounted', id: m.id, ok: false, error: String((e && e.message) || e) });
      }
      return;
    }
    case 'shared':
      ctl = new Int32Array(m.ctl);
      if (m.arena) arena = new Uint8Array(m.arena);
      startBeat();
      return;
    case 'ping':
      self.postMessage({ type: 'pong', id: m.id, mounted: !!server });
      return;
    case 'sync': {
      let r;
      if (parked && parked.method === m.method && parked.path === m.path) {
        r = parked.r;
        parked = null;
      } else {
        try {
          if (mounting) await mounting.catch(() => {});
          r = await answer(m.method, m.path, m.own);
        } catch (e) {
          r = { status: 500, headers: {}, body: null, error: e };
        }
      }
      if (r.error) console.error('ownfiles:', m.path, r.error);
      if (r.pass) {
        ctl[1] = 0; ctl[2] = 0; ctl[3] = 3;
        Atomics.store(ctl, 0, 2);
        Atomics.notify(ctl, 0);
        return;
      }
      const len = r.body ? r.body.length : 0;
      ctl[1] = r.status;
      ctl[2] = len;
      ctl[4] = Math.max(0, CT.indexOf((r.headers && r.headers['content-type']) || 'application/octet-stream'));
      ctl[5] = r.headers && r.headers['cache-control'] ? CC.indexOf(r.headers['cache-control']) : -1;
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
        r = await answer(m.method, m.path, m.own);
      } catch (e) {
        r = { status: 500, headers: {}, body: null, error: e };
      }
      if (r.error) console.error('ownfiles:', m.path, r.error);
      if (r.pass) {
        self.postMessage({ type: 'async', id: m.id, pass: true });
        return;
      }
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
