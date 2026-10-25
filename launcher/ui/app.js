// Leyline Launcher UI. Plain JS over the Rust core's commands (src-tauri/src/app.rs).
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

// Inside the app this is Tauri's invoke. Opened as a plain web page (a design preview) there is no core, so
// every call says so instead of failing silently.
const invoke = window.__TAURI__ && window.__TAURI__.core
  ? window.__TAURI__.core.invoke
  : async (cmd) => {
      if (cmd === "get_state") {
        return { version: "preview", settings: { clients: [], selected_client: null, selected_realm: "play.openvanilla.app",
          wine: { enabled: true, command: "wine", prefix: "" } }, official_realm: "play.openvanilla.app",
          browser_url: "https://play.openvanilla.app/wrath", windows: false, data_dir: "(app data folder)" };
      }
      throw "This is a preview page: open it in the Leyline app.";
    };

// What's new, shown on Home and on the News page. Newest first.
const NEWS = [
  { tag: "LATEST NEWS · CLIENT 20261025F", title: "CHARACTER CREATE IS BACK IN COLOUR", items: [
    "Animated race backgrounds at character select and create",
    "No more falling through ground that hasn't loaded yet",
    "Duels arena now on the realm list",
  ] },
  { tag: "LEYLINE LAUNCHER 0.1", title: "ONE LAUNCHER FOR EVERY REALM", items: [
    "Uses the game client already on your PC: 3.3.5a or 1.12.1",
    "Sets the realm for you and keeps your original realmlist as a backup",
    "Or play Wrath in your browser, with nothing to install",
  ] },
];

let state = null;
let catalogNames = [];
let realmNames = [];

function say(id, text, kind) {
  const s = $(id);
  s.textContent = text || "";
  s.className = "status" + (kind ? " " + kind : "");
}

// ------------------------------------------------------------------ window (the title bar is ours)
const win = window.__TAURI__ && window.__TAURI__.window ? window.__TAURI__.window.getCurrentWindow() : null;
$("win-min").addEventListener("click", () => win && win.minimize());
$("win-max").addEventListener("click", () => win && win.toggleMaximize());
$("win-close").addEventListener("click", () => win && win.close());

// ------------------------------------------------------------------ links (a fixed list in the core)
async function openLink(name) {
  try { await invoke("open_link", { name }); }
  catch (e) { say("play-status", String(e), "bad"); }
}
document.querySelectorAll("[data-link]").forEach((b) => b.addEventListener("click", () => openLink(b.dataset.link)));
$("tb-account").addEventListener("click", () => openLink("account"));

