"""The Leyline network: community realms hosted by players are the front of it (owner, 2026-10-29: "server arrays
for p2p rather than our own"). Our own server is a temporary sampler, "Leyline Sample Hangout", pinned below the
featured community realms. Served by stream/wrath_portal.py, which loads this file from beside itself and runs
without it.

    GET  /wrath/realms                  the realm browser: community realms first, in the fair order below, filters
                                        (?build= &tag= &region= &lang= &now=1), the network line, Host your own
    GET  /wrath/realms.json             the same list for the launcher, the in-game window (realm/custom/
                                        leyline-fetch.py) and the hub: the relay's records (schema 1) with the staff
                                        overrides applied (hidden left out; featured, verified, sample marked) in
                                        display order, plus {"network": {"realms", "players", "bots"}}. CORS *.
    GET  /wrath/realms/report?realm=ID  report a realm (signed in);  POST it to queue the report for the admin console
                                        (stream/admin.py, Reports and Realms). One open report per account and realm.

The order (order()):
  1. featured community realms (staff pick them in the admin console), live ones only, by score;
  2. the Leyline Sample Hangout (our own realm: the relay record whose id is the hangout's, WU_HANGOUT_REALM or
     hangout-realm.id), pinned, labelled "temporary" (shown even when its record is missing);
  3. every other live community realm, by score;
  4. offline realms, by name.
The score comes from the relay's listing (hosting/relay/wurelay/listing.py score()): players now (diminishing),
bots counted apart and worth little, uptime over 24 h and 7 d, a small boost while new. Nothing can be bought or
voted on. A realm whose heartbeats stop shows offline at once and leaves the list after 6 h (the relay does that).

Standard library only.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_NAME = os.environ.get("WU_SAMPLE_NAME", "Leyline Sample Hangout")
SAMPLE_NOTE = "temporary"
REALM_ID_RE = re.compile(r"^[a-z2-7]{16}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")

TAGS = [("blizzlike", "Blizzlike"), ("boosted", "Boosted"), ("custom", "Custom"), ("pvp", "PvP"), ("rp", "RP"),
        ("hangout", "Hangout"), ("bots", "Bots")]
TAG_LABEL = dict(TAGS)
REGIONS = [("na-east", "North America east"), ("na-west", "North America west"), ("sa", "South America"),
           ("eu", "Europe"), ("africa", "Africa"), ("me", "Middle East"), ("asia", "Asia"), ("oce", "Oceania")]
REGION_LABEL = dict(REGIONS)
BUILDS = {5875: "1.12.1", 8606: "2.4.3", 12340: "3.3.5a", 15595: "4.3.4", 18414: "5.4.8"}
BUILD_OF = {v: k for k, v in BUILDS.items()}
# The newest client build offered. Hidden by the owner on 2026-10-30 ("3.3.5 at max until I research"): realms on
# 4.3.4 and 5.4.8 are left out of the lists, the counts and the filters (the relay may still list them). Set this
# back to 18414 (or set LEYLINE_ALL_CLIENTS=1) to show them again.
MAX_OFFERED_BUILD = 12340


# Vanilla Remastered: the second official realm (hosting/vanilla-remastered/vr-beacon-up.sh writes its relay realm id
# to /srv/wrath/portal/vr-realm.id, mounted at /app). Read like the Hangout's id file; until it exists the realm lists
# like any community realm. Pinned right after the official realm, marked official, optional.
VR_REALM = os.environ.get("WU_VR_REALM", "").strip()
VR_FILE = os.environ.get("WU_VR_FILE", "/app/vr-realm.id")
VR_LINE = "An optional second realm, hosted by Leyline for now."
_vr = {"at": -1e9, "id": None}


def vr_id() -> str | None:
    """Vanilla Remastered's relay realm id, or None. Re-read once a minute."""
    if VR_REALM:
        return VR_REALM if REALM_ID_RE.match(VR_REALM) else None
    now = time.monotonic()
    if now - _vr["at"] > 60:
        _vr["at"] = now
        try:
            with open(VR_FILE, encoding="utf-8") as f:
                v = f.read(64).strip()
            _vr["id"] = v if REALM_ID_RE.match(v) else None
        except OSError:
            _vr["id"] = None
    return _vr["id"]


def offered(build, env=None) -> bool:
    v = (os.environ if env is None else env).get("LEYLINE_ALL_CLIENTS", "").strip().lower()
    return v in ("1", "true", "yes", "on") or (build or 12340) <= MAX_OFFERED_BUILD
