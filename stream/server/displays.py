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
"""
import json
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as e:
        print("the database query failed: " + (e.stderr or "").strip()[:400], file=sys.stderr)
        sys.exit(1)
