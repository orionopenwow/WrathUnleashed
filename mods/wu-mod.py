#!/usr/bin/env python3
"""wu-mod: check, scaffold and pack WrathUnleashed mod packages.

    python3 wu-mod.py check <dir|zip>      validate a mod package (exit 1 on errors)
    python3 wu-mod.py new <id> [--dir D]   make a new mod from the template
    python3 wu-mod.py pack <dir> [-o D]    check, then write <id>-<version>.zip and .sha256

Python 3.8+, standard library only. Uses `luac5.1 -p` for Lua syntax when it is installed,
otherwise a small built-in parser (set WU_MOD_NO_LUAC=1 to force the built-in one).
See SPEC.md for the format and README-modders.md for a walkthrough.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

TOOL_VERSION = "0.1.0"
WU_CURRENT = "1.0.0"          # the newest WrathUnleashed version this checker knows about
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(HERE, "template")
TEMPLATE_ID = "dalaran-dice"

MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 2000

REQUIRED_FIELDS = ["id", "name", "version", "author", "licence", "kind", "wu", "description"]
OPTIONAL_FIELDS = ["permissions", "screenshots", "links"]
KINDS = ("ui", "realm", "both")
PERMISSIONS = ("commands", "gossip", "spawns", "events", "chat", "db", "timers")
TOP_LEVEL_OK = {"mod.json", "ui", "realm", "assets", "tests", "README.md", "README.txt",
                "LICENSE", "LICENSE.txt", "LICENSE.md", "CHANGELOG.md", ".gitignore"}
IGNORED_NAMES = {".git", "__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini", ".gitignore"}

# Blizzard game-data formats. Never allowed anywhere in a package, whatever the name says.
BLOCKED_EXT = {".mpq": "MPQ archive", ".blp": "BLP texture", ".m2": "M2 model", ".wmo": "WMO world model",
               ".adt": "ADT terrain tile", ".dbc": "DBC client database", ".skin": "M2 skin file",
               ".anim": "M2 animation file", ".wdt": "WDT map file", ".wdl": "WDL map file",
               ".db2": "DB2 client database", ".bls": "BLS shader"}
BLOCKED_MAGIC = [(b"MPQ\x1a", "MPQ archive"), (b"MPQ\x1b", "MPQ archive"), (b"BLP1", "BLP texture"),
                 (b"BLP2", "BLP texture"), (b"MD20", "M2 model"), (b"MD21", "M2 model"),
                 (b"WDBC", "DBC client database"), (b"REVM", "WMO/ADT/WDT chunk file")]
SCREENSHOT_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# Common SPDX licence ids. Anything else gets a warning, not an error (LicenseRef-* is accepted).
SPDX_IDS = {"0BSD", "AGPL-3.0-only", "AGPL-3.0-or-later", "Apache-2.0", "Artistic-2.0", "BSD-2-Clause",
            "BSD-3-Clause", "BSL-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0",
            "CC0-1.0", "EPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
            "ISC", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later", "MIT",
            "MIT-0", "MPL-2.0", "OFL-1.1", "Unlicense", "WTFPL", "Zlib"}
SPDX_DEPRECATED = {"GPL-2.0": "GPL-2.0-only", "GPL-3.0": "GPL-3.0-only", "LGPL-2.1": "LGPL-2.1-only",
                   "LGPL-3.0": "LGPL-3.0-only", "AGPL-3.0": "AGPL-3.0-only", "GPLv3": "GPL-3.0-only",
                   "GPLv2": "GPL-2.0-only", "Apache 2.0": "Apache-2.0", "BSD": "BSD-3-Clause"}

ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                       r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
WU_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$")

# ---------------------------------------------------------------- realm API tables (mod-ale)

# Player events whose handlers mod-ale runs through CallAllFunctionsBool(..., default false):
# a handler that returns nil (or anything that is not a boolean) counts as "false" = deny.
CAN_PLAYER_EVENTS = {48: "ON_CAN_INIT_TRADE", 49: "ON_CAN_SEND_MAIL", 50: "ON_CAN_JOIN_LFG",
                     55: "ON_CAN_GROUP_INVITE", 59: "ON_CAN_RESURRECT", 60: "ON_CAN_UPDATE_SKILL"}
EVENT_CONSTANTS = {"PLAYER_EVENT_ON_LOGIN": 3, "PLAYER_EVENT_ON_LOGOUT": 4, "PLAYER_EVENT_ON_CHAT": 18,
                   "PLAYER_EVENT_ON_WHISPER": 19, "PLAYER_EVENT_ON_GROUP_CHAT": 20,
                   "PLAYER_EVENT_ON_GUILD_CHAT": 21, "PLAYER_EVENT_ON_CHANNEL_CHAT": 22,
                   "PLAYER_EVENT_ON_FIRST_LOGIN": 30, "PLAYER_EVENT_ON_COMMAND": 42,
                   "ADDON_EVENT_ON_MESSAGE": 30}
EVENT_CONSTANTS.update({"PLAYER_EVENT_" + v: k for k, v in CAN_PLAYER_EVENTS.items()})

PLAYER_EVENT_PERMISSION = {42: "commands", 18: "chat", 19: "chat", 20: "chat", 21: "chat", 22: "chat"}
SERVER_EVENT_PERMISSION = {30: "chat"}
REGISTER_EVENTS = {"RegisterServerEvent", "RegisterPlayerEvent", "RegisterGuildEvent", "RegisterGroupEvent",
                   "RegisterCreatureEvent", "RegisterUniqueCreatureEvent", "RegisterAllCreatureEvent",
                   "RegisterGameObjectEvent", "RegisterItemEvent", "RegisterBGEvent", "RegisterMapEvent",
                   "RegisterInstanceEvent", "RegisterTicketEvent", "RegisterSpellEvent"}
REGISTER_GOSSIP = {"RegisterCreatureGossipEvent", "RegisterGameObjectGossipEvent",
                   "RegisterItemGossipEvent", "RegisterPlayerGossipEvent"}
GLOBAL_CALL_PERMISSION = {"PerformIngameSpawn": "spawns", "SendWorldMessage": "chat",
                          "CharDBExecute": "db", "CharDBQuery": "db", "CharDBQueryAsync": "db",
                          "WorldDBExecute": "db", "WorldDBQuery": "db", "WorldDBQueryAsync": "db",
                          "CreateLuaEvent": "timers"}
METHOD_CALL_PERMISSION = {"SpawnCreature": "spawns", "SummonGameObject": "spawns",
                          "SendAddonMessage": "chat", "SendChatMessageToPlayer": "chat",
                          "SendUnitSay": "chat", "SendUnitYell": "chat", "SendUnitEmote": "chat",
                          "SendUnitWhisper": "chat", "Say": "chat", "Yell": "chat",
                          "RegisterEvent": "timers"}
OVMOD_PERMISSION = {"Send": "chat", "On": "chat"}  # OVMod.Send / OVMod.On (ov_modapi.lua)
SQL_CALLS = {"CharDBExecute", "CharDBQuery", "CharDBQueryAsync", "WorldDBExecute", "WorldDBQuery",
             "WorldDBQueryAsync"}

FORBIDDEN_GLOBALS = {
    "io": "file access is not allowed in realm mods",
    "loadstring": "running code built from strings is not allowed",
    "load": "running code built from strings is not allowed",
    "loadfile": "loading other files is not allowed; put your code in realm/",
    "dofile": "loading other files is not allowed; put your code in realm/",
    "require": "loading modules is not allowed; use the globals the realm provides (for example OVMod)",
    "module": "module() is not allowed; use local tables",
    "debug": "the debug library is not allowed",
    "package": "the package library is not allowed",
    "setfenv": "changing function environments is not allowed",
    "getfenv": "reading function environments is not allowed",
    "_G": "reaching into the global table is not allowed; use local variables",
    "collectgarbage": "collectgarbage can stall the whole server",
    "HttpRequest": "network access is not allowed in realm mods",
    "RunCommand": "running GM console commands is not allowed",
    "AuthDBExecute": "the auth (accounts) database is off limits",
    "AuthDBQuery": "the auth (accounts) database is off limits",
    "AuthDBQueryAsync": "the auth (accounts) database is off limits",
    "RegisterPacketEvent": "raw packet hooks are not allowed in this version; use OVMod messages",
    "ReloadALE": "reloading the Lua engine is not allowed",
    "ReloadEluna": "reloading the Lua engine is not allowed",
    "Ban": "banning is for staff, not mods",
    "Kick": "kicking is for staff, not mods",
}
OS_ALLOWED = {"time", "clock", "date", "difftime"}

LUA_KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
                "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}
BLOCK_OPEN = {"function", "if", "do", "repeat"}
BLOCK_CLOSE = {"end", "until"}


# ---------------------------------------------------------------- reporting

DEFAULT_FIX = {
    "manifest-json": "make mod.json one JSON object: { \"id\": \"my-mod\", ... }",
    "manifest-field": "set it to a short piece of text, e.g. \"name\": \"My Mod\"",
    "manifest-wu": "use the oldest WrathUnleashed version the mod works with, e.g. \"wu\": \"1.0\"",
    "manifest-kind": "use \"ui\" (addon only), \"realm\" (server only) or \"both\"",
    "manifest-permissions": "use a list such as [\"commands\", \"chat\"] (see SPEC.md for the vocabulary)",
    "manifest-screenshots": "use a list of .png/.jpg/.webp paths inside the package, e.g. [\"assets/shot.png\"]",
    "manifest-links": "use a list of https:// URLs or {\"label\": ..., \"url\": \"https://...\"} objects",
    "layout-symlink": "copy the real file or folder in instead of linking to it",
    "layout-size": "remove large or generated files; keep packages under 50 MB",
    "zip": "rebuild the zip with `wu-mod.py pack <folder>`",
    "input": "pass the mod folder (the one with mod.json) or a .zip made by `wu-mod.py pack`",
}


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, code, where, msg, fix=None):
        self.items.append((level, code, where, msg, fix))

    def error(self, code, where, msg, fix=None):
        self.add("ERROR", code, where, msg, fix or DEFAULT_FIX.get(code, "see SPEC.md"))

    def warn(self, code, where, msg, fix=None):
        self.add("WARN", code, where, msg, fix)

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    def codes(self, level=None):
        return {i[1] for i in self.items if level is None or i[0] == level}

    def print(self, out=sys.stdout):
        for level, code, where, msg, fix in self.items:
            out.write("%-5s %s  [%s] %s\n" % (level, where or "-", code, msg))
            if fix:
                out.write("      fix: %s\n" % fix)


# ---------------------------------------------------------------- Lua tokenizer

class LuaSyntaxError(Exception):
    def __init__(self, line, msg):
        Exception.__init__(self, msg)
        self.line = line
        self.msg = msg


class Tok:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind, self.value, self.line = kind, value, line

    def is_(self, kind, value=None):
        return self.kind == kind and (value is None or self.value == value)

    def __repr__(self):
        return "%s:%r@%d" % (self.kind, self.value, self.line)


_OPS3 = ("...",)
_OPS2 = ("..", "==", "~=", "<=", ">=")
_OPS1 = set("+-*/%^#<>=(){}[];:,.")
_NUM_RE = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _long_bracket(src, i):
    """At src[i] == '[': return (level, start_of_content) for [[ or [==[, else None."""
    m = re.match(r"\[(=*)\[", src[i:i + 64])
    if not m:
        return None
    return len(m.group(1)), i + m.end()


def tokenize(src):
    toks, i, n, line = [], 0, len(src), 1
    if src.startswith("#"):              # shebang line, as lua allows
        while i < n and src[i] != "\n":
            i += 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r\f\v":
            i += 1
        elif src.startswith("--", i):
            lb = _long_bracket(src, i + 2) if i + 2 < n and src[i + 2] == "[" else None
            if lb:
                close = "]" + "=" * lb[0] + "]"
                j = src.find(close, lb[1])
                if j < 0:
                    raise LuaSyntaxError(line, "unfinished long comment")
                line += src.count("\n", i, j)
                i = j + len(close)
            else:
                while i < n and src[i] != "\n":
                    i += 1
        elif c == "[" and _long_bracket(src, i):
            level, start = _long_bracket(src, i)
            close = "]" + "=" * level + "]"
            j = src.find(close, start)
            if j < 0:
                raise LuaSyntaxError(line, "unfinished long string")
            toks.append(Tok("str", src[start:j], line))
            line += src.count("\n", i, j)
            i = j + len(close)
        elif c in "\"'":
            j, buf = i + 1, []
            while True:
                if j >= n or src[j] == "\n":
                    raise LuaSyntaxError(line, "unfinished string")
                if src[j] == "\\":
                    if j + 1 < n and src[j + 1] == "\n":
                        line += 1
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == c:
                    break
                buf.append(src[j])
                j += 1
            toks.append(Tok("str", "".join(buf), line))
            i = j + 1
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM_RE.match(src, i)
            toks.append(Tok("num", m.group(0), line))
            i = m.end()
            if i < n and (src[i].isalpha() or src[i] == "_"):
                raise LuaSyntaxError(line, "malformed number near '%s'" % src[m.start():i + 1])
        elif c.isalpha() or c == "_":
            m = _NAME_RE.match(src, i)
            w = m.group(0)
            toks.append(Tok("kw" if w in LUA_KEYWORDS else "name", w, line))
            i = m.end()
        else:
            for op in _OPS3 + _OPS2:
                if src.startswith(op, i):
                    toks.append(Tok("op", op, line))
                    i += len(op)
                    break
            else:
                if c in _OPS1:
                    toks.append(Tok("op", c, line))
                    i += 1
                else:
                    raise LuaSyntaxError(line, "unexpected symbol '%s'" % c)
    toks.append(Tok("eof", "", line))
    return toks


def minimal_parse(toks):
    """Block and bracket balance. Not a full Lua parser; luac5.1 -p is used when available."""
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for t in toks:
        if t.kind == "kw" and t.value in BLOCK_OPEN:
            stack.append((t.value, t.line))
        elif t.kind == "kw" and t.value in BLOCK_CLOSE:
            want = "repeat" if t.value == "until" else None
            if not stack or stack[-1][0] in "([{":
                raise LuaSyntaxError(t.line, "'%s' without a matching opener" % t.value)
            if (want and stack[-1][0] != want) or (not want and stack[-1][0] == "repeat"):
                raise LuaSyntaxError(t.line, "'%s' closes '%s' from line %d" % (t.value, stack[-1][0], stack[-1][1]))
            stack.pop()
        elif t.kind == "op" and t.value in "([{" and len(t.value) == 1:
            stack.append((t.value, t.line))
        elif t.kind == "op" and t.value in pairs and len(t.value) == 1:
            if not stack or stack[-1][0] != pairs[t.value]:
                raise LuaSyntaxError(t.line, "unexpected '%s'" % t.value)
            stack.pop()
    if stack:
        what, line = stack[-1]
        raise LuaSyntaxError(line, "'%s' is never closed ('end' expected)" % what if what not in "([{"
                             else "'%s' is never closed" % what)


def find_luac():
    if os.environ.get("WU_MOD_NO_LUAC"):
        return None
    for name in ("luac5.1", "luac51"):
        p = shutil.which(name)
        if p:
            return p
    p = shutil.which("luac")
    if p:
        try:
            out = subprocess.run([p, "-v"], capture_output=True, text=True, timeout=10)
            if "5.1" in (out.stdout + out.stderr):
                return p
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def check_lua_syntax(path, rel, src, report, luac):
    """Returns tokens, or None when the file does not parse."""
    if luac:
        out = subprocess.run([luac, "-p", path], capture_output=True, text=True)
        if out.returncode != 0:
            msg = (out.stderr or out.stdout).strip().splitlines()
            msg = msg[0] if msg else "syntax error"
            m = re.search(r":(\d+): (.*)$", msg)
            where = "%s:%s" % (rel, m.group(1)) if m else rel
            report.error("lua-syntax", where, m.group(2) if m else msg,
                         "fix the Lua syntax (the game uses Lua 5.1)")
            return None
    try:
        toks = tokenize(src)
        if not luac:
            minimal_parse(toks)
        return toks
    except LuaSyntaxError as e:
        report.error("lua-syntax", "%s:%d" % (rel, e.line), e.msg, "fix the Lua syntax (the game uses Lua 5.1)")
        return None


# ---------------------------------------------------------------- Lua static checks (realm)

def matching_end(toks, i):
    """toks[i] opens a block (function/if/do/repeat); return the index of its end/until."""
    depth = 0
    for j in range(i, len(toks)):
        t = toks[j]
        if t.kind == "kw" and t.value in BLOCK_OPEN:
            depth += 1
        elif t.kind == "kw" and t.value in BLOCK_CLOSE:
            depth -= 1
            if depth == 0:
                return j
    return len(toks) - 1


def call_args(toks, i):
    """toks[i] is '('. Return (list of arg token lists, index of ')')."""
    args, cur, depth, j = [], [], 0, i
    while j < len(toks):
        t = toks[j]
        if t.kind == "kw" and t.value == "function":
            e = matching_end(toks, j)
            cur.extend(toks[j:e + 1])
            j = e + 1
            continue
        if t.kind == "op" and t.value in ("(", "[", "{"):
            depth += 1
            if depth > 1:
                cur.append(t)
        elif t.kind == "op" and t.value in (")", "]", "}"):
            depth -= 1
            if depth == 0:
                if cur or args:
                    args.append(cur)
                return args, j
            cur.append(t)
        elif t.kind == "op" and t.value == "," and depth == 1:
            args.append(cur)
            cur = []
        elif t.kind == "eof":
            break
        else:
            cur.append(t)
        j += 1
    return args, j


def local_names(toks):
    names = set()
    for k, t in enumerate(toks):
        if t.is_("kw", "local"):
            j = k + 1
            if toks[j].is_("kw", "function"):
                j += 1
            while toks[j].kind == "name":
                names.add(toks[j].value)
                if toks[j + 1].is_("op", ","):
                    j += 2
                else:
                    break
        elif t.is_("kw", "function") and k + 1 < len(toks):
            # parameters: function name(a, b) / function(a, b)
            j = k + 1
            while j < len(toks) and not toks[j].is_("op", "("):
                j += 1
            j += 1
            while j < len(toks) and not toks[j].is_("op", ")"):
                if toks[j].kind == "name":
                    names.add(toks[j].value)
                j += 1
        elif t.is_("kw", "for"):
            j = k + 1
            while j < len(toks) and not (toks[j].is_("kw", "in") or toks[j].is_("op", "=")):
                if toks[j].kind == "name":
                    names.add(toks[j].value)
                j += 1
    return names


def local_constants(toks):
    """local NAME = <number> -> {NAME: int}"""
    out = {}
    for k in range(len(toks) - 3):
        if (toks[k].is_("kw", "local") and toks[k + 1].kind == "name" and toks[k + 2].is_("op", "=")
                and toks[k + 3].kind == "num" and not toks[k + 4].is_("op", ",")):
            try:
                out[toks[k + 1].value] = int(toks[k + 3].value, 0)
            except ValueError:
                pass
    return out


def resolve_event_id(arg, consts):
    if len(arg) == 1 and arg[0].kind == "num":
        try:
            return int(arg[0].value, 0)
        except ValueError:
            return None
    if len(arg) == 1 and arg[0].kind == "name":
        name = arg[0].value
        if name in consts:
            return consts[name]
        return EVENT_CONSTANTS.get(name)
    return None


def find_function_def(toks, name, before):
    """Index of the 'function' keyword that defines `name`, preferring the last one before `before`."""
    found = []
    for k in range(len(toks) - 3):
        t = toks[k]
        if t.is_("kw", "function") and toks[k + 1].is_("name", name) and toks[k + 2].is_("op", "("):
            found.append(k)
        elif (t.kind == "name" and t.value == name and toks[k + 1].is_("op", "=")
              and toks[k + 2].is_("kw", "function")):
            found.append(k + 2)
    if not found:
        return None
    earlier = [k for k in found if k < before]
    return earlier[-1] if earlier else found[-1]


def bool_expression(expr):
    """True when a return expression is certainly a boolean."""
    if not expr:
        return False
    if len(expr) == 1:
        return expr[0].kind == "kw" and expr[0].value in ("true", "false")
    depth, has_cmp, has_andor = 0, False, False
    for t in expr:
        if t.kind == "op" and t.value in ("(", "[", "{"):
            depth += 1
        elif t.kind == "op" and t.value in (")", "]", "}"):
            depth -= 1
        elif depth == 0 and t.kind == "op" and t.value in ("==", "~=", "<", ">", "<=", ">="):
            has_cmp = True
        elif depth == 0 and t.kind == "kw" and t.value in ("and", "or"):
            has_andor = True
    if has_andor:
        return False
    return expr[0].is_("kw", "not") or has_cmp


def function_returns(toks, fstart):
    """For the function whose 'function' keyword is at fstart: list of (return_tok, expr, depth, end_idx),
    and the index of the function's 'end'. Returns inside nested functions are skipped."""
    fend = matching_end(toks, fstart)
    j = fstart + 1
    while j < fend and not toks[j].is_("op", ")"):   # skip the parameter list
        j += 1
    j += 1
    depth, rets = 0, []
    while j < fend:
        t = toks[j]
        if t.is_("kw", "function"):
            j = matching_end(toks, j) + 1
            continue
        if t.kind == "kw" and t.value in BLOCK_OPEN:
            depth += 1
        elif t.kind == "kw" and t.value in BLOCK_CLOSE:
            depth -= 1
        elif t.is_("kw", "return"):
            k, expr, pd = j + 1, [], 0
            while k < fend:
                u = toks[k]
                if u.is_("kw", "function"):
                    e = matching_end(toks, k)
                    expr.extend(toks[k:e + 1])
                    k = e + 1
                    continue
                if pd == 0 and (u.kind == "kw" and u.value in ("end", "else", "elseif", "until")
                                or u.is_("op", ";")):
                    break
                if u.kind == "op" and u.value in ("(", "[", "{"):
                    pd += 1
                elif u.kind == "op" and u.value in (")", "]", "}"):
                    pd -= 1
                expr.append(u)
                k += 1
            end_idx = k + 1 if k < fend and toks[k].is_("op", ";") else k
            rets.append((t, expr, depth, end_idx))
            j = k
            continue
        j += 1
    return rets, fend


def check_can_hook(toks, fstart, rel, event_id, report):
    label = "event %d (%s)" % (event_id, CAN_PLAYER_EVENTS[event_id])
    rets, fend = function_returns(toks, fstart)
    for rtok, expr, depth, end_idx in rets:
        if not expr or (len(expr) == 1 and expr[0].is_("kw", "nil")):
            report.error("can-hook-return", "%s:%d" % (rel, rtok.line),
                         "%s handler returns nothing; mod-ale treats that as false and blocks the action "
                         "for every player" % label,
                         "write `return true` to allow or `return false` to block")
        elif not bool_expression(expr):
            report.error("can-hook-return", "%s:%d" % (rel, rtok.line),
                         "%s handler returns `%s`, which the checker cannot prove is a boolean; a non-boolean "
                         "counts as false in mod-ale" % (label, " ".join(t.value for t in expr)[:60]),
                         "return true or false literally, or a comparison such as `return x == true`")
    last_ok = any(depth == 0 and end_idx == fend for _, _, depth, end_idx in rets)
    if not last_ok:
        report.error("can-hook-return", "%s:%d" % (rel, toks[fend].line),
                     "%s handler can reach its end without a return, which mod-ale reads as false "
                     "(this is how the Dungeon Finder broke on our live realm)" % label,
                     "end the handler with `return true` (allow), after any `return false` checks")


SQL_TABLE_RE = re.compile(
    r"\b(?:FROM|INTO|(?<!KEY )(?<!ON )UPDATE|JOIN|TRUNCATE(?:\s+TABLE)?|TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?)\s+(`?[\w.$%]+`?)",
    re.IGNORECASE)
SQL_VERB_RE = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|REPLACE|TRUNCATE)\b", re.I)
SQL_BANNED_RE = re.compile(r"\b(GRANT|REVOKE|CREATE\s+USER|LOAD\s+DATA|INTO\s+OUTFILE|INTO\s+DUMPFILE|"
                           r"SET\s+GLOBAL|SHUTDOWN|CREATE\s+(?:DATABASE|SCHEMA)|DROP\s+(?:DATABASE|SCHEMA))\b",
                           re.I)


def check_sql_call(fn, arg, line, rel, prefix, report):
    strings = [t.value for t in arg if t.kind == "str"]
    where = "%s:%d" % (rel, line)
    if not strings:
        report.error("sql-literal", where, "%s(...) has no SQL text the checker can read" % fn,
                     "start the call with the SQL as a string literal, e.g. "
                     "%s(string.format(\"INSERT INTO %srolls ...\", ...))" % (fn, prefix))
        return
    sql = " ".join(strings)
    bare = re.sub(r"'(?:[^'\\]|\\.|'')*'", "''", sql)   # drop SQL string values
    if SQL_BANNED_RE.search(bare):
        report.error("sql-forbidden", where, "%s uses a statement mods may not run: %s"
                     % (fn, SQL_BANNED_RE.search(bare).group(1)), "only work with rows in your own tables")
    if re.search(r";\s*\S", bare):
        report.error("sql-forbidden", where, "%s runs more than one statement" % fn,
                     "send one statement per call")
    tables = [m.group(1).strip("`") for m in SQL_TABLE_RE.finditer(bare)]
    if not tables:
        if SQL_VERB_RE.search(bare) or not bare.strip():
            report.error("sql-literal", where, "%s: the checker cannot see which table this SQL uses" % fn,
                         "write the table name inside the string literal, not in a variable")
        return
    for tbl in tables:
        if "." in tbl:
            report.error("sql-table", where, "%s uses `%s`; mods may not name another database" % (fn, tbl),
                         "use a table named %s<something> in the realm's own database" % prefix)
        elif not tbl.lower().startswith(prefix) or len(tbl) <= len(prefix):
            report.error("sql-table", where, "%s touches table `%s`; mods may only use their own tables"
                         % (fn, tbl), "name your tables %s<something>, e.g. %srolls" % (prefix, prefix))


def check_realm_lua(toks, rel, manifest_id, declared, report, used):
    locals_ = local_names(toks)
    consts = local_constants(toks)
    prefix = "mod_" + manifest_id.replace("-", "_") + "_"

    for k, t in enumerate(toks):
        prev = toks[k - 1] if k else None
        after_dot = prev is not None and prev.kind == "op" and prev.value in (".", ":")
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        if t.kind != "name":
            continue

        # forbidden APIs
        if not after_dot and t.value in FORBIDDEN_GLOBALS and t.value not in locals_:
            report.error("forbidden-api", "%s:%d" % (rel, t.line),
                         "`%s` is not allowed in realm mods: %s" % (t.value, FORBIDDEN_GLOBALS[t.value]),
                         "remove it")
            continue
        if not after_dot and t.value == "os" and "os" not in locals_:
            if nxt and nxt.is_("op", ".") and toks[k + 2].kind == "name" and toks[k + 2].value in OS_ALLOWED:
                continue
            what = "os." + toks[k + 2].value if nxt and nxt.is_("op", ".") else "os"
            report.error("forbidden-api", "%s:%d" % (rel, t.line),
                         "`%s` is not allowed in realm mods; only os.time, os.clock, os.date and os.difftime"
                         % what, "remove it")
            continue
        if after_dot and t.value == "dump" and k >= 2 and (toks[k - 2].is_("name", "string") or prev.value == ":"):
            report.error("forbidden-api", "%s:%d" % (rel, t.line), "`string.dump` is not allowed", "remove it")
            continue

        is_call = nxt is not None and nxt.is_("op", "(")
        if not is_call:
            continue
        perm = None
        if not after_dot and t.value in locals_:
            continue
        if not after_dot and (t.value in REGISTER_EVENTS or t.value in REGISTER_GOSSIP):
            args, _ = call_args(toks, k + 1)
            if t.value in REGISTER_GOSSIP:
                perm = "gossip"
            else:
                eid = resolve_event_id(args[0], consts) if args else None
                if eid is None:
                    report.error("event-id", "%s:%d" % (rel, t.line),
                                 "%s: the checker cannot read the event id" % t.value,
                                 "pass the event id as a number, e.g. RegisterPlayerEvent(42, onCommand)")
                    perm = "events"
                elif t.value == "RegisterPlayerEvent":
                    perm = PLAYER_EVENT_PERMISSION.get(eid, "events")
                    if eid in CAN_PLAYER_EVENTS and len(args) >= 2:
                        h = args[1]
                        if h and h[0].is_("kw", "function"):
                            fstart = toks.index(h[0])
                        elif len(h) == 1 and h[0].kind == "name":
                            fstart = find_function_def(toks, h[0].value, k)
                        else:
                            fstart = None
                        if fstart is None:
                            report.error("can-hook-return", "%s:%d" % (rel, t.line),
                                         "cannot find the handler for event %d in this file" % eid,
                                         "define the handler as a local function in the same file")
                        else:
                            check_can_hook(toks, fstart, rel, eid, report)
                elif t.value == "RegisterServerEvent":
                    perm = SERVER_EVENT_PERMISSION.get(eid, "events")
                else:
                    perm = "events"
        elif not after_dot and t.value in GLOBAL_CALL_PERMISSION:
            perm = GLOBAL_CALL_PERMISSION[t.value]
            if t.value in SQL_CALLS:
                args, _ = call_args(toks, k + 1)
                check_sql_call(t.value, args[0] if args else [], t.line, rel, prefix, report)
        elif after_dot and prev.value == ":" and t.value in METHOD_CALL_PERMISSION:
            perm = METHOD_CALL_PERMISSION[t.value]
        elif (after_dot and prev.value == "." and k >= 2 and toks[k - 2].is_("name", "OVMod")
              and t.value in OVMOD_PERMISSION):
            perm = OVMOD_PERMISSION[t.value]
        if perm:
            used.setdefault(perm, (rel, t.line, t.value))
            if perm not in declared:
                report.error("permission-missing", "%s:%d" % (rel, t.line),
                             "`%s` needs the `%s` permission, which mod.json does not declare" % (t.value, perm),
                             "add \"%s\" to \"permissions\" in mod.json" % perm)

    # globals: shared Lua state, so warn about names that could collide with other scripts
    depth, brackets, ok_prefixes = 0, 0, (manifest_id.replace("-", "_").upper(), camel(manifest_id))
    for k, t in enumerate(toks):
        if t.kind == "op" and t.value in ("(", "[", "{"):
            brackets += 1
        elif t.kind == "op" and t.value in (")", "]", "}"):
            brackets -= 1
        if t.kind == "kw" and t.value in BLOCK_OPEN:
            if depth == 0 and t.value == "function" and toks[k + 1].kind == "name" \
                    and toks[k + 2].is_("op", "(") and not (k and toks[k - 1].is_("kw", "local")) \
                    and not toks[k + 1].value.startswith(ok_prefixes):
                report.warn("global", "%s:%d" % (rel, t.line),
                            "global function `%s`; all realm scripts share one Lua state" % toks[k + 1].value,
                            "write `local function %s(...)`" % toks[k + 1].value)
            depth += 1
        elif t.kind == "kw" and t.value in BLOCK_CLOSE:
            depth -= 1
        elif (depth == 0 and brackets == 0 and t.kind == "name" and toks[k + 1].is_("op", "=")
              and (k == 0 or toks[k - 1].line < t.line) and t.value not in locals_
              and not t.value.startswith(ok_prefixes)):
            report.warn("global", "%s:%d" % (rel, t.line),
                        "global variable `%s`; all realm scripts share one Lua state" % t.value,
                        "write `local %s = ...`" % t.value)


def camel(mod_id):
    return "".join(p.capitalize() for p in mod_id.split("-"))


# ---------------------------------------------------------------- manifest

def semver_tuple(v):
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", v)
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def check_licence(value, report):
    if not isinstance(value, str) or not value.strip():
        report.error("manifest-licence", "mod.json", "\"licence\" must be an SPDX licence id",
                     "for example \"MIT\", \"GPL-3.0-or-later\" or \"CC-BY-4.0\" (see spdx.org/licenses)")
        return
    if value in SPDX_DEPRECATED:
        report.error("manifest-licence", "mod.json", "\"%s\" is not an SPDX id" % value,
                     "use \"%s\"" % SPDX_DEPRECATED[value])
        return
    parts = re.split(r"\s+(?:AND|OR|WITH)\s+|[()]", value)
    for p in (x.strip() for x in parts):
        if not p:
            continue
        if p.startswith("LicenseRef-") or p in SPDX_IDS or p.rstrip("+") in SPDX_IDS:
            continue
        if not re.match(r"^[A-Za-z0-9.+-]+$", p):
            report.error("manifest-licence", "mod.json", "\"%s\" is not a valid SPDX expression" % value,
                         "use one id such as \"MIT\", or join ids with AND / OR")
            return
        report.warn("manifest-licence", "mod.json", "\"%s\" is not in the checker's list of common SPDX ids" % p,
                    "check the spelling at https://spdx.org/licenses/")


def load_manifest(root, report):
    path = os.path.join(root, "mod.json")
    if not os.path.isfile(path):
        report.error("manifest-missing", "mod.json", "no mod.json at the top of the package",
                     "create mod.json (run `wu-mod.py new <id>` for a starting point)")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except UnicodeDecodeError:
        report.error("manifest-json", "mod.json", "mod.json is not UTF-8", "save it as UTF-8")
        return None
    except json.JSONDecodeError as e:
        report.error("manifest-json", "mod.json:%d" % e.lineno, "mod.json is not valid JSON: %s" % e.msg,
                     "check for a missing comma or quote near that line")
        return None
    if not isinstance(data, dict):
        report.error("manifest-json", "mod.json", "mod.json must be a JSON object { ... }")
        return None

    if "license" in data and "licence" not in data:
        report.warn("manifest-field", "mod.json", "\"license\" is spelled \"licence\" in this format",
                    "rename the field to \"licence\"")
        data["licence"] = data.pop("license")
    for f in REQUIRED_FIELDS:
        if f not in data:
            report.error("manifest-field", "mod.json", "missing required field \"%s\"" % f,
                         "add \"%s\": ... (see SPEC.md)" % f)
    for f in data:
        if f not in REQUIRED_FIELDS and f not in OPTIONAL_FIELDS:
            report.warn("manifest-field", "mod.json", "unknown field \"%s\" (ignored)" % f,
                        "check the spelling; known fields are listed in SPEC.md")
    for f in ("name", "author", "description"):
        if f in data and (not isinstance(data[f], str) or not data[f].strip()):
            report.error("manifest-field", "mod.json", "\"%s\" must be a non-empty string" % f)
    if isinstance(data.get("name"), str) and len(data["name"]) > 48:
        report.error("manifest-field", "mod.json", "\"name\" is longer than 48 characters", "shorten it")
    if isinstance(data.get("description"), str) and len(data["description"]) > 300:
        report.error("manifest-field", "mod.json", "\"description\" is longer than 300 characters",
                     "keep it to a sentence or two; put details in README.md")

    mid = data.get("id")
    if "id" in data and (not isinstance(mid, str) or not ID_RE.match(mid) or not 3 <= len(mid) <= 32):
        report.error("manifest-id", "mod.json", "\"id\" must be 3-32 characters: lowercase letters, digits "
                     "and single dashes, starting with a letter (got %r)" % (mid,),
                     "for example \"dalaran-dice\"")
        data["id"] = None
    v = data.get("version")
    if "version" in data and (not isinstance(v, str) or not SEMVER_RE.match(v)):
        report.error("manifest-version", "mod.json", "\"version\" must be semver MAJOR.MINOR.PATCH (got %r)" % (v,),
                     "for example \"0.1.0\"")
    w = data.get("wu")
    if "wu" in data:
        if not isinstance(w, str) or not WU_RE.match(w):
            report.error("manifest-wu", "mod.json", "\"wu\" must be the minimum WrathUnleashed version, "
                         "like \"1.0\" or \"1.0.0\" (got %r)" % (w,))
        elif semver_tuple(w) > semver_tuple(WU_CURRENT):
            report.warn("manifest-wu", "mod.json", "needs WrathUnleashed %s, newer than this checker knows (%s)"
                        % (w, WU_CURRENT), "update wu-mod.py, or lower \"wu\" if that was a typo")
    if "licence" in data:
        check_licence(data["licence"], report)
    k = data.get("kind")
    if "kind" in data and k not in KINDS:
        report.error("manifest-kind", "mod.json", "\"kind\" must be \"ui\", \"realm\" or \"both\" (got %r)" % (k,))

    perms = data.get("permissions", [])
    if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
        report.error("manifest-permissions", "mod.json", "\"permissions\" must be a list of strings")
        perms = []
    for p in perms:
        if p not in PERMISSIONS:
            report.error("manifest-permissions", "mod.json", "unknown permission \"%s\"" % p,
                         "use only: " + ", ".join(PERMISSIONS))
    if len(set(perms)) != len(perms):
        report.warn("manifest-permissions", "mod.json", "a permission is listed twice")
    data["permissions"] = [p for p in perms if p in PERMISSIONS]
    if perms and k == "ui":
        report.warn("manifest-permissions", "mod.json", "a ui-only mod does not need realm permissions",
                    "remove \"permissions\", or set \"kind\" to \"both\"")

    shots = data.get("screenshots", [])
    if not isinstance(shots, list):
        report.error("manifest-screenshots", "mod.json", "\"screenshots\" must be a list of file paths")
        shots = []
    for s in shots:
        if not isinstance(s, str) or s.startswith("/") or ".." in s.replace("\\", "/").split("/"):
            report.error("manifest-screenshots", "mod.json", "screenshot %r must be a path inside the package" % (s,))
            continue
        if os.path.splitext(s)[1].lower() not in SCREENSHOT_EXT:
            report.error("manifest-screenshots", "mod.json", "screenshot %s must be .png, .jpg or .webp" % s)
        if not os.path.isfile(os.path.join(root, s)):
            report.error("manifest-screenshots", "mod.json", "screenshot %s does not exist" % s,
                         "add the file or remove it from \"screenshots\"")

    links = data.get("links", [])
    if not isinstance(links, list):
        report.error("manifest-links", "mod.json", "\"links\" must be a list")
        links = []
    for ln in links:
        url = ln.get("url") if isinstance(ln, dict) else ln
        if not isinstance(url, str) or not url.startswith("https://"):
            report.error("manifest-links", "mod.json", "link %r must be an https:// URL" % (url,),
                         "use {\"label\": \"Source\", \"url\": \"https://...\"} or a plain https:// string")
    return data


# ---------------------------------------------------------------- package walk

def walk_files(root, report):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_NAMES)
        for d in list(dirnames):
            if os.path.islink(os.path.join(dirpath, d)):
                report.error("layout-symlink", os.path.relpath(os.path.join(dirpath, d), root).replace(os.sep, "/"),
                             "symbolic links are not allowed", "copy the real folder in instead")
                dirnames.remove(d)
        for fn in sorted(filenames):
            if fn in IGNORED_NAMES:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                report.error("layout-symlink", rel, "symbolic links are not allowed", "copy the real file in instead")
                continue
            files.append(rel)
    return files


def check_blocked_files(root, files, report):
    total = 0
    for rel in files:
        full = os.path.join(root, rel)
        size = os.path.getsize(full)
        total += size
        ext = os.path.splitext(rel)[1].lower()
        if ext in BLOCKED_EXT:
            report.error("asset-blocked", rel, "%s files are Blizzard game data and cannot be in a mod"
                         % BLOCKED_EXT[ext],
                         "remove it; ship your own art (.tga for textures in ui/, .png/.ogg in assets/)")
            continue
        with open(full, "rb") as f:
            head = f.read(4)
        for magic, what in BLOCKED_MAGIC:
            if head == magic:
                report.error("asset-blocked", rel, "this file is a %s (renamed); Blizzard game data cannot be "
                             "in a mod" % what, "remove it")
                break
        if size > MAX_FILE_BYTES:
            report.error("layout-size", rel, "file is larger than %d MB" % (MAX_FILE_BYTES // 2 ** 20),
                         "make it smaller or split it")
    if total > MAX_PACKAGE_BYTES:
        report.error("layout-size", None, "package is larger than %d MB" % (MAX_PACKAGE_BYTES // 2 ** 20))
    if len(files) > MAX_FILES:
        report.error("layout-size", None, "package has more than %d files" % MAX_FILES)


def check_layout(root, files, manifest, report):
    tops = sorted({f.split("/")[0] for f in files})
    for t in tops:
        if t not in TOP_LEVEL_OK:
            report.warn("layout-unknown", t, "unexpected item at the top of the package (it will be shipped "
                        "but nothing uses it)", "move it into ui/, realm/, assets/ or tests/, or remove it")
    kind = manifest.get("kind") if manifest else None
    has_ui = any(f.startswith("ui/") for f in files)
    has_realm = any(f.startswith("realm/") for f in files)
    if kind in ("ui", "both") and not has_ui:
        report.error("layout-kind", "ui/", "kind is \"%s\" but there is no ui/ folder" % kind,
                     "add ui/<AddonName>/<AddonName>.toc, or change \"kind\"")
    if kind in ("realm", "both") and not has_realm:
        report.error("layout-kind", "realm/", "kind is \"%s\" but there is no realm/ folder" % kind,
                     "add realm/<name>.lua, or change \"kind\"")
    if kind == "ui" and has_realm:
        report.error("layout-kind", "realm/", "kind is \"ui\" but the package has a realm/ folder",
                     "set \"kind\" to \"both\", or remove realm/")
    if kind == "realm" and has_ui:
        report.error("layout-kind", "ui/", "kind is \"realm\" but the package has a ui/ folder",
                     "set \"kind\" to \"both\", or remove ui/")
    for f in files:
        if f.startswith("realm/"):
            ext = os.path.splitext(f)[1].lower()
            if ext == ".sql":
                report.error("layout-realm", f, ".sql files are not run by the realm",
                             "create your tables from Lua with CharDBExecute(\"CREATE TABLE IF NOT EXISTS mod_...\")")
            elif ext not in (".lua", ".md", ".txt"):
                report.error("layout-realm", f, "realm/ may only hold .lua files (and .md/.txt notes)",
                             "move other files to assets/")
    assets = [f for f in files if f.startswith("assets/")]
    credits = [f for f in assets if f.lower() in ("assets/credits.txt", "assets/credits.md")]
    real = [f for f in assets if f not in credits]
    if real and not credits:
        report.error("asset-credits", "assets/", "assets/ has files but no assets/CREDITS.txt",
                     "add assets/CREDITS.txt with one line per file: name, author, licence, source")
    elif real:
        with open(os.path.join(root, credits[0]), "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for f in real:
            if os.path.basename(f) not in text:
                report.error("asset-credits", f, "not listed in %s" % credits[0],
                             "add a line: %s - author - licence - source" % os.path.basename(f))


def parse_toc(text):
    meta, files = {}, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("##"):
            m = re.match(r"##\s*([^:]+):\s*(.*)$", s)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
        elif s and not s.startswith("#"):
            files.append(s.replace("\\", "/"))
    return meta, files


def check_ui(root, files, report, luac):
    ui_files = [f for f in files if f.startswith("ui/")]
    if not ui_files:
        return
    addons = sorted({f.split("/")[1] for f in ui_files if f.count("/") >= 2})
    for f in ui_files:
        if f.count("/") == 1:
            report.error("ui-layout", f, "files directly in ui/ are not loaded",
                         "put the addon in its own folder: ui/<AddonName>/")
    lower = {f.lower(): f for f in files}
    for name in addons:
        toc_rel = "ui/%s/%s.toc" % (name, name)
        if toc_rel not in files:
            report.error("ui-toc", "ui/%s/" % name, "no %s.toc in ui/%s/" % (name, name),
                         "the .toc file must have the same name as its folder")
            continue
        with open(os.path.join(root, toc_rel), "r", encoding="utf-8", errors="replace") as fh:
            meta, listed = parse_toc(fh.read())
        iface = meta.get("Interface")
        if iface != "30300":
            report.error("ui-toc", toc_rel, "## Interface must be 30300 for 3.3.5a (got %r)" % (iface,),
                         "set the first line to: ## Interface: 30300")
        if not meta.get("Title"):
            report.warn("ui-toc", toc_rel, "no ## Title line", "add: ## Title: %s" % name)
        for item in listed:
            rel = "ui/%s/%s" % (name, item)
            if rel not in files:
                hint = " (the case differs: %s)" % lower[rel.lower()] if rel.lower() in lower else ""
                report.error("ui-toc", toc_rel, "lists %s, which does not exist%s" % (item, hint),
                             "fix the file name in the .toc (names are case-sensitive in the browser client)")
    for f in ui_files:
        full = os.path.join(root, f)
        if f.endswith(".lua"):
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                check_lua_syntax(full, f, fh.read(), report, luac)
        elif f.endswith(".xml"):
            try:
                tree = ET.parse(full)
            except ET.ParseError as e:
                report.error("ui-xml", "%s:%d" % (f, e.position[0]), "XML is not well formed: %s" % e,
                             "check for an unclosed tag or a stray '&' (write &amp;)")
                continue
            base = os.path.dirname(f)
            for el in tree.iter():
                tag = el.tag.split("}")[-1]
                if tag in ("Script", "Include") and el.get("file"):
                    ref = os.path.normpath(os.path.join(base, el.get("file").replace("\\", "/"))).replace(os.sep, "/")
                    if ref not in files:
                        report.error("ui-xml", f, "<%s file=\"%s\"> points to a missing file" % (tag, el.get("file")),
                                     "fix the path (relative to the XML file)")


def check_realm(root, files, manifest, report, luac):
    lua_files = [f for f in files if f.startswith("realm/") and f.endswith(".lua")]
    if not lua_files or not manifest or not manifest.get("id"):
        return
    declared = set(manifest.get("permissions", []))
    used = {}
    for f in lua_files:
        full = os.path.join(root, f)
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        toks = check_lua_syntax(full, f, src, report, luac)
        if toks is not None:
            check_realm_lua(toks, f, manifest["id"], declared, report, used)
    for p in sorted(declared - set(used)):
        report.warn("permission-unused", "mod.json", "permission \"%s\" is declared but not used" % p,
                    "remove it so players see only what the mod really does")


# ---------------------------------------------------------------- zip input

def safe_extract(zpath, dest, report):
    try:
        zf = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        report.error("zip", zpath, "not a valid zip file")
        return None
    total = 0
    with zf:
        names = zf.infolist()
        if len(names) > MAX_FILES:
            report.error("layout-size", zpath, "zip has more than %d entries" % MAX_FILES)
            return None
        for info in names:
            n = info.filename.replace("\\", "/")
            if n.startswith("/") or re.match(r"^[A-Za-z]:", n) or ".." in n.split("/"):
                report.error("zip", n, "unsafe path in zip", "rebuild the zip with `wu-mod.py pack`")
                return None
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                report.error("layout-symlink", n, "symbolic links are not allowed in the zip")
                return None
            total += info.file_size
            if total > MAX_PACKAGE_BYTES:
                report.error("layout-size", zpath, "zip unpacks to more than %d MB" % (MAX_PACKAGE_BYTES // 2 ** 20))
                return None
        zf.extractall(dest)
    if os.path.isfile(os.path.join(dest, "mod.json")):
        return dest
    entries = [e for e in os.listdir(dest) if e not in IGNORED_NAMES and e != "__MACOSX"]
    if len(entries) == 1 and os.path.isfile(os.path.join(dest, entries[0], "mod.json")):
        return os.path.join(dest, entries[0])
    return dest


# ---------------------------------------------------------------- commands

def check_package(path):
    report = Report()
    tmp = None
    try:
        if os.path.isfile(path) and path.lower().endswith(".zip"):
            tmp = tempfile.mkdtemp(prefix="wu-mod-")
            root = safe_extract(path, tmp, report)
            if root is None:
                return report
        elif os.path.isdir(path):
            root = path
        else:
            report.error("input", path, "not a folder or a .zip file")
            return report
        luac = find_luac()
        files = walk_files(root, report)
        manifest = load_manifest(root, report)
        check_blocked_files(root, files, report)
        check_layout(root, files, manifest, report)
        check_ui(root, files, report, luac)
        check_realm(root, files, manifest, report, luac)
        report.manifest = manifest
        report.root = root
        report.luac = luac
        return report
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def cmd_check(path):
    report = check_package(path)
    report.print()
    n_err = len(report.errors)
    n_warn = len(report.items) - n_err
    parser = "luac5.1 -p" if getattr(report, "luac", None) else "built-in parser"
    if n_err:
        print("\n%s: %d error(s), %d warning(s). Fix the errors above and run check again." % (path, n_err, n_warn))
        return 1
    print("%s: OK (%d warning(s); Lua checked with %s)" % (path, n_warn, parser))
    return 0


def cmd_new(mod_id, parent):
    if not ID_RE.match(mod_id) or not 3 <= len(mod_id) <= 32:
        print("error: id must be 3-32 characters of lowercase letters, digits and single dashes, "
              "starting with a letter, e.g. my-mod", file=sys.stderr)
        return 2
    dest = os.path.join(parent, mod_id)
    if os.path.exists(dest):
        print("error: %s already exists" % dest, file=sys.stderr)
        return 2
    words = mod_id.split("-")
    subs = [(TEMPLATE_ID, mod_id),
            (TEMPLATE_ID.replace("-", "_").upper(), mod_id.replace("-", "_").upper()),
            (TEMPLATE_ID.replace("-", "_"), mod_id.replace("-", "_")),
            (camel(TEMPLATE_ID), camel(mod_id)),
            ("Dalaran Dice", " ".join(w.capitalize() for w in words))]

    def sub(s):
        for a, b in subs:
            s = s.replace(a, b)
        return s

    for dirpath, dirnames, filenames in os.walk(TEMPLATE_DIR):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_NAMES]
        rel_dir = os.path.relpath(dirpath, TEMPLATE_DIR)
        out_dir = os.path.join(dest, sub(rel_dir)) if rel_dir != "." else dest
        os.makedirs(out_dir, exist_ok=True)
        for fn in filenames:
            if fn in IGNORED_NAMES:
                continue
            src = os.path.join(dirpath, fn)
            out = os.path.join(out_dir, sub(fn))
            try:
                with open(src, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except UnicodeDecodeError:
                shutil.copyfile(src, out)
                continue
            if fn == "mod.json":
                data = json.loads(text)
                data.update({"id": mod_id, "name": " ".join(w.capitalize() for w in words), "version": "0.1.0",
                             "author": "Your Name", "description": "Describe what %s does in a sentence." % mod_id})
                text = json.dumps(data, indent=2) + "\n"
            else:
                text = sub(text)
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
    print("Created %s from the dalaran-dice template." % dest)
    print("Next: edit mod.json, then run:  python3 %s check %s" % (os.path.relpath(__file__), dest))
    return 0


ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def cmd_pack(path, out_dir):
    report = check_package(path)
    if report.errors:
        report.print()
        print("\nNot packed: fix the errors above first.")
        return 1
    m = report.manifest
    root = report.root
    files = walk_files(root, Report())
    name = "%s-%s.zip" % (m["id"], m["version"])
    os.makedirs(out_dir, exist_ok=True)
    zpath = os.path.join(out_dir, name)
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in sorted(files):
            info = zipfile.ZipInfo("%s/%s" % (m["id"], rel), date_time=ZIP_EPOCH)
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            with open(os.path.join(root, rel), "rb") as fh:
                zf.writestr(info, fh.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    h = hashlib.sha256()
    with open(zpath, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with open(zpath + ".sha256", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s  %s\n" % (digest, name))
    n_warn = len(report.items)
    print("Packed %s (%d files, %d warning(s))" % (zpath, len(files), n_warn))
    print("sha256 %s" % digest)
    return 0


USAGE = """usage:
  wu-mod.py check <dir|zip>       validate a mod package
  wu-mod.py new <id> [--dir D]    create a mod from the template (in D, default: current folder)
  wu-mod.py pack <dir> [-o D]     check, then write <id>-<version>.zip and .sha256 (in D, default: current folder)
  wu-mod.py --version
"""


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if argv else 2
    if argv[0] == "--version":
        print("wu-mod %s (WrathUnleashed %s)" % (TOOL_VERSION, WU_CURRENT))
        return 0
    cmd, rest = argv[0], argv[1:]

    def opt(flags, default):
        for f in flags:
            if f in rest:
                i = rest.index(f)
                if i + 1 >= len(rest):
                    raise SystemExit("error: %s needs a value" % f)
                val = rest[i + 1]
                del rest[i:i + 2]
                return val
        return default

    if cmd == "check" and len(rest) == 1:
        return cmd_check(rest[0])
    if cmd == "new":
        d = opt(("--dir", "-d"), ".")
        if len(rest) == 1:
            return cmd_new(rest[0], d)
    if cmd == "pack":
        d = opt(("-o", "--out"), ".")
        if len(rest) == 1:
            return cmd_pack(rest[0], d)
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
