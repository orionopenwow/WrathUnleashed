#!/usr/bin/env python3
"""The scout: a daily scan for novel open projects the Leyline launcher could link, list or learn from (owner,
2026-10-30: "a robust scanning system for novel GitHubs and other things we can merge into this ultimate launcher").

    python3 -I tools/hub-index/scout.py run [--date YYYY-MM-DD] [--probe 40] [--max-pages 1] [--no-reddit]
                                            [--report FILE]

Where it looks (read-only, rate-limit aware, works without a token: fewer results then):
  * GitHub search, per area (launchers, server cores and modules, bots, addons and UI, tools and editors, web and
    mobile clients, graphics): repos created in the last 30 days, and repos pushed in the last 14 days with stars
    (the risers; star velocity comes from scout-state.json's history, the pool's last-known stars as a baseline);
  * Codeberg and GitLab, newest first, like hub_index.py discover;
  * r/wowservers, its public feeds only (new/.rss and top/.json?t=week) with a polite User-Agent: GitHub, GitLab
    and Codeberg links in the posts. 403 and 429 are taken as "not today". Nothing else is fetched from Reddit, and
    never a post's image.
How each find is vetted: the index's own rules (hub_index.py probe + judge: licence including the rider check, game-
format files, binaries, decompiled or wowdecomp-derived, paid, blocklist, cheats), plus lure detection (look-alike
names of known projects, identical star counts across new repos of different owners, release-only binaries, README
"download it from Releases" / "turn off your antivirus" patterns). Each is tagged with what it could add to Leyline
(realm hosting, mobile, graphics, bots, mod format, editor, web client, launcher, ...) with a one-line reason taken
from its own words. Heuristics only: no LLM calls.
What it writes (same input, same bytes: no clocks but the date):
  docs/scout/<date>.md                 the digest: top 15 new, top risers, Reddit mentions (permalinks), merge
                                       candidates by tag, rejected with reasons, suspected lures
  tools/hub-index/scout-state.json     star history, first-seen dates, verdicts, Reddit posts seen
  tools/hub-index/candidates.json      new finds that passed (not lures, no hard rule) join the pool with
                                       via "scout:...", so the daily index build and its review gate look at them
Nothing is posted anywhere. The workflow (.github/workflows/scout.yml) opens or updates one PR, never merges it.
Standard library only (plus git for the probes).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_index():
    spec = importlib.util.spec_from_file_location("wu_hub_index", os.path.join(HERE, "hub_index.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HI = _load_index()
H = HI.H
REPO = HI.REPO
STATE = os.path.join(HERE, "scout-state.json")
OUT_DIR = os.path.join(REPO, "docs", "scout")
log = HI.log

# ------------------------------------------------------------------------------------------- where to look
# area -> GitHub queries. "new" runs every query with created:>=30 days ago; "risers" the first two with pushed:>=14
# days ago and stars:>=15. Keep them few: an anonymous run gets 10 searches a minute.
AREAS = {
    "launchers": ["wow launcher", "realmlist launcher", "topic:wow-launcher", "private server launcher"],
    "server cores and modules": ["topic:azerothcore-module", "azerothcore module", "topic:trinitycore", "topic:vmangos",
                                 "topic:cmangos"],
    "bots": ["playerbots", "npcbots", "topic:playerbots", "llm npc azerothcore"],
    "addons and UI": ["topic:wow-addon", "topic:wotlk-addon", "topic:vanilla-addons", "3.3.5 addon"],
    "tools and editors": ["noggit", "wow map editor", "dbc editor", "wow model viewer", "azerothcore tool"],
    "web and mobile clients": ["wow web client", "wotlk webgl", "wow wasm", "wow android", "wow mobile client"],
    "graphics": ["wow hd textures", "wotlk graphics", "wow reshade", "dxvk wow"],
}
NEW_DAYS, RISER_DAYS, RISER_STARS = 30, 14, 15
CODEBERG_TERMS = ["azerothcore", "trinitycore", "wotlk", "vanilla-wow", "wow-addon", "mangos"]
GITLAB_TOPICS = ["azerothcore", "trinitycore", "wow-addon", "world-of-warcraft", "wotlk"]
REDDIT_FEEDS = ("https://www.reddit.com/r/wowservers/new/.rss", "https://www.reddit.com/r/wowservers/top/.json?t=week")
REDDIT_HOSTS = frozenset({"www.reddit.com"})
REDDIT_UA = "leyline-scout/1.0 (read-only daily digest; +https://github.com/orionopenwow/Leyline)"
REDDIT_MAX_LOOKUPS = 15
REPO_LINK = re.compile(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|codeberg\.org)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
                       r"(?:/[A-Za-z0-9_.-]+)?", re.I)

# ------------------------------------------------------------------------------------------- what it could add
# (tag, weight for Leyline, pattern). The reason line quotes the words that matched, from the project's own text.
TAGS = [
    ("web client", 5, re.compile(r"(?i)\bweb ?gpu\b|\bwebgl\b|\bwasm\b|webassembly|in (the|your) browser|\bweb client\b|"
                                 r"\bthree\.js\b|\bbabylon(js)?\b")),
    ("realm hosting", 5, re.compile(r"(?i)docker[- ]compose|\bdocker\b|\bhelm\b|kubernetes|one[- ]click (server|realm)|"
                                    r"\bself[- ]host(ed|ing)?\b|\bserver (manager|panel|launcher)\b|\brealm (manager|hosting)\b|"
                                    r"\bansible\b|\bcontrol panel\b")),
    ("launcher", 4, re.compile(r"(?i)\blauncher\b|\bupdater\b|\brealmlist\b|\bpatch(er)? (manager|downloader)\b")),
    ("mobile", 4, re.compile(r"(?i)\bandroid\b|\bios\b|\bmobile\b|\bflutter\b|react native|\bwinlator\b|\bbox64\b")),
    ("mod format", 4, re.compile(r"(?i)\bmod (manager|loader|format)\b|\baddon (manager|updater)\b|\bpackage manager\b|"
                                 r"\bmanifest\b|\bplugin system\b|\bmodding (api|framework)\b")),
    ("bots", 3, re.compile(r"(?i)\bplayerbots?\b|\bnpcbots?\b|\bbots?\b|\bai players?\b|\bllm\b|\bgpt\b|\bcompanions?\b")),
    ("editor", 3, re.compile(r"(?i)\beditor\b|\bnoggit\b|\bmap (maker|builder)\b|\bdbc\b|\bwdbx\b|\bmodel viewer\b|\bstudio\b")),
    ("graphics", 3, re.compile(r"(?i)\bshaders?\b|\breshade\b|\bdxvk\b|\bvulkan\b|\btextures?\b|\bhd\b|\b4k\b|\blighting\b|"
                               r"\bupscal\w*\b")),
    ("server core", 2, re.compile(r"(?i)\bemulator\b|\bazerothcore\b|\btrinitycore\b|\bc?mangos\b|\bvmangos\b|\bskyfire\b|"
                                  r"\bworldserver\b|\bauthserver\b")),
    ("addons/UI", 2, re.compile(r"(?i)\baddons?\b|\buser interface\b|\bui\b|\bunit ?frames?\b|\baction ?bars?\b")),
    ("tools", 1, re.compile(r"(?i)\barmory\b|\bcms\b|\bdiscord bot\b|\bapi\b|\bdashboard\b|\bstatus page\b|\bmonitor")),
]

# ------------------------------------------------------------------------------------------- lures
LURE_README = re.compile(r"(?i)download (it |the )?(latest |newest )?(version |build )?(from|in|on|at) (the )?releases?\b|"
                         r"\b(go|head) to (the )?releases?\b|download (the )?(setup|installer|\.exe|exe)\b|"
                         r"\bpassword\s*[:=]\s*\S+|\b(disable|turn off) (your )?(anti-?virus|defender|windows defender|av)\b|"
                         r"\brun (it )?as admin(istrator)?\b|extract (the )?(zip|rar|archive) and run")
LURE_STRONG = re.compile(r"(?i)\bpassword\s*[:=]\s*\S+|\b(disable|turn off) (your )?(anti-?virus|defender|windows defender|av)\b")
LURE_SUFFIX = re.compile(r"(?i)[-_ ]?(pro|free|crack(ed)?|download|latest|full|premium|unlocked|20\d\d|v?\d+(\.\d+)*)$")
SOURCE_SIGNS = ("cpp", "lua")
GENERIC_NAMES = {re.sub(r"[^a-z0-9]", "", g) for g in HI.GENERIC} | {"addons", "scripts", "server", "launcher", "client",
                                                                      "tools", "website", "playerbots", "dotfiles"}


def norm_name(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein distance, stopping early above cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------------------------------- small helpers
def iso(d: datetime.date) -> str:
    return d.isoformat()


def days_between(a: str, b: str) -> int | None:
    try:
        return (datetime.date.fromisoformat(b[:10]) - datetime.date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return None


def md(text, n: int = 160) -> str:
    """One line of someone else's text, safe in a Markdown table or list: cleaned, cut, no markup or links."""
    t = HI.H.clean_line(str(text or ""), n)
    t = re.sub(r"[<>]", "", t)
    return re.sub(r"([\\|\[\]`*_])", r"\\\1", t)


