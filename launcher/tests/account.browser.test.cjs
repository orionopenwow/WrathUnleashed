// Manage account and the sign-in in steps (ui/account.js, ui/social.js) in Chromium, with a fake Tauri core (owner
// 2026-10-30: "Allow manage account within launcher, bio profile pic etc basic stuff, smooth out the login process,
// incorporate hero key gmail and discord signin in sign in phases on site and launcher").
//
// Covers: the chooser (Hero Key, Google, Discord; a way the website doesn't offer is hidden), the way rides to the core
// (social_signin_start {via}), the waiting state (code, open again, cancel), auto-continue, a refused or expired code
// (an error and the chooser again), the first-time profile step (step 2, Skip, Save and continue, back where you were),
// the profile page (picture, name#tag, bio; name rules before any call; only changed fields sent; the server's refusal
// shown), the ways to sign in (each a named link, never a URL), Sign out, pictures only from the website's avatar
// addresses, and names as text.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/account.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');
const PIC = (id) => `https://play.openvanilla.app/wrath/avatar/p/${id}.svg`;
const SVG = (c) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="${c}"/></svg>`;

const FAKE = (o) => {
  const opts = o || {};
  const calls = (window.__calls = []);
  let signed = !!opts.signed;
  const avatars = ['star', 'moon', 'flame'].map((id) => ({ id, name: id[0].toUpperCase() + id.slice(1), url: `https://play.openvanilla.app/wrath/avatar/p/${id}.svg` }));
  const prof = { bio: opts.bio || '', avatar: opts.avatar || '', setup: opts.setup !== false,
    avatar_url: opts.picUrl || 'https://play.openvanilla.app/wrath/avatar/u/aaaaaaaaaa.svg?v=2' };
  let name = opts.evil ? '<img src=x onerror=window.__xss=1>' : 'Alice';
  window.__poll = opts.poll || 'signed_in';
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: true, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'social_status': return signed;
      case 'social_ways': return { herokey: true, google: true, discord: !!opts.discord };
      case 'social_signin_start': return { state: 'pending', user_code: 'BCDF-GHJK', verify_url: 'https://play.openvanilla.app/wrath/link?code=BCDF-GHJK' };
      case 'social_signin_poll': if (window.__poll === 'signed_in') signed = true; return { state: window.__poll, user_code: 'BCDF-GHJK', verify_url: '' };
      case 'social_signin_cancel': return null;
      case 'social_signin_reopen': return null;
      case 'social_signout': signed = false; return null;
      case 'social_call':
        if (args.action === 'me') return { me: { pid: 'aaaaaaaaaa', name, tag: '4821', main: '', offline: false, profile: { ...prof } },
          avatars, ways: { herokey: true, google: true, discord: !!opts.discord }, manage_url: 'https://play.openvanilla.app/wrath/profile' };
        if (args.action === 'profile') {
          if (opts.refuse) throw 'Pick another name.';
          const a = args.args;
          if ('name' in a) name = a.name;
          if ('bio' in a) prof.bio = a.bio;
          if ('avatar' in a) { prof.avatar = a.avatar; prof.avatar_url = 'https://play.openvanilla.app/wrath/avatar/u/aaaaaaaaaa.svg?v=3'; }
          if ('setup' in a) prof.setup = a.setup;
          return { ok: true, me: { pid: 'aaaaaaaaaa', name, tag: '4821', main: '', show_main: false, offline: false, profile: { ...prof } } };
        }
        throw 'unexpected social call ' + args.action;
      case 'forum_call': return { threads: [], categories: [] };
      case 'open_link': return null;
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  const errors = [], fetched = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('https://play.openvanilla.app/wrath/avatar/**', (r) => { fetched.push(r.request().url());
    r.fulfill({ body: SVG('#5b8def'), contentType: 'image/svg+xml' }); });
  await page.route('https://evil.example/**', (r) => { fetched.push(r.request().url()); r.fulfill({ body: SVG('red'), contentType: 'image/svg+xml' }); });
  await page.route('https://play.openvanilla.app/wrath/art/**', (r) => r.abort());
  await page.addInitScript(FAKE, opts || {});
  await page.goto(INDEX);
  return { page, errors, fetched };
}
const called = (page, cmd, pred) => page.evaluate(([c, p]) => window.__calls.some(([x, a]) => x === c && (!p || new Function('a', 'return ' + p)(a))), [cmd, pred || '']);

