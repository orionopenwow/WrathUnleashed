"""The Leyline Admin Console (stream/admin.py hooked into wrath_portal.py), end to end on a local portal with a fake
website sign-in, a fake realm SOAP (answering ov_admin.lua's "ovadmin" words; the Lua side has its own test,
stream/tests/test_ov_admin.lua), a fake Beacons relay and a fake GitHub releases API.

Covers: who gets in (owner, staff file, WU_MODS_ADMINS, GM level, everyone else refused), noindex, CSRF on every POST,
same-origin, the typed confirm, owner-only actions, the audit log (who, what, when, before, after), rate limits, every
section's actions (catalog, Workshop, index, realms, releases and channel, news, flags, themes, reports, staff),
the public feeds, the overrides the public pages honour, no secrets on the pages, nothing deleted.

    python3 -I stream/tests/test_admin.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.parse, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
STREAM = os.path.dirname(PORTAL)
ROOT = os.path.dirname(STREAM)

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, str(extra)[:600])


T = tempfile.mkdtemp(prefix="wu-admin-")
DATA, MODS, WSDIR = os.path.join(T, "data"), os.path.join(T, "mods"), os.path.join(T, "workshop")
for d in (DATA, MODS, WSDIR, os.path.join(DATA, "hub")):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------- the catalog: the real mods, packed by wu-mod.py
r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "mods", "wu-mod.py"), "catalog", os.path.join(ROOT, "mods", "catalog"),
                    "-o", os.path.join(MODS, "catalog.json"), "--dist", os.path.join(MODS, "files")], capture_output=True, text=True)
check("setup: wu-mod.py catalog", r.returncode == 0, r.stdout + r.stderr)
cat = json.load(open(os.path.join(MODS, "catalog.json")))
# a bad mod: an MPQ inside its zip, which the checker must find
with zipfile.ZipFile(os.path.join(MODS, "files", "badmod-1.0.0.zip"), "w") as z:
    z.writestr("badmod/mod.json", json.dumps({"id": "badmod", "name": "Bad", "version": "1.0.0", "kind": "ui"}))
    z.writestr("badmod/ui/Bad/data.mpq", b"MPQ\x1a" + b"\0" * 60)
cat["mods"].append({"id": "badmod", "name": "Bad mod", "version": "1.0.0", "kind": "ui", "zip": "badmod-1.0.0.zip",
                    "description": "x", "author": "x", "licence": "MIT"})
json.dump(cat, open(os.path.join(MODS, "catalog.json"), "w"))
cdoc = json.load(open(os.path.join(ROOT, "mods", "categories.json")))
if "themes" not in [c["id"] for c in cdoc["categories"]]:   # the themes agent's 13th category (docs/THEMES.md)
    cdoc["categories"].append({"id": "themes", "name": "Themes", "line": "Launcher theme packs.", "icon": ""})
json.dump(cdoc, open(os.path.join(MODS, "categories.json"), "w"))
CATS = [c["id"] for c in cdoc["categories"]]

PID = "3f9a0c12bd47"
open(os.path.join(DATA, "projects.jsonl"), "w").write(json.dumps({
    "id": PID, "url": "https://github.com/alice/frame-kit", "host": "github.com", "forge": "github", "title": "frame-kit",
    "author": "alice", "author_url": "https://github.com/alice", "licence": "MIT", "description": "Tidy unit frames for raids.",
    "category": CATS[0], "builds": ["3.3.5a"], "stars": 4, "last_push": "", "submitted_by": "Alice", "submitter": "acc-alice",
    "submitted_at": "2026-10-25T11:58:00Z", "last_checked": "", "reports": ["acc-bob", "acc-cid"], "hidden": False}) + "\n")

json.dump({"updated": int(time.time()), "items": [
    {"id": 1, "kind": "course", "title": "Windmill Nine", "author": "Ann", "descr": "", "version": 1, "created": 100, "plays": 50, "up": 3, "down": 0},
    {"id": 2, "kind": "build", "title": "Cozy Inn", "author": "Bob", "descr": "", "version": 1, "created": 200, "plays": 1, "up": 0, "down": 0},
]}, open(os.path.join(WSDIR, "items.json"), "w"))

HUB_INDEX = os.path.join(T, "community-index.json")
H1, H2, HE = "0123456789ab", "ba9876543210", "aaaaaaaaaaaa"
json.dump({"format": 1, "entries": [
    {"id": "link:" + HE, "name": "Individual Progression", "repo": "https://github.com/x/y", "licence": "MIT",
     "category": "presets", "type": "module", "description": "d", "updated": "2026-10-01"}]}, open(HUB_INDEX, "w"))
open(os.path.join(DATA, "hub", "submissions.jsonl"), "w").write(
    json.dumps({"id": H1, "repo": "https://github.com/c/cool-addon", "build": "3.3.5a", "category": "addons",
                "note": "A cool addon", "at": "2026-10-29T10:00:00Z", "via": "portal"}) + "\n"
    + json.dumps({"id": H2, "repo": "https://github.com/m/meh", "build": "1.12", "category": "tools", "note": "", "at": "x", "via": "portal"}) + "\n")


class FakeSocial:
    """stream/social.py's Social.reports / resolve_report, as the social agent defined them."""
    def __init__(self):
        self.rows = [{"id": 5, "at": 1761739200, "reporter": "acc-bob", "reporter_name": "Bob", "target": "acc-mal",
                      "target_name": "Mallory", "reason": "abuse", "note": "keeps going", "via": "launcher", "status": "open",
                      "handled_by": None, "handled_at": None, "outcome": None,
                      "context": [{"from": "acc-bob", "text": "PRIVATE-REPORTER-MESSAGE", "at": 1, "via": "game"},
                                  {"from": "acc-mal", "text": "OLDER-MALLORY-MESSAGE", "at": 2, "via": "game"},
                                  {"from": "acc-mal", "text": "you are <b>bad</b> REPORTED-BODY", "at": 3, "via": "game"},
                                  {"from": "acc-bob", "text": "PRIVATE-LATER-REPLY", "at": 4, "via": "game"}]}]

    def reports(self, status="open", limit=100):
        return [dict(r) for r in self.rows if not status or r["status"] == status][:limit]

    def resolve_report(self, rid, by, outcome, status="done"):
        for r in self.rows:
            if r["id"] == rid:
                r.update(status=status, handled_by=by, outcome=outcome)
                return True
        return False


