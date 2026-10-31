// The addon marketplace in Mods › Discover (ui/market.js) in Chromium with a fake Tauri core: upstream addons
// (installed from the author's repo) get their own card with the credit line, licence chip, "Works on" badge and
// Source link; the sub-category chips and the "Works on Wrath Unleashed" filter; search by tags and folders; the
// detail view (needs, can't go with, size and files, whole-interface warning, last reviewed); Install that offers
// what an addon needs first, refuses one beside a conflicting install, warns for a whole-UI replacement; the
// update dot; text shown as text. Screenshots go to $MARKET_SHOTS when set.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/market.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const SHOTS = process.env.MARKET_SHOTS || '';
const C1 = '0123456789abcdef0123456789abcdef01234567';

const U = (slug, name, extra) => Object.assign({
  id: 'up:' + slug, source: 'upstream', name, description: `${name} does useful things. More words here.`, category: 'addons',
  builds: ['3.3.5a'], author: 'alice', author_url: 'https://github.com/alice', licence: 'MIT', licence_source: 'LICENSE',
  repo: `https://github.com/alice/${name.replace(/\W/g, '')}`, page: `https://github.com/alice/${name.replace(/\W/g, '')}`,
  credits: `${name} by alice · MIT · Installs from the author's GitHub`, stars: null, last_push: '', version: '1.2.3',
  kind: 'ui', permissions: null, on_wrath: null, download: null, sha256: null, size: 2_400_000, file_count: 120,
  tags: ['unit-frames'], addons: [name.replace(/\W/g, '')], requires: [], conflicts: [], replaces_ui: false, native: false,
  blp: 'none', mirror_allowed: true, review: { by: 'owner', at: '2026-10-31T09:00:00Z', notes: '' },
  compat: { realm: 'Wrath Unleashed', status: 'untested', checked_at: '' },
  install: { from: 'commit-archive', url: `https://github.com/alice/x/archive/${C1}.zip`, rev: C1, sha256: null, size: 2_400_000,
    file_count: 120, strip_prefix: '', folders: {}, files_digest: 'ab'.repeat(32) },
}, extra || {});
const PK = { id: 'mod:pings', source: 'packaged', name: 'Pings', description: 'Pings on the map.', category: 'addons', builds: ['3.3.5a'],
  author: 'Leyline', author_url: '', licence: 'MIT', repo: '', page: '', credits: 'Pings', stars: null, last_push: '', version: '0.1.0',
  kind: 'ui', permissions: [], on_wrath: true, download: 'https://play.openvanilla.app/wrath/mods/pings/download', sha256: 'ab'.repeat(32), size: 1000 };
const CATALOG = { categories: [{ id: 'addons', name: 'Addons and UI', line: '', icon: '' }, { id: 'tools', name: 'Tools', line: '', icon: '' }],
  projects: [
    U('elvui', 'ElvUI', { tags: ['full-ui'], replaces_ui: true, licence: '', mirror_allowed: false, author: 'ElvUI-WotLK',
      description: 'A complete replacement interface.', compat: { realm: 'Wrath Unleashed', status: 'works', checked_at: '2026-10-31T10:00:00Z' } }),
    U('spec-switch', 'Spec Switch', { tags: ['full-ui'], requires: ['up:elvui'] }),
    U('skada', 'Skada', { tags: ['meters'], blp: 'author-art', mirror_allowed: false, compat: { realm: 'Wrath Unleashed', status: 'works', checked_at: '' } }),
    U('plates', 'Plates', { tags: ['nameplates'], conflicts: ['up:plates-old'], addons: ['PlateBuffs'] }),
    U('plates-old', 'Plates Old', { tags: ['nameplates'], conflicts: ['up:plates'], addons: ['PlateBuffs'] }),
    U('evil', '<img src=x onerror="window.__pwned=1">', { tags: ['chat'] }),
    PK, Object.assign({}, PK, { id: 'mod:hud', name: 'Hud', category: 'tools', on_wrath: false }),
  ], from_cache: false, saved_at: 1, error: null };

