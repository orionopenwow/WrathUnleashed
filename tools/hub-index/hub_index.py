#!/usr/bin/env python3
"""The Leyline hub's community index: a link-out list of open mods for every client build the launcher supports
(1.12.1, 2.4.3, 3.3.5a, 4.3.4, 5.4.8), found on the forges, checked against our rules, and written to
stream/hub/community-index.json. Nothing of anyone's is mirrored or hosted; each entry links to its repo.

    python3 -I tools/hub-index/hub_index.py discover [--max-pages 3]
        Search the forges for candidates and add them to tools/hub-index/candidates.json (the pool: a repo found
        once stays in it, with what the search said: stars, licence, description, topics). GitHub's search API
        (topic and keyword queries per build, and TOC "## Interface:" code search when the token allows it),
        Codeberg's and GitLab's. Token: GITHUB_TOKEN / GH_TOKEN (the workflow's default token is enough);
        without one the anonymous limits apply and the run takes what it can get.

    python3 -I tools/hub-index/hub_index.py build [--jobs 4] [--approved FILE|URL] [--issues owner/repo]
                                                  [--only owner/repo ...] [--report FILE]
        Every candidate (seeds.json: curated; candidates.json: discovered; approved submissions from the portal's
        approved.json and from approved GitHub issues) is probed: a shallow, blob-less git clone (removed straight
        after) for the file list, the licence file, the README and the addon TOCs; plus the forge API's metadata
        when it answers. Then judged by the rules below, deduped, scored, and written:
          stream/hub/community-index.json   the index (format 2, sorted, no dates of its own: same input, same bytes)
          tools/hub-index/holding.json      needs_licence (would be listed once it has an open licence), review
                                            (a person should look), excluded (with the reason)
        Probe results are cached in tools/hub-index/.cache/ by the repo's HEAD commit.

    python3 -I tools/hub-index/hub_index.py gate --base FILE [--full-out FILE] [--summary FILE] [--report FILE]
        The daily review gate (docs/HUB-RANKINGS.md): FILE is the index on main before this run. Entries already on
        main take this run's stars, last change, archived flag, score and latest release; new entries, other changes
        and removals that aren't a hard rule wait for a person (the full build goes to --full-out for the review PR).
        A build never drops an entry because its forge didn't answer, and refuses to shrink the index by more than
        20% at once (build --allow-shrink to override).

    python3 -I tools/hub-index/hub_index.py check
        Validate the index with the hub's own rules (stream/hub.py validate_index). Exit 1 on any problem.

The rules (docs/HUB-INDEX.md has the reasoning):
  * no game data: a repo with game-format files (MPQ, M2, BLP, ADT, WMO, WDT, WDL, DBC, SKIN, ANIM, vmaps, mmaps)
    is left out, and so is anything that calls itself a repack, a client patch or a client download;
  * no binaries or archives committed to the repo (exe, dll, zip, rar, 7z, msi, scr): source only;
  * nothing paid: no shops, VIP, donation perks or paywalled versions;
  * nothing from or about the Chumpton account;
  * nothing decompiled or derived from wowdecomp/Waystone (wowdecomp got a cease-and-desist on 2026-10-29);
  * no bots or cheats for other people's realms;
  * an open licence (SPDX, from the forge or the licence file) or it waits in holding.json's needs_licence;
  * a supported client build, from the addon TOC's Interface number first, then the repo's own words;
  * the game's brand words never appear in our display text: names are cleaned, descriptions scrubbed, and an
    author whose name carries one goes to review;
  * discovered (not curated or submitted) projects need a little signal: MIN_STARS stars.
Standard library only (plus the git command).
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
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SEEDS = os.path.join(HERE, "seeds.json")
CANDIDATES = os.path.join(HERE, "candidates.json")
BLOCKLIST = os.path.join(HERE, "blocklist.json")
HOLDING = os.path.join(HERE, "holding.json")
CACHE = os.path.join(HERE, ".cache", "probes.json")
INDEX = os.path.join(REPO, "stream", "hub", "community-index.json")
MIN_STARS = 3
PROBE_VERSION = 4                 # bump when probe() or the file patterns change: the cache is then refreshed


def load_hub():
    spec = importlib.util.spec_from_file_location("wu_hub_rules", os.path.join(REPO, "stream", "hub.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = load_hub()


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ------------------------------------------------------------------------------------------- patterns
GAME_DATA_EXT = re.compile(r"\.(mpq|m2|mdx|blp|adt|wmo|wdt|wdl|dbc|db2|skin|anim|bls|vmo|vmtile|vmtree|mmap|mmtile|"
                           r"phys|bone|lit|wlw|wlq|zmp)$", re.I)
BINARY_EXT = re.compile(r"\.(exe|dll|scr|msi|zip|rar|7z|cab|apk|dmg|pkg)$", re.I)
# Build dependencies a server core vendors (mysql.exe, zlib.dll, ...) are not what the binaries rule is about.
DEP_DIR = re.compile(r"(?i)(^|/)(deps?|contrib|third[_-]?party|vendor|external|extern|packages|win(32|64)?)/")
DECOMP_FILE = re.compile(r"\.(idb|i64|gzf|til|id0|id1)$|(^|/)ghidra[^/]*/|(^|/)[^/]*decompil", re.I)
# Excluded: wowdecomp anywhere; Waystone or "decompiled" in the project's own name, description or topics; a README
# that says the code is decompiled. Review: a README that mentions decompiler tools (Ghidra, IDA, Hex-Rays).
DECOMP_RE = re.compile(r"(?i)wowdecomp|waystone|decompil|\bdecomp\b|reverse[- ]engineered (game )?client")
DECOMP_README = re.compile(r"(?i)wowdecomp|decompiled (from )?(the )?(game|client|binary|binaries|source|code|wow\.exe)|"
                           r"(code|source|client) (was |is )?decompiled|reverse[- ]engineered (game )?client source")
DECOMP_TOOLS = re.compile(r"(?i)\bghidra\b|\bida pro\b|hex-?rays|\bdecompiler\b")
REPACK_RE = re.compile(r"(?i)\brepacks?\b|client[ _-]?patch|\bhd[ _-]?patch|\bpatch-[a-z0-9]\.mpq|\bmpqs?\b|"
                       r"(game|full|complete)[ _-]?client\b|client[ _-]?(download|installer)|data[ _-]?files?\b.*\bdownload")
CHEAT_RE = re.compile(r"(?i)\bunlocker\b|speed[ _-]?hack|(?<!anti)(?<!anti-)(?<!anti )cheat(?!ing ?detect)|wall[ _-]?hack|"
                      r"\binject(or|ion)?\b|warden[ _-]?bypass|bypass(es|ing)?[ _-]?warden|memory[ _-]?(read|edit|hack)|"
                      r"fishing[ _-]?bot|grind[ _-]?bot|rotation[ _-]?bot|\bbotting\b|\baimbot\b|\bexploits?\b|spoof|"
                      r"packet[ _-]?(editor|sniff)|\bmultibox(ing)?\b|\bnavmesh bot\b|\bautomated play\b|wrobot|honorbuddy|"
                      r"\bmorpher\b")
MONEY_RE = re.compile(r"(?i)\bvip\b|donat(e|ion|ions|or)s?\b|\bpay(ment|pal|wall)s?\b|\bstripe\b|credit[ _-]?card|"
                      r"cash[ _-]?shop|\bdonation[ _-]?(shop|store|points)|store[ _-]?system|\bin-?game[ _-]?(store|shop)\b|"
                      r"\bpremium\b|micro[ _-]?transactions?|\bbattle[ _-]?pass\b|\bshop\b|\bwebshop\b")
PAID_STRONG = re.compile(r"(?i)\b(paid|premium|pro|full) (version|edition|tier|features?)\b|licen[cs]e key|\bpaywall|"
                         r"buy (it|now|a licen[cs]e)|purchase (a |the )?(licen[cs]e|copy|full)|sold separately|"
                         r"(only )?for (patrons|subscribers|supporters)\b|early access for|patreon[- ]exclusive")
PAID_SOFT = re.compile(r"(?i)\bpatreon\b|\bsubscription\b|\bpremium\b|\bvip\b")
GAME_SIGNAL = re.compile(r"(?i)\baddons?\b|\brealms?\b|azerothcore|trinitycore|\bmangos|\beluna\b|private[ _-]?server|"
                         r"\bemulator\b|\.toc\b|\bwow\b|warcraft|azeroth|\bwotlk\b|\bvanilla\b|\bdungeon|\braid|"
                         r"\bguild\b|\bquests?\b|game ?server|worldserver|\bnpcs?\b")
OTHER_GAME_RE = re.compile(r"(?i)\bretail\b.*\b(only|version)\b|\bdragonflight\b|\bthe war within\b|\bshadowlands\b|"
                           r"\bclassic era\b|\bseason of discovery\b|\bhardcore classic\b")
STRONG_BUILD = {
    "1.12": re.compile(r"(?<![\d.])1\.12(\.[01x])?(?![\d.])|\bvmangos\b|mangos[ _-]?zero|mangos[ _-]?classic|\b5875\b"),
    "2.4.3": re.compile(r"(?<![\d.])2\.4\.3(?![\d.])|mangos[ _-]?one\b|mangos[ _-]?tbc|\b8606\b"),
    "3.3.5a": re.compile(r"(?<![\d.])3\.3\.5a?(?![\d.])|azerothcore|mangos[ _-]?two\b|mangos[ _-]?wotlk|\b12340\b"),
    "4.3.4": re.compile(r"(?<![\d.])4\.3\.4(?![\d.])|mangos[ _-]?three\b|\b15595\b"),
    "5.4.8": re.compile(r"(?<![\d.])5\.4\.8(?![\d.])|skyfire[ _-]?548|\b18414\b"),
}
WEAK_BUILD = {
    "1.12": re.compile(r"(?i)\bvanilla\b|\bturtle\b|\b1\.12\b"),
    "2.4.3": re.compile(r"(?i)\btbc\b|burning[ _-]?crusade"),
    "3.3.5a": re.compile(r"(?i)\bwotlk\b|\bwrath\b|\b335\b"),
    "4.3.4": re.compile(r"(?i)\bcataclysm\b|\bcata\b"),
    "5.4.8": re.compile(r"(?i)\bpandaria\b|\bmop\b"),
}
CAT_RULES = [
    ("graphics", re.compile(r"(?i)\bshaders?\b|\bgraphics\b|volumetric|\bfog\b|lighting|reshade|\bdxvk\b|post[ _-]?process")),
    ("encounters", re.compile(r"(?i)\bboss|encounter|\braid|dungeon|mythic|\binstance|challenge|\bdelves?\b|keystone")),
    ("sandbox", re.compile(r"(?i)minigame|game[ _-]?mode|hide[ _-]?and[ _-]?seek|prop[ _-]?hunt|battle[ _-]?royale|\b1v1\b|"
                           r"\bduels?\b|\brace\b|housing|sandbox|\bgolf\b|\bevent(s)?[ _-]?(system|scripts?)\b")),
    ("presets", re.compile(r"(?i)progression|hardcore|blizzlike|\bpreset|\bdocker|\bdeploy|compose\b|ansible|\bhelm\b|"
                           r"\bsetup\b|\bkubernetes\b|\binstaller\b")),
    ("audio", re.compile(r"(?i)\bsounds?\b|\bmusic\b|\baudio\b|\bvoice")),
    ("tools", re.compile(r"(?i)\btool|editor|viewer|\bcms\b|\bapi\b|armory|\bstats\b|backup|registration|\badmin|"
                         r"launcher|parser|converter|discord|telegram|monitor|\bstatus\b|database[ _-]?editor|\bweb\b|\bsite\b|\bmcp\b")),
]
TYPE_PHRASE = {"addon": "An addon", "module": "A realm module", "lua": "Lua scripts for realms", "core": "A server core",
               "tool": "A tool", "preset": "A ready-made realm setup", "other": "A project"}
CORE_PHRASE = {"3.3.5a": "AzerothCore, TrinityCore or CMaNGOS realms", "1.12": "1.12.1 realms", "2.4.3": "2.4.3 realms",
               "4.3.4": "4.3.4 realms", "5.4.8": "5.4.8 realms"}

# ------------------------------------------------------------------------------------------- licences
LICENCE_FILE = re.compile(r"^(?:licen[cs]e|copying|unlicense)(?:[._-][A-Za-z0-9.-]+)?(?:\.(?:md|txt|rst))?$", re.I)


def classify_licence(text: str) -> str | None:
    """An SPDX id (GitHub's spelling) for a licence file's text, "NONFREE" for non-commercial or no-derivatives
    terms, or None when it isn't recognised."""
    t = re.sub(r"\s+", " ", text.lower())
    head = re.sub(r"[#*=_-]+", " ", t[:400])
    if "affero general public license" in head:
        return "AGPL-3.0"
    if "lesser general public license" in head or "library general public license" in head:
        return "LGPL-3.0" if "version 3" in head else "LGPL-2.1" if "version 2.1" in head else None
    if "general public license" in head:
        return "GPL-3.0" if "version 3" in head else "GPL-2.0" if "version 2" in head else None
    if "general public license" in t:
        m = re.search(r"gnu (affero |lesser )?general public license,? (?:as published by the free software "
                      r"foundation,? )?(?:either )?version ([23](?:\.1)?)", t)
        if not m:
            return None
        kind, ver = m.group(1) or "", m.group(2)
        if kind.startswith("affero"):
            return "AGPL-3.0"
        if kind.startswith("lesser"):
            return "LGPL-3.0" if ver == "3" else "LGPL-2.1"
        return "GPL-3.0" if ver == "3" else "GPL-2.0"
    if "mozilla public license" in t and "2.0" in t:
        return "MPL-2.0"
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "free and unencumbered software released into the public domain" in t:
        return "Unlicense"
    if "noncommercial" in t or "non-commercial" in t or "noderivatives" in t or "no derivatives" in t:
        return "NONFREE"
    if "cc0 1.0 universal" in t or "creative commons zero" in t:
        return "CC0-1.0"
    if "attribution-sharealike 4.0" in t:
        return "CC-BY-SA-4.0"
    if "attribution 4.0 international" in t:
        return "CC-BY-4.0"
    if "permission is hereby granted, free of charge" in t:
        return "MIT"
    if "redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause" if ("neither the name" in t or "endorse or promote" in t) else "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t \
            or "permission to use, copy, modify, and distribute this software for any purpose" in t:
        return "ISC"
    if "altered source versions must be plainly marked" in t:
        return "Zlib"
    if "do what the fuck you want to" in t:
        return "WTFPL"
    if "boost software license" in t:
        return "BSL-1.0"
    return None


def spdx(v) -> str:
    """A forge's licence id as one of ours ("" for none or unknown)."""
    if not isinstance(v, str):
        return ""
    v = v.strip()
    alias = {"GPL-2.0+": "GPL-2.0-or-later", "GPL-3.0+": "GPL-3.0-or-later", "LGPL-2.1+": "LGPL-2.1-or-later",
             "MIT License": "MIT", "Apache License 2.0": "Apache-2.0", "The Unlicense": "Unlicense"}
    v = alias.get(v, v)
    return v if v in H.OPEN_LICENCES else ""


# ------------------------------------------------------------------------------------------- forge APIs
class Api:
    """GitHub, GitLab and Codeberg REST calls. ok() is False when GitHub's API can't be reached at all (no
    network, a proxy that refuses it): the build then runs on git alone and the pool's last-known metadata."""

    def __init__(self, token: str | None = None, timeout: float = 20.0, opener=None, sleep=time.sleep):
        self.token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleep
        self._ok = None
        self.calls = 0
        self.limited = False          # GitHub said we are out of API calls: no more GitHub calls this run
        self.lock = __import__("threading").Lock()

    def get(self, url: str, accept: str = "application/vnd.github+json"):
        """(status, decoded JSON or None, headers). One retry after a short wait for a 5xx or a dropped connection.
        Once GitHub answers that the rate limit is used up (403/429 with X-RateLimit-Remaining: 0 or Retry-After),
        every later GitHub call answers (429, None, {}) at once, and the build keeps last-known values."""
        gh = url.startswith("https://api.github.com/")
        headers = {"Accept": accept, "User-Agent": "leyline-hub-index"}
        if self.token and gh:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in (1, 2):
            if gh and self.limited:
                return 429, None, {}
            with self.lock:
                self.calls += 1
            try:
                with self.opener(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    return r.status, json.loads(r.read(8_000_000).decode("utf-8")), dict(r.headers)
            except urllib.error.HTTPError as e:
                hdr = dict(e.headers or {})
                low = {k.lower(): v for k, v in hdr.items()}
                if gh and e.code in (403, 429) and (low.get("x-ratelimit-remaining") == "0" or "retry-after" in low):
                    if not self.limited:
                        log(f"  GitHub's API rate limit is used up (HTTP {e.code}): last-known values are kept from here on")
                    self.limited = True
                    return e.code, None, hdr
                if e.code >= 500 and attempt == 1:
                    self.sleep(3)
                    continue
                return e.code, None, hdr
            except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError):
                if attempt == 1:
                    self.sleep(3)
                    continue
                return 0, None, {}
        return 0, None, {}

    def ok(self) -> bool:
        if self._ok is None:
            st, doc, _ = self.get("https://api.github.com/repos/azerothcore/azerothcore-wotlk")
            self._ok = st == 200 and isinstance(doc, dict) and doc.get("full_name") is not None
        return self._ok

    def github_repo(self, owner: str, repo: str) -> dict | None:
        st, d, _ = self.get(f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}")
        if st in (404, 451):
            return {"missing": True}
        return gh_meta(d) if st == 200 and isinstance(d, dict) else None

    def github_release(self, owner: str, repo: str) -> dict | None:
        """The latest release ({tag, date, url}: its page on GitHub), {} when the repo has none, None when the API
        didn't answer (keep what we had)."""
        st, d, _ = self.get(f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases/latest")
        if st == 404:
            return {}
        if st != 200 or not isinstance(d, dict):
            return None
        return release_meta(d, f"https://github.com/{owner}/{repo}")

    def search(self, q: str, pages: int, sleep=time.sleep) -> list[dict]:
        out = []
        for page in range(1, pages + 1):
            url = ("https://api.github.com/search/repositories?" +
                   urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 100, "page": page}))
            st, d, hdr = self.get(url)
            sleep(2.2 if self.token else 6.5)                            # 30 / 10 searches a minute
            if st != 200 or not isinstance(d, dict):
                log(f"  search {q!r} page {page}: HTTP {st}")
                break
            items = d.get("items") or []
            out += [gh_meta(i) for i in items if isinstance(i, dict)]
            if len(items) < 100:
                break
        return [m for m in out if m]

    def code_search(self, q: str, sleep=time.sleep) -> list[str]:
        """Repo URLs whose files match (needs a token; any failure gives [])."""
        if not self.token:
            return []
        url = "https://api.github.com/search/code?" + urllib.parse.urlencode({"q": q, "per_page": 100})
        st, d, _ = self.get(url)
        sleep(6.5)
        if st != 200 or not isinstance(d, dict):
            log(f"  code search {q!r}: HTTP {st}")
            return []
        return sorted({i["repository"]["html_url"] for i in d.get("items") or []
                       if isinstance(i, dict) and isinstance(i.get("repository"), dict) and i["repository"].get("html_url")})

    def codeberg_search(self, q: str) -> list[dict]:
        st, d, _ = self.get("https://codeberg.org/api/v1/repos/search?" +
                            urllib.parse.urlencode({"q": q, "topic": "true", "limit": 50}), "application/json")
        items = d.get("data") if isinstance(d, dict) else None
        return [gitea_meta(i) for i in items or [] if isinstance(i, dict)] if st == 200 else []

    def gitlab_search(self, topic: str) -> list[dict]:
        st, d, _ = self.get("https://gitlab.com/api/v4/projects?" + urllib.parse.urlencode(
            {"topic": topic, "per_page": 100, "order_by": "star_count", "sort": "desc", "visibility": "public"}),
            "application/json")
        return [gitlab_meta(i) for i in d or [] if isinstance(i, dict)] if st == 200 and isinstance(d, list) else []

    def gitlab_licence(self, path: str) -> str:
        st, d, _ = self.get(f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(path, safe='')}?license=true",
                            "application/json")
        lic = (d or {}).get("license") if st == 200 and isinstance(d, dict) else None
        return spdx((lic or {}).get("key", "").upper().replace("APACHE-2.0", "Apache-2.0").replace("UNLICENSE", "Unlicense")) \
            if isinstance(lic, dict) else ""

    def issues(self, slug: str) -> list[dict]:
        """Approved submission issues (labels mod-submission and approved) of a public repo."""
        st, d, _ = self.get(f"https://api.github.com/repos/{slug}/issues?" + urllib.parse.urlencode(
            {"labels": "mod-submission,approved", "state": "all", "per_page": 100}))
        return d if st == 200 and isinstance(d, list) else []


