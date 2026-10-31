// The Leyline spinner (ui/spin.css, ui/spin.js): the header mark is the spinning mark in Dark and Light, a loading
// state (Discover while the Workshop catalog loads) carries the spinner before its words and loses it when the words
// change, the swirl really turns (its transform changes over time) while the crystal stays upright, and with reduced
// motion it stands still.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/spin.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');

const FAKE = ({ saved, active }) => {
  const calls = (window.__calls = []);
  try {
    localStorage.setItem('leyline.page', 'discover');
    if (saved) localStorage.setItem('leyline.theme', JSON.stringify(saved)); else localStorage.removeItem('leyline.theme');
  } catch (_) { /* fine */ }
  // What themes.rs gives: the two built-ins, and the saved choice (an older id already moved by migrate_id).
  let core = active || 'dark';
  const builtins = [
    { id: 'dark', name: 'Dark', kind: 'dark', builtin: true, description: 'Navy and charcoal with a blue accent. The default.' },
    { id: 'light', name: 'Light', kind: 'light', builtin: true, description: 'Bright and clean with the same blue accent.' },
  ];
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: false, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
      case 'themes_list': return { active: core, themes: builtins };
      case 'theme_apply': core = args.id; return null;
      case 'realm_status': return { state: 'online', ping_ms: 10 };
      case 'realms_list': return { realms: [], network: { realms: 0, players: 0, bots: 0 }, from_cache: false, saved_at: 1, error: null };
      case 'mods_catalog': return new Promise(() => {});   // the Workshop never answers: Discover stays loading
      case 'mods_updates': return [];
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

async function open(opts, ctxOpts) {
  const ctx = await browser.newContext(Object.assign({ colorScheme: 'dark' }, ctxOpts || {}));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, opts || {});
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LySpin && document.querySelector('.titlebar .brand .ly-spin'));
  return { page, ctx, errors };
}
const angle = (page, sel, pseudo) => page.evaluate(([s, p]) => {
  const t = getComputedStyle(document.querySelector(s), p).transform;
  if (!t || t === 'none') return 0;
  const m = t.match(/matrix\(([^)]+)\)/)[1].split(',').map(Number);
  return Math.round(Math.atan2(m[1], m[0]) * 180 / Math.PI * 10) / 10;
}, [sel, pseudo]);

test('the header mark is the spinner, in Dark and in Light', async () => {
  for (const light of [false, true]) {
    const { page, ctx, errors } = await open(light ? { saved: { id: 'light', kind: 'light' }, active: 'light' } : {});
    const r = await page.evaluate(() => {
      const s = document.querySelector('.titlebar .brand .ly-spin');
      const b = getComputedStyle(s, '::before'), a = getComputedStyle(s, '::after');
      return { swirl: b.backgroundImage, crystal: a.backgroundImage, anim: b.animationName, dur: b.animationDuration,
        w: s.getBoundingClientRect().width, base: document.documentElement.dataset.base, img: !!document.querySelector('.titlebar .brand img') };
    });
    assert.equal(r.base, light ? 'light' : 'dark');
    assert.match(r.swirl, /leyline-swirl-256\.webp/);
    assert.match(r.crystal, /leyline-crystal-256\.webp/);
    assert.equal(r.anim, 'ly-spin-turn');
    assert.equal(r.dur, '16s', 'the header turns slowly');
    assert.equal(r.w, 48);
    assert.equal(r.img, false, 'no still image left in the header');
    assert.deepEqual(errors, []);
    await ctx.close();
  }
});

test('a loading state carries the spinner, and loses it when it is done', async () => {
  const { page, ctx, errors } = await open();
  await page.waitForFunction(() => /Loading the Workshop/.test(document.getElementById('cat-status').textContent));
  await page.waitForFunction(() => document.querySelector('#cat-status > .ly-spin:first-child'));
  assert.ok(await page.evaluate(() => document.getElementById('cat-status').classList.contains('busy')));
  // the words change (as say() does): the spinner goes; a busy text again: it comes back
  await page.evaluate(() => { const s = document.getElementById('cat-status'); s.textContent = 'Done.'; s.className = 'status ok'; });
  await page.waitForFunction(() => !document.querySelector('#cat-status .ly-spin'));
  await page.evaluate(() => { document.getElementById('cat-status').textContent = 'Checking…'; });
  await page.waitForFunction(() => document.querySelector('#cat-status > .ly-spin'));
  // a failure that ends in an ellipsis is not busy
  await page.evaluate(() => { const s = document.getElementById('cat-status'); s.textContent = 'Could not reach…'; s.className = 'status bad'; });
  await page.waitForFunction(() => !document.querySelector('#cat-status .ly-spin'));
  // the title bar pill while the realm is checked: spinner in place of the dot (the fake answers at once, so set it)
  await page.evaluate(() => { document.getElementById('tb-status-text').textContent = 'Checking…'; });
  await page.waitForFunction(() => document.querySelector('#tb-status-text > .ly-spin'));
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('#tb-status > .dot')).display), 'none');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('the swirl turns, the crystal does not; reduced motion stands still', async () => {
  const { page, ctx } = await open();
  const sel = '.titlebar .brand .ly-spin';
  await page.evaluate(() => document.querySelector('.titlebar .brand .ly-spin').classList.remove('slow'));
  const a = await angle(page, sel, '::before');
  await page.waitForTimeout(700);
  const b = await angle(page, sel, '::before');
  assert.notEqual(a, b, `the swirl turned (${a} -> ${b})`);
  assert.equal(await angle(page, sel, '::after'), 0, 'the crystal stays upright');
  await ctx.close();

  const still = await open(null, { reducedMotion: 'reduce' });
  const r = await still.page.evaluate(() => getComputedStyle(document.querySelector('.titlebar .brand .ly-spin'), '::before').animationName);
  assert.equal(r, 'none');
  const c = await angle(still.page, sel, '::before');
  await still.page.waitForTimeout(500);
  assert.equal(await angle(still.page, sel, '::before'), c);
  await still.ctx.close();
});
