// Leyline Launcher: Home's hero gallery and the rows below the fold. Loaded last: it reads the data app.js and
// modes.js already load (window.LeylineApp, window.LeylineModes) and makes two reads of its own: the latest three forum
// threads (forum_call "latest", the Forum page's own read) for the launch slide, at most once a minute while Home is
// shown, and the site's list of Home screenshots (/wrath/art/home/home.json, the one address the window's CSP lets it read). Every page jump goes through window.LeylineNav.show(page, noLoad, tab). Everything from a catalog, the realm
// list, the forum or home.json is shown with textContent; nothing here is set as HTML.
//
// The gallery: first, the launch slide (Join the official realm, App.HANGOUT: Play now and Join the Discord, with the official
// lineup, what's on and the latest forum threads beside it); then one slide per highlight (the featured mode, what's
// new, browser play with the realms on the network, hosting, your Den, a Workshop mod with its screenshots), each a big
// title, one short line, a row of live counts and one button, over the owner's in-game screenshot (fetched from the
// site, a plain gradient until it is in or when there is none) and beside a glass panel; a slide
// without its data is left out. It moves on every 7 s, stops while the pointer is over it or something in it has
// focus, and never moves by itself under prefers-reduced-motion. Dots, the arrows, and
// Left / Right while it has focus. The rows: Popular realms, Mods to try, Game modes, News and a Host your own banner;
// a row shows once its data is in and hides when there is nothing to show.
//
// No game screenshots or game art ship with the launcher (owner rule): the screenshots are the site's, read at runtime;
// the Workshop's are creator uploads the site serves; the featured mode's key art is the launcher's own.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const App = window.LeylineApp;
  const hero = $("hero");
  if (!App || !hero) return;
  const Modes = () => window.LeylineModes || null;
  const go = (page, tab) => window.LeylineNav.show(page, false, tab);
  const firstSentence = (s) => String(s || "").trim().split(/(?<=[.!?])\s+/)[0];
  const AUTO_MS = Number(window.LEYLINE_HERO_MS) || 7000;   // a test may shorten it
  const SITE_ORIGIN = "https://play.openvanilla.app";   // the only place pictures come from (the window's CSP agrees)
  const reduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };

  // ---------------------------------------------------------------- the slides
  const slidesBox = $("hero-slides");
  const dotsBox = $("hero-dots");
  let slides = [];        // [{ key, node, title }]
  let index = 0;

  function modeData(id) {
    const M = Modes();
    return M ? M.modes().find((m) => m.id === id) || null : null;
  }
  // the realms worth counting (a build the launcher does not offer is left out, as on Realms)
  const listed = () => App.realms().filter((r) => !App.hiddenBuild(r.build));
  const liveRealms = () => listed().filter((r) => r.state === "live");
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

  // what each slide needs, or null to leave it out
  function slideDefs() {
    const out = [];
    const M = Modes();
    // (0) launch (owner 2026-10-30): the official realm (App.HANGOUT), where everyone meets in Dalaran, is the front door.
    // Play now selects it and presses PLAY (browser play when there is no 3.3.5a client); Join the Discord is the core's
    // named link. TODO(owner): the kicker and the line, his words.
    if (App.playHangout) {
      out.push({ key: "hangout", kicker: "Open now · " + App.HANGOUT.kind, title: "Join " + App.HANGOUT.name,
        line: "Everyone meets in Dalaran. Say hello, then try /golf and /modes.",
        chips: hangoutChips, photo: true, side: hangoutSide, cta: "Play now", run: () => App.playHangout(),
        cta2: "Join the Discord", run2: () => App.openLink("discord") });
    }
    // (a) the featured mode with its key art
    if (M && M.ART[M.FEATURED] && !artFailed) {
      const a = M.ART[M.FEATURED];
      const m = modeData(M.FEATURED);
      out.push({ key: "mode", kicker: m && m.status === "coming" ? "Featured mode · Coming soon" : "Featured mode",
        title: a.title, line: firstSentence(m ? m.line : "") || "A survivors-style roguelike.",
        cta: "See the mode", art: "mode", run: () => M.show(M.FEATURED) });
    }
    // (b) what's new: the newest entry, its points beside it
    const n = App.news()[0];
    if (n) out.push({ key: "news", kicker: "What's new", title: n.title, line: "",   // its points are in the panel beside it
      photo: true, side: newsSide, cta: "Read the patch notes", run: () => go("news") });
    // (c) browser play (left out when it is already on), with the realms on the network beside it
    if (App.mode() !== "browser") {
      out.push({ key: "browser", kicker: "Nothing to install", title: "Play in your browser", line: "Your game folder, straight in a browser tab.",
        chips: networkChips, photo: true, side: realmsPanel, cta: "Use browser play",
        run: (b) => { App.setMode("browser"); b.textContent = "Browser play is on"; b.disabled = true; } });
    }
    // (d) hosting
    out.push({ key: "host", kicker: "Host", title: "Host an always-on realm", line: "Vanilla+ or your own rules, on the Leyline network.",
      chips: hostChips, photo: true, side: hostSteps, cta: "Start hosting", run: () => go("host") });
    // (e) your Den (docs/DEN.md): the Host page with Make my Den picked, as the play bar's My Den does when there is none
    // TODO(owner): the Den slide's kicker, title, line and chips, his words.
    out.push({ key: "den", kicker: "Your own room", title: "Make your Den", line: "A plain white room on your PC. Build it up in edit mode, then invite your friends.",
      chips: () => [{ t: "Private, invite only" }, { t: "Up to 10 friends" }, { t: "Hundreds of props" }],
      photo: true, side: denSteps, cta: "Make my Den", run: makeDen });
    // (f) a Workshop mod: the first packaged one, its screenshot in front of three more
    const cat = App.catalog();
    const p = cat.projects.find((x) => x.source === "packaged");
    if (p) out.push({ key: "mod", kicker: "Workshop spotlight", title: p.name, line: firstSentence(p.description) || "A mod from the Workshop.",
      chips: modChips, ill: () => shotStack(p), side: () => moreMods(p), cta: "See it in Discover", run: () => go("mods", "discover") });
    return out;
  }
  let artFailed = false;
  function makeDen() {
    go("host");
    document.dispatchEvent(new CustomEvent("leyline:host-ruleset", { detail: { profile: "den" } }));
  }

  // ---- live chips above the kicker: counts from the realm list and the Workshop (a reserved row, so nothing moves)
  function hangoutChips() {
    const hang = App.realms().find((r) => r.official);
    const live = liveRealms();
    const out = [];
    if (hang && hang.state === "live" && hang.players != null) out.push({ t: `${hang.players} on ${App.HANGOUT.name} now`, live: true });
    if (live.length) out.push({ t: `${sum(live)} playing on ${plural(live.length, "realm")}` });
    return out;
  }
  const sum = (list) => list.reduce((a, r) => a + (Number(r.players) || 0), 0);
  function networkChips() {
    const live = liveRealms();
    return live.length ? [{ t: `${sum(live)} playing now`, live: true }, { t: plural(live.length, "realm") + " live" }] : [];
  }
  function hostChips() {
    const community = liveRealms().filter((r) => !r.official);
    const fresh = listed().filter((r) => r.is_new && !r.official).length;
    const out = [];
    if (community.length) out.push({ t: plural(community.length, "community realm") + " live", live: true });
    if (fresh) out.push({ t: `${fresh} new on the list` });
    out.push({ t: "No ports to open" });
    return out;
  }
  function modChips() {
    const cat = App.catalog();
    const n = cat.projects.filter((x) => x.source === "packaged").length;
    const out = [{ t: `${n} ready to install` }];
    if (cat.categories.length) out.push({ t: plural(cat.categories.length, "category", "categories") });
    return out;
  }
  function chipRow(list) {
    const row = el("div", "hs-chips");
    for (const c of list || []) row.append(el("span", "hs-chip" + (c.live ? " live" : ""), c.t));
    return row;
  }

  // ---- the owner's in-game screenshots, hosted on the site and fetched while Leyline runs (owner 2026-10-30: "in game
  // screenshots in those panes"; nothing game-made ships with the launcher). The site's home.json says which files there
  // are, per slide id (tools/site-art/publish_home_art.py writes it): { "slides": { "hangout": [{ "file", "alt", "credit" }] } }.
  // Only that folder, only plain file names; alt and credit are shown as text. With no manifest, or a picture that fails,
  // the slide keeps its plain gradient. Several files for a slide take turns, one a day.
  const HOME_ART = SITE_ORIGIN + "/wrath/art/home/";
  let homeArt = null;      // null: not read (yet, or it failed); else { id: [{ url, alt, credit }] }
  const ART_FILE = /^[a-z0-9][a-z0-9-]{0,40}\.(?:webp|jpg)$/;
  const clip = (v, n) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim().slice(0, n) : "");
  function readHomeArt(j) {
    const out = {};
    const all = j && typeof j === "object" && j.slides && typeof j.slides === "object" ? j.slides : {};
    for (const id of Object.keys(all)) {
      if (!/^[a-z0-9][a-z0-9-]{0,40}$/.test(id)) continue;
      const list = (Array.isArray(all[id]) ? all[id] : [all[id]]).filter((x) => x && typeof x === "object" && ART_FILE.test(String(x.file || "")));
      if (list.length) out[id] = list.slice(0, 12).map((x) => ({ url: HOME_ART + x.file, alt: clip(x.alt, 200), credit: clip(x.credit, 120) }));
    }
    return out;
  }
  function artFor(id) {
    const list = homeArt && homeArt[id];
    return list && list.length ? list[Math.floor(Date.now() / 86400000) % list.length] : null;
  }
  async function loadHomeArt() {
    try {
      const r = await fetch(HOME_ART + "home.json", { credentials: "omit", referrerPolicy: "no-referrer" });
      if (!r.ok) return;
      homeArt = readHomeArt(await r.json());
    } catch (_) { return; }
    build();
  }
  // a screenshot that fills the slide, under a scrim; the words turn light once it is in
  function photo(s, id) {
    const a = artFor(id);
    if (!a) return;
    const img = el("img", "hs-photo");
    img.alt = a.alt;
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.draggable = false;
    img.addEventListener("load", () => {
      if (img.naturalWidth < 2) { img.remove(); return; }
      s.classList.add("has-photo");
      if (slides[index] && slides[index].node === s) hero.classList.add("on-art");
    });
    img.addEventListener("error", () => { img.remove(); s.classList.remove("has-photo"); if (slides[index] && slides[index].node === s) hero.classList.remove("on-art"); });
    img.src = a.url;
    s.append(img);
    if (a.credit) s.append(el("small", "hs-credit", a.credit));
  }

  // the Den slide's right side: three steps, as the host slide's
  function denSteps() {
    // TODO(owner): the three step names
    return stepsCard("Your Den in three steps", [["A white room", "Yours, on this PC"], ["Edit mode", "Place, move and stack props"],
      ["Invite friends", "Send them the Den's link"]]);
  }

  const SLASH = { minigolf: "/golf" };   // the rest start from /modes (the Hangout's line); TODO(owner): each mode's own command

  // a mode tile's picture: its screenshot from the site (home.json "mode-<id>"), else its colour and initial
  function modePic(m) {
    const pic = el("span", "hs-mt-pic");
    pic.setAttribute("aria-hidden", "true");
    pic.style.setProperty("--h", String(App.nameHue(m.title)));
    pic.append(el("b", "", ([...String(m.title).trim()][0] || "?").toUpperCase()));
    const a = artFor("mode-" + m.id);
    if (a) {
      const img = el("img");
      img.alt = "";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", () => img.remove());
      img.src = a.url;
      pic.append(img);
    }
    return pic;
  }

  // the launch slide's right side: the official lineup, what's on (three modes), the latest forum threads
  function hangoutSide() {
    const box = el("div", "hs-side hs-stack");
    box.append(lineupPanel());
    const M = Modes();
    const on = M ? M.modes().filter((m) => m.status === "live" && m.kind === "realm").slice(0, 3) : [];
    if (on.length) {
      const card = el("div", "hs-glass hs-whats");
      card.append(sideHead("What's on in " + App.HANGOUT.name));
      const row = el("div", "hs-mt-row");
      for (const m of on) {
        const b = el("button", "hs-mt");
        b.type = "button";
        b.dataset.mode = m.id;
        b.title = `${m.title}: open Modes`;
        b.addEventListener("click", () => M.show(m.id));
        b.append(modePic(m), el("b", "", m.title), el("i", "", SLASH[m.id] || "/modes"));
        row.append(b);
      }
      card.append(row);
      box.append(card);
    }
    const fm = el("div", "hs-glass hs-forum-card");
    const all = el("button", "hs-side-a", "Forum");
    all.type = "button";
    all.addEventListener("click", () => go("forum"));
    fm.append(sideHead("Latest on the forum", all), el("ul", "hs-forum"));
    fillForum(fm.lastChild);
    box.append(fm);
    return box;
  }
  function sideHead(text, extra) {
    const h = el("div", "hs-side-h");
    h.append(el("span", "", text));
    if (extra) h.append(extra);
    return h;
  }

  // the latest forum threads (forum_call "latest", as the Forum page reads them): titles and names as text only
  let forum = null;        // null: not asked yet; [] none or unreachable; else up to three threads
  let forumAt = 0;
  function ago(t) {
    const d = Math.max(0, Math.floor(Date.now() / 1000) - (Number(t) || 0));
    for (const [n, w] of [[86400 * 7, "w"], [86400, "d"], [3600, "h"], [60, "m"]]) if (d >= n) return `${Math.floor(d / n)}${w} ago`;
    return "just now";
  }
  function fillForum(ul) {
    if (forum === null) {   // placeholders the size of a thread, so nothing moves when they come in
      ul.replaceChildren(...[0, 1, 2].map(() => { const li = el("li", "hs-fr-wait"); li.append(el("span"), el("span")); return li; }));
      return;
    }
    if (!forum.length) {
      const li = el("li", "hs-fr-none");
      const b = el("button", "hs-fr", "");
      b.type = "button";
      b.append(el("b", "", "Say hello on the forum"), el("i", "", "Ideas, Den tours, game nights"));   // TODO(owner): his words
      b.addEventListener("click", () => go("forum"));
      li.append(b);
      ul.replaceChildren(li);
      return;
    }
    ul.replaceChildren(...forum.map((t) => {
      const li = el("li");
      const b = el("button", "hs-fr");
      b.type = "button";
      b.title = String(t.title || "");
      b.append(el("b", "", String(t.title || "")),
        el("i", "", `${String(t.author || "Someone")} · ${plural(Number(t.replies) || 0, "reply", "replies")} · ${ago(t.bumped || t.created)}`));
      b.addEventListener("click", () => {
        if (window.LeylineForum && t.id != null) window.LeylineForum.openThread(t.id); else go("forum");
      });
      li.append(b);
      return li;
    }));
  }
  async function loadForum() {
    const tauri = window.__TAURI__ && window.__TAURI__.core ? window.__TAURI__.core.invoke : null;
    if (!tauri || Date.now() - forumAt < 60000) return;
    forumAt = Date.now();
    let list = [];
    try {
      const r = await tauri("forum_call", { action: "latest", args: { n: 3 } });
      list = r && Array.isArray(r.threads) ? r.threads.filter((t) => t && typeof t === "object").slice(0, 3) : [];
    } catch (_) { list = []; }
    forum = list;
    slidesBox.querySelectorAll(".hs-forum").forEach(fillForum);
  }

  // the browser slide's right side (owner 2026-10-30: "list many example servers in this pane"): the realms on the
  // network now, live ones first, up to seven; each with its kind, version, players and how full it is; a row opens Realms
  const fillPct = (players, max) => (!players ? 0 : Math.max(6, Math.min(100, Math.round((100 * players) / (max > 0 ? max : 100)))));
  function realmsPanel() {
    const all = listed();
    if (!all.length) return null;
    const rank = (r) => (r.official ? 0 : r.state === "live" ? 1 : 2);
    const list = all.slice().sort((a, b) => rank(a) - rank(b) || (b.players || 0) - (a.players || 0)).slice(0, 7);
    const box = el("div", "hs-side hs-realms hs-rich");
    box.append(sideHead("On the network", el("span", "hs-side-n", plural(all.length, "realm"))));
    for (const r of list) {
      const live = r.state === "live" || r.official;
      const row = el("button", "hs-rl" + (live ? " live" : ""));
      row.type = "button";
      row.title = `${r.name}: open Realms`;
      row.addEventListener("click", () => go("realms"));
      const name = el("span", "hs-rl-n");
      const sub = el("i", "", r.official ? "Run by Leyline" : live ? r.kind || "Community realm" : "Offline for now");
      name.append(el("b", "", r.name), sub);
      if (r.is_new && !r.official) sub.append(el("span", "hs-new", "New"));
      const meta = el("span", "hs-rl-m");
      const ver = App.realmVersion(r);
      if (ver) meta.append(el("span", "rl-ver sm", ver));
      meta.append(el("span", "hs-rl-p", live && r.players != null ? `${r.players}` : "–"));
      const bar = el("span", "hs-rl-bar");
      bar.setAttribute("aria-hidden", "true");
      bar.append(el("i"));
      bar.firstChild.style.width = (live ? fillPct(r.players, r.max_players) : 0) + "%";
      row.append(App.realmIcon(r.name, r.official), name, meta, bar);
      box.append(row);
    }
    return box;
  }

  // the official lineup, the Hangout first, then Vanilla Remastered when the network lists it; a row opens Realms
  function lineupPanel() {
    const all = App.realms();
    const hang = all.find((r) => r.official) || { official: true, name: App.HANGOUT.name, state: "live", players: null };
    const rest = all.filter((r) => !r.official && (r.pinned || /^vanilla remastered$/i.test(String(r.name || "").trim())));
    const box = el("div", "hs-glass hs-realms hs-lineup");
    box.append(sideHead("The official lineup"));
    for (const r of [hang, ...rest.slice(0, 3)]) {
      const live = r.state === "live";
      const row = el("button", "hs-rl" + (live ? " live" : ""));
      row.type = "button";
      row.title = `${r.name}: open Realms`;
      row.addEventListener("click", () => go("realms"));
      const name = el("span", "hs-rl-n");
      name.append(el("b", "", r.name), el("i", "", r.official ? App.HANGOUT.kind : (live ? "Bring your own client" : "Offline for now")));
      const meta = el("span", "hs-rl-m");
      const ver = r.official ? "3.3.5a" : App.realmVersion(r);
      if (ver) meta.append(el("span", "rl-ver sm", ver));
      meta.append(el("span", "hs-rl-p", live && r.players != null ? `${r.players}` : "–"));
      row.append(App.realmIcon(r.name, r.official), name, meta);
      box.append(row);
    }
    return box;
  }

  // what's new, beside the title: every point of the newest entry, then the two before it
  function newsSide() {
    const list = App.news();
    const n = list[0];
    const box = el("div", "hs-side hs-glass hs-notes");
    box.append(sideHead("In this update"));
    const ul = el("ul", "hs-ticks");
    for (const it of n.items.slice(0, 5)) ul.append(el("li", "", it));
    box.append(ul);
    const older = list.slice(1, 3);
    if (older.length) {
      box.append(sideHead("Earlier"));
      for (const o of older) {
        const b = el("button", "hs-fr hs-older");
        b.type = "button";
        b.append(el("b", "", o.title), el("i", "", o.items[0] || ""));
        b.addEventListener("click", () => go("news"));
        box.append(b);
      }
    }
    return box;
  }

  // the host slide's right side (owner 2026-10-30: "make this a small infographic for setup guide"): four steps
  function hostSteps() {
    return stepsCard("Set up in four steps", [["Pick a ruleset", "Vanilla+, Dalaran hangout, a Den or your own"],
      ["Press Start", "The host pack runs it on this PC"], ["Listed in a minute", "The relay: no ports, your address hidden"],
      ["Invite friends", "Share the link, or go public"]]);
  }
  function stepsCard(title, steps) {
    const box = el("div", "hs-side hs-steps");
    box.append(el("div", "hs-side-h", title));
    const ol = el("ol", "hs-st");
    steps.forEach(([t, l], i) => {
      const li = el("li", "");
      li.append(el("span", "hs-st-n", String(i + 1)));
      const tx = el("span", "hs-st-t");
      tx.append(el("b", "", t), el("i", "", l));
      li.append(tx);
      ol.append(li);
    });
    box.append(ol);
    return box;
  }

  // the Workshop slide's right side: the spotlight mod's screenshot in front of three more mods' (creator uploads the
  // site serves; the same rules as Discover's cards), a tile drawn from the name while one loads or when there is none
  const SITE = SITE_ORIGIN;
  function siteImage(u) {
    if (typeof u !== "string" || !u) return "";
    if (/^\/wrath\/[A-Za-z0-9._~\/-]+$/.test(u) && !u.includes("..")) return SITE + u;
    if (u.startsWith(SITE + "/") && /^[A-Za-z0-9._~\/:-]+$/.test(u) && !u.includes("..")) return u;
    return "";
  }
  function thumbUrl(p) {
    const first = (v) => (Array.isArray(v) ? v[0] : v);
    for (const v of [p.thumb, p.thumbnail, p.preview, first(p.screenshots), first(p.images), p.icon]) {
      const u = siteImage(typeof v === "object" && v ? v.url : v);
      if (u) return u;
    }
    const mid = String(p.id || "").startsWith("mod:") ? p.id.slice(4) : "";
    if (p.source === "packaged" && /^[a-z0-9-]+$/.test(mid)) return `${SITE}/wrath/mods/${mid}/shot/0`;
    const gh = /^https:\/\/github\.com\/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\/([A-Za-z0-9][A-Za-z0-9._-]{0,99}?)(?:\.git)?\/?$/.exec(p.repo || "");
    if (gh) return `${SITE}/wrath/art/hub-thumbs/${gh[1].toLowerCase()}__${gh[2].toLowerCase()}.webp`;
    return "";
  }
  function shot(p, cls) {
    const f = el("figure", "hs-shot " + cls);
    const tile = el("span", "hs-shot-tile", ([...String(p.name || "?").trim()][0] || "?").toUpperCase());
    const h = App.nameHue(p.name || p.id);
    tile.style.setProperty("--h1", String(h));
    tile.style.setProperty("--h2", String((h + 48) % 360));
    tile.setAttribute("aria-hidden", "true");
    f.append(tile);
    const u = thumbUrl(p);
    if (u) {
      const img = el("img");
      img.alt = "";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      img.width = 480;
      img.height = 270;
      img.addEventListener("load", () => { if (img.naturalWidth > 1) f.classList.add("has-img"); else img.remove(); });
      img.addEventListener("error", () => { img.remove(); f.classList.remove("has-img"); });
      img.src = u;
      f.append(img);
    }
    return f;
  }
  const othersOf = (p) => {
    const cat = App.catalog();
    return cat.projects.filter((x) => x !== p && x.source === "packaged").concat(cat.projects.filter((x) => x !== p && x.source !== "packaged"));
  };
  const catName = (p) => { const k = App.catalog().categories.find((x) => x.id === p.category); return k ? k.name : ""; };
  function shotStack(p) {
    const box = el("div", "hs-ill hs-ill-shots");
    box.setAttribute("aria-hidden", "true");
    othersOf(p).slice(0, 3).forEach((o, i) => box.append(shot(o, "back b" + (i + 1))));
    const front = shot(p, "front");
    const cap = el("figcaption", "hs-shot-cap");
    cap.append(el("b", "", p.name), el("i", "", [p.author ? "by " + p.author : "", catName(p)].filter(Boolean).join(" · ")));
    front.append(cap);
    box.append(front);
    return box;
  }
  // the Workshop slide's right side: more to try, each with its picture; a row opens Discover
  function moreMods(p) {
    const list = othersOf(p).slice(0, 5);
    if (!list.length) return null;
    const box = el("div", "hs-side hs-more");
    box.append(sideHead("More in the Workshop"));
    for (const o of list) {
      const row = el("button", "hs-wm");
      row.type = "button";
      row.title = `${o.name}: open Mods › Discover`;
      row.addEventListener("click", () => go("mods", "discover"));
      const tx = el("span", "hs-wm-t");
      tx.append(el("b", "", o.name), el("i", "", [catName(o) || (o.source === "packaged" ? "Workshop" : "Community link"), o.author ? "by " + o.author : ""].filter(Boolean).join(" · ")));
      row.append(shot(o, "mini"), tx);
      box.append(row);
    }
    return box;
  }

  function slideNode(d) {
    const s = el("div", "hero-slide hs-" + d.key);
    s.dataset.key = d.key;
    s.setAttribute("role", "group");
    s.setAttribute("aria-roledescription", "slide");
    if (d.art === "mode") {
      const M = Modes();
      const img = M.artImg(M.FEATURED, "hs-art");
      img.alt = "";
      img.addEventListener("error", () => { artFailed = true; build(); });
      // the key art carries the mode's own lettering: show it whole (never cropped) over a soft blur of itself
      const bg = img.cloneNode(true);
      bg.className = "hs-art-bg";
      bg.setAttribute("aria-hidden", "true");
      s.classList.add("has-art");
      s.append(bg, img);
    } else {
      if (d.photo) photo(s, d.key);
      const pic = d.ill ? d.ill() : null;
      if (pic) { s.classList.add("has-ill"); s.append(pic); }
      const side = d.side ? d.side() : null;
      if (side) { s.classList.add("has-side"); s.append(side); } else if (!pic && !d.photo) s.append(el("span", "hs-deco"));
    }
    const body = el("div", "hs-body");
    const b = el("button", "btn primary hs-go", d.cta);
    b.type = "button";
    b.addEventListener("click", () => d.run(b));
    let b2 = null;
    if (d.cta2) {
      b2 = el("button", "btn hs-go2", d.cta2);
      b2.type = "button";
      b2.addEventListener("click", () => d.run2(b2));
    }
    if (d.chips) body.append(chipRow(d.chips()));
    // over key art the picture already shows the name: the heading stays for screen readers only
    body.append(el("small", "hs-kick", d.kicker), el("h2", "hs-title" + (d.art ? " sr" : ""), d.title));
    if (d.line) body.append(el("p", "hs-line", d.line));
    if (b2) { const row = el("div", "hs-acts"); row.append(b, b2); body.append(row); } else body.append(b);
    s.append(body);
    return s;
  }

  function build() {
    const keep = slides[index] ? slides[index].key : null;
    const defs = slideDefs();
    slides = defs.map((d) => ({ key: d.key, title: d.title, node: slideNode(d) }));
    slidesBox.replaceChildren(...slides.map((s) => s.node));
    dotsBox.replaceChildren(...slides.map((s, i) => {
      const b = el("button", "hero-dot");
      b.type = "button";
      b.dataset.i = String(i);
      b.setAttribute("aria-label", `Slide ${i + 1} of ${slides.length}: ${s.title}`);
      b.addEventListener("click", () => { show(i); });
      return b;
    }));
    $("hero-ctl").hidden = slides.length < 2;
    const at = slides.findIndex((s) => s.key === keep);
    show(at >= 0 ? at : 0, true);
    if (!timer) restart();
  }

  function show(i, quiet) {
    if (!slides.length) return;
    index = (i + slides.length) % slides.length;
    slides.forEach((s, j) => {
      const on = j === index;
      s.node.classList.toggle("on", on);
      s.node.setAttribute("aria-label", `${j + 1} of ${slides.length}`);
      s.node.inert = !on;
      s.node.setAttribute("aria-hidden", String(!on));
    });
    hero.classList.toggle("on-art", /\bhas-(?:art|photo)\b/.test(slides[index].node.className));   // the dots go dark over key art
    dotsBox.querySelectorAll(".hero-dot").forEach((b, j) => {
      if (j === index) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    if (!quiet) restart();
  }
  $("hero-prev").addEventListener("click", () => show(index - 1));
  $("hero-next").addEventListener("click", () => show(index + 1));
  hero.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    show(index + (e.key === "ArrowRight" ? 1 : -1));
    // keep the keyboard on the gallery: on the dot of the new slide when a dot had it, else on the gallery itself
    if (document.activeElement && document.activeElement.classList.contains("hero-dot")) dotsBox.children[index].focus();
    else if (!hero.contains(document.activeElement) || document.activeElement.inert || document.activeElement.closest("[inert]")) hero.focus();
  });
  hero.tabIndex = 0;

  // ---------------------------------------------------------------- moving on by itself
  let timer = null;
  let hovered = false;
  let focused = false;
  const onHome = () => { const p = $("page-play"); return !!p && p.classList.contains("on"); };
  const autoOn = () => !reduced.matches && slides.length > 1;
  const paused = () => hovered || focused || document.hidden || !onHome();
  function restart() {
    clearTimeout(timer);
    timer = null;
    hero.classList.toggle("is-auto", autoOn());
    if (!autoOn() || paused()) return;
    timer = setTimeout(() => { timer = null; show(index + 1); }, AUTO_MS);
  }
  hero.addEventListener("mouseenter", () => { hovered = true; restart(); });
  hero.addEventListener("mouseleave", () => { hovered = false; restart(); });
  hero.addEventListener("focusin", () => { focused = true; restart(); });
  hero.addEventListener("focusout", (e) => { if (!hero.contains(e.relatedTarget)) { focused = false; restart(); } });
  document.addEventListener("visibilitychange", restart);
  document.addEventListener("leyline:page", restart);
  if (reduced.addEventListener) reduced.addEventListener("change", restart);

  // ---------------------------------------------------------------- the rows below the fold
  function card(cls, onClick, title) {
    const b = el("button", "hm-card " + cls);
    b.type = "button";
    if (title) b.title = title;
    b.addEventListener("click", onClick);
    return b;
  }
  const txt = (name, line, extra) => {
    const t = el("span", "hm-txt");
    const top = el("span", "hm-name-line");
    top.append(el("b", "hm-name", name));
    if (extra) top.append(extra);
    t.append(top, el("span", "hm-line", line));
    return t;
  };
  function fill(id, nodes) {
    $(id + "-row").replaceChildren(...nodes);
    $(id).hidden = !nodes.length;
    cue();
  }

  function renderRealms() {
    const live = App.realms().filter((r) => r.state === "live" && !App.hiddenBuild(r.build)).slice(0, 4);
    fill("hm-realms", live.map((r) => {
      const c = card("hm-realm", () => go("realms"), `${r.name}: open Realms`);
      const ver = App.realmVersion(r);
      let chip = null;
      if (ver) { chip = el("span", "rl-ver sm", ver); chip.title = "Game client version"; }
      const line = r.players != null ? `${r.players} playing` : "Online";
      const t = txt(r.name, line, chip);
      t.lastChild.classList.add("hm-live");
      c.append(App.realmIcon(r.name, r.official), t);
      return c;
    }));
  }

  function renderMods() {
    const cat = App.catalog();
    const picks = cat.projects.filter((p) => p.source === "packaged").concat(cat.projects.filter((p) => p.source !== "packaged")).slice(0, 4);
    fill("hm-mods", picks.map((p) => {
      const c = card("hm-mod", () => go("mods", "discover"), `${p.name}: open Mods › Discover`);
      const k = cat.categories.find((x) => x.id === p.category);
      const ic = el("span", "hm-ic", ([...String(p.name).trim()][0] || "?").toUpperCase());
      ic.style.setProperty("--h", String(App.nameHue(p.name)));
      ic.setAttribute("aria-hidden", "true");
      c.append(ic, txt(p.name, k ? k.name : p.source === "packaged" ? "Workshop" : "Community link"));
      return c;
    }));
  }

  function renderModes() {
    const M = Modes();
    if (!M) return;
    const art = (m) => (M.ART[m.id] ? 0 : 1);
    const list = M.modes().slice().sort((a, b) => art(a) - art(b) || (a.status === "live" ? 0 : 1) - (b.status === "live" ? 0 : 1)).slice(0, 4);
    fill("hm-modes", list.map((m) => {
      const c = card("hm-mode", () => M.show(m.id), `${m.title}: open Modes`);
      c.dataset.mode = m.id;
      const pic = el("span", "hm-pic");
      pic.setAttribute("aria-hidden", "true");
      pic.style.setProperty("--h", String(App.nameHue(m.title)));
      const img = M.artImg(m.id, "");
      if (img) {
        img.alt = "";
        img.addEventListener("error", () => { img.remove(); pic.classList.remove("has-art"); });
        pic.classList.add("has-art");
        pic.append(img);
      } else {
        pic.append(el("i", "", ([...String(m.title).trim()][0] || "?").toUpperCase()));
      }
      c.append(pic, txt(m.title, m.status === "coming" ? "Coming soon" : M.KIND[m.kind] || "Game mode"));
      return c;
    }));
  }

  function renderNewsRow() {
    fill("hm-news", App.news().slice(0, 2).map((n) => {
      const c = card("hm-news", () => go("news"), "Open News");
      const t = el("span", "hm-txt");
      t.append(el("small", "hm-kick", n.tag), el("b", "hm-name", n.title), el("span", "hm-line", n.items[0] || ""));
      c.append(t);
      return c;
    }));
  }

  document.querySelectorAll("[data-hm-go]").forEach((b) => b.addEventListener("click", () => {
    const g = b.dataset.hmGo;
    if (g === "discover") go("mods", "discover"); else go(g);
  }));
  $("hm-host-start").addEventListener("click", () => go("host"));
  $("hm-host-link").addEventListener("click", () => go("host"));
  $("hm-host-docs").addEventListener("click", () => App.openLink("docs"));   // a named link in the core (lib.rs LINKS)

  // the "More below" cue: shown while the rows are there and the page has not been scrolled down yet
  const main = document.querySelector("main");
  function cue() {
    const any = [...document.querySelectorAll("#home-more .hm-sec")].some((s) => !s.hidden);
    $("home-cue").hidden = !any || (main && main.scrollTop > 40);
  }
  $("home-cue").addEventListener("click", () => {
    const more = $("home-more");
    more.scrollIntoView({ behavior: reduced.matches ? "auto" : "smooth", block: "start" });
  });
  if (main) main.addEventListener("scroll", cue, { passive: true });

  // ---------------------------------------------------------------- data in
  document.addEventListener("leyline:realms", () => { renderRealms(); build(); });
  document.addEventListener("leyline:catalog", () => { build(); renderMods(); });
  document.addEventListener("leyline:modes", () => { build(); renderModes(); });
  document.addEventListener("leyline:page", (e) => { if ((e.detail || {}).page === "play") loadForum(); });
  build();
  loadForum();
  loadHomeArt();
  renderRealms();
  renderMods();
  renderModes();
  renderNewsRow();
  if (Modes()) Modes().ensure();

  window.LeylineHome = { slides: () => slides.map((s) => s.key), index: () => index, show, build, autoOn, AUTO_MS, thumbUrl, readHomeArt, HOME_ART };
})();