def _num(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def gh_meta(d) -> dict | None:
    if not isinstance(d, dict) or not isinstance(d.get("html_url"), str):
        return None
    lic = d.get("license") if isinstance(d.get("license"), dict) else {}
    return {"repo": d["html_url"], "stars": _num(d.get("stargazers_count")), "licence": spdx(lic.get("spdx_id")),
            "licence_raw": lic.get("spdx_id") or "", "description": d.get("description") or "",
            "topics": sorted(t for t in d.get("topics") or [] if isinstance(t, str)), "archived": bool(d.get("archived")),
            "fork": bool(d.get("fork")), "pushed": (d.get("pushed_at") or "")[:10], "private": bool(d.get("private"))}


def release_meta(d: dict, repo_url: str) -> dict:
    """{tag, date, url} of a GitHub release document, {} when it isn't a usable one (a draft, odd text, a page off
    the repo)."""
    tag = d.get("tag_name") if isinstance(d.get("tag_name"), str) else ""
    url = d.get("html_url") if isinstance(d.get("html_url"), str) else ""
    if d.get("draft") or not tag:
        return {}
    tag = H.clean_line(tag, 40)
    rel = {"tag": tag, "date": (d.get("published_at") or d.get("created_at") or "")[:10], "url": url}
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rel["date"]):
        rel["date"] = ""
    return rel if tag and not H.release_problem(rel, repo_url) else {}


