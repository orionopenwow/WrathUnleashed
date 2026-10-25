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
const loaders = { discover: () => loadCatalog(), mods: () => loadInstalled(), realms: () => loadRealms(), host: () => loadHost() };
let currentPage = "play";
function show(page) {
  currentPage = page;
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
  } else {
    $("cat-q").value = q;
    catFilter.cat = "";
    show("discover");
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
  renderClientPickers();
}

// ------------------------------------------------------------------ realm: the chosen realm, the rows, live status
function isOfficial() { return $("play-realm").value === "official"; }
function chosenRealm() { return isOfficial() ? state.official_realm : $("play-custom").value.trim(); }
function realmLabel() {
  if (isOfficial()) return "WrathUnleashed";
  const a = chosenRealm();
  const r = realmsCache.find((x) => x.address === a);
  return r ? r.name : (a || "Another realm");
}

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
  if (custom) {
    const beacon = realmsCache.find((x) => x.address === custom);
    add(beacon ? beacon.name : custom, false);
  }
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
    const beacon = realmsCache.find((x) => !x.official && x.address === realm && x.status_url);
    const s = await invoke("realm_status", beacon ? { realm, statusUrl: beacon.status_url } : { realm });
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
    detail = "PLAY takes you to your game clients: point Leyline at your game folder";
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

