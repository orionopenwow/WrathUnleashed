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
                               "mods" step publishes into /app/mods, one page per mod, the zips, and the
                               community links (stream/projects.py; signed in: POST to add, report, hide)
         GET /wrath/workshop[/<id>]  public: what players made (courses, modes, builds; stream/creations.py), read
                               from the file realm/custom/workshop-export.py writes to /app/workshop every
                               5 minutes; Play is /wrath?go=w:<id> ("ovws go" over SOAP, ov_workshop.lua)
         GET /wrath/status.json  public realm status for the website's Beacons page, the launcher
                               and the GM console (CORS *, cached 30 s, at most one SOAP call per
                               30 s however many visitors ask)
         GET /wrath/admin[/...], POST /wrath/admin/act   staff only: the Leyline Admin Console (stream/admin.py,
                               docs/ADMIN-CONSOLE.md); GET /wrath/leyline/{flags,channel,news,themes,realm-overrides}.json
                               are its public feeds for the launcher
         GET/POST /wrath/leyline/forum[/...], GET /wrath/forum/api/...   the Leyline forum (stream/forum.py): read
                               by anyone, posts from signed-in website accounts; its JSON is for the launcher

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
                               (no-store, same-origin only); the client logs in with it. A realm hop
                               (?go=r:<community realm id> through the gate, the Leyline window's Join)
                               gives that realm's relay addresses instead and NO Wrath login: hop,
                               hop_name, hop_ws, hop_join, home (wrath-early.js rewrites /ws/<port> to
                               hop_ws and fills in the realm's own login from this browser's storage)
         POST /__gate?layer=on|off|beat   the game-folder layer (ownfiles.js): a streamed player
                               dropped their own 3.3.5a game folder on the page, so the realm lifts the
                               zone limit for the account (the same "ovstream clear" as own files) and keeps
                               a lease (WU_LAYER_LEASE s, 15 min) the page renews ("beat"). "off" (the page
                               loaded without the folder) and a lapsed lease (a sweeper, every 30 s) mark the
                               account again for what is left of its session, so the realm never strands a
                               streamed player where they cannot load. A new stream play, own files and
                               "End my browser pass" drop the lease. Same-origin JSON POSTs with the session
                               cookie only. (On /__gate because Caddy already sends that path here.)
  The off switch: WU_STREAM=0 (the default until stream-up.sh sets 1). /wrath/play then says
  streaming is off and /__auth refuses the game data.
  The game data killswitch (stream/server/gamedata-switch.sh, docs/GAME-DATA-ON-OUR-SERVER.md): while the flag
  file WU_GAMEDATA_FLAG (/app/gamedata-off) exists, this server serves no game data at all: streaming is off
  whatever WU_STREAM says, /wrath/play sends everyone to "Play with my own game files", /__auth answers 410 Gone
  for /data (Caddy answers 410 before it, too), the page env says WU_GAMEDATA_OFF, the game screenshots in
  /wrath/art answer 410, and /wrath/status.json says "gamedata_streaming": false (and since when). Sessions are in memory: a restart of this
  service signs stream players out of the stream site (they click Play again).

Settings (environment, /srv/wrath/portal.env):
  SOAP_USER, SOAP_PASS   AzerothCore GM level 3 account for SOAP (required; deploy.sh makes it)
  AC_SOAP_URL            default http://ov-ac-worldserver:7878/
  PORTAL_URL             default http://ovlive-realm:8090 (the Open Vanilla realm service)
  PUBLIC_HOST            default play.openvanilla.app
  REALM_NAME             default WrathUnleashed (ignored while LEYLINE_BRAND=1)
  LEYLINE_BRAND          1 = the Leyline names everywhere people read them: the site is "Leyline", the main realm
                         "Dalaran Hangout" (LEYLINE_REALM_NAME overrides). Default 0: exactly as before.
                         realm/brand.sh on|off flips it with the realm's name and the in-game wording.
  PACKAGE_URL            optional link to the player package (shown on the page when set)
  BRIDGE_USERS           console logins the realm service may use (default WRSOAP,ADMINISTRATOR)
  WU_STREAM              1 = browser streaming on, 0 = off (default 0)
  STREAM_HOST            default wrath.openvanilla.app
  STREAM_SLICES          the slice names /wrath/play accepts (default mini)
  WU_SLICE_DIR           where <slice>.json lives (default /app/slices; maxTier is read from it)
  WU_GAMEDATA_FLAG       the killswitch's flag file (default /app/gamedata-off = /srv/wrath/portal/gamedata-off);
                         read on every request, so gamedata-switch.sh needs no restart of this service
  WU_OWNFILES            1 = show "Play with my own game files" (the browser client on STREAM_HOST
                         with the player's own Data folder); 0 = off (default; stream-up.sh sets 1)
  WU_RELAY_LISTING       the Beacons relay's listing for GET /wrath/realms. Unset: the URL in
                         /app/relay-listing.url (the relay step writes the relay's address on the Docker
                         network there, so the list works without DNS), else
                         https://relay.openvanilla.app/api/listing/realms.json
  WU_JOIN_BASE           where a community realm's Join link goes (default https://relay.openvanilla.app,
                         which serves /join/<realm id> itself)
  WU_HANGOUT_REALM       the relay realm id of the Dalaran Hangout: this realm itself, reached as a Leyline
                         Beacon through the relay (hosting/hangout/hangout-up.sh). Unset: the id in
                         /app/hangout-realm.id (WU_HANGOUT_FILE; the hangout step writes it), else none.
                         It is listed first; a hop to it keeps the player's own Wrath login (the same realm,
                         the same account: no join page, no second account) and lands in Dalaran, and so
                         does "Back to Wrath" (?go=h:dalaran)
  WU_MODS_DIR            the published mods catalog for /wrath/mods (default /app/mods = /srv/wrath/portal/mods,
                         written by stream/server/mods-install.sh)
  WU_PORTAL_DATA         the Workshop's community links, projects.jsonl (default /data = /srv/wrath/portal-data,
                         the one writable mount); WU_MODS_ADMINS, WU_GITHUB_TOKEN etc.: stream/projects.py
  WU_WORKSHOP_ITEMS_DIR  the approved Workshop items for /wrath/workshop (default /app/workshop =
                         /srv/wrath/portal/workshop, written by realm/custom/workshop-export.py)
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
docs = _load_module("wu_docs", "docs.py")   # /wrath/docs (stream/docs.py: the Leyline docs, from docs/leyline)
hostflow = _load_module("wu_hostflow", "hostflow.py")   # /wrath/host: "+ Your server" (stream/hostflow.py)
creations = _load_module("wu_creations", "creations.py")   # /wrath/workshop: what players made (stream/creations.py)
leyline_net = _load_module("wu_leyline_net", "leyline_net.py")   # /wrath/leyline/flags.json + the Host pack (stream/leyline_net.py)
herokey_mod = _load_module("wu_herokey", "herokey_sso.py")   # Hero Key sign-in on Beacons (stream/herokey_sso.py)
hub_mod = _load_module("wu_hub", "hub.py")   # /wrath/leyline-preview: the hidden Leyline hub (stream/hub.py)
playmodes = _load_module("wu_playmodes", "playmodes.py")   # game modes: /wrath/modes.json, Games, ?go=mode: (stream/playmodes.py)
if hub_mod is not None:
    hub_mod.bind(lambda name: globals()[name])
if hostflow is not None:
    hostflow.bind(lambda name: globals()[name])
social = _load_module("wu_social", "social.py")   # Leyline friends and messages (stream/social.py)
if social is not None:
    social.bind(lambda name: globals()[name])
profiles = _load_module("wu_profiles", "profiles.py")   # /wrath/signin, /wrath/profile, /wrath/avatar (stream/profiles.py)
if profiles is not None:
    profiles.bind(lambda name: globals()[name])
forum = _load_module("wu_forum", "forum.py")   # the Leyline forum: /wrath/leyline/forum, /wrath/forum/api (stream/forum.py)
if forum is not None:
    forum.bind(lambda name: globals()[name])
hub_rank = _load_module("wu_hub_rank", "hub_rank.py")   # mods.json, installs and ratings (stream/hub_rank.py)
if hub_rank is not None:
    hub_rank.bind(lambda name: globals()[name])
    hub_rank.setup()
network = _load_module("wu_network", "network.py")   # the realm browser, /wrath/realms.json, realm reports (stream/network.py)
if network is not None:
    network.bind(lambda name: globals()[name])
admin = _load_module("wu_admin", "admin.py")   # /wrath/admin: the Leyline Admin Console (stream/admin.py)
if admin is not None:
    admin.bind(lambda name: globals()[name])
    if creations is not None:
        creations.adjust = admin.adjust_catalog


def signin_url(nxt: str = "/wrath") -> str:
    """The sign-in for a page of ours: the Leyline sign-in (stream/profiles.py), else the website's own."""
    if profiles is not None and profiles.store is not None:
        return profiles.signin_url(nxt)
    return "/login?next=" + urllib.parse.quote(nxt, safe="")


def host_plus(where: str) -> str:
    """The "+ Your server" button (stream/hostflow.py), or nothing when that module is missing."""
    return hostflow.plus_button(where) if hostflow is not None else ""


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
# The Leyline brand switch (owner 2026-10-30): LEYLINE_BRAND=1 in portal.env (realm/brand.sh on|off sets it) shows
# every player- and visitor-facing name as Leyline and the main realm as "Dalaran Hangout". Unset or 0 (the default):
# every page reads exactly as before. Only names people read change: no route, cookie, file or id does.
BRAND = os.environ.get("LEYLINE_BRAND", "0").strip() == "1"
if BRAND:
    REALM_NAME = os.environ.get("LEYLINE_REALM_NAME", "").strip() or "Dalaran Hangout"
    SITE_NAME = "Leyline"
else:
    REALM_NAME = os.environ.get("REALM_NAME", "WrathUnleashed")
    SITE_NAME = REALM_NAME
# "Back to ..." on the hop bar and the in-game Leyline window: the main realm by its name.
BACK_LABEL = f"Back to {REALM_NAME}" if BRAND else "Back to Wrath"
# The brand switch's safety net (send() runs every text/html and JSON answer through it while BRAND is on): an old
# name a module or a mod still carries, in text people read, becomes Leyline. Scripts, styles, URLs and the attributes
# that hold ids or addresses are left alone, and so are identifiers (WrathUnleashedUI) and domains (openvanilla.app).
_BRAND_SKIP = (r'<script\b.*?</script>|<style\b.*?</style>'
               r'|\b(?:href|src|action|id|class|name|for|data-[\w-]+)="[^"]*"|https?://[^\s"\'<>]+')
_BRAND_OLD = r'(?<![\w/.-])(?:Wrath ?Unleashed|Open ?Vanilla)(?!\w|\.\w)'
_BRAND_HTML = re.compile(f"({_BRAND_SKIP})|({_BRAND_OLD})", re.S)
_BRAND_JSON = re.compile(f"(https?://[^\\s\"'<>]+)|({_BRAND_OLD})")


def brand_body(body: bytes, ctype: str) -> bytes:
    """The page as people read it with the Leyline brand on; unchanged when it is off (or not text)."""
    if not BRAND or not body:
        return body
    kind = ctype.split(";", 1)[0].strip().lower()
    if kind not in ("text/html", "application/json"):
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    if kind == "text/html":
        out = brand_look(_BRAND_HTML.sub(lambda m: m.group(1) or "Leyline", text))   # + the flat look and the spinning mark
    else:
        out = _BRAND_JSON.sub(lambda m: m.group(1) or "Leyline", text)
    return body if out == text else out.encode("utf-8")


# The official realm's lead line on the realm cards, and the player package's start file as the account page names it
# (the file keeps its name in the package; with the brand on the page names it plainly).
OFFICIAL_LEAD = f"{REALM_NAME}, the official realm" if BRAND else "The WrathUnleashed realm"
PLAY_STEP = "Run the <b>Play</b> file from the player package" if BRAND else "Run <b>Play WrathUnleashed.bat</b>"
PACKAGE_URL = os.environ.get("PACKAGE_URL", "")
BRIDGE_USERS = {u.strip().upper() for u in os.environ.get("BRIDGE_USERS", "WRSOAP,ADMINISTRATOR").split(",") if u.strip()}
PAGE_PORT = int(os.environ.get("PAGE_PORT", "8091"))
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "7878"))
# Only the live realm service may use the bridge: its "ovlive-realm" alias is its alone (staging,
# Duels and Warfront run their own realm services on the same network with other account lists).
BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "ovlive-realm")

STREAM_HOST = os.environ.get("STREAM_HOST", "wrath.openvanilla.app")
STREAM_SLICES = {x.strip() for x in os.environ.get("STREAM_SLICES", "mini").split(",") if x.strip()}
# The slice behind "Play now" and every ?mini=mini link (stream/server/slice-serve.sh sets it; default mini), so
# the Leyline Sample Hangout's "sampler" slice can be served without changing a link.
PLAY_SLICE = os.environ.get("WU_PLAY_SLICE", "").strip() or "mini"
# The Leyline Sample Hangout (realm/sampler.sh sets WU_SAMPLER=1 in portal.env): the official realm's cards on the
# play page, /wrath/realms and /wrath/leyline name it and say it is temporary. REALM_NAME (the site) stays.
SAMPLER = os.environ.get("WU_SAMPLER") == "1"
SAMPLER_NAME = REALM_NAME if BRAND else "Leyline Sample Hangout"
SAMPLER_NOTE = ("Temporary: a place to try the game. Dalaran, the starting areas and every dungeon and raid stream "
                "to your browser; add your own 3.3.5a game folder to explore the whole world. Community realms on "
                "Leyline are where the world opens up.")  # TODO(owner): the Sample Hangout's own pitch line
