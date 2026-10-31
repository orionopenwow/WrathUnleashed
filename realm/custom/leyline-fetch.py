#!/usr/bin/env python3
"""Writes the Leyline realm list for ov_leyline.lua (the in-game Leyline window). Host side, stdlib only.

Reads the Leyline network listing (the portal's /wrath/realms.json: the relay's records with the staff overrides:
hidden left out, featured and verified marked) and, when that is not reachable, the relay's own listing; writes a
small Lua data file next to the realm scripts, atomically:

    python3 -I /srv/wrath/leyline-fetch.py                     # from cron, every 5 minutes:
    */5 * * * * root python3 -I /srv/wrath/leyline-fetch.py >/dev/null 2>&1     (/etc/cron.d/leyline-realms)

    OV_LEYLINE_NETWORK   network listing  default https://play.openvanilla.app/wrath/realms.json ("" = skip it)
    OV_LEYLINE_LISTING   relay listing    default https://relay.openvanilla.app/api/listing/realms.json
    OV_LEYLINE_OUT       file to write    default /srv/wrath/custom/lua_scripts/leyline-realms.dat
    OV_LEYLINE_HOME      the Dalaran Hangout's realm id (this realm through the relay), listed first; default:
                         the id in /srv/wrath/hangout-realm.id (OV_LEYLINE_HOME_FILE; written by the hangout step)
    OV_LEYLINE_VR        Vanilla Remastered's realm id, the second official realm: pinned right after the Hangout
                         (marked verified: the window has no "official" word yet); default: the id in
                         /srv/wrath/vr-realm.id (OV_LEYLINE_VR_FILE; written by the vr-beacon step). Until it exists
                         the realm lists like any other.
    --from FILE          read a listing from a local JSON file instead (tests)

On any failure the old file is left as it is (the window shows its age) and the exit code is 1.
The file holds only: return { updated = N, realms = { { id = "...", name = "...", ruleset = "...",
live = true, players = N, bots = N, score = N, up = N, build = N, region = "...", est = true, lang = "...",
maxp = N, tags = "pvp,rp", featured = true, verified = true, new = true, sample = true }, ... } } (the fields after
bots are optional). Order: featured live realms, the sample hangout (this realm through the relay), live realms by
the listing's fair score, offline ones. Strings carry every byte outside a small safe set as a \\ddd
escape, so they never hold a quote or a backslash (ov_leyline.lua checks that before reading it).
"""
import json, os, re, sys, tempfile, time, urllib.request

LISTING = os.environ.get("OV_LEYLINE_LISTING", "https://relay.openvanilla.app/api/listing/realms.json")
NETWORK = os.environ.get("OV_LEYLINE_NETWORK", "https://play.openvanilla.app/wrath/realms.json")
OUT = os.environ.get("OV_LEYLINE_OUT", "/srv/wrath/custom/lua_scripts/leyline-realms.dat")
HOME_FILE = os.environ.get("OV_LEYLINE_HOME_FILE", "/srv/wrath/hangout-realm.id")
VR_FILE = os.environ.get("OV_LEYLINE_VR_FILE", "/srv/wrath/vr-realm.id")
MAX_BYTES, MAX_REALMS, TIMEOUT = 2_000_000, 60, 10
REALM_ID = re.compile(r"^[a-z2-7]{16}$")
RULESETS = {"main", "brawl", "progression", "casual", "dalaran", "vanillaplus", "custom"}
BRANDS = re.compile(r"(?i)\b(world\s+of\s+warcraft|warcraft|lich\s+king|blizzard|wow)\b")
SAFE = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.,'!?()-&+#")
TAGS = ("blizzlike", "boosted", "custom", "pvp", "rp", "hangout", "bots")
REGIONS = {"na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce"}
BUILDS = {5875, 8606, 12340, 15595, 18414}
# The newest client build offered. Hidden by the owner on 2026-10-30 ("3.3.5 at max until I research"): realms on
# 4.3.4 and 5.4.8 are left out of the in-game list. Set this back to 18414 (or LEYLINE_ALL_CLIENTS=1) to list them.
MAX_OFFERED_BUILD = 12340
ALL_CLIENTS = os.environ.get("LEYLINE_ALL_CLIENTS", "").strip().lower() in ("1", "true", "yes", "on")
LANG = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


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
    if prof.get("build") in BUILDS and prof["build"] > MAX_OFFERED_BUILD and not ALL_CLIENTS:
        return None   # 4.3.4 / 5.4.8: not offered for now
    hb = com.get("lastHeartbeat") if isinstance(com.get("lastHeartbeat"), dict) else {}
    name = rec.get("name") if isinstance(rec.get("name"), str) else ""
    name = "".join(c for c in name if c.isprintable() and c not in "|:")
    name = " ".join(BRANDS.sub("", name).split())[:32] or "Unnamed realm"
    up = com.get("uptime") if isinstance(com.get("uptime"), dict) else {}
    pct = [v for v in (up.get("d7"), up.get("h24")) if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100]
    sc = com.get("score")
    tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
    region, est = rec.get("region"), False
    if region not in REGIONS:
        region, est = (com.get("regionEstimate"), True) if com.get("regionEstimate") in REGIONS else (None, False)
    mp = rec.get("maxPlayers")
    return {"id": rid, "name": name, "ruleset": prof.get("ruleset") if prof.get("ruleset") in RULESETS else "custom",
            "live": rec.get("state") == "live", "players": count(hb.get("players")), "bots": count(hb.get("bots")),
            "score": round(sc) if isinstance(sc, (int, float)) and not isinstance(sc, bool) and 0 <= sc <= 1000 else 0,
            "up": pct[0] if pct else None,
            "build": prof.get("build") if prof.get("build") in BUILDS and not isinstance(prof.get("build"), bool) else 12340,
            "region": region, "est": est,
            "lang": rec.get("language") if isinstance(rec.get("language"), str) and LANG.match(rec["language"]) else None,
            "maxp": mp if isinstance(mp, int) and not isinstance(mp, bool) and 1 <= mp <= 10000 else None,
            "tags": ",".join(t for t in TAGS if t in {x for x in tags[:20] if isinstance(x, str)}),
            "featured": com.get("featured") is True, "verified": com.get("verified") is True, "new": com.get("new") is True,
            "sample": com.get("sample") is True}


