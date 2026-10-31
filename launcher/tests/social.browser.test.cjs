// The launcher's Community › Friends tab (ui/social.js) in Chromium, with a fake Tauri core: the Community menu item and
// its Friends tab work with app.js's navigation, Home's friends panel (groups, counts, search, folding, your menu), sign-in by code, the friends list with presence and unread, a conversation, sending,
// accepting a request, names shown as text (never markup), and a revoked sign-in going back to the sign-in screen.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/social.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');

// The fake core: get_state for app.js, the social_* commands for social.js. window.__calls records them.
const FAKE = () => {
  const calls = (window.__calls = []);
  let signed = false, polls = 0, v = 1, revoked = false;
  const me = { pid: 'aaaaaaaaaa', name: 'Alice', tag: '4821', main: '', show_main: false, offline: false, status: 'launcher' };
  const st = {
    v, me, outgoing: [], blocked: [],
    incoming: [{ pid: 'cccccccccc', name: 'Carol', tag: '1111', at: 1 }],
    friends: [
      { pid: 'bbbbbbbbbb', name: 'Bob', tag: '2222', main: '', status: 'game', realm: 'WrathUnleashed', char: 'Bobbert', unread: 2 },
      { pid: 'dddddddddd', name: '<img src=x onerror=window.__xss=1>', tag: '3333', main: '', status: 'offline', realm: '', char: '', unread: 0 },
    ],
  };
  const thread = [{ id: 1, mine: false, text: 'hi <b>alice</b>', at: 1700000000, via: 'game' }];
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: true, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'social_status': return signed;
      case 'social_signin_start': return { state: 'pending', user_code: 'BCDF-GHJK', verify_url: 'https://play.openvanilla.app/wrath/link?code=BCDF-GHJK' };
      case 'social_signin_poll': polls++; if (polls >= 1) { signed = true; return { state: 'signed_in', user_code: 'BCDF-GHJK', verify_url: '' }; }
        return { state: 'pending' };
      case 'social_call': {
        if (revoked) throw 'signed_out';
        const a = args.action, p = args.args || {};
        if (a === 'state') return st;
        if (a === 'events') return new Promise((r) => { window.__wake = () => r(Object.assign({}, st, { v: ++v })); });
        if (a === 'thread') return { messages: thread };
        if (a === 'read') { st.friends[0].unread = 0; return { ok: true }; }
        if (a === 'send') { const m = { id: 9, mine: true, text: p.text, at: 1700000100, via: 'launcher' }; thread.push(m); return { ok: true, message: m }; }
        if (a === 'accept') { st.incoming = []; st.friends.push({ pid: 'cccccccccc', name: 'Carol', tag: '1111', status: 'offline', realm: '', char: '', unread: 0 }); return { ok: true, text: "You're friends now." }; }
        return { ok: true, text: 'ok' };
      }
      default: throw 'unknown ' + cmd;
    }
  } } };
  window.__revoke = () => { revoked = true; };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

