"""The Leyline Workshop on the web (stream/creations.py: GET /wrath/workshop and /wrath/workshop/<id>), its data
(realm/custom/workshop-export.py against a fake database), the share link /wrath/w/<id> (stream/links.py kind "w"),
Play (/wrath?go=w:<id> -> "ovws go" over SOAP for realm/custom/lua_scripts/ov_workshop.lua), the deploy steps that
ship it, and the game-data magic bytes refused wherever mod files are taken in.

    python3 -I stream/tests/test_creations.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

SOAP_PORT, REALM_PORT, PAGE_PORT = 17913, 18213, 18214
PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
HERE = os.path.dirname(PORTAL)
REPO = os.path.dirname(HERE)
DATA = tempfile.mkdtemp(prefix="wu-creations-")
ART = tempfile.mkdtemp()
for n in ("wu-theme.css", "leyline-bg.webp"):
    src = os.path.join(HERE, "www-files", "art", n)
    if os.path.isfile(src):
        shutil.copy(src, ART)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL=f"http://127.0.0.1:{SOAP_PORT}/",
                  PORTAL_URL=f"http://127.0.0.1:{REALM_PORT}", WU_STREAM="0", STREAM_HOST="wrath.example",
                  PUBLIC_HOST="play.example", WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_ART_DIR=ART,
                  WU_WORKSHOP_ITEMS_DIR=DATA)

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BANNED = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")


def visible(p):
    p = re.sub(r"<style.*?</style>", " ", p, flags=re.S)
    attrs = " ".join(re.findall(r'(?:alt|title|content|aria-label)="([^"]*)"', p))
    return re.sub(r"<[^>]+>", " ", p) + " " + attrs


# ---------------------------------------------------------------- 1. the export, against a fake database
ex = load("workshop_export", os.path.join(REPO, "realm", "custom", "workshop-export.py"))
src = open(os.path.join(REPO, "realm", "custom", "workshop-export.py"), encoding="utf-8").read()
check("export: READ ONLY session, one fixed SELECT of approved items", "SET SESSION TRANSACTION READ ONLY" in src
      and "WHERE state = 'approved'" in ex.SQL and ex.SQL.startswith("SELECT ") and ";" not in ex.SQL)
check("export: never selects guids, refs (course keys, build codes) or state", not re.search(r"author_guid|\bref\b|state,", ex.SQL.split("WHERE")[0]))
seen_sql = []
rows = "\n".join([
    "7\tcourse\tWindmill Nine\tAlys\tNine holes, one windmill.\t2\t1700000000\t41\t5\t1",
    "9\tmode\tTag <b>Arena</b>\tBo\t\t1\t1700000100\t3\t0\t0",
    "12\tbuild\tGreen Camp\tAnn\tA camp\\tby the lake\t1\t1700000200\t0\t2\t0",
    "13\tbuild\tBad author\tAnn123\t\t1\t1\t0\t0\t0",
    "14\tbanner\tWrong kind\tAnn\t\t1\t1\t0\t0\t0",
    "x\tcourse\tNo id\tAnn\t\t1\t1\t0\t0\t0",
    "7\tcourse\tDuplicate\tAnn\t\t1\t1\t0\t0\t0",
    "15\tmode\t\tAnn\t\t1\t1\t0\t0\t0",
    "short\trow",
]) + "\n"
n = ex.run(lambda sql: seen_sql.append(sql) or rows, out=DATA, now=1700001000)
doc = json.load(open(os.path.join(DATA, "items.json")))
check("export: only good rows", n == 3 and [i["id"] for i in doc["items"]] == [7, 9, 12], doc["items"])
check("export: fields", doc["items"][0] == {"id": 7, "kind": "course", "title": "Windmill Nine", "author": "Alys",
      "descr": "Nine holes, one windmill.", "version": 2, "created": 1700000000, "plays": 41, "up": 5, "down": 1}
      and doc["updated"] == 1700001000)
check("export: titles cleaned, escapes undone then cleaned", doc["items"][1]["title"] == "Tag bArenab" and doc["items"][2]["descr"] == "A camp by the lake")
try:
    ex.run(lambda s: (_ for _ in ()).throw(RuntimeError("mysql down")), out=DATA)
    check("export: a database failure raises (cron keeps the old file)", False)
except RuntimeError:
    check("export: a database failure raises (cron keeps the old file)", json.load(open(os.path.join(DATA, "items.json")))["updated"] == 1700001000)
check("export: no temp files left", [f for f in os.listdir(DATA) if f.startswith(".tmp")] == [])

# more items, so the list pages
items = doc["items"] + [{"id": 100 + k, "kind": "course", "title": f"Course {k}", "author": "Pat", "descr": "",
                         "version": 1, "created": 1600000000 + k, "plays": k, "up": 0, "down": 0} for k in range(30)]
items.append({"id": 200, "kind": "mode", "title": "Sneaky", "author": "Bo", "descr": "<script>alert(1)</script>",
              "version": 1, "created": 5, "plays": 0, "up": 0, "down": 0, "author_guid": 77, "account": "WR000001"})
items.append({"id": 201, "kind": "mode", "title": "Bad", "author": "Bo<i>", "version": 1, "created": 5, "plays": 0, "up": 0, "down": 0})
items.append({"id": 0, "kind": "mode", "title": "Zero", "author": "Bo", "version": 1, "created": 5, "plays": 0, "up": 0, "down": 0})
items.append({"id": 202, "kind": "mode", "title": "Neg", "author": "Bo", "version": 1, "created": 5, "plays": -1, "up": 0, "down": 0})
items.append({"id": 203, "kind": "mode", "title": "Bool", "author": "Bo", "version": 1, "created": 5, "plays": True, "up": 0, "down": 0})
json.dump({"updated": 1700002000, "items": items}, open(os.path.join(DATA, "items.json"), "w"))

# ---------------------------------------------------------------- 2. the portal with fakes
soap = {"commands": [], "ovws": "ovws ok: WR000123 -> 7 (30 min)"}


class Soap(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        cmd = wp._tag_text(self.rfile.read(int(self.headers["Content-Length"])), "command")
        soap["commands"].append(cmd)
        if cmd.startswith("account create"):
            ok, text = False, "Account with this name already exist!"
        elif cmd.startswith("ovws"):
            ok, text = soap["ovws"] is not None, soap["ovws"] or "There is no such command."
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


wp = load("wp", PORTAL)
wp.realm_status = lambda: {"online": True, "players": 3, "bots": 10}
C = wp.creations
check("creations.py loaded beside the portal", C is not None)
if C is None:
    print(f"\n{passed}/{passed + failed} passed"); sys.exit(1)
C.store.root = DATA
C.STAT_EVERY = 0

for port, h in ((SOAP_PORT, Soap), (REALM_PORT, Realm), (PAGE_PORT, wp.PageHandler)):
    srv = ThreadingHTTPServer(("127.0.0.1", port), h)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, cookie="", ip="10.7.0.1", method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    hd = {"X-Forwarded-For": ip}
    if cookie:
        hd["Cookie"] = cookie
    c.request(method, path, headers=hd)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


# --- the store
C.store.refresh()
ids = sorted(C.store.by_id)
check("store: bad entries dropped (author, id 0, negative, booleans)", 201 not in ids and 0 not in ids and 202 not in ids
      and 203 not in ids and 200 in ids and len(ids) == 34, ids)
check("store: only the known fields are kept", set(C.store.by_id[200]) == {"id", "kind", "title", "author", "descr", "version",
      "created", "plays", "up", "down"})
check("store: item by path digits only", C.store.item("7")["title"] == "Windmill Nine" and C.store.item("07") is None
      and C.store.item("7x") is None and C.store.item("../7") is None and C.store.item(0) is None)

# --- the list
st, h, b = get("/wrath/workshop")
page = b.decode()
check("GET /wrath/workshop: 200 html", st == 200 and h.get("content-type", "").startswith("text/html"), st)
check("trailing slash too", get("/wrath/workshop/")[0] == 200)
check("no script allowed (CSP script-src 'none')", "script-src 'none'" in h.get("content-security-policy", ""))
check("no script on the page, none from the data", "<script" not in page and "alert(1)" not in page)
check("the site nav, with Workshop marked", 'id="ly-site-nav"' in page and re.search(r'<a href="/wrath/workshop" class="on" aria-current="page">Workshop</a>', page))
check("link card", 'property="og:url" content="https://play.example/wrath/workshop"' in page)
check("title", "<title>Workshop · WrathUnleashed</title>" in page)
check("most played first", page.index("Windmill Nine") < page.index("Course 29") < page.index("Course 28<"))
check("each row: title link, kind and author, plays, rating, Play", 'href="/wrath/workshop/7">Windmill Nine</a>' in page
      and "Course by Alys" in page and "41 plays" in page and "+5" in page and "-1" in page
      and 'href="/wrath?go=w:7"' in page and ">Play</a>" in page)
check("25 a page, with a next link", page.count('class="ws-play"') == 25 and 'href="/wrath/workshop?page=2"' in page)
st, _, b = get("/wrath/workshop?page=2")
check("page 2", st == 200 and b.decode().count('class="ws-play"') == 9 and 'rel="prev"' in b.decode())
check("a page past the end is the last page", "Page 2 of 2" in get("/wrath/workshop?page=99")[2].decode())
p = get("/wrath/workshop?kind=mode")[2].decode()
check("by kind", "Sneaky" in p and "Windmill Nine" not in p and 'aria-current="page">Modes<' in p)
p = get("/wrath/workshop?sort=rating")[2].decode()
check("top rated", p.index("Windmill Nine") < p.index("Green Camp") < p.index("Course 29"))
p = get("/wrath/workshop?sort=new&kind=build")[2].decode()
check("new, builds", "Green Camp" in p and "Course 1" not in p)
p = get("/wrath/workshop?kind=<script>&sort=x&page=-1")[2].decode()
check("junk query: the default list, nothing echoed", "<script>" not in p and "Windmill Nine" in p)
check("no game-brand names", not BANNED.findall(visible(page)), BANNED.findall(visible(page)))

# --- one item
st, h, b = get("/wrath/workshop/7")
item = b.decode()
check("item page: 200 with its title, kind, author, description", st == 200 and "<h1>Windmill Nine</h1>" in item
      and "Minigolf course by Alys" in item and "Nine holes, one windmill." in item)
check("item page: a big Play to the game", 'class="ws-play big" href="/wrath?go=w:7"' in item)
check("item page: plays, rating, version, share link", "<dd>41</dd>" in item and "<dd>2</dd>" in item
      and "https://play.example/wrath/w/7" in item and "<code>.workshop play 7</code>" in item)
check("item page: no script, its own card", "<script" not in item and 'content="https://play.example/wrath/workshop/7"' in item)
for bad in ("/wrath/workshop/99999", "/wrath/workshop/abc", "/wrath/workshop/7/..", "/wrath/workshop/0", "/wrath/workshop/%37"):
    check(f"404 for {bad}", get(bad)[0] == 404)
check("a 404 is still a page with the nav", 'id="ly-site-nav"' in get("/wrath/workshop/99999")[2].decode())
check("no game-brand names on an item", not BANNED.findall(visible(item)))
os.rename(os.path.join(DATA, "items.json"), os.path.join(DATA, "gone.json"))
p = get("/wrath/workshop")[2].decode()
check("no export yet: an empty Workshop, not an error", "Nothing here yet" in p)
os.rename(os.path.join(DATA, "gone.json"), os.path.join(DATA, "items.json"))
open(os.path.join(DATA, "items.json"), "a").write("garbage")
check("a broken file: an empty Workshop, not an error", get("/wrath/workshop")[0] == 200)
json.dump({"updated": 1700002000, "items": items}, open(os.path.join(DATA, "items.json"), "w"))

# --- the share link
L = wp.links
check("links: kind w", L.check_go("w:7") == ("w", "7") and L.check_go("w:0") is None and L.check_go("w:abc") is None
      and L.check_go("w:1234567890") is None and L.deep_link("w", "7") == "/wrath?go=w:7")
st, _, b = get("/wrath/w/7")
sh = b.decode()
check("share link /wrath/w/7: the item's title on the card and the page", st == 200 and "Windmill Nine · Workshop" in sh
      and "a minigolf course by Alys" in sh)
check("share link goes on to Play and to the item", "/wrath?go=w:7" in sh and 'href="/wrath/workshop/7"' in sh)
check("share link for an unknown id: generic, still a link", "Workshop item 4242" in get("/wrath/w/4242")[2].decode())

# --- Play: the go intent
def ovws():
    return [c for c in soap["commands"] if c.startswith("ovws")]


get("/wrath?go=w:7")
check("signed out: nothing sent", ovws() == [])
st, _, b = get("/wrath/account?go=w:7", cookie="wr_session=good")
check("signed in: the page still works", st == 200 and b"WR000123" in b, st)
check("signed in: ovws go for the game account", ovws() == ["ovws go WR000123 7"], ovws())
check("after the account is ensured", soap["commands"].index("ovws go WR000123 7") >
      soap["commands"].index("account set password WR000123 Pa55word1234abcd Pa55word1234abcd"))
check("no ovgo for a Workshop item", not [c for c in soap["commands"] if c.startswith("ovgo")])
k = len(ovws())
for bad in ("w:0", "w:7;drop", "w:abc", "w:", "w:99999999999"):
    get(f"/wrath/account?go={bad}", cookie="wr_session=good")
check("bad ids never reach SOAP", len(ovws()) == k, ovws()[k:])
soap["ovws"] = None
st, _, b = get("/wrath/account?go=w:9", cookie="wr_session=good")
check("realm without ov_workshop.lua: the page still works", st == 200 and ovws()[-1] == "ovws go WR000123 9")
check("go_command", C.go_command("wr000123", "12") == "ovws go WR000123 12" and C.go_command("WR 1", "12") is None
      and C.go_command("WR1", "1 2") is None and C.go_command("WR1", "0") is None)
calls = []
check("go_intent: confirmed once, not resent within 2 min", C.go_intent(lambda c: calls.append(c) or "ovws ok", "UNIT1", "5")
      and C.go_intent(lambda c: calls.append(c) or "ovws ok", "UNIT1", "5") and calls == ["ovws go UNIT1 5"])
check("go_intent: a SOAP error is False, never raised", C.go_intent(lambda c: (_ for _ in ()).throw(OSError("x")), "UNIT2", "5") is False)

# ---------------------------------------------------------------- 3. shipped by the steps
fl = open(os.path.join(HERE, "fastloop.sh"), encoding="utf-8").read()
check("fastloop.sh: installs creations.py, backs it up, puts it back", 'install -m 644 creations.py "$WU/portal/creations.py"' in fl
      and '"$BK/creations.py"' in fl and "/wrath/workshop" in fl)
check("fastloop.sh: bash syntax", subprocess.run(["bash", "-n", os.path.join(HERE, "fastloop.sh")]).returncode == 0)
bat = open(os.path.join(HERE, "Update sign-in and warm-up.bat"), encoding="utf-8").read()
check("sign-in bat: packs creations.py", 'if exist creations.py set "LINKS=%LINKS% creations.py"' in bat and " creations.py " in bat)
sp = open(os.path.join(REPO, "realm", "serverpass.sh"), encoding="utf-8").read()
check("serverpass.sh: installs the export with its cron and makes the table", "/srv/wrath/workshop-export.py" in sp
      and "/etc/cron.d/wu-workshop" in sp and "CREATE TABLE IF NOT EXISTS mod_workshop_items" in sp
      and "/srv/wrath/portal/workshop" in sp)
check("serverpass.sh: bash syntax", subprocess.run(["bash", "-n", os.path.join(REPO, "realm", "serverpass.sh")]).returncode == 0)
lua = open(os.path.join(REPO, "realm", "custom", "lua_scripts", "ov_workshop.lua"), encoding="utf-8").read()
check("serverpass.sh makes the same table as ov_workshop.lua",
      re.sub(r"\s+", " ", re.search(r"mod_workshop_items \((.*?)\)\]\]", lua, re.S).group(1)).strip()
      == re.sub(r"\s+", " ", re.search(r"CREATE TABLE IF NOT EXISTS mod_workshop_items \((.*?)\n\);", sp, re.S).group(1)).strip())
spbat = open(os.path.join(REPO, "realm", "Server pass - finder 10 and bug reports.bat"), encoding="utf-8").read()
check("server pass bat: uploads ov_workshop.lua and workshop-export.py", 'custom\\lua_scripts\\ov_workshop.lua' in spbat
      and 'custom\\workshop-export.py' in spbat and "armory-export.py workshop-export.py" in spbat)
check("export: parses", subprocess.run([sys.executable, "-I", "-c", "import ast,sys;ast.parse(open(sys.argv[1]).read())",
                                        os.path.join(REPO, "realm", "custom", "workshop-export.py")]).returncode == 0)

# ---------------------------------------------------------------- 4. game data is refused wherever mod files come in
need = {"MPQ\\x1a": "MPQ", "MD20": "M2", "BLP2": "BLP", "REVM": "ADT/WMO/WDT (MVER chunk)"}
wumod = load("wu_mod", os.path.join(REPO, "mods", "wu-mod.py"))
magics = {m for m, _ in wumod.BLOCKED_MAGIC}
check("wu-mod.py (the mods step, run again on the server) refuses the magics",
      {b"MPQ\x1a", b"MD20", b"BLP2", b"REVM"} <= magics)
rs = open(os.path.join(REPO, "launcher", "src-tauri", "src", "mods.rs"), encoding="utf-8").read()
check("the launcher's mod import refuses them", all(f'b"{m}"' in rs for m in need))
js = open(os.path.join(HERE, "www-files", "wu-addons-core.js"), encoding="utf-8").read()
check("the browser's addon loader refuses them", all(f"'{m}'" in js for m in need))
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "assets"))
open(os.path.join(tmp, "assets", "tree.png"), "wb").write(b"MD20" + b"\0" * 32)
open(os.path.join(tmp, "assets", "tile.glb"), "wb").write(b"REVM" + b"\0" * 32)
rep = wumod.Report()
wumod.check_blocked_files(tmp, ["assets/tree.png", "assets/tile.glb"], rep)
check("a renamed model and map tile are refused by their bytes", len(rep.errors) == 2)

# ---------------------------------------------------------------- 5. the creators' doc
doc_md = open(os.path.join(REPO, "docs", "WORKSHOP.md"), encoding="utf-8").read()
check("docs/WORKSHOP.md: publish, review, Play and the web page", all(w in doc_md for w in (".workshop publish", "/golf",
      "/modes", ".build share", "/wrath/workshop", "GM")))
check("docs/WORKSHOP.md: no game-brand names", not BANNED.findall(doc_md))

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
