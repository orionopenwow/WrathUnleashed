"""Local test of the streaming gate (/wrath/play, /__gate, /__auth, /__env.js, /wrath/play/end)
against a fake AzerothCore SOAP server and a fake Open Vanilla realm service.

    python3 -I tests/test_stream.py wrath_portal.py
"""
import http.client, json, os, sys, tempfile, threading, importlib.util, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, PAGE_PORT = 17879, 18090, 18092
slices = tempfile.mkdtemp()
with open(os.path.join(slices, "mini.json"), "w") as f:
    json.dump({"slice": "mini", "maxTier": 4, "title": "Mini"}, f)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_SLICE_DIR=slices, WU_STREAM="1",
                  STREAM_HOST="wrath.example")

spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

soap = {"commands": [], "reply": "ovstream ok", "fail_create": True}


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        cmd = wp._tag_text(self.rfile.read(int(self.headers["Content-Length"])), "command")
        soap["commands"].append(cmd)
        if cmd.startswith("account create") and soap["fail_create"]:
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
        doc = {"/api/me": {"display_name": "Tester"}, "/api/play": {"user": "WR000123", "pass": "Pa55word1234abcd"}}[self.path]
        body = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


for port, h in ((SOAP_PORT, Soap), (REALM_PORT, Realm), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, cookie="", headers=None, ip="10.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    h = {"X-Forwarded-For": ip}
    if cookie:
        h["Cookie"] = cookie
    h.update(headers or {})
    c.request("GET", path, headers=h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


fails = 0
count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


# --- /wrath/play signed out
st, h, b = get("/wrath")
check("signed out /wrath: saved-key sign-in page", st == 200 and b"AUTO" not in b and b"/auth/key" in b and "connect-src 'self'" in (h.get("content-security-policy") or h.get("Content-Security-Policy") or ""))
st, h, b = get("/wrath/play?mini=mini")
check("signed out: sign-in page", st == 200 and b"Sign in with Google" in b)
check("signed out: no realm mark", not any(c.startswith("ovstream") for c in soap["commands"]))

# --- unknown slice
st, h, b = get("/wrath/play?mini=everything", cookie="wr_session=good")
check("unknown slice: 404", st == 404)

# --- signed in: mark + redirect to the gate
st, h, b = get("/wrath/play?mini=mini", cookie="wr_session=good")
loc = h.get("location", "")
check("play: 302 to the stream gate", st == 302 and loc.startswith("https://wrath.example/__gate?code="), loc)
check("play: account ensured", "account set password WR000123 Pa55word1234abcd Pa55word1234abcd" in soap["commands"])
check("play: realm mark with the slice tier and 12 h", "ovstream mark WR000123 mini 4 43200" in soap["commands"], soap["commands"][-1])
check("play: no-store", h.get("cache-control") == "no-store")
code = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)["code"][0]
check("play: password not in the redirect", "Pa55word" not in loc)

# --- the gate swaps the code once for the cookie
st, h, b = get("/__gate?code=" + urllib.parse.quote(code))
ck = h.get("set-cookie", "")
check("gate: 302 to /", st == 302 and h.get("location") == "/")
check("gate: cookie flags", all(x in ck for x in ("wu_play=", "HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=43200")), ck)
sid = ck.split(";")[0].split("=", 1)[1]
st, h, b = get("/__gate?code=" + urllib.parse.quote(code))
check("gate: a code works once", st == 302 and "wu_play" not in h.get("set-cookie", "") and h["location"].endswith("/wrath"))
st, h, b = get("/__gate?code=bogus")
check("gate: bad code goes back to the sign-in page", st == 302 and h["location"] == "https://play.openvanilla.app/wrath")

# --- expired code
code2 = wp.sessions.create("WR000123", "Pa55word1234abcd", "mini", 4)
with wp.sessions.lock:
    sid2, _ = wp.sessions.codes[code2]
    wp.sessions.codes[code2] = (sid2, time.time() - 1)
st, h, b = get("/__gate?code=" + code2)
check("gate: an expired code is refused", "wu_play" not in h.get("set-cookie", ""))

# --- forward_auth
st, h, b = get("/__auth", cookie=f"wu_play={sid}", headers={"X-Forwarded-Uri": "/data/DBFilesClient%5CMap.dbc"})
check("auth: valid cookie -> 200", st == 200)
st, h, b = get("/__auth", headers={"X-Forwarded-Uri": "/"})
check("auth: no cookie -> 302 to /wrath", st == 302 and h["location"] == "https://play.openvanilla.app/wrath")
st, h, b = get("/__auth", cookie="wu_play=forged", headers={"X-Forwarded-Uri": "/data/x"})
check("auth: forged cookie -> 302", st == 302)

# --- env.js
st, h, b = get("/__env.js", cookie=f"wu_play={sid}")
txt = b.decode()
check("env: 200 js", st == 200 and h["content-type"].startswith("application/javascript"))
check("env: global name the client reads", txt.startswith("window.__wenilla_env = "))
env = json.loads(txt.split("\n")[0][len("window.__wenilla_env = "):].rstrip(";"))
check("env: Forever UI on by default", env.get("foreverui") == "1")
check("env: ?foreverui= on the page is copied over the env (the env outranks the query)", "get('foreverui')" in txt and "e.foreverui=v" in txt)
check("env: user/pass/host", env["user"] == "WR000123" and env["pass"] == "Pa55word1234abcd" and env["host"] == "play.openvanilla.app", env)
check("env: no dev_query_creds", "dev_query_creds" not in env)
check("env: no-store + same-origin", h.get("cache-control") == "no-store" and h.get("cross-origin-resource-policy") == "same-origin")
st, h, b = get("/__env.js")
check("env: no session -> 401, no password", st == 401 and b"Pa55word" not in b)

# --- the off switch
os.environ["WU_STREAM"] = "0"
st, h, b = get("/wrath/play?mini=mini", cookie="wr_session=good")
check("off: /wrath/play says streaming is off", st == 200 and "Streaming is off right now".encode() in b)
check("off: the Discord help line", b"https://discord.gg/hVeUxYwbkr" in b)
st, h, b = get("/__auth", cookie=f"wu_play={sid}", headers={"X-Forwarded-Uri": "/data/DBFilesClient%5CMap.dbc"})
check("off: /data denied even with a session", st == 403)
st, h, b = get("/__auth", cookie=f"wu_play={sid}", headers={"X-Forwarded-Uri": "/ws/8085?host=x"})
check("off: /ws denied", st == 403)
st, h, b = get("/__env.js", cookie=f"wu_play={sid}")
check("off: no credentials handed out", st == 401 and b"Pa55word" not in b)
st, h, b = get("/wrath", cookie="wr_session=good")
check("off: no Play-in-browser button", b"/wrath/play?mini=mini" not in b)
os.environ["WU_STREAM"] = "1"
st, h, b = get("/wrath", cookie="wr_session=good")
check("on: /wrath (Play now) goes straight into the game", st in (302, 303) and (h.get("location") or h.get("Location") or "") == "/wrath/play?mini=mini", str(st))
st, h, b = get("/wrath/account", cookie="wr_session=good")
check("on: account page shows the button + Discord line", b"/wrath/play?mini=mini" in b and b"discord.gg/hVeUxYwbkr" in b)

# --- the realm does not confirm the mark: no session
soap["reply"] = None
n = len(wp.sessions.sessions)
st, h, b = get("/wrath/play?mini=mini", cookie="wr_session=good", ip="10.0.0.9")
check("no realm script: 503, no session", st == 503 and len(wp.sessions.sessions) == n)
soap["reply"] = "ovstream ok"

# --- ending the pass
st, h, b = get("/wrath/play/end", cookie="wr_session=good", ip="10.0.0.8")
check("end: 200", st == 200 and b"pass has ended" in b)
check("end: realm clear", soap["commands"][-1] == "ovstream clear WR000123")
st, h, b = get("/__auth", cookie=f"wu_play={sid}", headers={"X-Forwarded-Uri": "/"})
check("end: the session is gone", st == 302)

# --- rate limit on the gate
codes = [get("/__gate?code=x", ip="10.9.9.9")[0] for _ in range(65)]
check("gate rate limit (60 a minute per address)", codes.count(429) == 5, codes)
plays = [get("/wrath/play?mini=mini", ip="10.9.9.8") for _ in range(32)]
check("play rate limit (30 a minute per address)", [p[0] for p in plays].count(429) == 2, [p[0] for p in plays])
busy = plays[-1][2]
check("a 429 page retries by itself, no script", b'http-equiv="refresh"' in busy and b"<script" not in busy and b"Trying again" in busy)

# --- per-user session cap
for _ in range(5):
    wp.sessions.create("CAPUSER", "pw", "mini", 0)
check("sessions per user capped", sum(1 for v in wp.sessions.sessions.values() if v["user"] == "CAPUSER") == wp.Sessions.PER_USER)

# --- "Play with my own game files" (mode=own)
st, h, b = get("/wrath", cookie="wr_session=good")
check("own: no button while WU_OWNFILES is not 1", b"/wrath/play?mode=own" not in b)
st, h, b = get("/wrath/play?mode=own", cookie="wr_session=good", ip="10.1.0.1")
check("own: refused while WU_OWNFILES is not 1", st == 404)
os.environ["WU_OWNFILES"] = "1"
st, h, b = get("/wrath/account", cookie="wr_session=good")
check("own: realm list shows both ways to play", b"<h2>Dalaran</h2>" in b and b"Play in the browser with my game folder" in b
      and b"/wrath/play?mode=own" in b and b"/wrath/play?mini=mini" in b)
st, h, b = get("/wrath/play?mode=own", ip="10.1.0.1")
check("own: signed out -> sign-in page", st == 200 and b"Sign in with Google" in b)
stream_code = wp.sessions.create("WR000123", "Pa55word1234abcd", "mini", 4)
stream_sid = wp.sessions.redeem(stream_code)
before = len(soap["commands"])
st, h, b = get("/wrath/play?mode=own", cookie="wr_session=good", ip="10.1.0.1")
loc = h.get("location", "")
new = soap["commands"][before:]
check("own: 302 to the stream gate", st == 302 and loc.startswith("https://wrath.example/__gate?code="), loc)
check("own: no realm mark (the whole world)", not any(c.startswith("ovstream mark") for c in new), new)
check("own: an earlier stream mark is cleared", "ovstream clear WR000123" in new, new)
check("own: the player's stream session is ended", wp.sessions.get(stream_sid) is None)
ocode = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)["code"][0]
st, h, b = get("/__gate?code=" + urllib.parse.quote(ocode))
check("own: the gate lands on /?ownfiles=1", st == 302 and h.get("location") == "/?ownfiles=1", h.get("location"))
osid = h.get("set-cookie", "").split(";")[0].split("=", 1)[1]
st, h, b = get("/__auth", cookie=f"wu_play={osid}", headers={"X-Forwarded-Uri": "/data/DBFilesClient%5CMap.dbc"})
check("own: /data denied (they read their own files)", st == 403)
st, h, b = get("/__auth", cookie=f"wu_play={osid}", headers={"X-Forwarded-Uri": "/data/__tier/2.txt"})
check("own: /data/__tier denied too", st == 403)
for uri in ("/?ownfiles=1", "/ownfiles.js", "/wenilla_bg.wasm", "/ws/3724", "/ws/8085?host=x"):
    st, h, b = get("/__auth", cookie=f"wu_play={osid}", headers={"X-Forwarded-Uri": uri})
    check(f"own: {uri} allowed", st == 200)
