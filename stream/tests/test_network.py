"""The Leyline network (stream/network.py hooked into wrath_portal.py): community realms first in the fair order,
the Leyline Sample Hangout pinned below the featured ones, filters, the network line, Host your own, the uptime and
verified badges, /wrath/realms.json for the launcher and the in-game list, player reports on a realm and the admin
console acting on them, and the hub's realm pages. A fake relay listing, a fake website sign-in.

    python3 -I stream/tests/test_network.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RELAY_PORT, PAGE_PORT = 18193, 18194
DATA = tempfile.mkdtemp()
HANG, FEAT, PLAIN, BUSY, SLEEPY, HIDDEN, OLD = ("hangouthangout22", "featuredfeatured", "plainplainplainp",
                                               "busybusybusybusy", "sleepysleepysle2", "hiddenhiddenhidd", "oldoldoldoldoldo")
os.makedirs(os.path.join(DATA, "admin"))
with open(os.path.join(DATA, "admin", "realm-overrides.json"), "w") as f:
    json.dump({"format": 1, "realms": {FEAT: {"featured": True, "verified": True}, HIDDEN: {"hidden": True},
                                       BUSY: {"verified": True}}}, f)
os.environ.update(WU_SAMPLER="1", SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_PORTAL_DATA=DATA, WU_HANGOUT_REALM=HANG,
                  WU_RELAY_LISTING=f"http://127.0.0.1:{RELAY_PORT}/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.example", WU_ADMIN_OWNERS="owner1")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1] if len(sys.argv) > 1 else "stream/wrath_portal.py")
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
net = wp.network
assert net is not None, "stream/network.py did not load"


def rec(rid, name, live=True, players=0, bots=0, score=0.0, tags=(), region=None, lang=None, build=12340, up=(None, None),
        new=False, est=None, maxp=None):
    return {"schema": 1, "slug": "c-" + rid, "name": name, "official": False, "state": "live" if live else "offline",
            "tagline": "", "type": "PvE", "tags": list(tags), "region": region, "language": lang, "maxPlayers": maxp,
            "profile": {"ruleset": "main", "build": build, "core": "azerothcore", "address": "relay.example", "port": 40002},
            "community": {"realmId": rid, "relay": "relay.example", "claimed": True, "score": score, "new": new,
                          "uptime": {"h24": up[0], "d7": up[1]}, "regionEstimate": est,
                          "lastHeartbeat": {"online": live, "players": players, "bots": bots}}}


LISTING = {"schema": 1, "kind": "community", "realms": [
    rec(BUSY, "Busy Den", players=30, bots=40, score=80.5, tags=["pvp", "bots"], region="na-east", lang="en", up=(99, 98)),
    rec(HANG, "Wrath Unleashed", players=1, bots=30, score=60, tags=["hangout"]),
    rec(PLAIN, "Plain Field", players=0, score=30, tags=["rp"], lang="de", est="eu", up=(70, 60), new=True, maxp=50),
    rec(FEAT, "Picked One", players=2, score=12, tags=["blizzlike", "pvp"], region="eu", build=5875, up=(95, 96)),
    rec(SLEEPY, "Sleepy Hollow", live=False, players=0, score=0),
    rec(HIDDEN, "Hidden Away", players=9, score=99),
    rec("brandbrandbrandb", "WoW Warcraft Den", live=False, players=0, score=0),   # an older relay: no word filter
    {"name": "Old relay record", "state": "live", "profile": {"ruleset": "main"},     # a relay from before 2026-10-29
     "community": {"realmId": OLD, "lastHeartbeat": {"online": True, "players": 3, "bots": 0}}},
    {"name": "junk", "community": {"realmId": "../x"}, "tags": "pvp"},
]}


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        body = json.dumps(LISTING).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


wp.realm_status = lambda: {"online": True, "players": 4, "bots": 10, "updated_at": time.time()}


def fake_portal_get(path, cookie, ip, ua):
    m = re.search(r"wr_session=(\w+)", cookie)
    if not m:
        return 401, {}
    who = m.group(1)
    if path == "/api/me":
        return 200, {"id": who, "display_name": who.title()}
    return 200, {"user": who.upper()[:16]}


wp.portal_get = fake_portal_get
for port, h in ((RELAY_PORT, Relay), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, cookie="", body=None, ip="10.0.0.7", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
    hd = {"X-Forwarded-For": ip}
    if cookie:
        hd["Cookie"] = "wr_session=" + cookie
    if body is not None:
        body = urllib.parse.urlencode(body)
        hd["Content-Type"] = "application/x-www-form-urlencoded"
    hd.update(headers or {})
    c.request(method, path, body=body, headers=hd)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


# ---------------------------------------------------------------- the module on its own
x = net.extra({"tags": ["pvp", "evil", 3, "PVP"], "region": "mars", "language": "<b>", "maxPlayers": 10**7,
               "profile": {"build": True, "core": "rm -rf", "port": 99999},
               "community": {"score": float("nan"), "uptime": {"h24": 101, "d7": -1}, "regionEstimate": "eu",
                             "relay": "evil.example:22/x"}})
check("extra: every field checked", x["tags"] == ["pvp"] and x["region"] is None and x["language"] is None
      and x["max_players"] is None and x["build"] == 12340 and x["core"] == "azerothcore" and x["port"] is None
      and x["score"] == 0.0 and x["up24"] is None and x["up7"] is None and x["region_est"] == "eu" and x["relay"] is None)
check("region: the host's choice, else the relay's estimate", net.region_of({"region": "asia", "region_est": "eu"}) == ("asia", False)
      and net.region_of({"region_est": "eu"}) == ("eu", True) and net.region_of({}) == (None, False))
o = net.order([{"id": "a", "name": "A", "live": True, "score": 10}, {"id": "b", "name": "B", "live": True, "score": 50},
               {"id": "c", "name": "C", "live": True, "score": 1, "featured": True},
               {"id": "d", "name": "D", "live": True, "score": 90, "hangout": True},
               {"id": "e", "name": "E", "live": False, "score": 0, "featured": True}])
check("order: featured, the sample, then by score, offline (featured or not) last",
      [r["id"] for r in o] == ["c", "d", "b", "a", "e"] and [r["group"] for r in o] == ["featured", "sample", "community", "community", "offline"])
check("no pay or vote placement: the order reads only score, featured and live",
      net.order([{"id": "z", "name": "Z", "live": True, "score": 5, "paid": True, "votes": 10**6},
                 {"id": "y", "name": "Y", "live": True, "score": 6}])[0]["id"] == "y")
t = net.totals([{"live": True, "players": 3, "bots": 1}, {"live": False, "players": 9}], {"online": True, "players": 2, "bots": 5})
check("totals: live realms, plus the sample's own numbers when its record is missing", t == {"realms": 2, "players": 5, "bots": 6})
check("network line", net.network_line(t) == "2 realms · 5 players online · 6 bots"
      and net.network_line({"realms": 1, "players": 1, "bots": 0}) == "1 realm · 1 player online")
f = net.filters_from({"build": ["1.12.1"], "tag": ["pvp"], "region": ["eu"], "lang": ["de"], "now": ["1"], "x": ["y"]})
check("filters from the query", f == {"build": 5875, "tag": "pvp", "region": "eu", "lang": "de", "now": True})
check("junk filters ignored", net.filters_from({"build": ["9"], "tag": ["<x>"], "region": ["mars"], "lang": ["english"]}) == {})
# 4.3.4 / 5.4.8 not offered for now (the owner, 2026-10-30): not a filter, their realms are not listed or counted
check("capped at 3.3.5a", net.MAX_OFFERED_BUILD == 12340 and net.offered(12340, {}) and not net.offered(15595, {})
      and net.offered(18414, {"LEYLINE_ALL_CLIENTS": "1"}))
check("a 4.3.4 / 5.4.8 build is no filter", net.filters_from({"build": ["4.3.4"]}) == {} and net.filters_from({"build": ["5.4.8"]}) == {})
_o = net.order([{"id": "a", "name": "A", "live": True, "build": 8606}, {"id": "c", "name": "C", "live": True, "build": 15595},
                {"id": "m", "name": "M", "live": False, "build": 18414}])
check("realms on 4.3.4 / 5.4.8 are left out", [r["id"] for r in _o] == ["a"])
_b = net.page_body([{"id": "cccccccccccccccc", "name": "Cata Den", "live": True, "build": 15595, "players": 3}], True, {"build": ["4.3.4"]},
                   {}, "https://relay.openvanilla.app/join/", {})
check("realms page: no 4.3.4 realm, no 4.3.4 chip", "Cata Den" not in _b and "4.3.4" not in _b)
check("matches", net.matches({"build": 5875, "tags": ["pvp"], "region": "eu", "language": "de-AT", "live": True, "players": 1}, f)
      and not net.matches({"build": 5875, "tags": ["pvp"], "region": "eu", "language": "de", "live": True, "players": 0}, f))

# ---------------------------------------------------------------- /wrath/realms
st, h, page = req("GET", "/wrath/realms")
check("realms: 200, no script, CSP strict", st == 200 and "<script" not in page.split("</style>", 1)[-1]
      and "script-src 'none'" in h.get("content-security-policy", ""))
i_feat, i_sample = page.find("<h2>Picked One</h2>"), page.find("<h2>Leyline Sample Hangout</h2>")
i_busy, i_plain, i_old, i_sleepy = (page.find("<h2>Busy Den</h2>"), page.find("<h2>Plain Field</h2>"),
                                    page.find("<h2>Old relay record</h2>"), page.find("<h2>Sleepy Hollow</h2>"))
check("order on the page: featured, the sample (pinned), by score, offline last",
      0 <= i_feat < i_sample < i_busy < i_plain < i_old < i_sleepy, (i_feat, i_sample, i_busy, i_plain, i_old, i_sleepy))
check("the sample: no Temporary chip (read as a wipe), the start line, its own numbers, Play", ">Temporary</span>" not in page[i_sample:i_busy]
      and "Start at level 1 or boost to 80" in page[i_sample:i_busy]
      and "4 playing · 10 bots" in page[i_sample:i_busy]
      and 'href="/wrath?go=h:dalaran">Play in Dalaran</a>' in page[i_sample:i_busy])
check("the hangout's relay record is the sample, not listed twice", "<h2>Wrath Unleashed</h2>" not in page)
check("names are neutral on /wrath/realms (an older relay's brand words dropped)", "<h2>Den</h2>" in page
      and not re.search(r"(?i)\bwow\b|warcraft", page))
check("hidden by staff: not on the page", "Hidden Away" not in page and HIDDEN not in page)
check("network line: live community realms + the sample", "5 realms · 39 players online · 50 bots" in page,   # the hangout from its own status (4 players, 10 bots), not its record
      re.findall(r'net-line">([^<]*)', page))
check("featured and verified badges", ">Featured</span>" in page[i_feat:i_sample] and "Verified host" in page[i_feat:i_sample]
      and "Verified host" in page[i_busy:i_plain] and "Featured" not in page[i_busy:i_plain])
check("build, core, tags, region, language", ">1.12.1</span><span class=\"tag\">AzerothCore</span>" in page[i_feat:i_sample] and "1.12.1 · " not in page and ">Blizzlike<" in page[i_feat:i_sample]
      and ">Europe<" in page[i_feat:i_sample] and ">English<" in page[i_busy:i_plain])
check("estimated region marked, new badge, player limit", "Europe (estimated)" in page[i_plain:i_old]
      and ">New</span>" in page[i_plain:i_old] and "0 playing of 50" in page[i_plain:i_old])
check("uptime badge (7 d), and none for an old relay record", "98% up · 7 d" in page[i_busy:i_plain]
      and "60% up" in page[i_plain:i_old] and "% up" not in page[i_old:i_sleepy])
check("bots counted apart", "30 playing · 40 bots" in page[i_busy:i_plain])
check("Join and Report on community realms", f'href="https://relay.example/join/{BUSY}"' in page
      and f'href="/wrath/realms/report?realm={BUSY}"' in page)
check("filters: plain links", 'href="/wrath/realms?tag=pvp"' in page and 'href="/wrath/realms?build=1.12.1"' in page
      and 'href="/wrath/realms?region=eu"' in page and 'href="/wrath/realms?lang=de"' in page and 'href="/wrath/realms?now=1"' in page)
check("Host your own: three steps and the links", 'id="host-your-own"' in page and page.count("<li>", page.find('id="host-your-own"')) >= 3
      and 'href="/wrath/leyline">Get the launcher' in page and 'href="/wrath/host"' in page and "TODO(owner)" in page)
check("the order is explained: nothing can be bought", "nothing can be bought" in page)
st, _, pvp = req("GET", "/wrath/realms?tag=pvp")
check("filter tag=pvp: pvp realms, the sample stays", st == 200 and "Busy Den" in pvp and "Picked One" in pvp
      and "Plain Field" not in pvp and "Leyline Sample Hangout" in pvp and 'class="on">PvP' in pvp)
_, _, old = req("GET", "/wrath/realms?build=1.12.1")
check("filter build=1.12.1", "Picked One" in old and "Busy Den" not in old)
_, _, now = req("GET", "/wrath/realms?now=1")
check("filter has players now", "Busy Den" in now and "Plain Field" not in now and "Sleepy Hollow" not in now)
_, _, de = req("GET", "/wrath/realms?lang=de&region=eu")
check("filters combine (language and region, estimated counts)", "Plain Field" in de and "Picked One" not in de)
_, _, none = req("GET", "/wrath/realms?tag=hangout&lang=de")
check("no match: says so, links back", "No realms match these filters" in none)

# ---------------------------------------------------------------- /wrath/realms.json
st, h, raw = req("GET", "/wrath/realms.json")
doc = json.loads(raw)
ids = [r["community"]["realmId"] for r in doc["realms"]]
check("realms.json: 200, CORS, network kind", st == 200 and h.get("access-control-allow-origin") == "*" and doc["kind"] == "network")
check("realms.json: display order, hidden left out", ids == [FEAT, HANG, BUSY, PLAIN, OLD, "brandbrandbrandb", SLEEPY], ids)
check("realms.json: a neutral name, nameOk false for a name the filter changed",
      next(r for r in doc["realms"] if r["community"]["realmId"] == "brandbrandbrandb")["name"] == "Den"
      and next(r for r in doc["realms"] if r["community"]["realmId"] == "brandbrandbrandb")["community"]["nameOk"] is False
      and next(r for r in doc["realms"] if r["community"]["realmId"] == BUSY)["community"]["nameOk"] is True)
check("realms.json: network totals", doc["network"] == {"realms": 5, "players": 39, "bots": 50}, doc["network"])
c = {r["community"]["realmId"]: r for r in doc["realms"]}
check("realms.json: featured, verified, sample, group", c[FEAT]["community"]["featured"] and c[FEAT]["community"]["verified"]
      and c[HANG]["community"]["sample"] and c[HANG]["community"]["sampleName"] == "Leyline Sample Hangout"
      and c[HANG]["community"]["group"] == "sample" and not c[BUSY]["community"]["featured"])
check("realms.json: the launcher's fields", c[BUSY]["connect"]["url"] == f"https://relay.example/join/{BUSY}"
      and c[BUSY]["profile"]["port"] == 40002 and c[BUSY]["status"]["url"] == f"https://relay.example/r/{BUSY}/status.json"
      and c[FEAT]["profile"]["version"] == "1.12.1" and c[BUSY]["tags"] == ["pvp", "bots"] and c[PLAIN]["maxPlayers"] == 50
      and c[BUSY]["community"]["uptime"] == {"h24": 99, "d7": 98})
check("realms.json: an old relay record gets safe defaults", c[OLD]["profile"]["build"] == 12340 and c[OLD]["tags"] == []
      and c[OLD]["community"]["uptime"] == {"h24": None, "d7": None})
check("realms.json: the sample block for the launcher", doc["sample"] == {"name": "Leyline Sample Hangout", "temporary": True})
check("realms.json: never official, direct connect off", all(not r["official"] and not r["community"]["directConnect"]
                                                             for r in doc["realms"]))

# ---------------------------------------------------------------- reports
st, h, _ = req("GET", f"/wrath/realms/report?realm={BUSY}")
check("report: sign in first", st in (302, 303) and h.get("location", "").startswith("/login?next="))
st, _, form = req("GET", f"/wrath/realms/report?realm={BUSY}", cookie="alice")
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', form)
check("report form: reasons, a note, CSRF", st == 200 and "Report Busy Den" in form and 'value="cheat"' in form and tok)
st, _, body = req("POST", "/wrath/realms/report", cookie="alice", body={"realm": BUSY, "reason": "cheat", "csrf": "bad"})
check("report: a bad CSRF token is refused", st == 400 and "timed out" in body and net.reports("open") == [])
st, _, body = req("POST", "/wrath/realms/report", cookie="alice", body={"realm": BUSY, "reason": "cheat", "csrf": tok.group(1)},
                  headers={"Origin": "https://evil.example"})
check("report: another site's form is refused", st == 403)
st, _, body = req("POST", "/wrath/realms/report", cookie="alice",
                  body={"realm": BUSY, "reason": "cheat", "note": "sells gold <b>here</b>\x07", "csrf": tok.group(1)})
reps = net.reports("open")
check("report: queued for staff", st == 200 and "Report sent" in body and len(reps) == 1 and reps[0]["realm"] == BUSY
      and reps[0]["reason"] == "cheat" and reps[0]["note"] == "sells gold <b>here</b>" and reps[0]["by"] != "alice"
      and reps[0]["by_name"] == "Alice")
st, _, body = req("POST", "/wrath/realms/report", cookie="alice", body={"realm": BUSY, "reason": "name", "csrf": tok.group(1)})
check("report: one open report per account and realm", st == 400 and "already reported" in body and len(net.reports("open")) == 1)
tok_b = re.search(r'name="csrf" value="([0-9a-f]+)"', req("GET", f"/wrath/realms/report?realm={HIDDEN}", cookie="bob")[2])
st, _, body = req("POST", "/wrath/realms/report", cookie="bob", body={"realm": HIDDEN, "reason": "name",
                                                                     "csrf": net.csrf("bob")})
check("report: only realms on the list", st == 404 and len(net.reports("open")) == 1)
st, _, body = req("POST", "/wrath/realms/report", cookie="bob", body={"realm": BUSY, "reason": "pay me", "csrf": net.csrf("bob")})
check("report: a reason from the list only", st == 400 and "Pick a reason" in body)
st, _, body = req("POST", "/wrath/realms/report", cookie="bob", body={"realm": BUSY, "reason": "other", "note": "x" * 400,
                                                                     "csrf": net.csrf("bob")})
check("report: the note is capped", st == 400 and "under 300" in body)
got = [net.add_report(rid, "x", "other", "", "spam0", "S", now=1e9 + 10)[0] for rid in (PLAIN, FEAT, HANG, OLD, SLEEPY, BUSY)]
check("report: rate limited per account (5 an hour)", got == [True] * 5 + [False]
      and net.add_report(BUSY, "x", "name", "", "spam0", "S", now=1e9 + 20)[1].startswith("You've sent")
      and net.add_report(BUSY, "x", "name", "", "spam0", "S", now=1e9 + 4000)[0])

# ---------------------------------------------------------------- the admin console acts on them
user = {"session": "s1", "account": "owner1", "role": "owner", "name": "Owner"}
adm = wp.admin.realms_page(user)
check("admin realms: open reports under the realm, Feature and Verify", "open report" in adm and "Resolve reports" in adm
      and "realm.feature" in adm and "realm.unverify" in adm and "sells gold &lt;b&gt;here&lt;/b&gt;" in adm)
check("admin reports page: the realm reports section", "Realm reports" in wp.admin.reports_page(user, {}))
n_busy = len(net.reports("open", BUSY))
before, after = wp.admin.ACTIONS["realm.reports"][0](user, BUSY, {"how": "dismissed"})
check("admin: resolve a realm's reports", n_busy >= 1 and before["open_reports"] == n_busy and after["open_reports"] == 0
      and not net.reports("open", BUSY) and net.reports("dismissed", BUSY)[0]["closed_by"] == "Owner")
wp.admin.ACTIONS["realm.feature"][0](user, PLAIN, {})
wp._listing["at"] = -1e9
time.sleep(0.2)
req("GET", "/wrath/realms.json")
time.sleep(0.5)
doc = json.loads(req("GET", "/wrath/realms.json")[2])
ids = [r["community"]["realmId"] for r in doc["realms"]]
check("admin: featuring a realm puts it above the sample", ids[:3] == [FEAT, PLAIN, HANG] or ids[:3] == [PLAIN, FEAT, HANG], ids)
ov = json.loads(wp.admin.feed("/wrath/leyline/realm-overrides.json"))
check("realm-overrides.json: featured and verified for the launcher", ov["featured"] == sorted([FEAT, PLAIN])
      and ov["verified"] == sorted([BUSY, FEAT]) and HIDDEN in ov["hidden"])

# ---------------------------------------------------------------- the hub
st, _, hub = req("GET", "/wrath/leyline-preview/realms")
check("hub realms page: the same list, filters on the hub's own path", st == 200 and "Wrath Unleashed" in hub
      and "Busy Den" in hub and 'href="/wrath/leyline-preview/realms?tag=pvp"' in hub and 'id="host-your-own"' in hub)
st, _, front = req("GET", "/wrath/leyline-preview")
check("hub front page: Platform Status has the network line, linked to the hub's realm list", "Realm network" in front
      and re.search(r"\d+ realms · \d+ players online", front) and 'href="/wrath/leyline-preview/realms"' in front
      and "Host a Beacon" in front)

# the realm list under the hero (owner 2026-10-30): every server, ours first, one click to play
sec = re.search(r'<section class="hb-sec hb-realms" id="realms".*?</section>', front, re.S)
sec = sec.group(0) if sec else ""
rows = re.findall(r'<li class="hb-rl[^"]*"( data-home="1"| data-rid="([a-z2-7]{16})") data-client="(browser|own)" data-live="(\d)"'
                  r' data-players="(\d+)">(?:<span class="hb-rl-ic.*?</span>)?<div class="hb-rl-n"><b>([^<]+)</b>', sec)
names = [r[5] for r in rows]
check("hub realm list: right under the hero, before the products and Platform Status", sec
      and front.index('class="hb-hero"') < front.index('id="realms"') < front.index('id="features"') < front.index('id="status"'))
# launch (owner 2026-10-30): the Hangout and the Wrath realm are the same realm, one name everywhere (sampler or not)
check("hub realm list: the home realm first, as Official, played with a plain /wrath", rows and rows[0][0] == ' data-home="1"'
      and names[0] == "Wrath Unleashed" and 'href="/wrath" aria-label="Play Wrath Unleashed in your browser"' in sec
      and '<span class="hb-bdg o">Official</span>' in sec and "Leyline Sample Hangout" not in sec and sec.count("<b>Wrath Unleashed</b>") == 1, names)
check("hub realm list: featured next, offline last, hidden realms never", set(names[1:3]) == {"Picked One", "Plain Field"}
      and names[-1] == "Sleepy Hollow" and rows[-1][3] == "0" and "Hidden Away" not in sec and "Busy Den" in names, names)
check("hub realm list: Play in browser is the hop link, only for live realms the browser plays", f'href="/wrath?go=r:{BUSY}"' in sec
      and f'go=r:{FEAT}' not in sec and f'go=r:{SLEEPY}' not in sec and "Bring your own game client" in sec
      and "Needs a" not in sec and "1.12.1" not in re.sub(r'<span class="hb-ver"[^>]*>[^<]*</span>', "", sec))   # the version chip only
check("hub realm list: the desktop address for each realm with a port, ours by the site's host", "relay.example:40002" in sec
      and f'title="The realm address for a desktop client">{wp.PUBLIC_HOST}</code>' in sec)
check("hub realm list: badges, how it plays (never a build), core, region, uptime", all(x in sec for x in ('class="hb-bdg f">Featured', 'class="hb-bdg v"',
      "Bring your own game client · AzerothCore", "Plays in your browser · AzerothCore", "Original rules", "North America east", "98% up", "<b class=\"hb-n\">30</b> playing", "40 bots")), sec[:400])
check("hub realm list: a GET form filter that works without script", f'action="/wrath/leyline-preview/realms" data-rf="hb-rlist"' in sec
      and '<select name="client"><option value="">Any</option><option value="browser">Plays in browser</option>'
      '<option value="own">Own client</option></select>' in sec and 'name="now" value="1"' in sec)
check("hub realm list: Open in launcher on every row (the home realm as official)", 'href="leyline://realm/official"' in sec
      and sec.count(">Open in launcher</a>") == sec.count('class="hb-addr"') or sec.count(">Open in launcher</a>") >= 2, sec[:300])
st, _, only = req("GET", "/wrath/leyline-preview/realms?client=own&now=1")
check("hub realms page: the form's filters on the server", st == 200 and "<b>Picked One</b>" in only and "<b>Busy Den</b>" not in only
      and "<b>Wrath Unleashed</b>" not in only)
st, _, none = req("GET", "/wrath/leyline-preview/realms?client=own&tag=bots")
check("hub realms page: no match says so", "No realms match these filters" in none)
st, _, beacon = req("GET", "/wrath/leyline-preview/beacon")
check("hub Host a Beacon: the launcher's Host page and the website", 'href="/wrath/leyline">Get the launcher' in beacon
      and 'href="/wrath/host"' in beacon)

# ---------------------------------------------------------------- Warden (Browser players off) is carried for the hub
check("warden carried from the relay record (Play in browser only without it)",
      net.extra({"profile": {"warden": True}})["warden"] is True and net.extra({"profile": {"warden": "yes"}})["warden"] is None
      and net.extra({})["warden"] is None)

# ---------------------------------------------------------------- totals: players and bots apart, our own realm from its own status
_t = net.totals([{"id": "h" * 16, "live": True, "hangout": True, "players": 1, "bots": 0},
                 {"id": "c" * 16, "live": True, "players": 3, "bots": 7}], {"online": True, "players": 0, "bots": 1})
check("totals: bots never counted as players (our realm from its own status)", _t == {"realms": 2, "players": 3, "bots": 8}, _t)
_t = net.totals([{"id": "h" * 16, "live": True, "hangout": True, "players": 2, "bots": 5}], {})
check("totals: without its own status, the record's numbers", _t == {"realms": 1, "players": 2, "bots": 5}, _t)
_t = net.totals([], {"online": True, "players": 4, "bots": 2})
check("totals: our realm with no record yet", _t == {"realms": 1, "players": 4, "bots": 2}, _t)

# ---------------------------------------------------------------- Vanilla Remastered: the second official realm (vr-realm.id)
VRID = "vrvrvrvrvrvrvrvr"
_rs = [{"id": "busybusybusybusy", "name": "Busy", "live": True, "players": 30, "score": 90.0, "build": 12340},
       {"id": VRID, "name": "Vanilla Remastered", "live": False, "players": 0, "score": 1.0, "build": 5875, "core": "cmangos"},
       {"id": "hanghanghanghang", "name": "Wrath Unleashed", "live": True, "hangout": True, "players": 2, "build": 12340}]
net.VR_REALM = ""
net.VR_FILE = os.path.join(tempfile.mkdtemp(), "vr-realm.id")
net._vr["at"] = -1e9
check("vr: without the id file it lists like any realm (offline last)", [r["id"] for r in net.order(_rs)][-1] == VRID
      and not any(r.get("official") for r in net.order(_rs)))
with open(net.VR_FILE, "w") as f:
    f.write(VRID + "\n")
net._vr["at"] = -1e9
_o = net.order(_rs)
check("vr: pinned right after the Hangout, official, even offline", [r["id"] for r in _o][:2] == ["hanghanghanghang", VRID]
      and _o[1]["official"] and _o[1]["group"] == "official")
_rec = net.record_of(_o[1])
check("vr: official, pinned, optional in the launcher's record", _rec["community"]["official"] and _rec["community"]["pinned"]
      and _rec["community"]["optional"] and "Hosted by Leyline for now".lower() in _rec["community"]["note"].lower())
_c = net.card(_o[1], "https://relay.example", {})
check("vr: card says official and hosted by Leyline for now; the version only in its chip",
      ">Official<" in _c and "hosted by Leyline for now" in _c and '<span class="tag">CMaNGOS</span>' in _c
      and '<span class="tag ver"' in _c and "1.12.1 · " not in _c, _c[:400])
net._vr.update(at=1e18, id=None)

# ---------------------------------------------------------------- shipping: the signin step
STREAM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fl = open(os.path.join(STREAM, "fastloop.sh"), encoding="utf-8").read()
bat = open(os.path.join(STREAM, "Update sign-in and warm-up.bat"), encoding="utf-8").read()
import subprocess
check("signin step ships network.py, backs it up, puts it back", 'install -m 644 network.py "$WU/portal/network.py"' in fl
      and 'cp -p "$BK/network.py" "$WU/portal/network.py"' in fl and 'set "LINKS=%LINKS% network.py"' in bat
      and " network.py " in re.search(r"\$\(ls ([^)]*)\)", bat).group(1)
      and subprocess.run(["bash", "-n", os.path.join(STREAM, "fastloop.sh")]).returncode == 0)

# ---------------------------------------------------------------- nothing player-visible names the game or its maker
bad = [p for p in (page, hub, front, form) if re.search(r"(?i)world of warcraft|warcraft|lich king|blizzard|\bwow\b", p)]
check("no game-brand names on the network pages", not bad)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
