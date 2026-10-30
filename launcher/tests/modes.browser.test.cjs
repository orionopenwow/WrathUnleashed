// The launcher's Modes page (ui/modes.js) in Chromium, with a fake Tauri core: the nav button after Realms, the cards
// (players, kind, credit and license for third-party modes, Coming soon with a source link and no PLAY), PLAY in the
// browser (mode_open_browser by id), PLAY on the desktop (mode_prepare_desktop, then play on the official realm, with
// the client picked on the page), a client of another build refused, HOST IT for a realm type, the offline notice,
// the page remembered from last time loading by itself, and catalog text shown as text, never markup.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/modes.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const CATALOG = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'stream', 'playmodes.json'), 'utf8'));

const FAKE = ({ modes, extra, offline, browser, page }) => {
  const calls = (window.__calls = []);
  try {
    localStorage.setItem('leyline.mode', browser ? 'browser' : 'online');
    if (page) localStorage.setItem('leyline.page', page); else localStorage.removeItem('leyline.page');
  } catch (_) { /* fine */ }
  const list = modes.concat(extra || []);
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [
          { id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: '' },
          { id: 'c1121-1', name: 'My Vanilla', path: '/y', build: '1.12.1', realmlist: '' }],
        selected_client: 'c335a-1', selected_realm: 'play.openvanilla.app', wine: { enabled: true, command: 'wine', prefix: '' } },
        official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'modes_list': return { modes: list, from_cache: false, builtin: !!offline, saved_at: null, error: offline ? 'offline' : null };
      case 'mode_open_browser': return 'Opened it in your browser.';
      case 'mode_open_credit': return null;
      case 'mode_prepare_desktop': return 'Minigolf starts after you log in.';
      case 'play': return 'Started My Wrath on play.openvanilla.app.';
      case 'realms_list': return { realms: [], network: { realms: 0, players: 0, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'p2p_flags': return { effective: { p2p_hosting: false, limits: {} } };
      case 'host_info': return { dir: '', is_kit: false, problems: [], kit: null, seeds: [], realm: null };
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts = {}) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, Object.assign({ modes: CATALOG.modes }, opts));
  await page.goto(INDEX);
  if (!opts.page) await page.click('.nav[data-page="modes"]');
  await page.waitForFunction(() => document.querySelectorAll('#md-list .md-card').length > 0);
  return { page, errors };
}
const card = (page, id) => page.locator(`#md-list .md-card[data-mode="${id}"]`);
const calls = (page, name) => page.evaluate((n) => window.__calls.filter(([c]) => c === n).map(([, a]) => a), name);

test('Modes page: nav after Realms, cards, credit, Coming soon', async () => {
  const { page, errors } = await open();
  const navs = await page.$$eval('aside nav .nav', (b) => b.map((x) => x.dataset.page));
  assert.equal(navs[navs.indexOf('realms') + 1], 'modes', 'Modes comes right after Realms');
  assert.ok(await page.isVisible('#page-modes'));
  const names = await page.$$eval('#md-list .md-card .name', (n) => n.map((x) => x.textContent));
  assert.deepEqual(names, CATALOG.modes.map((m) => m.title));
  assert.equal(await page.textContent('#md-net'), '5 to play · 2 coming soon');
  const golf = await card(page, 'minigolf').textContent();
  assert.match(golf, /1-8 players/); assert.match(golf, /On our realm/); assert.match(golf, /PLAY/);
  assert.doesNotMatch(golf, /Coming soon/);
  const surv = await card(page, 'azeroth-survivors').textContent();
  assert.match(surv, /Coming soon/); assert.match(surv, /By Aethus · Open rebuild by OutThisLife · MIT or Apache-2.0/);
  assert.match(surv, /No server/); assert.match(surv, /1 player/); assert.match(surv, /Community made/);
  assert.equal(await card(page, 'azeroth-survivors').locator('.md-play').count(), 0, 'no PLAY while coming');
  const hordes = await card(page, 'hordes-of-azeroth').textContent();
  assert.match(hordes, /By jonhaldors · GPL-3.0 \(client\), GPL-2.0 \(server\)/); assert.match(hordes, /Its own realm type/);
  assert.match(hordes, /Any number of players/);
  assert.equal(await card(page, 'hordes-of-azeroth').locator('button:has-text("HOST IT")').count(), 0, 'no Host it while coming');
  await card(page, 'hordes-of-azeroth').locator('button:has-text("More source")').click();
  await card(page, 'azeroth-survivors').locator('button:has-text("Source")').click();
  assert.deepEqual(await calls(page, 'mode_open_credit'), [{ id: 'hordes-of-azeroth', n: 1 }, { id: 'azeroth-survivors', n: 0 }]);
  assert.match(await page.textContent('#md-how'), /starts your game client/);
  const text = await page.textContent('#page-modes');
  assert.doesNotMatch(text, /world of warcraft|\bwow\b|warcraft|lich king|blizzard/i);
  assert.deepEqual(errors, []);
  await page.close();
});

