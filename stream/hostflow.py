"""Host a realm from the website: the "+ Your server" flow (stream/wrath_portal.py hooks it in).

    GET  /wrath/host               signed out: to the site's sign-in and back here. Signed in: the form
                                   (realm name, preset, house rules, public or private, the GM account
                                   name, a tagline) and the account's own realms
    POST /wrath/host               checks everything, makes a pending realm for this account, 303 to its page
    GET  /wrath/host/<id>          owner only: the share link, the one-click setup for the host's PC and
                                   live status ("Waiting for your PC" -> "Online, listed"; meta refresh)
    GET  /wrath/host/<id>/leyline-<id>.sh    owner only: Mac/Linux, runs `leyline host` with the answers
    GET  /wrath/host/<id>/leyline-<id>.bat   owner only: Windows, runs "Host a Wrath realm.bat" the same way

The realm runs on the host's own PC (free) and reaches players through the Leyline relay. A pending
realm has a page id (16 base32 letters, the shape of a realm id but not one), an invite secret and a host
secret (B32, the same lengths setup.py makes), and a claim token that ties the realm to the Hero Key account
that made it. The download carries them to the PC as one base64 "seed" v2 (setup.py init --seed), used once
and deleted there. The realm's Ed25519 key, and so its realm id, is made ON THE HOST'S PC (setup.py), as
wunet/keys.py says: the website never holds a realm key. The PC's agent shows the relay
pair_hash(claim token) = sha256("leyline-pair-v1\n" + token); the website asks the relay
(GET /api/pair/<hash>) which realm that is, and from then on the page shows that realm id's links and status.
Records made before this (seed v1) carried a website-made key: they still work, and the site still forgets
such a key once the realm connects.

Nothing here makes game accounts or sets passwords: the host makes the GM account on their own join
page (the host link) with a password only their browser sees. The download holds only this realm's own
key and links: never the site's settings, other realms, or anyone's sign-in.

Status comes from the relay's public API (GET /api/realms/<id>: online) and the realm list
(wrath_portal.community_realms: listed). With WU_LISTING_SITE_SECRET set, a listed public realm is
claimed for its account (POST /api/listing/claims, hosting/relay/wurelay/listing.py) once its signed
heartbeat carries the claim token.

Settings (environment):
  WU_HOST_DIR             where pending realms are kept, one 0600 JSON file each (default /hosted, a
                          writable volume; the portal's /app is read-only)
  WU_HOST_KIT_URL         the host kit download (shown on the start page; unset: the zip on the public
                          Leyline repo's "host-kit" release, published by the "hostkit" step)
  WU_LISTING_SITE_SECRET  the relay's RELAY_LISTING_SITE_SECRET, for claims (unset: no claims)
  WU_HOST_PER_ACCOUNT     realms one account may make (default 3)

Standard library only (plus wunet/ed25519_pure.py, loaded from beside this file or from the repo).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import importlib.util
import json
import os
import re
import secrets
import shlex
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOST_DIR = os.environ.get("WU_HOST_DIR", "/hosted")
KIT_URL_DEFAULT = "https://github.com/orionopenwow/Leyline/releases/download/host-kit/WrathUnleashed-host-kit.zip"
KIT_URL = os.environ.get("WU_HOST_KIT_URL") or KIT_URL_DEFAULT
SITE_SECRET = os.environ.get("WU_LISTING_SITE_SECRET", "")
PER_ACCOUNT = int(os.environ.get("WU_HOST_PER_ACCOUNT", "3") or 3)
MAX_TOTAL = 5000
GUIDE_URL = "/wrath/docs/hosting"      # docs/leyline/hosting.md, served by the portal (the repo is private)

# The same rules as setup.py and the relay.
NAME_RE = re.compile(r"^[A-Za-z0-9 _'-]{1,32}$")
GM_RE = re.compile(r"^[A-Za-z0-9]{3,16}$")
RID_RE = re.compile(r"^[a-z2-7]{16}$")
B32 = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
BANNED = re.compile(r"(?i)world\s*of\s*warcraft|\bwow\b|warcraft|lich\s*king|blizzard")
PRESETS = {   # setup.py PROFILES, in the order the form shows them (dalaran first: the default)
    "dalaran": ("Dalaran hangout", "Light on your PC, no bots: everyone boosts to 80 and meets in Dalaran."),
    "main": ("Classic levelling", "The full world from level 1, with a one-time boost to 80 for anyone who wants it."),
    "brawl": ("Brawl", "Everyone starts at 80 in Dalaran with everything unlocked."),
    "progression": ("Progression", "Level 1x through the original world, then the two expansions, per character."),
}
DEFAULT_TAGLINE = {"dalaran": "A Dalaran hangout: boost to 80, duel, queue, meet."}
DEFAULT_RULES = ("Be kind: no harassment, hate speech or spam.\n"
                 "Duel anyone who agrees; no griefing in Dalaran.\n"
                 "No cheats, bots or exploits.\n"
                 "The host's word is final: the host is the GM here.")
MAX_RULES, RULE_LEN, TAGLINE_LEN = 10, 120, 80
FORM_BYTES = 8192
STATUS_TTL = 10
REFRESH = 15
POSTS_PER_MIN = 20   # per address

_get = None          # the portal's globals, looked up late (bind)
_lock = threading.Lock()
_status: dict = {}
_csrf_key = secrets.token_bytes(32)


def bind(getter) -> None:
    """getter(name) -> one of the portal's globals (portal_get, render, leyline_css, community_realms, ...)."""
    global _get
    _get = getter


