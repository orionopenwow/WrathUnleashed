"""The hidden Leyline hub (stream/hub.py) on the portal: every route answers 200 with noindex (meta and
X-Robots-Tag), the catalog merges the Workshop, the community index and themes (a duplicate shows once), "Submit a
mod" queues without personal data, the admin console's decisions apply (approved.json, delist), the launcher feed
keeps the all.json shape, the front-door switch, and no current page links to the preview.

    python3 -I stream/tests/test_hub.py stream/wrath_portal.py
"""
import html, http.client, importlib.util, json, os, re, shutil, sys, tempfile, threading, time, urllib.parse
from http.server import ThreadingHTTPServer

PAGE_PORT = 18231
PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
HERE = os.path.dirname(PORTAL)
REPO = os.path.dirname(HERE)
DATA = tempfile.mkdtemp(prefix="wu-hub-data-")
HUBDIR = tempfile.mkdtemp(prefix="wu-hub-dir-")
shutil.copy(os.path.join(HERE, "hub", "community-index.json"), HUBDIR)
json.dump({"format": 1, "themes": [{"id": "night-sky", "name": "Night Sky", "description": "Deep blue and stars.",
                                    "author": "Leyline", "licence": "CC-BY-4.0"},
                                   {"id": "bad", "name": "WoW theme"}, {"id": "../x", "name": "Path"}]},
          open(os.path.join(HUBDIR, "themes.json"), "w"))
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example",
                  WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_PORTAL_DATA=DATA, WU_HUB_DIR=HUBDIR,
                  WU_MODS_DIR=tempfile.mkdtemp(), WU_WORKSHOP_ITEMS_DIR=tempfile.mkdtemp())
os.environ.pop("WU_HUB_FRONT", None)
os.environ.pop("WU_HUB", None)

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS", name)
    else:
        failed += 1; print("FAIL", name, extra)


BANNED = re.compile(r"(?i)world\s*of\s*warcraft|\bwow\b|warcraft|lich\s*king|blizzard")


def visible(p):
    p = re.sub(r"<style.*?</style>", " ", p, flags=re.S)
    p = re.sub(r"<!--.*?-->", " ", p, flags=re.S)
    attrs = " ".join(re.findall(r'(?:alt|title|content|aria-label|placeholder|value)="([^"]*)"', p))
    return re.sub(r"<[^>]+>", " ", p) + " " + attrs


spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)
wp.realm_status = lambda: {"online": True, "players": 3, "bots": 10}
HB = wp.hub_mod
check("hub.py loaded beside the portal", HB is not None)
if HB is None:
    print(f"\n{passed}/{passed + failed} passed"); sys.exit(1)

