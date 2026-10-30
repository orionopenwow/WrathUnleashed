"""Community projects in the Workshop (stream/projects.py + stream/workshop.py through wrath_portal.py):
add a link signed in, listed at once, credited everywhere, report and hide, /wrath/mods/all.json.
Fake website (/api/me) and fake GitHub / GitLab / Codeberg APIs on 127.0.0.1: no network.

    python3 -I stream/tests/test_projects.py stream/wrath_portal.py
"""
import html, http.client, importlib.util, io, json, logging, os, re, shutil, sys, tempfile, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
STREAM = os.path.dirname(PORTAL)
ROOT = os.path.dirname(STREAM)

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

T = tempfile.mkdtemp(prefix="wu-projects-")
PUB = os.path.join(T, "mods"); DATA = os.path.join(T, "data")
os.makedirs(PUB); os.makedirs(DATA)
shutil.copy(os.path.join(ROOT, "mods", "catalog.json"), PUB)
json.dump({"installed": {"pings": "0.1.0"}}, open(os.path.join(PUB, "installed.json"), "w"))
TOKEN = "ghp_TESTSECRET0123456789abcdef"

# ---------------------------------------------------------------- fakes
api_seen = []
GH = {
    "/repos/alice/frame-kit": {"name": "frame-kit", "description": "Unit frames, rebuilt.", "license": {"spdx_id": "MIT"},
                               "stargazers_count": 42, "pushed_at": "2026-10-20T10:00:00Z",
                               "owner": {"login": "alice", "html_url": "https://github.com/alice"}, "private": False},
    "/repos/mallory/evil": {"name": "<script>alert(1)</script>", "description": "\"><img src=x onerror=1>",
                            "license": None, "stargazers_count": 1, "pushed_at": "2026-01-01T00:00:00Z",
                            "owner": {"login": "<b>mal</b>", "html_url": "javascript:alert(1)"}},
    "/repos/carol/wow-tools": {"name": "wow-tools", "description": "Tools for World of Warcraft by Blizzard fans",
                               "license": {"spdx_id": "GPL-3.0-only"}, "stargazers_count": 7,
                               "pushed_at": "2026-09-01T00:00:00Z", "owner": {"login": "carol", "html_url": "https://github.com/carol"}},
}
for i in range(1, 6):
    GH[f"/repos/bob/proj{i}"] = {"name": f"proj{i}", "description": "", "license": {"spdx_id": "Apache-2.0"},
                                 "stargazers_count": i, "pushed_at": "2026-10-01T00:00:00Z",
                                 "owner": {"login": "bob", "html_url": "https://github.com/bob"}}
GL = {"/projects/dave%2Fsub%2Fraidtimer": {"name": "raidtimer", "description": "Boss timers", "star_count": 3,
                                          "last_activity_at": "2026-10-10T00:00:00Z", "visibility": "public",
                                          "license": {"nickname": "MPL-2.0", "name": "Mozilla Public License 2.0"},
                                          "namespace": {"name": "Dave", "path": "dave", "web_url": "https://gitlab.com/dave"}}}
CB = {"/repos/erin/coremod": {"name": "coremod", "description": "A realm module", "stars_count": 5, "licenses": ["AGPL-3.0"],
                              "updated_at": "2026-10-11T00:00:00Z", "owner": {"login": "erin", "html_url": "https://codeberg.org/erin"}}}


class Api(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split("?")[0]
        api_seen.append((path, self.headers.get("Authorization", "")))
        if path.startswith("/gh/repos/slow/"):
            time.sleep(1.5)
        doc = {"/gh": GH, "/gl": GL, "/cb": CB}.get(path[:3], {}).get(path[3:])
        body = json.dumps(doc or {"message": "Not Found"}).encode()
        try:
            self.send_response(200 if doc else 404); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except OSError:
            pass


USERS = {"alice": {"id": "hk-alice", "display_name": "Alice"}, "bob": {"id": "hk-bob", "display_name": "Bob <i>"},
         "admin": {"id": "hk-admin", "display_name": "Admin"}, "carol": {"id": 77, "display_name": "Carol"},
         "frank": {"id": "hk-frank", "display_name": "Frank"}, "gina": {"id": "hk-gina", "display_name": "Gina"}}


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        sess = re.search(r"wr_session=([a-z]+)", self.headers.get("Cookie", ""))
        who = sess.group(1) if sess else ""
        if who == "down":
            self.send_response(500); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = USERS.get(who)
        body = json.dumps(doc or {"error": "signed out"}).encode()
        self.send_response(200 if doc else 401); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


def serve(h):
    s = ThreadingHTTPServer(("127.0.0.1", 0), h); s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s
api, site = serve(Api), serve(Site)
A = f"http://127.0.0.1:{api.server_address[1]}"

os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/",
                  PORTAL_URL=f"http://127.0.0.1:{site.server_address[1]}", WU_STREAM="0", STREAM_HOST="wrath.example",
                  PUBLIC_HOST="play.example", WU_MODS_DIR=PUB, WU_PORTAL_DATA=DATA, WU_MODS_ADMINS="hk-admin",
                  WU_GITHUB_API=A + "/gh", WU_GITLAB_API=A + "/gl", WU_CODEBERG_API=A + "/cb", WU_GITHUB_TOKEN=TOKEN,
                  WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json", NO_PROXY="127.0.0.1,localhost",
                  no_proxy="127.0.0.1,localhost")
