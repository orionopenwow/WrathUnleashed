"""The hidden Leyline hub (stream/hub.py) on the portal: every route answers 200 with noindex (meta and
X-Robots-Tag), the catalog merges the Workshop, the community index and themes (a duplicate shows once), "Submit a
mod" queues without personal data, the admin console's decisions apply (approved.json, delist), the launcher feed
keeps the all.json shape, the front-door switch, and no current page links to the preview.

    python3 -I stream/tests/test_hub.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, sys, tempfile, threading
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
         "/wrath/leyline-preview/p/" + first["id"].replace(":", "-"), "/wrath/leyline-preview/p/theme-night-sky"]
for p in pages:
    st, h, b = req(p)
    s = b.decode()
    check(f"GET {p}: 200 html", st == 200 and h.get("content-type", "").startswith("text/html"), st)
    check(f"GET {p}: noindex header and meta", h.get("x-robots-tag") == "noindex, nofollow"
          and '<meta name="robots" content="noindex">' in s)
    check(f"GET {p}: no script, no brand words", "<script" not in s and "script-src 'none'" in h.get("content-security-policy", "")
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
check("front page: every offered build with a count", all(f"/wrath/leyline-preview/catalog?build={b}" in front for b in HB.offered_builds()))
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
check("front page: the 12 categories and themes", all(f"catalog?cat={c}" in front for c in HB.CATEGORY_IDS + ["themes"]))
check("front page: creators and Host a Beacon", "/wrath/leyline-preview/creators" in front and "/wrath/leyline-preview/beacon" in front)
check("front page: a TODO(owner) for the tagline, no words in the owner's voice", "TODO(owner)" in front)
# the owner's mockup (2026-10-30): header nav, the hero, Platform Status, Community Spotlight, the footer
nav = re.search(r'<nav class="hb-nav"[^>]*>(.*?)</nav>', front, re.S).group(1)
check("header: Features, Download, Community, Status, Docs", re.findall(r">([^<]+)</a>", nav) == ["Features", "Download", "Community", "Status", "Docs"], nav)
check("hero: the crystal over the turning swirl, the heading, three bullets, Download Now",
      'class="ly-spin slow hb-swirl"' in front and "leyline-crystal-512.png" in front and "Every client, every server" in front
      and front.count("<li>", front.index('class="hb-bullets"'), front.index("</ul>", front.index('class="hb-bullets"'))) == 3
      and "1.12.1, 2.4.3 and 3.3.5a" in front and "4.3.4" not in visible(front) and "5.4.8" not in visible(front)
      and re.search(r'class="hb-cta" href="https://github\.com/orionopenwow/Leyline/releases"[^>]*>Download Now<', front))
stats = re.search(r'<section class="hb-sec" id="status".*?</section>', front, re.S).group(0)
check("Platform Status: the main realm online from realm_status, sign-in, the network, the relay, the mod catalog",
      all(x in stats for x in ('Server: <em class="ok">OK</em> · 3 playing', "Sign-in", "Realm network", "Relay", "Mod catalog", " items · "))
      and '<em class="ok">OK</em>' in stats, stats)
check("Platform Status: a failing source is red, never a made-up OK", '<em class="bad">' in stats and "Game logins:" in stats)
check("Platform Status: no client downloads (we never download clients)", "Client" not in stats and "download" not in stats.lower())
spot = re.search(r'<section class="hb-sec" id="community".*?</section>', front, re.S).group(0)
spots = re.findall(r'<a class="hb-spot" href="/wrath/leyline-preview/p/([^"]+)">.*?<b>([^<]+)</b><i>by ([^<]+)</i>', spot, re.S)
names = {e["id"].replace(":", "-"): (e["name"], e["author"]) for e in INDEX["entries"]}
check("Community Spotlight: two to four real items, with their own names and authors", 2 <= len(spots) <= 4
      and all(names.get(slug) == (n, a) for slug, n, a in spots if slug in names) and any(slug in names for slug, _, _ in spots), spots)
foot = re.search(r'<footer class="hb-foot">.*?</footer>', front, re.S).group(0)
check("footer: Docs, Download, Community, Status, the wordmark, Discord and GitHub only",
      all(f">{x}<" in foot for x in ("Docs", "Download", "Community", "Status", "Discord", "GitHub")) and "<b>Leyline</b>" in foot)
os.environ["WU_LEYLINE_DIR"] = os.path.join(DATA, "leyline")
os.makedirs(os.environ["WU_LEYLINE_DIR"], exist_ok=True)
rel = "https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.4.0"
json.dump({"stable": {"version": "0.4.0", "tag": "launcher-v0.4.0", "url": rel}}, open(os.path.join(os.environ["WU_LEYLINE_DIR"], "channel.json"), "w"))
if wp.admin is not None and hasattr(wp.admin, "leyline_dir"):
    check("Download Now: the stable release the admin console published", f'href="{rel}"' in req("/wrath/leyline-preview")[2].decode())
json.dump({"stable": {"version": "0.4.0", "tag": "x", "url": "https://evil.example/x"}}, open(os.path.join(os.environ["WU_LEYLINE_DIR"], "channel.json"), "w"))
check("Download Now: never a link off the releases page", "evil.example" not in req("/wrath/leyline-preview")[2].decode())
cat = req("/wrath/leyline-preview/catalog?build=2.4.3")[2].decode()
check("catalog: filtered by build", all(("2.4.3" in e["builds"] or "any" in e["builds"]) for e in INDEX["entries"]
                                      if f'/p/{e["id"].replace(":", "-")}"' in cat) and "2.4.3" in cat)
cata = req("/wrath/leyline-preview/catalog?build=5.4.8")[2].decode()
check("catalog: no item made only for 4.3.4 / 5.4.8", not any(
    f'/p/{e["id"].replace(":", "-")}"' in cata for e in INDEX["entries"] if not set(e["builds"]) & {"1.12", "2.4.3", "3.3.5a", "any"}))
junk = req("/wrath/leyline-preview/catalog?q=%3Cscript%3E")[2].decode()
check("catalog: the query is escaped", "<script>" not in junk and "&lt;script&gt;" in junk)
item = req("/wrath/leyline-preview/p/" + first["id"].replace(":", "-"))[2].decode()
check("item: View source, credit, licence, no Install", "View source on GitHub" in item and first["licence"] in item
      and 'rel="noopener noreferrer nofollow ugc"' in item and ">Install<" not in item and "/download" not in item)
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
os.environ["WU_HUB_FRONT"] = "1"
st, h, b = req("/wrath/leyline")
s = b.decode()
check("switch on: /wrath/leyline is the hub's front page, indexable", st == 200 and 'class="hb-top"' in s
      and "x-robots-tag" not in h and 'content="noindex"' not in s and "Preview:" not in s)
os.environ.pop("WU_HUB_FRONT")
os.environ["WU_HUB"] = "0"
check("WU_HUB=0: the preview is off", req("/wrath/leyline-preview")[0] == 404 and req("/wrath/leyline/catalog.json")[0] == 404)
os.environ.pop("WU_HUB")

# ---------------------------------------------------------------- shipping
bat = open(os.path.join(HERE, "Update sign-in and warm-up.bat"), encoding="utf-8").read()
fl = open(os.path.join(HERE, "fastloop.sh"), encoding="utf-8").read()
check("sign-in bat: packs hub.py and hub/", 'if exist hub.py if exist hub\\community-index.json set "LINKS=%LINKS% hub.py hub"' in bat
      and " hub.py " in re.search(r"\$\(ls ([^)]*)\)", bat).group(0))
check("fastloop.sh: installs hub.py and its data, backs them up, puts them back", 'install -m 644 hub.py "$WU/portal/hub.py"' in fl
      and '"$BK/hub.py"' in fl and 'install -m 644 hub/*.json "$WU/portal/hub/"' in fl)
check("the index in the repo passes the hub's rules", HB.validate_index(json.load(open(os.path.join(HERE, "hub", "community-index.json")))) == [])

srv.shutdown()
shutil.rmtree(DATA, ignore_errors=True)
shutil.rmtree(HUBDIR, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