def P(name):
    return _get(name)


# ----------------------------------------------------------------------------------------------
# Realm keys (the same as wunet/keys.py: realm id = base32(sha256(public key))[:16])
# ----------------------------------------------------------------------------------------------

def _load_ed25519():
    for p in (os.path.join(HERE, "ed25519_pure.py"),
              os.path.join(HERE, "..", "hosting", "kit", "tools", "wunet", "ed25519_pure.py")):
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("wu_ed25519", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("ed25519_pure.py not found")


ed25519 = _load_ed25519()


def realm_id(public: bytes) -> str:
    return base64.b32encode(hashlib.sha256(public).digest()).decode().lower()[:16]


def gen(n: int) -> str:
    return "".join(secrets.choice(B32) for _ in range(n))


def new_realm_secrets() -> dict:
    """A pending realm: a page id, the links' secrets and the claim (= pairing) token. No key: the PC makes it."""
    while True:
        pid = base64.b32encode(os.urandom(10)).decode().lower()
        if not load(pid):
            break
    return {"pending_id": pid, "realm_id": None, "invite_secret": gen(20), "host_secret": gen(24),
            "claim": secrets.token_urlsafe(18)}


PAIR_CTX = b"leyline-pair-v1\n"


def pair_hash(token: str) -> str:
    """The same as hosting/kit/tools/wunet/keys.py pair_hash: what the realm's agent shows the relay."""
    return hashlib.sha256(PAIR_CTX + token.encode("utf-8")).hexdigest()


def page_id(rec: dict) -> str:
    """The id in this realm's page and download addresses (the pending id; an older record's realm id)."""
    return rec.get("pending_id") or rec["realm_id"]


# ----------------------------------------------------------------------------------------------
# The store: one file per pending realm, 0600, in HOST_DIR/realms
# ----------------------------------------------------------------------------------------------

def _dir() -> str:
    d = os.path.join(HOST_DIR, "realms")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def load(rid: str) -> dict | None:
    if not RID_RE.match(rid or ""):
        return None
    try:
        with open(os.path.join(_dir(), rid + ".json"), encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) and (doc.get("pending_id") or doc.get("realm_id")) == rid else None
    except (OSError, ValueError):
        return None


def save(rec: dict) -> None:
    d = _dir()
    pid = page_id(rec)
    tmp = os.path.join(d, pid + ".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, sort_keys=True)
    os.replace(tmp, os.path.join(d, pid + ".json"))


def all_ids() -> list[str]:
    try:
        return [n[:-5] for n in os.listdir(_dir()) if n.endswith(".json") and RID_RE.match(n[:-5])]
    except OSError:
        return []


def realms_of(owner: str) -> list[dict]:
    out = [r for r in (load(i) for i in all_ids()) if r and hmac.compare_digest(r.get("owner", ""), owner)]
    return sorted(out, key=lambda r: r.get("created", 0))


def owner_key(user: str) -> str:
    """The account's game login (one per web user, e.g. WR000123) is its stable id here."""
    return user.upper()


# ----------------------------------------------------------------------------------------------
# The form
# ----------------------------------------------------------------------------------------------

def _one_line(v: str) -> str:
    return " ".join(v.replace("\x00", "").split())


def validate(form: dict) -> tuple[dict, dict]:
    """(clean answers, errors by field). form: field -> str."""
    g = lambda k: form.get(k, "") if isinstance(form.get(k, ""), str) else ""   # noqa: E731
    err, out = {}, {}
    name = _one_line(g("name"))
    if not name:
        err["name"] = "Give your realm a name."
    elif not NAME_RE.match(name):
        err["name"] = "Realm names: up to 32 letters, digits, spaces, _ ' or -."
    elif _get is not None and name.lower() == str(P("REALM_NAME")).lower():
        err["name"] = "That's the official realm's name: pick your own."
    out["name"] = name
    preset = g("preset") or "dalaran"
    if preset not in PRESETS:
        err["preset"] = "Pick one of the presets."
        preset = "dalaran"
    out["preset"] = preset
    vis = g("visibility") or "public"
    if vis not in ("public", "private"):
        err["visibility"] = "Choose public or private."
        vis = "public"
    out["visibility"] = vis
    gm = g("gm").strip()
    if not GM_RE.match(gm):
        err["gm"] = "Your GM account name: 3 to 16 letters or digits (you make this account yourself)."
    out["gm"] = gm.upper() if GM_RE.match(gm) else gm[:16]
    tag = _one_line(g("tagline"))
    if len(tag) > TAGLINE_LEN:
        err["tagline"] = f"The tagline is one line of up to {TAGLINE_LEN} characters."
    out["tagline"] = tag[:TAGLINE_LEN]
    raw = g("rules").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_one_line(x) for x in raw.split("\n")]
    lines = [x for x in lines if x]
    if len(raw) > 2000 or len(lines) > MAX_RULES or any(len(x) > RULE_LEN for x in lines):
        err["rules"] = f"Up to {MAX_RULES} house rules, one per line, {RULE_LEN} characters each."
    if any(ord(c) < 32 and c not in "\n\t" for c in raw):
        err["rules"] = "House rules: plain text only."
    out["rules"] = lines[:MAX_RULES]
    for k, text in (("name", name), ("tagline", tag), ("rules", " ".join(lines))):
        if k not in err and BANNED.search(text):
            err[k] = "Please leave game and publisher brand names out: Leyline is its own project."
    return out, err


def csrf(owner: str) -> str:
    return hmac.new(_csrf_key, ("host:" + owner).encode(), hashlib.sha256).hexdigest()[:32]


# ----------------------------------------------------------------------------------------------
# Status: the relay's API and the realm list
# ----------------------------------------------------------------------------------------------

def relay_api() -> str:
    """The relay's base URL: the one the realm list reads (often its Docker-network address), else the join base."""
    try:
        u = P("listing_url")()
        if u.endswith("/api/listing/realms.json"):
            return u[: -len("/api/listing/realms.json")]
    except Exception:  # noqa: BLE001
        pass
    return P("JOIN_BASE")


def relay_online(rid: str) -> bool | None:
    """True / False from GET /api/realms/<id>; None when the relay doesn't know it yet or can't be reached."""
    now = time.monotonic()
    with _lock:
        hit = _status.get(rid)
        if hit and now - hit[0] < STATUS_TTL:
            return hit[1]
    v = None
    try:
        req = urllib.request.Request(f"{relay_api()}/api/realms/{rid}", headers={"Accept": "application/json",
                                                                                 "User-Agent": "wrath-portal"})
        with urllib.request.urlopen(req, timeout=2.5) as r:
            doc = json.loads(r.read(65536).decode("utf-8"))
        v = bool(doc.get("online")) if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        v = None
    with _lock:
        _status[rid] = (now, v)
        if len(_status) > 5000:
            _status.clear()
    return v


def relay_pair(rec: dict) -> str | None:
    """The realm id the host's PC registered with this record's token (GET /api/pair/<hash> on the relay), or None
    (not yet, or the relay can't be reached). Cached like relay_online."""
    h = pair_hash(rec["claim"])
    now = time.monotonic()
    with _lock:
        hit = _status.get("pair:" + h)
        if hit and now - hit[0] < STATUS_TTL:
            return hit[1]
    v = None
    try:
        req = urllib.request.Request(f"{relay_api()}/api/pair/{h}", headers={"Accept": "application/json",
                                                                             "User-Agent": "wrath-portal"})
        with urllib.request.urlopen(req, timeout=2.5) as r:
            doc = json.loads(r.read(65536).decode("utf-8"))
        rid = doc.get("realm_id") if isinstance(doc, dict) else None
        v = rid if isinstance(rid, str) and RID_RE.match(rid) else None
    except Exception:  # noqa: BLE001 - 404 (not yet) or unreachable: ask again on the next view
        v = None
    with _lock:
        _status["pair:" + h] = (now, v)
    return v


def listed_entry(rid: str) -> dict | None:
    try:
        realms, _ok = P("community_realms")()
    except Exception:  # noqa: BLE001
        return None
    return next((r for r in realms if r.get("id") == rid), None)


def try_claim(rec: dict) -> None:
    """A listed public realm whose heartbeat carries the claim token: bind it to the account (once)."""
    if not SITE_SECRET or rec.get("claimed") or not rec.get("claim"):
        return
    body = json.dumps({"realm_id": rec["realm_id"], "token": rec["claim"],
                       "claimed_by": (rec.get("owner_display") or "a Hero Key account")[:40]}).encode()
    req = urllib.request.Request(f"{relay_api()}/api/listing/claims", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + SITE_SECRET})
    try:
        with urllib.request.urlopen(req, timeout=2.5) as r:
            if r.status == 200:
                rec["claimed"] = True
    except Exception:  # noqa: BLE001 - not yet (the next heartbeat carries it); tried again on the next view
        return


