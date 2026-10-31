"""The Leyline Admin Console: staff pages on the Wrath portal (stream/wrath_portal.py hooks it in).

Everything the owner and staff need to keep Leyline and its launcher running, in one place, server-rendered, in the
Leyline look, with a little plain script (only for the typed confirm). Nothing here deletes player data.

    GET  /wrath/admin                  dashboard: realm and relay, launcher versions (only if something logs them),
                                       catalog counts, open reports, queues
    GET  /wrath/admin/catalog          packaged mods and community links: approve, reject, unpublish, feature, edit
                                       name, description and category, re-run the checker
    GET  /wrath/admin/catalog/mod/<id> one mod: its checker findings
    GET  /wrath/admin/workshop         what players made (characters.mod_workshop_items, over SOAP: ov_admin.lua)
    GET  /wrath/admin/hub              the community index: submissions queue, hide or unhide, re-scan
    GET  /wrath/admin/realms           community realms from the Beacons relay: hide, flag, mark official, heartbeats
    GET  /wrath/admin/releases         the launcher's GitHub releases, the stable/beta channel and hold, News posts
    GET  /wrath/admin/flags            feature flags (owner)
    GET  /wrath/admin/themes           theme packs (the Workshop category "themes"): approve, reject, feature
    GET  /wrath/admin/reports          .bug reports (ov_admin.lua), message reports (stream/social.py), community link
                                       reports (stream/projects.py): resolve, notes
    GET  /wrath/admin/forum            the forum (stream/forum.py): reported posts (hide, done, dismiss), threads (pin, lock,
                                       hide, merge a duplicate into another), hidden posts (show again)
    GET  /wrath/admin/health           what this server can see of itself (and Autopilot, when it is reachable)
    GET  /wrath/admin/staff            who is staff (owner: grant and revoke)
    GET  /wrath/admin/audit            every admin action: who, what, when, before and after
    POST /wrath/admin/act              every action (one form field "action"); CSRF token, typed confirm for the
                                       destructive ones, rate-limited, written to the audit log

Public feeds (no sign-in, CORS *, cached a minute): what the launcher and the other services read.

    GET  /wrath/leyline/flags.json          the host-pack/P2P agent's file (stream/leyline_net.py serves it when present;
                                            this module writes it through leyline_net.write_flags, or in the same format)
    GET  /wrath/leyline/channel.json        {"format": 1, "updated_at", "stable": {version, tag, url} | null,
                                             "beta": {...} | null, "hold": false, "hold_note": ""}
    GET  /wrath/leyline/news.json           {"format": 1, "updated_at", "posts": [{id, date, tag, title, items[]}]}
    GET  /wrath/leyline/realm-overrides.json {"format": 1, "updated_at", "hidden": [ids], "official": [ids]}

Who may come in (docs/ADMIN-CONSOLE.md): the signed-in website account (the same /api/me as everything else) is
    owner   when its account id is in WU_ADMIN_OWNERS
    staff   when it is in the staff file (the owner grants it on /wrath/admin/staff), in WU_ADMIN_STAFF, or in
            WU_MODS_ADMINS (the Workshop's own admins: stream/projects.py), or when its game account's GM level on
            the realm is at least WU_ADMIN_GM_LEVEL (default 3; 0 turns that off), asked over SOAP ("ovadmin gm")
Anyone else gets a plain "staff only" page (403) with their own account id, so the owner can grant it.

Files (WU_ADMIN_DIR, default $WU_PORTAL_DATA/admin = /data/admin, the portal's one writable mount):
    staff.json            {"format": 1, "staff": {"<account id>": {"name", "by", "at"}}}
    audit.jsonl           one JSON object a line: {at, who, name, role, action, target, before, after, ok, note}
    overrides.json        {"format": 1, "mods": {id: {...}}, "projects": {pid: {...}}, "workshop": {id: {...}}}:
                           state ("approved" | "rejected" | "unpublished"),
                           featured, category, name, description. stream/workshop.py and stream/creations.py read it
                           through adjust_catalog().
    realm-overrides.json  {"format": 1, "realms": {"<realm id>": {"hidden", "official", "flag", "by", "at"}}}
    notes.json            report notes and resolutions, {"<kind>:<id>": {"status", "notes": [{by, at, text}]}}
    checks/<kind>-<id>.json  the checker's last findings
    secret.key            the CSRF key (0600), unless WU_ADMIN_SECRET is set
The public feeds live in WU_LEYLINE_DIR (default $WU_PORTAL_DATA/leyline): flags.json, channel.json, news.json.
The hub's own folder ($WU_PORTAL_DATA/hub, stream/hub.py): decisions.jsonl gets one line per decision (approve,
reject, delist), rescan.json the re-scan requests; submissions.jsonl is only read.

Other settings: WU_ADMIN_OWNERS, WU_ADMIN_STAFF, WU_ADMIN_GM_LEVEL, WU_ADMIN_SECRET, WU_LEYLINE_RELEASES_API (the
GitHub releases API URL), WU_THEMES_REVIEW (1: theme packs wait for approval), WU_HUB_INDEX / WU_HUB_DIR,
WU_LAUNCHER_VERSIONS, WU_AUTOPILOT_STATUS, WU_MOD_TOOL (mods/wu-mod.py). Standard library only.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import html
import importlib.util
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("wrath-portal.admin")
e = html.escape
HERE = os.path.dirname(os.path.abspath(__file__))

_get = None


def bind(getter) -> None:
    """getter(name) -> one of the portal's globals (portal_get, ac_soap, SoapError, workshop, ...), looked up late."""
    global _get
    _get = getter


def P(name):
    try:
        return _get(name) if _get else None
    except KeyError:
        return None


# ----------------------------------------------------------------------------------------------
# Settings and limits
# ----------------------------------------------------------------------------------------------

ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
REALM_ID_RE = re.compile(r"^[a-z2-7]{16}$")
MOD_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
PID_RE = re.compile(r"^[0-9a-f]{12}$")
WS_ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
HUB_ENTRY_RE = re.compile(r"^link:[0-9a-f]{12}$")
VERSION_RE = re.compile(r"^\d{1,5}\.\d{1,5}\.\d{1,5}(?:[-+][0-9A-Za-z.-]{1,40})?$")
TAG_RE = re.compile(r"^(?:launcher-)?v?(\d{1,5}\.\d{1,5}\.\d{1,5}(?:[-+][0-9A-Za-z.-]{1,40})?)$")
BRAND_RE = re.compile(r"(?i)world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|\bwow\b")
GAME_TEXT_BAD = re.compile(r"[^A-Za-z0-9 \-!&.,?:()]")   # ov_workshop.lua's cleanText characters
STATES = ("approved", "pending", "rejected", "unpublished")
BUG_STATES = ("new", "seen", "resolved", "wontfix")
MAX_FORM = 8192
POSTS_PER_MIN = 30          # per account
PAGES_PER_MIN = 240         # per account
IP_PER_MIN = 120            # before sign-in is known (each costs an /api/me)
CACHE_S = 30
RELEASES_TTL = 600
GM_TTL = 300
SITE_RELEASES = "https://github.com/orionopenwow/Leyline/releases"


def _portal_data() -> str:
    return os.environ.get("WU_PORTAL_DATA", "/data")


def admin_dir() -> str:
    return os.environ.get("WU_ADMIN_DIR") or os.path.join(_portal_data(), "admin")


def leyline_dir() -> str:
    return os.environ.get("WU_LEYLINE_DIR") or os.path.join(_portal_data(), "leyline")


def _now() -> float:
    return time.time()


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_now() if t is None else t))


def _csv_env(name: str) -> set[str]:
    return {x.strip() for x in os.environ.get(name, "").split(",") if x.strip()}


# ----------------------------------------------------------------------------------------------
# Files: read anything, write atomically (temp file, fsync, rename) under one lock
# ----------------------------------------------------------------------------------------------

_lock = threading.RLock()


def _read_json(path: str, default, limit: int = 4_000_000):
    try:
        with open(path, "rb") as f:
            b = f.read(limit + 1)
        if len(b) > limit:
            return default
        doc = json.loads(b.decode("utf-8"))
        return doc if isinstance(doc, type(default)) else default
    except (OSError, ValueError, UnicodeDecodeError):
        return default


def _write_json(path: str, doc, mode: int = 0o644) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apath(name: str) -> str:
    return os.path.join(admin_dir(), name)


def _lpath(name: str) -> str:
    return os.path.join(leyline_dir(), name)


def _writable(d: str) -> bool:
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".probe-")
        os.close(fd)
        os.unlink(tmp)
        return True
    except OSError:
        return False


# ----------------------------------------------------------------------------------------------
# The audit log: every action, who, what, when, before and after. Append-only; never rewritten here.
# ----------------------------------------------------------------------------------------------

