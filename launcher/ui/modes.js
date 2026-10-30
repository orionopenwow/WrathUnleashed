// Leyline Launcher: the Modes page. Every game mode one click away, over the Rust core's modes commands
// (src-tauri/src/modes.rs), which read the site's catalog (https://play.openvanilla.app/wrath/modes.json, cached,
// with a copy built into Leyline).
//
// Loaded before app.js: it adds its own nav button (after Realms) and page, so app.js's navigation and its client
// pickers (.client-pick) pick them up like the others. PLAY follows the Home page's play setting (localStorage
// "leyline.mode"): in the browser it opens the mode's link; on the desktop it writes the pick into your 3.3.5a
// client (mode_prepare_desktop) and starts it on the official realm (app.rs "play"). The UI only ever names a
// mode id: every address is built by the core. Everything from the catalog is shown with textContent.
(function () {
  "use strict";
  const tauri = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;
  const invoke = tauri || (async () => { throw "This is a preview page: open it in the Leyline app."; });
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const KIND = { realm: "On our realm", offline: "No server", "realm-type": "Its own realm type" };
  const OFFICIAL = "play.openvanilla.app";

  // ---------------------------------------------------------------- the nav button and the page
  const nav = document.querySelector("aside nav");
  const navBtn = el("button", "nav");
  navBtn.dataset.page = "modes";
  navBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7" width="18" height="11" rx="5"/><path d="M8 10.5v4M6 12.5h4"/><circle cx="15.5" cy="11.5" r="1"/><circle cx="17.5" cy="13.8" r="1"/></svg>';
  navBtn.appendChild(document.createTextNode("Modes"));
  const realmsBtn = nav && nav.querySelector('[data-page="realms"]');
  if (realmsBtn) realmsBtn.after(navBtn); else if (nav) nav.appendChild(navBtn);

  const page = el("section", "page");
  page.id = "page-modes";
  page.innerHTML = `
    <div class="panel wide md">
      <h2>Modes</h2>
      <p class="lede">Minigames and game modes. PLAY signs you in and starts the game once your character is in the world.</p>
      <div class="toolbar">
        <label class="inline">Play with <select class="client-pick" data-for="modes"></select></label>
        <span class="md-how" id="md-how"></span>
        <button type="button" class="btn small" id="md-refresh">REFRESH</button>
      </div>
      <p class="net-line" id="md-net" aria-live="polite"></p>
      <p class="status" id="md-status" role="status"></p>
      <div class="md-list" id="md-list"></div>
    </div>`;
  const main = document.querySelector("main");
  const realmsPage = document.getElementById("page-realms");
  if (realmsPage) realmsPage.after(page); else if (main) main.appendChild(page);

  function say(text, kind) {
    const s = $("md-status");
    s.textContent = text || "";
    s.className = "status" + (kind ? " " + kind : "");
  }
  function browserMode() {
    try { return localStorage.getItem("leyline.mode") === "browser"; } catch (_) { return false; }
  }
  function renderHow() {
    $("md-how").textContent = browserMode() ? "PLAY opens your web browser (change it on Home)." : "PLAY starts your game client (change it on Home).";
  }

  function playersText(p) {
    if (p.max === null || p.max === undefined) return p.min === 1 ? "Any number of players" : `${p.min}+ players`;
    if (p.min === p.max) return p.min === 1 ? "1 player" : `${p.min} players`;
    return `${p.min}-${p.max} players`;
  }

  // ---------------------------------------------------------------- the list
  let modes = [];
  let loaded = false;

  async function load() {
    loaded = true;
    renderHow();
    $("md-net").textContent = "Loading…";
    let l;
    try { l = await invoke("modes_list"); }
    catch (e) { $("md-net").textContent = ""; say(String(e), "bad"); return; }
    modes = Array.isArray(l.modes) ? l.modes : [];
    const live = modes.filter((m) => m.status === "live").length;
    let line = `${live} to play · ${modes.length - live} coming soon`;
    if (l.builtin) line += " · offline: the list built into Leyline";
    else if (l.from_cache) line += " · offline: the last list Leyline saw";
    $("md-net").textContent = line;
    render();
  }

  function card(m) {
    const c = el("div", "realm-card md-card");
    c.dataset.mode = m.id;
    const top = el("div", "top");
    top.append(el("span", "name", m.title));
    if (m.status === "coming") top.append(el("span", "tag warn", "Coming soon"));
    c.append(top);
    const tags = el("div", "tags");
    tags.append(el("span", "tag", KIND[m.kind] || m.kind), el("span", "tag", playersText(m.players)));
    if (m.credit) tags.append(el("span", "tag gold", "Community made"));
    c.append(tags, el("p", "desc", m.line));
    if (m.credit) {
      const cr = el("p", "credit");
      cr.append(document.createTextNode(`By ${m.credit.by}${m.credit.note ? " · " + m.credit.note : ""} · ${m.credit.license}`));
      c.append(cr);
    }
    const acts = el("div", "acts");
    if (m.status === "live" && (m.kind === "realm" || m.kind === "offline")) {
      const b = el("button", "btn small md-play", "PLAY");
      b.type = "button";
      b.addEventListener("click", () => play(m, b));
      acts.append(b);
    } else if (m.status === "live" && m.kind === "realm-type") {
      const b = el("button", "btn small", "HOST IT");
      b.type = "button";
      b.title = "This mode is a realm type: host one with the Host pack, or find one on Realms.";
      b.addEventListener("click", () => {
        const go = document.querySelector('.nav[data-page="host"]');
        if (go) go.click();
      });
      acts.append(b);
    }
    const links = (m.credit ? [m.credit.source].concat(m.credit.more || []) : []);
    links.forEach((u, i) => {
      const b = el("button", "link-s", i === 0 ? "Source ›" : "More source ›");
      b.type = "button";
      b.title = u;
      b.addEventListener("click", async () => {
        try { await invoke("mode_open_credit", { id: m.id, n: i }); } catch (e) { say(String(e), "bad"); }
      });
      acts.append(b);
    });
    if (acts.childNodes.length) c.append(acts);
    return c;
  }

  function render() {
    const box = $("md-list");
    box.replaceChildren(...modes.map(card));
    if (!modes.length) box.append(el("p", "hint", "No modes listed right now."));
  }

  // ---------------------------------------------------------------- PLAY
  function pickedClient(state) {
    const sel = page.querySelector(".client-pick");
    const id = (sel && sel.value) || state.settings.selected_client;
    return state.settings.clients.find((c) => c.id === id) || null;
  }

  async function play(m, btn) {
    btn.disabled = true;
    try {
      if (m.kind === "offline" || browserMode()) {
        say(await invoke("mode_open_browser", { id: m.id }), "ok");
        return;
      }
      const state = await invoke("get_state");
      const c = pickedClient(state);
      if (!c) { say("Add your 3.3.5a game folder first (Clients), or switch Home to play in the browser.", "bad"); return; }
      if (c.build !== "3.3.5a") { say(`${m.title} runs on the 3.3.5a realm: pick a 3.3.5a client above.`, "bad"); return; }
      say("Starting…");
      const ready = await invoke("mode_prepare_desktop", { client: c.id, id: m.id });
      const started = await invoke("play", { client: c.id, realm: state.official_realm || OFFICIAL });
      say(`${started} ${ready}`, "ok");
    } catch (e) {
      say(String(e), "bad");
    } finally {
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------- start
  $("md-refresh").addEventListener("click", load);
  navBtn.addEventListener("click", () => { if (!loaded) load(); else renderHow(); });
  // app.js may open this page itself (the page remembered from last time)
  new MutationObserver(() => { if (page.classList.contains("on") && !loaded) load(); }).observe(page, { attributes: true, attributeFilter: ["class"] });

  window.LeylineModes = { load, modes: () => modes };
})();
