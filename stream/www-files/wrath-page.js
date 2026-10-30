// wrath-page.js — the WrathUnleashed (3.3.5a) browser page's page layer, loaded by wrath-early.js
// (which www-patch.py puts into the served index.html). A port of what applies to Wrath from Open
// Vanilla's 1.12 page layer (realm/www/openvanilla.js):
//
//   * Account dock: the page's links (full screen, the bell, "download sections", the FPS journal
//     button) fold into a small handle at the top centre, so nothing sits on the minimap. Click to
//     open; in the world with touch on it moves to the bottom edge (touch.js).
//   * Signing in: when the page hands the client its game login (/__env.js), a "Signing in"
//     cover hides the login screen from the first glue screen until the character list is up, so
//     the player never sees a login form they don't need. A failed sign-in uncovers it after a
//     few seconds (the client brings its own form back then: startup_pace.rs).
//   * Loading screens (wu-loading.css, wu-loading.js): the boot overlay in the 1.12 boot screen's
//     look (portal art, framed panel, blue bar, one word), and the same screen over the client's
//     world-loading screens; no numbers, counts or section names on screen.
//   * Loading: stage timings (stages.js) to the console and window.owdiag (the boot overlay's
//     percent, MB and file counts are hidden; stages.js and wu-loading.js keep them); fetch-ahead
//     in the world (ahead.js, needs the bridge); the service worker switch (sw-register.js,
//     opt-in: ?sw=1 or /sw-config.json); the slim boot list is wrath-early.js's.
//   * Busy realm: a small, dismissible note when the realm is down or has a queue
//     (play.openvanilla.app/wrath/status.json, wrath_portal.py).
//   * Corner logo on the glue screens: off until the owner gives an image (CONFIG.logoUrl).
//   * Touch controls (touch.js, touch-driver.js) on touch screens or with ?touch=1; the mouse
//     fixes (input.js) everywhere; a connected controller starts the bridge's gamepad mapper.
//   * window.owdiag (wu-diag.js): loaded on first use, or at once with ?diag=1.
//
// Not ported (1.12 only): the Workshop addons button and ?addon= links, Warfront ?mode=, the Duels
// ?friend= / ?watch= / ?room= links, the login queue's "While you wait" grid (Wrath's page has no
// #ovq queue window), the launcher line (no WrathUnleashed desktop launcher to point at), the
// lite-texture switch and first-visit lite textures (the streamed slice is exported lite already and
// wenilla-host has no ?lite=1), the memory store for sync reads (syncread.js: the 3.3.5a client has
// its own, globalThis.__wenilla_prefetch in benilla-formats web.rs), the WMO and warm-up
// prefetchers, "now playing", and the 1.12 boot screen's video loop (1.3 MB; the poster art is used).
//
// Never load-bearing: any failure here leaves the game exactly as it was.

const BASE = new URL('./', import.meta.url).href;

// The owner's choices. Empty = that part stays off.
export const CONFIG = {
  // TODO(owner): a WrathUnleashed logo image for the glue screens' top-left corner (a path under
  // the served www, e.g. 'wu-corner-logo.webp'; about 14% of the screen height). Empty: no logo.
  logoUrl: '',
  // TODO(owner): where the busy-realm note links to (e.g. a "play offline" or download page) and
  // the words on that link. Empty: the note says only what the realm's status is.
  busyLinkUrl: '',
  busyLinkText: '',
  // the loading screens' background (wu-loading.css): '' = the 1.12 boot screen's portal art
  // (art/wu-load-bg.webp), 'orion' = the Orion constellation art (art/wu-load-orion.webp).
  // ?loadart=orion on the page address tries it for one visit.
  loadingArt: '',
  // the realm's public status (wrath_portal.py GET /wrath/status.json, CORS *)
  statusUrl: 'https://play.openvanilla.app/wrath/status.json',
  // where a realm hop and "Back to Wrath" go (a hop session's env.home wins: wrath_portal.py hop_env)
  homeUrl: 'https://play.openvanilla.app',
};

const STYLE_ID = 'wu-page-style';
const status = { dock: false, signin: 'off', busy: null, logo: false, touch: null, sw: null, go: null };

function style() {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = `
    #ow-dock { position: fixed; top: 0; left: 50%; transform: translateX(-50%); z-index: 30;
      display: flex; flex-direction: column; align-items: center; font: 12px system-ui, sans-serif; }
    #ow-dock-handle { all: unset; cursor: pointer; padding: 1px 14px 3px; color: #e8d7a8;
      background: rgba(10,8,18,.55); border: 1px solid rgba(201,162,39,.35); border-top: 0;
      border-radius: 0 0 8px 8px; opacity: .45; transition: opacity .15s; line-height: 12px; font-size: 11px;
      letter-spacing: .08em; }
    #ow-dock-handle:hover, #ow-dock.open #ow-dock-handle, #ow-dock-handle:focus-visible { opacity: 1; }
    #ow-dock-panel { display: none; margin-top: 2px; padding: 6px 10px; gap: 2px 4px; flex-wrap: wrap;
      justify-content: center; align-items: center; max-width: min(520px, 92vw);
      background: rgba(10,8,18,.9); border: 1px solid rgba(201,162,39,.5); border-radius: 8px;
      box-shadow: 0 6px 24px rgba(0,0,0,.6); color: #bbb; }
    #ow-dock.open #ow-dock-panel { display: flex; }
    #ow-dock-panel #bar, #ow-dock-panel #fs, #ow-dock-panel #bell, #ow-dock-panel #dl,
    #ow-dock-panel #wenilla-journal-download {
      position: static !important; inset: auto !important; transform: none !important;
      background: none !important; border: 0 !important; border-radius: 0 !important;
      padding: 2px 4px !important; margin: 0 !important; display: inline-flex; flex-wrap: wrap;
      align-items: center; gap: 2px 6px; font: 12px system-ui, sans-serif !important; }
    #ow-dock-panel #dl[hidden] { display: none !important; }
    #ow-dock-panel a, #ow-dock-panel button { color: #e8e2d0 !important; padding: 3px 6px !important;
      margin: 0 !important; border-radius: 4px; cursor: pointer; }
    #ow-dock-panel a:hover, #ow-dock-panel button:hover { background: rgba(201,162,39,.18) !important; }

    /* "Signing in": over the client's login screen while it signs in with the page's login */
    #ow-signin { position: fixed; inset: 0; z-index: 25; display: grid; place-items: center;
      background: radial-gradient(120% 90% at 50% 45%, #14223a 0%, #070b14 60%, #020306 100%);
      transition: opacity .35s; color: #d8e6f5; font: 600 clamp(15px, 2.4vh, 22px) Georgia, serif; letter-spacing: .08em; }
    #ow-signin.off { opacity: 0; pointer-events: none; }
    #ow-signin .wu-spin { width: 34px; height: 34px; margin: 0 auto 14px; border-radius: 50%;
      border: 3px solid rgba(160,200,240,.18); border-top-color: #9cc8f0; animation: wu-spin 1s linear infinite; }
    @keyframes wu-spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { #ow-signin .wu-spin { animation: none; } }

    /* The corner logo on the glue screens, at the 4:3 glue area's top-left. */
    #ow-glue-logo { position: fixed; z-index: 5; pointer-events: none; user-select: none;
      top: 1.2vh; left: calc(max(0px, (100vw - 133.333vh) / 2) + 0.6vh); height: 14vh; width: auto;
      max-width: 40vw; object-fit: contain; filter: drop-shadow(0 2px 6px rgba(0,0,0,.6));
      opacity: 0; transition: opacity .35s ease; }
    #ow-glue-logo.on { opacity: 1; }
  `;
  document.head.append(s);
}

