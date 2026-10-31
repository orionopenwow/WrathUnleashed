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

// What's new, shown on Home and on the News page. Newest first. The website's news feed replaces these when it loads
// (loadNews: the core's news_list, news.rs, /wrath/leyline/news.json); these are the offline copy.
const NEWS = [
  { tag: "LEYLINE LAUNCHER 0.3", title: "EVERY CLIENT, EVERY SERVER", items: [
    "Finds every game client on your PC",
    "PLAY picks the client a realm needs",
    "Updates in the background, never mid-game",
  ] },
  { tag: "LATEST NEWS · CLIENT 20261025F", title: "CHARACTER CREATE IS BACK IN COLOUR", items: [
    "Animated race backgrounds at character select and create",
    "No more falling through ground that hasn't loaded yet",
    "Duels arena now on the realm list",
  ] },
  { tag: "LEYLINE LAUNCHER 0.2", title: "MODS, REALMS AND HOSTING", items: [
    "Install, update, turn off and remove Workshop mods per client, or drop your own zip",
    "Play on community Beacons from the realm list, and back to Wrath in one click",
    "Host your own realm from the Host page with the Host pack",
  ] },
  { tag: "LEYLINE LAUNCHER 0.1", title: "ONE LAUNCHER FOR EVERY REALM", items: [
    "Uses the client you already have",
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
// Never a raw error to the player (friendly.js): the error goes to the console, the player gets a plain line. A line
// the core wrote for players is shown as it is; anything technical gets the line for that place.
const OOPS = {
  "play-status": "That didn't work. Try again, or ask on the Discord.",
  "cl-status": "Leyline couldn't use that folder. Pick the folder that holds the game, or see Find your game files.",
  "cat-status": "Can't reach the Workshop. Try again.",
  "mods-status": "That mod change didn't work. Try again, or ask on the Discord.",
  "rl-status": "Can't reach the realm list right now. Try again, or ask on the Discord.",
  "host-status-line": "The host didn't answer. Try again, or see the Guide tab.",
  "set-status": "Couldn't save that. Try again.",
  "count-status": "Couldn't save that. Try again.",
  "upd-status": "Couldn't check for updates right now. Leyline tries again later.",
};
function oops(e, fallback) {
  return window.LeylineFriendly ? window.LeylineFriendly(e, fallback) : (fallback || "Something went wrong. Try again.");
}
function sayErr(id, e, kind) { say(id, oops(e, OOPS[id]), kind || "bad"); }

// ------------------------------------------------------------------ window (the title bar is ours)
const win = window.__TAURI__ && window.__TAURI__.window ? window.__TAURI__.window.getCurrentWindow() : null;
$("win-min").addEventListener("click", () => win && win.minimize());
$("win-max").addEventListener("click", () => win && win.toggleMaximize());
$("win-close").addEventListener("click", () => win && win.close());

// ------------------------------------------------------------------ links (a fixed list in the core)
async function openLink(name) {
  try { await invoke("open_link", { name }); }
  catch (e) { sayErr("play-status", e); }
}
document.querySelectorAll("[data-link]").forEach((b) => b.addEventListener("click", () => openLink(b.dataset.link)));
$("tb-account").addEventListener("click", () => openLink("account"));

// ------------------------------------------------------------------ navigation
// The side menu matches the website's (stream/hub.py nav_items): Home (play), Realms, Mods, Host, Forum, News,
// then Settings and Help. Mods is one page with tabs. The page ids from before (mymods, discover, and community,
// friends and hub, which became the Forum on 2026-10-30) still work everywhere: show() maps them to the page + tab, so a remembered page, a
// data-page-go button or a leyline:// link lands where it used to; a page with tabs alone opens its last tab. Modes has no menu item
// but is still a page (Home's featured mode, Realms › MODES, show("modes")).
const TABS = { mods: ["installed", "discover"] };
const ALIASES = { mymods: ["mods", "installed"], installed: ["mods", "installed"], discover: ["mods", "discover"],
  community: ["forum", ""], friends: ["forum", ""], hub: ["forum", ""], chat: ["forum", ""] };
const loaders = { "mods:discover": () => loadCatalog(), "mods:installed": () => loadInstalled(), realms: () => loadRealms(), host: () => loadHost(),
  forum: () => window.LeylineForum && window.LeylineForum.load() };
let currentPage = "play";
let currentTab = "";
const lastTab = {};
try { Object.assign(lastTab, JSON.parse(localStorage.getItem("leyline.tabs") || "{}")); } catch (_) { /* storage may be off */ }
function resolvePage(page, tab) {
  if (ALIASES[page]) [page, tab] = ALIASES[page];
  if (!document.getElementById("page-" + page)) return ["play", ""];
  if (!TABS[page]) return [page, ""];
  if (!TABS[page].includes(tab)) tab = TABS[page].includes(lastTab[page]) ? lastTab[page] : TABS[page][0];
  return [page, tab];
}
function show(want, noLoad, wantTab) {
  const [page, tab] = resolvePage(want, wantTab);
  currentPage = page;
  currentTab = tab;
  document.querySelectorAll(".nav[data-page]").forEach((b) => b.classList.toggle("on", b.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  if (tab) {
    lastTab[page] = tab;
    document.querySelectorAll(`.page-tab[data-group="${page}"]`).forEach((b) => {
      const on = b.dataset.tab === tab;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    });
    for (const t of TABS[page]) { const pane = $("pane-" + t); if (pane) pane.classList.toggle("on", t === tab); }
  }
  const key = tab ? page + ":" + tab : page;
  if (loaders[key] && !noLoad) loaders[key]();
  try { localStorage.setItem("leyline.page", page); localStorage.setItem("leyline.tabs", JSON.stringify(lastTab)); } catch (_) { /* storage may be off */ }
  document.dispatchEvent(new CustomEvent("leyline:page", { detail: { page, tab } }));
}
document.querySelectorAll(".nav[data-page]").forEach((b) => b.addEventListener("click", () => show(b.dataset.page)));
document.querySelectorAll("[data-page-go]").forEach((b) => b.addEventListener("click", () => show(b.dataset.pageGo)));
document.querySelectorAll(".page-tab[data-group]").forEach((b) => {
  b.addEventListener("click", () => show(b.dataset.group, false, b.dataset.tab));
  // the arrow keys move between a page's tabs (the usual tab list keys)
  b.addEventListener("keydown", (e) => {
    const tabs = TABS[b.dataset.group];
    const i = tabs.indexOf(b.dataset.tab);
    const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
    if (j === null) return;
    e.preventDefault();
    const t = tabs[(j + tabs.length) % tabs.length];
    show(b.dataset.group, false, t);
    const next = document.querySelector(`.page-tab[data-group="${b.dataset.group}"][data-tab="${t}"]`);
    if (next) next.focus();
  });
});
window.LeylineNav = { show, current: () => ({ page: currentPage, tab: currentTab }), TABS, ALIASES };

// ------------------------------------------------------------------ the backdrop behind the pages
// The website's picture (stream/hub.py BACKDROP), fetched from the site when Leyline starts, never shipped with the
// app. It sits behind the content area only (not the side bar or the menus), under the theme's wash
// (--t-backdrop-wash). Until it loads, if it fails, or with Settings › Background picture off: the plain colour.
// The window's CSP allows images from exactly this origin (tauri.conf.json img-src).
const BACKDROP_URL = "https://play.openvanilla.app/wrath/art/leyline-shot-backdrop.webp";
let backdropTried = false;
function backdropOn() {
  try { return localStorage.getItem("leyline.backdrop") !== "off"; } catch (_) { return true; }
}
function applyBackdrop() {
  const box = $("backdrop");
  if (!box) return;
  const on = backdropOn();
  if ($("set-backdrop")) $("set-backdrop").checked = on;
  if (!on) { box.classList.remove("has-pic"); return; }
  if (backdropTried) { if (box.dataset.loaded === "1") box.classList.add("has-pic"); return; }
  backdropTried = true;
  const img = new Image();
  img.decoding = "async";
  img.addEventListener("load", () => { box.dataset.loaded = "1"; if (backdropOn()) box.classList.add("has-pic"); });
  img.addEventListener("error", () => { box.dataset.loaded = "0"; box.classList.remove("has-pic"); });
  img.src = BACKDROP_URL;
}
if ($("set-backdrop")) {
  $("set-backdrop").addEventListener("change", () => {
    try { localStorage.setItem("leyline.backdrop", $("set-backdrop").checked ? "on" : "off"); } catch (_) { /* storage may be off */ }
    if ($("set-backdrop").checked && $("backdrop").dataset.loaded === "0") backdropTried = false;   // offline before: try again
    applyBackdrop();
  });
}
applyBackdrop();

// ------------------------------------------------------------------ search
$("search-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $("search").value.trim().toLowerCase();
  if (!q) return;
  if (realmNames.some((n) => n.toLowerCase().includes(q)) || "wrathunleashed".includes(q)) {
    show("realms");
  } else {
    $("cat-q").value = q;
    catFilter.cat = "";
    show("mods", false, "discover");
  }
});

// ------------------------------------------------------------------ news
// Home's hero gallery and its News row read the news too (home.js, App.news()); the News page lists every entry.
let news = NEWS;
async function loadNews() {
  let r = null;
  try { r = await invoke("news_list"); } catch (e) { console.error("[leyline] news", e); return; }   // keep the built-in posts
  const posts = r && Array.isArray(r.posts) ? r.posts.filter((p) => p && typeof p.title === "string" && p.title) : [];
  if (!posts.length) return;
  news = posts.map((p) => ({ tag: [p.tag, p.date].filter(Boolean).join(" · "), title: p.title, items: Array.isArray(p.items) ? p.items : [] }));
  renderNews();
  document.dispatchEvent(new CustomEvent("leyline:news"));   // Home's What's new slide and News row (home.js)
}
function renderNews() {
  $("news-full").replaceChildren(...news.map((x) => {
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
  renderClientPickers();
}

// ------------------------------------------------------------------ realm: the chosen realm, the rows, live status
function isOfficial() { return $("play-realm").value === "official"; }
function chosenRealm() { return isOfficial() ? state.official_realm : $("play-custom").value.trim(); }
// The official realm (launch, owner 2026-10-30; renamed "Wrath Unleashed" for now, owner 2026-10-30 23:32): where
// everyone meets in Dalaran. One name everywhere, whatever the listing calls it (the Sample Hangout, the realm's own
// name). The one place the launcher's UI names it: home.js and addons.js read it from here (window.LeylineApp.HANGOUT).
const HANGOUT = { name: "Wrath Unleashed", kind: "Official realm" };
// The official lineup after the Hangout: a record the network marks official or pinned, or one known by name until it
// does (Vanilla Remastered). Pinned under the Hangout in the play bar's realm picker.
const LINEUP_NAMES = ["vanilla remastered"];
function inLineup(r) {
  return !!r && !r.official && (!!r.pinned || !!r.lineup || LINEUP_NAMES.includes(String(r.name || "").trim().toLowerCase()));
}
function officialName() { return HANGOUT.name; }
function realmLabel() {
  if (isOfficial()) return officialName();
  const a = chosenRealm();
  if (a && a === denAddress()) return DEN.name;
  const r = realmsCache.find((x) => x.address === a);
  return r ? r.name : (a || "Another realm");
}

function saveSelection() {
  if (currentClient()) invoke("select", { client: $("play-client").value, realm: chosenRealm() }).catch(() => {});
}

let lastStatusClass = "";
// The side bar's "Your realms", dressed like the website's realm list: the realm's icon (the crystal for the official
// realm, else its initial on a colour from its name), its name, the gold client version and the live dot.
function renderRealmRows() {
  const rows = $("realm-rows");
  rows.replaceChildren();
  const add = (name, official, ver) => {
    const on = official ? isOfficial() : !isOfficial();
    const b = el("button", "realm-row" + (on ? " on" : ""));
    b.type = "button";
    const dot = el("span", "dot");
    if (on && lastStatusClass) b.classList.add(lastStatusClass);
    const txt = el("span", "rr-txt");
    txt.append(el("span", "name", name));
    if (ver) { const v = el("span", "rl-ver sm", ver); v.title = "Game client version"; txt.append(v); }
    b.append(!official && name === DEN.name && custom === denAddress() ? markIcon("den") : realmIcon(name, official, "sm"), txt, dot);
    b.title = ver ? `${name} · ${ver}` : name;
    b.addEventListener("click", () => {
      $("play-realm").value = official ? "official" : "custom";
      realmChanged();
      saveSelection();
      show("play");
    });
    rows.append(b);
  };
  add(officialName(), true, "3.3.5a");
  const saved = state.settings.selected_realm;
  const custom = !isOfficial() ? chosenRealm() : (saved && saved !== state.official_realm ? saved : "");
  if (custom) {
    const beacon = realmsCache.find((x) => x.address === custom);
    if (custom === denAddress()) add(DEN.name, false, DEN.build);   // this PC's Den (the play bar's My Den)
    else add(beacon ? beacon.name : custom, false, realmVersion(beacon));
  }
}

// Home's SERVER card: the chosen realm's icon, name and client version (the players bar comes with its status). Home has
// no SERVER or GAME CLIENT card since the play bar shows both (owner 2026-10-30): these do nothing without them.
function renderSrvHead() {
  if (!$("srv-name")) return;
  const name = realmLabel();
  $("srv-name").textContent = name;
  const r = isOfficial() ? null : realmAt(chosenRealm());
  fillRealmIcon($("srv-ic"), name, isOfficial());
  const ver = isOfficial() ? "3.3.5a" : realmVersion(r);
  $("srv-ver").hidden = !ver;
  $("srv-ver").textContent = ver || "";
}
function renderSrvBar(players) {
  const bar = $("srv-bar");
  if (!bar) return;
  if (players == null) { bar.hidden = true; return; }
  const o = isOfficial() ? (realmsCache || []).find((x) => x.official) : realmAt(chosenRealm());
  bar.hidden = false;
  bar.firstElementChild.style.width = playersFill(players, o && o.max_players) + "%";
}

let statusSeq = 0;
let officialGamedata;   // false = the official realm's server streams no game data (browser play needs the player's folder)
async function refreshStatus() {
  const realm = chosenRealm();
  const seq = ++statusSeq;
  const set = (cls, pill, line, detail) => {
    if (seq !== statusSeq) return;
    lastStatusClass = cls;
    $("tb-status").className = "pill " + cls;
    $("tb-status-text").textContent = pill;
    if ($("srv-state")) {
      $("srv-state").className = "srv-state " + cls;
      $("srv-state-text").textContent = line;
      $("srv-detail").textContent = detail;
    }
    document.querySelectorAll(".realm-row.on").forEach((r) => {
      r.classList.remove("is-online", "is-partial", "is-offline");
      if (cls) r.classList.add(cls);
    });
  };
  renderSrvHead();
  renderSrvBar(null);
  if (!realm) return set("", "No realm", "NO REALM CHOSEN", "Type a realm address under Realms.");
  set("", "Checking…", "CHECKING…", realm);
  try {
    const beacon = realmsCache.find((x) => !x.official && x.address === realm && x.status_url);
    const s = await invoke("realm_status", beacon ? { realm, statusUrl: beacon.status_url } : { realm });
    // The official realm's game data killswitch (status.json "gamedata_streaming"): BROWSER mode says what it needs.
    if (seq === statusSeq && !beacon && isOfficial()) { officialGamedata = s.gamedata_streaming; renderPlayBar(); }
    const ms = s.ping_ms != null ? `${s.ping_ms} ms` : "";
    const counts = [s.players != null ? `Players: ${s.players}` : "", s.bots != null ? `Bots: ${s.bots}` : ""].filter(Boolean);
    const host = realm.includes(":") ? realm : `${realm}:3724`;
    if (seq === statusSeq) renderSrvBar(s.state === "online" && s.players != null ? s.players : null);
    if (s.state === "online") set("is-online", ms ? `Online  ${ms}` : "Online", ms ? `ONLINE  (${ms})` : "ONLINE", (counts.length ? counts : [host]).join(" · "));
    else if (s.state === "partial") set("is-partial", "Partly up", "PARTLY UP", "Login answers · world server down");
    else if (s.state === "offline") set("is-offline", "Offline", "OFFLINE", "World server down");
    else set("is-partial", "No answer", "NO ANSWER", "The realm didn't answer: check your connection");
  } catch (e) {
    set("is-partial", "No answer", "STATUS UNAVAILABLE", oops(e, "Couldn't check the realm right now."));
  }
}
setInterval(() => { if (state) refreshStatus(); }, 60000);

// ------------------------------------------------------------------ play bar
let mode = "online";
try { mode = localStorage.getItem("leyline.mode") === "browser" ? "browser" : "online"; } catch (_) { /* fine */ }

function setMode(m) {
  if (m === "solo") { say("play-status", "Solo play on this PC arrives in a later Leyline release.", "warn"); return; }
  mode = m;
  try { localStorage.setItem("leyline.mode", m); } catch (_) { /* fine */ }
  renderPlayBar();
  document.dispatchEvent(new CustomEvent("leyline:mode", { detail: { mode: m } }));
}

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
  renderClientMenu();
  if ($("play-empty")) $("play-empty").hidden = s.clients.length !== 0;
  if ($("client-change")) $("client-change").textContent = s.clients.length ? "Change game folder" : "Add your game folder";
  const official = !s.selected_realm || s.selected_realm === state.official_realm;
  $("play-realm").value = official ? "official" : "custom";
  $("play-custom").value = official ? "" : s.selected_realm;
  realmChanged();
}

function renderClientCard() {
  const box = $("client-now");
  if (!box) return;
  box.replaceChildren();
  const c = currentClient();
  if (!c) return;
  box.append(el("b", "", c.name), el("span", "", buildLabel(c.build)));
}

// The build the chosen realm needs, when the list says ("3.3.5a" for the official realm).
function chosenRealmBuild() {
  if (isOfficial()) return "3.3.5a";
  const r = realmAt(chosenRealm());
  return r && r.build ? r.build : null;
}

function realmChanged() {
  $("play-custom-wrap").hidden = isOfficial();
  const c = currentClient();
  const need = chosenRealmBuild();
  let hint = "";
  if (c && need && c.build !== need) hint = `This realm runs ${need}. Pick a ${need} client, or another realm for this ${c.build} client.`;
  else if (c) hint = `PLAY sets this client's realm address (${BUILDS[c.build] ? BUILDS[c.build].file : "its realm file"}; your original is kept as a backup) and starts it.`;
  $("play-hint").textContent = hint;
  renderClientCard();
  renderRealmRows();
  renderPlayBar();
  refreshStatus();
}

// ------------------------------------------------------------------ the play bar's client picker: a drop-up list
// Top: Add a game folder… and Find your game files. Then the families Leyline plays that have no folder yet, greyed
// ("Not found": a click opens the Find your game files guide). Nearest the button: the folders you added, the picked
// one marked. Arrow keys, Home / End, Enter or Space, Esc; a click outside closes it. #play-client stays the model.
const FAMILIES = [["1.12.1", "Vanilla"], ["2.4.3", "TBC"], ["3.3.5a", "Wrath"]];
let menuOpen = false;
function clientVersion(c) { return c && BUILDS[c.build] ? c.build : (c && c.exe_version) || ""; }
function renderClientMenu() {
  if (!state) return;
  const c = currentClient();
  $("pb-client-name").textContent = c ? c.name : "No game client";
  $("pb-client").classList.toggle("empty", !c);
  const v = clientVersion(c);
  $("pb-client-ver").hidden = !v;
  $("pb-client-ver").textContent = v;
  $("pb-client").title = c ? `${c.name} · ${c.path}` : "Add your game folder";
  if (menuOpen) return;   // never rebuilt under the keyboard: it is built fresh each time it opens
  const menu = $("pb-menu");
  const rows = [];
  const row = (cls, label, opts) => {
    const li = el("li", "pb-opt " + cls);
    li.setAttribute("role", "option");
    li.tabIndex = -1;
    li.id = "pb-opt-" + rows.length;
    const name = el("span", "pb-opt-name", label);
    li.append(name);
    if (opts.ver) li.append(el("span", "rl-ver sm", opts.ver));
    if (opts.sub) li.append(el("span", "pb-opt-sub", opts.sub));
    li.setAttribute("aria-selected", String(!!opts.selected));
    if (opts.disabled) li.setAttribute("aria-disabled", "true");
    if (opts.title) li.title = opts.title;
    li.addEventListener("click", () => { closeClientMenu(true); opts.run(); });
    rows.push(li);
    return li;
  };
  const sep = () => { const d = el("li", "pb-sep"); d.setAttribute("role", "presentation"); return d; };
  const top = [
    row("pb-act", "Add a game folder…", { run: () => show("clients") }),
    row("pb-act", "Find your game files", { run: () => openFindFiles() }),
  ];
  const have = state.settings.clients;
  const missing = FAMILIES.filter(([b]) => !have.some((x) => x.build === b)).map(([b, name]) =>
    row("pb-missing", name, { ver: b, sub: "Not found", disabled: true, title: `No ${b} folder added yet: how to find it`, run: () => openFindFiles(name, b) }));
  const tail = (t) => ([...t].length > 30 ? "…" + [...t].slice(-29).join("") : t);   // the end of a long path, where the folder name is
  const mine = have.map((x) => row("pb-mine", x.name, { ver: clientVersion(x), sub: tail(x.path), selected: c && x.id === c.id, title: x.path,
    run: () => { $("play-client").value = x.id; realmChanged(); saveSelection(); } }));
  const parts = [top, missing, mine].filter((g) => g.length);
  menu.replaceChildren(...parts.flatMap((g, i) => (i ? [sep(), ...g] : g)));
}
function menuRows() { return [...$("pb-menu").querySelectorAll(".pb-opt")]; }
function openClientMenu() {
  if (menuOpen) return;
  if (typeof closeRealmMenu === "function") closeRealmMenu(false);
  renderClientMenu();
  menuOpen = true;
  $("pb-menu").hidden = false;
  $("pb-client").setAttribute("aria-expanded", "true");
  const rows = menuRows();
  const at = rows.find((r) => r.getAttribute("aria-selected") === "true") || rows[rows.length - 1];
  if (at) at.focus();
}
function closeClientMenu(refocus) {
  if (!menuOpen) return;
  menuOpen = false;
  $("pb-menu").hidden = true;
  $("pb-client").setAttribute("aria-expanded", "false");
  if (refocus) $("pb-client").focus();
}
$("pb-client").addEventListener("click", () => (menuOpen ? closeClientMenu(true) : openClientMenu()));
$("pb-client").addEventListener("keydown", (e) => {
  if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); openClientMenu(); }
});
$("pb-menu").addEventListener("keydown", (e) => {
  const rows = menuRows();
  const i = rows.indexOf(document.activeElement);
  let j = null;
  if (e.key === "ArrowDown") j = Math.min(rows.length - 1, i + 1);
  else if (e.key === "ArrowUp") j = Math.max(0, i - 1);
  else if (e.key === "Home") j = 0;
  else if (e.key === "End") j = rows.length - 1;
  else if (e.key === "Escape") { e.preventDefault(); closeClientMenu(true); return; }
  else if (e.key === "Tab") { closeClientMenu(false); return; }
  else if ((e.key === "Enter" || e.key === " ") && i >= 0) { e.preventDefault(); rows[i].click(); return; }
  if (j === null) return;
  e.preventDefault();
  rows[j].focus();
});
document.addEventListener("pointerdown", (e) => {
  if (menuOpen && !e.target.closest(".pb-left .pb-pick")) closeClientMenu(false);
});

// The Find your game files guide (page-findfiles), with the family asked for when a greyed row opened it.
let ffWant = null;
function openFindFiles(name, build) {
  ffWant = name ? `Looking for ${name} ${build}. ` : null;
  show("findfiles");
}
document.addEventListener("leyline:page", (e) => {
  if (e.detail.page !== "findfiles") return;
  $("ff-want").hidden = !ffWant;
  $("ff-want").textContent = ffWant || "";
  ffWant = null;   // opened any other way (Clients' link, a remembered page): the general guide
});
$("ff-pick").addEventListener("click", async () => {
  show("clients");
  try { addClient(await invoke("pick_folder")); } catch (e) { sayErr("cl-status", e); }
});
$("ff-browser").addEventListener("click", () => { setMode("browser"); show("play"); });

// ------------------------------------------------------------------ the play bar's realm picker: a drop-up list
// (owner 2026-10-30: the ONLINE / SOLO / BROWSER switch gave way to it.) Your realms first (the official one and the
// one you picked before), then the live realms on the network by players, then Play in your browser and My Den, and
// at the bottom + Make a realm and Find more realms…. Picking a realm selects it the way the side bar's
// Your realms does; browser play is a row. The same keys as the client list.
// My Den (docs/DEN.md, owner 2026-10-30; it took Solo's place): the private room to build in, hosted on this PC (the
// host kit's state/host.json profile "den", read by host_info). Hosted: the row plays it as the Host page's Play
// would, through the realm's own invite link (host_invite, then join_invite: the relay's knock, the client pointed
// at the Den), then PLAY. Not hosted: the Host page with Make my Den picked (hostconsole.js "leyline:host-ruleset").
const DEN = { name: "My Den", profile: "den", build: "3.3.5a" };
const denHosted = () => !!(kit && kit.realm && kit.realm.profile === DEN.profile);
function denAddress() {
  try { return localStorage.getItem("leyline.den") || ""; } catch (_) { return ""; }
}
// the kit as it is now (the realm picker asks each time it opens: the Den may have been made since)
async function readKit() {
  try { kit = await invoke("host_info"); } catch (_) { /* a preview page, or no kit */ }
  return kit;
}
// marks for the rows that are not a realm on the list: a house for My Den, a globe for browser play
const MARKS = {
  den: '<svg viewBox="0 0 16 16" width="14" height="14" focusable="false"><path d="M2.5 7.4 8 2.8l5.5 4.6M4 6.3v6.9h8V6.3M6.6 13.2V9.6h2.8v3.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  web: '<svg viewBox="0 0 16 16" width="14" height="14" focusable="false"><g fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="8" cy="8" r="5.6"/><path d="M2.4 8h11.2M8 2.4c1.6 1.6 2.3 3.5 2.3 5.6S9.6 12 8 13.6M8 2.4C6.4 4 5.7 5.9 5.7 8s.7 4 2.3 5.6"/></g></svg>',
};
function markIcon(kind) {
  const box = el("span", "rl-ic sm pb-mark-ic pb-" + kind + "-ic");
  box.setAttribute("aria-hidden", "true");
  box.innerHTML = MARKS[kind];
  return box;
}
const denIcon = () => markIcon("den");
// the chosen realm is this PC's Den (the address its invite gave)
const denChosen = () => mode !== "browser" && !isOfficial() && !!chosenRealm() && chosenRealm() === denAddress();
async function playDen() {
  const c = currentClient();
  const own = c && c.build === DEN.build ? c : (state && state.settings.clients.find((x) => x.build === DEN.build));
  if (!own) {
    show("clients");
    say("cl-status", `Your Den plays with a ${DEN.build} client: add your ${DEN.build} game folder, then pick My Den again.`, "warn");
    return;
  }
  say("play-status", "Opening your Den…");
  let link = null;
  try { link = await invoke("host_invite"); } catch (_) { /* no kit */ }
  if (!link) { say("play-status", "Your Den has no invite link yet: start it once on the Host page.", "warn"); return; }
  let j;
  try { j = await invoke("join_invite", { client: own.id, link }); }
  catch (e) { say("play-status", oops(e, "Your Den didn't answer.") + " Is your Den running? Start it on the Host page.", "bad"); return; }
  try { localStorage.setItem("leyline.den", j.address); } catch (_) { /* the bar then shows the address */ }
  $("play-client").value = own.id;
  $("play-realm").value = "custom";
  $("play-custom").value = j.address;
  if (mode === "browser") setMode("online");
  realmChanged();
  saveSelection();
  $("play-form").requestSubmit();
}
function makeDen() {
  show("host");
  document.dispatchEvent(new CustomEvent("leyline:host-ruleset", { detail: { profile: DEN.profile } }));
}
let rmenuOpen = false;
const realmRowsOf = (m) => [...m.querySelectorAll(".pb-opt")];
function pickRealm(r) {
  $("play-realm").value = r.official ? "official" : "custom";
  if (!r.official) $("play-custom").value = r.address || "";
  if (mode === "browser") setMode("online");
  realmChanged();
  saveSelection();
}
function renderRealmMenu() {
  const menu = $("pb-rmenu");
  const rows = [];
  const row = (cls, label, opts) => {
    const li = el("li", "pb-opt " + cls);
    li.setAttribute("role", "option");
    li.tabIndex = -1;
    li.id = "pb-ropt-" + rows.length;
    if (opts.icon) li.append(opts.icon);
    li.append(el("span", "pb-opt-name", label));
    if (opts.kind) li.append(el("span", "pb-opt-kind", opts.kind));
    if (opts.ver) li.append(el("span", "rl-ver sm", opts.ver));
    if (opts.sub) li.append(el("span", "pb-opt-sub" + (opts.subCls ? " " + opts.subCls : ""), opts.sub));
    li.setAttribute("aria-selected", String(!!opts.selected));
    if (opts.disabled) li.setAttribute("aria-disabled", "true");
    if (opts.title) li.title = opts.title;
    li.addEventListener("click", () => { if (opts.disabled) return; closeRealmMenu(true); opts.run(); });
    rows.push(li);
    return li;
  };
  const head = (text) => { const h = el("li", "pb-head", text); h.setAttribute("role", "presentation"); return h; };
  const sep = () => { const d = el("li", "pb-sep"); d.setAttribute("role", "presentation"); return d; };
  const online = mode !== "browser";
  const here = chosenRealm();
  const players = (r) => (!r ? "" : r.state !== "live" ? "Offline" : r.players == null ? "Online" : `${r.players} playing`);
  const realmRow = (r) => row("pb-realm-opt" + (r.state === "live" ? "" : " off"), r.name, {
    icon: realmIcon(r.name, r.official, "sm"), ver: r.official ? "3.3.5a" : realmVersion(r), sub: players(r), subCls: r.state === "live" ? "live" : "",
    kind: r.official ? HANGOUT.kind : "",
    selected: online && (r.official ? isOfficial() : !isOfficial() && r.address === here), title: r.tagline || r.name, run: () => pickRealm(r) });
  // the official lineup first (launch): the official realm (HANGOUT) pinned at the top, labelled, then Vanilla Remastered when
  // its record is on the list
  const off = (realmsCache || []).find((x) => x.official) || { official: true, name: officialName(), state: "live", players: null };
  const lineup = (realmsCache || []).filter((r) => inLineup(r) && r.address && !hiddenBuild(r.build));
  const official = [realmRow(off), ...lineup.map(realmRow)];
  const mine = [];
  const saved = !isOfficial() ? here : (state.settings.selected_realm && state.settings.selected_realm !== state.official_realm ? state.settings.selected_realm : "");
  const savedRealm = saved ? realmAt(saved) : null;
  if (saved && saved === denAddress() && denHosted()) { /* the Den: its own row below */ }
  else if (saved && savedRealm && !inLineup(savedRealm)) mine.push(realmRow(savedRealm));
  else if (saved && !savedRealm) mine.push(row("pb-realm-opt", saved, { icon: realmIcon(saved, false, "sm"), selected: online && !isOfficial(), sub: "Your address", run: () => pickRealm({ official: false, address: saved }) }));
  const live = (realmsCache || []).filter((r) => !r.official && !inLineup(r) && r.state === "live" && r.address && r.address !== saved && !hiddenBuild(r.build))
    .sort((x, y) => (y.players || 0) - (x.players || 0)).slice(0, 6).map(realmRow);
  const other = [
    row("pb-browser", "Play in your browser", { icon: markIcon("web"), sub: "Nothing to install", selected: !online, run: () => setMode("browser") }),
    denHosted()
      ? row("pb-den", DEN.name, { icon: denIcon(), ver: DEN.build, sub: "On this PC", selected: online && !isOfficial() && !!here && here === denAddress(),
        title: "Your Den on this PC: play it", run: playDen })
      : row("pb-den", DEN.name, { icon: denIcon(), sub: "Make your Den", title: "A private room to build in: you and the friends you invite", run: makeDen }),
  ];
  const acts = [
    row("pb-act", "+ Make a realm", { run: () => show("host") }),
    row("pb-act", "Find more realms…", { run: () => show("realms") }),
  ];
  const parts = [[head("Official"), ...official]];
  if (mine.length) parts.push([head("Your realms"), ...mine]);
  if (live.length) parts.push([head("On the network"), ...live]);
  parts.push(other, acts);
  menu.replaceChildren(...parts.flatMap((g, i) => (i ? [sep(), ...g] : g)));
}
function openRealmMenu() {
  if (rmenuOpen) return;
  closeClientMenu(false);
  renderRealmMenu();
  rmenuOpen = true;
  $("pb-rmenu").hidden = false;
  $("pb-realm-btn").setAttribute("aria-expanded", "true");
  const focusPicked = () => {
    const rows = realmRowsOf($("pb-rmenu"));
    const at = rows.find((r) => r.getAttribute("aria-selected") === "true") || rows[0];
    if (at) at.focus();
  };
  focusPicked();
  // My Den: hosted on this PC or not, as the kit says now (the row changes only when that changed)
  const had = denHosted();
  readKit().then(() => {
    if (!rmenuOpen || denHosted() === had) return;
    const i = realmRowsOf($("pb-rmenu")).indexOf(document.activeElement);
    renderRealmMenu();
    const rows = realmRowsOf($("pb-rmenu"));
    if (i >= 0 && rows[i]) rows[i].focus(); else focusPicked();
  });
}
function closeRealmMenu(refocus) {
  if (!rmenuOpen) return;
  rmenuOpen = false;
  $("pb-rmenu").hidden = true;
  $("pb-realm-btn").setAttribute("aria-expanded", "false");
  if (refocus) $("pb-realm-btn").focus();
}
$("pb-realm-btn").addEventListener("click", () => (rmenuOpen ? closeRealmMenu(true) : openRealmMenu()));
$("pb-realm-btn").addEventListener("keydown", (e) => {
  if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); openRealmMenu(); }
});
$("pb-rmenu").addEventListener("keydown", (e) => {
  const rows = realmRowsOf($("pb-rmenu"));
  const i = rows.indexOf(document.activeElement);
  let j = null;
  if (e.key === "ArrowDown") j = Math.min(rows.length - 1, i + 1);
  else if (e.key === "ArrowUp") j = Math.max(0, i - 1);
  else if (e.key === "Home") j = 0;
  else if (e.key === "End") j = rows.length - 1;
  else if (e.key === "Escape") { e.preventDefault(); closeRealmMenu(true); return; }
  else if (e.key === "Tab") { closeRealmMenu(false); return; }
  else if ((e.key === "Enter" || e.key === " ") && i >= 0) { e.preventDefault(); rows[i].click(); return; }
  if (j === null) return;
  e.preventDefault();
  rows[j].focus();
});
document.addEventListener("pointerdown", (e) => {
  if (rmenuOpen && !e.target.closest(".pb-mid .pb-pick")) closeRealmMenu(false);
});

function renderPlayBar() {
  if (!state) return;
  const c = currentClient();
  const bar = $("play-headline").parentElement;   // the status line under the realm's name
  let head = "READY TO PLAY", detail = "", warn = false;
  if (mode === "browser" && officialGamedata === false) {
    head = "BROWSER PLAY · NEEDS YOUR GAME FOLDER"; warn = true;
    detail = "The browser will ask for your game folder (it stays on your PC)";
  } else if (mode === "browser") {
    head = "READY · NOTHING TO INSTALL";
  } else if (!c) {
    // no game folder: PLAY opens Find your game files (which has browser play too)
    head = "ADD YOUR GAME FOLDER"; warn = true;
    detail = "PLAY shows where to find it, or play in your browser";
  } else if (chosenRealmBuild() && c.build !== chosenRealmBuild()) {
    const need = chosenRealmBuild();
    head = `THIS SERVER NEEDS ${need.toUpperCase()}`; warn = true;
    const other = state.settings.clients.find((x) => x.build === need);
    detail = other ? `Pick ${other.name}` : `Add a ${need} folder`;
  } else if (!chosenRealm()) {
    head = "CHOOSE A REALM"; warn = true;
    detail = "Type the realm's address under Realms";
  } else {
    detail = "";
  }
  $("play-headline").textContent = head;
  bar.classList.toggle("warn", warn);
  $("pb-detail").textContent = detail;
  $("pb-realm").textContent = mode === "browser" ? "In your browser" : realmLabel();
  $("pb-realm-btn").title = mode === "browser" ? "Plays in your browser: choose a realm instead" : `${realmLabel()}: choose another realm`;
  // the realm's icon and client version beside its name (none in the browser)
  const official = isOfficial();
  const rv = mode === "browser" ? null : official ? "3.3.5a" : denChosen() ? DEN.build : realmVersion(realmAt(chosenRealm()));
  $("pb-realm-ver").hidden = !rv;
  $("pb-realm-ver").textContent = rv || "";
  $("pb-realm-ic").hidden = mode === "browser";
  if (mode !== "browser") fillRealmIcon($("pb-realm-ic"), realmLabel(), official);
  $("pb-realm-ic").classList.toggle("pb-mark-ic", denChosen());
  if (denChosen()) $("pb-realm-ic").innerHTML = MARKS.den;
  if (rmenuOpen) renderRealmMenu();
  renderClientMenu();
  $("play-caption").textContent = mode === "browser" ? "IN YOUR BROWSER" : (c ? `ONLINE  ·  ${c.name.toUpperCase()}` : "NO GAME FOLDER YET");
}

$("play-realm").addEventListener("change", () => { realmChanged(); saveSelection(); });
$("play-custom").addEventListener("change", () => { realmChanged(); saveSelection(); });
$("play-client").addEventListener("change", () => { realmChanged(); saveSelection(); });

$("play-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (mode === "browser") {
    try { await invoke("open_browser_play"); say("play-status", "Opened the browser client.", "ok"); }
    catch (e) { sayErr("play-status", e); }
    return;
  }
  const c = currentClient();
  if (!c) { openFindFiles(); return; }   // no game folder yet: where to find one (and browser play)
  const realm = chosenRealm();
  if (!realm) { show("realms"); $("play-custom").focus(); return say("play-status", "Type a realm address.", "bad"); }
  $("play-go").disabled = true;
  try {
    if (window.LeylineAddons && isOfficial()) await window.LeylineAddons.beforePlay(c);   // offers the Leyline addons (addons.js)
    say("play-status", "Starting…");
    say("play-status", await invoke("play", { client: c.id, realm }), "ok");
    state = await invoke("get_state");
  } catch (e) {
    sayErr("play-status", e);
  } finally {
    $("play-go").disabled = false;
  }
});

