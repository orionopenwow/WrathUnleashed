"""The share links (stream/links.py, hooked into GET /r /h /q /m /u of wrath_portal.py): link cards,
the /wrath?go= deep link, strict path checks, escaping, the generic card, the rate limit, no game-brand names.

    python3 -I stream/tests/test_links.py stream/wrath_portal.py
"""
import http.client, importlib.util, os, re, sys, threading
from http.server import ThreadingHTTPServer

os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", PUBLIC_HOST="play.example",
                  WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.community_realms = lambda: ([{"id": "abcdefghijklmnop", "name": "Frost <Fun> Realm", "tagline": "Bring a \"coat\""}], True)

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

L = wp.links
check("links.py loaded beside the portal", L is not None)
if L is None:
    print(f"\n{passed}/{passed + failed} passed"); sys.exit(1)

def page(path):
    return L.share_page(path, wp.card_meta, wp.render, wp.REALM_NAME, wp.community_realms).decode()

def meta(p, key):
    m = re.search(r'(?:property|name)="' + re.escape(key) + r'" content="([^"]*)"', p)
    return m.group(1) if m else None

# parse: the allow-lists
good = {"/r/wrathunleashed": ("r", "wrathunleashed"), "/r/abcdefghijklmnop": ("r", "abcdefghijklmnop"),
        "/h/krasus-landing": ("h", "krasus-landing"), "/q/258": ("q", "258"), "/q/heroic-random": ("q", "heroic-random"),
        "/m/better-bags": ("m", "better-bags"), "/u/Arthasx": ("u", "Arthasx"), "/wrath/q/258": ("q", "258")}
for p, want in good.items():
    check(f"parse {p}", L.parse(p) == want, L.parse(p))
bad = ["/r", "/r/", "/r/UPPER", "/r/-lead", "/r/trail-", "/r/" + "a" * 33, "/h/a b", "/h/a%20b", "/q/<x>",
       "/q/258;x", "/m/ab", "/m/1mod", "/m/a--b", "/m/" + "a" * 33, "/u/A", "/u/" + "A" * 13, "/u/Name1",
       "/u/N%C3%A9", "/u/../etc", "/x/thing", "/r/a/b", "/q/" + "1" * 90, "/m/a.b", "/u/Ab\nC", "/u/Abc\n", "/q/258\n", "/r\n"]
for p in bad:
    check(f"refuse {p!r}", L.parse(p) is None, L.parse(p))
check("match owns bad links too", all(L.match(p) for p in ("/r", "/q/<x>", "/u/" + "A" * 13)))
check("match leaves other paths", not any(L.match(p) for p in ("/wrath", "/wrath/realms", "/x/y", "/rr/x", "/")))

# deep links
check("deep link q", L.deep_link("q", "258") == "/wrath?go=q:258")
check("deep link u", L.deep_link("u", "Arthasx") == "/wrath?go=u:Arthasx")
check("check_go round trip", L.check_go("h:krasus-landing") == ("h", "krasus-landing"))
check("check_go refuses junk", all(L.check_go(v) is None for v in ("q:<x>", "z:1", "q", "", None, "q:" + "1" * 50, "u:a/b")))

# pages
q = page("/q/258")
check("queue page renders", q.startswith("<!doctype html>"))
check("card url", meta(q, "og:url") == "https://play.example/q/258", meta(q, "og:url"))
check("card image 1200x630", meta(q, "og:image") == "https://play.example/wrath/art/wu-card.webp"
      and meta(q, "og:image:width") == "1200" and meta(q, "og:image:height") == "630")
check("twitter large card", meta(q, "twitter:card") == "summary_large_image" and meta(q, "twitter:image"))
check("card title", "258" in (meta(q, "og:title") or "") and meta(q, "og:title") == meta(q, "twitter:title"))
check("own description", meta(q, "og:description") and meta(q, "og:description") != wp.CARD_DESCRIPTION
      and meta(q, "og:description") == meta(q, "twitter:description") == meta(q, "description"))