logbuf = io.StringIO()
logging.basicConfig(stream=logbuf, level=logging.DEBUG)
spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.community_realms = lambda: ([], True)
wp.realm_status = lambda: {"online": True, "players": 1, "bots": 0}
Wk = wp.workshop
check("projects.py loaded with the Workshop", Wk is not None and Wk.projects is not None and Wk.projects.dir == DATA)
Wk.projects.meta.timeout = 0.5

# the one category list: mods/categories.json (the Workshop's own), for the form, the filters and all.json
cj = json.load(open(os.path.join(ROOT, "mods", "categories.json")))
CAT_IDS = [c["id"] for c in cj["categories"]]
check("13 categories from mods/categories.json", len(CAT_IDS) == 13 and [c["id"] for c in Wk.categories()[0]] == CAT_IDS)

srv = serve(wp.PageHandler)
PORT = srv.server_address[1]
ip_n = [0]
def req(method, path, who="", form=None, ip=None, raw=None):
    if ip is None:
        ip_n[0] += 1; ip = f"198.51.100.{ip_n[0] % 250}"
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"X-Forwarded-For": ip}
    if who:
        h["Cookie"] = f"wr_session={who}"
    body = raw if raw is not None else (urllib.parse.urlencode(form).encode() if form is not None else None)
    if body is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=body, headers=h); r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode("utf-8", "replace")

def token(who, path="/wrath/mods/submit", act=""):
    """The form token of the form posting to <path>[/<act>] on that page."""
    target = path + ("/" + act if act else "")
    m = re.search(r'action="' + re.escape(target) + r'"><input type="hidden" name="t" value="([0-9a-f]+)"', req("GET", path, who)[2])
    return m.group(1) if m else ""

def submit(who, url, cat="addons", builds="3.3.5a", desc="A tidy set of unit frames for raids.", tok=None):
    return req("POST", "/wrath/mods/submit", who, {"t": token(who) if tok is None else tok, "url": url,
                                                    "category": cat, "builds": builds, "description": desc})

def records():
    return [json.loads(l) for l in open(os.path.join(DATA, "projects.jsonl"))] if os.path.exists(os.path.join(DATA, "projects.jsonl")) else []

def comm_cards(h):
    return re.findall(r'<a class="wk-card" href="/wrath/mods/p/([0-9a-f]{12})"', h)

def err(h):
    m = re.search(r'<p class="wk-msg" role="alert">([^<]*)</p>', h)
    return html.unescape(m.group(1)) if m else ""

# ---------------------------------------------------------------- sign-in required
st, _, h = req("GET", "/wrath/mods/submit")
check("signed out: a sign-in button, no form", st == 200 and "/login?next=%2Fwrath%2Fmods%2Fsubmit" in h and "<form class=\"wk-form\"" not in h)
st, _, h = req("POST", "/wrath/mods/submit", "", {"url": "https://github.com/alice/frame-kit", "category": "interface",
                                                  "builds": "any", "description": "Unit frames, rebuilt nicely."})
check("signed out: POST refused, nothing stored", st == 403 and records() == [])
st, _, h = req("GET", "/wrath/mods/submit", "nobody")
check("an expired session is signed out", "Sign in to add a link" in h)
st, _, h = req("GET", "/wrath/mods/submit", "down")
check("website down: a clear 503", st == 503 and "isn't answering" in h)
st, _, h = req("GET", "/wrath/mods/submit", "alice")
check("signed in: the form", st == 200 and 'action="/wrath/mods/submit"' in h and 'name="url"' in h and h.count("<option value=") == 14
      and all(f'<option value="{c}">' in h for c in CAT_IDS)
      and all(f'value="{b}"' in h for b in ("3.3.5a", "1.12", "both", "any")))
