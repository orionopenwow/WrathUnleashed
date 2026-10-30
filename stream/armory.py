"""The Wrath web armory for the portal (stream/wrath_portal.py), in the Leyline page look.

    GET /wrath/armory              search by name (?q=, letters only, at most 12), and showcase lists:
                                   recent level 80s, most achievement points, guilds
    GET /wrath/armory/<Name>       a character sheet: the equipped items in a paper-doll layout (names in
                                   their quality colours, plain text), both talent specs as points per tree,
                                   achievements, honorable kills, arena ratings, professions, last seen (a
                                   day), and a share link (/wrath/u/<Name>)

The data is files only, written every 5 minutes by realm/custom/armory-export.py (run by cron on the host;
the portal never touches the database):

    <WU_ARMORY_DIR>/index.json      {"updated": N, "chars": [summary, ...]}
    <WU_ARMORY_DIR>/c/<Name>.json   one character

Privacy. The export already leaves out bots (RNDBOT accounts), characters whose player typed ".armory off"
in game (ov_armory.lua), deleted characters, and every account detail. This module checks again: a character
is shown only when it is in the index AND its file is there; only the fields listed in clean_char() are ever
read (no gold, bags, bank, mail, accounts or addresses, even if a file held them); a record that says it is a
bot is dropped. An opted-out character and a name nobody has look exactly the same (404).

Files are cached in memory (re-read when they change, checked at most every few seconds); pages are cached
for 30 s. Standard library only; when this file is missing the portal simply has no armory.
"""
from __future__ import annotations

import collections
import html
import json
import os
import re
import threading
import time

DATA_DIR = os.environ.get("WU_ARMORY_DIR", "/app/armory")
NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")
MAX_QUERY = 12
MAX_RESULTS = 25
SHOW = 10
STAT_EVERY = 5.0          # seconds between checks of index.json's mtime
PAGE_TTL = 30.0
PAGE_CACHE_MAX = 400
CHAR_CACHE_MAX = 600
MAX_FILE = 512_000
MAX_INDEX = 16_000_000

RACES = {1: "Human", 2: "Orc", 3: "Dwarf", 4: "Night Elf", 5: "Undead", 6: "Tauren", 7: "Gnome", 8: "Troll",
         10: "Blood Elf", 11: "Draenei"}
ALLIANCE = {1, 3, 4, 7, 11}
CLASSES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest", 6: "Death Knight", 7: "Shaman",
           8: "Mage", 9: "Warlock", 11: "Druid"}
CLASS_COLOR = {1: "#c79c6e", 2: "#f58cba", 3: "#abd473", 4: "#fff569", 5: "#ffffff", 6: "#ff4d6a", 7: "#2f8fff",
               8: "#69ccf0", 9: "#a29bff", 11: "#ff7d0a"}
TREES = {1: ("Arms", "Fury", "Protection"), 2: ("Holy", "Protection", "Retribution"),
         3: ("Beast Mastery", "Marksmanship", "Survival"), 4: ("Assassination", "Combat", "Subtlety"),
         5: ("Discipline", "Holy", "Shadow"), 6: ("Blood", "Frost", "Unholy"),
         7: ("Elemental", "Enhancement", "Restoration"), 8: ("Arcane", "Fire", "Frost"),
         9: ("Affliction", "Demonology", "Destruction"), 11: ("Balance", "Feral Combat", "Restoration")}
# quality -> (label, colour); the colours are lifted a little from the classic ones to read on the dark panel
QUALITY = {0: ("Poor", "#9d9d9d"), 1: ("Common", "#ffffff"), 2: ("Uncommon", "#1eff00"), 3: ("Rare", "#4aa3ff"),
           4: ("Epic", "#c27bff"), 5: ("Legendary", "#ff8000"), 6: ("Artifact", "#e6cc80"), 7: ("Heirloom", "#e6cc80")}
