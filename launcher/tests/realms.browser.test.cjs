// The launcher's Realms page and the Host page's realm list details (ui/app.js, ui/host.js) in Chromium, with a fake
// Tauri core: the network order as realms.rs gives it, the network line, each realm dressed like the website's realm
// list made simple (the official realm first; icon, gold client version, one tag: Official or Featured; one line, type ·
// core, the rest on hover; players with a fill bar; offline dimmed), the search box, the FILTERS popover (build, rules
// tag, region, language, has players now, "Only realms my clients can play") with its count, the … menu, Report,
// direct connect only with the p2p_hosting flag on, the Host your own banner, the empty state, and saving the details.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/realms.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');

const FAKE = (p2p) => {
  const calls = (window.__calls = []);
  const base = { official: false, kind: 'PvE', ruleset: 'main', state: 'live', version: '3.3.5a', core: 'azerothcore',
    build: '3.3.5a', tags: [], region: null, region_estimated: false, language: null, max_players: null, uptime_24h: null,
    uptime_7d: null, is_new: false, score: 0, featured: false, verified: false, direct: false, rules: [], claimed: true,
    players: 0, bots: 0, tagline: '', summary: '', join_url: null, discord: null, relay: 'relay.openvanilla.app' };
  const R = (o) => Object.assign({}, base, o, { report_url: o.official ? null : `https://play.openvanilla.app/wrath/realms/report?realm=${o.realm_id}` });
  const realms = [
    R({ slug: 'c-dddddddddddddddd', realm_id: 'dddddddddddddddd', name: 'Picked', featured: true, verified: true, build: '1.12.1',
        core: 'vmangos', tags: ['pvp', 'rp'], region: 'eu', language: 'de', uptime_7d: 97, players: 2, address: 'relay.openvanilla.app:40020', group: 'featured' }),
    R({ slug: 'official', name: 'Leyline Sample Hangout', official: true, temporary: true, tagline: 'Temporary: our own realm.', address: 'play.openvanilla.app', group: 'official' }),
    R({ slug: 'c-bbbbbbbbbbbbbbbb', realm_id: 'bbbbbbbbbbbbbbbb', name: 'Busy Den', tags: ['bots'], region: 'na-east', region_estimated: true,
        is_new: true, players: 30, bots: 40, max_players: 100, uptime_24h: 70, direct: true, address: 'relay.openvanilla.app:40002', group: 'community' }),
    R({ slug: 'c-cccccccccccccccc', realm_id: 'cccccccccccccccc', name: 'Asleep', state: 'offline', address: 'relay.openvanilla.app:40004', group: 'offline' }),
  ];
  let details = { tags: ['rp'], region: 'eu', language: 'de', max_players: null, direct: false };
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [{ id: 'c335a-1', name: 'My Wrath', path: '/x', build: '3.3.5a', realmlist: '' }],
        selected_client: 'c335a-1', selected_realm: 'play.openvanilla.app', wine: { enabled: true, command: 'wine', prefix: '' } },
        official_realm: 'play.openvanilla.app', browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'realms_list': return { realms, network: { realms: 3, players: 33, bots: 40 }, from_cache: false, saved_at: 1, error: null };
      case 'p2p_flags': return { effective: { p2p_hosting: p2p, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case 'host_listing': return details;
      case 'host_listing_set': details = args.details; return 'Saved. The realm list shows them within a minute.';
      case 'open_url': return null;
      case 'back_to_official': return 'Back on the official realm.';
      case 'restore_realmlist': return 'Your own realmlist is back.';
      case 'deep_link_take': { const l = window.__link || null; window.__link = null; return l; }
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(p2p) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, p2p);
  await page.goto(INDEX);
  await page.click('.nav[data-page="realms"]');
  await page.waitForFunction(() => document.querySelectorAll('#rl-list .realm-card').length > 0);
  return { page, errors };
}
const names = (page) => page.$$eval('#rl-list .realm-card .name', (n) => n.map((x) => x.textContent));

