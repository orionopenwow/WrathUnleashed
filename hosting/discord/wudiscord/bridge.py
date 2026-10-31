"""Leyline Discord bridge (stdlib only, Python 3.10+).

    python3 -m wudiscord.bridge          (PYTHONPATH=hosting/discord; settings from the environment only)
    python3 -m wudiscord.bridge --check [--env-file F]  (settings only, no network; exit 2 and the reasons if incomplete)

Two-way bridge between the Wrath realm's World chat channel and one Discord channel, plus a bug-report feed:

  game -> Discord   realm/custom/lua_scripts/ov_discord.lua queues World channel lines; every WU_DISCORD_POLL seconds
                    this daemon runs "wudiscord pull <seq> <bug-id>" over AzerothCore SOAP and posts them to
                    DISCORD_CHAT_CHANNEL_ID as "[Name]: text" (several lines per Discord message when busy).
  Discord -> game   it reads DISCORD_CHAT_CHANNEL_ID with the bot token (REST, messages after the last one seen) and
                    runs "wudiscord say <hex name> <hex text>": players see "[Discord] Name: text".
  bug feed          .bug reports (ov_bug_reports) newer than the last one posted go to DISCORD_BUG_CHANNEL_ID.

Safety: nothing ever pings (allowed_mentions parse=[] on every post, and @everyone / @here / <@...> are defused in the
text too); Discord markdown in game text is escaped; links from the game are dropped unless their host is in
WU_DISCORD_LINK_ALLOW; length caps and rate limits both ways; bot and webhook messages (this bot's own included) are
skipped; a mute list (WU_DISCORD_MUTE and WU_DISCORD_MUTE_FILE: Discord user ids or character names) works both ways.
The token is read from DISCORD_BOT_TOKEN, sent only in the Authorization header, and never logged (a log filter
blanks it should it ever appear in a message).

Environment:
  DISCORD_BOT_TOKEN          required. The bot needs the Message Content intent (Developer Portal > Bot) and, in the
                             channels, View Channel + Read Message History + Send Messages.
  DISCORD_CHAT_CHANNEL_ID    required. The channel bridged with World chat.
  DISCORD_BUG_CHANNEL_ID     optional. The bug-report feed (off when empty).
  SOAP_URL                   default http://127.0.0.1:7878/ (AC_SOAP_URL is read too, like the portal)
  SOAP_USER, SOAP_PASS       a GM level 3 account (the signup service's WUSOAP works)
  WU_DISCORD_LINK_ALLOW      hosts whose links may go from the game to Discord, comma-separated (subdomains included)
  WU_DISCORD_MUTE            Discord user ids and/or character names, comma-separated
  WU_DISCORD_MUTE_FILE       the same, one per line (# comments), re-read when it changes
  WU_DISCORD_POLL            seconds between rounds (default 3)
  WU_DISCORD_STATE           where the last message / report ids are kept (default /var/lib/wu-discord/state.json)
  WU_DISCORD_API             default https://discord.com/api/v10 (tests point it elsewhere)
  WU_DISCORD_DRY_RUN         1 = log what would be posted / said, touch neither Discord nor the realm
  WU_SITE_URL                the site named in the User-Agent Discord asks for (default https://play.openvanilla.app)
  LOG_LEVEL                  default INFO

New-realm announcements (OFF by default; the owner's choice to turn on). Our rule is that humans share Discord links;
an automated post is a different thing, so this stays off unless the owner sets WU_DISCORD_ANNOUNCE_REALMS=1. When on,
every WU_DISCORD_ANNOUNCE_EVERY seconds it reads the site's realm list and posts one line per realm that is public,
live, claimed by a Hero Key account, whose name passed the word filter (community.nameOk), and that has been listed for
ANNOUNCE_GRACE seconds at least: "New realm listed: <name> — <link>". Each realm once (its id is kept in the state
file); on the first run every realm already listed is marked as seen, so turning it on never floods the channel.
  WU_DISCORD_ANNOUNCE_REALMS 1 = on (default 0, off)
  DISCORD_ANNOUNCE_CHANNEL_ID  where the lines go (default: DISCORD_CHAT_CHANNEL_ID)
  WU_DISCORD_REALMS_URL      the realm list (default <WU_SITE_URL>/wrath/realms.json)
  WU_DISCORD_ANNOUNCE_EVERY  seconds between looks (default 300, at least 60)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

log = logging.getLogger("wu-discord")

USER_AGENT = "DiscordBot (" + os.environ.get("WU_SITE_URL", "https://play.openvanilla.app") + ", 1) leyline-bridge"
DISCORD_MAX = 2000         # Discord's message length
GAME_TEXT_MAX = 200        # Discord -> game, per line (ov_discord.lua caps again)
NAME_MAX = 24
CHAT_LINE_MAX = 300        # game -> Discord, per line
BUG_TEXT_MAX = 600
QUEUE_MAX = 60             # game lines waiting for Discord; older ones are dropped when Discord is slow
POSTS_PER_WINDOW, POST_WINDOW = 4, 5.0         # Discord allows 5 per 5 s per channel; stay under
USER_MAX, USER_WINDOW = 4, 20.0                # Discord -> game: per Discord user
GAME_SAY_MAX, GAME_SAY_WINDOW = 20, 60.0       # Discord -> game: everyone together
PLAYER_MAX, PLAYER_WINDOW = 5, 30.0            # game -> Discord: per character (the Lua has its own cap too)
ANNOUNCE_GRACE = 600       # a realm is announced only after this long on the list (the hub's "New realm" waits as long)
ANNOUNCE_MAX = 2000        # realm ids remembered as announced
ANNOUNCE_PER_ROUND = 3
RID_RE = re.compile(r"^[a-z2-7]{16}$")
# Shown to players in game: the rule is that players never see these names; masked in Discord -> game text.
GAME_BRAND_WORDS = re.compile(r"(?i)world\s+of\s+warcraft|\bwarcraft\b|\bwow\b|lich\s+king|\bblizzard\b")


# -------------------------------------------------------------------------------------------------------------------
# text: game -> Discord
# -------------------------------------------------------------------------------------------------------------------

_GAME_LINK = re.compile(r"\|H[^|]*\|h(.*?)\|h", re.S)        # |Hitem:...|h[Frostmourne]|h -> [Frostmourne]
_GAME_COLOR = re.compile(r"\|c[0-9a-fA-F]{8}|\|r")
_GAME_TEXTURE = re.compile(r"\|T[^|]*\|t")
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁦-⁩]")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b(?:[a-z0-9-]+\.)+[a-z]{2,24}(?::\d+)?(?:/\S*)?")
_MD = re.compile(r"([\\*_~`|>#\[\]()<:-])")
ZWSP = "​"


def strip_game_markup(s: str) -> str:
    s = _GAME_LINK.sub(r"\1", s)
    s = _GAME_TEXTURE.sub("", s)
    s = _GAME_COLOR.sub("", s)
    return s.replace("||", "|")


def _host_of(url: str) -> str:
    u = url if "://" in url else "http://" + url
    try:
        return (urllib.parse.urlsplit(u).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def link_allowed(url: str, allow: set[str]) -> bool:
    h = _host_of(url)
    return bool(h) and any(h == a or h.endswith("." + a) for a in allow)


def defuse_mentions(s: str) -> str:
    """No pings even if allowed_mentions were ever lost: @everyone/@here broken, <@..> <@&..> <#..> taken apart."""
    s = re.sub(r"@(everyone|here)", "@" + ZWSP + r"\1", s, flags=re.I)
    return re.sub(r"<(@[!&]?|#)(\d+)>", lambda m: m.group(1).replace("@", "@" + ZWSP) + m.group(2), s)


