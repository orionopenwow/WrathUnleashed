"""The Leyline hub (hidden preview): one catalog of the Workshop, the community index and theme packs.

Built for the 2026-10-26 brief ("hide the full leyline front page thing but build it out for now") and the
2026-10-29 one (an auto-populated index of open mods for every client build the launcher supports, and a way
for people to submit their mods). Served by stream/wrath_portal.py, which loads this file from beside itself
and runs without it.

    GET  /wrath/leyline-preview               the front page: the hero (the big mark leads), the live ticker, every realm
                                              on the network (one-click Play in browser, the desktop address, a hover
                                              preview), how it works, the numbers, one feature section per part of
                                              Leyline (launcher, hosting, realms, modes, mods, community, agents) on a
                                              ley line, Hosted by the community (posters), Mod of the week, Hero Key,
                                              Creator spotlight, News, Platform Status, Community Spotlight,
                                              categories, creators, Host a Beacon. Every hub page has the same header:
                                              the launcher's pages (Play, Realms, Mods, Addons, Modes, Host, Community,
                                              More) with Download and Sign In (or the account chip).
                                              No client build number or game name on any hub page
                                              (neutral(), CLIENT_LABEL, COMPAT; stream/tests/test_hub.py checks)
    GET  /wrath/leyline-preview/catalog       everything, filtered by plain links and a GET form (no script):
                                              ?build=1.12|2.4.3|3.3.5a &cat=<category>|themes (4.3.4, 5.4.8 hidden: HIDDEN_BUILDS)
                                              &source=workshop|index|theme &q=<text> &sort=score|name|updated &page=N
    GET  /wrath/leyline-preview/p/<id>        one item (id: link-<12 hex>, mod-<mod id>, theme-<id>)
    GET  /wrath/leyline-preview/creators      for creators: the docs, how the index works, how to submit
    GET  /wrath/leyline-preview/beacon        Host a Beacon (your own realm on the Leyline list)
    GET  /wrath/leyline-preview/realms        every realm on the network as rows: ours first, then stream/network.py's
                                              order; filters ?client=browser|own &tag= &region= &lang= &now=1
    GET  /wrath/leyline-preview/modes         the launcher's Modes page: every game mode, one click (/wrath?go=mode:<id>)
    GET  /wrath/leyline-preview/news          the launcher's News page: the admin console's news.json posts
    GET  /wrath/leyline-preview/gallery       the gallery: our in-game screenshots (hidden while the game data killswitch is
                                              on: one flat Leyline tile instead), the Workshop's mod screenshots and featured
                                              mods (Install with Leyline, View), the launcher's pages; ?f=game|mods|launcher.
                                              The front page shows ten of them (after the feature sections). Pictures are only
                                              ever our own files: nothing pulled or hotlinked from another site or CDN (press
                                              kits, wiki or database sites, other people's READMEs: copyright and hotlinking)
    GET  /wrath/leyline-preview/submit        the "Submit a mod" form;  POST it to queue a submission
    GET  /wrath/leyline-preview/approved.json the approved submissions and delisted repos (the index pipeline reads
                                              it: tools/hub-index/hub_index.py); repo URLs only, no notes
    GET  /wrath/leyline/catalog.json          the merged catalog for the Leyline launcher, in the all.json shape
                                              (mods/all-json.md) with the extra fields in docs/HUB-INDEX.md (CORS *)

Hidden: every preview page carries <meta name="robots" content="noindex"> and an X-Robots-Tag header, and no
other page links here. The front page and the realm list carry one small script (HUB_JS, under a CSP nonce):
Copy buttons, the realm filter without a reload, live player counts and the section reveal; without it they work
the same, only still. The gallery page carries it too (filters in place, the lightbox). Every other hub page has no script. The one switch: WU_HUB_FRONT=1 serves the front page at /wrath/leyline too (the front
door, and the gallery at /wrath/leyline/gallery) and drops the noindex. Off by default. WU_HUB=0 turns the whole thing off (404s).

Data (read-only /app, beside this file in a checkout):
    hub/community-index.json   tools/hub-index/hub_index.py's output (the link-out index); WU_HUB_DIR overrides
    hub/themes.json            theme packs (format in docs/HUB-INDEX.md); missing = none yet
Writable ($WU_PORTAL_DATA/hub, default /data/hub):
    submissions.jsonl          the queue the "Submit a mod" form appends to (no personal data)
    decisions.jsonl            written by the admin console: approve / reject / delist (docs/HUB-INDEX.md)

The rules the index pipeline and these pages share live here too (licences, the brand-word check and cleaner,
canonical repo links and ids, validate_index), so there is one copy. Standard library only.
"""
from __future__ import annotations

import hashlib
import html
import itertools
import json
import math
import os
import re
import secrets
import threading
import time
import urllib.parse

BASE = "/wrath/leyline-preview"
FEED = "/wrath/leyline/catalog.json"
FRONT = "/wrath/leyline"
HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------------------------------- shared rules
BUILDS = ["1.12", "2.4.3", "3.3.5a", "4.3.4", "5.4.8"]           # the client builds the launcher supports
BUILD_LABEL = {"1.12": "1.12.1", "2.4.3": "2.4.3", "3.3.5a": "3.3.5a", "4.3.4": "4.3.4", "5.4.8": "5.4.8", "any": "Any build"}
BUILD_ERA = {"1.12": "Classic", "2.4.3": "Outland", "3.3.5a": "Wrath", "4.3.4": "Cataclysm", "5.4.8": "Pandaria"}
# The builds offered now. Hidden by the owner on 2026-10-30 ("3.3.5 at max until I research"): 4.3.4 and 5.4.8 stay
# in BUILDS (the index keeps their entries) but the hub does not show them, their chips or their items. Empty this
# tuple (or set LEYLINE_ALL_CLIENTS=1) to show them again.
HIDDEN_BUILDS = ("4.3.4", "5.4.8")


def offered_builds(env=None) -> list:
    v = (os.environ if env is None else env).get("LEYLINE_ALL_CLIENTS", "").strip().lower()
    return list(BUILDS) if v in ("1", "true", "yes", "on") else [b for b in BUILDS if b not in HIDDEN_BUILDS]


def offered_only(item: dict, offered=None):
    """The item with only the offered builds, or None when it is made only for builds not offered now."""
    offered = (offered_builds() if offered is None else offered) + ["any"]
    b = [x for x in (item.get("builds") or ["any"]) if x in offered]
    return {**item, "builds": b} if b else None


# The addon TOC "## Interface:" numbers of those builds.
INTERFACE = {"11200": "1.12", "20400": "2.4.3", "30300": "3.3.5a", "40300": "4.3.4", "50400": "5.4.8"}
CATEGORIES = [
    ("addons", "Addons and UI"), ("graphics", "Shaders and graphics"), ("sandbox", "Sandbox and game modes"),
    ("maps", "Custom maps"), ("builds", "Builds"), ("encounters", "Boss fights and encounters"),
    ("models", "Models and props"), ("realm-scripts", "Realm scripts"), ("presets", "Server presets"),
    ("audio", "Sounds and music"), ("tools", "Tools"), ("conversions", "Total conversions"),
]
CATEGORY_IDS = [c for c, _ in CATEGORIES]
THEMES = ("themes", "Themes")                                      # the 13th shelf: launcher theme packs
TYPES = ("addon", "module", "lua", "core", "tool", "preset", "other")
# Open licences (SPDX ids, GitHub's spelling). Anything else, or none, keeps a repo off the index.
OPEN_LICENCES = {
    "MIT", "MIT-0", "Apache-2.0", "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-only",
    "GPL-3.0-or-later", "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "LGPL-2.1", "LGPL-2.1-only",
    "LGPL-2.1-or-later", "LGPL-3.0", "LGPL-3.0-only", "LGPL-3.0-or-later", "MPL-2.0", "BSD-2-Clause",
    "BSD-3-Clause", "0BSD", "ISC", "Unlicense", "CC0-1.0", "Zlib", "BSL-1.0", "WTFPL", "CC-BY-4.0",
    "CC-BY-SA-4.0", "EPL-2.0", "EUPL-1.2", "Artistic-2.0", "OFL-1.1", "MS-PL", "NCSA", "PostgreSQL", "Vim",
}
FORGES = {"github.com": "github", "gitlab.com": "gitlab", "codeberg.org": "codeberg"}
FORGE_LABEL = {"github": "GitHub", "gitlab": "GitLab", "codeberg": "Codeberg"}
SEG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
HEX12 = re.compile(r"^[0-9a-f]{12}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")

# The brand words that never appear in anything a visitor sees. Stricter than a word match: "WoW" inside a
# name ("MalfurionWoW", "WowDevTools") counts too. "WotLK" and "Wrath" are fine.
BANNED_RE = re.compile(
    r"(?i:world\s*of\s*warcraft|warcraft|lich\s*king|blizzard)"
    r"|(?i:(?<![a-z])wow(?![a-z]))"
    r"|WoW|WOW|(?<![a-z])Wow(?=[A-Z0-9])|(?<=[a-z])Wow(?![a-z])")


def banned(text: str) -> bool:
    return bool(BANNED_RE.search(text or ""))


# The hub pages never show a client build number or the game's name (the owner, 2026-10-30: "not mention client numbers
# or world of warcraft on any part of the site but gently indicate its for all clients"). The catalog and the realm list
# still filter by build underneath (?build=, the launcher feed keeps the numbers); what a visitor reads is these words.
# TODO(owner): the wording of the client labels.
CLIENT_LABEL = {"1.12": "Classic era", "2.4.3": "Second era", "3.3.5a": "Third era", "4.3.4": "Fourth era",
                "5.4.8": "Fifth era", "any": "Any client"}
_VER = (r"v?(?:1\.12(?:\.[0-9x]+)?|2\.4(?:\.3)?|3\.3(?:\.5a?)?|4\.3(?:\.4)?|5\.4(?:\.8)?"
        r"|5875|6005|8606|12340|15595|18414)")
_VER_LIST = rf"(?<![\w.]){_VER}(?:\s*(?:,|/|&|\band\b|\bor\b)\s*{_VER})*(?![\w]|\.\d)"
VERSION_RE = re.compile(_VER_LIST, re.I)


def neutral(text, n: int = 0) -> str:
    """Text from a repo, a realm, a news post or a mode, fit for the hub: the brand words dropped (scrub) and every client
    build number taken out with the little words around it ("An addon for 1.12.1" -> "An addon", "(3.3.5a)" -> "")."""
    s = scrub(clean_line(text, 2000) if isinstance(text, str) else "")
    s = re.sub(rf"(?i)\s*\b(?:for|on|in|with|from)\s+(?:the\s+)?{_VER_LIST}(?:\s+(?:clients?|servers?|realms?|cores?|builds?))?", "", s)
    s = re.sub(rf"(?i)\s*[(\[]\s*{_VER_LIST}(?:\s+[\w-]+)?\s*[)\]]", "", s)
    s = re.sub(rf"(?i)\b(?:patch|version|build|client)\s+{_VER_LIST}", "", s)
    s = VERSION_RE.sub("", s)
    s = re.sub(r"\(\s*\)|\[\s*\]", "", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    s = re.sub(r"\s+([,.;:!?)])", r"\1", s)
    s = re.sub(r"([(-])\s*[-–]\s*", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–:,;/·|")
    s = re.sub(r"\b([Aa]) (?=[aeiouAEIOU][a-z])", r"\1n ", s)
    s = re.sub(r"\b([Aa])n (?=[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z0-9])", r"\1 ", s)
    s = s[:1].upper() + s[1:]
    return clean_line(s, n) if n else s


def clean_line(v, n: int = 200) -> str:
    """One line of plain text: control and direction characters dropped, spaces collapsed, cut to n."""
    if not isinstance(v, str):
        return ""
    s = re.sub(r"\s+", " ", CTRL_RE.sub(" ", v)).strip()
    if len(s) > n:
        s = s[:n - 1].rstrip(" ,;:-") + "…"
    return s


def scrub(text: str) -> str:
    """Text from a repo, made fit to show: the brand words dropped where they are an adjective ("A WoW emulator" ->
    "An emulator", "Vanilla WoW 1.12.1 addon" -> "Vanilla 1.12.1 addon"), otherwise replaced ("for World of
    Warcraft" -> "for the game", "Wrath of the Lich King" -> "Wrath"), then tidied."""
    s = text or ""
    s = re.sub(r"(?i)\bwrath\s+of\s+the\s+lich\s*king\b", "Wrath", s)
    s = re.sub(r"(?i)\b(vanilla|classic|turtle|tortoise|legacy|retail)[ -](wow|world\s*of\s*warcraft)\b", r"\1", s)
    s = re.sub(r"(?i)\b(?:wow|world\s*of\s*warcraft)[ -]+(classic|vanilla|tbc|wotlk)\b", r"\1", s)
    s = re.sub(r"(?i)\b(?:world\s*of\s*warcraft|wow)[ -]+(?=\d|(addon|emulator|server|macro|sound|interface|client|core|"
               r"private|launcher|mod|database|tool|script|lua|combat|engine|clone|armory|guide|quest|ui\b|api\b|"
               r"patch|bot|plugin|player|character|account|realm))", "", s)

    def rep(m):
        w = m.group(0).lower()
        if "lich" in w:
            return "Wrath"
        if "blizzard" in w:
            return "the publisher"
        return "the game"
    s = re.sub(r"(?i)\b(?:blizzard|world\s*of\s*warcraft|wow|warcraft)\s+(?=fans?\b|players?\b|community\b|veterans?\b)", "", s)
    s = BANNED_RE.sub(rep, s)
    s = re.sub(r"\bthe game(\s+the game)+\b", "the game", s)
    s = re.sub(r"\b([Aa]) (?=[aeiouAEIOU][a-z])", r"\1n ", s)
    s = re.sub(r"\b([Aa])n (?=[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z0-9])", r"\1 ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -:")
    return s[:1].upper() + s[1:]


def clean_name(raw: str) -> str:
    """A display name from a repo or addon name: brand words dropped (never replaced with an odd phrase),
    separators kept readable. "WoW-Spell-Editor" -> "Spell-Editor", "mangos-wotlk" stays."""
    s = BANNED_RE.sub(" ", raw or "")
    s = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", s)                   # TOC colour codes
    s = re.sub(r"(?<=[\s_.-])[\s_.-]+|^[\s_.-]+|[\s_.-]+$", "", s)  # leftover separators
    s = re.sub(r"\s{2,}", " ", s).strip(" -_.")
    return clean_line(s, 64)


def canonical(raw: str) -> dict | None:
    """A forge repo link in canonical form ({url, key, host, forge, owner, repo}), or None. GitHub, GitLab and
    Codeberg only (the index needs their APIs). key = the url lowercased; id = sha256(key)[:12], the same id
    stream/projects.py gives a community link to the same repo, so the two dedupe by id."""
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw or len(raw) > 300 or CTRL_RE.search(raw) or re.search(r"\s", raw):
        return None
    if raw.startswith("git@"):                                      # git@github.com:owner/repo.git
        m = re.fullmatch(r"git@([a-z.]+):(.+)", raw)
        raw = f"https://{m.group(1)}/{m.group(2)}" if m else raw
    try:
        u = urllib.parse.urlsplit(raw)
        port = u.port
    except ValueError:
        return None
    if u.scheme.lower() not in ("https", "http") or u.username or u.password or port not in (None, 443):
        return None
    host = (u.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    forge = FORGES.get(host)
    if not forge:
        return None
    parts = [p for p in urllib.parse.unquote(u.path or "").split("/") if p]
    if "-" in parts:
        parts = parts[:parts.index("-")]
    parts = parts[:3] if forge == "gitlab" and len(parts) >= 3 and parts[2] not in ("tree", "blob", "issues") else parts[:2]
    if len(parts) < 2 or not all(SEG_RE.fullmatch(p) for p in parts) or ".." in parts:
        return None
    if parts[-1].lower().endswith(".git"):
        parts[-1] = parts[-1][:-4]
        if not parts[-1]:
            return None
    if parts[0].lower() in {"topics", "orgs", "users", "explore", "search", "settings", "marketplace", "sponsors",
                            "features", "collections", "trending", "about", "login", "api", "new"}:
        return None
    url = f"https://{host}/" + "/".join(parts)
    key = url.lower()
    return {"url": url, "key": key, "host": host, "forge": forge, "owner": "/".join(parts[:-1]), "repo": parts[-1],
            "id": hashlib.sha256(key.encode()).hexdigest()[:12]}


def build_tag(v) -> str:
    """A build as the catalog tags it ("1.12.1" and "1.12" -> "1.12"), or ""."""
    v = (v or "").strip().lower() if isinstance(v, str) else ""
    v = {"1.12.1": "1.12", "3.3.5": "3.3.5a", "vanilla": "1.12", "classic": "1.12", "tbc": "2.4.3", "wotlk": "3.3.5a",
         "wrath": "3.3.5a", "cata": "4.3.4", "cataclysm": "4.3.4", "mop": "5.4.8", "pandaria": "5.4.8"}.get(v, v)
    return v if v in BUILDS or v == "any" else ""


def offered_tag(v) -> str:
    """build_tag, but "" for a build not offered now (HIDDEN_BUILDS): what pages and the submit form take."""
    t = build_tag(v)
    return t if t == "any" or t in offered_builds() else ""


ENTRY_KEYS = {"id", "name", "author", "owner", "repo", "forge", "licence", "category", "type", "builds", "summary",
              "description", "stars", "updated", "archived", "needs", "source", "score", "release", "thumb", "thumb_credit"}
RELEASE_KEYS = {"tag", "date", "url"}

# Preview thumbnails (tools/hub-index/hub_index.py thumbs): a GitHub project's own preview image, made a small WebP and
# served from our site (the art route, /wrath/art/hub-thumbs/<owner>__<repo>.webp), never hotlinked. Always credited.
THUMB_URL = "/wrath/art/hub-thumbs/"
THUMB_CREDIT = "Preview image from the project's GitHub page"
THUMB_PART = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")
THUMB_FILE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}__[a-z0-9][a-z0-9._-]{0,99}\.webp")


def thumb_name(repo_url: str) -> str:
    """"<owner>__<repo>.webp" for a GitHub repo link, "" when it isn't one or a part is odd."""
    c = canonical(repo_url or "")
    if not c or c["forge"] != "github":
        return ""
    owner, repo = c["owner"].lower(), c["repo"].lower()
    if "/" in owner or not THUMB_PART.fullmatch(owner) or not THUMB_PART.fullmatch(repo) or ".." in owner + repo:
        return ""
    return f"{owner}__{repo}.webp"


def thumb_problem(e: dict) -> str:
    """"" when an entry's thumb fields are fine (or absent), else what is wrong."""
    has = [k for k in ("thumb", "thumb_credit") if k in e]
    if not has:
        return ""
    if len(has) != 2:
        return "thumb and thumb_credit go together"
    name = thumb_name(e.get("repo", ""))
    if not name or e["thumb"] != THUMB_URL + name:
        return f"thumb must be {THUMB_URL}<owner>__<repo>.webp for its own GitHub repo"
    if e["thumb_credit"] != THUMB_CREDIT:
        return "thumb_credit must be exactly: " + THUMB_CREDIT
    return ""


# External packs (the index's top-level "external" list; owner's decision 2026-10-30): HD graphics packs and the like,
# made and hosted by their authors. Link-only: never an entry, never mirrored, never installable; each page says so.
EXTERNAL_TYPE = "external-pack"
EXTERNAL_NOTE = "External download, made and hosted by its authors; not checked or hosted by Leyline"
EXTERNAL_KEYS = {"id", "name", "author", "url", "repo", "category", "type", "builds", "summary", "external", "note",
                 "source_thread", "added", "thumb", "thumb_credit"}
EXTERNAL_ID = re.compile(r"ext:[0-9a-f]{12}")
EXTERNAL_FILE = re.compile(r"(?i)\.(zip|rar|7z|mpq|exe|msi|apk|dmg|torrent|tar(\.\w+)?|tgz)(\?|#|$)|/releases/download/|"
                           r"[?&]download=|mega\.nz|mediafire\.com|drive\.google\.com|dropbox\.com/s|wetransfer\.com|"
                           r"^leyline:")
EXTERNAL_LABEL = "Graphics & external packs"


def external_id(url: str) -> str:
    return "ext:" + hashlib.sha256(str(url).strip().lower().encode("utf-8")).hexdigest()[:12]


def external_problems(x) -> list[str]:
    """Problems with one item of the index's "external" list ([] = fine). The pages show only items without any."""
    if not isinstance(x, dict):
        return ["not an object"]
    out = []
    extra = set(x) - EXTERNAL_KEYS
    if extra:
        out.append(f"unknown fields {sorted(extra)}")
    url = x.get("url")
    u = urllib.parse.urlsplit(url if isinstance(url, str) else "")
    if not isinstance(url, str) or u.scheme != "https" or not u.hostname or u.username or u.password or len(url) > 400 \
            or re.search(r"[\s<>\"']", url) or CTRL_RE.search(url):
        out.append("url must be an https page")
    elif EXTERNAL_FILE.search(url):
        out.append("url must be the pack's own page, never a file or a file host")
    if not isinstance(x.get("id"), str) or not EXTERNAL_ID.fullmatch(x["id"]) or x["id"] != external_id(url or ""):
        out.append("id must be ext:<12 hex> of its url")
    if x.get("type") != EXTERNAL_TYPE or x.get("external") is not True or x.get("note") != EXTERNAL_NOTE:
        out.append("type, external flag and note are fixed")
    if x.get("category") not in CATEGORY_IDS:
        out.append(f"category {x.get('category')!r}")
    b = x.get("builds")
    if not isinstance(b, list) or not b or any(v not in BUILDS + ["any"] for v in b):
        out.append(f"builds {b!r}")
    for k in ("name", "summary"):
        if not isinstance(x.get(k), str) or not x[k].strip():
            out.append(f"{k} missing")
    for k in ("name", "author", "summary", "added"):
        if k in x and not isinstance(x[k], str):
            out.append(f"{k} must be text")
    vis = " ".join(str(x.get(k) or "") for k in ("name", "author", "summary", "note"))
    if banned(vis):
        out.append("a brand word in its visible text")
    if "<" in vis or ">" in vis or CTRL_RE.search(vis):
        out.append("markup or control characters")
    if re.search(r"(?i)wowdecomp|waystone|decompil|chumpton|repack|\bleak", vis + " " + str(url) + " " + str(x.get("repo") or "")):
        out.append("decompiled, leaked or repack material")
    if "source_thread" in x and not _https(x["source_thread"]):
        out.append("source_thread must be an https link")
    if "repo" in x:
        c = canonical(x["repo"])
        if not c or c["url"] != x["repo"]:
            out.append("repo is not a canonical forge link")
    if "thumb" in x or "thumb_credit" in x:
        if "repo" not in x:
            out.append("thumb only from the pack's own GitHub repo")
        elif thumb_problem(x):
            out.append(thumb_problem(x))
    return out


def release_problem(r, repo: str) -> str:
    """"" when an entry's latest-release record ({tag, date, url}: the release's page on the repo's own forge) is
    fine, else what is wrong. The daily index refresh writes it (tools/hub-index/hub_index.py)."""
    if not isinstance(r, dict) or set(r) - RELEASE_KEYS or not {"tag", "url"} <= set(r):
        return "release must be {tag, date, url}"
    if not isinstance(r["tag"], str) or not r["tag"].strip() or len(r["tag"]) > 40 or CTRL_RE.search(r["tag"]) \
            or "<" in r["tag"] or ">" in r["tag"]:
        return "release tag"
    if r.get("date") not in (None, "") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("date"))):
        return "release date"
    url = r["url"]
    if not isinstance(url, str) or not url.startswith(repo + "/") or len(url) > 400 or re.search(r"[\s<>\"']", url) \
            or CTRL_RE.search(url):
        return "release url must be on the entry's own repo"
    return ""


def visible_text(e: dict) -> str:
    """Everything of an index entry a visitor can see (never the repo URL: pages show "View source")."""
    return " ".join(str(e.get(k) or "") for k in ("name", "author", "summary", "description", "needs", "licence"))


def validate_index(doc) -> list[str]:
    """Problems with a community-index.json document ([] = fine). The pages and the pipeline both run this."""
    out = []
    if not isinstance(doc, dict) or doc.get("format") != 2 or not isinstance(doc.get("entries"), list):
        return ["not a format-2 index ({format: 2, entries: [...]})"]
    seen, keys = set(), set()
    for i, e in enumerate(doc["entries"]):
        where = f"entry {i} ({e.get('name') if isinstance(e, dict) else '?'})"
        if not isinstance(e, dict):
            out.append(f"{where}: not an object")
            continue
        extra = set(e) - ENTRY_KEYS
        if extra:
            out.append(f"{where}: unknown fields {sorted(extra)}")
        c = canonical(e.get("repo", ""))
        if not c or c["url"] != e.get("repo"):
            out.append(f"{where}: repo is not a canonical forge link")
            continue
        if e.get("id") != "link:" + c["id"]:
            out.append(f"{where}: id must be link:{c['id']}")
        if c["key"] in keys or e.get("id") in seen:
            out.append(f"{where}: duplicate")
        keys.add(c["key"])
        seen.add(e.get("id"))
        for k in ("name", "author", "summary"):
            if not isinstance(e.get(k), str) or not e[k].strip():
                out.append(f"{where}: {k} missing")
        if e.get("licence") not in OPEN_LICENCES:
            out.append(f"{where}: licence {e.get('licence')!r} is not an open licence")
        if e.get("category") not in CATEGORY_IDS:
            out.append(f"{where}: category {e.get('category')!r}")
        if e.get("type") not in TYPES:
            out.append(f"{where}: type {e.get('type')!r}")
        b = e.get("builds")
        if not isinstance(b, list) or not b or any(x not in BUILDS + ["any"] for x in b) or b != sorted(set(b), key=_build_order):
            out.append(f"{where}: builds {b!r}")
        if e.get("source") not in ("seed", "discovered", "submitted"):
            out.append(f"{where}: source {e.get('source')!r}")
        if banned(visible_text(e)):
            out.append(f"{where}: a brand word in its visible text")
        if "chumpton" in json.dumps(e).lower():
            out.append(f"{where}: excluded account")
        if re.search(r"(?i)wowdecomp|waystone|decompil", visible_text(e) + " " + e.get("repo", "")):
            out.append(f"{where}: decompiled or wowdecomp-derived")
        for k in ("name", "author", "summary", "description"):
            v = e.get(k)
            if isinstance(v, str) and (CTRL_RE.search(v) or "<" in v or ">" in v):
                out.append(f"{where}: {k} has markup or control characters")
        if not isinstance(e.get("score"), (int, float)) or isinstance(e.get("score"), bool):
            out.append(f"{where}: score")
        if "release" in e and (p := release_problem(e["release"], e.get("repo", ""))):
            out.append(f"{where}: {p}")
        if (p := thumb_problem(e)):
            out.append(f"{where}: {p}")
    if "external" in doc and not isinstance(doc["external"], list):
        out.append("external must be a list")
    ids =[e.get("id") for e in doc["entries"] if isinstance(e, dict)]
    order = sorted(doc["entries"], key=entry_order) if all(isinstance(e, dict) for e in doc["entries"]) else None
    if order is not None and [e.get("id") for e in order] != ids:
        out.append("entries are not in the canonical order (category, name, id)")
    return out


def _build_order(b: str) -> int:
    return (BUILDS + ["any"]).index(b) if b in BUILDS + ["any"] else 99


def entry_order(e: dict):
    return (str(e.get("category", "")), str(e.get("name", "")).lower(), str(e.get("id", "")))


# ------------------------------------------------------------------------------------------- data
def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def front_on() -> bool:
    return os.environ.get("WU_HUB_FRONT", "0").strip() == "1"


def hub_on() -> bool:
    return os.environ.get("WU_HUB", "1").strip() != "0"


def data_dir() -> str:
    return os.environ.get("WU_HUB_DIR") or (os.path.join(HERE, "hub") if os.path.isdir(os.path.join(HERE, "hub"))
                                             else "/app/hub")


def state_dir() -> str:
    return os.path.join(os.environ.get("WU_PORTAL_DATA", "/data"), "hub")