test('Realms page: the official realm first, the slim line, one tag, players, Report, Host your own', async () => {
  const { page, errors } = await open(false);
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Picked', 'Busy Den', 'Asleep'], 'the official realm first, then the network order');
  assert.equal(await page.textContent('#rl-net'), '3 realms · 33 playing');
  assert.equal(await page.getAttribute('#rl-net', 'title'), '40 bots too');
  const cards = page.locator('#rl-list .realm-card');
  const badges = (i) => cards.nth(i).locator('.rl-bdg').allTextContents();
  assert.deepEqual(await badges(0), ['Official'], 'no badge pile: Official or Featured only');
  assert.deepEqual(await badges(1), ['Featured']);
  assert.deepEqual(await badges(2), []);
  assert.equal(await cards.nth(0).locator('.rl-bdg').getAttribute('title'), 'Temporary: our own realm for now');
  assert.equal(await cards.nth(1).locator('.rl-ok').getAttribute('title'), 'Verified host: checked by Leyline staff');
  assert.equal(await cards.nth(1).locator('.rl-note').textContent(), 'Needs your own 1.12.1 client', 'a quiet note only when it applies');
  assert.equal(await cards.nth(2).locator('.rl-note').count(), 0);
  assert.equal(await page.locator('#rl-list .rl-addr').count(), 0, 'no address chip');
  assert.equal(await cards.nth(1).locator('.rl-meta').textContent(), 'PvE · vMaNGOS', 'one line: type · core');
  const more = await cards.nth(1).locator('.rl-meta').getAttribute('title');
  assert.match(more, /Community realm/); assert.match(more, /Europe/); assert.match(more, /PvP/); assert.match(more, /97% up · 7 d/);
  assert.match(more, /Realmlist: relay\.openvanilla\.app:40020/);
  assert.match(await cards.nth(2).locator('.rl-meta').getAttribute('title'), /New.*North America east \(estimated\).*70% up · 24 h/);
  assert.match(await cards.nth(0).locator('.rl-meta').getAttribute('title'), /Run by Leyline/);
  assert.ok(await cards.nth(0).evaluate((e) => e.classList.contains('on')), 'the picked realm is lit');
  assert.deepEqual(await cards.locator('.rl-ver').allTextContents(), ['3.3.5a', '1.12.1', '3.3.5a', '3.3.5a'], 'the gold client version');
  // the icon: the crystal mark for the official realm, else the initial on a colour from the name
  assert.equal(await cards.nth(0).locator('.rl-ic img').getAttribute('src'), 'art/brand/leyline-crystal-256.webp');
  assert.equal(await cards.nth(1).locator('.rl-ic').textContent(), 'P');
  const hue = (i) => cards.nth(i).locator('.rl-ic').evaluate((e) => e.style.getPropertyValue('--h'));
  assert.match(await hue(1), /^\d+$/);
  assert.notEqual(await hue(1), await hue(2), 'a hue from the name');
  assert.equal(await cards.nth(2).locator('.rl-pop').textContent(), '30 / 100');
  assert.equal(await cards.nth(2).locator('.rl-pop .state').getAttribute('title'), '30 of 100 playing · 40 bots');
  assert.equal(await cards.nth(2).locator('.rl-bar i').evaluate((e) => e.style.width), '30%', 'players fill the bar');
  assert.ok(await cards.nth(3).evaluate((e) => e.classList.contains('off') && getComputedStyle(e).opacity < 1), 'an offline realm is dimmed');
  assert.equal(await cards.nth(3).locator('.rl-bar').count(), 0);
  assert.equal(await cards.nth(1).locator('.acts .btn').first().textContent(), 'PLAY');
  assert.doesNotMatch(await cards.nth(2).textContent(), /Direct connect/, 'direct connect only with p2p_hosting on');
  assert.equal(await cards.nth(0).locator('button:has-text("Report")').count(), 0, 'no Report on the sample');
  await cards.nth(2).locator('button:has-text("Report")').click();
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_url' && a.url === 'https://play.openvanilla.app/wrath/realms/report?realm=bbbbbbbbbbbbbbbb')));
  // the search box
  await page.fill('#rl-q', 'busy');
  assert.deepEqual(await names(page), ['Busy Den']);
  await page.fill('#rl-q', 'nothing like it');
  assert.match(await page.textContent('#rl-list .rl-empty'), /No realm called/);
  await page.click('#rl-list .rl-empty button');
  assert.equal(await page.inputValue('#rl-q'), '');
  assert.equal((await names(page)).length, 4);
  // Host your own: a slim banner, two buttons to the Host page
  assert.equal(await page.locator('#rl-host-cta ol').count(), 0);
  await page.click('#rl-host-link');
  assert.ok(await page.locator('#page-host').evaluate((e) => e.classList.contains('on')));
  await page.click('.nav[data-page="realms"]');
  await page.click('#rl-host');
  assert.ok(await page.locator('#page-host').evaluate((e) => e.classList.contains('on')));
  assert.deepEqual(errors, []);
});

