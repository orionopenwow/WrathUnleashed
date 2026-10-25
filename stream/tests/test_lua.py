"""ov_slices.lua under a fake mod-ale (tests/test_ov_slices.lua, needs lua5.1) with the tiers made
from slices/mini.json by lua/tiers_lua.py, and the main realm's ov_main.lua beside it for the boost;
tiers_lua.py itself; lfg_ids.py on a synthetic LFGDungeons.dbc; displays.py's SQL.

    python3 -I tests/test_lua.py        (from the stream folder)

ov_main.lua is looked for in $OV_MAIN_LUA, then ..\\realm\\custom\\lua_scripts\\ov_main.lua (the
WrathUnleashed folder); without it the boost tests are skipped (and say so).
"""
import copy, importlib.util, json, os, struct, subprocess, sys, tempfile
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


doc = json.load(open(os.path.join(HERE, "slices/mini.json"), encoding="utf-8"))
tl = load("tl", os.path.join(HERE, "lua/tiers_lua.py"))

# 1. tiers_lua.py
tmp = tempfile.mkdtemp()
tiers_file = os.path.join(tmp, "ov_slices_tiers.lua")
with open(tiers_file, "w") as f:
    f.write(tl.lua(doc))
ordered = tl.ordered_tiers(doc)
check("tiers: order lists every tier once", sorted(doc["order"]) == sorted(t["key"] for t in doc["tiers"]))
check("tiers: base then Dalaran first", [t["key"] for _, t in ordered[:2]] == ["base", "dalaran"])
keys = {t["key"] for _, t in ordered}
check("tiers: the capitals, starter areas and Ebon Hold are streamed",
      {"stormwind", "orgrimmar", "northshire", "valley-of-trials", "ebon-hold"} <= keys)
kinds = {t["key"]: (t["kind"], t.get("faction")) for _, t in ordered}
check("tiers: each capital and starter area has its faction",
      kinds["stormwind"] == ("city", "alliance") and kinds["orgrimmar"] == ("city", "horde")
      and kinds["northshire"] == ("starter", "alliance") and kinds["valley-of-trials"] == ("starter", "horde")
      and kinds["ebon-hold"] == ("starter", "deathknight"))
check("tiers: every starter area has a home spot", all(t.get("home") for _, t in ordered if t["kind"] == "starter"))
dung = [t for _, t in ordered if t["kind"] == "dungeon" and t.get("levels")]
lv = [t["levels"][0] for t in dung]
check("tiers: levelling dungeons in level order among themselves", lv == sorted(lv), lv)
check("tiers: the earlier tiers are kept", all(k in doc["order"] for k in
      ("arenas", "violet-hold-toc", "naxx-os-voa", "battlegrounds", "heroic-rotation", "icc-toc")))
check("tiers: maxTier is the last tier (the budget decides what fits)", doc["maxTier"] == len(doc["order"]) - 1)
maps_seen = {}
dupes = []
for n, t in ordered:
    for m in t["maps"]:
        if "zone" not in m and "box" not in m:
            if m["id"] in maps_seen:
                dupes.append(m["id"])
            maps_seen[m["id"]] = n
check("tiers: no whole map in two tiers", not dupes, dupes)
re = copy.deepcopy(doc)
re["order"] = ["base", "dalaran", "icc-toc"] + [k for k in doc["order"] if k not in ("base", "dalaran", "icc-toc")]
out = tl.lua(re)
check("tiers: reordering moves the tier numbers", '[2] = { key = "icc-toc"' in out)
for bad, why in ((dict(doc, order=doc["order"] + ["nope"]), "unknown key"),
                 (dict(doc, order=doc["order"] + ["base"]), "key twice")):
    try:
        tl.lua(bad); ok = False
    except ValueError:
        ok = True
    check(f"tiers: refuses an order with an {why}", ok)
old = {"slice": "mini", "tiers": [{"tier": 1, "name": "Dalaran", "kind": "home", "maps": [{"id": 571, "zone": 4395}]},
                                 {"tier": 0, "name": "base", "maps": []}]}
check("tiers: an older file with tier numbers still works", '[1] = { key = "1", name = "Dalaran", kind = "home"' in tl.lua(old))
r = subprocess.run(["luac5.1", "-p", tiers_file], capture_output=True, text=True)
check("tiers: the generated file is valid Lua 5.1", r.returncode == 0, r.stderr)

# 2. the Lua tests (with ov_main.lua for the boost when it can be found)
ov_main = os.environ.get("OV_MAIN_LUA") or os.path.join(HERE, "..", "realm", "custom", "lua_scripts", "ov_main.lua")
args = ["lua5.1", os.path.join(HERE, "tests/test_ov_slices.lua"), os.path.join(HERE, "lua/ov_slices.lua"), tiers_file]
if os.path.isfile(ov_main):
    args.append(ov_main)