# theme packs: Workshop entries in the "themes" category (docs/THEMES.md)
TPID = "7e7e7e7e7e7e"
with open(os.path.join(DATA, "projects.jsonl"), "a") as f:
    f.write(json.dumps({"id": TPID, "url": "https://github.com/ann/frost-glass", "host": "github.com", "forge": "github",
                        "title": "Frost Glass", "author": "ann", "licence": "MIT", "description": "A cool blue theme pack.",
                        "category": "themes", "builds": ["any"], "submitted_by": "Ann", "submitter": "acc-ann",
                        "submitted_at": "2026-10-29T11:00:00Z", "last_checked": "", "reports": [], "hidden": False}) + "\n")

SOAP_PORT, RELAY_PORT, SITE_PORT, GH_PORT, PAGE_PORT = 17931, 17932, 17933, 17934, 17935
RID_A, RID_B = "abcdefghijklmnop", "qrstuvwxyz234567"
os.environ.update(
    SOAP_USER="WUSOAP", SOAP_PASS="sekritsoappass", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
    PORTAL_URL=f"http://127.0.0.1:{SITE_PORT}", PUBLIC_HOST="play.example", WU_STREAM="0", STREAM_HOST="wrath.example",
    WU_RELAY_LISTING=f"http://127.0.0.1:{RELAY_PORT}/api/listing/realms.json", WU_JOIN_BASE="https://relay.example",
    WU_PORTAL_DATA=DATA, WU_MODS_DIR=MODS, WU_WORKSHOP_ITEMS_DIR=WSDIR, WU_ADMIN_OWNERS="owner1",
    WU_MODS_ADMINS="modadm", WU_HUB_INDEX=HUB_INDEX,
    WU_LEYLINE_RELEASES_API=f"http://127.0.0.1:{GH_PORT}/repos/orionopenwow/Leyline/releases", WU_HANGOUT_FILE=os.path.join(T, "none"))

# ---------------------------------------------------------------- fakes
soap_log = []
ws_items = {1: {"kind": "course", "state": "approved", "title": "Windmill Nine", "descr": ""},
            2: {"kind": "build", "state": "pending", "title": "Cozy Inn", "descr": ""},
            3: {"kind": "mode", "state": "pending", "title": "Shit Arena", "descr": ""}}
bugs = {7: {"status": "new", "text": "quest giver <script>alert(1)</script> has no mark"}, 6: {"status": "seen", "text": "stuck"}}
GM = {"WRGM": 3, "WRPLAYER": 0}


def soap_answer(cmd):
    m = re.match(r"^ovadmin (\S+)\s*(.*)$", cmd)
    if not m:
        return "Connected players: 4 (peak: 9). Queue: 2.\nCharacters in world: 10\nServer uptime: 1 hour(s)"
    word, rest = m.groups()
    if word == "ping":
        return "ovadmin ok\novadmin end 0"
    if word == "gm":
        n = rest.upper()
        return f"ovadmin gm {n} {GM.get(n, 0)}\novadmin end 1"
    if word == "ws":
        a = rest.split(" ", 3)
        if a[0] == "list":
            rows = [f"ROW\t{i}\t{it['kind']}\t{it['state']}\t1\t0\t0\t0\tAnn\t{1 if 'Shit' in it['title'] else 0}\t{it['title']}\t{it['descr']}"
                    for i, it in sorted(ws_items.items(), reverse=True) if a[1] == "all" or it["state"] == a[1]]
            return "\n".join(rows + [f"ovadmin end {len(rows)}"])
        if a[0] == "set":
            it = ws_items.get(int(a[1]))
            if not it:
                return "ovadmin error: no such item"
            it["state"] = {"approve": "approved", "reject": "rejected", "pending": "pending"}[a[2]]
            return f"ovadmin ok: #{a[1]} {it['state']}\novadmin end 0"
        if a[0] == "edit":
            ws_items[int(a[1])][a[2]] = a[3]
            return f"ovadmin ok: #{a[1]} {a[3]}\novadmin end 0"
        if a[0] == "check":
            f = ["title: filtered word"] if "Shit" in ws_items[int(a[1])]["title"] else []
            return "\n".join([f"FINDING\t{x}" for x in f] + [f"ovadmin end {len(f)}"])
    if word == "bugs":
        a = rest.split()
        if a[0] == "list":
            rows = [f"ROW\t{i}\t{b['status']}\t1700000000\tAnn\t12\t0\t12\t{b['text']}" for i, b in sorted(bugs.items(), reverse=True)
                    if a[1] == "all" or (a[1] == "open" and b["status"] in ("new", "seen")) or b["status"] == a[1]]
            return "\n".join(rows + [f"ovadmin end {len(rows)}"])
        if a[0] == "set":
            bugs[int(a[1])]["status"] = a[2]
            return f"ovadmin ok: bug {a[1]} {a[2]}\novadmin end 0"
        if a[0] == "count":
            c = {}
            for b in bugs.values():
                c[b["status"]] = c.get(b["status"], 0) + 1
            return "\n".join([f"COUNT\t{k}\t{v}" for k, v in c.items()] + [f"ovadmin end {len(c)}"])
    return "ovadmin error: usage"


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        cmd = re.search(r"<command>(.*)</command>", body, re.S).group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        soap_log.append(cmd)
        out = escape(soap_answer(cmd))
        b = (f'<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">'
             f'<SOAP-ENV:Body><ns1:executeCommandResponse><result>{out}</result></ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>').encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


