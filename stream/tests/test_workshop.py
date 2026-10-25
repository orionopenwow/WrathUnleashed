"""The mods Workshop end to end: the "mods" step's server script (stream/server/mods-install.sh with
mods-overlay.py, against fake docker and SOAP in a temp /srv/wrath) publishes mods/catalog, then the portal
serves it (stream/workshop.py hooked into wrath_portal.py: GET /wrath/mods, /wrath/mods/<id>, the zip, the
screenshots), the share link /wrath/m/<id> uses the real mod name, and the in-game Workshop tab reads the
generated mod list (stream/tests/test_wuui_workshop.lua).

    python3 -I stream/tests/test_workshop.py stream/wrath_portal.py
"""
import hashlib, http.client, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import ThreadingHTTPServer

PORTAL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "wrath_portal.py"))
STREAM = os.path.dirname(PORTAL)
ROOT = os.path.dirname(STREAM)
MODS = os.path.join(ROOT, "mods")
LUA = shutil.which("lua5.1")

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

# ---------------------------------------------------------------- 1. the mods step on a fake server
T = tempfile.mkdtemp(prefix="wu-workshop-")
WU = os.path.join(T, "srv", "wrath"); ST = os.path.join(WU, "stream"); FAKE = os.path.join(T, "fake")
for d in (os.path.join(ST, "slices", "mini", "DBFilesClient"), os.path.join(ST, "www"), os.path.join(WU, "portal"),
          os.path.join(WU, "custom", "lua_scripts"), FAKE):
    os.makedirs(d, exist_ok=True)
shutil.copy(os.path.join(STREAM, "server", "stream-lib.sh"), ST)
open(os.path.join(WU, "portal.env"), "w").write("STREAM_SLICES=mini\n")
open(os.path.join(ST, "www", "boot-manifest.json"), "w").write(json.dumps({"names": ["Interface\\GlueXML\\GlueXML.toc"]}))
open(os.path.join(WU, "soap-cmd.sh"), "w").write('echo "$*" >> "$(dirname "$0")/soap.log"\n'
                                                 '[ -f "$(dirname "$0")/soap.fail" ] && { echo "refused"; exit 1; }\necho ok\n')
open(os.path.join(FAKE, "docker"), "w").write('#!/usr/bin/env bash\necho "$*" >> "%s/docker.log"\n'
                                              'case "$1" in logs) echo "ready..."; cat "%s/worldlog" 2>/dev/null ;; ps) echo wu-play ;; inspect) echo 2026-10-25T00:00:00Z ;; esac\nexit 0\n'
                                              % (WU, FAKE))
os.chmod(os.path.join(FAKE, "docker"), 0o755)
ENV = dict(os.environ, WU_DIR=WU, WU_MODS_BACKUPS=os.path.join(T, "bk"), WU_RELOAD_WAIT="0", MODS_WARN_MIN="0",
           PATH=FAKE + os.pathsep + os.environ.get("PATH", ""))


def upload(edit=None):
    """The tar the .bat sends: kit/ + catalog/ (a fresh copy, optionally edited)."""
    u = tempfile.mkdtemp(prefix="up-", dir=T)
    os.makedirs(os.path.join(u, "kit"))
    for src in (os.path.join(MODS, "wu-mod.py"), os.path.join(STREAM, "server", "mods-install.sh"),
                os.path.join(STREAM, "server", "mods-overlay.py")):
        shutil.copy(src, os.path.join(u, "kit"))
    shutil.copytree(os.path.join(MODS, "catalog"), os.path.join(u, "catalog"))
    if edit:
        edit(os.path.join(u, "catalog"))
    return u


