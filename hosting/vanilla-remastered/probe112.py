"""The 1.12 realm's self-check probes (run in a throwaway python container on the realm's network by
tools/ov112-off/start-112-realm.sh and hosting/vanilla-remastered/vr-beacon-up.sh). Standard library plus the kit's
wunet (mounted beside this file). Never logs in, never sends a password.

    python3 -I probe112.py logon HOST PORT    a 1.12.1 (build 5875) logon challenge for a made-up account;
                                              ok when the login server answers (0x04: unknown account)
    python3 -I probe112.py world HOST PORT    the world server's first packet is SMSG_AUTH_CHALLENGE
    python3 -I probe112.py http URL           the page answers (any status below 500)

Prints one line; exit 0 when it passed, 1 when not.
"""
import asyncio
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wunet import wire335  # noqa: E402

BUILD = 5875
SMSG_AUTH_CHALLENGE = 0x1EC


async def world_hello(host, port, timeout=10):
    r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    try:
        head = await asyncio.wait_for(r.readexactly(4), timeout)
        return int.from_bytes(head[2:4], "little")
    finally:
        w.close()


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        return 2
    what = argv[0]
    try:
        if what == "logon":
            code = asyncio.run(wire335.logon_probe(argv[1], int(argv[2]), timeout=8, build=BUILD))
            # a real answer for a 1.12.1 client: go on / banned / unknown account / in use. 0x09 (wrong version)
            # means the login server does not take 1.12.1 clients: not ok.
            ok = code in (0x00, 0x03, 0x04, 0x06)
            print(f"logon answer {code:#04x} ({'ok' if ok else 'unexpected'})")
            return 0 if ok else 1
        if what == "world":
            op = asyncio.run(world_hello(argv[1], int(argv[2])))
            ok = op == SMSG_AUTH_CHALLENGE
            print(f"world greeting {op:#06x} ({'ok' if ok else 'unexpected'})")
            return 0 if ok else 1
        if what == "http":
            try:
                with urllib.request.urlopen(urllib.request.Request(argv[1], method="GET"), timeout=10) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            print(f"HTTP {code}")
            return 0 if code < 500 else 1
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, wire335.WowError, ValueError) as e:
        print(f"no answer: {type(e).__name__}")
        return 1
    print("unknown probe")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
