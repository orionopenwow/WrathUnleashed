"""Local test of a Leyline realm hop through the portal: /wrath/play (stream and own files) with ?go=r:<id>,
the gate, and /__env.js for that session (the relay's addresses for the realm, never the Wrath login), against
a fake SOAP server, a fake Open Vanilla realm service and a fake relay listing.

    python3 -I stream/tests/test_hop.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, RELAY_PORT, PAGE_PORT = 17883, 18095, 18096, 18097
slices = tempfile.mkdtemp()
with open(os.path.join(slices, "mini.json"), "w") as f:
    json.dump({"slice": "mini", "maxTier": 4, "title": "Mini"}, f)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_SLICE_DIR=slices, WU_STREAM="1", WU_OWNFILES="1",
                  STREAM_HOST="wrath.example", WU_RELAY_LISTING=f"http://127.0.0.1:{RELAY_PORT}/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.example", WU_RELAY_WS="wss://relay.example",
                  WU_HANGOUT_REALM="hangouthangout22", WU_LEYLINE_DIR=tempfile.mkdtemp())
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

LIVE, OFF, HANG = "abcdefghijklmnop", "qrstuvwxyz234567", "hangouthangout22"
SOAP_CMDS = []


def rec(rid, name, live):
    return {"name": name, "official": False, "state": "live" if live else "offline", "profile": {"ruleset": "dalaran"},
            "community": {"realmId": rid, "lastHeartbeat": {"players": 3, "bots": 0}}}


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        hang = rec(HANG, "Dalaran Hangout", True)
        hang["community"]["lastHeartbeat"]["players"] = 1
        body = json.dumps({"realms": [rec(LIVE, "Frost Haven", True), rec(OFF, "Quiet Corner", False), hang]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
        m = re.search(r"<command>(.*?)</command>", raw, re.S)
        SOAP_CMDS.append(m.group(1) if m else raw)
        body = ('<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
                f'xmlns:ns1="urn:AC"><SOAP-ENV:Body><ns1:executeCommandResponse><result>{escape("ovstream ok ovgo ok")}</result>'
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

# --- the Dalaran Hangout: this realm through the relay. The player's own Wrath login (no join page, no second
# account), the relay bridge for the sockets, and the arrival in Dalaran (the go intent on the realm).
def gos():
    return [c for c in SOAP_CMDS if c.startswith("ovgo ")]


wp.modes._recent.clear()
SOAP_CMDS.clear()
gate, land, env, txt = session_env(f"/wrath/play?mini=mini&go=r:{HANG}")
check("hangout: a hop session through the relay", env.get("hop") == HANG and env.get("hop_ws") == f"wss://relay.example/ws/{HANG}", env)
check("hangout: the player's own Wrath login, marked as such", env.get("hop_home") == "1" and env.get("user") == "WR000123"
      and env.get("pass") == "Pa55word1234abcd", env)
check("hangout: lands in Dalaran (ovgo h:dalaran for the account)", gos() == ["ovgo set WR000123 h:dalaran"], gos())
check("hangout: no account made or reset beyond the usual", not [c for c in SOAP_CMDS if "account create" in c.lower()
                                                               and "WR000123" not in c], SOAP_CMDS)
wp.modes._recent.clear()
SOAP_CMDS.clear()
_, _, env, _ = session_env(f"/wrath/play?mode=own&go=r:{HANG}")
check("hangout with own files: the Wrath login too", env.get("hop_home") == "1" and env.get("mode") == "own" and env.get("user") == "WR000123")
check("hangout with own files: Dalaran", "ovgo set WR000123 h:dalaran" in gos(), gos())
# another Beacon: never the Wrath login, never a Dalaran intent
wp.modes._recent.clear()
SOAP_CMDS.clear()
_, _, env, txt = session_env(f"/wrath/play?mini=mini&go=r:{LIVE}")
check("a community Beacon: no hop_home, no Wrath login", "hop_home" not in env and "pass" not in env and "Pa55word" not in txt)
check("a community Beacon: no go intent", gos() == [], gos())
# Back to Wrath (wrath-page.js hopUrl('wrath')): /wrath?go=h:dalaran -> straight in, Dalaran on arrival
wp.modes._recent.clear()
SOAP_CMDS.clear()
st, h, _ = get("/wrath?go=h:dalaran", cookie="wr_session=good")
check("back to Wrath: straight in with the Dalaran go", st == 302 and h["location"] == "/wrath/play?mini=mini&go=h:dalaran", h.get("location"))
_, land, env, _ = session_env("/wrath/play?mini=mini&go=h:dalaran")
check("back to Wrath: a plain Wrath session", "hop" not in env and env.get("user") == "WR000123" and env.get("host") == "play.openvanilla.app")
check("back to Wrath: lands in Dalaran", "ovgo set WR000123 h:dalaran" in gos(), gos())
# the hangout first on the realm list, with its own button (straight to Dalaran, no join page)
realms, _ok = wp.community_realms()
check("hangout first in the community list", [r["id"] for r in realms][:1] == [HANG] and realms[0]["hangout"], [r["id"] for r in realms])
page = wp.realms_page().decode()
i_h, i_l = page.find("<h2>WrathUnleashed</h2>"), page.find("Frost Haven")   # the hangout's record is our own card
check("realms page: the hangout before the other Beacons", 0 < i_h < i_l, (i_h, i_l))
check("realms page: Play in Dalaran, run by Leyline", 'href="/wrath?go=h:dalaran">Play in Dalaran</a>' in page
      and "Run by Leyline" in page and f"/join/{HANG}" not in page)
# no hangout configured (unset, or junk): nothing special
saved = wp.HANGOUT_REALM
wp.HANGOUT_REALM = "not-an-id"
check("junk hangout id: none", wp.hangout_id() is None)
wp.HANGOUT_REALM = saved

# --- Hero Key sign-in on Beacons (docs/HERO-KEY-SSO.md): the herokey_sso flag, OFF by default
_, _, env, txt = session_env(f"/wrath/play?mini=mini&go=r:{LIVE}")
check("herokey off (default): no hop_sso, no login, the join page flow", "hop_sso" not in env and "user" not in env
      and "pass" not in env and env.get("hop_join"))
check("herokey off: no public key published", get("/wrath/leyline/herokey.json")[0] == 404)
check("herokey off: the launcher's call says it isn't on", wp.herokey_issue_api("WR000123", LIVE, "launcher")[0] == 404)
check("herokey off: no key files made", not os.listdir(wp.HEROKEY_DIR) or "herokey-site.key" not in os.listdir(wp.HEROKEY_DIR))
wp.leyline_net.write_flags(None, {"herokey_sso": True}, by="test")
_, _, env, txt = session_env(f"/wrath/play?mini=mini&go=r:{LIVE}")
sso = env.get("hop_sso") or {}
a = sso.get("assertion") or {}
check("herokey on: the hop carries a signed assertion for that realm", a.get("aud") == LIVE and len(sso.get("sig", "")) == 128
      and sso.get("redeem") == f"https://relay.example/api/realms/{LIVE}/herokey", sso)
check("herokey on: a one-time login for the realm's own account (HK + pseudonym)", re.match(r"^HK[A-Z2-7]{14}$", env.get("user", ""))
      and len(env.get("pass", "")) == 16 and env["user"] == "HK" + a["sub"][:14].upper(), env.get("user"))
check("herokey on: never the Wrath login or the global account id", "Pa55word" not in txt and "WR000123" not in txt.upper())
pub = json.loads(get("/wrath/leyline/herokey.json")[2])
check("herokey on: the public key is published, and only it", pub.get("ctx") == "leyline-herokey-sso-v1"
      and len(pub["keys"]) == 1 and pub["keys"][0]["kid"] == a.get("kid") and wp.herokey_keys.secret().hex() not in json.dumps(pub))
check("herokey on: the key files are 0600", oct(os.stat(os.path.join(wp.HEROKEY_DIR, "herokey-site.key")).st_mode & 0o777) == "0o600"
      and oct(os.stat(os.path.join(wp.HEROKEY_DIR, "herokey-pepper.key")).st_mode & 0o777) == "0o600")
# the realm side accepts it (the host kit's checker, the key pinned)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hosting", "kit", "tools"))
from wunet import herokey as kit_hk   # noqa: E402
pinned = {p["kid"]: bytes.fromhex(p["pub"]) for p in pub["keys"]}
claims, why = kit_hk.check(a, sso["sig"], LIVE, pinned, kit_hk.ReplayCache())
check("herokey on: the realm's agent verifies it", why is None and kit_hk.account_name(claims["sub"]) == env["user"], why)
_, _, env2, _ = session_env(f"/wrath/play?mini=mini&go=r:{LIVE}")
check("herokey on: the same pseudonym next time, a new one-time password", env2["user"] == env["user"] and env2["pass"] != env["pass"]
      and env2["hop_sso"]["assertion"]["nonce"] != a["nonce"])
gate, land, env3, _ = session_env(f"/wrath/play?mini=mini&go=r:{HANG}")
check("herokey on: the Dalaran Hangout still uses the Wrath login", "hop_sso" not in env3 and env3.get("user") == "WR000123")
_, _, env4, _ = session_env("/wrath/play?mini=mini")
check("herokey on: a plain Wrath session is unchanged", "hop_sso" not in env4 and env4.get("user") == "WR000123")
st, doc = wp.herokey_issue_api("WR000123", LIVE, "launcher")
check("launcher call: assertion, login, redeem; longer login window", st == 200 and doc["assertion"]["login_ttl"] == 600
      and doc["login"]["user"] == env["user"] and doc["redeem"].endswith(f"/api/realms/{LIVE}/herokey"), (st, doc.get("error")))
check("launcher call: offline realm / bad id / the hangout refused",
      [wp.herokey_issue_api("WR000123", r, "launcher")[0] for r in (OFF, "../x", HANG)] == [404, 400, 400])
for _ in range(70):
    wp.herokey_issue("WR000555", LIVE, 120)
check("rate limit: 60 assertions an hour per account", wp.herokey_issue("WR000555", LIVE, 120) is None
      and wp.herokey_issue("WR000556", LIVE, 120) is not None)
wp.leyline_net.write_flags(None, {"herokey_sso": False}, by="test")
_, _, env5, _ = session_env(f"/wrath/play?mini=mini&go=r:{LIVE}")
check("herokey back off: the old hop at once", "hop_sso" not in env5 and "user" not in env5)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
