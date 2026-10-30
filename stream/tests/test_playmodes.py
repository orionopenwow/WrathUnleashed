"""Leyline game modes (stream/playmodes.py + stream/playmodes.json): the catalog and its checker, GET /wrath/modes.json,
the Games section of /wrath/modes, and ?go=mode:<id> through sign-in ("ovplay go" over SOAP for
realm/custom/lua_scripts/ov_playmode.lua) against a fake SOAP. Also kept in step: the realm's table, the server-pass
.bat, the deploy scripts and the launcher's built-in copy.

    python3 -I stream/tests/test_playmodes.py stream/wrath_portal.py
"""
import copy, http.client, importlib.util, json, os, re, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, PAGE_PORT = 17993, 18293, 18294
HERE = os.path.dirname(os.path.abspath(sys.argv[1]))
REPO = os.path.dirname(HERE)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_STREAM="0", STREAM_HOST="wrath.example",
                  PUBLIC_HOST="play.example", WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_ART_DIR=tempfile.mkdtemp())
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.realm_status = lambda: {"online": True, "players": 3, "bots": 10}

soap = {"commands": [], "ovplay": "ovplay ok: WR000123 -> minigolf (30 min)"}


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        cmd = wp._tag_text(self.rfile.read(int(self.headers["Content-Length"])), "command")
        soap["commands"].append(cmd)
        if cmd.startswith("account create"):
            ok, text = False, "Account with this name already exist!"
        elif cmd.startswith("ovplay"):
            ok, text = soap["ovplay"] is not None, soap["ovplay"] or "There is no such command."
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


def get(path, cookie="", ip="10.9.0.1", method="GET"):
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


PM = wp.playmodes
check("playmodes.py loaded beside the portal", PM is not None)
if PM is None:
    print(f"\n{passed}/{passed + failed} passed"); sys.exit(1)
check("the catalog passes its check", PM.ERRORS == [] and PM.CATALOG is not None, PM.ERRORS)
ids = [m["id"] for m in PM.entries()]
check("the seed modes", ids == ["minigolf", "bumper-balls", "coin-dash", "community", "brawl", "azeroth-survivors", "hordes-of-azeroth"], ids)
check("live realm modes", PM.realm_ids() == ["minigolf", "bumper-balls", "coin-dash", "community"], PM.realm_ids())
surv, hordes = PM.by_id("azeroth-survivors"), PM.by_id("hordes-of-azeroth")
check("Azeroth Survivors: offline, coming, credited (MIT or Apache-2.0)", surv["kind"] == "offline" and surv["status"] == "coming"
      and surv["credit"]["by"] == "Aethus" and "Apache-2.0" in surv["credit"]["license"] and "MIT" in surv["credit"]["license"]
      and surv["credit"]["source"] == "https://github.com/OutThisLife/azeroth-survivors-re" and "survivors=1" in surv["start"]["path"])
check("Hordes of Azeroth: a realm type, coming, both repos and licenses", hordes["kind"] == "realm-type" and hordes["status"] == "coming"
      and hordes["credit"]["by"] == "jonhaldors" and "GPL-3.0" in hordes["credit"]["license"] and "GPL-2.0" in hordes["credit"]["license"]
      and hordes["credit"]["source"] == "https://github.com/jonhaldors/hordes-of-azeroth"
      and hordes["credit"]["more"] == ["https://github.com/jonhaldors/hordes-of-azeroth-server"])
check("every third-party entry is credited", all(m.get("credit") for m in PM.entries() if m["id"] in ("azeroth-survivors", "hordes-of-azeroth")))

# --- the checker refuses ----------------------------------------------------------------------------------------
base = json.load(open(os.path.join(HERE, "playmodes.json")))


def bad(fn):
    d = copy.deepcopy(base)
    fn(d)
    return PM.check(d)