CORES = {"azerothcore": "AzerothCore", "trinitycore": "TrinityCore", "cmangos": "CMaNGOS", "vmangos": "vMaNGOS",
         "mangos": "MaNGOS", "other": "Other"}
LANGS = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "pt": "Português", "pt-BR": "Português (BR)",
         "it": "Italiano", "nl": "Nederlands", "pl": "Polski", "ru": "Русский", "tr": "Türkçe", "sv": "Svenska",
         "cs": "Čeština", "zh": "中文", "ko": "한국어", "ja": "日本語"}
REPORT_REASONS = [("name", "Offensive name or text"), ("cheat", "Cheating, scams or stolen accounts"),
                  ("host", "Harassment by the host or GMs"), ("misleading", "Not what the listing says"),
                  ("other", "Something else")]
REPORT_REASON = dict(REPORT_REASONS)
NOTE_LEN = 300
REPORTS_PER_HOUR = 5
MAX_REPORTS = 3000
HOST_URL = "/wrath/host"          # "+ Your server" on the website (stream/hostflow.py)
LAUNCHER_URL = "/wrath/leyline"   # the Leyline launcher download page
HOSTING_DOCS = "/wrath/docs/hosting"

_get = None
_lock = threading.Lock()
_csrf_key = secrets.token_bytes(32)
_rate: dict[str, list[float]] = {}


def bind(getter) -> None:
    global _get
    _get = getter


def P(name):
    try:
        return _get(name) if _get else None
    except Exception:   # noqa: BLE001
        return None


def e(v) -> str:
    return html.escape(str(v), quote=True)


