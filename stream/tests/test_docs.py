"""The Leyline docs (GET /wrath/docs, stream/docs.py over docs/leyline/*.md): every page renders, the Markdown
renderer escapes everything, unknown pages are 404s, no game-brand names, every relative link resolves, the portal
route answers, and the sign-in step ships the pages.

    python3 -I stream/tests/test_docs.py [stream/docs.py [stream/wrath_portal.py]]
"""
import html, http.client, importlib.util, os, re, shutil, subprocess, sys, tempfile, threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS_PY = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "docs.py"))
PORTAL = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(DOCS_PY), "wrath_portal.py"))
STREAM = os.path.dirname(DOCS_PY)
ROOT = os.path.dirname(STREAM)
DOCS_DIR = os.path.join(ROOT, "docs", "leyline")

os.environ.pop("WU_DOCS_DIR", None)
spec = importlib.util.spec_from_file_location("wu_docs_test", DOCS_PY)
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

BANNED = re.compile(r"(?i)world\s+of\s+warcraft|\bwow\b|warcraft|lich\s+king|blizzard")
def visible(page):
    return html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", page, flags=re.S)))

CSS = "/*LEYLINE-CSS*/"
names = [n for n, _ in d.PAGES]

# ---------------------------------------------------------------- 1. the page list and the files
check("ten pages, fixed order", names == ["index", "play", "commands", "mods", "publishing", "hosting", "launcher",
                                          "hero-key", "cross-server", "unite"], names)
on_disk = sorted(f[:-3] for f in os.listdir(DOCS_DIR) if f.endswith(".md"))
check("every page has its file in docs/leyline", all(n in on_disk for n in names), set(names) - set(on_disk))
check("every file in docs/leyline is on the page list", all(n in names for n in on_disk), set(on_disk) - set(names))
check("docs_dir finds the repo's docs/leyline", os.path.samefile(d.docs_dir(), DOCS_DIR), d.docs_dir())

# ---------------------------------------------------------------- 2. every page renders
pages = {}
for n in names:
    status, body = d.page(d.page_url(n), CSS, lambda p, t: f'<meta property="og:url" content="https://x{p}">', "WU")
    page = body.decode("utf-8")
    pages[n] = page
    check(f"{n}: 200", status == 200, status)
    check(f"{n}: one h1", page.count("<h1") == 1)
    check(f"{n}: Leyline look and docs CSS", CSS in page and ".ld-toc" in page and 'class="ly"' in page)
    check(f"{n}: table of contents lists every page", all(f'href="{d.page_url(m)}"' in page for m in names))
    check(f"{n}: current page marked", f'href="{d.page_url(n)}" aria-current="page"' in page)
    check(f"{n}: no script, no inline handlers", "<script" not in page.lower() and not re.search(r"\son[a-z]+=", page))
    check(f"{n}: link card for its own URL", f'content="https://x{d.page_url(n)}"' in page)
status, body = d.page("/wrath/docs")
check("/wrath/docs is the overview", status == 200 and b"What&#x27;s live and what&#x27;s planned" in body)

# ---------------------------------------------------------------- 3. content the owner asked for
idx = visible(pages["index"])
check("index: aims and a live/planned table", "The aims" in idx and "Live" in idx and "Planned" in idx
      and pages["index"].count("<table") == 1)
check("mods: the full field table and permissions", all(f"<code>{f}</code>" in pages["mods"] for f in
      ("id", "name", "version", "author", "licence", "kind", "wu", "description", "permissions", "screenshots",
       "links", "commands", "chat", "gossip", "spawns", "events", "db", "timers")))
import json
cats = [c["id"] for c in json.load(open(os.path.join(ROOT, "mods", "categories.json")))["categories"]]
check("mods: the category field and every category in categories.json", "<code>category</code>" in pages["mods"]
      and len(cats) == 13 and all(f"<td><code>{c}</code></td>" in pages["mods"] for c in cats), cats)
check("mods/publishing: no stale 'categories.json does not exist' note",
      "no such file" not in pages["mods"] and "does not exist" not in visible(pages["mods"]))
