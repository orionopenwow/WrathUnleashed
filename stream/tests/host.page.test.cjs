// Host your own from the game, in the page layer (node, no browser): wrath-page.js's leyline-host block takes the
// in-game Host window's choices (the Lua global WUUI_LEYLINE_HOST, through the bridge), checks every name and value
// again (the same rules as WrathUnleashedUI/Host.lua, stream/hostflow.py prefill() and the launcher's deeplink.rs),
// and offers the website's host page with them; anything off is dropped.
//
//   node --test tests/host.page.test.cjs          (from the stream folder)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const WWW = path.join(__dirname, '..', 'www-files');
const GOOD = 'core=azerothcore&preset=main&name=Frost%20Haven%27s&type=rppvp&xp=5&loot=2&start=level1&bots=40'
  + '&vis=private&signup=invite&herokey=on&region=eu&lang=pt-BR&tags=pvp%2Crp&max=100';

async function page() {
  globalThis.window = { __wenilla_env: {} };
  return import(pathToFileURL(path.join(WWW, 'wrath-page.js')).href);
}

test('hostQuery: the game\'s query string, checked and in order', async () => {
  const m = await page();
  assert.equal(m.hostQuery(GOOD), "core=azerothcore&preset=main&name=Frost%20Haven's&type=rppvp&xp=5&loot=2&start=level1"
    + '&bots=40&vis=private&signup=invite&herokey=on&region=eu&lang=pt-BR&tags=pvp%2Crp&max=100');
  assert.ok(m.hostQuery('core=cmangos&preset=cmangos-1.12.1&name=Old&type=normal&vis=public&signup=open&herokey=off'));
  const bad = [
    null, 42, '', 'core=azerothcore', GOOD + '&evil=1', GOOD + '&name=x',
    GOOD.replace('preset=main', 'preset=cmangos-1.12.1'),            // the ruleset of another core
    GOOD.replace('Frost%20Haven%27s', 'My%20WoW%20realm'),             // a brand name
    GOOD.replace('Frost%20Haven%27s', 'a%3Cscript%3E'),
    GOOD.replace('Frost%20Haven%27s', 'x'.repeat(33)),
    GOOD.replace('xp=5', 'xp=11'), GOOD.replace('xp=5', 'xp=2.5'), GOOD.replace('bots=40', 'bots=999'),
    GOOD.replace('type=rppvp', 'type=evil'), GOOD.replace('vis=private', 'vis=secret'),
    GOOD.replace('region=eu', 'region=mars'), GOOD.replace('lang=pt-BR', 'lang=klingon'),
    GOOD.replace('tags=pvp%2Crp', 'tags=bots'), GOOD.replace('max=100', 'max=-1'),
    'core=azerothcore&preset=dalaran&name=Den&type=normal&bots=10&vis=public&signup=open&herokey=off',  // no bots there
    'core=azerothcore&preset=brawl&name=Den&type=normal&start=level1&vis=public&signup=open&herokey=off', // start: main only
    'core=cmangos&preset=cmangos-2.4.3&name=Den&type=normal&xp=3&vis=public&signup=open&herokey=off',    // rates: AzerothCore
    'x'.repeat(700),
  ];
  for (const b of bad) assert.equal(m.hostQuery(b), null, String(b).slice(0, 80));
});

test('hostPageUrl: the website (or the env\'s home)', async () => {
  const m = await page();
  assert.equal(m.hostPageUrl('core=x'), 'https://play.openvanilla.app/wrath/host?core=x');
  assert.equal(m.hostPageUrl('core=x', { home: 'https://play.example' }), 'https://play.example/wrath/host?core=x');
  assert.equal(m.hostPageUrl('core=x', { home: 'javascript:alert(1)' }), 'https://play.openvanilla.app/wrath/host?core=x');
  assert.equal(m.hostPageUrl(null), null);
});

test('watchHostAsk: takes the global, marks the page, offers the host page once; junk is dropped', async () => {
  const m = await page();
  const shown = [];
  let global = GOOD;
  const ran = [];
  const wenilla = {
    ready: true, state: {},
    lua: async (code) => { ran.push(code); const v = global; global = null; return [v]; },
  };
  const h = m.watchHostAsk(wenilla, { pollMs: 0, show: (u) => shown.push(u) });
  assert.match(m.HOST_TAKE, /^WUUI_PAGE = true; /);
  const url = await h.take();
  assert.equal(url, 'https://play.openvanilla.app/wrath/host?' + m.hostQuery(GOOD));
  assert.deepEqual(shown, [url]);
  assert.equal(ran[0], m.HOST_TAKE);
  assert.equal(await h.take(), null, 'taken once: the global is cleared');
  global = 'core=azerothcore&preset=main&name=x&evil=1';
  assert.equal(await h.take(), null);
  assert.equal(h.refused, 1);
  assert.equal(shown.length, 1);
  assert.deepEqual(m.watchHostAsk(null), { polls: 0, taken: null, refused: 0, busy: false, timer: 0, take: null, error: null });
});
