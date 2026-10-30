#!/usr/bin/env python3
"""The host kit zip for players: build it, check it, publish it on the public Leyline repo's "host-kit" release.

    py -3 tools\\leyline-repo\\hostkit.py [--upload] [--kit hosting\\kit] [--realm realm] [--out FILE.zip] [--list]

Builds the host kit zip (WrathUnleashed-host-kit.zip: the release asset keeps its name) the way "Make host kit.bat" does (the kit folder plus realm-files/: the
presets, modules.env, the realm Lua, the profile SQL and the realm's build recipe), but straight from the repo,
without touching the kit folder and without questions (the Autopilot step "hostkit"):

  * left out: state/, cache/, realm-files/ already in the kit, .env, __pycache__, zips, and the owner-only tools
    (Make host kit.bat, Publish host kit.bat, make-kit.sh);
  * line ends fixed for players: .bat files CRLF, everything else LF (a CRLF shell script breaks on a Mac);
  * modules.env without its AC_*DATABASE_INFO lines (the kit's compose file sets those from the host's own
    generated password, and the realm's copy carries the PC's local test password);
  * the safety check: export.py's own rules over every file (game data, secrets, logs, decompiled code; the
    README/HTML/docs brand check), plus: the realm .env files may hold only AC_/OV_/WU_ settings with no
    password, secret or token in them. Anything flagged stops it and nothing is uploaded.

--upload puts the zip on https://github.com/orionopenwow/Leyline/releases/tag/host-kit (made on first use,
replaced after) with the owner's own gh sign-in (a release needs no workflow permission) and checks that the
download link answers without signing in. It prints the link the site uses (stream/hostflow.py's default).
Exit codes: 0 ok, 1 refused or failed, 2 usage. Standard library only (plus gh for --upload).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import export  # noqa: E402  (the Leyline export's safety rules)

REPO = HERE.parents[1]
SLUG = "orionopenwow/Leyline"
TAG = "host-kit"
NAME = "WrathUnleashed-host-kit.zip"
URL = f"https://github.com/{SLUG}/releases/download/{TAG}/{NAME}"
TOP = "Leyline host"                              # the folder players get when they unzip
PRESETS = ("main", "brawl", "progression", "casual", "dalaran")
SQL = ("brawl_world.sql", "brawl_world_2.sql", "main_unbrawl.sql", "main_world.sql", "modern_combos.sql")
OWNER_ONLY = {"Make host kit.bat", "Publish host kit.bat", "make-kit.sh"}
SKIP = export.SKIP_DIRS | {"realm-files"}
ENV_KEY = re.compile(r"^(AC|OV|WU)_[A-Z0-9_]+$")
ENV_BAD = re.compile(r"PASS|SECRET|TOKEN|PRIVATE|DATABASE_INFO|API_?KEY", re.I)
NOT_OWNER = ("chumpton",)
NOTES = ("The host kit: host a 3.3.5a realm from your own PC with Docker, no port forwarding. Unzip it, then run "
         "'Host a Leyline realm.bat' (Windows) or 'bash leyline host' (Mac, Linux). Guide: "
         "https://play.openvanilla.app/wrath/docs/hosting")


class Refused(Exception):
    pass


def find_realm(kit: Path) -> Path:
    for c in (kit.parent / "realm", kit.parent.parent / "realm"):
        if (c / "profiles" / "main.env").is_file():
            return c
    raise Refused(f"no realm folder next to {kit} (looked for ../realm and ../../realm)")


def text_fix(rel: str, data: bytes) -> bytes:
    if b"\0" in data:
        return data
    lf = data.replace(b"\r\n", b"\n")
    return lf.replace(b"\n", b"\r\n") if rel.lower().endswith((".bat", ".cmd")) else lf


def strip_db_info(data: bytes) -> bytes:
    keep = [l for l in data.decode("utf-8").split("\n") if not re.match(r"\s*AC_\w*DATABASE_INFO\s*=", l)]
    return "\n".join(keep).encode()


def collect(kit: Path, realm: Path) -> dict[str, bytes]:
    """{path inside the kit folder: bytes}."""
    files: dict[str, bytes] = {}
    for d, dirs, names in os.walk(kit):
        dirs[:] = sorted(x for x in dirs if x not in SKIP and not x.startswith(".git"))
        for n in sorted(names):
            rel = (Path(d) / n).relative_to(kit).as_posix()
            if (rel in OWNER_ONLY or rel == ".env" or n.lower().endswith(".zip") or export.JUNK.search(n)
                    or rel.endswith(".leyline-tmp")):
                continue
            files[rel] = (Path(d) / n).read_bytes()
    rf = "realm-files/"
    for p in PRESETS:
        files[f"{rf}profiles/{p}.env"] = (realm / "profiles" / f"{p}.env").read_bytes()
    files[f"{rf}modules.env"] = strip_db_info((realm / "modules.env").read_bytes().replace(b"\r\n", b"\n"))
    lua = realm / "custom" / "lua_scripts"
    for p in sorted(lua.rglob("*")):
        if p.is_file() and not export.JUNK.search(p.name):
            files[f"{rf}lua_scripts/{p.relative_to(lua).as_posix()}"] = p.read_bytes()
    for f in SQL:
        if (realm / f).is_file():
            files[f"{rf}sql/{f}"] = (realm / f).read_bytes()
    files[f"{rf}build/sources.lock"] = (realm / "custom" / "sources.lock").read_bytes()
    files[f"{rf}build/fetch.sh"] = (realm / "custom" / "fetch.sh").read_bytes()
    for p in sorted((realm / "custom" / "patches").glob("*.patch")):
        files[f"{rf}build/patches/{p.name}"] = p.read_bytes()
    # the relay code, for the community relay (docker-compose.volunteer-relay.yml, tools/Dockerfile.relay)
    wurelay = kit.parent / "relay" / "wurelay"
    if wurelay.is_dir():
        for p in sorted(wurelay.rglob("*")):
            if p.is_file() and not export.JUNK.search(p.name) and "__pycache__" not in p.parts:
                files[f"tools/wurelay/{p.relative_to(wurelay).as_posix()}"] = p.read_bytes()
    files = {rel: text_fix(rel, data) for rel, data in files.items()}
    manifest = "".join(f"{hashlib.sha256(files[r]).hexdigest()}  ./{r[len(rf):]}\n"
                       for r in sorted(files) if r.startswith(rf))
    files[f"{rf}MANIFEST.sha256"] = manifest.encode()
    return files


def problems(files: dict[str, bytes]) -> list[str]:
    """Everything that must stop the publish (empty = clean)."""
    out = []
    for rel, data in sorted(files.items()):
        repo_rel = f"hosting/kit/{rel}"
        if rel.startswith("realm-files/") and rel.endswith(".env"):
            name = rel.rsplit("/", 1)[-1]
            if export.GAME_DATA.search(name) or export.SECRET_TEXT.search(data):
                out.append(f"{rel}: secret (key or token inside)")
            for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                key = s.split("=", 1)[0].strip()
                if "=" not in s or not ENV_KEY.match(key) or ENV_BAD.search(key):
                    out.append(f"{rel}:{n}: setting {key!r} is not allowed in a public kit")
            continue
        why = export.refusal(repo_rel, data)
        if why:
            out.append(f"{rel}: {why}")
        if export.user_facing(repo_rel):
            out.extend(export.brand_hits(rel, data))
    for must in ("Host a Wrath realm.bat", "host-wrath-realm.sh", "leyline", "docker-compose.host.yml",
                 "tools/Dockerfile", "realm-files/profiles/main.env", "realm-files/build/sources.lock"):
        if must not in files:
            out.append(f"{must}: missing from the kit")
    return out


def write_zip(files: dict[str, bytes], out: Path) -> None:
    """Same files in, same bytes out (fixed dates, sorted)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(files):
            data = files[rel]
            zi = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=(2026, 1, 1, 0, 0, 0))
            exe = data.startswith(b"#!")
            zi.external_attr = ((0o100755 if exe else 0o100644) << 16)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, out)