class Store:
    """The submissions queue and the admin console's decisions: JSON lines, appended under a lock."""

    MAX_QUEUE = 2000

    def __init__(self, root: str | None = None):
        self.root = root
        self.lock = threading.Lock()

    @property
    def dir(self) -> str:
        return self.root or state_dir()

    def _read(self, name: str) -> list[dict]:
        out = []
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict):
                        out.append(r)
        except OSError:
            pass
        return out

    def submissions(self) -> list[dict]:
        return self._read("submissions.jsonl")

    def decisions(self) -> dict[str, dict]:
        """The latest decision per id (a later line wins)."""
        out = {}
        for r in self._read("decisions.jsonl"):
            i = r.get("id")
            if isinstance(i, str) and HEX12.fullmatch(i) and r.get("decision") in ("approve", "reject", "delist"):
                out[i] = r
        return out

    def pending(self) -> list[dict]:
        """Submissions with no decision yet (for the admin console), oldest first, one per repo."""
        dec = self.decisions()
        seen, out = set(), []
        for r in self.submissions():
            if r.get("id") in dec or r.get("id") in seen:
                continue
            seen.add(r.get("id"))
            out.append(r)
        return out

    def append(self, rec: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n"
        with self.lock:
            with open(os.path.join(self.dir, "submissions.jsonl"), "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def approved_doc(self) -> dict:
        """What the pipeline merges: approved submissions (repo, build, category) and delisted repos. No notes."""
        dec = self.decisions()
        subs = {r.get("id"): r for r in self.submissions() if isinstance(r.get("id"), str)}
        approved, delisted = [], []
        for i, d in sorted(dec.items()):
            s = subs.get(i, {})
            c = canonical(d.get("repo") or s.get("repo") or "")
            if not c or c["id"] != i:
                continue
            if d["decision"] == "approve":
                approved.append({"id": i, "repo": c["url"], "build": build_tag(d.get("build") or s.get("build")) or "any",
                                 "category": (d.get("category") or s.get("category") or "")
                                 if (d.get("category") or s.get("category")) in CATEGORY_IDS else ""})
            elif d["decision"] == "delist":
                delisted.append({"id": i, "repo": c["url"]})
        return {"format": 1, "approved": approved, "delisted": delisted}


class Hub:
    """The pages. bind() gives it the portal's helpers (ly_shell, workshop, PUBLIC_HOST, ...)."""

    PER_PAGE = 48
    MAX_NOTE = 280

    def __init__(self, root: str | None = None, store: Store | None = None):
        self.root = root
        self.store = store or Store()
        self.portal = lambda name: None
        self._cache: dict[str, tuple[float, float, object]] = {}
        self._limit: dict[str, list[float]] = {}
        self._health: tuple[float, str] = (-1e9, "")
        self.lock = threading.Lock()

    def health_state(self) -> str:
        """The footer's status dot: "ok" (every Platform Status source answered OK), "warn" (some didn't), "bad" (none
        did), or "" when Platform Status hasn't been read in the last 2 minutes (the front page reads it; no dot then)."""
        at, st = self._health
        return st if time.monotonic() - at < 120 else ""

    # ---------------------------------------------------------------- reading
    def _json(self, name: str):
        path = os.path.join(self.root or data_dir(), name)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return None
        hit = self._cache.get(path)
        if hit and hit[0] == mtime:
            return hit[2]
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            doc = None
        self._cache[path] = (mtime, time.time(), doc)
        return doc

    def index(self) -> list[dict]:
        doc = self._json("community-index.json")
        if not isinstance(doc, dict) or validate_index(doc):
            return []
        gone = {d["id"] for d in self.store.approved_doc()["delisted"]}
        return [e for e in doc["entries"] if e["id"][5:] not in gone]

    def themes(self) -> list[dict]:
        doc = self._json("themes.json")
        out = []
        for t in (doc.get("themes") if isinstance(doc, dict) else None) or []:
            if not isinstance(t, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", str(t.get("id", ""))):
                continue
            name, desc, author = clean_line(t.get("name"), 64), clean_line(t.get("description"), 200), clean_line(t.get("author"), 60)
            if not name or banned(name + " " + desc + " " + author):
                continue
            out.append({"id": "theme:" + t["id"], "source": "theme", "name": name, "description": desc,
                        "summary": desc or "A theme pack for the Leyline launcher.", "category": "themes",
                        "builds": ["any"], "author": author or "Leyline", "licence": clean_line(t.get("licence"), 40),
                        "repo": _https(t.get("repo")), "download": _https(t.get("download")),
                        "sha256": t.get("sha256") if re.fullmatch(r"[0-9a-f]{64}", str(t.get("sha256", ""))) else None,
                        "type": "theme", "score": 0, "stars": None, "updated": clean_line(t.get("updated"), 10)})
        return sorted(out, key=lambda x: x["name"].lower())

    def workshop(self) -> list[dict]:
        """The Workshop's all.json projects (packaged mods and community links), [] without a Workshop."""
        ws = self.portal("workshop")
        if ws is None:
            return []
        try:
            doc = json.loads(ws.all_json())
            return [p for p in doc.get("projects", []) if isinstance(p, dict) and isinstance(p.get("id"), str)]
        except Exception:   # noqa: BLE001: a broken Workshop never breaks the hub
            return []

    def items(self) -> list[dict]:
        """Everything in one shape: Workshop first (it wins a duplicate), then the index, then themes."""
        out, have = [], set()
        for p in self.workshop():
            pid = p["id"]
            have.add(pid)
            out.append({"id": pid, "source": "workshop", "name": clean_line(p.get("name"), 64),
                        "summary": clean_line(p.get("description"), 200), "description": "",
                        "category": p.get("category") if p.get("category") in CATEGORY_IDS else "addons",
                        "builds": [b for b in (p.get("builds") or ["any"]) if b in BUILDS + ["any"]] or ["any"],
                        "author": clean_line(p.get("author"), 60), "licence": clean_line(p.get("licence"), 40),
                        "repo": _https(p.get("repo")), "page": _https(p.get("page")), "download": p.get("download"),
                        "sha256": p.get("sha256"), "stars": p.get("stars"), "updated": clean_line(p.get("last_push"), 10),
                        "type": "addon" if p.get("kind") == "ui" else "module" if p.get("kind") == "realm" else "other",
                        "score": 50.0, "packaged": p.get("source") == "packaged", "ws": p})
        for e in self.index():
            if e["id"] in have:
                continue
            out.append({**e, "source": "index", "page": "", "download": None, "sha256": None, "packaged": False})
        out += self.themes()
        offered = offered_builds()
        return [x for x in (offered_only(i, offered) for i in out) if x is not None]

    def external(self) -> list[dict]:
        """The index's external packs (link-only, made and hosted by their authors), each checked on its own
        (external_problems: a bad one is left out, the rest still show), in the catalog's item shape with
        source "external". Never in items(): nothing that lists items can offer to install one."""
        doc = self._json("community-index.json")
        if not isinstance(doc, dict) or not isinstance(doc.get("external"), list) or validate_index(doc):
            return []
        out, seen = [], set()
        offered = offered_builds()
        for x in doc["external"]:
            if external_problems(x) or x["id"] in seen:
                continue
            seen.add(x["id"])
            i = {"id": x["id"], "source": "external", "name": clean_line(x["name"], 64), "summary": clean_line(x["summary"], 240),
                 "description": "", "category": x["category"], "builds": list(x["builds"]),
                 "author": clean_line(x.get("author") or "", 60), "licence": "", "url": x["url"],
                 "repo": x.get("repo", ""), "forge": (canonical(x["repo"]) or {}).get("forge", "") if x.get("repo") else "",
                 "type": EXTERNAL_TYPE, "external": True, "note": EXTERNAL_NOTE, "score": 0, "stars": None,
                 "updated": "", "page": "", "download": None, "sha256": None, "packaged": False}
            for k in ("thumb", "thumb_credit"):
                if k in x:
                    i[k] = x[k]
            i = offered_only(i, offered)
            if i is not None:
                out.append(i)
        return sorted(out, key=lambda i: (i["name"].lower(), i["id"]))

    def get_item(self, slug: str) -> dict | None:
        m = re.fullmatch(r"(link|mod|theme|ext)-([a-z0-9][a-z0-9-]{1,40})", slug or "")
        if not m:
            return None
        want = f"{m.group(1)}:{m.group(2)}"
        pool = self.external() if m.group(1) == "ext" else self.items()
        return next((i for i in pool if i["id"] == want), None)

    def thumb_of(self, i: dict) -> str:
        """The item's preview thumbnail URL (our own copy of its GitHub preview image) when it has one and the file is
        on this site, else ""."""
        if thumb_problem(i) or "thumb" not in i:
            return ""
        have = self.portal("art_present")
        try:
            ok = have is None or bool(have(i["thumb"][len("/wrath/art/"):]))
        except Exception:   # noqa: BLE001
            ok = False
        return i["thumb"] if ok else ""

    @staticmethod
    def gen_art(i: dict, name: str, icon: str = "mods", cls: str = "hb-gt-art gen") -> str:
        """The tile drawn from an item's id (the same id, the same tile): a gradient, its initial and a kind icon."""
        h = hashlib.sha256(str(i["id"]).encode()).digest()
        h1 = 200 + h[0] % 90
        h2 = (h1 + 40 + h[1] % 80) % 360
        return (f'<span class="{cls}" style="--h1:{h1};--h2:{h2};--a:{h[2] % 180}deg" aria-hidden="true">'
                f'<b>{html.escape((name or "?")[:1].upper())}</b><svg viewBox="0 0 24 24">{NAV_ICONS.get(icon, NAV_ICONS["mods"])}</svg></span>')

    # ---------------------------------------------------------------- the launcher feed
    def feed(self) -> bytes:
        """The merged catalog in the all.json shape (mods/all-json.md) plus the hub fields (docs/HUB-INDEX.md)."""
        host = self.portal("PUBLIC_HOST") or "play.openvanilla.app"
        base = f"https://{host}"
        projects = []
        for i in self.items():
            if i["source"] == "workshop":
                p = dict(i["ws"])
                p.update({"link_out": not i["packaged"], "hub_page": base + BASE + "/p/" + _slug(i["id"])})
                projects.append(p)
                continue
            link = i["source"] == "index"
            projects.append({
                "id": i["id"], "source": "community" if link else "theme", "hub_source": i["source"],
                "name": i["name"], "description": i["summary"] if link else i["description"],
                "repo_description": i.get("description", "") if link else "",
                "category": i["category"], "builds": i["builds"], "author": i["author"],
                "author_url": f"https://{i['repo'].split('/')[2]}/{i['owner']}" if link else "",
                "licence": i["licence"], "repo": i["repo"], "page": base + BASE + "/p/" + _slug(i["id"]),
                "hub_page": base + BASE + "/p/" + _slug(i["id"]),
                "credits": f"{i['name']} by {i['author']} · {i['licence'] or 'licence not stated'}"
                           + (f" · {i['repo'].split('/')[2]}" if i.get("repo") else ""),
                "stars": i.get("stars"), "last_push": i.get("updated") or "",
                "submitted_by": "", "submitted_at": "", "last_checked": "",
                "version": None, "kind": None, "permissions": None, "on_wrath": None,
                "download": None if link else i.get("download"), "sha256": None if link else i.get("sha256"),
                "link_out": link, "type": i.get("type"), "score": i.get("score"), "archived": bool(i.get("archived")),
                "needs": i.get("needs", "") if link else "", "forge": i.get("forge", "") if link else "",
            })
        projects.sort(key=lambda p: (str(p.get("name", "")).lower(), str(p.get("id"))))
        cats = self.categories()
        doc = {"format": 1, "hub": 1, "generated_at": _iso_now(),
               "categories": cats + ([] if any(c["id"] == THEMES[0] for c in cats) else
                                     [{"id": THEMES[0], "name": THEMES[1], "line": "Looks for the Leyline launcher.",
                                       "icon": "palette"}]),
               "builds": offered_builds() + ["any"], "projects": projects}
        return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")

    def categories(self) -> list[dict]:
        ws = self.portal("workshop")
        if ws is not None:
            try:
                cats = ws.categories()[0]
                if cats:
                    return [{k: c.get(k, "") for k in ("id", "name", "line", "icon")} for c in cats]
            except Exception:   # noqa: BLE001
                pass
        return [{"id": c, "name": n, "line": "", "icon": ""} for c, n in CATEGORIES]

    # ---------------------------------------------------------------- pages
    # ---------------------------------------------------------------- the look (owner 2026-10-30, after his mockup)
    # Flat and dark like the launcher (the portal's LOOK_VARS and SPIN_CSS, HUB_CSS): a header with the spinning mark
    # and the Leyline / Launcher wordmark, the site's sign-in; a footer with the real links only. No script.
    def _download(self) -> str:
        """The Leyline launcher's download: the stable release the admin console published (channel.json), else the
        releases page the launcher docs link (docs/leyline/launcher.md)."""
        adm = self.portal("admin")
        try:
            st = (adm.channel_doc() or {}).get("stable") if adm is not None else None
            url = _https((st or {}).get("url"))
            if url.startswith(RELEASES + "/"):
                return url
        except Exception:   # noqa: BLE001: the releases page then
            pass
        return RELEASES

    def _spin(self, size: int, cls: str = "", label: str = "") -> str:
        sp = self.portal("spin")
        if sp is not None:
            return sp(size, cls, label)
        return f'<span class="ly-spin {cls}" style="--ly-spin-size:{int(size)}px" aria-hidden="true"></span>'

    def _wordmark(self) -> str:
        return f'{self._spin(52, "slow hb-mark")}<span class="hb-word"><b>Leyline</b><i>Launcher</i></span>'

    def nav_items(self) -> tuple[list, list]:
        """The header's items, the launcher's pages on the web (owner 2026-10-30: "it should have servers, mods, addons,
        etc ... cause it should all work in browser too"): (main, more). Each (key, label, href, icon)."""
        home = FRONT if front_on() else BASE
        main = [("play", "Play", "/wrath", "play"), ("realms", "Realms", BASE + "/realms", "realms"),
                ("mods", "Mods", BASE + "/catalog", "mods"), ("addons", "Addons", BASE + "/catalog?cat=addons", "addons"),
                ("modes", "Modes", BASE + "/modes", "modes"), ("host", "Host", "/wrath/host", "host"),
                ("community", "Community", "/wrath/workshop", "community")]
        more = [("gallery", "Gallery", home + "/gallery", "gallery"), ("docs", "Docs", "/wrath/docs", "docs"), ("news", "News", BASE + "/news", "news"),
                ("creators", "Creators", BASE + "/creators", "creators"), ("status", "Status", home + "#status", "status")]
        return main, more

    def _header(self, active: str) -> str:
        e = html.escape
        home = FRONT if front_on() else BASE
        main, more = self.nav_items()

        def item(key, label, href, icon, cls="hb-ni"):
            on = key == active
            return (f'<a class="{cls}{" on" if on else ""}" href="{e(href)}"' + (' aria-current="page"' if on else "")
                    + f'><svg viewBox="0 0 24 24" aria-hidden="true">{NAV_ICONS[icon]}</svg><span>{e(label)}</span></a>')
        more_on = any(k == active for k, *_ in more)
        drop = (f'<details class="hb-more-d"><summary class="hb-ni{" on" if more_on else ""}">'
                f'<svg viewBox="0 0 24 24" aria-hidden="true">{NAV_ICONS["more"]}</svg><span>More</span></summary>'
                '<div class="hb-more-m">' + "".join(item(*m, cls="hb-mi") for m in more) + "</div></details>")
        extra = '<div class="hb-nav-x">' + "".join(item(*m) for m in more) + "</div>"
        who = getattr(_REQ, "who", None)
        if who:
            name = clean_name(who[1] or who[0]) or "Account"
            acct = (f'<a class="hb-acct" href="/wrath/account" aria-label="Your account: {e(name)}">'
                    f'<span class="hb-av" aria-hidden="true">{e(name[:1].upper())}</span><span class="hb-acct-n">{e(name)}</span></a>')
        else:
            acct = ('<a class="hb-signin" href="/login?next=%2Fwrath"><img src="/wrath/art/leyline-crystal-128.png" alt="" width="26" height="26">'
                    'Sign In</a>')
        dl = self._download()
        dl_a = (f'<a class="hb-dl" href="{e(dl)}" rel="noopener noreferrer"><svg viewBox="0 0 24 24" aria-hidden="true">'
                f'{NAV_ICONS["download"]}</svg>Download</a>')
        return (f'<header class="hb-top"><a class="hb-brand" href="{home}" aria-label="Leyline Launcher">{self._wordmark()}</a>'
                '<input type="checkbox" id="hb-menu" class="hb-menu-t" aria-label="Menu">'
                '<label for="hb-menu" class="hb-menu-b" aria-hidden="true">Menu</label>'
                f'<nav class="hb-nav" aria-label="Leyline">{"".join(item(*m) for m in main)}{drop}{extra}'
                f'<a class="hb-dl-x" href="{e(dl)}" rel="noopener noreferrer">Download the launcher</a></nav>'
                f'<div class="hb-end">{dl_a}{acct}</div></header>')

    def _shell(self, title: str, body: str, path: str, nonce: str = "", active: str | None = None) -> bytes:
        """The page around body. nonce: the CSP nonce for HUB_JS (the front page and the realm list); "" for no script.
        active: the header item to highlight (default: from path)."""
        e = html.escape
        front = path in (BASE, FRONT)
        home = FRONT if front_on() else BASE
        dl = self._download()
        top = self._header(ACTIVE.get(path.split("?")[0], "mods" if path.startswith(BASE + "/p/") else "") if active is None else active)
        sub = "" if front else (f'<nav class="hb-sub" aria-label="Hub">'
               + "".join(f'<a href="{BASE}{h}"' + (' aria-current="page" class="on"' if path == BASE + h else "") + f">{t}</a>"
                         for h, t in (("", "Hub"), ("/realms", "Realms"), ("/modes", "Modes"), ("/catalog", "Catalog"), ("/gallery", "Gallery"),
                                      ("/news", "News"), ("/creators", "Creators"), ("/beacon", "Host a Beacon"),
                                      ("/submit", "Submit a mod")))
               + "</nav>")
        flag = '<p class="hb-flag">Preview: this page is hidden while it is being built.</p>' if not front_on() else ""
        repo = self.portal("LEYLINE_REPO") or "https://github.com/orionopenwow/Leyline"
        discord = self.portal("DISCORD_URL") or ""
        foot_links = [("Docs", "/wrath/docs"), ("Download", dl), ("Community", f"{home}#community"), ("Status", f"{home}#status"),
                      ("Catalog", f"{BASE}/catalog"), ("Creators", f"{BASE}/creators"), ("Submit a mod", f"{BASE}/submit")]
        social = ([("Discord", discord)] if discord else []) + [("GitHub", repo)]
        hs = self.health_state()
        health = (f'<a class="hb-health {hs}" href="{home}#status"><span class="hb-hdot" aria-hidden="true"></span>'
                  f'{HEALTH_WORDS[hs]}</a>') if hs else ""
        foot = ('<footer class="hb-foot"><div class="hb-foot-in">' + health +
                '<nav class="hb-foot-links" aria-label="More">'
                + "".join(f'<a href="{e(h)}"' + (' rel="noopener noreferrer"' if h.startswith("http") else "") + f">{e(t)}</a>"
                          for t, h in foot_links) + '</nav>'
                f'<div class="hb-foot-row"><a class="hb-brand small" href="{home}" aria-label="Leyline Launcher">{self._wordmark()}</a>'
                '<p class="hb-foot-fine">Open source. No shop, nothing to buy. Bots are labelled.</p>'
                '<nav class="hb-social" aria-label="Elsewhere">'
                + "".join(f'<a href="{e(h)}" rel="noopener noreferrer">{e(t)}</a>' for t, h in social)
                + '</nav></div></div></footer>')
        robots = "" if front_on() else '<meta name="robots" content="noindex">'
        meta = ('<meta name="description" content="Leyline: one launcher for your own game clients and every realm, '
                'with mods, addons, realm scripts and tools.">')
        css = (self.portal("LOOK_VARS") or LOOK_FALLBACK) + (self.portal("SPIN_CSS") or "") + HUB_CSS
        return (f'<!doctype html><html lang="en" data-look="leyline"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
                f'<title>{e(title)}</title>{meta}{robots}<style>{css}</style></head>'
                f'<body class="hb"><a class="hb-skip" href="#main">Skip to content</a>{top}'
                f'<main id="main" class="hb-main{" hb-front" if front else ""}">{flag}{sub}{body}</main>{foot}'
                + (f'<script nonce="{e(nonce)}">{HUB_JS}</script>' if nonce else "") + '</body></html>').encode("utf-8")

    def status_cards(self) -> str:
        """Platform Status: live values only, read when the page is made (no script). A source this portal doesn't
        have is left out; one that fails says so in red."""
        e = html.escape
        cards, oks = [], []

        def card(name, line, ok, href="", tail=""):
            if ok is not None:
                oks.append(bool(ok))
            word = "OK" if ok is True else ("Offline" if ok is False else "")
            cls = "ok" if ok is True else "bad" if ok is False else ""
            tag = f'a href="{e(href)}"' if href else "div"
            cards.append(f'<{tag} class="hb-stat"><b>{e(name)}</b><span>{e(line)}'
                         + (f' <em class="{cls}">{word}</em>' if word else "") + e(tail) + f"</span></{tag.split()[0]}>")
        rs = self.portal("realm_status")
        try:
            st = rs() if rs else None
        except Exception:   # noqa: BLE001
            st = None
        if st is not None:
            si = self.portal("sample_info")
            name = self.portal("REALM_NAME") or "Main realm"
            try:
                if self.portal("SAMPLER") and si:
                    name = si().get("name") or name
            except Exception:   # noqa: BLE001
                pass
            on = bool(st.get("online"))
            pl = st.get("players")
            card(neutral(name) or "Main realm", "Server:", on, "/wrath/realms", f" · {int(pl)} playing" if on and isinstance(pl, int) and pl >= 0 else "")
        health = self.portal("health")
        if health is not None:
            try:
                ok = bool(health()[0])
            except Exception:   # noqa: BLE001
                ok = False
            card("Sign-in", "Game logins:", ok)
        got = self._network()
        if got is not None:
            net, realms, ok, st2 = got
            t = net.totals(net.order(realms), st2)
            card("Realm network", net.network_line(t), None, BASE + "/realms")
            card("Relay", "Realm list:", bool(ok))
        items = self.items()
        n_ws = sum(1 for i in items if i["source"] == "workshop")
        card("Mod catalog", f"{len(items)} items · {n_ws} in the Workshop", None, BASE + "/catalog")
        state = ("ok" if all(oks) else "bad" if not any(oks) else "warn") if oks else ""
        self._health = (time.monotonic(), state)
        return ('<section class="hb-sec" id="status" aria-labelledby="hb-st"><h2 id="hb-st">Platform Status</h2>'
                f'<div class="hb-stats">{"".join(cards)}</div></section>')

    def spotlight(self) -> str:
        """Community Spotlight: the top Hot and New items from the hub rankings (stream/hub_rank.py), else the index's
        best scores. Real items only: name, author, their own short line, a Workshop screenshot when there is one."""
        e = html.escape
        items = [i for i in self.items() if i["source"] != "theme"]
        if not items:
            return ""
        picks, labels = [], {}
        rk = self.portal("hub_rank")
        store = getattr(rk, "store", None) if rk is not None else None
        if store is not None:
            for sort, label in (("hot", "Hot"), ("new", "New")):
                try:
                    ranked = store.ranked(items, sort)
                except Exception:   # noqa: BLE001
                    ranked = []
                for i, _m in ranked:
                    if i["id"] not in labels:
                        picks.append(i); labels[i["id"]] = label
                        if sum(1 for v in labels.values() if v == label) >= 2:
                            break
        if not picks:
            for i in sorted(items, key=lambda i: (-float(i.get("score") or 0), i["name"].lower()))[:4]:
                picks.append(i); labels[i["id"]] = "Top"
        cards = []
        for i in picks[:4]:
            shot = ""
            if self.shot_count(i):
                shot = f'<img src="/wrath/mods/{e(i["id"][4:])}/shot/0" alt="" loading="lazy" width="160" height="100">'
            elif self.thumb_of(i):
                shot = (f'<img src="{e(self.thumb_of(i))}" alt="" loading="lazy" width="160" height="80" '
                        f'title="{e(THUMB_CREDIT)}">')
            name = neutral(i["name"]) or "Untitled"
            pic = shot or f'<span class="hb-initial" aria-hidden="true">{e(name[:1].upper())}</span>'
            line = neutral(i.get("summary") or i.get("description") or "")
            cards.append(f'<a class="hb-spot" href="{BASE}/p/{_slug(i["id"])}"><span class="hb-pic">{pic}</span>'
                         f'<span class="hb-spot-t"><small>{e(labels[i["id"]])}</small><b>{e(name)}</b>'
                         f'<i>by {e(neutral(i["author"]) or "unknown")}</i><span>{e(line)}</span></span></a>')
        return ('<section class="hb-sec" id="community" aria-labelledby="hb-cs"><h2 id="hb-cs">Community Spotlight</h2>'
                f'<div class="hb-spots">{"".join(cards)}</div>'
                f'<p class="hb-more"><a href="{BASE}/catalog">Browse the whole catalog</a></p></section>')

    # ---------------------------------------------------------------- the realm list (the sub hero and /realms)
    def realm_rows(self, query: dict | None = None):
        """(rows, network totals, fresh, filters, facets) for every realm on the network, or None without a realm list.
        The order: the home realm (ours) first, then the network's own order (stream/network.py order(), the same as the
        launcher's realms.rs): featured, the other live realms by the fair score and players, offline ones last.
        Builds above 3.3.5a are left out (MAX_OFFERED_BUILD). query: the realm list's filters (?build, ?tag, ...)."""
        got = self._network()
        if got is None:
            return None
        net, realms, ok, st = got
        shown = net.order(realms)
        t = net.totals(shown, st)
        si = self.portal("sample_info")
        try:
            sample = si() if si else {}
        except Exception:   # noqa: BLE001
            sample = {}
        f = net.filters_from(query or {})
        cl = ((query or {}).get("client") or [""])[0]
        if cl in dict(CLIENT_FILTER):
            f["client"] = cl
        rec = next((r for r in shown if r["sample"]), None) or {}
        live = bool(st.get("online")) if st else bool(rec.get("live"))
        players = st.get("players") if st and isinstance(st.get("players"), int) else rec.get("players")
        bots = st.get("bots") if st and isinstance(st.get("bots"), int) else rec.get("bots")
        home = {**rec, "home": True, "official": True, "live": live, "players": players, "bots": bots, "build": BROWSER_BUILD,
                "name": sample.get("name") or self.portal("REALM_NAME") or "Official realm",
                "temporary": bool(sample.get("temporary")), "featured": False, "new": False, "group": "home",
                "address": self.portal("PUBLIC_HOST") or "play.openvanilla.app"}
        fits = lambda r: net.matches(r, f) and f.get("client") in (None, client_of(r))   # noqa: E731
        rows = [home] if fits(home) else []
        for r in shown:
            if r["sample"] or not fits(r):
                continue
            port, relay = r.get("port"), r.get("relay") or "relay.openvanilla.app"
            rows.append({**r, "home": False, "address": f"{relay}:{port}" if port else ""})
        return rows, t, ok, f, net.facets([r for r in shown if not r["sample"]])

    def realm_row(self, r: dict) -> str:
        e = html.escape
        net = self.portal("network")
        client = client_of(r)
        name = neutral(r.get("name")) or "A realm"
        bdg = []
        if r.get("home") or r.get("official"):
            bdg.append('<span class="hb-bdg o">Official</span>')
        if r.get("temporary"):
            bdg.append('<span class="hb-bdg">Temporary</span>')
        if r.get("featured"):
            bdg.append('<span class="hb-bdg f">Featured</span>')
        if r.get("verified"):
            bdg.append('<span class="hb-bdg v" title="Checked by Leyline staff">Verified</span>')
        if r.get("new"):
            bdg.append('<span class="hb-bdg">New</span>')
        meta = [COMPAT[client], net.CORES.get(r.get("core"), "AzerothCore")]
        reg, est = net.region_of(r)
        if reg:
            meta.append(net.REGION_LABEL[reg] + (" (est.)" if est else ""))
        meta += [TAG_WORDS.get(t, net.TAG_LABEL[t]) for t in r.get("tags") or [] if t in net.TAG_LABEL and t != "hangout"]
        up = r.get("up7") if r.get("up7") is not None else r.get("up24")
        if up is not None:
            meta.append(f"{up}% up")
        live = bool(r.get("live"))
        players = r.get("players") if isinstance(r.get("players"), int) else None
        if not live:
            count = '<div class="hb-rl-p off">Offline</div>'
        elif players is None:
            count = '<div class="hb-rl-p"><span class="hb-dot" aria-hidden="true"></span>Online</div>'
        else:
            bots = r.get("bots") or 0
            count = (f'<div class="hb-rl-p"><span class="hb-dot" aria-hidden="true"></span><b class="hb-n">{players}</b> playing'
                     f'<small class="hb-bots">{f"{bots} bots" if bots else ""}</small></div>')
        acts = []
        if live and client == "browser":
            href = "/wrath" if r.get("home") else f'/wrath?go=r:{r["id"]}'
            acts.append(f'<a class="hb-play" href="{e(href)}" aria-label="Play {e(name)} in your browser">Play in browser</a>')
        if REALM_DEEPLINK and (r.get("home") or r.get("id")):
            rid = "official" if r.get("home") else r["id"]
            acts.append(f'<a class="hb-ghost" href="{e(REALM_DEEPLINK.format(id=rid))}">Open in launcher</a>')
        if r.get("address"):
            acts.append(f'<code class="hb-addr" title="The realm address for a desktop client">{e(r["address"])}</code>')
        rid = r.get("id") or ""
        data = ' data-home="1"' if r.get("home") else (f' data-rid="{e(rid)}"' if rid else "")
        # the hover / focus preview: the realm's own tagline and its tags, laid over the rows below (no layout shift)
        line = neutral(r.get("tagline"), 120) or ("The official realm: one click and you are in, in this browser."
                                                  if r.get("home") else "")
        tags = [TAG_WORDS.get(t, net.TAG_LABEL[t]) for t in r.get("tags") or [] if t in net.TAG_LABEL]
        pv = (f'<div class="hb-rl-pv" role="note">' + (f"<p>{e(line)}</p>" if line else "")
              + (f'<p class="hb-rl-pt">{"".join(f"<span>{e(t)}</span>" for t in tags)}</p>' if tags else "")
              + "</div>") if line or tags else ""
        return (f'<li class="hb-rl{" home" if r.get("home") else ""}{" pv" if pv else ""}"{data} data-client="{client}" '
                f'data-live="{1 if live else 0}" data-players="{players or 0}"><div class="hb-rl-n"><b>{e(name)}</b>{"".join(bdg)}'
                f'<span class="hb-rl-m">{e(" · ".join(meta))}</span></div>{count}'
                f'<div class="hb-rl-a">{"".join(acts)}</div>{pv}</li>')

    def realm_section(self, got=None) -> str:
        """The sub hero: every server on the network, the home realm first, one click to play. "" without a list."""
        got = self.realm_rows() if got is None else got
        if not got:
            return ""
        e = html.escape
        rows, t, ok, _f, fc = got
        net = self.portal("network")
        shown = rows[:FRONT_REALMS]
        opts = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in CLIENT_FILTER)
        form = (f'<form class="hb-rf" method="get" action="{BASE}/realms" data-rf="hb-rlist" aria-label="Filter realms">'
                f'<label>Play <select name="client"><option value="">Any</option>{opts}</select></label>'
                '<label><input type="checkbox" name="now" value="1"> Has players</label>'
                '<button type="submit">Filter</button></form>')
        more = len(rows) > 8
        stale = "" if ok else '<p class="hb-fine">The community list may be a little out of date right now.</p>'
        return ('<section class="hb-sec hb-realms" id="realms" aria-labelledby="hb-rlh">'
                f'<div class="hb-rl-head"><div><h2 id="hb-rlh">Realms on the network</h2>'
                f'<p class="hb-netline" data-net>{e(net.network_line(t))}</p></div>{form}</div>'
                f'<ul class="hb-rlist{" cap" if more else ""}" id="hb-rlist">{"".join(self.realm_row(r) for r in shown)}</ul>'
                '<p class="hb-rl-none" hidden>No realms match. Try Any, or everyone.</p>' + stale +
                f'<p class="hb-more"><a href="{BASE}/realms">Every realm, with filters</a> · '
                '<a href="/wrath/host">Host your own</a></p></section>')

    def how_strip(self) -> str:
        e = html.escape
        steps = (("Get the launcher", "Free, for Windows, macOS and Linux"),
                 ("Point it at your game folder", "Or play in your browser, nothing to install"),
                 ("Pick a realm", "Any server on the list, one click"))
        return ('<!-- TODO(owner): the "how it works" wording -->'
                '<ol class="hb-how hb-rv" aria-label="How it works">'
                + "".join(f"<li><b>{e(a)}</b><span>{e(b)}</span></li>" for a, b in steps) + "</ol>")

    @staticmethod
    def _crest(size: int = 44) -> str:
        """A small crest of our own: the Leyline crystal inside a ring of eight studs (no shield, no game emblem)."""
        studs = "".join(f'<circle cx="{24 + 19.5 * math.cos(k * math.pi / 4):.2f}" cy="{24 + 19.5 * math.sin(k * math.pi / 4):.2f}" r="1.3"/>'
                        for k in range(8))
        return (f'<svg class="hb-crest" viewBox="0 0 48 48" width="{size}" height="{size}" aria-hidden="true" focusable="false">'
                '<circle cx="24" cy="24" r="22" class="r1"/><circle cx="24" cy="24" r="17" class="r2"/>'
                f'<g class="st">{studs}</g><g transform="translate(13.6 9.6) scale(.65)">'
                '<polygon points="16,1.5 9,11 16,30.5" fill="#c9b2ff"/><polygon points="16,1.5 23,11 16,30.5" fill="#8b6cf0"/>'
                '<polygon points="9,11 16,30.5 5.5,13" fill="#5b3fc4"/><polygon points="23,11 16,30.5 26.5,13" fill="#4a2fa8"/>'
                '<polygon points="16,1.5 9,11 5.5,13" fill="#b9d0ff"/><polygon points="16,1.5 23,11 26.5,13" fill="#7aa3f5"/></g></svg>')

    @staticmethod
    def _rune_rule() -> str:
        """The ornamental divider: a line, small diamonds and dots, our own shapes (an SVG, no picture)."""
        return ('<div class="hb-rune" aria-hidden="true"><svg viewBox="0 0 64 14" width="64" height="14" focusable="false">'
                '<circle cx="3" cy="7" r="1.6" class="dt"/><path d="M14 7l3-3 3 3-3 3z" class="dm s"/><path d="M32 1l6 6-6 6-6-6z" class="dm"/>'
                '<path d="M44 7l3-3 3 3-3 3z" class="dm s"/><circle cx="61" cy="7" r="1.6" class="dt"/></svg></div>')

    def host_showcase(self) -> str:
        """The "Host a server" picture: the server software the host pack runs (HOST_CORES), one card each with what it is
        good for, its scripting, bots and the eras it covers (words, never client numbers), One click to host or Coming,
        "Your own" for any core on the relay, and the realm console's status strip. Slate cards, a rune rule, torch gold
        used sparingly, our crest from the Leyline crystal. Purely our own shapes and colours."""
        e = html.escape
        cards = []
        for cid, name, status, eras, line, script, bots in HOST_CORES:
            live = status == "live"
            chip = ('<span class="hb-sw-chip go">One click to host</span>' if live else '<span class="hb-sw-chip soon">Coming</span>')
            cards.append(f'<li class="hb-sw-c{"" if live else " soon"}" data-core="{cid}" data-status="{status}">'
                         f'<p class="hb-sw-h"><b>{e(name)}</b>{chip}</p><p class="hb-sw-l">{e(line)}</p>'
                         f'<p class="hb-sw-eras">{"".join(f"<span>{e(x)}</span>" for x in eras)}</p>'
                         f'<dl><dt>Scripting</dt><dd>{e(script)}</dd><dt>Bots</dt><dd>{e(bots)}</dd></dl></li>')
        cards.append(f'<li class="hb-sw-c own" data-core="own" data-status="own"><p class="hb-sw-h"><b>{e(HOST_OWN[0])}</b>'
                     f'<span class="hb-sw-chip">List it on the relay</span></p><p class="hb-sw-l">{e(HOST_OWN[1])}</p></li>')
        svc = "".join(f'<li><i></i>{e(x)}<span>{e(y)}</span></li>' for x, y in HOST_SERVICES)
        return ('<div class="hb-sw" role="group" aria-label="Server software Leyline hosts">'
                f'<div class="hb-sw-top">{self._crest()}<div><p class="hb-sw-k">The host pack</p><p class="hb-sw-t">Server software</p></div>'
                '<p class="hb-sw-run"><span aria-hidden="true"></span>Your realm · running</p></div>'
                f'{self._rune_rule()}<ul class="hb-sw-list">{"".join(cards)}</ul>{self._rune_rule()}'
                f'<ul class="hb-sw-svc" aria-label="The realm console">{svc}</ul></div>')

    def realm_list_art(self, got) -> str:
        """The "Realms & hopping" picture: a realm list in our own fantasy panel, from the live rows (realm_rows: ours
        first, then featured and the rest by players): Realm, Type (from its tags), Characters, Population (words from
        players online). Ours is selected and Recommended. Each row is a link to play it, as on the realm list; a dimmed
        "Your realm here" row invites hosting when the list is short."""
        e = html.escape
        rows = (got[0] if got else [])[:REALM_LIST_MAX]
        out = []
        for r in rows:
            name = neutral(r.get("name")) or "A realm"
            live = bool(r.get("live"))
            players = r.get("players") if isinstance(r.get("players"), int) else None
            typ, tcls = realm_type(r.get("tags"))
            pop, pcls = population(live, players)
            home = bool(r.get("home"))
            if home and live:
                pop, pcls = "Recommended", "rec"
            client = client_of(r)
            if live and client == "browser":
                href, how = ("/wrath" if home else f'/wrath?go=r:{r["id"]}'), "Play in your browser"
            elif REALM_DEEPLINK and (home or r.get("id")):
                href, how = REALM_DEEPLINK.format(id="official" if home else r["id"]), "Open in the launcher"
            else:
                href, how = BASE + "/realms", "See it on the realm list"
            chars = '<span class="hb-rlx-ch" title="Your characters show once you sign in">–</span>'
            out.append(f'<li><a class="hb-rlx-r{" sel" if home else ""}{"" if live else " off"}" href="{e(href)}"'
                       + (' aria-current="true"' if home else "")
                       + f' aria-label="{e(name)}: {e(typ)}, population {e(pop)}. {e(how)}" data-type="{tcls}" data-pop="{pcls}">'
                       f'<span class="hb-rlx-n">{e(name)}</span><span class="hb-rlx-t {tcls}">{e(typ)}</span>{chars}'
                       f'<span class="hb-rlx-p {pcls}">{e(pop)}</span></a></li>')
        if len(rows) < REALM_LIST_MAX:
            out.append('<li><a class="hb-rlx-r you" href="/wrath/host" data-type="pve" data-pop="none">'
                       '<span class="hb-rlx-n">Your realm here</span><span class="hb-rlx-t">Host one</span>'
                       '<span class="hb-rlx-ch">–</span><span class="hb-rlx-p">Open</span></a></li>')
        return ('<div class="hb-rlx" role="group" aria-labelledby="hb-rlx-h">'
                f'<div class="hb-rlx-top">{self._crest(34)}<p class="hb-rlx-h" id="hb-rlx-h">Realm list</p></div>{self._rune_rule()}'
                '<p class="hb-rlx-cols" aria-hidden="true"><span>Realm</span><span>Type</span><span>Characters</span>'
                f'<span>Population</span></p><ul class="hb-rlx-l">{"".join(out)}</ul>'
                f'<p class="hb-rlx-f"><a href="{BASE}/realms">Every realm, with filters</a><a href="/wrath">Play ours now</a></p></div>')

    def modes_art(self, shot) -> str:
        """The "Game modes" picture: the owner's Minigolf recording (our mode on our realm) as a muted loop that HUB_JS
        plays only while it is on screen (the poster alone with reduced motion or Save-Data; without script the poster
        and a Play link). With the game data killswitch on: the launcher's Modes page instead."""
        e = html.escape
        have = self.portal("art_present")

        def ok(n):
            try:
                return have is None or bool(have(n))
            except Exception:   # noqa: BLE001
                return False
        names = ("leyline-shot-minigolf.webp", "leyline-shot-minigolf.webm", "leyline-shot-minigolf.mp4")
        if not self.game_shots_on() or not all(ok(n) for n in names):
            return shot("modes", "The launcher's Modes page: minigames and game modes with one PLAY button each.")
        poster, webm, mp4 = ("/wrath/art/" + n for n in names)
        return ('<figure class="hb-shot hb-vid">'
                f'<video muted loop playsinline preload="none" poster="{poster}" width="820" height="596" data-hb-vid '
                'aria-label="Minigolf on our own realm: a ball rolls down a green fairway toward the flag, in a red desert canyon.">'
                f'<source src="{webm}" type="video/webm"><source src="{mp4}" type="video/mp4"></video>'
                f'<figcaption><span>Minigolf, on our own realm</span><a class="hb-vid-play" href="{e("/wrath?go=mode:minigolf")}">'
                'Play</a></figcaption></figure>')

    def features(self, got=None) -> str:
        """The feature sections, one per part of Leyline, in the recommended order (after the original site's big
        alternating showcases: #server-software, #desktop-launcher, #forge, #agents): words on one side, a picture on
        the other, the sides flipping each time, stacked on a phone. Pictures are launcher screenshots (tools/art/
        leyline-ui-shots.cjs: the launcher's own pages with sample data, no client numbers) or small CSS drawings."""
        e = html.escape
        got = self.realm_rows() if got is None else got
        pm = self.portal("playmodes")
        try:
            live = [neutral(m["title"]) for m in (pm.entries() if pm is not None else []) if m["status"] == "live"][:3]
        except Exception:   # noqa: BLE001
            live = []
        modes_line = (", ".join(live) + " and more, one click each") if live else "Minigames and game modes, one click each"
        rk = self.portal("hub_rank")
        discord = self.portal("DISCORD_URL") or ""
        dl = self._download()

        def shot(name, alt):
            return (f'<figure class="hb-shot"><img src="/wrath/art/leyline-ui-{name}.webp" alt="{e(alt)}" width="1240" '
                    'height="760" loading="lazy" decoding="async"></figure>')
        host_art = self.host_showcase()
        community_art = ('<div class="hb-draw hb-people" aria-hidden="true">'
                         + "".join(f'<p class="hb-pp"><i style="--h:{h}">{c}</i><b>{t}</b><span>{s}</span></p>' for h, c, t, s in (
                             (220, "Q", "Quest Lens", "New in the Workshop"), (265, "L", "Lantern Isle", "A realm opened tonight"),
                             (160, "M", "Minigolf course", "Built by players"), (300, "D", "Discord", "Where everyone meets")))
                         + "</div>")
        agents_art = ('<pre class="hb-draw hb-code" aria-hidden="true"><code><s>GET</s> /wrath/leyline/catalog.json\n\n'
                      '{ <u>"name"</u>: <q>"Quest Lens"</q>,\n  <u>"category"</u>: <q>"addons"</q>,\n'
                      '  <u>"licence"</u>: <q>"MIT"</q>,\n  <u>"link_out"</u>: <s>false</s>,\n'
                      '  <u>"credits"</u>: <q>"Quest Lens by Leyline"</q> }</code></pre>')
        # TODO(owner): the order of the products and their wording (this order is the recommendation; move the rows)
        secs = [
            ("launcher", "Desktop launcher", "Play, mod and meet up in one app",
             "Leyline is the one program you start. It finds the game folders you already have, signs you in once, "
             "installs mods in a click, takes you to any realm and keeps itself up to date.",
             ["Your own clients, found for you", "One sign-in everywhere", "Updates in the background, never mid-game",
              "Windows, macOS and Linux"],
             [(dl, "Download the launcher", True), ("/wrath", "Play in your browser", False)],
             shot("home", "The Leyline launcher's home page: the server, your account, your game client and the PLAY button.")),
            ("host", "Host a server", "Host your own realm in one click",
             "Run a realm from your own PC, on any core. The host pack is everything a host needs in one download: the "
             "scripts, the realm tools and the relay agent. Our code only, never game files.",
             ["Any core, your rules, your GM login", "No port forwarding: the relay lists it",
              "Start from the website or the launcher's Host page", "An invite link for friends"],
             [("/wrath/host", "Start hosting", False), (BASE + "/beacon", "Host a Beacon", False)], host_art),
            ("realms", "Realms & hopping", "Every realm, one list",
             "Every server on the Leyline network, hosted by players and ranked by players online, uptime and staff "
             "picks. Nothing can be bought. Hop from one realm to the next in a click.",
             ["Plays in your browser, or with your own client", "Filters for rules, region and language",
              "Hero Key sign-in across realms (coming)"],
             [(BASE + "/realms", "See the realms", False)], (self.realm_list_art(got) if got else
                                                            shot("realms", "The launcher's Realms page: every realm on the network with its players, uptime and badges."))),
            ("modes", "Game modes", "Minigames and modes, one click",
             modes_line + ". PLAY signs you in and starts the game once your character is in the world.",
             ["Made by players, checked by a GM", "Host a mode as a whole realm type", "The same list in the launcher"],
             [(BASE + "/modes", "Play a mode", False)], self.modes_art(shot)),
            ("mods", "Mods & the Workshop", "Hot, rising and top picks",
             "Addons, realm scripts, tools and themes, sorted by what players install and rate. Install in one click with "
             "the launcher; open projects from anywhere are linked with credit to their authors.",
             ["One-click install, every package checked", "Rate what you play", "Submit your own project with a link"],
             [(BASE + "/catalog" + ("?sort=hot" if rk is not None else ""), "Browse mods", False),
              (BASE + "/submit", "Submit a mod", False)],
             shot("workshop", "The launcher's Discover page: Workshop mods sorted by Hot, with ratings, installs and Install.")),
            ("community", "Community hub", "What players make, together",
             "The people behind the realms and mods, what they made this week and where they meet. Every project "
             "belongs to its authors, under the licence they chose.",
             ["Community Spotlight, from real rankings", "News from the launcher and the realms"]
             + (["The Discord, linked from everywhere"] if discord else []),
             [("/wrath/workshop", "Explore", False), (BASE + "/news", "News", False)], community_art),
            ("agents", "Agents & tooling", "Build on Leyline",
             "The creator docs, the package format and an open catalog feed any tool can read. Make an addon, a realm "
             "script or a whole mode, and bring your own helpers to build it.",
             ["Open source, open data", "A public JSON feed, no key needed", "The docs for modes, realms and hosting"],
             [(BASE + "/creators", "Start building", False), ("/wrath/docs", "Read the docs", False)], agents_art),
        ]
        out = []
        for n, (icon, eyebrow, title, lede, points, acts, art) in enumerate(secs):
            btns = "".join(f'<a class="{"hb-cta sm" if k == 0 else "hb-ghost"}" href="{e(h)}"'
                           + (' rel="noopener noreferrer"' if ext or h.startswith("http") else "") + f">{e(t)}</a>"
                           for k, (h, t, ext) in enumerate(acts))
            out.append(f'<section class="hb-fs hb-rv{" flip" if n % 2 else ""}" id="f-{icon}" aria-labelledby="hb-f-{icon}">'
                       f'<div class="hb-fs-t"><p class="hb-eyebrow"><span class="hb-ico"><svg viewBox="0 0 24 24" aria-hidden="true">'
                       f'{ICONS[icon]}</svg></span>{e(eyebrow)}</p><h2 id="hb-f-{icon}">{e(title)}</h2><p class="hb-lede">{e(lede)}</p>'
                       f'<ul class="hb-points">{"".join(f"<li>{e(x)}</li>" for x in points)}</ul>'
                       f'<p class="hb-fs-a">{btns}</p></div><div class="hb-fs-v">{art}</div></section>')
        # the ley line: a faint thread down the left of the sections, drawn as you scroll (HUB_JS); fully drawn without
        # script or with reduced motion; never takes a click; hidden where the page is too narrow for a margin
        thread = ('<svg class="hb-thread" viewBox="0 0 40 1000" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
                  '<defs><linearGradient id="hb-tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5b8def"/>'
                  '<stop offset="1" stop-color="#8b6cf0"/></linearGradient></defs>'
                  '<path pathLength="1" d="M20 0 C34 70 6 110 20 180 S34 290 20 360 S6 470 20 540 S34 650 20 720 S6 830 20 900 S30 970 20 1000"/></svg>')
        return ('<div class="hb-feats" id="features"><h2 class="hb-vh">Everything in Leyline</h2>' + thread
                + "".join(out) + "</div>")

    # ---------------------------------------------------------------- the front page's live and community parts
    def ticker(self, got) -> str:
        """The live band under the hero, from the realm list's own rows: who is playing where, and new realms. The moving
        copy is aria-hidden; screen readers get the first copy as a plain list. HUB_JS updates the counts (data-tick)."""
        if not got:
            return ""
        e = html.escape
        rows = got[0]
        live = sorted((r for r in rows if r.get("live") and isinstance(r.get("players"), int) and r["players"] > 0),
                      key=lambda r: -r["players"])[:8]
        out = []
        for r in live:
            name = neutral(r.get("name")) or "a realm"
            key = 'data-tick="home"' if r.get("home") else f'data-tick="{e(r.get("id") or "")}"'
            hang = r.get("hangout") or "hangout" in (r.get("tags") or []) or "hangout" in name.lower()
            where = (f'in {"" if name.lower().startswith("the ") else "the "}{e(name)}' if hang else f"playing on {e(name)}")
            out.append(f'<li {key}><b class="hb-tn">{int(r["players"])}</b> {where}</li>')
        for r in [r for r in rows if r.get("new") and not r.get("home")][:2]:
            out.append(f'<li class="new">New realm: {e(neutral(r.get("name")) or "a realm")}</li>')
        if not out:
            return ""
        items = "".join(out)
        return ('<section class="hb-tick" aria-labelledby="hb-tick-h"><h2 id="hb-tick-h" class="hb-vh">Live on the network</h2>'
                f'<div class="hb-tick-run"><ul class="hb-tick-l">{items}</ul>'
                f'<ul class="hb-tick-l dup" aria-hidden="true">{items}</ul></div></section>')

    def featured_mod_ok(self) -> bool:
        """The featured modpack's screenshot may show: game pictures are on (the killswitch is off) and the file is there."""
        if not self.game_shots_on():
            return False
        have = self.portal("art_present")
        try:
            return have is None or bool(have(f"leyline-shot-{FEATURED_MOD['key']}.webp"))
        except Exception:   # noqa: BLE001
            return False

    def featured_mod(self) -> str:
        """The wide featured-mod showcase under the numbers: the modpack's screenshot full-bleed under a soft vignette, the
        words on a panel over it (under it on a phone), a link out (its authors host it; no Install: we neither host nor
        check it). Hidden with the game data killswitch. HUB_JS eases the picture as it scrolls by (never with reduced
        motion)."""
        if not self.featured_mod_ok():
            return ""
        e = html.escape
        f = FEATURED_MOD
        src = f"/wrath/art/leyline-shot-{f['key']}.webp"
        return ('<section class="hb-coa hb-rv" id="featured-mod" aria-labelledby="hb-coa-h">'
                f'<div class="hb-coa-pic"><img src="{src}" alt="{e(f["alt"])}" width="{f["w"]}" height="{f["h"]}" loading="lazy" '
                'decoding="async"></div><div class="hb-coa-in"><div class="hb-coa-t">'
                f'<p class="hb-coa-k"><span aria-hidden="true"></span>{e(f["label"])}</p><h2 id="hb-coa-h">{e(f["title"])}</h2>'
                '<!-- TODO(owner): the featured modpack\'s final copy -->'
                f'<p class="hb-coa-l">{e(f["line"])}</p>'
                f'<p class="hb-coa-a"><a class="hb-cta sm" href="{e(f["url"])}" rel="{FEATURED_REL}" target="_blank">{e(f["button"])}'
                '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8M17 14v5H5V7h5"/></svg></a></p>'
                f'<p class="hb-coa-n">{e(f["note"])}</p></div>'
                f'<p class="hb-coa-cr">{e(f["credit"])}</p></div></section>')

    def counters(self, got, items: list) -> str:
        """Realms, players and mods: the final numbers in the page (no script, reduced motion: just these); HUB_JS counts
        up to them once when they scroll into view."""
        e = html.escape
        nums = []
        if got:
            t = got[1]
            nums += [(t["realms"], "realms online"), (t["players"], "players right now")]
        nums.append((sum(1 for i in items if i["source"] != "theme"), "mods, addons and tools"))
        return ('<section class="hb-nums hb-rv" aria-label="Leyline in numbers">'
                + "".join(f'<p><b class="hb-num" data-count="{int(n)}">{int(n)}</b><span>{e(t)}</span></p>' for n, t in nums)
                + "</section>")

    def _ranked(self, items: list):
        """(items in Hot order, metrics) from the hub rankings, or (best score first, {}) without them."""
        rk = self.portal("hub_rank")
        store = getattr(rk, "store", None) if rk is not None else None
        if store is not None:
            try:
                ranked = store.ranked(items, "hot")
                return [i for i, _m in ranked], {i["id"]: m for i, m in ranked}
            except Exception:   # noqa: BLE001
                pass
        return sorted(items, key=lambda i: (-float(i.get("score") or 0), i["name"].lower(), i["id"])), {}

    def mod_of_week(self, items: list) -> str:
        """The top Hot item (best score without rankings): its Workshop screenshot if any, author, one line, Install with
        Leyline (the launcher's leyline://install/<id>) and View."""
        e = html.escape
        pool = [i for i in items if i["source"] != "theme"]
        if not pool:
            return ""
        order, _m = self._ranked(pool)
        i = order[0]
        rk = self.portal("hub_rank")
        inst = rk.installable(i) if rk is not None and hasattr(rk, "installable") else bool(i.get("packaged"))
        name = neutral(i["name"]) or "Untitled"
        credit = ""
        if self.shot_count(i):
            pic = f'<img src="/wrath/mods/{e(i["id"][4:])}/shot/0" alt="A screenshot of {e(name)}" loading="lazy" width="320" height="200">'
        elif self.thumb_of(i):
            pic = f'<img src="{e(self.thumb_of(i))}" alt="The preview image of {e(name)}" loading="lazy" width="640" height="320">'
            credit = f'<p class="hb-th-cr">{e(THUMB_CREDIT)}</p>'
        else:
            pic = self.gen_art(i, name, KIND_WORDS[self._kind(i)][2])
        line = neutral(i.get("summary") or i.get("description") or "", 160)
        return ('<section class="hb-motw hb-rv" id="mod-week" aria-labelledby="hb-motw-h">'
                f'<div class="hb-motw-pic">{pic}</div><div class="hb-motw-t"><p class="hb-kick">Mod of the week</p>'
                f'<h2 id="hb-motw-h">{e(name)}</h2><p class="hb-by">by {e(neutral(i["author"]) or "unknown")}</p>'
                f'<p class="hb-motw-l">{e(line)}</p><p class="hb-fs-a">'
                f'<a class="hb-cta sm" href="leyline://install/{e(i["id"])}">{"Install with Leyline" if inst else "Open in Leyline"}</a>'
                f'<a class="hb-ghost" href="{BASE}/p/{_slug(i["id"])}">View</a></p>{credit}</div></section>')

    def posters(self, got) -> str:
        """Hosted by the community: up to three live community realms as posters, each with its own backdrop made from
        its realm id (the same id, the same poster). TODO(owner): hosts uploading their own poster image comes later."""
        if not got:
            return ""
        e = html.escape
        net = self.portal("network")
        picks = [r for r in got[0] if not r.get("home") and not r.get("official") and r.get("live") and r.get("id")][:3]
        if not picks:
            return ""
        cards = []
        for r in picks:
            h = hashlib.sha256(r["id"].encode()).digest()
            h1 = 200 + h[0] % 90                 # blue to violet, like the mark
            h2 = (h1 + 40 + h[1] % 80) % 360
            ang, x, y, rot = h[2] % 180, 20 + h[3] % 60, 15 + h[4] % 50, h[5] % 360
            name = neutral(r.get("name")) or "A realm"
            tags = [TAG_WORDS.get(t, net.TAG_LABEL[t]) for t in r.get("tags") or [] if t in net.TAG_LABEL][:3]
            players = r.get("players") if isinstance(r.get("players"), int) else None
            acts = []
            if client_of(r) == "browser":
                acts.append(f'<a class="hb-play" href="/wrath?go=r:{e(r["id"])}" aria-label="Play {e(name)} in your browser">Play</a>')
            if REALM_DEEPLINK:
                acts.append(f'<a class="hb-ghost" href="{e(REALM_DEEPLINK.format(id=r["id"]))}">Open in launcher</a>')
            cards.append(
                f'<article class="hb-poster" style="--h1:{h1};--h2:{h2};--a:{ang}deg;--x:{x}%;--y:{y}%;--r:{rot}deg">'
                '<span class="hb-poster-bg" aria-hidden="true"></span>'
                f'<p class="hb-poster-p">{"New realm" if r.get("new") and not players else "" if players is None else f"<b>{players}</b> playing"}</p>'
                f'<h3>{e(name)}</h3><p class="hb-poster-l">{e(neutral(r.get("tagline"), 90) or COMPAT[client_of(r)])}</p>'
                + (f'<p class="hb-poster-tags">{"".join(f"<span>{e(t)}</span>" for t in tags)}</p>' if tags else "")
                + f'<p class="hb-poster-a">{"".join(acts)}</p></article>')
        return ('<!-- TODO(owner): hosts uploading their own poster image comes later -->'
                '<section class="hb-sec hb-rv" id="hosted" aria-labelledby="hb-hosted-h"><h2 id="hb-hosted-h">Hosted by the community</h2>'
                f'<div class="hb-posters">{"".join(cards)}</div>'
                f'<p class="hb-more"><a href="{BASE}/realms">Every realm</a> · <a href="/wrath/host">Host your own</a></p></section>')

    def herokey_teaser(self, got) -> str:
        """One key, every realm: the Hero Key sign-on (flag herokey_sso). Off: "Coming soon"; on: available now."""
        e = html.escape
        hk = self.portal("herokey_on")
        try:
            on = bool(hk()) if hk is not None else False
        except Exception:   # noqa: BLE001
            on = False
        names = [neutral(r.get("name")) for r in (got[0] if got else []) if r.get("live")]
        names = [n for n in names if n][:3]
        names += ["Your realm", "A friend's realm", "Tonight's realm"][len(names):]
        cards = "".join(f'<span class="hb-hk-c"><i aria-hidden="true"></i>{e(n)}</span>' for n in names[:3])
        badge = '<span class="hb-bdg v">Available now</span>' if on else '<span class="hb-bdg f">Coming soon</span>'
        line = ("Sign in once with your Hero Key and play on any realm on the network: no new account for each server."
                if on else "Soon you'll sign in once with your Hero Key and play on any realm on the network: no new "
                           "account for each server.")
        act = (f'<p class="hb-fs-a"><a class="hb-cta sm" href="{BASE}/realms">Pick a realm</a></p>' if on else "")
        return ('<section class="hb-hk hb-rv" id="herokey" aria-labelledby="hb-hk-h">'
                f'<div class="hb-hk-t"><p class="hb-kick">Hero Key {badge}</p><h2 id="hb-hk-h">One key, every realm</h2>'
                f'<p>{e(line)}</p>{act}</div>'
                f'<div class="hb-hk-art" aria-hidden="true">{cards}<span class="hb-hk-key"><svg viewBox="0 0 24 24">'
                f'{NAV_ICONS["key"]}</svg></span></div></section>')

    def creator_spotlight(self, items: list) -> str:
        """Who made the top mods this month: the authors of the Hot list (installs in the last 30 days with rankings,
        the index's scores without), up to 4, with counts; each links to the catalog searched by their name."""
        e = html.escape
        pool = [i for i in items if i["source"] != "theme" and clean_line(i.get("author"), 60)]
        if not pool:
            return ""
        order, metrics = self._ranked(pool)
        by: dict[str, dict] = {}
        for rank, i in enumerate(order[:40]):
            a = clean_line(i["author"], 60)
            shown = neutral(a, 60)
            if not shown or shown.lower() in ("unknown", "leyline"):
                continue
            d = by.setdefault(a.lower(), {"q": a, "name": shown, "n": 0, "inst": 0, "best": rank, "top": i})
            d["n"] += 1
            d["inst"] += ((metrics.get(i["id"]) or {}).get("installs") or {}).get("d30", 0)
        people = sorted(by.values(), key=lambda d: (-d["inst"], -d["n"], d["best"]))[:4]
        if not people:
            return ""
        cards = []
        for d in people:
            q = urllib.parse.urlencode({"q": d["q"][:60]})
            bits = [f'{d["n"]} mod{"" if d["n"] == 1 else "s"} in the top list']
            if d["inst"] > 0:
                bits.append(f'{d["inst"]} install{"" if d["inst"] == 1 else "s"} this month')
            cards.append(f'<a class="hb-cr" href="{BASE}/catalog?{e(q)}"><span class="hb-av" aria-hidden="true">{e(d["name"][:1].upper())}</span>'
                         f'<span><b>{e(d["name"])}</b><small>{e(" · ".join(bits))}</small>'
                         f'<i>Top: {e(neutral(d["top"]["name"]) or "Untitled")}</i></span></a>')
        return ('<section class="hb-sec hb-rv" id="creators-top" aria-labelledby="hb-cr-h"><h2 id="hb-cr-h">Creator spotlight</h2>'
                f'<div class="hb-crs">{"".join(cards)}</div></section>')

    def news_strip(self) -> str:
        """The latest three posts from the admin console's news (read-only), linking to the news page."""
        e = html.escape
        posts = self.news_posts(3)
        if not posts:
            return ""
        cards = "".join(f'<a class="hb-nw" href="{BASE}/news"><small>{e(p["tag"])}{" · " if p["tag"] and p["date"] else ""}'
                        f'{e(p["date"])}</small><b>{e(p["title"])}</b>'
                        + (f"<span>{e(next(x for x in p['items'] if x))}</span>" if any(p["items"]) else "") + "</a>"
                        for p in posts)
        return ('<section class="hb-sec hb-rv" id="news" aria-labelledby="hb-nw-h"><h2 id="hb-nw-h">News</h2>'
                f'<div class="hb-nws">{cards}</div><p class="hb-more"><a href="{BASE}/news">All the news</a></p></section>')

    # ---------------------------------------------------------------- the gallery (owner 2026-10-30: "in game screenshots
    # or cdn pulls or at least something and featured mods on the site in a gallery for promo and appeal")
    # Only pictures we serve ourselves: our in-game screenshots (GAME_SHOTS, off with the game data killswitch), the mod
    # screenshots authors uploaded to our Workshop (/wrath/mods/<id>/shot/0), the launcher's own pages (LAUNCHER_SHOTS) and
    # the Leyline mark. Never a picture pulled or hotlinked from another site or CDN (press kits, wiki or database sites,
    # third-party READMEs): their copyright isn't ours to give, and the page's CSP (img-src 'self') blocks them anyway. A
    # catalog item without our own screenshot gets a tile drawn from its id (gradient, initial, kind icon).
    def game_shots_on(self) -> bool:
        """The in-game screenshots may show: the portal's game data killswitch is off (wrath_portal.gamedata_off(), the
        same flag that makes /wrath/art answer 410 for them). Without the portal's hook: off (never a broken image)."""
        off = self.portal("gamedata_off")
        try:
            return off is not None and not off()
        except Exception:   # noqa: BLE001
            return False

    def shot_count(self, i: dict) -> int:
        """How many screenshots a Workshop item has on our site (0 for links, themes and the index)."""
        if i.get("source") != "workshop" or not str(i.get("id", "")).startswith("mod:"):
            return 0
        ws = i.get("ws") or {}
        if isinstance(ws.get("screenshots"), list):
            return len(ws["screenshots"])
        w = self.portal("workshop")
        try:
            m = w.mod(i["id"][4:]) if w is not None and hasattr(w, "mod") else None
        except Exception:   # noqa: BLE001
            m = None
        return len(m.get("screenshots") or []) if isinstance(m, dict) else 0

    def _kind(self, i: dict) -> str:
        rk = self.portal("hub_rank")
        try:
            k = rk.kind_of(i) if rk is not None and hasattr(rk, "kind_of") else ""
        except Exception:   # noqa: BLE001
            k = ""
        if k in KIND_WORDS:
            return k
        if i.get("source") == "theme":
            return "theme"
        if i.get("category") == "sandbox" or i.get("type") == "mode":
            return "mode"
        return "addon" if i.get("type") == "addon" or i.get("category") == "addons" else "mod"

    def gallery_tiles(self, items: list | None = None, want: int = 0) -> list[dict]:
        """Every picture the gallery can show, in the gallery's order: in-game shots, mods and launcher shots taken in
        turn (one of each, then the next), so any prefix is a mix. want: stop after that many (0: all).
        A tile: {k: game|mods|launcher, id, title, line, credit, label, img: (src, w, h, alt) or None, art (html, no img),
        href (no script: the image or the item page), acts [(href, label, primary)]}."""
        items = self.items() if items is None else items
        dl = self._download()
        game = []
        have = self.portal("art_present")
        if self.featured_mod_ok():   # the featured modpack first, with its authors' credit and a link out (no Install)
            f = FEATURED_MOD
            src = f"/wrath/art/leyline-shot-{f['key']}.webp"
            game.append({"k": "game", "id": "g-" + f["key"], "title": f["title"], "line": f["short"], "credit": f["credit"],
                         "label": f["label"], "img": (src, f["w"], f["h"], f["alt"]), "art": "", "href": src, "ext": True,
                         "acts": [(f["url"], f["button"], True)]})
        if self.game_shots_on():
            for key, (w, h, title, line, alt) in GAME_SHOTS.items():
                name = f"leyline-shot-{key}.webp"
                try:
                    ok = have is None or bool(have(name))
                except Exception:   # noqa: BLE001
                    ok = False
                if ok:
                    src = "/wrath/art/" + name
                    game.append({"k": "game", "id": "g-" + key, "title": title, "line": line, "credit": "In game, on our own realm",
                                 "label": "In game", "img": (src, w, h, alt), "art": "", "href": src,
                                 "acts": [("/wrath", "Play in your browser", True)]})
        if not game:   # the killswitch (or no shots): one flat Leyline tile with the mark, no game picture at all
            game.append({"k": "game", "id": "g-leyline", "title": "See it in game", "line": "Start the game in a browser tab and look around.",
                         "credit": "Leyline", "label": "In game", "img": None, "flat": True,
                         "art": f'<span class="hb-gt-art flat" aria-hidden="true">{self._spin(120, "slow")}</span>',
                         "href": "/wrath", "acts": [("/wrath", "Play in your browser", True)]})
        launcher = [{"k": "launcher", "id": "l-" + key, "title": title, "line": line, "credit": "The Leyline launcher, with sample data",
                     "label": "Launcher", "img": ("/wrath/art/leyline-ui-" + key + ".webp", 1240, 760, alt), "art": "",
                     "href": "/wrath/art/leyline-ui-" + key + ".webp", "acts": [(dl, "Download the launcher", True)]}
                    for key, (title, line, alt) in LAUNCHER_SHOTS.items()]
        mods = []
        pool = [i for i in items if i["source"] != "theme"]
        if pool:
            order, _m = self._ranked(pool)
            # the Mod of the week, then the best with our own screenshot and the top of Hot taken in turn, then every
            # other item with our screenshot
            shots = [i for i in order[1:] if self.shot_count(i) or self.thumb_of(i)]
            hot = [i for i in order[1:4] if i not in shots[:3]]
            picks = [order[0]]
            for a, b in itertools.zip_longest(shots[:3], hot):
                picks += [x for x in (a, b) if x is not None and x not in picks]
            picks += [i for i in shots if i not in picks]
            rk = self.portal("hub_rank")
            for n, i in enumerate(picks):
                name = neutral(i["name"]) or "Untitled"
                author = neutral(i["author"]) or "unknown"
                kind = self._kind(i)
                slug = _slug(i["id"])
                inst = rk.installable(i) if rk is not None and hasattr(rk, "installable") else bool(i.get("packaged"))
                view = f"{BASE}/p/{slug}"
                img, art, credit = None, "", "by " + author
                if self.shot_count(i):
                    img = (f'/wrath/mods/{i["id"][4:]}/shot/0', 640, 360, f"A screenshot of {name}, {KIND_WORDS[kind][1]} by {author}")
                elif self.thumb_of(i):
                    img = (self.thumb_of(i), 640, 320, f"The preview image of {name}, {KIND_WORDS[kind][1]} by {author}")
                    credit += " · " + THUMB_CREDIT
                else:
                    art = self.gen_art(i, name, KIND_WORDS[kind][2])
                mods.append({"k": "mods", "id": "m-" + slug, "title": name, "line": neutral(i.get("summary") or i.get("description") or "", 140),
                             "credit": credit, "label": ("Mod of the week · " if n == 0 else "") + KIND_WORDS[kind][0],
                             "img": img, "art": art, "href": view,
                             "acts": [(f"leyline://install/{i['id']}", "Install with Leyline" if inst else "Open in Leyline", True),
                                      (view, "View", False)]})
        # External packs only with their own GitHub repo's preview image (no picture of theirs otherwise: we never pull
        # images from their pages), never with an install action: the authors' page and ours.
        for x in self.external():
            src = self.thumb_of(x)
            if not src or (canonical(x.get("repo") or "") or {}).get("forge") != "github":
                continue
            name = neutral(x["name"]) or "Untitled"
            by = neutral(x["author"]) or "its authors"
            mods.append({"k": "mods", "id": "x-" + _slug(x["id"]), "title": name, "line": neutral(x["summary"], 140),
                         "credit": f"by {by} · {THUMB_CREDIT} · External: not checked or hosted by Leyline",
                         "label": "External pack", "img": (src, 640, 320, f"The preview image of {name}, an external pack by {by}"),
                         "art": "", "href": f"{BASE}/p/{_slug(x['id'])}", "ext": True,
                         "acts": [(x["url"], "Visit the authors' page", True), (f"{BASE}/p/{_slug(x['id'])}", "View", False)]})
        out, lists = [], [game, mods, launcher]
        while any(lists) and (not want or len(out) < want):
            for lst in lists:
                if lst and (not want or len(out) < want):
                    out.append(lst.pop(0))
        return out

    @staticmethod
    def _sizes(n: int) -> list[str]:
        """The bento: a size per tile (big 2x2, wide 2x1, "" 1x1) so the grid comes out even on four columns and on two
        (a phone), with no hole at the end: when it wouldn't, the last tiles grow wide."""
        s = ["big" if k == 0 else "wide" if k % 3 == 0 else "" for k in range(n)]
        cells = {"big": 4, "wide": 2, "": 1}
        best = None
        tail = [k for k in range(max(1, n - 3), n)]
        for combo in itertools.product(["", "wide"], repeat=len(tail)):
            t = list(s)
            for k, v in zip(tail, combo):
                t[k] = v
            if sum(cells[x] for x in t) % 4 == 0:
                cost = sum(1 for k, v in zip(tail, combo) if s[k] != v)
                if best is None or cost < best[0]:
                    best = (cost, t)
        return best[1] if best else s

    def gallery_tile(self, t: dict, size: str = "", lightbox: bool = True) -> str:
        """One tile: a link (the image, or the item page; the lightbox takes the click when there is script), the
        caption (shown on hover and focus, always on touch), and for mods Install with Leyline and View."""
        e = html.escape
        if t["img"]:
            src, w, h, alt = t["img"]
            pic = f'<img src="{e(src)}" alt="{e(alt)}" width="{int(w)}" height="{int(h)}" loading="lazy" decoding="async">'
        else:
            pic = t["art"]
        ext = (f' rel="{FEATURED_REL}" target="_blank"' if t.get("ext") else ' rel="noopener noreferrer"')
        acts = "".join(f'<a class="{"hb-gt-i" if primary else "hb-gt-v"}" href="{e(h)}"'
                       + (ext if h.startswith("http") else "") + f">{e(label)}</a>" for h, label, primary in t["acts"])
        cap = (f'<small>{e(t["label"])}</small><b>{e(t["title"])}</b>'
               + (f'<span class="hb-gt-l">{e(t["line"])}</span>' if t["line"] else "") + f'<i>{e(t["credit"])}</i>')
        aria = "" if t["img"] else f' aria-label="{e(t["title"])}: {e(t["label"])}"'
        return (f'<figure class="hb-gt{" " + size if size else ""}{" flat" if t.get("flat") else ""}" data-k="{t["k"]}" id="{e(t["id"])}">'
                f'<a class="hb-gt-a" href="{e(t["href"])}"' + (" data-lb" if lightbox else "") + f'{aria}>{pic}</a>'
                f'<figcaption class="hb-gt-c">{cap}<span class="hb-gt-x"' + ("" if t["k"] == "mods" or t.get("ext") else " hidden") + f'>{acts}</span>'
                '</figcaption></figure>')

    def gallery_grid(self, tiles: list[dict], whole: bool = True) -> str:
        """The grid. whole: every kind is in it (the script may filter in place); else it is one ?f= filter's tiles."""
        sizes = self._sizes(len(tiles))
        return (f'<div class="hb-gal" data-gal="{"all" if whole else "one"}">'
                + "".join(self.gallery_tile(t, s) for t, s in zip(tiles, sizes))
                + '<p class="hb-gal-none"' + (" hidden" if tiles else "") + '>Nothing here yet.</p></div>')

    def gallery_url(self) -> str:
        return (FRONT if front_on() else BASE) + "/gallery"

    def gallery_chips(self, cur: str = "") -> str:
        """All / In game / Mods / Launcher: links to the gallery page (?f=), which the script turns into filters in place."""
        e = html.escape
        g = self.gallery_url()
        return ('<nav class="hb-gal-f" aria-label="Show">' + "".join(
            f'<a class="hb-chip{" on" if f == cur else ""}" href="{e(g + ("?f=" + f if f else ""))}" data-f="{f}"'
            + (' aria-current="true"' if f == cur else "") + f">{e(label)}</a>" for f, label in GALLERY_FILTERS) + "</nav>")

    def gallery_section(self, items: list) -> str:
        """The front page's gallery: ten tiles of the mix, the filters, and a link to everything."""
        tiles = self.gallery_tiles(items, want=10)
        if not tiles:
            return ""
        return ('<section class="hb-sec hb-gal-s hb-rv" id="gallery" aria-labelledby="hb-gal-h">'
                '<div class="hb-gal-hd"><div><h2 id="hb-gal-h">Gallery</h2><p class="hb-gal-sub">In the game, in the launcher '
                f'and in the Workshop.</p></div>{self.gallery_chips()}</div>{self.gallery_grid(tiles)}'
                f'<p class="hb-more"><a href="{self.gallery_url()}">See the whole gallery</a></p></section>')

    def gallery_page(self, query: dict, path: str, nonce: str = "") -> bytes:
        f = (query.get("f") or [""])[0]
        f = f if f in dict(GALLERY_FILTERS) else ""
        tiles = [t for t in self.gallery_tiles() if not f or t["k"] == f]
        n = len(tiles)
        body = ('<header class="hb-head"><h1>Gallery</h1><p>Screenshots from the game, the Leyline launcher and the mods people '
                f'made. {n} picture{"" if n == 1 else "s"}.</p></header>'
                f'<div class="hb-gal-hd page">{self.gallery_chips(f)}</div>{self.gallery_grid(tiles, not f)}'
                '<p class="hb-fine">Every picture here is served from our own site: taken on our realm, in our launcher, uploaded to '
                'our Workshop by the mod\'s authors, or a project\'s own preview image from its GitHub page (credited on the '
                'picture); the featured modpack\'s screenshot is its authors\', credited on it. Each mod belongs to its authors, under '
                'the licence they chose. External packs are made and hosted by their authors, not checked or hosted by Leyline.</p>')
        return self._shell("Gallery · Leyline", body, path, nonce, active="gallery")

    def featured_strip(self, items: list) -> str:
        """The catalog's featured row: the gallery's mod tiles (no script there, so each tile is a link)."""
        tiles = [t for t in self.gallery_tiles(items) if t["k"] == "mods"][:4]
        if not tiles:
            return ""
        return ('<section class="hb-feat-s" aria-labelledby="hb-feat-h"><h2 id="hb-feat-h">Featured</h2><div class="hb-gal strip">'
                + "".join(self.gallery_tile(t, "", lightbox=False) for t in tiles) + "</div></section>")

    def front_page(self, path: str = BASE, nonce: str = "") -> bytes:
        e = html.escape
        items = self.items()
        got = self.realm_rows() or False
        status = self.status_cards()
        by_cat = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORY_IDS + ["themes"]}
        cats = "".join(
            f'<a class="hb-chip" href="{BASE}/catalog?cat={c}">{e(n)} <small>{by_cat[c]}</small></a>' for c, n in CATEGORIES + [THEMES])
        body = (
            '<section class="hb-hero" id="top" aria-labelledby="hb-h">'
            f'<div class="hb-art" aria-hidden="true">{self._spin(400, "slow hb-hero-mark")}</div>'
            '<!-- TODO(owner): the hero heading and the line under it; his final wording -->'
            '<h1 id="hb-h">Every client, every server</h1>'
            '<p class="hb-sub-h">One launcher for every classic client and every server: your game, your realm, one click.</p>'
            f'<p class="hb-hero-a"><a class="hb-cta" href="{e(self._download())}" rel="noopener noreferrer">Download Now</a>'
            '<a class="hb-ghost lg" href="/wrath">Play in your browser</a></p>'
            '<p class="hb-note">Free and open source, for Windows, macOS and Linux. Nothing to buy.</p></section>'
            + self.ticker(got) + self.realm_section(got) + self.how_strip() + self.counters(got, items) + self.featured_mod() + self.features(got)
            + self.gallery_section(items) + self.posters(got)
            + f'<div class="hb-pair">{self.mod_of_week(items)}{self.herokey_teaser(got)}</div>'
            + self.creator_spotlight(items) + self.news_strip()
            + f'<div class="hb-rv">{status}</div><div class="hb-rv">{self.spotlight()}</div>' +
            '<section class="hb-sec hb-rv" aria-labelledby="hb-b"><h2 id="hb-b">Browse by category</h2>'
            f'<p class="hb-chips">{cats}</p></section>'
            '<section class="hb-two hb-rv">'
            f'<a class="hb-box" href="{BASE}/creators"><b>For creators</b><span>Make an addon, a realm script or a whole mode: '
            'the docs, the package format and how the index works.</span></a>'
            f'<a class="hb-box" href="{BASE}/beacon"><b>Host a Beacon</b><span>Run your own realm and put it on the Leyline '
            'list, so players can hop over from the launcher.</span></a></section>'
            '<p class="hb-fine">Community projects are links: nothing of theirs is hosted here. Each belongs to its '
            'authors, under the licence they chose. Leyline is an independent open-source project.</p>')
        return self._shell("Leyline", body, path, nonce)

    def _network(self):
        """(network module, realms, ok, the sample's status) from the portal, or None when it has no realm list."""
        net, cr = self.portal("network"), self.portal("community_realms")
        if net is None or cr is None:
            return None
        try:
            realms, ok = cr()
        except Exception:   # noqa: BLE001
            realms, ok = [], False
        rs = self.portal("realm_status")
        try:
            st = rs() if rs else {}
        except Exception:   # noqa: BLE001
            st = {}
        return net, realms, ok, st

    def realm_filters(self, f: dict, fc: dict) -> str:
        """The realm list's filters as plain links (no script): how to play (in the browser or with your own client, never
        a build number), rules, region, language, has players now. The network's filters_html, in the hub's words."""
        e = html.escape
        net = self.portal("network")

        def qs(**over):
            g = {k: v for k, v in f.items() if k != "build"}
            g.update(over)
            q = {k: ("1" if k == "now" else v) for k, v in g.items() if v not in (None, False, "")}
            return BASE + "/realms" + ("?" + urllib.parse.urlencode(sorted(q.items())) if q else "")

        def row(key, label, opts):
            if not opts:
                return ""
            cur = f.get(key)
            links = [f'<a href="{e(qs(**{key: None}))}"' + (' class="on"' if cur is None else "") + ">any</a>"]
            links += [f'<a href="{e(qs(**{key: v}))}"' + (' class="on"' if cur == v else "") + f">{e(t)}</a>" for v, t in opts]
            return f"<span>{e(label)}:</span> " + " ".join(links)
        parts = [row("client", "Play", list(CLIENT_FILTER)),
                 row("tag", "Rules", [(t, TAG_WORDS.get(t, net.TAG_LABEL[t])) for t in fc["tag"]]),
                 row("region", "Region", [(g, net.REGION_LABEL[g]) for g in fc["region"]]),
                 row("lang", "Language", [(x, net.LANGS.get(x, x)) for x in fc["lang"]])]
        now = (f'<a href="{e(qs(now=None))}">everyone</a> <a class="on" href="#">has players now</a>' if f.get("now")
               else f'<a class="on" href="#">everyone</a> <a href="{e(qs(now=True))}">has players now</a>')
        parts.append("<span>Show:</span> " + now)
        return '<nav class="net-filters" aria-label="Filter realms">' + "".join(f"<div>{p}</div>" for p in parts if p) + "</nav>"

    def realms_page(self, query: dict, nonce: str = "") -> bytes:
        """Every realm on the network as the front page's rows (Play in browser, the address), with the network's
        filters as links (they work without script) and Host your own."""
        got = self.realm_rows(query)
        if got is None:
            body = '<section class="ly-panel"><h2>Realms</h2><p><a href="/wrath/realms">The realm list</a></p></section>'
            return self._shell("Realms · Leyline", body, BASE + "/realms")
        e = html.escape
        net = self.portal("network")
        rows, t, ok, f, fc = got
        ln = self.portal("leyline_net")
        try:
            pack = ln.hostpack() if ln is not None else None
        except Exception:   # noqa: BLE001
            pack = None
        if rows:
            listing = f'<ul class="hb-rlist" id="hb-rlist">{"".join(self.realm_row(r) for r in rows)}</ul>'
        elif f:
            listing = f'<p class="hb-rl-none">No realms match these filters. <a href="{BASE}/realms">Show every realm</a></p>'
        else:
            listing = '<p class="hb-rl-none">The realm list isn\'t reachable right now. Try again in a minute.</p>'
        body = ('<section class="hb-head"><h1>Realms</h1>'
                '<p>Every server on the Leyline network, hosted by players. The order is players online, uptime and '
                'staff picks: nothing can be bought.</p>'
                f'<p class="hb-netline" data-net>{e(net.network_line(t))}</p></section>'
                + self.realm_filters(f, fc)
                + ("" if ok else '<p class="hb-fine">The community list may be a little out of date right now.</p>')
                + listing
                + '<p class="hb-fine">Play in browser opens the realm in this browser. For a desktop client, use the '
                  'address in the launcher (Realms, then Add a realm) or in your realmlist file.</p>'
                + net.host_cta("hub", pack["download"] if pack else None))
        return self._shell("Realms · Leyline", body, BASE + "/realms", nonce)

    def modes_page(self) -> bytes:
        """The launcher's Modes page on the web: every game mode, one click to play (the go intent, /wrath?go=mode:)."""
        e = html.escape
        pm = self.portal("playmodes")
        try:
            modes = pm.entries() if pm is not None else []
        except Exception:   # noqa: BLE001
            modes = []
        cards = []
        for m in modes:
            tags = [pm.KIND_TEXT.get(m["kind"], ""), pm.players_text(m["players"])]
            if m["status"] == "coming":
                tags.append("Coming soon")
            href = pm.play_href(m, "/wrath/host")
            act = ""
            if href:
                label = "Host it" if m["kind"] == "realm-type" else "Play"
                act = (f'<p class="hb-act"><a class="{"hb-ghost" if m["kind"] == "realm-type" else "hb-play"}" href="{e(href)}">'
                       f'{label}</a></p>')
            c = m.get("credit") or {}
            credit = (f'<p class="hb-meta">By {e(neutral(c["by"]))} · {e(c.get("license", ""))} · '
                      f'<a href="{e(c["source"])}" rel="noopener noreferrer">Source</a></p>') if c.get("by") and c.get("source") else ""
            art = MODE_ART.get(m["id"])
            have = self.portal("art_present")
            try:
                art_ok = bool(art) and (have is None or bool(have(art[0])))
            except Exception:   # noqa: BLE001
                art_ok = False
            pic = (f'<img class="hb-mode-art" src="/wrath/art/{e(art[0])}" alt="{e(art[3])}" width="{art[1]}" height="{art[2]}" '
                   'loading="lazy" decoding="async">') if art_ok else ""
            cards.append(f'<article class="hb-mode{" art" if pic else ""}" id="mode-{e(m["id"])}">{pic}<h2>{e(neutral(m["title"]))}</h2><p>{e(neutral(m["line"]))}</p>'
                         f'<p>{"".join(f"<span class=hb-tag>{e(x)}</span>" for x in tags if x)}</p>{credit}{act}</article>')
        body = ('<section class="hb-head"><h1>Modes</h1><p>Minigames and game modes. Play signs you in and starts the game '
                'in your browser once your character is in the world. The launcher lists the same games on its Modes page.</p></section>'
                + (f'<div class="hb-modes">{"".join(cards)}</div>' if cards else
                   '<p class="hb-empty">No modes are listed right now. <a href="/wrath/modes">The modes page</a></p>')
                + '<p class="hb-fine">Duels, boss fights, dungeons and hangouts are on <a href="/wrath/modes">the full modes page</a>.</p>')
        return self._shell("Modes · Leyline", body, BASE + "/modes")

    def news_posts(self, n: int = 30) -> list[dict]:
        """The admin console's news.json posts fit to show ({title, tag, date, items}), newest first as published: a
        post with a brand word anywhere is dropped whole, client numbers are taken out (neutral). The news page and the
        front page's News both read this."""
        adm = self.portal("admin")
        try:
            posts = adm.news_doc()["posts"] if adm is not None else []
        except Exception:   # noqa: BLE001
            posts = []
        out = []
        for p in posts[:200]:
            if len(out) >= n:
                break
            raw = [clean_line(x, 200) for x in (p.get("items") if isinstance(p.get("items"), list) else [])[:12]]
            title, tag, date = clean_line(p.get("title"), 120), clean_line(p.get("tag"), 60), clean_line(p.get("date"), 10)
            if not title or banned(" ".join([title, tag] + raw)):
                continue
            title, tag, items = neutral(title, 120), neutral(tag, 60), [neutral(x, 200) for x in raw]
            if not title:
                continue
            out.append({"title": title, "tag": tag, "date": date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else "",
                        "items": items})
        return out

    def news_page(self) -> bytes:
        """The launcher's News page on the web: the posts the admin console publishes (/wrath/leyline/news.json)."""
        e = html.escape
        out = []
        for p in self.news_posts(30):
            tag, date, title, items = p["tag"], p["date"], p["title"], p["items"]
            out.append(f'<article><small>{e(tag)}{" · " if tag and date else ""}{e(date)}</small><h2>{e(title)}</h2>'
                       + (f'<ul>{"".join(f"<li>{e(x)}</li>" for x in items if x)}</ul>' if any(items) else "") + "</article>")
        body = ('<section class="hb-head"><h1>News</h1><p>What changed in the launcher, the realms and the browser game.</p></section>'
                + (f'<div class="hb-news">{"".join(out)}</div>' if out else '<p class="hb-empty">No news posts yet.</p>'))
        return self._shell("News · Leyline", body, BASE + "/news")

    def card(self, i: dict, m: dict | None = None, rk=None) -> str:
        e = html.escape
        rank = ""
        if m is not None and rk is not None:
            rank = (f'<p class="hb-rk">{e(rk.stars_text(m["rating"]))} · {m["installs"]["all"]} installs'
                    + (" · Install with Leyline" if rk.installable(i) else "") + "</p>")
        badge = {"workshop": "Workshop", "index": "Community", "theme": "Theme"}[i["source"]]
        builds = " ".join(f'<span class="hb-tag">{e(CLIENT_LABEL.get(b, "Any client"))}</span>' for b in i["builds"])
        stars = f' · ★ {int(i["stars"])}' if isinstance(i.get("stars"), int) and not isinstance(i.get("stars"), bool) else ""
        return (f'<article class="hb-card">{self.card_pic(i)}<h3><a href="{BASE}/p/{_slug(i["id"])}">{e(neutral(i["name"]) or "Untitled")}</a></h3>'
                f'<p class="hb-by">by {e(neutral(i["author"]) or "unknown")} · <span class="hb-src hb-{i["source"]}">{badge}</span></p>'
                f'<p>{e(neutral(i.get("description") or i["summary"]))}</p><p class="hb-meta">{builds}'
                f'<span class="hb-lic">{e(neutral(i.get("licence")) or "licence not stated")}{stars}</span></p>{rank}</article>')

    def card_pic(self, i: dict) -> str:
        """A card's picture: the Workshop screenshot, else the project's preview thumbnail (credited in its title), else
        the tile drawn from its id. A link to the item page, skipped by keyboard and screen readers (the name links)."""
        e = html.escape
        name = neutral(i["name"]) or "Untitled"
        href = f"{BASE}/p/{_slug(i['id'])}"
        if self.shot_count(i):
            pic = f'<img src="/wrath/mods/{e(i["id"][4:])}/shot/0" alt="" loading="lazy" width="640" height="360">'
        elif self.thumb_of(i):
            pic = f'<img src="{e(self.thumb_of(i))}" alt="" loading="lazy" width="640" height="320" title="{e(THUMB_CREDIT)}">'
        else:
            icon = "creators" if i.get("source") == "theme" else "mods" if i.get("source") == "external" else KIND_WORDS[self._kind(i)][2]
            pic = self.gen_art(i, name, icon, "hb-gt-art gen hb-card-art")
        return f'<a class="hb-card-pic" href="{href}" tabindex="-1" aria-hidden="true">{pic}</a>'

    def ext_card(self, i: dict) -> str:
        """An external pack in the catalog: the flag that we neither checked nor host it, and the authors' page. Never
        an Install."""
        e = html.escape
        builds = " ".join(f'<span class="hb-tag">{e(CLIENT_LABEL.get(b, "Any client"))}</span>' for b in i["builds"])
        return (f'<article class="hb-card hb-ext">{self.card_pic(i)}<h3><a href="{BASE}/p/{_slug(i["id"])}">{e(neutral(i["name"]) or "Untitled")}</a></h3>'
                f'<p class="hb-by">by {e(neutral(i["author"]) or "its authors")} · <span class="hb-src hb-external">External</span></p>'
                f'<p>{e(neutral(i["summary"]))}</p><p class="hb-ext-b" role="note">{e(EXTERNAL_NOTE)}</p>'
                f'<p class="hb-meta">{builds}</p><p class="hb-ext-a"><a class="hb-ghost" href="{e(i["url"])}" '
                f'rel="noopener nofollow ugc" target="_blank">Visit the authors\' page</a></p></article>')

    def catalog_page(self, query: dict) -> bytes:
        e = html.escape
        q1 = lambda k: (query.get(k) or [""])[0][:80]   # noqa: E731
        build, cat, source, text, sort = offered_tag(q1("build")), q1("cat"), q1("source"), clean_line(q1("q"), 60), q1("sort") or "score"
        cat = cat if cat in CATEGORY_IDS + ["themes"] else ""
        source = source if source in ("workshop", "index", "theme", "external") else ""
        rk = self.portal("hub_rank")
        rk = rk if rk is not None and getattr(rk, "store", None) is not None else None
        ranked_sorts = [s for s, _ in rk.SORT_LABELS] if rk else []
        sort = sort if sort in ("score", "name", "updated") or sort in ranked_sorts else "score"
        kind = q1("kind") if rk and q1("kind") in rk.KINDS else ""
        try:
            page = max(1, min(500, int(q1("page") or 1)))
        except ValueError:
            page = 1
        items = self.items()
        ext = self.external() if not kind and source in ("", "external") else []
        if source == "external":
            items = []

        def keep(lst):
            if build:
                lst = [i for i in lst if build in i["builds"] or "any" in i["builds"]]
            if cat:
                lst = [i for i in lst if i["category"] == cat]
            if text:
                words = text.lower().split()
                lst = [i for i in lst if all(w in (i["name"] + " " + i["summary"] + " " + i.get("description", "")
                                                   + " " + i["author"]).lower() for w in words)]
            return lst
        items, ext = keep(items), keep(ext)
        if source and source != "external":
            items = [i for i in items if i["source"] == source]
        if kind:
            items = [i for i in items if rk.kind_of(i) == kind]
        metrics = rk.store.metrics(self.items()) if rk else {}
        if sort == "name":
            items.sort(key=lambda i: (i["name"].lower(), i["id"]))
        elif sort in ranked_sorts:
            items.sort(key=lambda i: rk.sort_key(sort, metrics[i["id"]], i))
        elif sort == "updated":
            items.sort(key=lambda i: (i.get("updated") or "", i["name"].lower()), reverse=True)
        else:
            items.sort(key=lambda i: (-float(i.get("score") or 0), i["name"].lower(), i["id"]))
        total = len(items)
        pages = max(1, math.ceil(total / self.PER_PAGE))
        page = min(page, pages)
        shown = items[(page - 1) * self.PER_PAGE: page * self.PER_PAGE]

        def link(**over):
            cur = {"build": build, "cat": cat, "source": source, "kind": kind, "q": text, "sort": sort if sort != "score" else ""}
            cur.update(over)
            qs = urllib.parse.urlencode({k: v for k, v in cur.items() if v})
            return f"{BASE}/catalog" + (f"?{qs}" if qs else "")

        def chips(key, opts, cur):
            return "".join(f'<a class="hb-chip{" on" if v == cur else ""}" href="{e(link(**{key: v, "page": ""}))}"'
                           + (' aria-current="true"' if v == cur else "") + f">{e(label)}</a>" for v, label in opts)
        f_build = chips("build", [("", "Every client")] + [(b, CLIENT_LABEL[b]) for b in offered_builds()], build)
        f_cat = chips("cat", [("", "All")] + CATEGORIES + [THEMES], cat)
        f_src = chips("source", [("", "Everything"), ("workshop", "Workshop"), ("index", "Community"), ("theme", "Themes"),
                                 ("external", EXTERNAL_LABEL)], source)
        if rk:
            f_sort = chips("sort", [("", "Best")] + rk.SORT_LABELS + [("name", "A to Z")], sort if sort != "score" else "")
            f_kind = "<p>" + chips("kind", [("", "Every kind")] + rk.KIND_LABELS, kind) + "</p>"
        else:
            f_sort = chips("sort", [("", "Best"), ("name", "A to Z"), ("updated", "Recently updated")], sort if sort != "score" else "")
            f_kind = ""
        hidden = "".join(f'<input type="hidden" name="{k}" value="{e(v)}">' for k, v in
                         (("build", build), ("cat", cat), ("source", source), ("kind", kind), ("sort", sort if sort != "score" else "")) if v)
        nav = ""
        if pages > 1:
            nav = ('<nav class="hb-pages" aria-label="Pages">'
                   + (f'<a href="{e(link(page=str(page - 1)))}">Previous</a>' if page > 1 else "")
                   + f"<span>Page {page} of {pages}</span>"
                   + (f'<a href="{e(link(page=str(page + 1)))}">Next</a>' if page < pages else "") + "</nav>")
        grid = "".join(self.card(i, metrics.get(i["id"]) if rk else None, rk) for i in shown) or (
            "" if source == "external" else
            '<p class="hb-empty">Nothing here yet. '
            + (f'<a href="{BASE}/submit">Submit a mod</a> to fill it.' if cat != "themes" else "Theme packs are on the way.") + "</p>")
        group = ""
        if ext and page == 1:
            group = ('<section class="hb-ext-s" id="external" aria-labelledby="hb-ext-h">'
                     f'<h2 id="hb-ext-h">{e(EXTERNAL_LABEL)}</h2><p class="hb-ext-lede">Packs made and hosted by their authors. '
                     'Leyline only links to their own pages: it hasn\'t checked them, doesn\'t host them and can\'t install them.</p>'
                     f'<div class="hb-grid">{"".join(self.ext_card(x) for x in ext)}</div></section>')
        elif source == "external":
            group = '<p class="hb-empty">No external packs here.</p>'
        total += len(ext)
        body = (f'<header class="hb-head"><h1>Catalog</h1><p>{total} items'
                + (f' for the {e(CLIENT_LABEL[build].lower())}' if build and build != "any" else "") + '</p></header>'
                f'<form class="hb-search" method="get" action="{BASE}/catalog" role="search">{hidden}'
                f'<label for="hb-q">Search</label><input id="hb-q" name="q" value="{e(text)}" maxlength="60">'
                '<button type="submit">Search</button></form>'
                f'<div class="hb-filters"><p>{f_build}</p><p>{f_cat}</p><p>{f_src}</p>{f_kind}'
                f'<p role="tablist" aria-label="Sort">{f_sort}</p></div>'
                + (self.featured_strip(self.items()) if page == 1 and not (build or cat or source or kind or text) else "")
                + (f'<div class="hb-grid">{grid}</div>' if grid else "") + f'{group}{nav}' + (f"<style>{rk.RANK_CSS}</style>" if rk else ""))
        return self._shell("Catalog · Leyline", body, BASE + "/catalog", active="addons" if cat == "addons" else "mods")

    def item_page(self, slug: str, handler=None, query: dict | None = None) -> tuple[int, bytes]:
        e = html.escape
        i = self.get_item(slug)
        if i is None:
            return 404, self._shell("Not found · Leyline", '<section class="ly-panel"><h2>Not in the catalog</h2>'
                                    f'<p><a href="{BASE}/catalog">See everything</a></p></section>', BASE)
        if i["source"] == "external":
            return 200, self.external_page(i, slug)
        rows = [("Works with", ", ".join(CLIENT_LABEL.get(b, "Any client") for b in i["builds"])),
                ("Category", dict(CATEGORIES + [THEMES]).get(i["category"], i["category"])),
                ("Author", neutral(i["author"]) or "unknown"), ("Licence", neutral(i.get("licence")) or "not stated")]
        if isinstance(i.get("stars"), int) and not isinstance(i.get("stars"), bool):
            rows.append(("Stars", str(i["stars"])))
        if i.get("updated"):
            rows.append(("Last change", i["updated"][:10]))
        if i.get("needs"):
            rows.append(("Needs", neutral(i["needs"]) or "See its page"))
        if i.get("archived"):
            rows.append(("Status", "Archived by its authors (read-only)"))
        rel = i.get("release") if isinstance(i.get("release"), dict) else None
        if rel:
            rows.append(("Latest release", (neutral(rel["tag"]) or "Latest") + (f" ({rel['date']})" if rel.get("date") else "")))
        table = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows)
        acts = []
        if i["source"] == "workshop":
            local = urllib.parse.urlsplit(i.get("page") or "").path
            if local.startswith("/wrath/"):
                acts.append(f'<a class="ly-btn" href="{e(local)}">Open in the Workshop</a>')
        if i.get("repo"):
            forge = FORGE_LABEL.get(i.get("forge", ""), "the forge")
            acts.append(f'<a class="ly-btn hb-alt" href="{e(i["repo"])}" rel="noopener noreferrer nofollow ugc">'
                        f'View source on {e(forge)}</a>')
        how = {"index": "A community project: Leyline links to it and hosts nothing of it. Install it the way its "
                        "authors describe. The launcher shows it with View source and no Install button.",
               "workshop": "In our Workshop" + (": the launcher installs it in one click." if i.get("packaged") else
                                                 ": a link people shared."),
               "theme": "A theme pack for the Leyline launcher."}[i["source"]]
        name, summary, about = neutral(i["name"]) or "Untitled", neutral(i["summary"]), neutral(i.get("description"))
        desc = f'<p class="hb-repo">From the repo: {e(about)}</p>' if about else ""
        if rel and i.get("repo") and rel["url"].startswith(i["repo"] + "/"):
            acts.append(f'<a class="ly-btn hb-alt" href="{e(rel["url"])}" rel="noopener noreferrer nofollow ugc">Latest release</a>')
        rk = self.portal("hub_rank")
        try:
            panel = rk.item_panel(handler, i, query) + f"<style>{rk.RANK_CSS}</style>" if rk is not None and handler is not None else ""
        except Exception:   # noqa: BLE001: the rankings never break the page
            panel = ""
        body = (f'<article class="ly-panel hb-item">{self.item_pic(i)}<h1>{e(name)}</h1><p class="hb-sum">{e(summary)}</p>{desc}'
                f'<table class="ly-table">{table}</table><p class="hb-actions">{" ".join(acts)}</p>'
                f'<p class="hb-fine">{e(how)}</p></article>{panel}')
        return 200, self._shell(f"{name} · Leyline", body, BASE + "/p/" + slug)

    def item_pic(self, i: dict) -> str:
        """An item page's picture: the Workshop screenshot, else the preview thumbnail with its credit under it, else the
        tile drawn from its id."""
        e = html.escape
        name = neutral(i["name"]) or "Untitled"
        if self.shot_count(i):
            return (f'<figure class="hb-item-pic"><img src="/wrath/mods/{e(i["id"][4:])}/shot/0" alt="A screenshot of {e(name)}" '
                    'width="640" height="360"></figure>')
        if self.thumb_of(i):
            return (f'<figure class="hb-item-pic"><img src="{e(self.thumb_of(i))}" alt="The preview image of {e(name)}" '
                    f'width="640" height="320"><figcaption>{e(THUMB_CREDIT)}</figcaption></figure>')
        icon = "creators" if i.get("source") == "theme" else "mods" if i.get("source") == "external" else KIND_WORDS[self._kind(i)][2]
        return f'<figure class="hb-item-pic">{self.gen_art(i, name, icon)}</figure>'

    def external_page(self, i: dict, slug: str) -> bytes:
        """An external pack's own page: what it is, the flag (made and hosted by its authors, not checked or hosted by
        Leyline), the authors' page (a new tab, nofollow) and, when it has one, its source repo. Never an Install, never
        a leyline://install link, never a download of ours."""
        e = html.escape
        name = neutral(i["name"]) or "Untitled"
        rows = [("Works with", ", ".join(CLIENT_LABEL.get(b, "Any client") for b in i["builds"])),
                ("Category", dict(CATEGORIES).get(i["category"], i["category"])),
                ("Made by", neutral(i["author"]) or "its authors"), ("Where it comes from", "Its authors' own page")]
        table = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows)
        acts = [f'<a class="ly-btn" href="{e(i["url"])}" rel="noopener nofollow ugc" target="_blank">Visit the authors\' page</a>']
        if i.get("repo") and _https(i["repo"]):
            acts.append(f'<a class="ly-btn hb-alt" href="{e(i["repo"])}" rel="noopener nofollow ugc" target="_blank">'
                        f'View source on {e(FORGE_LABEL.get(i.get("forge", ""), "the forge"))}</a>')
        body = (f'<article class="ly-panel hb-item hb-ext-item">{self.item_pic(i)}<h1>{e(name)}</h1>'
                f'<p class="hb-ext-b" role="note"><b>External</b> {e(EXTERNAL_NOTE)}.</p>'
                f'<p class="hb-sum">{e(neutral(i["summary"]))}</p><table class="ly-table">{table}</table>'
                f'<p class="hb-actions">{" ".join(acts)}</p>'
                '<p class="hb-fine">Leyline lists this pack as a link only: it is made, hosted and kept up to date by its authors. '
                'We haven\'t checked what it contains and we don\'t host or install it. Download it from the authors\' page, the '
                'way they describe, and only if you trust it.</p>'
                f'<p class="hb-more"><a href="{BASE}/catalog?source=external">Every external pack</a></p></article>')
        return self._shell(f"{name} · Leyline", body, BASE + "/p/" + slug)

    def creators_page(self) -> bytes:
        rules = "".join(f"<li>{x}</li>" for x in (
            "Open licence only: the repo must have a licence file. No licence, no listing (it waits on a list until it has one).",
            "No game data: nothing that ships the game's files, client patches or repacks.",
            "Nothing paid, no shops, VIP or donation perks.",
            "Nothing decompiled or derived from decompiled clients.",
            "No bots or cheats for other people's realms.",
            "Names are shown without the game's brand words; credit always goes to the authors."))
        body = ('<section class="ly-panel"><h1>For creators</h1>'
                '<p>Leyline lists two kinds of things: mods in our Workshop (packages the launcher installs) and open '
                'projects anywhere on GitHub, GitLab or Codeberg (linked, never hosted).</p>'
                '<ul class="hb-list">'
                '<li><a href="/wrath/docs">The Leyline docs</a>: modes, the realm API, hosting.</li>'
                '<li><a href="/wrath/mods">The Workshop</a>: what is packaged today.</li>'
                f'<li><a href="{BASE}/submit">Submit a mod</a>: add your repo to the index.</li></ul></section>'
                '<section class="ly-panel"><h2>How the index works</h2>'
                '<p>Every day a script checks the forges for open projects for every client the launcher supports, '
                'reads each repo\'s licence, files and addon TOC, and refreshes the stars and '
                'latest releases of what is listed. New projects wait until a person has looked at them. The short description is written from the repo\'s own one-line '
                'description and facts.</p>'
                f'<h3>What gets listed</h3><ul class="hb-list">{rules}</ul>'
                '<p>Want your project taken off? Open an issue on the Leyline repo or use Report on its page, and it '
                'is gone with the next update.</p></section>')
        return self._shell("Creators · Leyline", body, BASE + "/creators")

    def beacon_page(self) -> bytes:
        host_url = self.portal("HOST_URL") or "https://github.com/orionopenwow/WrathUnleashed"
        e = html.escape
        body = ('<section class="ly-panel"><h1>Host a Beacon</h1>'
                '<p>A Beacon is a realm someone runs on their own PC or server and puts on the Leyline list. Players '
                'see it in the launcher and in the game\'s Leyline window and hop over with one click.</p>'
                '<ol class="hb-list"><li>Get the host kit and start a realm: one command, your rules, your GM login.</li>'
                '<li>Pick a preset or add realm scripts from the catalog.</li>'
                '<li>Turn on the Beacon: the relay lists it, no port forwarding needed.</li></ol>'
                '<p>In the Leyline launcher: open Host, get the Host pack, pick a profile and your house rules, then '
                'set the realm list details (tags, region, language, player limit). Community realms are listed first '
                'everywhere: on the website, in the launcher and in the game\'s Leyline window.</p>'
                '<p class="hb-actions"><a class="ly-btn" href="/wrath/leyline">Get the launcher</a> '
                '<a class="ly-btn hb-alt" href="/wrath/host">Start on the website</a></p>'
                f'<p class="hb-actions"><a class="ly-btn" href="{e(host_url)}" rel="noopener noreferrer">The host guide</a> '
                '<a class="ly-btn hb-alt" href="/wrath/realms">See live realms</a></p></section>'
                f'<section class="ly-panel"><h2>Server presets and realm scripts</h2><p>'
                f'<a href="{BASE}/catalog?cat=presets">Presets</a> · <a href="{BASE}/catalog?cat=realm-scripts">Realm scripts</a> · '
                f'<a href="{BASE}/catalog?cat=encounters">Encounters</a></p></section>')
        return self._shell("Host a Beacon · Leyline", body, BASE + "/beacon")

    def submit_page(self, msg: str = "", form: dict | None = None, done: bool = False) -> bytes:
        e = html.escape
        form = form or {}
        if done:
            body = ('<section class="ly-panel"><h1>Thank you</h1><p>Your submission is in the queue. A person checks '
                    'it against the rules, and the daily index update picks it up once it is approved.</p>'
                    f'<p><a href="{BASE}/catalog">Back to the catalog</a></p></section>')
            return self._shell("Submitted · Leyline", body, BASE + "/submit")
        opt = lambda v, label, cur: f'<option value="{e(v)}"{" selected" if v == cur else ""}>{e(label)}</option>'  # noqa: E731
        builds = "".join(opt(b, CLIENT_LABEL[b], form.get("build", "")) for b in offered_builds() + ["any"])
        cats = "".join(opt(c, n, form.get("category", "")) for c, n in CATEGORIES)
        err = f'<p class="hb-err" role="alert">{e(msg)}</p>' if msg else ""
        body = ('<section class="ly-panel"><h1>Submit a mod</h1>'
                '<p>Add an open project to the index: an addon, a realm module or script, a tool, a preset. '
                'We only need the link; the rest is read from the repo. No account, no email.</p>'
                f'{err}<form class="hb-form" method="post" action="{BASE}/submit">'
                f'<label for="s-repo">Repo link (GitHub, GitLab or Codeberg)</label>'
                f'<input id="s-repo" name="repo" required maxlength="300" placeholder="https://github.com/you/your-mod" '
                f'value="{e(form.get("repo", ""))}">'
                f'<label for="s-build">Made for</label><select id="s-build" name="build">{builds}</select>'
                f'<label for="s-cat">Category</label><select id="s-cat" name="category">{cats}</select>'
                f'<label for="s-note">A short note for the reviewers (optional)</label>'
                f'<textarea id="s-note" name="note" maxlength="{self.MAX_NOTE}" rows="3">{e(form.get("note", ""))}</textarea>'
                '<label class="hb-hp" aria-hidden="true">Leave empty <input name="website" tabindex="-1" autocomplete="off"></label>'
                '<button class="ly-btn" type="submit">Submit</button></form>'
                '<p class="hb-fine">Please don\'t put names, emails or other personal details in the note. '
                'The rules are on the <a href="' + BASE + '/creators">creators page</a>.</p></section>')
        return self._shell("Submit a mod · Leyline", body, BASE + "/submit")

    # ---------------------------------------------------------------- submissions
    def _rate_ok(self, ip: str, now: float) -> bool:
        with self.lock:
            if len(self._limit) > 5000:
                self._limit.clear()
            hits = [t for t in self._limit.get(ip, []) if now - t < 3600]
            if len(hits) >= 5:
                self._limit[ip] = hits
                return False
            hits.append(now)
            self._limit[ip] = hits
            day = [t for t in self._limit.get("*", []) if now - t < 86400]
            if len(day) >= 200:
                self._limit["*"] = day
                return False
            day.append(now)
            self._limit["*"] = day
            return True

    def submit(self, form: dict, ip: str, now: float | None = None) -> tuple[bool, str]:
        """Validates and queues one submission. (ok, message for the page)."""
        now = time.time() if now is None else now
        if (form.get("website") or "").strip():
            return True, ""                                         # a bot filled the hidden field: say thanks, keep nothing
        c = canonical(form.get("repo", ""))
        if not c:
            return False, "Paste the repo's own link, like https://github.com/owner/repo (GitHub, GitLab or Codeberg)."
        build = offered_tag(form.get("build"))
        if not build:
            return False, "Pick the client it is made for."
        cat = form.get("category") if form.get("category") in CATEGORY_IDS else ""
        if not cat:
            return False, "Pick a category."
        note = clean_line(form.get("note", ""), self.MAX_NOTE)
        if "chumpton" in (c["key"] + " " + note).lower():
            return False, "That project can't be listed here."
        if any(i["id"] == "link:" + c["id"] for i in self.items()):
            return False, "That project is already in the catalog."
        dec = self.store.decisions().get(c["id"])
        if dec and dec["decision"] in ("reject", "delist"):
            return False, "That project was reviewed and isn't listed here."
        if any(r.get("id") == c["id"] for r in self.store.pending()):
            return False, "That project is already in the queue: thanks."
        if not self._rate_ok(ip or "?", now):
            return False, "Too many submissions from here for now. Please try again later."
        if len(self.store.submissions()) >= Store.MAX_QUEUE:
            return False, "The queue is full right now. Please try again later."
        self.store.append({"id": c["id"], "repo": c["url"], "build": build, "category": cat, "note": note,
                           "at": time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(now)), "via": "portal"})
        return True, ""


