#!/usr/bin/env python3
"""The creature and game-object displays spawned on a slice's maps, from the realm's database.

Run on the server (from /srv/wrath/stream): prints kind<TAB>map<TAB>displayId<TAB>tier lines
("c" creature, "g" game object) for `wenilla-host --deps / --size-report --displays`.

    python3 -I displays.py slices/mini.json [--tiers 0-7] [--instances] [--sql]

The tier column says which tier's map entry the spawn is in, so two tiers on one continent
(Stormwind City and Northshire Valley on map 0) each get their own creatures. --instances also
prints every spawn on every map that is not a continent (0, 1, 530, 571), with tier "-": that is
what "Size report.bat" measures each instance with.

--sql prints the query instead of running it. It runs through the database container the way
deploy.sh does (docker exec ov-ac-database mysql ... acore_world), read-only.

A map entry with "spawnBox": [xmin, xmax, ymin, ymax(, zmin)] only takes spawns inside that box
(Dalaran on Northrend, the capitals, the starter areas); every other map takes all its spawns.
Tier numbers are positions in the slice's "order" list (or the "tier" fields of an older file).
Creature models come from creature_template_model (AzerothCore since 2023), else from
creature_template.modelid1..4.

Player mounts (the tier with "mounts": true, the base): the engine seats a rider only once the
mount's model has loaded, and mounts are not spawned anywhere, so they are listed on their own.
A mount spell applies aura 78 (SPELL_AURA_MOUNTED) with EffectMiscValue = a creature_template
entry, whose model the server sends as UNIT_FIELD_MOUNTDISPLAYID. That is in Spell.dbc (the
server's own copy), read with SkillLineAbility.dbc and TaxiNodes.dbc from the first of:
--dbc DIR, $WU_DBC_DIR, ../client-data/dbc beside this script, /srv/wrath/client-data/dbc (the
ov-client-data volume), the worldserver container's DataDir/dbc (ov-ac-worldserver; DataDir from
its AC_DATA_DIR, else worldserver.conf, else /azerothcore/env/dist/data). Player mounts are the
aura-78 spells in SkillLineAbility (the spellbook: skill 777 Mounts and the class mounts), or taught
by an item, a trainer, a quest or playercreateinfo_spell_custom (custom realms), or learned or
triggered by one of those, plus every aura-78 spell with the same name (the speed variants of
Invincible, the Headless Horseman's mount, the Touring Rocket...). The flight-master mounts
(TaxiNodes MountCreatureID) and the passengers a vehicle mount carries (the mammoth's vendors,
vehicle_template_accessory) go along. Lines: c<TAB>0<TAB>displayId<TAB>tier (the tier decides, the
map is not used). Without Spell.dbc it says so and prints the spawns only.

The same player spells' summons go to that tier too: SPELL_EFFECT_SUMMON 28 and SUMMON_PET 56
(warlock demons, the DK's ghouls and Army of the Dead, the water elemental, shadowfiend, totems,
companion pets...) as creatures, the object summons (portals, soulwells, bobbers: effects 50, 76,
104-107) as game objects, and the race totem models (player_totem_model). Hunter pets are whatever
beast was tamed, so they are not listed. Transports (game object type 15: ships, zeppelins,
gunships) go to the base, since the server shows them continent-wide; elevators and lifts (type 11)
go to the tier whose map they are on, the whole map, not only the spawnBox.
--no-mounts leaves them out; --all-mounts takes every aura-78 spell (NPC and quest mounts too).
"""
import json
import os
import struct
import subprocess
import sys

DB = ["docker", "exec", "-i", "ov-ac-database", "sh", "-c",
      'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B acore_world']
CONTINENTS = (0, 1, 530, 571)