for name, fn in (
        ("not the catalog", lambda d: d.clear()),
        ("schema 2", lambda d: d.update(schema=2)),
        ("bad id", lambda d: d["modes"][0].update(id="Mini Golf")),
        ("duplicate id", lambda d: d["modes"][1].update(id="minigolf", start={"go": "mode:minigolf"})),
        ("unknown field", lambda d: d["modes"][0].update(price=5)),
        ("markup in a title", lambda d: d["modes"][0].update(title="<b>Golf</b>")),
        ("a brand name", lambda d: d["modes"][0].update(line="The best minigolf in all of Warcraft, honest.")),
        ("a short line", lambda d: d["modes"][0].update(line="Golf.")),
        ("unknown kind", lambda d: d["modes"][0].update(kind="arcade")),
        ("unknown status", lambda d: d["modes"][0].update(status="beta")),
        ("players max below min", lambda d: d["modes"][0].update(players={"min": 4, "max": 2})),
        ("players not numbers", lambda d: d["modes"][0].update(players={"min": True, "max": 2})),
        ("realm mode with another go", lambda d: d["modes"][0].update(start={"go": "mode:coin-dash"})),
        ("realm mode with a url", lambda d: d["modes"][0].update(start={"path": "/wrath"})),
        ("two ways to start", lambda d: d["modes"][0].update(start={"go": "mode:minigolf", "path": "/wrath"})),
        ("offline path off the site", lambda d: d["modes"][5].update(start={"path": "https://evil.example/x"})),
        ("offline path with a quote", lambda d: d["modes"][5].update(start={"path": '/wrath/play?x="1'})),
        ("realm type bad preset", lambda d: d["modes"][4].update(start={"host": "../x"})),
        ("credit without a license", lambda d: d["modes"][5]["credit"].pop("license")),
        ("credit http source", lambda d: d["modes"][5]["credit"].update(source="http://github.com/x")),
        ("credit javascript source", lambda d: d["modes"][5]["credit"].update(source="javascript:alert(1)")),
        ("credit more not https", lambda d: d["modes"][6]["credit"].update(more=["ftp://x.example/y"])),
        ("credit more not a list", lambda d: d["modes"][6]["credit"].update(more="https://github.com/x")),
):
    check(f"checker refuses: {name}", bad(fn) != [])
check("checker on a broken file: no catalog, a reason", PM.load(os.path.join(tempfile.mkdtemp(), "none.json"))[0] is None)

# --- /wrath/modes.json --------------------------------------------------------------------------------------------
st, h, b = get("/wrath/modes.json")
doc = json.loads(b)
check("GET /wrath/modes.json: 200 json", st == 200 and h.get("content-type", "").startswith("application/json"), st)
check("modes.json is the catalog", doc == {"schema": 1, "modes": base["modes"]})
check("modes.json readable from anywhere, cached", h.get("access-control-allow-origin") == "*" and "max-age" in h.get("cache-control", ""))
check("HEAD: no body", get("/wrath/modes.json", method="HEAD")[2] == b"")
check("trailing slash too", get("/wrath/modes.json/")[0] == 200)

# --- the Games section ----------------------------------------------------------------------------------------------
st, _, b = get("/wrath/modes")
page = b.decode()
check("/wrath/modes still 200", st == 200)
check("Games comes first, with a jump link", 'id="games"' in page and '>Games</h2>' in page and 'href="#games"' in page
      and page.index('id="games"') < page.index('id="duels"'))
for m in PM.entries():
    check(f"card {m['id']}", f'id="mode-{m["id"]}"' in page and wp.html.escape(m["title"]) in page)
for mid in PM.realm_ids():
    check(f"Play {mid}: /wrath?go=mode:{mid}", f'href="/wrath?go=mode:{mid}">Play<' in page)
check("brawl: Host it", 'id="mode-brawl"' in page and re.search(r'id="mode-brawl".*?href="/wrath/host">Host it<', page, re.S))
for mid in ("azeroth-survivors", "hordes-of-azeroth"):
    card = re.search(rf'id="mode-{mid}".*?</div></div>', page, re.S)
    card = card.group(0) if card else ""
    check(f"{mid}: Coming soon, credit and source, no Play", "Coming soon" in card and "Source</a>" in card
          and 'class="md-go"' not in card and PM.by_id(mid)["credit"]["source"] in card)
check("players text", "1-8 players" in page and "1 player" in page and "Any number of players" in page)
BANNED = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")
vis = re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", page, flags=re.S))
check("no game-brand names in the page", not BANNED.findall(vis))
check("no game-brand names in the catalog", not BANNED.findall(json.dumps(base)))
check("no script on the page", "<script" not in page)
saved = PM.CATALOG["modes"][0]["title"], PM.CATALOG["modes"][0]["line"]
PM.CATALOG["modes"][0]["title"], PM.CATALOG["modes"][0]["line"] = 'Go<script>x</script>"', "a & b <img src=x>"
sec = PM.section()
PM.CATALOG["modes"][0]["title"], PM.CATALOG["modes"][0]["line"] = saved
check("escaped", "Go&lt;script&gt;x&lt;/script&gt;&quot;" in sec and "a &amp; b &lt;img src=x&gt;" in sec and "<script>" not in sec)
check("the hub's own tests' counts are untouched (no extra shots or queue buttons)", page.count('class="md-shot"') == 4 and page.count(">Queue<") == 5)

# --- the play intent: unit --------------------------------------------------------------------------------------------
check("go_mode", PM.go_mode("mode:minigolf") == "minigolf" and PM.go_mode("mode:coin-dash") == "coin-dash")
for v in ("mode:brawl", "mode:azeroth-survivors", "mode:MINIGOLF", "mode:minigolf x", "mode:", "minigolf", "q:minigolf",
          "mode:" + "a" * 40, None, 5):
    check(f"go_mode refuses {v!r}", PM.go_mode(v) is None)
