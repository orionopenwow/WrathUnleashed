// Leyline Launcher: your profile (the title bar's chip, top right) and the sign-in. Under it in the code: Home's old right
// panel (the Discord and the forum's latest threads), hidden for now (owner 2026-10-30).
//
// The profile is the Leyline sign-in (the Rust core's social commands, src-tauri/src/social.rs, talking to the portal's
// /wrath/api/social: stream/social.py and stream/profiles.py). Signing in happens on the website, in your browser: you
// pick a way (Hero Key, Google or Discord: only the ones the website offers right now), the browser opens that way's
// sign-in with a code, and Leyline continues by itself once the code is approved. The launcher keeps only a revocable
// token. The first time, Manage account (account.js) opens for the profile step (name, picture, bio). Signed in: your
// picture and name with a menu (Manage account, Sign out). The same sign-in rates mods and signs in to community realms
// with your Hero Key.
//
// The sign-in's state (flow) is shared with Manage account, which shows the same chooser and waiting state; both listen
// for "leyline:signin" and "leyline:me". Loaded before app.js. Everything from the server is shown with textContent or
// as an image address from it: no markup from anyone's name.
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
  const emit = (name, detail) => document.dispatchEvent(new CustomEvent(name, { detail }));

  let me = null, extra = {}, signedIn = false, code = "", ways = null;
  // the sign-in in progress: stage idle | choose | waiting | error; via: the way picked; note: what went wrong
  const flow = { stage: "idle", via: "", note: "" };
  let runId = 0;

  function say(text, kind) {
    const s = $("hf-status");
    if (!s) return;
    s.textContent = text || "";
    s.className = "status hf-status" + (kind ? " " + kind : "");
  }

  // ---------------------------------------------------------------- pictures
  function hue(name) { let h = 0; for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) >>> 0; return h % 360; }
  function letterOf(name) { return (String(name).match(/[A-Za-z0-9]/) || ["?"])[0].toUpperCase(); }
  // a picture from the website (only https://play.openvanilla.app, the one place the launcher loads images from), else the
  // letter on a hue from the name; a picture that doesn't load falls back to the letter
  const PIC_RE = /^https:\/\/play\.openvanilla\.app\/wrath\/avatar\/[a-z]\/[a-z0-9]{2,12}\.svg(\?v=\d{1,9})?$/;
  function avatar(name, cls, url) {
    const av = el("span", "sx-av" + (cls ? " " + cls : "")); av.style.setProperty("--h", hue(name));
    const b = el("b", "", letterOf(name));
    av.append(b);
    if (url && PIC_RE.test(url)) {
      const img = el("img"); img.alt = ""; img.decoding = "async"; img.referrerPolicy = "no-referrer";
      img.onload = () => av.classList.add("has-pic");
      img.onerror = () => img.remove();
      img.src = url;
      av.append(img);
    }
    return av;
  }
  const picOf = (m) => (m && m.profile && m.profile.avatar_url) || "";

  // ---------------------------------------------------------------- the ways and the chooser
  const WAYS = [["herokey", "Hero Key", "Sign in with your Hero Key"], ["google", "Google", "Continue with Google"], ["discord", "Discord", "Continue with Discord"]];
  const WAY_ICON = {
    herokey: '<path fill="currentColor" d="M7 14a3 3 0 1 1 0-6 3 3 0 0 1 0 6Zm5.65-4A6 6 0 1 0 12.65 14H15v3h3v-3h2v-4h-7.35Z"/>',
    google: '<path fill="#EA4335" d="M12 4.75c1.77 0 3.36.61 4.6 1.8l3.43-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.69 1.28 6.61l3.99 3.1C6.22 6.86 8.87 4.75 12 4.75z"/><path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.13 2.74-2.39 3.59l3.86 3c2.26-2.09 3.55-5.18 3.55-8.83z"/><path fill="#FBBC05" d="M5.26 14.29A7.2 7.2 0 0 1 4.89 12c0-.8.14-1.57.38-2.29l-3.99-3.1A11.95 11.95 0 0 0 0 12c0 1.94.46 3.77 1.28 5.39l3.98-3.1z"/><path fill="#34A853" d="M12 24c3.24 0 5.97-1.06 7.95-2.9l-3.86-3c-1.08.72-2.46 1.15-4.09 1.15-3.13 0-5.78-2.11-6.73-4.96l-3.98 3.1C3.25 21.3 7.3 24 12 24z"/>',
    discord: '<path fill="currentColor" d="M20.32 4.37A19.8 19.8 0 0 0 15.43 2.8a13.7 13.7 0 0 0-.63 1.29 18.4 18.4 0 0 0-5.6 0 13 13 0 0 0-.64-1.29 19.7 19.7 0 0 0-4.89 1.52C.56 9.04-.28 13.6.14 18.1a19.9 19.9 0 0 0 6.02 3.04c.49-.66.92-1.36 1.29-2.1a12.9 12.9 0 0 1-2.03-.97c.17-.13.34-.26.5-.39a14.2 14.2 0 0 0 12.16 0c.17.14.33.27.5.39-.65.38-1.33.71-2.04.97.37.74.8 1.44 1.29 2.1a19.8 19.8 0 0 0 6.03-3.04c.5-5.22-.84-9.74-3.54-13.73ZM8.02 15.33c-1.18 0-2.16-1.08-2.16-2.42 0-1.33.96-2.42 2.16-2.42 1.21 0 2.18 1.1 2.16 2.42 0 1.34-.96 2.42-2.16 2.42Zm7.97 0c-1.19 0-2.16-1.08-2.16-2.42 0-1.33.95-2.42 2.16-2.42 1.2 0 2.18 1.1 2.16 2.42 0 1.34-.95 2.42-2.16 2.42Z"/>',
  };
  function svg(inner, cls) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); if (cls) s.classList.add(cls);
    s.innerHTML = inner;   // our own constant icons only
    return s;
  }
  async function loadWays() {
    try { ways = await invoke("social_ways"); }
    catch (_) { if (!ways) ways = { herokey: true, google: true, discord: false }; }
    emit("leyline:signin", { ...flow, code });
    return ways;
  }
  const wayOn = (k) => !ways || ways[k] === true || k === "herokey";

  // The chooser and the waiting state, built into box (the title bar's pop-over, or Manage account's card).
  function buildFlow(box, big) {
    box.textContent = "";
    if (flow.stage === "waiting") {
      const w = el("div", "sf-wait");
      const sp = el("span", "ly-spin"); sp.setAttribute("aria-hidden", "true");
      const t = el("div", "sf-wait-t");
      t.append(el("b", "", "Waiting for your browser…"),
        el("span", "", "Finish signing in there" + (flow.via ? " with " + (WAYS.find((x) => x[0] === flow.via) || ["", "the website"])[1] : "") + ", then approve this code. Leyline continues by itself."));
      w.append(sp, t);
      const c = el("p", "sx-code", code); c.setAttribute("aria-label", "Sign-in code " + code.split("").join(" "));
      const row = el("div", "sf-acts");
      const again = el("button", "btn small", "OPEN THE PAGE AGAIN"); again.type = "button";
      again.onclick = () => invoke("social_signin_reopen").catch((e) => fail(String(e)));
      const cancel = el("button", "link-s", "Cancel"); cancel.type = "button"; cancel.onclick = cancelSignIn;
      row.append(again, cancel);
      box.append(w, c, row);
      return;
    }
    if (flow.stage === "error") {
      const p = el("p", "sf-err", flow.note); p.setAttribute("role", "alert");
      box.append(p);
    }
    if (!big) box.append(el("p", "sf-h", "Sign in to Leyline"));
    const list = el("div", "sf-ways");
    for (const [k, , label] of WAYS) {
      if (!wayOn(k)) continue;
      const b = el("button", "sf-way sf-" + k); b.type = "button"; b.dataset.via = k;
      b.append(svg(WAY_ICON[k]), el("span", "", label));
      b.onclick = () => signIn(k);
      list.append(b);
    }
    box.append(list, el("p", "sf-fine", "Opens the website in your browser. New here? Google" + (wayOn("discord") ? " or Discord" : "")
      + " makes your free account. We never see your password."));
  }

  // ---------------------------------------------------------------- the title bar's chip
  let meMenu = null;
  function closeMeMenu() { if (meMenu) { meMenu.remove(); meMenu = null; const b = $("hf-me-btn"); if (b) b.setAttribute("aria-expanded", "false"); } }
  document.addEventListener("pointerdown", (e) => {
    if (meMenu && !e.target.closest(".hf-me-pick")) closeMeMenu();
    if (flow.stage === "choose" && !e.target.closest(".tb-me")) { flow.stage = "idle"; renderCode(); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && flow.stage === "choose") { flow.stage = "idle"; renderCode(); const b = $("hf-signin"); if (b) b.focus(); } });

  function renderMe() {
    const box = $("hf-me");
    if (!box) return;
    closeMeMenu();
    box.textContent = "";
    if (!signedIn || !me) {
      const t = el("div", "hf-me-t");
      t.append(el("b", "hf-me-name", "Leyline"), el("span", "hf-me-st", "Signed out"));
      const b = el("button", "btn small primary hf-signin", "SIGN IN"); b.type = "button"; b.id = "hf-signin";
      b.title = "Sign in with your Hero Key, Google or Discord, in your browser";
      b.setAttribute("aria-haspopup", "dialog");
      b.onclick = () => {
        if (flow.stage === "waiting") { renderCode(); return; }
        flow.stage = flow.stage === "choose" ? "idle" : "choose"; flow.note = "";
        renderCode();
        if (flow.stage === "choose") { loadWays(); const f = document.querySelector("#hf-code .sf-way"); if (f) f.focus(); }
      };
      box.append(avatar("?", "hf-me-av hf-anon"), t, b);
      renderCode();
      return;
    }
    const pick = el("div", "hf-me-pick");
    const btn = el("button", "hf-me-btn");
    btn.type = "button"; btn.id = "hf-me-btn";
    btn.setAttribute("aria-haspopup", "menu"); btn.setAttribute("aria-expanded", "false");
    btn.append(el("b", "hf-me-name", me.name));
    btn.append(svg('<path d="M6 9l6 6 6-6"/>', "hf-caret"));
    btn.title = me.tag ? `${me.name}#${me.tag}` : me.name;
    btn.onclick = () => {
      if (meMenu) { closeMeMenu(); return; }
      meMenu = el("div", "hf-me-menu"); meMenu.setAttribute("role", "menu");
      const item = (label, fn) => { const b = el("button", "", label); b.type = "button"; b.setAttribute("role", "menuitem"); b.onclick = () => { closeMeMenu(); fn(); }; meMenu.append(b); return b; };
      item("Manage account", manage);
      item("Sign out", signOut);
      meMenu.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMeMenu(); btn.focus(); } });
      pick.append(meMenu);
      btn.setAttribute("aria-expanded", "true");
      meMenu.querySelector("button").focus();
    };
    pick.append(btn, el("span", "hf-me-st", me.tag ? "#" + me.tag : "Signed in"));
    const av = avatar(me.name, "hf-me-av", picOf(me));
    av.title = "Manage account"; av.classList.add("hf-me-pic");
    av.onclick = manage;
    box.append(av, pick);
    renderCode();
  }
  function manage() { if (window.LeylineNav) window.LeylineNav.show("account"); }

  // the pop-over under the chip: the chooser, then the code while the browser is open
  function renderCode() {
    const box = $("hf-code");
    if (box) {
      const open = !signedIn && (flow.stage === "choose" || flow.stage === "waiting" || flow.stage === "error")
        && !(window.LeylineNav && window.LeylineNav.current().page === "account");
      box.hidden = !open;
      if (open) buildFlow(box, false); else box.textContent = "";
      box.setAttribute("role", flow.stage === "waiting" ? "status" : "dialog");
      box.setAttribute("aria-label", "Sign in");
    }
    emit("leyline:signin", { ...flow, code });
  }

  async function loadMe() {
    try {
      const r = await invoke("social_call", { action: "me", args: {} });
      me = r && r.me ? r.me : null;
      extra = r ? { avatars: r.avatars || [], ways: r.ways || null, manage_url: r.manage_url || "" } : {};
      if (extra.ways) ways = Object.assign({}, ways || {}, extra.ways);
      signedIn = !!me;
    } catch (e) {
      if (String(e) === "signed_out") { signedIn = false; me = null; say("You were signed out. Sign in again.", "warn"); }
      else if (signedIn && !me) say("Couldn't reach the website to load your name. It will try again.", "warn");
    }
    renderMe();
    emit("leyline:me", { me, signedIn });
    return me;
  }

  function fail(note) { flow.stage = "error"; flow.note = note; code = ""; renderCode(); }

  async function signIn(via) {
    const id = ++runId;
    flow.via = typeof via === "string" ? via : ""; flow.note = "";
    try {
      const s = await invoke("social_signin_start", { via: flow.via || null });
      if (id !== runId) return;
      code = s.user_code || "";
      flow.stage = "waiting";
      renderCode();
      say("");
      for (;;) {
        await sleep(4000);
        if (id !== runId || flow.stage !== "waiting") return;
        let p;
        try { p = await invoke("social_signin_poll"); }
        catch (e) { if (id !== runId) return; continue; }   // a dropped connection: keep waiting
        if (id !== runId) return;
        if (p.state === "pending") continue;
        code = "";
        if (p.state === "signed_in") {
          flow.stage = "idle"; signedIn = true;
          renderCode();
          await loadMe();
          if (me && me.profile && me.profile.setup === false) {   // the first time: the profile step, in Manage account
            if (window.LeylineNav) window.LeylineNav.show("account");
            emit("leyline:welcome", {});
          } else say("Signed in.", "ok");
        } else if (p.state === "denied") fail("Not signed in: the code was refused on the website.");
        else if (p.state === "signed_out") { flow.stage = "idle"; renderCode(); return; }
        else fail("The code expired. Pick a way to try again.");
        return;
      }
    } catch (e) { if (id === runId) fail(String(e)); }
  }

  async function cancelSignIn() {
    runId++;
    await invoke("social_signin_cancel").catch(() => {});
    code = ""; flow.stage = "idle"; flow.note = "";
    renderCode(); say("");
  }

  async function signOut() {
    signedIn = false; me = null;
    await invoke("social_signout").catch(() => {});
    renderMe(); say("Signed out. The sign-in was revoked on the website too.", "ok");
    emit("leyline:me", { me: null, signedIn: false });
  }

  // after a save in Manage account: the chip shows the new name and picture
  function setMe(m) { if (m) { me = Object.assign({}, me || {}, m); signedIn = true; renderMe(); emit("leyline:me", { me, signedIn }); } }

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
    if (yes) loadMe(); else loadWays();
  })();
  // back on Home: the latest threads again
  document.addEventListener("leyline:page", (ev) => { if ((ev.detail || {}).page === "play") loadLatest(); });

  document.addEventListener("leyline:page", (ev) => { if ((ev.detail || {}).page !== "account" || flow.stage !== "idle") renderCode(); });

  window.LeylineSocial = { refresh: loadMe, me: () => me, extra: () => extra, signedIn: () => signedIn, signIn, signOut, cancelSignIn,
    loadLatest, flow: () => ({ ...flow, code }), ways: () => ways, loadWays, buildFlow, avatar, setMe, openLink };
})();
