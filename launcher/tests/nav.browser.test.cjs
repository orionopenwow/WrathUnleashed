// The launcher's side menu, page tabs and backdrop (ui/index.html, ui/app.js, ui/style.css) in Chromium with a fake
// Tauri core: the menu matches the website's (Home, Realms, Mods, Host, Forum, News; then Your realms, Settings,
// Help), Mods has the tabs Installed and Discover, the Forum replaced Community (Friends and Hub) and the old page ids
// (mymods, discover, friends, community, hub, mods) still land on the right page and tab, the arrow keys move between tabs, the
// Your realms rows carry the realm's icon and client version, and the website's backdrop sits behind the content area
// only, with the plain colour when it fails to load or Settings › Background picture is off.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/nav.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const BACKDROP = 'https://play.openvanilla.app/wrath/art/leyline-shot-backdrop.webp';
const PICTURE = path.join(__dirname, '..', 'ui', 'art', 'leyline-bg.webp');   // a stand-in: the test never reaches the site

const FAKE = ({ page, backdrop, tabs }) => {
  const calls = (window.__calls = []);
  try {
    if (page) localStorage.setItem('leyline.page', page); else localStorage.removeItem('leyline.page');
    if (backdrop) localStorage.setItem('leyline.backdrop', backdrop); else localStorage.removeItem('leyline.backdrop');
    if (tabs) localStorage.setItem('leyline.tabs', JSON.stringify(tabs)); else localStorage.removeItem('leyline.tabs');
  } catch (_) { /* fine */ }
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [{ id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: '' }],
        selected_client: 'c335a-1', selected_realm: 'play.openvanilla.app', wine: { enabled: false, command: 'wine', prefix: '' } },
        official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
      case 'realms_list': return { realms: [{ slug: 'official', name: 'Wrath Unleashed', official: true, state: 'live', build: '3.3.5a',
        version: '3.3.5a', core: 'azerothcore', tags: [], players: 5, bots: 0, address: 'play.openvanilla.app' }],
        network: { realms: 0, players: 5, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'realm_status': return { state: 'online', ping_ms: 10, players: 5 };
      case 'mods_catalog': return { categories: [], projects: [], from_cache: false, saved_at: 1, error: null };
      case 'mods_ranked': return { ids: [], metrics: {}, from_cache: false, error: null };
      case 'mods_installed': return { client: 'c335a-1', build: '3.3.5a', mods: [] };
      case 'mods_updates': return [];
      case 'themes_list': return { active: 'dark', themes: [] };
      case 'deep_link_take': return null;
      case 'launcher_update_state': return { mode: 'auto', checking: false, downloading: false, ready: null, info: null };
      case 'host_info': return { dir: null, is_kit: false, problems: [], seeds: [], realm: null };
      case 'modes_list': return { modes: [], from_cache: false, builtin: false, saved_at: null, error: null };
      case 'p2p_flags': return { effective: { p2p_hosting: false, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case 'social_status': return false;
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts, picture) {
  const ctx = await browser.newContext({ colorScheme: 'dark' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route(BACKDROP, (r) => (picture === 'fail' ? r.abort() : r.fulfill({ path: PICTURE, contentType: 'image/webp' })));
  await page.addInitScript(FAKE, opts || {});
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineNav && document.querySelector('.page.on'));
  return { page, ctx, errors };
}
const where = (page) => page.evaluate(() => ({
  nav: [...document.querySelectorAll('.nav.on[data-page]')].map((b) => b.dataset.page),
  page: [...document.querySelectorAll('.page.on')].map((p) => p.id),
  panes: [...document.querySelectorAll('.page.on .tabpane.on')].map((p) => p.id),
}));

test('the side menu matches the website, with the same line icons', async () => {
  const { page, ctx, errors } = await open();
  const items = await page.$$eval('aside nav .nav', (b) => b.map((x) => [x.dataset.page, x.textContent.trim().replace(/\d+$/, '')]));
  assert.deepEqual(items, [['play', 'Home'], ['realms', 'Realms'], ['mods', 'Mods'], ['host', 'Host'], ['forum', 'Forum'], ['news', 'News']]);
  assert.equal(await page.locator('aside nav .nav svg').count(), 6, 'each with its line icon');
  const foot = await page.$$eval('.side-foot .nav:not([hidden])', (b) => b.map((x) => x.dataset.page));
  assert.deepEqual(foot, ['settings', 'help']);
  assert.equal(await page.textContent('.side-label'), 'YOUR REALMS');
  assert.equal(await page.locator('[data-link="support"]:visible').count(), 0, 'support buttons stay hidden');
  // Your realms: the crystal for the official realm and the gold client version
  await page.waitForFunction(() => document.querySelector('#realm-rows .realm-row .name').textContent === 'Wrath Unleashed');
  assert.equal(await page.getAttribute('#realm-rows .realm-row .rl-ic img', 'src'), 'art/brand/leyline-crystal-256.webp');
  assert.equal(await page.textContent('#realm-rows .realm-row .rl-ver'), '3.3.5a');
  assert.equal(await page.textContent('#pb-realm-ver'), '3.3.5a', 'the play bar too');
  assert.equal(await page.locator('#page-play #srv-name, #page-play #client-now').count(), 0, 'no SERVER or GAME CLIENT card on Home');
  const text = await page.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /world of warcraft|\bwow\b|warcraft|lich king|blizzard/i);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Mods: Installed and Discover tabs; the Forum (no tabs, no Friends); the arrow keys', async () => {
  const { page, ctx, errors } = await open();
  await page.click('.nav[data-page="mods"]');
  assert.deepEqual(await where(page), { nav: ['mods'], page: ['page-mods'], panes: ['pane-installed'] });
  await page.click('#tab-mods-discover');
  assert.deepEqual((await where(page)).panes, ['pane-discover']);
  assert.ok(await page.evaluate(() => window.__calls.some(([c]) => c === 'mods_catalog')), 'Discover loads the Workshop');
  // the Discover features are all there: the Themes sub-tab, the Sort and Show menus
  assert.deepEqual(await page.$$eval('#discover-tabs .ly-tab', (b) => b.map((x) => x.textContent)), ['Mods', 'Themes']);
  assert.deepEqual(await page.$$eval('#cat-sort option', (o) => o.map((x) => x.textContent)), ['Hot', 'Rising', 'Top rated', 'Most installed', 'This month', 'New', 'Updated']);
  assert.equal(await page.$$eval('#cat-cat option', (o) => o[0].textContent.replace(/ \(\d+\)$/, '')), 'All');
  await page.click('#discover-tabs [data-tab="themes"]');
  assert.ok(await page.isVisible('#themes-discover'));
  await page.click('#discover-tabs [data-tab="mods"]');
  // the arrow keys move between the page's tabs
  await page.focus('#tab-mods-discover');
  await page.keyboard.press('ArrowRight');
  assert.deepEqual((await where(page)).panes, ['pane-installed']);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'tab-mods-installed');
  // FIND MODS on Installed goes to Discover
  await page.click('#pane-installed [data-page-go="discover"]');
  assert.deepEqual((await where(page)).panes, ['pane-discover']);
  // a page remembers its last tab
  await page.click('.nav[data-page="forum"]');
  assert.deepEqual(await where(page), { nav: ['forum'], page: ['page-forum'], panes: [] });
  assert.ok(await page.isVisible('#fm-discord'), 'the Forum page has Join the Discord');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'forum_call' && a.action === 'categories')), 'opening it reads the forum');
  assert.equal(await page.locator('#page-community, #pane-friends, #nav-friends-count, .nav[data-page="community"]').count(), 0, 'no Community page, Friends tab or friends badge');
  await page.click('.nav[data-page="mods"]');
  assert.deepEqual((await where(page)).panes, ['pane-discover'], 'Mods opens on its last tab');
  assert.deepEqual(await page.evaluate(() => [localStorage.getItem('leyline.page'), JSON.parse(localStorage.getItem('leyline.tabs'))]),
    ['mods', { mods: 'discover' }]);
  assert.deepEqual(errors, []);
  await ctx.close();
});

