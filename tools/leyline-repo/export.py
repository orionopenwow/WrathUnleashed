#!/usr/bin/env python3
"""Leyline's own repo (github.com/orionopenwow/Leyline): copy the network's parts out of WrathUnleashed.

    py -3 tools\\leyline-repo\\export.py .repos\\leyline-public
    python3 tools/leyline-repo/export.py TARGET [--source REPO] [--dry-run] [--list-exec]

Only the paths in ALLOW are copied, at the same paths as here (so the hosting tests run there as they do
here). The export also writes README.md, LICENSE, THIRD-PARTY-NOTICES.md and .gitignore at the top.

Safety, in this order, before anything is written:
  * game data (.mpq .m2 .wmo .adt .blp .dbc .skin .anim ..., .tgz and its parts), secrets (.env files other than
    *.example, keys, *.pem, tokens, private-key text), logs, decompiled code and original-binary citations (stock-client addresses and symbols) are refused. Machine-local folders
    (state/, cache/, logs/, realm-files/, __pycache__/, .git/) are never entered. A refused file that ALLOW names
    on its own stops the export; one found inside an allowed folder is left out and listed as REFUSED.
  * the brand check: the README, every user-facing .html and every page under docs/ must not name the game or its maker. A hit stops the
    export (exit 1) and nothing is written.
Then the sync: a file is rewritten only when its bytes changed, and files that are no longer exported are deleted,
but only inside the folders the export manages (MANAGED, the top folders of ALLOW), never in .git and never
anywhere else in the target. Same source in, same bytes out: no dates, sorted order.

Exit codes: 0 ok, 1 refused (brand words, a named file refused, a bad target), 2 usage.
Standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADDON = "stream/fui-web/Interface/AddOns/WrathUnleashedUI"

# The allow-list: folders (copied whole, minus refusals), single files, and globs. Paths as in this repo.
# Public = the launcher, the host kit, the relay and their docs (docs/REPO-MAP.md marks them "public"). Never labs/,
# client/ (our client patches), server/, tools/ or the Autopilot files: those stay in the private repo.
ALLOW = [
    "hosting/relay",                              # the relay (wurelay, its Dockerfile and deploy scripts)
    "hosting/kit",                                # the host kit: the `leyline` command, host scripts, compose
    #   (hosting/kit/tools is inside it: wunet, wuhost, the tools image)
    "hosting/discord",                            # the Discord bridge
    "hosting/tests",                              # the hosting tests
    "hosting/README.md",
    "hosting/INSTALL-OPERATE.md",
    f"{ADDON}/Leyline.lua",                       # the in-game Leyline window (needs only the addon's table)
    f"{ADDON}/Style.lua",                         # the Leyline look for the in-game windows (Leyline.lua uses it when there)
    f"{ADDON}/Host.lua",                          # the in-game Host window: set up a realm, and Your realm for its GM
    f"{ADDON}/Media",                             # its art: our own TGA files (stream/fui-web/make-wuui-media.py)
    "stream/fui-web/make-wuui-media.py",          # makes that art from the Leyline art
    "realm/custom/lua_scripts/ov_hostctl.lua",    # Your realm's realm half (GM only)
    "realm/custom/lua_scripts/ov_leyline.lua",    # its realm half: the WULY realm list
    "realm/custom/lua_scripts/ov_discord.lua",    # the Discord bridge's realm half
    "stream/links.py",                            # short share links (/r /h /q /m /u)
    "stream/playmodes.json",                      # the mode catalog the launcher builds in (modes.rs include_str!)
    "stream/www-files/art/leyline-*",             # the Leyline art, leyline-display-OFL.txt included
    "mods/SPEC.md",                               # the mod package format
    "docs/leyline",                               # the Leyline docs (also served at /wrath/docs)
    "launcher",                                   # the Leyline desktop launcher (Tauri 2: web UI over a Rust core)
]
# The top folders the export owns in the target: it deletes stale files only below these.
MANAGED = sorted({p.split("/", 1)[0] for p in ALLOW})
GENERATED = ["README.md", "LICENSE", "THIRD-PARTY-NOTICES.md", ".gitignore"]

# Folders never entered (machine-local, build output, caches, version control).
SKIP_DIRS = {"state", "cache", "logs", "realm-files", "__pycache__", ".git", "node_modules", ".pytest_cache",
             "target", "gen"}                    # target/, gen/: the launcher's Rust and Tauri build output
JUNK = re.compile(r"(\.pyc|\.pyo|~|\.swp|\.DS_Store|Thumbs\.db|desktop\.ini)$", re.I)

GAME_DATA = re.compile(r"\.(mpq|m2|wmo|adt|wdt|wdl|blp|dbc|db2|skin|anim|bls|phys|bone|lit|mdx|wlw|wlq|zmp)$"
                       r"|\.tgz($|\.)|\.tar\.gz$|\.part\.?\d+$|\.part\.[a-z0-9]+$", re.I)
SECRET_NAME = re.compile(r"(^|/)\.env$|\.env$|\.(pem|key|p12|pfx|jks|keystore|crt|der|secret|kdbx)$"
                         r"|(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$|token|credential|passw|host-login|"
                         r"\.netrc$|\.pgpass$|\.npmrc$|(^|/)secrets?(/|\.|$)", re.I)
SECRET_TEXT = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30}|github_pat_[A-Za-z0-9_]{30}"
                         rb"|xox[abp]-[A-Za-z0-9-]{10}|AKIA[0-9A-Z]{16}"
                         rb"|[MN][A-Za-z\d]{23,25}\.[\w-]{6}\.[\w-]{27,}")     # a Discord bot token's shape
LOG_NAME = re.compile(r"\.log(\.\d+)?$|(^|/)logs?\.txt$|\.(dmp|trace)$", re.I)
DECOMP_NAME = re.compile(r"decomp|ghidra|hexrays|\.(idb|i64|gzf|til|nam|id0|id1)$|(^|/)ida[_-]", re.I)
DECOMP_TEXT = re.compile(rb"Hex-Rays decompiler|Generated by Ghidra|Decompiled (with|by) |\bIDA Pro\b"
                         rb"|Decompiled from ", re.I)
# Original-binary citations: the stock client's addresses and internal symbols ("`CanTargetUnit 0x6e4440`",
# "`[0xcf0bc8]`", "CGGameUI::SetUIScale", "the reference's"). Our files describe behaviour in plain words; a file
# that cites the stock binary is refused. In a .patch/.diff only the lines it adds count (context is upstream's).
CITE_TEXT = re.compile(
    rb"`\[?0x[0-9a-fA-F]{6,8}\]?`"                                        # `0x689110`, `[0xbd0778]`
    rb"|\[0x[0-9a-fA-F]{6,8}\]"                                           # [0xcf0bc8]
    rb"|\b[A-Z][a-z0-9]+(?:_?[A-Z][a-z0-9]*)+\s+`?0x[0-9a-fA-F]{6,8}\b"   # CanTargetUnit 0x6e4440
    rb"|\b(?:C(?!Str\b|String\b)[A-Z][A-Za-z0-9]*|[A-Z][A-Za-z0-9]*_C)::[A-Za-z_]\w*"   # CGGameUI::SetUIScale
    rb"|\bsub_[0-9A-Fa-f]{6,}\b"
    rb"|(?i:\bthe reference(?:'s\b| client\b| binary\b| exe\b)|\bas the reference does\b)")


def citation(rel: str, data: bytes):
    """The first original-binary citation in the file (only added lines of a patch), or None."""
    if rel.endswith((".patch", ".diff")):
        data = b"\n".join(l[1:] for l in data.split(b"\n") if l.startswith(b"+") and not l.startswith(b"+++"))
    m = CITE_TEXT.search(data)
    return m.group(0).decode("utf-8", "replace") if m else None


# Public config that carries an .env name: allowed only by exact path, and only with these keys.
PUBLIC_ENV = {"hosting/kit/tools/wunet/leyline.env": {"LEYLINE_DOMAIN"}}

BANNED = [re.compile(r"world\s+of\s+warcraft", re.I), re.compile(r"warcraft", re.I),
          re.compile(r"lich\s+king", re.I), re.compile(r"blizzard", re.I), re.compile(r"\bWoW\b")]


class Refused(Exception):
    pass


def refusal(rel: str, data: bytes) -> str | None:
    """Why this file must not be exported, or None."""
    name = rel.rsplit("/", 1)[-1]
    if GAME_DATA.search(name):
        return "game data"
    if LOG_NAME.search(rel):
        return "log"
    if DECOMP_NAME.search(rel) or DECOMP_TEXT.search(data):
        return "decompiled code"
    cite = citation(rel, data)
    if cite:
        return f"original-binary citation ({cite})"
    if rel in PUBLIC_ENV:
        keys = {l.split("=", 1)[0].strip() for l in data.decode("utf-8", "replace").splitlines()
                if l.strip() and not l.lstrip().startswith("#")}
        if not keys <= PUBLIC_ENV[rel]:
            return "secret (.env with unexpected keys: " + ", ".join(sorted(keys - PUBLIC_ENV[rel])) + ")"
    elif not name.endswith(".example") and (".env" in name.lower() or SECRET_NAME.search(rel)):
        return "secret"
    if SECRET_TEXT.search(data):
        return "secret (key or token inside)"
    return None


def walk(root: Path, top: str):
    """Every file under root/top, sorted, as repo-relative posix paths, plus the folders left out."""
    files, skipped = [], []
    base = root / top
    for d, dirs, names in os.walk(base):
        rd = Path(d).relative_to(root).as_posix()
        for x in sorted(dirs):
            if x in SKIP_DIRS or x.startswith(".git"):
                skipped.append(f"{rd}/{x}/")
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith(".git"))
        for n in sorted(names):
            if not JUNK.search(n):
                files.append(f"{rd}/{n}")
    return files, skipped


def plan(src: Path):
    """{rel: (bytes, executable)} for every exported file, the REFUSED list and the skipped folders."""
    out, refused, skipped = {}, [], []
    for entry in ALLOW:
        if any(c in entry for c in "*?["):
            parent = entry.rsplit("/", 1)[0]
            pdir = src / parent
            names = sorted(n for n in (os.listdir(pdir) if pdir.is_dir() else [])
                           if fnmatch.fnmatchcase(n, entry.rsplit("/", 1)[1]) and (pdir / n).is_file())
            if not names:
                raise Refused(f"the allow-list entry {entry} matches nothing in {src}")
            cands, named = [f"{parent}/{n}" for n in names], False
        elif (src / entry).is_dir():
            cands, sk = walk(src, entry)
            skipped += sk
            named = False
        elif (src / entry).is_file():
            cands, named = [entry], True
        else:
            raise Refused(f"the allow-list entry {entry} is missing from {src}")
        for rel in cands:
            p = src / rel
            if p.is_symlink():
                refused.append((rel, "symlink"))
                continue
            data = p.read_bytes()
            why = refusal(rel, data)
            if why:
                if named:
                    raise Refused(f"{rel} is on the allow-list but looks like {why}: not exported")
                refused.append((rel, why))
                continue
            out[rel] = (data, data.startswith(b"#!"))           # shebang only: same answer on Windows
    return out, refused, skipped


# --------------------------------------------------------------------------------------------- generated files
README = """# Leyline