// ------------------------------------------------------------------ navigation
const loaders = { discover: loadMods, realms: loadRealms };
function show(page) {
  document.querySelectorAll(".nav[data-page]").forEach((b) => b.classList.toggle("on", b.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  if (loaders[page]) loaders[page]();
  try { localStorage.setItem("leyline.page", page); } catch (_) { /* storage may be off */ }
}
document.querySelectorAll(".nav[data-page]").forEach((b) => b.addEventListener("click", () => show(b.dataset.page)));
document.querySelectorAll("[data-page-go]").forEach((b) => b.addEventListener("click", () => show(b.dataset.pageGo)));

// ------------------------------------------------------------------ search
$("search-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $("search").value.trim().toLowerCase();
  if (!q) return;
  if (realmNames.some((n) => n.toLowerCase().includes(q)) || "wrathunleashed".includes(q)) {
    show("realms");
    renderNames("realms", realmNames.filter((n) => n.toLowerCase().includes(q)));
  } else {
    show("discover");
    renderNames("mods", catalogNames.filter((n) => n.toLowerCase().includes(q)));
  }
});

// ------------------------------------------------------------------ news
function renderNews() {
  const n = NEWS[0];
  $("news-tag").textContent = n.tag;
  $("news-title").textContent = n.title;
  $("news-items").replaceChildren(...n.items.map((t) => el("li", "", t)));
  $("news-full").replaceChildren(...NEWS.map((x) => {
    const d = el("div", "news-entry");
    const ul = el("ul");
    ul.replaceChildren(...x.items.map((t) => el("li", "", t)));
    d.append(el("b", "", x.title), ul);
    return d;
  }));
}

// ------------------------------------------------------------------ state
async function refresh() {
  state = await invoke("get_state");
  $("ver").textContent = "Leyline v" + state.version;
  $("data-dir").textContent = state.data_dir;
  renderPlay();
  renderClients();
  renderSettings();
}

// ------------------------------------------------------------------ realm: the chosen realm, the rows, live status
function isOfficial() { return $("play-realm").value === "official"; }
function chosenRealm() { return isOfficial() ? state.official_realm : $("play-custom").value.trim(); }
function realmLabel() { return isOfficial() ? "WrathUnleashed" : (chosenRealm() || "Another realm"); }

function saveSelection() {
  if (currentClient()) invoke("select", { client: $("play-client").value, realm: chosenRealm() }).catch(() => {});
}

let lastStatusClass = "";
function renderRealmRows() {
  const rows = $("realm-rows");
  rows.replaceChildren();
  const add = (name, official) => {
    const on = official ? isOfficial() : !isOfficial();
    const b = el("button", "realm-row" + (on ? " on" : ""));
    b.type = "button";
    const dot = el("span", "dot");
    if (on && lastStatusClass) b.classList.add(lastStatusClass);
    b.append(el("span", "letter", name.charAt(0).toUpperCase()), el("span", "name", name), dot);
    b.addEventListener("click", () => {
      $("play-realm").value = official ? "official" : "custom";
      realmChanged();
      saveSelection();
      show("play");
    });
    rows.append(b);
  };
  add("WrathUnleashed", true);
  const saved = state.settings.selected_realm;
  const custom = !isOfficial() ? chosenRealm() : (saved && saved !== state.official_realm ? saved : "");
  if (custom) add(custom, false);
}

let statusSeq = 0;
async function refreshStatus() {
  const realm = chosenRealm();
  const seq = ++statusSeq;
  const set = (cls, pill, line, detail) => {
    if (seq !== statusSeq) return;
    lastStatusClass = cls;
    $("tb-status").className = "pill " + cls;
    $("tb-status-text").textContent = pill;
    $("srv-state").className = "srv-state " + cls;
    $("srv-state-text").textContent = line;
    $("srv-detail").textContent = detail;
    document.querySelectorAll(".realm-row.on").forEach((r) => {
      r.classList.remove("is-online", "is-partial", "is-offline");
      if (cls) r.classList.add(cls);
    });
  };
  $("srv-name").textContent = realmLabel();
  if (!realm) return set("", "No realm", "NO REALM CHOSEN", "Type a realm address under Realms.");
  set("", "Checking…", "CHECKING…", realm);
  try {
    const s = await invoke("realm_status", { realm });
    const ms = s.ping_ms != null ? `${s.ping_ms} ms` : "";
    const counts = [s.players != null ? `Players: ${s.players}` : "", s.bots != null ? `Bots: ${s.bots}` : ""].filter(Boolean);
    const host = realm.includes(":") ? realm : `${realm}:3724`;
    if (s.state === "online") set("is-online", ms ? `Online  ${ms}` : "Online", ms ? `ONLINE  (${ms})` : "ONLINE", [...counts, host].join(" · "));
    else if (s.state === "partial") set("is-partial", "Partly up", "PARTLY UP", "Login answers · world server down");
    else if (s.state === "offline") set("is-offline", "Offline", "OFFLINE", "World server down");
    else set("is-partial", "No answer", "NO ANSWER", `${host} did not answer: check your connection`);
  } catch (e) {
    set("is-partial", "No answer", "STATUS UNAVAILABLE", String(e));
  }
}
setInterval(() => { if (state) refreshStatus(); }, 60000);

// ------------------------------------------------------------------ play bar
let mode = "online";
try { mode = localStorage.getItem("leyline.mode") === "browser" ? "browser" : "online"; } catch (_) { /* fine */ }

function setMode(m) {
  if (m === "solo") { say("play-status", "Solo play on this PC arrives in a later Leyline release.", "warn"); return; }
  mode = m;
  document.querySelectorAll(".mode").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === m)));
  try { localStorage.setItem("leyline.mode", m); } catch (_) { /* fine */ }
  renderPlayBar();
}
document.querySelectorAll(".mode").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