test('signed out: SIGN IN opens the chooser; only the ways the website offers', async () => {
  const { page, errors } = await open();
  await page.click('#hf-signin');
  await page.waitForSelector('#hf-code:not([hidden]) .sf-way');
  assert.deepEqual(await page.$$eval('#hf-code .sf-way', (b) => b.map((x) => x.dataset.via)), ['herokey', 'google']);
  assert.match(await page.textContent('#hf-code'), /never see your password/);
  await page.keyboard.press('Escape');
  assert.ok(await page.isHidden('#hf-code'), 'Escape closes it');
  await page.close();
  const o = await open({ discord: true });
  await o.page.click('#hf-signin');
  await o.page.waitForFunction(() => document.querySelectorAll('#hf-code .sf-way').length === 3);
  assert.deepEqual(await o.page.$$eval('#hf-code .sf-way', (b) => b.map((x) => x.textContent)), ['Sign in with your Hero Key', 'Continue with Google', 'Continue with Discord']);
  assert.deepEqual([...errors, ...o.errors], []);
  await o.page.close();
});

test('the way goes to the core; the code waits; first time: the profile step, then back where you were', async () => {
  const { page, errors } = await open({ setup: false });
  await page.click('.nav[data-page="realms"]');
  await page.click('#hf-signin');
  await page.click('#hf-code .sf-way[data-via="google"]');
  await page.waitForSelector('#hf-code .sx-code');
  assert.ok(await called(page, 'social_signin_start', 'a.via === "google"'));
  assert.match(await page.textContent('#hf-code'), /Waiting for your browser.*with Google/);
  assert.equal(await page.textContent('#hf-code .sx-code'), 'BCDF-GHJK');
  await page.click('#hf-code button:has-text("OPEN THE PAGE AGAIN")');
  assert.ok(await called(page, 'social_signin_reopen'));
  // continues by itself: signed in, and the first time Manage account opens on step 2
  await page.waitForSelector('#page-account.on .ac-welcome', { timeout: 9000 });
  assert.match(await page.textContent('#ac-view .ac-steps li.on'), /Your profile/);
  assert.match(await page.textContent('#ac-view h2'), /Welcome, Alice/);
  assert.ok(await page.isHidden('#hf-code'));
  await page.check('#ac-view input[name="ac-avatar"][value="moon"]', { force: true });
  await page.fill('#ac-bio', 'Hosting on weekends');
  await page.click('#ac-save');
  await page.waitForSelector('#page-realms.on');
  assert.ok(await called(page, 'social_call', 'a.action === "profile" && a.args.setup === true && a.args.avatar === "moon" && a.args.bio === "Hosting on weekends" && !("name" in a.args)'));
  await page.waitForFunction(() => document.querySelector('#hf-me .hf-me-av img'));
  assert.match(await page.getAttribute('#hf-me .hf-me-av img', 'src'), /avatar\/u\/aaaaaaaaaa\.svg\?v=3$/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('Skip for now marks the step done and sends nothing else', async () => {
  const { page, errors } = await open({ setup: false });
  await page.click('#hf-signin');
  await page.click('#hf-code .sf-way[data-via="herokey"]');
  await page.waitForSelector('#ac-skip', { timeout: 9000 });
  await page.click('#ac-skip');
  await page.waitForSelector('#page-play.on');
  assert.ok(await called(page, 'social_call', 'a.action === "profile" && JSON.stringify(a.args) === JSON.stringify({setup: true})'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('a refused or expired code: why, and the chooser again; Cancel stops waiting', async () => {
  const { page, errors } = await open({ poll: 'denied' });
  await page.click('#hf-signin');
  await page.click('#hf-code .sf-way[data-via="herokey"]');
  await page.waitForSelector('#hf-code .sf-err', { timeout: 9000 });
  assert.match(await page.textContent('#hf-code .sf-err'), /refused/);
  assert.ok(await page.isVisible('#hf-code .sf-way[data-via="google"]'), 'pick again');
  await page.evaluate(() => { window.__poll = 'expired'; });
  await page.click('#hf-code .sf-way[data-via="google"]');
  await page.waitForFunction(() => /expired/.test((document.querySelector('#hf-code .sf-err') || {}).textContent || ''), null, { timeout: 9000 });
  await page.evaluate(() => { window.__poll = 'pending'; });
  await page.click('#hf-code .sf-way[data-via="herokey"]');
  await page.waitForSelector('#hf-code .sx-code');
  await page.click('#hf-code button:has-text("Cancel")');
  assert.ok(await called(page, 'social_signin_cancel'));
  assert.ok(await page.isHidden('#hf-code'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('Manage account signed out: step 1 and the same chooser on the page', async () => {
  const { page, errors } = await open({ discord: true });
  await page.evaluate(() => window.LeylineNav.show('account'));
  await page.waitForFunction(() => document.querySelectorAll('#ac-view .sf-way').length === 3);
  assert.match(await page.textContent('#ac-view .ac-steps li.on'), /Sign in/);
  await page.click('#ac-view .sf-way[data-via="discord"]');
  await page.waitForSelector('#ac-view .sx-code');
  assert.ok(await called(page, 'social_signin_start', 'a.via === "discord"'));
  assert.ok(await page.isHidden('#hf-code'), 'no pop-over on top of the page');
  assert.deepEqual(errors, []);
  await page.close();
});

test('Manage account signed in: picture, name#tag, bio; save only what changed; the name rules first; refusals shown', async () => {
  const { page, errors } = await open({ signed: true, bio: 'Hello', avatar: 'star', discord: true });
  await page.waitForSelector('#hf-me-btn');
  await page.click('#hf-me-btn');
  await page.click('#hf-me [role="menuitem"]:has-text("Manage account")');
  await page.waitForSelector('#ac-view .ac-head');
  assert.match(await page.textContent('#ac-view .ac-me-n'), /Alice#4821/);
  assert.equal(await page.textContent('#ac-view .ac-me-bio'), 'Hello');
  assert.ok(await page.isChecked('#ac-view input[name="ac-avatar"][value="star"]'));
  assert.equal(await page.inputValue('#ac-name'), 'Alice');
  await page.fill('#ac-name', 'x');
  await page.click('#ac-save');
  assert.match(await page.textContent('#ac-status'), /2 to 24/);
  assert.ok(!(await called(page, 'social_call', 'a.action === "profile"')), 'refused before any call');
  await page.fill('#ac-name', 'Alice');
  await page.fill('#ac-bio', 'Hello there');
  assert.equal(await page.textContent('.ac-count'), '11/300');
  await page.click('#ac-save');
  await page.waitForFunction(() => /Saved/.test(document.getElementById('ac-status').textContent));
  assert.ok(await called(page, 'social_call', 'a.action === "profile" && JSON.stringify(a.args) === JSON.stringify({setup: true, bio: "Hello there"})'));
  assert.equal(await page.textContent('#ac-view .ac-me-bio'), 'Hello there');
  // the ways: named links only
  assert.deepEqual(await page.$$eval('#ac-view .ac-ways button', (b) => b.map((x) => x.dataset.link)), ['herokey', 'linkgoogle', 'linkdiscord', 'linkedlaunchers']);
  await page.click('#ac-view .ac-ways button[data-link="linkgoogle"]');
  assert.ok(await called(page, 'open_link', 'a.name === "linkgoogle"'));
  await page.click('#ac-view button:has-text("Your profile on the website")');
  assert.ok(await called(page, 'open_link', 'a.name === "profile"'));
  await page.click('#ac-signout');
  await page.waitForSelector('#ac-view .ac-signin');
  assert.ok(await called(page, 'social_signout'));
  assert.ok(await page.isVisible('#hf-signin'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('the server refusing a name shows its words', async () => {
  const { page, errors } = await open({ signed: true, refuse: true });
  await page.waitForSelector('#hf-me-btn');
  await page.evaluate(() => window.LeylineNav.show('account'));
  await page.waitForSelector('#ac-name');
  await page.fill('#ac-name', 'Bobby');
  await page.click('#ac-save');
  await page.waitForFunction(() => /Pick another name/.test(document.getElementById('ac-status').textContent));
  assert.ok(await page.isEnabled('#ac-save'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('pictures load only from the website\'s avatar addresses; names are text', async () => {
  const { page, errors, fetched } = await open({ signed: true, evil: true, picUrl: 'https://evil.example/x.svg' });
  await page.waitForSelector('#hf-me-btn');
  assert.equal(await page.textContent('#hf-me .hf-me-name'), '<img src=x onerror=window.__xss=1>');
  assert.equal(await page.locator('#hf-me .hf-me-av img').count(), 0, 'no picture from elsewhere');
  await page.evaluate(() => window.LeylineNav.show('account'));
  await page.waitForSelector('#ac-view .ac-pics');
  await page.waitForTimeout(300);
  assert.ok(!fetched.some((u) => u.startsWith('https://evil.example')), 'never fetched');
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.equal(await page.locator('#ac-view .ac-pics input').count(), 4, 'your initial and the presets');
  assert.deepEqual(errors, []);
  await page.close();
});
