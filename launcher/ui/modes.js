// Leyline Launcher: the Modes page. Every game mode one click away, over the Rust core's modes commands
// (src-tauri/src/modes.rs), which read the site's catalog (https://play.openvanilla.app/wrath/modes.json, cached,
// with a copy built into Leyline).
//
// Loaded before app.js: it adds its own page, so app.js's navigation and its client pickers (.client-pick) pick it up
// like the others. It has no menu item since the side menu matches the website's (owner 2026-10-30): Home's featured
// gallery, Realms › MODES and show("modes") (window.LeylineNav) open it. PLAY follows the Home page's play setting (localStorage
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
  // Key art shipped with the launcher (art/modes/), by mode id: on the mode's card and, for the featured mode, as a
  // banner on Home. A mode without art, or art that fails to load, simply has none (the card and Home as before).
  const ART = {
    "azeroth-survivors": { src: "art/modes/azeroth-survivors.webp", src2: "art/modes/azeroth-survivors@1.5x.webp", w: 483, h: 298,
      title: "Azeroth Survivors", alt: "Azeroth Survivors key art: the title over a band of heroes and a moonlit castle." },
  };
  const FEATURED = "azeroth-survivors";   // TODO(owner): the mode featured on Home
  function artImg(id, cls) {
    const a = ART[id];
    if (!a) return null;
    const img = el("img", cls);
    img.src = a.src;
    if (a.src2) img.srcset = `${a.src} 1x, ${a.src2} 1.5x`;
    img.width = a.w; img.height = a.h; img.alt = a.alt; img.decoding = "async";
    return img;
  }

  // ---------------------------------------------------------------- the page (no menu item)
  function openPage() {
    if (window.LeylineNav) { window.LeylineNav.show("modes"); return; }
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p === page));
  }
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
    catch (e) { loaded = false; $("md-net").textContent = ""; say(String(e), "bad"); return; }   // opening the page tries again
    modes = Array.isArray(l.modes) ? l.modes : [];
    const live = modes.filter((m) => m.status === "live").length;
    let line = `${live} to play · ${modes.length - live} coming soon`;
    if (l.builtin) line += " · offline: the list built into Leyline";
    else if (l.from_cache) line += " · offline: the last list Leyline saw";
    $("md-net").textContent = line;
    render();
    document.dispatchEvent(new CustomEvent("leyline:modes"));   // Home's Game modes row (home.js)
  }
  // Home asks for the list once at start (the same modes_list the page makes; the core caches it).
  function ensure() { if (!loaded) load(); }

  function card(m) {
    const c = el("div", "realm-card md-card");
    c.dataset.mode = m.id;
    const art = artImg(m.id, "md-art");
    if (art) {
      c.classList.add("has-art");
      art.addEventListener("error", () => { art.remove(); c.classList.remove("has-art"); });
      c.append(art);
    }
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
    } else if (m.status !== "live") {
      // Not playable yet: say so where PLAY would be, so it never looks like a broken button.
      const b = el("button", "btn small md-soon", "COMING SOON");
      b.type = "button";
      b.disabled = true;
      b.title = `${m.title} isn't playable yet. It shows here when it is.`;
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

  // ---------------------------------------------------------------- open one mode: this page with its card flashed (Home's
  // gallery and its Game modes row call it; home.js builds the featured mode's slide from ART and artImg).
  function show(id) {
    openPage();
    const go = () => {
      const c = document.querySelector(`#md-list .md-card[data-mode="${id}"]`);
      if (!c) return false;
      c.scrollIntoView({ block: "nearest" });
      c.classList.remove("md-flash"); void c.offsetWidth; c.classList.add("md-flash");
      return true;
    };
    if (!go()) {
      const mo = new MutationObserver(() => { if (go()) mo.disconnect(); });
      mo.observe($("md-list"), { childList: true });
      setTimeout(() => mo.disconnect(), 10000);
    }
  }

  // ---------------------------------------------------------------- start
  $("md-refresh").addEventListener("click", load);
  // whenever the page opens (show("modes"), or the page remembered from last time): load once, then keep "PLAY …" current
  new MutationObserver(() => { if (page.classList.contains("on")) { if (!loaded) load(); else renderHow(); } }).observe(page, { attributes: true, attributeFilter: ["class"] });

  window.LeylineModes = { load, ensure, modes: () => modes, show, open: openPage, ART, FEATURED, artImg, KIND, playersText };
})();
