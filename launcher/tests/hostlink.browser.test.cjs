// The launcher's leyline://host links (deeplink.rs Link::Host) in Chromium, with a fake Tauri core: the in-game Host
// window's choices open the Host page with them listed in plain words and "MAKE IT ON THE WEBSITE" (open_host_form with
// the same checked query, nothing else starts); the game's "Your realm" links (manage=<what>) open the Host page with
// what to do for that control.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/hostlink.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const Q = 'core=azerothcore&preset=main&name=Frost%20Haven%27s&type=rppvp&xp=5&loot=2&start=level1&bots=40'
  + '&vis=private&signup=invite&herokey=on&region=eu&lang=pt-BR&tags=pvp%2Crp&max=100';

const FAKE = (link) => {
  const calls = (window.__calls = []);
  window.__link = link;
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: false, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
      case 'host_info': return { dir: null, is_kit: false, problems: [], seeds: [], realm: null };
      case 'deep_link_take': { const l = window.__link || null; window.__link = null; return l; }
      case 'open_host_form': return null;
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

test('leyline://host?<choices>: the Host page with the choices, and the website form on a click', async () => {
  const page = await browser.newPage();
  await page.addInitScript(FAKE, { action: 'host', id: Q });
  await page.goto(INDEX);
  await page.waitForFunction(() => !document.getElementById('host-from-game').hidden);
  assert.ok(await page.locator('#page-host').evaluate((e) => e.classList.contains('on')), 'the Host page is open');
  assert.equal(await page.textContent('#host-from-game-title'), 'FROM THE GAME: YOUR NEW REALM');
  const items = await page.$$eval('#host-from-game-list li', (l) => l.map((x) => x.textContent));
  assert.deepEqual(items, ['Core: AzerothCore', 'Ruleset: Classic levelling', "Realm name: Frost Haven's", 'Type: RP-PvP',
    'XP rate: 5x', 'Loot rate: 2x', 'New characters: Level 1 only', 'Bots: 40', 'Who can find it: Private: invite link only',
    'Accounts: Invite link only', 'Hero Key sign-in: On', 'Region: eu', 'Language: pt-BR', 'Tags: pvp, rp',
    'Max players shown: 100']);
  const started = await page.evaluate(() => window.__calls.map(([c]) => c).filter((c) => /^(host_start|open_host_form|play)/.test(c)));
  assert.deepEqual(started, [], 'nothing starts by itself');
  await page.click('#host-from-game-go');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'open_host_form'));
  const call = await page.evaluate(() => window.__calls.find(([c]) => c === 'open_host_form'));
  assert.deepEqual(call[1], { query: Q }, 'the core checks the same query again');
  assert.match(await page.textContent('#host-status-line'), /website's host page is open with your choices/);
  const text = await page.textContent('#host-from-game');
  assert.doesNotMatch(text, /warcraft|\bwow\b|lich king|blizzard/i);
});

test('leyline://host?manage=<what>: the Host page says what to do for that control', async () => {
  const page = await browser.newPage();
  await page.addInitScript(FAKE, { action: 'host', id: 'manage=bots' });
  await page.goto(INDEX);
  await page.waitForFunction(() => !document.getElementById('host-from-game').hidden);
  assert.equal(await page.textContent('#host-from-game-title'), 'FROM THE GAME: BOTS');
  assert.match(await page.textContent('#host-from-game-list'), /leyline options --bots 40/);
  assert.ok(await page.locator('#host-from-game-go').evaluate((e) => e.hidden), 'no website button for a control');
});
