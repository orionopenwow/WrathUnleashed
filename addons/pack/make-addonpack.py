#!/usr/bin/env python3
"""The Leyline addons: our own in-game addons as one versioned download that the Leyline launcher installs into a
player's own 3.3.5a game folder (launcher/src-tauri/src/addons.rs; Clients, Mods › Our addons, the PLAY prompt).

    py -3 addons\\pack\\make-addonpack.py [--version 2026.1031.0900] [--out DIR] [--upload] [--no-brand]

What goes in (ADDONS below), each as <Name>/... in the zip:

  WrathUnleashedUI   stream/fui-web/Interface/AddOns/WrathUnleashedUI   the in-game UI for our realm (the browser
                     client gets the same folder from the stream)
  OVArmory           addons/OVArmory                                    /armory (talks to ov_armory.lua)
  OVQoL              addons/OVQoL                                       /qol (talks to ov_qol.lua)
  WUModCatalog       made here from mods/catalog.json (wu-mod.py)       the Workshop tab's list of the realm's mods

Never: Forever UI (its art is the modern game's: players fetch it from its own project), MiniGM (third-party, GM
only), the 1.12 addons, or any game data. Only addon text, our font and our textures are taken (ALLOWED); every
file goes through the Leyline export's refusal rules and the launcher's own game-data list; each .toc must say
## Interface: 30300 and list only files that are there; the addon list's lines (Title, Notes, Author) may not
name the game or its maker. Anything flagged: nothing is made.

Writes, into DIR (default %TEMP%\\leyline-addons):

  leyline-addons-<version>.zip          the pack (sorted, fixed dates: the same files give the same bytes)
  leyline-addons-<version>.zip.sha256   "<sha256>  <file>"
  addonpack.json                        the listing Leyline reads: {"format":1, name, version, build, download,
                                        sha256, size, addons:[{name,title,version}], files:{path: sha256}}

--upload puts the zip and addonpack.json on https://github.com/orionopenwow/Leyline/releases/tag/leyline-addons with
the owner's own gh sign-in (versioned zip names, so an older addonpack.json never points at a file that changed).
Leyline reads https://github.com/orionopenwow/Leyline/releases/download/leyline-addons/addonpack.json, checks the
zip's sha256 and every file's, and refuses a download from anywhere else.

--no-brand keeps the addon list's old names (WrathUnleashed UI); by default they say Leyline, as the launcher does
(the same swaps as the realm's brand switch, stream/server/fui-overlay.py BRAND_SWAPS).
Exit codes: 0 ok, 1 refused or failed, 2 usage. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tools" / "leyline-repo"))
import export  # noqa: E402  (the public export's refusal rules and brand words)
import hostkit  # noqa: E402  (gh and the owner check)

SLUG = "orionopenwow/Leyline"
TAG = "leyline-addons"
BASE = f"https://github.com/{SLUG}/releases/download/{TAG}"
NAME = "Leyline addons"
INTERFACE = "30300"
BUILD = "3.3.5a"
ADDONS = [
    ("WrathUnleashedUI", "stream/fui-web/Interface/AddOns/WrathUnleashedUI"),
    ("OVArmory", "addons/OVArmory"),
    ("OVQoL", "addons/OVQoL"),
]
CATALOG_ADDON = "WUModCatalog"
# The launcher takes exactly these (addons.rs OUR_EXT).
ALLOWED = (".toc", ".lua", ".xml", ".ttf", ".tga", ".txt")
# Notes for people reading the repo, not part of an addon: left out without a word.
SKIP = re.compile(r"^(readme(\..*)?|\.gitignore|\.ds_store|thumbs\.db|desktop\.ini)$", re.I)
SKIP_DIRS = {".git", "__pycache__", "tests"}
MAX_FILE = 10 * 1024 * 1024
MAX_PACK = 20 * 1024 * 1024   # addons.rs MAX_PACK
NOTES = ("The Leyline addons for a 3.3.5a game folder: the Leyline window, game modes, golf, Edit mode and the "
         "Builder, your Den, the Workshop tab, companions, the Armory and quality of life. Leyline installs and "
         "updates them from its Clients and Mods pages; each file is checked against addonpack.json. Our code only.")
# The launcher's own refusal list (launcher/src-tauri/src/mods.rs BLOCKED_EXT / BLOCKED_MAGIC).
GAME_EXT = (".mpq", ".blp", ".m2", ".wmo", ".adt", ".dbc", ".db2", ".skin", ".anim", ".wdt", ".wdl", ".bls", ".casc")
GAME_MAGIC = (b"MPQ\x1a", b"MPQ\x1b", b"BLP1", b"BLP2", b"MD20", b"MD21", b"WDBC", b"WDB2", b"REVM")
# The brand switch's swaps of the addon list's lines (stream/server/fui-overlay.py BRAND_SWAPS).
BRAND_SWAPS = [("## Title: WrathUnleashed UI", "## Title: Leyline UI"),
               ("## Notes: WrathUnleashed's ", "## Notes: Leyline's "),
               ("## Title: Mod list (WrathUnleashed)", "## Title: Mod list (Leyline)"),
               ("## Author: WrathUnleashed", "## Author: Leyline"),
               # this pack's own two (the stream does not carry them)
               ("## Title: WrathUnleashed Armory", "## Title: Leyline Armory"),
               ("## Notes: WrathUnleashed quality of life", "## Notes: Leyline quality of life")]


class Refused(Exception):
    pass


def version_now(t: float | None = None) -> str:
    """YYYY.MMDD.HHMM in UTC: always newer than the last one, and a version Leyline can compare."""
    g = time.gmtime(t if t is not None else time.time())
    return f"{g.tm_year}.{g.tm_mon * 100 + g.tm_mday}.{g.tm_hour * 100 + g.tm_min}"


def brand(text: str) -> str:
    out = []
    for line in text.split("\n"):
        cr = "\r" if line.endswith("\r") else ""
        body = line[:-1] if cr else line
        for old, new in BRAND_SWAPS:
            if body == old or (old.endswith(" ") and body.startswith(old)):
                body = new + body[len(old):]
                break
        out.append(body + cr)
    return "\n".join(out)


def wu_mod():
    spec = importlib.util.spec_from_file_location("wu_mod", REPO / "mods" / "wu-mod.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def catalog_addon(catalog_json: Path, branded: bool) -> dict[str, bytes]:
    """WUModCatalog from the checked catalog (mods/catalog.json, written by the mods step's wu-mod.py catalog)."""
    wm = wu_mod()
    cat = json.loads(catalog_json.read_text(encoding="utf-8"))
    toc = wm.CATALOG_TOC
    if branded:
        toc = toc.replace("(WrathUnleashed)", "(Leyline)").replace("## Author: WrathUnleashed", "## Author: Leyline")
    return {f"{CATALOG_ADDON}/{CATALOG_ADDON}.toc": toc.encode(), f"{CATALOG_ADDON}/{CATALOG_ADDON}.lua": wm.catalog_lua(cat).encode()}


def collect(repo: Path = REPO, branded: bool = True, with_catalog: bool = True) -> tuple[dict[str, bytes], list[str]]:
    """({"<Addon>/<path>": bytes}, problems)."""
    files: dict[str, bytes] = {}
    bad: list[str] = []
    for name, rel in ADDONS:
        root = repo / rel
        if not (root / f"{name}.toc").is_file():
            bad.append(f"{rel}: no {name}.toc")
            continue
        for d, dirs, names in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
            for n in sorted(names):
                p = Path(d) / n
                inner = p.relative_to(root).as_posix()
                if SKIP.match(n):
                    continue
                if p.is_symlink():
                    bad.append(f"{name}/{inner}: a link")
                    continue
                if not n.lower().endswith(ALLOWED):
                    bad.append(f"{name}/{inner}: not an addon file (allowed: {' '.join(ALLOWED)})")
                    continue
                data = p.read_bytes()
                if n.lower().endswith(".toc") and branded:
                    data = brand(data.decode("utf-8")).encode("utf-8")
                files[f"{name}/{inner}"] = data
    if with_catalog:
        cj = repo / "mods" / "catalog.json"
        if cj.is_file():
            files.update(catalog_addon(cj, branded))
        else:
            bad.append("mods/catalog.json: missing (run the mods step's catalog first, or --no-catalog)")
    return files, bad


def toc_lines(text: str) -> tuple[dict[str, str], list[str]]:
    meta, listed = {}, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("##"):
            k, _, v = s[2:].partition(":")
            meta[k.strip()] = v.strip()
        elif s and not s.startswith("#"):
            listed.append(s.replace("\\", "/"))
    return meta, listed


def problems(files: dict[str, bytes]) -> list[str]:
    """Everything that must stop the pack (empty = clean)."""
    out = []
    total = 0
    addons = sorted({k.split("/", 1)[0] for k in files})
    for rel, data in sorted(files.items()):
        base = rel.rsplit("/", 1)[-1].lower()
        total += len(data)
        why = export.refusal(f"addons/{rel}", data)
        if why:
            out.append(f"{rel}: {why}")
        if base.endswith(GAME_EXT) or data[:4] in GAME_MAGIC:
            out.append(f"{rel}: game data")
        if not base.endswith(ALLOWED):
            out.append(f"{rel}: not an addon file")
        if len(data) > MAX_FILE:
            out.append(f"{rel}: larger than 10 MB")
    for a in addons:
        toc = files.get(f"{a}/{a}.toc")
        if toc is None:
            out.append(f"{a}: no {a}.toc")
            continue
        meta, listed = toc_lines(toc.decode("utf-8", "replace"))
        if meta.get("Interface") != INTERFACE:
            out.append(f"{a}/{a}.toc: ## Interface must be {INTERFACE} (got {meta.get('Interface')})")
        for item in listed:
            if f"{a}/{item}" not in files:
                out.append(f"{a}/{a}.toc lists {item}, which is not in the pack")
        shown = "\n".join(f"{k}: {v}" for k, v in meta.items() if k.split("-")[0] in ("Title", "Notes", "Author"))
        out.extend(f"{a}/{a}.toc: the addon list says {h.split(': ', 1)[-1]}" for h in export.brand_hits(f"{a}.toc", shown.encode()))
    if any(a.lower() == "foreverui" for a in addons):
        out.append("ForeverUI: not ours to ship (its art is the modern game's)")
    if total > MAX_PACK:
        out.append(f"the pack is {total // 1024} KB, more than the launcher takes")
    return out


def write_zip(files: dict[str, bytes], out: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(files):
            zi = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            zi.external_attr = 0o100644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, files[rel])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, out)


