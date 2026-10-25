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
check("displays: Dalaran by its box, the forest below it included", "c.map = 571 AND c.position_x BETWEEN 5500.0 AND 6150.0" in sql and "c.position_z" not in sql)
check("displays: a box's z min still works", "c.position_z >= 450.0" in dp.entry_cond("c", {"id": 571, "spawnBox": [0, 1, 0, 1, 450]}))
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

# 5. displays.py: player mounts (synthetic 3.3.5a Spell.dbc / SkillLineAbility.dbc / TaxiNodes.dbc)
def wdbc(fields, recs, strings=b"\0"):
    body = b"".join(struct.pack(f"<{fields}i", *r) for r in recs)
    return b"WDBC" + struct.pack("<4I", len(recs), fields, fields * 4, len(strings)) + body + strings


def spell(sid, name_off=0, eff=(0, 0, 0), aura=(0, 0, 0), misc=(0, 0, 0), trig=(0, 0, 0)):
    r = [0] * 234
    r[0] = sid
    r[71:74], r[95:98], r[110:113], r[116:119] = eff, aura, misc, trig
    r[136 + 3] = name_off  # a non-enUS locale column: the first non-empty one is the name
    return r


names = b"\0Swift Ram\0Big Bear\0Learning\0NPC Wolf\0Trainer Horse\0"
off = {n: names.index(n.encode() + b"\0") for n in ("Swift Ram", "Big Bear", "Learning", "NPC Wolf", "Trainer Horse")}
SPELLS = wdbc(234, [
    spell(1000, off["Swift Ram"], eff=(6, 0, 0), aura=(78, 0, 0), misc=(500, 0, 0)),     # spellbook (777)
    spell(1001, off["NPC Wolf"], eff=(6, 0, 0), aura=(78, 0, 0), misc=(501, 0, 0)),      # NPC only
    spell(1002, off["Learning"], eff=(36, 0, 0), trig=(1003, 0, 0)),                     # an item's learn spell
    spell(1003, off["Big Bear"], eff=(6, 6, 0), aura=(78, 32, 0), misc=(502, 0, 0)),     # what it teaches
    spell(1004, off["Big Bear"], eff=(6, 0, 0), aura=(78, 0, 0), misc=(503, 0, 0)),      # a speed variant
    spell(1005, eff=(6, 0, 0), aura=(78, 0, 0)),                                         # no creature
    spell(1006, aura=(78, 0, 0), misc=(504, 0, 0)),                                      # no effect
    spell(1007, off["Trainer Horse"], eff=(0, 0, 6), aura=(0, 0, 78), misc=(0, 0, 505)), # trainer, 3rd effect
    spell(1009, eff=(56, 0, 0), misc=(701, 0, 0)),                                       # Summon Voidwalker
    spell(1010, eff=(6, 0, 0), aura=(23, 0, 0), trig=(1011, 0, 0)),                      # a channel...
    spell(1011, eff=(28, 0, 0), misc=(702, 0, 0)),                                       # ...summons ghouls
    spell(1012, eff=(28, 0, 0), misc=(703, 0, 0)),                                       # an NPC's summon
    spell(1013, eff=(50, 0, 0), misc=(800, 0, 0)),                                       # a portal object
], names)
SLA = wdbc(14, [[i, 777, sp_] + [0] * 11 for i, sp_ in enumerate((1000, 1009, 1010, 1013), 1)])
TAXI = wdbc(24, [[1] + [0] * 21 + [600, 601], [2] + [0] * 23])
sp = dp.parse_spells(SPELLS)
check("mounts: Spell.dbc columns (effect 71, aura 95, misc 110, trigger 116, name 136+)",
      sp[1003] == ((6, 6, 0), (78, 32, 0), (502, 0, 0), (0, 0, 0), "Big Bear") and sp[1002][3] == (1003, 0, 0), sp.get(1003))
check("mounts: SkillLineAbility spell column", dp.parse_column(SLA, dp.SLA_FIELDS, (dp.SLA_SPELL,), "s") == {1000, 1009, 1010, 1013})
check("mounts: TaxiNodes MountCreatureID columns 22, 23", dp.parse_column(TAXI, dp.TAXI_FIELDS, dp.TAXI_MOUNT, "t") == {600, 601})
ent, n = dp.mount_entries(sp, {1000, 1002, 1007, 99999})
check("mounts: player spells, what they learn, same-name variants; not NPC-only, no-creature or no-effect",
      ent == {500, 502, 503, 505} and n == 4, (ent, n))
check("mounts: --all-mounts takes every aura-78 spell", dp.mount_entries(sp, None)[0] == {500, 501, 502, 503, 505})
player = {1000, 1002, 1007, 1009, 1010, 1013}
check("summons: pets and what a channel triggers, not an NPC's", dp.summon_entries(sp, player) == ({701, 702}, 2), dp.summon_entries(sp, player))
check("summons: summoned objects", dp.summon_entries(sp, player, dp.OBJECT_SUMMONS)[0] == {800})
osql = dp.objects_sql({800}, "0")
check("summons: object displays from gameobject_template", "'g', 0, t.displayId, '0'" in osql and "IN (800)" in osql)
tsql = dp.transports_sql(doc, {0, 1}, "0")
check("transports: type 15 to the base, type-11 elevators on the tier's whole map",
      "t.type = 15" in tsql and "g.map IN (571)" in tsql and "t.type = 11" in tsql and "'1' FROM gameobject g" in tsql
      and "position_x" not in tsql, tsql)
