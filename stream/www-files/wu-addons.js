// wu-addons.js — "Your addons" on the Wrath page: drop an addon's .zip (or its folder) anywhere on
// the page to install it; the dock's "Your addons" lists them (size, on/off, remove).
//
// Loaded by wrath-early.js before the client starts: boot() reads the turned-on addons from this
// browser's private storage (wu-addons-core.js openStore, one folder per account) into the layer
// wrath-early.js put in front of the client's body store, so the client finds them as ordinary
// addons on this page load (and in game under Esc > Mods & Workshop > Installed). An addon added,
// turned on/off or removed here takes effect when the page next loads.
//
// Safety: every drop is checked with the UI rules of mods/wu-mod.py (wu-addons-core.js validate):
// Interface/AddOns/<Name>/ only, a <Name>.toc with ## Interface: 30300, the file types an addon
// uses, no game data, size limits, safe zip paths. The files stay in this browser, are never
// uploaded, and the page never runs them: only the client's addon sandbox does.

import { openStore, readZip, validate, fmtSize, AddonError, LIMITS } from './wu-addons-core.js';

const state = { store: null, layer: null, loaded: [], changed: false, error: null, panel: null };

function account() {
  const env = globalThis.__wenilla_env;
  return env && typeof env === 'object' && typeof env.user === 'string' ? env.user : '';
}

/** Before the client starts: the turned-on addons into the layer, then the page's drop and list. */
export async function boot(layer) {
  state.layer = layer || globalThis.__wuAddonLayer || null;
  try {
    state.store = await openStore({ user: account() });
    const list = await state.store.load();
    if (state.layer && list.length) {
      state.layer.set(list);
      // the name index the layer adds to must be in the body store before the client asks for it
      const s = state.layer.store;
      if (s && !Map.prototype.has.call(s, '__index')) {
        try {
          const r = await fetch('/data/__index');
          if (r.ok) Map.prototype.set.call(s, '__index', await r.arrayBuffer());
        } catch (_) { /* the client reads it itself; local addons then wait for the next load */ }
      }
    }
    state.loaded = list.map((a) => a.name);
    if (list.broken && list.broken.length) console.warn('wu-addons: unreadable, left out:', list.broken.join(', '));
  } catch (e) {
    state.error = String((e && e.message) || e);
    console.warn('wu-addons:', e);
  }
  const ui = () => { try { mountDrop(); mountDockButton(); } catch (e) { console.warn('wu-addons ui', e); } };
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ui, { once: true });
    else ui();
  }
  globalThis.wuAddons = { state, install: installFiles, list: () => state.store && state.store.list() };
  return { loaded: state.loaded.slice(), error: state.error };
}

// -- reading a drop -------------------------------------------------------------------------------

function xmlCheck(text) {
  if (typeof DOMParser === 'undefined') return null;
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  const err = doc.getElementsByTagName('parsererror')[0];
  return err ? (err.textContent || 'parse error').split('\n')[0].slice(0, 120) : null;
}

async function readFolder(entry, prefix, out) {
  if (out.length > LIMITS.files) throw new AddonError(`the folder has more than ${LIMITS.files} files`);
  if (entry.isFile) {
    const file = await new Promise((res, rej) => entry.file(res, rej));
    if (file.size > LIMITS.file) throw new AddonError(`${prefix + entry.name} is larger than ${fmtSize(LIMITS.file)}`);
    out.push({ path: prefix + entry.name, data: new Uint8Array(await file.arrayBuffer()) });
    return;
  }
  if (!entry.isDirectory) return;
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
    if (!batch.length) break;
    for (const e of batch) await readFolder(e, prefix + entry.name + '/', out);
  }
}

/** The dropped things as file sets: [{label, entries} | {label, error}]. */
async function readDrop(dt) {
  const out = [];
  const items = dt.items ? [...dt.items].filter((i) => i.kind === 'file') : [];
  const entries = items.map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
  const files = [...(dt.files || [])];
  for (let i = 0; i < Math.max(entries.length, files.length); i++) {
    const entry = entries[i];
    const file = files[i];
    const label = (entry && entry.name) || (file && file.name) || 'the drop';
    try {
      if (entry && entry.isDirectory) {
        const got = [];
        await readFolder(entry, '', got);
        out.push({ label, entries: got });
      } else if (file && /\.zip$/i.test(file.name)) {
        if (file.size > LIMITS.package * 2) throw new AddonError(`the zip is larger than ${fmtSize(LIMITS.package)}`);
        out.push({ label, entries: await readZip(new Uint8Array(await file.arrayBuffer())) });
      } else {
        throw new AddonError('drop an addon\'s .zip or its folder');
      }
    } catch (e) {
      out.push({ label, error: String((e && e.message) || e) });
    }
  }
  return out;
}