GAME = {"owner1": "WROWNER", "staff1": "WRSTAFF", "modadm": "WRMOD", "gmguy": "WRGM", "player": "WRPLAYER", "newbie": "WRNEW"}


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        m = re.search(r"wr_session=([a-z0-9]+)", self.headers.get("Cookie", ""))
        who = m.group(1) if m else ""
        if who not in GAME:
            self.send_response(401)
            self.end_headers()
            return
        doc = {"id": who, "display_name": who.title()} if self.path == "/api/me" else \
            {"user": GAME[who], "pass": "GAMEPASS" + who.upper()}
        b = json.dumps(doc).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def rec(rid, name, live=True, players=3):
    return {"schema": 1, "name": name, "official": False, "state": "live" if live else "offline", "tagline": "t", "type": "Fun",
            "profile": {"ruleset": "dalaran"}, "community": {"realmId": rid, "claimed": True, "relay": "relay.example",
                                                            "firstSeen": "2026-10-20T00:00:00Z", "lastSeen": "2026-10-29T12:00:00Z",
                                                            "lastHeartbeat": {"online": live, "players": players, "bots": 1, "seq": 42}}}


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        b = json.dumps({"schema": 1, "realms": [rec(RID_A, "Frost Haven"), rec(RID_B, "Quiet Corner", False, 0)]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


RELEASES = [{"tag_name": "launcher-v0.5.0", "name": "Leyline 0.5.0", "draft": False, "prerelease": True,
             "published_at": "2026-10-29T10:00:00Z", "html_url": "https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.5.0",
             "assets": [{"name": "latest.json"}, {"name": "Leyline.msi"}]},
            {"tag_name": "launcher-v0.4.2", "name": "Leyline 0.4.2", "draft": False, "prerelease": False,
             "published_at": "2026-10-20T10:00:00Z", "html_url": "https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.4.2",
             "assets": [{"name": "latest.json"}]},
            {"tag_name": "launcher-v0.6.0", "name": "draft", "draft": True, "prerelease": False, "published_at": None,
             "html_url": "https://github.com/orionopenwow/Leyline/releases/tag/untagged", "assets": []}]


class GitHub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        b = json.dumps(RELEASES).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


for port, h in ((SOAP_PORT, Soap), (SITE_PORT, Site), (RELAY_PORT, Relay), (GH_PORT, GitHub)):
    s = ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()

spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)
A = wp.admin
LIMITS = (A.POSTS_PER_MIN, A.IP_PER_MIN, A.PAGES_PER_MIN)
A.POSTS_PER_MIN = A.IP_PER_MIN = A.PAGES_PER_MIN = 10 ** 6   # the rate limits have their own test at the end
import types
FAKE_SOCIAL = FakeSocial()
wp.social = types.SimpleNamespace(store=FAKE_SOCIAL, match=lambda path: False)   # what the portal has once stream/social.py is merged
check("the portal loads admin.py", A is not None and wp.workshop is not None and wp.workshop.adjust == A.adjust_catalog
      and wp.creations.adjust == A.adjust_catalog)
srv = wp.Server(("127.0.0.1", PAGE_PORT), wp.PageHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, who=None, form=None, origin="https://play.example", ctype="application/x-www-form-urlencoded", ip=None):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=30)
    h = {"X-Forwarded-For": ip or "10.0.0.1"}
    if who:
        h["Cookie"] = f"wr_session={who}"
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = ctype
        if origin:
            h["Origin"] = origin
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    out = (r.status, {k: v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace"))
    c.close()
    return out


def token(who, path="/wrath/admin/catalog"):
    st, _, body = req("GET", path, who)
    m = re.search(r'name="csrf" value="([0-9a-f]+)"', body)
    return m.group(1) if m else ""


def act(who, action, target, back="/wrath/admin", **fields):
    f = {"csrf": fields.pop("csrf", None) or token(who), "action": action, "target": target, "back": back}
    f.update(fields)
    st, hd, body = req("POST", "/wrath/admin/act", who, f)
    loc = urllib.parse.unquote(hd.get("Location", ""))
    return st, loc


def ok_(r):
    return r[0] == 303 and "ok=Done" in r[1]


def audit():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "admin", "audit.jsonl"))]
    except OSError:
        return []


def feed(name):
    st, hd, body = req("GET", f"/wrath/leyline/{name}")
    return st, hd, json.loads(body) if st == 200 else {}


# ---------------------------------------------------------------- who gets in
st, hd, _ = req("GET", "/wrath/admin")
check("signed out: to the sign-in, and back here", st == 302 and hd.get("Location") == "/login?next=%2Fwrath%2Fadmin")
st, hd, body = req("GET", "/wrath/admin", "player")
check("a player: 403 staff only, with their own account id", st == 403 and "Staff only" in body and "<code>player</code>" in body)
check("refusals are noindex too", hd.get("X-Robots-Tag", "").startswith("noindex") and 'name="robots" content="noindex' in body)
check("a player's page has no admin links", "/wrath/admin/act" not in body and "csrf" not in body)
st, hd, body = req("GET", "/wrath/admin", "owner1")
check("the owner: the dashboard", st == 200 and "Leyline Admin" in body and "Signed in as Owner1 (owner)" in body, body[:400])
check("noindex: header and meta", hd.get("X-Robots-Tag") == "noindex, nofollow" and '<meta name="robots" content="noindex,nofollow">' in body)
check("the page's one script carries the CSP nonce", re.search(r"script-src 'nonce-([^']+)'", hd.get("Content-Security-Policy", ""))
      and re.search(r"<script nonce=\"[^\"]+\">", body) and "no-store" in hd.get("Cache-Control", ""))
st, _, body = req("GET", "/wrath/admin", "modadm")
check("WU_MODS_ADMINS (the Workshop's admins) are staff", st == 200 and "(staff)" in body)
st, _, body = req("GET", "/wrath/admin", "gmguy")
check("a GM level 3 game account is staff (ovadmin gm over SOAP)", st == 200 and "(staff)" in body and "ovadmin gm WRGM" in soap_log)
os.environ["WU_ADMIN_GM_LEVEL"] = "0"
A._gm_cache.clear()
check("WU_ADMIN_GM_LEVEL=0 turns the GM rule off", req("GET", "/wrath/admin", "gmguy")[0] == 403)
os.environ["WU_ADMIN_GM_LEVEL"] = "4"
A._gm_cache.clear()
check("GM level below the minimum: refused", req("GET", "/wrath/admin", "gmguy")[0] == 403)
del os.environ["WU_ADMIN_GM_LEVEL"]
A._gm_cache.clear()

# ---------------------------------------------------------------- dashboard
st, _, body = req("GET", "/wrath/admin", "owner1")
check("dashboard: realm numbers from status", "Players online" in body and "<b>4</b><span>Players online" in body
      and "<b>2</b><span>Login queue" in body, re.findall(r"<b>[^<]*</b><span>[^<]*", body))
check("dashboard: relay realms counted", "<b>2</b><span>Community realms" in body)
check("dashboard: queues (Workshop 2 waiting, 2 index submissions)", "<b>2</b><span>Workshop waiting" in body
      and "<b>2</b><span>Index submissions" in body and "<b>0</b><span>Theme packs waiting" in body)
check("dashboard: open reports (2 bugs, 1 message, 1 link)", "<b>2</b><span>Open .bug reports" in body
      and "<b>1</b><span>Open message reports" in body and "<b>1</b><span>Reported links" in body)
check("dashboard: catalog counts", f"<b>{len(cat['mods'])}</b><span>Packaged mods" in body and "<b>2</b><span>Community links" in body
      and "<b>2</b><span>Workshop items live" in body and "<b>1</b><span>Index entries" in body)