// -- Account dock ------------------------------------------------------------------------------

export function dock() {
  if (document.getElementById('ow-dock')) return null;
  // The Wrath page: #fs, #bell and #dl (index.html, www-patch.py); a realm-style page: one #bar.
  const found = ['bar', 'dl', 'bell', 'fs'].map((id) => document.getElementById(id)).filter(Boolean);
  const parts = found.filter((el) => !found.some((o) => o !== el && o.contains(el)));
  if (!parts.length) return null;
  const root = document.createElement('div');
  root.id = 'ow-dock';
  const handle = document.createElement('button');
  handle.id = 'ow-dock-handle';
  handle.type = 'button';
  handle.title = 'Full screen, notifications, downloads';
  handle.setAttribute('aria-expanded', 'false');
  handle.textContent = '☰ menu';
  const panel = document.createElement('div');
  panel.id = 'ow-dock-panel';
  // A real move, not a copy: every listener (full screen, bell, sections) stays attached.
  for (const p of parts) panel.append(p);
  try { panel.append(bugButton()); } catch (e) { console.warn('wrath-page.js bug button', e); }
  root.append(handle, panel);
  document.body.append(root);
  const set = (open) => {
    root.classList.toggle('open', open);
    handle.setAttribute('aria-expanded', String(open));
  };
  handle.addEventListener('click', (e) => { e.stopPropagation(); set(!root.classList.contains('open')); });
  // Clicking back into the game closes it, so it never steals the canvas for long.
  document.addEventListener('pointerdown', (e) => { if (!root.contains(e.target)) set(false); }, true);
  panel.addEventListener('click', (e) => { if (e.target.closest('a,button') && e.target.id !== 'bell') setTimeout(() => set(false), 0); });
  // The client's "download FPS journal" button (perf/journal_web.rs) sits bottom-right, under the
  // touch cluster: into the dock as well when it appears.
  const takeJournal = () => {
    const j = document.getElementById('wenilla-journal-download');
    if (j && !panel.contains(j)) panel.append(j);
  };
  takeJournal();
  try {
    const mo = new MutationObserver(takeJournal);
    mo.observe(document.body, { childList: true });
  } catch { /* fine */ }
  status.dock = true;
  return root;
}

// -- Report a bug ------------------------------------------------------------------------------
// One queue for every bug: the menu's "Report a bug" sends the same `.bug <text>` a player types in
// game (ov_reports.lua stores it with the character and position in ov_bug_reports; the GM console's
// Bug Reports tab shows it). The page adds what the player can't easily say: the client build, the
// browser, memory, the map. Written before entering the world, it waits and goes once in the world.

let bridge = null;
const BUG_KEY = 'wu-bug-pending';
const BUG_MAX = 480;   // ov_reports.lua keeps 500

function bugContext() {
  const bits = [];
  try { bits.push('web ' + (document.querySelector('meta[name="wu-build"]')?.content || window.__wenilla_build || 'client')); } catch { /* fine */ }
  try {
    const ua = navigator.userAgentData?.brands?.find((b) => !/Not.?A.?Brand|Chromium/i.test(b.brand));
    bits.push(ua ? `${ua.brand} ${ua.version}` : (navigator.userAgent.match(/(Firefox|Edg|Chrome|Safari)\/[\d.]+/) || ['browser'])[0]);
  } catch { /* fine */ }
  try { bits.push(`${innerWidth}x${innerHeight}@${devicePixelRatio}`); } catch { /* fine */ }
  try { const m = window.__wenilla_mem?.(); if (m) bits.push(`wasm ${Math.round(m.wasmMB)}MB`); } catch { /* fine */ }
  try { const st = bridge?.state; if (st?.map?.id != null) bits.push('map ' + st.map.id); } catch { /* fine */ }
  return ' [' + bits.join(', ') + ']';
}

function inWorld() {
  try { return bridge?.state?.session?.state === 'inworld' && typeof bridge.chat === 'function'; } catch { return false; }
}