def escape_md(s: str) -> str:
    return _MD.sub(r"\\\1", s)


def clean_for_discord(text: str, allow: set[str], cap: int = CHAT_LINE_MAX) -> str:
    """One line of game text, safe to post: markup out, links dropped unless allow-listed, markdown escaped."""
    s = _CONTROL.sub(" ", strip_game_markup(text))
    s = re.sub(r"\s+", " ", s).strip()
    out, pos = [], 0
    esc = lambda t: escape_md(defuse_mentions(t))
    for m in _URL.finditer(s):
        out.append(esc(s[pos:m.start()]))
        url = m.group(0).rstrip(".,!?;)")
        tail = m.group(0)[len(url):]
        if link_allowed(url, allow):
            out.append("<" + (url if "://" in url else "https://" + url) + ">")   # <...>: no embed preview
        else:
            out.append("[link removed]")
        out.append(esc(tail))
        pos = m.end()
    out.append(esc(s[pos:]))
    s = "".join(out)
    if len(s) > cap:
        s = s[:cap - 1].rstrip("\\") + "…"
    return s


def chat_line(name: str, text: str, allow: set[str]) -> str:
    return f"[{escape_md(_CONTROL.sub('', name))[:NAME_MAX * 2]}]: {clean_for_discord(text, allow)}"


