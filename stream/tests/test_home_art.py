"""The launcher Home gallery's screenshots on the site (GET /wrath/art/home/<name>): the pattern allow-list, real
WebP / JPEG only, home.json only when it is a JSON object, short cache times, readable cross-site, and 410 under the
game data killswitch (they are game pictures).

    python3 -I stream/tests/test_home_art.py stream/wrath_portal.py
"""
import http.client, importlib.util, io, json, os, sys, tempfile, threading
from http.server import ThreadingHTTPServer

PAGE_PORT = 18097
ART = tempfile.mkdtemp()
FLAG = os.path.join(tempfile.mkdtemp(), "gamedata-off")
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example",
                  WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_ART_DIR=ART, WU_GAMEDATA_FLAG=FLAG)
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)

srv = ThreadingHTTPServer(("127.0.0.1", PAGE_PORT), wp.PageHandler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get(path, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", PAGE_PORT, timeout=20)
    c.request(method, path, headers={"X-Forwarded-For": "10.9.0.1"})
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
HOME = os.path.join(ART, "home")
os.makedirs(HOME)
files = {"hangout.webp": WEBP, "hangout-2.webp": WEBP, "mode-minigolf.webp": WEBP, "den.jpg": JPEG,
         "fake.webp": b"<html>not a picture</html>", "fake.jpg": WEBP, "big.webp": WEBP + b"\x00" * 1_600_000,
         "home.json": json.dumps({"version": 1, "slides": {"hangout": [{"file": "hangout.webp", "alt": "a", "credit": ""}]}}).encode(),
         "notes.txt": b"secret", "x.png": b"\x89PNG"}
for n, b in files.items():
    with open(os.path.join(HOME, n), "wb") as f:
        f.write(b)

for name, ctype, body in (("hangout.webp", "image/webp", WEBP), ("hangout-2.webp", "image/webp", WEBP),
                          ("mode-minigolf.webp", "image/webp", WEBP), ("den.jpg", "image/jpeg", JPEG)):
    st, h, b = get("/wrath/art/home/" + name)
    check(f"home/{name}: 200 {ctype}, the file", st == 200 and h.get("content-type") == ctype and b == body, (st, h.get("content-type")))
    check(f"home/{name}: an hour's cache, cross-site, nosniff", h.get("cache-control") == "public, max-age=3600"
          and h.get("access-control-allow-origin") == "*" and h.get("x-content-type-options") == "nosniff", h.get("cache-control"))
st, h, b = get("/wrath/art/home/home.json")
check("home.json: 200 JSON, five minutes' cache, cross-site (the launcher fetches it)",
      st == 200 and h.get("content-type", "").startswith("application/json") and json.loads(b)["slides"]["hangout"][0]["file"] == "hangout.webp"
      and h.get("cache-control") == "public, max-age=300" and h.get("access-control-allow-origin") == "*", (st, h.get("cache-control")))
for bad in ("fake.webp", "fake.jpg", "big.webp", "notes.txt", "x.png", "missing.webp", "Hangout.webp", "../home/hangout.webp",
            "..%2fwrath_portal.py", "sub/hangout.webp", "hangout.webp.txt", "-x.webp", "home.json.bak", ""):
    st, h, b = get("/wrath/art/home/" + bad)
    check(f"home/{bad!r} refused", st == 404 and b != WEBP and b"secret" not in b, st)
with open(os.path.join(HOME, "home.json"), "w") as f:
    f.write("[1, 2]")
check("home.json that is not an object: 404", get("/wrath/art/home/home.json")[0] == 404)
with open(os.path.join(HOME, "home.json"), "w") as f:
    f.write("{nope")
check("home.json that is not JSON: 404", get("/wrath/art/home/home.json")[0] == 404)
check("the old allow-list is untouched (an unknown name at the top 404s)", get("/wrath/art/hangout.webp")[0] == 404)

# the killswitch: the screenshots go (410), like the other game pictures
open(FLAG, "w").close()
st, h, b = get("/wrath/art/home/hangout.webp")
check("killswitch on: a screenshot answers 410", st == 410 and b != WEBP, st)
os.remove(FLAG)
check("killswitch off: back", get("/wrath/art/home/hangout.webp")[0] == 200)

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
