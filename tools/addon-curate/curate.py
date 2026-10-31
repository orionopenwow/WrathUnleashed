#!/usr/bin/env python3
"""Curate third-party addons for the Workshop marketplace (all.json source "upstream", mods/SPEC.md "Upstream addons").

An upstream addon is installed by the Leyline launcher straight from its author's own repo (a release asset, or the
commit archive pinned to a 40-hex commit). We never host it, unless its licence is open and it carries no .blp art
(mirror_allowed). This tool finds the exact file to install, runs the launcher's rules over it (launcher/src-tauri/src/upstream-rules.json,
the one list both sides read), records every file's sha256, and writes the result to mods/upstream.json for a person to
review. Only reviewed entries are published (stream/upstream-addons.json, merged into /wrath/mods/all.json by
stream/upstream_addons.py).

    python3 -I tools/addon-curate/curate.py run [--only ID ...] [--scratch DIR]
        Curate every seed in seeds-addons.json (or only these ids): resolve, download, check, hash. New entries are
        pending (review.by empty). An approved entry whose upstream moved on keeps its approved install and gets a
        pending_update with the difference; it stays published as approved until someone approves the update.
    python3 -I tools/addon-curate/curate.py approve ID --by NAME [--notes TEXT] [--works]
        Mark an entry reviewed (and its pending update, if any, promoted). --works records that it was tried on
        Wrath Unleashed. Then publishes.
    python3 -I tools/addon-curate/curate.py unapprove ID
        Back to pending (off the site at the next publish). Then publishes.
    python3 -I tools/addon-curate/curate.py publish
        Write stream/upstream-addons.json: the approved entries in the all.json project shape.
    python3 -I tools/addon-curate/curate.py list
        One line per entry: id, status, licence, files, flags.

For the Admin Console (stream/admin.py): approve_entry(path, id, by, notes, works) and pending_entries(path) do the
same as the commands, without printing.

Network: the GitHub API when it answers (GITHUB_TOKEN / GH_TOKEN used when set), else git over https (ls-remote and a
shallow clone; `git archive` gives the same bytes per file as GitHub's archive/<commit>.zip). Standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# The one rules list, built into the launcher too (upstream.rs include_str!), so the two cannot disagree.
RULES_PATH = os.path.join(ROOT, "launcher", "src-tauri", "src", "upstream-rules.json")
SEEDS_PATH = os.path.join(HERE, "seeds-addons.json")
OUT_PATH = os.path.join(ROOT, "mods", "upstream.json")
PUBLISH_PATH = os.path.join(ROOT, "stream", "upstream-addons.json")
REALM = "Wrath Unleashed"

RULES = json.load(open(RULES_PATH, encoding="utf-8"))
INTERFACE = RULES["interface"]


# ------------------------------------------------------------------------------------------------ the rules
def ext_of(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    i = base.rfind(".")
    return base[i:].lower() if i > 0 else ""


def classify(path: str, blp_ok: bool, head: bytes = b"") -> str:
    """What happens to one file inside an addon folder (path relative to the folder): "install", "skip", "blp"
    (installed only when the entry allows author art) or "refuse: <why>" (the whole entry is refused). The launcher's
    upstream::classify gives the same answer for the same input (launcher/src-tauri/src/upstream-cases.json)."""
    low = path.lower()
    parts = low.split("/")
    base = parts[-1]
    e = ext_of(low)
    if e in RULES["refuse_ext"]:
        return "refuse: " + e + " files are never allowed"
    h = head[:4].hex()
    for magic, what in RULES["refuse_magic"].items():
        if h.startswith(magic):
            return "refuse: " + what + " (by its first bytes)"
    if h in RULES["blp_magic"] and e != RULES["blp_ext"]:
        return "refuse: a renamed .blp texture"
    if any(p in RULES["skip_dirs"] for p in parts[:-1]):
        return "skip"
    if base in RULES["skip_names"] or e in RULES["skip_ext"]:
        return "skip"
    if e == RULES["blp_ext"]:
        return "install" if blp_ok else "blp"
    if e in RULES["install_ext"]:
        return "install"
    return "skip"   # extensionless (LICENSE, README) and anything the client never loads


def name_ok(name: str) -> bool:
    low = name.lower()
    return (bool(re.fullmatch(RULES["name_re"], name)) and low not in RULES["reserved"]
            and not any(low.startswith(p) for p in RULES["reserved_prefix"]) and not name.endswith("."))


def interface_ok(value: str) -> bool:
    """`## Interface:` holds 30300, alone or in a comma list ("30300, 11508")."""
    return INTERFACE in [v.strip() for v in (value or "").replace("\r", "").split(",")]


def stock_art(path: str) -> bool:
    """A texture named like the game's own interface art (UI-*, Interface/..., spell and item icons): a person looks."""
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    tails = {low, base} | {low.split("/", i)[-1] for i in range(1, low.count("/") + 1)}
    return any(re.search(p, t) for p in RULES["stock_art"] for t in tails)


