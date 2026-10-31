"""Leyline profiles and the unified sign-in (stream/profiles.py) through the real portal (stream/wrath_portal.py) with the
real social.py (names, tags, launcher tokens), forum.py (avatars on posts), hub.py (the look) and admin.py (the Profiles
tab), against a fake website sign-in (/api/me, /api/play and its /login page, whose buttons decide which ways show).

Covers: the chooser (Hero Key, Google, Discord; a way the website doesn't offer is hidden, a dead website falls back),
the hand-over (our ly_next and the website's wr_next cookies, HttpOnly, Secure, SameSite=Lax), safe "next" addresses,
the first-time profile step (form token, cross-site and Origin checks, Skip, saving name, picture and bio, the brand and
word rules), signed-in shortcuts, the launcher link page's sign-in (chooser, or straight to a way with ?via=), the
pictures (presets, a player's by public id, cache headers, no script), the launcher's JSON (GET me, POST profile,
GET ways, the CSRF rule for cookies), the profile page (ways to sign in, sign out), the admin console's resets (audited,
the old value kept), the forum's avatars and the deploy lists.

    python3 -I stream/tests/test_profiles.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "stream", "wrath_portal.py"))
STREAM = os.path.dirname(PORTAL)
TMP = tempfile.mkdtemp(prefix="wu-profiles-")
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra!r}"[:600] if extra and not cond else ""))
    fails += 0 if cond else 1


ACCOUNTS = {"alice": ("alice", "Alice", "WR000001"), "bob": ("bob", "Bob", "WR000002"), "staff1": ("staff1", "Mod Sam", "WR000003")}
LOGIN = {"html": '<a href="/auth/google/start">Google</a><a href="/auth/discord/start">Discord</a><a class="btn" href="/key">Key</a>',
         "down": False}
login_reads = []


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/login":
            login_reads.append(self.headers.get("Cookie", ""))
            if LOGIN["down"]:
                self.send_response(502); self.send_header("Content-Length", "0"); self.end_headers(); return
            b = LOGIN["html"].encode()
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        m = re.search(r"wr_session=(\w+)", self.headers.get("Cookie", ""))
        a = ACCOUNTS.get(m.group(1)) if m else None
        if not a:
            self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = {"/api/me": {"id": a[0], "display_name": a[1]}, "/api/play": {"user": a[2], "pass": "x" * 16}}[self.path]
        b = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


SITE = serve(Site)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL=f"http://127.0.0.1:{SITE}",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_PORTAL_DATA=TMP, WU_HOST_DIR=os.path.join(TMP, "hosted"),
                  WU_RELAY_LISTING="http://127.0.0.1:9/none", WU_ADMIN_STAFF="staff1", WU_ADMIN_OWNERS="", WU_ADMIN_GM_LEVEL="0",
                  PUBLIC_HOST="play.example", WU_HUB_FRONT="0")
os.environ.pop("WU_FORM_SECRET", None)
spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.ac_soap = lambda cmd: ""
check("the portal loads profiles.py", wp.profiles is not None)
S = wp.social.setup(start_thread=False)
PR = wp.profiles.setup()
F = wp.forum.setup()
PM = wp.profiles
check("the store opens in WU_PORTAL_DATA (profiles.sqlite3, 0600)", PR is not None
      and (os.stat(os.path.join(TMP, "profiles.sqlite3")).st_mode & 0o777) == 0o600)
wp.browse_limit.hit = lambda *a, **k: True
wp.admin.POSTS_PER_MIN = wp.admin.IP_PER_MIN = wp.admin.PAGES_PER_MIN = 10 ** 6
PAGE = serve(wp.PageHandler)
BRAND = re.compile(r"(?i)world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|\bwow\b")


def req(method, path, who=None, form=None, origin="https://play.example", sfs="same-origin", headers=None, cookies=""):
    c = http.client.HTTPConnection("127.0.0.1", PAGE, timeout=30)
    h = {"X-Forwarded-For": "10.0.0.7"}
    ck = [f"wr_session={who}"] if who else []
    if cookies:
        ck.append(cookies)
    if ck:
        h["Cookie"] = "; ".join(ck)
    body = None
    if form is not None:
        body = (form if isinstance(form, (bytes, str)) else urllib.parse.urlencode(form))
        body = body.encode() if isinstance(body, str) else body
        h["Content-Type"] = "application/x-www-form-urlencoded"
        if origin is not None:
            h["Origin"] = origin
        if sfs:
            h["Sec-Fetch-Site"] = sfs
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    hd = {}
    for k, v in r.getheaders():
        hd.setdefault(k, []).append(v)
    out = (r.status, {k: v[0] for k, v in hd.items()}, r.read().decode("utf-8", "replace"), hd)
    c.close()
    return out


def tok(who, path, cookies=""):
    st, _, body, _ = req("GET", path, who, cookies=cookies)
    m = re.search(r'name="t" value="([0-9a-f]{32})"', body)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- the ways the website offers
w = PM.ways(force=True)
check("ways: read from the website's /login (no cookie sent): Hero Key, Google, Discord", w == {"herokey": True, "google": True, "discord": True}
      and login_reads and login_reads[-1] == "", (w, login_reads))
n = len(login_reads)
PM.ways(); PM.ways()
check("ways: cached (the sign-in page is read every few minutes, not per request)", len(login_reads) == n)
LOGIN["html"] = '<a href="/auth/google/start">Google</a><a href="/key">Key</a>'
check("ways: Discord off on the website (DISCORD_SIGNIN=off / no client): no Discord", PM.ways(force=True)["discord"] is False)
LOGIN["down"] = True
check("ways: the website down: Hero Key and Google (as for months), no Discord", PM.ways(force=True) == {"herokey": True, "google": True, "discord": False})
LOGIN["down"] = False
LOGIN["html"] = '<a href="/auth/google/start">Google</a><a href="/key">Key</a>'
PM.ways(force=True)

# ---------------------------------------------------------------- phase 1: the chooser
st, hd, body, _ = req("GET", "/wrath/signin?next=%2Fwrath%2Fleyline%2Fforum")
check("chooser: 200, the steps (Sign in, Your profile, Play), step 1 current", st == 200 and 'class="pf-steps"' in body
      and re.search(r'data-n="1" class="on" aria-current="step"><span>Sign in', body) and "Your profile" in body, body[:400])
check("chooser: Hero Key first, then Google; Discord hidden while the website doesn't offer it",
      'href="/wrath/signin/go/herokey?next=%2Fwrath%2Fleyline%2Fforum"' in body and "/wrath/signin/go/google?" in body
      and "/wrath/signin/go/discord" not in body and body.index("go/herokey") < body.index("go/google"))
check("chooser: no script, the hub's look, noindex, never a game or company name", "<script" not in body and 'class="hb-top"' in body
      and hd.get("X-Robots-Tag", "").startswith("noindex") and not BRAND.search(re.sub(r"<[^>]+>", " ", body)))
check("chooser: More ways (the website's own page, guest play) keeps the next", 'href="/login?next=%2Fwrath%2Fleyline%2Fforum"' in body)
LOGIN["html"] += '<a href="/auth/discord/start">Discord</a>'
PM.ways(force=True)
st, hd, body, _ = req("GET", "/wrath/signin")
check("chooser: Discord shows once the website offers it", "/wrath/signin/go/discord?next=%2Fwrath" in body and "Continue with Discord" in body)

# the hand-over
st, hd, body, raw = req("GET", "/wrath/signin/go/google?next=%2Fwrath%2Fleyline%2Fforum")
ck = raw.get("Set-Cookie", [])
check("go/google: on to the website's Google start", st == 302 and hd.get("Location") == "/auth/google/start", (st, hd))
check("go/google: ly_next (Path=/wrath) and the website's wr_next = /wrath/signin/welcome (Path=/), both HttpOnly Secure Lax 15 min",
      any(c.startswith("ly_next=/wrath/leyline/forum;") and "Path=/wrath;" in c for c in ck)
      and any(c.startswith("wr_next=/wrath/signin/welcome;") and "Path=/;" in c for c in ck)
      and all("HttpOnly" in c and "Secure" in c and "SameSite=Lax" in c and "Max-Age=900" in c for c in ck), ck)
st, hd, _, _ = req("GET", "/wrath/signin/go/herokey?next=%2Fwrath")
check("go/herokey: the website's Hero Key page", st == 302 and hd.get("Location") == "/key")
st, hd, _, _ = req("GET", "/wrath/signin/go/discord?next=%2Fwrath")
check("go/discord: the website's Discord start (when offered)", st == 302 and hd.get("Location") == "/auth/discord/start")
st, hd, _, _ = req("GET", "/wrath/signin/go/evil?next=%2Fwrath")
check("go/<unknown>: back to the chooser", st == 302 and hd.get("Location", "").startswith("/wrath/signin?next="))
for bad in ("https://evil.example/", "//evil.example/x", "/wrathx", "/\\evil", "/wrath/signin", "/login", "javascript:alert(1)"):
    check(f"safe next: {bad!r} becomes /wrath", PM.safe_next(bad) == "/wrath", PM.safe_next(bad))
check("safe next: our own pages stay", PM.safe_next("/wrath/link?code=BCDF-GHJK") == "/wrath/link?code=BCDF-GHJK"
      and PM.safe_next("/wrath/leyline/forum/t/3") == "/wrath/leyline/forum/t/3")

# ---------------------------------------------------------------- phase 2: the first-time profile
st, hd, body, _ = req("GET", "/wrath/signin/welcome", "alice", cookies="ly_next=/wrath/leyline/forum")
check("welcome: first time: the profile step (name, 13 pictures, bio, Skip)", st == 200 and "Welcome, Alice" in body
      and 'data-n="2" class="on"' in body and body.count('name="avatar"') == 13 and 'name="bio"' in body and "Skip for now" in body, body[:300])
check("welcome: the pictures are ours (/wrath/avatar), the name field is filled in", 'src="/wrath/avatar/p/star.svg"' in body
      and 'value="Alice"' in body)
st, hd, body, _ = req("GET", "/wrath/signin/welcome", None, cookies="ly_next=/wrath")
check("welcome: signed out (the sign-in didn't finish): the chooser with a note", st == 200 and "finish. Try again" in body and "go/herokey" in body)
t = tok("alice", "/wrath/signin/welcome", "ly_next=/wrath/leyline/forum")
form = {"t": t, "do": "save", "name": "Alice", "avatar": "moon", "bio": "I host a realm.\nfuck this Warcraft-free bio, WoW"}
st, hd, body, _ = req("POST", "/wrath/signin/welcome", "alice", dict(form, t="0" * 32), cookies="ly_next=/wrath/leyline/forum")
check("welcome POST: a wrong form token is refused", st == 403 and "timed out" in body)
st, _, _, _ = req("POST", "/wrath/signin/welcome", "alice", form, origin="https://evil.example", cookies="ly_next=/wrath/leyline/forum")
check("welcome POST: another Origin is refused", st == 403)
st, _, _, _ = req("POST", "/wrath/signin/welcome", "alice", form, sfs="cross-site", cookies="ly_next=/wrath/leyline/forum")
check("welcome POST: cross-site is refused", st == 403)
st, _, body, _ = req("POST", "/wrath/signin/welcome", "alice", dict(form, name="WoWAlice"), cookies="ly_next=/wrath/leyline/forum")
check("welcome POST: a name with a game name is refused, the form comes back filled in", st == 400 and "Pick another name" in body
      and "I host a realm." in body and PR.get("WR000001")["setup"] is False)
st, _, body, _ = req("POST", "/wrath/signin/welcome", "alice", dict(form, avatar="../x"), cookies="ly_next=/wrath/leyline/forum")
check("welcome POST: an unknown picture is refused", st == 400 and "Pick one of the pictures" in body)
st, hd, _, raw = req("POST", "/wrath/signin/welcome", "alice", dict(form, name="Alice_R"), cookies="ly_next=/wrath/leyline/forum")
p = PR.get("WR000001")
check("welcome POST: saved, then back where they came from (ly_next cleared)", st == 303 and hd.get("Location") == "/wrath/leyline/forum"
      and any(c.startswith("ly_next=;") and "Max-Age=0" in c for c in raw.get("Set-Cookie", [])), (st, hd))
check("welcome POST: the picture, the bio (words starred, game names replaced, line break kept), setup done",
      p["avatar"] == "moon" and p["setup"] and p["bio"].startswith("I host a realm.\n") and "****" in p["bio"]
      and not BRAND.search(p["bio"]), p)
check("welcome POST: the name is social.py's (with its #tag)", S.profile("WR000001")["name"] == "Alice_R")
for nm in ("Lich_King", "War.craft", "WoWAlice", "Blizzard9", "wow", "World-of-Warcraft"):
    check(f"names: {nm!r} refused", PM.name_problem(nm) != "")
for nm in ("Wowza", "Snowy", "Kingsley", "Orion_7"):
    check(f"names: {nm!r} fine", PM.name_problem(nm) == "")
check("history: bio, picture and name changes kept", {x["field"] for x in PR.history("WR000001")} >= {"bio", "avatar", "name"})
st, hd, _, _ = req("GET", "/wrath/signin/welcome", "alice", cookies="ly_next=/wrath/realms")
check("welcome: once set up, straight on to next", st == 302 and hd.get("Location") == "/wrath/realms")
st, hd, _, _ = req("GET", "/wrath/signin?next=%2Fwrath%2Fmods", "alice")
check("chooser: signed in and set up: straight on to next", st == 302 and hd.get("Location") == "/wrath/mods")
st, hd, _, _ = req("GET", "/wrath/signin?next=%2Fwrath%2Fmods", "bob")
check("chooser: signed in, never set up: the profile step", st == 302 and hd.get("Location") == "/wrath/signin/welcome")
t = tok("bob", "/wrath/signin/welcome", "ly_next=/wrath")
st, hd, _, _ = req("POST", "/wrath/signin/welcome", "bob", {"t": t, "do": "skip"}, cookies="ly_next=/wrath")
check("welcome: Skip for now marks it done, nothing else changes", st == 303 and PR.get("WR000002")["setup"] and PR.get("WR000002")["avatar"] == "")

# ---------------------------------------------------------------- the launcher's link page
st, hd, _, _ = req("GET", "/wrath/link?code=BCDF-GHJK")
check("link page signed out: the Leyline chooser, coming back to the code", st == 302
      and hd.get("Location") == "/wrath/signin?next=" + urllib.parse.quote("/wrath/link?code=BCDF-GHJK", safe=""), hd)
st, hd, _, _ = req("GET", "/wrath/link?code=BCDF-GHJK&via=google")
check("link page ?via=google (the launcher's button): straight to that way", st == 302
      and hd.get("Location") == "/wrath/signin/go/google?next=" + urllib.parse.quote("/wrath/link?code=BCDF-GHJK", safe=""), hd)
st, hd, _, _ = req("GET", "/wrath/link?code=BCDF-GHJK&via=evil")
check("link page ?via=<unknown>: the chooser", hd.get("Location", "").startswith("/wrath/signin?next="))
st, hd, body, _ = req("GET", "/wrath/signin?next=" + urllib.parse.quote("/wrath/link?code=BCDF-GHJK", safe=""))
check("chooser for the launcher: says so", "link the Leyline launcher" in body)
d = S.device_start("10.0.0.9")
st, hd, _, _ = req("GET", "/wrath/signin?next=" + urllib.parse.quote("/wrath/link?code=" + d["user_code"], safe=""), "bob")
check("chooser for the launcher, signed in: on to the code (the launcher asks for the profile itself)", st == 302
      and hd.get("Location") == "/wrath/link?code=" + d["user_code"])

st, hd, _, _ = req("GET", "/wrath/signin/welcome", "staff1", cookies="ly_next=/wrath/link?code=" + d["user_code"])
check("welcome for the launcher's code, never set up: straight on to the code", st == 302
      and hd.get("Location") == "/wrath/link?code=" + d["user_code"] and not PR.get("WR000003")["setup"])

# ---------------------------------------------------------------- pictures
st, hd, body, _ = req("GET", "/wrath/avatar/p/star.svg")
check("preset: an SVG, cached a week, no script", st == 200 and hd.get("Content-Type") == "image/svg+xml"
      and "max-age=604800" in hd.get("Cache-Control", "") and "<script" not in body and body.startswith("<svg"))
st, hd2, _, _ = req("GET", "/wrath/avatar/p/star.svg", headers={"If-None-Match": hd.get("ETag", "")})
check("preset: ETag answers 304", st == 304)
check("preset: every one draws", all(req("GET", f"/wrath/avatar/p/{x[0]}.svg")[0] == 200 for x in PM.PRESETS))
check("preset: an unknown one is 404", req("GET", "/wrath/avatar/p/nope.svg")[0] == 404 and req("GET", "/wrath/avatar/p/../x")[0] == 404)
pid_a = S.profile("WR000001")["pid"]
url = PM.avatar_url("WR000001")
st, hd, body, _ = req("GET", url)
check("a player's picture by public id: their preset, cached a day with ?v", st == 200 and 'aria-label="Moon"' in body
      and "max-age=86400" in hd.get("Cache-Control", "") and url.startswith(f"/wrath/avatar/u/{pid_a}.svg?v="), url)
st, hd, body, _ = req("GET", f"/wrath/avatar/u/{S.profile('WR000002')['pid']}.svg")
check("no picture chosen: the initial; without ?v five minutes", st == 200 and ">B</text>" in body and "max-age=300" in hd.get("Cache-Control", ""))
check("an unknown public id is 404", req("GET", "/wrath/avatar/u/zzzzzzzzzz.svg")[0] == 404)

# ---------------------------------------------------------------- the launcher's JSON
d = S.device_start("10.0.0.8")
S.device_answer(d["user_code"].replace("-", ""), "WR000001", True)
S.devices[d["user_code"].replace("-", "")]["polled"] = 0
token = S.device_poll(d["device_code"])["token"]
B = {"Authorization": f"Bearer {token}"}


def jget(path, **kw):
    st, hd, body, _ = req("GET", path, **kw)
    try:
        return st, json.loads(body)
    except ValueError:
        return st, {}


def jpost(path, doc, headers=None, who=None, origin="https://play.example"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE, timeout=30)
    h = {"X-Forwarded-For": "10.0.0.7", "Content-Type": "application/json", **(headers or {})}
    if who:
        h["Cookie"] = f"wr_session={who}"
        h["Origin"] = origin
    c.request("POST", path, body=json.dumps(doc).encode(), headers=h)
    r = c.getresponse()
    b = r.read().decode()
    c.close()
    try:
        return r.status, json.loads(b)
    except ValueError:
        return r.status, {}


st, me = jget("/wrath/api/social/me", headers=B)
check("GET me (launcher): the profile (bio, picture, absolute picture address, setup)", st == 200 and me["me"]["profile"]["avatar"] == "moon"
      and me["me"]["profile"]["setup"] is True and me["me"]["profile"]["avatar_url"].startswith(f"https://play.example/wrath/avatar/u/{pid_a}.svg?v="), me)
check("GET me: the presets (absolute), the ways, the manage page", len(me["avatars"]) == 12
      and me["avatars"][0]["url"] == "https://play.example/wrath/avatar/p/star.svg" and me["ways"]["discord"] is True
      and me["manage_url"] == "https://play.example/wrath/profile")
st, ways = jget("/wrath/api/social/ways")
check("GET ways: no sign-in needed", st == 200 and ways == {"herokey": True, "google": True, "discord": True})
st, out = jpost("/wrath/api/social/profile", {"bio": "Hello there", "avatar": "gem", "setup": True}, B)
check("POST profile (launcher): bio and picture saved, the new profile back", st == 200 and out["me"]["profile"]["avatar"] == "gem"
      and PR.get("WR000001")["bio"] == "Hello there")
v1 = PR.get("WR000001")["ver"]
st, out = jpost("/wrath/api/social/profile", {"avatar": "evil"}, B)
check("POST profile: an unknown picture is refused", st == 400 and "picture" in out.get("error", ""))
st, out = jpost("/wrath/api/social/profile", {"bio": "x" * 700}, B)
check("POST profile: an overlong bio is refused", st == 400)
st, out = jpost("/wrath/api/social/profile", {"bio": 5}, B)
check("POST profile: a bio that isn't text is refused", st == 400)
st, out = jpost("/wrath/api/social/profile", {"name": "Lich King", "bio": "changed?"}, B)
check("POST profile: a refused name changes nothing (not even the bio)", st == 400 and PR.get("WR000001")["bio"] == "Hello there")
st, out = jpost("/wrath/api/social/profile", {"name": "AliceR", "avatar": ""}, B)
check("POST profile: a new name and back to the initial; the picture's version moves on", st == 200 and out["me"]["name"] == "AliceR"
      and out["me"]["profile"]["avatar"] == "" and PR.get("WR000001")["ver"] > v1)
st, out = jpost("/wrath/api/social/profile", {"bio": "x"}, who="alice")
check("POST profile with the cookie: needs the CSRF header", st == 403)
st, me2 = jget("/wrath/api/social/me", who="alice")
st, out = jpost("/wrath/api/social/profile", {"bio": "From the web"}, {"X-Leyline-CSRF": me2.get("csrf", "")}, who="alice")
check("POST profile with the cookie and the CSRF header: saved", st == 200 and PR.get("WR000001")["bio"] == "From the web")
st, out = jpost("/wrath/api/social/profile", {"bio": "x"}, {"X-Leyline-CSRF": me2.get("csrf", "")}, who="alice", origin="https://evil.example")
check("POST profile from another Origin: refused", st == 403)

# ---------------------------------------------------------------- the profile page
st, hd, _, _ = req("GET", "/wrath/profile")
check("profile page signed out: the chooser, coming back here", st == 302 and hd.get("Location") == "/wrath/signin?next=%2Fwrath%2Fprofile")
st, hd, body, _ = req("GET", "/wrath/profile", "alice")
check("profile page: who is signed in (picture, name#tag), the form, the ways, sign out", st == 200 and "AliceR" in body
      and "#" + S.profile("WR000001")["tag"] in body and 'action="/logout"' in body and "/account/key" in body
      and "/auth/google/start?link=1" in body and "/auth/discord/start?link=1" in body and "/wrath/link" in body and "<script" not in body)
check("profile page: never a game or company name", not BRAND.search(re.sub(r"<[^>]+>", " ", body)))
t = tok("alice", "/wrath/profile")
st, hd, _, _ = req("POST", "/wrath/profile", "alice", {"t": t, "name": "AliceR", "avatar": "sun", "bio": "Sunny"})
check("profile page POST: saved (303 to ?saved=1)", st == 303 and hd.get("Location") == "/wrath/profile?saved=1"
      and PR.get("WR000001")["avatar"] == "sun")
st, _, body, _ = req("GET", "/wrath/profile?saved=1", "alice")
check("profile page: Saved.", "Saved." in body and "Sunny" in body)
st, _, body, _ = req("POST", "/wrath/profile", "alice", {"t": t, "name": "x", "avatar": "sun", "bio": ""})
check("profile page POST: a bad name shows why", st == 400 and "2 to 24" in body)
st, _, body, _ = req("POST", "/wrath/profile", None, {"t": t, "name": "x"})
check("profile page POST signed out: to the sign-in", st == 303)
LOGIN["html"] = '<a href="/auth/google/start">Google</a><a href="/key">Key</a>'
PM.ways(force=True)
st, hd, body, _ = req("GET", "/wrath/profile", "alice")
check("profile page: no Link Discord while the website doesn't offer it", "/auth/discord/start" not in body)

# ---------------------------------------------------------------- the forum shows the picture
tid = F.new_thread("WR000001", "general", "Hello from Alice", "First post here")
st, _, body, _ = req("GET", f"/wrath/leyline/forum/t/{tid}")
check("forum: the poster's picture beside their name", st == 200 and re.search(r'<img class="fm-av" src="/wrath/avatar/u/' + pid_a + r'\.svg\?v=\d+"', body), body[:200])
st, _, body, _ = req("GET", "/wrath/leyline/forum/new")
check("forum signed out: Sign in goes to the Leyline sign-in", st == 302 or "/wrath/signin?next=" in body)

# ---------------------------------------------------------------- the admin console
user = {"account": "WR000003", "name": "Mod Sam", "role": "staff", "session": "s"}
body = wp.admin.profiles_page(user, {})
check("admin Profiles: the recent profiles with their resets", "AliceR" in body and "profile.reset.avatar" in body and "profile.reset.bio" in body)
body = wp.admin.profiles_page(user, {"q": ["AliceR#" + S.profile("WR000001")["tag"]]})
check("admin Profiles: find by Name#tag", "AliceR" in body and "Bob" not in body)
ok, msg = wp.admin.run_action(user, {"action": "profile.reset.avatar", "target": "WR000001"})
check("admin: reset the picture (audited), the old one kept in the history", ok and PR.get("WR000001")["avatar"] == ""
      and any(x["field"] == "avatar" and x["old"] == "sun" and x["by"] == "staff:WR000003" for x in PR.history("WR000001"))
      and any(r.get("action") == "profile.reset.avatar" for r in wp.admin.audit_tail(20)), msg)
ok, msg = wp.admin.run_action(user, {"action": "profile.reset.bio", "target": "WR000001"})
check("admin: reset the bio", ok and PR.get("WR000001")["bio"] == "")
ok, msg = wp.admin.run_action(user, {"action": "profile.reset.name", "target": "WR000001"})
check("admin: reset the name needs the typed confirm", not ok and S.profile("WR000001")["name"] == "AliceR")
ok, msg = wp.admin.run_action(user, {"action": "profile.reset.name", "target": "WR000001", "confirm": "WR000001"})
check("admin: reset the name to Player", ok and S.profile("WR000001")["name"] == "Player")
ok, msg = wp.admin.run_action(user, {"action": "profile.reset.bio", "target": "nope!"})
check("admin: a bad target is refused", not ok)
check("admin: the Profiles tab is listed", ("profiles", "Profiles") in wp.admin.TABS)

# ---------------------------------------------------------------- the nav and the deploy
check("site nav: Sign in goes to the Leyline sign-in", "/wrath/signin?next=%2Fwrath" in wp.site_nav("", False)
      and "/wrath/profile" in wp.site_nav("", True))
fl = open(os.path.join(STREAM, "fastloop.sh"), encoding="utf-8").read()
bat = open(os.path.join(STREAM, "Update sign-in and warm-up.bat"), encoding="utf-8", errors="replace").read()
check("deploy: fastloop.sh backs up, puts back and installs profiles.py", fl.count("profiles.py") >= 3)
check("deploy: the .bat sends profiles.py", "profiles.py" in bat)

print(f"{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