Leyline is a **mod launcher** and a **peer-to-peer realm network** for classic game clients.

- **Host a realm in one click**, from the browser or the desktop launcher. It runs on your own PC (Docker is
  the only thing it needs) and is listed for everyone on the Leyline realm list. No port forwarding: your realm
  talks out to a Leyline relay, players connect to the relay, and nobody sees your home address.
- **Mods and addons hub**: find, install, update and share mods, addons, game modes and themes. The launcher
  installs them into your own client in one click and checks every file first.
- **Play in your browser** (nothing to install), or **with your own client**: the launcher finds the client you
  already have, points it at the realm you picked and starts it.
- **A sample realm to try**: our temporary *Dalaran Hangout* (3.3.5a) is a Leyline realm like any other, and
  it gets our client additions first.
- **Open source**, MIT licensed. No game data is in this repo: hosts extract what their realm needs from their
  own install, on their own PC, and it never leaves it.

## Quick start: host a realm

From the browser: sign in on the Leyline site, press **Host a realm**, choose a name and house rules, and run
the one-click setup it gives you. From the desktop launcher: open **Host**.

Or by hand. macOS or Linux, with Docker running:

```sh
git clone https://github.com/orionopenwow/Leyline.git
cd Leyline/hosting/kit
bash leyline host        # a few questions the first time; safe to run again
bash leyline status      # your invite or join link
```

