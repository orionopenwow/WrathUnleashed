"""Leyline friends and messages (stream/social.py) through the real portal (stream/wrath_portal.py) and against
the real realm script (realm/custom/lua_scripts/ov_social.lua, run by lua5.1 under a fake mod-ale:
tests/social_realm_driver.lua). Covers sign-in (cookie + CSRF, the launcher's device code and token, revoke),
requests, presence (game, launcher, appear offline), messages both ways, unread at login, blocks, rate limits,
retention, the report queue, bots, realm restarts and that message bodies are never logged.

    python3 -I stream/tests/test_social.py stream/wrath_portal.py
"""
import http.client, importlib.util, io, json, logging, os, re, subprocess, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PORTAL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stream", "wrath_portal.py")
LUA = os.path.join(ROOT, "realm", "custom", "lua_scripts", "ov_social.lua")
TMP = tempfile.mkdtemp(prefix="wu-social-")
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    fails += 0 if cond else 1


# ---------------------------------------------------------------- the website (sign-in) and the realm
ACCOUNTS = {"alice": ("Alice W", "WR000001"), "bob": ("Bob", "WR000002"), "carol": ("Carol", "WR000003"),
            "dave": ("Dave", "WR000004")}


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
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


class Realm:
    """ov_social.lua in lua5.1, spoken to line by line."""
    def __init__(self, start=2000000):
        self.p = subprocess.Popen(["lua5.1", os.path.join(HERE, "social_realm_driver.lua"), LUA, str(start)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lock = threading.Lock()
        self.up = True
        for i, name in ((1, "WR000001"), (2, "WR000002"), (3, "WR000003"), (4, "WR000004"), (9, "RNDBOT0009")):
            self.do(f"USER {i} {name}")

    def do(self, line):
        with self.lock:
            self.p.stdin.write(line + "\n"); self.p.stdin.flush()
            out = []
            while True:
                l = self.p.stdout.readline()
                if not l or l.rstrip("\n") == "END":
                    return out
                out.append(l.rstrip("\n"))

    def soap(self, cmd):
        if not self.up:
            raise OSError("realm down")
        sent.append(cmd)
        return "\n".join(self.do("SOAP " + cmd))

    def msgs(self, acc):
        return self.do(f"MSGS {acc}")


sent = []
realm = Realm()
SITE = serve(Site)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL=f"http://127.0.0.1:{SITE}",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_PORTAL_DATA=TMP, WU_HOST_DIR=os.path.join(TMP, "hosted"),
                  WU_RELAY_LISTING="http://127.0.0.1:9/none", WU_SOCIAL_MSG_PER_MIN="20")
spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
check("portal loads social.py", wp.social is not None)
wp.ac_soap = realm.soap
S = wp.social.setup(start_thread=False)
check("the store opens in WU_PORTAL_DATA", S is not None and os.path.isfile(os.path.join(TMP, "social.sqlite3")))
logbuf = io.StringIO()
lh = logging.StreamHandler(logbuf); lh.setLevel(logging.DEBUG)
logging.getLogger().addHandler(lh); logging.getLogger().setLevel(logging.DEBUG)
PAGE = serve(wp.PageHandler)


def call(method, path, body=None, sess=None, token=None, headers=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", PAGE, timeout=40)
    h = dict(headers or {})
    if sess:
        h["Cookie"] = f"wr_session={sess}"
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h["Content-Type"] = "application/json" if raw is None else "application/x-www-form-urlencoded"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    b = r.read()
    try:
        doc = json.loads(b)
    except ValueError:
        doc = b.decode("utf-8", "replace")
    return r.status, doc, r


API = "/wrath/api/social/"
csrf = {}


def me(sess):
    st, doc, _ = call("GET", API + "me", sess=sess)
    csrf[sess] = doc.get("csrf")
    return st, doc


def post(sess, sub, body, **kw):
    return call("POST", API + sub, body, sess=sess, headers={"X-Leyline-CSRF": csrf.get(sess, "")}, **kw)[:2]


def state(sess=None, token=None):
    return call("GET", API + "state", sess=sess, token=token)[1]


def friend(st, name):
    for f in st["friends"]:
        if f["name"] == name:
            return f
    return None


# ---------------------------------------------------------------- sign-in and CSRF
st, doc, _ = call("GET", API + "me")
check("signed out: 401", st == 401)
st, doc = me("alice")
check("signed in: me with a csrf token", st == 200 and doc["me"]["name"] == "AliceW" and re.fullmatch(r"\d{4}", doc["me"]["tag"])
      and len(doc.get("csrf", "")) == 32, doc)
for s in ("bob", "carol", "dave"):
    me(s)
st, doc, _ = call("POST", API + "profile", {"name": "Alice"}, sess="alice")
check("POST without the csrf header: 403", st == 403)
st, doc, _ = call("POST", API + "profile", {"name": "Alice"}, sess="alice",
                  headers={"X-Leyline-CSRF": csrf["alice"], "Sec-Fetch-Site": "cross-site"})
check("cross-site POST: 403", st == 403)
st, doc, _ = call("POST", API + "profile", {"name": "Alice"}, sess="alice",
                  headers={"X-Leyline-CSRF": csrf["alice"], "Origin": "https://evil.example"})
check("POST from another origin: 403", st == 403)
st, doc = post("alice", "profile", {"name": "Alice"})
check("profile: name set", st == 200 and doc["me"]["name"] == "Alice")
st, doc = post("alice", "profile", {"name": "Fuuuck"})
check("profile: the word filter refuses a name", st == 400)
st, doc = post("alice", "profile", {"name": "Warcraftfan"})
check("profile: brand names refused", st == 400)
st, doc = post("alice", "profile", {"name": "a b"})
check("profile: spaces refused", st == 400)
st, doc = post("alice", "profile", {"main": "Alicia"})
check("profile: a main must be a character seen on the realm", st == 400)
alice_tag = state("alice")["me"]["tag"]
bob_tag = state("bob")["me"]["tag"]
st, doc, r = call("POST", API + "profile", raw=b"{nope", sess="alice", headers={"X-Leyline-CSRF": csrf["alice"]})
check("bad JSON: 400", st == 400)

# ---------------------------------------------------------------- requests
st, doc = post("alice", "request", {"to": "Nobody#0000"})
check("request: unknown player 404", st == 404)
st, doc = post("alice", "request", {"to": f"Bob#{bob_tag}"})
check("request sent", st == 200 and doc["text"] == "Request sent.")
s = state("bob")
check("bob sees the request", len(s["incoming"]) == 1 and s["incoming"][0]["name"] == "Alice")
s = state("alice")
check("alice sees it waiting, no presence", s["outgoing"][0]["name"] == f"Bob#{bob_tag}" and not s["friends"])
alice_pid = state("bob")["incoming"][0]["pid"]
st, doc = post("bob", "accept", {"pid": alice_pid})
check("accepted", st == 200 and friend(state("alice"), "Bob") and friend(state("bob"), "Alice"))
check("presence: offline until seen", friend(state("alice"), "Bob")["status"] == "offline")
st, doc = post("carol", "request", {"to": "Alice"})
check("request by a unique name", st == 200)
carol_pid = state("alice")["incoming"][0]["pid"]

# ---------------------------------------------------------------- the realm: presence, messages both ways
S.tick()
check("first pull is a full one", sent and sent[0].startswith("ovsocial pull 0 0 1"))
realm.do("LOGIN 2 22 Bobbert")
realm.do("LOGIN 9 99 Botty")
S.tick()
f = friend(state("alice"), "Bob")
check("bob in game: realm and character", f["status"] == "game" and f["char"] == "Bobbert" and f["realm"] == "WrathUnleashed", f)
check("bots never appear", "RNDBOT0009" not in S.ingame and not S.profile("RNDBOT0009"))
st, doc = post("alice", "profile", {"main": "Alicia"})
check("main still refused (alice never played Alicia)", st == 400)
SECRET = "the-secret-body-7731"
st, doc = post("alice", "send", {"to": friend(state("alice"), "Bob")["pid"], "text": f"hi bob {SECRET}"})
check("alice sends from the web", st == 200 and doc["message"]["mine"] and doc["message"]["via"] == "web")
S.tick()
lines = realm.msgs(2)
check("bob sees it in game, whisper-style with [Leyline]",
      any(l == f"|cff66ccff[Leyline]|r |cffff80ff[Alice] whispers: hi bob {SECRET}|r" for l in lines), lines)
check("bob's panel gets it (M:) and his list (B/R/E)", any(l.startswith("@M:Alice:hi bob") for l in lines))
check("a message shown in game counts as read", friend(state("bob"), "Alice")["unread"] == 0)
realm.do("CMD 2 .lm Alice hey alice, shit happens")
S.tick()
th = call("GET", API + "thread?with=" + friend(state("alice"), "Bob")["pid"], sess="alice")[1]["messages"]
check("bob's .lm reaches alice, stamped as bob, via game", th[-1]["mine"] is False and th[-1]["via"] == "game"
      and th[-1]["text"].startswith("hey alice"), th)
check("the word filter masks words in messages", "****" in th[-1]["text"] and "shit" not in th[-1]["text"])
check("unread counted for alice", friend(state("alice"), "Bob")["unread"] == 1)
post("alice", "read", {"with": friend(state("alice"), "Bob")["pid"]})
check("read clears unread", friend(state("alice"), "Bob")["unread"] == 0)
realm.do("CMD 2 .lm Nobody hello")
S.tick()
check("in game: unknown friend explained", any("no Leyline friend called Nobody" in l for l in realm.msgs(2)))
realm.do("ADDON 2 F:add:Carol")
S.tick()
check("in game .lf add (addon F:) makes a request", any(o["name"] == "Carol" for o in state("bob")["outgoing"]))
realm.do("CMD 2 .lf")
S.tick()
lines = realm.msgs(2)
check(".lf lists friends with presence", any("Alice#" + alice_tag + ": offline" in l for l in lines), lines)

# a client can't claim to be someone else: the realm stamps the account
realm.do("LOGIN 3 33 Carolyn")
realm.do("ADDON 3 S:Alice:i am bob")
S.tick()
th = call("GET", API + "thread?with=" + friend(state("alice"), "Bob")["pid"], sess="alice")[1]["messages"]
check("a spoofed sender goes nowhere (carol isn't alice's friend yet)", not any("i am bob" in m["text"] for m in th))
check("carol is told why", any("no Leyline friend called Alice" in l for l in realm.msgs(3)))

# ---------------------------------------------------------------- the launcher: device code, token, presence
st, dev, _ = call("POST", API + "device/start", {})
check("device/start", st == 200 and re.fullmatch(r"[A-Z]{4}-[A-Z]{4}", dev["user_code"])
      and dev["verify_url"] == f"https://play.openvanilla.app/wrath/link?code={dev['user_code']}", dev)
st, doc, _ = call("POST", API + "device/poll", {"device_code": dev["device_code"]})
check("poll: pending", doc["status"] == "pending")
st, page, r = call("GET", "/wrath/link?code=" + dev["user_code"])
check("link page signed out: to the website's sign-in and back", st == 302
      and r.getheader("Location") == "/login?next=" + urllib.parse.quote("/wrath/link?code=" + dev["user_code"], safe=""))
st, page, _ = call("GET", "/wrath/link?code=" + dev["user_code"], sess="alice")
check("link page shows the code and Approve", st == 200 and dev["user_code"] in page and "Approve" in page)
tok = re.search(r'name="code" value="([A-Z]+)"><input type="hidden" name="t" value="([0-9a-f]+)"><button class="ly-btn" name="do" value="approve"', page)
check("the form carries a token", tok is not None)
form = urllib.parse.urlencode({"code": tok.group(1), "t": "0" * 32, "do": "approve"}).encode()
st, page, _ = call("POST", "/wrath/link", raw=form, sess="alice")
check("a wrong form token is refused", "timed out" in page)
form = urllib.parse.urlencode({"code": tok.group(1), "t": tok.group(2), "do": "approve"}).encode()
st, page, _ = call("POST", "/wrath/link", raw=form, sess="alice", headers={"Origin": "https://evil.example"})
check("approve from another site refused", st == 403)
st, page, _ = call("POST", "/wrath/link", raw=form, sess="alice")
check("approved", st == 200 and "go back to the launcher" in page and "Linked launchers" in page)
time.sleep(DEV_WAIT := 3.2)
st, doc, _ = call("POST", API + "device/poll", {"device_code": dev["device_code"]})
check("poll: the token, once", doc.get("status") == "ok" and re.fullmatch(r"[A-Za-z0-9_-]{43}", doc.get("token", "")), doc)
TOKEN = doc.get("token")
time.sleep(DEV_WAIT)
st, doc, _ = call("POST", API + "device/poll", {"device_code": dev["device_code"]})
check("the token is handed over only once", doc["status"] == "expired")
check("only a hash of the token is stored", TOKEN not in open(os.path.join(TMP, "social.sqlite3"), "rb").read().decode("latin-1"))
s = state(token=TOKEN)
check("the launcher reads state with its token", s["me"]["name"] == "Alice")
check("alice online in the launcher for bob", friend(state("bob"), "Alice")["status"] == "launcher")
st, doc, _ = call("POST", API + "send", {"to": friend(s, "Bob")["pid"], "text": "from the launcher"}, token=TOKEN)
check("the launcher sends with its token (no csrf needed)", st == 200 and doc["message"]["via"] == "launcher")
st, doc, _ = call("GET", API + "state", token="x" * 43)
check("a wrong token: 401", st == 401)
# Hero Key sign-in to a Beacon (docs/HERO-KEY-SSO.md): the herokey_sso flag is off by default
st, doc, _ = call("POST", API + "herokey", {"realm": "abcdefghijk2345a"}, token=TOKEN)
check("herokey with the flag off: 404, nothing issued", st == 404 and "isn't on" in doc.get("error", ""), doc)
st, doc, _ = call("POST", API + "herokey", {"realm": "abcdefghijk2345a"}, token="x" * 43)
check("herokey with a wrong token: 401", st == 401)
_hk_seen = []
_hk_saved = wp.herokey_issue_api
wp.herokey_issue_api = lambda acct, realm, via: (_hk_seen.append((acct, realm, via)), (200, {"ok": True}))[1]
st, doc, _ = call("POST", API + "herokey", {"realm": "abcdefghijk2345a", "acct": "WR000002"}, token=TOKEN)
check("herokey: the launcher's own account, its realm, via launcher", st == 200 and _hk_seen == [("WR000001", "abcdefghijk2345a", "launcher")], _hk_seen)
wp.herokey_issue_api = _hk_saved

# long poll: wakes on a change
v = state(token=TOKEN)["v"]
res = {}
t0 = time.time()
th_ = threading.Thread(target=lambda: res.update(r=call("GET", API + f"events?since={v}", token=TOKEN)[1]))
th_.start()
time.sleep(0.5)
realm.do("CMD 2 .lm Alice ping")
S.tick()
th_.join(10)
check("events: the long poll wakes on a new message", res.get("r", {}).get("friends") is not None and time.time() - t0 < 8)

# appear offline
st, doc = post("alice", "profile", {"offline": True})
check("appear offline: bob sees alice offline", st == 200 and friend(state("bob"), "Alice")["status"] == "offline")
post("alice", "profile", {"offline": False})
realm.do("CMD 2 .lf offline")
S.tick()
check("in game .lf offline", friend(state("alice"), "Bob")["status"] == "offline")
realm.do("CMD 2 .lf online")
S.tick()
check("in game .lf online", friend(state("alice"), "Bob")["status"] == "game")

# ---------------------------------------------------------------- unread messages at login, logout
realm.do("LOGOUT 2")
S.tick()
check("logout: bob offline", friend(state("alice"), "Bob")["status"] == "offline")
post("alice", "send", {"to": friend(state("alice"), "Bob")["pid"], "text": "while you were out"})
realm.do("LOGIN 2 22 Bobbert")
S.tick(); S.tick()
check("unread delivered at login", any("while you were out" in l for l in realm.msgs(2)))
st, doc = post("alice", "profile", {"main": "Alicia"})
check("main: refused until played", st == 400)

# ---------------------------------------------------------------- realm restart: a new boot, a fresh snapshot
realm.p.stdin.close(); realm.p.wait(5)
realm.__init__(3000000)
S.tick()
check("after a realm restart nobody is in game until they log in", friend(state("alice"), "Bob")["status"] == "offline")
realm.do("LOGIN 2 22 Bobbert")
S.realm_state["full_at"] = -1e9
S.tick()
check("the snapshot brings bob back", friend(state("alice"), "Bob")["status"] == "game")
realm.up = False
S.tick(); S.tick(); S.tick()
check("realm down: in-game presence cleared", friend(state("alice"), "Bob")["status"] == "offline")
realm.up = True
S.realm_state["full_at"] = -1e9
S.tick()

# ---------------------------------------------------------------- rate limits, length caps
bpid = friend(state("alice"), "Bob")["pid"]
st, doc = post("alice", "send", {"to": bpid, "text": "x" * 501})
check("501 characters refused", st == 400)
st, doc = post("alice", "send", {"to": bpid, "text": "   "})
check("empty refused", st == 400)
codes = [post("alice", "send", {"to": bpid, "text": f"spam {i}"})[0] for i in range(25)]
check("rate limit: 429 after 20 a minute", 429 in codes and codes.count(200) <= 20)
st, doc = post("dave", "send", {"to": bpid, "text": "hello stranger"})
check("only friends can message", st == 403)

# ---------------------------------------------------------------- reports
st, doc = post("bob", "report", {"pid": alice_pid, "reason": "spam", "note": "too many lines"})
check("report filed", st == 200)
st, doc = post("bob", "report", {"pid": alice_pid, "reason": "nonsense"})
check("report needs a known reason", st == 400)
reps = S.reports("open")
check("the report queue has it with the thread's last messages", len(reps) == 1 and reps[0]["reason"] == "spam"
      and reps[0]["target_name"] == "Alice" and reps[0]["reporter"] == "WR000002" and 1 <= len(reps[0]["context"]) <= 20
      and reps[0]["note"] == "too many lines")
check("resolve a report", S.resolve_report(reps[0]["id"], "gm", "warned") and S.reports("open") == []
      and S.reports("done")[0]["outcome"] == "warned")

# ---------------------------------------------------------------- block
st, doc = post("bob", "block", {"pid": alice_pid})
check("block", st == 200)
check("block hides everything both ways", friend(state("alice"), "Bob") is None and friend(state("bob"), "Alice") is None)
st, doc = post("alice", "send", {"to": bpid, "text": "hello?"})
check("blocked: can't message", st == 403)
st, doc = post("alice", "request", {"to": f"Bob#{bob_tag}"})
check("blocked: a request looks like an unknown player", st == 404 and "No player" in doc["error"])
check("blocked list", state("bob")["blocked"][0]["name"] == "Alice")
realm.do("CMD 2 .lm Alice psst")
S.tick()
check("blocked: in game too", any("no Leyline friend called Alice" in l for l in realm.msgs(2)))
post("bob", "unblock", {"pid": alice_pid})
check("unblock: not friends again by itself", friend(state("bob"), "Alice") is None and not state("bob")["blocked"])
post("alice", "decline", {"pid": carol_pid})
check("decline", not state("alice")["incoming"])

# ---------------------------------------------------------------- retention
lo, hi = sorted(["WR000001", "WR000002"])
S.x("INSERT INTO social_messages (lo, hi, sender, body, at, via) VALUES (?,?,?,?,?,?)", (lo, hi, "WR000001", "ancient", 1000, "web"))
S.sweep(force=True)
check("messages older than 30 days are deleted", not S.q("SELECT 1 FROM social_messages WHERE body = 'ancient'"))
S.thread_max = 5
post("bob", "request", {"to": f"Alice#{alice_tag}"}); post("alice", "accept", {"pid": state("alice")["incoming"][0]["pid"]})
bpid = friend(state("alice"), "Bob")["pid"]
S.lim_min.q.clear()   # the per-minute limit from the burst above (instead of waiting a minute)
post("alice", "send", {"to": bpid, "text": "one more"})
n = S.q("SELECT COUNT(*) FROM social_messages WHERE lo = ? AND hi = ?", (lo, hi))[0][0]
check("a conversation keeps at most thread_max messages", n == 5, n)

# ---------------------------------------------------------------- revoke
toks = S.tokens("WR000001")
st, page, _ = call("GET", "/wrath/link", sess="alice")
m = re.search(r'name="id" value="([0-9a-f]{12})"><input type="hidden" name="t" value="([0-9a-f]+)"', page)
form = urllib.parse.urlencode({"id": m.group(1), "t": m.group(2), "do": "revoke"}).encode()
st, page, _ = call("POST", "/wrath/link", raw=form, sess="alice")
check("revoke from the link page", "Revoked" in page and not S.tokens("WR000001") and len(toks) == 1)
st, doc, _ = call("GET", API + "state", token=TOKEN)
check("a revoked token: 401", st == 401)

# ---------------------------------------------------------------- privacy and logs
check("message bodies never logged", SECRET not in logbuf.getvalue() and "while you were out" not in logbuf.getvalue())
src = open(os.path.join(ROOT, "stream", "social.py"), encoding="utf-8").read()
check("social.py never logs a body or a text", not re.search(r"log\.\w+\([^)]*(body|text)\b", src))
shown = " ".join(x for x in re.findall(r'"([^"]*)"', src) if "(?i)" not in x)
check("no brand names in what players see", not re.search(r"(?i)warcraft|blizzard|lich king|\bwow\b", shown))

realm.p.stdin.close()
print(f"{count - fails} passed, {fails} failed")
sys.exit(1 if fails else 0)