def gh_find(item: dict) -> dict | None:
    """A GitHub search or repo document as a find (hub_index.gh_meta plus created and the owner's type)."""
    m = HI.gh_meta(item)
    if not m:
        return None
    m["created"] = (item.get("created_at") or "")[:10]
    m["forge"] = "github"
    return m


def gitea_find(item: dict) -> dict | None:
    m = HI.gitea_meta(item)
    if m:
        m["created"] = (item.get("created_at") or "")[:10]
        m["forge"] = "codeberg"
    return m


def gitlab_find(item: dict) -> dict | None:
    m = HI.gitlab_meta(item)
    if m:
        m["created"] = (item.get("created_at") or "")[:10]
        m["forge"] = "gitlab"
    return m


# ------------------------------------------------------------------------------------------- gathering
class Scout:
    def __init__(self, today: datetime.date, api=None, fetcher=None, probe_fn=None, max_pages: int = 1,
                 reddit: bool = True, sleep=time.sleep):
        self.today = today
        self.api = api or HI.Api()
        self.fetcher = fetcher or HI.Fetcher(page_base="https://www.reddit.com", page_hosts=REDDIT_HOSTS,
                                             image_hosts=frozenset())
        self.probe_fn = probe_fn or HI.probe
        self.max_pages = max(1, max_pages)
        self.reddit_on = reddit
        self.sleep = sleep
        self.finds: dict[str, dict] = {}
        self.notes: list[str] = []
        self.mentions: list[dict] = []

    # --------------------------------------------------------------- GitHub
    def search(self, q: str, sort: str) -> list[dict]:
        out = []
        for page in range(1, self.max_pages + 1):
            url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
                {"q": q, "sort": sort, "order": "desc", "per_page": 50, "page": page})
            st, d, _ = self.api.get(url)
            self.sleep(2.2 if self.api.token else 6.5)                    # 30 / 10 searches a minute
            if st != 200 or not isinstance(d, dict):
                if st not in (200, 0):
                    log(f"  search {q!r}: HTTP {st}")
                break
            items = [i for i in d.get("items") or [] if isinstance(i, dict)]
            out += [f for f in (gh_find(i) for i in items) if f]
            if len(items) < 50:
                break
        return out

    def add(self, meta: dict, source: str, area: str = "") -> dict | None:
        c = H.canonical(meta.get("repo", ""))
        if not c or meta.get("private") or meta.get("fork"):
            return None
        f = self.finds.get(c["key"])
        if f is None:
            f = self.finds[c["key"]] = {"key": c["key"], "repo": c["url"], "forge": c["forge"], "owner": c["owner"],
                                        "name": c["repo"], "id": c["id"], "sources": [], "areas": [], "stars": None,
                                        "created": "", "pushed": "", "description": "", "topics": [], "licence": "",
                                        "archived": False, "reddit": []}
        if source not in f["sources"]:
            f["sources"] = sorted(f["sources"] + [source])
        if area and area not in f["areas"]:
            f["areas"] = sorted(f["areas"] + [area])
        for k in ("stars", "created", "pushed", "description", "topics", "licence", "archived", "licence_raw"):
            if meta.get(k) not in (None, "", []):
                f[k] = meta[k]
        return f

    def github(self) -> None:
        new_since = iso(self.today - datetime.timedelta(days=NEW_DAYS))
        push_since = iso(self.today - datetime.timedelta(days=RISER_DAYS))
        for area, queries in AREAS.items():
            for q in queries:
                if self.api.limited:
                    break
                for m in self.search(f"{q} created:>={new_since} fork:false", "stars"):
                    self.add(m, "github:new", area)
            for q in queries[:2]:
                if self.api.limited:
                    break
                for m in self.search(f"{q} pushed:>={push_since} stars:>={RISER_STARS} fork:false", "stars"):
                    self.add(m, "github:risers", area)
        if self.api.limited:
            self.notes.append("GitHub's API rate limit ran out during the run: fewer GitHub results than usual"
                              + ("" if self.api.token else " (no token: anonymous limits)") + ".")
        elif not self.api.token:
            self.notes.append("No GitHub token: anonymous search limits (fewer pages).")

    def forges(self) -> None:
        since = iso(self.today - datetime.timedelta(days=NEW_DAYS))
        for t in CODEBERG_TERMS:
            st, d, _ = self.api.get("https://codeberg.org/api/v1/repos/search?" + urllib.parse.urlencode(
                {"q": t, "topic": "true", "sort": "created", "order": "desc", "limit": 50}), "application/json")
            items = d.get("data") if st == 200 and isinstance(d, dict) else None
            for i in items or []:
                m = gitea_find(i) if isinstance(i, dict) else None
                if m and m.get("created", "") >= since:
                    self.add(m, "codeberg:new", "")
        for t in GITLAB_TOPICS:
            st, d, _ = self.api.get("https://gitlab.com/api/v4/projects?" + urllib.parse.urlencode(
                {"topic": t, "per_page": 50, "order_by": "created_at", "sort": "desc", "visibility": "public"}),
                "application/json")
            for i in d if st == 200 and isinstance(d, list) else []:
                m = gitlab_find(i) if isinstance(i, dict) else None
                if m and m.get("created", "") >= since:
                    self.add(m, "gitlab:new", "")

    # --------------------------------------------------------------- Reddit
    def reddit(self) -> None:
        """r/wowservers' two public feeds. Only these two URLs are ever fetched from Reddit."""
        posts: dict[str, dict] = {}
        for url in REDDIT_FEEDS:
            st, body, _ = self.fetcher.get(url, REDDIT_HOSTS, 3_000_000, {"User-Agent": REDDIT_UA, "Accept":
                                                                          "application/json, application/atom+xml"})
            if st != 200 or not body:
                self.notes.append(f"Reddit {'new (RSS)' if url.endswith('.rss') else 'top of the week (JSON)'}: "
                                  f"{'HTTP ' + str(st) if st else 'no answer'}, skipped today.")
                continue
            got = parse_reddit_rss(body) if url.endswith(".rss") else parse_reddit_json(body)
            for p in got:
                old = posts.get(p["permalink"])
                if old:
                    old["links"] = sorted(set(old["links"]) | set(p["links"]))
                    old["score"] = max(old.get("score") or 0, p.get("score") or 0) if (old.get("score") is not None
                                                                                        or p.get("score") is not None) else None
                else:
                    posts[p["permalink"]] = p
        lookups = 0
        for perm in sorted(posts):
            p = posts[perm]
            if not p["links"]:
                continue
            self.mentions.append(p)
            for link in p["links"]:
                c = H.canonical(link)
                if not c:
                    continue
                f = self.finds.get(c["key"])
                if f is None and lookups < REDDIT_MAX_LOOKUPS and c["forge"] == "github" and not self.api.limited:
                    lookups += 1
                    st, d, _ = self.api.get(f"https://api.github.com/repos/{urllib.parse.quote(c['owner'])}/"
                                            f"{urllib.parse.quote(c['repo'])}")
                    m = gh_find(d) if st == 200 and isinstance(d, dict) else None
                    f = self.add(m or {"repo": c["url"]}, "reddit", "")
                elif f is None:
                    f = self.add({"repo": c["url"]}, "reddit", "")
                else:
                    self.add({"repo": c["url"]}, "reddit", "")
                if f is not None and perm not in f["reddit"]:
                    f["reddit"] = sorted(f["reddit"] + [perm])

    def gather(self) -> None:
        if self.api.ok() if hasattr(self.api, "ok") else True:
            self.github()
        else:
            self.notes.append("GitHub's API did not answer: no GitHub search today.")
        self.forges()
        if self.reddit_on:
            self.reddit()