test('PLAY on the desktop: the pick, then play on the official realm', async () => {
  const { page, errors } = await open();
  await card(page, 'minigolf').locator('.md-play').click();
  await page.waitForFunction(() => /Started/.test(document.getElementById('md-status').textContent));
  assert.deepEqual(await calls(page, 'mode_prepare_desktop'), [{ client: 'c335a-1', id: 'minigolf' }]);
  assert.deepEqual(await calls(page, 'play'), [{ client: 'c335a-1', realm: 'play.openvanilla.app' }]);
  assert.equal(await page.textContent('#md-status'), 'Started My Wrath on play.openvanilla.app. Minigolf starts after you log in.');
  assert.deepEqual(await calls(page, 'mode_open_browser'), []);
  // another build's client: refused before anything is written
  await page.selectOption('#page-modes .client-pick', 'c1121-1');
  await card(page, 'coin-dash').locator('.md-play').click();
  await page.waitForFunction(() => /3.3.5a realm/.test(document.getElementById('md-status').textContent));
  assert.equal((await calls(page, 'mode_prepare_desktop')).length, 1);
  // a realm type: HOST IT goes to the Host page
  await card(page, 'brawl').locator('button:has-text("HOST IT")').click();
  assert.ok(await page.isVisible('#page-host'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('PLAY in the browser, offline list, remembered page, text not markup', async () => {
  const evil = { id: 'evil', title: '<img src=x onerror="window.__pwned=1">', line: '<b>bold</b> & more', kind: 'realm',
    players: { min: 1, max: 2 }, status: 'live', start: { go: 'mode:evil' }, credit: { by: '<i>x</i>', license: 'MIT', source: 'https://example.org/x' } };
  const { page, errors } = await open({ browser: true, offline: true, page: 'modes', extra: [evil] });
  assert.match(await page.textContent('#md-net'), /offline: the list built into Leyline/);
  assert.match(await page.textContent('#md-how'), /opens your web browser/);
  await card(page, 'bumper-balls').locator('.md-play').click();
  await page.waitForFunction(() => /browser/.test(document.getElementById('md-status').textContent));
  assert.deepEqual(await calls(page, 'mode_open_browser'), [{ id: 'bumper-balls' }]);
  assert.deepEqual(await calls(page, 'mode_prepare_desktop'), []);
  assert.equal(await card(page, 'evil').locator('img').count(), 0);
  assert.equal(await card(page, 'evil').locator('.name').textContent(), evil.title);
  assert.match(await card(page, 'evil').textContent(), /<b>bold<\/b> & more/);
  assert.equal(await page.evaluate(() => window.__pwned), undefined);
  assert.deepEqual(errors, []);
  await page.close();
});

test('Key art: on the Azeroth Survivors card and as the featured banner on Home, one click to its card', async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, { modes: CATALOG.modes });
  await page.goto(INDEX);
  const ban = page.locator('#page-play .news #feat-mode');
  await page.waitForFunction(() => { const i = document.querySelector('#feat-mode img'); return i && i.complete && i.naturalWidth > 0; });
  assert.equal(await ban.getAttribute('data-mode'), 'azeroth-survivors');
  assert.match(await ban.getAttribute('aria-label'), /Featured mode: Azeroth Survivors/);
  assert.ok(await page.evaluate(() => document.querySelector('.news').classList.contains('has-feat') && document.querySelector('.news').firstElementChild.id === 'feat-mode'), 'the art is the hero card\'s backdrop');
  assert.match(await ban.textContent(), /FEATURED MODE.*Azeroth Survivors.*See it in Modes/);
  assert.equal(await page.$eval('#feat-mode img', (i) => i.getAttribute('src')), 'art/modes/azeroth-survivors.webp');
  await ban.click();
  assert.ok(await page.isVisible('#page-modes'));
  await page.waitForFunction(() => { const c = document.querySelector('#md-list .md-card[data-mode="azeroth-survivors"]'); return c && c.classList.contains('md-flash'); });
  const art = card(page, 'azeroth-survivors').locator('img.md-art');
  assert.equal(await art.count(), 1);
  assert.match(await art.getAttribute('alt'), /Azeroth Survivors key art/);
  assert.ok(await art.evaluate((i) => i.complete && i.naturalWidth === 483 && i.naturalHeight === 298), 'the cropped art (no banner) loads');
  assert.ok(await card(page, 'azeroth-survivors').evaluate((c) => c.classList.contains('has-art')));
  assert.equal(await card(page, 'minigolf').locator('img').count(), 0, 'modes without art have no picture');
  assert.deepEqual(errors, []);
  await page.close();
});

test('Key art missing: no banner on Home, the card as before', async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('**/art/modes/**', (r) => r.abort());
  await page.addInitScript(FAKE, { modes: CATALOG.modes });
  await page.goto(INDEX);
  await page.waitForFunction(() => !document.getElementById('feat-mode'));
  await page.click('.nav[data-page="modes"]');
  await page.waitForFunction(() => document.querySelectorAll('#md-list .md-card').length > 0);
  await page.waitForFunction(() => !document.querySelector('#md-list .md-card[data-mode="azeroth-survivors"] img'));
  assert.equal(await card(page, 'azeroth-survivors').evaluate((c) => c.classList.contains('has-art')), false);
  assert.match(await card(page, 'azeroth-survivors').textContent(), /Coming soon/);
  assert.deepEqual(errors, []);
  await page.close();
});