def bug_post(bug: dict, allow: set[str]) -> str:
    who = escape_md(_CONTROL.sub("", bug["name"]))
    head = f"**Bug #{bug['id']}** from {who} (level {bug['level']}, map {bug['map']}, zone {bug['zone']})"
    return head + "\n> " + clean_for_discord(bug["text"], allow, BUG_TEXT_MAX)


def pack(lines: list[str], limit: int = DISCORD_MAX) -> list[str]:
    """Lines joined into as few Discord messages as fit."""
    msgs, cur = [], ""
    for ln in lines:
        ln = ln[:limit]
        if cur and len(cur) + 1 + len(ln) > limit:
            msgs.append(cur); cur = ln
        else:
            cur = ln if not cur else cur + "\n" + ln
    if cur:
        msgs.append(cur)
    return msgs


# -------------------------------------------------------------------------------------------------------------------
# text: Discord -> game
# -------------------------------------------------------------------------------------------------------------------

def clean_for_game(msg: dict) -> str:
    """A Discord message as one plain line for the game: mentions resolved or removed, no pings, no markup."""
    s = msg.get("content") or ""
    users = {}
    for u in msg.get("mentions") or []:
        nick = ((u.get("member") or {}).get("nick")) or u.get("global_name") or u.get("username") or "someone"
        users[str(u.get("id"))] = nick
    s = re.sub(r"<@!?(\d+)>", lambda m: "@" + users.get(m.group(1), "someone"), s)
    s = re.sub(r"<@&\d+>", "", s)                                   # role mentions: dropped
    s = re.sub(r"<#\d+>", "#channel", s)
    s = re.sub(r"<a?:(\w{1,32}):\d+>", r":\1:", s)                  # custom emoji
    s = re.sub(r"<t:(\d+)(?::\w)?>", "(a time)", s)
    s = re.sub(r"@(everyone|here)\b", "", s, flags=re.I)
    s = re.sub(r"(\*\*|__|~~|\|\||`+)", "", s)                        # bold / underline / strike / spoiler / code
    if msg.get("attachments"):
        s += " [attachment]"
    if msg.get("sticker_items"):
        s += " [sticker]"
    s = _CONTROL.sub(" ", s)
    s = GAME_BRAND_WORDS.sub("***", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:GAME_TEXT_MAX]


def display_name(msg: dict) -> str:
    a = msg.get("author") or {}
    n = ((msg.get("member") or {}).get("nick")) or a.get("global_name") or a.get("username") or "someone"
    n = GAME_BRAND_WORDS.sub("***", _CONTROL.sub("", n)).strip()
    return n[:NAME_MAX] or "someone"


# -------------------------------------------------------------------------------------------------------------------
# rate limits, mute list, config, state
# -------------------------------------------------------------------------------------------------------------------