// ------------------------------------------------------------------ clients
function renderClients() {
  const list = $("cl-list");
  list.replaceChildren();
  if (state.settings.clients.length === 0) {
    // the empty state: where to look first
    const p = el("p", "hint cl-empty", "No game folder yet. ");
    const go = el("button", "link", "Find your game files ›");
    go.type = "button";
    go.addEventListener("click", () => openFindFiles());
    p.append(go);
    list.append(p);
    return;
  }
  for (const c of state.settings.clients) {
    const card = el("div", "card");
    const top = el("div", "top");
    top.append(el("span", "name", c.name), el("span", "build", offeredBuild(c.build) ? c.build : "other build"));
    const tags = el("div", "tags");
    if (buildTag(c.build) === "other") tags.append(el("span", "tag warn", "Realms only, no mods"));
    const meta = el("div", "meta");
    meta.append(el("span", "", "Folder: " + c.path));
    const check = el("span", "", "");
    meta.append(check);
    // the technical lines, for whoever is helping: behind Details
    const more = el("details", "cl-more");
    more.append(el("summary", "", "Details"));
    const tech = el("div", "meta");
    if (buildTag(c.build) === "other") tech.append(el("span", "", `Build: ${c.exe_version || "unknown"}`));
    else {
      tech.append(el("span", "", `Build: ${buildLabel(c.build)}`));
      tech.append(el("span", "", `Addons: Interface ${{"1.12.1": "11200", "2.4.3": "20400", "3.3.5a": "30300", "4.3.4": "40300", "5.4.8": "50400"}[c.build]}`));
    }
    if (BUILDS[c.build]) tech.append(el("span", "", `Realm address file: ${BUILDS[c.build].file}`));
    tech.append(el("span", "", "Realm: " + (c.realmlist || "not set")));
    if (c.locale) tech.append(el("span", "", "Locale: " + c.locale));
    more.append(tech);
    const acts = el("div", "acts");
    const bCheck = el("button", "btn small", "Check");
    const bRename = el("button", "btn small", "Rename");
    const bRemove = el("button", "btn small danger", "Remove");
    acts.append(bCheck, bRename, bRemove);
    card.append(top, tags, meta, more, acts);
    card.dataset.client = c.id;
    if (window.LeylineAddons) window.LeylineAddons.clientCard(card, c);   // the Leyline addons row (addons.js)
    list.append(card);

    const runCheck = async () => {
      check.className = "";
      check.textContent = "Checking…";
      try {
        const d = await invoke("check_client", { id: c.id });
        if (d.complete) {
          check.className = "ok";
          check.textContent = "Looks complete";
          if (d.exe_version) check.title = `Executable ${d.exe_version}`;   // the technical part, on hover
        } else {
          check.className = "warn";
          check.textContent = "Missing: " + d.missing.join(", ");
        }
      } catch (e) {
        check.className = "warn";
        check.textContent = oops(e, "Couldn't check this folder right now.");
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
        catch (e) { sayErr("cl-status", e); }
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
        bRemove.textContent = "Click again to remove";
        armed = setTimeout(() => { armed = null; bRemove.textContent = "Remove"; }, 3000);
        return;
      }
      clearTimeout(armed);
      try { await invoke("remove_client", { id: c.id }); await refresh(); say("cl-status", "Removed from Leyline. Your game folder was not touched.", "ok"); }
      catch (e) { sayErr("cl-status", e); }
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
    let msg = `Added ${r.profile.name}: ${d.build_label}, detected ${how}.`;
    if (d.build === "other") msg += " Leyline does not know this build: you can play realms with it, but it offers no mods for it.";
    if (!d.complete) msg += " Some files are missing: " + d.missing.join(", ");
    await refresh();
    say("cl-status", msg, d.complete ? "ok" : "warn");
    $("cl-path").value = "";
    if (window.LeylineAddons) window.LeylineAddons.offer(r.profile);   // a 3.3.5a client: the Leyline addons step (addons.js)
  } catch (e) {
    sayErr("cl-status", e);
  }
}
$("cl-pick").addEventListener("click", async () => {
  try { addClient(await invoke("pick_folder")); } catch (e) { sayErr("cl-status", e); }
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
  // on Windows clients start directly: no Wine settings to show (nor their Save)
  $("wine-set").hidden = !!state.windows;
  $("wine-set").disabled = !!state.windows;
  if ($("set-save")) $("set-save").hidden = !!state.windows;
  $("set-count").checked = state.settings.count_installs !== false;
}
$("set-count").addEventListener("change", async () => {
  const on = $("set-count").checked;
  try {
    await invoke("set_count_installs", { on });
    state.settings.count_installs = on;
    say("count-status", on ? "Your installs count toward the rankings." : "Your installs are not counted.", "ok");
  } catch (e) { $("set-count").checked = !on; sayErr("count-status", e); }
});
$("set-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const wine = { enabled: $("wine-on").checked, command: $("wine-cmd").value.trim() || "wine", prefix: $("wine-prefix").value.trim() };
  try { await invoke("set_wine", { wine }); await refresh(); say("set-status", "Saved.", "ok"); }
  catch (e) { sayErr("set-status", e); }
});

// ------------------------------------------------------------------ the client pickers on Mods, Discover, Realms
// They all follow the one selected client (the play bar's).
function renderClientPickers() {
  document.querySelectorAll(".client-pick").forEach((sel) => {
    sel.replaceChildren();
    for (const c of state.settings.clients) {
      const o = el("option", "", `${c.name} · ${c.build}`);
      o.value = c.id;
      sel.append(o);
    }
    if (!state.settings.clients.length) sel.append(el("option", "", "No game client yet"));
    sel.disabled = !state.settings.clients.length;
    if (state.settings.selected_client) sel.value = state.settings.selected_client;
  });
}
function pickedClient() {
  return state.settings.clients.find((c) => c.id === state.settings.selected_client) || state.settings.clients[0] || null;
}
document.querySelectorAll(".client-pick").forEach((sel) => sel.addEventListener("change", async () => {
  state.settings.selected_client = sel.value;
  $("play-client").value = sel.value;
  renderClientPickers();
  realmChanged();
  saveSelection();
  const page = sel.dataset.for;
  if (page === "mods") loadInstalled();
  if (page === "discover") { await loadInstalled(true); renderCatalog(); }
}));
function needClient(statusId) {
  const c = pickedClient();
  if (!c) { say(statusId, "Add your game folder first: pick Add a game folder… in the play bar.", "bad"); return null; }
  return c;
}
// The builds Leyline knows (clients.rs). "other" is any build it does not: it plays realms, but takes no mods.
const BUILDS = {
  "1.12.1": { num: 5875, tag: "1.12", file: "realmlist.wtf" },
  "2.4.3": { num: 8606, tag: "2.4.3", file: "Data\\<locale>\\realmlist.wtf" },
  "3.3.5a": { num: 12340, tag: "3.3.5a", file: "Data\\<locale>\\realmlist.wtf" },
  "4.3.4": { num: 15595, tag: "4.3.4", file: "WTF\\Config.wtf" },
  "5.4.8": { num: 18414, tag: "5.4.8", file: "WTF\\Config.wtf" },
};
// The newest build offered (clients.rs MAX_OFFERED_BUILD). Hidden by the owner on 2026-10-30: 4.3.4 and 5.4.8 are
// not shown for now. Set this back to 18414 (or window.LEYLINE_ALL_CLIENTS = true) to show them again.
const MAX_OFFERED_BUILD = 12340;
const offeredBuild = (b) => !!BUILDS[b] && (window.LEYLINE_ALL_CLIENTS === true || BUILDS[b].num <= MAX_OFFERED_BUILD);
const hiddenBuild = (b) => !!BUILDS[b] && !offeredBuild(b);
const buildLabel = (b) => (offeredBuild(b) ? `${b} · ${BUILDS[b].num}` : "other build");
const buildTag = (b) => (offeredBuild(b) ? BUILDS[b].tag : "other");
const fitsClient = (p, c) => !c || (buildTag(c.build) !== "other" && (!p.builds.length || p.builds.includes("any") || p.builds.includes(buildTag(c.build))));
// The listed realm at this address, if any (its build and server).
const realmAt = (addr) => realmsCache.find((x) => x.address === addr) || null;
const clientFits = (r, c) => !r || !r.build || (c && c.build === r.build);
const clientFor = (r) => {
  const c = pickedClient();
  if (clientFits(r, c)) return c;
  return state.settings.clients.find((x) => clientFits(r, x)) || null;
};

// ------------------------------------------------------------------ opening listed pages
async function openUrl(url) {
  try { await invoke("open_url", { url }); } catch (e) { sayErr("play-status", e); }
}
function linkBtn(label, url) {
  const b = el("button", "link-s", label);
  b.type = "button";
  b.addEventListener("click", () => openUrl(url));
  return b;
}

// ------------------------------------------------------------------ Discover: the Workshop catalog
let catalog = { categories: [], projects: [] };
let installed = [];          // the picked client's mods
const catFilter = { cat: "", sort: "hot", kind: "" };
try { catFilter.sort = localStorage.getItem("leyline.catSort") || "hot"; } catch (_) { /* storage may be off */ }
// The hub's rankings (rankings.rs: mods.json): the catalog ids in the chosen order, and each one's numbers.
let ranked = null;
let linkedId = "";            // a project a leyline:// link asked for: shown highlighted
async function loadRanks(refresh) {
  try {
    ranked = await invoke("mods_ranked", { sort: catFilter.sort, kind: catFilter.kind, client: null, refresh: !!refresh });
  } catch (_) { ranked = null; }
}
// Without rankings (offline on first start): the kind from the catalog's own fields, like rankings.rs kind_of.
const kindOf = (p) => (p.category === "sandbox" ? "mode" : (p.kind === "ui" || p.category === "addons") ? "addon" : "mod");
const kindFor = (p) => (ranked && ranked.metrics && ranked.metrics[p.id] && ranked.metrics[p.id].kind) || kindOf(p);
// Kinds sit in the one Show menu with the categories (themes have their own tab, Discover › Themes).
const KINDS = [["addon", "Addons"], ["mod", "Realm mods and tools"], ["mode", "Game modes"]];
const SORTS = ["hot", "rising", "top", "installs", "installs30", "new", "updated"];
if (!SORTS.includes(catFilter.sort)) catFilter.sort = "hot";
function renderSorts() {
  $("cat-sort").value = catFilter.sort;
}
$("cat-sort").addEventListener("change", async () => {
  catFilter.sort = $("cat-sort").value;
  try { localStorage.setItem("leyline.catSort", catFilter.sort); } catch (_) { /* fine */ }
  await loadRanks(false);
  renderCatalog();
});
// The Show menu: All, the kinds and the categories that have something to show (with the client filter on, for this client).
function renderShowMenu(pool) {
  const sel = $("cat-cat");
  const want = catFilter.kind ? "kind:" + catFilter.kind : catFilter.cat ? "cat:" + catFilter.cat : "";
  const kinds = {}, cats = {};
  for (const p of pool) { kinds[kindFor(p)] = (kinds[kindFor(p)] || 0) + 1; cats[p.category] = (cats[p.category] || 0) + 1; }
  const opt = (v, label, n) => { const o = el("option", "", n === undefined ? label : `${label} (${n})`); o.value = v; return o; };
  const opts = [opt("", "All", pool.length)];
  const kg = el("optgroup"); kg.label = "Kind";
  for (const [k, label] of KINDS) if (kinds[k] || want === "kind:" + k) kg.append(opt("kind:" + k, label, kinds[k] || 0));
  const cg = el("optgroup"); cg.label = "Category";
  for (const k of catalog.categories) if (cats[k.id] || want === "cat:" + k.id) cg.append(opt("cat:" + k.id, k.name, cats[k.id] || 0));
  if (kg.children.length > 1) opts.push(kg);
  if (cg.children.length) opts.push(cg);
  sel.replaceChildren(...opts);
  sel.value = want;
  if (sel.value !== want) sel.value = "";
}
$("cat-cat").addEventListener("change", async () => {
  const v = $("cat-cat").value;
  const kind = v.startsWith("kind:") ? v.slice(5) : "";
  catFilter.cat = v.startsWith("cat:") ? v.slice(4) : "";
  if (kind !== catFilter.kind) { catFilter.kind = kind; await loadRanks(false); }
  renderCatalog();
});

let catFailed = false;   // the Workshop could not be read and there is nothing to show: the status line says so, alone
async function loadCatalog(quiet) {
  if (!quiet) say("cat-status", "Loading the Workshop…");
  try {
    catalog = await invoke("mods_catalog");
    if (window.LeylineThemes) catalog = window.LeylineThemes.takeThemes(catalog); // themes.js: theme packs go under Discover › Themes
    catalogNames = catalog.projects.map((p) => p.name);
    const when = catalog.saved_at ? new Date(catalog.saved_at * 1000).toLocaleString() : "an earlier visit";
    if (catalog.from_cache) say("cat-status", `Offline: showing the Workshop as it was ${when}.`, "warn");
    else say("cat-status", catalog.projects.length ? `${catalog.projects.length} projects in the Workshop.` : "", "ok");
    catFailed = false;
  } catch (e) {
    // one line, no count (owner audit 2026-10-30): the grid stays empty under it
    console.error("[leyline] workshop", e);
    catFailed = !catalog.projects.length;
    say("cat-status", "Can't reach the Workshop. Try again.", "bad");
  }
  await loadRanks(true);
  renderModTiles();
  document.dispatchEvent(new CustomEvent("leyline:catalog"));  // Home's Workshop spotlight and Mods to try (home.js)
  await loadInstalled(true);
  renderCatalog();
}

function renderCatalog() {
  const c = pickedClient();
  const q = $("cat-q").value.trim().toLowerCase();
  const fitOnly = $("cat-fit").checked;
  $("pane-discover").classList.toggle("fit-off", !fitOnly);
  renderSorts();
  renderShowMenu(catalog.projects.filter((p) => !fitOnly || !c || fitsClient(p, c)));
  const grid = $("cat-grid");
  if (window.LeylineMarket) window.LeylineMarket.bar(catFilter.cat);   // sub-category chips above the grid (market.js)
  grid.replaceChildren();
  let ordered = catalog.projects;
  if (ranked && ranked.ids) {
    const byId = new Map(catalog.projects.map((p) => [p.id, p]));
    ordered = ranked.ids.map((id) => byId.get(id)).filter(Boolean);
  } else if (catFilter.kind) {
    ordered = catalog.projects.filter((p) => kindOf(p) === catFilter.kind);
  }
  const list = ordered.filter((p) => {
    if (catFilter.cat && p.category !== catFilter.cat) return false;
    if (fitOnly && c && !fitsClient(p, c)) return false;
    if (window.LeylineMarket && !window.LeylineMarket.keep(p)) return false;   // the addon chips (market.js)
    if (q && !(`${p.name} ${p.description} ${p.author} ${p.category} ${window.LeylineMarket ? window.LeylineMarket.words(p) : ""}`.toLowerCase().includes(q))) return false;
    return true;
  });
  if (!list.length) {
    if (catFailed) return;   // "Can't reach the Workshop. Try again." is already the one line
    const cat = catalog.categories.find((k) => k.id === catFilter.cat);
    grid.append(el("p", "hint dc-empty", catalog.projects.length
      ? (cat && !catalog.projects.some((p) => p.category === cat.id) ? `No mods in ${cat.name} yet. Make the first one: see Make a mod.` : "Nothing matches.")
      : "The Workshop list is not here yet."));
    return;
  }
  for (const p of list) grid.append(projectCard(p, c));
}

// Rating stars on a card's picture (shown on hover and focus). Rating needs the Leyline sign-in on Home (the
// same website sign-in).
function rateStars(p) {
  const stars = el("span", "stars");
  stars.setAttribute("role", "group");
  stars.setAttribute("aria-label", `Rate ${p.name}`);
  for (let n = 1; n <= 5; n++) {
    const b = el("button", "", "★");
    b.type = "button";
    b.title = `${n} star${n > 1 ? "s" : ""}`;
    b.setAttribute("aria-label", `Rate ${n} star${n > 1 ? "s" : ""}`);
    b.addEventListener("click", (ev) => { ev.stopPropagation(); rateProject(p, n, stars); });
    stars.append(b);
  }
  return stars;
}
async function rateProject(p, n, box) {
  try {
    const r = await invoke("mod_rate", { project: p.id, stars: n });
    box.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i < n));
    if (ranked && ranked.metrics && ranked.metrics[p.id] && r && r.rating) ranked.metrics[p.id].rating = r.rating;
    say("cat-status", `Thanks: you rated ${p.name} ${n} star${n > 1 ? "s" : ""}.`, "ok");
  } catch (e) {
    say("cat-status", String(e) === "signed_out" ? "Sign in (top right) to rate mods: the same sign-in as the website." : oops(e, "Couldn't save your rating. Try again."), "bad");
  }
}

