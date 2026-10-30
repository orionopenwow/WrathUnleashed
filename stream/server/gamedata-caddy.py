#!/usr/bin/env python3
"""The game data killswitch's Caddy part: a small block inside the streaming site (stream-up.sh's block for
wrath.openvanilla.app) that answers every game-data route with 410 Gone, before the sign-in gate and before
wu-play are ever asked.

    python3 -I gamedata-caddy.py add    <Caddyfile> [<stream host>]   put the block in (idempotent)
    python3 -I gamedata-caddy.py remove <Caddyfile>                   take it out (idempotent)
    python3 -I gamedata-caddy.py status <Caddyfile>                   "on" (block in), "off", or "no-site"

Exit codes: 0 done, 3 no streaming site block in the Caddyfile (then nothing on that site is served at all, so
there is nothing to switch), 2 a broken Caddyfile (a start marker without its end marker).

The routes it closes (docs/GAME-DATA-ON-OUR-SERVER.md):
    /data and /data/*        the slice, the Forever UI overlay laid over it, /data/__index, /data/__tier/*
    /boot-manifest.json      the boot read-set: game file names (paths inside the game's archives)
    /world-manifest.json     the world read-set: the same, for the world
The page, the client's own code (/wenilla.js, the wasm, /boot.js, ...), /__gate, /__env.js and /ws stay as they
are: a player with their own game folder still plays (ownfiles.js answers /data in the page itself).

Standard library only. The Caddyfile is edited in place (it is bind-mounted into Caddy's container).
"""
from __future__ import annotations

import sys

STREAM_BEGIN = "# >>> WrathUnleashed streaming (stream-up.sh)"
STREAM_END = "# <<< WrathUnleashed streaming"
BEGIN = "\t# >>> game data killswitch (gamedata-switch.sh)"
END = "\t# <<< game data killswitch"
ROUTES = ("/data", "/data/*", "/boot-manifest.json", "/world-manifest.json")
PLAY_OWN = "https://play.openvanilla.app/wrath/play?mode=own"
# The answer: small JSON the client and the launcher can read, and plain words for anyone who opens it.
BODY = ('{"error":"gamedata_off","gamedata_streaming":false,'
        '"message":"This realm needs your own game folder. Drop your 3.3.5a game folder on the game page.",'
        '"own_files":"' + PLAY_OWN + '"}')


def block() -> str:
    """The lines that go right after the site's opening line (tab-indented like stream-up.sh's block)."""
    return (f"{BEGIN}: no game data from this server.\n"
            "\t# Every game-data route answers 410 Gone before the sign-in gate or wu-play is asked.\n"
            "\t# Undo: bash /srv/wrath/stream/gamedata-switch.sh on\n"
            f"\t@gamedata_off path {' '.join(ROUTES)}\n"
            "\thandle @gamedata_off {\n"
            '\t\theader Content-Type "application/json; charset=utf-8"\n'
            '\t\theader Cache-Control "no-store"\n'
            "\t\theader Cross-Origin-Resource-Policy same-origin\n"
            f"\t\trespond `{BODY}` 410\n"
            "\t}\n"
            f"{END}\n")


def _site(s: str) -> tuple[int, int] | None:
    """(start, end) of stream-up.sh's block, or None when the Caddyfile has none."""
    if STREAM_BEGIN not in s:
        return None
    i = s.index(STREAM_BEGIN)
    j = s.find(STREAM_END, i)
    if j < 0:
        raise ValueError("the streaming block's start marker has no end marker")
    return i, j


def strip(s: str) -> str:
    """The Caddyfile without our block (every copy of it)."""
    while BEGIN in s:
        i = s.index(BEGIN)
        j = s.find(END, i)
        if j < 0:
            raise ValueError("the killswitch start marker has no end marker")
        j = s.find("\n", j)
        s = s[:i] + (s[j + 1:] if j >= 0 else "")
    return s


def add(s: str, host: str = "wrath.openvanilla.app") -> str:
    """The Caddyfile with our block first inside the streaming site. Raises LookupError when there is no site."""
    s = strip(s)
    span = _site(s)
    if span is None:
        raise LookupError("no streaming site block")
    i, j = span
    opening = f"\n{host} {{\n"
    k = s.find(opening, i, j)
    if k < 0:
        raise LookupError(f"the streaming block has no '{host} {{' line")
    k += len(opening)
    return s[:k] + block() + s[k:]


def status(s: str) -> str:
    if _site(s) is None:
        return "no-site"
    return "on" if BEGIN in s else "off"


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("add", "remove", "status"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 64
    cmd, path = argv[1], argv[2]
    host = argv[3] if len(argv) > 3 else "wrath.openvanilla.app"
    with open(path, encoding="utf-8") as f:
        s = f.read()
    try:
        if cmd == "status":
            print(status(s))
            return 0
        new = add(s, host) if cmd == "add" else strip(s)
    except LookupError as e:
        print(f"  {e}: nothing to change on that site", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if new != s:
        with open(path, "r+", encoding="utf-8") as f:
            f.seek(0)
            f.write(new)
            f.truncate()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