class Window:
    """At most `limit` events per `secs` for each key."""

    def __init__(self, limit: int, secs: float, clock=time.monotonic):
        self.limit, self.secs, self.clock, self.seen = limit, secs, clock, {}

    def allow(self, key="") -> bool:
        t = self.clock()
        kept = [x for x in self.seen.get(key, []) if t - x < self.secs]
        if len(kept) >= self.limit:
            self.seen[key] = kept
            return False
        kept.append(t)
        self.seen[key] = kept
        return True


class Mutes:
    def __init__(self, env_list: str = "", path: str = ""):
        self.fixed = {x.strip().lower() for x in env_list.split(",") if x.strip()}
        self.path, self.mtime, self.from_file = path, None, set()

    def _reload(self):
        if not self.path:
            return
        try:
            m = os.stat(self.path).st_mtime
        except OSError:
            self.from_file, self.mtime = set(), None
            return
        if m == self.mtime:
            return
        self.mtime = m
        with open(self.path, encoding="utf-8") as f:
            self.from_file = {ln.split("#", 1)[0].strip().lower() for ln in f} - {""}

    def muted(self, *keys) -> bool:
        self._reload()
        names = self.fixed | self.from_file
        return any(k and str(k).strip().lower() in names for k in keys)


class Config:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.token = env.get("DISCORD_BOT_TOKEN", "").strip()
        self.chat_channel = env.get("DISCORD_CHAT_CHANNEL_ID", "").strip()
        self.bug_channel = env.get("DISCORD_BUG_CHANNEL_ID", "").strip()
        self.soap_url = env.get("SOAP_URL") or env.get("AC_SOAP_URL") or "http://127.0.0.1:7878/"
        self.soap_user = env.get("SOAP_USER", "")
        self.soap_pass = env.get("SOAP_PASS", "")
        self.link_allow = {h.strip().lower().lstrip(".") for h in env.get("WU_DISCORD_LINK_ALLOW", "").split(",") if h.strip()}
        self.mutes = Mutes(env.get("WU_DISCORD_MUTE", ""), env.get("WU_DISCORD_MUTE_FILE", ""))
        self.poll = max(1.0, float(env.get("WU_DISCORD_POLL", "3") or 3))
        self.state_path = env.get("WU_DISCORD_STATE", "/var/lib/wu-discord/state.json")
        self.api = env.get("WU_DISCORD_API", "https://discord.com/api/v10").rstrip("/")
        self.dry_run = env.get("WU_DISCORD_DRY_RUN", "0") == "1"
        site = env.get("WU_SITE_URL", "https://play.openvanilla.app").rstrip("/")
        self.site = site
        self.announce = env.get("WU_DISCORD_ANNOUNCE_REALMS", "0").strip() == "1"   # off unless the owner turns it on
        self.announce_channel = env.get("DISCORD_ANNOUNCE_CHANNEL_ID", "").strip() or self.chat_channel
        self.realms_url = env.get("WU_DISCORD_REALMS_URL", "").strip() or site + "/wrath/realms.json"
        self.announce_every = max(60.0, float(env.get("WU_DISCORD_ANNOUNCE_EVERY", "300") or 300))

    def problems(self) -> list[str]:
        p = []
        if not self.token:
            p.append("DISCORD_BOT_TOKEN is not set")
        if not self.chat_channel.isdigit():
            p.append("DISCORD_CHAT_CHANNEL_ID is not set (a channel id: digits)")
        if self.announce and not self.announce_channel.isdigit():
            p.append("DISCORD_ANNOUNCE_CHANNEL_ID must be a channel id (digits)")
        if self.announce and not self.realms_url.startswith("https://") and not self.realms_url.startswith("http://127.0.0.1"):
            p.append("WU_DISCORD_REALMS_URL must be an https address")
        if self.bug_channel and not self.bug_channel.isdigit():
            p.append("DISCORD_BUG_CHANNEL_ID must be a channel id (digits) or empty")
        if not self.soap_user or not self.soap_pass:
            p.append("SOAP_USER / SOAP_PASS are not set")
        return p

    def __repr__(self):  # never the token or the SOAP password
        return (f"Config(chat={self.chat_channel}, bugs={self.bug_channel or '-'}, soap={self.soap_url}, "
                f"soap_user={self.soap_user}, links={sorted(self.link_allow)}, poll={self.poll}, "
                f"announce={'on ' + self.announce_channel if self.announce else 'off'})")


