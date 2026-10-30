"""The game data killswitch (stream/server/gamedata-switch.sh, docs/GAME-DATA-ON-OUR-SERVER.md):

  * Caddy: gamedata-caddy.py puts its 410 block first inside the streaming site that stream-up.sh writes, takes it
    out again byte for byte, is idempotent, and leaves a Caddyfile without a streaming site alone;
  * the sign-in gate (wrath_portal.py) with the flag file: /__auth answers 410 for /data and the manifests for every
    session, /wrath/play sends a streamed Play to "own game files", the page env says WU_GAMEDATA_OFF, the game
    screenshots answer 410, /wrath/status.json says "gamedata_streaming": false and since when; and all of it back
    as before without the flag;
  * the admin console's read-only status line (stream/admin.py).

    python3 -I stream/tests/test_gamedata.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
STREAM = os.path.dirname(HERE)
SOAP_PORT, REALM_PORT, PAGE_PORT = 17979, 18190, 18192
T = tempfile.mkdtemp(prefix="wu-gamedata-")
FLAG = os.path.join(T, "app", "gamedata-off")
os.makedirs(os.path.dirname(FLAG))
slices = os.path.join(T, "slices"); os.makedirs(slices)
with open(os.path.join(slices, "mini.json"), "w") as f:
    json.dump({"slice": "mini", "maxTier": 4, "title": "Mini"}, f)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_SLICE_DIR=slices, WU_STREAM="1", WU_OWNFILES="1",
                  STREAM_HOST="wrath.example", WU_GAMEDATA_FLAG=FLAG, WU_PORTAL_DATA=os.path.join(T, "data"),
                  WU_ART_DIR=os.path.join(STREAM, "www-files", "art"))

fails = 0
count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


# ------------------------------------------------------------------------------------------------ Caddy
spec = importlib.util.spec_from_file_location("gdc", os.path.join(STREAM, "server", "gamedata-caddy.py"))
gdc = importlib.util.module_from_spec(spec); spec.loader.exec_module(gdc)

# The streaming site exactly as stream-up.sh writes it (its heredoc, with the shell variables filled in).
up = open(os.path.join(STREAM, "server", "stream-up.sh")).read()
lib = open(os.path.join(STREAM, "server", "stream-lib.sh")).read()
here = re.search(r"cat >> \"\$CF\" <<EOF\n(.*?)\nEOF\n", up, re.S).group(1)
mb = re.search(r'MARK_BEGIN="([^"]+)"', lib).group(1)
me = re.search(r'MARK_END="([^"]+)"', lib).group(1)
site = (here.replace("$MARK_BEGIN", mb).replace("$MARK_END", me).replace("$STREAM_HOST", "wrath.openvanilla.app"))
other = "play.openvanilla.app {\n\thandle {\n\t\treverse_proxy ovlive-realm:8090\n\t}\n}\n"
cf = other + "\n" + site + "\n"
check("caddy: the markers match stream-up.sh's", mb == gdc.STREAM_BEGIN and me == gdc.STREAM_END)
check("caddy: status of a plain streaming site is off", gdc.status(cf) == "off")
on = gdc.add(cf, "wrath.openvanilla.app")
check("caddy: status after add is on", gdc.status(on) == "on")
i_block, i_gate, i_client, i_auth = (on.index(gdc.BEGIN), on.index("@gate path"), on.index("@client path"),
                                     on.index("\tforward_auth"))
check("caddy: the 410 block comes first in the site (before the gate, the client route and forward_auth)",
      on.index("wrath.openvanilla.app {") < i_block < i_gate < i_client < i_auth)
check("caddy: it closes /data, /data/* and both manifests",
      "@gamedata_off path /data /data/* /boot-manifest.json /world-manifest.json" in on)
check("caddy: it answers 410 with a JSON body", re.search(r"respond `\{.*\}` 410\n", on) is not None)
body = re.search(r"respond `(.*)` 410", on).group(1)
doc = json.loads(body)
check("caddy: the body says what the player needs", doc["error"] == "gamedata_off" and doc["gamedata_streaming"] is False
      and "your own game folder" in doc["message"] and "3.3.5a" in doc["message"])
check("caddy: the body has no Caddy placeholders other than the JSON itself",
      "{http." not in body and "{path" not in body and "{env." not in body)
check("caddy: no-store and same-origin on the 410", 'header Cache-Control "no-store"' in on
      and "header Cross-Origin-Resource-Policy same-origin" in on)
check("caddy: the other site is untouched", on.startswith(other))
check("caddy: add twice = once", gdc.add(on, "wrath.openvanilla.app") == on and on.count(gdc.BEGIN) == 1)
check("caddy: remove gives back the file byte for byte", gdc.strip(on) == cf)
check("caddy: remove of a file without it changes nothing", gdc.strip(cf) == cf)
check("caddy: the client's own files and the page still go to wu-play", gdc.strip(on).count("wu-play:8090") == on.count("wu-play:8090") >= 4)
try:
    gdc.add(other)
    check("caddy: no streaming site -> LookupError", False)
except LookupError:
    check("caddy: no streaming site -> LookupError", True)
check("caddy: status without a site", gdc.status(other) == "no-site")
# the command line, on a file
p = os.path.join(T, "Caddyfile")
open(p, "w").write(cf)
check("caddy cli: add -> 0", gdc.main(["x", "add", p, "wrath.openvanilla.app"]) == 0 and open(p).read() == on)
check("caddy cli: remove -> 0", gdc.main(["x", "remove", p]) == 0 and open(p).read() == cf)
open(p, "w").write(other)
check("caddy cli: no site -> 3, file untouched", gdc.main(["x", "add", p]) == 3 and open(p).read() == other)
open(p, "w").write(other + "\n" + mb + "\nwrath.openvanilla.app {\n")
check("caddy cli: a broken streaming block -> 2", gdc.main(["x", "add", p]) == 2)
check("caddy: tabs, like the rest of the block", all(l.startswith("\t") for l in gdc.block().splitlines()))

# ------------------------------------------------------------------------------------------------ the portal
pspec = importlib.util.spec_from_file_location("wp", sys.argv[1] if len(sys.argv) > 1 else os.path.join(STREAM, "wrath_portal.py"))
wp = importlib.util.module_from_spec(pspec); pspec.loader.exec_module(wp)
soap = {"commands": []}


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        cmd = wp._tag_text(self.rfile.read(int(self.headers["Content-Length"])), "command")
        soap["commands"].append(cmd)
        text = ("ovstream ok" if cmd.startswith("ovstream") else
                "Connected players: 3 (peak: 4).\nCharacters in world: 10 (peak: 10, lifetime: 10).\nServer uptime: 1 hour(s)"
                if cmd == "server info" else "done")
        inner = f"<ns1:executeCommandResponse><result>{escape(text)}</result></ns1:executeCommandResponse>"
        b = ('<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
             f'xmlns:ns1="urn:AC"><SOAP-ENV:Body>{inner}</SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class Realm(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if "wr_session=good" not in self.headers.get("Cookie", ""):
            self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = {"/api/me": {"display_name": "Tester"}, "/api/play": {"user": "WR000123", "pass": "Pa55word1234abcd"}}[self.path]
        b = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


for port, h in ((SOAP_PORT, Soap), (REALM_PORT, Realm), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

ip_n = [0]


def get(path, cookie="", headers=None):
    ip_n[0] += 1
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    hd = {"X-Forwarded-For": f"10.9.{ip_n[0] // 200}.{ip_n[0] % 200 + 1}"}
    if cookie:
        hd["Cookie"] = cookie
    hd.update(headers or {})
    c.request("GET", path, headers=hd)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


def play_session(path="/wrath/play?mini=mini"):
    """Sign in, press Play, swap the code at the gate: (the Play redirect, the gate's landing, the wu_play cookie)."""
    st, h, _ = get(path, cookie="wr_session=good")
    loc = h.get("location", "")
    if st != 302 or "/__gate?code=" not in loc:
        return loc, None, None
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)["code"][0]
    st, h, _ = get("/__gate?code=" + urllib.parse.quote(code))
    return loc, h.get("location"), h.get("set-cookie", "").split(";")[0]