function currentClient() {
  return state.settings.clients.find((x) => x.id === $("play-client").value);
}

function renderPlay() {
  const s = state.settings;
  const sel = $("play-client");
  sel.replaceChildren();
  for (const c of s.clients) {
    const o = el("option", "", c.name);
    o.value = c.id;
    sel.append(o);
  }
  if (s.clients.length === 0) sel.append(el("option", "", "No game client yet"));
  if (s.selected_client) sel.value = s.selected_client;
  sel.disabled = s.clients.length === 0;
  $("play-empty").hidden = s.clients.length !== 0;
  $("client-change").textContent = s.clients.length ? "CHANGE WOW FOLDER" : "ADD YOUR WOW FOLDER";
  const official = !s.selected_realm || s.selected_realm === state.official_realm;
  $("play-realm").value = official ? "official" : "custom";
  $("play-custom").value = official ? "" : s.selected_realm;
  realmChanged();
}

function renderClientCard() {
  const box = $("client-now");
  box.replaceChildren();
  const c = currentClient();
  if (!c) return;
  box.append(el("b", "", c.name), el("span", "", c.build + " · Installed · your own game folder"));
}

function realmChanged() {
  $("play-custom-wrap").hidden = isOfficial();
  const c = currentClient();
  let hint = "";
  if (c && c.build === "1.12.1" && isOfficial()) hint = "The official realm runs 3.3.5a. Pick a 3.3.5a client, or another realm for this 1.12.1 client.";
  else if (c) hint = "PLAY sets this client's realmlist.wtf (your original is kept as a backup) and starts it.";
  $("play-hint").textContent = hint;
  renderClientCard();
  renderRealmRows();
  renderPlayBar();
  refreshStatus();
}

function renderPlayBar() {
  if (!state) return;
  const c = currentClient();
  const bar = $("play-headline").parentElement;
  let head = "READY TO PLAY", detail = "", warn = false;
  if (mode === "browser") {
    head = "READY · PLAYS IN YOUR BROWSER";
    detail = "WrathUnleashed · plays in your web browser, nothing to install";
  } else if (!c) {
    head = "SET UP YOUR GAME CLIENT"; warn = true;
    detail = "PLAY takes you to your game clients: point Leyline at your WoW folder";
  } else if (c.build === "1.12.1" && isOfficial()) {
    head = "THIS SERVER NEEDS 3.3.5A"; warn = true;
    detail = "WrathUnleashed runs 3.3.5a: pick a 3.3.5a client or another realm";
  } else if (!chosenRealm()) {
    head = "CHOOSE A REALM"; warn = true;
    detail = "Type the realm's address under Realms";
  } else {
    detail = `${realmLabel()} · Realmlist set automatically`;
  }
  $("play-headline").textContent = head;
  bar.classList.toggle("warn", warn);
  $("pb-detail").textContent = detail;
  $("pb-realm").textContent = mode === "browser" ? "Plays in your web browser" : realmLabel();
  $("play-caption").textContent = mode === "browser" ? "IN YOUR BROWSER" : (c ? `ONLINE  ·  ${c.name.toUpperCase()}` : "ONLINE");
}

