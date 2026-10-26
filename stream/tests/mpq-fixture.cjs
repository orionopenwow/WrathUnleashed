// mpq-fixture.cjs — small, real MPQ archives for the tests (format v1, the layout 3.3.5a's own archives use):
// an encrypted hash table and block table, files stored, zlib-compressed (single unit or sectored), or as
// delete markers, and a (listfile). Read back by www-files/mpq.js exactly like a game archive.
//
//   const { buildMpq, gameFolder, fakeBlob } = require('./mpq-fixture.cjs');
//   buildMpq({ 'DBFilesClient\\Map.dbc': Buffer.from('...'), 'Old.blp': { deleted: true } })  -> Buffer
//   gameFolder({ locale: 'enUS', build: 12340, ... })  -> [{ path, data }] a 3.3.5a Data folder
//   fakeBlob(size, segments)  -> a Blob-like of any size (sparse: zeros between segments), counting reads
'use strict';
const zlib = require('node:zlib');
const M = require('../www-files/mpq.js');

const FLAG = M.FLAG;
const FILE_KEY = M.HASH.FILE_KEY;

/// files: { name: Buffer | string | { data, compress: 'single'|'sectors'|false, deleted } }.
/// opts: { listfile = true, sectorShift = 3 (4 KiB sectors), dataOffset = 0 (where the files start: a big
/// number makes a sparse "huge" archive with fakeBlob), header = 0 (MPQ header offset) }.
function buildMpq(files, opts = {}) {
  const listfile = opts.listfile !== false;
  const shift = opts.sectorShift === undefined ? 3 : opts.sectorShift;
  const ss = 512 * 2 ** shift;
  const names = Object.keys(files);
  const all = names.slice();
  if (listfile) all.push('(listfile)');
  const bodies = [];
  const blocks = [];
  let pos = 32;                                   // after the header (archive-relative)
  const segments = [];                            // [archive offset, Buffer] (for fakeBlob)
  const place = (buf) => {
    const at = opts.dataOffset && bodies.length === 0 ? Math.max(pos, opts.dataOffset) : pos;
    bodies.push([at, buf]);
    pos = at + buf.length;
    return at;
  };
  for (const name of all) {
    let spec = name === '(listfile)' ? Buffer.from(names.join('\r\n') + '\r\n') : files[name];
    if (typeof spec === 'string' || Buffer.isBuffer(spec) || spec instanceof Uint8Array) spec = { data: spec };
    if (spec.deleted) {
      blocks.push([0, 0, 0, (FLAG.EXISTS | FLAG.DELETE_MARKER) >>> 0]);
      continue;
    }
    const data = Buffer.from(typeof spec.data === 'string' ? Buffer.from(spec.data) : spec.data);
    const mode = spec.compress === undefined ? (data.length > 64 ? 'single' : false) : spec.compress;
    if (!mode || data.length === 0) {
      const at = place(data);
      blocks.push([at, data.length, data.length, FLAG.EXISTS >>> 0]);
    } else if (mode === 'single') {
      const z = zlib.deflateSync(data);
      const body = z.length + 1 < data.length ? Buffer.concat([Buffer.from([0x02]), z]) : data;
      const at = place(body);
      blocks.push([at, body.length, data.length, (FLAG.EXISTS | FLAG.COMPRESS | FLAG.SINGLE_UNIT) >>> 0]);
    } else {
      const count = Math.ceil(data.length / ss);
      const parts = [];
      for (let i = 0; i < count; i++) {
        const raw = data.subarray(i * ss, Math.min(data.length, (i + 1) * ss));
        const z = zlib.deflateSync(raw);
        parts.push(z.length + 1 < raw.length ? Buffer.concat([Buffer.from([0x02]), z]) : Buffer.from(raw));
      }
      const table = Buffer.alloc((count + 1) * 4);
      let off = table.length;
      for (let i = 0; i < count; i++) { table.writeUInt32LE(off, i * 4); off += parts[i].length; }
      table.writeUInt32LE(off, count * 4);
      const body = Buffer.concat([table, ...parts]);
      const at = place(body);
      blocks.push([at, body.length, data.length, (FLAG.EXISTS | FLAG.COMPRESS) >>> 0]);
    }
  }
  let hashCount = 4;
  while (hashCount < all.length * 2) hashCount *= 2;
  const hash = new Uint32Array(hashCount * 4).fill(0xffffffff);
  all.forEach((name, bi) => {
    const h = M.nameHashes(name);
    let i = (h.start & (hashCount - 1)) >>> 0;
    while (hash[i * 4 + 3] !== 0xffffffff) i = (i + 1) % hashCount;
    hash[i * 4] = h.a; hash[i * 4 + 1] = h.b; hash[i * 4 + 2] = 0; hash[i * 4 + 3] = bi;
  });
  const block = new Uint32Array(blocks.length * 4);
  blocks.forEach((b, i) => block.set(b, i * 4));
  const hashBytes = new Uint8Array(hash.buffer.slice(0));
  M.encryptBytes(hashBytes, M.hashString('(hash table)', FILE_KEY));
  const blockBytes = new Uint8Array(block.buffer.slice(0));
  M.encryptBytes(blockBytes, M.hashString('(block table)', FILE_KEY));
  const hashPos = pos, blockPos = pos + hashBytes.length;
  const size = blockPos + blockBytes.length;
  const head = Buffer.alloc(32);
  head.writeUInt32LE(0x1a51504d, 0);
  head.writeUInt32LE(32, 4);
  head.writeUInt32LE(size, 8);
  head.writeUInt16LE(0, 12);
  head.writeUInt16LE(shift, 14);
  head.writeUInt32LE(hashPos, 16);
  head.writeUInt32LE(blockPos, 20);
  head.writeUInt32LE(hashCount, 24);
  head.writeUInt32LE(blocks.length, 28);
  segments.push([0, head]);
  for (const [at, b] of bodies) segments.push([at, b]);
  segments.push([hashPos, Buffer.from(hashBytes)]);
  segments.push([blockPos, Buffer.from(blockBytes)]);
  if (opts.sparse) return { size, segments };
  const out = Buffer.alloc(size);
  for (const [at, b] of segments) b.copy(out, at);
  return out;
}