class State:
    def __init__(self, path: str):
        self.path = path
        self.data = {"discord_after": None, "bug_after": None, "boot": None, "seq": 0, "announced": None}
        try:
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not save state to %s: %s", self.path, e.strerror)


class SecretFilter(logging.Filter):
    """Blanks the given secrets in every log record (belt and braces: nothing logs them on purpose)."""

    def __init__(self, *secrets):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record):
        msg = record.getMessage()
        if any(s in msg for s in self.secrets):
            for s in self.secrets:
                msg = msg.replace(s, "[redacted]")
            record.msg, record.args = msg, ()
        return True


# -------------------------------------------------------------------------------------------------------------------
# transports (both take `urlopen` so the tests can run without a network)
# -------------------------------------------------------------------------------------------------------------------

class TransportError(Exception):
    """kind: 'auth', 'down', 'fault', 'forbidden', 'notfound'. Never carries the token."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind, self.detail = kind, detail


class Discord:
    def __init__(self, token: str, api: str, urlopen=urllib.request.urlopen, sleep=time.sleep):
        self._token, self.api, self._open, self._sleep = token, api, urlopen, sleep

    def __repr__(self):
        return f"Discord(api={self.api})"

    def _call(self, method: str, path: str, body=None, tries: int = 3):
        data = json.dumps(body).encode() if body is not None else None
        for _ in range(tries):
            req = urllib.request.Request(self.api + path, data=data, method=method, headers={
                "Authorization": "Bot " + self._token, "User-Agent": USER_AGENT,
                "Content-Type": "application/json"})
            try:
                with self._open(req, timeout=15) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    try:
                        wait = float(json.loads(e.read() or b"{}").get("retry_after", 1))
                    except (ValueError, AttributeError):
                        wait = 1.0
                    log.info("Discord rate limit: waiting %.1f s", wait)
                    self._sleep(min(max(wait, 0.1), 30))
                    continue
                kind = {401: "auth", 403: "forbidden", 404: "notfound"}.get(e.code, "fault")
                raise TransportError(kind, f"HTTP {e.code} on {method} {path.split('?')[0]}") from None
            except (urllib.error.URLError, socket.timeout, OSError) as e:
                raise TransportError("down", type(e).__name__) from None
        raise TransportError("fault", "still rate limited")

    def me(self) -> dict:
        return self._call("GET", "/users/@me")

    def messages_after(self, channel: str, after: str | None, limit: int = 50) -> list[dict]:
        q = {"limit": str(limit)}
        if after:
            q["after"] = after
        out = self._call("GET", f"/channels/{channel}/messages?" + urllib.parse.urlencode(q)) or []
        return sorted(out, key=lambda m: int(m["id"]))

    def latest_id(self, channel: str) -> str:
        last = self._call("GET", f"/channels/{channel}/messages?limit=1") or []
        return str(last[0]["id"]) if last else "0"

    def post(self, channel: str, content: str) -> dict:
        return self._call("POST", f"/channels/{channel}/messages", {
            "content": content[:DISCORD_MAX], "allowed_mentions": {"parse": []}, "flags": 4})  # 4 = no link embeds


class Soap:
    def __init__(self, url: str, user: str, password: str, urlopen=urllib.request.urlopen):
        self.url, self._user, self._pass, self._open = url, user, password, urlopen

    def __repr__(self):
        return f"Soap(url={self.url}, user={self._user})"

    def command(self, command: str) -> str:
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">'
                f"<SOAP-ENV:Body><ns1:executeCommand><command>{xml_escape(command)}</command>"
                "</ns1:executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>").encode()
        auth = base64.b64encode(f"{self._user}:{self._pass}".encode()).decode()
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"urn:AC#executeCommand"',
            "Authorization": "Basic " + auth})
        try:
            with self._open(req, timeout=15) as r:
                return _tag_text(r.read(), "result")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise TransportError("auth", f"SOAP HTTP {e.code}") from None
            raise TransportError("fault", _tag_text(e.read(), "faultstring") or f"SOAP HTTP {e.code}") from None
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise TransportError("down", type(e).__name__) from None


def _tag_text(body: bytes, tag: str) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            return el.text
    return ""


def _unhex(h: str) -> str:
    return bytes.fromhex(h).decode("utf-8", "replace")


def parse_pull(text: str):
    """The answer to "wudiscord pull": (boot, seq, chat lines, bug reports), or None if it is not one."""
    lines = [ln.strip() for ln in (text or "").replace("\r", "").split("\n") if ln.strip()]
    head = next((i for i, ln in enumerate(lines) if ln.startswith("wudiscord ok ")), None)
    if head is None:
        return None
    parts = lines[head].split()
    try:
        boot, seq = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        return None
    chats, bugs = [], []
    for ln in lines[head + 1:]:
        p = ln.split(" ")
        try:
            if p[0] == "C" and len(p) == 4:
                chats.append({"seq": int(p[1]), "name": _unhex(p[2]), "text": _unhex(p[3])})
            elif p[0] == "B" and len(p) == 7:
                bugs.append({"id": int(p[1]), "name": _unhex(p[2]), "level": int(p[3]), "map": int(p[4]),
                             "zone": int(p[5]), "text": _unhex(p[6])})
        except ValueError:
            continue
    return boot, seq, chats, bugs


# -------------------------------------------------------------------------------------------------------------------
# new-realm announcements (off by default)
# -------------------------------------------------------------------------------------------------------------------

def _iso(v) -> float | None:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v):
        return None
    try:
        import calendar
        return float(calendar.timegm(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, OverflowError):
        return None


def announceable(rec, now: float) -> str | None:
    """The realm id when this realm-list record may be announced, else None: a community realm (never ours), live,
    claimed, its name passed the word filter, listed for ANNOUNCE_GRACE at least."""
    if not isinstance(rec, dict) or rec.get("official") or rec.get("state") != "live":
        return None
    com = rec.get("community") if isinstance(rec.get("community"), dict) else {}
    rid = com.get("realmId")
    if not isinstance(rid, str) or not RID_RE.match(rid) or com.get("official") or com.get("sample") or com.get("pinned"):
        return None
    if com.get("claimed") is not True or com.get("nameOk") is not True:
        return None
    name = rec.get("name")
    if not isinstance(name, str) or not name.strip() or GAME_BRAND_WORDS.search(name):
        return None
    t = _iso(com.get("firstSeen"))
    if t is None or now - t < ANNOUNCE_GRACE:
        return None
    return rid


def announce_line(name: str, rid: str, site: str) -> str:
    """"New realm listed: <name> — <link>", the name made safe (no pings, no markdown, one line)."""
    n = escape_md(defuse_mentions(_CONTROL.sub(" ", name)).strip())[:64]
    return f"New realm listed: {n} — {site}/wrath/r/{rid}"


def fetch_realms(url: str, urlopen=urllib.request.urlopen) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=8) as r:
        doc = json.loads(r.read(2_000_000).decode("utf-8"))
    realms = doc.get("realms") if isinstance(doc, dict) else None
    return realms if isinstance(realms, list) else []


# -------------------------------------------------------------------------------------------------------------------
# the bridge
# -------------------------------------------------------------------------------------------------------------------

class Bridge:
    def __init__(self, cfg: Config, discord, soap, state: State, clock=time.monotonic):
        self.cfg, self.discord, self.soap, self.state = cfg, discord, soap, state
        self.bot_id = None
        self.outbox: list[str] = []
        self.dropped = 0
        self.posts = Window(POSTS_PER_WINDOW, POST_WINDOW, clock)
        self.players = Window(PLAYER_MAX, PLAYER_WINDOW, clock)
        self.users = Window(USER_MAX, USER_WINDOW, clock)
        self.game_says = Window(GAME_SAY_MAX, GAME_SAY_WINDOW, clock)
        self.clock = clock
        self.next_announce = 0.0
        self.fetch = fetch_realms

    # -- start ------------------------------------------------------------------------------------------------------
    def start(self):
        me = self.discord.me() or {}
        self.bot_id = str(me.get("id") or "")
        log.info("Discord bot %s ready; bridging channel %s%s", me.get("username", "?"), self.cfg.chat_channel,
                 f", bug feed {self.cfg.bug_channel}" if self.cfg.bug_channel else "")
        if self.state.data.get("discord_after") is None:       # first run: start at the newest message, no replay
            self.state.data["discord_after"] = self.discord.latest_id(self.cfg.chat_channel)
        if self.cfg.bug_channel and self.state.data.get("bug_after") is None:   # first run: no old reports
            m = re.search(r"wudiscord bugmax (\d+)", self.soap.command("wudiscord bugmax") or "")
            self.state.data["bug_after"] = int(m.group(1)) if m else 0
        self.state.save()

    # -- game -> Discord --------------------------------------------------------------------------------------------
    def pull_game(self):
        st = self.state.data
        bug_after = st.get("bug_after") if self.cfg.bug_channel else -1
        got = parse_pull(self.soap.command(f"wudiscord pull {int(st.get('seq') or 0)} "
                                           f"{int(bug_after if bug_after is not None else -1)} {int(st.get('boot') or 0)}"))
        if got is None:
            log.warning("the realm did not answer wudiscord pull (is ov_discord.lua loaded?)")
            return
        boot, seq, chats, bugs = got
        if st.get("boot") != boot:
            if st.get("boot") is not None:
                log.info("the realm restarted or reloaded its scripts: chat sequence starts again")
            st["boot"] = boot
        for c in chats:
            if self.cfg.mutes.muted(c["name"]) or not self.players.allow(c["name"].lower()):
                continue
            if not strip_game_markup(c["text"]).strip():
                continue
            self.outbox.append(chat_line(c["name"], c["text"], self.cfg.link_allow))
        # the realm sends at most 25 lines per pull: carry on from the last one it sent, not from its newest
        st["seq"] = max(c["seq"] for c in chats) if chats else seq
        if len(self.outbox) > QUEUE_MAX:
            self.dropped += len(self.outbox) - QUEUE_MAX
            self.outbox = self.outbox[-QUEUE_MAX:]
        for b in bugs:
            if self.cfg.dry_run:
                log.info("dry run: bug feed <- %s", bug_post(b, self.cfg.link_allow))
            else:
                self.discord.post(self.cfg.bug_channel, bug_post(b, self.cfg.link_allow))
            st["bug_after"] = b["id"]

    def flush(self):
        if self.dropped:
            self.outbox.insert(0, f"*({self.dropped} lines skipped: chat was busier than Discord allows)*")
            self.dropped = 0
        if not self.outbox:
            return
        msgs = pack(self.outbox)
        sent = 0
        for m in msgs:
            if not self.posts.allow("chat"):
                break
            if self.cfg.dry_run:
                log.info("dry run: Discord <- %s", m)
            else:
                self.discord.post(self.cfg.chat_channel, m)
            sent += 1
        # what did not fit stays for the next round (lines never hold a newline themselves)
        left = "\n".join(msgs[sent:])
        self.outbox = left.split("\n") if left else []

    # -- Discord -> game --------------------------------------------------------------------------------------------
    def pull_discord(self):
        st = self.state.data
        for m in self.discord.messages_after(self.cfg.chat_channel, st.get("discord_after")):
            st["discord_after"] = str(m["id"])
            a = m.get("author") or {}
            if a.get("bot") or a.get("system") or m.get("webhook_id") or str(a.get("id")) == self.bot_id:
                continue
            if m.get("type", 0) not in (0, 19):          # ordinary messages and replies only (no joins, pins ...)
                continue
            name = display_name(m)
            if self.cfg.mutes.muted(a.get("id"), a.get("username"), name):
                continue
            text = clean_for_game(m)
            if not text:
                continue
            if not self.users.allow(str(a.get("id"))) or not self.game_says.allow():
                log.info("Discord -> game: rate limited (%s)", a.get("id"))
                continue
            if self.cfg.dry_run:
                log.info("dry run: game <- [Discord] %s: %s", name, text)
                continue
            self.soap.command(f"wudiscord say {name.encode().hex()} {text.encode().hex()}")

    # -- new realms -> Discord (off unless WU_DISCORD_ANNOUNCE_REALMS=1) ---------------------------------------------
    def announce_realms(self, now: float | None = None):
        if not self.cfg.announce or self.clock() < self.next_announce:
            return
        self.next_announce = self.clock() + self.cfg.announce_every
        now = time.time() if now is None else now
        try:
            realms = self.fetch(self.cfg.realms_url)
        except Exception as e:   # noqa: BLE001 - the site down never stops the chat bridge
            log.info("realm list not reachable for announcements: %s", type(e).__name__)
            return
        st = self.state.data
        first = st.get("announced") is None
        seen = list(st.get("announced") or [])
        posted = 0
        for rec in realms:
            rid = announceable(rec, now)
            if not rid or rid in seen:
                continue
            seen.append(rid)
            if first or posted >= ANNOUNCE_PER_ROUND:
                if not first:
                    seen.pop()        # over this round's cap: the next round posts it
                continue
            line = announce_line(rec["name"], rid, self.cfg.site)
            if self.cfg.dry_run:
                log.info("dry run: announce <- %s", line)
            else:
                self.discord.post(self.cfg.announce_channel, line)
            posted += 1
        st["announced"] = seen[-ANNOUNCE_MAX:]

    # -- one round --------------------------------------------------------------------------------------------------
    def step(self):
        errors = []
        for part in (self.pull_game, self.flush, self.pull_discord, self.announce_realms):
            try:
                part()
            except TransportError as e:
                errors.append(e)
                log.warning("%s: %s", part.__name__, e)
        self.state.save()
        return errors


def read_env_file(path: str) -> dict:
    """KEY=VALUE lines the way systemd's EnvironmentFile reads them (no shell: any character is fine in a value)."""
    env = {}
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln[0] in "#;" or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k.strip()] = v
    return env