check("dashboard: launcher versions are not collected (no telemetry)", "Not collected" in body and "no telemetry" in body)
os.makedirs(os.path.join(DATA, "admin"), exist_ok=True)
json.dump({"versions": {"0.4.2": 12, "0.5.0": 3, "junk<": 9}}, open(os.path.join(DATA, "admin", "launcher-versions.json"), "w"))
body = req("GET", "/wrath/admin", "owner1")[2]
check("dashboard: launcher versions from an update-check summary, when one exists", "<td>0.4.2</td><td>12</td>" in body and "junk" not in body)

TABS = ["catalog", "workshop", "hub", "realms", "releases", "flags", "themes", "reports", "health", "staff", "audit", "catalog/mod/pings"]
res = {t: req("GET", "/wrath/admin/" + t, "owner1") for t in TABS}
check("every section renders for the owner", all(r[0] == 200 for r in res.values()), {t: r[0] for t, r in res.items()})
check("every section renders for staff", all(req("GET", "/wrath/admin/" + t, "modadm")[0] == 200 for t in TABS))
check("every section refuses a player", all(req("GET", "/wrath/admin/" + t, "player")[0] == 403 for t in TABS))
st, hd, body = req("POST", "/wrath/admin/act", "owner1", {"csrf": token("owner1"), "action": "news.hide", "target": "zz", "confirm": "zz"})
loc = hd.get("Location", "")
check("after an action: the message, signed", st == 303 and "&m=" in loc and "No such post" in req("GET", loc, "owner1")[2])
check("a crafted message link shows nothing", "Call 555" not in req("GET", "/wrath/admin?err=Call+555+now&m=0000", "owner1")[2]
      and "Call 555" not in req("GET", "/wrath/admin?ok=Call+555", "owner1")[2])
check("an unknown section: 404, still noindex", req("GET", "/wrath/admin/nope", "owner1")[0] == 404)
allpages = "".join(r[2] for r in res.values())
check("no secrets on any page (SOAP login, game passwords, the CSRF key)", "sekritsoappass" not in allpages and "GAMEPASS" not in allpages
      and A._secret().hex() not in allpages and "WUSOAP" not in allpages)
check("the Workshop page says 'Nothing is deleted'", "Nothing is deleted" in res["workshop"][2])

# ---------------------------------------------------------------- CSRF, origin, form shape
n0 = len(audit())
st, _, body = req("POST", "/wrath/admin/act", "owner1", {"action": "flag.set", "target": "p2p_hosting", "on": "1", "confirm": "p2p_hosting"})
check("POST without a CSRF token: 403", st == 403 and "out of date" in body)
check("... and it is in the audit log as refused", audit()[-1]["ok"] is False and "CSRF" in audit()[-1]["note"] and len(audit()) == n0 + 1)
st, _, _ = req("POST", "/wrath/admin/act", "owner1", {"csrf": "0" * 40, "action": "flag.set", "target": "p2p_hosting", "on": "1", "confirm": "p2p_hosting"})
check("a wrong token: 403", st == 403)
st, _, _ = req("POST", "/wrath/admin/act", "owner1", {"csrf": token("modadm"), "action": "flag.set", "target": "p2p_hosting", "on": "1", "confirm": "p2p_hosting"})
check("another account's token: 403", st == 403)
st, _, _ = req("POST", "/wrath/admin/act", "owner1", {"csrf": token("owner1"), "action": "news.add", "target": "new"}, origin="https://evil.example")
check("another site's form: 403", st == 403)
st, _, _ = req("POST", "/wrath/admin/act", "owner1", {"csrf": token("owner1")}, ctype="application/json")
check("not a form: 400", st == 400)
st, _, _ = req("POST", "/wrath/admin/act", "player", {"csrf": token("owner1"), "action": "flag.set", "target": "p2p_hosting"})
check("a player's POST: 403", st == 403)
check("flags untouched by all of that", feed("flags.json")[2]["flags"]["p2p_hosting"] is False)
st, _, _ = req("POST", "/wrath/admin/nope", "owner1", {"x": "1"})
check("POST elsewhere under /wrath/admin: 405", st == 405)

# ---------------------------------------------------------------- flags (owner, typed confirm)
import hashlib


def flag_sha_ok(d):
    body = {k: v for k, v in d.items() if k != "sha256"}
    return d.get("sha256") == hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


st, hd, f = feed("flags.json")
check("flags.json: the host-pack/P2P agent's format, all off, sha256", f.get("format") == 1 and f["flags"] == {
      "p2p_hosting": False, "torrent_downloads": False, "torrent_seeding": False, "webrtc_presence": False}
      and flag_sha_ok(f) and set(f) == {"format", "updated_at", "flags", "limits", "stun", "sha256"}
      and hd.get("Access-Control-Allow-Origin") == "*", f)
r = act("modadm", "flag.set", "p2p_hosting", on="1", confirm="p2p_hosting")
check("staff cannot flip a flag (owner only)", "err=Only the owner" in r[1] and audit()[-1]["note"] == "owner only")
r = act("owner1", "flag.set", "p2p_hosting", on="1")
check("the owner without the typed confirm: refused", "err=Type p2p_hosting to confirm" in r[1] and not feed("flags.json")[2]["flags"]["p2p_hosting"])
r = act("owner1", "flag.set", "p2p_hosting", on="1", confirm="p2p_hostin")
check("a mistyped confirm: refused", "err=" in r[1])
r = act("owner1", "flag.set", "p2p_hosting", "/wrath/admin/flags", on="1", confirm="p2p_hosting")
f = feed("flags.json")[2]
check("typed confirm: on, a new updated_at and sha256", ok_(r) and f["flags"]["p2p_hosting"] is True and flag_sha_ok(f)
      and f["updated_at"] != "2026-10-29T00:00:00Z", r)
check("the served file never names the admin", "owner1" not in json.dumps(f))
check("redirect back to the section", r[1].startswith("/wrath/admin/flags?ok="))
a = audit()[-1]
check("audit: who, what, when, before, after", a["who"] == "owner1" and a["name"] == "Owner1" and a["role"] == "owner"
      and a["action"] == "flag.set" and a["target"] == "p2p_hosting" and a["before"] == {"p2p_hosting": False}
      and a["after"]["p2p_hosting"] is True and re.match(r"^\d{4}-\d\d-\d\dT", a["at"]) and a["ok"] is True, a)