def addon_list(files: dict[str, bytes]) -> list[dict]:
    out = []
    for a in sorted({k.split("/", 1)[0] for k in files}):
        meta, _ = toc_lines(files[f"{a}/{a}.toc"].decode("utf-8", "replace"))
        title = re.sub(r"\|c[0-9a-fA-F]{8}|\|r", "", meta.get("Title", a))
        out.append({"name": a, "title": title[:64], "version": meta.get("Version", "")[:40]})
    return out


def build(out: Path, version: str, repo: Path = REPO, branded: bool = True, with_catalog: bool = True) -> dict:
    files, bad = collect(repo, branded, with_catalog)
    bad += problems(files)
    if bad:
        raise Refused("the pack has files that must not go to players (nothing was made):\n  " + "\n  ".join(bad))
    zname = f"leyline-addons-{version}.zip"
    zpath = out / zname
    write_zip(files, zpath)
    data = zpath.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    (out / (zname + ".sha256")).write_text(f"{sha}  {zname}\n", encoding="utf-8")
    desc = {"format": 1, "name": NAME, "version": version, "build": BUILD, "download": f"{BASE}/{zname}",
            "sha256": sha, "size": len(data), "addons": addon_list(files),
            "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())}}
    (out / "addonpack.json").write_text(json.dumps(desc, indent=1) + "\n", encoding="utf-8")
    return {"zip": zpath, "json": out / "addonpack.json", "desc": desc, "files": len(files)}


def upload(made: dict, run=hostkit.gh) -> None:
    rc, who = run(["api", "user", "--jq", ".login"])
    who = who.strip()
    if rc != 0 or not who:
        raise Refused("the GitHub CLI is not signed in: gh auth login (as the owner)")
    if who.lower() in hostkit.NOT_OWNER:
        raise Refused(f"the GitHub CLI is signed in as {who}; the addons are published as the owner only: gh auth switch")
    rc, out = run(["repo", "view", SLUG, "--json", "visibility", "--jq", ".visibility"])
    if rc != 0 or out.strip().upper() != "PUBLIC":
        raise Refused(f"{SLUG} is not public on GitHub: players could not download the addons")
    # The zip first, then the listing that points at it: a player never gets a listing for a missing file.
    rc, _ = run(["release", "view", TAG, "-R", SLUG, "--json", "tagName"])
    if rc != 0:
        rc, out = run(["release", "create", TAG, str(made["zip"]), "-R", SLUG, "--title", NAME, "--notes", NOTES])
    else:
        rc, out = run(["release", "upload", TAG, str(made["zip"]), "-R", SLUG, "--clobber"])
    if rc != 0:
        raise Refused("the upload failed: " + (out.strip().splitlines() or ["?"])[-1])
    rc, out = run(["release", "upload", TAG, str(made["json"]), "-R", SLUG, "--clobber"])
    if rc != 0:
        raise Refused("the listing's upload failed: " + (out.strip().splitlines() or ["?"])[-1])


def main(argv=None, run=hostkit.gh) -> int:
    ap = argparse.ArgumentParser(description="Build (and publish) the Leyline addons.")
    ap.add_argument("--version", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--no-brand", action="store_true")
    ap.add_argument("--no-catalog", action="store_true", help="leave the WUModCatalog addon out")
    a = ap.parse_args(argv)
    version = a.version or version_now()
    if not all(p.isdigit() for p in version.split(".")) or not 1 <= len(version.split(".")) <= 3:
        print("LEYLINE ADDONS STOPPED: --version is numbers and dots, like 2026.1031.0900", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else Path(os.environ.get("TEMP") or "/tmp") / "leyline-addons"
    try:
        made = build(out, version, branded=not a.no_brand, with_catalog=not a.no_catalog)
        d = made["desc"]
        names = ", ".join(f"{x['name']}" for x in d["addons"])
        print(f"[1/2] {made['zip'].name}: {names}; {made['files']} files, {d['size'] // 1024} KB, "
              f"sha256 {d['sha256'][:16]}..., safety check clean -> {out}")
        if a.upload:
            print(f"[2/2] Publishing on {SLUG} (release {TAG})")
            upload(made, run)
            print(f"      {d['download']}")
            print(f"      {BASE}/addonpack.json (Leyline reads this)")
        else:
            print("[2/2] Not published (no --upload)")
        print("LEYLINE ADDONS OK")
        return 0
    except Refused as e:
        print(f"LEYLINE ADDONS STOPPED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