# The Leyline launcher's download when the admin console has published none (docs/leyline/launcher.md links it too).
RELEASES = "https://github.com/orionopenwow/Leyline/releases"
# the launcher's Dark tokens, when the hub runs without the portal (the portal's LOOK_VARS is the one copy)
LOOK_FALLBACK = (":root{--lk-bg:#15181f;--lk-chrome:#181b23;--lk-surface:#1e222b;--lk-surface-2:#252a35;--lk-raised:#2c3240;"
                 "--lk-border:#2c313c;--lk-border-strong:#3c4352;--lk-text:#eef0f4;--lk-text-2:#c8cdd7;--lk-muted:#9aa1ae;"
                 "--lk-accent:#5b8def;--lk-accent-strong:#7aa3f5;--lk-accent-soft:rgba(91,141,239,.16);--lk-accent-2:#8b6cf0;"
                 "--lk-ok:#4fd18b;--lk-bad:#ff7f76;--lk-r:14px;--lk-r-sm:10px;"
                 "--lk-font:system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif}")

HUB_CSS = """
*{box-sizing:border-box}html{background:var(--lk-bg)}
body.hb{margin:0;min-height:100vh;display:flex;flex-direction:column;background:var(--lk-bg);color:var(--lk-text);font:15px/1.55 var(--lk-font)}
.hb a{color:var(--lk-accent-strong)}
.hb :where(a,button,summary,input,select,textarea,label):focus-visible{outline:2px solid var(--lk-accent-strong);outline-offset:2px}
.hb-skip{position:absolute;left:8px;top:-60px;z-index:30;padding:8px 12px;border-radius:8px;background:var(--lk-accent);color:#fff!important}
.hb-skip:focus{top:8px}
/* the header: the launcher's pages on the web. A sticky bar with a blur; a hairline and a shadow once the page scrolls
   (a scroll timeline where the browser has one, else .hb-scrolled from HUB_JS on the front page) */
.hb-top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:10px 24px;padding:14px clamp(20px,2.6vw,48px);min-height:76px;
background:rgba(24,27,35,.86);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);border-bottom:1px solid transparent}
.hb-top.hb-scrolled{border-bottom-color:var(--lk-border);box-shadow:0 6px 22px rgba(0,0,0,.35)}
@supports (animation-timeline:scroll()){.hb-top{animation:hb-edge linear both;animation-timeline:scroll(root);animation-range:0 56px}}
@keyframes hb-edge{from{border-bottom-color:transparent;box-shadow:none}to{border-bottom-color:var(--lk-border);box-shadow:0 6px 22px rgba(0,0,0,.35)}}
.hb-brand{display:inline-flex;align-items:center;gap:10px;text-decoration:none;color:var(--lk-text)!important;flex:none}
.hb-mark{background:none;box-shadow:none}
.hb-mark::before,.hb-mark::after{inset:0}
.hb-word{display:grid;line-height:1.05}.hb-word b{font-size:23px;font-weight:700;letter-spacing:-.01em}
.hb-word i{font-style:normal;font-weight:600;font-size:15.5px;color:var(--lk-accent)}
.hb-nav{display:flex;align-items:center;gap:clamp(2px,.6vw,12px);margin:0 auto}
.hb-ni,.hb-mi{position:relative;display:inline-flex;align-items:center;gap:9px;padding:10px 14px;border-radius:var(--lk-r-sm);color:var(--lk-text-2)!important;
text-decoration:none;font-weight:600;font-size:16px;white-space:nowrap;cursor:pointer}
.hb-ni svg,.hb-mi svg,.hb-dl svg{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.hb-ni svg{opacity:.8}
.hb-ni:hover,.hb-mi:hover{background:var(--lk-accent-soft);color:var(--lk-text)!important}
.hb-ni.on{color:var(--lk-text)!important;background:var(--lk-accent-soft)}
.hb-ni.on svg{opacity:1;color:var(--lk-accent-strong)}
.hb-ni.on::after{content:"";position:absolute;left:14px;right:14px;bottom:-17px;height:2px;border-radius:2px;background:var(--lk-accent)}
.hb-more-d{position:relative}
.hb-more-d summary{list-style:none}.hb-more-d summary::-webkit-details-marker{display:none}
.hb-more-d summary::after{content:"";width:6px;height:6px;margin-left:2px;border:solid currentColor;border-width:0 1.6px 1.6px 0;transform:translateY(-2px) rotate(45deg)}
.hb-more-d summary.on::after{position:static;height:6px;background:none;border-radius:0}
.hb-more-d[open] summary{background:var(--lk-accent-soft);color:var(--lk-text)!important}
.hb-more-m{position:absolute;right:0;top:calc(100% + 8px);z-index:25;display:grid;min-width:190px;padding:6px;border-radius:var(--lk-r);
background:var(--lk-surface);border:1px solid var(--lk-border-strong);box-shadow:0 14px 40px rgba(0,0,0,.45)}
.hb-mi{padding:9px 10px}.hb-mi.on{color:var(--lk-text)!important;background:var(--lk-accent-soft)}
.hb-nav-x,.hb-dl-x{display:none}
.hb-end{display:flex;align-items:center;gap:12px;flex:none}
.hb-dl{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 20px;border-radius:var(--lk-r-sm);background:var(--lk-accent);
color:#fff!important;text-decoration:none;font-weight:700;font-size:15.5px;box-shadow:0 4px 14px rgba(91,141,239,.3)}
.hb-dl:hover{background:var(--lk-accent-strong)}
.hb-signin,.hb-acct{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 16px 0 8px;border-radius:var(--lk-r-sm);
border:1px solid var(--lk-border-strong);background:transparent;color:var(--lk-text)!important;text-decoration:none;font-weight:600;font-size:15.5px}
.hb-signin:hover,.hb-acct:hover{border-color:var(--lk-accent);background:var(--lk-accent-soft)}
.hb-signin img{transform:scale(1.5)}
.hb-acct{gap:8px;padding:0 12px 0 4px}.hb-acct-n{max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb-av{display:grid;place-items:center;flex:none;width:32px;height:32px;border-radius:50%;font-weight:800;font-size:14px;color:#fff;
background:linear-gradient(135deg,var(--lk-accent),var(--lk-accent-2))}
.hb-menu-t{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
.hb-menu-b{display:none;cursor:pointer;padding:7px 12px;border:1px solid var(--lk-border-strong);border-radius:var(--lk-r-sm);font-weight:600;font-size:14px}
.hb-menu-t:focus-visible+.hb-menu-b{outline:2px solid var(--lk-accent-strong);outline-offset:2px}
.hb-menu-t:checked+.hb-menu-b{background:var(--lk-accent-soft);border-color:var(--lk-accent)}
@media (max-width:1500px){.hb-ni{padding:9px 9px;font-size:15px;gap:7px}.hb-ni svg{width:17px;height:17px}.hb-nav{gap:2px}.hb-top{gap:10px 16px}}
@media (max-width:1320px){.hb-ni svg{display:none}.hb-ni{padding:9px 10px}}
@media (max-width:1180px){.hb-ni svg{display:none}.hb-ni{padding:8px 8px}}
/* tablets and phones: Menu opens a full-width sheet, the same items as a two-column grid of icon tiles */
@media (max-width:1080px){.hb-top{flex-wrap:wrap;padding:9px 16px}
.hb-menu-b{display:inline-block;order:3}.hb-end{margin-left:auto;order:2}
.hb-nav{display:none;order:4;flex:1 0 100%;margin:4px 0 6px;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.hb-menu-t:checked~.hb-nav{display:grid}
.hb-nav .hb-ni{display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:12px;border:1px solid var(--lk-border);
background:var(--lk-surface);white-space:normal}
.hb-nav .hb-ni svg{display:block;width:22px;height:22px;color:var(--lk-accent-strong)}
.hb-ni.on::after{display:none}.hb-nav .hb-ni.on{border-color:var(--lk-accent)}
.hb-more-d{display:none}.hb-nav-x{display:contents}
.hb-dl-x{display:block;grid-column:1/-1;padding:12px;border-radius:var(--lk-r-sm);background:var(--lk-accent);color:#fff!important;
text-align:center;text-decoration:none;font-weight:700}}
@media (max-width:560px){.hb-dl{display:none}.hb-word b{font-size:17px}.hb-word i{font-size:12.5px}.hb-brand .ly-spin{--ly-spin-size:36px!important}
.hb-signin,.hb-acct{padding-right:10px;font-size:13.5px}.hb-acct-n{max-width:70px}.hb-top{gap:8px}}
.hb-main{flex:1;width:100%;max-width:1040px;margin:0 auto;padding:20px 16px 40px}
.hb-flag{margin:0 0 12px;text-align:center;font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--lk-accent-2)}
.hb-sub{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin:0 0 18px}
.hb-sub a{padding:7px 12px;border:1px solid var(--lk-border);border-radius:999px;text-decoration:none;color:var(--lk-muted);font-weight:600;font-size:13px}
.hb-sub a.on,.hb-sub a:hover{color:var(--lk-text);border-color:var(--lk-accent);background:var(--lk-accent-soft)}
/* the hero: the whole Leyline mark leads (owner 2026-10-30: "make the hero image bigger its dwarfed by typography"):
   ~380-400px on a desktop, 220px on a phone, the 512px layers so it stays crisp, a soft glow; the swirl turns slowly */
.hb-hero{position:relative;text-align:center;padding:4px 16px 26px;margin:0 -16px;overflow:hidden;isolation:isolate}
.hb-art{position:relative;display:grid;place-items:center;margin:-6px auto 6px;width:100%;
height:calc(clamp(220px,min(34vw,42vh),400px) + 16px)}
.hb-art::before{content:"";position:absolute;left:50%;top:50%;z-index:-1;width:calc(clamp(220px,min(34vw,42vh),400px) * 1.35);aspect-ratio:1;
transform:translate(-50%,-50%);border-radius:50%;
background:radial-gradient(closest-side,rgba(91,141,239,.34),rgba(139,108,240,.15) 55%,transparent 100%)}
.hb-hero-mark{--ly-spin-size:clamp(220px,min(34vw,42vh),400px)!important;--ly-spin-turn:48s!important}
.hb-hero-mark::before{background-image:url(/wrath/art/leyline-swirl-512.png)}
.hb-hero-mark::after{background-image:url(/wrath/art/leyline-crystal-512.png);filter:drop-shadow(0 0 16px rgba(91,141,239,.6))}
.hb-hero h1{margin:0 0 8px;font-size:clamp(22px,3vw,32px);line-height:1.1;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--lk-text-2)}
.hb-sub-h{max-width:560px;margin:0 auto 18px;color:var(--lk-text-2);font-size:clamp(15px,1.8vw,17px);line-height:1.5}
.hb-hero-a{display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:10px 12px;margin:0}
.hb-cta{display:inline-block;padding:13px 30px;border-radius:var(--lk-r-sm);background:var(--lk-accent);color:#fff!important;
text-decoration:none;font-weight:700;font-size:17px;box-shadow:0 0 0 1px rgba(255,255,255,.08),0 8px 26px rgba(91,141,239,.35)}
.hb-cta:hover{background:var(--lk-accent-strong)}
.hb-cta.sm{padding:10px 18px;font-size:15px;box-shadow:0 6px 18px rgba(91,141,239,.28)}
.hb-ghost.lg{min-height:48px;padding:0 22px;font-size:16px}
.hb-note{margin:10px 0 0;color:var(--lk-muted);font-size:13px}
/* sections */
.hb-sec{margin:26px 0}.hb-sec h2{margin:0 0 12px;font-size:20px;font-weight:700}.hb-sec h3{margin:14px 0 8px;font-size:15px;color:var(--lk-text-2)}
.hb-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.hb-stat{display:grid;gap:2px;padding:12px 14px;background:var(--lk-surface);border:1px solid var(--lk-border);border-radius:var(--lk-r-sm)}
a.hb-stat{text-decoration:none;color:var(--lk-text)!important}a.hb-stat:hover{border-color:var(--lk-accent)}
.hb-stat b{font-weight:650}.hb-stat span{color:var(--lk-muted);font-size:13.5px}
.hb-stat em{font-style:normal;font-weight:700}.hb-stat em.ok{color:var(--lk-ok)}.hb-stat em.bad{color:var(--lk-bad)}
.hb-spots{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,420px),1fr));gap:12px}
.hb-spot{display:flex;gap:14px;padding:12px;background:var(--lk-surface);border:1px solid var(--lk-border);border-radius:var(--lk-r);
text-decoration:none;color:var(--lk-text)!important}
.hb-spot:hover{border-color:var(--lk-accent)}
.hb-pic{flex:none;width:120px;height:84px;border-radius:var(--lk-r-sm);overflow:hidden;display:grid;place-items:center;
background:linear-gradient(135deg,rgba(91,141,239,.35),rgba(139,108,240,.3))}
.hb-pic img{width:100%;height:100%;object-fit:cover}
.hb-initial{font-size:34px;font-weight:800;color:#fff}
.hb-spot-t{display:grid;gap:1px;min-width:0;align-content:start}
.hb-spot-t small{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--lk-accent-2)}
.hb-spot-t b{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb-spot-t i{font-style:normal;font-size:12.5px;color:var(--lk-muted)}
.hb-spot-t span{font-size:13.5px;color:var(--lk-text-2);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
@media (max-width:420px){.hb-pic{width:84px;height:72px}}
.hb-more{margin:10px 0 0;font-size:14px}
.hb-chips{display:flex;flex-wrap:wrap;gap:6px;margin:0}
.hb-chip{padding:7px 12px;border-radius:999px;border:1px solid var(--lk-border);background:var(--lk-surface);text-decoration:none;
color:var(--lk-text-2)!important;font-size:13px}
.hb-chip small{color:var(--lk-muted)}.hb-chip:hover{border-color:var(--lk-accent)}
.hb-chip.on{background:var(--lk-accent-soft);border-color:var(--lk-accent);color:var(--lk-text)!important}
.hb-two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:26px 0}
.hb-box{display:grid;gap:4px;padding:16px;background:var(--lk-surface);border:1px solid var(--lk-border);border-radius:var(--lk-r);
text-decoration:none;color:var(--lk-text-2)!important}
.hb-box b{color:var(--lk-text);font-size:16px}.hb-box:hover{border-color:var(--lk-accent)}
.hb-fine,.hb-count{color:var(--lk-muted);font-size:13.5px;text-align:center}
/* the footer */
.hb-foot{border-top:1px solid var(--lk-border);background:var(--lk-chrome)}
.hb-foot-in{max-width:1040px;margin:0 auto;padding:18px 16px 24px}
.hb-foot-links{display:flex;flex-wrap:wrap;gap:4px 18px;margin-bottom:14px}
.hb-foot-links a,.hb-social a{color:var(--lk-text-2);text-decoration:none;font-size:13.5px}
.hb-foot-links a:hover,.hb-social a:hover{color:var(--lk-text);text-decoration:underline}
.hb-foot-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px 24px}
.hb-brand.small .ly-spin{--ly-spin-size:32px!important}.hb-brand.small .hb-word b{font-size:16px}.hb-brand.small .hb-word i{font-size:12px}
.hb-foot-fine{margin:0;color:var(--lk-muted);font-size:13px;flex:1 1 220px}
.hb-social{display:flex;gap:16px}
/* the sub-pages (catalog, item, creators, realms, beacon, submit): the same flat panels */
.hb .ly-panel{background:var(--lk-surface);border:1px solid var(--lk-border);border-radius:var(--lk-r);padding:20px;margin:16px 0}
.hb h1{font-size:clamp(28px,4.6vw,40px);line-height:1.1;margin:0 0 10px;font-weight:800;letter-spacing:-.01em}
.hb .ly-panel h2{font-size:20px;margin:0 0 10px}
.hb-head{text-align:center}.hb-head p{color:var(--lk-muted)}
.hb .ly-btn{display:inline-flex;align-items:center;padding:10px 18px;border-radius:var(--lk-r-sm);background:var(--lk-accent);color:#fff!important;
border:1px solid var(--lk-accent);text-decoration:none;font:600 15px var(--lk-font);cursor:pointer}
.hb .ly-btn:hover{background:var(--lk-accent-strong)}
.hb .ly-btn.hb-alt{background:var(--lk-raised);border-color:var(--lk-border-strong);color:var(--lk-text)!important}
.hb-actions{display:flex;flex-wrap:wrap;gap:10px}
.hb .ly-table{width:100%;border-collapse:collapse;font-size:14px;margin:10px 0}
.hb .ly-table th,.hb .ly-table td{text-align:left;padding:8px;border-bottom:1px solid var(--lk-border)}
.hb .ly-table th{color:var(--lk-muted);font-weight:600;width:34%}
.hb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.hb-card{padding:14px;border:1px solid var(--lk-border);border-radius:var(--lk-r);background:var(--lk-surface)}
.hb-card h3{margin:0 0 4px;font-size:16px;font-weight:650}
.hb-card h3 a{text-decoration:none;color:var(--lk-text)}.hb-card p{margin:4px 0;font-size:14px;overflow-wrap:anywhere;color:var(--lk-text-2)}
.hb-by,.hb-meta{color:var(--lk-muted)!important}
.hb-tag,.hb-src{display:inline-block;margin:2px 4px 2px 0;padding:2px 8px;border-radius:999px;border:1px solid var(--lk-border);font-size:12px}
.hb-src.hb-workshop{border-color:var(--lk-ok);color:var(--lk-ok)}.hb-src.hb-theme{border-color:var(--lk-accent-2);color:var(--lk-accent-2)}
.hb-lic{font-size:12px}
.hb-filters p{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.hb-search{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.hb-search input,.hb-form input,.hb-form select,.hb-form textarea{min-height:40px;padding:8px 10px;border-radius:var(--lk-r-sm);
border:1px solid var(--lk-border-strong);background:var(--lk-surface-2);color:var(--lk-text);font:15px var(--lk-font);max-width:100%}
.hb-search input{flex:1 1 220px}.hb-search button{min-height:40px;padding:0 16px;border-radius:var(--lk-r-sm);border:1px solid var(--lk-accent);
background:var(--lk-accent);color:#fff;font:600 14px var(--lk-font);cursor:pointer}
.hb-form{display:grid;gap:8px;max-width:560px}.hb-form label{font-weight:600}
.hb-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.hb-err{padding:10px;border:1px solid var(--lk-bad);border-radius:var(--lk-r-sm);color:var(--lk-bad)}
.hb-pages{display:flex;gap:14px;justify-content:center;margin:16px 0}
.hb-card-pic{display:block;margin:-14px -14px 10px;aspect-ratio:2/1;overflow:hidden;border-radius:var(--lk-r) var(--lk-r) 0 0;background:var(--lk-surface-2)}
.hb-card-pic img,.hb-card-pic .hb-gt-art{display:grid;width:100%;height:100%;object-fit:cover}
.hb-card-art.gen b{font-size:44px}
.hb-src.hb-external{border-color:#e0a84a;color:#f0c27a}
.hb-ext-b{margin:6px 0;padding:6px 10px;border-radius:var(--lk-r-sm);border:1px solid rgba(224,168,74,.55);background:rgba(224,168,74,.1);
color:#f3d29a!important;font-size:13px!important}
.hb-ext-b b{margin-right:6px;padding:1px 7px;border-radius:999px;background:#e0a84a;color:#1b1406;font-size:11px;letter-spacing:.06em;text-transform:uppercase}
.hb-ext-a{margin-top:8px!important}
.hb-ext-s{margin:28px 0 8px}.hb-ext-s h2{margin:0 0 4px;font-size:20px}.hb-ext-lede{margin:0 0 12px;color:var(--lk-text-2)}
.hb-item-pic{margin:0 0 14px;max-width:640px;border-radius:var(--lk-r-sm);overflow:hidden;background:var(--lk-surface-2)}
.hb-item-pic img,.hb-item-pic .hb-gt-art{display:grid;width:100%;height:auto;aspect-ratio:2/1;object-fit:cover}
.hb-item-pic figcaption,.hb-th-cr{padding:5px 10px;font-size:12px;color:var(--lk-muted)}
.hb-th-cr{padding:0;margin:8px 0 0!important}
.hb-motw-pic .hb-gt-art{width:100%;height:100%}
.hb-item h1{text-align:left}.hb-sum{font-size:17px}.hb-repo{color:var(--lk-muted)}
.hb-list li{margin:4px 0}.hb-empty{color:var(--lk-muted)}
.hb .realm{background:var(--lk-surface)!important;border:1px solid var(--lk-border)!important;border-radius:var(--lk-r)!important;box-shadow:none!important}
.hb .tag{background:var(--lk-surface-2)!important;border-color:var(--lk-border)!important;color:var(--lk-text-2)!important}
/* the realm list under the hero: every server on the network, one row each */
.hb-rl-head{display:flex;flex-wrap:wrap;align-items:end;justify-content:space-between;gap:8px 16px;margin:0 0 10px}
.hb-rl-head h2{margin:0}
.hb-netline{margin:2px 0 0;color:var(--lk-muted);font-size:13.5px}
.hb-dot{display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:var(--lk-ok);vertical-align:1px;
box-shadow:0 0 0 3px rgba(79,209,139,.18)}
.hb-rf{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;font-size:13.5px;color:var(--lk-text-2)}
.hb-rf select{min-height:34px;padding:4px 8px;border-radius:var(--lk-r-sm);border:1px solid var(--lk-border-strong);background:var(--lk-surface-2);
color:var(--lk-text);font:14px var(--lk-font)}
.hb-rf input{accent-color:var(--lk-accent)}
.hb-rf button{min-height:34px;padding:0 12px;border-radius:var(--lk-r-sm);border:1px solid var(--lk-border-strong);background:var(--lk-raised);
color:var(--lk-text);font:600 13.5px var(--lk-font);cursor:pointer}
.hb-rlist{list-style:none;margin:0;padding:0;border:1px solid var(--lk-border);border-radius:var(--lk-r);background:var(--lk-surface);overflow:hidden}
.hb-rl{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:6px 16px;padding:11px 14px;
border-top:1px solid var(--lk-border);transition:background-color .15s}
.hb-rl:first-child{border-top:0}.hb-rl:hover{background:var(--lk-surface-2)}
.hb-rl.home{background:linear-gradient(90deg,var(--lk-accent-soft),transparent 70%)}
.hb-rl[hidden],.hb-rlist.cap>.hb-rl:nth-child(n+9){display:none}
.hb-rl-n{display:flex;flex-wrap:wrap;align-items:center;gap:3px 8px;min-width:0}
.hb-rl-n b{font-weight:650;overflow-wrap:anywhere}
.hb-rl-m{flex:1 0 100%;color:var(--lk-muted);font-size:12.5px}
.hb-bdg{padding:0 7px;border-radius:999px;border:1px solid var(--lk-border-strong);color:var(--lk-text-2);font-size:11px;font-weight:700;letter-spacing:.04em;line-height:18px}
.hb-bdg.o{border-color:var(--lk-accent);color:var(--lk-accent-strong)}.hb-bdg.f{border-color:var(--lk-accent-2);color:var(--lk-accent-2)}
.hb-bdg.v{border-color:var(--lk-ok);color:var(--lk-ok)}
.hb-rl-p{text-align:right;font-size:13.5px;color:var(--lk-text-2);white-space:nowrap}
.hb-rl-p b{color:var(--lk-text);font-weight:700;font-variant-numeric:tabular-nums}.hb-rl-p small{display:block;color:var(--lk-muted);font-size:12px}
.hb-rl-p.off{color:var(--lk-muted)}
.hb-rl-p b.bump{animation:hb-bump .9s ease-out}
@keyframes hb-bump{from{color:var(--lk-ok)}}
.hb-rl-a{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:6px}
.hb-play,.hb-ghost{display:inline-flex;align-items:center;min-height:34px;padding:0 12px;border-radius:var(--lk-r-sm);text-decoration:none;
font-weight:650;font-size:13.5px;white-space:nowrap}
.hb-play{background:var(--lk-accent);color:#fff!important}.hb-play:hover{background:var(--lk-accent-strong)}
.hb-ghost{border:1px solid var(--lk-border-strong);color:var(--lk-text)!important}.hb-ghost:hover{border-color:var(--lk-accent);background:var(--lk-accent-soft)}
.hb-need{color:var(--lk-muted);font-size:12.5px}
code.hb-addr{padding:6px 8px;border-radius:8px;background:var(--lk-surface-2);color:var(--lk-text-2);font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
-webkit-user-select:all;user-select:all;overflow-wrap:anywhere}
.hb-copy{min-height:30px;padding:0 10px;border-radius:8px;border:1px solid var(--lk-border-strong);background:transparent;color:var(--lk-text-2);
font:600 12.5px var(--lk-font);cursor:pointer}.hb-copy:hover{border-color:var(--lk-accent);color:var(--lk-text)}
.hb-rl-none{padding:14px;color:var(--lk-muted);text-align:center}
@media (max-width:640px){.hb-rl{grid-template-columns:minmax(0,1fr) auto;padding:11px 12px}.hb-rl-a{grid-column:1/-1;justify-content:flex-start}}
/* how it works: three steps in one slim strip */
.hb-how{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;margin:22px 0;padding:0;list-style:none;counter-reset:hb-how;
border:1px solid var(--lk-border);border-radius:var(--lk-r);background:var(--lk-chrome)}
.hb-how li{position:relative;display:grid;gap:2px;padding:12px 16px 12px 52px;counter-increment:hb-how;border-left:1px solid var(--lk-border)}
.hb-how li:first-child{border-left:0}
.hb-how li::before{content:counter(hb-how);position:absolute;left:16px;top:13px;display:grid;place-items:center;width:24px;height:24px;border-radius:50%;
background:var(--lk-accent-soft);color:var(--lk-accent-strong);font-weight:700;font-size:13px;box-shadow:0 0 0 1px var(--lk-accent)}
.hb-how b{font-weight:650}.hb-how span{color:var(--lk-muted);font-size:13px}
@media (max-width:720px){.hb-how{grid-template-columns:1fr}.hb-how li{border-left:0;border-top:1px solid var(--lk-border)}.hb-how li:first-child{border-top:0}}
/* the feature sections, in the recommended order: full-width bands, words and a picture side by side, flipping sides */
.hb-vh{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.hb-fs{position:relative;display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);align-items:center;gap:28px 44px;padding:56px 0;
border-top:1px solid var(--lk-border);scroll-margin-top:72px}
.hb-fs.flip{grid-template-columns:minmax(0,7fr) minmax(0,5fr);background:var(--lk-chrome);
box-shadow:0 0 0 100vmax var(--lk-chrome);clip-path:inset(0 -100vmax)}
.hb-fs.flip .hb-fs-t{order:2}
.hb-eyebrow{display:flex;align-items:center;gap:10px;margin:0 0 10px;color:var(--lk-accent-strong);font-size:12.5px;font-weight:700;
letter-spacing:.1em;text-transform:uppercase}
.hb-ico{display:grid;place-items:center;flex:none;width:34px;height:34px;border-radius:10px;background:var(--lk-accent-soft);color:var(--lk-accent-strong)}
.hb-ico svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.hb-fs h2{margin:0 0 12px;font-size:clamp(24px,3.4vw,32px);line-height:1.15;font-weight:800;letter-spacing:-.01em}
.hb-lede{margin:0 0 14px;color:var(--lk-text-2);font-size:16px}
.hb-points{margin:0 0 20px;padding:0;list-style:none;display:grid;gap:7px}
.hb-points li{position:relative;padding-left:24px;color:var(--lk-text-2);font-size:14.5px}
.hb-points li::before{content:"";position:absolute;left:3px;top:.5em;width:8px;height:8px;border-radius:50%;background:var(--lk-accent);
box-shadow:0 0 0 3px var(--lk-accent-soft)}
.hb-fs-a{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0}
.hb-fs-a .hb-ghost{min-height:42px;padding:0 16px;font-size:14.5px}
.hb-shot{margin:0;border-radius:var(--lk-r);overflow:hidden;border:1px solid var(--lk-border-strong);background:var(--lk-surface);
box-shadow:0 18px 50px rgba(0,0,0,.45),0 0 0 1px rgba(91,141,239,.12),0 0 60px rgba(91,141,239,.10)}
.hb-shot img{display:block;width:100%;height:auto}
/* the drawings (host, community, agents): plain CSS, the launcher's colours */
.hb-draw{margin:0;padding:22px;border-radius:var(--lk-r);border:1px solid var(--lk-border-strong);background:var(--lk-surface);
box-shadow:0 18px 50px rgba(0,0,0,.4),0 0 60px rgba(91,141,239,.08)}
.hb-draw p{margin:0}
.hb-dt{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px!important;font-size:17px}
.hb-dt em{font-style:normal;font-size:12.5px;font-weight:700;color:var(--lk-ok);padding:2px 10px;border-radius:999px;border:1px solid var(--lk-ok)}
.hb-svc{display:flex;align-items:center;gap:10px;padding:10px 12px;margin-top:8px!important;border-radius:var(--lk-r-sm);
background:var(--lk-surface-2);font-size:14.5px;font-weight:600}
.hb-svc i{width:9px;height:9px;border-radius:50%;background:var(--lk-ok);box-shadow:0 0 0 3px rgba(79,209,139,.18)}
.hb-svc span{margin-left:auto;color:var(--lk-muted);font-weight:500;font-size:13px}
.hb-cores{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0!important}
.hb-cores span{padding:3px 10px;border-radius:999px;border:1px solid var(--lk-border-strong);color:var(--lk-text-2);font-size:12.5px}
.hb-dbtn{display:flex;gap:10px}.hb-dbtn span{flex:1;text-align:center;padding:10px;border-radius:var(--lk-r-sm);font-weight:700;font-size:14px;
border:1px solid var(--lk-border-strong)}.hb-dbtn span:first-child{background:var(--lk-accent);border-color:var(--lk-accent);color:#fff}
.hb-people{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.hb-pp{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:2px 12px;padding:12px;border-radius:var(--lk-r-sm);
background:var(--lk-surface-2)}
.hb-pp i{grid-row:span 2;display:grid;place-items:center;width:42px;height:42px;border-radius:12px;font-style:normal;font-weight:800;color:#fff;
background:linear-gradient(135deg,hsl(var(--h) 70% 62%),hsl(calc(var(--h) + 40) 60% 52%))}
.hb-pp b{font-size:14.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hb-pp span{color:var(--lk-muted);font-size:12.5px}
.hb-code{overflow:auto;font:13.5px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--lk-text-2);white-space:pre}
.hb-code s{text-decoration:none;color:var(--lk-accent-2);font-weight:700}.hb-code u{text-decoration:none;color:var(--lk-accent-strong)}
.hb-code q{quotes:none;color:var(--lk-ok)}
@media (max-width:860px){.hb-fs,.hb-fs.flip{grid-template-columns:minmax(0,1fr);gap:22px;padding:40px 0}.hb-fs.flip .hb-fs-t{order:0}}
@media (max-width:420px){.hb-people{grid-template-columns:minmax(0,1fr)}.hb-draw{padding:16px}.hb-code{font-size:12px}}
/* lift and glow on hover, like the launcher's cards; never with reduced motion */
.hb-stat,.hb-spot,.hb-box,.hb-card,.hb-mode{transition:transform .15s ease,border-color .15s,box-shadow .15s}
:is(a.hb-stat,.hb-spot,.hb-box,.hb-mode):hover{transform:translateY(-2px);border-color:var(--lk-accent);
box-shadow:0 8px 24px rgba(0,0,0,.28),0 0 0 1px rgba(91,141,239,.35),0 0 26px rgba(91,141,239,.12)}
/* section reveal: only sections below the fold when the page loads, only with script, only with motion */
.hb-js .hb-wait{opacity:0;transform:translateY(10px)}
.hb-js .hb-wait.in{opacity:1;transform:none;transition:opacity .5s ease,transform .5s ease}
/* the modes and news sub-pages */
.hb-modes{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:12px}
.hb-mode{display:grid;gap:6px;align-content:start;padding:16px;background:var(--lk-surface);border:1px solid var(--lk-border);border-radius:var(--lk-r)}
.hb-mode h2{margin:0;font-size:17px}.hb-mode p{margin:0;color:var(--lk-text-2);font-size:14px}
.hb-mode .hb-act{margin-top:6px}
.hb-news{display:grid;gap:12px}.hb-news article{padding:16px;background:var(--lk-surface);border:1px solid var(--lk-border);border-radius:var(--lk-r)}
.hb-news small{color:var(--lk-accent-2);font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:11px}
.hb-news h2{margin:4px 0 6px;font-size:18px}.hb-news ul{margin:0;padding-left:20px;color:var(--lk-text-2)}
/* the network's filters and Host your own, in the flat look */
.hb .net-filters{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:center;margin:8px 0 14px;font-size:13.5px}
.hb .net-filters span{color:var(--lk-muted)}.hb .net-filters a{color:var(--lk-text-2);white-space:nowrap}
.hb .net-filters a.on{color:var(--lk-text);font-weight:700;text-decoration:none}
.hb .host-cta{margin:18px 0;padding:18px 20px;border:1px solid var(--lk-border);border-radius:var(--lk-r);background:var(--lk-surface)}
.hb .host-cta h2{margin:0 0 6px;font-size:20px}.hb .host-cta ol{margin:8px 0 10px 1.2em;padding:0;color:var(--lk-text-2)}
.hb .host-cta .btn{display:inline-flex;padding:9px 16px;border-radius:var(--lk-r-sm);border:1px solid var(--lk-border-strong);
color:var(--lk-text)!important;text-decoration:none;font-weight:600}
.hb .host-cta .btn.primary{background:var(--lk-accent);border-color:var(--lk-accent);color:#fff!important}
.hb .fine{color:var(--lk-muted);font-size:13.5px}
/* the realm list: a hover / focus preview of the realm (its tagline and tags), laid over the rows below */
.hb-rlist{overflow:visible}.hb-rl:first-child{border-radius:var(--lk-r) var(--lk-r) 0 0}.hb-rl:last-child,.hb-rlist.cap>.hb-rl:nth-child(8){border-radius:0 0 var(--lk-r) var(--lk-r)}
.hb-rl{position:relative}
.hb-rl-pv{position:absolute;left:14px;top:calc(100% - 4px);z-index:6;width:min(420px,calc(100% - 28px));padding:10px 12px;border-radius:var(--lk-r-sm);
background:var(--lk-raised);border:1px solid var(--lk-border-strong);box-shadow:0 12px 32px rgba(0,0,0,.5);pointer-events:none;
visibility:hidden;opacity:0;transform:translateY(-4px);transition:opacity .15s,transform .15s,visibility 0s .15s}
.hb-rl-pv p{margin:0;color:var(--lk-text-2);font-size:13.5px}
.hb-rl-pt{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px!important}
.hb-rl-pt span{padding:1px 8px;border-radius:999px;border:1px solid var(--lk-border-strong);font-size:12px;color:var(--lk-muted)}
.hb-rl.pv:is(:hover,:focus-within){z-index:7}
.hb-rl.pv:is(:hover,:focus-within) .hb-rl-pv{visibility:visible;opacity:1;transform:none;transition:opacity .15s,transform .15s}
@media (hover:none){.hb-rl.pv:hover:not(:focus-within) .hb-rl-pv{visibility:hidden}}
/* the live ticker under the hero: one slow loop, paused on hover or focus, still with reduced motion */
.hb-tick{position:relative;margin:0 -16px 6px;overflow:hidden;border-block:1px solid var(--lk-border);background:var(--lk-chrome);
-webkit-mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent);mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent)}
.hb-tick-run{display:flex;width:max-content;animation:hb-tick 48s linear infinite}
.hb-tick:is(:hover,:focus-within) .hb-tick-run{animation-play-state:paused}
@keyframes hb-tick{to{transform:translateX(-50%)}}
.hb-tick-l{display:flex;flex:none;justify-content:space-around;gap:0;min-width:1040px;margin:0;padding:0;list-style:none}
.hb-tick-l li{flex:none;padding:8px 26px;color:var(--lk-text-2);font-size:13.5px;white-space:nowrap}
.hb-tick-l li::before{content:"";display:inline-block;width:7px;height:7px;margin-right:9px;border-radius:50%;background:var(--lk-ok);vertical-align:1px}
.hb-tick-l li.new::before{background:var(--lk-accent-2)}
.hb-tick-l b{color:var(--lk-text);font-variant-numeric:tabular-nums}
/* the numbers */
.hb-nums{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0 6px;text-align:center}
.hb-nums p{display:grid;gap:2px;margin:0;padding:14px 10px}
.hb-num{font-size:clamp(30px,4.4vw,42px);font-weight:800;line-height:1;font-variant-numeric:tabular-nums;
background:linear-gradient(180deg,#fff,var(--lk-accent-strong));-webkit-background-clip:text;background-clip:text;color:transparent}
.hb-nums span{color:var(--lk-muted);font-size:13.5px}
/* the ley line down the feature sections */
.hb-feats{position:relative}
.hb-thread{position:absolute;left:-58px;top:40px;width:40px;height:calc(100% - 80px);overflow:visible;pointer-events:none;z-index:2}
.hb-thread path{fill:none;stroke:url(#hb-tg);stroke-width:2;stroke-linecap:round;opacity:.45;vector-effect:non-scaling-stroke;
filter:drop-shadow(0 0 4px rgba(120,120,255,.6))}
.hb-js .hb-thread.draw path{stroke-dasharray:1;stroke-dashoffset:var(--hb-draw,1)}
.hb-fs::before{content:"";position:absolute;z-index:2;left:-43px;top:66px;width:9px;height:9px;border-radius:50%;background:var(--lk-accent-2);
box-shadow:0 0 0 4px rgba(139,108,240,.18),0 0 14px rgba(139,108,240,.6);opacity:.7;pointer-events:none}
@media (max-width:1150px){.hb-thread,.hb-fs::before{display:none}}
/* the screenshots lean toward the cursor (HUB_JS: fine pointers, motion allowed) */
.hb-shot{position:relative;transform:perspective(1100px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .25s ease,box-shadow .25s}
.hb-shot::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .25s;
background:radial-gradient(circle at var(--gx,50%) var(--gy,50%),rgba(122,163,245,.18),transparent 55%)}
.hb-shot.tilt::after{opacity:1}
.hb-shot.tilt{box-shadow:0 22px 60px rgba(0,0,0,.5),0 0 0 1px rgba(91,141,239,.25),0 0 80px rgba(91,141,239,.2)}
/* hosted by the community: posters */
.hb-posters{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:14px}
.hb-poster{position:relative;isolation:isolate;display:flex;flex-direction:column;justify-content:flex-end;min-height:300px;padding:18px;
border-radius:var(--lk-r);overflow:hidden;border:1px solid var(--lk-border-strong);
background:linear-gradient(var(--a),hsl(var(--h1) 55% 26%),hsl(var(--h2) 50% 16%) 70%,#11131a)}
.hb-poster-bg{position:absolute;inset:0;z-index:-1;
background:url(/wrath/art/leyline-crystal-256.webp) var(--x) var(--y)/58% no-repeat,
repeating-radial-gradient(circle at var(--x) var(--y),transparent 0 22px,hsl(var(--h2) 80% 70% / .08) 22px 23px);opacity:.55;
transform:rotate(var(--r));transform-origin:var(--x) var(--y);scale:1.2}
.hb-poster::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,transparent 30%,rgba(10,12,18,.88))}
.hb-poster h3{margin:0 0 4px;font-size:22px;font-weight:800;letter-spacing:-.01em;color:#fff}
.hb-poster-p{position:absolute;top:14px;left:16px;margin:0;font-size:12.5px;color:#dfe6ff}
.hb-poster-p b{font-size:15px}
.hb-poster-l{margin:0 0 8px;color:#d6dbea;font-size:14px}
.hb-poster-tags{display:flex;flex-wrap:wrap;gap:5px;margin:0 0 12px}
.hb-poster-tags span{padding:1px 8px;border-radius:999px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);font-size:12px;color:#eef}
.hb-poster-a{display:flex;flex-wrap:wrap;gap:8px;margin:0}
.hb-poster .hb-ghost{background:rgba(10,12,18,.4)}
/* mod of the week and Hero Key, side by side */
.hb-pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:14px;margin:26px 0}
.hb-motw,.hb-hk{display:grid;gap:16px;padding:18px;border-radius:var(--lk-r);border:1px solid var(--lk-border);background:var(--lk-surface)}
.hb-motw{grid-template-columns:minmax(0,2fr) minmax(0,3fr);align-items:center}
.hb-motw-pic{aspect-ratio:16/10;border-radius:var(--lk-r-sm);overflow:hidden;display:grid;place-items:center;
background:linear-gradient(135deg,rgba(91,141,239,.4),rgba(139,108,240,.35))}
.hb-motw-pic img{width:100%;height:100%;object-fit:cover}
.hb-kick{display:flex;align-items:center;gap:8px;margin:0 0 4px;font-size:11.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--lk-accent-2)}
.hb-motw h2,.hb-hk h2{margin:0 0 2px;font-size:22px;font-weight:800}
.hb-motw .hb-by{margin:0 0 8px;font-size:13px}.hb-motw-l,.hb-hk p{margin:0 0 12px;color:var(--lk-text-2);font-size:14.5px}
.hb-hk{grid-template-columns:minmax(0,1fr)}
.hb-hk-art{position:relative;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding-top:30px}
.hb-hk-c{display:grid;justify-items:center;gap:6px;padding:12px 6px;border-radius:var(--lk-r-sm);background:var(--lk-surface-2);
border:1px solid var(--lk-border);font-size:12.5px;font-weight:600;color:var(--lk-text-2);text-align:center;overflow-wrap:anywhere}
.hb-hk-c i{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,var(--lk-accent),var(--lk-accent-2));opacity:.8}
.hb-hk-key{position:absolute;top:0;left:calc(100% / 6 - 13px);width:26px;height:26px;color:#ffd77a;animation:hb-key 7.5s ease-in-out infinite}
.hb-hk-key svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;filter:drop-shadow(0 0 6px rgba(255,215,122,.6))}
@keyframes hb-key{0%,22%{left:calc(100% / 6 - 13px)}33%,55%{left:calc(50% - 13px)}66%,88%{left:calc(500% / 6 - 13px)}100%{left:calc(100% / 6 - 13px)}}
@media (max-width:520px){.hb-motw{grid-template-columns:minmax(0,1fr)}}
/* creator spotlight and news */
.hb-crs{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:10px}
.hb-cr{display:flex;align-items:center;gap:12px;padding:12px;border-radius:var(--lk-r);border:1px solid var(--lk-border);background:var(--lk-surface);
text-decoration:none;color:var(--lk-text)!important}
.hb-cr .hb-av{width:42px;height:42px;font-size:18px}
.hb-cr>span:last-child{display:grid;min-width:0}.hb-cr b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb-cr small{color:var(--lk-muted);font-size:12.5px}.hb-cr i{font-style:normal;font-size:12.5px;color:var(--lk-text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb-nws{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:10px}
.hb-nw{display:grid;gap:3px;align-content:start;padding:14px;border-radius:var(--lk-r);border:1px solid var(--lk-border);background:var(--lk-surface);
text-decoration:none;color:var(--lk-text)!important}
.hb-nw small{color:var(--lk-accent-2);font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:11px}
.hb-nw b{font-size:16px}.hb-nw span{color:var(--lk-text-2);font-size:13.5px}
:is(.hb-cr,.hb-nw){transition:transform .15s ease,border-color .15s,box-shadow .15s}
:is(.hb-cr,.hb-nw):hover{transform:translateY(-2px);border-color:var(--lk-accent);box-shadow:0 8px 24px rgba(0,0,0,.28),0 0 26px rgba(91,141,239,.12)}
/* the footer's status dot */
.hb-health{display:inline-flex;align-items:center;gap:8px;margin:0 0 12px;color:var(--lk-text-2)!important;text-decoration:none;font-size:13px;font-weight:600}
.hb-health:hover{color:var(--lk-text)!important}
.hb-hdot{width:9px;height:9px;border-radius:50%;background:var(--lk-ok)}
.hb-health.ok .hb-hdot{animation:hb-pulse 2.4s ease-out infinite}
.hb-health.warn .hb-hdot{background:#f0b54a}.hb-health.bad .hb-hdot{background:var(--lk-bad)}
@keyframes hb-pulse{0%{box-shadow:0 0 0 0 rgba(79,209,139,.55)}80%,100%{box-shadow:0 0 0 9px rgba(79,209,139,0)}}
/* the gallery: a bento of our own pictures (in game, the launcher, the Workshop), the caption on hover and focus (always
   on touch), a lightbox from HUB_JS; uniform tiles while a filter is on */
.hb-gal-hd{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px 16px;margin:0 0 14px}
.hb-gal-hd h2{margin:0}.hb-gal-sub{margin:2px 0 0;color:var(--lk-muted);font-size:14px}
.hb-gal-f{display:flex;flex-wrap:wrap;gap:6px}
.hb-gal{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:clamp(120px,15vw,184px);grid-auto-flow:dense;gap:10px}
.hb-gal.flt .hb-gt{grid-column:auto;grid-row:auto}
.hb-gal-none{grid-column:1/-1;margin:0;padding:30px;text-align:center;color:var(--lk-muted)}
.hb-gt{position:relative;isolation:isolate;margin:0;min-width:0;border-radius:var(--lk-r);overflow:hidden;background:var(--lk-surface-2);
border:1px solid var(--lk-border);transition:border-color .2s,box-shadow .2s}
.hb-gt[hidden]{display:none}
.hb-gt.big{grid-column:span 2;grid-row:span 2}.hb-gt.wide{grid-column:span 2}
.hb-gt:is(:hover,:focus-within){border-color:var(--lk-accent);box-shadow:0 12px 34px rgba(0,0,0,.4),0 0 30px rgba(91,141,239,.14)}
.hb-gt-a{position:absolute;inset:0;display:block;border-radius:inherit;overflow:hidden;color:#fff!important;text-decoration:none}
.hb-gt-a:focus-visible{outline-offset:-3px}
.hb-gt-a img,.hb-gt-a .hb-gt-art{display:block;width:100%;height:100%;object-fit:cover;transition:transform .55s cubic-bezier(.2,.7,.2,1)}
.hb-gt:is(:hover,:focus-within) :is(.hb-gt-a img,.hb-gt-a .hb-gt-art){transform:scale(1.05)}
.hb-gt-art,.hb-gt-a .hb-gt-art{position:relative;display:grid;place-items:center}
.hb-gt-art svg{fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.hb-gt-art.gen{color:#fff;background:url(/wrath/art/leyline-crystal-256.webp) 94% 118%/34% no-repeat,
linear-gradient(var(--a),hsl(var(--h1) 55% 30%),hsl(var(--h2) 50% 16%) 72%,#11131a)}
.hb-gt-art.gen b{font-size:clamp(40px,6vw,76px);font-weight:800;line-height:1;opacity:.94;text-shadow:0 6px 30px rgba(0,0,0,.35)}
.hb-gt-art.gen svg{position:absolute;top:12px;left:12px;width:22px;height:22px;opacity:.8}
.hb-gt-art.flat{background:radial-gradient(circle at 50% 46%,rgba(91,141,239,.24),rgba(139,108,240,.08) 46%,transparent 70%),var(--lk-surface-2)}
.hb-gt-art.flat .ly-spin{--ly-spin-size:clamp(64px,9vw,120px)!important}
.hb-gt-c{position:absolute;left:0;right:0;bottom:0;z-index:1;display:grid;gap:1px;padding:34px 14px 12px;pointer-events:none;
background:linear-gradient(180deg,transparent,rgba(10,12,18,.72) 38%,rgba(10,12,18,.94));opacity:0;transform:translateY(10px);
transition:opacity .25s ease,transform .25s ease}
.hb-gt:is(:hover,:focus-within) .hb-gt-c{opacity:1;transform:none}
@media (hover:none){.hb-gt-c{opacity:1;transform:none}}
.hb-gt.flat .hb-gt-c{opacity:1;transform:none}
.hb-gt-c small{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#a9c2ff}
.hb-gt-c b{font-size:15px;font-weight:700;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb-gt.big .hb-gt-c b{font-size:21px}
.hb-gt-l{font-size:12.5px;color:#d6dbea;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hb-gt-c i{font-style:normal;font-size:12px;color:#aab2c2}
.hb-gt-x{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}.hb-gt-x[hidden]{display:none}
.hb-gt-x a{pointer-events:auto;padding:5px 10px;border-radius:8px;font-size:12.5px;font-weight:650;text-decoration:none}
.hb-gt-i{background:var(--lk-accent);color:#fff!important}.hb-gt-i:hover{background:var(--lk-accent-strong)}
.hb-gt-v{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.22);color:#eef!important}
.hb-gal.strip{grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));grid-auto-rows:160px}
.hb-feat-s{margin:0 0 18px}.hb-feat-s h2{margin:0 0 10px;font-size:17px}
@media (max-width:640px){.hb-gal{grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:124px;gap:8px}
.hb-gt:not(.big,.wide) :is(.hb-gt-l,.hb-gt-c i,.hb-gt-x){display:none}
.hb-gt-c{padding:26px 10px 9px}.hb-gt-c b{font-size:13.5px}.hb-gal.strip{grid-template-columns:repeat(2,minmax(0,1fr))}}
/* the lightbox (HUB_JS builds it; without script each tile is a plain link) */
html.hb-lb-on{overflow:hidden}
.hb-lb{position:fixed;inset:0;z-index:50;display:grid;place-items:center;padding:clamp(8px,3vw,36px);background:rgba(8,10,14,.88);
-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);opacity:0;transition:opacity .2s ease}
.hb-lb[hidden]{display:none}.hb-lb.open{opacity:1}
.hb-lb-in{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 300px;width:min(1240px,100%);max-height:100%;overflow:hidden;
background:var(--lk-surface);border:1px solid var(--lk-border-strong);border-radius:var(--lk-r);box-shadow:0 30px 80px rgba(0,0,0,.6);
transform:scale(.97);transition:transform .22s ease}
.hb-lb.open .hb-lb-in{transform:none}
.hb-lb-pic{position:relative;display:grid;place-items:center;min-height:0;min-width:0;background:#0b0d12}
.hb-lb-pic img{display:block;max-width:100%;max-height:calc(100vh - 90px);width:auto;height:auto;object-fit:contain}
.hb-lb-pic .hb-gt-art{width:100%;aspect-ratio:16/9;transform:none!important}
.hb-lb-pic .hb-gt-art.gen{background-size:24%,auto;background-position:92% 108%,0 0}.hb-lb-pic .hb-gt-art.gen b{font-size:clamp(80px,14vw,160px)}
.hb-lb-pic .hb-gt-art.gen svg{width:30px;height:30px;top:18px;left:18px}
.hb-lb-cap{display:grid;align-content:start;gap:6px;padding:22px 20px;overflow:auto}
.hb-lb-cap small{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--lk-accent-2)}
.hb-lb-cap h2{margin:0;font-size:22px;line-height:1.2}.hb-lb-cap p{margin:0;color:var(--lk-text-2)}
.hb-lb-cap .hb-lb-cr{color:var(--lk-muted);font-size:13.5px}
.hb-lb-a{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.hb-lb-n{color:var(--lk-muted);font-size:12.5px;margin-top:8px!important}
.hb-lb button{display:grid;place-items:center;width:40px;height:40px;padding:0;border-radius:50%;border:1px solid rgba(255,255,255,.2);
background:rgba(16,18,24,.78);color:#fff;cursor:pointer;font:600 20px/1 var(--lk-font)}
.hb-lb button:hover{background:var(--lk-accent);border-color:var(--lk-accent)}
.hb-lb button svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.hb-lb-x{position:absolute;top:10px;right:10px;z-index:2}
.hb-lb-p,.hb-lb-nx{position:absolute;top:50%;margin-top:-20px}.hb-lb-p{left:10px}.hb-lb-nx{right:10px}
.hb-lb button[hidden]{display:none}
@media (max-width:760px){.hb-lb{padding:0;place-items:stretch}.hb-lb-in{grid-template-columns:1fr;grid-template-rows:auto 1fr;border-radius:0;overflow:auto;width:100%}
.hb-lb-pic img{max-height:62vh}.hb-lb-cap{padding:16px}.hb-lb-x{top:8px;right:8px}}
/* the featured modpack (Hub.featured_mod): full-bleed picture, soft vignette, the words on a glass panel; eases on scroll */
body.hb{overflow-x:clip}
.hb-coa{position:relative;width:100vw;margin:34px 0 16px calc(50% - 50vw);min-height:clamp(440px,50vw,620px);display:flex;align-items:center;
overflow:hidden;isolation:isolate;background:#0b0d12;scroll-margin-top:72px}
.hb-coa-pic{position:absolute;inset:0;z-index:-1;overflow:hidden}
.hb-coa-pic img{display:block;width:100%;height:100%;object-fit:cover;object-position:62% 42%;
transform:scale(calc(1.1 - var(--coa,.5) * .06)) translateY(calc((var(--coa,.5) - .5) * -36px))}
.hb-coa-pic::after{content:"";position:absolute;inset:0;pointer-events:none;background:
radial-gradient(130% 95% at 68% 45%,transparent 42%,rgba(8,10,15,.72) 100%),
linear-gradient(90deg,rgba(12,14,20,.9) 0%,rgba(12,14,20,.55) 34%,rgba(12,14,20,0) 62%),
linear-gradient(0deg,var(--lk-bg) 0%,transparent 20%),linear-gradient(180deg,var(--lk-bg) 0%,transparent 16%)}
.hb-coa-in{position:relative;width:100%;max-width:1040px;margin:0 auto;padding:56px 16px}
.hb-coa-t{max-width:450px;padding:26px 28px 22px;border-radius:var(--lk-r);background:rgba(16,19,27,.6);-webkit-backdrop-filter:blur(12px) saturate(1.15);
backdrop-filter:blur(12px) saturate(1.15);border:1px solid rgba(255,255,255,.09);box-shadow:0 24px 70px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.06)}
.hb-coa-k{display:flex;align-items:center;gap:9px;margin:0 0 8px;color:#e6bb5f;font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}
.hb-coa-k span{width:24px;height:2px;border-radius:2px;background:linear-gradient(90deg,#d9a441,rgba(217,164,65,0))}
.hb-coa h2{margin:0 0 10px;font-size:clamp(26px,3.5vw,38px);line-height:1.1;font-weight:800;letter-spacing:-.015em}
.hb-coa-l{margin:0 0 18px;color:var(--lk-text-2);font-size:15.5px}
.hb-coa-a{margin:0 0 14px}.hb-coa-a .hb-cta{display:inline-flex;align-items:center;gap:9px}
.hb-coa-a svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.hb-coa-n{margin:0;padding-top:12px;border-top:1px solid rgba(255,255,255,.08);color:var(--lk-muted);font-size:12.5px;line-height:1.45}
.hb-coa-cr{position:absolute;right:16px;bottom:16px;margin:0;font-size:11.5px;color:rgba(255,255,255,.72);text-shadow:0 1px 3px #000}
@media (max-width:720px){.hb-coa{display:block;min-height:0;margin-top:26px}.hb-coa-pic{position:relative;aspect-ratio:845/577}
.hb-coa-pic::after{background:radial-gradient(120% 90% at 50% 40%,transparent 50%,rgba(8,10,15,.6) 100%),linear-gradient(0deg,var(--lk-bg) 0%,transparent 35%)}
.hb-coa-in{margin-top:-64px;padding:0 16px 8px}.hb-coa-t{max-width:none;padding:20px 18px 16px}.hb-coa-cr{position:static;margin:8px 2px 0;text-align:right;color:var(--lk-muted);text-shadow:none}}
/* the fantasy panels (server software, the realm list): carved slate, a rune rule, torch gold used sparingly, our crest */
.hb-sw,.hb-rlx{position:relative;padding:20px;border-radius:var(--lk-r);color:var(--lk-text);background:
radial-gradient(120% 80% at 0% 0%,rgba(91,141,239,.11),transparent 55%),radial-gradient(100% 70% at 100% 100%,rgba(139,108,240,.11),transparent 60%),
repeating-linear-gradient(135deg,rgba(255,255,255,.014) 0 2px,transparent 2px 7px),linear-gradient(180deg,#1d212a,#14171e);
border:1px solid #373c48;box-shadow:inset 0 0 0 1px rgba(217,164,65,.13),inset 0 1px 0 rgba(255,255,255,.05),0 18px 50px rgba(0,0,0,.45),0 0 60px rgba(91,141,239,.08)}
.hb-sw p,.hb-rlx p{margin:0}
.hb-crest{flex:none;display:block}.hb-crest .r1{fill:#12141b;stroke:rgba(217,164,65,.75);stroke-width:1.3}
.hb-crest .r2{fill:none;stroke:rgba(122,163,245,.4);stroke-width:1}.hb-crest .st circle{fill:#d9a441}
.hb-rune{display:flex;align-items:center;gap:8px;margin:14px 0}.hb-rune::before,.hb-rune::after{content:"";flex:1;height:1px}
.hb-rune::before{background:linear-gradient(90deg,transparent,rgba(217,164,65,.45))}.hb-rune::after{background:linear-gradient(90deg,rgba(217,164,65,.45),transparent)}
.hb-rune svg{flex:none}.hb-rune .dm{fill:none;stroke:#d9a441;stroke-width:1.3}.hb-rune .dm.s{stroke:rgba(139,108,240,.9)}.hb-rune .dt{fill:rgba(122,163,245,.85)}
.hb-sw-top,.hb-rlx-top{display:flex;align-items:center;gap:12px}
.hb-sw-k{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#d9a441}
.hb-sw-t{font-size:19px;font-weight:800;letter-spacing:-.01em}
.hb-sw-run{margin-left:auto!important;display:flex;align-items:center;gap:7px;padding:3px 10px;border-radius:999px;border:1px solid rgba(79,209,139,.5);
color:var(--lk-ok);font-size:12px;font-weight:700;white-space:nowrap}
.hb-sw-run span{width:7px;height:7px;border-radius:50%;background:var(--lk-ok);box-shadow:0 0 0 3px rgba(79,209,139,.18)}
.hb-sw-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:0;padding:0;list-style:none}
.hb-sw-c{position:relative;padding:12px 13px;border-radius:10px;border:1px solid #30353f;
background:linear-gradient(180deg,rgba(255,255,255,.04),rgba(255,255,255,0) 60%),#181b23;box-shadow:inset 0 1px 0 rgba(255,255,255,.04),inset 0 -2px 0 rgba(0,0,0,.25)}
.hb-sw-c::before{content:"";position:absolute;left:12px;right:12px;top:-1px;height:1px;background:linear-gradient(90deg,transparent,rgba(217,164,65,.5),transparent)}
.hb-sw-c.soon{background:#16181f}.hb-sw-c.soon::before{background:linear-gradient(90deg,transparent,rgba(139,108,240,.4),transparent)}
.hb-sw-c.soon :is(b,.hb-sw-l,dd){opacity:.8}
.hb-sw-c.own{grid-column:1/-1;border-style:dashed;border-color:#3d4352;background:rgba(24,27,35,.6)}.hb-sw-c.own::before{display:none}
.hb-sw-h{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px!important}.hb-sw-h b{font-size:15px}
.hb-sw-chip{flex:none;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;white-space:nowrap;border:1px solid var(--lk-border-strong);color:var(--lk-text-2)}
.hb-sw-chip.go{color:#f1cf86;border-color:rgba(217,164,65,.55);background:rgba(217,164,65,.1)}.hb-sw-chip.soon{color:var(--lk-muted)}
.hb-sw-l{margin-bottom:8px!important;color:var(--lk-text-2);font-size:12.5px;line-height:1.45}
.hb-sw-eras{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px!important}
.hb-sw-eras span{font-size:11px;font-weight:600;padding:1px 7px;border-radius:6px;background:var(--lk-accent-soft);color:var(--lk-accent-strong)}
.hb-sw dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 10px;margin:0;font-size:12px}.hb-sw dt{color:var(--lk-muted)}.hb-sw dd{margin:0;color:var(--lk-text-2)}
.hb-sw-svc{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:0;padding:0;list-style:none}
.hb-sw-svc li{position:relative;display:grid;padding:6px 8px 6px 22px;border-radius:8px;background:rgba(0,0,0,.24);border:1px solid #2a2e39;font-size:12px;font-weight:600}
.hb-sw-svc i{position:absolute;left:9px;top:12px;width:7px;height:7px;border-radius:50%;background:var(--lk-ok);box-shadow:0 0 0 3px rgba(79,209,139,.16)}
.hb-sw-svc span{color:var(--lk-muted);font-weight:500;font-size:11px}
.hb-rlx-h{font-size:19px;font-weight:800;letter-spacing:.02em}
.hb-rlx-cols,.hb-rlx-r{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(0,.8fr) minmax(0,.8fr) minmax(0,1fr);align-items:center;gap:8px}
.hb-rlx-cols{padding:0 12px 6px;color:#d9a441;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
.hb-rlx-l{display:grid;gap:4px;margin:0;padding:0;list-style:none}
.hb-rlx-r{padding:9px 12px;border-radius:8px;border:1px solid transparent;text-decoration:none;color:var(--lk-text)!important;font-size:14px;
background:rgba(0,0,0,.16);transition:background .15s,border-color .15s}
.hb-rlx-r:hover,.hb-rlx-r:focus-visible{background:rgba(122,163,245,.09);border-color:rgba(122,163,245,.3)}
.hb-rlx-r.sel{background:linear-gradient(90deg,rgba(217,164,65,.17),rgba(217,164,65,.04));border-color:rgba(217,164,65,.5);box-shadow:inset 3px 0 0 #d9a441}
.hb-rlx-r.off{opacity:.62}.hb-rlx-r.you{opacity:.6;border:1px dashed #3d4352;background:transparent}.hb-rlx-r.you:hover{opacity:1}
.hb-rlx-n{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb-rlx-t,.hb-rlx-ch,.hb-rlx-p{font-size:13px;color:var(--lk-text-2)}
.hb-rlx-t.pvp{color:#ff8a80}.hb-rlx-t.rp{color:#5fd896}.hb-rlx-t.rppvp{color:#f2a654}
.hb-rlx-p{font-weight:700}.hb-rlx-p.low{color:#5fd896}.hb-rlx-p.med{color:#e9c45c}.hb-rlx-p.high{color:#f2a654}.hb-rlx-p.full{color:#ff8a80}
.hb-rlx-p.rec{color:#8fb2ff}.hb-rlx-p.off{color:var(--lk-muted);font-weight:500}
.hb-rlx-f{display:flex;justify-content:space-between;gap:10px;margin-top:12px!important;font-size:13px}
@media (max-width:560px){.hb-sw,.hb-rlx{padding:16px}.hb-sw-list{grid-template-columns:minmax(0,1fr)}.hb-sw-svc{grid-template-columns:repeat(2,minmax(0,1fr))}
.hb-sw-run{display:none!important}.hb-rlx-cols{display:none}
.hb-rlx-r{grid-template-columns:minmax(0,1fr) auto;gap:2px 10px}.hb-rlx-n{grid-column:1}.hb-rlx-p{grid-column:2;grid-row:1;text-align:right}
.hb-rlx-t{grid-column:1;grid-row:2;font-size:12px}.hb-rlx-ch{display:none}}
/* the Minigolf loop in Game modes: poster first, played on screen by HUB_JS */
.hb-vid{position:relative}.hb-vid video{display:block;width:100%;height:auto;background:#0b0d12}
.hb-vid figcaption{position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:26px 14px 12px;
background:linear-gradient(0deg,rgba(6,8,12,.78),transparent);color:#fff;font-size:13.5px;font-weight:600}
.hb-vid-play{padding:5px 14px;border-radius:999px;background:var(--lk-accent);color:#fff!important;text-decoration:none;font-weight:700}
.hb-mode.art{overflow:hidden}.hb-mode-art{display:block;width:calc(100% + 32px);max-width:none;height:auto;aspect-ratio:483/298;object-fit:cover;
margin:-16px -16px 6px;border-bottom:1px solid var(--lk-border)}
/* reduced motion: nothing moves (the ticker stands still and wraps, the key stays put, the thread is drawn, no tilt) */
@media (prefers-reduced-motion:reduce){.hb *{transition:none!important;animation:none!important}
:is(a.hb-stat,.hb-spot,.hb-box,.hb-mode,.hb-cr,.hb-nw):hover{transform:none}
.hb-top{border-bottom-color:var(--lk-border)}
.hb-tick{-webkit-mask-image:none;mask-image:none}.hb-tick-run{width:auto}.hb-tick-l{flex-wrap:wrap;justify-content:center;min-width:0;width:100%}
.hb-tick-l li{padding:6px 14px}.hb-tick-l.dup{display:none}
.hb-shot{transform:none!important}.hb-thread path{stroke-dasharray:none!important}
.hb-coa-pic img{transform:scale(1.03)!important}.hb-rlx-r{transition:none}
.hb-gt :is(img,.hb-gt-art),.hb-lb-in{transform:none!important}.hb-gt-c{transform:none}.hb-lb{-webkit-backdrop-filter:none;backdrop-filter:none}}
"""