def status():
    st, h, b = get("/wrath/status.json")
    return st, json.loads(b)


# --- streaming on (no flag): as before
st, doc = status()
check("on: status.json says gamedata_streaming true, no since", st == 200 and doc.get("gamedata_streaming") is True
      and doc.get("gamedata_since") is None and doc.get("players") == 3)
_, land, stream_ck = play_session()
check("on: Play streams the slice (gate lands on /)", land == "/", land)
st, _, _ = get("/__auth", cookie=stream_ck, headers={"X-Forwarded-Uri": "/data/__tier/index.json"})
check("on: a stream session reads /data", st == 200)
st, h, _ = get("/__auth", headers={"X-Forwarded-Uri": "/data/__tier/index.json"})
check("on: no session -> the gate (302), not 410", st == 302)
st, _, b = get("/__env.js", cookie=stream_ck)
check("on: env has no WU_GAMEDATA_OFF", st == 200 and b"WU_GAMEDATA_OFF" not in b)
st, _, _ = get("/wrath/art/leyline-shot-city.webp")
check("on: the screenshots are served", st == 200)
check("on: stream_on()", wp.stream_on() and not wp.gamedata_off())
_, _, b = get("/wrath/account", cookie="wr_session=good")
check("on: no killswitch words on the realm list", b"needs your own game folder" not in b)

# --- the switch: the flag file appears (gamedata-switch.sh off)
with open(FLAG, "w") as f:
    f.write('{"gamedata_streaming": false, "since": "2026-10-29T18:04:00Z", "by": "owner"}\n')
check("off: stream_on() is off whatever WU_STREAM says", not wp.stream_on() and wp.gamedata_off())
st, doc = status()
check("off: status.json says gamedata_streaming false, since the switch", doc.get("gamedata_streaming") is False
      and doc.get("gamedata_since") == "2026-10-29T18:04:00Z", doc)
