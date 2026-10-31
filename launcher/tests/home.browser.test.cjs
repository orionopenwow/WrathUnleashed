// The launcher's Home page (ui/home.js, ui/home.css) in Chromium with a fake Tauri core: the hero gallery (the featured
// mode with its key art, what's new, browser play, hosting, a Workshop mod; a slide without its data left out), its dots,
// arrows and Left / Right keys, moving on by itself and not under prefers-reduced-motion, and the rows below the fold
// (Popular realms, Mods to try, Game modes, News, Host your own) shown with their data, hidden when empty, each click
// landing on its page.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/home.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const PICTURE = path.join(__dirname, '..', 'ui', 'art', 'leyline-bg.webp');   // the site's backdrop, stood in
const MODES = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'stream', 'playmodes.json'), 'utf8')).modes;

const FAKE = ({ empty, browser, ms, modes }) => {
  const calls = (window.__calls = []);
  try {
    localStorage.removeItem('leyline.page');
    localStorage.setItem('leyline.mode', browser ? 'browser' : 'online');
  } catch (_) { /* fine */ }
  if (ms) window.LEYLINE_HERO_MS = ms;
  const base = { official: false, kind: 'PvE', state: 'live', version: '3.3.5a', core: 'azerothcore', build: '3.3.5a', tags: [],
    players: 0, bots: 0, max_players: null, address: null };
  const R = (o) => Object.assign({}, base, o);
  const realms = empty ? [R({ slug: 'official', name: 'Dalaran Hangout', official: true, state: 'offline', address: 'play.openvanilla.app' })] : [
    R({ slug: 'official', name: 'Dalaran Hangout', official: true, players: 5, address: 'play.openvanilla.app' }),
    R({ slug: 'c-a', realm_id: 'a', name: 'Busy Den', players: 30, address: 'relay.openvanilla.app:40002' }),
    R({ slug: 'c-b', realm_id: 'b', name: 'Old Keep', build: '1.12.1', version: '1.12.1', players: 3, address: 'relay.openvanilla.app:40003' }),
    R({ slug: 'c-c', realm_id: 'c', name: 'Hidden Cata', build: '4.3.4', version: '4.3.4', players: 9 }),
    R({ slug: 'c-d', realm_id: 'd', name: 'Quiet Glade', players: null }),
    R({ slug: 'c-e', realm_id: 'e', name: 'Fifth Live', players: 1 }),
    R({ slug: 'c-f', realm_id: 'f', name: 'Asleep', state: 'offline' }),
  ];
  const P = (id, name, o) => Object.assign({ id, name, source: 'packaged', download: 'https://x/' + id, builds: ['3.3.5a'], category: 'ui', kind: 'ui',
    description: name + ' makes things better. And more.', author: 'Someone', licence: 'MIT' }, o || {});
  const catalog = empty ? { categories: [], projects: [] } : { categories: [{ id: 'ui', name: 'Interface' }, { id: 'tools', name: 'Tools' }], projects: [
    P('link:1', 'Linked Thing', { source: 'community', download: null, category: 'tools' }),
    P('mod:bars', 'Better Bars'), P('mod:maps', 'Map Plus'), P('mod:bags', 'One Bag'), P('mod:more', 'Fifth Mod'),
  ] };
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [{ id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: '' }],
        selected_client: 'c335a-1', selected_realm: 'play.openvanilla.app', wine: { enabled: false, command: 'wine', prefix: '' } },
        official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
      case 'realms_list': return { realms, network: { realms: 5, players: 48, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'realm_status': return { state: 'online', ping_ms: 10, players: 5 };
      case 'mods_catalog': return Object.assign({ from_cache: false, saved_at: 1, error: null }, catalog);
      case 'mods_ranked': return { ids: [], metrics: {}, from_cache: false, error: null };
      case 'mods_installed': return { client: 'c335a-1', build: '3.3.5a', mods: [] };
      case 'mods_updates': return [];
      case 'themes_list': return { active: 'dark', themes: [] };
      case 'deep_link_take': return null;
      case 'launcher_update_state': return { mode: 'auto', checking: false, downloading: false, ready: null, info: null };
      case 'host_info': return { dir: null, is_kit: false, problems: [], seeds: [], realm: null };
      case 'modes_list': return { modes: empty ? [] : modes, from_cache: false, builtin: false, saved_at: null, error: null };
      case 'mode_open_browser': return 'Opened it in your browser.';
      case 'p2p_flags': return { effective: { p2p_hosting: false, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case 'social_status': return false;
      case 'open_link': return null;
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts = {}, ctxOpts = {}) {
  const ctx = await browser.newContext(Object.assign({ colorScheme: 'dark', viewport: { width: 1400, height: 860 } }, ctxOpts));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('https://play.openvanilla.app/**', (r) => r.fulfill({ path: PICTURE, contentType: 'image/webp' }));
  if (opts.noArt) await page.route('**/art/modes/**', (r) => r.abort());
  await page.addInitScript(FAKE, Object.assign({ modes: MODES }, opts));
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineHome && document.querySelector('#page-play.on'));
  return { page, ctx, errors };
}
const keys = (page) => page.evaluate(() => window.LeylineHome.slides());
const current = (page) => page.evaluate(() => {
  const on = [...document.querySelectorAll('#hero-slides .hero-slide.on')];
  const dot = document.querySelector('#hero-dots .hero-dot[aria-current="true"]');
  return { on: on.map((s) => s.dataset.key), dot: dot ? Number(dot.dataset.i) : -1, i: window.LeylineHome.index() };
});
const where = (page) => page.evaluate(() => ({ page: document.querySelector('.page.on').id, panes: [...document.querySelectorAll('.page.on .tabpane.on')].map((p) => p.id) }));

test('the gallery: every slide with its data, a title, one line and one button; art for the featured mode', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => window.LeylineHome.slides().includes('mod'));
  assert.deepEqual(await keys(page), ['mode', 'news', 'browser', 'host', 'mod']);
  for (const s of await page.$$('#hero-slides .hero-slide')) {
    assert.equal(await s.$$eval('.hs-title', (x) => x.length), 1);
    assert.equal(await s.$$eval('button', (x) => x.length), 1, 'one button per slide');
  }
  const mode = page.locator('.hero-slide[data-key="mode"]');
  assert.equal(await mode.locator('img.hs-art').getAttribute('src'), 'art/modes/azeroth-survivors.webp');
  assert.equal(await mode.locator('.hs-title').textContent(), 'Azeroth Survivors');
  assert.match(await mode.locator('.hs-kick').textContent(), /Coming soon/i, 'from the modes list');
  assert.equal(await page.textContent('.hero-slide[data-key="news"] .hs-title'), 'EVERY CLIENT, EVERY SERVER', 'the newest entry');
  assert.equal(await page.textContent('.hero-slide[data-key="mod"] .hs-title'), 'Better Bars', 'the first packaged project');
  assert.equal(await page.textContent('.hero-slide[data-key="mod"] .hs-line'), 'Better Bars makes things better.', 'one short line');
  assert.equal(await page.locator('#hero-dots .hero-dot').count(), 5);
  assert.deepEqual(await current(page), { on: ['mode'], dot: 0, i: 0 });
  assert.equal(await page.locator('.hero-slide[inert]').count(), 4, 'the hidden slides take no focus');
  const text = await page.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /world of warcraft|\bwow\b|warcraft|lich king|blizzard/i);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('slides without their data are left out (no catalog, no art, browser play already on)', async () => {
  const { page, ctx, errors } = await open({ empty: true, browser: true, noArt: true, ms: 600000 });
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'mods_catalog'));
  await page.waitForFunction(() => !window.LeylineHome.slides().includes('mode'));
  assert.deepEqual(await keys(page), ['news', 'host']);
  assert.equal(await page.locator('#hero-slides .hero-slide img').count(), 0);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('dots, arrows and the Left / Right keys move the gallery; the buttons do what they say', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => window.LeylineHome.slides().length === 5);
  await page.click('#hero-dots .hero-dot[data-i="3"]');
  assert.deepEqual(await current(page), { on: ['host'], dot: 3, i: 3 });
  await page.click('#hero-next');
  assert.equal((await current(page)).i, 4);
  await page.click('#hero-next');
  assert.equal((await current(page)).i, 0, 'wraps round');
  await page.click('#hero-prev');
  assert.equal((await current(page)).i, 4);
  await page.focus('#hero-dots .hero-dot[aria-current="true"]');
  await page.keyboard.press('ArrowRight');
  assert.equal((await current(page)).i, 0);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.i), '0', 'the focus follows the dot');
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  assert.deepEqual(await current(page), { on: ['host'], dot: 3, i: 3 });
  // a slide's button, then the keys: the gallery keeps the keyboard
  await page.focus('.hero-slide.on .hs-go');
  await page.keyboard.press('ArrowRight');
  assert.equal((await current(page)).i, 4);
  assert.ok(await page.evaluate(() => document.getElementById('hero').contains(document.activeElement)));

  await page.click('.hero-slide[data-key="mod"] .hs-go');
  assert.deepEqual(await where(page), { page: 'page-mods', panes: ['pane-discover'] });
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.evaluate(() => window.LeylineHome.show(1));
  await page.click('.hero-slide[data-key="news"] .hs-go');
  assert.equal((await where(page)).page, 'page-news');
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.evaluate(() => window.LeylineHome.show(3));
  await page.click('.hero-slide[data-key="host"] .hs-go');
  assert.equal((await where(page)).page, 'page-host');
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.evaluate(() => window.LeylineHome.show(2));
  await page.click('.hero-slide[data-key="browser"] .hs-go');
  assert.equal(await page.getAttribute('.mode[data-mode="browser"]', 'aria-checked'), 'true', 'the play bar switches to BROWSER');
  assert.equal(await page.evaluate(() => localStorage.getItem('leyline.mode')), 'browser');
  assert.match(await page.textContent('.hero-slide[data-key="browser"] .hs-go'), /on/);
  await page.evaluate(() => window.LeylineHome.show(0));
  await page.click('.hero-slide[data-key="mode"] .hs-go');
  assert.equal((await where(page)).page, 'page-modes');
  await page.waitForFunction(() => { const c = document.querySelector('#md-list .md-card[data-mode="azeroth-survivors"]'); return c && c.classList.contains('md-flash'); });
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the gallery moves on by itself, stops on hover, and never under prefers-reduced-motion', async () => {
  let { page, ctx, errors } = await open({ ms: 250 });
  await page.mouse.move(5, 5);
  await page.waitForFunction(() => window.LeylineHome.index() >= 1, null, { timeout: 4000 });
  assert.equal(await page.evaluate(() => window.LeylineHome.autoOn()), true);
  const box = await page.locator('#hero').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const at = (await current(page)).i;
  await page.waitForTimeout(900);
  assert.equal((await current(page)).i, at, 'paused while the pointer is over it');
  await page.mouse.move(5, 5);
  await page.waitForFunction((a) => window.LeylineHome.index() !== a, at, { timeout: 4000 });
  assert.deepEqual(errors, []);
  await ctx.close();

  ({ page, ctx, errors } = await open({ ms: 250 }, { reducedMotion: 'reduce' }));
  await page.mouse.move(5, 5);
  await page.waitForTimeout(1200);
  assert.equal(await page.evaluate(() => window.LeylineHome.autoOn()), false);
  assert.equal((await current(page)).i, 0, 'stays on the first slide');
  await page.click('#hero-next');
  await page.waitForTimeout(800);
  assert.equal((await current(page)).i, 1, 'moves only when asked');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the rows below the fold: realms, mods, modes, news and hosting, each landing on its page', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => !document.getElementById('hm-realms').hidden && !document.getElementById('hm-mods').hidden && !document.getElementById('hm-modes').hidden);
  // the first screen is the top row as before: the rows start below the fold
  const fold = await page.evaluate(() => {
    const m = document.querySelector('main').getBoundingClientRect();
    return { main: m.bottom, more: document.getElementById('home-more').querySelector('.hm-sec:not([hidden])').getBoundingClientRect().top,
      hero: document.getElementById('hero').getBoundingClientRect().height, scrollW: document.querySelector('main').scrollWidth - document.querySelector('main').clientWidth };
  });
  assert.ok(fold.more >= fold.main, `the rows start below the fold (${fold.more} >= ${fold.main})`);
  assert.ok(fold.hero > 300, 'the hero keeps its size');
  assert.equal(fold.scrollW, 0, 'no sideways scroll');
  assert.ok(await page.isVisible('#home-cue'), 'More below');

  const names = (id) => page.$$eval(`#${id}-row .hm-name`, (n) => n.map((x) => x.textContent));
  assert.deepEqual(await names('hm-realms'), ['Dalaran Hangout', 'Busy Den', 'Old Keep', 'Quiet Glade'], 'live realms, no hidden builds, four at most');
  assert.deepEqual(await page.$$eval('#hm-realms-row .hm-card', (c) => c.map((x) => [x.querySelector('.rl-ver').textContent, x.querySelector('.hm-line').textContent])),
    [['3.3.5a', '5 playing'], ['3.3.5a', '30 playing'], ['1.12.1', '3 playing'], ['3.3.5a', 'Online']]);
  assert.deepEqual(await names('hm-mods'), ['Better Bars', 'Map Plus', 'One Bag', 'Fifth Mod'], 'packaged first, four at most');
  assert.equal(await page.textContent('#hm-mods-row .hm-card .hm-line'), 'Interface');
  assert.equal(await page.locator('#hm-modes-row .hm-card').count(), 4);
  assert.equal(await page.getAttribute('#hm-modes-row .hm-card', 'data-mode'), 'azeroth-survivors', 'the mode with art first');
  assert.equal(await page.locator('#hm-modes-row .hm-card:first-child img').getAttribute('src'), 'art/modes/azeroth-survivors.webp');
  assert.deepEqual(await names('hm-news'), ['EVERY CLIENT, EVERY SERVER', 'CHARACTER CREATE IS BACK IN COLOUR']);
  assert.equal(await page.textContent('#hm-news-row .hm-card .hm-line'), 'Finds every game client on your PC');

  await page.click('#home-cue');
  await page.waitForFunction(() => document.querySelector('main').scrollTop > 100);
  const back = () => page.evaluate(() => window.LeylineNav.show('play'));
  await page.click('#hm-realms-row .hm-card >> nth=1');
  assert.equal((await where(page)).page, 'page-realms');
  await back();
  await page.click('#hm-mods-row .hm-card >> nth=0');
  assert.deepEqual(await where(page), { page: 'page-mods', panes: ['pane-discover'] });
  await back();
  await page.click('#hm-modes-row .hm-card[data-mode="minigolf"]');
  assert.equal((await where(page)).page, 'page-modes');
  await page.waitForFunction(() => { const c = document.querySelector('#md-list .md-card[data-mode="minigolf"]'); return c && c.classList.contains('md-flash'); });
  await back();
  await page.click('#hm-news-row .hm-card >> nth=0');
  assert.equal((await where(page)).page, 'page-news');
  for (const [sel, want] of [['#hm-realms [data-hm-go]', 'page-realms'], ['#hm-mods [data-hm-go]', 'page-mods'], ['#hm-modes [data-hm-go]', 'page-modes'],
    ['#hm-news [data-hm-go]', 'page-news'], ['#hm-host-start', 'page-host'], ['#hm-host-link', 'page-host']]) {
    await back();
    await page.click(sel);
    assert.equal((await where(page)).page, want, sel);
  }
  await back();
  await page.click('#hm-host-docs');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_link' && a.name === 'docs')), 'a named link, no address from the page');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('rows without data stay hidden; Host your own is always there', async () => {
  const { page, ctx, errors } = await open({ empty: true, ms: 600000 });
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'realms_list') && window.__calls.some(([c]) => c === 'modes_list'));
  await page.waitForTimeout(200);
  const hidden = await page.evaluate(() => ['hm-realms', 'hm-mods', 'hm-modes', 'hm-news', 'hm-host'].map((id) => document.getElementById(id).hidden));
  assert.deepEqual(hidden, [true, true, true, false, false], 'only News (built in) and Host your own');
  assert.equal(await page.locator('#hm-realms-row .hm-card').count(), 0);
  assert.deepEqual(errors, []);
  await ctx.close();
});