// ------------------------------------------------------------------ Discover cards: a picture, a name, one line
// The picture: the catalog's own (thumb, preview, screenshots[0], images[0], when a catalog has them), else the
// Workshop's first screenshot of a packaged mod (/wrath/mods/<id>/shot/0), else the hub's copy of a GitHub repo's
// preview (/wrath/art/hub-thumbs/<owner>__<repo>.webp). Only from the site itself (the window's CSP allows no other
// host). Lazy; while it loads, and when there is none (a 404), the tile drawn from the name shows.
const SITE = "https://play.openvanilla.app";
function siteImage(u) {
  if (typeof u !== "string" || !u) return "";
  if (/^\/wrath\/[A-Za-z0-9._~\/-]+$/.test(u) && !u.includes("..")) return SITE + u;
  if (u.startsWith(SITE + "/") && /^[A-Za-z0-9._~\/:-]+$/.test(u) && !u.includes("..")) return u;
  return "";
}
function thumbUrl(p) {
  const first = (v) => (Array.isArray(v) ? v[0] : v);
  for (const v of [p.thumb, p.thumbnail, p.preview, first(p.screenshots), first(p.images), p.icon]) {
    const u = siteImage(typeof v === "object" && v ? v.url : v);
    if (u) return u;
  }
  const mid = p.id.startsWith("mod:") ? p.id.slice(4) : "";
  if (p.source === "packaged" && /^[a-z0-9-]+$/.test(mid)) return `${SITE}/wrath/mods/${mid}/shot/0`;
  const gh = /^https:\/\/github\.com\/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\/([A-Za-z0-9][A-Za-z0-9._-]{0,99}?)(?:\.git)?\/?$/.exec(p.repo || "");
  if (gh) return `${SITE}/wrath/art/hub-thumbs/${gh[1].toLowerCase()}__${gh[2].toLowerCase()}.webp`;
  return "";
}
// A small glyph per category (24x24, stroked), for the drawn tile.
const CAT_GLYPHS = {
  addons: "M9 4h4v2.5a1.5 1.5 0 0 0 3 0V4h4v6h-2.5a1.5 1.5 0 0 0 0 3H20v7H4v-7h2.5a1.5 1.5 0 0 0 0-3H4V4z",
  graphics: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
  sandbox: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5",
  maps: "M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2zM9 4v14M15 6v14",
  builds: "M4 20h16M6 20V10l6-5 6 5v10M10 20v-5h4v5",
  encounters: "M5 19L19 5M14 5h5v5M5 5l5 5M14 14l5 5M19 14v5h-5",
  models: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
  "realm-scripts": "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  presets: "M5 6h14M5 12h14M5 18h14M9 4v4M15 10v4M8 16v4",
  audio: "M9 18V6l11-2v12M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  tools: "M14.5 5.5a4 4 0 0 0-5 5L4 16v4h4l5.5-5.5a4 4 0 0 0 5-5L16 12l-4-4z",
  conversions: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5",
};
function genTile(p) {
  const t = el("span", "dc-gen");
  t.setAttribute("aria-hidden", "true");
  const h = nameHue(p.name || p.id);
  t.style.setProperty("--h1", String(h));
  t.style.setProperty("--h2", String((h + 48) % 360));
  t.append(el("b", "", ([...String(p.name || "?").trim()][0] || "?").toUpperCase()));
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", CAT_GLYPHS[p.category] || CAT_GLYPHS.addons);
  svg.append(path);
  t.append(svg);
  return t;
}
function cardThumb(p) {
  const box = el("div", "dc-thumb");
  box.append(genTile(p));
  const u = thumbUrl(p);
  if (u) {
    const img = el("img");
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.width = 480;
    img.height = 270;
    img.addEventListener("load", () => { if (img.naturalWidth > 1) box.classList.add("has-img"); else img.remove(); });
    img.addEventListener("error", () => { img.remove(); box.classList.remove("has-img"); });
    img.src = u;
    box.append(img);
  }
  return box;
}
// The first sentence of a description (the card clamps it to one line; the whole text is its tooltip).
function firstLine(text) {
  const t = String(text || "").replace(/\s+/g, " ").trim();
  const m = /^(.+?[.!?])(\s|$)/.exec(t);
  return m ? m[1] : t;
}
const shortNum = (n) => (n >= 10000 ? Math.round(n / 1000) + "k" : n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n));