# The hub's only script (front page and realm list; every other hub page has none). Plain and small: it adds
# Copy buttons to the realm addresses, the realm filter without a reload, the live player counts from the public
# /wrath/realms.json and /wrath/status.json every 30 s (the page's own numbers stay when they don't answer), and
# the section reveal. Everything works without it: the addresses are selectable text, the filter is a GET form.
HUB_JS = r"""(function(){
"use strict";
var d=document,root=d.documentElement;root.classList.add("hb-js");
var still=!!(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches);
if(!still&&"IntersectionObserver" in window){
  var io=new IntersectionObserver(function(es){es.forEach(function(x){if(x.isIntersecting){x.target.classList.add("in");io.unobserve(x.target);}});},{rootMargin:"0px 0px -6% 0px"});
  d.querySelectorAll(".hb-rv").forEach(function(s){if(s.getBoundingClientRect().top>innerHeight){s.classList.add("hb-wait");io.observe(s);}});
}
// the header: a hairline once scrolled (browsers without scroll timelines), More closes on Escape or a click outside
var top=d.querySelector(".hb-top");
if(top&&!(window.CSS&&CSS.supports&&CSS.supports("animation-timeline: scroll()"))){
  var edge=function(){top.classList.toggle("hb-scrolled",scrollY>8);};edge();addEventListener("scroll",edge,{passive:true});}
d.addEventListener("click",function(ev){d.querySelectorAll("details.hb-more-d[open]").forEach(function(x){if(!x.contains(ev.target))x.open=false;});});
d.addEventListener("keydown",function(ev){if(ev.key!=="Escape")return;d.querySelectorAll("details.hb-more-d[open]").forEach(function(x){
  x.open=false;var s=x.querySelector("summary");if(s)s.focus();});});
// the numbers count up once when they come into view (the page already has the final numbers)
if(!still&&"IntersectionObserver" in window){
  var cio=new IntersectionObserver(function(es){es.forEach(function(x){if(!x.isIntersecting)return;cio.unobserve(x.target);
    var el=x.target,to=+el.getAttribute("data-count"),t0=0;
    function step(t){if(!t0)t0=t;var k=Math.min(1,(t-t0)/1200);el.textContent=String(Math.round(to*(1-Math.pow(1-k,3))));if(k<1)requestAnimationFrame(step);}
    requestAnimationFrame(step);});},{threshold:.4});
  d.querySelectorAll(".hb-num[data-count]").forEach(function(n){if(n.getBoundingClientRect().top>innerHeight){n.textContent="0";cio.observe(n);}});
}
// the ley line draws itself down the feature sections as you scroll
var th=d.querySelector(".hb-thread"),feats=d.querySelector(".hb-feats");
if(th&&feats&&!still){th.classList.add("draw");var pend=0;
  var draw=function(){pend=0;var r=feats.getBoundingClientRect(),k=(innerHeight*.75-r.top)/Math.max(1,r.height);
    th.style.setProperty("--hb-draw",String(1-Math.max(0,Math.min(1,k))));};
  draw();addEventListener("scroll",function(){if(!pend){pend=1;requestAnimationFrame(draw);}},{passive:true});addEventListener("resize",draw);}
// the featured modpack's picture eases as it scrolls by (a slow zoom and drift); still with reduced motion
var coa=d.querySelector(".hb-coa");
if(coa&&!still){var cpend=0;var par=function(){cpend=0;var r=coa.getBoundingClientRect(),k=(innerHeight-r.top)/(innerHeight+r.height);
    coa.style.setProperty("--coa",Math.max(0,Math.min(1,k)).toFixed(3));};
  par();addEventListener("scroll",function(){if(!cpend){cpend=1;requestAnimationFrame(par);}},{passive:true});addEventListener("resize",par);}
// the Minigolf loop plays only while it is on screen; never with reduced motion or Save-Data (the poster stays)
var vids=d.querySelectorAll("video[data-hb-vid]"),save=!!(navigator.connection&&navigator.connection.saveData);
if(vids.length&&!still&&!save&&"IntersectionObserver" in window){
  var vio=new IntersectionObserver(function(es){es.forEach(function(x){var v=x.target;
    if(x.isIntersecting){var pr=v.play();if(pr&&pr.catch)pr.catch(function(){});}else if(!v.paused)v.pause();});},{threshold:.35});
  vids.forEach(function(v){vio.observe(v);});}
// the screenshots lean toward the cursor, with a soft glow (fine pointers only)
if(!still&&window.matchMedia&&matchMedia("(pointer:fine)").matches){d.querySelectorAll(".hb-shot").forEach(function(f){
  f.addEventListener("pointermove",function(ev){var r=f.getBoundingClientRect(),x=(ev.clientX-r.left)/r.width,y=(ev.clientY-r.top)/r.height;
    f.classList.add("tilt");f.style.setProperty("--ry",((x-.5)*6).toFixed(2)+"deg");f.style.setProperty("--rx",((.5-y)*5).toFixed(2)+"deg");
    f.style.setProperty("--gx",(x*100).toFixed(1)+"%");f.style.setProperty("--gy",(y*100).toFixed(1)+"%");});
  f.addEventListener("pointerleave",function(){f.classList.remove("tilt");f.style.setProperty("--rx","0deg");f.style.setProperty("--ry","0deg");});});}
// the gallery: the chips filter in place (without script they are links to the gallery page, ?f=), and a tile opens the
// lightbox: Esc or the backdrop closes it, the arrows move, Tab stays inside, focus goes back to the tile
var lb=null,lbl=[],cur=-1,parts={};
function mk(tag,cls,txt){var x=d.createElement(tag);if(cls)x.className=cls;if(txt!=null)x.textContent=txt;return x;}
function btn(cls,label,path){var b=mk("button",cls);b.type="button";b.setAttribute("aria-label",label);
  var s=d.createElementNS("http://www.w3.org/2000/svg","svg");s.setAttribute("viewBox","0 0 24 24");s.setAttribute("aria-hidden","true");
  var p=d.createElementNS("http://www.w3.org/2000/svg","path");p.setAttribute("d",path);s.appendChild(p);b.appendChild(s);return b;}
function clear(x){while(x.firstChild)x.removeChild(x.firstChild);}
function lbBuild(){lb=mk("div","hb-lb");lb.hidden=true;lb.setAttribute("role","dialog");lb.setAttribute("aria-modal","true");
  lb.setAttribute("aria-labelledby","hb-lb-t");
  var box=mk("div","hb-lb-in"),cap=mk("div","hb-lb-cap");parts.pic=mk("div","hb-lb-pic");
  parts.k=mk("small");parts.t=mk("h2");parts.t.id="hb-lb-t";parts.l=mk("p");parts.c=mk("p","hb-lb-cr");parts.a=mk("p","hb-lb-a");
  parts.n=mk("p","hb-lb-n");parts.n.setAttribute("aria-live","polite");
  parts.x=btn("hb-lb-x","Close","M6 6l12 12M18 6L6 18");parts.p=btn("hb-lb-p","Previous picture","M15 5l-7 7 7 7");
  parts.nx=btn("hb-lb-nx","Next picture","M9 5l7 7-7 7");
  [parts.k,parts.t,parts.l,parts.c,parts.a,parts.n].forEach(function(x){cap.appendChild(x);});
  parts.pic.appendChild(parts.p);parts.pic.appendChild(parts.nx);
  box.appendChild(parts.pic);box.appendChild(cap);box.appendChild(parts.x);lb.appendChild(box);d.body.appendChild(lb);
  parts.x.addEventListener("click",lbClose);parts.p.addEventListener("click",function(){lbShow(cur-1);});
  parts.nx.addEventListener("click",function(){lbShow(cur+1);});
  lb.addEventListener("click",function(ev){if(ev.target===lb)lbClose();});
  lb.addEventListener("keydown",function(ev){
    if(ev.key==="Escape"){ev.preventDefault();ev.stopPropagation();lbClose();}
    else if(ev.key==="ArrowLeft"){ev.preventDefault();lbShow(cur-1);}
    else if(ev.key==="ArrowRight"){ev.preventDefault();lbShow(cur+1);}
    else if(ev.key==="Tab"){var f=[].slice.call(lb.querySelectorAll("a[href],button")).filter(function(x){return !x.hidden&&x.offsetParent!==null;});
      if(!f.length)return;var i=f.indexOf(d.activeElement);
      if(ev.shiftKey&&i<=0){ev.preventDefault();f[f.length-1].focus();}else if(!ev.shiftKey&&i===f.length-1){ev.preventDefault();f[0].focus();}}});}
function txt(t,sel){var x=t.querySelector(sel);return x?x.textContent:"";}
function lbShow(i){var n=lbl.length;if(!n)return;cur=(i+n)%n;var t=lbl[cur];
  [].slice.call(parts.pic.childNodes).forEach(function(x){if(x!==parts.p&&x!==parts.nx)parts.pic.removeChild(x);});
  var im=t.querySelector(".hb-gt-a img"),art=t.querySelector(".hb-gt-a .hb-gt-art"),pic;
  if(im){pic=mk("img");pic.src=im.getAttribute("src");pic.alt=im.alt;pic.width=+im.getAttribute("width");pic.height=+im.getAttribute("height");pic.decoding="async";}
  else if(art){pic=art.cloneNode(true);}
  if(pic)parts.pic.insertBefore(pic,parts.p);
  parts.k.textContent=txt(t,".hb-gt-c small");parts.t.textContent=txt(t,".hb-gt-c b");parts.l.textContent=txt(t,".hb-gt-l");
  parts.c.textContent=txt(t,".hb-gt-c i");clear(parts.a);
  t.querySelectorAll(".hb-gt-x a").forEach(function(a){var c=a.cloneNode(true);c.className=a.className==="hb-gt-i"?"hb-cta sm":"hb-ghost";parts.a.appendChild(c);});
  parts.n.textContent=(cur+1)+" of "+n;parts.p.hidden=parts.nx.hidden=n<2;}
function lbOpen(t){if(!lb)lbBuild();var g=t.parentNode;
  lbl=[].slice.call(g.querySelectorAll(".hb-gt")).filter(function(x){return !x.hidden;});
  lbShow(Math.max(0,lbl.indexOf(t)));lb.hidden=false;root.classList.add("hb-lb-on");void lb.offsetWidth;lb.classList.add("open");parts.x.focus();}
function lbClose(){if(!lb||lb.hidden)return;lb.classList.remove("open");lb.hidden=true;root.classList.remove("hb-lb-on");
  var t=lbl[cur],a=t&&t.querySelector(".hb-gt-a");if(a)a.focus();}
d.querySelectorAll("[data-gal]").forEach(function(g){
  g.querySelectorAll(".hb-gt-a[data-lb]").forEach(function(a){a.addEventListener("click",function(ev){
    if(ev.button!==0||ev.metaKey||ev.ctrlKey||ev.shiftKey||ev.altKey)return;ev.preventDefault();lbOpen(a.parentNode);});});
  var box=g.closest("section")||g.parentNode,chips=box.querySelectorAll(".hb-gal-f a[data-f]"),none=g.querySelector(".hb-gal-none");
  if(g.getAttribute("data-gal")!=="all")return;
  chips.forEach(function(c){c.addEventListener("click",function(ev){if(ev.button!==0||ev.metaKey||ev.ctrlKey||ev.shiftKey)return;ev.preventDefault();
    var f=c.getAttribute("data-f"),n=0;
    g.querySelectorAll(".hb-gt").forEach(function(t){var ok=!f||t.getAttribute("data-k")===f;t.hidden=!ok;if(ok)n++;});
    g.classList.toggle("flt",!!f);if(none)none.hidden=n>0;
    chips.forEach(function(x){var on=x===c;x.classList.toggle("on",on);if(on)x.setAttribute("aria-current","true");else x.removeAttribute("aria-current");});
    if(/\/gallery$/.test(location.pathname)&&history.replaceState)history.replaceState(null,"",c.getAttribute("href"));});});});
if(navigator.clipboard){d.querySelectorAll("code.hb-addr").forEach(function(c){
  var b=d.createElement("button");b.type="button";b.className="hb-copy";b.textContent="Copy";
  b.setAttribute("aria-label","Copy the address "+c.textContent);
  b.addEventListener("click",function(){navigator.clipboard.writeText(c.textContent).then(function(){
    b.textContent="Copied";setTimeout(function(){b.textContent="Copy";},1600);},function(){});});
  c.after(b);});}
d.querySelectorAll("form[data-rf]").forEach(function(f){
  var list=d.getElementById(f.getAttribute("data-rf"));if(!list)return;
  var none=list.parentNode.querySelector(".hb-rl-none"),go=f.querySelector("button");if(go)go.hidden=true;
  function run(){var b=f.elements.client?f.elements.client.value:"",n=f.elements.now&&f.elements.now.checked,shown=0;
    list.querySelectorAll(".hb-rl").forEach(function(li){
      var ok=(!b||li.getAttribute("data-client")===b)&&(!n||(li.getAttribute("data-live")==="1"&&+li.getAttribute("data-players")>0));
      li.hidden=!ok;if(ok)shown++;});
    list.classList.toggle("cap",!b&&!n);if(none)none.hidden=shown>0;}
  f.addEventListener("change",run);f.addEventListener("submit",function(e){e.preventDefault();run();});});
var rows=d.querySelectorAll(".hb-rl[data-rid],.hb-rl[data-home],[data-tick]");if(!rows.length||!window.fetch)return;
function tk(key,p){if(typeof p!=="number"||p<0)return;d.querySelectorAll('[data-tick="'+key+'"] .hb-tn').forEach(function(b){b.textContent=String(p);});}
function set(li,on,p,bots){var el=li.querySelector(".hb-n");if(!el||li.getAttribute("data-live")!=="1")return;
  if(on===false){el.parentNode.classList.add("off");el.parentNode.textContent="Offline";li.setAttribute("data-live","0");return;}
  if(typeof p!=="number"||p<0)return;
  if(String(p)!==el.textContent){el.textContent=String(p);li.setAttribute("data-players",String(p));
    if(!still){el.classList.remove("bump");void el.offsetWidth;el.classList.add("bump");}}
  var s=li.querySelector(".hb-bots");if(s&&typeof bots==="number")s.textContent=bots?bots+" bots":"";}
function line(t){return t.realms+" realm"+(t.realms===1?"":"s")+" · "+t.players+" player"+(t.players===1?"":"s")+" online"+(t.bots?" · "+t.bots+" bots":"");}
function json(u){return fetch(u,{cache:"no-store",credentials:"omit"}).then(function(r){return r.ok?r.json():null;}).catch(function(){return null;});}
function tick(){if(d.hidden)return;
  json("/wrath/realms.json").then(function(j){if(!j||!Array.isArray(j.realms))return;
    j.realms.forEach(function(r){var c=r.community||{},h=c.lastHeartbeat||{};
      if(!/^[a-z2-7]{16}$/.test(c.realmId||""))return;
      var li=d.querySelector('.hb-rl[data-rid="'+c.realmId+'"]');if(li)set(li,h.online,h.players,h.bots);
      if(h.online!==false)tk(c.realmId,h.players);});
    var nl=d.querySelector("[data-net]");if(nl&&j.network&&typeof j.network.players==="number")nl.textContent=line(j.network);});
  var home=d.querySelector(".hb-rl[data-home]");
  if(home||d.querySelector('[data-tick="home"]'))json("/wrath/status.json").then(function(s){if(!s)return;
    if(home)set(home,s.online===true?true:s.online===false?false:undefined,s.players,s.bots);if(s.online!==false)tk("home",s.players);});}
setInterval(tick,30000);d.addEventListener("visibilitychange",function(){if(!d.hidden)tick();});
})();"""

