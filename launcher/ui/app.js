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
    "Host your own realm from the Host page with the host kit",
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
// The side menu matches the website's (stream/hub.py nav_items): Home (play), Realms, Mods, Host, Community, News,
// then Settings and Help. Mods and Community are one page each with tabs. The page ids from before (mymods,
// discover, friends, hub) still work everywhere: show() maps them to the page + tab, so a remembered page, a
// data-page-go button or a leyline:// link lands where it used to; a page with tabs alone opens its last tab. Modes has no menu item
// but is still a page (Home's featured mode, Realms › MODES, show("modes")).
const TABS = { mods: ["installed", "discover"], community: ["friends", "hub"] };
const ALIASES = { mymods: ["mods", "installed"], installed: ["mods", "installed"], discover: ["mods", "discover"],
  friends: ["community", "friends"], hub: ["community", "hub"] };
const loaders = { "mods:discover": () => loadCatalog(), "mods:installed": () => loadInstalled(), realms: () => loadRealms(), host: () => loadHost() };
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
// Home's hero gallery and its News row read NEWS too (home.js); the News page lists every entry.
function renderNews() {
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
  renderClientPickers();
}

// ------------------------------------------------------------------ realm: the chosen realm, the rows, live status
function isOfficial() { return $("play-realm").value === "official"; }
function chosenRealm() { return isOfficial() ? state.official_realm : $("play-custom").value.trim(); }
// The official realm's name comes from the realm listing (the network's sample block: "Dalaran Hangout" once the
// Leyline brand is on, the Sample Hangout while it runs); before the list arrives, a plain label.
function officialName() {
  const o = (realmsCache || []).find((x) => x.official);
  return (o && o.name) || "Official realm";
}
function realmLabel() {
  if (isOfficial()) return officialName();
  const a = chosenRealm();
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
    b.append(realmIcon(name, official, "sm"), txt, dot);
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
    add(beacon ? beacon.name : custom, false, realmVersion(beacon));
  }
}

// Home's SERVER card: the chosen realm's icon, name and client version (the players bar comes with its status).
function renderSrvHead() {
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
    $("srv-state").className = "srv-state " + cls;
    $("srv-state-text").textContent = line;
    $("srv-detail").textContent = detail;
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
  document.dispatchEvent(new CustomEvent("leyline:mode", { detail: { mode: m } }));
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
  renderClientMenu();
  $("play-empty").hidden = s.clients.length !== 0;
  $("client-change").textContent = s.clients.length ? "CHANGE GAME FOLDER" : "ADD YOUR GAME FOLDER";
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
  if (menuOpen && !e.target.closest(".pb-pick")) closeClientMenu(false);
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
  try { addClient(await invoke("pick_folder")); } catch (e) { say("cl-status", String(e), "bad"); }
});
$("ff-browser").addEventListener("click", () => { setMode("browser"); show("play"); });
$("pb-realm-btn").addEventListener("click", () => show("realms"));