/** Check and keep file sets; [{label, ok, addons, errors, warnings}] for the report. */
export async function installFiles(sets) {
  const report = [];
  for (const s of sets) {
    if (s.error) { report.push({ label: s.label, ok: false, errors: [s.error], warnings: [], addons: [] }); continue; }
    const v = validate(s.entries, { xml: xmlCheck });
    const r = { label: s.label, ok: false, errors: v.errors.slice(), warnings: v.warnings, addons: [] };
    if (!v.errors.length) {
      try {
        if (!state.store) throw new AddonError(state.error || 'this browser cannot keep addons');
        for (const a of v.addons) r.addons.push(await state.store.add(a));
        r.ok = true;
        state.changed = true;
      } catch (e) {
        r.errors.push(String((e && e.message) || e));
      }
    }
    report.push(r);
  }
  return report;
}

// -- the page -------------------------------------------------------------------------------------

const CSS = `
#wu-drop{position:fixed;inset:0;z-index:60;display:grid;place-items:center;pointer-events:none;opacity:0;
  transition:opacity .15s;background:rgba(5,4,12,.72)}
#wu-drop.on{opacity:1}
#wu-drop .box,#wu-addons{background:radial-gradient(120% 140% at 50% 0%,rgba(42,28,84,.92),rgba(8,6,18,.96) 70%);
  border:1px solid #8a6a2c;border-radius:10px;color:#e9e4d4;
  box-shadow:inset 0 0 0 1px rgba(255,215,130,.14),inset 0 0 36px rgba(70,50,160,.35),0 14px 44px rgba(0,0,0,.7)}
#wu-drop .box{padding:28px 44px;text-align:center;border-style:dashed;border-width:2px}
#wu-drop h2,#wu-addons h2{margin:0;font:600 22px 'OW Cinzel',Georgia,serif;letter-spacing:.06em;color:#f2d48a}
#wu-drop p{margin:8px 0 0;font:13px system-ui,sans-serif;color:#b9c6e6}
#wu-addons{position:fixed;top:2.4rem;left:50%;transform:translateX(-50%);z-index:61;width:min(30rem,calc(100vw - 1rem));
  max-height:calc(100vh - 3.4rem);overflow:auto;padding:14px 16px;box-sizing:border-box;font:13px/1.45 system-ui,sans-serif}
#wu-addons h2{font-size:17px;margin-bottom:4px}
#wu-addons .fine{color:#a9a3c4;font-size:12px;margin:0 0 8px}
#wu-addons .row{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid rgba(138,106,44,.35)}
#wu-addons .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#wu-addons .size,#wu-addons .note{color:#a9a3c4;font-size:12px;white-space:nowrap;font-variant-numeric:tabular-nums}
#wu-addons button{background:#2a2440;color:#e9e4d4;border:1px solid rgba(138,106,44,.6);border-radius:5px;padding:3px 9px;font:inherit;cursor:pointer}
#wu-addons button.go{background:#c9a227;color:#1a1408;font-weight:600;border-color:#c9a227}
#wu-addons label.sw{display:inline-flex;align-items:center;gap:4px;font-size:12px;cursor:pointer}
#wu-addons .msg{margin:8px 0 0;font-size:12px}
#wu-addons .msg .bad{color:#ff9a8f}
#wu-addons .msg .ok{color:#9fe0a0}
#wu-addons .msg .warn{color:#e8cf86}
#wu-addons .msg ul{margin:2px 0 6px;padding-left:18px}
#wu-addons .foot{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}
`;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k);
  return e;
}

function css() {
  if (document.getElementById('wu-addons-css')) return;
  document.head.append(el('style', { id: 'wu-addons-css' }, CSS));
}

const hasFiles = (e) => !!(e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files'));

function mountDrop() {
  if (document.getElementById('wu-drop')) return;
  css();
  const box = el('div', { class: 'box' }, el('h2', {}, 'Drop to install addon'),
    el('p', {}, 'An addon\'s .zip or its folder. It stays in this browser and is never uploaded.'));
  const overlay = el('div', { id: 'wu-drop', 'aria-hidden': 'true' }, box);
  document.body.append(overlay);
  let depth = 0;
  const show = (on) => overlay.classList.toggle('on', on);
  addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; show(true); }, true);
  addEventListener('dragover', (e) => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }, true);
  addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) show(false); }, true);
  addEventListener('drop', async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();   // a file dropped on the page must never navigate away from the game
    e.stopPropagation();
    depth = 0;
    show(false);
    const sets = await readDrop(e.dataTransfer);
    const report = await installFiles(sets);
    await openPanel(report);
  }, true);
}