def summary(files: dict[str, bytes]) -> list[str]:
    groups: dict[str, list[str]] = {}
    for rel in sorted(files):
        parts = rel.split("/")
        g = "/".join(parts[:2]) if parts[0] in ("realm-files", "tools") and len(parts) > 2 else (
            parts[0] if len(parts) > 1 else "(top)")
        groups.setdefault(g, []).append(parts[-1])
    return [f"  {g}: {len(v)} file(s)" + (f" ({', '.join(v)})" if len(v) <= 8 else "") for g, v in groups.items()]


# ------------------------------------------------------------------------------------------------ upload
def gh(args, capture=True):
    try:
        p = subprocess.run(["gh", *args], capture_output=capture, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, "gh is not installed"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def upload(zip_path: Path, run=gh, fetch=None) -> str:
    rc, who = run(["api", "user", "--jq", ".login"])
    who = who.strip()
    if rc != 0 or not who:
        raise Refused("the GitHub CLI is not signed in: gh auth login (as the owner)")
    if who.lower() in NOT_OWNER:
        raise Refused(f"the GitHub CLI is signed in as {who}; the kit is published as the owner only: gh auth switch")
    rc, out = run(["repo", "view", SLUG, "--json", "visibility", "--jq", ".visibility"])
    if rc != 0:
        raise Refused(f"{SLUG} is not on GitHub yet: run the Leyline step first")
    if out.strip().upper() != "PUBLIC":
        raise Refused(f"{SLUG} is {out.strip() or 'not public'}: players could not download the kit")
    rc, _ = run(["release", "view", TAG, "-R", SLUG, "--json", "tagName"])
    if rc != 0:
        rc, out = run(["release", "create", TAG, str(zip_path), "-R", SLUG, "--title", "Host kit", "--notes", NOTES])
        verb = "created"
    else:
        rc, out = run(["release", "upload", TAG, str(zip_path), "-R", SLUG, "--clobber"])
        verb = "replaced"
    if rc != 0:
        raise Refused("the upload failed: " + out.strip().splitlines()[-1] if out.strip() else "the upload failed")
    print(f"  release {TAG}: {verb} {NAME}")
    (fetch or check_download)(URL)
    return URL


def check_download(url: str) -> None:
    """Anonymous HEAD on the public link (GitHub redirects to its file host)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "hostkit-check"})
        with urllib.request.urlopen(req, timeout=20) as r:
            size = r.headers.get("Content-Length")
            print(f"  the download answers without signing in ({int(size) // 1024 if size else '?'} KB)")
    except Exception as e:                      # the upload worked; a slow CDN is not a failure
        print(f"  !! could not check the download link yet ({e}); try it in a browser in a minute")


def main(argv=None, run=gh, fetch=None) -> int:
    ap = argparse.ArgumentParser(description="Build, check and publish the host kit zip.")
    ap.add_argument("--kit", default=str(REPO / "hosting" / "kit"))
    ap.add_argument("--realm", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--list", action="store_true", help="print every file in the zip")
    a = ap.parse_args(argv)
    kit = Path(a.kit).resolve()
    try:
        if not (kit / "Host a Wrath realm.bat").is_file():
            raise Refused(f"{kit} is not the host kit folder")
        realm = Path(a.realm).resolve() if a.realm else find_realm(kit)
        files = collect(kit, realm)
        bad = problems(files)
        if bad:
            raise Refused("the kit has files that must not go to players (nothing was made or uploaded):\n  "
                          + "\n  ".join(bad))
        out = Path(a.out) if a.out else Path(os.environ.get("TEMP") or "/tmp") / "wu-host-kit" / NAME
        write_zip(files, out)
        size = out.stat().st_size
        print(f"[1/2] {NAME}: {len(files)} files, {size // 1024} KB, safety check clean -> {out}")
        for line in summary(files):
            print(line)
        if a.list:
            for rel in sorted(files):
                print(f"    {TOP}/{rel}")
        if a.upload:
            print(f"[2/2] Publishing on {SLUG} (release {TAG})")
            url = upload(out, run, fetch)
            print(f"\nDownload link (the site's host page uses it): {url}")
        print("HOST KIT OK")
        return 0
    except Refused as e:
        print(f"HOST KIT STOPPED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
