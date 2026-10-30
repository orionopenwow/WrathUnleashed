"""Leyline guest pass: "Try Leyline in the Goldshire Inn", with no sign-up (loaded by wrath_portal.py).

OFF unless WU_GUEST_DEMO=1 (read on every request). When on:

  GET /wrath?demo=1     hands the visitor a guest login from the operator's pool and sends them to the
                        stream site (the same one-time-code gate as /wrath/play), where the client
                        page goes straight into the world as the pass's character (/__env.js carries
                        "char" and "demo": no character select).
  GET /wrath/demo       a preview page with the "Try it" section (section_html / SECTION_CSS: the
                        snippet for the bottom of the main page).

The pool is made by the operator (stream/server/demo-pool.sh): accounts LYDEMO01.. with one character
each, listed one per line as "<ACCOUNT> <Character>" in WU_DEMO_POOL (default demo-pool.txt next to
this file). No passwords are kept anywhere: each time a pass is handed out, and again when it ends, the
account gets a new random password through SOAP, so a pass works once, for one visitor.

  * one visitor per pass: a pass is busy until it ends; a visitor (by IP) who comes back while their
    pass is open gets the same pass again (their earlier page session is closed)
  * rate limit: at most WU_DEMO_PER_HOUR (3) new passes per IP per hour
  * a pass lasts WU_DEMO_MINUTES (20); then it is recycled: page sessions ended, the character logged
    out ("ovdemo end", realm/custom/lua_scripts/ov_demo.lua), the password changed, a minute's rest,
    free again. A pass whose recycling failed is never handed out until a retry succeeds.

The realm side (ov_demo.lua) holds LYDEMO characters in the Goldshire Inn and only while "ovdemo begin"
has opened their pass. Guest accounts are not stream-marked, so ov_slices.lua leaves them alone.
"""
from __future__ import annotations

import collections
import html
import logging
import os
import re
import secrets
import threading
import time

log = logging.getLogger("wrath-portal.demo")

# The one public base URL of the website (player-facing links). Keep ov_demo.lua's PUBLIC_BASE_URL in step.
PUBLIC_BASE_URL = "https://" + os.environ.get("PUBLIC_HOST", "play.openvanilla.app")
SIGNUP_URL = PUBLIC_BASE_URL + "/login?next=%2Fwrath"
SIGNUP_PATH = "/login?next=%2Fwrath"
TRY_PATH = "/wrath?demo=1"

PREFIX = "LYDEMO"
ACCOUNT_RE = re.compile(r"^LYDEMO[0-9A-Z]{1,10}$")
CHAR_RE = re.compile(r"^[A-Z][a-z]{1,11}$")
MODE = "demo"           # the page session's mode (wrath_portal.Sessions)
COOL_S = 60             # rest between two visitors of one pass
SWEEP_S = 20


def demo_on() -> bool:
    return os.environ.get("WU_GUEST_DEMO", "0").strip() == "1"


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(os.environ.get(name, default)), hi))
    except ValueError:
        return default


def pass_minutes() -> int:
    return _int_env("WU_DEMO_MINUTES", 20, 5, 120)


def per_hour() -> int:
    return _int_env("WU_DEMO_PER_HOUR", 3, 1, 50)


def pool_path() -> str:
    return os.environ.get("WU_DEMO_POOL") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-pool.txt")


def demo_slice() -> str:
    return os.environ.get("WU_DEMO_SLICE", "mini").strip() or "mini"


def new_password() -> str:
    """A random game password (letters and digits, 16: the realm's longest)."""
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789") for _ in range(16))


def parse_pool(text: str) -> list[tuple[str, str]]:
    """[(ACCOUNT, Character)] from the pool file; bad lines are skipped (and logged)."""
    out, seen = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not ACCOUNT_RE.match(parts[0].upper()) or not CHAR_RE.match(parts[1]):
            log.warning("demo pool line %d skipped (want: %s01 Charname)", n, PREFIX)
            continue
        acct = parts[0].upper()
        if acct in seen:
            continue
        seen.add(acct)
        out.append((acct, parts[1]))
    return out


