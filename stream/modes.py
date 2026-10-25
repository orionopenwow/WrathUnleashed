"""The Modes hub (GET /wrath/modes) and the go-anywhere intent, for stream/wrath_portal.py.

  /wrath/modes   a public page in the Leyline look: Duels, Boss fights (every raid, by region, and by
                 wing where it has wings), Dungeons (every 5-player dungeon, plus the random queues) and
                 Hangouts (Dalaran, the Goldshire Inn). Every card has one link, a share link of
                 stream/links.py (/wrath/h/<id>, /wrath/q/<id>, /wrath/b/<id>), which carries
                 ?go=<kind>:<id> through sign-in to the game.

  go intent      when a signed-in player arrives with ?go=, the portal calls go_intent(): one console
                 command over SOAP,
                     ovgo set <ACCOUNT> <kind>:<id>
                 handled by realm/custom/lua_scripts/ov_go.lua, which acts on that account's next login (or
                 at once if it is online) and forgets it after 30 minutes. Only ids in stream/modes_data.py
                 are sent; ov_go.lua checks them again against its own copy of the same table.

All the data (map ids, entrances, levels, names) is in stream/modes_data.py. Standard library only; both
files are loaded from beside the portal and nothing here raises to the caller.
"""
from __future__ import annotations

import html
import importlib.util
import os
import re
import threading
import time