def audit(user: dict, action: str, target: str, before, after, ok: bool = True, note: str = "") -> None:
    rec = {"at": _iso(), "who": user.get("account", ""), "name": user.get("name", ""), "role": user.get("role", ""),
           "action": action, "target": str(target)[:120], "before": before, "after": after, "ok": bool(ok),
           "note": str(note)[:300]}
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
    with _lock:
        os.makedirs(admin_dir(), exist_ok=True)
        fd = os.open(_apath("audit.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    log.info("admin %s %s by %s: %s", action, str(target)[:60], user.get("account", ""), "ok" if ok else "refused")


def audit_tail(n: int = 200, action: str = "") -> list[dict]:
    try:
        with open(_apath("audit.jsonl"), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 2_000_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and (not action or r.get("action", "").startswith(action)):
            out.append(r)
            if len(out) >= n:
                break
    return out


# ----------------------------------------------------------------------------------------------
# Rate limits
# ----------------------------------------------------------------------------------------------

class _Window:
    def __init__(self, seconds: int):
        self.seconds, self.q, self.lock = seconds, {}, threading.Lock()

    def hit(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.q.setdefault(key, collections.deque())
            while q and now - q[0] > self.seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.q) > 20000:
                self.q = {k: v for k, v in self.q.items() if v}
            return True


limits = _Window(60)


# ----------------------------------------------------------------------------------------------
# Who is staff
# ----------------------------------------------------------------------------------------------

def owners() -> set[str]:
    return _csv_env("WU_ADMIN_OWNERS")


def staff_file() -> dict:
    doc = _read_json(_apath("staff.json"), {})
    s = doc.get("staff") if isinstance(doc.get("staff"), dict) else {}
    return {k: v for k, v in s.items() if isinstance(k, str) and ACCOUNT_ID_RE.fullmatch(k) and isinstance(v, dict)}


def env_staff() -> set[str]:
    return _csv_env("WU_ADMIN_STAFF") | _csv_env("WU_MODS_ADMINS")


def gm_min() -> int:
    try:
        return max(0, int(os.environ.get("WU_ADMIN_GM_LEVEL", "3")))
    except ValueError:
        return 3


_gm_cache: dict[str, tuple[float, int]] = {}


def gm_level(game_user: str) -> int:
    """The game account's highest GM level on the realm (ov_admin.lua "ovadmin gm"), cached; 0 when unknown."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,16}", game_user or ""):
        return 0
    key = game_user.upper()
    hit = _gm_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    level = 0
    ok, lines, _ = soap_lines(f"ovadmin gm {key}")
    if ok:
        for line in lines:
            m = re.match(rf"^ovadmin gm {key} (\d+)$", line)
            if m:
                level = int(m.group(1))
    if len(_gm_cache) > 2000:
        _gm_cache.clear()
    _gm_cache[key] = (time.monotonic() + GM_TTL, level)
    return level


def role_of(account: str, game_user_fn=None) -> str:
    """"owner", "staff" or "" for a website account id. game_user_fn() -> the game account name (asked only when
    the GM-level rule is needed)."""
    if not account:
        return ""
    if account in owners():
        return "owner"
    if account in staff_file() or account in env_staff():
        return "staff"
    need = gm_min()
    if need and game_user_fn is not None:
        try:
            user = game_user_fn()
        except Exception:   # noqa: BLE001
            user = ""
        if user and gm_level(user) >= need:
            return "staff"
    return ""


def account_of(me) -> str:
    if not isinstance(me, dict):
        return ""
    for k in ("id", "user_id", "account_id", "username"):
        v = me.get(k)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            s = str(v).strip()[:64]
            return s if ACCOUNT_ID_RE.fullmatch(s) else ""
    return ""


def display_of(me) -> str:
    if not isinstance(me, dict):
        return ""
    return " ".join(str(me.get("display_name") or me.get("username") or "").split())[:40] or "staff"


def _session(h) -> str:
    for part in h.headers.get("Cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "wr_session":
            return v[:512]
    return ""


_secret_cache: list[bytes] = []


def _secret() -> bytes:
    env = os.environ.get("WU_ADMIN_SECRET", "")
    if env:
        return env.encode()
    if _secret_cache:
        return _secret_cache[0]
    path = _apath("secret.key")
    with _lock:
        try:
            with open(path, "rb") as f:
                key = f.read(64)
        except OSError:
            key = b""
        if len(key) < 32:
            key = secrets.token_bytes(32)
            try:
                os.makedirs(admin_dir(), exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(key)
            except OSError:
                pass   # in memory only: forms made before a restart then ask again
        _secret_cache.append(key)
    return _secret_cache[0]


def csrf_token(session: str, account: str) -> str:
    return hmac.new(_secret(), f"admin|{session}|{account}".encode(), hashlib.sha256).hexdigest()[:40]


def who(h, path: str) -> dict | None:
    """The signed-in staff member {account, name, role, session}, or None after answering (sign-in, 403, 503, 429)."""
    ip = h.ip()
    if not limits.hit("ip:" + ip, IP_PER_MIN):
        h.send(429, page_simple("Slow down", "Too many requests. Wait a minute and try again."), headers=NOINDEX)
        return None
    cookie = h.headers.get("Cookie", "")
    ua = h.headers.get("User-Agent", "")
    if "wr_session=" not in cookie:
        h.redirect("/login?next=" + urllib.parse.quote(path, safe=""))
        return None
    status, me = P("portal_get")("/api/me", cookie, ip, ua)
    if status in (401, 403) or 300 <= status < 400:
        h.redirect("/login?next=" + urllib.parse.quote(path, safe=""))
        return None
    if status != 200 or not isinstance(me, dict) or not me:
        h.send(503, page_simple("Try again shortly", "The website isn't answering right now."), headers=NOINDEX)
        return None
    account = account_of(me)

    def game_user():
        st, play = P("portal_get")("/api/play", cookie, ip, ua)
        return str(play.get("user", "")) if st == 200 and isinstance(play, dict) else ""
    role = role_of(account, game_user)
    if not role:
        h.send(403, denied_page(account), headers=NOINDEX)
        return None
    return {"account": account, "name": display_of(me), "role": role, "session": _session(h)}


# ----------------------------------------------------------------------------------------------
# SOAP (ov_admin.lua on the realm)
# ----------------------------------------------------------------------------------------------

def soap_lines(command: str) -> tuple[bool, list[str], str]:
    """(ok, lines, error) for one "ovadmin ..." console command."""
    fn, err_cls = P("ac_soap"), P("SoapError")
    if fn is None:
        return False, [], "no SOAP here"
    try:
        text = fn(command)
    except Exception as ex:   # noqa: BLE001: SoapError or anything else: the page says so
        kind = getattr(ex, "kind", "") if err_cls is not None and isinstance(ex, err_cls) else "error"
        return False, [], f"the realm did not answer ({kind or 'error'})"
    lines = [x.rstrip("\r") for x in (text or "").split("\n") if x.strip()]
    for x in lines:
        if x.startswith("ovadmin error:"):
            return False, lines, x[len("ovadmin error:"):].strip()[:200]
    if not any(x.startswith("ovadmin ") for x in lines):
        return False, lines, "the realm's ov_admin.lua is not loaded (run the scripts step)"
    return True, lines, ""


def game_text(v: str, n: int) -> str:
    """Text for a SOAP command: the characters ov_workshop.lua keeps, one line, at most n."""
    return " ".join(GAME_TEXT_BAD.sub("", " ".join(str(v or "").split())).split())[:n]


_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    v = fn()
    _cache[key] = (time.monotonic() + ttl, v)
    return v


def forget(prefix: str) -> None:
    for k in [k for k in _cache if k.startswith(prefix)]:
        _cache.pop(k, None)


def ws_list(state: str) -> tuple[bool, list[dict], str]:
    def get():
        ok, lines, err = soap_lines(f"ovadmin ws list {state} 200")
        rows = []
        for x in lines:
            f = x.split("\t")
            if f[0] == "ROW" and len(f) >= 12 and WS_ID_RE.fullmatch(f[1]):
                rows.append({"id": int(f[1]), "kind": f[2][:8], "state": f[3][:10], "version": f[4][:6],
                             "plays": f[5][:10], "up": f[6][:10], "down": f[7][:10], "author": f[8][:12],
                             "flagged": f[9] == "1", "title": f[10][:48], "descr": f[11][:160]})
        return ok, rows, err
    return cached("ws:" + state, CACHE_S, get)


def bug_list(state: str) -> tuple[bool, list[dict], str]:
    def get():
        ok, lines, err = soap_lines(f"ovadmin bugs list {state} 100")
        rows = []
        for x in lines:
            f = x.split("\t")
            if f[0] == "ROW" and len(f) >= 9 and f[1].isdigit():
                rows.append({"id": int(f[1]), "status": f[2][:16], "created": int(f[3]) if f[3].isdigit() else 0,
                             "char": f[4][:12], "level": f[5][:3], "map": f[6][:6], "zone": f[7][:8],
                             "text": "\t".join(f[8:])[:500]})
        return ok, rows, err
    return cached("bugs:" + state, CACHE_S, get)


def bug_counts() -> tuple[bool, dict]:
    def get():
        ok, lines, _ = soap_lines("ovadmin bugs count")
        c = {}
        for x in lines:
            f = x.split("\t")
            if f[0] == "COUNT" and len(f) == 3 and f[2].isdigit():
                c[f[1][:16]] = int(f[2])
        return ok, c
    return cached("bugcount", CACHE_S, get)


# ----------------------------------------------------------------------------------------------
# Overrides: the catalog, the Workshop, theme packs (read by workshop.py / creations.py through adjust_catalog)
# ----------------------------------------------------------------------------------------------

SECTIONS = ("mods", "projects", "workshop")
_ov_cache = {"key": None, "doc": {}}


def overrides() -> dict:
    path = _apath("overrides.json")
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and _ov_cache["key"] == key:
        return _ov_cache["doc"]
    doc = _read_json(path, {}) if key else {}
    clean = {s: {k: v for k, v in (doc.get(s) or {}).items() if isinstance(k, str) and isinstance(v, dict)}
             if isinstance(doc.get(s), dict) else {} for s in SECTIONS}
    _ov_cache.update(key=key, doc=clean)
    return clean


def set_override(section: str, ident: str, changes: dict) -> tuple[dict, dict]:
    """Merge changes (None removes a key) into one override; returns (before, after)."""
    with _lock:
        doc = _read_json(_apath("overrides.json"), {})
        if not isinstance(doc.get(section), dict):
            doc[section] = {}
        sec = doc[section]
        before = dict(sec.get(ident) or {})
        after = dict(before)
        for k, v in changes.items():
            if v is None:
                after.pop(k, None)
            else:
                after[k] = v
        if after:
            sec[ident] = after
        else:
            sec.pop(ident, None)
        doc["format"] = 1
        doc["updated_at"] = _iso()
        _write_json(_apath("overrides.json"), doc)
        _ov_cache["key"] = None
    return before, after


def adjust_catalog(section: str, items: list[dict], key: str = "id") -> list[dict]:
    """The items as visitors should see them: unpublished and rejected ones gone, staff edits and "featured" applied.
    workshop.py calls it for "mods" (key "id") and "projects" (key "pid"); creations.py for "workshop" (key "id").
    Never raises: on any problem the items come back as they were."""
    try:
        ov = overrides().get(section) or {}
        hold = themes_review() and section in ("mods", "projects")
        if not ov and not hold:
            return items
        out = []
        for it in items:
            o = ov.get(str(it.get(key))) or {}
            if hold and (o.get("category") or it.get("category")) == THEMES_CAT and o.get("state") != "approved":
                continue
            if not o:
                out.append(it)
                continue
            if o.get("state") in ("rejected", "unpublished"):
                continue
            it = dict(it)
            if o.get("featured"):
                it["featured"] = True
            for f in ("name", "description", "category", "title"):
                if isinstance(o.get(f), str) and o[f] and f in it:
                    it[f] = o[f]
            out.append(it)
        return out
    except Exception:   # noqa: BLE001
        return items


# ----------------------------------------------------------------------------------------------
# Realm overrides (the community realm list honours them: wrath_portal.fetch_listing -> apply_realm_overrides)
# ----------------------------------------------------------------------------------------------

def realm_overrides() -> dict:
    doc = _read_json(_apath("realm-overrides.json"), {})
    r = doc.get("realms") if isinstance(doc.get("realms"), dict) else {}
    return {k: v for k, v in r.items() if REALM_ID_RE.fullmatch(k) and isinstance(v, dict)}


def apply_realm_overrides(realms: list[dict]) -> list[dict]:
    """Hidden realms left out; official (the sample hangout), featured and verified ones marked. Never raises."""
    try:
        ov = realm_overrides()
        if not ov:
            return realms
        out = []
        for r in realms:
            o = ov.get(r.get("id")) or {}
            if o.get("hidden"):
                continue
            for k in ("official", "featured", "verified"):
                if o.get(k):
                    r = dict(r, **{k: True})
            out.append(r)
        return out
    except Exception:   # noqa: BLE001
        return realms


def set_realm_override(rid: str, changes: dict) -> tuple[dict, dict]:
    with _lock:
        doc = _read_json(_apath("realm-overrides.json"), {})
        realms = doc.setdefault("realms", {})
        before = dict(realms.get(rid) or {})
        after = dict(before)
        for k, v in changes.items():
            if v is None or v is False or v == "":
                after.pop(k, None)
            else:
                after[k] = v
        after.pop("by", None)
        after.pop("at", None)
        if after:
            realms[rid] = after
        else:
            realms.pop(rid, None)
        doc.update(format=1, updated_at=_iso())
        _write_json(_apath("realm-overrides.json"), doc)
    return before, after


# ----------------------------------------------------------------------------------------------
# Data sources
# ----------------------------------------------------------------------------------------------

def mods_raw() -> tuple[list[dict], dict]:
    w = P("workshop")
    if w is None:
        return [], {}
    try:
        return w.load(raw=True)
    except TypeError:   # a workshop.py without the admin hook
        return w.load()
    except Exception:   # noqa: BLE001
        return [], {}


def categories() -> list[dict]:
    w = P("workshop")
    try:
        return w.categories()[0] if w is not None else []
    except Exception:   # noqa: BLE001
        return []


def projects_all() -> list[dict]:
    w = P("workshop")
    proj = getattr(w, "projects", None) if w is not None else None
    if proj is None:
        return []
    try:
        return list(proj.load())
    except Exception:   # noqa: BLE001
        return []


def creations_store():
    c = P("creations")
    return getattr(c, "store", None) if c is not None else None


def raw_listing() -> tuple[bool, list[dict], str]:
    """The relay's community records as they are (heartbeats included), cached."""
    def get():
        try:
            raw = P("_read_listing")(P("listing_url")())
            doc = json.loads(raw.decode("utf-8"))
            recs = doc.get("realms") if isinstance(doc, dict) else None
            if not isinstance(recs, list):
                return False, [], "not a listing"
        except Exception as ex:   # noqa: BLE001
            return False, [], str(ex)[:120]
        out = []
        for rec in recs[:500]:
            if not isinstance(rec, dict):
                continue
            com = rec.get("community") if isinstance(rec.get("community"), dict) else {}
            rid = com.get("realmId")
            if not isinstance(rid, str) or not REALM_ID_RE.fullmatch(rid):
                continue
            hb = com.get("lastHeartbeat") if isinstance(com.get("lastHeartbeat"), dict) else {}

            def t(v, n=60):
                return " ".join(v.split())[:n] if isinstance(v, str) else ""

            def num(v):
                return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000 else None
            out.append({"id": rid, "name": t(rec.get("name"), 32) or "Unnamed realm", "state": t(rec.get("state"), 10),
                        "tagline": t(rec.get("tagline"), 80), "relay": t(com.get("relay"), 80),
                        "claimed": bool(com.get("claimed")), "first": t(com.get("firstSeen"), 25),
                        "last": t(com.get("lastSeen"), 25), "online": bool(hb.get("online")),
                        "players": num(hb.get("players")), "bots": num(hb.get("bots")),
                        "hb": {k: v for k, v in list(hb.items())[:12] if isinstance(k, str) and len(k) <= 24
                               and (isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) <= 40))}})
        return True, out, ""
    return cached("listing", CACHE_S, get)


def releases() -> tuple[bool, list[dict], str]:
    """The launcher's GitHub releases (public API, read-only, no token), cached 10 minutes."""
    url = os.environ.get("WU_LEYLINE_RELEASES_API", "https://api.github.com/repos/orionopenwow/Leyline/releases?per_page=30")

    def get():
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "wrath-portal-admin"})
            with urllib.request.urlopen(req, timeout=6) as r:
                doc = json.loads(r.read(3_000_000).decode("utf-8"))
        except Exception as ex:   # noqa: BLE001
            return False, [], str(ex)[:120]
        out = []
        for r in doc if isinstance(doc, list) else []:
            if not isinstance(r, dict) or not isinstance(r.get("tag_name"), str):
                continue
            m = TAG_RE.fullmatch(r["tag_name"])
            page = r.get("html_url") if isinstance(r.get("html_url"), str) and r["html_url"].startswith(SITE_RELEASES + "/") else ""
            assets = r.get("assets") if isinstance(r.get("assets"), list) else []
            out.append({"tag": r["tag_name"][:60], "version": m.group(1) if m else "", "name": str(r.get("name") or "")[:80],
                        "draft": bool(r.get("draft")), "prerelease": bool(r.get("prerelease")),
                        "published": str(r.get("published_at") or "")[:20], "url": page,
                        "assets": [str(a.get("name"))[:80] for a in assets if isinstance(a, dict)][:20],
                        "latest_json": any(isinstance(a, dict) and a.get("name") == "latest.json" for a in assets)})
        return True, out, ""
    return cached("releases", RELEASES_TTL, get)


THEMES_CAT = "themes"   # the Workshop category theme packs use (docs/THEMES.md, the themes agent)


def themes_review() -> bool:
    """WU_THEMES_REVIEW=1: theme packs stay off the site and all.json until staff approve them."""
    return os.environ.get("WU_THEMES_REVIEW", "0") == "1"


def hub_dir() -> str:
    """Where the hub keeps its queue and the console's decisions (stream/hub.py state_dir)."""
    return os.path.join(_portal_data(), "hub")


def hub_index_path() -> str:
    env = os.environ.get("WU_HUB_INDEX")
    if env:
        return env
    d = os.environ.get("WU_HUB_DIR")
    cands = ([os.path.join(d, "community-index.json")] if d else []) + [
        os.path.join(HERE, "hub", "community-index.json"), "/app/hub/community-index.json"]
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[0]


def hub_entries() -> list[dict]:
    """The index (tools/hub-index output). Entry ids are "link:<12 hex>"."""
    doc = _read_json(hub_index_path(), {})
    return [x for x in (doc.get("entries") if isinstance(doc.get("entries"), list) else []) if isinstance(x, dict)
            and isinstance(x.get("id"), str) and HUB_ENTRY_RE.fullmatch(x["id"])][:5000]


def _jsonl(path: str, ok, limit: int = 5000) -> list[dict]:
    out = []
    try:
        with open(path, "rb") as f:
            data = f.read(16_000_000)
    except OSError:
        return out
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and ok(r):
            out.append(r)
    return out[-limit:]


def hub_submissions() -> list[dict]:
    """stream/hub.py's queue: {id (12 hex), repo, build, category, note, at, via}, one per line."""
    return _jsonl(os.path.join(hub_dir(), "submissions.jsonl"), lambda r: isinstance(r.get("id"), str) and PID_RE.fullmatch(r["id"]))


def hub_decisions() -> dict[str, dict]:
    """The latest decision per id (a later line wins), as stream/hub.py Store.decisions reads them."""
    out = {}
    for r in _jsonl(os.path.join(hub_dir(), "decisions.jsonl"), lambda r: isinstance(r.get("id"), str) and PID_RE.fullmatch(r["id"])):
        if r.get("decision") in ("approve", "reject", "delist"):
            out[r["id"]] = r
    return out


def hub_rescans() -> dict:
    doc = _read_json(os.path.join(hub_dir(), "rescan.json"), {})
    return doc.get("requests") if isinstance(doc.get("requests"), dict) else {}


def social_store():
    """stream/social.py's store (Social.reports / resolve_report), or None when the social module is not here."""
    mod = P("social")
    return getattr(mod, "store", None) if mod is not None else None


def forum_store():
    """stream/forum.py's store, or None when the forum is not on this portal."""
    mod = P("forum")
    return getattr(mod, "store", None) if mod is not None else None


def notes() -> dict:
    doc = _read_json(_apath("notes.json"), {})
    return {k: v for k, v in doc.items() if isinstance(v, dict) and ":" in k}


# Feature flags: the host-pack/P2P agent's format (stream/leyline_net.py, docs/P2P-AND-TORRENT.md). When that module is
# in the portal it reads, writes and serves the file; without it this keeps the same format byte for byte.
FLAGS_KNOWN = ("p2p_hosting", "torrent_downloads", "torrent_seeding", "webrtc_presence")
FLAG_LIMITS = {"seed_upload_kbps": 100_000, "seed_ratio_pct": 1000, "max_peers": 200}
FLAG_STUN = ["stun.cloudflare.com:3478"]


def _ln():
    return P("leyline_net")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _flags_make(flags: dict, limits: dict, stun: list, updated_at: str) -> dict:
    doc = {"format": 1, "updated_at": updated_at, "flags": {k: flags.get(k) is True for k in FLAGS_KNOWN},
           "limits": {k: max(0, min(int(limits.get(k) or 0), cap)) for k, cap in FLAG_LIMITS.items()},
           "stun": [x for x in stun if isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9.-]{1,253}:[0-9]{1,5}", x)][:4]}
    doc["sha256"] = hashlib.sha256(_canonical(doc).encode("utf-8")).hexdigest()
    return doc


def flags_doc() -> dict:
    """{format, updated_at, flags: {name: bool}, limits, stun, sha256}: the served file, or all off."""
    ln = _ln()
    if ln is not None:
        try:
            return ln.load()
        except Exception:   # noqa: BLE001
            pass
    doc = _read_json(_lpath("flags.json"), {})
    if (doc.get("format") == 1 and isinstance(doc.get("flags"), dict)
            and doc.get("sha256") == hashlib.sha256(_canonical({k: v for k, v in doc.items() if k != "sha256"}).encode()).hexdigest()):
        return doc
    return _flags_make({}, {}, FLAG_STUN, "2026-10-29T00:00:00Z")


def flags_known() -> tuple[str, ...]:
    ln = _ln()
    return tuple(getattr(ln, "KNOWN", FLAGS_KNOWN)) if ln is not None else FLAGS_KNOWN


def write_flag(name: str, on: bool, by: str) -> dict:
    ln = _ln()
    if ln is not None:
        return ln.write_flags(ln.path(), {name: on}, by=by)
    with _lock:
        cur = flags_doc()
        doc = _flags_make(dict(cur["flags"], **{name: on}), cur.get("limits") or {}, cur.get("stun") or FLAG_STUN, _iso())
        _write_json(_lpath("flags.json"), doc)
    return doc


def channel_doc() -> dict:
    doc = _read_json(_lpath("channel.json"), {})

    def ch(v):
        return v if isinstance(v, dict) and isinstance(v.get("version"), str) and VERSION_RE.fullmatch(v["version"]) else None
    return {"format": 1, "updated_at": doc.get("updated_at") if isinstance(doc.get("updated_at"), str) else None,
            "stable": ch(doc.get("stable")), "beta": ch(doc.get("beta")), "hold": doc.get("hold") is True,
            "hold_note": str(doc.get("hold_note") or "")[:200]}


def news_doc() -> dict:
    doc = _read_json(_lpath("news.json"), {})
    posts = [p for p in (doc.get("posts") if isinstance(doc.get("posts"), list) else []) if isinstance(p, dict)
             and isinstance(p.get("id"), str)]
    return {"format": 1, "updated_at": doc.get("updated_at"), "posts": posts[:200]}


def launcher_versions() -> dict | None:
    path = os.environ.get("WU_LAUNCHER_VERSIONS") or _apath("launcher-versions.json")
    doc = _read_json(path, {})
    v = doc.get("versions")
    if not isinstance(v, dict):
        return None
    return {str(k)[:32]: n for k, n in v.items() if isinstance(n, int) and VERSION_RE.fullmatch(str(k))}


# ----------------------------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------------------------

NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}

