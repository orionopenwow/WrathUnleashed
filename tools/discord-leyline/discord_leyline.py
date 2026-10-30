#!/usr/bin/env python3
"""Leyline Discord: rebrand and reset the owner's Discord server, in one run, from his own PC.

The owner runs this himself (the two .bat files next to it). Discord only lets a program change a server through a bot
token, so he makes a throwaway bot, invites it, pastes its token here, runs this, then kicks the bot. See README.md.

What it does, in order (a preview shows all of it first and changes nothing):
  1. backs up the server (settings, roles, channels and their permissions, the last N messages per text channel)
     to Desktop/Leyline-discord-backup-<stamp>/ before any change;
  2. roles Moderator, Helper, Creator, Member in Leyline colours;
  3. categories START, PLAY, CREATE, FEEDBACK and their channels; reuses a channel whose name already matches
     (its history stays), creates the rest;
  4. server name Leyline, icon, banner (if the server has the banner feature), system channel #welcome,
     rules channel #welcome (Community servers), AFK off;
  5. every other channel moves into a hidden, read-only ARCHIVE category (Moderators can still read it);
  6. only with --delete-archived / --delete-old-roles, and a typed confirmation: deletes the archive / old roles.
It never posts a message: it writes the #welcome and #help drafts to text files for the owner to post himself.
Running it twice changes nothing the second time.

Python 3 standard library only. The token is never printed, logged or written anywhere by this script.
"""
import argparse
import base64
import datetime as _dt
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_BASE = os.environ.get("LEYLINE_DISCORD_API", "https://discord.com/api/v10").rstrip("/")
AUDIT_REASON = "Leyline rebrand"
USER_AGENT = "DiscordBot (https://github.com/orionopenwow/Leyline, 1.0) leyline-rebrand"
BACKOFF = float(os.environ.get("LEYLINE_DISCORD_BACKOFF", "1"))   # seconds; tests shrink it

# ---------------------------------------------------------------------------------------------------------------------
# The look. Change these tables to change the theme.
SERVER_NAME = "Leyline"
ICON_FILE = HERE / "art" / "leyline-discord-icon-512.png"
BANNER_FILE = HERE / "art" / "leyline-discord-banner-960x540.png"

# One small glyph in front of every channel name, per category. --plain turns them off.
GLYPHS = {"START": "✦", "PLAY": "◆", "CREATE": "⟡", "FEEDBACK": "·"}
GLYPH_SEP = "︱"          # between the glyph and the name: "✦︱welcome"

TEXT, VOICE, CATEGORY, NEWS = 0, 2, 4, 5
ARCHIVE = "ARCHIVE"

# (category, [(name, type, topic, slowmode seconds, read-only for @everyone)])
LAYOUT = [
    ("START", [
        ("welcome", TEXT, "Leyline, the mod launcher community. Start here: what it is, where to play, "
                          "get the launcher, host a realm. Read-only.", 0, True),
        ("announcements", NEWS, "Releases and realm news. Read-only.", 0, True),
    ]),
    ("PLAY", [
        ("general", TEXT, "Talk about anything Leyline.", 0, False),
        ("help", TEXT, "Getting in: the browser, the launcher, your own game files. Helpers answer here.", 10, False),
        ("looking-for-group", TEXT, "Find people to play with on any Beacon: dungeons, raids, duels.", 0, False),
        ("Hangout", VOICE, None, 0, False),
    ]),
    ("CREATE", [
        ("mods-and-workshop", TEXT, "Share and ask about addons, mods, modes, themes and builds.", 0, False),
        ("host-a-beacon", TEXT, "Host your own realm: the Host pack, the relay, invite links.", 0, False),
        ("showcase", TEXT, "Screenshots and clips. Images and links only.", 0, False),
    ]),
    ("FEEDBACK", [
        ("bug-reports", TEXT, "Something broken? Use .bug in game when you can; post the rest here.", 0, False),
        ("ideas", TEXT, "Suggestions. One idea per message; react to support.", 10, False),
    ]),
]

# An existing channel with one of these names is reused (history kept) instead of making a new one. First match wins.
ALIASES = {
    "welcome": ["welcome", "start-here"],
    "announcements": ["announcements", "announcement", "news"],
    "general": ["general", "general-chat", "chat"],
    "help": ["help", "support"],
    "looking-for-group": ["looking-for-group", "lfg"],
    "mods-and-workshop": ["mods-and-workshop", "mods", "workshop", "modding"],
    "host-a-beacon": ["host-a-beacon", "hosting"],
    "showcase": ["showcase", "screenshots"],
    "bug-reports": ["bug-reports", "bug-report", "bugs"],
    "ideas": ["ideas", "suggestions"],
    "hangout": ["hangout", "general", "lounge"],
}

# Permission bits (Discord's numbers).
P_KICK = 1 << 1
P_ADD_REACTIONS = 1 << 6
P_VIEW = 1 << 10
P_SEND = 1 << 11
P_MANAGE_MESSAGES = 1 << 13
P_HISTORY = 1 << 16
P_CONNECT = 1 << 20
P_MUTE = 1 << 22
P_MOVE = 1 << 24
P_MANAGE_THREADS = 1 << 34
P_PUBLIC_THREADS = 1 << 35
P_PRIVATE_THREADS = 1 << 36
P_SEND_IN_THREADS = 1 << 38
P_TIMEOUT = 1 << 40
P_NO_TALK = P_SEND | P_SEND_IN_THREADS | P_PUBLIC_THREADS | P_PRIVATE_THREADS

