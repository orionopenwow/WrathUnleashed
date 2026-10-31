// The launcher's Home page (ui/home.js, ui/home.css) in Chromium with a fake Tauri core: the hero gallery (Join Wrath
// Unleashed first, with Play now and Join the Discord, the lineup, what's on and the latest forum threads; then the featured
// mode with its key art, what's new, browser play with the realms, hosting, your Den, a Workshop mod with its screenshots;
// a slide without its data left out; live counts; network strings shown as text, never HTML), its dots,
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

const FAKE = ({ empty, browser, ms, modes, noClients, forumDown, forumWait }) => {
  const calls = (window.__calls = []);
  try {
    localStorage.removeItem('leyline.page');
    localStorage.setItem('leyline.mode', browser ? 'browser' : 'online');
  } catch (_) { /* fine */ }
  if (ms) window.LEYLINE_HERO_MS = ms;
  const base = { official: false, kind: 'PvE', state: 'live', version: '3.3.5a', core: 'azerothcore', build: '3.3.5a', tags: [],
    players: 0, bots: 0, max_players: null, address: null };
  const R = (o) => Object.assign({}, base, o);
  const realms = empty ? [R({ slug: 'official', name: 'Wrath Unleashed', official: true, state: 'offline', address: 'play.openvanilla.app' })] : [
    R({ slug: 'official', name: 'Wrath Unleashed', official: true, players: 5, address: 'play.openvanilla.app' }),
    R({ slug: 'c-a', realm_id: 'a', name: 'Busy Den', players: 30, max_players: 60, is_new: true, kind: 'Fun', address: 'relay.openvanilla.app:40002' }),
    R({ slug: 'c-b', realm_id: 'b', name: 'Old Keep', build: '1.12.1', version: '1.12.1', players: 3, address: 'relay.openvanilla.app:40003' }),
    R({ slug: 'c-c', realm_id: 'c', name: 'Hidden Cata', build: '4.3.4', version: '4.3.4', players: 9 }),
    R({ slug: 'c-d', realm_id: 'd', name: 'Quiet Glade', players: null }),
    R({ slug: 'c-e', realm_id: 'e', name: 'Fifth Live', players: 1 }),
    R({ slug: 'c-f', realm_id: 'f', name: 'Asleep <b>zz</b>', state: 'offline' }),
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
      case 'get_state': return { version: 'test', settings: { clients: noClients ? [] : [{ id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: '' }],
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
      case 'play': return 'Started.';
      case 'open_browser_play': return null;
      case 'select': return null;
      case 'forum_call':
        if (args.action !== 'latest') return { threads: [], categories: [] };
        if (forumDown) throw 'The forum is not reachable.';
        if (forumWait) await new Promise((r) => setTimeout(r, forumWait));
        return { threads: [
          { id: 7, title: 'Golf night <img src=x onerror="window.__xss=1">', author: '<b>Pell</b>', replies: 1, created: 1, bumped: Math.floor(Date.now() / 1000) - 120, cat: 'general' },
          { id: 8, title: 'Den tour', author: 'Thistle', replies: 4, created: 1, bumped: 1, cat: 'dens' },
          { id: 9, title: 'Third', author: 'K', replies: 0, created: 1, bumped: 1, cat: 'general' },
          { id: 10, title: 'Fourth is never shown', author: 'K', replies: 0, created: 1, bumped: 1, cat: 'general' }] };
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

let window_requests = [];
async function open(opts = {}, ctxOpts = {}) {
  window_requests = [];
  const ctx = await browser.newContext(Object.assign({ colorScheme: 'dark', viewport: { width: 1400, height: 860 } }, ctxOpts));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('https://play.openvanilla.app/**', (r) => r.fulfill({ path: PICTURE, contentType: 'image/webp' }));
  if (opts.noArt) await page.route('**/art/modes/**', (r) => r.abort());
  // the site's Home screenshots: home.json as given (none: the site answers 404), a listed file missing: 404
  await page.route('https://play.openvanilla.app/wrath/art/home/**', (r) => {
    const name = r.request().url().split('/wrath/art/home/')[1];
    window_requests.push(name);
    if (name === 'home.json') return opts.homeArt ? r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' },
      body: JSON.stringify(opts.homeArt) }) : r.fulfill({ status: 404, body: 'not found', headers: { 'access-control-allow-origin': '*' } });
    if ((opts.homeMissing || []).includes(name)) return r.fulfill({ status: 404, body: 'not found' });
    return r.fulfill({ path: PICTURE, contentType: 'image/webp' });
  });
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
  assert.deepEqual(await keys(page), ['hangout', 'mode', 'news', 'browser', 'host', 'den', 'mod']);
  for (const s of await page.$$('#hero-slides .hero-slide')) {
    assert.equal(await s.$$eval('.hs-title', (x) => x.length), 1);
    const want = (await s.getAttribute('data-key')) === 'hangout' ? 2 : 1;
    assert.equal(await s.$$eval('.hs-body button', (x) => x.length), want, 'one button per slide, two on the launch slide (the realm rows on the side are links to Realms)');
  }
  const hang = page.locator('.hero-slide[data-key="hangout"]');
  assert.equal(await hang.locator('.hs-title').textContent(), 'Join Wrath Unleashed');
  assert.deepEqual(await hang.locator('.hs-body button').allTextContents(), ['Play now', 'Join the Discord']);
  assert.match(await hang.locator('.hs-line').textContent(), /\/golf and \/modes/);
  assert.deepEqual(await hang.locator('.hs-lineup .hs-rl-n b').allTextContents(), ['Wrath Unleashed'], 'the official lineup: the Hangout (no Vanilla Remastered record here)');
  const mode = page.locator('.hero-slide[data-key="mode"]');
  assert.equal(await mode.locator('img.hs-art').getAttribute('src'), 'art/modes/azeroth-survivors.webp');
  assert.equal(await mode.locator('.hs-title').textContent(), 'Azeroth Survivors');
  assert.match(await mode.locator('.hs-kick').textContent(), /Coming soon/i, 'from the modes list');
  assert.equal(await page.textContent('.hero-slide[data-key="news"] .hs-title'), 'EVERY CLIENT, EVERY SERVER', 'the newest entry');
  assert.equal(await page.textContent('.hero-slide[data-key="mod"] .hs-title'), 'Better Bars', 'the first packaged project');
  assert.equal(await page.textContent('.hero-slide[data-key="mod"] .hs-line'), 'Better Bars makes things better.', 'one short line');
  assert.equal(await page.textContent('.hero-slide[data-key="den"] .hs-title'), 'Make your Den');
  assert.equal(await page.locator('#hero-dots .hero-dot').count(), 7);
  assert.deepEqual(await current(page), { on: ['hangout'], dot: 0, i: 0 });
  assert.equal(await page.locator('.hero-slide[inert]').count(), 6, 'the hidden slides take no focus');
  const text = await page.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /world of warcraft|\bwow\b|warcraft|lich king|blizzard/i);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('slides without their data are left out (no catalog, no art, browser play already on)', async () => {
  const { page, ctx, errors } = await open({ empty: true, browser: true, noArt: true, ms: 600000 });
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'mods_catalog'));
  await page.waitForFunction(() => !window.LeylineHome.slides().includes('mode'));
  assert.deepEqual(await keys(page), ['hangout', 'news', 'host', 'den']);
  assert.deepEqual(await page.locator('.hero-slide[data-key="hangout"] .hs-chip').allTextContents(), [], 'no counts without live realms');
  assert.equal(await page.locator('.hero-slide[data-key="hangout"] .hs-whats').count(), 0, "no what's on without the modes list");
  assert.equal(await page.locator('#hero-slides .hero-slide img.hs-art').count(), 0, 'no key art (the lineup crystal icon is not art)');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('dots, arrows and the Left / Right keys move the gallery; the buttons do what they say', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => window.LeylineHome.slides().length === 7);
  await page.click('#hero-dots .hero-dot[data-i="4"]');
  assert.deepEqual(await current(page), { on: ['host'], dot: 4, i: 4 });
  await page.click('#hero-next');
  assert.equal((await current(page)).i, 5);
  await page.click('#hero-next');
  await page.click('#hero-next');
  assert.equal((await current(page)).i, 0, 'wraps round');
  await page.click('#hero-prev');
  assert.equal((await current(page)).i, 6);
  await page.focus('#hero-dots .hero-dot[aria-current="true"]');
  await page.keyboard.press('ArrowRight');
  assert.equal((await current(page)).i, 0);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.i), '0', 'the focus follows the dot');
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  assert.deepEqual(await current(page), { on: ['host'], dot: 4, i: 4 });
  // a slide's button, then the keys: the gallery keeps the keyboard
  await page.focus('.hero-slide.on .hs-go');
  await page.keyboard.press('ArrowRight');
  assert.equal((await current(page)).i, 5);
  assert.ok(await page.evaluate(() => document.getElementById('hero').contains(document.activeElement)));

  await page.evaluate(() => window.LeylineHome.show(6));
  await page.click('.hero-slide[data-key="mod"] .hs-go');
  assert.deepEqual(await where(page), { page: 'page-mods', panes: ['pane-discover'] });
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.evaluate(() => window.LeylineHome.show(2));
  await page.click('.hero-slide[data-key="news"] .hs-go');
  assert.equal((await where(page)).page, 'page-news');
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.evaluate(() => window.LeylineHome.show(4));
  await page.click('.hero-slide[data-key="host"] .hs-go');
  assert.equal((await where(page)).page, 'page-host');
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.evaluate(() => window.LeylineHome.show(3));
  await page.click('.hero-slide[data-key="browser"] .hs-go');
  assert.equal(await page.textContent('#pb-realm'), 'In your browser', 'the play bar switches to browser play');
  assert.equal(await page.evaluate(() => localStorage.getItem('leyline.mode')), 'browser');
  assert.match(await page.textContent('.hero-slide[data-key="browser"] .hs-go'), /on/);
  await page.evaluate(() => window.LeylineHome.show(1));
  await page.click('.hero-slide[data-key="mode"] .hs-go');
  assert.equal((await where(page)).page, 'page-modes');
  await page.waitForFunction(() => { const c = document.querySelector('#md-list .md-card[data-mode="azeroth-survivors"]'); return c && c.classList.contains('md-flash'); });
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the launch slide: Play now selects Wrath Unleashed and plays; Join the Discord opens the named link', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => window.LeylineHome.slides()[0] === 'hangout');
  await page.evaluate(() => window.LeylineHome.show(0));
  await page.click('.hero-slide[data-key="hangout"] .hs-go2');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_link' && a.name === 'discord')), 'openLink("discord")');
  await page.evaluate(() => { const r = document.getElementById('play-realm'); r.value = 'custom'; document.getElementById('play-custom').value = 'relay.openvanilla.app:40002'; });
  await page.click('.hero-slide[data-key="hangout"] .hs-go');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'play'));
  assert.equal(await page.inputValue('#play-realm'), 'official');
  assert.deepEqual(await page.evaluate(() => window.__calls.find(([c]) => c === 'play')[1]), { client: 'c335a-1', realm: 'play.openvanilla.app' }, 'the 3.3.5a client on the Hangout');
  assert.equal(await page.textContent('#pb-realm'), 'Wrath Unleashed');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the launch slide without a 3.3.5a client: Play now is browser play (the Hangout in the browser, nothing to install)', async () => {
  const { page, ctx, errors } = await open({ ms: 600000, noClients: true });
  await page.waitForFunction(() => window.LeylineHome.slides()[0] === 'hangout');
  await page.evaluate(() => window.LeylineHome.show(0));
  await page.click('.hero-slide[data-key="hangout"] .hs-go');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'open_browser_play'));
  assert.equal(await page.evaluate(() => window.LeylineApp.mode()), 'browser');
  assert.ok(!(await page.evaluate(() => window.__calls.some(([c]) => c === 'play'))));
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
  assert.deepEqual(await names('hm-realms'), ['Wrath Unleashed', 'Busy Den', 'Old Keep', 'Quiet Glade'], 'live realms, no hidden builds, four at most');
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

