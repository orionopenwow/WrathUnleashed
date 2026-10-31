"""Upstream addons in /wrath/mods/all.json: curated third-party addons the Leyline launcher installs straight from
their author's repo (mods/SPEC.md "Upstream addons", mods/all-json.md).

The list is upstream-addons.json beside this file, written by tools/addon-curate/curate.py (publish, approve): only
entries a person reviewed are in it. add_upstream() appends them to the Workshop's all.json body; the portal calls it
on the way out (stream/wrath_portal.py, beside leyline_net.add_hostpack). Nothing is hosted here: each entry's
install address is the author's own release asset or commit archive.

Every entry is checked again before it is served: id up:<slug>, source "upstream", an install address on the
entry's own repo in an allowed shape, a 40-hex commit for an archive, review.by set, native false, no brand words in
the name. A bad entry is dropped, never served half-checked. Standard library only.
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.environ.get("WU_UPSTREAM_ADDONS", os.path.join(HERE, "upstream-addons.json"))
MAX = 2000

_ID = re.compile(r"up:[a-z][a-z0-9]*(-[a-z0-9]+)*")
_REPO = re.compile(r"https://(github\.com|gitlab\.com|codeberg\.org)/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_BANNED = re.compile(r"(?i:world\s*of\s*warcraft|warcraft|lich\s*king|blizzard|wotlk)|(?i:(?<![a-z])wow(?![a-z]))|WoW|WOW")

_cache: dict = {"mtime": None, "projects": []}


def url_ok(inst: dict, repo: str) -> bool:
    """The install address is the entry's own repo: a release asset, or an archive pinned to a 40-hex commit."""
    m = _REPO.fullmatch(repo or "")
    u, rev, frm = inst.get("url"), inst.get("rev"), inst.get("from")
    if not m or not isinstance(u, str) or not isinstance(rev, str) or re.search(r"[\s?#%\\]|/\.\./", u):
        return False
    host, o, r = m.groups()
    if frm == "release-asset" and host == "github.com":
        rest = u.removeprefix(f"https://github.com/{o}/{r}/releases/download/")
        parts = rest.split("/")
        return rest != u and len(parts) == 2 and all(parts) and ".." not in parts and parts[1].lower().endswith(".zip")
    if frm == "commit-archive" and _HEX40.fullmatch(rev):
        want = {"github.com": f"https://github.com/{o}/{r}/archive/{rev}.zip",
                "gitlab.com": f"https://gitlab.com/{o}/{r}/-/archive/{rev}/{r}-{rev}.zip",
                "codeberg.org": f"https://codeberg.org/{o}/{r}/archive/{rev}.zip"}[host]
        return u == want
    return False   # "mirror": not served until Leyline hosts copies (only ever with mirror_allowed)


def valid(p) -> bool:
    if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not _ID.fullmatch(p["id"]) or len(p["id"]) > 35:
        return False
    inst = p.get("install")
    rv = p.get("review")
    return (p.get("source") == "upstream" and p.get("native") is False and isinstance(inst, dict)
            and isinstance(rv, dict) and isinstance(rv.get("by"), str) and rv["by"].strip() != ""
            and isinstance(p.get("name"), str) and p["name"].strip() != "" and not _BANNED.search(p["name"])
            and not _BANNED.search(p.get("description") or "")
            and url_ok(inst, p.get("repo", "")) and isinstance(inst.get("folders"), dict) and inst["folders"]
            and (inst.get("sha256") is None or (isinstance(inst["sha256"], str) and _HEX64.fullmatch(inst["sha256"])))
            and isinstance(inst.get("files_digest"), str) and _HEX64.fullmatch(inst["files_digest"]) is not None
            and p.get("blp") in ("none", "author-art"))


def projects(path: str | None = None) -> list[dict]:
    """The reviewed entries (all.json projects), re-read when the file changes. [] when there is none."""
    path = path or PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    if _cache["mtime"] == (path, mtime):
        return _cache["projects"]
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        items = doc.get("projects") if isinstance(doc, dict) else None
    except (OSError, ValueError):
        items = None
    out = [p for p in (items or [])[:MAX] if valid(p)] if isinstance(items, list) else []
    _cache.update(mtime=(path, mtime), projects=out)
    return out


def add_upstream(all_json: bytes, items: list[dict] | None = None) -> bytes:
    """all.json with the reviewed upstream addons added (each once, sorted in by name). Unchanged when there are
    none or the body is odd."""
    items = projects() if items is None else [p for p in items if valid(p)]
    if not items:
        return all_json
    try:
        doc = json.loads(all_json)
        have = doc["projects"]
    except (ValueError, KeyError, TypeError):
        return all_json
    if not isinstance(have, list):
        return all_json
    ids = {p.get("id") for p in have if isinstance(p, dict)}
    have.extend(p for p in items if p["id"] not in ids)
    have.sort(key=lambda p: (str(p.get("name", "")).lower(), str(p.get("source", ""))) if isinstance(p, dict) else ("", ""))
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