# (name, colour, hoist (shown apart in the member list), mentionable, permissions given when the role is created)
ROLES = [
    ("Moderator", 0x8B5CF6, True, False, P_MANAGE_MESSAGES | P_MANAGE_THREADS | P_TIMEOUT | P_MUTE | P_MOVE),
    ("Helper", 0x5B8DEF, True, True, 0),
    ("Creator", 0xA78BFA, True, False, 0),
    ("Member", 0x93B4F5, False, False, 0),
]
KEEP_ROLE_NAMES = {"owner"}       # never removed by --delete-old-roles either

LINK_PLAY = "https://play.openvanilla.app/wrath"
LINK_LAUNCHER = "https://github.com/orionopenwow/Leyline/releases"
LINK_HOST = "https://play.openvanilla.app/wrath/host"

WELCOME_DRAFT = f"""TODO(owner): your opening line, in your own words.

Leyline is an open-source mod launcher and realm network. Play in the browser, install mods in one click, \
find community realms or host your own.

Play in the browser: {LINK_PLAY}
Get the launcher: {LINK_LAUNCHER}
Host a realm: {LINK_HOST}

The rules
1. No client downloads, game files, repacks or torrents. Bring your own.
2. Nobody here will ever ask for your password or Hero Key. If someone does, it isn't us: report them.
3. Be decent.

TODO(owner): your sign-off.
"""

HELP_DRAFT = f"""Getting in

1. In the browser: open {LINK_PLAY} and follow the steps on the page.
2. With the launcher: download it from {LINK_LAUNCHER}, then point it at your own game folder.
3. Hosting your own realm: {LINK_HOST}

Stuck? Post here: what you tried, what you see, and a screenshot. A Helper will answer.
Never post your password or Hero Key. Nobody here will ask for them.

TODO(owner): known issues, one line each.
"""

BANNED = re.compile(r"world\s*of\s*warcraft|\bwow\b|warcraft|lich\s*king|blizzard|\d+\.\d+(\.\d+)?", re.I)

TEXTY = (TEXT, NEWS)
MOVABLE = (TEXT, VOICE, NEWS, 13, 15, 16)       # text, voice, announcement, stage, forum, media
MESSAGE_TYPES = (TEXT, VOICE, NEWS, 13)


# ---------------------------------------------------------------------------------------------------------------------
class Out:
    """Every line goes through here, so the token can never reach the screen even by accident."""
    secret = None

    @classmethod
    def say(cls, *parts):
        s = " ".join(str(p) for p in parts)
        if cls.secret:
            s = s.replace(cls.secret, "[hidden]")
        print(s, flush=True)


say = Out.say


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(f"Discord said {status}: {message}")
        self.status, self.code = status, code


class Discord:
    def __init__(self, token, allow_writes=False, sleep=time.sleep):
        self._token = token
        self.allow_writes = allow_writes
        self.sleep = sleep

    def request(self, method, path, body=None, query=None):
        if method != "GET" and not self.allow_writes:
            raise RuntimeError(f"blocked a {method} in preview mode")       # belt and braces: preview never writes
        url = API_BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bot " + self._token, "User-Agent": USER_AGENT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET":
            headers["X-Audit-Log-Reason"] = urllib.parse.quote(AUDIT_REASON)
        tries_5xx = 0
        tries_429 = 0
        while True:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    if r.headers.get("X-RateLimit-Remaining") == "0":
                        self.sleep(min(float(r.headers.get("X-RateLimit-Reset-After") or 0), 60))
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    info = json.loads(raw) if raw else {}
                except ValueError:
                    info = {}
                if e.code == 429 and tries_429 < 10:
                    tries_429 += 1
                    wait = info.get("retry_after") or e.headers.get("Retry-After") or 1
                    self.sleep(float(wait) + 0.05)
                    continue
                if e.code >= 500 and tries_5xx < 4:
                    self.sleep(BACKOFF * (2 ** tries_5xx))
                    tries_5xx += 1
                    continue
                msg = info.get("message") or (e.reason if isinstance(e.reason, str) else "error")
                raise ApiError(e.code, msg, info.get("code")) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if tries_5xx < 4:
                    self.sleep(BACKOFF * (2 ** tries_5xx))
                    tries_5xx += 1
                    continue
                raise ApiError("no answer", str(getattr(e, "reason", e))) from None


# ---------------------------------------------------------------------------------------------------------------------
def slug(name):
    """'✦︱Welcome' -> 'welcome'. Drops leading glyphs, lowercases, spaces to dashes."""
    s = (name or "").strip().lower()
    m = re.search(r"[0-9a-z]", s)
    s = s[m.start():] if m else ""
    return re.sub(r"[\s_]+", "-", s).strip("-")


def styled(cat, name, plain):
    return name if plain or not GLYPHS.get(cat) else f"{GLYPHS[cat]}{GLYPH_SEP}{name}"


def okey(o):
    try:
        n = int(o["id"])
    except (ValueError, TypeError):
        n = 10 ** 30
    return (o.get("position") or 0, n)


def ow_map(ch):
    return {o["id"]: o for o in ch.get("permission_overwrites") or []}