$("play-realm").addEventListener("change", () => { realmChanged(); saveSelection(); });
$("play-custom").addEventListener("change", () => { realmChanged(); saveSelection(); });
$("play-client").addEventListener("change", () => { realmChanged(); saveSelection(); });

$("play-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (mode === "browser") {
    try { await invoke("open_browser_play"); say("play-status", "Opened the browser client.", "ok"); }
    catch (e) { say("play-status", String(e), "bad"); }
    return;
  }
  const c = currentClient();
  if (!c) { show("clients"); return; }
  const realm = chosenRealm();
  if (!realm) { show("realms"); $("play-custom").focus(); return say("play-status", "Type a realm address.", "bad"); }
  $("play-go").disabled = true;
  say("play-status", "Starting…");
  try {
    say("play-status", await invoke("play", { client: c.id, realm }), "ok");
    state = await invoke("get_state");
  } catch (e) {
    say("play-status", String(e), "bad");
  } finally {
    $("play-go").disabled = false;
  }
});

// ------------------------------------------------------------------ clients
function renderClients() {
  const list = $("cl-list");
  list.replaceChildren();
  if (state.settings.clients.length === 0) {
    list.append(el("p", "hint", "No clients yet."));
    return;
  }
  for (const c of state.settings.clients) {
    const card = el("div", "card");
    const top = el("div", "top");
    top.append(el("span", "name", c.name), el("span", "build", c.build === "3.3.5a" ? "3.3.5a · 12340" : "1.12.1 · 5875"));
    const meta = el("div", "meta");
    meta.append(el("span", "", "Folder: " + c.path));
    meta.append(el("span", "", "Realm: " + (c.realmlist || "not set")));
    if (c.locale) meta.append(el("span", "", "Locale: " + c.locale));
    const check = el("span", "", "");
    meta.append(check);
    const acts = el("div", "acts");
    const bCheck = el("button", "btn small", "CHECK");
    const bRename = el("button", "btn small", "RENAME");
    const bRemove = el("button", "btn small danger", "REMOVE");
    acts.append(bCheck, bRename, bRemove);
    card.append(top, meta, acts);
    list.append(card);

    const runCheck = async () => {
      check.className = "";
      check.textContent = "Checking…";
      try {
        const d = await invoke("check_client", { id: c.id });
        if (d.complete) {
          check.className = "ok";
          check.textContent = "Looks complete" + (d.exe_version ? ` (executable ${d.exe_version})` : "");
        } else {
          check.className = "warn";
          check.textContent = "Missing: " + d.missing.join(", ");
        }
      } catch (e) {
        check.className = "warn";
        check.textContent = String(e);
      }
    };
    bCheck.addEventListener("click", runCheck);
    // Rename in place (no prompt(): not every webview has one).
    bRename.addEventListener("click", () => {
      const input = el("input");
      input.value = c.name;
      input.maxLength = 60;
      const save = async () => {
        try { await invoke("rename_client", { id: c.id, name: input.value }); await refresh(); }
        catch (e) { say("cl-status", String(e), "bad"); }
      };
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") save();
        if (e.key === "Escape") renderClients();
      });
      input.addEventListener("blur", save);
      top.firstChild.replaceWith(input);
      input.focus();
      input.select();
    });
    // Remove takes a second click (no confirm(), same reason).
    let armed = null;
    bRemove.addEventListener("click", async () => {
      if (!armed) {
        bRemove.textContent = "CLICK AGAIN TO REMOVE";
        armed = setTimeout(() => { armed = null; bRemove.textContent = "REMOVE"; }, 3000);
        return;
      }
      clearTimeout(armed);
      try { await invoke("remove_client", { id: c.id }); await refresh(); say("cl-status", "Removed from Leyline. Your game folder was not touched.", "ok"); }
      catch (e) { say("cl-status", String(e), "bad"); }
    });
    runCheck();
  }
}