SLICE_DIR = os.environ.get("WU_SLICE_DIR", "/app/slices")
ART_DIR = os.environ.get("WU_ART_DIR", "/app/art")
# Forever UI in the browser client (only where it is installed: fui-install.sh lays it over the slice).
# "1" turns it on; WU_FOREVERUI=0 in portal.env gives everyone the stock look. ?foreverui=0 on the page wins.
FOREVERUI = "0" if os.environ.get("WU_FOREVERUI", "1").strip() == "0" else "1"
SESSION_TTL = 12 * 3600
CODE_TTL = 60
DISCORD_URL = "https://discord.gg/hVeUxYwbkr"
GAME_FOLDER_HELP = "/wrath/docs/play#use-your-own-game-folder-to-go-anywhere"
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


def gamedata_flag() -> str:
    return os.environ.get("WU_GAMEDATA_FLAG", "/app/gamedata-off")


def gamedata_off() -> bool:
    """The game data killswitch (gamedata-switch.sh): the flag file exists. Read on every request."""
    return os.path.exists(gamedata_flag())


def gamedata_state() -> dict:
    """{"gamedata_streaming": bool, "gamedata_since": ISO time or None} for status.json and the admin console.
    "since" is when the switch was thrown (the flag's own record, else the file's time); while streaming, the last
    "on" of the switch, or None when it never ran."""
    p = gamedata_flag()
    try:
        st = os.stat(p)
    except OSError:
        # Streaming: since the last "on" of the switch, when it ever ran (gamedata-switch.sh writes gamedata-last.json).
        since = None
        try:
            with open(os.path.join(os.path.dirname(p), "gamedata-last.json"), encoding="utf-8") as f:
                last = json.loads(f.read(4096) or "{}")
            v = last.get("at") if isinstance(last, dict) and last.get("state") == "on" else None
            if isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", v):
                since = v
        except (OSError, ValueError):
            pass
        return {"gamedata_streaming": True, "gamedata_since": since}
    since = None
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.loads(f.read(4096) or "{}")
        v = doc.get("since") if isinstance(doc, dict) else None
        if isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", v):
            since = v
    except (OSError, ValueError):
        pass
    return {"gamedata_streaming": False,
            "gamedata_since": since or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))}


# What /data and the other game-data routes answer while the killswitch is on (the same words as Caddy's block,
# stream/server/gamedata-caddy.py; Caddy answers first, this is the second lock).
GAMEDATA_GONE = (json.dumps({"error": "gamedata_off", "gamedata_streaming": False,
                             "message": "This realm needs your own game folder. Drop your 3.3.5a game folder on the game page.",
                             "own_files": "https://play.openvanilla.app/wrath/play?mode=own"},
                            separators=(",", ":")) + "\n").encode("utf-8")


def stream_on() -> bool:
    """The off switch, read on every request (WU_STREAM=1 turns streaming on). The game data killswitch wins."""
    return os.environ.get("WU_STREAM", "0").strip() == "1" and not gamedata_off()


def ownfiles_on() -> bool:
    """"Play with my own game files" in the browser (WU_OWNFILES=1). Independent of WU_STREAM."""
    return os.environ.get("WU_OWNFILES", "0").strip() == "1"


OWN = "own"  # the session mode of "Play with my own game files"


def slice_info(slug: str) -> dict | None:
    """<WU_SLICE_DIR>/<slug>.json, or None when the slice is unknown or not set up here. "mini" means PLAY_SLICE."""
    if slug == "mini":
        slug = PLAY_SLICE
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

    def set_hop(self, sid: str, hop: dict) -> None:
        """This session plays on a community realm (a Leyline hop): /__env.js gives that realm's addresses."""
        with self.lock:
            if sid in self.sessions:
                self.sessions[sid]["hop"] = {"id": hop["id"], "name": hop["name"], "home": bool(hop.get("home"))}

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


LAYER_LEASE = max(120, int(os.environ.get("WU_LAYER_LEASE", "900") or 900))
LAYER_BUILD = 12340


class Layers:
    """Streamed accounts whose zone limit is lifted because the player's page reads their own game folder
    (POST /__gate?layer=on). In memory: user -> {sid, until, slice, tier, sess_exp, retry}. A lapsed lease is
    marked again by sweep_layers(); a failed mark is retried there."""

    def __init__(self):
        self.lock = threading.Lock()
        self.leases: dict[str, dict] = {}

    def lift(self, user: str, sid: str, sess: dict, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.lock:
            self.leases[user.upper()] = {"sid": sid, "until": now + LAYER_LEASE, "slice": sess.get("slice") or PLAY_SLICE,
                                         "tier": int(sess.get("tier") or 0), "sess_exp": float(sess.get("exp") or now),
                                         "retry": False}

    def renew(self, user: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.lock:
            lease = self.leases.get(user.upper())
            if not lease or lease["retry"]:
                return False
            lease["until"] = now + LAYER_LEASE
            return True

    def take(self, user: str) -> dict | None:
        with self.lock:
            return self.leases.pop(user.upper(), None)

    def has(self, user: str) -> bool:
        with self.lock:
            return user.upper() in self.leases

    def lapsed(self, now: float | None = None) -> list[tuple[str, dict]]:
        now = time.time() if now is None else now
        with self.lock:
            out = [(u, l) for u, l in self.leases.items() if l["until"] <= now]
            for u, _ in out:
                del self.leases[u]
            return out

    def put_back(self, user: str, lease: dict, now: float | None = None) -> None:
        """A mark that failed: tried again on the next sweep (the lease no longer lifts anything)."""
        now = time.time() if now is None else now
        with self.lock:
            self.leases.setdefault(user.upper(), {**lease, "until": now + 30, "retry": True})


layers = Layers()


def layer_mark(user: str, lease: dict, now: float | None = None) -> None:
    """The stream mark back, for what is left of the stream session (at least a minute)."""
    now = time.time() if now is None else now
    secs = int(max(60, min(SESSION_TTL, lease.get("sess_exp", now) - now)))
    realm_mark(user, lease.get("slice") or PLAY_SLICE, int(lease.get("tier") or 0), secs)


def sweep_layers(now: float | None = None) -> int:
    """Mark every account whose lease lapsed (the tab closed, crashed, or lost the folder). Returns how many."""
    n = 0
    for user, lease in layers.lapsed(now):
        if not stream_on():
            continue   # streaming off: the switch released every mark already
        try:
            layer_mark(user, lease, now)
            n += 1
            log.info("layer lease lapsed: %s marked again", user)
        except SoapError as e:
            log.error("layer lease lapsed: mark %s failed: %s %s", user, e.kind, e.detail[:160])
            layers.put_back(user, lease, now)
    return n


def _layer_sweeper() -> None:
    while True:
        time.sleep(30)
        try:
            sweep_layers()
        except Exception:  # noqa: BLE001: the sweeper must keep running
            log.exception("layer sweep")


def cookie_value(header: str, name: str) -> str:
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def hop_for(query: dict) -> dict | None:
    """?go=r:<id> naming a live community realm on the relay's listing: {"id", "name"}, else None (the official
    realm, an unknown or offline realm: no hop, the player lands on Wrath)."""
    if links is None:
        return None
    got = links.check_go((query.get("go") or [""])[0][:40])
    if not got or got[0] != "r" or not REALM_ID_RE.match(got[1]):
        return None
    for r in community_realms()[0]:
        if r["id"] == got[1] and r["live"]:
            return {"id": r["id"], "name": r["name"], "home": r["id"] == hangout_id()}
    return None


def hop_env(sess: dict) -> dict:
    """The env of a hop session: the relay's addresses for that realm and no Wrath login (the realm has its
    own accounts; the page fills in the one this browser keeps for it)."""
    rid = sess["hop"]["id"]
    env = {"hop": rid, "hop_name": sess["hop"]["name"], "hop_ws": f"{RELAY_WS}/ws/{rid}",
           "hop_join": f"{JOIN_BASE}/join/{rid}?hop=1", "host": urllib.parse.urlsplit(RELAY_WS).hostname or "",
           "home": f"https://{PUBLIC_HOST}"}
    if sess["hop"].get("home") and rid == hangout_id():
        # The Dalaran Hangout is this realm through the relay: the player's own Wrath login, as on a plain visit
        # (the same account; the relay and the Beacon agent only carry SRP, never the password).
        env.update(user=sess["user"], hop_home="1")
        env["pass"] = sess["pass"]
    else:
        # Hero Key sign-in (the herokey_sso flag; off: nothing here, the join page as before): a signed assertion
        # for this realm and the one-time login it sets there. wrath-early.js redeems it at the relay before the
        # client starts; a realm that doesn't take it falls back to the join page.
        t = herokey_issue(sess["user"], rid, herokey_mod.LOGIN_TTL_WEB if herokey_mod else 120)
        if t:
            env["hop_sso"] = {"assertion": t["assertion"], "sig": t["sig"], "redeem": herokey_redeem_url(rid)}
            env.update(user=t["login"]["user"])
            env["pass"] = t["login"]["pass"]
    if sess.get("mode") == OWN:
        env["mode"] = OWN
    else:
        env.update(slice=sess["slice"], slice_tier=str(sess["tier"]))
    return env


# ----------------------------------------------------------------------------------------------
# Hero Key sign-in on Beacons (docs/HERO-KEY-SSO.md): behind the herokey_sso flag, OFF by default
# ----------------------------------------------------------------------------------------------
# The site key and the pseudonym pepper live beside the flags file (/data/leyline, 0600), made on first use.
HEROKEY_DIR = os.environ.get("WU_HEROKEY_DIR", "") or getattr(leyline_net, "DIR", "/data/leyline")
herokey_keys = herokey_mod.Keys(HEROKEY_DIR) if herokey_mod is not None else None


def herokey_on() -> bool:
    """The owner turned herokey_sso on (the admin console's flags). Read on every use, so turning it off is instant."""
    if herokey_keys is None or leyline_net is None:
        return False
    try:
        return leyline_net.load().get("flags", {}).get("herokey_sso") is True
    except Exception:   # noqa: BLE001: a broken flags file means off
        return False


def herokey_redeem_url(rid: str) -> str:
    return f"{JOIN_BASE}/api/realms/{rid}/herokey"


def herokey_issue(user: str, rid: str, login_ttl: int) -> dict | None:
    """An assertion and one-time login for this account on this realm, or None (flag off, too many, a key problem).
    Never logged: the login is the player's alone."""
    if not herokey_on() or not REALM_ID_RE.match(rid or "") or not ACCOUNT_RE.match(user or ""):
        return None
    if not herokey_limit.hit("hk:" + user.upper(), 60) or not herokey_limit.hit("hk-all", 20000):
        return None
    try:
        return herokey_mod.issue(herokey_keys.secret(), herokey_keys.pepper(), user, rid, PUBLIC_HOST, login_ttl)
    except Exception as e:   # noqa: BLE001: the hop falls back to the join page
        logging.getLogger("wrath-portal").warning("herokey: could not issue (%s)", type(e).__name__)
        return None


def herokey_issue_api(acct: str, realm, via: str) -> tuple[int, dict]:
    """POST /wrath/api/social/herokey {realm} (stream/social.py): the launcher's Hero Key sign-in to a Beacon."""
    if not herokey_on():
        return 404, {"error": "Hero Key sign-in for community realms isn't on yet."}
    if not isinstance(realm, str) or not REALM_ID_RE.match(realm):
        return 400, {"error": "That is not a realm id."}
    if realm == hangout_id():
        return 400, {"error": "The Dalaran Hangout uses your own game login."}
    if not any(r["id"] == realm and r["live"] for r in community_realms()[0]):
        return 404, {"error": "That realm isn't online right now."}
    t = herokey_issue(acct, realm, herokey_mod.LOGIN_TTL_LAUNCHER if via == "launcher" else herokey_mod.LOGIN_TTL_WEB)
    if not t:
        return 429, {"error": "Too many sign-ins. Try again later."}
    return 200, {"ok": True, "realm": realm, "assertion": t["assertion"], "sig": t["sig"], "login": t["login"],
                 "redeem": herokey_redeem_url(realm)}


def herokey_public() -> tuple[int, bytes, str] | None:
    """GET /wrath/leyline/herokey.json: the site's public key(s), for the host kit to pin. Only while the flag is on."""
    if not herokey_on():
        return None
    try:
        doc = herokey_keys.public_doc()
    except Exception:   # noqa: BLE001
        return None
    return 200, json.dumps(doc, separators=(",", ":")).encode(), "application/json; charset=utf-8"


def env_js(sess: dict) -> bytes:
    """The page env the web client reads before its query string (benilla_app::webenv)."""
    if sess.get("hop"):
        env = hop_env(sess)
    elif sess.get("mode") == OWN:
        env = {"user": sess["user"], "pass": sess["pass"], "host": PUBLIC_HOST, "mode": OWN}
    else:
        env = {"user": sess["user"], "pass": sess["pass"], "host": PUBLIC_HOST,
               "slice": sess["slice"], "slice_tier": str(sess["tier"])}
        if sess.get("mode") == "stream":
            env["layer"] = "1"   # ownfiles.js may offer the game-folder layer (POST /__gate?layer=...)
    env["moderncombos"] = "1"   # character create offers the realm's 83 retail race/class pairs
    env["foreverui"] = FOREVERUI  # Forever UI on (the client reads this before its query string)
    if BRAND:   # the page layer's wording (wrath-page.js: the hop bar's "Back to ...", the tab note); off: not sent
        env["brand"] = "leyline"
        env["home_name"] = REALM_NAME
    if guest and sess.get("mode") == "demo":
        env.update(guest.env_extra(sess))  # the guest pass's character: no character select
    body = json.dumps(env, separators=(",", ":")).replace("<", "\\u003c")
    out = f"window.__wenilla_env = {body};\n"
    # The env object outranks the query string in the client, so ?foreverui=0 (or 1) is copied in.
    out += ("(function(e){try{var v=new URLSearchParams(location.search).get('foreverui');"
            "if(v!==null)e.foreverui=v;}catch(_){}})(window.__wenilla_env);\n")
    if gamedata_off():
        # The killswitch: ownfiles.js goes straight to "drop your game folder" and never asks /data.
        out += "window.WU_GAMEDATA_OFF = true;\n"
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
    "leyline-shot-coa-ultrahd.webp": "image/webp",   # the front page's featured modpack (its authors' screenshot)
    # the owner's Minigolf recording for the Game modes section: a short muted loop and its poster
    "leyline-shot-minigolf.mp4": "video/mp4", "leyline-shot-minigolf.webm": "video/webm", "leyline-shot-minigolf.webp": "image/webp",
    "leyline-mode-azeroth-survivors.webp": "image/webp",   # the mode's key art (the owner's; crest cropped out)
    # the front page's Forge and Agents sections: the owner's own app screenshots (Forge's map of its own island;
    # the Agents inn), game pictures, so behind the killswitch like the other leyline-shot- files
    "leyline-shot-forge.webp": "image/webp", "leyline-shot-agents.webp": "image/webp",
    "leyline-shot-backdrop.webp": "image/webp",   # the hub's backdrop (the owner's picture), faint behind every page
    "leyline-display.woff2": "font/woff2", "leyline-display-OFL.txt": "text/plain; charset=utf-8",   # Big Shoulders Display 600 (SIL OFL 1.1, leyline-display-OFL.txt)
    "leyline-corner-tl.webp": "image/webp", "leyline-corner-tr.webp": "image/webp",   # our gold frame art, hued blue
    "leyline-corner-bl.webp": "image/webp", "leyline-corner-br.webp": "image/webp", "leyline-divider.webp": "image/webp",
    # the owner's screenshots for /wrath/modes (stream/modes.py); a missing one leaves a painted panel
    "leyline-shot-dalaran.webp": "image/webp", "leyline-shot-start.webp": "image/webp",
    "leyline-shot-city.webp": "image/webp", "leyline-shot-durotar.webp": "image/webp",
    "leyline-shot-coa-ultrahd.webp": "image/webp",
    "leyline-shot-minigolf.mp4": "video/mp4", "leyline-shot-minigolf.webm": "video/webm", "leyline-shot-minigolf.webp": "image/webp",
    # the round Leyline mark, split so the swirl turns while the crystal stays upright (SPIN_CSS, the hub)
    "leyline-swirl-256.webp": "image/webp", "leyline-crystal-256.webp": "image/webp",
    "leyline-swirl-128.png": "image/png", "leyline-crystal-128.png": "image/png",
    "leyline-swirl-512.png": "image/png", "leyline-crystal-512.png": "image/png", "leyline-mark-512.png": "image/png",
    # the launcher's own pages for the hub's feature sections (tools/art/leyline-ui-shots.cjs: sample data, no game art)
    "leyline-ui-home.webp": "image/webp", "leyline-ui-realms.webp": "image/webp", "leyline-ui-modes.webp": "image/webp",
    "leyline-ui-workshop.webp": "image/webp",
}
ART_MAX_AGE = 7 * 86400
# Screenshots of the running game (rendered from the game's own files): the killswitch takes them off too
# (410; the pages that show them fall back to a painted panel). docs/GAME-DATA-ON-OUR-SERVER.md
GAMEDATA_ART = frozenset(n for n in ART_TYPES if n.startswith("leyline-shot-"))
_theme_ver = {"key": None, "v": ""}


# The hub's preview thumbnails (tools/hub-index/hub_index.py thumbs: a GitHub project's own preview image as a small
# WebP, stream/www-files/art/hub-thumbs/): allowed by pattern, WebP only, nothing else from that folder.
HUB_THUMB_RE = re.compile(r"hub-thumbs/[a-z0-9][a-z0-9._-]{0,99}__[a-z0-9][a-z0-9._-]{0,99}\.webp")
HUB_THUMB_MAX = 200_000


# The launcher Home gallery's in-game screenshots (owner 2026-10-30), in ART_DIR/home/: one or more per slide id
# (hangout.webp, browser.webp, hangout-2.webp, mode-minigolf.webp ...) and home.json, the list the launcher reads (which
# files, their alt text and credit). Written by tools/site-art/publish_home_art.py (the Autopilot step "homeart"),
# never part of the repo or the launcher. Allowed by pattern: a real WebP or JPEG, or a JSON object, nothing else.
# Game pictures, so the killswitch takes them off too (410; the launcher keeps its plain gradient).
HOME_ART_RE = re.compile(r"home/[a-z0-9][a-z0-9-]{0,40}\.(?:webp|jpg)")
HOME_JSON = "home/home.json"
HOME_ART_MAX = 1_500_000
HOME_JSON_MAX = 64_000
HOME_ART_MAX_AGE = 3600   # an hour: a new screenshot under the same name shows the same day
HOME_JSON_MAX_AGE = 300


def art_type(name: str) -> str:
    """The Content-Type of an allowed art name, "" for anything else (never a path from the URL)."""
    if name in ART_TYPES:
        return ART_TYPES[name]
    if not isinstance(name, str) or ".." in name:
        return ""
    if HUB_THUMB_RE.fullmatch(name):
        return "image/webp"
    if name == HOME_JSON:
        return "application/json; charset=utf-8"
    if HOME_ART_RE.fullmatch(name):
        return "image/webp" if name.endswith(".webp") else "image/jpeg"
    return ""


def home_art(name: str) -> bool:
    """A Home screenshot (not the list): game pictures, behind the killswitch."""
    return isinstance(name, str) and bool(HOME_ART_RE.fullmatch(name)) and ".." not in name


def art_bytes(name: str) -> bytes | None:
    """One file from the allow-list in ART_DIR, or None (not listed, or missing). Never a path from the URL."""
    if not art_type(name):
        return None
    try:
        with open(os.path.join(ART_DIR, name), "rb") as f:
            body = f.read(4_000_000)
    except OSError:
        return None
    if name in ART_TYPES:
        return body
    if name == HOME_JSON:                                   # the list: a JSON object or nothing
        try:
            ok = len(body) <= HOME_JSON_MAX and isinstance(json.loads(body.decode("utf-8")), dict)
        except (ValueError, UnicodeDecodeError):
            ok = False
        return body if ok else None
    webp = body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    if home_art(name):                                      # a screenshot: a real WebP or JPEG of a sane size, or nothing
        jpeg = body[:3] == b"\xff\xd8\xff"
        ok = len(body) <= HOME_ART_MAX and (webp if name.endswith(".webp") else jpeg)
        return body if ok else None
    if len(body) > HUB_THUMB_MAX or not webp:
        return None                                         # a hub thumbnail is a real WebP or nothing
    return body


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
    return bool(art_type(name)) and os.path.isfile(os.path.join(ART_DIR, name))


CARD_DESCRIPTION = ("Play Wrath in your browser, on the Leyline network. "
                    "Dalaran hangout, Dungeon Finder, host your own realm.")


def card_meta(path: str, title: str = "") -> str:
    """Link-preview tags (Open Graph and X) for a public page, so a pasted link shows a proper card."""
    e = html.escape
    title = title or REALM_NAME
    url = f"https://{PUBLIC_HOST}{path}"
    img = f"https://{PUBLIC_HOST}{art_url('wu-card.webp')}"
    card = [("property", "og:image:type", "image/webp"), ("property", "og:image:width", "1200"), ("property", "og:image:height", "630")]
    if BRAND:   # the brand on: the round mark, not the painted card
        img = f"https://{PUBLIC_HOST}{art_url('leyline-mark-512.png')}"
        card = [("property", "og:image:type", "image/png"), ("property", "og:image:width", "512"), ("property", "og:image:height", "512")]
    tags = [("property", "og:type", "website"), ("property", "og:site_name", SITE_NAME),
            ("property", "og:title", title), ("property", "og:description", CARD_DESCRIPTION),
            ("property", "og:url", url), ("property", "og:image", img),
            *card, ("property", "og:image:alt", f"{REALM_NAME}: Wrath on the Leyline network"),
            ("name", "twitter:card", "summary" if BRAND else "summary_large_image"), ("name", "twitter:title", title),
            ("name", "twitter:description", CARD_DESCRIPTION), ("name", "twitter:image", img)]
    return (f'<meta name="description" content="{e(CARD_DESCRIPTION)}"><link rel="canonical" href="{e(url)}">'
            + "".join(f'<meta {k}="{n}" content="{e(v)}">' for k, n, v in tags))


def render(body: str, nonce: str = "", script: str = "", wide: bool = False, meta: str = "", title: str = "",
           current: str = "", next_step: str = "", signed_in: bool = False, chrome: bool = True) -> bytes:
    """A page in the gold look. With chrome (the default) it carries the site's one nav (current marks the item
    for this page) and footer, and next_step ("play" or "host") adds the closing call to action."""
    s = f'<script nonce="{nonce}">{script}</script>' if script else ""
    v = theme_version()
    theme = f'<link rel="stylesheet" href="{art_url("wu-theme.css")}?v={v}">' if v and not BRAND else ""   # brand on: the flat look
    full = f"{title} · {SITE_NAME}" if title else SITE_NAME
    top = (SKIP_LINK + site_nav(current, signed_in)) if chrome else ""
    end = ((next_block(next_step) if next_step else "") + site_footer()) if chrome else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="dark">'
            f'<title>{html.escape(full)}</title>{meta}<style>{STYLE}{SITE_CSS if chrome else ""}</style>{theme}</head>'
            f'<body class="wu">{top}<main id="main" class="wu-panel{" wide" if wide else ""}">{body}</main>{end}{s}</body></html>').encode("utf-8")


