// stages.js — when each step of a visit happened on the WrathUnleashed page, and whether the first
// 30 s in the world stuttered. Ported from Open Vanilla's 1.12 page layer (realm/www/stages.js);
// installed first by wrath-page.js, read by window.owdiag (wu-diag.js).
//
// The 3.3.5a client's progress stages (window.__wenilla_progress(stage), benilla-app webprogress.rs
// and startup_pace.rs; an older client build sends only the first two):
//   'startup'       the first update's Startup pile is done
//   'ready'         the first glue screen is up (login or the character list), once per page load
//   'enter'         the world session started: the loading screen is up
//   'world'         the first world frame the loading screen no longer covers
//   'reconnecting', 'reconnect:<s>', 'focus:<adt>'   (not marks: passed on as events only)
//
// Marks (ms since navigation; performance marks "ow:stage:<name>"):
//   engine-start   'startup'
//   engine         'ready'
//   login          the login screen (bridge state)
//   charlist       the character list (bridge state 'charselect')
//   world-enter    'enter', or the bridge state turning 'inworld' (older client)
//   world-ready    'world'
//   first-frame    the first animation frame after world-ready (after world-enter, older client)
//   first-move     the first snapshot after world-ready with the player moving (bridge)
//
// Every stage is also sent as a window 'ow:progress' event, with the 1.12 names touch.js and the
// page layer listen for added: 'world-loading' with 'enter', and 'world-ready' with 'world'. Nothing is shown on screen: the marks, the boot overlay's texts and
// the frame-gap summary go to the console and window.owStages.

const HITCH_MS = 100;
const WATCH_MS = 30000;
const TAG = '[WrathUnleashed]';

/** The marks and 1.12-style events a client stage stands for. */
export function stageMap(stage) {
  switch (stage) {
    case 'startup': return { mark: 'engine-start', events: [] };
    case 'ready': return { mark: 'engine', events: [] };
    case 'enter': return { mark: 'world-enter', events: ['world-loading'] };
    case 'world': return { mark: 'world-ready', events: ['world-ready'] };
    default: return { mark: null, events: [] };
  }
}

export function installStages(wenilla) {
  if (window.owStages) return window.owStages;
  const marks = {};
  const hitches = [];
  const boot = [];
  const st = (window.owStages = { marks, hitches, boot, frames: 0, worstFrameMs: 0, summary });
  const fire = (detail) => { try { window.dispatchEvent(new CustomEvent('ow:progress', { detail })); } catch { /* old browser */ } };
  const mark = (name, at = performance.now()) => {
    if (name in marks) return;
    marks[name] = Math.round(at);
    try { performance.mark('ow:stage:' + name, { startTime: at }); } catch { /* old browser */ }
    console.info(`${TAG} ${name} at ${marks[name]} ms`);
    if (name === 'world-ready' || (name === 'world-enter' && !watchStarted)) startWatch(name);
  };

  // The engine's progress hook: boot.js assigns window.__wenilla_progress; keep its function and
  // see every stage first, whichever of the two installs first.
  let inner = window.__wenilla_progress;
  let inWorldLoad = false;     // between 'world-loading' and 'world-ready' (each world entry)
  const hook = (stage) => {
    const s = String(stage);
    const m = stageMap(s);
    if (m.mark) mark(m.mark);
    fire(s);
    for (const ev of m.events) {
      if (ev === 'world-loading') { if (inWorldLoad) continue; inWorldLoad = true; }
      if (ev === 'world-ready') inWorldLoad = false;
      fire(ev);
    }
    if (s === 'world') afterFrame(() => mark('first-frame'));
    if (typeof inner === 'function') return inner(stage);
    return undefined;
  };
  try {
    Object.defineProperty(window, '__wenilla_progress', {
      configurable: true,
      get: () => hook,
      set: (f) => { if (f !== hook) inner = f; },
    });
  } catch { /* a non-configurable global: stages fall back to the bridge */ }

  // The bridge: screen states and the first movement.
  let readyPos = null;
  wenilla?.on?.('state', (s) => {
    const name = s?.state;
    if (name === 'login') mark('login');
    if (name === 'charselect') mark('charlist');
    // an older client has no 'enter': the bridge's state stands in for the mark (not for the
    // 'world-loading' event: with no 'world' after it, the touch controls would stay hidden)
    if (name === 'inworld' && !('world-enter' in marks)) { mark('world-enter'); afterFrame(() => markLate('first-frame')); }
  });
  wenilla?.on?.('frame', (snap) => {
    if (!('world-ready' in marks) || 'first-move' in marks) return;
    const p = snap?.self?.pos;
    if (!p) return;
    readyPos ??= p;
    if (snap.self.moving || Math.hypot(p[0] - readyPos[0], p[1] - readyPos[1]) > 0.5) mark('first-move');
  });
  function markLate(name) { if (!('world-ready' in marks)) mark(name); }

  // The boot overlay's lines (download percent, data counts) are hidden on screen (wrath-page.js);
  // their phases are kept here instead, one entry per phase, with the last text seen.
  watchBootOverlay(boot);

  // The frame-gap watch.
  let watchStarted = false;
  function startWatch(from) {
    watchStarted = true;
    const t0 = performance.now();
    let last = t0;
    const tick = (t) => {
      const gap = t - last;
      last = t;
      st.frames += 1;
      if (gap > st.worstFrameMs) st.worstFrameMs = Math.round(gap);
      if (gap > HITCH_MS) hitches.push({ at: Math.round(t - t0), ms: Math.round(gap), from });
      if (t - t0 < WATCH_MS) requestAnimationFrame(tick);
      else console.info(`${TAG} first ${WATCH_MS / 1000}s after ${from}: ${st.frames} frames, ${hitches.length} hitches over ${HITCH_MS} ms (worst ${st.worstFrameMs} ms)`);
    };
    requestAnimationFrame(tick);
  }

  function summary() {
    const d = (a, b) => (marks[a] != null && marks[b] != null ? marks[b] - marks[a] : null);
    return {
      marks: { ...marks },
      spans: {
        boot: marks.engine ?? null,
        startup: d('engine-start', 'engine'),
        toCharlist: marks.charlist ?? null,
        worldLoad: d('world-enter', 'world-ready'),
        toFirstFrame: d('world-enter', 'first-frame'),
        toFirstMove: d('world-ready', 'first-move'),
      },
      boot: boot.slice(),
      hitches: hitches.length,
      worstFrameMs: st.worstFrameMs,
    };
  }
  return st;
}

/** Follow #wenilla-boot's text lines (boot.js) into `out`: [{ phase, text, at }]. */
function watchBootOverlay(out) {
  const phaseOf = (t) => t.split(/\s+[—-]\s+|\s+\d/)[0].trim();
  const seen = new Map();
  const read = () => {
    const el = document.getElementById('wenilla-boot');
    if (!el) return;
    for (const sel of ['.stage', '.data', '.err']) {
      const t = el.querySelector(sel)?.textContent?.trim();
      if (!t) continue;
      const phase = sel + ' ' + phaseOf(t);
      const row = seen.get(phase);
      if (row) { row.text = t; continue; }
      const r = { phase, text: t, at: Math.round(performance.now()) };
      seen.set(phase, r);
      out.push(r);
      console.info(`${TAG} boot: ${t}`);
    }
  };
  try {
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { subtree: true, childList: true, characterData: true });
    setTimeout(() => mo.disconnect(), 180000);
  } catch { /* no observer */ }
}

function afterFrame(fn) {
  requestAnimationFrame(() => requestAnimationFrame(() => fn()));
}