# The launcher's deep link for a realm (launcher/src-tauri/src/deeplink.rs: realm/<realm id or official>). It shows
# the realm on the launcher's Realms page with PLAY focused; nothing starts until the player clicks PLAY.
REALM_DEEPLINK = "leyline://realm/{id}"
BROWSER_BUILD = 12340   # the browser game is a 3.3.5a client: only 3.3.5a realms get "Play in browser"
# How a realm is played, in words (never its build): the browser game's build plays in the browser, the rest need the
# player's own client. The realm list filters by these (?client=browser|own).
CLIENT_FILTER = (("browser", "Plays in browser"), ("own", "Own client"))
COMPAT = {"browser": "Plays in your browser", "own": "Bring your own game client"}
TAG_WORDS = {"blizzlike": "Original rules"}   # the network's tag labels the hub words differently


def client_of(r: dict) -> str:
    return "browser" if r.get("build", 12340) == BROWSER_BUILD else "own"
FRONT_REALMS = 60       # rows sent on the front page (8 show until a filter is used; the rest are on the realm list)

# Icons for the products (24x24 strokes, the launcher's nav style).
ICONS = {
    "launcher": '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8M12 18v3M9 9l3 3 3-3M12 6v6"/>',
    "host": '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    "realms": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "modes": '<path d="M6 9h12a3 3 0 0 1 3 3v2a3 3 0 0 1-5.2 2L14 14h-4l-1.8 2A3 3 0 0 1 3 14v-2a3 3 0 0 1 3-3z"/><path d="M8 11v2M7 12h2M16 11.5h.01M17.5 13h.01"/>',
    "mods": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "community": '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3.5 2.7-6 6-6s6 2.5 6 6M15 14.5c3 0 6 2 6 5"/>',
    "agents": '<rect x="5" y="7" width="14" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9.5 16h5M2 12v3M22 12v3"/>',
}