def _post_links(text: str) -> list[str]:
    out = set()
    for m in REPO_LINK.finditer(text or ""):
        u = m.group(0).rstrip(".,);:!?'\"")
        c = H.canonical(u)
        if c:
            out.add(c["url"])
    return sorted(out)


def _permalink_ok(url: str) -> bool:
    u = urllib.parse.urlsplit(url or "")
    return u.scheme == "https" and u.hostname == "www.reddit.com" and u.path.startswith("/r/wowservers/comments/") \
        and not u.query and len(url) < 300


def parse_reddit_rss(body: bytes) -> list[dict]:
    """Posts of an Atom feed: {permalink, title, links (forge repo links in the post), score None}."""
    text = body.decode("utf-8", "replace")
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("a:entry", ns):
        link = e.find("a:link", ns)
        perm = (link.get("href") if link is not None else "") or ""
        perm = perm.split("?")[0]
        if not _permalink_ok(perm):
            continue
        title = (e.findtext("a:title", "", ns) or "").strip()
        content = e.findtext("a:content", "", ns) or ""
        out.append({"permalink": perm, "title": title, "links": _post_links(content + " " + title), "score": None})
    return out


def parse_reddit_json(body: bytes) -> list[dict]:
    try:
        doc = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return []
    out = []
    for ch in ((doc.get("data") or {}).get("children") or []) if isinstance(doc, dict) else []:
        d = ch.get("data") if isinstance(ch, dict) else None
        if not isinstance(d, dict) or not isinstance(d.get("permalink"), str):
            continue
        perm = "https://www.reddit.com" + d["permalink"].split("?")[0]
        if not _permalink_ok(perm):
            continue
        text = " ".join(str(d.get(k) or "") for k in ("url", "selftext", "title"))
        score = d.get("score") if isinstance(d.get("score"), int) and not isinstance(d.get("score"), bool) else None
        out.append({"permalink": perm, "title": str(d.get("title") or "").strip(), "links": _post_links(text), "score": score})
    return out


