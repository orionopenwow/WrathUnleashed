#!/usr/bin/env python3
"""WrathUnleashed GM console: one owner-only page to run the live server.

Runs in its own container (wu-gmconsole, see gmconsole-install.sh) on the host's network and
listens on 127.0.0.1:8099 ONLY. Nothing public routes to it: the owner reaches it through the SSH
tunnel "Open GM Console.bat" opens (ssh -L 8099:127.0.0.1:8099).

Auth: the token in /srv/wrath/gmconsole.env (GM_TOKEN=..., chmod 600, made at install). The
.bat reads it over the tunnel's own SSH connection and opens /login?t=<token> once; that sets a
session cookie (HttpOnly, SameSite=Strict) and redirects to /. Without the cookie every path is
401. Every POST needs the session's CSRF token (X-CSRF header) and a JSON body; destructive
actions also need "confirm": true (the page asks first). The Host header must be 127.0.0.1:8099
or localhost:8099 (no DNS rebinding).

It does its work with the server's own tools:
  * SOAP console commands through /srv/wrath/soap-cmd.sh (its password never enters this process)
  * MySQL through `docker exec ov-ac-database ... mysql` (the container's own MYSQL_ROOT_PASSWORD)
  * docker / docker compose through the mounted docker.sock
  * stream-switch.sh and stream-lib.sh's recreate_portal for streaming and the sign-in page
Every action is written to /srv/wrath/gmconsole-audit.log. Secrets are scrubbed from everything it
shows or writes. It never deletes characters or accounts and never drops tables.

Bug reports: ov_bug_reports (ov_reports.lua) and gm_ticket are read; the one write is
ov_bug_reports.status. GET /api/export/new-reports returns the new ones as JSON for a scheduled
triage task: loopback only, "Authorization: Bearer <GM_TOKEN>" (no cookie needed).

stdlib only (python:3.12-alpine).
"""
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

E = os.environ.get
WU = E("GM_WU_DIR", "/srv/wrath")
ST = E("GM_STREAM_DIR", WU + "/stream")
REALM_DIR = E("GM_REALM_DIR", "/opt/wenilla-realm")
CADDYFILE = E("GM_CADDYFILE", "/opt/openvanilla-classicplus/Caddyfile")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
# The shared WrathUnleashed look (a copy of stream/www-files/art: wu-theme.css, the starfield, corners, dragons,
# divider, Cinzel), served at /static/art/<name> from this list only, without the login (it is our own art).
ART_DIR = E("GM_ART_DIR", os.path.join(STATIC_DIR, "art"))
ART_TYPES = {
    "wu-theme.css": "text/css; charset=utf-8",
    "wu-load-orion.webp": "image/webp", "wu-load-bg.webp": "image/webp", "wu-card.webp": "image/webp",
    "wu-corner-tl.webp": "image/webp", "wu-corner-tr.webp": "image/webp",
    "wu-corner-bl.webp": "image/webp", "wu-corner-br.webp": "image/webp",
    "wu-divider.webp": "image/webp", "wu-dragon-l.webp": "image/webp", "wu-dragon-r.webp": "image/webp",
    "Cinzel-SemiBold.woff2": "font/woff2", "Cinzel-OFL.txt": "text/plain; charset=utf-8",
}


def art_bytes(name):
    """One file from the allow-list, or None. The name is only ever a key of ART_TYPES, never a path."""
    if name not in ART_TYPES:
        return None
    try:
        with open(os.path.join(ART_DIR, name), "rb") as f:
            return f.read(4_000_000)
    except OSError:
        return None
TOKEN_FILE = E("GM_TOKEN_FILE", WU + "/gmconsole.env")
AUDIT_FILE = E("GM_AUDIT_FILE", WU + "/gmconsole-audit.log")
SPEED_FILE = E("GM_SPEED_FILE", WU + "/gmconsole-speed.json")
BIND = E("GM_BIND", "127.0.0.1")
PORT = int(E("GM_PORT", "8099"))
DOCKER = E("GM_DOCKER", "docker")
PUBLIC_HOST = E("GM_PUBLIC_HOST", "play.openvanilla.app")
PUBLIC_URL = E("GM_PUBLIC_URL", "https://" + PUBLIC_HOST).rstrip("/")
STREAM_URL = E("GM_STREAM_URL", "https://wrath.openvanilla.app").rstrip("/")
SITE_URL = E("GM_SITE_URL", "https://openvanilla.app").rstrip("/")
STATUS_URL = E("GM_STATUS_URL", PUBLIC_URL + "/wrath/status.json")
FEED_URL = E("GM_FEED_URL", PUBLIC_URL + "/community/feed.json")
RELAY_HOST = E("GM_RELAY_HOST", "relay.openvanilla.app")
RELAY_URL = E("GM_RELAY_URL", "https://" + RELAY_HOST + "/healthz")
PLAY_URL = E("GM_PLAY_URL", "").rstrip("/")   # wu-play's origin; empty = its container address
SLUG = E("GM_REALM_SLUG", "wrathunleashed")
BOT_PREFIX = E("GM_BOT_PREFIX", "RNDBOT")      # mod-playerbots: AiPlayerbot.RandomBotAccountPrefix (upper case)
TIME_SCALE = float(E("GM_TIME_SCALE", "1"))    # tests run countdowns faster
EXTRA_HOSTS = {h.strip() for h in E("GM_EXTRA_HOSTS", "").split(",") if h.strip()}
DISK_WARN = 3 * 1024 ** 3
SESSION_TTL = 12 * 3600
WORLD = "ov-ac-worldserver"
DB = "ov-ac-database"
SITE_ORIGIN = SITE_URL

if BIND not in ("127.0.0.1", "::1", "localhost"):
    sys.exit("gmconsole: GM_BIND must be a loopback address; it is never served publicly")


# ----------------------------------------------------------------------------------------------
# Secrets: loaded only to check the login and to scrub them from anything shown or written
# ----------------------------------------------------------------------------------------------

def read_kv(path):
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip().replace("\r", "")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def load_token():
    t = read_kv(TOKEN_FILE).get("GM_TOKEN", "")
    if len(t) < 32:
        sys.exit("gmconsole: no GM_TOKEN (32+ chars) in %s: run gmconsole-install.sh" % TOKEN_FILE)
    return t


TOKEN = load_token()
_SECRETS = set()


def refresh_secrets():
    s = {TOKEN}
    for p, keys in ((WU + "/signup.env", ("SOAP_PASS",)), (WU + "/portal.env", ("SOAP_PASS", "SESSION_SECRET", "GATE_SECRET")),
                    (WU + "/.env", ("DB_ROOT_PASSWORD",))):
        kv = read_kv(p)
        for k, v in kv.items():
            if k in keys or re.search(r"(PASS|SECRET|TOKEN|KEY)$", k):
                if len(v) >= 6:
                    s.add(v)
    _SECRETS.clear()
    _SECRETS.update(s)


refresh_secrets()


def redact(text):
    if not text:
        return text or ""
    for s in _SECRETS:
        if s and s in text:
            text = text.replace(s, "[hidden]")
    return text


# ----------------------------------------------------------------------------------------------
# Running the server's tools
# ----------------------------------------------------------------------------------------------

def run(argv, input=None, timeout=60, cwd=None, env=None, merge=True):
    """(returncode, stdout[, +stderr]) with secrets scrubbed. Never raises for a failed command."""
    e = dict(os.environ)
    e.pop("GM_TOKEN", None)
    if env:
        e.update(env)
    try:
        p = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd, env=e, errors="replace")
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ss" % timeout
    except OSError as ex:
        return 127, "%s could not run (%s)" % (argv[0], ex.strerror or ex)
    out = p.stdout + (p.stderr if merge else "")
    return p.returncode, redact(out)


def soap(cmd, timeout=40):
    rc, out = run(["bash", WU + "/soap-cmd.sh", cmd], timeout=timeout)
    return rc == 0, out.strip()


MYSQL_SH = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B --default-character-set=utf8mb4 '


def sql(db, query):
    """Rows of a read query, run inside the database container (its own root password)."""
    rc, out = run([DOCKER, "exec", "-i", DB, "sh", "-c", MYSQL_SH + db], input=query, timeout=30, merge=False)
    if rc != 0:
        raise ToolError("database query failed (is %s running?)" % DB)
    rows = []
    for line in out.splitlines():
        if line:
            rows.append([None if c == "NULL" else c.replace("\\t", "\t").replace("\\n", " ").replace("\\\\", "\\")
                         for c in line.split("\t")])
    return rows


def docker(*args, timeout=60, cwd=None):
    return run([DOCKER, *args], timeout=timeout, cwd=cwd)


class ToolError(Exception):
    pass


class Bad(Exception):
    """A request the console refuses (400)."""


class Busy(Exception):
    pass


_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn, fresh=False):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and not fresh and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (time.monotonic(), val)
    return val


def drop_cache(*prefixes):
    with _cache_lock:
        for k in list(_cache):
            if any(k.startswith(p) for p in prefixes):
                del _cache[k]


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean_lines(text):
    return [_ANSI.sub("", ln).rstrip("\r") for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]


# ----------------------------------------------------------------------------------------------
# Containers
# ----------------------------------------------------------------------------------------------

EXPECTED = [
    ("ov-ac-database", "Database (MySQL 8.4)", None),
    ("ov-ac-authserver", "Auth server (3724)", None),
    ("ov-ac-worldserver", "World server (8085, SOAP)", None),
    ("wu-portal", "Sign-in page /wrath", None),
    ("wu-play", "Stream slice host", None),
    ("caddy", "Web front (Caddy)", ("wenilla-realm", "caddy")),
    ("realm", "Site sign-in (ovlive-realm)", ("wenilla-realm", "realm")),
    ("wu-gmconsole", "This console", None),
]


def list_containers():
    rc, out = docker("ps", "-a", "--no-trunc", "--format", "{{json .}}", timeout=20)
    if rc != 0:
        raise ToolError("docker ps failed: " + out[:200])
    items = []
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        labels = {}
        for part in (d.get("Labels") or "").split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                labels[k] = v
        items.append({"name": d.get("Names", ""), "state": d.get("State", ""), "status": d.get("Status", ""),
                      "image": d.get("Image", ""), "project": labels.get("com.docker.compose.project", ""),
                      "service": labels.get("com.docker.compose.service", "")})
    return items


def containers():
    return cached("containers", 5, list_containers)


def find_container(key):
    """The container name for an EXPECTED key (compose services found by their labels)."""
    for k, _label, comp in EXPECTED:
        if k != key:
            continue
        for c in containers():
            if comp and c["project"] == comp[0] and c["service"] == comp[1]:
                return c["name"]
            if not comp and c["name"] == k:
                return c["name"]
        if comp:
            for c in containers():
                if c["service"] == comp[1] or c["name"].endswith("-" + comp[1] + "-1"):
                    return c["name"]
    return None


