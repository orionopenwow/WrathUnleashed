"""Leyline hub rankings (stream/hub_rank.py) on the real portal (stream/wrath_portal.py): the formulas on fixed
fixtures (Hot decay, Rising with its minimum, the Bayesian Top rated, outlier damping, New and Recently updated),
the anonymous install ping (dedupe per install id and day, the per-address caps, no IP or install id kept in clear),
ratings (website sign-in + CSRF, the launcher's Bearer token, one per account and changeable, rate limits, the item
page's plain form), the public mods.json API (sorts, client and kind filters, CORS) and the hub pages' sort tabs.

    python3 -I stream/tests/test_hub_rank.py stream/wrath_portal.py
"""
import hashlib, http.client, importlib.util, json, os, re, secrets, shutil, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
HERE = os.path.dirname(PORTAL)
DATA = tempfile.mkdtemp(prefix="wu-rank-data-")
HUBDIR = tempfile.mkdtemp(prefix="wu-rank-hub-")
shutil.copy(os.path.join(HERE, "hub", "community-index.json"), HUBDIR)
SHA = "ab" * 32
json.dump({"format": 1, "themes": [
    {"id": "night-sky", "name": "Night Sky", "description": "Deep blue and stars.", "author": "Leyline", "licence": "CC-BY-4.0",
     "download": "https://play.example/wrath/themes/night-sky.zip", "sha256": SHA, "updated": "2026-10-20"},
    {"id": "ember", "name": "Ember", "description": "Warm.", "author": "Leyline", "licence": "CC0-1.0"}]},
    open(os.path.join(HUBDIR, "themes.json"), "w"))

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS", name)
    else:
        failed += 1; print("FAIL", name, extra)


ACCOUNTS = {"alice": ("Alice", "WR000001"), "bob": ("Bob", "WR000002"), "carol": ("Carol", "WR000003")}


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        m = re.search(r"wr_session=(\w+)", self.headers.get("Cookie", ""))
        acct = ACCOUNTS.get(m.group(1)) if m else None
        if not acct:
            self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = {"/api/me": {"display_name": acct[0]}, "/api/play": {"user": acct[1], "pass": "x" * 16}}[self.path]
        b = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


SITE = serve(Site)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL=f"http://127.0.0.1:{SITE}",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example",
                  WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_PORTAL_DATA=DATA, WU_HUB_DIR=HUBDIR,
                  WU_MODS_DIR=tempfile.mkdtemp(), WU_WORKSHOP_ITEMS_DIR=tempfile.mkdtemp(), WU_HUB_RANK_TTL="0")
for k in ("WU_HUB_FRONT", "WU_HUB", "WU_HUB_RANK"):
    os.environ.pop(k, None)
spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)
RK = wp.hub_rank
check("hub_rank.py loaded beside the portal, its store in WU_PORTAL_DATA", RK is not None and RK.store is not None
      and os.path.isfile(os.path.join(DATA, "hub_rank.sqlite3")))
if RK is None or RK.store is None:
    print(f"\n{passed}/{passed + failed} passed"); sys.exit(1)
SOC = wp.social.setup(start_thread=False)

# ================================================================ the formulas, on fixed fixtures
T = 20400            # "today" as a day number
NOW = T * 86400 + 3600


def it(i, **kw):
    d = {"id": i, "name": i.split(":")[1], "source": "index", "builds": ["3.3.5a"], "category": "addons", "type": "addon"}
    d.update(kw)
    return d


items = [it("link:aaaaaaaaaaaa"), it("link:bbbbbbbbbbbb"), it("link:cccccccccccc"), it("link:dddddddddddd"),
         it("link:eeeeeeeeeeee"), it("link:ffffffffffff"), it("link:999999999999")]
inst = []
inst += [("link:aaaaaaaaaaaa", T - k, 10) for k in range(7)]                      # steady 10 a day
inst += [("link:bbbbbbbbbbbb", T - k, 2) for k in range(7, 14)] + [("link:bbbbbbbbbbbb", T - k, 1) for k in range(7)]
inst += [("link:cccccccccccc", T - 1, 3), ("link:cccccccccccc", T, 3)]            # 6 this week, none before
inst += [("link:dddddddddddd", T, 1000)]                                          # a one-day flood
inst += [("link:eeeeeeeeeeee", T - 9, 8)]                                          # 8, nine days ago
inst += [("link:ffffffffffff", T, 1)]
rats = [("link:eeeeeeeeeeee", 5, NOW)] + [("link:ffffffffffff", 5 if k % 2 else 4, NOW - 86400 * 40) for k in range(20)]
M = RK.compute(items, inst, rats, {"link:999999999999": T, "link:aaaaaaaaaaaa": T - 30}, T)
a, b, c, d, e_, f = (M[x] for x in ("link:aaaaaaaaaaaa", "link:bbbbbbbbbbbb", "link:cccccccccccc", "link:dddddddddddd",
                                     "link:eeeeeeeeeeee", "link:ffffffffffff"))
