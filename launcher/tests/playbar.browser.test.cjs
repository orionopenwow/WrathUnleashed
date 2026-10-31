// The launcher's play bar (ui/index.html #play-form, ui/app.js renderClientMenu / renderPlayBar) in Chromium with a fake
// Tauri core: the client picker opens a drop-up list (actions on top, the families with no folder greyed "Not found",
// your folders nearest the button with the picked one marked), a greyed row opens Find your game files, picking a
// row changes the client, the keyboard (Up / Down / Home / End / Enter / Esc) and a click outside, the realm button,
// the mode switch, no version text in the bar, and the guide: plain words, no download links, browser play.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/playbar.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const PICTURE = path.join(__dirname, '..', 'ui', 'art', 'leyline-bg.webp');

const FAKE = ({ clients }) => {
  const calls = (window.__calls = []);
  try { localStorage.removeItem('leyline.page'); localStorage.setItem('leyline.mode', 'online'); } catch (_) { /* fine */ }
  const list = clients || [];
  const st = { version: 'test', settings: { clients: list, selected_client: list[0] ? list[0].id : null, selected_realm: 'play.openvanilla.app',
    wine: { enabled: false, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return JSON.parse(JSON.stringify(st));
      case 'select': st.settings.selected_client = args.client; return null;
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
      case 'pick_folder': return null;
      default: throw 'unknown ' + cmd;
    }
  } } };
};
const TWO = [
  { id: 'c335a-1', name: 'My Wrath', path: 'C:\\Games\\Wrath', build: '3.3.5a', realmlist: '' },
  { id: 'c1121-1', name: 'My Vanilla', path: '/home/me/Games/vanilla', build: '1.12.1', realmlist: '' },
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
  await page.addInitScript(FAKE, opts);
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineNav && document.querySelector('#page-play.on') && window.__calls.some(([c]) => c === 'realms_list'));
  return { page, ctx, errors };
}
const rows = (page) => page.$$eval('#pb-menu > li', (l) => l.map((x) => (x.classList.contains('pb-sep') ? '---'
  : [x.className.replace('pb-opt ', ''), x.querySelector('.pb-opt-name').textContent, (x.querySelector('.rl-ver') || {}).textContent || '',
    (x.querySelector('.pb-opt-sub') || {}).textContent || '', x.getAttribute('aria-selected'), x.getAttribute('aria-disabled')].join('|'))));
const pageOn = (page) => page.evaluate(() => document.querySelector('.page.on').id);

