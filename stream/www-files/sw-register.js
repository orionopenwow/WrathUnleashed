// sw-register.js — turns the WrathUnleashed page's service worker (wrath-sw.js) on or off for this
// browser. A port of Open Vanilla's 1.12 ow/sw-register.js without its lite-texture setting (the
// streamed slice is exported with lite textures already; wenilla-host has no ?lite=1 switch).
// Imported by wrath-page.js; never load-bearing.
//
// Who decides, highest first:
//   ?nosw=1 / ?sw=1          this browser, remembered (localStorage "ow:sw" = off / on)
//   localStorage "ow:sw"     a previous ?sw= choice
//   /sw-config.json          {"sw": "on" | "off" | "opt-in"}: the operator's switch for everyone
//                            ("off" also makes running workers remove themselves)
//   default                  opt-in: nothing happens until ?sw=1
//
//   owsw.status()   -> what the worker holds (entries, MB used of quota)
//   owsw.clear()    -> delete the cached data (the worker stays)
//   owsw.off()      -> unregister and delete everything (same as ?nosw=1)

const BASE = new URL('./', import.meta.url);
const SW_URL = new URL('wrath-sw.js', BASE).href;
const LS = (k, v) => {
  try {
    if (v === undefined) return localStorage.getItem(k);
    if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v);
  } catch { /* storage blocked: defaults apply */ }
  return null;
};

async function off() {
  navigator.serviceWorker.controller?.postMessage({ type: 'disable' });
  const regs = await navigator.serviceWorker.getRegistrations();
  await Promise.all(regs.filter((r) => [r.active, r.installing, r.waiting].some((w) => w?.scriptURL === SW_URL)).map((r) => r.unregister()));
  for (const k of await caches.keys()) if (k.startsWith('wu-data-')) await caches.delete(k);
}

function post(msg) {
  const target = navigator.serviceWorker.controller;
  if (target) target.postMessage(msg);
  else navigator.serviceWorker.ready.then((r) => r.active?.postMessage(msg)).catch(() => {});
}

export async function installServiceWorker() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return { state: 'unsupported' };
  const q = new URLSearchParams(location.search);
  if (q.get('nosw') === '1') LS('ow:sw', 'off');
  else if (q.get('sw') === '1') LS('ow:sw', 'on');
  let mode = LS('ow:sw');
  if (!mode) {
    try {
      const r = await fetch(new URL('sw-config.json', BASE), { cache: 'no-store' });
      if (r.ok) mode = (await r.json()).sw || null;
    } catch { /* no file: opt-in */ }
  }
  mode ||= 'opt-in';
  const api = {
    mode,
    status: () => new Promise((resolve) => {
      const ch = (e) => { if (e.data?.type === 'status') { navigator.serviceWorker.removeEventListener('message', ch); resolve(e.data.status); } };
      navigator.serviceWorker.addEventListener('message', ch);
      post({ type: 'status' });
      setTimeout(() => resolve({ controlled: !!navigator.serviceWorker.controller, mode }), 3000);
    }),
    clear: () => post({ type: 'clear' }),
    off: () => { LS('ow:sw', 'off'); return off(); },
  };
  window.owsw = api;
  if (mode !== 'on') {
    if ((await navigator.serviceWorker.getRegistrations()).some((r) => r.active?.scriptURL === SW_URL)) await off();
    return { state: mode };
  }
  navigator.storage?.persist?.().catch(() => {});
  try {
    await navigator.serviceWorker.register(SW_URL, { scope: '/', updateViaCache: 'none' });
  } catch (e) {
    console.warn('sw-register: service worker not registered:', e?.message || e);
    return { state: 'failed', error: String(e?.message || e) };
  }
  return { state: 'on', controlled: !!navigator.serviceWorker.controller };
}