def health(c):
    if not c:
        return "missing"
    if c["state"] != "running":
        return "down"
    st = c["status"].lower()
    if "unhealthy" in st:
        return "unhealthy"
    if "starting" in st or "restarting" in st:
        return "starting"
    return "ok"


def container_table():
    by = {c["name"]: c for c in containers()}
    rows, seen = [], set()
    for key, label, _comp in EXPECTED:
        name = find_container(key)
        c = by.get(name) if name else None
        seen.add(name)
        rows.append({"key": key, "label": label, "name": name or key, "health": health(c),
                     "status": c["status"] if c else "not found", "image": c["image"] if c else ""})
    others = [{"key": c["name"], "label": "other", "name": c["name"], "health": "other", "status": c["status"],
               "image": c["image"]} for c in containers() if c["name"] not in seen]
    return rows, others


def inspect(name, fmt):
    rc, out = docker("inspect", "-f", fmt, name, timeout=15)
    return out.strip() if rc == 0 else ""


def started_at(name):
    return inspect(name, "{{.State.StartedAt}}")


def iso_to_epoch(s):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", s or "")
    if not m:
        return None
    import calendar
    return calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))


def play_origin():
    if PLAY_URL:
        return PLAY_URL
    ip = inspect("wu-play", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}").split()
    return "http://%s:8090" % ip[0] if ip else ""


# ----------------------------------------------------------------------------------------------
# Realm
# ----------------------------------------------------------------------------------------------

RACES = {1: "Human", 2: "Orc", 3: "Dwarf", 4: "Night Elf", 5: "Undead", 6: "Tauren", 7: "Gnome", 8: "Troll",
         10: "Blood Elf", 11: "Draenei"}
CLASSES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest", 6: "Death Knight", 7: "Shaman",
           8: "Mage", 9: "Warlock", 11: "Druid"}
ZONES = {1: "Dun Morogh", 3: "Badlands", 10: "Duskwood", 11: "Wetlands", 12: "Elwynn Forest", 14: "Durotar",
         15: "Dustwallow Marsh", 17: "The Barrens", 28: "Western Plaguelands", 33: "Stranglethorn Vale",
         38: "Loch Modan", 40: "Westfall", 44: "Redridge Mountains", 45: "Arathi Highlands", 65: "Dragonblight",
         66: "Zul'Drak", 67: "The Storm Peaks", 85: "Tirisfal Glades", 130: "Silverpine Forest", 141: "Teldrassil",
         148: "Darkshore", 210: "Icecrown", 215: "Mulgore", 267: "Hillsbrad Foothills", 331: "Ashenvale",
         394: "Grizzly Hills", 405: "Desolace", 440: "Tanaris", 490: "Un'Goro Crater", 495: "Howling Fjord",
         1377: "Silithus", 1497: "Undercity", 1519: "Stormwind City", 1537: "Ironforge", 1637: "Orgrimmar",
         1638: "Thunder Bluff", 1657: "Darnassus", 2597: "Alterac Valley", 2817: "Crystalsong Forest",
         3277: "Warsong Gulch", 3358: "Arathi Basin", 3430: "Eversong Woods", 3433: "Ghostlands",
         3483: "Hellfire Peninsula", 3487: "Silvermoon City", 3518: "Nagrand", 3519: "Terokkar Forest",
         3520: "Shadowmoon Valley", 3521: "Zangarmarsh", 3522: "Blade's Edge Mountains", 3523: "Netherstorm",
         3524: "Azuremyst Isle", 3525: "Bloodmyst Isle", 3537: "Borean Tundra", 3557: "The Exodar",
         3703: "Shattrath City", 3711: "Sholazar Basin", 3820: "Eye of the Storm", 4080: "Isle of Quel'Danas",
         4197: "Wintergrasp", 4298: "Scarlet Enclave (Ebon Hold)", 4378: "Dalaran Arena", 4384: "Strand of the Ancients",
         4395: "Dalaran", 4406: "Ring of Valor", 4710: "Isle of Conquest", 4722: "Trial of the Crusader",
         4812: "Icecrown Citadel", 3456: "Naxxramas", 4493: "The Obsidian Sanctum", 4603: "Vault of Archavon",
         4415: "The Violet Hold", 206: "Utgarde Keep", 4100: "Culling of Stratholme"}

_RE_CONNECTED = re.compile(r"Connected players:\s*(\d+)", re.I)
_RE_PEAK = re.compile(r"Connected players:\s*\d+\s*\(peak:\s*(\d+)", re.I)
_RE_CHARS = re.compile(r"Characters in world:\s*(\d+)", re.I)
_RE_UPTIME = re.compile(r"uptime:\s*([^\r\n]*)", re.I)
_RE_UPART = re.compile(r"(\d+)\s*(day|hour|minute|second|d|h|m|s)", re.I)
_RE_DIFF = re.compile(r"Update time diff:\s*(\d+)\s*ms", re.I)
_RE_MEAN = re.compile(r"Mean:\s*(\d+)\s*ms", re.I)
_RE_MEDIAN = re.compile(r"Median:\s*(\d+)\s*ms", re.I)
_RE_PCT = re.compile(r"Percentiles[^:]*:\s*(\d+)\s*ms,\s*(\d+)\s*ms,\s*(\d+)\s*ms", re.I)
_RE_REV = re.compile(r"(AzerothCore rev\.[^\r\n]*)", re.I)


def parse_server_info(text):
    def num(r):
        m = r.search(text)
        return int(m.group(1)) if m else None
    out = {"players": num(_RE_CONNECTED), "peak": num(_RE_PEAK), "characters": num(_RE_CHARS),
           "diff_ms": num(_RE_DIFF), "mean_ms": num(_RE_MEAN), "median_ms": num(_RE_MEDIAN),
           "p95_ms": None, "p99_ms": None, "max_ms": None, "uptime_s": None, "uptime": None, "revision": None}
    m = _RE_PCT.search(text)
    if m:
        out["p95_ms"], out["p99_ms"], out["max_ms"] = (int(x) for x in m.groups())
    m = _RE_UPTIME.search(text)
    if m:
        out["uptime"] = m.group(1).strip().rstrip(".")
        parts = _RE_UPART.findall(m.group(1))
        if parts:
            out["uptime_s"] = sum(int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u[0].lower()] for n, u in parts)
    m = _RE_REV.search(text)
    if m:
        out["revision"] = m.group(1)[:160]
    out["bots"] = max(0, out["characters"] - out["players"]) if out["characters"] is not None and out["players"] is not None else None
    return out


def server_info(fresh=False):
    def get():
        ok, text = soap("server info", timeout=15)
        d = parse_server_info(text) if ok else {}
        d["online"] = ok
        d["error"] = None if ok else (text[:200] or "no answer")
        return d
    return cached("serverinfo", 10, get, fresh)


IMPORTANT = re.compile(r"(?i)(\berror\b|\bfatal\b|crash|assert|exception|\blua\b|\.lua\b|\bale\b|eluna|failed)")


def important_logs(n=10):
    def get():
        rc, out = docker("logs", "--tail", "4000", WORLD, timeout=30)
        if rc != 0:
            return ["(no world server log: " + out[:120] + ")"]
        return [ln[:400] for ln in clean_lines(out) if IMPORTANT.search(ln)][-n:]
    return cached("implogs", 15, get)


# ----------------------------------------------------------------------------------------------
# Files on the server
# ----------------------------------------------------------------------------------------------

def mtime(p):
    try:
        return int(os.stat(p).st_mtime)
    except OSError:
        return None


def dir_size(path):
    total = files = 0
    for root, _dirs, names in os.walk(path):
        for n in names:
            try:
                st = os.lstat(os.path.join(root, n))
            except OSError:
                continue
            total += st.st_size
            files += 1
    return total, files


_build_cache = {}


def client_build(d):
    """What browser client a www folder holds: a stamp if the build has one, else a quick id."""
    if not os.path.isdir(d):
        return None
    idx = os.path.join(d, "index.html")
    wasm = None
    try:
        for n in sorted(os.listdir(d)):
            if n.endswith(".wasm"):
                wasm = os.path.join(d, n)
                break
    except OSError:
        return None
    stamp, source = None, None
    for n in ("version.txt", "BUILD", "build.txt", "build.json", ".build"):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    raw = f.read(400).strip()
                if n.endswith(".json"):
                    try:
                        j = json.loads(raw)
                        raw = str(j.get("build") or j.get("version") or j.get("commit") or raw)
                    except ValueError:
                        pass
                stamp, source = raw.splitlines()[0][:80] if raw else None, n
            except OSError:
                pass
            if stamp:
                break
    if not stamp:
        for n in ("boot.js", "index.html"):
            p = os.path.join(d, n)
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    s = f.read(200000)
            except OSError:
                continue
            m = re.search(r"""(?:__wenilla_build|BUILD_ID|build(?:Id|_id|Stamp))\s*[:=]\s*['"]([\w.\-+]{4,64})['"]""", s) \
                or re.search(r"wenilla(?:_bg\.wasm|\.js)\?v=([\w.\-]{4,64})", s)
            if m:
                stamp, source = m.group(1), n
                break
    info = {"stamp": stamp, "stamp_source": source, "index_mtime": mtime(idx), "wasm": None}
    if wasm:
        st = os.stat(wasm)
        key = (wasm, st.st_size, int(st.st_mtime))
        qid = _build_cache.get(key)
        if not qid:
            h = hashlib.sha256(str(st.st_size).encode())
            try:
                with open(wasm, "rb") as f:
                    h.update(f.read(1 << 20))
                    if st.st_size > 2 << 20:
                        f.seek(-(1 << 20), 2)
                        h.update(f.read(1 << 20))
            except OSError:
                pass
            qid = h.hexdigest()[:12]
            _build_cache[key] = qid
        info["wasm"] = {"name": os.path.basename(wasm), "bytes": st.st_size, "mtime": int(st.st_mtime), "id": qid,
                        "gz": os.path.isfile(wasm + ".gz"), "br": os.path.isfile(wasm + ".br")}
    info["id"] = stamp or (info["wasm"]["id"] if info["wasm"] else None)
    return info


def portal_env():
    return read_kv(WU + "/portal.env")


def served_slice():
    s = (portal_env().get("STREAM_SLICES") or "mini").split(",")[0].strip() or "mini"
    return s if re.match(r"^[a-z0-9-]{1,32}$", s) else "mini"