ADMIN_CSS = """
.ad-top{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:0 0 6px}
.ad-top a{padding:6px 11px;border:1px solid var(--ly-line);border-radius:999px;text-decoration:none;font-size:14px;color:var(--ly-ink)}
.ad-top a.on{border-color:var(--ly-cyan);box-shadow:var(--ly-glow);color:#bff6ff}
.ad-who{color:var(--ly-dim);font-size:13px;text-align:center;margin:0 0 4px}
.ly h1.ad{font-size:clamp(34px,6vw,54px)}
.ad-msg{border:1px solid var(--ly-cyan);border-radius:6px;padding:10px 14px;margin:12px 0;background:rgba(20,60,80,.5)}
.ad-msg.err{border-color:#ff7a90;background:rgba(80,20,40,.5)}
.ad-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.ad-stat{background:rgba(18,22,54,.7);border:1px solid var(--ly-line);border-radius:6px;padding:12px}
.ad-stat b{display:block;font:600 26px/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;color:var(--ly-cyan)}
.ad-stat span{color:var(--ly-dim);font-size:13px}
.ad form{display:inline-flex;flex-wrap:wrap;gap:6px;align-items:center;margin:2px 4px 2px 0}
.ad form.blk{display:flex;flex-direction:column;align-items:stretch;max-width:560px}
.ad input[type=text],.ad textarea,.ad select{background:rgba(5,8,25,.85);color:var(--ly-ink);border:1px solid var(--ly-line);
border-radius:4px;padding:5px 8px;font:inherit;font-size:14px;max-width:100%}
.ad textarea{min-height:90px}
.ad button{background:linear-gradient(180deg,rgba(40,52,110,.92),rgba(16,20,52,.95));color:var(--ly-ink);border:1px solid rgba(140,170,255,.45);
border-radius:4px;padding:5px 11px;font:inherit;font-size:13px;cursor:pointer}
.ad button.danger{border-color:#ff7a90;color:#ffd0d8}
.ad button:disabled{opacity:.45;cursor:not-allowed}
.ad .tag{display:inline-block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--ly-line);
border-radius:999px;padding:1px 7px;margin:0 4px 0 0;color:var(--ly-dim)}
.ad .tag.hot{color:#ffd27a;border-color:#ffd27a}.ad .tag.bad{color:#ff9aab;border-color:#ff9aab}.ad .tag.good{color:#5ef0a0;border-color:#5ef0a0}
.ad .fine{color:var(--ly-dim);font-size:13px}
.ad .ly-table td{vertical-align:top}
.ad details{margin-top:4px}.ad summary{cursor:pointer;color:var(--ly-cyan);font-size:13px}
.ad code{font-size:13px;color:#d6c8ff}
.ad .body{white-space:pre-wrap;word-break:break-word;background:rgba(5,8,25,.6);border-left:2px solid var(--ly-violet);padding:6px 9px;margin:4px 0}
"""

# The typed confirm: the button stays off until the box holds the expected text. The server checks it again.
CONFIRM_JS = """
document.querySelectorAll('form[data-confirm]').forEach(function(f){
  var box=f.querySelector('input[name=confirm]'),btn=f.querySelector('button');
  if(!box||!btn)return;
  var want=f.getAttribute('data-confirm');
  function upd(){btn.disabled=box.value.trim()!==want}
  box.addEventListener('input',upd);upd();
});
"""

TABS = (("", "Dashboard"), ("catalog", "Catalog"), ("workshop", "Workshop"), ("hub", "Index"), ("realms", "Realms"),
        ("releases", "Releases"), ("flags", "Flags"), ("themes", "Themes"), ("reports", "Reports"),
        ("forum", "Forum"), ("health", "Health"), ("staff", "Staff"), ("audit", "Audit"))


def _css() -> str:
    fn = P("leyline_css")
    return (fn() if callable(fn) else "") + ADMIN_CSS


def page_simple(title: str, text: str) -> bytes:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="dark"><title>{e(title)} · Leyline Admin</title>'
            f'<style>{_css()}</style></head><body class="ly"><div class="ly-glow"></div><div class="ly-wrap ad">'
            f'<section class="ly-panel"><h2>{e(title)}</h2><p>{e(text)}</p><p><a href="/wrath/leyline">Leyline</a></p></section>'
            f'</div></body></html>').encode("utf-8")


def denied_page(account: str) -> bytes:
    acct = (f' Your account id is <code>{e(account)}</code>: the owner can add it on the Staff page.' if account else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="dark"><title>Staff only · Leyline Admin</title>'
            f'<style>{_css()}</style></head><body class="ly"><div class="ly-glow"></div><div class="ly-wrap ad">'
            f'<section class="ly-panel"><h2>Staff only</h2><p>This part of the site is for the Leyline staff.{acct}</p>'
            f'<p><a href="/wrath/leyline">Back to Leyline</a></p></section></div></body></html>').encode("utf-8")


def flash_sig(kind: str, text: str) -> str:
    """The after-action message rides in the URL; only messages this console made are shown (no crafted links)."""
    return hmac.new(_secret(), f"flash|{kind}|{text}".encode(), hashlib.sha256).hexdigest()[:16]


def shell(user: dict, tab: str, title: str, body: str, nonce: str, query: dict | None = None) -> bytes:
    nav = "".join(f'<a href="/wrath/admin{"/" + k if k else ""}"{" class=on" if k == tab else ""}>{e(v)}</a>'
                  for k, v in TABS)
    q = query or {}
    msg = ""
    sig = (q.get("m") or [""])[0]
    if q.get("ok") and hmac.compare_digest(sig, flash_sig("ok", q["ok"][0])):
        msg = f'<p class="ad-msg" role="status">{e(q["ok"][0][:300])}</p>'
    elif q.get("err") and hmac.compare_digest(sig, flash_sig("err", q["err"][0])):
        msg = f'<p class="ad-msg err" role="alert">{e(q["err"][0][:300])}</p>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="dark">'
            f'<title>{e(title)} · Leyline Admin</title><style>{_css()}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div><div class="ly-wrap ad">'
            f'<header class="ly-hero"><h1 class="ad">Leyline Admin</h1></header>'
            f'<p class="ad-who">Signed in as {e(user["name"])} ({e(user["role"])})</p>'
            f'<nav class="ad-top" aria-label="Admin">{nav}</nav>{msg}<main id="main">{body}</main></div>'
            f'<script nonce="{nonce}">{CONFIRM_JS}</script></body></html>').encode("utf-8")


def act(user: dict, action: str, target: str, label: str, back: str, fields: str = "", confirm: str | None = None,
        danger: bool = False, block: bool = False) -> str:
    """One action form. confirm: the text the staff member must type (the target, usually)."""
    tok = csrf_token(user["session"], user["account"])
    c_attr = f' data-confirm="{e(confirm)}"' if confirm else ""
    c_box = (f'<input type="text" name="confirm" autocomplete="off" placeholder="type {e(confirm)}" '
             f'aria-label="Type {e(confirm)} to confirm" size="{min(24, max(8, len(confirm) + 2))}">' if confirm else "")
    return (f'<form method="post" action="/wrath/admin/act"{c_attr}{" class=blk" if block else ""}>'
            f'<input type="hidden" name="csrf" value="{tok}"><input type="hidden" name="action" value="{e(action)}">'
            f'<input type="hidden" name="target" value="{e(target)}"><input type="hidden" name="back" value="{e(back)}">'
            f'{fields}{c_box}<button type="submit"{" class=danger" if danger else ""}>{e(label)}</button></form>')


def _tags(*pairs) -> str:
    return "".join(f'<span class="tag {cls}">{e(t)}</span>' for t, cls in pairs if t)


def _takedown(forms: str) -> str:
    """Destructive forms folded away, each with its typed confirm."""
    return f'<details><summary>Reject or unpublish</summary>{forms}</details>' if forms else ""


def _cat_select(name: str, current: str) -> str:
    opts = "".join(f'<option value="{e(c["id"])}"{" selected" if c["id"] == current else ""}>{e(c["name"])}</option>'
                   for c in categories())
    return f'<select name="{name}" aria-label="Category"><option value="">(as published)</option>{opts}</select>'


def _when(t) -> str:
    if isinstance(t, (int, float)) and t > 0:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))
    return e(str(t or ""))[:20]


# ---------------------------------------------------------------------------------------- dashboard

def gamedata_status() -> dict:
    """The game data killswitch's state (the portal's gamedata_state(); stream/server/gamedata-switch.sh flips it).
    Read-only here: the switch is the owner's bat / Autopilot step, never a button on this console."""
    fn = P("gamedata_state")
    if fn:
        try:
            got = fn()
            if isinstance(got, dict) and "gamedata_streaming" in got:
                return got
        except Exception:   # noqa: BLE001
            pass
    off = os.path.exists(os.environ.get("WU_GAMEDATA_FLAG", "/app/gamedata-off"))
    return {"gamedata_streaming": not off, "gamedata_since": None}


def gamedata_line() -> str:
    """'Game data streaming: on/off since ...', for the Dashboard and Health."""
    g = gamedata_status()
    on = bool(g.get("gamedata_streaming"))
    since = g.get("gamedata_since")
    when = f" since {e(_when_iso(since))}" if since else ""
    if on:
        return (f'<p class="ad-gamedata">Game data streaming: <b>on</b>{when}. '
                '<span class="fine">The slim streamed sampler is served from this server. Off: the owner\'s '
                '"Game data killswitch ON.bat" (or the Autopilot step gamedata-off).</span></p>')
    return (f'<p class="ad-gamedata">Game data streaming: <b>off</b>{when}. '
            '<span class="fine">This server serves no game data: players use their own 3.3.5a game folder. On again: the '
            'owner\'s "Game data killswitch OFF.bat" (or the Autopilot step gamedata-on).</span></p>')


def _when_iso(v) -> str:
    """'2026-10-29 18:04 UTC' for an ISO time; the text itself otherwise."""
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d)T(\d\d:\d\d):\d\dZ", str(v))
    return f"{m.group(1)} {m.group(2)} UTC" if m else str(v)


def dashboard(user: dict) -> str:
    st = {}
    try:
        st = json.loads(P("status_json")().decode("utf-8"))
    except Exception:   # noqa: BLE001
        st = {}
    try:
        realms, listing_ok = P("community_realms")()
    except Exception:   # noqa: BLE001
        realms, listing_ok = [], False
    mods, _ = mods_raw()
    ov = overrides()
    projs = projects_all()
    store = creations_store()
    try:
        if store is not None:
            store.refresh()
        ws_live = len(store.items) if store is not None else None
    except Exception:   # noqa: BLE001
        ws_live = None
    ws_ok, ws_pending, _ = ws_list("pending")
    bc_ok, bc = bug_counts()
    links_reported = sum(1 for p in projs if not p.get("hidden") and p.get("reports"))
    soc_n = None
    if social_store() is not None:
        try:
            soc_n = len(social_store().reports("open", 1000))
        except Exception:   # noqa: BLE001
            soc_n = None
    fm_n = None
    if forum_store() is not None:
        try:
            fm_n = len(forum_store().reports("open", 1000))
        except Exception:   # noqa: BLE001
            fm_n = None
    themes = theme_items()
    th_pending = sum(1 for t in themes if t["state"] != "approved") if themes_review() else 0
    dec = hub_decisions()
    hub_pending = len({s["id"] for s in hub_submissions() if s["id"] not in dec})
    lv = launcher_versions()

    def stat(n, label):
        return f'<div class="ad-stat"><b>{e(str(n)) if n is not None else "?"}</b><span>{e(label)}</span></div>'
    realm = (stat("online" if st.get("online") else "down", "Realm") + stat(st.get("players"), "Players online")
             + stat(st.get("bots"), "Bots") + stat(st.get("queue") if st.get("queue") is not None else 0, "Login queue")
             + stat(len(realms) if listing_ok else "down", "Community realms (relay)"))
    catalog = (stat(len(mods), "Packaged mods") + stat(sum(1 for o in ov["mods"].values() if o.get("state") in ("rejected", "unpublished")), "Mods taken down")
               + stat(len(projs), "Community links") + stat(sum(1 for p in projs if p.get("hidden")), "Links hidden")
               + stat(ws_live, "Workshop items live") + stat(len(hub_entries()), "Index entries") + stat(len(themes), "Theme packs"))
    reports = (stat((bc.get("new", 0) + bc.get("seen", 0)) if bc_ok else None, "Open .bug reports")
               + stat(soc_n, "Open message reports") + stat(fm_n, "Open forum reports") + stat(links_reported, "Reported links")
               + stat(len(P("network").reports("open")) if P("network") is not None else None, "Open realm reports"))
    queues = (stat(len(ws_pending) if ws_ok else None, "Workshop waiting") + stat(hub_pending, "Index submissions")
              + stat(th_pending, "Theme packs waiting"))
    if lv:
        lv_html = ('<table class="ly-table"><thead><tr><th>Version</th><th>Update checks</th></tr></thead><tbody>'
                   + "".join(f'<tr><td>{e(k)}</td><td>{n}</td></tr>' for k, n in sorted(lv.items(), key=lambda x: -x[1])[:20])
                   + '</tbody></table>')
    else:
        lv_html = ('<p class="fine">Not collected. The launcher asks GitHub for updates directly, so no server of ours sees '
                   'which versions are out there, and there is no telemetry. If an update endpoint ever logs the anonymous '
                   'version string, point WU_LAUNCHER_VERSIONS at its {"versions": {"x.y.z": n}} summary.</p>')
    return (f'<section class="ly-panel"><h2>Realm and relay</h2><div class="ad-stats">{realm}</div>{gamedata_line()}</section>'
            f'<section class="ly-panel"><h2>Queues</h2><div class="ad-stats">{queues}</div>'
            f'<p class="fine"><a href="/wrath/admin/workshop">Workshop</a> · <a href="/wrath/admin/hub">Index</a> · '
            f'<a href="/wrath/admin/themes">Themes</a></p></section>'
            f'<section class="ly-panel"><h2>Reports</h2><div class="ad-stats">{reports}</div>'
            f'<p class="fine"><a href="/wrath/admin/reports">Open the reports</a> · <a href="/wrath/admin/forum">The forum</a></p></section>'
            f'<section class="ly-panel"><h2>Catalog</h2><div class="ad-stats">{catalog}</div></section>'
            f'<section class="ly-panel"><h2>Launchers in the wild</h2>{lv_html}</section>')