function sendBug(text) {
  const clean = String(text).replace(/[\r\n\t]+/g, ' ').replace(/\|/g, '/').trim();
  if (!clean) return 'empty';
  const line = (clean + bugContext()).slice(0, BUG_MAX);
  if (inWorld()) { bridge.chat('.bug ' + line); return 'sent'; }
  try { localStorage.setItem(BUG_KEY, line); } catch { return 'nowhere'; }
  const t = setInterval(() => {
    if (!inWorld()) return;
    clearInterval(t);
    let pending = null;
    try { pending = localStorage.getItem(BUG_KEY); localStorage.removeItem(BUG_KEY); } catch { /* fine */ }
    if (pending) bridge.chat('.bug ' + pending);
  }, 3000);
  return 'queued';
}

function bugButton() {
  const b = document.createElement('button');
  b.type = 'button';
  b.id = 'wu-bug';
  b.textContent = 'Report a bug';
  b.title = 'Tell us what went wrong: it goes to the same queue as .bug in game';
  b.addEventListener('click', () => {
    const box = document.createElement('div');
    box.id = 'wu-bug-box';
    box.setAttribute('role', 'dialog');
    box.style.cssText = 'position:fixed;inset:0;z-index:2147483600;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55)';
    box.innerHTML = '<div style="background:#0d111c;border:1px solid #6b5a2e;border-radius:10px;padding:18px 20px;width:min(440px,92vw);color:#e9e4d4;font:15px/1.45 Georgia,serif">'
      + '<div style="color:#f0d389;font-size:18px;margin-bottom:6px">Report a bug</div>'
      + '<div style="font-size:13px;opacity:.8;margin-bottom:8px">What happened, and what you expected. Your character, place and browser are added for you.</div>'
      + '<textarea maxlength="400" style="width:100%;height:96px;box-sizing:border-box;background:#070a12;color:#e9e4d4;border:1px solid #3a3320;border-radius:6px;padding:8px;font:14px system-ui"></textarea>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px">'
      + '<button data-x="cancel" type="button" style="padding:8px 14px;border-radius:6px;border:1px solid #3a3320;background:#151a28;color:#e9e4d4">Cancel</button>'
      + '<button data-x="send" type="button" style="padding:8px 16px;border-radius:6px;border:0;background:linear-gradient(#f0d389,#d8b25a);color:#1b1406;font-weight:600">Send</button></div>'
      + '<div data-x="note" style="font-size:13px;margin-top:8px;min-height:1em"></div></div>';
    document.body.append(box);
    const ta = box.querySelector('textarea');
    const note = box.querySelector('[data-x="note"]');
    const close = () => box.remove();
    ta.focus();
    // keys typed here are for the box, not the game
    box.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Escape') close(); }, true);
    box.addEventListener('keyup', (e) => e.stopPropagation(), true);
    box.querySelector('[data-x="cancel"]').addEventListener('click', close);
    box.addEventListener('click', (e) => { if (e.target === box) close(); });
    box.querySelector('[data-x="send"]').addEventListener('click', () => {
      const r = sendBug(ta.value);
      if (r === 'empty') { note.textContent = 'Write a few words first.'; return; }
      note.textContent = r === 'sent' ? 'Sent. Thank you: it is in the bug queue.'
        : r === 'queued' ? 'Saved: it goes in as soon as you are in the world.'
        : 'Could not save it here: in game, type .bug and what happened.';
      setTimeout(close, 1600);
    });
  });
  return b;
}

// -- Signing in --------------------------------------------------------------------------------

/** Whether the page signed the player in: /__env.js set an account and a password. Read only. */
export function pageSignedIn(env = window.__wenilla_env) {
  return !!(env && typeof env === 'object' && env.user && env.pass);
}

/** A Leyline guest pass (/wrath?demo=1, stream/demo.py): /__env.js names the character, so the
 *  client seats it without the character list (webenv "char"). Read only. */
export function guestPass(env = window.__wenilla_env) {
  return pageSignedIn(env) && env.demo === '1';
}

export function signingIn(wenilla) {
  if (!pageSignedIn()) return;
  const guest = guestPass();    // the cover stays up through the character list, into the inn
  const GIVE_UP_MS = guest ? 30000 : 12000;     // a failed sign-in: the client's own form comes back
  const NO_BRIDGE_MS = 5000;    // without bridge states: about a sign-in's length
  let cover = null, done = false, timer = 0;
  status.signin = 'waiting';
  function hide(why) {
    if (done) return;
    done = true;
    clearTimeout(timer);
    status.signin = 'done: ' + why;
    if (!cover) return;
    const c = cover;
    cover = null;
    c.classList.add('off');
    setTimeout(() => c.remove(), 400);
  }
  function show() {
    if (done || cover) return;
    cover = document.createElement('div');
    cover.id = 'ow-signin';
    cover.setAttribute('role', 'status');
    cover.innerHTML = '<div><div class="wu-spin" aria-hidden="true"></div>'
      + (guest ? 'Opening the Goldshire Inn…' : 'Signing in…') + '</div>';
    document.body.append(cover);
    status.signin = 'shown';
    timer = setTimeout(() => hide(wenilla?.ready ? 'gave up' : 'timer'), wenilla?.ready ? GIVE_UP_MS : NO_BRIDGE_MS);
  }
  // From the first glue screen (the boot overlay is over everything before it), until the
  // character list, the realm list or the world.
  addEventListener('ow:progress', (e) => {
    if (e.detail === 'ready') show();
    if (e.detail === 'enter' || e.detail === 'world') hide('world');
  });
  wenilla?.on?.('state', (s) => {
    const name = s?.state;
    if (name === 'login' && !done) show();
    if (guest && name === 'charselect') return;   // the client goes on into the world by itself
    if (name === 'charselect' || name === 'charcreate' || name === 'inworld' || /realm/i.test(name || '')) hide(name);
  });
}

// -- Corner logo -------------------------------------------------------------------------------

export function glueLogo(wenilla) {
  if (!CONFIG.logoUrl) return;
  const img = document.createElement('img');
  img.id = 'ow-glue-logo';
  img.alt = '';
  img.decoding = 'async';
  img.src = new URL(CONFIG.logoUrl, BASE).href;
  let glue = false;
  const GLUE = new Set(['login', 'charselect']);   // not charcreate: it sat on the faction panel (1.12)
  const sync = () => {
    if (!img.isConnected) document.body.append(img);
    img.classList.toggle('on', glue);
  };
  addEventListener('ow:progress', (e) => {
    if (e.detail === 'ready') { glue = true; sync(); }
    if (e.detail === 'enter' || e.detail === 'world') { glue = false; sync(); }
  });
  wenilla?.on?.('state', (s) => { glue = GLUE.has(s?.state); sync(); });
  status.logo = true;
}

