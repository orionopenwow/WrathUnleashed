// Leyline themes: applies the chosen theme before the page paints, and draws Settings › Themes and
// Mods › Discover › Themes. Plain JS, no framework. The Rust side is src-tauri/src/themes.rs.
//
// Two built-in looks, Dark (the default) and Light. How a theme is applied:
//   <html data-theme="<id>" data-base="dark|light">      always (style.css is Dark; data-base="light" switches)
//   <style id="ly-theme-pack">                            an installed pack's checked CSS (from the core only)
// Ctrl+Shift+Backspace always goes back to Dark. A choice saved by an older Leyline (Leyline Classic, the
// Rounded looks) is moved to Dark or Light, here and in the core.
"use strict";

(function () {
  const KEY = "leyline.theme";
  const DEFAULT = "dark";
  const BUILTIN_KIND = { dark: "dark", light: "light" };
  const root = document.documentElement;
  const sysDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  // Older built-ins, and what they become. "Rounded Auto" followed the system: it lands on whichever the system is now.
  const LEGACY = {
    "leyline-classic": () => "dark",
    "dark-rounded": () => "dark",
    "light-rounded": () => "light",
    "rounded-system": () => (sysDark && !sysDark.matches ? "light" : "dark"),
  };
  const invoke = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;

  let current = { id: DEFAULT, kind: "dark" };
  let migrated = false;         // an old choice was moved: tell the core once
  let saved = current;          // what is remembered (a preview may differ until KEEP)
  let list = [];                // themes_list().themes
  let catalogThemes = [];       // the Workshop's "themes" projects
  let catalogCategory = null;

  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) { return null; } },
    set(v) {
      try { localStorage.setItem(KEY, JSON.stringify(v)); }
      catch (_) { try { localStorage.setItem(KEY, JSON.stringify({ id: v.id, kind: v.kind })); } catch (_) { /* storage off */ } }
    },
  };

  // A pack's kind: "dark" or "light" (packs made for an older Leyline say "rounded-light", "rounded-dark" or "classic").
  const base = (kind) => (kind === "light" || kind === "rounded-light" ? "light" : "dark");

  function paint(id, kind, css) {
    root.dataset.theme = id;
    root.dataset.base = base(kind);
    delete root.dataset.skin;
    let tag = document.getElementById("ly-theme-pack");
    if (css) {
      if (!tag) { tag = document.createElement("style"); tag.id = "ly-theme-pack"; document.head.append(tag); }
      tag.textContent = css;
    } else if (tag) tag.remove();
    current = { id, kind };
  }

  // Apply a theme. Packs fetch their checked CSS from the core; built-ins need nothing.
  async function apply(id, opts) {
    const o = opts || {};
    let kind = BUILTIN_KIND[id];
    let css = "";
    if (!kind) {
      if (!invoke) throw "Theme packs work in the Leyline app.";
      const t = await invoke("theme_css", { id });
      kind = t.kind; css = t.css;
    }
    paint(id, kind, css);
    if (o.save) {
      if (invoke) await invoke("theme_apply", { id });
      saved = { id, kind };
      store.set(css.length < 1500000 ? { id, kind, css } : { id, kind });
    }
  }

  // ---------------------------------------------------------------- before first paint
  (function boot() {
    let s = store.get();
    if (s && typeof s.id === "string" && LEGACY[s.id]) {
      const id = LEGACY[s.id]();
      s = { id, kind: BUILTIN_KIND[id] };
      store.set(s);
      migrated = true;
    }
    if (s && typeof s.id === "string" && typeof s.kind === "string") {
      try { paint(s.id, s.kind, typeof s.css === "string" ? s.css : ""); } catch (_) { paint(DEFAULT, "dark", ""); }
    } else paint(DEFAULT, "dark", "");
    saved = current;
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.shiftKey && e.key === "Backspace") {
        e.preventDefault();
        apply(DEFAULT, { save: true }).then(() => say("Back to Dark.", "ok")).catch(() => paint(DEFAULT, "dark", ""));
      }
    });
  })();

  // ---------------------------------------------------------------- the core's word wins
  async function sync() {
    if (!invoke) {
      list = Object.keys(BUILTIN_KIND).map((id) => ({ id, builtin: true, kind: BUILTIN_KIND[id], name: NAMES[id], description: LINES[id], author: "Leyline" }));
      return;
    }
    if (migrated) {                                  // the core moves old choices too; this keeps Light-from-Auto
      migrated = false;
      try { await invoke("theme_apply", { id: saved.id }); } catch (_) { /* the core's own default stands */ }
    }
    const r = await invoke("themes_list");
    list = r.themes || [];
    if (current.id !== saved.id) return;            // a preview is on: leave it until KEEP or UNDO
    if (r.active === saved.id && BUILTIN_KIND[r.active]) return;
    try {
      await apply(r.active, { save: false });         // packs: always the checked CSS from the core
      saved = current;
      const css = (document.getElementById("ly-theme-pack") || {}).textContent || "";
      store.set(css.length < 1500000 ? { id: current.id, kind: current.kind, css } : { id: current.id, kind: current.kind });
    } catch (_) {
      paint(DEFAULT, "dark", "");
      saved = current;
      store.set(saved);
    }
  }
  const NAMES = { dark: "Dark", light: "Light" };
  const LINES = {
    dark: "Navy and charcoal with a blue accent. The default.",
    light: "Bright and clean with the same blue accent.",
  };

  // ---------------------------------------------------------------- small helpers
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const btn = (label, cls, fn) => {
    const b = el("button", "btn small" + (cls ? " " + cls : ""), label);
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  };
  function say(text, kind) {
    for (const s of document.querySelectorAll(".themes-status")) {
      s.textContent = text || "";
      s.className = "status themes-status" + (kind ? " " + kind : "");
    }
  }
  const nameOf = (id) => (list.find((t) => t.id === id) || {}).name || NAMES[id] || id;

  async function busy(b, fn) {
    const all = document.querySelectorAll(".themes-box button");
    all.forEach((x) => { x.dataset.was = x.disabled ? "1" : ""; x.disabled = true; });
    try { await fn(); }
    catch (e) { say(String(e), "bad"); }
    finally { all.forEach((x) => { if (document.contains(x)) x.disabled = x.dataset.was === "1"; }); render(); }
  }

  // ---------------------------------------------------------------- preview bar
  function previewBar() {
    let bar = document.getElementById("theme-preview-bar");
    if (current.id === saved.id) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = el("div", "theme-preview-bar");
      bar.id = "theme-preview-bar";
      bar.setAttribute("role", "status");
      document.body.append(bar);
    }
    bar.replaceChildren(
      el("span", "", "Previewing " + nameOf(current.id)),
      btn("KEEP", "", () => busy(null, async () => { await apply(current.id, { save: true }); say("Theme set to " + nameOf(current.id) + ".", "ok"); })),
      btn("UNDO", "", () => busy(null, async () => { await apply(saved.id, { save: false }); say(""); })),
    );
  }

  // ---------------------------------------------------------------- cards
  function swatch(t) {
    const s = el("div", "theme-swatch");
    if (t.preview && /^data:image\/(png|webp);base64,/.test(t.preview)) {
      const img = el("img");
      img.alt = "";
      img.src = t.preview;
      s.append(img);
    } else {
      s.classList.add("k-" + (t.kind === "unknown" ? "unknown" : base(t.kind)));
      s.append(el("i", "sw-side"), el("i", "sw-main"), el("i", "sw-btn"));
    }
    return s;
  }

  function themeCard(t) {
    const card = el("article", "theme-card" + (t.id === saved.id ? " on" : ""));
    card.append(swatch(t));
    const top = el("div", "top");
    top.append(el("b", "name", t.name || t.id));
    if (t.id === saved.id) top.append(el("span", "tag gold", "In use"));
    else if (t.id === current.id) top.append(el("span", "tag", "Previewing"));
    card.append(top);
    if (t.problem) {
      card.append(el("p", "hint bad", "This pack no longer passes the checks: " + t.problem));
    } else {
      card.append(el("p", "desc", t.description || ""));
      if (!t.builtin) card.append(el("p", "credit", [t.author, "v" + t.version, t.licence, t.source === "catalog" ? "from the Workshop" : "from a file"].filter(Boolean).join(" · ")));
    }
    const acts = el("div", "acts");
    if (!t.problem && t.id !== saved.id) {
      acts.append(btn("USE", "", () => busy(null, async () => { await apply(t.id, { save: true }); say("Theme set to " + nameOf(t.id) + ".", "ok"); })));
      if (t.id !== current.id) acts.append(btn("PREVIEW", "", () => busy(null, async () => { await apply(t.id, { save: false }); say(""); })));
    }
    if (!t.builtin) {
      acts.append(btn("REMOVE", "danger", () => busy(null, async () => {
        await invoke("theme_remove", { id: t.id });
        if (current.id === t.id || saved.id === t.id) await apply(DEFAULT, { save: true });
        await sync();
        say("Removed " + (t.name || t.id) + ".", "ok");
      })));
    }
    card.append(acts);
    return card;
  }

  function catalogCard(p) {
    const card = el("article", "theme-card");
    card.append(swatch({ kind: "unknown" }));
    const top = el("div", "top");
    top.append(el("b", "name", p.name));
    if (p.version) top.append(el("span", "ver-s", "v" + p.version));
    card.append(top, el("p", "desc", p.description || ""));
    card.append(el("p", "credit", p.credits || [p.author, p.licence || "licence not stated"].filter(Boolean).join(" · ")));
    const acts = el("div", "acts");
    const slug = p.id.startsWith("mod:") ? p.id.slice(4) : "";
    const have = list.find((t) => !t.builtin && (t.project === p.id || t.id === slug));
    if (p.source === "packaged" && p.download) {
      const fromHere = have && have.project === p.id;
      const update = fromHere && p.version && have.version !== p.version;
      if (!have || update) {
        acts.append(btn(update ? "UPDATE TO " + p.version : "INSTALL", "", () => busy(null, async () => {
          say("Downloading " + p.name + "…");
          const t = await invoke("theme_install", { project: p.id });
          await sync();
          say(`Installed ${t.name}. Press USE to switch to it.`, "ok");
        })));
      } else {
        const b = btn("INSTALLED", "", () => {});
        b.disabled = true;
        acts.append(b);
      }
      if (have && !have.problem && have.id !== saved.id) {
        acts.append(btn("USE", "", () => busy(null, async () => { await apply(have.id, { save: true }); say("Theme set to " + have.name + ".", "ok"); })));
      }
    } else {
      acts.append(el("span", "hint", "Get it from its page, then INSTALL FROM A ZIP."));
    }
    for (const [label, url] of [["Page", p.page], ["Source", p.repo], ["Author", p.author_url]]) {
      if (!url) continue;
      const b = el("button", "link-s", label);
      b.type = "button";
      b.addEventListener("click", () => invoke && invoke("open_url", { url }).catch((e) => say(String(e), "bad")));
      acts.append(b);
    }
    card.append(acts);
    return card;
  }

  // ---------------------------------------------------------------- the two places themes show
  function section(title, items, empty) {
    const s = el("section", "themes-group");
    s.append(el("h3", "", title));
    const grid = el("div", "theme-grid");
    if (items.length) items.forEach((i) => grid.append(i));
    else grid.append(el("p", "hint", empty));
    s.append(grid);
    return s;
  }

  function localButtons() {
    const row = el("div", "row");
    const pick = (folder) => busy(null, async () => {
      if (!invoke) throw "Theme packs work in the Leyline app.";
      const path = await invoke("pick_theme", { folder });
      if (!path) return;
      const t = await invoke("theme_install_local", { path });
      await sync();
      say(`Installed ${t.name}. Press USE to switch to it.`, "ok");
    });
    row.append(btn("INSTALL FROM A ZIP…", "", () => pick(false)), btn("INSTALL FROM A FOLDER…", "", () => pick(true)));
    return row;
  }

  function renderSettings(box) {
    const builtins = list.filter((t) => t.builtin).map(themeCard);
    const packs = list.filter((t) => !t.builtin).map(themeCard);
    const go = btn("FIND MORE THEMES", "", () => { if (window.LeylineNav) window.LeylineNav.show("mods", false, "discover"); showTab("themes"); });
    const actions = localButtons();
    actions.append(go);
    box.replaceChildren(
      el("h3", "", "Themes"),
      el("p", "lede", "How Leyline looks. Themes change colours, corners and fonts, never what the launcher does. Ctrl+Shift+Backspace always goes back to Dark."),
      section("Built in", builtins, ""),
      section("Installed", packs, "No theme packs yet. Find some under Mods › Discover › Themes, or install one from a zip."),
      actions,
      el("p", "status themes-status"),
    );
  }

  function renderDiscover(box) {
    const cards = catalogThemes.map(catalogCard);
    box.replaceChildren(
      el("p", "lede", (catalogCategory && catalogCategory.line) || "Theme packs from the Workshop: colours, fonts and art for the launcher. Packs are only CSS and images, checked before they are used."),
      section("From the Workshop", cards, "No theme packs in the Workshop yet. Make the first one: see MAKE A THEME."),
      section("Built in and installed", list.map(themeCard), ""),
    );
    const row = localButtons();
    const make = el("button", "btn small", "MAKE A THEME");
    make.type = "button";
    make.addEventListener("click", () => invoke && invoke("open_link", { name: "themes" }).catch((e) => say(String(e), "bad")));
    row.append(make);
    box.append(row, el("p", "status themes-status"));
  }

  function render() {
    const s = document.getElementById("themes-settings");
    if (s) renderSettings(s);
    const d = document.getElementById("themes-discover");
    if (d && !d.hidden) renderDiscover(d);
    previewBar();
  }

  // ---------------------------------------------------------------- Mods › Discover: Mods | Themes
  let tab = "mods";
  function showTab(t) {
    tab = t;
    const panel = document.getElementById("pane-discover");
    if (!panel) return;
    panel.dataset.tab = t;
    document.querySelectorAll("#discover-tabs .ly-tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
    const d = document.getElementById("themes-discover");
    d.hidden = t !== "themes";
    if (t === "themes") { renderDiscover(d); loadCatalog(); }
  }

  async function loadCatalog() {
    if (!invoke) return;
    try {
      const c = await invoke("mods_catalog");
      takeThemes(c);
      const d = document.getElementById("themes-discover");
      if (d && !d.hidden) renderDiscover(d);
    } catch (e) { say(String(e), "bad"); }
  }

  // app.js hands the Workshop catalog through here: theme packs are listed under Mods › Discover › Themes, not as mods.
  function takeThemes(c) {
    if (!c || !Array.isArray(c.projects)) return c;
    catalogThemes = c.projects.filter((p) => p.category === "themes");
    catalogCategory = (c.categories || []).find((k) => k.id === "themes") || catalogCategory;
    return Object.assign({}, c, {
      projects: c.projects.filter((p) => p.category !== "themes"),
      categories: (c.categories || []).filter((k) => k.id !== "themes"),
    });
  }

  function mount() {
    const settings = document.querySelector("#page-settings .panel");
    if (settings && !document.getElementById("themes-settings")) {
      const box = el("div", "themes-box");
      box.id = "themes-settings";
      const before = Array.from(settings.querySelectorAll("h3")).find((h) => h.textContent.trim() === "Updates");
      settings.insertBefore(box, before || null);
    }
    const panel = document.getElementById("pane-discover");
    if (panel && !document.getElementById("discover-tabs")) {
      const tabs = el("div", "ly-tabs");
      tabs.id = "discover-tabs";
      tabs.setAttribute("role", "tablist");
      for (const [id, label] of [["mods", "Mods"], ["themes", "Themes"]]) {
        const b = el("button", "ly-tab", label);
        b.type = "button";
        b.dataset.tab = id;
        b.setAttribute("role", "tab");
        b.addEventListener("click", () => showTab(id));
        tabs.append(b);
      }
      panel.insertBefore(tabs, panel.firstChild);
      const box = el("div", "themes-box");
      box.id = "themes-discover";
      box.hidden = true;
      panel.append(box);
      showTab(tab);
    }
    document.querySelectorAll('.nav[data-page="settings"]').forEach((n) => n.addEventListener("click", () => sync().then(render).catch(() => {})));
    document.addEventListener("leyline:page", (ev) => {
      const d = ev.detail || {};
      if (d.page === "mods" && d.tab === "discover") sync().then(render).catch(() => {});
    });
    render();
    sync().then(render).catch((e) => say(String(e), "bad"));
  }

  window.LeylineThemes = { apply, takeThemes, showTab, current: () => current, DEFAULT, BUILTINS: Object.keys(BUILTIN_KIND) };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