# ------------------------------------------------------------------------------------------------ brand words
BANNED_RE = re.compile(
    r"(?i:world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|wotlk|wrath\s+of\s+the\s+lich\s+king)"
    r"|(?i:(?<![a-z])wow(?![a-z]))|WoW|WOW|(?<![a-z])Wow(?=[A-Z0-9])|(?<=[a-z])Wow(?![a-z])")


def banned(text: str) -> bool:
    return bool(BANNED_RE.search(text or ""))


def clean_name(raw: str) -> str:
    """A display name: TOC colour codes and the game's brand words out, separators tidied. "Skada (WoTLK)" -> "Skada"."""
    s = re.sub(r"\|c[0-9a-fA-F]{8}|\|r|\|T[^|]*\|t", "", raw or "")
    s = BANNED_RE.sub(" ", s)
    s = re.sub(r"\(\s*\)|\[\s*\]", " ", s)
    s = re.sub(r"(?<=[\s_.-])[\s_.-]+|^[\s_.*-]+|[\s_.-]+$", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -_.*")
    return "".join(c for c in s if c.isprintable())[:64]


# ------------------------------------------------------------------------------------------------ licences
LICENCE_FILE_RE = re.compile(r"(?i)^(licen[cs]e|copying|unlicense)([._-][a-z0-9]+)?(\.(md|txt|rst))?$")


def licence_of(text: str) -> str:
    """An SPDX-style id from a licence file's text. The GNU family by its title (the GPL's own text names the LGPL
    further down), the version from the title's lines."""
    t = " ".join((text or "").lower().split())
    if not t:
        return ""
    head = t[:400]
    m = re.search(r"version (\d)(\.\d)?", head)
    v = (m.group(1) + (m.group(2) or ".0")) if m else ""
    gnu = [(t.find(k), spdx) for k, spdx in (("gnu affero general public", "AGPL-"), ("gnu lesser general public", "LGPL-"),
                                              ("gnu library general public", "LGPL-"), ("gnu general public license", "GPL-"))
           if 0 <= t.find(k) < 400]
    if gnu:
        spdx = min(gnu)[1]
        return spdx + (v or {"AGPL-": "3.0", "LGPL-": "2.1", "GPL-": "2.0"}[spdx])
    if "permission is hereby granted, free of charge" in t or "mit license" in head:
        return "MIT"
    if "apache license" in head and "version 2.0" in head:
        return "Apache-2.0"
    if "mozilla public license" in head:
        return "MPL-2.0"
    if "this is free and unencumbered software released into the public domain" in t:
        return "Unlicense"
    if "do what the fuck you want" in t:
        return "WTFPL"
    if "redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause" if "neither the name" in t or "names of its contributors" in t else "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software" in t:
        return "ISC"
    if "creative commons" in head and "cc0" in t:
        return "CC0-1.0"
    if "gnu general public license" in t:
        return "GPL-" + (v or "2.0")
    if "all rights reserved" in t:
        return "All rights reserved"
    return "LicenseRef-custom"


def licence_open(lic: str) -> bool:
    return lic in RULES["open_licences"]


def toc_licence(value: str) -> str:
    v = (value or "").strip().lower()
    for k, s in (("mit", "MIT"), ("gplv3", "GPL-3.0"), ("gpl v3", "GPL-3.0"), ("gplv2", "GPL-2.0"), ("gpl v2", "GPL-2.0"),
                 ("lgpl", "LGPL-2.1"), ("all rights reserved", "All rights reserved"), ("bsd", "BSD")):
        if v.startswith(k) or v == k:
            return s
    return ""


# ------------------------------------------------------------------------------------------------ TOCs
def parse_toc(text: str) -> tuple[dict, list]:
    meta, files = {}, []
    for line in text.splitlines():
        s = line.strip().lstrip("﻿")
        if s.startswith("##"):
            k, sep, v = s[2:].partition(":")
            if sep:
                meta.setdefault(k.strip(), v.strip())
        elif s and not s.startswith("#"):
            files.append(s.replace("\\", "/"))
    return meta, files


def deps_of(meta: dict) -> list[str]:
    out = []
    for k, v in meta.items():
        if k.lower() in ("dependencies", "requireddeps") or re.fullmatch(r"(?i)dep[a-z0-9]*", k) and k.lower() != "deps-optional":
            out += [d.strip() for d in v.split(",") if d.strip()]
    return sorted(set(out))


# ------------------------------------------------------------------------------------------------ an archive
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def files_digest(files: dict) -> str:
    """The digest the launcher checks when an entry carries no full file list: sha256 of the sorted
    "<path>\\0<sha256>\\n" lines."""
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(p.encode("utf-8") + b"\0" + files[p].encode() + b"\n")
    return h.hexdigest()


WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def safe_rel(name: str) -> bool:
    """The launcher's mods::safe_rel: a path Windows can hold, without zip-slip (one bad name refuses the download)."""
    if name.startswith("/") or name[1:2] == ":" or len(name) > 400 or name.count("/") >= 16:
        return False
    for part in name.split("/"):
        if (not part or part in (".", "..") or part.endswith((".", " ")) or len(part) > 128
                or any(ord(c) < 32 or c in ':*?"<>|' for c in part) or part.split(".")[0].lower() in WINDOWS_DEVICES):
            return False
    return True


def read_zip(path: str) -> list[tuple[str, bytes]]:
    """Every file in a zip (directories left out), refusing what the launcher's reader refuses."""
    out, seen, total = [], set(), 0
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > RULES["caps"]["files"] * 2:
            raise ValueError("more than %d files in the archive" % (RULES["caps"]["files"] * 2))
        for i in infos:
            name = i.filename.replace("\\", "/")
            if not safe_rel(name):
                raise ValueError("a file name Leyline cannot install safely: " + name)
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("a symbolic link in the archive: " + name)
            if i.flag_bits & 0x1:
                raise ValueError("an encrypted file in the archive: " + name)
            if name.lower() in seen:
                raise ValueError("two files differ only in case: " + name)
            seen.add(name.lower())
            total += i.file_size
            if total > RULES["caps"]["total"] * 3:
                raise ValueError("the archive unpacks too big")
            out.append((name, zf.read(i)))
    return out


def common_prefix(names: list[str]) -> str:
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) == 1 and all("/" in n for n in names):
        return tops.pop() + "/"
    return ""


