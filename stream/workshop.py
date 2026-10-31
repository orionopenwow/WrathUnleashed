"""The mods Workshop on the Wrath portal (stream/wrath_portal.py), in the Leyline look.

    GET /wrath/mods                     the whole catalog: a category grid with counts, then the mods as a card
                                        grid; filters ?kind=ui|realm|both and ?perm=<permission>|none (no realm
                                        permissions) as plain links, and ?q=<text> (name, description, category)
    GET /wrath/mods/c/<category>        one category (mods/categories.json): its line, its mods, the same filters;
                                        an empty one says so and links the modder guide (never fake entries)
    GET /wrath/mods/<id>                one mod: what it does, its permissions in plain words, screenshots,
                                        the zip, "Already on Wrath" when the realm runs it, its share link
    GET /wrath/mods/<id>/download       the mod's zip (the name comes from the catalog, never the URL)
    GET /wrath/mods/<id>/shot/<n>       screenshot n (0-based) of the mod
    GET /wrath/mods/catalog.json        the catalog itself, for tools (CORS *)

Community projects (stream/projects.py): links people add, listed at once beside the packaged mods unless the
hub's rules hold one for a person (no open licence, cheats, decompiled or leaked material: stream/hub.py link_problems);
nothing is hosted, links only. Every card has a Credits line: author, licence, repo.

    GET  /wrath/mods?build=3.3.5a|1.12&source=packaged|community   more filters, with the ones above
    GET  /wrath/mods/p/<pid>             one community project: its credits, the link, Report (Hide for admins)
    GET  /wrath/mods/submit              signed in: the form to add a link;  POST it to add one
    POST /wrath/mods/p/<pid>/report      signed in: report a link;  .../hide, .../unhide: WU_MODS_ADMINS only
    GET  /wrath/mods/credits             every author and project, thanked
    GET  /wrath/mods/all.json            packaged + community in one schema (mods/all-json.md), for the Leyline
                                         Launcher and the in-game window (CORS *):
        {"format": 1, "generated_at", "categories": [{id, name, line, icon}], "builds": ["3.3.5a", "1.12", "any"],
         "projects": [{id ("mod:<id>" | "link:<12 hex>"), source ("packaged" | "community"), name, description,
                       category, builds, author, author_url, licence, repo, page, credits, stars, last_push,
                       submitted_by, submitted_at, last_checked, version, kind, permissions, on_wrath, download,
                       sha256}]}   (packaged-only fields are null for community links; sorted by name)

The data is what "mods/Put mods on Wrath.bat" (stream/server/mods-install.sh) publishes into
$WU/portal/mods, which wu-portal sees as /app/mods (WU_MODS_DIR):

    categories.json   mods/categories.json, copied by the mods step: [{id, name, line, icon}] in order, and
                      kind_defaults {kind: id}. Missing: read from ../mods/categories.json beside this file (a
                      checkout); missing there too: no category bar or pages, the mods still list.
    catalog.json      wu-mod.py catalog: {"format": 1, "mods": [{id, name, version, author, licence, kind,
                      description, category, permissions, screenshots, addons, zip, sha256, size, ...}]}
    installed.json    {"installed": {"<id>": "<version>"}, "at": "..."}: what the realm runs now
    files/<zip>       the packed mods (+ .sha256)
    shots/<id>/<file> their screenshots

Every value from the catalog is checked again here (ids, file names) and HTML-escaped on the way out.
A missing or broken catalog gives an empty Workshop, never an error. Standard library only; the portal
loads this file from beside itself and runs without it (the routes then answer 404).
"""
from __future__ import annotations

import hashlib
import hmac
import html
import importlib.util
import json
import os
import re
import secrets
import threading
import time
import urllib.parse

MODS_DIR = os.environ.get("WU_MODS_DIR", "/app/mods")
ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")           # mods/wu-mod.py ID_RE
VERSION_RE = re.compile(r"^\d{1,5}\.\d{1,5}\.\d{1,5}(?:[-+][0-9A-Za-z.-]{1,40})?$")
SHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(png|jpe?g|webp)$", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
KINDS = ("ui", "realm", "both")
PERMISSIONS = ("commands", "chat", "gossip", "spawns", "events", "db", "timers")
MAX_MODS = 500
MAX_ZIP = 60 * 1024 * 1024
MAX_SHOT = 10 * 1024 * 1024
MAX_QUERY = 60
MAX_FORM = 4096
RESERVED_IDS = {"submit", "credits"}       # Workshop pages: a mod by these names would be shadowed
SOURCES = ("packaged", "community")
SOURCE_LABEL = {"packaged": "Packaged", "community": "Community link"}
BUILD_FILTERS = ("3.3.5a", "1.12")
REPO_BASE = "https://github.com/orionopenwow/Leyline/blob/main/mods/SPEC.md#"
PUBLIC_BASE = "https://" + os.environ.get("PUBLIC_HOST", "play.openvanilla.app")
EXT_REL = 'rel="noopener noreferrer nofollow ugc"'
GUIDE_URL = "https://github.com/orionopenwow/Leyline/blob/main/mods/SPEC.md"
CATEGORIES_FALLBACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mods", "categories.json")
# Line icons by the "icon" name in categories.json (24x24, stroke currentColor). Unknown names get the initial.
ICONS = {
    "interface": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 9v11"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    "dice": '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1"/><circle cx="15" cy="15" r="1"/><circle cx="15" cy="9" r="1"/><circle cx="9" cy="15" r="1"/>',
    "map": '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "blocks": '<rect x="3" y="13" width="8" height="8"/><rect x="13" y="13" width="8" height="8"/><rect x="8" y="3" width="8" height="8"/>',
    "skull": '<path d="M5 11a7 7 0 0 1 14 0v4h-3v4H8v-4H5z"/><circle cx="9" cy="11" r="1.5"/><circle cx="15" cy="11" r="1.5"/>',
    "cube": '<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/>',
    "server": '<rect x="4" y="3" width="16" height="7" rx="1"/><rect x="4" y="14" width="16" height="7" rx="1"/><path d="M8 6.5h.01M8 17.5h.01"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "wrench": '<path d="M14 6a4 4 0 0 0 5 5l-9 9a2 2 0 0 1-3-3l9-9a4 4 0 0 0-2-2z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.3-1.7-.4-1 .3-2.3 1.5-2.3H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
}
SHOT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}

KIND_LABEL = {"ui": "Interface", "realm": "Realm", "both": "Interface + realm"}
KIND_WORDS = {
    "ui": "An addon: it runs in your game and changes nothing on the realm.",
    "realm": "Realm scripts: it runs on the realm for everyone, no addon needed.",
    "both": "Realm scripts plus an addon that shows what they do.",
}
PERM_LABEL = {"commands": "Commands", "chat": "Messages", "gossip": "Talk options", "spawns": "Spawns",
              "events": "Game events", "db": "Own records", "timers": "Timers"}
PERM_WORDS = {
    "commands": "Adds commands you type in chat, such as .dice.",
    "chat": "Sends messages: to players near you, to your group, or to its own addon.",
    "gossip": "Adds talk options to characters, objects or items.",
    "spawns": "Can place characters or objects in the world.",
    "events": "Reacts to things that happen in the game, such as logging in or joining a group.",
    "db": "Keeps its own records on the realm, in its own tables only.",
    "timers": "Runs things on a timer.",
}

_CAT_PATH_RE = re.compile(r"^/wrath/mods/c/([^/]{1,40})$")
_PATH_RE = re.compile(r"^/wrath/mods(?:/(catalog\.json|[^/]{1,40})(?:/(download|shot)(?:/(\d{1,2}))?)?)?$")
_PROJ_RE = re.compile(r"^/wrath/mods/p/([0-9a-f]{12})(?:/(report|hide|unhide))?$")


# A link the hub's rules held (stream/projects.py, stream/hub.py link_problems): said plainly, without the reasons
QUEUED_NOTE = ("Thanks: this one waits for a person to check it before it's listed (we check licences, and keep "
               "cheats and leaked or decompiled material off the Workshop).")


