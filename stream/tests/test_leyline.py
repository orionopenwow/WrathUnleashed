"""The Leyline explainer page (GET /wrath/leyline): renders, links, link card, no game-brand names.

    python3 -I stream/tests/test_leyline.py stream/wrath_portal.py
"""
import importlib.util, os, re, sys
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json")
spec = importlib.util.spec_from_file_location("wp", sys.argv[1])
wp = importlib.util.module_from_spec(spec); spec.loader.exec_module(wp)
wp.realm_status = lambda: {"online": True, "players": 4, "bots": 30}

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

page = wp.leyline_page().decode()
check("renders a page", page.startswith("<!doctype") or "<html" in page.lower(), page[:80])
check("heading", "Leyline" in page and "An open network of realms and mods" in page)
for part in ("Play", "Host", "Mod", "Open", "Coming next"):
    check(f"section {part}", f">{part}<" in page)
check("play button", 'href="/wrath"' in page)
check("host guide link", "hosting/INSTALL-OPERATE.md" in page)
check("realm list link", 'href="/wrath/realms"' in page)
check("live players", "4 playing" in page and "30 bots" in page, re.findall(r"[^<>]*playing[^<>]*", page)[:2])
check("link card", 'property="og:url" content="https://' in page and "/wrath/leyline" in page and "twitter:card" in page)
visible = re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", page, flags=re.S))
bad = re.findall(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard", visible)
check("no game-brand names in visible text", not bad, bad)
check("own files said plainly", "3.3.5a game files" in page)
realms = wp.realms_page().decode()
check("realm list links here", 'href="/wrath/leyline"' in realms)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
