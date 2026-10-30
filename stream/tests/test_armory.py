"""The web armory: realm/custom/armory-export.py against a fake database (sqlite, the same SQL), then
stream/armory.py and its hooks in wrath_portal.py and links.py: privacy, opt-out, bots, escaping, limits.

    python3 -I stream/tests/test_armory.py stream/wrath_portal.py
"""
import http.client, importlib.util, json, os, re, shutil, sqlite3, struct, sys, tempfile, threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(sys.argv[1]))
REPO = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="wu-armory-test-")
OUT, DBC = os.path.join(TMP, "armory"), os.path.join(TMP, "dbc")
os.makedirs(DBC)
os.environ.update(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
                  WU_STREAM="0", STREAM_HOST="wrath.example", WU_RELAY_LISTING="http://127.0.0.1:9/api/listing/realms.json",
                  WU_ARMORY_DIR=OUT, WU_ARMORY_OUT=OUT, WU_ARMORY_DBC=DBC, PUBLIC_HOST="play.example")

passed = failed = 0
def check(name, ok, extra=""):
    global passed, failed
    if ok: passed += 1; print("PASS", name)
    else: failed += 1; print("FAIL", name, extra)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

# --- fake client DBC files ---------------------------------------------------------------------------
def dbc(path, rows, fields):
    recs = b"".join(struct.pack(f"<{fields}I", *(list(r) + [0] * (fields - len(r)))) for r in rows)
    with open(path, "wb") as f:
        f.write(b"WDBC" + struct.pack("<4I", len(rows), fields, fields * 4, 1) + recs + b"\0")

def row(n, **at):
    r = [0] * n
    for k, v in at.items(): r[int(k[1:])] = v
    return r
# Paladin trees: 382 Holy (0), 383 Protection (1), 381 Retribution (2); one pet tab (class mask 0) ignored
dbc(os.path.join(DBC, "TalentTab.dbc"), [row(24, f0=382, f20=2, f22=0), row(24, f0=383, f20=2, f22=1),
                                         row(24, f0=381, f20=2, f22=2), row(24, f0=409, f20=0, f22=0)], 24)
dbc(os.path.join(DBC, "Talent.dbc"), [row(23, f0=1, f1=381, f4=1001, f5=1002, f6=1003),
                                      row(23, f0=2, f1=382, f4=2001), row(23, f0=3, f1=409, f4=3001)], 23)
dbc(os.path.join(DBC, "Achievement.dbc"), [row(62, f0=13, f39=10), row(62, f0=6, f39=10), row(62, f0=500, f39=25, f41=1)], 62)

# --- fake database: the AzerothCore tables the export reads (only the columns it uses, plus bait) --------
db = sqlite3.connect(":memory:", check_same_thread=False)
for name in ("acore_auth", "acore_characters", "acore_world"):
    db.execute(f"ATTACH DATABASE ':memory:' AS {name}")