function renderPlayBar() {
  if (!state) return;
  const c = currentClient();
  const bar = $("play-headline").parentElement;
  let head = "READY TO PLAY", detail = "", warn = false;
  if (mode === "browser" && officialGamedata === false) {
    head = "BROWSER PLAY · NEEDS YOUR GAME FOLDER"; warn = true;
    detail = "The browser will ask for your game folder (it stays on your PC)";
  } else if (mode === "browser") {
    head = "READY · NOTHING TO INSTALL";
  } else if (!c) {
    head = "SET UP YOUR GAME CLIENT"; warn = true;
    detail = "Point Leyline at your game folder";
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
  $("pb-realm").textContent = mode === "browser" ? "Plays in your browser" : realmLabel();
  // the realm's icon and client version beside its name (none in the browser)
  const official = isOfficial();
  const rv = mode === "browser" ? null : official ? "3.3.5a" : realmVersion(realmAt(chosenRealm()));
  $("pb-realm-ver").hidden = !rv;
  $("pb-realm-ver").textContent = rv || "";
  $("pb-realm-ic").hidden = mode === "browser";
  if (mode !== "browser") fillRealmIcon($("pb-realm-ic"), realmLabel(), official);
  renderClientMenu();
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
    top.append(el("span", "name", c.name), el("span", "build", buildLabel(c.build)));
    const tags = el("div", "tags");
    if (buildTag(c.build) === "other") tags.append(el("span", "tag warn", `Other build${c.exe_version ? " " + c.exe_version : ""}: realms only, no mods`));
    else tags.append(el("span", "tag", `Addons: Interface ${{"1.12.1": "11200", "2.4.3": "20400", "3.3.5a": "30300", "4.3.4": "40300", "5.4.8": "50400"}[c.build]}`));
    if (BUILDS[c.build]) tags.append(el("span", "tag", `Realm address: ${BUILDS[c.build].file}`));
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
    card.append(top, tags, meta, acts);
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
    let msg = `Added ${r.profile.name}: ${d.build_label}, detected ${how}.`;
    if (d.build === "other") msg += " Leyline does not know this build: you can play realms with it, but it offers no mods for it.";
    if (!d.complete) msg += " Some files are missing: " + d.missing.join(", ");
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
  $("set-count").checked = state.settings.count_installs !== false;
}
$("set-count").addEventListener("change", async () => {
  const on = $("set-count").checked;
  try {
    await invoke("set_count_installs", { on });
    state.settings.count_installs = on;
    say("count-status", on ? "Your installs count toward the rankings." : "Your installs are not counted.", "ok");
  } catch (e) { $("set-count").checked = !on; say("count-status", String(e), "bad"); }
});
$("set-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const wine = { enabled: $("wine-on").checked, command: $("wine-cmd").value.trim() || "wine", prefix: $("wine-prefix").value.trim() };
  try { await invoke("set_wine", { wine }); await refresh(); say("set-status", "Saved.", "ok"); }
  catch (e) { say("set-status", String(e), "bad"); }
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
  if (!c) { say(statusId, "Add your game client first (CHANGE GAME FOLDER on Home).", "bad"); return null; }
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
  try { await invoke("open_url", { url }); } catch (e) { say("play-status", String(e), "bad"); }
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
function renderSorts() {
  document.querySelectorAll("#cat-sorts [data-sort]").forEach((b) => {
    const on = b.dataset.sort === catFilter.sort;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  $("cat-kind").value = catFilter.kind;
}
document.querySelectorAll("#cat-sorts [data-sort]").forEach((b) => b.addEventListener("click", async () => {
  catFilter.sort = b.dataset.sort;
  try { localStorage.setItem("leyline.catSort", catFilter.sort); } catch (_) { /* fine */ }
  await loadRanks(false);
  renderCatalog();
}));
$("cat-kind").addEventListener("change", async () => {
  catFilter.kind = $("cat-kind").value;
  await loadRanks(false);
  renderCatalog();
});

async function loadCatalog(quiet) {
  if (!quiet) say("cat-status", "Loading the Workshop…");
  try {
    catalog = await invoke("mods_catalog");
    if (window.LeylineThemes) catalog = window.LeylineThemes.takeThemes(catalog); // themes.js: theme packs go under Discover › Themes
    catalogNames = catalog.projects.map((p) => p.name);
    const when = catalog.saved_at ? new Date(catalog.saved_at * 1000).toLocaleString() : "an earlier visit";
    if (catalog.from_cache) say("cat-status", `Offline: showing the Workshop as it was ${when}.`, "warn");
    else say("cat-status", `${catalog.projects.length} projects in the Workshop.`, "ok");
  } catch (e) {
    say("cat-status", String(e), "bad");
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
  const counts = {};
  for (const p of catalog.projects) counts[p.category] = (counts[p.category] || 0) + 1;
  const chips = $("cat-chips");
  chips.replaceChildren();
  const chip = (id, label, n) => {
    const b = el("button", "chip-btn" + (catFilter.cat === id ? " on" : ""), n === undefined ? label : `${label} ${n}`);
    b.type = "button";
    b.addEventListener("click", () => { catFilter.cat = id; renderCatalog(); });
    chips.append(b);
  };
  chip("", "All", catalog.projects.length);
  for (const k of catalog.categories) chip(k.id, k.name, counts[k.id] || 0);

  renderSorts();
  const grid = $("cat-grid");
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
    if (q && !(`${p.name} ${p.description} ${p.author} ${p.category}`.toLowerCase().includes(q))) return false;
    return true;
  });
  if (!list.length) {
    const cat = catalog.categories.find((k) => k.id === catFilter.cat);
    grid.append(el("p", "hint", catalog.projects.length
      ? (cat && !counts[cat.id] ? `No mods in ${cat.name} yet. Make the first one: see MAKE A MOD.` : "Nothing matches.")
      : "The Workshop list is not here yet."));
    return;
  }
  for (const p of list) grid.append(projectCard(p, c));
}

// A card's numbers and its rating stars. Rating needs the Community › Friends sign-in (the same website sign-in).
function statsLine(p) {
  const m = ranked && ranked.metrics ? ranked.metrics[p.id] : null;
  const st = el("div", "stats");
  if (m) {
    const r = m.rating || {};
    st.append(el("span", "rating", r.n ? `★ ${Number(r.avg).toFixed(1)} · ${r.n} rating${r.n === 1 ? "" : "s"}` : "No ratings yet"));
    st.append(el("span", "installs", `${m.installs.all} install${m.installs.all === 1 ? "" : "s"}`));
    if (m.rising) st.append(el("span", "tag good", "Rising"));
  }
  const stars = el("span", "stars");
  stars.setAttribute("role", "group");
  stars.setAttribute("aria-label", `Rate ${p.name}`);
  for (let n = 1; n <= 5; n++) {
    const b = el("button", "", "★");
    b.type = "button";
    b.title = `${n} star${n > 1 ? "s" : ""}`;
    b.setAttribute("aria-label", `Rate ${n} star${n > 1 ? "s" : ""}`);
    b.addEventListener("click", () => rateProject(p, n, stars));
    stars.append(b);
  }
  st.append(stars);
  return st;
}
async function rateProject(p, n, box) {
  try {
    const r = await invoke("mod_rate", { project: p.id, stars: n });
    box.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i < n));
    if (ranked && ranked.metrics && ranked.metrics[p.id] && r && r.rating) ranked.metrics[p.id].rating = r.rating;
    say("cat-status", `Thanks: you rated ${p.name} ${n} star${n > 1 ? "s" : ""}.`, "ok");
  } catch (e) {
    say("cat-status", String(e) === "signed_out" ? "Sign in under Community › Friends to rate mods (the same sign-in as the website)." : String(e), "bad");
  }
}

function projectCard(p, c) {
  const card = el("article", "mod-card" + (p.id === linkedId ? " linked" : ""));
  card.dataset.id = p.id;
  const top = el("div", "top");
  top.append(el("b", "name", p.name));
  if (p.version) top.append(el("span", "ver-s", "v" + p.version));
  const cat = catalog.categories.find((k) => k.id === p.category);
  const tags = el("div", "tags");
  tags.append(el("span", "tag", p.source === "packaged" ? "Packaged" : "Community link"));
  if (cat) tags.append(el("span", "tag", cat.name));
  tags.append(el("span", "tag", p.builds.length ? p.builds.map((b) => (b === "any" ? "Any build" : b)).join(" · ") : "Any build"));
  if (p.on_wrath) tags.append(el("span", "tag gold", "On the Wrath realm"));
  const fits = fitsClient(p, c);
  if (c && !fits) tags.append(el("span", "tag warn", `Not for ${c.build}`));
  card.append(top, tags, el("p", "desc", p.description || ""));
  const credit = el("p", "credit", p.credits || [p.author, p.licence || "licence not stated"].filter(Boolean).join(" · "));
  card.append(credit, statsLine(p));
  const acts = el("div", "acts");
  const mine = installed.find((m) => m.key === p.id);
  if (p.source === "packaged" && p.download) {
    const b = el("button", "btn small");
    b.type = "button";
    if (!c) { b.textContent = "INSTALL"; b.disabled = true; b.title = "Add a game client first"; }
    else if (!fits) { b.textContent = "INSTALL"; b.disabled = true; b.title = `Made for ${p.builds.join(" / ")} clients`; }
    else if (mine && mine.update) b.textContent = `UPDATE TO ${mine.update}`;
    else if (mine) { b.textContent = "INSTALLED"; b.disabled = true; }
    else b.textContent = "INSTALL";
    b.addEventListener("click", () => installProject(p, b));
    acts.append(b);
    if (p.kind === "realm") b.title = "A realm mod: it runs on a realm that installs it, not in your game";
  } else if (p.source !== "packaged") {
    acts.append(el("span", "hint", "Get it from its page, then drop the zip on Mods › Installed."));
  }
  if (p.page) acts.append(linkBtn("Page", p.page));
  if (p.repo) acts.append(linkBtn("Source", p.repo));
  if (p.author_url) acts.append(linkBtn("Author", p.author_url));
  card.append(acts);
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
  btn.textContent = "INSTALLING…";
  const was = installed.find((m) => m.key === p.id);
  say("cat-status", `Downloading ${p.name}…`);
  try {
    const m = await withNativeOk(() => invoke("mod_install", { client: c.id, project: p.id }));
    say("cat-status", installedText(was ? "Updated" : "Installed", m, c), m.warnings.length ? "warn" : "ok");
  } catch (e) {
    say("cat-status", String(e), "bad");
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
  say("cat-status", c ? `From the hub: ${p.name}. Press INSTALL to put it in ${c.name}.` : `From the hub: ${p.name}. Add your game client first, then press INSTALL.`, "ok");
}

// The in-game Host window (leyline://host?<choices>, checked by deeplink.rs): the Host page with the host's choices and
// "MAKE IT ON THE WEBSITE" (the website's form filled in; the realm key is still made on this PC). From the game's
// "Your realm" tab (leyline://host?manage=<what>): the Host page with what to do for that control. Nothing starts.
const HOST_WORDS = {
  core: { azerothcore: "AzerothCore", cmangos: "CMaNGOS" },
  preset: { dalaran: "Dalaran hangout", main: "Classic levelling", brawl: "Brawl", progression: "Progression", vanillaplus: "Vanilla+",
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
  bots: ["Bots", "In your host kit folder: leyline options --bots 40 (0 turns them off), then restart the realm (leyline stop, then leyline host)."],
  rates: ["Rates", "In your host kit folder: leyline options --xp 3 --loot 1 --rep 2 (1 to 10), then restart the realm (leyline stop, then leyline host)."],
  signup: ["Sign-up", "In your host kit folder: leyline signup open (anyone), leyline signup invite (invite link only) or leyline signup off."],
  list: ["The Leyline list", "In your host kit folder: leyline public (on the list) or leyline private (invite link only). The list changes within a minute."],
  invite: ["Invite link", "Your realm's invite link is below, under YOUR REALM: COPY INVITE LINK. NEW INVITE LINK stops the old one."],
};

function hostChoices(id) {
  const p = new URLSearchParams(id);
  return HOST_LABELS.filter(([k]) => p.has(k)).map(([k, label]) => {
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
    catch (e) { say("host-status-line", String(e), "bad"); }
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
    if (!quiet) say("mods-status", String(e), "bad");
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
  $("mods-client-note").textContent = c ? `${buildLabel(c.build)} · ${c.path}` : "";
  const list = $("mods-list");
  list.replaceChildren();
  const ups = installed.filter((m) => m.update);
  $("mods-update-all").hidden = ups.length < 2;
  $("mods-update-all").textContent = `UPDATE ALL (${ups.length})`;
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
    const tog = el("button", "btn small", m.enabled ? "TURN OFF" : "TURN ON");
    tog.addEventListener("click", () => modAction("mod_set_enabled", { client: c.id, key: m.key, on: !m.enabled }, m.enabled ? `Turned off ${m.name}.` : `Turned on ${m.name}.`));
    acts.append(tog);
    if (m.update) {
      const up = el("button", "btn small", "UPDATE");
      up.addEventListener("click", async () => {
        up.disabled = true;
        up.textContent = "UPDATING…";
        say("mods-status", `Downloading ${m.name} v${m.update}…`);
        try { say("mods-status", await updateMod(c, m), "ok"); }
        catch (e) { say("mods-status", String(e), "bad"); }
        await loadInstalled();
        renderCatalog();
      });
      acts.append(up);
    }
    // One click: removal takes out only the files Leyline put in and you have not changed, so nothing of yours goes.
    const rm = el("button", "btn small danger", "REMOVE");
    rm.addEventListener("click", async () => {
      rm.disabled = true;
      rm.textContent = "REMOVING…";
      try {
        const r = await invoke("mod_uninstall", { client: c.id, key: m.key });
        let t = `Removed ${m.name}: ${r.removed_files} files.`;
        if (r.changed && r.changed.length) t += ` Left the files you changed: ${r.changed.join(", ")}.`;
        if (r.kept.length) t += ` Kept files Leyline did not put there: ${r.kept.join(", ")}.`;
        if (m.source === "catalog") t += " Install it again any time from Mods › Discover.";
        say("mods-status", t, r.changed && r.changed.length ? "warn" : "ok");
      } catch (e) { say("mods-status", String(e), "bad"); }
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
  catch (e) { say("mods-status", String(e), "bad"); }
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
    catch (e) { say("mods-status", `${m.name}: ${e}`, "bad"); break; }
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
    realmsCache = l.realms;
    realmNames = l.realms.map((r) => r.name);
    const when = l.saved_at ? new Date(l.saved_at * 1000).toLocaleString() : "an earlier visit";
    const n = l.realms.length - 1;
    networkTotals = l.network || null;
    if (l.from_cache) say("rl-status", `Offline: showing the list as it was ${when}.`, "warn");
    else if (l.error) say("rl-status", "The community list is not reachable right now: " + l.error, "warn");
    else say("rl-status", "", "ok");   // the count is already on the network line above
    fillRealmFilters();
  } catch (e) {
    say("rl-status", String(e), "bad");
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
const TAG_LABELS = { blizzlike: "Blizzlike", boosted: "Boosted", custom: "Custom", pvp: "PvP", rp: "RP", hangout: "Hangout", bots: "Bots" };
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
function networkLine(t) {
  if (!t) return "";
  return `${t.realms} realm${t.realms === 1 ? "" : "s"} · ${t.players} player${t.players === 1 ? "" : "s"} online` + (t.bots ? ` · ${t.bots} bots` : "");
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

function renderRealms() {
  const box = $("rl-list");
  box.replaceChildren();
  const now = state.settings.selected_realm;
  const mine = $("rl-mine").checked;
  if ($("rl-net")) $("rl-net").textContent = networkLine(networkTotals);
  let shown = 0;
  for (const r of realmsCache) {
    const fit = clientFor(r);
    if (mine && !fit) continue;
    if (!realmMatches(r)) continue;
    shown++;
    const live = r.state === "live";
    const card = el("article", "realm-card rl" + (r.address && r.address === now ? " on" : "") + (r.featured ? " featured" : "")
      + (r.official ? " official" : "") + (live ? "" : " off"));
    // like the website's realm list (stream/hub.py realm_row): icon · name, version, badges, meta · players · actions
    const main = el("div", "rl-main");
    const title = el("div", "rl-title");
    title.append(el("b", "name", r.name));
    const ver = realmVersion(r);
    if (ver) { const v = el("span", "rl-ver", ver); v.title = "Game client version"; title.append(v); }
    const badge = (text, cls, tip) => { const b = el("span", "rl-bdg" + (cls ? " " + cls : ""), text); if (tip) b.title = tip; title.append(b); };
    if (r.official) badge("Official", "o");
    if (r.official && r.temporary) badge("Temporary", "warn");
    if (r.featured) badge("Featured", "f");
    if (r.verified) badge("Verified", "v", "Verified host: checked by Leyline staff");
    if (r.is_new) badge("New", "");
    if (r.direct && p2pHosting) badge("Direct connect available", "v");
    if (r.build && !fit) badge(`Needs your own ${r.build} client`, "warn");
    const meta = el("div", "rl-meta");
    const m = (text, cls) => { if (text) meta.append(el("span", cls || "", text)); };
    m(r.official ? "Run by Leyline" : "Community realm");
    m(r.kind);
    m(CORE_LABELS[r.core] || "Other server");
    if (r.region) m((REGION_LABELS[r.region] || r.region) + (r.region_estimated ? " (estimated)" : ""));
    for (const t of r.tags || []) if (!r.official) m(TAG_LABELS[t] || t);
    m(r.language);
    const u = r.uptime_7d != null ? r.uptime_7d : r.uptime_24h;
    if (u != null) m(`${u}% up · ${r.uptime_7d != null ? "7 d" : "24 h"}`, u >= 95 ? "ok" : u >= 75 ? "" : "warn");
    main.append(title, meta);
    if (r.tagline) main.append(el("p", "desc", r.tagline));
    if (r.rules && r.rules.length) {
      const ul = el("ul", "rules");
      ul.replaceChildren(...r.rules.slice(0, 4).map((x) => el("li", "", x)));
      main.append(ul);
    }
    if (!r.address) main.append(el("div", "hint", "No desktop address yet: PLAY asks the relay"));
    // players online, with a small fill bar
    const pop = el("div", "rl-pop");
    const st = el("span", "state " + (live ? "is-online" : "is-offline"));
    st.append(el("span", "dot"));
    if (!live) st.append(el("span", "", "Offline"));
    else if (r.players == null) st.append(el("span", "", "Online"));
    else {
      const n = el("span", "");
      n.append(el("b", "rl-n", String(r.players)), document.createTextNode(`${r.max_players ? " of " + r.max_players : ""} playing`));
      st.append(n);
    }
    pop.append(st);
    if (live && r.bots) pop.append(el("small", "rl-bots", `${r.bots} bots`));
    if (live) {
      const bar = el("span", "rl-bar");
      bar.setAttribute("aria-hidden", "true");
      const fill = el("i");
      fill.style.width = playersFill(r.players, r.max_players) + "%";
      bar.append(fill);
      pop.append(bar);
    }
    card.append(realmIcon(r.name, r.official), main, pop);
    const acts = el("div", "acts");
    const play = el("button", "btn small primary", "PLAY");
    if (!state.settings.clients.length) { play.disabled = true; play.title = "Add a game client first"; }
    else if (!fit) { play.title = `This realm runs ${r.build}: PLAY says what is missing`; }
    else play.title = `Plays with ${fit.name}`;
    play.addEventListener("click", () => playRealm(r, play));
    acts.append(play);
    if (heroKeyOn && !r.official && r.realm_id && r.state === "live") {
      const hk = el("button", "btn small", "Sign in with your Hero Key");
      hk.title = "No account to make: your Hero Key signs you in here (a one-time password, shown below)";
      hk.disabled = play.disabled;
      hk.addEventListener("click", () => playRealmHeroKey(r, hk));
      acts.append(hk);
    }
    if (r.join_url) acts.append(linkBtn("Make an account", r.join_url));
    if (r.discord) acts.append(linkBtn("Discord", r.discord));
    if (r.report_url && !r.official) { const rep = linkBtn("Report", r.report_url); rep.title = "Report this realm to Leyline staff (on the website)"; acts.append(rep); }
    if (r.address) { const ad = el("code", "rl-addr", r.address); ad.title = "Realmlist: the realm address for a desktop client"; acts.append(ad); }
    card.append(acts);
    box.append(card);
  }
  if (realmsCache.length <= 1) box.append(el("p", "hint", "No community realms listed right now. Host one: see Host your own below."));
  else if (shown <= 1 && mine) box.append(el("p", "hint", "None of the listed realms fits your clients. Untick the box to see them all."));
  else if (shown <= 1) box.append(el("p", "hint", "No community realms match these filters."));
}
for (const id of ["rl-f-build", "rl-f-tag", "rl-f-region", "rl-f-lang", "rl-f-now"]) {
  if ($(id)) $(id).addEventListener("change", () => renderRealms());
}
if ($("rl-host")) $("rl-host").addEventListener("click", () => show("host"));
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
    const msg = await invoke("play_realm", { client: picked.id, slug: r.slug });
    say("rl-status", msg + (r.official ? "" : " First time here? Make your account with Make an account."), "ok");
    await refresh();
    renderRealms();
  } catch (e) { say("rl-status", String(e), "bad"); }
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
  } catch (e) { say("rl-status", String(e), "bad"); }
  btn.disabled = false;
}

$("rl-refresh").addEventListener("click", () => loadRealms());
$("rl-back").addEventListener("click", async () => {
  const c = needClient("rl-status");
  if (!c) return;
  try { say("rl-status", await invoke("back_to_official", { client: c.id }), "ok"); await refresh(); renderRealms(); }
  catch (e) { say("rl-status", String(e), "bad"); }
});
$("rl-restore").addEventListener("click", async () => {
  const c = needClient("rl-status");
  if (!c) return;
  try { say("rl-status", await invoke("restore_realmlist", { client: c.id }), "ok"); await refresh(); renderRealms(); }
  catch (e) { say("rl-status", String(e), "bad"); }
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
  } catch (e) { say("rl-status", String(e), "bad"); }
});

// ------------------------------------------------------------------ Host
let kit = null;
async function loadHost() {
  try { kit = await invoke("host_info"); } catch (e) { say("host-status-line", String(e), "bad"); return; }
  renderHost();
}

function hostRealmId() {
  if (kit && kit.realm) return kit.realm.realm_id;
  const s = kit && kit.seeds.find((x) => x.in_kit);
  return s ? s.realm_id : null;
}

function renderHost() {
  $("host-kit").textContent = kit.dir
    ? (kit.is_kit ? `Host kit: ${kit.dir}` : `Chosen folder: ${kit.dir}`)
    : "No kit folder chosen yet.";
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
    top.append(el("span", "name", s.file_name), el("span", "build", s.in_kit ? "IN THE KIT" : "IN DOWNLOADS"));
    const acts = el("div", "acts");
    if (s.in_kit) {
      const b = el("button", "btn small", "START THIS REALM");
      b.disabled = !kit.is_kit;
      b.addEventListener("click", () => hostStart(s.file_name));
      acts.append(b);
    } else {
      const b = el("button", "btn small", "COPY INTO THE KIT");
      b.disabled = !kit.is_kit;
      b.addEventListener("click", async () => {
        try { kit = await invoke("host_copy_seed", { fileName: s.file_name }); renderHost(); say("host-status-line", "Copied: now start it.", "ok"); }
        catch (e) { say("host-status-line", String(e), "bad"); }
      });
      acts.append(b);
    }
    const meta = el("div", "meta");
    meta.append(el("span", "", `Your realm file from the website (realm ${s.realm_id}). It holds your realm's key: keep it to yourself.`));
    card.append(top, meta, acts);
    seeds.append(card);
  }
  $("host-start").disabled = !kit.is_kit;
  $("host-start").textContent = kit.realm ? `START ${kit.realm.name.toUpperCase() || "MY REALM"}` : "START MY REALM";
  const rid = hostRealmId();
  $("host-card").hidden = !rid;
  if (rid) {
    $("host-name").textContent = (kit.realm && kit.realm.name) || "Your realm";
    hostStatus();
  }
  document.dispatchEvent(new CustomEvent("leyline:kit", { detail: kit }));   // hostconsole.js: the console or the setup start
}

async function hostStart(seed) {
  say("host-status-line", "Starting the host kit…");
  try { say("host-status-line", await invoke("host_start", seed ? { seed } : {}), "ok"); }
  catch (e) { say("host-status-line", String(e), "bad"); }
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
    set("is-partial", "NOT SEEN YET", String(e));
  }
}

$("host-pick").addEventListener("click", async () => {
  const p = await invoke("pick_host_kit").catch(() => null);
  if (!p) return;
  try { kit = await invoke("set_host_kit", { path: p }); renderHost(); }
  catch (e) { say("host-status-line", String(e), "bad"); }
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
  else if (upd.checked_at) { text = i.error ? "Could not check: " + i.error : "No launcher releases on this channel yet."; kind = i.error ? "warn" : ""; }
  if (upd.error && !upd.ready && !upd.downloading) { text += (text ? " " : "") + upd.error; kind = "warn"; }
  say("upd-status", text, kind);
}
async function loadUpdateState() {
  try { upd = await invoke("launcher_update_state"); renderUpdate(); } catch (_) { /* preview page */ }
}
async function checkUpdate() {
  say("upd-status", "Checking…");
  try { upd = await invoke("launcher_update_check"); renderUpdate(); }
  catch (e) { say("upd-status", String(e), "bad"); }
}
async function restartToUpdate() {
  if (!upd) return;
  if (!upd.ready) { if (upd.info && upd.info.url) openUrl(upd.info.url); return; }
  try { await invoke("launcher_update_restart"); }
  catch (e) { say("upd-status", String(e), "bad"); say("play-status", String(e), "bad"); await loadUpdateState(); }
}
$("upd-check").addEventListener("click", checkUpdate);
$("upd-restart").addEventListener("click", restartToUpdate);
$("upd-open").addEventListener("click", () => { if (upd && upd.info && upd.info.url) openUrl(upd.info.url); });
$("tb-update").addEventListener("click", restartToUpdate);
$("upd-channel").addEventListener("change", async () => {
  say("upd-status", "Saved. Checking the new channel…");
  try { upd = await invoke("set_update_channel", { channel: $("upd-channel").value }); renderUpdate(); }
  catch (e) { say("upd-status", String(e), "bad"); }
});
setInterval(loadUpdateState, 60000);

// ------------------------------------------------------------------ for Home's gallery and rows (home.js, loaded after this)
window.LeylineApp = {
  news: () => NEWS, realms: () => realmsCache, catalog: () => catalog, mode: () => mode, setMode, openLink,
  realmIcon, realmVersion, hiddenBuild, nameHue,
};

// ------------------------------------------------------------------ start
renderNews();
renderModTiles();
refresh().then(() => {
  setMode(mode);
  loadCatalog(true).then(handleDeepLink);
  loadRealms(true);
  loadUpdateState();
  setupDrop();
  let page = "play";
  try { page = localStorage.getItem("leyline.page") || "play"; } catch (_) { /* fine */ }
  show(page);   // an unknown or old page id: resolvePage maps it, or Home
}).catch((e) => {
  document.body.prepend(el("p", "status bad", "Leyline could not start: " + e));
});
