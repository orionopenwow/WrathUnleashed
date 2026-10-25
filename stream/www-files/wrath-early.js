// wrath-early.js — the WrathUnleashed page layer's first step: a classic script that www-patch.py puts
// right before the page's module script, so it runs before boot.js asks for its prefetch list. It
// does two things itself (the slim boot list, and linking wu-loading.css so boot.js's overlay is
// styled from its first frame) and then loads wrath-page.js, which does the rest.
//
// A classic script on purpose: if this file is missing or fails, the browser carries on with the
// page's module script exactly as before (a failed static import would stop the game from starting).
//
// Slim boot list: boot.js prefetches every name in /boot-manifest.json before the client starts.
// Music and long sounds are only played, never read before the login screen (and with the page's
// sign-in the login screen plays none: benilla-app startup_pace.rs, quiet login), so they are left
// out of that rush; the client fetches a sound itself when it plays it. ?slimboot=0 turns it off.
(function () {
  'use strict';
  // Missing-file and warning capture, from the first line of boot, for the smoke tests (the console
  // keeps only its most recent lines). window.__wuMissing: each game file the client asked for and the
  // slice does not have (Map name -> {t, what}); window.__wuWarn: the last 2000 warnings and errors;
  // window.__wuMissingDump() lists the missing names, sorted. Only string tests on lines the client
  // already prints, so it costs nothing in play.
  try {
    var missing = new Map();
    var warn = [];
    var notInChain = /file not in patch chain: ([^\s]+)/;
    var notFound = /Path not found: ([^\s]+)/;
    var bad = /WARN|ERROR|panicked|TIMED OUT/;
    var keep = function (args) {
      var s = args[0];
      if (typeof s !== 'string' || !bad.test(s)) return;
      var m = notInChain.exec(s) || notFound.exec(s);
      if (m) {
        var name = m[1].replace(/\//g, '\\').toLowerCase();
        if (!missing.has(name)) missing.set(name, { t: Math.round(performance.now()), what: s.replace(/%c/g, '').slice(0, 160) });
      }
      warn.push({ t: Math.round(performance.now()), s: s.replace(/%c/g, '').slice(0, 300) });
      if (warn.length > 2000) warn.splice(0, warn.length - 2000);
    };
    ['log', 'warn', 'error'].forEach(function (level) {
      var orig = console[level];
      if (typeof orig !== 'function') return;
      console[level] = function () { try { keep(arguments); } catch (e) { /* never in the way */ } return orig.apply(console, arguments); };
    });
    window.__wuMissing = missing;
    window.__wuWarn = warn;
    window.__wuMissingDump = function () { return Array.from(missing.keys()).sort(); };
  } catch (e) { /* the capture is optional */ }
  // One game per browser. Two tabs signed in to the same account knock each other off the realm
  // ("Disconnected", back to the login). The first tab holds a Web Lock for its whole life. A second tab
  // goes to tab.html?m=busy (a small note page: no game starts) with "Play here", which tells the first
  // tab to step aside (it goes to tab.html?m=moved) and comes back here once the lock is free.
  // ?multitab=1 skips the guard (tests).
  try {
    var here = location.pathname + location.search + location.hash;
    var noteUrl = function (m) { return './tab.html?m=' + m + '&r=' + encodeURIComponent(here); };
    var locks = navigator.locks && typeof navigator.locks.request === 'function' ? navigator.locks : null;
    if (locks && !/[?&]multitab=1\b/.test(location.search)) {
      var chan = typeof BroadcastChannel === 'function' ? new BroadcastChannel('wu-game') : null;
      locks.request('wu-game', { ifAvailable: true }, function (lock) {
        if (!lock) { window.__wuStopped = true; location.replace(noteUrl('busy')); return null; }
        if (chan) chan.onmessage = function (e) { if (e.data === 'take-over') location.replace(noteUrl('moved')); };
        return new Promise(function () { /* held until this tab closes or navigates */ });
      });
    }
  } catch (e) { console.warn('wrath-early.js tab guard', e); }
  // Keyboard Lock in fullscreen: Esc and browser shortcuts reach the game (hold Esc to leave fullscreen).
  try {
    document.addEventListener('fullscreenchange', function () {
      var kb = navigator.keyboard;
      if (!kb || typeof kb.lock !== 'function') return;
      if (document.fullscreenElement) kb.lock().catch(function () {});
      else if (typeof kb.unlock === 'function') kb.unlock();
    });
  } catch (e) { /* no Keyboard Lock */ }
})();
// "Your addons" (wu-addons.js): the addons a player dropped on this page, kept in this browser. The
// client asks the page's body store (globalThis.__wenilla_prefetch, benilla-formats web.rs) first
// for every /data read and for the name index /data/__index. This puts a layered store there before
// anything else makes one: it answers Interface\AddOns\<Name>\... from the player's files and adds
// their names to the index, so the client's own addon discovery finds them and runs them in its
// addon sandbox. The page never runs them. A folder the realm already serves wins over a local one
// of the same name. The client's start (the wasm download's response) waits for the files to be
// read from browser storage, at most 5 s. ?localaddons=0 turns it off for one visit.
(function () {
  'use strict';
  var g = typeof window !== 'undefined' ? window : globalThis;
  if (g.__wuStopped || g.__wuAddonLayer) return;
  try {
    if (/[?&]localaddons=0\b/.test((g.location && g.location.search) || '')) return;
    var PREFIX = 'interface\\addons\\';
    var key = function (name) { return String(name).replace(/\//g, '\\').toLowerCase(); };
    var addons = new Map();   // lower folder -> {name, files: Map(store key -> ArrayBuffer), names: [index names]}
    var shadowed = new Set();
    var merged = null;        // {base, out}: the last index merge
    var owner = function (k) {
      if (k.lastIndexOf(PREFIX, 0) !== 0) return null;
      var rest = k.slice(PREFIX.length), j = rest.indexOf('\\');
      return j <= 0 ? null : rest.slice(0, j);
    };
    var local = function (k) {
      if (typeof k !== 'string') return undefined;
      var o = owner(k);
      if (!o || shadowed.has(o)) return undefined;
      var a = addons.get(o);
      return a ? a.files.get(k) : undefined;
    };
    var merge = function (base) {
      if (!addons.size) return base;
      if (merged && merged.base === base) return merged.out;
      var names;
      try { names = JSON.parse(new TextDecoder().decode(base)); } catch (e) { return base; }
      if (!Array.isArray(names)) return base;
      var server = new Set();
      for (var i = 0; i < names.length; i++) { var o = owner(key(names[i])); if (o) server.add(o); }
      shadowed = new Set();
      var extra = [];
      addons.forEach(function (a, o) {
        if (server.has(o)) shadowed.add(o);
        else for (var n = 0; n < a.names.length; n++) extra.push(a.names[n]);
      });
      var out = extra.length ? new TextEncoder().encode(JSON.stringify(names.concat(extra))).buffer : base;
      merged = { base: base, out: out };
      return out;
    };
    class AddonLayerStore extends Map {
      get(k) {
        var v = local(k);
        if (v !== undefined) return v;
        v = super.get(k);
        return k === '__index' && v ? merge(v) : v;
      }
      has(k) { return local(k) !== undefined || super.has(k); }
      // web.rs drops a big body after one read: the player's files stay, for the next UI reload
      delete(k) { return local(k) !== undefined ? false : super.delete(k); }
    }
    var store = new AddonLayerStore(g.__wenilla_prefetch instanceof Map ? g.__wenilla_prefetch : []);
    g.__wenilla_prefetch = store;
    var ready = null;
    var layer = g.__wuAddonLayer = {
      /** list: [{name, files: [[path inside the addon folder, ArrayBuffer]]}] */
      set: function (list) {
        addons = new Map();
        shadowed = new Set();
        merged = null;
        (list || []).forEach(function (a) {
          var lower = String(a.name).toLowerCase();
          var files = new Map(), names = [];
          a.files.forEach(function (f) {
            var name = 'Interface\\AddOns\\' + a.name + '\\' + String(f[0]).replace(/\//g, '\\');
            files.set(key(name), f[1]);
            names.push(name);
          });
          addons.set(lower, { name: a.name, files: files, names: names });
        });
      },
      /** what the client sees: the folders loaded, and those the realm's own copy hides */
      info: function () {
        var on = [], hidden = [];
        addons.forEach(function (a, o) { (shadowed.has(o) ? hidden : on).push(a.name); });
        return { loaded: on, shadowed: hidden, merged: !!merged };
      },
      ready: function () { return ready; },
      store: store,
    };
    if (typeof g.fetch === 'function') {
      var origFetch = g.fetch;
      g.fetch = function (input) {
        var p = origFetch.apply(this, arguments);
        if (!ready) return p;
        var path = '';
        try {
          var url = typeof input === 'string' ? input : (input instanceof URL ? input.href : input && input.url);
          path = url ? new URL(url, g.location.href).pathname : '';
        } catch (e) { /* not a URL */ }
        if (!/\/wenilla_bg\.wasm$/.test(path)) return p;
        var wait = new Promise(function (res) { setTimeout(res, 5000); });
        return Promise.race([ready.catch(function () {}), wait]).then(function () { return p; });
      };
    }
    ready = (g.__wuAddonsImport ? g.__wuAddonsImport() : import('./wu-addons.js'))
      .then(function (m) { return m.boot(layer); })
      .catch(function (e) { console.warn('wu-addons.js:', e); });
    g.__wuAddonsReady = ready;
  } catch (e) { console.warn('wrath-early.js your addons', e); }
})();
(function () {
  'use strict';
  if (window.__wuStopped) return;
  var SKIP_AT_BOOT = /\.(mp3|wav|ogg)$/i;
  try {
    if (!window.__wuSlimBoot && !/[?&]slimboot=0\b/.test(location.search) && typeof window.fetch === 'function') {
      window.__wuSlimBoot = true;
      var orig = window.fetch;
      window.fetch = function (input, init) {
        var p = orig.apply(this, arguments);
        var path = '';
        try {
          var url = typeof input === 'string' ? input : (input instanceof URL ? input.href : input && input.url);
          path = url ? new URL(url, location.href).pathname : '';
        } catch (e) { /* not a URL */ }
        if (path !== '/boot-manifest.json') return p;
        return p.then(function (r) {
          if (!r.ok) return r;
          return r.clone().json().then(function (j) {
            if (!j || !Array.isArray(j.names)) return r;
            var names = j.names.filter(function (n) { return !SKIP_AT_BOOT.test(n); });
            if (names.length === j.names.length) return r;
            var out = Object.assign({}, j, { names: names });
            return new Response(JSON.stringify(out), { status: r.status, statusText: r.statusText, headers: r.headers });
          }, function () { return r; });
        });
      };
    }
  } catch (e) { console.warn('wrath-early.js slim boot', e); }
  // The loading screens' look, before boot.js draws its overlay (wu-loading.css).
  try {
    if (!document.getElementById('wu-loading-css')) {
      var link = document.createElement('link');
      link.id = 'wu-loading-css';
      link.rel = 'stylesheet';
      link.href = './wu-loading.css';
      (document.head || document.documentElement).appendChild(link);
    }
  } catch (e) { console.warn('wrath-early.js loading style', e); }
  try {
    window.__wuPage = import('./wrath-page.js')
      .then(function (m) { return m.install(); })
      .catch(function (e) { console.warn('wrath-page.js:', e); });
  } catch (e) { console.warn('wrath-early.js', e); }
})();
// >>> leyline-hop (realm hopping, 2026-10-25) ------------------------------------------------------
// A Leyline hop session (the Leyline window's Join: /wrath?go=r:<realm id>, wrath_portal.py hop_env) gets an
// env with hop, hop_ws (wss://<relay>/ws/<realm id>) and no login. Before the client starts, this:
//   * points the client's connections at the relay's bridge: the client always dials {this page}/ws/<port>
//     (benilla-app net/ws.rs); /ws/3724 becomes <hop_ws>/auth and any other port (the realm's world port, which
//     its realm list names) <hop_ws>/world. Nothing else is touched.
//   * fills in that realm's own login, kept in this browser only (localStorage wu.leyline.login.<realm id>, put
//     there by the realm's join page through wrath-page.js), never the Wrath one and never sent to our servers.
// wrath-page.js shows "Back to Wrath" and, with no login kept yet, the realm's join page.
(function (root) {
  'use strict';
  var ID = /^[a-z2-7]{16}$/;
  var KEY = 'wu.leyline.login.';
  var USER = /^[A-Za-z0-9]{3,16}$/, PASS = /^[\x21-\x7e]{1,16}$/;

  /** hop_ws when it is the relay bridge for this very realm (wss:, or ws: on a plain-http dev page), else null. */
  function hopBase(env, protocol) {
    var b = env && typeof env.hop_ws === 'string' ? env.hop_ws : '';
    var m = /^(wss?):\/\/[A-Za-z0-9.-]+(?::\d{1,5})?\/ws\/([a-z2-7]{16})$/.exec(b);
    if (!m || m[2] !== env.hop || (m[1] === 'ws' && protocol !== 'http:')) return null;
    return b;
  }

  /** The client's {page}/ws/<port> on this page's own host -> the bridge; anything else unchanged. */
  function rewrite(url, base, pageHost) {
    var m = /^wss?:\/\/([^/?#]+)\/ws\/(\d{1,5})(?:[?#].*)?$/.exec(String(url));
    if (!m || m[1] !== pageHost) return url;
    return base + (m[2] === '3724' ? '/auth' : '/world');
  }

  function savedLogin(storage, id) {
    try {
      var v = JSON.parse(storage.getItem(KEY + id) || 'null');
      if (v && USER.test(v.user) && PASS.test(v.pass)) return { user: v.user.toUpperCase(), pass: v.pass };
    } catch (e) { /* storage blocked or junk */ }
    return null;
  }

  function saveLogin(storage, id, user, pass) {
    if (!ID.test(id) || !USER.test(user || '') || !PASS.test(pass || '')) return false;
    try { storage.setItem(KEY + id, JSON.stringify({ user: user.toUpperCase(), pass: pass })); return true; } catch (e) { return false; }
  }

  function forgetLogin(storage, id) { try { storage.removeItem(KEY + id); } catch (e) { /* blocked */ } }

  function apply(win) {
    var env = win.__wenilla_env;
    if (!env || typeof env !== 'object' || !ID.test(env.hop || '')) return null;
    var base = hopBase(env, win.location.protocol);
    if (!base) { console.warn('leyline hop: no usable relay address; staying put'); return null; }
    delete env.user; delete env.pass;   // only ever this realm's own login
    var login = null;
    try { login = savedLogin(win.localStorage, env.hop); } catch (e) { login = null; }
    if (login) { env.user = login.user; env.pass = login.pass; }
    var Orig = win.WebSocket;
    if (typeof Orig === 'function' && !Orig.__wuHop) {
      var host = win.location.host;
      var Hop = function WebSocket(url, protocols) {
        var to = rewrite(url, base, host);
        return protocols === undefined ? new Orig(to) : new Orig(to, protocols);
      };
      Hop.prototype = Orig.prototype;
      ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach(function (k) { Hop[k] = Orig[k]; });
      Hop.__wuHop = true;
      win.WebSocket = Hop;
    }
    return { id: env.hop, name: String(env.hop_name || ''), base: base, login: !!login };
  }

  var api = { KEY: KEY, hopBase: hopBase, rewrite: rewrite, savedLogin: savedLogin, saveLogin: saveLogin,
              forgetLogin: forgetLogin, apply: apply, state: null };
  root.__wuHop = api;
  try { if (root.location) api.state = apply(root); } catch (e) { console.warn('wrath-early.js leyline hop', e); }
})(typeof window !== 'undefined' ? window : globalThis);
// <<< leyline-hop -----------------------------------------------------------------------------------