def status_of(rec: dict) -> tuple[str, str, bool]:
    """(state, text, final). Also learns the realm id from the relay (pairing), forgets an old record's realm key
    once the PC has connected, and claims."""
    changed = False
    if not rec.get("realm_id"):
        rid = relay_pair(rec) if rec.get("claim") else None
        if not rid:
            return ("waiting", "Waiting for your PC", False)
        rec["realm_id"] = rid
        rec["first_online"] = int(time.time())
        changed = True
    rid = rec["realm_id"]
    online = relay_online(rid)
    entry = listed_entry(rid) if rec["visibility"] == "public" else None
    if (online or entry) and rec.get("realm_key"):
        rec["realm_key"] = None            # the PC holds it now; the site keeps no copy
        rec["first_online"] = int(time.time())
        changed = True
    if entry and entry.get("live"):
        if not entry.get("claimed") and not rec.get("claimed"):
            try_claim(rec)
            changed = changed or bool(rec.get("claimed"))
        state = ("listed", "Online, listed", True)
    elif online and rec["visibility"] == "private":
        state = ("online", "Online, private: friends join with your invite link", True)
    elif online:
        state = ("online", "Online: joining the realm list (about a minute)", False)
    elif rec.get("first_online"):
        state = ("offline", "Your PC is offline: start it again to bring the realm back", False)
    else:
        state = ("waiting", "Waiting for your PC", False)
    if changed:
        save(rec)
    return state


