"""The Leyline Workshop on the web: what players made on the realm, for stream/wrath_portal.py.

    GET /wrath/workshop              public: the approved courses, modes and builds, with title, kind, author,
                                     plays and rating; ?kind=course|mode|build, ?sort=plays|rating|new, ?page=N
    GET /wrath/workshop/<id>         public: one item, with a Play button
    (share link /wrath/w/<id>, stream/links.py kind "w")

Play is a plain link to /wrath?go=w:<id>. The portal checks it (links.check_go) and, once the player is signed in,
records it on the realm with one console command over SOAP (remember_go -> go_intent here):

    ovws go <ACCOUNT> <id>

realm/custom/lua_scripts/ov_workshop.lua plays the item when that account is in the world (at once if online, else
at the next login, within 30 minutes): a course starts where the character stands with the party invited, a mode
is hosted, a build is pasted in the build area. The realm checks the id again (approved items only).

The data is a file only, like the armory: realm/custom/workshop-export.py (cron on the host, every 5 minutes)
writes the approved items to <WU_WORKSHOP_ITEMS_DIR>/items.json (default /app/workshop, which is
/srv/wrath/portal/workshop on the host). The portal never reaches the database. Every field is checked again
here: an id, a known kind, a title of plain characters, an author that is a character name (nothing else about
a player is in the file), whole numbers. Pages have no script (the site's CSP is script-src 'none').

Standard library only; when this file is missing the portal simply has no Workshop pages.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time

DATA_DIR = os.environ.get("WU_WORKSHOP_ITEMS_DIR", "/app/workshop")
MAX_FILE = 4_000_000
MAX_ITEMS = 5000
PAGE = 25
STAT_EVERY = 5.0
ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")
TITLE_BAD = re.compile(r"[^A-Za-z0-9 \-!&.,?:()]")
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
KINDS = {"course": ("Course", "Minigolf course"), "mode": ("Mode", "Mode"), "build": ("Build", "Build")}
KIND_ORDER = ("course", "mode", "build")
SORTS = {"plays": "Most played", "rating": "Top rated", "new": "New"}
HOW = {"course": "Starts where you stand and invites your party.",
       "mode": "Hosted where you stand; your party nearby is invited.",
       "build": "Pasted where you stand, in a build area (builders only)."}

e = html.escape


def _n(v, lo=0, hi=2**31 - 1):
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if lo <= v <= hi else None


def _text(v, n: int) -> str:
    if not isinstance(v, str):
        return ""
    return re.sub(r" +", " ", TITLE_BAD.sub("", re.sub(r"\s", " ", v))).strip()[:n]


def clean_item(r) -> dict | None:
    """One exported item with every field checked, or None."""
    if not isinstance(r, dict):
        return None
    iid = _n(r.get("id"), 1, 999_999_999)
    kind = r.get("kind")
    author = r.get("author")
    if iid is None or kind not in KINDS or not (isinstance(author, str) and NAME_RE.fullmatch(author)):
        return None
    title = _text(r.get("title"), 48)
    if not title:
        return None
    nums = {k: _n(r.get(k)) for k in ("version", "created", "plays", "up", "down")}
    if any(v is None for v in nums.values()):
        return None
    return {"id": iid, "kind": kind, "title": title, "author": author, "descr": _text(r.get("descr"), 160),
            "version": max(1, nums["version"]), **{k: nums[k] for k in ("created", "plays", "up", "down")}}


class Store:
    """items.json, read again when it changes."""

    def __init__(self, root: str = DATA_DIR):
        self.root = root
        self.lock = threading.Lock()
        self.checked = 0.0
        self.key = None
        self.updated = 0
        self.items: list[dict] = []
        self.by_id: dict[int, dict] = {}

    def refresh(self) -> None:
        now = time.monotonic()
        with self.lock:
            if self.key is not None and now - self.checked < STAT_EVERY:
                return
            self.checked = now
            p = os.path.join(self.root, "items.json")
            try:
                st = os.stat(p)
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                key = ("missing",)
            if key == self.key:
                return
            self.key = key
            doc = None
            if key != ("missing",):
                try:
                    with open(p, "rb") as f:
                        b = f.read(MAX_FILE + 1)
                    doc = json.loads(b.decode("utf-8")) if len(b) <= MAX_FILE else None
                except (OSError, ValueError, UnicodeDecodeError):
                    doc = None
            items, by_id = [], {}
            raw = doc.get("items") if isinstance(doc, dict) and isinstance(doc.get("items"), list) else []
            for r in raw[:MAX_ITEMS]:
                it = clean_item(r)
                if it and it["id"] not in by_id:
                    by_id[it["id"]] = it
                    items.append(it)
            self.items, self.by_id = items, by_id
            self.updated = (_n(doc.get("updated")) or 0) if isinstance(doc, dict) else 0

    def item(self, iid) -> dict | None:
        """One approved item by id (an int, or the digits of a path), else None."""
        if isinstance(iid, str):
            if not ID_RE.fullmatch(iid):
                return None
            iid = int(iid)
        if _n(iid, 1) is None:
            return None
        self.refresh()
        return self.by_id.get(iid)

    def listing(self, kind: str, sort: str) -> list[dict]:
        self.refresh()
        l = [it for it in self.items if kind == "all" or it["kind"] == kind]
        if sort == "rating":
            l.sort(key=lambda it: (-(it["up"] - it["down"]), -it["up"], -it["id"]))
        elif sort == "new":
            l.sort(key=lambda it: (-it["created"], -it["id"]))
        else:
            l.sort(key=lambda it: (-it["plays"], -it["id"]))
        return l


store = Store()


def match(path: str) -> bool:
    return path == "/wrath/workshop" or (path or "").startswith("/wrath/workshop/")


def play_href(iid: int) -> str:
    return f"/wrath?go=w:{int(iid)}"


def card_item(iid) -> dict | None:
    """For the share link card (stream/links.py, kind "w"): {"title", "kind", "author"} or None."""
    it = store.item(iid)
    return {"title": it["title"], "kind": KINDS[it["kind"]][1], "author": it["author"]} if it else None


WS_CSS = """
.ws-bar{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:10px 0}
.ws-bar a{font:600 13px/1 system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;text-decoration:none;color:var(--ly-ink);
padding:9px 13px;border:1px solid var(--ly-line);border-radius:999px;background:rgba(20,24,60,.6)}
.ws-bar a[aria-current]{border-color:var(--ly-cyan);color:#bff6ff;box-shadow:var(--ly-glow)}
.ws-bar a:hover,.ws-bar a:focus-visible{border-color:var(--ly-cyan)}
.ws-play{display:inline-block;padding:8px 16px;font:600 14px/1 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;
text-decoration:none;color:#1a1030;background:linear-gradient(180deg,#9ff0ff,var(--ly-cyan));border:1px solid #9ff0ff;border-radius:6px}
.ws-play:hover,.ws-play:focus-visible{box-shadow:var(--ly-glow)}
.ws-play.big{padding:14px 28px;font-size:17px}
.ws-up{color:#8fe36b}.ws-down{color:#ff8a8a}
.ws-pages{display:flex;gap:14px;justify-content:center;margin:12px 0}
.ws-item{text-align:center}
.ws-item dl{display:grid;grid-template-columns:auto auto;gap:6px 14px;justify-content:center;margin:14px 0}
.ws-item dt{color:var(--ly-dim)}.ws-item dd{margin:0;text-align:left}
.ws-item code{word-break:break-all}
"""


def _page(title: str, body: str, css: str, meta: str) -> bytes:
    """The page; the site's nav and footer are put in by the portal (wrath_portal.site_chrome)."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{e(title)}</title>{meta}<style>{css}{WS_CSS}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div><div class="ly-wrap">{body}</div></body></html>').encode("utf-8")


def _rating(it: dict) -> str:
    return (f'<span class="ws-up" aria-label="{it["up"]} thumbs up">+{it["up"]}</span> '
            f'<span class="ws-down" aria-label="{it["down"]} thumbs down">-{it["down"]}</span>')


def _q(kind: str, sort: str, page: int = 1) -> str:
    parts = []
    if kind != "all":
        parts.append(f"kind={kind}")
    if sort != "plays":
        parts.append(f"sort={sort}")
    if page > 1:
        parts.append(f"page={page}")
    return "/wrath/workshop" + ("?" + "&".join(parts) if parts else "")


def _arg(query: dict, name: str) -> str:
    v = (query.get(name) or [""])[0]
    return v if isinstance(v, str) else ""


def _footer(st: Store) -> str:
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(st.updated)) if st.updated else "not yet"
    return ('<p class="ly-fine">Made by players on this realm and checked by a GM. Updated every 5 minutes (last: '
            + e(when) + '). Play opens the game in your browser; nothing to install and nothing to buy. '
            'Make your own: <a href="/wrath/docs">the docs</a>, or in game <code>/golf edit</code>, '
            '<code>/modes edit</code> and <code>/builder</code>.</p>')


def index_page(query: dict, css: str, card_meta, realm_name: str, st: Store | None = None) -> bytes:
    st = st or store
    kind = _arg(query, "kind")
    kind = kind if kind in KINDS else "all"
    sort = _arg(query, "sort")
    sort = sort if sort in SORTS else "plays"
    raw_page = _arg(query, "page")
    page = int(raw_page) if raw_page.isdigit() and 0 < len(raw_page) <= 4 else 1
    items = st.listing(kind, sort)
    pages = max(1, -(-len(items) // PAGE))
    page = min(max(1, page), pages)
    shown = items[(page - 1) * PAGE: page * PAGE]

    def tab(k, label, cur, href):
        return f'<a href="{e(href)}"' + (' aria-current="page"' if k == cur else "") + f'>{e(label)}</a>'
    kinds = "".join(tab(k, lab, kind, _q(k, sort)) for k, lab in
                    [("all", "All")] + [(k, KINDS[k][0] + "s") for k in KIND_ORDER])
    sorts = "".join(tab(s, lab, sort, _q(kind, s)) for s, lab in SORTS.items())
    parts = ['<header class="ly-hero"><h1>Workshop</h1>'
             f'<p class="ly-lede">Minigolf courses, modes and builds that players made on {e(realm_name)}. '
             'Pick one and press Play: it starts in the game, in your browser.</p>'
             f'<span class="ly-ver">{len(st.items)} item{"" if len(st.items) == 1 else "s"}</span></header>',
             f'<nav class="ws-bar" aria-label="Kind">{kinds}</nav><nav class="ws-bar" aria-label="Sort">{sorts}</nav>']
    if shown:
        rows = "".join(
            f'<tr><td class="name"><a href="/wrath/workshop/{it["id"]}">{e(it["title"])}</a>'
            f'<span class="sub">{e(KINDS[it["kind"]][0])} by {e(it["author"])}'
            f'{" · " + e(it["descr"][:80]) if it["descr"] else ""}</span></td>'
            f'<td>{it["plays"]} play{"" if it["plays"] == 1 else "s"}</td><td>{_rating(it)}</td>'
            f'<td><a class="ws-play" href="{e(play_href(it["id"]))}" aria-label="Play {e(it["title"])}">Play</a></td></tr>'
            for it in shown)
        parts.append('<section class="ly-panel" aria-labelledby="ws-h"><h2 id="ws-h">'
                     + e("Everything" if kind == "all" else KINDS[kind][0] + "s") + '</h2>'
                     '<table class="ly-table"><thead><tr><th>Title</th><th>Plays</th><th>Rating</th><th></th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></section>')
        if pages > 1:
            nav = []
            if page > 1:
                nav.append(f'<a href="{e(_q(kind, sort, page - 1))}" rel="prev">Previous</a>')
            nav.append(f'<span>Page {page} of {pages}</span>')
            if page < pages:
                nav.append(f'<a href="{e(_q(kind, sort, page + 1))}" rel="next">Next</a>')
            parts.append(f'<nav class="ws-pages" aria-label="Pages">{"".join(nav)}</nav>')
    else:
        parts.append('<section class="ly-panel"><h2>Nothing here yet</h2><p class="ly-fine">Be the first: build a minigolf '
                     'course (<code>/golf edit</code>), write a mode (<code>/modes edit</code>) or share a build '
                     '(<code>.build share</code>, then <code>.workshop publish</code>).</p></section>')
    parts.append(_footer(st))
    title = "Workshop · " + realm_name
    return _page(title, "".join(parts), css, card_meta(_q(kind, sort, page) if page > 1 or kind != "all" or sort != "plays"
                                                       else "/wrath/workshop", title))


def item_page(raw: str, css: str, card_meta, realm_name: str, public_host: str, st: Store | None = None) -> tuple[int, bytes]:
    st = st or store
    it = st.item(raw)
    if not it:
        return 404, _page("Not in the Workshop", '<section class="ly-panel"><h2>Not in the Workshop</h2>'
                          '<p class="ly-fine">That item isn\'t in the Workshop (yet, or any more). '
                          '<a href="/wrath/workshop">See everything</a>.</p></section>', css, "")
    made = time.strftime("%Y-%m-%d", time.gmtime(it["created"])) if it["created"] else ""
    share = f"https://{public_host}/wrath/w/{it['id']}"
    body = ('<article class="ly-panel ws-item">'
            f'<h1>{e(it["title"])}</h1>'
            f'<p class="ly-lede">{e(KINDS[it["kind"]][1])} by {e(it["author"])}</p>'
            + (f'<p>{e(it["descr"])}</p>' if it["descr"] else "")
            + f'<p><a class="ws-play big" href="{e(play_href(it["id"]))}">Play</a></p>'
            f'<p class="ly-fine">{e(HOW[it["kind"]])} You sign in first if you haven\'t.</p>'
            '<dl>'
            f'<dt>Plays</dt><dd>{it["plays"]}</dd>'
            f'<dt>Rating</dt><dd>{_rating(it)}</dd>'
            f'<dt>Version</dt><dd>{it["version"]}</dd>'
            + (f'<dt>Published</dt><dd>{e(made)}</dd>' if made else "")
            + f'<dt>Share</dt><dd><code>{e(share)}</code></dd>'
            '</dl>'
            f'<p>In game: <code>.workshop play {it["id"]}</code>, or Esc &gt; Mods &amp; Workshop &gt; Workshop.</p>'
            '<p><a href="/wrath/workshop">Everything in the Workshop</a></p></article>' + _footer(st))
    title = f"{it['title']} · Workshop · {realm_name}"
    return 200, _page(title, body, css, card_meta(f"/wrath/workshop/{it['id']}", title))


def page(path: str, query: dict, css: str, card_meta, realm_name: str, public_host: str,
         st: Store | None = None) -> tuple[int, bytes]:
    """(status, page) for a path match() owns. Never raises."""
    st = st or store
    try:
        st.refresh()
        if path == "/wrath/workshop":
            return 200, index_page(query, css, card_meta, realm_name, st)
        return item_page(path[len("/wrath/workshop/"):], css, card_meta, realm_name, public_host, st)
    except Exception:  # noqa: BLE001: never a stack trace to a visitor
        return 503, _page("Workshop", '<section class="ly-panel"><h2>Workshop</h2><p class="ly-fine">'
                          'The Workshop isn\'t available right now.</p></section>', css, "")


# ------------------------------------------------------------------------------------------ the go intent

def go_command(account: str, iid: str) -> str | None:
    """The console command, or None when the account or the id is not allowed."""
    if not isinstance(account, str) or not ACCOUNT_RE.fullmatch(account):
        return None
    if not isinstance(iid, str) or not ID_RE.fullmatch(iid):
        return None
    return f"ovws go {account.upper()} {int(iid)}"


_recent: dict = {}
_recent_lock = threading.Lock()
REPEAT_S = 120


def go_intent(soap, account: str, iid: str, log=None) -> bool:
    """Record "play item <id>" for the account on the realm. soap(command) -> reply text (raises on failure).
    True when the realm confirmed ("ovws ok"); never raises: a failed go never stops anyone playing."""
    cmd = go_command(account, iid)
    if not cmd:
        return False
    now = time.monotonic()
    key = account.upper()
    with _recent_lock:
        last = _recent.get(key)
        if last and last[0] == iid and now - last[1] < REPEAT_S:
            return True
    try:
        text = soap(cmd) or ""
    except Exception as ex:  # noqa: BLE001
        if log:
            log.warning("workshop go %s %s failed: %s", key, iid, getattr(ex, "kind", type(ex).__name__))
        return False
    ok = "ovws ok" in text
    if ok:
        with _recent_lock:
            _recent[key] = (iid, now)
            if len(_recent) > 20000:
                _recent.clear()
    elif log:
        log.warning("workshop go %s %s: the realm did not confirm (is ov_workshop.lua loaded?)", key, iid)
    return ok
