"""The Leyline forum: a minimalist place to share and consolidate (stream/wrath_portal.py hooks it in).

Owner, 2026-10-30: "change community to forum and build out a minimalist forum category for people to share and
consolidate" (and the friends area goes, in favour of the Discord). The categories are fixed (CATEGORIES): Share your
realm, Mods & addons, Dens & builds, Help, General and Announcements (only staff start threads there).

Who is who: the website's own sign-in (the wr_session cookie, Hero Key or Google, checked through /api/me and /api/play,
exactly like stream/social.py). No accounts are made here. A poster's name is their Leyline profile name and #tag from
stream/social.py when it is on this portal (else the website's display name, cleaned); staff are whoever the admin
console says (stream/admin.py role_of). Reading needs no sign-in.

Pages (the hub's look, stream/hub.py; no script):
    GET  /wrath/leyline/forum                   the categories, the latest threads, title search
    GET  /wrath/leyline/forum/c/<cat>[?page=N]  one category: pinned threads first, then the latest bumped
    GET  /wrath/leyline/forum/t/<id>[?page=N]   one thread (a merged thread sends a 301 to the one it went into)
    GET  /wrath/leyline/forum/t/<id>/reply      the reply form on its own (the launcher's Reply opens it)
    GET  /wrath/leyline/forum/new[?c=<cat>]     the new-thread form
    GET  /wrath/leyline/forum/search?q=         title search
    GET  /wrath/leyline/forum/report?p=<post>   report a post
    POST /wrath/leyline/forum/new | /t/<id>/reply | /report     (form fields + the form token "t")
JSON, read only, CORS * (the launcher's Forum page reads it through its http command):
    GET  /wrath/forum/api/categories            {format, categories: [{id, name, line, staff_only, threads, posts, last}]}
    GET  /wrath/forum/api/latest?n=             {threads: [...]}   (n <= 20)
    GET  /wrath/forum/api/threads?cat=&page=    {cat, threads: [...], page, more}
    GET  /wrath/forum/api/thread?id=&page=      {thread, posts: [{id, author, tag, staff, at, hidden, text, parts}], page, more}
    GET  /wrath/forum/api/search?q=             {q, threads: [...]}
  a thread: {id, cat, title, author, tag, created, bumped, replies, pinned, locked, url}; parts: the text cut into
  [{"t": text} | {"u": url}] so a client can make the links without parsing.

Text: plain text only. Links (http and https) are made clickable with rel="nofollow ugc noopener noreferrer"; an
image address is just a link (nothing is uploaded here, nothing is embedded). No HTML. Titles 4-100 characters, posts
up to 5000. The realm's word filter (social.py bad_word/mask) refuses names and titles and stars words out of posts;
game and company names are refused in titles (hub.py banned, the same rule as names everywhere) and replaced in posts.

Rate limits, per account, from the database (a restart doesn't reset them): a gap between posts, threads and posts an
hour and a day, and the number of links in one post. An account new to the forum (first seen less than
WU_FORUM_NEW_HOURS ago, default 72) gets the stricter set (LIMITS["new"]).

Moderation: Report on every post (reasons REASONS, 10 a day). Staff hide or show posts and threads, lock, pin and merge
a duplicate thread into another from the admin console's Forum tab (stream/admin.py), which reads Forum.reports() and
calls the store's moderation methods. Nothing is deleted: hidden posts stay in the database.

Storage: SQLite in $WU_PORTAL_DATA (default /data), forum.sqlite3; the form key in forum.key (0600) unless
WU_FORM_SECRET is set. Settings: WU_FORUM=0 (off), WU_FORUM_NEW_HOURS. Standard library only.
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

try:
    import sqlite3
except ImportError:   # an image without it: the portal runs without the forum
    sqlite3 = None

log = logging.getLogger("wrath-portal.forum")

PAGE = "/wrath/leyline/forum"
API = "/wrath/forum/api"
PREVIEW = "/wrath/leyline-preview/forum"   # the hub's preview address: sends a 301 to PAGE

# (id, name, one line, staff only). TODO(owner): the category names and lines.
CATEGORIES = (
    ("realms", "Share your realm", "Realms you host and invite links to public realms.", False),
    ("mods", "Mods & addons", "Share what you made or found, ask for a mod, swap tips.", False),
    ("dens", "Dens & builds", "Show your Den and your builds. Screenshots as links.", False),
    ("help", "Help", "Stuck with the launcher, hosting or a realm? Ask here.", False),
    ("general", "General", "Everything else.", False),
    ("news", "Announcements", "News from the Leyline team.", True),
)
CAT = {c[0]: c for c in CATEGORIES}
REASONS = (("spam", "Spam or advertising"), ("harassment", "Harassment"), ("hate", "Hate"),
           ("unsafe", "A harmful or scam link"), ("off-topic", "Off topic"), ("other", "Something else"))
REASON = dict(REASONS)
TITLE_MIN, TITLE_MAX = 4, 100
BODY_MAX = 5000
NOTE_MAX = 300
PER_PAGE = 30
FORM_MAX = 16384
LIMITS = {   # gap: seconds between posts; thread_h/d: new threads an hour/day; post_h/d: posts (threads too); links per post
    "normal": {"gap": 15, "thread_h": 5, "thread_d": 15, "post_h": 40, "post_d": 200, "links": 10},
    "new": {"gap": 60, "thread_h": 1, "thread_d": 3, "post_h": 8, "post_d": 25, "links": 2},
}
REPORTS_PER_DAY = 10
ACCT_RE = re.compile(r"^[A-Z0-9]{1,16}$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)
BRAND_RE = re.compile(r"(?i:world\s*of\s*warcraft|warcraft|lich\s*king|blizzard)|(?i:(?<![a-z])wow(?![a-z]))"
                      r"|WoW|WOW|(?<![a-z])Wow(?=[A-Z0-9])|(?<=[a-z])Wow(?![a-z])")


def _now() -> float:
    return time.time()


# ------------------------------------------------------------------------------------------- text
def clean_line(v, n: int) -> str:
    if not isinstance(v, str):
        return ""
    return re.sub(r"\s+", " ", CTRL_RE.sub(" ", v)).strip()[:n]


def clean_body(v, n: int = BODY_MAX + 1) -> str:
    """Plain text with its line breaks: control characters out, at most two empty lines in a row."""
    if not isinstance(v, str):
        return ""
    s = CTRL_RE.sub("", v.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    "))
    s = re.sub(r"[  ]+\n", "\n", s)
    s = re.sub(r"\n{4,}", "\n\n\n", s).strip()
    return s[:n]


def _url_end(u: str) -> str:
    """A link without the punctuation that ends the sentence around it."""
    while u and u[-1] in ".,;:!?'\"":
        u = u[:-1]
    if u.endswith(")") and u.count("(") < u.count(")"):
        u = u[:-1]
    return u


def parts(text: str) -> list[dict]:
    """The text cut into [{"t": text} | {"u": url}] (http and https only)."""
    out, at = [], 0
    for m in URL_RE.finditer(text or ""):
        u = _url_end(m.group(0))
        if len(u) < 12:
            continue
        if m.start() > at:
            out.append({"t": text[at:m.start()]})
        out.append({"u": u})
        at = m.start() + len(u)
    if at < len(text or ""):
        out.append({"t": text[at:]})
    return out


def links_in(text: str) -> int:
    return sum(1 for p in parts(text) if "u" in p)


def unbrand(text: str) -> str:
    """Game and company names in a post replaced (outside links): "Lich King" -> "Wrath", "Blizzard" -> "the
    publisher", the rest -> "the game"."""
    def rep(m):
        w = m.group(0).lower()
        return "Wrath" if "lich" in w else ("the publisher" if "blizzard" in w else "the game")
    out = []
    for p in parts(text):
        if "u" in p:
            out.append(p["u"])
        else:
            t = re.sub(r"(?i)\bwrath\s+of\s+the\s+lich\s*king\b", "Wrath", p["t"])
            out.append(BRAND_RE.sub(rep, t))
    return "".join(out)