const showKey = (page, k) => page.evaluate((k) => window.LeylineHome.show(window.LeylineHome.slides().indexOf(k)), k);

test('the launch slide is full: live counts, the lineup, three modes with pictures, the latest forum threads as text', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => document.querySelectorAll('.hero-slide[data-key="hangout"] .hs-forum .hs-fr').length === 3);
  await page.waitForFunction(() => document.querySelector('.hero-slide[data-key="hangout"] .hs-mt'));
  const hang = page.locator('.hero-slide[data-key="hangout"]');
  // live realms with an offered build: the Hangout 5, Busy Den 30, Old Keep 3, Quiet Glade (no count), Fifth Live 1
  assert.deepEqual(await hang.locator('.hs-chip').allTextContents(), ['5 on Wrath Unleashed now', '39 playing on 5 realms']);
  assert.deepEqual(await hang.locator('.hs-mt').evaluateAll((b) => b.map((x) => [x.dataset.mode, x.querySelector('i').textContent, x.querySelector('.hs-mt-pic b').textContent])),
    [['minigolf', '/golf', 'M'], ['bumper-balls', '/modes', 'B'], ['coin-dash', '/modes', 'C']], 'live modes on the realm, each with its colour and initial (no screenshots listed)');
  // forum strings are text: the title's tag is shown, not made; three at most
  const rows = await hang.locator('.hs-forum .hs-fr').evaluateAll((b) => b.map((x) => [x.querySelector('b').textContent, x.querySelector('i').textContent]));
  assert.equal(rows[0][0], 'Golf night <img src=x onerror="window.__xss=1">');
  assert.match(rows[0][1], /^<b>Pell<\/b> · 1 reply · 2m ago$/);
  assert.deepEqual(rows.slice(1).map((r) => r[0]), ['Den tour', 'Third']);
  assert.equal(await page.locator('#hero img[src="x"], #hero .hs-forum b b').count(), 0, 'no element made from a forum string');
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.equal(await page.evaluate(() => window.__calls.filter(([c, a]) => c === 'forum_call' && a.action === 'latest' && a.args.n === 3).length >= 1), true);
  // a thread opens on the Forum page, a mode on Modes
  await hang.locator('.hs-forum .hs-fr').nth(1).click();
  assert.equal((await where(page)).page, 'page-forum');
  assert.deepEqual(await page.evaluate(() => window.LeylineForum.view()), { kind: 'thread', id: 8 });
  await page.evaluate(() => window.LeylineNav.show('play'));
  await showKey(page, 'hangout');
  await hang.locator('.hs-mt[data-mode="bumper-balls"]').click();
  assert.equal((await where(page)).page, 'page-modes');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the forum unreachable: one row to the Forum page; the card keeps its size while the threads come in', async () => {
  let { page, ctx, errors } = await open({ ms: 600000, forumDown: true });
  await page.waitForSelector('.hero-slide[data-key="hangout"] .hs-fr-none');
  assert.equal(await page.textContent('.hero-slide[data-key="hangout"] .hs-fr-none b'), 'Say hello on the forum');
  await page.click('.hero-slide[data-key="hangout"] .hs-fr-none button');
  assert.equal((await where(page)).page, 'page-forum');
  assert.deepEqual(errors, []);
  await ctx.close();

  ({ page, ctx, errors } = await open({ ms: 600000, forumWait: 700 }));
  await page.waitForSelector('.hero-slide[data-key="hangout"] .hs-fr-wait');
  const box = () => page.evaluate(() => {
    const c = document.querySelector('.hero-slide[data-key="hangout"] .hs-forum-card').getBoundingClientRect();
    const b = document.querySelector('.hero-slide[data-key="hangout"] .hs-body').getBoundingClientRect();
    return { card: Math.round(c.height), body: Math.round(b.top), hero: Math.round(document.getElementById('hero').getBoundingClientRect().height) };
  });
  const before = await box();
  await page.waitForSelector('.hero-slide[data-key="hangout"] .hs-forum .hs-fr');
  assert.deepEqual(await box(), before, 'no layout shift when the threads arrive');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the realms beside browser play: kind, New, version, players and a bar of how full; names as text', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => document.querySelectorAll('.hero-slide[data-key="browser"] .hs-rich .hs-rl').length > 3);
  const rows = await page.locator('.hero-slide[data-key="browser"] .hs-rich .hs-rl').evaluateAll((b) => b.map((x) => ({
    name: x.querySelector('.hs-rl-n b').textContent, sub: x.querySelector('.hs-rl-n i').textContent,
    ver: (x.querySelector('.rl-ver') || {}).textContent, p: x.querySelector('.hs-rl-p').textContent, bar: x.querySelector('.hs-rl-bar i').style.width })));
  assert.deepEqual(rows[0], { name: 'Wrath Unleashed', sub: 'Run by Leyline', ver: '3.3.5a', p: '5', bar: '6%' });
  assert.deepEqual(rows[1], { name: 'Busy Den', sub: 'FunNew', ver: '3.3.5a', p: '30', bar: '50%' }, 'its limit is 60');
  assert.ok(!rows.some((r) => r.name === 'Hidden Cata'), 'a build not offered is left out');
  assert.deepEqual(rows[rows.length - 1], { name: 'Asleep <b>zz</b>', sub: 'Offline for now', ver: '3.3.5a', p: '–', bar: '0%' });
  assert.equal(await page.locator('.hero-slide[data-key="browser"] .hs-rl-n b b').count(), 0);
  assert.deepEqual(await page.locator('.hero-slide[data-key="browser"] .hs-chip').allTextContents(), ['39 playing now', '5 realms live']);
  assert.deepEqual(await page.locator('.hero-slide[data-key="host"] .hs-chip').allTextContents(), ['4 community realms live', '1 new on the list', 'No ports to open']);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the Den slide opens the Host page with the Den picked; the Workshop slide shows site screenshots only', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => window.LeylineHome.slides().includes('mod'));
  assert.deepEqual(await page.locator('.hero-slide[data-key="den"] .hs-steps .hs-st-t b').allTextContents(), ['A white room', 'Edit mode', 'Invite friends']);
  await page.evaluate(() => document.addEventListener('leyline:host-ruleset', (e) => { window.__ruleset = e.detail.profile; }));
  await showKey(page, 'den');
  await page.click('.hero-slide[data-key="den"] .hs-go');
  assert.equal((await where(page)).page, 'page-host');
  assert.equal(await page.evaluate(() => window.__ruleset), 'den');
  await page.evaluate(() => window.LeylineNav.show('play'));

  const mod = page.locator('.hero-slide[data-key="mod"]');
  assert.equal(await mod.locator('.hs-shot.front img').getAttribute('src'), 'https://play.openvanilla.app/wrath/mods/bars/shot/0');
  assert.equal(await mod.locator('.hs-shot.front .hs-shot-cap b').textContent(), 'Better Bars');
  assert.deepEqual(await mod.locator('.hs-more .hs-wm b').allTextContents(), ['Map Plus', 'One Bag', 'Fifth Mod', 'Linked Thing']);
  assert.deepEqual(await mod.locator('.hs-chip').allTextContents(), ['4 ready to install', '2 categories']);
  const srcs = await page.$$eval('#hero img', (i) => i.map((x) => x.getAttribute('src')));
  assert.ok(srcs.every((u) => u.startsWith('https://play.openvanilla.app/wrath/') || u.startsWith('art/')), 'pictures from the site or the launcher only: ' + srcs.join(' '));
  assert.deepEqual(await page.evaluate(() => [
    window.LeylineHome.thumbUrl({ id: 'x', thumb: 'https://evil.example/a.png' }),
    window.LeylineHome.thumbUrl({ id: 'x', thumb: '/wrath/../etc/passwd' }),
    window.LeylineHome.thumbUrl({ id: 'x', screenshots: ['/wrath/mods/x/shot/2'] }),
    window.LeylineHome.thumbUrl({ id: 'link:1', source: 'community', repo: 'https://github.com/Some/Repo' }),
  ]), ['', '', 'https://play.openvanilla.app/wrath/mods/x/shot/2', 'https://play.openvanilla.app/wrath/art/hub-thumbs/some__repo.webp']);
  await showKey(page, 'mod');
  await mod.locator('.hs-more .hs-wm').first().click();
  assert.deepEqual(await where(page), { page: 'page-mods', panes: ['pane-discover'] });
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('every slide fits at 1100 px and 1400 px: words, panel and picture apart, nothing off the slide; motion only when allowed', async () => {
  for (const viewport of [{ width: 1100, height: 760 }, { width: 1400, height: 860 }]) {
    const { page, ctx, errors } = await open({ ms: 600000 }, { viewport });
    await page.waitForFunction(() => window.LeylineHome.slides().length === 7 && document.querySelector('.hs-forum .hs-fr'));
    for (const k of await keys(page)) {
      await showKey(page, k);
      await page.waitForTimeout(500);
      const r = await page.evaluate(() => {
        const s = document.querySelector('.hero-slide.on');
        const box = (q) => { const e = s.querySelector(q); if (!e) return null; const b = e.getBoundingClientRect(); return { l: b.left, r: b.right, t: b.top, b: b.bottom }; };
        const hero = document.getElementById('hero').getBoundingClientRect();
        const words = [...s.querySelectorAll('.hs-body > *')].map((e) => e.getBoundingClientRect());
        return { key: s.dataset.key, hero: { l: hero.left, r: hero.right, t: hero.top, b: hero.bottom }, side: box('.hs-side'), ill: box('.hs-ill'),
          body: { l: Math.min(...words.map((w) => w.left)), r: Math.max(...words.map((w) => w.right)), t: Math.min(...words.map((w) => w.top)), b: Math.max(...words.map((w) => w.bottom)) },
          scroll: document.querySelector('main').scrollWidth - document.querySelector('main').clientWidth };
      });
      const apart = (a, b) => a.r <= b.l + 1 || b.r <= a.l + 1 || a.b <= b.t + 1 || b.b <= a.t + 1;
      const inside = (a) => a.l >= r.hero.l - 1 && a.r <= r.hero.r + 1 && a.t >= r.hero.t - 1 && a.b <= r.hero.b + 1;
      assert.equal(r.scroll, 0, `${k} @${viewport.width}: no sideways scroll`);
      assert.ok(inside(r.body), `${k} @${viewport.width}: the words on the slide`);
      if (r.side) { assert.ok(apart(r.side, r.body), `${k} @${viewport.width}: the panel clear of the words ${JSON.stringify(r)}`); assert.ok(inside(r.side), `${k} @${viewport.width}: the panel on the slide`); }
      if (r.ill) assert.ok(apart(r.ill, r.body), `${k} @${viewport.width}: the picture clear of the words`);
    }
    const anim = await page.evaluate(() => { window.LeylineHome.show(6); return getComputedStyle(document.querySelector('.hero-slide.on .hs-shot.b1')).animationName; });
    assert.equal(anim, 'hs-drift-a');
    assert.deepEqual(errors, []);
    await ctx.close();
  }
  const { page, ctx } = await open({ ms: 600000 }, { reducedMotion: 'reduce' });
  await page.waitForFunction(() => window.LeylineHome.slides().includes('mod'));
  assert.equal(await page.evaluate(() => { window.LeylineHome.show(window.LeylineHome.slides().indexOf('mod')); return getComputedStyle(document.querySelector('.hero-slide.on .hs-shot.b1')).animationName; }), 'none', 'still under reduced motion');
  await ctx.close();
});

