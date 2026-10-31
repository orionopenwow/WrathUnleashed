// The launcher's play bar (ui/index.html #play-form, ui/app.js renderClientMenu / renderPlayBar) in Chromium with a fake
// Tauri core: the client picker opens a drop-up list (actions on top, the families with no folder greyed "Not found",
// your folders nearest the button with the picked one marked), a greyed row opens Find your game files, picking a
// row changes the client, the keyboard (Up / Down / Home / End / Enter / Esc) and a click outside, the realm picker (a
// drop-up list of realms, browser play, My Den, Make a realm, Find more; picking selects and saves; My Den plays the
// Den this PC hosts, or opens the Host page with Make my Den picked), no mode switch, no
// version text in the bar, and the guide: plain words, no download links, browser play.
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
  assert.equal(await page.evaluate(() => localStorage.getItem('leyline.mode')), 'browser', 'No files? Play in your browser');
  assert.equal(await page.textContent('#pb-realm'), 'In your browser');
  await page.click('#pb-client');
  await page.click('#pb-menu >> text=Add a game folder…');
  assert.equal(await pageOn(page), 'page-clients');
  await page.click('#page-clients [data-page-go="findfiles"]');
  assert.equal(await pageOn(page), 'page-findfiles');
  assert.equal(await page.isVisible('#ff-want'), false);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the middle and right: the realm picker with its version and one status line, PLAY; no mode switch, no version text', async () => {
  const { page, ctx, errors } = await open({ clients: TWO });
  await page.waitForFunction(() => document.getElementById('pb-realm').textContent === 'Dalaran Hangout');
  assert.equal(await page.textContent('#pb-realm-ver'), '3.3.5a');
  assert.equal(await page.textContent('#play-headline'), 'READY TO PLAY');
  assert.ok(await page.evaluate(() => document.getElementById('play-headline').closest('#pb-realm-btn')), 'the status line under the realm name');
  assert.equal(await page.isVisible('#pb-detail'), false, 'nothing repeated under it');
  assert.doesNotMatch(await page.textContent('#play-form'), /Leyline v/);
  assert.equal(await page.textContent('#ver'), 'Leyline vtest');
  assert.ok(await page.evaluate(() => document.getElementById('ver').closest('#page-settings')), 'the version lives in Settings');
  // the bar's three blocks sit left to right on one row; no ONLINE / SOLO / BROWSER switch
  const x = await page.evaluate(() => ['.pb-left', '.pb-mid', '.pb-right'].map((s) => document.querySelector(s).getBoundingClientRect().left));
  assert.ok(x[0] < x[1] && x[1] < x[2]);
  assert.equal(await page.locator('#play-form .modes, #play-form .mode').count(), 0);
  assert.ok(await page.evaluate(() => document.querySelector('.pb-right .play').getBoundingClientRect().width >= 280), 'PLAY is bigger');
  assert.equal(await page.getAttribute('#pb-realm-btn', 'aria-haspopup'), 'listbox');
  assert.deepEqual(errors, []);
  await ctx.close();
});