test('Realms page: the FILTERS popover, its count, Clear filters; the … menu', async () => {
  const { page, errors } = await open(false);
  assert.ok(await page.isHidden('#rl-filters'), 'closed at first');
  assert.ok(await page.isHidden('#rl-fcount'), 'no count with no filters');
  await page.click('#rl-filters-btn');
  assert.ok(await page.isVisible('#rl-filters'));
  assert.equal(await page.getAttribute('#rl-filters-btn', 'aria-expanded'), 'true');
  const opts = await page.$$eval('#rl-f-tag option', (o) => o.map((x) => x.value));
  assert.deepEqual(opts, ['', 'bots', 'pvp', 'rp']);
  await page.selectOption('#rl-f-tag', 'pvp');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Picked'], 'tag filter; the sample stays');
  assert.equal(await page.textContent('#rl-fcount'), '1');
  assert.equal(await page.getAttribute('#rl-filters-btn', 'aria-label'), 'Filters, 1 on');
  await page.selectOption('#rl-f-tag', '');
  await page.selectOption('#rl-f-region', 'na-east');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Busy Den'], 'an estimated region counts');
  await page.check('#rl-f-now');
  assert.equal(await page.textContent('#rl-fcount'), '2');
  await page.selectOption('#rl-f-region', '');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Picked', 'Busy Den'], 'has players now');
  await page.uncheck('#rl-f-now');
  await page.selectOption('#rl-f-build', '1.12.1');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Picked']);
  await page.selectOption('#rl-f-build', '');
  await page.check('#rl-mine');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Busy Den', 'Asleep'], 'Only realms my clients can play still works');
  await page.selectOption('#rl-f-build', '1.12.1');
  assert.equal(await page.textContent('#rl-fcount'), '2');
  assert.match(await page.textContent('#rl-list .rl-empty'), /No realms match these filters/);
  await page.click('#rl-f-clear');
  assert.ok(await page.isHidden('#rl-fcount'));
  assert.equal(await page.isChecked('#rl-mine'), false);
  assert.equal((await names(page)).length, 4);
  // Escape and a click outside close it
  await page.keyboard.press('Escape');
  assert.ok(await page.isHidden('#rl-filters'));
  await page.click('#rl-filters-btn');
  await page.click('#rl-net');
  assert.ok(await page.isHidden('#rl-filters'));
  // the … menu: Back to the official realm, Use my own realmlist
  assert.ok(await page.isHidden('#rl-back'));
  await page.click('#rl-more');
  assert.deepEqual(await page.$$eval('#rl-menu [role="menuitem"]', (b) => b.map((x) => x.textContent)), ['Back to the official realm', 'Use my own realmlist']);
  await page.click('#rl-back');
  assert.ok(await page.isHidden('#rl-menu'), 'a choice closes the menu');
  assert.ok(await page.evaluate(() => window.__calls.some(([c]) => c === 'back_to_official')));
  assert.deepEqual(errors, []);
});

