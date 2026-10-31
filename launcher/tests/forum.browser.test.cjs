// The launcher's Forum page (ui/forum.js) in Chromium with a fake Tauri core: the side menu's Forum item (its icon,
// where Community was), the categories and the latest threads from the forum's JSON (forum_call), a category's threads
// with pinned and locked tags and paging, a thread with its posts (plain text, links as buttons that open through
// forum_open "link", a hidden post as one line, the Team badge), New thread and Reply opening the website (forum_open),
// title search, the old page ids landing here, an unreachable forum, and text never read as markup.
//
//   NODE_PATH=$(npm root -g) node --test launcher/tests/forum.browser.test.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const INDEX = 'file://' + path.join(__dirname, '..', 'ui', 'index.html');

const FAKE = (opts) => {
  const calls = (window.__calls = []);
  try { if (opts.page) localStorage.setItem('leyline.page', opts.page); else localStorage.removeItem('leyline.page'); } catch (_) { /* fine */ }
  const now = Math.floor(Date.now() / 1000);
  const T = (id, cat, title, extra) => Object.assign({ id, cat, title, author: 'Bramble', tag: '4655', created: now - 7200, bumped: now - 3600,
    replies: 2, pinned: false, locked: false, url: 'https://play.openvanilla.app/wrath/leyline/forum/t/' + id }, extra || {});
  const cats = [
    { id: 'realms', name: 'Share your realm', line: 'Realms you host and invite links.', staff_only: false, threads: 2, posts: 5, last: T(1, 'realms', 'Frost Haven') },
    { id: 'mods', name: 'Mods & addons', line: 'Share what you made.', staff_only: false, threads: 0, posts: 0, last: null },
    { id: 'news', name: 'Announcements', line: 'News from the team.', staff_only: true, threads: 1, posts: 1, last: null },
  ];
  const latest = [T(1, 'realms', 'Frost Haven'), T(2, 'realms', '<img src=x onerror=window.__xss=1>', { pinned: true, locked: true })];
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    calls.push([cmd, args]);
    switch (cmd) {
      case 'get_state': return { version: 'test', settings: { clients: [], selected_client: null, selected_realm: 'play.openvanilla.app',
        wine: { enabled: true, command: 'wine', prefix: '' } }, official_realm: 'play.openvanilla.app',
        browser_url: 'https://play.openvanilla.app/wrath', windows: false, data_dir: '/tmp' };
      case 'social_status': return false;
      case 'forum_open': case 'open_link': return null;
      case 'forum_call': {
        if (opts.down) throw "The forum isn't answering right now (timed out).";
        const a = args.action, p = args.args || {};
        if (a === 'categories') return { format: 1, categories: cats };
        if (a === 'latest') return { threads: latest.slice(0, p.n || 8) };
        if (a === 'threads') return { cat: p.cat, threads: p.page === 2 ? [T(3, p.cat, 'An older one')] : latest, page: p.page, more: p.page !== 2 };
        if (a === 'search') return { q: p.q, threads: [T(1, 'realms', 'Frost Haven')] };
        if (a === 'thread') return {
          thread: T(p.id, 'realms', p.id === 2 ? 'Locked one' : 'Frost Haven', { locked: p.id === 2 }), page: 1, pages: 1, more: false,
          reply_url: 'https://play.openvanilla.app/wrath/leyline/forum/t/' + p.id + '/reply',
          posts: [
            { id: 10, author: 'Bramble', tag: '4655', staff: false, at: now - 7200, hidden: false, text: 'Invite: https://play.openvanilla.app/wrath/i/frost <b>hi</b>',
              parts: [{ t: 'Invite: ' }, { u: 'https://play.openvanilla.app/wrath/i/frost' }, { t: ' <b>hi</b>' }] },
            { id: 11, author: '', tag: '', staff: false, at: now - 3000, hidden: true, text: '', parts: [] },
            { id: 12, author: 'Orion', tag: '1001', staff: true, at: now - 60, hidden: false, text: 'Welcome!', parts: [{ t: 'Welcome!' }] },
          ] };
        throw 'unknown forum action';
      }
      default: throw 'unknown ' + cmd;
    }
  } } };
};

let browser;
test.before(async () => { browser = await chromium.launch(); });
test.after(async () => { await browser.close(); });

async function open(opts) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(FAKE, opts || {});
  await page.goto(INDEX);
  await page.waitForFunction(() => window.LeylineNav && window.LeylineForum);
  return { page, errors };
}
const calls = (page, cmd) => page.evaluate((c) => window.__calls.filter(([x]) => x === c).map(([, a]) => a), cmd);

test('the Forum item: where Community was, with its icon; the categories and the latest threads', async () => {
  const { page, errors } = await open();
  const nav = page.locator('aside nav .nav[data-page="forum"]');
  assert.equal(await nav.count(), 1);
  assert.equal((await nav.textContent()).trim(), 'Forum');
  assert.equal(await nav.locator('svg path').count(), 2, 'the two speech bubbles');
  assert.deepEqual(await page.$$eval('aside nav .nav', (b) => b.map((x) => x.dataset.page)), ['play', 'realms', 'mods', 'host', 'forum', 'news']);
  await nav.click();
  await page.waitForSelector('#fm-view .fm-cats');
  assert.deepEqual(await page.$$eval('#fm-view .fm-cats .fm-row-t > b', (b) => b.map((x) => x.textContent)), ['Share your realm', 'Mods & addons', 'Announcements']);
  assert.match(await page.textContent('#fm-view .fm-cats li:first-child'), /Latest: Frost Haven.*2 threads/);
  const latest = page.locator('#fm-view .fm-box:nth-child(2) .fm-row');
  assert.equal(await latest.count(), 2);
  assert.match(await latest.nth(0).textContent(), /Frost Haven.*by Bramble in Share your realm · 2 hours ago.*2 replies · active 1 hour ago/);
  assert.match(await latest.nth(1).textContent(), /PinnedLocked<img src=x/, 'tags, and the title as text');
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.ok(await page.isVisible('#fm-discord'), 'Join the Discord on the page');
  await page.click('#fm-discord');
  assert.deepEqual((await calls(page, 'open_link')).pop(), { name: 'discord' });
  await page.click('#fm-new');
  assert.deepEqual((await calls(page, 'forum_open')).pop(), { kind: 'new', arg: null }, 'New thread opens the website');
  assert.deepEqual(errors, []);
  await page.close();
});