const NET = [
  { slug: 'official', name: 'Dalaran Hangout', official: true, state: 'live', build: '3.3.5a', version: '3.3.5a', core: 'azerothcore', tags: [], players: 5, bots: 0, address: 'play.openvanilla.app' },
  { slug: 'c-a', realm_id: 'a', name: 'Small Den', state: 'live', build: '3.3.5a', version: '3.3.5a', core: 'azerothcore', tags: [], players: 3, bots: 0, address: 'relay.openvanilla.app:40001' },
  { slug: 'c-b', realm_id: 'b', name: 'Busy Den', state: 'live', build: '3.3.5a', version: '3.3.5a', core: 'azerothcore', tags: [], players: 30, bots: 0, address: 'relay.openvanilla.app:40002' },
  { slug: 'c-c', realm_id: 'c', name: 'Asleep', state: 'offline', build: '3.3.5a', version: '3.3.5a', core: 'azerothcore', tags: [], players: 0, bots: 0, address: 'relay.openvanilla.app:40004' },
];
async function openNet(net = NET) {
  const ctx = await browser.newContext({ colorScheme: 'dark', viewport: { width: 1400, height: 860 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('https://play.openvanilla.app/**', (r) => r.fulfill({ path: PICTURE, contentType: 'image/webp' }));
  await page.addInitScript(FAKE, { clients: TWO });
  await page.addInitScript((net) => {
    const inner = window.__TAURI__.core.invoke;
    window.__TAURI__.core.invoke = async (cmd, args) => {
      const r = await inner(cmd, args);
      if (cmd === 'realms_list') r.realms = net;
      return r;
    };
  }, net);
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineNav && document.querySelector('#page-play.on') && window.__calls.some(([c]) => c === 'realms_list'));
  await page.waitForFunction(() => document.getElementById('pb-realm').textContent === 'Dalaran Hangout');
  return { page, ctx, errors };
}
const rrows = (page) => page.$$eval('#pb-rmenu > li', (l) => l.map((x) => (x.classList.contains('pb-sep') ? '---' : x.classList.contains('pb-head') ? '# ' + x.textContent
  : [x.querySelector('.pb-opt-name').textContent, (x.querySelector('.rl-ver') || {}).textContent || '', (x.querySelector('.pb-opt-sub') || {}).textContent || '',
    x.getAttribute('aria-selected'), x.getAttribute('aria-disabled') || ''].join('|'))));

test('the realm picker: a drop-up list of your realms, live realms, browser play, My Den, Make a realm and Find more', async () => {
  const { page, ctx, errors } = await openNet();
  assert.equal(await page.isVisible('#pb-rmenu'), false);
  await page.click('#pb-realm-btn');
  assert.equal(await page.getAttribute('#pb-realm-btn', 'aria-expanded'), 'true');
  assert.equal(await page.getAttribute('#pb-rmenu', 'role'), 'listbox');
  assert.deepEqual(await rrows(page), [
    '# Official', 'Dalaran Hangout|3.3.5a|5 playing|true|', '---',
    '# On the network', 'Busy Den|3.3.5a|30 playing|false|', 'Small Den|3.3.5a|3 playing|false|', '---',
    'Play in your browser||Nothing to install|false|', 'My Den||Make your Den|false|', '---',
    '+ Make a realm|||false|', 'Find more realms…|||false|',
  ], 'live realms by players; offline ones left out');
  assert.equal(await page.evaluate(() => document.activeElement.querySelector('.pb-opt-name').textContent), 'Dalaran Hangout', 'the picked row has the focus');
  const r = await page.evaluate(() => [document.getElementById('pb-rmenu').getBoundingClientRect(), document.getElementById('pb-realm-btn').getBoundingClientRect()].map((b) => [b.top, b.bottom]));
  assert.ok(r[0][1] <= r[1][0] && r[0][0] >= 0, 'a drop-up');
  // pick Busy Den: selected like the side bar's Your realms does, and saved
  await page.click('#pb-rmenu >> text=Busy Den');
  assert.equal(await page.isVisible('#pb-rmenu'), false);
  assert.equal(await page.inputValue('#play-realm'), 'custom');
  assert.equal(await page.inputValue('#play-custom'), 'relay.openvanilla.app:40002');
  assert.equal(await page.textContent('#pb-realm'), 'Busy Den');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'select' && a.realm === 'relay.openvanilla.app:40002')), 'saved');
  await page.click('#pb-realm-btn');
  const now = await rrows(page);
  assert.ok(now.includes('Busy Den|3.3.5a|30 playing|true|'), 'now under Your realms, marked');
  assert.ok(!now.slice(now.indexOf('# On the network')).some((x) => x.startsWith('Busy Den')), 'not twice');
  // browser play is a row; the picker says so; a realm row turns it back off
  await page.click('#pb-rmenu >> text=Play in your browser');
  assert.equal(await page.textContent('#pb-realm'), 'In your browser');
  assert.equal(await page.textContent('#play-headline'), 'READY · NOTHING TO INSTALL');
  assert.equal(await page.evaluate(() => localStorage.getItem('leyline.mode')), 'browser');
  assert.equal(await page.evaluate(() => window.LeylineApp.mode()), 'browser');
  await page.click('#pb-realm-btn');
  assert.equal(await page.getAttribute('#pb-rmenu .pb-browser', 'aria-selected'), 'true');
  assert.equal(await page.locator('#pb-rmenu .pb-solo').count(), 0, 'Solo (coming soon) gave way to My Den');
  await page.click('#pb-rmenu >> text=Dalaran Hangout');
  assert.equal(await page.evaluate(() => window.LeylineApp.mode()), 'online');
  assert.equal(await page.inputValue('#play-realm'), 'official');
  assert.equal(await page.textContent('#pb-realm'), 'Dalaran Hangout');
  // the bottom rows
  await page.click('#pb-realm-btn');
  await page.click('#pb-rmenu >> text=+ Make a realm');
  assert.equal(await pageOn(page), 'page-host');
  await page.click('#pb-realm-btn');
  await page.click('#pb-rmenu >> text=Find more realms…');
  assert.equal(await pageOn(page), 'page-realms');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the realm picker: the official lineup first, the Dalaran Hangout labelled the Wrath realm, then Vanilla Remastered', async () => {
  const vr = { slug: 'c-v', realm_id: 'v', name: 'Vanilla Remastered', state: 'live', build: '1.12.1', version: '1.12.1', core: 'vmangos', tags: [], players: 2, bots: 0, address: 'relay.openvanilla.app:40050' };
  const { page, ctx, errors } = await openNet([Object.assign({}, NET[0], { name: 'Leyline Sample Hangout' }), NET[1], NET[2], vr, NET[3]]);
  await page.click('#pb-realm-btn');
  const rows = await rrows(page);
  assert.deepEqual(rows.slice(0, 4), ['# Official', 'Dalaran Hangout|3.3.5a|5 playing|true|', 'Vanilla Remastered|1.12.1|2 playing|false|', '---'],
    'one name for the official realm whatever the list calls it; the lineup pinned under it');
  assert.ok(!rows.slice(4).some((x) => x.startsWith('Vanilla Remastered')), 'not twice');
  assert.equal(await page.textContent('#pb-rmenu .pb-opt-kind'), 'the Wrath realm');
  assert.equal(await page.locator('#pb-rmenu .pb-opt-kind').count(), 1, 'only the Hangout has the label');
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('#pb-rmenu .pb-opt-kind'), '::before').content), '"· "');
  await page.click('#pb-rmenu >> text=Vanilla Remastered');
  assert.equal(await page.inputValue('#play-custom'), 'relay.openvanilla.app:40050');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the realm picker by keyboard: Up opens, arrows and Home / End, Enter picks, Esc closes; only one list open', async () => {
  const { page, ctx, errors } = await openNet();
  await page.focus('#pb-realm-btn');
  await page.keyboard.press('ArrowUp');
  assert.ok(await page.isVisible('#pb-rmenu'));
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement.querySelector('.pb-opt-name').textContent), 'Busy Den');
  await page.keyboard.press('End');
  assert.equal(await page.evaluate(() => document.activeElement.querySelector('.pb-opt-name').textContent), 'Find more realms…');
  await page.keyboard.press('Home');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  assert.equal(await page.textContent('#pb-realm'), 'Small Den');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'pb-realm-btn', 'the focus back on the button');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Escape');
  assert.equal(await page.isVisible('#pb-rmenu'), false);
  assert.equal(await page.getAttribute('#pb-realm-btn', 'aria-expanded'), 'false');
  await page.click('#pb-realm-btn');
  await page.click('#pb-client');
  assert.equal(await page.isVisible('#pb-rmenu'), false, 'opening the client list closes the realm list');
  assert.ok(await page.isVisible('#pb-menu'));
  await page.click('#pb-realm-btn');
  assert.equal(await page.isVisible('#pb-menu'), false, 'and the other way round');
  await page.mouse.click(700, 300);
  assert.equal(await page.isVisible('#pb-rmenu'), false, 'a click outside closes it');
  assert.deepEqual(errors, []);
  await ctx.close();
});

