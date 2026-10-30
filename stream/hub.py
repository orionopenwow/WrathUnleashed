"""The Leyline hub (hidden preview): one catalog of the Workshop, the community index and theme packs.

Built for the 2026-10-26 brief ("hide the full leyline front page thing but build it out for now") and the
2026-10-29 one (an auto-populated index of open mods for every client build the launcher supports, and a way
for people to submit their mods). Served by stream/wrath_portal.py, which loads this file from beside itself
and runs without it.

    GET  /wrath/leyline-preview               the front page: builds, categories, picks, creators, Host a Beacon
    GET  /wrath/leyline-preview/catalog       everything, filtered by plain links and a GET form (no script):
                                              ?build=1.12|2.4.3|3.3.5a &cat=<category>|themes (4.3.4, 5.4.8 hidden: HIDDEN_BUILDS)
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

    def _shell(self, title: str, body: str, path: str) -> bytes:
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
                         for h, t in (("", "Hub"), ("/catalog", "Catalog"), ("/creators", "Creators"),
                                      ("/realms", "Realms"), ("/beacon", "Host a Beacon"), ("/submit", "Submit a mod")))
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
                f'<main id="main" class="hb-main{" hb-front" if front else ""}">{flag}{sub}{body}</main>{foot}</body></html>').encode("utf-8")

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
            card(name, "Server:", on, "/wrath/realms", f" · {int(pl)} playing" if on and isinstance(pl, int) and pl >= 0 else "")
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
            pic = shot or f'<span class="hb-initial" aria-hidden="true">{e((i["name"] or "?")[:1].upper())}</span>'
            line = i.get("summary") or i.get("description") or ""
            cards.append(f'<a class="hb-spot" href="{BASE}/p/{_slug(i["id"])}"><span class="hb-pic">{pic}</span>'
                         f'<span class="hb-spot-t"><small>{e(labels[i["id"]])}</small><b>{e(i["name"])}</b>'
                         f'<i>by {e(i["author"] or "unknown")}</i><span>{e(line)}</span></span></a>')
        return ('<section class="hb-sec" id="community" aria-labelledby="hb-cs"><h2 id="hb-cs">Community Spotlight</h2>'
                f'<div class="hb-spots">{"".join(cards)}</div>'
                f'<p class="hb-more"><a href="{BASE}/catalog">Browse the whole catalog</a></p></section>')

    def front_page(self, path: str = BASE) -> bytes:
        e = html.escape
        items = self.items()
        shown = offered_builds()
        by_build = {b: sum(1 for i in items if b in i["builds"]) for b in shown}
        by_cat = {c: sum(1 for i in items if i["category"] == c) for c in CATEGORY_IDS + ["themes"]}
        builds = "".join(
            f'<a class="hb-chip" href="{BASE}/catalog?build={b}"><b>{e(BUILD_LABEL[b])}</b> {by_build[b]}</a>' for b in shown)
        cats = "".join(
            f'<a class="hb-chip" href="{BASE}/catalog?cat={c}">{e(n)} <small>{by_cat[c]}</small></a>' for c, n in CATEGORIES + [THEMES])
        bullets = "".join(f"<li>{e(x)}</li>" for x in (
            "Finds your own 1.12.1, 2.4.3 and 3.3.5a clients, and lists other builds too",
            "Realms show their server and build; PLAY picks a client that fits",
            "Updates itself in the background: restart when you're ready, never mid-game"))
        body = (
            '<section class="hb-hero" id="features" aria-labelledby="hb-h">'
            f'<div class="hb-art" aria-hidden="true">{self._spin(560, "slow hb-swirl")}'
            '<img class="hb-crystal" src="/wrath/art/leyline-crystal-512.png" alt="" width="380" height="380" fetchpriority="high"></div>'
            '<!-- TODO(owner): the hero heading and bullets are from the owner\'s mockup; his final wording -->'
            '<h1 id="hb-h">Every client, every server</h1>'
            f'<ul class="hb-bullets">{bullets}</ul>'
            f'<p><a class="hb-cta" href="{e(self._download())}" rel="noopener noreferrer">Download Now</a></p>'
            '<p class="hb-note">Free and open source, for Windows, macOS and Linux. Nothing to buy.</p></section>'
            + self.status_cards() + self.spotlight() +
            '<section class="hb-sec" aria-labelledby="hb-b"><h2 id="hb-b">Browse by client</h2>'
            f'<p class="hb-chips">{builds}</p><h3>Categories</h3><p class="hb-chips">{cats}</p></section>'
            '<section class="hb-two">'
            f'<a class="hb-box" href="{BASE}/creators"><b>For creators</b><span>Make an addon, a realm script or a whole mode: '
            'the docs, the package format and how the index works.</span></a>'
            f'<a class="hb-box" href="{BASE}/beacon"><b>Host a Beacon</b><span>Run your own realm and put it on the Leyline '
            'list, so players can hop over from the launcher.</span></a></section>'
            '<p class="hb-fine">Community projects are links: nothing of theirs is hosted here. Each belongs to its '
            'authors, under the licence they chose.</p>')
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

    def card(self, i: dict, m: dict | None = None, rk=None) -> str:
        e = html.escape
        rank = ""
        if m is not None and rk is not None:
            rank = (f'<p class="hb-rk">{e(rk.stars_text(m["rating"]))} · {m["installs"]["all"]} installs'
                    + (" · Install with Leyline" if rk.installable(i) else "") + "</p>")
        badge = {"workshop": "Workshop", "index": "Community", "theme": "Theme"}[i["source"]]
        builds = " ".join(f'<span class="hb-tag">{e(BUILD_LABEL.get(b, b))}</span>' for b in i["builds"])
        stars = f' · ★ {int(i["stars"])}' if isinstance(i.get("stars"), int) and not isinstance(i.get("stars"), bool) else ""
        return (f'<article class="hb-card"><h3><a href="{BASE}/p/{_slug(i["id"])}">{e(i["name"])}</a></h3>'
                f'<p class="hb-by">by {e(i["author"] or "unknown")} · <span class="hb-src hb-{i["source"]}">{badge}</span></p>'
                f'<p>{e(i.get("description") or i["summary"])}</p><p class="hb-meta">{builds}'
                f'<span class="hb-lic">{e(i.get("licence") or "licence not stated")}{stars}</span></p>{rank}</article>')

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
        f_build = chips("build", [("", "All builds")] + [(b, BUILD_LABEL[b]) for b in offered_builds()], build)
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
                + (f' for {e(BUILD_LABEL[build])}' if build else "") + '</p></header>'
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
        rel = i.get("release") if isinstance(i.get("release"), dict) else None
        if rel:
            rows.append(("Latest release", rel["tag"] + (f" ({rel['date']})" if rel.get("date") else "")))
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
        if rel and i.get("repo") and rel["url"].startswith(i["repo"] + "/"):
            acts.append(f'<a class="ly-btn hb-alt" href="{e(rel["url"])}" rel="noopener noreferrer nofollow ugc">Latest release</a>')
        rk = self.portal("hub_rank")
        try:
            panel = rk.item_panel(handler, i, query) + f"<style>{rk.RANK_CSS}</style>" if rk is not None and handler is not None else ""
        except Exception:   # noqa: BLE001: the rankings never break the page
            panel = ""
        body = (f'<article class="ly-panel hb-item"><h1>{e(i["name"])}</h1><p class="hb-sum">{e(i["summary"])}</p>{desc}'
                f'<table class="ly-table">{table}</table><p class="hb-actions">{" ".join(acts)}</p>'
                f'<p class="hb-fine">{e(how)}</p></article>{panel}')
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
                '<p>Every day a script checks the forges for open projects for each client build (1.12.1, 2.4.3 '
                'and 3.3.5a for now), reads each repo\'s licence, files and addon TOC, and refreshes the stars and '
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
        builds = "".join(opt(b, BUILD_LABEL[b], form.get("build", "")) for b in offered_builds() + ["any"])
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
        build = offered_tag(form.get("build"))
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
/* the hero: the big crystal glowing over the slowly turning swirl */
.hb-hero{position:relative;text-align:center;padding:24px 16px 36px;margin:0 -16px;overflow:hidden;isolation:isolate}
.hb-signin img{transform:scale(1.7)}
.hb-art{position:relative;height:270px;display:grid;place-items:center;margin-bottom:0}
.hb-swirl{position:absolute;left:50%;top:50%;width:min(560px,130vw)!important;height:min(560px,130vw)!important;
transform:translate(-50%,-42%);opacity:.24;z-index:-1}
.hb-swirl::after{display:none}
.hb-crystal{width:380px;height:380px;max-width:none;margin:-55px 0;filter:drop-shadow(0 0 22px rgba(91,141,239,.7)) drop-shadow(0 0 60px rgba(139,108,240,.45))}
.hb-hero h1{margin:6px 0 12px;font-size:clamp(30px,5.4vw,48px);line-height:1.05;font-weight:800;letter-spacing:-.01em;text-transform:uppercase}
.hb-bullets{display:inline-block;margin:0 auto 22px;padding:0 16px;text-align:left;color:var(--lk-text-2);max-width:620px}
.hb-bullets li{margin:4px 0;padding-left:4px}
.hb-bullets li::marker{color:var(--lk-accent)}
.hb-cta{display:inline-block;padding:13px 30px;border-radius:var(--lk-r-sm);background:var(--lk-accent);color:#fff!important;
text-decoration:none;font-weight:700;font-size:17px;box-shadow:0 0 0 1px rgba(255,255,255,.08),0 8px 26px rgba(91,141,239,.35)}
.hb-cta:hover{background:var(--lk-accent-strong)}
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
@media (max-width:420px){.hb-pic{width:84px;height:72px}.hb-crystal{width:300px;height:300px;margin:-40px 0}.hb-art{height:220px}}
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
@media (prefers-reduced-motion:reduce){.hb *{transition:none!important}}
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