test('the picker: the client and its version; the drop-up list in its three groups', async () => {
  const { page, ctx, errors } = await open({ clients: TWO });
  assert.equal(await page.textContent('#pb-client-name'), 'My Wrath');
  assert.equal(await page.textContent('#pb-client-ver'), '3.3.5a');
  assert.equal(await page.isVisible('#pb-menu'), false);
  await page.click('#pb-client');
  assert.equal(await page.getAttribute('#pb-client', 'aria-expanded'), 'true');
  assert.equal(await page.getAttribute('#pb-menu', 'role'), 'listbox');
  assert.deepEqual(await rows(page), [
    'pb-act|Add a game folder…|||false|', 'pb-act|Find your game files|||false|', '---',
    'pb-missing|TBC|2.4.3|Not found|false|true', '---',
    'pb-mine|My Wrath|3.3.5a|C:\\Games\\Wrath|true|', 'pb-mine|My Vanilla|1.12.1|/home/me/Games/vanilla|false|',
  ]);
  assert.equal(await page.evaluate(() => document.activeElement.textContent.startsWith('My Wrath')), true, 'the picked row has the focus');
  // the list opens upwards, above the button, inside the window
  const r = await page.evaluate(() => [document.getElementById('pb-menu').getBoundingClientRect(), document.getElementById('pb-client').getBoundingClientRect()].map((b) => [b.top, b.bottom]));
  assert.ok(r[0][1] <= r[1][0] && r[0][0] >= 0, 'a drop-up');
  // pick My Vanilla
  await page.click('#pb-menu .pb-mine >> text=My Vanilla');
  assert.equal(await page.isVisible('#pb-menu'), false);
  assert.equal(await page.inputValue('#play-client'), 'c1121-1');
  assert.equal(await page.textContent('#pb-client-ver'), '1.12.1');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'select' && a.client === 'c1121-1')), 'saved');
  assert.match(await page.textContent('#play-headline'), /NEEDS 3\.3\.5A/, 'the official realm runs 3.3.5a');
  assert.equal(await page.textContent('#pb-detail'), 'Pick My Wrath');
  const text = await page.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /world of warcraft|\bwow\b|warcraft|lich king|blizzard/i);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the keyboard: Up opens, arrows and Home / End move, Enter picks, Esc closes; a click outside closes', async () => {
  const { page, ctx, errors } = await open({ clients: TWO });
  await page.focus('#pb-client');
  await page.keyboard.press('ArrowUp');
  assert.ok(await page.isVisible('#pb-menu'));
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement.querySelector('.pb-opt-name').textContent), 'My Vanilla');
  await page.keyboard.press('Home');
  assert.equal(await page.evaluate(() => document.activeElement.querySelector('.pb-opt-name').textContent), 'Add a game folder…');
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  assert.equal(await page.inputValue('#play-client'), 'c1121-1');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'pb-client', 'the focus back on the button');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Escape');
  assert.equal(await page.isVisible('#pb-menu'), false);
  assert.equal(await page.getAttribute('#pb-client', 'aria-expanded'), 'false');
  await page.click('#pb-client');
  await page.mouse.click(700, 300);
  assert.equal(await page.isVisible('#pb-menu'), false, 'a click outside closes it');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('no clients: every family greyed; a greyed row opens Find your game files; Add a game folder opens Clients', async () => {
  const { page, ctx, errors } = await open({ clients: [] });
  assert.equal(await page.textContent('#pb-client-name'), 'No game client');
  assert.equal(await page.isVisible('#pb-client-ver'), false);
  await page.click('#pb-client');
  assert.deepEqual(await rows(page), ['pb-act|Add a game folder…|||false|', 'pb-act|Find your game files|||false|', '---',
    'pb-missing|Vanilla|1.12.1|Not found|false|true', 'pb-missing|TBC|2.4.3|Not found|false|true', 'pb-missing|Wrath|3.3.5a|Not found|false|true']);
  await page.click('#pb-menu .pb-missing >> text=TBC');
  assert.equal(await pageOn(page), 'page-findfiles');
  assert.equal(await page.textContent('#ff-want'), 'Looking for TBC 2.4.3. ');
  const guide = await page.textContent('#page-findfiles');
  assert.match(guide, /Leyline can't download the game for you\./);
  assert.match(guide, /Windows[\s\S]*Mac[\s\S]*Linux/);
  assert.match(guide, /backup/i);
  assert.match(guide, /friend/i);
  assert.doesNotMatch(guide, /world of warcraft|\bwow\b|warcraft|lich king|blizzard|torrent/i);
  assert.equal(await page.locator('#page-findfiles a, #page-findfiles [data-link]').count(), 0, 'no links out of the app at all');
  await page.click('#ff-pick');
  assert.equal(await pageOn(page), 'page-clients');
  assert.ok(await page.evaluate(() => window.__calls.some(([c]) => c === 'pick_folder')), 'CHOOSE A FOLDER… asks for the folder');
  await page.evaluate(() => window.LeylineNav.show('findfiles'));
  await page.click('#ff-browser');
  assert.equal(await pageOn(page), 'page-play');
  assert.equal(await page.getAttribute('.mode[data-mode="browser"]', 'aria-checked'), 'true', 'No files? Play in your browser');
  assert.equal(await page.textContent('#pb-realm'), 'Plays in your browser');
  await page.click('#pb-client');
  await page.click('#pb-menu >> text=Add a game folder…');
  assert.equal(await pageOn(page), 'page-clients');
  await page.click('#page-clients [data-page-go="findfiles"]');
  assert.equal(await pageOn(page), 'page-findfiles');
  assert.equal(await page.isVisible('#ff-want'), false);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the middle and right: the realm with its version (to Realms), one status line, the mode switch; no version text in the bar', async () => {
  const { page, ctx, errors } = await open({ clients: TWO });
  await page.waitForFunction(() => document.getElementById('pb-realm').textContent === 'Dalaran Hangout');
  assert.equal(await page.textContent('#pb-realm-ver'), '3.3.5a');
  assert.equal(await page.textContent('#play-headline'), 'READY TO PLAY');
  assert.equal(await page.isVisible('#pb-detail'), false, 'nothing repeated under it');
  assert.doesNotMatch(await page.textContent('#play-form'), /Leyline v/);
  assert.equal(await page.textContent('#ver'), 'Leyline vtest');
  assert.ok(await page.evaluate(() => document.getElementById('ver').closest('#page-settings')), 'the version lives in Settings');
  // the bar's three blocks sit left to right on one row
  const x = await page.evaluate(() => ['.pb-left', '.pb-mid', '.pb-right'].map((s) => document.querySelector(s).getBoundingClientRect().left));
  assert.ok(x[0] < x[1] && x[1] < x[2]);
  assert.ok(await page.evaluate(() => document.querySelector('.pb-right .modes') && document.querySelector('.pb-right .play')), 'the mode switch beside PLAY');
  await page.click('.mode[data-mode="browser"]');
  assert.equal(await page.textContent('#play-headline'), 'READY · NOTHING TO INSTALL');
  await page.click('.mode[data-mode="online"]');
  await page.click('#pb-realm-btn');
  assert.equal(await pageOn(page), 'page-realms');
  assert.deepEqual(errors, []);
  await ctx.close();
});