const FAKE = ({ catalog, installedMods }) => {
  const calls = (window.__calls = []);
  try {
    localStorage.setItem('leyline.page', 'discover');
    localStorage.removeItem('leyline.mkSub');
    localStorage.removeItem('leyline.mkWorks');
  } catch (_) { /* fine */ }
  let mods = installedMods || [];
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [
          { id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: '' }],
        selected_client: 'c335a-1', selected_realm: 'play.openvanilla.app', wine: { enabled: true, command: 'wine', prefix: '' },
        count_installs: true },
        official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'mods_catalog': return catalog;
      case 'mods_ranked': throw 'offline';
      case 'mods_installed': return { client: 'c335a-1', build: '3.3.5a', mods };
      case 'mod_install': {
        const p = catalog.projects.find((x) => x.id === args.project);
        mods = mods.filter((m) => m.key !== p.id).concat([{ key: p.id, name: p.name, version: p.version, source: p.source, update: null,
          in_catalog: true, enabled: true, files: [], addons: p.addons || [], patches: [] }]);
        return { key: p.id, name: p.name, version: p.version, warnings: [], kept: [] };
      }
      case 'deep_link_take': return null;
      case 'open_url': return null;
      case 'mods_updates': return [];
      case 'realms_list': return { realms: [], network: { realms: 0, players: 0, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'host_info': return { dir: '', is_kit: false, problems: [], kit: null, seeds: [], realm: null };
      case 'launcher_update_state': return { mode: 'auto', checking: false, downloading: false, ready: null, info: null };
      case 'modes_list': return { modes: [], from_cache: false, builtin: false, saved_at: null, error: null };
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts = {}, viewport) {
  const page = await browser.newPage({ viewport: viewport || { width: 1280, height: 860 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, Object.assign({ catalog: CATALOG }, opts));
  await page.goto(INDEX);
  await page.waitForFunction(() => document.querySelectorAll('#cat-grid .mod-card').length > 0);
  return { page, errors };
}
const names = (page) => page.$$eval('#cat-grid .mod-card .name', (n) => n.map((x) => x.textContent));
const calls = (page, name) => page.evaluate((n) => window.__calls.filter(([c]) => c === n).map(([, a]) => a), name);
const card = (page, id) => page.locator(`#cat-grid .mod-card[data-id="${id}"]`);
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, name + '.png') }); };