def find_addons(rels: dict) -> tuple[dict, dict]:
    """Addon folders in an archive (paths relative to strip_prefix): ({archive dir: installed name}, {name: toc text}).
    A folder D with D.toc for this client, up to two levels deep and not inside another addon; or the archive's root
    when its .toc files are at the top ("root is the addon": the folder is named after the .toc for this client)."""
    tocs = {}
    for p, b in rels.items():
        if p.lower().endswith(".toc"):
            meta, _ = parse_toc(b[:200_000].decode("utf-8", "replace"))
            tocs[p] = (meta, b.decode("utf-8", "replace"))
    folders, texts = {}, {}
    root_tocs = sorted(p for p in tocs if "/" not in p and interface_ok(tocs[p][0].get("Interface", "")))
    if root_tocs:
        # Questie-335.toc beside Questie.toc (00000): the one for this client names the folder.
        name = sorted(root_tocs, key=lambda p: (len(p), p))[0][:-4]
        folders[""] = name
        texts[name] = tocs[name + ".toc"][1]
        return folders, texts
    cands = []
    for p in tocs:
        parts = p.split("/")
        if len(parts) in (2, 3) and parts[-1][:-4] == parts[-2] and interface_ok(tocs[p][0].get("Interface", "")):
            cands.append("/".join(parts[:-1]))
    for d in sorted(cands, key=lambda d: (d.count("/"), d)):
        if any(d.startswith(o + "/") for o in folders):
            continue    # a library's own .toc inside an addon
        folders[d] = d.rsplit("/", 1)[-1]
        texts[folders[d]] = tocs[d + "/" + folders[d] + ".toc"][1]
    return folders, texts


