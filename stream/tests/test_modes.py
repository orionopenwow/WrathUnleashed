"""The Modes hub (GET /wrath/modes, stream/modes.py + stream/modes_data.py) and the go intent ("ovgo set" over
SOAP for realm/custom/lua_scripts/ov_go.lua): routes, segments, escaping, every Go link resolves, screenshots and
their fallback, no game-brand names, the SOAP call against a fake SOAP, and the data kept in step with
stream/slices/mini.json, ov_go.lua and the server-pass .bat.

    python3 -I stream/tests/test_modes.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, PAGE_PORT = 17893, 18193, 18194
HERE = os.path.dirname(os.path.abspath(sys.argv[1]))
REPO = os.path.dirname(HERE)
ART = tempfile.mkdtemp()
for n in ("wu-theme.css", "leyline-bg.webp"):
    src = os.path.join(HERE, "www-files", "art", n)
    if os.path.isfile(src):
        shutil.copy(src, ART)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_STREAM="0", STREAM_HOST="wrath.example",
                  PUBLIC_HOST="play.example", WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_ART_DIR=ART)
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.realm_status = lambda: {"online": True, "players": 3, "bots": 10}

soap = {"commands": [], "ovgo": "ovgo ok: WR000123 -> x (30 min)"}


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        cmd = wp._tag_text(self.rfile.read(int(self.headers["Content-Length"])), "command")
        soap["commands"].append(cmd)
        if cmd.startswith("account create"):
            ok, text = False, "Account with this name already exist!"
        elif cmd.startswith("ovgo"):
            ok, text = soap["ovgo"] is not None, soap["ovgo"] or "There is no such command."
        else:
            ok, text = True, "done"
        inner = (f"<ns1:executeCommandResponse><result>{escape(text)}</result></ns1:executeCommandResponse>" if ok else
                 f"<SOAP-ENV:Fault><faultcode>SOAP-ENV:Client</faultcode><faultstring>{escape(text)}</faultstring></SOAP-ENV:Fault>")
        body = ('<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
                f'xmlns:ns1="urn:AC"><SOAP-ENV:Body>{inner}</SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()
        self.send_response(200 if ok else 500)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class Realm(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if "wr_session=good" not in self.headers.get("Cookie", ""):
            self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = {"/api/me": {"display_name": "Tester"}, "/api/play": {"user": "WR000123", "pass": "Pa55word1234abcd"}}[self.path]
        body = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


for port, h in ((SOAP_PORT, Soap), (REALM_PORT, Realm), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, cookie="", ip="10.7.0.1", method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    hd = {"X-Forwarded-For": ip}
    if cookie:
        hd["Cookie"] = cookie
    c.request(method, path, headers=hd)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)


M, L, D = wp.modes, wp.links, getattr(wp.modes, "data", None)
check("modes.py and modes_data.py loaded beside the portal", M is not None and D is not None and L is not None)
if M is None or L is None:
    print(f"\n{passed}/{passed + failed} passed"); sys.exit(1)
check("data tables pass their own check", D.check() == [], D.check())

BANNED = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")


def visible(p):
    p = re.sub(r"<style.*?</style>", " ", p, flags=re.S)
    attrs = " ".join(re.findall(r'(?:alt|title|content|aria-label)="([^"]*)"', p))
    return re.sub(r"<[^>]+>", " ", p) + " " + attrs


# --- the route ------------------------------------------------------------------------------------------------
st, h, b = get("/wrath/modes")
page = b.decode()
check("GET /wrath/modes: 200 html", st == 200 and h.get("content-type", "").startswith("text/html"), st)
check("trailing slash too", get("/wrath/modes/")[0] == 200)
check("HEAD: no body", get("/wrath/modes", method="HEAD")[2] == b"")
check("no script allowed (CSP script-src 'none')", "script-src 'none'" in h.get("content-security-policy", ""))
check("no script on the page", "<script" not in page)
check("Leyline look (its css, nav and title font)", "body.ly" in page and 'class="ly-nav"' in page and "Leyline Display" in page
      and "/wrath/art/leyline-bg.webp" in page)
check("link card", 'property="og:url" content="https://play.example/wrath/modes"' in page and "twitter:card" in page)
check("title", "<title>Modes · WrathUnleashed</title>" in page)
for seg, hid in (("Duels", "duels"), ("Boss fights", "bosses"), ("Dungeons", "dungeons"), ("Hangouts", "hangouts")):
    check(f"segment {seg}", f'id="{hid}"' in page and f">{seg}</h2>" in page and f'href="#{hid}"' in page)
check("duels: how it works today (/duel, .wu)", "<code>/duel</code>" in page and "<code>.wu</code>" in page)
check("duels: one Go duel link", page.count(">Go duel<") == 1 and 'href="/wrath/h/duels"' in page)
for r in D.RAIDS:
    check(f"raid {r['name']}", f'href="/wrath/b/{r["id"]}"' in page and wp.html.escape(r["name"]) in page)
for name in ("Naxxramas", "Ulduar", "Icecrown Citadel", "Molten Core", "Karazhan", "Sunwell Plateau", "The Ruby Sanctum"):
    check(f"has {name}", wp.html.escape(name) in page)
check("raids by region", page.index(">Azeroth <") < page.index(">Outland <") < page.index(">Northrend <"))
wings = [w for r in D.RAIDS for w in r.get("wings", [])]
check("every wing has a Go", len(wings) >= 15 and all(f'href="/wrath/b/{w["id"]}"' in page for w in wings))
check("ICC wings, ending at the Frozen Throne", all(n in page for n in ("The Lower Spire", "The Plagueworks", "The Crimson Hall",
      "The Frostwing Halls", "The Frozen Throne")) and "the Frozen Throne" in page)
check("every 5-player dungeon", len(D.DUNGEONS) == 51 and all(f'href="/wrath/q/{d["id"]}"' in page for d in D.DUNGEONS))
check("the random queues", all(f'href="/wrath/q/{q["id"]}"' in page for q in D.RANDOM_QUEUES) and page.count(">Queue<") == 5)
check("hangouts: Dalaran and the Goldshire Inn", 'href="/wrath/h/dalaran"' in page and 'href="/wrath/h/goldshire-inn"' in page
      and "The Goldshire Inn" in page and 'href="/wrath/demo"' in page)
check("level and size tags", "Levels 10-23" in page and "Level 80" in page and "10 / 25 players" in page and "5 players" in page)
check("bots tag on dungeons and queues only", page.count(">Bots can fill<") == len(D.DUNGEONS) + len(D.RANDOM_QUEUES))
vis = visible(page)
bad = BANNED.findall(vis)
check("no game-brand names in the page", not bad, bad)
check("no game-brand names in the data at all", not BANNED.findall(json.dumps(D.places())))
check("leyline nav links the hub", 'href="/wrath/modes"' in wp.leyline_page().decode())

# --- every Go link resolves ----------------------------------------------------------------------------------------
hrefs = sorted(set(re.findall(r'href="(/wrath/[hqb]/[^"]+)"', page)))
check("about a hundred Go links", len(hrefs) == len(M.PLACES), (len(hrefs), len(M.PLACES)))
unresolved = []
for href in hrefs:
    got = L.parse(href)
    if not got or L.go_value(*got) not in M.PLACES:
        unresolved.append(href)
check("every Go link parses and is a known place", not unresolved, unresolved[:5])
for href, name in (("/wrath/q/deadmines", "The Deadmines"), ("/wrath/b/icc-frozen-throne", "Icecrown Citadel: The Frozen Throne"),
                   ("/wrath/q/262", "Random Heroic: Northrend"), ("/wrath/h/duels", "Duels in Dalaran")):
    st, _, sb = get(href)
    s = sb.decode()
    kind, ident = L.parse(href)
    check(f"share page {href}: names it, deep links on", st == 200 and wp.html.escape(name) in s
          and f"/wrath?go={kind}:{ident}" in s and not BANNED.findall(visible(s)), st)
check("browser goLink knows b:", "b: /^[a-z0-9]" in open(os.path.join(HERE, "www-files", "wrath-page.js")).read())
check("unknown b id still a card", get("/wrath/b/not-a-raid")[0] == 200)

# --- escaping --------------------------------------------------------------------------------------------------
saved = D.DUNGEONS[0]["name"], D.RAIDS[0]["bosses"][0], D.HANGOUTS[0]["line"]
D.DUNGEONS[0]["name"] = 'Rage<script>alert(1)</script>"x'
D.RAIDS[0]["bosses"][0] = "Luci&fron <b>"
D.HANGOUTS[0]["line"] = "Meet \"here\" <img src=x>"
p2 = M.page(wp.leyline_css(), wp.art_url, wp.art_present, wp.card_meta, "Real<m>").decode()
D.DUNGEONS[0]["name"], D.RAIDS[0]["bosses"][0], D.HANGOUTS[0]["line"] = saved
check("names escaped", "Rage&lt;script&gt;alert(1)&lt;/script&gt;&quot;x" in p2 and "<script>" not in p2)
check("bosses escaped", "Luci&amp;fron &lt;b&gt;" in p2)
check("lines escaped", "Meet &quot;here&quot; &lt;img src=x&gt;" in p2 and "<img src=x>" not in p2)
check("realm name escaped", "Real&lt;m&gt;" in p2 and "Real<m>" not in p2)

# --- screenshots ------------------------------------------------------------------------------------------------
for n in ("leyline-shot-dalaran.webp", "leyline-shot-start.webp", "leyline-shot-city.webp", "leyline-shot-durotar.webp"):
    check(f"art allow-list has {n}", wp.ART_TYPES.get(n) == "image/webp" and n in M.SHOT_NAMES)
check("missing shots: a painted panel per segment, no broken image", page.count('class="md-shot"') == 4 and "<img" not in page)
check("missing shot: 404 from the art route", get("/wrath/art/leyline-shot-city.webp")[0] == 404)
with open(os.path.join(ART, "leyline-shot-city.webp"), "wb") as f:
    f.write(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
p3 = get("/wrath/modes", ip="10.7.0.2")[2].decode()
check("present shot: shown", '<img src="/wrath/art/leyline-shot-city.webp"' in p3 and p3.count("<img") == 1)
st, h3, _ = get("/wrath/art/leyline-shot-city.webp")
check("present shot: served as webp", st == 200 and h3.get("content-type") == "image/webp")
check("art route still refuses other names", get("/wrath/art/leyline-shot-x.webp")[0] == 404)

# --- rate limit -------------------------------------------------------------------------------------------------
codes = [get("/wrath/modes", ip="10.7.9.9", method="HEAD")[0] for _ in range(601)]
check("rate limit like /wrath/leyline (600/min)", codes.count(200) == 600 and codes[-1] == 429, (codes.count(200), codes[-1]))

# --- the go intent: unit ------------------------------------------------------------------------------------------
check("go_command", M.go_command("wr000123", "q:deadmines") == "ovgo set WR000123 q:deadmines")
for acct, go in (("WR000123", "q:nope"), ("WR000123", "m:better-bags"), ("WR000123", "u:Arthas"), ("WR 1", "q:deadmines"),
                 ("WR000123;x", "q:deadmines"), ("A" * 17, "q:deadmines"), ("WR000123", "q:deadmines x"), ("WR000123", "q:<x>"),
                 ("WR000123", ""), (None, "q:deadmines"), ("WR000123", None)):
    check(f"go_command refuses {acct!r} {go!r}", M.go_command(acct, go) is None)
calls = []
check("go_intent: confirmed", M.go_intent(lambda c: calls.append(c) or "ovgo ok: X", "UNIT1", "h:dalaran") and calls == ["ovgo set UNIT1 h:dalaran"])
check("go_intent: the same again within 2 min is not resent", M.go_intent(lambda c: calls.append(c) or "ovgo ok", "UNIT1", "h:dalaran") and len(calls) == 1)


def boom(c):
    raise wp.SoapError("down", "x")


check("go_intent: SOAP down is False, never raises", M.go_intent(boom, "UNIT2", "h:dalaran") is False)
check("go_intent: no confirmation is False", M.go_intent(lambda c: "There is no such command.", "UNIT3", "h:dalaran") is False)
check("go_intent: bad target never reaches SOAP", M.go_intent(lambda c: calls.append(c) or "ovgo ok", "UNIT4", "q:x;y") is False and len(calls) == 1)

# --- the go intent: through the portal, with a fake SOAP -------------------------------------------------------------
def ovgo():
    return [c for c in soap["commands"] if c.startswith("ovgo")]


get("/wrath?go=q:deadmines")
check("signed out: no go sent", ovgo() == [])
st, _, b = get("/wrath/account?go=q:deadmines", cookie="wr_session=good")
check("signed in: the page still works", st == 200 and b"WR000123" in b, st)
check("signed in: ovgo set for the game account", ovgo() == ["ovgo set WR000123 q:deadmines"], ovgo())
check("after the account is ensured", soap["commands"].index("ovgo set WR000123 q:deadmines") >
      soap["commands"].index("account set password WR000123 Pa55word1234abcd Pa55word1234abcd"))
get("/wrath?go=b:icc-frozen-throne", cookie="wr_session=good")
check("/wrath with a raid wing", ovgo()[-1] == "ovgo set WR000123 b:icc-frozen-throne", ovgo())
n = len(ovgo())
for bad in ("q:nope", "q:%3Cx%3E", "m:better-bags", "u:Arthasx", "r:wrathunleashed", "q:deadmines%20x", "zz", "h:dalaran:x"):
    get("/wrath/account?go=" + bad, cookie="wr_session=good")
check("only allow-listed places are sent", len(ovgo()) == n, ovgo()[n:])
soap["ovgo"] = None   # ov_go.lua not loaded: the command fails
st, _, b = get("/wrath/account?go=h:goldshire-inn", cookie="wr_session=good")
check("realm without ov_go.lua: the page still works", st == 200 and b"WR000123" in b and ovgo()[-1] == "ovgo set WR000123 h:goldshire-inn")
soap["ovgo"] = "ovgo ok"
check("no go: nothing sent", (lambda k: (get("/wrath/account", cookie="wr_session=good"), len(ovgo()) == k)[1])(len(ovgo())))
wp.gate_limit.q.clear()
k = len(ovgo())
for i in range(25):
    get(f"/wrath/account?go=q:{D.DUNGEONS[i]['id']}", cookie="wr_session=good", ip=f"10.8.0.{i}")
check("at most 20 go intents a minute per account", len(ovgo()) - k == 20, len(ovgo()) - k)

# --- kept in step -----------------------------------------------------------------------------------------------
mini = json.load(open(os.path.join(HERE, "slices", "mini.json")))
mini_pos = {p["map"]: (p["x"], p["y"], p["z"], p["o"]) for t in mini["tiers"] for p in (t.get("play") or [])}
diff = [m for m, pos in D.ENTRANCES.items() if mini_pos.get(m) != pos]
check("ENTRANCES match mini.json's .play teleports", not diff, diff)
inst = [m for m in mini_pos if m not in (571, 0, 1, 609)]
check("every streamed instance has an entrance here", all(m in D.ENTRANCES for m in inst), [m for m in inst if m not in D.ENTRANCES])
for t in mini["tiers"]:
    if t.get("kind") == "dungeon" and t.get("levels"):
        m = t["maps"][0]["id"]
        d = next((d for d in D.DUNGEONS if d["map"] == m), None)
        if not d or list(d["levels"]) != t["levels"]:
            check(f"levels of map {m} match mini.json", False, (d and d["levels"], t["levels"]))
slices = open(os.path.join(HERE, "lua", "ov_slices.lua")).read()
pools = {name: {int(x) for x in re.search(name + r" = \{([^}]*)\}", slices).group(1).split(",")}
         for name in ("CLASSIC5", "BC5", "WRATH5")}
by_exp = {e: {d["map"] for d in D.DUNGEONS if d["exp"] == e} for e in ("azeroth", "outland", "northrend")}
check("dungeon maps = ov_slices.lua's pools", by_exp["azeroth"] == pools["CLASSIC5"] and by_exp["outland"] == pools["BC5"]
      and by_exp["northrend"] == pools["WRATH5"], {k: by_exp[k] ^ pools[v] for k, v in (("azeroth", "CLASSIC5"), ("outland", "BC5"), ("northrend", "WRATH5"))})
check("random queues = ov_slices.lua's RANDOM_POOL", {q["id"] for q in D.RANDOM_QUEUES} ==
      set(re.findall(r"\[(\d+)\] = (?:CLASSIC5|BC5|WRATH5)", slices)))
OVGO = os.path.join(REPO, "realm", "custom", "lua_scripts", "ov_go.lua")
lua = open(OVGO, encoding="utf-8").read()
check("ov_go.lua carries the current table (python3 stream/modes_data.py --write ...)", D.splice(lua) == lua)
check("ov_go.lua: one place per Go link", lua.count('what = "') == len(M.PLACES))
bat = open(os.path.join(REPO, "realm", "Server pass - finder 10 and bug reports.bat"), "rb").read()
check("server pass .bat copies ov_go.lua", b'copy /y "custom\\lua_scripts\\ov_go.lua" "%T%\\" >nul' in bat)
check("server pass .bat line endings unchanged (one style)", (b"\r\n" in bat) == (bat.count(b"\n") == bat.count(b"\r\n")))

shutil.rmtree(ART, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
