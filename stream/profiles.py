"""Leyline profiles and the unified sign-in for the Wrath portal (stream/wrath_portal.py hooks it in).

Owner, 2026-10-30: "Allow manage account within launcher, bio profile pic etc basic stuff, smooth out the login process,
incorporate hero key gmail and discord signin in sign in phases on site and launcher".

Who signs in, and how: the website's own sign-in (the Rust site on this host, /login, /auth/<provider>/start, /key)
still issues the one session cookie (wr_session); nothing here makes accounts, sees passwords or reads its database.
This module adds Leyline's own sign-in page in front of it, in phases:

    1. /wrath/signin?next=<path>       one chooser: Hero Key, Google, Discord (a button shows only when the website offers
                                       that way: its /login page is read every few minutes, see methods())
       /wrath/signin/go/<way>?next=    remembers where to come back to (our ly_next cookie, and the website's own wr_next
                                       pointing at step 2) and hands over to the website's flow for that way
    2. /wrath/signin/welcome           first time only: "make your profile" (display name, picture, optional bio), Skip
                                       works; a launcher link (/wrath/link) skips it (the launcher asks itself)
    3. back to <next>
    /wrath/profile                     manage your profile on the website: picture, name, bio, sign-in ways, sign out

Profiles: the display name and #tag are stream/social.py's (one name everywhere, its rules: social.name_error, which
refuses the game and company names). Here: a bio (plain text, up to BIO_MAX, the word filter's words starred out, game
and company names replaced like forum posts) and a picture: one of PRESETS (original shapes drawn here, no game art) or
the default (your initial on a colour). Uploads and the Google/Discord picture are not offered: the portal image has no
image library to re-encode uploads safely, and the website's /api/me does not pass the provider's picture on
(docs/SIGN-IN.md says what each would need).

    GET  /wrath/avatar/p/<preset>.svg   a preset (cached a week)
    GET  /wrath/avatar/u/<pid>.svg      a player's picture by their public id (?v=<n> changes with it: cached a day;
                                        without v: five minutes)
    JSON for the launcher and the page's own script, under /wrath/api/social (stream/social.py's auth: a launcher token
    or the cookie with X-Leyline-CSRF):
    GET  me                       ... me.profile {bio, avatar, avatar_url, setup}, avatars [{id, name, url}], ways
    POST profile {name?, bio?, avatar?, setup?}
    GET  ways                     (no sign-in) {herokey, google, discord}: which sign-in buttons to show

The admin console's Profiles tab (stream/admin.py) resets a picture, bio or name; every change (the player's own too) is
kept in profile_history, nothing is deleted. Storage: SQLite in $WU_PORTAL_DATA (default /data), profiles.sqlite3.
Settings: WU_PROFILES=0 (off). Standard library only.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request

try:
    import sqlite3
except ImportError:   # an image without it: the portal runs without profiles
    sqlite3 = None

log = logging.getLogger("wrath-portal.profiles")

SIGNIN = "/wrath/signin"
WELCOME = SIGNIN + "/welcome"
PROFILE = "/wrath/profile"
AVATAR = "/wrath/avatar"
LINK_PAGE = "/wrath/link"
BIO_MAX = 300
FORM_MAX = 4096
NEXT_COOKIE = "ly_next"
WAYS = ("herokey", "google", "discord")
WAY_START = {"herokey": "/key", "google": "/auth/google/start", "discord": "/auth/discord/start"}
WAYS_TTL, WAYS_TTL_FAIL = 300, 60
PID_RE = re.compile(r"^[a-z0-9]{10}$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")

# The preset pictures: (id, name, background from, to, the shape in a 24-unit box). Original simple shapes.
PRESETS = (
    ("star", "Star", "#5b8def", "#8b6cf0", '<path d="M12 3.5l2.6 5.6 6.1.7-4.5 4.2 1.2 6-5.4-3-5.4 3 1.2-6L3.3 9.8l6.1-.7z"/>'),
    ("moon", "Moon", "#2f3f8f", "#6c5ce7", '<path d="M15.5 3.6a8.6 8.6 0 1 0 4.9 14.6A7 7 0 0 1 15.5 3.6z"/>'),
    ("flame", "Flame", "#f0743e", "#d6336c", '<path d="M12 2.8c.6 3.4 4.9 5.3 4.9 10.1a4.9 4.9 0 0 1-9.8 0c0-2.3 1.2-3.7 2.3-4.8.2 1.5.9 2.6 2 3.1-.6-3.1-.1-5.9.6-8.4z"/>'),
    ("leaf", "Leaf", "#2fb37a", "#167a6b", '<path d="M19.6 4.4C10.2 4 4.4 8.6 4.6 15.4c0 1.4.4 2.7 1 3.8L4 20.8l1 1 1.7-1.6c1 .6 2.2.9 3.5.9 6.4 0 9.8-6.3 9.4-16.7zM9 16.6c1.9-3.3 4.4-5.8 7.6-7.6-2.6 2.4-4.6 5-6 8z"/>'),
    ("peak", "Peak", "#3a7bd5", "#00a3a3", '<path d="M2.5 19.5l6.6-11 3.4 5.4 2.2-3.2 6.8 8.8z"/><path d="M9.1 8.5l1.8 2.9-1.8 1-1.6-1.2z" opacity=".55"/>'),
    ("gem", "Gem", "#7d5fff", "#c056e0", '<path d="M7 4h10l4 5-9 11L3 9z"/><path d="M3 9h18M9 4l3 16M15 4l-3 16" fill="none" stroke="rgba(0,0,0,.25)" stroke-width="1"/>'),
    ("sun", "Sun", "#f5a623", "#f06543", '<circle cx="12" cy="12" r="4.4"/><path d="M12 1.8v3.4M12 18.8v3.4M1.8 12h3.4M18.8 12h3.4M4.8 4.8l2.4 2.4M16.8 16.8l2.4 2.4M4.8 19.2l2.4-2.4M16.8 7.2l2.4-2.4" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/>'),
    ("bolt", "Bolt", "#f7b733", "#fc4a1a", '<path d="M13.5 2.5L5 13.4h5.6l-1.2 8.1 8.6-11h-5.7z"/>'),
    ("wave", "Wave", "#1fa2ff", "#12d8fa", '<path d="M2 14c2.5 0 2.5-3 5-3s2.5 3 5 3 2.5-3 5-3 2.5 3 5 3v5H2z"/><path d="M2 9.5c2.5 0 2.5-3 5-3s2.5 3 5 3 2.5-3 5-3 2.5 3 5 3" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" opacity=".7"/>'),
    ("shield", "Shield", "#4b6cb7", "#182848", '<path d="M12 2.5l8 3v6.1c0 4.8-3.3 8.6-8 10-4.7-1.4-8-5.2-8-10V5.5z"/><path d="M12 6.5v11" stroke="rgba(0,0,0,.25)" stroke-width="1.5"/>'),
    ("crown", "Crown", "#c99a2e", "#8e5a12", '<path d="M3 8l4.5 4L12 5l4.5 7L21 8l-1.8 10H4.8z"/><rect x="4.8" y="18.6" width="14.4" height="2" rx=".6"/>'),
    ("tree", "Tree", "#38a169", "#22543d", '<path d="M12 2.5l5.5 7.2h-2.9l4.4 5.8H13.4V21h-2.8v-5.5H5l4.4-5.8H6.5z"/>'),
)
PRESET = {p[0]: p for p in PRESETS}
INITIAL_COLOURS = (("#5b8def", "#8b6cf0"), ("#2fb37a", "#167a6b"), ("#f0743e", "#d6336c"), ("#7d5fff", "#c056e0"),
                   ("#1fa2ff", "#3a7bd5"), ("#c99a2e", "#8e5a12"), ("#e0567a", "#8b6cf0"), ("#00a3a3", "#2f3f8f"))


def _now() -> float:
    return time.time()


def preset_svg(pid: str) -> bytes:
    _id, name, a, b, shape = PRESET[pid]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256" role="img" aria-label="{name}">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/>'
            f'</linearGradient></defs><rect width="64" height="64" fill="url(#g)"/>'
            f'<g transform="translate(14 14) scale(1.5)" fill="#fff">{shape}</g></svg>').encode("utf-8")


def initial_svg(name: str, seed: str) -> bytes:
    ch = next((c for c in (name or "") if c.isalnum()), "?").upper()
    a, b = INITIAL_COLOURS[int(hashlib.sha256(seed.encode()).hexdigest()[:4], 16) % len(INITIAL_COLOURS)]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256" role="img">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/>'
            f'</linearGradient></defs><rect width="64" height="64" fill="url(#g)"/>'
            f'<text x="32" y="42" text-anchor="middle" font-family="system-ui,Segoe UI,Arial,sans-serif" font-size="30" '
            f'font-weight="700" fill="#fff">{html.escape(ch)}</text></svg>').encode("utf-8")


def clean_bio(v) -> str:
    """Plain text, at most BIO_MAX characters, at most 4 line breaks; the word filter's words starred out and game and company
    names replaced (forum.unbrand / social.mask when those modules are here)."""
    if not isinstance(v, str):
        return ""
    s = CTRL_RE.sub(" ", v.replace("\r\n", "\n").replace("\r", "\n"))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", "\n".join(line.strip() for line in s.split("\n"))).strip()
    while s.count("\n") > 4:
        s = s[::-1].replace("\n", " ", 1)[::-1]
    s = s[:BIO_MAX]
    fm, soc = P("forum"), P("social")
    try:
        if fm is not None:
            s = fm.unbrand(s)
        elif soc is not None:
            s = soc.BRAND_RE.sub("the game", s)
        if soc is not None:
            s = soc.mask(s)
    except Exception:   # noqa: BLE001
        pass
    return s[:BIO_MAX]


SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  acct TEXT PRIMARY KEY, bio TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '', setup INTEGER NOT NULL DEFAULT 0,
  ver INTEGER NOT NULL DEFAULT 1, updated INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS profile_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, acct TEXT NOT NULL, field TEXT NOT NULL,
  old TEXT NOT NULL, new TEXT NOT NULL, by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS profile_history_acct ON profile_history (acct, id);
"""