def analyze(names_bytes: list[tuple[str, bytes]], seed: dict) -> dict:
    """Run the rules over one archive. Returns {ok, problem?, strip_prefix, folders, files, skip, blp_files, ...}."""
    names = [n for n, _ in names_bytes]
    prefix = common_prefix(names)
    rels = {n[len(prefix):]: b for n, b in names_bytes}
    out = {"ok": False, "strip_prefix": prefix, "flags": [], "notes": []}
    # Refused anywhere in the archive, even outside the addon folders.
    for p, b in sorted(rels.items()):
        if any(part.lower() in RULES["skip_dirs"] for part in p.split("/")[:-1]):
            continue
        v = classify(p, True, b[:4])
        if v.startswith("refuse"):
            out["problem"] = f"{p}: {v[8:]}"
            return out
    folders, texts = find_addons(rels)
    if not folders:
        ifaces = sorted({parse_toc(b.decode("utf-8", "replace"))[0].get("Interface", "?").strip() for p, b in rels.items()
                         if p.lower().endswith(".toc")})
        out["problem"] = "no addon for this client (" + ("Interface " + ", ".join(ifaces) if ifaces else "no .toc") + ")"
        return out
    for d, name in folders.items():
        if not name_ok(name):
            out["problem"] = f"{name}: not a folder name Leyline installs"
            return out
    files, skip, blp_files, art_flags, sizes = {}, set(), [], [], {}
    for p, b in sorted(rels.items()):
        home = None
        for d in sorted(folders, key=len, reverse=True):
            if d == "" or p.startswith(d + "/"):
                home = d
                break
        if home is None:
            skip.add(p.split("/", 1)[0] + ("/" if "/" in p else ""))
            continue
        inner = p[len(home) + 1:] if home else p
        if home == "" and "/" not in inner and inner.lower().endswith(".toc") and inner[:-4] != folders[""]:
            skip.add(inner)   # the other build's .toc beside ours (pfQuest.toc next to pfQuest-wotlk.toc)
            continue
        v = classify(inner, True, b[:4])
        if v == "skip":
            top = inner.split("/")
            skip.add(folders[home] + "/" + (top[0] + "/" if len(top) > 1 and top[0].lower() in RULES["skip_dirs"] else inner))
            continue
        dest = folders[home] + "/" + inner
        if ext_of(inner) == RULES["blp_ext"]:
            blp_files.append(dest)
            if stock_art(inner):
                art_flags.append(dest)
        files[dest] = sha256_bytes(b)
        sizes[dest] = len(b)
        if len(b) > RULES["caps"]["file"]:
            out["problem"] = f"{dest} is larger than {RULES['caps']['file'] // 1048576} MB"
            return out
    total = sum(sizes.values())
    if len(files) > RULES["caps"]["files"] or total > RULES["caps"]["total"]:
        out["problem"] = f"too big for an addon: {len(files)} files, {total // 1048576} MB"
        return out
    addons, requires_folders, missing = {}, set(), []
    for name, text in sorted(texts.items()):
        meta, listed = parse_toc(text)
        addons[name] = {"interface": meta.get("Interface", "").replace("\r", "").strip(),
                        "title": clean_name(meta.get("Title", "")) or name,
                        "version": clean_name(meta.get("Version", ""))[:40],
                        "author": clean_name(meta.get("Author", ""))[:80],
                        "x_license": meta.get("X-License", "")[:80]}
        for dep in deps_of(meta):
            requires_folders.add(dep)
        for item in listed:
            if name + "/" + item not in files:
                missing.append(name + "/" + item)
    names_set = set(addons)
    requires_folders -= names_set
    out.update(ok=True, folders=folders, files=files, size=total, file_count=len(files),
               skip=sorted(skip)[:200], blp_files=sorted(blp_files), addons=addons,
               needs_folders=sorted(requires_folders))
    if missing:
        libs = [m for m in missing if "/libs/" in m.lower() or "/lib/" in m.lower()]
        out["missing"] = missing[:50]
        if libs and ".pkgmeta" in {p.rsplit("/", 1)[-1].lower() for p in rels}:
            out["ok"] = False
            out["problem"] = ("its libraries are fetched by the packager (.pkgmeta) and are not in the source: "
                              "needs a packaged release (" + ", ".join(libs[:3]) + ")")
            return out
        out["flags"].append(f"the .toc lists {len(missing)} file(s) that are not there (" + ", ".join(missing[:3]) + ")")
    if art_flags:
        out["flags"].append(f"{len(art_flags)} .blp file(s) named like stock interface art: check them ("
                            + ", ".join(art_flags[:4]) + ")")
    if blp_files:
        out["notes"].append(f"{len(blp_files)} .blp texture(s): the author's art, installed from upstream only")
    lic_text, lic_file = "", ""
    # The repo's own licence: at its top, or at the top of one of its addon folders (never a library's or an icon set's).
    tops = {d + "/" for d in folders if d and "/" not in d} | {""}
    for p in sorted(rels, key=lambda p: (p.count("/"), p)):
        base = p.rsplit("/", 1)[-1]
        if LICENCE_FILE_RE.match(base) and p[: len(p) - len(base)] in tops:
            lic_text, lic_file = rels[p][:20000].decode("utf-8", "replace"), p
            break
    out["licence"] = licence_of(lic_text) if lic_file else ""
    out["licence_source"] = lic_file
    if not lic_file:
        for a in addons.values():
            t = toc_licence(a["x_license"])
            if t:
                out["licence"], out["licence_source"] = t, "toc"
                break
    return out