check("transports: none without tiers", "WHERE FALSE" in dp.transports_sql(doc, set(), None))
for bad, what in ((b"nope" + bytes(20), "not a DBC"), (wdbc(233, [[0] * 233]), "wrong column count")):
    try:
        dp.parse_spells(bad); refused = False
    except ValueError:
        refused = True
    check(f"mounts: refuses a Spell.dbc that is {what}", refused)
msql = dp.mounts_sql({502, 500}, "0")
check("mounts: models of the mounts and their passengers, tier 0, map unused",
      "creature_template_model m WHERE m.CreatureID IN (500, 502)" in msql and "vehicle_template_accessory WHERE entry IN (500, 502)" in msql
      and "SELECT DISTINCT 'c', 0, x.d, '0'" in msql)
check("mounts: the other-gender model too", "DisplayID_Other_Gender" in msql)
check("mounts: old schema and no accessory table",
      "t.modelid4" in dp.mounts_sql({1}, "0", False, False) and "vehicle_template_accessory" not in dp.mounts_sql({1}, "0", False, False))
check("mounts: none, empty query", "WHERE FALSE" in dp.mounts_sql(set(), "0"))
check("mounts: mini.json puts them in the base (tier 0)", dp.mounts_tier(doc, set(range(100)), False) == "0" == str(K["base"]))
check("mounts: not when the base tier is not asked for", dp.mounts_tier(doc, {1, 2}, False) is None)

# main() end to end: a fake docker (the database answers, no worldserver), the DBCs in --dbc.
dbcdir = os.path.join(tmp, "dbc"); os.makedirs(dbcdir, exist_ok=True)
for fn, b in (("Spell.dbc", SPELLS), ("skilllineability.dbc", SLA), ("TaxiNodes.dbc", TAXI)):
    open(os.path.join(dbcdir, fn), "wb").write(b)
fakebin = os.path.join(tmp, "fakebin"); os.makedirs(fakebin, exist_ok=True)
open(os.path.join(fakebin, "docker"), "w").write(r'''#!/usr/bin/env python3
import re, sys
a = sys.argv[1:]
if a[:1] == ["ps"] or "ov-ac-database" not in a:
    sys.exit(0)
q = sys.stdin.read()
if "SHOW TABLES LIKE 'creature_template_model'" in q: print("creature_template_model")
elif "SHOW TABLES LIKE 'vehicle_template_accessory'" in q: print("vehicle_template_accessory")
elif "SHOW COLUMNS FROM creature" in q: print("id1\tint")
elif "FROM spell_dbc" in q: sys.exit(1)
elif "FROM item_template" in q: print("1002\n0\n-5")
elif "FROM trainer_spell" in q: print("1007")
elif "FROM npc_trainer" in q: sys.exit(1)
elif "taxinodes_dbc" in q: print("0")
elif "t.type = 1" in q:
    if "t.type = 15" in q: print("g\t0\t900\t0")
    if "t.type = 11" in q: print("g\t571\t901\t1")
elif "player_totem_model" in q: print("c\t0\t4589\t0")
elif "gameobject_template t WHERE t.entry IN" in q: print("g\t0\t8000\t0")
elif "x.d" in q:
    for e in re.search(r"CreatureID IN \(([0-9, ]+)\)", q).group(1).split(", "): print(f"c\t0\t{int(e) * 10}\t0")
elif "FROM creature c" in q: print("c\t571\t100\t1")
''')
os.chmod(os.path.join(fakebin, "docker"), 0o755)
env = dict(os.environ, PATH=fakebin + os.pathsep + os.environ["PATH"])
env.pop("WU_DBC_DIR", None)
slice_file = os.path.join(HERE, "slices/mini.json")
r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "server/displays.py"), slice_file, "--tiers", "0-1", "--dbc", dbcdir],
                   capture_output=True, text=True, env=env)
lines = sorted(r.stdout.split("\n")[:-1])
check("mounts: main() prints the spawns, then the mounts as tier-0 lines", r.returncode == 0 and lines == sorted(
    ["c\t571\t100\t1", "g\t0\t900\t0", "g\t571\t901\t1", "c\t0\t4589\t0", "g\t0\t8000\t0"]
    + [f"c\t0\t{e * 10}\t0" for e in (500, 502, 503, 505, 600, 601, 701, 702)]), (r.returncode, lines, r.stderr[-300:]))
check("mounts: says what it read", "mounts:" in r.stderr and "4 mount spells" in r.stderr, r.stderr.strip()[-200:])
r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "server/displays.py"), slice_file, "--tiers", "0-1", "--dbc", dbcdir, "--no-mounts"],
                   capture_output=True, text=True, env=env)
check("mounts: --no-mounts (no mounts or summons; transports of tier 1 only)", r.returncode == 0 and r.stdout == "c\t571\t100\t1\ng\t571\t901\t1\n", r.stdout)
r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "server/displays.py"), slice_file, "--tiers", "0-1", "--dbc", os.path.join(tmp, "nowhere")],
                   capture_output=True, text=True, env=dict(env, WU_DBC_DIR=os.path.join(tmp, "nowhere2")))
check("mounts: no Spell.dbc anywhere fails soft (spawns kept, exit 0, a clear message naming the places tried)",
      r.returncode == 0 and r.stdout.startswith("c\t571\t100\t1\n") and "c\t0\t5000" not in r.stdout and "mounts: NOT included" in r.stderr and "nowhere2" in r.stderr
      and dp.HOST_DBC in r.stderr, (r.returncode, r.stdout, r.stderr[-300:]))

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