def crest(title: str) -> str:
    """The page heading: the title between the two dragons, with the gold divider under it."""
    if BRAND:   # the spinning mark over the title, no dragons
        return f'<div class="crest wu-brand">{spin(56, "ly-crest-mark")}<h1>{html.escape(title)}</h1></div>'
    return f'<div class="crest wu-brand"><h1>{html.escape(title)}</h1></div>'


RULE = '<hr class="rule wu-divider">'


def signed_out_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}<p class="sub">Wrath · on the Leyline network</p>{RULE}'
        f'<p class="center"><a class="btn primary" href="{html.escape(signin_url("/wrath"))}">Sign in</a></p>'
        '<p class="fine center">Played here before? Use the same sign-in. Your Wrath login appears here.</p>'
        '<p class="fine center"><a href="/wrath/realms">All realms</a>, including community realms hosted by players · '
        '<a href="/wrath/leyline">What is Leyline?</a></p>',
        meta=card_meta("/wrath"), title="Sign in", current="play")


def stream_off_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}{RULE}'
        '<p class="center">Streaming is off right now — play with your own game files.</p>'
        '<p class="center"><a class="btn primary" href="/wrath">Get your game login</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>', title="Streaming is off", current="play")


def gamedata_off_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}{RULE}'
        '<p class="center">This realm needs your own game folder: it streams no game files.</p>'
        '<p class="center">Play with your own 3.3.5a game client, or use your 3.3.5a game folder in the browser.</p>'
        '<p class="center"><a class="btn primary" href="/wrath">Get your game login</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>', title="Bring your game folder", current="play")


def stream_ended_page() -> bytes:
    return render(
        f'{crest(REALM_NAME)}{RULE}'
        '<p class="center">Your browser pass has ended. Your account can go anywhere again with your own game files.</p>'
        '<p class="center"><a class="btn" href="/wrath/account">Back</a></p>'
        f'<p class="fine">{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}'
        f'<a href="{DISCORD_URL}">{DISCORD_URL}</a></p>', title="Browser pass ended", current="play")


def busy_page(wait: int = 15, back: str = "/wrath") -> bytes:
    """A 429: the page tries again by itself (a meta refresh, no script) instead of leaving a dead end.
    Limits are per address, and a household or a cafe shares one, so the page stays calm about it."""
    body = (f'{crest(REALM_NAME)}<p class="sub">Lots of sign-ins from your network right now.</p>{RULE}'
            f'<p class="center">Trying again in {int(wait)} seconds…</p>'
            f'<p class="center"><a class="btn" href="{html.escape(back)}">Try now</a></p>')
    page = render(body, title="One moment", current=nav_key(back)).decode("utf-8")
    # back to the page that was busy (a browsing page must not bounce people into the game at /wrath)
    return page.replace("<head>", f'<head><meta http-equiv="refresh" content="{int(wait)};url={html.escape(back)}">', 1).encode("utf-8")


