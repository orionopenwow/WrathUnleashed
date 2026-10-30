// Leyline: the Host pack, Docker, realm controls (stop, logs, invite link) on the Host page, and the P2P /
// torrent switches under Settings > Advanced. Commands: src-tauri/src/p2p/cmds.rs. Loaded after app.js.
"use strict";
(() => {
  const call = window.__TAURI__ && window.__TAURI__.core
    ? window.__TAURI__.core.invoke
    : async () => { throw "This is a preview page: open it in the Leyline app."; };
  const byId = (id) => document.getElementById(id);
  const mk = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const note = (node, text, kind) => { node.textContent = text || ""; node.className = "status" + (kind ? " " + kind : ""); };
  const btn = (label, cls, on) => { const b = mk("button", cls || "btn", label); b.type = "button"; b.addEventListener("click", on); return b; };
  const linkBtn = (label, name) => btn(label, "btn small", () => call("open_link", { name }).catch(() => {}));

  // ---------------------------------------------------------------- Host page: the pack and Docker
  const page = byId("page-host");
  const panel = page && page.querySelector(".panel");
  if (!panel) return;
  const packCard = mk("section", "card stone");
  packCard.id = "hp-card";
  const head = mk("div", "card-head");
  head.append(mk("span", "", "HOST PACK"));
  const packLine = mk("div", "hint", "Checking…");
  const packActs = mk("div", "row");
  const packStatus = mk("p", "status");
  const dockLine = mk("div", "hint");
  const dockActs = mk("div", "row");
  packCard.append(head, mk("p", "lede",
    "Everything a host needs, in one download: the scripts, the realm tools and the relay agent. Our code only, no game files. Only hosts need it, and Docker."),
    packLine, packActs, packStatus, dockLine, dockActs);
  const steps = panel.querySelector("ol.steps");
  panel.insertBefore(packCard, steps || panel.firstChild);

  let pack = null;
  async function useKit(dir) {
    try { await call("set_host_kit", { path: dir }); } catch (e) { note(packStatus, String(e), "bad"); return; }
    if (typeof loadHost === "function") loadHost();   // app.js: re-read the kit
  }
  async function loadPack() {
    try { pack = await call("hostpack_info"); } catch (e) { packLine.textContent = String(e); return; }
    packActs.replaceChildren();
    const inst = pack.installed, av = pack.available;
    if (!inst) {
      packLine.textContent = av ? `Not installed. Version ${av.version}${av.size ? `, ${Math.ceil(av.size / 1024)} KB` : ""}.`
        : `Not installed. ${pack.error || "The Host pack is not listed yet."}`;
      if (av) packActs.append(btn("GET THE HOST PACK", "btn", install));
    } else {
      packLine.textContent = `Installed: version ${inst.version}` + (pack.update && av ? `. Version ${av.version} is out.` : ".") + ` Folder: ${pack.kit_dir}`;
      if (pack.update) packActs.append(btn(`UPDATE TO ${av.version}`, "btn", install));
      packActs.append(btn("USE THE HOST PACK", "btn", () => useKit(pack.kit_dir)));
    }
  }
  async function install() {
    note(packStatus, "Downloading and checking the Host pack…");
    packActs.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const [inst, dir] = await call("hostpack_install");
      note(packStatus, `Host pack ${inst.version} installed and checked. Your realm's own files were kept.`, "ok");
      await useKit(dir);
    } catch (e) { note(packStatus, String(e), "bad"); }
    loadPack();
  }
  async function loadDocker() {
    dockLine.textContent = "Checking Docker…";
    dockActs.replaceChildren();
    let d;
    try { d = await call("docker_info"); } catch (e) { dockLine.textContent = String(e); return; }
    dockLine.className = "hint " + (d.state === "ready" ? "ok" : "warn");
    dockLine.textContent = (d.state === "ready" ? `Docker ${d.version || ""} is ready.` : d.help);
    if (d.state !== "ready") dockActs.append(linkBtn("GET DOCKER", d.get_url.includes("engine") ? "dockerengine" : "docker"));
    dockActs.append(btn("CHECK AGAIN", "btn small", loadDocker));
  }

  // ---------------------------------------------------------------- Host page: realm controls
  const hostCard = byId("host-card");
  const ctl = mk("div", "row");
  const inviteLine = mk("div", "hint");
  const ctlStatus = mk("p", "status");
  const logs = mk("pre", "logs");
  logs.hidden = true;
  logs.style.cssText = "max-height:260px;overflow:auto;white-space:pre-wrap;font:11px ui-monospace,Consolas,monospace;background:#0b0c0f;padding:8px;border:1px solid #333;user-select:text";
  let invite = null;
  async function loadInvite() {
    try { invite = await call("host_invite"); } catch { invite = null; }
    inviteLine.textContent = invite ? `Invite link: ${invite}` : "The invite link appears after the first start.";
  }
  ctl.append(
    btn("STOP", "btn small", async () => {
      note(ctlStatus, "Stopping…");
      try { note(ctlStatus, await call("host_stop"), "ok"); } catch (e) { note(ctlStatus, String(e), "bad"); }
    }),
    btn("LOGS", "btn small", async () => {
      if (!logs.hidden) { logs.hidden = true; return; }
      note(ctlStatus, "Reading the logs…");
      try { logs.textContent = await call("host_logs", { lines: 200 }) || "(no log lines yet)"; logs.hidden = false; logs.scrollTop = logs.scrollHeight; note(ctlStatus, ""); }
      catch (e) { note(ctlStatus, String(e), "bad"); }
    }),
    btn("COPY INVITE LINK", "btn small", async () => {
      await loadInvite();
      if (!invite) { note(ctlStatus, "No invite link yet: start your realm once.", "warn"); return; }
      try { await navigator.clipboard.writeText(invite); note(ctlStatus, "Copied. Friends open it once, then play from the launcher or the browser.", "ok"); }
      catch { note(ctlStatus, invite, "ok"); }
    }),
    btn("NEW INVITE LINK", "btn small", async () => {
      note(ctlStatus, "Making a new invite link…");
      try { invite = await call("host_new_invite"); inviteLine.textContent = `Invite link: ${invite}`; note(ctlStatus, "New link made. The old one no longer lets anyone new in.", "ok"); }
      catch (e) { note(ctlStatus, String(e), "bad"); }
    }),
  );
  if (hostCard) hostCard.append(ctl, inviteLine, ctlStatus, logs);

  // ---------------------------------------------------------------- Host page: the realm list details
  // Tags, region, language and the player limit are the network's filters; they live in the kit's state/beacon.json
  // (host.rs ListingDetails) and reach the list with the next heartbeat. Direct connections stay off unless the
  // host allows them AND the network turns them on (the p2p_hosting flag); nothing here turns a flag on.
  const TAGS = [["blizzlike", "Blizzlike"], ["boosted", "Boosted"], ["custom", "Custom"], ["pvp", "PvP"], ["rp", "RP"], ["hangout", "Hangout"], ["bots", "Bots"]];
  const REGIONS = [["", "Not shown"], ["na-east", "North America east"], ["na-west", "North America west"], ["sa", "South America"],
    ["eu", "Europe"], ["africa", "Africa"], ["me", "Middle East"], ["asia", "Asia"], ["oce", "Oceania"]];
  const listCard = mk("section", "card stone");
  listCard.id = "hl-card";
  const lhead = mk("div", "card-head");
  lhead.append(mk("span", "", "ON THE REALM LIST"));
  const tagBox = mk("div", "row");
  const tagChecks = TAGS.map(([v, label]) => {
    const l = mk("label", "check inline"); const c = mk("input", ""); c.type = "checkbox"; c.value = v;
    l.append(c, document.createTextNode(" " + label)); tagBox.append(l); return c;
  });
  const region = mk("select", "");
  for (const [v, t] of REGIONS) { const o = mk("option", "", t); o.value = v; region.append(o); }
  const lang = mk("input", ""); lang.placeholder = "en, de, pt-BR"; lang.maxLength = 6; lang.size = 8; lang.spellcheck = false;
  const maxp = mk("input", ""); maxp.type = "number"; maxp.min = "0"; maxp.max = "10000"; maxp.placeholder = "not shown";
  const direct = mk("input", ""); direct.type = "checkbox";
  const fields = mk("div", "row");
  const lr = mk("label", "inline", "Region "); lr.append(region);
  const ll = mk("label", "inline", "Language "); ll.append(lang);
  const lm = mk("label", "inline", "Player limit "); lm.append(maxp);
  fields.append(lr, ll, lm);
  const dl = mk("label", "check inline"); dl.append(direct, document.createTextNode(" Allow direct connections (off by default; only used once the network turns direct connections on)"));
  const listStatus = mk("p", "status");
  listCard.append(lhead, mk("p", "lede", "How players find your realm: the rules it runs, where it is and its language. Bots are tagged by themselves when your realm runs them."),
    tagBox, fields, dl, mk("div", "row"), listStatus);
  listCard.lastChild.previousSibling.append(btn("SAVE", "btn small", saveListing));
  panel.insertBefore(listCard, packCard.nextSibling);

  async function loadListing() {
    let d;
    try { d = await call("host_listing"); } catch (e) { note(listStatus, String(e), "warn"); return; }
    tagChecks.forEach((c) => { c.checked = d.tags.includes(c.value); });
    region.value = d.region || "";
    lang.value = d.language || "";
    maxp.value = d.max_players || "";
    direct.checked = !!d.direct;
  }
  async function saveListing() {
    const details = {
      tags: tagChecks.filter((c) => c.checked).map((c) => c.value),
      region: region.value || null,
      language: lang.value.trim() || null,
      max_players: +maxp.value > 0 ? Math.floor(+maxp.value) : null,
      direct: direct.checked,
    };
    note(listStatus, "Saving…");
    try { note(listStatus, await call("host_listing_set", { details }), "ok"); } catch (e) { note(listStatus, String(e), "bad"); }
  }

  // ---------------------------------------------------------------- Host page: which game (host any client)
  // The realm profiles the kit can run for the clients Leyline found on this PC (host/profiles.rs). The pick is
  // saved in the kit folder; START MY REALM hands it to the kit's script with that client's folder, from which the
  // server data is made (read-only, nothing downloaded).
  const gameCard = mk("section", "card stone");
  gameCard.id = "hg-card";
  const ghead = mk("div", "card-head");
  ghead.append(mk("span", "", "WHICH GAME"));
  const gameSel = mk("select", "");
  const clientSel = mk("select", "");
  const gameHint = mk("p", "hint");
  const gameStatus = mk("p", "status");
  const gRow = mk("div", "row");
  const lg = mk("label", "inline", "Realm "); lg.append(gameSel);
  const lc = mk("label", "inline", "Your client "); lc.append(clientSel);
  gRow.append(lg, lc);
  gameCard.append(ghead, mk("p", "lede", "Host a realm for any client you have on this PC. Players need their own client of the same version."),
    gRow, gameHint, gameStatus);
  panel.insertBefore(gameCard, packCard.nextSibling);
  let offers = [];
  function showClients(keep) {
    const o = offers.find((x) => x.id === gameSel.value);
    clientSel.replaceChildren();
    for (const c of (o ? o.clients : [])) { const op = mk("option", "", `${c.name} · ${c.path}`); op.value = c.id; clientSel.append(op); }
    lc.hidden = !o || !o.clients.length;
    if (keep) clientSel.value = keep;
    gameHint.textContent = o ? (o.note || `Runs ${o.core} for the ${o.version} client. The server data is made from your client's folder (read-only).`) : "";
    gameHint.className = "hint" + (o && o.note ? " warn" : "");
  }
  async function saveGame() {
    const o = offers.find((x) => x.id === gameSel.value);
    if (o && o.note) { note(gameStatus, ""); return; }
    if (!o) {
      try { await call("host_choose", { profile: "", clientId: null }); note(gameStatus, "The kit keeps the realm it hosts, or asks on its first start.", "ok"); }
      catch (e) { note(gameStatus, String(e), "bad"); }
      return;
    }
    try {
      await call("host_choose", { profile: o.id, clientId: clientSel.value || null });
      note(gameStatus, `Saved: START MY REALM hosts a ${o.version} realm.`, "ok");
    } catch (e) { note(gameStatus, String(e), "bad"); }
  }
  gameSel.addEventListener("change", () => { showClients(); saveGame(); });
  clientSel.addEventListener("change", saveGame);
  async function loadGames() {
    let r;
    try { r = await call("host_profiles"); } catch (e) { gameHint.textContent = String(e); return; }
    if (!Array.isArray(r) || !Array.isArray(r[0])) return;
    const [list, choice] = r;
    offers = list.filter((o) => o && Array.isArray(o.clients));
    gameSel.replaceChildren();
    const first = mk("option", "", "As set up before (or the kit asks)"); first.value = ""; gameSel.append(first);
    for (const o of offers) {
      const op = mk("option", "", o.note ? `${o.label} (needs a ${o.version} client)` : o.label);
      op.value = o.id; op.disabled = !!o.note; gameSel.append(op);
    }
    let keep = null;
    if (choice && offers.some((o) => o.id === choice.profile && !o.note)) {
      gameSel.value = choice.profile;
      const o = offers.find((x) => x.id === choice.profile);
      const c = o.clients.find((x) => x.path === choice.client_dir);
      keep = c ? c.id : null;
    }
    showClients(keep);
  }

  function loadHostExtras() { loadPack(); loadDocker(); loadInvite(); loadListing(); loadGames(); }

  // ---------------------------------------------------------------- Settings > Advanced: P2P and torrent
  const setPanel = byId("page-settings") && byId("page-settings").querySelector(".panel");
  const adv = mk("section", "");
  adv.id = "p2p-adv";
  const advList = mk("div", "");
  const advStatus = mk("p", "status");
  const natLine = mk("p", "hint");
  adv.append(mk("h3", "", "Advanced: peer-to-peer"),
    mk("p", "lede", "Off unless you or the website turn them on. Peer-to-peer never carries game files or a game client: only Leyline itself, mods that passed the Workshop checks, theme packs and the Host pack, each checked against its sha256."),
    advList, natLine, advStatus);
  if (setPanel) setPanel.insertBefore(adv, setPanel.querySelector("h3") || null);

  async function loadFlags() {
    let v;
    try { v = await call("p2p_flags"); } catch (e) { note(advStatus, String(e), "bad"); return; }
    advList.replaceChildren();
    for (const [name, label] of v.known) {
      const row = mk("label", "inline");
      const sel = mk("select", "");
      const local = Object.prototype.hasOwnProperty.call(v.local.overrides, name) ? v.local.overrides[name] : null;
      for (const [val, text] of [["", `Follow the website (${v.site[name] ? "on" : "off"})`], ["on", "On on this PC"], ["off", "Off on this PC"]]) {
        const o = mk("option", "", text); o.value = val; sel.append(o);
      }
      sel.value = local === null ? "" : (local ? "on" : "off");
      sel.addEventListener("change", async () => {
        try { await call("p2p_set_flag", { name, value: sel.value === "" ? null : sel.value === "on" }); note(advStatus, "Saved.", "ok"); loadFlags(); }
        catch (e) { note(advStatus, String(e), "bad"); }
      });
      row.append(mk("span", "", `${label}: ${v.effective[name] ? "ON" : "off"} `), sel);
      advList.append(row);
    }
    const lim = v.effective.limits;
    const up = mk("input", ""); up.type = "number"; up.min = "0"; up.max = "100000"; up.value = lim.seed_upload_kbps;
    const ratio = mk("input", ""); ratio.type = "number"; ratio.min = "0"; ratio.max = "1000"; ratio.value = lim.seed_ratio_pct;
    const limRow = mk("div", "row");
    const l1 = mk("label", "inline", "Upload cap KB/s (0 = none) "); l1.append(up);
    const l2 = mk("label", "inline", "Share back up to % of size (0 = never) "); l2.append(ratio);
    limRow.append(l1, l2, btn("SAVE LIMITS", "btn small", async () => {
      try {
        await call("p2p_set_limits", { limits: { seed_upload_kbps: +up.value || 0, seed_ratio_pct: +ratio.value || 0, max_peers: lim.max_peers || 30 } });
        note(advStatus, "Limits saved.", "ok");
      } catch (e) { note(advStatus, String(e), "bad"); }
    }));
    advList.append(limRow);
    natLine.replaceChildren();
    if (v.effective.p2p_hosting) {
      natLine.append(btn("CHECK MY NETWORK", "btn small", async () => {
        note(advStatus, "Asking a STUN server for this PC's public address…");
        try {
          const r = await call("p2p_nat_check");
          const words = { open: "no router in the way", endpoint_independent: "direct connections can work", symmetric: "direct connections will not work: the relay is used", unknown: "could not tell", blocked: "UDP is blocked: the relay is used" };
          note(advStatus, `Network: ${words[r.kind] || r.kind}.`, r.kind === "open" || r.kind === "endpoint_independent" ? "ok" : "warn");
        } catch (e) { note(advStatus, String(e), "bad"); }
      }));
    }
    // "Help the network: relay for others" (docs/LEYLINE-MESH.md): only when the website offers it AND this PC is "On".
    if (v.site.relay_volunteer && v.local.overrides.relay_volunteer === true) {
      const hostIn = mk("input", ""); hostIn.placeholder = "this PC's public name, like relay.example.org"; hostIn.size = 34;
      const vRow = mk("div", "row");
      vRow.append(mk("span", "hint", "Relaying needs a public name for this PC and ports 80, 443 and 41000-41051 open. Players' game traffic passes through it (never passwords). "), hostIn,
        btn("START RELAYING", "btn small", async () => {
          note(advStatus, "Starting the community relay…");
          try { note(advStatus, await call("host_volunteer_relay", { on: true, publicHost: hostIn.value.trim(), region: null }), "ok"); }
          catch (e) { note(advStatus, String(e), "bad"); }
        }),
        btn("STOP", "btn small", async () => {
          try { note(advStatus, await call("host_volunteer_relay", { on: false, publicHost: null, region: null }), "ok"); }
          catch (e) { note(advStatus, String(e), "bad"); }
        }));
      advList.append(vRow);
    }
    if (v.error) note(advStatus, v.from_cache ? "Using the saved copy of the website's switches (offline)." : "Could not read the website's switches: everything stays off unless you turn it on here.", "warn");
  }

  // ---------------------------------------------------------------- when the pages open
  document.querySelectorAll('[data-page="host"]').forEach((b) => b.addEventListener("click", loadHostExtras));
  document.querySelectorAll('[data-page="settings"]').forEach((b) => b.addEventListener("click", loadFlags));
})();
