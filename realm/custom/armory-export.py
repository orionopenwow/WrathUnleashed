#!/usr/bin/env python3
"""Exports the web armory's character data for wu-portal (stream/armory.py). Host side, stdlib only.

    python3 -I /srv/wrath/armory-export.py               # from cron, every 5 minutes:
    */5 * * * * root python3 -I /srv/wrath/armory-export.py >/dev/null 2>&1     (/etc/cron.d/wu-armory)

Why a file export and not a database login for the portal: wu-portal runs on the website's network with no
route to the database and no MySQL client, and this way no new password exists anywhere. The queries below
are fixed text (nothing from a visitor ever reaches SQL) and run in the database container through its own
root login, inside a READ ONLY session, so a mistake here cannot change a row. The portal only reads files.

Reads acore_characters (and acore_auth only to leave the playerbots' RNDBOT accounts out, and acore_world's
item_template for item names). Writes, atomically, into OUT (default /srv/wrath/portal/armory, which
wu-portal sees as /app/armory):

    index.json        {"updated": unix time, "chars": [summary, ...]}
    c/<Name>.json     one character sheet

Privacy (stream/armory.py checks it all again):
  - never exported: account ids or names, IPs, gold, bags, bank, mail, positions, character guids;
  - characters whose player typed ".armory off" in game (ov_armory_privacy.hidden = 1, ov_armory.lua) are
    left out entirely, and their old files are removed on the same run;
  - bots (accounts named RNDBOT*, mod-playerbots' random bots) are left out entirely;
  - deleted characters, and names that are not plain 2-12 letters, are left out;
  - last seen is a day (YYYY-MM-DD) only.

    WU_ARMORY_OUT      the folder to write       default /srv/wrath/portal/armory
    WU_ARMORY_DBC      the client's DBC folder   default /srv/wrath/client-data/dbc
                       (Talent, TalentTab and Achievement .dbc: talent points per tree and achievement
                       points; without them those parts are left empty and the rest still exports)
    WU_DB_CONTAINER    default ov-ac-database

On any failure nothing is written and the exit code is 1 (the site keeps the last good export).
Never prints a password: mysql runs in its container with the container's own MYSQL_ROOT_PASSWORD.
"""
from __future__ import annotations

import json, os, re, struct, subprocess, sys, tempfile, time

OUT = os.environ.get("WU_ARMORY_OUT", "/srv/wrath/portal/armory")
DBC_DIR = os.environ.get("WU_ARMORY_DBC", "/srv/wrath/client-data/dbc")
DB_CONTAINER = os.environ.get("WU_DB_CONTAINER", "ov-ac-database")
NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")
MAX_CHARS = 20000
EQUIP_SLOTS = 19            # 0 head .. 18 tabard (bag 0)
PROFESSIONS = (164, 165, 171, 182, 186, 197, 202, 333, 393, 755, 773, 129, 185, 356)
ACH_LEVEL_80 = 13           # "Level 80": its date is the day the character reached 80

# Every query: playable characters of real players who did not opt out. The account table is only joined
# to drop bots; nothing from it is selected.
VISIBLE = ("FROM acore_characters.characters c "
           "JOIN acore_auth.account a ON a.id = c.account "
           "LEFT JOIN acore_characters.ov_armory_privacy p ON p.guid = c.guid "
           "WHERE c.deleteDate IS NULL AND a.username NOT LIKE 'RNDBOT%' AND IFNULL(p.hidden, 0) = 0 "
           "AND c.level BETWEEN 1 AND 255")