st, _, h = submit("alice", "https://github.com/alice/frame-kit", tok="")
check("no form token: refused", st == 400 and records() == [])
st, _, h = submit("alice", "https://github.com/alice/frame-kit", tok=token("bob"))
check("another session's token: refused", st == 400 and records() == [])
check("POST elsewhere: 405", req("POST", "/wrath/realms", "alice", {})[0] == 405)
check("a huge body: 413", req("POST", "/wrath/mods/submit", "alice", raw=b"x" * 5000)[0] == 413)

# ---------------------------------------------------------------- a good submission
st, hd, h = submit("alice", "https://github.com/alice/frame-kit/tree/main/src", builds="both")
recs = records()
r = recs[0] if recs else {}
check("valid GitHub link: added and redirected", st == 303 and hd.get("Location", "").startswith(f"/wrath/mods/p/{r.get('id')}?added=1"), (st, hd, err(h)))
check("record: canonical url, title, owner, licence, stars, push",
      r.get("url") == "https://github.com/alice/frame-kit" and r.get("title") == "frame-kit" and r.get("author") == "alice"
      and r.get("licence") == "MIT" and r.get("stars") == 42 and r.get("last_push") == "2026-10-20T10:00:00Z"
      and r.get("author_url") == "https://github.com/alice", r)
check("record: category, builds, description, who, when", r.get("category") == "addons" and r.get("builds") == ["3.3.5a", "1.12"]
      and r.get("description") == "A tidy set of unit frames for raids." and r.get("submitted_by") == "Alice"
      and r.get("submitter") == "hk-alice" and r.get("submitted_at", "").endswith("Z") and r.get("last_checked"))
check("GitHub API asked with the optional token", any(p == "/gh/repos/alice/frame-kit" and a == "Bearer " + TOKEN for p, a in api_seen))
st, _, h = req("GET", f"/wrath/mods/p/{r['id']}?added=1")
check("project page: credits, link, thanks", st == 200 and "frame-kit" in h and 'href="https://github.com/alice/frame-kit"' in h
      and "MIT" in h and 'href="https://github.com/alice"' in h and "Added: it" in h and "Nothing is hosted here" in h)
check("project page: external links are nofollow ugc", 'rel="noopener noreferrer nofollow ugc"' in h)
st, _, lp = req("GET", "/wrath/mods")
check("listed at once beside the packaged mods", comm_cards(lp) == [r["id"]]
      and re.findall(r'<a class="wk-card" href="/wrath/mods/([a-z0-9-]+)"', lp) == ["dalaran-dice", "emote-wheel", "pings"])
check("a Credits line under every card", lp.count('class="wk-item"') == 4 and lp.count('<p class="wk-credit">Credits: ') == 4)
check("packaged credit: author, licence, repo", "Credits: WrathUnleashed &middot; MIT &middot; <a href=\"https://github.com/orionopenwow/WrathUnleashed/tree/main/mods/catalog/pings\"" in lp)
check("community credit: author link, licence, repo", 'Credits: <a href="https://github.com/alice" rel="noopener noreferrer nofollow ugc">alice</a> &middot; MIT &middot; <a href="https://github.com/alice/frame-kit"' in lp)
st, _, dp = req("GET", "/wrath/mods/pings")
check("packaged detail page: author, licence, repo", "<dt>Author</dt><dd>WrathUnleashed</dd>" in dp and "<dt>Licence</dt><dd>MIT</dd>" in dp
      and "<dt>Repo</dt>" in dp and "mods/catalog/pings" in dp)
check("lists the add and credits links", 'href="/wrath/mods/submit"' in lp and 'href="/wrath/mods/credits"' in lp)

# ---------------------------------------------------------------- validation
n0 = len(records())
bad = [("http://github.com/alice/other", "https://"), ("javascript:alert(1)", "https://"), ("ftp://github.com/a/b", "https://"),
       ("https://evil.example/x", "aren't accepted"), ("https://user:pw@github.com/a/b", "login"),
       ("https://github.com:8443/a/b", "port"), ("https://127.0.0.1/a", "normal web address"), ("https://localhost/a", "normal web address"),
       ("https://github.com/alice", "Link the repo itself"), ("https://github.com/settings/profile", "Link the repo itself"),
       ("https://github.com/a/b c", "spaces"), ("https://github.com/a/" + "b" * 300, "longer than"), ("", "Paste"),
       ("https://github.com/ghost/missing", "couldn't find"), ("https://github.evil.example/a/b", "aren't accepted"),
       ("https://xn--gthub-zsa.com/a/b", "aren't accepted")]
for url, want in bad:
    st, _, h = submit("frank", url)
    check(f"refused: {url[:45] or '(empty)'}", st == 400 and want in err(h), (st, err(h)))