function projectCard(p, c) {
  if (p.source === "upstream" && window.LeylineMarket) return window.LeylineMarket.card(p, c);   // from the author (market.js)
  const card = el("article", "mod-card dc-card" + (p.id === linkedId ? " linked" : ""));
  card.dataset.id = p.id;
  const fits = fitsClient(p, c);
  const thumb = cardThumb(p);
  const cat = catalog.categories.find((k) => k.id === p.category);
  if (c && !fits) thumb.append(el("span", "dc-tag warn", `Not for ${c.build}`));
  else if (cat) thumb.append(el("span", "dc-tag", cat.name));
  thumb.append(rateStars(p));
  const body = el("div", "dc-body");
  const page = p.page || p.repo || "";
  const name = el(page ? "button" : "b", "name", p.name);
  if (page) {
    name.type = "button";
    name.title = `Open ${p.name}'s page`;
    name.addEventListener("click", () => openUrl(page));
    card.classList.add("can-open");
  }
  const line = firstLine(p.description);
  const desc = el("p", "desc", line);
  if (p.description && p.description.trim() !== line) desc.title = p.description;
  body.append(name, desc);
  const foot = el("div", "dc-foot");
  const meta = el("div", "dc-meta");
  if (p.version) meta.append(el("span", "ver-s", "v" + p.version));
  const m = ranked && ranked.metrics ? ranked.metrics[p.id] : null;
  if (m) {
    const r = m.rating || {};
    if (r.n) { const s = el("span", "rating", `★ ${Number(r.avg).toFixed(1)}`); s.title = `${r.n} rating${r.n === 1 ? "" : "s"}`; meta.append(s); }
    const all = (m.installs && m.installs.all) || 0;
    const ins = el("span", "installs", shortNum(all));
    ins.title = `${all} install${all === 1 ? "" : "s"}`;
    meta.append(ins);
    if (m.rising) { const r = el("span", "rising", "▲"); r.title = "Rising"; r.setAttribute("aria-label", "Rising"); meta.append(r); }
  } else if (p.source !== "packaged") meta.append(el("span", "src", "Community"));
  const acts = el("div", "acts");
  const mine = installed.find((x) => x.key === p.id);
  if (p.source === "packaged" && p.download) {
    const b = el("button", "btn small");
    b.type = "button";
    if (!c) { b.textContent = "Install"; b.disabled = true; b.title = "Add a game client first"; }
    else if (!fits) { b.textContent = "Install"; b.disabled = true; b.title = `Made for ${p.builds.join(" / ")} clients`; }
    else if (mine && mine.update) { b.textContent = "Update"; b.title = `Update to ${mine.update}`; b.classList.add("primary"); }
    else if (mine) { b.textContent = "Installed ✓"; b.disabled = true; b.classList.add("done"); }
    else { b.textContent = "Install"; b.classList.add("primary"); }
    b.addEventListener("click", (ev) => { ev.stopPropagation(); installProject(p, b); });
    if (p.kind === "realm") b.title = "A realm mod: it runs on a realm that installs it, not in your game";
    acts.append(b);
  } else if (page) {
    const b = el("button", "btn small", "Get ↗");
    b.type = "button";
    b.title = "Get it from its page, then drop the zip on Mods › Installed.";
    b.addEventListener("click", (ev) => { ev.stopPropagation(); openUrl(page); });
    acts.append(b);
  }
  foot.append(meta, acts);
  body.append(foot);
  card.append(thumb, body);
  // the whole card opens the page (the name is the keyboard way in; buttons and stars keep their own clicks)
  if (page) card.addEventListener("click", (ev) => { if (!ev.target.closest("button, a, select, input")) openUrl(page); });
  return card;
}

