// Home's right panel (ui/social.js) in Chromium, with a fake Tauri core (owner 2026-10-30: "remove the friends area and
// concept in favor of discord encouragement and keep the profile thing up there where it is now"): the profile row stays
// (avatar, your name with its menu: Manage account and Sign out, no Appear online/offline; signed out: Sign in, the
// code shown in the panel, signed in after you approve), under it a Join the Discord card and the forum's latest three
// threads (a row opens the thread on the Forum page). No friends list, chat, friend badge or presence anywhere; names
// and titles shown as text, never markup; a revoked sign-in goes back to Sign in.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/social.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');

const THREADS = [
  { id: 7, cat: 'realms', title: 'Frost Haven: a cosy realm', author: 'Bramble', tag: '4655', created: 1, bumped: 2, replies: 3, pinned: false, locked: false },
  { id: 8, cat: 'dens', title: '<img src=x onerror=window.__xss=1>', author: 'Kestrel', tag: '1', created: 1, bumped: 2, replies: 1, pinned: false, locked: false },
  { id: 9, cat: 'help', title: 'Game folder not found', author: 'Alice', tag: '4821', created: 1, bumped: 2, replies: 0, pinned: false, locked: false },
];

// The fake core: get_state for app.js, the social_* and forum_* commands. window.__calls records them.
const FAKE = (opts) => {
  const calls = (window.__calls = []);
  let signed = !!(opts && opts.signed), polls = 0, revoked = false;
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: true, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'social_status': return signed;
      case 'social_ways': return { herokey: true, google: true, discord: false };
      case 'social_signin_start': return { state: 'pending', user_code: 'BCDF-GHJK', verify_url: 'https://play.openvanilla.app/wrath/link?code=BCDF-GHJK' };
      case 'social_signin_poll': polls++; signed = true; return { state: 'signed_in', user_code: 'BCDF-GHJK', verify_url: '' };
      case 'social_signout': signed = false; return null;
      case 'social_call':
        if (revoked) throw 'signed_out';
        if (args.action === 'me') return { me: { pid: 'aaaaaaaaaa', name: opts && opts.evil ? '<b>Alice</b>' : 'Alice', tag: '4821', main: '', offline: false } };
        throw 'unexpected social call ' + args.action;
      case 'forum_call':
        if (args.action === 'latest') return { threads: window.__threads.slice(0, args.args.n || 8) };
        if (args.action === 'categories') return { format: 1, categories: [{ id: 'realms', name: 'Share your realm', line: 'x', staff_only: false, threads: 1, posts: 1, last: null }] };
        if (args.action === 'thread') return { thread: Object.assign({}, window.__threads[0], { id: args.args.id }), posts: [], page: 1, pages: 1, more: false };
        throw 'unexpected forum call';
      case 'open_link': return null;
      default: throw 'unknown ' + cmd;
    }
  } } };
  window.__revoke = () => { revoked = true; };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript((t) => { window.__threads = t; }, THREADS);
  await page.addInitScript(FAKE, opts || {});
  await page.goto(INDEX);
  return { page, errors };
}

test('no friends anywhere: no Friends tab, chat, friends list, badge or presence', async () => {
  const { page, errors } = await open({ signed: true });
  await page.waitForFunction(() => document.querySelector('#hf-me .hf-me-name') && document.querySelector('#hf-me .hf-me-name').textContent === 'Alice');
  assert.equal(await page.locator('#page-community, #pane-friends, #sx-chat, #sx-friends, #hf-list, #hf-tools, #hf-q, #hf-add, #nav-friends-count, #tab-friends-count, .sx-dot, .sx-friend').count(), 0);
  assert.equal(await page.locator('.nav[data-page="community"], .nav[data-page="friends"]').count(), 0);
  const text = await page.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /\bfriends? list|add a friend|friend request|appear (on|off)line|search friends/i);
  assert.ok(!(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'social_call' && ['state', 'events'].includes(a.action)))), 'no friends state or presence poll');
  assert.deepEqual(errors, []);
  await page.close();
});