# The header's line icons (the launcher's sidebar style: 24x24 strokes, currentColor).
NAV_ICONS = {
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l6-3.5z"/>',
    "realms": ICONS["realms"], "mods": ICONS["mods"], "modes": ICONS["modes"], "host": ICONS["host"],
    "community": ICONS["community"],
    "addons": '<path d="M9 4h4v2.5a1.5 1.5 0 0 0 3 0V4h4v6h-2.5a1.5 1.5 0 0 0 0 3H20v7H4v-7h2.5a1.5 1.5 0 0 0 0-3H4V4z"/>',
    "more": '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
    "docs": '<path d="M5 4h9l5 5v11H5z"/><path d="M14 4v5h5M8 13h8M8 17h6"/>',
    "news": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h6M7 12h10M7 15h10"/>',
    "creators": '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 7l3 3"/>',
    "status": '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "key": '<circle cx="8" cy="12" r="4"/><path d="M12 12h9M18 12v3M21 12v2"/>',
    "gallery": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
}
# The gallery (Hub.gallery_tiles). Our in-game screenshots (stream/www-files/art, checked by eye: no logo, no game name;
# behind the game data killswitch): name -> (width, height, title, line, alt). Words only; no client numbers, no game name.
GAME_SHOTS = {
    "dalaran": (690, 390, "The hangout", "The meeting place on our flagship realm, streamed into a browser tab.",
                "In-game screenshot: a robed hero on a cobbled path through a violet city, under a stone archway."),
    "durotar": (865, 475, "Red desert, first steps", "New characters by a campfire in the desert, a few minutes after signing in.",
                "In-game screenshot: two new characters by a campfire on red desert ground."),
    "start": (745, 420, "A quiet start", "Begin at level 1 beside the chapel, or take a boost with gear, professions and a trip to the city.",
              "In-game screenshot: two characters on green grass in front of a stone chapel."),
    "city": (770, 430, "A city at night", "Group up, duel and run dungeons; labelled bots fill the empty places.",
             "In-game screenshot: a character in a stone city at night, towers and trees against the stars."),
}
# The launcher's own pages (tools/art/leyline-ui-shots.cjs: sample data, no game art): name -> (title, line, alt).
LAUNCHER_SHOTS = {
    "home": ("The launcher", "The server, your account, your game client and one PLAY button.",
             "The Leyline launcher's home page: the server, your account, your game client and the PLAY button."),
    "workshop": ("Mods in one click", "Workshop mods sorted by Hot, with ratings, installs and Install.",
                 "The launcher's Discover page: Workshop mods sorted by Hot, with ratings, installs and Install."),
    "realms": ("Every realm, one list", "Players online, uptime and badges for every realm on the network.",
               "The launcher's Realms page: every realm on the network with its players, uptime and badges."),
    "modes": ("Game modes", "Minigames and modes, with one PLAY button each.",
              "The launcher's Modes page: minigames and game modes with one PLAY button each."),
}
KIND_WORDS = {"addon": ("Addon", "an addon", "addons"), "mod": ("Mod", "a mod", "mods"), "mode": ("Game mode", "a game mode", "modes"),
              "theme": ("Theme", "a theme", "creators")}