# ------------------------------------------------------------------------------------------- scoring and vetting
def velocity(f: dict, state: dict, pool: dict, today: str) -> float | None:
    """Stars a week: from the state's history (the oldest point in the last 30 days, else the newest older one),
    else the pool's last-known stars against the last run, else stars over age for a repo made in the last 60 days."""
    stars = f.get("stars")
    if not isinstance(stars, int):
        return None
    hist = [(d, n) for d, n in (state.get("repos", {}).get(f["key"], {}).get("stars") or []) if d < today]
    if hist:
        recent = [p for p in hist if (days_between(p[0], today) or 999) <= 30]
        d0, n0 = (recent[0] if recent else hist[-1])
        days = days_between(d0, today) or 0
        if days > 0:
            return round((stars - n0) * 7 / days, 1)
    p = pool.get(f["key"])
    last = state.get("last_run") or ""
    if p and isinstance(p.get("stars"), int) and last:
        days = days_between(last, today) or 0
        if days > 0:
            return round((stars - p["stars"]) * 7 / days, 1)
    age = days_between(f.get("created") or "", today)
    if age is not None and 0 <= age <= 60:
        return round(stars * 7 / max(age, 1), 1)
    return None


def merge_tags(f: dict, readme: str = "") -> list[dict]:
    """What it could add to Leyline: [{tag, weight, why}] (why: the words that matched, and where)."""
    out = []
    own = " ".join([f["name"].replace("-", " ").replace("_", " "), f.get("description") or "",
                    " ".join(t.replace("-", " ") for t in f.get("topics") or [])])
    for tag, w, rx in TAGS:
        hits = sorted({m.group(0).lower() for m in rx.finditer(own)})
        where = "its description" if hits else ""
        if not hits and readme:
            hits = sorted({m.group(0).lower() for m in rx.finditer(readme[:30_000])})
            where = "its README"
        if hits:
            words = ", ".join(f"'{h}'" for h in hits[:3])
            out.append({"tag": tag, "weight": w, "why": f"{words} in {where}"})
    return out