for (const [old, want] of [['mymods', ['page-mods', 'pane-installed']], ['discover', ['page-mods', 'pane-discover']],
  ['friends', ['page-forum', null]], ['hub', ['page-forum', null]], ['community', ['page-forum', null]], ['chat', ['page-forum', null]],
  ['mods', ['page-mods', 'pane-installed']], ['modes', ['page-modes', null]], ['nonsense', ['page-play', null]]]) {
  test(`the old page id "${old}" (remembered, or from a button or link) lands on the right page and tab`, async () => {
    const { page, ctx, errors } = await open({ page: old });
    const w = await where(page);
    assert.deepEqual([w.page[0], w.panes[0] || null], want);
    await page.evaluate(() => window.LeylineNav.show('play'));
    await page.evaluate((o) => window.LeylineNav.show(o), old);
    const v = await where(page);
    assert.deepEqual([v.page[0], v.panes[0] || null], want);
    assert.deepEqual(errors, []);
    await ctx.close();
  });
}

test('the backdrop: behind the content area only, under the wash; plain when it fails or is off', async () => {
  let { page, ctx, errors } = await open();
  await page.waitForFunction(() => document.getElementById('backdrop').classList.contains('has-pic'));
  const r = await page.evaluate(() => {
    const b = document.getElementById('backdrop'), m = document.querySelector('main'), s = document.querySelector('.side');
    const cs = getComputedStyle(b);
    const rect = (e) => { const x = e.getBoundingClientRect(); return [x.left, x.top, x.width, x.height].map(Math.round); };
    return { img: cs.backgroundImage, b: rect(b), m: rect(m), sideBg: getComputedStyle(s).backgroundImage, panel: getComputedStyle(document.querySelector('.home .news')).backdropFilter };
  });
  assert.match(r.img, /linear-gradient\(rgba\(9, 11, 17, 0\.52\).*rgba\(9, 11, 17, 0\.8\) 80%\), url\("https:\/\/play\.openvanilla\.app\/wrath\/art\/leyline-shot-backdrop\.webp"\)/);
  assert.equal(r.b[0], r.m[0], 'starts at the content area\'s left edge, not behind the side bar');
  assert.ok(r.b[1] <= r.m[1] && r.b[1] + r.b[3] === r.m[1] + r.m[3], 'behind the content area, and up behind the see-through title bar');
  assert.ok(r.b[2] >= r.m[2], 'as wide as it, and on Home under the docked profile panel too');
  assert.equal(r.sideBg, 'none', 'not behind the side bar');
  assert.match(r.panel, /blur/, 'panels are a blurred layer over it');
  assert.equal(await page.isChecked('#set-backdrop'), true, 'on by default');
  // Settings › Background picture off: the plain colour, remembered
  await page.click('.nav[data-page="settings"]');
  await page.click('#set-backdrop');
  assert.equal(await page.evaluate(() => document.getElementById('backdrop').classList.contains('has-pic')), false);
  assert.equal(await page.evaluate(() => localStorage.getItem('leyline.backdrop')), 'off');
  assert.deepEqual(errors, []);
  await ctx.close();

  ({ page, ctx, errors } = await open({ backdrop: 'off' }));
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(() => document.getElementById('backdrop').classList.contains('has-pic')), false);
  assert.equal(await page.isChecked('#set-backdrop'), false);
  await ctx.close();

  ({ page, ctx, errors } = await open({}, 'fail'));
  await page.waitForFunction(() => document.getElementById('backdrop').dataset.loaded === '0');
  assert.equal(await page.evaluate(() => getComputedStyle(document.getElementById('backdrop')).backgroundColor), 'rgb(18, 21, 27)', 'the plain colour');
  assert.deepEqual(errors, []);
  await ctx.close();
});