check("installs: all time, 30 days, this week", a["installs"] == {"all": 70, "d30": 70, "d7": 70, "prev7": 0}, a["installs"])
check("rising: needs RISING_MIN installs this week and growth", c["rising"] is not None and abs(c["rising"] - 1.1375) < 1e-3
      and b["rising"] is None and f["rising"] is None, (c["rising"], b["rising"]))
check("rising: a steady 10 a day (from nothing) beats 6 from nothing", a["rising"] > c["rising"])
check("damping: a 1000-install day with no history counts as 25 + sqrt(975)", d["installs"]["all"] == round(25 + 975 ** .5),
      d["installs"])
check("damping keeps a real climb: 30/day after a month at 20/day counts in full",
      RK.damp_series({T - k: 20 for k in range(1, 29)} | {T: 30})[T] == 30.0)
check("damping: the cap follows the mod's own median (4 x 20 = 80)", abs(RK.damp_series({T - k: 20 for k in range(1, 29)} | {T: 180})[T]
                                                                       - (80 + 100 ** .5)) < 1e-9)
hot_e = RK.compute([items[4]], [("link:eeeeeeeeeeee", T - 9, 8)], [], {}, T)["link:eeeeeeeeeeee"]["hot"]
hot_now = RK.compute([items[4]], [("link:eeeeeeeeeeee", T, 1)], [], {}, T)["link:eeeeeeeeeeee"]["hot"]
check("hot: 8 installs nine days ago weigh what 1 does today (half-life 3 days)", abs(hot_e - hot_now) < 1e-9, (hot_e, hot_now))
check("hot: a 5-star rating today pushes like 4 installs", abs(RK.compute([items[0]], [], [("link:aaaaaaaaaaaa", 5, NOW)], {}, T)
                                                               ["link:aaaaaaaaaaaa"]["hot"] - __import__("math").log10(5)) < 1e-3)
check("hot: a fresh update adds up to 0.5", abs(RK.compute([it("link:aaaaaaaaaaaa", updated=RK._day_str(T))], [], [], {}, T)
                                                ["link:aaaaaaaaaaaa"]["hot"] - 0.5) < 1e-9)
prior = (5 + 20 * 4.5 + 3.5 * 10) / (21 + 10)
check("top rated: Bayesian (C=5, prior = the site mean blended with 3.5 over 10)",
      abs(e_["rating"]["score"] - (5 * prior + 5) / 6) < 1e-3 and abs(f["rating"]["score"] - (5 * prior + 90) / 25) < 1e-3,
      (e_["rating"], f["rating"], prior))
check("top rated: one 5-star rating does not top twenty at 4.5", f["rating"]["score"] > e_["rating"]["score"]
      and e_["rating"]["avg"] == 5.0 and f["rating"]["avg"] == 4.5)
order = lambda s: [i["id"][5:7] for i, _ in sorted(((i, M[i["id"]]) for i in items), key=lambda p: RK.sort_key(s, p[1], p[0]))]  # noqa: E731
check("sort top: rated first by the Bayesian score, unrated after", order("top")[:2] == ["ff", "ee"], order("top"))
check("sort rising: only risers first (the flood rises too, damped)", order("rising")[:3] == ["aa", "dd", "cc"], order("rising"))
check("sort installs: all time", order("installs")[0] == "aa" and order("installs")[1] == "dd", order("installs"))
check("sort new: newest first seen first, unknown dates last", order("new")[:2] == ["99", "aa"], order("new"))
check("4.3.4 / 5.4.8 not offered for now: read as no client", RK.client_tag("4.3.4") == "" and RK.client_tag("18414") == ""
      and RK.HIDDEN_CLIENTS == ("4.3.4", "5.4.8"))
os.environ["LEYLINE_ALL_CLIENTS"] = "1"
check("the override counts them again", RK.client_tag("15595") == "4.3.4")
del os.environ["LEYLINE_ALL_CLIENTS"]
check("build/kind helpers", RK.client_tag("12340") == "3.3.5a" and RK.client_tag("1.12.1") == "1.12" and RK.client_tag("9.9") == ""
      and RK.kind_of({"source": "theme"}) == "theme" and RK.kind_of({"category": "sandbox"}) == "mode"
      and RK.kind_of({"type": "addon"}) == "addon" and RK.kind_of({"type": "module", "category": "tools"}) == "mod")