def gitea_meta(d) -> dict | None:
    if not isinstance(d, dict) or not isinstance(d.get("html_url"), str):
        return None
    lics = d.get("licenses") if isinstance(d.get("licenses"), list) else []
    return {"repo": d["html_url"], "stars": _num(d.get("stars_count")), "licence": spdx(lics[0]) if lics else "",
            "licence_raw": lics[0] if lics else "", "description": d.get("description") or "",
            "topics": sorted(t for t in d.get("topics") or [] if isinstance(t, str)), "archived": bool(d.get("archived")),
            "fork": bool(d.get("fork")), "pushed": (d.get("updated_at") or "")[:10], "private": bool(d.get("private"))}


def gitlab_meta(d) -> dict | None:
    if not isinstance(d, dict) or not isinstance(d.get("web_url"), str):
        return None
    return {"repo": d["web_url"], "stars": _num(d.get("star_count")), "licence": "", "licence_raw": "",
            "description": d.get("description") or "", "topics": sorted(t for t in d.get("topics") or [] if isinstance(t, str)),
            "archived": bool(d.get("archived")), "fork": bool(d.get("forked_from_project")),
            "pushed": (d.get("last_activity_at") or "")[:10], "private": d.get("visibility") not in (None, "public"),
            "path": d.get("path_with_namespace") or ""}