def render(text: str) -> str:
    """Escaped HTML with the links made clickable (the CSS keeps the line breaks: white-space: pre-wrap)."""
    e = html.escape
    out = []
    for p in parts(text):
        if "u" in p:
            u = p["u"]
            shown = u if len(u) <= 70 else u[:60] + "…" + u[-8:]
            out.append(f'<a href="{e(u)}" rel="nofollow ugc noopener noreferrer">{e(shown)}</a>')
        else:
            out.append(e(p["t"]))
    return "".join(out)


class ForumError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status, self.text = status, text


SCHEMA = """
CREATE TABLE IF NOT EXISTS forum_users (
  acct TEXT PRIMARY KEY, name TEXT NOT NULL, tag TEXT NOT NULL DEFAULT '', first INTEGER NOT NULL, last INTEGER NOT NULL,
  staff INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS forum_threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cat TEXT NOT NULL, title TEXT NOT NULL, title_lc TEXT NOT NULL, author TEXT NOT NULL,
  created INTEGER NOT NULL, bumped INTEGER NOT NULL, replies INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
  locked INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, merged_into INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS forum_threads_cat ON forum_threads (cat, pinned, bumped);
CREATE INDEX IF NOT EXISTS forum_threads_bumped ON forum_threads (bumped);
CREATE TABLE IF NOT EXISTS forum_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread INTEGER NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL,
  created INTEGER NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, opener INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS forum_posts_thread ON forum_posts (thread, created, id);
CREATE INDEX IF NOT EXISTS forum_posts_author ON forum_posts (author, created);
CREATE TABLE IF NOT EXISTS forum_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, reporter TEXT NOT NULL, post INTEGER NOT NULL,
  reason TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
  handled_by TEXT NOT NULL DEFAULT '', handled_at INTEGER NOT NULL DEFAULT 0, outcome TEXT NOT NULL DEFAULT '',
  UNIQUE (reporter, post));
CREATE INDEX IF NOT EXISTS forum_reports_status ON forum_reports (status, id);
"""


