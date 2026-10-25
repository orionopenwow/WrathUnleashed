"""The site as one place: the one nav on every page (the right item marked), the footer and the closing step, the
styled 404, the "Right now" strip on /wrath/leyline (with and without real data, never a made-up number), share
boxes, titles and link cards, focus and reduced-motion styles, images, no game-brand names, escaping.

    python3 -I stream/tests/test_site.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix="wu-site-")
MODS, ARM, ART = (os.path.join(TMP, d) for d in ("mods", "armory", "art"))
for d in (os.path.join(MODS, "files"), os.path.join(ARM, "c"), ART):
    os.makedirs(d)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example", WU_MODS_DIR=MODS,
                  WU_ARMORY_DIR=ARM, WU_ART_DIR=ART, WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.example")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

BANNED = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")
def visible(p):
    p = re.sub(r"<style.*?</style>", " ", p, flags=re.S)
    attrs = " ".join(re.findall(r'(?:alt|title|content|aria-label|placeholder)="([^"]*)"', p))
    return re.sub(r"<[^>]+>", " ", p) + " " + attrs

def set_listing(realms, ok=True):
    with wp._listing_lock:
        wp._listing.update(at=time.monotonic(), ok=ok, realms=realms, fetched=True, when=time.time() if ok else 0.0)

def expire_strip():
    with wp._right_now_lock:
        wp._right_now["at"] = -1e9

check("modules beside the portal loaded", all(m is not None for m in (wp.modes, wp.armory, wp.workshop, wp.links)))
wp.armory.STAT_EVERY = 0
wp.armory.store.root = ARM

# ---------------------------------------------------------------- 1. no data at all
wp.realm_status = lambda: {}
set_listing([], ok=False)
items, _ = wp.right_now(fresh=True)
check("no data: no items", items == [], items)
ly = wp.leyline_page().decode()
check("no data: no Right now strip at all", "Right now" not in ly and 'class="ly-now"' not in ly)
check("no data: the page still renders", "<h1>Leyline</h1>" in ly)

# zeros are left out, never shown as live
wp.realm_status = lambda: {"online": True, "players": 0, "bots": 40, "updated_at": "2026-10-25T10:20:30Z"}
set_listing([{"id": "abcdefghijklmnop", "name": "Quiet", "live": False, "players": 0, "bots": 0}])
items, _ = wp.right_now(fresh=True)
check("zero players and no live realm: left out", items == [], items)
wp.realm_status = lambda: {"online": False, "players": 7}
items, _ = wp.right_now(fresh=True)
check("realm down: its player number is not shown", items == [], items)
wp.realm_status = lambda: {"online": True, "players": None}
check("unknown players: left out", wp.right_now(fresh=True)[0] == [])

# ---------------------------------------------------------------- 2. real data
wp.realm_status = lambda: {"online": True, "players": 12, "bots": 30, "updated_at": "2026-10-25T10:20:30Z"}
set_listing([{"id": "abcdefghijklmnop", "name": "Frost", "live": True, "players": 3, "bots": 0, "ruleset": "dalaran",
              "type": "Fun", "tagline": "", "claimed": True, "rules": []},
             {"id": "qrstuvwxyz234567", "name": "Ember", "live": True, "players": 1, "bots": 0, "ruleset": "main",
              "type": "PvE", "tagline": "", "claimed": False, "rules": []},
             {"id": "aaaaaaaaaaaaaaaa", "name": "Shut", "live": False, "players": None, "bots": None, "ruleset": "custom",
              "type": "PvE", "tagline": "", "claimed": False, "rules": []}])
cat = {"format": 1, "mods": [
    {"id": "old-mod", "name": "Old Mod", "version": "1.0.0", "kind": "ui", "zip": "old-mod-1.0.0.zip", "description": "x"},
    {"id": "evil-mod", "name": "Evil <script>alert(1)</script> & \"Co\"", "version": "1.0.0", "kind": "ui",
     "zip": "evil-mod-1.0.0.zip", "description": "y"},
    {"id": "new-mod", "name": "New Mod", "version": "2.0.0", "kind": "realm", "zip": "new-mod-2.0.0.zip", "description": "z"}]}
json.dump(cat, open(os.path.join(MODS, "catalog.json"), "w"))
now = time.time()
for i, z in enumerate(("old-mod-1.0.0.zip", "evil-mod-1.0.0.zip", "new-mod-2.0.0.zip")):
    p = os.path.join(MODS, "files", z)
    open(p, "wb").write(b"PK")
    os.utime(p, (now - 3000 + i * 1000, now - 3000 + i * 1000))
chars = [{"name": n, "race": 1, "class": 2, "level": 80, "reached80_day": d, "last_day": d}
         for n, d in (("Arthas", "2026-10-20"), ("Jaina", "2026-10-24"), ("Thrall", "2026-10-22"), ("Uther", "2026-10-21"))]
chars.append({"name": "Lowbie", "race": 2, "class": 1, "level": 30})
json.dump({"updated": int(now), "chars": chars}, open(os.path.join(ARM, "index.json"), "w"))
for c in chars:
    json.dump(dict(c, items=[]), open(os.path.join(ARM, "c", c["name"] + ".json"), "w"))

items, when = wp.right_now(fresh=True)
kinds = [i["kind"] for i in items]
check("real data: four items, in order", kinds == ["players", "realms", "mods", "eighties"], kinds)
ly = wp.leyline_page().decode()
strip = ly.split('class="ly-now"', 1)[1].split("</section>", 1)[0] if 'class="ly-now"' in ly else ""
check("strip: on the page, under Right now", "Right now" in strip)
check("strip: players from realm_status, linked", '<b>12</b> players on WrathUnleashed</a>' in strip and 'href="/wrath/realms"' in strip)
check("strip: bots not counted as players", "42" not in strip and "30" not in strip.split("<p>")[0])
check("strip: live community realms counted (offline left out)", "<b>2</b> community realms live" in strip)
mods_li = re.findall(r'href="/wrath/mods/([a-z-]+)"', strip)
check("strip: latest mods, newest zip first, each linked", mods_li == ["new-mod", "evil-mod", "old-mod"], mods_li)
check("strip: mod names escaped", "Evil &lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;Co&quot;" in strip and "<script>" not in strip)
eighties = re.findall(r'href="/wrath/armory/([A-Za-z]+)"', strip)
check("strip: recent level 80s, newest first, linked to the armory", eighties == ["Jaina", "Thrall", "Uther"], eighties)
check("strip: links to the Workshop and the armory", 'href="/wrath/mods">Latest mods:' in strip and 'href="/wrath/armory">Recent level 80s:' in strip)
check("strip: says when it was read", re.search(r'Updated <time datetime="\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ">\d\d:\d\d UTC</time>', strip))

# cached for 60 s
wp.realm_status = lambda: {"online": True, "players": 99}
check("cache: the same numbers within 60 s", "<b>12</b> players" in wp.right_now_html() and "<b>99</b>" not in wp.right_now_html())
expire_strip()
check("cache: new numbers after 60 s", "<b>99</b> players" in wp.right_now_html())
check("cache: TTL is 60 s", wp.RIGHT_NOW_TTL == 60)
wp.realm_status = lambda: {"online": True, "players": 1}
expire_strip()
check("strip: one player is 'player'", "<b>1</b> player on" in wp.right_now_html())

# a source that breaks is left out, the others stay
def boom():
    raise RuntimeError("down")
wp.realm_status = boom
expire_strip()
items, _ = wp.right_now()
check("a broken source is left out, the rest stay", [i["kind"] for i in items] == ["realms", "mods", "eighties"], items)
# escaping of the realm name in the strip
saved = wp.REALM_NAME
wp.REALM_NAME = 'Wr<a>"th'
wp.realm_status = lambda: {"online": True, "players": 5}
expire_strip()
h = wp.right_now_html()
check("strip: realm name escaped", "Wr&lt;a&gt;&quot;th" in h and "Wr<a>" not in h)
wp.REALM_NAME = saved
wp.realm_status = lambda: {"online": True, "players": 12, "bots": 30, "updated_at": "2026-10-25T10:20:30Z"}
expire_strip()

# ---------------------------------------------------------------- 3. every page through the real handler
srv = ThreadingHTTPServer(("127.0.0.1", 0), wp.PageHandler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path, ip="203.0.113.5"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.request("GET", path, headers={"X-Forwarded-For": ip}); r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")

NAV_ITEMS = [("Leyline", "/wrath/leyline"), ("Play", "/wrath/account"), ("Realms", "/wrath/realms"), ("Modes", "/wrath/modes"),
             ("Mods", "/wrath/mods"), ("Armory", "/wrath/armory"), ("Server", wp.HOST_URL), ("Discord", wp.DISCORD_URL),
             ("Sign in", "/login?next=%2Fwrath"), ("Play now", "/wrath")]
CURRENT_HREF = {"leyline": "/wrath/leyline", "play": "/wrath/account", "realms": "/wrath/realms", "modes": "/wrath/modes",
                "mods": "/wrath/mods", "armory": "/wrath/armory"}

def nav_of(page):
    m = re.search(r'<nav class="ly-nav" id="ly-site-nav".*?</nav>', page, re.S)
    return m.group(0) if m else ""

def check_chrome(label, page, current, public=True, next_step=True, signed_in=False):
    nav = nav_of(page)
    check(f"{label}: the site nav, once", page.count('id="ly-site-nav"') == 1 and nav)
    check(f"{label}: no nav of its own left", page.count('<nav class="ly-nav"') == 1 and 'class="grp"' not in page)
    want = [x for x in NAV_ITEMS if not (signed_in and x[0] == "Sign in")]
    missing = [t for t, href in want if f'href="{wp.html.escape(href)}"' not in nav or f">{t}</a>" not in nav]
    check(f"{label}: every nav item", not missing, missing)
    marked = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', nav)
    check(f"{label}: marks {current or 'nothing'} as current", marked == ([CURRENT_HREF[current]] if current else []), marked)
    if current:
        check(f"{label}: the current item is styled", re.search(r'<a href="%s" class="[^"]*\bon\b' % re.escape(CURRENT_HREF[current]), nav))
    check(f"{label}: phone menu works without script", re.search(r'<input type="checkbox" id="ly-menu" class="ly-menu-t"><label for="ly-menu"[^>]*>Menu</label><div class="ly-links">', nav)
          and ".ly-menu-t:checked~.ly-links" in page)
    check(f"{label}: skip link to the content", 'href="#main">Skip to content' in page and 'id="main"' in page)
    foot = page.split('<footer class="ly-foot">', 1)[-1].split("</footer>", 1)[0] if '<footer class="ly-foot">' in page else ""
    check(f"{label}: footer (GitHub, Discord, Report a bug, no shop)", f'href="{wp.LEYLINE_REPO}"' in foot and f'href="{wp.DISCORD_URL}"' in foot
          and ">Report a bug<" in foot and wp.LEYLINE_REPO + "/issues/new" in foot and "No shop. Bots are labelled." in foot)
    title = re.search(r"<title>([^<]+)</title>", page)
    check(f"{label}: a title", title and title.group(1).strip())
    if public:
        check(f"{label}: a link card", 'property="og:title"' in page and 'name="twitter:card"' in page)
    if next_step:
        nxt = re.findall(r'<aside class="ly-next".*?</aside>', page, re.S)
        check(f"{label}: ends with one clear next step", len(nxt) == 1 and ("Play now</a>" in nxt[0] or "Host a realm</a>" in nxt[0])
              and page.index(nxt[0]) < page.index('<footer class="ly-foot">'))
    check(f"{label}: focus and reduced-motion styles", ":focus-visible" in page and "prefers-reduced-motion:reduce" in page)
    imgs = re.findall(r"<img\b[^>]*>", page)
    bad = [i for i in imgs if not (re.search(r'\bwidth="\d+"', i) and re.search(r'\bheight="\d+"', i))
           or not ('loading="lazy"' in i or 'fetchpriority="high"' in i)]
    check(f"{label}: images sized and lazy (the hero emblem loads first)", not bad, bad[:2])
    bad = BANNED.findall(visible(page))
    check(f"{label}: no game-brand names", not bad, bad)

PAGES = [("/wrath/leyline", "leyline", 200), ("/wrath/realms", "realms", 200), ("/wrath/modes", "modes", 200),
         ("/wrath/mods", "mods", 200), ("/wrath/mods/new-mod", "mods", 200), ("/wrath/armory", "armory", 200),
         ("/wrath/armory/Arthas", "armory", 200), ("/wrath/armory/Nobody", "armory", 404), ("/wrath/q/258", "modes", 200),
         ("/wrath/u/Arthas", "armory", 200), ("/wrath/r/wrath", "realms", 200), ("/wrath/m/new-mod", "mods", 200),
         ("/wrath/demo", "", 200)]
for path, cur, code in PAGES:
    st, hd, page = get(path)
    check(f"{path}: {code}", st == code, st)
    check(f"{path}: still no script (CSP script-src 'none')", "<script" not in page and "script-src 'none'" in hd.get("content-security-policy", ""))
    share = path.startswith(("/wrath/q", "/wrath/u", "/wrath/r/", "/wrath/m/"))
    check_chrome(path, page, cur, public=path != "/wrath/demo", next_step=not share)

st, hd, page = get("/wrath")   # signed out: the saved-key sign-in page (it has its own nonce script)
check_chrome("/wrath (signed out)", page, "play", next_step=False)
check_chrome("sign-in page", wp.signed_out_page().decode(), "play", next_step=False)
check_chrome("error page", wp.error_page("x").decode(), "", public=False, next_step=False)
check_chrome("busy page", wp.busy_page(back="/wrath/realms").decode(), "realms", public=False, next_step=False)
check_chrome("streaming off page", wp.stream_off_page().decode(), "play", public=False, next_step=False)
acct = wp.account_page("Tester", "WR1", "pw", "n").decode()
check_chrome("account page (signed in)", acct, "play", public=False, next_step=False, signed_in=True)
check("account page: still the realm list and the Hero Key link", "Choose a realm" in acct and 'href="/account/key"' in acct
      and 'class="wu-panel wide"' in acct)
check("account page: no Sign in once signed in", ">Sign in</a>" not in nav_of(acct))
check("the gold pages keep their themed body", '<body class="wu">' in wp.signed_out_page().decode())
check("titles say which page", "<title>Realms · WrathUnleashed</title>" in get("/wrath/realms")[2]
      and "<title>Leyline</title>" in get("/wrath/leyline")[2] and "<title>Sign in · WrathUnleashed</title>" in wp.signed_out_page().decode())

# ---------------------------------------------------------------- 4. the 404
st, hd, nf = get("/wrath/no-such-page")
check("404: status and html", st == 404 and hd.get("content-type", "").startswith("text/html"), (st, hd.get("content-type")))
check("404: a styled page, not 'not found'", nf != "not found\n" and "<h1>Not found</h1>" in nf and 'class="ly"' in nf)
check_chrome("404 page", nf, "")
for href in ("/wrath", "/wrath/leyline", "/wrath/realms", "/wrath/modes", "/wrath/mods", "/wrath/armory", wp.HOST_URL):
    check(f"404: links on to {href}", f'<a class="ly-feat" href="{wp.html.escape(href)}"' in nf)
check("404: kept out of search results", '<meta name="robots" content="noindex">' in nf)
check("404: other unknown paths too", get("/nope")[0] == 404 and "Not found" in get("/x/y/z")[2])
check("404: art files stay a plain 404", get("/wrath/art/nothing.webp")[0] == 404 and "<nav" not in get("/wrath/art/nothing.webp")[2])
check("404: a path with markup is not echoed", "<b>" not in get("/wrath/%3Cb%3Ehi")[2])

# ---------------------------------------------------------------- 5. share boxes and update times
st, _, realms = get("/wrath/realms")
boxes = re.findall(r'<details class="ly-share"><summary>Share</summary><code tabindex="0">([^<]+)</code>', realms)
check("realms: a share box per realm card", boxes == ["https://play.example/wrath/r/wrath", "https://play.example/wrath/r/abcdefghijklmnop",
      "https://play.example/wrath/r/qrstuvwxyz234567", "https://play.example/wrath/r/aaaaaaaaaaaaaaaa"], boxes)
check("realms: every share link is a real share link", all(wp.links.parse(b.split("play.example", 1)[1]) for b in boxes))
check("realms: status time shown", 'Realm status <time datetime="2026-10-25T10:20:30Z">10:20 UTC</time>' in realms)
check("realms: community list time shown", re.search(r'Community list <time datetime="[^"]+">\d\d:\d\d UTC</time>', realms))
check("realms: ends with Host a realm", "Host a realm</a>" in re.findall(r'<aside class="ly-next".*?</aside>', realms, re.S)[0])
check("realms: the old Back link is gone", 'class="keylink" href="/wrath">Back' not in realms)
st, _, md = get("/wrath/modes")
go = re.findall(r'class="md-go" href="(/wrath/[hqb]/[^"]+)"', md)
sh = re.findall(r'<code tabindex="0">https://play\.example(/wrath/[hqb]/[^<]+)</code>', md)
check("modes: a share box on every card, with that card's link", len(go) > 50 and go == sh, (len(go), len(sh)))
st, _, sheet = get("/wrath/armory/Arthas")
check("armory: the sheet's share link", 'href="/wrath/u/Arthas"' in sheet and "https://play.example/wrath/u/Arthas</code>" in sheet)
check("armory: last updated shown", "Updated every 5 minutes (last: " in sheet)
check("leyline: realm list update time", re.search(r'Realm status <time datetime="2026-10-25T10:20:30Z">', get("/wrath/leyline")[2]))
check("updated_text: junk is nothing", wp.updated_text("<b>") == "" and wp.updated_text(None) == "" and wp.updated_text(0) == "")

# ---------------------------------------------------------------- 6. the pieces
check("nav_key", [wp.nav_key(p) for p in ("/wrath/leyline", "/wrath", "/wrath/account", "/wrath/realms", "/wrath/r/x",
      "/wrath/modes", "/wrath/q/258", "/wrath/mods/x", "/m/x", "/wrath/armory/A", "/u/A", "/wrath/x")]
      == ["leyline", "play", "play", "realms", "realms", "modes", "modes", "mods", "mods", "armory", "armory", ""])
once = wp.site_chrome(get("/wrath/modes")[2].encode(), "/wrath/modes")
check("site_chrome: never twice", once.decode().count('id="ly-site-nav"') == 1)
check("site_chrome: leaves non-pages alone", wp.site_chrome(b"plain", "/x") == b"plain" and wp.site_chrome(b"\xff\xfe", "/x") == b"\xff\xfe")
mod_page = wp.site_chrome(b'<!doctype html><html><head><title>T &amp; U</title></head><body class="ly"><div class="ly-glow"></div>'
                          b'<nav class="ly-nav" aria-label="Leyline"><div class="grp"><a href="/x">Old</a></div></nav>'
                          b'<div class="ly-wrap"><img src="/a.webp" width="2" height="2"></div></body></html>', "/wrath/mods").decode()
check("site_chrome: a module's own nav is replaced", ">Old<" not in mod_page and 'aria-current="page">Mods<' in mod_page)
check("site_chrome: a link card added when missing", 'property="og:title" content="T &amp; U"' in mod_page)
check("site_chrome: images made lazy", '<img loading="lazy" decoding="async" src="/a.webp"' in mod_page)
check("share_box escapes", "&lt;" in wp.share_box("/wrath/<x>") and "<x>" not in wp.share_box("/wrath/<x>"))

# ---------------------------------------------------------------- 7. no game-brand names in the new code's strings
for f in ("wrath_portal.py", "modes.py", "armory.py"):
    src = open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), f), encoding="utf-8").read()
    check(f"no game-brand names in {f}", not BANNED.findall(src), BANNED.findall(src)[:3])

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