# ------------------------------------------------------------------------------------------- discover
GITHUB_QUERIES = [
    ("topic:azerothcore-module", "3.3.5a"), ("topic:azerothcore-lua", "3.3.5a"), ("topic:azerothcore-tools", "3.3.5a"),
    ("topic:azerothcore", "3.3.5a"), ("topic:eluna", ""), ("topic:trinitycore", ""), ("topic:cmangos", ""),
    ("topic:mangos", ""), ("topic:vmangos", "1.12"), ("topic:wotlk", "3.3.5a"), ("topic:wotlk-addon", "3.3.5a"),
    ("topic:tbc", "2.4.3"), ("topic:vanilla-wow", "1.12"), ("topic:vanilla-addons", "1.12"), ("topic:turtle-wow", "1.12"),
    ("topic:cata", "4.3.4"), ("topic:cataclysm", "4.3.4"), ("topic:mop", "5.4.8"), ("topic:skyfire", "5.4.8"),
    ("topic:wow-addon", ""), ("topic:wow-addons", ""), ("topic:world-of-warcraft-addon", ""),
    ("3.3.5a in:name,description", "3.3.5a"), ("1.12.1 in:name,description", "1.12"), ("2.4.3 in:name,description", "2.4.3"),
    ("4.3.4 in:name,description", "4.3.4"), ("5.4.8 in:name,description", "5.4.8"),
]
CODE_QUERIES = [(f'"## Interface: {n}" extension:toc', b) for n, b in sorted(H.INTERFACE.items())]
CODEBERG_QUERIES = [("azerothcore", "3.3.5a"), ("eluna", ""), ("wow-addon", ""), ("vmangos", "1.12"), ("cmangos", ""),
                    ("trinitycore", ""), ("wotlk", "3.3.5a"), ("vanilla-wow", "1.12")]
GITLAB_TOPICS = [("azerothcore", "3.3.5a"), ("eluna", ""), ("wow-addon", ""), ("trinitycore", ""), ("cmangos", ""),
                 ("vmangos", "1.12")]


def merge_candidate(pool: dict, meta: dict, via: str, build: str) -> None:
    c = H.canonical(meta.get("repo", ""))
    if not c or meta.get("private") or meta.get("fork"):
        return
    rec = pool.setdefault(c["key"], {"repo": c["url"], "via": [], "builds": []})
    if via not in rec["via"]:
        rec["via"] = sorted(rec["via"] + [via])
    if build and build not in rec["builds"]:
        rec["builds"] = sorted(rec["builds"] + [build], key=H._build_order)
    for k in ("stars", "licence", "description", "topics", "archived", "pushed"):
        if meta.get(k) not in (None, "", []):
            rec[k] = meta[k]


def discover(api: Api, max_pages: int, sleep=time.sleep) -> int:
    doc = read_json(CANDIDATES, {"format": 1, "candidates": []})
    pool = {H.canonical(r["repo"])["key"]: r for r in doc.get("candidates", []) if H.canonical(r.get("repo", ""))}
    before = len(pool)
    for q, b in GITHUB_QUERIES:
        hits = api.search(q + " stars:>=2 fork:false", max_pages, sleep=sleep)
        log(f"  github {q!r}: {len(hits)}")
        for m in hits:
            merge_candidate(pool, m, "github:" + q, b)
    for q, b in CODE_QUERIES:
        for url in api.code_search(q, sleep=sleep):
            merge_candidate(pool, {"repo": url}, "code:" + q, b)
    for q, b in CODEBERG_QUERIES:
        for m in api.codeberg_search(q):
            merge_candidate(pool, m, "codeberg:" + q, b)
    for t, b in GITLAB_TOPICS:
        for m in api.gitlab_search(t):
            if m.get("stars", 0) and m["stars"] >= MIN_STARS and m.get("path"):
                m["licence"] = api.gitlab_licence(m["path"])
            merge_candidate(pool, m, "gitlab:" + t, b)
    doc = {"format": 1, "note": doc.get("note", "The discovered pool. hub_index.py discover adds to it."),
           "candidates": sorted(pool.values(), key=lambda r: r["repo"].lower())}
    write_json(CANDIDATES, doc)
    log(f"discover: {len(pool) - before} new candidates, {len(pool)} in the pool")
    return 0


# ------------------------------------------------------------------------------------------- submissions
def read_approved(src: str, opener=urllib.request.urlopen) -> dict:
    """The portal's approved.json (a file path or an https URL): {approved: [...], delisted: [...]}."""
    if not src:
        return {"approved": [], "delisted": []}
    try:
        if src.startswith("https://"):
            with opener(urllib.request.Request(src, headers={"User-Agent": "leyline-hub-index"}), timeout=20) as r:
                doc = json.loads(r.read(4_000_000).decode("utf-8"))
        else:
            doc = read_json(src, None)
    except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as e:
        log(f"approved submissions: could not read {src}: {type(e).__name__} (none merged this run)")
        return {"approved": [], "delisted": []}
    if not isinstance(doc, dict):
        return {"approved": [], "delisted": []}
    ok = lambda r: isinstance(r, dict) and H.canonical(r.get("repo", ""))  # noqa: E731
    return {"approved": [r for r in doc.get("approved") or [] if ok(r)],
            "delisted": [r for r in doc.get("delisted") or [] if ok(r)]}


ISSUE_FIELDS = {"repo link": "repo", "client build": "build", "category": "category"}


def parse_issue(body: str) -> dict:
    """The fields of a submit-mod issue form ("### Repo link\\n\\nhttps://...")."""
    out = {}
    for m in re.finditer(r"(?m)^###\s+(.+?)\s*$\n+(.*?)(?=^###\s|\Z)", body or "", re.S):
        k = ISSUE_FIELDS.get(m.group(1).strip().lower())
        if k:
            out[k] = m.group(2).strip().splitlines()[0].strip() if m.group(2).strip() else ""
    names = {n.lower(): c for c, n in H.CATEGORIES}
    if "category" in out:
        out["category"] = names.get(out["category"].lower(), out["category"] if out["category"] in H.CATEGORY_IDS else "")
    if "build" in out:
        out["build"] = H.build_tag(out["build"].split()[0] if out["build"] else "")
    return out


# ------------------------------------------------------------------------------------------- probe
def git(*args, cwd=None, timeout=180) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true", GIT_LFS_SKIP_SMUDGE="1")
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    if r.returncode != 0:
        raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["git failed"])[-1][:200])
    return r.stdout


def parse_toc(text: str) -> dict:
    out = {}
    for line in text.splitlines()[:60]:
        m = re.match(r"\s*##\s*([A-Za-z-]+)\s*:\s*(.*)$", line)
        if m:
            out.setdefault(m.group(1).lower(), m.group(2).strip())
    return out