check("go_command", PM.go_command("wr000123", "minigolf") == "ovplay go WR000123 minigolf")
for acct, mid in (("WR 1", "minigolf"), ("A" * 17, "minigolf"), ("WR1;x", "minigolf"), ("WR1", "brawl"), ("WR1", "x;y"), (None, "minigolf")):
    check(f"go_command refuses {acct!r} {mid!r}", PM.go_command(acct, mid) is None)
calls = []
check("go_intent: confirmed", PM.go_intent(lambda c: calls.append(c) or "ovplay ok", "UNIT1", "minigolf") and calls == ["ovplay go UNIT1 minigolf"])
check("go_intent: the same again within 2 min is not resent", PM.go_intent(lambda c: calls.append(c) or "ovplay ok", "UNIT1", "minigolf") and len(calls) == 1)


def boom(c):
    raise wp.SoapError("down", "x")


check("go_intent: SOAP down is False, never raises", PM.go_intent(boom, "UNIT2", "minigolf") is False)
check("go_intent: no confirmation is False", PM.go_intent(lambda c: "There is no such command.", "UNIT3", "minigolf") is False)

# --- through the portal -------------------------------------------------------------------------------------------------
def sent(prefix):
    return [c for c in soap["commands"] if c.startswith(prefix)]


get("/wrath?go=mode:minigolf")
check("signed out: nothing sent", sent("ovplay") == [])
st, _, b = get("/wrath/account?go=mode:bumper-balls", cookie="wr_session=good")
check("signed in: the page still works", st == 200 and b"WR000123" in b, st)
check("signed in: ovplay go for the game account", sent("ovplay") == ["ovplay go WR000123 bumper-balls"], sent("ovplay"))
check("never as an ovgo place", sent("ovgo") == [])
get("/wrath?go=mode:coin-dash", cookie="wr_session=good")
check("/wrath with a mode", sent("ovplay")[-1] == "ovplay go WR000123 coin-dash", sent("ovplay"))
n = len(sent("ovplay"))
for v in ("mode:brawl", "mode:azeroth-survivors", "mode:hordes-of-azeroth", "mode:nope", "mode:MINIGOLF", "mode:%3Cx%3E", "mode:minigolf%20x"):
    get("/wrath/account?go=" + v, cookie="wr_session=good")
check("only live realm modes are sent", len(sent("ovplay")) == n, sent("ovplay")[n:])
soap["ovplay"] = None
st, _, b = get("/wrath/account?go=mode:community", cookie="wr_session=good")
check("realm without ov_playmode.lua: the page still works", st == 200 and b"WR000123" in b and sent("ovplay")[-1] == "ovplay go WR000123 community")
soap["ovplay"] = "ovplay ok"
check("the gate's go carries no mode (the realm acts on the account; nothing in the page)", wp.go_param({"go": ["mode:minigolf"]}) == "")
check("share-link go values still work", wp.go_param({"go": ["q:deadmines"]}) == "&go=q:deadmines")

# --- kept in step ---------------------------------------------------------------------------------------------------------
lua = open(os.path.join(REPO, "realm", "custom", "lua_scripts", "ov_playmode.lua"), encoding="utf-8").read()
table = lua[lua.index("local MODES = {"):lua.index("\n}\n", lua.index("local MODES = {"))]
lua_ids = re.findall(r'\["([a-z0-9-]+)"\] = \{', table)
check("ov_playmode.lua's table = the catalog's live realm modes", sorted(lua_ids) == sorted(PM.realm_ids()), (lua_ids, PM.realm_ids()))
for m in PM.entries():
    if m["kind"] == "realm":
        check(f"ov_playmode.lua title of {m['id']}", f'["{m["id"]}"] = {{ title = "{m["title"]}"' in table)
bat = open(os.path.join(REPO, "realm", "Server pass - finder 10 and bug reports.bat"), "rb").read()
check("server pass .bat copies ov_playmode.lua", b'copy /y "custom\\lua_scripts\\ov_playmode.lua" "%T%\\" >nul' in bat)
check("server pass .bat line endings unchanged (one style)", (b"\r\n" in bat) == (bat.count(b"\n") == bat.count(b"\r\n")))
for f in ("Update sign-in and warm-up.bat", "fastloop.sh", os.path.join("server", "stream-up.sh"), "Update browser client.bat"):
    t = open(os.path.join(HERE, f), encoding="utf-8", errors="replace").read()
    check(f"deploy: {f} carries playmodes.py and playmodes.json", "playmodes.py" in t and "playmodes.json" in t)
rs = open(os.path.join(REPO, "launcher", "src-tauri", "src", "modes.rs"), encoding="utf-8").read()
check("the launcher's built-in copy is this file", 'include_str!("../../../stream/playmodes.json")' in rs)
check("the launcher reads /wrath/modes.json", "https://play.openvanilla.app/wrath/modes.json" in rs)

print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