def tiers_arg(s: str) -> set[int]:
    out = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def ordered_tiers(doc: dict) -> list[tuple[int, dict]]:
    """[(tier number, tier)]: positions in "order", else the "tier" fields (as lua/tiers_lua.py)."""
    order = doc.get("order")
    if order is None:
        return [(int(t.get("tier", -1)), t) for t in doc.get("tiers", [])]
    by_key = {t.get("key"): t for t in doc.get("tiers", [])}
    return [(i, by_key[k]) for i, k in enumerate(order) if k in by_key]


def entry_cond(alias: str, m: dict) -> str:
    mid = int(m["id"])
    box = m.get("spawnBox")
    if not box:
        return f"{alias}.map = {mid}"
    x0, x1, y0, y1 = (float(v) for v in box[:4])
    z = f" AND {alias}.position_z >= {float(box[4])}" if len(box) > 4 else ""
    return (f"({alias}.map = {mid} AND {alias}.position_x BETWEEN {x0} AND {x1} "
            f"AND {alias}.position_y BETWEEN {y0} AND {y1}{z})")


def map_filter(alias: str, slice_doc: dict, tiers: set[int]) -> list[tuple[str, str]]:
    """[(tier label, condition)] for every map entry of the chosen tiers."""
    out = []
    for n, t in ordered_tiers(slice_doc):
        if n not in tiers:
            continue
        conds = [entry_cond(alias, m) for m in t.get("maps", [])]
        if conds:
            out.append((str(n), " OR ".join(conds)))
    return out


# creature spawn ids: AzerothCore master has id1..id3; older cores (and some forks) have one `id`
CREATURE_IDS = "c.id1, c.id2, c.id3"


def selects(alias: str, label: str, cond: str, template_model: bool) -> list[str]:
    lab = "'" + label.replace("'", "") + "'"
    if alias == "g":
        return [f"SELECT DISTINCT 'g', g.map, t.displayId, {lab} FROM gameobject g "
                f"JOIN gameobject_template t ON t.entry = g.id WHERE ({cond}) AND t.displayId <> 0"]
    if template_model:
        return [f"SELECT DISTINCT 'c', c.map, m.CreatureDisplayID, {lab} FROM creature c "
                f"JOIN creature_template_model m ON m.CreatureID IN ({CREATURE_IDS}) WHERE ({cond})"]
    return [f"SELECT DISTINCT 'c', c.map, t.modelid{i}, {lab} FROM creature c JOIN creature_template t "
            f"ON t.entry IN ({CREATURE_IDS}) WHERE ({cond}) AND t.modelid{i} <> 0" for i in range(1, 5)]


def build_sql(slice_doc: dict | None, tiers: set[int], template_model: bool = True, instances: bool = False) -> str:
    parts = []
    for alias in ("c", "g"):
        for label, cond in (map_filter(alias, slice_doc, tiers) if slice_doc else []):
            parts += selects(alias, label, cond, template_model)
        if instances:
            cont = ", ".join(str(m) for m in CONTINENTS)
            parts += selects(alias, "-", f"{alias}.map NOT IN ({cont})", template_model)
    if not parts:
        return "SELECT 1 FROM DUAL WHERE FALSE;\n"
    return " UNION ".join(parts) + ";\n"


def run(sql: str) -> str:
    return subprocess.run(DB, input=sql, capture_output=True, text=True, check=True).stdout