SLOTS = {0: "Head", 1: "Neck", 2: "Shoulder", 3: "Shirt", 4: "Chest", 5: "Waist", 6: "Legs", 7: "Feet", 8: "Wrist",
         9: "Hands", 10: "Finger", 11: "Finger", 12: "Trinket", 13: "Trinket", 14: "Back", 15: "Main hand",
         16: "Off hand", 17: "Ranged", 18: "Tabard"}
LEFT, RIGHT, BOTTOM = (0, 1, 2, 14, 4, 3, 18, 8), (9, 5, 6, 7, 10, 11, 12, 13), (15, 16, 17)
PROFESSIONS = {164: "Blacksmithing", 165: "Leatherworking", 171: "Alchemy", 182: "Herbalism", 186: "Mining",
               197: "Tailoring", 202: "Engineering", 333: "Enchanting", 393: "Skinning", 755: "Jewelcrafting",
               773: "Inscription", 129: "First Aid", 185: "Cooking", 356: "Fishing"}
SECONDARY = {129, 185, 356}
ARENA = {2: "2v2", 3: "3v3", 5: "5v5"}
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GUILD_RE = re.compile(r"^[^\x00-\x1f<>]{1,24}$")

e = html.escape


# ----------------------------------------------------------------------------------------------
# data: whitelisted fields only
# ----------------------------------------------------------------------------------------------

def _n(v, lo=0, hi=2**31 - 1):
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _day(v) -> str:
    return v if isinstance(v, str) and DAY_RE.fullmatch(v) else ""


def _guild(v) -> str:
    return v.strip() if isinstance(v, str) and GUILD_RE.fullmatch(v.strip() or "-") and v.strip() else ""


def clean_summary(r) -> dict | None:
    """The fields a list or a card may show, checked; None for anything not plainly a player's character."""
    if not isinstance(r, dict) or r.get("bot") or r.get("hidden"):
        return None
    name = r.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return None
    race, cls, level = _n(r.get("race"), 0, 255), _n(r.get("class"), 0, 255), _n(r.get("level"), 1, 255)
    if race not in RACES or cls not in CLASSES or level is None:
        return None
    return {"name": name, "race": race, "class": cls, "gender": 1 if r.get("gender") == 1 else 0, "level": level,
            "guild": _guild(r.get("guild")), "ach_points": _n(r.get("ach_points")),
            "ach_count": _n(r.get("ach_count")) or 0, "last_day": _day(r.get("last_day")),
            "reached80_day": _day(r.get("reached80_day"))}


def clean_char(r) -> dict | None:
    base = clean_summary(r)
    if base is None:
        return None
    items = {}
    for it in r.get("items") if isinstance(r.get("items"), list) else []:
        if not isinstance(it, dict):
            continue
        slot, entry = _n(it.get("slot"), 0, 18), _n(it.get("entry"), 1)
        name = it.get("name")
        if slot is None or entry is None or slot in items:
            continue
        items[slot] = {"entry": entry, "quality": _n(it.get("quality"), 0, 7) or 0, "ilvl": _n(it.get("ilvl"), 0, 1000) or 0,
                       "name": name.strip()[:80] if isinstance(name, str) and name.strip() else f"Item {entry}"}
    specs = []
    for s in (r.get("specs") if isinstance(r.get("specs"), list) else [])[:2]:
        if isinstance(s, list) and len(s) == 3 and all(_n(x, 0, 100) is not None for x in s):
            specs.append(list(s))
    arena = []
    for a in r.get("arena") if isinstance(r.get("arena"), list) else []:
        if isinstance(a, dict) and _n(a.get("type")) in ARENA:
            arena.append({"type": a["type"], "rating": _n(a.get("rating"), 0, 10000) or 0,
                          "personal": _n(a.get("personal"), 0, 10000) or 0})
    prof = []
    for p in r.get("prof") if isinstance(r.get("prof"), list) else []:
        if isinstance(p, dict) and _n(p.get("skill")) in PROFESSIONS and _n(p.get("value"), 1, 1000):
            prof.append({"skill": p["skill"], "value": p["value"], "max": _n(p.get("max"), 0, 1000) or p["value"]})
    base.update(items=items, specs=specs, active_spec=1 if r.get("active_spec") == 1 else 0,
                hk=_n(r.get("hk")) or 0, arena=arena[:3], prof=prof[:6])
    return base


