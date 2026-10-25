#!/usr/bin/env python3
"""WrathUnleashed sign-in bridge (Python 3 standard library only).

Players sign in with the website's own sign-in (Google or a Hero Key, served by the Open Vanilla
realm service at play.openvanilla.app). This service then shows them their Wrath (3.3.5a) game
login. There are no separate Wrath accounts to hand out.

Two listeners, both inside Docker networks only (never published on the host):

  :8091  the page, behind the site's Caddy at https://play.openvanilla.app/wrath
         GET /wrath            signed out: a button to the site's sign-in (Google or Hero Key)
                               signed in:  the player's game account name and password
         GET /wrath/healthz    200 when AzerothCore's SOAP answers
         GET /wrath/realms     public: the official realm first, then community realms from the
                               Beacons relay's listing (cached; a dead relay never slows the page)
         GET /wrath/armory[/<Name>]  public: the web armory (stream/armory.py), read from the files that
                               realm/custom/armory-export.py writes to /app/armory every 5 minutes
         GET /wrath/mods       public: the mods Workshop (stream/workshop.py, optional): the catalog the
                               "mods" step publishes into /app/mods, one page per mod, the zips
         GET /wrath/status.json  public realm status for the website's Beacons page, the launcher
                               and the GM console (CORS *, cached 30 s, at most one SOAP call per
                               30 s however many visitors ask)

  :7878  a SOAP bridge for the realm service, on its network under the name "mangosd". The
         realm service was written for the 1.12 server: it speaks SOAP with the urn:MaNGOS
         namespace and its own console login. The bridge passes a short list of commands
         (account create / set password / delete, kick, ban, unban, announce, server info) to
         AzerothCore's SOAP with this service's own GM login, so new web accounts are created
         straight on the Wrath realm. Anything else is refused.

How a player's account is made: the realm service already owns one game account per web user
(name WR000123, a random 16-character password kept encrypted in its own database), handed to
its play page by GET /api/play. This page asks for the same thing with the player's own cookie,
then makes sure that account exists on AzerothCore with that password (create, or reset the
password when it already exists). Accounts from the 1.12 days therefore carry over by name.

Play in the browser, streamed (a small "mini" slice of the game, never the full client):

  on play.openvanilla.app (Caddy routes /wrath* here):
         GET /wrath/play?mini=<slug>   signed in: marks the game account as a stream account on
                               the realm (SOAP "ovstream mark", handled by lua/ov_slices.lua,
                               which keeps it inside the slice), opens a 12 h play session and
                               redirects to https://<STREAM_HOST>/__gate?code=<one-time, 60 s>
         GET /wrath/play?mode=own   "Play with my own game files" in the browser: the same session
                               and gate, but NO realm mark (the whole world) and no game data from
                               the server: the page reads the player's own 3.3.5a Data folder
                               (ownfiles.js). Lands on https://<STREAM_HOST>/?ownfiles=1. Works with
                               streaming off (WU_STREAM=0); needs WU_OWNFILES=1 (stream-up.sh sets it:
                               the stream site must exist). Clears an earlier stream mark first.
         GET /wrath/play/end   ends the player's sessions and clears the realm mark, so their
                               account is not held to the slice when they play with their own files
  on the stream site (STREAM_HOST, its own Caddy site block):
         GET /__gate?code=     swaps the code for the HttpOnly Secure SameSite=Lax cookie wu_play
         GET /__auth           Caddy forward_auth for everything else on the site: 200 for a live
                               session, otherwise a 302 to the /wrath page (403 for /data and /ws
                               while streaming is off). An own-files session: the page and /ws
                               always, /data never (403: they read their own files)
         GET /__env.js         window.__wenilla_env = {user, pass, host, ...} for that session only
                               (no-store, same-origin only); the client logs in with it
  The off switch: WU_STREAM=0 (the default until stream-up.sh sets 1). /wrath/play then says
  streaming is off and /__auth refuses the game data. Sessions are in memory: a restart of this
  service signs stream players out of the stream site (they click Play again).

Settings (environment, /srv/wrath/portal.env):
  SOAP_USER, SOAP_PASS   AzerothCore GM level 3 account for SOAP (required; deploy.sh makes it)
  AC_SOAP_URL            default http://ov-ac-worldserver:7878/
  PORTAL_URL             default http://ovlive-realm:8090 (the Open Vanilla realm service)
  PUBLIC_HOST            default play.openvanilla.app
  REALM_NAME             default WrathUnleashed
  PACKAGE_URL            optional link to the player package (shown on the page when set)
  BRIDGE_USERS           console logins the realm service may use (default WRSOAP,ADMINISTRATOR)
  WU_STREAM              1 = browser streaming on, 0 = off (default 0)
  STREAM_HOST            default wrath.openvanilla.app
  STREAM_SLICES          the slice names /wrath/play accepts (default mini)
  WU_SLICE_DIR           where <slice>.json lives (default /app/slices; maxTier is read from it)
  WU_OWNFILES            1 = show "Play with my own game files" (the browser client on STREAM_HOST
                         with the player's own Data folder); 0 = off (default; stream-up.sh sets 1)
  WU_RELAY_LISTING       the Beacons relay's listing for GET /wrath/realms. Unset: the URL in
                         /app/relay-listing.url (the relay step writes the relay's address on the Docker
                         network there, so the list works without DNS), else
                         https://relay.openvanilla.app/api/listing/realms.json
  WU_JOIN_BASE           where a community realm's Join link goes (default https://relay.openvanilla.app,
                         which serves /join/<realm id> itself)
  WU_MODS_DIR            the published mods catalog for /wrath/mods (default /app/mods = /srv/wrath/portal/mods,
                         written by stream/server/mods-install.sh)
  WU_ART_DIR             the site art and theme (default /app/art = /srv/wrath/portal/art on the host,
                         installed from stream/www-files/art by fastloop.sh), served at /wrath/art/<name>
                         from a fixed list. Missing: the pages fall back to plain CSS.

Passwords are never logged.
"""

from __future__ import annotations

import base64
import collections
import hashlib
import html
import importlib.util
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape as xml_escape


def _load_links():
    """stream/links.py (the /r /h /q /m /u share links), loaded from beside this file (python3 -I leaves
    this folder off sys.path). None when it is missing or broken: the portal runs without those links."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("wu_links", os.path.join(os.path.dirname(os.path.abspath(__file__)), "links.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


links = _load_links()


def _load_armory():
    """stream/armory.py (the web armory at /wrath/armory), beside this file like links.py; None when it is
    missing or broken: the portal runs without it."""
    try:
        spec = importlib.util.spec_from_file_location("wu_armory", os.path.join(os.path.dirname(os.path.abspath(__file__)), "armory.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _load_module(name: str, file: str):
    """A module beside this file (python3 -I leaves this folder off sys.path), or None when missing or broken."""
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), file))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _load_modes():
    """stream/modes.py (GET /wrath/modes and the go intent; its data is stream/modes_data.py), from beside
    this file. None when missing or broken: the portal runs without them."""
    try:
        spec = importlib.util.spec_from_file_location("wu_modes", os.path.join(os.path.dirname(os.path.abspath(__file__)), "modes.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if links is not None:
            links.NAMES.update(mod.names())   # share cards say "The Deadmines", not "deadmines"
        return mod
    except Exception:
        return None


armory = _load_armory()
modes = _load_modes()
workshop_mod = _load_module("wu_workshop", "workshop.py")   # /wrath/mods (stream/workshop.py); set up below


def go_param(query: dict) -> str:
    """'&go=<kind>:<id>' for a share-link deep link carried through sign-in (checked again at every hop), else ''."""
    if links is None:
        return ""
    v = (query.get("go") or [""])[0][:40]
    got = links.check_go(v) if v else None
    return "&go=" + urllib.parse.quote(links.go_value(*got), safe=":") if got else ""

SOAP_USER = os.environ.get("SOAP_USER", "")
SOAP_PASS = os.environ.get("SOAP_PASS", "")
AC_SOAP_URL = os.environ.get("AC_SOAP_URL", "http://ov-ac-worldserver:7878/")
PORTAL_URL = os.environ.get("PORTAL_URL", "http://ovlive-realm:8090").rstrip("/")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "play.openvanilla.app")
REALM_NAME = os.environ.get("REALM_NAME", "WrathUnleashed")
PACKAGE_URL = os.environ.get("PACKAGE_URL", "")
BRIDGE_USERS = {u.strip().upper() for u in os.environ.get("BRIDGE_USERS", "WRSOAP,ADMINISTRATOR").split(",") if u.strip()}
PAGE_PORT = int(os.environ.get("PAGE_PORT", "8091"))
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "7878"))
# Only the live realm service may use the bridge: its "ovlive-realm" alias is its alone (staging,
# Duels and Warfront run their own realm services on the same network with other account lists).
BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "ovlive-realm")

STREAM_HOST = os.environ.get("STREAM_HOST", "wrath.openvanilla.app")
STREAM_SLICES = {x.strip() for x in os.environ.get("STREAM_SLICES", "mini").split(",") if x.strip()}
SLICE_DIR = os.environ.get("WU_SLICE_DIR", "/app/slices")
ART_DIR = os.environ.get("WU_ART_DIR", "/app/art")
# Forever UI in the browser client (only where it is installed: fui-install.sh lays it over the slice).
# "1" turns it on; WU_FOREVERUI=0 in portal.env gives everyone the stock look. ?foreverui=0 on the page wins.
FOREVERUI = "0" if os.environ.get("WU_FOREVERUI", "1").strip() == "0" else "1"
SESSION_TTL = 12 * 3600
CODE_TTL = 60
DISCORD_URL = "https://discord.gg/hVeUxYwbkr"
DISCORD_HELP = ("Need help finding or setting up your own 3.3.5a game folder? Join our Discord and "
                "people will help: " + DISCORD_URL)

ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
PASS_RE = re.compile(r"^[\x21-\x7e]{1,16}$")
# What the realm service may run through the bridge (lower-case prefixes).
BRIDGE_ALLOW = ("account create ", "account set password ", "account delete ", "server info",
                "kick ", "ban account ", "ban character ", "unban account ", "unban character ",
                "announce ", "notify ")

log = logging.getLogger("wrath-portal")


# ----------------------------------------------------------------------------------------------
# AzerothCore SOAP
# ----------------------------------------------------------------------------------------------

class SoapError(Exception):
    """kind: 'fault' (the console said no; detail is its text), 'auth', 'down'."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail


def _tag_text(body: bytes, tag: str) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            return el.text.strip()
    return ""


_soap_lock = threading.Lock()  # AzerothCore's SOAP serves one request at a time


def ac_soap(command: str) -> str:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:xsi="http://www.w3.org/1999/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/1999/XMLSchema" xmlns:ns1="urn:AC">'
        f"<SOAP-ENV:Body><ns1:executeCommand><command>{xml_escape(command)}</command>"
        "</ns1:executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    ).encode("utf-8")
    token = base64.b64encode(f"{SOAP_USER}:{SOAP_PASS}".encode()).decode("ascii")
    req = urllib.request.Request(AC_SOAP_URL, data=envelope, method="POST", headers={
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"urn:AC#executeCommand"',
        "Authorization": f"Basic {token}",
    })
    with _soap_lock:
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return _tag_text(resp.read(), "result")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SoapError("auth", f"HTTP {e.code}") from None
            raise SoapError("fault", _tag_text(e.read(), "faultstring") or f"HTTP {e.code}") from None
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise SoapError("down", str(e)) from None