test('Realms page: no community realms: one line and HOST ONE', async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, false);
  await page.addInitScript(() => {
    const inner = window.__TAURI__.core.invoke;
    window.__TAURI__.core.invoke = async (cmd, args) => {
      const r = await inner(cmd, args);
      if (cmd === 'realms_list') r.realms = r.realms.filter((x) => x.official);
      return r;
    };
  });
  await page.goto(INDEX);
  await page.click('.nav[data-page="realms"]');
  await page.waitForFunction(() => document.querySelector('#rl-list .rl-empty'));
  assert.match(await page.textContent('#rl-list .rl-empty'), /No community realms yet/);
  await page.click('#rl-list .rl-empty button:has-text("HOST ONE")');
  assert.ok(await page.locator('#page-host').evaluate((e) => e.classList.contains('on')));
  assert.deepEqual(errors, []);
  await page.close();
});

test('Direct connect shows with p2p_hosting on; the Host page saves the realm list details', async () => {
  const { page, errors } = await open(true);
  await page.click('#rl-refresh');
  await page.waitForTimeout(100);
  assert.match(await page.locator('#rl-list .realm-card').nth(2).textContent(), /Direct connect available/, 'on the one line');
  await page.click('.nav[data-page="host"]');
  await page.waitForFunction(() => document.querySelector('#hl-card input[value="rp"]') && document.querySelector('#hl-card input[value="rp"]').checked);
  assert.equal(await page.inputValue('#hl-card select'), 'eu');
  await page.check('#hl-card input[value="pvp"]');
  await page.fill('#hl-card input[type="number"]', '80');
  await page.click('#hl-card button:has-text("SAVE")');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_listing_set'));
  const sent = await page.evaluate(() => window.__calls.find(([c]) => c === 'host_listing_set')[1].details);
  assert.deepEqual(sent, { tags: ['pvp', 'rp'], region: 'eu', language: 'de', max_players: 80, direct: false }, 'direct stays off unless ticked');
  assert.match(await page.textContent('#hl-card .status'), /Saved/);
  assert.deepEqual(errors, []);
});

// 4.3.4 and 5.4.8 are not offered for now (the owner, 2026-10-30; app.js MAX_OFFERED_BUILD): a realm on those builds
// is not listed and not a build filter, and a client on one shows as an other build; the override brings them back.
async function openWithCata(all) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, false);
  await page.addInitScript((all) => {
    if (all) window.LEYLINE_ALL_CLIENTS = true;
    const inner = window.__TAURI__.core.invoke;
    window.__TAURI__.core.invoke = async (cmd, args) => {
      const r = await inner(cmd, args);
      if (cmd === 'get_state') r.settings.clients.push({ id: 'c434-1', name: 'My Cata', path: '/y', build: '4.3.4', realmlist: '' });
      if (cmd === 'realms_list') r.realms = r.realms.concat([Object.assign({}, r.realms[2], { slug: 'c-eeeeeeeeeeeeeeee', realm_id: 'eeeeeeeeeeeeeeee',
        name: 'Cata Den', build: '4.3.4', version: '4.3.4', core: 'trinitycore', group: 'community' })]);
      return r;
    };
  }, all);
  await page.goto(INDEX);
  await page.click('.nav[data-page="realms"]');
  await page.waitForFunction(() => document.querySelectorAll('#rl-list .realm-card').length > 0);
  return { page, errors };
}

test('Realms page: 4.3.4 / 5.4.8 are hidden until the override', async () => {
  const { page, errors } = await openWithCata(false);
  assert.ok(!(await names(page)).includes('Cata Den'), 'a 4.3.4 realm is not listed');
  assert.deepEqual(await page.$$eval('#rl-f-build option', (o) => o.map((x) => x.value)), ['', '1.12.1', '3.3.5a']);
  await page.click('.nav[data-page="play"]');
  await page.click('#client-change');
  const cata = await page.locator('#page-clients .card', { hasText: 'My Cata' }).textContent();
  assert.match(cata, /other build/); assert.doesNotMatch(cata, /4\.3\.4|15595|40300/);
  assert.doesNotMatch(await page.textContent('#page-clients .lede'), /4\.3\.4|5\.4\.8/);
  assert.deepEqual(errors, []);
  await page.close();

  const all = await openWithCata(true);
  assert.ok((await names(all.page)).includes('Cata Den'), 'the override lists it');
  assert.deepEqual(await all.page.$$eval('#rl-f-build option', (o) => o.map((x) => x.value)), ['', '1.12.1', '3.3.5a', '4.3.4']);
  assert.deepEqual(all.errors, []);
  await all.page.close();
});

