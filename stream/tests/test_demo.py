"""The Leyline guest pass ("Try Leyline in the Goldshire Inn"): stream/demo.py through wrath_portal.py,
against a fake realm backend (no account is made and no password is typed: the backend only records).
Also runs the realm script's tests (tests/test_ov_demo.lua) when lua5.1 is installed.

    python3 -I stream/tests/test_demo.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.parse
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STREAM = os.path.dirname(HERE)
PAGE_PORT = 18093
slices = tempfile.mkdtemp()
with open(os.path.join(slices, "mini.json"), "w") as f:
    json.dump({"slice": "mini", "maxTier": 6, "title": "Mini"}, f)
pool = os.path.join(slices, "demo-pool.txt")
with open(pool, "w") as f:
    f.write("# the operator's pool\nLYDEMO01 Visitoraa\nLYDEMO02 Visitorab\nWR000123 Sneaky\nLYDEMO03 bad_name\n")
for k in ("WU_GUEST_DEMO", "WU_DEMO_MINUTES", "WU_DEMO_PER_HOUR"):
    os.environ.pop(k, None)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_SLICE_DIR=slices, WU_STREAM="1", STREAM_HOST="wrath.example", WU_DEMO_POOL=pool,
                  WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.realm_status = lambda: {"online": True, "players": 4, "bots": 30}

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)


class FakeRealm:
    """Records what the portal asks of the realm. fail = {"begin", "end", "set_password"} to refuse."""
    def __init__(self):
        self.calls, self.fail, self.pw = [], set(), {}
    def _go(self, what, *a):
        self.calls.append((what,) + a)
        if what in self.fail:
            raise wp.SoapError("fault", f"fake {what} refused")
    def set_password(self, user, pw): self._go("set_password", user); self.pw[user] = pw
    def begin(self, user, secs): self._go("begin", user, secs)
    def end(self, user): self._go("end", user)
    def did(self, what): return [c for c in self.calls if c[0] == what]


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t


check("demo.py loads beside the portal (python -I)", wp.guest is not None and type(wp.guest).__name__ == "Demo")
realm, clock = FakeRealm(), Clock()
dm = importlib.util.module_from_spec(importlib.util.spec_from_file_location("dm", os.path.join(STREAM, "demo.py")))
dm.__spec__.loader.exec_module(dm)
css = lambda: wp.LEYLINE_CSS.replace("ART_BG", wp.art_url("leyline-bg.webp")).replace("ART_FONT", wp.art_url("Cinzel-SemiBold.woff2"))
g = dm.Demo(realm, wp.sessions, wp.slice_info, wp.stream_on, lambda: wp.STREAM_HOST, css, clock=clock, monotonic=clock)
wp.guest = g   # the portal's handler uses this one

# -- the pool file ----------------------------------------------------------------------------------
entries = dm.parse_pool(open(pool).read())
check("pool: guest accounts only, bad lines skipped", entries == [("LYDEMO01", "Visitoraa"), ("LYDEMO02", "Visitorab")], entries)
check("pool file has no passwords in the format", all(len(l.split()) <= 2 for l in open(pool).read().splitlines() if not l.startswith("#")))

# -- HTTP through the portal ----------------------------------------------------------------------
srv = ThreadingHTTPServer(("127.0.0.1", PAGE_PORT), wp.PageHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path, ip="203.0.113.5", cookie=""):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=10)
    h = {"X-Forwarded-For": ip}
    if cookie: h["Cookie"] = cookie
    c.request("GET", path, headers=h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode("utf-8", "replace")

st, hd, body = get("/wrath?demo=1")
check("off by default (no WU_GUEST_DEMO): 404 page", st == 404 and "closed" in body, st)
check("off: nothing asked of the realm", realm.calls == [], realm.calls)
check("off: no pool loaded", g.pool.passes == {})
st, hd, body = get("/wrath/demo")
check("section preview renders while off", st == 200 and "Try Leyline in the Goldshire Inn" in body, st)

os.environ["WU_GUEST_DEMO"] = "1"
st, hd, body = get("/wrath?demo=1")
loc = hd.get("Location", "")
check("on: redirect to the stream gate", st == 302 and loc.startswith("https://wrath.example/__gate?code="), (st, loc))
check("first pass handed out", g.pool.passes["LYDEMO01"]["state"] == "busy" and g.pool.passes["LYDEMO01"]["ip"] == "203.0.113.5")
check("pool recycled once before first use (unknown passwords)", ("end", "LYDEMO02") in realm.calls and ("end", "LYDEMO01") in realm.calls)
check("pass opened on the realm: new password, then begin 20 min",
      realm.calls[-2:] == [("set_password", "LYDEMO01"), ("begin", "LYDEMO01", 1200)], realm.calls[-3:])
pw1 = realm.pw["LYDEMO01"]
check("password is random and fits the realm", re.fullmatch(r"[A-Za-z0-9]{16}", pw1) is not None)
check("no password in the URL", pw1 not in loc)
st, hd, _ = get(urllib.parse.urlsplit(loc).path + "?" + urllib.parse.urlsplit(loc).query)
check("gate lands on /?demo=1", st == 302 and hd.get("Location") == "/?demo=1", hd.get("Location"))
cookie = hd.get("Set-Cookie", "").split(";")[0]
st, hd, env = get("/__env.js", cookie=cookie)
envobj = json.loads(env.split("=", 1)[1].split(";\n", 1)[0])
check("env: the guest login", st == 200 and envobj.get("user") == "LYDEMO01" and envobj.get("pass") == pw1)
check("env: the character to seat (no character select)", envobj.get("char") == "Visitoraa" and envobj.get("demo") == "1", envobj)
check("env: the streamed slice", envobj.get("slice") == "mini" and envobj.get("slice_tier") == "6")
check("env: the sign-up link", envobj.get("signup") == "https://play.openvanilla.app/login?next=%2Fwrath")
check("not stream-marked (ov_slices.lua leaves guests alone)", not [c for c in realm.calls if "ovstream" in str(c)])
st, _, _ = get("/__auth", cookie=cookie)
check("the guest may load the page and /data", st == 200)

n_calls = len(realm.calls)
st, hd, _ = get("/wrath?demo=1")
check("same visitor again: the same pass, nothing new on the realm", st == 302 and len(realm.calls) == n_calls
      and g.pool.passes["LYDEMO01"]["state"] == "busy" and g.pool.passes["LYDEMO02"]["state"] != "busy")
check("one session per pass", sum(1 for s in wp.sessions.sessions.values() if s["user"] == "LYDEMO01") == 1)
st, hd, env = get("/__env.js", cookie=cookie)
check("the older page session is closed", st == 401)

st, hd, _ = get("/wrath?demo=1", ip="198.51.100.7")
check("a second visitor gets the second pass", st == 302 and g.pool.passes["LYDEMO02"]["ip"] == "198.51.100.7")
st, hd, body = get("/wrath?demo=1", ip="192.0.2.9")
check("pool empty: 'every pass is in use'", st == 503 and "Every guest pass is in use" in body, st)

# -- expiry and recycling -------------------------------------------------------------------------
clock.t += 20 * 60 + 1
realm.calls.clear()
g.sweep()
check("ended passes: guests logged out on the realm", ("end", "LYDEMO01") in realm.calls and ("end", "LYDEMO02") in realm.calls)
check("ended passes: passwords changed", realm.pw["LYDEMO01"] != pw1 and len(realm.did("set_password")) == 2)
check("ended passes: page sessions gone", not any(s["user"].startswith("LYDEMO") for s in wp.sessions.sessions.values()))
check("ended passes rest first", {p["state"] for p in g.pool.passes.values()} == {"cool"})
st, _, body = get("/wrath?demo=1", ip="192.0.2.9")
check("resting passes are not handed out", st == 503)
clock.t += 61
st, _, _ = get("/wrath?demo=1", ip="192.0.2.9")
check("after the rest, free again", st == 302 and g.pool.passes["LYDEMO01"]["ip"] == "192.0.2.9")

# -- a realm that doesn't answer ------------------------------------------------------------------
realm.fail = {"begin"}
st, _, body = get("/wrath?demo=1", ip="192.0.2.10")
check("begin refused: 503, and that pass is set aside", st == 503 and g.pool.passes["LYDEMO02"]["state"] == "dirty", st)
realm.fail = {"set_password"}
g.sweep()
check("recycling refused: still set aside", g.pool.passes["LYDEMO02"]["state"] == "dirty")
realm.fail = set()
g.sweep()
check("recycling retried: free again (no visitor got in)", g.pool.passes["LYDEMO02"]["state"] == "free")

# -- rate limit -----------------------------------------------------------------------------------
os.environ["WU_DEMO_PER_HOUR"] = "2"
clock.t += 3600 * 2
g.sweep(); clock.t += 61; g.sweep()
ip = "203.0.113.77"
results = []
for _ in range(3):
    st, _, body = get("/wrath?demo=1", ip=ip)
    results.append(st)
    clock.t += 20 * 60 + 1; g.sweep(); clock.t += 61; g.sweep()
check("rate limit per IP per hour", results == [302, 302, 429], results)
os.environ.pop("WU_DEMO_PER_HOUR")

# -- turning it off again -------------------------------------------------------------------------
os.environ["WU_GUEST_DEMO"] = "0"
st, _, _ = get("/wrath?demo=1", ip="203.0.113.200")
check("WU_GUEST_DEMO=0 closes it at once", st == 404)
os.environ["WU_STREAM"] = "0"; os.environ["WU_GUEST_DEMO"] = "1"
st, _, body = get("/wrath?demo=1", ip="203.0.113.201")
check("streaming off: no pass", st == 503 and "resting" in body)
os.environ["WU_STREAM"] = "1"; os.environ["WU_GUEST_DEMO"] = "0"

# -- the section ----------------------------------------------------------------------------------
sec = dm.section_html()
check("section: title and Try it button", "Try Leyline in the Goldshire Inn" in sec and '>Try it</a>' in sec)
check("section: goes to /wrath?demo=1", 'href="/wrath?demo=1"' in sec)
check("section: Leyline page style (ly-panel, ly-btn, ly-fine)", 'class="ly-panel ly-demo"' in sec and 'class="ly-btn"' in sec and "ly-fine" in sec)
check("section CSS uses the page's tokens", "var(--ly-panel" in dm.SECTION_CSS and "var(--ly-line" in dm.SECTION_CSS)
check("one public base URL", dm.SIGNUP_URL.startswith(dm.PUBLIC_BASE_URL) and dm.PUBLIC_BASE_URL == "https://play.openvanilla.app")
lua_src = open(os.path.join(STREAM, "..", "realm", "custom", "lua_scripts", "ov_demo.lua"), encoding="utf-8").read()
check("ov_demo.lua's base URL matches demo.py's", f'local PUBLIC_BASE_URL = "{dm.PUBLIC_BASE_URL}"' in lua_src)
_, _, prev = get("/wrath/demo")
pages = [sec, prev, g.notice("x", "y").decode()] + [get("/wrath?demo=1", ip="203.0.113.9")[2]]
BRAND = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard|openvanilla|open vanilla|openwow")
for i, pg in enumerate(pages):
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", pg, flags=re.S))
    check(f"page {i}: no game-brand or old names in visible text", not BRAND.findall(visible), BRAND.findall(visible))
lua_strings = re.findall(r'"([^"\n]*)"', re.sub(r"--[^\n]*", "", lua_src))
bad = [s for s in lua_strings if BRAND.search(s.replace("play.openvanilla.app", ""))]
check("ov_demo.lua: no game-brand or old names in its strings", not bad, bad)
lp = wp.leyline_page().decode()
check("the Leyline page is unchanged by this (still renders)", "<h1>Leyline</h1>" in lp)

# -- the client page --------------------------------------------------------------------------------
js = open(os.path.join(STREAM, "www-files", "wrath-page.js"), encoding="utf-8").read()
check("wrath-page.js: guest pass keeps the cover up past the character list",
      "export function guestPass" in js and "if (guest && name === 'charselect') return;" in js)

# -- the slice ------------------------------------------------------------------------------------
doc = json.load(open(os.path.join(STREAM, "slices", "mini.json"), encoding="utf-8"))
tier = next((t for t in doc["tiers"] if t["key"] == "goldshire-inn"), None)
check("slice: a goldshire-inn tier", tier is not None)
check("slice: kind base (opens no place in the realm rule)", tier and tier["kind"] == "base")
check("slice: right after Northshire in the order", doc["order"].index("goldshire-inn") == doc["order"].index("northshire") + 1)
check("slice: maxTier still the last tier", doc["maxTier"] == len(doc["order"]) - 1)
m = tier["maps"][0]
inn = (-9460.3, 18.9)
b = m["box"]
check("slice: the inn is inside the box and spawn box", b[0] <= inn[0] <= b[1] and b[2] <= inn[1] <= b[3] and m["spawnBox"][:4] == b)
tile = lambda v: int(32 - v / (1600 / 3))
check("slice: its ground tiles are Azeroth_31_49 / Azeroth_32_49", {(tile(y), tile(x)) for x in b[:2] for y in b[2:]} == {(31, 49), (32, 49)})
north = next(t for t in doc["tiers"] if t["key"] == "northshire")["maps"][0]
nb, mg = north["box"], north["marginTiles"]
ntx = range(tile(nb[3]) - mg, tile(nb[2]) + mg + 1); nty = range(tile(nb[1]) - mg, tile(nb[0]) + mg + 1)
check("slice: Northshire's margin already streams those tiles", 31 in ntx and 32 in ntx and 49 in nty, (list(ntx), list(nty)))
tl_spec = importlib.util.spec_from_file_location("tl", os.path.join(STREAM, "lua", "tiers_lua.py"))
tl = importlib.util.module_from_spec(tl_spec); tl_spec.loader.exec_module(tl)
check("slice: tiers_lua.py accepts it", 'key = "goldshire-inn"' in tl.lua(doc) and 'kind = "base"' in tl.lua(doc))

# -- the operator script ----------------------------------------------------------------------------
sh = os.path.join(STREAM, "server", "demo-pool.sh")
r = subprocess.run(["bash", "-n", sh], capture_output=True, text=True)
check("demo-pool.sh: shell syntax", r.returncode == 0, r.stderr)
src = open(sh, encoding="utf-8").read()
check("demo-pool.sh: never prints or stores the password", "echo \"$pw" not in src and "$pw\" >>" not in src and "unset pw" in src)
check("stream-up.sh installs demo.py", 'install -m 644 "$ST/demo.py" "$WU/portal/demo.py"' in open(os.path.join(STREAM, "server", "stream-up.sh")).read())

# -- the realm script -----------------------------------------------------------------------------
lua = shutil.which("lua5.1") or shutil.which("luajit")
if lua:
    r = subprocess.run([lua, os.path.join(HERE, "test_ov_demo.lua"), os.path.join(STREAM, "..", "realm", "custom", "lua_scripts", "ov_demo.lua")],
                       capture_output=True, text=True)
    check("ov_demo.lua fake-ALE tests", r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1] + r.stderr[-300:])
else:
    print("SKIP ov_demo.lua fake-ALE tests (no lua5.1)")

srv.shutdown()
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