def _load_projects():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects.py")
    try:
        spec = importlib.util.spec_from_file_location("wu_projects", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:   # noqa: BLE001: the Workshop still shows the packaged mods
        return None


projects_mod = _load_projects()

WORKSHOP_CSS = """
.wk-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;margin:0 0 14px}
.wk-bar .lbl{font:600 11px/1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--ly-dim);margin-right:2px}
.wk-chip{display:inline-block;font:600 12px/1 system-ui,sans-serif;letter-spacing:.06em;text-decoration:none;color:var(--ly-dim)!important;
padding:7px 10px;border:1px solid var(--ly-line);border-radius:999px;background:rgba(20,24,60,.6)}
.wk-chip:hover,.wk-chip:focus-visible{color:var(--ly-ink)!important;border-color:var(--ly-cyan)}
.wk-chip.on{color:#1a1030!important;background:linear-gradient(180deg,#9ff0ff,var(--ly-cyan));border-color:#9ff0ff}
.wk-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
@media (max-width:860px){.wk-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:560px){.wk-grid{grid-template-columns:1fr}}
.wk-item{display:flex;flex-direction:column;min-width:0;background:rgba(18,22,54,.78);border:1px solid var(--ly-line);border-radius:6px;overflow:hidden}
.wk-item:hover,.wk-item:focus-within{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.wk-card{display:flex;flex-direction:column;flex:1;text-decoration:none;color:var(--ly-ink)!important;min-width:0}
.wk-credit{margin:0;padding:8px 14px 12px;border-top:1px solid var(--ly-line);font-size:12px;color:var(--ly-dim);overflow-wrap:anywhere}
.wk-credit a{color:var(--ly-ink)}
.wk-card .noimg.link{background:linear-gradient(135deg,#0b1030,#1a0f3a)}
.wk-tag.comm{color:#ffd27a;border-color:rgba(255,210,122,.55)}
.wk-actions form{margin:0}
.wk-btn.quiet{font:600 13px/1 system-ui,sans-serif;min-height:36px;padding:8px 12px;cursor:pointer}
.wk-form{display:grid;gap:14px;max-width:560px}
.wk-form label{display:grid;gap:6px;font-weight:600}
.wk-form .hint{font-weight:400;font-size:13px;color:var(--ly-dim)}
.wk-form fieldset{border:1px solid var(--ly-line);border-radius:6px;padding:10px 12px;display:flex;flex-wrap:wrap;gap:12px}
.wk-form fieldset label{display:flex;gap:6px;align-items:center;font-weight:400}
.wk-form legend{font-weight:600;padding:0 4px}
.wk-form input[type=url],.wk-form input[type=text],.wk-form select{font:15px/1.3 system-ui,sans-serif;color:var(--ly-ink);
background:#0b0f2a;border:1px solid var(--ly-line);border-radius:6px;padding:10px 12px;min-height:44px;max-width:100%}
.wk-form button.wk-btn{cursor:pointer}
.wk-msg{padding:10px 14px;border-radius:6px;border:1px solid rgba(255,140,140,.6);color:#ffc0c0;margin:0 0 14px}
.wk-msg.ok{border-color:rgba(94,240,160,.55);color:#9ff5c4}
.wk-thanks{columns:2 260px;column-gap:24px;padding:0;list-style:none}
.wk-thanks li{break-inside:avoid;margin:0 0 14px}
.wk-thanks b{color:var(--ly-cyan)}
.wk-thanks span{display:block;font-size:13px;color:var(--ly-dim)}
.wk-card img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;background:#070918}
.wk-card .noimg{aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;background:#070918;color:var(--ly-dim);
font:600 28px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.1em;text-transform:uppercase}
.wk-card .body{padding:12px 14px 10px;display:flex;flex-direction:column;gap:6px}
.wk-card h3{margin:0;font:600 21px/1.15 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--ly-cyan);overflow-wrap:anywhere}
.wk-card p{margin:0;font-size:14px;overflow-wrap:anywhere}
.wk-tags{display:flex;flex-wrap:wrap;gap:5px}
.wk-tag{font:600 10px/1 system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--ly-violet);
border:1px solid rgba(180,140,255,.5);border-radius:999px;padding:4px 7px}
.wk-tag.kind{color:var(--ly-cyan);border-color:rgba(95,227,255,.5)}
.wk-tag.live{color:#5ef0a0;border-color:rgba(94,240,160,.55)}
.wk-ver{font-size:12px;color:var(--ly-dim)}
.wk-empty{text-align:center;color:var(--ly-dim)}
.wk-detail{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:20px;align-items:start}
@media (max-width:760px){.wk-detail{grid-template-columns:1fr}}
.wk-shots img{display:block;width:100%;height:auto;border:1px solid var(--ly-line);border-radius:6px;margin:0 0 10px;background:#070918}
.wk-facts{margin:0;display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:14px}
.wk-facts dt{color:var(--ly-dim)}.wk-facts dd{margin:0;overflow-wrap:anywhere}
.wk-perms{margin:8px 0 0;padding-left:1.2rem}.wk-perms li{margin:6px 0}
.wk-perms b{color:var(--ly-cyan)}
.wk-live{display:inline-block;margin:6px 0 4px;padding:6px 12px;border:1px solid rgba(94,240,160,.55);border-radius:999px;color:#5ef0a0;font-weight:600}
.wk-actions{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 6px}
.wk-btn{display:inline-flex;align-items:center;min-height:44px;padding:10px 16px;text-decoration:none;color:var(--ly-ink)!important;
font:600 17px/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.1em;text-transform:uppercase;
background:linear-gradient(180deg,rgba(40,52,110,.92),rgba(16,20,52,.95));border:1px solid rgba(140,170,255,.45);border-radius:6px}
.wk-btn:hover,.wk-btn:focus-visible{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.wk-btn.violet{background:linear-gradient(180deg,rgba(90,52,160,.92),rgba(36,18,80,.95));border-color:rgba(190,150,255,.55)}
.wk-sum{font:12px/1.4 ui-monospace,monospace;color:var(--ly-dim);overflow-wrap:anywhere}
.wk-lede{max-width:640px;margin:0 auto 18px;text-align:center}
.ly .wk-h1{font-size:clamp(44px,8vw,76px)}
.wk-cats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
@media (max-width:860px){.wk-cats{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:620px){.wk-cats{grid-template-columns:repeat(2,minmax(0,1fr))}}
.wk-cat{display:flex;gap:10px;align-items:center;min-width:0;min-height:56px;padding:10px 12px;text-decoration:none;color:var(--ly-ink)!important;
background:rgba(18,22,54,.78);border:1px solid var(--ly-line);border-radius:6px}
.wk-cat:hover,.wk-cat:focus-visible{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.wk-cat.on{border-color:var(--ly-cyan);background:rgba(30,60,110,.7)}
.wk-cat.zero{opacity:.62}.wk-cat.zero:hover,.wk-cat.zero:focus-visible{opacity:1}
.wk-ico{flex:none;width:30px;height:30px;display:flex;align-items:center;justify-content:center;color:var(--ly-cyan);
font:600 16px/1 'Leyline Display','OW Cinzel',Impact,sans-serif}
.wk-ico svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.wk-cat .nm{flex:1;min-width:0;font:600 13px/1.25 system-ui,sans-serif;letter-spacing:.04em;overflow-wrap:anywhere}
.wk-cat .n{flex:none;font:600 12px/1 system-ui,sans-serif;color:var(--ly-dim);padding:4px 7px;border:1px solid var(--ly-line);border-radius:999px}
.wk-cat:not(.zero) .n{color:#1a1030;background:var(--ly-cyan);border-color:var(--ly-cyan)}
.wk-search{display:flex;gap:8px;justify-content:center;margin:0 0 14px}
.wk-search input{flex:1;max-width:420px;min-height:40px;padding:8px 12px;font:15px system-ui,sans-serif;color:var(--ly-ink);
background:rgba(7,9,24,.85);border:1px solid var(--ly-line);border-radius:6px}
.wk-search input:focus{outline:2px solid var(--ly-cyan);outline-offset:1px}
.wk-search button{min-height:40px;padding:8px 14px;font:600 12px/1 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;
color:#1a1030;background:linear-gradient(180deg,#9ff0ff,var(--ly-cyan));border:1px solid #9ff0ff;border-radius:6px;cursor:pointer}
.wk-tag.cat{color:#ffd98a;border-color:rgba(255,217,138,.5)}
.wk-first{max-width:560px;margin:4px auto 0;text-align:center;padding:18px;border:1px dashed rgba(140,170,255,.5);border-radius:6px;background:rgba(7,9,24,.55)}
.wk-first h3{margin:0 0 6px;font:600 20px/1.15 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--ly-cyan)}
.wk-first .wk-actions{justify-content:center}
"""


def match(path: str) -> bool:
    """True for every path the Workshop owns (/wrath/mods and below), valid or not."""
    return path == "/wrath/mods" or (path or "").startswith("/wrath/mods/")


def _clean(m) -> dict | None:
    """One catalog entry with every field checked, or None."""
    if not isinstance(m, dict):
        return None
    mid = m.get("id")
    if not isinstance(mid, str) or not (3 <= len(mid) <= 32) or not ID_RE.fullmatch(mid) or mid in RESERVED_IDS:
        return None
    ver = m.get("version")
    if not isinstance(ver, str) or not VERSION_RE.fullmatch(ver):
        return None
    kind = m.get("kind") if m.get("kind") in KINDS else None
    if not kind:
        return None

    def text(k, n):
        v = m.get(k)
        return v.strip()[:n] if isinstance(v, str) else ""

    perms = [p for p in (m.get("permissions") or []) if isinstance(p, str) and p in PERMISSIONS] \
        if isinstance(m.get("permissions"), list) else []
    shots = []
    for s in m.get("screenshots") or [] if isinstance(m.get("screenshots"), list) else []:
        b = os.path.basename(s) if isinstance(s, str) else ""
        if SHOT_RE.fullmatch(b):
            shots.append(b)
    addons = [a for a in (m.get("addons") or []) if isinstance(a, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", a)] \
        if isinstance(m.get("addons"), list) else []
    zname = m.get("zip")
    if zname != f"{mid}-{ver}.zip":
        zname = None
    sha = m.get("sha256") if isinstance(m.get("sha256"), str) and SHA_RE.fullmatch(m.get("sha256")) else ""
    size = m.get("size") if isinstance(m.get("size"), int) and m.get("size") >= 0 else None
    cat = m.get("category") if isinstance(m.get("category"), str) and len(m.get("category")) <= 32 \
        and ID_RE.fullmatch(m.get("category")) else ""
    repo = ""
    for ln in m.get("links") or [] if isinstance(m.get("links"), list) else []:
        repo = _https_link(ln.get("url") if isinstance(ln, dict) else ln)
        if repo:
            break
    return {"id": mid, "category": cat, "version": ver, "kind": kind, "name": text("name", 48) or mid,
            "author": text("author", 80), "licence": text("licence", 80), "description": text("description", 300),
            "permissions": sorted(set(perms), key=PERMISSIONS.index), "screenshots": shots[:8],
            "addons": addons[:8], "zip": zname, "sha256": sha, "size": size,
            "repo": repo or REPO_BASE + mid, "builds": ["3.3.5a"]}


def _https_link(v) -> str:
    """v when it is a plain https URL with a normal host name, else ''."""
    if not isinstance(v, str) or len(v) > 300 or not v.startswith("https://") or re.search(r"[\s\x00-\x1f\x7f]", v):
        return ""
    try:
        host = urllib.parse.urlsplit(v).hostname or ""
    except ValueError:
        return ""
    return v if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,63}", host.lower()) else ""


def _short_url(u: str) -> str:
    """The site a link goes to (github.com), for a credit line. Only the site: a path is someone else's
    naming, and the link itself carries it."""
    try:
        h = (urllib.parse.urlsplit(u).hostname or "").lower()
    except ValueError:
        h = ""
    return re.sub(r"^www\.", "", h) or "link"


class Workshop:
    def __init__(self, mods_dir: str = MODS_DIR, css=None, card_meta=None, realm_name: str = "WrathUnleashed",
                 projects=None):
        self.dir = mods_dir
        self.css = css or (lambda: "")
        self.card_meta = card_meta or (lambda path, title="": "")
        self.realm_name = realm_name
        self._cache = {"key": None, "mods": [], "installed": {}}
        self._cats = {"key": None, "list": [], "defaults": {}}
        self._lock = threading.Lock()
        if projects is None and projects_mod is not None:
            try:   # its category choices are always this Workshop's categories.json
                projects = projects_mod.Projects(categories=lambda: [c["id"] for c in self.categories()[0]])
            except Exception:   # noqa: BLE001
                projects = None
        self.projects = projects
        self._secret = os.environ.get("WU_FORM_SECRET", "").encode() or secrets.token_bytes(32)
        # The Admin Console's overrides (stream/admin.py adjust_catalog, set by the portal): None = as published.
        self.adjust = None
        self._who_cache: dict[str, tuple[float, object]] = {}

    # ---------------------------------------------------------------- data
    def _stat(self, name):
        try:
            st = os.stat(os.path.join(self.dir, name))
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _read_json(self, name, limit=4_000_000):
        try:
            with open(os.path.join(self.dir, name), "rb") as f:
                return json.loads(f.read(limit).decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None

    def _categories_path(self) -> str:
        own = os.path.join(self.dir, "categories.json")
        return own if os.path.isfile(own) or not os.path.isfile(CATEGORIES_FALLBACK) else CATEGORIES_FALLBACK

    def categories(self) -> tuple[list[dict], dict]:
        """([{id, name, line, icon}] in order, {kind: default id}) from categories.json; ([], {}) if unreadable."""
        path = self._categories_path()
        try:
            st = os.stat(path)
            key = (path, st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        with self._lock:
            if self._cats["key"] == key and key is not None:
                return self._cats["list"], self._cats["defaults"]
        doc = None
        if key is not None:
            try:
                with open(path, "rb") as f:
                    doc = json.loads(f.read(200_000).decode("utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                doc = None
        cats, seen = [], set()
        for c in (doc.get("categories") if isinstance(doc, dict) and isinstance(doc.get("categories"), list) else [])[:40]:
            if not isinstance(c, dict):
                continue
            cid = c.get("id")
            if not isinstance(cid, str) or not (2 <= len(cid) <= 32) or not ID_RE.fullmatch(cid) or cid in seen:
                continue
            name = c.get("name").strip()[:48] if isinstance(c.get("name"), str) and c.get("name").strip() else cid
            line = c.get("line").strip()[:200] if isinstance(c.get("line"), str) else ""
            icon = c.get("icon") if c.get("icon") in ICONS else ""
            seen.add(cid)
            cats.append({"id": cid, "name": name, "line": line, "icon": icon})
        kd = doc.get("kind_defaults") if isinstance(doc, dict) and isinstance(doc.get("kind_defaults"), dict) else {}
        defaults = {k: v for k, v in kd.items() if k in KINDS and v in seen}
        with self._lock:
            self._cats = {"key": key, "list": cats, "defaults": defaults}
        return cats, defaults

    def category(self, cat_id: str) -> dict | None:
        return next((c for c in self.categories()[0] if c["id"] == cat_id), None)

    def load(self, raw: bool = False) -> tuple[list[dict], dict]:
        """(mods, {id: installed version}), reread only when the files change. Each mod's "category" is a
        known category id (its own, else the default for its kind) or "" when there is no category list.
        Staff overrides (self.adjust) are applied unless raw."""
        mods, installed = self._load()
        return (mods if raw or self.adjust is None else self.adjust("mods", mods, "id")), installed

    def _load(self) -> tuple[list[dict], dict]:
        cats, defaults = self.categories()
        key = (self._stat("catalog.json"), self._stat("installed.json"), self._cats["key"])
        with self._lock:
            if self._cache["key"] == key:
                return self._cache["mods"], self._cache["installed"]
        cat = self._read_json("catalog.json")
        mods, seen = [], set()
        for m in (cat.get("mods") if isinstance(cat, dict) and isinstance(cat.get("mods"), list) else [])[:MAX_MODS]:
            c = _clean(m)
            if c and c["id"] not in seen:
                seen.add(c["id"])
                known = {x["id"] for x in cats}
                c["category"] = c["category"] if c["category"] in known else defaults.get(c["kind"], "")
                mods.append(c)
        mods.sort(key=lambda m: m["name"].lower())
        inst = self._read_json("installed.json")
        installed = {}
        if isinstance(inst, dict) and isinstance(inst.get("installed"), dict):
            installed = {k: v for k, v in inst["installed"].items()
                         if isinstance(k, str) and ID_RE.fullmatch(k) and isinstance(v, str) and VERSION_RE.fullmatch(v)}
        with self._lock:
            self._cache = {"key": key, "mods": mods, "installed": installed}
        return mods, installed

    def mod(self, mod_id: str) -> dict | None:
        """The catalog entry for mod_id, or None. Never raises (the share links call it)."""
        try:
            for m in self.load()[0]:
                if m["id"] == mod_id:
                    return m
        except Exception:
            pass
        return None

    def on_wrath(self, m: dict) -> bool:
        return self.load()[1].get(m["id"]) == m["version"]

    # ---------------------------------------------------------------- pages
    def _page(self, title: str, path: str, card_title: str, body: str, desc: str = "") -> bytes:
        e = html.escape
        meta = self.card_meta(path, card_title)
        if desc:
            d = e(desc)
            meta = re.sub(r'((?:name="description"|property="og:description"|name="twitter:description") content=")[^"]*(")',
                          lambda mm: mm.group(1) + d + mm.group(2), meta)
        nav = ('<nav class="ly-nav" aria-label="Leyline"><div class="grp">'
               '<a href="/wrath/leyline">Hub</a><a href="/wrath/realms">Realms</a><a href="/wrath/mods">Mods</a></div>'
               '<div class="grp"><a href="/login?next=%2Fwrath">Sign in</a><a class="hot" href="/wrath">Play now</a></div></nav>')
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
                f'<title>{e(title)}</title>{meta}<style>{self.css()}{WORKSHOP_CSS}</style></head>'
                f'<body class="ly"><div class="ly-glow"></div>{nav}<div class="ly-wrap">{body}</div></body></html>').encode("utf-8")

    # ---------------------------------------------------------------- community projects, one list
    def community(self) -> list[dict]:
        """The visible community projects, each checked again for what the pages need. Never raises."""
        if self.projects is None:
            return []
        try:
            recs = self.projects.visible()
            self.projects.maybe_refresh()
        except Exception:   # noqa: BLE001
            return []
        known = {c["id"] for c in self.categories()[0]}
        out = []
        for r in recs:
            url = _https_link(r.get("url"))
            if not url:
                continue

            def t(k, n=120):
                v = r.get(k)
                return v.strip()[:n] if isinstance(v, str) else ""
            builds = [b for b in r.get("builds") or [] if b in ("3.3.5a", "1.12", "any")] \
                if isinstance(r.get("builds"), list) else []
            stars = r.get("stars") if isinstance(r.get("stars"), int) and not isinstance(r.get("stars"), bool) else None
            out.append({"pid": r["id"], "url": url, "host": t("host", 80), "name": t("title", 80) or t("host", 80),
                        "author": t("author", 60), "author_url": _https_link(r.get("author_url")),
                        "licence": t("licence", 60), "description": t("description", 160),
                        "repo_description": t("repo_description", 300),
                        "category": r.get("category") if r.get("category") in known else "",
                        "builds": builds or ["any"], "stars": stars, "last_push": t("last_push", 25),
                        "submitted_by": t("submitted_by", 40), "submitted_at": t("submitted_at", 25),
                        "last_checked": t("last_checked", 25),
                        "reports": len(r["reports"]) if isinstance(r.get("reports"), list) else 0})
        return out if self.adjust is None else self.adjust("projects", out, "pid")

    def everything(self) -> list[dict]:
        """Packaged mods and community projects in one shape for the pages and all.json, sorted by name."""
        mods, installed = self.load()
        items = []
        for m in mods:
            items.append({"source": "packaged", "id": "mod:" + m["id"], "href": f"/wrath/mods/{m['id']}", "m": m,
                          "name": m["name"], "description": m["description"], "category": m["category"],
                          "builds": m["builds"], "author": m["author"], "author_url": "", "licence": m["licence"],
                          "repo": m["repo"], "on_wrath": installed.get(m["id"]) == m["version"],
                          "featured": bool(m.get("featured"))})
        for p in self.community():
            items.append({"source": "community", "id": "link:" + p["pid"], "href": f"/wrath/mods/p/{p['pid']}", "p": p,
                          "name": p["name"], "description": p["description"], "category": p["category"],
                          "builds": p["builds"], "author": p["author"], "author_url": p["author_url"],
                          "licence": p["licence"], "repo": p["url"], "on_wrath": False, "featured": bool(p.get("featured"))})
        items.sort(key=lambda x: (x["name"].lower(), x["source"]))
        return items

    # ---------------------------------------------------------------- sign-in (through the portal's /api/me)
    def _me(self, req):
        """The signed-in user's /api/me answer, None when signed out, "down" when the website did not answer."""
        if not req or "wr_session=" not in (req.get("cookie") or "") or not callable(req.get("who")):
            return None
        key = hashlib.sha256(req["cookie"].encode("utf-8", "replace")).hexdigest()
        now = time.time()
        hit = self._who_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        try:
            me = req["who"](req["cookie"], req.get("ip", ""), req.get("ua", ""))
        except Exception:   # noqa: BLE001
            return "down"
        if len(self._who_cache) > 2000:
            self._who_cache.clear()
        self._who_cache[key] = (now + 60, me)
        return me

    @staticmethod
    def _session(req) -> str:
        for part in (req or {}).get("cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "wr_session":
                return v
        return ""

    def _token(self, req, action: str) -> str:
        """A form token for this session and action (no cookie of our own, no state)."""
        return hmac.new(self._secret, (self._session(req) + "|" + action).encode(), hashlib.sha256).hexdigest()[:32]

    def _token_ok(self, req, action: str) -> bool:
        got = ((req or {}).get("form") or {}).get("t", "")
        return bool(self._session(req)) and isinstance(got, str) and hmac.compare_digest(got, self._token(req, action))

    # ---------------------------------------------------------------- the list
    @staticmethod
    def _filters(query: dict) -> tuple[str, str, str, str, str]:
        kind = (query.get("kind") or [""])[0]
        perm = (query.get("perm") or [""])[0]
        q = " ".join(str((query.get("q") or [""])[0]).split())[:MAX_QUERY]
        build = (query.get("build") or [""])[0]
        source = (query.get("source") or [""])[0]
        return ((kind if kind in KINDS else ""), (perm if perm in PERMISSIONS or perm == "none" else ""), q,
                (build if build in BUILD_FILTERS else ""), (source if source in SOURCES else ""))

    @staticmethod
    def _href(kind: str = "", perm: str = "", q: str = "", cat: str = "", build: str = "", source: str = "") -> str:
        qs = urllib.parse.urlencode([(k, v) for k, v in (("kind", kind), ("perm", perm), ("q", q), ("build", build),
                                                         ("source", source)) if v])
        return ("/wrath/mods/c/" + cat if cat else "/wrath/mods") + ("?" + qs if qs else "")

    @staticmethod
    def icon(c: dict) -> str:
        if c.get("icon") in ICONS:
            return (f'<span class="wk-ico" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false">'
                    f'{ICONS[c["icon"]]}</svg></span>')
        return f'<span class="wk-ico" aria-hidden="true">{html.escape(c["name"][:1])}</span>'

    @staticmethod
    def _matches(m: dict, q: str, cat_names: dict) -> bool:
        """Every word of q appears in the name, the description, the category (name or id) or the author."""
        hay = " ".join((m["name"], m["description"], m["category"], cat_names.get(m["category"], ""),
                        m.get("author", ""))).lower()
        return all(w in hay for w in q.lower().split())

    def _credit_html(self, it: dict) -> str:
        e = html.escape
        who = e(it["author"] or "Unknown author")
        if it.get("author_url"):
            who = f'<a href="{e(it["author_url"])}" {EXT_REL}>{who}</a>'
        lic = e(it["licence"]) if it["licence"] else "Licence not stated"
        return (f'<p class="wk-credit">Credits: {who} &middot; {lic} &middot; '
                f'<a href="{e(it["repo"])}" {EXT_REL}>{e(_short_url(it["repo"]))}</a></p>')

    @staticmethod
    def credit_text(it: dict) -> str:
        return (f'{it["name"]} by {it["author"] or "unknown author"} · {it["licence"] or "licence not stated"} · '
                f'{_short_url(it["repo"])}')

    def _card(self, it: dict, installed: dict, cat_names: dict, cid: str) -> str:
        e = html.escape
        builds = " · ".join("Any build" if b == "any" else b for b in it["builds"])
        tags = []
        if it["category"] in cat_names and not cid:
            tags.append(f'<span class="wk-tag cat">{e(cat_names[it["category"]])}</span>')
        if it["source"] == "packaged":
            m = it["m"]
            img = (f'<img src="/wrath/mods/{e(m["id"])}/shot/0" alt="" loading="lazy" width="640" height="360">'
                   if m["screenshots"] else f'<div class="noimg" aria-hidden="true">{e(m["name"][:1])}</div>')
            tags.append(f'<span class="wk-tag kind">{e(KIND_LABEL[m["kind"]])}</span>')
            if installed.get(m["id"]) == m["version"]:
                tags.append('<span class="wk-tag live">On Wrath</span>')
            tags += [f'<span class="wk-tag">{e(PERM_LABEL[p])}</span>' for p in m["permissions"]]
            line = f'v{e(m["version"])}{" · " + e(m["author"]) if m["author"] else ""}'
        else:
            p = it["p"]
            img = f'<div class="noimg link" aria-hidden="true">{e(it["name"][:1])}</div>'
            tags.append('<span class="wk-tag comm">Community link</span>')
            line = f'{e(p["host"])} · {e(builds)}' + (f' · &#9733; {p["stars"]}' if p["stars"] is not None else "")
        return (f'<div class="wk-item"><a class="wk-card" href="{e(it["href"])}">{img}<div class="body">'
                f'<h3>{e(it["name"])}</h3><span class="wk-ver">{line}</span>'
                f'<p>{e(it["description"])}</p><div class="wk-tags">{"".join(tags)}</div></div></a>'
                f'{self._credit_html(it)}</div>')

    def list_page(self, query: dict, cat: dict | None = None) -> bytes:
        e = html.escape
        mods, installed = self.load()
        cats, _ = self.categories()
        cat_names = {c["id"]: c["name"] for c in cats}
        kind, perm, q, build, source = self._filters(query)
        cid = cat["id"] if cat else ""
        items = self.everything()
        in_cat = [it for it in items if not cid or it["category"] == cid]

        def keep(it):
            if build and build not in it["builds"] and "any" not in it["builds"]:
                return False
            if source and it["source"] != source:
                return False
            if kind or perm:   # mod kinds and realm permissions are packaged-mod facts
                if it["source"] != "packaged":
                    return False
                m = it["m"]
                if kind and m["kind"] != kind:
                    return False
                if perm and not ((perm == "none" and not m["permissions"]) or perm in m["permissions"]):
                    return False
            return not q or self._matches(it, q, cat_names)
        shown = [it for it in in_cat if keep(it)]

        def chip(label, on, **change):
            f = dict(kind=kind, perm=perm, q=q, cat=cid, build=build, source=source)
            f.update(change)
            return f'<a class="wk-chip{" on" if on else ""}" href="{e(self._href(**f))}">{e(label)}</a>'
        kinds = chip("All", not kind, kind="") + "".join(chip(KIND_LABEL[k], kind == k, kind=k) for k in KINDS)
        perms = chip("Any", not perm, perm="") + chip("None", perm == "none", perm="none") \
            + "".join(chip(PERM_LABEL[p], perm == p, perm=p) for p in PERMISSIONS)
        builds = chip("Any", not build, build="") + "".join(chip(b, build == b, build=b) for b in BUILD_FILTERS)
        sources = chip("All", not source, source="") + "".join(chip(SOURCE_LABEL[s], source == s, source=s) for s in SOURCES)

        counts = {c["id"]: 0 for c in cats}
        for it in items:
            if it["category"] in counts:
                counts[it["category"]] += 1
        cat_grid = ""
        if cats:
            tiles = []
            for c in cats:
                n = counts[c["id"]]
                cls = "wk-cat" + (" on" if c["id"] == cid else "") + ("" if n else " zero")
                cur = ' aria-current="page"' if c["id"] == cid else ""
                tiles.append(f'<a class="{cls}" href="/wrath/mods/c/{e(c["id"])}" title="{e(c["line"])}"{cur}>'
                             f'{self.icon(c)}<span class="nm">{e(c["name"])}</span>'
                             f'<span class="n" aria-label="{n} project{"" if n == 1 else "s"}">{n}</span></a>')
            cat_grid = ('<section class="ly-panel" aria-labelledby="wk-cats"><h2 id="wk-cats">Categories</h2>'
                        f'<nav class="wk-cats" aria-label="Categories">{"".join(tiles)}</nav></section>')

        cards = [self._card(it, installed, cat_names, cid) for it in shown]
        here = self._href(cat=cid)
        if cards:
            grid = f'<div class="wk-grid">{"".join(cards)}</div>'
        elif cat and not in_cat:
            grid = ('<div class="wk-first"><h3>Publish the first one</h3>'
                    f'<p>Nothing in {e(cat["name"])} yet. Make a mod in the open format, check it with wu-mod.py '
                    'and send it in: it shows up here once it is on the realm. Or add a link to your own project.</p>'
                    f'<div class="wk-actions"><a class="wk-btn violet" href="{GUIDE_URL}" rel="noopener noreferrer">'
                    'Read the modder guide</a><a class="wk-btn" href="/wrath/mods/submit">Add your project</a></div></div>')
        elif in_cat:
            grid = f'<p class="wk-empty">No mods match these filters. <a href="{e(here)}">Show all</a></p>'
        else:
            grid = '<p class="wk-empty">The Workshop is empty right now. Mods appear here once they are on the realm.</p>'

        search = (f'<form class="wk-search" method="get" action="{e(here)}" role="search">'
                  + "".join(f'<input type="hidden" name="{k}" value="{e(v)}">'
                            for k, v in (("kind", kind), ("perm", perm), ("build", build), ("source", source)) if v)
                  + f'<input type="search" name="q" value="{e(q)}" maxlength="{MAX_QUERY}" '
                  'placeholder="Search names, descriptions, categories" aria-label="Search mods">'
                  '<button type="submit">Search</button></form>')
        filters = (search
                   + f'<div class="wk-bar" role="group" aria-label="Source"><span class="lbl">Source</span>{sources}</div>'
                   + f'<div class="wk-bar" role="group" aria-label="Build"><span class="lbl">Build</span>{builds}</div>'
                   + f'<div class="wk-bar" role="group" aria-label="Kind"><span class="lbl">Kind</span>{kinds}</div>'
                   + f'<div class="wk-bar" role="group" aria-label="Permissions"><span class="lbl">Permissions</span>{perms}</div>')
        fine = ('<p class="ly-fine">In the game: Esc &rarr; Mods &amp; Workshop turns the addons on and off. '
                f'Make your own: <a href="{GUIDE_URL}" rel="noopener noreferrer">the modder guide</a> and '
                '<a href="https://github.com/orionopenwow/Leyline/blob/main/mods/SPEC.md" '
                'rel="noopener noreferrer">the mod format and a template</a>. '
                '<a href="/wrath/mods/credits">Credits</a> thanks every author; tools read '
                '<a href="/wrath/mods/all.json">all.json</a>.</p>')
        add = ('<p class="wk-actions" style="justify-content:center"><a class="wk-btn violet" href="/wrath/mods/submit">'
               'Add your project</a><a class="wk-btn" href="/wrath/mods/credits">Credits</a></p>')
        if cat:
            n = len(in_cat)
            body = (
                '<p><a href="/wrath/mods">&larr; All categories</a></p>'
                f'<header class="ly-hero"><h1 class="wk-h1">{e(cat["name"])}</h1>'
                f'<p class="wk-lede">{e(cat["line"])} {n} mod{"" if n == 1 else "s"} here.</p></header>'
                '<section class="ly-panel" aria-labelledby="wk-mods"><h2 id="wk-mods">Mods</h2>'
                + (filters if in_cat else "") + f'{grid}</section>{cat_grid}{fine}')
            return self._page(f"{cat['name']} · Workshop", f"/wrath/mods/c/{cat['id']}",
                              f"{cat['name']} · Leyline Workshop", body,
                              cat["line"] or "Community mods for Wrath on the Leyline network.")
        n_live = sum(1 for m in mods if installed.get(m["id"]) == m["version"])
        n_comm = sum(1 for it in items if it["source"] == "community")
        body = (
            '<header class="ly-hero"><h1 class="wk-h1">Workshop</h1>'
            '<p class="wk-lede">The whole Leyline catalog for Wrath: addons, graphics, game modes, maps, builds, '
            'encounters, models, realm scripts, presets, sounds, tools and total conversions, in one open format, '
            'plus community projects, credited to the people who made them. '
            f'{n_live} of {len(mods)} are on {e(self.realm_name)} now; {n_comm} community '
            f'link{"" if n_comm == 1 else "s"}.</p>{add}</header>'
            f'{cat_grid}'
            '<section class="ly-panel" aria-labelledby="wk-mods"><h2 id="wk-mods">Mods</h2>'
            f'{filters}{grid}</section>{fine}')
        return self._page(f"Workshop · {self.realm_name}", "/wrath/mods", f"Workshop · {self.realm_name}", body,
                          "Community mods for Wrath on the Leyline network: addons, game modes, maps, realm scripts "
                          "and more, free, open and credited.")

    def detail_page(self, m: dict) -> bytes:
        e = html.escape
        live = self.on_wrath(m)
        shots = "".join(f'<img src="/wrath/mods/{e(m["id"])}/shot/{i}" alt="{e(m["name"])} screenshot {i + 1}" '
                        f'width="640" height="360">' for i in range(len(m["screenshots"])))
        if m["kind"] == "ui":
            perm_html = '<p>None on the realm. It is an addon only: it runs in your own game.</p>'
        elif m["permissions"]:
            perm_html = '<ul class="wk-perms">' + "".join(
                f'<li><b>{e(PERM_LABEL[p])}.</b> {e(PERM_WORDS[p])}</li>' for p in m["permissions"]) + '</ul>'
        else:
            perm_html = '<p>None: its realm scripts use nothing beyond their own code.</p>'
        addons = ""
        if m["addons"]:
            addons = (f'<p>Adds the addon{"s" if len(m["addons"]) > 1 else ""} {e(", ".join(m["addons"]))}. '
                      'Turn it on or off in the game: Esc &rarr; Mods &amp; Workshop.</p>')
        size = f" ({m['size'] / 1024:.0f} KB)" if m["size"] else ""
        download = (f'<a class="wk-btn" href="/wrath/mods/{e(m["id"])}/download" download>Download zip{size}</a>'
                    if m["zip"] else "")
        status = (f'<span class="wk-live">Already on Wrath</span>' if live else
                  '<p class="ly-fine" style="text-align:left">Not on Wrath yet: it reaches the realm after review.</p>')
        facts = [("Version", m["version"]), ("Author", m["author"]), ("Licence", m["licence"]),
                 ("Kind", KIND_LABEL[m["kind"]])]
        c = self.category(m["category"]) if m["category"] else None
        cat_dd = (f'<dt>Category</dt><dd><a href="/wrath/mods/c/{e(c["id"])}">{e(c["name"])}</a></dd>' if c else "")
        body = (
            f'<p><a href="/wrath/mods">&larr; All mods</a></p>'
            f'<section class="ly-panel" aria-labelledby="wk-name"><h2 id="wk-name">{e(m["name"])}</h2>'
            f'<div class="wk-detail"><div class="wk-shots">{shots or ""}'
            f'<p>{e(m["description"])}</p><p>{e(KIND_WORDS[m["kind"]])}</p>{addons}</div>'
            f'<div>{status}<dl class="wk-facts">'
            + "".join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in facts if v) + cat_dd
            + f'<dt>Builds</dt><dd>{e(", ".join(m["builds"]))}</dd>'
            f'<dt>Repo</dt><dd><a href="{e(m["repo"])}" {EXT_REL}>{e(_short_url(m["repo"]))}</a></dd>'
            + '</dl><h3 class="wk-sub">What it can do on the realm</h3>' + perm_html
            + f'<div class="wk-actions">{download}'
            f'<a class="wk-btn violet" href="/wrath/m/{e(m["id"])}">Share link</a>'
            f'<a class="wk-btn" href="/wrath?go=m:{e(m["id"])}">Play</a></div>'
            + (f'<p class="wk-sum">sha256 {e(m["sha256"])}</p>' if m["sha256"] and m["zip"] else "")
            + f'<p class="ly-fine" style="text-align:left">Share: <a href="/wrath/m/{e(m["id"])}">'
            f'play.openvanilla.app/wrath/m/{e(m["id"])}</a></p></div></div>'
            + self._credit_html({"author": m["author"], "author_url": "", "licence": m["licence"], "repo": m["repo"]})
            + '</section>')
        return self._page(f"{m['name']} · Workshop", f"/wrath/mods/{m['id']}", f"Mod: {m['name']} · Leyline", body,
                          m["description"] or "A community mod for Wrath on the Leyline network.")

    def project_page(self, pid: str, req=None, note: str = "", status: int = 200) -> tuple[int, bytes]:
        e = html.escape
        me = self._me(req)
        admin = isinstance(me, dict) and self.projects is not None and self.projects.is_admin(me)
        p = next((x for x in self.community() if x["pid"] == pid), None)
        hidden = False
        if p is None and admin:
            rec = self.projects.get(pid)
            if rec and rec.get("hidden"):
                hidden = True
                known = {c["id"] for c in self.categories()[0]}
                p = {"pid": pid, "url": _https_link(rec.get("url")) or "https://invalid.example/",
                     "host": str(rec.get("host", ""))[:80], "name": str(rec.get("title", ""))[:80] or "Hidden link",
                     "author": str(rec.get("author", ""))[:60], "author_url": _https_link(rec.get("author_url")),
                     "licence": str(rec.get("licence", ""))[:60], "description": str(rec.get("description", ""))[:160],
                     "repo_description": "", "category": rec.get("category") if rec.get("category") in known else "",
                     "builds": ["any"], "stars": None, "last_push": "", "submitted_by": str(rec.get("submitted_by", ""))[:40],
                     "submitted_at": str(rec.get("submitted_at", ""))[:25], "last_checked": "",
                     "reports": len(rec.get("reports") or [])}
        if p is None:
            return 404, self.not_found("Project not found", "No project by that link is in the Workshop.")
        builds = ", ".join("Any build" if b == "any" else b for b in p["builds"])
        author = e(p["author"] or "Unknown")
        if p["author_url"]:
            author = f'<a href="{e(p["author_url"])}" {EXT_REL}>{author}</a>'
        c = self.category(p["category"]) if p["category"] else None
        facts = [("Author", author),
                 ("Licence", e(p["licence"]) if p["licence"] else "Not stated: ask the author before you reuse it"),
                 ("Category", f'<a href="/wrath/mods/c/{e(c["id"])}">{e(c["name"])}</a>' if c else ""),
                 ("Builds", e(builds)), ("Stars", str(p["stars"]) if p["stars"] is not None else ""),
                 ("Last update", e(p["last_push"][:10])), ("Added by", e(p["submitted_by"])),
                 ("Added", e(p["submitted_at"][:10])), ("Checked", e(p["last_checked"][:10]))]
        if admin:
            facts.append(("Reports", str(p["reports"])))
        actions = f'<a class="wk-btn violet" href="{e(p["url"])}" {EXT_REL}>Open the project</a>'
        if isinstance(me, dict) and me and not hidden:
            actions += (f'<form method="post" action="/wrath/mods/p/{pid}/report">'
                        f'<input type="hidden" name="t" value="{self._token(req, "report:" + pid)}">'
                        '<button class="wk-btn quiet" type="submit">Report</button></form>')
        elif not hidden:
            actions += (f'<a class="wk-btn quiet" href="/login?next={urllib.parse.quote("/wrath/mods/p/" + pid, safe="")}">'
                        'Sign in to report</a>')
        if admin:
            act = "unhide" if hidden else "hide"
            actions += (f'<form method="post" action="/wrath/mods/p/{pid}/{act}">'
                        f'<input type="hidden" name="t" value="{self._token(req, act + ":" + pid)}">'
                        f'<button class="wk-btn quiet" type="submit">{"Show again" if hidden else "Hide"}</button></form>')
        msg = f'<p class="wk-msg ok" role="status">{e(note)}</p>' if note else ""
        if hidden:
            msg += '<p class="wk-msg" role="status">Hidden: only admins see this page.</p>'
        it = {"author": p["author"], "author_url": p["author_url"], "licence": p["licence"], "repo": p["url"]}
        body = (
            '<p><a href="/wrath/mods">&larr; All mods</a></p>'
            f'<section class="ly-panel" aria-labelledby="wk-name"><h2 id="wk-name">{e(p["name"])}</h2>{msg}'
            f'<div class="wk-detail"><div><p>{e(p["description"])}</p>'
            + (f'<p class="ly-fine" style="text-align:left">From the repo: {e(p["repo_description"])}</p>'
               if p["repo_description"] else "")
            + f'<p class="ly-fine" style="text-align:left">A community project, linked from the Workshop. '
            f'Nothing is hosted here: the link goes to {e(p["host"])}, where its author keeps it.</p></div>'
            '<div><dl class="wk-facts">' + "".join(f'<dt>{e(k)}</dt><dd>{v}</dd>' for k, v in facts if v)
            + f'</dl><div class="wk-actions">{actions}</div></div></div>{self._credit_html(it)}</section>')
        return status, self._page(f"{p['name']} · Workshop", f"/wrath/mods/p/{pid}", f"Project: {p['name']} · Leyline",
                                  body, p["description"] or "A community project on the Leyline network.")

    def submit_page(self, req=None, error: str = "", form=None, status: int = 200, note: str = "") -> tuple[int, bytes]:
        e = html.escape
        me = self._me(req)
        form = form or {}
        if me == "down":
            inner = '<p class="wk-msg" role="alert">The website isn\'t answering right now. Please try again shortly.</p>'
            status = 503
        elif not isinstance(me, dict) or not me:
            inner = ('<p>Sign in with your Hero Key (or Google) to add a link. Each link shows its author, licence and '
                     'repo, and most list straight away.</p><p class="wk-actions"><a class="wk-btn violet" '
                     'href="/login?next=%2Fwrath%2Fmods%2Fsubmit">Sign in to add a link</a></p>')
        elif self.projects is None or not self.projects.writable():
            inner = '<p class="wk-msg" role="alert">Adding links is closed right now. Please try again later.</p>'
        else:
            cats = "".join(f'<option value="{e(c["id"])}"{" selected" if form.get("category") == c["id"] else ""}>'
                           f'{e(c["name"])}</option>' for c in self.categories()[0])
            pick = form.get("builds") or "3.3.5a"
            builds = "".join(f'<label><input type="radio" name="builds" value="{v}"{" checked" if pick == v else ""}> {lbl}</label>'
                             for v, lbl in (("3.3.5a", "3.3.5a"), ("1.12", "1.12"), ("both", "Both"), ("any", "Any build")))
            err = (f'<p class="wk-msg" role="alert">{e(error)}</p>' if error else
                   f'<p class="wk-msg" role="status">{e(note)}</p>' if note else "")
            inner = (
                f'{err}<form class="wk-form" method="post" action="/wrath/mods/submit">'
                f'<input type="hidden" name="t" value="{self._token(req, "submit")}">'
                '<label>Project link <span class="hint">A public repo on GitHub, GitLab or Codeberg, or the project\'s '
                'page (https only). We read the repo\'s name, author and licence from it.</span>'
                f'<input type="url" name="url" required maxlength="300" placeholder="https://github.com/you/your-project" '
                f'value="{e(form.get("url", ""))}"></label>'
                f'<label>Category<select name="category" required><option value="">Pick one</option>{cats}</select></label>'
                f'<fieldset><legend>Client builds</legend>{builds}</fieldset>'
                '<label>One-line description <span class="hint">What it does, in up to 140 characters.</span>'
                f'<input type="text" name="description" required minlength="10" maxlength="140" '
                f'value="{e(form.get("description", ""))}"></label>'
                '<p class="ly-fine" style="text-align:left;margin:0">Most links list straight away, credited to the author; one with no open licence, or that looks like a cheat or leaked material, waits for a person first. '
                'Links only: nothing is uploaded or hosted here. Anyone signed in can report a link.</p>'
                '<p class="wk-actions" style="margin:0"><button class="wk-btn violet" type="submit">Add the link</button></p></form>')
        body = ('<p><a href="/wrath/mods">&larr; All mods</a></p>'
                '<section class="ly-panel" aria-labelledby="wk-sub"><h2 id="wk-sub">Add your project</h2>'
                f'{inner}</section>')
        return status, self._page("Add a project · Workshop", "/wrath/mods/submit", "Add your project · Leyline Workshop",
                                  body, "Share a link to your mod, tool or server project on the Leyline Workshop.")

    def credits_page(self) -> bytes:
        e = html.escape
        by: dict[str, list[dict]] = {}
        for it in self.everything():
            by.setdefault(it["author"] or "Unknown author", []).append(it)
        rows = []
        for author in sorted(by, key=str.lower):
            its = by[author]
            url = next((i["author_url"] for i in its if i["author_url"]), "")
            name = f'<a href="{e(url)}" {EXT_REL}>{e(author)}</a>' if url else e(author)
            projs = "".join(f'<span><a href="{e(i["href"])}">{e(i["name"])}</a> &middot; '
                            f'{e(i["licence"]) if i["licence"] else "licence not stated"} &middot; '
                            f'<a href="{e(i["repo"])}" {EXT_REL}>{e(_short_url(i["repo"]))}</a></span>' for i in its)
            rows.append(f'<li><b>{name}</b>{projs}</li>')
        n = sum(len(v) for v in by.values())
        inner = (f'<ul class="wk-thanks">{"".join(rows)}</ul>' if rows
                 else '<p class="wk-empty">No projects yet. <a href="/wrath/mods/submit">Add the first one</a></p>')
        body = ('<p><a href="/wrath/mods">&larr; All mods</a></p>'
                '<header class="ly-hero"><h1 class="wk-h1">Credits</h1>'
                f'<p class="wk-lede">Thank you to every author: {len(by)} people and teams, {n} projects. '
                'Everything here is theirs, shared under the licence each one chose.</p></header>'
                f'<section class="ly-panel" aria-labelledby="wk-cr"><h2 id="wk-cr">Authors and projects</h2>{inner}</section>')
        return self._page("Credits · Workshop", "/wrath/mods/credits", "Credits · Leyline Workshop", body,
                          "Every author and project in the Leyline Workshop, thanked.")

    def all_json(self) -> bytes:
        out = []
        for it in self.everything():
            m, p = it.get("m"), it.get("p")
            out.append({
                "id": it["id"], "source": it["source"], "name": it["name"], "description": it["description"],
                "category": it["category"], "builds": it["builds"], "author": it["author"],
                "author_url": it["author_url"], "licence": it["licence"], "repo": it["repo"],
                "page": PUBLIC_BASE + it["href"], "credits": self.credit_text(it),
                "stars": p["stars"] if p else None, "last_push": p["last_push"] if p else "",
                "submitted_by": p["submitted_by"] if p else "", "submitted_at": p["submitted_at"] if p else "",
                "last_checked": p["last_checked"] if p else "",
                "version": m["version"] if m else None, "kind": m["kind"] if m else None,
                "permissions": m["permissions"] if m else None, "on_wrath": it["on_wrath"] if m else None,
                "download": (PUBLIC_BASE + f"/wrath/mods/{m['id']}/download") if m and m["zip"] else None,
                "sha256": m["sha256"] if m and m["zip"] else None,
                "featured": it["featured"],
            })
        doc = {"format": 1, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "categories": self.categories()[0], "builds": ["3.3.5a", "1.12", "any"], "projects": out}
        return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")

    # ---------------------------------------------------------------- posts
    blocked = None   # admin.blocked(activity, acct=, site=) -> refusal text; set by the portal

    def _sanctioned(self, me: dict) -> str:
        if self.blocked is None:
            return ""
        site = next((str(me.get(k)) for k in ("id", "user_id", "account_id", "username") if me.get(k)), "")[:64]
        try:
            return self.blocked("submit", site=site)
        except Exception:   # noqa: BLE001
            return ""

    def _post(self, path: str, req: dict) -> tuple[int, bytes, str, dict]:
        HTML = "text/html; charset=utf-8"
        form = req.get("form") or {}
        if path == "/wrath/mods/submit":
            me = self._me(req)
            if me == "down" or not isinstance(me, dict) or not me:
                st, body = self.submit_page(req)
                return (503 if me == "down" else 403), body, HTML, {}
            if not self._token_ok(req, "submit"):
                st, body = self.submit_page(req, "That form was out of date. Please try again.", form, 400)
                return 400, body, HTML, {}
            if self.projects is None:
                st, body = self.submit_page(req)
                return 503, body, HTML, {}
            blk = self._sanctioned(me)
            if blk:   # a site-wide sanction (Leyline HQ: the portal sets self.blocked = admin.blocked)
                st, body = self.submit_page(req, blk, form, 403)
                return 403, body, HTML, {}
            ok, res = self.projects.submit(me, form)
            if ok and isinstance(res, dict) and res.get("review"):   # the hub's rules held it: a person checks it first
                return 303, b"", "text/plain", {"Location": "/wrath/mods/submit?queued=1"}
            if ok:
                return 303, b"", "text/plain", {"Location": f"/wrath/mods/p/{res['id']}?added=1"}
            msg, _, existing = str(res).partition("|")
            rec = self.projects.get(existing) if existing else None
            if rec and not rec.get("hidden"):
                return 303, b"", "text/plain", {"Location": f"/wrath/mods/p/{existing}?dup=1"}
            st, body = self.submit_page(req, msg, form, 400)
            return 400, body, HTML, {}
        m = _PROJ_RE.fullmatch(path)
        if not m or not m.group(2) or self.projects is None:
            return 404, self.not_found(), HTML, {}
        pid, act = m.group(1), m.group(2)
        me = self._me(req)
        if me == "down":
            return 503, self.not_found("Try again shortly", "The website isn't answering right now."), HTML, {}
        if not isinstance(me, dict) or not me or not self._token_ok(req, f"{act}:{pid}"):
            st, body = self.project_page(pid, req, "", 403)
            return st, body, HTML, {}
        if act == "report":
            ok, msg = self.projects.report(pid, me)
        else:
            ok, msg = self.projects.set_hidden(pid, me, act == "hide")
        if ok:
            return 303, b"", "text/plain", {"Location": f"/wrath/mods/p/{pid}?done={act}"}
        st, body = self.project_page(pid, req, "", 403)
        if st == 404:
            return 404, body, HTML, {}
        return 403, body.replace(b'<div class="wk-detail">', ('<p class="wk-msg" role="alert">' + html.escape(msg)
                                                              + '</p><div class="wk-detail">').encode(), 1), HTML, {}

    def not_found(self, title: str = "Mod not found", text: str = "No mod by that name is in the Workshop.") -> bytes:
        e = html.escape
        body = (f'<section class="ly-panel"><h2>{e(title)}</h2><p class="wk-empty">{e(text)} '
                '<a href="/wrath/mods">See every mod</a></p></section>')
        return self._page(f"Workshop · {self.realm_name}", "/wrath/mods", f"Workshop · {self.realm_name}", body)

    def _file(self, *parts, limit: int) -> bytes | None:
        try:
            with open(os.path.join(self.dir, *parts), "rb") as f:
                b = f.read(limit + 1)
            return b if len(b) <= limit else None
        except OSError:
            return None

    # ---------------------------------------------------------------- routing
    def serve(self, path: str, query: dict, req: dict | None = None) -> tuple[int, bytes, str, dict]:
        """(status, body, content type, extra headers) for a path match() owns.

        req (optional, from the portal): {"method", "cookie", "ip", "ua", "form": {name: value},
        "who": callable(cookie, ip, ua) -> the /api/me dict, None when signed out; raises when the site is down}.
        Without it every page is the signed-out page and POSTs are refused."""
        HTML = "text/html; charset=utf-8"
        if req and req.get("method") == "POST":
            return self._post(path or "", req)
        if path == "/wrath/mods/all.json":
            return 200, self.all_json(), "application/json; charset=utf-8", {"Access-Control-Allow-Origin": "*"}
        if path == "/wrath/mods/credits":
            return 200, self.credits_page(), HTML, {}
        if path == "/wrath/mods/submit":
            st, body = self.submit_page(req, note=QUEUED_NOTE if (query or {}).get("queued") else "")
            return st, body, HTML, {}
        pm = _PROJ_RE.fullmatch(path or "")
        if pm:
            if pm.group(2):
                return 405, b"use the button on the page\n", "text/plain", {"Allow": "POST"}
            notes = {"added": "Added: it's in the Workshop now. Thank you for sharing it.",
                     "dup": "That project is already listed: here it is."}
            note = next((v for k, v in notes.items() if query.get(k)), "")
            done = (query.get("done") or [""])[0]
            note = note or {"report": "Thanks: the admins will take a look.", "hide": "Hidden.",
                            "unhide": "Shown again."}.get(done, "")
            st, body = self.project_page(pm.group(1), req, note)
            return st, body, HTML, {}
        cm = _CAT_PATH_RE.fullmatch(path or "")
        if cm:
            cat = self.category(cm.group(1)) if ID_RE.fullmatch(cm.group(1)) else None
            if cat is None:
                return 404, self.not_found("Category not found", "No category by that name is in the Workshop."), HTML, {}
            return 200, self.list_page(query, cat), HTML, {}
        m = _PATH_RE.fullmatch(path or "")
        if not m:
            return 404, self.not_found(), HTML, {}
        ident, action, num = m.group(1), m.group(2), m.group(3)
        if ident is None:
            return 200, self.list_page(query), HTML, {}
        if ident == "catalog.json":
            if action:
                return 404, self.not_found(), HTML, {}
            mods, installed = self.load()
            doc = {"format": 1, "categories": self.categories()[0],
                   "mods": [dict(x, on_wrath=installed.get(x["id"]) == x["version"]) for x in mods]}
            return 200, (json.dumps(doc, indent=1) + "\n").encode("utf-8"), "application/json; charset=utf-8", \
                {"Access-Control-Allow-Origin": "*"}
        mod = self.mod(ident) if (3 <= len(ident) <= 32 and ID_RE.fullmatch(ident)) else None
        if mod is None:
            return 404, self.not_found(), HTML, {}
        if action is None:
            return 200, self.detail_page(mod), HTML, {}
        if action == "download" and num is None and mod["zip"]:
            b = self._file("files", mod["zip"], limit=MAX_ZIP)
            if b is not None:
                return 200, b, "application/zip", {"Content-Disposition": f'attachment; filename="{mod["zip"]}"'}
        if action == "shot" and num is not None and int(num) < len(mod["screenshots"]):
            name = mod["screenshots"][int(num)]
            b = self._file("shots", mod["id"], name, limit=MAX_SHOT)
            if b is not None:
                return 200, b, SHOT_TYPES[name.rsplit(".", 1)[1].lower()], {}
        return 404, b"not found\n", "text/plain", {}


def parse_form(body: bytes) -> dict:
    """An application/x-www-form-urlencoded body (at most MAX_FORM bytes) as {name: first value}."""
    try:
        pairs = urllib.parse.parse_qsl(body[:MAX_FORM].decode("utf-8"), keep_blank_values=True, max_num_fields=20)
    except (UnicodeDecodeError, ValueError):
        return {}
    out = {}
    for k, v in pairs:
        out.setdefault(k, v)
    return out