test('A website\'s Open in launcher (leyline://realm/<id>) shows that realm with PLAY focused, starting nothing', async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(() => { window.__link = { action: 'realm', id: 'bbbbbbbbbbbbbbbb' }; });
  await page.addInitScript(FAKE, false);
  await page.goto(INDEX);
  await page.waitForFunction(() => document.querySelector('#rl-list .realm-card.linked'));
  assert.ok(await page.locator('#page-realms').evaluate((e) => e.classList.contains('on')));
  assert.equal(await page.textContent('#rl-list .realm-card.linked .name'), 'Busy Den');
  assert.match(await page.textContent('#rl-status'), /From the website: Busy Den\. Press PLAY/);
  assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.textContent), 'PLAY');
  const started = await page.evaluate(() => window.__calls.map(([c]) => c).filter((c) => /^(play|play_realm|start_)/.test(c)));
  assert.deepEqual(started, [], 'nothing starts by itself');
  assert.deepEqual(errors, []);
});

// Hero Key sign-in on community realms (docs/HERO-KEY-SSO.md): only with the herokey_sso flag on, only on live
// community realms; the one-time password is shown, never kept in the page.
test('Hero Key sign-in: hidden with the flag off; on: live community realms only, password shown once', async () => {
  const off = await open(false);
  await off.page.click('#rl-refresh');
  await off.page.waitForTimeout(100);
  assert.equal(await off.page.locator('button:has-text("Sign in with your Hero Key")').count(), 0, 'flag off: no button');
  assert.deepEqual(off.errors, []);
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, false);
  await page.addInitScript(() => {
    const inner = window.__TAURI__.core.invoke;
    window.__TAURI__.core.invoke = async (cmd, args) => {
      if (cmd === 'play_realm_herokey') { window.__calls.push([cmd, args]); return { realm: 'bbbbbbbbbbbbbbbb', user: 'HKABCDEFGHIJKLMN', pass: 'Q7W8E9R2T3Y4U5I6', valid_s: 600 }; }
      const r = await inner(cmd, args);
      if (cmd === 'p2p_flags') r.effective.herokey_sso = true;
      return r;
    };
  });
  await page.goto(INDEX);
  await page.click('.nav[data-page="realms"]');
  await page.waitForFunction(() => document.querySelectorAll('#rl-list .realm-card').length > 0);
  await page.click('#rl-refresh');
  await page.waitForTimeout(100);
  const cards = page.locator('#rl-list .realm-card');
  const hk = (i) => cards.nth(i).locator('button:has-text("Sign in with your Hero Key")').count();
  assert.deepEqual([await hk(0), await hk(1), await hk(2), await hk(3)], [0, 1, 1, 0], 'live community realms only (not the official one, first, not offline)');
  await cards.nth(2).locator('button:has-text("Sign in with your Hero Key")').click();
  await page.waitForFunction(() => /one-time password/.test(document.querySelector('#rl-status').textContent));
  assert.match(await page.textContent('#rl-status'), /HKABCDEFGHIJKLMN.*Q7W8E9R2T3Y4U5I6.*10 minutes/);
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'play_realm_herokey' && a.slug === 'c-bbbbbbbbbbbbbbbb')));
  assert.ok(!(await page.evaluate(() => JSON.stringify(localStorage))).includes('Q7W8'), 'never kept in the page');
  assert.deepEqual(errors, []);
});