# --- player mounts -------------------------------------------------------------------------------
# Column indexes in the 3.3.5a DBC records, from AzerothCore's format strings (DBCfmt.h; every
# character, 'x' included, is one 4-byte column), not from DBCStructure.h's comments (TaxiNodes'
# are one off). SpellEntryfmt is 234 columns: Effect 71-73, EffectApplyAuraName 95-97,
# EffectMiscValue 110-112, EffectTriggerSpell 116-118, SpellName 136-151 (string offsets).
SPELL_FIELDS, SP_EFFECT, SP_AURA, SP_MISC, SP_TRIGGER, SP_NAME = 234, 71, 95, 110, 116, 136
SLA_FIELDS, SLA_SPELL = 14, 2              # SkillLineAbilityfmt "niiiixxiiiiixx"
TAXI_FIELDS, TAXI_MOUNT = 24, (22, 23)     # TaxiNodesEntryfmt "nifffssssssssssssssssxii"
AURA_MOUNTED = 78                          # SPELL_AURA_MOUNTED
# Effects whose EffectTriggerSpell a player's spell goes on to cast: LEARN_SPELL, TRIGGER_MISSILE,
# TRIGGER_SPELL, FORCE_CAST(_WITH_VALUE), TRIGGER_SPELL_WITH_VALUE, TRIGGER_MISSILE_SPELL_WITH_VALUE,
# TRIGGER_SPELL_2, FORCE_CAST_2 (SharedDefines.h); and auras PERIODIC_TRIGGER_SPELL 23,
# PROC_TRIGGER_SPELL 42 (Army of the Dead's ghouls, a channel's summons).
LEARNS = (36, 32, 64, 140, 141, 142, 148, 151, 160)
TRIGGER_AURAS = (23, 42)
SUMMONS = (28, 56)                         # SPELL_EFFECT_SUMMON, SPELL_EFFECT_SUMMON_PET: a creature
OBJECT_SUMMONS = (50, 76, 104, 105, 106, 107)  # TRANS_DOOR, SUMMON_OBJECT_WILD, SUMMON_OBJECT_SLOT1-4
DBC_DIR = "/azerothcore/env/dist/data"     # docker-compose.prod.yml's AC_DATA_DIR (and the image's)
HOST_DBC = "/srv/wrath/client-data/dbc"    # bound into the ov-client-data volume (RUNBOOK step 4)
WORLDSERVER = "ov-ac-worldserver"


def dbc_records(data: bytes, fields: int, what: str):
    """(record offset, string block offset, count) of a WDBC file with `fields` columns."""
    if len(data) < 20 or data[:4] != b"WDBC":
        raise ValueError(f"{what} is not a WDBC file")
    n, f, size, _strings = struct.unpack_from("<4I", data, 4)
    if f != fields or size != fields * 4:
        raise ValueError(f"{what} has {f} columns of {size} bytes, not the 3.3.5a {fields}")
    if 20 + n * size > len(data):
        raise ValueError(f"{what} is cut short")
    return 20, 20 + n * size, n, size


def dbc_string(data: bytes, strings: int, off: int) -> str:
    if off <= 0:
        return ""
    end = data.find(b"\0", strings + off)
    return data[strings + off:end if end >= 0 else len(data)].decode("utf-8", "replace")


def parse_spells(data: bytes) -> dict[int, tuple]:
    """Spell.dbc: {id: (effects, auras, misc values, trigger spells, name)}, three of each."""
    base, strings, n, size = dbc_records(data, SPELL_FIELDS, "Spell.dbc")
    out = {}
    for r in range(n):
        o = base + r * size
        col = lambda c: struct.unpack_from("<3i", data, o + 4 * c)
        names = struct.unpack_from("<16I", data, o + 4 * SP_NAME)
        name = next((dbc_string(data, strings, x) for x in names if x), "")
        out[struct.unpack_from("<I", data, o)[0]] = (col(SP_EFFECT), col(SP_AURA), col(SP_MISC),
                                                     col(SP_TRIGGER), name)
    return out


def parse_column(data: bytes, fields: int, cols: tuple[int, ...], what: str) -> set[int]:
    """Every non-zero value of the given columns."""
    base, _, n, size = dbc_records(data, fields, what)
    return {v for r in range(n) for c in cols
            if (v := struct.unpack_from("<i", data, base + r * size + 4 * c)[0]) > 0}