def error_page(msg: str) -> bytes:
    return render(f'{crest(REALM_NAME)}{RULE}<p class="err">{html.escape(msg)}</p>'
                  '<p class="center"><a class="btn" href="/wrath">Try again</a></p>', title="Something went wrong")


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
        nonce, AUTO_SIGNIN_JS, meta=card_meta("/wrath"), title="Sign in", current="play")

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
                   else '<a class="btn primary" href="/wrath/play?mode=own">Play with my game folder</a>'
                   if gamedata_off() and ownfiles_on() else '<span class="btn off">Opening soon</span>')
    if gamedata_off():   # the game data killswitch: say plainly what the browser needs now
        dalaran_btn += ('<br><span class="fine">This realm needs your own game folder: drop your 3.3.5a game folder '
                        f'on the game page. <a href="{GAME_FOLDER_HELP}">Where is it?</a></span>')
    pkg = (f'<li><a href="{html.escape(PACKAGE_URL)}">Download the player package</a> and unzip it.</li>'
           if PACKAGE_URL else '<li>Unzip the player package you were sent.</li>')
    dots = "\u2022" * len(password)
    body = (
        f'<style>{REALM_CSS}</style>'
        f'<div class="top"><span class="eyebrow">{html.escape(REALM_NAME)}</span>'
        '<a class="keylink" href="/account/key">Your Hero Key</a></div>'
        f'{crest("Choose a realm")}<p class="sub">Signed in as {html.escape(display)}</p>{RULE}'
        # 1. Dalaran: the streamed mini version
        + (f'<div class="realm"><h2>{SAMPLER_NAME}</h2>'
           f'<div class="tags"><span class="tag">Temporary</span><span class="tag">In your browser</span>'
           f'<span class="tag">No download</span>{live}</div>'
           f'<p>{html.escape(SAMPLER_NOTE)} Start at level 1 or boost to 80.</p>' if SAMPLER else
           '<div class="realm"><h2>Dalaran</h2>'
           f'<div class="tags"><span class="tag">In your browser</span><span class="tag">No download</span>{live}</div>'
           '<p>Jump straight in: Dalaran, arenas, dungeons and raids, streamed to your browser. '
           'Start at level 1 or boost to 80.</p>')
        + f'<p>{dalaran_btn}</p>'
        + (f'<p class="fine">Have a 3.3.5a game folder? Drop it on the game page (or choose it from the page menu) '
           f'to go anywhere, on the same characters. It is read on your computer and never uploaded. '
           f'<a href="{GAME_FOLDER_HELP}">How</a></p>' if streamed else '')
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
        + ('<p><a class="btn" href="/wrath/play?mode=own">Play in the browser with my game folder</a> '
           f'<a class="fine" href="{GAME_FOLDER_HELP}">Where is my game folder?</a></p>'
           if ownfiles_on() else '')
        + '<details id="desktop"><summary>Play with your own 3.3.5a client: your game account name and password</summary>'
        '<label>Account</label><div class="row">'
        f'<div class="field" id="acct">{html.escape(user)}</div>'
        '<button class="ghost" data-copy="acct" type="button">Copy</button></div>'
        '<label>Password</label><div class="row">'
        f'<div class="field" id="pw" data-v="{html.escape(password)}">{dots}</div>'
        '<button class="ghost" id="show" type="button">Show</button>'
        '<button class="ghost" data-copy="pw" type="button">Copy</button></div>'
        f'<ol>{pkg}<li>{PLAY_STEP} and pick your own 3.3.5a game folder. '
        'Or, in your own client: open <code>Data\\enUS\\realmlist.wtf</code> in your game folder '
        '(<code>enGB</code>, <code>deDE</code>… for other languages) and make its only line '
        f'<code>set realmlist {html.escape(PUBLIC_HOST)}</code></li>'
        '<li>Log in with the account and password above. They are not your website sign-in: '
        'this account name and password are made for the game.</li></ol>'
        '<p class="fine">This login is yours alone. Sign in here again any time to see it.</p></details></div>'
        f'<p class="fine foot">No game files? Dalaran needs none. For the whole world: '
        f'{html.escape(DISCORD_HELP.split(DISCORD_URL)[0])}<a href="{DISCORD_URL}">{html.escape(DISCORD_URL.split("//")[-1])}</a></p>'
        + host_plus("account") +
        '<p class="fine"><a href="/wrath/realms">Community realms</a>: Dalaran hangouts and realms hosted by players</p>'
        '<p class="fine"><a href="/wrath/modes">Modes</a>: duels, boss fights, dungeons and hangouts, one click each</p>')
    return render(body, nonce, COPY_JS, wide=True, title="Choose a realm", current="play", signed_in=True)


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
# Realm hops: the relay's browser bridge (wss://<relay>/ws/<realm id>/auth and /world, hosting/relay/wurelay).
RELAY_WS = os.environ.get("WU_RELAY_WS", "wss://relay.openvanilla.app").rstrip("/")
HANGOUT_REALM = os.environ.get("WU_HANGOUT_REALM", "").strip()
HANGOUT_FILE = os.environ.get("WU_HANGOUT_FILE", "/app/hangout-realm.id")
_hangout = {"at": -1e9, "id": None}


def hangout_id() -> str | None:
    """The Dalaran Hangout's relay realm id (this realm as a Leyline Beacon), or None. Re-read once a minute."""
    if HANGOUT_REALM:
        return HANGOUT_REALM if REALM_ID_RE.match(HANGOUT_REALM) else None
    now = time.monotonic()
    if now - _hangout["at"] > 60:
        _hangout["at"] = now
        try:
            with open(HANGOUT_FILE, encoding="utf-8") as f:
                v = f.read(64).strip()
            _hangout["id"] = v if REALM_ID_RE.match(v) else None
        except OSError:
            _hangout["id"] = None
    return _hangout["id"]


LISTING_TTL = 60          # seconds a good answer is used before it is refreshed (in the background)
LISTING_RETRY = 30        # after a failure
LISTING_WAIT = 2.5        # the longest a page request ever waits for the relay
LISTING_STUCK = 120       # a refresh still running after this long is given up on (a hung connection)
LISTING_MAX = 200
LISTING_BYTES = 2_000_000
REALM_ID_RE = re.compile(r"^[a-z2-7]{16}$")
RULESET_LABELS = {"main": "Level 1 or boost to 80", "brawl": "Brawl: everyone 80",
                  "progression": "Progression", "casual": "Casual", "dalaran": "Dalaran hangout",
                  "vanillaplus": "Vanilla+", "custom": "Custom rules"}
_listing: dict = {"at": -1e9, "ok": False, "realms": [], "fetched": False, "when": 0.0}   # when: wall clock of the last good fetch
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
    out = {"id": rid, "name": txt(rec.get("name"), 32) or "Unnamed realm", "tagline": txt(rec.get("tagline"), 80),
           "type": txt(rec.get("type"), 8) or "PvE", "ruleset": ruleset, "live": rec.get("state") == "live",
           "players": _nonneg(hb.get("players")), "bots": _nonneg(hb.get("bots")),
           "claimed": bool(com.get("claimed")),
           "rules": [t for t in (txt(x, 120) for x in (rec.get("rules") if isinstance(rec.get("rules"), list) else [])[:10]) if t]}
    if network is not None:   # build, core, tags, region, language, uptime, score, ... (stream/network.py)
        out.update(network.extra(rec))
    return out


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


def _read_listing(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "wrath-portal"})
    with urllib.request.urlopen(req, timeout=LISTING_WAIT) as r:
        return r.read(LISTING_BYTES + 1)


def fetch_listing() -> list[dict]:
    # The relay's address on the server (relay-listing.url) first; if that stops answering (a relay or
    # network change on the box: the list once went stale for an hour this way), its public address.
    url = listing_url()
    try:
        raw = _read_listing(url)
    except Exception as first:  # noqa: BLE001 - any failure on the inside address: try the public one
        if url == RELAY_LISTING_DEFAULT:
            raise
        log.info("community listing: %s failed (%s); trying %s", url, str(first)[:80], RELAY_LISTING_DEFAULT)
        raw = _read_listing(RELAY_LISTING_DEFAULT)
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
    home = hangout_id()
    for r in out:
        r["hangout"] = r["id"] == home
    # the Dalaran Hangout first, then live realms by the listing's fair score (stream/network.py order() makes the
    # display order: featured, the sample hangout, the rest)
    out.sort(key=lambda r: (not r["hangout"], not r["live"], -(r.get("score") or 0), -(r["players"] or 0),
                            r["name"].lower()))
    return out


def _refresh_listing(busy=None) -> None:
    busy = busy or _listing_busy
    try:
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
                _listing["when"] = time.time()
    finally:   # always, or no refresh ever runs again and the list freezes
        busy.release()
        _listing_done.set()


def community_realms() -> tuple[list[dict], bool]:
    """(realms, fresh): the cached list and whether the last fetch worked. Never blocks longer than
    LISTING_WAIT, and only before the first fetch has finished."""
    with _listing_lock:
        age = time.monotonic() - _listing["at"]
        stale = age > (LISTING_TTL if _listing["ok"] else LISTING_RETRY)
        fetched = _listing["fetched"]
    global _listing_busy
    if stale and _listing_busy.locked() and time.monotonic() - _listing.get("busy_at", 0) > LISTING_STUCK:
        log.info("community listing: a refresh hung for %ss; starting a new one", LISTING_STUCK)
        _listing_busy = threading.Lock()   # the hung thread releases its own lock, not this one
    busy = _listing_busy
    if stale and busy.acquire(blocking=False):
        _listing["busy_at"] = time.monotonic()
        _listing_done.clear()
        threading.Thread(target=_refresh_listing, args=(busy,), daemon=True).start()
    if not fetched:
        _listing_done.wait(LISTING_WAIT)
    with _listing_lock:
        realms, ok = list(_listing["realms"]), _listing["ok"]
    return (admin.apply_realm_overrides(realms) if admin is not None else realms), ok   # staff: hidden, official


def _players_text(players, bots, live) -> str:
    if not live:
        return "offline"
    if players is None:
        return '<span class="live">● online</span>'
    s = f'<span class="live">● online</span> · {players} playing'
    return s + (f" · {bots} bots" if bots else "")


def sample_info() -> dict:
    """Our own realm on the network's lists (stream/network.py): the Leyline Sample Hangout, temporary, while
    WU_SAMPLER=1 (realm/sampler.sh); before that, this realm under its own name."""
    if SAMPLER:
        return {"name": SAMPLER_NAME, "temporary": True,
                "blurb_html": f'<p>{html.escape(SAMPLER_NOTE)} (<a href="{GAME_FOLDER_HELP}">How to add your game folder</a>.)</p>'}
    return {"name": REALM_NAME, "temporary": False,
            "blurb_html": f'<p>{OFFICIAL_LEAD}: Dalaran in your browser, or the whole world with your own game files '
                          f'(drop your 3.3.5a game folder on the game page: <a href="{GAME_FOLDER_HELP}">how</a>).</p>'}


def realms_page(query: dict | None = None) -> bytes:
    st = realm_status()
    if network is not None:
        realms, ok = community_realms()
        pack = leyline_net.hostpack() if leyline_net is not None else None
        with _listing_lock:
            when = _listing["when"]
        stamps = [x for x in (updated_text(st.get("updated_at"), "Realm status"),
                              updated_text(when, "Community list") if ok else "") if x]
        body = (f'<style>{REALM_CSS}{network.NET_CSS}</style>'
                f'{crest("Realms")}<p class="sub">The Leyline network: realms hosted by players</p>{RULE}'
                + host_plus("realms")
                + network.page_body(realms, ok, query or {}, st, JOIN_BASE, RULESET_LABELS, share_box,
                                    pack["download"] if pack else None, sample=sample_info())
                + '<p class="fine foot">Community realms are run by players on their own PCs, through the Leyline relay '
                '(nobody sees anyone\'s home address). Each host sets their own house rules and is the GM there. The order '
                'is players online, uptime and staff picks: nothing can be bought. '
                '<a href="/wrath/leyline">What is Leyline?</a></p>'
                + (f'<p class="fine">{" · ".join(stamps)}</p>' if stamps else ''))
        return render(body, wide=True, meta=card_meta("/wrath/realms", f"Realms · {REALM_NAME}"), title="Realms",
                      current="realms", next_step="host")
    official = (
        f'<div class="realm"><h2>{html.escape(SAMPLER_NAME if SAMPLER else REALM_NAME)}</h2>'
        '<div class="tags"><span class="tag">Official</span>'
        + ('<span class="tag">Temporary</span>' if SAMPLER else '') +
        '<span class="tag">Level 1 or boost to 80</span>'
        f'{_players_text(_nonneg(st.get("players")), _nonneg(st.get("bots")), bool(st.get("online")))}</div>'
        + (f'<p>{html.escape(SAMPLER_NOTE)} '
           f'(<a href="{GAME_FOLDER_HELP}">How to add your game folder</a>.)</p>' if SAMPLER else
           f'<p>{OFFICIAL_LEAD}: Dalaran in your browser, or the whole world with your own game files '
           f'(drop your 3.3.5a game folder on the game page: <a href="{GAME_FOLDER_HELP}">how</a>).</p>') +
        '<p><a class="btn primary" href="/wrath">Play</a></p>'
        + share_box("/wrath/r/wrath") + '</div>')
    realms, ok = community_realms()
    rows = []
    for r in realms:
        name = html.escape(r["name"])
        tags = (('<span class="tag">Official</span>' if r.get("official") else '')
                + f'<span class="tag">{html.escape(RULESET_LABELS[r["ruleset"]])}</span>'
                f'<span class="tag">{html.escape(r["type"])}</span>'
                + ('' if r["claimed"] else '<span class="tag">unclaimed</span>')
                + _players_text(r["players"], r["bots"], r["live"]))
        join = f'{JOIN_BASE}/join/{r["id"]}'
        if r.get("hangout"):
            # this realm's own Dalaran through the relay: the player's Wrath characters, no new account
            tags = (f'<span class="tag">Run by {html.escape(REALM_NAME)}</span>'
                    '<span class="tag">Your Wrath characters</span>' + _players_text(r["players"], r["bots"], r["live"]))
            button = '<a class="btn primary" href="/wrath?go=h:dalaran">Play in Dalaran</a>'
        else:
            button = f'<a class="btn" href="{html.escape(join)}" rel="noopener noreferrer">Join</a>'
        rows.append(
            f'<div class="realm"><h2>{name}</h2><div class="tags">{tags}</div>'
            + (f'<p>{html.escape(r["tagline"])}</p>' if r["tagline"] else '')
            + ('<details><summary>House rules</summary><ol>'
               + "".join(f'<li>{html.escape(x)}</li>' for x in r["rules"]) + '</ol></details>' if r["rules"] else '')
            + f'<p>{button}</p>'
            + share_box(f'/wrath/r/{r["id"]}') + '</div>')
    if rows:
        community = "".join(rows)
        if not ok:
            community = '<p class="fine">The realm list may be a little out of date right now.</p>' + community
    elif ok:
        community = ('<p class="fine">No community realms are open right now. Anyone can host one: '
                     'a private realm for friends or a public Dalaran hangout, with their own GM login and rules.</p>')
    else:
        community = '<p class="fine">The community realm list isn\'t reachable right now. Try again in a minute.</p>'
    with _listing_lock:
        when = _listing["when"]
    stamps = [x for x in (updated_text(st.get("updated_at"), "Realm status"),
                          updated_text(when, "Community list") if ok else "") if x]
    body = (f'<style>{REALM_CSS}</style>'
            f'{crest("Realms")}<p class="sub">Wrath · on the Leyline network</p>{RULE}'
            + official +
            '<h2 class="eyebrow">Community realms</h2>'
            + host_plus("realms")
            + community +
            '<p class="fine foot">Community realms are run by players on their own PCs, through the Leyline relay '
            '(nobody sees anyone\'s home address). Each host sets their own house rules and is the GM there. '
            '<a href="/wrath/leyline">What is Leyline?</a></p>'
            + (f'<p class="fine">{" · ".join(stamps)}</p>' if stamps else ''))
    return render(body, wide=True, meta=card_meta("/wrath/realms", f"Realms · {REALM_NAME}"), title="Realms",
                  current="realms", next_step="host")