// ------------------------------------------------------------------ native code: a one-time OK per mod
// The core refuses a mod with .dll/.asi/.exe files until the player says yes once; its error starts with
// NATIVE_CONFIRM: and carries {key, name, files}. The OK is kept in the launcher's settings.
const NATIVE = "NATIVE_CONFIRM:";
function askNative(info) {
  return new Promise((resolve) => {
    const d = $("native-dlg");
    $("native-name").textContent = info.name || "This mod";
    $("native-files").replaceChildren(...(info.files || []).slice(0, 30).map((f) => el("li", "", f)));
    const done = (yes) => { if (d.open) d.close(); resolve(yes); };
    $("native-yes").onclick = () => done(true);
    $("native-no").onclick = () => done(false);
    d.oncancel = (ev) => { ev.preventDefault(); done(false); };
    if (d.showModal) d.showModal(); else resolve(window.confirm(`${info.name} has native code. Install it?`));
  });
}
async function withNativeOk(run) {
  try {
    return await run();
  } catch (e) {
    const t = String(e);
    if (!t.startsWith(NATIVE)) throw e;
    let info;
    try { info = JSON.parse(t.slice(NATIVE.length)); } catch (_) { throw "Leyline could not read this mod's native code notice."; }
    if (!(await askNative(info))) throw `Not installed: you said no to ${info.name || "its"} native code.`;
    await invoke("mod_native_confirm", { key: info.key });
    return await run();
  }
}

// What an install says afterwards: its notes, and the player's changed files an update kept.
function installedText(verb, m, c) {
  let t = `${verb} ${m.name}${m.version ? " v" + m.version : ""} in ${c.name}.`;
  if (m.kept && m.kept.length) t += " Kept your changes: " + m.kept.join("; ") + ".";
  if (m.warnings && m.warnings.length) t += " Note: " + m.warnings.join("; ");
  return t;
}

async function installProject(p, btn) {
  const c = needClient("cat-status");
  if (!c) return;
  btn.disabled = true;
  btn.textContent = "Installing…";
  const was = installed.find((m) => m.key === p.id);
  say("cat-status", `Downloading ${p.name}…`);
  try {
    const m = await withNativeOk(() => invoke("mod_install", { client: c.id, project: p.id }));
    say("cat-status", installedText(was ? "Updated" : "Installed", m, c), m.warnings.length ? "warn" : "ok");
  } catch (e) {
    sayErr("cat-status", e);
  }
  await loadInstalled(true);
  renderCatalog();
}

// A hub page's "Install with Leyline" (leyline://install/<id>): show that project with its INSTALL button. Nothing
// installs until the player clicks INSTALL.
async function handleDeepLink() {
  let link = null;
  try { link = await invoke("deep_link_take"); } catch (_) { return; }
  if (link && link.action === "realm" && typeof link.id === "string") return showLinkedRealm(link.id);
  if (link && link.action === "host" && typeof link.id === "string") return showHostLink(link.id);
  if (!link || link.action !== "install" || typeof link.id !== "string") return;
  const p = catalog.projects.find((x) => x.id === link.id);
  show("mods", true, "discover");   // the catalog was just loaded
  if (!p) { say("cat-status", "That mod is not in the Workshop catalog here yet. Try again after the catalog refreshes.", "warn"); return; }
  linkedId = p.id;
  catFilter.cat = "";
  catFilter.kind = "";
  $("cat-q").value = "";
  const c = pickedClient();
  if (c && !fitsClient(p, c)) $("cat-fit").checked = false;
  await loadRanks(false);
  renderCatalog();
  const card = document.querySelector(`#cat-grid .mod-card[data-id="${CSS.escape(p.id)}"]`);
  if (card) { card.scrollIntoView({ block: "center" }); const b = card.querySelector(".acts .btn"); if (b && !b.disabled) b.focus(); }
  say("cat-status", c ? `From the hub: ${p.name}. Press Install to put it in ${c.name}.` : `From the hub: ${p.name}. Add your game folder first, then press Install.`, "ok");
}

// The in-game Host window (leyline://host?<choices>, checked by deeplink.rs): the Host page with the host's choices and
// "MAKE IT ON THE WEBSITE" (the website's form filled in; the realm key is still made on this PC). From the game's
// "Your realm" tab (leyline://host?manage=<what>): the Host page with what to do for that control. Nothing starts.
const HOST_WORDS = {
  core: { azerothcore: "AzerothCore", cmangos: "CMaNGOS" },
  preset: { den: "My Den", dalaran: "Dalaran hangout", main: "Classic levelling", brawl: "Brawl", progression: "Progression", vanillaplus: "Vanilla+",
    "cmangos-1.12.1": "CMaNGOS Classic", "cmangos-2.4.3": "CMaNGOS TBC" },
  type: { normal: "Normal", pvp: "PvP", rp: "RP", rppvp: "RP-PvP" },
  start: { level1: "Level 1 only", boost: "Level 1, or the boost to 80" },
  vis: { public: "Public: on the Leyline list", private: "Private: invite link only" },
  signup: { open: "Open: anyone", invite: "Invite link only", off: "Closed" },
  herokey: { on: "On", off: "Off" },
};
const HOST_LABELS = [["core", "Core"], ["preset", "Ruleset"], ["name", "Realm name"], ["type", "Type"], ["xp", "XP rate"],
  ["loot", "Loot rate"], ["rep", "Reputation rate"], ["start", "New characters"], ["bots", "Bots"], ["vis", "Who can find it"],
  ["signup", "Accounts"], ["herokey", "Hero Key sign-in"], ["region", "Region"], ["lang", "Language"], ["tags", "Tags"],
  ["max", "Max players shown"]];