test('upstream cards: credit line, licence chip, badge, Source link, text as text', async () => {
  const { page, errors } = await open();
  await shot(page, 'discover-dark');
  const elv = card(page, 'up:elvui');
  assert.equal(await elv.locator('.mk-credit').textContent(), "ElvUI-WotLK·Installs from the author's GitHub");
  assert.equal(await elv.locator('.mk-lic').textContent(), 'No licence');
  assert.equal(await elv.locator('.mk-ui-tag').textContent(), 'Whole interface');
  assert.equal(await elv.locator('.mk-badge').textContent(), 'Works on Wrath Unleashed');
  assert.equal(await card(page, 'up:skada').locator('.mk-lic').textContent(), 'MIT');
  assert.equal(await card(page, 'up:spec-switch').locator('.mk-badge').count(), 0, 'untested: no badge');
  assert.equal(await elv.locator('.acts .btn').allTextContents().then((t) => t.join('|')), 'Source|Install');
  await elv.locator('.mk-src').click();
  assert.deepEqual((await calls(page, 'open_url')).slice(-1)[0], { url: 'https://github.com/alice/ElvUI' });
  assert.equal(await card(page, 'mod:pings').locator('.mk-credit').count(), 0, 'packaged mods keep their own card');
  assert.equal(await page.evaluate(() => window.__pwned), undefined);
  assert.ok((await names(page)).includes('<img src=x onerror="window.__pwned=1">'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('sub-category chips, Works on filter, search by tag', async () => {
  const { page, errors } = await open();
  const chips = await page.$$eval('#mk-bar .chip-btn', (b) => b.map((x) => x.textContent));
  assert.deepEqual(chips, ['All addons', 'Full interfaces', 'Nameplates', 'Meters', 'Chat', 'Works on Wrath Unleashed'], 'only tags in use, in order');
  await page.click('#mk-bar .chip-btn:text-is("Nameplates")');
  await page.waitForFunction(() => document.querySelectorAll('#cat-grid .mod-card').length === 2);
  assert.deepEqual((await names(page)).sort(), ['Plates', 'Plates Old']);
  assert.equal(await page.getAttribute('#mk-bar .chip-btn:text-is("Nameplates")', 'aria-pressed'), 'true');
  await page.click('#mk-bar .chip-btn:text-is("All addons")');
  await page.click('#mk-bar .mk-works-chip');
  await page.waitForFunction(() => document.querySelectorAll('#cat-grid .mod-card').length === 3);
  assert.deepEqual((await names(page)).sort(), ['ElvUI', 'Pings', 'Skada'], 'reviewed on the realm (and our own mods on it)');
  await page.click('#mk-bar .mk-works-chip');
  await page.fill('#cat-q', 'meters');
  await page.waitForFunction(() => document.querySelectorAll('#cat-grid .mod-card').length === 1);
  assert.deepEqual(await names(page), ['Skada'], 'search reads the sub-category');
  await page.fill('#cat-q', 'platebuffs');
  await page.waitForFunction(() => document.querySelectorAll('#cat-grid .mod-card').length === 2);
  await page.fill('#cat-q', '');
  await page.selectOption('#cat-cat', 'cat:tools');
  await page.waitForFunction(() => document.getElementById('mk-bar').hidden);
  assert.deepEqual(errors, []);
  await page.close();
});

test('detail view: facts, warnings, Install from it', async () => {
  const { page, errors } = await open();
  await card(page, 'up:elvui').locator('.name').click();
  await page.waitForSelector('#mk-dlg[open]');
  await shot(page, 'detail-elvui');
  const facts = await page.$$eval('#mk-dlg .mk-facts dt', (d) => d.map((x) => x.textContent));
  assert.deepEqual(facts, ['Made by', 'Licence', 'Comes from', 'Version', 'Size', 'Addon folders', 'Last reviewed', 'On Wrath Unleashed']);
  assert.match(await page.textContent('#mk-dlg'), /Replaces your whole interface\. It may conflict with the Leyline UI\./);
  assert.match(await page.textContent('#mk-dlg .mk-facts'), /2\.3 MB, 120 files/);
  assert.match(await page.textContent('#mk-dlg .mk-facts'), /Licence not stated/);
  await page.click('#mk-dlg .btn:text-is("Close")');
  await card(page, 'up:spec-switch').click({ position: { x: 20, y: 20 } });
  await page.waitForSelector('#mk-dlg[open]');
  assert.match(await page.textContent('#mk-dlg .mk-facts'), /NeedsElvUI/);
  await page.click('#mk-dlg .btn:text-is("Close")');
  await card(page, 'up:skada').locator('.name').click();
  assert.match(await page.textContent('#mk-dlg .mk-facts'), /Uses the author's own textures/);
  await page.click('#mk-dlg .btn:text-is("Install")');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'mod_install' && a.project === 'up:skada'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('Install: needs first, conflicts refused, whole-UI warning, update dot', async () => {
  const { page, errors } = await open();
  // Spec Switch needs ElvUI (a whole-UI replacement): offered first, then the warning for ElvUI itself
  await card(page, 'up:spec-switch').locator('.acts .btn.primary').click();
  await page.waitForSelector('#mk-dlg[open]');
  await shot(page, 'needs');
  assert.match(await page.textContent('#mk-dlg h3'), /Spec Switch needs another addon/);
  assert.deepEqual(await page.$$eval('#mk-dlg .mk-list li', (l) => l.map((x) => x.textContent)), ['ElvUI']);
  await page.click('#mk-dlg .btn:text-is("Install all")');
  await page.waitForFunction(() => window.__calls.filter(([c]) => c === 'mod_install').length === 2);
  assert.deepEqual((await calls(page, 'mod_install')).map((a) => a.project), ['up:elvui', 'up:spec-switch']);
  // ElvUI on its own: the whole-interface warning, and No means nothing installs
  const fresh = await open();
  await card(fresh.page, 'up:elvui').locator('.acts .btn.primary').click();
  await fresh.page.waitForSelector('#mk-dlg[open]');
  assert.match(await fresh.page.textContent('#mk-dlg'), /replaces your whole interface/);
  await fresh.page.click('#mk-dlg .btn:text-is("Cancel")');
  assert.equal((await calls(fresh.page, 'mod_install')).length, 0);
  await fresh.page.close();
  // A conflicting addon already in: refused before anything downloads
  const withOld = await open({ installedMods: [{ key: 'up:plates-old', name: 'Plates Old', version: '1', source: 'upstream', update: '1.2.3',
    in_catalog: true, enabled: true, files: [], addons: ['PlateBuffs'], patches: [] }] });
  await withOld.page.waitForSelector('#cat-grid .mod-card[data-id="up:plates-old"] .mk-dot');
  assert.equal(await card(withOld.page, 'up:plates-old').locator('.acts .btn.primary').textContent(), 'Update');
  await card(withOld.page, 'up:plates').locator('.acts .btn.primary').click();
  await withOld.page.waitForSelector('#mk-dlg[open]');
  assert.match(await withOld.page.textContent('#mk-dlg h3'), /can't go in beside Plates Old/);
  await withOld.page.click('#mk-dlg .btn:text-is("OK")');
  assert.equal((await calls(withOld.page, 'mod_install')).length, 0);
  await shot(withOld.page, 'update-dot');
  await withOld.page.close();
  assert.deepEqual(errors, []);
  await page.close();
});

test('light look and a narrow window', async () => {
  const { page, errors } = await open({}, { width: 900, height: 900 });
  await page.evaluate(() => document.documentElement.setAttribute('data-base', 'light'));
  await shot(page, 'discover-light-narrow');
  const over = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  assert.equal(over, false, 'no sideways scroll');
  assert.deepEqual(errors, []);
  await page.close();
});
