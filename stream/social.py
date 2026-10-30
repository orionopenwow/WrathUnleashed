"""Leyline friends and messages for the Wrath portal (stream/wrath_portal.py hooks it in).

Who is who: a Leyline account is the player's game account (one per website account, e.g. WR000123: the
website's sign-in hands it out through /api/play, exactly as stream/hostflow.py uses it). No new accounts,
emails or passwords. Friends see a chosen name (default: the website's display name, or the first character
the realm saw) with a 4-digit tag ("Orion#4821"), and the main character when one is set.

Three ways in, one store:
  the browser   the website session cookie (wr_session, checked through /api/me and /api/play, cached 60 s);
                POSTs carry X-Leyline-CSRF (from GET .../me) and must not be cross-site
  the launcher  a revocable session token from a device-code sign-in (POST .../device/start, the player
                approves the code at /wrath/link in their own browser, signed in with the website's sign-in,
                then POST .../device/poll hands the token over once). Sent as "Authorization: Bearer <token>".
                Only sha256(token) is stored; /wrath/link lists the linked launchers with a Revoke button
  the realm     ov_social.lua (realm/custom/lua_scripts) over AzerothCore SOAP, the same console the portal already
                uses for accounts: this module polls "ovsocial pull" every few seconds for logins, logouts,
                .lm messages and .lf actions, and sends "ovsocial msg|tell|fr" back. No new ports. The realm stamps
                the sender (the logged-in character's own account), never the client

The JSON API, under /wrath/api/social (Caddy sends /wrath* here; /api/* belongs to the website's own service):
    GET  me                       {me, csrf}               (csrf only for cookie sign-in)
    GET  state                    {v, me, friends, incoming, outgoing, blocked}
    GET  events?since=<v>         waits up to 25 s for a change, then the state ({v, same: true} when none)
    GET  thread?with=<pid>[&before=<id>]   {messages: [{id, mine, text, at, via}]} (50 at a time, oldest first)
    POST profile  {name?, main?, show_main?, offline?}
    POST request  {to}             "Name#1234", a unique name, or a character name seen on the realm
    POST accept|decline|remove|unblock {pid};  POST block {pid} or {to}
    POST send     {to: pid, text}
    POST read     {with: pid}
    POST report   {pid, reason, note?}   the last 20 messages of that thread go with it, for the moderators
    POST device/start            {device_code, user_code, verify_url, interval, expires_in}  (no sign-in)
    POST device/poll {device_code}  {status: pending|ok|denied|expired, token?}
    POST token/revoke            the launcher signs itself out (Bearer)
  GET/POST /wrath/link           the approval page (and the list of linked launchers, with Revoke)

Privacy: presence only between accepted friends (both said yes); "appear offline" shows you offline to
everyone; a block hides everything both ways (friendship and requests removed, no messages, no presence, no
lookups). Bots (RNDBOT accounts, IsBot on the realm) never appear. Message bodies are never logged.

Storage: SQLite in $WU_PORTAL_DATA (default /data, the portal's one writable mount), social.sqlite3 (stdlib
sqlite3). Messages are kept 30 days and at most 500 per conversation (WU_SOCIAL_KEEP_DAYS, WU_SOCIAL_THREAD_MAX).

The report queue (the admin console reads it): table social_reports (see docs/SOCIAL.md), or in Python
Social.reports(status) and Social.resolve_report(id, by, outcome).

Settings (environment): WU_PORTAL_DATA, WU_SOCIAL=0 (off), WU_SOCIAL_POLL (seconds, default 3),
WU_SOCIAL_KEEP_DAYS (30), WU_SOCIAL_THREAD_MAX (500), WU_SOCIAL_MSG_PER_MIN (20), WU_SOCIAL_MSG_PER_DAY (600).
Standard library only.
"""
from __future__ import annotations

import collections
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

try:
    import sqlite3
except ImportError:   # an image without it: the portal runs without friends (the loader catches this)
    sqlite3 = None

log = logging.getLogger("wrath-portal.social")

API = "/wrath/api/social"
LINK_PAGE = "/wrath/link"
NAME_MIN, NAME_MAX = 2, 24
TEXT_MAX = 500
REASONS = ("spam", "harassment", "hate", "cheating", "other")
NOTE_MAX = 300
PAGE = 50
LONGPOLL = 25
LAUNCHER_ONLINE = 75          # seconds since the launcher's last call: still "online in the launcher"
DEVICE_TTL = 600
DEVICE_INTERVAL = 4
MAX_WAITERS = 200
BODY_MAX = 8192
USER_CODE_ABC = "BCDFGHJKLMNPQRSTVWXZ"   # consonants: no words, no 0/O 1/I mix-ups
ACCT_RE = re.compile(r"^[A-Z0-9]{1,16}$")
PID_RE = re.compile(r"^[a-z0-9]{10}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-À-ɏ]{2,24}$")
CHAR_RE = re.compile(r"^[A-Za-zÀ-ɏ]{2,12}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
CODE_RE = re.compile(r"^[" + USER_CODE_ABC + r"]{4}-?[" + USER_CODE_ABC + r"]{4}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
BRAND_RE = re.compile(r"(?i)world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|\bwow\b")

# The realm's word filter (ov_workshop.lua badWord), ported: names that trip it are refused; in messages the
# words are masked. A short list on purpose.
BAD = ("fuck", "shit", "cunt", "bitch", "whore", "slut", "nigger", "nigga", "faggot", "fag", "retard", "rape",
       "rapist", "kike", "spic", "chink", "tranny", "nazi", "hitler", "cock", "dick", "pussy", "porn", "penis",
       "vagina", "twat", "wank", "dildo", "kys")
BAD_INSIDE = {"fuck", "shit", "nigger", "nigga", "faggot", "whore", "rapist", "hitler", "porn", "dildo"}
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "@": "a",
                      "$": "s", "!": "i", "|": "l"})


def _squash(s: str) -> str:
    return re.sub(r"(.)\1+", r"\1", s)


def bad_word(text: str) -> str | None:
    low = str(text or "").lower().translate(LEET)
    words = re.findall(r"[a-z]+", low)
    joined = "".join(words)
    seen = set(words) | {_squash(w) for w in words}
    for b in BAD:
        if b in seen or b + "s" in seen:
            return b
        if b in BAD_INSIDE and (b in joined or b in _squash(joined)):
            return b
    if re.fullmatch(r"[a-z\s.\-_]+", low):
        singles = re.sub(r"[^a-z]", "", low)
        if 3 <= len(singles) <= 12:
            for b in BAD_INSIDE:
                if b in _squash(singles):
                    return b
    return None


def mask(text: str) -> str:
    """A message with the filter's words starred out (the rest untouched)."""
    def rep(m):
        w = m.group(0)
        n = _squash(w.lower().translate(LEET))
        n2 = re.sub(r"[^a-z]", "", n)
        hit = n2 in BAD or (n2.endswith("s") and n2[:-1] in BAD) or any(b in n2 for b in BAD_INSIDE)
        return "*" * len(w) if hit else w
    return re.sub(r"[A-Za-z0-9@$!|]+", rep, text)


def clean_text(v, n: int) -> str:
    if not isinstance(v, str):
        return ""
    return re.sub(r"[ \t]+", " ", CTRL_RE.sub(" ", v)).strip()[:n]


def clean_name(v) -> str:
    """A display name from anything (the website's display name, a character): allowed characters only."""
    s = re.sub(r"[^A-Za-z0-9_.\-À-ɏ]", "", str(v or ""))[:NAME_MAX]
    if len(s) < NAME_MIN or bad_word(s) or BRAND_RE.search(s):
        return ""
    return s


def name_error(v) -> str:
    if not isinstance(v, str) or not NAME_RE.fullmatch(v):
        return "Names are 2 to 24 letters, digits, dots, dashes or underscores."
    if bad_word(v) or BRAND_RE.search(v):
        return "Pick another name."
    return ""