class Store:
    """index.json and the character files, read when they change."""

    def __init__(self, root: str = DATA_DIR):
        self.root = root
        self.lock = threading.Lock()
        self.checked = 0.0
        self.key = None
        self.updated = 0
        self.chars: list[dict] = []
        self.by_name: dict[str, dict] = {}
        self.cache: collections.OrderedDict = collections.OrderedDict()

    @staticmethod
    def _load(path: str, limit: int):
        try:
            with open(path, "rb") as f:
                b = f.read(limit + 1)
            return json.loads(b.decode("utf-8")) if len(b) <= limit else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None

    def refresh(self) -> None:
        now = time.monotonic()
        with self.lock:
            if now - self.checked < STAT_EVERY and self.key is not None:
                return
            self.checked = now
            p = os.path.join(self.root, "index.json")
            try:
                st = os.stat(p)
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                key = ("missing",)
            if key == self.key:
                return
            self.key = key
            doc = self._load(p, MAX_INDEX) if key != ("missing",) else None
            chars, by_name = [], {}
            for r in (doc.get("chars") if isinstance(doc, dict) and isinstance(doc.get("chars"), list) else []):
                c = clean_summary(r)
                if c and c["name"].lower() not in by_name:
                    by_name[c["name"].lower()] = c
                    chars.append(c)
            self.chars, self.by_name = chars, by_name
            self.updated = (_n(doc.get("updated")) or 0) if isinstance(doc, dict) else 0
            self.cache.clear()

    def summary(self, name: str) -> dict | None:
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            return None
        self.refresh()
        return self.by_name.get(name.lower())

    def char(self, name: str) -> dict | None:
        s = self.summary(name)
        if s is None:   # not in the index: unknown, a bot, or opted out; the file is never read
            return None
        path = os.path.join(self.root, "c", s["name"] + ".json")
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = (s["name"], st.st_mtime_ns, st.st_size)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        r = self._load(path, MAX_FILE)
        c = clean_char(r) if isinstance(r, dict) and r.get("name") == s["name"] else None
        with self.lock:
            self.cache[key] = c
            while len(self.cache) > CHAR_CACHE_MAX:
                self.cache.popitem(last=False)
        return c

    def search(self, q: str) -> list[dict]:
        self.refresh()
        q = q.lower()
        starts = [c for c in self.chars if c["name"].lower().startswith(q)]
        inside = [c for c in self.chars if q in c["name"].lower() and c not in starts]
        return (sorted(starts, key=lambda c: (len(c["name"]), c["name"])) + sorted(inside, key=lambda c: c["name"]))[:MAX_RESULTS]

    def showcase(self) -> dict:
        self.refresh()
        recent = sorted((c for c in self.chars if c["level"] >= 80 and c["reached80_day"]),
                        key=lambda c: (c["reached80_day"], c["name"]), reverse=True)[:SHOW]
        by_points = sorted((c for c in self.chars if (c["ach_points"] or c["ach_count"])),
                           key=lambda c: (-(c["ach_points"] or 0), -c["ach_count"], c["name"]))[:SHOW]
        guilds: dict[str, list] = {}
        for c in self.chars:
            if c["guild"]:
                g = guilds.setdefault(c["guild"], [0, 0])
                g[0] += 1
                g[1] += c["level"] >= 80
        top_guilds = sorted(guilds.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0].lower()))[:SHOW]
        return {"recent80": recent, "points": by_points, "guilds": top_guilds, "count": len(self.chars)}


store = Store()


