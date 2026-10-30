"""Leyline hub rankings: install counts, ratings and the sorted mods list (Hot, Rising, Top rated, Most installed,
New, Recently updated). Served by stream/wrath_portal.py, which loads this file from beside itself and runs without
it. The formulas, with the reasons for each constant, are in docs/HUB-RANKINGS.md; the functions below are the one
copy (compute()).

    GET  /wrath/leyline/mods.json   the ranked list, public (CORS *):
                                    ?sort=hot|rising|top|installs|installs30|new|updated  (default hot)
                                    &client=<build>  (1.12, 1.12.1, 5875, 2.4.3, 3.3.5a, 12340, ...: fits that client)
                                    &kind=addon|mod|mode|theme  &q=<text>  &limit=1..1000 (50)  &offset=N
    POST /wrath/api/hub/install     {id, iid, build?, via?}: one anonymous install, from the launcher (or the site).
                                    iid is a random id the launcher makes per install (22-64 of [A-Za-z0-9_-]); a
                                    retry with the same iid on the same day counts once. Content-Type must be JSON.
    GET  /wrath/api/hub/me?id=<id>  {signed_in, csrf?, mine}: the viewer's own rating (website sign-in cookie, or the
                                    launcher's friends token as "Authorization: Bearer ...")
    POST /wrath/api/hub/rate        {id, stars: 1..5, or 0 to take it back}: cookie + X-Leyline-CSRF, or Bearer.
                                    The hub's item page posts the same as a plain form (id, stars, t) and is sent back.

Privacy: nothing personal is kept in clear.
  * installs: the mod, the UTC day, the build, and hmac(server key, iid) for that day's dedupe (those rows are
    dropped after 3 days); then only per-mod per-day counts. No IP is stored: for rate limits the IP is hashed with
    a salt that lives in memory only and changes every UTC day.
  * ratings: hmac(server key, account) (the game account the website sign-in hands out), the stars and when.
    One per account per mod; a new rating replaces the old one.
Storage: SQLite in $WU_PORTAL_DATA (default /data), hub_rank.sqlite3. Standard library only.
Settings: WU_HUB_RANK=0 (off), WU_HUB_RANK_TTL (seconds the computed rankings are reused, default 300).
"""
from __future__ import annotations

import calendar
import collections
import hashlib
import hmac
import html
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import urllib.parse

try:
    import sqlite3
except ImportError:   # the portal runs without rankings
    sqlite3 = None

log = logging.getLogger("wrath-portal.hub-rank")

FEED = "/wrath/leyline/mods.json"
API = "/wrath/api/hub"
SORTS = ("hot", "rising", "top", "installs", "installs30", "new", "updated")
KINDS = ("addon", "mod", "mode", "theme")
BODY_MAX = 2048
IID_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
ID_RE = re.compile(r"^(mod|link|theme):[a-z0-9][a-z0-9-]{1,40}$")
DAY = 86400

# ---- the formulas' constants (docs/HUB-RANKINGS.md explains each)
HOT_HALF_LIFE = 3.0          # days: an install counts half as much for Hot every 3 days
HOT_RATING_HALF_LIFE = 7.0   # days, for a rating's push on Hot
HOT_RATING_WEIGHT = 2.0      # a 5-star rating today = 4 installs today (2 x (5-3)); a 1-star one = -4
HOT_WINDOW = 30              # days of history Hot looks at
FRESH_BOOST = 0.5            # Hot: + 0.5 x 2^(-days since the last update / 7)
FRESH_HALF_LIFE = 7.0
STAR_WEIGHT = 0.1            # Hot: + 0.1 x log10(1 + forge stars): a tie-breaker, never a ranking on its own
RISING_MIN = 5               # installs in the last 7 days before something can be Rising
RISING_K = 5                 # smoothing: log2((last7 + 5) / (prev7 + 5))
BAYES_C = 5                  # Top rated: the prior counts as 5 ratings
BAYES_PRIOR = 3.5            # ... of the site-wide mean, which itself starts at 3.5 (blended in over 10 ratings)
BAYES_PRIOR_N = 10
DAMP_FLOOR = 25              # outlier damping: a day's installs above max(25, 4 x the mod's 28-day median) count
DAMP_MULT = 4                # as the cap plus the square root of the rest
DAMP_DAYS = 28

