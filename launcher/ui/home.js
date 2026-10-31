// Leyline Launcher: Home's hero gallery and the rows below the fold. Loaded last: it reads the data app.js and
// modes.js already load (window.LeylineApp, window.LeylineModes) and makes one call of its own: the latest three forum
// threads (forum_call "latest", the Forum page's own read) for the launch slide, at most once a minute while Home is
// shown. Every page jump goes through window.LeylineNav.show(page, noLoad, tab). Everything from a catalog, the realm
// list or the forum is shown with textContent; the only markup set as HTML is the illustrations drawn in this file.
//
// The gallery: first, the launch slide (Join the Dalaran Hangout: Play now and Join the Discord, with the official
// lineup, what's on and the latest forum threads beside it); then one slide per highlight (the featured mode, what's
// new, browser play with the realms on the network, hosting, your Den, a Workshop mod with its screenshots), each a big
// title, one short line, a row of live counts and one button, over an original illustration or beside a panel; a slide
// without its data is left out. It moves on every 7 s, stops while the pointer is over it or something in it has
// focus, and never moves by itself under prefers-reduced-motion (nor do the illustrations). Dots, the arrows, and
// Left / Right while it has focus. The rows: Popular realms, Mods to try, Game modes, News and a Host your own banner;
// a row shows once its data is in and hides when there is nothing to show.
//
// No game screenshots or game art here (owner rule): the pictures are drawn below, the Workshop's are creator uploads
// the site serves at runtime, and the featured mode's key art is the launcher's own.
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
  // the realms worth counting (a build the launcher does not offer is left out, as on Realms)
  const listed = () => App.realms().filter((r) => !App.hiddenBuild(r.build));
  const liveRealms = () => listed().filter((r) => r.state === "live");
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;

  // what each slide needs, or null to leave it out
  function slideDefs() {
    const out = [];
    const M = Modes();
    // (0) launch (owner 2026-10-30): the Dalaran Hangout, the Wrath realm where everyone meets, is the front door.
    // Play now selects it and presses PLAY (browser play when there is no 3.3.5a client); Join the Discord is the core's
    // named link. TODO(owner): the kicker and the line, his words.
    if (App.playHangout) {
      out.push({ key: "hangout", kicker: "Open now · " + App.HANGOUT.kind, title: "Join the " + App.HANGOUT.name,
        line: "Everyone meets in Dalaran. Say hello, then try /golf and /modes.",
        chips: hangoutChips, ill: () => ill("isle", ISLE), side: hangoutSide, cta: "Play now", run: () => App.playHangout(),
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
      ill: () => ill("notes", NOTES), side: newsSide, cta: "Read the patch notes", run: () => go("news") });
    // (c) browser play (left out when it is already on), with the realms on the network beside it
    if (App.mode() !== "browser") {
      out.push({ key: "browser", kicker: "Nothing to install", title: "Play in your browser", line: "Your game folder, straight in a browser tab.",
        chips: networkChips, ill: browserWindow, side: realmsPanel, cta: "Use browser play",
        run: (b) => { App.setMode("browser"); b.textContent = "Browser play is on"; b.disabled = true; } });
    }
    // (d) hosting
    out.push({ key: "host", kicker: "Host", title: "Host an always-on realm", line: "Vanilla+ or your own rules, on the Leyline network.",
      chips: hostChips, ill: () => ill("relay", RELAY), side: hostSteps, cta: "Start hosting", run: () => go("host") });
    // (e) your Den (docs/DEN.md): the Host page with Make my Den picked, as the play bar's My Den does when there is none
    // TODO(owner): the Den slide's kicker, title, line and chips, his words.
    out.push({ key: "den", kicker: "Your own room", title: "Make your Den", line: "A plain white room on your PC. Build it up in edit mode, then invite your friends.",
      chips: () => [{ t: "Private, invite only" }, { t: "Up to 10 friends" }, { t: "Hundreds of props" }],
      side: denStage, cta: "Make my Den", run: makeDen });
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
    if (hang && hang.state === "live" && hang.players != null) out.push({ t: `${hang.players} in the Hangout now`, live: true });
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

  // ---- original illustrations (drawn here, no game art): constant markup only, never anything from the network
  function ill(kind, markup) {
    const box = el("div", "hs-ill hs-ill-" + kind);
    box.setAttribute("aria-hidden", "true");
    box.innerHTML = markup;
    return box;
  }
  const STAR = "M0-6L1.4-1.4 6 0 1.4 1.4 0 6-1.4 1.4-6 0-1.4-1.4z";
  const stars = (pts) => pts.map(([x, y, k]) => `<path class="il-star" d="${STAR}" transform="translate(${x} ${y}) scale(${k || 1})"/>`).join("");
  // a floating city of spires over ley lines: the Hangout
  const ISLE = `<svg viewBox="0 0 520 340" preserveAspectRatio="xMidYMid meet">
<defs><radialGradient id="hsi-glow" cx=".5" cy=".55" r=".5"><stop offset="0" class="s-a2" stop-opacity=".5"/><stop offset="1" class="s-a2" stop-opacity="0"/></radialGradient>
<linearGradient id="hsi-rock" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-rock1"/><stop offset="1" class="s-rock2"/></linearGradient>
<linearGradient id="hsi-wall" x1="0" y1="0" x2="1" y2="0"><stop offset="0" class="s-wall1"/><stop offset="1" class="s-wall2"/></linearGradient>
<linearGradient id="hsi-roof" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-a2"/><stop offset="1" class="s-a"/></linearGradient></defs>
<ellipse cx="260" cy="180" rx="255" ry="160" fill="url(#hsi-glow)"/>
<g class="il-ley"><path d="M-10 272C120 200 270 330 530 196"/><path d="M-10 118C150 176 330 34 530 112"/></g>
<g class="il-float">
<path fill="url(#hsi-rock)" d="M128 218Q150 254 200 270Q236 300 258 334Q282 298 322 274Q372 252 392 218Z"/>
<path fill="url(#hsi-rock)" opacity=".7" d="M180 262l14 30 10-26zM330 258l-8 34-14-24z"/>
<ellipse class="il-top" cx="260" cy="218" rx="132" ry="22"/>
<g fill="url(#hsi-wall)"><rect x="246" y="96" width="28" height="122"/><rect x="212" y="132" width="22" height="86"/><rect x="286" y="124" width="22" height="94"/>
<rect x="184" y="166" width="16" height="52"/><rect x="320" y="160" width="16" height="58"/><rect x="168" y="196" width="184" height="24" rx="3"/></g>
<g fill="url(#hsi-roof)"><path d="M240 98L260 26 280 98z"/><path d="M207 134L223 82 239 134z"/><path d="M281 126L297 72 313 126z"/><path d="M180 168L192 134 204 168z"/><path d="M316 162L328 126 340 162z"/></g>
<g class="il-win"><rect x="256" y="118" width="8" height="12" rx="4"/><rect x="256" y="148" width="8" height="12" rx="4"/><rect x="220" y="158" width="6" height="10" rx="3"/>
<rect x="294" y="148" width="6" height="10" rx="3"/><rect x="294" y="178" width="6" height="10" rx="3"/><rect x="189" y="184" width="6" height="9" rx="3"/><rect x="325" y="178" width="6" height="9" rx="3"/></g>
<g class="il-gold"><circle cx="260" cy="24" r="3.5"/><circle cx="223" cy="80" r="2.5"/><circle cx="297" cy="70" r="2.5"/></g>
<ellipse class="il-ring" cx="260" cy="112" rx="48" ry="9"/>
</g>
<g class="il-bob"><path fill="url(#hsi-roof)" d="M84 126l12 24-12 28-12-28z"/><path fill="url(#hsi-roof)" opacity=".8" d="M446 186l8 16-8 18-8-18z"/></g>
<g class="il-bob2"><path fill="url(#hsi-roof)" opacity=".9" d="M424 70l9 18-9 20-9-20z"/></g>
${stars([[52, 60], [150, 40, 0.7], [380, 40], [470, 140, 0.8], [110, 250, 0.6], [410, 280, 0.7]])}
</svg>`;
  // a stack of notes with a tick: what's new
  const NOTES = `<svg viewBox="0 0 440 300" preserveAspectRatio="xMidYMid meet">
<defs><radialGradient id="hsn-glow" cx=".5" cy=".5" r=".5"><stop offset="0" class="s-a" stop-opacity=".35"/><stop offset="1" class="s-a" stop-opacity="0"/></radialGradient></defs>
<ellipse cx="220" cy="150" rx="210" ry="140" fill="url(#hsn-glow)"/>
<g class="il-ley"><path d="M-10 240C110 180 250 290 450 200"/></g>
<g class="il-sheet" transform="rotate(-9 200 150)"><rect x="110" y="62" width="190" height="170" rx="14"/></g>
<g class="il-sheet" transform="rotate(5 240 150)"><rect x="150" y="56" width="190" height="170" rx="14"/></g>
<g class="il-float"><g class="il-sheet front"><rect x="126" y="44" width="200" height="190" rx="16"/>
<rect class="il-bar a" x="150" y="70" width="96" height="12" rx="6"/>
<g class="il-lines"><rect x="176" y="104" width="120" height="8" rx="4"/><rect x="176" y="134" width="104" height="8" rx="4"/><rect x="176" y="164" width="124" height="8" rx="4"/><rect x="176" y="194" width="84" height="8" rx="4"/></g>
<g class="il-dots"><circle cx="160" cy="108" r="6"/><circle cx="160" cy="138" r="6"/><circle cx="160" cy="168" r="6"/><circle cx="160" cy="198" r="6"/></g></g>
<g transform="translate(318 214)"><circle class="il-badge" r="30"/><path class="il-tick" d="M-13 1l8 9 18-20"/></g></g>
${stars([[80, 70], [380, 60, 0.8], [400, 250, 0.7], [60, 210, 0.6]])}
</svg>`;
  // your PC, the relay and the realm list, joined by moving dashes: hosting
  const RELAY = `<svg viewBox="0 0 520 250" preserveAspectRatio="xMidYMid meet">
<defs><linearGradient id="hsr-roof" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="s-a2"/><stop offset="1" class="s-a"/></linearGradient>
<radialGradient id="hsr-glow" cx=".5" cy=".5" r=".5"><stop offset="0" class="s-a2" stop-opacity=".45"/><stop offset="1" class="s-a2" stop-opacity="0"/></radialGradient></defs>
<g class="il-flow"><path d="M134 104H206"/><path d="M314 104H386"/></g>
<g transform="translate(80 104)"><circle class="il-node" r="52"/><rect class="il-screen" x="-26" y="-22" width="52" height="34" rx="4"/><path class="il-stroke" d="M-8 20h16M0 12v8"/>
<path class="il-tri" d="M-6-12l14 7-14 7z"/></g>
<g transform="translate(260 104)"><circle r="80" fill="url(#hsr-glow)"/><circle class="il-node" r="56"/><g class="il-bob"><path fill="url(#hsr-roof)" d="M0-40l24 38L0 44-24-2z"/><path class="il-facet" d="M0-40v84M-24-2h48"/></g></g>
<g transform="translate(440 104)"><circle class="il-node" r="52"/><circle class="il-globe" r="28"/><ellipse class="il-globe" rx="12" ry="28"/><path class="il-globe" d="M-28 0h56M-24-14h48M-24 14h48"/>
<g class="il-orbit"><circle cx="-34" cy="-22" r="5" class="d1"/><circle cx="36" cy="-16" r="4" class="d2"/><circle cx="30" cy="26" r="5" class="d3"/><circle cx="-30" cy="24" r="3.5" class="d1"/></g></g>
<g class="il-label"><text x="80" y="186">Your PC</text><text x="260" y="192">The relay</text><text x="440" y="186">The realm list</text></g>
<g class="il-sub"><text x="80" y="206">runs your realm</text><text x="260" y="212">hides your address</text><text x="440" y="206">players find you</text></g>
</svg>`;

  // the browser slide's picture: a browser window with an original night landscape in it (fixed colours: it is a screen)
  function browserWindow() {
    const box = el("div", "hs-ill hs-ill-browser");
    box.setAttribute("aria-hidden", "true");
    const win = el("div", "hs-win");
    const bar = el("div", "hs-win-bar");
    bar.append(el("i"), el("i"), el("i"), el("span", "hs-win-url", "Leyline · in a browser tab"));
    const pic = el("div", "hs-win-pic");
    pic.innerHTML = `<svg viewBox="0 0 480 250" preserveAspectRatio="xMidYMid slice">
<defs><linearGradient id="hsb-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#151a3c"/><stop offset=".62" stop-color="#4a3a8e"/><stop offset="1" stop-color="#d4886e"/></linearGradient></defs>
<rect width="480" height="250" fill="url(#hsb-sky)"/><circle cx="372" cy="66" r="26" fill="#fde9c4"/><circle cx="372" cy="66" r="40" fill="#fde9c4" opacity=".12"/>
<g fill="#fff" opacity=".8"><circle cx="40" cy="30" r="1.4"/><circle cx="120" cy="56" r="1"/><circle cx="210" cy="24" r="1.3"/><circle cx="300" cy="40" r=".9"/><circle cx="440" cy="30" r="1.2"/><circle cx="90" cy="100" r=".8"/></g>
<path fill="#2d2a62" d="M0 180L56 124 104 160 168 102 236 166 296 118 356 162 418 112 480 150V250H0z"/>
<path fill="#221f4c" d="M0 206Q84 160 164 192T324 188T480 180V250H0z"/>
<g fill="#1a1838"><rect x="122" y="132" width="16" height="50"/><path d="M118 134l12-26 12 26z"/></g><rect x="127" y="146" width="5" height="8" rx="2.5" fill="#f6c76b"/>
<path class="il-river" d="M-10 236C110 196 220 252 490 206"/>
<path fill="#141230" d="M0 250V230Q120 216 240 232T480 226V250z"/>
<g fill="#0f0d26"><path d="M30 232l10-30 10 30z"/><path d="M48 234l8-22 8 22z"/><path d="M400 228l10-32 10 32z"/><path d="M420 230l8-22 8 22z"/></g>
</svg>`;
    const tag = el("span", "hs-win-tag", "Nothing to install");   // TODO(owner): the window's badge
    win.append(bar, pic, tag);
    box.append(win);
    return box;
  }

  // the Den slide's right side: three isometric rooms, a white room, edit mode, friends in
  const P = (u, v, h) => `${(100 + 80 * u - 80 * v).toFixed(1)},${(80 + 40 * u + 40 * v - (h || 0)).toFixed(1)}`;
  const XY = (u, v, h) => P(u, v, h).split(",").map(Number);
  const poly = (cls, pts) => `<polygon class="${cls}" points="${pts.join(" ")}"/>`;
  function cube(u0, v0, u1, v1, h, color) {
    return `<g class="iso" style="--c:${color}">` +
      poly("f-l", [P(u0, v1), P(u1, v1), P(u1, v1, h), P(u0, v1, h)]) +
      poly("f-r", [P(u1, v0), P(u1, v1), P(u1, v1, h), P(u1, v0, h)]) +
      poly("f-t", [P(u0, v0, h), P(u1, v0, h), P(u1, v1, h), P(u0, v1, h)]) + "</g>";
  }
  function figure(u, v, color) {
    const [x, y] = XY(u, v);
    return `<g class="fig" style="--c:${color}"><ellipse class="fig-sh" cx="${x}" cy="${y}" rx="9" ry="3.5"/>` +
      `<rect x="${x - 6}" y="${y - 22}" width="12" height="21" rx="6"/><circle cx="${x}" cy="${y - 28}" r="6"/></g>`;
  }
  function room(inside) {
    return `<svg viewBox="0 6 200 164" preserveAspectRatio="xMidYMid meet">` +
      poly("rm-wl", [P(0, 1), P(0, 0), P(0, 0, 64), P(0, 1, 64)]) + poly("rm-wr", [P(0, 0), P(1, 0), P(1, 0, 64), P(0, 0, 64)]) +
      poly("rm-fl", [P(0, 0), P(1, 0), P(1, 1), P(0, 1)]) +
      `<circle class="rm-lt" cx="${XY(0, 0.5, 50)[0]}" cy="${XY(0, 0.5, 50)[1]}" r="4"/><circle class="rm-lt" cx="${XY(0.5, 0, 50)[0]}" cy="${XY(0.5, 0, 50)[1]}" r="4"/>` +
      inside + "</svg>";
  }
  function denRooms() {
    const grid = [0.25, 0.5, 0.75].map((t) => `<path class="rm-grid" d="M${P(t, 0)}L${P(t, 1)}M${P(0, t)}L${P(1, t)}"/>`).join("");
    const [gx, gy] = XY(0.42, 0.58, 22);
    const gizmo = `<g class="gizmo"><path class="gz-y" d="M${gx} ${gy}v-30"/><path class="gz-x" d="M${gx} ${gy}l26 13"/><path class="gz-z" d="M${gx} ${gy}l-26 13"/>` +
      `<circle cx="${gx}" cy="${gy}" r="3"/></g>`;
    const ghost = `<g class="ghost">${poly("", [P(0.62, 0.18, 30), P(0.84, 0.18, 30), P(0.84, 0.4, 30), P(0.62, 0.4, 30)])}` +
      `<path d="M${P(0.84, 0.4, 30)}L${P(0.84, 0.4)}M${P(0.62, 0.4, 30)}L${P(0.62, 0.4)}M${P(0.84, 0.18, 30)}L${P(0.84, 0.18)}"/></g>`;
    const [lx, ly] = XY(0.5, 0.5, 96);
    const link = `<g class="link-badge" transform="translate(${lx} ${ly})"><circle r="13"/><path d="M-5 3l-2 2a3.5 3.5 0 0 1-5-5l3-3a3.5 3.5 0 0 1 5 0M5-3l2-2a3.5 3.5 0 0 1 5 5l-3 3a3.5 3.5 0 0 1-5 0M-3 3l6-6"/></g>`;
    return [
      room(figure(0.55, 0.55, "var(--t-accent)")),
      room(grid + cube(0.3, 0.46, 0.56, 0.72, 22, "#c9a46a") + cube(0.06, 0.08, 0.2, 0.3, 40, "#7d8db3") + ghost + gizmo + figure(0.9, 0.46, "var(--t-accent)")),
      room(poly("rug", [P(0.2, 0.25), P(0.8, 0.25), P(0.8, 0.85), P(0.2, 0.85)]) + cube(0.06, 0.1, 0.5, 0.26, 16, "#8b6cf0") + cube(0.06, 0.1, 0.5, 0.14, 32, "#7559d8") +
        cube(0.78, 0.06, 0.92, 0.2, 14, "#b9774b") + `<circle class="leaf" cx="${XY(0.85, 0.13, 30)[0]}" cy="${XY(0.85, 0.13, 30)[1]}" r="11"/>` +
        figure(0.45, 0.5, "var(--t-accent)") + figure(0.66, 0.62, "#e0a93a") + figure(0.4, 0.78, "#3fbf7f") + link),
    ];
  }
  function denStage() {
    const box = el("div", "hs-side hs-den");
    const ol = el("ol", "hs-den-steps");
    const rooms = denRooms();
    // TODO(owner): the three step names
    [["A white room", "Yours, on this PC"], ["Edit mode", "Place, move and stack props"], ["Invite friends", "Send them the Den's link"]].forEach(([t, l], i) => {
      const li = el("li", "hs-den-step");
      const pic = el("span", "hs-den-pic");
      pic.setAttribute("aria-hidden", "true");
      pic.innerHTML = rooms[i];
      const tx = el("span", "hs-den-t");
      tx.append(el("span", "hs-st-n", String(i + 1)), el("b", "", t), el("i", "", l));
      li.append(pic, tx);
      ol.append(li);
    });
    box.append(ol);
    return box;
  }

  // the game modes' small pictures (by mode id; any other mode gets the puzzle)
  const MODE_PICS = {
    minigolf: `<svg viewBox="0 0 120 64"><path class="mp-hill" d="M0 64V40Q30 26 62 34T120 26V64z"/><path class="mp-green" d="M0 64V50Q40 40 70 45T120 40V64z"/>
<path class="mp-path" d="M27 52Q52 34 86 42"/><ellipse class="mp-hole" cx="88" cy="43" rx="6" ry="2"/><path class="mp-pole" d="M88 43V9"/><path class="mp-flag" d="M88 9l17 5-17 5z"/><circle class="mp-ball" cx="24" cy="53" r="3.8"/></svg>`,
    "bumper-balls": `<svg viewBox="0 0 120 64"><ellipse class="mp-arena" cx="58" cy="50" rx="48" ry="11"/><ellipse class="mp-rim" cx="58" cy="47" rx="48" ry="11"/>
<circle class="mp-b1" cx="42" cy="38" r="10"/><circle class="mp-b2" cx="68" cy="37" r="10"/><g class="mp-fly"><circle class="mp-b3" cx="102" cy="18" r="7.5"/></g>
<path class="mp-motion" d="M86 27l-9 4M88 34l-8 2"/><circle class="mp-shine" cx="38" cy="34" r="3"/><circle class="mp-shine" cx="64" cy="33" r="3"/></svg>`,
    "coin-dash": `<svg viewBox="0 0 120 64"><g class="mp-coin"><circle cx="30" cy="42" r="10"/><circle class="in" cx="30" cy="42" r="6"/></g><g class="mp-coin"><circle cx="54" cy="30" r="10"/><circle class="in" cx="54" cy="30" r="6"/></g>
<g class="mp-coin"><circle cx="74" cy="46" r="9"/><circle class="in" cx="74" cy="46" r="5"/></g><path class="mp-gem" d="M98 16l11 12-11 18-11-18z"/><path class="mp-gem-f" d="M87 28h22M98 16v30"/>
<path class="il-star" d="${STAR}" transform="translate(16 18) scale(.8)"/></svg>`,
    _: `<svg viewBox="0 0 120 64"><path class="mp-puz" d="M42 14h12v4a4 4 0 0 0 8 0v-4h12v14h-4a4 4 0 0 0 0 8h4v14H62v-4a4 4 0 0 0-8 0v4H42V36h4a4 4 0 0 0 0-8h-4z"/></svg>`,
  };
  const SLASH = { minigolf: "/golf" };   // the rest start from /modes (the Hangout's line); TODO(owner): each mode's own command

  // the launch slide's right side: the official lineup, what's on (three modes), the latest forum threads
  function hangoutSide() {
    const box = el("div", "hs-side hs-stack");
    box.append(lineupPanel());
    const M = Modes();
    const on = M ? M.modes().filter((m) => m.status === "live" && m.kind === "realm").slice(0, 3) : [];
    if (on.length) {
      const card = el("div", "hs-glass hs-whats");
      card.append(sideHead("What's on in the Hangout"));
      const row = el("div", "hs-mt-row");
      for (const m of on) {
        const b = el("button", "hs-mt");
        b.type = "button";
        b.dataset.mode = m.id;
        b.title = `${m.title}: open Modes`;
        b.addEventListener("click", () => M.show(m.id));
        const pic = el("span", "hs-mt-pic");
        pic.setAttribute("aria-hidden", "true");
        pic.innerHTML = MODE_PICS[m.id] || MODE_PICS._;   // constant markup
        b.append(pic, el("b", "", m.title), el("i", "", SLASH[m.id] || "/modes"));
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
    const box = el("div", "hs-side hs-steps");
    box.append(el("div", "hs-side-h", "Set up in four steps"));
    const ol = el("ol", "hs-st");
    [["Pick a ruleset", "Vanilla+, Dalaran hangout, a Den or your own"],
     ["Press Start", "The host pack runs it on this PC"],
     ["Listed in a minute", "The relay: no ports, your address hidden"],
     ["Invite friends", "Share the link, or go public"]].forEach(([t, l], i) => {
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
  const SITE = "https://play.openvanilla.app";
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
      const pic = d.ill ? d.ill() : null;
      if (pic) { s.classList.add("has-ill"); s.append(pic); }
      const side = d.side ? d.side() : null;
      if (side) { s.classList.add("has-side"); s.append(side); } else if (!pic) s.append(el("span", "hs-deco"));
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
  document.addEventListener("leyline:realms", () => { renderRealms(); build(); });
  document.addEventListener("leyline:catalog", () => { build(); renderMods(); });
  document.addEventListener("leyline:modes", () => { build(); renderModes(); });
  document.addEventListener("leyline:page", (e) => { if ((e.detail || {}).page === "play") loadForum(); });
  build();
  loadForum();
  renderRealms();
  renderMods();
  renderModes();
  renderNewsRow();
  if (Modes()) Modes().ensure();

  window.LeylineHome = { slides: () => slides.map((s) => s.key), index: () => index, show, build, autoOn, AUTO_MS, thumbUrl };
})();
