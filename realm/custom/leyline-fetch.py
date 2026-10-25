#!/usr/bin/env python3
"""Writes the Leyline realm list for ov_leyline.lua (the in-game Leyline window). Host side, stdlib only.

Reads the relay's public listing and writes a small Lua data file next to the realm scripts, atomically:

    python3 -I /srv/wrath/leyline-fetch.py                     # from cron, every 5 minutes:
    */5 * * * * root python3 -I /srv/wrath/leyline-fetch.py >/dev/null 2>&1     (/etc/cron.d/leyline-realms)

    OV_LEYLINE_LISTING   listing URL      default https://relay.openvanilla.app/api/listing/realms.json
    OV_LEYLINE_OUT       file to write    default /srv/wrath/custom/lua_scripts/leyline-realms.dat
    --from FILE          read a listing from a local JSON file instead (tests)

On any failure the old file is left as it is (the window shows its age) and the exit code is 1.
The file holds only: return { updated = N, realms = { { id = "...", name = "...", ruleset = "...",
live = true, players = N, bots = N }, ... } }. Strings carry every byte outside a small safe set as a \\ddd
escape, so they never hold a quote or a backslash (ov_leyline.lua checks that before reading it).
"""
import json, os, re, sys, tempfile, time, urllib.request

LISTING = os.environ.get("OV_LEYLINE_LISTING", "https://relay.openvanilla.app/api/listing/realms.json")
OUT = os.environ.get("OV_LEYLINE_OUT", "/srv/wrath/custom/lua_scripts/leyline-realms.dat")
MAX_BYTES, MAX_REALMS, TIMEOUT = 2_000_000, 60, 10
REALM_ID = re.compile(r"^[a-z2-7]{16}$")
RULESETS = {"main", "brawl", "progression", "casual", "dalaran", "custom"}
BRANDS = re.compile(r"(?i)\b(world\s+of\s+warcraft|warcraft|lich\s+king|blizzard|wow)\b")
SAFE = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.,'!?()-&+#")


def lua_str(s: str) -> str:
    return '"' + "".join(chr(b) if b in SAFE else "\\%03d" % b for b in s.encode("utf-8")) + '"'


def count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000 else None


def clean(rec):
    if not isinstance(rec, dict) or rec.get("official"):
        return None
    com = rec.get("community") if isinstance(rec.get("community"), dict) else {}
    rid = com.get("realmId")
    if not isinstance(rid, str) or not REALM_ID.match(rid):
        return None
    prof = rec.get("profile") if isinstance(rec.get("profile"), dict) else {}
    hb = com.get("lastHeartbeat") if isinstance(com.get("lastHeartbeat"), dict) else {}
    name = rec.get("name") if isinstance(rec.get("name"), str) else ""
    name = "".join(c for c in name if c.isprintable() and c not in "|:")
    name = " ".join(BRANDS.sub("", name).split())[:32] or "Unnamed realm"
    return {"id": rid, "name": name, "ruleset": prof.get("ruleset") if prof.get("ruleset") in RULESETS else "custom",
            "live": rec.get("state") == "live", "players": count(hb.get("players")), "bots": count(hb.get("bots"))}


def render(doc, now) -> str:
    recs = doc.get("realms") if isinstance(doc, dict) else None
    if not isinstance(recs, list):
        raise ValueError("not a listing")
    out, seen = [], set()
    for rec in recs:
        c = clean(rec)
        if c and c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    out.sort(key=lambda r: (not r["live"], -(r["players"] or 0), r["name"].lower()))
    lines = []
    for r in out[:MAX_REALMS]:
        f = [f'id = {lua_str(r["id"])}', f'name = {lua_str(r["name"])}', f'ruleset = {lua_str(r["ruleset"])}',
             f'live = {"true" if r["live"] else "false"}']
        f += [f"{k} = {r[k]}" for k in ("players", "bots") if r[k] is not None]
        lines.append("  { " + ", ".join(f) + " },")
    return f"return {{ updated = {int(now)}, realms = {{\n" + "\n".join(lines) + "\n} }\n"


def main(argv):
    if len(argv) == 3 and argv[1] == "--from":
        with open(argv[2], "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    else:
        req = urllib.request.Request(LISTING, headers={"Accept": "application/json", "User-Agent": "leyline-fetch"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("listing too large")
    text = render(json.loads(raw.decode("utf-8")), time.time())
    d = os.path.dirname(os.path.abspath(OUT))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".leyline-")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT)
    except BaseException:
        os.unlink(tmp)
        raise
    n = text.count("\n  { ")
    print(f"leyline-fetch: {n} realms -> {OUT}")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as e:  # noqa: BLE001 - keep the old file, say why, exit 1
        print(f"leyline-fetch: failed ({str(e)[:160]}); the old list is kept", file=sys.stderr)
        sys.exit(1)
