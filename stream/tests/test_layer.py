"""Local test of the game-folder layer's realm side (POST /__gate?layer=on|off|beat, the lease and its sweeper)
against a fake AzerothCore SOAP server and a fake Open Vanilla realm service.

    python3 -I stream/tests/test_layer.py stream/wrath_portal.py

on: the same "ovstream clear" as own files, a lease; beat: renews it (no SOAP); off: "ovstream mark" for what is
left of the session, once; a lapsed lease is marked again by the sweeper (retried when the realm fails); a new
stream play, own files and "End my browser pass" drop the lease; only same-origin JSON posts from a streamed
session (not own files, not a hop, not with streaming off); a wrong build is refused; no password in any answer.
"""
import http.client, json, os, sys, tempfile, threading, importlib.util, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, PAGE_PORT = 17979, 18190, 18192
slices = tempfile.mkdtemp()
with open(os.path.join(slices, "mini.json"), "w") as f:
    json.dump({"slice": "mini", "maxTier": 4, "title": "Mini"}, f)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_SLICE_DIR=slices, WU_STREAM="1", WU_OWNFILES="1",
                  STREAM_HOST="wrath.example")

spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

soap = {"commands": [], "reply": "ovstream ok"}
PASSWORD = "Pa55word1234abcd"


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        cmd = wp._tag_text(self.rfile.read(int(self.headers["Content-Length"])), "command")
        soap["commands"].append(cmd)
        if cmd.startswith("account create"):
            ok, text = False, "Account with this name already exist!"
        elif cmd.startswith("ovstream"):
            ok, text = soap["reply"] is not None, soap["reply"] or "There is no such command."
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
        doc = {"/api/me": {"display_name": "Tester"}, "/api/play": {"user": "WR000123", "pass": PASSWORD}}[self.path]
        body = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


for port, h in ((SOAP_PORT, Soap), (REALM_PORT, Realm), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, cookie="", headers=None, body=None, ip="10.9.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    h = {"X-Forwarded-For": ip}
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


ORIGIN = {"Origin": "https://wrath.example", "Content-Type": "application/json"}


def layer(op, cookie, body=None, headers=None, ip="10.9.0.1"):
    st, h, b = req("POST", "/__gate?layer=" + op, cookie, ORIGIN if headers is None else headers,
                   json.dumps(body or {"build": 12340, "names": 5}).encode(), ip)
    try:
        doc = json.loads(b)
    except ValueError:
        doc = {}
    return st, doc, b


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


def new_session(ip="10.9.0.1"):
    st, h, _ = req("GET", "/wrath/play?mini=mini", "wr_session=good", ip=ip)
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(h["location"]).query)["code"][0]
    st, h, _ = req("GET", "/__gate?code=" + urllib.parse.quote(code), ip=ip)
    return h["set-cookie"].split(";")[0]


def since(n):
    return soap["commands"][n:]


cookie = new_session()
st, h, b = req("GET", "/__env.js", cookie)
check("env: a streamed session may offer the layer", b'"layer":"1"' in b)

# --- refusals, none of which touch the realm
n = len(soap["commands"])
st, doc, _ = layer("on", cookie, headers={"Content-Type": "application/json"})
check("no Origin: 403", st == 403)
st, doc, _ = layer("on", cookie, headers={"Origin": "https://evil.example", "Content-Type": "application/json"})
check("another site's Origin: 403", st == 403)
st, doc, _ = layer("on", cookie, headers={"Origin": "https://wrath.example", "Content-Type": "text/plain"})
check("not JSON (a form post from anywhere): 415", st == 415)
st, doc, _ = layer("on", "")
check("no session: 403", st == 403 and doc.get("state") == "n/a")
st, doc, _ = layer("dance", cookie)
check("an unknown op: 400", st == 400)
st, doc, _ = layer("on", cookie, body={"build": 5875})
check("a 1.12 build: refused", st == 400 and "12340" in doc.get("why", ""))
st, doc, _ = layer("beat", cookie)
check("beat with no lease: 409 (the page asks with on)", st == 409 and doc.get("state") == "held")
st, doc, _ = layer("off", cookie)
check("off with no lease: held, no SOAP", st == 200 and doc == {"ok": True, "state": "held"})
check("the refusals sent nothing to the realm", since(n) == [], since(n))

# --- on / beat / off
n = len(soap["commands"])
st, doc, raw = layer("on", cookie)
check("on: lifted", st == 200 and doc.get("ok") and doc.get("state") == "lifted" and doc.get("lease") == wp.LAYER_LEASE)
check("on: the same SOAP clear as own files", since(n) == ["ovstream clear WR000123"], since(n))
check("on: a lease", wp.layers.has("WR000123"))
check("no password in any answer", PASSWORD.encode() not in raw)
n = len(soap["commands"])
st, doc, _ = layer("beat", cookie)
check("beat: renewed, no SOAP", st == 200 and doc.get("state") == "lifted" and since(n) == [])
st, doc, _ = layer("off", cookie)
marks = since(n)
check("off: marked again for what is left of the session", st == 200 and doc.get("state") == "held" and len(marks) == 1
      and marks[0].startswith("ovstream mark WR000123 mini 4 ") and 43000 < int(marks[0].split()[-1]) <= 43200, marks)
check("off: the lease is gone", not wp.layers.has("WR000123"))
n = len(soap["commands"])
layer("off", cookie)
check("off twice: no second mark", since(n) == [])