# ------------------------------------------------------------------------------------------ catalog

def _checks(kind: str, ident: str) -> dict:
    return _read_json(_apath(os.path.join("checks", f"{kind}-{ident}.json")), {})


def catalog_page(user: dict) -> str:
    back = "/wrath/admin/catalog"
    mods, installed = mods_raw()
    ov = overrides()
    rows = []
    for m in mods:
        o = ov["mods"].get(m["id"]) or {}
        state = o.get("state", "approved")
        chk = _checks("mod", m["id"])
        chk_tag = (("checker: %d errors" % chk.get("errors", 0), "bad") if chk.get("errors") else
                   ("checker ok", "good") if chk else ("", ""))
        edit = act(user, "mod.edit", m["id"], "Save", back,
                   f'<input type="text" name="name" maxlength="60" value="{e(o.get("name", ""))}" placeholder="{e(m["name"])}" aria-label="Name">'
                   f'<input type="text" name="description" maxlength="200" value="{e(o.get("description", ""))}" placeholder="description (as published)" aria-label="Description">'
                   + _cat_select("category", o.get("category", "")))
        down = (act(user, "mod.reject", m["id"], "Reject", back, confirm=m["id"], danger=True)
                + act(user, "mod.unpublish", m["id"], "Unpublish", back, confirm=m["id"], danger=True)) if state == "approved" else ""
        acts = (act(user, "mod.approve", m["id"], "Approve", back) if state != "approved" else "") \
            + act(user, "mod.feature", m["id"], "Unfeature" if o.get("featured") else "Feature", back,
                  f'<input type="hidden" name="on" value="{"0" if o.get("featured") else "1"}">') \
            + act(user, "mod.check", m["id"], "Re-run checker", back)
        rows.append(f'<tr><td class="name"><b>{e(o.get("name") or m["name"])}</b><span class="sub"><code>{e(m["id"])}</code> '
                    f'v{e(m["version"])} · {e(m["kind"])} · {e(o.get("category") or m.get("category") or "")}</span>'
                    f'{_tags((state, "good" if state == "approved" else "bad"), ("featured", "hot") if o.get("featured") else ("", ""), chk_tag, ("on the realm", "") if installed.get(m["id"]) == m["version"] else ("", ""))}'
                    f'<span class="sub"><a href="/wrath/admin/catalog/mod/{e(m["id"])}">checker findings</a></span></td>'
                    f'<td>{acts}<details><summary>Edit name, description, category</summary>{edit}</details>'
                    f'{_takedown(down)}</td></tr>')
    mods_html = ('<table class="ly-table"><thead><tr><th>Mod</th><th>Actions</th></tr></thead><tbody>' + "".join(rows)
                 + '</tbody></table>') if rows else '<p class="fine">No packaged mods in the catalog.</p>'
    prow = []
    for p in sorted(projects_all(), key=lambda p: (-len(p.get("reports") or []), str(p.get("title", "")).lower())):
        pid = p.get("id", "")
        if not isinstance(pid, str) or not PID_RE.fullmatch(pid):
            continue
        o = ov["projects"].get(pid) or {}
        nrep = len(p.get("reports") or []) if isinstance(p.get("reports"), list) else 0
        acts = (act(user, "link.unhide", pid, "Unhide", back) if p.get("hidden")
                else act(user, "link.hide", pid, "Hide", back, confirm=pid, danger=True)) \
            + act(user, "link.feature", pid, "Unfeature" if o.get("featured") else "Feature", back,
                  f'<input type="hidden" name="on" value="{"0" if o.get("featured") else "1"}">') \
            + (act(user, "link.dismiss", pid, "Dismiss reports", back) if nrep and not p.get("hidden") else "")
        edit = act(user, "link.edit", pid, "Save", back,
                   f'<input type="text" name="name" maxlength="80" value="{e(o.get("name", ""))}" placeholder="{e(str(p.get("title", "")))}" aria-label="Title">'
                   f'<input type="text" name="description" maxlength="160" value="{e(o.get("description", ""))}" placeholder="description (as submitted)" aria-label="Description">'
                   + _cat_select("category", o.get("category", "")))
        url = p.get("url") if isinstance(p.get("url"), str) and p["url"].startswith("https://") else ""
        prow.append(f'<tr><td class="name"><b>{e(o.get("name") or str(p.get("title") or p.get("host") or pid))}</b>'
                    f'<span class="sub"><code>{e(pid)}</code> · {e(str(p.get("category") or ""))} · by {e(str(p.get("submitted_by") or ""))}'
                    f'{" · " + "<a href=" + chr(34) + e(url) + chr(34) + " rel=" + chr(34) + "noopener noreferrer nofollow" + chr(34) + ">link</a>" if url else ""}</span>'
                    f'{_tags(("hidden", "bad") if p.get("hidden") else ("listed", "good"), (f"{nrep} reports", "hot") if nrep else ("", ""), ("featured", "hot") if o.get("featured") else ("", ""))}</td>'
                    f'<td>{acts}<details><summary>Edit</summary>{edit}</details></td></tr>')
    links_html = ('<table class="ly-table"><thead><tr><th>Link</th><th>Actions</th></tr></thead><tbody>' + "".join(prow)
                  + '</tbody></table>') if prow else '<p class="fine">No community links yet.</p>'
    return (f'<section class="ly-panel"><h2>Packaged mods</h2><p class="fine">Mods come from mods/catalog through the '
            f'"mods" step, already checked there. Rejecting or unpublishing takes one off the site and out of all.json for the '
            f'launcher; the files stay. Feature, name, description and category change what players see.</p>{mods_html}</section>'
            f'<section class="ly-panel"><h2>Community links</h2><p class="fine">Links people added on /wrath/mods/submit. '
            f'Hidden links stay in the file.</p>{links_html}</section>')


def mod_page(user: dict, mod_id: str) -> tuple[int, str]:
    mods, _ = mods_raw()
    m = next((x for x in mods if x["id"] == mod_id), None)
    if m is None:
        return 404, '<section class="ly-panel"><h2>Not found</h2><p>No such mod.</p></section>'
    chk = _checks("mod", mod_id)
    if chk:
        items = "".join(f'<tr><td>{e(i.get("level", ""))}</td><td><code>{e(i.get("code", ""))}</code></td>'
                        f'<td>{e(i.get("where", ""))}</td><td>{e(i.get("msg", ""))}</td></tr>' for i in chk.get("items", [])[:300])
        found = (f'<p>Last run {e(chk.get("at", ""))} by {e(chk.get("by", ""))}: {chk.get("errors", 0)} errors, '
                 f'{chk.get("warnings", 0)} warnings{" (" + e(chk.get("note", "")) + ")" if chk.get("note") else ""}.</p>'
                 + ('<table class="ly-table"><thead><tr><th>Level</th><th>Code</th><th>Where</th><th>What</th></tr></thead>'
                    f'<tbody>{items}</tbody></table>' if items else '<p class="fine">Nothing to report.</p>'))
    else:
        found = '<p class="fine">The checker has not been run from here yet.</p>'
    return 200, (f'<section class="ly-panel"><h2>{e(m["name"])}</h2><p><code>{e(m["id"])}</code> v{e(m["version"])}, '
                 f'zip <code>{e(m.get("zip") or "-")}</code></p>'
                 f'{act(user, "mod.check", m["id"], "Re-run checker", "/wrath/admin/catalog/mod/" + m["id"])}{found}'
                 f'<p><a href="/wrath/admin/catalog">Back to the catalog</a></p></section>')


def _wu_mod():
    cands = [os.environ.get("WU_MOD_TOOL", ""), os.path.join(HERE, "..", "mods", "wu-mod.py"),
             os.path.join(HERE, "wu-mod.py"), "/app/mods/wu-mod.py"]
    for p in cands:
        if p and os.path.isfile(p):
            try:
                spec = importlib.util.spec_from_file_location("wu_mod_tool", p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "check_package"):
                    return mod
            except Exception:   # noqa: BLE001
                continue
    return None


def run_mod_check(m: dict, by: str) -> dict:
    w = P("workshop")
    doc = {"at": _iso(), "by": by, "errors": 0, "warnings": 0, "items": [], "note": ""}
    tool = _wu_mod()
    zpath = os.path.join(getattr(w, "dir", "/app/mods"), "files", m.get("zip") or "")
    if tool is None:
        doc.update(errors=1, note="the checker (mods/wu-mod.py) is not on this server",
                   items=[{"level": "ERROR", "code": "tool", "where": "", "msg": "wu-mod.py not found (set WU_MOD_TOOL)"}])
    elif not m.get("zip") or not os.path.isfile(zpath):
        doc.update(errors=1, note="no zip", items=[{"level": "ERROR", "code": "zip", "where": "", "msg": "the mod's zip is not on the server"}])
    else:
        try:
            rep = tool.check_package(zpath)
            items = [{"level": str(i[0]), "code": str(i[1]), "where": str(i[2] or "")[:200], "msg": str(i[3])[:400]}
                     for i in rep.items]
            doc.update(items=items[:500], errors=sum(1 for i in items if i["level"] == "ERROR"),
                       warnings=sum(1 for i in items if i["level"] != "ERROR"))
        except Exception as ex:   # noqa: BLE001
            doc.update(errors=1, note="the checker failed", items=[{"level": "ERROR", "code": "crash", "where": "", "msg": str(ex)[:300]}])
    with _lock:
        _write_json(_apath(os.path.join("checks", f"mod-{m['id']}.json")), doc)
    return doc


# ------------------------------------------------------------------------------- the player Workshop

def workshop_page(user: dict, query: dict) -> str:
    state = (query.get("state") or ["pending"])[0]
    if state not in ("pending", "approved", "rejected", "all"):
        state = "pending"
    back = "/wrath/admin/workshop?state=" + state
    ok, rows, err = ws_list(state)
    ov = overrides()["workshop"]
    tabs = " · ".join(f'<a href="/wrath/admin/workshop?state={s}">{"<b>" + s + "</b>" if s == state else s}</a>'
                      for s in ("pending", "approved", "rejected", "all"))
    if not ok:
        return (f'<section class="ly-panel"><h2>Workshop</h2><p>{tabs}</p><p class="ad-msg err">{e(err)}</p></section>')
    out = []
    for r in rows:
        sid = str(r["id"])
        o = ov.get(sid) or {}
        chk = _checks("ws", sid)
        down = ((act(user, "ws.reject", sid, "Reject", back, confirm=sid, danger=True) if r["state"] != "rejected" else "")
                + (act(user, "ws.unpublish", sid, "Unpublish", back, confirm=sid, danger=True) if r["state"] == "approved" else ""))
        acts = ((act(user, "ws.approve", sid, "Approve", back) if r["state"] != "approved" else "")
                + act(user, "ws.feature", sid, "Unfeature" if o.get("featured") else "Feature", back,
                      f'<input type="hidden" name="on" value="{"0" if o.get("featured") else "1"}">')
                + act(user, "ws.check", sid, "Re-run checks", back))
        edit = (act(user, "ws.edit", sid, "Save title", back, f'<input type="hidden" name="field" value="title">'
                    f'<input type="text" name="text" maxlength="40" value="{e(r["title"])}" aria-label="Title">')
                + act(user, "ws.edit", sid, "Save description", back, f'<input type="hidden" name="field" value="descr">'
                      f'<input type="text" name="text" maxlength="140" value="{e(r["descr"])}" aria-label="Description">'))
        findings = ""
        if chk:
            findings = ('<span class="sub">Checks (' + e(chk.get("at", "")) + '): '
                        + (e("; ".join(chk.get("items", []))) if chk.get("items") else "nothing found") + '</span>')
        out.append(f'<tr><td class="name"><b>#{r["id"]} {e(r["title"])}</b><span class="sub">{e(r["kind"])} v{e(r["version"])} by '
                   f'{e(r["author"])} · {e(r["plays"])} plays · +{e(r["up"])} -{e(r["down"])}</span>'
                   f'{"<span class=sub>" + e(r["descr"]) + "</span>" if r["descr"] else ""}'
                   f'{_tags((r["state"], "good" if r["state"] == "approved" else "hot" if r["state"] == "pending" else "bad"), ("filtered word", "bad") if r["flagged"] else ("", ""), ("featured", "hot") if o.get("featured") else ("", ""))}'
                   f'{findings}</td><td>{acts}<details><summary>Edit</summary>{edit}</details>{_takedown(down)}</td></tr>')
    table = ('<table class="ly-table"><thead><tr><th>Item</th><th>Actions</th></tr></thead><tbody>' + "".join(out)
             + '</tbody></table>') if out else '<p class="fine">Nothing here.</p>'
    return (f'<section class="ly-panel"><h2>Workshop</h2><p>{tabs}</p><p class="fine">What players made: courses, modes and '
            f'builds (characters.mod_workshop_items, through ov_admin.lua). Unpublish puts an item back to waiting; reject '
            f'keeps it off. Nothing is deleted: plays and votes stay. The website list follows within 5 minutes '
            f'(workshop-export.py).</p>{table}</section>')


# ------------------------------------------------------------------------------------- the index (hub)

def hub_page(user: dict) -> str:
    back = "/wrath/admin/hub"
    dec = hub_decisions()
    resc = hub_rescans()
    srow, seen = [], set()
    for s in reversed(hub_submissions()):
        sid = s["id"]
        if sid in seen:
            continue
        seen.add(sid)
        d = dec.get(sid)
        repo = s.get("repo") if isinstance(s.get("repo"), str) and s["repo"].startswith("https://") else ""
        if d:
            acts = _tags((d.get("decision", ""), "good" if d.get("decision") == "approve" else "bad")) + \
                f'<span class="sub">{e(str(d.get("reason", "")))} ({e(str(d.get("by", "")))}, {e(str(d.get("at", "")))})</span>'
        else:
            acts = (act(user, "hub.approve", sid, "Approve", back,
                        '<input type="text" name="reason" maxlength="200" placeholder="note (optional)" aria-label="Note">')
                    + act(user, "hub.reject", sid, "Reject", back,
                          '<input type="text" name="reason" maxlength="200" placeholder="reason (required)" aria-label="Reason" required>',
                          danger=True))
        srow.append(f'<tr><td class="name"><b>{e(repo or sid)}</b><span class="sub"><code>{e(sid)}</code> · '
                    f'{e(str(s.get("build") or ""))} · {e(str(s.get("category") or ""))} · {e(str(s.get("at") or ""))}'
                    f'{" · <a href=" + chr(34) + e(repo) + chr(34) + " rel=" + chr(34) + "noopener noreferrer nofollow" + chr(34) + ">repo</a>" if repo else ""}</span>'
                    f'<span class="sub">{e(str(s.get("note") or "")[:280])}</span></td><td>{acts}</td></tr>')
    subs_html = ('<table class="ly-table"><thead><tr><th>Submission</th><th>Decision</th></tr></thead><tbody>' + "".join(srow)
                 + '</tbody></table>') if srow else '<p class="fine">No submissions yet.</p>'
    erow = []
    for x in hub_entries():
        hid = x["id"].split(":", 1)[1]
        delisted = (dec.get(hid) or {}).get("decision") == "delist"
        acts = (act(user, "hub.relist", hid, "List again", back) if delisted else
                act(user, "hub.delist", hid, "Delist", back,
                    '<input type="text" name="reason" maxlength="200" placeholder="reason" aria-label="Reason" required>',
                    confirm=hid, danger=True)) \
            + act(user, "hub.rescan", hid, "Re-scan", back)
        erow.append(f'<tr><td class="name"><b>{e(str(x.get("name", "")))}</b><span class="sub"><code>{e(hid)}</code> · '
                    f'{e(str(x.get("category", "")))} · {e(str(x.get("licence", "")))} · updated {e(str(x.get("updated", "")))}</span>'
                    f'{_tags(("delisted", "bad") if delisted else ("", ""), ("re-scan asked", "hot") if hid in resc else ("", ""))}</td>'
                    f'<td>{acts}</td></tr>')
    ent_html = ('<table class="ly-table"><thead><tr><th>Entry</th><th>Actions</th></tr></thead><tbody>' + "".join(erow)
                + '</tbody></table>') if erow else f'<p class="fine">No index file at {e(hub_index_path())}.</p>'
    return (f'<section class="ly-panel"><h2>Submissions</h2><p class="fine">Decisions are appended to hub/decisions.jsonl '
            f'(stream/hub.py reads them, and its approved.json feeds the index build in tools/hub-index). Nothing here edits '
            f'the index itself.</p>{subs_html}</section><section class="ly-panel"><h2>Index entries</h2>'
            f'{act(user, "hub.rescan", "all", "Re-scan everything", back)}{ent_html}</section>')