def mount_entries(spells: dict[int, tuple], player: set[int] | None) -> tuple[set[int], int]:
    """(creature entries, spell count) of the aura-78 spells players cast. `player`: the spells
    players have (spellbook, items, trainers, quests), None for every aura-78 spell."""
    mounts = {sid: {m for a, m, e in zip(s[1], s[2], s[0]) if e and a == AURA_MOUNTED and m > 0}
              for sid, s in spells.items()}
    mounts = {sid: m for sid, m in mounts.items() if m}
    if player is None:
        chosen = set(mounts)
    else:
        chosen = {s for s in reach(spells, player) if s in mounts}
        names = {spells[s][4] for s in chosen if spells[s][4]}
        chosen |= {s for s in mounts if spells[s][4] in names}
    return {m for s in chosen for m in mounts[s]}, len(chosen)


def reach(spells: dict[int, tuple], player: set[int]) -> set[int]:
    """`player` and every spell they learn or go on to cast (an item's "learn" spell, a summon a
    channel triggers)."""
    seen, todo = set(), [s for s in player if s in spells]
    while todo:
        sid = todo.pop()
        if sid in seen:
            continue
        seen.add(sid)
        e, a, _, trig, _ = spells[sid]
        todo += [t for k, au, t in zip(e, a, trig)
                 if (k in LEARNS or (k and au in TRIGGER_AURAS)) and t in spells and t not in seen]
    return seen


def summon_entries(spells: dict[int, tuple], player: set[int] | None, effects=SUMMONS) -> tuple[set[int], int]:
    """(entries, spell count) the players' spells summon: creatures for SUMMONS (pets, guardians,
    totems, companions), game objects for OBJECT_SUMMONS (portals, soulwells, bobbers). None: every
    spell's."""
    pool = set(spells) if player is None else reach(spells, player)
    out, n = set(), 0
    for sid in pool:
        e, _, misc, _, _ = spells[sid]
        got = {m for k, m in zip(e, misc) if k in effects and m > 0}
        if got:
            out |= got
            n += 1
    return out, n


def mounts_sql(entries: set[int], label: str, template_model: bool = True, accessories: bool = True) -> str:
    """The models of these creatures and of the passengers they carry, and the other-gender model
    the server may pick instead (creature_model_info.DisplayID_Other_Gender)."""
    if not entries:
        return "SELECT 1 FROM DUAL WHERE FALSE;\n"
    ids = ", ".join(str(e) for e in sorted(entries))
    lab = "'" + label.replace("'", "") + "'"
    who = f"({ids})" + (f" OR {{col}} IN (SELECT accessory_entry FROM vehicle_template_accessory "
                        f"WHERE entry IN ({ids}))" if accessories else "")
    if template_model:
        models = [f"SELECT m.CreatureDisplayID AS d FROM creature_template_model m WHERE m.CreatureID IN "
                  + who.format(col="m.CreatureID")]
    else:
        models = [f"SELECT t.modelid{i} AS d FROM creature_template t WHERE (t.entry IN "
                  + who.format(col="t.entry") + f") AND t.modelid{i} <> 0" for i in range(1, 5)]
    m = " UNION ".join(models)
    return (f"SELECT DISTINCT 'c', 0, x.d, {lab} FROM ({m}) x WHERE x.d <> 0 UNION "
            f"SELECT DISTINCT 'c', 0, i.DisplayID_Other_Gender, {lab} FROM creature_model_info i "
            f"JOIN ({m}) y ON y.d = i.DisplayID WHERE i.DisplayID_Other_Gender <> 0;\n")


def objects_sql(entries: set[int], label: str) -> str:
    """The displays of summoned game objects."""
    if not entries:
        return "SELECT 1 FROM DUAL WHERE FALSE;\n"
    ids = ", ".join(str(e) for e in sorted(entries))
    lab = "'" + label.replace("'", "") + "'"
    return (f"SELECT DISTINCT 'g', 0, t.displayId, {lab} FROM gameobject_template t "
            f"WHERE t.entry IN ({ids}) AND t.displayId <> 0;\n")


