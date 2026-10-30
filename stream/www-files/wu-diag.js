// wu-diag.js — window.owdiag on the WrathUnleashed page: one call, one compact JSON report.
// A small stand-in for Open Vanilla's 1.12 owdiag kit (its checks and capture routines are 1.12
// specific); loaded by wrath-page.js on first use, or at once with ?diag=1.
//
//   await owdiag.run()     the page's state: bridge, stages, touch, input, service worker,
//                          fetch-ahead, the screen, and the checks that failed
//   await owdiag.log()     the captured page errors and failed requests, deduplicated
//   owdiag.stages()        window.owStages.summary()
//   ?diag=1                runs once when the first glue screen is up and logs the report
//
// Never prints a credential: __wenilla_env is reported only as which keys it has.

export function createDiag(wenilla) {
  const errors = new Map();
  const failed = new Map();
  let capturing = false;
  const note = (m, k) => m.set(k, (m.get(k) || 0) + 1);

  function capture() {
    if (capturing) return;
    capturing = true;
    addEventListener('error', (e) => note(errors, String(e.message || e.error || 'error').slice(0, 200)));
    addEventListener('unhandledrejection', (e) => note(errors, String(e.reason?.message || e.reason || 'rejection').slice(0, 200)));
    try {
      new PerformanceObserver((list) => {
        for (const r of list.getEntries()) if (r.responseStatus >= 400) note(failed, `${r.responseStatus} ${new URL(r.name).pathname}`.slice(0, 160));
      }).observe({ type: 'resource', buffered: true });
    } catch { /* no responseStatus in this browser */ }
  }

  function envKeys() {
    const e = window.__wenilla_env;
    return e && typeof e === 'object' ? Object.keys(e).sort() : [];
  }

  async function run() {
    const c = document.getElementById('benilla');
    const checks = [];
    const check = (name, ok, why) => checks.push({ name, ok: !!ok, ...(ok ? {} : { why }) });
    check('bridge.js loaded', !!wenilla, 'window.wenilla missing');
    check('bridge answers (wenilla.ready)', !!wenilla?.ready, 'the client has no page bridge compiled in (BRIDGE-GAPS.md)');
    check('cross-origin isolated', self.crossOriginIsolated, 'COOP/COEP missing: sections.js and own files need it');
    check('game canvas', !!c, 'no <canvas id="benilla">');
    let sw = null;
    try { sw = window.owsw ? await Promise.race([window.owsw.status(), new Promise((r) => setTimeout(() => r({ timeout: true }), 1500))]) : null; } catch { /* none */ }
    const t = window.owTouch;
    return {
      at: new Date().toISOString(),
      page: location.pathname,
      ua: navigator.userAgent,
      screen: { css: [innerWidth, innerHeight], dpr: devicePixelRatio, canvas: c ? [c.width, c.height] : null, touchPoints: navigator.maxTouchPoints || 0 },
      env: envKeys(),
      bridge: { ready: !!wenilla?.ready, commands: wenilla?.commands?.length || 0, state: wenilla?.state?.session?.state || null },
      stages: window.owStages?.summary?.() || null,
      touch: t ? { on: t.on, inworld: t.inworld, via: t.bridge, presses: t.presses, taps: t.taps, drags: t.drags, errors: t.errors, layout: t.layout, driver: t.driver } : null,
      input: window.owInput || null,
      sw,
      ahead: window.owAhead || null,
      loading: window.wuLoading ? { shown: window.wuLoading.shown, on: window.wuLoading.on, lines: window.wuLoading.lines } : null,
      page_layer: window.wuPage?.status || null,
      failing: checks.filter((x) => !x.ok),
      passed: checks.filter((x) => x.ok).length,
      errors: errors.size,
    };
  }

  return {
    capture,
    run,
    stages: () => window.owStages?.summary?.() || null,
    log: async () => ({ errors: Object.fromEntries(errors), failed: Object.fromEntries(failed) }),
    autorun: () => {
      const go = () => run().then((r) => console.info('[WrathUnleashed] owdiag', r));
      addEventListener('ow:progress', (e) => { if (e.detail === 'ready' || e.detail === 'world') setTimeout(go, 3000); });
    },
  };
}