test('a category: its threads, paging, New thread here; Announcements is the team only', async () => {
  const { page, errors } = await open({ page: 'forum' });
  await page.waitForSelector('#fm-view .fm-cats');
  await page.click('#fm-view .fm-cats .fm-row >> nth=0');
  await page.waitForSelector('#fm-view .fm-title');
  assert.equal(await page.textContent('#fm-view .fm-title'), 'Share your realm');
  assert.deepEqual((await calls(page, 'forum_call')).pop(), { action: 'threads', args: { cat: 'realms', page: 1 } });
  await page.click('#fm-view button:has-text("NEW THREAD HERE")');
  assert.deepEqual((await calls(page, 'forum_open')).pop(), { kind: 'new', arg: 'realms' });
  await page.click('#fm-view .fm-pager button:has-text("Older")');
  await page.waitForFunction(() => /An older one/.test(document.getElementById('fm-view').textContent));
  assert.ok(await page.isVisible('#fm-view .fm-pager button:has-text("Newer")'));
  await page.click('#fm-view .fm-crumb button:has-text("Forum")');
  await page.waitForSelector('#fm-view .fm-cats');
  await page.click('#fm-view .fm-cats .fm-row >> nth=2');
  await page.waitForSelector('#fm-view .fm-title');
  assert.ok(await page.isDisabled('#fm-view button:has-text("THE TEAM POSTS HERE")'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('a thread: plain text, links as buttons, a removed post, the Team badge; Reply opens the website', async () => {
  const { page, errors } = await open({ page: 'forum' });
  await page.waitForSelector('#fm-view .fm-cats');
  await page.click('#fm-view .fm-box:nth-child(2) .fm-row >> nth=0');
  await page.waitForSelector('#fm-view .fm-post');
  const posts = page.locator('#fm-view .fm-post');
  assert.equal(await posts.count(), 3);
  assert.equal(await posts.nth(0).locator('.fm-text').textContent(), 'Invite: https://play.openvanilla.app/wrath/i/frost <b>hi</b>');
  assert.equal(await posts.nth(0).locator('.fm-text b').count(), 0, 'no markup from a post');
  await posts.nth(0).locator('.fm-link').click();
  assert.deepEqual((await calls(page, 'forum_open')).pop(), { kind: 'link', arg: 'https://play.openvanilla.app/wrath/i/frost' });
  assert.match(await posts.nth(1).textContent(), /removed by a moderator/);
  assert.match(await posts.nth(2).textContent(), /Orion#1001Team/);
  assert.match(await page.textContent('#fm-view .fm-crumb'), /Forum \/ Share your realm/);
  await page.click('#fm-view button:has-text("REPLY")');
  assert.deepEqual((await calls(page, 'forum_open')).pop(), { kind: 'reply', arg: '1' });
  await page.click('#fm-view button:has-text("ON THE WEBSITE")');
  assert.deepEqual((await calls(page, 'forum_open')).pop(), { kind: 'thread', arg: '1' });
  // a locked thread: no Reply
  await page.evaluate(() => window.LeylineForum.openThread(2));
  await page.waitForFunction(() => /Locked one/.test(document.getElementById('fm-view').textContent));
  assert.ok(await page.isDisabled('#fm-view button:has-text("LOCKED")'));
  assert.deepEqual(errors, []);
  await page.close();
});

test('search: thread titles', async () => {
  const { page, errors } = await open({ page: 'forum' });
  await page.waitForSelector('#fm-view .fm-cats');
  await page.fill('#fm-q', 'x');
  await page.press('#fm-q', 'Enter');
  assert.match(await page.textContent('#fm-status'), /two letters/);
  await page.fill('#fm-q', 'frost');
  await page.press('#fm-q', 'Enter');
  await page.waitForFunction(() => /Titles with “frost”/.test(document.getElementById('fm-view').textContent));
  assert.deepEqual((await calls(page, 'forum_call')).pop(), { action: 'search', args: { q: 'frost' } });
  assert.equal(await page.locator('#fm-view .fm-row').count(), 1);
  assert.deepEqual(errors, []);
  await page.close();
});

for (const old of ['friends', 'community', 'hub']) {
  test(`the old page id "${old}" opens the Forum`, async () => {
    const { page, errors } = await open({ page: old });
    await page.waitForSelector('#page-forum.on #fm-view .fm-cats');
    assert.deepEqual(errors, []);
    await page.close();
  });
}

test('the forum unreachable: the reason and Try again, nothing breaks', async () => {
  const { page, errors } = await open({ page: 'forum', down: true });
  await page.waitForFunction(() => /isn't answering/.test(document.getElementById('fm-view').textContent));
  assert.ok(await page.isVisible('#fm-view button:has-text("TRY AGAIN")'));
  assert.ok(await page.isVisible('#fm-discord'), 'the Discord is still one click away');
  const text = await page.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /world of warcraft|\bwow\b|warcraft|lich king|blizzard/i);
  assert.deepEqual(errors, []);
  await page.close();
});