check("unknown flags refused", "err=Unknown flag" in act("owner1", "flag.set", "voice_chat", on="1", confirm="voice_chat")[1])
check("flags page shows the flags with confirm boxes", 'data-confirm="torrent_seeding"' in req("GET", "/wrath/admin/flags", "owner1")[2])
check("staff see flags without switches", 'data-confirm="' not in req("GET", "/wrath/admin/flags", "modadm")[2])
act("owner1", "flag.set", "p2p_hosting", on="0", confirm="p2p_hosting")
check("and off again", feed("flags.json")[2]["flags"]["p2p_hosting"] is False and flag_sha_ok(feed("flags.json")[2]))
wp.leyline_net = types.SimpleNamespace(serve=lambda path: None, KNOWN=("p2p_hosting", "x_flag"), load=lambda: {"format": 1, "updated_at": "u", "flags": {"x_flag": True}},
                                       path=lambda: "/nowhere", write_flags=lambda p, ch, by="": (_ for _ in ()).throw(ValueError("x_flag is locked")))
body = req("GET", "/wrath/admin/flags", "owner1")[2]
r = act("owner1", "flag.set", "x_flag", on="0", confirm="x_flag")
check("with stream/leyline_net.py in the portal: its flags, its writer, its feed", "<code>x_flag</code>" in body and "err=x_flag is locked" in r[1]
      and not A.match("/wrath/leyline/flags.json"))
wp.leyline_net = None

# ---------------------------------------------------------------- catalog
mods_ids = lambda: [p["id"] for p in json.loads(req("GET", "/wrath/mods/all.json")[2])["projects"]]
check("catalog: pings listed before", "mod:pings" in mods_ids())
check("unpublish needs the typed confirm", "err=Type pings" in act("modadm", "mod.unpublish", "pings")[1])
r = act("modadm", "mod.unpublish", "pings", confirm="pings")
check("unpublish: gone from all.json and its page", ok_(r) and "mod:pings" not in mods_ids() and req("GET", "/wrath/mods/pings")[0] == 404)
check("... the zip and the catalog file stay", os.path.isfile(os.path.join(MODS, "files", "pings-" + next(m["version"] for m in cat["mods"] if m["id"] == "pings") + ".zip")))
check("the admin catalog still shows it, unpublished", "unpublished" in req("GET", "/wrath/admin/catalog", "modadm")[2])
r = act("modadm", "mod.approve", "pings")
check("approve: back", ok_(r) and "mod:pings" in mods_ids() and audit()[-1]["before"] == {"state": "unpublished"})
r = act("modadm", "mod.reject", "emote-wheel", confirm="emote-wheel")
check("reject: gone", ok_(r) and "mod:emote-wheel" not in mods_ids())
act("modadm", "mod.approve", "emote-wheel")
r = act("modadm", "mod.feature", "pings", on="1")
proj = {p["id"]: p for p in json.loads(req("GET", "/wrath/mods/all.json")[2])["projects"]}
check("feature: all.json says featured", ok_(r) and proj["mod:pings"]["featured"] is True and proj["mod:dalaran-dice"]["featured"] is False)
r = act("modadm", "mod.edit", "pings", name="Map Pings", description="Ping the map for your party.", category=CATS[1])
proj = {p["id"]: p for p in json.loads(req("GET", "/wrath/mods/all.json")[2])["projects"]}
check("edit: name, description, category", ok_(r) and proj["mod:pings"]["name"] == "Map Pings"
      and proj["mod:pings"]["description"] == "Ping the map for your party." and proj["mod:pings"]["category"] == CATS[1])
check("edit: shown on the mod's page too", "Map Pings" in req("GET", "/wrath/mods/pings")[2])
check("edit: a game-brand word is refused", "err=Players see this" in act("modadm", "mod.edit", "pings", name="WoW Pings")[1])
check("edit: unknown category refused", "err=Unknown category" in act("modadm", "mod.edit", "pings", category="nope")[1])
check("edit: unknown mod refused", "err=No such mod" in act("modadm", "mod.edit", "nosuch", name="x")[1])
r = act("modadm", "mod.check", "badmod")
chk = json.load(open(os.path.join(DATA, "admin", "checks", "mod-badmod.json")))
check("re-run the checker: the MPQ in a zip is found", ok_(r) and chk["errors"] >= 1 and any(i["code"] == "blocked" or "MPQ" in i["msg"] for i in chk["items"]), chk)
body = req("GET", "/wrath/admin/catalog/mod/badmod", "modadm")[2]
check("the checker's findings on the mod's page", "MPQ" in body and "errors" in body)
r = act("modadm", "mod.check", "pings")
chk = json.load(open(os.path.join(DATA, "admin", "checks", "mod-pings.json")))
check("a good mod checks clean", ok_(r) and chk["errors"] == 0, chk)
check("the catalog page tags the checker result", "checker: " in req("GET", "/wrath/admin/catalog", "modadm")[2])

# community links
r = act("modadm", "link.dismiss", PID)
recs = [json.loads(x) for x in open(os.path.join(DATA, "projects.jsonl"))]
check("dismiss reports: the link stays, its reports go", ok_(r) and recs[0]["reports"] == [] and not recs[0]["hidden"])
check("hide needs the confirm", "err=Type " + PID in act("modadm", "link.hide", PID)[1])
r = act("modadm", "link.hide", PID, confirm=PID)
recs = [json.loads(x) for x in open(os.path.join(DATA, "projects.jsonl"))]
recs = {x["id"]: x for x in recs}
check("hide: hidden in the file (nothing deleted), off all.json", ok_(r) and len(recs) == 2 and recs[PID]["hidden"] is True
      and "link:" + PID not in mods_ids())
act("modadm", "link.unhide", PID)
r = act("modadm", "link.feature", PID, on="1")
r2 = act("modadm", "link.edit", PID, name="Frame Kit", description="Unit frames for raids.", category=CATS[2])
proj = {p["id"]: p for p in json.loads(req("GET", "/wrath/mods/all.json")[2])["projects"]}
check("links: feature and edit", ok_(r) and ok_(r2) and proj["link:" + PID]["featured"] is True and proj["link:" + PID]["name"] == "Frame Kit"
      and proj["link:" + PID]["category"] == CATS[2])

# ---------------------------------------------------------------- the player Workshop (SOAP)
body = req("GET", "/wrath/admin/workshop", "modadm")[2]
check("workshop: pending items over SOAP, flagged titles tagged", "#2 Cozy Inn" in body and "#3 Shit Arena" in body and "filtered word" in body
      and "#1 Windmill" not in body)
soap_log.clear()
r = act("modadm", "ws.approve", "2", "/wrath/admin/workshop?state=pending")
check("approve: ovadmin ws set 2 approve", ok_(r) and soap_log[-1] == "ovadmin ws set 2 approve" and ws_items[2]["state"] == "approved"
      and r[1].startswith("/wrath/admin/workshop?state=pending&ok="))