Windows: double-click `hosting/kit/Host a Leyline realm.bat`. Full guide: `hosting/INSTALL-OPERATE.md`.
The host kit runs 3.3.5a realms (AzerothCore) and, with its profiles, 1.12.1 and 2.4.3 realms too.

To play on a realm, open its join link (`https://relay.<domain>/join/<realm id>`) and follow the page, or pick
it on the launcher's **Realms** page.

## Run the tests

```sh
cd hosting/tests && python3 -m unittest discover -s . -p 'test_*.py'
```

A few tests read files that only the WrathUnleashed repo has (realm profiles, CI workflows, its control
panel); run those there.

## Layout

| Path | What it is |
|---|---|
| `hosting/relay/` | the relay: tunnels for hosts, the join page, the realm listing, per-IP limits |
| `hosting/kit/` | the host kit: the `leyline` command, host scripts, Docker compose |
| `hosting/kit/tools/` | the host agent, setup and self-check (`wuhost`), the shared network code (`wunet`) |
| `hosting/discord/` | the Discord bridge |
| `hosting/tests/` | tests for all of the above |
| `realm/custom/lua_scripts/` | the realm-side scripts the Leyline window and the Discord bridge talk to |
| `stream/fui-web/.../Leyline.lua` | the in-game Leyline window (`/leyline`); it runs inside the WrathUnleashed UI addon |
| `stream/links.py` | short share links for realms, hangouts, queues, mods and players |
| `stream/www-files/art/` | the Leyline art and display font (SIL OFL 1.1) |
| `mods/SPEC.md` | the mod package format |
| `docs/leyline/` | the Leyline docs: play, mods, publishing, hosting, launcher, Hero Key, other servers, commands |
| `stream/playmodes.json` | the game-mode catalog the launcher builds in |
| `launcher/` | the Leyline desktop launcher (Windows, macOS, Linux): clients, mods, realms, hosting. Build steps in `launcher/README.md` |