class Forum:
    """The store: categories, threads, posts, reports, limits and the staff tools. Thread-safe (one connection, one lock)."""

    def __init__(self, data_dir: str | None = None, clock=_now, db_file: str | None = None):
        if sqlite3 is None:
            raise RuntimeError("sqlite3 is missing")
        self.dir = data_dir or os.environ.get("WU_PORTAL_DATA", "/data")
        self.path = db_file or os.path.join(self.dir, "forum.sqlite3")
        self.clock = clock
        try:
            self.new_hours = max(0, int(os.environ.get("WU_FORUM_NEW_HOURS", "72") or 72))
        except ValueError:
            self.new_hours = 72
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.key = self._key()

    def _key(self) -> bytes:
        env = os.environ.get("WU_FORM_SECRET", "")
        if env:
            return ("forum|" + env).encode()
        p = os.path.join(self.dir, "forum.key")
        try:
            with open(p, "rb") as f:
                k = f.read(64)
            if len(k) >= 32:
                return k
        except OSError:
            pass
        k = secrets.token_bytes(32)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(k)
        except OSError:
            pass   # in memory only: a form made before a restart then asks again
        return k

    def now(self) -> int:
        return int(self.clock())

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

    # ------------------------------------------------------------------ people
    def seen(self, acct: str, name: str, tag: str = "", staff: bool = False) -> None:
        """The account is here (signed in): remember its name now and when the forum first saw it."""
        if not ACCT_RE.fullmatch(acct or ""):
            raise ForumError(400, "Unknown account.")
        t = self.now()
        with self.lock:
            if self.one("SELECT 1 FROM forum_users WHERE acct = ?", (acct,)):
                self.x("UPDATE forum_users SET name = ?, tag = ?, last = ?, staff = ? WHERE acct = ?",
                       (name or "Player", tag or "", t, 1 if staff else 0, acct))
            else:
                self.x("INSERT INTO forum_users (acct, name, tag, first, last, staff) VALUES (?,?,?,?,?,?)",
                       (acct, name or "Player", tag or "", t, t, 1 if staff else 0))

    def is_new(self, acct: str) -> bool:
        r = self.one("SELECT first FROM forum_users WHERE acct = ?", (acct,))
        return r is None or self.now() - r[0] < self.new_hours * 3600

    def limits(self, acct: str) -> dict:
        return LIMITS["new" if self.is_new(acct) else "normal"]

    def check_rate(self, acct: str, thread: bool, links: int) -> None:
        lim = self.limits(acct)
        t = self.now()
        if links > lim["links"]:
            raise ForumError(400, f"At most {lim['links']} link{'s' if lim['links'] != 1 else ''} in one post"
                             + (" while your account is new here." if lim is LIMITS["new"] else "."))
        last = self.one("SELECT MAX(created) FROM forum_posts WHERE author = ?", (acct,))[0]
        if last is not None and t - last < lim["gap"]:
            raise ForumError(429, f"Wait {lim['gap'] - (t - last)} seconds before posting again.")
        ph = self.one("SELECT COUNT(*) FROM forum_posts WHERE author = ? AND created > ?", (acct, t - 3600))[0]
        pd = self.one("SELECT COUNT(*) FROM forum_posts WHERE author = ? AND created > ?", (acct, t - 86400))[0]
        if ph >= lim["post_h"] or pd >= lim["post_d"]:
            raise ForumError(429, "That's a lot of posts for now. Try again later."
                             + (" New accounts have a lower limit for their first days." if lim is LIMITS["new"] else ""))
        if thread:
            th = self.one("SELECT COUNT(*) FROM forum_threads WHERE author = ? AND created > ?", (acct, t - 3600))[0]
            td = self.one("SELECT COUNT(*) FROM forum_threads WHERE author = ? AND created > ?", (acct, t - 86400))[0]
            if th >= lim["thread_h"] or td >= lim["thread_d"]:
                raise ForumError(429, "That's a lot of new threads for now. Reply in one, or try again later."
                                 + (" New accounts have a lower limit for their first days." if lim is LIMITS["new"] else ""))

    # ------------------------------------------------------------------ the rules for what is written
    def title_ok(self, v) -> str:
        t = clean_line(v, TITLE_MAX + 1)
        if len(t) < TITLE_MIN:
            raise ForumError(400, f"Give the thread a title of at least {TITLE_MIN} characters.")
        if len(t) > TITLE_MAX:
            raise ForumError(400, f"Titles are at most {TITLE_MAX} characters.")
        if BRAND_RE.search(t) or _hook("banned", t):
            raise ForumError(400, "Leave game and company names out of the title.")
        if _hook("bad_word", t):
            raise ForumError(400, "Pick another title.")
        if URL_RE.search(t):
            raise ForumError(400, "Put links in the post, not the title.")
        return t

    def body_ok(self, v) -> str:
        b = clean_body(v)
        if not b:
            raise ForumError(400, "Write something first.")
        if len(b) > BODY_MAX:
            raise ForumError(400, f"Posts are at most {BODY_MAX} characters.")
        b = unbrand(b)
        masked = _hook("mask", b)
        return masked if isinstance(masked, str) and len(masked) == len(b) else b

    # ------------------------------------------------------------------ writing
    def new_thread(self, acct: str, cat, title, body, staff: bool = False) -> int:
        if cat not in CAT:
            raise ForumError(400, "Pick a category.")
        if CAT[cat][3] and not staff:
            raise ForumError(403, "Only the Leyline team posts in Announcements.")
        t, b = self.title_ok(title), self.body_ok(body)
        if not staff:
            self.check_rate(acct, True, links_in(b))
        now = self.now()
        with self.lock:
            tid = self.x("INSERT INTO forum_threads (cat, title, title_lc, author, created, bumped) VALUES (?,?,?,?,?,?)",
                         (cat, t, t.lower(), acct, now, now))
            self.x("INSERT INTO forum_posts (thread, author, body, created, opener) VALUES (?,?,?,?,1)", (tid, acct, b, now))
        log.info("forum: new thread %d in %s", tid, cat)
        return tid

    def reply(self, acct: str, tid, body, staff: bool = False) -> int:
        th = self.thread(tid)
        if not th or th["hidden"] or th["merged_into"]:
            raise ForumError(404, "That thread isn't here any more.")
        if th["locked"] and not staff:
            raise ForumError(403, "This thread is locked.")
        b = self.body_ok(body)
        if not staff:
            self.check_rate(acct, False, links_in(b))
        now = self.now()
        with self.lock:
            pid = self.x("INSERT INTO forum_posts (thread, author, body, created) VALUES (?,?,?,?)", (th["id"], acct, b, now))
            self.recount(th["id"])
        return pid

    def recount(self, tid: int) -> None:
        with self.lock:
            n = self.one("SELECT COUNT(*), MAX(created) FROM forum_posts WHERE thread = ? AND hidden = 0", (tid,))
            self.x("UPDATE forum_threads SET replies = ?, bumped = COALESCE(?, bumped) WHERE id = ?",
                   (max(0, (n[0] or 0) - 1), n[1], tid))

    def report(self, acct: str, post_id, reason, note) -> str:
        p = self.post(post_id)
        if not p:
            raise ForumError(404, "That post isn't here any more.")
        if reason not in REASON:
            raise ForumError(400, "Pick a reason.")
        if p["author"] == acct:
            raise ForumError(400, "That's your own post.")
        n = self.one("SELECT COUNT(*) FROM forum_reports WHERE reporter = ? AND at > ?", (acct, self.now() - 86400))[0]
        if n >= REPORTS_PER_DAY:
            raise ForumError(429, "You've sent a lot of reports today. The moderators will look at them.")
        try:
            self.x("INSERT INTO forum_reports (at, reporter, post, reason, note) VALUES (?,?,?,?,?)",
                   (self.now(), acct, p["id"], reason, clean_line(note or "", NOTE_MAX)))
        except sqlite3.IntegrityError:
            return "You already reported this post. Thanks."
        log.info("forum report filed (%s)", reason)
        return "Thanks. The moderators will look at it."

    # ------------------------------------------------------------------ reading
    _TCOLS = ("t.id, t.cat, t.title, t.author, t.created, t.bumped, t.replies, t.pinned, t.locked, t.hidden, t.merged_into, "
              "COALESCE(u.name, 'Player'), COALESCE(u.tag, '')")

    @staticmethod
    def _t(r) -> dict:
        return {"id": r[0], "cat": r[1], "title": r[2], "author_acct": r[3], "created": r[4], "bumped": r[5], "replies": r[6],
                "pinned": bool(r[7]), "locked": bool(r[8]), "hidden": bool(r[9]), "merged_into": r[10], "author": r[11],
                "tag": r[12]}

    def thread(self, tid) -> dict | None:
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            return None
        r = self.one(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author WHERE t.id = ?", (tid,))
        return self._t(r) if r else None

    def resolve(self, tid) -> dict | None:
        """The thread, following merges (at most 8 hops)."""
        th = self.thread(tid)
        for _ in range(8):
            if not th or not th["merged_into"]:
                return th
            th = self.thread(th["merged_into"])
        return th

    _LIVE = "t.hidden = 0 AND t.merged_into = 0"

    def threads(self, cat: str, page: int = 1) -> tuple[list[dict], bool]:
        off = (max(1, page) - 1) * PER_PAGE
        rows = self.q(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author "
                      f"WHERE t.cat = ? AND {self._LIVE} ORDER BY t.pinned DESC, t.bumped DESC, t.id DESC LIMIT ? OFFSET ?",
                      (cat, PER_PAGE + 1, off))
        return [self._t(r) for r in rows[:PER_PAGE]], len(rows) > PER_PAGE

    def latest(self, n: int = 8) -> list[dict]:
        rows = self.q(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author "
                      f"WHERE {self._LIVE} ORDER BY t.bumped DESC, t.id DESC LIMIT ?", (max(1, min(int(n), 50)),))
        return [self._t(r) for r in rows]

    def search(self, text, n: int = 50) -> list[dict]:
        s = clean_line(text, 60).lower()
        if len(s) < 2:
            return []
        like = "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.q(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author "
                      f"WHERE {self._LIVE} AND t.title_lc LIKE ? ESCAPE '\\' ORDER BY t.bumped DESC LIMIT ?", (like, n))
        return [self._t(r) for r in rows]

    def categories(self) -> list[dict]:
        out = []
        for cid, name, line, staff in CATEGORIES:
            n = self.one(f"SELECT COUNT(*), COALESCE(SUM(t.replies + 1), 0) FROM forum_threads t WHERE t.cat = ? AND {self._LIVE}", (cid,))
            last = self.q(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author "
                          f"WHERE t.cat = ? AND {self._LIVE} ORDER BY t.bumped DESC LIMIT 1", (cid,))
            out.append({"id": cid, "name": name, "line": line, "staff_only": staff, "threads": n[0], "posts": n[1],
                        "last": self._t(last[0]) if last else None})
        return out

    def post(self, pid) -> dict | None:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return None
        r = self.one("SELECT p.id, p.thread, p.author, p.body, p.created, p.hidden, p.opener, COALESCE(u.name, 'Player'), "
                     "COALESCE(u.tag, ''), COALESCE(u.staff, 0) FROM forum_posts p LEFT JOIN forum_users u ON u.acct = p.author WHERE p.id = ?", (pid,))
        return self._p(r) if r else None

    @staticmethod
    def _p(r) -> dict:
        return {"id": r[0], "thread": r[1], "author": r[2], "body": r[3], "created": r[4], "hidden": bool(r[5]),
                "opener": bool(r[6]), "name": r[7], "tag": r[8], "staff": bool(r[9])}

    def posts(self, tid: int, page: int = 1) -> tuple[list[dict], bool, int]:
        """(posts, more, pages): oldest first."""
        total = self.one("SELECT COUNT(*) FROM forum_posts WHERE thread = ?", (tid,))[0]
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        off = (max(1, page) - 1) * PER_PAGE
        rows = self.q("SELECT p.id, p.thread, p.author, p.body, p.created, p.hidden, p.opener, COALESCE(u.name, 'Player'), "
                      "COALESCE(u.tag, ''), COALESCE(u.staff, 0) FROM forum_posts p LEFT JOIN forum_users u ON u.acct = p.author "
                      "WHERE p.thread = ? ORDER BY p.created, p.id LIMIT ? OFFSET ?", (tid, PER_PAGE, off))
        return [self._p(r) for r in rows], off + PER_PAGE < total, pages

    def page_of(self, pid: int) -> int:
        p = self.post(pid)
        if not p:
            return 1
        n = self.one("SELECT COUNT(*) FROM forum_posts WHERE thread = ? AND (created < ? OR (created = ? AND id < ?))",
                     (p["thread"], p["created"], p["created"], p["id"]))[0]
        return n // PER_PAGE + 1

    # ------------------------------------------------------------------ the staff tools (stream/admin.py's Forum tab)
    def set_thread(self, tid, field: str, on: bool) -> tuple[dict, dict]:
        if field not in ("pinned", "locked", "hidden"):
            raise ForumError(400, "Unknown change.")
        th = self.thread(tid)
        if not th:
            raise ForumError(404, "No such thread.")
        self.x(f"UPDATE forum_threads SET {field} = ? WHERE id = ?", (1 if on else 0, th["id"]))
        return {field: th[field]}, {field: bool(on)}

    def set_post_hidden(self, pid, on: bool) -> tuple[dict, dict]:
        p = self.post(pid)
        if not p:
            raise ForumError(404, "No such post.")
        self.x("UPDATE forum_posts SET hidden = ? WHERE id = ?", (1 if on else 0, p["id"]))
        self.recount(p["thread"])
        return {"hidden": p["hidden"]}, {"hidden": bool(on)}

    def merge(self, src, dst) -> tuple[dict, dict]:
        """Thread src (a duplicate) into dst: its posts move over in time order, src then sends readers to dst."""
        a, b = self.thread(src), self.resolve(dst)
        if not a or not b:
            raise ForumError(404, "No such thread.")
        if a["merged_into"]:
            raise ForumError(400, "That thread was already merged.")
        if a["id"] == b["id"]:
            raise ForumError(400, "A thread can't be merged into itself.")
        with self.lock:
            self.x("UPDATE forum_posts SET thread = ?, opener = 0 WHERE thread = ?", (b["id"], a["id"]))
            self.x("UPDATE forum_threads SET merged_into = ?, replies = 0, pinned = 0 WHERE id = ?", (b["id"], a["id"]))
            self.recount(b["id"])
        return {"thread": a["id"], "title": a["title"]}, {"merged_into": b["id"]}

    def staff_threads(self, text: str = "", n: int = 60) -> list[dict]:
        s = clean_line(text, 60).lower()
        if s:
            like = "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = self.q(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author "
                          "WHERE t.merged_into = 0 AND t.title_lc LIKE ? ESCAPE '\\' ORDER BY t.bumped DESC LIMIT ?", (like, n))
        else:
            rows = self.q(f"SELECT {self._TCOLS} FROM forum_threads t LEFT JOIN forum_users u ON u.acct = t.author "
                          "WHERE t.merged_into = 0 ORDER BY t.pinned DESC, t.bumped DESC LIMIT ?", (n,))
        return [self._t(r) for r in rows]

    def hidden_posts(self, n: int = 50) -> list[dict]:
        rows = self.q("SELECT p.id, p.thread, p.author, p.body, p.created, p.hidden, p.opener, COALESCE(u.name, 'Player'), "
                      "COALESCE(u.tag, ''), COALESCE(u.staff, 0) FROM forum_posts p LEFT JOIN forum_users u ON u.acct = p.author "
                      "WHERE p.hidden = 1 ORDER BY p.id DESC LIMIT ?", (n,))
        return [self._p(r) for r in rows]

    def reports(self, status: str = "open", limit: int = 100) -> list[dict]:
        rows = self.q("SELECT r.id, r.at, r.reporter, r.post, r.reason, r.note, r.status, r.handled_by, r.handled_at, r.outcome, "
                      "COALESCE(u.name, '') FROM forum_reports r LEFT JOIN forum_users u ON u.acct = r.reporter "
                      "WHERE (? = '' OR r.status = ?) ORDER BY r.id DESC LIMIT ?",
                      (status or "", status or "", max(1, min(int(limit), 1000))))
        out = []
        for r in rows:
            p = self.post(r[3]) or {}
            th = self.thread(p.get("thread")) or {}
            out.append({"id": r[0], "at": r[1], "reporter": r[2], "reporter_name": r[10], "post": r[3], "reason": r[4],
                        "note": r[5], "status": r[6], "handled_by": r[7], "handled_at": r[8], "outcome": r[9],
                        "post_body": p.get("body", ""), "post_hidden": p.get("hidden", False), "author": p.get("author", ""),
                        "author_name": p.get("name", ""), "thread": th.get("id"), "thread_title": th.get("title", "")})
        return out

    def resolve_report(self, rid: int, by: str, outcome: str, status: str = "done") -> bool:
        if status not in ("done", "dismissed", "open"):
            return False
        return bool(self.x("UPDATE forum_reports SET status = ?, handled_by = ?, handled_at = ?, outcome = ? WHERE id = ?",
                           (status, clean_line(by, 60), self.now(), clean_line(outcome, 300), int(rid))))

    # ------------------------------------------------------------------ the JSON shapes
    def thread_doc(self, th: dict) -> dict:
        return {"id": th["id"], "cat": th["cat"], "title": th["title"], "author": th["author"], "tag": th["tag"],
                "created": th["created"], "bumped": th["bumped"], "replies": th["replies"], "pinned": th["pinned"],
                "locked": th["locked"], "url": f"https://{_public_host()}{PAGE}/t/{th['id']}"}

    def post_doc(self, p: dict) -> dict:
        if p["hidden"]:
            return {"id": p["id"], "author": "", "tag": "", "staff": False, "at": p["created"], "hidden": True,
                    "text": "", "parts": []}
        return {"id": p["id"], "author": p["name"], "tag": p["tag"], "staff": p["staff"],
                "at": p["created"], "hidden": False, "text": p["body"], "parts": parts(p["body"])}