def probe(url: str, cache: dict, git_fn=git) -> dict:
    """What the repo's files say: {ok, head, updated, files_n, licence, licence_file, readme, tocs, game_data,
    binaries, decomp_files, cpp, lua, conf_dist, cmake, docker, error}. Cached by HEAD commit."""
    try:
        head = git_fn("ls-remote", url, "HEAD", timeout=60).split()[0:1]
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "error": str(e)[:160]}
    head = head[0] if head else ""
    hit = cache.get(url)
    if hit and hit.get("head") == head and hit.get("v") == PROBE_VERSION and hit.get("ok"):
        return hit
    out = {"ok": False, "v": PROBE_VERSION, "head": head, "error": ""}
    tmp = tempfile.mkdtemp(prefix="hubidx-")
    r = os.path.join(tmp, "r")
    try:
        git_fn("clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout", url, r)
        out["updated"] = git_fn("log", "-1", "--format=%cs", cwd=r).strip()
        files = git_fn("ls-tree", "-r", "--name-only", "HEAD", cwd=r).splitlines()
        out["files_n"] = len(files)
        out["game_data"] = sorted(f for f in files if GAME_DATA_EXT.search(f))[:5]
        out["binaries"] = sorted(f for f in files if BINARY_EXT.search(f) and not DEP_DIR.search(f))[:5]
        out["decomp_files"] = sorted(f for f in files if DECOMP_FILE.search(f))[:5]
        out["cpp"] = sum(1 for f in files if re.search(r"\.(cpp|cc|h|hpp)$", f, re.I))
        out["lua"] = sum(1 for f in files if f.lower().endswith(".lua"))
        out["conf_dist"] = any(re.search(r"(^|/)conf/[^/]+\.conf\.dist$", f) for f in files)
        out["cmake"] = "CMakeLists.txt" in files
        out["core_dirs"] = any(re.match(r"src/(server|game)/", f) for f in files)
        out["docker"] = any(re.search(r"(^|/)(docker-compose[^/]*\.ya?ml|compose\.ya?ml|Dockerfile)$", f) for f in files)
        out["licence"], out["licence_file"] = "", ""
        root = [f for f in files if "/" not in f]
        for f in sorted(root, key=lambda x: (len(x), x)):
            if LICENCE_FILE.match(f):
                lic = classify_licence(git_fn("show", f"HEAD:{f}", cwd=r)[:200_000])
                out["licence_file"] = f
                if lic:
                    out["licence"] = lic
                    break
        readme = next((f for f in sorted(root) if re.match(r"(?i)^readme(\.(md|txt|rst|markdown))?$", f)), None)
        out["readme"] = git_fn("show", f"HEAD:{readme}", cwd=r)[:60_000] if readme else ""
        tocs = sorted((f for f in files if f.lower().endswith(".toc") and f.count("/") <= 2
                       and not re.search(r"(?i)(^|/)libs?/", f)), key=lambda x: (x.count("/"), x))
        if tocs:                                  # the addon's own TOCs: the shallowest level only (not bundled ones)
            top = tocs[0].count("/")
            tocs = [f for f in tocs if f.count("/") == top][:8]
        out["tocs"] = []
        for f in tocs:
            t = parse_toc(git_fn("show", f"HEAD:{f}", cwd=r)[:20_000])
            out["tocs"].append({"file": f, "interface": t.get("interface", ""), "title": t.get("title", ""),
                                "author": t.get("author", "")})
        out["ok"] = True
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
        out["error"] = str(e)[:160]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ------------------------------------------------------------------------------------------- judge
def detect_builds(cand: dict, facts: dict, meta: dict) -> tuple[list[str], str]:
    """(builds, why) — builds [] when none of ours. Addon TOCs decide for addons."""
    tocs = [t for t in facts.get("tocs") or [] if t.get("interface")]
    if tocs:
        ifs = sorted({re.split(r"[ ,]", t["interface"])[0] for t in tocs})
        got = sorted({H.INTERFACE[i] for t in tocs for i in re.split(r"[ ,]+", t["interface"]) if i in H.INTERFACE},
                     key=H._build_order)
        return (got, "toc") if got else ([], "addon for another client build (Interface " + ", ".join(ifs) + ")")
    text = " ".join([cand.get("name_raw", ""), meta.get("description", ""), " ".join(meta.get("topics") or [])])
    readme = facts.get("readme", "")[:20_000]
    via = " ".join((cand.get("pool") or {}).get("via") or [])
    if "azerothcore" in (text + " " + cand["url"] + " " + via).lower() \
            or (facts.get("conf_dist") and cand.get("name_raw", "").lower().startswith("mod")):
        return ["3.3.5a"], "azerothcore"
    if "vmangos" in (text + " " + via).lower():
        return ["1.12"], "vmangos"
    strong = sorted({b for b, rx in STRONG_BUILD.items() if rx.search(text.lower()) or rx.search(readme.lower())},
                    key=H._build_order)
    if strong:
        return strong, "version"
    weak = sorted({b for b, rx in WEAK_BUILD.items() if rx.search(text)}, key=H._build_order)
    if weak:
        return weak, "name"
    hint = [b for b in cand.get("hint_builds") or [] if b in H.BUILDS or b == "any"]
    if hint:
        return sorted(set(hint), key=H._build_order), "hint"
    return [], "no sign of a supported client build"


def detect_type(cand: dict, facts: dict, meta: dict) -> str:
    if cand.get("type") in H.TYPES:
        return cand["type"]
    if any(t.get("interface") for t in facts.get("tocs") or []):
        return "addon"
    name = cand.get("name_raw", "").lower()
    if facts.get("conf_dist") or (facts.get("cpp") and name.startswith("mod-")) or "azerothcore-module" in (meta.get("topics") or []):
        return "module"
    if facts.get("cmake") and facts.get("core_dirs") and facts.get("cpp", 0) > 200:
        return "core"
    if facts.get("lua", 0) >= 1 and not facts.get("cpp") and not facts.get("tocs"):
        return "lua"
    if facts.get("docker") and facts.get("files_n", 0) < 80 and not facts.get("cpp") \
            and re.search(r"(?i)docker|deploy|compose|ansible|helm|setup|install", cand.get("name_raw", "") + " " + meta.get("description", "")):
        return "preset"
    return "tool"


def detect_category(cand: dict, typ: str, meta: dict) -> str:
    if cand.get("category") in H.CATEGORY_IDS:
        return cand["category"]
    text = " ".join([cand.get("name_raw", "").replace("-", " ").replace("_", " "), meta.get("description", ""),
                     " ".join(meta.get("topics") or [])])
    if typ == "addon":
        return "audio" if CAT_RULES[3][1].search(text) else "addons"
    if typ in ("core", "preset"):
        return "presets"
    for cat, rx in CAT_RULES:
        if cat == "tools" and typ in ("module", "lua"):
            continue
        if rx.search(text):
            return cat
    return "tools" if typ == "tool" else "realm-scripts"


ACRONYMS = {"llm": "LLM", "npc": "NPC", "npcs": "NPCs", "pbc": "PBC", "xp": "XP", "ai": "AI", "bg": "BG", "lfg": "LFG",
            "aoe": "AoE", "rdf": "RDF", "pvp": "PvP", "pve": "PvE", "gm": "GM", "ui": "UI", "api": "API", "db": "DB",
            "dk": "DK", "ah": "AH", "cms": "CMS", "mcp": "MCP", "tc": "TC", "tbc": "TBC", "srp6": "SRP6", "dps": "DPS"}
GENERIC = {"core", "server", "scripts", "addons", "addon", "modules", "module", "tools", "emulator", "trinitycore",
           "mangos", "project", "source", "src", "repo"}


def humanize(name: str) -> str:
    """'mod-improved-bank' -> 'Improved Bank', 'mod-llm-guide' -> 'LLM Guide'."""
    name = re.sub(r"^(mod|module)[-_]", "", name, flags=re.I)
    words = [w for w in re.split(r"[-_ ]+", name) if w]
    return " ".join(ACRONYMS.get(w.lower(), w if (w[:1].isupper() or any(c.isdigit() for c in w)) else w.capitalize())
                    for w in words)


def display_name(cand: dict, facts: dict) -> str:
    """The curated name, else the repo's own name: AzerothCore-style "mod-..." names made readable, a generic one
    ("core") with its owner in front, and when brand words had to come out, the addon's TOC title (cleaned) or the
    rest made readable ("wow-sounds" -> "Sounds")."""
    if cand.get("name"):
        return H.clean_name(cand["name"])
    raw = cand.get("name_raw", "")
    name = H.clean_name(raw)
    if re.match(r"(?i)^mod[-_]", raw) and name == raw:
        return H.clean_line(humanize(raw), 64)
    if name.lower() in GENERIC:
        return H.clean_line(f"{cand['owner'].split('/')[-1]} {name}", 64)
    if name == raw:
        return name
    titles = sorted({H.clean_name(t["title"]) for t in facts.get("tocs") or [] if t.get("title")} - {""})
    if len(titles) == 1 and len(titles[0]) >= 3:
        return titles[0]
    return H.clean_line(humanize(name), 64)