def slice_desc(name):
    try:
        with open(os.path.join(ST, "slices", name + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def slice_size(name):
    d = os.path.join(ST, "slices", name)
    if not os.path.isdir(d):
        return None
    return cached("slicesize:" + name, 600, lambda: dict(zip(("bytes", "files"), dir_size(d))))


def stream_state():
    env = portal_env()
    name = served_slice()
    desc = slice_desc(name) or {}
    tiers = desc.get("tiers") or []
    play = next((c for c in containers() if c["name"] == "wu-play"), None)
    fui_flag = env.get("WU_FOREVERUI", "1").strip() != "0"
    overlay = os.path.isdir(os.path.join(ST, "overlays", "foreverui"))
    return {
        "streaming": env.get("WU_STREAM", "0").strip() == "1",
        "ownfiles": env.get("WU_OWNFILES", "0").strip() == "1",
        "slice": name, "stream_host": env.get("STREAM_HOST", ""),
        "max_tier": desc.get("maxTier"), "tier_count": len(tiers), "budget_mb": desc.get("budgetMB"),
        "size": slice_size(name), "wu_play": health(play), "wu_play_status": play["status"] if play else "not found",
        "foreverui_flag": fui_flag, "foreverui_overlay": overlay, "foreverui": fui_flag and overlay,
        "kit": os.path.isfile(os.path.join(ST, "stream-switch.sh")),
    }


def host_stats():
    out = {}
    try:
        st = os.statvfs(WU)
        out["disk_free"] = st.f_bavail * st.f_frsize
        out["disk_total"] = st.f_blocks * st.f_frsize
    except OSError:
        out["disk_free"] = out["disk_total"] = None
    out["disk_warn"] = out["disk_free"] is not None and out["disk_free"] < DISK_WARN
    mem = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    out["mem_total"] = mem.get("MemTotal")
    out["mem_avail"] = mem.get("MemAvailable")
    try:
        with open("/proc/loadavg") as f:
            out["load"] = [float(x) for x in f.read().split()[:3]]
    except (OSError, ValueError):
        out["load"] = None
    try:
        out["cpus"] = os.cpu_count()
        with open("/proc/uptime") as f:
            out["host_uptime_s"] = int(float(f.read().split()[0]))
    except (OSError, ValueError):
        out["host_uptime_s"] = None
    return out


# ----------------------------------------------------------------------------------------------
# Jobs (long actions run in the background, one at a time) and the audit log
# ----------------------------------------------------------------------------------------------

_audit_lock = threading.Lock()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def audit(action, detail, result):
    line = "%s %s %s -> %s\n" % (now_iso(), action, json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                                  str(result).replace("\n", " ")[:300])
    line = redact(line)
    with _audit_lock:
        new = not os.path.exists(AUDIT_FILE)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        if new:
            try:
                os.chmod(AUDIT_FILE, 0o600)
            except OSError:
                pass


def audit_tail(n=60):
    try:
        with open(AUDIT_FILE, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        m = re.match(r"(\S+) (\S+) (.*) -> (.*)$", ln.rstrip("\n"))
        if m:
            out.append({"at": m.group(1), "action": m.group(2), "detail": m.group(3), "result": m.group(4)})
    return out


class Job:
    def __init__(self, name, detail):
        self.id = secrets.token_hex(4)
        self.name, self.detail = name, detail
        self.state = "running"
        self.started = now_iso()
        self.ended = None
        self.lines = []
        self.cancel = threading.Event()
        self.cancellable = False

    def log(self, text):
        for ln in redact(str(text)).splitlines() or [""]:
            self.lines.append(time.strftime("%H:%M:%S ") + ln[:500])
        del self.lines[:-400]

    def sleep(self, seconds):
        """True when cancelled while waiting."""
        return self.cancel.wait(max(0.0, seconds) * TIME_SCALE)

    def view(self):
        return {"id": self.id, "name": self.name, "state": self.state, "started": self.started, "ended": self.ended,
                "lines": self.lines[-200:], "cancellable": self.cancellable and self.state == "running"}


JOBS = []
_jobs_lock = threading.Lock()


def start_job(name, detail, fn, cancellable=False):
    with _jobs_lock:
        if any(j.state == "running" for j in JOBS):
            raise Busy("another action is still running: wait for it (Updates tab)")
        job = Job(name, detail)
        job.cancellable = cancellable
        JOBS.append(job)
        del JOBS[:-20]

    def body():
        try:
            res = fn(job)
            if job.state == "running":
                job.state = "ok" if res is not False else "failed"
        except Exception as e:  # noqa: BLE001 (any failure ends the job, never the service)
            job.log("ERROR: %s" % e)
            job.state = "failed"
        job.ended = now_iso()
        audit(name, detail, job.state + ": " + (job.lines[-1][9:] if job.lines else ""))
        drop_cache("containers", "serverinfo", "implogs")
    threading.Thread(target=body, daemon=True).start()
    return job


def jobs_view():
    with _jobs_lock:
        return [j.view() for j in reversed(JOBS)]


# ----------------------------------------------------------------------------------------------
# Input checks
# ----------------------------------------------------------------------------------------------

RE_CHAR = re.compile(r"^[^\W\d_]{2,12}$")
RE_ACCT = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")
RE_BANTIME = re.compile(r"^(-1|(\d{1,4}[dhms]){1,4})$")


def char_name(v):
    v = str(v or "").strip()
    if not RE_CHAR.match(v):
        raise Bad("not a character name (2-12 letters)")
    return v[0].upper() + v[1:].lower()


def acct_name(v):
    v = str(v or "").strip()
    if not RE_ACCT.match(v):
        raise Bad("not an account name (letters, digits, _ . -)")
    if v.upper().startswith(BOT_PREFIX):
        raise Bad("that is a random bot account")
    return v.upper()


def text(v, maxlen=255, field="text"):
    s = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(v or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        raise Bad("%s is empty" % field)
    return s[:maxlen]


def intval(v, lo, hi, field):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise Bad("%s must be a number" % field)
    if not lo <= n <= hi:
        raise Bad("%s must be %d..%d" % (field, lo, hi))
    return n


# ----------------------------------------------------------------------------------------------
# Actions (POST /api/action/<name>)
# ----------------------------------------------------------------------------------------------

def soap_action(cmd):
    ok, out = soap(cmd)
    if not ok:
        raise ToolError(out or "the world server refused the command")
    return out or "ok"


def a_kick(a):
    return soap_action("kick %s" % char_name(a.get("name")))


def a_mute(a):
    n = char_name(a.get("name"))
    m = intval(a.get("minutes"), 1, 10080, "minutes")
    return soap_action("mute %s %d %s" % (n, m, text(a.get("reason") or "muted by GM", 120, "reason")))


def a_unmute(a):
    return soap_action("unmute %s" % char_name(a.get("name")))


def a_tele_dalaran(a):
    return soap_action("tele name %s Dalaran" % char_name(a.get("name")))


def a_announce(a):
    return soap_action("announce %s" % text(a.get("text")))


def a_notify(a):
    return soap_action("notify %s" % text(a.get("text")))


def a_mail(a):
    n = char_name(a.get("name"))
    subj = text(a.get("subject"), 60, "subject").replace('"', "'")
    body = text(a.get("body") or subj, 400, "body").replace('"', "'")
    item = intval(a.get("item"), 1, 9999999, "item id")
    count = intval(a.get("count") or 1, 1, 200, "count")
    return soap_action('send items %s "%s" "%s" %d:%d' % (n, subj, body, item, count))


def a_ban(a):
    acct = acct_name(a.get("account"))
    dur = str(a.get("duration") or "").strip().lower()
    if not RE_BANTIME.match(dur):
        raise Bad("duration: -1 (permanent) or like 1h, 1d, 7d, 30d")
    reason = str(a.get("reason") or "").strip()
    if len(reason) < 3:
        raise Bad("a ban needs a reason (3+ characters)")
    return soap_action("ban account %s %s %s" % (acct, dur, text(reason, 200, "reason")))


def a_unban(a):
    return soap_action("unban account %s" % acct_name(a.get("account")))


LUA_ERR = re.compile(r"(?i)lua.*(error|failed)|\[(eluna|ale)\].*error|ale.*error")


def a_reload_ale(a):
    out = soap_action("reload ale")
    time.sleep(2 * TIME_SCALE)
    rc, logs = docker("logs", "--since", "40s", WORLD, timeout=20)
    errs = [ln for ln in clean_lines(logs) if LUA_ERR.search(ln)][-5:] if rc == 0 else []
    return out + ("\nLua errors since the reload:\n" + "\n".join(errs) if errs else "\nno Lua errors in the log since")


def fmt_left(s):
    if s >= 60:
        m = s // 60
        return "%d minute%s" % (m, "" if m == 1 else "s")
    return "%d seconds" % s


def wait_world_ready(job, before, limit_s=1800):
    """Wait for a new world server start that logged 'ready...' (as deploy.sh's wait_ready)."""
    waited = 0
    while waited < limit_s:
        st = started_at(WORLD)
        if st and st != before:
            rc, out = docker("logs", "--since", st, WORLD, timeout=60)
            if rc == 0 and "ready..." in out:
                return True
        if waited and waited % 60 == 0:
            job.log("  still starting (%d min)..." % (waited // 60))
        if job.sleep(10):
            job.log("  (stopped waiting; the world server keeps starting by itself)")
            return False
        waited += 10
    return False


def a_restart_world(a):
    minutes = intval(a.get("minutes"), 1, 15, "minutes")
    if minutes not in (1, 5, 15):
        raise Bad("countdown: 1, 5 or 15 minutes")
    reason = text(a.get("reason"), 80, "reason") if a.get("reason") else ""

    def job_fn(job):
        total = minutes * 60
        tail = (": " + reason) if reason else ""
        ok, out = soap("announce Server restart in %s%s. Please log out somewhere safe." % (fmt_left(total), tail))
        if not ok:
            job.log("ERROR: the world server did not take the announcement (%s); nothing restarted" % out[:120])
            return False
        job.log("announced: restart in " + fmt_left(total))
        left = total
        for mark in [m for m in (600, 300, 120, 60, 30, 10) if m < total] + [0]:
            if job.sleep(left - mark):
                soap("announce The server restart is cancelled.")
                job.log("players told the restart is off")
                job.state = "cancelled"
                return None
            left = mark
            if mark:
                soap("announce Server restart in %s." % fmt_left(mark))
                job.log("announced: " + fmt_left(mark))
        job.cancellable = False
        ok, out = soap("saveall")
        job.log("saveall: " + (out[:120] if ok else "failed (%s); the stop saves players too" % out[:120]))
        before = started_at(WORLD)
        job.log("docker compose up -d --no-deps --force-recreate ac-worldserver")
        rc, out = docker("compose", "up", "-d", "--no-deps", "--force-recreate", "ac-worldserver", timeout=400, cwd=WU)
        job.log(out[-600:] or "(no output)")
        if rc != 0:
            job.log("ERROR: docker compose failed (rc %d)" % rc)
            return False
        job.log("waiting for the world server to report ready (2-10 minutes)...")
        if not wait_world_ready(job, before):
            job.log("ERROR: not ready yet: see Logs, worldserver")
            return False
        info = server_info(fresh=True)
        job.log("world server ready (%s)" % ("SOAP answers" if info.get("online") else "SOAP not answering yet"))
        return True
    return start_job("restart_world", {"minutes": minutes, "reason": reason}, job_fn, cancellable=True)


def a_cancel_job(a):
    jid = str(a.get("id") or "")
    with _jobs_lock:
        for j in JOBS:
            if j.id == jid and j.state == "running":
                if not j.cancellable:
                    raise Bad("this step can't be cancelled any more")
                j.cancel.set()
                return "cancelling"
    raise Bad("no such running job")


def a_rollback_client(a):
    www, old, swap = ST + "/www", ST + "/www.old", ST + "/www.swap"
    if not os.path.isdir(old):
        raise Bad("no previous client on the server (www.old missing; a slice upload removes it)")
    if not os.path.isdir(www):
        raise Bad("www is missing")
    if os.path.exists(swap):
        raise Bad("www.swap is left from an interrupted swap: fix it by hand first")
    before = (client_build(www) or {}).get("id")
    os.rename(www, swap)
    os.rename(old, www)
    os.rename(swap, old)
    rc, out = docker("restart", "wu-play", timeout=60)
    after = (client_build(www) or {}).get("id")
    msg = "client %s is live, %s kept as www.old" % (after, before)
    if rc != 0:
        msg += "; wu-play restart failed: " + out[:160]
    return msg


def lib_bash(snippet, args=(), env=None, timeout=300):
    lib = ST + "/stream-lib.sh"
    if not os.path.isfile(lib):
        raise ToolError("%s missing (the streaming kit)" % lib)
    e = {"WU_DIR": WU, "WU_STREAM_DIR": ST, "WU_CADDYFILE": CADDYFILE, "WU_CADDY_DIR": REALM_DIR}
    e.update(env or {})
    return run(["bash", "-c", 'set -uo pipefail; . "$0"; ' + snippet, lib, *args], env=e, timeout=timeout)


def a_restart_portal(a):
    def job_fn(job):
        if os.path.isfile(ST + "/stream-lib.sh"):
            job.log("recreating wu-portal (stream-lib.sh recreate_portal: reads portal.env again)")
            rc, out = lib_bash("recreate_portal")
        else:
            job.log("docker restart wu-portal")
            rc, out = docker("restart", "wu-portal")
        job.log(out[-800:] if out else "")
        job.log("wu-portal is up" if rc == 0 else "ERROR: wu-portal did not come back (Logs, wu-portal)")
        return rc == 0
    return start_job("restart_portal", {}, job_fn)


def caddy_exec(*args):
    return docker("compose", "exec", "-T", "caddy", "caddy", *args, "--config", "/etc/caddy/Caddyfile",
                  "--adapter", "caddyfile", timeout=60, cwd=REALM_DIR)


def a_reload_caddy(a):
    rc, out = caddy_exec("validate")
    if rc != 0:
        raise ToolError("the Caddyfile does not validate; Caddy keeps the running config:\n" + out[-800:])
    rc, out2 = caddy_exec("reload")
    if rc != 0:
        raise ToolError("caddy reload failed (the running config stays):\n" + out2[-800:])
    return "valid; reloaded"


def a_stream(a):
    on = bool(a.get("on"))
    script = ST + "/stream-switch.sh"
    if not os.path.isfile(script):
        raise Bad("stream-switch.sh is not on the server (Make mini slice.bat uploads the kit)")

    def job_fn(job):
        job.log("bash stream-switch.sh " + ("on" if on else "off"))
        rc, out = run(["bash", script, "on" if on else "off"], env={"WU_DIR": WU, "WU_STREAM_DIR": ST}, timeout=300)
        job.log(out[-1500:])
        return rc == 0
    return start_job("stream_" + ("on" if on else "off"), {}, job_fn)


def a_foreverui(a):
    on = bool(a.get("on"))
    if on and not os.path.isdir(ST + "/overlays/foreverui"):
        raise Bad("Forever UI is not on the server yet: run stream\\Add Forever UI to the stream.bat first")

    def job_fn(job):
        job.log("WU_FOREVERUI=%d in portal.env, then recreate wu-portal" % on)
        rc, out = lib_bash('kv_set "$WU/portal.env" WU_FOREVERUI "$1" && recreate_portal', args=("1" if on else "0",))
        job.log(out[-800:] if out else "")
        job.log("Forever UI is %s for new page loads" % ("on" if on else "off") if rc == 0 else "ERROR: see above")
        return rc == 0
    return start_job("foreverui_" + ("on" if on else "off"), {}, job_fn)


SPEED_PLAN = [
    ("p0-1", "P0", "Bake new static cells right away (static_gx / merge, ms not frames)", "client"),
    ("p0-2", "P0", "Parallel loader awaits: WMO groups, ADT layer textures, M2 skin/.anim", "client"),
    ("p0-3", "P0", "Async reader checks the /data/__index name index (no 404 probes)", "client"),
    ("p0-4", "P0", "Server TCP/QUIC: BBR + fq, no slow start after idle, HTTP/3 on UDP 443", "server"),
    ("p0-5", "P0", "No sync XHR in the world (skin composites, skybox, stars) + tripwire", "client"),
    ("p1-6", "P1", "Distance-priority fetch scheduler (24-48 in flight, nearest first)", "client"),
    ("p1-7", "P1", "Prefetch the entry ring at character select (per-tile lists, Cache Storage)", "client+host"),
    ("p1-8", "P1", "Mip-first textures and a near-ring loading gate (needs Range on /data)", "client+host"),
    ("p1-9", "P1", "WDL placeholder under not-yet-loaded terrain", "client"),
    ("p1-10", "P1", "Prefetch along the movement vector (and taxi paths)", "client"),
    ("p2-11", "P2", "Per-tile packs + persistent cache (OPFS) + optional R2 edge", "client+host"),
    ("p2-12", "P2", "Spawn-time fade-in", "client"),
    ("p2-13", "P2", "Decode in Web Workers (parser-only wasm)", "client"),
    ("p2-14", "P2", "GPU upload budget while paced; smaller alpha arrays", "client"),
    ("m-1", "Measure", "?loadtrace=1 per-request + lifecycle trace, CSV export", "client"),
    ("m-2", "Measure", "Harness: netem 190 ms x {20,50,100} Mbps, cold/warm, 5 runs", "test box"),
]
SPEED_STATES = ("todo", "doing", "done", "skip")
_speed_lock = threading.Lock()


def speed_marks():
    try:
        with open(SPEED_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def a_speed_mark(a):
    sid = str(a.get("id") or "")
    st = str(a.get("status") or "")
    if sid not in {x[0] for x in SPEED_PLAN}:
        raise Bad("unknown plan item")
    if st not in SPEED_STATES:
        raise Bad("status: " + ", ".join(SPEED_STATES))
    note = text(a.get("note"), 200, "note") if a.get("note") else ""
    with _speed_lock:
        d = speed_marks()
        d[sid] = {"status": st, "note": note, "at": now_iso()}
        tmp = SPEED_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, SPEED_FILE)
    return "%s: %s" % (sid, st)


# name: (function, destructive?, audited detail keys)
ACTIONS = {
    "kick": (a_kick, True, ("name",)),
    "mute": (a_mute, True, ("name", "minutes", "reason")),
    "unmute": (a_unmute, False, ("name",)),
    "tele_dalaran": (a_tele_dalaran, True, ("name",)),
    "announce": (a_announce, False, ("text",)),
    "notify": (a_notify, False, ("text",)),
    "mail": (a_mail, False, ("name", "subject", "item", "count")),
    "ban": (a_ban, True, ("account", "duration", "reason")),
    "unban": (a_unban, True, ("account",)),
    "reload_ale": (a_reload_ale, False, ()),
    "restart_world": (a_restart_world, True, ("minutes", "reason")),
    "cancel_job": (a_cancel_job, False, ("id",)),
    "rollback_client": (a_rollback_client, True, ()),
    "restart_portal": (a_restart_portal, True, ()),
    "reload_caddy": (a_reload_caddy, True, ()),
    "stream": (a_stream, True, ("on",)),
    "foreverui": (a_foreverui, True, ("on",)),
    "speed_mark": (a_speed_mark, False, ("id", "status")),
}
_action_lock = threading.Lock()


def do_action(name, args):
    if name not in ACTIONS:
        raise Bad("unknown action")
    fn, destructive, keys = ACTIONS[name]
    if destructive and args.get("confirm") is not True:
        raise Bad("this action needs confirm: true (the page asks first)")
    detail = {k: args.get(k) for k in keys if k in args}
    with _action_lock:
        try:
            res = fn(args)
        except Bad as e:
            audit(name, detail, "refused: %s" % e)
            raise
        except (ToolError, Busy) as e:
            audit(name, detail, "failed: %s" % e)
            raise
    if isinstance(res, Job):
        audit(name, detail, "started job " + res.id)
        return {"ok": True, "job": res.view()}
    audit(name, detail, "ok: " + str(res)[:200])
    drop_cache("serverinfo", "players", "containers")
    return {"ok": True, "message": res}


# ----------------------------------------------------------------------------------------------
# Pages (GET /api/...)
# ----------------------------------------------------------------------------------------------

def api_overview(q):
    rows, others = container_table()
    return {"realm": server_info(), "containers": rows, "other_containers": others, "host": host_stats(),
            "stream": stream_state(), "client": client_build(ST + "/www"), "client_old": client_build(ST + "/www.old"),
            "logs": important_logs(), "jobs": jobs_view()[:3], "profile": read_kv(WU + "/.env").get("OV_PROFILE", "?")}


def zone_name(z):
    try:
        z = int(z)
    except (TypeError, ValueError):
        return "?"
    return ZONES.get(z, "zone %d" % z)


def api_players(q):
    def get():
        bp = BOT_PREFIX.replace("'", "")
        rows = sql("acore_characters",
                   "SELECT c.name, c.level, c.class, c.race, c.zone, c.map, a.username, c.totaltime, a.id "
                   "FROM characters c JOIN acore_auth.account a ON a.id = c.account "
                   "WHERE c.online = 1 AND a.username NOT LIKE '%s%%' ORDER BY c.name LIMIT 500;\n"
                   "SELECT COUNT(*) FROM characters c JOIN acore_auth.account a ON a.id = c.account "
                   "WHERE c.online = 1 AND a.username LIKE '%s%%';\n" % (bp, bp))
        players, bots = [], 0
        for r in rows:
            if len(r) == 1:
                bots = int(r[0] or 0)
                continue
            if len(r) < 9:
                continue
            players.append({"name": r[0], "level": int(r[1] or 0), "class": CLASSES.get(int(r[2] or 0), r[2]),
                            "race": RACES.get(int(r[3] or 0), r[3]), "zone": zone_name(r[4]), "map": r[5],
                            "account": r[6], "played_h": round(int(r[7] or 0) / 3600, 1)})
        return {"players": players, "bots_online": bots}
    try:
        d = cached("players", 5, get, q.get("fresh") == "1")
        d["error"] = None
    except ToolError as e:
        d = {"players": [], "bots_online": None, "error": str(e)}
    d["realm"] = server_info()
    d["bot_prefix"] = BOT_PREFIX
    return d


def api_accounts(q):
    s = (q.get("q") or "").strip()
    if not re.match(r"^[A-Za-z0-9_]{1,32}$", s):
        raise Bad("search: 1-32 letters, digits or _")
    like = s.upper().replace("_", "\\_") + "%"
    bp = BOT_PREFIX.replace("'", "")
    rows = sql("acore_auth",
               "SELECT a.id, a.username, a.last_login, a.online, "
               "(SELECT COUNT(*) FROM account_banned b WHERE b.id = a.id AND b.active = 1), "
               "(SELECT b.banreason FROM account_banned b WHERE b.id = a.id AND b.active = 1 ORDER BY b.bandate DESC LIMIT 1), "
               "(SELECT COUNT(*) FROM acore_characters.characters c WHERE c.account = a.id), "
               "(SELECT GROUP_CONCAT(c.name ORDER BY c.level DESC SEPARATOR ', ') FROM acore_characters.characters c WHERE c.account = a.id), "
               "a.mutetime "
               "FROM account a WHERE a.username NOT LIKE '%s%%' AND (a.username LIKE '%s' OR a.id IN "
               "(SELECT c.account FROM acore_characters.characters c WHERE c.name LIKE '%s')) ORDER BY a.username LIMIT 50;\n"
               % (bp, like, like))
    out = []
    now = time.time()
    for r in rows:
        if len(r) < 9:
            continue
        mt = int(r[8] or 0)
        out.append({"id": int(r[0]), "username": r[1], "last_login": r[2], "online": r[3] == "1",
                    "banned": int(r[4] or 0) > 0, "ban_reason": r[5] or "", "characters": int(r[6] or 0),
                    "names": (r[7] or "")[:120], "muted": mt > now})
    return {"accounts": out}


def lua_files():
    d = WU + "/custom/lua_scripts"
    out = []
    try:
        for n in sorted(os.listdir(d)):
            if n.endswith(".lua"):
                p = os.path.join(d, n)
                out.append({"name": n, "mtime": mtime(p), "bytes": os.path.getsize(p)})
    except OSError:
        pass
    return out


def last_audit(action):
    for e in audit_tail(400):
        if e["action"] == action and e["result"].startswith("ok"):
            return iso_to_epoch(e["at"])
    return None


def api_updates(q):
    world_start = iso_to_epoch(started_at(WORLD))
    portal_start = iso_to_epoch(started_at("wu-portal"))
    play_start = iso_to_epoch(started_at("wu-play"))
    profile = read_kv(WU + "/.env").get("OV_PROFILE", "main")
    pf = WU + "/profiles/%s.env" % profile
    lua = lua_files()
    last_reload = max([t for t in (last_audit("reload_ale"), world_start) if t] or [0]) or None
    for f in lua:
        f["pending"] = bool(last_reload and f["mtime"] and f["mtime"] > last_reload)
    items = []

    def item(key, label, live, pending, note, fix=None):
        items.append({"key": key, "label": label, "live": live, "pending": pending, "note": note, "fix": fix})

    www, old = client_build(ST + "/www"), client_build(ST + "/www.old")
    w_m = (www or {}).get("index_mtime")
    item("client", "Browser client (stream/www)", (www or {}).get("id") or "none",
         bool(www and play_start and w_m and w_m > play_start),
         "previous: %s" % ((old or {}).get("id") or "none kept (www.old missing)"),
         "rollback_client" if old else None)
    pp = WU + "/portal/wrath_portal.py"
    kp = ST + "/wrath_portal.py"
    item("portal", "Sign-in page (portal/wrath_portal.py)", "running since container start",
         bool(portal_start and mtime(pp) and mtime(pp) > portal_start),
         "the stream kit's copy %s" % ("matches" if file_hash(pp) == file_hash(kp) else
                                      ("differs (stream-up.sh installs it)" if os.path.isfile(kp) else "is not on the server")),
         "restart_portal")
    item("lua", "Realm scripts (custom/lua_scripts)", "%d files" % len(lua), any(f["pending"] for f in lua),
         "%d changed since the last reload or world start" % sum(f["pending"] for f in lua), "reload_ale")
    item("profile", "World profile (%s)" % os.path.relpath(pf, WU), profile,
         bool(world_start and mtime(pf) and mtime(pf) > world_start),
         "newer than the running world server = restart to apply", "restart_world")
    want = read_kv(pf).get("AC_SOCKET_TIME_OUT_TIME_ACTIVE")
    rc, have = docker("exec", WORLD, "printenv", "AC_SOCKET_TIME_OUT_TIME_ACTIVE", timeout=15)
    have = have.strip() if rc == 0 else None
    item("timeout", "Slow-load kicks (SocketTimeOutTimeActive)", have or "default 60000",
         bool(want and want != have), "profile wants %s; Stop slow-load kicks.bat sets 600000" % (want or "nothing"),
         "restart_world")
    try:
        pci = int(sql("acore_world", "SELECT COUNT(*) FROM playercreateinfo;")[0][0])
    except (ToolError, IndexError, ValueError):
        pci = None
    log_last = tail_file(WU + "/charfix/charfix.log", 1)
    item("charfix", "Character-create fix (charfix_world.sql)", "%s race/class pairs" % (pci if pci is not None else "?"),
         pci is not None and pci < 83, (log_last[0][:120] if log_last else "never run here"), None)
    sqls = []
    try:
        for n in sorted(os.listdir(WU + "/sql")):
            if n.endswith(".sql"):
                sqls.append({"name": n, "mtime": mtime(WU + "/sql/" + n)})
    except OSError:
        pass
    item("caddy", "Caddyfile", "mtime %s" % fmt_time(mtime(CADDYFILE)), False,
         "Reload validates first; a bad file is never loaded", "reload_caddy")
    cc = read_sys("net/ipv4/tcp_congestion_control")
    item("net", "Download tuning (BBR)", cc or "?", cc not in (None, "bbr"), "Speed up downloads.bat sets bbr + fq", None)
    return {"items": items, "lua": lua, "sql": sqls, "world_started": world_start, "audit": audit_tail(60),
            "jobs": jobs_view(), "bats": BATS, "train": TRAIN}


def file_hash(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def tail_file(p, n):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\n") for ln in f.readlines()[-n:]]
    except OSError:
        return []


def fmt_time(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t)) + "Z" if t else "?"


def read_sys(key):
    try:
        with open("/proc/sys/" + key) as f:
            return f.read().strip()
    except OSError:
        return None


def fetch(url, headers=None, timeout=10, max_bytes=4_000_000, method="GET"):
    """One HTTP(S) request, no redirects: status, headers, body (capped), ttfb and total in ms."""
    u = urllib.parse.urlsplit(url)
    out = {"url": url, "status": None, "headers": {}, "body": b"", "bytes": 0, "ttfb_ms": None, "total_ms": None, "error": None}
    try:
        if u.scheme == "https":
            conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        h = {"User-Agent": "wu-gmconsole/1", "Accept": "*/*"}
        h.update(headers or {})
        t0 = time.perf_counter()
        conn.request(method, path, headers=h)
        r = conn.getresponse()
        out["ttfb_ms"] = round((time.perf_counter() - t0) * 1000)
        out["status"] = r.status
        out["headers"] = {k.lower(): v for k, v in r.getheaders()}
        n, keep = 0, []
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n <= max_bytes:
                keep.append(chunk)
        out["total_ms"] = round((time.perf_counter() - t0) * 1000)
        out["bytes"] = n
        out["body"] = b"".join(keep)
        conn.close()
    except (OSError, http.client.HTTPException, ssl.SSLError, ValueError) as e:
        out["error"] = str(e)[:200] or type(e).__name__
    return out


def jfetch(url, **kw):
    r = fetch(url, **kw)
    r["json"] = None
    if r["status"] == 200:
        try:
            r["json"] = json.loads(r["body"].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
    return r


def parallel(fns):
    res = [None] * len(fns)

    def go(i, f):
        try:
            res[i] = f()
        except Exception as e:  # noqa: BLE001
            res[i] = e
    th = [threading.Thread(target=go, args=(i, f), daemon=True) for i, f in enumerate(fns)]
    for t in th:
        t.start()
    for t in th:
        t.join(40)
    return res


def preview(j, limit=6000):
    s = json.dumps(j, indent=2, ensure_ascii=False) if j is not None else ""
    return s if len(s) <= limit else s[:limit] + "\n... (cut)"


def api_beacons(q):
    def get():
        org = {"Origin": SITE_ORIGIN}
        st, feed, idx, rec, page, relay = parallel([
            lambda: jfetch(STATUS_URL, headers=org), lambda: jfetch(FEED_URL, headers=org),
            lambda: jfetch(SITE_URL + "/realms/index.json"), lambda: jfetch(SITE_URL + "/realms/%s.json" % SLUG),
            lambda: fetch(SITE_URL + "/realms.html", max_bytes=200000), lambda: fetch(RELAY_URL, timeout=8)])
        checks = []

        def chk(cid, label, ok, detail):
            checks.append({"id": cid, "label": label, "ok": ok, "detail": detail})

        def why(r):
            return r["error"] or "HTTP %s" % r["status"]
        sj = st["json"]
        chk("status", "status.json reachable", bool(sj), "%s, %s ms" % (why(st), st["ttfb_ms"]) if not sj else
            "HTTP 200 in %s ms: online=%s players=%s bots=%s" % (st["ttfb_ms"], sj.get("online"), sj.get("players"), sj.get("bots")))
        acao = st["headers"].get("access-control-allow-origin")
        chk("cors", "status.json CORS for %s" % SITE_ORIGIN, acao in ("*", SITE_ORIGIN),
            "Access-Control-Allow-Origin: %s" % (acao or "missing"))
        chk("online", "Realm reports online", bool(sj and sj.get("online")), "from status.json" if sj else "no status")
        fj = feed["json"]
        n = len(fj) if isinstance(fj, list) else len(fj.get("items") or fj.get("realms") or fj.get("entries") or []) if isinstance(fj, dict) else 0
        chk("feed", "community feed.json reachable", fj is not None, why(feed) if fj is None else "HTTP 200, %d entries" % n)
        ij = idx["json"]
        listed = isinstance(ij, dict) and SLUG in (ij.get("realms") or [])
        chk("index", "Site lists the realm (realms/index.json)", listed, why(idx) if ij is None else
            ("%s listed" % SLUG if listed else "%s not in %s" % (SLUG, ij.get("realms"))))
        rj = rec["json"]
        todo = [k for k in ("tagline", "summary", "rules") if "TODO" in json.dumps((rj or {}).get(k, ""))]
        chk("record", "Realm record realms/%s.json" % SLUG, bool(rj) and rj.get("slug") == SLUG,
            why(rec) if rj is None else "state=%s, status url %s" % (rj.get("state"),
                                                                 "matches" if (rj.get("status") or {}).get("url") == STATUS_URL else "DIFFERS"))
        chk("record_text", "Record has the owner's text (no TODO)", bool(rj) and not todo,
            "TODO left in: " + ", ".join(todo) if todo else ("ok" if rj else "no record"))
        chk("page", "realms.html page", page["status"] == 200, why(page))
        try:
            addrs = sorted({a[4][0] for a in socket.getaddrinfo(RELAY_HOST, 443, proto=socket.IPPROTO_TCP)})
            chk("relay_dns", "DNS %s" % RELAY_HOST, True, ", ".join(addrs))
        except OSError as e:
            chk("relay_dns", "DNS %s" % RELAY_HOST, False, "does not resolve (%s): add the A record when the relay VM is up" % e)
        chk("relay", "Relay health (hosting kit)", relay["status"] == 200,
            "healthz %s" % why(relay) if relay["status"] != 200 else "healthz ok in %s ms" % relay["ttfb_ms"])
        kit = os.path.isdir(WU + "/hosting") or os.path.isdir("/opt/wu-relay")
        chk("kit", "Hosting kit / relay files on this server", None if not kit else True,
            "present" if kit else "not here (the relay runs on its own VM: hosting/relay/deploy)")
        return {"checks": checks, "status_preview": preview(sj), "feed_preview": preview(fj),
                "record_preview": preview(rj), "at": now_iso(),
                "urls": {"status": STATUS_URL, "feed": FEED_URL, "site": SITE_URL + "/realms.html#" + SLUG, "relay": RELAY_URL}}
    return cached("beacons", 120, get, q.get("fresh") == "1")


def caddy_encodes():
    try:
        with open(CADDYFILE, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out, site = [], None
    for ln in lines:
        if ln and not ln[0].isspace() and ln.rstrip().endswith("{") and not ln.startswith(("(", "{", "#")):
            site = ln.rstrip(" {")
        m = re.match(r"\s*encode\s*(.*)$", ln)
        if m and site:
            out.append({"site": site, "encode": m.group(1).strip() or "(default)"})
    return out


def precompressed():
    out = []
    d = ST + "/www"
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not n.endswith((".wasm", ".js")):
            continue
        p = os.path.join(d, n)
        sz = os.path.getsize(p)
        row = {"name": n, "bytes": sz}
        for ext in ("gz", "br"):
            q = p + "." + ext
            if os.path.isfile(q):
                row[ext] = {"bytes": os.path.getsize(q), "ratio": round(sz / max(1, os.path.getsize(q)), 2),
                            "stale": mtime(q) < mtime(p)}
            else:
                row[ext] = None
        out.append(row)
    return out


def api_speed(q):
    def get():
        po = play_origin()
        www = client_build(ST + "/www") or {}
        wasm = (www.get("wasm") or {}).get("name", "wenilla_bg.wasm")
        enc = {"Accept-Encoding": "br, gzip"}
        jobs = [lambda: fetch(PUBLIC_URL + "/wrath", max_bytes=300000), lambda: fetch(STREAM_URL + "/", max_bytes=100000),
                lambda: fetch(STATUS_URL)]
        if po:
            jobs += [lambda: fetch(po + "/" + wasm, headers=enc, timeout=60, max_bytes=1),
                     lambda: fetch(po + "/data/__index", headers=enc, timeout=30, max_bytes=1),
                     lambda: fetch(po + "/data/__tier/1.txt", timeout=20)]
        res = parallel(jobs)
        rows = []

        def row(label, r, where, note=""):
            if isinstance(r, Exception) or r is None:
                rows.append({"label": label, "where": where, "error": str(r)})
                return
            mbps = round(r["bytes"] * 8 / 1e6 / (r["total_ms"] / 1000), 1) if r["total_ms"] and r["bytes"] > 100000 else None
            rows.append({"label": label, "where": where, "status": r["status"], "ttfb_ms": r["ttfb_ms"],
                         "total_ms": r["total_ms"], "bytes": r["bytes"], "encoding": r["headers"].get("content-encoding"),
                         "mbps": mbps, "error": r["error"], "note": note})
        row("Sign-in page /wrath", res[0], "public")
        row("Stream site / (gate)", res[1], "public", "302/401 = the sign-in gate answers")
        row("status.json", res[2], "public")
        if po:
            row("/" + wasm, res[3], "origin", "wu-play direct")
            row("/data/__index", res[4], "origin")
            names = []
            t1 = res[5]
            if isinstance(t1, dict) and t1.get("status") == 200:
                for ln in t1["body"].decode("utf-8", "replace").splitlines():
                    ln = ln.strip().split("\t")[0]
                    if ln and not ln.startswith("#"):
                        names.append(ln)
                    if len(names) >= 3:
                        break
            files = parallel([lambda n=n: fetch(po + "/data/" + urllib.parse.quote(n, safe=""), headers=enc, timeout=30, max_bytes=1)
                              for n in names])
            for n, r in zip(names, files):
                row("/data/" + n[-48:], r, "origin", "tier 1 file")
        alt = {}
        for lbl, r in (("public", res[0]), ("stream", res[1])):
            alt[lbl] = (r["headers"].get("alt-svc") if isinstance(r, dict) else None)
        sysctl = {"tcp_congestion_control": read_sys("net/ipv4/tcp_congestion_control"),
                  "default_qdisc": read_sys("net/core/default_qdisc"),
                  "tcp_slow_start_after_idle": read_sys("net/ipv4/tcp_slow_start_after_idle")}
        checks = [
            {"label": "BBR congestion control", "ok": sysctl["tcp_congestion_control"] == "bbr", "detail": sysctl["tcp_congestion_control"] or "?"},
            {"label": "fq queueing", "ok": sysctl["default_qdisc"] == "fq", "detail": sysctl["default_qdisc"] or "?"},
            {"label": "No slow start after idle", "ok": sysctl["tcp_slow_start_after_idle"] == "0", "detail": sysctl["tcp_slow_start_after_idle"] or "?"},
            {"label": "HTTP/3 advertised (alt-svc h3) on %s" % PUBLIC_HOST, "ok": "h3" in (alt["public"] or ""), "detail": alt["public"] or "no alt-svc header"},
            {"label": "HTTP/3 advertised on the stream site", "ok": "h3" in (alt["stream"] or ""), "detail": alt["stream"] or "no alt-svc header"},
        ]
        pre = precompressed()
        wrow = next((p for p in pre if p["name"].endswith(".wasm")), None)
        checks.append({"label": "wasm precompressed (.br/.gz, up to date)",
                       "ok": bool(wrow and (wrow["br"] or wrow["gz"]) and not any(wrow[e] and wrow[e]["stale"] for e in ("br", "gz"))),
                       "detail": ("br x%s" % wrow["br"]["ratio"] if wrow and wrow["br"] else "no .br") + ", " +
                                 ("gz x%s" % wrow["gz"]["ratio"] if wrow and wrow["gz"] else "no .gz") if wrow else "no wasm in www"})
        return {"rows": rows, "checks": checks, "encodes": caddy_encodes(), "precompressed": pre, "origin": po or None, "at": now_iso()}
    d = cached("speed", 300, get, q.get("fresh") == "1")
    marks = speed_marks()
    d = dict(d)
    d["plan"] = [{"id": i, "level": lv, "title": t, "where": w, "status": (marks.get(i) or {}).get("status", "todo"),
                  "note": (marks.get(i) or {}).get("note", ""), "at": (marks.get(i) or {}).get("at")} for i, lv, t, w in SPEED_PLAN]
    d["states"] = SPEED_STATES
    return d


def api_streaming(q):
    s = stream_state()
    desc = slice_desc(s["slice"]) or {}
    order = desc.get("order") or [t.get("key") for t in desc.get("tiers") or []]
    names = {t.get("key"): t.get("name") for t in desc.get("tiers") or []}
    index, err = None, None
    po = play_origin()
    if po:
        r = jfetch(po + "/data/__tier/index.json", timeout=8)
        if isinstance(r["json"], list):
            index = r["json"]
        else:
            err = r["error"] or "HTTP %s" % r["status"]
    else:
        err = "wu-play is not running"
    tiers = []
    if index:
        for t in index:
            tiers.append({"tier": t.get("tier"), "name": t.get("name"), "files": t.get("files"), "bytes": t.get("bytes")})
    else:
        for i, k in enumerate(order):
            tiers.append({"tier": i, "name": names.get(k) or k, "files": None, "bytes": None,
                          "held": desc.get("maxTier") is None or i <= desc.get("maxTier")})
    rc, logs = docker("logs", "--tail", "150", "wu-play", timeout=20)
    return {"state": s, "tiers": tiers, "tier_source": "wu-play /data/__tier/index.json" if index else "slices/%s.json" % s["slice"],
            "tier_error": err, "logs": clean_lines(logs)[-150:] if rc == 0 else [logs[:200]], "jobs": jobs_view()[:3]}


LOG_SOURCES = {"worldserver": WORLD, "authserver": "ov-ac-authserver", "wu-portal": "wu-portal", "wu-play": "wu-play",
               "caddy": None, "database": DB, "gmconsole": "wu-gmconsole"}


def api_logs(q):
    src = q.get("c") or "worldserver"
    if src not in LOG_SOURCES:
        raise Bad("unknown log")
    name = LOG_SOURCES[src] or find_container("caddy")
    if not name:
        return {"source": src, "lines": ["(no caddy container found)"]}
    n = intval(q.get("n") or 300, 20, 3000, "lines")
    rc, out = docker("logs", "--tail", str(n), name, timeout=30)
    lines = clean_lines(out)
    f = (q.get("q") or "").strip().lower()
    if f:
        lines = [ln for ln in lines if f in ln.lower()]
    return {"source": src, "container": name, "lines": [ln[:600] for ln in lines[-n:]], "rc": rc}


def api_jobs(q):
    return {"jobs": jobs_view()}


# ----------------------------------------------------------------------------------------------
# Bug reports (ov_reports.lua's acore_characters.ov_bug_reports) and native GM tickets (gm_ticket)
# ----------------------------------------------------------------------------------------------
# Read through the same docker-exec mysql as everything else. User text never enters SQL as a quoted
# literal: the search goes in as a hex literal (X'...'), statuses come from a fixed list, ids are ints.
# Text columns come back HEX()-encoded so tabs, newlines and backslashes in reports survive mysql -B.
# The only write is ov_bug_reports.status.

REPORT_STATES = ("new", "seen", "fixed", "wontfix")
MAPS = {0: "Eastern Kingdoms", 1: "Kalimdor", 30: "Alterac Valley", 33: "Shadowfang Keep", 34: "The Stockade",
        36: "The Deadmines", 43: "Wailing Caverns", 47: "Razorfen Kraul", 48: "Blackfathom Deeps", 70: "Uldaman",
        90: "Gnomeregan", 109: "Sunken Temple", 129: "Razorfen Downs", 189: "Scarlet Monastery", 209: "Zul'Farrak",
        229: "Blackrock Spire", 230: "Blackrock Depths", 249: "Onyxia's Lair", 289: "Scholomance", 309: "Zul'Gurub",
        329: "Stratholme", 349: "Maraudon", 389: "Ragefire Chasm", 409: "Molten Core", 429: "Dire Maul",
        469: "Blackwing Lair", 489: "Warsong Gulch", 509: "Ruins of Ahn'Qiraj", 529: "Arathi Basin", 530: "Outland",
        531: "Temple of Ahn'Qiraj", 533: "Naxxramas", 571: "Northrend", 574: "Utgarde Keep", 575: "Utgarde Pinnacle",
        576: "The Nexus", 578: "The Oculus", 595: "Culling of Stratholme", 599: "Halls of Stone",
        600: "Drak'Tharon Keep", 601: "Azjol-Nerub", 602: "Halls of Lightning", 603: "Ulduar", 604: "Gundrak",
        608: "The Violet Hold", 609: "Ebon Hold", 615: "The Obsidian Sanctum", 616: "The Eye of Eternity",
        619: "Ahn'kahet", 624: "Vault of Archavon", 631: "Icecrown Citadel", 632: "The Forge of Souls",
        649: "Trial of the Crusader", 650: "Trial of the Champion", 658: "Pit of Saron", 668: "Halls of Reflection",
        724: "The Ruby Sanctum"}
# GM tickets mapped onto the same four states for the filter (they stay read-only here)
_TICKET_STATE = {"new": "t.type = 0 AND t.viewed = 0", "seen": "t.type = 0 AND t.viewed <> 0",
                 "fixed": "t.type = 1", "wontfix": "t.type = 2"}


def map_name(m):
    try:
        m = int(m)
    except (TypeError, ValueError):
        return "?"
    return MAPS.get(m, "map %d" % m)


def area_name(a):
    try:
        a = int(a)
    except (TypeError, ValueError):
        return None
    return ZONES.get(a) if a else None


def unhex(s):
    try:
        return bytes.fromhex(s or "").decode("utf-8", "replace")
    except ValueError:
        return ""


def num_or(v, cast=int):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def like_hex(q):
    """A LIKE '%q%' pattern for user text as a hex literal: nothing in it can close a quote."""
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "CONCAT('%%', CONVERT(X'%s' USING utf8mb4), '%%') COLLATE utf8mb4_unicode_ci" % q.encode("utf-8").hex()


def report_search(v):
    s = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(v or ""))
    return re.sub(r"\s+", " ", s).strip()[:100]


def report_status_arg(v):
    v = str(v or "").strip().lower()
    if v in ("", "all"):
        return None
    if v not in REPORT_STATES:
        raise Bad("status: all, " + ", ".join(REPORT_STATES))
    return v


def tele_cmd(x, y, z, m):
    if None in (x, y, z, m):
        return None
    return ".go xyz %.2f %.2f %.2f %d" % (x, y, z, m)


def query_reports(status=None, search="", limit=200, since=0):
    where = []
    if status:
        where.append("status = '%s'" % status)          # from REPORT_STATES only
    if search:
        p = like_hex(search)
        where.append("(text LIKE %s OR char_name LIKE %s)" % (p, p))
    if since:
        where.append("id > %d" % since)
    rows = sql("acore_characters",
               "SELECT id, account_id, char_guid, HEX(char_name), level, class, map_id, zone_id, area_id, "
               "pos_x, pos_y, pos_z, HEX(text), status, UNIX_TIMESTAMP(created_at) FROM ov_bug_reports%s "
               "ORDER BY created_at DESC, id DESC LIMIT %d;\n" % (" WHERE " + " AND ".join(where) if where else "", limit))
    out = []
    for r in rows:
        if len(r) < 15:
            continue
        x, y, z, m = num_or(r[9], float), num_or(r[10], float), num_or(r[11], float), num_or(r[6])
        cls = num_or(r[5])
        out.append({"kind": "report", "id": num_or(r[0]), "account_id": num_or(r[1]), "char_guid": num_or(r[2]),
                    "char_name": unhex(r[3]), "level": num_or(r[4]), "class": CLASSES.get(cls, "class %s" % r[5]),
                    "map_id": m, "map": map_name(m), "zone_id": num_or(r[7]), "zone": zone_name(r[7]),
                    "area_id": num_or(r[8]), "area": area_name(r[8]), "x": x, "y": y, "z": z,
                    "text": unhex(r[12]), "status": r[13] if r[13] in REPORT_STATES else (r[13] or "new"),
                    "created": num_or(r[14]), "tele": tele_cmd(x, y, z, m)})
    return out


def query_tickets(status=None, search="", limit=200):
    where = []
    if status:
        where.append(_TICKET_STATE[status])
    if search:
        p = like_hex(search)
        where.append("(t.description LIKE %s OR t.name LIKE %s)" % (p, p))
    rows = sql("acore_characters",
               "SELECT t.id, t.playerGuid, HEX(t.name), HEX(t.description), t.createTime, t.mapId, t.posX, t.posY, "
               "t.posZ, t.type, t.viewed, c.level, c.class, HEX(IFNULL(t.response, '')) FROM gm_ticket t "
               "LEFT JOIN characters c ON c.guid = t.playerGuid%s ORDER BY t.createTime DESC, t.id DESC LIMIT %d;\n"
               % (" WHERE " + " AND ".join(where) if where else "", limit))
    out = []
    for r in rows:
        if len(r) < 14:
            continue
        x, y, z, m = num_or(r[6], float), num_or(r[7], float), num_or(r[8], float), num_or(r[5])
        typ, viewed, cls = num_or(r[9]), num_or(r[10]) or 0, num_or(r[12])
        st = {0: "seen" if viewed else "new", 1: "fixed", 2: "wontfix"}.get(typ, "new")
        out.append({"kind": "ticket", "id": num_or(r[0]), "char_guid": num_or(r[1]), "char_name": unhex(r[2]),
                    "level": num_or(r[11]), "class": CLASSES.get(cls, "?") if cls is not None else "?",
                    "map_id": m, "map": map_name(m), "zone_id": None, "zone": None, "area_id": None, "area": None,
                    "x": x, "y": y, "z": z, "text": unhex(r[3]), "status": st,
                    "ticket_state": {0: "open", 1: "closed", 2: "character deleted"}.get(typ, "?"),
                    "response": unhex(r[13]), "created": num_or(r[4]), "tele": tele_cmd(x, y, z, m)})
    return out


def api_reports(q):
    status = report_status_arg(q.get("status"))
    search = report_search(q.get("q"))
    out = {"status": status or "all", "q": search, "states": REPORT_STATES, "reports": [], "tickets": [],
           "error": None, "ticket_error": None}
    try:
        out["reports"] = query_reports(status, search)
    except ToolError:
        out["error"] = "could not read ov_bug_reports (is ov_reports.lua loaded? it creates the table)"
    if q.get("tickets", "1") != "0":
        try:
            out["tickets"] = query_tickets(status, search)
        except ToolError:
            out["ticket_error"] = "could not read gm_ticket"
    items = out["reports"] + out["tickets"]
    items.sort(key=lambda r: (r["created"] or 0, r["kind"] == "report", r["id"] or 0), reverse=True)
    out["items"] = items
    try:
        counts = sql("acore_characters", "SELECT status, COUNT(*) FROM ov_bug_reports GROUP BY status;\n")
        out["counts"] = {r[0]: num_or(r[1]) for r in counts if len(r) == 2}
    except ToolError:
        out["counts"] = {}
    return out


def a_report_status(a):
    rid = intval(a.get("id"), 1, 2 ** 32 - 1, "report id")
    st = str(a.get("status") or "").strip().lower()
    if st not in REPORT_STATES:
        raise Bad("status: " + ", ".join(REPORT_STATES))
    rows = sql("acore_characters", "UPDATE ov_bug_reports SET status = '%s' WHERE id = %d;\n"
               "SELECT status FROM ov_bug_reports WHERE id = %d;\n" % (st, rid, rid))
    if not rows or rows[-1][0] != st:
        raise Bad("no bug report #%d" % rid)
    return "report #%d: %s" % (rid, st)


ACTIONS["report_status"] = (a_report_status, False, ("id", "status"))


def export_new_reports(q):
    """New bug reports (and new GM tickets) for a scheduled triage task. Read-only."""
    since = intval(q.get("since") or 0, 0, 2 ** 32 - 1, "since")
    reports = query_reports("new", "", limit=500, since=since)
    try:
        tickets, terr = query_tickets("new", "", limit=200), None
    except ToolError:
        tickets, terr = [], "could not read gm_ticket"
    return {"realm": SLUG, "at": now_iso(), "since": since, "count": len(reports), "reports": reports,
            "tickets": tickets, "ticket_error": terr}


# ----------------------------------------------------------------------------------------------
# Health (read-only)
# ----------------------------------------------------------------------------------------------

ERROR_LINE = re.compile(r"(?i)(\berror\b|\bfatal\b|crash|assert|exception|\bfailed\b)")


def error_logs(n=20):
    def get():
        rc, out = docker("logs", "--tail", "4000", WORLD, timeout=30)
        if rc != 0:
            return ["(no world server log: " + out[:120] + ")"]
        return [ln[:400] for ln in clean_lines(out) if ERROR_LINE.search(ln)][-n:]
    return cached("errlogs:%d" % n, 15, get)


def parse_size(s):
    m = re.match(r"\s*([\d.]+)\s*([KMGT]?i?B)?", s or "")
    if not m:
        return None
    unit = (m.group(2) or "B").upper().replace("I", "")
    mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}.get(unit, 1)
    return int(float(m.group(1)) * mult)


def container_stats():
    def get():
        rc, out = docker("stats", "--no-stream", "--format", "{{json .}}", WORLD, DB, timeout=30)
        if rc != 0:
            return {"error": "docker stats failed: " + out[:160]}
        res = {}
        for line in out.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            used, _, limit = (d.get("MemUsage") or "").partition("/")
            res[d.get("Name") or d.get("Container") or ""] = {
                "cpu_pct": num_or((d.get("CPUPerc") or "").rstrip("%"), float),
                "mem_pct": num_or((d.get("MemPerc") or "").rstrip("%"), float),
                "mem_used": parse_size(used), "mem_limit": parse_size(limit), "mem_usage": d.get("MemUsage") or ""}
        return res
    return cached("dstats", 10, get)


def api_health(q):
    p = api_players({})
    st = container_stats()
    by = {c["name"]: c for c in containers()}
    return {"realm": p["realm"], "players_real": None if p.get("error") else len(p["players"]),
            "bots_online": p["bots_online"], "players_error": p.get("error"),
            "world": dict(st.get(WORLD) or {}, health=health(by.get(WORLD)), started=iso_to_epoch(started_at(WORLD))),
            "database": dict(st.get(DB) or {}, health=health(by.get(DB)), started=iso_to_epoch(started_at(DB))),
            "stats_error": st.get("error"), "host": host_stats(), "errors": error_logs(20), "at": now_iso()}


GETS = {"/api/overview": api_overview, "/api/players": api_players, "/api/accounts": api_accounts,
        "/api/updates": api_updates, "/api/streaming": api_streaming, "/api/beacons": api_beacons,
        "/api/speed": api_speed, "/api/logs": api_logs, "/api/jobs": api_jobs,
        "/api/reports": api_reports, "/api/health": api_health}
EXPORT_PATH = "/api/export/new-reports"

# The owner's tools on his PC (C:\Users\campw\Desktop\WrathUnleashed): uploads still come from these.
BATS = [
    {"bat": r"realm\Update realm scripts.bat", "what": "Sends Lua scripts (default ov_main.lua) and runs reload ale. Backs up; a refused reload puts the old files back.",
     "when": "Lua-only realm changes. Nobody is disconnected.", "restart": "no"},
    {"bat": r"realm\Fix character create.bat", "what": "charfix_world.sql: all 83 race/class pairs, start zones, gear. Backs up the tables.",
     "when": "Once, or after the world DB was rebuilt. Undo: Rollback character fix.bat.", "restart": "world (2-10 min)"},
    {"bat": r"realm\Stop slow-load kicks.bat", "what": "SocketTimeOutTimeActive = 10 min in the profile.",
     "when": "Once (Updates shows whether it holds).", "restart": "world"},
    {"bat": r"stream\Update browser client.bat", "what": "New browser client into stream/www (the previous one kept as www.old), then stream-up.sh.",
     "when": "A new client build. Only new page loads get it.", "restart": "wu-play, wu-portal"},
    {"bat": r"stream\Roll back browser client.bat", "what": "Swaps www and www.old, restarts wu-play. Same as the button here.",
     "when": "The new client is bad.", "restart": "wu-play"},
    {"bat": r"stream\Make mini slice.bat", "what": "Builds the streamed slice from your Data folder and uploads it (3 SSH logins).",
     "when": "Tier changes in slices\\mini.json. Note: it deletes www.old (no client rollback after it).", "restart": "wu-play"},
    {"bat": r"stream\Add Forever UI to the stream.bat", "what": "Lays Forever UI over the slice and the boot list.",
     "when": "Forever UI art changed. The on/off switch is here (Streaming).", "restart": "wu-play"},
    {"bat": r"server\Speed up downloads.bat", "what": "BBR + fq + no slow start after idle, UDP 443 for HTTP/3.",
     "when": "Once; the Speed tab checks it still holds after a reboot.", "restart": "caddy (seconds)"},
    {"bat": r"server\Deploy Wrath to my server.bat", "what": "The full deploy (deploy.sh): images, databases, profile SQL, sign-in page, Caddy.",
     "when": "New realm images or modules only. The heavy hammer.", "restart": "everything"},
]
TRAIN = [
    ("Preflight", "Overview all green, disk free over 3 GB, no action running. Note the client build and world uptime."),
    ("Backup", "The .bat tools back up what they replace (lua-backups, charfix-backups, www.old, Caddyfile backups). Before a DB change take a dump (deploy.sh does)."),
    ("Apply", "Run ONE .bat for the change (table below), then the matching button here: Reload realm scripts, or Restart world with a countdown."),
    ("Health check", "Overview green, world update diff under 100 ms, Players list loads, Beacons status.json online, Logs: no new Lua errors."),
    ("Roll back", "Anything red: Roll back browser client here, or restore the backup the .bat printed, then Reload / Restart again."),
]


# ----------------------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------------------

SESSIONS = {}
_sess_lock = threading.Lock()
_fails = []
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf" content="%s"><title>WrathUnleashed GM</title><link rel="stylesheet" href="/static/art/wu-theme.css">
<link rel="stylesheet" href="/static/app.css">
<link rel="icon" href="data:,"></head><body class="wu"><div id="app"></div><script src="/static/app.js"></script></body></html>"""
NOAUTH = b"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GM console</title><link rel="stylesheet" href="/static/art/wu-theme.css"><link rel="stylesheet" href="/static/app.css"></head>
<body class="wu"><main class="signed-out wu-panel"><div class="wu-brand"><h1>GM console</h1></div><hr class="wu-divider">
<p>Not signed in. Open the console with <b>Open GM Console.bat</b> on your PC.</p></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "wu-gmconsole"
    sys_version = ""

    def log_message(self, fmt, *args):
        # never the query string: /login?t=<token> must not reach a log
        sys.stderr.write("%s %s %s\n" % (now_iso(), self.command, urllib.parse.urlsplit(self.path).path[:120]))

    def headers_common(self, ctype, length):
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        body = redact(body.decode("utf-8", "replace")).encode("utf-8") if ctype.startswith("application/json") else body
        self.send_response(code)
        self.headers_common(ctype, len(body))
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def host_ok(self):
        h = (self.headers.get("Host") or "").lower()
        allowed = {"127.0.0.1:%d" % PORT, "localhost:%d" % PORT, "[::1]:%d" % PORT} | EXTRA_HOSTS
        return h in allowed

    def session(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "gmc_s" and v:
                with _sess_lock:
                    s = SESSIONS.get(v)
                    if s and s["exp"] > time.time():
                        return s
        return None

    def do_HEAD(self):
        self.do_GET()

    def art(self, name):
        """GET /static/art/<name>: the shared look, from the allow-list, cached (the theme for an hour, the art
        for a week). No login needed: it is our own art, nothing private."""
        body = art_bytes(name)
        if body is None:
            return self.send(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", ART_TYPES[name])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=%d" % (3600 if name.endswith(".css") else 604800))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path.startswith("/static/art/"):
            return self.art(urllib.parse.unquote(u.path[len("/static/art/"):]))
        if u.path == "/static/app.css":     # styles only, so the signed-out page has the look too
            with open(os.path.join(STATIC_DIR, "app.css"), "rb") as f:
                return self.send(200, f.read(), "text/css; charset=utf-8")
        if u.path == "/healthz":
            return self.send(200, b"ok\n", "text/plain")
        if u.path == "/login":
            return self.login(q.get("t", ""))
        if u.path == EXPORT_PATH:
            return self.export(q)
        s = self.session()
        if not s:
            if u.path.startswith("/api/"):
                return self.send(401, {"error": "not signed in"})
            return self.send(401, NOAUTH, "text/html; charset=utf-8")
        if u.path == "/":
            return self.send(200, SHELL % s["csrf"], "text/html; charset=utf-8")
        if u.path in ("/static/app.js", "/static/app.css"):
            p = os.path.join(STATIC_DIR, os.path.basename(u.path))
            with open(p, "rb") as f:
                return self.send(200, f.read(), "text/javascript; charset=utf-8" if p.endswith(".js") else "text/css; charset=utf-8")
        fn = GETS.get(u.path)
        if not fn:
            return self.send(404, {"error": "not found"})
        try:
            return self.send(200, fn(q))
        except Bad as e:
            return self.send(400, {"error": str(e)})
        except ToolError as e:
            return self.send(502, {"error": str(e)})

    def export(self, q):
        """GET /api/export/new-reports[?since=<id>] with "Authorization: Bearer <GM_TOKEN>" from loopback
        only (for a scheduled triage task on the server). No cookie, no query-string token."""
        if self.client_address[0] not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return self.send(403, {"error": "loopback only"})
        now = time.time()
        _fails[:] = [x for x in _fails if now - x < 600]
        if len(_fails) >= 20:
            return self.send(429, {"error": "too many wrong tokens; wait 10 minutes"})
        auth = self.headers.get("Authorization") or ""
        tok = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        if not tok or not hmac.compare_digest(tok.encode(), TOKEN.encode()):
            _fails.append(now)
            time.sleep(0.5)
            return self.send(401, {"error": "Authorization: Bearer <GM_TOKEN> required"})
        try:
            return self.send(200, export_new_reports(q))
        except Bad as e:
            return self.send(400, {"error": str(e)})
        except ToolError as e:
            return self.send(502, {"error": str(e)})

    def login(self, t):
        now = time.time()
        _fails[:] = [x for x in _fails if now - x < 600]
        if len(_fails) >= 20:
            return self.send(429, {"error": "too many wrong tokens; wait 10 minutes"})
        if not t or not hmac.compare_digest(t.encode(), TOKEN.encode()):
            _fails.append(now)
            time.sleep(0.5)
            return self.send(401, NOAUTH, "text/html; charset=utf-8")
        sid = secrets.token_urlsafe(32)
        with _sess_lock:
            for k in [k for k, v in SESSIONS.items() if v["exp"] < now]:
                del SESSIONS[k]
            SESSIONS[sid] = {"csrf": secrets.token_urlsafe(24), "exp": now + SESSION_TTL}
        audit("login", {}, "ok")
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", "gmc_s=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d" % (sid, SESSION_TTL))
        self.headers_common("text/plain", 0)
        self.end_headers()

    def do_POST(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        u = urllib.parse.urlsplit(self.path)
        s = self.session()
        if not s:
            return self.send(401, {"error": "not signed in"})
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT):
            return self.send(403, {"error": "bad origin"})
        tok = self.headers.get("X-CSRF") or ""
        if not tok or not hmac.compare_digest(tok.encode(), s["csrf"].encode()):
            return self.send(403, {"error": "bad CSRF token: reload the page"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, {"error": "JSON only"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > 20000:
            return self.send(413, {"error": "too big"})
        try:
            args = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self.send(400, {"error": "bad JSON"})
        if u.path == "/logout":
            with _sess_lock:
                SESSIONS.pop(next((k for k, v in SESSIONS.items() if v is s), ""), None)
            return self.send(200, {"ok": True})
        m = re.match(r"^/api/action/([a-z_]+)$", u.path)
        if not m:
            return self.send(404, {"error": "not found"})
        try:
            return self.send(200, do_action(m.group(1), args))
        except Bad as e:
            return self.send(400, {"error": str(e)})
        except Busy as e:
            return self.send(409, {"error": str(e)})
        except ToolError as e:
            return self.send(502, {"error": str(e)})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    fam = socket.AF_INET6 if ":" in BIND else socket.AF_INET
    Server.address_family = fam
    httpd = Server((BIND, PORT), Handler)
    sys.stderr.write("%s wu-gmconsole on http://%s:%d (loopback only)\n" % (now_iso(), BIND, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
