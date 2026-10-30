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

  function loadHostExtras() { loadPack(); loadDocker(); loadInvite(); }

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
    if (v.error) note(advStatus, v.from_cache ? "Using the saved copy of the website's switches (offline)." : "Could not read the website's switches: everything stays off unless you turn it on here.", "warn");
  }

  // ---------------------------------------------------------------- when the pages open
  document.querySelectorAll('[data-page="host"]').forEach((b) => b.addEventListener("click", loadHostExtras));
  document.querySelectorAll('[data-page="settings"]').forEach((b) => b.addEventListener("click", loadFlags));
})();