def summary_line(typ: str, builds: list[str], needs: str) -> str:
    labels = [H.BUILD_LABEL[b] for b in builds if b in H.BUILD_LABEL]
    on = "every build" if builds == ["any"] else (", ".join(labels[:-1]) + " and " + labels[-1] if len(labels) > 1 else labels[0])
    if typ == "core":
        return f"An open server core for {on} realms."
    if typ == "module":
        return f"A realm module for {needs or 'AzerothCore'} ({on})."
    if typ == "lua":
        return f"Lua scripts for {on} realms" + (f", on {needs}." if needs else ".")
    if typ == "addon":
        return f"An addon for the {on} client."
    if typ == "preset":
        return f"A ready-made realm setup for {on}."
    return f"A tool for {on} modders and realm hosts."


def judge(cand: dict, facts: dict, meta: dict, block: dict) -> dict:
    """{verdict: listed | needs_licence | review | excluded, reason, entry?}"""
    url, key = cand["url"], cand["key"]
    owner = cand["owner"]
    text = " ".join([cand.get("name_raw", ""), meta.get("description", ""), " ".join(meta.get("topics") or [])])
    readme = facts.get("readme", "")
    for b in block.get("repos", []):
        if b["repo"].lower() == key:
            return {"verdict": "excluded", "reason": b["reason"]}
    for b in block.get("owners", []):
        if b["owner"].lower() == owner.lower().split("/")[0]:
            return {"verdict": "excluded", "reason": b["reason"]}
    for b in block.get("patterns", []):
        if re.search(b["pattern"], key + " " + text, re.I):
            return {"verdict": "excluded", "reason": b["reason"]}
    for b in block.get("review", []):
        if b["repo"].lower() == key:
            return {"verdict": "review", "reason": b["reason"]}
    if "chumpton" in (key + " " + text + " " + readme).lower():
        return {"verdict": "excluded", "reason": "the Chumpton account (never listed)"}
    if DECOMP_RE.search(key + " " + text) or DECOMP_README.search(readme) or facts.get("decomp_files"):
        return {"verdict": "excluded", "reason": "decompiled code, or derived from wowdecomp/Waystone"}
    if meta.get("missing"):
        return {"verdict": "excluded", "reason": "the repo is gone"}
    if not facts.get("ok"):
        return {"verdict": "excluded", "reason": "could not read the repo: " + (facts.get("error") or "?")}
    if facts.get("game_data"):
        return {"verdict": "excluded", "reason": "ships game-format files: " + ", ".join(facts["game_data"][:3])}
    if facts.get("binaries"):
        return {"verdict": "excluded", "reason": "ships binaries or archives (we only link source): "
                + ", ".join(facts["binaries"][:3])}
    if REPACK_RE.search(text):
        return {"verdict": "excluded", "reason": "a repack, client patch or client download"}
    if CHEAT_RE.search(text):
        return {"verdict": "excluded", "reason": "a bot, cheat or exploit for other people's realms"}
    if MONEY_RE.search(text):
        return {"verdict": "excluded", "reason": "built to sell things (shop, VIP, donations or payments)"}
    if PAID_STRONG.search(readme):
        return {"verdict": "excluded", "reason": "a paid or paywalled version (README)"}
    if OTHER_GAME_RE.search(text):
        return {"verdict": "excluded", "reason": "made for the current game, not a classic client"}
    builds, why = detect_builds(cand, facts, meta)
    if cand.get("builds_given"):
        given = [b for b in cand["builds_given"] if b in H.BUILDS or b == "any"]
        if why == "toc" and given and "any" not in given:
            inter = sorted(set(given) & set(builds), key=H._build_order)
            if not inter:
                return {"verdict": "review", "reason": f"listed for {', '.join(given)} but its TOC says {', '.join(builds)}"}
            builds = inter
        if why != "toc" and given:
            builds = sorted(set(given), key=H._build_order)
            why = "given"
    hint = [b for b in cand.get("hint_builds") or [] if b in H.BUILDS]
    conflict = why == "toc" and cand["origin"] == "discovered" and hint and not set(hint) & set(builds)
    if why in ("name", "hint") and not GAME_SIGNAL.search(text + " " + readme[:20_000]):
        return {"verdict": "excluded", "reason": "nothing says it is for the game (a name match only)"}
    if not builds:
        return {"verdict": "excluded", "reason": why}
    typ = detect_type(cand, facts, meta)
    licence = meta.get("licence") or ""
    if not licence:
        fl = facts.get("licence") or ""
        if fl == "NONFREE":
            return {"verdict": "excluded", "reason": "licence is not open (non-commercial or no-derivatives terms)"}
        licence = fl if fl in H.OPEN_LICENCES else ""
    stars = meta.get("stars")
    if cand["origin"] == "discovered" and (stars is None or stars < MIN_STARS):
        return {"verdict": "excluded", "reason": f"below the bar for discovered projects ({stars or 0} stars)"}
    name = display_name(cand, facts)
    author = cand.get("author") or owner.split("/")[-1]
    if not licence:
        return {"verdict": "needs_licence", "reason": "no open licence file" + (f" ({facts.get('licence_file')})"
                                                                              if facts.get("licence_file") else ""),
                "name": name, "builds": builds}
    if conflict:
        return {"verdict": "review", "reason": f"its TOC says {', '.join(builds)} but it was found under {', '.join(hint)}"}
    if H.banned(author):
        return {"verdict": "review", "reason": "the author's name carries a brand word (credit can't be shown cleanly)"}
    if not name or len(name) < 2:
        return {"verdict": "review", "reason": "no usable display name once brand words are taken out"}
    if DECOMP_TOOLS.search(readme):
        return {"verdict": "review", "reason": "README mentions decompiler tools: check nothing in it is decompiled"}
    soft = sorted({m.group(0).lower() for m in PAID_SOFT.finditer(readme)})
    if soft and cand["origin"] == "discovered":
        return {"verdict": "review", "reason": "README mentions " + ", ".join(soft) + ": check nothing is paywalled"}
    category = detect_category(cand, typ, meta)
    needs = cand.get("needs") or ("AzerothCore" if typ == "module" else "")
    desc = H.clean_line(H.scrub(meta.get("description") or ""), 200)
    summary = H.clean_line(cand.get("description") or summary_line(typ, builds, needs), 240)
    if H.banned(summary + " " + desc):
        desc = ""
    entry = {"id": "link:" + cand["id"], "name": name, "author": H.clean_line(author, 60), "owner": owner,
             "repo": url, "forge": cand["forge"], "licence": licence, "category": category, "type": typ,
             "builds": builds, "summary": summary, "description": desc if desc.lower() != summary.lower() else "",
             "stars": stars, "updated": facts.get("updated") or meta.get("pushed") or "",
             "archived": bool(meta.get("archived")), "source": cand["origin"]}
    if needs:
        entry["needs"] = needs
    if isinstance(meta.get("release"), dict) and meta["release"] and not H.release_problem(meta["release"], url):
        entry["release"] = dict(meta["release"])
    return {"verdict": "listed", "entry": entry}


def score(e: dict, ref: datetime.date) -> float:
    s = 10 * math.log10((e.get("stars") or 0) + 1)
    try:
        age = (ref - datetime.date.fromisoformat(e.get("updated", "")[:10])).days
    except ValueError:
        age = 99999
    s += 6 if age < 365 else 3 if age < 3 * 365 else 1 if age < 6 * 365 else 0
    s += {"seed": 5, "submitted": 3}.get(e["source"], 0)
    s += 1 if e.get("description") else 0
    s -= 3 if e.get("archived") else 0
    return round(s, 1)