def card_line(name: str, st: Store | None = None) -> dict | None:
    """For links.py's /u/<name> card: {"name", "line"} when the character is in the armory, else None."""
    try:
        s = (st or store).summary(name)
    except Exception:  # noqa: BLE001: a card never breaks
        return None
    if not s:
        return None
    return {"name": s["name"], "line": f"level {s['level']} {RACES[s['race']]} {CLASSES[s['class']]}"}


# ----------------------------------------------------------------------------------------------
# pages
# ----------------------------------------------------------------------------------------------

ARMORY_CSS = """
.ar-search{display:flex;gap:8px;max-width:520px;margin:6px auto 4px}
.ar-search input{flex:1;min-width:0;padding:11px 12px;font:600 16px system-ui,sans-serif;color:var(--ly-ink);
background:rgba(6,8,24,.85);border:1px solid var(--ly-line);border-radius:6px}
.ar-search input:focus-visible{outline:2px solid var(--ly-cyan);outline-offset:1px}
.ar-search button{padding:0 18px;font:600 15px system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#1a1030;
background:linear-gradient(180deg,#9ff0ff,var(--ly-cyan));border:1px solid #9ff0ff;border-radius:6px;cursor:pointer}
.ar-list{list-style:none;margin:0;padding:0}
.ar-list li{display:flex;justify-content:space-between;gap:10px;padding:8px 2px;border-bottom:1px solid rgba(120,150,255,.12)}
.ar-list li:last-child{border-bottom:0}
.ar-list .sub,.ar-dim{color:var(--ly-dim);font-size:13px}
.ar-cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
@media (max-width:860px){.ar-cols{grid-template-columns:1fr}}
.ar-cols h3,.ar-box h3{margin:0 0 8px;font:600 19px/1.15 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--ly-cyan)}
.ar-head{text-align:center;margin:4px 0 6px}
.ar-head .who{font-size:17px}
.ar-head h1{font-size:clamp(40px,8vw,72px);margin:0 0 4px}
.ar-doll{display:grid;grid-template-columns:1fr minmax(0,240px) 1fr;gap:10px;align-items:start}
.ar-doll .mid{align-self:stretch;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;
gap:6px;padding:14px;border:1px solid var(--ly-line);border-radius:6px;background:rgba(18,22,54,.55)}
.ar-doll .mid .big{font:600 44px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;color:#bff6ff}
.ar-col{display:flex;flex-direction:column;gap:6px}
.ar-col.right{text-align:right}
.ar-bottom{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:6px}
.ar-slot{padding:7px 10px;border:1px solid rgba(120,150,255,.2);border-radius:5px;background:rgba(8,10,30,.7);min-height:46px}
.ar-slot .lab{display:block;font:600 10px/1.3 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--ly-dim)}
.ar-slot .it{font-weight:600;overflow-wrap:anywhere}
.ar-slot .il{color:var(--ly-dim);font-size:12px;margin-left:4px}
.ar-slot.empty .it{color:#5a6088;font-weight:400}
@media (max-width:700px){.ar-doll{grid-template-columns:1fr}.ar-col.right{text-align:left}.ar-doll .mid{order:-1}
.ar-bottom{grid-template-columns:1fr}}
.ar-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
@media (max-width:700px){.ar-grid{grid-template-columns:1fr}}
.ar-box{background:rgba(18,22,54,.7);border:1px solid var(--ly-line);border-radius:6px;padding:14px 16px}
.ar-spec{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid rgba(120,150,255,.12)}
.ar-spec:last-child{border-bottom:0}
.ar-tag{display:inline-block;margin-left:6px;font:600 10px/1 system-ui;letter-spacing:.1em;text-transform:uppercase;
color:#5ef0a0;border:1px solid rgba(94,240,160,.5);border-radius:999px;padding:3px 7px;vertical-align:middle}
.ar-share{display:flex;gap:8px;align-items:center;justify-content:center;flex-wrap:wrap;margin:14px 0 0}
.ar-share code{background:rgba(6,8,24,.85);border:1px solid var(--ly-line);border-radius:4px;padding:6px 9px;overflow-wrap:anywhere;user-select:all}
.ar-share .ly-btn{min-height:44px;font-size:18px;padding:8px 18px}
.ar-stat{font:600 26px/1.1 'Leyline Display','OW Cinzel',Impact,sans-serif;color:#bff6ff}
"""