class ProfileError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status, self.text = status, text


class Profiles:
    """The bio and picture store (the name and #tag stay in stream/social.py). Thread-safe (one connection, one lock)."""

    def __init__(self, data_dir: str | None = None, clock=_now, db_file: str | None = None):
        if sqlite3 is None:
            raise RuntimeError("sqlite3 is missing")
        self.dir = data_dir or os.environ.get("WU_PORTAL_DATA", "/data")
        self.path = db_file or os.path.join(self.dir, "profiles.sqlite3")
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.key = os.environ.get("WU_FORM_SECRET", "").encode() or secrets.token_bytes(32)

    def now(self) -> int:
        return int(self.clock())

    def one(self, sql: str, args=()):
        with self.lock:
            r = self.db.execute(sql, args).fetchall()
        return r[0] if r else None

    def q(self, sql: str, args=()) -> list:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def get(self, acct: str) -> dict:
        r = self.one("SELECT bio, avatar, setup, ver, updated FROM profiles WHERE acct = ?", (acct,))
        if not r:
            return {"acct": acct, "bio": "", "avatar": "", "setup": False, "ver": 1, "updated": 0}
        return {"acct": acct, "bio": r[0], "avatar": r[1], "setup": bool(r[2]), "ver": r[3], "updated": r[4]}

    def _hist(self, acct: str, field: str, old: str, new: str, by: str) -> None:
        self.db.execute("INSERT INTO profile_history (at, acct, field, old, new, by) VALUES (?,?,?,?,?,?)",
                        (self.now(), acct, field, old, new, by[:80]))

    def update(self, acct: str, bio=None, avatar=None, setup=None, by: str = "self") -> dict:
        """Change the bio and/or picture (None: unchanged) and/or the first-time flag. Every change goes in the history."""
        if avatar is not None and avatar != "" and avatar not in PRESET:
            raise ProfileError(400, "Pick one of the pictures.")
        if bio is not None:
            bio = clean_bio(bio)
        with self.lock:
            cur = self.get(acct)
            changed = False
            self.db.execute("BEGIN")
            try:
                self.db.execute("INSERT OR IGNORE INTO profiles (acct, updated) VALUES (?, ?)", (acct, self.now()))
                if bio is not None and bio != cur["bio"]:
                    self._hist(acct, "bio", cur["bio"], bio, by)
                    self.db.execute("UPDATE profiles SET bio = ? WHERE acct = ?", (bio, acct))
                    changed = True
                if avatar is not None and avatar != cur["avatar"]:
                    self._hist(acct, "avatar", cur["avatar"], avatar, by)
                    self.db.execute("UPDATE profiles SET avatar = ?, ver = ver + 1 WHERE acct = ?", (avatar, acct))
                    changed = True
                if setup is not None and bool(setup) != cur["setup"]:
                    self.db.execute("UPDATE profiles SET setup = ? WHERE acct = ?", (1 if setup else 0, acct))
                if changed:
                    self.db.execute("UPDATE profiles SET updated = ? WHERE acct = ?", (self.now(), acct))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return self.get(acct)

    def note_name(self, acct: str, old: str, new: str, by: str) -> None:
        """A name change (made in stream/social.py) goes in the same history; the default picture shows the new initial."""
        if old == new:
            return
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO profiles (acct, updated) VALUES (?, ?)", (acct, self.now()))
            self._hist(acct, "name", old, new, by)
            self.db.execute("UPDATE profiles SET ver = ver + 1, updated = ? WHERE acct = ?", (self.now(), acct))

    def history(self, acct: str, n: int = 20) -> list[dict]:
        return [{"id": r[0], "at": r[1], "field": r[2], "old": r[3], "new": r[4], "by": r[5]} for r in
                self.q("SELECT id, at, field, old, new, by FROM profile_history WHERE acct = ? ORDER BY id DESC LIMIT ?", (acct, n))]

    def recent(self, n: int = 60) -> list[str]:
        return [r[0] for r in self.q("SELECT acct FROM profiles ORDER BY updated DESC LIMIT ?", (n,))]