# ----------------------------------------------------------------------------------------------- records
def _nonneg(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000 else None


def _pct(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 else None


def extra(rec: dict) -> dict:
    """The network fields of one relay record (wurelay/listing.py), each checked; safe defaults for older relays."""
    com = rec.get("community") if isinstance(rec.get("community"), dict) else {}
    prof = rec.get("profile") if isinstance(rec.get("profile"), dict) else {}
    up = com.get("uptime") if isinstance(com.get("uptime"), dict) else {}
    build = prof.get("build") if prof.get("build") in BUILDS and not isinstance(prof.get("build"), bool) else None
    if build is None and isinstance(prof.get("version"), str):
        build = BUILD_OF.get(prof["version"])
    tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
    want = {t for t in tags[:20] if isinstance(t, str)}
    relay = com.get("relay") if isinstance(com.get("relay"), str) and HOST_RE.match(com["relay"]) else None
    port = prof.get("port") if isinstance(prof.get("port"), int) and not isinstance(prof.get("port"), bool) \
        and 1 <= prof["port"] <= 65535 else None
    sc = com.get("score")
    return {
        "relay": relay, "port": port,
        "build": build or 12340,
        "core": prof.get("core") if prof.get("core") in CORES else "azerothcore",
        "tags": [t for t, _ in TAGS if t in want],
        "region": rec.get("region") if rec.get("region") in REGION_LABEL else None,
        "region_est": com.get("regionEstimate") if com.get("regionEstimate") in REGION_LABEL else None,
        "language": rec.get("language") if isinstance(rec.get("language"), str) and LANG_RE.match(rec["language"]) else None,
        "max_players": rec.get("maxPlayers") if isinstance(rec.get("maxPlayers"), int) and not isinstance(rec.get("maxPlayers"), bool)
        and 1 <= rec["maxPlayers"] <= 10000 else None,
        "up24": _pct(up.get("h24")), "up7": _pct(up.get("d7")),
        "new": com.get("new") is True,
        "score": float(sc) if isinstance(sc, (int, float)) and not isinstance(sc, bool) and math.isfinite(sc) and 0 <= sc <= 1000 else 0.0,
        "direct": com.get("directConnect") is True,
        # Warden (the core's client anti-cheat): on, the browser client (no Warden module) is turned away, so the
        # site must not offer "Play in browser" (the host's "Browser players" switch: setup.py browser on|off)
        "warden": prof.get("warden") if isinstance(prof.get("warden"), bool) else None,
        "first_seen": com.get("firstSeen") if isinstance(com.get("firstSeen"), str) and len(com["firstSeen"]) <= 25 else "",
    }


def region_of(r: dict):
    """(region, estimated): the host's own choice, else the relay's coarse estimate."""
    if r.get("region"):
        return r["region"], False
    if r.get("region_est"):
        return r["region_est"], True
    return None, False


def order(realms: list[dict]) -> list[dict]:
    """Sets r["group"] (featured, sample, community, offline) and sorts; see the module docstring."""
    out = []
    vr = vr_id()
    for r in realms:
        if not offered(r.get("build")):   # 4.3.4 / 5.4.8: not offered for now (MAX_OFFERED_BUILD)
            continue
        r = dict(r)
        r["sample"] = bool(r.get("hangout"))
        r["vr"] = bool(vr) and r.get("id") == vr and not r["sample"]
        if r["vr"]:   # the second official realm: pinned right after the Hangout, live or not
            r["official"] = True
            r["group"] = "official"
        elif not r.get("live"):
            r["group"] = "offline" if not r["sample"] else "sample"
        elif r["sample"]:
            r["group"] = "sample"
        elif r.get("featured"):
            r["group"] = "featured"
        else:
            r["group"] = "community"
        out.append(r)
    rank = {"featured": 0, "sample": 1, "official": 1.5, "community": 2, "offline": 3}
    live = lambda r: r["group"] != "offline"   # noqa: E731
    out.sort(key=lambda r: (rank[r["group"]], -(r.get("score") or 0) if live(r) else 0,
                            -(r.get("players") or 0) if live(r) else 0, str(r.get("name", "")).lower(), r.get("id", "")))
    return out


def totals(realms: list[dict], sample_status: dict | None = None) -> dict:
    """{"realms", "players", "bots"} online on the network. Players and bots are counted apart and never mixed: our own
    realm's numbers come from its own status (sample_status: players and bots measured on the realm itself) rather than
    its relay record (the agent's last heartbeat, which can lag a bot in or out); a count that is not a plain number is
    left out rather than guessed."""
    live = [r for r in realms if r.get("live")]
    st = sample_status or {}
    own_ok = bool(st.get("online")) and _nonneg(st.get("players")) is not None
    n = p = b = 0
    for r in live:
        n += 1
        if (r.get("sample") or r.get("hangout")) and own_ok:
            continue   # counted once below, from its own status
        p += _nonneg(r.get("players")) or 0
        b += _nonneg(r.get("bots")) or 0
    if own_ok:
        if not any(r.get("sample") or r.get("hangout") for r in live):
            n += 1
        p += _nonneg(st.get("players")) or 0
        b += _nonneg(st.get("bots")) or 0
    return {"realms": n, "players": p, "bots": b}


def network_line(t: dict) -> str:
    s = f'{t["realms"]} realm{"" if t["realms"] == 1 else "s"} · {t["players"]} player{"" if t["players"] == 1 else "s"} online'
    return s + (f' · {t["bots"]} bots' if t.get("bots") else "")


# ----------------------------------------------------------------------------------------------- filters
def filters_from(query: dict) -> dict:
    def one(k, n=16):
        v = (query.get(k) or [""])[0]
        return v[:n] if isinstance(v, str) else ""
    f = {}
    b = one("build")
    if b in BUILD_OF and offered(BUILD_OF[b]):
        f["build"] = BUILD_OF[b]
    t = one("tag")
    if t in TAG_LABEL:
        f["tag"] = t
    g = one("region")
    if g in REGION_LABEL:
        f["region"] = g
    lang = one("lang", 8)
    if LANG_RE.match(lang):
        f["lang"] = lang
    if one("now") == "1":
        f["now"] = True
    return f


def matches(r: dict, f: dict) -> bool:
    if "build" in f and r.get("build", 12340) != f["build"]:
        return False
    if "tag" in f and f["tag"] not in (r.get("tags") or []):
        return False
    if "region" in f and region_of(r)[0] != f["region"]:
        return False
    if "lang" in f and (r.get("language") or "").split("-")[0] != f["lang"].split("-")[0]:
        return False
    if f.get("now") and not (r.get("live") and (r.get("players") or 0) > 0):
        return False
    return True


def facets(realms: list[dict]) -> dict:
    return {"build": sorted({r.get("build", 12340) for r in realms}),
            "tag": [t for t, _ in TAGS if any(t in (r.get("tags") or []) for r in realms)],
            "region": [g for g, _ in REGIONS if any(region_of(r)[0] == g for r in realms)],
            "lang": sorted({r["language"] for r in realms if r.get("language")})}


# ----------------------------------------------------------------------------------------------- JSON
def record_of(r: dict, sample: dict | None = None) -> dict:
    """One display realm as a schema-1 listing record (what the launcher's realms.rs reads)."""
    relay = r.get("relay") or "relay.openvanilla.app"
    rid = r["id"]
    return {
        "schema": 1, "slug": "c-" + rid, "name": r.get("name", ""), "official": False,
        "state": "live" if r.get("live") else "offline", "tagline": r.get("tagline", ""), "summary": "",
        "type": r.get("type", "PvE"),
        "profile": {"game": None, "version": BUILDS.get(r.get("build", 12340)), "build": r.get("build", 12340),
                    "core": r.get("core", "azerothcore"), "address": relay, "port": r.get("port"),
                    "ruleset": r.get("ruleset", "custom"), "warden": r.get("warden")},
        "connect": {"kind": "web-signin", "url": f"https://{relay}/join/{rid}", "label": "Join this realm"},
        "rules": list(r.get("rules") or []),
        "tags": list(r.get("tags") or []), "region": r.get("region"), "language": r.get("language"),
        "maxPlayers": r.get("max_players"),
        "status": {"url": f"https://{relay}/r/{rid}/status.json", "format": "openvanilla-status-1"},
        "community": {
            "realmId": rid, "relay": relay, "claimed": bool(r.get("claimed")),
            "lastHeartbeat": {"online": bool(r.get("live")), "players": r.get("players"), "bots": r.get("bots")},
            "uptime": {"h24": r.get("up24"), "d7": r.get("up7")}, "new": bool(r.get("new")),
            "score": r.get("score", 0.0), "regionEstimate": r.get("region_est"),
            "directConnect": bool(r.get("direct")),
            "featured": bool(r.get("featured")), "verified": bool(r.get("verified")), "official": bool(r.get("official")),
            "pinned": bool(r.get("vr") or r.get("sample")), "optional": bool(r.get("vr")),
            "note": VR_LINE if r.get("vr") else None,
            "sample": bool(r.get("sample")), "group": r.get("group", "community"),
            "sampleName": ((sample or {}).get("name") or SAMPLE_NAME) if r.get("sample") else None,
        },
    }


def realms_json(realms: list[dict], ok: bool, sample_status: dict | None = None, sample: dict | None = None) -> bytes:
    shown = order(realms)
    doc = {"schema": 1, "kind": "network", "ok": ok,
           "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "network": totals(shown, sample_status),
           "sample": {"name": (sample or {}).get("name") or SAMPLE_NAME, "temporary": bool((sample or {}).get("temporary", True))},
           "realms": [record_of(r, sample) for r in shown]}
    return (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8")


# ----------------------------------------------------------------------------------------------- HTML
NET_CSS = """
.net-line{text-align:center;color:#b4ab96;margin:6px 0 14px;font-size:.95rem}
.net-filters{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:center;margin:8px 0 6px;font-size:.88rem}
.net-filters span{color:#b4ab96}.net-filters a{white-space:nowrap}.net-filters a.on{font-weight:700;text-decoration:none;color:#ece6d6}
.realm.featured{border-color:#8a6a2c}.realm.sample{border-style:dashed}
.badge{display:inline-block;border-radius:999px;padding:1px 9px;font-size:.8rem;border:1px solid #6b5a2e;background:rgba(40,30,10,.7)}
.badge.good{border-color:#3f7a4c;color:#9fe0ae}.badge.warn{border-color:#7a6a3f;color:#e8d79a}.badge.dim{color:#9d9686}
.host-cta{border:1px solid #4a3b1c;border-radius:4px;padding:14px 18px;margin:18px 0;background:rgba(12,10,24,.55)}
.host-cta h2{margin:0 0 6px}.host-cta ol{margin:8px 0 10px 1.2em;padding:0}.report{font-size:.85rem}
"""


def uptime_badge(r: dict) -> str:
    u = r.get("up7") if r.get("up7") is not None else r.get("up24")
    if u is None:
        return '<span class="badge dim" title="Watched for less than an hour">uptime: new</span>' if r.get("live") else ""
    cls = "good" if u >= 95 else "warn" if u >= 75 else "dim"
    span = "7 d" if r.get("up7") is not None else "24 h"
    return f'<span class="badge {cls}" title="Online {u}% of the last {span}, from its heartbeats">{u}% up · {span}</span>'


def _players(r: dict) -> str:
    if not r.get("live"):
        return "offline"
    if r.get("players") is None:
        return '<span class="live">● online</span>'
    s = f'<span class="live">● online</span> · {r["players"]} playing'
    if r.get("max_players"):
        s += f' of {r["max_players"]}'
    return s + (f' · {r["bots"]} bots' if r.get("bots") else "")


def tags_html(r: dict, ruleset_labels: dict) -> str:
    out = []
    if r.get("official"):
        out.append('<span class="tag">Official</span>')
    if r.get("featured"):
        out.append('<span class="badge warn">Featured</span>')
    if r.get("verified"):
        out.append('<span class="badge good" title="Checked by Leyline staff">Verified host</span>')
    if r.get("new"):
        out.append('<span class="badge">New</span>')
    # the client version only in its own chip (no version numbers anywhere else on the site); the tag is the core
    out.append(f'<span class="tag ver" title="The game client this realm needs">{e(BUILDS.get(r.get("build", 12340), "3.3.5a"))}</span>')
    out.append(f'<span class="tag">{e(CORES.get(r.get("core"), "AzerothCore"))}</span>')
    out.append(f'<span class="tag">{e(ruleset_labels.get(r.get("ruleset"), "Custom rules"))}</span>')
    out.append(f'<span class="tag">{e(r.get("type") or "PvE")}</span>')
    out += [f'<span class="tag">{e(TAG_LABEL[t])}</span>' for t in r.get("tags") or [] if t in TAG_LABEL]
    reg, est = region_of(r)
    if reg:
        title = ' title="Estimated from the relay"' if est else ""
        out.append(f'<span class="tag"{title}>{e(REGION_LABEL[reg])}{" (estimated)" if est else ""}</span>')
    if r.get("language"):
        out.append(f'<span class="tag">{e(LANGS.get(r["language"], r["language"]))}</span>')
    if not r.get("claimed"):
        out.append('<span class="tag">unclaimed</span>')
    out.append(uptime_badge(r))
    out.append(_players(r))
    return "".join(x for x in out if x)


def summary(realms: list[dict], sample_status: dict | None, n: int = 5) -> tuple[dict, list[dict]]:
    """(network totals, the first n realms in display order, sample included): the hub's and the Leyline page's
    "Realms on the network" panel."""
    shown = order(realms)
    return totals(shown, sample_status), [r for r in shown if r["group"] != "offline"][:n]


def host_cta(where: str = "realms", pack_url: str | None = None) -> str:
    """"Host your own": the same three steps on every surface. TODO(owner): the heading and lede wording."""
    pack = (f' · <a href="{e(pack_url)}" rel="noopener noreferrer">Host pack download</a>' if pack_url else
            f' · <a href="{HOSTING_DOCS}">Host pack</a>')
    return (f'<section class="host-cta" id="host-your-own" data-where="{e(where)}">'
            '<!-- TODO(owner): the "Host your own" heading and lede -->'
            '<h2>Host your own realm</h2>'
            '<p>Community realms are the Leyline network. Anyone can run one from their own PC.</p>'
            '<ol><li>Get the Leyline launcher (or the Host pack) and Docker.</li>'
            '<li>Open Host in the launcher: pick a profile, a name and your house rules. The realm runs on your PC.</li>'
            '<li>Make it public: the relay lists it here, with no port forwarding. You are its GM.</li></ol>'
            f'<p><a class="btn primary" href="{LAUNCHER_URL}">Get the launcher</a> '
            f'<a class="btn" href="{HOST_URL}">Start on the website</a></p>'
            f'<p class="fine"><a href="{HOSTING_DOCS}">How hosting works</a>{pack}</p></section>')


def _qs(f: dict, base: str = "/wrath/realms", **over) -> str:
    g = dict(f)
    for k, v in over.items():
        if v is None:
            g.pop(k, None)
        else:
            g[k] = v
    q = {k: (BUILDS[v] if k == "build" else "1" if k == "now" else v) for k, v in g.items()}
    return base + ("?" + urllib.parse.urlencode(sorted(q.items())) if q else "")


def filters_html(f: dict, fc: dict, base: str = "/wrath/realms") -> str:
    def chips(key, label, opts):
        if not opts:
            return ""
        cur = f.get(key)
        links = [f'<a href="{e(_qs(f, base, **{key: None}))}"{' class="on"' if cur is None else ""}>any</a>']
        for v, text in opts:
            links.append(f'<a href="{e(_qs(f, base, **{key: v}))}"{' class="on"' if cur == v else ""}>{e(text)}</a>')
        return f'<span>{e(label)}:</span> ' + " ".join(links)
    parts = [chips("build", "Build", [(b, BUILDS[b]) for b in fc["build"]]),
             chips("tag", "Rules", [(t, TAG_LABEL[t]) for t in fc["tag"]]),
             chips("region", "Region", [(g, REGION_LABEL[g]) for g in fc["region"]]),
             chips("lang", "Language", [(x, LANGS.get(x, x)) for x in fc["lang"]])]
    now = (f'<a href="{e(_qs(f, base, now=None))}">everyone</a> <a class="on" href="#">has players now</a>' if f.get("now")
           else f'<a class="on" href="#">everyone</a> <a href="{e(_qs(f, base, now=True))}">has players now</a>')
    parts.append('<span>Show:</span> ' + now)
    return '<nav class="net-filters" aria-label="Filter realms">' + "".join(f"<div>{p}</div>" for p in parts if p) + "</nav>"


def card(r: dict, join_base: str, ruleset_labels: dict, share_box=None) -> str:
    cls = "realm " + {"featured": "featured", "sample": "sample"}.get(r.get("group"), "")
    join = f'{join_base}/join/{r["id"]}'
    button = f'<a class="btn" href="{e(join)}" rel="noopener noreferrer">Join</a>'
    return (f'<div class="{cls.strip()}" id="r-{e(r["id"])}"><h2>{e(r["name"])}</h2>'
            f'<div class="tags">{tags_html(r, ruleset_labels)}</div>'
            + (f'<p>{e(r["tagline"])}</p>' if r.get("tagline") else '')
            + (f'<p class="fine">{e(VR_LINE)}</p>' if r.get("vr") else '')
            + ('<details><summary>House rules</summary><ol>'
               + "".join(f'<li>{e(x)}</li>' for x in r["rules"]) + '</ol></details>' if r.get("rules") else '')
            + f'<p>{button} <a class="report" href="/wrath/realms/report?realm={e(r["id"])}" rel="nofollow">Report</a></p>'
            + (share_box(f'/wrath/r/{r["id"]}') if share_box else '') + '</div>')


def sample_card(st: dict, rec: dict | None, share_box=None, sample: dict | None = None) -> str:
    """Our own realm, pinned below the featured ones. Numbers from its own status, else its relay record.
    sample: {"name", "temporary", "blurb_html"} from the portal (the Leyline Sample Hangout while WU_SAMPLER=1 is set,
    realm/sampler.sh; the realm's own name before that)."""
    sm = sample or {}
    name = sm.get("name") or SAMPLE_NAME
    temporary = sm.get("temporary", True)
    blurb = sm.get("blurb_html") or ('<!-- TODO(owner): the sample hangout blurb -->'
                                     '<p>A place to try the game in your browser and meet people. Leyline runs it for '
                                     'now; the realms around it are run by players.</p>')
    live = bool(st.get("online")) if st else bool(rec and rec.get("live"))
    players = _nonneg(st.get("players")) if st else None
    bots = _nonneg(st.get("bots")) if st else None
    if players is None and rec:
        players, bots = rec.get("players"), rec.get("bots")
    r = {"live": live, "players": players, "bots": bots}
    return (f'<div class="realm sample" id="sample"><h2>{e(name)}</h2>'
            '<div class="tags"><span class="tag">Official</span>'
            + ('<span class="badge warn">Temporary</span>' if temporary else '')
            + f'<span class="tag">Run by Leyline</span><span class="tag ver">3.3.5a</span>{_players(r)}</div>'
            + blurb
            # its relay record is there: the go intent lands players straight in Dalaran (stream/links.py)
            + ('<p><a class="btn primary" href="/wrath?go=h:dalaran">Play in Dalaran</a></p>' if rec else
               '<p><a class="btn primary" href="/wrath">Play</a></p>')
            + (share_box("/wrath/r/wrath") if share_box else '') + '</div>')


def page_body(realms: list[dict], ok: bool, query: dict, sample_status: dict, join_base: str, ruleset_labels: dict,
              share_box=None, pack_url: str | None = None, base: str = "/wrath/realms", sample: dict | None = None) -> str:
    """Everything between the crest and the footer of /wrath/realms."""
    shown = order(realms)
    t = totals(shown, sample_status)
    f = filters_from(query or {})
    community = [r for r in shown if not r["sample"]]
    sample_rec = next((r for r in shown if r["sample"]), None)
    hits = [r for r in community if matches(r, f)]
    featured = [r for r in hits if r["group"] == "featured"]
    rest = [r for r in hits if r["group"] != "featured"]
    out = [f'<p class="net-line">{e(network_line(t))}</p>', filters_html(f, facets(community), base)]
    out += [card(r, join_base, ruleset_labels, share_box) for r in featured]
    out.append(sample_card(sample_status, sample_rec, share_box, sample))
    if rest:
        out += [card(r, join_base, ruleset_labels, share_box) for r in rest]
        if not ok:
            out.insert(2, '<p class="fine">The realm list may be a little out of date right now.</p>')
    elif community and f:
        out.append(f'<p class="fine">No realms match these filters. <a href="{e(base)}">Show every realm</a></p>')
    elif ok and not community:
        out.append('<p class="fine">No community realms are open right now. Anyone can host one: a private realm for '
                   'friends or a public one, with their own GM login and rules.</p>')
    elif not ok:
        out.append('<p class="fine">The community realm list isn\'t reachable right now. Try again in a minute.</p>')
    out.append(host_cta("realms", pack_url))
    return "".join(out)


# ----------------------------------------------------------------------------------------------- reports
def data_dir() -> str:
    return os.environ.get("WU_NETWORK_DIR") or os.path.join(os.environ.get("WU_PORTAL_DATA", "/data"), "network")


def _rpath() -> str:
    return os.path.join(data_dir(), "realm-reports.json")


def _load() -> dict:
    try:
        with open(_rpath(), encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and isinstance(doc.get("reports"), list):
            return doc
    except (OSError, ValueError):
        pass
    return {"format": 1, "reports": []}


def _save(doc: dict) -> None:
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, _rpath())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def reports(status: str = "open", realm: str | None = None) -> list[dict]:
    """Realm reports, newest first ("" = every status). The admin console reads these."""
    rs = [r for r in _load()["reports"] if isinstance(r, dict)]
    rs = [r for r in rs if (not status or r.get("status") == status) and (realm is None or r.get("realm") == realm)]
    return sorted(rs, key=lambda r: str(r.get("at", "")), reverse=True)


def open_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for r in reports("open"):
        out[r["realm"]] = out.get(r["realm"], 0) + 1
    return out


def resolve(realm: str, by: str, how: str = "resolved") -> int:
    """Close every open report on a realm (the admin console's action); returns how many."""
    n = 0
    with _lock:
        doc = _load()
        for r in doc["reports"]:
            if isinstance(r, dict) and r.get("realm") == realm and r.get("status") == "open":
                r.update(status=how if how in ("resolved", "dismissed") else "resolved", closed_by=str(by)[:40],
                         closed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                n += 1
        if n:
            _save(doc)
    return n


def add_report(realm: str, realm_name: str, reason: str, note: str, account: str, display: str,
               now: float | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else now
    if not REALM_ID_RE.match(realm or ""):
        return False, "That is not a realm on the list."
    if reason not in REPORT_REASON:
        return False, "Pick a reason."
    note = " ".join("".join(c for c in (note or "") if c.isprintable()).split())
    if len(note) > NOTE_LEN:
        return False, f"Keep the note under {NOTE_LEN} characters."
    who = hashlib.sha256(("realm-report:" + account).encode()).hexdigest()[:16]
    with _lock:
        q = [t for t in _rate.get(who, []) if now - t < 3600]
        if len(q) >= REPORTS_PER_HOUR:
            return False, "You've sent a lot of reports this hour. Try again later."
        doc = _load()
        if any(isinstance(r, dict) and r.get("realm") == realm and r.get("by") == who and r.get("status") == "open"
               for r in doc["reports"]):
            return False, "You already reported this realm. Staff will look at it."
        q.append(now)
        _rate[who] = q
        doc["reports"].append({"id": secrets.token_hex(6), "realm": realm, "name": str(realm_name)[:32],
                               "reason": reason, "note": note, "by": who, "by_name": str(display)[:40],
                               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "status": "open"})
        doc["reports"] = doc["reports"][-MAX_REPORTS:]
        _save(doc)
    return True, "Thanks. Leyline staff will look at it."


def csrf(account: str) -> str:
    return hmac.new(_csrf_key, ("realm-report:" + account).encode(), hashlib.sha256).hexdigest()[:32]


# ----------------------------------------------------------------------------------------------- routes
def match(path: str) -> bool:
    return path in ("/wrath/realms.json", "/wrath/realms/report")


def _account(me) -> str:
    if not isinstance(me, dict):
        return ""
    for k in ("id", "user_id", "account_id", "username"):
        v = me.get(k)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            return str(v).strip()[:64]
    return ""


def who(h, path: str):
    """(account, display) for the signed-in website account, or None after answering (sign-in or an error)."""
    cookie = h.headers.get("Cookie", "")
    if "wr_session=" not in cookie:
        h.redirect("/login?next=" + urllib.parse.quote(path, safe=""))
        return None
    status, me = P("portal_get")("/api/me", cookie, h.ip(), h.headers.get("User-Agent", ""))
    if status in (401, 403) or 300 <= status < 400:
        h.redirect("/login?next=" + urllib.parse.quote(path, safe=""))
        return None
    acct = _account(me) if status == 200 else ""
    if not acct:
        h.send(503, P("error_page")("The website isn't answering right now. Please try again shortly."))
        return None
    return acct, str(me.get("display_name") or me.get("username") or "")[:40]


def _listed(rid: str):
    cr = P("community_realms")
    realms = cr()[0] if cr else []
    return next((r for r in realms if r.get("id") == rid), None)


def report_page(account: str, rid: str, r: dict | None, msg: str = "", done: bool = False) -> bytes:
    render = P("render")
    if done:
        body = (f'<section class="realm"><h2>Report sent</h2><p>{e(msg)}</p>'
                '<p><a href="/wrath/realms">Back to the realms</a></p></section>')
    elif r is None:
        body = ('<section class="realm"><h2>Not on the list</h2><p>That realm is not on the Leyline list right now.</p>'
                '<p><a href="/wrath/realms">Back to the realms</a></p></section>')
    else:
        opts = "".join(f'<label><input type="radio" name="reason" value="{k}" required> {e(t)}</label><br>'
                       for k, t in REPORT_REASONS)
        body = (f'<section class="realm"><h2>Report {e(r["name"])}</h2>'
                + (f'<p class="fine">{e(msg)}</p>' if msg else '')
                + '<p>Leyline staff read every report. They can hide a realm from the list or flag it. Your report '
                  'is not shown to the host.</p>'
                  '<form method="post" action="/wrath/realms/report">'
                  f'<input type="hidden" name="realm" value="{e(rid)}"><input type="hidden" name="csrf" value="{e(csrf(account))}">'
                  f'<p>{opts}</p><p><label>What happened? (optional)<br><textarea name="note" maxlength="{NOTE_LEN}" '
                  'rows="3" cols="40"></textarea></label></p><p><button class="btn primary" type="submit">Send report</button> '
                  '<a href="/wrath/realms">Cancel</a></p></form></section>')
    if render is None:
        return body.encode("utf-8")
    return render(body, title="Report a realm")


def get(h, path: str, query: dict) -> None:
    lim = P("browse_limit")
    if lim is not None and not lim.hit(h.ip(), 600):
        h.send(429, b'{"error":"too many requests"}\n', "application/json")
        return
    if path == "/wrath/realms.json":
        cr, rs = P("community_realms"), P("realm_status")
        realms, ok = cr() if cr else ([], False)
        si = P("sample_info")
        h.send(200, realms_json(realms, ok, rs() if rs else {}, si() if si else None), "application/json; charset=utf-8",
               headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=30"})
        return
    acct = who(h, path)
    if acct is None:
        return
    rid = (query.get("realm") or [""])[0][:16]
    h.send(200, report_page(acct[0], rid, _listed(rid) if REALM_ID_RE.match(rid) else None))


def _form(h) -> dict | None:
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > 4096:
        return None
    try:
        q = urllib.parse.parse_qs(h.rfile.read(n).decode("utf-8"), keep_blank_values=True, max_num_fields=10)
    except (UnicodeDecodeError, ValueError):
        return None
    return {k: v[0] for k, v in q.items()}


def post(h, path: str) -> None:
    if path != "/wrath/realms/report":
        h.send(405, b"method not allowed\n", "text/plain")
        return
    lim = P("gate_limit")
    if lim is not None and not lim.hit("realm-report:" + h.ip(), 20):
        h.send(429, P("busy_page")(back="/wrath/realms"))
        return
    origin = h.headers.get("Origin", "")
    if origin and origin != f"https://{P('PUBLIC_HOST') or 'play.openvanilla.app'}" and not (origin == "null" and h.headers.get("Sec-Fetch-Site", "") == "same-origin"):
        h.send(403, P("error_page")("That form came from another site."))
        return
    form = _form(h)
    if form is None:
        h.send(400, P("error_page")("That form didn't arrive in one piece. Please try again."))
        return
    acct = who(h, path)
    if acct is None:
        return
    account, display = acct
    rid = form.get("realm", "")[:16]
    r = _listed(rid) if REALM_ID_RE.match(rid) else None
    if not hmac.compare_digest(form.get("csrf", ""), csrf(account)):
        h.send(400, report_page(account, rid, r, "The form timed out. Please send it again."))
        return
    if r is None:
        h.send(404, report_page(account, rid, None))
        return
    ok, msg = add_report(rid, r.get("name", ""), form.get("reason", ""), form.get("note", ""), account, display)
    h.send(200 if ok else 400, report_page(account, rid, r, msg, done=ok))