check("publishing: the category pages and the submit form as coming soon", "/wrath/mods/c/" in pages["publishing"]
      and "/wrath/mods/submit" in pages["publishing"] and "coming soon" in visible(pages["publishing"]))
check("mods: the Pings walkthrough", "Walkthrough: the Pings mod" in pages["mods"] and "realm/pings.lua" in pages["mods"])
spec_md = open(os.path.join(ROOT, "mods", "SPEC.md"), encoding="utf-8").read()
for rule in ("CAN_JOIN_LFG", "10 MB a file, 50 MB a package, 2000 files", "## Interface: 30300", "CREATE TABLE IF NOT EXISTS",
             "string.dump", "RegisterPacketEvent", "WUModCatalog"):
    check(f"mods matches SPEC.md: {rule}", rule in spec_md and html.escape(rule) in pages["mods"])
check("unite: marked as a proposal", "This page is a proposal" in visible(pages["unite"]))
check("hero-key: unverified parts marked to confirm", "To confirm" in visible(pages["hero-key"])
      and "herokey_v2.py" in pages["hero-key"] and "passport.py" in pages["hero-key"])
check("launcher: planned, Tauri, the decisions", all(s in visible(pages["launcher"]) for s in
      ("planned", "Tauri", "All mods are allowed", "No review queue yet", "No code signing yet")))
cs = visible(pages["cross-server"])
check("cross-server: never touch others, the three open layers, how to list",
      all(s in cs for s in ("We never touch other servers' clients", "The mod format", "The realm record and listing schema",
                            "The relay protocol", "How another server can list on Leyline")))
cmd = pages["commands"]
for c in (".wu", ".bug", ".stuck", ".recruit", ".buddy", ".build", ".go", ".armory", "/leyline", "/builder", "/ping", "/wheel"):
    check(f"commands: {c}", f"<code>{c}" in cmd)
host = visible(pages["hosting"])
check("hosting: leyline host, relay, presets, house rules, GM account, private and public",
      all(s in host for s in ("leyline host", "The relay", "Presets", "House rules", "The GM account", "Private and public")))
check("publishing: package, submit a link, the mods step", all(s in visible(pages["publishing"]) for s in
      ("Package your mod", "Submit a link", "The mods step")))

# ---------------------------------------------------------------- 4. escaping
evil = ('# Title <img src=x onerror=alert(1)>\n\n<script>alert(1)</script> **<b>bold</b>** `<i>code</i>`\n\n'
        '[click](javascript:alert(1)) [q](https://ok.example/"onmouseover=alert(1)) [p](mods.md#x"y) '
        '[d](data:text/html,hi) [e](//evil.example/) [ok](https://ok.example/a?b=1&c=2)\n\n'
        '| a | b |\n|---|---|\n| <svg onload=1> | `x\\|y` |\n\n- <iframe>\n\n> <style>x</style>\n\n```\n</code><script>\n```\n')
out, heads = d.render_markdown(evil)
check("escaping: no raw tags from the text", not re.search(r"<(script|img|iframe|svg|style|b|i)[\s>]", out), out)
check("escaping: tags shown as text", "&lt;script&gt;" in out and "&lt;img src=x onerror=alert(1)&gt;" in out
      and "&lt;svg onload=1&gt;" in out and "&lt;/code&gt;&lt;script&gt;" in out)
check("escaping: no javascript:, data: or protocol-relative links",
      "javascript:" not in out.split("click")[0] and 'href="javascript' not in out and 'href="data:' not in out
      and 'href="//' not in out)