srv = ThreadingHTTPServer(("127.0.0.1", PAGE_PORT), wp.PageHandler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(path, method="GET", body=None, ip="10.9.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
    hd = {"X-Forwarded-For": ip}
    if body is not None:
        hd["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=body, headers=hd)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


INDEX = json.load(open(os.path.join(HUBDIR, "community-index.json")))
first = INDEX["entries"][0]
pages = ["/wrath/leyline-preview", "/wrath/leyline-preview/", "/wrath/leyline-preview/catalog",
         "/wrath/leyline-preview/catalog?build=1.12", "/wrath/leyline-preview/catalog?build=5.4.8&sort=name",
         "/wrath/leyline-preview/catalog?cat=themes", "/wrath/leyline-preview/catalog?source=index&page=2",
         "/wrath/leyline-preview/catalog?q=%3Cscript%3E&cat=nope&build=9&sort=x&page=-4",
         "/wrath/leyline-preview/creators", "/wrath/leyline-preview/beacon", "/wrath/leyline-preview/submit",
         "/wrath/leyline-preview/forge", "/wrath/leyline-preview/agents",
         "/wrath/leyline-preview/realms", "/wrath/leyline-preview/modes", "/wrath/leyline-preview/news",
         "/wrath/leyline-preview/gallery", "/wrath/leyline-preview/gallery?f=mods", "/wrath/leyline-preview/gallery?f=%3Cx%3E",
         "/wrath/leyline-preview/p/" + first["id"].replace(":", "-"), "/wrath/leyline-preview/p/theme-night-sky"]
for p in pages:
    st, h, b = req(p)
    s = b.decode()
    check(f"GET {p}: 200 html", st == 200 and h.get("content-type", "").startswith("text/html"), st)
    check(f"GET {p}: noindex header and meta", h.get("x-robots-tag") == "noindex, nofollow"
          and '<meta name="robots" content="noindex">' in s)
    csp = h.get("content-security-policy", "")
    if p.rstrip("/").split("?")[0] in ("/wrath/leyline-preview", "/wrath/leyline-preview/realms", "/wrath/leyline-preview/gallery"):
        # the front page, the realm list and the gallery: one small script, under this response's nonce, reading only this site
        nm = re.search(r"'nonce-([A-Za-z0-9_-]{16,})'", csp)
        gal = p.split("?")[0].endswith("/gallery")
        check(f"GET {p}: one script, under the CSP nonce, connect-src 'self'", nm and s.count("<script") == 1
              and f'<script nonce="{nm.group(1)}">' in s and ("connect-src" not in csp if gal else "connect-src 'self'" in csp)
              and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
              and "<script src" not in s, csp)
        check(f"GET {p}: no brand words", not BANNED.findall(visible(re.sub(r"<script.*?</script>", " ", s, flags=re.S))))
    else:
        check(f"GET {p}: no script, no brand words", "<script" not in s and "script-src 'none'" in csp
              and not BANNED.findall(visible(s)), BANNED.findall(visible(s))[:5])
    front_p = p.rstrip("/") == "/wrath/leyline-preview"
    check(f"GET {p}: the hub's own header (mark, wordmark, Sign In) and, below the front page, its sub-nav",
          'class="hb-top"' in s and 'class="ly-spin slow hb-mark"' in s and "<b>Leyline</b><i>Launcher</i>" in s
          and 'class="hb-signin" href="/login?next=%2Fwrath"' in s and ('class="hb-sub"' in s) != front_p
          and 'id="ly-site-nav"' not in s and 'class="hb-foot"' in s)
    check(f"GET {p}: the flat look, none of the painted art", 'data-look="leyline"' in s and "ly-spin-turn" in s and not re.search(
          r"leyline-(?:bg|emblem|divider|corner)|wu-(?:theme|card|corner|dragon|divider)|Cinzel|Leyline Display", s))
    check(f"GET {p}: no Support link, no other social sites", not re.search(r">\s*Support\s*<|facebook|twitter|instagram|x\.com", s, re.I))
st, h, _ = req("/wrath/leyline-preview", method="HEAD")
check("HEAD works", st == 200 and h.get("x-robots-tag"))
for p in ("/wrath/leyline-preview/p/link-000000000000", "/wrath/leyline-preview/p/../../etc", "/wrath/leyline-preview/nope"):
    st, h, b = req(p)
    check(f"GET {p}: 404, still noindex", st == 404 and h.get("x-robots-tag") == "noindex, nofollow", st)

front = req("/wrath/leyline-preview")[2].decode()
check("front page: no Browse by client chips (no client numbers on the hub)", "catalog?build=" not in front)
# 4.3.4 and 5.4.8 are not offered for now (the owner, 2026-10-30): no chips, no items made only for them
check("offered builds: capped at 3.3.5a", HB.offered_builds({}) == ["1.12", "2.4.3", "3.3.5a"]
      and HB.offered_builds({"LEYLINE_ALL_CLIENTS": "1"}) == HB.BUILDS)
check("front page: no 4.3.4 / 5.4.8 chips", all(f"catalog?build={b}" not in front for b in ("4.3.4", "5.4.8")))
check("offered_only: hidden-only items go, mixed ones keep the offered builds",
      HB.offered_only({"builds": ["4.3.4", "5.4.8"]}, HB.offered_builds({})) is None
      and HB.offered_only({"builds": ["3.3.5a", "4.3.4"]}, HB.offered_builds({}))["builds"] == ["3.3.5a"]
      and HB.offered_only({"builds": ["4.3.4"]}, HB.offered_builds({"LEYLINE_ALL_CLIENTS": "1"})) is not None)
check("offered_tag: a hidden build is no filter", HB.offered_tag("5.4.8") == "" and HB.offered_tag("cata") == ""
      and HB.offered_tag("1.12.1") == "1.12" and HB.build_tag("5.4.8") == "5.4.8")
check("catalog page: the 12 categories and themes", all(f"catalog?cat={c}" in req("/wrath/leyline-preview/catalog")[2].decode() for c in HB.CATEGORY_IDS + ["themes"]))
check("front page: creators and Host a Beacon", "/wrath/leyline-preview/creators" in front and "/wrath/leyline-preview/beacon" in front)
check("front page: a TODO(owner) for the tagline, no words in the owner's voice", "TODO(owner)" in front)
# the owner's mockup (2026-10-30): header nav, the hero, Platform Status, Community Spotlight, the footer
# the header mirrors the launcher's pages (owner 2026-10-30: "servers, mods, addons, etc ... it should all work in browser too")
NAV_ORDER = ["Play", "Realms", "Mods", "Addons", "Host", "Community", "More"]


def header_of(page):
    hd = re.search(r'<header class="hb-top">.*?</header>', page, re.S).group(0)
    nav = re.search(r'<nav class="hb-nav"[^>]*>(.*?)</nav>', hd, re.S).group(1)
    top = re.sub(r'<div class="hb-more-m">.*?</div>|<div class="hb-nav-x">.*?</div>', "", nav, flags=re.S)
    labels = re.findall(r'class="hb-ni[^"]*"[^>]*>(?:<svg.*?</svg>)<span>([^<]+)</span>', top, re.S)
    on = re.findall(r'class="hb-ni on"[^>]*>(?:<svg.*?</svg>)<span>([^<]+)</span>', top, re.S)
    return hd, nav, labels, on


hd, nav, labels, on = header_of(front)
check("side menu (owner 2026-10-30: \"make all the tools come from the side by default and can collapse\"): a fold switch before the "
      "header, a sidebar on wide screens, folded to icons, remembered by HUB_JS, the top bar kept on a phone",
      front.count('<input type="checkbox" id="hb-side" class="hb-side-t" aria-label="Fold the side menu"><header class="hb-top">') == 1
      and '<label for="hb-side" class="hb-side-b"' in hd and "@media (min-width:1081px){" in front
      and "body.hb .hb-top{position:fixed;inset:0 auto 0 0;width:var(--hb-side)" in front
       and ":root:has(#hb-side:checked){--hb-side:72px}" in front and 'localStorage.setItem("leyline.side"' in HB.HUB_JS
      and "@media (max-width:1080px){.hb-side-t,.hb-side-b{display:none}}" in front)
check("header: Play, Realms, Mods, Addons, Host, Community, More (Modes, Gallery and Status out of the menu)", labels == NAV_ORDER, labels)
hrefs = dict(re.findall(r'<a class="hb-ni[^"]*" href="([^"]+)"[^>]*><svg.*?</svg><span>([^<]+)</span>', nav, re.S)[i][::-1] for i in range(6))
check("header: each item goes to the launcher page's web twin", hrefs == {
      "Play": "/wrath", "Realms": "/wrath/leyline-preview/realms", "Mods": "/wrath/leyline-preview/catalog",
      "Addons": "/wrath/leyline-preview/catalog?cat=addons", "Host": "/wrath/host",
      "Community": "/wrath/leyline-preview#community"} and "addons" in HB.CATEGORY_IDS, hrefs)
more = re.search(r'<details class="hb-more-d"><summary class="hb-ni[^"]*">.*?<span>More</span></summary><div class="hb-more-m">(.*?)</div></details>', nav, re.S)
check("header: More is a details dropdown (no script needed) with Forge, Agents, Docs, News, Creators",
      more and re.findall(r"<span>([^<]+)</span>", more.group(1)) == ["Forge", "Agents", "Docs", "News", "Creators"]
      and "#status" not in more.group(1) and "/gallery" not in more.group(1))
check("header: the phone sheet has the same items as tiles, and the download", re.findall(
      r"<span>([^<]+)</span>", re.search(r'<div class="hb-nav-x">(.*?)</div>', nav, re.S).group(1)) == ["Forge", "Agents", "Docs", "News", "Creators"]
      and 'class="hb-dl-x"' in nav and 'id="hb-menu" class="hb-menu-t"' in hd and '<label for="hb-menu" class="hb-menu-b"' in hd)
check("header: a line icon by every item (inline SVG, currentColor)", nav.count('<svg viewBox="0 0 24 24" aria-hidden="true">') == 6 + 1 + 5 + 5
      and "stroke:currentColor" in front)
check("header: Download (primary) and Sign In (the crystal) on the right, no item active on the front page",
      re.search(r'<div class="hb-end"><a class="hb-dl" href="https://github\.com/orionopenwow/Leyline/releases/download/launcher-latest/Leyline\.exe"[^>]*>.*?Download</a>'
                r'<a class="hb-signin" href="/login\?next=%2Fwrath"><img src="/wrath/art/leyline-crystal-128.png"', hd, re.S)
      and on == [] and 'aria-current="page"' not in hd)
check("header: sticky with a blur, a hairline once scrolled, none of it moving with reduced motion",
      "backdrop-filter:blur(14px)" in front and "animation-timeline:scroll(root)" in front and ".hb-top.hb-scrolled{" in front
      and "hb-scrolled" in HB.HUB_JS and re.search(r"prefers-reduced-motion:reduce\)\{[^}]*animation:none!important\}.*?\.hb-top\{border-bottom-color", front, re.S))
check("hero: the whole mark leads, crisp (the 512px layers), big (~400px, 220px on a phone), turning slowly; the heading a step down",
      'class="ly-spin slow hb-hero-mark"' in front and "leyline-swirl-512.png" in front and "leyline-crystal-512.png" in front
      and "--ly-spin-size:clamp(220px,min(34vw,42vh),400px)" in front and ".hb-hero h1{margin:0 0 8px;font-size:clamp(22px,3vw,32px)" in front
      and "hb-crystal" not in front
      and "Every client, every server" in front and "One launcher for every classic client and every server" in front
      and "hb-bullets" not in front and "TODO(owner): the hero heading" in front
      and 'class="hb-hero-a"' not in front and 'class="hb-dl" href="https://github.com/orionopenwow/Leyline/releases/download/launcher-latest/Leyline.exe"' in front)
stats = re.search(r'<section class="hb-sec" id="status".*?</section>', front, re.S).group(0)
check("Platform Status: the main realm online from realm_status, sign-in, the network, the relay, the mod catalog",
      all(x in stats for x in ('Server: <em class="ok">OK</em> · 3 playing', "Sign-in", "Realm network", "Relay", "Mod catalog", " items · "))
      and '<em class="ok">OK</em>' in stats, stats)
check("Platform Status: a failing source is red, never a made-up OK", '<em class="bad">' in stats and "Game logins:" in stats)
check("Platform Status: no client downloads (we never download clients)", "Client" not in stats and "download" not in stats.lower())
spot = re.search(r'<section class="hb-sec" id="community".*?</section>', front, re.S).group(0)
spots = re.findall(r'<a class="hb-spot" href="/wrath/leyline-preview/p/([^"]+)">.*?<b>([^<]+)</b><i>by ([^<]+)</i>', spot, re.S)
names = {e["id"].replace(":", "-"): (HB.neutral(e["name"]), HB.neutral(e["author"])) for e in INDEX["entries"]}
check("Community Spotlight: two to four real items, with their own names and authors", 2 <= len(spots) <= 4
      and all(names.get(slug) == (HB.neutral(n), HB.neutral(a)) for slug, n, a in spots if slug in names) and any(slug in names for slug, _, _ in spots), spots)
foot = re.search(r'<footer class="hb-foot">.*?</footer>', front, re.S).group(0)
check("footer: Docs, Download, Community, Status, the wordmark, Discord and GitHub only",
      all(f">{x}<" in foot for x in ("Docs", "Download", "Community", "Status", "Discord", "GitHub")) and "<b>Leyline</b>" in foot)
# the owner's 2026-10-30 additions: realms under the hero, the feature sections in order, how it works, the polish
fs = re.findall(r'<section class="hb-fs hb-rv( flip)?" id="f-([a-z]+)".*?<p class="hb-eyebrow">.*?</span>([^<]+)</p><h2[^>]*>([^<]+)</h2>'
                r'<p class="hb-lede">([^<]+)</p><ul class="hb-points">(.*?)</ul><p class="hb-fs-a">(.*?)</p></div>'
                r'<div class="hb-fs-v">(.*?)</div></section>', front, re.S)
check("feature sections: one per part of Leyline, in the recommended order", [f[1] for f in fs] == [
      "launcher", "host", "realms", "modes", "mods", "forge", "agents", "community"] and [f[2] for f in fs] == [
      "Desktop launcher", "Server hosting software", "Realms &amp; hopping", "Minigolf &amp; game modes", "Mods &amp; the Workshop",
      "Forge", "Agents", "Community hub"], [f[1:3] for f in fs])
check("feature sections: alternating sides (every other one flips)", [bool(f[0]) for f in fs] == [False, True] * 4)
check("feature sections: a heading, a lede, points and a first link each", all(f[3] and f[4] and f[5].count("<li>") >= 2
      and 'class="hb-cta sm"' in f[6] for f in fs))
hrefs = [re.findall(r'href="([^"]+)"', f[6]) for f in fs]
check("feature sections: links to pages that exist, nothing paid", [h[0] for h in hrefs][1:] == [
      "/wrath/host", "/wrath/leyline-preview/realms", "/wrath?go=mode:minigolf", "/wrath/leyline-preview/catalog?sort=hot",
      "/wrath/leyline-preview/forge", "/wrath/leyline-preview/agents", "/wrath/leyline-preview/catalog"] and hrefs[0][0].startswith("https://github.com/orionopenwow/Leyline/releases")
      and not re.search(r"(?i)support|donat|\bvip\b|\bshop\b", " ".join(f[6] for f in fs)))
check("feature sections: a TODO(owner) to reorder them", "TODO(owner): the order of the products" in open(HB.__file__).read())
check("feature sections: the game modes line from playmodes.json, Hero Key as coming", "Minigolf" in fs[3][4]
      and "Hero Key sign-in across realms (coming)" in fs[2][5])
check("feature sections: every one has its icon", front.count('<span class="hb-ico"><svg viewBox="0 0 24 24" aria-hidden="true">') == 8)
feats = re.search(r'<div class="hb-feats" id="features">.*?(?=<section class="hb-sec hb-gal-s|<section class="hb-sec hb-rv" id="hosted"|<div class="hb-pair">)', front, re.S).group(0)
shots = re.findall(r'<img src="/wrath/art/(leyline-ui-[a-z]+\.webp)" alt="([^"]+)" width="1240" height="760" loading="lazy"', feats)
check("feature sections: the launcher's own pages as pictures (served, lazy, with alt text), our own panels for the rest "
      "(server software, the realm list; the Minigolf loop falls back to the Modes page without the game shots)",
      [n for n, _ in shots] == ["leyline-ui-home.webp", "leyline-ui-modes.webp", "leyline-ui-workshop.webp"]
      and 'class="hb-sw"' in fs[1][7] and 'class="hb-rlx"' in fs[2][7]
      and all(a for _, a in shots) and all(n in wp.ART_TYPES and not n.startswith("leyline-shot-") for n, _ in shots)
      and all(os.path.isfile(os.path.join(HERE, "www-files", "art", n)) for n, _ in shots)
      and 'class="hb-draw hb-people"' in fs[7][7] and 'class="hb-draw hb-code"' in fs[5][7] and 'class="hb-draw hb-code"' in fs[6][7]
      and not re.search(r"leyline-shot-|wu-load-orion|painted", feats, re.I) and not re.search(r"wu-load-orion|painted", front, re.I))
how = re.search(r'<ol class="hb-how[^"]*" aria-label="How it works">(.*?)</ol>', front, re.S)
check("how it works: three steps, launcher, game folder or browser, realm", how and re.findall(r"<b>([^<]+)</b>", how.group(1)) == [
      "Get the launcher", "Point it at your game folder", "Pick a realm"] and "play in your browser" in how.group(1)
      and "TODO(owner): the \"how it works\" wording" in front)
order = [front.index(x) for x in ('class="hb-hero"', 'id="realms"', 'class="hb-how', 'id="features"', 'id="f-launcher"', 'id="f-agents"',
                                  'id="status"', 'id="community"')]
check("front page order: hero, realms, how it works, the feature sections, status, spotlight", order == sorted(order), order)
check("realm list without a relay: our realm still there, one click", 'data-home="1"' in front and 'class="hb-play" href="/wrath"' in front
      and f'>{wp.PUBLIC_HOST}</code>' in front and "may be a little out of date" in front)
check("polish: hover lift and the reveal stop for reduced motion", "@media (prefers-reduced-motion:reduce)" in front
      and "animation:none!important" in front and ".hb-js .hb-wait{" in front and "focus-visible{outline:2px" in front)
check("polish: the script reads only this site's public JSON", re.findall(r'json\("([^"]+)"\)', HB.HUB_JS) == ["/wrath/realms.json", "/wrath/status.json"]
      and "innerHTML" not in HB.HUB_JS and "eval" not in HB.HUB_JS)
check("sub-nav: Realms, Modes and News", all(f'href="/wrath/leyline-preview/{x}"' in req("/wrath/leyline-preview/catalog")[2].decode()
                                               for x in ("realms", "modes", "news")))
for path, want in (("/realms", ["Realms"]), ("/catalog", ["Mods"]), ("/catalog?cat=addons", ["Addons"]), ("/catalog?cat=tools", ["Mods"]),
                   ("/modes", []), ("/beacon", ["Host"]), ("/submit", ["Mods"]), ("/p/" + first["id"].replace(":", "-"), ["Mods"]),
                   ("/news", ["More"]), ("/creators", ["More"]), ("", [])):
    pg = req("/wrath/leyline-preview" + path)[2].decode()
    hd, nav, labels, on = header_of(pg)
    more_on = 'class="hb-ni on"><svg' in re.search(r"<summary.*?</summary>", nav, re.S).group(0)
    sub_on = re.findall(r'class="hb-mi on" href="[^"]+" aria-current="page" title="[^"]+"><svg.*?</svg><span>([^<]+)</span>', nav, re.S)
    check(f"header on {path or '/'}: the same items, {want or sub_on or 'nothing'} active", labels == NAV_ORDER and on == want
          and (more_on == bool(sub_on)) and (sub_on == {"/news": ["News"], "/creators": ["Creators"]}.get(path, []))
          and hd.count('aria-current="page"') == len([w for w in want if w != "More"]) + 2 * len(sub_on), (labels, on, sub_on))   # (the dropdown's and the phone sheet's copy: one shows)
modes = req("/wrath/leyline-preview/modes")[2].decode()
mode_ids = [m["id"] for m in wp.playmodes.entries()]
check("modes page: every mode in playmodes.json, live realm modes one click", all(f'id="mode-{i}"' in modes for i in mode_ids)
      and 'class="hb-play" href="/wrath?go=mode:minigolf"' in modes and "Azeroth Survivors" in modes
      and 'go=mode:azeroth-survivors' not in modes and "Coming soon" in modes and 'href="/wrath/host">Host it' in modes)
check("modes page: no script", "<script" not in modes)
news = req("/wrath/leyline-preview/news")[2].decode()
check("news page: empty says so", "No news posts yet." in news)
os.makedirs(os.path.join(DATA, "leyline"), exist_ok=True)
json.dump({"format": 1, "posts": [{"id": "a", "date": "2026-10-29", "tag": "Launcher 0.3", "title": "Every client", "items": ["One", "Two"]},
                                  {"id": "b", "title": "WoW news", "items": []}]}, open(os.path.join(DATA, "leyline", "news.json"), "w"))
os.environ["WU_LEYLINE_DIR"] = os.path.join(DATA, "leyline")
news = req("/wrath/leyline-preview/news")[2].decode()
if wp.admin is not None:
    check("news page: the admin console's posts, brand words dropped", "Every client" in news and "<li>One</li>" in news
          and "WoW news" not in news)
os.environ["WU_LEYLINE_DIR"] = os.path.join(DATA, "leyline")
os.makedirs(os.environ["WU_LEYLINE_DIR"], exist_ok=True)
rel = "https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.4.0"
json.dump({"stable": {"version": "0.4.0", "tag": "launcher-v0.4.0", "url": rel}}, open(os.path.join(os.environ["WU_LEYLINE_DIR"], "channel.json"), "w"))
if wp.admin is not None and hasattr(wp.admin, "leyline_dir"):
    check("Download Now: the stable release the admin console published", f'href="{rel}"' in req("/wrath/leyline-preview")[2].decode())
json.dump({"stable": {"version": "0.4.0", "tag": "x", "url": "https://evil.example/x"}}, open(os.path.join(os.environ["WU_LEYLINE_DIR"], "channel.json"), "w"))
check("Download Now: never a link off the releases page", "evil.example" not in req("/wrath/leyline-preview")[2].decode())
cat = req("/wrath/leyline-preview/catalog?build=2.4.3")[2].decode()
check("catalog: filtered by build, labelled in words", all(("2.4.3" in e["builds"] or "any" in e["builds"]) for e in INDEX["entries"]
                                      if f'/p/{e["id"].replace(":", "-")}"' in cat) and "for the second era" in cat
      and 'aria-current="true">Second era</a>' in cat and "2.4.3" not in visible(re.sub(r'<input type="hidden"[^>]*>', "", cat)))
cata = req("/wrath/leyline-preview/catalog?build=5.4.8")[2].decode()
check("catalog: no item made only for 4.3.4 / 5.4.8", not any(
    f'/p/{e["id"].replace(":", "-")}"' in cata for e in INDEX["entries"] if not set(e["builds"]) & {"1.12", "2.4.3", "3.3.5a", "any"}))
junk = req("/wrath/leyline-preview/catalog?q=%3Cscript%3E")[2].decode()
check("catalog: the query is escaped", "<script>" not in junk and "&lt;script&gt;" in junk)
item = req("/wrath/leyline-preview/p/" + first["id"].replace(":", "-"))[2].decode()
check("item: View source, credit, licence, no Install", "View source on GitHub" in item and first["licence"] in item
      and 'rel="noopener noreferrer nofollow ugc"' in item and ">Install<" not in item
      and "/download" not in re.sub(r'<header class="hb-top">.*?</header>|<footer class="hb-foot">.*?</footer>', "", item, flags=re.S))   # the menu's own Download is the launcher
check("item: the repo URL is a link, never shown as text", first["repo"] not in visible(item))
theme = req("/wrath/leyline-preview/p/theme-night-sky")[2].decode()
check("themes: listed, bad ones dropped", "Night Sky" in theme and "WoW theme" not in req("/wrath/leyline-preview/catalog?cat=themes")[2].decode())

# ---------------------------------------------------------------- submissions
qfile = os.path.join(DATA, "hub", "submissions.jsonl")
form = "repo=https%3A%2F%2Fgithub.com%2Fnew-author%2Fcool-mod&build=2.4.3&category=tools&note=Hi+there"
st, h, _ = req("/wrath/leyline-preview/submit", "POST", form)
check("submit: 303 to the thanks page", st == 303 and h.get("location") == "/wrath/leyline-preview/submit?done=1", (st, h))
recs = [json.loads(l) for l in open(qfile)]
check("submit: one record, no personal data", len(recs) == 1 and set(recs[0]) == {"id", "repo", "build", "category", "note", "at", "via"}
      and recs[0]["repo"] == "https://github.com/new-author/cool-mod" and recs[0]["build"] == "2.4.3"
      and "10.9.0.1" not in open(qfile).read(), recs)
check("thanks page", "Thank you" in req("/wrath/leyline-preview/submit?done=1")[2].decode())
st, _, b = req("/wrath/leyline-preview/submit", "POST", form)
check("submit: the same repo again is already queued", st == 400 and "already in the queue" in b.decode())
st, _, b = req("/wrath/leyline-preview/submit", "POST", "repo=https%3A%2F%2Fexample.com%2Fx&build=3.3.5a&category=tools")
check("submit: other sites refused, the form kept", st == 400 and "GitHub, GitLab or Codeberg" in b.decode() and "example.com" in b.decode())
st, _, b = req("/wrath/leyline-preview/submit", "POST", "repo=" + first["repo"] + "&build=3.3.5a&category=tools")
check("submit: a listed repo is already in the catalog", st == 400 and "already in the catalog" in b.decode())
st, _, b = req("/wrath/leyline-preview/submit", "POST", "repo=https%3A%2F%2Fgithub.com%2FChumpton%2Fx&build=3.3.5a&category=tools")
check("submit: Chumpton refused", st == 400)
st, _, b = req("/wrath/leyline-preview/submit", "POST", "repo=https%3A%2F%2Fgithub.com%2Fa%2Fb&build=9.9&category=tools")
check("submit: a build we don't have", st == 400 and "build" in b.decode())
st, _, _ = req("/wrath/leyline-preview/submit", "POST", "repo=https%3A%2F%2Fgithub.com%2Fbot%2Fspam&build=3.3.5a&category=tools&website=x")
check("submit: the hidden field filled (a bot): thanked, nothing kept", st == 303 and "bot/spam" not in open(qfile).read())
st, _, _ = req("/wrath/leyline-preview/submit", "POST", "x" * 5000)
check("submit: too large", st == 413)
codes = [req("/wrath/leyline-preview/submit", "POST", f"repo=https%3A%2F%2Fgithub.com%2Frate%2Fm{k}&build=3.3.5a&category=tools",
             ip="10.9.9.9")[0] for k in range(7)]
check("submit: 5 an hour from one address", codes[:5] == [303] * 5 and codes[5:] == [400, 400], codes)
st, _, _ = req("/wrath/leyline-preview/catalog", "POST", "a=b")
check("POST elsewhere: 405", st == 405)

store = HB.hub.store
new_id = recs[0]["id"]
check("pending: oldest first, one per repo", [r["id"] for r in store.pending()][0] == new_id and len(store.pending()) == 6)
delist = first["id"][5:]
with open(os.path.join(DATA, "hub", "decisions.jsonl"), "w") as f:
    f.write(json.dumps({"id": new_id, "decision": "approve", "category": "audio", "at": "2026-10-29T10:00:00Z"}) + "\n")
    f.write(json.dumps({"id": delist, "repo": first["repo"], "decision": "delist", "at": "2026-10-29T10:01:00Z"}) + "\n")
    f.write("not json\n")
    f.write(json.dumps({"id": "zz", "decision": "approve"}) + "\n")
st, h, b = req("/wrath/leyline-preview/approved.json")
doc = json.loads(b)
check("approved.json: approved with the admin's category, delisted, nothing else", st == 200 and doc == {
    "format": 1, "approved": [{"id": new_id, "repo": "https://github.com/new-author/cool-mod", "build": "2.4.3", "category": "audio"}],
    "delisted": [{"id": delist, "repo": first["repo"]}]} and h.get("x-robots-tag"), doc)
check("approved.json: no notes or times", "Hi there" not in b.decode() and "2026-10" not in b.decode())
check("a decided submission leaves the queue", new_id not in [r["id"] for r in store.pending()])
check("a delisted entry is gone at once", req("/wrath/leyline-preview/p/" + first["id"].replace(":", "-"))[0] == 404)
st, _, b = req("/wrath/leyline-preview/submit", "POST", "repo=" + first["repo"] + "&build=3.3.5a&category=tools", ip="10.1.1.1")
check("a delisted repo can't be submitted again", st == 400 and "reviewed" in b.decode())

# ---------------------------------------------------------------- the launcher feed
st, h, b = req("/wrath/leyline/catalog.json")
feed = json.loads(b)
check("feed: 200 json, CORS *", st == 200 and h.get("access-control-allow-origin") == "*" and h["content-type"].startswith("application/json"))
check("feed: the all.json shape", feed["format"] == 1 and isinstance(feed["projects"], list) and feed["builds"] == ["1.12", "2.4.3", "3.3.5a", "any"]
      and not any(set(p.get("builds") or []) & {"4.3.4", "5.4.8"} for p in feed["projects"])
      and [c["id"] for c in feed["categories"]][-1] == "themes" and len(feed["categories"]) == 13)
ids = [p["id"] for p in feed["projects"]]
check("feed: ids in the launcher's forms", all(re.fullmatch(r"link:[0-9a-f]{12}|mod:[a-z][a-z0-9-]{2,31}|theme:[a-z][a-z0-9-]{1,31}", i) for i in ids))
links = [p for p in feed["projects"] if p.get("hub_source") == "index"]
check("feed: index entries are link-out, no Install", links and all(p["link_out"] and p["download"] is None and p["sha256"] is None
      and p["source"] == "community" and p["repo"].startswith("https://") for p in links))
check("feed: every field all.json has", all(set(p) >= {"id", "source", "name", "description", "category", "builds", "author",
      "author_url", "licence", "repo", "page", "credits", "stars", "last_push", "version", "kind", "permissions", "on_wrath",
      "download", "sha256"} for p in links))
check("feed: sorted by name", [p["name"].lower() for p in feed["projects"]] == sorted(p["name"].lower() for p in feed["projects"]))
check("feed: the delisted entry is out", first["id"] not in ids)
check("feed: no brand words", not BANNED.findall(" ".join(p["name"] + " " + p["description"] + " " + p["author"] + " " + p["credits"]
                                                      for p in feed["projects"])))


class FakeWorkshop:
    def all_json(self):
        dup = INDEX["entries"][1]
        return json.dumps({"projects": [
            {"id": "mod:pings", "source": "packaged", "name": "Pings", "description": "Alt-click the map.", "category": "addons",
             "builds": ["3.3.5a"], "author": "WrathUnleashed", "licence": "MIT", "repo": "", "page": "https://play.example/wrath/mods/pings",
             "download": "https://play.example/wrath/mods/pings/download", "sha256": "a" * 64, "kind": "ui"},
            {"id": dup["id"], "source": "community", "name": "Shared link", "description": "Someone shared it.", "category": "tools",
             "builds": ["3.3.5a"], "author": "x", "licence": "MIT", "repo": dup["repo"], "page": "https://play.example/wrath/mods/p/" + dup["id"][5:]}]})

    def categories(self):
        return [{"id": c, "name": n, "line": "", "icon": ""} for c, n in HB.CATEGORIES], {}


real = HB.hub.portal
HB.hub.portal = lambda name: FakeWorkshop() if name == "workshop" else real(name)
items = HB.hub.items()
dup_id = INDEX["entries"][1]["id"]
check("merge: a Workshop link and an index entry for one repo show once, as the Workshop's",
      [i["source"] for i in items if i["id"] == dup_id] == ["workshop"])
check("merge: packaged mods first-class", any(i["id"] == "mod:pings" and i["packaged"] for i in items))
feed2 = json.loads(req("/wrath/leyline/catalog.json")[2])
pings = next(p for p in feed2["projects"] if p["id"] == "mod:pings")
check("feed: packaged mods keep their download", pings["download"].endswith("/download") and pings["link_out"] is False)
HB.hub.portal = real

# ---------------------------------------------------------------- no client numbers, no game name (owner 2026-10-30)
# Every hub page, with realms on several builds and catalog text full of build numbers and the game's name: none of it
# reaches what a visitor reads (text, title, meta, alt, labels). The launcher feed keeps the numbers (it is data).
NOPE = re.compile(r"(?i)(?<![\w.])v?(?:1\.12(?:\.1)?|2\.4\.3|3\.3\.5a?|4\.3\.4|5\.4\.8|5875|8606|12340|15595|18414)(?![\w])"
                  r"|world\s*of\s*warcraft|warcraft|(?<![a-z])wow(?![a-z])|lich\s*king|blizzard")


def shown(p):
    """What a visitor can read: the text, the title, meta content, alt, title, aria-label, placeholder (not values,
    hidden inputs, URLs, the script or the styles)."""
    p = re.sub(r"<(script|style)\b.*?</\1>", " ", p, flags=re.S)
    p = re.sub(r"<!--.*?-->|<input[^>]*type=\"hidden\"[^>]*>", " ", p, flags=re.S)
    # the realm list's version chip is the one allowed client number (owner 2026-10-30: "list the client version number in
    # the realm list too")
    p = re.sub(r'<span class="hb-ver" title="Game client version">[0-9a-z.]+</span>', " ", p)
    attrs = " ".join(re.findall(r'(?:alt|title|content|aria-label|placeholder)="([^"]*)"', p))
    import html as _h
    return _h.unescape(re.sub(r"<[^>]+>", " ", p) + " " + attrs)


def rec(rid, name, build, live=True, players=3, tags=(), core="azerothcore", port=40100):
    return wp.clean_listing_record({"schema": 1, "name": name, "state": "live" if live else "offline", "tags": list(tags),
        "profile": {"build": build, "core": core, "port": port, "address": "relay.example"},
        "community": {"realmId": rid, "relay": "relay.example", "claimed": True, "score": 5,
                      "lastHeartbeat": {"online": live, "players": players, "bots": 0}}})


listing = [rec("aaaaaaaaaaaaaaaa", "WoW 1.12.1 Classic", 5875, tags=["blizzlike"], core="vmangos"),
           rec("bbbbbbbbbbbbbbbb", "Outland 2.4.3 Blizzard Fans", 8606, core="cmangos", port=40101),
           rec("cccccccccccccccc", "Lich King 3.3.5a (12340)", 12340, port=40102),
           rec("dddddddddddddddd", "Warcraft Nights", 12340, live=False, port=40103)]
with wp._listing_lock:
    wp._listing.update(realms=[r for r in listing if r], ok=True, fetched=True, at=time.monotonic() + 1e6, when=time.time())
json.dump({"format": 1, "posts": [{"id": "v", "date": "2026-10-30", "tag": "Patch 2.4.3", "title": "Launcher 0.5 for 1.12.1 and 3.3.5a",
                                   "items": ["Finds your own 1.12.1, 2.4.3 and 3.3.5a clients", "Build 12340 realms play in the browser"]}]},
          open(os.path.join(os.environ["WU_LEYLINE_DIR"], "news.json"), "w"))
idx = json.load(open(os.path.join(HUBDIR, "community-index.json")))
kept = json.dumps(idx)
e0 = idx["entries"][2]
e0["summary"] = "An addon for 1.12.1 and 3.3.5a clients (5875 / 12340)."
e0["description"] = "Works on 2.4.3 too. Version 3.3.5a build."
e0["needs"] = "A 3.3.5a client"
json.dump(idx, open(os.path.join(HUBDIR, "community-index.json"), "w"))


class BrandWorkshop(FakeWorkshop):
    def all_json(self):
        return json.dumps({"projects": [
            {"id": "mod:bags", "source": "packaged", "name": "WoW 1.12.1 Bags", "category": "addons", "builds": ["1.12", "3.3.5a"],
             "description": "A World of Warcraft 3.3.5a addon for Wrath of the Lich King (12340), made by Blizzard fans.",
             "author": "Bag Maker", "licence": "MIT", "repo": "", "page": "https://play.example/wrath/mods/bags",
             "download": "https://play.example/wrath/mods/bags/download", "sha256": "a" * 64, "kind": "ui"}]})


HB.hub.portal = lambda name: BrandWorkshop() if name == "workshop" else real(name)
every = ["", "/realms", "/realms?client=own", "/realms?client=browser&now=1", "/realms?build=1.12.1", "/modes", "/news",
         "/catalog", "/catalog?build=1.12", "/catalog?build=3.3.5a&sort=name", "/catalog?q=bags", "/creators", "/beacon", "/forge", "/agents",
         "/submit", "/p/mod-bags", "/p/" + e0["id"].replace(":", "-"), "/p/theme-night-sky"]
for path in every:
    st, _, b = req("/wrath/leyline-preview" + path)
    found = NOPE.findall(shown(b.decode()))
    check(f"no client numbers or game name: {path or '/'} ({st})", st == 200 and not found, found[:6])
st, _, b = req("/wrath/leyline-preview/submit", "POST", "repo=https%3A%2F%2Fgithub.com%2Fa%2Fb&build=9.9&category=tools", ip="10.4.4.4")
check("no client numbers or game name: the submit form's error page", st == 400 and not NOPE.findall(shown(b.decode())))
front = req("/wrath/leyline-preview")[2].decode()
bags = req("/wrath/leyline-preview/p/mod-bags")[2].decode()
rl = req("/wrath/leyline-preview/realms")[2].decode()
check("neutralised, not dropped: the realms, the mod and the news are still there in words",
      "<b>Classic</b>" in rl and "Outland Fans" in rl or "Outland" in rl)
check("realm rows: how it plays in words, the filter by those words",
      "Plays in your browser · AzerothCore" in rl and "Bring your own game client · vMaNGOS" in rl and "Original rules" in rl
      and 'href="/wrath/leyline-preview/realms?client=browser">Plays in browser</a>' in rl
      and 'href="/wrath/leyline-preview/realms?client=own">Own client</a>' in rl
      and '<option value="browser">Plays in browser</option><option value="own">Own client</option>' in front
      and 'data-client="own"' in front)
own = req("/wrath/leyline-preview/realms?client=own")[2].decode()
check("realm filter: Own client is every realm the browser can't play", "<b>Classic</b>" in own and "Leyline Sample Hangout" not in own
      and 'data-client="browser"' not in own)
check("item page: the mod in words", "<h1>Bags</h1>" in bags and "An addon for Wrath" in bags and "Classic era, Third era" in bags
      and "<title>Bags · Leyline</title>" in bags, re.sub(r"<style.*?</style>", "", bags, flags=re.S)[:2500])
news = req("/wrath/leyline-preview/news")[2].decode()
check("news: the post kept, its numbers gone", "<h2>Launcher 0.5</h2>" in news and "Finds your own clients" in news, news[-600:])
check("the launcher feed still has the builds (data, not text)", json.loads(req("/wrath/leyline/catalog.json")[2])["builds"][:3] == ["1.12", "2.4.3", "3.3.5a"])
check("neutral(): the helper", HB.neutral("Vanilla WoW 1.12.1 addon (3.3.5a)") == "Vanilla addon"
      and HB.neutral("TrinityCore (3.3.5 branch)") == "TrinityCore" and HB.neutral("Uses Lua 5.1") == "Uses Lua 5.1"
      and HB.neutral("A WoW 1.12.1 addon for World of Warcraft") == "An addon for the game")
HB.hub.portal = real
open(os.path.join(HUBDIR, "community-index.json"), "w").write(kept)
with wp._listing_lock:
    wp._listing.update(realms=[], ok=False, fetched=False, at=-1e9)

# ---------------------------------------------------------------- the front page's new parts (owner 2026-10-30)
def realm_rec(rid, name, build=12340, players=0, tags=(), tagline="", new=False, port=40200, live=True):
    return wp.clean_listing_record({"schema": 1, "name": name, "tagline": tagline, "state": "live" if live else "offline",
        "tags": list(tags), "profile": {"build": build, "core": "azerothcore", "port": port, "address": "relay.example"},
        "community": {"realmId": rid, "relay": "relay.example", "claimed": True, "score": 5, "new": new,
                      "lastHeartbeat": {"online": live, "players": players, "bots": 0}}})


RIDS = ["oldoldoldoldoldo", "busybusybusybusy", "plainplainplainp", "quietquietquieta"]
listing = [realm_rec(RIDS[0], "Old Days", 5875, 12, ["blizzlike", "pvp"], "The old rules, the old days.", port=40201),
           realm_rec(RIDS[1], "Busy Den", 12340, 30, ["pvp"], "Fast levels, world PvP every evening.", port=40202),
           realm_rec(RIDS[2], "Plain Field", 12340, 0, ["rp"], "Slow roleplay on quiet fields.", new=True, port=40203),
           realm_rec(RIDS[3], "Quiet Shore", 12340, 2, [], "", port=40204),
           realm_rec("offofoffofoffofo", "Sleepy Hollow", 12340, 0, live=False, port=40205)]
with wp._listing_lock:
    wp._listing.update(realms=[r for r in listing if r], ok=True, fetched=True, at=time.monotonic() + 1e6, when=time.time())
json.dump({"format": 1, "posts": [
    {"id": "n1", "date": "2026-10-30", "tag": "Realms", "title": "Realm hopping in one click", "items": ["Hop without signing in again"]},
    {"id": "n2", "date": "2026-10-30", "tag": "Oops", "title": "WoW night", "items": ["dropped"]},
    {"id": "n3", "date": "2026-10-29", "tag": "Launcher", "title": "Launcher 0.6 for 3.3.5a", "items": ["Finds your own 1.12.1 client"]},
    {"id": "n4", "date": "2026-10-28", "tag": "Workshop", "title": "Hot, rising and top", "items": ["Rate what you play"]},
    {"id": "n5", "date": "2026-10-20", "tag": "Old", "title": "The fourth one", "items": []}]},
    open(os.path.join(os.environ["WU_LEYLINE_DIR"], "news.json"), "w"))
pool = [i for i in HB.hub.items() if i["source"] != "theme"]
HOT = sorted(pool, key=lambda i: i["name"].lower())[3]          # some item that isn't the best score
AUTH = {i["author"] for i in pool}


class FakeStore:
    def ranked(self, items, sort="hot"):
        rest = [i for i in items if i["id"] != HOT["id"]]
        order = [i for i in items if i["id"] == HOT["id"]] + sorted(rest, key=lambda i: (-float(i.get("score") or 0), i["name"].lower()))
        return [(i, {"installs": {"all": 9, "d30": 500 if i["id"] == HOT["id"] else 1, "d7": 0, "prev7": 0}}) for i in order]

    def metrics(self, items):
        return {i["id"]: {"installs": {"all": 0, "d30": 0}, "rating": {"avg": None, "n": 0}} for i in items}


class FakeRank:
    store = FakeStore()
    KINDS = ()
    SORT_LABELS = []
    KIND_LABELS = []
    RANK_CSS = ""

    @staticmethod
    def installable(i):
        return i["id"] == HOT["id"]


HK = {"on": False}
WHO = {"v": None}


class FakeSocial:
    @staticmethod
    def cookie_user(h):
        return WHO["v"]


def portal_with(name):
    if name == "hub_rank":
        return FakeRank
    if name == "herokey_on":
        return lambda: HK["on"]
    if name == "social":
        return FakeSocial
    return real(name)


HB.hub.portal = portal_with
fp = req("/wrath/leyline-preview")[2].decode()
order = [fp.find(x) for x in ('class="hb-hero"', 'class="hb-tick"', 'id="realms"', 'class="hb-how', 'class="hb-nums', 'id="features"',
                              'id="f-agents"', 'id="hosted"', 'id="mod-week"', 'id="herokey"', 'id="creators-top"', 'id="news"',
                              'id="status"', 'id="community"')]
check("front page order: hero, ticker, realms, how it works, numbers, features, hosted, mod of the week, Hero Key, creators, "
      "news, status, spotlight", -1 not in order and order == sorted(order), order)
tick = re.search(r'<section class="hb-tick".*?</section>', fp, re.S).group(0)
plain = re.search(r'<ul class="hb-tick-l">(.*?)</ul>', tick, re.S).group(1)
lis = re.findall(r"<li[^>]*>(.*?)</li>", plain)
home_li = [x for x in lis if "Busy Den" not in x and "Old Days" not in x and "Quiet Shore" not in x and "New realm" not in x]
check("ticker: who is playing where, from the realm list's rows, most players first, then new realms",
      [x for x in lis if x not in home_li] == ['<b class="hb-tn">30</b> playing on Busy Den', '<b class="hb-tn">12</b> playing on Old Days',
                                              '<b class="hb-tn">2</b> playing on Quiet Shore', "New realm: Plain Field"]
      and len(home_li) <= 1 and all(re.fullmatch(r'<b class="hb-tn">3</b> (?:playing on|in the) [^<]+', x) for x in home_li)
      and "Sleepy Hollow" not in tick and f'data-tick="{RIDS[1]}"' in plain and 'data-tick="home"' in plain, lis)
check("ticker: one plain list for screen readers, the looping copy aria-hidden, a heading",
      tick.count('<ul class="hb-tick-l">') == 1 and tick.count('<ul class="hb-tick-l dup" aria-hidden="true">') == 1
      and '<h2 id="hb-tick-h" class="hb-vh">Live on the network</h2>' in tick)
check("ticker: a slow loop, paused on hover and focus, still and wrapped with reduced motion",
      ".hb-tick-run{display:flex;width:max-content;animation:hb-tick 48s linear infinite}" in fp
      and ".hb-tick:is(:hover,:focus-within) .hb-tick-run{animation-play-state:paused}" in fp
      and re.search(r"prefers-reduced-motion:reduce\)\{.*?\.hb-tick-l\{flex-wrap:wrap.*?\.hb-tick-l\.dup\{display:none\}", fp, re.S))
check("ticker: the 30 s live update refreshes its counts (same JSON, text only)", "[data-tick=" in HB.HUB_JS and "tk(c.realmId,h.players)" in HB.HUB_JS
      and 'tk("home",s.players)' in HB.HUB_JS)
nums = re.findall(r'<b class="hb-num" data-count="(\d+)">(\d+)</b><span>([^<]+)</span>', fp)
check("numbers: realms, players, mods, the final values in the page (no script, reduced motion)", [n[2] for n in nums] == [
      "realms online", "players right now", "mods, addons and tools"] and all(a == b for a, b, _ in nums)
      and int(nums[2][0]) == len(pool) and int(nums[1][0]) >= 44, nums)
check("numbers: counted up once by the script, only below the fold, never with reduced motion",
      re.search(r"if\(!still&&\"IntersectionObserver\" in window\)\{\s*var cio=", HB.HUB_JS) and 'n.textContent="0";cio.observe(n)' in HB.HUB_JS
      and "getBoundingClientRect().top>innerHeight){n.textContent" in HB.HUB_JS)
check("ley line: a faint thread down the feature sections, drawn on scroll by script, drawn whole without it or with reduced motion,"
      " never takes a click, hidden on narrow screens",
      '<svg class="hb-thread" viewBox="0 0 40 1000" preserveAspectRatio="none" aria-hidden="true" focusable="false">' in fp
      and "pointer-events:none;z-index:2}" in fp and ".hb-js .hb-thread.draw path{stroke-dasharray:1" in fp
      and ".hb-thread path{stroke-dasharray:none!important}" in fp and "@media (max-width:1150px){.hb-thread,.hb-fs::before{display:none}}" in fp
      and 'if(th&&feats&&!still){th.classList.add("draw")' in HB.HUB_JS)
check("screenshots: tilt toward the cursor with a glow, fine pointers and motion only",
      'if(!still&&window.matchMedia&&matchMedia("(pointer:fine)").matches){d.querySelectorAll(".hb-shot")' in HB.HUB_JS
      and ".hb-shot.tilt::after{opacity:1}" in fp and ".hb-shot{transform:none!important}" in fp)
pv = re.search(rf'<li class="hb-rl pv" data-rid="{RIDS[1]}".*?</li>', fp, re.S)
check("realm rows: a preview with the tagline and tags on hover and focus, laid over (no layout shift)",
      pv and '<div class="hb-rl-pv" role="note"><p>Fast levels, world PvP every evening.</p><p class="hb-rl-pt"><span>PvP</span></p></div>' in pv.group(0)
      and ".hb-rl-pv{position:absolute;" in fp and ".hb-rl.pv:is(:hover,:focus-within) .hb-rl-pv{visibility:visible" in fp
      and re.search(rf'<li class="hb-rl" data-rid="{RIDS[3]}"', fp), pv.group(0)[-400:] if pv else "")
motw = re.search(r'<section class="hb-motw hb-rv" id="mod-week".*?</section>', fp, re.S).group(0)
check("mod of the week: the top Hot item, its author, one line, Install with Leyline and View",
      f'href="leyline://install/{HOT["id"]}">Install with Leyline</a>' in motw and f'href="/wrath/leyline-preview/p/{HOT["id"].replace(":", "-")}">View</a>' in motw
      and f">{html.escape(HB.neutral(HOT['name']))}</h2>" in motw and f"by {html.escape(HB.neutral(HOT['author']))}" in motw and "Mod of the week" in motw, motw)
posters = re.findall(r'<article class="hb-poster" style="--h1:(\d+);--h2:(\d+);--a:(\d+)deg;--x:(\d+)%;--y:(\d+)%;--r:(\d+)deg">(.*?)</article>', fp, re.S)
names = [re.search(r"<h3>([^<]+)</h3>", p[6]).group(1) for p in posters]
check("hosted by the community: up to three live community realms as posters (not ours, not offline)",
      names == ["Busy Den", "Old Days", "Quiet Shore"] or (len(names) == 3 and "Sleepy Hollow" not in names and "Leyline Sample Hangout" not in names), names)
again = re.findall(r'<article class="hb-poster" style="([^"]+)"', req("/wrath/leyline-preview")[2].decode())
check("posters: a backdrop made from each realm's id (the same every time, different per realm), the mark only",
      again == re.findall(r'<article class="hb-poster" style="([^"]+)"', fp) and len(set(again)) == len(again)
      and "url(/wrath/art/leyline-crystal-256.webp)" in fp and "TODO(owner): hosts uploading their own poster image" in fp)
bd = next(p[6] for p in posters if "Busy Den" in p[6])
od = next((p[6] for p in posters if "Old Days" in p[6]), "")
check("posters: name, tagline, tags, players, Play in the browser or Open in launcher",
      "<b>30</b> playing" in bd and "Fast levels, world PvP every evening." in bd and "<span>PvP</span>" in bd
      and f'href="/wrath?go=r:{RIDS[1]}"' in bd and f'href="leyline://realm/{RIDS[1]}">Open in launcher' in bd
      and (not od or ("go=r:" not in od and "Open in launcher" in od)))
newsb = re.search(r'<section class="hb-sec hb-rv" id="news".*?</section>', fp, re.S).group(0) if 'id="news"' in fp else ""
if wp.admin is not None:
    check("news: the latest three posts, brand-word posts dropped, numbers taken out, read-only links to the news page",
          re.findall(r"<b>([^<]+)</b>", newsb) == ["Realm hopping in one click", "Launcher 0.6", "Hot, rising and top"]
          and "WoW" not in newsb and "Finds your own client" in newsb and newsb.count('href="/wrath/leyline-preview/news"') == 4
          and "<form" not in newsb, newsb)
hk = re.search(r'<section class="hb-hk hb-rv" id="herokey".*?</section>', fp, re.S).group(0)
check("Hero Key (flag off): one key, every realm, Coming soon, a key moving between three realm cards",
      "One key, every realm" in hk and "Coming soon" in hk and "Available now" not in hk and hk.count('<span class="hb-hk-c">') == 3
      and 'class="hb-hk-key"' in hk and "@keyframes hb-key" in fp)
HK["on"] = True
hk_on = re.search(r'<section class="hb-hk hb-rv" id="herokey".*?</section>', req("/wrath/leyline-preview")[2].decode(), re.S).group(0)
check("Hero Key (flag on): available now, no Coming soon", "Available now" in hk_on and "Coming soon" not in hk_on
      and 'href="/wrath/leyline-preview/realms">Pick a realm' in hk_on)
HK["on"] = False
crs = re.findall(r'<a class="hb-cr" href="/wrath/leyline-preview/catalog\?q=([^"]+)">.*?<b>([^<]+)</b><small>([^<]+)</small><i>Top: ([^<]+)</i>',
                 re.search(r'id="creators-top".*?</section>', fp, re.S).group(0), re.S)
check("creator spotlight: up to four authors of the top mods, with counts, linking to their work in the catalog",
      1 <= len(crs) <= 4 and HB.neutral(HOT["author"]) == html.unescape(crs[0][1]) and all(re.match(r"\d+ mods? in the top list", c[2]) for c in crs)
      and re.search(r"· [5-9]\d\d installs this month$", crs[0][2]) and len({c[1] for c in crs}) == len(crs)
      and all(urllib.parse.unquote_plus(html.unescape(c[0])) in AUTH for c in crs), crs)
foot = re.search(r'<footer class="hb-foot">.*?</footer>', fp, re.S).group(0)
st_words = re.findall(r'<em class="(ok|bad)">', re.search(r'id="status".*?</section>', fp, re.S).group(0))
want = "ok" if all(w == "ok" for w in st_words) else "warn" if "ok" in st_words else "bad"
check(f"footer: the status dot ({want}), linking to Platform Status, pulsing only when all is OK",
      re.search(rf'<a class="hb-health {want}" href="/wrath/leyline-preview#status"><span class="hb-hdot" aria-hidden="true"></span>', foot)
      and ".hb-health.ok .hb-hdot{animation:hb-pulse" in fp and ".hb-health.warn .hb-hdot{background:#f0b54a}" in fp, (want, foot[:300]))
check("realm list: each row shows its client version as a chip (the one place the hub names a build), an icon and a fill bar",
      re.search(r'<li class="hb-rl home[^"]*" data-home="1"[^>]*><span class="hb-rl-ic home" style="--h:\d+" aria-hidden="true"><svg class="hb-crest"', fp)
      and '<span class="hb-ver" title="Game client version">3.3.5a</span>' in fp and 'class="hb-rl-bar"' in fp)
check("the front page with all of this: no client numbers or game names", not NOPE.findall(shown(fp)), NOPE.findall(shown(fp))[:6])
check("still one script, under the nonce, reading only this site's JSON", fp.count("<script") == 1
      and re.findall(r'json\("([^"]+)"\)', HB.HUB_JS) == ["/wrath/realms.json", "/wrath/status.json"] and "innerHTML" not in HB.HUB_JS)
# signed in: the account chip instead of Sign In (the site's session, through the portal's social module)
WHO["v"] = ("BRAN", "Bran")
c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
c.request("GET", "/wrath/leyline-preview/creators", headers={"Cookie": "wr_session=abc", "X-Forwarded-For": "10.9.0.7"})
signed = c.getresponse().read().decode()
check("header signed in: the account chip, no Sign In", '<a class="hb-acct" href="/wrath/account" aria-label="Your account: Bran">' in signed
      and 'class="hb-signin"' not in signed)
check("header signed out (no cookie): Sign In, the social module never asked", 'class="hb-signin"' in req("/wrath/leyline-preview/creators")[2].decode())
WHO["v"] = None

# ---------------------------------------------------------------- the gallery (owner 2026-10-30: screenshots and featured mods)
GALS = re.compile(r'<figure class="hb-gt( [a-z ]+)?" data-k="(game|mods|launcher)" id="([^"]+)">(.*?)</figure>', re.S)


class ShotWorkshop(FakeWorkshop):
    """A Workshop whose packaged mod has a screenshot (all.json doesn't list screenshots: the hub asks mod())."""
    def mod(self, mid):
        return {"id": mid, "screenshots": ["one.png"]} if mid == "pings" else None


def portal_gal(name):
    return ShotWorkshop() if name == "workshop" else portal_with(name)


HB.hub.portal = portal_gal
check("gallery: a game shot missing from the art folder is never a broken image (the flat tile instead)",
      'id="g-leyline"' in req("/wrath/leyline-preview/gallery")[2].decode() and not os.path.isdir(wp.ART_DIR))
check("modes page: a mode's key art missing from the art folder is no picture at all (never a broken image)",
      'id="mode-azeroth-survivors"' in req("/wrath/leyline-preview/modes")[2].decode()
      and 'class="hb-mode-art"' not in req("/wrath/leyline-preview/modes")[2].decode())
check("featured modpack: missing from the art folder, no section and no tile", 'id="featured-mod"' not in req("/wrath/leyline-preview")[2].decode())
ART_WAS = wp.ART_DIR
wp.ART_DIR = os.path.join(HERE, "www-files", "art")
fp = req("/wrath/leyline-preview")[2].decode()
# the front page no longer has the gallery section (owner 2026-10-30: "remove gallery at bottom"); its place near the foot
# is the sliding strip of mod and in-game pictures ("this place should show sliding gallery of mod images")
check("front page: no gallery section, no Browse by category, no For creators / Host a Beacon boxes",
      'id="gallery"' not in fp and "Browse by category" not in fp and 'class="hb-two' not in fp)
ms = re.search(r'<section class="hb-ms hb-rv" aria-labelledby="hb-ms-h">.*?</section>', fp, re.S)
ms = ms.group(0) if ms else ""
ms_imgs = re.findall(r'<li><a class="hb-ms-t" href="[^"]+"(?: rel="noopener noreferrer")?><img src="([^"]+)" alt="[^"]+" width="\d+" height="\d+" loading="lazy"', ms)
check("mod strip: near the foot (after the spotlight, before the fine print), real pictures only (mods and in game, no launcher "
      "shots, no drawn tiles), twice for the loop with the copy hidden from screen readers",
      ms and fp.find('id="community"') < fp.find('class="hb-ms ') < fp.find('class="hb-fine"') and len(ms_imgs) >= 6
      and not any("leyline-ui-" in u for u in ms_imgs) and '<ul class="hb-ms-l dup" aria-hidden="true" inert>' in ms
      and ms.count("<li>") == 2 * ms.split('class="hb-ms-l dup"')[0].count("<li>"), ms_imgs)
check("mod strip: stops on hover and focus, does not move with reduced motion",
      ".hb-ms:hover .hb-ms-run,.hb-ms:focus-within .hb-ms-run{animation-play-state:paused}" in fp
      and "@media (prefers-reduced-motion:reduce){.hb-ms{overflow-x:auto!important}.hb-ms-run{animation:none" in fp)
check("mod strip: clipped to the page, so the sliding copy never widens it", ".hb-ms{margin:34px 0 18px;overflow:hidden;overflow:clip;max-width:100%}" in fp)
gsec = req("/wrath/leyline-preview/gallery")[2].decode()
tiles = GALS.findall(gsec)[:12]
kinds = [t[1] for t in tiles]
check("gallery: the first tiles are in game, mods and launcher taken in turn", len(tiles) >= 8
      and kinds[:6] == ["game", "mods", "launcher"] * 2 and {"game", "mods", "launcher"} <= set(kinds), kinds)
check("gallery: the first tile is the big featured modpack shot, with its authors' credit and a link out (no Install)",
      tiles and "big" in tiles[0][0] and tiles[0][2] == "g-coa-ultrahd"
      and 'src="/wrath/art/leyline-shot-coa-ultrahd.webp"' in tiles[0][3] and "<i>Screenshot: the modpack&#x27;s authors</i>" in tiles[0][3]
      and f'<a class="hb-gt-i" href="{html.escape(HB.FEATURED_MOD["url"])}" rel="noopener nofollow ugc" target="_blank">See the modpack</a>' in tiles[0][3]
      and "Install" not in tiles[0][3] and "<small>Featured mod</small>" in tiles[0][3], tiles[0][:3] if tiles else "")
check("gallery: then the in-game shots, the hangout first", [t[2] for t in tiles if t[1] == "game"][:2] == ["g-coa-ultrahd", "g-dalaran"])
mt = [t for t in tiles if t[1] == "mods"]
check("gallery: the first mod is the Mod of the week (top Hot), then the rest of Hot",
      mt and mt[0][2] == "m-" + HOT["id"].replace(":", "-") and "Mod of the week" in mt[0][3], [t[2] for t in mt])
check("gallery: every mod tile has Install with Leyline (leyline://install/<id>), View and the author's credit", mt and all(
      re.search(r'<a class="hb-gt-i" href="leyline://install/(?:mod|link|theme):[a-z0-9-]+">(?:Install with|Open in) Leyline</a>'
                r'<a class="hb-gt-v" href="/wrath/leyline-preview/p/[a-z0-9-]+">View</a>', t[3]) and re.search(r"<i>by [^<]+</i>", t[3])
      and 'class="hb-gt-x" hidden' not in t[3] for t in mt))
check("gallery: the Mod of the week installs with Leyline", f'href="leyline://install/{HOT["id"]}">Install with Leyline</a>' in mt[0][3])
gal = req("/wrath/leyline-preview/gallery")[2].decode()
pings = next((t for t in GALS.findall(gal) if t[2] == "m-mod-pings"), None)
check("gallery page: a Workshop mod with its own screenshot shows it (from the Workshop, same origin), with alt text and size",
      pings and re.search(r'<img src="/wrath/mods/pings/shot/0" alt="A screenshot of Pings, an addon by WrathUnleashed" width="640" height="360" '
                          r'loading="lazy" decoding="async">', pings[3]), pings[3][:300] if pings else "")
gen = [t for t in GALS.findall(gal) if t[1] == "mods" and "<img" not in t[3]]
check("gallery: a mod without our screenshot gets a tile drawn from its id (gradient, initial, kind icon), labelled",
      gen and all(re.search(r'<span class="hb-gt-art gen" style="--h1:\d+;--h2:\d+;--a:\d+deg" aria-hidden="true"><b>.</b><svg', t[3])
                  and re.search(r'<a class="hb-gt-a" href="[^"]+" data-lb aria-label="[^"]+">', t[3]) for t in gen))
imgs = re.findall(r"<img\b[^>]*>", gal + gsec)
check("gallery: every picture has alt text, a width and a height, and loads lazily", imgs and all(
      re.search(r'alt="[^"]{12,}"', i) and re.search(r'width="\d+" height="\d+"', i) and 'loading="lazy"' in i
      for i in re.findall(r'<img\b[^>]*>', "".join(t[3] for t in GALS.findall(gal + gsec)))), imgs[:3])
tiles_all = GALS.findall(gal)
check("gallery page: every eligible picture (the featured modpack and 4 in game, 4 launcher, the mods) and no game shot missing",
      sum(1 for t in tiles_all if t[1] == "game") == 5 and sum(1 for t in tiles_all if t[1] == "launcher") == 4
      and sum(1 for t in tiles_all if t[1] == "mods") >= 4 and 'data-gal="all"' in gal, [t[1] for t in tiles_all])
check("gallery: without script each tile is a link: the image itself, or the mod's page", all(
      re.search(r'<a class="hb-gt-a" href="(/wrath/art/leyline-(?:shot|ui)-[a-z-]+\.webp|/wrath/leyline-preview/p/[a-z0-9-]+|/wrath)" data-lb', t[3])
      for t in tiles_all))
chips = re.findall(r'<a class="hb-chip( on)?" href="([^"]+)" data-f="([a-z]*)"(?: aria-current="true")?>([^<]+)</a>', gsec)
check("gallery filters: All, In game, Mods, Launcher, links to the gallery page (?f=) that work without script",
      [(c[1], c[3]) for c in chips] == [("/wrath/leyline-preview/gallery", "All"), ("/wrath/leyline-preview/gallery?f=game", "In game"),
                                        ("/wrath/leyline-preview/gallery?f=mods", "Mods"), ("/wrath/leyline-preview/gallery?f=launcher", "Launcher")]
      and chips[0][0] == " on", chips)
for f in ("game", "mods", "launcher"):
    g = req("/wrath/leyline-preview/gallery?f=" + f)[2].decode()
    ks = [t[1] for t in GALS.findall(g)]
    check(f"gallery ?f={f}: only those tiles, its chip on, no in-place filter", ks and set(ks) == {f} and 'data-gal="one"' in g
          and re.search(rf'<a class="hb-chip on" href="/wrath/leyline-preview/gallery\?f={f}" data-f="{f}" aria-current="true">', g), ks)
check("gallery ?f=<junk>: everything", [t[1] for t in GALS.findall(req("/wrath/leyline-preview/gallery?f=nope")[2].decode())] == [t[1] for t in tiles_all])
hd, nav, labels, on = header_of(gal)
check("gallery page: the hub header (Gallery is no longer in the menu), the sub-nav",
      labels == NAV_ORDER and "/gallery" not in nav
      and '<a href="/wrath/leyline-preview/gallery" aria-current="page" class="on">Gallery</a>' in gal)
check("gallery: script filters in place and opens the lightbox (Esc, arrows, Tab kept inside, focus back to the tile), no innerHTML",
      all(x in HB.HUB_JS for x in ('d.querySelectorAll("[data-gal]")', 'ev.key==="Escape"', 'ev.key==="ArrowLeft"', 'ev.key==="ArrowRight"',
                                    'ev.key==="Tab"', 'aria-modal', "if(a)a.focus()", 'if(g.getAttribute("data-gal")!=="all")return;'))
      and "innerHTML" not in HB.HUB_JS and HB.HUB_JS.find('d.querySelectorAll("[data-gal]")') < HB.HUB_JS.find("if(!rows.length||!window.fetch)return;"))
check("gallery: hover zoom and caption reveal, none of it moving with reduced motion; uniform tiles while filtered",
      ".hb-gt:is(:hover,:focus-within) :is(.hb-gt-a img,.hb-gt-a .hb-gt-art){transform:scale(1.05)}" in fp
      and "@media (hover:none){.hb-gt-c{opacity:1;transform:none}}" in fp
      and re.search(r"prefers-reduced-motion:reduce\)\{.*?\.hb-gt :is\(img,\.hb-gt-art\),\.hb-lb-in\{transform:none!important\}", fp, re.S)
      and ".hb-gal.flt .hb-gt{grid-column:auto;grid-row:auto}" in fp)
SRC = re.compile(r'(?:src|href)="([^"]+\.(?:webp|png|jpe?g|gif|avif|svg))"|<img\b[^>]*\bsrc="([^"]+)"|url\(([^)]+)\)', re.I)
HB.hub.portal = lambda name: None if name == "hub_rank" else portal_gal(name)
cat = req("/wrath/leyline-preview/catalog")[2].decode()
catf = req("/wrath/leyline-preview/catalog?cat=addons")[2].decode()
HB.hub.portal = portal_gal
third = [u for page in (fp, gal, cat) for m in SRC.findall(page) for u in m if u and not u.startswith("#") and not (u.startswith("/") and not u.startswith("//"))]
check("no third-party pictures anywhere on the hub: every image, image link and CSS url() is our own path", not third, third[:5])
check("gallery: CSP img-src 'self' (the browser would refuse another site's picture anyway)",
      "img-src 'self'" in req("/wrath/leyline-preview/gallery")[1].get("content-security-policy", ""))
check("gallery: no client numbers or game names in captions, alt text or labels", not NOPE.findall(shown(gal)) and not NOPE.findall(shown(gsec))
      and not BANNED.findall(visible(gal)), NOPE.findall(shown(gal))[:5])
strip = re.search(r'<section class="hb-feat-s".*?</section>', cat, re.S)
check("catalog: a Featured strip of the gallery's mod tiles (plain links, no script), only unfiltered on page 1",
      strip and 1 <= len(GALS.findall(strip.group(0))) <= 4 and all(t[1] == "mods" for t in GALS.findall(strip.group(0)))
      and "data-lb" not in strip.group(0) and "<script" not in cat
      and 'class="hb-feat-s"' not in catf)
# the game data killswitch: no game picture at all, one flat Leyline tile (the mark) in their place
FLAG = os.path.join(DATA, "gamedata-off-test")
os.environ["WU_GAMEDATA_FLAG"] = FLAG
open(FLAG, "w").close()
fk = req("/wrath/leyline-preview")[2].decode()
gk = req("/wrath/leyline-preview/gallery?f=game")[2].decode()
fk_tiles = GALS.findall(req("/wrath/leyline-preview/gallery")[2].decode())
check("killswitch on: no in-game screenshot anywhere on the front page or the gallery", "leyline-shot-" not in fk
      and "leyline-shot-" not in req("/wrath/leyline-preview/gallery")[2].decode() and req("/wrath/art/leyline-shot-city.webp")[0] == 410)
check("killswitch on: one flat Leyline tile with the mark instead, still In game, Play in your browser",
      [t[2] for t in fk_tiles if t[1] == "game"] == ["g-leyline"] and [t[2] for t in GALS.findall(gk)] == ["g-leyline"]
      and re.search(r'<figure class="hb-gt[a-z ]* flat" data-k="game" id="g-leyline"><a class="hb-gt-a" href="/wrath" data-lb aria-label="[^"]+">'
                    r'<span class="hb-gt-art flat" aria-hidden="true"><span class="ly-spin slow"', gk)
      and fk_tiles[1][1] == "mods" and fk_tiles[2][1] == "launcher", [t[:3] for t in fk_tiles][:4])
check("killswitch on: no featured modpack section and no modpack tile; its picture answers 410",
      'id="featured-mod"' not in fk and "g-coa-ultrahd" not in fk and req("/wrath/art/leyline-shot-coa-ultrahd.webp")[0] == 410)
check("killswitch on: Game modes shows the launcher's Modes page instead of the Minigolf loop (and the loop answers 410)",
      "<video" not in fk and re.search(r'id="f-modes".*?<img src="/wrath/art/leyline-ui-modes\.webp"', fk, re.S)
      and req("/wrath/art/leyline-shot-minigolf.mp4")[0] == 410 and req("/wrath/art/leyline-shot-minigolf.webm")[0] == 410)
os.remove(FLAG)
os.environ.pop("WU_GAMEDATA_FLAG")
check("killswitch off again: the shots are back", "leyline-shot-dalaran.webp" in req("/wrath/leyline-preview")[2].decode())

# ---------------------------------------------------------------- the featured modpack (owner 2026-10-30: "under this show a
# screenshot ... the CoA ultra hd modpack feature")
coa = re.search(r'<section class="hb-coa hb-rv" id="featured-mod".*?</section>', fp, re.S)
check("featured mod: on the front page right under the numbers, before the feature sections",
      coa and fp.find('class="hb-nums') < fp.find('id="featured-mod"') < fp.find('id="features"')
      and re.search(r'</section><section class="hb-coa hb-rv" id="featured-mod"', fp)
      and fp[fp.find('class="hb-nums'):fp.find('id="featured-mod"')].count("<section") == 1)
coa = coa.group(0) if coa else ""
check("featured mod: label, title, the screenshot (served, sized, alt), a TODO for the owner's copy",
      '<p class="hb-coa-k"><span aria-hidden="true"></span>Featured mod</p>' in coa and "Conquest of Azeroth: UltraHD</h2>" in coa
      and re.search(r'<img src="/wrath/art/leyline-shot-coa-ultrahd\.webp" alt="[^"]{30,}" width="845" height="577" loading="lazy"', coa)
      and "leyline-shot-coa-ultrahd.webp" in wp.ART_TYPES and "leyline-shot-coa-ultrahd.webp" in wp.GAMEDATA_ART
      and os.path.isfile(os.path.join(HERE, "www-files", "art", "leyline-shot-coa-ultrahd.webp")) and "TODO(owner)" in coa)
check("featured mod: the external note and the credit, word for word",
      '<p class="hb-coa-n">External download, made and hosted by its authors; not checked or hosted by Leyline</p>' in coa
      and '<p class="hb-coa-cr">Screenshot: the modpack&#x27;s authors</p>' in coa)
# a slider since 2026-10-30 ("a sliding preview too of the best latest mods"): the modpack is the first slide
coa_slides = re.split(r'<div class="hb-coa-s(?: mod)?"', coa)[1:]
coa1 = coa_slides[0] if coa_slides else ""
links = re.findall(r'<a ([^>]*)>(.*?)</a>', coa1, re.S)
check("featured mod: the first slide has one link out, See the modpack (noopener nofollow ugc, a new tab), no Install, nothing hosted here",
      len(links) == 1 and f'href="{html.escape(HB.FEATURED_MOD["url"])}"' in links[0][0] and 'rel="noopener nofollow ugc"' in links[0][0]
      and 'target="_blank"' in links[0][0] and links[0][1].startswith("See the modpack")
      and not re.search(r"(?i)install|leyline://|download\"", coa1.replace("External download", "")) and "/wrath/mods/" not in coa1)
more = coa_slides[1:]
check("featured slider: then up to five of the best mods with a picture, each a link to its own page here (no Install, no link out)",
      len(coa_slides) <= 6 and all(re.search(r'<a class="hb-cta sm" href="/wrath/[a-z-]+/p/[^"]+">See the mod</a>', x) for x in more)
      and not any(re.search(r"(?i)leyline://|target=\"_blank\"", x) for x in more))
check("featured slider: dots and arrows only with the script (hidden until then); a sideways snap scroll without it",
      ('<div class="hb-coa-nav" hidden>' in coa) == (len(coa_slides) > 1) and "scroll-snap-type:x mandatory" in fp
      and "timer=setInterval" in HB.HUB_JS and "if(!still){timer=" in HB.HUB_JS)
check("featured mod: no game name in what shows (the address is only a link)", not BANNED.findall(visible(coa))
      and not BANNED.findall(re.sub(r'href="[^"]*"', "", coa)))
check("featured mod: a slow zoom and drift on scroll from the page's script, still with reduced motion",
      "var coa=d.querySelector(\".hb-coa\");" in HB.HUB_JS and "if(coa&&!still)" in HB.HUB_JS and "--coa" in fp
      and re.search(r"prefers-reduced-motion:reduce\)\{.*?\.hb-coa-pic img\{transform:scale\(1\.03\)!important\}", fp, re.S))

# ---------------------------------------------------------------- the server software (owner: "we should have server software in
# this area and themed"): the cores the host pack really runs, checked against hosting/kit/tools/wuhost/cores.py
cspec = importlib.util.spec_from_file_location("kitcores", os.path.join(REPO, "hosting", "kit", "tools", "wuhost", "cores.py"))
kc = importlib.util.module_from_spec(cspec)
cspec.loader.exec_module(kc)
kit_live = {"azerothcore"} | {p["core"] for p in kc.offered_profiles({}).values()}
kit_any = kit_live | {p["core"] for p in kc.PROFILES.values()}
sw = re.search(r'<div class="hb-sw" role="group".*?<ul class="hb-sw-cores">.*?</ul></div>', fp, re.S)
sw = sw.group(0) if sw else ""
cores = re.findall(r'<li class="hb-sw-core[^"]*" data-core="([a-z]+)" data-status="([a-z]+)" title="([^"]+)"><b>([^<]+)</b><span>([^<]+)</span></li>', sw)
check("host console (owner: \"the server GM console / health etc ... all in one host server package\"): in the hosting section",
      'id="f-host"' in fp and sw and fp.find('id="f-host"') < fp.find('class="hb-sw"') < fp.find('id="f-realms"')
      and "Your realm console" in sw and "Online · listed" in sw)
check("host console: health tiles (the four services, players, uptime)",
      re.findall(r"<li><i></i>([^<]+)<span>", sw) == ["Database", "Login server", "World server", "Relay agent", "Players", "Uptime"])
check("host console: the GM controls of the in-game Your realm window, restart with its five-minute warning",
      re.findall(r"<li><b>([^<]+)</b><span>", sw) == [a for a, _ in HB.HOST_GM]
      and "with a five-minute warning" in sw and "announce" in open(os.path.join(REPO, "realm", "custom", "lua_scripts", "ov_hostctl.lua")).read().lower())
check("host console: Check my realm's checks and Realm tools' jobs",
      all(html.escape(x) in sw for x in HB.HOST_CHECKS) and all(f"<li>{html.escape(x)}</li>" in sw for x in HB.HOST_TOOLS))
check("host console: the cores it runs, One click only for what the host pack runs today (cores.py), the rest Coming, and Your own",
      sorted(c[0] for c in cores) == ["azerothcore", "cmangos", "own", "trinitycore", "vmangos"]
      and {c[0] for c in cores if c[1] == "live"} == kit_live and all(c[4] == "One click" for c in cores if c[1] == "live")
      and all(c[4] == "Coming" for c in cores if c[1] == "coming") and [c[4] for c in cores if c[0] == "own"] == ["Relay agent"],
      (kit_live, [c[:2] for c in cores]))
check("server software: our own crest (the Leyline crystal) and a rune rule drawn in SVG, no pictures, no game words, no numbers",
      '<svg class="hb-crest"' in sw and sw.count('class="hb-rune"') == 2 and "<img" not in sw and "url(" not in sw
      and not BANNED.findall(visible(sw)) and not NOPE.findall(shown(sw)), NOPE.findall(shown(sw)))
check("server software: torch gold used sparingly next to our blue and violet",
      "#d9a441" in fp and fp.count("#d9a441") <= 12 and ".hb-sw-chip.go{color:#f1cf86" in fp)

# ---------------------------------------------------------------- the realm list picture (owner: "the actual looking realm list
# thing but ... our featured server names")
check("realm types from tags: Normal, PvP, RP, RP-PvP", [HB.realm_type(t)[0] for t in ([], ["hangout"], ["pvp"], ["rp"], ["rp", "pvp"],
      ["blizzlike", "pvp", "bots"])] == ["Normal", "Normal", "PvP", "RP", "RP-PvP", "PvP"])
check("population words from players: Offline, Low, Medium, High, Full", [HB.population(*x)[0] for x in (
      (False, 50), (True, None), (True, 0), (True, 19), (True, 20), (True, 79), (True, 80), (True, 199), (True, 200), (True, 900))]
      == ["Offline", "Low", "Low", "Low", "Medium", "Medium", "High", "High", "Full", "Full"])
RROWS = [{"home": True, "name": "Dalaran Hangout", "live": True, "players": 4, "tags": ["hangout"], "build": 12340},
         {"id": "featuredfeatured", "name": "Old Days", "live": True, "players": 90, "tags": ["rp", "pvp"], "featured": True, "build": 12340},
         {"id": "busybusybusybusy", "name": "Busy Den", "live": True, "players": 230, "tags": ["pvp"], "build": 12340},
         {"id": "quietquietquietq", "name": "Quiet <Meadow>", "live": True, "players": 30, "tags": ["rp"], "build": 5875},
         {"id": "sleepysleepysle2", "name": "Sleepy", "live": False, "players": None, "tags": [], "build": 12340}]
rl = HB.hub.realm_list_art((RROWS, {}, True, {}, {}))
rrows = re.findall(r'<li><a class="hb-rlx-r([^"]*)" href="([^"]+)"[^>]*data-type="([a-z]+)" data-pop="([a-z]+)">'
                   r'<span class="hb-rlx-n">([^<]+)</span><span class="hb-rlx-t[^"]*">([^<]+)</span>.*?<span class="hb-rlx-p[^"]*">([^<]+)</span></a></li>', rl)
check("realm list: the rows from the live list in its order, then a dimmed Your realm here (Host one) row",
      [r[4] for r in rrows] == ["Dalaran Hangout", "Old Days", "Busy Den", "Quiet &lt;Meadow&gt;", "Sleepy", "Your realm here"]
      and rrows[-1][0] == " you" and rrows[-1][1] == "/wrath/host" and rrows[-1][5] == "Host one", [r[4] for r in rrows])
check("realm list: types coloured from tags, population in words", [(r[5], r[2]) for r in rrows[:5]] == [
      ("Normal", "pve"), ("RP-PvP", "rppvp"), ("PvP", "pvp"), ("RP", "rp"), ("Normal", "pve")]
      and [r[6] for r in rrows[:5]] == ["Recommended", "High", "Full", "Medium", "Offline"]
      and all(f".hb-rlx-t.{c}{{color:" in HB.HUB_CSS for c in ("pvp", "rp", "rppvp"))
      and all(f".hb-rlx-p.{c}{{color:" in HB.HUB_CSS for c in ("low", "med", "high", "full", "rec")), [(r[5], r[6]) for r in rrows])
check("realm list: ours selected and Recommended; each row one click to play, as on the realm list",
      rrows[0][0] == " sel" and 'aria-current="true"' in rl and [r[1] for r in rrows[:5]] == [
      "/wrath", "/wrath?go=r:featuredfeatured", "/wrath?go=r:busybusybusybusy", "leyline://realm/quietquietquietq", "leyline://realm/sleepysleepysle2"]
      and rrows[4][0] == " off")
check("realm list: columns Realm, Type, Characters, Population; rows are links (keyboard focusable) with a spoken summary",
      re.findall(r"<span>([A-Za-z]+)</span>", re.search(r'<p class="hb-rlx-cols".*?</p>', rl).group(0)) == ["Realm", "Type", "Characters", "Population"]
      and rl.count('aria-label="') == 5 and "Realm list</p>" in rl and ".hb-rlx-r:hover,.hb-rlx-r:focus-visible{" in HB.HUB_CSS)
full = HB.hub.realm_list_art((RROWS + [dict(RROWS[2], id="b" * 16, name="More")] * 3, {}, True, {}, {}))
check("realm list: at most six realms, no Your realm here row when the list is full", full.count('class="hb-rlx-r') == HB.REALM_LIST_MAX
      and "Your realm here" not in full)
check("realm list: on the front page in Realms & hopping, our own drawing (no picture, no game words or numbers)",
      re.search(r'id="f-realms".*?<div class="hb-rlx" role="group"', fp, re.S) and "<img" not in rl and "url(" not in rl
      and not BANNED.findall(visible(rl)) and not NOPE.findall(shown(rl)))
check("realm list: stacks on a phone", "@media (max-width:560px){" in HB.HUB_CSS and ".hb-rlx-cols{display:none}" in HB.HUB_CSS)

# ---------------------------------------------------------------- the Minigolf loop in Game modes (owner: "in here show the minigolf gif")
vid = re.search(r'<figure class="hb-shot hb-vid">.*?</figure>', fp, re.S)
vid = vid.group(0) if vid else ""
check("game modes: the Minigolf recording, muted, looped, inline, nothing loaded until it plays, the poster first",
      re.search(r'id="f-modes".*?<figure class="hb-shot hb-vid">', fp, re.S)
      and '<video muted loop playsinline preload="none" poster="/wrath/art/leyline-shot-minigolf.webp" width="820" height="596" data-hb-vid' in vid
      and vid.find('<source src="/wrath/art/leyline-shot-minigolf.webm" type="video/webm">')
      < vid.find('<source src="/wrath/art/leyline-shot-minigolf.mp4" type="video/mp4">') and "autoplay" not in vid)
check("game modes: caption and a Play link to the mode (works without script)", "<span>Minigolf, on our own realm</span>" in vid
      and 'href="/wrath?go=mode:minigolf">Play</a>' in vid
      and any(m["id"] == "minigolf" and m["start"] == {"go": "mode:minigolf"} for m in json.load(open(os.path.join(HERE, "playmodes.json")))["modes"]))
check("game modes: played only on screen, never with reduced motion or Save-Data",
      'd.querySelectorAll("video[data-hb-vid]")' in HB.HUB_JS and "navigator.connection.saveData" in HB.HUB_JS
      and "!still&&!save" in HB.HUB_JS and "v.pause()" in HB.HUB_JS)
check("game modes: the loop's files served and behind the killswitch",
      all(n in wp.ART_TYPES and n in wp.GAMEDATA_ART and os.path.isfile(os.path.join(HERE, "www-files", "art", n))
          for n in ("leyline-shot-minigolf.mp4", "leyline-shot-minigolf.webm", "leyline-shot-minigolf.webp"))
      and wp.ART_TYPES["leyline-shot-minigolf.mp4"] == "video/mp4" and wp.ART_TYPES["leyline-shot-minigolf.webm"] == "video/webm")
st, hd, b = req("/wrath/art/leyline-shot-minigolf.mp4")
whole = len(b)
check("game modes: the video answers a plain GET whole, with Accept-Ranges", st == 200 and hd.get("accept-ranges") == "bytes"
      and hd.get("content-type") == "video/mp4" and whole > 100000)


def ranged(path, rng):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
    c.request("GET", path, headers={"Range": rng})
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


st, hd, b = ranged("/wrath/art/leyline-shot-minigolf.webm", "bytes=0-99")
check("game modes: a byte range answers 206 with Content-Range (seeking works)", st == 206 and len(b) == 100
      and re.fullmatch(r"bytes 0-99/\d+", hd.get("content-range", "")))
st, hd, b = ranged("/wrath/art/leyline-shot-minigolf.mp4", "bytes=-10")
check("game modes: a suffix range is the last bytes", st == 206 and len(b) == 10 and hd["content-range"] == f"bytes {whole - 10}-{whole - 1}/{whole}")
check("game modes: a range past the end is 416; a picture ignores ranges", ranged("/wrath/art/leyline-shot-minigolf.mp4", f"bytes={whole + 5}-")[0] == 416
      and ranged("/wrath/art/leyline-shot-dalaran.webp", "bytes=0-9")[0] == 200)
check("game modes: the page's CSP lets our own media play", "media-src 'self'" in req("/wrath/leyline-preview")[1].get("content-security-policy", ""))

# ---------------------------------------------------------------- the modes' key art (Azeroth Survivors)
mp = req("/wrath/leyline-preview/modes")[2].decode()
sv = re.search(r'<article class="hb-mode art" id="mode-azeroth-survivors">.*?</article>', mp, re.S)
check("modes page: Azeroth Survivors shows its key art (served, sized, alt), the others none",
      sv and re.search(r'<img class="hb-mode-art" src="/wrath/art/leyline-mode-azeroth-survivors\.webp" alt="[^"]{20,}" width="483" height="298"', sv.group(0))
      and mp.count('class="hb-mode-art"') == 1 and "leyline-mode-azeroth-survivors.webp" in wp.ART_TYPES
      and os.path.isfile(os.path.join(HERE, "www-files", "art", "leyline-mode-azeroth-survivors.webp")))
wp.ART_DIR = ART_WAS
HB.hub.portal = portal_with
HB.hub.portal = lambda name: None if name == "hub_rank" else portal_with(name)
best = sorted(pool, key=lambda i: (-float(i.get("score") or 0), i["name"].lower(), i["id"]))[0]
check("mod of the week without rankings: the best score", f'leyline://install/{best["id"]}"' in req("/wrath/leyline-preview")[2].decode())
HB.hub.portal = real
with wp._listing_lock:
    wp._listing.update(realms=[], ok=False, fetched=False, at=-1e9)

# ---------------------------------------------------------------- hidden: nothing links here; the switches
for p in ("/wrath/leyline", "/wrath/realms", "/wrath/modes", "/wrath/mods", "/wrath/docs", "/wrath/armory", "/wrath/workshop",
          "/wrath/nope"):
    st, _, b = req(p)
    check(f"{p} ({st}) doesn't link to the preview", b"leyline-preview" not in b)
leaks = []
for d in (os.path.join(HERE, "www-files"), os.path.join(REPO, "docs", "leyline"), os.path.join(REPO, "launcher", "ui")):
    for root, _, files in os.walk(d):
        for n in files:
            if n.endswith((".html", ".js", ".md", ".css")):
                if "leyline-preview" in open(os.path.join(root, n), encoding="utf-8", errors="replace").read():
                    leaks.append(n)
check("no page file, doc or launcher page links to the preview", not leaks, leaks)
check("the site nav and footer don't", "leyline-preview" not in wp.site_nav() + wp.site_footer())
old = req("/wrath/leyline")[2].decode()
check("switch off (default): /wrath/leyline is the current page", 'class="hb-top"' not in old)
check("switch off (default): /wrath/leyline/gallery is not served", 'class="hb-top"' not in req("/wrath/leyline/gallery")[2].decode())
os.environ["WU_HUB_FRONT"] = "1"
st, h, b = req("/wrath/leyline")
s = b.decode()
check("switch on: /wrath/leyline is the hub's front page, indexable", st == 200 and 'class="hb-top"' in s
      and "x-robots-tag" not in h and 'content="noindex"' not in s and "Preview:" not in s)
st, h, b = req("/wrath/leyline/gallery")
check("switch on: /wrath/leyline/gallery is the gallery, indexable (no longer in the menu)",
      st == 200 and "<h1>Gallery</h1>" in b.decode() and "x-robots-tag" not in h and 'content="noindex"' not in b.decode()
      and "/wrath/leyline/gallery" not in s)
# the front door is the main site (owner 2026-10-30: "make this our main one"): every hub page at /wrath/leyline/<page>
check("switch on: no link on the front page says leyline-preview", "leyline-preview" not in s)
for pg in ("/realms", "/catalog?cat=addons", "/modes", "/news", "/creators", "/beacon", "/submit", "/forge", "/agents",
           "/p/theme-night-sky"):
    st, h, b = req("/wrath/leyline" + pg)
    t = b.decode()
    check(f"switch on: /wrath/leyline{pg} is served, indexable, no preview flag or links",
          st == 200 and 'class="hb-top"' in t and "leyline-preview" not in t and "Preview:" not in t
          and 'class="hb-sub"' not in t and "x-robots-tag" not in h,
          (st, "leyline-preview" in t, "Preview:" in t, 'class="hb-sub"' in t, h.get("x-robots-tag"), re.findall(r".{60}leyline-preview.{40}", t)[:2]))
st, h, _ = req("/wrath/leyline-preview/catalog?cat=addons&q=bags")
check("switch on: an old preview address sends a 301 to the front door, with its query",
      st == 301 and h.get("location") == "/wrath/leyline/catalog?cat=addons&q=bags", (st, h.get("location")))
check("switch on: the preview's own front page too", req("/wrath/leyline-preview")[1].get("location") == "/wrath/leyline")
check("switch on: the catalog feed stays where launchers read it", req("/wrath/leyline/catalog.json")[0] == 200)
for old_p, to in (("/wrath/realms?client=own", "/wrath/leyline/realms?client=own"), ("/wrath/mods", "/wrath/leyline/catalog"),
                  ("/wrath/workshop?q=bags&x=1", "/wrath/leyline/catalog?q=bags"),
                  ("/wrath/mods/c/addons", "/wrath/leyline/catalog?cat=addons")):
    st, h, _ = req(old_p)
    check(f"switch on: the older page {old_p} sends a 301 to its twin", st == 301 and h.get("location") == to, (st, h.get("location")))
check("switch on: a Workshop item page stays", req("/wrath/mods/pings")[0] != 301)
st, h, _ = req("/wrath/leyline/submit", "POST", "repo=https%3A%2F%2Fgithub.com%2Fa%2Fb&build=3.3.5a&category=tools", ip="10.4.4.9")
check("switch on: Submit a mod posts at the front door and lands there", st in (303, 400)
      and (st == 400 or h.get("location") == "/wrath/leyline/submit?done=1"), (st, h.get("location")))
check("Referrer-Policy same-origin: Chrome sends a real Origin on the site's own forms (no-referrer made it null, and "
      "every Origin check refused them), and other sites still get nothing", req("/wrath/leyline")[1].get("referrer-policy") == "same-origin")
os.environ.pop("WU_HUB_FRONT")
check("switch off: the older pages stay themselves", req("/wrath/realms")[0] == 200 and req("/wrath/mods")[0] == 200)
os.environ["WU_HUB"] = "0"
check("WU_HUB=0: the preview is off", req("/wrath/leyline-preview")[0] == 404 and req("/wrath/leyline/catalog.json")[0] == 404)
os.environ.pop("WU_HUB")

# ---------------------------------------------------------------- preview thumbnails and external packs
TCRED = "Preview image from the project's GitHub page"
ENOTE = "External download, made and hosted by its authors; not checked or hosted by Leyline"
gh = [e for e in INDEX["entries"] if e["forge"] == "github"]
base_e = dict(gh[0])
base_e.pop("thumb", None); base_e.pop("thumb_credit", None)
tn = HB.thumb_name(base_e["repo"])
good = dict(base_e, thumb="/wrath/art/hub-thumbs/" + tn, thumb_credit=TCRED)
check("thumb: the entry's own /wrath/art/hub-thumbs/<owner>__<repo>.webp with the exact credit passes",
      tn.endswith(".webp") and "__" in tn and not HB.thumb_problem(good))
for why, bad in {"another repo's file": dict(good, thumb="/wrath/art/hub-thumbs/someone__else.webp"),
                 "an outside link": dict(good, thumb="https://opengraph.githubassets.com/x/" + tn),
                 "a png": dict(good, thumb="/wrath/art/hub-thumbs/" + tn[:-5] + ".png"),
                 "another credit": dict(good, thumb_credit="From GitHub"),
                 "no credit": {k: v for k, v in good.items() if k != "thumb_credit"}}.items():
    doc = dict(INDEX, entries=[bad if e["id"] == bad["id"] else e for e in INDEX["entries"]])
    check(f"thumb: {why} is refused (validate_index)", any("thumb" in p for p in HB.validate_index(doc)))
gl = [e for e in INDEX["entries"] if e["forge"] != "github"]
if gl:
    check("thumb: only for a GitHub repo", HB.thumb_problem(dict(gl[0], thumb="/wrath/art/hub-thumbs/a__b.webp", thumb_credit=TCRED)))


def ext(url, **kw):
    x = {"id": HB.external_id(url), "name": "Crisp Ground Pack", "author": "Pack Folk", "url": url, "category": "graphics",
         "type": "external-pack", "builds": ["3.3.5a"], "summary": "Sharper ground textures, from its authors' page.",
         "external": True, "note": ENOTE}
    x.update(kw)
    return x


EXT_REPO = ext("https://github.com/packfolk/crisp-ground", repo="https://github.com/packfolk/crisp-ground",
               thumb="/wrath/art/hub-thumbs/packfolk__crisp-ground.webp", thumb_credit=TCRED)
EXT_PAGE = ext("https://forum.example.org/t/sky-pack", name="Sky Pack", author="")
check("external: a well-formed pack passes", HB.external_problems(EXT_REPO) == [] and HB.external_problems(EXT_PAGE) == [])
for why, bad in {"a made-up id": dict(EXT_PAGE, id="ext:000000000000"), "an id that isn't ext:<12hex>": dict(EXT_PAGE, id="link:abc"),
                 "http": ext("http://forum.example.org/t/x"), "a direct file": ext("https://cdn.example.org/pack.zip"),
                 "a file host": ext("https://mega.nz/file/abc"), "an install link": ext("leyline://install/x"),
                 "another type": dict(EXT_PAGE, type="addon"), "no flag": dict(EXT_PAGE, external=False),
                 "another note": dict(EXT_PAGE, note="Fine to install"), "an install field": dict(EXT_PAGE, download="https://x.example/a"),
                 "a brand word": dict(EXT_PAGE, name="WoW HD"), "markup": dict(EXT_PAGE, summary="<b>hi</b>"),
                 "a thumb without a repo": dict(EXT_PAGE, thumb="/wrath/art/hub-thumbs/a__b.webp", thumb_credit=TCRED),
                 "a repack": dict(EXT_PAGE, summary="A full repack")}.items():
    check(f"external: {why} is refused", HB.external_problems(bad), why)
EXT_BAD = ext("https://files.example.org/pack.7z", name="Bad Pack")
fx = json.loads(json.dumps(INDEX))
skip_thumb = gh[1]["id"]
for e in fx["entries"]:
    if e["forge"] == "github" and e["id"] != skip_thumb:
        e.update(thumb="/wrath/art/hub-thumbs/" + HB.thumb_name(e["repo"]), thumb_credit=TCRED)
fx["external"] = [EXT_REPO, EXT_PAGE, EXT_BAD]
check("fixture index (thumbs on GitHub entries) passes the hub's rules", HB.validate_index(fx) == [], HB.validate_index(fx)[:3])
json.dump(fx, open(os.path.join(HUBDIR, "community-index.json"), "w"))
ART_TMP = tempfile.mkdtemp(prefix="wu-hub-art-")
os.makedirs(os.path.join(ART_TMP, "hub-thumbs"))
WEBP = b"RIFF" + (30).to_bytes(4, "little") + b"WEBPVP8 " + b"\0" * 22
for e in fx["entries"] + [EXT_REPO]:
    if "thumb" in e:
        open(os.path.join(ART_TMP, e["thumb"][len("/wrath/art/"):]), "wb").write(WEBP)
open(os.path.join(ART_TMP, "hub-thumbs", "fake__html.webp"), "wb").write(b"<html>not an image</html>")
open(os.path.join(ART_TMP, "hub-thumbs", "x__y.png"), "wb").write(b"\x89PNG\r\n\x1a\n")
open(os.path.join(ART_TMP, "wu-theme.css"), "w").write("body{}")
ART_WAS2, wp.ART_DIR = wp.ART_DIR, ART_TMP
thumb1 = fx["entries"][[e["id"] for e in fx["entries"]].index(gh[0]["id"])]["thumb"]
st, h, b = req(thumb1)
check("art route: a hub thumbnail is served (image/webp, nosniff)", st == 200 and h.get("content-type") == "image/webp" and b == WEBP
      and h.get("x-content-type-options") == "nosniff", (st, h.get("content-type")))
for p in ("/wrath/art/hub-thumbs/fake__html.webp", "/wrath/art/hub-thumbs/x__y.png", "/wrath/art/hub-thumbs/..%2Fwu-theme.css",
          "/wrath/art/hub-thumbs/../wu-theme.css", "/wrath/art/hub-thumbs/Upper__Case.webp", "/wrath/art/hub-thumbs/nounderscore.webp",
          "/wrath/art/hub-thumbs/", "/wrath/art/hub-thumbs/a__b.webp/x"):
    check(f"art route: {p} is refused", req(p)[0] == 404)
check("art_present: thumbnails by pattern only", wp.art_present(thumb1[len("/wrath/art/"):]) and not wp.art_present("hub-thumbs/x__y.png")
      and not wp.art_present("../art/wu-theme.css"))
catx = req("/wrath/leyline-preview/catalog?sort=name")[2].decode()
cards = re.findall(r'<article class="hb-card(?: hb-ext)?">.*?</article>', catx, re.S)
withth = [c for c in cards if '/wrath/art/hub-thumbs/' in c]
check("catalog: GitHub entries show their thumbnail on the card (credited in its title)", withth and all(
      re.search(r'<a class="hb-card-pic" href="/wrath/leyline-preview/p/[a-z0-9-]+" tabindex="-1" aria-hidden="true"><img src="/wrath/art/hub-thumbs/'
                r'[a-z0-9._-]+__[a-z0-9._-]+\.webp" alt="" loading="lazy" width="640" height="320" title="Preview image from the project&#x27;s GitHub page">', c)
      for c in withth), withth[:1])
noth = next((c for c in cards if f'p/{skip_thumb.replace(":", "-")}"' in c), "")
check("catalog: an entry without a thumbnail gets the tile drawn from its id", noth and 'class="hb-gt-art gen hb-card-art"' in noth
      and "hub-thumbs" not in noth, noth[:300])
grp = re.search(r'<section class="hb-ext-s" id="external".*?</section>', catx, re.S)
grp = grp.group(0) if grp else ""
check("catalog: a 'Graphics & external packs' group with the good packs only", "<h2 id=\"hb-ext-h\">Graphics &amp; external packs</h2>" in grp
      and "Crisp Ground Pack" in grp and "Sky Pack" in grp and "Bad Pack" not in catx)
ecards = re.findall(r'<article class="hb-card hb-ext">.*?</article>', grp, re.S)
check("catalog: each external pack carries the badge and Visit the authors' page (new tab, noopener nofollow ugc)", len(ecards) == 2 and all(
      f'<p class="hb-ext-b" role="note">{html.escape(ENOTE)}</p>' in c
      and re.search(r'<a class="hb-ghost" href="https://[^"]+" rel="noopener nofollow ugc" target="_blank">Visit the authors. page</a>', c)
      for c in ecards), ecards[:1])
check("catalog: never an Install for an external pack", "leyline://install/ext:" not in catx and not any("Install" in c for c in ecards))
check("catalog: the source chip 'Graphics & external packs' (?source=external) shows only them",
      'href="/wrath/leyline-preview/catalog?source=external"' in req("/wrath/leyline-preview/catalog")[2].decode())
only = req("/wrath/leyline-preview/catalog?source=external")[2].decode()
check("catalog ?source=external: the two packs, nothing else", len(re.findall(r'<article class="hb-card hb-ext">', only)) == 2
      and '<article class="hb-card">' not in only)
check("catalog ?cat=addons: no external packs (they are graphics)", 'class="hb-ext-s"' not in req("/wrath/leyline-preview/catalog?cat=addons")[2].decode())
check("catalog: search finds an external pack", "Sky Pack" in req("/wrath/leyline-preview/catalog?q=sky")[2].decode())
st, h, b = req("/wrath/leyline-preview/p/" + EXT_REPO["id"].replace(":", "-"))
xp = b.decode()
check("external item page: 200, noindex, the badge, Visit the authors' page (new tab, nofollow) and the source repo",
      st == 200 and h.get("x-robots-tag") and f"{html.escape(ENOTE)}" in xp and '<b>External</b>' in xp
      and "<a class=\"ly-btn\" href=\"https://github.com/packfolk/crisp-ground\" rel=\"noopener nofollow ugc\" target=\"_blank\">Visit the authors' page</a>" in xp)
check("external item page: never an Install, an install link or a download of ours", "leyline://" not in xp
      and not re.search(r"(?i)\binstall with\b|>Install<|download=", xp))
check("external item page: its thumbnail with the credit under it", '<img src="/wrath/art/hub-thumbs/packfolk__crisp-ground.webp"' in xp
      and f"<figcaption>{html.escape(TCRED)}</figcaption>" in xp)
xp2 = req("/wrath/leyline-preview/p/" + EXT_PAGE["id"].replace(":", "-"))[2].decode()
check("external item page without a repo: the generated tile, 'its authors', no source button", 'class="hb-gt-art gen"' in xp2
      and "its authors" in xp2 and "View source" not in xp2 and "hub-thumbs" not in xp2)
check("external item page: a bad pack is not there", req("/wrath/leyline-preview/p/" + EXT_BAD["id"].replace(":", "-"))[0] == 404)
check("external pages: no brand words or client numbers", not BANNED.findall(visible(xp + xp2 + grp)) and not NOPE.findall(shown(xp + xp2 + grp)))
ip = req(re.search(r'href="(/wrath/leyline-preview/p/link-[a-z0-9]+)"', withth[0]).group(1) if withth else "/x")[2].decode()
check("item page: the thumbnail with its credit", re.search(r'<figure class="hb-item-pic"><img src="/wrath/art/hub-thumbs/[^"]+\.webp" alt="The preview '
      r'image of [^"]+" width="640" height="320"><figcaption>Preview image from the project&#x27;s GitHub page</figcaption></figure>', ip))
galx = req("/wrath/leyline-preview/gallery")[2].decode()
gt = {t[2]: t for t in GALS.findall(galx)}
xt = gt.get("x-" + EXT_REPO["id"].replace(":", "-"))
check("gallery: an external pack with its GitHub thumbnail is a tile, credited, flagged external, no Install",
      xt and 'src="/wrath/art/hub-thumbs/packfolk__crisp-ground.webp"' in xt[3] and TCRED.replace("'", "&#x27;") in xt[3]
      and "not checked or hosted by Leyline" in xt[3] and "leyline://" not in xt[3]
      and 'rel="noopener nofollow ugc" target="_blank">Visit the authors&#x27; page</a>' in xt[3], xt[3][:400] if xt else list(gt)[:20])
check("gallery: an external pack without a GitHub thumbnail is not", "x-" + EXT_PAGE["id"].replace(":", "-") not in gt)
tm = [t for t in GALS.findall(galx) if t[1] == "mods" and "/hub-thumbs/" in t[3] and not t[2].startswith("x-")]
check("gallery: mod tiles use the thumbnail, and the credit is in the caption the lightbox shows (.hb-gt-c i)", tm and all(
      re.search(r'<img src="/wrath/art/hub-thumbs/[^"]+" alt="The preview image of [^"]+" width="640" height="320"', t[3])
      and re.search(r"<i>by [^<]+ · Preview image from the project&#x27;s GitHub page</i>", t[3]) for t in tm)
      and 'parts.c.textContent=txt(t,".hb-gt-c i")' in HB.HUB_JS, [t[2] for t in tm][:5])
check("gallery page: the fine print says where the pictures come from", "preview image from its GitHub page" in galx)
frontx = req("/wrath/leyline-preview")[2].decode()
top = HB.hub._ranked([i for i in HB.hub.items() if i["source"] != "theme"])[0][0]
motw = re.search(r'<section class="hb-motw.*?</section>', frontx, re.S).group(0)
if top.get("thumb"):
    check("Mod of the week: the thumbnail and its credit", top["thumb"] in motw and f'<p class="hb-th-cr">{html.escape(TCRED)}</p>' in motw)
else:
    check("Mod of the week: the generated tile when there's no thumbnail", 'class="hb-gt-art gen"' in motw)
spot = re.search(r'id="community".*?</section>', frontx, re.S).group(0)
check("Community Spotlight: thumbnails where there's no Workshop screenshot", "/wrath/art/hub-thumbs/" in spot)
check("front page: never an install link for an external pack", "leyline://install/ext:" not in frontx)
feedx = json.loads(req("/wrath/leyline/catalog.json")[2])
check("launcher feed: no external packs (never installable)", not any(str(p.get("id", "")).startswith("ext:") for p in feedx["projects"]))
wp.ART_DIR = ART_WAS2
check("thumbnail file gone: the generated tile instead of a broken image",
      "/wrath/art/hub-thumbs/" not in req("/wrath/leyline-preview/catalog")[2].decode())
n_before = len(HB.hub.index())
json.dump(dict(fx, external=[dict(EXT_PAGE, download="https://x.example/a")]), open(os.path.join(HUBDIR, "community-index.json"), "w"))
check("a bad external list never takes the index down", 'class="hb-ext-s"' not in req("/wrath/leyline-preview/catalog")[2].decode()
      and n_before > 0 and len(HB.hub.index()) == n_before)
shutil.copy(os.path.join(HERE, "hub", "community-index.json"), HUBDIR)
shutil.rmtree(ART_TMP, ignore_errors=True)

# ---------------------------------------------------------------- shipping
bat = open(os.path.join(HERE, "Update sign-in and warm-up.bat"), encoding="utf-8").read()
fl = open(os.path.join(HERE, "fastloop.sh"), encoding="utf-8").read()
check("sign-in bat: packs hub.py and hub/", 'if exist hub.py if exist hub\\community-index.json set "LINKS=%LINKS% hub.py hub"' in bat
      and " hub.py " in re.search(r"\$\(ls ([^)]*)\)", bat).group(0))
check("fastloop.sh: installs hub.py and its data, backs them up, puts them back", 'install -m 644 hub.py "$WU/portal/hub.py"' in fl
      and '"$BK/hub.py"' in fl and 'install -m 644 hub/*.json "$WU/portal/hub/"' in fl)
check("fastloop.sh: installs the art's files and the hub-thumbs folder (WebP only), never trips on the subfolder",
      "install -m 644 www-files/art/*" not in fl and 'find www-files/art -maxdepth 1 -type f -exec install -m 644 {} "$WU/portal/art/"' in fl
      and "find www-files/art/hub-thumbs -maxdepth 1 -type f -name '*.webp' -exec install -m 644 {} \"$WU/portal/art/hub-thumbs/\"" in fl)
check("sign-in bat: packs the whole www-files/art folder (tar is recursive: hub-thumbs goes along)", " www-files/art " in bat)
check("the index in the repo passes the hub's rules", HB.validate_index(json.load(open(os.path.join(HERE, "hub", "community-index.json")))) == [])

srv.shutdown()
shutil.rmtree(DATA, ignore_errors=True)
shutil.rmtree(HUBDIR, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