test('signed in: the profile sits in the title bar, top right, with Manage account and Sign out', async () => {
  const { page, errors } = await open({ signed: true });
  await page.waitForFunction(() => document.querySelector('#hf-me .hf-me-name') && document.querySelector('#hf-me .hf-me-name').textContent === 'Alice');
  assert.equal(await page.textContent('#hf-me .hf-me-st'), '#4821');
  assert.equal(await page.getAttribute('#hf-me-btn', 'title'), 'Alice#4821');
  // owner 2026-10-30 22:11: the side panel is hidden; the profile is in the title bar beside the window buttons
  const r = await page.evaluate(() => {
    const me = document.getElementById('hf-me').getBoundingClientRect();
    const win = document.querySelector('.titlebar .winbtns').getBoundingClientRect();
    return { inBar: !!document.getElementById('hf-me').closest('.titlebar'), top: Math.round(me.top), gap: Math.round(win.left - me.right) };
  });
  assert.ok(r.inBar, 'in the title bar'); assert.ok(r.top < 30, 'at the top'); assert.ok(r.gap >= 0 && r.gap < 40, 'just left of the window buttons');
  await page.click('#hf-me-btn');
  assert.deepEqual(await page.$$eval('#hf-me [role="menuitem"]', (b) => b.map((x) => x.textContent)), ['Manage account', 'Sign out']);
  await page.click('#hf-me [role="menuitem"]:has-text("Manage account")');
  // Manage account is a page in the launcher now (account.js), not the website
  await page.waitForSelector('#page-account.on');
  assert.ok(!(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_link' && a.name === 'account'))));
  await page.click('#hf-me-btn');
  await page.click('#hf-me [role="menuitem"]:has-text("Sign out")');
  await page.waitForSelector('#hf-signin');
  assert.ok(await page.evaluate(() => window.__calls.some(([c]) => c === 'social_signout')));
  assert.match(await page.textContent('#hf-status'), /Signed out/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('signed out: Sign in, pick a way, the code under the chip, then your name', async () => {
  const { page, errors } = await open();
  await page.waitForSelector('#hf-signin');
  assert.equal(await page.textContent('#hf-me .hf-me-st'), 'Signed out');
  await page.click('#hf-signin');
  await page.waitForSelector('#hf-code:not([hidden]) .sf-way');
  await page.click('#hf-code .sf-way[data-via="herokey"]');
  await page.waitForSelector('#hf-code .sx-code');
  assert.match(await page.textContent('#hf-code'), /BCDF-GHJK/);
  await page.waitForFunction(() => document.querySelector('#hf-me .hf-me-name') && document.querySelector('#hf-me .hf-me-name').textContent === 'Alice', null, { timeout: 9000 });
  assert.ok(await page.isHidden('#hf-code'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('the side panel is hidden: Home uses the full width; a subtle Join the Discord sits right of the search', async () => {
  const { page, errors } = await open({ signed: true, evil: true });
  await page.waitForFunction(() => document.querySelector('#hf-me .hf-me-name'));
  assert.equal(await page.textContent('#hf-me .hf-me-name'), '<b>Alice</b>', 'a name is text');
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.ok(await page.isHidden('#home-side'), 'the panel is hidden');
  const g = await page.evaluate(() => {
    const s = document.getElementById('search-form').getBoundingClientRect(), d = document.getElementById('tb-discord').getBoundingClientRect();
    const m = document.querySelector('main').getBoundingClientRect();
    return { after: Math.round(d.left - s.right), sameRow: Math.abs((d.top + d.bottom) / 2 - (s.top + s.bottom) / 2) < 4, mainRight: Math.round(innerWidth - m.right) };
  });
  assert.ok(g.after >= 0 && g.after < 60, 'right of the search'); assert.ok(g.sameRow, 'on the same row');
  assert.equal(g.mainRight, 0, 'Home reaches the window edge again');
  assert.match(await page.textContent('#tb-discord'), /Join the Discord/);
  await page.click('#tb-discord');
  assert.ok(await page.evaluate(() => window.__calls.some(([c, a]) => c === 'open_link' && a.name === 'discord')), 'opens the Discord through openLink');
  assert.deepEqual(errors, []);
  await page.close();
});

test('a revoked sign-in goes back to Sign in', async () => {
  const { page, errors } = await open({ signed: true });
  await page.waitForFunction(() => document.querySelector('#hf-me-btn'));
  await page.evaluate(() => { window.__revoke(); return window.LeylineSocial.refresh(); });
  await page.waitForSelector('#hf-signin');
  assert.match(await page.textContent('#hf-status'), /signed out/i);
  assert.deepEqual(errors, []);
  await page.close();
});
