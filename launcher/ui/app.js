// Leyline launcher UI. Plain JS over the Rust core's commands (src-tauri/src/app.rs).
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

let state = null;

function say(id, text, kind) {
  const s = $(id);
  s.textContent = text || "";
  s.className = "status" + (kind ? " " + kind : "");
}

// ------------------------------------------------------------------ navigation
const loaders = { mods: loadMods, realms: loadRealms };
function show(page) {
  document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("on", b.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === "page-" + page));
  if (loaders[page]) loaders[page]();
  try { localStorage.setItem("leyline.page", page); } catch (_) { /* storage may be off */ }
}
document.querySelectorAll(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.page)));
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => show(b.dataset.goto)));

// ------------------------------------------------------------------ state
async function refresh() {
  state = await invoke("get_state");
  $("ver").textContent = "v" + state.version;
  $("data-dir").textContent = state.data_dir;
  renderPlay();
  renderClients();
  renderSettings();
}

// ------------------------------------------------------------------ play
function renderPlay() {
  const s = state.settings;
  const sel = $("play-client");
  sel.replaceChildren();
  for (const c of s.clients) {
    const o = el("option", "", `${c.name}`);
    o.value = c.id;
    sel.append(o);
  }
  if (s.selected_client) sel.value = s.selected_client;
  const none = s.clients.length === 0;
  $("play-empty").hidden = !none;
  $("play-form").hidden = none;
  const official = !s.selected_realm || s.selected_realm === state.official_realm;
  $("play-realm").value = official ? "official" : "custom";
  $("play-custom").value = official ? "" : s.selected_realm;
  realmChanged();
}

function chosenRealm() {
  return $("play-realm").value === "official" ? state.official_realm : $("play-custom").value.trim();
}

function realmChanged() {
  const custom = $("play-realm").value === "custom";
  $("play-custom-wrap").hidden = !custom;
  const c = state.settings.clients.find((x) => x.id === $("play-client").value);
  let hint = "";
  if (c && c.build === "1.12.1" && !custom) {
    hint = "The official realm runs 3.3.5a. Pick a 3.3.5a client, or another realm for this 1.12.1 client.";
  } else if (c) {
    hint = "PLAY sets this client's realmlist.wtf (your original is kept as a backup) and starts it.";
  }
  $("play-hint").textContent = hint;
}
$("play-realm").addEventListener("change", realmChanged);
$("play-client").addEventListener("change", () => {
  realmChanged();
  invoke("select", { client: $("play-client").value, realm: chosenRealm() }).catch(() => {});
});

$("play-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const client = $("play-client").value;
  const realm = chosenRealm();
  if (!realm) return say("play-status", "Type a realm address.", "bad");
  $("play-go").disabled = true;
  say("play-status", "Starting…");
  try {
    say("play-status", await invoke("play", { client, realm }), "ok");
    state = await invoke("get_state");
  } catch (e) {
    say("play-status", String(e), "bad");
  } finally {
    $("play-go").disabled = false;
  }
});

$("play-browser").addEventListener("click", async () => {
  try {
    await invoke("open_browser_play");
    say("play-status", "Opened the browser client.", "ok");
  } catch (e) {
    say("play-status", String(e), "bad");
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
    const bCheck = el("button", "btn small", "Check");
    const bRename = el("button", "btn small", "Rename");
    const bRemove = el("button", "btn small danger", "Remove");
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
        bRemove.textContent = "Click again to remove";
        armed = setTimeout(() => { armed = null; bRemove.textContent = "Remove"; }, 3000);
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

// ------------------------------------------------------------------ read-only listings
async function loadListing(cmd, prefix) {
  say(prefix + "-status", "Loading…");
  try {
    const l = await invoke(cmd);
    $(prefix + "-count").textContent = String(l.count);
    const when = l.saved_at ? new Date(l.saved_at * 1000).toLocaleString() : "an earlier visit";
    if (l.from_cache) say(prefix + "-status", `Offline: showing the copy saved ${when}.`, "warn");
    else say(prefix + "-status", "Up to date.", "ok");
    const ul = $(prefix + "-names");
    ul.replaceChildren(...l.names.slice(0, 40).map((n) => el("li", "", n)));
  } catch (e) {
    $(prefix + "-count").textContent = "–";
    say(prefix + "-status", String(e), "bad");
  }
}
function loadMods() { loadListing("catalog_listing", "mods"); }
function loadRealms() { loadListing("realm_listing", "realms"); }

// ------------------------------------------------------------------ start
refresh().then(() => {
  let page = "play";
  try { page = localStorage.getItem("leyline.page") || "play"; } catch (_) { /* fine */ }
  show($("page-" + page) ? page : "play");
}).catch((e) => {
  document.body.prepend(el("p", "status bad", "Leyline could not start: " + e));
});
