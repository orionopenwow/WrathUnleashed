// wu-addons-core.js — "Your addons": the parts with no page in them, so node can test them
// (tests/wu-addons.test.cjs). wu-addons.js is the page half (the drop overlay, the list).
//
//   readZip(bytes)          a zip's files, with zip-slip, symlink, encryption and size checks
//   validate(entries)       the UI half of mods/wu-mod.py's rules on a zip's or a folder's files:
//                           which addon folders it holds, and every reason to refuse it
//   openStore({root, user}) the player's addons in this browser (Origin Private File System),
//                           one folder per account: list, add, on/off, remove, load
//
// How the client gets them: wrath-early.js puts a layered body store at
// globalThis.__wenilla_prefetch before the client starts. The client (benilla-formats web.rs)
// asks that store first for every /data read and for the name index /data/__index; the layer
// answers Interface\AddOns\<Name>\... from these files and adds their names to the index, so the
// client's own addon discovery (ui_script/addons.rs discover_web) finds them like any other addon,
// and they run in its addon sandbox. Nothing here runs an addon's code, and nothing is uploaded.

export const MiB = 1024 * 1024;
// mods/wu-mod.py's limits (MAX_FILE_BYTES, MAX_PACKAGE_BYTES, MAX_FILES), plus a cap on all of a
// player's addons together in this browser.
export const LIMITS = { file: 10 * MiB, package: 50 * MiB, files: 2000, total: 100 * MiB };

// Game data: never allowed, by extension or by file signature (wu-mod.py BLOCKED_EXT/BLOCKED_MAGIC).
export const BLOCKED_EXT = {
  '.mpq': 'an archive of game data', '.blp': 'a game texture', '.m2': 'a game model', '.wmo': 'a game world model',
  '.adt': 'a game terrain tile', '.dbc': 'a game database', '.skin': 'a game model skin', '.anim': 'a game animation',
  '.wdt': 'a game map file', '.wdl': 'a game map file', '.db2': 'a game database', '.bls': 'a game shader',
};
const BLOCKED_MAGIC = [['MPQ\x1a', 'an archive of game data'], ['MPQ\x1b', 'an archive of game data'],
  ['BLP1', 'a game texture'], ['BLP2', 'a game texture'], ['MD20', 'a game model'], ['MD21', 'a game model'],
  ['WDBC', 'a game database'], ['REVM', 'a game map file']];
// What an addon folder may hold: its code and its own art, fonts and sounds (.tga for textures).
export const ALLOWED_EXT = new Set(['.toc', '.lua', '.xml', '.tga', '.ttf', '.ogg', '.mp3', '.wav', '.txt', '.md', '.toml']);
// Folder names the realm ships itself (mods-overlay.py RESERVED, wu-mod.py RESERVED_ADDONS).
export const RESERVED = new Set(['foreverui', 'wrathunleashedui', 'wumodcatalog']);
export const NAME_RE = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
const IGNORED = new Set(['.git', '__pycache__', '.ds_store', 'thumbs.db', 'desktop.ini', '.gitignore', '__macosx']);
// a WU mod package's top level (wu-mod.py TOP_LEVEL_OK): only ui/ is installed in the browser
const PACKAGE_TOP = new Set(['mod.json', 'ui', 'realm', 'assets', 'tests', 'readme.md', 'readme.txt', 'license',
  'license.txt', 'license.md', 'changelog.md']);
// loose notes beside the addon folders of a plain addon zip: skipped, never installed
const NOTE_RE = /^(readme|license|licence|changelog|credits)(\.(md|txt))?$/i;

export class AddonError extends Error {
  constructor(message, problems = []) {
    super(message);
    this.problems = problems;
  }
}