def install(u):
    p = subprocess.run(["bash", os.path.join(u, "kit", "mods-install.sh"), "install", u], env=ENV,
                       capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout + p.stderr


def read(*parts):
    try:
        return open(os.path.join(*parts), encoding="utf-8").read()
    except OSError:
        return ""


def count(path, needle):
    return read(path).count(needle)


LUA_MODS = os.path.join(WU, "custom", "lua_scripts", "mods")
SLICE = os.path.join(ST, "slices", "mini")
PUB = os.path.join(WU, "portal", "mods")
rc, out = install(upload())
check("mods step: MODS OK", rc == 0 and "MODS OK" in out, out[-1500:])
check("realm halves in lua_scripts/mods/<id>/", os.path.isfile(os.path.join(LUA_MODS, "pings", "pings.lua"))
      and os.path.isfile(os.path.join(LUA_MODS, "dalaran-dice", "dalaran_dice.lua")))
check("a UI-only mod puts nothing on the realm", not os.path.exists(os.path.join(LUA_MODS, "emote-wheel")))
check("new realm scripts: a restart, never a live reload", count(os.path.join(WU, "docker.log"), "restart ov-ac-worldserver") == 1
      and count(os.path.join(WU, "soap.log"), "reload ale") == 0, read(WU, "soap.log") + read(WU, "docker.log"))
check("addons laid over the slice", all(os.path.isfile(os.path.join(SLICE, "Interface", "AddOns", a, a + ".toc"))
                                        for a in ("WUPings", "WUEmoteWheel", "DalaranDice", "WUModCatalog")))
gen = read(SLICE, "Interface", "AddOns", "WUModCatalog", "WUModCatalog.lua")
check("generated mod list names every mod", all(f'id = "{m}"' in gen for m in ("pings", "emote-wheel", "dalaran-dice")))
check("a record for exact undo", os.path.isfile(os.path.join(SLICE, ".overlay-mods", "added.txt")))
bm = json.load(open(os.path.join(ST, "www", "boot-manifest.json")))
check("boot list has the addons", "Interface\\AddOns\\WUPings\\WUPings.lua" in bm["names"] and bm.get("mods_overlay")
      and "Interface\\GlueXML\\GlueXML.toc" in bm["names"])
check("wu-play restarted for new addons", count(os.path.join(WU, "docker.log"), "restart wu-play") == 1)
check("kit installed beside fui-install.sh", os.path.isfile(os.path.join(ST, "mods-install.sh")) and os.path.isfile(os.path.join(ST, "mods-overlay.py")))
cat = json.loads(read(PUB, "catalog.json") or "{}")
ids = sorted(m["id"] for m in cat.get("mods", []))
check("catalog.json published", ids == ["dalaran-dice", "emote-wheel", "pings"], ids)
inst = json.loads(read(PUB, "installed.json") or "{}")
check("installed.json says what the realm runs", inst.get("installed", {}).get("pings") == "0.1.0")
zp = os.path.join(PUB, "files", "pings-0.1.0.zip")
check("zips published with matching sha256", os.path.isfile(zp) and hashlib.sha256(open(zp, "rb").read()).hexdigest()
      == next(m["sha256"] for m in cat["mods"] if m["id"] == "pings"))
check("screenshots published", os.path.isfile(os.path.join(PUB, "shots", "pings", "preview.png")))
names = [n for m in cat["mods"] for n in [m["zip"]]]
check("no game data in any package", not any(re.search(r"\.(mpq|blp|m2|wmo|adt|dbc)$", n, re.I)
      for z in names for n in __import__("zipfile").ZipFile(os.path.join(PUB, "files", z)).namelist()))

rc, out = install(upload())
check("run again unchanged: OK", rc == 0 and "MODS OK" in out, out[-800:])
check("unchanged: no reload, no restarts", count(os.path.join(WU, "soap.log"), "reload ale") == 0
      and count(os.path.join(WU, "docker.log"), "restart ov-ac-worldserver") == 1
      and count(os.path.join(WU, "docker.log"), "restart wu-play") == 1)

before = read(LUA_MODS, "pings", "pings.lua")
def break_mod(c):
    with open(os.path.join(c, "pings", "realm", "pings.lua"), "a") as f:
        f.write('\nos.execute("rm -rf /")\n')
rc, out = install(upload(break_mod))
check("a mod that fails the checks: refused, nothing changed", rc != 0 and "nothing changed" in out
      and read(LUA_MODS, "pings", "pings.lua") == before and "forbidden-api" in out, out[-600:])

def change_mod(c):
    with open(os.path.join(c, "pings", "realm", "pings.lua"), "a") as f:
        f.write("\n-- a new line\n")
open(os.path.join(FAKE, "worldlog"), "w").write("[ALE] lua_scripts/mods/pings/pings.lua:120: attempt to call a nil value\n")
rc, out = install(upload(change_mod))
check("a Lua error after reload: rolled back", rc != 0 and read(LUA_MODS, "pings", "pings.lua") == before
      and "previous" in out, out[-600:])
check("a changed script reloads live; rollback reloads again", count(os.path.join(WU, "soap.log"), "reload ale") == 2,
      read(WU, "soap.log"))
check("site unchanged after a rollback", json.loads(read(PUB, "installed.json"))["installed"] == inst["installed"])
os.remove(os.path.join(FAKE, "worldlog"))
open(os.path.join(WU, "soap.fail"), "w").write("")
rc, out = install(upload(change_mod))
check("a refused reload: rolled back", rc != 0 and read(LUA_MODS, "pings", "pings.lua") == before, out[-400:])
os.remove(os.path.join(WU, "soap.fail"))

new_slice = os.path.join(ST, "slices", "mini.stage"); os.makedirs(os.path.join(new_slice, "DBFilesClient"))
p = subprocess.run(["bash", os.path.join(ST, "mods-install.sh"), "reapply-slice", "mini", new_slice], env=ENV,
                   capture_output=True, text=True)
check("reapply-slice lays the mods over a new slice", p.returncode == 0
      and os.path.isfile(os.path.join(new_slice, "Interface", "AddOns", "WUPings", "WUPings.lua")), p.stdout + p.stderr)
ov = importlib.util.spec_from_file_location("mods_overlay", os.path.join(STREAM, "server", "mods-overlay.py"))
mo = importlib.util.module_from_spec(ov); ov.loader.exec_module(mo)
mo.unapply_slice(new_slice, quiet=True)
check("unapply is exact", sorted(os.listdir(new_slice)) == ["DBFilesClient"], os.listdir(new_slice))
check("overlay never takes Forever UI's folders", not mo.taken(("Interface", "AddOns", "ForeverUI", "x.lua"))
      and not mo.taken(("Interface", "AddOns", "WrathUnleashedUI", "x.lua")) and mo.taken(("Interface", "AddOns", "WUPings", "a.lua"))
      and not mo.taken(("Interface", "GlueXML", "GlueXML.toc")))
hooks = read(STREAM, "server", "slice-install.sh") + read(STREAM, "server", "patch-index.sh")
check("new slices and client builds get the mods back", "mods-install.sh\" reapply-slice" in hooks and "mods-install.sh\" reapply-www" in hooks)
bat = read(MODS, "Put mods on Wrath.bat")
check("the bat: one ssh, the owner's key and host", bat.count("ssh -i") == 1 and "%USERPROFILE%\\.ssh\\openwow" in bat
      and "root@play.openvanilla.app" in bat and "MODS OK" in bat)
ctl = read(ROOT, "tools", "control", "control.py")
check("Autopilot step 'mods'", '"mods":  ("mods/Put mods on Wrath.bat"' in ctl and "def restart_if_updated" in ctl)

# ---------------------------------------------------------------- 2. the site
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example", WU_MODS_DIR=PUB,
                  WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json")
spec = importlib.util.spec_from_file_location("wp", PORTAL)
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.community_realms = lambda: ([], True)
wp.realm_status = lambda: {"online": True, "players": 1, "bots": 0}
check("workshop.py loaded beside the portal", wp.workshop is not None and wp.workshop.dir == PUB)
Wk = wp.workshop

def page(path, query=None):
    st, body, ctype, hd = Wk.serve(path, query or {})
    return st, body.decode("utf-8", "replace") if ctype.startswith(("text", "application/json")) else body, ctype, hd

def cards(html_):
    return re.findall(r'<a class="wk-card" href="/wrath/mods/([a-z0-9-]+)"', html_)

st, lp, ct, _ = page("/wrath/mods")
check("GET /wrath/mods is a page", st == 200 and ct.startswith("text/html") and "<h1 class=\"wk-h1\">Workshop</h1>" in lp)
check("a card per mod, by name", cards(lp) == ["dalaran-dice", "emote-wheel", "pings"], cards(lp))
check("Leyline look", "ly-panel" in lp and "/wrath/art/leyline-bg.webp" in lp and 'class="ly"' in lp)
check("card shows the screenshot", '/wrath/mods/pings/shot/0' in lp)
check("On Wrath badges", lp.count(">On Wrath<") == 3)
check("filter ui", cards(page("/wrath/mods", {"kind": ["ui"]})[1]) == ["emote-wheel"])
check("filter both", cards(page("/wrath/mods", {"kind": ["both"]})[1]) == ["dalaran-dice", "pings"])
check("filter realm (none here)", cards(page("/wrath/mods", {"kind": ["realm"]})[1]) == [] and "No mods match" in page("/wrath/mods", {"kind": ["realm"]})[1])
check("filter permission db", cards(page("/wrath/mods", {"perm": ["db"]})[1]) == ["dalaran-dice"])
check("filter permission timers", cards(page("/wrath/mods", {"perm": ["timers"]})[1]) == ["pings"])
check("filter no permissions", cards(page("/wrath/mods", {"perm": ["none"]})[1]) == ["emote-wheel"])
check("filters combine", cards(page("/wrath/mods", {"kind": ["both"], "perm": ["chat"]})[1]) == ["dalaran-dice", "pings"])
check("junk filters ignored", cards(page("/wrath/mods", {"kind": ["<x>"], "perm": ["files"]})[1]) == ["dalaran-dice", "emote-wheel", "pings"])
f = page("/wrath/mods", {"kind": ["ui"]})[1]
check("filter chips are links that keep the other filter", 'href="/wrath/mods?kind=ui&amp;perm=db"' in f and 'class="wk-chip on"' in f)

st, dp, _, _ = page("/wrath/mods/pings")
check("detail page", st == 200 and "<h2 id=\"wk-name\">Pings</h2>" in dp)
check("permissions in plain words", "Sends messages: to players near you" in dp and "Runs things on a timer." in dp)
check("download link and size", 'href="/wrath/mods/pings/download"' in dp and "KB)" in dp)
check("Already on Wrath", "Already on Wrath" in dp)
check("share link /wrath/m/<id>", 'href="/wrath/m/pings"' in dp)
check("sha256 shown", next(m["sha256"] for m in cat["mods"] if m["id"] == "pings") in dp)
check("UI-only mod: no realm permissions said plainly", "None on the realm" in page("/wrath/mods/emote-wheel")[1])
check("its addon named with the in-game switch", "WUEmoteWheel" in page("/wrath/mods/emote-wheel")[1]
      and "Esc &rarr; Mods &amp; Workshop" in page("/wrath/mods/emote-wheel")[1])
check("detail link card", 'property="og:url" content="https://play.example/wrath/mods/pings"' in dp
      and "Alt-click the world map" in (re.search(r'property="og:description" content="([^"]*)"', dp) or [None, ""])[1])

st, z, ct, hd = page("/wrath/mods/pings/download")
check("download: the zip", st == 200 and ct == "application/zip" and z == open(zp, "rb").read())
check("download: attachment name", hd.get("Content-Disposition") == 'attachment; filename="pings-0.1.0.zip"')
st, img, ct, _ = page("/wrath/mods/pings/shot/0")
check("screenshot", st == 200 and ct == "image/png" and img[:4] == b"\x89PNG")
st, cj, ct, hd = page("/wrath/mods/catalog.json")
check("catalog.json for tools", st == 200 and json.loads(cj)["mods"][0]["on_wrath"] is True and hd.get("Access-Control-Allow-Origin") == "*")
for bad in ("/wrath/mods/nope", "/wrath/mods/UPPER", "/wrath/mods/pings/shot/7", "/wrath/mods/pings/shot", "/wrath/mods/../../etc",
            "/wrath/mods/pings/download/1", "/wrath/mods/pings/x", "/wrath/mods/a%2Fb", "/wrath/mods/" + "a" * 50,
            "/wrath/mods/catalog.json/download"):
    check(f"404 for {bad}", page(bad)[0] == 404)

# installed.json says another version: not "Already on Wrath"
shutil.copytree(PUB, os.path.join(T, "pub2"))
P2 = os.path.join(T, "pub2")
json.dump({"installed": {"pings": "0.0.9"}}, open(os.path.join(P2, "installed.json"), "w"))
W2 = wp.workshop_mod.Workshop(P2, wp.leyline_css, wp.card_meta, wp.REALM_NAME)
check("older version installed: not on Wrath", "Already on Wrath" not in W2.serve("/wrath/mods/pings", {})[1].decode()
      and W2.serve("/wrath/mods", {})[1].decode().count(">On Wrath<") == 0)

# hostile catalog: escaped, bad entries dropped, bad file names never served
evil = {"format": 1, "mods": [
    {"id": "evil-mod", "name": "<script>alert(1)</script>", "version": "1.0.0", "kind": "ui", "author": "\"><img src=x>",
     "description": "<b>bold</b>", "screenshots": ["../../../etc/passwd", "ok.png"], "zip": "../../x.zip", "sha256": "z"},
    {"id": "../up", "name": "x", "version": "1.0.0", "kind": "ui"},
    {"id": "nokind", "name": "x", "version": "1.0.0", "kind": "server"},
    "junk"]}
P3 = os.path.join(T, "pub3"); os.makedirs(P3)
json.dump(evil, open(os.path.join(P3, "catalog.json"), "w"))
W3 = wp.workshop_mod.Workshop(P3, wp.leyline_css, wp.card_meta, wp.REALM_NAME)
l3 = W3.serve("/wrath/mods", {})[1].decode(); d3 = W3.serve("/wrath/mods/evil-mod", {})[1].decode()
check("hostile catalog: only the valid id listed", cards(l3) == ["evil-mod"])
check("hostile catalog: escaped", "<script>alert" not in l3 + d3 and "&lt;script&gt;" in d3 and "<img src=x>" not in d3 and "<b>bold" not in l3)
check("hostile catalog: a bad zip name is never offered", "/download" not in d3 and W3.serve("/wrath/mods/evil-mod/download", {})[0] == 404)
check("hostile catalog: path screenshots dropped", W3.mod("evil-mod")["screenshots"] == ["passwd"] or W3.mod("evil-mod")["screenshots"] == ["ok.png"])
P4 = os.path.join(T, "pub4"); os.makedirs(P4); open(os.path.join(P4, "catalog.json"), "w").write("{broken")
W4 = wp.workshop_mod.Workshop(P4, wp.leyline_css, wp.card_meta, wp.REALM_NAME)
check("broken catalog: an empty Workshop, no error", W4.serve("/wrath/mods", {})[0] == 200 and "empty right now" in W4.serve("/wrath/mods", {})[1].decode())
W5 = wp.workshop_mod.Workshop(os.path.join(T, "missing"), wp.leyline_css, wp.card_meta, wp.REALM_NAME)
check("no catalog at all: empty, and mod() is None", W5.mod("pings") is None and W5.serve("/wrath/mods", {})[0] == 200)

# share links use the real name
L = wp.links
sp = L.share_page("/wrath/m/pings", wp.card_meta, wp.render, wp.REALM_NAME, wp.community_realms, mods=Wk.mod).decode()
check("share link: real mod name", "Mod: Pings · Leyline" in sp and "the Pings mod" in sp)
check("share link: real description", "Alt-click the world map" in (re.search(r'property="og:description" content="([^"]*)"', sp) or [None, ""])[1])
check("share link: on to the Workshop page", 'href="/wrath/mods/pings"' in sp)
sp2 = L.share_page("/m/better-bags", wp.card_meta, wp.render, wp.REALM_NAME, wp.community_realms, mods=Wk.mod).decode()
check("share link: unknown mod keeps the generic card", "Better Bags" in sp2 and "/wrath/mods/" not in sp2)
sp3 = L.share_page("/m/pings", wp.card_meta, wp.render, wp.REALM_NAME, wp.community_realms, mods=lambda i: 1 / 0).decode()
check("share link: a broken catalog never breaks it", "go=m:pings" in sp3)
check("Leyline nav links the Workshop", 'href="/wrath/mods">Mods</a>' in wp.leyline_page().decode())

# through the real handler
srv = ThreadingHTTPServer(("127.0.0.1", 0), wp.PageHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path, ip="203.0.113.7"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request("GET", path, headers={"X-Forwarded-For": ip}); res = c.getresponse()
    return res.status, dict(res.getheaders()), res.read()
st, hd, body = get("/wrath/mods?kind=ui")
check("GET /wrath/mods?kind=ui through the portal", st == 200 and cards(body.decode()) == ["emote-wheel"])
check("CSP: no scripts, own images", "script-src 'none'" in hd.get("Content-Security-Policy", "") and "img-src 'self'" in hd.get("Content-Security-Policy", ""))
st, hd, body = get("/wrath/mods/pings/download")
check("GET the zip through the portal", st == 200 and hd.get("Content-Disposition", "").startswith("attachment;") and body[:2] == b"PK")
st, hd, body = get("/wrath/m/pings")
check("GET /wrath/m/pings uses the catalog", st == 200 and b"Mod: Pings" in body)
check("other paths unchanged", get("/wrath/modsx")[0] == 404 and get("/nope")[0] == 404)
codes = [get("/wrath/mods/pings/download", ip="198.51.100.20")[0] for _ in range(32)]
check("downloads: 30 a minute", codes.count(200) == 30 and codes[-1] == 429, (codes.count(200), codes[-1]))
codes = [get("/wrath/mods", ip="198.51.100.21")[0] for _ in range(602)]
check("pages: 600 a minute", codes.count(200) == 600 and codes[-1] == 429, (codes.count(200), codes[-1]))
srv.shutdown()

def visible(p):
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", p, flags=re.S))
allp = lp + dp + page("/wrath/mods/emote-wheel")[1] + page("/wrath/mods/dalaran-dice")[1] + page("/wrath/mods/nope")[1] + sp
texts = visible(allp) + " ".join(re.findall(r'content="([^"]*)"', allp)) + json.dumps(cat)
brand = re.findall(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard", texts)
check("no game-brand names", not brand, brand)

# ---------------------------------------------------------------- 3. the in-game Workshop tab with the generated list
if LUA:
    p = subprocess.run([LUA, os.path.join(STREAM, "tests", "test_wuui_workshop.lua"),
                        os.path.join(STREAM, "fui-web", "Interface", "AddOns", "WrathUnleashedUI"),
                        os.path.join(SLICE, "Interface", "AddOns", "WUModCatalog", "WUModCatalog.lua")],
                       capture_output=True, text=True)
    check("in-game Workshop tab reads the generated list", p.returncode == 0, p.stdout[-800:] + p.stderr)
else:
    print("SKIP in-game Workshop tab (no lua5.1)")

shutil.rmtree(T, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