def score(f: dict) -> float:
    s = 10 * math.log10((f.get("stars") or 0) + 1)
    v = f.get("velocity")
    if isinstance(v, (int, float)) and v > 0:
        s += 8 * math.log10(v + 1)
    s += 6 if f.get("novel") else 0
    s += 4 if f.get("age") is not None and f["age"] <= NEW_DAYS else 0
    s += min(10, sum(t["weight"] for t in f.get("tags") or []))
    s += 2 if f.get("reddit") else 0
    s -= 5 if f.get("archived") else 0
    return round(s, 1)


def known_projects(pool: dict) -> dict[str, list[tuple[str, str, int]]]:
    """Normalised name -> [(url, owner, stars)] for projects we already know well (the index, seeds, the pool with
    some stars): the names a lure copies."""
    out: dict[str, list] = {}
    idx = HI.read_json(HI.INDEX, {}).get("entries") or []
    seeds = HI.read_json(HI.SEEDS, {}).get("seeds") or []
    for url, stars in [(e.get("repo", ""), e.get("stars") or 0) for e in idx] + [(s.get("repo", ""), 100) for s in seeds] \
            + [(r.get("repo", ""), r.get("stars") or 0) for r in pool.values() if (r.get("stars") or 0) >= 25]:
        c = H.canonical(url)
        if c and len(norm_name(c["repo"])) >= 5 and norm_name(c["repo"]) not in GENERIC_NAMES:
            out.setdefault(norm_name(c["repo"]), []).append((c["url"], c["owner"].lower(), int(stars or 0)))
    return out


def lookalike(f: dict, known: dict) -> str:
    """A new repo (60 days) named like a project we know, by another owner, with no more stars than it."""
    n = norm_name(f["name"])
    if len(n) < 5 or f.get("age") is None or f["age"] > 60:
        return ""
    base = norm_name(LURE_SUFFIX.sub("", f["name"]))
    for cand in sorted({n, base}):
        for k in sorted(known):
            if (cand == k or (len(k) >= 7 and edit_distance(cand, k, 2) <= 2)) and \
                    all(owner != f["owner"].lower() for _u, owner, _s in known[k]):
                best = max(known[k], key=lambda x: (x[2], x[0]))
                if (f.get("stars") or 0) <= max(best[2], 10):
                    return f"a look-alike of {best[0]} (same or near-same name, another owner)"
    return ""


def name_tokens(f: dict) -> set[str]:
    words = re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", f["name"]).lower())
    out = {w for w in words if len(w) >= 4}
    d = re.sub(r"\s+", " ", (f.get("description") or "").strip().lower())
    if len(d) >= 12:
        out.add("desc:" + d)
    return out


def star_clusters(finds: list[dict]) -> dict[str, str]:
    """New repos (made in the window, within a week of each other) by three or more different owners with exactly the
    same star count (5 or more) and a shared name word or the same description: bought or botted stars on copies, the
    usual lure campaign. key -> reason."""
    by: dict[tuple, list[dict]] = {}
    for f in finds:
        if isinstance(f.get("stars"), int) and f["stars"] >= 5 and f.get("age") is not None and f["age"] <= NEW_DAYS:
            for t in name_tokens(f):
                by.setdefault((f["stars"], t), []).append(f)
    out = {}
    for (stars, _t), fs in sorted(by.items()):
        fs = sorted(fs, key=lambda f: (f.get("created") or "", f["key"]))
        owners = {f["owner"].lower() for f in fs}
        if len(owners) >= 3:
            span = days_between(fs[0].get("created") or "", fs[-1].get("created") or "")
            if span is not None and span <= 7:
                for f in fs:
                    out.setdefault(f["key"], f"one of {len(fs)} new look-alike repos by different owners with exactly "
                                             f"{stars} stars each")
    return out