# ----------------------------------------------------------------------------------------------
# The portal's hooks (stream/wrath_portal.py: bind, setup, match, get, post)
# ----------------------------------------------------------------------------------------------
_get = None
store: Forum | None = None
_who_cache: dict[str, tuple[float, dict | None]] = {}


def bind(getter) -> None:
    global _get
    _get = getter


def P(name):
    try:
        return _get(name) if _get else None
    except KeyError:
        return None


def _public_host() -> str:
    return P("PUBLIC_HOST") or "play.openvanilla.app"


def _hook(name: str, text: str):
    """social.py's word filter (bad_word, mask) and hub.py's brand rule (banned), when those modules are here."""
    try:
        if name == "banned":
            hub = P("hub_mod")
            return bool(hub.banned(text)) if hub is not None else False
        soc = P("social")
        if soc is None:
            return None if name == "bad_word" else text
        return getattr(soc, name)(text)
    except Exception:   # noqa: BLE001
        return None if name != "mask" else text


def setup() -> Forum | None:
    global store
    if store is not None:
        return store
    if os.environ.get("WU_FORUM", "1") == "0":
        return None
    try:
        store = Forum()
    except Exception:   # noqa: BLE001: the rest of the portal runs without the forum
        log.exception("forum: off (the store didn't open)")
        return None
    return store


def match(path: str) -> bool:
    return (path in (PAGE, API, PREVIEW) or path.startswith(PAGE + "/") or path.startswith(API + "/")
            or path.startswith(PREVIEW + "/"))