def transports_sql(doc: dict, tiers: set[int], base: str | None) -> str:
    """Ships, zeppelins and gunships (gameobject type 15, the `transports` table) go to the base:
    the server shows a continent's transports to everyone on it, wherever they are, and they cross
    continents. Elevators and lifts (type 11) spawned on a tier's maps go to that tier, its whole
    map (the server sends them map-wide), not only its spawnBox."""
    parts = []
    if base is not None:
        lab = "'" + base + "'"
        parts.append(f"SELECT DISTINCT 'g', 0, t.displayId, {lab} FROM gameobject_template t "
                     f"WHERE t.type = 15 AND t.displayId <> 0")
    for n, t in ordered_tiers(doc):
        if n not in tiers:
            continue
        maps = sorted({int(m["id"]) for m in t.get("maps", [])})
        if maps:
            ids = ", ".join(str(m) for m in maps)
            parts.append(f"SELECT DISTINCT 'g', g.map, t.displayId, '{n}' FROM gameobject g JOIN "
                         f"gameobject_template t ON t.entry = g.id WHERE g.map IN ({ids}) AND t.type = 11 "
                         f"AND t.displayId <> 0")
    return (" UNION ".join(parts) + ";\n") if parts else "SELECT 1 FROM DUAL WHERE FALSE;\n"


TOTEMS_SQL = "SELECT DISTINCT 'c', 0, DisplayId, '{tier}' FROM player_totem_model WHERE DisplayId <> 0;\n"


def mounts_tier(doc: dict, tiers: set[int], forced: bool) -> str | None:
    """The tier label mounts go to: the chosen tier with "mounts": true (else 0 with --mounts)."""
    for n, t in ordered_tiers(doc):
        if t.get("mounts") and n in tiers:
            return str(n)
    return "0" if forced and 0 in tiers else None


def _docker(args: list[str], binary: bool = False):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout if binary else r.stdout.decode(errors="replace")


def _pick(names: list[str], want: str) -> str | None:
    return next((n for n in names if n.lower() == want.lower()), None)