check("the list is fresh after an action", "#2 Cozy Inn" in req("GET", "/wrath/admin/workshop?state=approved", "modadm")[2])
check("reject needs the confirm", "err=Type 3" in act("modadm", "ws.reject", "3")[1] and ws_items[3]["state"] == "pending")
r = act("modadm", "ws.reject", "3", confirm="3")
check("reject", ok_(r) and ws_items[3]["state"] == "rejected")
r = act("modadm", "ws.unpublish", "1", confirm="1")
check("unpublish = back to waiting (ovadmin ws set 1 pending), nothing deleted", ok_(r) and soap_log[-1] == "ovadmin ws set 1 pending"
      and ws_items[1]["state"] == "pending")
act("modadm", "ws.approve", "1")
r = act("modadm", "ws.edit", "2", field="title", text="The 'Cozy' Inn; DROP TABLE <x>")
check("edit: text cleaned before SOAP (ov_workshop's characters only)", ok_(r) and soap_log[-1] == "ovadmin ws edit 2 title The Cozy Inn DROP TABLE x", soap_log[-1:])
check("edit: audit before/after", audit()[-1]["before"] == {"title": "Cozy Inn"} and audit()[-1]["after"] == {"title": "The Cozy Inn DROP TABLE x"})
check("edit: other fields refused", "err=Unknown field" in act("modadm", "ws.edit", "2", field="author", text="Bob")[1])
check("edit: brand words refused", "err=Players see this" in act("modadm", "ws.edit", "2", field="descr", text="best wow build")[1])
check("bad ids never reach SOAP", "err=Not a Workshop item id" in act("modadm", "ws.approve", "2;server shutdown")[1]
      and not any("shutdown" in c for c in soap_log))
r = act("modadm", "ws.check", "3")
check("re-run the checks: findings saved and shown", ok_(r) and json.load(open(os.path.join(DATA, "admin", "checks", "ws-3.json")))["items"] == ["title: filtered word"]
      and "title: filtered word" in req("GET", "/wrath/admin/workshop?state=rejected", "modadm")[2])
r = act("modadm", "ws.feature", "2", on="1")
lst = req("GET", "/wrath/workshop?sort=plays", None)[2]
check("feature: the public Workshop lists it first", ok_(r) and lst.find("Cozy Inn") < lst.find("Windmill Nine") and lst.find("Cozy Inn") > 0)
good_soap, wp.AC_SOAP_URL = wp.AC_SOAP_URL, "http://127.0.0.1:9/"
A.forget("ws:")
body = req("GET", "/wrath/admin/workshop", "modadm")[2]
r = act("modadm", "ws.approve", "3")
wp.AC_SOAP_URL = good_soap
A.forget("ws:")
check("a realm that does not answer: the page and the action say so", "the realm did not answer (down)" in body
      and "err=the realm did not answer" in r[1] and audit()[-1]["ok"] is False)

# ---------------------------------------------------------------- the community index
def decisions():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "hub", "decisions.jsonl"))]
    except OSError:
        return []


body = req("GET", "/wrath/admin/hub", "modadm")[2]
check("hub: submissions and entries", "https://github.com/c/cool-addon" in body and "Individual Progression" in body and "A cool addon" in body)
check("reject without a reason: refused", "err=Say why" in act("modadm", "hub.reject", H2)[1] and decisions() == [])
r1 = act("modadm", "hub.approve", H1, reason="nice")
r2 = act("modadm", "hub.reject", H2, reason="no licence file")
d = decisions()
check("decisions appended to hub/decisions.jsonl in stream/hub.py's shape", ok_(r1) and ok_(r2) and len(d) == 2
      and d[0]["id"] == H1 and d[0]["decision"] == "approve" and d[0]["repo"] == "https://github.com/c/cool-addon" and d[0]["build"] == "3.3.5a"
      and d[0]["category"] == "addons" and d[1]["decision"] == "reject" and d[1]["reason"] == "no licence file" and d[1]["by"] == "modadm", d)
check("decided submissions leave the queue", "hub.approve" not in req("GET", "/wrath/admin/hub", "modadm")[2])
check("unknown submission refused", "err=No such submission" in act("modadm", "hub.approve", "ffffffffffff")[1])
check("delist needs the confirm and a reason", "err=" in act("modadm", "hub.delist", HE, reason="x")[1]
      and "err=Say why" in act("modadm", "hub.delist", HE, confirm=HE)[1])
r = act("modadm", "hub.delist", HE, reason="ships game data", confirm=HE)
r2 = act("modadm", "hub.rescan", "all")
r3 = act("modadm", "hub.rescan", HE)
d = decisions()
resc = json.load(open(os.path.join(DATA, "hub", "rescan.json")))
check("delist and re-scan", ok_(r) and ok_(r2) and ok_(r3) and d[-1]["decision"] == "delist" and d[-1]["id"] == HE
      and set(resc["requests"]) == {"all", HE})
check("the index file itself is untouched", json.load(open(HUB_INDEX))["entries"][0] == json.load(open(HUB_INDEX))["entries"][0]
      and "delist" not in open(HUB_INDEX).read())
r = act("modadm", "hub.relist", HE)
check("list again: an approve line (the latest line wins)", ok_(r) and decisions()[-1]["decision"] == "approve" and decisions()[-1]["id"] == HE)
check("bad ids refused", "err=No such index entry" in act("modadm", "hub.rescan", "../x")[1])

# ---------------------------------------------------------------- realms
body = req("GET", "/wrath/admin/realms", "modadm")[2]
check("realms: from the relay, with heartbeats", "Frost Haven" in body and RID_A in body and "seq: 42" in body and "last 2026-10-29T12:00:00Z" in body)
pub = req("GET", "/wrath/realms")[2]
check("public list before", "Frost Haven" in pub and "Quiet Corner" in pub)
check("hide needs the realm id typed", "err=" in act("modadm", "realm.hide", RID_B)[1])
r = act("modadm", "realm.hide", RID_B, confirm=RID_B)
pub = req("GET", "/wrath/realms")[2]
check("hide: off the public realm list at once", ok_(r) and "Quiet Corner" not in pub and "Frost Haven" in pub)
r = act("modadm", "realm.official", RID_A, confirm=RID_A)
pub = req("GET", "/wrath/realms")[2]
check("mark official: tagged Official on the public list", ok_(r) and re.search(r"Frost Haven</h2><div class=\"tags\"><span class=\"tag\">Official", pub), pub[:200])
st, hd, ov = feed("realm-overrides.json")
check("realm-overrides.json for the launcher: hidden and official ids only", ov.get("hidden") == [RID_B] and ov.get("official") == [RID_A]
      and set(ov) == {"format", "updated_at", "hidden", "official"} and hd.get("Access-Control-Allow-Origin") == "*")