# Accounts already checked since this process started: name -> password fingerprint.
_ensured: dict[str, str] = {}
_ensured_lock = threading.Lock()


def ensure_account(name: str, password: str) -> None:
    """The game account exists on AzerothCore with this password."""
    if not ACCOUNT_RE.match(name) or not PASS_RE.match(password):
        raise SoapError("fault", "unexpected account name or password shape")
    fp = hashlib.sha256(password.encode()).hexdigest()
    with _ensured_lock:
        if _ensured.get(name.upper()) == fp:
            return
    try:
        ac_soap(f"account create {name} {password}")
        log.info("account created on Wrath: %s", name.upper())
    except SoapError as e:
        if e.kind == "fault" and "exist" in e.detail.lower():
            ac_soap(f"account set password {name} {password} {password}")
            log.info("account checked on Wrath: %s", name.upper())
        else:
            raise
    with _ensured_lock:
        _ensured[name.upper()] = fp


# ----------------------------------------------------------------------------------------------
# The Open Vanilla realm service (who is signed in, and their game account)
# ----------------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect means "not signed in"
        return None


_portal = urllib.request.build_opener(_NoRedirect)


def portal_get(path: str, cookie: str, ip: str, ua: str) -> tuple[int, dict]:
    req = urllib.request.Request(PORTAL_URL + path, headers={
        "Cookie": cookie,
        "Host": PUBLIC_HOST,
        "X-Forwarded-For": ip,
        "X-Real-IP": ip,
        "User-Agent": ua[:200],
        "Accept": "application/json",
        "X-Requested-With": "wenilla",
    })
    try:
        with _portal.open(req, timeout=15) as resp:
            body = resp.read(65536)
            try:
                return resp.status, json.loads(body.decode("utf-8"))
            except ValueError:
                return resp.status, {}
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, socket.timeout, OSError):
        return 0, {}


# ----------------------------------------------------------------------------------------------
# Play in the browser, streamed: sessions, one-time codes, the realm mark
# ----------------------------------------------------------------------------------------------

SLUG_RE = re.compile(r"^[a-z0-9-]{1,32}$")


def stream_on() -> bool:
    """The off switch, read on every request (WU_STREAM=1 turns streaming on)."""
    return os.environ.get("WU_STREAM", "0").strip() == "1"


def ownfiles_on() -> bool:
    """"Play with my own game files" in the browser (WU_OWNFILES=1). Independent of WU_STREAM."""
    return os.environ.get("WU_OWNFILES", "0").strip() == "1"


OWN = "own"  # the session mode of "Play with my own game files"


def slice_info(slug: str) -> dict | None:
    """<WU_SLICE_DIR>/<slug>.json, or None when the slice is unknown or not set up here."""
    if slug not in STREAM_SLICES or not SLUG_RE.match(slug):
        return None
    try:
        with open(os.path.join(SLICE_DIR, slug + ".json"), encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        tier = max(0, min(int(doc.get("maxTier", 0)), 99))
    except (TypeError, ValueError):
        tier = 0
    return {"slug": slug, "tier": tier, "title": str(doc.get("title") or slug)}


class Sessions:
    """Play sessions (id -> game login) and their one-time codes, in memory only."""

    MAX_SESSIONS = 5000
    PER_USER = 3

    def __init__(self):
        self.lock = threading.Lock()
        self.sessions: dict[str, dict] = {}
        self.codes: dict[str, tuple[str, float]] = {}

    def _sweep(self, now: float) -> None:
        for k in [k for k, v in self.sessions.items() if v["exp"] <= now]:
            del self.sessions[k]
        for k in [k for k, v in self.codes.items() if v[1] <= now]:
            del self.codes[k]

    def create(self, user: str, password: str, slug: str, tier: int, mode: str = "stream") -> str:
        """A new session and its one-time code (returns the code). mode "stream" (the slice, the
        realm mark) or OWN (the player's own game files: no mark, no /data)."""
        now = time.time()
        sid, code = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.lock:
            self._sweep(now)
            mine = sorted((v["exp"], k) for k, v in self.sessions.items() if v["user"] == user.upper())
            for _, k in mine[: max(0, len(mine) - self.PER_USER + 1)]:
                del self.sessions[k]
            while len(self.sessions) >= self.MAX_SESSIONS:
                del self.sessions[min(self.sessions, key=lambda k: self.sessions[k]["exp"])]
            self.sessions[sid] = {"user": user.upper(), "pass": password, "slice": slug,
                                  "tier": tier, "mode": mode, "exp": now + SESSION_TTL}
            self.codes[code] = (sid, now + CODE_TTL)
        return code

    def redeem(self, code: str) -> str | None:
        """The session id for a one-time code (the code is gone afterwards either way)."""
        now = time.time()
        with self.lock:
            got = self.codes.pop(code, None)
            if not got or got[1] <= now or got[0] not in self.sessions:
                return None
            return got[0]

    def get(self, sid: str) -> dict | None:
        now = time.time()
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s["exp"] <= now:
                self.sessions.pop(sid, None)
                return None
            return dict(s)

    def end_user(self, user: str) -> int:
        with self.lock:
            gone = [k for k, v in self.sessions.items() if v["user"] == user.upper()]
            for k in gone:
                del self.sessions[k]
            for c in [c for c, v in self.codes.items() if v[0] in gone]:
                del self.codes[c]
        return len(gone)


sessions = Sessions()


def realm_mark(user: str, slug: str, tier: int, seconds: int) -> None:
    """Flag the account on the realm (acore_auth.ov_stream_accounts, written by ov_slices.lua's
    console command). Raises SoapError when the realm did not confirm: streaming then stays shut,
    because an unmarked account would not be held to the slice."""
    if not ACCOUNT_RE.match(user) or not SLUG_RE.match(slug):
        raise SoapError("fault", "unexpected account or slice name")
    text = ac_soap(f"ovstream mark {user.upper()} {slug} {int(tier)} {int(seconds)}")
    if "ovstream ok" not in text:
        raise SoapError("fault", "the realm did not confirm the stream mark (is ov_slices.lua loaded?)")


def realm_clear(user: str) -> None:
    if not ACCOUNT_RE.match(user):
        raise SoapError("fault", "unexpected account name")
    text = ac_soap(f"ovstream clear {user.upper()}")
    if "ovstream ok" not in text:
        raise SoapError("fault", "the realm did not confirm clearing the stream mark")


def cookie_value(header: str, name: str) -> str:
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def env_js(sess: dict) -> bytes:
    """The page env the web client reads before its query string (benilla_app::webenv)."""
    if sess.get("mode") == OWN:
        env = {"user": sess["user"], "pass": sess["pass"], "host": PUBLIC_HOST, "mode": OWN}
    else:
        env = {"user": sess["user"], "pass": sess["pass"], "host": PUBLIC_HOST,
               "slice": sess["slice"], "slice_tier": str(sess["tier"])}
    env["moderncombos"] = "1"   # character create offers the realm's 83 retail race/class pairs
    env["foreverui"] = FOREVERUI  # Forever UI on (the client reads this before its query string)
    if guest and sess.get("mode") == "demo":
        env.update(guest.env_extra(sess))  # the guest pass's character: no character select
    body = json.dumps(env, separators=(",", ":")).replace("<", "\\u003c")
    out = f"window.__wenilla_env = {body};\n"
    # The env object outranks the query string in the client, so ?foreverui=0 (or 1) is copied in.
    out += ("(function(e){try{var v=new URLSearchParams(location.search).get('foreverui');"
            "if(v!==null)e.foreverui=v;}catch(_){}})(window.__wenilla_env);\n")
    if sess.get("mode") == OWN:
        # ownfiles.js offers "Stream a mini version instead" when streaming is on.
        url = json.dumps(f"https://{PUBLIC_HOST}/wrath/play?mini=mini")
        out += (f"window.WU_STREAM_AVAILABLE = {'true' if stream_on() and slice_info('mini') else 'false'};\n"
                f"window.WU_STREAM_URL = {url};\n")
    return out.encode("utf-8")


# ----------------------------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------------------------

# The look: the shared theme (stream/www-files/art/wu-theme.css, also used by the control window and the GM
# console) and its art, served from ART_DIR at /wrath/art/<name> (the stream site is behind the sign-in gate
# and fonts need CORS, so the art can't come from there). STYLE is this page's layout plus a plain fallback
# that reads well on its own when the art is missing; its colour rules sit in :where() (no specificity) so
# the theme, linked after it, always wins.
ART_TYPES = {
    "wu-theme.css": "text/css; charset=utf-8",
    "wu-load-orion.webp": "image/webp", "wu-load-bg.webp": "image/webp",
    "wu-corner-tl.webp": "image/webp", "wu-corner-tr.webp": "image/webp",
    "wu-corner-bl.webp": "image/webp", "wu-corner-br.webp": "image/webp",
    "wu-divider.webp": "image/webp", "wu-dragon-l.webp": "image/webp", "wu-dragon-r.webp": "image/webp",
    "Cinzel-SemiBold.woff2": "font/woff2", "Cinzel-OFL.txt": "text/plain; charset=utf-8",
    "wu-card.webp": "image/webp",   # the link-preview card (tools/art/wu-card.html, 1200 x 630)
    "leyline-emblem.webp": "image/webp", "leyline-bg.webp": "image/webp",   # the Leyline page (owner's art)
    "leyline-shot-dalaran.webp": "image/webp", "leyline-shot-start.webp": "image/webp",   # gallery (live client shots)
    "leyline-shot-city.webp": "image/webp", "leyline-shot-durotar.webp": "image/webp",
    "leyline-display.woff2": "font/woff2", "leyline-display-OFL.txt": "text/plain; charset=utf-8",   # Big Shoulders Display 600 (SIL OFL 1.1, leyline-display-OFL.txt)
    "leyline-corner-tl.webp": "image/webp", "leyline-corner-tr.webp": "image/webp",   # our gold frame art, hued blue
    "leyline-corner-bl.webp": "image/webp", "leyline-corner-br.webp": "image/webp", "leyline-divider.webp": "image/webp",
    # the owner's screenshots for /wrath/modes (stream/modes.py); a missing one leaves a painted panel
    "leyline-shot-dalaran.webp": "image/webp", "leyline-shot-start.webp": "image/webp",
    "leyline-shot-city.webp": "image/webp", "leyline-shot-durotar.webp": "image/webp",
}
ART_MAX_AGE = 7 * 86400
_theme_ver = {"key": None, "v": ""}


def art_bytes(name: str) -> bytes | None:
    """One file from the allow-list in ART_DIR, or None (not listed, or missing). Never a path from the URL."""
    if name not in ART_TYPES:
        return None
    try:
        with open(os.path.join(ART_DIR, name), "rb") as f:
            return f.read(4_000_000)
    except OSError:
        return None


def theme_version() -> str:
    """A short hash of wu-theme.css for its link (?v=), so a new theme shows at once; "" when it is missing."""
    p = os.path.join(ART_DIR, "wu-theme.css")
    try:
        st = os.stat(p)
    except OSError:
        return ""
    key = (st.st_mtime_ns, st.st_size)
    if _theme_ver["key"] != key:
        b = art_bytes("wu-theme.css")
        _theme_ver.update(key=key, v=hashlib.sha256(b).hexdigest()[:10] if b else "")
    return _theme_ver["v"]


STYLE = """
:where(body){margin:0;min-height:100vh;background:#07060f;color:#ece6d6;font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px 16px;box-sizing:border-box;overflow-x:hidden}
main{width:min(31rem,100%);border-radius:6px;padding:28px 28px 24px;box-sizing:border-box}
:where(main){background:#12101e;border:1px solid #8a6a2c}
main.wide{width:min(36rem,100%)}
.crest{display:flex;justify-content:center;margin:0 0 2px}
h1{margin:0;font-size:1.75rem;text-align:center}
:where(h1){color:#f0d389;font-family:Georgia,serif;font-weight:600}
h2{margin:0;font-size:1.2rem}
:where(h2){color:#f0d389;font-family:Georgia,serif;font-weight:600}
.sub{margin:6px 0 18px;text-align:center;color:#b4ab96}
.rule{display:block;height:14px;margin:12px auto 16px;width:min(300px,80%);border:0}
:where(.rule){border-top:1px solid #4a3b1c;height:0}
p{margin:12px 0}.center{text-align:center}
:where(a.btn,button){display:inline-block;background:#8f1d14;color:#f0d389;border:1px solid #d8b25a;border-radius:4px;padding:9px 18px;font:600 1rem Georgia,serif;text-decoration:none;cursor:pointer}
:where(button.ghost){background:#1a1722;padding:6px 12px;font-size:.85rem}
:where(.btn.off){background:#1a1722;color:#8d8574;border-color:#4a3b1c;cursor:default}
.row{display:flex;gap:8px;align-items:center;margin:6px 0 14px;flex-wrap:wrap}
.field{flex:1 1 9rem;background:#05040c;border:1px solid #4a3b1c;border-radius:4px;padding:8px 10px;font:600 1.05rem ui-monospace,monospace;letter-spacing:.04em;min-width:0;overflow-wrap:anywhere;color:#ece6d6}
label{color:#b4ab96;font-size:.9rem}ol{padding-left:1.3rem}li{margin:5px 0}
.fine{color:#a59d8a;font-size:.9rem}.err{color:#ff9a8a;text-align:center}
:where(a){color:#f0d389;text-underline-offset:2px}
.fine a{color:#d8c08a}
:where(a,button,summary):focus-visible{outline:2px solid #f0d389;outline-offset:2px}
code{background:#05040c;border:1px solid #4a3b1c;border-radius:4px;padding:1px 5px;font-size:.9em;overflow-wrap:anywhere}
@media (max-width:480px){body{justify-content:flex-start;padding:16px}main{padding:22px 18px 18px}h1{font-size:1.45rem}}
"""


def art_url(name: str) -> str:
    return "/wrath/art/" + name


def art_present(name: str) -> bool:
    return name in ART_TYPES and os.path.isfile(os.path.join(ART_DIR, name))


CARD_DESCRIPTION = ("Play Wrath in your browser, on the Leyline network. "
                    "Dalaran hangout, Dungeon Finder, host your own realm.")


def card_meta(path: str, title: str = "") -> str:
    """Link-preview tags (Open Graph and X) for a public page, so a pasted link shows a proper card."""
    e = html.escape
    title = title or REALM_NAME
    url = f"https://{PUBLIC_HOST}{path}"
    img = f"https://{PUBLIC_HOST}{art_url('wu-card.webp')}"
    tags = [("property", "og:type", "website"), ("property", "og:site_name", REALM_NAME),
            ("property", "og:title", title), ("property", "og:description", CARD_DESCRIPTION),
            ("property", "og:url", url), ("property", "og:image", img),
            ("property", "og:image:type", "image/webp"), ("property", "og:image:width", "1200"),
            ("property", "og:image:height", "630"), ("property", "og:image:alt", f"{REALM_NAME}: Wrath on the Leyline network"),
            ("name", "twitter:card", "summary_large_image"), ("name", "twitter:title", title),
            ("name", "twitter:description", CARD_DESCRIPTION), ("name", "twitter:image", img)]
    return (f'<meta name="description" content="{e(CARD_DESCRIPTION)}"><link rel="canonical" href="{e(url)}">'
            + "".join(f'<meta {k}="{n}" content="{e(v)}">' for k, n, v in tags))


def render(body: str, nonce: str = "", script: str = "", wide: bool = False, meta: str = "") -> bytes:
    s = f'<script nonce="{nonce}">{script}</script>' if script else ""
    v = theme_version()
    theme = f'<link rel="stylesheet" href="{art_url("wu-theme.css")}?v={v}">' if v else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="dark">'
            f'<title>{html.escape(REALM_NAME)}</title>{meta}<style>{STYLE}</style>{theme}</head>'
            f'<body class="wu"><main class="wu-panel{" wide" if wide else ""}">{body}</main>{s}</body></html>').encode("utf-8")