def _load_data():
    spec = importlib.util.spec_from_file_location(
        "wu_modes_data", os.path.join(os.path.dirname(os.path.abspath(__file__)), "modes_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


data = _load_data()
PLACES = data.places()
GO_RE = re.compile(r"^[hqb]:[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")

# The owner's screenshots (stream/www-files/art, served by the portal's /wrath/art/<name>). A missing one
# leaves the segment's painted fallback: no broken image.
SHOTS = {
    "duels": ("leyline-shot-city.webp", "A city street on Wrath"),
    "bosses": ("leyline-shot-dalaran.webp", "Dalaran on Wrath"),
    "dungeons": ("leyline-shot-durotar.webp", "Durotar on Wrath"),
    "hangouts": ("leyline-shot-start.webp", "A starting area on Wrath"),
}
SHOT_NAMES = tuple(n for n, _ in SHOTS.values())

MODES_CSS = """
.md-jump{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:18px 0 6px}
.md-jump a{font:600 13px/1 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;text-decoration:none;color:var(--ly-ink);
padding:10px 14px;border:1px solid var(--ly-line);border-radius:999px;background:rgba(20,24,60,.6)}
.md-jump a:hover,.md-jump a:focus-visible{border-color:var(--ly-cyan);box-shadow:var(--ly-glow)}
.md-shot{position:relative;height:clamp(140px,26vw,240px);margin:-4px 0 16px;border-radius:6px;border:1px solid var(--ly-line);overflow:hidden;
background:radial-gradient(60% 80% at 30% 20%,rgba(140,90,255,.35),transparent 70%),radial-gradient(50% 70% at 80% 60%,rgba(60,200,255,.25),transparent 70%),#0b0e26}
.md-shot img{display:block;width:100%;height:100%;object-fit:cover}
.md-lede{max-width:720px;margin:0 auto 14px;text-align:center;color:var(--ly-ink)}
.md-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.md-card{display:flex;flex-direction:column;gap:6px;background:rgba(18,22,54,.7);border:1px solid var(--ly-line);border-radius:6px;padding:14px}
.md-card h3,.md-raid h3{margin:0;font:600 19px/1.15 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--ly-cyan)}
.md-card p{margin:0;color:var(--ly-ink);font-size:14px}
.md-tags{display:flex;flex-wrap:wrap;gap:6px}
.md-tag{font:600 11px/1 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--ly-dim);border:1px solid var(--ly-line);border-radius:999px;padding:4px 8px}
.md-tag.bots{color:#5ef0a0;border-color:rgba(94,240,160,.45)}
.md-go{align-self:flex-start;margin-top:auto;font:600 14px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.12em;text-transform:uppercase;
text-decoration:none;color:#1a1030!important;background:linear-gradient(180deg,#9ff0ff,var(--ly-cyan));border:1px solid #9ff0ff;border-radius:4px;padding:8px 14px}
.md-go:hover,.md-go:focus-visible{box-shadow:var(--ly-glow)}
.md-region{margin:22px 0 10px;font:600 13px/1 system-ui,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--ly-violet);text-align:center}
.md-region span{color:var(--ly-dim);letter-spacing:.06em;text-transform:none;font-weight:400}
.md-raid{background:rgba(18,22,54,.7);border:1px solid var(--ly-line);border-radius:6px;padding:14px;margin:0 0 12px}
.md-raid .top{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between;margin-bottom:8px}
.md-raid .md-cards{grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
.md-raid .md-card{background:rgba(10,12,34,.6)}
.md-raid .md-card h3{font-size:16px}
.md-bosses{margin:0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:4px 10px;font-size:13px;color:var(--ly-dim)}
.md-bosses li::after{content:"\\00b7";margin-left:10px;color:var(--ly-line)}.md-bosses li:last-child::after{content:""}
.md-hint{font-size:13px;color:var(--ly-dim);margin:8px 0 0}
.md-steps{margin:8px 0 0;padding-left:1.2rem}.md-steps li{margin:4px 0}
.ly code{background:rgba(5,6,20,.8);border:1px solid var(--ly-line);border-radius:4px;padding:1px 5px}
"""


def _tag(text: str, cls: str = "") -> str:
    return f'<span class="md-tag{" " + cls if cls else ""}">{html.escape(text)}</span>'


def _levels(lv) -> str:
    lo, hi = lv
    return f"Level {lo}" if lo == hi else f"Levels {lo}-{hi}"


_host = {"name": "play.openvanilla.app"}   # the public host, for the full link in a Share box (set by page())


def _share(href: str) -> str:
    """A Share box with no script (the page allows none): it opens on the full link, which one tap selects."""
    url = html.escape(f'https://{_host["name"]}{href}')
    return (f'<details class="ly-share"><summary>Share</summary><code tabindex="0">{url}</code>'
            '<small>Tap the link to select it, then copy. It opens with a preview card.</small></details>')


def _card(name: str, line: str, tags: list[str], href: str, go_label: str = "Go") -> str:
    e = html.escape
    return (f'<div class="md-card"><h3>{e(name)}</h3>'
            + (f'<p>{e(line)}</p>' if line else "")
            + f'<div class="md-tags">{"".join(tags)}</div>'
            f'<a class="md-go" href="{e(href)}">{e(go_label)}</a>{_share(href)}</div>')


def _shot(key: str, art_url, have) -> str:
    name, alt = SHOTS[key]
    img = ""
    try:
        ok = bool(have(name))
    except Exception:
        ok = False
    if ok:
        img = (f'<img src="{html.escape(art_url(name))}" alt="{html.escape(alt)}" width="1280" height="720" '
               'loading="lazy" decoding="async">')
    return f'<div class="md-shot">{img}</div>'


def link(kind: str, ident: str) -> str:
    return f"/wrath/{kind}/{ident}"


def page(css: str, art_url, have, card_meta, realm_name: str = "WrathUnleashed",
         public_host: str = "play.openvanilla.app") -> bytes:
    """The /wrath/modes page. css is the portal's LEYLINE_CSS with its art filled in, art_url(name) the
    art route, have(name) whether that art file is there, card_meta(path, title) the link-preview tags,
    public_host the site's name for the full links in the Share boxes. The site's nav and footer are put
    in by the portal (wrath_portal.site_chrome)."""
    e = html.escape
    D = data
    _host["name"] = public_host
    regions = {k: (n, sub) for k, n, sub in D.EXPANSIONS}

    # Duels
    duel = D.DUEL
    duels = (
        '<section class="ly-panel" id="duels" aria-labelledby="md-duels"><h2 id="md-duels">Duels</h2>'
        + _shot("duels", art_url, have)
        + '<p class="md-lede">The duel spot is in the Dalaran hangout. Go there, find someone, and '
        'challenge them: target them and type <code>/duel</code>, or right-click their portrait and pick Duel. '
        'Either of you can say no. Type <code>.wu</code> in game for every realm command.</p>'
        '<div class="md-cards">'
        + _card(duel["name"], duel["line"], [_tag(duel["tag"]), _tag("Players only")], link("h", duel["id"]), "Go duel")
        + '</div></section>')

    # Boss fights
    raids_html = []
    for key, _n, _s in D.EXPANSIONS:
        rows = [r for r in D.RAIDS if r["exp"] == key]
        if not rows:
            continue
        name, sub = regions[key]
        raids_html.append(f'<h3 class="md-region">{e(name)} <span>· raids</span></h3>')
        for r in rows:
            tags = [_tag(f"Level {r['level']}"), _tag(f"{r['size']} players")]
            head = (f'<div class="top"><h3>{e(r["name"])}</h3><div class="md-tags">{"".join(tags)}</div>'
                    f'<a class="md-go" href="{e(link("b", r["id"]))}">Go</a>{_share(link("b", r["id"]))}</div>')
            if r.get("wings"):
                wings = "".join(
                    '<div class="md-card">'
                    f'<h3>{e(w["name"])}</h3>'
                    '<ul class="md-bosses">' + "".join(f"<li>{e(b)}</li>" for b in w["bosses"]) + "</ul>"
                    f'<a class="md-go" href="{e(link("b", w["id"]))}">Go</a>{_share(link("b", w["id"]))}</div>'
                    for w in r["wings"])
                body = f'<div class="md-cards">{wings}</div>'
            else:
                body = '<ul class="md-bosses">' + "".join(f"<li>{e(b)}</li>" for b in r["bosses"]) + "</ul>"
            hint = f'<p class="md-hint">{e(r["hint"])}</p>' if r.get("hint") else ""
            raids_html.append(f'<div class="md-raid">{head}{body}{hint}</div>')
    bosses = (
        '<section class="ly-panel" id="bosses" aria-labelledby="md-bosses"><h2 id="md-bosses">Boss fights</h2>'
        + _shot("bosses", art_url, have)
        + '<p class="md-lede">Every raid, from Molten Core to the Frozen Throne. Go takes your character to the '
        'raid\'s door. Raids need a raid group (Party &rarr; Convert to Raid works with just one friend), and '
        'new characters can boost to 80 with <code>.boost</code>.</p>'
        + "".join(raids_html) + '</section>')

    # Dungeons
    dung_html = []
    for key, _n, _s in D.EXPANSIONS:
        name, sub = regions[key]
        cards = []
        for q in (q for q in D.RANDOM_QUEUES if q["exp"] == key):
            cards.append(_card(q["name"], q["line"], [_tag(_levels(q["levels"])), _tag("5 players"),
                                                      _tag("Bots can fill", "bots")], link("q", q["id"]), "Queue"))
        for d in (d for d in D.DUNGEONS if d["exp"] == key):
            tags = [_tag(_levels(d["levels"])), _tag("5 players")]
            if d["bots"]:
                tags.append(_tag("Bots can fill", "bots"))
            cards.append(_card(d["name"], "", tags, link("q", d["id"])))
        dung_html.append(f'<h3 class="md-region">{e(name)} <span>· {e(sub)}</span></h3>'
                         f'<div class="md-cards">{"".join(cards)}</div>')
    dungeons = (
        '<section class="ly-panel" id="dungeons" aria-labelledby="md-dungeons"><h2 id="md-dungeons">Dungeons</h2>'
        + _shot("dungeons", art_url, have)
        + '<p class="md-lede">Every 5-player dungeon, and the random queues. No group? The Dungeon Finder '
        'fills it with labelled bots, and <code>.recruit tank</code> (or healer, dps) adds one to your party.</p>'
        + "".join(dung_html) + '</section>')

    # Hangouts
    hang_cards = []
    for h in D.HANGOUTS:
        hang_cards.append(_card(h["name"], h["line"], [_tag(h["tag"]), _tag("Players only")], link("h", h["id"])))
    hangouts = (
        '<section class="ly-panel" id="hangouts" aria-labelledby="md-hangouts"><h2 id="md-hangouts">Hangouts</h2>'
        + _shot("hangouts", art_url, have)
        + '<p class="md-lede">Places to meet, trade and show off. The Goldshire Inn also has a guest pass: '
        '<a href="/wrath/demo">try it with no sign-up</a>.</p>'
        f'<div class="md-cards">{"".join(hang_cards)}</div></section>')

    body = (
        '<div class="ly-wrap"><header class="ly-hero"><h1>Modes</h1>'
        f'<p class="ly-lede">Duels, boss fights, dungeons and hangouts on {e(realm_name)}. Every card is one click: '
        'sign in, and your character is taken there.</p>'
        '<nav class="md-jump" aria-label="Modes"><a href="#duels">Duels</a><a href="#bosses">Boss fights</a>'
        '<a href="#dungeons">Dungeons</a><a href="#hangouts">Hangouts</a></nav></header>'
        + duels + bosses + dungeons + hangouts
        + '<p class="ly-fine">Go works for a character of the right level that is out of combat and not inside an '
        'instance; it waits for your next login for 30 minutes. In the browser, places outside the streamed areas '
        'need your own 3.3.5a game files.</p></div>')
    meta = card_meta("/wrath/modes", f"Modes · {realm_name}")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>Modes · {e(realm_name)}</title>{meta}<style>{css}{MODES_CSS}</style></head>'
            f'<body class="ly"><div class="ly-glow"></div>{body}</body></html>').encode("utf-8")


def names() -> dict:
    """"<kind>:<id>" -> the place's name, for the share link cards (links.NAMES)."""
    return {k: v["name"] for k, v in PLACES.items()}


def go_command(account: str, go: str) -> str | None:
    """The console command for this intent, or None when the account or the target is not allowed."""
    if not isinstance(account, str) or not isinstance(go, str) or not ACCOUNT_RE.fullmatch(account):
        return None
    if not GO_RE.fullmatch(go) or go not in PLACES:
        return None
    return f"ovgo set {account.upper()} {go}"


_recent: dict = {}
_recent_lock = threading.Lock()
REPEAT_S = 120   # the same intent for the same account is sent once per two minutes


def go_intent(soap, account: str, go: str, log=None) -> bool:
    """Record the intent on the realm. soap(command) -> reply text (raises on failure). True when the realm
    confirmed ("ovgo ok"); False otherwise (never raises: a failed go never stops anyone playing)."""
    cmd = go_command(account, go)
    if not cmd:
        return False
    now = time.monotonic()
    key = account.upper()
    with _recent_lock:
        last = _recent.get(key)
        if last and last[0] == go and now - last[1] < REPEAT_S:
            return True
    try:
        text = soap(cmd) or ""
    except Exception as ex:  # noqa: BLE001
        if log:
            log.warning("go intent %s %s failed: %s", key, go, getattr(ex, "kind", type(ex).__name__))
        return False
    ok = "ovgo ok" in text
    if ok:
        with _recent_lock:
            _recent[key] = (go, now)
            if len(_recent) > 20000:
                _recent.clear()
    elif log:
        log.warning("go intent %s %s: the realm did not confirm (is ov_go.lua loaded?)", key, go)
    return ok