def thread_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _now() -> float:
    return time.time()


class Window:
    """A sliding-window counter: hit(key, limit) is False once key has had limit hits in the window."""
    def __init__(self, seconds: float, clock=time.monotonic):
        self.seconds, self.q, self.lock, self.clock = seconds, {}, threading.Lock(), clock

    def hit(self, key: str, limit: int) -> bool:
        now = self.clock()
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


class SocialError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status, self.text = status, text


SCHEMA = """
CREATE TABLE IF NOT EXISTS social_accounts (
  acct TEXT PRIMARY KEY, pid TEXT NOT NULL UNIQUE, name TEXT NOT NULL, name_lc TEXT NOT NULL, tag TEXT NOT NULL,
  main TEXT NOT NULL DEFAULT '', show_main INTEGER NOT NULL DEFAULT 0, offline INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL, UNIQUE (name_lc, tag));
CREATE INDEX IF NOT EXISTS social_accounts_name ON social_accounts (name_lc);
CREATE TABLE IF NOT EXISTS social_chars (
  name_lc TEXT NOT NULL, realm TEXT NOT NULL, acct TEXT NOT NULL, name TEXT NOT NULL, seen INTEGER NOT NULL,
  PRIMARY KEY (name_lc, realm));
CREATE TABLE IF NOT EXISTS social_rel (
  a TEXT NOT NULL, b TEXT NOT NULL, state TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', at INTEGER NOT NULL,
  PRIMARY KEY (a, b));
CREATE INDEX IF NOT EXISTS social_rel_b ON social_rel (b);
CREATE TABLE IF NOT EXISTS social_blocks (a TEXT NOT NULL, b TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS social_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lo TEXT NOT NULL, hi TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL,
  at INTEGER NOT NULL, via TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS social_messages_thread ON social_messages (lo, hi, id);
CREATE INDEX IF NOT EXISTS social_messages_at ON social_messages (at);
CREATE TABLE IF NOT EXISTS social_tokens (
  hash TEXT PRIMARY KEY, acct TEXT NOT NULL, label TEXT NOT NULL, created INTEGER NOT NULL, used INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS social_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, reporter TEXT NOT NULL, target TEXT NOT NULL,
  reason TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', context TEXT NOT NULL DEFAULT '[]', via TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open', handled_by TEXT NOT NULL DEFAULT '', handled_at INTEGER NOT NULL DEFAULT 0,
  outcome TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS social_reports_status ON social_reports (status, id);
"""