check("off: status.json keeps the realm numbers", doc.get("online") is True and doc.get("players") == 3)
for uri in ("/data/__tier/index.json", "/data/DBFilesClient%5CMap.dbc", "/data/__index", "/data", "/boot-manifest.json",
            "/world-manifest.json?v=2"):
    for who, ck in (("no session", ""), ("old stream session", stream_ck)):
        st, h, b = get("/__auth", cookie=ck, headers={"X-Forwarded-Uri": uri})
        check(f"off: {uri} ({who}) -> 410 Gone with JSON", st == 410 and h.get("content-type", "").startswith("application/json")
              and json.loads(b)["error"] == "gamedata_off")
own_loc, own_land, own_ck = play_session("/wrath/play?mode=own")
st, _, _ = get("/__auth", cookie=own_ck, headers={"X-Forwarded-Uri": "/data/__index"})
check("off: an own-files session gets 410 for /data too", st == 410)
for uri in ("/?ownfiles=1", "/wenilla_bg.wasm", "/ownfiles.js", "/ws/3724"):
    st, _, _ = get("/__auth", cookie=own_ck, headers={"X-Forwarded-Uri": uri})
    check(f"off: own files still reach {uri}", st == 200)
st, h, _ = get("/__auth", cookie=stream_ck, headers={"X-Forwarded-Uri": "/"})
check("off: an old stream page is sent to Play again (no stream any more)", st == 302
      and h["location"] == "https://play.openvanilla.app/wrath/play?mini=mini")
soap["commands"].clear()
loc, land, ck = play_session("/wrath/play?mini=mini")
check("off: a streamed Play becomes own files (gate lands on /?ownfiles=1)", land == "/?ownfiles=1", (loc, land))
check("off: no realm mark", not any(c.startswith("ovstream mark") for c in soap["commands"]), soap["commands"])
check("off: the account is cleared from any old mark", "ovstream clear WR000123" in soap["commands"])
st, _, b = get("/__env.js", cookie=ck)
check("off: env says WU_GAMEDATA_OFF and no stream offer", st == 200 and b"window.WU_GAMEDATA_OFF = true;" in b
      and b"window.WU_STREAM_AVAILABLE = false;" in b and b'"mode":"own"' in b)
st, _, b = get("/__env.js", cookie=stream_ck)
check("off: an old stream session gets no login (back to the sign-in)", st == 401)
st, h, b = get("/wrath/art/leyline-shot-city.webp")
check("off: game screenshots -> 410", st == 410)
st, _, _ = get("/wrath/art/wu-theme.css")
check("off: our own art is still served", st == 200)
_, _, b = get("/wrath/account", cookie="wr_session=good")
check("off: realm list: Dalaran plays with the game folder, says why", b"/wrath/play?mode=own" in b
      and b"Play with my game folder" in b and b"needs your own game folder" in b and b"/wrath/play?mini=mini" not in b)
os.environ["WU_OWNFILES"] = "0"
st, _, b = get("/wrath/play?mini=mini", cookie="wr_session=good")
check("off, own files not set up: a plain page, no stream", st == 200 and b"needs your own game folder" in b)
os.environ["WU_OWNFILES"] = "1"
for word in (b"World of Warcraft", b"Warcraft", b"Blizzard", b"Lich King"):
    check(f"off: no {word.decode()} in the player pages", word not in b and word not in wp.GAMEDATA_GONE)
check("off: no WoW in the 410 body", not re.search(rb"\bWoW\b", wp.GAMEDATA_GONE))
os.remove(FLAG)
with open(FLAG, "w") as f:
    f.write("junk")
st, doc = status()
check("off (odd flag file): still off, since = the file's time", doc.get("gamedata_streaming") is False
      and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", doc.get("gamedata_since") or "") is not None)

# --- the admin console's status line (read-only)
A = wp.admin
if A is not None:
    line = A.gamedata_line()
    check("admin: off line", "Game data streaming: <b>off</b> since " in line and "own 3.3.5a game folder" in line)
    check("admin: the line has no button", "<form" not in line and "<button" not in line)
    names = [n for n, _, _ in A.health_checks()]
    check("admin: Health lists game data streaming", "Game data streaming" in names)

# --- back on (gamedata-switch.sh on): the flag goes, gamedata-last.json says since when
os.remove(FLAG)
with open(os.path.join(os.path.dirname(FLAG), "gamedata-last.json"), "w") as f:
    f.write('{"state": "on", "at": "2026-11-02T09:00:00Z", "by": "owner"}\n')
st, doc = status()
check("on again: status.json true, since the switch", doc.get("gamedata_streaming") is True
      and doc.get("gamedata_since") == "2026-11-02T09:00:00Z", doc)
_, land, ck = play_session()
check("on again: Play streams the slice", land == "/")
st, _, _ = get("/__auth", cookie=ck, headers={"X-Forwarded-Uri": "/data/__index"})
check("on again: /data for a stream session", st == 200)
st, _, _ = get("/wrath/art/leyline-shot-city.webp")
check("on again: screenshots back", st == 200)
if A is not None:
    check("admin: on line, since the switch", "Game data streaming: <b>on</b> since 2026-11-02 09:00 UTC" in A.gamedata_line())

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
