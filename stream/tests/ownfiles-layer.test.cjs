// Node tests for the player's own 3.3.5a game folder (www-files/chain.js + mpq.js, the reader the page's worker
// runs) and the layer over the streamed slice, on real (small) MPQ archives made by mpq-fixture.cjs:
//   * a game folder, its Data folder, the Data folder's contents, loose archives (refused with a clear message);
//   * locale folders (enUS, enGB, deDE, two at once) and the patch order (patch, patch-N, patch-xxXX, patch-xxXX-N,
//     patch-10 ignored, a letter patch last), delete markers;
//   * the build read from the files (component.wow-data.txt, the game's exe across a 4 MiB read boundary), a 1.12,
//     a 2.4.3 and a wrong-build folder refused;
//   * a 3.9 GB archive read with small slices only (no whole-file copies);
//   * the layer: slice names pass to the server, the folder answers the rest, a name in neither is a 404 with no
//     request, /data/__index is the union, a slice name the server failed comes from the folder;
//   * what a drop is (game folder or addon), and the Lua chunk the page hands the game (run through lua5.1).
//
//   node --test stream/tests/ownfiles-layer.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const M = require('../www-files/mpq.js');
const C = require('../www-files/chain.js');
const F = require('./mpq-fixture.cjs');

const entriesOf = (list) => list.map((e) => ({ path: e.path, file: F.fileOf(e.data, e.path.split('/').pop()) }));
const text = (u8) => Buffer.from(u8).toString('utf8');

async function openChain(list, opts = {}) {
  const entries = entriesOf(list);
  const listing = C.listingFromFiles(entries, 'Game', opts);
  return { chain: await C.Chain.open(listing), entries };
}

test('the fixture writer makes archives the reader opens', async () => {
  const buf = F.buildMpq({ 'A\\b.txt': 'hello', 'Big.bin': { data: Buffer.alloc(20000, 3), compress: 'sectors' }, 'Gone.blp': { deleted: true } });
  const a = await M.MpqArchive.open(M.bytesSource(new Uint8Array(buf)), 't.MPQ');
  assert.equal(text(await a.readFile('a/B.TXT')), 'hello');
  assert.equal((await a.readFile('Big.bin')).length, 20000);
  assert.ok(a.isDeleteMarker('Gone.blp'));
  assert.match(text(await a.readFile('(listfile)')), /A\\b\.txt/);
});

for (const root of ['Game', 'Data', '']) {
  test(`validate: ${root === 'Game' ? 'the game folder' : root === 'Data' ? 'its Data folder' : "the Data folder's contents"}`, async () => {
    const entries = entriesOf(F.gameFolder({ root }));
    const r = await C.validate(entries, root || 'Data');
    assert.equal(r.ok, true, r.errors.join('; '));
    assert.equal(r.locale, 'enUS');
    assert.equal(r.build.build, 12340);
    assert.deepEqual(r.order, ['enUS/speech-enUS.MPQ', 'enUS/locale-enUS.MPQ', 'common-2.MPQ', 'common.MPQ', 'lichking.MPQ',
      'expansion.MPQ', 'enUS/patch-enUS.MPQ', 'patch.MPQ', 'enUS/patch-enUS-2.MPQ', 'enUS/patch-enUS-3.MPQ', 'patch-2.MPQ', 'patch-3.MPQ']);
  });
}

test('the chain: the highest patch wins, delete markers hide, locale patches order', async () => {
  const { chain } = await openChain(F.gameFolder());
  assert.equal(text(await chain.read('Textures\\Common.blp')), 'common-v4 (patch-3)');
  assert.equal(text(await chain.read('DBFilesClient\\Spell.dbc')), 'WDBC spell enUS patch-3');
  assert.equal(text(await chain.read('textures/common2.BLP')), 'common-2');
  await assert.rejects(chain.read('Textures\\Gone.blp'), (e) => e.code === 'notfound' || e.code === 'deleted');
  await assert.rejects(chain.read('Nope\\Nothing.blp'), (e) => e.code === 'notfound');
  assert.equal((await chain.read('World\\Big\\Huge.blp')).length, 70000);
});

test('patch-xx order: patch-10 is not a patch-? match, a letter patch sorts last', async () => {
  const patches = {
    'patch-2.MPQ': { 'T.blp': '2' }, 'patch-3.MPQ': { 'T.blp': '3' }, 'patch-10.MPQ': { 'T.blp': '10' }, 'patch-A.MPQ': { 'T.blp': 'A' },
  };
  const { chain } = await openChain(F.gameFolder({ patches }));
  assert.ok(!chain.order.includes('patch-10.MPQ'));
  assert.equal(chain.order[chain.order.length - 1], 'patch-A.MPQ');
  assert.equal(text(await chain.read('T.blp')), 'A');
});