const HOME = { version: 1, slides: {
  hangout: [{ file: 'hangout.webp', alt: 'Players <b>in</b> Dalaran', credit: 'Shot by <i>Orion</i>' }],
  browser: [{ file: 'browser.webp', alt: 'In a tab', credit: '' }],
  host: [{ file: 'host.webp', alt: 'A realm', credit: '' }],
  den: [{ file: 'den.webp', alt: 'A Den', credit: '' }],
  news: [{ file: '../news.webp', alt: 'no' }, { file: 'https://evil.example/x.webp' }],
  'mode-minigolf': [{ file: 'mode-minigolf.webp', alt: '' }],
  'Bad Id': [{ file: 'bad.webp' }],
} };

test('in-game screenshots: from the site\'s home.json only, filling the slide under a scrim; alt and credit as text; no drawings', async () => {
  const { page, ctx, errors } = await open({ ms: 600000, homeArt: HOME, homeMissing: ['den.webp'] });
  await page.waitForFunction(() => document.querySelector('.hero-slide[data-key="hangout"].has-photo') && document.querySelector('.hero-slide[data-key="host"].has-photo'));
  const shots = await page.$$eval('#hero .hs-photo', (i) => i.map((x) => [x.closest('.hero-slide').dataset.key, x.getAttribute('src'), x.getAttribute('alt')]));
  assert.deepEqual(shots.sort(), [
    ['browser', 'https://play.openvanilla.app/wrath/art/home/browser.webp', 'In a tab'],
    ['hangout', 'https://play.openvanilla.app/wrath/art/home/hangout.webp', 'Players <b>in</b> Dalaran'],
    ['host', 'https://play.openvanilla.app/wrath/art/home/host.webp', 'A realm'],
  ], 'den.webp is missing (404: dropped), news lists only bad names, mode and Workshop slides keep their own pictures');
  assert.equal(await page.textContent('.hero-slide[data-key="hangout"] .hs-credit'), 'Shot by <i>Orion</i>');
  assert.equal(await page.locator('#hero .hs-credit i, #hero .hs-photo ~ b').count(), 0, 'no element made from home.json');
  const den = page.locator('.hero-slide[data-key="den"]');
  assert.equal(await den.evaluate((s) => s.classList.contains('has-photo')), false, 'a missing screenshot: the plain gradient');
  assert.match(await den.evaluate((s) => getComputedStyle(s, '::before').backgroundImage), /gradient/);
  assert.equal(await page.locator('.hero-slide[data-key="news"] .hs-photo').count(), 0);
  assert.equal(await page.locator('#hero-slides svg').count(), 0, 'no drawings on any slide');
  // the words turn light over a screenshot; the image fills the slide
  const fit = await page.evaluate(() => {
    window.LeylineHome.show(0);
    const s = document.querySelector('.hero-slide.on'), img = s.querySelector('.hs-photo');
    // layout sizes (the picture eases from a 3 % zoom, the slide slides in): it covers the slide
    return { fill: getComputedStyle(img).objectFit, w: img.offsetWidth === s.offsetWidth && img.offsetLeft === 0, h: img.offsetHeight === s.offsetHeight && img.offsetTop === 0,
      title: getComputedStyle(s.querySelector('.hs-title')).color, dots: document.getElementById('hero').classList.contains('on-art') };
  });
  assert.deepEqual(fit, { fill: 'cover', w: true, h: true, title: 'rgb(255, 255, 255)', dots: true });
  // the minigolf tile gets its listed picture
  assert.equal(await page.getAttribute('.hs-mt[data-mode="minigolf"] .hs-mt-pic img', 'src'), 'https://play.openvanilla.app/wrath/art/home/mode-minigolf.webp');
  assert.ok(window_requests.every((n) => /^(home\.json|[a-z0-9-]+\.webp)$/.test(n)), window_requests.join(' '));
  assert.ok(!window_requests.includes('bad.webp') && !window_requests.some((n) => n.includes('news')), 'only listed, well-named files');
  assert.deepEqual(await page.evaluate(() => {
    const H = window.LeylineHome;
    return [H.HOME_ART, Object.keys(H.readHomeArt({ slides: { a: { file: 'a.webp' }, b: [{ file: 'b.png' }], c: [{ file: 'c/d.webp' }], 'e-2': [{ file: 'e-2.jpg' }] } })),
      H.readHomeArt(null), H.readHomeArt({ slides: { a: [{ file: 'a.webp', alt: 5, credit: 'x'.repeat(300) }] } }).a[0].credit.length];
  }), ['https://play.openvanilla.app/wrath/art/home/', ['a', 'e-2'], {}, 120]);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('no home.json on the site: every slide keeps its gradient and no screenshot is asked for', async () => {
  const { page, ctx, errors } = await open({ ms: 600000 });
  await page.waitForFunction(() => window.LeylineHome.slides().includes('mod'));
  await page.waitForTimeout(400);
  assert.deepEqual(window_requests, ['home.json']);
  assert.equal(await page.locator('#hero .hs-photo, #hero .has-photo').count(), 0);
  assert.deepEqual(errors, []);
  await ctx.close();
});