for desc, want in (("short", "at least"), ("x" * 141, "140"), ("Get it at https://spam.example now", "link box"),
                   ("Best World of Warcraft addon ever made", "brand"), ("A fine WoW addon for raids", "brand"),
                   ("line one\nline two of it", "one line")):
    st, _, h = submit("frank", "https://github.com/bob/proj5", desc=desc)
    check(f"refused description: {desc[:24]!r}", st == 400 and want in err(h), (st, err(h)))
st, _, h = submit("frank", "https://github.com/bob/proj5", cat="interface")
check("refused: unknown category", st == 400 and "category" in err(h))
st, _, h = submit("frank", "https://github.com/bob/proj5", builds="2.4.3")
check("refused: unknown builds", st == 400 and "builds" in err(h))
check("a refused form keeps what was typed (escaped)", 'value="https://github.com/bob/proj5"' in h)
check("nothing stored for refused links", len(records()) == n0)

# ---------------------------------------------------------------- duplicates
for dup in ("https://github.com/Alice/Frame-Kit", "https://github.com/alice/frame-kit.git", "https://github.com/alice/frame-kit/",
            "https://github.com/alice/frame-kit?tab=readme#top", "https://GITHUB.com/alice/frame-kit/issues"):
    st, hd, h = submit("frank", dup)
    check(f"duplicate: {dup[19:]}", st == 303 and hd.get("Location") == f"/wrath/mods/p/{r['id']}?dup=1", (st, err(h)))
check("duplicates add nothing", len(records()) == n0)
check("duplicate page says so", "already listed" in req("GET", f"/wrath/mods/p/{r['id']}?dup=1")[2])

# ---------------------------------------------------------------- limits: 3 a day per account
codes = [submit("bob", f"https://github.com/bob/proj{i}", cat="tools", builds="1.12" if i == 1 else "any",
                desc=f"Project number {i} for the tools shelf.")[0] for i in range(1, 5)]
st, _, h = submit("bob", "https://github.com/bob/proj5", desc="Project number five for the tools.")
check("3 links a day per account", codes == [303, 303, 303, 400] and "3 links a day" in err(h), (codes, err(h)))
saved = Wk.projects.day_max; Wk.projects.day_max = len(records())
st, _, h = submit("gina", "https://github.com/bob/proj5", desc="Project number five for the tools.")
check("a cap for everyone per day", st == 400 and "Lots of links" in err(h))
Wk.projects.day_max = saved

# ---------------------------------------------------------------- escaping and brand words in forge metadata
st, hd, h = submit("carol", "https://github.com/mallory/evil", cat="sandbox", desc="Looks <b>bold</b> & \"quoted\" here")
ev = next((x for x in records() if x["url"].endswith("/mallory/evil")), {})
check("hostile metadata stored as plain text", st == 303 and ev.get("author_url") == "https://github.com/mallory" and ev.get("submitter") == "77", ev)
pages = req("GET", "/wrath/mods")[2] + req("GET", f"/wrath/mods/p/{ev.get('id')}")[2] + req("GET", "/wrath/mods/credits")[2]
check("escaped everywhere", "<script>alert(1)" not in pages and "&lt;script&gt;alert(1)&lt;/script&gt;" in pages
      and "<img src=x" not in pages and "<b>bold</b>" not in pages and "&lt;b&gt;bold&lt;/b&gt;" in pages
      and "<b>mal</b>" not in pages and "javascript:" not in pages)
st, _, h = submit("carol", "https://github.com/carol/wow-tools", cat="tools", desc="Handy tools for the game, by fans.")
wt = next((x for x in records() if x["url"].endswith("/carol/wow-tools")), {})
check("brand names in a repo's metadata are replaced", st == 303 and wt.get("title") == "the game-tools"
      and "Warcraft" not in wt.get("repo_description", "") and "Blizzard" not in wt.get("repo_description", ""), wt)

# ---------------------------------------------------------------- other forges, pages, slow APIs
st, _, h = submit("alice", "https://gitlab.com/dave/sub/raidtimer/-/tree/main", cat="encounters", builds="1.12", desc="Boss timers for every raid.")
gl = next((x for x in records() if "gitlab" in x["url"]), {})
check("GitLab: metadata read", st == 303 and gl.get("url") == "https://gitlab.com/dave/sub/raidtimer" and gl.get("licence") == "MPL-2.0"
      and gl.get("stars") == 3 and gl.get("author") == "Dave", gl)
