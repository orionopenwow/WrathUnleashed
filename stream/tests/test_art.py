"""The play pages' art and theme (GET /wrath/art/<name>), the themed pages, the link-preview tags and the
plain fallback when the art is missing.

    python3 -I stream/tests/test_art.py stream/wrath_portal.py
"""
import http.client, importlib.util, os, sys, tempfile, threading
from http.server import ThreadingHTTPServer

PAGE_PORT = 18096
ART = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "www-files", "art")
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example",
                  WU_RELAY_LISTING="http://127.0.0.1:9/realms.json", WU_ART_DIR=ART)
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


# --- the art route: the allow-list, content types, caching
for name, ctype in (("wu-theme.css", "text/css"), ("wu-load-orion.webp", "image/webp"), ("wu-corner-tl.webp", "image/webp"),
                    ("wu-dragon-r.webp", "image/webp"), ("wu-divider.webp", "image/webp"), ("wu-card.webp", "image/webp"),
                    ("Cinzel-SemiBold.woff2", "font/woff2"), ("Cinzel-OFL.txt", "text/plain")):
    st, h, b = get("/wrath/art/" + name)
    with open(os.path.join(ART, name), "rb") as f:
        same = f.read() == b
    check(f"art {name}: 200 {ctype}, the file itself", st == 200 and h.get("content-type", "").startswith(ctype) and same,
          (st, h.get("content-type")))
st, h, b = get("/wrath/art/wu-theme.css")
check("art: cached a week, public", h.get("cache-control") == "public, max-age=604800", h.get("cache-control"))
check("art: readable cross-site (fonts need CORS)", h.get("access-control-allow-origin") == "*")
check("art: nosniff", h.get("x-content-type-options") == "nosniff")
st, h, b = get("/wrath/art/wu-theme.css", "HEAD")
check("art: HEAD has no body", st == 200 and b == b"")
with open(os.path.join(ART, "wu-card.webp"), "rb") as f:
    card = f.read()
check("card: a webp file", card[:4] == b"RIFF" and card[8:12] == b"WEBP")

# --- the allow-list blocks everything else, ../ included
for bad in ("../wrath_portal.py", "..%2fwrath_portal.py", "%2e%2e%2fwrath_portal.py", "..%2F..%2Fetc%2Fpasswd",
            "%2fetc%2fpasswd", "wu-theme.css%00.webp", "WU-THEME.CSS", "nope.webp", "", "art/wu-theme.css",
            "./wu-theme.css", "wu-theme.css/"):
    st, h, b = get("/wrath/art/" + bad)
    if bad == "wu-theme.css/":  # the router trims one trailing slash: still the allow-listed file, nothing else
        check("art: trailing slash is the same file", st in (200, 404) and b"import " not in b)
        continue
    check(f"art: {bad!r} refused", st == 404 and b"import " not in b and b"root:" not in b, st)
st, h, b = get("/wrath/../wrath_portal.py")
check("no file outside the art route", st == 404 and b"import " not in b)

# --- the pages use the theme, and the CSP lets them
st, h, b = get("/wrath")
page = b.decode()
csp = h.get("content-security-policy", "")
check("/wrath: 200, links the theme with a version", st == 200 and '/wrath/art/wu-theme.css?v=' in page)
check("/wrath: CSP allows our own images, fonts and styles", "img-src 'self'" in csp and "font-src 'self'" in csp
      and "style-src 'self' 'unsafe-inline'" in csp and "default-src 'none'" in csp, csp)
check("/wrath: themed body and panel", '<body class="wu">' in page and 'class="wu-panel' in page)
check("/wrath: the dragons crest", 'class="crest wu-brand"' in page)
st, h, b = get("/wrath/realms")
check("/wrath/realms: themed", st == 200 and b"wu-theme.css?v=" in b and b'class="wu-panel wide"' in b)
check("busy page themed", b"wu-theme.css?v=" in wp.busy_page() and b"Try now" in wp.busy_page())
check("error page themed", b"wu-theme.css?v=" in wp.error_page("x") and b"Try again" in wp.error_page("x"))

# --- link-preview cards (Open Graph and X) on the public pages
for path, page in (("/wrath", get("/wrath")[2].decode()), ("/wrath/realms", get("/wrath/realms")[2].decode()),
                   ("/wrath (signed-out page)", wp.signed_out_page().decode())):
    url = "https://play.example" + path.split(" ")[0]
    img = "https://play.example/wrath/art/wu-card.webp"
    want = ['<meta property="og:type" content="website">', f'<meta property="og:url" content="{url}">',
            f'<meta property="og:image" content="{img}">', '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">', '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:image" content="{img}">', '<meta property="og:title" content="',
            '<meta name="twitter:title" content="', '<meta property="og:description" content="Play Wrath of the Lich King 3.3.5a in your browser.',
            '<meta name="twitter:description" content="Play Wrath of the Lich King 3.3.5a in your browser.']
    missing = [w for w in want if w not in page]
    check(f"preview tags on {path}", not missing, missing)
    head = page.split("</head>", 1)[0]
    check(f"preview tags in the <head> of {path}", head.count('property="og:') >= 8 and 'twitter:card' in head)
check("no preview tags on the signed-in account page",
      b"og:title" not in wp.account_page("T", "WR1", "pw", "n") and b"og:title" not in wp.error_page("x"))
st, h, b = get("/wrath/art/wu-card.webp")
check("the card image is served", st == 200 and h.get("content-type") == "image/webp" and b == card)

# --- the art directory is missing: plain CSS, still a working page
wp.ART_DIR = tempfile.mkdtemp() + "/missing"
st, h, b = get("/wrath/art/wu-theme.css")
check("missing art dir: the art route 404s", st == 404)
st, h, b = get("/wrath")
page = b.decode()
check("missing art dir: /wrath still renders, no theme link", st == 200 and "wu-theme.css" not in page and "<style>" in page
      and "Signing you in" in page)
st, h, b = get("/wrath/realms")
check("missing art dir: realm list still renders", st == 200 and b"<h2>WrathUnleashed</h2>" in b and b"wu-theme.css" not in b)
check("missing art dir: busy page still renders", b"Try now" in wp.busy_page() and b"wu-theme.css" not in wp.busy_page())

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