async function addClient(path) {
  if (!path) return;
  say("cl-status", "Looking at the folder…");
  try {
    const r = await invoke("add_client", { path });
    const d = r.detection;
    const how = d.detected_by === "exe_version" ? "from the executable" : "from the data files";
    const msg = `Added ${r.profile.name}, detected ${how}.` + (d.complete ? "" : " Some files are missing: " + d.missing.join(", "));
    await refresh();
    say("cl-status", msg, d.complete ? "ok" : "warn");
    $("cl-path").value = "";
  } catch (e) {
    say("cl-status", String(e), "bad");
  }
}
$("cl-pick").addEventListener("click", async () => {
  try { addClient(await invoke("pick_folder")); } catch (e) { say("cl-status", String(e), "bad"); }
});
$("cl-add").addEventListener("click", () => addClient($("cl-path").value.trim()));
$("cl-path").addEventListener("keydown", (e) => { if (e.key === "Enter") addClient($("cl-path").value.trim()); });

// ------------------------------------------------------------------ settings
function renderSettings() {
  const w = state.settings.wine;
  $("wine-on").checked = !!w.enabled;
  $("wine-cmd").value = w.command || "";
  $("wine-prefix").value = w.prefix || "";
  $("wine-note").textContent = state.windows
    ? "You are on Windows: clients start directly and these settings are not used."
    : "Clients are Windows programs. On this system Leyline starts them through Wine.";
  $("wine-set").disabled = state.windows;
}
$("set-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const wine = { enabled: $("wine-on").checked, command: $("wine-cmd").value.trim() || "wine", prefix: $("wine-prefix").value.trim() };
  try { await invoke("set_wine", { wine }); await refresh(); say("set-status", "Saved.", "ok"); }
  catch (e) { say("set-status", String(e), "bad"); }
});

// ------------------------------------------------------------------ listings (mods catalog, realm list)
function renderNames(prefix, names) {
  $(prefix + "-names").replaceChildren(...names.slice(0, 40).map((n) => el("li", "", n)));
}

function renderModTiles() {
  const box = $("mod-tiles");
  box.replaceChildren();
  const names = catalogNames.slice(0, 3);
  while (names.length < 3) names.push("");
  for (const n of names) {
    const t = el("button", "tile");
    t.type = "button";
    const txt = el("span", "tile-txt");
    txt.append(el("b", "", n || "Mod catalog"), el("i", "", n ? "In the catalog" : "Loading…"));
    t.append(el("span", "tile-ico", (n || "M").charAt(0).toUpperCase()), txt);
    t.addEventListener("click", () => show("discover"));
    box.append(t);
  }
}

async function loadListing(cmd, prefix) {
  say(prefix + "-status", "Loading…");
  try {
    const l = await invoke(cmd);
    $(prefix + "-count").textContent = String(l.count);
    const when = l.saved_at ? new Date(l.saved_at * 1000).toLocaleString() : "an earlier visit";
    if (l.from_cache) say(prefix + "-status", `Offline: showing the copy saved ${when}.`, "warn");
    else say(prefix + "-status", "Up to date.", "ok");
    if (prefix === "mods") { catalogNames = l.names; renderModTiles(); }
    else realmNames = l.names;
    renderNames(prefix, l.names);
  } catch (e) {
    $(prefix + "-count").textContent = "–";
    say(prefix + "-status", String(e), "bad");
  }
}
function loadMods() { loadListing("catalog_listing", "mods"); }
function loadRealms() { loadListing("realm_listing", "realms"); }

// ------------------------------------------------------------------ start
renderNews();
renderModTiles();
refresh().then(() => {
  setMode(mode);
  loadMods();
  loadRealms();
  let page = "play";
  try { page = localStorage.getItem("leyline.page") || "play"; } catch (_) { /* fine */ }
  show($("page-" + page) ? page : "play");
}).catch((e) => {
  document.body.prepend(el("p", "status bad", "Leyline could not start: " + e));
});
