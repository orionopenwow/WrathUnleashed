"""Local test of a Leyline realm hop through the portal: /wrath/play (stream and own files) with ?go=r:<id>,
the gate, and /__env.js for that session (the relay's addresses for the realm, never the Wrath login), against
a fake SOAP server, a fake Open Vanilla realm service and a fake relay listing.

    python3 -I stream/tests/test_hop.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, RELAY_PORT, PAGE_PORT = 17883, 18095, 18096, 18097
slices = tempfile.mkdtemp()
with open(os.path.join(slices, "mini.json"), "w") as f:
    json.dump({"slice": "mini", "maxTier": 4, "title": "Mini"}, f)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_SLICE_DIR=slices, WU_STREAM="1", WU_OWNFILES="1",
                  STREAM_HOST="wrath.example", WU_RELAY_LISTING=f"http://127.0.0.1:{RELAY_PORT}/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.example", WU_RELAY_WS="wss://relay.example")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

LIVE, OFF = "abcdefghijklmnop", "qrstuvwxyz234567"


def rec(rid, name, live):
    return {"name": name, "official": False, "state": "live" if live else "offline", "profile": {"ruleset": "dalaran"},
            "community": {"realmId": rid, "lastHeartbeat": {"players": 3, "bots": 0}}}


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        body = json.dumps({"realms": [rec(LIVE, "Frost Haven", True), rec(OFF, "Quiet Corner", False)]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = ('<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
                f'xmlns:ns1="urn:AC"><SOAP-ENV:Body><ns1:executeCommandResponse><result>{escape("ovstream ok")}</result>'
                '</ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class Realm(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        doc = {"/api/me": {"display_name": "Tester"}, "/api/play": {"user": "WR000123", "pass": "Pa55word1234abcd"}}[self.path]
        body = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


for port, h in ((SOAP_PORT, Soap), (REALM_PORT, Realm), (RELAY_PORT, Relay), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, cookie="", ip="10.0.0.9"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    hd = {"X-Forwarded-For": ip}
    if cookie:
        hd["Cookie"] = cookie
    c.request("GET", path, headers=hd)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


def session_env(play_path):
    """Sign in via play_path, follow the gate, return (landing, env dict, env.js text)."""
    st, h, _ = get(play_path, cookie="wr_session=good")
    gate = h.get("location", "")
    assert st == 302 and "/__gate?code=" in gate, (st, gate)
    q = urllib.parse.urlsplit(gate).query
    st, h, _ = get("/__gate?" + q)
    land = h.get("location", "")
    sid = h.get("set-cookie", "").split(";")[0].split("=", 1)[1]
    st, h, b = get("/__env.js", cookie=f"wu_play={sid}")
    txt = b.decode()
    env = json.loads(txt.split("\n")[0][len("window.__wenilla_env = "):].rstrip(";"))
    return gate, land, env, txt


# --- /wrath?go=r:<live realm> -> straight in, carried to the gate and the landing page
st, h, _ = get(f"/wrath?go=r:{LIVE}", cookie="wr_session=good")
check("/wrath?go=r: goes straight in with the hop", st == 302 and h["location"] == f"/wrath/play?mini=mini&go=r:{LIVE}", h.get("location"))

gate, land, env, txt = session_env(f"/wrath/play?mini=mini&go=r:{LIVE}")
check("gate keeps the hop", gate.endswith(f"&go=r:{LIVE}"), gate)
check("lands on the client with the hop", land == f"/?go=r:{LIVE}", land)
check("hop env: realm and its name", env.get("hop") == LIVE and env.get("hop_name") == "Frost Haven", env)
check("hop env: the relay bridge for that realm", env.get("hop_ws") == f"wss://relay.example/ws/{LIVE}")
check("hop env: the realm's join page in hop mode", env.get("hop_join") == f"https://relay.example/join/{LIVE}?hop=1")
check("hop env: the client's realmlist is the relay", env.get("host") == "relay.example")
check("hop env: the way home", env.get("home") == "https://play.openvanilla.app")
check("hop env: NO Wrath login (the realm has its own accounts)", "user" not in env and "pass" not in env
      and "Pa55word" not in txt and "WR000123" not in txt)
check("hop env: still the streamed slice and Forever UI", env.get("slice") == "mini" and env.get("foreverui") == "1")

# --- own game files hop: the go is carried through /wrath/play?mode=own too
gate, land, env, txt = session_env(f"/wrath/play?mode=own&go=r:{LIVE}")
check("own files: gate keeps the hop", gate.endswith(f"&go=r:{LIVE}"), gate)
check("own files: lands with ownfiles and the hop", land == f"/?ownfiles=1&go=r:{LIVE}", land)
check("own files: hop env with mode own, no slice, no login", env.get("hop") == LIVE and env.get("mode") == "own"
      and "slice" not in env and "pass" not in env)

# --- no hop: offline realm, unknown realm, the official realm, a bad id -> a normal Wrath session
for go, why in ((f"r:{OFF}", "offline realm"), ("r:" + "a" * 16, "unknown realm"), ("r:wrath", "the official realm"),
                ("r:../../x", "bad id"), ("q:258", "another kind")):
    _, _, env, _ = session_env("/wrath/play?mini=mini&go=" + urllib.parse.quote(go, safe=":"))
    check(f"no hop for {why}: Wrath login, Wrath host", "hop" not in env and env.get("user") == "WR000123"
          and env.get("host") == "play.openvanilla.app", env)

# --- Back to Wrath: plain /wrath/play gives a session without the hop
_, land, env, _ = session_env("/wrath/play?mini=mini")
check("back to Wrath: no hop, the Wrath login", land == "/" and "hop" not in env and env.get("user") == "WR000123")

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