for (const loc of ['enGB', 'deDE', 'frFR', 'esES', 'ruRU', 'koKR']) {
  test(`locale folder ${loc}`, async () => {
    const entries = entriesOf(F.gameFolder({ locales: [loc] }));
    const r = await C.validate(entries, 'Game');
    assert.equal(r.ok, true, r.errors.join('; '));
    assert.equal(r.locale, loc);
    assert.ok(r.order.includes(`${loc}/patch-${loc}-3.MPQ`));
    const { chain } = await openChain(F.gameFolder({ locales: [loc] }));
    assert.equal(text(await chain.read('DBFilesClient\\Spell.dbc')), `WDBC spell ${loc} patch-3`);
  });
}

test('two language folders: the player\'s language, else enUS, with a warning', async () => {
  const list = F.gameFolder({ locales: ['deDE', 'enUS'] });
  let r = await C.validate(entriesOf(list), 'Game');
  assert.equal(r.ok, true);
  assert.equal(r.locale, 'enUS');
  assert.match(r.warnings.join(' '), /2 language folders \(deDE, enUS\): using enUS/);
  r = await C.validate(entriesOf(list), 'Game', { locale: 'deDE' });
  assert.equal(r.locale, 'deDE');
  const { chain } = await openChain(list, { locale: 'deDE' });
  assert.equal(chain.locale, 'deDE');
  assert.equal(text(await chain.read('DBFilesClient\\Spell.dbc')), 'WDBC spell deDE patch-3');
});