def crest(title: str) -> str:
    """The page heading: the title between the two dragons, with the gold divider under it."""
    return f'<div class="crest wu-brand"><h1>{html.escape(title)}</h1></div>'


RULE = '<hr class="rule wu-divider">'


def signed_out_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}<p class="sub">Wrath · on the Leyline network</p>{RULE}'
        '<p class="center"><a class="btn primary" href="/login?next=%2Fwrath">Sign in with Google or your Hero Key</a></p>'
        '<p class="fine center">Played here before? Use the same sign-in. Your Wrath login appears here.</p>'
        '<p class="fine center"><a href="/wrath/realms">All realms</a>, including community realms hosted by players · '
        '<a href="/wrath/leyline">What is Leyline?</a></p>',
        meta=card_meta("/wrath"))


def stream_off_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}{RULE}'
        '<p class="center">Streaming is off right now — play with your own game files.</p>'
        '<p class="center"><a class="btn primary" href="/wrath">Get your game login</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>')


def stream_ended_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}{RULE}'
        '<p class="center">Your browser pass has ended. Your account can go anywhere again with your own game files.</p>'
        '<p class="center"><a class="btn" href="/wrath/account">Back</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>')


def busy_page(wait: int = 15, back: str = "/wrath") -> bytes:
    """A 429: the page tries again by itself (a meta refresh, no script) instead of leaving a dead end.
    Limits are per address, and a household or a cafe shares one, so the page stays calm about it."""
    body = (f'{crest(REALM_NAME)}<p class="sub">Lots of sign-ins from your network right now.</p>{RULE}'
            f'<p class="center">Trying again in {int(wait)} seconds…</p>'
            f'<p class="center"><a class="btn" href="{html.escape(back)}">Try now</a></p>')
    page = render(body).decode("utf-8")
    # back to the page that was busy (a browsing page must not bounce people into the game at /wrath)
    return page.replace("<head>", f'<head><meta http-equiv="refresh" content="{int(wait)};url={html.escape(back)}">', 1).encode("utf-8")


def error_page(msg: str) -> bytes:
    return render(f'{crest(REALM_NAME)}{RULE}<p class="err">{html.escape(msg)}</p>'
                  '<p class="center"><a class="btn" href="/wrath">Try again</a></p>')


COPY_JS = """
document.querySelectorAll('[data-copy]').forEach(function(b){b.addEventListener('click',function(){
var t=document.getElementById(b.dataset.copy);var v=t.dataset.v||t.textContent;
navigator.clipboard.writeText(v).then(function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1500)});});});
var sh=document.getElementById('show');if(sh)sh.addEventListener('click',function(){var p=document.getElementById('pw');
if(p.dataset.shown){p.textContent='\\u2022'.repeat(p.dataset.v.length);delete p.dataset.shown;sh.textContent='Show'}
else{p.textContent=p.dataset.v;p.dataset.shown='1';sh.textContent='Hide'}});
"""


SIGN_IN_URL = "/login?next=%2Fwrath"

# Signed out: a Hero Key this browser saved ("Save in this browser" on the realm site, a
# PasswordCredential whose password is the ovk1. key) signs in by itself, then comes back here.
# The /login fetch sets wr_next=/wrath, so the realm's /auth/key lands on /wrath. No saved key, a
# browser without the API, a refusal or 6 seconds of nothing: the normal sign-in page. Tried once per
# tab (sessionStorage), so a failed key never loops.
AUTO_SIGNIN_JS = """
(function(){
var go=function(){location.replace('%s')};
var tried=false;try{tried=sessionStorage.getItem('ov_autokey')==='1';sessionStorage.setItem('ov_autokey','1')}catch(e){}
if(tried||!window.PasswordCredential||!navigator.credentials){go();return}
var done=false,t=setTimeout(function(){if(!done){done=true;go()}},6000);
fetch('%s',{credentials:'same-origin',redirect:'manual'}).catch(function(){}).then(function(){
return navigator.credentials.get({password:true,mediation:'optional'})}).then(function(c){
if(done)return;done=true;clearTimeout(t);
if(!c||!c.password||c.password.indexOf('ovk1.')!==0){go();return}
var f=document.createElement('form');f.method='post';f.action='/auth/key';
var i=document.createElement('input');i.type='hidden';i.name='key';i.value=c.password;f.appendChild(i);
document.body.appendChild(f);f.submit()},function(){if(!done){done=true;clearTimeout(t);go()}});
})();
""" % (SIGN_IN_URL, SIGN_IN_URL)


def auto_signin_page(nonce: str) -> bytes:
    return render(
        f'{crest(REALM_NAME)}<p class="sub">Signing you in…</p>{RULE}'
        f'<p class="fine center"><a href="{SIGN_IN_URL}">Sign in another way</a></p>',
        nonce, AUTO_SIGNIN_JS, meta=card_meta("/wrath"))

REALM_CSS = """
.realm{position:relative;border:1px solid #4a3b1c;border-radius:4px;padding:16px 18px;margin:14px 0;background:rgba(5,4,12,.55);box-shadow:inset 0 0 0 1px rgba(0,0,0,.4)}
.realm h2{margin:0}.tags{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0 10px;font-size:.85rem;color:#b4ab96}
.tag{display:inline-block;border:1px solid #4a3b1c;border-radius:999px;padding:1px 9px;background:rgba(12,10,24,.7)}
.live{color:#6fd88a}
details{margin-top:10px}summary{cursor:pointer;color:#b4ab96;font-size:.92rem}summary:hover{color:#ece6d6}
details[open] summary{margin-bottom:10px}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:8px}
.eyebrow{font-size:.78rem;letter-spacing:.14em;text-transform:uppercase;color:#b4ab96;font-family:inherit;font-weight:600}
h2.eyebrow{margin:24px 0 4px;text-align:center}
.keylink{font-size:.9rem}
.realm p{margin:10px 0}.realm .btn{margin-top:2px}
.realm:first-of-type{border-color:#8a6a2c;box-shadow:inset 0 0 0 1px rgba(255,215,130,.08),inset 0 0 24px rgba(216,178,90,.07),0 8px 24px rgba(0,0,0,.35)}
.end{margin:12px 0 0}.foot{margin:20px 0 0;padding-top:14px;border-top:1px solid #2e2716}
@media (max-width:480px){.realm{padding:14px}.realm .btn{display:flex;width:100%;box-sizing:border-box;white-space:normal;text-align:center}}
"""