// My Den (docs/DEN.md): the kit's state/host.json profile "den" says this PC hosts one
const DEN_KIT = { dir: '/home/me/kit', is_kit: true, has_windows_script: true, has_unix_script: true, problems: [], seeds: [],
  realm: { realm_id: 'abcdefghijk2345a', name: 'My Den', visibility: 'private', relay: 'relay.openvanilla.app', profile: 'den' } };
const DEN_INVITE = 'https://relay.openvanilla.app/join/abcdefghijk2345a#k3y';
async function openDen(hostKit, clients = [TWO[1], TWO[0]]) {
  const ctx = await browser.newContext({ colorScheme: 'dark', viewport: { width: 1400, height: 860 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('https://play.openvanilla.app/**', (r) => r.fulfill({ path: PICTURE, contentType: 'image/webp' }));
  await page.addInitScript(FAKE, { clients });   // the 1.12.1 folder picked: the Den takes the 3.3.5a one
  await page.addInitScript((hostKit) => {
    const inner = window.__TAURI__.core.invoke;
    window.__kit = hostKit;
    window.__TAURI__.core.invoke = async (cmd, args) => {
      switch (cmd) {
        case 'host_info': window.__calls.push([cmd, args]); return JSON.parse(JSON.stringify(window.__kit));
        case 'host_invite': window.__calls.push([cmd, args]); return window.__kit.realm ? 'https://relay.openvanilla.app/join/abcdefghijk2345a#k3y' : null;
        case 'join_invite': window.__calls.push([cmd, args]); return { address: 'relay.openvanilla.app:40007', name: 'My Den' };
        case 'play': window.__calls.push([cmd, args]); return 'Started My Wrath.';
        case 'host_profiles': window.__calls.push([cmd, args]); return [[
          { id: 'vanillaplus', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c335a-1', name: 'My Wrath', path: '/g' }], note: null },
          { id: 'den', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c335a-1', name: 'My Wrath', path: '/g' }], note: null },
          { id: 'dalaran', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c335a-1', name: 'My Wrath', path: '/g' }], note: null },
        ], null];
        case 'host_choose': window.__calls.push([cmd, args]); return { profile: args.profile, client_dir: '' };
        case 'hostpack_info': return { installed: { version: '7' }, available: { version: '7' }, update: false, kit_dir: '/home/me/kit' };
        case 'docker_info': return { state: 'ready', version: '27', help: '', get_url: '' };
        case 'host_listing': return { tags: [], region: null, language: null, max_players: null, direct: false };
        case 'host_console': return { set_up: true, linked: false, name: 'My Den', realm_id: 'abcdefghijk2345a', profile: 'den', core: 'azerothcore',
          visibility: 'private', signup: 'invite', browser: false, max_players: 10, docker: true, services: [], gm: false, gm_note: null };
        case 'host_status': return { realm_id: args.realmId, online: true, name: 'My Den', visibility: 'private', players: 1, bots: 0, listed: false };
        default: return inner(cmd, args);
      }
    };
  }, hostKit);
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineNav && document.querySelector('#page-play.on') && window.__calls.some(([c]) => c === 'realms_list'));
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_info'));
  return { page, ctx, errors };
}
const callsOf = (page, cmd) => page.evaluate((cmd) => window.__calls.filter(([c]) => c === cmd).map(([, a]) => a), cmd);

test('My Den hosted on this PC: the row plays it through its own invite link with the 3.3.5a client', async () => {
  const { page, ctx, errors } = await openDen(DEN_KIT);
  await page.click('#pb-realm-btn');
  const den = (await rrows(page)).find((x) => x.startsWith('My Den'));
  assert.equal(den, 'My Den|3.3.5a|On this PC|false|', 'its version, and on this PC');
  assert.equal(await page.locator('#pb-rmenu .pb-den .pb-den-ic svg').count(), 1, 'the house mark');
  await page.click('#pb-rmenu .pb-den');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.equal(await page.isVisible('#pb-rmenu'), false);
  assert.deepEqual(await callsOf(page, 'join_invite'), [{ client: 'c335a-1', link: DEN_INVITE }], 'the relay knock with the Den\'s own invite');
  assert.deepEqual(await callsOf(page, 'play'), [{ client: 'c335a-1', realm: 'relay.openvanilla.app:40007' }], 'then PLAY, on the Wrath folder');
  assert.equal(await page.inputValue('#play-client'), 'c335a-1');
  assert.equal(await page.inputValue('#play-custom'), 'relay.openvanilla.app:40007');
  assert.equal(await page.textContent('#pb-realm'), 'My Den', 'the bar names it');
  assert.equal(await page.textContent('#pb-realm-ver'), '3.3.5a');
  assert.ok(await page.evaluate(() => document.querySelector('#pb-realm-ic.pb-mark-ic svg')), 'and shows the house mark');
  await page.click('#pb-realm-btn');
  const rows = await rrows(page);
  assert.ok(rows.includes('My Den|3.3.5a|On this PC|true|'), 'now marked');
  assert.ok(!rows.some((x) => x.startsWith('relay.openvanilla.app:40007')), 'not again as an address under Your realms');
  assert.equal(await pageOn(page), 'page-play');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('My Den not hosted: the row opens the Host page with Make my Den picked', async () => {
  const { page, ctx, errors } = await openDen({ dir: '/home/me/kit', is_kit: true, has_windows_script: true, has_unix_script: true, problems: [], seeds: [], realm: null });
  await page.click('#pb-realm-btn');
  assert.ok((await rrows(page)).includes('My Den||Make your Den|false|'));
  await page.click('#pb-rmenu .pb-den');
  assert.equal(await pageOn(page), 'page-host');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_choose'));
  assert.deepEqual((await callsOf(page, 'host_choose'))[0], { profile: 'den', clientId: 'c335a-1' });
  await page.waitForFunction(() => document.querySelector('.hc-rs[data-profile="den"].on'));
  assert.equal(await page.getAttribute('.hc-rs[data-profile="den"]', 'aria-checked'), 'true');
  assert.equal(await page.textContent('#hc-start'), 'Start My Den');
  assert.equal(await callsOf(page, 'join_invite').then((l) => l.length), 0, 'nothing joined, nothing started');
  assert.equal(await callsOf(page, 'play').then((l) => l.length), 0);
  // made since: the row plays it now
  await page.evaluate((k) => { window.__kit = k; }, DEN_KIT);
  await page.click('.nav[data-page="play"]');
  await page.click('#pb-realm-btn');
  await page.waitForFunction(() => document.querySelector('#pb-rmenu .pb-den .pb-opt-sub').textContent === 'On this PC');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('My Den hosted but no 3.3.5a folder: Clients, with what to add', async () => {
  const { page, ctx, errors } = await openDen(DEN_KIT, [TWO[1]]);
  await page.click('#pb-realm-btn');
  await page.click('#pb-rmenu .pb-den');
  assert.equal(await pageOn(page), 'page-clients');
  assert.match(await page.textContent('#cl-status'), /3\.3\.5a game folder/);
  assert.equal(await callsOf(page, 'join_invite').then((l) => l.length), 0);
  assert.deepEqual(errors, []);
  await ctx.close();
});
