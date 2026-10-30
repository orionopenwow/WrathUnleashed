"""The Leyline hub (hidden preview): one catalog of the Workshop, the community index and theme packs.

Built for the 2026-10-26 brief ("hide the full leyline front page thing but build it out for now") and the
2026-10-29 one (an auto-populated index of open mods for every client build the launcher supports, and a way
for people to submit their mods). Served by stream/wrath_portal.py, which loads this file from beside itself
and runs without it.

    GET  /wrath/leyline-preview               the front page: the hero, every realm on the network (one-click Play in
                                              browser, the desktop address), how it works, one feature section per
                                              part of Leyline (launcher, hosting, realms, modes, mods, community,
                                              agents), Platform Status, Community Spotlight, categories, creators,
                                              Host a Beacon. No client build number or game name on any hub page
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
    GET  /wrath/leyline-preview/submit        the "Submit a mod" form;  POST it to queue a submission
    GET  /wrath/leyline-preview/approved.json the approved submissions and delisted repos (the index pipeline reads
                                              it: tools/hub-index/hub_index.py); repo URLs only, no notes
    GET  /wrath/leyline/catalog.json          the merged catalog for the Leyline launcher, in the all.json shape
                                              (mods/all-json.md) with the extra fields in docs/HUB-INDEX.md (CORS *)

Hidden: every preview page carries <meta name="robots" content="noindex"> and an X-Robots-Tag header, and no
other page links here. The front page and the realm list carry one small script (HUB_JS, under a CSP nonce):
Copy buttons, the realm filter without a reload, live player counts and the section reveal; without it they work
the same, only still. Every other hub page has no script. The one switch: WU_HUB_FRONT=1 serves the front page at /wrath/leyline too (the front
door) and drops the noindex. Off by default. WU_HUB=0 turns the whole thing off (404s).

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
              "description", "stars", "updated", "archived", "needs", "source", "score", "release"}
RELEASE_KEYS = {"tag", "date", "url"}


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
    ids = [e.get("id") for e in doc["entries"] if isinstance(e, dict)]
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
        self.lock = threading.Lock()

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

    def get_item(self, slug: str) -> dict | None:
        m = re.fullmatch(r"(link|mod|theme)-([a-z0-9][a-z0-9-]{1,40})", slug or "")
        if not m:
            return None
        want = f"{m.group(1)}:{m.group(2)}"
        return next((i for i in self.items() if i["id"] == want), None)

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
        return f'{self._spin(44, "slow hb-mark")}<span class="hb-word"><b>Leyline</b><i>Launcher</i></span>'

    def _shell(self, title: str, body: str, path: str, nonce: str = "") -> bytes:
        """The page around body. nonce: the CSP nonce for HUB_JS (the front page and the realm list); "" for no script."""
        e = html.escape
        front = path in (BASE, FRONT)
        home = FRONT if front_on() else BASE
        dl = self._download()
        here = "" if front else home
        nav = [("Features", f"{here}#features", False), ("Download", dl, True), ("Community", f"{here}#community", False),
               ("Status", f"{here}#status", False), ("Docs", "/wrath/docs", False)]
        links = "".join(f'<a href="{e(h)}"' + (' rel="noopener noreferrer"' if ext else "") + f">{e(t)}</a>" for t, h, ext in nav)
        top = (f'<header class="hb-top"><a class="hb-brand" href="{home}" aria-label="Leyline Launcher">{self._wordmark()}</a>'
               '<input type="checkbox" id="hb-menu" class="hb-menu-t"><label for="hb-menu" class="hb-menu-b">Menu</label>'
               f'<nav class="hb-nav" aria-label="Leyline">{links}</nav>'
               '<a class="hb-signin" href="/login?next=%2Fwrath"><img src="/wrath/art/leyline-crystal-128.png" alt="" width="26" height="26">'
               'Sign In</a></header>')
        sub = "" if front else (f'<nav class="hb-sub" aria-label="Hub">'
               + "".join(f'<a href="{BASE}{h}"' + (' aria-current="page" class="on"' if path == BASE + h else "") + f">{t}</a>"
                         for h, t in (("", "Hub"), ("/realms", "Realms"), ("/modes", "Modes"), ("/catalog", "Catalog"),
                                      ("/news", "News"), ("/creators", "Creators"), ("/beacon", "Host a Beacon"),
                                      ("/submit", "Submit a mod")))
               + "</nav>")
        flag = '<p class="hb-flag">Preview: this page is hidden while it is being built.</p>' if not front_on() else ""
        repo = self.portal("LEYLINE_REPO") or "https://github.com/orionopenwow/Leyline"
        discord = self.portal("DISCORD_URL") or ""
        foot_links = [("Docs", "/wrath/docs"), ("Download", dl), ("Community", f"{home}#community"), ("Status", f"{home}#status"),
                      ("Catalog", f"{BASE}/catalog"), ("Creators", f"{BASE}/creators"), ("Submit a mod", f"{BASE}/submit")]
        social = ([("Discord", discord)] if discord else []) + [("GitHub", repo)]
        foot = ('<footer class="hb-foot"><div class="hb-foot-in">'
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
        cards = []

        def card(name, line, ok, href="", tail=""):
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
            ws = i.get("ws") or {}
            if i["source"] == "workshop" and isinstance(ws.get("screenshots"), list) and ws["screenshots"] and str(i["id"]).startswith("mod:"):
                shot = f'<img src="/wrath/mods/{e(i["id"][4:])}/shot/0" alt="" loading="lazy" width="160" height="100">'
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
        return (f'<li class="hb-rl{" home" if r.get("home") else ""}"{data} data-client="{client}" data-live="{1 if live else 0}" '
                f'data-players="{players or 0}"><div class="hb-rl-n"><b>{e(name)}</b>{"".join(bdg)}'
                f'<span class="hb-rl-m">{e(" · ".join(meta))}</span></div>{count}'
                f'<div class="hb-rl-a">{"".join(acts)}</div></li>')

    def realm_section(self) -> str:
        """The sub hero: every server on the network, the home realm first, one click to play. "" without a list."""
        got = self.realm_rows()
        if got is None:
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

    def features(self) -> str:
        """The feature sections, one per part of Leyline, in the recommended order (after the original site's big
        alternating showcases: #server-software, #desktop-launcher, #forge, #agents): words on one side, a picture on
        the other, the sides flipping each time, stacked on a phone. Pictures are launcher screenshots (tools/art/
        leyline-ui-shots.cjs: the launcher's own pages with sample data, no client numbers) or small CSS drawings."""
        e = html.escape
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
        host_art = ('<div class="hb-draw hb-console" aria-hidden="true"><p class="hb-dt"><b>Your realm</b><em>Running</em></p>'
                    + "".join(f'<p class="hb-svc"><i></i>{x}<span>{y}</span></p>' for x, y in (
                        ("Database", "ready"), ("Login server", "ready"), ("World server", "ready"), ("Relay agent", "listed")))
                    + '<p class="hb-cores">' + "".join(f"<span>{x}</span>" for x in ("AzerothCore", "TrinityCore", "CMaNGOS",
                                                                                         "vMaNGOS", "Your own"))
                    + '</p><p class="hb-dbtn"><span>Start</span><span>Invite link</span></p></div>')
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
             [(BASE + "/realms", "See the realms", False)],
             shot("realms", "The launcher's Realms page: every realm on the network with its players, uptime and badges.")),
            ("modes", "Game modes", "Minigames and modes, one click",
             modes_line + ". PLAY signs you in and starts the game once your character is in the world.",
             ["Made by players, checked by a GM", "Host a mode as a whole realm type", "The same list in the launcher"],
             [(BASE + "/modes", "Play a mode", False)],
             shot("modes", "The launcher's Modes page: minigames and game modes with one PLAY button each.")),
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
        return ('<div class="hb-feats" id="features"><h2 class="hb-vh">Everything in Leyline</h2>'
                + "".join(out) + "</div>")

    def front_page(self, path: str = BASE, nonce: str = "") -> bytes:
        e = html.escape
        items = self.items()
        by_cat = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORY_IDS + ["themes"]}
        cats = "".join(
            f'<a class="hb-chip" href="{BASE}/catalog?cat={c}">{e(n)} <small>{by_cat[c]}</small></a>' for c, n in CATEGORIES + [THEMES])
        body = (
            '<section class="hb-hero" id="top" aria-labelledby="hb-h">'
            f'<div class="hb-art" aria-hidden="true">{self._spin(208, "slow hb-hero-mark")}</div>'
            '<!-- TODO(owner): the hero heading and the line under it; his final wording -->'
            '<h1 id="hb-h">Every client, every server</h1>'
            '<p class="hb-sub-h">One launcher for every classic client and every server: your game, your realm, one click.</p>'
            f'<p class="hb-hero-a"><a class="hb-cta" href="{e(self._download())}" rel="noopener noreferrer">Download Now</a>'
            '<a class="hb-ghost lg" href="/wrath">Play in your browser</a></p>'
            '<p class="hb-note">Free and open source, for Windows, macOS and Linux. Nothing to buy.</p></section>'
            + self.realm_section() + self.how_strip() + self.features()
            + f'<div class="hb-rv">{self.status_cards()}</div><div class="hb-rv">{self.spotlight()}</div>' +
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
            cards.append(f'<article class="hb-mode" id="mode-{e(m["id"])}"><h2>{e(neutral(m["title"]))}</h2><p>{e(neutral(m["line"]))}</p>'
                         f'<p>{"".join(f"<span class=hb-tag>{e(x)}</span>" for x in tags if x)}</p>{credit}{act}</article>')
        body = ('<section class="hb-head"><h1>Modes</h1><p>Minigames and game modes. Play signs you in and starts the game '
                'in your browser once your character is in the world. The launcher lists the same games on its Modes page.</p></section>'
                + (f'<div class="hb-modes">{"".join(cards)}</div>' if cards else
                   '<p class="hb-empty">No modes are listed right now. <a href="/wrath/modes">The modes page</a></p>')
                + '<p class="hb-fine">Duels, boss fights, dungeons and hangouts are on <a href="/wrath/modes">the full modes page</a>.</p>')
        return self._shell("Modes · Leyline", body, BASE + "/modes")

    def news_page(self) -> bytes:
        """The launcher's News page on the web: the posts the admin console publishes (/wrath/leyline/news.json)."""
        e = html.escape
        adm = self.portal("admin")
        try:
            posts = adm.news_doc()["posts"] if adm is not None else []
        except Exception:   # noqa: BLE001
            posts = []
        out = []
        for p in posts[:30]:
            raw = [clean_line(x, 200) for x in (p.get("items") if isinstance(p.get("items"), list) else [])[:12]]
            title, tag, date = clean_line(p.get("title"), 120), clean_line(p.get("tag"), 60), clean_line(p.get("date"), 10)
            if not title or banned(" ".join([title, tag] + raw)):
                continue
            title, tag, items = neutral(title, 120), neutral(tag, 60), [neutral(x, 200) for x in raw]
            if not title:
                continue
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
        return (f'<article class="hb-card"><h3><a href="{BASE}/p/{_slug(i["id"])}">{e(neutral(i["name"]) or "Untitled")}</a></h3>'
                f'<p class="hb-by">by {e(neutral(i["author"]) or "unknown")} · <span class="hb-src hb-{i["source"]}">{badge}</span></p>'
                f'<p>{e(neutral(i.get("description") or i["summary"]))}</p><p class="hb-meta">{builds}'
                f'<span class="hb-lic">{e(neutral(i.get("licence")) or "licence not stated")}{stars}</span></p>{rank}</article>')

    def catalog_page(self, query: dict) -> bytes:
        e = html.escape
        q1 = lambda k: (query.get(k) or [""])[0][:80]   # noqa: E731
        build, cat, source, text, sort = offered_tag(q1("build")), q1("cat"), q1("source"), clean_line(q1("q"), 60), q1("sort") or "score"
        cat = cat if cat in CATEGORY_IDS + ["themes"] else ""
        source = source if source in ("workshop", "index", "theme") else ""
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
        if build:
            items = [i for i in items if build in i["builds"] or "any" in i["builds"]]
        if cat:
            items = [i for i in items if i["category"] == cat]
        if source:
            items = [i for i in items if i["source"] == source]
        if kind:
            items = [i for i in items if rk.kind_of(i) == kind]
        if text:
            words = text.lower().split()
            items = [i for i in items if all(w in (i["name"] + " " + i["summary"] + " " + i.get("description", "")
                                                   + " " + i["author"]).lower() for w in words)]
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
        f_src = chips("source", [("", "Everything"), ("workshop", "Workshop"), ("index", "Community"), ("theme", "Themes")], source)
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
            '<p class="hb-empty">Nothing here yet. '
            + (f'<a href="{BASE}/submit">Submit a mod</a> to fill it.' if cat != "themes" else "Theme packs are on the way.") + "</p>")
        body = (f'<header class="hb-head"><h1>Catalog</h1><p>{total} items'
                + (f' for the {e(CLIENT_LABEL[build].lower())}' if build and build != "any" else "") + '</p></header>'
                f'<form class="hb-search" method="get" action="{BASE}/catalog" role="search">{hidden}'
                f'<label for="hb-q">Search</label><input id="hb-q" name="q" value="{e(text)}" maxlength="60">'
                '<button type="submit">Search</button></form>'
                f'<div class="hb-filters"><p>{f_build}</p><p>{f_cat}</p><p>{f_src}</p>{f_kind}'
                f'<p role="tablist" aria-label="Sort">{f_sort}</p></div>'
                f'<div class="hb-grid">{grid}</div>{nav}' + (f"<style>{rk.RANK_CSS}</style>" if rk else ""))
        return self._shell("Catalog · Leyline", body, BASE + "/catalog")

    def item_page(self, slug: str, handler=None, query: dict | None = None) -> tuple[int, bytes]:
        e = html.escape
        i = self.get_item(slug)
        if i is None:
            return 404, self._shell("Not found · Leyline", '<section class="ly-panel"><h2>Not in the catalog</h2>'
                                    f'<p><a href="{BASE}/catalog">See everything</a></p></section>', BASE)
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
        body = (f'<article class="ly-panel hb-item"><h1>{e(name)}</h1><p class="hb-sum">{e(summary)}</p>{desc}'
                f'<table class="ly-table">{table}</table><p class="hb-actions">{" ".join(acts)}</p>'
                f'<p class="hb-fine">{e(how)}</p></article>{panel}')
        return 200, self._shell(f"{name} · Leyline", body, BASE + "/p/" + slug)

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
/* the header */
.hb-top{position:sticky;top:0;z-index:20;display:flex;align-items:center;flex-wrap:wrap;gap:8px 18px;padding:10px 24px;
background:rgba(24,27,35,.94);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);border-bottom:1px solid var(--lk-border)}
.hb-brand{display:inline-flex;align-items:center;gap:11px;text-decoration:none;color:var(--lk-text)!important}
.hb-mark{border-radius:50%;background:radial-gradient(circle at 50% 45%,rgba(91,141,239,.18),rgba(139,108,240,.06) 70%);box-shadow:0 0 0 1px var(--lk-border-strong)}
.hb-mark::before,.hb-mark::after{inset:3px}
.hb-word{display:grid;line-height:1.05}.hb-word b{font-size:20px;font-weight:700;letter-spacing:-.01em}
.hb-word i{font-style:normal;font-weight:600;font-size:15px;color:var(--lk-accent)}
.hb-nav{display:flex;gap:4px;margin-left:auto}
.hb-nav a{padding:8px 12px;border-radius:var(--lk-r-sm);color:var(--lk-text-2);text-decoration:none;font-weight:600;font-size:14px}
.hb-nav a:hover{background:var(--lk-accent-soft);color:var(--lk-text)}
.hb-signin{display:inline-flex;align-items:center;gap:4px;padding:5px 16px 5px 8px;border-radius:var(--lk-r-sm);border:1px solid var(--lk-border-strong);
background:var(--lk-surface);color:var(--lk-text)!important;text-decoration:none;font-weight:600;font-size:14px}
.hb-signin:hover{border-color:var(--lk-accent)}
.hb-menu-t{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
.hb-menu-b{display:none;cursor:pointer;padding:7px 12px;border:1px solid var(--lk-border-strong);border-radius:var(--lk-r-sm);font-weight:600;font-size:14px}
.hb-menu-t:focus-visible+.hb-menu-b{outline:2px solid var(--lk-accent-strong)}
@media (max-width:820px){.hb-top{padding:10px 16px}.hb-menu-b{display:inline-block;margin-left:auto;order:2}.hb-signin{order:1;margin-left:auto}
.hb-signin+*{margin-left:0}.hb-nav{display:none;order:3;flex:1 0 100%;flex-direction:column;margin:0}
.hb-menu-t:checked~.hb-nav{display:flex}.hb-word b{font-size:18px}.hb-word i{font-size:13px}}
.hb-main{flex:1;width:100%;max-width:1040px;margin:0 auto;padding:20px 16px 40px}
.hb-flag{margin:0 0 12px;text-align:center;font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--lk-accent-2)}
.hb-sub{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin:0 0 18px}
.hb-sub a{padding:7px 12px;border:1px solid var(--lk-border);border-radius:999px;text-decoration:none;color:var(--lk-muted);font-weight:600;font-size:13px}
.hb-sub a.on,.hb-sub a:hover{color:var(--lk-text);border-color:var(--lk-accent);background:var(--lk-accent-soft)}
/* the hero: the whole Leyline mark, crisp and centred; the swirl turns slowly (SPIN_CSS .slow), a soft glow behind it */
.hb-hero{position:relative;text-align:center;padding:30px 16px 40px;margin:0 -16px;overflow:hidden;isolation:isolate}
.hb-signin img{transform:scale(1.7)}
.hb-art{position:relative;display:grid;place-items:center;margin:0 auto 18px;width:280px;max-width:100%;height:240px}
.hb-art::before{content:"";position:absolute;inset:0;z-index:-1;border-radius:50%;
background:radial-gradient(closest-side,rgba(91,141,239,.30),rgba(139,108,240,.13) 55%,transparent 100%)}
.hb-hero-mark{--ly-spin-turn:40s!important}
.hb-hero-mark::before{background-image:url(/wrath/art/leyline-swirl-256.webp);
background-image:image-set(url(/wrath/art/leyline-swirl-256.webp) 1x,url(/wrath/art/leyline-swirl-512.png) 2x)}
.hb-hero-mark::after{background-image:url(/wrath/art/leyline-crystal-256.webp);
background-image:image-set(url(/wrath/art/leyline-crystal-256.webp) 1x,url(/wrath/art/leyline-crystal-512.png) 2x);
filter:drop-shadow(0 0 10px rgba(91,141,239,.55))}
.hb-hero h1{margin:0 0 12px;font-size:clamp(30px,5.4vw,50px);line-height:1.05;font-weight:800;letter-spacing:-.01em;text-transform:uppercase}
.hb-sub-h{max-width:560px;margin:0 auto 24px;color:var(--lk-text-2);font-size:clamp(16px,2.2vw,19px);line-height:1.5}
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
@media (max-width:420px){.hb-pic{width:84px;height:72px}.hb-art{width:220px;height:184px;margin-bottom:12px}
.hb-hero-mark{--ly-spin-size:160px!important}}
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
@media (prefers-reduced-motion:reduce){.hb *{transition:none!important;animation:none!important}
:is(a.hb-stat,.hb-spot,.hb-box,.hb-mode):hover{transform:none}}
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
var rows=d.querySelectorAll(".hb-rl[data-rid],.hb-rl[data-home]");if(!rows.length||!window.fetch)return;
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
      var li=d.querySelector('.hb-rl[data-rid="'+c.realmId+'"]');if(li)set(li,h.online,h.players,h.bots);});
    var nl=d.querySelector("[data-net]");if(nl&&j.network&&typeof j.network.players==="number")nl.textContent=line(j.network);});
  var home=d.querySelector(".hb-rl[data-home]");
  if(home)json("/wrath/status.json").then(function(s){if(s)set(home,s.online===true?true:s.online===false?false:undefined,s.players,s.bots);});}
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
    return path == BASE or path.startswith(BASE + "/") or path == FEED or (path == FRONT and front_on())


def _robots(public: bool = False) -> dict:
    return {} if (public or front_on()) else {"X-Robots-Tag": "noindex, nofollow"}


def get(handler, path: str, query: dict) -> None:
    """GET (and HEAD) for every path match() owns. handler: the portal's request handler (send, ip)."""
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
    if path in (BASE, FRONT):
        nonce = secrets.token_urlsafe(16)
        handler.send(200, hub.front_page(path, nonce), nonce=nonce, connect=True, headers=_robots())
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
