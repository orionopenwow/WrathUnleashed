#!/usr/bin/env python3
"""The Host pack: the host kit as a versioned download that Leyline installs from its Host page.

    py -3 hosting\\pack\\make-hostpack.py [--version 2026.1029.1700] [--out DIR] [--upload] [--write-site]

Builds, from the repo, with the host kit's own rules (tools/leyline-repo/hostkit.py: the kit folder plus
realm-files/, the owner-only tools and every host's secrets left out, the safety check over every file):

  DIR/leyline-host-pack-<version>.zip          the pack (our code only: never game data, never a client)
  DIR/leyline-host-pack-<version>.zip.sha256   "<sha256>  <file>"
  DIR/leyline-host-pack-<version>.torrent      single-file torrent, web seed = the release download (BEP 19)
  DIR/hostpack.json                            the descriptor Leyline reads ({"format":1, version, download,
                                               sha256, size, torrent})

--upload puts the zip, its torrent and hostpack.json on https://github.com/orionopenwow/Leyline/releases/tag/host-pack
with the owner's own gh sign-in (versioned file names, so an older hostpack.json never points at a file that
changed). --write-site copies hostpack.json to stream/hostpack.json, which the sign-in step ("signin") deploys:
the site then lists the pack in /wrath/mods/all.json (category "tools", kind "hostpack") and at
/wrath/leyline/hostpack.json. Exit codes: 0 ok, 1 refused or failed, 2 usage. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tools" / "leyline-repo"))
import hostkit  # noqa: E402  (the kit's file list, safety check and zip writer)

SLUG = "orionopenwow/Leyline"
TAG = "host-pack"
BASE = f"https://github.com/{SLUG}/releases/download/{TAG}"
PIECE = 256 * 1024
NAME = "Host pack"
NOTES = ("The Host pack for Leyline: host a 3.3.5a realm from your own PC with Docker. Leyline downloads and "
         "updates it from its Host page; each file is checked against hostpack.json's sha256. Our code only.")
# The same refusal list the launcher applies (launcher/src-tauri/src/p2p/checker.rs).
GAME_EXT = (".mpq", ".blp", ".m2", ".wmo", ".adt", ".dbc", ".db2", ".skin", ".anim", ".wdt", ".wdl", ".bls", ".casc")
GAME_MAGIC = (b"MPQ\x1a", b"MPQ\x1b", b"BLP1", b"BLP2", b"MD20", b"MD21", b"WDBC", b"WDB2", b"REVM")
CLIENT_NAMES = ("wow.exe", "wow-64.exe", "wowb.exe", "wowt.exe", "wowclassic.exe")


class Refused(Exception):
    pass


def version_now(t: float | None = None) -> str:
    """YYYY.MMDD.HHMM in UTC: always newer than the last one, and a version Leyline can compare."""
    g = time.gmtime(t if t is not None else time.time())
    return f"{g.tm_year}.{g.tm_mon * 100 + g.tm_mday}.{g.tm_hour * 100 + g.tm_min}"


def floor_check(files: dict[str, bytes]) -> list[str]:
    """The launcher's own refusal list, run here too so a pack it would refuse is never published."""
    out = []
    for rel, data in files.items():
        base = rel.rsplit("/", 1)[-1].lower()
        if base.endswith(GAME_EXT) or base in CLIENT_NAMES or (base.startswith("wow") and base.endswith(".exe")):
            out.append(f"{rel}: game data or a game client")
        if data[:4] in GAME_MAGIC:
            out.append(f"{rel}: game data (by its contents)")
    return out


# ------------------------------------------------------------------------------------------------ torrent
def bencode(v) -> bytes:
    if isinstance(v, int):
        return b"i%de" % v
    if isinstance(v, str):
        v = v.encode()
    if isinstance(v, bytes):
        return b"%d:%s" % (len(v), v)
    if isinstance(v, list):
        return b"l" + b"".join(bencode(x) for x in v) + b"e"
    if isinstance(v, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, x) for k, x in v.items())
        return b"d" + b"".join(bencode(k) + bencode(x) for k, x in items) + b"e"
    raise TypeError(type(v))


def make_torrent(name: str, data: bytes, web_seeds: list[str], piece: int = PIECE) -> tuple[bytes, str]:
    """(torrent bytes, info-hash hex) for a single-file torrent with web seeds."""
    pieces = b"".join(hashlib.sha1(data[i:i + piece]).digest() for i in range(0, len(data), piece))
    info = {"length": len(data), "name": name, "piece length": piece, "pieces": pieces}
    top = {"info": info, "url-list": web_seeds, "created by": "Leyline make-hostpack.py",
           "comment": "Leyline Host pack: our code only, no game data"}
    return bencode(top), hashlib.sha1(bencode(info)).hexdigest()


