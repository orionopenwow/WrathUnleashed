// The launcher's Realms page and the Host page's realm list details (ui/app.js, ui/host.js) in Chromium, with a fake
// Tauri core: the network order as realms.rs gives it, the network line, the badges (featured, verified, new, uptime,
// temporary), the filters (build, rules tag, region, language, has players now), "Only realms my clients can play",
// Report, direct connect only with the p2p_hosting flag on, Host your own, and saving the details.
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

test('Realms page: the network order, line, badges, filters, Report, Host your own', async () => {
  const { page, errors } = await open(false);
  assert.deepEqual(await names(page), ['Picked', 'Leyline Sample Hangout', 'Busy Den', 'Asleep'], 'featured, the sample, by score, offline');
  assert.equal(await page.textContent('#rl-net'), '3 realms · 33 players online · 40 bots');
  const cards = page.locator('#rl-list .realm-card');
  const picked = await cards.nth(0).textContent();
  assert.match(picked, /Featured/); assert.match(picked, /Verified host/); assert.match(picked, /97% up · 7 d/);
  assert.match(picked, /PvP/); assert.match(picked, /Europe/); assert.match(picked, /de/);
  assert.match(await cards.nth(1).textContent(), /temporary/);
  assert.match(await cards.nth(1).textContent(), /Run by Leyline/);
  const busy = await cards.nth(2).textContent();
  assert.match(busy, /New/); assert.match(busy, /70% up · 24 h/); assert.match(busy, /North America east \(estimated\)/);
  assert.match(busy, /30 of 100 players · 40 bots/);
  assert.doesNotMatch(busy, /Direct connect/, 'direct connect only with p2p_hosting on');
  assert.equal(await cards.nth(1).locator('button:has-text("Report")').count(), 0, 'no Report on the sample');
  await cards.nth(2).locator('button:has-text("Report")').click();
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_url' && a.url === 'https://play.openvanilla.app/wrath/realms/report?realm=bbbbbbbbbbbbbbbb')));

  // filters
  const opts = await page.$$eval('#rl-f-tag option', (o) => o.map((x) => x.value));
  assert.deepEqual(opts, ['', 'bots', 'pvp', 'rp']);
  await page.selectOption('#rl-f-tag', 'pvp');
  assert.deepEqual(await names(page), ['Picked', 'Leyline Sample Hangout'], 'tag filter; the sample stays');
  await page.selectOption('#rl-f-tag', '');
  await page.selectOption('#rl-f-region', 'na-east');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Busy Den'], 'an estimated region counts');
  await page.selectOption('#rl-f-region', '');
  await page.check('#rl-f-now');
  assert.deepEqual(await names(page), ['Picked', 'Leyline Sample Hangout', 'Busy Den'], 'has players now');
  await page.uncheck('#rl-f-now');
  await page.selectOption('#rl-f-build', '1.12.1');
  assert.deepEqual(await names(page), ['Picked', 'Leyline Sample Hangout']);
  await page.selectOption('#rl-f-build', '');
  await page.check('#rl-mine');
  assert.deepEqual(await names(page), ['Leyline Sample Hangout', 'Busy Den', 'Asleep'], 'Only realms my clients can play still works');
  await page.uncheck('#rl-mine');

  // Host your own: three steps, opens the Host page
  assert.equal(await page.locator('#rl-host-cta ol.steps li').count(), 3);
  await page.click('#rl-host');
  assert.ok(await page.locator('#page-host').evaluate((e) => e.classList.contains('on')));
  assert.deepEqual(errors, []);
});

test('Direct connect shows with p2p_hosting on; the Host page saves the realm list details', async () => {
  const { page, errors } = await open(true);
  await page.click('#rl-refresh');
  await page.waitForTimeout(100);
  assert.match(await page.locator('#rl-list .realm-card').nth(2).textContent(), /Direct connect available/);
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
