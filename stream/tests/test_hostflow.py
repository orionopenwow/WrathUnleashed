"""The host-a-realm flow (GET/POST /wrath/host, /wrath/host/<id> and its downloads; stream/hostflow.py):
sign-in redirect, form validation, owner-only pages, downloads with no foreign secrets, the download really
sets up the kit (leyline host --config-only, no Docker) with the realm key made on the PC (never on the site),
pairing (the site finds the PC's realm id through the relay by the token's hash), live status, claims, escaping,
an older record (a site-made key, seed v1) still working, no banned words.

    python3 -I stream/tests/test_hostflow.py stream/wrath_portal.py
"""
import base64, http.client, importlib.util, json, os, re, shutil, stat, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix="wu-hostflow-")
SENTINELS = {"SOAP_PASS": "SOAPSECRET-sentinel-123", "WU_LISTING_SITE_SECRET": "SITESECRET-sentinel-456"}
fake_relay = {"online": set(), "claims": [], "auth": [], "pairs": {}, "pair_asks": []}


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, st, doc):
        b = json.dumps(doc).encode()
        self.send_response(st); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        m = re.match(r"^/api/realms/([a-z2-7]{16})$", self.path)
        if m and m.group(1) in fake_relay["online"]:
            return self.reply(200, {"realm_id": m.group(1), "online": True})
        if self.path == "/api/listing/realms.json":
            return self.reply(200, {"realms": []})
        m = re.match(r"^/api/pair/([0-9a-f]{64})$", self.path)
        if m:
            fake_relay["pair_asks"].append(m.group(1))
            rid_ = fake_relay["pairs"].get(m.group(1))
            if rid_:
                return self.reply(200, {"realm_id": rid_, "online": rid_ in fake_relay["online"]})
            return self.reply(404, {"error": "no realm has shown this pairing yet"})
        self.reply(404, {"error": "unknown realm"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        fake_relay["claims"].append(body)
        fake_relay["auth"].append(self.headers.get("Authorization"))
        self.reply(200, {"ok": True})


ACCOUNTS = {"alice": ("Alice", "WR000001", "AlicePass1234567"), "bob": ("Bob", "WR000002", "BobPass123456789"),
            "carol": ("Carol", "WR000003", "CarolPass1234567")}


class Portal(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        m = re.search(r"wr_session=(\w+)", self.headers.get("Cookie", ""))
        acct = ACCOUNTS.get(m.group(1)) if m else None
        if not acct:
            self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = {"/api/me": {"display_name": acct[0]}, "/api/play": {"user": acct[1], "pass": acct[2]}}[self.path]
        b = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


RELAY_PORT, PORTAL_PORT = serve(Relay), serve(Portal)
os.environ.update(SOAP_USER="WUSOAP", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL=f"http://127.0.0.1:{PORTAL_PORT}",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_HOST_DIR=os.path.join(TMP, "hosted"),
                  WU_RELAY_LISTING=f"http://127.0.0.1:{RELAY_PORT}/api/listing/realms.json",
                  WU_JOIN_BASE="https://relay.test", **SENTINELS)
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.realm_status = lambda: {"online": True, "players": 4, "bots": 30}
listing = []
wp.community_realms = lambda: (list(listing), True)
hf = wp.hostflow
PAGE_PORT = serve(wp.PageHandler)

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, str(extra)[:300])


_n = [0]


def req(method, path, who=None, body=None, headers=None, ip=None):
    """Each POST from its own address (the create limit is per address and is checked on its own below)."""
    _n[0] += 1
    ip = ip or ("10.1.0.1" if method == "GET" else f"10.2.{_n[0] // 250}.{_n[0] % 250}")
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
    h = {"X-Forwarded-For": ip}
    if who:
        h["Cookie"] = f"wr_session={who}"
    if body is not None:
        body = urllib.parse.urlencode(body).encode() if isinstance(body, dict) else body
        h["Content-Type"] = "application/x-www-form-urlencoded"
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


BANNED = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")


def visible(page):
    page = page.decode() if isinstance(page, bytes) else page
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", page, flags=re.S))


def token(who):
    st, _, b = req("GET", "/wrath/host", who)
    m = re.search(rb'name="csrf" value="([0-9a-f]+)"', b)
    return m.group(1).decode() if m else ""


def form(who, **kw):
    d = {"csrf": token(who), "name": "Violet Hangout", "preset": "dalaran", "visibility": "public", "gm": "bossman",
         "tagline": "Duels by the fountain", "rules": "Be kind.\nDuels by consent only."}
    d.update(kw)
    return d


check("module loaded", hf is not None)

# --- signed out: straight to sign-in, and back here afterwards
st, h, b = req("GET", "/wrath/host")
check("signed out: 302 to sign-in", st == 302 and h.get("location") == "/login?next=%2Fwrath%2Fhost", h.get("location"))
st, h, b = req("GET", "/wrath/host", "nobody")
check("bad session: 302 to sign-in", st == 302 and h["location"].startswith("/login?next="))
st, h, b = req("GET", "/wrath/host/abcdefghijklmnop")
check("signed out start page: sign-in, back to it", st == 302 and h["location"] == "/login?next=%2Fwrath%2Fhost%2Fabcdefghijklmnop")
st, h, b = req("POST", "/wrath/host", None, {"name": "x"})
check("signed out POST: sign-in", st == 302 and h["location"].startswith("/login?next="))

# --- the form
st, h, b = req("GET", "/wrath/host", "alice")
page = b.decode()
check("form renders", st == 200 and "<form method=\"post\" action=\"/wrath/host\">" in page)
for f in ('name="name"', 'name="preset"', 'name="rules"', 'name="visibility"', 'name="gm"', 'name="tagline"', 'name="csrf"'):
    check(f"form field {f}", f in page)
check("dalaran is the default preset", 'value="dalaran" checked' in page)
check("all kit presets offered", all(f'value="{k}"' in page for k in ("dalaran", "main", "brawl", "progression")))
check("public by default", 'value="public" checked' in page)
check("start server button", ">Start server</button>" in page)
check("signed-in name shown", "Signed in as Alice" in page)
check("no script, CSP script-src none", "<script" not in page and "script-src 'none'" in h.get("content-security-policy", ""))
check("no-store", h.get("cache-control") == "no-store")
check("no instant-slot option", not re.search(r"(?i)instant|slot|coming soon", page))
check("form: no banned words", not BANNED.findall(visible(page)), BANNED.findall(visible(page)))

# --- validation
for label, kw, field in (
        ("empty name", {"name": ""}, "name"),
        ("bad name chars", {"name": "Bad<name>"}, "name"),
        ("long name", {"name": "x" * 33}, "name"),
        ("brand word in name", {"name": "WoW Fans"}, "name"),
        ("the official realm's name", {"name": "wrathunleashed"}, "name"),
        ("brand word in rules", {"rules": "No Warcraft talk"}, "rules"),
        ("bad gm", {"gm": "ab"}, "gm"),
        ("gm with symbols", {"gm": "boss_man"}, "gm"),
        ("bad preset", {"preset": "everything"}, "preset"),
        ("bad visibility", {"visibility": "secret"}, "visibility"),
        ("long tagline", {"tagline": "t" * 81}, "tagline"),
        ("too many rules", {"rules": "\n".join(f"rule {i}" for i in range(11))}, "rules"),
        ("long rule", {"rules": "r" * 121}, "rules")):
    st, h, b = req("POST", "/wrath/host", "alice", form("alice", **kw))
    check(f"invalid: {label}", st == 400 and f'id="err-{field}"'.encode() in b, (st, b[:200]))
st, h, b = req("POST", "/wrath/host", "alice", form("alice", name='"><script>alert(1)</script>', tagline="<b>hi</b>"))
check("escaping: re-rendered values", st == 400 and b"<script>alert" not in b and b"&lt;script&gt;" in b and b"&lt;b&gt;hi" in b)
st, h, b = req("POST", "/wrath/host", "alice", form("alice", csrf="0" * 32))
check("csrf: bad token refused", st == 400 and b"timed out" in b)
st, h, b = req("POST", "/wrath/host", "bob", form("alice"))
check("csrf: another account's token refused", st == 400)
st, h, b = req("POST", "/wrath/host", "alice", form("alice"), headers={"Origin": "https://evil.example"})
check("foreign Origin refused", st == 403)
st, h, b = req("POST", "/wrath/host", "alice", b"name=x", headers={"Content-Type": "text/plain"})
check("non-form body refused", st == 400)
st, h, b = req("POST", "/wrath/elsewhere", "alice", {"a": "b"})
check("POST elsewhere: 405", st == 405)
check("nothing made by bad posts", hf.realms_of("WR000001") == [])

# --- a good post makes a pending realm
st, h, b = req("POST", "/wrath/host", "alice", form("alice"), headers={"Origin": "https://play.openvanilla.app"})
loc = h.get("location", "")
m = re.match(r"^/wrath/host/([a-z2-7]{16})$", loc)
check("created: 303 to the start page", st == 303 and m, (st, loc))
pid = m.group(1) if m else "x" * 16
rec_path = os.path.join(TMP, "hosted", "realms", pid + ".json")
check("record file is 0600", os.path.exists(rec_path) and stat.S_IMODE(os.stat(rec_path).st_mode) == 0o600)
rec = hf.load(pid)
check("the site makes no realm key (the PC does)", rec and "realm_key" not in rec and rec["realm_id"] is None
      and rec["pending_id"] == pid)
check("secrets made like setup.py", rec and re.fullmatch(r"[A-Z2-9]{20}", rec["invite_secret"])
      and re.fullmatch(r"[A-Z2-9]{24}", rec["host_secret"]) and re.fullmatch(r"[A-Za-z0-9_-]{24}", rec["claim"]))
check("answers kept", rec and (rec["name"], rec["preset"], rec["visibility"], rec["gm"], rec["rules"])
      == ("Violet Hangout", "dalaran", "public", "BOSSMAN", ["Be kind.", "Duels by consent only."]))
check("owned by the account", rec and rec["owner"] == "WR000001")
check("no password stored", rec and "AlicePass" not in json.dumps(rec) and "pass" not in rec)

# --- the start page: owner only
st, h, b = req("GET", loc, "alice")
page = b.decode()
check("start page renders", st == 200 and "Violet Hangout" in page)
check("links wait for the PC (the realm id comes from its key)", "appear here as soon as your PC connects" in page
      and "/wrath/r/" not in page and rec["host_secret"] not in page)
check("waiting status", "Waiting for your PC" in page)
check("asked the relay by the token's hash, never the token", fake_relay["pair_asks"]
      and fake_relay["pair_asks"][-1] == hf.pair_hash(rec["claim"]) and rec["claim"] not in "".join(fake_relay["pair_asks"]))
check("polls with a meta refresh", '<meta http-equiv="refresh" content="15">' in page)
check("download links", f'/wrath/host/{pid}/leyline-{pid}.bat' in page and f'/wrath/host/{pid}/leyline-{pid}.sh' in page)
KIT_ZIP = "https://github.com/orionopenwow/Leyline/releases/download/host-kit/WrathUnleashed-host-kit.zip"
check("host kit: the published zip by default (WU_HOST_KIT_URL unset)", "WU_HOST_KIT_URL" not in os.environ
      and hf.KIT_URL == KIT_ZIP and f'href="{KIT_ZIP}"' in page, hf.KIT_URL)
check("hosting guide: the public docs page, not the private repo", 'href="/wrath/docs/hosting"' in page
      and "github.com/orionopenwow/WrathUnleashed" not in page)
check("start page: no instant-slot option", not re.search(r"(?i)instant|slot|coming soon", page))
check("start page: no banned words", not BANNED.findall(visible(page)), BANNED.findall(visible(page)))
check("start page: no script", "<script" not in page)
st, h, b = req("GET", loc, "bob")
check("other account: 404", st == 404 and rec["host_secret"].encode() not in b)
st, h, b = req("GET", f"/wrath/host/{pid}/leyline-{pid}.sh", "bob")
check("other account: no download", st == 404 and rec["claim"].encode() not in b)
st, h, b = req("GET", "/wrath/host/zzzzzzzzzzzzzzzz", "alice")
check("unknown realm: 404", st == 404)
st, h, b = req("GET", f"/wrath/host/{pid}/leyline-aaaaaaaaaaaaaaaa.sh", "alice")
check("mismatched file name: 404", st == 404)
st, h, b = req("GET", "/wrath/host", "alice")
check("form lists the account's realms", f'href="/wrath/host/{pid}"'.encode() in b)

# --- bob's realm (private), to check nothing crosses over
st, h, b = req("POST", "/wrath/host", "bob", form("bob", name="Bobs Den", visibility="private", gm="bobgm", preset="main"))
bob_pid = re.match(r"^/wrath/host/([a-z2-7]{16})$", h.get("location", "")).group(1)
bob = hf.load(bob_pid)

# --- the downloads
st, h, sh = req("GET", f"/wrath/host/{pid}/leyline-{pid}.sh", "alice")
check("sh: attachment", st == 200 and h.get("content-disposition") == f'attachment; filename="leyline-{pid}.sh"')
st, h, bat = req("GET", f"/wrath/host/{pid}/leyline-{pid}.bat", "alice")
check("bat: attachment, CRLF", st == 200 and h.get("content-disposition", "").endswith(f'.bat"') and b"\r\n" in bat
      and b"\n" not in bat.replace(b"\r\n", b""))
for label, blob in (("sh", sh), ("bat", bat)):
    text = blob.decode()
    foreign = [v for v in list(SENTINELS.values()) + ["AlicePass1234567", "BobPass", "wr_session", "WUSOAP",
                                                      bob["invite_secret"], bob["host_secret"], bob["claim"]] if v in text]
    check(f"{label}: no foreign secrets", not foreign, foreign)
    check(f"{label}: never sets a password or makes accounts", not re.search(r"(?i)passw(or)?d\s*=|account create|friend ", text))
    seed = re.search(r"([A-Za-z0-9+/=]{200,})", text)
    doc = json.loads(base64.b64decode(seed.group(1))) if seed else {}
    check(f"{label}: seed v2 carries this realm only, and no key", doc.get("v") == 2 and doc.get("claim") == rec["claim"]
          and doc.get("gm_name") == "BOSSMAN" and doc.get("rules") == rec["rules"] and set(doc) == {
              "v", "invite_secret", "host_secret", "claim", "name", "profile",
              "visibility", "gm_name", "tagline", "rules"}, doc.keys())
    check(f"{label}: says the key is made on the PC", "made on" in text and "never leaves it" in text)
    check(f"{label}: no banned words", not BANNED.findall(text), BANNED.findall(text))
check("sh: runs leyline host", 'exec bash "$KIT/leyline" host "$@"' in sh.decode() and "LEYLINE_GM=BOSSMAN" in sh.decode())
check("bat: runs the kit's host script", 'call "Host a Wrath realm.bat"' in bat.decode() and "--seed state/seed.b64" in bat.decode())

# --- the .sh really sets up a kit (config only, this machine's python3, no Docker)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
kit = os.path.join(TMP, "kit")
os.makedirs(kit)
for f in ("leyline", "host-wrath-realm.sh"):
    shutil.copy(os.path.join(ROOT, "hosting", "kit", f), kit)
shutil.copytree(os.path.join(ROOT, "hosting", "kit", "tools"), os.path.join(kit, "tools"),
                ignore=shutil.ignore_patterns("__pycache__"))
with open(os.path.join(kit, f"leyline-{pid}.sh"), "wb") as f:
    f.write(sh)
env = dict(os.environ, LEYLINE_LOCAL_TOOLS="1")
for k in SENTINELS:
    env.pop(k, None)
p = subprocess.run(["bash", os.path.join(kit, f"leyline-{pid}.sh"), "--config-only"], env=env, cwd=TMP,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
check("sh: leyline host --config-only works", p.returncode == 0, p.stdout[-600:] + p.stderr[-600:])
sys.path.insert(0, os.path.join(kit, "tools"))
from wunet import keys as wkeys  # noqa: E402
try:
    cfg = json.load(open(os.path.join(kit, "state", "host.json")))
except (OSError, ValueError):
    cfg = {}
rid = cfg.get("realm_id") or "y" * 16
check("kit: the realm id comes from the key made on the PC", rid != pid and rid == wkeys.realm_id(wkeys.public_key(
    bytes.fromhex(open(os.path.join(kit, "state", "realm.key")).read().strip()))), cfg.get("realm_id"))
check("kit: the pair hash is the website's", wkeys.pair_hash(rec["claim"]) == hf.pair_hash(rec["claim"]))
check("kit: the website's links and claim", (cfg.get("invite_secret"), cfg.get("host_secret"), cfg.get("claim"))
      == (rec["invite_secret"], rec["host_secret"], rec["claim"]))
check("kit: answers", (cfg.get("name"), cfg.get("profile"), cfg.get("visibility"), cfg.get("gm_name"), cfg.get("relay"))
      == ("Violet Hangout", "dalaran", "public", "BOSSMAN", "relay.test"))
check("kit: tagline", (cfg.get("record") or {}).get("tagline") == "Duels by the fountain")
check("kit: house rules", (cfg.get("record") or {}).get("rules") == rec["rules"])
check("kit: no generated GM login", not os.path.exists(os.path.join(kit, "state", "host-login.txt")) and "gm" not in cfg)
check("kit: seed used and deleted", not os.path.exists(os.path.join(kit, "state", "seed.b64")))
check("kit: realm.key is 0600", stat.S_IMODE(os.stat(os.path.join(kit, "state", "realm.key")).st_mode) == 0o600)

# --- from the game (WrathUnleashedUI/Host.lua, the launcher's leyline://host): the form filled in, checked again
GAME_Q = ("core=azerothcore&preset=main&name=Frost%20Haven%27s&type=pvp&xp=5&loot=2&rep=3&start=level1&bots=20"
          "&vis=private&signup=invite&herokey=on&region=eu&lang=de&tags=pvp%2Crp&max=60")
st, h, b = req("GET", "/wrath/host?" + GAME_Q)
check("from the game, signed out: sign-in keeps the choices", st == 302
      and urllib.parse.unquote(h.get("location", "")) == "/login?next=/wrath/host?" + GAME_Q, h.get("location"))
st, h, b = req("GET", "/wrath/host?" + GAME_Q, "carol")
page = b.decode()
check("from the game: filled in, says so", st == 200 and "Filled in with your choices from the game" in page
      and 'value="Frost Haven&#x27;s"' in page and 'value="main" checked' in page and 'value="private" checked' in page)
check("from the game: More settings open with every choice", "<details class=\"more\" open>" in page
      and '<option value="pvp" selected>' in page and '<option value="5" selected>' in page
      and '<option value="level1" selected>' in page and 'name="bots" min="0" max="200" value="20"' in page
      and '<option value="invite" selected>' in page and '<option value="on" selected>' in page
      and '<option value="eu" selected>' in page and 'name="lang" maxlength="6" value="de"' in page
      and 'value="rp" checked' in page and 'value="pvp" checked' in page and 'value="60"' in page)
check("from the game: no GM name (the host types it)", 'name="gm" maxlength="16" required autocomplete="off" value=""' in page)
st, h, b = req("GET", "/wrath/host?core=azerothcore&preset=dalaran&name=My%20WoW&bots=40&xp=99&evil=1", "carol")
page = b.decode()
check("from the game: what is wrong is left out, and said", st == 200 and "Left out (not valid): bots, evil, name, xp." in page
      and "My WoW" not in page and "<script" not in page)
check("prefill: a ruleset of another core is left out", hf.prefill("core=cmangos&preset=main")[1] == ["preset"])
check("prefill: rates and bots are AzerothCore's", hf.prefill("preset=cmangos-1.12.1&xp=3&bots=5")[1] == ["bots", "xp"])
for label, kw, field in (("rate out of range", {"xp": "11"}, "xp"), ("bots on the hangout", {"bots": "5"}, "bots"),
                         ("start outside Classic levelling", {"start": "level1"}, "start"), ("bad tag", {"tags": "bots"}, "tags"),
                         ("bad language", {"lang": "klingon"}, "lang"), ("bad type", {"type": "evil"}, "type")):
    st, h, b = req("POST", "/wrath/host", "carol", form("carol", **kw))
    check(f"invalid more settings: {label}", st == 400 and f'id="err-{field}"'.encode() in b, (st, b[:200]))
st, h, b = req("POST", "/wrath/host", "carol", form("carol", name="Frost Haven", preset="main", visibility="private",
                                                    type="pvp", xp="5", loot="2", rep="3", start="level1", bots="20",
                                                    signup="invite", herokey="on", region="eu", lang="de", tags="pvp,rp",
                                                    max="60"))
cm = re.match(r"^/wrath/host/([a-z2-7]{16})$", h.get("location", ""))
crec = hf.load(cm.group(1)) if cm else {}
check("more settings: saved with the realm", st == 303 and crec.get("options") == {
    "type": "pvp", "xp": 5, "loot": 2, "rep": 3, "start": "level1", "bots": 20, "signup": "invite", "herokey": "on",
    "region": "eu", "lang": "de", "tags": ["pvp", "rp"], "max": 60}, crec.get("options"))
cpid = cm.group(1) if cm else "z" * 16
st, h, csh = req("GET", f"/wrath/host/{cpid}/leyline-{cpid}.sh", "carol")
cseed = re.search(r"([A-Za-z0-9+/=]{200,})", csh.decode())
cdoc = json.loads(base64.b64decode(cseed.group(1))) if cseed else {}
check("more settings: in the seed", cdoc.get("options") == crec.get("options"))
kit2 = os.path.join(TMP, "kit2")
os.makedirs(os.path.join(kit2, "realm-files", "lua_scripts"))
for f in ("leyline", "host-wrath-realm.sh"):
    shutil.copy(os.path.join(ROOT, "hosting", "kit", f), kit2)
shutil.copytree(os.path.join(ROOT, "hosting", "kit", "tools"), os.path.join(kit2, "tools"),
                ignore=shutil.ignore_patterns("__pycache__"))
with open(os.path.join(kit2, f"leyline-{cpid}.sh"), "wb") as f:
    f.write(csh)
p = subprocess.run(["bash", os.path.join(kit2, f"leyline-{cpid}.sh"), "--config-only"], env=env, cwd=TMP,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
check("kit with more settings: config written", p.returncode == 0, p.stdout[-600:] + p.stderr[-600:])
try:
    c2 = json.load(open(os.path.join(kit2, "state", "host.json")))
except (OSError, ValueError):
    c2 = {}
r2 = c2.get("record") or {}
check("kit: bots, sign-up, Hero Key from the game", (c2.get("bots"), c2.get("signup"), c2.get("herokey")) == (20, "invite", True),
      (c2.get("bots"), c2.get("signup"), c2.get("herokey")))
check("kit: the realm list's type, tags, region, language, max", (r2.get("type"), r2.get("tags"), r2.get("region"),
      r2.get("language"), r2.get("max_players")) == ("PvP", ["pvp", "rp", "bots"], "eu", "de", 60), r2)
renv = open(os.path.join(kit2, "state", "realm.env")).read() if os.path.exists(os.path.join(kit2, "state", "realm.env")) else ""
check("kit: state/realm.env (type, rates, start)", all(x in renv.splitlines() for x in (
    "AC_GAME_TYPE=1", "AC_RATE_XP_KILL=5", "AC_RATE_XP_QUEST=5", "AC_RATE_DROP_ITEM_NORMAL=2", "AC_RATE_DROP_MONEY=2",
    "AC_RATE_REPUTATION_GAIN=3", "OV_MAIN=0")), renv)
dat_p = os.path.join(kit2, "realm-files", "lua_scripts", "host-realm.dat")
dat = open(dat_p).read() if os.path.exists(dat_p) else ""
check("kit: host-realm.dat for Your realm in game, no secrets (private: no join link)",
      dat.startswith('return { realm_id = "') and 'visibility = "private"' in dat and "bots = 20" in dat
      and 'rates = "5/2/3"' in dat and "join" not in dat and c2.get("invite_secret", "x") not in dat
      and c2.get("host_secret", "x") not in dat, dat)
p = subprocess.run(["bash", os.path.join(kit2, "leyline"), "options", "--xp", "2", "--type", "rp"], env=env, cwd=kit2,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
renv = open(os.path.join(kit2, "state", "realm.env")).read()
check("leyline options: rates and type changed for the next start", p.returncode == 0 and "AC_RATE_XP_KILL=2" in renv
      and "AC_GAME_TYPE=6" in renv and json.load(open(os.path.join(kit2, "state", "host.json")))["record"]["type"] == "RP",
      p.stdout[-300:] + p.stderr[-300:])
p = subprocess.run(["bash", os.path.join(kit2, "leyline"), "options", "--bots", "60"], env=env, cwd=kit2,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
envf = open(os.path.join(kit2, ".env")).read() if os.path.exists(os.path.join(kit2, ".env")) else ""
check("leyline options --bots: the bot count for the next start", p.returncode == 0 and "WU_BOTS=60" in envf.splitlines()
      and json.load(open(os.path.join(kit2, "state", "host.json")))["bots"] == 60 and "bots = 60" in
      open(os.path.join(kit2, "realm-files", "lua_scripts", "host-realm.dat")).read(), p.stderr[-300:])
p = subprocess.run(["bash", os.path.join(kit2, "leyline"), "options", "--xp", "99"], env=env, cwd=kit2,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
check("leyline options: out of range refused", p.returncode != 0 and "AC_RATE_XP_KILL=2" in open(os.path.join(kit2, "state", "realm.env")).read())
check("kit: host link", open(os.path.join(kit, "state", "host-link.txt")).read().strip()
      == f"https://relay.test/join/{rid}#{rec['invite_secret']}~{rec['host_secret']}")
p = subprocess.run(["bash", os.path.join(kit, f"leyline-{pid}.sh"), "--config-only"], env=env, cwd=TMP,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
check("sh: safe to run again", p.returncode == 0 and json.load(open(os.path.join(kit, "state", "host.json")))["realm_id"] == rid,
      p.stdout[-300:])
st, h, bsh = req("GET", f"/wrath/host/{bob_pid}/leyline-{bob_pid}.sh", "bob")
with open(os.path.join(kit, "other.sh"), "wb") as f:
    f.write(bsh)
p = subprocess.run(["bash", os.path.join(kit, "other.sh"), "--config-only"], env=env, cwd=TMP,
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
check("another realm's file in the same kit is refused", p.returncode != 0 and "another realm" in (p.stdout + p.stderr)
      and json.load(open(os.path.join(kit, "state", "host.json")))["realm_id"] == rid, p.stdout[-300:] + p.stderr[-300:])

# --- live status: the PC connects (and shows the relay its pair hash), then the realm is listed and claimed
hf._status.clear()
fake_relay["online"].add(rid)
fake_relay["pairs"][wkeys.pair_hash(cfg["claim"])] = rid
st, h, b = req("GET", loc, "alice")
check("online, not listed yet", b"joining the realm list" in b)
check("paired: the site learned the PC's realm id", hf.load(pid)["realm_id"] == rid and "realm_key" not in hf.load(pid))
page = b.decode()
check("share link once paired", f"https://play.openvanilla.app/wrath/r/{rid}" in page)
check("host's own join link (GM account) once paired",
      f"https://relay.test/join/{rid}#{rec['invite_secret']}~{rec['host_secret']}" in page)
listing.append({"id": rid, "name": "Violet Hangout", "tagline": "", "type": "PvE", "ruleset": "dalaran", "live": True,
                "players": 0, "bots": 0, "claimed": False, "rules": []})
hf._status.clear()
st, h, b = req("GET", loc, "alice")
check("online, listed", b"Online, listed" in b and b"http-equiv=\"refresh\"" not in b)
check("claimed for the account", fake_relay["claims"] and fake_relay["claims"][-1] == {
    "realm_id": rid, "token": rec["claim"], "claimed_by": "Alice"} and fake_relay["auth"][-1] == "Bearer " + SENTINELS["WU_LISTING_SITE_SECRET"])
n = len(fake_relay["claims"])
hf._status.clear()
req("GET", loc, "alice")
check("claimed once", len(fake_relay["claims"]) == n)
st, h, b = req("GET", f"/wrath/host/{pid}/leyline-{pid}.sh", "alice")
check("download gone once the PC holds the key", st == 410)
st, h, b = req("GET", loc, "alice")
check("still at its page address after pairing", st == 200 and b"Violet Hangout" in b)

# --- private realm: invite link once paired, never listed
bob_rid = "bobrealmbobrealm"
fake_relay["pairs"][hf.pair_hash(bob["claim"])] = bob_rid
fake_relay["online"].add(bob_rid)
hf._status.clear()
st, h, b = req("GET", f"/wrath/host/{bob_pid}", "bob")
check("private: invite link with its secret", f"https://relay.test/join/{bob_rid}#{bob['invite_secret']}".encode() in b)
check("private: online without the list", b"Online, private" in b)
# a realm id from the relay that isn't one is never taken
weird = hf.new_realm_secrets()
weird.update(owner="WR000009", owner_display="W", created=1, name="Weird", preset="main", visibility="public", gm="WGM",
             tagline="", rules=[], claimed=False, first_online=None)
hf.save(weird)
fake_relay["pairs"][hf.pair_hash(weird["claim"])] = "../../etc/passwd"
hf._status.clear()
check("junk realm id from the relay ignored", hf.status_of(weird)[0] == "waiting" and hf.load(weird["pending_id"])["realm_id"] is None)

# --- an older record (made before the key moved to the PC): a site-made key, seed v1, the key forgotten online
old_key = os.urandom(32)
old_rid = hf.realm_id(hf.ed25519.public_key(old_key))
old = {"realm_key": old_key.hex(), "realm_id": old_rid, "invite_secret": hf.gen(20), "host_secret": hf.gen(24),
       "claim": "oldclaimoldclaimoldclaim", "owner": "WR000002", "owner_display": "Bob", "created": 2, "name": "Old Den",
       "preset": "main", "visibility": "public", "gm": "OLDGM", "tagline": "", "rules": [], "claimed": False,
       "first_online": None}
hf.save(old)
st, h, b = req("GET", f"/wrath/host/{old_rid}", "bob")
check("old record: page at its realm id, links shown", st == 200 and f"/wrath/r/{old_rid}".encode() in b)
st, h, b = req("GET", f"/wrath/host/{old_rid}/leyline-{old_rid}.sh", "bob")
seed = re.search(rb"([A-Za-z0-9+/=]{200,})", b)
doc = json.loads(base64.b64decode(seed.group(1))) if seed else {}
check("old record: seed v1 with its key", st == 200 and doc.get("v") == 1 and doc.get("realm_key") == old_key.hex()
      and doc.get("realm_id") == old_rid)
fake_relay["online"].add(old_rid)
hf._status.clear()
req("GET", f"/wrath/host/{old_rid}", "bob")
check("old record: the site forgets its key once online", hf.load(old_rid)["realm_key"] is None)

# --- per-account limit
for i in range(2):
    req("POST", "/wrath/host", "alice", form("alice", name=f"Extra {i}"))
st, h, b = req("POST", "/wrath/host", "alice", form("alice", name="One Too Many"))
check("per-account limit", st == 400 and len(hf.realms_of("WR000001")) == hf.PER_ACCOUNT)

# --- the create limit per address
codes = [req("POST", "/wrath/host", "alice", {"x": "y"}, ip="10.9.9.9")[0] for _ in range(hf.POSTS_PER_MIN + 1)]
check("posts per address are limited", codes[-1] == 429 and 429 not in codes[:-1], codes)

# --- the "+ Your server" buttons
for name, html_ in (("realm list", wp.realms_page()), ("Leyline page", wp.leyline_page()),
                    ("account page", wp.account_page("Alice", "WR000001", "AlicePass1234567", "n"))):
    check(f"+ button on the {name}", b'class="ly-plus" href="/wrath/host"' in html_ and b"Your server" in html_)
check("Leyline page keeps its three big buttons", wp.leyline_page().decode().count('class="ly-btn') == 3)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