st, _, h = submit("alice", "https://codeberg.org/erin/coremod", cat="realm-scripts", builds="3.3.5a", desc="A realm module for cores.")
cb = next((x for x in records() if "codeberg" in x["url"]), {})
check("Codeberg: metadata read", st == 303 and cb.get("licence") == "AGPL-3.0" and cb.get("stars") == 5 and cb.get("author") == "erin", cb)
st, _, h = submit("frank", "https://someone.itch.io/tiny-game", cat="sandbox", builds="any", desc="A tiny game inside the game.")
it = next((x for x in records() if "itch.io" in x["url"]), {})
check("a project page: accepted without asking any API", st == 303 and it.get("title") == "tiny-game" and it.get("author") == "someone.itch.io"
      and it.get("last_checked") == "" and not any("itch" in p for p, _ in api_seen), it)
t0 = time.time()
st, _, h = submit("frank", "https://github.com/slow/thing", cat="tools", builds="any", desc="A slow repo to time out on.")
sl = next((x for x in records() if "slow/thing" in x["url"]), {})
check("a slow API: times out, still added, last_checked empty", st == 303 and time.time() - t0 < 1.4 and sl.get("last_checked") == ""
      and sl.get("title") == "thing", (st, time.time() - t0, sl))
n_api = len(api_seen)
Wk.projects.meta.fetch("github", "alice", "frame-kit")
check("forge answers are cached", len(api_seen) == n_api)

# ---------------------------------------------------------------- filters
st, _, h = req("GET", "/wrath/mods?source=community")
check("filter: community only", len(comm_cards(h)) == len(records()) and "/wrath/mods/pings\"" not in h)
st, _, h = req("GET", "/wrath/mods?source=packaged")
check("filter: packaged only", comm_cards(h) == [] and 'href="/wrath/mods/pings"' in h)
st, _, h = req("GET", "/wrath/mods?build=1.12")
want = sorted(x["id"] for x in records() if "1.12" in x["builds"] or "any" in x["builds"])
check("filter: build 1.12 (and any)", sorted(comm_cards(h)) == want and 'href="/wrath/mods/pings"' not in h, (comm_cards(h), want))
st, _, h = req("GET", "/wrath/mods/c/sandbox")
check("category page /c/sandbox: packaged and community", st == 200 and 'href="/wrath/mods/dalaran-dice"' in h and ev["id"] in comm_cards(h)
      and 'href="/wrath/mods/pings"' not in h and "Sandbox and game modes" in h)
tl = dict(re.findall(r'<a class="wk-cat[^"]*" href="/wrath/mods/c/([a-z-]+)"[^>]*>.*?<span class="n"[^>]*>(\d+)</span></a>', req("GET", "/wrath/mods")[2]))
check("category counts include community links", tl.get("encounters") == "1" and tl.get("realm-scripts") == "1"
      and tl.get("addons") == "3", tl)
check("filters keep the category", 'href="/wrath/mods/c/sandbox?source=community"' in h)
check("unknown category: 404", req("GET", "/wrath/mods/c/nope")[0] == 404)
st, _, h = req("GET", "/wrath/mods?q=raidtimer")
check("search", comm_cards(h) == [gl["id"]] and 'href="/wrath/mods/pings"' not in h)
check("kind filter: packaged only", comm_cards(req("GET", "/wrath/mods?kind=ui")[2]) == [])

# ---------------------------------------------------------------- report and hide
pid = r["id"]
st, _, h = req("POST", f"/wrath/mods/p/{pid}/report", "", {})
check("signed out: report refused", st == 403 and records()[0]["reports"] == [])
st, _, h = req("GET", f"/wrath/mods/p/{pid}", "bob")
check("signed in: a Report button", f'action="/wrath/mods/p/{pid}/report"' in h and f'action="/wrath/mods/p/{pid}/hide"' not in h)
st, hd, _ = req("POST", f"/wrath/mods/p/{pid}/report", "bob", {"t": token("bob", f"/wrath/mods/p/{pid}", "report")})
check("report: thanked", st == 303 and hd.get("Location") == f"/wrath/mods/p/{pid}?done=report"
      and "admins will take a look" in req("GET", hd.get("Location", "/"))[2])