# ---------------------------------------------------------------------------------------------- the portal's side
_get = None
store: Profiles | None = None
_ways = {"at": -1e9, "ttl": 0, "doc": None}
_ways_lock = threading.Lock()
_lim: dict[str, list] = {}


def bind(getter) -> None:
    global _get
    _get = getter


def P(name):
    try:
        return _get(name) if _get else None
    except KeyError:
        return None


def setup() -> Profiles | None:
    global store
    if store is not None:
        return store
    if os.environ.get("WU_PROFILES", "1") == "0" or sqlite3 is None:
        return None
    try:
        store = Profiles()
    except Exception:   # noqa: BLE001: the rest of the portal runs without profiles
        log.exception("profiles: off (the store didn't open)")
        return None
    return store


def _soc():
    """stream/social.py's store (names, tags, public ids), or None."""
    soc = P("social")
    return getattr(soc, "store", None) if soc is not None else None


def match(path: str) -> bool:
    return path in (SIGNIN, PROFILE) or path.startswith(SIGNIN + "/") or path.startswith(AVATAR + "/")


def host() -> str:
    return P("PUBLIC_HOST") or "play.openvanilla.app"


def _hit(key: str, limit: int, seconds: float = 600) -> bool:
    t = time.monotonic()
    q = [x for x in _lim.get(key, []) if t - x < seconds]
    if len(q) >= limit:
        _lim[key] = q
        return False
    q.append(t)
    _lim[key] = q
    if len(_lim) > 20000:
        _lim.clear()
    return True


# ------------------------------------------------------------------ which ways the website offers
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _read_login() -> str:
    base = (P("PORTAL_URL") or "").rstrip("/")
    req = urllib.request.Request(base + "/login", headers={"Host": host(), "Accept": "text/html",
                                                           "User-Agent": "Leyline portal (sign-in ways)"})
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=6) as r:
        return r.read(400000).decode("utf-8", "replace")


def ways(force: bool = False) -> dict:
    """{herokey, google, discord}: what the website's own sign-in page offers right now (read every WAYS_TTL seconds; when it
    can't be read: the Hero Key and Google, as the website has offered for months, and no Discord)."""
    with _ways_lock:
        if not force and _ways["doc"] is not None and time.monotonic() - _ways["at"] < _ways["ttl"]:
            return dict(_ways["doc"])
    try:
        page = _read_login()
        doc = {"herokey": 'href="/key"' in page or "/auth/key" in page, "google": "/auth/google/start" in page,
               "discord": "/auth/discord/start" in page}
        ttl = WAYS_TTL
    except Exception as e:   # noqa: BLE001
        log.info("profiles: the sign-in page didn't answer (%s)", type(e).__name__)
        doc, ttl = {"herokey": True, "google": True, "discord": False}, WAYS_TTL_FAIL
    doc["herokey"] = True   # the Hero Key page is the website's own, always there
    with _ways_lock:
        _ways.update(at=time.monotonic(), ttl=ttl, doc=doc)
    return dict(doc)