def _session(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "wr_session":
            return v[:512]
    return ""


def viewer(h) -> dict | None:
    """The signed-in website account {acct, name, tag, staff, session}, cached 60 s; None when signed out.
    Raises OSError when the website isn't answering."""
    cookie = h.headers.get("Cookie", "")
    sess = _session(cookie)
    if not sess:
        return None
    key = hashlib.sha256(sess.encode()).hexdigest()
    hit = _who_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    ip, ua = h.ip(), h.headers.get("User-Agent", "")
    status, me = P("portal_get")("/api/me", cookie, ip, ua)
    if status in (401, 403) or 300 <= status < 400:
        return None
    if status != 200 or not isinstance(me, dict) or not me:
        raise OSError(f"api/me answered {status}")
    status, play = P("portal_get")("/api/play", cookie, ip, ua)
    user = str(play.get("user", "")) if isinstance(play, dict) else ""
    if status != 200 or not re.fullmatch(r"[A-Za-z0-9]{1,16}", user):
        raise OSError(f"api/play answered {status}")
    acct = user.upper()
    display = str(me.get("display_name") or me.get("username") or "")
    name, tag = "", ""
    soc = P("social")
    try:
        if soc is not None and getattr(soc, "store", None) is not None:   # the Leyline profile name and #tag
            p = soc.store.ensure(acct, display)
            name, tag = p["name"], p["tag"]
        elif soc is not None:
            name = soc.clean_name(display)
    except Exception:   # noqa: BLE001
        name = ""
    if not name:
        name = re.sub(r"[^A-Za-z0-9_.\-À-ɏ]", "", display)[:24]
        if len(name) < 2 or BRAND_RE.search(name):
            name = "Player"
    staff = False
    adm = P("admin")
    if adm is not None:
        try:
            staff = bool(adm.role_of(adm.account_of(me), lambda: user))
        except Exception:   # noqa: BLE001
            staff = False
    who = {"acct": acct, "name": name, "tag": tag, "staff": staff, "session": sess, "display": display}
    if len(_who_cache) > 5000:
        _who_cache.clear()
    _who_cache[key] = (time.monotonic() + 60, who)
    return who


def form_token(who: dict, action: str) -> str:
    return hmac.new(store.key, f"forum|{who['session']}|{who['acct']}|{action}".encode(), hashlib.sha256).hexdigest()[:32]


def _same_site(h) -> bool:
    """A form POST from our own pages: not cross-site, and the Origin (when sent) is ours. A sandboxed or privacy
    context can send "Origin: null": allowed only when the browser also says Sec-Fetch-Site: same-origin."""
    sfs = h.headers.get("Sec-Fetch-Site", "")
    if sfs == "cross-site":
        return False
    origin = h.headers.get("Origin", "")
    if origin and origin != f"https://{_public_host()}" and not (origin == "null" and sfs == "same-origin"):
        return False
    return True


def _json(h, status: int, doc: dict) -> None:
    h.send(status, json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
           headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=15"} if status == 200 else
           {"Access-Control-Allow-Origin": "*"})


def _int(v, default: int = 1, hi: int = 10 ** 6) -> int:
    try:
        return max(1, min(int(v), hi))
    except (TypeError, ValueError):
        return default


def _limited(h) -> bool:
    lim = P("browse_limit")
    return lim is not None and not lim.hit(h.ip(), 600)


def api(h, sub: str, query: dict) -> None:
    one = lambda k: (query.get(k) or [""])[0]   # noqa: E731
    if sub == "categories":
        cats = store.categories()
        for c in cats:
            c["last"] = store.thread_doc(c["last"]) if c["last"] else None
        return _json(h, 200, {"format": 1, "url": f"https://{_public_host()}{PAGE}", "categories": cats})
    if sub == "latest":
        return _json(h, 200, {"threads": [store.thread_doc(t) for t in store.latest(_int(one("n"), 8, 20))]})
    if sub == "threads":
        cat = one("cat")
        if cat not in CAT:
            return _json(h, 404, {"error": "Unknown category."})
        page = _int(one("page"))
        ts, more = store.threads(cat, page)
        return _json(h, 200, {"cat": cat, "name": CAT[cat][1], "threads": [store.thread_doc(t) for t in ts], "page": page, "more": more})
    if sub == "thread":
        th = store.resolve(one("id"))
        if not th or th["hidden"]:
            return _json(h, 404, {"error": "That thread isn't here."})
        page = _int(one("page"))
        ps, more, pages = store.posts(th["id"], page)
        return _json(h, 200, {"thread": store.thread_doc(th), "posts": [store.post_doc(p) for p in ps], "page": page,
                              "pages": pages, "more": more, "reply_url": f"https://{_public_host()}{PAGE}/t/{th['id']}/reply"})
    if sub == "search":
        return _json(h, 200, {"q": clean_line(one("q"), 60), "threads": [store.thread_doc(t) for t in store.search(one("q"))]})
    _json(h, 404, {"error": "Unknown call."})


# ------------------------------------------------------------------ pages
FORUM_CSS = """
.fm{display:grid;gap:16px}
.fm-head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px 16px}
.fm-head h1{margin:0;font-size:clamp(22px,3vw,28px);font-weight:800}
.fm-head p{margin:4px 0 0;color:var(--lk-text-2)}
.fm-crumb{margin:0 0 2px;font-size:13px;color:var(--lk-muted)}.fm-crumb a{color:var(--lk-text-2);text-decoration:none}
.fm-crumb a:hover{color:var(--lk-text);text-decoration:underline}
.fm-acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.fm-search{display:flex;gap:6px;flex:1 1 260px;max-width:420px}
.fm-search input{flex:1;min-width:0;min-height:40px;padding:8px 12px;border-radius:var(--lk-r-sm);border:1px solid var(--lk-border-strong);
background:var(--lk-surface);color:var(--lk-text);font:inherit}
.fm-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:40px;padding:0 16px;border-radius:var(--lk-r-sm);
border:0;background:var(--lk-accent);color:#fff!important;font:inherit;font-weight:700;text-decoration:none;cursor:pointer}
.fm-btn:hover{background:var(--lk-accent-strong)}
.fm-btn.ghost{background:transparent;border:1px solid var(--lk-border-strong);color:var(--lk-text)!important;font-weight:600}
.fm-btn.ghost:hover{border-color:var(--lk-accent);background:var(--lk-accent-soft)}
.fm-box{border:1px solid var(--lk-border);border-radius:var(--lk-r);background:var(--lk-surface);overflow:hidden}
.fm-box h2{margin:0;padding:12px 16px;font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--lk-accent-strong);
border-bottom:1px solid var(--lk-border)}
.fm-list{margin:0;padding:0;list-style:none}.fm-list li+li{border-top:1px solid var(--lk-border)}
.fm-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 16px;align-items:center;padding:12px 16px;
text-decoration:none;color:var(--lk-text)!important}
a.fm-row:hover{background:var(--lk-surface-2)}
.fm-row b{font-size:15.5px;font-weight:650;overflow-wrap:anywhere}.fm-row small{color:var(--lk-muted);font-size:13px}
.fm-row .fm-n{text-align:right;color:var(--lk-text-2);font-size:13px;white-space:nowrap}
.fm-row .fm-line{grid-column:1/-1;color:var(--lk-text-2);font-size:13.5px}
.fm-tag{display:inline-block;margin-right:6px;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.04em;
vertical-align:2px;background:var(--lk-accent-soft);color:var(--lk-accent-strong)}
.fm-tag.lock{background:rgba(255,127,118,.14);color:var(--lk-bad)}
.fm-empty{margin:0;padding:18px 16px;color:var(--lk-muted)}
.fm-post{padding:14px 16px}.fm-post+.fm-post{border-top:1px solid var(--lk-border)}
.fm-by{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin:0 0 8px;font-size:13px;color:var(--lk-muted)}
.fm-by b{color:var(--lk-text);font-size:14.5px}.fm-by .fm-av{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;
font-weight:800;font-size:13px;color:#fff;background:linear-gradient(135deg,var(--lk-accent),var(--lk-accent-2))}
.fm-by img.fm-av{display:block;object-fit:cover;background:none}
.fm-by .fm-team{padding:1px 7px;border-radius:999px;background:var(--lk-accent);color:#fff;font-size:11px;font-weight:700}
.fm-by a{margin-left:auto;color:var(--lk-muted);font-size:12.5px}
.fm-text{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6;color:var(--lk-text)}
.fm-text a{color:var(--lk-accent-strong)}
.fm-gone{margin:0;color:var(--lk-muted);font-style:italic}
.fm-form{display:grid;gap:8px;padding:16px}
.fm-form label{font-weight:600}
.fm-form input,.fm-form select,.fm-form textarea{width:100%;min-height:40px;padding:8px 12px;border-radius:var(--lk-r-sm);
border:1px solid var(--lk-border-strong);background:var(--lk-bg);color:var(--lk-text);font:inherit}
.fm-form textarea{min-height:160px;resize:vertical;line-height:1.55}
.fm-form .fm-acts{margin-top:4px}
.fm-fine{margin:0;color:var(--lk-muted);font-size:13px}
.fm-msg{margin:0;padding:10px 14px;border-radius:var(--lk-r-sm);background:var(--lk-accent-soft);border:1px solid var(--lk-accent)}
.fm-msg.err{background:rgba(255,127,118,.12);border-color:var(--lk-bad)}
.fm-pages{display:flex;gap:14px;justify-content:center;margin:0;font-size:14px}
.fm-dc{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 18px;padding:16px 18px;border-radius:var(--lk-r);
border:1px solid var(--lk-border-strong);background:linear-gradient(120deg,rgba(91,141,239,.16),rgba(139,108,240,.10) 60%,rgba(20,23,31,.55))}
.fm-dc p{margin:0;flex:1 1 260px;color:var(--lk-text-2)}.fm-dc b{color:var(--lk-text)}
@media (max-width:560px){.fm-row{grid-template-columns:minmax(0,1fr)}.fm-row .fm-n{text-align:left}.fm-head .fm-acts{width:100%}}
"""


def _ago(t: int) -> str:
    d = max(0, int(store.clock()) - int(t or 0))
    if d < 60:
        return "just now"
    for n, w in ((86400 * 30, "month"), (86400 * 7, "week"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if d >= n:
            k = d // n
            return f"{k} {w}{'s' if k != 1 else ''} ago"
    return "just now"


def _shell(h, title: str, body: str, path: str, who, status: int = 200) -> None:
    hub = P("hub_mod")
    page = f'<div class="fm">{body}</div>'
    if hub is not None and getattr(hub, "hub", None) is not None:
        try:
            hub._REQ.who = (who["acct"], who["display"] or who["name"]) if who else None
            out = hub.hub._shell(title, page, path, active="forum", css=FORUM_CSS)
            hh = hub._Live(h) if hub.front_on() else h
            hh.send(status, out, headers={} if hub.front_on() else {"X-Robots-Tag": "noindex, nofollow"})
            return
        except Exception:   # noqa: BLE001: the plain page then
            log.exception("forum: the hub's page failed")
    shell = P("ly_shell")
    if shell is not None:
        h.send(status, shell(title, page, path, "", "", FORUM_CSS, noindex=True))
        return
    h.send(status, (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title><style>{FORUM_CSS}</style>"
                    f"<main>{page}</main>").encode("utf-8"))


def _signin_url(path: str) -> str:
    fn = P("signin_url")   # the Leyline sign-in (stream/profiles.py) when the portal has it
    if callable(fn):
        try:
            return fn(path)
        except Exception:   # noqa: BLE001
            pass
    return "/login?next=" + urllib.parse.quote(path, safe="")


def _avatar(acct: str, name: str) -> str:
    """The poster's picture (stream/profiles.py), else their initial."""
    e = html.escape
    prof = P("profiles")
    if prof is not None and getattr(prof, "store", None) is not None:
        try:
            u = prof.avatar_url(acct)
            if u:
                return f'<img class="fm-av" src="{e(u)}" alt="" width="28" height="28" loading="lazy">'
        except Exception:   # noqa: BLE001
            pass
    return f'<span class="fm-av" aria-hidden="true">{e(name[:1].upper())}</span>'


def _discord_card() -> str:
    d = P("DISCORD_URL") or ""
    if not d.startswith("https://"):
        return ""
    # TODO(owner): the Discord line on the forum
    return (f'<div class="fm-dc"><p><b>Talk live on the Discord.</b> Quick questions, finding a group, voice chat and the '
            f'first word on new realms. The forum keeps the good stuff findable.</p>'
            f'<a class="fm-btn" href="{html.escape(d)}" rel="noopener noreferrer">Join the Discord</a></div>')


def _search_form(q: str = "") -> str:
    return (f'<form class="fm-search" method="get" action="{PAGE}/search" role="search">'
            f'<input type="search" name="q" value="{html.escape(q)}" maxlength="60" placeholder="Search thread titles" aria-label="Search thread titles">'
            '<button class="fm-btn ghost" type="submit">Search</button></form>')


def _thread_rows(ts: list[dict], show_cat: bool = False) -> str:
    e = html.escape
    if not ts:
        return '<p class="fm-empty">No threads here yet. Start the first one.</p>'
    rows = []
    for t in ts:
        tags = ("<span class=\"fm-tag\">Pinned</span>" if t["pinned"] else "") + ("<span class=\"fm-tag lock\">Locked</span>" if t["locked"] else "")
        where = f' in {e(CAT[t["cat"]][1])}' if show_cat and t["cat"] in CAT else ""
        n = t["replies"]
        rows.append(f'<li><a class="fm-row" href="{PAGE}/t/{t["id"]}"><span>{tags}<b>{e(t["title"])}</b><br>'
                    f'<small>by {e(t["author"])}{where} · {_ago(t["created"])}</small></span>'
                    f'<span class="fm-n">{n} repl{"y" if n == 1 else "ies"}<br><small>active {_ago(t["bumped"])}</small></span></a></li>')
    return f'<ul class="fm-list">{"".join(rows)}</ul>'


def page_index(h, who) -> None:
    e = html.escape
    cats = store.categories()
    rows = []
    for c in cats:
        last = c["last"]
        lst = f'Latest: {e(last["title"])}' if last else "Nothing yet"
        rows.append(f'<li><a class="fm-row" href="{PAGE}/c/{c["id"]}"><span><b>{e(c["name"])}</b></span>'
                    f'<span class="fm-n">{c["threads"]} thread{"" if c["threads"] == 1 else "s"} · {c["posts"]} post{"" if c["posts"] == 1 else "s"}</span>'
                    f'<span class="fm-line">{e(c["line"])}<br><small>{lst}</small></span></a></li>')
    new = (f'<a class="fm-btn" href="{PAGE}/new">New thread</a>' if who else
           f'<a class="fm-btn" href="{_signin_url(PAGE + "/new")}">Sign in to post</a>')
    # TODO(owner): the forum's heading line
    body = ('<section class="fm-head"><div><h1>Forum</h1><p>Share your realms, mods and builds, ask for help, and keep the '
            f'good answers in one place.</p></div><div class="fm-acts">{_search_form()}{new}</div></section>'
            + _discord_card()
            + f'<section class="fm-box" aria-labelledby="fm-cats"><h2 id="fm-cats">Categories</h2><ul class="fm-list">{"".join(rows)}</ul></section>'
            + f'<section class="fm-box" aria-labelledby="fm-new"><h2 id="fm-new">Latest threads</h2>{_thread_rows(store.latest(10), True)}</section>'
            + '<p class="fm-fine">Plain text and links only: nothing is uploaded here, so share screenshots as links. '
              'Be kind; report anything that breaks the rules and the moderators will look.</p>')
    _shell(h, "Forum · Leyline", body, PAGE, who)


def page_cat(h, who, cat: str, query: dict) -> None:
    e = html.escape
    c = CAT[cat]
    page = _int((query.get("page") or ["1"])[0], 1, 1000)
    ts, more = store.threads(cat, page)
    can = who and (not c[3] or who["staff"])
    new = (f'<a class="fm-btn" href="{PAGE}/new?c={cat}">New thread</a>' if can else
           ("" if who else f'<a class="fm-btn" href="{_signin_url(PAGE + "/new?c=" + cat)}">Sign in to post</a>'))
    nav = ""
    if page > 1 or more:
        nav = ('<nav class="fm-pages" aria-label="Pages">' + (f'<a href="{PAGE}/c/{cat}?page={page - 1}">Newer</a>' if page > 1 else "")
               + f"<span>Page {page}</span>" + (f'<a href="{PAGE}/c/{cat}?page={page + 1}">Older</a>' if more else "") + "</nav>")
    body = (f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a></p><h1>{e(c[1])}</h1><p>{e(c[2])}</p></div>'
            f'<div class="fm-acts">{new}</div></section>'
            f'<section class="fm-box" aria-label="Threads">{_thread_rows(ts)}</section>{nav}')
    _shell(h, f"{c[1]} · Forum · Leyline", body, f"{PAGE}/c/{cat}", who)


def _reply_form(who, th: dict, note: str = "", text: str = "") -> str:
    e = html.escape
    if th["locked"] and not (who and who["staff"]):
        return '<p class="fm-fine">This thread is locked, so no new replies.</p>'
    if not who:
        return (f'<p class="fm-acts"><a class="fm-btn" href="{_signin_url(PAGE + "/t/" + str(th["id"]) + "/reply")}">Sign in to reply</a>'
                '<span class="fm-fine">Use your Hero Key or Google sign-in on this website.</span></p>')
    err = f'<p class="fm-msg err" role="alert">{e(note)}</p>' if note else ""
    return (f'<section class="fm-box" aria-labelledby="fm-rp"><h2 id="fm-rp">Reply</h2>'
            f'<form class="fm-form" method="post" action="{PAGE}/t/{th["id"]}/reply">{err}'
            f'<input type="hidden" name="t" value="{form_token(who, "reply:" + str(th["id"]))}">'
            f'<label for="fm-b">Your reply, as {e(who["name"])}</label>'
            f'<textarea id="fm-b" name="body" maxlength="{BODY_MAX}" required>{e(text)}</textarea>'
            '<p class="fm-fine">Plain text. Links work; images show as links.</p>'
            '<div class="fm-acts"><button class="fm-btn" type="submit">Post reply</button></div></form></section>')


def page_thread(h, who, tid: str, query: dict, note: str = "", text: str = "", status: int = 200) -> None:
    e = html.escape
    th = store.thread(tid)
    if th and th["merged_into"]:
        to = store.resolve(th["id"])
        if to:
            h.send_response(301)
            h.send_header("Location", f"{PAGE}/t/{to['id']}")
            h.send_header("Content-Length", "0")
            h.end_headers()
            return
    if not th or th["hidden"]:
        return _shell(h, "Not here · Forum · Leyline", f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a></p>'
                      '<h1>That thread isn\'t here</h1><p>It may have been removed.</p></div></section>', PAGE, who, 404)
    page = _int((query.get("page") or ["1"])[0], 1, 1000)
    ps, more, pages = store.posts(th["id"], page)
    out = []
    for p in ps:
        if p["hidden"]:
            out.append(f'<article class="fm-post" id="p{p["id"]}"><p class="fm-gone">This post was removed by a moderator.</p></article>')
            continue
        team = '<span class="fm-team">Team</span>' if p["staff"] else ""
        tag = f'<small>#{e(p["tag"])}</small>' if p["tag"] else ""
        rep = (f'<a href="{PAGE}/report?p={p["id"]}" rel="nofollow">Report</a>' if (who and who["acct"] != p["author"]) else "")
        out.append(f'<article class="fm-post" id="p{p["id"]}"><p class="fm-by">{_avatar(p["author"], p["name"])}'
                   f'<b>{e(p["name"])}</b>{tag}{team}<span>{_ago(p["created"])}</span>{rep}</p>'
                   f'<p class="fm-text">{render(p["body"])}</p></article>')
    nav = ""
    if pages > 1:
        nav = ('<nav class="fm-pages" aria-label="Pages">' + (f'<a href="{PAGE}/t/{th["id"]}?page={page - 1}">Earlier</a>' if page > 1 else "")
               + f"<span>Page {page} of {pages}</span>" + (f'<a href="{PAGE}/t/{th["id"]}?page={page + 1}">Later</a>' if more else "") + "</nav>")
    msg = ""
    if (query.get("reported") or [""])[0] == "1":
        msg = '<p class="fm-msg" role="status">Thanks. The moderators will look at it.</p>'
    c = CAT.get(th["cat"], ("", "Forum", "", False))
    tags = ("<span class=\"fm-tag\">Pinned</span>" if th["pinned"] else "") + ("<span class=\"fm-tag lock\">Locked</span>" if th["locked"] else "")
    body = (f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a> / <a href="{PAGE}/c/{e(th["cat"])}">{e(c[1])}</a></p>'
            f'<h1>{tags}{e(th["title"])}</h1></div></section>{msg}'
            f'<section class="fm-box" aria-label="Posts">{"".join(out)}</section>{nav}'
            + (_reply_form(who, th, note, text) if not more else ""))
    _shell(h, f"{th['title']} · Forum · Leyline", body, f"{PAGE}/t/{th['id']}", who, status)


def page_reply(h, who, tid: str, note: str = "", text: str = "", status: int = 200) -> None:
    e = html.escape
    th = store.resolve(tid)
    if not th or th["hidden"]:
        return page_thread(h, who, tid, {})
    if not who:
        return h.redirect(_signin_url(f"{PAGE}/t/{th['id']}/reply"))
    body = (f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a> / '
            f'<a href="{PAGE}/t/{th["id"]}">{e(th["title"])}</a></p><h1>Reply</h1></div></section>'
            + _reply_form(who, th, note, text))
    _shell(h, f"Reply · {th['title']} · Forum · Leyline", body, f"{PAGE}/t/{th['id']}/reply", who, status)


def page_new(h, who, query: dict, note: str = "", form: dict | None = None, status: int = 200) -> None:
    e = html.escape
    form = form or {}
    cat = form.get("cat") or (query.get("c") or [""])[0]
    if not who:
        return h.redirect(_signin_url(PAGE + "/new" + (f"?c={cat}" if cat in CAT else "")))
    opts = "".join(f'<option value="{cid}"{" selected" if cid == cat else ""}>{e(n)}</option>'
                   for cid, n, _l, staff in CATEGORIES if not staff or who["staff"])
    err = f'<p class="fm-msg err" role="alert">{e(note)}</p>' if note else ""
    body = (f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a></p><h1>New thread</h1>'
            '<p>Search first: the answer may be in a thread already.</p></div></section>'
            f'<section class="fm-box"><form class="fm-form" method="post" action="{PAGE}/new">{err}'
            f'<input type="hidden" name="t" value="{form_token(who, "new")}">'
            f'<label for="fm-c">Category</label><select id="fm-c" name="cat" required>'
            f'<option value="">Pick one</option>{opts}</select>'
            f'<label for="fm-t">Title</label><input id="fm-t" name="title" maxlength="{TITLE_MAX}" required value="{e(form.get("title", ""))}">'
            f'<label for="fm-b">Post, as {e(who["name"])}</label>'
            f'<textarea id="fm-b" name="body" maxlength="{BODY_MAX}" required>{e(form.get("body", ""))}</textarea>'
            '<p class="fm-fine">Plain text. Links work; screenshots go in as links. Sharing a realm? Put its invite link here.</p>'
            '<div class="fm-acts"><button class="fm-btn" type="submit">Post thread</button>'
            f'<a class="fm-btn ghost" href="{PAGE}">Cancel</a></div></form></section>')
    _shell(h, "New thread · Forum · Leyline", body, PAGE + "/new", who, status)


def page_search(h, who, query: dict) -> None:
    q = clean_line((query.get("q") or [""])[0], 60)
    ts = store.search(q) if q else []
    body = (f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a></p><h1>Search</h1></div>'
            f'<div class="fm-acts">{_search_form(q)}</div></section>'
            + (f'<section class="fm-box" aria-label="Results">{_thread_rows(ts, True) if ts else "<p class=fm-empty>No thread titles match.</p>"}</section>'
               if q else '<p class="fm-fine">Type at least two letters of a thread title.</p>'))
    _shell(h, "Search · Forum · Leyline", body, PAGE + "/search", who)


def page_report(h, who, query: dict, note: str = "", status: int = 200) -> None:
    e = html.escape
    pid = (query.get("p") or [""])[0]
    p = store.post(pid)
    if not who:
        return h.redirect(_signin_url(f"{PAGE}/report?p={_int(pid)}"))
    if not p or p["hidden"]:
        return _shell(h, "Report · Forum · Leyline", '<section class="fm-head"><div><h1>That post isn\'t here</h1></div></section>', PAGE, who, 404)
    opts = "".join(f'<label><input type="radio" name="reason" value="{k}" required> {e(v)}</label>' for k, v in REASONS)
    err = f'<p class="fm-msg err" role="alert">{e(note)}</p>' if note else ""
    body = (f'<section class="fm-head"><div><p class="fm-crumb"><a href="{PAGE}">Forum</a> / <a href="{PAGE}/t/{p["thread"]}#p{p["id"]}">Back to the thread</a></p>'
            f'<h1>Report a post</h1><p>By {e(p["name"])}. The moderators see the post and your reason, not your name in public.</p></div></section>'
            f'<section class="fm-box"><form class="fm-form" method="post" action="{PAGE}/report">{err}'
            f'<input type="hidden" name="t" value="{form_token(who, "report:" + str(p["id"]))}"><input type="hidden" name="p" value="{p["id"]}">'
            f'<fieldset style="border:0;margin:0;padding:0;display:grid;gap:6px"><legend style="font-weight:600;margin-bottom:4px">Why?</legend>{opts}</fieldset>'
            f'<label for="fm-n">Anything the moderators should know (optional)</label>'
            f'<input id="fm-n" name="note" maxlength="{NOTE_MAX}">'
            '<div class="fm-acts"><button class="fm-btn" type="submit">Send the report</button></div></form></section>')
    _shell(h, "Report · Forum · Leyline", body, PAGE + "/report", who, status)


def _sanctioned(who: dict, sub: str) -> str:
    """The refusal text when a sanction stops this post (reports stay open to everyone), else ""."""
    try:
        adm = P("admin")
    except Exception:   # noqa: BLE001: a portal without the admin console
        adm = None
    if adm is None or sub.startswith("report") or not hasattr(adm, "blocked"):
        return ""
    return adm.blocked("post", acct=who.get("acct", ""))


def _down(h) -> None:
    _shell(h, "Forum · Leyline", '<section class="fm-head"><div><h1>Forum</h1><p>The website\'s sign-in isn\'t answering right '
           'now. Try again shortly.</p></div></section>', PAGE, None, 503)


def get(h, path: str, query: dict) -> None:
    if store is None:
        return h.send(404, b"not found\n", "text/plain")
    if path == PREVIEW or path.startswith(PREVIEW + "/"):   # the hub preview's address: one forum, one address
        qs = urllib.parse.urlencode(query, doseq=True) if query else ""
        h.send_response(301)
        h.send_header("Location", PAGE + path[len(PREVIEW):] + ("?" + qs if qs else ""))
        h.send_header("Content-Length", "0")
        h.end_headers()
        return
    if _limited(h):
        return h.send(429, b"too many requests\n", "text/plain")
    if path == API or path.startswith(API + "/"):
        return api(h, path[len(API):].strip("/"), query)
    try:
        who = viewer(h)
    except OSError:
        who = None
    if who:
        store.seen(who["acct"], who["name"], who["tag"], who["staff"])
    sub = path[len(PAGE):].strip("/")
    if sub == "":
        return page_index(h, who)
    m = re.fullmatch(r"c/([a-z]{2,12})", sub)
    if m and m.group(1) in CAT:
        return page_cat(h, who, m.group(1), query)
    m = re.fullmatch(r"t/(\d{1,9})", sub)
    if m:
        return page_thread(h, who, m.group(1), query)
    m = re.fullmatch(r"t/(\d{1,9})/reply", sub)
    if m:
        return page_reply(h, who, m.group(1))
    if sub == "new":
        return page_new(h, who, query)
    if sub == "search":
        return page_search(h, who, query)
    if sub == "report":
        return page_report(h, who, query)
    _shell(h, "Not found · Forum · Leyline", f'<section class="fm-head"><div><h1>Not found</h1><p><a href="{PAGE}">The forum</a></p></div></section>',
           PAGE, who, 404)


def _read_form(h) -> dict | None:
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > FORM_MAX:
        return None
    try:
        q = urllib.parse.parse_qs(h.rfile.read(n).decode("utf-8"), keep_blank_values=True, max_num_fields=12)
    except (UnicodeDecodeError, ValueError):
        return None
    return {k: v[0] for k, v in q.items()}


def _see_other(h, url: str) -> None:
    h.send_response(303)
    h.send_header("Location", url)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", "0")
    h.end_headers()


def post(h, path: str) -> None:
    if store is None or path == API or path.startswith(API + "/"):
        _read_form(h)
        return h.send(405, b"method not allowed\n", "text/plain")
    form = _read_form(h)   # read first, so a refusal never resets the connection under the sender
    if not _same_site(h):
        return h.send(403, b"That form came from another site.\n", "text/plain")
    if form is None:
        return h.send(400, b"That form didn't arrive in one piece.\n", "text/plain")
    try:
        who = viewer(h)
    except OSError:
        return _down(h)
    sub = path[len(PAGE):].strip("/")
    if not who:
        return _see_other(h, _signin_url(PAGE))
    blk = _sanctioned(who, sub)
    if blk:   # a site-wide sanction (Leyline HQ, stream/admin.py blocked()): no new posts while it lasts
        return _shell(h, "Forum · Leyline", f'<section class="fm-head"><div><h1>Forum</h1><p>{html.escape(blk)}</p></div></section>',
                      PAGE, who, 403)
    store.seen(who["acct"], who["name"], who["tag"], who["staff"])
    tok = form.get("t", "")
    try:
        if sub == "new":
            if not hmac.compare_digest(tok, form_token(who, "new")):
                return page_new(h, who, {}, "That form timed out. Post it again.", form, 403)
            try:
                tid = store.new_thread(who["acct"], form.get("cat"), form.get("title"), form.get("body"), who["staff"])
            except ForumError as ex:
                return page_new(h, who, {}, ex.text, form, ex.status)
            return _see_other(h, f"{PAGE}/t/{tid}")
        m = re.fullmatch(r"t/(\d{1,9})/reply", sub)
        if m:
            tid = m.group(1)
            if not hmac.compare_digest(tok, form_token(who, "reply:" + str(int(tid)))):
                return page_reply(h, who, tid, "That form timed out. Post it again.", form.get("body", ""), 403)
            try:
                pid = store.reply(who["acct"], tid, form.get("body"), who["staff"])
            except ForumError as ex:
                return page_reply(h, who, tid, ex.text, form.get("body", ""), ex.status)
            th = store.post(pid)["thread"]
            pg = store.page_of(pid)
            return _see_other(h, f"{PAGE}/t/{th}" + (f"?page={pg}" if pg > 1 else "") + f"#p{pid}")
        if sub == "report":
            pid = str(_int(form.get("p"), 0))
            if not hmac.compare_digest(tok, form_token(who, "report:" + pid)):
                return page_report(h, who, {"p": [pid]}, "That form timed out. Send it again.", 403)
            try:
                store.report(who["acct"], pid, form.get("reason"), form.get("note"))
            except ForumError as ex:
                return page_report(h, who, {"p": [pid]}, ex.text, ex.status)
            p = store.post(pid)
            return _see_other(h, f"{PAGE}/t/{p['thread']}?reported=1#p{p['id']}")
    except ForumError as ex:   # noqa: PERF203
        return h.send(ex.status, (ex.text + "\n").encode(), "text/plain")
    h.send(405, b"method not allowed\n", "text/plain")