def lure_reason(f: dict, facts: dict, known: dict, clusters: dict) -> str:
    if f["key"] in clusters:
        return clusters[f["key"]]
    la = lookalike(f, known)
    if la:
        return la
    readme = facts.get("readme") or ""
    if LURE_STRONG.search(readme):
        return "README asks for an archive password or to turn off the antivirus"
    if facts.get("ok"):
        no_source = not any(facts.get(k) for k in SOURCE_SIGNS) and not facts.get("tocs") and (facts.get("files_n") or 0) <= 4
        if no_source and LURE_README.search(readme):
            return "release-only download: almost no files, and the README says to download it from Releases"
    return ""


HARD = re.compile(r"(?i)game-format|binaries|decompil|chumpton|repack|client patch|bot, cheat|sell things|paid|"
                  r"licence is not open|blocklist|current game|is gone")


def meta_reject(cand: dict, meta: dict, block: dict) -> str:
    """The rules a find breaks on its name, description and topics alone ("" when none): for finds not probed."""
    v = HI.judge(cand, {"ok": True, "readme": "", "tocs": [], "files_n": 10, "cpp": 1}, dict(meta, licence="MIT"), block)
    return v["reason"] if v["verdict"] == "excluded" and HARD.search(v["reason"]) else ""


def make_cand(f: dict) -> dict:
    c = H.canonical(f["repo"])
    text = " ".join([f["name"], f.get("description") or "", " ".join(f.get("topics") or [])])
    hint = sorted({b for b, rx in HI.STRONG_BUILD.items() if rx.search(text.lower())}, key=H._build_order)
    return {"url": c["url"], "key": c["key"], "id": c["id"], "forge": c["forge"], "owner": c["owner"],
            "name_raw": c["repo"], "origin": "discovered", "hint_builds": hint, "builds_given": [],
            "pool": {"via": [f"scout:{s}" for s in f["sources"]]}}


def vet(fs: list[dict], probe_n: int, probe_fn, jobs: int = 4) -> None:
    """Probe the best probe_n finds (git), judge every find, and look for lures. Sets on each find: verdict
    (passes | index | watch | rejected | lure | unprobed), reason, tags, lure."""
    block = HI.read_json(HI.BLOCKLIST, {})
    cache = HI.read_json(HI.CACHE, {})
    pool = {H.canonical(r["repo"])["key"]: r for r in HI.read_json(HI.CANDIDATES, {}).get("candidates", [])
            if H.canonical(r.get("repo", ""))}
    known = known_projects(pool)
    clusters = star_clusters(fs)
    order = sorted(fs, key=lambda f: (-score(f), f["key"]))
    todo = order[:max(0, probe_n)]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for f, facts in zip(todo, ex.map(lambda f: probe_fn(f["repo"], cache), todo)):
            results[f["key"]] = facts
    for f in fs:
        facts = results.get(f["key"])
        cand = make_cand(f)
        meta = {k: f.get(k) for k in ("stars", "licence", "description", "topics", "archived", "pushed")}
        meta["licence"] = HI.spdx(meta.get("licence") or "")
        f["tags"] = merge_tags(f, (facts or {}).get("readme") or "")
        f["lure"] = lure_reason(f, facts or {}, known, clusters)
        if f["lure"]:
            f["verdict"], f["reason"] = "lure", f["lure"]
            continue
        if facts is None:
            why = meta_reject(cand, meta, block)
            f["verdict"], f["reason"] = ("rejected", why) if why else ("unprobed", "not probed this run (below the top "
                                                                       f"{probe_n})")
            continue
        v = HI.judge(cand, facts, meta, block)
        reason = v.get("reason", "")
        if v["verdict"] == "listed":
            f["verdict"], f["reason"] = "index", "passes the index rules: the daily build will propose it"
        elif reason.startswith("could not read"):
            f["verdict"], f["reason"] = "unprobed", reason
        elif v["verdict"] == "excluded" and HARD.search(reason):
            f["verdict"], f["reason"] = "rejected", reason
        elif v["verdict"] == "review":
            f["verdict"], f["reason"] = "watch", "needs a person: " + reason
        else:                                  # needs_licence, no supported build, too few stars: not an entry (yet)
            f["verdict"], f["reason"] = "watch", reason or v["verdict"]
        lic = facts.get("licence") or ""
        if lic:
            f["licence_file"] = lic