def ow_norm(lst):
    return sorted((str(o["id"]), int(o.get("type", 0)), int(o.get("allow") or 0), int(o.get("deny") or 0))
                  for o in lst or [])


def file_sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def data_uri(p):
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def state_path():
    return Path(os.environ.get("LEYLINE_STATE_FILE") or HERE / ".leyline-state.json")


def load_state():
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        state_path().write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------------------
class Rebrand:
    """Works out every change from the server as it is now. In preview it only records them; in apply it makes them.
    The same code runs both ways, so the preview is exactly what will happen."""

    def __init__(self, api, guild_id, opts, apply):
        self.api, self.gid, self.opts, self.apply = api, guild_id, opts, apply
        self.lines = []          # (section, text, is_change)
        self.changes = 0
        self.fake = 0
        self.archived = []       # channel ids that are (or will be) in ARCHIVE
        self.hidden_cats = []
        self.state = load_state()

    # -- recording / doing --------------------------------------------------------------------------------------------
    def note(self, section, text):
        self.lines.append((section, text, False))

    def act(self, section, text, method, path, body=None):
        self.changes += 1
        self.lines.append((section, text, True))
        if not self.apply:
            return None
        res = self.api.request(method, path, body)
        say("  done:", text)
        return res

    def new_id(self):
        self.fake += 1
        return f"new-{self.fake}"

    # -- reading ------------------------------------------------------------------------------------------------------
    def load(self):
        g = self.api.request
        self.guild = g("GET", f"/guilds/{self.gid}")
        self.original_name = self.guild.get("name") or ""
        self.roles = g("GET", f"/guilds/{self.gid}/roles")
        self.channels = g("GET", f"/guilds/{self.gid}/channels")
        self.me = g("GET", "/users/@me")
        bot = g("GET", f"/guilds/{self.gid}/members/{self.me['id']}")
        try:
            owner = g("GET", f"/guilds/{self.gid}/members/{self.guild['owner_id']}")
            self.owner_roles = set(owner.get("roles") or [])
        except ApiError:
            self.owner_roles = set()
        pos = {r["id"]: r.get("position", 0) for r in self.roles}
        self.bot_top = max([pos.get(r, 0) for r in bot.get("roles") or []] or [0])
        self.features = set(self.guild.get("features") or [])

    def role_block(self, r):
        """Why the script must leave this role alone, or None if it may change it."""
        if r["id"] == self.gid:
            return "@everyone"
        if r.get("managed") or (r.get("tags") or {}).get("integration_id") or (r.get("tags") or {}).get("bot_id"):
            return "belongs to a bot or integration"
        if r.get("position", 0) >= self.bot_top:
            return "above the bot's role"
        if r["id"] in self.owner_roles:
            return "you have this role"
        return None

    # -- the steps ----------------------------------------------------------------------------------------------------
    def run(self):
        self.load()
        self.do_roles()
        self.do_categories()
        self.do_channels()
        self.do_guild()
        self.do_archive()
        self.do_order()
        if self.opts.delete_old_roles:
            self.do_delete_roles()
        if self.opts.delete_archived:
            self.do_delete_archived()
        self.manual_steps()

    def do_roles(self):
        self.role_ids = {}
        for name, colour, hoist, mention, perms in ROLES:
            found = sorted([r for r in self.roles if r["name"].strip().lower() == name.lower()],
                           key=lambda r: -r.get("position", 0))
            if found:
                r = found[0]
                self.role_ids[name] = r["id"]
                why = self.role_block(r)
                diff = {}
                if r["name"] != name:
                    diff["name"] = name
                if r.get("color", 0) != colour:
                    diff["color"] = colour
                if bool(r.get("hoist")) != hoist:
                    diff["hoist"] = hoist
                if not diff:
                    self.note("roles", f"keep {name} (already right)")
                elif why:
                    self.note("roles", f"keep {name} as it is ({why}); can't restyle it")
                else:
                    self.act("roles", f"restyle {name} (colour #{colour:06x})", "PATCH",
                             f"/guilds/{self.gid}/roles/{r['id']}", diff)
                    r.update(diff)
            else:
                body = {"name": name, "color": colour, "hoist": hoist, "mentionable": mention,
                        "permissions": str(perms)}
                res = self.act("roles", f"create {name} (colour #{colour:06x}{', shown apart' if hoist else ''})",
                               "POST", f"/guilds/{self.gid}/roles", body)
                if res:     # Discord puts a new role at the bottom and shifts the rest: read them again
                    self.roles = self.api.request("GET", f"/guilds/{self.gid}/roles")
                    self.bot_top += 1
                    r = next(x for x in self.roles if x["id"] == res["id"])
                else:
                    for o in self.roles:
                        if o["id"] != self.gid and o.get("position", 0) >= 1:
                            o["position"] = o.get("position", 0) + 1
                    self.bot_top += 1
                    r = dict(body, id=self.new_id(), position=1)
                    self.roles.append(r)
                self.role_ids[name] = r["id"]
        # Order Moderator > Helper > Creator > Member using only the slots these roles already hold.
        mine = [r for r in self.roles if r["id"] in self.role_ids.values() and not self.role_block(r)]
        want = [n for n, *_ in ROLES if any(r["id"] == self.role_ids[n] for r in mine)]
        if len(mine) > 1:
            slots = sorted((r.get("position", 0) for r in mine), reverse=True)
            byname = {n: next(r for r in mine if r["id"] == self.role_ids[n]) for n in want}
            cur = [n for n in sorted(want, key=lambda n: -byname[n].get("position", 0))]
            if cur != want or len(set(slots)) != len(slots):
                if len(set(slots)) != len(slots):
                    slots = list(range(max(slots), max(slots) - len(slots), -1))
                body = [{"id": byname[n]["id"], "position": p} for n, p in zip(want, slots) if p >= 1]
                self.act("roles", "order roles: " + " > ".join(want), "PATCH", f"/guilds/{self.gid}/roles", body)
                for b in body:
                    next(r for r in self.roles if r["id"] == b["id"])["position"] = b["position"]

    def find_cat(self, name):
        for c in sorted(self.channels, key=okey):
            if c["type"] == CATEGORY and slug(c["name"]) == slug(name) and c["id"] not in self.used:
                return c
        return None

    def ensure_overwrite(self, ch, target_id, otype, allow, deny, section):
        """Make one permission overwrite on a channel exactly (allow, deny); (0, 0) means 'none at all'."""
        cur = ow_map(ch).get(target_id)
        label = "@everyone" if target_id == self.gid else next(
            (r["name"] for r in self.roles if r["id"] == target_id), target_id)
        if allow == 0 and deny == 0:
            if cur is not None:
                self.act(section, f"{ch['name']}: clear the {label} override", "DELETE",
                         f"/channels/{ch['id']}/permissions/{target_id}")
                ch["permission_overwrites"] = [o for o in ch["permission_overwrites"] if o["id"] != target_id]
            return
        if cur is not None and int(cur.get("allow") or 0) == allow and int(cur.get("deny") or 0) == deny:
            return
        text = f"{ch['name']}: {label} " + ("read-only" if deny & P_SEND else
                                           "can post" if allow & P_SEND else "can view")
        self.act(section, text, "PUT", f"/channels/{ch['id']}/permissions/{target_id}",
                 {"allow": str(allow), "deny": str(deny), "type": otype})
        ch["permission_overwrites"] = [o for o in ch.get("permission_overwrites") or [] if o["id"] != target_id]
        ch["permission_overwrites"].append({"id": target_id, "type": otype, "allow": str(allow), "deny": str(deny)})

    def do_categories(self):
        self.used = set()
        self.cat_ids = {}
        for cat, _ in LAYOUT:
            c = self.find_cat(cat)
            if c:
                self.used.add(c["id"])
                if c["name"] != cat:
                    self.act("channels", f"rename category {c['name']!r} -> {cat}", "PATCH",
                             f"/channels/{c['id']}", {"name": cat})
                    c["name"] = cat
                else:
                    self.note("reused", f"category {cat}")
            else:
                body = {"name": cat, "type": CATEGORY}
                res = self.act("created", f"category {cat}", "POST", f"/guilds/{self.gid}/channels", body)
                c = res or dict(body, id=self.new_id(), position=10 ** 6 + self.fake, permission_overwrites=[])
                self.channels.append(c)
                self.used.add(c["id"])
            self.cat_ids[cat] = c["id"]
            # a Leyline category is visible to everyone: drop any @everyone override it had
            self.ensure_overwrite(c, self.gid, 0, 0, 0, "channels")

    def find_channel(self, name, ctype):
        ok = (VOICE,) if ctype == VOICE else TEXTY
        for alias in ALIASES.get(slug(name), [slug(name)]):
            for c in sorted(self.channels, key=lambda c: int(c["id"]) if c["id"].isdigit() else 10 ** 30):
                if c["type"] in ok and c["id"] not in self.used and slug(c["name"]) == alias:
                    return c
        return None

    def do_channels(self):
        self.chan_ids = {}
        mod = self.role_ids["Moderator"]
        news_ok = "NEWS" in self.features or "COMMUNITY" in self.features
        for cat, chans in LAYOUT:
            for name, ctype, topic, slow, ro in chans:
                want_name = styled(cat, name, self.opts.plain)
                c = self.find_channel(name, ctype)
                if c:
                    self.used.add(c["id"])
                    diff = {}
                    if c["name"] != want_name:
                        diff["name"] = want_name
                    if c.get("parent_id") != self.cat_ids[cat]:
                        diff["parent_id"] = self.cat_ids[cat]
                    if ctype != VOICE:
                        if (c.get("topic") or None) != topic:
                            diff["topic"] = topic
                        if (c.get("rate_limit_per_user") or 0) != slow:
                            diff["rate_limit_per_user"] = slow
                    if diff:
                        what = ", ".join({"name": "rename", "parent_id": f"move to {cat}", "topic": "topic",
                                          "rate_limit_per_user": f"slowmode {slow}s"}[k] for k in diff)
                        self.act("reused", f"{c['name']} -> {want_name} (keeps its history; {what})", "PATCH",
                                 f"/channels/{c['id']}", diff)
                        c.update(diff)
                    else:
                        self.note("reused", f"{want_name} (already right)")
                else:
                    t = NEWS if ctype == NEWS and news_ok else (TEXT if ctype == NEWS else ctype)
                    body = {"name": want_name, "type": t, "parent_id": self.cat_ids[cat]}
                    if ctype != VOICE:
                        body["topic"] = topic
                        if slow:
                            body["rate_limit_per_user"] = slow
                    extra = f", slowmode {slow}s" if slow else ""
                    res = self.act("created", f"{want_name} in {cat}{extra}{', read-only' if ro else ''}", "POST",
                                   f"/guilds/{self.gid}/channels", body)
                    c = res or dict(body, id=self.new_id(), position=10 ** 6 + self.fake, permission_overwrites=[])
                    c.setdefault("permission_overwrites", [])
                    self.channels.append(c)
                    self.used.add(c["id"])
                self.chan_ids[name] = c["id"]
                if ro:
                    self.ensure_overwrite(c, self.gid, 0, 0, P_NO_TALK, "channels")
                    self.ensure_overwrite(c, mod, 0, P_SEND, 0, "channels")
                else:
                    self.ensure_overwrite(c, self.gid, 0, 0, 0, "channels")

    def icon_step(self, field, path, label):
        sha = file_sha(path)
        rec = self.state.get(self.gid, {}).get(field) or {}
        if rec.get("sha") == sha and rec.get("hash") and rec["hash"] == self.guild.get(field):
            self.note("server", f"{label} already set")
            return None
        return sha

    def do_guild(self):
        diff, said = {}, []
        if self.guild.get("name") != SERVER_NAME:
            diff["name"] = SERVER_NAME
            said.append(f"rename {self.guild.get('name')!r} -> {SERVER_NAME!r}")
        uploads = {}
        for field, path, label, feature in (("icon", ICON_FILE, "icon", None),
                                            ("banner", BANNER_FILE, "banner", "BANNER"),
                                            ("splash", BANNER_FILE, "invite background", "INVITE_SPLASH")):
            if feature and feature not in self.features:
                continue
            if not path.exists():
                self.note("can't", f"{label}: {path.name} is missing next to the script")
                continue
            sha = self.icon_step(field, path, label)
            if sha:
                diff[field] = data_uri(path)
                uploads[field] = sha
                said.append(f"{label} -> {path.name}")
        welcome = self.chan_ids["welcome"]
        if self.guild.get("system_channel_id") != welcome:
            diff["system_channel_id"] = welcome
            said.append("system messages -> #welcome")
        if "COMMUNITY" in self.features and self.guild.get("rules_channel_id") != welcome:
            diff["rules_channel_id"] = welcome
            said.append("rules channel -> #welcome")
        if self.guild.get("afk_channel_id"):
            diff["afk_channel_id"] = None
            said.append("AFK channel off")
        if not diff:
            self.note("server", "name, channels for system messages and AFK already right")
            return
        res = self.act("server", "; ".join(said), "PATCH", f"/guilds/{self.gid}", diff)
        if res:
            self.guild = res
            for field, sha in uploads.items():
                self.state.setdefault(self.gid, {})[field] = {"sha": sha, "hash": res.get(field)}
            save_state(self.state)
        else:
            self.guild.update({k: v for k, v in diff.items() if k not in uploads})

    def archive_overwrites(self):
        return [{"id": self.gid, "type": 0, "allow": "0", "deny": str(P_VIEW | P_NO_TALK | P_CONNECT)},
                {"id": self.role_ids["Moderator"], "type": 0, "allow": str(P_VIEW | P_HISTORY),
                 "deny": str(P_NO_TALK | P_CONNECT)}]

    def do_archive(self):
        keep = {self.guild.get("public_updates_channel_id"), self.guild.get("safety_alerts_channel_id")} - {None}
        todo = [c for c in sorted(self.channels, key=okey)
                if c["type"] in MOVABLE and c["id"] not in self.used and c["id"] not in keep]
        for c in self.channels:
            if c["id"] in keep and c["id"] not in self.used:
                self.note("kept", f"{c['name']} stays where it is (Discord needs it for Community updates)")
        arch = self.find_cat(ARCHIVE)
        if not todo and not arch:
            self.note("archive", "nothing to archive")
            self.arch_id = None
            self.hide_old_categories()
            return
        want = self.archive_overwrites()
        if arch:
            self.used.add(arch["id"])
            if arch["name"] != ARCHIVE:
                self.act("archive", f"rename category {arch['name']!r} -> {ARCHIVE}", "PATCH",
                         f"/channels/{arch['id']}", {"name": ARCHIVE})
                arch["name"] = ARCHIVE
            if ow_norm(arch.get("permission_overwrites")) != ow_norm(want):
                self.act("archive", "ARCHIVE: hidden from everyone, Moderators can read", "PATCH",
                         f"/channels/{arch['id']}", {"permission_overwrites": want})
                arch["permission_overwrites"] = want
        else:
            body = {"name": ARCHIVE, "type": CATEGORY, "permission_overwrites": want}
            res = self.act("archive", "create hidden ARCHIVE category (read-only, Moderators can read)", "POST",
                           f"/guilds/{self.gid}/channels", body)
            arch = res or dict(body, id=self.new_id(), position=10 ** 6 + self.fake)
            self.channels.append(arch)
            self.used.add(arch["id"])
        self.arch_id = arch["id"]
        for c in todo:
            self.used.add(c["id"])
            self.archived.append(c["id"])
            body = {}
            if c.get("parent_id") != arch["id"]:
                body["parent_id"] = arch["id"]
            if ow_norm(c.get("permission_overwrites")) != ow_norm(want):
                body["permission_overwrites"] = want
            if body:
                self.act("archive", f"{c['name']} -> ARCHIVE (hidden, read-only, history kept)", "PATCH",
                         f"/channels/{c['id']}", body)
                c.update(body)
        if not todo:
            self.note("archive", "every old channel is already in ARCHIVE")
        self.hide_old_categories()

    def hide_old_categories(self):
        for cat in sorted(self.channels, key=okey):
            if cat["type"] != CATEGORY or cat["id"] in self.used:
                continue
            self.hidden_cats.append(cat["id"])
            if any(c.get("parent_id") == cat["id"] for c in self.channels if c["type"] != CATEGORY):
                continue        # still holds something we left alone (e.g. Community updates)
            cur = ow_map(cat).get(self.gid)
            if cur and int(cur.get("deny") or 0) & P_VIEW:
                continue
            deny = (int(cur.get("deny") or 0) if cur else 0) | P_VIEW
            allow = (int(cur.get("allow") or 0) if cur else 0) & ~P_VIEW
            self.act("archive", f"hide the empty old category {cat['name']!r}", "PUT",
                     f"/channels/{cat['id']}/permissions/{self.gid}",
                     {"allow": str(allow), "deny": str(deny), "type": 0})
            cat["permission_overwrites"] = [o for o in cat.get("permission_overwrites") or []
                                            if o["id"] != self.gid] + [
                {"id": self.gid, "type": 0, "allow": str(allow), "deny": str(deny)}]

    def do_order(self):
        cats = sorted([c for c in self.channels if c["type"] == CATEGORY], key=okey)
        want = [self.cat_ids[c] for c, _ in LAYOUT] + ([self.arch_id] if self.arch_id else [])
        want += [c["id"] for c in cats if c["id"] not in want]
        body = []
        if [c["id"] for c in cats] != want:
            body += [{"id": i, "position": n} for n, i in enumerate(want)]
        for cat, chans in LAYOUT:
            for group in (TEXTY, (VOICE,)):
                ids = [self.chan_ids[n] for n, t, *_ in chans if (t in TEXTY) == (group == TEXTY)]
                cur = [c["id"] for c in sorted(self.channels, key=okey)
                       if c.get("parent_id") == self.cat_ids[cat] and c["type"] in group]
                if cur != ids:
                    body += [{"id": i, "position": n} for n, i in enumerate(ids)]
        if body:
            self.act("order", "put categories and channels in order (START, PLAY, CREATE, FEEDBACK, ARCHIVE)",
                     "PATCH", f"/guilds/{self.gid}/channels", body)
            for b in body:
                next(c for c in self.channels if c["id"] == b["id"])["position"] = b["position"]

    def old_roles(self):
        keep_names = {n.lower() for n, *_ in ROLES} | KEEP_ROLE_NAMES
        out, blocked = [], []
        for r in sorted(self.roles, key=lambda r: -r.get("position", 0)):
            if r["id"] in self.role_ids.values() or r["name"].strip().lower() in keep_names:
                continue
            why = self.role_block(r)
            if why == "@everyone":
                continue
            (blocked if why else out).append((r, why))
        return out, blocked

    def do_delete_roles(self):
        out, blocked = self.old_roles()
        for r, why in blocked:
            self.note("roles", f"keep {r['name']} ({why})")
        for r, _ in out:
            self.act("deleted", f"role {r['name']}", "DELETE", f"/guilds/{self.gid}/roles/{r['id']}")

    def do_delete_archived(self):
        if not self.arch_id:
            self.note("deleted", "nothing archived to delete")
        else:
            for c in sorted(self.channels, key=okey):
                if c.get("parent_id") == self.arch_id and c["type"] != CATEGORY:
                    self.act("deleted", f"channel {c['name']} (from ARCHIVE)", "DELETE", f"/channels/{c['id']}")
            self.act("deleted", "the ARCHIVE category", "DELETE", f"/channels/{self.arch_id}")
        for cid in self.hidden_cats:
            c = next(x for x in self.channels if x["id"] == cid)
            if not any(x.get("parent_id") == cid for x in self.channels if x["type"] != CATEGORY):
                self.act("deleted", f"empty old category {c['name']!r}", "DELETE", f"/channels/{cid}")

    def manual_steps(self):
        m = []
        if "COMMUNITY" in self.features:
            m.append("Rules for new members: Server Settings -> Onboarding (or Safety Setup -> Rules Screening on "
                     "older menus) -> add: no client downloads or game files; nobody asks for passwords or Hero Keys; "
                     "be decent.")
            m.append("Onboarding: Server Settings -> Onboarding -> Default Channels: tick #welcome, #announcements, "
                     "#general, #help. A question there can hand out the Member role.")
            m.append("Description: Server Settings -> Community -> Overview -> Server Description (TODO(owner)).")
        else:
            m.append("Rules screening and onboarding need a Community server: Server Settings -> Enable Community "
                     "(choose #welcome as the rules channel), then Server Settings -> Onboarding.")
        if "BANNER" not in self.features:
            m.append("Banner: needs boost level 2. When you have it: Server Settings -> Overview -> Server Banner "
                     "Background -> upload art/leyline-discord-banner-960x540.png (or run this script again).")
        if "VANITY_URL" in self.features:
            m.append("Invite link: Server Settings -> Vanity URL -> discord.gg/leyline (if it's free).")
        else:
            m.append("Invite link discord.gg/leyline needs boost level 3: Server Settings -> Vanity URL.")
        m.append("Release feed: #announcements -> Edit Channel -> Integrations -> Webhooks -> New Webhook; on GitHub, "
                 "the Leyline repo -> Settings -> Webhooks: the webhook URL + /github, events: Releases only.")
        m.append("Member role: Discord has no built-in auto-role; give it by hand, through Onboarding, or skip it.")
        m.append("Last: kick the helper bot (Server Settings -> Integrations -> the bot -> Kick, or right-click it in "
                 "the member list -> Kick), then Developer Portal -> your app -> Bot -> Reset Token (or delete the app).")
        for x in m:
            self.note("manual", x)

    # -- printing -----------------------------------------------------------------------------------------------------
    SECTIONS = [("server", "Server"), ("roles", "Roles"), ("created", "New channels"),
                ("reused", "Reused channels (history kept)"), ("channels", "Channel settings"),
                ("archive", "Archive"), ("kept", "Left alone"), ("order", "Order"),
                ("deleted", "DELETED"), ("can't", "Can't do"), ("manual", "Do these by hand afterwards")]

    def report(self):
        say("")
        for key, title in self.SECTIONS:
            items = [(t, ch) for s, t, ch in self.lines if s == key]
            if key == "roles" and not self.opts.delete_old_roles:
                out, _ = self.old_roles()
                if out:
                    items.append(("old roles left alone (add --delete-old-roles to remove them): "
                                  + ", ".join(r["name"] for r, _ in out), False))
            if key == "deleted" and not self.opts.delete_archived and self.archived:
                items.append(("nothing (archived channels stay; --delete-archived would delete them)", False))
            if not items:
                continue
            say(f"{title}:")
            for t, ch in items:
                say(("  * " if ch else "    ") + t)
        say("")
        say(f"{self.changes} change(s)." if self.changes else "Nothing to change: the server is already Leyline.")


