#!/usr/bin/env python3
"""Exports the approved Workshop items for wu-portal (stream/creations.py, /wrath/workshop). Host side, stdlib only.

    python3 -I /srv/wrath/workshop-export.py             # from cron, every 5 minutes:
    */5 * * * * root python3 -I /srv/wrath/workshop-export.py >/dev/null 2>&1     (/etc/cron.d/wu-workshop)

The same way as the armory (armory-export.py): wu-portal has no route to the database and no MySQL client, so
this writes a file it can read. One fixed SELECT (nothing from a visitor ever reaches SQL), run in the database
container through its own root login inside a READ ONLY session, so a mistake here cannot change a row.

Reads acore_characters.mod_workshop_items (made by realm/custom/lua_scripts/ov_workshop.lua). Only approved items,
and only these fields: id, kind, title, author (a character name), description, version, created, plays,
thumbs up, thumbs down. Never the author's guid or account, never a build code or a course key, never anything
pending or rejected. Writes, atomically:

    <OUT>/items.json     {"updated": unix time, "items": [ {...}, ... ]}

    WU_WORKSHOP_OUT     default /srv/wrath/portal/workshop (wu-portal sees /app/workshop)
    WU_DB_CONTAINER     default ov-ac-database

On any failure nothing is written and the exit code is 1 (the site keeps the last good export).
"""
from __future__ import annotations

import json, os, re, subprocess, sys, tempfile, time

OUT = os.environ.get("WU_WORKSHOP_OUT", "/srv/wrath/portal/workshop")
DB_CONTAINER = os.environ.get("WU_DB_CONTAINER", "ov-ac-database")
MAX_ITEMS = 5000
NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")
KINDS = ("course", "mode", "build")

SQL = ("SELECT id, kind, title, author, descr, version, created_at, plays, up, down "
       "FROM acore_characters.mod_workshop_items WHERE state = 'approved' "
       f"ORDER BY id LIMIT {MAX_ITEMS}")


def docker_runner(sql: str) -> str:
    """The real database: mysql inside its container, read-only session, batch output."""
    cmd = ["docker", "exec", "-i", DB_CONTAINER, "sh", "-c",
           'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B --default-character-set=utf8mb4']
    r = subprocess.run(cmd, input=("SET SESSION TRANSACTION READ ONLY;\n" + sql + ";\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("mysql failed: " + r.stderr.decode("utf-8", "replace").strip()[:300])
    return r.stdout.decode("utf-8", "replace")


_UNESC = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "\\": "\\"}


def _field(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _UNESC.get(m.group(1), m.group(1)), s) if "\\" in s else s


def _int(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n < 2**31 else None


def _text(s: str, n: int) -> str:
    return re.sub(r"[^A-Za-z0-9 \-!&.,?:()]", "", re.sub(r"\s+", " ", s)).strip()[:n]


def build(text: str) -> list[dict]:
    items, seen = [], set()
    for line in text.split("\n"):
        if not line:
            continue
        f = [_field(x) for x in line.split("\t")]
        if len(f) < 10:
            continue
        nums = [_int(x) for x in (f[0], f[5], f[6], f[7], f[8], f[9])]
        if any(n is None for n in nums) or nums[0] < 1 or nums[0] in seen:
            continue
        kind, title, author = f[1], _text(f[2], 48), f[3]
        if kind not in KINDS or not title or not NAME_RE.fullmatch(author):
            continue
        seen.add(nums[0])
        items.append({"id": nums[0], "kind": kind, "title": title, "author": author, "descr": _text(f[4], 160),
                      "version": max(1, nums[1]), "created": nums[2], "plays": nums[3], "up": nums[4], "down": nums[5]})
    return items


def publish(items: list[dict], out: str, now: int) -> int:
    os.makedirs(out, mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"updated": now, "items": items}, fh, ensure_ascii=True, separators=(",", ":"))
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(out, "items.json"))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return len(items)


def run(runner=docker_runner, out: str = OUT, now: int | None = None) -> int:
    now = int(time.time()) if now is None else now
    return publish(build(runner(SQL)), out, now)


def main() -> int:
    try:
        n = run()
    except Exception as e:  # noqa: BLE001: cron: one line, old export stays
        print("workshop export failed: " + str(e)[:300], file=sys.stderr)
        return 1
    print(f"workshop export: {n} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