/// A Blob-like of `size` bytes made of `segments` ([offset, Buffer]) with zeros between: a "huge" archive with
/// no huge allocation. `reads` records every slice that was read (start, length).
function fakeBlob(size, segments, name = 'big.MPQ') {
  const reads = [];
  const make = (start, end) => ({
    size: end - start,
    async arrayBuffer() {
      reads.push([start, end - start]);
      const out = new Uint8Array(end - start);
      for (const [at, b] of segments) {
        const s = Math.max(start, at), e = Math.min(end, at + b.length);
        if (s < e) out.set(b.subarray(s - at, e - at), s - start);
      }
      return out.buffer;
    },
    async text() { return Buffer.from(await this.arrayBuffer()).toString('utf8'); },
    slice(a = 0, b = end - start) {
      const s = Math.min(end, start + Math.max(0, a)), e = Math.min(end, start + Math.max(0, b));
      return make(s, Math.max(s, e));
    },
  });
  const blob = make(0, size);
  blob.name = name;
  blob.reads = reads;
  return blob;
}

/// A File-like over a Buffer (Node has File, but this keeps the tests independent of its version).
function fileOf(buf, name) {
  return fakeBlob(buf.length, [[0, Buffer.from(buf)]], name);
}

/// A small 3.3.5a game folder: [{ path, data }] under `root` ('' = the Data folder's own contents, 'Data' = a
/// Data folder, 'Game' = a game folder holding Data). opts: { locales: ['enUS'], build: 12340 | null (no
/// component file), exe: build for a Wow.exe | null, patches: { 'patch-2.MPQ': {...files} }, extra: {...} }.
function gameFolder(opts = {}) {
  const root = opts.root === undefined ? 'Game' : opts.root;
  const data = root === '' ? '' : root === 'Data' ? 'Data/' : `${root}/Data/`;
  const out = [];
  const add = (p, buf) => out.push({ path: p, data: buf });
  add(`${data}common.MPQ`, buildMpq({ 'World\\Maps\\Azeroth\\Azeroth_30_30.adt': Buffer.from('common azeroth tile'),
    'Textures\\Common.blp': Buffer.from('common-v1'), 'Interface\\Glues\\Shared.blp': Buffer.from('glue') }));
  add(`${data}common-2.MPQ`, buildMpq({ 'Textures\\Common2.blp': Buffer.from('common-2') }));
  add(`${data}expansion.MPQ`, buildMpq({ 'World\\Maps\\Expansion01\\Expansion01_30_30.adt': Buffer.from('outland tile') }));
  if (opts.lichking !== false) {
    add(`${data}lichking.MPQ`, buildMpq({ 'World\\Maps\\Northrend\\Northrend_30_30.adt': Buffer.from('icecrown glacier tile'),
      'World\\Big\\Huge.blp': { data: Buffer.alloc(70000, 7), compress: 'sectors' } }));
  }
  add(`${data}patch.MPQ`, buildMpq({ 'Textures\\Common.blp': Buffer.from('common-v2 (patch)') }));
  for (const [name, files] of Object.entries(opts.patches || { 'patch-2.MPQ': { 'Textures\\Common.blp': Buffer.from('common-v3 (patch-2)') },
    'patch-3.MPQ': { 'Textures\\Common.blp': Buffer.from('common-v4 (patch-3)'), 'Textures\\Gone.blp': { deleted: true } } })) {
    add(`${data}${name}`, buildMpq(files));
  }
  for (const loc of opts.locales || ['enUS']) {
    add(`${data}${loc}/locale-${loc}.MPQ`, buildMpq({ 'DBFilesClient\\Spell.dbc': Buffer.from(`WDBC spell ${loc}`) }));
    add(`${data}${loc}/speech-${loc}.MPQ`, buildMpq({ 'Sound\\Speech.wav': Buffer.from(`speech ${loc}`) }));
    add(`${data}${loc}/patch-${loc}.MPQ`, buildMpq({ 'DBFilesClient\\Spell.dbc': Buffer.from(`WDBC spell ${loc} patched`) }));
    add(`${data}${loc}/patch-${loc}-2.MPQ`, buildMpq({ 'DBFilesClient\\Spell.dbc': Buffer.from(`WDBC spell ${loc} patch-2`) }));
    add(`${data}${loc}/patch-${loc}-3.MPQ`, buildMpq({ 'DBFilesClient\\Spell.dbc': Buffer.from(`WDBC spell ${loc} patch-3`) }));
    if (opts.build !== null) add(`${data}${loc}/component.wow-${loc}.txt`, Buffer.from(`<componentinfo><component name="wow-${loc}" version="${opts.build || 12340}"/></componentinfo>`));
  }
  if (opts.build !== null) add(`${data}component.wow-data.txt`, Buffer.from(`<componentinfo><component name="wow-data" version="${opts.build || 12340}"/></componentinfo>`));
  if (opts.exe && root !== '' && root !== 'Data') add(`${root}/Wow.exe`, exeWithVersion(opts.exe));
  for (const [p, b] of Object.entries(opts.extra || {})) add(data + p, b);
  return out;
}