The Mods & Workshop panel (`ModsPanel.lua`) uses the rest of the WrathUnleashed UI addon, so it stays in
WrathUnleashed; the in-game window here opens from it.

## Where this comes from

This repo is copied from [WrathUnleashed](https://github.com/orionopenwow/WrathUnleashed) by its
`tools/leyline-repo/export.py`. Send changes there: anything changed only here is replaced on the next copy.

- WrathUnleashed: https://github.com/orionopenwow/WrathUnleashed
- The mod format and template: https://github.com/orionopenwow/WrathUnleashed/tree/main/mods

## License

MIT (see `LICENSE`). Third-party parts and their licenses: `THIRD-PARTY-NOTICES.md`.
"""

NOTICES = """# Third-party notices

Leyline's own code is MIT licensed (`LICENSE`). These parts come from elsewhere or work with outside software:

- **Leyline display font** (`stream/www-files/art/leyline-display.woff2`): Big Shoulders Display,
  SIL Open Font License 1.1. The license is next to it: `stream/www-files/art/leyline-display-OFL.txt`.
- **Launcher font** (`launcher/ui/art/fonts/`): Inter, SIL Open Font License 1.1. The license is next to it:
  `Inter-OFL.txt`.
- **Ed25519 fallback** (`hosting/kit/tools/wunet/ed25519_pure.py`): from the Leyline Launcher (the older Python launcher), the same
  project, MIT.
- **SRP6 test vectors** (`hosting/tests/test_crypto.py`): from a public MIT-licensed SRP test corpus.
- **AzerothCore** (AGPL-3.0): the realm images the host kit runs are built from AzerothCore and its modules.
  No AzerothCore source is in this repo; its sources are at https://github.com/azerothcore.
- **Tauri** (MIT or Apache-2.0) and the Rust crates in `launcher/src-tauri/Cargo.lock`, each under its own
  license (mostly MIT or Apache-2.0): the launcher is built with them; none of their source is in this repo.
- **Other server cores** (host any client): the host kit's profiles in `hosting/kit/profiles/` build CMaNGOS
  Classic and TBC (GPL-2.0, https://github.com/cmangos) and TrinityCore 4.3.4 (GPL-2.0,
  https://github.com/The-Cataclysm-Preservation-Project/TrinityCore) on the host's PC from that source at pinned
  commits, with each project's own database. None of their source is in this repo; credits and licences: each
  profile's `NOTICE.md`.
- **Game data**: none here. Hosts extract dbc and map files from their own client of the realm's version (3.3.5a,
  or 1.12.1, 2.4.3, 4.3.4 for the other profiles), on their own PC, and they never leave it.
"""

GITIGNORE = """# Leyline: our own code and docs only. Never game data, secrets or machine-local files.
**/state/
**/cache/
**/realm-files/
**/logs/
.env
*.env
!*.env.example
!hosting/kit/tools/wunet/leyline.env
*.pem
*.key
*.log
__pycache__/
*.pyc
node_modules/
launcher/src-tauri/target/
launcher/src-tauri/gen/
*.mpq
*.MPQ
*.m2
*.wmo
*.adt
*.blp
*.dbc
*.skin
*.anim
*.tgz
*.part*
.DS_Store
Thumbs.db
"""


def license_text(src: Path) -> bytes:
    """The repo's own license (MIT): a top-level LICENSE if the repo has one, else the mod template's."""
    for p in (src / "LICENSE", src / "mods" / "template" / "LICENSE"):
        if p.is_file():
            b = p.read_bytes()
            if not b.lstrip().startswith(b"MIT License"):
                raise Refused(f"{p} is not the MIT license: check which license Leyline should use")
            return b
    raise Refused("no LICENSE found in the repo (LICENSE or mods/template/LICENSE)")


def brand_hits(rel: str, data: bytes) -> list[str]:
    text = data.decode("utf-8", "replace")
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for rx in BANNED:
            m = rx.search(line)
            if m:
                hits.append(f"{rel}:{n}: \"{m.group(0)}\"")
                break
    return hits


def user_facing(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1].lower()
    return (name.endswith((".html", ".htm")) or (name.startswith("readme") and "/tests/" not in f"/{rel}")
            or (rel.startswith("docs/") and name.endswith(".md")))


# ------------------------------------------------------------------------------------------------------- sync
def write_if_changed(path: Path, data: bytes, exe: bool) -> bool:
    changed = False
    try:
        changed = path.read_bytes() != data
    except OSError:
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".leyline-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    if os.name != "nt":
        mode = path.stat().st_mode
        want = (mode | 0o111) if exe else (mode & ~0o111)
        if want != mode:
            os.chmod(path, want)
            changed = True
    return changed


def stale(target: Path, keep: set[str]) -> list[str]:
    """Files under the managed folders of target that the export no longer makes (never in .git)."""
    out = []
    for top in MANAGED:
        base = target / top
        if not base.is_dir() or base.is_symlink():
            continue
        for d, dirs, names in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x != ".git" and not (Path(d) / x).is_symlink())
            for n in sorted(names):
                rel = (Path(d) / n).relative_to(target).as_posix()
                if rel not in keep:
                    out.append(rel)
    return out


def prune_empty(target: Path) -> None:
    for top in MANAGED:
        base = target / top
        if not base.is_dir():
            continue
        for d, dirs, names in sorted(os.walk(base, topdown=False), key=lambda t: -len(t[0])):
            if ".git" in Path(d).relative_to(target).parts:
                continue
            try:
                if not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass


INCLUDE_RE = re.compile(rb'include_(?:str|bytes)!\(\s*"([^"]+)"\s*\)')


def missing_includes(files: dict) -> list:
    """Every include_str!/include_bytes! in an exported .rs file must point at an exported file, or the
    Leyline repo's launcher build fails (2026-10-30: modes.rs and stream/playmodes.json)."""
    out = []
    for rel, (data, _x) in files.items():
        if not rel.endswith(".rs"):
            continue
        base = rel.rsplit("/", 1)[0]
        for m in INCLUDE_RE.finditer(data):
            parts = (base + "/" + m.group(1).decode()).split("/")
            norm = []
            for part in parts:
                if part == "..":
                    if norm:
                        norm.pop()
                elif part not in ("", "."):
                    norm.append(part)
            target = "/".join(norm)
            if target not in files:
                out.append(f"{rel}: {m.group(1).decode()} -> {target}")
    return out


def export(src: Path, target: Path, dry: bool = False, out=print) -> dict:
    src, target = src.resolve(), target.resolve()
    # Inside the workspace only under .repos/ (gitignored; "Move to Leyline.bat" puts the public clone at
    # .repos/leyline-public). Never the workspace itself, a folder holding it, or anywhere else inside it.
    in_repos = (src / ".repos") in target.parents
    if target == src or target in src.parents or (src in target.parents and not in_repos):
        raise Refused(f"the target {target} must be outside the workspace folder (or under its .repos/), "
                      "and not contain it")
    files, refused, skipped = plan(src)
    files["README.md"] = (README.encode(), False)
    files["LICENSE"] = (license_text(src), False)
    files["THIRD-PARTY-NOTICES.md"] = (NOTICES.encode(), False)
    files[".gitignore"] = (GITIGNORE.encode(), False)

    missing = missing_includes(files)
    if missing:
        raise Refused("the launcher builds in files the export leaves out (its build would fail):\n  "
                      + "\n  ".join(missing))
    hits = [h for rel in sorted(files) if user_facing(rel) for h in brand_hits(rel, files[rel][0])]
    if hits:
        raise Refused("brand words in user-facing files (nothing was written):\n  " + "\n  ".join(hits))

    for rel, why in refused:
        out(f"REFUSED {rel} ({why})")
    for d in skipped:
        if not d.endswith(("__pycache__/", ".pytest_cache/")):
            out(f"skipped {d} (machine-local, never exported)")

    written, deleted = [], []
    if not dry:
        target.mkdir(parents=True, exist_ok=True)
    for rel in sorted(files):
        data, exe = files[rel]
        if dry:
            p = target / rel
            if not p.is_file() or p.read_bytes() != data:
                written.append(rel)
        elif write_if_changed(target / rel, data, exe):
            written.append(rel)
    for rel in stale(target, set(files)):
        deleted.append(rel)
        if not dry:
            (target / rel).unlink()
    if not dry:
        prune_empty(target)
    for rel in written:
        out(f"wrote   {rel}")
    for rel in deleted:
        out(f"deleted {rel}")
    out(f"Leyline export: {len(files)} files, {len(written)} written, {len(deleted)} deleted, "
        f"{len(refused)} refused{' (dry run)' if dry else ''} -> {target}")
    return {"files": sorted(files), "written": written, "deleted": deleted, "refused": refused,
            "exec": sorted(r for r, (_, e) in files.items() if e)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Copy Leyline's parts of WrathUnleashed into the Leyline repo folder.")
    ap.add_argument("target", nargs="?")
    ap.add_argument("--source", default=str(REPO), help="the WrathUnleashed folder (default: this repo)")
    ap.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    ap.add_argument("--list-exec", action="store_true", help="print the exported files that are executable")
    a = ap.parse_args(argv)
    try:
        if a.list_exec:
            files, _, _ = plan(Path(a.source).resolve())
            for rel in sorted(r for r, (_, e) in files.items() if e):
                print(rel)
            return 0
        if not a.target:
            ap.print_usage(sys.stderr)
            return 2
        export(Path(a.source), Path(a.target), a.dry_run)
        return 0
    except Refused as e:
        print(f"EXPORT STOPPED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