check("refresh to deep link", 'http-equiv="refresh" content="1;url=/wrath?go=q:258"' in q)
check("button to deep link", 'href="/wrath?go=q:258"' in q)
check("tab title", "<title>" in q and "258" in q.split("<title>")[1].split("</title>")[0])

r = page("/r/abcdefghijklmnop")
check("community realm name, escaped", "Frost &lt;Fun&gt; Realm" in r and "<Fun>" not in r)
check("community tagline, escaped", "Bring a &quot;coat&quot;" in (meta(r, "og:description") or ""), meta(r, "og:description"))
o = page("/r/" + wp.REALM_NAME.lower())
check("official realm card", "official" in (meta(o, "og:description") or "").lower())
check("unknown realm still a card", meta(page("/r/nobody-here"), "og:title") and "go=r:nobody-here" in page("/r/nobody-here"))
check("wrath-prefixed canonical", meta(page("/wrath/u/Arthasx"), "og:url") == "https://play.example/wrath/u/Arthasx")
check("hangout page", "Krasus Landing" in page("/h/krasus-landing") and "go=h:krasus-landing" in page("/h/krasus-landing"))
check("mod page", "Better Bags" in page("/m/better-bags"))
check("player page", "Arthasx" in page("/u/Arthasx"))

for p in ("/q/<script>", "/r", "/u/" + "A" * 40, "/m/%3Cb%3E"):
    g = page(p)
    check(f"generic card for {p!r}", meta(g, "og:url") == "https://play.example/wrath" and 'url=/wrath"' in g
          and "<script>" not in g.lower().replace('<script nonce', '') and "go=" not in g, g[:120])

broken = L.share_page("/r/abcdefghijklmnop", wp.card_meta, wp.render, wp.REALM_NAME, lambda: 1 / 0).decode()
check("broken realm list still a card", meta(broken, "og:title") and "go=r:abcdefghijklmnop" in broken)

def visible(p):
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", p, flags=re.S))
allp = "".join(page(p) for p in list(good) + bad[:5])
brand = re.findall(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard", visible(allp) + " ".join(re.findall(r'content="([^"]*)"', allp)))
check("no game-brand names", not brand, brand)
check("no old brand names", not re.findall(r"(?i)open ?vanilla|openwow", visible(allp)))
check("says Leyline", "Leyline" in allp)

# through the real handler: routing, headers, rate limit
srv = ThreadingHTTPServer(("127.0.0.1", 0), wp.PageHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path, ip="203.0.113.5"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request("GET", path, headers={"X-Forwarded-For": ip}); res = c.getresponse()
    return res.status, dict(res.getheaders()), res.read().decode()
st, hd, body = get("/q/258")
check("GET /q/258 is 200", st == 200, st)
check("html, no-store, CSP", hd.get("Content-Type", "").startswith("text/html") and "default-src 'none'" in hd.get("Content-Security-Policy", ""))
check("GET bad link is 200 card", get("/q/%3Cscript%3E")[0] == 200 and "Traceback" not in get("/u/!!!")[2])
check("GET /wrath/m/better-bags", get("/wrath/m/better-bags")[0] == 200)
check("other paths unchanged", get("/nope")[0] == 404)
codes = [get("/h/x", ip="198.51.100.9")[0] for _ in range(125)]
check("rate limit like /wrath/leyline (120/min)", codes.count(200) == 120 and codes[-1] == 429, (codes.count(200), codes[-1]))
srv.shutdown()

# --- the deep link survives sign-in: /wrath -> /wrath/play -> /__gate -> the game page
check("go_param: a good link is carried", wp.go_param({"go": ["q:258"]}) == "&go=q:258", wp.go_param({"go": ["q:258"]}))
check("go_param: a bad link is dropped", wp.go_param({"go": ["q:<x>"]}) == "" and wp.go_param({"go": ["zz:1"]}) == "")
check("go_param: nothing given, nothing carried", wp.go_param({}) == "")
check("go_param: over-long dropped", wp.go_param({"go": ["u:" + "a" * 60]}) == "")

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