test('no language folder: refused, plainly', async () => {
  const list = F.gameFolder().filter((e) => !/\/enUS\//.test(e.path));
  const r = await C.validate(entriesOf(list), 'Game');
  assert.equal(r.ok, false);
  assert.match(r.errors.join(' '), /no locale folder \(enUS, enGB, deDE/);
});

test('the build comes from the files, not the folder name', async () => {
  // component.wow-data.txt says 8606 inside a folder named like a 3.3.5a one
  let r = await C.validate(entriesOf(F.gameFolder({ root: 'World 3.3.5a (12340)', build: 8606 })), 'World 3.3.5a (12340)');
  assert.equal(r.ok, false);
  assert.match(r.errors.join(' '), /build 8606.*needs 3\.3\.5a, build 12340/);
  // no component files, the game exe says 12340
  r = await C.validate(entriesOf(F.gameFolder({ build: null, exe: 12340 })), 'Game');
  assert.equal(r.ok, true, r.errors.join('; '));
  assert.equal(r.build.build, 12340);
  assert.equal(r.build.version, '3.3.5.12340');
  // the exe says 3.3.3 (11723)
  r = await C.validate(entriesOf(F.gameFolder({ build: null, exe: 11723 })), 'Game');
  assert.equal(r.ok, false);
  assert.match(r.errors.join(' '), /build 11723/);
  // nothing to read the build from: allowed, with a warning
  r = await C.validate(entriesOf(F.gameFolder({ build: null })), 'Game');
  assert.equal(r.ok, true);
  assert.match(r.warnings.join(' '), /Could not read the build number/);
});

test('the exe is read in 4 MiB slices, the version found across a slice boundary', async () => {
  const sig = F.exeWithVersion(12340).subarray(6000, 6052);
  const at = 4 * 1024 * 1024 - 24;
  const blob = F.fakeBlob(9 * 1024 * 1024, [[at, Buffer.from(sig)]], 'Wow.exe');
  const v = await C.exeVersion(blob);
  assert.deepEqual(v, { build: 12340, version: '3.3.5.12340' });
  assert.ok(blob.reads.every(([, len]) => len <= 4 * 1024 * 1024 + 64), JSON.stringify(blob.reads));
});

test('a 1.12 folder on the 3.3.5a page: refused, and it says so', async () => {
  for (const root of ['Game', '']) {
    const r = await C.validate(entriesOf(F.vanillaFolder(root)), 'Game');
    assert.equal(r.ok, false);
    assert.match(r.errors.join(' '), /1\.12 game folder.*needs a 3\.3\.5a game folder \(build 12340\)/);
    assert.doesNotMatch(r.errors.join(' '), /warcraft|blizzard|lich king|\bwow\b/i);
  }
});

test('a 2.4.3 folder (no lichking.MPQ): refused', async () => {
  const r = await C.validate(entriesOf(F.gameFolder({ lichking: false, build: null })), 'Game');
  assert.equal(r.ok, false);
  assert.match(r.errors.join(' '), /2\.4\.3/);
});

test('loose archives: one archive is not the game', async () => {
  const one = [{ path: 'patch-3.MPQ', data: F.buildMpq({ 'x': 'y' }) }];
  const r = await C.validate(entriesOf(one), 'Data');
  assert.equal(r.ok, false);
  assert.match(r.errors.join(' '), /One archive is not enough/);
  // the Data folder's archives and its enUS folder dropped together: the game
  const all = F.gameFolder({ root: '' });
  const r2 = await C.validate(entriesOf(all), 'Data');
  assert.equal(r2.ok, true);
});

test('a 3.9 GB archive: tables and files read in small slices, never the whole file', async () => {
  const big = F.buildMpq({ 'World\\Maps\\Northrend\\Northrend_31_31.adt': Buffer.alloc(150000, 9), 'Small.txt': 'far away' },
    { dataOffset: 3.9e9, sparse: true });
  const blob = F.fakeBlob(big.size, big.segments, 'lichking.MPQ');
  assert.ok(blob.size > 3.8e9);
  const list = F.gameFolder().filter((e) => !/lichking\.MPQ$/.test(e.path));
  const entries = entriesOf(list);
  entries.push({ path: 'Game/Data/lichking.MPQ', file: blob });
  const chain = await C.Chain.open(C.listingFromFiles(entries, 'Game'));
  const server = new C.LayerServer(chain, Buffer.from(JSON.stringify([])));
  await server.index();
  const r = await server.handle('GET', '/data/World%5CMaps%5CNorthrend%5CNorthrend_31_31.adt');
  assert.equal(r.status, 200);
  assert.equal(r.body.length, 150000);
  assert.equal(text((await server.handle('GET', '/data/Small.txt')).body), 'far away');
  const total = blob.reads.reduce((a, [, n]) => a + n, 0);
  const max = Math.max(...blob.reads.map(([, n]) => n));
  assert.ok(max <= 1024 * 1024 + 16, `largest read ${max}`);
  assert.ok(total < 4 * 1024 * 1024, `read ${total} bytes of a ${blob.size} byte archive`);
});

test('the layer: slice first, the folder for the rest, the union index, 404 for neither', async () => {
  const { chain } = await openChain(F.gameFolder());
  const slice = ['Textures\\Common.blp', 'Interface\\AddOns\\ForeverUI\\FUI.lua', 'DBFilesClient\\Spell.dbc'];
  const server = new C.LayerServer(chain, Buffer.from(JSON.stringify(slice)));
  const idx = JSON.parse(text((await server.handle('GET', '/data/__index')).body));
  for (const n of slice) assert.ok(idx.includes(n), n);
  assert.ok(idx.includes('World\\Maps\\Northrend\\Northrend_30_30.adt'));
  assert.equal(idx.filter((n) => C.indexKey(n) === C.indexKey('Textures\\Common.blp')).length, 1, 'no name twice');
  assert.ok(!idx.includes('Textures\\Gone.blp'), 'a deleted name is not listed');
  assert.equal(server.counts.slice, 3);
  assert.ok(server.counts.ownOnly > 3 && server.counts.own > server.counts.ownOnly);

  assert.deepEqual(await server.handle('GET', '/data/Textures%5CCommon.blp'), { pass: true });
  assert.deepEqual(await server.handle('GET', '/data/textures/common.BLP'), { pass: true }, 'any case, / or \\');
  assert.deepEqual(await server.handle('GET', '/data/Interface%5CAddOns%5CForeverUI%5CFUI.lua'), { pass: true }, 'realm-only content');
  assert.deepEqual(await server.handle('GET', '/data/__tier/index.json'), { pass: true });
  const own = await server.handle('GET', '/data/World%5CMaps%5CNorthrend%5CNorthrend_30_30.adt');
  assert.equal(own.status, 200);
  assert.equal(text(own.body), 'icecrown glacier tile');
  assert.equal(own.source, 'own');
  const head = await server.handle('HEAD', '/data/World%5CMaps%5CNorthrend%5CNorthrend_30_30.adt');
  assert.equal(head.status, 200);
  assert.equal(head.body, null);
  const none = await server.handle('GET', '/data/Nowhere%5CNothing.m2');
  assert.equal(none.status, 404, 'in neither source: a 404, no request');
  // the server failed a slice name: the folder's copy
  const forced = await server.handle('GET', '/data/Textures%5CCommon.blp', { own: true });
  assert.equal(text(forced.body), 'common-v4 (patch-3)');
  const forcedMissing = await server.handle('GET', '/data/Interface%5CAddOns%5CForeverUI%5CFUI.lua', { own: true });
  assert.equal(forcedMissing.status, 404);
  assert.equal((await server.handle('POST', '/data/World%5CMaps%5CNorthrend%5CNorthrend_30_30.adt')).status, 405);
});

test('the layer with no slice list: the folder first, a miss goes to the server', async () => {
  const { chain } = await openChain(F.gameFolder());
  const server = new C.LayerServer(chain, null);
  assert.equal((await server.handle('GET', '/data/Textures%5CCommon.blp')).status, 200);
  assert.deepEqual(await server.handle('GET', '/data/Interface%5CAddOns%5CForeverUI%5CFUI.lua'), { pass: true });
  const junk = new C.LayerServer(chain, Buffer.from('not json'));
  assert.deepEqual(await junk.handle('GET', '/data/Nowhere.m2'), { pass: true });
});

test('the layer ignores the loose Interface folder beside a game folder', async () => {
  const list = F.gameFolder();
  list.push({ path: 'Game/Interface/AddOns/Mine/Mine.toc', data: Buffer.from('## Interface: 30300') });
  const { chain } = await openChain(list);
  const server = new C.LayerServer(chain, Buffer.from('[]'));
  assert.equal((await server.handle('GET', '/data/Interface%5CAddOns%5CMine%5CMine.toc')).status, 404);
  const idx = JSON.parse(text((await server.handle('GET', '/data/__index')).body));
  assert.ok(!idx.some((n) => /Mine\.toc/.test(n)));
});

test('what a drop is: a game folder or an addon', () => {
  const d = (name, kids) => ({ name, dir: true, kids });
  const f = (name) => ({ name, dir: false });
  assert.equal(C.classifyDrop([d('World of Games 3.3.5a', ['Data', 'Wow.exe', 'Interface', 'WTF'])]), 'game');
  assert.equal(C.classifyDrop([d('Data', ['common.MPQ', 'enUS', 'patch.MPQ'])]), 'game');
  assert.equal(C.classifyDrop([d('anything', ['common.MPQ', 'lichking.MPQ'])]), 'game', 'a Data folder by another name');
  assert.equal(C.classifyDrop([f('common.MPQ'), f('lichking.MPQ'), d('enUS', ['locale-enUS.MPQ'])]), 'game', 'the Data folder\'s contents');
  assert.equal(C.classifyDrop([f('patch-3.MPQ')]), 'game', 'a loose archive (then refused with a message)');
  assert.equal(C.classifyDrop([d('Old', ['dbc.MPQ', 'model.MPQ'])]), 'game', 'a 1.12 folder (then refused with a message)');
  assert.equal(C.classifyDrop([f('Hello.zip')]), 'addon');
  assert.equal(C.classifyDrop([d('Hello', ['Hello.toc', 'Hello.lua'])]), 'addon');
  assert.equal(C.classifyDrop([d('Interface', ['AddOns'])]), 'addon');
  assert.equal(C.classifyDrop([f('notes.txt')]), 'unknown');
});

test('the Lua chunk the page hands the game is valid Lua and sets WUUI_GAMEFOLDER', async () => {
  const url = 'file://' + path.join(__dirname, '..', 'www-files', 'wrath-page.js');
  const quiet = console.warn; console.warn = () => {};
  const page = await import(url);
  console.warn = quiet;
  const st = { mounted: true, build: 12340, label: 'My "Data" ]]\n folder', counts: { ownOnly: 4242 }, realm: 'lifted', keepsFolders: true };
  const chunk = page.gameFolderLua(st, true);
  const lua = `WUUI_GAMEFOLDER_ASK = "pick"
local f = assert(loadstring(${JSON.stringify(chunk)}))
local got = f()
local s = WUUI_GAMEFOLDER
print(got, WUUI_GAMEFOLDER_ASK == nil, s.page, s.on, s.build, s.label, s.ownOnly, s.realm, s.keeps, s.allowed)`;
  const out = execFileSync('lua5.1', ['-e', lua], { encoding: 'utf8' }).trim().split('\t');
  assert.deepEqual(out, ['pick', 'true', 'true', 'true', '12340', 'My ?Data? ??? folder', '4242', 'lifted', 'true', 'true']);
  const off = page.gameFolderLua({ mounted: false, realm: 'weird' }, false);
  const out2 = execFileSync('lua5.1', ['-e', `local r = assert(loadstring(${JSON.stringify(off)}))(); local s = WUUI_GAMEFOLDER; print(r, s.on, s.build, s.label, s.realm, s.allowed)`], { encoding: 'utf8' }).trim().split('\t');
  assert.deepEqual(out2, ['nil', 'false', 'nil', 'nil', 'unknown', 'false']);
});
