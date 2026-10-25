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

import html
import json
import os
import re
import threading
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
GUIDE_URL = "https://github.com/orionopenwow/WrathUnleashed/blob/main/mods/README-modders.md"
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
.wk-card{display:flex;flex-direction:column;background:rgba(18,22,54,.78);border:1px solid var(--ly-line);border-radius:6px;
overflow:hidden;text-decoration:none;color:var(--ly-ink)!important;min-width:0}
.wk-card:hover,.wk-card:focus-visible{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.wk-card img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:cover;background:#070918}
.wk-card .noimg{aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;background:#070918;color:var(--ly-dim);
font:600 28px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.1em;text-transform:uppercase}
.wk-card .body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px}
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
    if not isinstance(mid, str) or not (3 <= len(mid) <= 32) or not ID_RE.fullmatch(mid):
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
    return {"id": mid, "category": cat, "version": ver, "kind": kind, "name": text("name", 48) or mid,
            "author": text("author", 80), "licence": text("licence", 80), "description": text("description", 300),
            "permissions": sorted(set(perms), key=PERMISSIONS.index), "screenshots": shots[:8],
            "addons": addons[:8], "zip": zname, "sha256": sha, "size": size}


class Workshop:
    def __init__(self, mods_dir: str = MODS_DIR, css=None, card_meta=None, realm_name: str = "WrathUnleashed"):
        self.dir = mods_dir
        self.css = css or (lambda: "")
        self.card_meta = card_meta or (lambda path, title="": "")
        self.realm_name = realm_name
        self._cache = {"key": None, "mods": [], "installed": {}}
        self._cats = {"key": None, "list": [], "defaults": {}}
        self._lock = threading.Lock()

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

    def load(self) -> tuple[list[dict], dict]:
        """(mods, {id: installed version}), reread only when the files change. Each mod's "category" is a
        known category id (its own, else the default for its kind) or "" when there is no category list."""
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

    @staticmethod
    def _filters(query: dict) -> tuple[str, str, str]:
        kind = (query.get("kind") or [""])[0]
        perm = (query.get("perm") or [""])[0]
        q = " ".join(str((query.get("q") or [""])[0]).split())[:MAX_QUERY]
        return (kind if kind in KINDS else ""), (perm if perm in PERMISSIONS or perm == "none" else ""), q

    @staticmethod
    def _href(kind: str, perm: str, q: str = "", cat: str = "") -> str:
        qs = urllib.parse.urlencode([(k, v) for k, v in (("kind", kind), ("perm", perm), ("q", q)) if v])
        return ("/wrath/mods/c/" + cat if cat else "/wrath/mods") + ("?" + qs if qs else "")

    @staticmethod
    def icon(c: dict) -> str:
        if c.get("icon") in ICONS:
            return (f'<span class="wk-ico" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false">'
                    f'{ICONS[c["icon"]]}</svg></span>')
        return f'<span class="wk-ico" aria-hidden="true">{html.escape(c["name"][:1])}</span>'

    @staticmethod
    def _matches(m: dict, q: str, cat_names: dict) -> bool:
        """Every word of q appears in the name, the description or the category (name or id)."""
        hay = " ".join((m["name"], m["description"], m["category"], cat_names.get(m["category"], ""))).lower()
        return all(w in hay for w in q.lower().split())

    def list_page(self, query: dict, cat: dict | None = None) -> bytes:
        e = html.escape
        mods, installed = self.load()
        cats, _ = self.categories()
        cat_names = {c["id"]: c["name"] for c in cats}
        kind, perm, q = self._filters(query)
        cid = cat["id"] if cat else ""
        in_cat = [m for m in mods if not cid or m["category"] == cid]
        shown = [m for m in in_cat if (not kind or m["kind"] == kind)
                 and (not perm or (perm == "none" and not m["permissions"]) or perm in m["permissions"])
                 and (not q or self._matches(m, q, cat_names))]

        def chip(label, k, p, on):
            return f'<a class="wk-chip{" on" if on else ""}" href="{e(self._href(k, p, q, cid))}">{e(label)}</a>'
        kinds = chip("All", "", perm, not kind) + "".join(chip(KIND_LABEL[k], k, perm, kind == k) for k in KINDS)
        perms = chip("Any", kind, "", not perm) + chip("None", kind, "none", perm == "none") \
            + "".join(chip(PERM_LABEL[p], kind, p, perm == p) for p in PERMISSIONS)

        counts = {c["id"]: 0 for c in cats}
        for m in mods:
            if m["category"] in counts:
                counts[m["category"]] += 1
        cat_grid = ""
        if cats:
            tiles = []
            for c in cats:
                n = counts[c["id"]]
                cls = "wk-cat" + (" on" if c["id"] == cid else "") + ("" if n else " zero")
                cur = ' aria-current="page"' if c["id"] == cid else ""
                tiles.append(f'<a class="{cls}" href="/wrath/mods/c/{e(c["id"])}" title="{e(c["line"])}"{cur}>'
                             f'{self.icon(c)}<span class="nm">{e(c["name"])}</span>'
                             f'<span class="n" aria-label="{n} mod{"" if n == 1 else "s"}">{n}</span></a>')
            cat_grid = ('<section class="ly-panel" aria-labelledby="wk-cats"><h2 id="wk-cats">Categories</h2>'
                        f'<nav class="wk-cats" aria-label="Categories">{"".join(tiles)}</nav></section>')

        cards = []
        for m in shown:
            img = (f'<img src="/wrath/mods/{e(m["id"])}/shot/0" alt="" loading="lazy" width="640" height="360">'
                   if m["screenshots"] else f'<div class="noimg" aria-hidden="true">{e(m["name"][:1])}</div>')
            tags = []
            if m["category"] in cat_names and not cid:
                tags.append(f'<span class="wk-tag cat">{e(cat_names[m["category"]])}</span>')
            tags.append(f'<span class="wk-tag kind">{e(KIND_LABEL[m["kind"]])}</span>')
            if installed.get(m["id"]) == m["version"]:
                tags.append('<span class="wk-tag live">On Wrath</span>')
            tags += [f'<span class="wk-tag">{e(PERM_LABEL[p])}</span>' for p in m["permissions"]]
            cards.append(f'<a class="wk-card" href="/wrath/mods/{e(m["id"])}">{img}<div class="body">'
                         f'<h3>{e(m["name"])}</h3><span class="wk-ver">v{e(m["version"])}'
                         f'{" · " + e(m["author"]) if m["author"] else ""}</span>'
                         f'<p>{e(m["description"])}</p><div class="wk-tags">{"".join(tags)}</div></div></a>')
        here = self._href("", "", "", cid)
        if cards:
            grid = f'<div class="wk-grid">{"".join(cards)}</div>'
        elif cat and not in_cat:
            grid = ('<div class="wk-first"><h3>Publish the first one</h3>'
                    f'<p>Nothing in {e(cat["name"])} yet. Make a mod in the open format, check it with wu-mod.py '
                    'and send it in: it shows up here once it is on the realm.</p>'
                    f'<div class="wk-actions"><a class="wk-btn violet" href="{GUIDE_URL}" rel="noopener noreferrer">'
                    'Read the modder guide</a></div></div>')
        elif in_cat:
            grid = f'<p class="wk-empty">No mods match these filters. <a href="{e(here)}">Show all</a></p>'
        else:
            grid = '<p class="wk-empty">The Workshop is empty right now. Mods appear here once they are on the realm.</p>'

        search = (f'<form class="wk-search" method="get" action="{e(here)}" role="search">'
                  + (f'<input type="hidden" name="kind" value="{e(kind)}">' if kind else "")
                  + (f'<input type="hidden" name="perm" value="{e(perm)}">' if perm else "")
                  + f'<input type="search" name="q" value="{e(q)}" maxlength="{MAX_QUERY}" '
                  'placeholder="Search names, descriptions, categories" aria-label="Search mods">'
                  '<button type="submit">Search</button></form>')
        filters = (search
                   + f'<div class="wk-bar" role="group" aria-label="Kind"><span class="lbl">Kind</span>{kinds}</div>'
                   + f'<div class="wk-bar" role="group" aria-label="Permissions"><span class="lbl">Permissions</span>{perms}</div>')
        fine = ('<p class="ly-fine">In the game: Esc &rarr; Mods &amp; Workshop turns the addons on and off. '
                f'Make your own: <a href="{GUIDE_URL}" rel="noopener noreferrer">the modder guide</a> and '
                '<a href="https://github.com/orionopenwow/WrathUnleashed/tree/main/mods" '
                'rel="noopener noreferrer">the mod format and a template</a>.</p>')
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
        body = (
            '<header class="ly-hero"><h1 class="wk-h1">Workshop</h1>'
            '<p class="wk-lede">The whole Leyline catalog for Wrath: addons, graphics, game modes, maps, builds, '
            'encounters, models, realm scripts, presets, sounds, tools and total conversions, in one open format. '
            f'{n_live} of {len(mods)} are on {e(self.realm_name)} now.</p></header>'
            f'{cat_grid}'
            '<section class="ly-panel" aria-labelledby="wk-mods"><h2 id="wk-mods">Mods</h2>'
            f'{filters}{grid}</section>{fine}')
        return self._page(f"Workshop · {self.realm_name}", "/wrath/mods", f"Workshop · {self.realm_name}", body,
                          "Community mods for Wrath on the Leyline network: addons, game modes, maps, realm scripts "
                          "and more, free and open.")


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
            + '</dl><h3 class="wk-sub">What it can do on the realm</h3>' + perm_html
            + f'<div class="wk-actions">{download}'
            f'<a class="wk-btn violet" href="/wrath/m/{e(m["id"])}">Share link</a>'
            f'<a class="wk-btn" href="/wrath?go=m:{e(m["id"])}">Play</a></div>'
            + (f'<p class="wk-sum">sha256 {e(m["sha256"])}</p>' if m["sha256"] and m["zip"] else "")
            + f'<p class="ly-fine" style="text-align:left">Share: <a href="/wrath/m/{e(m["id"])}">'
            f'play.openvanilla.app/wrath/m/{e(m["id"])}</a></p></div></div></section>')
        return self._page(f"{m['name']} · Workshop", f"/wrath/mods/{m['id']}", f"Mod: {m['name']} · Leyline", body,
                          m["description"] or "A community mod for Wrath on the Leyline network.")

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
    def serve(self, path: str, query: dict) -> tuple[int, bytes, str, dict]:
        """(status, body, content type, extra headers) for a path match() owns."""
        HTML = "text/html; charset=utf-8"
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