# ------------------------------------------------------------------------------------------- build
SKIP_RECHECK = re.compile(r"(?i)no licence|game-format|client patch files|licence is not open")
# Reasons that mean "we couldn't look this time", not "it broke a rule": a listed entry is kept as it was.
TRANSIENT = re.compile(r"^could not read the repo")
SHRINK_FLOOR = 0.8                # a run that would drop more than 20% of the entries at once writes nothing


def gather(approved: dict, issues: list[dict], only: list[str]) -> list[dict]:
    """Every candidate once (by canonical key), curated fields from seeds, hints from the pool and submissions."""
    out: dict[str, dict] = {}

    def add(repo, origin, **kw):
        c = H.canonical(repo)
        if not c:
            return None
        rec = out.get(c["key"])
        if rec is None:
            rec = out[c["key"]] = {"url": c["url"], "key": c["key"], "id": c["id"], "forge": c["forge"],
                                   "owner": c["owner"], "name_raw": c["repo"], "origin": origin, "hint_builds": [],
                                   "builds_given": [], "pool": {}}
        rank = {"seed": 0, "submitted": 1, "discovered": 2}
        if rank[origin] < rank[rec["origin"]]:
            rec["origin"] = origin
        for k, v in kw.items():
            if v in (None, "", []):
                continue
            if k in ("hint_builds", "builds_given"):
                rec[k] = sorted(set(rec[k]) | set(v), key=H._build_order)
            elif k == "pool":
                rec["pool"] = v
            elif origin == "seed" or k not in rec:
                rec[k] = v
        return rec

    for s in read_json(SEEDS, {}).get("seeds", []):
        skip = s.get("skip")
        if skip and not SKIP_RECHECK.search(skip):
            add(s["repo"], "seed", skip=skip)
            continue
        add(s["repo"], "seed", category=s.get("category"), type=s.get("type"), name=s.get("name"),
            description=s.get("description"), needs=s.get("needs"), author=s.get("author"),
            builds_given=[H.build_tag(b) for b in (s.get("builds") or [s.get("build") or "3.3.5a"])])
    for r in read_json(CANDIDATES, {}).get("candidates", []):
        add(r.get("repo", ""), "discovered", hint_builds=[H.build_tag(b) for b in r.get("builds") or [] if H.build_tag(b)],
            pool=r)
    for r in approved.get("approved", []):
        add(r["repo"], "submitted", builds_given=[H.build_tag(r.get("build")) or "any"],
            category=r.get("category") or None)
    for i in issues:
        f = parse_issue(i.get("body") or "")
        if f.get("repo") and f.get("build"):
            add(f["repo"], "submitted", builds_given=[f["build"]], category=f.get("category") or None)
    gone = {H.canonical(r["repo"])["key"] for r in approved.get("delisted", [])}
    cands = sorted(out.values(), key=lambda r: r["key"])
    for c in cands:
        if c["key"] in gone:
            c["skip"] = "delisted by an admin"
    if only:
        want = {o.lower().strip("/") for o in only}
        cands = [c for c in cands if c["key"].split("/", 3)[-1] in want or c["key"] in want]
    return cands


def build(jobs: int, approved_src: str, issues_repo: str, only: list[str], report: str, api: Api | None = None,
          probe_fn=probe, allow_shrink: bool = False) -> int:
    api = api or Api()
    api_ok = api.ok()
    log(f"forge API: {'yes' if api_ok else 'no (git only, the pool keeps the last-known metadata)'}")
    approved = read_approved(approved_src)
    issues = api.issues(issues_repo) if (api_ok and issues_repo) else []
    cands = gather(approved, issues, only)
    block = read_json(BLOCKLIST, {})
    cache = read_json(CACHE, {})
    todo = [c for c in cands if not c.get("skip")]
    log(f"probing {len(todo)} repos ({len(cands) - len(todo)} skipped by policy) ...")

    def work(c):
        meta = dict(c.get("pool") or {})
        meta.pop("release", None)
        if api_ok and c["forge"] == "github":
            m = api.github_repo(c["owner"], c["name_raw"])
            if m:
                meta.update({k: v for k, v in m.items() if v not in (None, "") or k in ("archived", "missing")})
                if not m.get("missing") and hasattr(api, "github_release"):
                    rel = api.github_release(c["owner"], c["name_raw"])
                    if rel is not None:
                        meta["release"] = rel             # {} = no release (known); missing = unknown, keep the old one
        return c, meta, probe_fn(c["url"], cache)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for n, (c, meta, facts) in enumerate(ex.map(work, todo), 1):
            results.append((c, meta, facts))
            if facts.get("ok"):
                cache[c["url"]] = facts
            if n % 25 == 0:
                log(f"  {n}/{len(todo)}")
    if not only:
        write_json(CACHE, {k: cache[k] for k in sorted(cache)})

    listed, holding = [], {"needs_licence": [], "review": [], "excluded": []}
    prev = {e["id"]: e for e in read_json(INDEX, {}).get("entries", []) if isinstance(e, dict) and "id" in e}
    kept = []
    for c in cands:
        if c.get("skip"):
            holding["excluded"].append({"repo": c["url"], "reason": c["skip"]})
    for c, meta, facts in results:
        v = judge(c, facts, meta, block)
        if only:
            log(f"  {c['url']}: {v['verdict']} {v.get('reason', '')} {json.dumps(v.get('entry', ''))[:300]}")
        old = prev.get("link:" + c["id"])
        if v["verdict"] == "excluded" and old and TRANSIENT.search(v["reason"]):
            # A forge that didn't answer this run never takes a listed entry off: it stays as it was.
            listed.append(dict(old))
            kept.append(f"{c['url']}: {v['reason']}")
            continue
        if v["verdict"] == "listed":
            if old and "release" not in meta and "release" in old and "release" not in v["entry"]:
                v["entry"]["release"] = old["release"]          # the API didn't answer for it: keep the last-known release
            listed.append(v["entry"])
        elif v["verdict"] == "needs_licence":
            holding["needs_licence"].append({"repo": c["url"], "name": v["name"], "builds": v["builds"], "reason": v["reason"]})
        else:
            holding[v["verdict"]].append({"repo": c["url"], "reason": v["reason"]})
    dates = [e["updated"][:10] for e in listed if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.get("updated", "")[:10])]
    ref = datetime.date.fromisoformat(max(dates)) if dates else datetime.date(2026, 1, 1)
    for e in listed:
        e["score"] = score(e, ref)
    for line in kept:
        log("  kept as it was (the repo didn't answer this run): " + line)
    # dedupe: one entry per display name and build set (mirrors and re-uploads), the best scored wins
    best: dict[tuple, dict] = {}
    for e in sorted(listed, key=lambda e: (-e["score"], e["id"])):
        k = (e["name"].lower(), tuple(e["builds"]))
        if k in best:
            holding["excluded"].append({"repo": e["repo"], "reason": f"same project as {best[k]['repo']}"})
            continue
        best[k] = e
    listed = sorted(best.values(), key=H.entry_order)
    if not only and len(prev) >= 20 and len(listed) < SHRINK_FLOOR * len(prev) and not allow_shrink:
        log(f"REFUSED: the index would shrink from {len(prev)} to {len(listed)} entries (more than "
            f"{round(100 * (1 - SHRINK_FLOOR))}% at once). Nothing written; look at the report, or run with --allow-shrink.")
        print(report_text({"entries": listed}, holding))
        return 3
    if only:
        old = read_json(INDEX, {}).get("entries", [])
        mine = {e["id"] for e in listed}
        probed = {"link:" + c["id"] for c, _, _ in results}
        listed = sorted([e for e in old if e["id"] not in probed] + listed, key=H.entry_order)
        _ = mine
    doc = {"format": 2,
           "policy": ("Link-out only: nothing here is mirrored or hosted. Open licences only; no game data, nothing "
                      "paid, nothing decompiled. Built by tools/hub-index/hub_index.py; a person reviews each update."),
           "builds": H.BUILDS, "categories": H.CATEGORY_IDS, "entries": listed}
    problems = H.validate_index(doc)
    for k in holding:
        holding[k].sort(key=lambda r: r["repo"].lower())
    text = report_text(doc, holding)
    print(text)
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write(text)
    if problems:
        for p in problems:
            log("PROBLEM  " + p)
        return 1
    write_json(INDEX, doc)
    if not only:
        write_json(HOLDING, {"format": 1, **holding})
    return 0