LEYLINE_REPO = "https://github.com/orionopenwow/Leyline"   # the public repo (the workspace repo is private)


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
.ly-wrap{position:relative;z-index:1}
@media (prefers-reduced-motion:no-preference){
body.ly::before{animation:ly-drift 180s linear infinite,ly-twinkle 5s ease-in-out infinite alternate}
body.ly::after{animation:ly-drift 120s linear infinite reverse,ly-twinkle 7s ease-in-out infinite alternate-reverse}
.ly-glow{animation:ly-pulse 9s ease-in-out infinite}}
@keyframes ly-drift{to{transform:translate(-420px,-210px)}}
@keyframes ly-twinkle{from{opacity:.35}to{opacity:.85}}
@keyframes ly-pulse{50%{opacity:.6}}
.ly a{color:var(--ly-cyan)}
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
    if BRAND:   # the brand on: none of the painted art (the nebula, the corners, the divider) or the display fonts
        css = re.sub(r"url\(/wrath/art/leyline-(?:bg|corner-[tb][lr]|divider)\.webp\)", "none", css)
        css = re.sub(r"@font-face\{[^}]*\}", "", css)
    return css


# ----------------------------------------------------------------------------------------------
# The Leyline look (owner 2026-10-30): flat and dark like the launcher, the round mark that turns
# ----------------------------------------------------------------------------------------------
#
# SPIN_CSS is the spinner: one empty element (spin()), the swirl turns, the crystal on top stays upright; the same rules
# as the launcher's ui/spin.css and the game page's www-files/leyline-look.css, only the image paths differ. LOOK_VARS
# are the launcher's Dark tokens. With the brand switch on, brand_look() adds them and FLAT_CSS to every page this
# portal sends (the gold render() pages and the Leyline ones): the painted art is not linked at all then (render(),
# leyline_css(), card_meta(), crest(), site_nav(), leyline_page()), and the spinning mark is the header logo. With
# the switch off nothing here is sent. The hub (stream/hub.py) uses SPIN_CSS and LOOK_VARS always.

SPIN_CSS = """
.ly-spin{--ly-spin-size:18px;--ly-spin-turn:7s;position:relative;display:inline-block;flex:none;vertical-align:middle;
width:var(--ly-spin-size);height:var(--ly-spin-size)}
.ly-spin::before,.ly-spin::after{content:"";position:absolute;inset:0;background:center/contain no-repeat;pointer-events:none}
.ly-spin::before{background-image:url(/wrath/art/leyline-swirl-256.webp);animation:ly-spin-turn var(--ly-spin-turn) linear infinite;will-change:transform}
.ly-spin::after{background-image:url(/wrath/art/leyline-crystal-256.webp)}
.ly-spin.slow{--ly-spin-turn:16s}
@keyframes ly-spin-turn{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.ly-spin::before{animation:none!important}}
"""
LOOK_VARS = """
:root{--lk-bg:#15181f;--lk-chrome:#181b23;--lk-surface:#1e222b;--lk-surface-2:#252a35;--lk-raised:#2c3240;
--lk-border:#2c313c;--lk-border-strong:#3c4352;--lk-text:#eef0f4;--lk-text-2:#c8cdd7;--lk-muted:#9aa1ae;
--lk-accent:#5b8def;--lk-accent-strong:#7aa3f5;--lk-accent-soft:rgba(91,141,239,.16);--lk-accent-2:#8b6cf0;
--lk-ok:#4fd18b;--lk-bad:#ff7f76;--lk-r:14px;--lk-r-sm:10px;
--lk-font:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
"""
FLAT_CSS = """
html,html body.wu,html body.ly{background:var(--lk-bg)!important;color:var(--lk-text)}
html body.ly::before,html body.ly::after,html body.wu::before,.ly-glow{display:none!important}
html body :is(h1,h2,h3,h4,p,li,td,th,a,button,label,summary,small,span,b,i,div,input,select,textarea,figcaption){font-family:var(--lk-font)!important}
html body a,html body :is(.fine,.sub,p,li) a{color:var(--lk-accent-strong)}
html body .foot{border-top-color:var(--lk-border)!important}
html body :is(h1,.ly h1,.hb-head h1){background:none!important;-webkit-text-fill-color:currentColor;color:var(--lk-text)!important;filter:none!important;
text-shadow:none!important;text-transform:none!important;letter-spacing:-.01em!important;font-weight:700!important}
html body.ly h1{font-size:clamp(38px,6vw,58px)!important}
html body :is(h2,.ly h2){color:var(--lk-text)!important;text-shadow:none!important;text-transform:none!important;letter-spacing:-.005em!important;font-weight:700!important}
html body.ly h2{font-size:22px!important}
html body :is(.ly-feat h3,.ly-shot figcaption b,.hb-card h3,.hb-build b,.ly-now b){color:var(--lk-text)!important;text-transform:none!important;letter-spacing:0!important;font-weight:650!important}
html body .ly-panel h2::after{display:none!important}
html body :is(main.wu-panel,.ly-panel,.realm,.ly-feat,.ly-shot,.ly-now,.hb-card,.hb-build,.hb-cat,.card){background:var(--lk-surface)!important;
border:1px solid var(--lk-border)!important;border-radius:var(--lk-r)!important;box-shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.18)!important}
html body :is(.ly-btn,a.btn,button,a.ly-next-go,.ly-nav a.ly-hot){background:var(--lk-accent)!important;color:#fff!important;
border:1px solid var(--lk-accent)!important;border-radius:var(--lk-r-sm)!important;box-shadow:none!important;text-transform:none!important;
letter-spacing:.01em!important;font-weight:650!important}
html body :is(.ly-btn,a.btn,button,a.ly-next-go):hover{background:var(--lk-accent-strong)!important;border-color:var(--lk-accent-strong)!important}
html body .ly-btn::before{display:none!important}
html body .ly-btn.violet{background:var(--lk-accent-2)!important;border-color:var(--lk-accent-2)!important}
html body :is(button.ghost,.btn.off,.ly-btn.hb-alt){background:var(--lk-raised)!important;border-color:var(--lk-border-strong)!important;color:var(--lk-text)!important}
html body :is(.sub,.fine,label,.tags,.eyebrow,summary,.ly-fine,.ly-lede,.ly-next p,.ly-foot,.hb-count){color:var(--lk-muted)}
html body .ly-lede{color:var(--lk-text-2)}
html body :is(.rule,.wu-divider){background:none!important;border:0!important;border-top:1px solid var(--lk-border)!important;height:0!important}
html body :is(.field,code,.tag,.ly-share code){background:var(--lk-surface-2)!important;border-color:var(--lk-border)!important;color:var(--lk-text)!important}
html body .ly-nav{background:var(--lk-chrome)!important;border-bottom:1px solid var(--lk-border)!important;-webkit-backdrop-filter:none;backdrop-filter:none}
html body .ly-nav a{color:var(--lk-muted);text-transform:none;letter-spacing:.01em;font-size:13px}
html body .ly-nav a:hover,html body .ly-nav a.on{color:var(--lk-text)!important;border-color:var(--lk-border-strong)!important;background:var(--lk-accent-soft)!important}
html body .ly-nav a.ly-brand{gap:9px;font:700 19px/1 var(--lk-font)!important;letter-spacing:-.01em!important;color:var(--lk-text)!important;
background:none!important;border-color:transparent!important}
html body .ly-foot{background:var(--lk-chrome)!important;border-top:1px solid var(--lk-border)!important}
html body .ly-foot a{color:var(--lk-text-2)}
html body .ly-dot{background:var(--lk-ok);box-shadow:none}
html body .ly-on,html body .live{color:var(--lk-ok)!important}
html body .ly-table th{color:var(--lk-muted);border-color:var(--lk-border)}html body .ly-table td{border-color:var(--lk-border)}
html body .ly-feat .soon{color:var(--lk-accent-2);border-color:var(--lk-accent-2)}
html body .ly-ver{border-color:var(--lk-border-strong);color:var(--lk-muted)}
html body .crest{flex-direction:column;align-items:center;gap:10px}
html body .ly-crest-mark,html body .ly-hero-mark{display:block;margin:0 auto}
html body .ly-hero-mark{--ly-spin-size:min(180px,48vw)!important;margin:6px auto 8px}
html body .ly-hero-mark::after{filter:drop-shadow(0 0 18px rgba(91,141,239,.55))}
html body .ly-skip{background:var(--lk-accent)!important;color:#fff!important}
html body .ly-btn{font-size:18px!important;min-height:52px}
html body .ly-plus{background:var(--lk-accent-2)!important;color:#fff!important;box-shadow:none!important;text-transform:none;letter-spacing:.01em}
html body .ly-now li{background:var(--lk-surface-2)!important;border-color:var(--lk-border)!important}
html body .ly .ly-now h2{color:var(--lk-ok)!important;font-size:12px!important;letter-spacing:.12em!important;text-transform:uppercase!important}
html body .ly-table td.name a{color:var(--lk-text);text-decoration:none;font-weight:600}
html body :where(a,button,summary,input,select,textarea,[tabindex]):focus-visible{outline:2px solid var(--lk-accent-strong)!important}
"""
_LOOK_TAG = f'<style id="ly-look">{LOOK_VARS}{SPIN_CSS}{FLAT_CSS}</style>'


def spin(size: int = 0, cls: str = "", label: str = "") -> str:
    """The spinning Leyline mark (SPIN_CSS). size in px (default 18), label: what a screen reader says (else hidden)."""
    c = "ly-spin" + (" " + cls if cls else "")
    st = f' style="--ly-spin-size:{int(size)}px"' if size else ""
    a = f' role="img" aria-label="{html.escape(label)}"' if label else ' aria-hidden="true"'
    return f'<span class="{c}"{st}{a}></span>'


def brand_look(page: str) -> str:
    """With the brand on: the flat look and the spinner's rules into a page (once; the hub has its own)."""
    if not BRAND or "</head>" not in page or 'id="ly-look"' in page or 'data-look="leyline"' in page:
        return page
    page = _PAINTED_FONT.sub("", page)   # the display fonts' @font-face rules (SITE_CSS, modules): nothing uses them now
    page = _PAINTED_URL.sub("none", page)   # any painted art a module's own CSS still names (the demo page's nebula)
    return page.replace("</head>", _LOOK_TAG + "</head>", 1)


_PAINTED_URL = re.compile(r"url\((?:/wrath/art/)?(?:leyline-(?:bg|emblem|divider|corner-[tb][lr])\.webp|wu-[\w-]+\.webp|ART_[A-Z]+)\)")
_PAINTED_FONT = re.compile(r"@font-face\{font-family:'(?:Leyline Display|OW Cinzel|WU Cinzel)';[^}]*\}")


# ----------------------------------------------------------------------------------------------
# The site's one nav and footer (every public page), the closing call to action, share boxes
# ----------------------------------------------------------------------------------------------
#
# Every page, in either look (the gold render() pages and the Leyline ones), carries the same nav: Leyline (the
# hub), Play, Realms, Modes, Mods, Armory, Docs, Server (host guide), Discord, then Sign in and Play now. The item for
# the page is marked (class "on", aria-current="page"). On a phone the links fold behind a Menu button: a
# checkbox and its label, so it works with no script (the public pages allow none: script-src 'none').
# The pages of the modules beside this file (modes.py, armory.py, workshop.py, demo.py, docs.py) get the nav and footer
# from site_chrome() as they are sent, so they stay one place without each module knowing the site's links.

HOST_URL = f"{LEYLINE_REPO}/blob/main/hosting/INSTALL-OPERATE.md"
BUG_URL = f"{LEYLINE_REPO}/issues/new"
SKIP_LINK = '<a class="ly-skip" href="#main">Skip to content</a>'