def main(argv=None) -> int:
    argv = list(argv or [])
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    env = dict(os.environ)
    if "--env-file" in argv:                 # the deploy script's check reads discord.env without a shell
        env.update(read_env_file(argv[argv.index("--env-file") + 1]))
    cfg = Config(env)
    redact = SecretFilter(cfg.token, cfg.soap_pass)
    for h in logging.getLogger().handlers:
        h.addFilter(redact)
    bad = cfg.problems()
    if bad:
        for p in bad:
            log.error("not starting: %s", p)
        return 2
    if "--check" in argv:          # the deploy script's offline check: settings only, no network
        print(f"CHECK OK {cfg!r}")
        return 0
    log.info("starting: %r", cfg)
    bridge = Bridge(cfg, Discord(cfg.token, cfg.api), Soap(cfg.soap_url, cfg.soap_user, cfg.soap_pass), State(cfg.state_path))
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    backoff = cfg.poll
    while not stop:
        try:
            bridge.start()
            break
        except TransportError as e:
            if e.kind in ("auth", "forbidden"):
                log.error("not starting: %s (check the bot token, the SOAP login and the channel permissions)", e.kind)
                return 3
            log.warning("waiting for Discord / the realm: %s", e)
            time.sleep(min(backoff, 60)); backoff *= 2
    backoff = cfg.poll
    while not stop:
        errors = bridge.step()
        backoff = min(backoff * 2, 60) if errors else cfg.poll
        time.sleep(backoff)
    bridge.state.save()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
