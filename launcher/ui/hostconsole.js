// Leyline: the host console. The Host page once a realm is set up on this PC, after the website's "Your realm console"
// (stream/hub.py host_showcase): the realm's name and state, six service tiles, the GM controls, the health check, the
// realm tools and the cores it runs on. Before a realm is set up: the setup start (a ruleset, or Link my server) and the
// guide. Commands: src-tauri/src/host/console.rs (through p2p/cmds.rs) plus the Host page's own (app.js, host.js).
// Leyline makes no accounts and handles no passwords: friends make their own on the realm's join page.
// Loaded after app.js and host.js; app.js sends "leyline:kit" each time it reads the kit.
"use strict";
(() => {
  const call = window.__TAURI__ && window.__TAURI__.core
    ? window.__TAURI__.core.invoke
    : async () => { throw "This is a preview page: open it in the Leyline app."; };
  // never a raw error to the player (friendly.js): the error goes to the console, the player gets a plain line
  const oops = (e, fb) => (window.LeylineFriendly ? window.LeylineFriendly(e, fb) : (fb || "Something went wrong. Try again."));
  const byId = (id) => document.getElementById(id);
  const mk = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const btn = (label, cls, on) => { const b = mk("button", cls || "btn small", label); b.type = "button"; if (on) b.addEventListener("click", on); return b; };
  const page = byId("page-host");
  const main = byId("hc-pane-main");
  const guidePane = byId("hc-pane-guide");
  if (!page || !main || !guidePane) return;

  // ---------------------------------------------------------------- our own shapes (as on the website: no game emblem)
  const studs = Array.from({ length: 8 }, (_, k) =>
    `<circle cx="${(24 + 19.5 * Math.cos(k * Math.PI / 4)).toFixed(2)}" cy="${(24 + 19.5 * Math.sin(k * Math.PI / 4)).toFixed(2)}" r="1.3"/>`).join("");
  const CREST = `<svg class="hc-crest" viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" focusable="false">
    <circle cx="24" cy="24" r="22" class="r1"/><circle cx="24" cy="24" r="17" class="r2"/><g class="st">${studs}</g>
    <g transform="translate(13.6 9.6) scale(.65)"><polygon points="16,1.5 9,11 16,30.5" fill="#c9b2ff"/><polygon points="16,1.5 23,11 16,30.5" fill="#8b6cf0"/>
    <polygon points="9,11 16,30.5 5.5,13" fill="#5b3fc4"/><polygon points="23,11 16,30.5 26.5,13" fill="#4a2fa8"/>
    <polygon points="16,1.5 9,11 5.5,13" fill="#b9d0ff"/><polygon points="16,1.5 23,11 26.5,13" fill="#7aa3f5"/></g></svg>`;
  const RUNE = '<svg viewBox="0 0 64 14" width="64" height="14" focusable="false"><circle cx="3" cy="7" r="1.6" class="dt"/>'
    + '<path d="M14 7l3-3 3 3-3 3z" class="dm s"/><path d="M32 1l6 6-6 6-6-6z" class="dm"/><path d="M44 7l3-3 3 3-3 3z" class="dm s"/>'
    + '<circle cx="61" cy="7" r="1.6" class="dt"/></svg>';
  const rune = () => { const d = mk("div", "hc-rune"); d.setAttribute("aria-hidden", "true"); d.innerHTML = RUNE; return d; };
  const crest = () => { const s = mk("span", "hc-crest-w"); s.innerHTML = CREST; return s; };
  const CHEV = '<svg class="hc-chev" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // ---------------------------------------------------------------- the words (the website's console, HOST_* in hub.py)
  const SERVICES = [["database", "Database"], ["login", "Login server"], ["world", "World server"], ["agent", "Relay agent"]];
  const GM = [
    ["announce", "Announce", "to everyone online"],
    ["motd", "Message of the day", "shown at login"],
    ["kick", "Kick", "one player"],
    ["ban", "Ban or unban", "a player"],
    ["allow", "Allow-list", "only listed characters"],
    ["restart", "Restart", "with a five-minute warning"],
  ];
  const CHECKS = [["pc", "The servers on your PC"], ["tunnel", "The tunnel to the relay"], ["login", "A login through the relay"],
    ["invite", "Your invite link"], ["list", "Your place on the realm list"]];
  const TOOLS = [["invite", "Invite links"], ["friends", "Accounts for friends"], ["vis", "Public or private"],
    ["signup", "Who may sign up"], ["browser", "Browser players"], ["max", "Max players"], ["logs", "Server logs"], ["rules", "House rules"]];
  // tools that change a setting of the kit's own realm: not for a linked server (its own settings), browser only on AzerothCore
  // and a Den has no player limit to set (the kit sets 10 for it, docs/DEN.md)
  const toolShown = (k, c) => !(c.linked && (k === "browser" || k === "max" || k === "signup")) && !(k === "browser" && (c.core || "azerothcore") !== "azerothcore")
    && !(k === "max" && c.profile === DEN);
  // the cores the host pack runs (stream/hub.py HOST_CORES): one click only for what the kit hosts today
  const CORES = [["azerothcore", "AzerothCore", "One click"], ["cmangos", "CMaNGOS", "One click"], ["trinitycore", "TrinityCore", "Coming"],
    ["vmangos", "vMaNGOS", "Coming"], ["own", "Your own", "Relay agent"]];
  // the rulesets, in plain words (host/profiles.rs PROFILES; the kit's own presets)
  const RULESETS = {
    vanillaplus: ["Vanilla+", "The original world to 60, made to stay up.", "Always on"],
    den: ["My Den", "A private room to build in: you and the friends you invite. No bots.", "Private"],
    dalaran: ["Dalaran hangout", "Light: a one-time boost, no bots."],
    main: ["Classic levelling", "From level 1 at 3x, or a one-time boost."],
    brawl: ["Brawl", "Everyone starts at the top level."],
    progression: ["Progression", "1x from level 1, era by era."],
    "cmangos-1.12.1": ["True Vanilla", "A plain realm on CMaNGOS, for the original client."],
    "cmangos-2.4.3": ["Second era", "A plain realm on CMaNGOS."],
    "tcpp-4.3.4": ["Fourth era", "A plain realm on TrinityCore."],
  };
  const ORDER = ["vanillaplus", "den", "dalaran", "main", "progression", "brawl", "cmangos-1.12.1", "cmangos-2.4.3", "tcpp-4.3.4"];
  // Make my Den (docs/DEN.md): the kit's "den" profile, private and sign-up from the invite link only, never bots, at
  // most 10 players (the kit writes those; host/profiles.rs starts it with --private). No bots or max-players choice.
  const DEN = "den";
  const DEN_FACTS = [["Private", "only friends with your invite link"], ["Sign-up", "from your invite link only"], ["No bots", "just you and your friends"]];
  // the guide: short how-tos, each with its page on the website (lib.rs LINKS: hostdocs, alwayson)
  const GUIDE = [
    ["network", "How the Leyline network works", "Players reach your realm through the Leyline relay, by its realm id: nobody sees your address and you open no ports. Public realms are listed; private ones take an invite link. Leyline never ships game files.", "network"],
    ["start", "Start your realm", "Pick a ruleset and press Start. A window opens: leave it running. The first start imports the databases, 5 to 20 minutes.", "hostdocs"],
    ["stop", "Stop it", "Stop keeps characters, accounts and your invite link. Start again any time; it picks up where it was.", "hostdocs"],
    ["update", "Update", "When a new Host pack is out, update it under Host pack & settings, then press Start again. Your realm and its links are kept.", "hostdocs"],
    ["public", "Go public", "Realm tools, Public or private. A public realm is on the Leyline realm list within a minute; a private one only takes your invite link.", "hostdocs"],
    ["invite", "Invite friends", "Realm tools, Invite links: copy the link and send it. Friends open it once and make their own account there.", "hostdocs"],
    ["claim", "Claim it with your Hero Key", "A listed realm shows as Unclaimed until you claim it. Get a claim token on the website and paste it under Public or private.", "alwayson"],
    ["alwayson", "Always on", "Vanilla+ starts always on: Docker brings it back after a reboot. With Docker Desktop, turn on its start at sign-in and keep the PC awake.", "alwayson"],
    ["link", "Link a server you already run", "Any core, here or elsewhere: Link my server runs only the relay agent next to it and never changes your server.", "alwayson"],
    ["backups", "Backups", "Stop the realm, then copy the Host pack folder: state holds your realm's key and links. Characters live in Docker's wu-database volume.", "hostdocs"],
    ["trouble", "When something's wrong", "Run the health check: each line says what to fix. Server logs are under Realm tools.", "hostdocs"],
  ];

  // ---------------------------------------------------------------- tabs
  const tabs = [...page.querySelectorAll(".page-tab[data-hc]")];
  function tab(name) {
    for (const b of tabs) { const on = b.dataset.hc === name; b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; }
    for (const p of page.querySelectorAll(".hc-pane")) p.classList.toggle("on", p.id === "hc-pane-" + name);
  }
  tabs.forEach((b) => {
    b.addEventListener("click", () => tab(b.dataset.hc));
    b.addEventListener("keydown", (e) => {
      const i = tabs.indexOf(b);
      const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
      if (j === null) return;
      e.preventDefault();
      const t = tabs[(j + tabs.length) % tabs.length];
      tab(t.dataset.hc); t.focus();
    });
  });

  // ---------------------------------------------------------------- the confirm (kick, ban, restart, stop, new link)
  function ask(title, body, yes) {
    const d = byId("hc-confirm");
    return new Promise((resolve) => {
      if (!d || !d.showModal) { resolve(window.confirm(`${title}\n\n${body}`)); return; }
      byId("hc-confirm-title").textContent = title;
      byId("hc-confirm-body").textContent = body;
      byId("hc-confirm-yes").textContent = yes;
      const done = (v) => { if (d.open) d.close(); resolve(v); };
      byId("hc-confirm-yes").onclick = () => done(true);
      byId("hc-confirm-no").onclick = () => done(false);
      d.oncancel = (ev) => { ev.preventDefault(); done(false); };
      d.showModal();
      byId("hc-confirm-no").focus();
    });
  }

  // ---------------------------------------------------------------- the guide (its own tab, and beside the setup start)
  function guideList(compact) {
    const box = mk("div", "hc-guide" + (compact ? " compact" : ""));
    if (!compact) box.append(mk("p", "hc-lede hc-guide-lede", "Short answers. Each links to its full page on the website."));
    for (const [id, title, body, link] of GUIDE) {
      const d = mk("details", "hc-g");
      d.dataset.topic = id;
      const s = mk("summary", "", title);
      s.insertAdjacentHTML("beforeend", CHEV);
      const p = mk("p", "", body);
      const more = btn("More on the website", "hc-more", () => call("open_link", { name: link }).catch(() => {}));
      more.dataset.link = link;
      d.append(s, p, more);
      box.append(d);
    }
    return box;
  }
  guidePane.append(guideList(false));

  // ---------------------------------------------------------------- state
  let kit = null;
  let con = null;
  let stat = null;
  let statErr = null;
  let gmStat = null;
  let mode = null;            // "console" | "setup"
  let autoTab = true;
  let openTool = null;
  let timer = null;
  let askedFor = null;        // a ruleset asked for from elsewhere (the play bar's My Den): picked once offered
  const ui = {};

  const say = (text, kind) => { if (ui.status) { ui.status.textContent = text || ""; ui.status.className = "status hc-status" + (kind ? " " + kind : ""); } };
  const isOn = () => page.classList.contains("on");

  document.addEventListener("leyline:kit", (e) => {
    kit = e.detail || null;
    const want = kit && kit.realm ? "console" : "setup";
    if (want !== mode) { mode = want; build(); if (autoTab) { tab("main"); autoTab = false; } }
    if (mode === "console") { refresh(); applyWant(); } else loadSetup();
  });
  // the play bar's My Den with no Den on this PC: the Host page with Make my Den picked
  document.addEventListener("leyline:host-ruleset", (e) => {
    askedFor = (e.detail && e.detail.profile) || null;
    tab("main");
    applyWant();
  });
  function applyWant() {
    if (!askedFor || !mode) return;
    const id = askedFor;
    if (mode === "console") {
      askedFor = null;
      const name = (kit && kit.realm && kit.realm.name) || "a realm";
      if (id === DEN) say(`This Host pack runs ${name}. A Host pack hosts one realm, so your Den needs a Host pack of its own.`, "warn");
      return;
    }
    if (!offers) return;    // loadSetup calls again once the rulesets are in
    askedFor = null;
    const o = offers.find((x) => x.id === id);
    if (!o) { say("Your Host pack has no Den yet: update it under Host pack & settings.", "warn"); return; }
    if (o.note) { say(o.note, "warn"); return; }
    pick(id).then(() => {
      const b = ui.rules && ui.rules.querySelector(`.hc-rs[data-profile="${id}"]`);
      if (b) { b.scrollIntoView({ block: "nearest" }); b.focus(); }
    });
  }

  function build() {
    main.replaceChildren();
    Object.keys(ui).forEach((k) => delete ui[k]);
    openTool = null;
    byId("hc-tab-main").textContent = mode === "console" ? "Console" : "Start";
    if (mode === "console") buildConsole(); else buildSetup();
  }

  // ================================================================ the console (a realm is set up)
  function buildConsole() {
    const sw = mk("section", "hc-sw");
    sw.setAttribute("aria-label", "Your realm console");
    // the header: crest, the realm's name, its state, start / stop
    const top = mk("div", "hc-top");
    const id = mk("div", "hc-id");
    ui.kicker = mk("p", "hc-k", "Your realm console");
    ui.name = mk("p", "hc-t", (kit.realm && kit.realm.name) || "Your realm");
    id.append(ui.kicker, ui.name);
    ui.badge = mk("p", "hc-run wait");
    ui.badge.setAttribute("role", "status");
    ui.badge.append(mk("span", "", ""), mk("b", "", "Checking…"));
    ui.badge.firstChild.setAttribute("aria-hidden", "true");
    ui.acts = mk("div", "hc-top-acts");
    ui.start = btn("Start", "btn small primary", startRealm);
    ui.stop = btn("Stop", "btn small", stopRealm);
    ui.refresh = btn("", "btn small hc-icon", () => refresh());
    ui.refresh.setAttribute("aria-label", "Refresh");
    ui.refresh.title = "Refresh";
    ui.refresh.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    ui.acts.append(ui.start, ui.stop, ui.refresh);
    top.append(crest(), id, ui.badge, ui.acts);

    // the six tiles
    ui.svc = mk("ul", "hc-svc");
    ui.svc.setAttribute("aria-label", "Health");
    ui.tiles = {};
    for (const [k, label] of [...SERVICES, ["players", "Players"], ["uptime", "Uptime"]]) {
      const li = mk("li", "hc-tile off");
      li.dataset.svc = k;
      const dot = mk("i", "");
      dot.setAttribute("aria-hidden", "true");
      const v = mk("span", "", "–");
      li.append(dot, mk("b", "", label), v);
      ui.svc.append(li);
      ui.tiles[k] = { li, v };
    }

    // GM controls | health check + realm tools
    const cols = mk("div", "hc-cols");
    const gmBox = mk("div", "hc-box");
    gmBox.append(mk("p", "hc-bh", "GM controls"));
    ui.gmNote = mk("p", "hc-note");
    ui.gmNote.hidden = true;
    ui.gm = mk("ul", "hc-acts");
    for (const [a, label, sub] of GM) ui.gm.append(gmRow(a, label, sub));
    gmBox.append(ui.gmNote, ui.gm);

    const right = mk("div", "hc-box");
    const chHead = mk("div", "hc-bh-row");
    chHead.append(mk("p", "hc-bh", "Health check"));
    ui.run = btn("Run check", "btn small", runCheck);
    ui.run.id = "hc-run-check";
    chHead.append(ui.run);
    ui.chk = mk("ul", "hc-chk");
    ui.checks = {};
    for (const [k, label] of CHECKS) {
      const li = mk("li", "c-idle");
      li.dataset.check = k;
      const i = mk("i", "");
      i.setAttribute("aria-hidden", "true");
      const t = mk("span", "", label);
      const d = mk("small", "");
      d.hidden = true;
      li.append(i, t, d);
      ui.chk.append(li);
      ui.checks[k] = { li, d };
    }
    ui.chkSum = mk("p", "hc-sum");
    ui.chkSum.hidden = true;
    ui.tools = mk("ul", "hc-tools");
    for (const [k, label] of TOOLS) {
      const li = mk("li", "");
      const b = btn(label, "hc-tool", () => toggleTool(k));
      b.dataset.tool = k;
      b.setAttribute("aria-pressed", "false");
      li.append(b);
      ui.tools.append(li);
    }
    right.append(chHead, ui.chk, ui.chkSum, mk("p", "hc-bh hc-gap", "Realm tools"), ui.tools);
    cols.append(gmBox, right);

    ui.drawer = mk("div", "hc-drawer");
    ui.drawer.hidden = true;
    ui.status = mk("p", "status hc-status");
    ui.status.setAttribute("role", "status");
    sw.append(top, rune(), ui.svc, cols, ui.drawer, ui.status, rune(), mk("p", "hc-bh", "Runs on"), coreChips());
    main.append(sw);
  }

  function coreChips(onOwn) {
    const ul = mk("ul", "hc-cores");
    ui.cores = {};
    for (const [id, name, tag] of CORES) {
      const li = mk("li", "hc-core" + (tag === "Coming" ? " soon" : "") + (id === "own" ? " own" : ""));
      li.dataset.core = id;
      const inner = id === "own" && onOwn ? btn("", "hc-core-b", onOwn) : mk("span", "hc-core-b");
      inner.append(mk("b", "", name), mk("span", "", tag));
      li.append(inner);
      ul.append(li);
      ui.cores[id] = li;
    }
    return ul;
  }

  // ---------------------------------------------------------------- GM rows: one line each, its form opens below it
  function gmRow(a, label, sub) {
    const li = mk("li", "hc-act");
    li.dataset.gm = a;
    const h = btn("", "hc-act-h");
    h.setAttribute("aria-expanded", "false");
    const s = mk("span", "", sub);
    h.append(mk("b", "", label), s);
    h.insertAdjacentHTML("beforeend", CHEV);
    const f = mk("div", "hc-act-f");
    f.hidden = true;
    h.addEventListener("click", () => {
      const open = f.hidden;
      for (const o of ui.gm.querySelectorAll(".hc-act")) { o.querySelector(".hc-act-f").hidden = true; o.querySelector(".hc-act-h").setAttribute("aria-expanded", "false"); o.classList.remove("open"); }
      f.hidden = !open;
      h.setAttribute("aria-expanded", String(open));
      li.classList.toggle("open", open);
      if (open) { const i = f.querySelector("input"); if (i) i.focus(); }
    });
    const input = (ph, max, cls) => { const i = mk("input", cls || ""); i.type = "text"; i.placeholder = ph; i.maxLength = max; i.spellcheck = false; i.autocomplete = "off"; return i; };
    const name = () => input("Character name", 12, "hc-name");
    if (a === "announce" || a === "motd") {
      const t = input(a === "announce" ? "Everyone online sees this" : "Shown to everyone at login", 200);
      const go = btn(a === "announce" ? "Send" : "Set", "btn small primary", async () => {
        if (!t.value.trim()) { t.focus(); return; }
        if (await gm(a, t.value, go)) { if (a === "announce") t.value = ""; }
      });
      t.addEventListener("keydown", (e) => { if (e.key === "Enter") go.click(); });
      f.append(t, go);
    } else if (a === "kick") {
      const n = name();
      const go = btn("Kick", "btn small danger", async () => {
        const who = n.value.trim();
        if (!who) { n.focus(); return; }
        if (await ask(`Kick ${who}?`, "They're sent off the realm now. They can log in again.", "Kick")) gm("kick", who, go);
      });
      f.append(n, go);
    } else if (a === "ban") {
      const n = name();
      const hrs = mk("select", "hc-hours");
      hrs.setAttribute("aria-label", "How long");
      for (const [v, t] of [["24", "1 day"], ["72", "3 days"], ["168", "1 week"], ["720", "30 days"]]) { const o = mk("option", "", t); o.value = v; hrs.append(o); }
      const go = btn("Ban", "btn small danger", async () => {
        const who = n.value.trim();
        if (!who) { n.focus(); return; }
        const long = hrs.options[hrs.selectedIndex].textContent;
        if (await ask(`Ban ${who} for ${long}?`, "They can't log in until it ends. You can unban them any time.", "Ban")) gm("ban", `${who}\t${hrs.value}`, go);
      });
      const un = btn("Unban", "btn small", () => { const who = n.value.trim(); if (!who) { n.focus(); return; } gm("unban", who, un); });
      f.append(n, hrs, go, un);
    } else if (a === "allow") {
      const n = name();
      const add = btn("Add", "btn small", () => { const who = n.value.trim(); if (!who) { n.focus(); return; } gm("allow", `add\t${who}`, add).then((ok) => { if (ok) n.value = ""; }); });
      const del = btn("Remove", "btn small", () => { const who = n.value.trim(); if (!who) { n.focus(); return; } gm("allow", `del\t${who}`, del); });
      const tog = btn("Turn on", "btn small", async () => {
        const on = !(gmStat && gmStat.allow === "on");
        if (on && !(await ask("Only listed characters?", "From now on, only characters on your list (and GMs) can log in. Others are told and sent off at login.", "Turn on"))) return;
        if (await gm("allow", on ? "on" : "off", tog)) gmStatus();
      });
      ui.allowToggle = tog;
      f.append(n, add, del, mk("span", "hc-sep"), tog);
    } else if (a === "restart") {
      const go = btn("Restart in 5 minutes", "btn small danger", async () => {
        if (await ask("Restart the realm?", "Everyone online is told now, and the realm restarts in five minutes. It's back a minute or two later.", "Restart in 5 minutes")) {
          if (await gm("restart", "", go)) gmStatus();
        }
      });
      const cancel = btn("Cancel restart", "btn small", async () => { if (await gm("cancel", "", cancel)) gmStatus(); });
      cancel.hidden = true;
      ui.restartGo = go;
      ui.restartCancel = cancel;
      f.append(mk("span", "hc-act-t", "Everyone online gets five minutes' warning."), go, cancel);
    }
    li.append(h, f);
    return li;
  }

  async function gm(action, data, b) {
    if (con && !con.gm) { say(con.gm_note || "Start your realm to use these.", "warn"); return false; }
    if (b) b.disabled = true;
    say("Sending to your realm…");
    try { say(await call("host_gm", { action, data }), "ok"); return true; }
    catch (e) { say(oops(e), "bad"); return false; }
    finally { if (b) b.disabled = false; }
  }

  // the GM controls' own state (restart coming, allow list, message of the day) from the realm itself
  async function gmStatus() {
    if (!con || !con.gm) return;
    let t;
    try { t = await call("host_gm", { action: "status", data: "" }); } catch (_) { return; }
    gmStat = {};
    for (const line of String(t).split("\n")) { const i = line.indexOf("="); if (i > 0) gmStat[line.slice(0, i)] = line.slice(i + 1); }
    const sub = (a, text) => { const r = ui.gm && ui.gm.querySelector(`[data-gm="${a}"] .hc-act-h span`); if (r) r.textContent = text; };
    if (gmStat.motd && gmStat.motd !== "-") sub("motd", `“${gmStat.motd.slice(0, 40)}”`);
    sub("allow", gmStat.allow === "on" ? `on · ${gmStat.allowed || 0} listed` : "only listed characters");
    if (ui.allowToggle) ui.allowToggle.textContent = gmStat.allow === "on" ? "Turn off" : "Turn on";
    const left = +gmStat.restart || 0;
    sub("restart", left > 0 ? `coming in ${Math.ceil(left / 60)} min` : "with a five-minute warning");
    if (ui.restartCancel) { ui.restartCancel.hidden = !(left > 0); ui.restartGo.hidden = left > 0; }
    if (gmStat.players && ui.tiles && !(stat && stat.players != null)) setTile("players", "ok", `${gmStat.players} online`);
  }

  // ---------------------------------------------------------------- data
  function setTile(k, state, text) {
    const t = ui.tiles && ui.tiles[k];
    if (!t) return;
    t.li.className = "hc-tile " + state;
    t.v.textContent = text;
  }
  function setBadge(cls, text) {
    if (!ui.badge) return;
    ui.badge.className = "hc-run " + cls;
    ui.badge.lastChild.textContent = text;
  }

  let busy = false;
  async function refresh(quiet) {
    if (mode !== "console" || busy) return;
    busy = true;
    const rid = kit && kit.realm && kit.realm.realm_id;
    try {
      const [c, s] = await Promise.all([
        call("host_console").catch((e) => { if (!quiet) say(oops(e), "bad"); return null; }),
        rid ? call("host_status", { realmId: rid }).then((x) => { statErr = null; return x; }).catch((e) => { statErr = String(e); return null; }) : null,
      ]);
      if (mode !== "console") return;
      con = c; stat = s;
      paint();
      if (con && con.gm && !gmStat) gmStatus();
    } finally { busy = false; }
  }

  function paint() {
    const c = con || { services: [], docker: false };
    if (c.name) ui.name.textContent = c.name;
    ui.kicker.textContent = c.linked ? "Your server, linked" : c.profile === DEN ? "Your Den" : "Your realm console";
    // the badge
    if (stat && stat.online) {
      setBadge("ok", stat.listed ? "Online · listed" : (stat.visibility === "private" || c.visibility === "private") ? "Online · private" : "Online");
    } else if (stat) setBadge("bad", "Offline");
    else if (statErr) setBadge("warn", "Not seen yet");
    else setBadge("wait", "Checking…");
    // the tiles
    for (const [k] of SERVICES) {
      const s = (c.services || []).find((x) => x.role === k);
      if (!s) { setTile(k, "off", "–"); continue; }
      let text = s.text;
      if (k === "agent" && s.state === "ok" && stat && stat.listed) text = "listed";
      setTile(k, s.state, text);
    }
    const players = stat && stat.players != null ? stat.players : null;
    setTile("players", stat && stat.online ? "ok" : "off", players != null ? `${players} online` : "–");
    setTile("uptime", c.uptime ? "ok" : "off", c.uptime || "–");
    // start or stop
    const running = (c.services || []).some((s) => s.state === "ok" || s.state === "starting");
    ui.start.hidden = running || c.linked;
    ui.stop.hidden = !running || c.linked;
    // GM controls
    ui.gmNote.hidden = !c.gm_note;
    ui.gmNote.textContent = c.gm_note || "";
    ui.gm.classList.toggle("off", !c.gm);
    for (const h of ui.gm.querySelectorAll(".hc-act-h")) h.disabled = !c.gm;
    if (!c.gm) for (const f of ui.gm.querySelectorAll(".hc-act-f")) f.hidden = true;
    // the cores: the one this realm runs
    for (const [id, li] of Object.entries(ui.cores || {})) {
      const cur = id === (c.core || "azerothcore");
      li.classList.toggle("cur", cur);
      if (cur) li.setAttribute("aria-current", "true"); else li.removeAttribute("aria-current");
    }
    for (const b of ui.tools.querySelectorAll(".hc-tool")) b.parentElement.hidden = !toolShown(b.dataset.tool, c);
    if (openTool && !toolShown(openTool, c)) toggleTool(openTool);
    if (!c.docker && con) say("Docker is not answering: start Docker Desktop, then refresh.", "warn");
    if (openTool) fillTool(openTool, true);
  }

  async function startRealm() {
    say("Starting your realm…");
    try { say(await call("host_start", {}), "ok"); } catch (e) { say(oops(e), "bad"); }
    setTimeout(() => refresh(true), 20000);
  }
  async function stopRealm() {
    if (!(await ask("Stop the realm?", "Everyone online is saved and sent off. Characters, accounts and your invite link are kept.", "Stop"))) return;
    ui.stop.disabled = true;
    say("Stopping…");
    try { say(await call("host_stop"), "ok"); } catch (e) { say(oops(e), "bad"); }
    ui.stop.disabled = false;
    gmStat = null;
    refresh(true);
  }

  // ---------------------------------------------------------------- the health check
  async function runCheck() {
    ui.run.disabled = true;
    ui.run.textContent = "Checking…";
    ui.chkSum.hidden = true;
    for (const { li, d } of Object.values(ui.checks)) { li.className = "c-run"; d.hidden = true; }
    let r = null;
    try { r = await call("host_check"); } catch (e) { say(oops(e), "bad"); }
    ui.run.disabled = false;
    ui.run.textContent = "Run check";
    if (!r) { for (const { li } of Object.values(ui.checks)) li.className = "c-idle"; return; }
    for (const row of r.rows || []) {
      const c = ui.checks[row.id];
      if (!c) continue;
      c.li.className = "c-" + row.state;
      const bad = (row.lines || []).find((l) => l.kind === "bad") || (row.lines || []).find((l) => l.kind === "note");
      c.d.hidden = !bad;
      c.d.textContent = bad ? (bad.fix ? `${bad.text} ${bad.fix}` : bad.text) : "";
      c.li.title = (row.lines || []).map((l) => l.text).join("\n");
    }
    ui.chkSum.hidden = false;
    ui.chkSum.className = "hc-sum " + (r.ok ? "ok" : "bad");
    ui.chkSum.textContent = r.ok ? "Players can reach your realm." : (r.summary || "Something needs fixing: see above.");
  }

  // ---------------------------------------------------------------- realm tools: one drawer under the panels
  function toggleTool(k) {
    openTool = openTool === k ? null : k;
    for (const b of ui.tools.querySelectorAll(".hc-tool")) b.setAttribute("aria-pressed", String(b.dataset.tool === openTool));
    ui.drawer.hidden = !openTool;
    if (openTool) fillTool(openTool);
  }

  function seg(options, current, on) {
    const g = mk("div", "hc-seg");
    g.setAttribute("role", "group");
    for (const [v, label] of options) {
      const b = btn(label, "hc-seg-b", () => on(v, b));
      b.dataset.value = v;
      b.setAttribute("aria-pressed", String(v === current));
      g.append(b);
    }
    return g;
  }
  async function tool(name, arg, b) {
    if (b) b.disabled = true;
    say("Saving…");
    try { say(await call("host_tool", { name, arg: arg || null }), "ok"); await refresh(true); return true; }
    catch (e) { say(oops(e), "bad"); return false; }
    finally { if (b) b.disabled = false; }
  }
  async function copyInvite() {
    let link = null;
    try { link = await call("host_invite"); } catch (_) { /* no kit */ }
    if (!link) { say("No invite link yet: it's made on the first start.", "warn"); return; }
    try { await navigator.clipboard.writeText(link); say("Invite link copied. Friends open it once, then play.", "ok"); }
    catch (_) { say(link, "ok"); }
  }

  async function fillTool(k, keep) {
    const d = ui.drawer;
    // a refresh repaints only the choices that show the realm's state, and never over something being typed
    const typing = [...d.querySelectorAll("input, textarea")].some((i) => i.value || document.activeElement === i);
    if (keep && d.dataset.tool === k && ((k !== "vis" && k !== "signup" && k !== "browser") || typing)) return;
    d.dataset.tool = k;
    d.replaceChildren();
    const head = mk("div", "hc-drawer-h");
    head.append(mk("b", "", TOOLS.find((t) => t[0] === k)[1]));
    const close = btn("", "hc-x", () => toggleTool(k));
    close.setAttribute("aria-label", "Close");
    close.innerHTML = '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
    head.append(close);
    d.append(head);
    const c = con || {};
    if (k === "invite") {
      let link = null;
      try { link = await call("host_invite"); } catch (_) { /* no kit */ }
      const code = mk("code", "hc-link", link || "Made on the first start.");
      const row = mk("div", "hc-row");
      row.append(btn("Copy", "btn small primary", copyInvite), btn("New link", "btn small", async (ev) => {
        const b = ev.currentTarget;
        if (!(await ask("Make a new invite link?", "The old link stops letting anyone new in. Friends who joined keep playing.", "Make a new link"))) return;
        b.disabled = true;
        try { code.textContent = await call("host_new_invite"); say("New invite link made.", "ok"); } catch (e) { say(oops(e), "bad"); }
        b.disabled = false;
      }));
      d.append(code, row, mk("p", "hc-fine", c.visibility === "private" ? "Private: the part after # is the key. Send it only to friends." : "Friends open it once, make their own account, then play."));
    } else if (k === "friends") {
      d.append(mk("p", "", "Friends make their own account on your join page, with your invite link. Leyline never makes accounts or sees passwords."));
      const row = mk("div", "hc-row");
      row.append(btn("Copy invite link", "btn small primary", copyInvite), btn("Who may sign up", "btn small", () => toggleTool("signup")));
      d.append(row);
    } else if (k === "vis") {
      d.append(seg([["public", "Public · on the realm list"], ["private", "Private · invite link only"]], c.visibility, (v, b) => { if (v !== c.visibility) tool(v, null, b); }));
      if (c.visibility === "public") {
        const tok = mk("input", "hc-token");
        tok.type = "text"; tok.placeholder = "Claim token from the website"; tok.maxLength = 64; tok.spellcheck = false; tok.autocomplete = "off";
        const row = mk("div", "hc-row");
        row.append(tok, btn("Claim with Hero Key", "btn small", (ev) => { if (!tok.value.trim()) { tok.focus(); return; } tool("claim", tok.value.trim(), ev.currentTarget); }));
        d.append(mk("p", "hc-fine", c.claim_sent ? "Claim sent: the realm list shows who it belongs to once the website sees it." : "Listed as Unclaimed until you claim it for your Hero Key account."), row);
      }
    } else if (k === "signup") {
      const now = c.signup || "invite";
      d.append(seg([["invite", "Invite link only"], ["open", "Anyone"], ["off", "Nobody new"]], now, (v, b) => { if (v !== now) tool("signup-" + v, null, b); }),
        mk("p", "hc-fine", "Who may make an account on your join page."));
    } else if (k === "browser") {
      const now = c.browser ? "on" : "off";
      d.append(seg([["on", "On · browsers can join"], ["off", "Off · desktop clients only"]], now, (v, b) => { if (v !== now) tool("browser-" + v, null, b); }),
        mk("p", "hc-fine", "The browser client has no anti-cheat module, so it can join only while the core's client anti-cheat (Warden) is off. The server's own checks stay on. Applies at the next start."));
    } else if (k === "max") {
      const n = mk("input", "hc-token");
      n.type = "number"; n.min = "0"; n.max = "10000"; n.placeholder = "0 = the ruleset's own";
      if (c.max_players) n.value = String(c.max_players);
      const row = mk("div", "hc-row");
      row.append(n, btn("Save", "btn small primary", (ev) => {
        const v = n.value.trim() || "0";
        if (!/^\d{1,5}$/.test(v) || Number(v) > 10000) { say("Max players: 0 to 10000.", "warn"); n.focus(); return; }
        tool("max", v, ev.currentTarget);
      }));
      d.append(row, mk("p", "hc-fine", "The most players at once: the server turns away the next one, and the realm list shows it. Applies at the next start."));
    } else if (k === "logs") {
      const pre = mk("pre", "hc-logs", "Reading the logs…");
      const row = mk("div", "hc-row");
      const load = async () => { try { pre.textContent = (await call("host_logs", { lines: 200 })) || "(no log lines yet)"; pre.scrollTop = pre.scrollHeight; } catch (e) { pre.textContent = oops(e); } };
      row.append(btn("Refresh", "btn small", load));
      d.append(pre, row);
      load();
    } else if (k === "rules") {
      const ta = mk("textarea", "hc-rules");
      ta.rows = 5; ta.spellcheck = true;
      ta.placeholder = "One rule per line, up to 10";
      const n = mk("span", "hc-fine");
      const count = () => { const l = ta.value.split("\n").filter((x) => x.trim()); n.textContent = `${l.length}/10`; n.classList.toggle("bad", l.length > 10 || l.some((x) => x.trim().length > 120)); };
      ta.addEventListener("input", count);
      try { ta.value = (await call("host_rules")).join("\n"); } catch (_) { /* none yet */ }
      count();
      const row = mk("div", "hc-row");
      row.append(btn("Save", "btn small primary", async (ev) => {
        const b = ev.currentTarget; b.disabled = true;
        try { say(await call("host_rules_set", { lines: ta.value.split("\n") }), "ok"); } catch (e) { say(oops(e), "bad"); }
        b.disabled = false;
      }), n);
      d.append(ta, row);
    }
  }

  // ================================================================ the setup start (no realm on this PC yet)
  let picked = null;
  let offers = null;
  function buildSetup() {
    const wrap = mk("div", "hc-setup");
    const sw = mk("section", "hc-sw hc-start");
    sw.setAttribute("aria-label", "Host a realm");
    const top = mk("div", "hc-top");
    const id = mk("div", "hc-id");
    id.append(mk("p", "hc-k", "The host pack"), mk("p", "hc-t", "Host a realm"));
    ui.prereq = mk("div", "hc-pre");
    top.append(crest(), id, ui.prereq);
    // TODO(owner): the setup start's line, in your own words.
    const lede = mk("p", "hc-lede", "Run a realm on this PC for friends or everyone. Players reach it through the Leyline relay: no ports to open, your address stays hidden.");
    // what a host needs and how long it takes, up front (the website's /wrath/host says the same). TODO(owner): the wording.
    const needs = mk("p", "hc-needs");
    needs.append(mk("b", "", "You need: "), document.createTextNode("Docker, your own game folder "),
      mk("span", "hc-ver", "3.3.5a"), document.createTextNode(", about 10 GB free. The first start takes 5 to 20 minutes, and your PC must stay on for others to play."));
    ui.rules = mk("div", "hc-rulesets");
    ui.rules.setAttribute("role", "radiogroup");
    ui.rules.setAttribute("aria-label", "Ruleset");
    const go = mk("div", "hc-go");
    ui.go = btn("Start", "btn primary", startPicked);
    ui.go.id = "hc-start";
    ui.go.disabled = true;
    ui.goHint = mk("span", "hc-fine", "Pick a ruleset.");
    go.append(ui.go, ui.goHint);
    // My Den: what the kit sets for it, in place of choices (no bots, no player limit)
    ui.den = mk("ul", "hc-den");
    ui.den.setAttribute("aria-label", "My Den");
    for (const [b, t] of DEN_FACTS) { const li = mk("li", ""); li.append(mk("b", "", b), mk("span", "", t)); ui.den.append(li); }
    ui.den.hidden = true;
    ui.status = mk("p", "status hc-status");
    ui.status.setAttribute("role", "status");
    const link = mk("div", "hc-linkcard");
    const lt = mk("div", "");
    lt.append(mk("b", "", "Already run a server?"), mk("span", "", "List it with the relay agent. Your server is not changed."));
    ui.linkBtn = btn("Link my server", "btn small", linkServer);
    ui.linkBtn.id = "hc-link";
    link.append(lt, ui.linkBtn);
    // before anything else, while the Host pack or Docker is missing (owner 2026-10-30: "make getting the host pack more obvious")
    ui.ready = mk("div", "hc-ready");
    ui.ready.hidden = true;
    sw.append(top, rune(), lede, needs, ui.ready, mk("p", "hc-bh", "Pick a ruleset"), ui.rules, ui.den, go, ui.status, link, rune(), mk("p", "hc-bh", "Runs on"), coreChips(linkServer));
    const side = mk("aside", "hc-box hc-side");
    side.append(mk("p", "hc-bh", "Guide"), guideList(true));
    wrap.append(sw, side);
    main.append(wrap);
    paintRulesets();
  }

  function paintRulesets() {
    if (!ui.rules) return;
    ui.rules.replaceChildren();
    const list = offers || ORDER.slice(0, 6).map((id) => ({ id, clients: [], note: null, core: "azerothcore" }));
    const ids = ORDER.filter((id) => list.some((o) => o.id === id));
    for (const id of ids) {
      const o = list.find((x) => x.id === id);
      const [title, line, chip] = RULESETS[id] || [o.label || id, ""];
      const b = btn("", "hc-rs" + (picked === id ? " on" : "") + (o.note ? " off" : ""), () => pick(id));
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(picked === id));
      b.dataset.profile = id;
      b.disabled = !!o.note;
      const h = mk("span", "hc-rs-h");
      h.append(mk("b", "", title));
      if (chip) h.append(mk("em", "", chip));
      b.append(h, mk("span", "hc-rs-l", o.note || line));
      ui.rules.append(b);
    }
    paintGo();
  }
  function paintGo() {
    if (!ui.go) return;
    const ready = kit && kit.is_kit;
    const name = picked ? (RULESETS[picked] || [picked])[0] : null;
    ui.go.disabled = !ready || !picked;
    ui.go.textContent = name ? `Start ${name}` : "Start";
    ui.goHint.textContent = !ready ? "Get the Host pack first (step 1 above)." : !picked ? "Pick a ruleset."
      : picked === "vanillaplus" ? "Always on: it comes back after a reboot."
      : picked === DEN ? "Then invite friends with your invite link. The first start takes 5 to 20 minutes." : "The first start takes 5 to 20 minutes.";
    if (ui.den) ui.den.hidden = picked !== DEN;
  }
  async function pick(id) {
    const o = (offers || []).find((x) => x.id === id);
    picked = id;
    paintRulesets();
    try { await call("host_choose", { profile: id, clientId: o && o.clients[0] ? o.clients[0].id : null }); say(""); }
    catch (e) { say(oops(e), "bad"); }
  }
  async function startPicked() {
    ui.go.disabled = true;
    say("Starting your realm…");
    try { say(await call("host_start", {}), "ok"); } catch (e) { say(oops(e), "bad"); }
    paintGo();
    setTimeout(() => { if (typeof loadHost === "function") loadHost(); }, 20000);   // app.js: read the kit again
  }
  async function linkServer() {
    if (!(kit && kit.is_kit)) { say("Get the Host pack first (Host pack & settings).", "warn"); return; }
    say("Opening Link my server…");
    try { say(await call("host_link_start"), "ok"); } catch (e) { say(oops(e), "bad"); }
  }

  // the two things a host needs first, as two big numbered steps; gone once both are ready
  function paintReady(p, d, haveKit) {
    const box = ui.ready;
    if (!box) return;
    const dockOk = !d || d.state === "ready";
    box.hidden = haveKit && dockOk;
    if (box.hidden) return;
    box.replaceChildren(mk("p", "hc-ready-h", "Before you start"));
    const step = (n, done, title, line, action) => {
      const r = mk("div", "hc-step" + (done ? " done" : ""));
      const num = mk("span", "hc-step-n", done ? "✓" : String(n));
      num.setAttribute("aria-hidden", "true");
      const t = mk("div", "hc-step-t");
      t.append(mk("b", "", title), mk("span", "", line));
      r.append(num, t);
      if (action) r.append(action);
      box.append(r);
    };
    const av = p && p.available, inst = p && p.installed;
    let kitBtn = null;
    if (!haveKit) {
      const label = inst ? "Use the Host pack" : "Get the Host pack";
      kitBtn = btn(label, "btn primary hc-step-go", () => getPack(kitBtn, inst && p.kit_dir));
      kitBtn.id = "hc-get-pack";
      if (!inst && !av) kitBtn.disabled = true;
    }
    const kitLine = haveKit ? "Installed and ready." : inst ? "Downloaded: one click to use it."
      : av ? `One download${av.size ? `, ${Math.ceil(av.size / 1024)} KB` : ""}: the realm, its console and the relay agent. No game files.`
      : "Not listed right now: try again in a minute.";
    step(1, haveKit, "Get the Host pack", kitLine, kitBtn);
    let dockBtn = null;
    if (!dockOk) dockBtn = btn("Get Docker", "btn hc-step-go", () => call("open_link", { name: (d.get_url || "").includes("engine") ? "dockerengine" : "docker" }).catch(() => {}));
    step(2, dockOk, "Get Docker", dockOk ? "Docker is running." : "Free. It runs the realm's servers. Start it once it's installed.", dockBtn);
  }
  async function getPack(b, dir) {
    b.disabled = true;
    b.textContent = dir ? "Setting up…" : "Downloading…";
    try {
      if (!dir) { const r = await call("hostpack_install"); dir = r[1]; }
      await call("set_host_kit", { path: dir });
      say("The Host pack is ready.", "ok");
      if (typeof loadHost === "function") loadHost();   // app.js: re-read the kit
    } catch (e) { say(oops(e), "bad"); b.disabled = false; b.textContent = "Try again"; }
  }

  async function loadSetup() {
    paintGo();
    const pre = ui.prereq;
    const [p, d, prof] = await Promise.all([
      call("hostpack_info").catch(() => null), call("docker_info").catch(() => null), call("host_profiles").catch(() => null)]);
    if (mode !== "setup") return;
    if (Array.isArray(prof) && Array.isArray(prof[0])) {
      offers = prof[0].filter((o) => o && Array.isArray(o.clients));
      if (prof[1] && prof[1].profile && !picked) picked = prof[1].profile;
    }
    paintRulesets();
    applyWant();
    if (!pre) return;
    pre.replaceChildren();
    const chip = (ok, text, onFix) => {
      const c = mk(onFix ? "button" : "span", "hc-pill " + (ok ? "ok" : "warn"));
      if (onFix) { c.type = "button"; c.addEventListener("click", onFix); }
      const dot = mk("span", "");
      dot.setAttribute("aria-hidden", "true");
      c.append(dot, document.createTextNode(text));
      return c;
    };
    const haveKit = kit && kit.is_kit;
    paintReady(p, d, haveKit);
    if (ui.ready && !ui.ready.hidden) return;   // the steps say it already: no pills in the corner
    pre.append(chip(haveKit, haveKit ? "Host pack ready" : (p && p.installed ? "Host pack: use it" : "Get the Host pack"), haveKit ? null : () => tab("kit")));
    if (d) pre.append(chip(d.state === "ready", d.state === "ready" ? "Docker ready" : "Get Docker", d.state === "ready" ? null : () => call("open_link", { name: (d.get_url || "").includes("engine") ? "dockerengine" : "docker" }).catch(() => {})));
  }
})();