# ================================================================ the portal
PAGE = serve(wp.PageHandler)


def call(method, path, body=None, sess=None, token=None, headers=None, ip="10.1.0.1", ctype=None):
    cn = http.client.HTTPConnection("127.0.0.1", PAGE, timeout=30)
    h = {"X-Forwarded-For": ip, **(headers or {})}
    if sess:
        h["Cookie"] = f"wr_session={sess}"
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        h["Content-Type"] = ctype or ("application/x-www-form-urlencoded" if isinstance(body, str) else "application/json")
    cn.request(method, path, body=data, headers=h)
    r = cn.getresponse()
    raw = r.read()
    try:
        doc = json.loads(raw)
    except ValueError:
        doc = raw.decode("utf-8", "replace")
    return r.status, doc, {k.lower(): v for k, v in r.getheaders()}


THEME = "theme:night-sky"
INDEX = json.load(open(os.path.join(HUBDIR, "community-index.json")))["entries"]
LINK = INDEX[0]["id"]
iid = lambda: secrets.token_urlsafe(16)   # noqa: E731

# ---- the install ping
st, doc, _ = call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": "short", "build": "3.3.5a"})
check("install: a bad install id is 400", st == 400, (st, doc))
st, doc, _ = call("POST", "/wrath/api/hub/install", {"id": "mod:nope-not-here", "iid": iid()})
check("install: an id not in the catalog is 404", st == 404)
st, doc, _ = call("POST", "/wrath/api/hub/install", "id=theme%3Anight-sky&iid=" + iid())
check("install: a form post (what another site could send) is refused", st == 415, st)
st, doc, _ = call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": iid()}, ctype="text/plain")
check("install: text/plain is refused too", st == 415)
one = iid()
raw_ids = [one]
st, doc, _ = call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": one, "build": "12340", "via": "launcher"})
check("install: counted", st == 200 and doc == {"ok": True, "counted": True}, (st, doc))
st, doc, _ = call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": one, "build": "12340"})
check("install: the same install id again the same day is not counted", st == 200 and doc["counted"] is False)
two = iid(); raw_ids.append(two)
check("install: a second install from the same address counts",
      call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": two})[1]["counted"] is True)
three = iid(); raw_ids.append(three)
check("install: a third of the same mod from the same address today is answered but not counted",
      call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": three})[1]["counted"] is False)
four = iid(); raw_ids.append(four)
check("install: another address counts", call("POST", "/wrath/api/hub/install", {"id": THEME, "iid": four}, ip="10.1.0.2")[1]["counted"])
codes = [call("POST", "/wrath/api/hub/install", {"id": LINK, "iid": iid()}, ip="10.1.0.3")[0] for _ in range(RK.INSTALL_PER_IP_HOUR + 1)]
check(f"install: {RK.INSTALL_PER_IP_HOUR} pings an hour from one address, then 429", codes[:-1] == [200] * RK.INSTALL_PER_IP_HOUR
      and codes[-1] == 429, codes[-3:])
st, doc, h = call("GET", "/wrath/leyline/mods.json?sort=installs&kind=theme")
nsky = next(x for x in doc["items"] if x["id"] == THEME)
check("mods.json: the installs show", nsky["installs"]["all"] == 3 and nsky["installs"]["d7"] == 3, nsky["installs"])
blob = open(os.path.join(DATA, "hub_rank.sqlite3"), "rb").read()
check("privacy: no IP address and no raw install id in the store", all(x.encode() not in blob for x in
      ["10.1.0.1", "10.1.0.2", "10.1.0.3", "127.0.0.1"] + raw_ids))
check("privacy: the IP hash is salted per day in memory only", RK.store.ip_hash("10.1.0.1") == RK.store.ip_hash("10.1.0.1")
      and RK.store._salt.hex() not in blob.hex())

# ---- ratings
st, doc, _ = call("GET", "/wrath/api/hub/me?id=" + THEME)
check("me: signed out says so", st == 200 and doc["signed_in"] is False and doc["mine"] == 0, (st, doc))
st, doc, _ = call("GET", "/wrath/api/hub/me?id=link:nope")
check("me: unknown id 404", st == 404)
st, me, _ = call("GET", "/wrath/api/hub/me?id=" + THEME, sess="alice")
check("me: signed in, with a CSRF token", st == 200 and me["signed_in"] and len(me.get("csrf", "")) == 32, me)
csrf = me["csrf"]
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 4})
check("rate: signed out is 401", st == 401)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 4}, sess="alice")
check("rate: without the CSRF header 403", st == 403)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 4}, sess="alice",
                  headers={"X-Leyline-CSRF": csrf, "Origin": "https://evil.example"})