/// An exe-shaped buffer with a VS_FIXEDFILEINFO naming 3.3.5.<build> (or 1.12.1.<build> with major 1).
function exeWithVersion(build, major = 3, minor = 3, patch = 5) {
  const b = Buffer.alloc(9000, 0x90);
  const at = 6000;
  b.writeUInt32LE(0xfeef04bd, at);
  b.writeUInt32LE(0x00010000, at + 4);
  b.writeUInt32LE(((major << 16) | minor) >>> 0, at + 8);
  b.writeUInt32LE(((patch << 16) | build) >>> 0, at + 12);
  return b;
}

/// A 1.12 Data folder (no common.MPQ): the old archive names.
function vanillaFolder(root = 'Game') {
  const data = root ? `${root}/Data/` : '';
  const out = [];
  for (const n of ['base.MPQ', 'dbc.MPQ', 'fonts.MPQ', 'interface.MPQ', 'misc.MPQ', 'model.MPQ', 'patch.MPQ',
    'sound.MPQ', 'speech.MPQ', 'terrain.MPQ', 'texture.MPQ', 'wmo.MPQ']) out.push({ path: data + n, data: buildMpq({ 'x.txt': Buffer.from(n) }) });
  if (root) out.push({ path: `${root}/WoW.exe`, data: exeWithVersion(5875, 1, 12, 1) });
  return out;
}

module.exports = { buildMpq, fakeBlob, fileOf, gameFolder, vanillaFolder, exeWithVersion };