def report_text(doc: dict, holding: dict) -> str:
    es = doc["entries"]
    if not es or "category" not in es[0]:
        return f"Community index: {len(es)} entries\n"
    lines = [f"Community index: {len(es)} entries", "", "By build:"]
    for b in H.BUILDS + ["any"]:
        n = sum(1 for e in es if b in e["builds"])
        if n:
            lines.append(f"  {H.BUILD_LABEL[b]:>9}: {n}")
    lines += ["", "By category:"]
    for c in H.CATEGORY_IDS:
        n = sum(1 for e in es if e["category"] == c)
        if n:
            lines.append(f"  {c:>14}: {n}")
    lines += ["", "By source:"] + [f"  {s:>10}: {sum(1 for e in es if e['source'] == s)}"
                                   for s in ("seed", "discovered", "submitted")]
    lines += ["", f"Holding: {len(holding['needs_licence'])} need a licence, {len(holding['review'])} for review, "
                  f"{len(holding['excluded'])} excluded"]
    for r in holding["review"]:
        lines.append(f"  review  {r['repo']}: {r['reason']}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------- the daily gate
# What may go live without a person: refreshes of entries a person already merged. Everything else waits for review.
REFRESH_FIELDS = ("stars", "updated", "archived", "score", "release")
# Removals that may go live without a person: the entry now breaks a hard rule (or an admin delisted it).
HARD_REMOVE = re.compile(r"(?i)game-format|binaries|decompil|chumpton|repo is gone|repack|client patch|bot, cheat|"
                         r"sell things|paid|licence is not open|no open licence|delisted|left out|another client build|"
                         r"current game")


def gate(base: dict, new: dict, holding: dict) -> tuple[dict, dict]:
    """(the index that may go live now, what waits for a person). base: the index on main (approved); new: this
    run's full build; holding: this run's holding.json (for the reasons entries left).
      * an entry in both: base's entry with REFRESH_FIELDS taken from new (other changes wait: "changed")
      * an entry only in base: removed when its reason is a hard rule (HARD_REMOVE), else kept ("kept")
      * an entry only in new: not added ("new")"""
    reasons = {}
    for k in ("excluded", "review"):
        for r in holding.get(k) or []:
            reasons[str(r.get("repo", "")).lower()] = r.get("reason", "")
    for r in holding.get("needs_licence") or []:
        reasons[str(r.get("repo", "")).lower()] = "no open licence: " + r.get("reason", "")
    b = {e["id"]: e for e in base.get("entries", [])}
    n = {e["id"]: e for e in new.get("entries", [])}
    out, wait = [], {"new": [], "changed": [], "kept": [], "removed": []}
    for i, e in b.items():
        if i in n:
            x = dict(e)
            for k in REFRESH_FIELDS:
                if k in n[i]:
                    x[k] = n[i][k]
                else:
                    x.pop(k, None)
            diff = sorted(k for k in set(e) | set(n[i]) if k not in REFRESH_FIELDS and e.get(k) != n[i].get(k))
            if diff:
                wait["changed"].append({"repo": e["repo"], "name": e["name"], "fields": diff})
            out.append(x)
            continue
        why = reasons.get(e["repo"].lower(), "")
        if why and HARD_REMOVE.search(why):
            wait["removed"].append({"repo": e["repo"], "name": e["name"], "reason": why})
        else:
            out.append(dict(e))
            wait["kept"].append({"repo": e["repo"], "name": e["name"], "reason": why or "not in this run"})
    for i, e in n.items():
        if i not in b:
            wait["new"].append({"repo": e["repo"], "name": e["name"], "builds": e["builds"], "category": e["category"]})
    doc = dict(new)
    doc["entries"] = sorted(out, key=H.entry_order)
    for k in wait:
        wait[k].sort(key=lambda r: r["repo"].lower())
    return doc, wait


def gate_text(wait: dict) -> str:
    lines = ["", "Daily gate: refreshed entries go live; these wait for a person (the review PR):",
             f"  new entries: {len(wait['new'])}", f"  changed beyond a refresh: {len(wait['changed'])}",
             f"  gone this run but kept (not a hard rule): {len(wait['kept'])}",
             f"  taken off now (a hard rule): {len(wait['removed'])}"]
    for r in wait["new"]:
        lines.append(f"  new      {r['repo']} ({r['name']}, {', '.join(r['builds'])}, {r['category']})")
    for r in wait["changed"]:
        lines.append(f"  changed  {r['repo']}: {', '.join(r['fields'])}")
    for r in wait["kept"]:
        lines.append(f"  kept     {r['repo']}: {r['reason']}")
    for r in wait["removed"]:
        lines.append(f"  removed  {r['repo']}: {r['reason']}")
    return "\n".join(lines) + "\n"


def run_gate(base_path: str, full_out: str, summary: str, report: str) -> int:
    """Read the base (main's index) and this run's build (INDEX), write the gated index to INDEX, the full build to
    full_out, and {review: N, ...} to summary."""
    base = read_json(base_path, None)
    new = read_json(INDEX, None)
    if not isinstance(base, dict) or not isinstance(new, dict):
        log("gate: cannot read the base or the new index")
        return 1
    holding = read_json(HOLDING, {})
    doc, wait = gate(base, new, holding)
    problems = H.validate_index(doc)
    if problems:
        for p in problems:
            log("PROBLEM  " + p)
        return 1
    if full_out:
        write_json(full_out, new)
    write_json(INDEX, doc)
    holding["pending_new"] = wait["new"]
    write_json(HOLDING, holding)
    text = gate_text(wait)
    print(text)
    if report:
        with open(report, "a", encoding="utf-8") as f:
            f.write(text)
    if summary:
        write_json(summary, {"review": len(wait["new"]) + len(wait["changed"]) + len(wait["kept"]),
                             **{k: len(v) for k, v in wait.items()}})
    return 0


def check() -> int:
    doc = read_json(INDEX, None)
    if doc is None:
        print(f"cannot read {INDEX}")
        return 1
    problems = H.validate_index(doc)
    for p in problems:
        print("PROBLEM  " + p)
    print(f"{len(doc.get('entries', []))} entries, {len(problems)} problems")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--max-pages", type=int, default=3)
    b = sub.add_parser("build")
    b.add_argument("--jobs", type=int, default=4)
    b.add_argument("--approved", default=os.environ.get("HUB_APPROVED_URL", ""))
    b.add_argument("--issues", default=os.environ.get("HUB_ISSUES_REPO", ""))
    b.add_argument("--only", nargs="*", default=[])
    b.add_argument("--report", default="")
    b.add_argument("--allow-shrink", action="store_true")
    g = sub.add_parser("gate")
    g.add_argument("--base", required=True)
    g.add_argument("--full-out", default="")
    g.add_argument("--summary", default="")
    g.add_argument("--report", default="")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    if a.cmd == "discover":
        api = Api()
        if not api.ok():
            log("discover: GitHub's API is not reachable from here; the pool is unchanged")
            return 0
        return discover(api, a.max_pages)
    if a.cmd == "build":
        return build(a.jobs, a.approved, a.issues, a.only, a.report, allow_shrink=a.allow_shrink)
    if a.cmd == "gate":
        return run_gate(a.base, a.full_out, a.summary, a.report)
    return check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
