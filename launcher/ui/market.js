// The addon marketplace in Mods › Discover: upstream addons (all.json source "upstream", src-tauri/src/upstream.rs),
// curated third-party addons the core installs straight from the author's own repo, checked file by file against
// what a person reviewed. app.js calls in with a few lines (window.LeylineMarket): keep(p) for the filters, bar() for
// the sub-category chips above the grid, card(p, c) for an upstream card. Everything else is here. It reads app.js's
// globals (catalog, installed, installProject, openUrl, cardThumb, fitsClient, firstLine) when it is called; it loads
// before app.js so the first Discover render already has it.
// The core never takes a URL from here: Install sends the project id, and the core finds the entry in its own catalog.
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  // The official realm's name (app.js HANGOUT, the one place the UI keeps it), read when needed: this file loads first.
  const realm = () => (window.LeylineApp && window.LeylineApp.HANGOUT && window.LeylineApp.HANGOUT.name) || "Wrath Unleashed";
  // The sub-categories (curate.py seeds' tags), in this order; a chip shows only when something has the tag.
  const SUBS = [
    ["full-ui", "Full interfaces"], ["unit-frames", "Unit frames"], ["raid-frames", "Raid frames"], ["action-bars", "Action bars"],
    ["nameplates", "Nameplates"], ["meters", "Meters"], ["boss-mods", "Boss fights"], ["raid-tools", "Raid tools"],
    ["auras", "Auras"], ["cooldowns", "Cooldowns"], ["combat-text", "Combat text"], ["quests", "Quests"], ["maps", "Maps"],
    ["minimap", "Minimap"], ["bags", "Bags"], ["auction", "Auction house"], ["gear", "Gear"], ["tooltips", "Tooltips"],
    ["chat", "Chat"], ["social", "Groups and friends"], ["class", "Class"], ["professions", "Professions"], ["pvp", "PvP"],
    ["skins", "Skins"], ["libraries", "Libraries"], ["quality-of-life", "Quality of life"],
  ];
  const SUB_NAME = Object.fromEntries(SUBS);
  const state = { sub: "", works: false };
  try { state.sub = localStorage.getItem("leyline.mkSub") || ""; state.works = localStorage.getItem("leyline.mkWorks") === "1"; } catch (_) { /* fine */ }

  const projects = () => (typeof catalog !== "undefined" && catalog && catalog.projects) || [];
  const mine = () => (typeof installed !== "undefined" && Array.isArray(installed) ? installed : []);
  const byId = (id) => projects().find((p) => p.id === id);
  const nameOf = (id) => (byId(id) || {}).name || id.replace(/^up:/, "");
  const works = (p) => !!(p.compat && p.compat.status === "works") || p.on_wrath === true;
  const fromWhere = (p) => (p.install && p.install.from === "mirror" ? "Hosted by Leyline" : "Installs from the author's GitHub");
  const licence = (p) => p.licence || "Licence not stated";
  const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1).replace(/\.0$/, "") + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");
  const day = (iso) => { const d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d.toLocaleDateString() : ""; };
  const save = () => { try { localStorage.setItem("leyline.mkSub", state.sub); localStorage.setItem("leyline.mkWorks", state.works ? "1" : "0"); } catch (_) { /* fine */ } };
  const rerender = () => { if (typeof renderCatalog === "function") renderCatalog(); };

  // ------------------------------------------------------------------ filters (app.js renderCatalog)
  function keep(p) {
    if (state.sub && !(p.tags || []).includes(state.sub)) return false;
    if (state.works && !works(p)) return false;
    return true;
  }
  // The words search looks at besides app.js's own (name, description, author, category).
  const words = (p) => [(p.tags || []).map((t) => SUB_NAME[t] || t).join(" "), (p.addons || []).join(" "), p.folder_name || ""].join(" ");

  function chip(label, on, click, title) {
    const b = el("button", "chip-btn" + (on ? " on" : ""), label);
    b.type = "button";
    b.setAttribute("aria-pressed", on ? "true" : "false");
    if (title) b.title = title;
    b.addEventListener("click", click);
    return b;
  }
  // The chips above the grid: the sub-categories (when Show is All or Addons and UI) and "Works on <realm>".
  function bar(cat) {
    let box = $("mk-bar");
    const grid = $("cat-grid");
    if (!box && grid) {
      box = el("div", "chips mk-bar");
      box.id = "mk-bar";
      box.setAttribute("role", "toolbar");
      box.setAttribute("aria-label", "Addon types");
      grid.before(box);
    }
    if (!box) return;
    const ups = projects().filter((p) => p.source === "upstream");
    const show = ups.length > 0 && (!cat || cat === "addons");
    box.hidden = !show;
    if (!show) {
      if (state.sub || state.works) { state.sub = ""; state.works = false; }
      box.replaceChildren();
      return;
    }
    const counts = {};
    for (const p of projects()) for (const t of p.tags || []) counts[t] = (counts[t] || 0) + 1;
    const kids = [chip("All addons", !state.sub, () => { state.sub = ""; save(); rerender(); })];
    for (const [id, label] of SUBS) {
      if (!counts[id]) continue;
      kids.push(chip(label, state.sub === id, () => { state.sub = state.sub === id ? "" : id; save(); rerender(); }, `${counts[id]} addon${counts[id] === 1 ? "" : "s"}`));
    }
    const w = chip(`Works on ${realm()}`, state.works, () => { state.works = !state.works; save(); rerender(); }, `Tried on ${realm()} by our team`);
    w.classList.add("mk-works-chip");
    kids.push(w);
    box.replaceChildren(...kids);
  }

  // ------------------------------------------------------------------ one dialog (confirms and the detail view)
  function dialog() {
    let d = $("mk-dlg");
    if (d) return d;
    d = el("dialog", "dlg mk-dlg");
    d.id = "mk-dlg";
    d.setAttribute("aria-labelledby", "mk-dlg-title");
    document.body.append(d);
    return d;
  }
  function closeDlg() { const d = $("mk-dlg"); if (d && d.open) d.close(); }
  // { title, body, list, warn, yes, no } -> Promise<boolean>
  function ask(o) {
    return new Promise((resolve) => {
      const d = dialog();
      const h = el("h3", "", o.title);
      h.id = "mk-dlg-title";
      const kids = [h];
      if (o.body) kids.push(el("p", "", o.body));
      if (o.list && o.list.length) { const ul = el("ul", "mk-list"); for (const x of o.list) ul.append(el("li", "", x)); kids.push(ul); }
      if (o.warn) kids.push(el("p", "mk-warn", o.warn));
      const row = el("div", "row");
      const yes = el("button", "btn primary", o.yes || "Continue");
      yes.type = "button";
      const no = el("button", "btn", o.no || "Cancel");
      no.type = "button";
      const done = (v) => { closeDlg(); resolve(v); };
      yes.addEventListener("click", () => done(true));
      no.addEventListener("click", () => done(false));
      d.oncancel = (ev) => { ev.preventDefault(); done(false); };
      row.append(yes, no);
      kids.push(row);
      d.replaceChildren(...kids);
      if (d.showModal) d.showModal(); else resolve(window.confirm(o.title));
    });
  }

  // ------------------------------------------------------------------ install with what it needs
  async function install(p, btn) {
    const have = new Set(mine().map((m) => m.key));
    const clash = (p.conflicts || []).filter((id) => have.has(id));
    if (clash.length) {
      await ask({ title: `${p.name} can't go in beside ${clash.map(nameOf).join(", ")}`,
        body: "They use the same addon folder. Remove the other one in Mods › Installed first.", yes: "OK", no: "Close" });
      return;
    }
    if (p.replaces_ui && !have.has(p.id)) {
      const ok = await ask({ title: `Install ${p.name}?`, body: `${p.name} replaces your whole interface.`,
        warn: "It may conflict with the Leyline UI. You can turn it off or remove it in Mods › Installed at any time.", yes: "Install it" });
      if (!ok) return;
    }
    const need = (p.requires || []).filter((id) => !have.has(id));
    if (need.length) {
      const known = need.filter((id) => byId(id) && byId(id).install);
      const ok = await ask({ title: `${p.name} needs ${need.length === 1 ? "another addon" : "other addons"}`,
        body: known.length === need.length ? "Install these first, then it:" : "Some of these are not in the marketplace; get them from their pages:",
        list: need.map(nameOf), yes: known.length ? "Install all" : "Install anyway" });
      if (!ok) return;
      for (const id of known) {
        if (typeof installProject === "function") await installProject(byId(id), el("button"));
        if (!new Set(mine().map((m) => m.key)).has(id)) return;   // it did not go in: installProject said why
      }
    }
    if (typeof installProject === "function") await installProject(p, btn || el("button"));
  }

  // ------------------------------------------------------------------ the detail view
  function fact(dl, k, v) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) return;
    dl.append(el("dt", "", k));
    const dd = el("dd");
    if (v instanceof Node) dd.append(v); else dd.textContent = Array.isArray(v) ? v.join(", ") : String(v);
    dl.append(dd);
  }
  function detail(p) {
    const d = dialog();
    const c = typeof pickedClient === "function" ? pickedClient() : null;
    const head = el("div", "mk-dhead");
    const h = el("h3", "", p.name);
    h.id = "mk-dlg-title";
    head.append(h);
    if (works(p)) head.append(el("span", "mk-badge", `Works on ${realm()}`));
    const kids = [head, el("p", "", p.description || "")];
    if (p.replaces_ui) kids.push(el("p", "mk-warn", "Replaces your whole interface. It may conflict with the Leyline UI."));
    const dl = el("dl", "mk-facts");
    const who = el("button", "link-s", p.author || "Unknown author");
    who.type = "button";
    if (p.author_url) who.addEventListener("click", () => openUrl(p.author_url)); else who.disabled = true;
    fact(dl, "Made by", who);
    fact(dl, "Licence", licence(p) + (p.licence && p.licence_source && p.licence_source !== "toc" ? ` (${p.licence_source})` : ""));
    fact(dl, "Comes from", fromWhere(p));
    fact(dl, "Version", p.version || "");
    if (p.size) fact(dl, "Size", `${mb(p.size)}, ${p.file_count || "?"} files`);
    fact(dl, "Addon folders", p.addons || []);
    fact(dl, "Needs", (p.requires || []).map(nameOf));
    fact(dl, "Can't go with", (p.conflicts || []).map(nameOf));
    if (p.blp === "author-art") fact(dl, "Art", "Uses the author's own textures, installed from the author only");
    const rv = p.review || {};
    fact(dl, "Last reviewed", rv.at ? day(rv.at) + (rv.notes ? ` · ${rv.notes}` : "") : "");
    fact(dl, `On ${realm()}`, works(p) ? `Works (checked ${day((p.compat || {}).checked_at) || "by our team"})` : "Not tried on our realm yet");
    kids.push(dl);
    kids.push(el("p", "small", "Leyline downloads it from the author, checks every file against what we reviewed, and puts it in your AddOns folder. Remove takes out exactly what it put in."));
    const row = el("div", "row");
    const m = mine().find((x) => x.key === p.id);
    const b = el("button", "btn primary");
    b.type = "button";
    if (!c) { b.textContent = "Install"; b.disabled = true; b.title = "Add a game client first"; }
    else if (typeof fitsClient === "function" && !fitsClient(p, c)) { b.textContent = "Install"; b.disabled = true; b.title = `For ${p.builds.join(" / ")} clients`; }
    else if (m && m.update) b.textContent = `Update to ${m.update}`;
    else if (m) { b.textContent = "Installed ✓"; b.disabled = true; }
    else b.textContent = "Install";
    b.addEventListener("click", async () => { closeDlg(); await install(p, el("button")); });
    const src = el("button", "btn", "Source ↗");
    src.type = "button";
    src.title = p.repo;
    src.addEventListener("click", () => openUrl(p.repo));
    const close = el("button", "btn", "Close");
    close.type = "button";
    close.addEventListener("click", closeDlg);
    row.append(b, src, close);
    kids.push(row);
    d.replaceChildren(...kids);
    d.oncancel = null;
    if (d.showModal) d.showModal();
  }

  // ------------------------------------------------------------------ the card
  function card(p, c) {
    const art = el("article", "mod-card dc-card mk-card can-open");
    art.dataset.id = p.id;
    const fits = typeof fitsClient === "function" ? fitsClient(p, c) : true;
    const thumb = typeof cardThumb === "function" ? cardThumb(p) : el("div", "dc-thumb");
    const tag = (p.tags || [])[0];
    if (c && !fits) thumb.append(el("span", "dc-tag warn", `Not for ${c.build}`));
    else if (p.replaces_ui) { const t = el("span", "dc-tag mk-ui-tag", "Whole interface"); t.title = "Replaces your whole interface; may conflict with the Leyline UI"; thumb.append(t); }
    else thumb.append(el("span", "dc-tag", SUB_NAME[tag] || "Addon"));
    if (works(p)) thumb.append(el("span", "mk-badge on-thumb", `Works on ${realm()}`));
    const m = mine().find((x) => x.key === p.id);
    if (m && m.update) { const dot = el("span", "mk-dot"); dot.title = `Update: ${m.update}`; dot.setAttribute("aria-label", "Update available"); thumb.append(dot); }
    const body = el("div", "dc-body");
    const name = el("button", "name", p.name);
    name.type = "button";
    name.title = `More about ${p.name}`;
    name.addEventListener("click", (ev) => { ev.stopPropagation(); detail(p); });
    const line = typeof firstLine === "function" ? firstLine(p.description) : p.description;
    const desc = el("p", "desc", line);
    if (p.description && p.description !== line) desc.title = p.description;
    const credit = el("p", "mk-credit");
    credit.append(el("span", "", p.author || "Unknown author"), el("span", "mk-sep", "·"), el("span", "", fromWhere(p)));
    credit.title = `${p.author || "Unknown author"} · ${licence(p)} · ${fromWhere(p)}`;
    body.append(name, desc, credit);
    const foot = el("div", "dc-foot");
    const meta = el("div", "dc-meta");
    const lic = el("span", "mk-lic" + (p.licence ? "" : " none"), p.licence || "No licence");
    lic.title = p.licence ? `Licence: ${p.licence}` : "The author states no licence: Leyline installs it from the author and never hosts a copy";
    meta.append(lic);
    const acts = el("div", "acts");
    const src = el("button", "btn small mk-src", "Source");
    src.type = "button";
    src.title = `Open ${p.repo}`;
    src.addEventListener("click", (ev) => { ev.stopPropagation(); openUrl(p.repo); });
    const b = el("button", "btn small");
    b.type = "button";
    if (!c) { b.textContent = "Install"; b.disabled = true; b.title = "Add a game client first"; }
    else if (!fits) { b.textContent = "Install"; b.disabled = true; b.title = `Made for ${p.builds.join(" / ")} clients`; }
    else if (m && m.update) { b.textContent = "Update"; b.title = `Update to ${m.update}`; b.classList.add("primary"); }
    else if (m) { b.textContent = "Installed ✓"; b.disabled = true; b.classList.add("done"); }
    else { b.textContent = "Install"; b.classList.add("primary"); }
    b.addEventListener("click", (ev) => { ev.stopPropagation(); install(p, b); });
    acts.append(src, b);
    foot.append(meta, acts);
    body.append(foot);
    art.append(thumb, body);
    art.addEventListener("click", (ev) => { if (!ev.target.closest("button, a, select, input")) detail(p); });
    return art;
  }

  window.LeylineMarket = { keep, words, bar, card, detail, install, state, SUBS };
})();