req("POST", f"/wrath/mods/p/{pid}/report", "bob", {"t": token("bob", f"/wrath/mods/p/{pid}", "report")})
check("a report is counted once per account", records()[0]["reports"] == ["hk-bob"])
check("report without a token: refused", req("POST", f"/wrath/mods/p/{pid}/report", "frank", {})[0] == 403)
check("report by GET: 405", req("GET", f"/wrath/mods/p/{pid}/report", "bob")[0] == 405)
check("reports alone don't hide (no queue)", pid in comm_cards(req("GET", "/wrath/mods")[2]))
st, _, h = req("POST", f"/wrath/mods/p/{pid}/hide", "bob", {"t": Wk._token({"cookie": "wr_session=bob"}, "hide:" + pid)})
check("not an admin (with a valid token): hide refused", st == 403 and "Only the Workshop" in err(h) and not records()[0]["hidden"])
st, _, h = req("GET", f"/wrath/mods/p/{pid}", "admin")
check("admin sees Hide and the report count", f'action="/wrath/mods/p/{pid}/hide"' in h and "<dt>Reports</dt><dd>1</dd>" in h)
st, hd, _h = req("POST", f"/wrath/mods/p/{pid}/hide", "admin", {"t": token("admin", f"/wrath/mods/p/{pid}", "hide")})
check("admin: hidden", st == 303 and records()[0]["hidden"] is True and records()[0]["hidden_by"] == "hk-admin")
check("hidden: off the list", pid not in comm_cards(req("GET", "/wrath/mods")[2]))
check("hidden: off all.json", pid not in req("GET", "/wrath/mods/all.json")[2])
check("hidden: off the credits", "frame-kit" not in req("GET", "/wrath/mods/credits")[2])
check("hidden: its page is gone for everyone else", req("GET", f"/wrath/mods/p/{pid}")[0] == 404 and req("GET", f"/wrath/mods/p/{pid}", "bob")[0] == 404)
st, _, h = req("GET", f"/wrath/mods/p/{pid}", "admin")
check("hidden: admins still see it, with Show again", st == 200 and "only admins see this" in h and f'/wrath/mods/p/{pid}/unhide' in h)
st, _, h = submit("gina", "https://github.com/alice/frame-kit")
check("a hidden link can't be added again", st == 400 and "taken down" in err(h))
st, hd, _ = req("POST", f"/wrath/mods/p/{pid}/unhide", "admin", {"t": token("admin", f"/wrath/mods/p/{pid}", "unhide")})
check("admin: shown again", st == 303 and records()[0]["hidden"] is False and pid in comm_cards(req("GET", "/wrath/mods")[2]))

# ---------------------------------------------------------------- all.json
st, hd, body = req("GET", "/wrath/mods/all.json")
doc = json.loads(body) if st == 200 else {}
ps = doc.get("projects", [])
keys = {"id", "source", "name", "description", "category", "builds", "author", "author_url", "licence", "repo", "page", "credits",
        "stars", "last_push", "submitted_by", "submitted_at", "last_checked", "version", "kind", "permissions", "on_wrath",
        "download", "sha256"}
check("all.json: format 1, CORS *", doc.get("format") == 1 and hd.get("Access-Control-Allow-Origin") == "*")
check("all.json: the 13 categories and the builds", [c["id"] for c in doc.get("categories", [])] == CAT_IDS and doc.get("builds") == ["3.3.5a", "1.12", "any"])
check("all.json: both kinds in one schema", {p["source"] for p in ps} == {"packaged", "community"} and all(set(p) == keys for p in ps))
check("all.json: every project once", len(ps) == 3 + len(records()) and len({p["id"] for p in ps}) == len(ps))
pk = next(p for p in ps if p["id"] == "mod:pings")
check("all.json: packaged fields", pk["download"] == "https://play.example/wrath/mods/pings/download" and pk["on_wrath"] is True
      and pk["licence"] == "MIT" and pk["builds"] == ["3.3.5a"] and pk["category"] == "addons" and pk["page"] == "https://play.example/wrath/mods/pings")
fk = next(p for p in ps if p["id"] == "link:" + pid)
check("all.json: community fields", fk["repo"] == "https://github.com/alice/frame-kit" and fk["stars"] == 42 and fk["submitted_by"] == "Alice"
      and fk["version"] is None and fk["download"] is None and fk["credits"] == "frame-kit by alice · MIT · github.com")
check("all.json: no account ids or reports", "hk-" not in body and "submitter" not in body and "reports" not in body)
check("all.json sorted by name", [p["name"].lower() for p in ps] == sorted(p["name"].lower() for p in ps))
check("all.json: credits the same as the cards", all(p["credits"].split(" · ")[1] in (p["licence"] or "licence not stated") for p in ps))

# ---------------------------------------------------------------- credits page
st, _, cp = req("GET", "/wrath/mods/credits")
vis = [x for x in records() if not x["hidden"]]
check("credits: every author", st == 200 and all(html_a in cp for html_a in ("WrathUnleashed", "alice", "bob", "Dave", "erin", "someone.itch.io")))
check("credits: every project, linked", all(f'href="/wrath/mods/p/{x["id"]}"' in cp for x in vis)
      and all(f'href="/wrath/mods/{m}"' in cp for m in ("pings", "emote-wheel", "dalaran-dice")))
