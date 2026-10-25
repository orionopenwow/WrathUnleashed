// chain.js — the 3.3.5a patch chain and the `/data` routes, in plain JavaScript.
//
// A line-by-line mirror of the desktop helper's behaviour, so the browser client cannot tell a
// player's local folder from `wenilla-host`:
//   * crates/benilla-formats/src/chain.rs — ArchiveLayout (base archives, named patches, patch
//     globs, alternate.MPQ refused), mount_order, locale_of, data_listing, Chain::resolve /
//     contains / read / list (the `(listfile)` union).
//   * crates/wenilla-host/src/data.rs — `GET|HEAD /data/{name}` (raw tail percent-decoded, `/`
//     mapped to `\`), `GET /data/__index` (JSON array: chain list + loose Interface names),
//     content types, cache headers, 404 for missing/tombstoned, the loose `Interface` folder
//     beside `Data` served when the chain lacks a name.
//
// Depends on mpq.js (global `WUMpq` / require). Exposes `WUChain` and module.exports.
(function (root) {
  'use strict';
  const M = root.WUMpq || (typeof require === 'function' ? require('./mpq.js') : null);
  if (!M) throw new Error('chain.js needs mpq.js loaded first');

  // --- the client's layout (chain.rs LAYOUT, lowest priority first) ---------------------------
  const LOCALE = '{locale}';
  const LAYOUT = {
    base: [
      { path: '{locale}/lichking-speech-{locale}.MPQ', required: false },
      { path: '{locale}/expansion-speech-{locale}.MPQ', required: false },
      { path: '{locale}/lichking-locale-{locale}.MPQ', required: false },
      { path: '{locale}/expansion-locale-{locale}.MPQ', required: false },
      { path: '{locale}/speech-{locale}.MPQ', required: true },
      { path: '{locale}/locale-{locale}.MPQ', required: true },
      { path: 'common-2.MPQ', required: false },
      { path: 'common.MPQ', required: true },
      { path: 'lichking.MPQ', required: false },
      { path: 'expansion.MPQ', required: false },
    ],
    patches: ['{locale}/patch-{locale}.MPQ', 'patch.MPQ'],
    patchGlobs: ['patch-?.MPQ', '{locale}/patch-{locale}-?.MPQ'],
    unsupported: ['alternate.MPQ'],
  };

  const asciiLower = (s) => s.replace(/[A-Z]+/g, (m) => m.toLowerCase());
  const eqi = (a, b) => a.length === b.length && asciiLower(a) === asciiLower(b);
  /// MPQ hashing's equivalence: any ASCII case, `/` == `\`.
  const indexKey = (name) => asciiLower(name.replace(/\//g, '\\'));

  class ChainError extends Error {}

  function globMatch(pattern, path) {
    if (pattern.length !== path.length) return false;
    for (let i = 0; i < pattern.length; i++) {
      const p = pattern[i], c = path[i];
      if (p === '?') { if (c === '/') return false; continue; }
      if (asciiLower(p) !== asciiLower(c)) return false;
    }
    return true;
  }

  /// chain.rs `mount_order`: ascending priority, as found on disk.
  function mountOrder(files, locale, layout = LAYOUT) {
    const named = (p) => p.split(LOCALE).join(locale);
    const find = (want) => {
      want = named(want);
      return files.find((f) => eqi(f, want));
    };
    for (const u of layout.unsupported) {
      const found = find(u);
      if (found) throw new ChainError(`${found} is mounted by a mechanism benilla does not implement`);
    }
    const order = [];
    for (const b of layout.base) {
      const found = find(b.path);
      if (found) order.push(found);
      else if (b.required) throw new ChainError(`the required archive ${named(b.path)} is missing`);
    }
    for (const p of layout.patches) {
      const found = find(p);
      if (found) order.push(found);
    }
    const globs = layout.patchGlobs.map(named);
    const patches = files.filter((f) => globs.some((g) => globMatch(g, f)));
    const key = (f) => asciiLower(f.replace(/\//g, '\\'));
    patches.sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
    order.push(...patches);
    return order;
  }

  /// chain.rs `locale_of`: the one subfolder holding every required locale archive.
  function localeOf(files, dirs, layout = LAYOUT) {
    const complete = (dir) =>
      layout.base
        .filter((b) => b.required && b.path.includes(LOCALE))
        .every((b) => {
          const want = b.path.split(LOCALE).join(dir);
          return files.some((f) => eqi(f, want));
        });
    const hits = dirs.filter(complete);
    if (hits.length === 1) return hits[0];
    if (hits.length === 0) throw new ChainError('no locale folder holds the locale archives');
    throw new ChainError(`more than one locale folder: ${JSON.stringify(hits)}`);
  }

  const byteSort = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  // --- listings ---------------------------------------------------------------------------------
  //
  // A listing is what chain.rs's `data_listing` produces, plus where each file's bytes are:
  //   { files: ['common.MPQ', ..., 'enUS/locale-enUS.MPQ'], dirs: ['Cache', 'enUS'],
  //     open(rel) -> Promise<Blob|File>, loose: Map(lowerKey -> {name, file}) | null, label }
  // `files` is top-level files (sorted) then each folder's files (folders sorted, files sorted),
  // exactly the order Rust's `find` walks.

  /// From a flat list of `{ path, file }` (path `/`-separated, relative to whatever was dropped:
  /// "Data/common.MPQ", "World of Warcraft/Data/enUS/locale-enUS.MPQ", or "common.MPQ" when the
  /// Data folder's own contents were dropped). The Data folder is the shallowest folder holding a
  /// `common.MPQ`; its sibling `Interface` folder, when present, is the loose addon layer.
  function listingFromFiles(entries, label) {
    const norm = entries.map((e) => ({ path: e.path.replace(/\\/g, '/').replace(/^\/+/, ''), file: e.file }));
    let dataDir = null;
    for (const e of norm) {
      const parts = e.path.split('/');
      if (eqi(parts[parts.length - 1], 'common.MPQ')) {
        const dir = parts.slice(0, -1).join('/');
        if (dataDir === null || dir.split('/').length < dataDir.split('/').length) dataDir = dir;
      }
    }
    const prefix = dataDir === null ? null : dataDir ? dataDir + '/' : '';
    const top = [], sub = new Map(), byRel = new Map();
    let looseRoot = null;
    if (prefix !== null) {
      const parent = dataDir.includes('/') ? dataDir.slice(0, dataDir.lastIndexOf('/') + 1) : '';
      if (dataDir !== '') looseRoot = parent; // the folder that holds Data (and maybe Interface)
      for (const e of norm) {
        if (!e.path.startsWith(prefix)) continue;
        const rel = e.path.slice(prefix.length);
        const parts = rel.split('/');
        if (parts.length === 1) top.push(rel);
        else if (parts.length === 2) {
          if (!sub.has(parts[0])) sub.set(parts[0], []);
          sub.get(parts[0]).push(parts[1]);
        } else if (!sub.has(parts[0])) sub.set(parts[0], []);
        if (parts.length <= 2) byRel.set(rel, e.file);
      }
    }
    const dirs = [...sub.keys()].sort(byteSort);
    const files = top.sort(byteSort);
    for (const d of dirs) for (const f of sub.get(d).sort(byteSort)) files.push(`${d}/${f}`);
    let loose = null;
    if (looseRoot !== null) {
      for (const e of norm) {
        if (!e.path.startsWith(looseRoot)) continue;
        const rel = e.path.slice(looseRoot.length).split('/');
        if (rel.length < 2 || !eqi(rel[0], 'Interface')) continue;
        if (rel.slice(1).some((c) => c === '' || c.startsWith('.'))) continue;
        if (!loose) loose = new Map();
        const name = 'Interface\\' + rel.slice(1).join('\\');
        loose.set(indexKey(name), { name, file: e.file });
      }
    }
    return {
      label: label || dataDir || 'Data',
      dataFound: prefix !== null,
      files,
      dirs,
      loose,
      async open(rel) {
        const f = byRel.get(rel);
        if (!f) throw new ChainError(`${rel}: not in the folder`);
        return f;
      },
    };
  }

  /// Walk a FileSystemDirectoryHandle (Chrome/Edge drop or showDirectoryPicker) into the flat
  /// `{ path, file }` list `listingFromFiles` takes: the Data folder's files and its subfolders'
  /// files, and the loose Interface tree when the WoW folder itself (holding Data) was chosen.
  /// Only `getFile()` is called — no bytes are read here.
  async function entriesFromHandle(dir) {
    const out = [];
    const kids = async (h) => {
      const list = [];
      for await (const [name, child] of h.entries()) list.push([name, child]);
      return list;
    };
    const walkData = async (h, prefix) => {
      for (const [name, child] of await kids(h)) {
        if (child.kind === 'file') out.push({ path: prefix + name, file: await child.getFile() });
        else if (child.kind === 'directory') {
          out.push({ path: prefix + name + '/', dirOnly: true });
          for (const [n2, c2] of await kids(child)) {
            if (c2.kind === 'file') out.push({ path: prefix + name + '/' + n2, file: await c2.getFile() });
          }
        }
      }
    };
    const walkAll = async (h, prefix, depth) => {
      if (depth > 12) return;
      for (const [name, child] of await kids(h)) {
        if (name.startsWith('.')) continue;
        if (child.kind === 'file') out.push({ path: prefix + name, file: await child.getFile() });
        else await walkAll(child, prefix + name + '/', depth + 1);
      }
    };
    const top = await kids(dir);
    const hasCommon = top.some(([n, c]) => c.kind === 'file' && eqi(n, 'common.MPQ'));
    const dataChild = top.find(([n, c]) => c.kind === 'directory' && eqi(n, 'Data'));
    if (!hasCommon && dataChild) {
      await walkData(dataChild[1], dataChild[0] + '/');
      const iface = top.find(([n, c]) => c.kind === 'directory' && eqi(n, 'Interface'));
      if (iface) await walkAll(iface[1], iface[0] + '/', 0);
    } else {
      await walkData(dir, '');
    }
    return out.filter((e) => !e.dirOnly);
  }

  // --- build check ------------------------------------------------------------------------------

  /// Look for the build number without opening any archive: 3.3.5a ships
  /// `Data/component.wow-data.txt` and `Data/<locale>/component.wow-<locale>.txt` whose
  /// `<component ... version="12340"/>` names the build; a dropped WoW folder also has Wow.exe,
  /// whose VS_FIXEDFILEINFO carries 3.3.5.12340.
  async function detectBuild(entries) {
    const comp = entries.filter((e) => /(^|\/)component\.wow-[^/]*\.txt$/i.test(e.path));
    for (const e of comp) {
      try {
        const text = await e.file.slice(0, 4096).text();
        const m = text.match(/version\s*=\s*"(\d+)"/i);
        if (m) return { build: Number(m[1]), source: e.path };
      } catch (_) {}
    }
    const exe = entries.find((e) => /(^|\/)wow\.exe$/i.test(e.path) && e.path.split('/').length <= 2);
    if (exe) {
      try {
        const bytes = new Uint8Array(await exe.file.arrayBuffer());
        for (let i = 0; i + 52 <= bytes.length; i += 4) {
          if (bytes[i] === 0xbd && bytes[i + 1] === 0x04 && bytes[i + 2] === 0xef && bytes[i + 3] === 0xfe) {
            const dv = new DataView(bytes.buffer, i);
            const ms = dv.getUint32(8, true), ls = dv.getUint32(12, true);
            return { build: ls & 0xffff, version: `${ms >>> 16}.${ms & 0xffff}.${ls >>> 16}.${ls & 0xffff}`, source: exe.path };
          }
        }
      } catch (_) {}
    }
    return null;
  }

  /// The checks the page shows before handing the folder over. `ok` is exactly "Chain.open would
  /// succeed on the listing" (same locale + mount-order rules); `warnings` never block.
  async function validate(entries, label) {
    const listing = listingFromFiles(entries, label);
    const report = { ok: false, errors: [], warnings: [], checks: [], locale: null, order: [], build: null, listing };
    const has = (rel) => listing.files.some((f) => eqi(f, rel));
    if (!listing.dataFound) {
      report.errors.push('No common.MPQ found. Choose the "Data" folder inside your World of Warcraft 3.3.5a folder (or the World of Warcraft folder itself).');
      return report;
    }
    for (const want of ['common.MPQ', 'expansion.MPQ', 'lichking.MPQ']) report.checks.push({ name: want, ok: has(want) });
    try {
      report.locale = localeOf(listing.files, listing.dirs);
      report.checks.push({ name: `${report.locale}/locale-${report.locale}.MPQ`, ok: true });
    } catch (e) {
      report.checks.push({ name: 'locale folder (enUS, enGB, deDE, …) with locale-*.MPQ', ok: false });
      report.errors.push(e.message);
      return report;
    }
    try {
      report.order = mountOrder(listing.files, report.locale);
    } catch (e) {
      report.errors.push(e.message);
      return report;
    }
    if (!has('expansion.MPQ') || !has('lichking.MPQ')) {
      report.warnings.push('expansion.MPQ or lichking.MPQ is missing: this does not look like a complete 3.3.5a install (Wrath content will be missing).');
    }
    report.build = await detectBuild(entries);
    if (!report.build) report.warnings.push('Could not confirm the build number (no component.wow-*.txt or Wow.exe found). The client expects 3.3.5a (12340).');
    else if (report.build.build !== 12340) report.warnings.push(`This folder is build ${report.build.build}; the client expects 3.3.5a (12340).`);
    report.ok = true;
    return report;
  }

  // --- the chain --------------------------------------------------------------------------------

  class Chain {
    /// chain.rs `Chain::open` over a listing: locale, mount order, every archive opened (tables
    /// parsed once, in parallel). An archive that fails to open fails the chain, like benilla.
    static async open(listing) {
      const locale = localeOf(listing.files, listing.dirs);
      const order = mountOrder(listing.files, locale);
      if (!order.length) throw new ChainError('no known 3.3.5a MPQs found');
      const archives = await Promise.all(
        order.map(async (rel) => {
          const file = await listing.open(rel);
          try {
            return await M.MpqArchive.open(M.blobSource(file, rel), rel);
          } catch (e) {
            throw new ChainError(`opening ${rel}: ${e.message}`);
          }
        })
      );
      const c = new Chain();
      c.locale = locale;
      c.order = order;
      c.archives = archives; // ascending priority
      c.loose = listing.loose || null;
      c.label = listing.label;
      return c;
    }

    /// The highest-priority archive with an entry for `name` (a delete marker included).
    resolve(name) {
      const h = M.nameHashes(name);
      for (let i = this.archives.length - 1; i >= 0; i--) {
        const bi = this.archives[i].find(h);
        if (bi >= 0) return { archive: this.archives[i], entry: this.archives[i].entry(bi), hashes: h };
      }
      return null;
    }

    contains(name) {
      const r = this.resolve(name);
      return !!r && (r.entry.flags & M.FLAG.DELETE_MARKER) === 0;
    }

    /// Read from the winning archive; throws MpqError 'notfound' / 'deleted' for the two missing
    /// shapes data.rs maps to 404.
    async read(name) {
      const r = this.resolve(name);
      if (!r) throw new M.MpqError('notfound', `file not in patch chain: ${name}`);
      if (r.entry.flags & M.FLAG.DELETE_MARKER) {
        throw new M.MpqError('deleted', `file deleted from patch chain: ${name} (tombstoned by ${r.archive.label})`);
      }
      return r.archive.readEntry(r.entry, name);
    }

    /// chain.rs `Chain::list`: union of every archive's `(listfile)` in mount order, deduped by
    /// the hashing equivalence, first spelling kept, tombstoned and unresolvable names dropped.
    async list() {
      const seen = new Set();
      const out = [];
      const dec = new TextDecoder('utf-8');
      for (const a of this.archives) {
        let bytes;
        try {
          bytes = await a.readFile('(listfile)');
        } catch (_) {
          continue;
        }
        for (const raw of dec.decode(bytes).split(/[;\r\n]/)) {
          const name = raw.trim();
          if (!name) continue;
          const key = indexKey(name);
          if (seen.has(key)) continue;
          seen.add(key);
          const r = this.resolve(name);
          if (r && !(r.entry.flags & M.FLAG.DELETE_MARKER)) out.push(name);
        }
      }
      return out;
    }
  }

  // --- a small byte-budget LRU of decompressed files -------------------------------------------

  class Lru {
    constructor(maxBytes = 96 * 1024 * 1024, maxItem = 16 * 1024 * 1024) {
      this.max = maxBytes;
      this.maxItem = maxItem;
      this.bytes = 0;
      this.map = new Map();
    }
    get(k) {
      const v = this.map.get(k);
      if (v === undefined) return undefined;
      this.map.delete(k);
      this.map.set(k, v);
      return v;
    }
    set(k, v) {
      if (v.length > this.maxItem) return;
      if (this.map.has(k)) { this.bytes -= this.map.get(k).length; this.map.delete(k); }
      this.map.set(k, v);
      this.bytes += v.length;
      for (const [key, val] of this.map) {
        if (this.bytes <= this.max) break;
        this.map.delete(key);
        this.bytes -= val.length;
      }
    }
    clear() { this.map.clear(); this.bytes = 0; }
  }

  // --- the /data routes ---------------------------------------------------------------------------

  /// data.rs `content_type`: chosen for the compression predicate, mirrored for fidelity.
  function contentType(name) {
    const i = name.lastIndexOf('.');
    const ext = i >= 0 ? asciiLower(name.slice(i + 1)) : asciiLower(name);
    if (ext === 'blp') return 'image/x-blp';
    if (ext === 'mp3') return 'audio/mpeg';
    return 'application/octet-stream';
  }

  /// `percent_decode_str(raw).decode_utf8_lossy()`: %XX only, '+' untouched, bad UTF-8 replaced.
  function percentDecodeLossy(raw) {
    const bytes = [];
    for (let i = 0; i < raw.length; i++) {
      const c = raw.charCodeAt(i);
      if (c === 0x25 && i + 2 < raw.length + 0 && /^[0-9a-fA-F]{2}$/.test(raw.substr(i + 1, 2))) {
        bytes.push(parseInt(raw.substr(i + 1, 2), 16));
        i += 2;
      } else if (c < 0x80) bytes.push(c);
      else for (const b of new TextEncoder().encode(raw[i])) bytes.push(b);
    }
    return new TextDecoder('utf-8').decode(new Uint8Array(bytes));
  }

  /// The server half of the Data URL scheme over a Chain. One per mounted chain.
  class DataServer {
    constructor(chain, opts = {}) {
      this.chain = chain;
      this.cache = new Lru(opts.cacheBytes, opts.cacheItemBytes);
      this.inflight = new Map();
      this.indexPromise = null;
    }

    /// The name list as JSON bytes, built once (single-flight; a failure is retried next time).
    index() {
      if (!this.indexPromise) {
        this.indexPromise = (async () => {
          const names = await this.chain.list();
          if (this.chain.loose) for (const { name } of this.chain.loose.values()) names.push(name);
          return new TextEncoder().encode(JSON.stringify(names));
        })().catch((e) => {
          this.indexPromise = null;
          throw e;
        });
      }
      return this.indexPromise;
    }

    /// `{ bytes, editable }` or throws MpqError notfound/deleted. Chain first, then the loose
    /// Interface folder for a name the chain lacks (data.rs `file`).
    async readName(name) {
      const key = indexKey(name);
      const hit = this.cache.get(key);
      if (hit) return hit;
      if (this.inflight.has(key)) return this.inflight.get(key);
      const p = (async () => {
        try {
          const bytes = await this.chain.read(name);
          const v = { bytes, editable: false, length: bytes.length };
          this.cache.set(key, v);
          return v;
        } catch (e) {
          if ((e.code === 'notfound' || e.code === 'deleted') && this.chain.loose) {
            const l = this.chain.loose.get(key);
            if (l) return { bytes: new Uint8Array(await l.file.arrayBuffer()), editable: true };
          }
          throw e;
        }
      })().finally(() => this.inflight.delete(key));
      this.inflight.set(key, p);
      return p;
    }

    /// Answer one request. `pathname` is the URL path (still percent-encoded), e.g.
    /// `/data/Interface%5CGlues%5CFoo.blp`. Returns `{ status, headers, body }` (body may be null).
    async handle(method, pathname, prefix = '/data/') {
      if (!pathname.startsWith(prefix)) return { status: 404, headers: {}, body: null };
      const raw = pathname.slice(prefix.length);
      const head = method === 'HEAD';
      if (method !== 'GET' && !head) return { status: 405, headers: { allow: 'GET,HEAD' }, body: null };
      const corp = { 'cross-origin-resource-policy': 'same-origin' };
      if (raw === '__index') {
        try {
          const bytes = await this.index();
          return { status: 200, headers: { ...corp, 'cache-control': 'no-cache', 'content-type': 'application/json' }, body: head ? null : bytes };
        } catch (e) {
          return { status: 500, headers: corp, body: null, error: e };
        }
      }
      const name = percentDecodeLossy(raw).replace(/\//g, '\\');
      try {
        const { bytes, editable } = await this.readName(name);
        return {
          status: 200,
          headers: {
            ...corp,
            'content-type': contentType(name),
            'cache-control': editable ? 'no-cache' : 'private, max-age=31536000, immutable',
            'content-length': String(bytes.length),
          },
          body: head ? null : bytes,
        };
      } catch (e) {
        if (e && (e.code === 'notfound' || e.code === 'deleted')) return { status: 404, headers: corp, body: null };
        return { status: 500, headers: corp, body: null, error: e };
      }
    }
  }

  const api = {
    LAYOUT,
    ChainError,
    Chain,
    DataServer,
    Lru,
    globMatch,
    mountOrder,
    localeOf,
    listingFromFiles,
    entriesFromHandle,
    detectBuild,
    validate,
    contentType,
    percentDecodeLossy,
    indexKey,
  };
  root.WUChain = api;
  if (typeof module === 'object' && module && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : self);
