// ahead.js — fetch the terrain ahead of the player on the WrathUnleashed page, so the client's
// own request for it is answered from the browser's HTTP cache instead of the network.
//
// A cut-down port of Open Vanilla's 1.12 ahead.js. It needs the page bridge's snapshots (self.pos,
// self.facing, self.moving, map.id: web/README.md "The contract"); without a bridge in the client
// it never starts. What it does, from the snapshot at most once a second:
//
//   * moving: the terrain tiles (ADTs) along the facing direction, ~25 s ahead at the current
//     speed (300..2000 yd), nearest first, and the 3x3 tiles round the player once;
//   * the URL is the one the 3.3.5a client's asset reader asks for: '/data/' + the asset path
//     "World/Maps/<dir>/<dir>_<x>_<y>.adt" percent-encoded as one component ('/' is %2F;
//     benilla-world terrain_stream.rs, benilla-formats web.rs encode_name), <dir> as Map.dbc spells
//     it, tile x/y as benilla-wdt world_to_tile;
//   * ?ahead=full also takes each tile's textures (MTEX) and models (MMDX, MWMO) in 1.12's
//     lower-case spelling. Off by default: this client's spelling for those is not checked yet,
//     and a different spelling is a download the client never uses.
//
// Only network work: nothing is decoded but the ADT's name chunks. 3 at a time, 100 MB per
// session at most; off on Save-Data or 2g/3g, and with ?noahead=1. window.owAhead for owdiag.

export const TILE = 533.33333;
const CONCURRENCY = 3;
const BUDGET = 100 * 1024 * 1024;
const LOOK_SECS = 25;
const LOOK_MIN = 300, LOOK_MAX = 2000;

/** benilla-wdt world_to_tile: world (x, y) -> ADT (tile_x, tile_y). */
export function tileOf(x, y) {
  const off = 32 * TILE;
  const tx = Math.min(63, Math.max(0, Math.floor((off - y) / TILE)));
  const ty = Math.min(63, Math.max(0, Math.floor((off - x) / TILE)));
  return [tx, ty];
}

/** The client's URL for an ADT. */
export function adtUrl(dir, tx, ty) {
  return '/data/' + encodeURIComponent(`World/Maps/${dir}/${dir}_${tx}_${ty}.adt`);
}

/** Map.dbc (WDBC): id -> Directory (field 1, a string offset). */
export function parseMapDirs(buf) {
  const v = new DataView(buf);
  const magic = String.fromCharCode(...new Uint8Array(buf, 0, 4));
  if (magic !== 'WDBC') throw new Error('not WDBC');
  const n = v.getUint32(4, true), size = v.getUint32(12, true);
  const strings = 20 + n * size;
  const bytes = new Uint8Array(buf);
  const str = (o) => { let e = strings + o; while (e < bytes.length && bytes[e]) e++; return new TextDecoder().decode(bytes.subarray(strings + o, e)); };
  const out = new Map();
  for (let i = 0; i < n; i++) {
    const r = 20 + i * size;
    out.set(v.getUint32(r, true), str(v.getUint32(r + 4, true)));
  }
  return out;
}

/** The tiles a straight line from (x, y) along `facing` crosses, `dist` yards out, nearest first. */
export function tilesAhead(x, y, facing, dist) {
  const out = [], seen = new Set();
  const step = TILE / 4;
  for (let d = 0; d <= dist; d += step) {
    const [tx, ty] = tileOf(x + Math.cos(facing) * d, y + Math.sin(facing) * d);
    const k = tx + '_' + ty;
    if (!seen.has(k)) { seen.add(k); out.push([tx, ty]); }
  }
  return out;
}

/** Chunks of an IFF-style file (ADT): id as written in the file's byte order ("XETM") -> [offset, size]. */
function chunks(buf) {
  const v = new DataView(buf), out = {};
  for (let o = 0; o + 8 <= buf.byteLength;) {
    const id = String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
    const size = v.getUint32(o + 4, true);
    if (!(id in out)) out[id] = [o + 8, size];
    o += 8 + size;
    if (id === 'KNCM') break;          // the map chunks start: the name lists are all before them
  }
  return out;
}
const names = (buf, [o, size]) => new TextDecoder().decode(new Uint8Array(buf, o, size)).split('\0').filter(Boolean);
const lowerUrl = (n) => '/data/' + encodeURIComponent(n.replace(/\\/g, '/').toLowerCase());