const HOST_MANAGE = {
  bots: ["Bots", "In your Host pack folder: leyline options --bots 40 (0 turns them off), then restart the realm (leyline stop, then leyline host)."],
  rates: ["Rates", "In your Host pack folder: leyline options --xp 3 --loot 1 --rep 2 (1 to 10), then restart the realm (leyline stop, then leyline host)."],
  signup: ["Sign-up", "In your Host pack folder: leyline signup open (anyone), leyline signup invite (invite link only) or leyline signup off."],
  list: ["The Leyline list", "In your Host pack folder: leyline public (on the list) or leyline private (invite link only). The list changes within a minute."],
  invite: ["Invite link", "Your realm's invite link is below, under Your realm: Copy invite link. New invite link stops the old one."],
};

function hostChoices(id) {
  const p = new URLSearchParams(id);
  // a Den has no bots and no player limit to choose (the kit sets both)
  const den = p.get("preset") === "den";
  return HOST_LABELS.filter(([k]) => p.has(k) && !(den && (k === "bots" || k === "max"))).map(([k, label]) => {
    const v = p.get(k);
    const words = HOST_WORDS[k] && HOST_WORDS[k][v];
    return [label, words || (["xp", "loot", "rep"].includes(k) ? v + "x" : k === "tags" ? v.split(",").join(", ") : v)];
  });
}

function showHostLink(id) {
  show("host");
  const box = $("host-from-game");
  if (!box) return;
  box.hidden = false;
  const list = $("host-from-game-list");
  const go = $("host-from-game-go");
  list.replaceChildren();
  if (id.startsWith("manage=")) {
    const m = HOST_MANAGE[id.slice(7)];
    if (!m) return;
    $("host-from-game-title").textContent = `FROM THE GAME: ${m[0].toUpperCase()}`;
    list.append(el("li", "", m[1]));
    go.hidden = true;
    say("host-status-line", `From the game: ${m[0]}.`, "ok");
    return;
  }
  $("host-from-game-title").textContent = "FROM THE GAME: YOUR NEW REALM";
  for (const [label, v] of hostChoices(id)) {
    const li = el("li", "");
    li.append(el("b", "", label + ": "), document.createTextNode(v));
    list.append(li);
  }
  go.hidden = false;
  go.onclick = async () => {
    try { await invoke("open_host_form", { query: id }); say("host-status-line", "The website's host page is open with your choices: sign in, add your GM account name, press Start server, then come back here for steps 2 and 3.", "ok"); }
    catch (e) { sayErr("host-status-line", e); }
  };
  say("host-status-line", "Your choices from the game are below. Make the realm on the website, then start it here.", "ok");
}

// A website's "Open in launcher" (leyline://realm/<id>): show that realm on the Realms page with PLAY focused.
// Nothing starts until the player clicks PLAY.
async function showLinkedRealm(id) {
  show("realms", true);
  if (!realmsCache.length) { try { await loadRealms(false); } catch (_) {} }
  const r = realmsCache.find((x) => (id === "official" ? x.official : x.realm_id === id));
  if (!r) { say("rl-status", "That realm isn't on the realm list right now: it may be offline. Try Refresh in a minute.", "warn"); return; }
  $("rl-mine").checked = false;
  renderRealms();
  const card = [...document.querySelectorAll("#rl-list .realm-card")].find((c) => c.querySelector(".name")?.textContent === r.name);
  if (card) { card.classList.add("linked"); card.scrollIntoView({ block: "center" }); const b = card.querySelector(".acts .btn"); if (b && !b.disabled) b.focus(); }
  say("rl-status", `From the website: ${r.name}. Press PLAY to join.`, "ok");
}

$("cat-q").addEventListener("input", renderCatalog);
$("cat-fit").addEventListener("change", renderCatalog);

// The three mod tiles (owner 2026-10-30: taken off Home; kept for a page that brings the box back).
function renderModTiles() {
  const box = $("mod-tiles");
  if (!box) return;
  box.replaceChildren();
  const mine = installed.slice().sort((x, y) => (y.update ? 1 : 0) - (x.update ? 1 : 0)).slice(0, 3);
  const picks = catalog.projects.filter((p) => p.source === "packaged").concat(catalog.projects.filter((p) => p.source !== "packaged"));
  for (let i = 0; i < 3; i++) {
    const m = mine[i];
    const p = m ? null : picks[i - mine.length];
    const t = el("button", "tile" + (m && m.update ? " has-update" : ""));
    t.type = "button";
    const txt = el("span", "tile-txt");
    let name = "Mod catalog", line = "Loading…", cls = "";
    if (m) {
      name = m.name;
      if (m.update) { line = `Update to v${m.update}`; cls = "upd"; }
      else if (!m.enabled) { line = "Turned off"; cls = "off"; }
      else line = m.version ? `Installed · v${m.version}` : "Installed";
    } else if (p) {
      name = p.name;
      line = "In the Workshop";
    } else if (catalog.projects.length || installed.length) {
      continue;
    }
    txt.append(el("b", "", name), el("i", cls, line));
    t.append(el("span", "tile-ico", name.charAt(0).toUpperCase()), txt);
    t.title = m ? "Open Mods › Installed" : "Open Mods › Discover";
    t.addEventListener("click", () => show("mods", false, m ? "installed" : "discover"));
    box.append(t);
  }
}

// ------------------------------------------------------------------ My Mods
async function loadInstalled(quiet) {
  const c = pickedClient();
  if (!c) { installed = []; if (!quiet) renderInstalled(); return; }
  try {
    const r = await invoke("mods_installed", { client: c.id });
    installed = r.mods;
  } catch (e) {
    installed = [];
    if (!quiet) sayErr("mods-status", e);
  }
  for (const badge of [$("nav-mods-count"), $("tab-mods-count")]) {
    if (!badge) continue;
    badge.hidden = !installed.length;
    badge.textContent = String(installed.length);
  }
  renderInstalled();
  renderModTiles();
  refreshModUpdates();
}

// The title bar's pill: Workshop updates for mods in any of your clients.
let modUpdates = [];
async function refreshModUpdates() {
  try { modUpdates = await invoke("mods_updates"); } catch (_) { modUpdates = []; }
  const pill = $("tb-modupd");
  pill.hidden = !modUpdates.length;
  pill.textContent = modUpdates.length === 1 ? "1 mod update" : `${modUpdates.length} mod updates`;
  pill.title = modUpdates.map((u) => `${u.name}: v${u.version || "?"} → v${u.update} (${u.client_name})`).join("\n");
}
$("tb-modupd").addEventListener("click", () => {
  // Open Mods › Installed on a client that has an update, if the picked one has none.
  const c = pickedClient();
  const u = modUpdates.find((x) => c && x.client === c.id) || modUpdates[0];
  if (u && (!c || u.client !== c.id)) {
    state.settings.selected_client = u.client;
    $("play-client").value = u.client;
    renderClientPickers();
    realmChanged();
    saveSelection();
  }
  show("mods", false, "installed");
});

async function updateMod(c, m) {
  const r = await withNativeOk(() => invoke("mod_install", { client: c.id, project: m.key }));
  return installedText("Updated", r, c);
}

function renderInstalled() {
  const c = pickedClient();
  if (window.LeylineAddons) window.LeylineAddons.renderMods(c);   // Our addons, above the Workshop mods (addons.js)
  $("mods-client-note").textContent = c ? (offeredBuild(c.build) ? c.build : "Other build") : "";
  $("mods-client-note").title = c ? `${buildLabel(c.build)} · ${c.path}` : "";
  const list = $("mods-list");
  list.replaceChildren();
  const ups = installed.filter((m) => m.update);
  $("mods-update-all").hidden = ups.length < 2;
  $("mods-update-all").textContent = `Update all (${ups.length})`;
  if (!c) { list.append(el("p", "hint", "Add your game client first.")); return; }
  if (buildTag(c.build) === "other" && !installed.length) { list.append(el("p", "hint", "Leyline does not know this client's build, so it installs no mods here. Realms work.")); return; }
  if (!installed.length) { list.append(el("p", "hint", "No mods in this client yet. Install from Mods › Discover, or drop one above.")); return; }
  for (const m of installed) {
    const card = el("div", "card" + (m.enabled ? "" : " off") + (m.update ? " has-update" : ""));
    const top = el("div", "top");
    top.append(el("span", "name", m.name), el("span", "build", m.version ? "v" + m.version : (m.source === "catalog" ? "Workshop" : "Local")));
    const tags = el("div", "tags");
    tags.append(el("span", "tag", m.source === "catalog" ? "Workshop" : "From your PC"));
    if (m.update) tags.append(el("span", "tag gold", `v${m.update} ready`));
    if (m.native_code) tags.append(el("span", "tag warn", "Native code"));
    if (!m.enabled) tags.append(el("span", "tag", "Turned off"));
    const meta = el("div", "meta");
    const what = [];
    if (m.addons.length) what.push("Addons: " + m.addons.join(", "));
    if (m.patches.length) what.push("Patch: " + m.patches.join(", "));
    if (m.natives && m.natives.length) what.push("Native: " + m.natives.join(", "));
    meta.append(el("span", "", what.join(" · ")));
    if (m.credits) meta.append(el("span", "", m.credits));
    if (m.update) meta.append(el("span", "ok", `Update available: v${m.update}`));
    else if (m.source === "catalog" && !m.in_catalog) meta.append(el("span", "warn", "No longer in the Workshop for this client"));
    for (const w of m.warnings || []) meta.append(el("span", "warn", w));
    const acts = el("div", "acts");
    const tog = el("button", "btn small", m.enabled ? "Turn off" : "Turn on");
    tog.addEventListener("click", () => modAction("mod_set_enabled", { client: c.id, key: m.key, on: !m.enabled }, m.enabled ? `Turned off ${m.name}.` : `Turned on ${m.name}.`));
    acts.append(tog);
    if (m.update) {
      const up = el("button", "btn small", "Update");
      up.addEventListener("click", async () => {
        up.disabled = true;
        up.textContent = "Updating…";
        say("mods-status", `Downloading ${m.name} v${m.update}…`);
        try { say("mods-status", await updateMod(c, m), "ok"); }
        catch (e) { sayErr("mods-status", e); }
        await loadInstalled();
        renderCatalog();
      });
      acts.append(up);
    }
    // One click: removal takes out only the files Leyline put in and you have not changed, so nothing of yours goes.
    const rm = el("button", "btn small danger", "Remove");
    rm.addEventListener("click", async () => {
      rm.disabled = true;
      rm.textContent = "Removing…";
      try {
        const r = await invoke("mod_uninstall", { client: c.id, key: m.key });
        let t = `Removed ${m.name}: ${r.removed_files} files.`;
        if (r.changed && r.changed.length) t += ` Left the files you changed: ${r.changed.join(", ")}.`;
        if (r.kept.length) t += ` Kept files Leyline did not put there: ${r.kept.join(", ")}.`;
        if (m.source === "catalog") t += " Install it again any time from Mods › Discover.";
        say("mods-status", t, r.changed && r.changed.length ? "warn" : "ok");
      } catch (e) { sayErr("mods-status", e); }
      await loadInstalled();
      renderCatalog();
    });
    acts.append(rm);
    card.append(top, tags, meta, acts);
    list.append(card);
  }
}

async function modAction(cmd, args, okText) {
  try { await invoke(cmd, args); say("mods-status", okText, "ok"); }
  catch (e) { sayErr("mods-status", e); }
  await loadInstalled();
  renderCatalog();
}

function showProblems(text) {
  const ul = $("mods-problems");
  const lines = String(text).split("\n").filter(Boolean);
  ul.hidden = lines.length < 2;
  ul.replaceChildren(...(lines.length < 2 ? [] : lines.slice(0, 30).map((l) => el("li", "", l))));
  return lines.length < 2 ? String(text) : `It can't be installed (${lines.length} problems):`;
}

async function installLocal(paths) {
  const c = needClient("mods-status");
  if (!c || !paths.length) return;
  $("mods-problems").hidden = true;
  for (const path of paths) {
    const name = path.split(/[\\/]/).pop();
    say("mods-status", `Checking ${name}…`);
    try {
      const m = await withNativeOk(() => invoke("mod_install_local", { client: c.id, path }));
      say("mods-status", installedText("Installed", m, c), m.warnings.length ? "warn" : "ok");
    } catch (e) {
      say("mods-status", `${name}: ` + showProblems(e), "bad");
      break;
    }
  }
  await loadInstalled();
  renderCatalog();
}
$("mods-update-all").addEventListener("click", async () => {
  const c = needClient("mods-status");
  if (!c) return;
  const ups = installed.filter((m) => m.update);
  const b = $("mods-update-all");
  b.disabled = true;
  const done = [];
  for (const m of ups) {
    say("mods-status", `Updating ${m.name} (${done.length + 1} of ${ups.length})…`);
    try { await updateMod(c, m); done.push(m.name); }
    catch (e) { say("mods-status", `${m.name}: ` + oops(e, OOPS["mods-status"]), "bad"); break; }
  }
  if (done.length === ups.length) say("mods-status", `Updated ${done.join(", ")}.`, "ok");
  b.disabled = false;
  await loadInstalled();
  renderCatalog();
});
$("mods-pick-file").addEventListener("click", async () => { const p = await invoke("pick_mod_file").catch(() => null); if (p) installLocal([p]); });
$("mods-pick-folder").addEventListener("click", async () => { const p = await invoke("pick_mod_folder").catch(() => null); if (p) installLocal([p]); });

// Files dropped on the window (Tauri gives their paths). Only Mods › Installed takes them; anywhere else they lead there.
function setupDrop() {
  const wv = window.__TAURI__ && window.__TAURI__.webview && window.__TAURI__.webview.getCurrentWebview
    ? window.__TAURI__.webview.getCurrentWebview() : null;
  if (!wv || !wv.onDragDropEvent) return;
  wv.onDragDropEvent((ev) => {
    const t = ev.payload && ev.payload.type;
    const here = currentPage === "mods" && currentTab === "installed";
    if (t === "enter" || t === "over") { $("drop").classList.add("over"); if (!here) show("mods", false, "installed"); }
    else if (t === "leave") $("drop").classList.remove("over");
    else if (t === "drop") {
      $("drop").classList.remove("over");
      if (!here) show("mods", false, "installed");
      installLocal(ev.payload.paths || []);
    }
  });
}