# ---------------------------------------------------------------------------------------------------------------------
def desktop():
    root = os.environ.get("LEYLINE_BACKUP_ROOT")
    if root:
        return Path(root)
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for d in (Path(os.environ["OneDrive"]) / "Desktop" if os.environ.get("OneDrive") else None, home / "Desktop"):
        if d and d.is_dir():
            return d
    return home


def safe_name(s):
    return re.sub(r"[^0-9A-Za-z_-]+", "", slug(s)) or "channel"


def backup(api, gid, n_messages):
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = desktop() / f"Leyline-discord-backup-{stamp}"
    k = 1
    while out.exists():
        k += 1
        out = desktop() / f"Leyline-discord-backup-{stamp}-{k}"
    (out / "messages").mkdir(parents=True)

    def dump(name, obj):
        (out / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")

    guild = api.request("GET", f"/guilds/{gid}")
    roles = api.request("GET", f"/guilds/{gid}/roles")
    channels = api.request("GET", f"/guilds/{gid}/channels")
    dump("guild.json", guild)
    dump("roles.json", roles)
    dump("channels.json", channels)          # includes every channel's permission_overwrites
    skipped = []
    if n_messages > 0:
        texty = [c for c in sorted(channels, key=okey) if c["type"] in MESSAGE_TYPES]
        for i, c in enumerate(texty, 1):
            say(f"  backing up messages {i}/{len(texty)}: {c['name']}")
            msgs, before = [], None
            try:
                while len(msgs) < n_messages:
                    q = {"limit": min(100, n_messages - len(msgs))}
                    if before:
                        q["before"] = before
                    page = api.request("GET", f"/channels/{c['id']}/messages", query=q)
                    if not page:
                        break
                    msgs += page
                    before = page[-1]["id"]
                    if len(page) < q["limit"]:
                        break
            except ApiError as e:
                skipped.append(f"{c['name']}: {e}")
            slim = [{"id": m["id"],
                     "author": (m.get("author") or {}).get("global_name") or (m.get("author") or {}).get("username"),
                     "author_id": (m.get("author") or {}).get("id"),
                     "time": m.get("timestamp"), "edited": m.get("edited_timestamp"),
                     "content": m.get("content"), "pinned": m.get("pinned", False),
                     "attachments": [a.get("url") for a in m.get("attachments") or []]} for m in msgs]
            (out / "messages" / f"{safe_name(c['name'])}-{c['id']}.json").write_text(
                json.dumps({"channel": c["name"], "id": c["id"], "messages": slim}, indent=1, ensure_ascii=False),
                encoding="utf-8")
    if skipped:
        dump("messages-skipped.json", skipped)
    return out


def write_drafts(folder):
    w = folder / "welcome-message.txt"
    h = folder / "help-getting-in.txt"
    w.write_text(WELCOME_DRAFT, encoding="utf-8")
    h.write_text(HELP_DRAFT, encoding="utf-8")
    copied = False
    if os.name == "nt":
        try:
            subprocess.run(["clip"], input=WELCOME_DRAFT.encode("utf-16"), check=True, timeout=10)
            copied = True
        except (OSError, subprocess.SubprocessError):
            pass
    return w, h, copied


def read_token(path):
    tok = ""
    if path and Path(path).is_file():
        tok = Path(path).read_text(encoding="utf-8-sig").strip()
        if tok:
            say(f"Using the bot token from {Path(path).name} (not shown).")
    if not tok:
        say("Paste the bot token (Developer Portal -> your app -> Bot -> Reset Token -> Copy).")
        say("It won't show while you paste. Press Enter after.")
        tok = getpass.getpass("Bot token: ").strip()
    tok = tok.strip().strip('"').strip("'")
    if tok.lower().startswith("bot "):
        tok = tok[4:].strip()
    if not tok or re.search(r"\s", tok):
        raise SystemExit("That doesn't look like a bot token. Copy it again from the Developer Portal.")
    Out.secret = tok
    return tok


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return ""


def pick_guild(api, given):
    if given:
        return str(given)
    guilds = api.request("GET", "/users/@me/guilds")
    if not guilds:
        raise SystemExit("The bot isn't in any server yet. Invite it first (README step 3), then run this again.")
    if len(guilds) == 1:
        say(f"The bot is in one server: {guilds[0]['name']} (id {guilds[0]['id']}). Using that.")
        return guilds[0]["id"]
    say("The bot is in more than one server:")
    for g in guilds:
        say(f"  {g['id']}  {g['name']}")
    gid = ask("Type the id of the server to change: ").strip()
    if gid not in {g["id"] for g in guilds}:
        raise SystemExit("That id isn't one of them. Nothing changed.")
    return gid


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Rebrand and reset a Discord server to Leyline (owner-run).")
    ap.add_argument("--apply", action="store_true", help="make the changes (asks you to type YES). Without it: preview")
    ap.add_argument("--guild", help="server id (default: the one server the bot is in, or it asks)")
    ap.add_argument("--plain", action="store_true", help="channel names without the leading glyphs")
    ap.add_argument("--backup-messages", type=int, default=1000, metavar="N",
                    help="messages to back up per text channel (default 1000; 0 skips messages)")
    ap.add_argument("--delete-archived", action="store_true",
                    help="after the backup, delete the archived channels (asks you to type the server name)")
    ap.add_argument("--delete-old-roles", action="store_true",
                    help="delete roles that aren't in the new set (asks you to type DELETE ROLES)")
    ap.add_argument("--token-file", default=str(HERE / "token.txt"), help=argparse.SUPPRESS)
    o = ap.parse_args(argv)

    try:
        tok = read_token(o.token_file)
        api = Discord(tok)
        try:
            me = api.request("GET", "/users/@me")
        except ApiError as e:
            if e.status == 401:
                raise SystemExit("Discord didn't accept that token. In the Developer Portal: Bot -> Reset Token, "
                                 "copy the new one, and try again.") from None
            raise
        say(f"Signed in as the bot {me.get('username')}.")
        gid = pick_guild(api, o.guild)

        plan = Rebrand(api, gid, o, apply=False)
        plan.run()
        old_name = plan.original_name
        say("")
        say(("PREVIEW (nothing will change)" if not o.apply else "PLAN") + f" for the server {old_name!r}:")
        plan.report()

        if not o.apply:
            say("")
            say("This was a preview. Nothing changed. To do it: run 'Leyline Discord - do it.bat'.")
            say(f"Before any change it backs up the server to your Desktop (last {o.backup_messages} messages "
                "per channel), and it writes the #welcome and #help drafts for you to post yourself.")
            return 0

        if plan.changes:
            if ask(f"\nType YES to make these {plan.changes} change(s) to {old_name!r}: ").strip() != "YES":
                say("Stopped. Nothing changed.")
                return 1
        if o.delete_old_roles:
            if ask("You asked to DELETE the old roles listed above. Type DELETE ROLES to confirm: ").strip() \
                    != "DELETE ROLES":
                say("Stopped. Nothing changed.")
                return 1
        if o.delete_archived:
            say("You asked to DELETE the archived channels. The backup keeps only their last "
                f"{o.backup_messages} messages each{' (NONE: --backup-messages 0)' if o.backup_messages <= 0 else ''}.")
            if ask(f"Type the server's name ({old_name}) to confirm: ").strip() != old_name.strip() or not old_name:
                say("Stopped. Nothing changed.")
                return 1

        say("\nBacking up first...")
        folder = backup(api, gid, max(0, o.backup_messages))
        say(f"Backup: {folder}")

        api.allow_writes = True
        say("\nChanging the server...")
        work = Rebrand(api, gid, o, apply=True)
        work.run()
        (folder / "what-changed.txt").write_text(
            "\n".join(f"[{s}] {'* ' if c else ''}{t}" for s, t, c in work.lines) + "\n", encoding="utf-8")
        say(f"Done: {work.changes} change(s)." if work.changes else "Nothing needed changing.")

        w, h, copied = write_drafts(folder)
        say("")
        say("Your #welcome message is a draft for YOU to post (it should come from you, not the bot):")
        say(f"  {w}" + ("  (also copied to the clipboard)" if copied else ""))
        say("  Fill in the TODO(owner) lines, paste it into #welcome, then hover it -> ... -> Pin Message.")
        say(f"The #help 'Getting in' note: {h}  (paste into #help and pin it the same way)")
        say("")
        say("Do these by hand:")
        for s, t, _ in work.lines:
            if s == "manual":
                say("  - " + t)
        return 0
    except ApiError as e:
        say(f"\nStopped: {e}")
        if e.status == 403:
            say("The bot needs the Administrator permission, and its role must be at the top of the role list "
                "(Server Settings -> Roles: drag the bot's role to the top). Then run this again; it carries on.")
        return 2
    except KeyboardInterrupt:
        say("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