# --- the realm does not answer
soap["reply"] = None
st, doc, _ = layer("on", cookie)
check("on, realm down: 503, not lifted", st == 503 and doc.get("state") == "held" and not wp.layers.has("WR000123"))
soap["reply"] = "ovstream ok"
layer("on", cookie)
soap["reply"] = None
st, doc, _ = layer("off", cookie)
check("off, realm down: 503, the lease kept for the sweeper", st == 503 and wp.layers.has("WR000123"))
soap["reply"] = "ovstream ok"
st, doc, _ = layer("beat", cookie)
check("a lease waiting for its mark does not renew", st == 409)
n = len(soap["commands"])
check("the sweeper marks it", wp.sweep_layers(time.time() + 31) == 1 and since(n)[0].startswith("ovstream mark WR000123 mini 4 "))
check("then it is gone", not wp.layers.has("WR000123"))

# --- a lapsed lease (the tab closed, crashed, or reloaded without the folder and never said so)
layer("on", cookie)
n = len(soap["commands"])
check("a live lease: the sweeper leaves it", wp.sweep_layers(time.time() + 60) == 0 and since(n) == [])
soap["reply"] = None
check("lapsed, realm down: retried later", wp.sweep_layers(time.time() + wp.LAYER_LEASE + 1) == 0 and wp.layers.has("WR000123"))
soap["reply"] = "ovstream ok"
n = len(soap["commands"])
check("lapsed: marked on the next sweep", wp.sweep_layers(time.time() + wp.LAYER_LEASE + 40) == 1
      and since(n)[0].startswith("ovstream mark WR000123 mini 4 ") and not wp.layers.has("WR000123"))
lease = {"slice": "mini", "tier": 4, "sess_exp": time.time() + 30}
n = len(soap["commands"])
wp.layer_mark("WR000123", lease)
check("a session about to end: marked for at least a minute", since(n) == ["ovstream mark WR000123 mini 4 60"], since(n))

# --- a new stream play, own files, "End my browser pass": the lease goes
layer("on", cookie)
cookie2 = new_session()
check("a new stream play drops the lease (its mark is new)", not wp.layers.has("WR000123"))
layer("on", cookie2)
req("GET", "/wrath/play?mode=own", "wr_session=good", ip="10.9.0.2")
check("own files drop the lease", not wp.layers.has("WR000123"))
cookie3 = new_session(ip="10.9.0.3")
layer("on", cookie3, ip="10.9.0.3")
req("GET", "/wrath/play/end", "wr_session=good", ip="10.9.0.3")
check("End my browser pass drops the lease", not wp.layers.has("WR000123"))

# --- sessions that are not streamed
st, h, _ = req("GET", "/wrath/play?mode=own", "wr_session=good", ip="10.9.0.4")
code = urllib.parse.parse_qs(urllib.parse.urlsplit(h["location"]).query)["code"][0]
st, h, _ = req("GET", "/__gate?code=" + urllib.parse.quote(code), ip="10.9.0.4")
own_cookie = h["set-cookie"].split(";")[0]
st, h, b = req("GET", "/__env.js", own_cookie, ip="10.9.0.4")
check("env: an own-files session does not offer the layer", b'"layer"' not in b)
st, doc, _ = layer("on", own_cookie, ip="10.9.0.4")
check("own files: no layer (it has the whole world already)", st == 403)
cookie4 = new_session(ip="10.9.0.5")
sid4 = cookie4.split("=", 1)[1]
wp.sessions.set_hop(sid4, {"id": "abcdefghijklmnop", "name": "Frost Haven"})
st, doc, _ = layer("on", cookie4, ip="10.9.0.5")
check("a realm hop: no layer", st == 403)
cookie5 = new_session(ip="10.9.0.6")
os.environ["WU_STREAM"] = "0"
st, doc, _ = layer("on", cookie5, ip="10.9.0.6")
check("streaming off: 503", st == 503 and doc.get("state") == "off")
n = len(soap["commands"])
os.environ["WU_STREAM"] = "1"
layer("on", cookie5, ip="10.9.0.6")
os.environ["WU_STREAM"] = "0"
check("streaming off: a lapsed lease is not marked (the switch released every mark)",
      wp.sweep_layers(time.time() + wp.LAYER_LEASE + 1) == 0 and since(n) == ["ovstream clear WR000123"], since(n))
os.environ["WU_STREAM"] = "1"

# --- the page's GET /__gate is unchanged, and the page still points players at the help
st, h, _ = req("GET", "/__gate?code=bogus")
check("GET /__gate unchanged", st == 302 and h["location"] == "https://play.openvanilla.app/wrath")
st, h, b = req("GET", "/wrath?list=1", "wr_session=good", ip="10.9.0.7")
check("account page: drop your game folder, with the help link", b"Drop it on the game page" in b
      and b"/wrath/docs/play#use-your-own-game-folder-to-go-anywhere" in b and b"Where is my game folder?" in b)
for word in (b"World of Warcraft", b"Warcraft", b"Lich King", b"Blizzard", b"WoW"):
    if word in b:
        check(f"no {word.decode()} on the account page", False)
        break
else:
    check("no game-brand names on the account page", True)
st, h, b = req("POST", "/__layer?layer=off", cookie5, ORIGIN, b"{}")
check("/__layer works too (for a Caddyfile that routes it)", st == 200)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