# ------------------------------------------------------------------ who is signed in
def _session(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "wr_session":
            return v[:512]
    return ""


def _cookie(h, name: str) -> str:
    for part in h.headers.get("Cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return urllib.parse.unquote(v)
    return ""


def viewer(h) -> dict | None:
    """{acct, name, tag, pid, session, display} for the website session; None when signed out. Raises OSError when the
    website isn't answering."""
    soc = P("social")
    if soc is None or _soc() is None:
        raise OSError("social.py is off")
    who = soc.cookie_user(h)
    if who is None:
        return None
    p = _soc().ensure(who[0], who[1])
    return {"acct": who[0], "name": p["name"], "tag": p["tag"], "pid": p["pid"], "display": who[1],
            "session": _session(h.headers.get("Cookie", ""))}


def safe_next(v) -> str:
    """A path on our own pages to come back to (/wrath...), else /wrath. Never another host, never the sign-in itself."""
    v = str(v or "")
    if (not v.startswith("/wrath") or v.startswith("//") or "\\" in v or len(v) > 300 or any(ord(c) < 32 for c in v)
            or v.startswith(SIGNIN) or not re.match(r"^/wrath(?:[/?#]|$)", v)):
        return "/wrath"
    return v


def signin_url(nxt: str = "/wrath") -> str:
    return SIGNIN + "?next=" + urllib.parse.quote(safe_next(nxt), safe="")


# ------------------------------------------------------------------ profiles as others see them
def avatar_url(acct: str, absolute: bool = False) -> str:
    """The picture's address for an account (by its public id), or "" without the social store."""
    soc = _soc()
    if soc is None or store is None:
        return ""
    p = soc.profile(acct)
    if not p:
        return ""
    u = f"{AVATAR}/u/{p['pid']}.svg?v={store.get(acct)['ver']}"
    return f"https://{host()}{u}" if absolute else u


def avatars(absolute: bool = False) -> list[dict]:
    pre = f"https://{host()}" if absolute else ""
    return [{"id": p[0], "name": p[1], "url": f"{pre}{AVATAR}/p/{p[0]}.svg"} for p in PRESETS]


def public(acct: str, absolute: bool = True) -> dict:
    """What GET .../social/me adds: me.profile, plus the presets and the sign-in ways."""
    pr = store.get(acct) if store is not None else {"bio": "", "avatar": "", "setup": False}
    return {"profile": {"bio": pr["bio"], "avatar": pr["avatar"], "avatar_url": avatar_url(acct, absolute), "setup": pr["setup"]},
            "avatars": avatars(absolute), "ways": ways(), "manage_url": f"https://{host()}{PROFILE}"}


def save(acct: str, doc: dict, by: str = "self") -> dict:
    """POST .../social/profile's bio, avatar and setup (the name is social.py's). Raises ProfileError."""
    if store is None:
        raise ProfileError(404, "Profiles are off here.")
    bio = doc.get("bio") if "bio" in doc else None
    if bio is not None and not isinstance(bio, str):
        raise ProfileError(400, "The bio is text.")
    if isinstance(bio, str) and len(bio) > BIO_MAX * 2:
        raise ProfileError(400, f"Bios are up to {BIO_MAX} characters.")
    av = doc.get("avatar") if "avatar" in doc else None
    if av is not None and not isinstance(av, str):
        raise ProfileError(400, "Pick one of the pictures.")
    setup_flag = doc.get("setup") if "setup" in doc else None
    if setup_flag is not None and not isinstance(setup_flag, bool):
        raise ProfileError(400, "Bad request.")
    return store.update(acct, bio=bio, avatar=av, setup=setup_flag, by=by)


SQUASHED_BRANDS = ("worldofwarcraft", "warcraft", "lichking", "blizzard")


def name_problem(name) -> str:
    """Why a display name is refused ("" when it's fine): social.py's rules, plus the game and company names hidden
    behind separators or run into other words ("Lich_King", "War.craft", "WoWAlice")."""
    mod = P("social")
    err = mod.name_error(name) if mod is not None else ("" if isinstance(name, str) else "Bad name.")
    if err:
        return err
    flat = re.sub(r"[^a-z]", "", name.lower())
    if "WoW" in name or re.search(r"(?i)(?:^|[^a-z])wow(?:[^a-z]|$)", name) or any(b in flat for b in SQUASHED_BRANDS):
        return "Pick another name."
    return ""


def set_name(acct: str, name, by: str = "self") -> dict:
    """The display name through social.py's rules (and name_problem's); the change is noted in the profile history."""
    soc, mod = _soc(), P("social")
    err = name_problem(name)
    if err:
        raise ProfileError(400, err)
    old = soc.ensure(acct)["name"]
    try:
        p = soc.set_profile(acct, {"name": name})
    except mod.SocialError as e:
        raise ProfileError(e.status, e.text)
    if store is not None:
        store.note_name(acct, old, p["name"], by)
    return p


def admin_reset(acct: str, field: str, by: str) -> tuple[dict, dict]:
    """The admin console's resets (stream/admin.py): picture or bio back to empty, or the name to "Player"."""
    soc = _soc()
    if store is None or soc is None or not soc.profile(acct):
        raise ProfileError(404, "No such profile.")
    cur = store.get(acct)
    if field == "avatar":
        store.update(acct, avatar="", by=by)
        return {"avatar": cur["avatar"]}, {"avatar": ""}
    if field == "bio":
        store.update(acct, bio="", by=by)
        return {"bio": cur["bio"]}, {"bio": ""}
    if field == "name":
        old = soc.profile(acct)["name"]
        p = set_name(acct, "Player", by)
        return {"name": old}, {"name": p["name"], "tag": p["tag"]}
    raise ProfileError(400, "Unknown field.")


# ------------------------------------------------------------------ pages
CSS = """
.pf{max-width:620px;margin:0 auto;display:grid;gap:16px}
.pf-card{border:1px solid var(--lk-border,rgba(255,255,255,.1));border-radius:var(--lk-r,14px);background:var(--lk-surface,#151924);padding:22px}
.pf h1{margin:0 0 4px;font-size:clamp(22px,4vw,28px);font-weight:800}
.pf p{margin:0;color:var(--lk-text-2,#b9c0d0);line-height:1.55}
.pf-steps{display:flex;gap:6px;margin:0 0 14px;padding:0;list-style:none;font-size:12.5px;color:var(--lk-muted,#8a93a6)}
.pf-steps li{display:flex;align-items:center;gap:6px;flex:1;min-width:0}
.pf-steps li::before{content:attr(data-n);display:grid;place-items:center;flex:none;width:22px;height:22px;border-radius:50%;
border:1px solid var(--lk-border-strong,rgba(255,255,255,.2));font-weight:700}
.pf-steps li.on{color:var(--lk-text,#fff);font-weight:650}.pf-steps li.on::before{background:var(--lk-accent,#5b8def);border-color:transparent;color:#fff}
.pf-steps li.done::before{content:"\\2713";background:var(--lk-accent-soft,rgba(91,141,239,.16));border-color:transparent;color:var(--lk-accent-strong,#7aa3f5)}
.pf-ways{display:grid;gap:10px;margin:18px 0 8px}
.pf-way{display:flex;align-items:center;justify-content:center;gap:10px;min-height:48px;padding:0 18px;border-radius:var(--lk-r-sm,10px);
font:inherit;font-weight:700;font-size:15.5px;text-decoration:none;cursor:pointer;border:1px solid var(--lk-border-strong,rgba(255,255,255,.2));
background:var(--lk-surface-2,#1b2030);color:var(--lk-text,#fff)!important}
.pf-way:hover{border-color:var(--lk-accent,#5b8def)}.pf-way svg{width:22px;height:22px;flex:none}
.pf-way.key{background:var(--lk-accent,#5b8def);border-color:transparent;color:#fff!important}.pf-way.key:hover{background:var(--lk-accent-strong,#7aa3f5)}
.pf-way.google{background:#fff;color:#1f1f1f!important;border-color:#dadce0}
.pf-way.discord{background:#5865f2;border-color:transparent;color:#fff!important}.pf-way.discord:hover{background:#4752c4}
.pf-fine{font-size:13px;color:var(--lk-muted,#8a93a6)!important}.pf-fine a{color:var(--lk-text-2,#b9c0d0)}
.pf-form{display:grid;gap:10px;margin-top:14px}
.pf-form label.l{font-weight:650;margin-top:6px}
.pf-form input[type=text],.pf-form textarea{width:100%;box-sizing:border-box;min-height:42px;padding:9px 12px;border-radius:var(--lk-r-sm,10px);
border:1px solid var(--lk-border-strong,rgba(255,255,255,.2));background:var(--lk-bg,#0d1017);color:var(--lk-text,#fff);font:inherit}
.pf-form textarea{min-height:96px;resize:vertical;line-height:1.5}
.pf-pics{display:grid;grid-template-columns:repeat(auto-fill,minmax(58px,1fr));gap:8px;margin:0;padding:0;border:0}
.pf-pics label{position:relative;display:block;cursor:pointer;border-radius:50%}
.pf-pics input{position:absolute;opacity:0;inset:0;margin:0}
.pf-pics img{display:block;width:100%;height:auto;aspect-ratio:1;border-radius:50%;border:3px solid transparent;box-sizing:border-box}
.pf-pics input:checked+img{border-color:var(--lk-accent-strong,#7aa3f5);box-shadow:0 0 0 2px var(--lk-bg,#0d1017) inset}
.pf-pics input:focus-visible+img{outline:2px solid var(--lk-accent-strong,#7aa3f5);outline-offset:2px}
.pf-acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
.pf-btn{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 18px;border-radius:var(--lk-r-sm,10px);border:0;
background:var(--lk-accent,#5b8def);color:#fff!important;font:inherit;font-weight:700;text-decoration:none;cursor:pointer}
.pf-btn:hover{background:var(--lk-accent-strong,#7aa3f5)}
.pf-btn.ghost{background:transparent;border:1px solid var(--lk-border-strong,rgba(255,255,255,.2));color:var(--lk-text,#fff)!important;font-weight:600}
.pf-me{display:flex;align-items:center;gap:14px}.pf-me img{width:64px;height:64px;border-radius:50%;flex:none}
.pf-me b{font-size:19px}.pf-me small{color:var(--lk-muted,#8a93a6);font-size:14px;margin-left:2px}
.pf-msg{margin:0;padding:10px 14px;border-radius:var(--lk-r-sm,10px);background:var(--lk-accent-soft,rgba(91,141,239,.16));border:1px solid var(--lk-accent,#5b8def)}
.pf-msg.err{background:rgba(255,127,118,.12);border-color:var(--lk-bad,#ff7f76)}
.pf-list{margin:10px 0 0;padding:0;list-style:none;display:grid;gap:8px}
.pf-list li{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:6px 12px;padding:10px 12px;border-radius:var(--lk-r-sm,10px);
background:var(--lk-surface-2,#1b2030)}
.pf-list a{color:var(--lk-accent-strong,#7aa3f5)}
.pf h2{margin:0 0 4px;font-size:15px;font-weight:750}
.pf-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
@media (max-width:520px){.pf-card{padding:16px}.pf-steps{font-size:11.5px}.pf-steps li span{display:none}.pf-steps li.on span{display:inline}}
"""

ICON = {
    "herokey": '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 14a3 3 0 1 1 0-6 3 3 0 0 1 0 6Zm5.65-4A6 6 0 1 0 12.65 14H15v3h3v-3h2v-4h-7.35Z"/></svg>',
    "google": '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>',
    "discord": '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M20.32 4.37A19.8 19.8 0 0 0 15.43 2.8a13.7 13.7 0 0 0-.63 1.29 18.4 18.4 0 0 0-5.6 0 13 13 0 0 0-.64-1.29 19.7 19.7 0 0 0-4.89 1.52C.56 9.04-.28 13.6.14 18.1a19.9 19.9 0 0 0 6.02 3.04c.49-.66.92-1.36 1.29-2.1a12.9 12.9 0 0 1-2.03-.97c.17-.13.34-.26.5-.39a14.2 14.2 0 0 0 12.16 0c.17.14.33.27.5.39-.65.38-1.33.71-2.04.97.37.74.8 1.44 1.29 2.1a19.8 19.8 0 0 0 6.03-3.04c.5-5.22-.84-9.74-3.54-13.73ZM8.02 15.33c-1.18 0-2.16-1.08-2.16-2.42 0-1.33.96-2.42 2.16-2.42 1.21 0 2.18 1.1 2.16 2.42 0 1.34-.96 2.42-2.16 2.42Zm7.97 0c-1.19 0-2.16-1.08-2.16-2.42 0-1.33.95-2.42 2.16-2.42 1.2 0 2.18 1.1 2.16 2.42 0 1.34-.95 2.42-2.16 2.42Z"/></svg>',
}
WAY_LABEL = {"herokey": "Sign in with your Hero Key", "google": "Continue with Google", "discord": "Continue with Discord"}


def _shell(h, title: str, inner: str, path: str, who=None, status: int = 200, cookies: list[str] | None = None) -> None:
    page = f'<div class="pf">{inner}</div>'
    body = None
    hub = P("hub_mod")
    if hub is not None and getattr(hub, "hub", None) is not None:
        try:
            hub._REQ.who = (who["acct"], who["name"]) if who else None
            body = hub.hub._shell(title, page, path, active="", css=CSS)
        except Exception:   # noqa: BLE001: the plain page then
            log.exception("profiles: the hub's page failed")
            body = None
    if body is None:
        shell = P("ly_shell")
        if shell is not None:
            try:
                body = shell(title, page, path, "", "", CSS, noindex=True)
            except Exception:   # noqa: BLE001
                body = None
    if body is None:
        body = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>{html.escape(title)}</title><style>{CSS}</style><main>{page}</main>").encode("utf-8")
    headers = {"X-Robots-Tag": "noindex, nofollow"}
    if cookies:
        _send_with_cookies(h, status, body, cookies, headers)
    else:
        h.send(status, body, headers=headers)


def _send_with_cookies(h, status: int, body: bytes, cookies: list[str], headers: dict) -> None:
    h.send_response(status)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    for c in cookies:
        h.send_header("Set-Cookie", c)
    for k, v in headers.items():
        h.send_header(k, v)
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("Referrer-Policy", "same-origin")
    h.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; "
                                             "frame-ancestors 'none'; base-uri 'none'")
    h.end_headers()
    h.wfile.write(body)


def _go(h, url: str, cookies: list[str] | None = None, status: int = 302) -> None:
    h.send_response(status)
    h.send_header("Location", url)
    for c in cookies or []:
        h.send_header("Set-Cookie", c)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Referrer-Policy", "same-origin")
    h.send_header("Content-Length", "0")
    h.end_headers()


def _cookie_str(name: str, value: str, path: str, max_age: int) -> str:
    return (f"{name}={urllib.parse.quote(value, safe='/')}; Path={path}; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax")


def form_token(who: dict, action: str) -> str:
    return hmac.new(store.key, f"profile|{who['session']}|{who['acct']}|{action}".encode(), hashlib.sha256).hexdigest()[:32]


def _same_site(h) -> bool:
    sfs = h.headers.get("Sec-Fetch-Site", "")
    if sfs == "cross-site":
        return False
    origin = h.headers.get("Origin", "")
    return not origin or origin == f"https://{host()}" or (origin == "null" and sfs == "same-origin")


def _steps(on: int) -> str:
    names = ("Sign in", "Your profile", "Play")
    return ('<ol class="pf-steps" aria-label="Steps">' + "".join(
        f'<li data-n="{i + 1}" class="{"on" if i + 1 == on else ("done" if i + 1 < on else "")}"'
        + (' aria-current="step"' if i + 1 == on else "") + f'><span>{n}</span></li>' for i, n in enumerate(names)) + "</ol>")


def page_signin(h, query: dict, note: str = "") -> None:
    e = html.escape
    nxt = safe_next((query.get("next") or [""])[0])
    try:
        who = viewer(h)
    except OSError:
        who = None
    if who and (query.get("switch") or [""])[0] != "1":
        pr = store.get(who["acct"])
        if not pr["setup"] and not nxt.startswith(LINK_PAGE):
            return _go(h, WELCOME, [_cookie_str(NEXT_COOKIE, nxt, "/wrath", 900)])
        return _go(h, nxt)
    w = ways()
    q = urllib.parse.quote(nxt, safe="")
    order = ("herokey", "google", "discord")
    btns = "".join(f'<a class="pf-way {"key" if k == "herokey" else k}" href="{SIGNIN}/go/{k}?next={q}">{ICON[k]}<span>{WAY_LABEL[k]}</span></a>'
                   for k in order if w.get(k))
    launcher = nxt.startswith(LINK_PAGE)
    msg = f'<p class="pf-msg err" role="alert">{e(note)}</p>' if note else ""
    # TODO(owner): the sign-in page's words
    lead = ("Sign in to link the Leyline launcher on this computer." if launcher else
            "One account for the website, the launcher and the forum.")
    inner = (f'<section class="pf-card">{_steps(1)}{msg}<h1>Sign in</h1><p>{e(lead)}</p>'
             f'<div class="pf-ways">{btns}</div>'
             '<p class="pf-fine">New here? Google' + (" or Discord" if w.get("discord") else "")
             + ' makes your free account in one step. A Hero Key signs you in to the account it belongs to. '
             "We never see your password.</p>"
             f'<p class="pf-fine" style="margin-top:8px"><a href="/login?next={q}">More ways to sign in</a></p></section>')
    _shell(h, "Sign in · Leyline", inner, SIGNIN, None)


def go_way(h, way: str, query: dict) -> None:
    nxt = safe_next((query.get("next") or [""])[0])
    if way not in WAYS or not ways().get(way):
        return _go(h, signin_url(nxt))
    if not _hit("go|" + h.ip(), 40):
        h.send(429, b"Too many sign-in attempts. Wait a few minutes.\n", "text/plain")
        return
    # Ours: where to come back to. The website's: where its own sign-in lands (it checks it is a path on this site).
    cookies = [_cookie_str(NEXT_COOKIE, nxt, "/wrath", 900), _cookie_str("wr_next", WELCOME, "/", 900)]
    _go(h, WAY_START[way], cookies)


def _pics(current: str, name: str, pid: str) -> str:
    e = html.escape
    out = [f'<label title="Your initial"><input type="radio" name="avatar" value=""{" checked" if not current else ""}>'
           f'<img src="{AVATAR}/i/{e(pid)}.svg" alt="Your initial" width="64" height="64"></label>']
    for p in PRESETS:
        out.append(f'<label title="{e(p[1])}"><input type="radio" name="avatar" value="{p[0]}"{" checked" if current == p[0] else ""}>'
                   f'<img src="{AVATAR}/p/{p[0]}.svg" alt="{e(p[1])}" width="64" height="64" loading="lazy"></label>')
    return '<fieldset class="pf-pics"><legend class="pf-sr">Picture</legend>' + "".join(out) + "</fieldset>"


def _profile_form(who: dict, action: str, post_to: str, submit: str, extra: str = "", form: dict | None = None) -> str:
    e = html.escape
    pr = store.get(who["acct"])
    form = form or {}
    name = form.get("name", who["name"])
    bio = form.get("bio", pr["bio"])
    av = form.get("avatar", pr["avatar"])
    return (f'<form class="pf-form" method="post" action="{post_to}"><input type="hidden" name="t" value="{form_token(who, action)}">'
            f'<label class="l" for="pf-n">Display name</label>'
            f'<input type="text" id="pf-n" name="name" value="{e(name)}" minlength="2" maxlength="24" required '
            'autocomplete="nickname" aria-describedby="pf-n-h">'
            f'<p class="pf-fine" id="pf-n-h">2 to 24 letters, digits, dots, dashes or underscores. Others see it as {e(who["name"])}#{e(who["tag"])}.</p>'
            f'<span class="l" style="font-weight:650;margin-top:6px">Picture</span>{_pics(av, who["name"], who["pid"])}'
            f'<label class="l" for="pf-b">Bio <span class="pf-fine">(optional)</span></label>'
            f'<textarea id="pf-b" name="bio" maxlength="{BIO_MAX}" placeholder="A line about you, your realm or what you play.">{e(bio)}</textarea>'
            f'<div class="pf-acts"><button class="pf-btn" type="submit" name="do" value="save">{e(submit)}</button>{extra}</div></form>')


def page_welcome(h, note: str = "", form: dict | None = None, status: int = 200) -> None:
    e = html.escape
    nxt = safe_next(_cookie(h, NEXT_COOKIE))
    try:
        who = viewer(h)
    except OSError:
        return _shell(h, "Sign in · Leyline", '<section class="pf-card"><h1>Sign in</h1><p>The website\'s sign-in isn\'t answering '
                      'right now. Try again shortly.</p></section>', SIGNIN, None, 503)
    if not who:
        return page_signin(h, {"next": [nxt]}, "The sign-in didn't finish. Try again.")
    if (store.get(who["acct"])["setup"] or nxt.startswith(LINK_PAGE)) and form is None and not note:   # the launcher asks itself
        return _go(h, nxt, [_cookie_str(NEXT_COOKIE, "", "/wrath", 0)])
    msg = f'<p class="pf-msg err" role="alert">{e(note)}</p>' if note else ""
    skip = '<button class="pf-btn ghost" type="submit" name="do" value="skip" formnovalidate>Skip for now</button>'
    # TODO(owner): the welcome words
    inner = (f'<section class="pf-card">{_steps(2)}{msg}<h1>Welcome, {e(who["name"])}</h1>'
             "<p>Pick how others see you on the forum and in the launcher. You can change it any time.</p>"
             + _profile_form(who, "welcome", WELCOME, "Save and continue", skip, form) + "</section>")
    _shell(h, "Your profile · Leyline", inner, WELCOME, who, status)


def page_profile(h, note: str = "", ok: str = "", form: dict | None = None, status: int = 200) -> None:
    e = html.escape
    try:
        who = viewer(h)
    except OSError:
        return _shell(h, "Profile · Leyline", '<section class="pf-card"><h1>Your profile</h1><p>The website\'s sign-in isn\'t '
                      'answering right now. Try again shortly.</p></section>', PROFILE, None, 503)
    if not who:
        return _go(h, signin_url(PROFILE))
    pr = store.get(who["acct"])
    w = ways()
    msg = (f'<p class="pf-msg err" role="alert">{e(note)}</p>' if note else "") + (f'<p class="pf-msg" role="status">{e(ok)}</p>' if ok else "")
    bio = f'<p style="margin-top:6px;white-space:pre-wrap">{e(pr["bio"])}</p>' if pr["bio"] else ""
    ways_rows = ['<li><span><b>Hero Key</b><br><span class="pf-fine">Your key: sign in on any device, and the launcher.</span></span>'
                 '<a href="/account/key">Manage your Hero Key</a></li>']
    if w.get("google"):
        ways_rows.append('<li><span><b>Google</b></span><a href="/auth/google/start?link=1">Link Google</a></li>')
    if w.get("discord"):
        ways_rows.append('<li><span><b>Discord</b></span><a href="/auth/discord/start?link=1">Link Discord</a></li>')
    ways_rows.append(f'<li><span><b>Leyline launcher</b><br><span class="pf-fine">The launchers signed in as you.</span></span>'
                     f'<a href="{LINK_PAGE}">Linked launchers</a></li>')
    inner = (f'<section class="pf-card"><div class="pf-me"><img src="{e(avatar_url(who["acct"]))}" alt="" width="64" height="64">'
             f'<div><b>{e(who["name"])}</b><small>#{e(who["tag"])}</small><p class="pf-fine">Signed in</p></div></div>{bio}</section>'
             f'{msg}<section class="pf-card"><h2>Edit your profile</h2>' + _profile_form(who, "profile", PROFILE, "Save", "", form)
             + '</section><section class="pf-card"><h2>Ways to sign in</h2><p class="pf-fine">Linking another way lets it sign in to '
             'this same account. Unlinking is done on the Hero Key page.</p>'
             f'<ul class="pf-list">{"".join(ways_rows)}</ul></section>'
             '<section class="pf-card"><h2>Sign out</h2><p class="pf-fine">Signs this browser out. Your launcher stays signed in '
             'until you sign out there or revoke it on Linked launchers.</p>'
             '<form method="post" action="/logout" class="pf-acts"><button class="pf-btn ghost" type="submit">Sign out</button></form></section>')
    _shell(h, "Your profile · Leyline", inner, PROFILE, who, status)


# ------------------------------------------------------------------ avatars
def _svg(h, body: bytes, max_age: int) -> None:
    etag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
    if h.headers.get("If-None-Match", "") == etag:
        h.send_response(304)
        h.send_header("ETag", etag)
        h.send_header("Cache-Control", f"public, max-age={max_age}")
        h.end_headers()
        return
    h.send_response(200)
    h.send_header("Content-Type", "image/svg+xml")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", f"public, max-age={max_age}")
    h.send_header("ETag", etag)
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
    h.send_header("Cross-Origin-Resource-Policy", "cross-origin")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    if h.command != "HEAD":
        h.wfile.write(body)


def serve_avatar(h, sub: str, query: dict) -> None:
    m = re.fullmatch(r"p/([a-z]{2,12})\.svg", sub)
    if m and m.group(1) in PRESET:
        return _svg(h, preset_svg(m.group(1)), 604800)
    m = re.fullmatch(r"([ui])/([a-z0-9]{10})\.svg", sub)
    soc = _soc()
    if m and soc is not None:
        acct = soc.by_pid(m.group(2))
        if acct:
            p = soc.profile(acct)
            av = store.get(acct)["avatar"] if (store is not None and m.group(1) == "u") else ""
            body = preset_svg(av) if av in PRESET else initial_svg(p["name"], p["pid"])
            return _svg(h, body, 86400 if (query.get("v") and m.group(1) == "u") else 300)
    h.send(404, b"not found\n", "text/plain")


# ------------------------------------------------------------------ routing
def get(h, path: str, query: dict) -> None:
    if store is None:
        return h.send(404, b"not found\n", "text/plain")
    if path.startswith(AVATAR + "/"):
        return serve_avatar(h, path[len(AVATAR) + 1:], query)
    lim = P("browse_limit")
    if lim is not None and not lim.hit(h.ip(), 600):
        return h.send(429, b"too many requests\n", "text/plain")
    if path == SIGNIN:
        return page_signin(h, query)
    if path == WELCOME:
        return page_welcome(h)
    m = re.fullmatch(re.escape(SIGNIN) + r"/go/([a-z]{3,10})", path)
    if m:
        return go_way(h, m.group(1), query)
    if path == PROFILE:
        ok = {"1": "Saved."}.get((query.get("saved") or [""])[0], "")
        return page_profile(h, ok=ok)
    h.send(404, b"not found\n", "text/plain")


def _read_form(h) -> dict | None:
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > FORM_MAX:
        return None
    try:
        q = urllib.parse.parse_qs(h.rfile.read(n).decode("utf-8"), keep_blank_values=True, max_num_fields=8)
    except (UnicodeDecodeError, ValueError):
        return None
    return {k: v[0] for k, v in q.items()}


def _apply(who: dict, form: dict) -> str:
    """Save the profile form; "" or the reason it was refused."""
    if form.get("avatar", "") not in ("",) + tuple(PRESET):
        return "Pick one of the pictures."
    try:
        if form.get("name", who["name"]) != who["name"]:
            p = set_name(who["acct"], form.get("name"))
            who["name"], who["tag"] = p["name"], p["tag"]
            mod = P("social")
            if mod is not None:
                mod._who_cache.clear()
        save(who["acct"], {"bio": form.get("bio", ""), "avatar": form.get("avatar", ""), "setup": True})
    except ProfileError as ex:
        return ex.text
    return ""


def post(h, path: str) -> None:
    form = _read_form(h)   # read first, so a refusal never resets the connection under the sender
    if store is None or path not in (WELCOME, PROFILE):
        return h.send(405, b"method not allowed\n", "text/plain")
    if not _same_site(h):
        return h.send(403, b"That form came from another site.\n", "text/plain")
    if form is None:
        return h.send(400, b"That form didn't arrive in one piece.\n", "text/plain")
    try:
        who = viewer(h)
    except OSError:
        return h.send(503, b"The website's sign-in isn't answering right now.\n", "text/plain")
    if not who:
        return _go(h, signin_url(PROFILE if path == PROFILE else "/wrath"), status=303)
    if not _hit("save|" + who["acct"], 30):
        return h.send(429, b"Too many changes. Wait a few minutes.\n", "text/plain")
    action = "welcome" if path == WELCOME else "profile"
    if not hmac.compare_digest(form.get("t", ""), form_token(who, action)):
        return (page_welcome if path == WELCOME else page_profile)(h, "That form timed out. Save it again.", form=form, status=403)
    if path == WELCOME:
        nxt = safe_next(_cookie(h, NEXT_COOKIE))
        if form.get("do") == "skip":
            store.update(who["acct"], setup=True)
        else:
            err = _apply(who, form)
            if err:
                return page_welcome(h, err, form, 400)
        return _go(h, nxt, [_cookie_str(NEXT_COOKIE, "", "/wrath", 0)], status=303)
    err = _apply(who, form)
    if err:
        return page_profile(h, err, form=form, status=400)
    _go(h, PROFILE + "?saved=1", status=303)