QUERIES = [
    ("chars", "SELECT c.guid, c.name, c.race, c.class, c.gender, c.level, c.logout_time, c.online, c.totalKills, "
              "c.activeTalentGroup, IFNULL((SELECT g.name FROM acore_characters.guild_member gm "
              "JOIN acore_characters.guild g ON g.guildid = gm.guildid WHERE gm.guid = c.guid LIMIT 1), '') "
              + VISIBLE + f" ORDER BY c.guid LIMIT {MAX_CHARS}"),
    ("items", "SELECT c.guid, ci.slot, ii.itemEntry, IFNULL(it.name, ''), IFNULL(it.Quality, 1), IFNULL(it.ItemLevel, 0) "
              "FROM acore_characters.character_inventory ci "
              "JOIN acore_characters.item_instance ii ON ii.guid = ci.item "
              "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
              "JOIN (SELECT c.guid " + VISIBLE + ") c ON c.guid = ci.guid "
              f"WHERE ci.bag = 0 AND ci.slot < {EQUIP_SLOTS}"),
    ("talents", "SELECT c.guid, t.spell, t.specMask FROM acore_characters.character_talent t "
                "JOIN (SELECT c.guid " + VISIBLE + ") c ON c.guid = t.guid"),
    ("ach", "SELECT c.guid, ca.achievement, ca.date FROM acore_characters.character_achievement ca "
            "JOIN (SELECT c.guid " + VISIBLE + ") c ON c.guid = ca.guid"),
    ("arena", "SELECT c.guid, tm.type, tm.rating, atm.personalRating FROM acore_characters.arena_team_member atm "
              "JOIN acore_characters.arena_team tm ON tm.arenaTeamId = atm.arenaTeamId "
              "JOIN (SELECT c.guid " + VISIBLE + ") c ON c.guid = atm.guid"),
    ("skills", "SELECT c.guid, s.skill, s.value, s.max FROM acore_characters.character_skills s "
               "JOIN (SELECT c.guid " + VISIBLE + ") c ON c.guid = s.guid "
               f"WHERE s.skill IN ({', '.join(map(str, PROFESSIONS))})"),
]


def batch_sql() -> str:
    """One script: a marker row before each query, so one mysql run gives every result."""
    return "".join(f"SELECT '#Q {k}';\n{q};\n" for k, q in QUERIES)


def docker_runner(sql: str) -> str:
    """The real database: mysql inside its container, read-only session, batch output."""
    cmd = ["docker", "exec", "-i", DB_CONTAINER, "sh", "-c",
           'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B --default-character-set=utf8mb4']
    r = subprocess.run(cmd, input=("SET SESSION TRANSACTION READ ONLY;\n" + sql).encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    if r.returncode != 0:
        # mysql's own error text (no password is ever on the command line or in it)
        raise RuntimeError("mysql failed: " + r.stderr.decode("utf-8", "replace").strip()[:300])
    return r.stdout.decode("utf-8", "replace")


_UNESC = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "\\": "\\"}


def _field(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _UNESC.get(m.group(1), m.group(1)), s) if "\\" in s else s


def parse_batch(text: str) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    cur = None
    for line in text.split("\n"):
        if line.startswith("#Q "):
            cur = line[3:].strip()
            out[cur] = []
        elif line and cur is not None:
            out[cur].append([_field(f) for f in line.split("\t")])
    missing = [k for k, _ in QUERIES if k not in out]
    if missing:
        raise RuntimeError("no result for " + ", ".join(missing))
    return out


# --- client DBC files (talent trees, achievement points) -------------------------------------------------

def dbc_rows(path: str):
    with open(path, "rb") as f:
        b = f.read(64_000_000)
    if b[:4] != b"WDBC":
        raise ValueError("not a DBC file")
    n, fields, size, _s = struct.unpack_from("<4I", b, 4)
    if size < fields * 4 or 20 + n * size > len(b):
        raise ValueError("bad DBC header")
    for r in range(n):
        yield struct.unpack_from(f"<{fields}I", b, 20 + r * size)


def _dbc(name: str) -> str | None:
    try:
        for f in os.listdir(DBC_DIR):
            if f.lower() == name.lower():
                return os.path.join(DBC_DIR, f)
    except OSError:
        pass
    return None


def load_talents() -> dict[int, tuple[int, int]]:
    """talent spell id -> (tree order 0-2, points that rank stands for)."""
    tt, t = _dbc("TalentTab.dbc"), _dbc("Talent.dbc")
    if not tt or not t:
        return {}
    try:
        order = {row[0]: row[22] for row in dbc_rows(tt) if len(row) > 22 and row[20] and row[22] < 3}
        spells = {}
        for row in dbc_rows(t):
            if row[1] not in order:
                continue
            for rank, spell in enumerate(row[4:13]):
                if spell:
                    spells[spell] = (order[row[1]], rank + 1)
        return spells
    except (OSError, ValueError, struct.error):
        return {}


def load_achievement_points() -> dict[int, int]:
    p = _dbc("Achievement.dbc")
    if not p:
        return {}
    try:
        # 3.3.5a: 62 fields; 39 points, 41 flags (bit 0: a counter, never "earned")
        return {row[0]: row[39] for row in dbc_rows(p) if len(row) >= 62 and not row[41] & 1}
    except (OSError, ValueError, struct.error):
        return {}


# --- building the records ---------------------------------------------------------------------------------

def _int(v, lo=0, hi=2**31 - 1) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return lo
    return min(max(n, lo), hi)


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts > 0 else ""


