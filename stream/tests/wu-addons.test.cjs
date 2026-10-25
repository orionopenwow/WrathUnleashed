// Node tests for "Your addons" (www-files/wu-addons-core.js and the layer in wrath-early.js):
// the zip reader (zip-slip, symlinks, encryption, sizes, checksums), the addon rules (the UI half of
// mods/wu-mod.py), the per-account store over a fake Origin Private File System, and the layered
// body store the client reads (the index merge, a realm folder winning, the wasm start waiting).
//
//   node --test tests/wu-addons.test.cjs          (from the stream folder; no browser needed)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const zlib = require('node:zlib');

const WWW = path.join(__dirname, '..', 'www-files');
const core = () => import(path.join(WWW, 'wu-addons-core.js'));

// -- fake zips ------------------------------------------------------------------------------------

/** entries: [{name, data, method?: 0|8, symlink?, encrypted?, usize?, crc?}] -> Buffer */
function makeZip(entries) {
  const locals = [], centrals = [];
  let off = 0;
  for (const e of entries) {
    const data = Buffer.isBuffer(e.data) ? e.data : Buffer.from(e.data ?? '');
    const method = e.method ?? 8;
    const body = method === 8 ? zlib.deflateRawSync(data) : data;
    const name = Buffer.from(e.name);
    const crc = e.crc ?? zlib.crc32(data);
    const usize = e.usize ?? data.length;
    const flags = (e.encrypted ? 1 : 0) | 0x800;
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(flags, 6); lh.writeUInt16LE(method, 8);
    lh.writeUInt32LE(crc, 14); lh.writeUInt32LE(body.length, 18); lh.writeUInt32LE(usize, 22); lh.writeUInt16LE(name.length, 26);
    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE((3 << 8) | 20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt16LE(flags, 8);
    ch.writeUInt16LE(method, 10); ch.writeUInt32LE(crc, 16); ch.writeUInt32LE(body.length, 20); ch.writeUInt32LE(usize, 24);
    ch.writeUInt16LE(name.length, 28);
    ch.writeUInt32LE(((e.symlink ? 0o120777 : 0o100644) << 16) >>> 0, 38);
    ch.writeUInt32LE(off, 42);
    locals.push(lh, name, body);
    centrals.push(ch, name);
    off += 30 + name.length + body.length;
  }
  const cd = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(off, 16);
  return Buffer.concat([...locals, cd, end]);
}

const TOC = (name, extra = '') => `## Interface: 30300\n## Title: ${name}\n${extra}${name}.lua\n`;
const addonFiles = (name, prefix = '') => [
  { name: `${prefix}${name}/${name}.toc`, data: TOC(name) },
  { name: `${prefix}${name}/${name}.lua`, data: `print("${name}")\n` },
];
const toEntries = (list) => list.map((e) => ({ path: e.name, data: new Uint8Array(Buffer.from(e.data)) }));

// -- a fake Origin Private File System --------------------------------------------------------------

class FakeFile {
  constructor() { this.bytes = new Uint8Array(0); }
  async getFile() {
    const b = this.bytes;
    return { size: b.length, text: async () => Buffer.from(b).toString('utf8'), arrayBuffer: async () => b.slice().buffer };
  }
  async createWritable() {
    const parts = [];
    const self = this;
    return {
      async write(d) { parts.push(typeof d === 'string' ? Buffer.from(d) : Buffer.from(d instanceof ArrayBuffer ? new Uint8Array(d) : d)); },
      async close() { if (self.failNext) { self.failNext = false; throw new Error('disk full'); } self.bytes = new Uint8Array(Buffer.concat(parts)); },
      async abort() {},
    };
  }
}
class FakeDir {
  constructor() { this.kids = new Map(); }
  async getDirectoryHandle(n, o = {}) { return this.get(n, o, FakeDir); }
  async getFileHandle(n, o = {}) { return this.get(n, o, FakeFile); }
  get(n, o, K) {
    let h = this.kids.get(n);
    if (!h) { if (!o.create) { const e = new Error('NotFoundError'); e.name = 'NotFoundError'; throw e; } h = new K(); this.kids.set(n, h); }
    if (!(h instanceof K)) throw new TypeError('TypeMismatchError');
    return h;
  }
  async removeEntry(n) { if (!this.kids.delete(n)) throw new Error('NotFoundError'); }
}

// -- zip reader -------------------------------------------------------------------------------------

test('readZip: stored and deflated files, exact bytes, folders and junk left out', async () => {
  const { readZip } = await core();
  const bin = Buffer.from([0, 1, 2, 0x80, 0xff, 0x7f]);
  const z = makeZip([{ name: 'A/', data: '', method: 0 }, { name: 'A/A.toc', data: TOC('A') }, { name: 'A/a.tga', data: bin, method: 0 },
    { name: '__MACOSX/A/._A.toc', data: 'x' }, { name: 'A/.DS_Store', data: 'x' }]);
  const files = await readZip(z);
  assert.deepEqual(files.map((f) => f.path), ['A/A.toc', 'A/a.tga']);
  assert.equal(Buffer.from(files[0].data).toString(), TOC('A'));
  assert.deepEqual([...files[1].data], [...bin]);
});

test('readZip refuses zip-slip, absolute paths, symlinks, passwords, oversize and lying sizes', async () => {
  const { readZip, LIMITS } = await core();
  const bad = async (entries, re, limits) => assert.rejects(readZip(makeZip(entries), limits), re);
  await bad([{ name: '../evil.lua', data: 'x' }], /unsafe path/);
  await bad([{ name: 'A/../../evil.lua', data: 'x' }], /unsafe path/);
  await bad([{ name: '/etc/passwd', data: 'x' }], /unsafe path/);
  await bad([{ name: 'C:/x.lua', data: 'x' }], /unsafe path/);
  await bad([{ name: 'A\\..\\x.lua', data: 'x' }], /unsafe path/);
  await bad([{ name: 'A/link', data: '/etc/passwd', symlink: true }], /symbolic links/);
  await bad([{ name: 'A/A.lua', data: 'x', encrypted: true }], /password/);
  await bad([{ name: 'A/big.tga', data: Buffer.alloc(2048) }], /larger than/, { ...LIMITS, file: 1024 });
  await bad([{ name: 'A/a.tga', data: Buffer.alloc(800) }, { name: 'A/b.tga', data: Buffer.alloc(800) }], /unpacks to more/, { ...LIMITS, package: 1024 });
  await bad([{ name: 'A/bomb.lua', data: Buffer.alloc(100000), usize: 10 }], /bigger than it says/);
  await bad([{ name: 'A/A.lua', data: 'hello', crc: 1234 }], /checksum/);
  await assert.rejects(readZip(Buffer.from('not a zip at all, just text')), /not a zip/);
  await assert.rejects(readZip(makeZip(Array.from({ length: 5 }, (_, i) => ({ name: `A/${i}.lua`, data: 'x' }))), { ...LIMITS, files: 4 }), /more than 4 files/);
});

// -- the rules --------------------------------------------------------------------------------------

test('validate finds the addon in every layout players send', async () => {
  const { validate } = await core();
  const ok = (list, names) => {
    const v = validate(toEntries(list));
    assert.deepEqual(v.errors, []);
    assert.deepEqual(v.addons.map((a) => a.name).sort(), names);
    for (const a of v.addons) assert.ok(a.files.some((f) => f.path === `${a.name}.toc`), 'paths are inside the addon folder');
    return v;
  };
  ok(addonFiles('Hello'), ['Hello']);                                                // Hello/Hello.toc
  ok([...addonFiles('One'), ...addonFiles('Two'), { name: 'README.md', data: 'hi' }], ['One', 'Two']);
  ok(addonFiles('Hello', 'Hello-1.2/'), ['Hello']);                                  // wrapped in a folder
  ok(addonFiles('Hello', 'Interface/AddOns/'), ['Hello']);                           // a game-folder tree
  ok(addonFiles('Hello', 'pack/Interface/AddOns/'), ['Hello']);
  ok([{ name: 'Solo.toc', data: TOC('Solo') }, { name: 'Solo.lua', data: 'x' }], ['Solo']);  // the addon's files at the top
  const v = ok([{ name: 'dice/mod.json', data: '{}' }, ...addonFiles('Dice', 'dice/ui/'), { name: 'dice/realm/dice.lua', data: 'x' },
    { name: 'dice/README.md', data: 'r' }], ['Dice']);                              // a WU mod package
  assert.match(v.warnings.join(), /realm half/);
  assert.ok(v.skipped.includes('mod.json') && v.skipped.includes('realm/dice.lua'));
});

test('validate passes the Workshop catalog mods as they are', async () => {
  const { validate } = await core();
  const cat = path.join(__dirname, '..', '..', 'mods', 'catalog');
  for (const id of fs.readdirSync(cat)) {
    const entries = [];
    const walk = (d, rel) => {
      for (const n of fs.readdirSync(d)) {
        const p = path.join(d, n);
        if (fs.statSync(p).isDirectory()) walk(p, rel + n + '/');
        else entries.push({ path: `${id}/${rel}${n}`, data: new Uint8Array(fs.readFileSync(p)) });
      }
    };
    walk(path.join(cat, id), '');
    const v = validate(entries);
    assert.deepEqual(v.errors, [], id);
    assert.ok(v.addons.length >= 1, id);
  }
});

test('validate refuses what wu-mod.py refuses, with a reason for each', async () => {
  const { validate } = await core();
  const refused = (list, re) => {
    const v = validate(toEntries(list));
    assert.ok(v.errors.some((e) => re.test(e)), `${re} in ${JSON.stringify(v.errors)}`);
  };
  refused([{ name: 'A/A.lua', data: 'x' }, { name: 'A/notes.txt', data: 'x' }], /no addon found|no A\.toc/);
  refused([{ name: 'A/A.toc', data: '## Interface: 11200\nA.lua\n' }, { name: 'A/A.lua', data: 'x' }], /Interface must be 30300 .*11200/);
  refused([{ name: 'A/A.toc', data: 'A.lua\n' }, { name: 'A/A.lua', data: 'x' }], /Interface must be 30300 .*none/);
  refused([{ name: 'A/A.toc', data: TOC('A', 'Core.lua\n') }, { name: 'A/A.lua', data: 'x' }, { name: 'A/core.lua', data: 'x' }], /Core\.lua.*case differs: core\.lua/);
  refused([...addonFiles('A'), { name: 'A/Icon.blp', data: 'x' }], /Icon\.blp is a game texture/);
  refused([...addonFiles('A'), { name: 'A/Icon.tga', data: 'BLP2xxxx' }], /renamed/);
  refused([...addonFiles('A'), { name: 'A/World.MPQ', data: 'x' }], /archive of game data/);
  refused([...addonFiles('A'), { name: 'A/Map.dbc', data: 'x' }], /game database/);
  refused([...addonFiles('A'), { name: 'A/tool.exe', data: 'MZ' }], /\.exe is not an addon file type/);
  refused([...addonFiles('A'), { name: 'A/page.html', data: '<script>' }], /\.html is not an addon file type/);
  refused([...addonFiles('A'), { name: 'stray.lua', data: 'x' }], /stray\.lua is not inside an addon folder/);
  refused([...addonFiles('A', 'Interface/AddOns/'), { name: 'WTF/Config.wtf', data: 'x' }], /outside Interface\/AddOns/);
  refused([{ name: 'm/mod.json', data: '{}' }, ...addonFiles('A', 'm/ui/'), { name: 'm/bin/x.lua', data: 'x' }], /outside Interface\/AddOns/);
  refused(addonFiles('ForeverUI'), /reserved/);
  refused(addonFiles('Blizzard_Raid'), /reserved/);
  refused(addonFiles('9Lives'), /folder name/);
  refused([...addonFiles('A'), { name: 'A/A.xml', data: '<Ui><Script file="Missing.lua"/></Ui>' }], /points to a file that is not in the folder/);
  refused([...addonFiles('A'), { name: 'A/A.xml', data: '<Ui><Include file="..\\..\\B\\B.xml"/></Ui>' }], /points to a file/);
  const xml = validate(toEntries([...addonFiles('A'), { name: 'A/A.xml', data: '<Ui><Frame></Ui>' }]), { xml: (t) => (t.includes('<Frame>') ? 'mismatched tag' : null) });
  assert.ok(xml.errors.some((e) => /not well formed \(mismatched tag\)/.test(e)));
  const ok = validate(toEntries([...addonFiles('A'), { name: 'A/A.xml', data: '<Ui><Script file="A.lua"/></Ui>' }, { name: 'A/art/x.tga', data: 'TGA' }]));
  assert.deepEqual(ok.errors, []);
});

test('nothing in the validator or the page names the game or its maker', async () => {
  for (const f of ['wu-addons-core.js', 'wu-addons.js']) {
    const src = fs.readFileSync(path.join(WWW, f), 'utf8');
    // every quoted string a player can see; the `blizzard_` folder-prefix rule itself is code, not text
    const strings = src.match(/(['"`])(?:\\.|(?!\1).)*\1/g) || [];
    for (const s of strings) {
      if (s === "'blizzard_'") continue;
      assert.doesNotMatch(s, /World of Warcraft|\bWoW\b|Warcraft|Lich King|Blizzard/i, `${f}: ${s}`);
    }
  }
});

// -- the store --------------------------------------------------------------------------------------

test('store: add, list, load, on/off, replace, remove; per account; survives reopening', async () => {
  const { openStore, validate } = await core();
  const root = new FakeDir();
  const s = await openStore({ root, user: 'Thrall' });
  const [hello] = validate(toEntries(addonFiles('Hello'))).addons;
  const [bye] = validate(toEntries(addonFiles('Bye'))).addons;
  assert.equal((await s.add(hello)).on, true);
  await s.add(bye);
  assert.deepEqual((await s.list()).map((a) => [a.name, a.files, a.on]), [['Bye', 2, true], ['Hello', 2, true]]);
  const loaded = await s.load();
  const h = loaded.find((a) => a.name === 'Hello');
  assert.deepEqual(h.files.map(([p]) => p).sort(), ['Hello.lua', 'Hello.toc']);
  assert.equal(Buffer.from(h.files.find(([p]) => p === 'Hello.lua')[1]).toString(), 'print("Hello")\n');
  assert.equal(await s.setOn('hello', false), true);
  assert.deepEqual((await s.load()).map((a) => a.name), ['Bye']);
  await s.add(hello);                                     // a new copy keeps the switch where it was
  assert.equal((await s.list()).find((a) => a.name === 'Hello').on, false);
  // another account in the same browser sees nothing of it; the same account after a reload does
  assert.deepEqual(await (await openStore({ root, user: 'jaina' })).list(), []);
  assert.deepEqual(await (await openStore({ root })).list(), []);
  const again = await openStore({ root, user: 'THRALL' });
  assert.equal((await again.list()).length, 2);
  assert.equal(await again.remove('Bye'), true);
  assert.equal(await again.remove('Bye'), false);
  assert.deepEqual((await again.list()).map((a) => a.name), ['Hello']);
  const dir = root.kids.get('wu-addons').kids.get('u-thrall');
  assert.ok(!dir.kids.has('bye.pack'), 'the removed pack is deleted');
  assert.ok(dir.kids.has('hello.pack'));
});

test('store: the total cap, a failed write keeps the old list, a broken pack is left out', async () => {
  const { openStore, validate, LIMITS } = await core();
  const root = new FakeDir();
  const s = await openStore({ root, user: 'a', limits: { ...LIMITS, total: 400 } });
  const big = (name, n) => validate(toEntries([...addonFiles(name), { name: `${name}/art.tga`, data: Buffer.alloc(n) }])).addons[0];
  await s.add(big('One', 150));
  await assert.rejects(s.add(big('Two', 150)), /not enough room/);
  await s.add(big('One', 200));                       // replacing counts the new size only
  assert.deepEqual((await s.list()).map((a) => a.name), ['One']);
  const dir = root.kids.get('wu-addons').kids.get('u-a');
  dir.kids.get('index.json').failNext = true;
  await assert.rejects(s.add(big('Small', 10)), /disk full/);
  assert.deepEqual((await s.list()).map((a) => a.name), ['One']);
  dir.kids.get('one.pack').bytes = new Uint8Array(3);   // cut short
  const loaded = await s.load();
  assert.deepEqual(loaded.map((a) => a.name), []);
  assert.deepEqual(loaded.broken, ['One']);
  await assert.rejects(s.add({ name: 'ForeverUI', files: [] }), /not an addon name/);
});

// -- the layer the client reads (wrath-early.js) ----------------------------------------------------

function runEarly({ prefetch, fetchImpl, addonsImport } = {}) {
  const src = fs.readFileSync(path.join(WWW, 'wrath-early.js'), 'utf8');
  const g = {
    console: { warn() {}, log() {} }, URL, TextEncoder, TextDecoder, Map, Set, Promise, JSON, setTimeout, clearTimeout,
    location: { href: 'https://wrath.example/', origin: 'https://wrath.example', pathname: '/', search: '?multitab=1&slimboot=0' },
    navigator: {}, document: { getElementById: () => null, createElement: () => ({}), head: null, documentElement: { appendChild() {} }, addEventListener() {} },
  };
  g.window = g;
  g.globalThis = g;
  if (prefetch) g.__wenilla_prefetch = prefetch;
  g.fetch = fetchImpl || (async () => ({ ok: true }));
  g.__wuAddonsImport = addonsImport || (() => Promise.resolve({ boot: () => null }));
  vm.runInNewContext(src, g);
  return g;
}
const enc = (s) => new TextEncoder().encode(s).buffer;
const dec = (b) => JSON.parse(new TextDecoder().decode(b));

test('layer: the client finds local addons in the name index and reads their files from the store', () => {
  const old = new Map([['dbfilesclient\\map.dbc', enc('kept')]]);
  const g = runEarly({ prefetch: old });
  const store = g.__wenilla_prefetch;
  assert.notEqual(store, old);
  assert.equal(new TextDecoder().decode(store.get('dbfilesclient\\map.dbc')), 'kept', 'what was stored before is kept');
  g.__wuAddonLayer.set([
    { name: 'Hello', files: [['Hello.toc', enc('## Interface: 30300\n')], ['sub/x.lua', enc('x')]] },
    { name: 'WUPings', files: [['WUPings.toc', enc('local copy')]] },
  ]);
  store.set('__index', enc(JSON.stringify(['Interface\\AddOns\\WUPings\\WUPings.toc', 'DBFilesClient\\Map.dbc'])));
  const names = dec(store.get('__index'));
  assert.deepEqual(names, ['Interface\\AddOns\\WUPings\\WUPings.toc', 'DBFilesClient\\Map.dbc',
    'Interface\\AddOns\\Hello\\Hello.toc', 'Interface\\AddOns\\Hello\\sub\\x.lua']);
  assert.equal(store.get('__index'), store.get('__index'), 'merged once per index body');
  assert.equal(new TextDecoder().decode(store.get('interface\\addons\\hello\\sub\\x.lua')), 'x');
  assert.ok(store.has('interface\\addons\\hello\\hello.toc'));
  assert.equal(store.delete('interface\\addons\\hello\\hello.toc'), false, 'a read-once drop never loses a local file');
  assert.ok(store.has('interface\\addons\\hello\\hello.toc'));
  // the realm's own WUPings wins: the local copy is hidden, the server's file is read as usual
  assert.equal(store.get('interface\\addons\\wupings\\wupings.toc'), undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(g.__wuAddonLayer.info())), { loaded: ['Hello'], shadowed: ['WUPings'], merged: true });
  assert.equal(store.get('interface\\addons\\nothere\\x.lua'), undefined);
});

test('layer: no local addons leaves the index untouched; ?localaddons=0 installs nothing', () => {
  const g = runEarly();
  const body = enc('["A"]');
  g.__wenilla_prefetch.set('__index', body);
  assert.equal(g.__wenilla_prefetch.get('__index'), body);
  const src = fs.readFileSync(path.join(WWW, 'wrath-early.js'), 'utf8');
  const off = { console: { warn() {} }, location: { search: '?localaddons=0&multitab=1' }, navigator: {}, document: {} };
  off.window = off;
  vm.runInNewContext(src, off);
  assert.equal(off.__wuAddonLayer, undefined);
  assert.equal(off.__wenilla_prefetch, undefined);
});

test('layer: the client download waits for the local addons to be read, other fetches do not', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const g = runEarly({ fetchImpl: async (u) => ({ ok: true, url: String(u) }), addonsImport: () => gate.then(() => ({ boot: () => 'booted' })) });
  let wasmDone = false;
  const wasm = g.fetch('./wenilla_bg.wasm').then((r) => { wasmDone = true; return r; });
  const other = await g.fetch('/data/__index');
  assert.equal(other.url, '/data/__index');
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(wasmDone, false);
  release();
  assert.equal((await wasm).url, './wenilla_bg.wasm');
  assert.equal(await g.__wuAddonsReady, 'booted');
});