db.executescript("""
CREATE TABLE acore_auth.account (id INTEGER PRIMARY KEY, username TEXT, last_ip TEXT, email TEXT);
CREATE TABLE acore_characters.characters (guid INTEGER PRIMARY KEY, account INT, name TEXT, race INT, class INT, gender INT,
  level INT, money INT, logout_time INT, online INT, totalKills INT, activeTalentGroup INT, deleteDate INT,
  position_x REAL);
CREATE TABLE acore_characters.guild (guildid INT, name TEXT);
CREATE TABLE acore_characters.guild_member (guildid INT, guid INT);
CREATE TABLE acore_characters.ov_armory_privacy (guid INT PRIMARY KEY, hidden INT, changed_at INT);
CREATE TABLE acore_characters.character_inventory (guid INT, bag INT, slot INT, item INT);
CREATE TABLE acore_characters.item_instance (guid INT, itemEntry INT, owner_guid INT);
CREATE TABLE acore_characters.character_talent (guid INT, spell INT, specMask INT);
CREATE TABLE acore_characters.character_achievement (guid INT, achievement INT, date INT);
CREATE TABLE acore_characters.arena_team (arenaTeamId INT, name TEXT, type INT, rating INT);
CREATE TABLE acore_characters.arena_team_member (arenaTeamId INT, guid INT, personalRating INT);
CREATE TABLE acore_characters.character_skills (guid INT, skill INT, value INT, max INT);
CREATE TABLE acore_characters.mail (id INT, receiver INT, subject TEXT);
CREATE TABLE acore_world.item_template (entry INT, name TEXT, Quality INT, ItemLevel INT);
INSERT INTO acore_auth.account VALUES (1,'SECRETACCT','203.0.113.77','x@example.com'),(2,'RNDBOT0042','',''),(3,'OTHERACCT','198.51.100.4','');
INSERT INTO acore_characters.characters VALUES
 (1,1,'Arthas',1,2,0,80,987654321,1761300000,0,1234,1,NULL,1.5),
 (2,1,'Hiddenone',2,1,0,80,5,1761300000,0,1,0,NULL,0),
 (3,2,'Botty',10,8,1,80,5,1761300000,1,1,0,NULL,0),
 (4,3,'Gonechar',3,1,0,30,5,1761300000,0,1,0,1761000000,0),
 (5,3,'Jaina',1,8,1,70,5,1761200000,1,0,0,NULL,0),
 (6,3,'Bad Name',1,1,0,10,5,1761200000,0,0,0,NULL,0);
INSERT INTO acore_characters.guild VALUES (1,'Tom & Jerry''s'),(2,'Botguild');
INSERT INTO acore_characters.guild_member VALUES (1,1),(1,5),(2,3);
INSERT INTO acore_characters.ov_armory_privacy VALUES (2,1,1761000000),(5,0,1761000000);
INSERT INTO acore_characters.character_inventory VALUES (1,0,0,101),(1,0,15,102),(1,0,23,103),(1,77,0,104),(3,0,0,105),(2,0,0,106);
INSERT INTO acore_characters.item_instance VALUES (101,50000,1),(102,50001,1),(103,50002,1),(104,50003,1),(105,50000,3),(106,50000,2);
INSERT INTO acore_characters.character_talent VALUES (1,1002,1),(1,2001,3),(1,3001,1);
INSERT INTO acore_characters.character_achievement VALUES (1,13,1761100000),(1,6,1760000000),(2,13,1761200000),(5,6,1760000000);
INSERT INTO acore_characters.arena_team VALUES (9,'Secret team',2,1650);
INSERT INTO acore_characters.arena_team_member VALUES (9,1,1700);
INSERT INTO acore_characters.character_skills VALUES (1,171,450,450),(1,185,300,450),(1,95,400,400),(2,171,1,75);
INSERT INTO acore_characters.mail VALUES (1,1,'MAILSECRET');
INSERT INTO acore_world.item_template VALUES (50000,'Helm of <img src=x onerror=alert(1)> "Doom"',4,264),
 (50001,'Frostmourne & Co',5,284),(50002,'BAGITEM Potion',1,1),(50003,'BAGITEM Sword',3,200);
""")

def mysql_esc(v):
    return "NULL" if v is None else str(v).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")

ran = []
def sqlite_runner(sql):
    """What `mysql -N -B` prints for the batch: tab-separated rows, marker rows included."""
    ran.append(sql)
    out = []
    for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
        for r in db.execute(stmt.rstrip(";")):
            out.append("\t".join(mysql_esc(v) for v in r))
    return "\n".join(out) + "\n"

ex = load("armory_export", os.path.join(REPO, "realm", "custom", "armory-export.py"))
NOW = 1761400000

# a stale file from before the player opted out: the export must remove it
os.makedirs(os.path.join(OUT, "c"))
with open(os.path.join(OUT, "c", "Hiddenone.json"), "w") as f: f.write('{"name":"Hiddenone"}')