# ----------------------------------------------------------------------------------------------- realms

def realms_page(user: dict) -> str:
    back = "/wrath/admin/realms"
    ok, recs, err = raw_listing()
    ov = realm_overrides()
    seen = set()
    rows = []
    for r in recs:
        seen.add(r["id"])
        o = ov.get(r["id"]) or {}
        rows.append(_realm_row(user, r, o, back))
    for rid, o in ov.items():   # overridden realms the relay no longer lists
        if rid not in seen:
            rows.append(_realm_row(user, {"id": rid, "name": "(not on the relay's list now)", "state": "", "tagline": "",
                                          "relay": "", "claimed": False, "first": "", "last": "", "online": False,
                                          "players": None, "bots": None, "hb": {}}, o, back))
    table = ('<table class="ly-table"><thead><tr><th>Realm</th><th>Heartbeat</th><th>Actions</th></tr></thead><tbody>'
             + "".join(rows) + '</tbody></table>') if rows else '<p class="fine">No community realms listed right now.</p>'
    warn = '' if ok else f'<p class="ad-msg err">The relay\'s listing did not answer: {e(err)}</p>'
    return (f'<section class="ly-panel"><h2>Community realms</h2><p class="fine">From the Beacons relay\'s listing. Hide '
            f'takes a realm off /wrath/realms, the share links and /wrath/leyline/realm-overrides.json (which the launcher '
            f'can honour); it does not stop the realm. To refuse a realm at the relay itself, add its id to the relay\'s '
            f'RELAY_BLOCK_FILE. Flags are a staff note only. Featured realms go above the sample hangout on every '
            f'realm list; Verified is a badge (a host staff know). Player reports show under each realm. A realm whose '
            f'heartbeats stop shows offline at once and leaves the list after 6 h by itself.</p>{warn}{table}</section>')


def _realm_reports_html(user: dict, rid: str, back: str) -> str:
    net = P("network")
    reps = net.reports("open", rid) if net is not None else []
    if not reps:
        return ""
    lines = "".join(f'<li>{e(net.REPORT_REASON.get(x.get("reason"), "?"))}{": " + e(x["note"]) if x.get("note") else ""}'
                    f' <span class="sub">{e(x.get("at", ""))} · {e(x.get("by_name") or x.get("by", ""))}</span></li>'
                    for x in reps[:8])
    return (f'<details><summary>{len(reps)} open report{"s" if len(reps) != 1 else ""}</summary><ul>{lines}</ul>'
            + act(user, "realm.reports", rid, "Resolve reports", back, '<input type="hidden" name="how" value="resolved">')
            + act(user, "realm.reports", rid, "Dismiss reports", back, '<input type="hidden" name="how" value="dismissed">')
            + '</details>')


def _realm_row(user: dict, r: dict, o: dict, back: str) -> str:
    rid = r["id"]
    hb = ", ".join(f"{k}: {v}" for k, v in r.get("hb", {}).items())
    net = P("network")
    nrep = (net.open_counts().get(rid, 0) if net is not None else 0)
    acts = ((act(user, "realm.unhide", rid, "Unhide", back) if o.get("hidden") else
             act(user, "realm.hide", rid, "Hide", back, confirm=rid, danger=True))
            + (act(user, "realm.unofficial", rid, "Not official", back) if o.get("official") else
               act(user, "realm.official", rid, "Mark official", back, confirm=rid))
            + (act(user, "realm.unfeature", rid, "Not featured", back) if o.get("featured") else
               act(user, "realm.feature", rid, "Feature", back))
            + (act(user, "realm.unverify", rid, "Not verified", back) if o.get("verified") else
               act(user, "realm.verify", rid, "Verify host", back))
            + (act(user, "realm.unflag", rid, "Clear flag", back) if o.get("flag") else
               act(user, "realm.flag", rid, "Flag", back, '<input type="text" name="reason" maxlength="200" '
                   'placeholder="why (staff only)" aria-label="Reason" required>')))
    return (f'<tr><td class="name"><b>{e(r["name"])}</b><span class="sub"><code>{e(rid)}</code> · {e(r.get("relay", ""))}</span>'
            f'{"<span class=sub>" + e(r["tagline"]) + "</span>" if r.get("tagline") else ""}'
            f'{_tags((r.get("state") or "", "good" if r.get("state") == "live" else ""), ("claimed", "") if r.get("claimed") else ("unclaimed", ""), ("hidden", "bad") if o.get("hidden") else ("", ""), ("official", "good") if o.get("official") else ("", ""), ("flagged", "hot") if o.get("flag") else ("", ""), ("featured", "hot") if o.get("featured") else ("", ""), ("verified", "good") if o.get("verified") else ("", ""), (f"{nrep} reports", "bad") if nrep else ("", ""))}'
            f'{"<span class=sub>Flag: " + e(o["flag"]) + "</span>" if o.get("flag") else ""}{_realm_reports_html(user, rid, back)}</td>'
            f'<td><span class="sub">last {e(r.get("last", ""))}</span><span class="sub">first {e(r.get("first", ""))}</span>'
            f'<span class="sub">{e(hb)[:300]}</span></td><td>{acts}</td></tr>')


# ---------------------------------------------------------------------------------------------- releases

def releases_page(user: dict) -> str:
    back = "/wrath/admin/releases"
    ok, rels, err = releases()
    ch = channel_doc()
    owner = user["role"] == "owner"
    rows = []
    for r in rels:
        tags = _tags(("draft", "bad") if r["draft"] else ("", ""), ("pre-release", "hot") if r["prerelease"] else ("", ""),
                     ("stable", "good") if ch["stable"] and ch["stable"].get("tag") == r["tag"] else ("", ""),
                     ("beta", "hot") if ch["beta"] and ch["beta"].get("tag") == r["tag"] else ("", ""),
                     ("latest.json", "") if r["latest_json"] else ("", ""))
        acts = ""
        if owner and r["version"] and not r["draft"]:
            acts = (act(user, "channel.set", r["tag"], "Make stable", back, '<input type="hidden" name="channel" value="stable">',
                        confirm=r["version"])
                    + act(user, "channel.set", r["tag"], "Make beta", back, '<input type="hidden" name="channel" value="beta">'))
        rows.append(f'<tr><td class="name"><b>{e(r["tag"])}</b><span class="sub">{e(r["name"])} · {e(r["published"])} · '
                    f'{len(r["assets"])} files{" · <a href=" + chr(34) + e(r["url"]) + chr(34) + " rel=noopener>page</a>" if r["url"] else ""}</span>{tags}</td>'
                    f'<td>{acts}</td></tr>')
    rel_html = ('<table class="ly-table"><thead><tr><th>Release</th><th>Channel</th></tr></thead><tbody>' + "".join(rows)
                + '</tbody></table>') if rows else ('<p class="fine">No releases yet.</p>' if ok else
                                                   f'<p class="ad-msg err">GitHub did not answer: {e(err)}</p>')
    hold = ""
    if owner:
        hold = (act(user, "channel.hold", "hold", "Release the hold" if ch["hold"] else "Hold all updates", back,
                    f'<input type="hidden" name="on" value="{"0" if ch["hold"] else "1"}">'
                    + ('' if ch["hold"] else '<input type="text" name="note" maxlength="200" placeholder="why (shown to no one)" aria-label="Note">'),
                    confirm="RELEASE" if ch["hold"] else "HOLD", danger=not ch["hold"]))
    chan = (f'<p>Stable: <b>{e(ch["stable"]["version"]) if ch["stable"] else "not set (the newest release)"}</b> · '
            f'Beta: <b>{e(ch["beta"]["version"]) if ch["beta"] else "not set"}</b> · '
            f'{_tags(("updates on hold", "bad") if ch["hold"] else ("updates flowing", "good"))}</p>{hold}'
            '<p class="fine">Written to /wrath/leyline/channel.json. The updater reads it before offering anything from '
            'latest.json (docs/ADMIN-CONSOLE.md says exactly how).</p>')
    posts = news_doc()["posts"]
    prow = "".join(
        f'<tr><td class="name"><b>{e(str(p.get("title", "")))}</b><span class="sub">{e(str(p.get("tag", "")))} · {e(str(p.get("date", "")))}</span>'
        f'{_tags(("hidden", "bad") if p.get("hidden") else ("shown", "good"))}<ul>'
        + "".join(f'<li>{e(str(i))}</li>' for i in (p.get("items") or [])[:8]) + '</ul></td><td>'
        + (act(user, "news.show", p["id"], "Show", back) if p.get("hidden") else act(user, "news.hide", p["id"], "Hide", back, confirm=p["id"], danger=True))
        + '</td></tr>' for p in posts)
    news_form = act(user, "news.add", "new", "Publish post", back,
                    '<input type="text" name="tag" maxlength="48" placeholder="tag, e.g. LAUNCHER 0.5" aria-label="Tag" required>'
                    '<input type="text" name="title" maxlength="80" placeholder="title" aria-label="Title" required>'
                    '<textarea name="items" maxlength="1200" placeholder="one line per point (up to 8)" aria-label="Points" required></textarea>',
                    block=True)
    news = (('<table class="ly-table"><thead><tr><th>Post</th><th></th></tr></thead><tbody>' + prow + '</tbody></table>')
            if prow else '<p class="fine">No posts yet: the launcher shows its built-in news.</p>')
    return (f'<section class="ly-panel"><h2>Channel</h2>{chan}</section>'
            f'<section class="ly-panel"><h2>Launcher releases</h2><p class="fine">github.com/orionopenwow/Leyline, read-only.</p>{rel_html}</section>'
            f'<section class="ly-panel"><h2>News</h2><p class="fine">The launcher\'s News page, from /wrath/leyline/news.json, '
            f'newest first.</p>{news_form}{news}</section>')


# ----------------------------------------------------------------------------------------------- flags

def flags_page(user: dict) -> str:
    back = "/wrath/admin/flags"
    f = flags_doc()
    owner = user["role"] == "owner"
    rows = []
    for k in flags_known():
        v = (f.get("flags") or {}).get(k) is True
        a = act(user, "flag.set", k, "Turn off" if v else "Turn on", back,
                f'<input type="hidden" name="on" value="{"0" if v else "1"}">', confirm=k, danger=not v) if owner else ""
        rows.append(f'<tr><td class="name"><code>{e(k)}</code></td><td>{_tags(("on", "good") if v else ("off", ""))}</td><td>{a}</td></tr>')
    lim = ", ".join(f"{k}: {v}" for k, v in (f.get("limits") or {}).items())
    return (f'<section class="ly-panel"><h2>Feature flags</h2><p class="fine">/wrath/leyline/flags.json (updated '
            f'{e(str(f.get("updated_at") or ""))}, sha256 {e(str(f.get("sha256") or ""))[:12]}...). Everything P2P and torrent ships '
            f'off; turning one on is the owner\'s call{"" if owner else " (owner only)"}. A player\'s own setting in the launcher '
            f'wins over this file.</p><table class="ly-table"><thead><tr><th>Flag</th><th>State</th><th></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><p class="fine">Limits: {e(lim)} · STUN: {e(", ".join(f.get("stun") or []))}. '
            f'A new flag is code: add it to KNOWN in stream/leyline_net.py and launcher/src-tauri/src/p2p/flags.rs, and it '
            f'shows up here.</p></section>')


# ----------------------------------------------------------------------------------------------- themes

def theme_items() -> list[dict]:
    """Theme packs: Workshop entries in the "themes" category (packaged mods and community links, docs/THEMES.md)."""
    ov = overrides()
    out = []
    for m in mods_raw()[0]:
        o = ov["mods"].get(m["id"]) or {}
        if (o.get("category") or m.get("category")) == THEMES_CAT:
            out.append({"kind": "mod", "id": m["id"], "name": o.get("name") or m["name"], "by": m.get("author", ""),
                        "version": m.get("version", ""), "state": o.get("state", "pending" if themes_review() else "approved"),
                        "featured": bool(o.get("featured")), "url": ""})
    for p in projects_all():
        pid = p.get("id", "")
        o = ov["projects"].get(pid) or {}
        if PID_RE.fullmatch(str(pid)) and (o.get("category") or p.get("category")) == THEMES_CAT:
            state = "hidden" if p.get("hidden") else o.get("state", "pending" if themes_review() else "approved")
            out.append({"kind": "link", "id": pid, "name": o.get("name") or str(p.get("title") or pid),
                        "by": str(p.get("submitted_by") or ""), "version": "", "state": state, "featured": bool(o.get("featured")),
                        "url": p.get("url") if isinstance(p.get("url"), str) and p["url"].startswith("https://") else ""})
    return out


def themes_page(user: dict) -> str:
    back = "/wrath/admin/themes"
    rows = []
    for t in theme_items():
        k, tid = t["kind"], t["id"]
        acts = ((act(user, f"{k}.approve", tid, "Approve", back) if t["state"] != "approved" and t["state"] != "hidden" else "")
                + (act(user, f"{k}.reject", tid, "Reject", back, confirm=tid, danger=True) if t["state"] in ("approved", "pending") else "")
                + act(user, f"{k}.feature", tid, "Unfeature" if t["featured"] else "Feature", back,
                      f'<input type="hidden" name="on" value="{"0" if t["featured"] else "1"}">')
                + (act(user, "mod.check", tid, "Re-run checker", back) if k == "mod" else ""))
        rows.append(f'<tr><td class="name"><b>{e(t["name"])}</b><span class="sub"><code>{e(k)}:{e(tid)}</code> '
                    f'{("v" + e(t["version"])) if t["version"] else ""} by {e(t["by"])}'
                    f'{" · <a href=" + chr(34) + e(t["url"]) + chr(34) + " rel=" + chr(34) + "noopener noreferrer nofollow" + chr(34) + ">link</a>" if t["url"] else ""}</span>'
                    f'{_tags((t["state"], "good" if t["state"] == "approved" else "hot" if t["state"] == "pending" else "bad"), ("featured", "hot") if t["featured"] else ("", ""))}'
                    f'</td><td>{acts}</td></tr>')
    table = ('<table class="ly-table"><thead><tr><th>Theme pack</th><th>Actions</th></tr></thead><tbody>' + "".join(rows)
             + '</tbody></table>') if rows else '<p class="fine">No theme packs in the Workshop yet.</p>'
    mode = ("Review is on (WU_THEMES_REVIEW=1): a pack stays off the site and all.json until it is approved here."
            if themes_review() else "Packs are listed as soon as they are added, like every Workshop entry; reject takes one "
            "off. Set WU_THEMES_REVIEW=1 to hold new packs until they are approved.")
    return (f'<section class="ly-panel"><h2>Theme packs</h2><p class="fine">Theme packs are the Workshop category '
            f'"themes" (docs/THEMES.md). {mode} The launcher checks every pack again when it installs and loads it.</p>{table}</section>')


# ---------------------------------------------------------------------------------------------- reports