# ------------------------------------------------------------------------------------------------ build
def build(out: Path, version: str, kit: Path | None = None, realm: Path | None = None) -> dict:
    kit = (kit or REPO / "hosting" / "kit").resolve()
    if not (kit / "Host a Wrath realm.bat").is_file():
        raise Refused(f"{kit} is not the host kit folder")
    realm = realm.resolve() if realm else hostkit.find_realm(kit)
    files = hostkit.collect(kit, realm)
    files["HOSTPACK-VERSION.txt"] = f"Leyline Host pack {version}\n".encode()
    bad = hostkit.problems(files) + floor_check(files)
    if bad:
        raise Refused("the pack has files that must not go to players (nothing was made):\n  " + "\n  ".join(bad))
    out.mkdir(parents=True, exist_ok=True)
    zname = f"leyline-host-pack-{version}.zip"
    zpath = out / zname
    hostkit.write_zip(files, zpath)
    data = zpath.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    (out / (zname + ".sha256")).write_text(f"{sha}  {zname}\n", encoding="utf-8")
    tname = f"leyline-host-pack-{version}.torrent"
    torrent, ih = make_torrent(zname, data, [f"{BASE}/{zname}"])
    (out / tname).write_bytes(torrent)
    desc = {"format": 1, "name": NAME, "version": version, "download": f"{BASE}/{zname}", "sha256": sha,
            "size": len(data), "torrent": f"{BASE}/{tname}", "info_hash": ih}
    (out / "hostpack.json").write_text(json.dumps(desc, indent=1) + "\n", encoding="utf-8")
    return {"zip": zpath, "torrent": out / tname, "json": out / "hostpack.json", "desc": desc, "files": len(files)}


def upload(made: dict, run=hostkit.gh) -> None:
    rc, who = run(["api", "user", "--jq", ".login"])
    who = who.strip()
    if rc != 0 or not who:
        raise Refused("the GitHub CLI is not signed in: gh auth login (as the owner)")
    if who.lower() in hostkit.NOT_OWNER:
        raise Refused(f"the GitHub CLI is signed in as {who}; the pack is published as the owner only: gh auth switch")
    rc, out = run(["repo", "view", SLUG, "--json", "visibility", "--jq", ".visibility"])
    if rc != 0 or out.strip().upper() != "PUBLIC":
        raise Refused(f"{SLUG} is not public on GitHub: players could not download the pack")
    assets = [str(made["zip"]), str(made["torrent"]), str(made["json"])]
    rc, _ = run(["release", "view", TAG, "-R", SLUG, "--json", "tagName"])
    if rc != 0:
        rc, out = run(["release", "create", TAG, *assets, "-R", SLUG, "--title", "Host pack", "--notes", NOTES])
    else:
        rc, out = run(["release", "upload", TAG, *assets, "-R", SLUG, "--clobber"])
    if rc != 0:
        raise Refused("the upload failed: " + (out.strip().splitlines() or ["?"])[-1])


def main(argv=None, run=hostkit.gh) -> int:
    ap = argparse.ArgumentParser(description="Build (and publish) the Leyline Host pack.")
    ap.add_argument("--version", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--kit", default="")
    ap.add_argument("--realm", default="")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--write-site", action="store_true", help="copy hostpack.json to stream/hostpack.json")
    a = ap.parse_args(argv)
    if a.write_site and not a.upload:
        print("HOST PACK STOPPED: --write-site needs --upload (the site would list a file that is not published)",
              file=sys.stderr)
        return 2
    version = a.version or version_now()
    if not all(p.isdigit() for p in version.split(".")) or not 1 <= len(version.split(".")) <= 3:
        print("HOST PACK STOPPED: --version is numbers and dots, like 2026.1029.1700", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else Path(os.environ.get("TEMP") or "/tmp") / "leyline-host-pack"
    try:
        made = build(out, version, Path(a.kit) if a.kit else None, Path(a.realm) if a.realm else None)
        d = made["desc"]
        print(f"[1/3] {made['zip'].name}: {made['files']} files, {d['size'] // 1024} KB, sha256 {d['sha256'][:16]}..., "
              f"safety check clean -> {out}")
        print(f"      torrent {made['torrent'].name} (info-hash {d['info_hash']}, web seed = the release file)")
        if a.upload:
            print(f"[2/3] Publishing on {SLUG} (release {TAG})")
            upload(made, run)
            print(f"      {d['download']}")
        if a.write_site:
            dest = REPO / "stream" / "hostpack.json"
            shutil.copyfile(made["json"], dest)
            print(f"[3/3] {dest} written: deploy it with the sign-in step (signin) and commit it")
        print("HOST PACK OK")
        return 0
    except (Refused, hostkit.Refused) as e:
        print(f"HOST PACK STOPPED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