def realm_status() -> dict:
    try:
        return json.loads(status_json().decode("utf-8"))
    except Exception:  # noqa: BLE001 - the list still works without numbers
        return {}


def account_page(display: str, user: str, password: str, nonce: str) -> bytes:
    """The realm list a signed-in player lands on: Dalaran (instant, in the browser) first."""
    st = realm_status()
    players = st.get("players")
    online = st.get("online")
    live = ('<span class="live">● online</span>' + (f" · {int(players)} playing" if isinstance(players, int) else "")
            if online else "status unavailable")
    streamed = stream_on() and slice_info("mini")
    dalaran_btn = ('<a class="btn primary" href="/wrath/play?mini=mini">Play now</a>' if streamed
                   else '<span class="btn off">Opening soon</span>')
    pkg = (f'<li><a href="{html.escape(PACKAGE_URL)}">Download the player package</a> and unzip it.</li>'
           if PACKAGE_URL else '<li>Unzip the player package you were sent.</li>')
    dots = "\u2022" * len(password)
    body = (
        f'<style>{REALM_CSS}</style>'
        f'<div class="top"><span class="eyebrow">{html.escape(REALM_NAME)}</span>'
        '<a class="keylink" href="/account/key">Your Hero Key</a></div>'
        f'{crest("Choose a realm")}<p class="sub">Signed in as {html.escape(display)}</p>{RULE}'
        # 1. Dalaran: the streamed mini version
        '<div class="realm"><h2>Dalaran</h2>'
        f'<div class="tags"><span class="tag">In your browser</span><span class="tag">No download</span>{live}</div>'
        '<p>Jump straight in: Dalaran, arenas, dungeons and raids, streamed to your browser. '
        'Start at level 1 or boost to 80.</p>'
        f'<p>{dalaran_btn}</p>'
        # Warm the browser client while the player reads this page: the stream site's public
        # warm.html stores the client's wasm in that origin's Cache Storage and its scripts in the
        # HTTP cache (same site, so the game page reads the same copies). No game data, no sign-in.
        + (f'<iframe src="https://{html.escape(STREAM_HOST)}/warm.html" hidden aria-hidden="true" '
           'tabindex="-1" loading="eager" style="display:none"></iframe>' if streamed else '')
        + ('<p class="fine end"><a href="/wrath/play/end">End my browser pass</a></p>' if streamed else '')
        + '</div>'
        # 2. The whole world: own game files
        f'<div class="realm"><h2>{html.escape(REALM_NAME)}</h2>'
        f'<div class="tags"><span class="tag">The whole world</span><span class="tag">Your own 3.3.5a files</span>{live}</div>'
        '<p>The full game, on the same realm and with the same characters. Uses your own 3.3.5a '
        'game files, read on your computer and never uploaded.</p>'
        + ('<p><a class="btn" href="/wrath/play?mode=own">Play in the browser with my game folder</a></p>'
           if ownfiles_on() else '')
        + '<details id="desktop"><summary>Play with the desktop client or the player package</summary>'
        '<label>Account</label><div class="row">'
        f'<div class="field" id="acct">{html.escape(user)}</div>'
        '<button class="ghost" data-copy="acct" type="button">Copy</button></div>'
        '<label>Password</label><div class="row">'
        f'<div class="field" id="pw" data-v="{html.escape(password)}">{dots}</div>'
        '<button class="ghost" id="show" type="button">Show</button>'
        '<button class="ghost" data-copy="pw" type="button">Copy</button></div>'
        f'<ol>{pkg}<li>Run <b>Play WrathUnleashed.bat</b> and pick your own 3.3.5a game folder, '
        f'or set <code>realmlist {html.escape(PUBLIC_HOST)}</code> in your own client.</li>'
        '<li>Log in with the account and password above.</li></ol>'
        '<p class="fine">This login is yours alone. Sign in here again any time to see it.</p></details></div>'
        f'<p class="fine foot">No game files? Dalaran needs none. For the whole world: '
        f'{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}<a href="{DISCORD_URL}">{html.escape(DISCORD_URL.split("//")[-1])}</a></p>'
        '<p class="fine"><a href="/wrath/realms">Community realms</a>: Dalaran hangouts and realms hosted by players</p>'
        '<p class="fine"><a href="/wrath/modes">Modes</a>: duels, boss fights, dungeons and hangouts, one click each</p>')
    return render(body, nonce, COPY_JS, wide=True)


# ----------------------------------------------------------------------------------------------
# Community realms (GET /wrath/realms): the Beacons listing on the relay
# ----------------------------------------------------------------------------------------------
#
# Public realms hosted by players announce themselves to the relay (hosting/relay/wurelay/listing.py,
# signed heartbeats); its GET /api/listing/realms.json is read here in the BACKGROUND and cached, so a
# slow or dead relay never slows the play page: a request waits at most LISTING_WAIT seconds, and only
# when nothing was ever fetched since this process started. The official realm is always listed first,
# from this service's own status (never from the relay).

RELAY_LISTING = os.environ.get("WU_RELAY_LISTING", "")
RELAY_LISTING_DEFAULT = "https://relay.openvanilla.app/api/listing/realms.json"
# Written by the relay step (hosting/relay/deploy/relay-up.sh) into /srv/wrath/portal (mounted at /app):
# the relay's address on the Docker network, so the list works before DNS and without a container restart.
RELAY_LISTING_FILE = os.environ.get("WU_RELAY_LISTING_FILE", "/app/relay-listing.url")
JOIN_BASE = os.environ.get("WU_JOIN_BASE", "https://relay.openvanilla.app").rstrip("/")
LISTING_TTL = 60          # seconds a good answer is used before it is refreshed (in the background)
LISTING_RETRY = 30        # after a failure
LISTING_WAIT = 2.5        # the longest a page request ever waits for the relay
LISTING_MAX = 200
LISTING_BYTES = 2_000_000
REALM_ID_RE = re.compile(r"^[a-z2-7]{16}$")
RULESET_LABELS = {"main": "Level 1 or boost to 80", "brawl": "Brawl: everyone 80",
                  "progression": "Progression", "casual": "Casual", "dalaran": "Dalaran hangout",
                  "custom": "Custom rules"}
_listing: dict = {"at": -1e9, "ok": False, "realms": [], "fetched": False}
_listing_lock = threading.Lock()
_listing_busy = threading.Lock()
_listing_done = threading.Event()


