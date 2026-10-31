// Leyline Launcher: the Forum page. Reads the website's forum (stream/forum.py) through the Rust core's forum commands
// (src-tauri/src/forum.rs): the categories, the latest threads, a category's threads, a thread, title search. Reading
// only: New thread and Reply open the forum's own pages in your browser (signed in with the website's sign-in).
//
// Loaded before app.js; app.js's navigation calls LeylineForum.load() when the page opens. Everything from the server is
// shown with textContent: a post is plain text, and its links are buttons that open only links the forum sent
// (forum.rs page_for "link").
(function () {
  "use strict";
  const tauri = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;
  const invoke = tauri || (async () => { throw "This is a preview page: open it in the Leyline app."; });
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const call = (action, args) => invoke("forum_call", { action, args: args || {} });
  const open = (kind, arg) => invoke("forum_open", { kind, arg: arg === undefined ? null : String(arg) })
    .then(() => say("Opened in your browser.", "ok")).catch((e) => say(String(e), "bad"));

  function say(text, kind) { const s = $("fm-status"); if (s) { s.textContent = text || ""; s.className = "status" + (kind ? " " + kind : ""); } }

  function ago(t) {
    const d = Math.max(0, Math.floor(Date.now() / 1000) - (t || 0));
    if (d < 60) return "just now";
    for (const [n, w] of [[86400 * 30, "month"], [86400 * 7, "week"], [86400, "day"], [3600, "hour"], [60, "minute"]]) {
      if (d >= n) { const k = Math.floor(d / n); return `${k} ${w}${k === 1 ? "" : "s"} ago`; }
    }
    return "just now";
  }
  const replies = (n) => `${n || 0} repl${n === 1 ? "y" : "ies"}`;

  let cats = [];
  let view = { kind: "home" };
  let seq = 0;

  function catName(id) { const c = cats.find((x) => x.id === id); return c ? c.name : "Forum"; }

  function loading(box) { box.replaceChildren(el("p", "hint fm-loading", "Loading…")); }
  function failed(box, e) {
    box.replaceChildren(el("p", "fm-empty", String(e || "The forum isn't reachable right now.")));
    const again = el("button", "btn small", "TRY AGAIN"); again.type = "button"; again.onclick = () => render();
    box.append(again);
  }

  function threadRow(t, showCat) {
    const b = el("button", "fm-row"); b.type = "button";
    const left = el("span", "fm-row-t");
    const title = el("b");
    if (t.pinned) title.append(el("span", "fm-tag", "Pinned"));
    if (t.locked) title.append(el("span", "fm-tag lock", "Locked"));
    title.append(document.createTextNode(String(t.title || "")));
    left.append(title, el("small", "", `by ${t.author || "Someone"}${showCat ? " in " + catName(t.cat) : ""} · ${ago(t.created)}`));
    b.append(left, el("span", "fm-row-n", `${replies(t.replies)} · active ${ago(t.bumped)}`));
    b.onclick = () => go({ kind: "thread", id: t.id, cat: t.cat });
    return b;
  }
  function list(threads, showCat, empty) {
    if (!threads.length) return el("p", "fm-empty", empty);
    const ul = el("ul", "fm-list");
    for (const t of threads) { const li = el("li"); li.append(threadRow(t, showCat)); ul.append(li); }
    return ul;
  }
  function box(title, ...kids) {
    const s = el("section", "fm-box");
    if (title) s.append(el("h3", "", title));
    s.append(...kids);
    return s;
  }
  function crumb(...parts) {
    const n = el("nav", "fm-crumb"); n.setAttribute("aria-label", "Where you are");
    parts.forEach(([label, to], i) => {
      if (i) n.append(document.createTextNode(" / "));
      if (to) { const b = el("button", "link-s", label); b.type = "button"; b.onclick = () => go(to); n.append(b); }
      else n.append(el("span", "", label));
    });
    return n;
  }
  // a post: plain text, its links as buttons (forum.rs opens only links the forum sent)
  function postText(p) {
    const d = el("p", "fm-text");
    for (const part of p.parts || [{ t: p.text || "" }]) {
      if (part.u) {
        const a = el("button", "fm-link", part.u.length > 70 ? part.u.slice(0, 60) + "…" + part.u.slice(-8) : part.u);
        a.type = "button"; a.title = part.u;
        a.onclick = () => open("link", part.u);
        d.append(a);
      } else d.append(document.createTextNode(part.t || ""));
    }
    return d;
  }

  async function render() {
    const out = $("fm-view");
    if (!out) return;
    const mine = ++seq;
    const stale = () => mine !== seq;
    loading(out);
    try {
      if (!cats.length || view.kind === "home") {
        const r = await call("categories");
        cats = Array.isArray(r && r.categories) ? r.categories : [];
      }
      if (stale()) return;
      if (view.kind === "home") {
        const r = await call("latest", { n: 10 });
        if (stale()) return;
        const cl = el("ul", "fm-list fm-cats");
        for (const c of cats) {
          const b = el("button", "fm-row"); b.type = "button";
          const t = el("span", "fm-row-t");
          t.append(el("b", "", c.name), el("small", "", c.line || ""));
          if (c.last) t.append(el("small", "fm-last", "Latest: " + c.last.title));
          b.append(t, el("span", "fm-row-n", `${c.threads} thread${c.threads === 1 ? "" : "s"}`));
          b.onclick = () => go({ kind: "cat", cat: c.id, page: 1 });
          const li = el("li"); li.append(b); cl.append(li);
        }
        const two = el("div", "fm-two");
        two.append(box("Categories", cl), box("Latest threads", list(r.threads || [], true, "No threads yet. Start the first one.")));
        out.replaceChildren(two);
      } else if (view.kind === "cat") {
        const r = await call("threads", { cat: view.cat, page: view.page || 1 });
        if (stale()) return;
        const c = cats.find((x) => x.id === view.cat) || {};
        const head = el("div", "fm-head");
        const t = el("div"); t.append(crumb(["Forum", { kind: "home" }]), el("h3", "fm-title", c.name || r.name || "Forum"), el("p", "hint", c.line || ""));
        const nb = el("button", "btn small", c.staff_only ? "THE TEAM POSTS HERE" : "NEW THREAD HERE"); nb.type = "button";
        nb.disabled = !!c.staff_only;
        nb.onclick = () => open("new", view.cat);
        head.append(t, nb);
        const pager = el("div", "fm-pager");
        if ((view.page || 1) > 1) { const p = el("button", "link-s", "‹ Newer"); p.type = "button"; p.onclick = () => go({ ...view, page: view.page - 1 }); pager.append(p); }
        if (r.more) { const n = el("button", "link-s", "Older ›"); n.type = "button"; n.onclick = () => go({ ...view, page: (view.page || 1) + 1 }); pager.append(n); }
        out.replaceChildren(head, box("", list(r.threads || [], false, "No threads here yet. Start the first one.")), pager);
      } else if (view.kind === "thread") {
        const r = await call("thread", { id: view.id, page: view.page || 1 });
        if (stale()) return;
        const th = r.thread || {};
        const head = el("div", "fm-head");
        const t = el("div");
        const title = el("h3", "fm-title");
        if (th.pinned) title.append(el("span", "fm-tag", "Pinned"));
        if (th.locked) title.append(el("span", "fm-tag lock", "Locked"));
        title.append(document.createTextNode(String(th.title || "")));
        t.append(crumb(["Forum", { kind: "home" }], [catName(th.cat), { kind: "cat", cat: th.cat, page: 1 }]), title);
        const acts = el("div", "fm-acts");
        const rp = el("button", "btn small primary", th.locked ? "LOCKED" : "REPLY"); rp.type = "button";
        rp.disabled = !!th.locked;
        rp.title = "Opens the reply page on the website, in your browser";
        rp.onclick = () => open("reply", th.id);
        const web = el("button", "btn small", "ON THE WEBSITE"); web.type = "button";
        web.onclick = () => open("thread", th.id);
        acts.append(rp, web);
        head.append(t, acts);
        const posts = el("div", "fm-posts");
        for (const p of r.posts || []) {
          const a = el("article", "fm-post");
          if (p.hidden) { a.append(el("p", "fm-gone", "This post was removed by a moderator.")); posts.append(a); continue; }
          const by = el("p", "fm-by");
          const av = el("span", "sx-av fm-av"); let h = 0; for (const ch of String(p.author)) h = (h * 31 + ch.codePointAt(0)) >>> 0;
          av.style.setProperty("--h", h % 360); av.append(el("b", "", (String(p.author).match(/[A-Za-z0-9]/) || ["?"])[0].toUpperCase()));
          by.append(av, el("b", "", String(p.author || "Someone")));
          if (p.tag) by.append(el("small", "", "#" + p.tag));
          if (p.staff) by.append(el("span", "fm-team", "Team"));
          by.append(el("span", "fm-when", ago(p.at)));
          a.append(by, postText(p));
          posts.append(a);
        }
        const pager = el("div", "fm-pager");
        if ((view.page || 1) > 1) { const p = el("button", "link-s", "‹ Earlier"); p.type = "button"; p.onclick = () => go({ ...view, page: view.page - 1 }); pager.append(p); }
        if (r.more) { const n = el("button", "link-s", "Later ›"); n.type = "button"; n.onclick = () => go({ ...view, page: (view.page || 1) + 1 }); pager.append(n); }
        out.replaceChildren(head, box("", posts), pager);
      } else if (view.kind === "search") {
        const r = await call("search", { q: view.q });
        if (stale()) return;
        out.replaceChildren(crumb(["Forum", { kind: "home" }], [`Titles with “${view.q}”`]),
          box("", list(r.threads || [], true, "No thread titles match.")));
      }
      say("");
    } catch (e) {
      if (!stale()) failed(out, e);
    }
  }

  function go(v) { view = v; render(); const m = document.querySelector("main"); if (m) m.scrollTop = 0; }

  // the page's own controls (index.html #page-forum)
  const form = $("fm-search");
  if (form) form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("fm-q").value.trim();
    if (q.length >= 2) go({ kind: "search", q: q.slice(0, 60) }); else say("Type at least two letters.", "warn");
  });
  if ($("fm-new")) $("fm-new").addEventListener("click", () => open("new", view.kind === "cat" ? view.cat : undefined));
  if ($("fm-discord")) $("fm-discord").addEventListener("click", () => invoke("open_link", { name: "discord" }).catch((e) => say(String(e), "bad")));

  window.LeylineForum = {
    load: () => render(),
    home: () => go({ kind: "home" }),
    openThread: (id) => {
      view = { kind: "thread", id };
      if (window.LeylineNav) window.LeylineNav.show("forum", true);
      render();
    },
    view: () => view,
  };
})();