# ------------------------------------------------------------------------------------------------ resolving
def _token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def http_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "leyline-addon-curate"})
    if _token():
        req.add_header("Authorization", "Bearer " + _token())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_download(url: str, dest: str, cap: int, timeout: int = 120) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "leyline-addon-curate"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        got = 0
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            got += len(b)
            if got > cap:
                raise ValueError("download larger than the cap")
            f.write(b)


def pick_asset(assets: list[dict]) -> dict | None:
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    bad = re.compile(r"(?i)classic|retail|vanilla|tbc|bcc|cata|mists|mainline|1\.12|2\.4")
    good = re.compile(r"(?i)wotlk|wrath|3\.3\.5|335|30300")
    pref = [a for a in zips if good.search(a["name"])] or [a for a in zips if not bad.search(a["name"])]
    return pref[0] if len(pref) == 1 or (pref and good.search(pref[0]["name"])) else None


def git(*args, cwd=None, timeout=600) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1")
    r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "advice.detachedHead=false", *args], cwd=cwd,
                       capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode and "could not read Username" in (r.stderr or ""):
        raise RuntimeError("the repository is not there any more (deleted, renamed or private)")
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else "git failed")
    return r.stdout


def commit_archive(owner: str, repo: str, branch: str, work: str) -> tuple[str, str]:
    """(40-hex commit, path of a zip with the same files as https://github.com/<o>/<r>/archive/<commit>.zip)."""
    url = f"https://github.com/{owner}/{repo}"
    clone = os.path.join(work, "clone")
    args = ["clone", "--depth", "1", "--quiet", "--no-tags"] + (["--branch", branch, "--single-branch"] if branch else []) + [url, clone]
    git(*args)
    rev = git("rev-parse", "HEAD", cwd=clone).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", rev):
        raise RuntimeError("no commit id")
    out = os.path.join(work, "archive.zip")
    git("archive", "--format=zip", f"--prefix={repo}-{rev}/", "-o", out, "HEAD", cwd=clone)
    shutil.rmtree(clone, ignore_errors=True)
    return rev, out


def resolve(seed: dict, work: str, fetch=None) -> dict:
    """Where the addon comes from: {from, url, rev, zip, sha256?, tag?}. A release asset when the API answers and the
    release has one zip for this client; else the commit archive."""
    if fetch is not None:
        return fetch(seed, work)
    owner, repo = seed["repo"].split("/")
    notes = []
    try:
        rel = http_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        a = pick_asset(rel.get("assets") or [])
        if a and not rel.get("prerelease") and not rel.get("draft"):
            u = a["browser_download_url"]
            if u.startswith(f"https://github.com/{owner}/{repo}/releases/download/") and a.get("size", 0) <= RULES["caps"]["download"]:
                z = os.path.join(work, "release.zip")
                http_download(u, z, RULES["caps"]["download"])
                return {"from": "release-asset", "url": u, "rev": rel.get("tag_name", ""), "zip": z,
                        "sha256": hashlib.sha256(open(z, "rb").read()).hexdigest(), "notes": notes}
        notes.append("no release zip for this client: the commit archive")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        notes.append("GitHub API not reachable (" + str(e)[:60] + "): the commit archive")
    rev, z = commit_archive(owner, repo, seed.get("branch", ""), work)
    return {"from": "commit-archive", "url": f"https://github.com/{owner}/{repo}/archive/{rev}.zip", "rev": rev, "zip": z,
            "notes": notes}