class Social:
    """The store, presence, rate limits and the realm bridge. Thread-safe (one connection, one lock)."""

    def __init__(self, data_dir: str | None = None, soap=None, realm_name: str = "WrathUnleashed", clock=_now,
                 db_file: str | None = None):
        if sqlite3 is None:
            raise RuntimeError("sqlite3 is missing")
        self.dir = data_dir or os.environ.get("WU_PORTAL_DATA", "/data")
        self.path = db_file or os.path.join(self.dir, "social.sqlite3")
        self.soap = soap               # soap(command) -> text; raises on failure
        self.realm = realm_name
        self.clock = clock
        self.keep_days = int(os.environ.get("WU_SOCIAL_KEEP_DAYS", "30") or 30)
        self.thread_max = int(os.environ.get("WU_SOCIAL_THREAD_MAX", "500") or 500)
        self.per_min = int(os.environ.get("WU_SOCIAL_MSG_PER_MIN", "20") or 20)
        self.per_day = int(os.environ.get("WU_SOCIAL_MSG_PER_DAY", "600") or 600)
        self.poll_every = float(os.environ.get("WU_SOCIAL_POLL", "3") or 3)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.cond = threading.Condition(self.lock)
        self.ver = 1
        self.acct_ver: dict[str, int] = {}
        self.ingame: dict[str, dict] = {}       # acct -> {realm, char, since}
        self.seen: dict[str, float] = {}        # acct -> last launcher/web call
        self.devices: dict[str, dict] = {}      # user code -> pending device sign-in
        self.waiters = 0
        self.outbox: collections.deque = collections.deque(maxlen=2000)
        self.dirty: set[str] = set()
        self.realm_state = {"boot": None, "seq": 0, "full_at": -1e9, "ok_at": 0.0, "fails": 0}
        self.lim_min = Window(60, self._mono)
        self.lim_day = Window(86400, self._mono)
        self.lim_hour = Window(3600, self._mono)
        self.lim_api = Window(60, self._mono)
        self.lim_ip = Window(600, self._mono)
        self.swept = 0.0
        self.key = os.environ.get("WU_FORM_SECRET", "").encode() or secrets.token_bytes(32)
        self.stop = threading.Event()
        self.wake = threading.Event()

    def _mono(self) -> float:
        return self.clock()

    def now(self) -> int:
        return int(self.clock())

    # ------------------------------------------------------------------ small db helpers
    def q(self, sql: str, args=()) -> list:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------------ change notification
    def touch(self, *accts: str) -> None:
        """These accounts' views changed: wake their launchers, push their in-game lists."""
        with self.cond:
            self.ver += 1
            for a in accts:
                if a:
                    self.acct_ver[a] = self.ver
                    if a in self.ingame:
                        self.dirty.add(a)
            self.cond.notify_all()
        self.wake.set()

    def touch_circle(self, acct: str) -> None:
        self.touch(acct, *self.friend_accts(acct))

    # ------------------------------------------------------------------ accounts
    def profile(self, acct: str):
        r = self.one("SELECT acct, pid, name, tag, main, show_main, offline FROM social_accounts WHERE acct = ?", (acct,))
        if not r:
            return None
        return {"acct": r[0], "pid": r[1], "name": r[2], "tag": r[3], "main": r[4], "show_main": bool(r[5]),
                "offline": bool(r[6])}

    def ensure(self, acct: str, name_hint: str = "") -> dict:
        """The account's profile, made on first sight (name from the hint, else "Player")."""
        acct = acct.upper()
        if not ACCT_RE.fullmatch(acct):
            raise SocialError(400, "Unknown account.")
        with self.lock:
            p = self.profile(acct)
            if p:
                return p
            name = clean_name(name_hint) or "Player"
            for _ in range(50):
                tag = f"{secrets.randbelow(9000) + 1000}"
                pid = "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(10))
                try:
                    self.x("INSERT INTO social_accounts (acct, pid, name, name_lc, tag, created) VALUES (?,?,?,?,?,?)",
                           (acct, pid, name, name.lower(), tag, self.now()))
                    break
                except sqlite3.IntegrityError:
                    continue
            return self.profile(acct)

    def by_pid(self, pid) -> str | None:
        if not isinstance(pid, str) or not PID_RE.fullmatch(pid):
            return None
        r = self.one("SELECT acct FROM social_accounts WHERE pid = ?", (pid,))
        return r[0] if r else None

    def label(self, p: dict) -> str:
        return p["main"] if p.get("show_main") and p.get("main") else p["name"]

    def set_profile(self, acct: str, doc: dict) -> dict:
        p = self.ensure(acct)
        if "name" in doc:
            name = doc.get("name")
            err = name_error(name)
            if err:
                raise SocialError(400, err)
            if name.lower() != p["name"].lower() or name != p["name"]:
                with self.lock:
                    taken = self.one("SELECT 1 FROM social_accounts WHERE name_lc = ? AND tag = ? AND acct <> ?",
                                     (name.lower(), p["tag"], acct))
                    tag = p["tag"]
                    if taken:   # keep the name, find a free tag
                        for _ in range(50):
                            tag = f"{secrets.randbelow(9000) + 1000}"
                            if not self.one("SELECT 1 FROM social_accounts WHERE name_lc = ? AND tag = ?", (name.lower(), tag)):
                                break
                    self.x("UPDATE social_accounts SET name = ?, name_lc = ?, tag = ? WHERE acct = ?",
                           (name, name.lower(), tag, acct))
        if "main" in doc:
            main = doc.get("main") or ""
            if main and (not isinstance(main, str) or not CHAR_RE.fullmatch(main)):
                raise SocialError(400, "That isn't a character name.")
            if main and not self.one("SELECT 1 FROM social_chars WHERE name_lc = ? AND acct = ?", (main.lower(), acct)):
                raise SocialError(400, "Log in with that character once, then pick it as your main.")
            self.x("UPDATE social_accounts SET main = ? WHERE acct = ?", (main[:1].upper() + main[1:].lower() if main else "", acct))
        if "show_main" in doc:
            self.x("UPDATE social_accounts SET show_main = ? WHERE acct = ?", (1 if doc.get("show_main") else 0, acct))
        if "offline" in doc:
            self.x("UPDATE social_accounts SET offline = ? WHERE acct = ?", (1 if doc.get("offline") else 0, acct))
        self.touch_circle(acct)
        return self.profile(acct)

    # ------------------------------------------------------------------ relations
    def blocked(self, a: str, b: str) -> bool:
        return bool(self.one("SELECT 1 FROM social_blocks WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)", (a, b, b, a)))

    def friends(self, a: str, b: str) -> bool:
        return bool(self.one("SELECT 1 FROM social_rel WHERE a = ? AND b = ? AND state = 'ok'", (a, b)))

    def friend_accts(self, acct: str) -> list[str]:
        return [r[0] for r in self.q("SELECT b FROM social_rel WHERE a = ? AND state = 'ok'", (acct,))]

    def find(self, acct: str, text) -> tuple[str | None, str]:
        """Someone to send a request to or to block: "Name#1234", a unique name, or a character seen on the realm.
        (acct or None, the label the asker typed)."""
        t = clean_text(text, 40) if isinstance(text, str) else ""
        if not t:
            return None, ""
        m = re.fullmatch(r"(.{2,24})#(\d{4})", t)
        if m:
            r = self.one("SELECT acct FROM social_accounts WHERE name_lc = ? AND tag = ?", (m.group(1).lower(), m.group(2)))
            return (r[0] if r else None), t
        rows = self.q("SELECT acct FROM social_accounts WHERE name_lc = ?", (t.lower(),))
        if len(rows) == 1:
            return rows[0][0], t
        if len(rows) > 1:
            raise SocialError(409, f"More than one player is called {t}: add their #number (for example {t}#1234).")
        rows = self.q("SELECT DISTINCT acct FROM social_chars WHERE name_lc = ?", (t.lower(),))
        if len(rows) == 1:
            return rows[0][0], t
        return None, t

    def request(self, acct: str, to) -> str:
        self.ensure(acct)
        if not self.lim_hour.hit("req|" + acct, 20):
            raise SocialError(429, "That's a lot of friend requests. Try again later.")
        other, label = self.find(acct, to)
        if not other or other == acct or other.startswith("RNDBOT") or self.blocked(acct, other):
            # the same answer for "no such player" and "they blocked you": a block is never revealed
            raise SocialError(404, f"No player called {label or 'that'} was found. Try their Name#1234.")
        with self.lock:
            if self.friends(acct, other):
                return "You're already friends."
            back = self.one("SELECT 1 FROM social_rel WHERE a = ? AND b = ? AND state = 'req'", (other, acct))
            if back:   # they asked first: this is a yes
                self._make_friends(acct, other)
                return "You're friends now."
            n = self.one("SELECT COUNT(*) FROM social_rel WHERE a = ? AND state = 'req'", (acct,))[0]
            if n >= 100:
                raise SocialError(429, "You have 100 requests waiting. Cancel some first.")
            self.x("INSERT OR REPLACE INTO social_rel (a, b, state, label, at) VALUES (?,?,'req',?,?)",
                   (acct, other, label, self.now()))
        self.touch(acct, other)
        p = self.profile(acct)
        self.tell(other, f"Friend request from {self.label(p)}#{p['tag']}. Type .lf accept {p['name']} or use the Friends panel.")
        return "Request sent."

    def _make_friends(self, a: str, b: str) -> None:
        t = self.now()
        with self.lock:
            self.x("DELETE FROM social_rel WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)", (a, b, b, a))
            n = self.one("SELECT COUNT(*) FROM social_rel WHERE a = ? AND state = 'ok'", (a,))[0]
            if n >= 500:
                raise SocialError(429, "You have 500 friends: remove someone first.")
            self.x("INSERT INTO social_rel (a, b, state, at) VALUES (?,?,'ok',?)", (a, b, t))
            self.x("INSERT INTO social_rel (a, b, state, at) VALUES (?,?,'ok',?)", (b, a, t))
        self.touch_circle(a)
        self.touch_circle(b)

    def accept(self, acct: str, other: str | None) -> str:
        if not other or not self.one("SELECT 1 FROM social_rel WHERE a = ? AND b = ? AND state = 'req'", (other, acct)):
            raise SocialError(404, "There's no request from them.")
        self._make_friends(acct, other)
        p = self.profile(acct)
        self.tell(other, f"{self.label(p)} accepted your friend request.")
        return "You're friends now."

    def decline(self, acct: str, other: str | None) -> str:
        if not other:
            raise SocialError(404, "There's no request from them.")
        n = self.x("DELETE FROM social_rel WHERE ((a = ? AND b = ?) OR (a = ? AND b = ?)) AND state = 'req'",
                   (other, acct, acct, other))
        self.touch(acct, other)
        return "Request removed." if n else "There was no request."

    def remove(self, acct: str, other: str | None) -> str:
        if not other:
            raise SocialError(404, "They aren't on your list.")
        self.x("DELETE FROM social_rel WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)", (acct, other, other, acct))
        self.touch_circle(acct)
        self.touch(other)
        return "Removed."

    def block(self, acct: str, other: str | None) -> str:
        if not other or other == acct:
            raise SocialError(404, "No player like that was found.")
        with self.lock:
            self.x("DELETE FROM social_rel WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)", (acct, other, other, acct))
            self.x("INSERT OR REPLACE INTO social_blocks (a, b, at) VALUES (?,?,?)", (acct, other, self.now()))
        self.touch_circle(acct)
        self.touch(other)
        return "Blocked. They can't see you, message you or send you requests."

    def unblock(self, acct: str, other: str | None) -> str:
        if not other:
            raise SocialError(404, "They aren't blocked.")
        self.x("DELETE FROM social_blocks WHERE a = ? AND b = ?", (acct, other))
        self.touch(acct)
        return "Unblocked."

    # ------------------------------------------------------------------ presence
    def status_of(self, acct: str, p: dict | None = None) -> tuple[str, str, str]:
        """("game"|"launcher"|"offline", realm, character) as friends see it."""
        p = p or self.profile(acct)
        if not p or p["offline"]:
            return "offline", "", ""
        g = self.ingame.get(acct)
        if g:
            return "game", g["realm"], g["char"]
        if self.clock() - self.seen.get(acct, -1e9) < LAUNCHER_ONLINE:
            return "launcher", "", ""
        return "offline", "", ""

    def mark_seen(self, acct: str) -> None:
        was = self.clock() - self.seen.get(acct, -1e9) < LAUNCHER_ONLINE
        self.seen[acct] = self.clock()
        if not was:
            self.touch_circle(acct)

    def sweep_seen(self) -> None:
        """Launchers that stopped calling drop to offline for their friends."""
        cut = self.clock() - LAUNCHER_ONLINE
        gone = [a for a, t in list(self.seen.items()) if t < cut]
        for a in gone:
            self.seen.pop(a, None)
            self.touch_circle(a)

    # ------------------------------------------------------------------ the state a client sees
    def state(self, acct: str) -> dict:
        me = self.ensure(acct)
        friends, incoming, outgoing, blocked = [], [], [], []
        unread = {r[0]: r[1] for r in self.q(
            "SELECT sender, COUNT(*) FROM social_messages WHERE (lo = ? OR hi = ?) AND sender <> ? AND seen = 0 GROUP BY sender",
            (acct, acct, acct))}
        for b, state, label, at in self.q("SELECT b, state, label, at FROM social_rel WHERE a = ?", (acct,)):
            p = self.profile(b)
            if not p:
                continue
            if state == "ok":
                st, realm, char = self.status_of(b, p)
                friends.append({"pid": p["pid"], "name": self.label(p), "tag": p["tag"], "main": p["main"],
                                "status": st, "realm": realm, "char": char, "unread": unread.get(b, 0)})
            elif state == "req":   # mine, waiting: shown as I typed it
                outgoing.append({"pid": p["pid"], "name": label or p["name"], "at": at})
        for a, label, at in self.q("SELECT a, label, at FROM social_rel WHERE b = ? AND state = 'req'", (acct,)):
            p = self.profile(a)
            if p:
                incoming.append({"pid": p["pid"], "name": self.label(p), "tag": p["tag"], "at": at})
        for (b,) in self.q("SELECT b FROM social_blocks WHERE a = ?", (acct,)):
            p = self.profile(b)
            if p:
                blocked.append({"pid": p["pid"], "name": p["name"], "tag": p["tag"]})
        order = {"game": 0, "launcher": 1, "offline": 2}
        friends.sort(key=lambda f: (order[f["status"]], f["name"].lower()))
        return {"v": self.ver, "me": {"pid": me["pid"], "name": me["name"], "tag": me["tag"], "main": me["main"],
                                     "show_main": me["show_main"], "offline": me["offline"],
                                     "status": self.status_of(acct, dict(me, offline=False))[0]},
                "friends": friends, "incoming": incoming, "outgoing": outgoing, "blocked": blocked}

    def wait(self, acct: str, since: int, timeout: float = LONGPOLL) -> bool:
        """True when something for acct changed after version since (or the long poll is full: answer now)."""
        with self.cond:
            if self.acct_ver.get(acct, 0) > since:
                return True
            if self.waiters >= MAX_WAITERS:
                return True
            self.waiters += 1
            try:
                end = time.monotonic() + timeout
                while self.acct_ver.get(acct, 0) <= since and not self.stop.is_set():
                    left = end - time.monotonic()
                    if left <= 0:
                        return False
                    self.cond.wait(min(left, 5))
                return True
            finally:
                self.waiters -= 1

    # ------------------------------------------------------------------ messages
    def send(self, acct: str, other: str | None, text, via: str) -> dict:
        if not other or not self.friends(acct, other) or self.blocked(acct, other):
            raise SocialError(403, "You can only message your Leyline friends.")
        body = clean_text(text if isinstance(text, str) else "", TEXT_MAX + 1)
        if not body:
            raise SocialError(400, "Type a message first.")
        if len(body) > TEXT_MAX:
            raise SocialError(400, f"Messages are at most {TEXT_MAX} characters.")
        if not self.lim_min.hit("msg|" + acct, self.per_min) or not self.lim_day.hit("msg|" + acct, self.per_day):
            raise SocialError(429, "You're sending messages too fast. Wait a moment.")
        body = mask(body)
        lo, hi = thread_key(acct, other)
        with self.lock:
            mid = self.x("INSERT INTO social_messages (lo, hi, sender, body, at, via) VALUES (?,?,?,?,?,?)",
                         (lo, hi, acct, body, self.now(), via))
            self.x("DELETE FROM social_messages WHERE id IN (SELECT id FROM social_messages WHERE lo = ? AND hi = ? "
                   "ORDER BY id DESC LIMIT -1 OFFSET ?)", (lo, hi, self.thread_max))
        self.sweep()
        self.touch(acct, other)
        if other in self.ingame:
            p = self.profile(acct)
            self.queue(("msg", other, mid, self.label(p), body))
        return {"id": mid, "mine": True, "text": body, "at": self.now(), "via": via}

    def thread(self, acct: str, other: str | None, before=None) -> list[dict]:
        if not other or self.blocked(acct, other):
            return []
        lo, hi = thread_key(acct, other)
        try:
            before = int(before) if before not in (None, "") else None
        except (TypeError, ValueError):
            before = None
        args = (lo, hi) + ((before,) if before else ()) + (PAGE,)
        rows = self.q("SELECT id, sender, body, at, via FROM social_messages WHERE lo = ? AND hi = ? "
                      + ("AND id < ? " if before else "") + "ORDER BY id DESC LIMIT ?", args)
        return [{"id": r[0], "mine": r[1] == acct, "text": r[2], "at": r[3], "via": r[4]} for r in reversed(rows)]

    def mark_read(self, acct: str, other: str | None) -> None:
        if not other:
            return
        lo, hi = thread_key(acct, other)
        n = self.x("UPDATE social_messages SET seen = 1 WHERE lo = ? AND hi = ? AND sender = ? AND seen = 0", (lo, hi, other))
        if n:
            self.touch(acct)

    def sweep(self, force: bool = False) -> None:
        """Retention: messages older than keep_days go; handled reports after 180 days. At most hourly."""
        t = self.clock()
        if not force and t - self.swept < 3600:
            return
        self.swept = t
        self.x("DELETE FROM social_messages WHERE at < ?", (int(t) - self.keep_days * 86400,))
        self.x("DELETE FROM social_reports WHERE status <> 'open' AND handled_at < ?", (int(t) - 180 * 86400,))

    # ------------------------------------------------------------------ reports (the admin console reads these)
    def report(self, acct: str, other: str | None, reason, note, via: str) -> str:
        if not other:
            raise SocialError(404, "No player like that was found.")
        if reason not in REASONS:
            raise SocialError(400, "Pick a reason: " + ", ".join(REASONS) + ".")
        if not self.lim_day.hit("report|" + acct, 10):
            raise SocialError(429, "You've sent a lot of reports today. The moderators will look at them.")
        lo, hi = thread_key(acct, other)
        rows = self.q("SELECT sender, body, at, via FROM social_messages WHERE lo = ? AND hi = ? ORDER BY id DESC LIMIT 20",
                      (lo, hi))
        ctx = [{"from": r[0], "text": r[1], "at": r[2], "via": r[3]} for r in reversed(rows)]
        self.x("INSERT INTO social_reports (at, reporter, target, reason, note, context, via) VALUES (?,?,?,?,?,?,?)",
               (self.now(), acct, other, reason, clean_text(note or "", NOTE_MAX), json.dumps(ctx), via))
        log.info("social report filed (%s)", reason)
        return "Thanks. The moderators will look at it. You can block them too."

    def reports(self, status: str = "open", limit: int = 100) -> list[dict]:
        rows = self.q("SELECT id, at, reporter, target, reason, note, context, via, status, handled_by, handled_at, outcome "
                      "FROM social_reports WHERE (? = '' OR status = ?) ORDER BY id DESC LIMIT ?",
                      (status or "", status or "", max(1, min(int(limit), 1000))))
        out = []
        for r in rows:
            rep, tgt = self.profile(r[2]) or {}, self.profile(r[3]) or {}
            out.append({"id": r[0], "at": r[1], "reporter": r[2], "reporter_name": rep.get("name", ""),
                        "target": r[3], "target_name": tgt.get("name", ""), "reason": r[4], "note": r[5],
                        "context": json.loads(r[6] or "[]"), "via": r[7], "status": r[8], "handled_by": r[9],
                        "handled_at": r[10], "outcome": r[11]})
        return out

    def resolve_report(self, rid: int, by: str, outcome: str, status: str = "done") -> bool:
        if status not in ("done", "dismissed", "open"):
            return False
        return bool(self.x("UPDATE social_reports SET status = ?, handled_by = ?, handled_at = ?, outcome = ? WHERE id = ?",
                           (status, clean_text(by, 40), self.now(), clean_text(outcome, 300), int(rid))))

    # ------------------------------------------------------------------ launcher sign-in: device codes and tokens
    def device_start(self, ip: str) -> dict:
        if not self.lim_ip.hit("dev|" + ip, 10):
            raise SocialError(429, "Too many sign-in attempts. Wait a few minutes.")
        t = self.clock()
        with self.lock:
            for code in [c for c, d in self.devices.items() if d["expires"] < t]:
                del self.devices[code]
            if len(self.devices) > 5000:
                raise SocialError(503, "Busy. Try again in a minute.")
            device = secrets.token_urlsafe(32)
            while True:
                code = "".join(secrets.choice(USER_CODE_ABC) for _ in range(8))
                if code not in self.devices:
                    break
            self.devices[code] = {"hash": hashlib.sha256(device.encode()).hexdigest(), "expires": t + DEVICE_TTL,
                                  "acct": None, "denied": False, "token": None, "polled": 0.0}
        user_code = code[:4] + "-" + code[4:]
        return {"device_code": device, "user_code": user_code, "interval": DEVICE_INTERVAL, "expires_in": DEVICE_TTL,
                "verify_url": f"https://{{host}}{LINK_PAGE}?code={user_code}"}

    def device_poll(self, device) -> dict:
        if not isinstance(device, str) or not DEVICE_RE.fullmatch(device):
            raise SocialError(400, "Bad device code.")
        h = hashlib.sha256(device.encode()).hexdigest()
        t = self.clock()
        with self.lock:
            for code, d in self.devices.items():
                if hmac.compare_digest(d["hash"], h):
                    if d["expires"] < t:
                        del self.devices[code]
                        return {"status": "expired"}
                    if t - d["polled"] < DEVICE_INTERVAL - 1:
                        return {"status": "slow_down"}
                    d["polled"] = t
                    if d["denied"]:
                        del self.devices[code]
                        return {"status": "denied"}
                    if d["token"]:
                        tok = d["token"]
                        del self.devices[code]
                        return {"status": "ok", "token": tok}
                    return {"status": "pending"}
        return {"status": "expired"}

    def device_lookup(self, code) -> str | None:
        c = re.sub(r"[^A-Za-z]", "", str(code or "")).upper()
        if len(c) != 8 or any(ch not in USER_CODE_ABC for ch in c):
            return None
        d = self.devices.get(c)
        return c if d and d["expires"] >= self.clock() and not d["token"] and not d["denied"] else None

    def device_answer(self, code: str, acct: str, approve: bool) -> bool:
        with self.lock:
            d = self.devices.get(code)
            if not d or d["expires"] < self.clock() or d["token"] or d["denied"]:
                return False
            if not approve:
                d["denied"] = True
                return True
            self.ensure(acct)
            n = self.one("SELECT COUNT(*) FROM social_tokens WHERE acct = ?", (acct,))[0]
            if n >= 10:   # the oldest launcher sign-in makes room
                self.x("DELETE FROM social_tokens WHERE hash = (SELECT hash FROM social_tokens WHERE acct = ? "
                       "ORDER BY used LIMIT 1)", (acct,))
            tok = secrets.token_urlsafe(32)
            label = "Leyline launcher, linked " + time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
            self.x("INSERT INTO social_tokens (hash, acct, label, created, used) VALUES (?,?,?,?,?)",
                   (hashlib.sha256(tok.encode()).hexdigest(), acct, label, self.now(), self.now()))
            d["token"] = tok
            return True

    def token_acct(self, tok) -> str | None:
        if not isinstance(tok, str) or not TOKEN_RE.fullmatch(tok):
            return None
        h = hashlib.sha256(tok.encode()).hexdigest()
        r = self.one("SELECT acct, used FROM social_tokens WHERE hash = ?", (h,))
        if not r:
            return None
        if self.now() - r[1] > 60:
            self.x("UPDATE social_tokens SET used = ? WHERE hash = ?", (self.now(), h))
        return r[0]

    def tokens(self, acct: str) -> list[dict]:
        return [{"id": r[0][:12], "label": r[1], "created": r[2], "used": r[3]} for r in
                self.q("SELECT hash, label, created, used FROM social_tokens WHERE acct = ? ORDER BY created", (acct,))]

    def revoke(self, acct: str, short_id: str | None = None, tok: str | None = None) -> bool:
        if tok:
            h = hashlib.sha256(tok.encode()).hexdigest()
            return bool(self.x("DELETE FROM social_tokens WHERE hash = ? AND acct = ?", (h, acct)))
        if isinstance(short_id, str) and re.fullmatch(r"[0-9a-f]{12}", short_id):
            return bool(self.x("DELETE FROM social_tokens WHERE acct = ? AND substr(hash, 1, 12) = ?", (acct, short_id)))
        return False

    # ------------------------------------------------------------------ the realm bridge (ov_social.lua over SOAP)
    def queue(self, item: tuple) -> None:
        self.outbox.append(item)
        self.wake.set()

    def tell(self, acct: str, text: str) -> None:
        if acct in self.ingame:
            self.queue(("tell", acct, text))

    @staticmethod
    def hx(s: str) -> str:
        return s.encode("utf-8").hex()

    @staticmethod
    def unhx(h: str) -> str | None:
        try:
            return bytes.fromhex(h).decode("utf-8", "replace")
        except ValueError:
            return None

    def game_list(self, acct: str) -> list[str]:
        """The in-game friends panel for acct: one line per person, name<TAB>tag<TAB>status<TAB>where."""
        s = self.state(acct)
        lines = []
        for f in s["friends"]:
            where = f"{f['char']} on {f['realm']}" if f["status"] == "game" else ("In the launcher" if f["status"] == "launcher" else "")
            lines.append("\t".join((f["name"], f["tag"], {"game": "g", "launcher": "l", "offline": "o"}[f["status"]],
                                    where, str(f["unread"]))))
        for f in s["incoming"]:
            lines.append("\t".join((f["name"], f["tag"], "q", "Wants to be friends", "0")))
        for f in s["outgoing"]:
            lines.append("\t".join((f["name"], "", "p", "Request sent", "0")))
        return lines[:200]

    def _game_commands(self, item: tuple) -> list[tuple[str, tuple]]:
        kind = item[0]
        if kind == "msg":
            _, acct, mid, sender, body = item
            return [(f"ovsocial msg {acct} {mid} {self.hx(sender)} {self.hx(body)}", item)]
        if kind == "tell":
            return [(f"ovsocial tell {item[1]} {self.hx(item[2])}", item)]
        if kind == "fr":
            acct = item[1]
            blob = self.hx("\n".join(self.game_list(acct)))
            parts = [blob[i:i + 960] for i in range(0, len(blob), 960)] or [""]
            return [(f"ovsocial fr {acct} {i + 1} {len(parts)} {p or '-'}", item) for i, p in enumerate(parts)]
        return []

    def flush(self) -> int:
        """Send what is waiting for the realm: notices, messages, then the friend lists that changed."""
        if self.soap is None:
            self.outbox.clear()
            return 0
        with self.lock:
            for a in sorted(self.dirty):
                if a in self.ingame:
                    self.outbox.append(("fr", a))
            self.dirty.clear()
        sent = 0
        while self.outbox:
            item = self.outbox.popleft()
            for cmd, it in self._game_commands(item):
                try:
                    out = self.soap(cmd)
                except Exception:   # noqa: BLE001: the realm is down; messages stay unread for next time
                    self.realm_state["fails"] += 1
                    return sent
                sent += 1
                m = re.search(r"ovsocial ok shown (\d+)", out or "")
                if it[0] == "msg" and m:
                    self.x("UPDATE social_messages SET seen = 1 WHERE id = ?", (int(m.group(1)),))
                    self.touch(it[1])
        return sent

    def pull(self) -> int:
        """One "ovsocial pull": events since the last one (and every 2 minutes, or after a restart, everyone online)."""
        if self.soap is None:
            return 0
        rs = self.realm_state
        t = self.clock()
        full = rs["boot"] is None or t - rs["full_at"] >= 120
        try:
            out = self.soap(f"ovsocial pull {rs['seq']} {rs['boot'] or 0} {1 if full else 0}")
        except Exception:   # noqa: BLE001
            rs["fails"] += 1
            if rs["fails"] >= 3 and self.ingame:   # the realm is gone: nobody is in game until it answers again
                gone = list(self.ingame)
                self.ingame.clear()
                for a in gone:
                    self.touch_circle(a)
            return 0
        lines = (out or "").splitlines()
        head = re.match(r"^ovsocial ok (\d+) (\d+) (\d+)", lines[0] if lines else "")
        if not head:
            rs["fails"] += 1
            return 0
        boot, seq = int(head.group(1)), int(head.group(2))
        rs["fails"], rs["ok_at"] = 0, t
        if rs["boot"] is not None and boot != rs["boot"] and not full:
            rs["boot"], rs["seq"], rs["full_at"] = boot, 0, -1e9   # a restart: start over with a snapshot now
            return self.pull()
        snapshot = {} if full else None
        n = 0
        for line in lines[1:]:
            parts = line.split(" ")
            try:
                n += self.event(parts, snapshot)
            except SocialError as e:   # say why in game (to the one who typed it)
                if parts[0] in ("M", "F") and len(parts) > 2 and ACCT_RE.fullmatch(parts[2]):
                    self.tell(parts[2], e.text)
            except Exception:   # noqa: BLE001: one bad line never stops the rest
                log.exception("social: bad realm line")
        if snapshot is not None:
            for a in [a for a, g in self.ingame.items() if g["realm"] == self.realm and a not in snapshot]:
                self.ingame.pop(a, None)
                self.touch_circle(a)
            for a, (char, guid) in snapshot.items():
                if a not in self.ingame:
                    self.login(a, char, quiet=True)
            rs["full_at"] = t
        rs["boot"], rs["seq"] = boot, seq
        return n

    def event(self, p: list[str], snapshot) -> int:
        kind = p[0] if p else ""
        if kind == "P" and len(p) >= 3 and snapshot is not None:
            acct, char = p[1], self.unhx(p[2]) or ""
            if ACCT_RE.fullmatch(acct) and not acct.startswith("RNDBOT") and CHAR_RE.fullmatch(char):
                snapshot[acct] = (char, p[3] if len(p) > 3 else "")
            return 0
        if kind not in ("I", "O", "M", "F") or len(p) < 4:
            return 0
        acct, char = p[2], self.unhx(p[3]) or ""
        if not ACCT_RE.fullmatch(acct) or acct.startswith("RNDBOT") or not CHAR_RE.fullmatch(char):
            return 0
        if kind == "I":
            self.login(acct, char)
        elif kind == "O":
            g = self.ingame.get(acct)
            if g and g["char"].lower() == char.lower():
                self.ingame.pop(acct, None)
                self.touch_circle(acct)
        elif kind == "M" and len(p) >= 6:
            self.game_message(acct, char, self.unhx(p[4]) or "", self.unhx(p[5]) or "")
        elif kind == "F" and len(p) >= 5:
            self.game_action(acct, char, self.unhx(p[4]) or "", self.unhx(p[5]) if len(p) > 5 else "")
        return 1

    def login(self, acct: str, char: str, quiet: bool = False) -> None:
        p = self.ensure(acct, char)
        with self.lock:
            self.x("INSERT OR REPLACE INTO social_chars (name_lc, realm, acct, name, seen) VALUES (?,?,?,?,?)",
                   (char.lower(), self.realm, acct, char, self.now()))
            self.ingame[acct] = {"realm": self.realm, "char": char, "since": self.now()}
        self.touch_circle(acct)
        if quiet:
            return
        if not p["offline"]:
            for f in self.friend_accts(acct):
                self.tell(f, f"{self.label(p)} is now in game ({char}).")
        # what arrived while they were away: the latest 5 unread lines, then a count
        rows = self.q("SELECT id, sender, body FROM social_messages WHERE (lo = ? OR hi = ?) AND sender <> ? AND seen = 0 "
                      "ORDER BY id DESC LIMIT 6", (acct, acct, acct))
        for mid, sender, body in reversed(rows[:5]):
            sp = self.profile(sender)
            if sp and not self.blocked(acct, sender):
                self.queue(("msg", acct, mid, self.label(sp), body))
        if len(rows) > 5:
            self.tell(acct, "More unread Leyline messages are waiting: open the Friends panel (/lfriends).")
        n = self.one("SELECT COUNT(*) FROM social_rel WHERE b = ? AND state = 'req'", (acct,))[0]
        if n:
            self.tell(acct, f"{n} friend request{'s' if n > 1 else ''} waiting: type .lf to see {'them' if n > 1 else 'it'}.")

    def resolve_friend(self, acct: str, text: str) -> str | None:
        """A friend named in game: name, Name#1234, main or the character they're on now."""
        t = (text or "").strip().lower()
        if not t:
            return None
        tag = None
        m = re.fullmatch(r"(.+)#(\d{4})", t)
        if m:
            t, tag = m.group(1), m.group(2)
        hits = []
        for f in self.friend_accts(acct):
            p = self.profile(f)
            if not p:
                continue
            names = {p["name"].lower(), (p["main"] or "").lower()}
            g = self.ingame.get(f)
            if g and not p["offline"]:
                names.add(g["char"].lower())
            if t in names and (tag is None or tag == p["tag"]):
                hits.append(f)
        if len(hits) > 1:
            raise SocialError(409, f"Two friends match {text}: add their #number.")
        return hits[0] if hits else None

    def game_message(self, acct: str, char: str, to: str, text: str) -> None:
        if acct not in self.ingame:
            self.login(acct, char, quiet=True)
        other = self.resolve_friend(acct, to)
        if not other:
            self.tell(acct, f"Not sent: no Leyline friend called {clean_text(to, 30)}. Type .lf for your list.")
            return
        self.send(acct, other, text, "game")

    def game_action(self, acct: str, char: str, verb: str, arg: str) -> None:
        if acct not in self.ingame:
            self.login(acct, char, quiet=True)
        verb = verb.lower()
        arg = clean_text(arg or "", 60)
        if verb == "add":
            self.tell(acct, self.request(acct, arg))
        elif verb in ("accept", "decline"):
            other = None
            for a, in self.q("SELECT a FROM social_rel WHERE b = ? AND state = 'req'", (acct,)):
                p = self.profile(a)
                if p and arg.lower() in (p["name"].lower(), f"{p['name'].lower()}#{p['tag']}", (p["main"] or "").lower()):
                    other = a
                    break
            self.tell(acct, self.accept(acct, other) if verb == "accept" else self.decline(acct, other))
        elif verb in ("remove", "block"):
            other = self.resolve_friend(acct, arg)
            if not other and verb == "block":
                other, _ = self.find(acct, arg)
            self.tell(acct, self.remove(acct, other) if verb == "remove" else self.block(acct, other))
        elif verb == "unblock":
            other, _ = self.find(acct, arg)
            self.tell(acct, self.unblock(acct, other))
        elif verb in ("offline", "online"):
            self.set_profile(acct, {"offline": verb == "offline"})
            self.tell(acct, "You appear offline to your Leyline friends." if verb == "offline" else "Your friends can see you again.")
        elif verb == "report":
            who, _, reason = arg.partition(" ")
            other = self.resolve_friend(acct, who)
            reason = reason.strip().lower() or "other"
            self.tell(acct, self.report(acct, other, reason if reason in REASONS else "other", "", "game"))
        elif verb == "list":
            self.touch(acct)
        else:
            self.tell(acct, "Leyline: .lf add|accept|decline|remove|block|unblock <name>, .lf offline|online, .lm <friend> <text>")

    def tick(self) -> None:
        self.pull()
        self.sweep_seen()
        self.flush()
        self.sweep()

    def run(self) -> None:
        """The bridge thread: pull and flush every poll_every seconds (sooner when something is waiting)."""
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:   # noqa: BLE001
                log.exception("social bridge")
            idle = not self.ingame and not self.seen
            self.wake.wait(self.poll_every * (5 if idle else 1))
            self.wake.clear()

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True, name="social-bridge").start()