check("flag needs a reason", "err=Say why" in act("modadm", "realm.flag", RID_A)[1])
r = act("modadm", "realm.flag", RID_A, reason="spam in the tagline")
check("flag: staff note, not on the public list or the feed", ok_(r) and "spam in the tagline" in req("GET", "/wrath/admin/realms", "modadm")[2]
      and "spam" not in req("GET", "/wrath/realms")[2] and "spam" not in json.dumps(feed("realm-overrides.json")[2]))
act("modadm", "realm.unhide", RID_B)
check("unhide: back", "Quiet Corner" in req("GET", "/wrath/realms")[2])
check("bad realm ids refused", "err=Not a realm id" in act("modadm", "realm.hide", "../../x", confirm="../../x")[1])

# ---------------------------------------------------------------- releases, channel, news
body = req("GET", "/wrath/admin/releases", "owner1")[2]
check("releases from GitHub: tags, pre-release, draft", "launcher-v0.5.0" in body and "launcher-v0.4.2" in body and "pre-release" in body and "draft" in body)
check("staff can't set the channel", "err=Only the owner" in act("modadm", "channel.set", "launcher-v0.4.2", channel="stable", confirm="0.4.2")[1])
check("stable needs the version typed", "err=Type 0.4.2" in act("owner1", "channel.set", "launcher-v0.4.2", channel="stable")[1])
r = act("owner1", "channel.set", "launcher-v0.4.2", channel="stable", confirm="0.4.2")
r2 = act("owner1", "channel.set", "launcher-v0.5.0", channel="beta")
ch = feed("channel.json")[2]
check("channel.json: stable and beta", ok_(r) and ok_(r2) and ch["stable"] == {"version": "0.4.2", "tag": "launcher-v0.4.2",
      "url": "https://github.com/orionopenwow/Leyline/releases/tag/launcher-v0.4.2"} and ch["beta"]["version"] == "0.5.0" and ch["hold"] is False, ch)
check("a draft or unknown tag is refused", "err=" in act("owner1", "channel.set", "launcher-v0.6.0", channel="beta")[1]
      and "err=" in act("owner1", "channel.set", "launcher-v9.9.9", channel="beta")[1])
check("hold needs HOLD typed", "err=Type HOLD" in act("owner1", "channel.hold", "hold", on="1")[1])
r = act("owner1", "channel.hold", "hold", on="1", note="bad build", confirm="HOLD")
check("hold: on", ok_(r) and feed("channel.json")[2]["hold"] is True)
r = act("owner1", "channel.hold", "hold", on="0", confirm="RELEASE")
check("release the hold", ok_(r) and feed("channel.json")[2]["hold"] is False)
r = act("modadm", "news.add", "new", tag="Launcher 0.5", title="Themes are here", items="Pick a theme\n\nMore to come\n")
news = feed("news.json")[2]
check("news: a post, in the launcher's shape", ok_(r) and news["posts"][0]["tag"] == "LAUNCHER 0.5" and news["posts"][0]["title"] == "THEMES ARE HERE"
      and news["posts"][0]["items"] == ["Pick a theme", "More to come"] and set(news["posts"][0]) == {"id", "date", "tag", "title", "items"})
check("news: brand words refused", "err=Players see this" in act("modadm", "news.add", "new", tag="x", title="Wrath of the Lich King", items="a")[1])
check("news: empty refused", "err=" in act("modadm", "news.add", "new", tag="x", title="", items="")[1])
pid_news = news["posts"][0]["id"]
r = act("modadm", "news.hide", pid_news, confirm=pid_news)
check("news: hide", ok_(r) and feed("news.json")[2]["posts"] == [])

# ---------------------------------------------------------------- themes (the Workshop's "themes" category)
body = req("GET", "/wrath/admin/themes", "modadm")[2]
check("themes: the Workshop's theme packs", "Frost Glass" in body and f"link:{TPID}" in body)
check("listed at once by default (like every Workshop entry)", "link:" + TPID in mods_ids())
os.environ["WU_THEMES_REVIEW"] = "1"
check("WU_THEMES_REVIEW=1: held until approved", "link:" + TPID not in mods_ids() and "link:" + PID in mods_ids(), mods_ids())
check("... and counted as waiting", "<b>1</b><span>Theme packs waiting" in req("GET", "/wrath/admin", "modadm")[2])
r = act("modadm", "link.approve", TPID, "/wrath/admin/themes")
r2 = act("modadm", "link.feature", TPID, "/wrath/admin/themes", on="1")
proj = {p["id"]: p for p in json.loads(req("GET", "/wrath/mods/all.json")[2])["projects"]}
check("approve and feature: in all.json, featured", ok_(r) and ok_(r2) and proj["link:" + TPID]["featured"] is True)
check("reject needs the confirm", "err=" in act("modadm", "link.reject", TPID)[1])
r = act("modadm", "link.reject", TPID, confirm=TPID)
check("reject: out again", ok_(r) and "link:" + TPID not in mods_ids())
del os.environ["WU_THEMES_REVIEW"]
check("a rejected pack stays out with review off too", "link:" + TPID not in mods_ids())

# ---------------------------------------------------------------- reports
body = req("GET", "/wrath/admin/reports", "modadm")[2]
check(".bug reports, escaped", "quest giver &lt;script&gt;alert(1)&lt;/script&gt;" in body and "<script>alert" not in body)
check("message reports: only the reported message", "REPORTED-BODY" in body and "you are &lt;b&gt;bad&lt;/b&gt;" in body
      and "PRIVATE-REPORTER-MESSAGE" not in body and "PRIVATE-LATER-REPLY" not in body and "OLDER-MALLORY-MESSAGE" not in body)
check("message reports: who, reason, the reporter's note", "Mallory" in body and "reported by Bob" in body and "keeps going" in body)
r = act("modadm", "bug.set", "7", "/wrath/admin/reports", status="resolved")
check("resolve a bug: ovadmin bugs set 7 resolved", ok_(r) and soap_log[-1] == "ovadmin bugs set 7 resolved" and bugs[7]["status"] == "resolved")
check("bad bug status refused", "err=" in act("modadm", "bug.set", "7", status="gone")[1])
r = act("modadm", "report.note", "bug:7", text="fixed in the next client")
check("a note on a report", ok_(r) and "fixed in the next client" in req("GET", "/wrath/admin/reports?bugs=all", "modadm")[2])
r = act("modadm", "msg.resolve", "5", "/wrath/admin/reports", outcome="warned")
check("resolve a message report (Social.resolve_report)", ok_(r) and FAKE_SOCIAL.rows[0]["status"] == "done"
      and FAKE_SOCIAL.rows[0]["outcome"] == "warned" and FAKE_SOCIAL.rows[0]["handled_by"] == "Modadm (modadm)")