def _nonneg(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000 else None


def clean_listing_record(rec) -> dict | None:
    """One listing record, reduced to what the page shows; None when it doesn't look like one."""
    if not isinstance(rec, dict) or rec.get("official"):   # only the official realm is official
        return None
    com = rec.get("community") if isinstance(rec.get("community"), dict) else {}
    rid = com.get("realmId")
    if not isinstance(rid, str) or not REALM_ID_RE.match(rid):
        return None
    prof = rec.get("profile") if isinstance(rec.get("profile"), dict) else {}
    hb = com.get("lastHeartbeat") if isinstance(com.get("lastHeartbeat"), dict) else {}
    ruleset = prof.get("ruleset") if prof.get("ruleset") in RULESET_LABELS else "custom"

    def txt(v, n):
        return " ".join(v.split())[:n] if isinstance(v, str) else ""
    return {"id": rid, "name": txt(rec.get("name"), 32) or "Unnamed realm", "tagline": txt(rec.get("tagline"), 80),
            "type": txt(rec.get("type"), 8) or "PvE", "ruleset": ruleset, "live": rec.get("state") == "live",
            "players": _nonneg(hb.get("players")), "bots": _nonneg(hb.get("bots")),
            "claimed": bool(com.get("claimed")),
            "rules": [t for t in (txt(x, 120) for x in (rec.get("rules") if isinstance(rec.get("rules"), list) else [])[:10]) if t]}


def listing_url() -> str:
    if RELAY_LISTING:
        return RELAY_LISTING
    try:
        with open(RELAY_LISTING_FILE, encoding="utf-8") as f:
            u = f.read().strip()
        if re.match(r"^https?://[A-Za-z0-9.:-]+/api/listing/realms\.json$", u):
            return u
    except OSError:
        pass
    return RELAY_LISTING_DEFAULT


def fetch_listing() -> list[dict]:
    req = urllib.request.Request(listing_url(), headers={"Accept": "application/json", "User-Agent": "wrath-portal"})
    with urllib.request.urlopen(req, timeout=LISTING_WAIT) as r:
        raw = r.read(LISTING_BYTES + 1)
    if len(raw) > LISTING_BYTES:
        raise ValueError("listing too large")
    doc = json.loads(raw.decode("utf-8"))
    recs = doc.get("realms") if isinstance(doc, dict) else None
    if not isinstance(recs, list):
        raise ValueError("not a listing")
    out, seen = [], set()
    for rec in recs[:LISTING_MAX]:
        c = clean_listing_record(rec)
        if c and c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    out.sort(key=lambda r: (not r["live"], -(r["players"] or 0), r["name"].lower()))
    return out


def _refresh_listing() -> None:
    try:
        realms, ok = fetch_listing(), True
    except Exception as e:  # noqa: BLE001 - any failure: keep the last good list, try again later
        realms, ok = None, False
        log.info("community listing unavailable: %s", str(e)[:120])
    with _listing_lock:
        _listing["at"] = time.monotonic()
        _listing["ok"] = ok
        _listing["fetched"] = True
        if ok:
            _listing["realms"] = realms
    _listing_busy.release()
    _listing_done.set()


def community_realms() -> tuple[list[dict], bool]:
    """(realms, fresh): the cached list and whether the last fetch worked. Never blocks longer than
    LISTING_WAIT, and only before the first fetch has finished."""
    with _listing_lock:
        age = time.monotonic() - _listing["at"]
        stale = age > (LISTING_TTL if _listing["ok"] else LISTING_RETRY)
        fetched = _listing["fetched"]
    if stale and _listing_busy.acquire(blocking=False):
        _listing_done.clear()
        threading.Thread(target=_refresh_listing, daemon=True).start()
    if not fetched:
        _listing_done.wait(LISTING_WAIT)
    with _listing_lock:
        return list(_listing["realms"]), _listing["ok"]


def _players_text(players, bots, live) -> str:
    if not live:
        return "offline"
    if players is None:
        return '<span class="live">● online</span>'
    s = f'<span class="live">● online</span> · {players} playing'
    return s + (f" · {bots} bots" if bots else "")


def realms_page() -> bytes:
    st = realm_status()
    official = (
        f'<div class="realm"><h2>{html.escape(REALM_NAME)}</h2>'
        '<div class="tags"><span class="tag">Official</span><span class="tag">Level 1 or boost to 80</span>'
        f'{_players_text(_nonneg(st.get("players")), _nonneg(st.get("bots")), bool(st.get("online")))}</div>'
        '<p>The WrathUnleashed realm: Dalaran in your browser, or the whole world with your own game files.</p>'
        '<p><a class="btn primary" href="/wrath">Play</a></p></div>')
    realms, ok = community_realms()
    rows = []
    for r in realms:
        name = html.escape(r["name"])
        tags = (f'<span class="tag">{html.escape(RULESET_LABELS[r["ruleset"]])}</span>'
                f'<span class="tag">{html.escape(r["type"])}</span>'
                + ('' if r["claimed"] else '<span class="tag">unclaimed</span>')
                + _players_text(r["players"], r["bots"], r["live"]))
        join = f'{JOIN_BASE}/join/{r["id"]}'
        rows.append(
            f'<div class="realm"><h2>{name}</h2><div class="tags">{tags}</div>'
            + (f'<p>{html.escape(r["tagline"])}</p>' if r["tagline"] else '')
            + ('<details><summary>House rules</summary><ol>'
               + "".join(f'<li>{html.escape(x)}</li>' for x in r["rules"]) + '</ol></details>' if r["rules"] else '')
            + f'<p><a class="btn" href="{html.escape(join)}" rel="noopener noreferrer">Join</a></p></div>')
    if rows:
        community = "".join(rows)
        if not ok:
            community = '<p class="fine">The realm list may be a little out of date right now.</p>' + community
    elif ok:
        community = ('<p class="fine">No community realms are open right now. Anyone can host one: '
                     'a private realm for friends or a public Dalaran hangout, with their own GM login and rules.</p>')
    else:
        community = '<p class="fine">The community realm list isn\'t reachable right now. Try again in a minute.</p>'
    body = (f'<style>{REALM_CSS}</style>'
            f'<div class="top"><span class="eyebrow">{html.escape(REALM_NAME)}</span>'
            '<a class="keylink" href="/wrath">Back</a></div>'
            f'{crest("Realms")}<p class="sub">Wrath · on the Leyline network</p>{RULE}'
            + official +
            '<h2 class="eyebrow">Community realms</h2>'
            + community +
            '<p class="fine foot">Community realms are run by players on their own PCs, through the Leyline relay '
            '(nobody sees anyone\'s home address). Each host sets their own house rules and is the GM there. '
            '<a href="/wrath/leyline">What is Leyline?</a></p>')
    return render(body, wide=True, meta=card_meta("/wrath/realms", f"Realms · {REALM_NAME}"))


LEYLINE_REPO = "https://github.com/orionopenwow/WrathUnleashed"


LEYLINE_CSS = """
:root{--ly-cyan:#5fe3ff;--ly-violet:#b48cff;--ly-ink:#e8ecff;--ly-dim:#a9b0d6;--ly-panel:rgba(14,16,40,.78);
--ly-line:rgba(120,150,255,.28);--ly-glow:0 0 18px rgba(95,227,255,.35)}
*{box-sizing:border-box}html,body{margin:0}
body.ly{min-height:100vh;color:var(--ly-ink);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#05060f url(ART_BG) center top/cover fixed no-repeat}
@media (max-width:700px){body.ly{background-attachment:scroll}}
body.ly::before,body.ly::after{content:"";position:fixed;inset:-50%;pointer-events:none;z-index:0;background-repeat:repeat}
body.ly::before{background-image:
radial-gradient(1px 1px at 20px 30px,#fff,transparent),radial-gradient(1px 1px at 120px 80px,#cfe8ff,transparent),
radial-gradient(1.5px 1.5px at 210px 160px,#fff,transparent),radial-gradient(1px 1px at 300px 40px,#bfe9ff,transparent),
radial-gradient(1px 1px at 380px 220px,#fff,transparent),radial-gradient(1.5px 1.5px at 60px 260px,#d9c8ff,transparent),
radial-gradient(1px 1px at 260px 300px,#fff,transparent),radial-gradient(1px 1px at 160px 380px,#cfe8ff,transparent);
background-size:420px 420px;opacity:.55}
body.ly::after{background-image:
radial-gradient(2px 2px at 90px 120px,#e9fbff,transparent),radial-gradient(1.5px 1.5px at 330px 60px,#e7dcff,transparent),
radial-gradient(2px 2px at 520px 340px,#fff,transparent),radial-gradient(1.5px 1.5px at 240px 470px,#bff3ff,transparent),
radial-gradient(2px 2px at 600px 180px,#fff,transparent);background-size:680px 680px;opacity:.7}
.ly-glow{position:fixed;inset:0;pointer-events:none;z-index:0;
background:radial-gradient(40% 30% at 50% 22%,rgba(140,90,255,.18),transparent 70%),radial-gradient(30% 25% at 78% 28%,rgba(60,200,255,.12),transparent 70%)}
.ly-nav,.ly-wrap{position:relative;z-index:1}
@media (prefers-reduced-motion:no-preference){
body.ly::before{animation:ly-drift 180s linear infinite,ly-twinkle 5s ease-in-out infinite alternate}
body.ly::after{animation:ly-drift 120s linear infinite reverse,ly-twinkle 7s ease-in-out infinite alternate-reverse}
.ly-glow{animation:ly-pulse 9s ease-in-out infinite}}
@keyframes ly-drift{to{transform:translate(-420px,-210px)}}
@keyframes ly-twinkle{from{opacity:.35}to{opacity:.85}}
@keyframes ly-pulse{50%{opacity:.6}}
.ly a{color:var(--ly-cyan)}
.ly-nav{position:sticky;top:0;z-index:5;display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:space-between;
padding:10px 16px;background:rgba(6,8,22,.82);backdrop-filter:blur(6px);border-bottom:1px solid var(--ly-line)}
.ly-nav .grp{display:flex;gap:6px;flex-wrap:wrap}
.ly-nav a{font:600 12px/1 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;text-decoration:none;color:var(--ly-dim);
padding:8px 11px;border:1px solid var(--ly-line);border-radius:4px;background:rgba(20,24,60,.6)}
.ly-nav a:hover,.ly-nav a:focus-visible{color:var(--ly-ink);border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.ly-nav a.hot{color:#1a1030;background:linear-gradient(180deg,#9ff0ff,var(--ly-cyan));border-color:#9ff0ff}
.ly-wrap{max-width:1040px;margin:0 auto;padding:24px 16px 56px}
.ly-hero{text-align:center;padding:12px 0 8px}
.ly-emblem{width:min(300px,70vw);height:auto;mix-blend-mode:screen;filter:drop-shadow(0 0 28px rgba(150,110,255,.55));
-webkit-mask-image:radial-gradient(closest-side,#000 74%,transparent 100%);mask-image:radial-gradient(closest-side,#000 74%,transparent 100%)}
@media (prefers-reduced-motion:no-preference){.ly-emblem{animation:ly-float 7s ease-in-out infinite}}
@keyframes ly-float{50%{transform:translateY(-6px)}}
.ly h1{font:600 clamp(56px,11vw,104px)/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.08em;text-transform:uppercase;margin:6px 0 10px;
background:linear-gradient(180deg,#bdfaff 0%,#8ff0ff 48%,#a9a6ff 78%,#c88cff 100%);-webkit-background-clip:text;background-clip:text;color:transparent;
filter:drop-shadow(0 0 6px rgba(120,225,255,.75)) drop-shadow(0 0 22px rgba(160,120,255,.45))}
.ly-lede{max-width:640px;margin:0 auto 10px;color:var(--ly-ink)}
.ly-ver{display:inline-block;font-size:12px;color:var(--ly-dim);border:1px solid var(--ly-line);border-radius:999px;padding:2px 10px}
.ly-cta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:26px auto 30px;max-width:900px}
@media (max-width:700px){.ly-cta{grid-template-columns:1fr}}
.ly-btn{position:relative;display:flex;align-items:center;justify-content:center;gap:10px;min-height:64px;padding:12px 18px;text-decoration:none;
font:600 clamp(20px,2.6vw,25px)/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--ly-ink)!important;
background:linear-gradient(180deg,rgba(40,52,110,.92),rgba(16,20,52,.95));border:1px solid rgba(140,170,255,.45);border-radius:6px;
box-shadow:inset 0 0 0 1px rgba(255,255,255,.05),0 6px 18px rgba(0,0,0,.45)}
.ly-btn:hover,.ly-btn:focus-visible{border-color:var(--ly-cyan);box-shadow:inset 0 0 0 1px rgba(255,255,255,.08),var(--ly-glow)}
.ly-btn::before{content:"";position:absolute;inset:-3px;pointer-events:none;background:
url(ART_CTL) top left/26px 22px no-repeat,url(ART_CTR) top right/26px 22px no-repeat,
url(ART_CBL) bottom left/26px 22px no-repeat,url(ART_CBR) bottom right/26px 22px no-repeat}
.ly-btn.violet{background:linear-gradient(180deg,rgba(90,52,160,.92),rgba(36,18,80,.95));border-color:rgba(190,150,255,.55)}
.ly-btn svg{width:26px;height:26px;flex:none}
.ly-panel{position:relative;background:
url(ART_CTL) top left/44px 38px no-repeat,url(ART_CTR) top right/44px 38px no-repeat,
url(ART_CBL) bottom left/44px 38px no-repeat,url(ART_CBR) bottom right/44px 38px no-repeat,var(--ly-panel);
border:1px solid var(--ly-line);border-radius:8px;padding:22px 20px;margin:18px 0;box-shadow:0 10px 30px rgba(0,0,0,.4)}
.ly-panel h2::after{content:"";display:block;width:min(300px,70%);height:18px;margin:6px auto 0;
background:url(ART_DIV) center/contain no-repeat}
.ly h2{font:600 28px/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.14em;text-transform:uppercase;text-align:center;margin:0 0 14px;color:#bff6ff;text-shadow:0 0 12px rgba(95,227,255,.45)}
.ly-table{width:100%;border-collapse:collapse;font-size:15px}
.ly-table th{font:600 11px/1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--ly-dim);text-align:left;
padding:10px;border-bottom:1px solid var(--ly-line)}
.ly-table td{padding:10px;border-bottom:1px solid rgba(120,150,255,.12)}
.ly-table tr.off td{color:var(--ly-dim)}
.ly-table .sub{display:block;font-size:12px;color:var(--ly-dim)}
.ly-on{color:#5ef0a0}.ly-off{color:var(--ly-dim)}
@media (max-width:640px){.ly-table thead{display:none}.ly-table tr{display:grid;grid-template-columns:1fr auto;gap:2px 10px;
padding:10px 0;border-bottom:1px solid rgba(120,150,255,.12)}.ly-table td{border:0;padding:0 4px}
.ly-table td.name{grid-column:1/-1}}
.ly-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
@media (max-width:860px){.ly-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:560px){.ly-grid{grid-template-columns:1fr}}
.ly-feat{background:rgba(18,22,54,.7);border:1px solid var(--ly-line);border-radius:6px;padding:16px}
.ly-feat h3{margin:0 0 6px;font:600 21px/1.15 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--ly-cyan)}
.ly-feat p{margin:0;color:var(--ly-ink)}
.ly-feat .soon{display:inline-block;margin-left:6px;font:600 10px/1 system-ui;letter-spacing:.1em;text-transform:uppercase;
color:var(--ly-violet);border:1px solid rgba(180,140,255,.5);border-radius:999px;padding:3px 7px;vertical-align:middle}
.ly-fine{color:var(--ly-dim);font-size:14px;text-align:center;margin-top:22px}
.ly-shots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
@media (max-width:640px){.ly-shots{grid-template-columns:1fr}}
.ly-shot{margin:0;background:rgba(10,12,34,.8);border:1px solid var(--ly-line);border-radius:6px;overflow:hidden}
.ly-shot img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:cover}
.ly-shot figcaption{padding:10px 12px;font-size:14px;color:var(--ly-ink)}
.ly-shot figcaption b{font:600 18px/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.08em;text-transform:uppercase;
color:var(--ly-cyan);display:block;margin-bottom:3px}
@font-face{font-family:'OW Cinzel';src:url(ART_FONT) format('woff2');font-display:swap}
@font-face{font-family:'Leyline Display';src:url(ART_LYF) format('woff2');font-display:swap}
"""


def leyline_css() -> str:
    """LEYLINE_CSS with its art filled in (the Leyline page, the armory and /wrath/modes)."""
    css = LEYLINE_CSS
    for k, f in (("ART_BG", "leyline-bg.webp"), ("ART_LYF", "leyline-display.woff2"), ("ART_FONT", "Cinzel-SemiBold.woff2"),
                 ("ART_CTL", "leyline-corner-tl.webp"), ("ART_CTR", "leyline-corner-tr.webp"), ("ART_CBL", "leyline-corner-bl.webp"),
                 ("ART_CBR", "leyline-corner-br.webp"), ("ART_DIV", "leyline-divider.webp")):
        css = css.replace(k, art_url(f))
    return css


def remember_go(user: str, query: dict) -> None:
    """A signed-in player came with ?go=<kind>:<id>: record it for their game account on the realm
    ("ovgo set", realm/custom/lua_scripts/ov_go.lua), at most 20 a minute per account. Never fails the page."""
    if modes is None or links is None:
        return
    v = (query.get("go") or [""])[0][:40]
    got = links.check_go(v) if v else None
    if not got or got[0] not in ("h", "q", "b") or not gate_limit.hit("go:" + user.upper(), 20):
        return
    modes.go_intent(ac_soap, user, links.go_value(*got), log)


def leyline_page() -> bytes:
    """/wrath/leyline: the Leyline network's own page, in its own look (the owner's emblem and nebula art,
    cyan and violet), with its features and aims in plain facts: what's live today, and what's planned (marked).
    The hero line under the title is the owner's own (from his mockup), trimmed to what's true today."""
    e = html.escape
    st = realm_status()
    rows = [(REALM_NAME, "Official · level 1 or boost to 80", "PvE", _nonneg(st.get("players")), _nonneg(st.get("bots")),
             bool(st.get("online")), "/wrath")]
    realms, _ok = community_realms()
    for r in realms[:20]:
        rows.append((r["name"], RULESET_LABELS[r["ruleset"]], r["type"], r["players"], r["bots"], r["live"],
                     f'{JOIN_BASE}/join/{r["id"]}'))
    trs = []
    for name, sub, typ, players, bots, live, link in rows:
        who = "–" if players is None else (f"{players}" + (f" <span class='sub'>+{bots} bots</span>" if bots else ""))
        trs.append(f'<tr class="{"" if live else "off"}"><td class="name"><a href="{e(link)}">{e(name)}</a>'
                   f'<span class="sub">{e(sub)}</span></td><td>{e(typ)}</td><td>{who}</td>'
                   f'<td class="{"ly-on" if live else "ly-off"}">{"● online" if live else "offline"}</td></tr>')
    icon_play = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="10"/><path d="M10 8l6 4-6 4z" fill="currentColor"/></svg>'
    icon_rocket = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 19c1-3 3-5 5-6M14 4c3 0 6 3 6 6l-7 7-6-6z"/><circle cx="15" cy="9" r="1.6"/></svg>'
    icon_portal = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M12 5a7 7 0 1 0 7 7"/><path d="M12 8a4 4 0 1 0 4 4"/></svg>'

    def shot(name, title, text):
        return (f'<figure class="ly-shot"><img src="{art_url("leyline-shot-" + name + ".webp")}" alt="{e(title)}" '
                f'loading="lazy" width="1280" height="720"><figcaption><b>{e(title)}</b>{e(text)}</figcaption></figure>')

    def feat(title, text, soon=False):
        return (f'<div class="ly-feat"><h3>{e(title)}{"<span class=soon>planned</span>" if soon else ""}</h3>'
                f'<p>{text}</p></div>')
    css = leyline_css()
    body = (
        '<nav class="ly-nav" aria-label="Leyline"><div class="grp">'
        '<a href="/wrath/leyline">Hub</a><a href="/wrath/modes">Modes</a><a href="/wrath/realms">Realms</a>'
        + ('<a href="/wrath/armory">Armory</a>' if armory is not None else '') +
        '<a href="/wrath/mods">Mods</a>'
        f'<a href="{e(LEYLINE_REPO)}/blob/main/hosting/INSTALL-OPERATE.md" rel="noopener noreferrer">Server</a></div>'
        '<div class="grp"><a href="/login?next=%2Fwrath">Sign in</a><a class="hot" href="/wrath">Play now</a></div></nav>'
        '<div class="ly-wrap"><header class="ly-hero">'
        f'<img class="ly-emblem" src="{art_url("leyline-emblem.webp")}" alt="" width="300" height="248">'
        '<h1>Leyline</h1>'
        '<p class="ly-lede">An open-source, community-built MMO project. Play in your browser or a client, '
        'build and share mods, and host your own realm.</p>'
        '<span class="ly-ver">Alpha</span></header>'
        '<div class="ly-cta">'
        f'<a class="ly-btn" href="/wrath">{icon_play}Play now</a>'
        f'<a class="ly-btn" href="/wrath#desktop">{icon_rocket}Client launcher</a>'
        f'<a class="ly-btn violet" href="{e(LEYLINE_REPO)}/blob/main/hosting/INSTALL-OPERATE.md" rel="noopener noreferrer">{icon_portal}Host realm</a>'
        '</div>'
        '<section class="ly-panel" aria-labelledby="ly-realms"><h2 id="ly-realms">Realm list</h2>'
        '<table class="ly-table"><thead><tr><th>Realm</th><th>Type</th><th>Players</th><th>Status</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
        '<p class="ly-fine">Community realms run on their hosts\' own PCs and join through the Leyline relay. '
        '<a href="/wrath/realms">All realms and house rules</a></p></section>'
        '<section class="ly-panel" aria-labelledby="ly-shots"><h2 id="ly-shots">See it running</h2><div class="ly-shots">'
        + shot("dalaran", "Dalaran hangout", "The flagship realm's meeting place, streamed into a browser tab.")
        + shot("start", "Your choice at the start", "Begin at level 1, or take a boost to 80 with gear, professions and a trip to Dalaran.")
        + shot("city", "Play with friends", "Group up, duel, and run dungeons where labelled bots fill the empty places.")
        + shot("durotar", "Every bar, ready", "A clean modern interface: every action bar on with common keys, sized to your screen.")
        + '</div><p class="ly-fine">Screenshots from the live browser client.</p></section>'
        '<section class="ly-panel" aria-labelledby="ly-what"><h2 id="ly-what">What Leyline does</h2><div class="ly-grid">'
        + feat("Play in the browser", "No install: sign in with a Hero Key and play the flagship realm, WrathUnleashed. "
               "Dalaran hangout, level 1 or a boost to 80, and a Dungeon Finder where labelled bots fill the group.")
        + feat("Host your own realm", "Run a realm on your own PC with the host kit: your own GM login, house rules and "
               "world preset. Private by invite link, or public on the realm list.")
        + feat("A relay that hides you", "Players reach your realm through the Leyline relay, so your home address stays "
               "hidden and you open no ports.")
        + feat("Mods and addons", "Browse the <a href=\"/wrath/mods\">Workshop</a>. In the game, Esc &rarr; Mods &amp; Workshop "
               "sets your UI size and turns addons on and off. Mods use one open format that anyone can publish to.")
        + feat("Open source", "Every line is on GitHub, and every project it builds on is credited.")
        + feat("Fair by design", "No shop and nothing to buy. Bots are always labelled and counted apart from players.")
        + feat("Companions", "Short a group? Type .recruit tank, healer or dps for labelled bot party members, "
               "or .buddy for a levelling partner who keeps your level.")
        + feat("Realms in the game", "Esc &rarr; Mods &amp; Workshop &rarr; Leyline realms lists every realm on the network, "
               "with a link to share.")
        + feat("Links that open the game", "Share a realm, a hangout or a dungeon queue as one short link with a preview card.")
        + '</div></section>'
        '<section class="ly-panel" aria-labelledby="ly-aims"><h2 id="ly-aims">Where it\'s going</h2><div class="ly-grid">'
        + feat("Host from a browser tab", "Start a realm from a tab and share a link: no install, no server bill.", True)
        + feat("One-click mods", "Browse the Workshop and install mods and modes into a realm in one click.", True)
        + feat("Hop between realms", "Join any realm from the in-game list, with friends, settings and addons that travel with you.", True)
        + feat("A peer-to-peer network", "Realms, hangouts and mods shared between players, so the network grows with them.", True)
        + feat("Try it here", "A Goldshire Inn demo on this page, with no sign-up.", True)
        + feat("Builders' tools", "Build in the world with your own models, and share it on the Workshop.", True)
        + '</div></section>'
        '<p class="ly-fine">The full world needs your own 3.3.5a game files; the browser streams only small areas '
        '(Dalaran, the starting zones, dungeons). '
        f'<a href="{e(LEYLINE_REPO)}" rel="noopener noreferrer">Source code</a></p></div>')
    meta = card_meta("/wrath/leyline", "Leyline · an open-source, community-built MMO project")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>Leyline</title>{meta}<style>{css}</style></head><body class="ly"><div class="ly-glow"></div>{body}</body></html>').encode("utf-8")


def leyline_css() -> str:
    """LEYLINE_CSS with its art placeholders pointing at /wrath/art/."""
    css = LEYLINE_CSS
    for k, f in (("ART_BG", "leyline-bg.webp"), ("ART_LYF", "leyline-display.woff2"), ("ART_FONT", "Cinzel-SemiBold.woff2"),
                 ("ART_CTL", "leyline-corner-tl.webp"), ("ART_CTR", "leyline-corner-tr.webp"), ("ART_CBL", "leyline-corner-bl.webp"),
                 ("ART_CBR", "leyline-corner-br.webp"), ("ART_DIV", "leyline-divider.webp")):
        css = css.replace(k, art_url(f))
    return css


workshop = None
if workshop_mod is not None:
    try:
        workshop = workshop_mod.Workshop(os.environ.get("WU_MODS_DIR", "/app/mods"), leyline_css, card_meta, REALM_NAME)
    except Exception:   # the rest of the portal must still start
        workshop = None


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


page_limit = _Window(60)
browse_limit = _Window(60)   # public read-only pages (Leyline, realms, modes, armory, mods, share links): 600 a minute
gate_limit = _Window(60)
armory_limit = _Window(60)   # armory searches: 30 a minute per address, on top of page_limit


_health = {"at": 0.0, "ok": False, "kind": ""}
_health_lock = threading.Lock()


def health() -> tuple[bool, str]:
    """SOAP check, at most once per 10 seconds (the page is public)."""
    with _health_lock:
        if time.monotonic() - _health["at"] > 10:
            try:
                ac_soap("server info")
                _health.update(ok=True, kind="")
            except SoapError as e:
                _health.update(ok=False, kind=e.kind)
            _health["at"] = time.monotonic()
        return _health["ok"], _health["kind"]


# ----------------------------------------------------------------------------------------------
# Public status (GET /wrath/status.json)
# ----------------------------------------------------------------------------------------------
#
# Read from AzerothCore's "server info" (cs_server.cpp, HandleServerInfoCommand). Its lines, from
# acore_string (11032, 11033, 11023, 13):
#   Connected players: {} (peak: {}).
#   Connected players: {} (peak: {}). Queue: {}.
#   Characters in world: {} (peak: {}, lifetime: {}).
#   Server uptime: {}            ({} = "1 day(s) 2 hour(s) 3 minute(s) 4 second(s)", Util.cpp)
#
# Real players and bots:
#   "Connected players" is WorldSessionMgr::GetActiveSessionCount(): sessions in the session
#   manager. mod-playerbots' bots get their own WorldSession objects that are never added there
#   (the module itself uses that count to tell whether a real player is on), so this is real
#   players only, including anyone still on the character screen.
#   "Characters in world" is WorldSessionMgr::GetPlayerCount(), which every Player object adds to
#   (Player.cpp constructor), bots included.
#   So bots = characters - connected, floored at 0. It is an estimate: it reads low by the number
#   of real players sitting on the character screen. An exact count needs the characters DB
#   (see the Beacons report); this service has no DB connection on purpose.

STATUS_TTL = 30
STATUS_BUILD = "3.3.5a"

_RE_CONNECTED = re.compile(r"Connected players:\s*(\d+)", re.I)
# older TrinityCore-style wording, in case the fork in use still has it
_RE_ONLINE_OLD = re.compile(r"(?:Players online|Online players):\s*(\d+)", re.I)
_RE_CHARACTERS = re.compile(r"Characters in world:\s*(\d+)", re.I)
_RE_QUEUE = re.compile(r"Queue:\s*(\d+)", re.I)
_RE_UPTIME_LINE = re.compile(r"uptime:\s*([^\r\n]*)", re.I)
_RE_UPTIME_PART = re.compile(r"(\d+)\s*(day|hour|minute|second|d|h|m|s)", re.I)
_UNIT_S = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_server_info(text: str) -> dict:
    """The numbers in a "server info" reply. Anything not found is None."""
    out: dict = {"players": None, "bots": None, "queue": None, "uptime_s": None}
    m = _RE_CONNECTED.search(text) or _RE_ONLINE_OLD.search(text)
    if m:
        out["players"] = int(m.group(1))
    m = _RE_QUEUE.search(text)
    if m:
        out["queue"] = int(m.group(1))
    m = _RE_CHARACTERS.search(text)
    if m and out["players"] is not None:
        out["bots"] = max(0, int(m.group(1)) - out["players"])
    m = _RE_UPTIME_LINE.search(text)
    if m:
        parts = _RE_UPTIME_PART.findall(m.group(1))
        if parts:
            out["uptime_s"] = sum(int(n) * _UNIT_S[u[0].lower()] for n, u in parts)
    return out


_status: dict = {"at": -1e9, "body": b""}
_status_lock = threading.Lock()      # guards _status
_status_refresh = threading.Lock()   # held by the one request that is asking SOAP


def _status_now() -> bytes:
    doc = {"realm": REALM_NAME, "online": False, "players": None, "bots": None, "queue": None,
           "uptime_s": None, "build": STATUS_BUILD, "bots_method": "characters_in_world_minus_connected",
           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        doc.update(parse_server_info(ac_soap("server info")))
        doc["online"] = True
    except SoapError as e:
        # "auth"/"fault": the worldserver answered, so it is up, but we learned no numbers
        doc["online"] = e.kind != "down"
        if e.kind != "down":
            log.warning("status: soap %s", e.kind)
    return (json.dumps(doc, separators=(",", ":")) + "\n").encode("utf-8")


def status_json() -> bytes:
    """The cached status document; SOAP is asked at most once per STATUS_TTL seconds."""
    with _status_lock:
        fresh = time.monotonic() - _status["at"] < STATUS_TTL
        body = _status["body"]
    if fresh and body:
        return body
    # One request refreshes; the others keep serving the previous answer meanwhile.
    if not _status_refresh.acquire(blocking=not body):
        return body
    try:
        with _status_lock:  # someone may have refreshed while we waited
            if time.monotonic() - _status["at"] < STATUS_TTL and _status["body"]:
                return _status["body"]
        body = _status_now()
        with _status_lock:
            _status.update(at=time.monotonic(), body=body)
        return body
    finally:
        _status_refresh.release()


class PageHandler(BaseHTTPRequestHandler):
    server_version = "wrath-portal"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def ip(self) -> str:
        # Caddy sets X-Forwarded-For to the real address (header_up in the site's Caddyfile).
        return (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0])[:64]

    def send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8", nonce: str = "",
             public: bool = False, same_origin: bool = False, connect: bool = False,
             headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if same_origin:  # /__env.js: never readable from another site's page
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if public:  # the status document: anyone may read it, from any site
            self.send_header("Cache-Control", f"public, max-age={STATUS_TTL}")
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        script = f"'nonce-{nonce}'" if nonce else "'none'"
        self.send_header("Content-Security-Policy",
                         f"default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; "
                         f"script-src {script}; "
                         f"frame-src https://{STREAM_HOST}; "
                         + ("connect-src 'self'; " if connect else "") +
                         "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def art(self, name: str) -> None:
        """GET /wrath/art/<name>: the site art and theme, from the allow-list only, cached for a week.
        Readable from any site (fonts need CORS; it is our own art, nothing private)."""
        body = art_bytes(name)
        if body is None:
            self.send(404, b"not found\n", "text/plain")
            return
        self.send_response(200)
        self.send_header("Content-Type", ART_TYPES[name])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", f"public, max-age={ART_MAX_AGE}")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, url: str, cookie: str = "") -> None:
        self.send_response(302)
        self.send_header("Location", url)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def signed_in_game_login(self, ip: str):
        """(status page bytes or None, user, password, display) for the signed-in player."""
        cookie = self.headers.get("Cookie", "")
        ua = self.headers.get("User-Agent", "")
        if "wr_session=" not in cookie:
            return (200, signed_out_page()), "", "", ""
        status, me = portal_get("/api/me", cookie, ip, ua)
        if status in (401, 403) or 300 <= status < 400:
            return (200, signed_out_page()), "", "", ""
        if status != 200 or not me:
            log.warning("api/me answered %s", status)
            return (503, error_page("The website isn't answering right now. Please try again shortly.")), "", "", ""
        status, play = portal_get("/api/play", cookie, ip, ua)
        user, password = str(play.get("user", "")), str(play.get("pass", ""))
        if status != 200 or not user or not password:
            log.warning("api/play answered %s", status)
            return (503, error_page("Your game account isn't ready yet. Please try again in a minute.")), "", "", ""
        display = str(me.get("display_name") or me.get("username") or user)
        return None, user, password, display

    def own_play(self, query: dict | None = None) -> None:
        """GET /wrath/play?mode=own: the browser client with the player's own game files."""
        if not ownfiles_on():
            self.send(404, error_page("Playing with your own game files in the browser isn't set up here yet."))
            return
        ip = self.ip()
        if not gate_limit.hit("play:" + ip, 30):
            self.send(429, busy_page())
            return
        page, user, password, _ = self.signed_in_game_login(ip)
        if page:
            self.send(*page)
            return
        try:
            ensure_account(user, password)
        except SoapError as e:
            log.error("ensure %s failed: %s %s", user.upper(), e.kind, e.detail[:160])
            self.send(503, error_page("The Wrath realm isn't answering right now. Please try again shortly."))
            return
        # Own files = the whole world: no stream session of this player stays open, and an earlier
        # stream mark is cleared. With streaming off the switch already released every mark (and
        # ov_slices.lua may not even be loaded), so a failed clear only matters while it is on.
        remember_go(user, query or {})
        sessions.end_user(user)
        try:
            realm_clear(user)
        except SoapError as e:
            if stream_on():
                log.error("own: clear %s failed: %s %s", user.upper(), e.kind, e.detail[:160])
                self.send(503, error_page("The realm isn't answering right now. Please try again shortly."))
                return
        code = sessions.create(user, password, OWN, 0, mode=OWN)
        log.info("own-files session for %s", user.upper())
        self.redirect(f"https://{STREAM_HOST}/__gate?code={urllib.parse.quote(code)}")

    def stream_play(self, query: dict) -> None:
        """GET /wrath/play?mini=<slug> on play.openvanilla.app (?mode=own: own_play)."""
        if (query.get("mode") or [""])[0] == OWN:
            self.own_play(query)
            return
        if not stream_on():
            self.send(200, stream_off_page())
            return
        ip = self.ip()
        if not gate_limit.hit("play:" + ip, 30):
            self.send(429, busy_page())
            return
        slug = (query.get("mini") or ["mini"])[0]
        info = slice_info(slug)
        if not info:
            self.send(404, error_page("That part of the game isn't streamed here."))
            return
        page, user, password, _ = self.signed_in_game_login(ip)
        if page:
            self.send(*page)
            return
        try:
            ensure_account(user, password)
            realm_mark(user, slug, info["tier"], SESSION_TTL)
        except SoapError as e:
            log.error("stream mark %s failed: %s %s", user.upper(), e.kind, e.detail[:160])
            self.send(503, error_page("Streaming isn't ready on the realm right now. Please try again shortly."))
            return
        remember_go(user, query)
        code = sessions.create(user, password, slug, info["tier"])
        log.info("stream session for %s (%s, tier %d)", user.upper(), slug, info["tier"])
        self.redirect(f"https://{STREAM_HOST}/__gate?code={urllib.parse.quote(code)}{go_param(query)}")

    def stream_end(self) -> None:
        """GET /wrath/play/end: end the player's sessions and clear the realm mark."""
        ip = self.ip()
        if not gate_limit.hit("end:" + ip, 30):
            self.send(429, busy_page())
            return
        page, user, _, _ = self.signed_in_game_login(ip)
        if page:
            self.send(*page)
            return
        sessions.end_user(user)
        try:
            realm_clear(user)
        except SoapError as e:
            log.error("stream clear %s failed: %s %s", user.upper(), e.kind, e.detail[:160])
            self.send(503, error_page("The realm isn't answering right now. Your pass ends by itself within 12 hours."))
            return
        self.send(200, stream_ended_page())

    def stream_gate(self, query: dict) -> None:
        """GET /__gate?code= on the stream site."""
        if not gate_limit.hit("gate:" + self.ip(), 60):
            self.send(429, busy_page())
            return
        code = (query.get("code") or [""])[0][:64]
        sid = sessions.redeem(code) if code else None
        if not sid:
            self.redirect(f"https://{PUBLIC_HOST}/wrath")
            return
        sess = sessions.get(sid) or {}
        land = "/?ownfiles=1" if sess.get("mode") == OWN else ("/?demo=1" if sess.get("mode") == "demo" else "/")
        go = go_param(query)
        if go:
            land += ("&" if "?" in land else "?") + go[1:]
        self.redirect(land, f"wu_play={sid}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; Secure; SameSite=Lax")

    def stream_session(self) -> dict | None:
        sid = cookie_value(self.headers.get("Cookie", ""), "wu_play")
        return sessions.get(sid) if sid and len(sid) < 128 else None

    def stream_auth(self) -> None:
        """GET /__auth: Caddy forward_auth. The original request is in X-Forwarded-Uri."""
        uri = self.headers.get("X-Forwarded-Uri", "/")
        game = uri.startswith("/data") or uri.startswith("/ws")
        sess = self.stream_session()
        if sess and sess.get("mode") == OWN:
            # Own game files: the page, its scripts and the realm connection (/ws), never the
            # server's game data. Streaming on or off does not matter.
            if uri.startswith("/data"):
                self.send(403, b"own game files: /data is not served\n", "text/plain")
            else:
                self.send(200, b"", "text/plain")
            return
        if not stream_on():
            if game:
                self.send(403, b"streaming is off\n", "text/plain")
            else:
                self.redirect(f"https://{PUBLIC_HOST}/wrath/play?mini=mini")
            return
        if sess:
            self.send(200, b"", "text/plain")
            return
        self.redirect(f"https://{PUBLIC_HOST}/wrath")

    def stream_env(self) -> None:
        """GET /__env.js on the stream site: the session's game login for the client."""
        if not gate_limit.hit("env:" + self.ip(), 90):
            self.send(429, b"/* too many requests */\n", "application/javascript")
            return
        sess = self.stream_session()
        if sess and sess.get("mode") != OWN and not stream_on():
            sess = None
        if not sess:
            body = (f"var g=null;try{{g=new URLSearchParams(location.search).get('go')}}catch(e){{}}"
                    f"location.replace({json.dumps('https://' + PUBLIC_HOST + '/wrath')}+(g&&g.length<41?'?go='+encodeURIComponent(g):''));\n").encode()
            self.send(401, body, "application/javascript; charset=utf-8", same_origin=True)
            return
        self.send(200, env_js(sess), "application/javascript; charset=utf-8", same_origin=True)

    def demo(self, path: str) -> None:
        """GET /wrath?demo=1 (a guest pass) and /wrath/demo (the "Try it" section): stream/demo.py."""
        ip = self.ip()
        if not page_limit.hit(ip, 120) or not gate_limit.hit("demo:" + ip, 20):
            self.send(429, busy_page())
            return
        if not guest:
            self.send(404, error_page("Guest passes aren't set up here."))
            return
        if path == "/wrath/demo":
            self.send(200, guest.preview())
            return
        if self.command == "HEAD":
            self.send(200, b"")
            return
        kind, *rest = guest.start(ip)
        if kind == "redirect":
            self.redirect(rest[0])
        else:
            self.send(rest[0], rest[1])

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_OPTIONS(self):  # noqa: N802
        # A plain GET needs no preflight; answer one anyway so a caller adding headers still works.
        if urllib.parse.urlsplit(self.path).path == "/wrath/status.json":
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Accept")
            self.send_header("Access-Control-Max-Age", "86400")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send(405, b"method not allowed\n", "text/plain")

    def do_GET(self):  # noqa: N802
        split = urllib.parse.urlsplit(self.path)
        path = split.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(split.query)
        if path == "/__auth":
            self.stream_auth()
            return
        if path == "/__gate":
            self.stream_gate(query)
            return
        if path == "/__env.js":
            self.stream_env()
            return
        if path == "/wrath/play":
            self.stream_play(query)
            return
        if path == "/wrath/play/end":
            self.stream_end()
            return
        if path == "/wrath/status.json":
            self.send(200, status_json(), "application/json; charset=utf-8", public=True)
            return
        if path == "/wrath/healthz":
            ok, kind = health()
            self.send(200 if ok else 503, b"ok\n" if ok else f"soap {kind}\n".encode(), "text/plain")
            return
        if path.startswith("/wrath/art/"):
            self.art(urllib.parse.unquote(path[len("/wrath/art/"):]))
            return
        if path == "/wrath/leyline":
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            self.send(200, leyline_page())
            return
        if armory is not None and armory.match(path):   # the web armory (stream/armory.py): files only, no database
            ip = self.ip()
            if not browse_limit.hit(ip, 600) or (armory.search_query(path, query) and not armory_limit.hit(ip, 30)):
                self.send(429, busy_page(back=path))
                return
            status, body = armory.page(path, query, leyline_css(), card_meta, REALM_NAME, PUBLIC_HOST)
            self.send(status, body)
            return
        if links is not None and links.match(path):   # share links (stream/links.py), same limit as /wrath/leyline
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            self.send(200, links.share_page(path, card_meta, render, REALM_NAME, community_realms,
                                            who=armory.card_line if armory is not None else None,
                                            mods=workshop.mod if workshop else None))
            return
        if path == "/wrath/modes" and modes is not None:
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            self.send(200, modes.page(leyline_css(), art_url, art_present, card_meta, REALM_NAME))
            return
        if workshop is not None and workshop_mod.match(path):   # the mods Workshop (stream/workshop.py)
            dl = "/download" in path
            if not browse_limit.hit(self.ip() + ("|dl" if dl else ""), 30 if dl else 600):
                self.send(429, busy_page(back=path))
                return
            status, body, ctype, extra = workshop.serve(path, query)
            self.send(status, body, ctype, headers=extra)
            return
        if path == "/wrath/realms":
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            self.send(200, realms_page())
            return
        if path == "/wrath/demo" or (path == "/wrath" and (query.get("demo") or [""])[0] == "1"):
            self.demo(path)
            return
        if path not in ("/wrath", "/wrath/account"):
            self.send(404, b"not found\n", "text/plain")
            return
        # /wrath is "Play now": signed in, straight into the game (the streamed realm in the browser).
        # /wrath/account is the page with the game login and the other ways to play.
        straight_in = path == "/wrath" and stream_on() and slice_info("mini") and query.get("list") is None
        ip = self.ip()
        if not page_limit.hit(ip, 120):
            self.send(429, busy_page())
            return
        cookie = self.headers.get("Cookie", "")
        ua = self.headers.get("User-Agent", "")
        if "wr_session=" not in cookie:
            nonce = secrets.token_urlsafe(16)   # a saved Hero Key signs in by itself, else the sign-in page
            self.send(200, auto_signin_page(nonce), nonce=nonce, connect=True)
            return
        status, me = portal_get("/api/me", cookie, ip, ua)
        if status in (401, 403) or 300 <= status < 400:
            return self.redirect(SIGN_IN_URL)
        if status != 200 or not me:
            log.warning("api/me answered %s", status)
            self.send(503, error_page("The website isn't answering right now. Please try again shortly."))
            return
        status, play = portal_get("/api/play", cookie, ip, ua)
        user, password = str(play.get("user", "")), str(play.get("pass", ""))
        if status != 200 or not user or not password:
            log.warning("api/play answered %s", status)
            self.send(503, error_page("Your game account isn't ready yet. Please try again in a minute."))
            return
        try:
            ensure_account(user, password)
        except SoapError as e:
            log.error("ensure %s failed: %s %s", user.upper(), e.kind, e.detail[:160])
            self.send(503, error_page("The Wrath realm isn't answering right now. Please try again shortly."))
            return
        remember_go(user, query)
        if straight_in:
            return self.redirect("/wrath/play?mini=mini" + go_param(query))
        nonce = secrets.token_urlsafe(16)
        display = str(me.get("display_name") or me.get("username") or user)
        self.send(200, account_page(display, user, password, nonce), nonce=nonce)


# ----------------------------------------------------------------------------------------------
# SOAP bridge for the realm service
# ----------------------------------------------------------------------------------------------

def soap_reply(ok: bool, text: str) -> bytes:
    inner = (f"<ns1:executeCommandResponse><result>{xml_escape(text)}</result></ns1:executeCommandResponse>"
             if ok else
             f"<SOAP-ENV:Fault><faultcode>SOAP-ENV:Client</faultcode><faultstring>{xml_escape(text)}</faultstring></SOAP-ENV:Fault>")
    return ('<?xml version="1.0" encoding="UTF-8"?><SOAP-ENV:Envelope '
            'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:MaNGOS">'
            f"<SOAP-ENV:Body>{inner}</SOAP-ENV:Body></SOAP-ENV:Envelope>").encode("utf-8")


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "wrath-bridge"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        try:
            allowed = set(socket.gethostbyname_ex(BRIDGE_HOST)[2])
        except OSError:
            allowed = set()
        if self.client_address[0] not in allowed:
            log.warning("bridge refused a caller that is not %s", BRIDGE_HOST)
            self.reply(403, soap_reply(False, "not allowed"))
            return
        auth = self.headers.get("Authorization", "")
        user = ""
        if auth.startswith("Basic "):
            try:
                user = base64.b64decode(auth[6:]).decode("utf-8", "replace").split(":", 1)[0].upper()
            except ValueError:
                user = ""
        if user not in BRIDGE_USERS:
            self.reply(401, soap_reply(False, "not allowed"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > 65536:
            self.reply(400, soap_reply(False, "bad request"))
            return
        command = _tag_text(self.rfile.read(length), "command")
        verb = " ".join(command.split()[:2]).lower()
        if not command.lower().startswith(BRIDGE_ALLOW):
            log.warning("bridge refused: %s", verb)
            self.reply(500, soap_reply(False, "That command is not available on this realm."))
            return
        try:
            text = ac_soap(command)
            log.info("bridge ran: %s", verb)
            self.reply(200, soap_reply(True, text))
        except SoapError as e:
            log.info("bridge %s: %s", verb, e.kind)
            # "already exist" passes through, so the realm service's own fallbacks still work
            self.reply(500 if e.kind == "fault" else 503, soap_reply(False, e.detail or e.kind))


def _load_guest():
    """The guest pass (stream/demo.py, beside this file; optional: without it the routes answer 404)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.py")
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location("wu_demo", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        css = lambda: LEYLINE_CSS.replace("ART_BG", art_url("leyline-bg.webp")).replace("ART_FONT", art_url("Cinzel-SemiBold.woff2"))
        return mod.Demo(mod.SoapBackend(ac_soap, SoapError), sessions, slice_info, stream_on, lambda: STREAM_HOST, css)
    except Exception:  # noqa: BLE001: the rest of the page must still start
        log.exception("demo.py did not load: guest passes are off")
        return None


guest = _load_guest()


def main() -> int:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not SOAP_USER or not SOAP_PASS:
        log.error("SOAP_USER and SOAP_PASS must be set (/srv/wrath/portal.env)")
        return 2
    bridge = ThreadingHTTPServer(("0.0.0.0", BRIDGE_PORT), BridgeHandler)
    bridge.daemon_threads = True
    threading.Thread(target=bridge.serve_forever, daemon=True).start()
    page = ThreadingHTTPServer(("0.0.0.0", PAGE_PORT), PageHandler)
    page.daemon_threads = True
    log.info("page :%d, bridge :%d, ac soap %s, portal %s", PAGE_PORT, BRIDGE_PORT, AC_SOAP_URL, PORTAL_URL)
    if guest:
        guest.start_thread()
    try:
        page.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