def dbc_reader(argv: list[str], tried: list[str]):
    """A function name -> bytes|None over the first dbc folder that has Spell.dbc, else None."""
    dirs = []
    if "--dbc" in argv:
        dirs.append(argv[argv.index("--dbc") + 1])
    if os.environ.get("WU_DBC_DIR"):
        dirs.append(os.environ["WU_DBC_DIR"])
    dirs += [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client-data", "dbc"), HOST_DBC]
    for d in dirs:
        tried.append(d)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        if _pick(names, "Spell.dbc"):
            def read(want, d=d, names=names):
                n = _pick(names, want)
                return open(os.path.join(d, n), "rb").read() if n else None
            return read, d
    # The worldserver's own DataDir, inside its container.
    ps = _docker(["ps", "--format", "{{.Names}}"]) or ""
    running = [n for n in ps.split() if n]
    cands = [WORLDSERVER] if WORLDSERVER in running else []
    cands += [n for n in running if n.startswith("ov-ac-") and "world" in n and n not in cands]
    for c in cands:
        env = _docker(["exec", c, "sh", "-c", 'printf %s "$AC_DATA_DIR"']) or ""
        if not env:
            conf = _docker(["exec", c, "sh", "-c", "cat /azerothcore/env/dist/etc/worldserver.conf 2>/dev/null"]) or ""
            for line in conf.splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "DataDir":
                    env = v.strip().strip('"')
        data_dir = (env or DBC_DIR).rstrip("/")
        if data_dir in (".", ""):
            data_dir = DBC_DIR
        d = data_dir + "/dbc"
        tried.append(f"{c}:{d}")
        names = (_docker(["exec", c, "ls", d]) or "").split()
        if _pick(names, "Spell.dbc"):
            def read(want, c=c, d=d, names=names):
                n = _pick(names, want)
                return _docker(["exec", c, "cat", f"{d}/{n}"], binary=True) if n else None
            return read, f"{c}:{d}"
    return None, None


# What players are taught: (query, what) per table; a table a core does not have is skipped.
PLAYER_SPELL_SQL = [
    ("SELECT spellid_1 FROM item_template UNION SELECT spellid_2 FROM item_template UNION "
     "SELECT spellid_3 FROM item_template UNION SELECT spellid_4 FROM item_template UNION "
     "SELECT spellid_5 FROM item_template", "items"),
    ("SELECT SpellId FROM trainer_spell", "trainers"),
    ("SELECT SpellID FROM npc_trainer", "trainers (old table)"),
    ("SELECT RewardSpell FROM quest_template UNION SELECT RewardDisplaySpell FROM quest_template", "quests"),
    ("SELECT Spell FROM playercreateinfo_spell_custom", "start spells"),
    ("SELECT Spell FROM skilllineability_dbc", "skilllineability_dbc"),
]
SPELL_DBC_SQL = ("SELECT ID, Effect_1, Effect_2, Effect_3, EffectAura_1, EffectAura_2, EffectAura_3, "
                 "EffectMiscValue_1, EffectMiscValue_2, EffectMiscValue_3, EffectTriggerSpell_1, "
                 "EffectTriggerSpell_2, EffectTriggerSpell_3, IFNULL(Name_Lang_enUS, '') FROM spell_dbc")
TAXI_DBC_SQL = "SELECT MountCreatureID_1 FROM taxinodes_dbc UNION SELECT MountCreatureID_2 FROM taxinodes_dbc"


def soft(sql: str) -> list[list[str]]:
    try:
        return [l.split("\t") for l in run(sql).splitlines() if l.strip()]
    except (subprocess.CalledProcessError, OSError):
        return []


def ints(rows: list[list[str]]) -> set[int]:
    return {int(r[0]) for r in rows if r and r[0].lstrip("-").isdigit() and int(r[0]) > 0}


PLAYER_SUMMONS: dict[str, set[int]] = {"c": set(), "g": set()}


def player_mounts(argv: list[str], all_mounts: bool) -> tuple[set[int] | None, str]:
    """(creature entries, what was read) of the player and taxi mounts; None when no Spell.dbc."""
    tried: list[str] = []
    read, where = dbc_reader(argv, tried)
    if read is None:
        return None, "no Spell.dbc in " + ", ".join(tried)
    try:
        spells = parse_spells(read("Spell.dbc") or b"")
    except ValueError as e:
        return None, f"{where}: {e}"
    for r in soft(SPELL_DBC_SQL + ";\n"):  # the realm's own spell rows override the DBC's
        if len(r) >= 14 and r[0].isdigit():
            v = [int(x) if x.lstrip("-").isdigit() else 0 for x in r[1:13]]
            spells[int(r[0])] = (tuple(v[0:3]), tuple(v[3:6]), tuple(v[6:9]), tuple(v[9:12]), r[13])
    notes = [f"{len(spells)} spells from {where}"]
    player: set[int] | None = set()
    sla = read("SkillLineAbility.dbc")
    try:
        player |= parse_column(sla, SLA_FIELDS, (SLA_SPELL,), "SkillLineAbility.dbc") if sla else set()
    except ValueError as e:
        notes.append(str(e))
    if not player:
        notes.append("no SkillLineAbility.dbc: every aura-78 spell taken, no summons")
        player = None
    else:
        for sql, _what in PLAYER_SPELL_SQL:
            player |= ints(soft(sql + ";\n"))
    entries, n = mount_entries(spells, None if all_mounts else player)
    if player is not None:
        pets, np = summon_entries(spells, player)
        objs, no = summon_entries(spells, player, OBJECT_SUMMONS)
        notes.append(f"{np} summon spells -> {len(pets)} creatures, {no} -> {len(objs)} objects")
        PLAYER_SUMMONS["c"], PLAYER_SUMMONS["g"] = pets, objs
    taxi = set()
    tx = read("TaxiNodes.dbc")
    try:
        taxi = parse_column(tx, TAXI_FIELDS, TAXI_MOUNT, "TaxiNodes.dbc") if tx else set()
    except ValueError as e:
        notes.append(str(e))
    taxi |= ints(soft(TAXI_DBC_SQL + ";\n"))
    notes.append(f"{n} mount spells -> {len(entries)} creatures, {len(taxi - entries)} more flight-master mounts")
    return entries | taxi, "; ".join(notes)


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    doc = json.load(open(argv[0], encoding="utf-8-sig"))
    tiers = set(range(0, 1000))
    if "--tiers" in argv:
        tiers = tiers_arg(argv[argv.index("--tiers") + 1])
    instances = "--instances" in argv
    if "--sql" in argv:
        sys.stdout.write(build_sql(doc, tiers, instances=instances))
        return 0
    has_model_table = run("SHOW TABLES LIKE 'creature_template_model';\n").strip() != ""
    global CREATURE_IDS
    if run("SHOW COLUMNS FROM creature LIKE 'id1';\n").strip() == "":
        CREATURE_IDS = "c.id"
    sys.stdout.write(run(build_sql(doc, tiers, has_model_table, instances)))
    label = None if "--no-mounts" in argv else mounts_tier(doc, tiers, "--mounts" in argv)
    # Transports and elevators: their own query, so a core without the columns loses only them.
    for sql, what in ((transports_sql(doc, tiers, label), "transports and elevators"),
                      (TOTEMS_SQL.format(tier=label) if label is not None else "", "totem models")):
        if not sql:
            continue
        try:
            out = run(sql)
            print(f"{what}: {len(out.splitlines())} displays", file=sys.stderr)
            sys.stdout.write(out)
        except subprocess.CalledProcessError as e:
            print(f"{what}: NOT included: " + (e.stderr or "").strip()[:200], file=sys.stderr)
    if label is not None:
        # Fail soft: the spawns above are already out; the slice is still good without mounts.
        try:
            entries, notes = player_mounts(argv, "--all-mounts" in argv)
        except Exception as e:  # noqa: BLE001 - never lose the spawn list over the mounts
            entries, notes = None, f"{type(e).__name__}: {e}"
        if entries is None:
            print(f"mounts: NOT included ({notes}). Mounting in the browser shows no mount until "
                  "the slice is made again with Spell.dbc found (pass --dbc <folder with Spell.dbc>).",
                  file=sys.stderr)
        else:
            try:
                acc = run("SHOW TABLES LIKE 'vehicle_template_accessory';\n").strip() != ""
                out = run(mounts_sql(entries, label, has_model_table, acc))
            except subprocess.CalledProcessError as e:
                print("mounts: NOT included, the model query failed: " + (e.stderr or "").strip()[:300],
                      file=sys.stderr)
                out = ""
            if out:
                print(f"mounts: {len(out.splitlines())} displays for tier {label} ({notes})", file=sys.stderr)
            sys.stdout.write(out)
            # Player pets, guardians, totems, companions and summoned objects: the same filter.
            try:
                pets = run(mounts_sql(PLAYER_SUMMONS["c"], label, has_model_table, False))
                objs = run(objects_sql(PLAYER_SUMMONS["g"], label))
                print(f"summons: {len(pets.splitlines())} creature and {len(objs.splitlines())} object "
                      f"displays for tier {label}", file=sys.stderr)
                sys.stdout.write(pets + objs)
            except subprocess.CalledProcessError as e:
                print("summons: NOT included, the model query failed: " + (e.stderr or "").strip()[:300],
                      file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as e:
        print("the database query failed: " + (e.stderr or "").strip()[:400], file=sys.stderr)
        sys.exit(1)