test('Community › Friends: sign in, list, chat, accept, text only, sign-out on revoke', async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE);
  await page.goto(INDEX);
  assert.equal(await page.locator('.nav[data-page="friends"]').count(), 0, 'no Friends menu item of its own');
  const nav = page.locator('.nav[data-page="community"]');
  assert.equal(await nav.count(), 1, 'one Community menu item');
  await nav.click();
  assert.ok(await page.locator('#page-community').evaluate((e) => e.classList.contains('on')), "app.js's navigation shows the page");
  assert.ok(await page.locator('#pane-friends').evaluate((e) => e.classList.contains('on')), 'on its Friends tab');
  assert.equal(await page.getAttribute('#tab-community-friends', 'aria-selected'), 'true');
  assert.ok(await page.locator('#sx-out').isVisible(), 'signed out: the sign-in screen');

  await page.click('#sx-signin');
  assert.equal(await page.textContent('#sx-code-text'), 'BCDF-GHJK');
  await page.waitForSelector('#sx-in:not([hidden])', { timeout: 9000 });
  assert.match(await page.textContent('#sx-me'), /Alice#4821/);
  const rows = page.locator('#sx-friends .sx-friend');
  assert.equal(await rows.count(), 2);
  assert.equal(await page.locator('#hf-list .hf-group[data-group="friends"] .sx-friend').count(), 2, "Home's friends panel lists them too");
  assert.match(await rows.nth(0).textContent(), /Bob.*In game: Bobbert on WrathUnleashed.*2/);
  assert.equal(await page.textContent('#nav-friends-count'), '3', 'unread + requests on the Community menu item');
  assert.equal(await page.textContent('#tab-friends-count'), '3', 'and on the Friends tab');
  assert.match(await rows.nth(1).textContent(), /<img src=x/, 'a name is shown as text');
  assert.equal(await page.evaluate(() => window.__xss), undefined, 'and never runs');

  await rows.nth(0).click();
  await page.waitForSelector('.sx-msg');
  assert.match(await page.textContent('.sx-msg'), /hi <b>alice<\/b>.*in game/);
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'social_call' && a.action === 'read')), 'opening marks it read');
  await page.fill('#sx-say', 'hello bob');
  await page.press('#sx-say', 'Enter');
  await page.waitForSelector('.sx-msg.mine');
  const sent = await page.evaluate(() => window.__calls.find(([c, a]) => c === 'social_call' && a.action === 'send')[1].args);
  assert.deepEqual(sent, { to: 'bbbbbbbbbb', text: 'hello bob' });

  await page.click('.sx-req button:has-text("ACCEPT")');
  await page.waitForFunction(() => document.querySelectorAll('#sx-friends .sx-friend').length === 3);

  await page.click('#sx-block');
  assert.equal(await page.textContent('#sx-block'), 'SURE?', 'block asks once more');
  await page.click('#sx-block');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'social_call' && a.action === 'block' && a.args.pid === 'bbbbbbbbbb'));

  await page.evaluate(() => { window.__revoke(); window.__wake(); });
  await page.waitForSelector('#sx-out:not([hidden])');
  assert.match(await page.textContent('#sx-status'), /signed out/i);
  assert.deepEqual(errors, []);
});

