"""The GM console's look: GET /static/art/<name> (the allow-list, content types, no login needed), the shell and
the signed-out page linking the shared theme, the copy of the art matching stream/www-files/art, and the
fallback when the art is missing.

    python3 -I gmconsole/tests/test_art.py
"""
import http.client, importlib.util, os, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "server")
SHARED = os.path.join(HERE, "..", "..", "stream", "www-files", "art")
PORT = 18099
wu = tempfile.mkdtemp()
with open(os.path.join(wu, "gmconsole.env"), "w") as f:
    f.write("GM_TOKEN=" + "t" * 40 + "\n")
os.environ.update(GM_WU_DIR=wu, GM_PORT=str(PORT), GM_DOCKER="/bin/false")
os.environ.pop("GM_ART_DIR", None)
spec = importlib.util.spec_from_file_location("gm", os.path.join(SERVER, "gmconsole.py"))
gm = importlib.util.module_from_spec(spec); spec.loader.exec_module(gm)
srv = gm.ThreadingHTTPServer(("127.0.0.1", PORT), gm.Handler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, cookie=""):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    h = {"Host": f"127.0.0.1:{PORT}"}
    if cookie:
        h["Cookie"] = cookie
    c.request("GET", path, headers=h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


# the copy in static/art is the shared art, file for file
art = os.path.join(SERVER, "static", "art")
names = sorted(os.listdir(SHARED))
diff = [n for n in names if not os.path.exists(os.path.join(art, n))
        or open(os.path.join(art, n), "rb").read() != open(os.path.join(SHARED, n), "rb").read()]
check("static/art matches stream/www-files/art (copy it again after an art change)", not diff and sorted(os.listdir(art)) == names, diff)
check("every allow-listed file is in the kit", all(os.path.exists(os.path.join(art, n)) for n in gm.ART_TYPES))

for name, ctype in (("wu-theme.css", "text/css"), ("wu-load-orion.webp", "image/webp"), ("wu-corner-tl.webp", "image/webp"),
                    ("wu-dragon-l.webp", "image/webp"), ("Cinzel-SemiBold.woff2", "font/woff2")):
    st, h, b = get("/static/art/" + name)
    check(f"/static/art/{name}: 200 {ctype} without a login", st == 200 and h.get("content-type", "").startswith(ctype)
          and b == open(os.path.join(art, name), "rb").read(), (st, h.get("content-type")))
st, h, b = get("/static/art/wu-load-orion.webp")
check("art: cached, one Cache-Control header", h.get("cache-control") == "private, max-age=604800", h.get("cache-control"))
for bad in ("../gmconsole.py", "..%2fgmconsole.py", "%2e%2e%2f%2e%2e%2fgmconsole.py", "..%2f..%2fgmconsole.env", "app.js", "x.css", ""):
    st, h, b = get("/static/art/" + bad)
    check(f"art: {bad!r} refused", st == 404 and b"import " not in b and b"GM_TOKEN" not in b, st)
st, h, b = get("/static/app.js")
check("app.js still needs the login", st == 401)

st, h, b = get("/")
check("signed out: themed page", st == 401 and b"/static/art/wu-theme.css" in b and b"Open GM Console.bat" in b and b'class="wu"' in b)
check("signed out: no inline styles (the CSP blocks them)", b"style=" not in b)
check("CSP allows our own fonts", "font-src 'self'" in h.get("content-security-policy", ""))
st, h, b = get("/login?t=" + "t" * 40)
cookie = (h.get("set-cookie") or "").split(";")[0]
st, h, b = get("/", cookie)
check("signed in: the shell links the theme before app.css", st == 200 and 0 < b.find(b"wu-theme.css") < b.find(b"app.css")
      and b'<body class="wu">' in b, st)

gm.ART_DIR = os.path.join(tempfile.mkdtemp(), "missing")
st, h, b = get("/static/art/wu-theme.css")
check("missing art: 404", st == 404)
st, h, b = get("/", cookie)
check("missing art: the console still loads with app.css", st == 200 and b"/static/app.css" in b)
st, h, b = get("/static/app.css")
check("app.css is served (no login needed: styles only)", st == 200 and h.get("content-type", "").startswith("text/css"))

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