GALLERY_FILTERS = (("", "All"), ("game", "In game"), ("mods", "Mods"), ("launcher", "Launcher"))

# The front page's featured mod (owner 2026-10-30: "under this show a screenshot ... the CoA ultra hd modpack feature"): a
# community graphics modpack, linked out only (never hosted or checked by us). Its screenshot is the authors' (banner
# cropped, a player name removed), a game picture: behind the game data killswitch like the other leyline-shot- files.
# The link is only an href; the words on the page never name the game.
FEATURED_MOD = {
    "key": "coa-ultrahd", "w": 845, "h": 577, "label": "Featured mod", "title": "Conquest of Azeroth: UltraHD",
    # TODO(owner): the final wording for the featured modpack
    "line": "A community graphics modpack for the classic client: higher-resolution textures, richer lighting and "
            "denser foliage, from the same game folder you already play with.",
    "short": "Higher-resolution textures, lighting and foliage for the classic client.",
    "alt": "Screenshot from the Conquest of Azeroth UltraHD modpack: characters on a flowered lawn in front of a stone "
           "chapel, under tall trees in warm light.",
    "note": "External download, made and hosted by its authors; not checked or hosted by Leyline",
    "credit": "Screenshot: the modpack's authors",
    "url": "https://www.reddit.com/r/wowservers/comments/1xiqhdg/conquest_of_azeroth_ultrahd_graphics_modpack/",
    "button": "See the modpack",
}
FEATURED_REL = "noopener nofollow ugc"

