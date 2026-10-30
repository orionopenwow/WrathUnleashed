"""The Leyline hub (hidden preview): one catalog of the Workshop, the community index and theme packs.

Built for the 2026-10-26 brief ("hide the full leyline front page thing but build it out for now") and the
2026-10-29 one (an auto-populated index of open mods for every client build the launcher supports, and a way
for people to submit their mods). Served by stream/wrath_portal.py, which loads this file from beside itself
and runs without it.

    GET  /wrath/leyline-preview               the front page: builds, categories, picks, creators, Host a Beacon
    GET  /wrath/leyline-preview/catalog       everything, filtered by plain links and a GET form (no script):
                                              ?build=1.12|2.4.3|3.3.5a|4.3.4|5.4.8 &cat=<category>|themes
                                              &source=workshop|index|theme &q=<text> &sort=score|name|updated &page=N
    GET  /wrath/leyline-preview/p/<id>        one item (id: link-<12 hex>, mod-<mod id>, theme-<id>)
    GET  /wrath/leyline-preview/creators      for creators: the docs, how the index works, how to submit
    GET  /wrath/leyline-preview/beacon        Host a Beacon (your own realm on the Leyline list)
    GET  /wrath/leyline-preview/realms        the Leyline network's realms (stream/network.py: community realms first,
                                              the sample hangout pinned, filters ?build= &tag= &region= &lang= &now=1)
    GET  /wrath/leyline-preview/submit        the "Submit a mod" form;  POST it to queue a submission
    GET  /wrath/leyline-preview/approved.json the approved submissions and delisted repos (the index pipeline reads
                                              it: tools/hub-index/hub_index.py); repo URLs only, no notes
    GET  /wrath/leyline/catalog.json          the merged catalog for the Leyline launcher, in the all.json shape
                                              (mods/all-json.md) with the extra fields in docs/HUB-INDEX.md (CORS *)

Hidden: every preview page carries <meta name="robots" content="noindex"> and an X-Robots-Tag header, and no
other page links here. The one switch: WU_HUB_FRONT=1 serves the front page at /wrath/leyline too (the front
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


ENTRY_KEYS = {"id", "name", "author", "owner", "repo", "forge", "licence", "category", "type", "builds", "summary",
              "description", "stars", "updated", "archived", "needs", "source", "score"}


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
        return out

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
               "builds": BUILDS + ["any"], "projects": projects}
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
    def _shell(self, title: str, body: str, path: str) -> bytes:
        shell = self.portal("ly_shell")
        sub = (f'<nav class="hb-sub" aria-label="Hub">'
               + "".join(f'<a href="{BASE}{h}"' + (' aria-current="page" class="on"' if path == BASE + h else "") + f">{t}</a>"
                         for h, t in (("", "Hub"), ("/catalog", "Catalog"), ("/creators", "Creators"),
                                      ("/realms", "Realms"), ("/beacon", "Host a Beacon"), ("/submit", "Submit a mod")))
               + "</nav>")
        body = (f'<p class="hb-flag">Preview: this page is hidden while it is being built.</p>' if not front_on() else "") + sub + body
        if shell is None:
            return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
                    f'<meta name="robots" content="noindex"><style>{HUB_CSS}</style></head><body class="ly">'
                    f'<main id="main">{body}</main></body></html>').encode("utf-8")
        meta = '<meta name="description" content="Leyline: mods, addons, realm scripts and tools for the game\'s classic clients.">'
        return shell(title, body, path, "leyline", next_step="", css=HUB_CSS, meta=meta, noindex=not front_on())

    def front_page(self, path: str = BASE) -> bytes:
        e = html.escape
        items = self.items()
        by_build = {b: sum(1 for i in items if b in i["builds"]) for b in BUILDS}
        by_cat = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORY_IDS + ["themes"]}
        n_index = sum(1 for i in items if i["source"] == "index")
        n_ws = sum(1 for i in items if i["source"] == "workshop")
        builds = "".join(
            f'<a class="hb-build" href="{BASE}/catalog?build={b}"><b>{e(BUILD_LABEL[b])}</b>'
            f'<span>{e(BUILD_ERA[b])}</span><small>{by_build[b]} items</small></a>' for b in BUILDS)
        cats = "".join(
            f'<a class="hb-cat" href="{BASE}/catalog?cat={c}"><b>{e(n)}</b><small>{by_cat[c]}</small></a>'
            for c, n in CATEGORIES + [THEMES])
        picks = []
        for b in BUILDS:
            best = sorted((i for i in items if b in i["builds"] and i["source"] != "theme"),
                          key=lambda i: (-float(i.get("score") or 0), i["name"].lower()))[:2]
            picks += [i for i in best if i not in picks]
        body = (
            '<header class="ly-hero hb-hero"><h1>Leyline</h1>'
            '<!-- TODO(owner): the hub tagline -->'
            '<p class="ly-lede">Mods, addons, realm scripts and tools for the game\'s classic clients, in one place: '
            'our Workshop and a credited index of open community work.</p>'
            f'<p class="hb-actions"><a class="ly-btn" href="{BASE}/catalog">Browse the catalog</a> '
            f'<a class="ly-btn hb-alt" href="{BASE}/submit">Submit a mod</a></p>'
            f'<p class="hb-count">{len(items)} items · {n_ws} in the Workshop · {n_index} open community projects</p></header>'
            f'<section class="ly-panel" aria-labelledby="hb-b"><h2 id="hb-b">Pick your client</h2>'
            f'<div class="hb-builds">{builds}</div></section>'
            f'<section class="ly-panel" aria-labelledby="hb-c"><h2 id="hb-c">Categories</h2><div class="hb-cats">{cats}</div></section>'
            f'<section class="ly-panel" aria-labelledby="hb-p"><h2 id="hb-p">Worth a look</h2>'
            f'<div class="hb-grid">{"".join(self.card(i) for i in picks[:10])}</div></section>'
            + self.realms_panel() +
            '<section class="hb-two">'
            f'<div class="ly-panel"><h2>For creators</h2><p>Make an addon, a realm script or a whole mode. '
            f'The docs, the package format and how the index works.</p><p><a href="{BASE}/creators">Start here</a></p></div>'
            f'<div class="ly-panel"><h2>Host a Beacon</h2><p>Run your own realm and put it on the Leyline list, '
            f'so players can hop over from the launcher.</p><p><a href="{BASE}/beacon">How it works</a></p></div></section>'
            '<p class="hb-fine">Community projects are links: nothing of theirs is hosted here. Each belongs to its '
            'authors, under the licence they chose. Nothing to buy.</p>')
        return self._shell("Leyline", body, path)

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

    def realms_panel(self) -> str:
        """The front page's "Realms on the network": the network line, the first realms in the network's order."""
        got = self._network()
        if got is None:
            return ""
        net, realms, ok, st = got
        e = html.escape
        t, top = net.summary(realms, st, 5)
        lis = []
        for r in top:
            sm = (self.portal("sample_info") or (lambda: {}))() or {}
            name = ((sm.get("name") or net.SAMPLE_NAME) + (" · temporary" if sm.get("temporary", True) else "")
                    if r.get("sample") else r["name"])
            who = f'{r["players"]} playing' if r.get("players") is not None else "online"
            lis.append(f'<li><b>{e(name)}</b> · {e(who)}{" · " + net.uptime_badge(r) if not r.get("sample") else ""}'
                       f'{" · Featured" if r.get("featured") else ""}</li>')
        body = ('<ul class="hb-list">' + "".join(lis) + '</ul>') if lis else (
            '<p>No community realms are open right now.</p>' if ok else '<p>The realm list isn\'t reachable right now.</p>')
        return (f'<section class="ly-panel" aria-labelledby="hb-r"><h2 id="hb-r">Realms on the network</h2>'
                f'<p class="hb-count">{e(net.network_line(t))}</p>{body}'
                f'<p><a href="{BASE}/realms">All realms</a> · <a href="{BASE}/beacon">Host your own</a></p></section>')

    def realms_page(self, query: dict) -> bytes:
        got = self._network()
        if got is None:
            body = '<section class="ly-panel"><h2>Realms</h2><p><a href="/wrath/realms">The realm list</a></p></section>'
            return self._shell("Realms · Leyline", body, BASE + "/realms")
        net, realms, ok, st = got
        ln = self.portal("leyline_net")
        try:
            pack = ln.hostpack() if ln is not None else None
        except Exception:   # noqa: BLE001
            pack = None
        css = (self.portal("REALM_CSS") or "") + net.NET_CSS
        body = (f'<style>{css}</style><section class="ly-panel"><h1>Realms</h1>'
                '<p>The Leyline network is realms hosted by players. The order is players online, uptime and staff '
                'picks: nothing can be bought.</p></section>'
                + net.page_body(realms, ok, query, st, self.portal("JOIN_BASE") or "https://relay.openvanilla.app",
                                self.portal("RULESET_LABELS") or {}, None, pack["download"] if pack else None,
                                base=BASE + "/realms", sample=si() if (si := self.portal("sample_info")) else None))
        return self._shell("Realms · Leyline", body, BASE + "/realms")

    def card(self, i: dict) -> str:
        e = html.escape
        badge = {"workshop": "Workshop", "index": "Community", "theme": "Theme"}[i["source"]]
        builds = " ".join(f'<span class="hb-tag">{e(BUILD_LABEL.get(b, b))}</span>' for b in i["builds"])
        stars = f' · ★ {int(i["stars"])}' if isinstance(i.get("stars"), int) and not isinstance(i.get("stars"), bool) else ""
        return (f'<article class="hb-card"><h3><a href="{BASE}/p/{_slug(i["id"])}">{e(i["name"])}</a></h3>'
                f'<p class="hb-by">by {e(i["author"] or "unknown")} · <span class="hb-src hb-{i["source"]}">{badge}</span></p>'
                f'<p>{e(i.get("description") or i["summary"])}</p><p class="hb-meta">{builds}'
                f'<span class="hb-lic">{e(i.get("licence") or "licence not stated")}{stars}</span></p></article>')

    def catalog_page(self, query: dict) -> bytes:
        e = html.escape
        q1 = lambda k: (query.get(k) or [""])[0][:80]   # noqa: E731
        build, cat, source, text, sort = build_tag(q1("build")), q1("cat"), q1("source"), clean_line(q1("q"), 60), q1("sort") or "score"
        cat = cat if cat in CATEGORY_IDS + ["themes"] else ""
        source = source if source in ("workshop", "index", "theme") else ""
        sort = sort if sort in ("score", "name", "updated") else "score"
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
        if text:
            words = text.lower().split()
            items = [i for i in items if all(w in (i["name"] + " " + i["summary"] + " " + i.get("description", "")
                                                   + " " + i["author"]).lower() for w in words)]
        if sort == "name":
            items.sort(key=lambda i: (i["name"].lower(), i["id"]))
        elif sort == "updated":
            items.sort(key=lambda i: (i.get("updated") or "", i["name"].lower()), reverse=True)
        else:
            items.sort(key=lambda i: (-float(i.get("score") or 0), i["name"].lower(), i["id"]))
        total = len(items)
        pages = max(1, math.ceil(total / self.PER_PAGE))
        page = min(page, pages)
        shown = items[(page - 1) * self.PER_PAGE: page * self.PER_PAGE]

        def link(**over):
            cur = {"build": build, "cat": cat, "source": source, "q": text, "sort": sort if sort != "score" else ""}
            cur.update(over)
            qs = urllib.parse.urlencode({k: v for k, v in cur.items() if v})
            return f"{BASE}/catalog" + (f"?{qs}" if qs else "")

        def chips(key, opts, cur):
            return "".join(f'<a class="hb-chip{" on" if v == cur else ""}" href="{e(link(**{key: v, "page": ""}))}"'
                           + (' aria-current="true"' if v == cur else "") + f">{e(label)}</a>" for v, label in opts)
        f_build = chips("build", [("", "All builds")] + [(b, BUILD_LABEL[b]) for b in BUILDS], build)
        f_cat = chips("cat", [("", "All")] + CATEGORIES + [THEMES], cat)
        f_src = chips("source", [("", "Everything"), ("workshop", "Workshop"), ("index", "Community"), ("theme", "Themes")], source)
        f_sort = chips("sort", [("", "Best"), ("name", "A to Z"), ("updated", "Recently updated")], sort if sort != "score" else "")
        hidden = "".join(f'<input type="hidden" name="{k}" value="{e(v)}">' for k, v in
                         (("build", build), ("cat", cat), ("source", source)) if v)
        nav = ""
        if pages > 1:
            nav = ('<nav class="hb-pages" aria-label="Pages">'
                   + (f'<a href="{e(link(page=str(page - 1)))}">Previous</a>' if page > 1 else "")
                   + f"<span>Page {page} of {pages}</span>"
                   + (f'<a href="{e(link(page=str(page + 1)))}">Next</a>' if page < pages else "") + "</nav>")
        grid = "".join(self.card(i) for i in shown) or (
            '<p class="hb-empty">Nothing here yet. '
            + (f'<a href="{BASE}/submit">Submit a mod</a> to fill it.' if cat != "themes" else "Theme packs are on the way.") + "</p>")
        body = (f'<header class="hb-head"><h1>Catalog</h1><p>{total} items'
                + (f' for {e(BUILD_LABEL[build])}' if build else "") + '</p></header>'
                f'<form class="hb-search" method="get" action="{BASE}/catalog" role="search">{hidden}'
                f'<label for="hb-q">Search</label><input id="hb-q" name="q" value="{e(text)}" maxlength="60">'
                '<button type="submit">Search</button></form>'
                f'<div class="hb-filters"><p>{f_build}</p><p>{f_cat}</p><p>{f_src}</p><p>{f_sort}</p></div>'
                f'<div class="hb-grid">{grid}</div>{nav}')
        return self._shell("Catalog · Leyline", body, BASE + "/catalog")

    def item_page(self, slug: str) -> tuple[int, bytes]:
        e = html.escape
        i = self.get_item(slug)
        if i is None:
            return 404, self._shell("Not found · Leyline", '<section class="ly-panel"><h2>Not in the catalog</h2>'
                                    f'<p><a href="{BASE}/catalog">See everything</a></p></section>', BASE)
        rows = [("Builds", ", ".join(BUILD_LABEL.get(b, b) for b in i["builds"])),
                ("Category", dict(CATEGORIES + [THEMES]).get(i["category"], i["category"])),
                ("Author", i["author"] or "unknown"), ("Licence", i.get("licence") or "not stated")]
        if isinstance(i.get("stars"), int) and not isinstance(i.get("stars"), bool):
            rows.append(("Stars", str(i["stars"])))
        if i.get("updated"):
            rows.append(("Last change", i["updated"][:10]))
        if i.get("needs"):
            rows.append(("Needs", i["needs"]))
        if i.get("archived"):
            rows.append(("Status", "Archived by its authors (read-only)"))
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
        desc = f'<p class="hb-repo">From the repo: {e(i["description"])}</p>' if i.get("description") else ""
        body = (f'<article class="ly-panel hb-item"><h1>{e(i["name"])}</h1><p class="hb-sum">{e(i["summary"])}</p>{desc}'
                f'<table class="ly-table">{table}</table><p class="hb-actions">{" ".join(acts)}</p>'
                f'<p class="hb-fine">{e(how)}</p></article>')
        return 200, self._shell(f"{i['name']} · Leyline", body, BASE + "/p/" + slug)

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
                '<p>Once a week a script searches the forges for open projects for each client build (1.12.1, 2.4.3, '
                '3.3.5a, 4.3.4, 5.4.8), reads each repo\'s licence, files and addon TOC, and proposes an update that a '
                'person reviews before it goes live. The short description is written from the repo\'s own one-line '
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
                    'it against the rules, and the weekly index update picks it up once it is approved.</p>'
                    f'<p><a href="{BASE}/catalog">Back to the catalog</a></p></section>')
            return self._shell("Submitted · Leyline", body, BASE + "/submit")
        opt = lambda v, label, cur: f'<option value="{e(v)}"{" selected" if v == cur else ""}>{e(label)}</option>'  # noqa: E731
        builds = "".join(opt(b, BUILD_LABEL[b], form.get("build", "")) for b in BUILDS + ["any"])
        cats = "".join(opt(c, n, form.get("category", "")) for c, n in CATEGORIES)
        err = f'<p class="hb-err" role="alert">{e(msg)}</p>' if msg else ""
        body = ('<section class="ly-panel"><h1>Submit a mod</h1>'
                '<p>Add an open project to the index: an addon, a realm module or script, a tool, a preset. '
                'We only need the link; the rest is read from the repo. No account, no email.</p>'
                f'{err}<form class="hb-form" method="post" action="{BASE}/submit">'
                f'<label for="s-repo">Repo link (GitHub, GitLab or Codeberg)</label>'
                f'<input id="s-repo" name="repo" required maxlength="300" placeholder="https://github.com/you/your-mod" '
                f'value="{e(form.get("repo", ""))}">'
                f'<label for="s-build">Client build</label><select id="s-build" name="build">{builds}</select>'
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
        build = build_tag(form.get("build"))
        if not build:
            return False, "Pick the client build it is for."
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


HUB_CSS = """
.hb-flag{margin:0 0 10px;text-align:center;font:600 11px/1.4 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--ly-violet,#b48cff)}
.hb-sub{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 8px;margin:0 0 18px}
.hb-sub a{padding:8px 12px;border:1px solid var(--ly-line,rgba(120,150,255,.28));border-radius:999px;text-decoration:none;
color:var(--ly-dim,#a9b0d6);font:600 12px/1 system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase}
.hb-sub a.on,.hb-sub a:hover{color:var(--ly-ink,#e8ecff);border-color:var(--ly-cyan,#5fe3ff)}
.hb-hero h1{margin-bottom:6px}.hb-count,.hb-fine{color:var(--ly-dim,#a9b0d6);font-size:14px;text-align:center}
.hb-actions{display:flex;flex-wrap:wrap;gap:10px;justify-content:center}
.ly-btn.hb-alt{background:transparent}
.hb-builds{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.hb-build,.hb-cat{display:flex;flex-direction:column;gap:2px;padding:14px;border:1px solid var(--ly-line,rgba(120,150,255,.28));border-radius:6px;
background:rgba(18,22,54,.7);text-decoration:none;color:var(--ly-ink,#e8ecff)}
.hb-build:hover,.hb-cat:hover{border-color:var(--ly-cyan,#5fe3ff);box-shadow:var(--ly-glow,0 0 18px rgba(95,227,255,.35))}
.hb-build b{font:600 26px/1 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.06em;color:var(--ly-cyan,#5fe3ff)}
.hb-build span{color:var(--ly-ink,#e8ecff)}.hb-build small,.hb-cat small{color:var(--ly-dim,#a9b0d6)}
.hb-cats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}
.hb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.hb-card{padding:14px;border:1px solid var(--ly-line,rgba(120,150,255,.28));border-radius:6px;background:rgba(18,22,54,.75)}
.hb-card h3{margin:0 0 4px;font:600 19px/1.2 'Leyline Display','OW Cinzel',Impact,sans-serif;letter-spacing:.05em}
.hb-card h3 a{text-decoration:none}.hb-card p{margin:4px 0;font-size:14px;overflow-wrap:anywhere}
.hb-by,.hb-meta{color:var(--ly-dim,#a9b0d6)}
.hb-tag,.hb-src{display:inline-block;margin:2px 4px 2px 0;padding:2px 8px;border-radius:999px;border:1px solid var(--ly-line,rgba(120,150,255,.28));font-size:12px}
.hb-src.hb-workshop{border-color:#5ef0a0;color:#5ef0a0}.hb-src.hb-theme{border-color:var(--ly-violet,#b48cff);color:var(--ly-violet,#b48cff)}
.hb-lic{font-size:12px}
.hb-two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.hb-head{text-align:center}.hb-head h1{font-size:clamp(40px,8vw,72px)}
.hb-filters p{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.hb-chip{padding:6px 10px;border-radius:999px;border:1px solid var(--ly-line,rgba(120,150,255,.28));text-decoration:none;font-size:13px}
.hb-chip.on{background:rgba(95,227,255,.14);border-color:var(--ly-cyan,#5fe3ff);color:var(--ly-ink,#e8ecff)}
.hb-search{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.hb-search input,.hb-form input,.hb-form select,.hb-form textarea{min-height:40px;padding:8px 10px;border-radius:4px;border:1px solid var(--ly-line,rgba(120,150,255,.28));
background:rgba(5,6,20,.9);color:var(--ly-ink,#e8ecff);font:15px system-ui,sans-serif;max-width:100%}
.hb-search input{flex:1 1 220px}.hb-search button{min-height:40px;padding:0 16px;border-radius:4px;border:1px solid var(--ly-cyan,#5fe3ff);
background:rgba(95,227,255,.14);color:var(--ly-ink,#e8ecff);font:600 14px system-ui,sans-serif;cursor:pointer}
.hb-form{display:grid;gap:8px;max-width:560px}.hb-form label{font-weight:600}
.hb-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.hb-err{padding:10px;border:1px solid #ff8a8a;border-radius:4px;color:#ffd0d0}
.hb-pages{display:flex;gap:14px;justify-content:center;margin:16px 0}
.hb-item h1{font-size:clamp(32px,6vw,56px);text-align:left}.hb-sum{font-size:18px}.hb-repo{color:var(--ly-dim,#a9b0d6)}
.hb-list li{margin:4px 0}.hb-empty{color:var(--ly-dim,#a9b0d6)}
"""


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
        handler.send(200, hub.front_page(path), headers=_robots())
        return
    if path == BASE + "/catalog":
        handler.send(200, hub.catalog_page(query), headers=_robots())
        return
    if path == BASE + "/creators":
        handler.send(200, hub.creators_page(), headers=_robots())
        return
    if path == BASE + "/realms":
        handler.send(200, hub.realms_page(query), headers=_robots())
        return
    if path == BASE + "/beacon":
        handler.send(200, hub.beacon_page(), headers=_robots())
        return
    if path == BASE + "/submit":
        done = (query.get("done") or [""])[0] == "1"
        handler.send(200, hub.submit_page(done=done), headers=_robots())
        return
    if path.startswith(BASE + "/p/"):
        status, body = hub.item_page(path[len(BASE + "/p/"):])
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