function mountDockButton() {
  let tries = 0;
  const look = () => {
    const panel = document.getElementById('ow-dock-panel');
    if (!panel) { if (++tries < 120) setTimeout(look, 250); return; }
    if (panel.querySelector('#wu-addons-open')) return;
    panel.append(el('button', { id: 'wu-addons-open', type: 'button', title: 'The addons you added to this browser',
      onclick: () => (state.panel ? closePanel() : openPanel()) }, 'Your addons'));
  };
  look();
}

function closePanel() {
  if (state.panel) state.panel.remove();
  state.panel = null;
}

function reportView(report) {
  const box = el('div', { class: 'msg', role: 'status' });
  for (const r of report || []) {
    if (r.ok) {
      box.append(el('div', { class: 'ok' }, `Installed ${r.addons.map((a) => `${a.name} (${fmtSize(a.size)})`).join(', ')}. ` +
        'It loads when the page next loads.'));
    } else {
      box.append(el('div', { class: 'bad' }, `${r.label} was not installed:`),
        el('ul', {}, ...r.errors.slice(0, 12).map((x) => el('li', {}, x)),
          r.errors.length > 12 ? el('li', {}, `and ${r.errors.length - 12} more`) : null));
    }
    if (r.warnings && r.warnings.length) box.append(el('ul', { class: 'warn' }, ...r.warnings.slice(0, 6).map((x) => el('li', {}, x))));
  }
  return box;
}

async function openPanel(report) {
  css();
  closePanel();
  const root = el('div', { id: 'wu-addons', role: 'dialog', 'aria-label': 'Your addons' });
  state.panel = root;
  document.body.append(root);
  await renderPanel(root, report);
}

async function renderPanel(root, report) {
  root.replaceChildren();
  const info = state.layer && state.layer.info ? state.layer.info() : { loaded: state.loaded, shadowed: [] };
  const list = state.store ? await state.store.list().catch(() => []) : [];
  const usage = state.store ? await state.store.usage().catch(() => null) : null;
  root.append(el('h2', {}, 'Your addons'),
    el('p', { class: 'fine' }, 'Drop an addon\'s .zip or folder anywhere on the page to add it. Addons stay in this browser, for ' +
      'this account, and are never uploaded. Changes here apply when the page next loads; in game, Esc > Mods & Workshop > ' +
      'Installed turns them on or off like any addon.'));
  if (state.error) root.append(el('p', { class: 'msg' }, el('span', { class: 'bad' }, state.error)));
  if (!list.length && state.store) root.append(el('p', { class: 'fine' }, 'No addons yet.'));
  const lowerShadow = new Set((info.shadowed || []).map((n) => n.toLowerCase()));
  const lowerLoaded = new Set((info.loaded || []).map((n) => n.toLowerCase()));
  for (const a of list) {
    const low = a.name.toLowerCase();
    const note = lowerShadow.has(low) ? 'the realm has its own copy' : a.on && !lowerLoaded.has(low) ? 'loads next time'
      : !a.on && lowerLoaded.has(low) ? 'off next time' : a.on ? 'loaded' : 'off';
    const box = el('input', { type: 'checkbox' });
    box.checked = a.on;
    box.addEventListener('change', async () => {
      await state.store.setOn(a.name, box.checked);
      state.changed = true;
      renderPanel(root);
    });
    root.append(el('div', { class: 'row' },
      el('span', { class: 'name', title: a.name }, a.name),
      el('span', { class: 'size' }, fmtSize(a.size)),
      el('span', { class: 'note' }, note),
      el('label', { class: 'sw', title: 'Load this addon' }, box, 'on'),
      el('button', { type: 'button', title: `Remove ${a.name} from this browser`, onclick: async () => {
        await state.store.remove(a.name);
        state.changed = true;
        renderPanel(root);
      } }, 'Remove')));
  }
  if (report) root.append(reportView(report));
  const pick = el('input', { type: 'file', accept: '.zip,application/zip', multiple: '', hidden: '' });
  pick.addEventListener('change', async () => {
    const sets = [];
    for (const f of pick.files) {
      try { sets.push({ label: f.name, entries: await readZip(new Uint8Array(await f.arrayBuffer())) }); }
      catch (e) { sets.push({ label: f.name, error: String((e && e.message) || e) }); }
    }
    renderPanel(root, await installFiles(sets));
  });
  root.append(el('div', { class: 'foot' },
    el('span', { class: 'fine' }, usage ? `${fmtSize(usage.used)} of ${fmtSize(usage.cap)} used` : ''),
    el('span', {}, pick,
      el('button', { type: 'button', onclick: () => pick.click() }, 'Add a .zip'), ' ',
      state.changed ? el('button', { type: 'button', class: 'go', onclick: () => location.reload() }, 'Reload now') : null, ' ',
      el('button', { type: 'button', onclick: closePanel }, 'Close'))));
}

export const _test = { state, readDrop };
