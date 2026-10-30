"""Short public share links for the Wrath portal (stream/wrath_portal.py), with link-preview cards.

    GET /r/<realm slug or id>   a realm (the official one, or a community realm from the Beacons listing)
    GET /h/<hangout>            a Dalaran hangout
    GET /q/<dungeon or queue>   a Dungeon Finder queue (a dungeon id such as 258, or a queue slug)
    GET /b/<raid or wing>       a boss fight: a raid or one of its wings (stream/modes_data.py ids)
    GET /m/<mod id>             a mod (its real name and description from the Workshop catalog, stream/workshop.py)
    GET /w/<workshop id>        something players made (a course, a mode or a build: stream/creations.py), with Play
    GET /u/<character>          a player profile (with the web armory, stream/armory.py, the card shows the
                                real character: "Name, level 80 Blood Elf Paladin", and links its sheet)

The same links also answer under /wrath (/wrath/r/<id> ...), which the site's proxy already sends here.

Each one is a small public page: Open Graph and X card tags (wrath_portal.card_meta, the 1200 x 630
wu-card.webp image), a line about what was shared, and a refresh plus a button on to the play page with
a deep link:

    /wrath?go=<kind>:<id>      kind is one of r h q b m u w; id passed the same allow-list as the link

Examples: /q/258 -> /wrath?go=q:258, /u/Arthas -> /wrath?go=u:Arthas, /h/krasus-landing ->
/wrath?go=h:krasus-landing. The go value only ever holds [A-Za-z0-9._-] after the colon, so it needs no
escaping in a URL, but it is still percent-quoted and HTML-escaped on the way out. A page that reads
?go= must check it again with the same rules (stream/www-files/wrath-page.js goLink()).

A malformed link (bad characters, too long, unknown kind) or an id nobody knows still gets the generic
card and a plain link to /wrath: never an error page. Nothing here raises to the caller.

Standard library only. The portal is deployed as a single file next to this one; when this file is
missing the portal simply doesn't answer these links.
"""
from __future__ import annotations

import html
import re
import urllib.parse