SITE_CSS = """
@font-face{font-family:'Leyline Display';src:url(/wrath/art/leyline-display.woff2) format('woff2');font-display:swap}
.ly-skip{position:absolute;left:8px;top:-80px;z-index:30;padding:9px 14px;border-radius:4px;background:#5fe3ff;color:#0a0d24!important;
font:600 14px system-ui,sans-serif;text-decoration:none}
.ly-skip:focus{top:8px}
.ly-nav{--n-ink:#e8ecff;--n-dim:#a9b0d6;--n-cyan:#5fe3ff;--n-line:rgba(120,150,255,.28);position:sticky;top:0;z-index:20;
display:flex;align-items:center;flex-wrap:wrap;gap:6px 10px;padding:8px 16px;box-sizing:border-box;width:100%;
background:rgba(6,8,22,.9);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);border-bottom:1px solid var(--n-line);
font:600 12px/1 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;text-align:left}
.ly-nav a,.ly-menu-b{display:inline-flex;align-items:center;min-height:34px;box-sizing:border-box;padding:0 10px;border:1px solid transparent;
border-radius:4px;color:var(--n-dim);text-decoration:none;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap}
.ly-nav a:hover{color:var(--n-ink);border-color:var(--n-line)}
.ly-nav a.on{color:var(--n-ink);border-color:var(--n-cyan);background:rgba(95,227,255,.12)}
.ly-nav a.ly-brand{order:0;font:600 21px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.14em;color:#bff6ff;padding:0 8px}
.ly-nav .ly-links{order:1;display:flex;flex-wrap:wrap;gap:2px;flex:1 1 auto}
.ly-nav .ly-end{order:2;display:flex;gap:6px;margin-left:auto}
.ly-nav a.ly-hot{order:3;color:#1a1030;background:linear-gradient(180deg,#9ff0ff,#5fe3ff);border-color:#9ff0ff}
.ly-nav a.ly-hot:hover{box-shadow:0 0 18px rgba(95,227,255,.45)}
.ly-menu-t{position:absolute;width:1px;height:1px;margin:0;opacity:0;pointer-events:none}
.ly-menu-b{display:none;cursor:pointer;border-color:var(--n-line);color:var(--n-ink)}
.ly-menu-b::before{content:"";width:14px;height:10px;margin-right:8px;border-top:2px solid;border-bottom:2px solid;
background:linear-gradient(currentColor,currentColor) center/100% 2px no-repeat}
@media (max-width:820px){
.ly-nav a.ly-hot{order:1;margin-left:auto}.ly-menu-b{display:inline-flex;order:2}
.ly-nav .ly-links,.ly-nav .ly-end{display:none;order:3;flex:1 0 100%;flex-direction:column;gap:2px;margin:4px 0 2px}
.ly-nav .ly-end{order:4;flex-direction:row;margin-left:0}
.ly-menu-t:checked~.ly-links,.ly-menu-t:checked~.ly-end{display:flex}
.ly-nav .ly-links a{min-height:42px;font-size:13px}}
.ly-menu-t:focus-visible+.ly-menu-b{outline:2px solid #5fe3ff;outline-offset:2px}
.ly-nav a:focus-visible,.ly-foot a:focus-visible,.ly-next a:focus-visible,.ly-share summary:focus-visible,.ly-share code:focus-visible,
.ly :where(a,button,summary,input,select,textarea,[tabindex]):focus-visible{outline:2px solid #5fe3ff;outline-offset:2px}
.ly-next,.ly-foot{position:relative;z-index:1;box-sizing:border-box;width:100%;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.ly-next{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:10px 18px;max-width:1040px;margin:8px auto 0;padding:22px 16px;
text-align:center;color:#e8ecff}
.ly-next p{margin:0;color:#a9b0d6}.ly-next p a{color:#5fe3ff}
a.ly-next-go{display:inline-flex;align-items:center;min-height:48px;padding:0 26px;border-radius:6px;text-decoration:none;
font:600 20px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.12em;text-transform:uppercase;
color:#1a1030!important;background:linear-gradient(180deg,#9ff0ff,#5fe3ff);border:1px solid #9ff0ff;box-shadow:0 6px 18px rgba(0,0,0,.4)}
a.ly-next-go:hover{box-shadow:0 0 22px rgba(95,227,255,.5)}
.ly-foot{margin-top:18px;padding:18px 16px 26px;border-top:1px solid rgba(120,150,255,.22);background:rgba(4,5,14,.78);color:#a9b0d6;text-align:center;font-size:14px}
.ly-foot nav{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 18px;margin-bottom:8px}
.ly-foot a{color:#cfd6ff;text-decoration:none;padding:4px 0}.ly-foot a:hover{color:#fff;text-decoration:underline}
.ly-foot p{margin:0}
body:has(>.ly-nav):not(.ly){justify-content:flex-start;padding-top:0;padding-bottom:0}
body:has(>.ly-nav):not(.ly)>.ly-nav{width:calc(100% + 32px);margin:0 -16px 28px}
body:has(>.ly-nav):not(.ly)>main{margin-bottom:auto}
body:has(>.ly-nav):not(.ly)>.ly-next{margin-top:18px}
body:has(>.ly-nav):not(.ly)>.ly-foot{width:calc(100% + 32px);margin:18px -16px 0}
.ly-share{margin:8px 0 0;font:13px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.ly-share>summary{display:inline-flex;align-items:center;min-height:30px;padding:0 10px;cursor:pointer;list-style:none;border-radius:4px;
border:1px solid rgba(120,150,255,.35);color:#cfd6ff;font-weight:600;font-size:11px;letter-spacing:.1em;text-transform:uppercase}
.ly-share>summary::-webkit-details-marker{display:none}
.ly-share>summary::before{content:"\\2197";margin-right:6px}
.ly-share[open]>summary{border-color:#5fe3ff;color:#fff}
.ly-share code{display:block;margin:6px 0 0;padding:7px 9px;border-radius:4px;border:1px solid rgba(120,150,255,.35);background:rgba(5,6,20,.9);
color:#e8ecff;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere;-webkit-user-select:all;user-select:all;cursor:text}
.ly-share small{display:block;margin-top:4px;color:#a9b0d6;font-size:12px}
.ly-now{position:relative;z-index:1;max-width:900px;margin:0 auto 26px;padding:12px 16px;border:1px solid rgba(120,150,255,.3);border-radius:8px;
background:rgba(10,12,34,.78);box-shadow:0 8px 24px rgba(0,0,0,.35)}
.ly .ly-now h2{margin:0 0 8px;font:600 13px/1 system-ui,sans-serif;letter-spacing:.18em;text-align:left;color:#5ef0a0;text-shadow:none}
.ly-now ul{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.ly-now li{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:7px 12px;border-radius:999px;border:1px solid rgba(120,150,255,.25);
background:rgba(20,24,60,.6);font-size:14px}
.ly-now li>a.all{color:#e8ecff;text-decoration:none;font-weight:600}
.ly-now b{font:600 18px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.06em;color:#bff6ff}
.ly-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#5ef0a0;box-shadow:0 0 8px #5ef0a0}
.ly-now p{margin:8px 0 0;font-size:12px;color:#a9b0d6}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}.ly-dot{animation:ly-live 2.4s ease-in-out infinite}}
@keyframes ly-live{50%{opacity:.35;box-shadow:none}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""


def _nav_item(key: str, label: str, href: str, current: str, cls: str = "", external: bool = False) -> str:
    on = key == current
    c = " ".join(x for x in (cls, "on" if on else "") if x)
    return (f'<a href="{html.escape(href)}"' + (f' class="{c}"' if c else "") + (' aria-current="page"' if on else "")
            + (' rel="noopener noreferrer"' if external else "") + f'>{html.escape(label)}</a>')


def site_nav(current: str = "", signed_in: bool = False) -> str:
    """The one nav (see above). current: leyline, play, realms, modes, mods, armory or docs ("" marks nothing)."""
    items = [("play", "Play", "/wrath/account"), ("realms", "Realms", "/wrath/realms")]
    if modes is not None:
        items.append(("modes", "Modes", "/wrath/modes"))
    if workshop_mod is not None:
        items.append(("mods", "Mods", "/wrath/mods"))
    if creations is not None:
        items.append(("workshop", "Workshop", "/wrath/workshop"))
    if armory is not None:
        items.append(("armory", "Armory", "/wrath/armory"))
    if docs is not None:
        items.append(("docs", "Docs", "/wrath/docs"))
    links_html = "".join(_nav_item(k, label, href, current) for k, label, href in items)
    links_html += _nav_item("server", "Server", HOST_URL, current, external=True)
    links_html += _nav_item("discord", "Discord", DISCORD_URL, current, external=True)
    end = (_nav_item("profile", "Profile", "/wrath/profile", current) if signed_in and profiles is not None and profiles.store is not None
           else "" if signed_in else _nav_item("signin", "Sign in", signin_url("/wrath"), current))
    return ('<nav class="ly-nav" id="ly-site-nav" aria-label="Leyline">'
            + (_nav_item("leyline", "Leyline", "/wrath/leyline", current, "ly-brand").replace(">Leyline</a>", ">" + spin(26) + "Leyline</a>")
               if BRAND else _nav_item("leyline", "Leyline", "/wrath/leyline", current, "ly-brand"))
            + '<a class="ly-hot" href="/wrath">Play now</a>'
            '<input type="checkbox" id="ly-menu" class="ly-menu-t"><label for="ly-menu" class="ly-menu-b">Menu</label>'
            f'<div class="ly-links">{links_html}</div>'
            + (f'<div class="ly-end">{end}</div>' if end else "") + '</nav>')


def site_footer() -> str:
    e = html.escape
    return ('<footer class="ly-foot"><nav aria-label="About Leyline">'
            f'<a href="{e(LEYLINE_REPO)}" rel="noopener noreferrer">Source on GitHub</a>'
            f'<a href="{e(DISCORD_URL)}" rel="noopener noreferrer">Discord</a>'
            f'<a href="{e(BUG_URL)}" rel="noopener noreferrer">Report a bug</a>'
            '<a href="/wrath/leyline">About Leyline</a></nav>'
            '<p>No shop. Bots are labelled.</p></footer>')


def next_block(kind: str = "play") -> str:
    """The one clear next step at the end of a page: Play now (the default) or Host a realm."""
    e = html.escape
    if kind == "host":
        return ('<aside class="ly-next" aria-label="Next step">'
                f'<a class="ly-next-go" href="{e(HOST_URL)}" rel="noopener noreferrer">Host a realm</a>'
                '<p>Your own realm on your own PC: your rules, your GM login, on the realm list in minutes. '
                'Or <a href="/wrath">play now</a>.</p></aside>')
    return ('<aside class="ly-next" aria-label="Next step"><a class="ly-next-go" href="/wrath">Play now</a>'
            '<p>In your browser, nothing to download and nothing to buy. '
            f'Or <a href="{e(HOST_URL)}" rel="noopener noreferrer">host a realm</a>.</p></aside>')


def share_box(path: str) -> str:
    """A Share control for a card, with no script: it opens on the full link, which one tap selects for copying."""
    url = html.escape(f"https://{PUBLIC_HOST}{path}")
    return (f'<details class="ly-share"><summary>Share</summary><code tabindex="0">{url}</code>'
            '<small>Tap the link to select it, then copy. It opens with a preview card.</small></details>')


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):\d{2}Z$")


def updated_text(when, label: str = "Updated") -> str:
    """'<label> <time>12:34 UTC</time>' for an ISO time (status.json's updated_at) or a Unix time; "" when unknown."""
    if isinstance(when, str):
        m = _ISO_RE.fullmatch(when)
        if not m:
            return ""
        iso, hm = when, f"{m.group(1)}:{m.group(2)}"
    elif isinstance(when, (int, float)) and not isinstance(when, bool) and when > 0:
        t = time.gmtime(when)
        iso, hm = time.strftime("%Y-%m-%dT%H:%M:%SZ", t), time.strftime("%H:%M", t)
    else:
        return ""
    return f'{html.escape(label)} <time datetime="{iso}">{hm} UTC</time>'


def nav_key(path: str) -> str:
    """Which nav item a path belongs to ("" for none)."""
    p = (path or "").split("?", 1)[0].rstrip("/") or "/"
    if p in ("/wrath", "/wrath/account") or p.startswith("/wrath/play"):
        return "play"
    if p == "/wrath/leyline":
        return "leyline"
    for key, roots in (("realms", ("/wrath/realms", "/wrath/r", "/r")), ("modes", ("/wrath/modes", "/wrath/h", "/wrath/q", "/wrath/b", "/h", "/q", "/b")),
                       ("mods", ("/wrath/mods", "/wrath/m", "/m")), ("armory", ("/wrath/armory", "/wrath/u", "/u")),
                       ("workshop", ("/wrath/workshop", "/wrath/w", "/w")),
                       ("docs", ("/wrath/docs",))):
        if any(p == r or p.startswith(r + "/") for r in roots):
            return key
    return ""


_MODULE_NAV_RE = re.compile(r'<nav class="ly-nav" aria-label="Leyline">.*?</nav>', re.S)
_IMG_NO_LOADING_RE = re.compile(r"<img(?![^>]*\bloading=)")


def site_chrome(page: bytes, path: str, next_step: str = "play") -> bytes:
    """A Leyline-look page from a module beside this file, with the site's nav, footer and closing step put in
    (any nav of its own taken out), its link card filled in when it has none, and images lazy-loaded. A page that
    already has the site nav, or isn't a page, is returned as it is. Never raises."""
    try:
        s = page.decode("utf-8")
        if 'id="ly-site-nav"' in s or "<body" not in s or "</head>" not in s:
            return page
        s = _MODULE_NAV_RE.sub("", s, count=1)
        head = f"<style>{SITE_CSS}</style>"
        if 'property="og:title"' not in s:
            t = re.search(r"<title>([^<]*)</title>", s)
            head = card_meta(path, html.unescape(t.group(1)) if t else "Leyline") + head
        s = s.replace("</head>", head + "</head>", 1)
        s = re.sub(r'<body[^>]*>(?:<div class="ly-glow"></div>)?', lambda m: m.group(0) + SKIP_LINK + site_nav(nav_key(path)), s, count=1)
        s = s.replace('<div class="ly-wrap">', '<div class="ly-wrap" id="main">', 1)
        s = _IMG_NO_LOADING_RE.sub('<img loading="lazy" decoding="async"', s)
        i = s.rfind("</body>")
        if i >= 0:
            s = s[:i] + (next_block(next_step) if next_step else "") + site_footer() + s[i:]
        return s.encode("utf-8")
    except Exception:  # noqa: BLE001: the page itself still goes out
        return page


def ly_shell(title: str, body: str, path: str, current: str, next_step: str = "play", css: str = "",
             meta: str | None = None, noindex: bool = False) -> bytes:
    """A whole page in the Leyline look, with the site's nav, footer and closing step."""
    meta = card_meta(path, title) if meta is None else meta
    if noindex:
        meta += '<meta name="robots" content="noindex">'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{html.escape(title)}</title>{meta}<style>{leyline_css()}{css}{SITE_CSS}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div>{SKIP_LINK}{site_nav(current)}'
            f'<div class="ly-wrap" id="main">{body}</div>{next_block(next_step) if next_step else ""}{site_footer()}'
            '</body></html>').encode("utf-8")


# ----------------------------------------------------------------------------------------------
# "Right now" on /wrath/leyline: real numbers only, cached 60 s
# ----------------------------------------------------------------------------------------------
#
# Players on Wrath (this service's own status), live community realms (the relay listing), the latest mods
# (the Workshop catalog, newest zip first) and recent level 80s (the armory index). A source that is missing,
# failing or says zero is left out: the strip never shows a made-up number or a 0 dressed up as live.