# The server cores the host pack can run (owner 2026-10-30: "we should have server software in this area"), in the
# words of hosting/kit/tools/wuhost/cores.py and docs/HOST-ANY-CLIENT.md: "live" only for what the kit hosts today
# (AzerothCore: the kit's own profiles; CMaNGOS: cmangos-1.12.1 and cmangos-2.4.3), the rest "coming". Eras are words,
# never client numbers. The hosting tests check this against cores.py (stream/tests/test_hub.py).
# (id, name, status, eras, line, scripting, bots)
HOST_CORES = (
    ("azerothcore", "AzerothCore", "live", ("Third era",),
     "The kit's default and the core our own realms run on: modules, events and the Dungeon Finder.",
     "C++ modules and Lua scripts", "Player bots built in"),
    ("cmangos", "CMaNGOS", "live", ("Classic era", "Second era"),
     "A long-running core with its whole world database kept in the open; one recipe for both eras.",
     "C++ scripts (ScriptDev2)", "No bots in the kit's build"),
    ("trinitycore", "TrinityCore", "coming", ("Fourth era",),
     "A preservation fork is already in the kit, ready to be switched on for the next era.",
     "C++ scripts", "No bots"),
    ("vmangos", "vMaNGOS", "coming", ("Classic era",),
     "The strongest classic core for content and progression; a profile is a small follow-up.",
     "C++ scripts", "No bots"),
)
HOST_OWN = ("Your own", "Already run a server? Put it on the Leyline list with the relay agent and keep your own core.")
# The realm console strip under the cores (what the host pack's Check shows).
HOST_SERVICES = (("Database", "ready"), ("Login server", "ready"), ("World server", "ready"), ("Relay agent", "listed"))

# The realm list picture in "Realms & hopping" (owner 2026-10-30: "the actual looking realm list thing but ... our featured
# server names"): our own panel built from the live rows. Population in words from players online; the type from tags.
REALM_LIST_MAX = 6
POP_WORDS = ((0, "Offline", "off"), (20, "Low", "low"), (80, "Medium", "med"), (200, "High", "high"), (10 ** 9, "Full", "full"))
# The modes' key art (the owner's, for the mode's authors): mode id -> (art file, width, height, alt). Missing: no picture.
MODE_ART = {
    "azeroth-survivors": ("leyline-mode-azeroth-survivors.webp", 483, 298,
                          "Azeroth Survivors key art: the title over a band of heroes and a moonlit castle."),
}


def realm_type(tags) -> tuple[str, str]:
    """(word, colour class) for a realm's rules from its tags: RP-PvP, PvP, RP, else Normal."""
    t = set(tags or [])
    if "pvp" in t and "rp" in t:
        return "RP-PvP", "rppvp"
    if "pvp" in t:
        return "PvP", "pvp"
    if "rp" in t:
        return "RP", "rp"
    return "Normal", "pve"


def population(live: bool, players) -> tuple[str, str]:
    """(word, colour class) from players online: Offline when it is down, else Low / Medium / High / Full."""
    if not live:
        return "Offline", "off"
    n = players if isinstance(players, int) and players > 0 else 0
    for top, word, cls in POP_WORDS[1:]:
        if n < top:
            return word, cls
    return "Full", "full"
# The header item each hub page highlights (the catalog: Addons when filtered to them, else Mods; an item page: Mods).
ACTIVE = {BASE + "/realms": "realms", BASE + "/catalog": "mods", BASE + "/submit": "mods", BASE + "/modes": "modes",
          BASE + "/beacon": "host", BASE + "/news": "news", BASE + "/creators": "creators", BASE + "/gallery": "gallery",
          FRONT + "/gallery": "gallery"}
HEALTH_WORDS = {"ok": "All systems OK", "warn": "Some systems are down", "bad": "Systems offline"}
# Who is signed in, for the header's account chip: set per request in get()/post() (the portal's threads).
_REQ = threading.local()


def _viewer(handler):
    """(acct, display) from the site's session cookie via the portal's social module, None when signed out or unknown.
    Only asks when the request carries the session cookie."""
    try:
        if "wr_session=" not in (handler.headers.get("Cookie", "") or ""):
            return None
        soc = hub.portal("social")
        return soc.cookie_user(handler) if soc is not None and hasattr(soc, "cookie_user") else None
    except Exception:   # noqa: BLE001: the sign-in being down never breaks a page
        return None


def _slug(cid: str) -> str:
    return cid.replace(":", "-", 1)


def _https(v) -> str:
    if not isinstance(v, str) or len(v) > 400 or not v.startswith("https://") or CTRL_RE.search(v) or re.search(r"\s", v):
        return ""
    return v


# ------------------------------------------------------------------------------------------- the portal's hooks
hub = Hub()
MAX_FORM = 4096


def bind(lookup) -> None:
    """The portal passes a lookup of its globals (ly_shell, workshop, PUBLIC_HOST, HOST_URL)."""
    def get(name):
        try:
            return lookup(name)
        except Exception:   # noqa: BLE001
            return None
    hub.portal = get


def match(path: str) -> bool:
    if not hub_on():
        return False
    return (path == BASE or path.startswith(BASE + "/") or path == FEED
            or (path in (FRONT, FRONT + "/gallery") and front_on()))


def _robots(public: bool = False) -> dict:
    return {} if (public or front_on()) else {"X-Robots-Tag": "noindex, nofollow"}


def get(handler, path: str, query: dict) -> None:
    """GET (and HEAD) for every path match() owns. handler: the portal's request handler (send, ip)."""
    _REQ.who = None
    limit = hub.portal("browse_limit")
    if limit is not None and not limit.hit(handler.ip(), 600):
        handler.send(429, b"too many requests\n", "text/plain")
        return
    if path == FEED:
        handler.send(200, hub.feed(), "application/json; charset=utf-8", headers={"Access-Control-Allow-Origin": "*"})
        return
    if path == BASE + "/approved.json":
        body = (json.dumps(hub.store.approved_doc(), indent=1, sort_keys=True) + "\n").encode()
        handler.send(200, body, "application/json; charset=utf-8", headers=_robots())
        return
    if path != FEED and path != BASE + "/approved.json":
        _REQ.who = _viewer(handler)
    if path in (BASE, FRONT):
        nonce = secrets.token_urlsafe(16)
        handler.send(200, hub.front_page(path, nonce), nonce=nonce, connect=True, headers=_robots())
        return
    if path in (BASE + "/gallery", FRONT + "/gallery"):
        nonce = secrets.token_urlsafe(16)
        handler.send(200, hub.gallery_page(query, path, nonce), nonce=nonce, headers=_robots())
        return
    if path == BASE + "/catalog":
        handler.send(200, hub.catalog_page(query), headers=_robots())
        return
    if path == BASE + "/creators":
        handler.send(200, hub.creators_page(), headers=_robots())
        return
    if path == BASE + "/realms":
        nonce = secrets.token_urlsafe(16)
        handler.send(200, hub.realms_page(query, nonce), nonce=nonce, connect=True, headers=_robots())
        return
    if path == BASE + "/modes":
        handler.send(200, hub.modes_page(), headers=_robots())
        return
    if path == BASE + "/news":
        handler.send(200, hub.news_page(), headers=_robots())
        return
    if path == BASE + "/beacon":
        handler.send(200, hub.beacon_page(), headers=_robots())
        return
    if path == BASE + "/submit":
        done = (query.get("done") or [""])[0] == "1"
        handler.send(200, hub.submit_page(done=done), headers=_robots())
        return
    if path.startswith(BASE + "/p/"):
        status, body = hub.item_page(path[len(BASE + "/p/"):], handler, query)
        handler.send(status, body, headers=_robots())
        return
    handler.send(404, hub._shell("Not found · Leyline", '<section class="ly-panel"><h2>Not found</h2>'
                                 f'<p><a href="{BASE}">The hub</a></p></section>', BASE), headers=_robots())


def post(handler, path: str) -> None:
    _REQ.who = None
    if path != BASE + "/submit":
        handler.send(405, b"method not allowed\n", "text/plain")
        return
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = -1
    if length < 0 or length > MAX_FORM:
        handler.send(413, b"too large\n", "text/plain")
        return
    raw = handler.rfile.read(length).decode("utf-8", "replace")
    form = {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items() if v}
    ok, msg = hub.submit(form, handler.ip())
    if ok:
        handler.send_response(303)
        handler.send_header("Location", BASE + "/submit?done=1")
        handler.send_header("Content-Length", "0")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        return
    handler.send(400, hub.submit_page(msg, form), headers=_robots())
