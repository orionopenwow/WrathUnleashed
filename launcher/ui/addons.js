// The Leyline addons (src-tauri/src/addons.rs): our own in-game addons in a player's 3.3.5a game folder. Install /
// Update / Remove per client on Game Clients and in Mods › Installed ("Our addons"), the setup step when a 3.3.5a
// client is added, the offer when PLAY goes to the Dalaran Hangout without them (with "Don't ask again"), update on
// start (Settings, on by default). app.js calls in through window.LeylineAddons with a few lines; everything else is
// here. The core never takes a URL from here: it fetches the listing itself and checks every file.
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const invoke = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : async () => { throw "This is a preview page: open it in the Leyline app."; };
  const REPLACE = "ADDONS_REPLACE:";

  // TODO(owner): the Leyline addons copy (Clients, Mods, the PLAY offer, Settings)
  const COPY = {
    title: "Leyline addons",
    pitch: "Recommended for the Dalaran Hangout: game modes, golf, Edit mode, your Den.",
    safe: "They go in their own folders in your game's AddOns. Your other addons stay as they are, and Uninstall takes out exactly what Leyline put in.",
    setupTitle: "One more step: the Leyline addons",
    playTitle: "Add the Leyline addons?",
    playBody: "The Dalaran Hangout is better with them: game modes, golf, Edit mode, your Den. It takes a few seconds.",
  };

  let ov = null;            // addons_status: { pack, from_cache, error, prefs, clients: [...] }
  const busy = new Set();   // client ids with an install or removal running
  const notes = {};         // client id -> [text, kind]: the last thing that happened there

  const forClient = (id) => (ov && ov.clients.find((x) => x.client === id)) || null;
  const packVersion = () => (ov && ov.pack ? ov.pack.version : "");

  async function load(refresh) {
    try { ov = await invoke("addons_status", { refresh: !!refresh }); } catch (e) { ov = ov || { pack: null, error: String(e), prefs: { auto_update: true, dont_ask: false }, clients: [] }; }
    renderAll();
    return ov;
  }

  // ------------------------------------------------------------------ the dialog (one, reused)
  function dialog() {
    let d = $("ad-dlg");
    if (d) return d;
    d = el("dialog", "dlg ad-dlg");
    d.id = "ad-dlg";
    d.setAttribute("aria-labelledby", "ad-dlg-title");
    d.innerHTML = '<div class="ad-dlg-head"><span class="ad-mark" aria-hidden="true"></span><h3 id="ad-dlg-title"></h3></div>' +
      '<p id="ad-dlg-body"></p><ul class="ad-dlg-list" id="ad-dlg-list" hidden></ul><p class="small" id="ad-dlg-fine"></p>' +
      '<label class="check ad-dlg-ask" id="ad-dlg-ask-wrap" hidden><input type="checkbox" id="ad-dlg-ask"> Don\'t ask again</label>' +
      '<div class="row"><button type="button" class="btn primary" id="ad-dlg-yes"></button><button type="button" class="btn" id="ad-dlg-no"></button></div>';
    document.body.append(d);
    return d;
  }
  // { title, body, list, fine, yes, no, ask } -> Promise<{ yes, dontAsk }>
  function ask(o) {
    return new Promise((resolve) => {
      const d = dialog();
      $("ad-dlg-title").textContent = o.title;
      $("ad-dlg-body").textContent = o.body;
      $("ad-dlg-list").hidden = !(o.list && o.list.length);
      $("ad-dlg-list").replaceChildren(...(o.list || []).map((x) => el("li", "", x)));
      $("ad-dlg-fine").textContent = o.fine || "";
      $("ad-dlg-fine").hidden = !o.fine;
      $("ad-dlg-ask-wrap").hidden = !o.ask;
      $("ad-dlg-ask").checked = false;
      $("ad-dlg-yes").textContent = o.yes;
      $("ad-dlg-no").textContent = o.no;
      const done = (yes) => { if (d.open) d.close(); resolve({ yes, dontAsk: !!o.ask && $("ad-dlg-ask").checked }); };
      $("ad-dlg-yes").onclick = () => done(true);
      $("ad-dlg-no").onclick = () => done(false);
      d.oncancel = (ev) => { ev.preventDefault(); done(false); };
      if (d.showModal) { d.showModal(); $("ad-dlg-yes").focus(); } else resolve({ yes: false, dontAsk: false });
    });
  }

  // ------------------------------------------------------------------ install / remove
  function doneText(r, c) {
    if (r.already) return `The Leyline addons are up to date in ${c.name}.`;
    let t = `Installed the Leyline addons (${r.addons.join(", ")}) in ${c.name}.`;
    if (r.moved_aside && r.moved_aside.length) t += ` Your own copies are kept in ${r.moved_aside.join(", ")}; Uninstall puts them back.`;
    if (r.kept && r.kept.length) t += " Kept your changes: " + r.kept.join("; ") + ".";
    return t;
  }

  // Install or update; asks before moving the player's own folders of the same name aside. Returns true when in.
  async function install(c) {
    if (!c || busy.has(c.id)) return false;
    busy.add(c.id);
    notes[c.id] = ["Downloading and checking…", ""];
    renderAll();
    let ok = false;
    try {
      let r;
      try {
        r = await invoke("addons_install", { client: c.id, replace: false });
      } catch (e) {
        const t = String(e);
        if (!t.startsWith(REPLACE)) throw e;
        let info = { folders: [] };
        try { info = JSON.parse(t.slice(REPLACE.length)); } catch (_) { /* fine */ }
        const a = await ask({
          title: "You already have some of these",
          body: `${c.name} has its own copy of these addon folders. Leyline did not put them there, so it asks first.`,
          list: info.folders.map((f) => "Interface/AddOns/" + f),
          fine: "Yes moves your copies, whole, into the game folder's Leyline/backup and puts ours in. Uninstall puts yours back.",
          yes: "MOVE MINE ASIDE AND INSTALL", no: "CANCEL",
        });
        if (!a.yes) throw "Not installed: your own copies stay as they are.";
        r = await invoke("addons_install", { client: c.id, replace: true });
      }
      notes[c.id] = [doneText(r, c), "ok"];
      ok = true;
    } catch (e) {
      notes[c.id] = [String(e), "bad"];
    }
    busy.delete(c.id);
    await load(false);
    return ok;
  }

  async function remove(c) {
    if (!c || busy.has(c.id)) return;
    busy.add(c.id);
    renderAll();
    try {
      const r = await invoke("addons_remove", { client: c.id });
      let t = `Removed the Leyline addons from ${c.name}: ${r.removed_files} files.`;
      if (r.changed && r.changed.length) t += ` Left the files you changed: ${r.changed.join(", ")}.`;
      if (r.restored && r.restored.length) t += ` Put your own copies back: ${r.restored.join(", ")}.`;
      if (r.still_backed_up && r.still_backed_up.length) t += ` Still in the backup (the place is taken): ${r.still_backed_up.join(", ")}.`;
      notes[c.id] = [t, (r.changed && r.changed.length) || (r.still_backed_up && r.still_backed_up.length) ? "warn" : "ok"];
    } catch (e) { notes[c.id] = [String(e), "bad"]; }
    busy.delete(c.id);
    await load(false);
  }

  // ------------------------------------------------------------------ one client's row (Clients card, Mods)
  function statusOf(s) {
    if (!ov) return ["Checking…", ""];
    if (!s || !s.supported) return ["Not for this client.", ""];
    if (!ov.pack && !s.installed) return [ov.error ? "Can't reach the download right now. Try again later." : "Not published yet.", "warn"];
    if (s.installed && s.missing.length) return [`Some are missing (${s.missing.join(", ")}): Install puts them back.`, "warn"];
    if (s.installed && s.update) return [`Update ready: v${packVersion()}`, "gold"];
    if (s.installed) return ["Installed and up to date", "ok"];
    if (s.foreign.length) return [`Not installed. You have your own ${s.foreign.join(", ")}: Leyline asks before it moves it.`, "warn"];
    return ["Not installed", ""];
  }

  function row(c, compact) {
    const s = forClient(c.id);
    const box = el("div", "ad-row" + (compact ? " compact" : ""));
    box.dataset.client = c.id;
    const head = el("div", "ad-head");
    const mark = el("span", "ad-mark");
    mark.setAttribute("aria-hidden", "true");
    const txt = el("div", "ad-txt");
    const name = el("b", "", COPY.title);
    if (s && s.installed) {
      const chip = el("span", "rl-ver sm ad-ver", "v" + s.installed);
      name.append(chip);
    }
    txt.append(name);
    if (!compact || !(s && s.installed)) txt.append(el("span", "ad-pitch", COPY.pitch));
    head.append(mark, txt);
    const [st, kind] = statusOf(s);
    const line = el("p", "ad-state " + kind, st);
    line.setAttribute("role", "status");
    const acts = el("div", "acts ad-acts");
    const supported = s && s.supported;
    if (supported) {
      const running = busy.has(c.id);
      if (!s.installed || s.update || s.missing.length) {
        const b = el("button", "btn small" + (s.update || !s.installed ? " primary" : ""), running ? "WORKING…" : s.installed ? (s.update ? "UPDATE" : "REPAIR") : "INSTALL");
        b.disabled = running || !ov || !ov.pack;
        b.addEventListener("click", () => install(c));
        acts.append(b);
      }
      if (s.installed || (s.backups && s.backups.length)) {
        const b = el("button", "btn small danger", running && s.installed ? "WORKING…" : "UNINSTALL");
        b.title = "Takes out exactly what Leyline put in (and puts your own copies back)";
        b.disabled = running;
        b.addEventListener("click", () => remove(c));
        acts.append(b);
      }
    }
    box.append(head, line);
    const n = notes[c.id];
    if (n) {
      const p = el("p", "ad-note " + n[1], n[0]);
      box.append(p);
    }
    if (acts.childElementCount) box.append(acts);
    return box;
  }

  // ------------------------------------------------------------------ mounting points
  // Clients: app.js renderClients calls clientCard(card, c) for each card.
  function clientCard(card, c) {
    if (!c || c.build !== "3.3.5a") return;
    const slot = el("div", "ad-slot");
    slot.dataset.client = c.id;
    slot.append(row(c, false));
    const acts = card.querySelector(":scope > .acts");
    if (acts) card.insertBefore(slot, acts); else card.append(slot);
  }

  // Mods › Installed: app.js renderInstalled calls renderMods(c) with the picked client.
  let modsClient = null;
  function renderMods(c) {
    modsClient = c || null;
    const list = $("mods-list");
    if (!list) return;
    let sec = $("ad-mods");
    if (!sec) {
      sec = el("section", "ad-mods");
      sec.id = "ad-mods";
      sec.setAttribute("aria-label", "Our addons");
      const drop = $("drop");
      (drop || list).parentElement.insertBefore(sec, drop || list);   // first on the tab: above the drop zone
    }
    sec.hidden = !c || c.build !== "3.3.5a";
    if (sec.hidden) return;
    const head = el("div", "card-head ad-mods-head");
    head.append(el("span", "", "OUR ADDONS"));
    const body = el("div", "ad-mods-body");
    body.append(row(c, false));
    const names = ov && ov.pack ? ov.pack.addons : [];
    if (names.length) {
      const ul = el("ul", "ad-list");
      for (const a of names) {
        const li = el("li");
        li.append(el("b", "", a.title || a.name), el("span", "", a.name));
        ul.append(li);
      }
      body.append(ul);
    }
    body.append(el("p", "hint ad-safe", COPY.safe));
    sec.replaceChildren(head, body);
  }

  function renderAll() {
    // cards app.js drew before this file loaded
    document.querySelectorAll("#cl-list .card[data-client]").forEach((card) => {
      if (card.querySelector(".ad-slot")) return;
      const c = clients().find((x) => x.id === card.dataset.client);
      if (c) clientCard(card, c);
    });
    document.querySelectorAll(".ad-slot[data-client]").forEach((slot) => {
      const c = clients().find((x) => x.id === slot.dataset.client);
      if (c) slot.replaceChildren(row(c, false));
    });
    if ($("ad-mods")) renderMods(modsClient);
    else if ($("mods-list") && clients().length) renderMods(picked());   // Mods drew before this file loaded
    renderSettings();
  }

  function picked() {
    const st = window.LeylineApp && window.LeylineApp.state ? window.LeylineApp.state() : null;
    const all = clients();
    return (st && all.find((c) => c.id === st.settings.selected_client)) || all[0] || null;
  }
  function clients() {
    const st = window.LeylineApp && window.LeylineApp.state ? window.LeylineApp.state() : null;
    return (st && st.settings && st.settings.clients) || [];
  }

  // ------------------------------------------------------------------ the setup step (a 3.3.5a client was added)
  async function offer(profile) {
    if (!profile || profile.build !== "3.3.5a") return;
    await load(false);
    const s = forClient(profile.id);
    if (!ov.pack || !s || s.installed) return;
    const a = await ask({ title: COPY.setupTitle, body: `Install the Leyline addons in ${profile.name}? ${COPY.pitch}`, fine: COPY.safe, yes: "INSTALL", no: "NOT NOW" });
    if (a.yes) await install(profile);
  }

  // ------------------------------------------------------------------ PLAY on the official realm
  // Called before the game starts. Never stops PLAY: whatever the answer (or an error), the game starts after.
  async function beforePlay(c) {
    if (!c || c.build !== "3.3.5a") return;
    try {
      if (!ov) await load(false);
      const s = forClient(c.id);
      if (!ov.pack || !s) return;
      if (s.installed) {
        // Behind the listing and updating is on: a quick update first (a few hundred KB).
        if ((s.update || s.missing.length) && ov.prefs.auto_update) await install(c);
        return;
      }
      if (!(await invoke("addons_should_offer", { client: c.id }))) return;
      const a = await ask({ title: COPY.playTitle, body: COPY.playBody, fine: COPY.safe, yes: "INSTALL AND PLAY", no: "PLAY WITHOUT", ask: true });
      if (a.dontAsk) {
        try { ov.prefs = await invoke("addons_set_prefs", { dontAsk: true }); } catch (_) { /* fine */ }
        renderSettings();
      }
      if (a.yes) await install(c);
    } catch (_) { /* PLAY goes on */ }
  }

  // ------------------------------------------------------------------ Settings
  function renderSettings() {
    let box = $("ad-settings");
    const anchor = $("upd-status");
    if (!box && anchor) {
      box = el("div", "ad-settings");
      box.id = "ad-settings";
      box.innerHTML = '<h3>Leyline addons</h3>' +
        '<label class="check"><input type="checkbox" id="ad-set-auto"> Update the Leyline addons when Leyline starts (in every game folder that has them)</label>' +
        '<label class="check"><input type="checkbox" id="ad-set-ask"> Offer them when I press PLAY on the Dalaran Hangout without them</label>' +
        '<p class="status" id="ad-set-status" role="status"></p>';
      anchor.after(box);
      const save = async (args, okText) => {
        try { ov.prefs = await invoke("addons_set_prefs", args); $("ad-set-status").textContent = okText; $("ad-set-status").className = "status ok"; }
        catch (e) { $("ad-set-status").textContent = String(e); $("ad-set-status").className = "status bad"; }
        renderSettings();
      };
      $("ad-set-auto").addEventListener("change", (e) => save({ autoUpdate: e.target.checked }, e.target.checked ? "They update when Leyline starts." : "They update only when you press Update."));
      $("ad-set-ask").addEventListener("change", (e) => save({ dontAsk: !e.target.checked }, e.target.checked ? "PLAY offers them again." : "PLAY won't ask again."));
    }
    if (!box || !ov) return;
    $("ad-set-auto").checked = ov.prefs.auto_update !== false;
    $("ad-set-ask").checked = !ov.prefs.dont_ask;
  }

  // ------------------------------------------------------------------ start
  async function start() {
    await load(false);
    await load(true);   // the release's listing (the offline copy until it answers)
    if (!ov.prefs.auto_update) return;
    try {
      const done = await invoke("addons_auto_update");
      for (const u of done || []) {
        const c = clients().find((x) => x.id === u.client);
        if (c) notes[u.client] = u.error ? [`Couldn't update the Leyline addons: ${u.error}`, "warn"] : [`Updated the Leyline addons in ${c.name} to v${u.version}.`, "ok"];
      }
      if (done && done.length) await load(false);
    } catch (_) { /* tried again next start */ }
  }

  window.LeylineAddons = { clientCard, renderMods, offer, beforePlay, install, remove, reload: load, status: () => ov };
  setTimeout(start, 0);
})();