def id_from(env, path):
    v = os.environ.get(env, "").strip()
    if not v:
        try:
            with open(path, encoding="utf-8") as f:
                v = f.read(64).strip()
        except OSError:
            v = ""
    return v if REALM_ID.match(v) else None


def home_id():
    return id_from("OV_LEYLINE_HOME", HOME_FILE)


def vr_id():
    return id_from("OV_LEYLINE_VR", VR_FILE)


def render(doc, now, home=None, vr=None) -> str:
    recs = doc.get("realms") if isinstance(doc, dict) else None
    if not isinstance(recs, list):
        raise ValueError("not a listing")
    out, seen = [], set()
    for rec in recs:
        c = clean(rec)
        if c and c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    for r in out:
        r["sample"] = r["sample"] or r["id"] == home
        r["vr"] = bool(vr) and r["id"] == vr and not r["sample"]
        if r["vr"]:
            r["verified"] = True   # official (staff run); ov_leyline.lua reads no "official" word yet

    # featured live realms, then the sample hangout (this realm through the relay), then live realms by the fair
    # score (busiest first when the listing has no score), then offline ones
    def rank(r):   # Vanilla Remastered (vr-realm.id): pinned right after the Hangout, live or not
        return 1 if r["sample"] else 1.5 if r["vr"] else 3 if not r["live"] else 0 if r["featured"] else 2
    out.sort(key=lambda r: (rank(r), -r["score"], -(r["players"] or 0), r["name"].lower()))
    lines = []
    for r in out[:MAX_REALMS]:
        f = [f'id = {lua_str(r["id"])}', f'name = {lua_str(r["name"])}', f'ruleset = {lua_str(r["ruleset"])}',
             f'live = {"true" if r["live"] else "false"}']
        f += [f"{k} = {r[k]}" for k in ("players", "bots") if r[k] is not None]
        f += [f"{k} = {r[k]}" for k in ("score", "up", "build", "maxp") if r[k] is not None]
        f += [f"{k} = {lua_str(r[k])}" for k in ("region", "lang", "tags") if r[k]]
        f += [f"{k} = true" for k in ("est", "featured", "verified", "new", "sample") if r[k]]
        lines.append("  { " + ", ".join(f) + " },")
    return f"return {{ updated = {int(now)}, realms = {{\n" + "\n".join(lines) + "\n} }\n"


def main(argv):
    if len(argv) == 3 and argv[1] == "--from":
        with open(argv[2], "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    else:
        raw, last = None, None
        for url in [u for u in (NETWORK, LISTING) if u]:
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "leyline-fetch"})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    raw = r.read(MAX_BYTES + 1)
                doc = json.loads(raw.decode("utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("realms"), list):
                    break
                raw, last = None, ValueError(f"{url}: not a listing")
            except Exception as e:  # noqa: BLE001 - try the next one
                raw, last = None, e
        if raw is None:
            raise last or ValueError("no listing")
    if len(raw) > MAX_BYTES:
        raise ValueError("listing too large")
    text = render(json.loads(raw.decode("utf-8")), time.time(), home_id(), vr_id())
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