RIGHT_NOW_TTL = 60
_right_now: dict = {"at": -1e9, "items": [], "when": 0.0}
_right_now_lock = threading.Lock()


def latest_mods(n: int = 3) -> list[dict]:
    """The Workshop's mods, newest published zip first ([] without a Workshop or a catalog)."""
    if workshop is None:
        return []
    try:
        mods, _ = workshop.load()
        root = getattr(workshop, "dir", "")

        def published(m):
            try:
                return os.stat(os.path.join(root, "files", m["zip"])).st_mtime if m.get("zip") else 0.0
            except (OSError, TypeError):
                return 0.0
        return sorted(mods, key=lambda m: (-published(m), m["name"].lower()))[:n]
    except Exception:  # noqa: BLE001
        return []


def _right_now_items() -> list[dict]:
    items = []
    try:
        st = realm_status()
    except Exception:  # noqa: BLE001
        st = {}
    players = _nonneg(st.get("players")) if isinstance(st, dict) and st.get("online") else None
    if players:
        items.append({"kind": "players", "n": players})
    try:
        realms, ok = community_realms()
    except Exception:  # noqa: BLE001
        realms, ok = [], False
    live = sum(1 for r in realms if r.get("live")) if ok else 0
    if live:
        items.append({"kind": "realms", "n": live})
    mods = latest_mods(3)
    if mods:
        items.append({"kind": "mods", "list": [(m["name"], f'/wrath/mods/{m["id"]}') for m in mods]})
    if armory is not None:
        try:
            recent = armory.store.showcase()["recent80"][:3]
        except Exception:  # noqa: BLE001
            recent = []
        if recent:
            items.append({"kind": "eighties", "list": [(c["name"], f'/wrath/armory/{c["name"]}') for c in recent]})
    return items


def right_now(fresh: bool = False) -> tuple[list[dict], float]:
    """(items, when they were read): read at most once per RIGHT_NOW_TTL seconds."""
    with _right_now_lock:
        if not fresh and time.monotonic() - _right_now["at"] < RIGHT_NOW_TTL:
            return list(_right_now["items"]), _right_now["when"]
    items = _right_now_items()
    with _right_now_lock:
        _right_now.update(at=time.monotonic(), items=items, when=time.time())
    return list(items), _right_now["when"]


def right_now_html() -> str:
    """The "Right now" strip, or "" when there is nothing real to show."""
    e = html.escape
    items, when = right_now()
    lis = []
    for it in items:
        k = it["kind"]
        if k == "players":
            n = it["n"]
            lis.append(f'<li><span class="ly-dot" aria-hidden="true"></span><a class="all" href="/wrath/realms">'
                       f'<b>{n}</b> {"player" if n == 1 else "players"} on {e(REALM_NAME)}</a></li>')
        elif k == "realms":
            n = it["n"]
            lis.append(f'<li><span class="ly-dot" aria-hidden="true"></span><a class="all" href="/wrath/realms">'
                       f'<b>{n}</b> community {"realm" if n == 1 else "realms"} live</a></li>')
        else:
            label, more = (("Latest mods", "/wrath/mods") if k == "mods" else ("Recent level 80s", "/wrath/armory"))
            names = ", ".join(f'<a href="{e(href)}">{e(name)}</a>' for name, href in it["list"])
            lis.append(f'<li><a class="all" href="{more}">{label}:</a> {names}</li>')
    if not lis:
        return ""
    stamp = updated_text(when)
    return ('<section class="ly-now" aria-labelledby="ly-now-h"><h2 id="ly-now-h">Right now</h2>'
            f'<ul>{"".join(lis)}</ul>' + (f'<p>{stamp}. Bots are never counted as players.</p>' if stamp else "")
            + '</section>')


def remember_go(user: str, query: dict) -> None:
    """A signed-in player came with ?go=<kind>:<id>: record it for their game account on the realm
    ("ovgo set", realm/custom/lua_scripts/ov_go.lua), at most 20 a minute per account. Never fails the page."""
    if playmodes is not None and (query.get("go") or [""])[0][:40].startswith("mode:"):   # a game mode (stream/playmodes.py)
        mid = playmodes.go_mode((query.get("go") or [""])[0][:40])
        if mid and gate_limit.hit("go:" + user.upper(), 20):
            playmodes.go_intent(ac_soap, user, mid, log)
        return
    if modes is None or links is None:
        return
    v = (query.get("go") or [""])[0][:40]
    got = links.check_go(v) if v else None
    if got and got[0] == "r" and got[1] == hangout_id():
        got = ("h", "dalaran")   # a hop into the Dalaran Hangout (this realm through the relay) lands in Dalaran
    if got and got[0] == "w":   # a Workshop item (stream/creations.py, "ovws go", ov_workshop.lua)
        if creations is not None and gate_limit.hit("go:" + user.upper(), 20):
            creations.go_intent(ac_soap, user, got[1], log)
        return
    if not got or got[0] not in ("h", "q", "b") or not gate_limit.hit("go:" + user.upper(), 20):
        return
    modes.go_intent(ac_soap, user, links.go_value(*got), log)


