"""The control window's look: GET /art/<name> (the allow-list, content types, the Host check), the page linking
the shared theme with every id the script uses, and the fallback when the art is missing.

    python3 -I tools/control/test_control_art.py
"""
import http.client, importlib.util, os, re, sys, tempfile, threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18097
os.environ.update(WU_CONTROL_PORT=str(PORT), LOCALAPPDATA=tempfile.mkdtemp())
os.environ.pop("WU_ART_DIR", None)
spec = importlib.util.spec_from_file_location("control", os.path.join(HERE, "control.py"))
ctl = importlib.util.module_from_spec(spec); spec.loader.exec_module(ctl)
ART = os.path.join(HERE, "..", "..", "stream", "www-files", "art")

srv = ThreadingHTTPServer(("127.0.0.1", PORT), ctl.H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, host=f"127.0.0.1:{PORT}"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("GET", path, headers={"Host": host})
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


for name, ctype in (("wu-theme.css", "text/css"), ("wu-load-orion.webp", "image/webp"), ("wu-corner-br.webp", "image/webp"),
                    ("wu-dragon-l.webp", "image/webp"), ("Cinzel-SemiBold.woff2", "font/woff2")):
    st, h, b = get("/art/" + name)
    with open(os.path.join(ART, name), "rb") as f:
        same = f.read() == b
    check(f"/art/{name}: 200 {ctype}", st == 200 and h.get("content-type", "").startswith(ctype) and same, (st, h.get("content-type")))
st, h, b = get("/art/wu-theme.css")
check("art: cached, nosniff", "max-age" in h.get("cache-control", "") and h.get("x-content-type-options") == "nosniff")
for bad in ("../control.py", "..%2fcontrol.py", "%2e%2e%2f%2e%2e%2fUPDATES-PENDING.txt", "..%5ccontrol.py", "nope.css", ""):
    st, h, b = get("/art/" + bad)
    check(f"art: {bad!r} refused", st == 404 and b"import " not in b, st)
st, h, b = get("/art/wu-theme.css", host="evil.example")
check("art: another Host is refused", st == 403)

# the page: the theme linked, and every id and the script exactly as before
st, h, b = get("/?t=" + ctl.TOKEN)
page = b.decode()
check("page: 200, themed", st == 200 and '<body class="wu">' in page and re.search(r'/art/wu-theme\.css\?v=[0-9a-f]{10}"', page))
ids = ["health", "auto", "gmc", "check", "game", "you", "now", "cupd", "fin", "pending", "msg", "go", "run", "con", "hist"]
check("page: every id the script uses is there once", all(page.count(f'id="{i}"') == 1 for i in ids))
check("page: the header says Leyline Control with the dragons", 'class="brand wu-brand"><h1>Leyline Control</h1>' in page)
check("page: Launch all is the gold one", 'class="primary" id="go">Launch all' in page)
check("page: Autopilot ON turns gold (the script sets .primary)", 'a.className=s.autopilot?"primary":""' in page)
check("page: CSP keeps everything on this PC", "default-src 'self'" in h.get("content-security-policy", ""))
st, h, b = get("/")
check("page: still needs the token", st == 403)

# the art is missing: the art route 404s, the page still works with its own CSS
ctl.ART_DIR = ctl.Path(tempfile.mkdtemp()) / "missing"
st, h, b = get("/art/wu-theme.css")
check("missing art: 404", st == 404)
st, h, b = get("/?t=" + ctl.TOKEN)
check("missing art: the page still renders with its own styles", st == 200 and b"<style>" in b and b'id="go"' in b)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
