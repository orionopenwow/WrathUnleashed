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

Passwords are never logged.
"""

from __future__ import annotations

import base64
import collections
import hashlib
import html
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

STYLE = """
body{margin:0;min-height:100vh;background:#0d0f16;color:#e9e4d4;font:16px/1.5 system-ui,sans-serif;display:flex;align-items:center;justify-content:center}
main{width:min(30rem,100% - 32px);background:#161a26;border:1px solid #3a3322;border-radius:10px;padding:24px;box-sizing:border-box}
h1{margin:0 0 4px;font-size:1.6rem;color:#f2c96b}.sub{margin:0 0 20px;color:#a59f8f}
a.btn,button{display:inline-block;background:#f2c96b;color:#1a1408;border:0;border-radius:6px;padding:10px 16px;font:600 1rem system-ui,sans-serif;text-decoration:none;cursor:pointer}
button.ghost{background:#2a2f3e;color:#e9e4d4;padding:6px 10px;font-size:.9rem}
.row{display:flex;gap:8px;align-items:center;margin:6px 0 14px}
.field{flex:1;background:#0d0f16;border:1px solid #3a3322;border-radius:6px;padding:8px 10px;font:600 1.05rem ui-monospace,monospace;letter-spacing:.04em;min-width:0;overflow-wrap:anywhere}
label{color:#a59f8f;font-size:.85rem}ol{padding-left:1.2rem}li{margin:4px 0}.fine{color:#8a8473;font-size:.85rem}.err{color:#ff8f8f}
a{color:#f2c96b;text-underline-offset:2px}a:visited{color:#d9b25c}a:hover{color:#ffe0a0}
.fine a{color:#b8a57a}.fine a:hover{color:#f2c96b}
a.btn:hover,button:hover{filter:brightness(1.08)}a.btn:focus-visible,button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid #f2c96b;outline-offset:2px}
code{background:#0d0f16;border:1px solid #2a2f3e;border-radius:4px;padding:1px 5px;font-size:.9em}
@media (max-width:480px){body{align-items:flex-start;padding:16px 0}main{padding:18px}}
"""


def render(body: str, nonce: str = "", script: str = "") -> bytes:
    s = f'<script nonce="{nonce}">{script}</script>' if script else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(REALM_NAME)}</title><style>{STYLE}</style></head>'
            f'<body><main>{body}</main>{s}</body></html>').encode("utf-8")


def signed_out_page() -> bytes:
    return render(
        f'<h1>{html.escape(REALM_NAME)}</h1><p class="sub">Wrath of the Lich King 3.3.5a</p>'
        '<p><a class="btn" href="/login?next=%2Fwrath">Sign in with Google or your Hero Key</a></p>'
        '<p class="fine">Already played on Open Vanilla? Use the same sign-in. Your Wrath login appears here.</p>')


def stream_off_page() -> bytes:
    return render(
        f'<h1>{html.escape(REALM_NAME)}</h1>'
        '<p>Streaming is off right now — play with your own game files.</p>'
        '<p><a class="btn" href="/wrath">Get your game login</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>')


def stream_ended_page() -> bytes:
    return render(
        f'<h1>{html.escape(REALM_NAME)}</h1>'
        '<p>Your browser pass has ended. Your account can go anywhere again with your own game files.</p>'
        '<p><a class="btn" href="/wrath/account">Back</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>')


def busy_page(wait: int = 15) -> bytes:
    """A 429: the page tries again by itself (a meta refresh, no script) instead of leaving a dead end.
    Limits are per address, and a household or a cafe shares one, so the page stays calm about it."""
    body = (f'<h1>{html.escape(REALM_NAME)}</h1><p class="sub">Lots of sign-ins from your network right now.</p>'
            f'<p>Trying again in {int(wait)} seconds...</p><p><a class="btn" href="/wrath">Try now</a></p>')
    page = render(body).decode("utf-8")
    return page.replace("<head>", f'<head><meta http-equiv="refresh" content="{int(wait)};url=/wrath">', 1).encode("utf-8")


def error_page(msg: str) -> bytes:
    return render(f'<h1>{html.escape(REALM_NAME)}</h1><p class="err">{html.escape(msg)}</p>'
                  '<p><a class="btn" href="/wrath">Try again</a></p>')


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
        f'<h1>{html.escape(REALM_NAME)}</h1><p class="sub">Signing you in…</p>'
        f'<p class="fine"><a href="{SIGN_IN_URL}">Sign in another way</a></p>',
        nonce, AUTO_SIGNIN_JS)

REALM_CSS = """
.realm{border:1px solid #3a3322;border-radius:8px;padding:14px 16px;margin:12px 0;background:#121520}
.realm h2{margin:0;font-size:1.25rem;color:#f2c96b}.tags{margin:4px 0 8px;font-size:.8rem;color:#a59f8f}
.tag{display:inline-block;border:1px solid #3a3322;border-radius:10px;padding:1px 8px;margin-right:4px}
.live{color:#7fd67f}.btn.off{background:#2a2f3e;color:#8a8473;cursor:default}
details{margin-top:8px}summary{cursor:pointer;color:#a59f8f;font-size:.9rem}summary:hover{color:#e9e4d4}
details[open] summary{margin-bottom:10px}
.top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.eyebrow{font-size:.75rem;letter-spacing:.12em;text-transform:uppercase;color:#a59f8f}
.keylink{font-size:.85rem}
.realm p{margin:8px 0}.realm .btn{margin-top:2px}
.realm:first-of-type{border-color:#5a4a26;box-shadow:0 0 0 1px rgba(242,201,107,.08),0 8px 24px rgba(0,0,0,.25)}
.end{margin:10px 0 0}.foot{margin:18px 0 0;padding-top:14px;border-top:1px solid #23283a}
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
    dalaran_btn = ('<a class="btn" href="/wrath/play?mini=mini">Play now</a>' if streamed
                   else '<span class="btn off">Opening soon</span>')
    pkg = (f'<li><a href="{html.escape(PACKAGE_URL)}">Download the player package</a> and unzip it.</li>'
           if PACKAGE_URL else '<li>Unzip the player package you were sent.</li>')
    dots = "\u2022" * len(password)
    body = (
        f'<style>{REALM_CSS}</style>'
        f'<div class="top"><span class="eyebrow">{html.escape(REALM_NAME)}</span>'
        '<a class="keylink" href="/account/key">Your Hero Key</a></div>'
        f'<h1>Choose a realm</h1><p class="sub">Signed in as {html.escape(display)}</p>'
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
        '<p>The full game, on the same realm and with the same characters. Uses your own World of Warcraft 3.3.5a '
        'game files, read on your computer and never uploaded.</p>'
        + ('<p><a class="btn" href="/wrath/play?mode=own">Play in the browser with my game folder</a></p>'
           if ownfiles_on() else '')
        + '<details><summary>Play with the desktop client or the player package</summary>'
        '<label>Account</label><div class="row">'
        f'<div class="field" id="acct">{html.escape(user)}</div>'
        '<button class="ghost" data-copy="acct" type="button">Copy</button></div>'
        '<label>Password</label><div class="row">'
        f'<div class="field" id="pw" data-v="{html.escape(password)}">{dots}</div>'
        '<button class="ghost" id="show" type="button">Show</button>'
        '<button class="ghost" data-copy="pw" type="button">Copy</button></div>'
        f'<ol>{pkg}<li>Run <b>Play WrathUnleashed.bat</b> and pick your own WoW 3.3.5a folder, '
        f'or set <code>realmlist {html.escape(PUBLIC_HOST)}</code> in your own client.</li>'
        '<li>Log in with the account and password above.</li></ol>'
        '<p class="fine">This login is yours alone. Sign in here again any time to see it.</p></details></div>'
        f'<p class="fine foot">No game files? Dalaran needs none. For the whole world: '
        f'{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}<a href="{DISCORD_URL}">{html.escape(DISCORD_URL.split("//")[-1])}</a></p>')
    return render(body, nonce, COPY_JS)


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
gate_limit = _Window(60)


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
             public: bool = False, same_origin: bool = False, connect: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
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
                         f"default-src 'none'; style-src 'unsafe-inline'; script-src {script}; "
                         f"frame-src https://{STREAM_HOST}; "
                         + ("connect-src 'self'; " if connect else "") +
                         "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
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

    def own_play(self) -> None:
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
            self.own_play()
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
        code = sessions.create(user, password, slug, info["tier"])
        log.info("stream session for %s (%s, tier %d)", user.upper(), slug, info["tier"])
        self.redirect(f"https://{STREAM_HOST}/__gate?code={urllib.parse.quote(code)}")

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
        land = "/?ownfiles=1" if sess.get("mode") == OWN else "/"
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
            body = f"location.replace({json.dumps('https://' + PUBLIC_HOST + '/wrath')});\n".encode()
            self.send(401, body, "application/javascript; charset=utf-8", same_origin=True)
            return
        self.send(200, env_js(sess), "application/javascript; charset=utf-8", same_origin=True)

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
        if straight_in:
            return self.redirect("/wrath/play?mini=mini")
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
    try:
        page.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