# ------------------------------------------------------------------------------------------- the digest
def digest(date: str, fs: list[dict], mentions: list[dict], notes: list[str], counts: dict) -> str:
    def link(f):
        return f"[{md(f['owner'] + '/' + f['name'], 80)}]({f['repo']})"

    def tags(f):
        return ", ".join(t["tag"] for t in f.get("tags") or []) or "-"

    good = [f for f in fs if f["verdict"] not in ("rejected", "lure")]
    new = sorted([f for f in good if f.get("age") is not None and f["age"] <= NEW_DAYS],
                 key=lambda f: (-f["score"], f["key"]))[:15]
    risers = sorted([f for f in good if isinstance(f.get("velocity"), (int, float)) and f["velocity"] > 0
                     and not (f.get("age") is not None and f["age"] <= NEW_DAYS)],
                    key=lambda f: (-f["velocity"], f["key"]))[:10]
    lines = [f"# Scout digest {date}", "",
             "New and rising open projects the Leyline launcher could link, list or learn from. Read-only: nothing here",
             "is listed until the daily index build and its review gate take it (finds that passed are in",
             "tools/hub-index/candidates.json). Made by tools/hub-index/scout.py (docs/HUB-INDEX.md, \"The scout\").", "",
             f"Looked at {len(fs)} projects ({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}); "
             f"{sum(1 for f in fs if f['verdict'] == 'index')} pass the index rules, "
             f"{sum(1 for f in fs if f['verdict'] == 'rejected')} rejected, "
             f"{sum(1 for f in fs if f['verdict'] == 'lure')} suspected lures."]
    for n in notes:
        lines.append(f"- {n}")
    lines += ["", "## Top 15 new", ""]
    if new:
        lines += ["| # | Project | Stars | Stars/week | Made | Could add | Verdict |", "|---|---|---|---|---|---|---|"]
        for k, f in enumerate(new, 1):
            lines.append(f"| {k} | {link(f)}<br>{md(f.get('description'), 120)} | {f.get('stars') if f.get('stars') is not None else '?'} "
                         f"| {f.get('velocity') if f.get('velocity') is not None else '-'} | {f.get('created') or '?'} "
                         f"| {tags(f)} | {f['verdict']}: {md(f['reason'], 90)} |")
    else:
        lines.append("Nothing new in the last 30 days.")
    lines += ["", "## Top risers", ""]
    if risers:
        lines += ["| Project | Stars | Stars/week | Could add | Verdict |", "|---|---|---|---|---|"]
        for f in risers:
            lines.append(f"| {link(f)} | {f.get('stars')} | +{f['velocity']} | {tags(f)} | {f['verdict']} |")
    else:
        lines.append("No risers yet (star history builds up over the daily runs).")
    lines += ["", "## Reddit mentions (r/wowservers)", ""]
    if mentions:
        by = {f["key"]: f for f in fs}
        for p in sorted(mentions, key=lambda p: (-(p.get("score") or 0), p["permalink"])):
            repos = []
            for u in p["links"]:
                c = H.canonical(u)
                f = by.get(c["key"]) if c else None
                repos.append(f"{link(f)} ({f['verdict']})" if f else md(u, 100))
            sc = f" ({p['score']} points)" if isinstance(p.get("score"), int) else ""
            lines.append(f"- [{md(p['title'], 120) or 'a post'}]({p['permalink']}){sc}: {', '.join(repos)}")
    else:
        lines.append("No posts linking a repo today (or Reddit didn't answer).")
    lines += ["", "## Merge candidates by tag", "",
              "What each could add to Leyline, from its own words (heuristic: read the repo before deciding anything)."]
    groups: dict[str, list[tuple[dict, str]]] = {}
    for f in good:
        for t in f.get("tags") or []:
            groups.setdefault(t["tag"], []).append((f, t["why"]))
    for tag, _w, _rx in TAGS:
        items = sorted(groups.get(tag, []), key=lambda x: (-x[0]["score"], x[0]["key"]))[:8]
        if items:
            lines += ["", f"### {tag}", ""]
            lines += [f"- {link(f)} ({f.get('stars') if f.get('stars') is not None else '?'} stars, {f['verdict']}): {md(why, 140)}"
                      for f, why in items]
    rej = [f for f in fs if f["verdict"] == "rejected"]
    lines += ["", "## Rejected", ""]
    if rej:
        why: dict[str, int] = {}
        for f in rej:
            r = re.sub(r":.*$", "", f["reason"])
            why[r] = why.get(r, 0) + 1
        lines += [f"- {n} x {md(r, 120)}" for r, n in sorted(why.items(), key=lambda x: (-x[1], x[0]))]
        lines += ["", "<details><summary>Each one</summary>", ""]
        lines += [f"- {link(f)}: {md(f['reason'], 140)}" for f in sorted(rej, key=lambda f: f["key"])[:60]]
        lines += ["", "</details>"]
    else:
        lines.append("None.")
    lures = [f for f in fs if f["verdict"] == "lure"]
    lines += ["", "## Suspected lures", ""]
    if lures:
        lines.append("Never listed, never added to the pool. Worth a blocklist entry (tools/hub-index/blocklist.json) when "
                     "a person agrees.")
        lines.append("")
        lines += [f"- {f['repo']} ({f.get('stars') if f.get('stars') is not None else '?'} stars, made "
                  f"{f.get('created') or '?'}): {md(f['lure'], 160)}" for f in sorted(lures, key=lambda f: f["key"])]
    else:
        lines.append("None today.")
    unp = [f for f in fs if f["verdict"] == "unprobed"]
    if unp:
        lines += ["", f"{len(unp)} more were found but not probed this run (only the best are cloned each day); the ones "
                      "that break no rule on their own words joined the pool, so the index build looks at them anyway."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------- the run
def run(today: datetime.date, scout: Scout, probe_n: int = 40, out_dir: str | None = None, report: str = "") -> int:
    date = iso(today)
    state = HI.read_json(STATE, {"format": 1, "repos": {}, "reddit": {}})
    state.setdefault("repos", {})
    state.setdefault("reddit", {})
    scout.gather()
    pool_doc = HI.read_json(HI.CANDIDATES, {"format": 1, "candidates": []})
    pool = {H.canonical(r["repo"])["key"]: r for r in pool_doc.get("candidates", []) if H.canonical(r.get("repo", ""))}
    index_keys = {H.canonical(e.get("repo", ""))["key"] for e in HI.read_json(HI.INDEX, {}).get("entries") or []
                  if H.canonical(e.get("repo", ""))}
    seed_keys = {H.canonical(s.get("repo", ""))["key"] for s in HI.read_json(HI.SEEDS, {}).get("seeds") or []
                 if H.canonical(s.get("repo", ""))}
    fs = sorted(scout.finds.values(), key=lambda f: f["key"])
    for f in fs:
        f["age"] = days_between(f.get("created") or "", date)
        f["velocity"] = velocity(f, state, pool, date)
        f["novel"] = f["key"] not in pool and f["key"] not in index_keys and f["key"] not in seed_keys \
            and f["key"] not in state["repos"]
    vet(fs, probe_n, scout.probe_fn)
    for f in fs:
        f["score"] = score(f)
    counts: dict[str, int] = {}
    for f in fs:
        for s in f["sources"]:
            k = s.split(":")[0]
            counts[k] = counts.get(k, 0) + 1
    text = digest(date, fs, scout.mentions, scout.notes, counts)
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{date}.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    # the pool: finds that broke no rule and aren't lures (the daily build vets them like any discovered repo)
    added = 0
    for f in fs:
        if f["verdict"] in ("rejected", "lure") or f["key"] in index_keys:
            continue
        build = (make_cand(f)["hint_builds"] or [""])[0]
        meta = {"repo": f["repo"], "stars": f.get("stars"), "licence": HI.spdx(f.get("licence") or ""),
                "description": f.get("description") or "", "topics": f.get("topics") or [],
                "archived": f.get("archived"), "pushed": f.get("pushed") or ""}
        is_new = f["key"] not in pool
        for s in f["sources"]:
            HI.merge_candidate(pool, meta, "scout:" + s, build)
        added += 1 if is_new and f["key"] in pool else 0
    HI.write_json(HI.CANDIDATES, {"format": 1, "note": pool_doc.get("note", "The discovered pool. hub_index.py discover "
                                                                            "and scout.py add to it."),
                                  "candidates": sorted(pool.values(), key=lambda r: r["repo"].lower())})
    # the state: star history (12 points), first seen, the last verdict; Reddit posts seen in the last 60 days
    for f in fs:
        r = state["repos"].setdefault(f["key"], {"first_seen": date, "stars": []})
        if isinstance(f.get("stars"), int):
            r["stars"] = [p for p in r.get("stars") or [] if p[0] != date] + [[date, f["stars"]]]
            r["stars"] = sorted(r["stars"])[-12:]
        r["verdict"], r["reason"] = f["verdict"], HI.H.clean_line(f["reason"], 160)
    for p in scout.mentions:
        state["reddit"].setdefault(p["permalink"], {"first_seen": date, "repos": p["links"]})
    state["reddit"] = {k: v for k, v in state["reddit"].items() if (days_between(v.get("first_seen", date), date) or 0) <= 60}
    state["repos"] = {k: v for k, v in state["repos"].items()
                      if (days_between(v.get("first_seen", date), date) or 0) <= 365 or v.get("verdict") in ("index", "watch")}
    HI.write_json(STATE, {"format": 1, "note": "tools/hub-index/scout.py's memory: star history, first seen, last "
                                               "verdict; Reddit posts seen. Safe to delete (velocity starts over).",
                          "last_run": date, "repos": {k: state["repos"][k] for k in sorted(state["repos"])},
                          "reddit": {k: state["reddit"][k] for k in sorted(state["reddit"])}})
    summary = (f"scout {date}: {len(fs)} projects, {added} new in the pool, "
               f"{sum(1 for f in fs if f['verdict'] == 'lure')} lures, {len(scout.mentions)} Reddit posts with links")
    print(summary)
    if report:
        with open(report, "w", encoding="utf-8") as fh:
            fh.write(summary + "\n\n" + text)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--date", default="", help="the digest's date (default: today, UTC)")
    r.add_argument("--probe", type=int, default=40, help="clone and check the best N finds (default 40)")
    r.add_argument("--max-pages", type=int, default=1)
    r.add_argument("--no-reddit", action="store_true")
    r.add_argument("--report", default="")
    a = ap.parse_args(argv)
    today = datetime.date.fromisoformat(a.date) if a.date else datetime.datetime.now(datetime.timezone.utc).date()
    return run(today, Scout(today, max_pages=a.max_pages, reddit=not a.no_reddit), a.probe, report=a.report)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
