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