check("escaping: an unsafe link keeps only its text", ">click<" not in out and "click" in out)
check("escaping: a quote can't break out of href", 'onmouseover=alert(1)"' not in out and '"onmouseover' not in out)
check("escaping: a safe https link, & escaped", 'href="https://ok.example/a?b=1&amp;c=2" rel="noopener noreferrer"' in out)
check("escaping: escaped pipe in a table cell", "<code>x|y</code>" in out)
check("headings get ids", heads and heads[0][1] == "title-img-srcx-onerroralert1", heads)
tmp = tempfile.mkdtemp(prefix="wu-docs-")
try:
    for n in names:
        shutil.copy(os.path.join(DOCS_DIR, n + ".md"), tmp)
    with open(os.path.join(tmp, "play.md"), "w") as f:
        f.write("# Play\n\n<script>alert('x')</script>\n\n<a href=\"https://x\" onclick=\"y\">raw</a>\n")
    with open(os.path.join(tmp, "secret.md"), "w") as f:
        f.write("# Secret\n")
    os.environ["WU_DOCS_DIR"] = tmp
    st, b = d.page("/wrath/docs/play", CSS)
    check("a file's raw HTML is escaped on the page", st == 200 and b"<script>alert" not in b and b"&lt;script&gt;" in b
          and b"&lt;a href=" in b and b'onclick="y"' not in b)
    st, b = d.page("/wrath/docs/secret", CSS)
    check("a file that isn't on the page list is never served", st == 404 and b"Secret" not in b.split(b"<article")[1])
    os.remove(os.path.join(tmp, "launcher.md"))
    st, _ = d.page("/wrath/docs/launcher", CSS)
    check("a listed page whose file is missing is a 404", st == 404)
    with open(os.path.join(tmp, "unite.md"), "w") as f:
        f.write("# Big\n" + "x" * (d.MAX_BYTES + 10))
    st, _ = d.page("/wrath/docs/unite", CSS)
    check("an oversized file is not served", st == 404)
finally:
    os.environ.pop("WU_DOCS_DIR", None)
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- 5. unknown pages are 404
for p in ("/wrath/docs/nope", "/wrath/docs/index.md", "/wrath/docs/INDEX", "/wrath/docs/../wrath_portal",
          "/wrath/docs/mods/extra", "/wrath/docs/%2e%2e", "/wrath/docs/", "/wrath/docs/hosting.md", "/wrath/docs/" + "a" * 500):
    st, b = d.page(p, CSS)
    check(f"404: {p[:40]}", st == 404 and b"Not found" in b)
check("match: only /wrath/docs and below", d.match("/wrath/docs") and d.match("/wrath/docs/mods")
      and not d.match("/wrath/docsx") and not d.match("/wrath"))

# ---------------------------------------------------------------- 6. no banned words
for n in names:
    src = open(os.path.join(DOCS_DIR, n + ".md"), encoding="utf-8").read()
    hits = BANNED.findall(src) + BANNED.findall(visible(pages[n]))
    check(f"{n}: no game-brand names", not hits, hits)
hits = BANNED.findall(open(DOCS_PY, encoding="utf-8").read())
check("docs.py: no game-brand names", not hits, hits)

# ---------------------------------------------------------------- 7. every relative link resolves
heads_of = {n: {h[1] for h in d.load(n)[1]} for n in names}
LOCAL_OK = ("/wrath", "/wrath/realms", "/wrath/mods", "/wrath/modes", "/wrath/armory", "/wrath/leyline", "/wrath/docs")
for n in names:
    src = open(os.path.join(DOCS_DIR, n + ".md"), encoding="utf-8").read()
    bad = []
    for url in d.links_in(src):
        if url.startswith("https://"):
            if d.resolve(url) is None: bad.append(url)
            continue
        if url.startswith("/"):
            if d.resolve(url) is None or url.split("#")[0].split("?")[0] not in LOCAL_OK: bad.append(url)
            continue
        if url.startswith("#"):
            if url[1:] not in heads_of[n]: bad.append(url)
            continue
        m = re.match(r"^([a-z0-9-]+)\.md(?:#([a-z0-9-]+))?$", url)
        if not m or m.group(1) not in heads_of or (m.group(2) and m.group(2) not in heads_of[m.group(1)]):
            bad.append(url)
    check(f"{n}: every link resolves", not bad, bad)
    rendered = re.findall(r'href="(/wrath/docs[^"]*)"', pages[n])
    broken = []
    for h in rendered:
        path, _, anchor = h.partition("#")
        target = "index" if path == "/wrath/docs" else path[len("/wrath/docs/"):]
        if target not in heads_of or (anchor and anchor not in heads_of[target]):
            broken.append(h)
    check(f"{n}: every rendered docs href points at a page and heading", not broken, broken)
    links_md = len([u for u in d.links_in(src)])
    links_html = len(re.findall(r"<a href=", pages[n].split("<article", 1)[1]))
    check(f"{n}: no link dropped", links_html >= links_md, (links_md, links_html))