def leyline_page() -> bytes:
    """/wrath/leyline: the Leyline network's own page, in its own look (the owner's emblem and nebula art,
    cyan and violet), with its features and aims in plain facts: what's live today, and what's planned (marked).
    The hero line under the title is the owner's own (from his mockup), trimmed to what's true today."""
    e = html.escape
    st = realm_status()
    rows = [(SAMPLER_NAME if SAMPLER else REALM_NAME,
             "Official · temporary · level 1 or boost to 80" if SAMPLER else "Official · level 1 or boost to 80", "PvE", _nonneg(st.get("players")), _nonneg(st.get("bots")),
             bool(st.get("online")), "/wrath")]
    realms, ok = community_realms()
    with _listing_lock:
        when = _listing["when"]
    stamps = [x for x in (updated_text(st.get("updated_at"), "Realm status"),
                          updated_text(when, "community list") if ok else "") if x]
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
    body = (
        '<header class="ly-hero">'
        + (spin(180, "ly-hero-mark") if BRAND else
           f'<img class="ly-emblem" src="{art_url("leyline-emblem.webp")}" alt="" width="300" height="248" '
           'decoding="async" fetchpriority="high">') +
        '<h1>Leyline</h1>'
        '<p class="ly-lede">An open-source, community-built MMO project. Play in your browser or a client, '
        'build and share mods, and host your own realm.</p>'
        '<span class="ly-ver">Alpha</span></header>'
        '<div class="ly-cta">'
        f'<a class="ly-btn" href="/wrath">{icon_play}Play now</a>'
        f'<a class="ly-btn" href="/wrath#desktop">{icon_rocket}Client launcher</a>'
        f'<a class="ly-btn violet" href="{e(HOST_URL)}" rel="noopener noreferrer">{icon_portal}Host realm</a>'
        '</div>'
        + right_now_html() +
        '<section class="ly-panel" aria-labelledby="ly-realms"><h2 id="ly-realms">Realm list</h2>'
        '<table class="ly-table"><thead><tr><th>Realm</th><th>Type</th><th>Players</th><th>Status</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
        + host_plus("leyline") +
        '<p class="ly-fine">Community realms run on their hosts\' own PCs and join through the Leyline relay. '
        '<a href="/wrath/realms">All realms and house rules</a>'
        + (f'<br>{" · ".join(stamps)}' if stamps else '') + '</p></section>'
        '<section class="ly-panel" aria-labelledby="ly-shots"><h2 id="ly-shots">See it running</h2><div class="ly-shots">'
        + shot("dalaran", "Dalaran hangout", "The flagship realm's meeting place, streamed into a browser tab.")
        + shot("start", "Your choice at the start", "Begin at level 1, or take a boost to 80 with gear, professions and a trip to Dalaran.")
        + shot("city", "Play with friends", "Group up, duel, and run dungeons where labelled bots fill the empty places.")
        + shot("durotar", "Every bar, ready", "A clean modern interface: every action bar on with common keys, sized to your screen.")
        + '</div><p class="ly-fine">Screenshots from the live browser client.</p></section>'
        '<section class="ly-panel" aria-labelledby="ly-what"><h2 id="ly-what">What Leyline does</h2><div class="ly-grid">'
        + feat("Play in the browser", f"No install: sign in with a Hero Key and play the flagship realm, {REALM_NAME}. "
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
        f'<a href="{e(LEYLINE_REPO)}" rel="noopener noreferrer">Source code</a></p>')
    meta = card_meta("/wrath/leyline", "Leyline · an open-source, community-built MMO project")
    return ly_shell("Leyline", body, "/wrath/leyline", "leyline", "play", meta=meta)


NOT_FOUND_CSS = """
a.ly-feat{display:block;text-decoration:none;color:inherit}
a.ly-feat:hover,a.ly-feat:focus-visible{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.ly .nf h1{font-size:clamp(44px,9vw,84px)}
"""


def not_found_page() -> bytes:
    """The 404 for any page this service doesn't have: the site nav and a way on to every main page."""
    e = html.escape

    def card(href, title, text, external=False):
        rel = ' rel="noopener noreferrer"' if external else ""
        return f'<a class="ly-feat" href="{e(href)}"{rel}><h3>{e(title)}</h3><p>{e(text)}</p></a>'
    cards = [card("/wrath", "Play now", "Straight into the game, in your browser."),
             card("/wrath/leyline", "Leyline", "The hub: what's live, who's on, and where it's going."),
             card("/wrath/realms", "Realms", "The official realm and every community realm.")]
    if modes is not None:
        cards.append(card("/wrath/modes", "Modes", "Duels, boss fights, dungeons and hangouts, one click each."))
    if workshop_mod is not None:
        cards.append(card("/wrath/mods", "Mods", "The Workshop: addons and realm scripts."))
    if armory is not None:
        cards.append(card("/wrath/armory", "Armory", "Look up any character on the realm."))
    cards += [card(HOST_URL, "Host a realm", "Run your own realm on your own PC.", True),
              card(DISCORD_URL, "Discord", "Ask for help, or tell us which link brought you here.", True)]
    body = ('<header class="ly-hero nf"><h1>Not found</h1>'
            '<p class="ly-lede">Nothing lives at this address. The link may be old or mistyped. Everything else is one click away.</p>'
            '</header><section class="ly-panel" aria-labelledby="nf-go"><h2 id="nf-go">Where to next</h2>'
            f'<div class="ly-grid">{"".join(cards)}</div></section>')
    return ly_shell(f"Not found · {REALM_NAME}", body, "/wrath/leyline", "", "play", NOT_FOUND_CSS, noindex=True)


def mods_who(cookie: str, ip: str, ua: str):
    """The Workshop's sign-in check: the /api/me answer, None when signed out; raises when the site is down."""
    if "wr_session=" not in cookie:
        return None
    status, me = portal_get("/api/me", cookie, ip, ua)
    if status in (401, 403) or 300 <= status < 400:
        return None
    if status != 200 or not me:
        raise OSError(f"api/me answered {status}")
    return me


workshop = None
if workshop_mod is not None:
    try:
        workshop = workshop_mod.Workshop(os.environ.get("WU_MODS_DIR", "/app/mods"), leyline_css, card_meta, REALM_NAME)
    except Exception:   # the rest of the portal must still start
        workshop = None
if workshop is not None and admin is not None:
    workshop.adjust = admin.adjust_catalog   # staff overrides: unpublished, featured, edited (stream/admin.py)


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
herokey_limit = _Window(3600)   # Hero Key sign-in assertions: 60 an hour per account
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


def status_with_gamedata(body: bytes) -> bytes:
    """The status document with the killswitch's state ("gamedata_streaming", "gamedata_since"), added per request
    (the SOAP part is cached 30 s; the switch shows at once). The launcher's BROWSER mode and the admin console read it."""
    try:
        doc = json.loads(body.decode("utf-8"))
    except ValueError:
        return body
    if not isinstance(doc, dict):
        return body
    doc.update(gamedata_state())
    return (json.dumps(doc, separators=(",", ":")) + "\n").encode("utf-8")


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
        body = brand_body(body, ctype)   # the Leyline brand switch (off: unchanged)
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
        self.send_header("Referrer-Policy", "same-origin")
        script = f"'nonce-{nonce}'" if nonce else "'none'"
        self.send_header("Content-Security-Policy",
                         f"default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self'; media-src 'self'; font-src 'self'; "
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
        if (name in GAMEDATA_ART or home_art(name)) and gamedata_off():
            self.send(410, GAMEDATA_GONE, "application/json; charset=utf-8")
            return
        body = art_bytes(name)
        if body is None:
            self.send(404, b"not found\n", "text/plain")
            return
        # one byte range (bytes=a-b, a-, -n) for the videos, so a browser can seek and Safari plays them at all;
        # anything else gets the whole file
        status, total = 200, len(body)
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        if m and art_type(name).startswith("video/") and (m.group(1) or m.group(2)):
            a, b = m.group(1), m.group(2)
            start, end = (total - min(int(b), total), total - 1) if not a else (int(a), min(int(b), total - 1) if b else total - 1)
            if start >= total or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status, body = 206, body[start:end + 1]
        self.send_response(status)
        self.send_header("Content-Type", art_type(name))
        self.send_header("Content-Length", str(len(body)))
        if art_type(name).startswith("video/"):
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        age = (ART_MAX_AGE if name in ART_TYPES else HOME_JSON_MAX_AGE if name == HOME_JSON
               else HOME_ART_MAX_AGE if home_art(name) else 86400)
        self.send_header("Cache-Control", f"public, max-age={age}")
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
        self.send_header("Referrer-Policy", "same-origin")
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
        layers.take(user)
        try:
            realm_clear(user)
        except SoapError as e:
            if stream_on():
                log.error("own: clear %s failed: %s %s", user.upper(), e.kind, e.detail[:160])
                self.send(503, error_page("The realm isn't answering right now. Please try again shortly."))
                return
        code = sessions.create(user, password, OWN, 0, mode=OWN)
        log.info("own-files session for %s", user.upper())
        self.redirect(f"https://{STREAM_HOST}/__gate?code={urllib.parse.quote(code)}{go_param(query or {})}")

    def stream_play(self, query: dict) -> None:
        """GET /wrath/play?mini=<slug> on play.openvanilla.app (?mode=own: own_play)."""
        if (query.get("mode") or [""])[0] == OWN:
            self.own_play(query)
            return
        if gamedata_off():
            # The game data killswitch: no streamed slice; the browser client runs on the player's own folder.
            if ownfiles_on():
                self.own_play(query)
            else:
                self.send(200, gamedata_off_page())
            return
        if not stream_on():
            self.send(200, stream_off_page())
            return
        ip = self.ip()
        if not gate_limit.hit("play:" + ip, 30):
            self.send(429, busy_page())
            return
        slug = (query.get("mini") or ["mini"])[0]
        if slug == "mini":
            slug = PLAY_SLICE
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
        layers.take(user)   # a new stream play: marked again above; a page with the folder lifts it again
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
        layers.take(user)
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
        hop = hop_for(query) if sess.get("mode") in ("stream", OWN) else None
        if hop:
            sessions.set_hop(sid, hop)
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
        if gamedata_off() and (uri.startswith("/data") or uri.split("?")[0] in ("/boot-manifest.json", "/world-manifest.json")):
            # The game data killswitch: gone for everyone, whatever the session (Caddy copies this answer).
            self.send(410, GAMEDATA_GONE, "application/json; charset=utf-8", same_origin=True)
            return
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

    def json_reply(self, status: int, doc: dict) -> None:
        self.send(status, (json.dumps(doc, separators=(",", ":")) + "\n").encode(), "application/json; charset=utf-8",
                  same_origin=True)

    def stream_layer(self, query: dict) -> None:
        """POST /__gate?layer=on|off|beat on the stream site: the game-folder layer (see the module doc)."""
        op = (query.get("layer") or [""])[0]
        if op not in ("on", "off", "beat"):
            self.json_reply(400, {"ok": False, "state": "unknown", "why": "layer=on|off|beat"})
            return
        if not gate_limit.hit("layer:" + self.ip(), 40):
            self.json_reply(429, {"ok": False, "state": "unknown", "why": "too many requests"})
            return
        if self.headers.get("Origin", "") != f"https://{STREAM_HOST}":
            self.json_reply(403, {"ok": False, "state": "unknown", "why": "same-origin only"})
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self.json_reply(415, {"ok": False, "state": "unknown", "why": "JSON only"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > 2048:
            self.json_reply(413, {"ok": False, "state": "unknown", "why": "too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        sid = cookie_value(self.headers.get("Cookie", ""), "wu_play")
        sess = self.stream_session()
        if not sess or sess.get("mode") != "stream" or sess.get("hop"):
            self.json_reply(403, {"ok": False, "state": "n/a", "why": "not a streamed session"})
            return
        if not stream_on():
            self.json_reply(503, {"ok": False, "state": "off", "why": "streaming is off"})
            return
        user = sess["user"]
        if op == "off":
            lease = layers.take(user)
            if not lease:
                self.json_reply(200, {"ok": True, "state": "held"})
                return
            try:
                layer_mark(user, {**lease, "slice": sess["slice"], "tier": sess["tier"], "sess_exp": sess["exp"]})
            except SoapError as e:
                log.error("layer off: mark %s failed: %s %s", user, e.kind, e.detail[:160])
                layers.put_back(user, lease)   # the sweeper tries again
                self.json_reply(503, {"ok": False, "state": "failed", "why": "the realm is not answering"})
                return
            log.info("layer off for %s: held to the stream again", user)
            self.json_reply(200, {"ok": True, "state": "held"})
            return
        if op == "beat" and layers.renew(user):
            self.json_reply(200, {"ok": True, "state": "lifted"})
            return
        if op == "beat":
            self.json_reply(409, {"ok": False, "state": "held", "why": "no lease: ask again with layer=on"})
            return
        build = body.get("build")
        if build is not None and build != LAYER_BUILD:
            self.json_reply(400, {"ok": False, "state": "held", "why": "this realm needs a 3.3.5a (12340) game folder"})
            return
        try:
            realm_clear(user)
        except SoapError as e:
            log.error("layer on: clear %s failed: %s %s", user, e.kind, e.detail[:160])
            self.json_reply(503, {"ok": False, "state": "held", "why": "the realm is not answering"})
            return
        layers.lift(user, sid, sess)
        log.info("layer on for %s: the whole world (own game folder)", user)
        self.json_reply(200, {"ok": True, "state": "lifted", "lease": LAYER_LEASE})

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
            self.send(200, site_chrome(guest.preview(), path))
            return
        if self.command == "HEAD":
            self.send(200, b"")
            return
        kind, *rest = guest.start(ip)
        if kind == "redirect":
            self.redirect(rest[0])
        else:
            self.send(rest[0], site_chrome(rest[1], path) if isinstance(rest[1], bytes) else rest[1])

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def mods_req(self, method: str, form: dict | None = None) -> dict:
        """What the Workshop needs to know who is signed in (stream/workshop.py serve)."""
        return {"method": method, "cookie": self.headers.get("Cookie", ""), "ip": self.ip(),
                "ua": self.headers.get("User-Agent", ""), "form": form or {}, "who": mods_who}

    def do_POST(self):  # noqa: N802
        # The Workshop's posts (add a link, report one, hide one: stream/workshop.py), the host flow, and the
        # stream site's game-folder layer (POST /__gate?layer=..., /__layer for a Caddyfile that routes it).
        split = urllib.parse.urlsplit(self.path)
        path = split.path.rstrip("/") or "/"
        if path in ("/__gate", "/__layer"):
            self.stream_layer(urllib.parse.parse_qs(split.query))
            return
        if profiles is not None and profiles.match(path):   # the profile forms (stream/profiles.py)
            profiles.post(self, path)
            return
        if social is not None and social.match(path):   # Leyline friends and messages (stream/social.py)
            social.post(self, path)
            return
        if forum is not None and forum.match(path):   # the forum's forms (stream/forum.py)
            forum.post(self, path)
            return
        if hub_rank is not None and hub_rank.match(path):   # POST /wrath/api/hub/install|rate (stream/hub_rank.py)
            hub_rank.post(self, path)
            return
        if hostflow is not None and hostflow.match(path):   # POST /wrath/host: make a realm (stream/hostflow.py)
            hostflow.post(self, path)
            return
        if admin is not None and admin.match(path):   # POST /wrath/admin/act: the Admin Console (stream/admin.py)
            admin.post(self, path)
        if network is not None and network.match(path):   # POST /wrath/realms/report (stream/network.py)
            network.post(self, path)
            return
        if hub_mod is not None and hub_mod.match(path):   # POST /wrath/leyline-preview/submit (stream/hub.py)
            hub_mod.post(self, path)
            return
        if workshop is None or not workshop_mod.match(path):
            self.send(405, b"method not allowed\n", "text/plain")
            return
        if not browse_limit.hit(self.ip() + "|post", 30):
            self.send(429, busy_page(back="/wrath/mods"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > workshop_mod.MAX_FORM:
            self.send(413, b"too large\n", "text/plain")
            return
        form = workshop_mod.parse_form(self.rfile.read(length))
        status, body, ctype, extra = workshop.serve(path, {}, self.mods_req("POST", form))
        if ctype.startswith("text/html"):
            body = site_chrome(body, path)
        self.send(status, body, ctype, headers=extra)

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
            self.send(200, status_with_gamedata(status_json()), "application/json; charset=utf-8", public=True)
            return
        if path == "/wrath/healthz":
            ok, kind = health()
            self.send(200 if ok else 503, b"ok\n" if ok else f"soap {kind}\n".encode(), "text/plain")
            return
        if path.startswith("/wrath/art/"):
            self.art(urllib.parse.unquote(path[len("/wrath/art/"):]))
            return
        if forum is not None and forum.match(path):   # the forum and its JSON (stream/forum.py)
            forum.get(self, path, query)
            return
        if profiles is not None and profiles.match(path):   # sign-in, profile and pictures (stream/profiles.py)
            profiles.get(self, path, query)
            return
        twin = hub_mod.twin(path, query) if hub_mod is not None and hasattr(hub_mod, "twin") else None
        if twin:   # an older page with a twin on the Leyline front door (stream/hub.py TWINS): one site, one page each
            self.send_response(301)
            self.send_header("Location", twin)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            return
        if path == "/wrath/leyline/herokey.json":   # the Hero Key sign-in public key (only with herokey_sso on)
            got = herokey_public()
            if got:
                self.send(got[0], got[1], got[2], public=True)
                return
        if leyline_net is not None and path.startswith("/wrath/leyline/"):   # flags.json, hostpack.json
            got = leyline_net.serve(path)
            if got:
                self.send(got[0], got[1], got[2], public=True)
                return
        if admin is not None and admin.match(path):   # /wrath/admin and the /wrath/leyline/*.json feeds (stream/admin.py)
            admin.get(self, path, query)
        if hub_rank is not None and hub_rank.match(path):   # /wrath/leyline/mods.json, /wrath/api/hub/me (stream/hub_rank.py)
            hub_rank.get(self, path, query)
            return
        if hub_mod is not None and hub_mod.match(path):   # the hidden Leyline hub and its launcher feed (stream/hub.py)
            hub_mod.get(self, path, query)
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
            self.send(status, site_chrome(body, path))
            return
        if links is not None and links.match(path):   # share links (stream/links.py), same limit as /wrath/leyline
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            key = nav_key(path)
            self.send(200, links.share_page(path, card_meta, lambda body, **kw: render(body, current=key, **kw),
                                            REALM_NAME, community_realms,
                                            who=armory.card_line if armory is not None else None,
                                            mods=workshop.mod if workshop else None,
                                            made=creations.card_item if creations is not None else None))
            return
        if path == "/wrath/modes" and modes is not None:
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            self.send(200, site_chrome(modes.page(leyline_css(), art_url, art_present, card_meta, REALM_NAME,
                                                  public_host=PUBLIC_HOST,
                                                  games=playmodes.section() if playmodes is not None else ""), path))
            return
        if path == "/wrath/modes.json" and playmodes is not None:   # the game modes catalog (stream/playmodes.py)
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, b'{"error":"busy"}', "application/json; charset=utf-8")
                return
            self.send(200, playmodes.json_bytes(), "application/json; charset=utf-8", public=True)
            return
        if workshop is not None and workshop_mod.match(path):   # the mods Workshop (stream/workshop.py)
            dl = "/download" in path
            if not browse_limit.hit(self.ip() + ("|dl" if dl else ""), 30 if dl else 600):
                self.send(429, busy_page(back=path))
                return
            status, body, ctype, extra = workshop.serve(path, query, self.mods_req("GET"))
            if path == "/wrath/mods/all.json" and status == 200 and leyline_net is not None:
                body = leyline_net.add_hostpack(body)   # the Host pack as a "tools" project (stream/leyline_net.py)
            if ctype.startswith("text/html"):
                body = site_chrome(body, path)
            self.send(status, body, ctype, headers=extra)
            return
        if creations is not None and creations.match(path):   # the Workshop of player creations (stream/creations.py)
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            status, body = creations.page(path, query, leyline_css(), card_meta, REALM_NAME, PUBLIC_HOST)
            self.send(status, site_chrome(body, path))
            return
        if docs is not None and docs.match(path):   # the Leyline docs (stream/docs.py)
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            status, body = docs.page(path, leyline_css(), card_meta, REALM_NAME)
            self.send(status, site_chrome(body, path))
            return
        if hostflow is not None and hostflow.match(path):   # "+ Your server" (stream/hostflow.py)
            hostflow.get(self, path)
            return
        if social is not None and social.match(path):   # Leyline friends and messages (stream/social.py)
            social.get(self, path, query)
            return
        if network is not None and network.match(path):   # /wrath/realms.json, /wrath/realms/report (stream/network.py)
            network.get(self, path, query)
            return
        if path == "/wrath/realms":
            if not browse_limit.hit(self.ip(), 600):
                self.send(429, busy_page(back=path))
                return
            self.send(200, realms_page(query))
            return
        if path == "/wrath/demo" or (path == "/wrath" and (query.get("demo") or [""])[0] == "1"):
            self.demo(path)
            return
        if path not in ("/wrath", "/wrath/account"):
            self.send(404, not_found_page())
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


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer with a real listen backlog. The default (5) made Caddy's burst of
    forward_auth checks overflow it whenever the game opened dozens of /data requests at once:
    the extra connections were dropped and retried by TCP after 1 s and 3 s, which was most of
    the time a streamed load spent waiting on game files."""
    request_queue_size = 1024
    daemon_threads = True


def main() -> int:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not SOAP_USER or not SOAP_PASS:
        log.error("SOAP_USER and SOAP_PASS must be set (/srv/wrath/portal.env)")
        return 2
    bridge = Server(("0.0.0.0", BRIDGE_PORT), BridgeHandler)
    bridge.daemon_threads = True
    threading.Thread(target=bridge.serve_forever, daemon=True).start()
    page = Server(("0.0.0.0", PAGE_PORT), PageHandler)
    page.daemon_threads = True
    log.info("page :%d, bridge :%d, ac soap %s, portal %s", PAGE_PORT, BRIDGE_PORT, AC_SOAP_URL, PORTAL_URL)
    if guest:
        guest.start_thread()
    threading.Thread(target=_layer_sweeper, daemon=True, name="layer-sweeper").start()
    if social is not None:
        social.setup()   # the store in /data and the realm bridge thread (stream/social.py)
    if profiles is not None:
        profiles.setup()   # the profiles' store in /data (stream/profiles.py)
    if forum is not None:
        forum.setup()   # the forum's store in /data (stream/forum.py)
    try:
        page.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
