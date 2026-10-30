"""Leyline game modes: the catalog (stream/playmodes.json), its checker, /wrath/modes.json and the "Games"
section of /wrath/modes, and the one-click play intent. For stream/wrath_portal.py; standard library only.

The catalog is the one list the launcher's Modes page (launcher/src-tauri/src/modes.rs fetches
https://play.openvanilla.app/wrath/modes.json) and the site show. Each entry:

    id        a-z, 0-9 and dashes, 2-24 long
    title     a short name;  line  one plain sentence about it
    kind      realm       runs on our realm (realm/custom/lua_scripts/ov_playmode.lua starts it through
                          ov_golf.lua / ov_modes.lua); start = {"go": "mode:<id>"}
              offline     runs in the browser client with no server (the player's own game folder);
                          start = {"path": "/wrath/..."} on this site
              realm-type  needs its own server type, hosted through the Host pack; start = {"host": "<preset>"}
    players   {"min": n, "max": n or null}
    status    live | coming   (coming: shown with "Coming soon" and its credit link, never a Play button)
    credit    for anything not ours: {"by", "license", "source": https URL, "note"?, "more"?: [https URLs]}

One click to play a realm mode: /wrath?go=mode:<id>. The portal's sign-in (wrath_portal.remember_go) sends one
console command over SOAP for the signed-in game account,
    ovplay go <ACCOUNT> <id>
and ov_playmode.lua starts the mode at that account's next login (or now, if a character is online), checking
the id against its own table. Only live realm-kind ids from the catalog are ever sent. The desktop launcher
does the same through a small addon file it writes into the player's own client (docs/leyline-modes-play.md).

Check the catalog:  python3 -I stream/playmodes.py --check   (exit 1 with the problems listed)
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import time

ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
PATH_RE = re.compile(r"^/wrath(?:/[A-Za-z0-9._-]+)*(?:\?[A-Za-z0-9._=&-]*)?$")
URL_RE = re.compile(r"^https://[a-z0-9.-]+\.[a-z]{2,}(?:/[A-Za-z0-9._~/%-]*)?$")
KINDS = ("realm", "offline", "realm-type")
STATUSES = ("live", "coming")
FIELDS = {"id", "title", "line", "kind", "players", "status", "start", "credit"}
CREDIT_FIELDS = {"by", "license", "source", "note", "more"}
MAX_PLAYERS = 40
# Names never shown to players (the owner's standing rule; the other suites check the same words).
BANNED = re.compile(r"world of warcraft|\bwow\b|warcraft|lich king|blizzard", re.I)
CATALOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playmodes.json")


def _text(v, lo: int, hi: int) -> bool:
    return isinstance(v, str) and lo <= len(v) <= hi and v == v.strip() and not any(c in v for c in "<>\n\r\t")


def check(doc) -> list[str]:
    """The catalog's problems, in plain words (an empty list: it is fine)."""
    errs: list[str] = []
    if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("modes"), list):
        return ['the catalog must be {"schema": 1, "modes": [...]}']
    if not doc["modes"] or len(doc["modes"]) > 200:
        errs.append("the catalog needs 1 to 200 modes")
    seen = set()
    for i, m in enumerate(doc["modes"]):
        where = f"mode {i + 1}"
        if not isinstance(m, dict):
            errs.append(f"{where}: not an object")
            continue
        mid = m.get("id")
        if not (isinstance(mid, str) and 2 <= len(mid) <= 24 and ID_RE.fullmatch(mid)):
            errs.append(f"{where}: id must be a-z, 0-9 and dashes, 2-24 long")
        else:
            where = mid
            if mid in seen:
                errs.append(f"{where}: the id is used twice")
            seen.add(mid)
        extra = set(m) - FIELDS
        if extra:
            errs.append(f"{where}: unknown fields {sorted(extra)}")
        if not _text(m.get("title"), 2, 40):
            errs.append(f"{where}: title must be 2-40 characters of plain text")
        if not _text(m.get("line"), 10, 140):
            errs.append(f"{where}: line must be one plain sentence of 10-140 characters")
        for f in ("title", "line"):
            if isinstance(m.get(f), str) and BANNED.search(m[f]):
                errs.append(f"{where}: {f} uses a name players must not see")
        kind, status = m.get("kind"), m.get("status")
        if kind not in KINDS:
            errs.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if status not in STATUSES:
            errs.append(f"{where}: status must be live or coming")
        p = m.get("players")
        if not isinstance(p, dict) or set(p) != {"min", "max"}:
            errs.append(f'{where}: players must be {{"min": n, "max": n or null}}')
        else:
            lo, hi = p["min"], p["max"]
            if not (isinstance(lo, int) and not isinstance(lo, bool) and 1 <= lo <= MAX_PLAYERS):
                errs.append(f"{where}: players.min must be 1-{MAX_PLAYERS}")
            elif hi is not None and not (isinstance(hi, int) and not isinstance(hi, bool) and lo <= hi <= MAX_PLAYERS):
                errs.append(f"{where}: players.max must be null or min-{MAX_PLAYERS}")
        s = m.get("start")
        if not isinstance(s, dict) or len(s) != 1:
            errs.append(f"{where}: start must have exactly one way to start")
        elif kind == "realm":
            if s.get("go") != f"mode:{mid}":
                errs.append(f'{where}: a realm mode starts with {{"go": "mode:{mid}"}}')
        elif kind == "offline":
            if not (isinstance(s.get("path"), str) and len(s["path"]) <= 120 and PATH_RE.fullmatch(s["path"])):
                errs.append(f'{where}: an offline mode starts with {{"path": "/wrath/..."}} on this site')
        elif kind == "realm-type":
            h = s.get("host")
            if not (isinstance(h, str) and 2 <= len(h) <= 32 and ID_RE.fullmatch(h)):
                errs.append(f'{where}: a realm type starts with {{"host": "<preset>"}}')
        c = m.get("credit")
        if c is not None:
            if not isinstance(c, dict) or set(c) - CREDIT_FIELDS or not {"by", "license", "source"} <= set(c):
                errs.append(f"{where}: credit needs by, license and source (and may have note, more)")
            else:
                for f in ("by", "license") + (("note",) if "note" in c else ()):
                    if not _text(c[f], 2, 80):
                        errs.append(f"{where}: credit.{f} must be 2-80 characters of plain text")
                urls = [c["source"]] + (c["more"] if isinstance(c.get("more"), list) else ["x"] if "more" in c else [])
                if not all(isinstance(u, str) and len(u) <= 200 and URL_RE.fullmatch(u) for u in urls) or len(urls) > 5:
                    errs.append(f"{where}: credit.source and credit.more must be plain https links (5 at most)")
    return errs


