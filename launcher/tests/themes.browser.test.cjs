// The launcher's two built-in looks (ui/themes.js, ui/style.css) in Chromium with a fake Tauri core: Dark is the
// default with nothing saved, only Dark and Light are built in, a choice saved by an older Leyline (Leyline Classic,
// the Rounded looks) moves to Dark or Light here and in the core, USE and Ctrl+Shift+Backspace, and no painted art,
// display font or old theme names left in the window.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/themes.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');

const FAKE = ({ saved, active }) => {
  const calls = (window.__calls = []);
  try {
    localStorage.setItem('leyline.page', 'settings');
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
      case 'mods_catalog': return { categories: [], projects: [], from_cache: false, saved_at: 1, error: null };
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

async function open(opts, scheme) {
  const ctx = await browser.newContext({ colorScheme: scheme || 'dark' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, opts || {});
  await page.goto(INDEX);
  await page.waitForFunction(() => document.querySelectorAll('#themes-settings .theme-card').length === 2);
  return { page, ctx, errors };
}
const look = (page) => page.evaluate(() => ({
  theme: document.documentElement.dataset.theme, base: document.documentElement.dataset.base, skin: document.documentElement.dataset.skin,
  bg: getComputedStyle(document.body).backgroundColor, stored: JSON.parse(localStorage.getItem('leyline.theme') || 'null'),
}));

test('nothing saved: Dark, and only Dark and Light are built in', async () => {
  const { page, ctx, errors } = await open();
  const l = await look(page);
  assert.equal(l.theme, 'dark');
  assert.equal(l.base, 'dark');
  assert.equal(l.skin, undefined);
  assert.equal(l.bg, 'rgb(21, 24, 31)', 'the dark window');
  assert.deepEqual(await page.evaluate(() => [window.LeylineThemes.DEFAULT, window.LeylineThemes.BUILTINS]), ['dark', ['dark', 'light']]);
  const names = await page.$$eval('#themes-settings .theme-card .name', (n) => n.map((x) => x.textContent));
  assert.deepEqual(names, ['Dark', 'Light']);
  assert.match(await page.textContent('#themes-settings .theme-card.on'), /In use/);
  assert.match(await page.textContent('#themes-settings .lede'), /goes back to Dark/);
  assert.ok(!(await page.evaluate(() => window.__calls.some((c) => c[0] === 'theme_apply'))), 'nothing to tell the core');
  assert.deepEqual(errors, []);
  await ctx.close();
});

test('USE Light, then Ctrl+Shift+Backspace goes back to Dark', async () => {
  const { page, ctx, errors } = await open();
  const light = page.locator('#themes-settings .theme-card', { hasText: 'Light' });
  await light.locator('button', { hasText: 'USE' }).click();
  await page.waitForFunction(() => document.documentElement.dataset.base === 'light');
  let l = await look(page);
  assert.equal(l.theme, 'light');
  assert.equal(l.bg, 'rgb(238, 241, 246)', 'the light window');
  assert.deepEqual([l.stored.id, l.stored.kind], ['light', 'light']);
  assert.ok(await page.evaluate(() => window.__calls.some((c) => c[0] === 'theme_apply' && c[1].id === 'light')));
  await page.keyboard.press('Control+Shift+Backspace');
  await page.waitForFunction(() => document.documentElement.dataset.base === 'dark');
  l = await look(page);
  assert.deepEqual([l.theme, l.stored.id], ['dark', 'dark']);
  assert.deepEqual(errors, []);
  await ctx.close();
});

for (const [old, scheme, want] of [['leyline-classic', 'light', 'dark'], ['dark-rounded', 'light', 'dark'], ['light-rounded', 'dark', 'light'],
  ['rounded-system', 'light', 'light'], ['rounded-system', 'dark', 'dark']]) {
  test(`an older saved choice (${old}, system ${scheme}) moves to ${want}`, async () => {
    const kind = { 'leyline-classic': 'classic', 'dark-rounded': 'rounded-dark', 'light-rounded': 'rounded-light', 'rounded-system': 'rounded-system' }[old];
    // The core has read the same old active.json and moved it too (Rounded Auto reads as Dark there).
    const core = { 'light-rounded': 'light' }[old] || 'dark';
    const { page, ctx, errors } = await open({ saved: { id: old, kind }, active: core }, scheme);
    await page.waitForFunction(() => window.__calls.some((c) => c[0] === 'theme_apply'));
    const l = await look(page);
    assert.deepEqual([l.theme, l.base, l.stored.id, l.stored.kind], [want, want, want, want]);
    assert.ok(await page.evaluate((w) => window.__calls.some((c) => c[0] === 'theme_apply' && c[1].id === w), want), 'the core is told');
    assert.match(await page.textContent('#themes-settings .theme-card.on'), new RegExp(want === 'dark' ? 'Dark' : 'Light'));
    assert.deepEqual(errors, []);
    await ctx.close();
  });
}

test('no painted art, display font or old theme names in the window', async () => {
  for (const scheme of ['dark', 'light']) {
    const { page, ctx } = await open(scheme === 'light' ? { saved: { id: 'light', kind: 'light' }, active: 'light' } : {});
    const r = await page.evaluate(() => {
      const urls = [];
      for (const el of document.querySelectorAll('*')) {
        if (el.src) urls.push(el.src);
        for (const pseudo of [null, '::before', '::after']) {
          const cs = getComputedStyle(el, pseudo);
          for (const p of ['backgroundImage', 'borderImageSource']) if (cs[p] && cs[p] !== 'none') urls.push(cs[p]);
        }
      }
      const fonts = new Set([...document.querySelectorAll('*')].map((e) => getComputedStyle(e).fontFamily));
      return { urls, fonts: [...fonts], text: document.body.innerText, brand: document.querySelector('.titlebar .brand').innerText,
        mark: document.querySelector('.titlebar .brand img').getAttribute('src') };
    });
    assert.ok(!r.urls.some((u) => /art\/kit|parchment|stone|play\.png|crest/.test(u)), r.urls.join('\n'));
    assert.ok(r.urls.some((u) => /leyline-mark-512\.png/.test(u)), 'the Home card has the Leyline mark');
    assert.ok(!r.fonts.some((f) => /Cinzel|Leyline Display|Impact/.test(f)), r.fonts.join(' | '));
    assert.equal(r.brand.replace(/\s+/g, ' ').trim(), 'Leyline Launcher');
    assert.equal(r.mark, 'art/brand/leyline-mark-512.png');
    for (const bad of ['Leyline Classic', 'Rounded', 'parchment', 'World of Warcraft', 'Warcraft', 'Blizzard', 'Lich King']) {
      assert.ok(!r.text.includes(bad), `${bad} in the window`);
    }
    assert.ok(!/\bWoW\b/.test(r.text));
    await ctx.close();
  }
});