check("credits: thanks and the count", "Thank you to every author" in cp and f"{3 + len(vis)} projects" in cp)

# ---------------------------------------------------------------- the site's one nav and footer on the new pages
def chrome_ok(h):
    return h.count('id="ly-site-nav"') == 1 and 'class="ly-foot"' in h and '<div class="grp">' not in h
for label, (m, u, w, f) in {"submit (signed out)": ("GET", "/wrath/mods/submit", "", None),
                            "submit (signed in)": ("GET", "/wrath/mods/submit", "alice", None),
                            "submit refused": ("POST", "/wrath/mods/submit", "alice", {"t": "x"}),
                            "credits": ("GET", "/wrath/mods/credits", "", None),
                            "project": ("GET", f"/wrath/mods/p/{pid}", "", None),
                            "report refused": ("POST", f"/wrath/mods/p/{pid}/report", "", {})}.items():
    st, _, h = req(m, u, w, f)
    check(f"site nav and footer: {label}", chrome_ok(h) and 'class="on"' in h.split('id="ly-site-nav"', 1)[1].split("</nav>", 1)[0]
          and 'href="/wrath/mods"' in h, (st, h[:300]))

# ---------------------------------------------------------------- storage
check("storage: JSON lines, no temp files left", all(l.strip().startswith("{") for l in open(os.path.join(DATA, "projects.jsonl")))
      and not [f for f in os.listdir(DATA) if f.endswith(".tmp")])
with open(os.path.join(DATA, "projects.jsonl"), "a") as fh:
    fh.write("{broken\n")
check("a broken line is skipped", len(Wk.projects.load()) == len(vis))
PM = wp.workshop_mod.projects_mod
closed = PM.Projects(os.path.join(T, "nope"), categories=["sandbox"])
ok, msg = closed.submit({"id": "x"}, {"url": "https://github.com/a/b", "category": "sandbox", "builds": "any", "description": "a fine thing here"})
check("no data folder: closed, never an error", not ok and "closed" in msg)
W2 = wp.workshop_mod.Workshop(PUB, wp.leyline_css, wp.card_meta, wp.REALM_NAME, projects=closed)
check("no data folder: the Workshop still lists the packaged mods", W2.serve("/wrath/mods", {})[0] == 200
      and json.loads(W2.serve("/wrath/mods/all.json", {})[1])["projects"][0]["source"] == "packaged")
check("account ids from /api/me", PM.account_of({"id": 5}) == "5" and PM.account_of({"username": "u"}) == "u" and PM.account_of({}) == "")

# ---------------------------------------------------------------- old routes still work, no secrets, no brand names
check("old routes unchanged", req("GET", "/wrath/mods/pings")[0] == 200 and req("GET", "/wrath/mods/catalog.json")[0] == 200
      and req("GET", "/wrath/mods/nope")[0] == 404 and req("GET", "/wrath/mods/p/zzz")[0] == 404)
check("the token is never logged", TOKEN not in logbuf.getvalue() and TOKEN[4:] not in logbuf.getvalue())
check("the token goes to GitHub only", all(a == "" for p, a in api_seen if not p.startswith("/gh/")))
def visible(p):
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", p, flags=re.S))
allp = "".join(req("GET", u, w)[2] for u, w in (("/wrath/mods", ""), ("/wrath/mods/submit", "alice"), ("/wrath/mods/submit", ""),
                                                 ("/wrath/mods/credits", ""), (f"/wrath/mods/p/{pid}", "admin"), (f"/wrath/mods/p/{wt['id']}", "")))
