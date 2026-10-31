// The host console (ui/hostconsole.js) in Chromium, with a fake Tauri core: once a realm is set up on this PC, the Host
// page is "Your realm console" (the website's mockup, stream/hub.py host_showcase): the realm's name and Online · listed,
// the six service tiles, the GM controls (announce at once; kick, ban and restart only after a confirm; a restart never
// carries a delay), the health check's five checks, the realm tools (invite links, accounts for friends through the
// invite link only, public or private, who may sign up, logs, house rules) and the cores. Before that: the setup start
// (the rulesets with Vanilla+ always on, Link my server) and the guide, whose links are named links in the core.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/hostconsole.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const RID = 'abcdefghijk2345a';

const FAKE = (setUp) => {
  const calls = (window.__calls = []);
  const den = setUp === 'den';   // a Den set up on this PC (docs/DEN.md)
  const realm = setUp ? { realm_id: 'abcdefghijk2345a', name: den ? 'My Den' : 'Frost Haven', visibility: den ? 'private' : 'public', relay: 'relay.openvanilla.app', profile: den ? 'den' : 'vanillaplus' } : null;
  const svc = (role, state, text) => ({ role, state, text });
  let rules = ['Be kind.', 'No gold selling.'];
  let visibility = den ? 'private' : 'public';
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: false, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: true, data_dir: '/tmp' };
      case 'deep_link_take': return null;
      case 'host_info': return { dir: '/home/me/kit', is_kit: !window.__noKit, has_windows_script: true, has_unix_script: true, problems: [], seeds: [], realm };
      case 'host_console': return { set_up: !!realm, linked: false, name: realm ? realm.name : '', realm_id: realm ? realm.realm_id : '',
        profile: realm ? realm.profile : 'vanillaplus', core: 'azerothcore', visibility, signup: 'invite', herokey: false, claim_sent: false, browser: true, max_players: den ? 10 : 0,
        relay: 'relay.openvanilla.app', relay_connected: true, relay_error: null, docker: true,
        services: [svc('database', 'ok', 'ready'), svc('login', 'ok', 'ready'), svc('world', 'ok', 'ready'), svc('agent', 'ok', 'connected')],
        uptime: '3 days', gm: true, gm_note: null, invite: 'https://relay.openvanilla.app/join/abcdefghijk2345a' };
      case 'host_status': return { realm_id: args.realmId, online: true, name: realm ? realm.name : 'Frost Haven', visibility, address: 'relay.openvanilla.app:40002', players: 12, bots: 0, listed: visibility === 'public' };
      case 'host_gm':
        if (args.action === 'status') return 'gm=1\nup=3725\nplayers=12\nbots=0\nrestart=0\nallow=off\nallowed=0\nvis=public\nmotd=-';
        return { announce: 'Announced to everyone online.', kick: `${args.data} was kicked.`, ban: 'Banned.', restart: 'Restart in 5 minutes. Everyone online was told.' }[args.action] || 'Done.';
      case 'host_check': return { ok: false, summary: "1 problem(s) found. Players can't join until they're fixed.", rows: [
        { id: 'pc', state: 'ok', lines: [{ kind: 'ok', text: 'The login server is running.', fix: null }] },
        { id: 'tunnel', state: 'ok', lines: [{ kind: 'ok', text: 'Your realm is connected to the relay.', fix: null }] },
        { id: 'login', state: 'bad', lines: [{ kind: 'bad', text: 'The world server is not reachable through the relay.', fix: 'Run the check again in a minute.' }] },
        { id: 'invite', state: 'ok', lines: [{ kind: 'ok', text: 'The join page works.', fix: null }] },
        { id: 'list', state: 'warn', lines: [{ kind: 'note', text: 'Your realm is not in the list yet.', fix: 'It appears within a minute.' }] }] };
      case 'host_tool': if (args.name === 'private' || args.name === 'public') visibility = args.name; return 'Saved.';
      case 'host_invite': return 'https://relay.openvanilla.app/join/abcdefghijk2345a';
      case 'host_new_invite': return 'https://relay.openvanilla.app/join/abcdefghijk2345a';
      case 'host_rules': return rules;
      case 'host_rules_set': rules = args.lines.filter((l) => l.trim()); return 'Saved. The realm list shows them within a minute.';
      case 'host_logs': return 'wu-host-worldserver | World initialized';
      case 'host_stop': return 'Stopped.';
      case 'host_start': return 'Started in its own window.';
      case 'host_link_start': return 'Started in its own window: answer its four questions.';
      case 'host_choose': return { profile: args.profile, client_dir: '' };
      case 'host_profiles': return [[
        { id: 'vanillaplus', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c1', name: 'Mine', path: '/g' }], note: null },
        { id: 'dalaran', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c1', name: 'Mine', path: '/g' }], note: null },
        { id: 'den', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c1', name: 'Mine', path: '/g' }], note: null },
        { id: 'main', label: 'x', version: '3.3.5a', core: 'azerothcore', in_kit: true, clients: [{ id: 'c1', name: 'Mine', path: '/g' }], note: null },
        { id: 'cmangos-1.12.1', label: 'x', version: '1.12.1', core: 'cmangos', in_kit: true, clients: [], note: 'Add your own client of that version on the Clients page first.' },
      ], null];
      case 'hostpack_info': return window.__noKit ? { installed: null, available: { version: '7', size: 412000 }, update: false, kit_dir: '/home/me/kit' }
        : { installed: { version: '7' }, available: { version: '7' }, update: false, kit_dir: '/home/me/kit' };
      case 'hostpack_install': window.__noKit = false; return [{ version: '7' }, '/home/me/kit'];
      case 'set_host_kit': return null;
      case 'docker_info': return window.__noKit ? { state: 'missing', version: null, help: 'Docker is not installed.', get_url: 'https://docs.docker.com/desktop/' } : { state: 'ready', version: '27.3.1', help: 'Docker is ready.', get_url: 'https://docs.docker.com/desktop/' };
      case 'host_listing': return { tags: [], region: null, language: null, max_players: null, direct: false };
      case 'p2p_flags': return { effective: { p2p_hosting: false, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case 'open_link': return null;
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(setUp, light) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, setUp);
  if (light) await page.addInitScript(() => { try { localStorage.setItem('leyline.theme', 'light'); } catch (_) { /* */ } });
  await page.goto(INDEX);
  await page.click('.nav[data-page="host"]');
  await page.waitForFunction(() => document.getElementById('hc-pane-main').classList.contains('on'));
  return { page, errors };
}
const calls = (page, cmd) => page.evaluate((c) => window.__calls.filter(([x]) => x === c).map(([, a]) => a), cmd);
const NO_BRANDS = /warcraft|\bwow\b|lich king|blizzard/i;

test('a realm set up on this PC: the Host page is its console', async () => {
  const { page, errors } = await open(true);
  await page.waitForFunction(() => document.querySelector('.hc-run').textContent === 'Online · listed');
  assert.equal(await page.textContent('#hc-tab-main'), 'Console');
  assert.equal(await page.textContent('.hc-t'), 'Frost Haven');
  const tiles = await page.$$eval('.hc-svc li', (l) => l.map((x) => [x.querySelector('b').textContent, x.querySelector('span').textContent, x.className]));
  assert.deepEqual(tiles, [['Database', 'ready', 'hc-tile ok'], ['Login server', 'ready', 'hc-tile ok'], ['World server', 'ready', 'hc-tile ok'],
    ['Relay agent', 'listed', 'hc-tile ok'], ['Players', '12 online', 'hc-tile ok'], ['Uptime', '3 days', 'hc-tile ok']]);
  assert.deepEqual(await page.$$eval('.hc-act-h b', (l) => l.map((x) => x.textContent)),
    ['Announce', 'Message of the day', 'Kick', 'Ban or unban', 'Allow-list', 'Restart']);
  assert.deepEqual(await page.$$eval('.hc-chk li span', (l) => l.map((x) => x.textContent)),
    ['The servers on your PC', 'The tunnel to the relay', 'A login through the relay', 'Your invite link', 'Your place on the realm list']);
  assert.deepEqual(await page.$$eval('.hc-tool', (l) => l.map((x) => x.textContent)),
    ['Invite links', 'Accounts for friends', 'Public or private', 'Who may sign up', 'Browser players', 'Max players', 'Server logs', 'House rules']);
  assert.deepEqual(await page.$$eval('.hc-core', (l) => l.map((x) => [x.dataset.core, x.querySelector('span span').textContent])),
    [['azerothcore', 'One click'], ['cmangos', 'One click'], ['trinitycore', 'Coming'], ['vmangos', 'Coming'], ['own', 'Relay agent']]);
  assert.equal(await page.getAttribute('.hc-core[data-core="azerothcore"]', 'aria-current'), 'true', 'the core this realm runs');
  assert.ok(await page.isHidden('.hc-top-acts button:has-text("Start")') && await page.isVisible('.hc-top-acts button:has-text("Stop")'));
  assert.doesNotMatch(await page.textContent('#page-host'), NO_BRANDS);
  assert.equal(await page.locator('#page-host input[type="password"]').count(), 0, 'Leyline never asks for a password');
  assert.deepEqual(errors, []);
});

test('GM controls: announce at once; kick, ban and restart only after a confirm; a restart never carries a delay', async () => {
  const { page, errors } = await open(true);
  await page.waitForFunction(() => document.querySelector('.hc-run').textContent === 'Online · listed');
  await page.click('[data-gm="announce"] .hc-act-h');
  await page.fill('[data-gm="announce"] input', 'Back in ten');
  await page.click('[data-gm="announce"] button:has-text("Send")');
  await page.waitForFunction(() => document.querySelector('.hc-status').textContent === 'Announced to everyone online.');
  assert.deepEqual((await calls(page, 'host_gm')).filter((a) => a.action !== 'status'), [{ action: 'announce', data: 'Back in ten' }]);

  // kick: Cancel does nothing, Kick does it
  await page.click('[data-gm="kick"] .hc-act-h');
  assert.ok(await page.isHidden('[data-gm="announce"] .hc-act-f'), 'one form open at a time');
  await page.fill('[data-gm="kick"] input', 'Grumpy');
  await page.click('[data-gm="kick"] .hc-act-f button:has-text("Kick")');
  await page.waitForSelector('#hc-confirm[open]');
  assert.equal(await page.textContent('#hc-confirm-title'), 'Kick Grumpy?');
  await page.click('#hc-confirm-no');
  await page.waitForTimeout(50);
  assert.equal((await calls(page, 'host_gm')).filter((a) => a.action === 'kick').length, 0, 'cancelled: nothing sent');
  await page.click('[data-gm="kick"] .hc-act-f button:has-text("Kick")');
  await page.click('#hc-confirm-yes');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_gm' && a.action === 'kick'));
  assert.deepEqual((await calls(page, 'host_gm')).find((a) => a.action === 'kick'), { action: 'kick', data: 'Grumpy' });

  // ban for a week
  await page.click('[data-gm="ban"] .hc-act-h');
  await page.fill('[data-gm="ban"] input', 'Grumpy');
  await page.selectOption('[data-gm="ban"] select', '168');
  await page.click('[data-gm="ban"] .hc-act-f button:has-text("Ban")');
  await page.waitForSelector('#hc-confirm[open]');
  assert.equal(await page.textContent('#hc-confirm-title'), 'Ban Grumpy for 1 week?');
  await page.click('#hc-confirm-yes');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_gm' && a.action === 'ban'));
  assert.deepEqual((await calls(page, 'host_gm')).find((a) => a.action === 'ban'), { action: 'ban', data: 'Grumpy\t168' });

  // restart: always the five-minute one
  await page.click('[data-gm="restart"] .hc-act-h');
  await page.click('[data-gm="restart"] button:has-text("Restart in 5 minutes")');
  await page.waitForSelector('#hc-confirm[open]');
  assert.match(await page.textContent('#hc-confirm-body'), /five minutes/);
  await page.click('#hc-confirm-yes');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_gm' && a.action === 'restart'));
  assert.deepEqual((await calls(page, 'host_gm')).find((a) => a.action === 'restart'), { action: 'restart', data: '' });
  assert.deepEqual(errors, []);
});

test('the health check, and the realm tools', async () => {
  const { page, errors } = await open(true);
  await page.waitForFunction(() => document.querySelector('.hc-run').textContent === 'Online · listed');
  await page.click('#hc-run-check');
  await page.waitForFunction(() => !document.querySelector('.hc-sum').hidden);
  assert.deepEqual(await page.$$eval('.hc-chk li', (l) => l.map((x) => x.className)), ['c-ok', 'c-ok', 'c-bad', 'c-ok', 'c-warn']);
  assert.match(await page.textContent('[data-check="login"] small'), /not reachable through the relay\. Run the check again/);
  assert.match(await page.textContent('.hc-sum'), /1 problem/);

  // accounts for friends: the invite link, never an account or a password
  await page.click('.hc-tool[data-tool="friends"]');
  assert.match(await page.textContent('.hc-drawer'), /their own account on your join page.*never makes accounts or sees passwords/);
  assert.equal(await page.locator('.hc-drawer input').count(), 0);
  // public or private
  await page.click('.hc-tool[data-tool="vis"]');
  assert.equal(await page.getAttribute('.hc-seg-b[data-value="public"]', 'aria-pressed'), 'true');
  await page.click('.hc-seg-b[data-value="private"]');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_tool' && a.name === 'private'));
  await page.waitForFunction(() => document.querySelector('.hc-seg-b[data-value="private"]').getAttribute('aria-pressed') === 'true');
  // who may sign up
  await page.click('.hc-tool[data-tool="signup"]');
  await page.click('.hc-seg-b[data-value="open"]');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_tool' && a.name === 'signup-open'));
  // browser players (Warden off) and max players (the server's cap)
  await page.click('.hc-tool[data-tool="browser"]');
  assert.equal(await page.getAttribute('.hc-seg-b[data-value="on"]', 'aria-pressed'), 'true');
  await page.click('.hc-seg-b[data-value="off"]');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_tool' && a.name === 'browser-off'));
  await page.click('.hc-tool[data-tool="max"]');
  await page.fill('.hc-drawer input[type=number]', '25');
  await page.click('.hc-drawer button:has-text("Save")');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_tool' && a.name === 'max' && a.arg === '25'));
  // house rules
  await page.click('.hc-tool[data-tool="rules"]');
  await page.waitForFunction(() => document.querySelector('.hc-rules') && document.querySelector('.hc-rules').value === 'Be kind.\nNo gold selling.');
  await page.fill('.hc-rules', 'Be kind.\nNo gold selling.\nHave fun.');
  await page.click('.hc-drawer button:has-text("Save")');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_rules_set'));
  assert.deepEqual((await calls(page, 'host_rules_set'))[0], { lines: ['Be kind.', 'No gold selling.', 'Have fun.'] });
  // a new invite link asks first
  await page.click('.hc-tool[data-tool="invite"]');
  await page.waitForSelector('.hc-link');
  await page.click('.hc-drawer button:has-text("New link")');
  await page.waitForSelector('#hc-confirm[open]');
  await page.click('#hc-confirm-no');
  assert.equal((await calls(page, 'host_new_invite')).length, 0);
  // the logs
  await page.click('.hc-tool[data-tool="logs"]');
  await page.waitForFunction(() => document.querySelector('.hc-logs') && /World initialized/.test(document.querySelector('.hc-logs').textContent));
  assert.deepEqual(errors, []);
});

test('no realm yet: the setup start (Vanilla+ always on, Link my server) and the guide', async () => {
  const { page, errors } = await open(false);
  assert.equal(await page.textContent('#hc-tab-main'), 'Start');
  await page.waitForFunction(() => document.querySelectorAll('.hc-rs').length === 5);
  assert.deepEqual(await page.$$eval('.hc-rs', (l) => l.map((x) => [x.dataset.profile, x.querySelector('b').textContent, x.disabled])),
    [['vanillaplus', 'Vanilla+', false], ['den', 'My Den', false], ['dalaran', 'Dalaran hangout', false], ['main', 'Classic levelling', false], ['cmangos-1.12.1', 'True Vanilla', true]]);
  assert.equal(await page.textContent('.hc-rs[data-profile="vanillaplus"] em'), 'Always on');
  assert.ok(await page.isDisabled('#hc-start'));
  await page.click('.hc-rs[data-profile="vanillaplus"]');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_choose'));
  assert.deepEqual((await calls(page, 'host_choose'))[0], { profile: 'vanillaplus', clientId: 'c1' });
  assert.equal(await page.textContent('#hc-start'), 'Start Vanilla+');
  assert.match(await page.textContent('.hc-go'), /Always on/);
  await page.click('#hc-start');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_start'));
  await page.click('#hc-link');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_link_start'));
  assert.match(await page.textContent('.hc-start .hc-status'), /four questions/);
  assert.match(await page.textContent('.hc-pre'), /Host pack ready.*Docker ready/);

  // the guide beside it, and on its own tab; its links are names in the core's list, never a URL
  assert.equal(await page.locator('.hc-side .hc-g').count(), 10);
  await page.click('#hc-tab-guide');
  assert.ok(await page.isVisible('#hc-pane-guide'));
  const topics = await page.$$eval('#hc-pane-guide .hc-g summary', (l) => l.map((x) => x.textContent));
  assert.deepEqual(topics, ['Start your realm', 'Stop it', 'Update', 'Go public', 'Invite friends', 'Claim it with your Hero Key', 'Always on',
    'Link a server you already run', 'Backups', "When something's wrong"]);
  await page.click('#hc-pane-guide .hc-g[data-topic="alwayson"] summary');
  await page.click('#hc-pane-guide .hc-g[data-topic="alwayson"] .hc-more');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'open_link'));
  assert.deepEqual((await calls(page, 'open_link'))[0], { name: 'alwayson' });
  const names = await page.$$eval('#hc-pane-guide .hc-more', (l) => [...new Set(l.map((x) => x.dataset.link))].sort());
  assert.deepEqual(names, ['alwayson', 'hostdocs']);
  // the kit and its settings are one tab away
  await page.click('#hc-tab-kit');
  assert.ok(await page.isVisible('#hp-card') && await page.isVisible("#hc-pane-kit ol.steps"));
  assert.doesNotMatch(await page.textContent('#page-host'), NO_BRANDS);
  assert.deepEqual(errors, []);
});

test('Make my Den: private and invite-only, no bots, no player limit; picked from the play bar; its console', async () => {
  const { page, errors } = await open(false);
  await page.waitForFunction(() => document.querySelectorAll('.hc-rs').length === 5);
  const card = '.hc-rs[data-profile="den"]';
  assert.equal(await page.textContent(`${card} .hc-rs-l`), 'A private room to build in: you and the friends you invite. No bots.');
  assert.equal(await page.textContent(`${card} em`), 'Private');
  assert.equal(await page.isVisible('.hc-den'), false, 'the Den facts only once it is picked');
  await page.click(card);
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'host_choose' && a.profile === 'den'));
  assert.equal(await page.textContent('#hc-start'), 'Start My Den');
  assert.ok(await page.isVisible('.hc-den'));
  assert.deepEqual(await page.$$eval('.hc-den li', (l) => l.map((x) => x.querySelector('b').textContent)), ['Private', 'Sign-up', 'No bots']);
  assert.match(await page.textContent('.hc-den'), /invite link only/);
  assert.equal(await page.locator('#page-host input[type="number"]:visible, #page-host [data-tool="max"]:visible').count(), 0, 'no bots or max-players control');
  await page.click('.hc-rs[data-profile="main"]');
  assert.equal(await page.isVisible('.hc-den'), false);
  // the play bar's My Den asks for it: picked again
  await page.evaluate(() => document.dispatchEvent(new CustomEvent('leyline:host-ruleset', { detail: { profile: 'den' } })));
  await page.waitForFunction(() => document.querySelector('.hc-rs[data-profile="den"].on'));
  assert.equal((await calls(page, 'host_choose')).pop().profile, 'den');
  await page.click('#hc-start');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'host_start'));
  assert.doesNotMatch(await page.textContent('#page-host'), NO_BRANDS);
  assert.deepEqual(errors, []);

  // a Den set up on this PC: its console, with no Max players tool
  const den = await open('den');
  await den.page.waitForFunction(() => document.querySelector('.hc-run') && document.querySelector('.hc-run').textContent === 'Online · private');
  assert.equal(await den.page.textContent('.hc-k'), 'Your Den');
  assert.equal(await den.page.textContent('.hc-t'), 'My Den');
  const shown = await den.page.$$eval('.hc-tool', (l) => l.filter((x) => !x.parentElement.hidden).map((x) => x.dataset.tool));
  assert.ok(!shown.includes('max') && shown.includes('invite') && shown.includes('signup'), shown.join(','));
  assert.deepEqual(den.errors, []);
});