# ---- rate limits (per hour unless said)
INSTALL_PER_IP_HOUR = 30     # pings from one (hashed) address
INSTALL_PER_IP_MOD_DAY = 2   # counted installs of one mod from one address a day (more are answered, not counted)
INSTALL_PER_DAY = 50000      # everything, a day
RATE_PER_ACCT_HOUR = 30
RATE_PER_IP_HOUR = 60
SEEN_KEEP_DAYS = 3


def _today(now: float) -> int:
    return int(now // DAY)


def _day_str(day: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(day * DAY))


def _date_day(v) -> int | None:
    """'2026-10-29' (or a longer ISO stamp) -> days since 1970, or None."""
    if not isinstance(v, str) or not re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        return calendar.timegm(time.strptime(v[:10], "%Y-%m-%d")) // DAY
    except (ValueError, OverflowError):
        return None


# ------------------------------------------------------------------------------------------- builds and kinds
BUILD_ALIASES = {"1.12": "1.12", "1.12.1": "1.12", "5875": "1.12", "2.4.3": "2.4.3", "8606": "2.4.3",
                 "3.3.5a": "3.3.5a", "3.3.5": "3.3.5a", "12340": "3.3.5a", "4.3.4": "4.3.4", "15595": "4.3.4",
                 "5.4.8": "5.4.8", "18414": "5.4.8"}


def client_tag(v) -> str:
    """A client build as the catalog tags it, or "" (unknown or none)."""
    return BUILD_ALIASES.get(str(v or "").strip().lower(), "")


def kind_of(i: dict) -> str:
    """addon (a UI addon for the client), mode (a game mode / sandbox), theme (a launcher theme) or mod (the rest:
    realm modules and scripts, tools, presets, cores)."""
    if i.get("source") == "theme":
        return "theme"
    if i.get("category") == "sandbox" or i.get("type") == "mode":
        return "mode"
    if i.get("type") == "addon" or i.get("category") == "addons":
        return "addon"
    return "mod"


def fits(i: dict, build: str) -> bool:
    b = i.get("builds") or ["any"]
    return not build or "any" in b or build in b


def installable(i: dict) -> bool:
    """What the launcher installs in one click: a Workshop package (zip on our site with a sha256) or a theme pack
    with a download. Community links are View source."""
    if i.get("source") == "workshop":
        return bool(i.get("packaged") and i.get("download") and i.get("sha256"))
    if i.get("source") == "theme":
        return bool(i.get("download") and i.get("sha256"))
    return False


# ------------------------------------------------------------------------------------------- the formulas
def damp_series(days: dict[int, int]) -> dict[int, float]:
    """Outlier damping per mod: a day's count n is kept up to cap = max(DAMP_FLOOR, DAMP_MULT x the median of the
    28 days before it, zeros included); above the cap only sqrt(n - cap) more counts. A real hit keeps climbing
    (its median rises with it); a one-day flood of fake pings mostly doesn't count."""
    out = {}
    for d, n in days.items():
        window = sorted(days.get(d - k, 0) for k in range(1, DAMP_DAYS + 1))
        med = (window[DAMP_DAYS // 2 - 1] + window[DAMP_DAYS // 2]) / 2
        cap = max(DAMP_FLOOR, DAMP_MULT * med)
        out[d] = float(n) if n <= cap else cap + math.sqrt(n - cap)
    return out


def bayes(total: float, n: int, prior: float) -> float:
    return (BAYES_C * prior + total) / (BAYES_C + n)


def compute(items: list[dict], installs: list[tuple], ratings: list[tuple], first_seen: dict[str, int],
            today: int) -> dict[str, dict]:
    """The metrics and scores of every item.
    installs: (mod, day, n) rows; ratings: (mod, stars, at_unix) rows (one per account already); first_seen: mod ->
    day. Returns {id: {installs: {all, d30, d7, prev7}, rating: {avg, n, score}, hot, rising, top, new, updated}}."""
    per: dict[str, dict[int, int]] = collections.defaultdict(dict)
    for mod, day, n in installs:
        per[mod][int(day)] = per[mod].get(int(day), 0) + int(n)
    rat: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)
    all_s = 0
    for mod, stars, at in ratings:
        rat[mod].append((int(stars), float(at)))
        all_s += int(stars)
    prior = (all_s + BAYES_PRIOR * BAYES_PRIOR_N) / (len(ratings) + BAYES_PRIOR_N)
    out = {}
    for i in items:
        mid = i["id"]
        damped = damp_series(per.get(mid, {}))
        tot = d30 = d7 = p7 = heat = 0.0
        for d, v in damped.items():
            age = today - d
            if age < 0:
                continue
            tot += v
            if age < 30:
                d30 += v
            if age < 7:
                d7 += v
            elif age < 14:
                p7 += v
            if age < HOT_WINDOW:
                heat += v * 2 ** (-age / HOT_HALF_LIFE)
        rs = rat.get(mid, [])
        for s, at in rs:
            age = max(0.0, today - at / DAY)
            if age < HOT_WINDOW:
                heat += HOT_RATING_WEIGHT * (s - 3) * 2 ** (-age / HOT_RATING_HALF_LIFE)
        upd = max([d for d in (_date_day(i.get("updated")), _date_day((i.get("release") or {}).get("date"))) if d is not None],
                  default=None)
        fresh = FRESH_BOOST * 2 ** (-max(0, today - upd) / FRESH_HALF_LIFE) if upd is not None else 0.0
        stars = i.get("stars") if isinstance(i.get("stars"), int) and not isinstance(i.get("stars"), bool) else 0
        hot = math.copysign(math.log10(1 + abs(heat)), heat) + fresh + STAR_WEIGHT * math.log10(1 + max(0, stars))
        rising = math.log2((d7 + RISING_K) / (p7 + RISING_K)) if d7 >= RISING_MIN and d7 > p7 else None
        n = len(rs)
        total = sum(s for s, _ in rs)
        added = first_seen.get(mid)
        sub = _date_day(i.get("added"))
        out[mid] = {
            "installs": {"all": round(tot), "d30": round(d30), "d7": round(d7), "prev7": round(p7)},
            "rating": {"avg": round(total / n, 2) if n else None, "n": n, "score": round(bayes(total, n, prior), 3) if n else None},
            "hot": round(hot, 4), "rising": round(rising, 4) if rising is not None else None,
            "new": _day_str(min(d for d in (added, sub) if d is not None)) if (added is not None or sub is not None) else "",
            "updated": _day_str(upd) if upd is not None else "",
        }
    return out


def sort_key(sort: str, m: dict, i: dict):
    """Python sort key (ascending) for a sort; the name breaks ties."""
    name = (i.get("name") or "").lower()
    if sort == "rising":
        return (m["rising"] is None, -(m["rising"] or 0), -m["installs"]["d7"], name)
    if sort == "top":
        return (m["rating"]["score"] is None, -(m["rating"]["score"] or 0), -m["rating"]["n"], name)
    if sort == "installs":
        return (-m["installs"]["all"], -m["hot"], name)
    if sort == "installs30":
        return (-m["installs"]["d30"], -m["hot"], name)
    new, upd = _date_day(m["new"]), _date_day(m["updated"])
    if sort == "new":
        return (new is None, -(new or 0), -(upd or 0), name)
    if sort == "updated":
        return (upd is None, -(upd or 0), name)
    return (-m["hot"], -float(i.get("score") or 0), name)


# ------------------------------------------------------------------------------------------- the store
SCHEMA = """
CREATE TABLE IF NOT EXISTS hub_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hub_install_seen (mod TEXT NOT NULL, day INTEGER NOT NULL, iid TEXT NOT NULL,
  PRIMARY KEY (mod, day, iid));
CREATE TABLE IF NOT EXISTS hub_installs (mod TEXT NOT NULL, day INTEGER NOT NULL, build TEXT NOT NULL DEFAULT '',
  n INTEGER NOT NULL, PRIMARY KEY (mod, day, build));
CREATE TABLE IF NOT EXISTS hub_ratings (mod TEXT NOT NULL, who TEXT NOT NULL, stars INTEGER NOT NULL, at INTEGER NOT NULL,
  PRIMARY KEY (mod, who));
CREATE INDEX IF NOT EXISTS hub_ratings_who ON hub_ratings (who, at);
CREATE TABLE IF NOT EXISTS hub_first_seen (mod TEXT PRIMARY KEY, day INTEGER NOT NULL);
"""


class Window:
    """A sliding-window counter: hit(key, limit) is False once key had limit hits in the window."""

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
            if len(self.q) > 50000:
                self.q = {k: v for k, v in self.q.items() if v}
            return True


class RankError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status, self.text = status, text


class Ranks:
    """The store, the rate limits and the cached rankings. Thread-safe (one connection, one lock)."""

    def __init__(self, data_dir: str | None = None, clock=time.time, mono=None, db_file: str | None = None):
        if sqlite3 is None:
            raise RuntimeError("no sqlite3")
        self.clock = clock
        mono = mono or (lambda: self.clock())
        path = db_file or os.path.join(data_dir or os.environ.get("WU_PORTAL_DATA", "/data"), "hub_rank.sqlite3")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()
        row = self.db.execute("SELECT v FROM hub_meta WHERE k='key'").fetchone()
        if row is None:
            self.db.execute("INSERT INTO hub_meta (k, v) VALUES ('key', ?)", (secrets.token_hex(32),))
            row = self.db.execute("SELECT v FROM hub_meta WHERE k='key'").fetchone()
        self.key = bytes.fromhex(row[0])
        self._salt_day, self._salt = -1, b""
        self.lim_ip = Window(3600, mono)
        self.lim_ip_mod = Window(DAY, mono)
        self.lim_day = Window(DAY, mono)
        self.lim_acct = Window(3600, mono)
        self.ttl = float(os.environ.get("WU_HUB_RANK_TTL", "300") or 300)
        self._cache: tuple[float, int, dict] | None = None
        self._swept = -1

    # ---------------------------------------------------------------- hashing
    def _h(self, kind: str, v: str, n: int = 32) -> str:
        return hmac.new(self.key, f"{kind}|{v}".encode(), hashlib.sha256).hexdigest()[:n]

    def ip_hash(self, ip: str) -> str:
        """The address, hashed with today's salt (memory only; a new one every UTC day). For rate limits only."""
        day = _today(self.clock())
        if day != self._salt_day:
            self._salt_day, self._salt = day, secrets.token_bytes(32)
        return hmac.new(self._salt, (ip or "?").encode(), hashlib.sha256).hexdigest()[:20]

    def who(self, acct: str) -> str:
        return self._h("acct", acct.upper())

    def csrf(self, session: str) -> str:
        return self._h("hubrate", session)

    def form_token(self, session: str, mid: str) -> str:
        return self._h("hubform", session + "|" + mid)

    # ---------------------------------------------------------------- writes
    def install(self, mid: str, iid: str, build: str, ip: str) -> bool:
        """Count one install (True) or not (False: a repeat, or over a cap). Raises RankError for a bad ping."""
        if not isinstance(iid, str) or not IID_RE.fullmatch(iid):
            raise RankError(400, "Bad install id.")
        iph = self.ip_hash(ip)
        if not self.lim_ip.hit("i|" + iph, INSTALL_PER_IP_HOUR):
            raise RankError(429, "Slow down a little.")
        now = self.clock()
        day = _today(now)
        with self.lock:
            self._sweep(day)
            cur = self.db.execute("INSERT OR IGNORE INTO hub_install_seen (mod, day, iid) VALUES (?, ?, ?)",
                                  (mid, day, self._h("iid", iid, 24)))
            if cur.rowcount == 0:
                return False                                   # the same install, again (a retry)
            if not self.lim_ip_mod.hit(f"{iph}|{mid}|{day}", INSTALL_PER_IP_MOD_DAY):
                return False
            if not self.lim_day.hit("all", INSTALL_PER_DAY):
                return False
            self.db.execute("INSERT INTO hub_installs (mod, day, build, n) VALUES (?, ?, ?, 1) "
                            "ON CONFLICT (mod, day, build) DO UPDATE SET n = n + 1", (mid, day, build or ""))
        return True

    def _sweep(self, day: int) -> None:
        if day != self._swept:
            self.db.execute("DELETE FROM hub_install_seen WHERE day < ?", (day - SEEN_KEEP_DAYS + 1,))
            self._swept = day

    def rate(self, mid: str, acct: str, stars, ip: str) -> int:
        """Set (1-5) or take back (0) this account's rating of mid. Returns what is kept now (0 = none)."""
        if isinstance(stars, bool) or not isinstance(stars, int):
            try:
                stars = int(str(stars))
            except ValueError:
                raise RankError(400, "Pick 1 to 5 stars.") from None
        if not 0 <= stars <= 5:
            raise RankError(400, "Pick 1 to 5 stars.")
        w = self.who(acct)
        if not self.lim_acct.hit("r|" + w, RATE_PER_ACCT_HOUR) or not self.lim_ip.hit("r|" + self.ip_hash(ip), RATE_PER_IP_HOUR):
            raise RankError(429, "Too many ratings for now. Try again later.")
        with self.lock:
            if stars == 0:
                self.db.execute("DELETE FROM hub_ratings WHERE mod = ? AND who = ?", (mid, w))
            else:
                self.db.execute("INSERT INTO hub_ratings (mod, who, stars, at) VALUES (?, ?, ?, ?) "
                                "ON CONFLICT (mod, who) DO UPDATE SET stars = excluded.stars, at = excluded.at",
                                (mid, w, stars, int(self.clock())))
        self._cache = None
        return stars

    def mine(self, mid: str, acct: str) -> int:
        with self.lock:
            r = self.db.execute("SELECT stars FROM hub_ratings WHERE mod = ? AND who = ?", (mid, self.who(acct))).fetchone()
        return int(r[0]) if r else 0

    def note_seen(self, ids: list[str], day: int) -> None:
        with self.lock:
            self.db.executemany("INSERT OR IGNORE INTO hub_first_seen (mod, day) VALUES (?, ?)", [(i, day) for i in ids])

    # ---------------------------------------------------------------- the rankings
    def metrics(self, items: list[dict], force: bool = False) -> dict[str, dict]:
        now = self.clock()
        ids = sorted(i["id"] for i in items)
        sig = hash(tuple(ids))
        c = self._cache
        if not force and c and now - c[0] < self.ttl and c[1] == sig:
            return c[2]
        day = _today(now)
        self.note_seen(ids, day)
        with self.lock:
            inst = self.db.execute("SELECT mod, day, SUM(n) FROM hub_installs GROUP BY mod, day").fetchall()
            rats = self.db.execute("SELECT mod, stars, at FROM hub_ratings").fetchall()
            first = dict(self.db.execute("SELECT mod, day FROM hub_first_seen").fetchall())
        m = compute(items, inst, rats, first, day)
        self._cache = (now, sig, m)
        return m

    def ranked(self, items: list[dict], sort: str = "hot", build: str = "", kind: str = "", q: str = "") -> list[tuple[dict, dict]]:
        sort = sort if sort in SORTS else "hot"
        m = self.metrics(items)
        words = [w for w in (q or "").lower().split() if w][:6]
        out = []
        for i in items:
            if not fits(i, build) or (kind and kind_of(i) != kind):
                continue
            if words and not all(w in " ".join(str(i.get(k) or "") for k in ("name", "summary", "description", "author")).lower()
                                 for w in words):
                continue
            out.append((i, m[i["id"]]))
        out.sort(key=lambda p: sort_key(sort, p[1], p[0]))
        return out


# ------------------------------------------------------------------------------------------- the portal's hooks
_get = lambda name: None   # noqa: E731
store: Ranks | None = None


def bind(getter) -> None:
    global _get

    def get(name):
        try:
            return getter(name)
        except Exception:   # noqa: BLE001
            return None
    _get = get


def setup() -> Ranks | None:
    global store
    if store is not None:
        return store
    if os.environ.get("WU_HUB_RANK", "1") == "0":
        return None
    try:
        store = Ranks()
    except Exception:   # noqa: BLE001: the portal runs without rankings
        log.exception("hub rankings: off (the store didn't open)")
        return None
    return store


def _hub():
    hm = _get("hub_mod")
    return getattr(hm, "hub", None) if hm is not None else None


def items() -> list[dict]:
    h = _hub()
    if h is None:
        return []
    try:
        return h.items()
    except Exception:   # noqa: BLE001
        return []


def match(path: str) -> bool:
    if os.environ.get("WU_HUB_RANK", "1") == "0":
        return False
    return path == FEED or path == API or path.startswith(API + "/")


def _json(h, status: int, doc: dict, cors: bool = False) -> None:
    headers = {"Cache-Control": "no-store"}
    if cors:
        headers = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60"}
    h.send(status, json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
           "application/json; charset=utf-8", headers=headers)


def item_view(i: dict, m: dict, host: str) -> dict:
    """One item of mods.json."""
    hub_page = f"https://{host}/wrath/leyline-preview/p/{i['id'].replace(':', '-', 1)}"
    v = {"id": i["id"], "name": i.get("name", ""), "author": i.get("author", ""), "summary": i.get("summary", ""),
         "kind": kind_of(i), "category": i.get("category", ""), "builds": i.get("builds") or ["any"],
         "source": i.get("source", ""), "installable": installable(i), "page": hub_page, "repo": i.get("repo", ""),
         "licence": i.get("licence", ""), "stars": i.get("stars"), "version": (i.get("ws") or {}).get("version") or None,
         "release": i.get("release") or None, **m}
    if v["installable"]:
        v["install"] = "leyline://install/" + i["id"]
    return v


def feed_doc(query: dict, host: str) -> dict:
    one = lambda k: (query.get(k) or [""])[0][:80]   # noqa: E731
    sort = one("sort") or "hot"
    if sort == "installs" and one("window") == "30":
        sort = "installs30"
    sort = sort if sort in SORTS else "hot"
    raw_client = one("client")
    build = client_tag(raw_client)
    kind = one("kind") if one("kind") in KINDS else ""
    q = re.sub(r"[^\w .'-]", " ", one("q"))[:60]
    try:
        limit = max(1, min(1000, int(one("limit") or 50)))
    except ValueError:
        limit = 50
    try:
        offset = max(0, min(5000, int(one("offset") or 0)))
    except ValueError:
        offset = 0
    its = items()
    ranked = store.ranked(its, sort, build, kind, q) if store is not None else []
    page = ranked[offset: offset + limit]
    return {"format": 1, "sort": sort, "client": build or None, "kind": kind or None, "total": len(ranked),
            "offset": offset, "limit": limit, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(store.clock() if store else time.time())),
            "formulas": "https://github.com/orionopenwow/WrathUnleashed/blob/main/docs/HUB-RANKINGS.md",
            "items": [dict(item_view(i, m, host), rank=offset + n + 1) for n, (i, m) in enumerate(page)]}


def _session(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "wr_session":
            return v
    return ""


def viewer(h) -> tuple[str, str, str] | None:
    """(acct, how, session-or-token) for whoever is asking, None when signed out. Raises OSError when the site's
    sign-in isn't answering, RankError when sign-in isn't available here (no social module)."""
    soc = _get("social")
    if soc is None or getattr(soc, "store", None) is None:
        raise RankError(503, "Sign-in isn't available here right now.")
    authz = h.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        tok = authz[7:].strip()
        acct = soc.store.token_acct(tok)
        return (acct, "token", tok) if acct else None
    who = soc.cookie_user(h)
    if who is None:
        return None
    return who[0], "cookie", _session(h.headers.get("Cookie", ""))


def _cross_site(h) -> bool:
    if h.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return True
    origin = h.headers.get("Origin", "")
    return bool(origin) and origin != f"https://{_get('PUBLIC_HOST') or 'play.openvanilla.app'}"


def _known(mid) -> dict | None:
    if not isinstance(mid, str) or not ID_RE.fullmatch(mid):
        return None
    return next((i for i in items() if i["id"] == mid), None)


def _rating_doc(mid: str) -> dict:
    its = items()
    m = store.metrics(its, force=True).get(mid) if store is not None else None
    return m["rating"] if m else {"avg": None, "n": 0, "score": None}


def get(h, path: str, query: dict) -> None:
    limit = _get("browse_limit")
    if limit is not None and not limit.hit(h.ip(), 600):
        return _json(h, 429, {"error": "Too many requests."})
    if store is None:
        return _json(h, 404, {"error": "Rankings are off here."})
    if path == FEED:
        return _json(h, 200, feed_doc(query, _get("PUBLIC_HOST") or "play.openvanilla.app"), cors=True)
    sub = path[len(API):].strip("/")
    if sub == "me":
        mid = (query.get("id") or [""])[0]
        if not _known(mid):
            return _json(h, 404, {"error": "Not in the catalog."})
        try:
            v = viewer(h)
        except RankError as e:
            return _json(h, e.status, {"error": e.text})
        except OSError:
            return _json(h, 503, {"error": "The website isn't answering right now."})
        if v is None:
            return _json(h, 200, {"signed_in": False, "mine": 0, "rating": _rating_doc(mid)})
        doc = {"signed_in": True, "mine": store.mine(mid, v[0]), "rating": _rating_doc(mid)}
        if v[1] == "cookie":
            doc["csrf"] = store.csrf(v[2])
        return _json(h, 200, doc)
    _json(h, 404, {"error": "Unknown call."})


def _body(h):
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > BODY_MAX:
        return None
    return h.rfile.read(n) if n else b""


def post(h, path: str) -> None:
    if store is None:
        return _json(h, 404, {"error": "Rankings are off here."})
    sub = path[len(API):].strip("/") if path.startswith(API) else ""
    raw = _body(h)
    if raw is None:
        return _json(h, 413, {"error": "Too large."})
    ctype = h.headers.get("Content-Type", "").split(";")[0].strip().lower()
    form = ctype == "application/x-www-form-urlencoded"
    if form:
        doc = dict(urllib.parse.parse_qsl(raw.decode("utf-8", "replace"), max_num_fields=8))
    elif ctype == "application/json":
        try:
            doc = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            doc = None
        if not isinstance(doc, dict):
            return _json(h, 400, {"error": "Bad request."})
    else:
        return _json(h, 415, {"error": "Send JSON."})
    if sub == "install":
        if form:
            return _json(h, 415, {"error": "Send JSON."})
        i = _known(doc.get("id"))
        if i is None:
            return _json(h, 404, {"error": "Not in the catalog."})
        try:
            counted = store.install(i["id"], doc.get("iid"), client_tag(doc.get("build")), h.ip())
        except RankError as e:
            return _json(h, e.status, {"error": e.text})
        return _json(h, 200, {"ok": True, "counted": counted})
    if sub == "rate":
        return _rate(h, doc, form)
    _json(h, 404, {"error": "Unknown call."})


def _rate(h, doc: dict, form: bool) -> None:
    i = _known(doc.get("id"))
    back = f"/wrath/leyline-preview/p/{i['id'].replace(':', '-', 1)}" if i else "/wrath/leyline-preview/catalog"

    def fail(status, text):
        if form:
            return _redirect(h, back + "?rated=" + urllib.parse.quote(text))
        return _json(h, status, {"error": text})
    if i is None:
        return fail(404, "Not in the catalog.")
    try:
        v = viewer(h)
    except RankError as e:
        return fail(e.status, e.text)
    except OSError:
        return fail(503, "The website isn't answering right now.")
    if v is None:
        if form:
            return _redirect(h, "/login?next=" + urllib.parse.quote(back, safe=""))
        return _json(h, 401, {"error": "Sign in first."})
    acct, how, sess = v
    if how == "cookie":
        if _cross_site(h):
            return fail(403, "That came from another site.")
        want = store.form_token(sess, i["id"]) if form else store.csrf(sess)
        got = doc.get("t", "") if form else h.headers.get("X-Leyline-CSRF", "")
        if not isinstance(got, str) or not hmac.compare_digest(got, want):
            return fail(403, "Reload the page and try again.")
    try:
        kept = store.rate(i["id"], acct, doc.get("stars"), h.ip())
    except RankError as e:
        return fail(e.status, e.text)
    if form:
        return _redirect(h, back + "?rated=" + ("Thanks." if kept else "Rating removed."))
    _json(h, 200, {"ok": True, "mine": kept, "rating": _rating_doc(i["id"])})


def _redirect(h, url: str) -> None:
    h.send_response(303)
    h.send_header("Location", url)
    h.send_header("Content-Length", "0")
    h.send_header("Cache-Control", "no-store")
    h.end_headers()


# ------------------------------------------------------------------------------------------- the hub pages' pieces
SORT_LABELS = [("hot", "Hot"), ("rising", "Rising"), ("top", "Top rated"), ("installs", "Most installed"),
               ("installs30", "Most installed (30 days)"), ("new", "New"), ("updated", "Recently updated")]
KIND_LABELS = [("addon", "Addons"), ("mod", "Realm mods and tools"), ("mode", "Game modes"), ("theme", "Themes")]


def stars_text(r: dict) -> str:
    if not r or not r.get("n"):
        return "No ratings yet"
    return f"{r['avg']:.1f} of 5 · {r['n']} rating" + ("s" if r["n"] != 1 else "")


def item_panel(h, i: dict, query: dict | None = None) -> str:
    """The item page's rankings block: installs, rating, an Install button (leyline://) and the rating form."""
    if store is None:
        return ""
    e = html.escape
    m = store.metrics(items()).get(i["id"])
    if m is None:
        return ""
    parts = [f'<p class="hb-stats"><span>{e(stars_text(m["rating"]))}</span>'
             f'<span>{m["installs"]["all"]} installs · {m["installs"]["d30"]} this month</span></p>']
    if installable(i):
        parts.append(f'<p class="hb-actions"><a class="ly-btn" href="leyline://install/{e(i["id"])}">Install with Leyline</a></p>'
                     '<p class="hb-fine">Opens the Leyline launcher, which installs it into your game client in one click. '
                     'No launcher yet? <a href="/wrath/leyline">Get it here</a>.</p>')
    note = ((query or {}).get("rated") or [""])[0][:80]
    if note:
        parts.append(f'<p class="hb-fine" role="status">{e(note)}</p>')
    try:
        v = viewer(h)
    except (RankError, OSError):
        v = None
    if v is None or v[1] != "cookie":
        parts.append(f'<p class="hb-fine"><a href="/login?next={e(urllib.parse.quote("/wrath/leyline-preview/p/" + i["id"].replace(":", "-", 1), safe=""))}">'
                     'Sign in</a> to rate it.</p>')
    else:
        mine = store.mine(i["id"], v[0])
        btns = "".join(f'<button class="hb-star{" on" if mine == s else ""}" name="stars" value="{s}" '
                       f'aria-label="{s} star{"s" if s > 1 else ""}">{"★" * s}</button>' for s in range(1, 6))
        undo = '<button class="hb-star" name="stars" value="0">Take my rating back</button>' if mine else ""
        parts.append(f'<form class="hb-rate" method="post" action="{API}/rate"><input type="hidden" name="id" value="{e(i["id"])}">'
                     f'<input type="hidden" name="t" value="{store.form_token(v[2], i["id"])}">'
                     f'<span>{"Your rating" if mine else "Rate it"}:</span>{btns}{undo}</form>')
    return '<section class="ly-panel hb-rank">' + "".join(parts) + "</section>"


RANK_CSS = """
.hb-stats{display:flex;flex-wrap:wrap;gap:6px 18px;justify-content:center;color:var(--ly-dim,#a9b0d6)}
.hb-rate{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:center}
.hb-star{min-height:36px;padding:0 10px;border-radius:4px;border:1px solid var(--ly-line,rgba(120,150,255,.28));background:transparent;
color:var(--ly-ink,#e8ecff);cursor:pointer}.hb-star.on,.hb-star:hover{border-color:var(--ly-cyan,#5fe3ff);background:rgba(95,227,255,.14)}
.hb-rk{font-size:12px;color:var(--ly-dim,#a9b0d6)}
"""
