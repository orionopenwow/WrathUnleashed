// The launcher's words after the UX audit (owner 2026-10-30), in Chromium with a fake Tauri core: no raw errors to
// players (friendly.js), "Original rules", versions out of the prose (Details holds the technical lines), the News page
// from the website's feed with the built-in posts offline, Help in four steps, Find your game files with the Discord,
// PLAY with no game folder, Settings › Privacy, no Wine on Windows, one sign-in wording, "Add a realm", the realm count,
// the official realm's name, the Host pack words and tabs, no money link, sentence-case buttons, the Workshop's one line.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/copy.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const PICTURE = path.join(__dirname, '..', 'ui', 'art', 'leyline-bg.webp');
const RAW = 'error sending request for url (https://play.openvanilla.app/wrath/forum/api/latest?n=8): dns error: failed to lookup address';

const FAKE = (o) => {
  const calls = (window.__calls = []);
  try {
    if (o.page) localStorage.setItem('leyline.page', o.page); else localStorage.removeItem('leyline.page');
    localStorage.setItem('leyline.mode', 'online');
  } catch (_) { /* fine */ }
  const clients = o.noClients ? [] : [{ id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: 'play.openvanilla.app', locale: 'enUS' }];
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    if ((o.fail || []).includes(cmd)) throw o.raw;
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients, selected_client: clients[0] ? clients[0].id : null,
        selected_realm: 'play.openvanilla.app', wine: { enabled: false, command: 'wine', prefix: '' } },
        official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: !!o.windows, data_dir: '/tmp' };
      case 'realms_list': return { realms: [{ slug: 'official', name: 'Leyline Sample Hangout', official: true, state: 'live', build: '3.3.5a',
        version: '3.3.5a', core: 'azerothcore', tags: [], players: 5, bots: 0, address: 'play.openvanilla.app' }],
        network: { realms: 0, players: 5, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'realm_status': return { state: 'online', ping_ms: 10, players: 5 };
      case 'mods_catalog': return { categories: [], projects: [], from_cache: false, saved_at: 1, error: null };
      case 'mods_ranked': return { ids: [], metrics: {}, from_cache: false, error: null };
      case 'mods_installed': return { client: 'c335a-1', build: '3.3.5a', mods: [] };
      case 'mods_updates': return [];
      case 'check_client': return { complete: true, missing: [], exe_version: '3.3.5.12340' };
      case 'themes_list': return { active: 'dark', themes: [] };
      case 'deep_link_take': return null;
      case 'launcher_update_state': return { mode: 'auto', checking: false, downloading: false, ready: null, info: null };
      case 'host_info': return { dir: null, is_kit: false, problems: [], seeds: [], realm: null };
      case 'modes_list': return { modes: [], from_cache: false, builtin: false, saved_at: null, error: null };
      case 'p2p_flags': return { effective: { p2p_hosting: false, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case 'social_status': return false;
      case 'news_list': if (o.news) return { posts: o.news, from_cache: false }; throw 'Offline and nothing cached yet.';
      case 'forum_call': return args.action === 'categories' ? { categories: [] } : { threads: [] };
      case 'open_link': return null;
      case 'play': return 'Started.';
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts) {
  const ctx = await browser.newContext({ colorScheme: 'dark', viewport: { width: 1400, height: 860 } });
  const page = await ctx.newPage();
  const errors = [], logged = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') logged.push(m.text()); });
  await page.route('https://**', (r) => r.fulfill({ path: PICTURE, contentType: 'image/webp' }));
  await page.addInitScript(FAKE, Object.assign({ raw: RAW }, opts || {}));
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineNav && document.querySelector('.page.on') && window.LeylineApp.state());
  return { page, ctx, errors, logged };
}
const go = (page, p, tab) => page.evaluate(([p, t]) => window.LeylineNav.show(p, false, t), [p, tab]);
const text = (page, sel) => page.evaluate((s) => document.querySelector(s).innerText, sel);
const BANNED = /world\s+of\s+warcraft|\bwow\b|warcraft|lich\s+king|blizzard/i;

test('friendly.js: a sentence for players stays, a raw error never shows, its tail is dropped, it reaches the console', async () => {
  const { page, ctx, errors } = await open();
  const r = await page.evaluate((raw) => {
    const f = window.LeylineFriendly;
    return [f('Pick a game client first.'), f(raw, 'The forum is down.'), f(raw), f({ message: 'TypeError: x is undefined' }, 'Oops.'),
      f("The forum isn't answering right now (error sending request: dns error)."), f('C:\\Games\\x not found'), f(null, 'Fallback.')];
  }, RAW);
  assert.deepEqual(r, ['Pick a game client first.', 'The forum is down.', 'Something went wrong. Try again, or ask on the Discord.', 'Oops.',
    "The forum isn't answering right now.", 'Something went wrong. Try again, or ask on the Discord.', 'Fallback.']);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('no raw errors: the forum down, PLAY failing; the error goes to the console', async () => {
  const { page, ctx, errors, logged } = await open({ fail: ['forum_call', 'play'] });
  await go(page, 'forum');
  await page.waitForFunction(() => /isn't reachable/.test(document.getElementById('fm-view').textContent));
  const fm = await page.textContent('#fm-view');
  assert.match(fm, /The forum isn't reachable right now\. Try again, or ask on the Discord\./);
  assert.doesNotMatch(fm, /error sending|dns|https?:/);
  assert.equal(await page.textContent('#fm-view button'), 'Try again');
  await go(page, 'play');
  await page.click('#play-go');
  await page.waitForFunction(() => document.getElementById('play-status').textContent);
  assert.equal(await page.textContent('#play-status'), "That didn't work. Try again, or ask on the Discord.");
  assert.ok(logged.some((l) => /dns error/.test(l)), 'the raw error is in the console for whoever helps');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('News: the website feed replaces the built-in posts; offline keeps them; More on the website opens the news page', async () => {
  let { page, ctx, errors } = await open({ news: [{ tag: 'LAUNCHER', date: '2026-10-30', title: 'FROM THE SITE', items: ['one', 'two'] }] });
  await go(page, 'news');
  await page.waitForFunction(() => /FROM THE SITE/.test(document.getElementById('news-full').textContent));
  assert.deepEqual(await page.evaluate(() => window.LeylineApp.news()), [{ tag: 'LAUNCHER · 2026-10-30', title: 'FROM THE SITE', items: ['one', 'two'] }]);
  assert.equal(await page.textContent('#page-news .btn'), 'More on the website');
  await page.click('#page-news [data-link="news"]');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_link' && a.name === 'news')));
  assert.deepEqual(errors, []);
  await ctx.close();
  ({ page, ctx, errors } = await open());
  await go(page, 'news');
  assert.match(await page.textContent('#news-full'), /EVERY CLIENT, EVERY SERVER/, 'offline: the built-in posts');
  assert.match(await page.textContent('#news-full'), /Uses the client you already have/);
  assert.doesNotMatch(await page.textContent('#news-full'), /3\.3\.5a|1\.12\.1/);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Help: four steps, level 1 or boost to 80, browser play, the way to Find your game files, the Discord as a line', async () => {
  const { page, ctx, errors } = await open();
  await go(page, 'help');
  const steps = await page.$$eval('#page-help .help-steps > li > b', (b) => b.map((x) => x.textContent));
  assert.deepEqual(steps, ['Get your game files.', 'Add your folder.', 'Pick a realm.', 'Play.']);
  const help = await text(page, '#page-help');
  assert.match(help, /Level 1 or boost to 80/i);
  assert.match(help, /Play in your browser/);
  assert.match(help, /Lost files or need help\? Ask on the Discord/);
  assert.equal(await page.locator('#page-help [data-link="discord"]').count(), 0, 'no second Discord button: the title bar has it');
  assert.equal(await page.locator('#page-help [data-link="gettingstarted"]').count(), 1, 'the player guide');
  assert.doesNotMatch(help, BANNED);
  await page.click("#page-help button:has-text(\"Can't find your files? ›\")");
  assert.ok(await page.isVisible('#page-findfiles'));
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('no game folder: PLAY opens Find your game files; the bar says so; Clients points there too', async () => {
  const { page, ctx, errors } = await open({ noClients: true });
  assert.equal(await page.textContent('#play-caption'), 'NO GAME FOLDER YET');
  assert.equal(await page.textContent('#play-headline'), 'ADD YOUR GAME FOLDER');
  await page.click('#play-go');
  assert.ok(await page.isVisible('#page-findfiles'), 'not Game Clients: where to find the files');
  assert.equal(await page.evaluate(() => window.__calls.some(([c]) => c === 'play')), false);
  await go(page, 'clients');
  assert.equal(await page.textContent('#cl-list'), 'No game folder yet. Find your game files ›');
  await page.click('#cl-list button');
  assert.ok(await page.isVisible('#page-findfiles'));
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Game Clients: the version chip shows, the technical lines sit behind Details', async () => {
  const { page, ctx, errors } = await open();
  await go(page, 'clients');
  const card = page.locator('#cl-list .card').first();
  assert.equal(await card.locator('.top .build').textContent(), '3.3.5a');
  assert.equal(await card.locator('.cl-more').getAttribute('open'), null, 'closed at first');
  const seen = await card.evaluate((c) => c.innerText);
  assert.doesNotMatch(seen, /12340|30300|realmlist\.wtf/);
  await card.locator('.cl-more summary').click();
  const more = await card.locator('.cl-more').innerText();
  assert.match(more, /12340/); assert.match(more, /Interface 30300/); assert.match(more, /realmlist\.wtf/);
  await go(page, 'mods', 'installed');
  assert.equal(await page.textContent('#mods-client-note'), '3.3.5a');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Settings: Privacy in one line about the account; no Wine on Windows; Wine elsewhere', async () => {
  let { page, ctx, errors } = await open({ windows: true });
  await go(page, 'settings');
  assert.match(await text(page, '#page-settings'), /No telemetry\. Your account is optional and lives on the website\./);
  assert.equal(await page.isVisible('#wine-set'), false);
  assert.equal(await page.isVisible('#set-save'), false);
  await ctx.close();
  ({ page, ctx, errors } = await open({ windows: false }));
  await go(page, 'settings');
  assert.equal(await page.isVisible('#wine-set'), true);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('one wording: sign-in, realms, the official name, original rules, Host pack; no money link', async () => {
  const { page, ctx, errors } = await open();
  assert.equal(await page.getAttribute('#tb-account', 'title'), 'Your account lives on the website: sign in, or manage it');
  assert.equal(await page.textContent('#page-forum .fm-fine'), 'Reading here; to post, sign in on the website. Plain text and links only.');
  assert.equal((await page.textContent('.realm-add')).trim(), '+Add a realm');
  assert.equal(await page.textContent('#play-realm option[value="official"]'), 'Wrath Unleashed (the official realm)');
  assert.equal(await page.locator('[data-link="support"]').count(), 0, 'no support link at all');
  const src = await page.content();
  assert.doesNotMatch(src, /Blizzlike|ko-fi|Sample Hangout/);
  assert.match(src, /Original rules/);
  // the Host page: Start is the way in, then the Guide, then the Host pack
  await go(page, 'host');
  assert.deepEqual(await page.$$eval('#page-host .page-tab', (b) => b.map((x) => [x.textContent, x.getAttribute('aria-selected')])),
    [['Start', 'true'], ['Guide', 'false'], ['Host pack & settings', 'false']]);
  await page.click('#hc-tab-kit');
  const kit = await text(page, '#hc-pane-kit');
  assert.match(kit, /Choose the Host pack folder…/); assert.match(kit, /Get the Host pack/);
  assert.doesNotMatch(kit, /host kit|THE KIT/i);
  assert.equal(await page.isVisible('#hl-adv'), false, 'the realm list settings wait for a realm');
  // Modes: the play setting lives in the play bar
  await go(page, 'modes');
  assert.match(await page.textContent('#md-how'), /change it in the play bar/);
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('buttons: sentence case everywhere but the PLAY picture; Home says level 1 or boost to 80', async () => {
  const { page, ctx, errors } = await open();
  const shouty = [];
  for (const [p, t] of [['play'], ['realms'], ['mods', 'installed'], ['mods', 'discover'], ['host'], ['forum'], ['news'], ['settings'], ['help'],
    ['clients'], ['findfiles'], ['modes']]) {
    await go(page, p, t);
    await page.waitForTimeout(150);
    shouty.push(...await page.$$eval('.page.on button.btn, .page.on .btn, #play-form button', (b) => b
      .filter((x) => x.id !== 'play-go' && x.offsetParent !== null)
      .map((x) => x.textContent.trim()).filter((t) => /[A-Z]{3,}/.test(t) && t === t.toUpperCase())));
  }
  assert.deepEqual([...new Set(shouty)], [], 'no ALL-CAPS button labels');
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.btn')).textTransform), 'none', 'and no CSS uppercase');
  await go(page, 'play');
  await page.waitForFunction(() => /Start at level 1 or boost to 80\./.test(document.getElementById('hero').textContent));
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('Realms: the count says community realms; Mods › Discover offline: one line, no count', async () => {
  const { page, ctx, errors } = await open({ fail: ['mods_catalog'], raw: 'error sending request for url (https://x/catalog.json)' });
  await go(page, 'realms');
  await page.waitForFunction(() => document.getElementById('rl-net').textContent);
  assert.equal(await page.textContent('#rl-net'), '0 community realms · 5 playing');
  await go(page, 'mods', 'discover');
  await page.waitForFunction(() => /Can't reach the Workshop/.test(document.getElementById('cat-status').textContent));
  assert.equal(await page.textContent('#cat-status'), "Can't reach the Workshop. Try again.");
  assert.equal(await page.textContent('#cat-grid'), '', 'no second line under it');
  assert.deepEqual(errors, []);
  await ctx.close();
});