test('the console in the Light theme reads the light tokens', async () => {
  const { page, errors } = await open(true, true);
  await page.evaluate(() => { document.documentElement.dataset.base = 'light'; });
  await page.waitForFunction(() => document.querySelector('.hc-run').textContent === 'Online · listed');
  const bg = await page.evaluate(() => getComputedStyle(document.querySelector('.hc-sw')).backgroundImage);
  assert.match(bg, /rgb\(253, 252, 249\)/, 'the light slate');
  const tile = await page.evaluate(() => getComputedStyle(document.querySelector('.hc-tile b')).color);
  assert.equal(tile, 'rgb(20, 24, 32)', 'dark text on light');
  assert.deepEqual(errors, []);
});

test('no Host pack yet: two big numbered steps come first, and Get the Host pack installs and uses it', async () => {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.addInitScript(() => { window.__noKit = true; });
  await page.addInitScript(FAKE, false);
  await page.goto(INDEX);
  await page.click('.nav[data-page="host"]');
  await page.waitForSelector('.hc-ready:not([hidden]) .hc-step');
  const steps = await page.$$eval('.hc-step', (l) => l.map((x) => [x.querySelector('b').textContent, x.classList.contains('done')]));
  assert.deepEqual(steps, [['Get the Host pack', false], ['Get Docker', false]]);
  assert.equal(await page.textContent('#hc-get-pack'), 'Get the Host pack');
  const order = await page.evaluate(() => { const r = document.querySelector('.hc-ready'), g = document.querySelector('.hc-rulesets');
    return !!(r.compareDocumentPosition(g) & Node.DOCUMENT_POSITION_FOLLOWING); });
  assert.ok(order, 'the steps come before the rulesets');
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
  await page.click('#hc-get-pack');
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'set_host_kit'));
  assert.ok((await calls(page, 'hostpack_install')).length === 1);
  assert.deepEqual((await calls(page, 'set_host_kit'))[0], { path: '/home/me/kit' });
  await page.close();
});
