// The hub's feature-section pictures (stream/www-files/art/leyline-ui-*.webp): the launcher's own pages (launcher/ui)
// in Chromium with a fake Tauri core and sample data, Dark theme, 1240 x 760 at 2x pixels (2480 x 1520, crisp on
// high-density screens; the page shows them at 1240 x 760). No game art, no client build numbers, no game name: text
// that is only a build number is hidden, numbers and the game's name are taken out of the rest, before the shot.
//
//   node tools/art/leyline-ui-shots.cjs OUTDIR [play realms discover modes]      (LEYLINE_SHOT_SCALE=1 for 1x)
//   then, per page (play -> home, discover -> workshop), webp q85, about 180 KB at most:
//   python3 -c "from PIL import Image; Image.open('OUTDIR/play.png').convert('RGB').save('stream/www-files/art/leyline-ui-home.webp', 'WEBP', quality=85, method=6)"
'use strict';
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd(), "/usr/lib/node_modules", "/usr/local/lib/node_modules"] }));
const path = require("path"), fs = require("fs");
const WT = path.join(__dirname, "..", "..");
const INDEX = "file://" + path.join(WT, "launcher", "ui", "index.html");
const OUT = path.resolve(process.argv[2] || ".") + "/";
const MODES = JSON.parse(fs.readFileSync(path.join(WT, "stream", "playmodes.json"), "utf8")).modes;

const FAKE = ({ page, modes }) => {
  try { localStorage.setItem("leyline.page", page); localStorage.setItem("leyline.catSort", "hot"); } catch (_) {}
  const base = { official: false, kind: "PvE", ruleset: "main", state: "live", version: "3.3.5a", core: "azerothcore", build: "3.3.5a",
    tags: [], region: null, region_estimated: false, language: null, max_players: null, uptime_24h: null, uptime_7d: null,
    is_new: false, score: 0, featured: false, verified: false, direct: false, rules: [], claimed: true, players: 0, bots: 0,
    tagline: "", summary: "", join_url: null, discord: null, relay: "relay.openvanilla.app" };
  const R = (o) => Object.assign({}, base, o, { report_url: o.official ? null : "https://play.openvanilla.app/wrath/realms/report?realm=" + o.realm_id });
  const realms = [
    R({ slug: "official", name: "Dalaran Hangout", official: true, tagline: "Our own realm: drop in and say hello.", address: "play.openvanilla.app", group: "official", players: 4, bots: 10 }),
    R({ slug: "c-dddddddddddddddd", realm_id: "dddddddddddddddd", name: "Old Days", featured: true, verified: true, core: "vmangos",
        tags: ["pvp", "rp"], region: "eu", language: "en", uptime_7d: 97, players: 12, address: "relay.openvanilla.app:40020", group: "featured" }),
    R({ slug: "c-bbbbbbbbbbbbbbbb", realm_id: "bbbbbbbbbbbbbbbb", name: "Busy Den", tags: ["bots"], region: "na-east", is_new: true,
        players: 30, bots: 40, max_players: 100, uptime_24h: 99, address: "relay.openvanilla.app:40011", group: "community" }),
    R({ slug: "c-eeeeeeeeeeeeeeee", realm_id: "eeeeeeeeeeeeeeee", name: "Lantern Isle", tags: ["custom"], region: "oce",
        players: 7, uptime_7d: 92, address: "relay.openvanilla.app:40031", group: "community" }),
    R({ slug: "c-ffffffffffffffff", realm_id: "ffffffffffffffff", name: "Quiet Meadow", tags: ["rp"], region: "eu", players: 3, address: "relay.openvanilla.app:40033", group: "community" }),
  ];
  const P = (id, name, desc, extra) => Object.assign({ id, source: "packaged", name, description: desc, category: "addons",
    builds: ["3.3.5a"], author: "Leyline", author_url: "", licence: "MIT", repo: "", page: "", credits: name + " by Leyline · MIT",
    stars: null, last_push: "", version: "1.0.0", kind: "ui", permissions: [], on_wrath: false,
    download: "https://play.openvanilla.app/wrath/mods/" + id.slice(4) + "/download", sha256: "ab".repeat(32), size: 1000 }, extra || {});
  const catalog = { categories: [{ id: "addons", name: "Addons and UI", line: "", icon: "" }, { id: "sandbox", name: "Sandbox and game modes", line: "", icon: "" },
    { id: "tools", name: "Tools", line: "", icon: "" }],
    projects: [P("mod:quest-lens", "Quest Lens", "Shows where your quests are on the map."),
      P("mod:golfcart", "Golf Cart", "A little cart for the minigolf course.", { category: "sandbox", kind: "both" }),
      P("mod:clean-bars", "Clean Bars", "Tidy action bars that stay out of the way."),
      P("mod:loot-ledger", "Loot Ledger", "Keeps a list of everything you picked up."),
      P("mod:party-pings", "Party Pings", "Ping a spot and your party sees it."),
      P("mod:calm-chat", "Calm Chat", "Softer chat colours and tidy tabs.")], from_cache: false, saved_at: 1, error: null };
  const M = (id, kind, all, avg, n, hot) => ({ id, kind, installs: { all, d30: all / 5, d7: 0 }, rating: { avg, n, score: avg }, hot, rising: hot, new: "2026-10-20", updated: "2026-10-28" });
  const metrics = { "mod:quest-lens": M("mod:quest-lens", "addon", 812, 4.7, 41, 3), "mod:golfcart": M("mod:golfcart", "mode", 390, 4.5, 18, 2.6),
    "mod:clean-bars": M("mod:clean-bars", "addon", 640, 4.4, 33, 2.2), "mod:loot-ledger": M("mod:loot-ledger", "addon", 220, 4.2, 12, 1.4),
    "mod:party-pings": M("mod:party-pings", "addon", 150, 4.6, 9, 1.1), "mod:calm-chat": M("mod:calm-chat", "addon", 95, 4.1, 5, 0.6) };
  const order = Object.keys(metrics);
  window.__TAURI__ = { core: { invoke: async (cmd, args) => {
    switch (cmd) {
      case "get_state": return { version: "", settings: { clients: [{ id: "c-1", name: "My game", path: "/games/mine", build: "3.3.5a", realmlist: "" }],
        selected_client: "c-1", selected_realm: "play.openvanilla.app", wine: { enabled: false, command: "wine", prefix: "" }, count_installs: true },
        official_realm: "play.openvanilla.app", browser_url: "https://play.openvanilla.app/wrath", windows: false, data_dir: "/tmp" };
      case "realms_list": return { realms, network: { realms: 5, players: 56, bots: 50 }, from_cache: false, saved_at: 1, error: null };
      case "realm_status": return { state: "online", players: 4, bots: 10, ping_ms: 38 };
      case "p2p_flags": return { effective: { p2p_hosting: false, limits: {} }, known: [], local: { overrides: {} }, site: {} };
      case "host_info": return { dir: "", is_kit: false, problems: [], kit: null, seeds: [], realm: null };
      case "host_listing": return { tags: ["rp"], region: "eu", language: "en", max_players: null, direct: false };
      case "mods_catalog": return catalog;
      case "mods_ranked": return { ids: order, metrics, from_cache: false, error: null };
      case "mods_installed": return { client: "c-1", build: "3.3.5a", mods: [] };
      case "mods_updates": return [];
      case "modes_list": return { modes, from_cache: false, builtin: false, saved_at: null, error: null };
      case "themes_list": return { themes: [], active: "dark" };
      case "deep_link_take": return null;
      case "launcher_update_state": return null;
      case "social_status": return { signed_in: false };
      default: return null;
    }
  } } };
};