// -- Diagnostics -------------------------------------------------------------------------------

function diag(wenilla) {
  let mod = null;
  const load = () => (mod ??= import(BASE + 'wu-diag.js').then((m) => m.createDiag(wenilla)));
  window.owdiag = new Proxy({}, {
    get: (_, name) => (name === 'then' ? undefined : (...args) => load().then((d) => (typeof d[name] === 'function' ? d[name](...args) : d[name]))),
  });
  load().then((d) => d.capture()).catch(() => {});
  if (new URLSearchParams(location.search).get('diag')) load().then((d) => d.autorun()).catch((e) => console.warn('owdiag:', e));
}

// -- Busy realm --------------------------------------------------------------------------------

/** What the status document says, for the note: { state: 'ok'|'full'|'down'|'unknown', why }. */
export function classifyStatus(doc, httpStatus = 200) {
  if (httpStatus >= 500) return { state: 'down', why: 'The realm is down right now.' };
  if (!doc || typeof doc !== 'object' || httpStatus >= 400) return { state: 'unknown' };
  if (doc.online === false) return { state: 'down', why: 'The realm is down right now.' };
  if (typeof doc.queue === 'number' && doc.queue > 0) return { state: 'full', why: `The realm is full: ${doc.queue} in the queue.` };
  return { state: 'ok' };
}

async function realmLoad() {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(CONFIG.statusUrl, { cache: 'no-store', mode: 'cors', credentials: 'omit', signal: ctl.signal });
    let d = null;
    try { d = await r.json(); } catch { /* not JSON */ }
    return classifyStatus(d, r.status);
  } catch {
    return { state: 'unknown' };   // the status page itself unreachable: say nothing
  } finally {
    clearTimeout(timer);
  }
}