def _who(c: dict) -> str:
    side = "Alliance" if c["race"] in ALLIANCE else "Horde"
    return (f'Level {c["level"]} {e(RACES[c["race"]])} '
            f'<span style="color:{CLASS_COLOR[c["class"]]}">{e(CLASSES[c["class"]])}</span> · {side}')


def _char_link(c: dict) -> str:
    return (f'<a href="/wrath/armory/{e(c["name"])}" style="color:{CLASS_COLOR[c["class"]]}">{e(c["name"])}</a>')


def _page(title: str, body: str, css: str, meta: str) -> bytes:
    """The page; the site's nav and footer are put in by the portal as it is sent (wrath_portal.site_chrome)."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{e(title)}</title>{meta}<style>{css}{ARMORY_CSS}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div><div class="ly-wrap">{body}</div></body></html>').encode("utf-8")


def _search_form(q: str = "") -> str:
    return ('<form class="ar-search" method="get" action="/wrath/armory" role="search">'
            f'<input type="search" name="q" value="{e(q)}" maxlength="{MAX_QUERY}" placeholder="Character name" '
            'aria-label="Character name" autocomplete="off" spellcheck="false" pattern="[A-Za-z]*">'
            '<button type="submit">Search</button></form>')


def _footer(st: Store) -> str:
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(st.updated)) if st.updated else "not yet"
    return ('<p class="ly-fine">Updated every 5 minutes (last: ' + e(when) + '). Bots are not listed. '
            'Rather not be here? Type <code>.armory off</code> in game and your character leaves the armory '
            'within 5 minutes (<code>.armory on</code> brings it back). Gold, bags, bank, mail and accounts are never shown.</p>')


def clean_query(raw: str) -> str:
    return re.sub(r"[^A-Za-z]", "", (raw or "")[:64])[:MAX_QUERY]


def index_page(query: dict, css: str, card_meta, realm_name: str, st: Store | None = None) -> bytes:
    st = st or store
    raw = (query.get("q") or [""])[0]
    q = clean_query(raw)
    sc = st.showcase()
    parts = ['<header class="ly-hero"><h1>Armory</h1>'
             f'<p class="ly-lede">The characters of {e(realm_name)}: gear, talents, achievements and professions.</p>'
             f'<span class="ly-ver">{sc["count"]} characters</span></header>', _search_form(q)]
    if raw and not q:
        parts.append('<p class="ly-fine">Names are letters only.</p>')
    if q:
        found = st.search(q)
        rows = "".join(f'<li><span>{_char_link(c)}</span><span class="sub">{_who(c)}'
                       f'{" · " + e(c["guild"]) if c["guild"] else ""}</span></li>' for c in found)
        parts.append('<section class="ly-panel" aria-labelledby="ar-res"><h2 id="ar-res">Results</h2>'
                     + (f'<ul class="ar-list">{rows}</ul>' if found
                        else f'<p class="ly-fine">Nobody called &ldquo;{e(q)}&rdquo; is in the armory.</p>')
                     + '</section>')

    def col(title, items):
        return f'<div><h3>{e(title)}</h3>' + (f'<ul class="ar-list">{"".join(items)}</ul>' if items
                                              else '<p class="ar-dim">Nobody yet.</p>') + '</div>'
    recent = [f'<li><span>{_char_link(c)}</span><span class="sub">{e(CLASSES[c["class"]])} · {e(c["reached80_day"])}</span></li>'
              for c in sc["recent80"]]
    points = [f'<li><span>{_char_link(c)}</span><span class="sub">'
              + (f'{c["ach_points"]} points' if c["ach_points"] is not None else f'{c["ach_count"]} earned')
              + '</span></li>' for c in sc["points"]]
    guilds = [f'<li><span>{e(g)}</span><span class="sub">{n} listed · {n80} at 80</span></li>' for g, (n, n80) in sc["guilds"]]
    parts.append('<section class="ly-panel" aria-labelledby="ar-show"><h2 id="ar-show">Showcase</h2><div class="ar-cols">'
                 + col("Recent level 80s", recent) + col("Achievement points", points) + col("Guilds", guilds)
                 + '</div></section>')
    parts.append(_footer(st))
    meta = card_meta("/wrath/armory", f"Armory · {realm_name}")
    return _page(f"Armory · {realm_name}", "".join(parts), css, meta)


def _slot(slot: int, items: dict) -> str:
    it = items.get(slot)
    if not it:
        return f'<div class="ar-slot empty"><span class="lab">{SLOTS[slot]}</span><span class="it">Empty</span></div>'
    label, colour = QUALITY.get(it["quality"], QUALITY[1])
    il = f'<span class="il">{it["ilvl"]}</span>' if it["ilvl"] else ""
    return (f'<div class="ar-slot"><span class="lab">{SLOTS[slot]}</span>'
            f'<span class="it" style="color:{colour}" title="{e(label)}">{e(it["name"])}</span>{il}</div>')


def char_page(name: str, css: str, card_meta, realm_name: str, public_host: str, st: Store | None = None) -> tuple[int, bytes]:
    st = st or store
    c = st.char(name) if NAME_RE.fullmatch(name or "") else None
    if c is None:
        body = ('<header class="ly-hero"><h1>Armory</h1></header>'
                '<section class="ly-panel"><h2>Not found</h2><p class="ly-fine">That character isn\'t in the armory.</p>'
                + _search_form() + '</section>' + _footer(st))
        return 404, _page(f"Armory · {realm_name}", body, css, card_meta("/wrath/armory", f"Armory · {realm_name}"))
    n = c["name"]
    items = c["items"]
    ilvls = [it["ilvl"] for s, it in items.items() if s not in (3, 18) and it["ilvl"]]
    avg = round(sum(ilvls) / len(ilvls)) if ilvls else 0
    mid = (f'<div class="mid"><span class="ar-dim">Average item level</span><span class="big">{avg or "–"}</span>'
           f'<span class="ar-dim">{e(c["guild"]) if c["guild"] else "No guild"}</span></div>')
    doll = ('<div class="ar-doll">'
            f'<div class="ar-col">{"".join(_slot(s, items) for s in LEFT)}</div>{mid}'
            f'<div class="ar-col right">{"".join(_slot(s, items) for s in RIGHT)}</div></div>'
            f'<div class="ar-bottom">{"".join(_slot(s, items) for s in BOTTOM)}</div>')
    trees = TREES[c["class"]]
    if c["specs"]:
        specs = ""
        for i, pts in enumerate(c["specs"]):
            if i == 1 and not any(pts):
                continue
            top = trees[max(range(3), key=lambda k: pts[k])] if any(pts) else "No talents"
            tag = '<span class="ar-tag">active</span>' if i == c["active_spec"] else ""
            specs += (f'<div class="ar-spec"><span>{"Primary" if i == 0 else "Secondary"}: <b>{e(top)}</b>{tag}</span>'
                      f'<span class="ar-dim" title="{e(" / ".join(trees))}">{pts[0]} / {pts[1]} / {pts[2]}</span></div>')
    else:
        specs = '<p class="ar-dim">Not available yet.</p>'
    ach = (f'<span class="ar-stat">{c["ach_points"]}</span> <span class="ar-dim">points</span> · ' if c["ach_points"] is not None else "")
    ach += f'<span class="ar-stat">{c["ach_count"]}</span> <span class="ar-dim">earned</span>'
    pvp = f'<p><span class="ar-stat">{c["hk"]}</span> <span class="ar-dim">honorable kills</span></p>'
    if c["arena"]:
        pvp += '<ul class="ar-list">' + "".join(
            f'<li><span>{ARENA[a["type"]]}</span><span class="sub">team {a["rating"]} · personal {a["personal"]}</span></li>'
            for a in c["arena"]) + '</ul>'
    prim = [p for p in c["prof"] if p["skill"] not in SECONDARY]
    sec = [p for p in c["prof"] if p["skill"] in SECONDARY]
    prof = ('<ul class="ar-list">' + "".join(
        f'<li><span>{e(PROFESSIONS[p["skill"]])}</span><span class="sub">{p["value"]} / {p["max"]}</span></li>'
        for p in prim + sec) + '</ul>') if c["prof"] else '<p class="ar-dim">None yet.</p>'
    share_path = f"/wrath/u/{n}"
    body = (f'<header class="ar-head"><h1>{e(n)}</h1><p class="who">{_who(c)}</p>'
            + (f'<p class="ar-dim">Last seen {e(c["last_day"])}</p>' if c["last_day"] else "")
            + '</header>'
            f'<section class="ly-panel" aria-labelledby="ar-gear"><h2 id="ar-gear">Gear</h2>{doll}</section>'
            '<div class="ar-grid">'
            f'<div class="ar-box"><h3>Talents</h3>{specs}</div>'
            f'<div class="ar-box"><h3>Achievements</h3><p>{ach}</p></div>'
            f'<div class="ar-box"><h3>Player vs player</h3>{pvp}</div>'
            f'<div class="ar-box"><h3>Professions</h3>{prof}</div></div>'
            f'<div class="ar-share"><a class="ly-btn" href="{e(share_path)}">Share</a>'
            f'<code tabindex="0" title="Tap to select, then copy">https://{e(public_host)}{e(share_path)}</code></div>'
            + _footer(st))
    title = f"{n} · Armory · {realm_name}"
    return 200, _page(title, body, css, card_meta(f"/wrath/armory/{n}", f"{n}, {card_line(n, st)['line']} · {realm_name}"))


def match(path: str) -> bool:
    return path == "/wrath/armory" or path.startswith("/wrath/armory/")


class _PageCache:
    def __init__(self):
        self.lock, self.d = threading.Lock(), collections.OrderedDict()

    def get(self, key):
        with self.lock:
            v = self.d.get(key)
            if v and time.monotonic() - v[0] < PAGE_TTL:
                return v[1]
            return None

    def put(self, key, val):
        with self.lock:
            self.d[key] = (time.monotonic(), val)
            self.d.move_to_end(key)
            while len(self.d) > PAGE_CACHE_MAX:
                self.d.popitem(last=False)


_pages = _PageCache()


def page(path: str, query: dict, css: str, card_meta, realm_name: str, public_host: str,
         st: Store | None = None) -> tuple[int, bytes]:
    """(status, page) for a path match() owns. Never raises."""
    st = st or store
    try:
        st.refresh()
        if path == "/wrath/armory":
            q = clean_query((query.get("q") or [""])[0])
            key = ("i", q, bool((query.get("q") or [""])[0]), st.key)
            hit = _pages.get(key) if st is store else None
            if hit is None:
                hit = (200, index_page(query, css, card_meta, realm_name, st))
                if st is store:
                    _pages.put(key, hit)
            return hit
        name = path[len("/wrath/armory/"):]
        key = ("c", name.lower(), st.key)
        hit = _pages.get(key) if st is store else None
        if hit is None:
            hit = char_page(name, css, card_meta, realm_name, public_host, st)
            if st is store:
                _pages.put(key, hit)
        return hit
    except Exception:  # noqa: BLE001: never a stack trace to a visitor
        return 503, _page("Armory", '<section class="ly-panel"><h2>Armory</h2><p class="ly-fine">'
                          'The armory isn\'t available right now.</p></section>', css, "")


def search_query(path: str, query: dict) -> bool:
    """True when the request is a search (the portal gives those a tighter rate limit)."""
    return path == "/wrath/armory" and bool((query.get("q") or [""])[0])