# ----------------------------------------------------------------------------------------------
# HTTP (stream/wrath_portal.py's PageHandler calls get/post)
# ----------------------------------------------------------------------------------------------

_get = None
store: Social | None = None
_who_cache: dict[str, tuple[float, str, str]] = {}


def bind(getter) -> None:
    """getter(name) -> one of the portal's globals (portal_get, ac_soap, ly_shell, PUBLIC_HOST, REALM_NAME ...)."""
    global _get
    _get = getter


def P(name):
    return _get(name)


def setup(start_thread: bool = True) -> Social | None:
    """Make the store (once). None when switched off (WU_SOCIAL=0) or when it can't open its file."""
    global store
    if store is not None:
        return store
    if os.environ.get("WU_SOCIAL", "1") == "0":
        return None
    try:
        store = Social(soap=P("ac_soap"), realm_name=P("REALM_NAME"))
    except Exception:   # noqa: BLE001: the rest of the portal runs without friends
        log.exception("social: off (the store didn't open)")
        return None
    if start_thread:
        store.start()
    return store


def match(path: str) -> bool:
    return path == LINK_PAGE or path == API or path.startswith(API + "/")


def _session(cookie: str) -> str:
    for part in cookie.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "wr_session":
            return v
    return ""


def csrf_for(session: str) -> str:
    return hmac.new(store.key, ("social|" + session).encode(), hashlib.sha256).hexdigest()[:32]


