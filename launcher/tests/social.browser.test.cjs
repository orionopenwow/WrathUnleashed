// The launcher's Friends page (ui/social.js) in Chromium, with a fake Tauri core: the nav button and page appear and
// work with app.js's navigation, sign-in by code, the friends list with presence and unread, a conversation, sending,
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

test('Friends page: sign in, list, chat, accept, text only, sign-out on revoke', async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE);
  await page.goto(INDEX);
  const nav = page.locator('.nav[data-page="friends"]');
  assert.equal(await nav.count(), 1, 'one Friends nav button');
  await nav.click();
  assert.ok(await page.locator('#page-friends').evaluate((e) => e.classList.contains('on')), "app.js's navigation shows the page");
  assert.ok(await page.locator('#sx-out').isVisible(), 'signed out: the sign-in screen');

  await page.click('#sx-signin');
  assert.equal(await page.textContent('#sx-code-text'), 'BCDF-GHJK');
  await page.waitForSelector('#sx-in:not([hidden])', { timeout: 9000 });
  assert.match(await page.textContent('#sx-me'), /Alice#4821/);
  const rows = page.locator('.sx-friend');
  assert.equal(await rows.count(), 2);
  assert.match(await rows.nth(0).textContent(), /Bob.*In game: Bobbert on WrathUnleashed.*2/);
  assert.equal(await page.textContent('#nav-friends-count'), '3', 'unread + requests on the nav badge');
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
  await page.waitForFunction(() => document.querySelectorAll('.sx-friend').length === 3);

  await page.click('#sx-block');
  assert.equal(await page.textContent('#sx-block'), 'SURE?', 'block asks once more');
  await page.click('#sx-block');
  await page.waitForFunction(() => window.__calls.some(([c, a]) => c === 'social_call' && a.action === 'block' && a.args.pid === 'bbbbbbbbbb'));

  await page.evaluate(() => { window.__revoke(); window.__wake(); });
  await page.waitForSelector('#sx-out:not([hidden])');
  assert.match(await page.textContent('#sx-status'), /signed out/i);
  assert.deepEqual(errors, []);
});