# ----------------------------------------------------------------------------------------------
# The download: a seed for setup.py init --seed, and a script that runs the kit with it
# ----------------------------------------------------------------------------------------------

def relay_host() -> str:
    return urllib.parse.urlsplit(P("JOIN_BASE")).hostname or "relay.openvanilla.app"


def seed_b64(rec: dict) -> str:
    """v2: the links' secrets, the claim (pairing) token and the answers; no key (the PC makes it). An older record
    that still holds a website-made key gets the v1 seed it was made for."""
    doc = {"v": 2, "invite_secret": rec["invite_secret"], "host_secret": rec["host_secret"], "claim": rec["claim"],
           "name": rec["name"], "profile": rec["preset"], "visibility": rec["visibility"],
           "gm_name": rec["gm"], "tagline": rec.get("tagline", ""), "rules": rec.get("rules", [])}
    if rec.get("realm_key"):
        doc.update(v=1, realm_id=rec["realm_id"], realm_key=rec["realm_key"])
    return base64.b64encode(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")


def script_sh(rec: dict) -> bytes:
    q = shlex.quote
    rid = page_id(rec)
    return (
        "#!/usr/bin/env bash\n"
        f"# Leyline: start your realm \"{rec['name']}\" on this Mac or Linux PC.\n"
        "# Put this file in your unzipped host kit folder (next to the `leyline` script), then run:\n"
        f"#   bash leyline-{rid}.sh\n"
        "# It sets up the realm with the answers you gave on the website and starts it with `leyline host`.\n"
        "# It holds this realm's links and its claim token: yours, keep it private.\n"
        "# The realm's key is made on this PC and never leaves it. No passwords, no accounts:\n"
        f"# you make your GM account {rec['gm']} yourself on your own join page (leyline status shows it).\n"
        "set -euo pipefail\n"
        'KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        '[ -f "$KIT/leyline" ] || { echo "Put this file in your host kit folder (next to leyline), then run it again."; exit 1; }\n'
        'mkdir -p "$KIT/state"\n'
        "umask 077\n"
        "cat > \"$KIT/state/seed.b64\" <<'SEED'\n"
        f"{seed_b64(rec)}\n"
        "SEED\n"
        "export WU_SEED=state/seed.b64 LEYLINE_NONINTERACTIVE=1\n"
        f"export LEYLINE_NAME={q(rec['name'])} LEYLINE_RULESET={q(rec['preset'])} "
        f"LEYLINE_VISIBILITY={q(rec['visibility'])} LEYLINE_GM={q(rec['gm'])}\n"
        f'export WU_RELAY="${{WU_RELAY:-{relay_host()}}}"\n'
        'exec bash "$KIT/leyline" host "$@"\n').encode("utf-8")


def script_bat(rec: dict) -> bytes:
    lines = [
        "@echo off",
        "setlocal",
        f"title Leyline - start {rec['name']}",
        f"rem Leyline: start your realm \"{rec['name']}\" on this Windows PC. Needs Docker Desktop.",
        "rem Put this file in your unzipped host kit folder (next to \"Host a Wrath realm.bat\") and double-click it.",
        "rem It sets up the realm with the answers you gave on the website, then starts it.",
        "rem It holds this realm's links and its claim token: yours, keep it private.",
        "rem The realm's key is made on this PC and never leaves it. No passwords, no accounts:",
        f"rem you make your GM account {rec['gm']} yourself on your own join page (state\\host-link.txt).",
        'cd /d "%~dp0"',
        'if not exist "Host a Wrath realm.bat" (echo Put this file in your host kit folder, next to "Host a Wrath realm.bat", then run it again. & pause & exit /b 1)',
        "docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it ^(or install it from docker.com^), then run this again. & pause & exit /b 1)",
        'if not defined WU_TOOLS_PREBUILT set "WU_TOOLS_PREBUILT=ghcr.io/orionopenwow/wu-host-tools:1"',
        'set "WU_TOOLS_IMAGE=wu-host-tools:1"',
        'docker pull -q "%WU_TOOLS_PREBUILT%" >nul 2>&1 && docker tag "%WU_TOOLS_PREBUILT%" "%WU_TOOLS_IMAGE%"',
        'docker image inspect "%WU_TOOLS_IMAGE%" >nul 2>&1 || docker build -q -t "%WU_TOOLS_IMAGE%" "%~dp0tools" >nul || (echo Building the helper image failed. Is this PC online? & pause & exit /b 1)',
        f'if not defined WU_RELAY set "WU_RELAY={relay_host()}"',
        'if not exist "state" mkdir "state"',
        f'> "state\\seed.b64" echo {seed_b64(rec)}',
        'docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup init --seed state/seed.b64 --relay %WU_RELAY% >nul || (echo Setting up the realm failed ^(see above^). & pause & exit /b 1)',
        f'set "WU_NAME={rec["name"]}"',
        f'set "WU_PROFILE={rec["preset"]}"',
        f'set "WU_VISIBILITY={rec["visibility"]}"',
        'call "Host a Wrath realm.bat"',
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# ----------------------------------------------------------------------------------------------
# Pages (the Leyline look)
# ----------------------------------------------------------------------------------------------

HOST_CSS = """
.hf{max-width:760px}.hf .ly-panel{padding:22px 22px 24px}
.hf label{display:block;font-weight:600;margin:14px 0 4px;color:var(--ly-ink)}
.hf .hint{display:block;font-weight:400;font-size:13px;color:var(--ly-dim);margin-top:2px}
.hf input[type=text],.hf textarea{width:100%;background:rgba(5,6,20,.85);color:var(--ly-ink);border:1px solid var(--ly-line);
border-radius:5px;padding:10px 12px;font:15px/1.4 system-ui,sans-serif}
.hf textarea{min-height:120px;resize:vertical}
.hf input:focus,.hf textarea:focus{outline:2px solid var(--ly-cyan);outline-offset:1px}
.hf .opts{display:grid;gap:8px;grid-template-columns:repeat(2,minmax(0,1fr))}
@media (max-width:560px){.hf .opts{grid-template-columns:1fr}}
.hf .opt{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--ly-line);border-radius:6px;padding:10px 12px;
background:rgba(18,22,54,.6);font-weight:400;margin:0;cursor:pointer}
.hf .opt b{display:block;color:var(--ly-cyan)}.hf .opt span{font-size:14px;color:var(--ly-dim)}
.hf .opt input{margin-top:4px;accent-color:#5fe3ff}
.hf .err{color:#ff9a8a;font-size:14px;margin:4px 0 0}
.hf .go{margin-top:20px;display:flex;justify-content:center}
.hf button,.hf a.dl{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:52px;padding:10px 26px;
font:600 20px/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.1em;text-transform:uppercase;cursor:pointer;
color:#1a1030;background:linear-gradient(180deg,#9ff0ff,#5fe3ff);border:1px solid #9ff0ff;border-radius:6px;text-decoration:none}
.hf a.dl{font-size:16px;min-height:44px;padding:8px 18px;color:var(--ly-ink)!important;
background:linear-gradient(180deg,rgba(40,52,110,.92),rgba(16,20,52,.95));border-color:rgba(140,170,255,.45)}
.hf button:focus-visible,.hf a.dl:focus-visible{outline:2px solid #fff;outline-offset:2px}
.hf .row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin:10px 0}
.hf code,.hf .link{display:block;background:rgba(5,6,20,.85);border:1px solid var(--ly-line);border-radius:5px;padding:9px 12px;
font:14px/1.4 ui-monospace,monospace;overflow-wrap:anywhere;color:var(--ly-ink)}
.hf .pill{display:inline-block;border-radius:999px;padding:4px 12px;font-weight:600;font-size:14px;border:1px solid var(--ly-line)}
.hf .pill.waiting{color:#ffd27a;border-color:rgba(255,210,122,.5)}.hf .pill.online,.hf .pill.listed{color:#5ef0a0;border-color:rgba(94,240,160,.5)}
.hf .pill.offline{color:var(--ly-dim)}
.hf ol{padding-left:1.3rem}.hf li{margin:8px 0}.hf .mine a{color:var(--ly-cyan)}
.hf .back{display:inline-block;margin:0 0 6px;font-size:14px}
.hf h1{font-size:clamp(40px,8vw,72px)}
"""

PLUS_CSS = (".ly-plus{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border-radius:999px;text-decoration:none;"
            "font:600 14px/1 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#1a1030!important;"
            "background:linear-gradient(180deg,#9ff0ff,#5fe3ff);border:1px solid #9ff0ff;box-shadow:0 0 14px rgba(95,227,255,.35)}"
            ".ly-plus:hover,.ly-plus:focus-visible{box-shadow:0 0 22px rgba(180,140,255,.6);outline:none}"
            ".ly-plus b{font-size:18px;line-height:1}.ly-plus-row{display:flex;justify-content:center;margin:14px 0}")


def plus_button(where: str = "") -> str:
    """The "+ Your server" button for the realm list, the Leyline page and the account page."""
    return (f'<style>{PLUS_CSS}</style><div class="ly-plus-row"><a class="ly-plus" href="/wrath/host" '
            f'data-where="{html.escape(where)}"><b aria-hidden="true">+</b>Your server</a></div>')


def page(title: str, inner: str, refresh: int = 0) -> bytes:
    e = html.escape
    css = P("leyline_css")() + HOST_CSS
    meta = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<meta name="robots" content="noindex">{meta}<title>{e(title)} · Leyline</title><style>{css}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div><div class="ly-wrap hf">'
            f'<a class="back" href="/wrath/leyline">&larr; Leyline</a>{inner}</div></body></html>').encode("utf-8")


def form_page(owner: str, display: str, vals: dict | None = None, errs: dict | None = None) -> bytes:
    e = html.escape
    vals, errs = vals or {}, errs or {}

    def er(k):
        return f'<p class="err" id="err-{k}">{e(errs[k])}</p>' if k in errs else ""
    preset = vals.get("preset", "dalaran")
    vis = vals.get("visibility", "public")
    rules = vals.get("rules")
    rules_text = "\n".join(rules) if isinstance(rules, list) else (rules if isinstance(rules, str) else DEFAULT_RULES)
    opts = "".join(
        f'<label class="opt"><input type="radio" name="preset" value="{k}"{" checked" if k == preset else ""}>'
        f'<div><b>{e(t)}</b><span>{e(d)}</span></div></label>' for k, (t, d) in PRESETS.items())
    visopts = "".join(
        f'<label class="opt"><input type="radio" name="visibility" value="{k}"{" checked" if k == vis else ""}>'
        f'<div><b>{t}</b><span>{d}</span></div></label>'
        for k, t, d in (("public", "Public", "Listed on the Leyline realm list for everyone."),
                        ("private", "Private", "Only people with your invite link can find and join it.")))
    mine = realms_of(owner)
    mine_html = ""
    if mine:
        mine_html = ('<section class="ly-panel mine"><h2>Your realms</h2><ul>'
                     + "".join(f'<li><a href="/wrath/host/{e(page_id(r))}">{e(r["name"])}</a> '
                               f'<span class="hint">{e(PRESETS[r["preset"]][0])}, {e(r["visibility"])}</span></li>'
                               for r in mine) + '</ul></section>')
    full = len(mine) >= PER_ACCOUNT
    inner = (
        '<header class="ly-hero"><h1>Your server</h1>'
        f'<p class="ly-lede">Signed in as {e(display)}. Your realm runs on your own PC, free, and players reach it '
        'through the Leyline relay: nobody sees your home address and you open no ports.</p></header>'
        + mine_html +
        ('<section class="ly-panel"><p>You have made the most realms one account can for now '
         f'({PER_ACCOUNT}). Open one above to start it.</p></section>' if full else
         '<section class="ly-panel"><h2>New realm</h2>'
         + (f'<p class="err">{e(errs["_"])}</p>' if "_" in errs else "") +
         '<form method="post" action="/wrath/host">'
         f'<input type="hidden" name="csrf" value="{e(csrf(owner))}">'
         '<label for="f-name">Realm name<span class="hint">Up to 32 letters, digits, spaces, _ \' or -</span></label>'
         f'<input type="text" id="f-name" name="name" maxlength="32" required value="{e(vals.get("name", ""))}">{er("name")}'
         f'<label>Preset</label><div class="opts">{opts}</div>{er("preset")}'
         '<label for="f-tag">Tagline<span class="hint">One line for the realm list (optional)</span></label>'
         f'<input type="text" id="f-tag" name="tagline" maxlength="{TAGLINE_LEN}" value="{e(vals.get("tagline", ""))}">{er("tagline")}'
         f'<label for="f-rules">House rules<span class="hint">One per line, up to {MAX_RULES}. Shown on the realm list and your join page.</span></label>'
         f'<textarea id="f-rules" name="rules">{e(rules_text)}</textarea>{er("rules")}'
         f'<label>Who can join</label><div class="opts">{visopts}</div>{er("visibility")}'
         '<label for="f-gm">Your GM account name<span class="hint">3 to 16 letters or digits. You make this game account '
         'yourself on your realm\'s join page, with your own password; it gets GM rights by itself.</span></label>'
         f'<input type="text" id="f-gm" name="gm" maxlength="16" required autocomplete="off" value="{e(vals.get("gm", ""))}">{er("gm")}'
         '<div class="go"><button type="submit">Start server</button></div></form></section>'))
    return page("Your server", inner)


def downloadable(rec: dict) -> bool:
    """The setup file is offered until the PC has registered the realm (or, for an older record, while the site
    still holds its key). Afterwards the PC holds everything: moving the realm = copying the kit folder."""
    return bool(rec.get("realm_key")) or not rec.get("realm_id")


def start_page(rec: dict) -> bytes:
    e = html.escape
    pid = page_id(rec)
    state, text, final = status_of(rec)
    rid = rec.get("realm_id")
    host = P("PUBLIC_HOST")
    join = P("JOIN_BASE")
    kit = KIT_URL or GUIDE_URL
    if downloadable(rec):
        dl = ('<div class="row">'
              f'<a class="dl" href="/wrath/host/{pid}/leyline-{pid}.bat" download>Windows (.bat)</a>'
              f'<a class="dl" href="/wrath/host/{pid}/leyline-{pid}.sh" download>Mac / Linux (.sh)</a></div>'
              '<p class="hint">The file holds your realm\'s links and the token that ties it to your account, so keep '
              'it to yourself. Your PC makes the realm\'s key itself: it never leaves your PC.</p>')
    else:
        dl = ('<p>Your PC holds this realm\'s key, so there is nothing more to download. To move the realm, '
              'copy the kit folder (with its <b>state</b> folder) to the new PC.</p>')
    if rid:
        share = f"https://{host}/wrath/r/{rid}"
        invite = f"{join}/join/{rid}" + (f"#{rec['invite_secret']}" if rec["visibility"] == "private" else "")
        host_link = f"{join}/join/{rid}#{rec['invite_secret']}~{rec['host_secret']}"
        priv = (f'<p>It\'s private: friends need your invite link to join.</p><div class="link">{e(invite)}</div>'
                if rec["visibility"] == "private" else
                '<p>It\'s public: it shows on the realm list for everyone, on the site and in the game, once your PC is online.</p>')
        links = (f'<p>Share this link: it opens your realm\'s page with a preview card.</p>'
                 f'<div class="link">{e(share)}</div>{priv}')
        gm = (f'<li>Make your GM account <b>{e(rec["gm"])}</b> on your own join link (yours only: it can make the GM '
              f'account), with a password you choose:<div class="link">{e(host_link)}</div></li>')
    else:
        links = ('<p>Your realm\'s links appear here as soon as your PC connects: the realm\'s address comes from the '
                 'key your PC makes.</p>')
        gm = (f'<li>Make your GM account <b>{e(rec["gm"])}</b> on your own join link, with a password you choose. The '
              'link shows here (and in the setup window on your PC) once your PC is connected.</li>')
    inner = (
        f'<header class="ly-hero"><h1>{e(rec["name"])}</h1>'
        f'<p class="ly-lede">{e(PRESETS[rec["preset"]][0])} · {e(rec["visibility"])} · GM {e(rec["gm"])}</p>'
        f'<span class="pill {e(state)}" role="status">{"&#9679; " if state in ("online", "listed") else ""}{e(text)}</span></header>'
        f'<section class="ly-panel"><h2>Your link</h2>{links}</section>'
        '<section class="ly-panel"><h2>Set up your PC</h2><ol>'
        f'<li>Install <a href="https://www.docker.com/products/docker-desktop/" rel="noopener noreferrer">Docker</a> '
        f'and unzip the <a href="{e(kit)}" rel="noopener noreferrer">host kit</a>. The server uses your own 3.3.5a game '
        'files, read on your PC; nothing is downloaded or shared.</li>'
        f'<li>Download your realm\'s file into the kit folder and run it.{dl}</li>'
        '<li>Leave it running. This page changes to <b>Online</b> when your PC connects to the relay.</li>'
        + gm +
        '</ol></section>'
        '<p class="ly-fine">The first start imports the databases and can take 5 to 20 minutes. '
        f'<a href="{e(GUIDE_URL)}" rel="noopener noreferrer">Hosting guide</a> · <a href="/wrath/host">Your realms</a></p>')
    return page(rec["name"], inner, refresh=0 if final else REFRESH)


# ----------------------------------------------------------------------------------------------
# Requests (h is the portal's PageHandler)
# ----------------------------------------------------------------------------------------------

DL_RE = re.compile(r"^/wrath/host/([a-z2-7]{16})/leyline-([a-z2-7]{16})\.(sh|bat)$")
START_RE = re.compile(r"^/wrath/host/([a-z2-7]{16})$")


def match(path: str) -> bool:
    return path == "/wrath/host" or path.startswith("/wrath/host/")


def _signin(path: str) -> str:
    return "/login?next=" + urllib.parse.quote(path, safe="")


def who(h, path: str):
    """(owner, display) for the signed-in account, or None after answering (sign-in redirect or an error)."""
    ip = h.ip()
    cookie = h.headers.get("Cookie", "")
    ua = h.headers.get("User-Agent", "")
    if "wr_session=" not in cookie:
        h.redirect(_signin(path))
        return None
    status, me = P("portal_get")("/api/me", cookie, ip, ua)
    if status in (401, 403) or 300 <= status < 400:
        h.redirect(_signin(path))
        return None
    if status != 200 or not me:
        h.send(503, P("error_page")("The website isn't answering right now. Please try again shortly."))
        return None
    status, play = P("portal_get")("/api/play", cookie, ip, ua)
    user = str(play.get("user", "")) if isinstance(play, dict) else ""
    if status != 200 or not re.match(r"^[A-Za-z0-9]{1,16}$", user):
        h.send(503, P("error_page")("Your account isn't ready yet. Please try again in a minute."))
        return None
    display = str(me.get("display_name") or me.get("username") or user)[:40]
    return owner_key(user), display


def _not_found(h):
    h.send(404, page("Not found", '<section class="ly-panel"><h2>Not found</h2><p>There is no realm here for your '
                                  'account. <a href="/wrath/host">Your realms</a></p></section>'))


def get(h, path: str) -> None:
    if not P("page_limit").hit(h.ip(), 120):
        h.send(429, P("busy_page")(back=path))
        return
    m_dl, m_start = DL_RE.match(path), START_RE.match(path)
    if path != "/wrath/host" and not m_dl and not m_start:
        _not_found(h)
        return
    acct = who(h, path)
    if acct is None:
        return
    owner, display = acct
    if path == "/wrath/host":
        h.send(200, form_page(owner, display))
        return
    rid = (m_dl or m_start).group(1)
    rec = load(rid)
    if not rec or not hmac.compare_digest(rec.get("owner", ""), owner) or (m_dl and m_dl.group(2) != rid):
        _not_found(h)
        return
    if m_start:
        h.send(200, start_page(rec))
        return
    if not downloadable(rec):
        h.send(410, page(rec["name"], '<section class="ly-panel"><h2>Already set up</h2><p>Your PC holds this realm\'s '
                                      f'key now. <a href="/wrath/host/{rid}">Back</a></p></section>'))
        return
    kind = m_dl.group(3)
    body = script_sh(rec) if kind == "sh" else script_bat(rec)
    h.send(200, body, "application/octet-stream",
           headers={"Content-Disposition": f'attachment; filename="leyline-{rid}.{kind}"'})


def read_form(h) -> dict | None:
    try:
        n = int(h.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if n < 0 or n > FORM_BYTES:
        return None
    if (h.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded"):
        return None
    try:
        q = urllib.parse.parse_qs(h.rfile.read(n).decode("utf-8"), keep_blank_values=True, max_num_fields=20)
    except (UnicodeDecodeError, ValueError):
        return None
    return {k: v[0] for k, v in q.items()}


def post(h, path: str) -> None:
    if path != "/wrath/host":
        h.send(405, b"method not allowed\n", "text/plain")
        return
    ip = h.ip()
    if not P("gate_limit").hit("host:" + ip, POSTS_PER_MIN):
        h.send(429, P("busy_page")(back="/wrath/host"))
        return
    origin = h.headers.get("Origin", "")
    if origin and origin != f"https://{P('PUBLIC_HOST')}":
        h.send(403, P("error_page")("That form came from another site."))
        return
    form = read_form(h)
    if form is None:
        h.send(400, P("error_page")("That form didn't arrive in one piece. Please try again."))
        return
    acct = who(h, path)
    if acct is None:
        return
    owner, display = acct
    if not hmac.compare_digest(form.get("csrf", ""), csrf(owner)):
        vals, _ = validate(form)
        h.send(400, form_page(owner, display, vals, {"_": "The form timed out. Check your answers and press Start server again."}))
        return
    vals, errs = validate(form)
    if errs:
        h.send(400, form_page(owner, display, vals, errs))
        return
    with _lock:
        if len(realms_of(owner)) >= PER_ACCOUNT:
            h.send(400, form_page(owner, display, vals, {"_": f"One account can make {PER_ACCOUNT} realms for now."}))
            return
        if len(all_ids()) >= MAX_TOTAL:
            h.send(503, form_page(owner, display, vals, {"_": "New realms are paused for a while. Please try again later."}))
            return
        rec = new_realm_secrets()
        rec.update(owner=owner, owner_display=display, created=int(time.time()), name=vals["name"],
                   preset=vals["preset"], visibility=vals["visibility"], gm=vals["gm"],
                   tagline=vals["tagline"] or DEFAULT_TAGLINE.get(vals["preset"], ""), rules=vals["rules"],
                   claimed=False, first_online=None)
        save(rec)
    h.send_response(303)
    h.send_header("Location", f"/wrath/host/{rec['pending_id']}")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", "0")
    h.end_headers()