# kind -> (allow-list for the id, what the card calls it)
KINDS = {
    "r": (re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"), "Realm"),
    "h": (re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"), "Dalaran hangout"),
    "q": (re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"), "Dungeon Finder"),
    "b": (re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$"), "Boss fight"),
    "m": (re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"), "Mod"),   # mods/wu-mod.py ID_RE, 3-32 long
    "u": (re.compile(r"^[A-Za-z]{2,12}$"), "Player"),               # a 3.3.5a character name
    "w": (re.compile(r"^[1-9][0-9]{0,8}$"), "Workshop"),            # a Workshop item id (ov_workshop.lua)
}
ID_LEN = {"m": (3, 32)}
MAX_PATH = 80
PREFIXES = ("/wrath/", "/")
_PATH_RE = re.compile(r"^/(?:wrath/)?([a-z])(?:/(.*))?$")
_DESC = {
    "r": "Join this realm on the Leyline network, right in your browser.",
    "h": "Meet up in Dalaran on the Leyline network, right in your browser.",
    "q": "Queue up together on Wrath, the Leyline network's browser realm.",
    "b": "A boss fight on Wrath, the Leyline network's browser realm. Gather a raid and go.",
    "m": "A community mod for Wrath on the Leyline network.",
    "u": "A player on Wrath, the Leyline network's browser realm.",
    "w": "Made by a player on Wrath. Press Play and it starts in your browser.",
}


# Known names for ids, filled by the portal from stream/modes_data.py: {"q:deadmines": "The Deadmines", ...}.
# An id missing here still gets a card, from the id itself.
NAMES: dict = {}


def match(path: str) -> bool:
    """True for any path these links own (/r, /r/..., /wrath/q/...), valid or not, so the portal sends
    them all to share_page() and a bad one gets the generic card instead of a 404."""
    m = _PATH_RE.fullmatch(path or "")
    return bool(m and m.group(1) in KINDS)


def parse(path: str) -> tuple[str, str] | None:
    """(kind, id) for a well-formed share link, else None. The id is matched as sent: no unquoting,
    no case folding, no trimming beyond the portal's trailing-slash strip."""
    if not isinstance(path, str) or len(path) > MAX_PATH:
        return None
    m = _PATH_RE.fullmatch(path)
    if not m or m.group(1) not in KINDS or m.group(2) is None:
        return None
    kind, ident = m.group(1), m.group(2)
    rx = KINDS[kind][0]
    lo, hi = ID_LEN.get(kind, (1, 32))
    if not (lo <= len(ident) <= hi) or not rx.fullmatch(ident):
        return None
    return kind, ident


def go_value(kind: str, ident: str) -> str:
    return f"{kind}:{ident}"


def deep_link(kind: str, ident: str) -> str:
    """/wrath?go=<kind>:<id>, for an already-validated pair."""
    return "/wrath?go=" + urllib.parse.quote(go_value(kind, ident), safe=":")


def check_go(value) -> tuple[str, str] | None:
    """The reverse of go_value, with the same rules: (kind, id) or None. For pages that read ?go=."""
    if not isinstance(value, str) or ":" not in value or len(value) > 40:
        return None
    kind, ident = value.split(":", 1)
    return parse(f"/{kind}/{ident}")


def _pretty(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-") if w)


def describe(kind: str, ident: str, realm_name: str, realms=None, who=None, mods=None, made=None) -> tuple[str, str, str]:
    """(card title, card description, the line on the page) for a valid link. realms is a callable
    giving the community realm list ([{"id", "name", "tagline"}...]); who(name) gives a character in the
    armory ({"name", "line"}) or None; mods(id) gives one Workshop entry ({"name", "description"}) or
    None (stream/workshop.py Workshop.mod); made(id) gives one Workshop item ({"title", "kind", "author"},
    stream/creations.py card_item) or None; any failure falls back to generic."""
    label = KINDS[kind][1]
    desc = _DESC[kind]
    if kind == "r":
        if ident in (realm_name.lower(), "official", "wrath", "wrathunleashed"):   # the old name's links keep working
            return f"{realm_name} · Leyline", "The official Wrath realm on the Leyline network. Play in your browser.", \
                f"{realm_name}, the official realm"
        try:
            for r in (realms() if realms else ([], False))[0]:
                if r.get("id") == ident:
                    name = str(r.get("name") or "A community realm")[:32]
                    tag = str(r.get("tagline") or "")[:80]
                    return f"{name} · Leyline realm", (tag + " " if tag else "") + desc, f"{name}, a community realm"
        except Exception:   # a broken listing never breaks a link
            pass
        return f"Realm {ident} · Leyline", desc, f"realm {ident}"
    known = NAMES.get(f"{kind}:{ident}")
    if known and kind in ("q", "b", "h"):
        name = str(known)[:64]
        if kind == "q" and ident.isdigit():   # a Dungeon Finder id keeps its number in the title
            return f"{label}: {ident} · {realm_name}", desc, name
        return f"{name} · {realm_name}", desc, name
    if kind == "b":
        return f"{label}: {_pretty(ident)} · {realm_name}", desc, f"the {_pretty(ident)} boss fight"
    if kind == "q":
        what = f"Dungeon Finder queue {ident}" if ident.isdigit() else f"the {_pretty(ident)} queue"
        return f"{label}: {_pretty(ident) if not ident.isdigit() else ident} · {realm_name}", desc, what
    if kind == "u":
        got = _who(who, ident)
        if got:
            name, line = got
            return (f"{name} · {realm_name}", f"{name}, {line}. {desc}", f"{name}, {line}")
        return f"{ident} · {realm_name}", desc, f"{ident}'s profile"
    if kind == "m":
        try:
            m = mods(ident) if mods else None
            if m:
                name = str(m.get("name") or _pretty(ident))[:48]
                about = str(m.get("description") or "").strip()[:200]
                return f"{label}: {name} · Leyline", (about + " " if about else "") + desc, f"the {name} mod"
        except Exception:   # a broken catalog never breaks a link
            pass
        return f"{label}: {_pretty(ident)} · Leyline", desc, f"the {_pretty(ident)} mod"
    if kind == "w":
        try:
            it = made(ident) if made else None
            if it:
                title = str(it.get("title") or "")[:48]
                what = str(it.get("kind") or "item").lower()[:24]
                author = str(it.get("author") or "")[:12]
                if title:
                    return (f"{title} · Workshop · {realm_name}", f"A {what} by {author}. " + desc,
                            f"{title}, a {what} by {author}")
        except Exception:   # a broken listing never breaks a link
            pass
        return f"Workshop item {ident} · {realm_name}", desc, f"Workshop item {ident}"
    return f"{_pretty(ident)} · {label}", desc, f"the {_pretty(ident)} hangout in Dalaran"


def _who(who, ident: str) -> tuple[str, str] | None:
    """(canonical name, "level 80 Blood Elf Paladin") from the armory, or None (not there, opted out, a bot,
    no armory, or anything odd: the generic card then)."""
    if who is None:
        return None
    try:
        got = who(ident)
    except Exception:
        return None
    if not isinstance(got, dict):
        return None
    name, line = got.get("name"), got.get("line")
    if not (isinstance(name, str) and KINDS["u"][0].fullmatch(name) and name.lower() == ident.lower()):
        return None
    if not (isinstance(line, str) and re.fullmatch(r"[A-Za-z0-9 ]{1,60}", line)):
        return None
    return name, line


def share_page(path: str, card_meta, render, realm_name: str = "WrathUnleashed", realms=None, who=None,
               mods=None, made=None) -> bytes:
    """The share page for path. card_meta(path, title) and render(body, meta=...) are the portal's own;
    who(name) gives an armory character for /u/<name>, mods(id) a Workshop entry for /m/<id>.
    Always returns a page: an unknown or malformed link gets the generic card and a link to /wrath."""
    e = html.escape
    got = None
    try:
        got = parse(path)
    except Exception:
        got = None
    if got:
        kind, ident = got
        try:
            title, desc, line = describe(kind, ident, realm_name, realms, who, mods, made)
        except Exception:
            title, desc, line = f"{realm_name} · Leyline", _DESC[kind], "a link"
        target = deep_link(kind, ident)
        canon = f"/{kind}/{ident}" if not path.startswith("/wrath/") else f"/wrath/{kind}/{ident}"
    else:
        title, desc, line, target, canon = "", "", "", "/wrath", "/wrath"
    meta = card_meta(canon, title)
    if desc:
        # card_meta carries the shared CARD_DESCRIPTION; a share link says what was shared instead.
        meta = _swap_description(meta, desc)
    meta += f'<meta http-equiv="refresh" content="1;url={e(target)}">'
    shared = (f'<p class="sub">Someone shared {e(line)} with you.</p>' if line
              else '<p class="sub">Play Wrath in your browser, on the Leyline network.</p>')
    sheet = ""
    if got and got[0] == "u":
        found = _who(who, got[1])
        if found:
            sheet = f'<p class="center"><a href="/wrath/armory/{e(found[0])}">See {e(found[0])} in the armory</a></p>'
    if got and got[0] == "m":
        try:
            if mods and mods(got[1]):
                sheet = f'<p class="center"><a href="/wrath/mods/{e(got[1])}">See it in the Workshop</a></p>'
        except Exception:
            sheet = ""
    if got and got[0] == "w":
        try:
            if made and made(got[1]):
                sheet = f'<p class="center"><a href="/wrath/workshop/{e(got[1])}">See it in the Workshop</a></p>'
        except Exception:
            sheet = ""

    body = (f'<div class="crest wu-brand"><h1>{e(title or realm_name)}</h1></div>{shared}'
            '<hr class="rule wu-divider">'
            f'<p class="center"><a class="btn primary" href="{e(target)}">Open in Wrath</a></p>{sheet}'
            '<p class="fine center">Taking you there now. Nothing to install: it runs in your browser '
            '(or with your own 3.3.5a game files).</p>')
    page = render(body, meta=meta).decode("utf-8")
    if title:   # the tab title says what was shared too
        page = re.sub(r"<title>[^<]*</title>", lambda _m: f"<title>{e(title)}</title>", page, count=1)
    return page.encode("utf-8")


def _swap_description(meta: str, desc: str) -> str:
    """Put desc in the description tags of card_meta's output (all of them, already escaped)."""
    d = html.escape(desc)
    return re.sub(r'((?:name="description"|property="og:description"|name="twitter:description") content=")[^"]*(")',
                  lambda m: m.group(1) + d + m.group(2), meta)