def reports_page(user: dict, query: dict) -> str:
    back = "/wrath/admin/reports"
    nts = notes()

    def note_html(key):
        n = nts.get(key) or {}
        out = "".join(f'<span class="sub">{e(x.get("at", ""))} {e(x.get("by", ""))}: {e(x.get("text", ""))}</span>'
                      for x in (n.get("notes") or [])[-5:])
        return out + act(user, "report.note", key, "Add note", back,
                         '<input type="text" name="text" maxlength="500" placeholder="note" aria-label="Note" required>')
    show = (query.get("bugs") or ["open"])[0]
    show = show if show in ("open", "all") + BUG_STATES else "open"
    ok, bugs, err = bug_list(show)
    brow = []
    for b in bugs:
        key = f"bug:{b['id']}"
        acts = "".join(act(user, "bug.set", str(b["id"]), lab, back, f'<input type="hidden" name="status" value="{s}">')
                       for s, lab in (("seen", "Seen"), ("resolved", "Resolve"), ("wontfix", "Won't fix")) if s != b["status"])
        brow.append(f'<tr><td class="name"><b>#{b["id"]} {e(b["char"])}</b><span class="sub">level {e(b["level"])} · map {e(b["map"])} '
                    f'zone {e(b["zone"])} · {_when(b["created"])}</span>{_tags((b["status"], "hot" if b["status"] == "new" else ""))}'
                    f'<div class="body">{e(b["text"])}</div></td><td>{acts}{note_html(key)}</td></tr>')
    bug_tabs = " · ".join(f'<a href="/wrath/admin/reports?bugs={s}">{"<b>" + s + "</b>" if s == show else s}</a>'
                          for s in ("open", "new", "seen", "resolved", "wontfix", "all"))
    bugs_html = (f'<p class="ad-msg err">{e(err)}</p>' if not ok else
                 ('<table class="ly-table"><thead><tr><th>Report</th><th>Actions</th></tr></thead><tbody>' + "".join(brow)
                  + '</tbody></table>') if brow else '<p class="fine">No reports here.</p>')
    mrow = []
    store = social_store()
    mshow = (query.get("msgs") or ["open"])[0]
    mshow = mshow if mshow in ("open", "done", "dismissed", "all") else "open"
    try:
        sreps = store.reports("" if mshow == "all" else mshow, 200) if store is not None else []
    except Exception:   # noqa: BLE001
        sreps = []
    for r in sreps:
        rid = r.get("id")
        if not isinstance(rid, int):
            continue
        key = f"msg:{rid}"
        target = r.get("target")
        # Only the reported message itself: the reported player's last message in the thread, never the rest of
        # the conversation and never the reporter's own messages.
        ctx = [m for m in (r.get("context") or []) if isinstance(m, dict) and m.get("from") == target]
        body = str(ctx[-1].get("text") or "")[:2000] if ctx else ""
        st = str(r.get("status") or "open")
        acts = ((act(user, "msg.resolve", str(rid), "Done", back, '<input type="text" name="outcome" maxlength="300" placeholder="outcome" aria-label="Outcome">')
                 + act(user, "msg.dismiss", str(rid), "Dismiss", back)) if st == "open" else act(user, "msg.reopen", str(rid), "Reopen", back))
        mrow.append(f'<tr><td class="name"><b>{e(str(r.get("target_name") or "?"))[:40]}</b> reported by {e(str(r.get("reporter_name") or "?"))[:40]}'
                    f'<span class="sub">{_when(r.get("at"))} · {e(str(r.get("reason") or ""))[:40]} · via {e(str(r.get("via") or ""))[:10]}'
                    f'{" · note: " + e(str(r.get("note") or ""))[:200] if r.get("note") else ""}</span>'
                    f'{_tags((st, "good" if st != "open" else "hot"))}'
                    f'{"<span class=sub>outcome: " + e(str(r.get("outcome") or ""))[:300] + "</span>" if r.get("outcome") else ""}'
                    + (f'<div class="body">{e(body)}</div>' if body else '<span class="sub">(no message from them in the thread)</span>')
                    + f'</td><td>{acts}{note_html(key)}</td></tr>')
    msg_tabs = " · ".join(f'<a href="/wrath/admin/reports?msgs={s}">{"<b>" + s + "</b>" if s == mshow else s}</a>'
                          for s in ("open", "done", "dismissed", "all"))
    msg_html = ('<table class="ly-table"><thead><tr><th>Reported message</th><th>Actions</th></tr></thead><tbody>' + "".join(mrow)
                + '</tbody></table>') if mrow else ('<p class="fine">No message reports here.</p>' if store is not None
                                                   else '<p class="fine">Friends and messages (stream/social.py) are not on this portal.</p>')
    msg_html = f'<p>{msg_tabs}</p>' + msg_html
    lrow = []
    for p in projects_all():
        n = len(p.get("reports") or []) if isinstance(p.get("reports"), list) else 0
        pid = p.get("id", "")
        if not n or p.get("hidden") or not PID_RE.fullmatch(str(pid)):
            continue
        lrow.append(f'<tr><td class="name"><b>{e(str(p.get("title") or pid))}</b><span class="sub">{n} reports · <code>{e(pid)}</code></span></td>'
                    f'<td>{act(user, "link.hide", pid, "Hide", back, confirm=pid, danger=True)}'
                    f'{act(user, "link.dismiss", pid, "Dismiss reports", back)}{note_html("link:" + pid)}</td></tr>')
    links_html = ('<table class="ly-table"><thead><tr><th>Reported link</th><th>Actions</th></tr></thead><tbody>' + "".join(lrow)
                  + '</tbody></table>') if lrow else '<p class="fine">No reported links.</p>'
    net = P("network")
    rrow = []
    for x in (net.reports("open") if net is not None else [])[:200]:
        rrow.append(f'<tr><td class="name"><b>{e(x.get("name") or x.get("realm"))}</b><span class="sub"><code>{e(x.get("realm", ""))}</code>'
                    f' · {e(x.get("at", ""))} · {e(x.get("by_name") or x.get("by", ""))}</span></td>'
                    f'<td>{e(net.REPORT_REASON.get(x.get("reason"), "?"))}{"<span class=sub>" + e(x["note"]) + "</span>" if x.get("note") else ""}</td>'
                    f'<td><a href="/wrath/admin/realms">Realms</a></td></tr>')
    realm_html = ('<table class="ly-table"><thead><tr><th>Realm</th><th>Reason</th><th></th></tr></thead><tbody>'
                  + "".join(rrow) + '</tbody></table>') if rrow else '<p class="fine">No open realm reports.</p>'
    return (f'<section class="ly-panel"><h2>.bug reports</h2><p>{bug_tabs}</p>{bugs_html}</section>'
            f'<section class="ly-panel"><h2>Realm reports</h2><p class="fine">From players on /wrath/realms. Resolve, '
            f'dismiss, hide or flag a realm on the Realms tab.</p>{realm_html}</section>'
            f'<section class="ly-panel"><h2>Message reports</h2>{msg_html}</section>'
            f'<section class="ly-panel"><h2>Workshop link reports</h2>{links_html}</section>')


# ------------------------------------------------------------------------------------------------ the forum
def forum_page(user: dict, query: dict) -> str:
    """The forum's queue (stream/forum.py), the way the reports work: reported posts first, then the threads (pin, lock,
    hide, merge a duplicate into another: "consolidate"), then the hidden posts. Nothing here deletes anything."""
    store = forum_store()
    if store is None:
        return '<section class="ly-panel"><h2>Forum</h2><p class="fine">The forum (stream/forum.py) is not on this portal.</p></section>'
    back = "/wrath/admin/forum"
    page = "/wrath/leyline/forum"
    show = (query.get("show") or ["open"])[0]
    show = show if show in ("open", "done", "dismissed", "all") else "open"
    rrow = []
    for r in store.reports("" if show == "all" else show, 200):
        rid, st = r["id"], r["status"]
        acts = ""
        if st == "open":
            if not r["post_hidden"]:
                acts += act(user, "forum.post.hide", str(r["post"]), "Hide the post", back)
            acts += (act(user, "forum.report.done", str(rid), "Done", back,
                         '<input type="text" name="outcome" maxlength="300" placeholder="outcome" aria-label="Outcome">')
                     + act(user, "forum.report.dismiss", str(rid), "Dismiss", back))
        else:
            acts += act(user, "forum.report.reopen", str(rid), "Reopen", back)
        rrow.append(f'<tr><td class="name"><b>{e(r["author_name"] or "?")[:40]}</b> reported by {e(r["reporter_name"] or "?")[:40]}'
                    f'<span class="sub">{_when(r["at"])} · {e(r["reason"])} · in <a href="{page}/t/{r["thread"]}#p{r["post"]}">'
                    f'{e(r["thread_title"] or "?")[:80]}</a>{" · note: " + e(r["note"])[:200] if r["note"] else ""}</span>'
                    f'{_tags((st, "good" if st != "open" else "hot"), ("hidden", "") if r["post_hidden"] else ("", ""))}'
                    + (f'<span class="sub">outcome: {e(r["outcome"])[:300]}</span>' if r["outcome"] else "")
                    + f'<div class="body">{e(r["post_body"])[:2000]}</div></td><td>{acts}</td></tr>')
    tabs = " · ".join(f'<a href="{back}?show={s}">{"<b>" + s + "</b>" if s == show else s}</a>' for s in ("open", "done", "dismissed", "all"))
    reports = (f'<p>{tabs}</p>' + ('<table class="ly-table"><thead><tr><th>Reported post</th><th>Actions</th></tr></thead><tbody>'
                                    + "".join(rrow) + '</tbody></table>' if rrow else '<p class="fine">No forum reports here.</p>'))
    q = (query.get("q") or [""])[0][:60]
    trow = []
    for t in store.staff_threads(q, 60):
        tid = str(t["id"])
        acts = (act(user, "forum.thread.unpin" if t["pinned"] else "forum.thread.pin", tid, "Unpin" if t["pinned"] else "Pin", back)
                + act(user, "forum.thread.unlock" if t["locked"] else "forum.thread.lock", tid, "Unlock" if t["locked"] else "Lock", back)
                + act(user, "forum.thread.unhide" if t["hidden"] else "forum.thread.hide", tid, "Show" if t["hidden"] else "Hide", back,
                      confirm=None if t["hidden"] else tid, danger=not t["hidden"])
                + act(user, "forum.thread.merge", tid, "Merge into", back,
                      '<input type="text" name="into" inputmode="numeric" pattern="[0-9]{1,9}" size="6" placeholder="thread #" '
                      'aria-label="Merge into thread number" required>', confirm=tid, danger=True))
        trow.append(f'<tr><td class="name"><b>#{tid} <a href="{page}/t/{tid}">{e(t["title"])}</a></b>'
                    f'<span class="sub">{e(t["cat"])} · by {e(t["author"])} · {t["replies"]} replies · {_when(t["bumped"])}</span>'
                    f'{_tags(("pinned", "good") if t["pinned"] else ("", ""), ("locked", "") if t["locked"] else ("", ""), ("hidden", "hot") if t["hidden"] else ("", ""))}'
                    f'</td><td>{acts}</td></tr>')
    search = (f'<form method="get" action="{back}"><input type="text" name="q" value="{e(q)}" maxlength="60" placeholder="title" '
              'aria-label="Search titles"> <button type="submit">Search</button></form>')
    threads = search + ('<table class="ly-table"><thead><tr><th>Thread</th><th>Actions</th></tr></thead><tbody>' + "".join(trow)
                        + '</tbody></table>' if trow else '<p class="fine">No threads.</p>')
    hrow = [f'<tr><td class="name"><b>{e(p["name"])}</b><span class="sub">post {p["id"]} in <a href="{page}/t/{p["thread"]}">thread #{p["thread"]}</a> · '
            f'{_when(p["created"])}</span><div class="body">{e(p["body"])[:600]}</div></td>'
            f'<td>{act(user, "forum.post.unhide", str(p["id"]), "Show again", back)}</td></tr>' for p in store.hidden_posts(50)]
    hidden = ('<table class="ly-table"><thead><tr><th>Hidden post</th><th></th></tr></thead><tbody>' + "".join(hrow)
              + '</tbody></table>') if hrow else '<p class="fine">No hidden posts.</p>'
    return (f'<section class="ly-panel"><h2>Reported posts</h2>{reports}</section>'
            f'<section class="ly-panel"><h2>Threads</h2><p class="fine">Pin keeps a thread at the top of its category. Merge moves a '
            f'duplicate\'s posts into another thread (type the duplicate\'s number to confirm); its address then leads there.</p>{threads}</section>'
            f'<section class="ly-panel"><h2>Hidden posts</h2>{hidden}</section>')


# ------------------------------------------------------------------------------------------------ health

def health_checks() -> list[tuple[str, bool | None, str]]:
    out = []
    try:
        ok, kind = P("health")()
        out.append(("Realm SOAP", ok, "answers" if ok else f"not answering ({kind})"))
    except Exception as ex:   # noqa: BLE001
        out.append(("Realm SOAP", False, str(ex)[:80]))
    ok, _, err = soap_lines("ovadmin ping")
    out.append(("ov_admin.lua on the realm", ok, "loaded" if ok else err))
    try:
        realms, lok = P("community_realms")()
        out.append(("Beacons relay listing", lok, f"{len(realms)} realms" if lok else "not answering"))
    except Exception:   # noqa: BLE001
        out.append(("Beacons relay listing", False, "error"))
    store = creations_store()
    if store is not None:
        try:
            store.refresh()
            age = _now() - store.updated if store.updated else None
            out.append(("Workshop export (items.json)", age is not None and age < 1800,
                        f"{int(age // 60)} min old" if age is not None else "missing"))
        except Exception:   # noqa: BLE001
            out.append(("Workshop export (items.json)", False, "unreadable"))
    mods, _ = mods_raw()
    out.append(("Mods catalog", bool(mods), f"{len(mods)} mods" if mods else "empty or missing"))
    g = gamedata_status()
    out.append(("Game data streaming", True, ("on" if g.get("gamedata_streaming") else "off: players use their own game folder")
                + (f" since {_when_iso(g['gamedata_since'])}" if g.get("gamedata_since") else "")
                + " (read-only here; the owner's killswitch bat flips it)"))
    out.append(("Admin folder writable", _writable(admin_dir()), admin_dir()))
    out.append(("Leyline feeds folder writable", _writable(leyline_dir()), leyline_dir()))
    out.append(("Checker (wu-mod.py)", _wu_mod() is not None, "found" if _wu_mod() is not None else "not on this server"))
    out.append(("Community index", os.path.isfile(hub_index_path()), hub_index_path()))
    rok, rels, rerr = releases()
    out.append(("GitHub releases API", rok, f"{len(rels)} releases" if rok else rerr))
    return out


def health_page(user: dict) -> str:
    rows = "".join(f'<tr><td class="name">{e(n)}</td><td>{_tags(("ok", "good") if ok else ("problem", "bad") if ok is False else ("?", ""))}</td>'
                   f'<td>{e(str(d))}</td></tr>' for n, ok, d in health_checks())
    ap = os.environ.get("WU_AUTOPILOT_STATUS", "")
    doc = _read_json(ap, {}) if ap else {}
    if doc:
        auto = (f'<p>Last run {e(str(doc.get("at", "")))}: {_tags(("ok", "good") if doc.get("ok") else ("failed", "bad"))}'
                f'{" failed step: " + e(str(doc.get("failed_step"))) if doc.get("failed_step") else ""}'
                f' · updates {e(", ".join(str(x) for x in (doc.get("ids") or [])[:20]))}</p>')
    else:
        auto = ('<p class="fine">Skipped: Autopilot runs on the owner\'s PC (control/last-run.json there) and its check logs '
                'stay there, so this server cannot see them. Set WU_AUTOPILOT_STATUS to a copy of last-run.json if a step '
                'ever uploads one.</p>')
    return (f'<section class="ly-panel"><h2>This server</h2>{gamedata_line()}<table class="ly-table"><tbody>{rows}</tbody></table></section>'
            f'<section class="ly-panel"><h2>Autopilot</h2>{auto}</section>')


