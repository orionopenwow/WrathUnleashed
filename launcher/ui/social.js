// Leyline Launcher: Home's right panel. Your profile at the top (owner 2026-10-30: "keep the profile thing up there where
// it is now"), then the Discord and the forum's latest threads (the friends area went "in favor of discord encouragement").
//
// The profile is the Leyline sign-in (the Rust core's social commands, src-tauri/src/social.rs, talking to the portal's
// /wrath/api/social: stream/social.py). It is the only place the launcher learns your name: the website's sign-in, in
// your browser (a code to approve), and the launcher keeps only a revocable token. The same sign-in rates mods and
// signs in to community realms with your Hero Key. Signed in: the avatar, your name with a menu (Manage account, Sign
// out). Signed out: Sign in. Friends, presence and messages are gone from the launcher.
//
// Loaded before app.js. Everything from the server is shown with textContent: no markup from anyone's name.
(function () {
  "use strict";
  const tauri = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;
  const invoke = tauri || (async (cmd) => {
    if (cmd === "social_status") return false;
    throw "This is a preview page: open it in the Leyline app.";
  });
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const openLink = (name) => invoke("open_link", { name }).catch((e) => say(String(e), "bad"));

  let me = null, signedIn = false, polling = false, code = "";

  function say(text, kind) {
    const s = $("hf-status");
    if (!s) return;
    s.textContent = text || "";
    s.className = "status hf-status" + (kind ? " " + kind : "");
  }

  // ---------------------------------------------------------------- the profile row
  function hue(name) { let h = 0; for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) >>> 0; return h % 360; }
  function avatar(name, cls) {
    const av = el("span", "sx-av" + (cls ? " " + cls : "")); av.style.setProperty("--h", hue(name));
    av.append(el("b", "", (String(name).match(/[A-Za-z0-9]/) || ["?"])[0].toUpperCase()));
    return av;
  }
  let meMenu = null;
  function closeMeMenu() { if (meMenu) { meMenu.remove(); meMenu = null; const b = $("hf-me-btn"); if (b) b.setAttribute("aria-expanded", "false"); } }
  document.addEventListener("pointerdown", (e) => { if (meMenu && !e.target.closest(".hf-me-pick")) closeMeMenu(); });

  function renderMe() {
    const box = $("hf-me");
    if (!box) return;
    closeMeMenu();
    box.textContent = "";
    if (!signedIn || !me) {
      const t = el("div", "hf-me-t");
      t.append(el("b", "hf-me-name", "Leyline"), el("span", "hf-me-st", "Signed out"));
      const b = el("button", "btn small primary hf-signin", "SIGN IN"); b.type = "button"; b.id = "hf-signin";
      b.title = "Sign in with the website (Google or your Hero Key), in your browser";
      b.onclick = signIn;
      box.append(avatar("?", "hf-me-av hf-anon"), t, b);
      renderCode();
      return;
    }
    const pick = el("div", "hf-me-pick");
    const btn = el("button", "hf-me-btn");
    btn.type = "button"; btn.id = "hf-me-btn";
    btn.setAttribute("aria-haspopup", "menu"); btn.setAttribute("aria-expanded", "false");
    btn.append(el("b", "hf-me-name", me.name));
    const car = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    car.setAttribute("viewBox", "0 0 24 24"); car.setAttribute("aria-hidden", "true"); car.classList.add("hf-caret");
    car.innerHTML = '<path d="M6 9l6 6 6-6"/>';
    btn.append(car);
    btn.title = me.tag ? `${me.name}#${me.tag}` : me.name;
    btn.onclick = () => {
      if (meMenu) { closeMeMenu(); return; }
      meMenu = el("div", "hf-me-menu"); meMenu.setAttribute("role", "menu");
      const item = (label, fn) => { const b = el("button", "", label); b.type = "button"; b.setAttribute("role", "menuitem"); b.onclick = () => { closeMeMenu(); fn(); }; meMenu.append(b); return b; };
      item("Manage account", () => openLink("account"));
      item("Sign out", signOut);
      meMenu.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMeMenu(); btn.focus(); } });
      pick.append(meMenu);
      btn.setAttribute("aria-expanded", "true");
      meMenu.querySelector("button").focus();
    };
    pick.append(btn, el("span", "hf-me-st", me.tag ? "#" + me.tag : "Signed in"));
    box.append(avatar(me.name, "hf-me-av"), pick);
    renderCode();
  }

  // the sign-in code, under the profile row while the browser page is open
  function renderCode() {
    const box = $("hf-code");
    if (!box) return;
    box.hidden = !code;
    box.textContent = "";
    if (!code) return;
    box.append(el("p", "", "Your browser opened the sign-in page. Approve it if it shows this code:"), el("p", "sx-code", code));
    const row = el("div", "hf-code-acts");
    const again = el("button", "link-s", "Open the page again"); again.type = "button";
    again.onclick = () => invoke("social_signin_reopen").catch((e) => say(String(e), "bad"));
    const cancel = el("button", "link-s", "Cancel"); cancel.type = "button";
    cancel.onclick = async () => { await invoke("social_signin_cancel").catch(() => {}); code = ""; renderCode(); say(""); };
    row.append(again, cancel);
    box.append(row);
  }

  async function loadMe() {
    try {
      const r = await invoke("social_call", { action: "me", args: {} });
      me = r && r.me ? r.me : null;
      signedIn = !!me;
    } catch (e) {
      if (String(e) === "signed_out") { signedIn = false; me = null; say("You were signed out. Sign in again.", "warn"); }
      else if (signedIn && !me) say("Couldn't reach the website to load your name. It will try again.", "warn");
    }
    renderMe();
  }

  async function signIn() {
    try {
      const s = await invoke("social_signin_start");
      code = s.user_code || "";
      renderCode();
      say("");
      if (polling) return;
      polling = true;
      try {
        for (;;) {
          await sleep(5000);
          if (!code) break;
          const p = await invoke("social_signin_poll");
          if (p.state === "pending") continue;
          code = "";
          if (p.state === "signed_in") { signedIn = true; say("Signed in.", "ok"); await loadMe(); }
          else if (p.state === "denied") { renderCode(); say("Not signed in: the code was refused on the website.", "warn"); }
          else { renderCode(); say("The code expired. Try again.", "warn"); }
          break;
        }
      } finally { polling = false; }
    } catch (e) { say(String(e), "bad"); }
  }

  async function signOut() {
    signedIn = false; me = null;
    await invoke("social_signout").catch(() => {});
    renderMe(); say("Signed out. The sign-in was revoked on the website too.", "ok");
  }

  // ---------------------------------------------------------------- under it: the Discord and the forum
  function renderBody() {
    const box = $("hf-body");
    if (!box) return;
    box.textContent = "";
    const dc = el("section", "hf-dc");
    dc.setAttribute("aria-labelledby", "hf-dc-h");
    const ic = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    ic.setAttribute("viewBox", "0 0 24 24"); ic.setAttribute("aria-hidden", "true"); ic.classList.add("hf-dc-ic");
    ic.innerHTML = '<path d="M4 6.5C4 5.1 5.1 4 6.5 4h11C18.9 4 20 5.1 20 6.5v8c0 1.4-1.1 2.5-2.5 2.5H11l-4.5 3.5V17C5.1 17 4 15.9 4 14.5z"/><circle cx="9" cy="10.5" r="1.2"/><circle cx="15" cy="10.5" r="1.2"/>';
    const h = el("h3", "", "Join the Discord"); h.id = "hf-dc-h";
    // TODO(owner): the Discord line in the launcher
    const p = el("p", "", "Find a group, voice chat, show what you made and hear about new realms first.");
    const b = el("button", "btn small primary hf-dc-go", "JOIN THE DISCORD"); b.type = "button";
    b.onclick = () => openLink("discord");
    dc.append(ic, h, p, b);
    const fm = el("section", "hf-fm");
    fm.setAttribute("aria-labelledby", "hf-fm-h");
    const head = el("div", "hf-fm-head");
    const fh = el("h3", "", "On the forum"); fh.id = "hf-fm-h";
    const all = el("button", "link-s", "Open ›"); all.type = "button"; all.title = "Open the Forum page";
    all.onclick = () => window.LeylineNav && window.LeylineNav.show("forum");
    head.append(fh, all);
    const list = el("ul", "hf-fm-list"); list.id = "hf-fm-list";
    fm.append(head, list);
    box.append(dc, fm, Object.assign(el("p", "status hf-status"), { id: "hf-status" }));
    loadLatest();
  }

  async function loadLatest() {
    const list = $("hf-fm-list");
    if (!list) return;
    let threads = [];
    try {
      const r = await invoke("forum_call", { action: "latest", args: { n: 3 } });
      threads = (r && Array.isArray(r.threads)) ? r.threads.slice(0, 3) : [];
    } catch (_) {
      list.replaceChildren(el("li", "hint", "The forum isn't reachable right now."));
      return;
    }
    if (!threads.length) { list.replaceChildren(el("li", "hint", "No threads yet. Start the first one on the Forum page.")); return; }
    list.replaceChildren(...threads.map((t) => {
      const li = el("li");
      const b = el("button", "hf-fm-row"); b.type = "button";
      b.append(el("b", "", String(t.title || "")), el("span", "", `${t.author || "Someone"} · ${t.replies || 0} repl${t.replies === 1 ? "y" : "ies"}`));
      b.onclick = () => { if (window.LeylineForum) window.LeylineForum.openThread(t.id); };
      li.append(b);
      return li;
    }));
  }

  // ---------------------------------------------------------------- start
  renderBody();
  (async () => {
    let yes = false;
    try { yes = await invoke("social_status"); } catch (_) { yes = false; }
    signedIn = !!yes;
    renderMe();
    if (yes) loadMe();
  })();
  // back on Home: the latest threads again
  document.addEventListener("leyline:page", (ev) => { if ((ev.detail || {}).page === "play") loadLatest(); });

  window.LeylineSocial = { refresh: loadMe, me: () => me, signedIn: () => signedIn, signIn, loadLatest };
})();