const ext = (p) => { const b = p.slice(p.lastIndexOf('/') + 1); const i = b.lastIndexOf('.'); return i > 0 ? b.slice(i).toLowerCase() : ''; };
export const fmtSize = (n) => (n < 1024 ? `${n} B` : n < MiB ? `${Math.ceil(n / 1024)} KB` : `${(n / MiB).toFixed(1)} MB`);

// -- zip ------------------------------------------------------------------------------------------

/** A zip entry's name made safe, '/'-separated, or null for a folder entry. Throws on zip-slip. */
export function safePath(raw) {
  const p = String(raw).replace(/\\/g, '/');
  if (p.startsWith('/') || /^[A-Za-z]:/.test(p)) throw new AddonError(`unsafe path in the zip: ${p}`);
  if (p.endsWith('/')) return null;
  const parts = p.split('/');
  for (const part of parts) {
    if (part === '' || part === '.' || part === '..' || /[\x00-\x1f:*?"<>|]/.test(part)) {
      throw new AddonError(`unsafe path in the zip: ${p}`);
    }
  }
  return parts.join('/');
}

let CRC_TABLE = null;
function crc32(u8) {
  if (!CRC_TABLE) {
    CRC_TABLE = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      CRC_TABLE[n] = c >>> 0;
    }
  }
  let c = 0xffffffff;
  for (let i = 0; i < u8.length; i++) c = CRC_TABLE[(c ^ u8[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function inflateRaw(data, max) {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  const reader = stream.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    let r;
    try { r = await reader.read(); } catch (_) { throw new AddonError('the zip is damaged (a file does not unpack)'); }
    if (r.done) break;
    total += r.value.byteLength;
    if (total > max) {
      reader.cancel().catch(() => {});
      throw new AddonError('a file in the zip unpacks bigger than it says');
    }
    chunks.push(r.value);
  }
  const out = new Uint8Array(total);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.byteLength; }
  return out;
}

/** The files of a zip: [{path, data: Uint8Array}], folders and ignored names left out. */
export async function readZip(bytes, limits = LIMITS) {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 22 - 65535); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new AddonError('this is not a zip file');
  const count = dv.getUint16(eocd + 10, true);
  const cdOff = dv.getUint32(eocd + 16, true);
  if (count === 0xffff || cdOff === 0xffffffff) throw new AddonError('zip64 archives are not supported: an addon is never that big');
  if (count > limits.files) throw new AddonError(`the zip has more than ${limits.files} files`);
  const dec = new TextDecoder();
  const entries = [];
  let p = cdOff;
  let declared = 0;
  for (let n = 0; n < count; n++) {
    if (p + 46 > u8.length || dv.getUint32(p, true) !== 0x02014b50) throw new AddonError('the zip is damaged (its file list does not read)');
    const madeBy = dv.getUint16(p + 4, true);
    const flags = dv.getUint16(p + 8, true);
    const method = dv.getUint16(p + 10, true);
    const crc = dv.getUint32(p + 16, true);
    const csize = dv.getUint32(p + 20, true);
    const usize = dv.getUint32(p + 24, true);
    const nlen = dv.getUint16(p + 28, true), elen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
    const attr = dv.getUint32(p + 38, true);
    const lho = dv.getUint32(p + 42, true);
    const raw = dec.decode(u8.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + elen + clen;
    const path = safePath(raw);
    if (path === null) continue;
    if (path.split('/').some((x) => IGNORED.has(x.toLowerCase()))) continue;
    if ((madeBy >> 8) === 3 && ((attr >>> 16) & 0o170000) === 0o120000) throw new AddonError(`symbolic links are not allowed: ${path}`);
    if (flags & 1) throw new AddonError(`the zip is password protected: ${path}`);
    if (method !== 0 && method !== 8) throw new AddonError(`the zip uses a packing method this page cannot read (${method}): repack it as a normal zip`);
    if (usize > limits.file) throw new AddonError(`${path} is larger than ${fmtSize(limits.file)}`);
    declared += usize;
    if (declared > limits.package) throw new AddonError(`the zip unpacks to more than ${fmtSize(limits.package)}`);
    entries.push({ path, method, crc, csize, usize, lho });
  }
  const out = [];
  for (const e of entries) {
    if (e.lho + 30 > u8.length || dv.getUint32(e.lho, true) !== 0x04034b50) throw new AddonError('the zip is damaged (a file header is missing)');
    const start = e.lho + 30 + dv.getUint16(e.lho + 26, true) + dv.getUint16(e.lho + 28, true);
    if (start + e.csize > u8.length) throw new AddonError('the zip is cut short');
    const body = u8.subarray(start, start + e.csize);
    const data = e.method === 0 ? body.slice() : await inflateRaw(body, e.usize);
    if (data.length !== e.usize || crc32(data) !== e.crc) throw new AddonError(`the zip is damaged: ${e.path} does not match its checksum`);
    out.push({ path: e.path, data });
  }
  return out;
}

// -- the layout and the rules ---------------------------------------------------------------------

function parseToc(text) {
  const meta = {}, files = [];
  for (const line of text.split(/\r?\n/)) {
    const s = line.trim();
    if (s.startsWith('##')) {
      const m = /^##\s*([^:]+):\s*(.*)$/.exec(s);
      if (m) meta[m[1].trim()] = m[2].trim();
    } else if (s && !s.startsWith('#')) files.push(s.replace(/\\/g, '/'));
  }
  return { meta, files };
}

function normJoin(base, rel) {
  const out = base ? base.split('/') : [];
  for (const part of rel.replace(/\\/g, '/').split('/')) {
    if (part === '' || part === '.') continue;
    if (part === '..') { if (!out.length) return null; out.pop(); } else out.push(part);
  }
  return out.join('/');
}

/** Where the addon folders are: a WU mod package (mod.json + ui/<Name>/), an
 *  Interface/AddOns/<Name>/ tree, a zip of addon folders (<Name>/<Name>.toc), one wrapped in a
 *  folder, or a zip of one addon's own files (<Name>.toc at the top). */
function locate(entries) {
  const paths = entries.map((e) => e.path);
  const low = paths.map((p) => p.toLowerCase());
  const pkg = low.find((p) => p === 'mod.json' || /^[^/]+\/mod\.json$/.test(p));
  if (pkg !== undefined) return { kind: 'package', root: pkg.slice(0, -'mod.json'.length), addonsAt: 'ui/' };
  const tops = new Set(low.map((p) => p.split('/')[0]));
  const wrap = tops.size === 1 && low.every((p) => p.includes('/')) ? [...tops][0] + '/' : '';
  for (const r of wrap ? ['', wrap] : ['']) {
    if (low.some((p) => p.startsWith(r + 'interface/addons/'))) return { kind: 'tree', root: r, addonsAt: 'interface/addons/' };
  }
  const tocAt = (r) => low.some((p) => {
    if (!p.startsWith(r)) return false;
    const parts = p.slice(r.length).split('/');
    return parts.length === 2 && parts[1] === parts[0] + '.toc';
  });
  if (tocAt('')) return { kind: 'folders', root: '', addonsAt: '' };
  if (wrap && tocAt(wrap)) return { kind: 'folders', root: wrap, addonsAt: '' };
  const rootTocs = paths.filter((p) => !p.includes('/') && p.toLowerCase().endsWith('.toc'));
  if (rootTocs.length === 1) return { kind: 'single', root: '', name: rootTocs[0].slice(0, -4) };
  return null;
}

/**
 * Check dropped files against the UI half of mods/wu-mod.py. `entries`: [{path, data}], '/'
 * separated (readZip's, or a dropped folder's with the folder's own name first). Returns
 * {addons: [{name, size, files: [{path, data}]}], errors: [], warnings: [], skipped: []}: install
 * only when errors is empty. `opts.xml(text)` returns an error string for XML that is not well
 * formed (the page passes DOMParser's; without it XML is not parsed, only its file references).
 */
export function validate(entries, opts = {}) {
  const limits = opts.limits || LIMITS;
  const errors = [], warnings = [], skipped = [];
  const res = { addons: [], errors, warnings, skipped };
  const files = entries.filter((e) => !e.path.split('/').some((x) => IGNORED.has(x.toLowerCase())));
  if (!files.length) { errors.push('there are no files in it'); return res; }
  if (files.length > limits.files) { errors.push(`it has more than ${limits.files} files`); return res; }
  const where = locate(files);
  if (!where) {
    errors.push('no addon found: an addon is a folder <Name> with a <Name>.toc inside (Interface/AddOns/<Name>/)');
    return res;
  }
  const byName = new Map();   // lower name -> {name, files}
  for (const e of files) {
    const low = e.path.toLowerCase();
    if (where.kind === 'single') {
      const name = where.name;
      if (!byName.has(name.toLowerCase())) byName.set(name.toLowerCase(), { name, files: [] });
      byName.get(name.toLowerCase()).files.push({ path: e.path, data: e.data });
      continue;
    }
    if (!low.startsWith(where.root)) { errors.push(`${e.path} is outside Interface/AddOns/<Name>/`); continue; }
    const rel = e.path.slice(where.root.length);
    const relLow = rel.toLowerCase();
    if (where.kind === 'package' && !relLow.startsWith('ui/')) {
      const top = relLow.split('/')[0];
      if (PACKAGE_TOP.has(top)) { skipped.push(rel); continue; }
      errors.push(`${e.path} is outside Interface/AddOns/<Name>/ (a mod package installs only its ui/ folder here)`);
      continue;
    }
    if (!relLow.startsWith(where.addonsAt)) {
      if (!rel.includes('/') && NOTE_RE.test(rel)) { skipped.push(rel); continue; }
      errors.push(`${e.path} is outside Interface/AddOns/<Name>/`);
      continue;
    }
    const inner = rel.slice(where.addonsAt.length);
    const slash = inner.indexOf('/');
    if (slash < 0) {
      if (NOTE_RE.test(inner)) { skipped.push(rel); continue; }
      errors.push(`${e.path} is not inside an addon folder (Interface/AddOns/<Name>/)`);
      continue;
    }
    const name = inner.slice(0, slash);
    if (!byName.has(name.toLowerCase())) byName.set(name.toLowerCase(), { name, files: [] });
    const a = byName.get(name.toLowerCase());
    if (a.name !== name) { errors.push(`${e.path}: the folder ${a.name} is spelled two ways`); continue; }
    a.files.push({ path: inner.slice(slash + 1), data: e.data });
  }
  if (where.kind === 'package' && files.some((e) => e.path.toLowerCase().startsWith(where.root + 'realm/'))) {
    warnings.push('this mod also has a realm half: only its addon is installed here; the realm half needs the realm to install it');
  }
  let total = 0;
  for (const a of byName.values()) {
    const errs = checkAddon(a, opts, limits, warnings);
    errors.push(...errs);
    a.size = a.files.reduce((n, f) => n + f.data.length, 0);
    total += a.size;
    res.addons.push(a);
  }
  if (!res.addons.length && !errors.length) errors.push('no addon found in it');
  if (total > limits.package) errors.push(`it is larger than ${fmtSize(limits.package)}`);
  return res;
}

function checkAddon(a, opts, limits, warnings) {
  const errors = [];
  const at = (p) => `${a.name}/${p}`;
  if (!NAME_RE.test(a.name)) {
    errors.push(`${a.name}: an addon folder name is letters, digits, _ . and -, starting with a letter`);
    return errors;
  }
  if (RESERVED.has(a.name.toLowerCase()) || a.name.toLowerCase().startsWith('blizzard_')) {
    errors.push(`${a.name}: this name is reserved for the realm's own interface`);
    return errors;
  }
  const have = new Map(a.files.map((f) => [f.path, f]));
  const lower = new Map(a.files.map((f) => [f.path.toLowerCase(), f.path]));
  for (const f of a.files) {
    const e = ext(f.path);
    if (BLOCKED_EXT[e]) { errors.push(`${at(f.path)} is ${BLOCKED_EXT[e]}: game data cannot be in an addon`); continue; }
    const head = String.fromCharCode(...f.data.subarray(0, 4));
    const magic = BLOCKED_MAGIC.find(([m]) => head === m);
    if (magic) { errors.push(`${at(f.path)} is ${magic[1]} (renamed): game data cannot be in an addon`); continue; }
    if (!ALLOWED_EXT.has(e)) { errors.push(`${at(f.path)}: ${e || 'files without an extension'} is not an addon file type (allowed: ${[...ALLOWED_EXT].join(' ')})`); continue; }
    if (f.data.length > limits.file) errors.push(`${at(f.path)} is larger than ${fmtSize(limits.file)}`);
  }
  const tocPath = lower.get(`${a.name.toLowerCase()}.toc`);
  if (!tocPath) {
    errors.push(`${a.name}: no ${a.name}.toc in the folder (the .toc has the same name as its folder)`);
    return errors;
  }
  const { meta, files } = parseToc(new TextDecoder().decode(have.get(tocPath).data));
  if (meta.Interface !== '30300') errors.push(`${at(tocPath)}: ## Interface must be 30300 for 3.3.5a (got ${meta.Interface === undefined ? 'none' : meta.Interface})`);
  if (!meta.Title) warnings.push(`${at(tocPath)}: no ## Title line`);
  for (const item of files) {
    if (!have.has(item)) {
      const hint = lower.has(item.toLowerCase()) ? ` (the case differs: ${lower.get(item.toLowerCase())})` : '';
      errors.push(`${at(tocPath)} lists ${item}, which is not in the folder${hint}`);
    }
  }
  for (const f of a.files) {
    if (ext(f.path) !== '.xml') continue;
    const text = new TextDecoder().decode(f.data);
    if (opts.xml) {
      const bad = opts.xml(text);
      if (bad) { errors.push(`${at(f.path)}: the XML is not well formed (${bad})`); continue; }
    }
    const base = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : '';
    for (const m of text.matchAll(/<(Script|Include)\b[^>]*?\bfile\s*=\s*["']([^"']+)["']/g)) {
      const ref = normJoin(base, m[2]);
      if (ref === null || !have.has(ref)) errors.push(`${at(f.path)}: <${m[1]} file="${m[2]}"> points to a file that is not in the folder`);
    }
  }
  return errors;
}

// -- the store ------------------------------------------------------------------------------------

/** The per-account folder name (the account as typed, folded to a safe name), 'default' when the
 *  page does not know the account. */
export function userKey(user) {
  const k = String(user || '').toLowerCase().replace(/[^a-z0-9_-]/g, '_').slice(0, 32);
  return k && /[a-z0-9]/.test(k) ? 'u-' + k : 'default';
}

/**
 * The player's addons in this browser: OPFS wu-addons/<account>/ holds index.json and one
 * <name>.pack per addon (its files back to back; index.json has where each one is). `root` is a
 * FileSystemDirectoryHandle (default: navigator.storage.getDirectory()). Every change is one
 * operation at a time, and index.json is written last, so a failed write leaves the old list.
 */
export async function openStore({ root, user, limits = LIMITS } = {}) {
  if (!root) {
    if (!globalThis.navigator?.storage?.getDirectory) throw new AddonError('this browser cannot keep addons (no private file storage)');
    root = await navigator.storage.getDirectory();
  }
  const top = await root.getDirectoryHandle('wu-addons', { create: true });
  const dir = await top.getDirectoryHandle(userKey(user), { create: true });
  let chain = Promise.resolve();
  const serial = (fn) => { const p = chain.then(fn); chain = p.catch(() => {}); return p; };
  const packName = (name) => name.toLowerCase() + '.pack';

  async function readIndex() {
    try {
      const f = await (await dir.getFileHandle('index.json')).getFile();
      const j = JSON.parse(await f.text());
      return Array.isArray(j && j.addons) ? j.addons.filter((a) => a && NAME_RE.test(a.name) && Array.isArray(a.files)) : [];
    } catch (_) {
      return [];
    }
  }
  async function write(name, data) {
    const w = await (await dir.getFileHandle(name, { create: true })).createWritable();
    try { await w.write(data); await w.close(); } catch (e) { try { await w.abort?.(); } catch (_) {} throw e; }
  }
  const writeIndex = (addons) => write('index.json', JSON.stringify({ format: 1, addons }));
  const view = (a) => ({ name: a.name, size: a.size, files: a.files.length, on: a.on !== false, added: a.added });

  return {
    user: userKey(user),
    list: () => serial(async () => (await readIndex()).map(view)),
    /** Add or replace one checked addon ({name, files: [{path, data}]}). */
    add: (addon) => serial(async () => {
      if (!NAME_RE.test(addon.name) || RESERVED.has(addon.name.toLowerCase())) throw new AddonError(`${addon.name}: not an addon name that can be installed`);
      const all = await readIndex();
      const others = all.filter((a) => a.name.toLowerCase() !== addon.name.toLowerCase());
      const size = addon.files.reduce((n, f) => n + f.data.length, 0);
      const used = others.reduce((n, a) => n + (a.size || 0), 0);
      if (used + size > limits.total) {
        throw new AddonError(`not enough room: your addons may use ${fmtSize(limits.total)} in this browser and ${fmtSize(used)} is taken; remove one first`);
      }
      const pack = new Uint8Array(size);
      const files = [];
      let o = 0;
      for (const f of addon.files) { pack.set(f.data, o); files.push([f.path, o, f.data.length]); o += f.data.length; }
      await write(packName(addon.name), pack);
      const prev = all.find((a) => a.name.toLowerCase() === addon.name.toLowerCase());
      others.push({ name: addon.name, size, on: prev ? prev.on !== false : true, added: Date.now(), files });
      others.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
      await writeIndex(others);
      return view(others.find((a) => a.name === addon.name));
    }),
    setOn: (name, on) => serial(async () => {
      const all = await readIndex();
      const a = all.find((x) => x.name.toLowerCase() === String(name).toLowerCase());
      if (!a) return false;
      a.on = !!on;
      await writeIndex(all);
      return true;
    }),
    remove: (name) => serial(async () => {
      const all = await readIndex();
      const keep = all.filter((a) => a.name.toLowerCase() !== String(name).toLowerCase());
      if (keep.length === all.length) return false;
      await writeIndex(keep);
      try { await dir.removeEntry(packName(name)); } catch (_) { /* already gone */ }
      return true;
    }),
    usage: () => serial(async () => ({ used: (await readIndex()).reduce((n, a) => n + (a.size || 0), 0), cap: limits.total })),
    /** The turned-on addons' files for the client: [{name, files: [[path, ArrayBuffer]]}]. A
     *  missing or short pack is left out (and named in `broken`). */
    load: () => serial(async () => {
      const out = [], broken = [];
      for (const a of await readIndex()) {
        if (a.on === false) continue;
        try {
          const buf = await (await (await dir.getFileHandle(packName(a.name))).getFile()).arrayBuffer();
          if (buf.byteLength !== a.size) throw new Error('size');
          out.push({ name: a.name, files: a.files.map(([p, off, len]) => [p, buf.slice(off, off + len)]) });
        } catch (_) {
          broken.push(a.name);
        }
      }
      return Object.assign(out, { broken });
    }),
  };
}