r = subprocess.run(args, capture_output=True, text=True)
lines = r.stdout.strip().splitlines()
print("\n".join(l for l in lines if l.startswith(("FAIL", "SKIP"))))
print(lines[-1] if lines else r.stderr)
check("ov_slices.lua fake-ALE tests", r.returncode == 0, r.stderr.strip()[-300:])
check("ov_main.lua boost tests ran" if os.path.isfile(ov_main) else "ov_main.lua not found: boost tests skipped (set OV_MAIN_LUA)",
      os.path.isfile(ov_main) or "SKIP" in r.stdout)
# the same tests under shuffled orders (base and Dalaran stay first): nothing may depend on positions
import random
for seed in (1, 3, 4):  # seed 2 shuffles every instance tier below the test mark in the starters-first order
    shuf = copy.deepcopy(doc)
    rest = shuf["order"][2:]
    random.Random(seed).shuffle(rest)
    shuf["order"] = shuf["order"][:2] + rest
    sf = os.path.join(tmp, f"shuffled-{seed}.lua")
    open(sf, "w").write(tl.lua(shuf))
    rs = subprocess.run(args[:3] + [sf] + args[4:], capture_output=True, text=True)
    check(f"ov_slices.lua fake-ALE tests, shuffled order {seed}", rs.returncode == 0,
          (rs.stdout.strip().splitlines() or [""])[-1] + " " + rs.stderr.strip()[-200:])
lua_tiers = {}
for line in r.stdout.splitlines():
    if line.startswith("TIERS "):
        for part in line[6:].split(";"):
            t, _, maps = part.partition("=")
            lua_tiers[int(t)] = sorted(int(m) for m in maps.split(",") if m)
json_tiers = {n: sorted(m["id"] for m in t["maps"]) for n, t in ordered}
check("lua tiers == mini.json tiers", lua_tiers == json_tiers, f"{lua_tiers} vs {json_tiers}")
check("mini.json maxTier in range", 1 <= doc["maxTier"] <= max(json_tiers))
check("mini.json has a budget", isinstance(doc.get("budgetMB"), int) and 1024 <= doc["budgetMB"] <= 8192)

# 3. lfg_ids.py
lfg = load("lfg", os.path.join(HERE, "lua/lfg_ids.py"))
fields, size = 49, 49 * 4
rows = [(241, 575, 1, 80, 80), (215, 608, 1, 75, 80), (261, -1, 6, 15, 80), (262, 0, 6, 80, 80), (300, 36, 1, 15, 23)]
body = b""
for id_, map_, type_, lo, hi in rows:
    rec = [0] * fields
    rec[0], rec[18], rec[19], rec[23], rec[26] = id_, lo, hi, map_, type_
    body += struct.pack(f"<{fields}i", *rec)
dbc = b"WDBC" + struct.pack("<4I", len(rows), fields, size, 1) + body + b"\0"
table = lfg.parse(dbc)
check("lfg: ids -> maps, randoms left out", table == {241: 575, 215: 608, 300: 36}, table)
levels = lfg.parse_levels(dbc)
check("lfg: level ranges", levels == {241: (80, 80), 215: (75, 80), 300: (15, 23)}, levels)
out = lfg.lua(table, levels)
check("lfg: Lua tables", "OV_STREAM_LFG = {" in out and "[241] = 575," in out and "OV_STREAM_LFG_LEVEL = {" in out and "[300] = { 15, 23 }," in out)
lfgf = os.path.join(tmp, "lfg.lua")
open(lfgf, "w").write(out)
check("lfg: valid Lua", subprocess.run(["luac5.1", "-p", lfgf]).returncode == 0)
try:
    lfg.parse(b"nope" + bytes(20)); bad = False
except ValueError:
    bad = True
check("lfg: refuses a non-DBC", bad)

# 4. displays.py
dp = load("dp", os.path.join(HERE, "server/displays.py"))
K = {t["key"]: n for n, t in ordered}
sql = dp.build_sql(doc, {1, K["violet-hold-toc"]})
check("displays: Dalaran by its box", "c.map = 571 AND c.position_x BETWEEN 5500.0 AND 6150.0" in sql and "c.position_z >= 450.0" in sql)
check("displays: Violet Hold tier maps", "c.map = 608" in sql and "g.map = 650" in sql)
check("displays: rows carry their tier", f"'{K['violet-hold-toc']}' FROM creature" in sql and "'1' FROM gameobject" in sql)
check("displays: other tiers left out", "533" not in sql)
sw = dp.build_sql(doc, {K["stormwind"], K["northshire"]})
check("displays: Stormwind and Northshire on map 0, each by its own box and tier",
      "c.position_x BETWEEN -9150.0 AND -8250.0" in sw and "c.position_x BETWEEN -9200.0 AND -8550.0" in sw
      and f"'{K['stormwind']}'" in sw and f"'{K['northshire']}'" in sw and "position_z" not in sw)
check("displays: creature_template_model", "creature_template_model" in sql)
check("displays: old schema fallback", "modelid4" in dp.build_sql(doc, {K["violet-hold-toc"]}, template_model=False))
inst = dp.build_sql(doc, set(), instances=True)
check("displays: --instances is every non-continent map, tier '-'", "c.map NOT IN (0, 1, 530, 571)" in inst and "'-'" in inst)
check("displays: tier list", dp.tiers_arg("0-2,5") == {0, 1, 2, 5})

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