n = ex.run(runner=sqlite_runner, out=OUT, now=NOW)
check("export: two characters (Arthas, Jaina)", n == 2, n)
index = json.load(open(os.path.join(OUT, "index.json")))
names = sorted(c["name"] for c in index["chars"])
check("export: index lists them", names == ["Arthas", "Jaina"], names)
check("export: opted out left out, old file removed", "Hiddenone" not in names and not os.path.exists(os.path.join(OUT, "c", "Hiddenone.json")))
check("export: bots left out", "Botty" not in names)
check("export: deleted characters left out", "Gonechar" not in names)
check("export: odd names left out", not any(" " in x for x in names))
check("export: only fixed SELECTs ran", all(not re.search(r"(?i)\b(insert|update|delete|replace|drop|create|alter)\b", s) for s in ran))
art = json.load(open(os.path.join(OUT, "c", "Arthas.json")))
check("export: talents per tree from the DBCs", art["specs"] == [[1, 0, 2], [1, 0, 0]], art["specs"])
check("export: achievements (counter not counted)", art["ach_count"] == 2 and art["ach_points"] == 20, (art["ach_count"], art["ach_points"]))
check("export: reached 80 day", art["reached80_day"] == "2025-10-22", art["reached80_day"])
check("export: last seen is a day", art["last_day"] == "2025-10-24", art["last_day"])
jai = json.load(open(os.path.join(OUT, "c", "Jaina.json")))
check("export: online now means seen today", jai["last_day"] == "2025-10-25", jai["last_day"])
check("export: equipped only (no bag or backpack items)", [i["slot"] for i in art["items"]] == [0, 15] and
      all("BAGITEM" not in i["name"] for i in art["items"]))
check("export: arena and professions", art["arena"] == [{"type": 2, "rating": 1650, "personal": 1700}] and
      [p["skill"] for p in art["prof"]] == [171, 185], (art["arena"], art["prof"]))
check("export: guild", art["guild"] == "Tom & Jerry's", art["guild"])
raw = "".join(open(os.path.join(dp, f)).read() for dp, _, fs in os.walk(OUT) for f in fs)
for bait in ("SECRETACCT", "203.0.113.77", "x@example.com", "987654321", "MAILSECRET", "BAGITEM", "Secret team",
             "Hiddenone", "Botty", "RNDBOT", "position", "account", "money", "guid"):
    check(f"export: never writes {bait!r}", bait not in raw)

# the privacy table missing (Lua not loaded yet): the export fails and the old files stay
db.execute("ALTER TABLE acore_characters.ov_armory_privacy RENAME TO ov_armory_privacy_x")
before = open(os.path.join(OUT, "index.json")).read()
try:
    ex.run(runner=sqlite_runner, out=OUT, now=NOW + 300); ok = False
except Exception:
    ok = True
check("export: no privacy table, no export (old files kept)", ok and open(os.path.join(OUT, "index.json")).read() == before)
db.execute("ALTER TABLE acore_characters.ov_armory_privacy_x RENAME TO ov_armory_privacy")
try:
    ex.parse_batch("#Q chars\n1\tA\n"); pb = False
except RuntimeError:
    pb = True
check("export: a cut-off answer is an error", pb)
check("export: mysql escapes undone", ex._field("a\\tb\\\\c\\n") == "a\tb\\c\n")
check("export: the real runner uses a read-only session",
      "SET SESSION TRANSACTION READ ONLY" in open(os.path.join(REPO, "realm", "custom", "armory-export.py")).read())

# --- the portal --------------------------------------------------------------------------------------
wp = load("wp", sys.argv[1])
wp.realm_status = lambda: {"online": True, "players": 4, "bots": 30}
A = wp.armory
check("armory.py loaded beside the portal", A is not None)
A.STAT_EVERY = 0
A.store.root = OUT
# planted by hand: a bot record and a hidden record in the index, a file with no index row
idx = json.load(open(os.path.join(OUT, "index.json")))
idx["chars"] += [dict(idx["chars"][0], name="Botplant", bot=True), dict(idx["chars"][0], name="Hidplant", hidden=True)]
json.dump(idx, open(os.path.join(OUT, "index.json"), "w"))
for nm in ("Botplant", "Hidplant", "Strayfile"):
    json.dump(dict(art, name=nm), open(os.path.join(OUT, "c", nm + ".json"), "w"))
