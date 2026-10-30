"""Leyline's network switches and the Host pack listing, for the site (wu-portal). Standard library only.

    GET /wrath/leyline/flags.json      the P2P/torrent feature flags (public, CORS *): every flag OFF until the
                                       admin console turns it on with write_flags()
    GET /wrath/leyline/hostpack.json   the Host pack descriptor (public, CORS *): version, download, sha256, size
    all.json                           add_hostpack() appends the Host pack to /wrath/mods/all.json as a project of
                                       category "tools", kind "hostpack"

The flags file (docs/P2P-AND-TORRENT.md):

    {"format": 1, "updated_at": "2026-10-29T00:00:00Z",
     "flags": {"p2p_hosting": false, "torrent_downloads": false, "torrent_seeding": false, "webrtc_presence": false,
               "mesh_realms": false, "mesh_relays": false, "relay_volunteer": false, "herokey_sso": false},
     "limits": {"seed_upload_kbps": 0, "seed_ratio_pct": 0, "max_peers": 0},
     "stun": ["stun.cloudflare.com:3478"],
     "sha256": "<sha256 of the canonical JSON of everything above>"}

Canonical JSON: json.dumps(doc_without_sha256, sort_keys=True, separators=(",", ":"), ensure_ascii=False). The
launcher (launcher/src-tauri/src/p2p/flags.rs) recomputes it and treats a mismatch, a missing file or a broken
one as "everything off". A local override in the launcher (Settings > Advanced) wins over this file.

For the admin console: call write_flags(path(), {"torrent_downloads": True}, by="<admin account>"). It checks
names and types, writes atomically, and appends one line per change to <file>.log (who, when, what). The
served file never names the admin.

Files: $WU_LEYLINE_DIR (default /data/leyline, i.e. $WU/portal-data/leyline: writable) holds flags.json and, optionally,
hostpack.json; a hostpack.json beside this module (stream/hostpack.json, written by
hosting/pack/make-hostpack.py) is the fallback. Neither file holds game data: the Host pack is our code only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time

DIR = os.environ.get("WU_LEYLINE_DIR", "/data/leyline")   # /data: wu-portal's one writable mount
HERE = os.path.dirname(os.path.abspath(__file__))
FORMAT = 1
KNOWN = ("p2p_hosting", "torrent_downloads", "torrent_seeding", "webrtc_presence",
         # the Leyline mesh (docs/LEYLINE-MESH.md): the realm list from signed records; community relays;
         # offering "Help the network: relay for others" (each PC still opts in on its own)
         "mesh_realms", "mesh_relays", "relay_volunteer",
         # Hero Key sign-in on Beacons (docs/HERO-KEY-SSO.md, stream/herokey_sso.py): hops and the launcher sign in to
         # a community realm with the website account; off = the realm's own join page, as before
         "herokey_sso")
LIMITS = {"seed_upload_kbps": 100_000, "seed_ratio_pct": 1000, "max_peers": 200}
DEFAULT_STUN = ["stun.cloudflare.com:3478"]
_STUN_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}:[0-9]{1,5}$")
PACK_ORIGINS = ("https://play.openvanilla.app/", "https://github.com/orionopenwow/Leyline/releases/download/")
_VER_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,2}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
JSON = "application/json; charset=utf-8"


def path() -> str:
    return os.path.join(DIR, "flags.json")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def doc_hash(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "sha256"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def make_doc(flags: dict | None = None, limits: dict | None = None, stun: list | None = None,
             updated_at: str | None = None) -> dict:
    """A complete, hashed flags document. Unknown flags are dropped; anything not a real bool is off."""
    fl = {k: (flags or {}).get(k) is True for k in KNOWN}
    lim = {k: max(0, min(int((limits or {}).get(k) or 0), cap)) for k, cap in LIMITS.items()}
    st = [s for s in (DEFAULT_STUN if stun is None else stun) if isinstance(s, str) and _STUN_RE.match(s)][:4]
    doc = {"format": FORMAT, "updated_at": updated_at or _now(), "flags": fl, "limits": lim, "stun": st}
    doc["sha256"] = doc_hash(doc)
    return doc


def defaults() -> dict:
    """Everything off (what is served when no file was ever written)."""
    return make_doc(updated_at="2026-10-29T00:00:00Z")


def check(doc) -> bool:
    return (isinstance(doc, dict) and doc.get("format") == FORMAT and isinstance(doc.get("flags"), dict)
            and doc.get("sha256") == doc_hash(doc))


def load(p: str | None = None) -> dict:
    """The flags file, or the all-off defaults when it is missing or broken."""
    try:
        with open(p or path(), encoding="utf-8") as f:
            doc = json.load(f)
        if check(doc):
            return doc
    except (OSError, ValueError):
        pass
    return defaults()


def _atomic(p: str, data: bytes) -> None:
    d = os.path.dirname(p) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".flags.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_flags(p: str | None, changes: dict, by: str = "", limits: dict | None = None,
                stun: list | None = None) -> dict:
    """Change some flags (and optionally the limits / STUN list) and write the file. Raises ValueError for an
    unknown flag or a value that is not True/False. Returns the new document."""
    p = p or path()
    for k, v in (changes or {}).items():
        if k not in KNOWN:
            raise ValueError(f"unknown flag {k!r}")
        if not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
    for k in (limits or {}):
        if k not in LIMITS:
            raise ValueError(f"unknown limit {k!r}")
    cur = load(p)
    flags = dict(cur["flags"], **(changes or {}))
    doc = make_doc(flags, dict(cur.get("limits") or {}, **(limits or {})),
                   cur.get("stun") if stun is None else stun)
    _atomic(p, (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    who = re.sub(r"[^A-Za-z0-9 _.@-]", "", str(by))[:64]
    line = json.dumps({"at": doc["updated_at"], "by": who, "flags": changes or {}, "limits": limits or {},
                       "stun": stun}, ensure_ascii=False)
    with open(p + ".log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return doc


# ------------------------------------------------------------------------------------------------ Host pack
def hostpack(paths: tuple[str, ...] | None = None) -> dict | None:
    """The Host pack descriptor ({"format":1, name, version, download, sha256, size, torrent}) or None."""
    for p in paths or (os.path.join(DIR, "hostpack.json"), os.path.join(HERE, "hostpack.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        ok = (isinstance(d, dict) and d.get("format") == 1 and isinstance(d.get("version"), str)
              and _VER_RE.match(d["version"]) and isinstance(d.get("download"), str)
              and d["download"].startswith(PACK_ORIGINS) and isinstance(d.get("sha256"), str)
              and _SHA_RE.match(d["sha256"]))
        if not ok:
            continue
        t = d.get("torrent")
        return {"format": 1, "name": str(d.get("name") or "Host pack")[:64], "version": d["version"],
                "download": d["download"], "sha256": d["sha256"],
                "size": d["size"] if isinstance(d.get("size"), int) else None,
                "torrent": t if isinstance(t, str) and t.startswith(PACK_ORIGINS) else None}
    return None


def hostpack_project(d: dict, public_base: str = "https://play.openvanilla.app") -> dict:
    """The Host pack as an all.json project (mods/all-json.md), category "tools", kind "hostpack"."""
    return {
        "id": "mod:host-pack", "source": "packaged", "name": d["name"],
        "description": "Host your own 3.3.5a realm from this PC with Docker: the scripts, the realm tooling and "
                       "the relay agent. Our code only, no game data. Leyline installs and updates it from the Host page.",
        "category": "tools", "builds": ["3.3.5a"], "author": "Leyline", "author_url": "", "licence": "MIT",
        "repo": "https://github.com/orionopenwow/Leyline", "page": public_base + "/wrath/docs/hosting",
        "credits": "Host pack by Leyline · MIT", "stars": None, "last_push": "", "submitted_by": "",
        "submitted_at": "", "last_checked": "", "version": d["version"], "kind": "hostpack", "permissions": None,
        "on_wrath": None, "download": d["download"], "sha256": d["sha256"], "size": d.get("size"),
        "torrent": d.get("torrent"),
    }


def add_hostpack(all_json: bytes, d: dict | None = None) -> bytes:
    """all.json with the Host pack project added (once). Unchanged when there is no pack or the body is odd."""
    d = d if d is not None else hostpack()
    if not d:
        return all_json
    try:
        doc = json.loads(all_json)
        projects = doc["projects"]
    except (ValueError, KeyError, TypeError):
        return all_json
    if not isinstance(projects, list) or any(isinstance(p, dict) and p.get("id") == "mod:host-pack" for p in projects):
        return all_json
    projects.append(hostpack_project(d))
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def serve(p: str):
    """(status, body, content type) for our two public files (the portal sends them public, CORS *), or None
    for any other path."""
    if p == "/wrath/leyline/flags.json":
        return 200, (json.dumps(load(), indent=1, ensure_ascii=False) + "\n").encode("utf-8"), JSON
    if p == "/wrath/leyline/hostpack.json":
        d = hostpack()
        if not d:
            return 404, b'{"error":"no host pack published yet"}\n', JSON
        return 200, (json.dumps(d, indent=1) + "\n").encode("utf-8"), JSON
    return None