// ------------------------------------------------------------------ Realms
let realmsCache = [];
async function loadRealms(quiet) {
  if (!quiet) say("rl-status", "Loading the realm list…");
  try {
    const l = await invoke("realms_list");
    // the core's official record (slug "official", realms.rs official()) is the Hangout; community records never are.
    // Its card keeps the record's own type (PvE): the Official badge already says what HANGOUT.kind would.
    realmsCache = l.realms.map((r) => (r.official && r.slug === "official" ? Object.assign({}, r, { name: HANGOUT.name }) : r));
    realmNames = l.realms.map((r) => r.name);
    const when = l.saved_at ? new Date(l.saved_at * 1000).toLocaleString() : "an earlier visit";
    const n = l.realms.length - 1;
    networkTotals = l.network || null;
    if (l.from_cache) say("rl-status", `Offline: showing the list as it was ${when}.`, "warn");
    else if (l.error) { console.error("[leyline] realm list", l.error); say("rl-status", "The community list isn't reachable right now. Try Refresh in a minute.", "warn"); }
    else say("rl-status", "", "ok");   // the count is already on the network line above
    fillRealmFilters();
  } catch (e) {
    sayErr("rl-status", e);
  }
  renderRealms();
  renderRealmRows();
  renderSrvHead();
  renderPlayBar();   // the play bar's realm name and version come from the list too
  document.dispatchEvent(new CustomEvent("leyline:realms"));   // Home's Popular realms row (home.js)
}

// The network (realms.rs order): featured community realms, the Leyline Sample Hangout (ours, temporary), the
// other live realms by the network's fair score, offline ones. The filters narrow the community realms.
let networkTotals = null;
let p2pHosting = false;   // direct connections are shown only when the p2p_hosting flag is on (Settings > Advanced)
let heroKeyOn = false;    // "Sign in with your Hero Key" only with the herokey_sso flag on (docs/HERO-KEY-SSO.md)
const TAG_LABELS = { blizzlike: "Original rules", boosted: "Boosted", custom: "Custom", pvp: "PvP", rp: "RP", hangout: "Hangout", bots: "Bots" };
const REGION_LABELS = { "na-east": "North America east", "na-west": "North America west", sa: "South America", eu: "Europe",
  africa: "Africa", me: "Middle East", asia: "Asia", oce: "Oceania" };
const RL_FILTERS = [
  ["rl-f-build", (r) => (r.build && offeredBuild(r.build) ? [r.build] : []), (v) => v],
  ["rl-f-tag", (r) => r.tags || [], (v) => TAG_LABELS[v] || v],
  ["rl-f-region", (r) => (r.region ? [r.region] : []), (v) => REGION_LABELS[v] || v],
  ["rl-f-lang", (r) => (r.language ? [r.language.split("-")[0]] : []), (v) => v],
];
function fillRealmFilters() {
  for (const [id, values, label] of RL_FILTERS) {
    const sel = $(id);
    if (!sel) continue;
    const cur = sel.value;
    const vs = [...new Set(realmsCache.filter((r) => !r.official).flatMap(values))].sort();
    sel.replaceChildren(el("option", "", "any"), ...vs.map((v) => { const o = el("option", "", label(v)); o.value = v; return o; }));
    sel.firstChild.value = "";
    sel.value = vs.includes(cur) ? cur : "";
  }
}
function realmMatches(r) {
  if (r.official) return true;   // the sample stays pinned
  if (hiddenBuild(r.build)) return false;   // 4.3.4 / 5.4.8 realms are not offered for now (MAX_OFFERED_BUILD)
  for (const [id, values] of RL_FILTERS) {
    const v = $(id) && $(id).value;
    if (v && !values(r).includes(v)) return false;
  }
  if ($("rl-f-now") && $("rl-f-now").checked && !(r.state === "live" && (r.players || 0) > 0)) return false;
  return true;
}
// The search box: a realm's name, line and tags (the official realm too).
function realmSearched(r) {
  const q = $("rl-q") ? $("rl-q").value.trim().toLowerCase() : "";
  if (!q) return true;
  return [r.name, r.tagline, r.kind, CORE_LABELS[r.core], REGION_LABELS[r.region], r.language, ...(r.tags || []).map((t) => TAG_LABELS[t] || t)]
    .filter(Boolean).join(" ").toLowerCase().includes(q);
}
// How many filters are on (the number on the FILTERS button).
function realmFilterCount() {
  let n = RL_FILTERS.filter(([id]) => $(id) && $(id).value).length;
  if ($("rl-f-now") && $("rl-f-now").checked) n++;
  if ($("rl-mine") && $("rl-mine").checked) n++;
  return n;
}
function clearRealmFilters() {
  for (const [id] of RL_FILTERS) if ($(id)) $(id).value = "";
  $("rl-f-now").checked = false;
  $("rl-mine").checked = false;
  renderRealms();
}
function networkLine(t) {
  if (!t) return "";
  // the network's count is the community realms (the official realm is listed on its own, first)
  return `${t.realms} community realm${t.realms === 1 ? "" : "s"} · ${t.players} playing`;
}
// A realm's look, as on the website: a hue from its name, the crystal for the official realm.
function nameHue(name) {
  let h = 2166136261;
  for (const ch of String(name)) h = Math.imul(h ^ ch.codePointAt(0), 16777619) >>> 0;
  return h % 360;
}
function fillRealmIcon(box, name, official) {
  box.replaceChildren();
  box.classList.toggle("crystal", !!official);
  if (official) {
    const img = el("img");
    img.src = "art/brand/leyline-crystal-256.webp";
    img.alt = "";
    img.decoding = "async";
    box.append(img);
    box.style.removeProperty("--h");
  } else {
    box.style.setProperty("--h", String(nameHue(name)));
    box.textContent = ([...String(name).trim()][0] || "?").toUpperCase();
  }
  return box;
}
function realmIcon(name, official, size) {
  const box = el("span", "rl-ic" + (size ? " " + size : ""));
  box.setAttribute("aria-hidden", "true");
  return fillRealmIcon(box, name, official);
}
// The client version a realm takes ("3.3.5a"), when the list says and the build is offered.
function realmVersion(r) {
  if (!r) return null;
  if (r.build) return offeredBuild(r.build) ? r.build : null;
  return r.version || null;
}
// How full a realm is, for the bar: at least a sliver when anyone is on; a realm without a limit counts 100.
function playersFill(players, max) {
  if (!players) return 0;
  const cap = max > 0 ? max : 100;
  return Math.max(6, Math.min(100, Math.round((100 * players) / cap)));
}

let rlOtherShown = false;
function renderRealms() {
  const box = $("rl-list");
  box.replaceChildren();
  const now = state.settings.selected_realm;
  const mine = $("rl-mine").checked;
  const net = $("rl-net");
  if (net) {
    net.textContent = networkLine(networkTotals);
    net.title = networkTotals && networkTotals.bots ? `${networkTotals.bots} bots too` : "";
  }
  const nf = realmFilterCount();
  $("rl-fcount").hidden = !nf;
  $("rl-fcount").textContent = nf ? String(nf) : "";
  $("rl-filters-btn").classList.toggle("on", nf > 0);
  $("rl-filters-btn").setAttribute("aria-label", nf ? `Filters, ${nf} on` : "Filters");
  if (!rlOtherShown && !isOfficial()) { rlOtherShown = true; $("rl-other").open = true; }   // their own realm address: show where it is set
  // the official realm first, then the official lineup (Vanilla Remastered when listed), then the network's order (realms.rs)
  const order = realmsCache.filter((r) => r.official).concat(realmsCache.filter(inLineup), realmsCache.filter((r) => !r.official && !inLineup(r)));
  let community = 0;
  for (const r of order) {
    const fit = clientFor(r);
    if (mine && !fit) continue;
    if (!realmMatches(r) || !realmSearched(r)) continue;
    if (!r.official) community++;
    const live = r.state === "live";
    const card = el("article", "realm-card rl" + (r.address && r.address === now ? " on" : "") + (r.featured ? " featured" : "")
      + (r.official ? " official" : "") + (live ? "" : " off"));
    // icon · name, version and one tag (Official or Featured) / one line (type · core) · players · PLAY
    const main = el("div", "rl-main");
    const title = el("div", "rl-title");
    const name = el("b", "name", r.name);
    if (r.tagline) name.title = r.tagline;
    title.append(name);
    if (r.verified) { const v = el("span", "rl-ok", "✓"); v.title = "Verified host: checked by Leyline staff"; v.setAttribute("aria-label", "Verified host"); title.append(v); }
    const ver = realmVersion(r);
    if (ver) { const v = el("span", "rl-ver", ver); v.title = "Game client version"; title.append(v); }
    if (r.official) { const b = el("span", "rl-bdg o", "Official"); if (r.temporary) b.title = "Temporary: our own realm for now"; title.append(b); }
    else if (r.featured) title.append(el("span", "rl-bdg f", "Featured"));
    const line = el("div", "rl-meta");
    const bits = [r.kind, CORE_LABELS[r.core] || "Other server"];
    if (r.direct && p2pHosting) bits.push("Direct connect available");
    line.append(el("span", "", bits.filter(Boolean).join(" · ")));
    // everything else about the realm, on hover
    const more = [r.official ? "Run by Leyline" : "Community realm", r.is_new ? "New" : "",
      r.region ? (REGION_LABELS[r.region] || r.region) + (r.region_estimated ? " (estimated)" : "") : "", r.language || "",
      ...(r.official ? [] : (r.tags || []).map((t) => TAG_LABELS[t] || t))];
    const u = r.uptime_7d != null ? r.uptime_7d : r.uptime_24h;
    if (u != null) more.push(`${u}% up · ${r.uptime_7d != null ? "7 d" : "24 h"}`);
    if (r.address) more.push("Realmlist: " + r.address);
    line.title = more.filter(Boolean).join(" · ") + (r.rules && r.rules.length ? "\n" + r.rules.slice(0, 4).join("\n") : "");
    main.append(title, line);
    if (r.build && !fit) main.append(el("div", "rl-note", `Needs your own ${r.build} client`));
    // the realm's own links, quiet
    const links = el("div", "rl-links");
    if (r.join_url) links.append(linkBtn("Make an account", r.join_url));
    if (r.discord) links.append(linkBtn("Discord", r.discord));
    if (r.report_url && !r.official) { const rep = linkBtn("Report", r.report_url); rep.title = "Report this realm to Leyline staff (on the website)"; links.append(rep); }
    if (links.children.length) main.append(links);
    // players: an online dot, the count and a small fill bar
    const pop = el("div", "rl-pop");
    const st = el("span", "state " + (live ? "is-online" : "is-offline"));
    st.append(el("span", "dot"));
    if (!live) st.append(el("span", "", "Offline"));
    else if (r.players == null) st.append(el("span", "", "Online"));
    else {
      const n = el("span", "");
      n.append(el("b", "rl-n", String(r.players)), document.createTextNode(r.max_players ? ` / ${r.max_players}` : " playing"));
      st.append(n);
      st.title = `${r.players}${r.max_players ? " of " + r.max_players : ""} playing` + (r.bots ? ` · ${r.bots} bots` : "");
    }
    pop.append(st);
    if (live) {
      const bar = el("span", "rl-bar");
      bar.setAttribute("aria-hidden", "true");
      const fill = el("i");
      fill.style.width = playersFill(r.players, r.max_players) + "%";
      bar.append(fill);
      pop.append(bar);
    }
    const acts = el("div", "acts");
    if (heroKeyOn && !r.official && r.realm_id && r.state === "live") {
      const hk = el("button", "btn small", "Sign in with your Hero Key");
      hk.title = "No account to make: your Hero Key signs you in here (a one-time password, shown below)";
      hk.disabled = !state.settings.clients.length;
      hk.addEventListener("click", () => playRealmHeroKey(r, hk));
      acts.append(hk);
    }
    const play = el("button", "btn small primary rl-play", "Play");
    if (!state.settings.clients.length) { play.disabled = true; play.title = "Add a game client first"; }
    else if (!fit) { play.title = `This realm runs ${r.build}: PLAY says what is missing`; }
    else play.title = `Plays with ${fit.name}`;
    play.addEventListener("click", () => playRealm(r, play));
    acts.prepend(play);
    card.append(realmIcon(r.name, r.official), main, pop, acts);
    box.append(card);
  }
  const empty = (text, label, fn) => {
    const e = el("div", "rl-empty");
    e.append(el("span", "", text));
    if (label) {
      const b = el("button", "btn small", label);
      b.type = "button";
      b.addEventListener("click", fn);
      e.append(b);
    }
    box.append(e);
  };
  const realmsQ = $("rl-q").value.trim();
  if (realmsCache.filter((r) => !r.official).length === 0) empty("No community realms yet. Be the first to run one: see Host your own below.");   // the banner below is the one call to action
  else if (!community && realmsQ) empty(`No realm called “${realmsQ}”.`, "Clear search", () => { $("rl-q").value = ""; renderRealms(); });
  else if (!community && nf) empty(mine && nf === 1 ? "None of the listed realms fits your clients." : "No realms match these filters.", "Clear filters", clearRealmFilters);
}
for (const id of ["rl-f-build", "rl-f-tag", "rl-f-region", "rl-f-lang", "rl-f-now"]) {
  if ($(id)) $(id).addEventListener("change", () => renderRealms());
}
$("rl-q").addEventListener("input", () => renderRealms());
$("rl-f-clear").addEventListener("click", clearRealmFilters);
if ($("rl-host")) $("rl-host").addEventListener("click", () => show("host"));
if ($("rl-host-link")) $("rl-host-link").addEventListener("click", () => show("host"));   // the Host page has Link my server
// The FILTERS popover and the … menu: one open at a time; a click outside or Escape closes it.
function rlPopover(btnId, boxId) {
  const btn = $(btnId), box = $(boxId);
  const set = (open) => { box.hidden = !open; btn.setAttribute("aria-expanded", String(open)); btn.classList.toggle("open", open); };
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const open = box.hidden;
    document.querySelectorAll("#page-realms .rl-popover").forEach((b) => { if (b !== box && !b.hidden) b.dispatchEvent(new Event("rl-close")); });
    set(open);
    if (open) { const f = box.querySelector("select, input, button"); if (f) f.focus(); }
  });
  box.addEventListener("rl-close", () => set(false));
  box.addEventListener("click", (ev) => ev.stopPropagation());
  box.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { set(false); btn.focus(); } });
  document.addEventListener("click", () => { if (!box.hidden) set(false); });
  return set;
}
rlPopover("rl-filters-btn", "rl-filters");
const rlMenu = rlPopover("rl-more", "rl-menu");
invoke("p2p_flags").then((v) => {
  p2pHosting = !!(v && v.effective && v.effective.p2p_hosting);
  heroKeyOn = !!(v && v.effective && v.effective.herokey_sso);   // Hero Key sign-in on realms (docs/HERO-KEY-SSO.md)
}).catch(() => {});
const CORE_LABELS = { azerothcore: "AzerothCore", trinitycore: "TrinityCore", cmangos: "CMaNGOS", vmangos: "vMaNGOS", mangos: "MaNGOS", other: "Other server" };
$("rl-mine").addEventListener("change", () => renderRealms());
async function playRealm(r, btn) {
  const picked = needClient("rl-status");
  if (!picked) return;
  const c = clientFor(r) || picked;
  btn.disabled = true;
  say("rl-status", `Starting ${c.name} on ${r.name}…`);
  try {
    if (window.LeylineAddons && r.official) await window.LeylineAddons.beforePlay(c);   // offers the Leyline addons (addons.js)
    const msg = await invoke("play_realm", { client: picked.id, slug: r.slug });
    say("rl-status", msg + (r.official ? "" : " First time here? Make your account with Make an account."), "ok");
    await refresh();
    renderRealms();
  } catch (e) { sayErr("rl-status", e); }
  btn.disabled = false;
}