(async () => {
  const b = await chromium.launch();
  for (const page of process.argv.slice(3).length ? process.argv.slice(3) : ["play", "realms", "discover", "modes"]) {
    const ctx = await b.newContext({ viewport: { width: 1240, height: 760 }, colorScheme: "dark", deviceScaleFactor: +(process.env.LEYLINE_SHOT_SCALE || 2) });
    const p = await ctx.newPage();
    p.on("pageerror", (e) => console.log(page, "pageerror", String(e).slice(0, 200)));
    await p.addInitScript(FAKE, { page, modes: MODES });
    await p.goto(INDEX);
    await p.waitForTimeout(1500);
    await p.evaluate(() => {
      // no client numbers or game names in the pictures: hide what is only a version, strip it from the rest
      const V = /\s*(?:·\s*)?\b(?:5875|8606|12340|15595|18414|v?1\.12(?:\.1)?|2\.4\.3|3\.3\.5a?|4\.3\.4|5\.4\.8)\b/gi;
      document.querySelectorAll("#news-items").forEach((x) => x.remove());
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const hit = [];
      while (w.nextNode()) if (/\b(?:1\.12|2\.4\.3|3\.3\.5|4\.3\.4|5\.4\.8|5875|8606|12340|15595|18414)|launcher 0\.|Leyline v/i.test(w.currentNode.nodeValue)) hit.push(w.currentNode);
      hit.forEach((t) => {
        const el = t.parentElement;
        const left = t.nodeValue.replace(V, "").replace(/Leyline launcher 0\.\d+|Leyline v\S*/i, "").replace(/^\s*·\s*/, "").trim();
        if (!left || /^[·\s]*$/.test(left) || /runs|needs|add your own/i.test(left)) { el.style.display = "none"; } else t.nodeValue = left;
      });
      document.querySelectorAll("select option").forEach((o) => { o.textContent = o.textContent.replace(V, "").replace(/\s*·\s*$/, ""); });
      // no game name either: "WRATH · ON THE LEYLINE NETWORK" -> "ON THE LEYLINE NETWORK", "BACK TO WRATH" -> "BACK TO OUR REALM"
      const w2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const named = [];
      while (w2.nextNode()) if (/\bwrath\b|wotlk|wrathunleashed/i.test(w2.currentNode.nodeValue)) named.push(w2.currentNode);
      named.forEach((t) => {
        t.nodeValue = t.nodeValue.replace(/^\s*WRATH\s*·\s*/i, "").replace(/BACK TO WRATH/i, "BACK TO OUR REALM")
          .replace(/\b(?:wrath ?unleashed|wotlk|wrath)\b/gi, "Leyline");
      });
    });
    await p.waitForTimeout(200);
    await p.screenshot({ path: OUT + page + ".png" });
    console.log("shot", page);
    await ctx.close();
  }
  await b.close();
})();