// Home's right column: the friends list (owner 2026-10-30): your own row and its menu, Favorites and Friends with
// online / total counts (folding remembered), the search box, a row opening the chat; signed out, one line and Sign in.
test("Home's friends panel: your row, the groups and their counts, folding, search, a row opens the chat", async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE);
  await page.addInitScript(() => {
    const inner = window.__TAURI__.core.invoke;
    window.__TAURI__.core.invoke = async (cmd, args) => {
      if (cmd === 'social_status') return true;
      const r = await inner(cmd, args);
      if (cmd === 'social_call' && args.action === 'state' && !r.__done) {
        r.__done = true;
        r.friends[0].favorite = true;
        r.friends.push({ pid: 'eeeeeeeeee', name: 'Kestrel', tag: '5555', main: '', status: 'launcher', realm: '', char: '', unread: 0 });
      }
      return r;
    };
  });
  await page.goto(INDEX);
  await page.evaluate(() => localStorage.removeItem('leyline.friends.folded'));
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#hf-me .hf-me-name') && document.querySelector('#hf-me .hf-me-name').textContent === 'Alice');
  assert.equal(await page.textContent('#hf-me .hf-me-st'), 'Online');
  assert.ok(await page.isVisible('#hf-me .hf-me-av .sx-dot'), 'a status dot on your avatar');
  const heads = () => page.$$eval('#hf-list .hf-ghead', (h) => h.map((x) => x.textContent));
  assert.deepEqual(await heads(), ['Favorites – 1/1', 'Friends – 2/3']);
  const rows = (g) => page.$$eval(`#hf-list .hf-group[data-group="${g}"] .sx-friend .sx-ft b`, (b) => b.map((x) => x.textContent));
  assert.deepEqual(await rows('fav'), ['Bob']);
  assert.deepEqual(await rows('friends'), ['Bob', 'Kestrel', '<img src=x onerror=window.__xss=1>'], 'in game, online, then offline');
  const bob = page.locator('#hf-list .hf-group[data-group="friends"] .sx-friend').first();
  assert.ok(await bob.evaluate((e) => e.classList.contains('st-game')), 'the name in the status colour');
  assert.equal(await bob.locator('.sx-ft i').textContent(), 'In game: Bobbert on WrathUnleashed');
  assert.ok(await page.locator('#hf-list .sx-friend.st-offline').evaluate((e) => getComputedStyle(e.querySelector('.sx-av')).filter !== 'none'), 'offline greyed');
  assert.equal(await page.locator('#home-friends .sx-av').first().evaluate((e) => e.getBoundingClientRect().width), 38, 'your 38px avatar (the slim panel)');
  assert.equal(await bob.locator('.sx-av').evaluate((e) => e.getBoundingClientRect().width), 32, '32px rows (the slim panel)');
  // search filters the rows, the counts stay the group's
  await page.fill('#hf-q', 'kes');
  assert.deepEqual(await rows('friends'), ['Kestrel']);
  assert.deepEqual(await rows('fav'), []);
  assert.deepEqual(await heads(), ['Favorites – 1/1', 'Friends – 2/3']);
  await page.fill('#hf-q', 'nobody');
  assert.match(await page.textContent('#hf-list .hf-group[data-group="friends"]'), /No one by that name/);
  await page.fill('#hf-q', '');
  // folding: the triangle, remembered
  await page.click('#hf-list .hf-group[data-group="fav"] .hf-ghead');
  assert.equal(await page.getAttribute('#hf-list .hf-group[data-group="fav"] .hf-ghead', 'aria-expanded'), 'false');
  assert.ok(await page.isHidden('#hf-list .hf-group[data-group="fav"] .hf-rows'));
  assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('leyline.friends.folded'))), { fav: true, friends: false });
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#hf-list .hf-group[data-group="fav"] .sx-friend'));
  assert.ok(await page.isHidden('#hf-list .hf-group[data-group="fav"] .hf-rows'), 'still folded after a reload');
  // your menu: Appear offline
  await page.click('#hf-me-btn');
  assert.deepEqual(await page.$$eval('#hf-me [role="menuitem"]', (b) => b.map((x) => x.textContent)), ['Appear online', 'Appear offline', 'Manage account', 'Sign out']);
  await page.click('#hf-me [role="menuitem"]:has-text("Appear offline")');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'social_call' && a.action === 'profile'));
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'social_call' && a.action === 'profile' && a.args.offline === true)));
  // a row opens the chat; add a friend focuses the field on Community › Friends
  await page.click('#hf-list .hf-group[data-group="friends"] .sx-friend >> nth=0');
  assert.ok(await page.locator('#pane-friends').evaluate((e) => e.classList.contains('on')));
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'social_call' && a.action === 'thread' && a.args.with === 'bbbbbbbbbb'));
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.click('#hf-add');
  await page.waitForFunction(() => document.activeElement && document.activeElement.id === 'sx-add');
  await page.evaluate(() => window.LeylineNav.show('play'));
  await page.click('#home-friends .hf-open');
  assert.ok(await page.locator('#pane-friends').evaluate((e) => e.classList.contains('on')));
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.deepEqual(errors, []);
  await page.close();
});

test("Home's friends panel signed out: one line and SIGN IN, no search", async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE);
  await page.goto(INDEX);
  await page.waitForSelector('#hf-list .hf-out');
  assert.equal(await page.textContent('#hf-me .hf-me-st'), 'Not signed in');
  assert.ok(await page.isHidden('#hf-tools'));
  await page.click('#hf-list .hf-out button:has-text("SIGN IN")');
  assert.ok(await page.locator('#pane-friends').evaluate((e) => e.classList.contains('on')));
  await page.waitForFunction(() => window.__calls.some(([c]) => c === 'social_signin_start'), 'starts the sign-in');
  assert.deepEqual(errors, []);
  await page.close();
});