# ---------------------------------------------------------------- 8. the portal route
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json")
pspec = importlib.util.spec_from_file_location("wp_docs", PORTAL)
wp = importlib.util.module_from_spec(pspec); pspec.loader.exec_module(wp)
check("portal: docs.py loaded", wp.docs is not None)
srv = ThreadingHTTPServer(("127.0.0.1", 0), wp.PageHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.request("GET", path)
    r = c.getresponse()
    return r.status, r.read(), dict(r.getheaders())
try:
    st, b, h = get("/wrath/docs")
    check("portal: GET /wrath/docs 200 in the Leyline look", st == 200 and b"ld-toc" in b and b"leyline-bg.webp" in b, st)
    check("portal: no scripts allowed on the page", "script-src 'none'" in h.get("Content-Security-Policy", ""))
    p = b.decode()
    nav = re.search(r'<nav class="ly-nav" id="ly-site-nav".*?</nav>', p, re.S)
    check("portal: the shared site nav, once, and no nav of the docs' own",
          nav and p.count('<nav class="ly-nav"') == 1 and 'class="grp"' not in p)
    check("portal: Docs in the shared nav, marked current", nav and re.search(
          r'<a href="/wrath/docs" class="on" aria-current="page">Docs</a>', nav.group(0)), nav and nav.group(0)[:300])
    check("portal: the shared footer and the skip link", '<footer class="ly-foot">' in p and 'id="main"' in p
          and 'href="#main"' in p)
    check("portal: the docs' table of contents kept", 'aria-label="Documentation"' in p)
    st, b, _ = get("/wrath/realms")
    check("portal: Docs is in the nav on the other pages too", b'<a href="/wrath/docs">Docs</a>' in b)
    st, b, _ = get("/wrath/docs/hosting/")
    check("portal: GET /wrath/docs/hosting/ 200", st == 200 and b"leyline host" in b, st)
    st, b, _ = get("/wrath/docs/cross-server?x=1")
    check("portal: a query string is ignored", st == 200, st)
    st, _, _ = get("/wrath/docs/nope")
    check("portal: unknown page 404", st == 404, st)
    st, _, _ = get("/wrath/docs/..%2fwrath_portal.py")
    check("portal: path tricks 404", st == 404, st)
finally:
    srv.shutdown()

# ---------------------------------------------------------------- 9. shipped with the sign-in step
fl = open(os.path.join(STREAM, "fastloop.sh"), encoding="utf-8").read()
check("fastloop.sh: installs docs.py and docs/leyline, backs them up",
      'install -m 644 docs.py "$WU/portal/docs.py"' in fl and 'docs/leyline/*.md "$WU/portal/docs/leyline/"' in fl
      and '"$BK/docs.py"' in fl and 'cp -a "$BK/docs" "$WU/portal/docs"' in fl)
check("fastloop.sh: checks /wrath/docs", "/wrath/docs" in fl)
check("fastloop.sh: bash syntax", subprocess.run(["bash", "-n", os.path.join(STREAM, "fastloop.sh")]).returncode == 0)
bat = open(os.path.join(STREAM, "Update sign-in and warm-up.bat"), encoding="utf-8").read()
check("sign-in bat: packs docs.py and the pages", "%DOCS%" in bat and "-C .. docs/leyline" in bat
      and "docs.py 2>/dev/null" in bat)
check("docs.py: finds the pages beside itself on the server", 'os.path.join(HERE, "docs", "leyline")' in open(DOCS_PY).read())

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
