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
// >>> wu-interface (the dock's Interface choice, 2026-10-24) ---------------------------------------
// Forever UI is the default; the player's saved choice (localStorage 'wu:interface': 'forever' or
// 'classic', set by the dock's Interface menu in wrath-page.js) goes into the client's env before
// boot, the same switch as ?foreverui= (benilla-app webenv.rs: the env object outranks the query).
// An explicit ?foreverui= in the address still wins for that visit. Storage blocked: the default.
(function () {
  try {
    var KEY = 'wu:interface';
    var stored = null;
    try { stored = window.localStorage ? window.localStorage.getItem(KEY) : null; } catch (e) { stored = null; }
    var env = window.__wenilla_env;
    var choice = stored === 'classic' ? 'classic' : 'forever';
    var source = (stored === 'classic' || stored === 'forever') ? 'saved' : 'default';
    // No saved choice: the portal's own value stands (WU_FOREVERUI=0 in portal.env gives "0").
    if (source === 'default' && env && typeof env === 'object' && String(env.foreverui).trim() === '0') choice = 'classic';
    var q = /[?&]foreverui=([^&#]*)/.exec(location.search || '');
    if (q) {
      var v = '';
      try { v = decodeURIComponent(q[1]); } catch (e) { v = q[1]; }
      choice = v.trim() === '0' ? 'classic' : 'forever';
      source = 'url';
    }
    if (env && typeof env === 'object') env.foreverui = choice === 'classic' ? '0' : '1';
    window.__wuInterface = { choice: choice, source: source, key: KEY };
  } catch (e) { console.warn('wrath-early.js interface', e); }
})();
// <<< wu-interface ---------------------------------------------------------------------------------

(function () {
  'use strict';
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
