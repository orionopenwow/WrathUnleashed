// The Leyline addons (ui/addons.js over src-tauri/src/addons.rs) in Chromium with a fake Tauri core: the row on a 3.3.5a
// client card (none on other builds) with Install / Update / Remove and its status, "you already have some of these"
// (asks, then installs with replace), a download that does not check out (says so, nothing installed), Mods › Our
// addons, the setup step when a 3.3.5a client is added, the PLAY offer on the Dalaran Hangout (Install and play, Play
// without, Don't ask again; never on another realm, never twice after Don't ask again), Settings (update on start,
// the offer), and update on start.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/addons.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const PICTURE = path.join(__dirname, '..', 'ui', 'art', 'leyline-bg.webp');

const FAKE = (o) => {
  const calls = (window.__calls = []);
  try { localStorage.setItem('leyline.page', o.page || 'clients'); localStorage.setItem('leyline.mode', 'online'); } catch (_) { /* fine */ }
  const clients = o.clients;
  const st = { version: 'test', settings: { clients, selected_client: clients[0] ? clients[0].id : null, selected_realm: 'play.openvanilla.app',
    wine: { enabled: false, command: 'wine', prefix: '' }, count_installs: true }, official_realm: 'play.openvanilla.app',
    browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
  const pack = o.noPack ? null : { format: 1, name: 'Leyline addons', version: '2026.1031.900', build: '3.3.5a', download: 'x', sha256: 'a'.repeat(64),
    addons: [{ name: 'OVArmory', title: 'Leyline Armory', version: '0.1' }, { name: 'OVQoL', title: 'OVQoL', version: '1.0.0' },
      { name: 'WrathUnleashedUI', title: 'Leyline UI', version: '' }], files: {} };
  const prefs = Object.assign({ auto_update: true, dont_ask: false }, o.prefs || {});
  const ad = {};   // client id -> { installed, update, foreign, backups }
  for (const c of clients) ad[c.id] = Object.assign({ installed: null, update: false, foreign: [], backups: [], missing: [] }, (o.addons || {})[c.id] || {});
  let replaceAsked = false;
  const status = () => ({ pack, from_cache: false, error: null, prefs: Object.assign({}, prefs), clients: clients.map((c) => Object.assign({
    client: c.id, name: c.name, build: c.build, supported: c.build === '3.3.5a', installed_at: 1 }, c.build === '3.3.5a' ? ad[c.id] : { installed: null, update: false, foreign: [], backups: [], missing: [] })) });
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return JSON.parse(JSON.stringify(st));
      case 'select': return null;
      case 'add_client': {
        const p = { id: 'c335a-2', name: 'New Wrath', path: args.path, build: '3.3.5a', realmlist: '' };
        clients.push(p); ad[p.id] = { installed: null, update: false, foreign: [], backups: [], missing: [] };
        return { profile: p, detection: { build: '3.3.5a', build_label: '3.3.5a (12340)', detected_by: 'exe_version', complete: true, missing: [] } };
      }
      case 'check_client': return { complete: true, missing: [], exe_version: '3.3.5.12340' };
      case 'play': return 'Started My Wrath on ' + args.realm + '.';
      case 'realms_list': return { realms: [{ slug: 'official', name: 'Dalaran Hangout', official: true, state: 'live', build: '3.3.5a', version: '3.3.5a',
        core: 'azerothcore', tags: [], players: 5, bots: 0, address: 'play.openvanilla.app' }], network: { realms: 0, players: 5, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'realm_status': return { state: 'online', ping_ms: 10, players: 5 };
      case 'mods_catalog': return { categories: [], projects: [], from_cache: false, saved_at: 1, error: null };
      case 'mods_ranked': return { ids: [], metrics: {}, from_cache: false, error: null };
      case 'mods_installed': return { client: args.client, build: '3.3.5a', mods: [] };
      case 'mods_updates': return [];
      case 'themes_list': return { active: 'dark', themes: [] };
      case 'deep_link_take': return null;
      case 'launcher_update_state': return { mode: 'auto', checking: false, downloading: false, ready: null, info: null };
      case 'host_info': return { dir: null, is_kit: false, problems: [], seeds: [], realm: null };
      case 'modes_list': return { modes: [], from_cache: false, builtin: false, saved_at: null, error: null };
      case 'p2p_flags': return { effective: { p2p_hosting: false, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case 'social_status': return false;
      // the Leyline addons
      case 'addons_status': return status();
      case 'addons_should_offer': return !prefs.dont_ask && !ad[args.client].installed;
      case 'addons_set_prefs':
        if (args.autoUpdate !== undefined) prefs.auto_update = args.autoUpdate;
        if (args.dontAsk !== undefined) prefs.dont_ask = args.dontAsk;
        return Object.assign({}, prefs);
      case 'addons_auto_update': return o.autoUpdated || [];
      case 'addons_install': {
        if (o.badDownload) throw 'The Leyline addons download did not check out (WrathUnleashedUI/Golf.lua is not the listed file), so nothing was installed. Try again later.';
        const a = ad[args.client];
        if (a.foreign.length && !args.replace) { replaceAsked = true; throw 'ADDONS_REPLACE:' + JSON.stringify({ folders: a.foreign }); }
        const moved = args.replace ? a.foreign.map((f) => `Leyline/backup/${f}-1`) : [];
        if (args.replace) { a.backups = a.foreign.slice(); a.foreign = []; }
        a.installed = pack.version; a.update = false; a.missing = [];
        return { version: pack.version, addons: pack.addons.map((x) => x.name), moved_aside: moved, kept: [], already: false };
      }
      case 'addons_remove': {
        const a = ad[args.client]; const back = a.backups.map((f) => 'Interface/AddOns/' + f);
        a.installed = null; a.backups = [];
        return { removed_files: 31, changed: [], kept: [], restored: back, still_backed_up: [] };
      }
      default: throw 'unknown ' + cmd;
    }
  } } };
  window.__replaceAsked = () => replaceAsked;
};
const TWO = () => [
  { id: 'c335a-1', name: 'My Wrath', path: 'C:\\Games\\Wrath', build: '3.3.5a', realmlist: '' },
  { id: 'c1121-1', name: 'My Vanilla', path: 'C:\\Games\\Vanilla', build: '1.12.1', realmlist: '' },
];

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });
async function open(opts = {}) {
  const ctx = await browser.newContext({ colorScheme: 'dark', viewport: { width: 1400, height: 860 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('https://play.openvanilla.app/**', (r) => r.fulfill({ path: PICTURE, contentType: 'image/webp' }));
  await page.addInitScript(FAKE, Object.assign({ clients: TWO() }, opts));
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineAddons && window.LeylineAddons.status() && window.__calls.filter(([c]) => c === 'addons_status').length >= 2);
  return { page, ctx, errors };
}
const calls = (page, name) => page.evaluate((n) => window.__calls.filter(([c]) => c === n).map(([, a]) => a), name);
const order = (page) => page.evaluate(() => window.__calls.map(([c]) => c).filter((c) => c === 'play' || c === 'addons_install'));
const slot = (page, id) => page.locator(`#cl-list .ad-slot[data-client="${id}"]`);

test('Clients: the row on a 3.3.5a card only, Install, then Update and Remove', async () => {
  const { page, ctx, errors } = await open();
  assert.equal(await page.locator('#cl-list .ad-slot').count(), 1, 'only the 3.3.5a client has the row');
  const row = slot(page, 'c335a-1');
  assert.match(await row.textContent(), /Leyline addons/);
  assert.match(await row.textContent(), /Recommended for the Dalaran Hangout: game modes, golf, Edit mode, your Den\./);
  assert.match(await row.locator('.ad-state').textContent(), /^Not installed$/);
  await row.getByRole('button', { name: 'INSTALL' }).click();
  await page.waitForFunction(() => /Installed the Leyline addons/.test(document.querySelector('#cl-list .ad-slot').textContent));
  assert.deepEqual(await calls(page, 'addons_install'), [{ client: 'c335a-1', replace: false }]);
  assert.match(await slot(page, 'c335a-1').locator('.ad-state').textContent(), /Installed and up to date/);
  assert.equal(await slot(page, 'c335a-1').locator('.ad-ver').textContent(), 'v2026.1031.900');
  await slot(page, 'c335a-1').getByRole('button', { name: 'UNINSTALL' }).click();
  await page.waitForFunction(() => /Removed the Leyline addons from My Wrath: 31 files\./.test(document.querySelector('#cl-list .ad-slot').textContent));
  assert.deepEqual(await calls(page, 'addons_remove'), [{ client: 'c335a-1' }]);
  const all = await page.textContent('body');
  assert.doesNotMatch(all, /World of Warcraft|Warcraft|\bWoW\b|Lich King|Blizzard/);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Clients: an update ready, and a download that does not check out', async () => {
  const { page, ctx, errors } = await open({ addons: { 'c335a-1': { installed: '2026.1030.1200', update: true } }, prefs: { auto_update: false }, badDownload: true });
  const row = slot(page, 'c335a-1');
  assert.match(await row.locator('.ad-state').textContent(), /Update ready: v2026\.1031\.900/);
  assert.equal(await calls(page, 'addons_auto_update').then((c) => c.length), 0, 'update on start is off');
  await row.getByRole('button', { name: 'UPDATE' }).click();
  await page.waitForFunction(() => /did not check out/.test(document.querySelector('#cl-list .ad-slot .ad-note.bad').textContent));
  assert.match(await slot(page, 'c335a-1').locator('.ad-state').textContent(), /Update ready/, 'still the old version');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Clients: your own copy of one of ours: asked first, then moved aside; Remove puts it back', async () => {
  const { page, ctx, errors } = await open({ addons: { 'c335a-1': { foreign: ['OVQoL'] } } });
  const row = slot(page, 'c335a-1');
  assert.match(await row.locator('.ad-state').textContent(), /You have your own OVQoL/);
  await row.getByRole('button', { name: 'INSTALL' }).click();
  await page.waitForSelector('#ad-dlg[open]');
  assert.equal(await page.textContent('#ad-dlg-title'), 'You already have some of these');
  assert.deepEqual(await page.$$eval('#ad-dlg-list li', (l) => l.map((x) => x.textContent)), ['Interface/AddOns/OVQoL']);
  await page.click('#ad-dlg-yes');
  await page.waitForFunction(() => /Your own copies are kept in Leyline\/backup\/OVQoL-1/.test(document.querySelector('#cl-list .ad-slot').textContent));
  assert.deepEqual(await calls(page, 'addons_install'), [{ client: 'c335a-1', replace: false }, { client: 'c335a-1', replace: true }]);
  await slot(page, 'c335a-1').getByRole('button', { name: 'UNINSTALL' }).click();
  await page.waitForFunction(() => /Put your own copies back: Interface\/AddOns\/OVQoL/.test(document.querySelector('#cl-list .ad-slot').textContent));
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Clients: saying no to moving your copy installs nothing', async () => {
  const { page, ctx } = await open({ addons: { 'c335a-1': { foreign: ['OVQoL'] } } });
  await slot(page, 'c335a-1').getByRole('button', { name: 'INSTALL' }).click();
  await page.waitForSelector('#ad-dlg[open]');
  await page.click('#ad-dlg-no');
  await page.waitForFunction(() => /your own copies stay as they are/.test(document.querySelector('#cl-list .ad-slot').textContent));
  assert.deepEqual(await calls(page, 'addons_install'), [{ client: 'c335a-1', replace: false }]);
  await ctx.close();
});

test('Mods › Installed: Our addons for the picked 3.3.5a client', async () => {
  const { page, ctx, errors } = await open({ page: 'installed', addons: { 'c335a-1': { installed: '2026.1031.900' } } });
  await page.waitForSelector('#ad-mods:not([hidden]) .ad-row');
  assert.match(await page.textContent('#ad-mods .card-head'), /OUR ADDONS/);
  assert.deepEqual(await page.$$eval('#ad-mods .ad-list li b', (l) => l.map((x) => x.textContent)), ['Leyline Armory', 'OVQoL', 'Leyline UI']);
  assert.match(await page.textContent('#ad-mods'), /Installed and up to date/);
  assert.match(await page.textContent('#ad-mods'), /Your other addons stay as they are/);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the setup step: adding a 3.3.5a client offers the addons', async () => {
  const { page, ctx, errors } = await open();
  await page.fill('#cl-path', 'D:\\Games\\Wrath2');
  await page.click('#cl-add');
  await page.waitForSelector('#ad-dlg[open]');
  assert.equal(await page.textContent('#ad-dlg-title'), 'One more step: the Leyline addons');
  assert.match(await page.textContent('#ad-dlg-body'), /Install the Leyline addons in New Wrath\? Recommended for the Dalaran Hangout/);
  assert.equal(await page.textContent('#ad-dlg-yes'), 'INSTALL');
  await page.click('#ad-dlg-yes');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'addons_install' && a.client === 'c335a-2'));
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('PLAY on the Dalaran Hangout: Install and play installs first, then the game starts', async () => {
  const { page, ctx, errors } = await open({ page: 'play' });
  await page.click('#play-go');
  await page.waitForSelector('#ad-dlg[open]');
  assert.equal(await page.textContent('#ad-dlg-title'), 'Add the Leyline addons?');
  assert.equal(await page.isVisible('#ad-dlg-ask'), true);
  await page.click('#ad-dlg-yes');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.deepEqual(await order(page), ['addons_install', 'play']);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('PLAY: Play without + Don\'t ask again starts the game and never asks again', async () => {
  const { page, ctx, errors } = await open({ page: 'play' });
  await page.click('#play-go');
  await page.waitForSelector('#ad-dlg[open]');
  await page.check('#ad-dlg-ask');
  await page.click('#ad-dlg-no');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.deepEqual(await calls(page, 'addons_set_prefs'), [{ dontAsk: true }]);
  assert.deepEqual(await order(page), ['play']);
  await page.waitForFunction(() => !document.querySelector('#play-go').disabled);
  await page.click('#play-go');
  await page.waitForFunction(() => window.__calls.filter(([c]) => c === 'play').length === 2);
  assert.equal(await page.locator('#ad-dlg[open]').count(), 0, 'not asked again');
  // Settings shows it, and can turn the offer back on.
  await page.evaluate(() => window.LeylineNav.show('settings'));
  assert.equal(await page.isChecked('#ad-set-ask'), false);
  assert.equal(await page.isChecked('#ad-set-auto'), true);
  await page.uncheck('#ad-set-auto');
  await page.check('#ad-set-ask');
  assert.deepEqual((await calls(page, 'addons_set_prefs')).slice(1), [{ autoUpdate: false }, { dontAsk: false }]);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('PLAY: Escape plays without; another realm and installed addons are never asked about', async () => {
  const { page, ctx } = await open({ page: 'play' });
  await page.click('#play-go');
  await page.waitForSelector('#ad-dlg[open]');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.deepEqual(await order(page), ['play']);
  await ctx.close();

  const b = await open({ page: 'play', addons: { 'c335a-1': { installed: '2026.1031.900' } } });
  await b.page.click('#play-go');
  await b.page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.equal(await b.page.locator('#ad-dlg[open]').count(), 0);
  assert.equal((await calls(b.page, 'addons_should_offer')).length, 0);
  await b.ctx.close();

  const c = await open({ page: 'play' });
  await c.page.evaluate(() => { const s = document.getElementById('play-realm'); s.value = 'custom'; s.dispatchEvent(new Event('change')); });
  await c.page.evaluate(() => { const i = document.getElementById('play-custom'); i.value = 'realm.example.org'; i.dispatchEvent(new Event('change')); });
  await c.page.click('#play-go');
  await c.page.waitForFunction(() => window.__calls.some(([x]) => x === 'play'));
  assert.equal(await c.page.locator('#ad-dlg[open]').count(), 0, 'not on another realm');
  assert.equal((await calls(c.page, 'addons_should_offer')).length, 0);
  await c.ctx.close();
});

test('update on start: asked once at start, and its result shown on the card', async () => {
  const { page, ctx, errors } = await open({ addons: { 'c335a-1': { installed: '2026.1031.900' } }, autoUpdated: [{ client: 'c335a-1', version: '2026.1031.900', error: null }] });
  await page.waitForFunction(() => /Updated the Leyline addons in My Wrath to v2026\.1031\.900\./.test(document.querySelector('#cl-list .ad-slot').textContent));
  assert.equal((await calls(page, 'addons_auto_update')).length, 1);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('not published yet: no Install button, and PLAY does not ask', async () => {
  const { page, ctx, errors } = await open({ noPack: true });
  const row = slot(page, 'c335a-1');
  assert.match(await row.locator('.ad-state').textContent(), /Not published yet/);
  assert.equal(await row.getByRole('button', { name: 'INSTALL' }).isDisabled(), true);
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.click('#play-go');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.equal(await page.locator('#ad-dlg[open]').count(), 0);
  assert.deepEqual(errors, []);
  await ctx.close();
});