check("handled reports leave the open list", "REPORTED-BODY" not in req("GET", "/wrath/admin/reports", "modadm")[2]
      and "REPORTED-BODY" in req("GET", "/wrath/admin/reports?msgs=done", "modadm")[2])
r = act("modadm", "msg.reopen", "5")
check("reopen", ok_(r) and FAKE_SOCIAL.rows[0]["status"] == "open")
check("unknown report refused", "err=No such report" in act("modadm", "msg.dismiss", "99")[1])
check("bad report keys refused", "err=Not a report" in act("modadm", "report.note", "x:../1", text="y")[1])

# ---------------------------------------------------------------- health
body = req("GET", "/wrath/admin/health", "modadm")[2]
check("health: SOAP, ov_admin.lua, relay, exports, folders, checker, GitHub", all(x in body for x in (
    "Realm SOAP", "ov_admin.lua on the realm", "Beacons relay listing", "Workshop export", "Admin folder writable",
    "Checker (wu-mod.py)", "GitHub releases API")))
check("health: Autopilot skipped, and why", "Skipped: Autopilot runs on the owner" in body)
ap = os.path.join(T, "last-run.json")
json.dump({"at": "2026-10-29 14:00:00", "ids": ["1063a"], "ok": False, "failed_step": "client"}, open(ap, "w"))
os.environ["WU_AUTOPILOT_STATUS"] = ap
body = req("GET", "/wrath/admin/health", "modadm")[2]
check("health: Autopilot's last run when a copy is reachable", "failed step: client" in body and "1063a" in body)

# ---------------------------------------------------------------- staff
check("staff can't grant", "err=Only the owner" in act("modadm", "staff.grant", "new", account="newbie")[1])
check("newbie is refused before", req("GET", "/wrath/admin", "newbie")[0] == 403)
r = act("owner1", "staff.grant", "new", account="newbie", name="New Helper")
check("the owner grants staff: newbie gets in", ok_(r) and req("GET", "/wrath/admin", "newbie")[0] == 200)
st = os.stat(os.path.join(DATA, "admin", "staff.json")).st_mode & 0o777
check("staff.json is not world-readable", st == 0o640, oct(st))
check("revoke needs the account id typed", "err=Type newbie" in act("owner1", "staff.revoke", "newbie")[1])
r = act("owner1", "staff.revoke", "newbie", confirm="newbie")
check("revoke: refused again", ok_(r) and req("GET", "/wrath/admin", "newbie")[0] == 403)
check("bad account ids refused", "err=" in act("owner1", "staff.grant", "new", account="a b<c>")[1])

# ---------------------------------------------------------------- audit
body = req("GET", "/wrath/admin/audit?action=realm.", "modadm")[2]
check("audit page, filtered", "realm.hide" in body and "flag.set" not in body)
log_ = audit()
check("every action is in the audit log", {"flag.set", "mod.unpublish", "mod.edit", "mod.check", "link.hide", "link.dismiss",
      "ws.approve", "ws.edit", "ws.check", "hub.reject", "hub.rescan", "realm.hide", "realm.official", "realm.flag",
      "channel.set", "channel.hold", "news.add", "news.hide", "link.approve", "link.reject", "bug.set", "report.note",
      "msg.resolve", "hub.delist", "hub.relist", "staff.grant", "staff.revoke"} - {a["action"] for a in log_ if a["ok"]} == set(),
      {"flag.set"} - {a["action"] for a in log_ if a["ok"]})
check("refusals are logged too", any(not a["ok"] and "confirm" in a["note"] for a in log_))
check("nothing was ever deleted on the realm", not any(re.search(r"(?i)\bdelete\b|unpublish|account (delete|set)|\bban\b", c) for c in soap_log))

# ---------------------------------------------------------------- public feeds: no names a player shouldn't see
allfeeds = "".join(req("GET", f"/wrath/leyline/{n}")[2] for n in ("flags.json", "channel.json", "news.json", "realm-overrides.json"))
check("feeds: no game-brand names, no staff ids", not re.search(r"(?i)warcraft|\bwow\b|blizzard|lich king", allfeeds) and "modadm" not in allfeeds
      and "owner1" not in allfeeds)
check("the /wrath/leyline page is unchanged", req("GET", "/wrath/leyline")[0] == 200)

# ---------------------------------------------------------------- rate limits
A.POSTS_PER_MIN, A.IP_PER_MIN, A.PAGES_PER_MIN = LIMITS
A.limits = A._Window(60)
tok = token("modadm")
codes = [req("POST", "/wrath/admin/act", "modadm", {"csrf": tok, "action": "report.note", "target": "bug:6", "text": f"n{i}",
                                                     "back": "/wrath/admin"}, ip=f"10.1.0.{i}")[0] for i in range(A.POSTS_PER_MIN + 1)]
check("at most 30 changes a minute per account", codes[:-1] == [303] * A.POSTS_PER_MIN and codes[-1] == 429, codes)
A.limits = A._Window(60)
codes = [req("GET", "/wrath/admin", None, ip="10.2.0.1")[0] for _ in range(A.IP_PER_MIN + 1)]
check("at most 120 requests a minute per address before sign-in", codes[-1] == 429 and codes[0] == 302)

# ---------------------------------------------------------------- shipping: the signin step and the scripts step
fl = open(os.path.join(STREAM, "fastloop.sh"), encoding="utf-8").read()
bat = open(os.path.join(STREAM, "Update sign-in and warm-up.bat"), encoding="utf-8").read()
sp = open(os.path.join(ROOT, "realm", "Server pass - finder 10 and bug reports.bat"), encoding="utf-8").read()
check("signin step ships admin.py and wu-mod.py, backs them up, puts them back", 'install -m 644 admin.py "$WU/portal/admin.py"' in fl
      and 'cp -p "$BK/admin.py" "$WU/portal/admin.py"' in fl and 'install -m 644 wu-mod.py "$WU/portal/wu-mod.py"' in fl
      and 'set "LINKS=%LINKS% admin.py"' in bat and all(" %s " % n in re.search(r"\$\(ls ([^)]*)\)", bat).group(1) + " " for n in ("admin.py", "wu-mod.py"))
      and subprocess.run(["bash", "-n", os.path.join(STREAM, "fastloop.sh")]).returncode == 0)
check("scripts step ships ov_admin.lua", 'copy /y "custom\\lua_scripts\\ov_admin.lua"' in sp)

shutil.rmtree(T, ignore_errors=True)
print(f"{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