# ------------------------------------------------------------------------------------------- staff, audit

def staff_page(user: dict) -> str:
    back = "/wrath/admin/staff"
    owner = user["role"] == "owner"
    rows = []
    for a in sorted(owners()):
        rows.append(f'<tr><td class="name"><code>{e(a)}</code></td><td>{_tags(("owner", "good"))} WU_ADMIN_OWNERS</td><td></td></tr>')
    for a, v in sorted(staff_file().items()):
        rev = act(user, "staff.revoke", a, "Revoke", back, confirm=a, danger=True) if owner else ""
        rows.append(f'<tr><td class="name"><code>{e(a)}</code> {e(str(v.get("name", "")))}</td>'
                    f'<td>{_tags(("staff", ""))} granted by {e(str(v.get("by", "")))} {e(str(v.get("at", "")))}</td><td>{rev}</td></tr>')
    for a in sorted(env_staff()):
        rows.append(f'<tr><td class="name"><code>{e(a)}</code></td><td>{_tags(("staff", ""))} environment (WU_ADMIN_STAFF / WU_MODS_ADMINS)</td><td></td></tr>')
    grant = act(user, "staff.grant", "new", "Grant staff", back,
                '<input type="text" name="account" maxlength="64" placeholder="account id" aria-label="Account id" required>'
                '<input type="text" name="name" maxlength="40" placeholder="name (for this list)" aria-label="Name">') if owner else ""
    gm = gm_min()
    return (f'<section class="ly-panel"><h2>Staff</h2><p class="fine">Owners come from WU_ADMIN_OWNERS. '
            f'{"Game accounts with GM level " + str(gm) + " or more on the realm are staff too." if gm else "The GM-level rule is off."} '
            f'Someone without access sees their own account id on the staff-only page.</p>'
            f'<table class="ly-table"><tbody>{"".join(rows)}</tbody></table>{grant}</section>')


def audit_page(user: dict, query: dict) -> str:
    flt = (query.get("action") or [""])[0][:40]
    rows = "".join(
        f'<tr><td class="name">{e(str(r.get("at", "")))}<span class="sub">{e(str(r.get("name", "")))} <code>{e(str(r.get("who", "")))}</code></span></td>'
        f'<td><code>{e(str(r.get("action", "")))}</code> {e(str(r.get("target", "")))}{_tags(("refused", "bad") if not r.get("ok") else ("", ""))}'
        f'<span class="sub">{e(str(r.get("note", "")))}</span></td>'
        f'<td><span class="sub">before: {e(json.dumps(r.get("before"), ensure_ascii=False))[:300]}</span>'
        f'<span class="sub">after: {e(json.dumps(r.get("after"), ensure_ascii=False))[:300]}</span></td></tr>'
        for r in audit_tail(300, flt))
    return (f'<section class="ly-panel"><h2>Audit log</h2><form method="get" action="/wrath/admin/audit">'
            f'<input type="text" name="action" value="{e(flt)}" placeholder="action starts with, e.g. flag." aria-label="Filter">'
            f'<button type="submit">Filter</button></form>'
            + (f'<table class="ly-table"><thead><tr><th>When, who</th><th>What</th><th>Change</th></tr></thead><tbody>{rows}</tbody></table>'
               if rows else '<p class="fine">Nothing logged yet.</p>') + '</section>')


# ----------------------------------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------------------------------

class Refused(Exception):
    pass


def _clean_line(v, n: int) -> str:
    s = " ".join(str(v or "").replace("\x00", "").split())
    return "".join(c for c in s if c.isprintable())[:n]


def _no_brand(s: str) -> str:
    if BRAND_RE.search(s):
        raise Refused("Players see this: leave out the game-brand names (say \"the game\", \"Wrath\", \"3.3.5a\").")
    return s


def _known_mod(ident: str) -> dict:
    m = next((x for x in mods_raw()[0] if x["id"] == ident), None)
    if m is None:
        raise Refused("No such mod.")
    return m


def _known_project(pid: str) -> dict:
    p = next((x for x in projects_all() if x.get("id") == pid), None) if PID_RE.fullmatch(pid) else None
    if p is None:
        raise Refused("No such link.")
    return p


def _feature_on(form) -> bool:
    return form.get("on") == "1"


def a_mod_state(state):
    def fn(user, target, form):
        _known_mod(target)
        return set_override("mods", target, {"state": state})
    return fn


def a_mod_feature(user, target, form):
    _known_mod(target)
    return set_override("mods", target, {"featured": True if _feature_on(form) else None})


def a_mod_edit(user, target, form):
    _known_mod(target)
    cat = form.get("category", "")
    if cat and cat not in {c["id"] for c in categories()}:
        raise Refused("Unknown category.")
    name = _no_brand(_clean_line(form.get("name"), 60))
    desc = _no_brand(_clean_line(form.get("description"), 200))
    return set_override("mods", target, {"name": name or None, "description": desc or None, "category": cat or None})


def a_mod_check(user, target, form):
    m = _known_mod(target)
    doc = run_mod_check(m, user["account"])
    return {}, {"errors": doc["errors"], "warnings": doc["warnings"], "note": doc.get("note", "")}


def _projects():
    w = P("workshop")
    proj = getattr(w, "projects", None) if w is not None else None
    if proj is None:
        raise Refused("Community links are not set up here.")
    return proj


def a_link_hidden(hidden):
    def fn(user, target, form):
        p = _known_project(target)
        before = {"hidden": bool(p.get("hidden")), "reports": len(p.get("reports") or [])}
        ok, msg = _projects().set_hidden(target, {"id": user["account"]}, hidden, staff=True)
        if not ok:
            raise Refused(msg)
        return before, {"hidden": hidden}
    return fn


def a_link_dismiss(user, target, form):
    p = _known_project(target)
    before = {"reports": len(p.get("reports") or [])}
    ok, msg = _projects().clear_reports(target)
    if not ok:
        raise Refused(msg)
    return before, {"reports": 0}


def a_link_state(state):
    def fn(user, target, form):
        _known_project(target)
        return set_override("projects", target, {"state": state})
    return fn


def a_link_feature(user, target, form):
    _known_project(target)
    return set_override("projects", target, {"featured": True if _feature_on(form) else None})


def a_link_edit(user, target, form):
    _known_project(target)
    cat = form.get("category", "")
    if cat and cat not in {c["id"] for c in categories()}:
        raise Refused("Unknown category.")
    name = _no_brand(_clean_line(form.get("name"), 80))
    desc = _no_brand(_clean_line(form.get("description"), 160))
    return set_override("projects", target, {"name": name or None, "description": desc or None, "category": cat or None})


def _ws_target(target: str) -> str:
    if not WS_ID_RE.fullmatch(target):
        raise Refused("Not a Workshop item id.")
    return target


def a_ws_set(word):
    def fn(user, target, form):
        _ws_target(target)
        ok, lines, err = soap_lines(f"ovadmin ws set {target} {word}")
        forget("ws:")
        if not ok:
            raise Refused(err or "The realm said no.")
        return {}, {"state": {"approve": "approved", "reject": "rejected", "pending": "pending"}[word]}
    return fn


def a_ws_edit(user, target, form):
    _ws_target(target)
    field = form.get("field")
    if field not in ("title", "descr"):
        raise Refused("Unknown field.")
    text = game_text(form.get("text"), 40 if field == "title" else 140)
    if field == "title" and not text:
        raise Refused("A title needs letters or digits.")
    _no_brand(text)
    before = next(({field: r[field]} for r in ws_list("all")[1] if str(r["id"]) == target), {})
    ok, lines, err = soap_lines(f"ovadmin ws edit {target} {field} {text}")
    forget("ws:")
    if not ok:
        raise Refused(err or "The realm said no.")
    return before, {field: text}


def a_ws_check(user, target, form):
    _ws_target(target)
    ok, lines, err = soap_lines(f"ovadmin ws check {target}")
    if not ok:
        raise Refused(err or "The realm said no.")
    items = [x.split("\t", 1)[1][:200] for x in lines if x.startswith("FINDING\t")]
    with _lock:
        _write_json(_apath(os.path.join("checks", f"ws-{target}.json")), {"at": _iso(), "by": user["account"], "items": items})
    return {}, {"findings": len(items)}


def a_ws_feature(user, target, form):
    _ws_target(target)
    return set_override("workshop", target, {"featured": True if _feature_on(form) else None})