# and a sheet with extra fields that must never be shown
json.dump(dict(art, money=987654321, account="SECRETACCT", bags=[{"name": "BAGITEM"}], mail="MAILSECRET", ip="203.0.113.77"),
          open(os.path.join(OUT, "c", "Arthas.json"), "w"))

def visible(b):
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", " ", b, flags=re.S))
BRANDS = re.compile(r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")

css = wp.leyline_css()
st, body = A.page("/wrath/armory/Arthas", {}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
body = body.decode()
check("sheet: 200", st == 200, st)
check("sheet: name, level, race and class", "<h1>Arthas</h1>" in body and "Level 80 Human" in body and "Paladin" in body)
check("sheet: item names escaped", "<img src=x" not in body and "&lt;img src=x onerror=alert(1)&gt; &quot;Doom&quot;" in body)
check("sheet: quality colours", "#c27bff" in body and "#ff8000" in body)
check("sheet: every slot drawn (paper doll)", body.count('class="ar-slot') == 19, body.count('class="ar-slot'))
check("sheet: guild escaped", "Tom &amp; Jerry&#x27;s" in body)
check("sheet: specs", "Retribution" in body and "1 / 0 / 2" in body and "active" in body)
check("sheet: achievements, kills, arena, professions", "20</span>" in body and "1234" in body and "2v2" in body
      and "Alchemy" in body and "Cooking" in body)
check("sheet: last seen a day", "Last seen 2025-10-24" in body)
check("sheet: share button to /wrath/u/Arthas", 'href="/wrath/u/Arthas"' in body and "https://play.example/wrath/u/Arthas" in body)
check("sheet: item names plain (no outside links)", not re.search(r'href="https?://(?!play\.example)', body))
for bait in ("987654321", "SECRETACCT", "BAGITEM", "MAILSECRET", "203.0.113.77", "Secret team"):
    check(f"sheet: never shows {bait!r}", bait not in body)
check("sheet: link card", 'property="og:url" content="https://play.example/wrath/armory/Arthas"' in body)
check("sheet: no game-brand names", not BRANDS.search(visible(body)), BRANDS.findall(visible(body)))
check("sheet: case-insensitive name", A.page("/wrath/armory/arthas", {}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)[0] == 200)

for nm in ("Hiddenone", "Botty", "Botplant", "Hidplant", "Strayfile", "Nobody", "Gonechar"):
    s2, b2 = A.page(f"/wrath/armory/{nm}", {}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
    check(f"sheet: {nm} is not shown (404, same page as unknown)", s2 == 404 and nm not in b2.decode())
s2, b2 = A.page("/wrath/armory/%3Cscript%3E", {}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
check("sheet: a bad name is a plain 404", s2 == 404 and "<script" not in b2.decode().lower().replace("<script nonce", ""))

st, ib = A.page("/wrath/armory", {}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
ib = ib.decode()
check("index: 200, heading, search", st == 200 and "<h1>Armory</h1>" in ib and 'name="q"' in ib and 'maxlength="12"' in ib)
check("index: showcase lists", all(x in ib for x in ("Recent level 80s", "Achievement points", "Guilds")))
check("index: Arthas a recent 80, with points", "/wrath/armory/Arthas" in ib and "20 points" in ib)
check("index: guilds count listed members only", "Tom &amp; Jerry&#x27;s" in ib and "2 listed" in ib and "Botguild" not in ib)
check("index: counts listed characters", ">2 characters<" in ib, re.findall(r">\d+ characters<", ib))
check("index: no hidden, bots or planted", all(x not in ib for x in ("Hiddenone", "Botty", "Botplant", "Hidplant", "Strayfile")))
check("index: says how to opt out", ".armory off" in ib and "Bots are not listed" in ib)
check("index: no game-brand names", not BRANDS.search(visible(ib)))
_, sb = A.page("/wrath/armory", {"q": ["art"]}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
res = sb.decode().split('id="ar-res"')[1].split("</section>")[0]
check("search: finds by part of a name", "/wrath/armory/Arthas" in res and "Jaina" not in res, res[:300])
_, sb = A.page("/wrath/armory", {"q": ['"><script>alert(1)</script>']}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
sb = sb.decode()
check("search: escaped and letters only", "<script>alert" not in sb and 'value="scriptalerts"' in sb, re.findall(r'value="[^"]*"', sb))
check("search: capped at 12", A.clean_query("a" * 500) == "a" * 12)
_, sb = A.page("/wrath/armory", {"q": ["hidden"]}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
check("search: opted out not found", "Hiddenone" not in sb.decode() and "Nobody called" in sb.decode())
_, sb = A.page("/wrath/armory", {"q": ["bot"]}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST)
check("search: bots not found", "Botty" not in sb.decode() and "Botplant" not in sb.decode())
check("armory missing: an empty page, not an error", A.Store(os.path.join(TMP, "none")).showcase()["count"] == 0)
s3, _ = A.page("/wrath/armory/Arthas", {}, css, wp.card_meta, wp.REALM_NAME, wp.PUBLIC_HOST, A.Store(os.path.join(TMP, "none")))
check("armory missing: sheets are 404", s3 == 404)

# --- share links: the u card ---------------------------------------------------------------------------
lb = wp.links.share_page("/wrath/u/arthas", wp.card_meta, wp.render, wp.REALM_NAME, who=A.card_line).decode()
check("u card: real character line", "Arthas, level 80 Human Paladin" in lb and 'content="Arthas · ' in lb)
check("u card: links the sheet", 'href="/wrath/armory/Arthas"' in lb)
for nm in ("Hiddenone", "Botty", "Botplant", "Nobody"):
    gb = wp.links.share_page(f"/u/{nm}", wp.card_meta, wp.render, wp.REALM_NAME, who=A.card_line).decode()
    check(f"u card: {nm} gets the generic card", f"{nm}&#x27;s profile" in gb and "/wrath/armory/" not in gb)
check("u card: a broken lookup is generic", "Arthas&#x27;s profile" in wp.links.share_page(
    "/u/Arthas", wp.card_meta, wp.render, wp.REALM_NAME, who=lambda n: 1 / 0).decode())
check("u card: an odd line is refused", "Arthas&#x27;s profile" in wp.links.share_page(
    "/u/Arthas", wp.card_meta, wp.render, wp.REALM_NAME, who=lambda n: {"name": "Arthas", "line": "<b>x</b>"}).decode())

# --- through the real handler: routing, headers, rate limits -------------------------------------------
srv = ThreadingHTTPServer(("127.0.0.1", 0), wp.PageHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path, ip="203.0.113.5"):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request("GET", path, headers={"X-Forwarded-For": ip}); res = c.getresponse()
    return res.status, dict(res.getheaders()), res.read().decode()
s, hd, b = get("/wrath/armory/Arthas")
check("GET sheet: 200, CSP, no scripts", s == 200 and "script-src 'none'" in hd.get("Content-Security-Policy", "") and "<script" not in b)
check("GET /wrath/armory/ (slash)", get("/wrath/armory/")[0] == 200)
check("GET /wrath/u/Arthas card", "level 80 Human Paladin" in get("/wrath/u/Arthas")[2])
check("GET leyline page links the armory", 'href="/wrath/armory"' in get("/wrath/leyline")[2])
codes = [get("/wrath/armory?q=ar", ip="198.51.100.20")[0] for _ in range(32)]
check("search rate limit (30/min)", codes.count(200) == 30 and codes[-1] == 429, (codes.count(200), codes[-1]))
codes = [get("/wrath/armory/Arthas", ip="198.51.100.21")[0] for _ in range(602)]
check("page rate limit (600/min)", codes.count(200) == 600 and codes[-1] == 429, (codes.count(200), codes[-1]))
srv.shutdown()

# --- no game-brand names in the new files' visible strings --------------------------------------------
for p in (os.path.join(HERE, "armory.py"), os.path.join(REPO, "realm", "custom", "armory-export.py")):
    txt = open(p, encoding="utf-8").read()
    check(f"no game-brand names in {os.path.basename(p)}", not BRANDS.search(txt), BRANDS.findall(txt))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