# ------------------------------------------------------------------------------------------------ entries
def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def entry_from(seed: dict, src: dict, a: dict) -> dict:
    owner, repo = seed["repo"].split("/")
    lic = a.get("licence", "")
    blp = "author-art" if a["blp_files"] else "none"
    primary = sorted(a["addons"], key=lambda n: (n.lower() != repo.lower().split("-")[0], len(n)))[0]
    pa = a["addons"][primary]
    display = clean_name(seed.get("display_name") or pa["title"] or primary) or primary
    flags = list(a["flags"])
    if banned(seed.get("description", "")) or banned(display):
        flags.append("brand word in our text")
    if seed.get("notes"):
        flags.append(seed["notes"])
    install = {"from": src["from"], "url": src["url"], "rev": src["rev"], "sha256": src.get("sha256"),
               "size": a["size"], "file_count": a["file_count"], "strip_prefix": a["strip_prefix"],
               "folders": a["folders"], "skip": a["skip"], "files": a["files"], "files_digest": files_digest(a["files"])}
    return {
        "id": "up:" + seed["id"], "source": "upstream", "name": primary, "display_name": display,
        "description": seed.get("description", ""), "category": "addons", "tags": seed.get("tags", []),
        "builds": ["3.3.5a"], "author": owner, "author_url": f"https://github.com/{owner}",
        "repo": f"https://github.com/{owner}/{repo}", "licence": lic, "licence_source": a.get("licence_source", ""),
        "mirror_allowed": licence_open(lic) and blp == "none", "version": pa["version"] or src["rev"][:7],
        "install": install, "addons": sorted(a["addons"]), "toc": a["addons"],
        "requires": sorted(set(seed.get("requires", []))), "needs_folders": a["needs_folders"],
        "conflicts": [], "replaces_ui": bool(seed.get("replaces_ui")), "native": False,
        "blp": blp, "blp_files": a["blp_files"], "flags": flags, "notes": src.get("notes", []) + a["notes"],
        "review": {"by": "", "at": "", "notes": ""},
        "compat": {"realm": REALM, "status": "untested", "checked_at": ""},
        "curated_at": now_iso(),
    }


def link_entries(entries: list[dict]) -> None:
    """requires from the TOCs' Dependencies (an entry that provides the folder), and conflicts between entries that
    install the same folder."""
    by_folder = {}
    for e in entries:
        for f in e["addons"]:
            by_folder.setdefault(f.lower(), []).append(e["id"])
    for e in entries:
        req = set(x if x.startswith("up:") else "up:" + x for x in e.get("requires", []))
        unresolved = []
        for f in e.get("needs_folders", []):
            got = [i for i in by_folder.get(f.lower(), []) if i != e["id"]]
            if got:
                req.add(sorted(got)[0])
            else:
                unresolved.append(f)
        e["requires"] = sorted(req)
        con = {i for f in e["addons"] for i in by_folder.get(f.lower(), []) if i != e["id"]}
        e["conflicts"] = sorted(con | set(e.get("conflicts_extra", [])))
        if unresolved:
            e.setdefault("flags", [])
            msg = "needs addons that are not in the marketplace: " + ", ".join(unresolved)
            if msg not in e["flags"]:
                e["flags"].append(msg)


def diff_files(old: dict, new: dict) -> dict:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    return {"added": len(added), "removed": len(removed), "changed": len(changed),
            "sample": (["+ " + p for p in added[:10]] + ["- " + p for p in removed[:10]] + ["~ " + p for p in changed[:10]])}


