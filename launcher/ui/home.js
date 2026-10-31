// Leyline Launcher: Home's hero gallery and the rows below the fold. Loaded last: it reads the data app.js and
// modes.js already load (window.LeylineApp, window.LeylineModes) and makes no calls of its own, apart from asking
// modes.js for its list once (the same modes_list the Modes page makes). Every page jump goes through
// window.LeylineNav.show(page, noLoad, tab). Everything from a catalog or the realm list is shown with textContent.
//
// The gallery: one slide per highlight (the featured mode, what's new, browser play, hosting, a Workshop mod), each a
// big title, one short line and one button; a slide without its data is left out. It moves on every 7 s, stops while
// the pointer is over it or something in it has focus, and never moves by itself under prefers-reduced-motion.
// Dots, the arrows, and Left / Right while it has focus. The rows: Popular realms, Mods to try, Game modes, News and
// a Host your own banner; a row shows once its data is in and hides when there is nothing to show.
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
  // what each slide needs, or null to leave it out
  function slideDefs() {
    const out = [];
    const M = Modes();
    // (a) the featured mode with its key art
    if (M && M.ART[M.FEATURED] && !artFailed) {
      const a = M.ART[M.FEATURED];
      const m = modeData(M.FEATURED);
      out.push({ key: "mode", kicker: m && m.status === "coming" ? "Featured mode · Coming soon" : "Featured mode",
        title: a.title, line: firstSentence(m ? m.line : "") || "A survivors-style roguelike.",
        cta: "See the mode", art: "mode", run: () => M.show(M.FEATURED) });
    }
    // (b) what's new: the newest entry
    const n = App.news()[0];
    if (n) out.push({ key: "news", kicker: "What's new", title: n.title, line: n.items[0] || "", cta: "Read the patch notes", run: () => go("news") });
    // (c) browser play (left out when it is already on)
    if (App.mode() !== "browser") {
      out.push({ key: "browser", kicker: "Nothing to install", title: "Play in your browser", line: "Your game folder, straight in a browser tab.",
        cta: "Use browser play", run: (b) => { App.setMode("browser"); b.textContent = "Browser play is on"; b.disabled = true; } });
    }
    // (d) hosting
    out.push({ key: "host", kicker: "Host", title: "Host an always-on realm", line: "Vanilla+ or your own rules, on the Leyline network.",
      cta: "Start hosting", run: () => go("host") });
    // (e) a Workshop mod: the first packaged one
    const p = App.catalog().projects.find((x) => x.source === "packaged");
    if (p) out.push({ key: "mod", kicker: "Workshop spotlight", title: p.name, line: firstSentence(p.description) || "A mod from the Workshop.",
      cta: "See it in Discover", run: () => go("mods", "discover") });
    return out;
  }
  let artFailed = false;

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
      s.classList.add("has-art");
      s.append(img);
    } else {
      s.append(el("span", "hs-deco"));
    }
    const body = el("div", "hs-body");
    const b = el("button", "btn primary hs-go", d.cta);
    b.type = "button";
    b.addEventListener("click", () => d.run(b));
    body.append(el("small", "hs-kick", d.kicker), el("h2", "hs-title", d.title));
    if (d.line) body.append(el("p", "hs-line", d.line));
    body.append(b);
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
    hero.classList.toggle("on-art", slides[index].node.classList.contains("has-art"));   // the dots go dark over key art
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
  document.addEventListener("leyline:realms", renderRealms);
  document.addEventListener("leyline:catalog", () => { build(); renderMods(); });
  document.addEventListener("leyline:modes", () => { build(); renderModes(); });
  build();
  renderRealms();
  renderMods();
  renderModes();
  renderNewsRow();
  if (Modes()) Modes().ensure();

  window.LeylineHome = { slides: () => slides.map((s) => s.key), index: () => index, show, build, autoOn, AUTO_MS };
})();
