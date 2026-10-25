// touch-driver.js — what touch.js talks to on the WrathUnleashed page: the page bridge
// (window.wenilla, bridge.js) when the client answers it, else the canvas's keyboard and wheel.
//
// Why a second path: bridge.js always defines window.wenilla, but the wasm side of the bridge
// (benilla-app/src/webbridge) is not compiled into the 3.3.5a client yet (lib.rs: `// mod
// webbridge;`), so on the live page wenilla.ready stays false, the command queue is never drained
// and every wenilla.lua() times out. Touch controls must still move the character there, so:
//
//   * bridge live (wenilla.ready):  hold / fire / lua / chat go to the bridge, unchanged;
//   * no bridge:                    hold / fire become key presses on the game canvas, by the
//                                   3.3.5a default key for that binding command (the client's own
//                                   builtin_default_bindings.wtf); CAMERAZOOMIN/OUT become wheel
//                                   notches; lua() rejects at once (callers treat it as "no answer");
//                                   chat() types the line into the chat box (Enter, the text, Enter).
//                                   A player who rebound a key moves with the old key's command:
//                                   that is the price of this path, and why the bridge is wanted.
//   * screen state:                 the bridge's 'state' events when live; else from the client's
//                                   progress stages (window 'ow:progress', stages.js): 'ready' =
//                                   a glue screen, 'enter' / 'world' = in the world. A return to
//                                   the character list from the world is not seen on this path
//                                   (touch.js then shows a flip button: driver.force()).
//
// The choice is made per call, so the bridge taking over mid-session (a new client build) just
// works: keys held through the fallback are let go when it does.

/** 3.3.5a's default keys for the commands touch.js sends (builtin_default_bindings.wtf). */
export const KEYMAP = {
  MOVEFORWARD: 'w', MOVEBACKWARD: 's', TURNLEFT: 'a', TURNRIGHT: 'd', STRAFELEFT: 'q', STRAFERIGHT: 'e',
  JUMP: ' ', TOGGLEAUTORUN: 'NumLock', TARGETNEARESTENEMY: 'Tab', ATTACKTARGET: 't',
  ACTIONBUTTON1: '1', ACTIONBUTTON2: '2', ACTIONBUTTON3: '3', ACTIONBUTTON4: '4', ACTIONBUTTON5: '5',
  ACTIONBUTTON6: '6', ACTIONBUTTON7: '7', ACTIONBUTTON8: '8', ACTIONBUTTON9: '9', ACTIONBUTTON10: '0',
  ACTIONBUTTON11: '-', ACTIONBUTTON12: '=',
  OPENALLBAGS: 'b', TOGGLECHARACTER0: 'c', TOGGLECHARACTER4: 'h', TOGGLESPELLBOOK: 'p', TOGGLETALENTS: 'n',
  TOGGLEQUESTLOG: 'l', TOGGLEWORLDMAP: 'm', TOGGLESOCIAL: 'o', TOGGLEACHIEVEMENT: 'y', TOGGLELFGPARENT: 'i',
  TOGGLEGAMEMENU: 'Escape', OPENCHAT: 'Enter',
};
const WHEEL = { CAMERAZOOMIN: -120, CAMERAZOOMOUT: 120 };

/** The KeyboardEvent fields for one key as a US keyboard sends it. */
export function keyFields(key) {
  if (key === ' ') return { key: ' ', code: 'Space' };
  if (/^[a-z]$/i.test(key)) return { key: key.toLowerCase(), code: 'Key' + key.toUpperCase() };
  if (/^\d$/.test(key)) return { key, code: 'Digit' + key };
  const SPECIAL = { '-': 'Minus', '=': 'Equal', '/': 'Slash', '.': 'Period', ',': 'Comma' };
  if (SPECIAL[key]) return { key, code: SPECIAL[key] };
  return { key, code: key };   // Tab, Enter, Escape, NumLock, Backspace: key and code agree
}

/** Map a client progress stage to the screen state it implies (no bridge). */
export function stateFromStage(stage) {
  if (stage === 'ready' || stage === 'reconnecting' || /^reconnect:/.test(stage || '')) return 'login';
  if (stage === 'enter' || stage === 'world' || stage === 'world-loading' || stage === 'world-ready') return 'inworld';
  return null;
}