// "Sign in with your Hero Key" (the herokey_sso flag): the realm sets a one-time login for this player's account
// there; the client starts with the account name filled in, and the password is shown here to type (the client
// can't take one from outside). Nothing is saved.
async function playRealmHeroKey(r, btn) {
  const picked = needClient("rl-status");
  if (!picked) return;
  btn.disabled = true;
  say("rl-status", `Signing in to ${r.name} with your Hero Key…`);
  try {
    const l = await invoke("play_realm_herokey", { client: picked.id, slug: r.slug });
    const mins = Math.max(1, Math.round((l.valid_s || 600) / 60));
    say("rl-status", `Started on ${r.name} as ${l.user}. At the login screen type this one-time password: ${l.pass} `
      + `(it works for ${mins} minutes and is not saved).`, "ok");
    await refresh();
    renderRealms();
  } catch (e) { sayErr("rl-status", e); }
  btn.disabled = false;
}

$("rl-refresh").addEventListener("click", () => loadRealms());
$("rl-back").addEventListener("click", async () => {
  rlMenu(false);
  const c = needClient("rl-status");
  if (!c) return;
  try { say("rl-status", await invoke("back_to_official", { client: c.id }), "ok"); await refresh(); renderRealms(); }
  catch (e) { sayErr("rl-status", e); }
});
$("rl-restore").addEventListener("click", async () => {
  rlMenu(false);
  const c = needClient("rl-status");
  if (!c) return;
  try { say("rl-status", await invoke("restore_realmlist", { client: c.id }), "ok"); await refresh(); renderRealms(); }
  catch (e) { sayErr("rl-status", e); }
});
$("rl-join").addEventListener("click", async () => {
  const c = needClient("rl-status");
  if (!c) return;
  const link = $("rl-invite").value.trim();
  if (!link) return say("rl-status", "Paste the invite link first.", "bad");
  try {
    const j = await invoke("join_invite", { client: c.id, link });
    say("rl-status", `${j.name || "The realm"} is open for this PC; ${c.name} now points at ${j.address}. Press PLAY.`, "ok");
    $("rl-invite").value = "";
    await refresh();
  } catch (e) { sayErr("rl-status", e); }
});

// ------------------------------------------------------------------ Host
let kit = null;
const NO_KIT = { dir: null, is_kit: false, problems: [], seeds: [], realm: null };
async function loadHost() {
  // no answer from the core: the page still opens on Start (the setup), never an empty tab
  try { kit = (await invoke("host_info")) || Object.assign({}, NO_KIT); } catch (e) { sayErr("host-status-line", e); kit = Object.assign({}, NO_KIT); }
  renderHost();
}

function hostRealmId() {
  if (kit && kit.realm) return kit.realm.realm_id;
  const s = kit && kit.seeds.find((x) => x.in_kit);
  return s ? s.realm_id : null;
}

function renderHost() {
  $("host-kit").textContent = kit.dir
    ? (kit.is_kit ? `Host pack: ${kit.dir}` : `Chosen folder: ${kit.dir}`)
    : "No Host pack folder chosen yet.";
  const probs = $("host-problems");
  probs.hidden = !kit.problems.length;
  probs.replaceChildren(...kit.problems.map((p) => el("li", "", p)));
  const seeds = $("host-seeds");
  seeds.replaceChildren();
  const want = state.windows ? "bat" : "sh";
  for (const s of kit.seeds) {
    if (s.kind !== want) continue;
    const card = el("div", "card");
    const top = el("div", "top");
    top.append(el("span", "name", s.file_name), el("span", "build", s.in_kit ? "In the Host pack" : "In Downloads"));
    const acts = el("div", "acts");
    if (s.in_kit) {
      const b = el("button", "btn small", "Start this realm");
      b.disabled = !kit.is_kit;
      b.addEventListener("click", () => hostStart(s.file_name));
      acts.append(b);
    } else {
      const b = el("button", "btn small", "Copy into the Host pack");
      b.disabled = !kit.is_kit;
      b.addEventListener("click", async () => {
        try { kit = await invoke("host_copy_seed", { fileName: s.file_name }); renderHost(); say("host-status-line", "Copied: now start it.", "ok"); }
        catch (e) { sayErr("host-status-line", e); }
      });
      acts.append(b);
    }
    const meta = el("div", "meta");
    meta.append(el("span", "", `Your realm file from the website (realm ${s.realm_id}). It holds your realm's key: keep it to yourself.`));
    card.append(top, meta, acts);
    seeds.append(card);
  }
  $("host-start").disabled = !kit.is_kit;
  $("host-start").textContent = kit.realm ? `Start ${kit.realm.name || "my realm"}` : "Start my realm";
  const rid = hostRealmId();
  $("host-card").hidden = !rid;
  if (rid) {
    $("host-name").textContent = (kit.realm && kit.realm.name) || "Your realm";
    hostStatus();
  }
  document.dispatchEvent(new CustomEvent("leyline:kit", { detail: kit }));   // hostconsole.js: the console or the setup start
}

async function hostStart(seed) {
  say("host-status-line", "Starting the Host pack…");
  try { say("host-status-line", await invoke("host_start", seed ? { seed } : {}), "ok"); }
  catch (e) { sayErr("host-status-line", e); }
  setTimeout(hostStatus, 20000);
}

async function hostStatus() {
  const rid = hostRealmId();
  if (!rid) return;
  const set = (cls, text, detail) => {
    $("host-state").className = "srv-state " + cls;
    $("host-state-text").textContent = text;
    $("host-detail").textContent = detail;
  };
  set("", "CHECKING…", "");
  try {
    const s = await invoke("host_status", { realmId: rid });
    const counts = [s.players != null ? `Players: ${s.players}` : "", s.bots != null ? `Bots: ${s.bots}` : ""].filter(Boolean);
    if (s.online) {
      set("is-online", s.listed ? "ONLINE · ON THE REALM LIST" : "ONLINE",
        [...counts, s.visibility === "private" ? "Private: friends join with your invite link" : "", s.address ? `Realmlist: ${s.address}` : ""].filter(Boolean).join(" · "));
    } else {
      set("is-offline", "OFFLINE", "The relay knows your realm, but your PC is not connected. Start it above.");
    }
  } catch (e) {
    set("is-partial", "NOT SEEN YET", oops(e, "The relay hasn't seen your realm yet."));
  }
}

$("host-pick").addEventListener("click", async () => {
  const p = await invoke("pick_host_kit").catch(() => null);
  if (!p) return;
  try { kit = await invoke("set_host_kit", { path: p }); renderHost(); }
  catch (e) { sayErr("host-status-line", e); }
});
$("host-start").addEventListener("click", () => hostStart(null));
$("host-refresh").addEventListener("click", () => loadHost());

// ------------------------------------------------------------------ the launcher's own updates
// The core checks at start and every 6 hours and downloads in the background (app.rs). The UI only shows it:
// "Update ready, restart" in the title bar, and the channel and state in Settings.
let upd = null;
function renderUpdate() {
  if (!upd) return;
  const i = upd.info || {};
  $("upd-channel").value = upd.channel || "stable";
  $("tb-update").hidden = !(upd.ready || (upd.mode === "link" && i.newer));
  $("tb-update").textContent = upd.ready ? "Update ready, restart" : `Leyline ${i.latest} is out`;
  $("tb-update").title = upd.ready
    ? (upd.game_running ? "Close your game first: Leyline restarts only when no game is open" : `Restart into Leyline ${upd.ready}`)
    : "Open the release page";
  $("upd-restart").hidden = !upd.ready;
  $("upd-open").hidden = !i.url;
  let text = "", kind = "";
  if (upd.checking) text = "Checking…";
  else if (upd.downloading) text = `Downloading Leyline ${i.latest} in the background…`;
  else if (upd.ready) { text = `Leyline ${upd.ready} is ready (you have ${i.current}). Restart when you like.` + (upd.game_running ? " Your game is open: restart after you close it." : ""); kind = "ok"; }
  else if (i.newer) { text = `Leyline ${i.latest} is out (you have ${i.current}). ${upd.note || ""}`; kind = "ok"; }
  else if (i.latest) { text = `You have the newest Leyline on the ${upd.channel} channel (${i.current}).` + (i.from_cache ? " (offline: from the last check)" : ""); kind = "ok"; }
  else if (upd.checked_at) { text = i.error ? oops(i.error, OOPS["upd-status"]) : "No launcher releases on this channel yet."; kind = i.error ? "warn" : ""; }
  if (upd.error && !upd.ready && !upd.downloading) { text += (text ? " " : "") + oops(upd.error, "The download didn't finish: Leyline tries again later."); kind = "warn"; }
  say("upd-status", text, kind);
}
async function loadUpdateState() {
  try { upd = await invoke("launcher_update_state"); renderUpdate(); } catch (_) { /* preview page */ }
}
async function checkUpdate() {
  say("upd-status", "Checking…");
  try { upd = await invoke("launcher_update_check"); renderUpdate(); }
  catch (e) { sayErr("upd-status", e); }
}
async function restartToUpdate() {
  if (!upd) return;
  if (!upd.ready) { if (upd.info && upd.info.url) openUrl(upd.info.url); return; }
  try { await invoke("launcher_update_restart"); }
  catch (e) { sayErr("upd-status", e); sayErr("play-status", e); await loadUpdateState(); }
}
$("upd-check").addEventListener("click", checkUpdate);
$("upd-restart").addEventListener("click", restartToUpdate);
$("upd-open").addEventListener("click", () => { if (upd && upd.info && upd.info.url) openUrl(upd.info.url); });
$("tb-update").addEventListener("click", restartToUpdate);
$("upd-channel").addEventListener("change", async () => {
  say("upd-status", "Saved. Checking the new channel…");
  try { upd = await invoke("set_update_channel", { channel: $("upd-channel").value }); renderUpdate(); }
  catch (e) { sayErr("upd-status", e); }
});
setInterval(loadUpdateState, 60000);

// ------------------------------------------------------------------ for Home's gallery and rows (home.js, loaded after this)
// Home's "Join <HANGOUT.name>" slide: select the Hangout and press PLAY. With a 3.3.5a client, that client on
// the Hangout; without one, browser play (the Hangout plays in the browser, nothing to install).
function playHangout() {
  $("play-realm").value = "official";
  const c = currentClient();
  const own = c && c.build === "3.3.5a" ? c : (state && state.settings.clients.find((x) => x.build === "3.3.5a"));
  if (own) {
    $("play-client").value = own.id;
    if (mode === "browser") setMode("online");
  } else if (mode !== "browser") setMode("browser");
  realmChanged();
  saveSelection();
  $("play-form").requestSubmit();
}

window.LeylineApp = {
  news: () => news, realms: () => realmsCache, catalog: () => catalog, mode: () => mode, setMode, openLink, playHangout, HANGOUT,
  realmIcon, realmVersion, hiddenBuild, nameHue,
  state: () => state,   // addons.js: the clients
};

// ------------------------------------------------------------------ start
renderNews();
renderModTiles();
refresh().then(() => {
  setMode(mode);
  loadCatalog(true).then(handleDeepLink);
  loadRealms(true);
  loadUpdateState();
  loadNews();
  readKit();   // the realm picker's My Den: hosted on this PC or not
  setupDrop();
  let page = "play";
  try { page = localStorage.getItem("leyline.page") || "play"; } catch (_) { /* fine */ }
  show(page);   // an unknown or old page id: resolvePage maps it, or Home
}).catch((e) => {
  document.body.prepend(el("p", "status bad", oops(e, "Leyline couldn't start. Close it and open it again, or ask on the Discord.")));
});