def cookie_user(h) -> tuple[str, str] | None:
    """(acct, display) for the website session, cached 60 s; None when signed out. Raises OSError when the site is down."""
    cookie = h.headers.get("Cookie", "")
    sess = _session(cookie)
    if not sess:
        return None
    key = hashlib.sha256(sess.encode()).hexdigest()
    hit = _who_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2]
    ip, ua = h.ip(), h.headers.get("User-Agent", "")
    status, me = P("portal_get")("/api/me", cookie, ip, ua)
    if status in (401, 403) or 300 <= status < 400:
        return None
    if status != 200 or not me:
        raise OSError(f"api/me answered {status}")
    status, play = P("portal_get")("/api/play", cookie, ip, ua)
    user = str(play.get("user", "")) if isinstance(play, dict) else ""
    if status != 200 or not re.fullmatch(r"[A-Za-z0-9]{1,16}", user):
        raise OSError(f"api/play answered {status}")
    display = str(me.get("display_name") or me.get("username") or "")
    if len(_who_cache) > 5000:
        _who_cache.clear()
    _who_cache[key] = (time.monotonic() + 60, user.upper(), display)
    return user.upper(), display


def _json(h, status: int, doc: dict) -> None:
    h.send(status, json.dumps(doc, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8")


def _auth(h, post: bool):
    """(acct, how, extra) or None after answering. how is "token" or "cookie"."""
    authz = h.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        tok = authz[7:].strip()
        acct = store.token_acct(tok)
        if not acct:
            _json(h, 401, {"error": "Signed out. Sign in again from the launcher."})
            return None
        return acct, "token", tok
    if post:   # a cookie POST: not from another site, and the token from GET me
        if h.headers.get("Sec-Fetch-Site", "") == "cross-site":
            _json(h, 403, {"error": "That came from another site."})
            return None
        origin = h.headers.get("Origin", "")
        if origin and origin != f"https://{P('PUBLIC_HOST')}":
            _json(h, 403, {"error": "That came from another site."})
            return None
    try:
        who = cookie_user(h)
    except OSError:
        _json(h, 503, {"error": "The website isn't answering right now."})
        return None
    if who is None:
        _json(h, 401, {"error": "Sign in first."})
        return None
    sess = _session(h.headers.get("Cookie", ""))
    if post and not hmac.compare_digest(h.headers.get("X-Leyline-CSRF", ""), csrf_for(sess)):
        _json(h, 403, {"error": "Reload the page and try again."})
        return None
    store.ensure(who[0], who[1])
    return who[0], "cookie", sess


def _body(h):
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > BODY_MAX:
        return None
    raw = h.rfile.read(n) if n else b"{}"
    try:
        doc = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def get(h, path: str, query: dict) -> None:
    if store is None:
        _json(h, 404, {"error": "Leyline friends are off here."}) if path != LINK_PAGE else h.send(404, b"not found\n", "text/plain")
        return
    if path == LINK_PAGE:
        return link_page(h, query)
    sub = path[len(API):].strip("/")
    a = _auth(h, False)
    if a is None:
        return
    acct, how, extra = a
    if not store.lim_api.hit("api|" + acct, 240):
        return _json(h, 429, {"error": "Slow down a little."})
    if how == "token":
        store.mark_seen(acct)
    one = lambda k: (query.get(k) or [""])[0]   # noqa: E731
    if sub == "me":
        p = store.ensure(acct)
        doc = {"me": {"pid": p["pid"], "name": p["name"], "tag": p["tag"], "main": p["main"], "offline": p["offline"]}}
        if how == "cookie":
            doc["csrf"] = csrf_for(extra)
        return _json(h, 200, doc)
    if sub == "state":
        return _json(h, 200, store.state(acct))
    if sub == "events":
        try:
            since = int(one("since") or 0)
        except ValueError:
            since = 0
        changed = store.wait(acct, since)
        if how == "token":
            store.mark_seen(acct)
        return _json(h, 200, store.state(acct) if changed else {"v": since, "same": True})
    if sub == "thread":
        other = store.by_pid(one("with"))
        if not other:
            return _json(h, 404, {"error": "Unknown player."})
        return _json(h, 200, {"messages": store.thread(acct, other, one("before"))})
    _json(h, 404, {"error": "Unknown call."})


def post(h, path: str) -> None:
    if store is None:
        _json(h, 404, {"error": "Leyline friends are off here."}) if path != LINK_PAGE else h.send(404, b"not found\n", "text/plain")
        return
    if path == LINK_PAGE:
        return link_post(h)
    sub = path[len(API):].strip("/")
    ip = h.ip()
    if sub == "device/start":
        try:
            d = store.device_start(ip)
        except SocialError as e:
            return _json(h, e.status, {"error": e.text})
        d["verify_url"] = d["verify_url"].replace("{host}", P("PUBLIC_HOST"))
        return _json(h, 200, d)
    if sub == "device/poll":
        doc = _body(h)
        if doc is None:
            return _json(h, 400, {"error": "Bad request."})
        if not store.lim_ip.hit("poll|" + ip, 400):
            return _json(h, 429, {"status": "slow_down"})
        try:
            return _json(h, 200, store.device_poll(doc.get("device_code")))
        except SocialError as e:
            return _json(h, e.status, {"error": e.text})
    a = _auth(h, True)
    if a is None:
        return
    acct, how, extra = a
    if not store.lim_api.hit("api|" + acct, 240):
        return _json(h, 429, {"error": "Slow down a little."})
    doc = _body(h)
    if doc is None:
        return _json(h, 400, {"error": "Bad request."})
    if how == "token":
        store.mark_seen(acct)
    via = "launcher" if how == "token" else "web"
    pid = lambda: store.by_pid(doc.get("pid"))   # noqa: E731
    try:
        if sub == "profile":
            p = store.set_profile(acct, {k: doc[k] for k in ("name", "main", "show_main", "offline") if k in doc})
            return _json(h, 200, {"ok": True, "me": {k: p[k] for k in ("pid", "name", "tag", "main", "show_main", "offline")}})
        if sub == "request":
            return _json(h, 200, {"ok": True, "text": store.request(acct, doc.get("to"))})
        if sub == "accept":
            return _json(h, 200, {"ok": True, "text": store.accept(acct, pid())})
        if sub == "decline":
            return _json(h, 200, {"ok": True, "text": store.decline(acct, pid())})
        if sub == "remove":
            return _json(h, 200, {"ok": True, "text": store.remove(acct, pid())})
        if sub == "block":
            other = pid() if doc.get("pid") else store.find(acct, doc.get("to"))[0]
            return _json(h, 200, {"ok": True, "text": store.block(acct, other)})
        if sub == "unblock":
            return _json(h, 200, {"ok": True, "text": store.unblock(acct, pid())})
        if sub == "send":
            return _json(h, 200, {"ok": True, "message": store.send(acct, store.by_pid(doc.get("to")), doc.get("text"), via)})
        if sub == "read":
            store.mark_read(acct, store.by_pid(doc.get("with")))
            return _json(h, 200, {"ok": True})
        if sub == "report":
            return _json(h, 200, {"ok": True, "text": store.report(acct, pid(), doc.get("reason"), doc.get("note"), via)})
        if sub == "token/revoke" and how == "token":
            store.revoke(acct, tok=extra)
            store.seen.pop(acct, None)
            store.touch_circle(acct)
            return _json(h, 200, {"ok": True})
    except SocialError as e:
        return _json(h, e.status, {"error": e.text})
    _json(h, 404, {"error": "Unknown call."})


# ------------------------------------------------------------------ /wrath/link: approve a launcher, list and revoke
LINK_CSS = """
.sl{max-width:560px;margin:0 auto}.sl .code{font:600 2rem/1.2 ui-monospace,monospace;letter-spacing:.12em;text-align:center;margin:.6em 0}
.sl form{display:inline}.sl .row{display:flex;gap:.6em;justify-content:center;margin:1em 0;flex-wrap:wrap}
.sl table{width:100%;border-collapse:collapse}.sl td{padding:.4em .2em;border-top:1px solid rgba(255,255,255,.08)}
.sl input[type=text]{font:inherit;padding:.4em .6em;width:12em;text-transform:uppercase}
"""


def _page(h, status: int, title: str, inner: str) -> None:
    try:
        body = P("ly_shell")(f"{title} · Leyline", f'<section class="ly-panel sl">{inner}</section>', LINK_PAGE, "", "",
                             LINK_CSS, noindex=True)
    except Exception:   # noqa: BLE001
        body = (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
                f"<style>{LINK_CSS}</style><main class=sl>{inner}</main>").encode("utf-8")
    h.send(status, body)


def _form_token(sess: str, action: str) -> str:
    return hmac.new(store.key, ("link|" + sess + "|" + action).encode(), hashlib.sha256).hexdigest()[:32]


def _signin(h, code: str = "") -> None:
    nxt = LINK_PAGE + (f"?code={code}" if code else "")
    h.redirect("/login?next=" + urllib.parse.quote(nxt, safe=""))


def link_page(h, query: dict, note: str = "") -> None:
    e = html.escape
    raw = (query.get("code") or [""])[0]
    code = store.device_lookup(raw)
    shown = (code[:4] + "-" + code[4:]) if code else ""
    try:
        who = cookie_user(h)
    except OSError:
        return _page(h, 503, "Link the launcher", "<h1>Link the launcher</h1><p>The website isn't answering right now. Try again shortly.</p>")
    if who is None:
        return _signin(h, shown or (raw if CODE_RE.fullmatch(raw or "") else ""))
    acct, _display = who
    sess = _session(h.headers.get("Cookie", ""))
    p = store.ensure(acct, _display)
    parts = [f"<h1>Link the Leyline launcher</h1>"]
    if note:
        parts.append(f"<p><b>{e(note)}</b></p>")
    if code:
        parts.append(
            f"<p>Your Leyline launcher on this computer shows this code. Only approve it if it's the same:</p>"
            f'<p class="code">{e(shown)}</p>'
            f"<p>The launcher gets a sign-in for friends and messages as <b>{e(p['name'])}#{e(p['tag'])}</b>. "
            "It never sees your password, and you can revoke it here any time.</p>"
            '<div class="row">'
            f'<form method="post" action="{LINK_PAGE}"><input type="hidden" name="code" value="{e(code)}">'
            f'<input type="hidden" name="t" value="{_form_token(sess, "approve:" + code)}">'
            '<button class="ly-btn" name="do" value="approve">Approve</button></form>'
            f'<form method="post" action="{LINK_PAGE}"><input type="hidden" name="code" value="{e(code)}">'
            f'<input type="hidden" name="t" value="{_form_token(sess, "deny:" + code)}">'
            '<button class="ly-btn ghost" name="do" value="deny">Not me</button></form></div>')
    elif raw:
        parts.append("<p>That code has expired or was already used. Start again from the launcher.</p>")
    else:
        parts.append(f'<form method="get" action="{LINK_PAGE}"><p>Type the code your launcher shows: '
                     '<input type="text" name="code" maxlength="9" autocomplete="off" required> '
                     '<button class="ly-btn">Next</button></p></form>')
    toks = store.tokens(acct)
    if toks:
        rows = "".join(
            f'<tr><td>{e(t["label"])}<br><small>last used {time.strftime("%Y-%m-%d", time.gmtime(t["used"]))}</small></td>'
            f'<td><form method="post" action="{LINK_PAGE}"><input type="hidden" name="id" value="{e(t["id"])}">'
            f'<input type="hidden" name="t" value="{_form_token(sess, "revoke:" + t["id"])}">'
            '<button class="ly-btn ghost" name="do" value="revoke">Revoke</button></form></td></tr>' for t in toks)
        parts.append(f"<h2>Linked launchers</h2><table>{rows}</table>")
    _page(h, 200, "Link the launcher", "".join(parts))


def link_post(h) -> None:
    origin = h.headers.get("Origin", "")
    if (origin and origin != f"https://{P('PUBLIC_HOST')}") or h.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return _page(h, 403, "Link the launcher", "<p>That form came from another site.</p>")
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        n = -1
    if n < 0 or n > 2048:
        return _page(h, 413, "Link the launcher", "<p>Too large.</p>")
    form = dict(urllib.parse.parse_qsl(h.rfile.read(n).decode("utf-8", "replace"), max_num_fields=10))
    try:
        who = cookie_user(h)
    except OSError:
        return _page(h, 503, "Link the launcher", "<p>The website isn't answering right now. Try again shortly.</p>")
    if who is None:
        return _signin(h)
    acct = who[0]
    sess = _session(h.headers.get("Cookie", ""))
    if not store.lim_ip.hit("link|" + acct, 30):
        return _page(h, 429, "Link the launcher", "<p>Too many tries. Wait a few minutes.</p>")
    act, code, tid = form.get("do", ""), store.device_lookup(form.get("code")), form.get("id", "")
    want = f"{act}:{code}" if act in ("approve", "deny") else f"revoke:{tid}"
    if not hmac.compare_digest(form.get("t", ""), _form_token(sess, want)):
        return link_page(h, {}, "That form timed out. Try again.")
    if act in ("approve", "deny"):
        if not code or not store.device_answer(code, acct, act == "approve"):
            return link_page(h, {}, "That code has expired. Start again from the launcher.")
        return link_page(h, {}, "Done: go back to the launcher." if act == "approve" else "Refused. The launcher was not linked.")
    if act == "revoke":
        ok = store.revoke(acct, short_id=tid)
        if ok:
            store.seen.pop(acct, None)
            store.touch_circle(acct)
        return link_page(h, {}, "Revoked: that launcher is signed out." if ok else "Already gone.")
    link_page(h, {})