export function makeDriver(raw, opts = {}) {
  const canvas = opts.canvas || (() => document.getElementById('benilla') || document.querySelector('canvas'));
  const live = () => !!raw?.ready;
  const held = new Set();            // commands held down through the key path
  const stateCbs = new Set();
  let synthetic = null;              // { session: { state } } while the bridge is silent
  const stats = { keys: 0, wheels: 0, refused: 0 };

  const focusCanvas = (c) => {
    const a = document.activeElement;
    // never take the keyboard from a text field (the chat sheet, the type bar)
    if (a && a !== c && a !== document.body && /^(INPUT|TEXTAREA)$/.test(a.tagName)) return;
    if (a !== c) { try { c.focus({ preventScroll: true }); } catch { /* not focusable */ } }
  };
  function key(type, k, extra = {}) {
    const c = canvas();
    if (!c) return;
    focusCanvas(c);
    stats.keys += 1;
    c.dispatchEvent(new KeyboardEvent(type, { ...keyFields(k), bubbles: true, cancelable: true, composed: true, ...extra }));
  }
  function tapKey(k, ms = 60) {
    key('keydown', k);
    setTimeout(() => key('keyup', k), ms);
  }
  function wheel(dy) {
    const c = canvas();
    if (!c) return;
    const r = c.getBoundingClientRect();
    stats.wheels += 1;
    c.dispatchEvent(new WheelEvent('wheel', { deltaY: dy, deltaMode: 0, bubbles: true, cancelable: true,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
  }
  const releaseKeys = () => { for (const cmd of [...held]) { held.delete(cmd); key('keyup', KEYMAP[cmd]); } };

  const driver = {
    stats,
    get live() { return live(); },
    get raw() { return raw; },
    get ready() { return live(); },
    get state() { return live() ? raw.state : (synthetic || raw?.state); },
    get gamepad() { return raw?.gamepad; },
    hold(cmd, down = true) {
      if (live()) { if (held.size) releaseKeys(); raw.hold(cmd, down); return; }
      const k = KEYMAP[cmd];
      if (!k) { stats.refused += 1; return; }
      if (down && !held.has(cmd)) { held.add(cmd); key('keydown', k); }
      else if (!down && held.has(cmd)) { held.delete(cmd); key('keyup', k); }
    },
    fire(cmd, amount = 1) {
      if (live()) { raw.fire(cmd, amount); return; }
      if (WHEEL[cmd]) { wheel(WHEEL[cmd] * Math.max(1, Math.round(amount))); return; }
      const k = KEYMAP[cmd];
      if (!k) { stats.refused += 1; return; }
      tapKey(k);
    },
    lua(chunk, timeoutMs) {
      if (live()) return raw.lua(chunk, timeoutMs);
      return Promise.reject(new Error('no page bridge in this client'));
    },
    chat(text) {
      if (live()) { raw.chat(text); return; }
      // the chat box: open it, type, send (as a keyboard would; slash commands parse client-side)
      key('keydown', 'Enter'); key('keyup', 'Enter');
      setTimeout(() => {
        for (const ch of String(text)) {
          key('keydown', ch); key('keypress', ch, { charCode: ch.charCodeAt(0) }); key('keyup', ch);
        }
        key('keydown', 'Enter'); key('keyup', 'Enter');
      }, 80);
    },
    on(name, cb) {
      if (name === 'state') stateCbs.add(cb);
      return raw?.on?.(name, cb);
    },
    releaseAll() { releaseKeys(); if (live()) raw.releaseAll?.(); },
    /** The screen state, whichever path knows it. */
    session() { return driver.state?.session?.state; },
  };

  // the screen state from the client's own progress stages, while the bridge says nothing
  const setSynthetic = (st) => {
    if (!st || live() || synthetic?.session?.state === st) return;
    synthetic = { session: { state: st, connected: true }, synthetic: true };
    for (const cb of stateCbs) { try { cb({ state: st, connected: true, synthetic: true }); } catch { /* one listener */ } }
  };
  addEventListener('ow:progress', (e) => setSynthetic(stateFromStage(String(e.detail || ''))));
  /** No bridge: the player says which screen this is (an older client sends no world stages). */
  driver.force = (st) => setSynthetic(st);
  // the bridge arriving: let go of anything the key path still holds
  raw?.on?.('ready', () => releaseKeys());
  return driver;
}