check("rate: from another origin 403", st == 403)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 4}, sess="alice",
                  headers={"X-Leyline-CSRF": csrf, "Sec-Fetch-Site": "cross-site"})
check("rate: cross-site 403", st == 403)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 4}, sess="bob", headers={"X-Leyline-CSRF": csrf})
check("rate: someone else's CSRF token 403", st == 403)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 9}, sess="alice", headers={"X-Leyline-CSRF": csrf})
check("rate: 9 stars is 400", st == 400)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 4}, sess="alice", headers={"X-Leyline-CSRF": csrf})
check("rate: saved", st == 200 and doc["mine"] == 4 and doc["rating"]["n"] == 1 and doc["rating"]["avg"] == 4.0, doc)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 2}, sess="alice", headers={"X-Leyline-CSRF": csrf})
check("rate: changeable, still one per account", doc["mine"] == 2 and doc["rating"]["n"] == 1 and doc["rating"]["avg"] == 2.0, doc)
tok = secrets.token_urlsafe(32)
SOC.ensure("WR000002", "Bob")
SOC.x("INSERT INTO social_tokens (hash, acct, label, created, used) VALUES (?,?,?,?,?)",
      (hashlib.sha256(tok.encode()).hexdigest(), "WR000002", "test", SOC.now(), SOC.now()))
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 5}, token=tok)
check("rate: the launcher's friends token works (no CSRF needed for a Bearer)", st == 200 and doc["rating"]["n"] == 2
      and doc["rating"]["avg"] == 3.5, (st, doc))
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 5}, token="x" * 43)
check("rate: a bad token is 401", st == 401)
st, doc, _ = call("GET", "/wrath/api/hub/me?id=" + THEME, token=tok)
check("me: by token, no csrf in the reply", doc["signed_in"] and doc["mine"] == 5 and "csrf" not in doc, doc)
st, doc, _ = call("POST", "/wrath/api/hub/rate", {"id": THEME, "stars": 0}, token=tok)
check("rate: 0 takes it back", doc["mine"] == 0 and doc["rating"]["n"] == 1)
blob = open(os.path.join(DATA, "hub_rank.sqlite3"), "rb").read()
check("privacy: no account name in clear", b"WR000001" not in blob and b"WR000002" not in blob)
st, carol, _ = call("GET", "/wrath/api/hub/me?id=" + LINK, sess="carol")
codes = [call("POST", "/wrath/api/hub/rate", {"id": LINK, "stars": 1 + k % 5}, sess="carol",
              headers={"X-Leyline-CSRF": carol["csrf"]}, ip="10.2.0.1")[0] for k in range(RK.RATE_PER_ACCT_HOUR + 1)]
check(f"rate: {RK.RATE_PER_ACCT_HOUR} ratings an hour per account, then 429", codes[-1] == 429 and set(codes[:-1]) == {200}, codes[-3:])

# ---- the item page: Install with Leyline and the plain rating form
st, page, h = call("GET", "/wrath/leyline-preview/p/theme-night-sky", sess="alice")
check("item page: Install with Leyline (leyline://install/<id>) for an installable item",
      st == 200 and 'href="leyline://install/theme:night-sky"' in page and "Install with Leyline" in page)
check("item page: still noindex, still no script", h.get("x-robots-tag") == "noindex, nofollow" and "<script" not in page)
m = re.search(r'name="t" value="([0-9a-f]{32})"', page)
check("item page: a rating form for the signed-in viewer", m is not None and 'action="/wrath/api/hub/rate"' in page)
st, _, h = call("POST", "/wrath/api/hub/rate", f"id=theme%3Anight-sky&stars=5&t={m.group(1) if m else ''}", sess="alice")
check("item form: saved, back to the page", st == 303 and h["location"].startswith("/wrath/leyline-preview/p/theme-night-sky?rated="), (st, h))
check("item form: the rating counts", RK.store.mine(THEME, "WR000001") == 5)
st, _, h = call("POST", "/wrath/api/hub/rate", "id=theme%3Anight-sky&stars=1&t=" + "0" * 32, sess="alice")
check("item form: a wrong token is refused (sent back with a note)", st == 303 and "Reload" in urllib.parse.unquote(h["location"])
      and RK.store.mine(THEME, "WR000001") == 5)
