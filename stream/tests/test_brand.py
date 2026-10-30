"""The Leyline brand switch (owner 2026-10-30), with it ON: every portal page, feed and the page env say Leyline and
"Dalaran Hangout" where people read them, never WrathUnleashed, Wrath Unleashed, Open Vanilla or OpenVanilla
(addresses, ids and identifiers are not text people read: href/src values, URLs, WrathUnleashedUI). With it OFF the
other suites run unchanged (test_site.py and the rest load the portal without LEYLINE_BRAND). Also: realm/brand.sh
check / on / off on a fake server, the sampler under the brand, the addon-list .toc swap both ways, and wu-mod.py's
WUModCatalog.toc.

    python3 -I stream/tests/test_brand.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer

PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
STREAM = os.path.dirname(PORTAL)
REPO = os.path.dirname(STREAM)
TMP = tempfile.mkdtemp(prefix="wu-brand-")
MODS, ARM, ART = (os.path.join(TMP, d) for d in ("mods", "armory", "art"))
for d in (os.path.join(MODS, "files"), os.path.join(ARM, "c"), ART):
    os.makedirs(d)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example", WU_MODS_DIR=MODS,
                  WU_ARMORY_DIR=ARM, WU_ART_DIR=ART, WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.example", LEYLINE_BRAND="1", REALM_NAME="WrathUnleashed",
                  WU_PORTAL_DATA=os.path.join(TMP, "data"))
spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, str(extra)[:600])

OLD = re.compile(r"WrathUnleashed(?!UI\b)|Wrath Unleashed|Open ?Vanilla|Back to Wrath\b")
ADDR = re.compile(r"https?://[^\s\"'<>]+|\b[\w.-]+\.openvanilla\.app\b|github\.com/[\w./-]+")


def visible(page: str) -> str:
    """What a person reads: text, plus the attributes people see (titles, alt text, link cards); never addresses."""
    page = re.sub(r"<style.*?</style>", " ", page, flags=re.S)
    page = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    attrs = " ".join(re.findall(r'(?:alt|title|content|aria-label|placeholder|value)="([^"]*)"', page))
    return ADDR.sub(" ", re.sub(r"<[^>]+>", " ", page) + " " + attrs)


def json_text(doc) -> str:
    """Every string value of a JSON document (keys are not read by people), addresses left out."""
    out = []
    def walk(v):
        if isinstance(v, dict):
            for x in v.values(): walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
        elif isinstance(v, str):
            out.append(v)
    walk(doc)
    return ADDR.sub(" ", " ".join(out))


# ---------------------------------------------------------------- 1. the names
check("brand on: the switch is read", wp.BRAND is True)
check("brand on: the main realm is Dalaran Hangout (REALM_NAME is ignored)", wp.REALM_NAME == "Dalaran Hangout", wp.REALM_NAME)
check("brand on: the site is Leyline", wp.SITE_NAME == "Leyline")
check("brand on: the Sample Hangout is Dalaran Hangout too", wp.SAMPLER_NAME == "Dalaran Hangout")
check("brand on: Back to Dalaran Hangout", wp.BACK_LABEL == "Back to Dalaran Hangout")
check("sample_info: the network's official realm is Dalaran Hangout", wp.sample_info()["name"] == "Dalaran Hangout"
      and not OLD.search(visible(wp.sample_info()["blurb_html"])))

# ---------------------------------------------------------------- 2. the safety net
b = wp.brand_body(b'<p title="Open Vanilla">WrathUnleashed and Wrath Unleashed. <a href="https://github.com/o/WrathUnleashed">x</a>'
                  b' WrathUnleashedUI <script>var a="WrathUnleashed"</script> play.openvanilla.app</p>', "text/html; charset=utf-8").decode()
check("safety net: text and visible attributes", "Leyline and Leyline." in b and 'title="Leyline"' in b, b)
check("safety net: addresses, identifiers and scripts untouched", "github.com/o/WrathUnleashed" in b and "WrathUnleashedUI" in b
      and 'var a="WrathUnleashed"' in b and "play.openvanilla.app" in b, b)
j = wp.brand_body(b'{"author":"WrathUnleashed","credits":"Pings by WrathUnleashed","id":"WrathUnleashedUI"}', "application/json").decode()
check("safety net: JSON author values", json.loads(j) == {"author": "Leyline", "credits": "Pings by Leyline", "id": "WrathUnleashedUI"}, j)
check("safety net: other types untouched", wp.brand_body(b"WrathUnleashed", "application/javascript") == b"WrathUnleashed")

# ---------------------------------------------------------------- 3. every page through the real handler
cat = {"format": 1, "mods": [
    {"id": "pings", "name": "Pings", "version": "1.0.0", "kind": "ui", "zip": "pings-1.0.0.zip", "author": "WrathUnleashed",
     "description": "Ping the map. By WrathUnleashed.", "credits": "Pings by WrathUnleashed"}]}
json.dump(cat, open(os.path.join(MODS, "catalog.json"), "w"))
open(os.path.join(MODS, "files", "pings-1.0.0.zip"), "wb").write(b"PK")
now = time.time()
chars = [{"name": "Arthas", "race": 1, "class": 2, "level": 80, "reached80_day": "2026-10-20", "last_day": "2026-10-20"}]
json.dump({"updated": int(now), "chars": chars}, open(os.path.join(ARM, "index.json"), "w"))
for c in chars:
    json.dump(dict(c, items=[]), open(os.path.join(ARM, "c", c["name"] + ".json"), "w"))
wp.realm_status = lambda: {"online": True, "players": 12, "bots": 30, "updated_at": "2026-10-25T10:20:30Z"}
with wp._listing_lock:
    wp._listing.update(at=time.monotonic(), ok=True, fetched=True, when=time.time(), realms=[
        {"id": "abcdefghijklmnop", "name": "Frost", "live": True, "players": 3, "bots": 0, "ruleset": "dalaran", "type": "Fun",
         "tagline": "", "claimed": True, "rules": []}])
if wp.armory is not None:
    wp.armory.STAT_EVERY = 0
    wp.armory.store.root = ARM

# the art as fastloop.sh installs it (www-files/art -> /wrath/art/)
for n in os.listdir(os.path.join(STREAM, "www-files", "art")):
    shutil.copy(os.path.join(STREAM, "www-files", "art", n), ART)
srv = ThreadingHTTPServer(("127.0.0.1", 0), wp.PageHandler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path, ip="203.0.113.5"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=20)
    c.request("GET", path, headers={"X-Forwarded-For": ip}); r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")

PAGES = ["/wrath", "/wrath/leyline", "/wrath/realms", "/wrath/modes", "/wrath/mods", "/wrath/mods/pings", "/wrath/armory",
         "/wrath/armory/Arthas", "/wrath/armory/Nobody", "/wrath/q/258", "/wrath/u/Arthas", "/wrath/r/wrath",
         "/wrath/m/pings", "/wrath/demo", "/wrath/docs", "/wrath/docs/mods", "/wrath/docs/play", "/wrath/docs/hosting",
         "/wrath/docs/hero-key", "/wrath/docs/publishing", "/wrath/workshop", "/wrath/host", "/wrath/link",
         "/wrath/admin", "/wrath/leyline-preview", "/wrath/no-such-page", "/wrath/play", "/wrath/play/end"]
for path in PAGES:
    st, hd, page = get(path)
    ok = st < 500
    bad = OLD.findall(visible(page)) if hd.get("content-type", "").startswith("text/html") else []
    check(f"{path}: answers ({st}) with no old names people read", ok and not bad, (st, bad[:4]))
    if hd.get("content-type", "").startswith("text/html") and "<title>" in page:
        t = re.search(r"<title>([^<]*)</title>", page).group(1)
        check(f"{path}: the title", not OLD.search(t), t)

# the look (owner 2026-10-30): flat, the spinning mark as the header and loading logo, none of the painted art
PAINTED = re.compile(r"""(?:url\(|href="|src="|content=")[^)"]*(?:wu-theme\.css|wu-card\.webp|wu-corner|wu-dragon|wu-divider|"""
                     r"""wu-load-|leyline-bg\.webp|leyline-corner|leyline-divider|leyline-emblem|Cinzel|leyline-display\.woff2)""")
for path in PAGES:
    st, hd, page = get(path)
    if not hd.get("content-type", "").startswith("text/html") or "</head>" not in page:
        continue
    check(f"{path}: no painted art or display font", not PAINTED.search(page), PAINTED.findall(page)[:4])
    hub = 'data-look="leyline"' in page
    check(f"{path}: the flat look and the spinner's rules", hub or page.count('id="ly-look"') == 1)
    if 'id="ly-site-nav"' in page:
        nav = re.search(r'<a href="/wrath/leyline" class="ly-brand[^"]*"[^>]*>(.*?)</a>', page)
        check(f"{path}: the nav's Leyline carries the spinning mark", nav and 'class="ly-spin"' in nav.group(1), nav and nav.group(0))
for label, page in (("sign-in", wp.signed_out_page()), ("busy", wp.busy_page()), ("error", wp.error_page("x"))):
    page = wp.brand_body(page, "text/html").decode()
    check(f"{label} page: the spinning mark over the title, no theme link", 'class="ly-spin ly-crest-mark"' in page
          and "wu-theme.css" not in page and 'id="ly-look"' in page)
ley = get("/wrath/leyline")[2]
check("/wrath/leyline: the big spinning mark, not the emblem", 'class="ly-spin ly-hero-mark"' in ley and "ly-emblem" not in ley.split("</style>")[-1])
check("link cards: the round mark", "leyline-mark-512.png" in wp.card_meta("/wrath") and "wu-card" not in wp.card_meta("/wrath"))
check("SPIN_CSS: the swirl turns, the crystal doesn't, reduced motion stands still",
      "ly-spin::before{background-image:url(/wrath/art/leyline-swirl-256.webp);animation:ly-spin-turn" in wp.SPIN_CSS
      and "ly-spin::after{background-image:url(/wrath/art/leyline-crystal-256.webp)}" in wp.SPIN_CSS
      and "prefers-reduced-motion:reduce){.ly-spin::before{animation:none" in wp.SPIN_CSS)
for n, t in (("leyline-swirl-256.webp", "image/webp"), ("leyline-crystal-256.webp", "image/webp"), ("leyline-mark-512.png", "image/png"),
             ("leyline-swirl-128.png", "image/png"), ("leyline-crystal-128.png", "image/png")):
    st, hd, _ = get("/wrath/art/" + n)
    check(f"/wrath/art/{n}: served", st == 200 and hd.get("content-type") == t, (st, hd.get("content-type")))
check("the logo files ship under the Leyline export's art rule", all(os.path.exists(os.path.join(STREAM, "www-files", "art", n)) for n in
      ("leyline-swirl-256.webp", "leyline-crystal-256.webp", "leyline-swirl-512.png", "leyline-crystal-512.png", "leyline-swirl-128.png",
       "leyline-crystal-128.png")))

# with the switch OFF: none of it (the other suites load the portal off and check the pages; this checks the look's parts)
os.environ["LEYLINE_BRAND"] = "0"
spec0 = importlib.util.spec_from_file_location("wp_off", PORTAL)
wp0 = importlib.util.module_from_spec(spec0); spec0.loader.exec_module(wp0)
os.environ["LEYLINE_BRAND"] = "1"
s0 = wp0.signed_out_page().decode()
check("brand off: the sign-in page keeps its theme, crest and card, no spinner or flat look",
      "wu-theme.css" in s0 and "ly-spin" not in s0 and 'id="ly-look"' not in s0 and "wu-card.webp" in s0
      and wp0.brand_body(s0.encode(), "text/html").decode() == s0)
check("brand off: the nav as before", "ly-spin" not in wp0.site_nav() and ">Leyline</a>" in wp0.site_nav())
check("brand off: the Leyline page keeps its emblem and art", "leyline-emblem.webp" in wp0.leyline_page().decode()
      and "leyline-bg.webp" in wp0.leyline_css() and "@font-face" in wp0.leyline_css())

st, _, realms = get("/wrath/realms")
check("realms page: Dalaran Hangout is the official realm", "Dalaran Hangout" in visible(realms))
check("realms page: titled for Leyline", "<title>Realms · Leyline</title>" in realms, re.findall(r"<title>[^<]*</title>", realms))

FEEDS = ["/wrath/status.json", "/wrath/realms.json", "/wrath/mods/all.json", "/wrath/mods/catalog.json", "/wrath/modes.json",
         "/wrath/leyline/flags.json", "/wrath/leyline/hostpack.json", "/wrath/leyline/catalog.json", "/wrath/leyline/mods.json",
         "/wrath/leyline/channel.json", "/wrath/leyline/news.json"]
for path in FEEDS:
    st, hd, body = get(path)
    if not hd.get("content-type", "").startswith("application/json"):
        check(f"{path}: not a JSON feed here ({st}), skipped", True)
        continue
    try:
        doc = json.loads(body)
    except ValueError:
        check(f"{path}: JSON", False, body[:200]); continue
    bad = OLD.findall(json_text(doc))
    if bad and os.environ.get("BRAND_DEBUG"): print("DBG", path, re.findall(r"\"[^\"]*WrathUnleashed[^\"]*\"", body)[:5])
    check(f"{path}: no old names in its text", not bad, bad[:4])
st, _, body = get("/wrath/realms.json")
if st == 200:
    check("realms.json: the network's sample block names Dalaran Hangout", json.loads(body).get("sample", {}).get("name") == "Dalaran Hangout", body[:300])

# the pages made outside the handler's routes (sign-in, account, error, busy)
for label, page in (("sign-in", wp.signed_out_page()), ("auto sign-in", wp.auto_signin_page("n")), ("error", wp.error_page("x")),
                    ("busy", wp.busy_page()), ("stream off", wp.stream_off_page()), ("game data off", wp.gamedata_off_page()),
                    ("browser pass ended", wp.stream_ended_page()), ("account", wp.account_page("Tester", "WR1", "pw", "n"))):
    page = wp.brand_body(page, "text/html")
    bad = OLD.findall(visible(page.decode()))
    check(f"{label} page: no old names", not bad, bad[:4])
acct = wp.account_page("Tester", "WR1", "pw", "n").decode()
check("account page: the player package step names no old brand", "Play</b> file from the player package" in acct)

# /__env.js: the page layer's words
sess = {"user": "WR1", "pass": "pw", "slice": "mini", "tier": 2, "mode": "stream"}
envjs = wp.env_js(sess).decode()
env = json.loads(envjs.split("window.__wenilla_env = ", 1)[1].split(";\n", 1)[0])
check("/__env.js: brand and the home realm's name", env.get("brand") == "leyline" and env.get("home_name") == "Dalaran Hangout", env)
hop = dict(sess, hop={"id": "abcdefghijklmnop", "name": "Frost", "home": False})
env = json.loads(wp.env_js(hop).decode().split("window.__wenilla_env = ", 1)[1].split(";\n", 1)[0])
check("/__env.js in a hop: the brand too", env.get("brand") == "leyline" and env.get("home_name") == "Dalaran Hangout", env)
srv.shutdown()

# the docs (renamed for the public repo): with the brand on the site shows them as written; off, docs.py's UNTIL_FLIP
# table gives back the old words (test_docs.py runs off), and every entry still matches its page
if wp.docs is not None:
    stale = [(n, new) for n, new, old in wp.docs.UNTIL_FLIP
             if new not in open(os.path.join(REPO, "docs", "leyline", n + ".md"), encoding="utf-8").read()]
    check("docs UNTIL_FLIP: every entry matches its page", not stale, stale)
    os.environ["LEYLINE_BRAND"] = "0"
    off = wp.docs.site_text("publishing", "2. Send the link to the Leyline team.")
    os.environ["LEYLINE_BRAND"] = "1"
    check("docs off: the old words", off == "2. Send the link to the WrathUnleashed team.", off)

# ---------------------------------------------------------------- 4. the stream page files
WWW = os.path.join(STREAM, "www-files")
page_js = open(os.path.join(WWW, "wrath-page.js"), encoding="utf-8").read()
check("wrath-page.js: every 'Back to Wrath' people see comes from brand()", "textContent = 'Back to Wrath'" not in page_js
      and ">Back to Wrath<" not in page_js and "words.back" in page_js)
tab = open(os.path.join(WWW, "tab.html"), encoding="utf-8").read()
check("tab.html: names the site from the kept brand", "localStorage.getItem('wu-brand')" in tab and "site + ' is already open" in tab)
# the files the page layer shows text from (a browser test, stream/tests/brand.browser.test.cjs, runs them)
for f in ("wrath-early.js", "wu-loading.js", "ownfiles.js", "sections.js", "touch.js", "wu-addons.js", "boot.js"):
    p = os.path.join(WWW, f)
    if not os.path.exists(p):
        continue
    src = open(p, encoding="utf-8").read()
    lits = re.findall(r"'([^'\n]*)'|\"([^\"\n]*)\"|`([^`]*)`", re.sub(r"(?m)^\s*//.*$|/\*.*?\*/", "", src, flags=re.S))
    bad = [x for t in lits for x in t if x and OLD.search(x) and not x.startswith("[WrathUnleashed]")]
    check(f"{f}: no old names in strings people see (console tags aside)", not bad, bad[:3])

early = open(os.path.join(WWW, "wrath-early.js"), encoding="utf-8").read()
check("wrath-early.js: links leyline-look.css and marks <html> only with the brand on",
      "env.brand === 'leyline'" in early and "./leyline-look.css" in early and "classList.add('ly-brand')" in early)
look = open(os.path.join(WWW, "leyline-look.css"), encoding="utf-8").read()
check("leyline-look.css: every rule outside the spinner waits for html.ly-brand", all(
      sel.strip().startswith(("html.ly-brand", ".ly-spin", "@keyframes", "from", "to")) or not sel.strip()
      for block in re.sub(r"/\*.*?\*/", "", look, flags=re.S).split("}") for sel in [block.split("{")[0].split(",")[0]]
      if "{" in block and not block.strip().startswith("@media")), look[:0])
check("leyline-look.css: no painted art", not PAINTED.search(re.sub(r"/\*.*?\*/", "", look, flags=re.S)))
wpatch = open(os.path.join(STREAM, "server", "www-patch.py"), encoding="utf-8").read()
check("www-patch.py ships leyline-look.css and the logo halves", '"leyline-look.css"' in wpatch and '"leyline-swirl-256.webp"' in wpatch
      and '"leyline-crystal-128.png"' in wpatch)

# ---------------------------------------------------------------- 5. the addon-list .toc swap and WUModCatalog
fo = importlib.util.spec_from_file_location("fo", os.path.join(STREAM, "server", "fui-overlay.py"))
fom = importlib.util.module_from_spec(fo); fo.loader.exec_module(fom)
toc = open(os.path.join(STREAM, "fui-web", "Interface", "AddOns", "WrathUnleashedUI", "WrathUnleashedUI.toc"), encoding="utf-8").read()
on = fom.brand_toc_text(toc, True)
heads = "\n".join(l for l in on.splitlines() if l.startswith(("## Title", "## Notes", "## Author")))
check("toc on: Title, Notes and Author say Leyline", "## Title: Leyline UI" in on and "## Author: Leyline" in on and not OLD.search(heads), heads)
check("toc on: the saved variables keep their names", "## SavedVariables: WrathUnleashedUIDB" in on and "WrathUnleashedUI.lua" in on)
check("toc off: byte for byte back", fom.brand_toc_text(on, False) == toc)
mo = importlib.util.spec_from_file_location("mo", os.path.join(STREAM, "server", "mods-overlay.py"))
mom = importlib.util.module_from_spec(mo); mo.loader.exec_module(mom)
check("mods-overlay.py: the same swap", mom.BRAND_SWAPS == fom.BRAND_SWAPS)
# stream/wu-mod.py is only the copy the signin step makes beside the portal (not in git): check it when it is there.
for wm in [p for p in (os.path.join(STREAM, "wu-mod.py"), os.path.join(REPO, "mods", "wu-mod.py")) if os.path.isfile(p)]:
    out = os.path.join(TMP, "cat-" + str(abs(hash(wm))))
    s = importlib.util.spec_from_file_location("wm", wm); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    os.environ["LEYLINE_BRAND"] = "1"
    m.write_catalog_addon({"mods": []}, out)
    t_on = open(os.path.join(out, m.CATALOG_ADDON, "WUModCatalog.toc"), encoding="utf-8").read()
    os.environ["LEYLINE_BRAND"] = "0"
    m.write_catalog_addon({"mods": []}, out)
    t_off = open(os.path.join(out, m.CATALOG_ADDON, "WUModCatalog.toc"), encoding="utf-8").read()
    os.environ["LEYLINE_BRAND"] = "1"
    check(f"{os.path.relpath(wm, REPO)}: WUModCatalog.toc follows the switch", "Mod list (Leyline)" in t_on and "## Author: Leyline" in t_on
          and t_off == m.CATALOG_TOC and fom.brand_toc_text(t_off, True) == t_on)

# ---------------------------------------------------------------- 6. realm/brand.sh on a fake server
STUB_DOCKER = r'''#!/usr/bin/env bash
S="$FAKE_STATE"
echo "docker $*" >> "$S/calls"
case "$1" in
  exec)
    if [ "$2" = ov-ac-worldserver ] && [ "$3" = printenv ]; then grep -E "^$4=" "$S/live.env" 2>/dev/null | tail -1 | cut -d= -f2-; exit 0; fi
    if [ "$2" = -i ] && [ "$3" = ov-ac-database ]; then
      sql=$(cat); echo "$sql" >> "$S/sql"
      case "$sql" in *"SELECT name FROM acore_auth.realmlist"*) cat "$S/realm-name" ;; *"SELECT COUNT"*) echo 3 ;; esac
      case "$sql" in *"UPDATE acore_auth.realmlist SET name = '"*) echo "$sql" | sed "s/.*SET name = '\([^']*\)'.*/\1/" > "$S/realm-name" ;; esac
      exit 0
    fi
    exit 0 ;;
  run) echo "run $*" >> "$S/runs"; exit 0 ;;
  restart) echo "restart $2" >> "$S/restarts"; exit 0 ;;
esac
exit 0
'''
FAKE_INSTALL = '''#!/usr/bin/env bash
# fake %s: records "brand on|off"
if [ "$1" = brand ]; then echo "%s brand $2" >> "$FAKE_STATE/stream"; fi
'''


def server(brand_aware=True):
    d = tempfile.mkdtemp(prefix="wu-brandsh-")
    w, st, bin_ = os.path.join(d, "wrath"), os.path.join(d, "state"), os.path.join(d, "bin")
    for p in (w, st, bin_, os.path.join(w, "profiles"), os.path.join(w, "custom", "lua_scripts"), os.path.join(w, "portal"),
              os.path.join(w, "stream"), os.path.join(w, "hangout-beacon", "state")):
        os.makedirs(p, exist_ok=True)
    open(os.path.join(w, "profiles", "main.env"), "w").write("OV_MAIN=1\n")
    open(os.path.join(w, "modules.env"), "w").write("AC_X=1\n")
    open(os.path.join(w, "portal.env"), "w").write("REALM_NAME=WrathUnleashed\nSTREAM_SLICES=mini\n")
    open(os.path.join(w, "portal", "wrath_portal.py"), "w").write("LEYLINE_BRAND\n")
    for f in ("ov_modapi.lua", "ov_qol.lua", "ov_main.lua", "ov_reports.lua", "ov_leyline.lua"):
        shutil.copy(os.path.join(REPO, "realm", "custom", "lua_scripts", f), os.path.join(w, "custom", "lua_scripts", f))
    for s in ("fui-install.sh", "mods-install.sh"):
        body = (FAKE_INSTALL % (s, s)) + ("#  brand)\n" if not brand_aware else "case x in\n  brand) ;;\nesac\n")
        open(os.path.join(w, "stream", s), "w").write(body)
    json.dump({"realm_id": "abcdefghijklmnop", "official": True, "record": {"tagline": "Old tagline.", "summary": "Old summary."}},
              open(os.path.join(w, "hangout-beacon", "state", "host.json"), "w"))
    open(os.path.join(st, "realm-name"), "w").write("WrathUnleashed\n")
    for name, body in (("docker", STUB_DOCKER), ("chown", "#!/bin/sh\nexit 0\n")):
        p = os.path.join(bin_, name); open(p, "w").write(body); os.chmod(p, 0o755)
    return d, w, st, bin_


def run(d, w, st, bin_, *args, script="brand.sh", extra=None):
    env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"], WU_DIR=w, FAKE_STATE=st, HOME=d, SAMPLER_WARN_MIN="0",
               **(extra or {}))
    env.pop("LEYLINE_BRAND", None)
    src = open(os.path.join(REPO, "realm", script), encoding="utf-8").read()
    src = src.replace("/root/brand-backups", os.path.join(d, "bk")).replace("/root/sampler-backups", os.path.join(d, "bk"))
    p = os.path.join(d, script); open(p, "w").write(src)
    return subprocess.run(["bash", p, *args], capture_output=True, text=True, env=env, cwd=w)


def read(p, default=""):
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return default


d, w, st, bin_ = server()
flag = os.path.join(w, "custom", "lua_scripts", "leyline-brand.on")
penv = os.path.join(w, "portal.env")
orig_penv = read(penv)
r = run(d, w, st, bin_, "check")
check("brand.sh check: reports success", r.returncode == 0 and r.stdout.rstrip().endswith("BRAND CHECK OK"), r.stdout + r.stderr)
check("brand.sh check: says what would change", "'WrathUnleashed' -> 'Dalaran Hangout'" in r.stdout and "-> 1" in r.stdout
      and "absent -> present" in r.stdout and "fui-install.sh brand on" in r.stdout, r.stdout)
check("brand.sh check: the realm scripts know the switch", all(f"{f} knows the switch" in r.stdout for f in ("ov_modapi.lua", "ov_qol.lua")), r.stdout)
check("brand.sh check: changes nothing", read(penv) == orig_penv and not os.path.exists(flag)
      and "UPDATE" not in read(os.path.join(st, "sql")) and read(os.path.join(st, "realm-name")).strip() == "WrathUnleashed")

r = run(d, w, st, bin_, "on")
check("brand.sh on: reports success", r.returncode == 0 and r.stdout.rstrip().endswith("BRAND OK"), r.stdout + r.stderr)
check("brand.sh on: the realm scripts' flag file", os.path.exists(flag))
check("brand.sh on: the realm list says Dalaran Hangout", read(os.path.join(st, "realm-name")).strip() == "Dalaran Hangout")
check("brand.sh on: the old name kept", read(os.path.join(w, "brand-state", "realm-name.txt")).strip() == "WrathUnleashed")
check("brand.sh on: portal.env LEYLINE_BRAND=1, the rest kept", "LEYLINE_BRAND=1" in read(penv) and "REALM_NAME=WrathUnleashed" in read(penv))
check("brand.sh on: the Leyline front page goes live with it (WU_HUB_FRONT=1)", "WU_HUB_FRONT=1" in read(penv))
check("brand.sh on: wu-portal restarted", "restart wu-portal" in read(os.path.join(st, "restarts")))
check("brand.sh on: the streamed addon names", read(os.path.join(st, "stream")).split() == ["fui-install.sh", "brand", "on", "mods-install.sh", "brand", "on"],
      read(os.path.join(st, "stream")))
bj = json.load(open(os.path.join(w, "hangout-beacon", "state", "beacon.json")))
check("brand.sh on: the hangout's listing text says Leyline", "Leyline" in bj["tagline"] and not OLD.search(bj["tagline"] + bj["summary"]), bj)
check("brand.sh on: the listing text is sent (wuhost.setup rules)", "wuhost.setup rules" in read(os.path.join(st, "runs")))
check("brand.sh on: no world server restart, no reload, nobody kicked",
      "restart ov-ac-worldserver" not in read(os.path.join(st, "restarts")) and "compose" not in read(os.path.join(st, "calls"))
      and "reload" not in read(os.path.join(st, "calls")))
check("brand.sh on: no character row touched", not re.search(r"(UPDATE|DELETE|INSERT)[^;]*characters", read(os.path.join(st, "sql")), re.I))
r = run(d, w, st, bin_, "on")
check("brand.sh on twice: still the real old name", r.returncode == 0 and read(os.path.join(w, "brand-state", "realm-name.txt")).strip() == "WrathUnleashed"
      and read(penv).count("LEYLINE_BRAND=") == 1)
r = run(d, w, st, bin_, "check")
check("brand.sh check while on: says what off would put back", "the brand is ON now" in r.stdout and "'Dalaran Hangout' -> 'WrathUnleashed'" in r.stdout, r.stdout)

# the Sample Hangout while the brand is on: the realm is still Dalaran Hangout
open(os.path.join(w, ".env"), "w").write("OV_PROFILE=main\n")
shutil.copy(os.path.join(REPO, "realm", "profiles", "main.env"), os.path.join(w, "profiles", "main.env"))
shutil.copy(os.path.join(REPO, "realm", "modules.env"), os.path.join(w, "modules.env"))
open(os.path.join(st, "started"), "w").write("1\n")
ov_file = os.path.join(REPO, "realm", "profiles", "sampler.env")
r = run(d, w, st, bin_, "check", ov_file, script="sampler.sh")
check("sampler under the brand: check names Dalaran Hangout", "-> 'Dalaran Hangout'" in r.stdout and "Leyline Sample Hangout'" not in r.stdout.split("realm list name")[1].split("\n")[0], r.stdout[-800:])

r = run(d, w, st, bin_, "off")
check("brand.sh off: reports success", r.returncode == 0 and r.stdout.rstrip().endswith("BRAND OK"), r.stdout + r.stderr)
check("brand.sh off: the flag file is gone", not os.path.exists(flag))
check("brand.sh off: the realm's old name is back", read(os.path.join(st, "realm-name")).strip() == "WrathUnleashed")
check("brand.sh off: portal.env LEYLINE_BRAND=0", "LEYLINE_BRAND=0" in read(penv))
check("brand.sh off: the front page hidden again (WU_HUB_FRONT=0)", "WU_HUB_FRONT=0" in read(penv))
check("brand.sh off: the streamed addon names back", read(os.path.join(st, "stream")).split()[-6:] == ["fui-install.sh", "brand", "off", "mods-install.sh", "brand", "off"])
bj = json.load(open(os.path.join(w, "hangout-beacon", "state", "beacon.json")))
check("brand.sh off: the hangout's own listing text again (beacon.json as before: no text of its own)",
      "tagline" not in bj and "summary" not in bj, bj)
shutil.rmtree(d, ignore_errors=True)

# older stream scripts: said, not run
d, w, st, bin_ = server(brand_aware=False)
r = run(d, w, st, bin_, "on")
check("brand.sh with older stream scripts: still OK, says to run the steps first", r.returncode == 0 and "older than the switch" in r.stdout
      and not read(os.path.join(st, "stream")), r.stdout)
shutil.rmtree(d, ignore_errors=True)

check("brand.sh: bad usage refused", run(*server(), "maybe").returncode == 1)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