class SoapBackend:
    """The realm, through the portal's SOAP (ac_soap). Every call raises on failure."""

    def __init__(self, soap, error_type=Exception):
        self.soap, self.error = soap, error_type

    def set_password(self, user: str, password: str) -> None:
        self.soap(f"account set password {user} {password} {password}")

    def begin(self, user: str, seconds: int) -> None:
        if "ovdemo ok" not in self.soap(f"ovdemo begin {user} {int(seconds)}"):
            raise RuntimeError("the realm did not confirm ovdemo begin (is ov_demo.lua loaded?)")

    def end(self, user: str) -> None:
        if "ovdemo ok" not in self.soap(f"ovdemo end {user}"):
            raise RuntimeError("the realm did not confirm ovdemo end")


class Pool:
    """The guest passes and who holds them, in memory. States: free, busy, cool, dirty."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.passes: dict[str, dict] = {}
        self._mtime = None

    def load(self, entries: list[tuple[str, str]]) -> None:
        with self.lock:
            keep = {a for a, _ in entries}
            for a in [a for a, p in self.passes.items() if a not in keep and p["state"] == "free"]:
                del self.passes[a]
            for acct, char in entries:
                p = self.passes.get(acct)
                if p:
                    p["char"] = char
                else:
                    # Unknown password state: recycle it once before the first visitor.
                    self.passes[acct] = {"char": char, "state": "dirty", "ip": "", "pw": "", "exp": 0.0, "free_at": 0.0}

    def reload(self, path: str) -> None:
        try:
            m = os.stat(path).st_mtime
        except OSError:
            return
        if m == self._mtime:
            return
        try:
            with open(path, encoding="utf-8-sig") as f:
                entries = parse_pool(f.read())
        except OSError as e:
            log.warning("demo pool %s unreadable: %s", path, e)
            return
        self._mtime = m
        self.load(entries)
        log.info("demo pool: %d passes", len(entries))

    def held_by(self, ip: str) -> str | None:
        now = self.clock()
        with self.lock:
            for a, p in self.passes.items():
                if p["state"] == "busy" and p["ip"] == ip and p["exp"] > now:
                    return a
        return None

    def take(self, ip: str) -> str | None:
        with self.lock:
            free = sorted(a for a, p in self.passes.items() if p["state"] == "free")
            if not free:
                return None
            a = free[0]
            self.passes[a].update(state="busy", ip=ip, exp=self.clock() + pass_minutes() * 60)
            return a

    def counts(self) -> dict:
        with self.lock:
            return dict(collections.Counter(p["state"] for p in self.passes.values()))


class Demo:
    """The guest-pass flow. The portal passes in what it owns (SOAP, sessions, the slice and stream
    switches, the stream host, the Leyline page CSS), so this module has no import of wrath_portal."""

    def __init__(self, backend, sessions, slice_info, stream_on, stream_host, base_css=lambda: "",
                 clock=time.time, monotonic=time.monotonic):
        self.backend, self.sessions, self.slice_info, self.stream_on = backend, sessions, slice_info, stream_on
        self.stream_host, self.base_css = stream_host, base_css
        self.clock, self.monotonic = clock, monotonic
        self.pool = Pool(clock)
        self.hits: dict[str, collections.deque] = {}
        self.hits_lock = threading.Lock()
        self._thread = None

    # -- rate limit --------------------------------------------------------------------------------

    def _allow(self, ip: str) -> bool:
        now = self.monotonic()
        with self.hits_lock:
            q = self.hits.setdefault(ip, collections.deque())
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= per_hour():
                return False
            q.append(now)
            if len(self.hits) > 20000:
                self.hits = {k: v for k, v in self.hits.items() if v}
            return True

    # -- the flow ----------------------------------------------------------------------------------

    def start(self, ip: str):
        """GET /wrath?demo=1. ("redirect", url) or ("page", status, body)."""
        if not demo_on():
            return "page", 404, self.notice("Guest passes are closed right now",
                                            "Make a free account and you can play straight away.")
        info = self.slice_info(demo_slice()) if self.stream_on() else None
        if not info:
            return "page", 503, self.notice("The browser realm is resting",
                                            "Playing in the browser is switched off for a moment. Please try again soon.")
        self.sweep()
        user = self.pool.held_by(ip)
        if user:
            p = self.pool.passes[user]
            self.sessions.end_user(user)     # one session per pass: the newest page wins
            code = self.sessions.create(user, p["pw"], info["slug"], info["tier"], mode=MODE)
            log.info("demo pass %s handed again to its visitor", user)
            return "redirect", self.gate_url(code)
        if not self._allow(ip):
            return "page", 429, self.notice("That's a lot of visits",
                                            "Guest passes are limited per connection. Make a free account to keep playing.")
        user = self.pool.take(ip)
        if not user:
            return "page", 503, self.notice("Every guest pass is in use",
                                            "The inn is full. Passes free up every few minutes; please try again soon.")
        password = new_password()
        try:
            self.backend.set_password(user, password)
            self.backend.begin(user, pass_minutes() * 60)
        except Exception as e:  # noqa: BLE001 (SOAP or realm): never hand out a half-made pass
            log.error("demo pass %s could not open: %s", user, str(e)[:160])
            with self.pool.lock:
                self.pool.passes[user].update(state="dirty", ip="", pw="")
            return "page", 503, self.notice("The realm isn't answering",
                                            "Please try again in a minute.")
        with self.pool.lock:
            self.pool.passes[user]["pw"] = password
        self.sessions.end_user(user)
        code = self.sessions.create(user, password, info["slug"], info["tier"], mode=MODE)
        log.info("demo pass %s opened (%d min)", user, pass_minutes())
        return "redirect", self.gate_url(code)

    def gate_url(self, code: str) -> str:
        from urllib.parse import quote
        return f"https://{self.stream_host()}/__gate?code={quote(code)}"

    def env_extra(self, sess: dict) -> dict:
        """What /__env.js adds for a guest session: the character to seat (no character select)."""
        p = self.pool.passes.get(str(sess.get("user", "")).upper())
        if not p or p["state"] != "busy":
            return {"demo": "1"}
        return {"demo": "1", "char": p["char"], "signup": SIGNUP_URL}

    def sweep(self) -> None:
        """Recycle ended passes; free rested ones; retry failed ones."""
        self.pool.reload(pool_path())
        now = self.clock()
        with self.pool.lock:
            due = [a for a, p in self.pool.passes.items()
                   if (p["state"] == "busy" and p["exp"] <= now) or p["state"] == "dirty"]
            for a, p in self.pool.passes.items():
                if p["state"] == "cool" and p["free_at"] <= now:
                    p["state"] = "free"
        for a in due:
            had_visitor = self.pool.passes[a]["state"] == "busy"
            self.sessions.end_user(a)
            try:
                try:
                    self.backend.end(a)
                except Exception as e:  # noqa: BLE001: a missing realm row is fine; the password change is what counts
                    log.warning("demo pass %s: end: %s", a, str(e)[:160])
                self.backend.set_password(a, new_password())
            except Exception as e:  # noqa: BLE001
                log.error("demo pass %s could not be recycled: %s", a, str(e)[:160])
                with self.pool.lock:
                    self.pool.passes[a].update(state="dirty", ip="", pw="")
                continue
            with self.pool.lock:   # after a visitor, a short rest (their page notices it ended); else free now
                self.pool.passes[a].update(state="cool" if had_visitor else "free", ip="", pw="",
                                           free_at=self.clock() + COOL_S)
            log.info("demo pass %s recycled", a)

    def start_thread(self) -> None:
        if self._thread:
            return

        def loop():
            while True:
                time.sleep(SWEEP_S)
                if not demo_on() and not any(p["state"] in ("busy", "dirty") for p in self.pool.passes.values()):
                    continue
                try:
                    self.sweep()
                except Exception:  # noqa: BLE001
                    log.exception("demo sweep")
        self._thread = threading.Thread(target=loop, name="demo-sweep", daemon=True)
        self._thread.start()

    # -- pages -------------------------------------------------------------------------------------

    def page(self, title: str, body: str) -> bytes:
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
                f'<title>{html.escape(title)}</title><style>{self.base_css()}{SECTION_CSS}</style></head>'
                f'<body class="ly"><div class="ly-wrap">{body}</div></body></html>').encode("utf-8")

    def notice(self, title: str, text: str) -> bytes:
        e = html.escape
        return self.page(title, f'<section class="ly-panel ly-demo"><h2>{e(title)}</h2>'
                                f'<p class="ly-demo-lede">{e(text)}</p><div class="ly-demo-go">'
                                f'<a class="ly-btn" href="{e(SIGNUP_PATH)}">Make a free account</a>'
                                f'<a class="ly-demo-alt" href="/wrath/leyline">Back to Leyline</a></div></section>')

    def preview(self) -> bytes:
        return self.page("Try Leyline in the Goldshire Inn", section_html())


# -- the section for the main page -----------------------------------------------------------------
# Drop section_html() at the bottom of the Leyline page and SECTION_CSS after LEYLINE_CSS. It uses the
# page's own tokens and its .ly-panel / .ly-btn / .ly-fine, with fallbacks so it also stands alone.

SECTION_CSS = """
.ly-demo{text-align:center;padding:26px 18px 22px;background:linear-gradient(180deg,rgba(40,30,18,.55),var(--ly-panel,rgba(14,16,40,.78)) 70%);
border-color:rgba(240,190,110,.35)}
.ly-demo h2{margin-bottom:8px}
.ly-demo-lede{max-width:560px;margin:0 auto 14px;color:var(--ly-ink,#e8ecff)}
.ly-demo-facts{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;list-style:none;margin:0 0 18px;padding:0}
.ly-demo-facts li{font-size:14px;color:var(--ly-dim,#a9b0d6);border:1px solid var(--ly-line,rgba(120,150,255,.28));border-radius:999px;padding:4px 12px;
background:rgba(18,22,54,.6)}
.ly-demo-go{display:flex;flex-direction:column;align-items:center;gap:10px}
.ly-demo-go .ly-btn{min-width:min(280px,100%);background:linear-gradient(180deg,rgba(150,96,36,.95),rgba(70,40,14,.96));border-color:rgba(255,206,130,.6)}
.ly-demo-go .ly-btn:hover,.ly-demo-go .ly-btn:focus-visible{border-color:#ffd889;box-shadow:0 0 18px rgba(255,200,110,.4)}
.ly-demo-alt{font-size:14px}
.ly-demo .ly-fine{margin-top:14px}
"""


def section_html() -> str:
    """The "Try it in the Goldshire Inn" section (HTML only; style: SECTION_CSS)."""
    m = pass_minutes()
    return (
        '<section class="ly-panel ly-demo" id="try" aria-labelledby="ly-try">'
        '<h2 id="ly-try">Try Leyline in the Goldshire Inn</h2>'
        '<p class="ly-demo-lede">No sign-up and no download. One click and you are standing in the Goldshire Inn, '
        'in your browser, as a guest: look around, meet the regulars, try the controls.</p>'
        f'<ul class="ly-demo-facts"><li>{m}-minute guest pass</li><li>Runs in the browser</li>'
        '<li>Free account to keep playing</li></ul>'
        f'<div class="ly-demo-go"><a class="ly-btn" href="{html.escape(TRY_PATH)}">Try it</a></div>'
        '<p class="ly-fine">Guest passes are shared and reset after each visit, so chat channels, whispers, trade, mail '
        f'and groups are off. <a href="{html.escape(SIGNUP_PATH)}">Make a free account</a> to keep a character and go further.</p>'
        '</section>')