def load(path: str = CATALOG_FILE) -> tuple[dict | None, list[str]]:
    """(the catalog, []) or (None, its problems). Never raises."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as ex:
        return None, [f"cannot read {os.path.basename(path)}: {ex}"]
    errs = check(doc)
    return (None, errs) if errs else (doc, [])


CATALOG, ERRORS = load()


def entries() -> list[dict]:
    return list(CATALOG["modes"]) if CATALOG else []


def by_id(mid: str) -> dict | None:
    return next((m for m in entries() if m["id"] == mid), None)


def realm_ids() -> list[str]:
    """The ids the realm may be asked to start: live realm modes."""
    return [m["id"] for m in entries() if m["kind"] == "realm" and m["status"] == "live"]


def json_bytes() -> bytes:
    """GET /wrath/modes.json: the checked catalog (an empty list when the file is missing or broken)."""
    doc = {"schema": 1, "modes": entries()}
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def players_text(p: dict) -> str:
    lo, hi = p["min"], p["max"]
    if hi is None:
        return "Any number of players" if lo == 1 else f"{lo}+ players"
    if lo == hi:
        return "1 player" if lo == 1 else f"{lo} players"
    return f"{lo}-{hi} players"


KIND_TEXT = {"realm": "On our realm", "offline": "No server", "realm-type": "Its own realm type"}


def play_href(m: dict, host_href: str = "/wrath/host") -> str | None:
    """Where the site's Play button goes, or None for a mode that is coming."""
    if m["status"] != "live":
        return None
    s = m["start"]
    if m["kind"] == "realm":
        return "/wrath?go=" + s["go"]
    if m["kind"] == "offline":
        return s["path"]
    return host_href