def _hub_append(rec: dict) -> None:
    """One line in hub/decisions.jsonl (stream/hub.py Store.decisions: the latest line per id wins)."""
    line = json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n"
    with _lock:
        os.makedirs(hub_dir(), exist_ok=True)
        fd = os.open(os.path.join(hub_dir(), "decisions.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)


def a_hub_decide(decision):
    def fn(user, target, form):
        sub = next((s for s in hub_submissions() if s["id"] == target), None)
        if sub is None:
            raise Refused("No such submission.")
        reason = _clean_line(form.get("reason"), 200)
        if decision == "reject" and not reason:
            raise Refused("Say why.")
        before = hub_decisions().get(target) or {}
        rec = {"id": target, "decision": decision, "repo": str(sub.get("repo") or "")[:300], "build": str(sub.get("build") or "")[:10],
               "category": str(sub.get("category") or "")[:32], "reason": reason, "by": user["account"], "at": _iso()}
        _hub_append(rec)
        return before, rec
    return fn


def _hub_entry(hid: str) -> dict:
    x = next((x for x in hub_entries() if x["id"] == "link:" + hid), None) if PID_RE.fullmatch(hid) else None
    if x is None:
        raise Refused("No such index entry.")
    return x


def a_hub_list(decision):
    def fn(user, target, form):
        x = _hub_entry(target)
        reason = _clean_line(form.get("reason"), 200)
        if decision == "delist" and not reason:
            raise Refused("Say why.")
        before = hub_decisions().get(target) or {}
        rec = {"id": target, "decision": decision, "repo": str(x.get("repo") or "")[:300], "category": str(x.get("category") or "")[:32],
               "reason": reason, "by": user["account"], "at": _iso()}
        _hub_append(rec)
        return before, rec
    return fn


def a_hub_rescan(user, target, form):
    if target != "all":
        _hub_entry(target)
    with _lock:
        path = os.path.join(hub_dir(), "rescan.json")
        doc = _read_json(path, {})
        reqs = doc.get("requests") if isinstance(doc.get("requests"), dict) else {}
        before = reqs.get(target) or {}
        reqs[target] = {"requested_at": _iso(), "by": user["account"]}
        _write_json(path, {"format": 1, "updated_at": _iso(), "requests": reqs})
    return before, reqs[target]


def _realm_target(target: str) -> str:
    if not REALM_ID_RE.fullmatch(target):
        raise Refused("Not a realm id.")
    return target


def a_realm_reports(user: dict, target: str, form: dict):
    """Close the open player reports on a realm (stream/network.py). form "how": resolved or dismissed."""
    _realm_target(target)
    net = P("network")
    if net is None:
        raise Refused("The realm reports module is not on this portal.")
    before = {"open_reports": len(net.reports("open", target))}
    how = form.get("how") if form.get("how") in ("resolved", "dismissed") else "resolved"
    n = net.resolve(target, user.get("name") or user.get("account") or "staff", how)
    return before, {"open_reports": before["open_reports"] - n, "closed": how}


def a_realm(changes_fn):
    def fn(user, target, form):
        _realm_target(target)
        before, after = set_realm_override(target, changes_fn(form))
        try:
            P("_listing")["at"] = -1e9   # the public list picks it up on its next read
        except Exception:   # noqa: BLE001
            pass
        forget("listing")
        return before, after
    return fn


def _flag_reason(form):
    r = _clean_line(form.get("reason"), 200)
    if not r:
        raise Refused("Say why.")
    return {"flag": r}


def a_channel_set(user, target, form):
    channel = form.get("channel")
    if channel not in ("stable", "beta"):
        raise Refused("Unknown channel.")
    ok, rels, err = releases()
    r = next((x for x in rels if x["tag"] == target and x["version"] and not x["draft"]), None)
    if r is None:
        raise Refused("That release is not on GitHub (or is a draft).")
    if channel == "stable" and form.get("confirm", "").strip() != r["version"]:
        raise Refused(f"Type {r['version']} to confirm.")
    with _lock:
        doc = channel_doc()
        before = {channel: doc.get(channel)}
        doc[channel] = {"version": r["version"], "tag": r["tag"], "url": r["url"]}
        doc["updated_at"] = _iso()
        _write_json(_lpath("channel.json"), doc)
    return before, {channel: doc[channel]}


def a_channel_hold(user, target, form):
    on = _feature_on(form)
    with _lock:
        doc = channel_doc()
        before = {"hold": doc["hold"]}
        doc["hold"] = on
        doc["hold_note"] = _clean_line(form.get("note"), 200) if on else ""
        doc["updated_at"] = _iso()
        _write_json(_lpath("channel.json"), doc)
    return before, {"hold": on}


def _news_write(fn):
    with _lock:
        doc = news_doc()
        before, after = fn(doc)
        doc["updated_at"] = _iso()
        _write_json(_lpath("news.json"), doc)
    return before, after


def a_news_add(user, target, form):
    tag = _no_brand(_clean_line(form.get("tag"), 48))
    title = _no_brand(_clean_line(form.get("title"), 80))
    items = [_no_brand(_clean_line(x, 200)) for x in str(form.get("items") or "").splitlines()]
    items = [x for x in items if x][:8]
    if not tag or not title or not items:
        raise Refused("A post needs a tag, a title and at least one point.")
    post = {"id": time.strftime("n%Y%m%d%H%M%S", time.gmtime()) + secrets.token_hex(2), "date": time.strftime("%Y-%m-%d", time.gmtime()),
            "tag": tag.upper(), "title": title.upper(), "items": items, "by": user["account"]}

    def w(doc):
        doc["posts"].insert(0, post)
        return {}, post
    return _news_write(w)


def a_news_hidden(hidden):
    def fn(user, target, form):
        def w(doc):
            for p in doc["posts"]:
                if p.get("id") == target:
                    before = {"hidden": bool(p.get("hidden"))}
                    if hidden:
                        p["hidden"] = True
                    else:
                        p.pop("hidden", None)
                    return before, {"hidden": hidden}
            raise Refused("No such post.")
        return _news_write(w)
    return fn


def a_flag_set(user, target, form):
    if target not in flags_known():
        raise Refused("Unknown flag.")
    on = _feature_on(form)
    before = {target: (flags_doc().get("flags") or {}).get(target) is True}
    try:
        doc = write_flag(target, on, user["account"])
    except ValueError as ex:
        raise Refused(str(ex)) from None
    return before, {target: doc["flags"][target], "sha256": doc.get("sha256", "")[:12]}


def _note_key(target: str) -> str:
    if not re.fullmatch(r"(bug:\d{1,10}|msg:\d{1,10}|link:[0-9a-f]{12})", target):
        raise Refused("Not a report.")
    return target


def _notes_write(key, fn):
    with _lock:
        doc = notes()
        n = doc.setdefault(key, {"status": "open", "notes": []})
        before = {"status": n.get("status", "open")}
        after = fn(n)
        _write_json(_apath("notes.json"), doc)
    return before, after


def a_report_note(user, target, form):
    key = _note_key(target)
    text = _clean_line(form.get("text"), 500)
    if not text:
        raise Refused("Write the note.")

    def w(n):
        n.setdefault("notes", []).append({"by": user["name"] + " (" + user["account"] + ")", "at": _iso(), "text": text})
        n["notes"] = n["notes"][-50:]
        return {"note": text}
    return _notes_write(key, w)


def a_report_status(status):
    def fn(user, target, form):
        key = _note_key(target)

        def w(n):
            n["status"] = status
            return {"status": status}
        return _notes_write(key, w)
    return fn


def a_msg_status(status):
    def fn(user, target, form):
        store = social_store()
        if store is None:
            raise Refused("Friends and messages are not on this portal.")
        if not target.isdigit() or len(target) > 10:
            raise Refused("Not a report.")
        outcome = _clean_line(form.get("outcome"), 300) or {"done": "handled", "dismissed": "dismissed", "open": "reopened"}[status]
        before = next(({"status": r.get("status")} for r in store.reports("", 1000) if r.get("id") == int(target)), None)
        if before is None:
            raise Refused("No such report.")
        if not store.resolve_report(int(target), user["name"] + " (" + user["account"] + ")", outcome, status):
            raise Refused("The report did not change.")
        return before, {"status": status, "outcome": outcome}
    return fn


def _forum():
    store = forum_store()
    if store is None:
        raise Refused("The forum is not on this portal.")
    return store, P("forum").ForumError


def _forum_id(target: str) -> int:
    if not target.isdigit() or len(target) > 9:
        raise Refused("Not a forum id.")
    return int(target)


def a_forum_thread(field, on):
    def fn(user, target, form):
        store, err = _forum()
        try:
            return store.set_thread(_forum_id(target), field, on)
        except err as ex:
            raise Refused(ex.text)
    return fn


def a_forum_post(on):
    def fn(user, target, form):
        store, err = _forum()
        try:
            return store.set_post_hidden(_forum_id(target), on)
        except err as ex:
            raise Refused(ex.text)
    return fn


def a_forum_merge(user, target, form):
    store, err = _forum()
    into = str(form.get("into") or "").strip()
    try:
        return store.merge(_forum_id(target), _forum_id(into))
    except err as ex:
        raise Refused(ex.text)


def a_forum_report(status):
    def fn(user, target, form):
        store, _ = _forum()
        rid = _forum_id(target)
        before = next(({"status": r["status"]} for r in store.reports("", 1000) if r["id"] == rid), None)
        if before is None:
            raise Refused("No such report.")
        outcome = _clean_line(form.get("outcome"), 300) or {"done": "handled", "dismissed": "dismissed", "open": "reopened"}[status]
        if not store.resolve_report(rid, user["name"] + " (" + user["account"] + ")", outcome, status):
            raise Refused("The report did not change.")
        return before, {"status": status, "outcome": outcome}
    return fn


def a_bug_set(user, target, form):
    status = form.get("status")
    if not target.isdigit() or len(target) > 10 or status not in BUG_STATES:
        raise Refused("Not a bug report or status.")
    ok, lines, err = soap_lines(f"ovadmin bugs set {int(target)} {status}")
    forget("bug")
    if not ok:
        raise Refused(err or "The realm said no.")
    _notes_write(f"bug:{int(target)}", lambda n: n.update(status="resolved" if status in ("resolved", "wontfix") else "open") or {})
    return {}, {"status": status}


def a_staff_grant(user, target, form):
    acct = str(form.get("account") or "").strip()
    if not ACCOUNT_ID_RE.fullmatch(acct):
        raise Refused("That is not an account id (it is shown on the staff-only page).")
    name = _clean_line(form.get("name"), 40)
    with _lock:
        doc = _read_json(_apath("staff.json"), {})
        s = doc.setdefault("staff", {})
        before = s.get(acct) or {}
        s[acct] = {"name": name, "by": user["account"], "at": _iso()}
        doc["format"] = 1
        _write_json(_apath("staff.json"), doc, 0o640)
    return before, s[acct]


def a_staff_revoke(user, target, form):
    with _lock:
        doc = _read_json(_apath("staff.json"), {})
        s = doc.setdefault("staff", {})
        if target not in s:
            raise Refused("Not on the staff list (owners and environment staff are set in portal.env).")
        before = s.pop(target)
        _write_json(_apath("staff.json"), doc, 0o640)
    return before, {}


# name -> (function, role needed, typed confirm: True = the target, a str = that word, None = none)
ACTIONS = {
    "mod.approve": (a_mod_state("approved"), "staff", None),
    "mod.reject": (a_mod_state("rejected"), "staff", True),
    "mod.unpublish": (a_mod_state("unpublished"), "staff", True),
    "mod.feature": (a_mod_feature, "staff", None),
    "mod.edit": (a_mod_edit, "staff", None),
    "mod.check": (a_mod_check, "staff", None),
    "link.hide": (a_link_hidden(True), "staff", True),
    "link.unhide": (a_link_hidden(False), "staff", None),
    "link.dismiss": (a_link_dismiss, "staff", None),
    "link.approve": (a_link_state("approved"), "staff", None),
    "link.reject": (a_link_state("rejected"), "staff", True),
    "link.feature": (a_link_feature, "staff", None),
    "link.edit": (a_link_edit, "staff", None),
    "ws.approve": (a_ws_set("approve"), "staff", None),
    "ws.reject": (a_ws_set("reject"), "staff", True),
    "ws.unpublish": (a_ws_set("pending"), "staff", True),
    "ws.edit": (a_ws_edit, "staff", None),
    "ws.check": (a_ws_check, "staff", None),
    "ws.feature": (a_ws_feature, "staff", None),
    "hub.approve": (a_hub_decide("approve"), "staff", None),
    "hub.reject": (a_hub_decide("reject"), "staff", None),
    "hub.delist": (a_hub_list("delist"), "staff", True),
    "hub.relist": (a_hub_list("approve"), "staff", None),
    "hub.rescan": (a_hub_rescan, "staff", None),
    "realm.hide": (a_realm(lambda f: {"hidden": True}), "staff", True),
    "realm.unhide": (a_realm(lambda f: {"hidden": None}), "staff", None),
    "realm.official": (a_realm(lambda f: {"official": True}), "staff", True),
    "realm.unofficial": (a_realm(lambda f: {"official": None}), "staff", None),
    "realm.flag": (a_realm(_flag_reason), "staff", None),
    "realm.unflag": (a_realm(lambda f: {"flag": None}), "staff", None),
    "realm.feature": (a_realm(lambda f: {"featured": True}), "staff", None),
    "realm.unfeature": (a_realm(lambda f: {"featured": None}), "staff", None),
    "realm.verify": (a_realm(lambda f: {"verified": True}), "staff", None),
    "realm.unverify": (a_realm(lambda f: {"verified": None}), "staff", None),
    "realm.reports": (a_realm_reports, "staff", None),
    "channel.set": (a_channel_set, "owner", None),      # stable: types the version (checked inside)
    "channel.hold": (a_channel_hold, "owner", "hold"),
    "news.add": (a_news_add, "staff", None),
    "news.hide": (a_news_hidden(True), "staff", True),
    "news.show": (a_news_hidden(False), "staff", None),
    "flag.set": (a_flag_set, "owner", True),
    "report.note": (a_report_note, "staff", None),
    "report.resolve": (a_report_status("resolved"), "staff", None),
    "report.reopen": (a_report_status("open"), "staff", None),
    "msg.resolve": (a_msg_status("done"), "staff", None),
    "msg.dismiss": (a_msg_status("dismissed"), "staff", None),
    "msg.reopen": (a_msg_status("open"), "staff", None),
    "bug.set": (a_bug_set, "staff", None),
    "forum.post.hide": (a_forum_post(True), "staff", None),
    "forum.post.unhide": (a_forum_post(False), "staff", None),
    "forum.thread.pin": (a_forum_thread("pinned", True), "staff", None),
    "forum.thread.unpin": (a_forum_thread("pinned", False), "staff", None),
    "forum.thread.lock": (a_forum_thread("locked", True), "staff", None),
    "forum.thread.unlock": (a_forum_thread("locked", False), "staff", None),
    "forum.thread.hide": (a_forum_thread("hidden", True), "staff", True),
    "forum.thread.unhide": (a_forum_thread("hidden", False), "staff", None),
    "forum.thread.merge": (a_forum_merge, "staff", True),
    "forum.report.done": (a_forum_report("done"), "staff", None),
    "forum.report.dismiss": (a_forum_report("dismissed"), "staff", None),
    "forum.report.reopen": (a_forum_report("open"), "staff", None),
    "staff.grant": (a_staff_grant, "owner", None),
    "staff.revoke": (a_staff_revoke, "owner", True),
}


def expected_confirm(action: str, target: str, form: dict) -> str | None:
    c = ACTIONS[action][2]
    if c is True:
        return target
    if c == "hold":
        return "HOLD" if _feature_on(form) else "RELEASE"
    return c


def run_action(user: dict, form: dict) -> tuple[bool, str]:
    """Check role and confirm, run, audit. (ok, message)."""
    action = str(form.get("action") or "")
    target = str(form.get("target") or "")[:120]
    if action not in ACTIONS:
        return False, "Unknown action."
    fn, need, _ = ACTIONS[action]
    if need == "owner" and user["role"] != "owner":
        audit(user, action, target, None, None, ok=False, note="owner only")
        return False, "Only the owner can do that."
    want = expected_confirm(action, target, form)
    if want is not None and str(form.get("confirm") or "").strip() != want:
        audit(user, action, target, None, None, ok=False, note="confirm text did not match")
        return False, f"Type {want} to confirm."
    try:
        before, after = fn(user, target, form)
    except Refused as r:
        audit(user, action, target, None, None, ok=False, note=str(r))
        return False, str(r)
    except OSError as ex:
        log.exception("admin %s failed", action)
        audit(user, action, target, None, None, ok=False, note="could not write: " + str(ex)[:100])
        return False, "Could not save (is the data folder writable?)."
    audit(user, action, target, before, after)
    return True, "Done: " + action.replace(".", " ") + (" " + target if target and target != "new" else "") + "."


# ----------------------------------------------------------------------------------------------
# Routing (wrath_portal.PageHandler calls match/get/post)
# ----------------------------------------------------------------------------------------------

FEEDS = {"/wrath/leyline/channel.json", "/wrath/leyline/news.json", "/wrath/leyline/realm-overrides.json"}
FLAGS_FEED = "/wrath/leyline/flags.json"   # served here only while stream/leyline_net.py is not in the portal
_MOD_PAGE = re.compile(r"^/wrath/admin/catalog/mod/([a-z][a-z0-9-]{1,31})$")


def match(path: str) -> bool:
    return (path == "/wrath/admin" or path.startswith("/wrath/admin/") or path in FEEDS
            or (path == FLAGS_FEED and _ln() is None))


def feed(path: str) -> bytes:
    if path.endswith("/flags.json"):
        doc = flags_doc()
    elif path.endswith("/channel.json"):
        doc = channel_doc()
    elif path.endswith("/news.json"):
        d = news_doc()
        doc = {"format": 1, "updated_at": d["updated_at"],
               "posts": [{k: p[k] for k in ("id", "date", "tag", "title", "items") if k in p} for p in d["posts"] if not p.get("hidden")][:20]}
    else:
        ov = realm_overrides()
        doc = {"format": 1, "updated_at": _read_json(_apath("realm-overrides.json"), {}).get("updated_at"),
               "hidden": sorted(k for k, v in ov.items() if v.get("hidden")),
               "official": sorted(k for k, v in ov.items() if v.get("official") and not v.get("hidden")),
               "featured": sorted(k for k, v in ov.items() if v.get("featured") and not v.get("hidden")),
               "verified": sorted(k for k, v in ov.items() if v.get("verified") and not v.get("hidden"))}
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def get(h, path: str, query: dict) -> None:
    if path in FEEDS or path == FLAGS_FEED:
        lim = P("browse_limit")
        if lim is not None and not lim.hit(h.ip(), 600):
            h.send(429, b'{"error":"too many requests"}\n', "application/json")
            return
        h.send(200, feed(path), "application/json; charset=utf-8",
               headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60"})
        return
    user = who(h, path)
    if user is None:
        return
    if not limits.hit("get:" + user["account"], PAGES_PER_MIN):
        h.send(429, page_simple("Slow down", "Too many pages in a minute."), headers=NOINDEX)
        return
    tab = path[len("/wrath/admin/"):] if path.startswith("/wrath/admin/") else ""
    status = 200
    if tab == "":
        title, body = "Dashboard", dashboard(user)
    elif tab == "catalog":
        title, body = "Catalog", catalog_page(user)
    elif _MOD_PAGE.match(path):
        title, (status, body), tab = "Mod", mod_page(user, _MOD_PAGE.match(path).group(1)), "catalog"
    elif tab == "workshop":
        title, body = "Workshop", workshop_page(user, query)
    elif tab == "hub":
        title, body = "Community index", hub_page(user)
    elif tab == "realms":
        title, body = "Realms", realms_page(user)
    elif tab == "releases":
        title, body = "Releases", releases_page(user)
    elif tab == "flags":
        title, body = "Flags", flags_page(user)
    elif tab == "themes":
        title, body = "Themes", themes_page(user)
    elif tab == "reports":
        title, body = "Reports", reports_page(user, query)
    elif tab == "forum":
        title, body = "Forum", forum_page(user, query)
    elif tab == "health":
        title, body = "Health", health_page(user)
    elif tab == "staff":
        title, body = "Staff", staff_page(user)
    elif tab == "audit":
        title, body = "Audit", audit_page(user, query)
    else:
        status, title, body = 404, "Not found", '<section class="ly-panel"><h2>Not found</h2></section>'
    nonce = secrets.token_urlsafe(16)
    h.send(status, shell(user, tab, title, body, nonce, query), nonce=nonce, headers=NOINDEX)


def read_form(h) -> dict | None:
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > MAX_FORM:
        return None
    if h.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
        return None
    try:
        q = urllib.parse.parse_qs(h.rfile.read(n).decode("utf-8"), keep_blank_values=True, max_num_fields=30)
    except (UnicodeDecodeError, ValueError):
        return None
    return {k: v[0] for k, v in q.items()}


def _back(form: dict) -> str:
    b = str(form.get("back") or "/wrath/admin")
    if not re.fullmatch(r"/wrath/admin(/[a-z0-9/-]*)?(\?[a-z]+=[a-z]+)?", b):
        b = "/wrath/admin"
    return b


def post(h, path: str) -> None:
    if path != "/wrath/admin/act":
        h.send(405, b"method not allowed\n", "text/plain", headers=NOINDEX)
        return
    origin = h.headers.get("Origin", "")
    host = P("PUBLIC_HOST") or "play.openvanilla.app"
    if origin and origin != f"https://{host}" and not (origin == "null" and h.headers.get("Sec-Fetch-Site", "") == "same-origin"):
        h.send(403, page_simple("Refused", "That form came from another site."), headers=NOINDEX)
        return
    form = read_form(h)
    if form is None:
        h.send(400, page_simple("Refused", "That form didn't arrive in one piece."), headers=NOINDEX)
        return
    user = who(h, path)
    if user is None:
        return
    if not limits.hit("post:" + user["account"], POSTS_PER_MIN):
        h.send(429, page_simple("Slow down", f"At most {POSTS_PER_MIN} changes a minute."), headers=NOINDEX)
        return
    if not user["session"] or not hmac.compare_digest(str(form.get("csrf") or ""), csrf_token(user["session"], user["account"])):
        audit(user, str(form.get("action") or "")[:40], str(form.get("target") or "")[:120], None, None, ok=False,
              note="CSRF token missing or wrong")
        h.send(403, page_simple("Refused", "That form is out of date. Go back, reload the page and try again."), headers=NOINDEX)
        return
    ok, msg = run_action(user, form)
    back = _back(form)
    sep = "&" if "?" in back else "?"
    h.send_response(303)
    kind, text = ("ok" if ok else "err"), msg[:300]
    h.send_header("Location", back + sep + kind + "=" + urllib.parse.quote(text) + "&m=" + flash_sig(kind, text))
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Robots-Tag", "noindex, nofollow")
    h.send_header("Content-Length", "0")
    h.end_headers()