def load_doc(path: str = OUT_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("entries"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"format": 1, "entries": [], "failed": [], "excluded": []}


def save_doc(doc: dict, path: str = OUT_PATH) -> None:
    doc["entries"].sort(key=lambda e: e["id"])
    doc["failed"].sort(key=lambda e: e["repo"].lower())
    doc["excluded"].sort(key=lambda e: e["repo"].lower())
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def status(e: dict) -> str:
    return "approved" if e.get("review", {}).get("by") else "pending"


def merge(doc: dict, new: dict) -> dict:
    """Put a freshly curated entry into the document, keeping an approved install until its update is approved."""
    old = next((e for e in doc["entries"] if e["id"] == new["id"]), None)
    if old is None:
        doc["entries"].append(new)
        return new
    doc["entries"].remove(old)
    if status(old) == "approved":
        if old["install"]["rev"] == new["install"]["rev"] and old["install"]["files"] == new["install"]["files"]:
            old.pop("pending_update", None)
            kept = dict(old, curated_at=new["curated_at"])
        else:
            kept = dict(old)
            kept["pending_update"] = {"install": new["install"], "version": new["version"], "addons": new["addons"],
                                      "toc": new["toc"], "blp": new["blp"], "blp_files": new["blp_files"],
                                      "licence": new["licence"], "licence_source": new["licence_source"],
                                      "mirror_allowed": new["mirror_allowed"], "flags": new["flags"],
                                      "needs_folders": new["needs_folders"],
                                      "diff": diff_files(old["install"]["files"], new["install"]["files"]),
                                      "curated_at": new["curated_at"]}
        doc["entries"].append(kept)
        return kept
    # Pending: replace with the new one, keeping our words when they were edited in the file.
    for k in ("display_name", "description", "tags", "replaces_ui"):
        if old.get(k) not in (None, "", []) and old.get(k) != new.get(k) and old.get("_edited"):
            new[k] = old[k]
    doc["entries"].append(new)
    return new


def curate(seeds: list[dict], doc: dict, scratch: str, fetch=None, log=print) -> dict:
    counts = {"resolved": 0, "failed": 0, "excluded": 0}
    ids = set()
    for seed in seeds:
        if seed.get("exclude"):
            doc["excluded"] = [x for x in doc["excluded"] if x["repo"] != seed["repo"]] + [
                {"repo": seed["repo"], "reason": seed["exclude"]}]
            doc["entries"] = [e for e in doc["entries"] if e["repo"].lower() != "https://github.com/" + seed["repo"].lower()]
            counts["excluded"] += 1
            continue
        work = tempfile.mkdtemp(prefix="cur-", dir=scratch)
        try:
            src = resolve(seed, work, fetch)
            a = analyze(read_zip(src["zip"]), seed)
            if not a["ok"]:
                raise ValueError(a["problem"])
            e = merge(doc, entry_from(seed, src, a))
            ids.add(e["id"])
            doc["failed"] = [x for x in doc["failed"] if x["repo"] != seed["repo"]]
            counts["resolved"] += 1
            log(f"ok      {e['id']:34} {src['from']:15} {a['file_count']:5} files  {e['licence'] or 'no licence':18} "
                f"{'blp ' if a['blp_files'] else ''}{'; '.join(e['flags'])[:100]}")
        except (RuntimeError, ValueError, OSError, zipfile.BadZipFile, subprocess.TimeoutExpired, KeyError) as ex:
            doc["failed"] = [x for x in doc["failed"] if x["repo"] != seed["repo"]] + [
                {"repo": seed["repo"], "id": "up:" + seed["id"], "reason": str(ex)[:300], "at": now_iso()}]
            counts["failed"] += 1
            log(f"FAILED  up:{seed['id']:31} {str(ex)[:160]}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    link_entries(doc["entries"])
    doc["counts"] = {"entries": len(doc["entries"]), "pending": sum(status(e) == "pending" for e in doc["entries"]),
                     "approved": sum(status(e) == "approved" for e in doc["entries"]), "failed": len(doc["failed"]),
                     "excluded": len(doc["excluded"])}
    doc["curated_at"] = now_iso()
    return counts


# ------------------------------------------------------------------------------------------------ review and publish
def approve(doc: dict, eid: str, by: str, notes: str = "", works: bool = False) -> dict:
    by = " ".join(str(by or "").split())[:60]
    if not by:
        raise ValueError("approve needs --by <name>")
    e = next((x for x in doc["entries"] if x["id"] == eid), None)
    if e is None:
        raise KeyError(f"no entry {eid}")
    if e.get("pending_update"):
        u = e.pop("pending_update")
        u.pop("diff", None)
        e.update(u)
    e["review"] = {"by": by, "at": now_iso(), "notes": " ".join(str(notes or "").split())[:300]}
    if works:
        e["compat"] = {"realm": REALM, "status": "works", "checked_at": now_iso()}
    return e


def unapprove(doc: dict, eid: str) -> dict:
    e = next((x for x in doc["entries"] if x["id"] == eid), None)
    if e is None:
        raise KeyError(f"no entry {eid}")
    e["review"] = {"by": "", "at": "", "notes": ""}
    return e


PUBLIC_FIELDS = ("id", "source", "name", "display_name", "description", "category", "tags", "builds", "author",
                 "author_url", "licence", "licence_source", "repo", "version", "addons", "requires", "conflicts",
                 "replaces_ui", "native", "blp", "mirror_allowed", "review", "compat")


def project(e: dict) -> dict:
    """An approved entry in the all.json project shape (mods/all-json.md)."""
    p = {k: e[k] for k in PUBLIC_FIELDS}
    p["name"] = e["display_name"] or e["name"]
    p["folder_name"] = e["name"]
    inst = dict(e["install"])
    if not e["mirror_allowed"]:
        inst.pop("mirror_url", None)
        if inst["from"] == "mirror":
            raise ValueError(f"{e['id']}: mirror without an open licence")
    # all.json carries the digest of the file list, not the list (mods/upstream.json keeps it for reviewers): the
    # launcher picks the files by the same rules and checks the digest of every path and sha256 it installs.
    inst.pop("files", None)
    inst.pop("skip", None)
    p["install"] = inst
    lic = e["licence"] or "licence not stated"
    where = "Hosted by Leyline" if inst["from"] == "mirror" else "Installs from the author's GitHub"
    p["credits"] = f"{p['name']} by {e['author']} · {lic} · {where}"
    p["page"] = e["repo"]
    p.update({"stars": None, "last_push": "", "submitted_by": "", "submitted_at": "", "last_checked": e["review"]["at"],
              "kind": "ui", "permissions": None, "on_wrath": None, "download": None, "sha256": inst.get("sha256"),
              "size": inst["size"], "file_count": inst["file_count"]})
    return p


def publish(doc: dict, path: str = PUBLISH_PATH) -> int:
    out = [project(e) for e in sorted(doc["entries"], key=lambda e: e["id"]) if status(e) == "approved"]
    body = {"format": 1, "about": "Approved upstream addons (tools/addon-curate/curate.py publish); merged into "
                                  "/wrath/mods/all.json by stream/upstream_addons.py.", "projects": out}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return len(out)


# For the Admin Console (N, stream/admin.py): the same as the commands, no printing.
def pending_entries(path: str = OUT_PATH) -> list[dict]:
    """Entries waiting for review (new ones, and approved ones with a pending update), with what a reviewer needs."""
    out = []
    for e in load_doc(path)["entries"]:
        if status(e) == "pending" or e.get("pending_update"):
            out.append({"id": e["id"], "name": e["display_name"], "repo": e["repo"], "licence": e["licence"] or "none",
                        "files": e["install"]["file_count"], "blp": e["blp"], "flags": e["flags"],
                        "update": (e.get("pending_update") or {}).get("diff")})
    return out


def approve_entry(path: str, eid: str, by: str, notes: str = "", works: bool = False,
                  publish_path: str = PUBLISH_PATH) -> dict:
    doc = load_doc(path)
    e = approve(doc, eid, by, notes, works)
    save_doc(doc, path)
    publish(doc, publish_path)
    return e


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*", default=[])
    r.add_argument("--scratch", default="")
    a = sub.add_parser("approve")
    a.add_argument("id")
    a.add_argument("--by", required=True)
    a.add_argument("--notes", default="")
    a.add_argument("--works", action="store_true")
    u = sub.add_parser("unapprove")
    u.add_argument("id")
    sub.add_parser("publish")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    doc = load_doc()
    if args.cmd == "run":
        seeds = json.load(open(SEEDS_PATH, encoding="utf-8"))["seeds"]
        if args.only:
            want = {i.removeprefix("up:") for i in args.only}
            seeds = [s for s in seeds if s.get("id") in want or s["repo"] in args.only]
        scratch = args.scratch or tempfile.mkdtemp(prefix="addon-curate-")
        os.makedirs(scratch, exist_ok=True)
        c = curate(seeds, doc, scratch)
        save_doc(doc)
        n = publish(doc)
        print(f"{c['resolved']} resolved, {c['failed']} failed, {c['excluded']} left out; "
              f"{doc['counts']['pending']} pending review, {n} published")
        return 0
    if args.cmd in ("approve", "unapprove"):
        try:
            e = approve(doc, args.id, args.by, args.notes, args.works) if args.cmd == "approve" else unapprove(doc, args.id)
        except (KeyError, ValueError) as ex:
            print(ex.args[0] if ex.args else ex, file=sys.stderr)
            return 1
        save_doc(doc)
        n = publish(doc)
        print(f"{e['id']}: {status(e)}; {n} published")
        return 0
    if args.cmd == "publish":
        print(f"{publish(doc)} published to {os.path.relpath(PUBLISH_PATH, ROOT)}")
        return 0
    for e in sorted(doc["entries"], key=lambda e: e["id"]):
        print(f"{e['id']:34} {status(e):8} {e['licence'] or '-':20} {e['install']['file_count']:5} "
              f"{'U ' if e.get('pending_update') else ''}{'; '.join(e['flags'])[:90]}")
    for f in doc["failed"]:
        print(f"{f['id']:34} failed   {f['reason'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
