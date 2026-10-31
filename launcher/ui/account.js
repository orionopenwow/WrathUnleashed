// Leyline Launcher: Manage account (owner 2026-10-30: "Allow manage account within launcher, bio profile pic etc basic
// stuff, smooth out the login process"). A page of its own (#page-account), opened from the title bar's profile chip.
//
// Signed out: the sign-in in steps (1 Sign in, 2 Your profile, 3 Play), the same chooser as the website's /wrath/signin
// (Hero Key, Google, Discord: only the ways the website offers) and the waiting state while the browser is open; the
// sign-in itself is social.js's (LeylineSocial). The first time after signing in: step 2, the profile, with Skip.
// Signed in: your picture, name#tag and bio; edit the display name, the picture (your initial or one of the website's
// preset pictures) and the bio; the ways to sign in (each opens the website: the Hero Key page, link Google or Discord,
// linked launchers); Sign out. Saving goes through the core's social_call "profile" (src-tauri/src/social.rs ACTIONS),
// which only sends name, avatar, bio and setup. Everything from the server is shown with textContent.
//
// Loaded after social.js, before app.js.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const tauri = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;
  const invoke = tauri || (async () => { throw "This is a preview page: open it in the Leyline app."; });
  const S = () => window.LeylineSocial;
  const BIO_MAX = 300;
  const NAME_RE = /^[A-Za-z0-9_.\-À-ɏ]{2,24}$/;
  const PRESET_RE = /^https:\/\/play\.openvanilla\.app\/wrath\/avatar\/p\/([a-z]{2,12})\.svg$/;

  let welcome = false, back = "play", draft = null, busy = false;

  function steps(on) {
    const ol = el("ol", "ac-steps"); ol.setAttribute("aria-label", "Steps");
    ["Sign in", "Your profile", "Play"].forEach((n, i) => {
      const li = el("li", i + 1 === on ? "on" : i + 1 < on ? "done" : "");
      li.dataset.n = String(i + 1);
      if (i + 1 === on) li.setAttribute("aria-current", "step");
      li.append(el("span", "", n));
      ol.append(li);
    });
    return ol;
  }

  function status(text, kind) {
    const s = $("ac-status");
    if (!s) return;
    s.textContent = text || "";
    s.className = "status" + (kind ? " " + kind : "");
  }

  // ---------------------------------------------------------------- signed out: the sign-in
  function renderSignedOut(view) {
    const card = el("section", "card ac-card ac-signin");
    card.append(steps(1), el("h2", "", "Sign in"),
      el("p", "ac-lede", "One account for the launcher, the website and the forum: your name and picture, mod ratings, and your Hero Key on community realms."));
    const box = el("div", "ac-flow"); box.id = "ac-flow";
    S().buildFlow(box, true);
    card.append(box);
    view.append(card);
  }

  // ---------------------------------------------------------------- signed in: the profile
  function pictureGrid(me, extra, chosen) {
    const fs = el("fieldset", "ac-pics");
    fs.append(el("legend", "ac-label", "Picture"));
    const opts = [["", "Your initial", ""]];
    for (const a of (extra.avatars || [])) {
      const m = PRESET_RE.exec(String(a.url || ""));
      if (m && m[1] === a.id) opts.push([a.id, String(a.name || a.id), a.url]);
    }
    for (const [id, name, url] of opts) {
      const lab = el("label", "ac-pic"); lab.title = name;
      const r = el("input"); r.type = "radio"; r.name = "ac-avatar"; r.value = id; r.checked = id === chosen;
      r.setAttribute("aria-label", name);
      r.onchange = () => { draft.avatar = id; preview(me); };
      const av = id ? S().avatar(name, "ac-pic-av", url) : S().avatar(draft.name || me.name, "ac-pic-av");
      lab.append(r, av);
      fs.append(lab);
    }
    if (opts.length === 1) fs.append(el("p", "hint", "The pictures load from the website. They'll show when it's reachable."));
    return fs;
  }

  function preview(me) {
    const box = $("ac-me-av");
    if (!box) return;
    const extra = S().extra();
    const p = (extra.avatars || []).find((a) => a.id === draft.avatar);
    const url = draft.avatar ? (p ? p.url : "") : (draft.avatar === (me.profile && me.profile.avatar) ? (me.profile && me.profile.avatar_url) : "");
    box.replaceChildren(S().avatar(draft.name || me.name, "ac-big", draft.avatar === "" && me.profile && me.profile.avatar === "" ? me.profile.avatar_url : url));
  }

  function renderProfile(view, me) {
    const extra = S().extra();
    const prof = me.profile || { bio: "", avatar: "", setup: true };
    if (!draft) draft = { name: me.name, avatar: prof.avatar || "", bio: prof.bio || "" };
    const ways = S().ways() || {};

    if (!welcome) {
      const head = el("section", "card ac-card ac-head");
      const av = el("div", "ac-me-av"); av.id = "ac-me-av";
      const t = el("div", "ac-me-t");
      const n = el("p", "ac-me-n"); n.append(el("b", "", me.name), el("span", "", me.tag ? "#" + me.tag : ""));
      t.append(n, el("p", "hint", "Signed in on this launcher"));
      if (prof.bio) t.append(el("p", "ac-me-bio", prof.bio));
      head.append(av, t);
      view.append(head);
    }

    // the form
    // the first time, the form is step 2 itself: the steps and the welcome on top of it, all in one card
    const form = el("form", "card ac-card ac-form" + (welcome ? " ac-welcome" : "")); form.id = "ac-form"; form.noValidate = true;
    // TODO(owner): the welcome words
    if (welcome) form.append(steps(2), el("h2", "", `Welcome, ${me.name}`), el("p", "ac-lede", "Pick how others see you on the forum and in the launcher. You can change it any time."));
    else form.append(el("h3", "", "Edit your profile"));
    const nl = el("label", "ac-label", "Display name"); nl.htmlFor = "ac-name";
    const name = el("input"); name.id = "ac-name"; name.type = "text"; name.maxLength = 24; name.value = draft.name; name.autocomplete = "off"; name.spellcheck = false;
    name.setAttribute("aria-describedby", "ac-name-h");
    const nh = el("p", "hint", `2 to 24 letters, digits, dots, dashes or underscores. Others see it with your tag${me.tag ? " (#" + me.tag + ")" : ""}.`); nh.id = "ac-name-h";
    name.oninput = () => { draft.name = name.value; };
    const bl = el("label", "ac-label", "Bio (optional)"); bl.htmlFor = "ac-bio";
    const bio = el("textarea"); bio.id = "ac-bio"; bio.maxLength = BIO_MAX; bio.rows = 3; bio.value = draft.bio;
    bio.placeholder = "A line about you, your realm or what you play.";
    const count = el("span", "ac-count", `${draft.bio.length}/${BIO_MAX}`); count.setAttribute("aria-live", "polite");
    bio.oninput = () => { draft.bio = bio.value; count.textContent = `${bio.value.length}/${BIO_MAX}`; };
    const acts = el("div", "ac-acts");
    const save = el("button", "btn primary", welcome ? "Save and continue" : "Save"); save.type = "submit"; save.id = "ac-save";
    acts.append(save);
    if (welcome) {
      const skip = el("button", "btn", "Skip for now"); skip.type = "button"; skip.id = "ac-skip";
      skip.onclick = () => submit(true);
      acts.append(skip);
    }
    const st = el("p", "status"); st.id = "ac-status"; st.setAttribute("role", "status");
    form.append(nl, name, nh, pictureGrid(me, extra, draft.avatar), bl, bio, count, acts, st);
    form.onsubmit = (e) => { e.preventDefault(); submit(false); };
    view.append(form);

    if (welcome) { preview(me); return; }

    // the ways to sign in
    const wc = el("section", "card ac-card ac-ways");
    wc.append(el("h3", "", "Ways to sign in"),
      el("p", "hint", "Each opens the website in your browser. Linking another way lets it sign in to this same account."));
    const ul = el("ul", "ac-list");
    const row = (title, line, label, link) => {
      const li = el("li");
      const t = el("div"); t.append(el("b", "", title)); if (line) t.append(el("span", "", line));
      const b = el("button", "btn small", label); b.type = "button"; b.dataset.link = link;
      b.onclick = () => S().openLink(link);
      li.append(t, b); ul.append(li);
    };
    row("Hero Key", "Your key signs you in on any device. Unlinking a way is done there too.", "Manage", "herokey");
    if (ways.google) row("Google", "", "Link Google", "linkgoogle");
    if (ways.discord) row("Discord", "", "Link Discord", "linkdiscord");
    row("Leyline launchers", "This one and any others signed in as you. Revoke one there.", "Linked launchers", "linkedlaunchers");
    wc.append(ul);
    view.append(wc);

    const so = el("section", "card ac-card ac-out");
    const sot = el("div"); sot.append(el("h3", "", "Sign out"), el("p", "hint", "Signs this launcher out and revokes its sign-in on the website."));
    const sob = el("button", "btn", "Sign out"); sob.type = "button"; sob.id = "ac-signout";
    sob.onclick = () => S().signOut();
    const web = el("button", "link-s", "Your profile on the website ›"); web.type = "button"; web.onclick = () => S().openLink("profile");
    so.append(sot, el("div", "ac-acts", ""), web);
    so.querySelector(".ac-acts").append(sob);
    view.append(so);
    preview(me);
  }

  async function submit(skip) {
    if (busy) return;
    const me = S().me();
    if (!me) return;
    const prof = me.profile || {};
    const args = { setup: true };
    if (!skip) {
      const n = (draft.name || "").trim();
      if (!NAME_RE.test(n)) { status("Names are 2 to 24 letters, digits, dots, dashes or underscores.", "bad"); $("ac-name").focus(); return; }
      if (n !== me.name) args.name = n;
      if (draft.avatar !== (prof.avatar || "")) args.avatar = draft.avatar;
      if (draft.bio !== (prof.bio || "")) args.bio = draft.bio;
    }
    busy = true;
    const btn = $("ac-save"); if (btn) btn.disabled = true;
    status("Saving…");
    try {
      const out = await invoke("social_call", { action: "profile", args });
      busy = false;
      S().setMe(out && out.me ? out.me : null);
      draft = null;
      if (welcome) {
        welcome = false;
        if (window.LeylineNav) window.LeylineNav.show(back && back !== "account" ? back : "play");
        return;
      }
      render();
      status("Saved.", "ok");
    } catch (e) {
      busy = false;
      if (btn) btn.disabled = false;
      const msg = String(e);
      status(msg === "signed_out" ? "You were signed out. Sign in again." : msg, "bad");
      if (msg === "signed_out") S().refresh();
    }
  }

  function render() {
    const view = $("ac-view");
    if (!view) return;
    const s = S();
    if (!s) return;
    const me = s.me();
    view.textContent = "";
    view.classList.toggle("ac-two", !!(s.signedIn() && me && !welcome));
    if (!s.signedIn() || !me) { draft = null; renderSignedOut(view); return; }
    renderProfile(view, me);
  }

  const onPage = () => window.LeylineNav && window.LeylineNav.current().page === "account";
  document.addEventListener("leyline:page", (ev) => {
    const page = (ev.detail || {}).page;
    if (page !== "account") { back = page; welcome = false; draft = null; return; }
    if (!S().signedIn()) S().loadWays();
    render();
    if (S().signedIn() && !S().me()) S().refresh();
  });
  document.addEventListener("leyline:me", () => { if (onPage() && !busy) { draft = null; render(); } });
  document.addEventListener("leyline:welcome", () => { welcome = true; draft = null; if (onPage()) render(); });
  document.addEventListener("leyline:signin", () => {
    if (!onPage() || S().signedIn()) return;
    const box = $("ac-flow");
    if (box) S().buildFlow(box, true); else render();
  });

  window.LeylineAccount = { render, welcome: () => welcome };
})();