// A share link's deep link (stream/links.py): /r/<realm>, /h/<hangout>, /q/<queue>, /b/<raid or wing>, /m/<mod>, /u/<character>
// send people on to the page with ?go=<kind>:<id>. This only reads and checks it (the same allow-lists
// as links.py) and leaves it on window.wuGo / the returned status for a later feature to act on; it
// never navigates or runs anything. Returns { kind, id } or null.
const GO_RULES = {
  r: /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/,
  h: /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/,
  q: /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/,
  b: /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/,
  m: /^(?=.{3,32}$)[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/,
  u: /^[A-Za-z]{2,12}$/,
};
export function goLink(search = location.search) {
  let v;
  try { v = new URLSearchParams(search).get('go'); } catch { return null; }
  if (!v || v.length > 40) return null;
  const i = v.indexOf(':');
  const kind = v.slice(0, i), id = v.slice(i + 1);
  if (i < 1 || !Object.hasOwn(GO_RULES, kind) || !GO_RULES[kind].test(id)) return null;
  return { kind, id };
}

function busyBanner() {
  try { if (sessionStorage.getItem('ow:busy-off')) return; } catch { /* storage off */ }
  let shown = null;
  const show = (why) => {
    if (shown) { shown.querySelector('span').textContent = why; return; }
    const css = document.createElement('style');
    css.textContent = `#ow-busy { position: fixed; left: 10px; bottom: 10px; z-index: 31; display: flex; gap: 8px;
      align-items: center; max-width: min(460px, calc(100vw - 20px)); padding: 5px 6px 5px 10px; border-radius: 8px;
      background: rgba(10,8,18,.9); border: 1px solid rgba(201,162,39,.55); color: #e8e2d0;
      font: 12px system-ui, sans-serif; box-shadow: 0 4px 16px rgba(0,0,0,.5); }
      #ow-busy a { color: #f3d179; font-weight: 600; white-space: nowrap; text-decoration: none; }
      #ow-busy a:hover { text-decoration: underline; }
      #ow-busy button { all: unset; cursor: pointer; color: #9a917f; padding: 0 4px; font-size: 14px; line-height: 1; }
      #ow-busy button:hover, #ow-busy button:focus-visible { color: #fff; }`;
    document.head.append(css);
    shown = document.createElement('div');
    shown.id = 'ow-busy';
    shown.setAttribute('role', 'status');
    const text = document.createElement('span');
    text.textContent = why;
    shown.append(text);
    if (CONFIG.busyLinkUrl && CONFIG.busyLinkText) {
      const link = document.createElement('a');
      link.href = CONFIG.busyLinkUrl;
      link.target = '_blank';   // a new tab: a place in the login queue here is kept
      link.rel = 'noopener';
      link.textContent = CONFIG.busyLinkText;
      shown.append(link);
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '×';
    close.setAttribute('aria-label', 'Dismiss');
    close.addEventListener('click', () => {
      shown.remove();
      try { sessionStorage.setItem('ow:busy-off', '1'); } catch { /* storage off */ }
    });
    shown.append(close);
    document.body.append(shown);
  };
  const look = async () => {
    if (document.visibilityState === 'hidden' || !document.body) return;
    const r = await realmLoad();
    status.busy = r.state;
    if (r.state === 'down' || r.state === 'full') show(r.why);
    else if (r.state === 'ok' && shown) { shown.remove(); shown = null; }
  };
  // three looks per page load at most (the portal asks the world server at most once per TTL)
  for (const at of [3000, 90000, 240000]) setTimeout(() => { look().catch(() => {}); }, at);
}

// -- Loading, input, touch -----------------------------------------------------------------------

function loading(wenilla) {
  import(BASE + 'ahead.js').then((m) => m.installAhead(wenilla)).catch((e) => console.warn('ahead.js:', e));
  import(BASE + 'sw-register.js').then((m) => m.installServiceWorker()).then((r) => { status.sw = r?.state || null; })
    .catch((e) => console.warn('sw-register.js:', e));
}

export function touchMaybe() {
  try {
    const q = new URLSearchParams(location.search).get('touch');
    if (q === '0' || q === 'off') return false;
    if (q !== null) return true;
    if (localStorage.getItem('ow:touch')) return localStorage.getItem('ow:touch') !== 'off' || (navigator.maxTouchPoints || 0) > 0;
  } catch { /* storage blocked */ }
  return (navigator.maxTouchPoints || 0) > 0;
}

// >>> fui-glue (WrathUnleashed glue layout, 2026-10-24) ------------------------------------------
// On the glue screens the account dock leaves the top centre, where Forever UI's REALMS | MENU bar
// sits, for the top-left corner (empty since the expansion logo is gone). From the first glue
// screen ('ready') until the world ('enter' / 'world'). A logout back to character select sends no
// stage, so the dock stays at the top centre then (the bar is still usable under its 17 px handle).
(() => {
  try {
    const css = document.createElement('style');
    css.id = 'wu-glue-dock';
    css.textContent = `html.ow-glue #ow-dock { left: 6px; top: 4px; transform: none; align-items: flex-start; }
      html.ow-glue #ow-dock-handle { border-top: 1px solid rgba(201,162,39,.35); border-radius: 8px; }`;
    (document.head || document.documentElement).append(css);
    addEventListener('ow:progress', (e) => {
      if (e.detail === 'ready') document.documentElement.classList.add('ow-glue');
      if (e.detail === 'enter' || e.detail === 'world') document.documentElement.classList.remove('ow-glue');
    });
  } catch { /* never load-bearing */ }
})();
// <<< fui-glue ------------------------------------------------------------------------------------

// >>> wu-interface (the dock's Interface choice, 2026-10-24) ---------------------------------------
// An "Interface" menu in the account dock: Forever UI (the default) or Classic 3.3.5. The choice is
// kept in localStorage ('wu:interface') and applied before boot by wrath-early.js, which sets
// window.__wenilla_env.foreverui (the ?foreverui= switch). Changing it asks once, then reloads,
// dropping any ?foreverui= from the address so the saved choice is the one used.
export const INTERFACE_KEY = 'wu:interface';
export const INTERFACES = [
  { id: 'forever', label: 'Forever UI (default)' },
  { id: 'classic', label: 'Classic 3.3.5' },
];

/** The address to reload: the current one without its foreverui parameter. */
export function interfaceReloadUrl(href) {
  const u = new URL(href);
  u.searchParams.delete('foreverui');
  return u.href;
}

/** Save the choice; false when storage is blocked (the reload would then change nothing). */
export function saveInterface(choice, storage = globalThis.localStorage) {
  try {
    storage.setItem(INTERFACE_KEY, choice === 'classic' ? 'classic' : 'forever');
    return storage.getItem(INTERFACE_KEY) === (choice === 'classic' ? 'classic' : 'forever');
  } catch {
    return false;
  }
}

export function interfaceMenu(panel, current = window.__wuInterface?.choice || 'forever') {
  if (!panel || panel.querySelector('#ow-interface')) return null;
  const row = document.createElement('label');
  row.id = 'ow-interface-row';
  row.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:2px 4px;color:#e8e2d0;font:12px system-ui,sans-serif';
  row.textContent = 'Interface';
  const sel = document.createElement('select');
  sel.id = 'ow-interface';
  sel.style.cssText = 'font:12px system-ui,sans-serif;background:#1a1626;color:#e8e2d0;border:1px solid rgba(201,162,39,.5);border-radius:4px;padding:1px 4px';
  for (const o of INTERFACES) {
    const opt = document.createElement('option');
    opt.value = o.id;
    opt.textContent = o.label;
    sel.append(opt);
  }
  sel.value = current === 'classic' ? 'classic' : 'forever';
  sel.addEventListener('change', () => {
    const want = sel.value;
    const label = INTERFACES.find((o) => o.id === want)?.label || want;
    if (!window.confirm(`Switch the interface to ${label}? The page will reload.`)) {
      sel.value = current;
      return;
    }
    if (!saveInterface(want)) {
      // storage blocked: this visit only, through the address
      const u = new URL(location.href);
      u.searchParams.set('foreverui', want === 'classic' ? '0' : '1');
      location.replace(u.href);
      return;
    }
    location.replace(interfaceReloadUrl(location.href));
  });
  row.append(sel);
  panel.append(row);
  return sel;
}

(() => {
  try {
    if (typeof document === 'undefined') return;
    let tries = 0;
    const look = () => {
      const panel = document.getElementById('ow-dock-panel');
      if (panel) { interfaceMenu(panel); return; }
      if (++tries < 120) setTimeout(look, 250);   // the dock is built at install: 30 s at most
    };
    look();
  } catch (e) { console.warn('wrath-page.js interface menu', e); }
})();
// <<< wu-interface ---------------------------------------------------------------------------------

// >>> leyline-hop (realm hopping, 2026-10-25) ------------------------------------------------------
// The Leyline window's Join (WrathUnleashedUI/Leyline.lua) can't navigate, so it asks the page: it sets the
// Lua global WUUI_LEYLINE_HOP to the realm id (or "wrath") and whispers WULY "H:<id>" to itself. The page
// takes the global through the bridge (and clears it) on a 1 s poll whenever the bridge is up, then reloads the
// game on that realm: <home>/wrath?go=r:<id> (with own game files: /wrath/play?mode=own&go=r:<id>). The poll is
// the trigger: the 3.3.5a web client hands CHAT_MSG_ADDON to the addons but not to the page bridge's event tap
// (benilla-ui addon_message.rs fires it past the tap), so the whisper's echo never reaches the page today; the
// CHAT_MSG_ADDON listener stays as a shortcut for a client that relays it. The global is the authority: a whisper
// from someone else can't make the page hop. "Back to Wrath" lands in Dalaran (?go=h:dalaran, ov_go.lua).
// In a hop session (wrath-early.js set it up): a "Back to Wrath" bar, and the realm's join page over the game
// when this browser has no login for that realm yet; the login it hands back is kept here (wrath-early.js).
// With Hero Key sign-in (hop.state.ssoPending, docs/HERO-KEY-SSO.md) the join page only shows when the realm
// refused it; "Use another account" turns Hero Key sign-in off for that realm in this browser, and the join page
// then offers "Sign in with your Hero Key" to turn it back on.
export const HOP_TAKE = 'local h = WUUI_LEYLINE_HOP; WUUI_LEYLINE_HOP = nil; return h';
const HOP_ID = /^[a-z2-7]{16}$/;

/** "wrath" or a realm id, else null. */
export function hopTarget(v) {
  return v === 'wrath' || (typeof v === 'string' && HOP_ID.test(v)) ? v : null;
}

/** Where a hop (or "Back to Wrath") goes. */
export function hopUrl(target, env = window.__wenilla_env || {}) {
  const t = hopTarget(target);
  if (!t) return null;
  const home = typeof env.home === 'string' && /^https:\/\/[a-z0-9.-]+$/i.test(env.home) ? env.home : CONFIG.homeUrl;
  const own = env.mode === 'own';
  if (t === 'wrath') return home + (own ? '/wrath/play?mode=own&go=h:dalaran' : '/wrath?go=h:dalaran');
  return home + (own ? `/wrath/play?mode=own&go=r:${t}` : `/wrath?go=r:${t}`);
}

/** CHAT_MSG_ADDON args ([prefix, msg, channel, sender] or {args}) that ask for a hop: the target, else null. */
export function hopEcho(payload) {
  const a = Array.isArray(payload) ? payload : (payload && Array.isArray(payload.args) ? payload.args : []);
  if (a[0] !== 'WULY' || a[2] !== 'WHISPER' || typeof a[1] !== 'string') return null;
  const m = /^H:([a-z2-7]{16}|wrath)$/.exec(a[1]);
  return m ? m[1] : null;
}

/** Watch for the Leyline window's Join. `go(url)` navigates (tests pass their own). Returns a small handle. */
export function watchHops(wenilla, { env = window.__wenilla_env || {}, go = (u) => location.assign(u), pollMs = 1000 } = {}) {
  const h = { taking: false, gone: null, take: null, timer: 0, polls: 0, taken: null, error: null };
  if (!wenilla || typeof wenilla.lua !== 'function') return h;
  h.take = async () => {
    if (h.taking || h.gone) return null;
    h.taking = true;
    h.polls++;
    try {
      let v = null;
      try { [v] = (await wenilla.lua(HOP_TAKE, 1500)) || []; h.error = null; } catch (e) { h.error = String(e?.message || e).slice(0, 120); }
      const t = hopTarget(v);
      if (t) h.taken = t;
      if (!t || (t === 'wrath' && !env.hop)) return null;   // already home
      if (t === env.hop) return null;                       // already there
      h.gone = hopUrl(t, env);
      go(h.gone);
      return h.gone;
    } finally {
      h.taking = false;
    }
  };
  try { wenilla.on?.('CHAT_MSG_ADDON', (p) => { if (hopEcho(p)) h.take(); }); } catch { /* old bridge */ }
  // Whenever the bridge has a VM (the Leyline window lives in the world, but a glue-screen menu may set it too).
  const vmUp = () => { try { return !!wenilla.ready && !!wenilla.state; } catch { return false; } };
  if (pollMs > 0) h.timer = setInterval(() => { if (vmUp()) h.take().catch(() => {}); }, pollMs);
  try { if (window.__wuHop) window.__wuHop.watch = h; } catch { /* no hop layer */ }
  return h;
}

/** A login handed back by the realm's join page (framed below), checked: {user, pass} or null. */
export function hopLoginMessage(ev, env = window.__wenilla_env || {}) {
  let origin = '';
  try { origin = new URL(env.hop_join).origin; } catch { return null; }
  const d = ev && ev.data;
  if (!ev || ev.origin !== origin || !d || d.type !== 'leyline-login' || d.realm !== env.hop) return null;
  if (!/^[A-Za-z0-9]{3,16}$/.test(d.user || '') || !/^[\x21-\x7e]{1,16}$/.test(d.pass || '')) return null;
  return { user: d.user, pass: d.pass };
}

const HOP_CSS = `
  #wu-hop-bar { position: fixed; left: 50%; bottom: 8px; transform: translateX(-50%); z-index: 32; display: flex;
    gap: 6px; align-items: center; padding: 4px 6px 4px 12px; border-radius: 8px; font: 12px system-ui, sans-serif;
    background: linear-gradient(#101a2c, #070b14); border: 1px solid rgba(201,162,39,.6); color: #d8e6f5;
    box-shadow: 0 4px 16px rgba(0,0,0,.6); }
  #wu-hop-bar b { color: #f0d389; font: 600 13px Georgia, serif; letter-spacing: .04em; }
  #wu-hop-bar button, #wu-hop-join button { cursor: pointer; border-radius: 6px; padding: 4px 10px; font: 12px system-ui, sans-serif;
    border: 1px solid rgba(201,162,39,.6); background: #151a28; color: #e9e4d4; }
  #wu-hop-bar button.home, #wu-hop-join button.home { border: 0; background: linear-gradient(#f0d389, #d8b25a); color: #1b1406; font-weight: 600; }
  #wu-hop-join { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center;
    background: radial-gradient(120% 90% at 50% 45%, rgba(20,34,58,.92) 0%, rgba(2,3,6,.96) 100%); }
  #wu-hop-join .panel { width: min(640px, 94vw); height: min(720px, 90vh); display: flex; flex-direction: column;
    border: 1px solid rgba(201,162,39,.6); border-radius: 10px; background: #0d111c; overflow: hidden; }
  #wu-hop-join .head { display: flex; gap: 8px; align-items: center; padding: 8px 10px; color: #f0d389;
    font: 600 15px Georgia, serif; border-bottom: 1px solid rgba(201,162,39,.35); }
  #wu-hop-join .head span { flex: 1; }
  #wu-hop-join iframe { flex: 1; border: 0; width: 100%; background: #15171a; }
`;

/** The Leyline brand switch (wrath_portal.py LEYLINE_BRAND=1 puts brand and home_name in the env): what the page
 * calls the main realm. Off (no env.brand): exactly the old words. Also kept in localStorage ("wu-brand") so the
 * one-tab note page (tab.html, which has no env) names it the same way. */
export function brand(env = window.__wenilla_env || {}, store = globalThis.localStorage) {
  const on = env.brand === 'leyline';
  const home = on ? (String(env.home_name || '').replace(/[\u0000-\u001f<>]/g, '').slice(0, 32) || 'Dalaran Hangout') : 'Wrath';
  try { if (on) store?.setItem('wu-brand', home); else store?.removeItem('wu-brand'); } catch { /* storage off */ }
  return { on, home, back: 'Back to ' + home };
}

/** In a hop session: the "Back to Wrath" bar, and the join page when no login is kept for this realm. */
export function hopUi(env = window.__wenilla_env || {}, hop = window.__wuHop) {
  if (!hop?.state || !env.hop || document.getElementById('wu-hop-bar')) return null;
  const css = document.createElement('style');
  css.textContent = HOP_CSS;
  document.head.append(css);
  const name = String(env.hop_name || 'a community realm').slice(0, 32);
  const words = brand(env);
  const home = () => location.assign(hopUrl('wrath', env));
  const hangout = !!hop.state.home;   // the Dalaran Hangout: Wrath itself, the player's own login
  const bar = document.createElement('div');
  bar.id = 'wu-hop-bar';
  const label = document.createElement('span');
  label.append('On ');
  const b = document.createElement('b');
  b.textContent = name;
  label.append(b, ' · Leyline');
  const back = document.createElement('button');
  back.className = 'home';
  back.type = 'button';
  back.textContent = words.back;
  back.addEventListener('click', home);
  const other = document.createElement('button');
  other.type = 'button';
  other.textContent = 'Use another account';
  other.title = 'Forget the login this browser keeps for ' + name;
  other.addEventListener('click', () => {
    hop.forgetLogin(localStorage, env.hop);
    if (hop.state.sso) hop.setSso?.(localStorage, env.hop, false);   // and no Hero Key sign-in here, until asked again
    location.reload();
  });
  bar.append(label, back);
  if (!hangout) bar.append(other);   // the hangout uses the Wrath login: nothing to forget
  document.body.append(bar);
  if (hop.state.login) {
    // Hero Key sign-in in flight: the join page only if the realm refuses it and no login is kept here
    if (hop.state.ssoPending) hop.state.ssoPending.then((ok) => { if (!ok && !hop.state.login) joinPage(); });
    return { bar };
  }
  return { bar, join: joinPage() };

  function joinPage() {
  if (document.getElementById('wu-hop-join')) return null;
  // First hop here: the realm's own join page (make an account, or sign in to yours), framed.
  const join = document.createElement('div');
  join.id = 'wu-hop-join';
  join.setAttribute('role', 'dialog');
  join.innerHTML = '<div class="panel"><div class="head"><span></span>'
    + '<button type="button" data-x="later">Type my login in the game</button>'
    + '<button type="button" class="home" data-x="home"></button></div></div>';
  join.querySelector('.head span').textContent = 'Join ' + name;
  join.querySelector('[data-x="home"]').textContent = words.back;
  if (hop.state.ssoOffer) {   // Hero Key sign-in was declined here with "Use another account": offer it back
    const hk = document.createElement('button');
    hk.type = 'button';
    hk.dataset.x = 'herokey';
    hk.textContent = 'Sign in with your Hero Key';
    hk.addEventListener('click', () => { hop.setSso?.(localStorage, env.hop, true); location.reload(); });
    join.querySelector('[data-x="later"]').before(hk);
  }
  const frame = document.createElement('iframe');
  frame.title = 'Join ' + name;
  frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin');
  frame.src = env.hop_join + '&from=' + encodeURIComponent(location.origin);
  join.querySelector('.panel').append(frame);
  join.querySelector('[data-x="home"]').addEventListener('click', home);
  join.querySelector('[data-x="later"]').addEventListener('click', () => join.remove());
  // keys typed in the join page are not for the game
  join.addEventListener('keydown', (e) => e.stopPropagation(), true);
  join.addEventListener('keyup', (e) => e.stopPropagation(), true);
  addEventListener('message', (ev) => {
    if (ev.source !== frame.contentWindow) return;
    const got = hopLoginMessage(ev, env);
    if (got && hop.saveLogin(localStorage, env.hop, got.user, got.pass)) location.reload();
  });
  document.body.append(join);
  return join;
  }
}
// <<< leyline-hop -----------------------------------------------------------------------------------

// >>> game-folder (the layer, 2026-10-25) ------------------------------------------------------------
// The player's own 3.3.5a game folder as a layer over the streamed slice (ownfiles.js). The game sees it
// through one Lua global the page sets on a 1 s poll while the bridge has a VM (a /reload wipes globals,
// so it is set again each time), and asks for the picker the way the Leyline window asks for a hop: the
// WrathUnleashedUI addon (GameFolder.lua) sets WUUI_GAMEFOLDER_ASK = "pick", which the poll takes and
// clears (CHAT_MSG_ADDON does not reach the page). The account dock gets a "Game folder" button too.
//   WUUI_GAMEFOLDER = { page = true, on = <folder in use>, build = <n>, label = "<folder name>",
//                       ownOnly = <names only the folder has>, realm = "lifted"|"held"|"unknown"|"failed",
//                       keeps = <the browser remembers folders>, allowed = <this page offers it> }
export const FOLDER_TAKE = 'local a = WUUI_GAMEFOLDER_ASK; WUUI_GAMEFOLDER_ASK = nil; return a';

const luaStr = (v) => '"' + String(v).replace(/[^A-Za-z0-9 _.()'-]/g, '?').slice(0, 40) + '"';
const luaNum = (v) => (Number.isFinite(v) ? String(Math.trunc(v)) : 'nil');

/** The Lua chunk that publishes the layer's state to the game and takes a pending ask. */
export function gameFolderLua(st, allowed) {
  const s = st || {};
  const realm = ['lifted', 'held', 'unknown', 'failed'].includes(s.realm) ? s.realm : 'unknown';
  return 'WUUI_GAMEFOLDER = { page = true, on = ' + (s.mounted ? 'true' : 'false')
    + ', build = ' + luaNum(s.build) + ', label = ' + (s.label ? luaStr(s.label) : 'nil')
    + ', ownOnly = ' + luaNum(s.counts && s.counts.ownOnly) + ', realm = ' + luaStr(realm)
    + ', keeps = ' + (s.keepsFolders ? 'true' : 'false') + ', allowed = ' + (allowed ? 'true' : 'false') + ' }; '
    + FOLDER_TAKE;
}

/** The poll: state in, "pick" out. `own` defaults to window.__wuOwnFiles. Returns a small handle. */
export function watchGameFolder(wenilla, { own = () => window.__wuOwnFiles, pollMs = 1000 } = {}) {
  const h = { polls: 0, asks: 0, error: null, timer: 0, busy: false, tick: null };
  if (!wenilla || typeof wenilla.lua !== 'function') return h;
  h.tick = async () => {
    const o = own();
    if (h.busy || !o) return null;
    h.busy = true;
    h.polls++;
    try {
      let v = null;
      try { [v] = (await wenilla.lua(gameFolderLua(o.status(), o.allowed ? o.allowed() : false), 1500)) || []; h.error = null; }
      catch (e) { h.error = String(e?.message || e).slice(0, 120); }
      if (v === 'pick') { h.asks++; o.pick().catch?.(() => {}); }
      return v;
    } finally {
      h.busy = false;
    }
  };
  const vmUp = () => { try { return !!wenilla.ready && !!wenilla.state; } catch { return false; } };
  if (pollMs > 0) h.timer = setInterval(() => { if (vmUp()) h.tick().catch(() => {}); }, pollMs);
  return h;
}

/** The dock's "Game folder" button: picks the folder, or says what is in use. */
export function folderButton(panel, own = () => window.__wuOwnFiles) {
  if (!panel || panel.querySelector('#wu-folder')) return null;
  const b = document.createElement('button');
  b.type = 'button';
  b.id = 'wu-folder';
  const label = () => {
    const st = own()?.status?.();
    b.textContent = st?.mounted ? 'Game folder: on' : 'Use my game folder';
    b.title = st?.mounted ? `The whole world, from your game folder “${st.label}”. Nothing is uploaded.`
      : 'Open the whole world with your own 3.3.5a game folder. Nothing is uploaded.';
  };
  label();
  setInterval(label, 3000);
  b.addEventListener('click', () => { own()?.pick?.()?.then?.(label, label); });
  panel.append(b);
  return b;
}

(() => {
  try {
    if (typeof document === 'undefined') return;
    let tries = 0;
    const look = () => {
      const panel = document.getElementById('ow-dock-panel');
      const o = window.__wuOwnFiles;
      if (panel && o) { if (o.allowed()) folderButton(panel); return; }
      if (++tries < 120) setTimeout(look, 250);
    };
    look();
  } catch (e) { console.warn('wrath-page.js game folder button', e); }
})();
// <<< game-folder ----------------------------------------------------------------------------------

let installed = null;

/** The page layer, once. `wenilla` defaults to bridge.js's (the same module the page imports). */
export async function install(wenilla) {
  if (installed) return installed;
  installed = status;
  window.wuPage = { status, CONFIG, sendBug: (t) => sendBug(t) };
  if (!wenilla) {
    try { wenilla = (await import(BASE + 'bridge.js')).wenilla || window.wenilla; } catch (e) { console.warn('wrath-page.js: bridge.js', e); }
  }
  bridge = wenilla || null;
  // Stage timings first, so the earliest stages are seen.
  import(BASE + 'stages.js').then((m) => m.installStages(wenilla)).catch((e) => console.warn('stages.js:', e));
  import(BASE + 'input.js').then((m) => m.installInput()).catch((e) => console.warn('input.js:', e));
  const step = (name, fn) => { try { fn(); } catch (e) { console.warn('wrath-page.js ' + name, e); } };
  step('style', style);
  step('brand', () => { status.brand = brand().on; });
  // the loading screens (wu-loading.css is linked by wrath-early.js; this adds the world cover)
  import(BASE + 'wu-loading.js').then((m) => m.installLoading({ art: CONFIG.loadingArt })).catch((e) => console.warn('wu-loading.js:', e));
  // the page's buttons may not be parsed yet when this runs very early
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => step('dock', dock), { once: true });
  else step('dock', dock);
  step('signing in', () => signingIn(wenilla));
  step('glue logo', () => glueLogo(wenilla));
  step('diag', () => diag(wenilla));
  step('loading', () => loading(wenilla));
  step('busy banner', busyBanner);
  step('go link', () => { status.go = goLink(); if (status.go) window.wuGo = status.go; });
  step('leyline hop', () => { status.hop = watchHops(wenilla); });
  step('game folder', () => { if (!window.__wenilla_env?.hop) status.folder = watchGameFolder(wenilla); });
  const ui = () => step('leyline hop page', () => { hopUi(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ui, { once: true });
  else ui();
  // Touch controls only where they can be used (a touch screen, ?touch=, a saved choice); elsewhere
  // a connected controller still starts the bridge's gamepad mapper, which touch.js otherwise does.
  if (touchMaybe()) {
    import(BASE + 'touch.js').then((m) => { status.touch = m.installTouch(wenilla); }).catch((e) => console.warn('touch.js:', e));
  } else {
    addEventListener('gamepadconnected', () => { try { wenilla?.gamepad?.start?.(); } catch { /* mapper missing */ } });
  }
  return status;
}
