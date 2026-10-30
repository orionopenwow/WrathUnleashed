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
    "Finds your own 1.12.1, 2.4.3 and 3.3.5a clients, and lists other builds too",
    "Realms show their server and build; PLAY picks a client that fits",
    "Updates itself in the background: restart when you are ready, never mid-game",
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
const loaders = { discover: () => loadCatalog(), mods: () => loadInstalled(), realms: () => loadRealms(), host: () => loadHost() };
let currentPage = "play";
function show(page, noLoad) {
  currentPage = page;
  document.querySelectorAll(".nav[data-page]").forEach((b) => b.classList.toggle("on", b.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  if (loaders[page] && !noLoad) loaders[page]();
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
  add(officialName(), true);
  const saved = state.settings.selected_realm;
  const custom = !isOfficial() ? chosenRealm() : (saved && saved !== state.official_realm ? saved : "");
  if (custom) {
    const beacon = realmsCache.find((x) => x.address === custom);
    add(beacon ? beacon.name : custom, false);
  }
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
  $("srv-name").textContent = realmLabel();
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
  box.append(el("b", "", c.name), el("span", "", buildLabel(c.build) + " · Installed · your own game folder"));
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

function renderPlayBar() {
  if (!state) return;
  const c = currentClient();
  const bar = $("play-headline").parentElement;
  let head = "READY TO PLAY", detail = "", warn = false;
  if (mode === "browser" && officialGamedata === false) {
    head = "BROWSER PLAY · NEEDS YOUR GAME FOLDER"; warn = true;
    detail = "This realm streams no game files: the browser asks for your own 3.3.5a game folder (read on your PC, never uploaded)";
  } else if (mode === "browser") {
    head = "READY · PLAYS IN YOUR BROWSER";
    detail = officialName() + " · plays in your web browser, nothing to install";
  } else if (!c) {
    head = "SET UP YOUR GAME CLIENT"; warn = true;
    detail = "PLAY takes you to your game clients: point Leyline at your game folder";
  } else if (chosenRealmBuild() && c.build !== chosenRealmBuild()) {
    const need = chosenRealmBuild();
    head = `THIS SERVER NEEDS ${need.toUpperCase()}`; warn = true;
    const other = state.settings.clients.find((x) => x.build === need);
    detail = other ? `${realmLabel()} runs ${need}: pick ${other.name}` : `${realmLabel()} runs ${need}: add your own ${need} client under Game clients`;
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

// A card's numbers and its rating stars. Rating needs the Friends sign-in (the same website sign-in).
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
    say("cat-status", String(e) === "signed_out" ? "Sign in on the Friends page to rate mods (the same sign-in as the website)." : String(e), "bad");
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
    acts.append(el("span", "hint", "Get it from its page, then drop the zip on My Mods."));
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
  if (!link || link.action !== "install" || typeof link.id !== "string") return;
  const p = catalog.projects.find((x) => x.id === link.id);
  show("discover", true);   // the catalog was just loaded
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

$("cat-q").addEventListener("input", renderCatalog);
$("cat-fit").addEventListener("change", renderCatalog);

// The three tiles on Home: the picked client's installed mods (updates first), or Workshop picks when it has none.
function renderModTiles() {
  const box = $("mod-tiles");
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
    t.title = m ? "Open My Mods" : "Open Discover";
    t.addEventListener("click", () => show(m ? "mods" : "discover"));
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
  // Open My Mods on a client that has an update, if the picked one has none.
  const c = pickedClient();
  const u = modUpdates.find((x) => c && x.client === c.id) || modUpdates[0];
  if (u && (!c || u.client !== c.id)) {
    state.settings.selected_client = u.client;
    $("play-client").value = u.client;
    renderClientPickers();
    realmChanged();
    saveSelection();
  }
  show("mods");
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
  if (!installed.length) { list.append(el("p", "hint", "No mods in this client yet. Install from Discover, or drop one above.")); return; }
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
        if (m.source === "catalog") t += " Install it again any time from Discover.";
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
    networkTotals = l.network || null;
    if (l.from_cache) say("rl-status", `Offline: showing the list as it was ${when}.`, "warn");
    else if (l.error) say("rl-status", "The community list is not reachable right now: " + l.error, "warn");
    else say("rl-status", `${n} community realm${n === 1 ? "" : "s"} on the Leyline network.`, "ok");
    fillRealmFilters();
  } catch (e) {
    say("rl-status", String(e), "bad");
  }
  renderRealms();
  renderRealmRows();
  $("srv-name").textContent = realmLabel();
}

// The network (realms.rs order): featured community realms, the Leyline Sample Hangout (ours, temporary), the
// other live realms by the network's fair score, offline ones. The filters narrow the community realms.
let networkTotals = null;
let p2pHosting = false;   // direct connections are shown only when the p2p_hosting flag is on (Settings > Advanced)
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
function uptimeTag(r) {
  const u = r.uptime_7d != null ? r.uptime_7d : r.uptime_24h;
  if (u == null) return null;
  return el("span", "tag" + (u >= 95 ? " good" : u >= 75 ? "" : " warn"), `${u}% up · ${r.uptime_7d != null ? "7 d" : "24 h"}`);
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
    const card = el("article", "realm-card" + (r.address && r.address === now ? " on" : "") + (r.featured ? " featured" : "") + (r.official ? " official" : ""));
    const head = el("div", "top");
    const st = el("span", "state " + (r.state === "live" ? "is-online" : "is-offline"));
    st.append(el("span", "dot"), el("span", "", r.state === "live" ? "Online" : "Offline"));
    head.append(el("b", "name", r.name), st);
    const counts = [r.players != null ? `${r.players}${r.max_players ? " of " + r.max_players : ""} players` : "", r.bots ? `${r.bots} bots` : ""].filter(Boolean).join(" · ");
    const facts = [r.official ? "Run by Leyline" : "Community realm", r.kind, r.ruleset, counts].filter(Boolean).join(" · ");
    const tags = el("div", "tags");
    if (r.official && r.temporary) tags.append(el("span", "tag warn", "temporary"));
    if (r.featured) tags.append(el("span", "tag gold", "Featured"));
    if (r.verified) tags.append(el("span", "tag good", "Verified host"));
    if (r.is_new) tags.append(el("span", "tag", "New"));
    const up = uptimeTag(r);
    if (up) tags.append(up);
    for (const t of r.tags || []) if (!r.official) tags.append(el("span", "tag", TAG_LABELS[t] || t));
    if (r.region) tags.append(el("span", "tag", (REGION_LABELS[r.region] || r.region) + (r.region_estimated ? " (estimated)" : "")));
    if (r.language) tags.append(el("span", "tag", r.language));
    if (r.direct && p2pHosting) tags.append(el("span", "tag good", "Direct connect available"));
    tags.append(el("span", "tag", r.build ? buildLabel(r.build) : (r.version || "Build not listed")));
    tags.append(el("span", "tag", CORE_LABELS[r.core] || "Other server"));
    if (r.build && !fit) tags.append(el("span", "tag warn", `Needs your own ${r.build} client`));
    card.append(head, el("div", "facts", facts), tags);
    if (r.tagline) card.append(el("p", "desc", r.tagline));
    if (r.rules && r.rules.length) {
      const ul = el("ul", "rules");
      ul.replaceChildren(...r.rules.slice(0, 4).map((x) => el("li", "", x)));
      card.append(ul);
    }
    card.append(el("div", "hint", r.address ? `Realmlist: ${r.address}` : "No desktop address yet: PLAY asks the relay"));
    const acts = el("div", "acts");
    const play = el("button", "btn small", "PLAY");
    if (!state.settings.clients.length) { play.disabled = true; play.title = "Add a game client first"; }
    else if (!fit) { play.title = `This realm runs ${r.build}: PLAY says what is missing`; }
    else play.title = `Plays with ${fit.name}`;
    play.addEventListener("click", () => playRealm(r, play));
    acts.append(play);
    if (r.join_url) acts.append(linkBtn("Make an account", r.join_url));
    if (r.discord) acts.append(linkBtn("Discord", r.discord));
    if (r.report_url && !r.official) { const rep = linkBtn("Report", r.report_url); rep.title = "Report this realm to Leyline staff (on the website)"; acts.append(rep); }
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
invoke("p2p_flags").then((v) => { p2pHosting = !!(v && v.effective && v.effective.p2p_hosting); }).catch(() => {});
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
  show($("page-" + page) ? page : "play");
}).catch((e) => {
  document.body.prepend(el("p", "status bad", "Leyline could not start: " + e));
});