jtext = json.dumps([{k: v for k, v in p.items() if k not in ("repo", "page", "author_url", "download")} for p in ps])
texts = visible(allp) + " ".join(re.findall(r'content="([^"]*)"', allp)) + jtext + open(os.path.join(ROOT, "mods", "categories.json")).read()
brand = re.findall(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard", texts)
check("no game-brand names", not brand, brand)

# ---------------------------------------------------------------- the sign-in deploy step mounts /data by itself
import subprocess
FL = os.path.join(T, "fl"); FB = os.path.join(FL, "bin"); FWU = os.path.join(FL, "srv", "wrath"); UP = os.path.join(FL, "up")
for d in (FB, os.path.join(FWU, "portal"), UP):
    os.makedirs(d, exist_ok=True)
for f in ("fastloop.sh", "wrath_portal.py", "workshop.py", "projects.py"):
    shutil.copy(os.path.join(STREAM, f), UP)
open(os.path.join(FB, "docker"), "w").write(r"""#!/usr/bin/env bash
S="$FAKE_STATE"; echo "$*" >> "$S/docker.log"
case "$1" in
  inspect)
    [ -f "$S/exists" ] || exit 1
    if [ "$2" = "-f" ]; then echo /app; grep -q -- '-v .*:/data' "$S/run" 2>/dev/null && echo /data; grep -q -- '-v .*:/hosted' "$S/run" 2>/dev/null && echo /hosted; fi; exit 0 ;;
  exec) [ -f "$S/exec.fail" ] && exit 1; exit 0 ;;
  run) echo "$*" > "$S/run"; touch "$S/exists"; echo cid; exit 0 ;;
  rename) exit 0 ;;
  *) exit 0 ;;
esac
""")
for tool, body in (("curl", 'echo 200'), ("sleep", 'exit 0')):
    open(os.path.join(FB, tool), "w").write("#!/usr/bin/env bash\n" + body + "\n")
for f in os.listdir(FB):
    os.chmod(os.path.join(FB, f), 0o755)
open(os.path.join(FL, "Caddyfile"), "w").write("play.example {\n}\n")

def fastloop(state):
    os.makedirs(state, exist_ok=True)
    env = dict(os.environ, PATH=FB + os.pathsep + os.environ["PATH"], FAKE_STATE=state, WU_DIR=FWU, WU_LIB=os.path.join(FL, "none.sh"),
               WU_CADDYFILE=os.path.join(FL, "Caddyfile"), WU_CADDY_DIR=FL, WU_BACKUPS=os.path.join(FL, "bk"))
    r = subprocess.run(["bash", os.path.join(UP, "fastloop.sh")], env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr, open(os.path.join(state, "docker.log")).read()

open(os.path.join(FWU, "portal", "wrath_portal.py"), "w").write("# the old page\n")
SA = os.path.join(FL, "a"); os.makedirs(SA); open(os.path.join(SA, "exists"), "w").write("")
open(os.path.join(SA, "run"), "w").write("run -d --name wu-portal -v /srv/wrath/portal:/app:ro python:3.12-alpine")
rc, out, dl = fastloop(SA)
run = open(os.path.join(SA, "run")).read()
check("deploy step: no /data mount, so wu-portal is recreated with it", rc == 0 and "FASTLOOP OK" in out
      and f"-v {FWU}/portal-data:/data" in run and os.path.isdir(os.path.join(FWU, "portal-data")), out[-800:])
check("recreated exactly like deploy.sh, plus the mounts", run.strip() == (
      f"run -d --name wu-portal --restart unless-stopped --memory 128m --network wenilla-realm_default --network-alias mangosd "
      f"--env-file {FWU}/portal.env -v {FWU}/portal:/app:ro -v {FWU}/hosted:/hosted -v {FWU}/portal-data:/data python:3.12-alpine python3 -I /app/wrath_portal.py")
      and "network connect ov-wotlk_edge wu-portal" in dl, run)
check("the old container is kept until the new one answers, then removed",
      dl.index("stop wu-portal") < dl.index("rename wu-portal wu-portal-before-data") < dl.index("run -d") < dl.index("exec wu-portal")
      < dl.rindex("rm -f wu-portal-before-data") and "restart wu-portal" not in dl, dl)
check("deploy step installs projects.py", os.path.isfile(os.path.join(FWU, "portal", "projects.py")))
SB = os.path.join(FL, "b"); shutil.copytree(SA, SB); os.remove(os.path.join(SB, "docker.log"))
rc, out, dl = fastloop(SB)
check("deploy step: mount already there, just a restart", rc == 0 and "restart wu-portal" in dl and "run -d" not in dl and "rename" not in dl, dl)
SC = os.path.join(FL, "c"); os.makedirs(SC); open(os.path.join(SC, "exists"), "w").write(""); open(os.path.join(SC, "exec.fail"), "w").write("")
open(os.path.join(FWU, "portal", "wrath_portal.py"), "w").write("# the old page\n")
rc, out, dl = fastloop(SC)
check("a new container that doesn't answer: the old one is put back", rc != 0 and "old container" in out
      and dl.index("run -d") < dl.rindex("rm -f wu-portal") < dl.rindex("rename wu-portal-before-data wu-portal") < dl.rindex("start wu-portal")
      and open(os.path.join(FWU, "portal", "wrath_portal.py")).read() == "# the old page\n", out[-600:] + dl)

srv.shutdown(); api.shutdown(); site.shutdown()
shutil.rmtree(T, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