// ------------------------------------------------------------------ the client pickers on Mods, Discover, Realms
// They all follow the one selected client (the play bar's).
function renderClientPickers() {
  document.querySelectorAll(".client-pick").forEach((sel) => {
    sel.replaceChildren();
    for (const c of state.settings.clients) {
      const o = el("option", "", `${c.name}`);
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
const buildTag = (b) => (b === "1.12.1" ? "1.12" : b);
const fitsClient = (p, c) => !c || !p.builds.length || p.builds.includes("any") || p.builds.includes(buildTag(c.build)) || (c.build === "1.12.1" && p.builds.includes("1.12.1"));

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
const catFilter = { cat: "" };

async function loadCatalog(quiet) {
  if (!quiet) say("cat-status", "Loading the Workshop…");
  try {
    catalog = await invoke("mods_catalog");
    catalogNames = catalog.projects.map((p) => p.name);
    const when = catalog.saved_at ? new Date(catalog.saved_at * 1000).toLocaleString() : "an earlier visit";
    if (catalog.from_cache) say("cat-status", `Offline: showing the Workshop as it was ${when}.`, "warn");
    else say("cat-status", `${catalog.projects.length} projects in the Workshop.`, "ok");
  } catch (e) {
    say("cat-status", String(e), "bad");
  }
  renderModTiles();
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

  const grid = $("cat-grid");
  grid.replaceChildren();
  const list = catalog.projects.filter((p) => {
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

function projectCard(p, c) {
  const card = el("article", "mod-card");
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
  card.append(credit);
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
    acts.append(el("span", "hint", "Get it from its page, then drop the zip on My Mods."));
  }
  if (p.page) acts.append(linkBtn("Page", p.page));
  if (p.repo) acts.append(linkBtn("Source", p.repo));
  if (p.author_url) acts.append(linkBtn("Author", p.author_url));
  card.append(acts);
  return card;
}

async function installProject(p, btn) {
  const c = needClient("cat-status");
  if (!c) return;
  btn.disabled = true;
  btn.textContent = "INSTALLING…";
  say("cat-status", `Downloading ${p.name}…`);
  try {
    const m = await invoke("mod_install", { client: c.id, project: p.id });
    say("cat-status", `Installed ${m.name} into ${c.name}.` + (m.warnings.length ? " Note: " + m.warnings.join("; ") : ""), "ok");
  } catch (e) {
    say("cat-status", String(e), "bad");
  }
  await loadInstalled(true);
  renderCatalog();
}

$("cat-q").addEventListener("input", renderCatalog);
$("cat-fit").addEventListener("change", renderCatalog);

function renderModTiles() {
  const box = $("mod-tiles");
  box.replaceChildren();
  const picks = catalog.projects.filter((p) => p.source === "packaged").concat(catalog.projects.filter((p) => p.source !== "packaged")).slice(0, 3);
  for (let i = 0; i < 3; i++) {
    const p = picks[i];
    const t = el("button", "tile");
    t.type = "button";
    const txt = el("span", "tile-txt");
    txt.append(el("b", "", p ? p.name : "Mod catalog"), el("i", "", p ? (installed.some((m) => m.key === p.id) ? "Installed" : "In the Workshop") : "Loading…"));
    t.append(el("span", "tile-ico", (p ? p.name : "M").charAt(0).toUpperCase()), txt);
    t.addEventListener("click", () => show("discover"));
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
  const badge = $("nav-mods-count");
  badge.hidden = !installed.length;
  badge.textContent = String(installed.length);
  renderInstalled();
}

function renderInstalled() {
  const c = pickedClient();
  $("mods-client-note").textContent = c ? `${c.build} · ${c.path}` : "";
  const list = $("mods-list");
  list.replaceChildren();
  if (!c) { list.append(el("p", "hint", "Add your game client first.")); return; }
  if (!installed.length) { list.append(el("p", "hint", "No mods in this client yet. Install from Discover, or drop one above.")); return; }
  for (const m of installed) {
    const card = el("div", "card" + (m.enabled ? "" : " off"));
    const top = el("div", "top");
    top.append(el("span", "name", m.name), el("span", "build", m.version ? "v" + m.version : (m.source === "catalog" ? "Workshop" : "Local")));
    const meta = el("div", "meta");
    const what = [];
    if (m.addons.length) what.push("Addons: " + m.addons.join(", "));
    if (m.patches.length) what.push("Patch: " + m.patches.join(", "));
    meta.append(el("span", "", what.join(" · ")));
    meta.append(el("span", "", (m.source === "catalog" ? "From the Workshop" : "Added from your PC") + (m.credits ? " · " + m.credits : "")));
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
        await modAction("mod_install", { client: c.id, project: m.key }, `Updated ${m.name} to v${m.update}.`);
      });
      acts.append(up);
    }
    const rm = el("button", "btn small danger", "REMOVE");
    let armed = null;
    rm.addEventListener("click", async () => {
      if (!armed) {
        rm.textContent = "CLICK AGAIN TO REMOVE";
        armed = setTimeout(() => { armed = null; rm.textContent = "REMOVE"; }, 3000);
        return;
      }
      clearTimeout(armed);
      try {
        const r = await invoke("mod_uninstall", { client: c.id, key: m.key });
        say("mods-status", `Removed ${m.name}: ${r.removed_files} files.` + (r.kept.length ? ` Kept files Leyline did not put there: ${r.kept.join(", ")}` : ""), "ok");
      } catch (e) { say("mods-status", String(e), "bad"); }
      await loadInstalled();
      renderCatalog();
    });
    acts.append(rm);
    card.append(top, meta, acts);
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
      const m = await invoke("mod_install_local", { client: c.id, path });
      say("mods-status", `Installed ${m.name} into ${c.name}.` + (m.warnings.length ? " Note: " + m.warnings.join("; ") : ""), m.warnings.length ? "warn" : "ok");
    } catch (e) {
      say("mods-status", `${name}: ` + showProblems(e), "bad");
      break;
    }
  }
  await loadInstalled();
  renderCatalog();
}
$("mods-pick-file").addEventListener("click", async () => { const p = await invoke("pick_mod_file").catch(() => null); if (p) installLocal([p]); });
$("mods-pick-folder").addEventListener("click", async () => { const p = await invoke("pick_mod_folder").catch(() => null); if (p) installLocal([p]); });

// Files dropped on the window (Tauri gives their paths). Only My Mods takes them; anywhere else they lead there.
function setupDrop() {
  const wv = window.__TAURI__ && window.__TAURI__.webview && window.__TAURI__.webview.getCurrentWebview
    ? window.__TAURI__.webview.getCurrentWebview() : null;
  if (!wv || !wv.onDragDropEvent) return;
  wv.onDragDropEvent((ev) => {
    const t = ev.payload && ev.payload.type;
    if (t === "enter" || t === "over") { $("drop").classList.add("over"); if (currentPage !== "mods") show("mods"); }
    else if (t === "leave") $("drop").classList.remove("over");
    else if (t === "drop") {
      $("drop").classList.remove("over");
      if (currentPage !== "mods") show("mods");
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
    if (l.from_cache) say("rl-status", `Offline: showing the list as it was ${when}.`, "warn");
    else if (l.error) say("rl-status", "The community list is not reachable right now: " + l.error, "warn");
    else say("rl-status", `${n} community realm${n === 1 ? "" : "s"} on the Leyline network.`, "ok");
  } catch (e) {
    say("rl-status", String(e), "bad");
  }
  renderRealms();
  renderRealmRows();
  $("srv-name").textContent = realmLabel();
}

function renderRealms() {
  const box = $("rl-list");
  box.replaceChildren();
  const c = pickedClient();
  const now = state.settings.selected_realm;
  for (const r of realmsCache) {
    const card = el("article", "realm-card" + (r.address && r.address === now ? " on" : ""));
    const head = el("div", "top");
    const st = el("span", "state " + (r.state === "live" ? "is-online" : "is-offline"));
    st.append(el("span", "dot"), el("span", "", r.state === "live" ? "Online" : "Offline"));
    head.append(el("b", "name", r.name), st);
    const counts = [r.players != null ? `${r.players} players` : "", r.bots ? `${r.bots} bots` : ""].filter(Boolean).join(" · ");
    const facts = [r.official ? "Official" : "Beacon", r.kind, r.ruleset, r.version, counts].filter(Boolean).join(" · ");
    card.append(head, el("div", "facts", facts));
    if (r.tagline) card.append(el("p", "desc", r.tagline));
    if (r.rules && r.rules.length) {
      const ul = el("ul", "rules");
      ul.replaceChildren(...r.rules.slice(0, 4).map((x) => el("li", "", x)));
      card.append(ul);
    }
    card.append(el("div", "hint", r.address ? `Realmlist: ${r.address}` : "No desktop address yet: PLAY asks the relay"));
    const acts = el("div", "acts");
    const play = el("button", "btn small", "PLAY");
    const wrongBuild = c && c.build !== "3.3.5a" && (r.version || "").startsWith("3.3.5");
    if (!c || wrongBuild) { play.disabled = true; play.title = !c ? "Add a game client first" : "This realm runs 3.3.5a"; }
    play.addEventListener("click", () => playRealm(r, play));
    acts.append(play);
    if (r.join_url) acts.append(linkBtn("Make an account", r.join_url));
    if (r.discord) acts.append(linkBtn("Discord", r.discord));
    card.append(acts);
    box.append(card);
  }
  if (realmsCache.length <= 1) box.append(el("p", "hint", "No community realms listed right now. Host one: see Host."));
}

async function playRealm(r, btn) {
  const c = needClient("rl-status");
  if (!c) return;
  btn.disabled = true;
  say("rl-status", `Starting ${c.name} on ${r.name}…`);
  try {
    const msg = await invoke("play_realm", { client: c.id, slug: r.slug });
    say("rl-status", msg + (r.official ? "" : " First time here? Make your account with Make an account."), "ok");
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
let updateUrl = null;
async function checkUpdate(quiet) {
  if (!quiet) say("upd-status", "Checking…");
  try {
    const u = await invoke("check_update");
    updateUrl = u.newer ? u.url : null;
    $("tb-update").hidden = !u.newer;
    $("upd-open").hidden = !u.url;
    if (u.newer) say("upd-status", `Leyline ${u.latest} is out (you have ${u.current}).`, "ok");
    else if (u.latest) say("upd-status", `You have the newest Leyline (${u.current}).` + (u.from_cache ? " (offline: from the last check)" : ""), "ok");
    else say("upd-status", u.error ? "Could not check: " + u.error : "No launcher releases yet.", u.error ? "warn" : "");
    if (u.url) $("upd-open").onclick = () => openUrl(u.url);
  } catch (e) {
    if (!quiet) say("upd-status", String(e), "bad");
  }
}
$("upd-check").addEventListener("click", () => checkUpdate(false));
$("tb-update").addEventListener("click", () => { if (updateUrl) openUrl(updateUrl); else show("settings"); });

// ------------------------------------------------------------------ start
renderNews();
renderModTiles();
refresh().then(() => {
  setMode(mode);
  loadCatalog(true);
  loadRealms(true);
  checkUpdate(true);
  setupDrop();
  let page = "play";
  try { page = localStorage.getItem("leyline.page") || "play"; } catch (_) { /* fine */ }
  show($("page-" + page) ? page : "play");
}).catch((e) => {
  document.body.prepend(el("p", "status bad", "Leyline could not start: " + e));
});