st, page, _ = call("GET", "/wrath/leyline-preview/p/" + LINK.replace(":", "-"))
check("item page: a community link has no Install button, signed out sees Sign in to rate",
      "leyline://" not in page and "Sign in</a> to rate" in page)
st, page, _ = call("GET", "/wrath/leyline-preview/p/theme-ember")
check("item page: a theme without a download has no Install button", st == 200 and "leyline://" not in page)

# ---- mods.json
st, doc, h = call("GET", "/wrath/leyline/mods.json")
check("mods.json: public, CORS *, hot by default", st == 200 and h.get("access-control-allow-origin") == "*" and doc["sort"] == "hot"
      and doc["total"] == len(doc["items"]) or doc["total"] > 50, (st, doc.get("sort")))
x = doc["items"][0]
check("mods.json: each item has its metrics", {"id", "name", "kind", "builds", "installs", "rating", "hot", "rising", "new",
                                               "updated", "installable", "page", "rank"} <= set(x), sorted(x))
for s in RK.SORTS:
    st, d2, _ = call("GET", f"/wrath/leyline/mods.json?sort={s}&limit=5")
    check(f"mods.json: sort={s}", st == 200 and d2["sort"] == s and len(d2["items"]) <= 5 and [i["rank"] for i in d2["items"]] == list(range(1, len(d2["items"]) + 1)))
st, d2, _ = call("GET", "/wrath/leyline/mods.json?sort=installs&window=30")
check("mods.json: installs&window=30 is installs30", d2["sort"] == "installs30")
st, d2, _ = call("GET", "/wrath/leyline/mods.json?sort=<x>&kind=nope&client=9.9")
check("mods.json: junk falls back (hot, every kind, every client)", d2["sort"] == "hot" and d2["kind"] is None and d2["client"] is None)
st, d2, _ = call("GET", "/wrath/leyline/mods.json?client=5875&limit=200")
check("mods.json: client=5875 lists only what fits 1.12", d2["client"] == "1.12" and d2["items"]
      and all("1.12" in i["builds"] or "any" in i["builds"] for i in d2["items"]))
st, d2, _ = call("GET", "/wrath/leyline/mods.json?kind=addon&limit=200")
check("mods.json: kind=addon", d2["items"] and all(i["kind"] == "addon" for i in d2["items"]))
st, d2, _ = call("GET", "/wrath/leyline/mods.json?sort=top&kind=theme")
check("mods.json: top rated themes, the rated one first, with its install link",
      d2["items"][0]["id"] == THEME and d2["items"][0]["install"] == "leyline://install/theme:night-sky"
      and d2["items"][0]["rating"]["n"] >= 1, d2["items"][:1])
st, d2, _ = call("GET", "/wrath/leyline/mods.json?limit=2&offset=1")
check("mods.json: paging", d2["offset"] == 1 and d2["items"][0]["rank"] == 2 and len(d2["items"]) == 2)
check("mods.json: no brand words in names", not any(re.search(r"(?i)\bwow\b|warcraft|blizzard", i["name"] + i["summary"])
                                                     for i in call("GET", "/wrath/leyline/mods.json?limit=200")[1]["items"]))

# ---- the hub catalog's sort tabs and kind filter
st, page, h = call("GET", "/wrath/leyline-preview/catalog?sort=top&kind=theme")
check("catalog: sort tabs (Hot, Rising, Top rated, Most installed, New, Recently updated) and kinds",
      all(t in page for t in ("Hot", "Rising", "Top rated", "Most installed", "New", "Recently updated", "Game modes")) and
      'role="tablist"' in page and h.get("x-robots-tag") == "noindex, nofollow")
check("catalog: kind=theme lists themes only, rated first", page.find("Night Sky") != -1 and
      (page.find("Ember") == -1 or page.find("Night Sky") < page.find("Ember")) and "/p/link-" not in page)
check("catalog: the cards show ratings and installs", "installs" in page and "of 5" in page)
st, page, _ = call("GET", "/wrath/leyline-preview/catalog?sort=rising")
check("catalog: sort=rising answers", st == 200 and "<script" not in page)

# ---- off switch
os.environ["WU_HUB_RANK"] = "0"
check("WU_HUB_RANK=0: the routes are not matched", not RK.match("/wrath/leyline/mods.json"))
os.environ.pop("WU_HUB_RANK")

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