export function installAhead(wenilla) {
  const q = new URLSearchParams(location.search);
  const st = (window.owAhead = { state: 'off', tiles: 0, files: 0, bytes: 0, last: '' });
  const c = navigator.connection;
  if (q.get('noahead') === '1') { st.state = 'off: ?noahead=1'; return st; }
  if (c && (c.saveData || ['slow-2g', '2g', '3g'].includes(c.effectiveType))) { st.state = 'off: slow connection'; return st; }
  if (!wenilla?.on) { st.state = 'off: no bridge'; return st; }
  const full = q.get('ahead') === 'full';
  st.state = 'waiting for the bridge';
  let dirs = null, dirsP = null;
  const queue = [], queued = new Set();
  let running = 0, lastAt = 0, around = null;
  const loadDirs = () => (dirsP ??= fetch('/data/' + encodeURIComponent('DBFilesClient\\Map.dbc'))
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error('Map.dbc ' + r.status))))
    .then((b) => { dirs = parseMapDirs(b); })
    .catch((e) => { st.state = 'off: ' + e.message; }));
  const want = (url, kind) => {
    if (queued.has(url) || st.bytes >= BUDGET) return;
    queued.add(url);
    queue.push({ url, kind });
    pump();
  };
  function pump() {
    while (running < CONCURRENCY && queue.length && st.bytes < BUDGET) {
      const job = queue.shift();
      running += 1;
      fetch(job.url, { priority: 'low', credentials: 'same-origin' }).then(async (r) => {
        if (!r.ok) return;
        const buf = await r.arrayBuffer();
        st.bytes += buf.byteLength;
        st.files += 1;
        if (job.kind === 'adt') { st.tiles += 1; if (full) deps(buf); }
      }).catch(() => {}).finally(() => { running -= 1; pump(); });
    }
  }
  function deps(buf) {
    try {
      const ch = chunks(buf);
      for (const id of ['XETM', 'XDMM', 'OMWM']) {          // MTEX, MMDX, MWMO as stored
        if (!ch[id]) continue;
        for (const n of names(buf, ch[id])) {
          const m2 = /\.(mdx|mdl)$/i.test(n) ? n.replace(/\.(mdx|mdl)$/i, '.m2') : n;
          want(lowerUrl(m2), 'dep');
          if (/\.m2$/i.test(m2)) want(lowerUrl(m2.replace(/\.m2$/i, '00.skin')), 'dep');
        }
      }
    } catch { /* not an ADT we can read: the tile alone */ }
  }
  wenilla.on('frame', (s) => {
    const now = performance.now();
    if (now - lastAt < 1000 || s?.session?.state !== 'inworld') return;
    lastAt = now;
    const me = s.self, map = s.map?.id;
    if (!me?.pos || map == null) return;
    if (!dirs) { loadDirs(); return; }
    const dir = dirs.get(map);
    if (!dir) return;
    st.state = 'on';
    const [x, y] = me.pos;
    const [tx, ty] = tileOf(x, y);
    const here = `${map}:${tx}_${ty}`;
    if (around !== here) {
      around = here;
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        const ax = tx + dx, ay = ty + dy;
        if (ax >= 0 && ax < 64 && ay >= 0 && ay < 64) want(adtUrl(dir, ax, ay), 'adt');
      }
    }
    if (me.moving) {
      const speed = Math.max(7, Number(me.speed) || 7);
      const dist = Math.min(LOOK_MAX, Math.max(LOOK_MIN, speed * LOOK_SECS));
      for (const [ax, ay] of tilesAhead(x, y, Number(me.facing) || 0, dist)) want(adtUrl(dir, ax, ay), 'adt');
      st.last = `${dir} ${tx}_${ty} ahead ${Math.round(dist)} yd`;
    }
  });
  return st;
}