st, h, b = get("/__env.js", cookie=f"wu_play={osid}")
txt = b.decode()
oenv = json.loads(txt.split("\n")[0][len("window.__wenilla_env = "):].rstrip(";"))
check("own: env has the login and mode own, no slice", oenv.get("mode") == "own" and oenv["user"] == "WR000123" and "slice" not in oenv, oenv)
check("own: env offers the stream when it is on", "window.WU_STREAM_AVAILABLE = true;" in txt and "wrath/play?mini=mini" in txt)
# streaming off does not touch own mode
os.environ["WU_STREAM"] = "0"
soap["reply"] = None   # ov_slices.lua unloaded: the clear fails, which is fine while streaming is off
st, h, b = get("/wrath", cookie="wr_session=good")
check("own, stream off: own button stays, mini button goes", b"/wrath/play?mode=own" in b and b"/wrath/play?mini=mini" not in b)
st, h, b = get("/wrath/play?mode=own", cookie="wr_session=good", ip="10.1.0.2")
check("own, stream off: still a session", st == 302 and "/__gate?code=" in h.get("location", ""), (st, h.get("location")))
o2 = urllib.parse.parse_qs(urllib.parse.urlsplit(h["location"]).query)["code"][0]
st, h, b = get("/__gate?code=" + urllib.parse.quote(o2))
osid2 = h.get("set-cookie", "").split(";")[0].split("=", 1)[1]
st, h, b = get("/__auth", cookie=f"wu_play={osid2}", headers={"X-Forwarded-Uri": "/ws/8085"})
check("own, stream off: /ws allowed", st == 200)
st, h, b = get("/__auth", cookie=f"wu_play={osid2}", headers={"X-Forwarded-Uri": "/data/x"})
check("own, stream off: /data denied", st == 403)
st, h, b = get("/__env.js", cookie=f"wu_play={osid2}")
check("own, stream off: env still handed out, no stream offer", st == 200 and b"WU_STREAM_AVAILABLE = false" in b)
st, h, b = get("/wrath/play?mini=mini", cookie="wr_session=good", ip="10.1.0.3")
check("own, stream off: the stream itself stays off", b"Streaming is off right now" in b)
os.environ["WU_STREAM"] = "1"
st, h, b = get("/wrath/play?mode=own", cookie="wr_session=good", ip="10.1.0.4")
check("own, stream on: a failed clear refuses (the mark would hold the player)", st == 503)
soap["reply"] = "ovstream ok"
del os.environ["WU_OWNFILES"]

# --- the existing page still works unchanged
st, h, b = get("/wrath/account", cookie="wr_session=good")
check("/wrath account page still shows the login", st == 200 and b"WR000123" in b)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