def section(host_href: str = "/wrath/host") -> str:
    """The "Games" section at the top of /wrath/modes (the hub's own CSS classes). "" without a catalog."""
    e = html.escape
    cards = []
    for m in entries():
        tags = [f'<span class="md-tag">{e(KIND_TEXT[m["kind"]])}</span>', f'<span class="md-tag">{e(players_text(m["players"]))}</span>']
        if m["status"] == "coming":
            tags.append('<span class="md-tag">Coming soon</span>')
        c = m.get("credit")
        credit = ""
        if c:
            note = f' · {e(c["note"])}' if c.get("note") else ""
            credit = (f'<p class="md-hint">By {e(c["by"])}{note} · {e(c["license"])} · '
                      f'<a href="{e(c["source"])}" rel="noopener">Source</a></p>')
        href = play_href(m, host_href)
        if href is None:
            act = ""
        else:
            label = {"realm": "Play", "offline": "Play", "realm-type": "Host it"}[m["kind"]]
            act = f'<a class="md-go" href="{e(href)}">{label}</a>'
        cards.append(f'<div class="md-card" id="mode-{e(m["id"])}"><h3>{e(m["title"])}</h3><p>{e(m["line"])}</p>'
                     f'<div class="md-tags">{"".join(tags)}</div>{credit}{act}</div>')
    if not cards:
        return ""
    return ('<section class="ly-panel" id="games" aria-labelledby="md-games"><h2 id="md-games">Games</h2>'
            '<p class="md-lede">Minigames and game modes. Play signs you in and starts the game when your character '
            'is in the world. The Leyline launcher lists the same games on its Modes page.</p>'
            f'<div class="md-cards">{"".join(cards)}</div></section>')


# --------------------------------------------------------------------------------------- the play intent

def go_mode(value) -> str | None:
    """The mode id of a ?go=mode:<id> value naming a live realm mode, else None."""
    if not isinstance(value, str) or len(value) > 40 or not value.startswith("mode:"):
        return None
    mid = value[5:]
    return mid if mid in realm_ids() else None


def go_command(account: str, mid: str) -> str | None:
    """The console command, or None when the account or the mode is not allowed."""
    if not isinstance(account, str) or not ACCOUNT_RE.fullmatch(account):
        return None
    if not isinstance(mid, str) or mid not in realm_ids():
        return None
    return f"ovplay go {account.upper()} {mid}"


_recent: dict = {}
_recent_lock = threading.Lock()
REPEAT_S = 120   # the same mode for the same account is sent once per two minutes


def go_intent(soap, account: str, mid: str, log=None) -> bool:
    """Record "play <mode>" for the account on the realm. soap(command) -> reply text (raises on failure).
    True when the realm confirmed ("ovplay ok"); never raises: a failed intent never stops anyone playing."""
    cmd = go_command(account, mid)
    if not cmd:
        return False
    now = time.monotonic()
    key = account.upper()
    with _recent_lock:
        last = _recent.get(key)
        if last and last[0] == mid and now - last[1] < REPEAT_S:
            return True
    try:
        text = soap(cmd) or ""
    except Exception as ex:  # noqa: BLE001
        if log:
            log.warning("play intent %s %s failed: %s", key, mid, getattr(ex, "kind", type(ex).__name__))
        return False
    ok = "ovplay ok" in text
    if ok:
        with _recent_lock:
            _recent[key] = (mid, now)
            if len(_recent) > 20000:
                _recent.clear()
    elif log:
        log.warning("play intent %s %s: the realm did not confirm (is ov_playmode.lua loaded?)", key, mid)
    return ok


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        p = next((a for a in sys.argv[1:] if not a.startswith("--")), CATALOG_FILE)
        doc, errs = load(p)
        for x in errs:
            print("FAIL", x)
        print("OK" if doc else "the catalog has problems", f"({len(doc['modes'])} modes)" if doc else "")
        sys.exit(0 if doc else 1)
    print(__doc__)