def build(res: dict, talents: dict, ach_points: dict, now: int) -> list[dict]:
    chars, names = {}, set()
    for row in res["chars"]:
        if len(row) < 11:
            continue
        guid, name = _int(row[0]), row[1]
        if not NAME_RE.fullmatch(name) or name.lower() in names:
            continue
        names.add(name.lower())
        online = _int(row[7]) == 1
        chars[guid] = {
            "name": name, "race": _int(row[2], 0, 255), "class": _int(row[3], 0, 255), "gender": _int(row[4], 0, 1),
            "level": _int(row[5], 1, 255), "last_day": _day(now if online else _int(row[6])),
            "hk": _int(row[8]), "active_spec": _int(row[9], 0, 1), "guild": row[10][:24],
            "items": [], "specs": [[0, 0, 0], [0, 0, 0]], "ach_count": 0, "ach_points": 0,
            "reached80_day": "", "arena": [], "prof": [],
        }
    for row in res["items"]:
        c = chars.get(_int(row[0])) if len(row) >= 6 else None
        if c is not None:
            c["items"].append({"slot": _int(row[1], 0, EQUIP_SLOTS - 1), "entry": _int(row[2]), "name": row[3][:80],
                               "quality": _int(row[4], 0, 7), "ilvl": _int(row[5], 0, 1000)})
    for row in res["talents"]:
        c = chars.get(_int(row[0])) if len(row) >= 3 else None
        t = talents.get(_int(row[1]))
        if c is None or t is None:
            continue
        mask = _int(row[2])
        for spec in (0, 1):
            if mask & (1 << spec):
                c["specs"][spec][t[0]] += t[1]
    for row in res["ach"]:
        c = chars.get(_int(row[0])) if len(row) >= 3 else None
        if c is None:
            continue
        a = _int(row[1])
        c["ach_count"] += 1
        c["ach_points"] += ach_points.get(a, 0)
        if a == ACH_LEVEL_80:
            c["reached80_day"] = _day(_int(row[2]))
    for row in res["arena"]:
        c = chars.get(_int(row[0])) if len(row) >= 4 else None
        if c is not None and _int(row[1]) in (2, 3, 5):
            c["arena"].append({"type": _int(row[1]), "rating": _int(row[2], 0, 10000), "personal": _int(row[3], 0, 10000)})
    for row in res["skills"]:
        c = chars.get(_int(row[0])) if len(row) >= 4 else None
        if c is not None and _int(row[1]) in PROFESSIONS and _int(row[2]) > 0:
            c["prof"].append({"skill": _int(row[1]), "value": _int(row[2], 0, 1000), "max": _int(row[3], 0, 1000)})
    for c in chars.values():
        c["items"].sort(key=lambda i: i["slot"])
        c["arena"].sort(key=lambda a: a["type"])
        c["prof"].sort(key=lambda p: p["skill"])
        if not talents:
            c["specs"] = []
        if not ach_points:
            c["ach_points"] = None
    return sorted(chars.values(), key=lambda c: c["name"].lower())


SUMMARY = ("name", "race", "class", "gender", "level", "guild", "ach_points", "ach_count", "last_day", "reached80_day")


def _write_json(path: str, obj) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=True, separators=(",", ":"))
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def publish(records: list[dict], out: str, now: int) -> int:
    """Character files first, then the index (the portal shows only characters in the index), then the
    files of characters no longer listed (opted out, deleted, renamed) are removed."""
    cdir = os.path.join(out, "c")
    os.makedirs(cdir, mode=0o755, exist_ok=True)
    keep = set()
    for r in records:
        _write_json(os.path.join(cdir, r["name"] + ".json"), r)
        keep.add(r["name"] + ".json")
    _write_json(os.path.join(out, "index.json"),
                {"updated": now, "chars": [{k: r[k] for k in SUMMARY} for r in records]})
    for f in os.listdir(cdir):
        if f not in keep:
            try:
                os.unlink(os.path.join(cdir, f))
            except OSError:
                pass
    return len(records)


def run(runner=docker_runner, out: str = OUT, now: int | None = None) -> int:
    now = int(time.time()) if now is None else now
    res = parse_batch(runner(batch_sql()))
    records = build(res, load_talents(), load_achievement_points(), now)
    return publish(records, out, now)


def main() -> int:
    try:
        n = run()
    except Exception as e:  # noqa: BLE001: cron: one line, old export stays
        print("armory export failed: " + str(e)[:300], file=sys.stderr)
        return 1
    print(f"armory export: {n} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
