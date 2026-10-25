"""Local test of the realm list (GET /wrath/realms): the official realm first, community realms from a fake
Beacons relay listing, escaping, the cache, and a slow or dead relay never slowing the page.

    python3 -I stream/tests/test_realms.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, RELAY_PORT, PAGE_PORT = 17881, 18093, 18094
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL="http://127.0.0.1:9", WU_STREAM="0", STREAM_HOST="wrath.example",
                  WU_RELAY_LISTING=f"http://127.0.0.1:{RELAY_PORT}/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.example")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

RID_A, RID_B, RID_C = "abcdefghijklmnop", "qrstuvwxyz234567", "aaaaaaaaaaaaaaaa"


def rec(rid, name, ruleset="dalaran", live=True, players=3, bots=0, **kw):
    r = {"schema": 1, "slug": "c-" + rid, "name": name, "official": False, "state": "live" if live else "offline",
         "tagline": kw.get("tagline", ""), "type": "Fun", "profile": {"ruleset": ruleset},
         "community": {"realmId": rid, "claimed": kw.get("claimed", False),
                       "lastHeartbeat": {"online": live, "players": players, "bots": bots}}}
    r.update(kw.get("extra", {}))
    return r


relay = {"mode": "ok", "hits": 0, "doc": {"schema": 1, "kind": "community", "realms": [
    rec(RID_B, "Quiet Corner", ruleset="main", live=False, players=0),
    rec(RID_A, "Frost <b>Haven</b>", players=7, bots=2, tagline="Duels at the fountain & <script>x</script>",
        extra={"rules": ["Be kind <3", "No ganking", 5]}),
    rec(RID_C, "Fake Official", extra={"official": True}),          # only the official realm is official
    {"name": "no id", "community": {"realmId": "../../etc"}},
    "junk",
]}}


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        relay["hits"] += 1
        if relay["mode"] == "slow":
            time.sleep(8)
        if relay["mode"] == "error":
            self.send_response(502); self.send_header("Content-Length", "0"); self.end_headers(); return
        body = json.dumps(relay["doc"]).encode() if relay["mode"] != "garbage" else b"<html>nope"
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        text = "Connected players: 12 (peak: 20).\nCharacters in world: 40 (peak: 50, lifetime: 9).\nServer uptime: 1 hour(s)"
        body = ('<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
                f'xmlns:ns1="urn:AC"><SOAP-ENV:Body><ns1:executeCommandResponse><result>{escape(text)}</result>'
                '</ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


servers = {}
for port, h in ((SOAP_PORT, Soap), (RELAY_PORT, Relay), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    srv.daemon_threads = True
    servers[port] = srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, ip="10.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
    t = time.monotonic()
    c.request("GET", path, headers={"X-Forwarded-For": ip})
    r = c.getresponse()
    body = r.read()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, body, time.monotonic() - t


def reset_cache():
    while wp._listing_busy.locked():   # a refresh thread from the previous case still running
        time.sleep(0.05)
    with wp._listing_lock:
        wp._listing.update(at=-1e9, ok=False, realms=[], fetched=False)


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


# --- the list
st, h, b, dt = get("/wrath/realms")
page = b.decode()
check("realms: 200, public (no sign-in needed)", st == 200)
check("realms: no script on the page", "<script" not in page.split("</style>", 1)[-1].replace("&lt;script&gt;", ""))
check("realms: CSP still strict", "script-src 'none'" in h.get("content-security-policy", ""))
i_off = page.find("<h2>WrathUnleashed</h2>")
i_a = page.find("Frost &lt;b&gt;Haven&lt;/b&gt;")
i_b = page.find("Quiet Corner")
check("official WrathUnleashed listed first", 0 <= i_off < i_a < i_b, (i_off, i_a, i_b))
check("official: players from the realm's own status", "12 playing" in page[i_off:i_a])
check("official: Play link to /wrath", 'href="/wrath">Play</a>' in page[i_off:i_a])
check("community: name escaped", "Frost &lt;b&gt;Haven&lt;/b&gt;" in page and "<b>Haven</b>" not in page)
check("community: tagline escaped", "Duels at the fountain &amp; &lt;script&gt;x&lt;/script&gt;" in page)
check("community: ruleset shown", "Dalaran hangout" in page[i_a:i_b])
check("community: players and bots", "7 playing · 2 bots" in page[i_a:i_b])
check("community: Join link /join/<id>", f'href="https://relay.example/join/{RID_A}"' in page)
check("community: offline realm after the live one, marked offline", "offline" in page[i_b:] and f"/join/{RID_B}" in page)
check("community: a record claiming to be official is dropped", "Fake Official" not in page and RID_C not in page)
check("community: records without a valid realm id dropped", "no id" not in page and "etc" not in page)
check("community: unclaimed tag", "unclaimed" in page[i_a:i_b])
check("community: house rules shown, escaped", "<li>Be kind &lt;3</li><li>No ganking</li></ol>" in page[i_a:i_b])

# --- cached: a second request does not ask the relay again
hits = relay["hits"]
get("/wrath/realms")
check("cached: no second fetch within the TTL", relay["hits"] == hits, relay["hits"])

# --- the relay is slow: the page answers within ~LISTING_WAIT, and from then on at once
reset_cache()
relay["mode"] = "slow"
st, h, b, dt = get("/wrath/realms")
check("slow relay: page answers within 3 s", st == 200 and dt < 3.5, f"{dt:.2f}s")
check("slow relay: says the list isn't reachable", b"isn&#x27;t reachable right now" in b or b"isn't reachable right now" in b)
check("slow relay: official realm still listed", b"<h2>WrathUnleashed</h2>" in b)
st, h, b, dt = get("/wrath/realms")
check("slow relay, next request: no waiting at all", dt < 0.5, f"{dt:.2f}s")

# --- the relay is down (nothing listening): fast
reset_cache()
servers[RELAY_PORT].shutdown(); servers[RELAY_PORT].server_close()
relay["mode"] = "ok"
st, h, b, dt = get("/wrath/realms")
check("dead relay: page still 200 and fast", st == 200 and dt < 3.0, f"{dt:.2f}s")
check("dead relay: no community realms, official first", b"<h2>WrathUnleashed</h2>" in b and b"Frost" not in b)

# --- the account page (the play page) links to the list and never asks the relay itself
hits = relay["hits"]
st, h, b, dt = get("/wrath")
check("play page answers while the relay is down", st == 200 and dt < 1.0, f"{dt:.2f}s")
check("sign-in page links to /wrath/realms", b'href="/wrath/realms"' in wp.signed_out_page())
check("play page does not fetch the listing", relay["hits"] == hits)
check("account page links to /wrath/realms", 'href="/wrath/realms"' in wp.account_page("T", "WR1", "pw", "n").decode())

# --- a broken answer keeps the last good list
srv = ThreadingHTTPServer(("127.0.0.1", RELAY_PORT), Relay); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
reset_cache()
get("/wrath/realms")
with wp._listing_lock:
    wp._listing["at"] = -1e9          # expire it
relay["mode"] = "garbage"
get("/wrath/realms")                  # starts a background refresh that fails
reset_cache_wait = time.monotonic()
while wp._listing_busy.locked() and time.monotonic() - reset_cache_wait < 5:
    time.sleep(0.05)
st, h, b, dt = get("/wrath/realms")
check("broken answer: last good list kept", b"Frost" in b, b[-300:])
check("broken answer: marked as maybe out of date", b"out of date" in b)

# --- empty listing
relay["mode"] = "ok"; relay["doc"] = {"schema": 1, "realms": []}
reset_cache()
st, h, b, dt = get("/wrath/realms")
check("empty listing: invites people to host", b"No community realms are open right now" in b)

# --- where the list comes from: env, else the file the relay step writes, else the public name
import tempfile
fd, urlfile = tempfile.mkstemp()
os.close(fd)
wp.RELAY_LISTING, wp.RELAY_LISTING_FILE = "", urlfile
with open(urlfile, "w") as f:
    f.write("http://172.18.0.1:8099/api/listing/realms.json\n")
check("listing url: from relay-listing.url", wp.listing_url() == "http://172.18.0.1:8099/api/listing/realms.json")
with open(urlfile, "w") as f:
    f.write("file:///etc/passwd\n")
check("listing url: a bad file is ignored", wp.listing_url() == wp.RELAY_LISTING_DEFAULT)
os.remove(urlfile)
check("listing url: no file -> https://relay.openvanilla.app", wp.listing_url() == "https://relay.openvanilla.app/api/listing/realms.json")

# --- the inside address stops answering: the public one is read instead
fd, urlfile = tempfile.mkstemp()
os.close(fd)
with open(urlfile, "w") as f:
    f.write("http://172.18.0.1:8099/api/listing/realms.json\n")
wp.RELAY_LISTING_FILE = urlfile
asked = []
good = json.dumps({"realms": [{"name": "Dalaran Hangout", "state": "live",
                               "community": {"realmId": "qt6yi563z2gbxlhx", "lastHeartbeat": {"players": 2}}}]}).encode()
real_read = wp._read_listing


def fake_read(url):
    asked.append(url)
    if "172.18.0.1" in url:
        raise OSError("connection refused")
    return good


wp._read_listing = fake_read
got = wp.fetch_listing()
check("listing: inside address down -> public address read", asked == ["http://172.18.0.1:8099/api/listing/realms.json", wp.RELAY_LISTING_DEFAULT])
check("listing: the public answer is used", [r["name"] for r in got] == ["Dalaran Hangout"] and got[0]["live"])
asked.clear()
wp.RELAY_LISTING_FILE = urlfile + ".gone"
try:
    wp._read_listing = lambda url: (asked.append(url), (_ for _ in ()).throw(OSError("down")))[1]
    wp.fetch_listing()
    check("listing: public address down too -> error", False)
except OSError:
    check("listing: public address down too -> error, asked once", asked == [wp.RELAY_LISTING_DEFAULT])
wp._read_listing = real_read
os.remove(urlfile)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
