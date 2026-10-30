"""The player side of the docker end-to-end test. Runs in a container on the relay's network, like a
player on the internet: never on the realm's network.

  python e2e_client.py private --state /state --relay-host relay.e2e --relay-http http://relay.e2e:8080 [--account U:P]
  python e2e_client.py public  ...

private: an unknocked IP is refused; a wrong invite is refused; the right invite lets this IP in;
         make an account from the join API (SRP6 verifier, real mode) or use --account (fake mode);
         log in, realm list (the world address must be the relay's), create a character, enter the
         world, ping, log out: on the per-realm port, on the shared 3724 and over the WebSocket path.
public:  (run from a fresh container = a new IP) the per-realm port works with no invite; the
         realm appears in the Beacons listing with players/bots; status.json is live.
Prints one JSON line; exit 0 = pass.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from helpers import ws_opener  # noqa: E402  (also puts kit/tools and relay on sys.path)
from wunet import srp6, wire335, ws  # noqa: E402


def http(method, url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json", "Origin": "https://openvanilla.app"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


class Check:
    def __init__(self):
        self.steps, self.failed = [], []

    def __call__(self, name, cond, detail=""):
        (self.steps if cond else self.failed).append(name + ("" if cond else f": {detail}"))
        print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  ({detail})"), flush=True)
        return cond


async def refused(host, port):
    try:
        await wire335.logon(host, port, "NOBODY", "x", timeout=5)
        return False
    except (wire335.WowError,) as e:
        return "unknown account" not in str(e) and "code" not in str(e)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, OSError):
        return True


async def play(c, label, host, port, user, pw, opener=None, expect_relay=None):
    try:
        rep = await wire335.full_run(host, port, user, pw, opener=opener, timeout=60)
    except Exception as e:  # noqa: BLE001 - report every failure kind
        c(label, False, f"{type(e).__name__}: {e}")
        return None
    ok = rep["steps"][-1] == "logout" and "enter_world" in rep["steps"]
    if expect_relay:
        ok = ok and rep["realm"]["address"].endswith(f":{expect_relay}")
    c(label, ok, json.dumps(rep, default=str)[:300])
    return rep


async def private(a, cfg, rs, c):
    rid, ap, wp = cfg["realm_id"], rs["auth_port"], rs["world_port"]
    st, info = http("GET", f"{a.relay_http}/api/realms/{rid}")
    c("realm online at the relay", st == 200 and info.get("online"), info)
    c("unknocked IP refused (private)", await refused(a.relay_host, ap))
    st, _ = http("POST", f"{a.relay_http}/api/realms/{rid}/knock", {"invite": "WRONGWRONGWRONG"})
    c("wrong invite refused", st == 403, st)
    with_ws = True
    try:
        sock = await ws.connect(f"ws://{a.relay_host}:{a.relay_http.rsplit(':', 1)[1]}/r/{rid}/ws/3724")
        sock.abort()
        with_ws = False
    except ws.HandshakeError as e:
        with_ws = e.status == 403
    c("websocket without invite refused", with_ws)
    st, k = http("POST", f"{a.relay_http}/api/realms/{rid}/knock", {"invite": cfg["invite_secret"]})
    c("invite link lets this IP in", st == 200, k)
    if a.account:
        user, pw = a.account.split(":", 1)
    else:
        user, pw = "E2E" + str(int(time.time()) % 100000), "E2EPASS1"
        salt, ver = srp6.make_verifier(user, pw)
        st, res = http("POST", f"{a.relay_http}/api/realms/{rid}/accounts",
                       {"invite": cfg["invite_secret"], "username": user, "salt": salt.hex(), "verifier": ver.hex()})
        c("account made from the join API", st == 201, res)
    await play(c, "login + char create + enter world + logout (per-realm port)", a.relay_host, ap, user, pw, expect_relay=wp)
    await play(c, "same through the shared port 3724", a.relay_host, a.shared_port, user, pw, expect_relay=wp)
    base = f"ws://{a.relay_host}:{a.relay_http.rsplit(':', 1)[1]}"
    await play(c, "same over the WebSocket path (browser client)", "relay", 3724, user, pw,
               opener=ws_opener(base, rid, invite=cfg["invite_secret"]))
    st, s = http("GET", f"{a.relay_http}/r/{rid}/status.json")
    c("status.json through the relay", st == 200 and s.get("online") is True and "bots" in s, s)
    return user, pw


async def public(a, cfg, rs, c):
    rid, ap, wp = cfg["realm_id"], rs["auth_port"], rs["world_port"]
    user, pw = a.account.split(":", 1)
    for _ in range(30):
        st, info = http("GET", f"{a.relay_http}/api/realms/{rid}")
        if info and info.get("visibility") == "public":
            break
        await asyncio.sleep(1)
    c("relay sees the realm as public", info.get("visibility") == "public", info)
    await play(c, "fresh IP, no invite: login + play (public, per-realm port)", a.relay_host, ap, user, pw, expect_relay=wp)
    rec = None
    for _ in range(40):
        st, doc = http("GET", f"{a.relay_http}/api/listing/realms.json")
        rec = next((r for r in (doc or {}).get("realms", []) if r["community"]["realmId"] == rid), None)
        if rec:
            break
        await asyncio.sleep(3)
    c("listed in Beacons (signed heartbeat)", bool(rec) and rec["official"] is False and
      rec["community"]["claimed"] is False, rec)
    if rec:
        c("listing counts bots separately", "bots" in rec["community"]["lastHeartbeat"], rec["community"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["private", "public"])
    ap.add_argument("--state", default="/state")
    ap.add_argument("--relay-host", default="relay.e2e")
    ap.add_argument("--relay-http", default="http://relay.e2e:8080")
    ap.add_argument("--account", help="USER:PASS (fake realm; real mode makes one through the join API)")
    ap.add_argument("--shared-port", type=int, default=3724)
    ap.add_argument("--save-account", help="write the account used to this file (for the public phase)")
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(a.state, "host.json")))
    rs = json.load(open(os.path.join(a.state, "relay-state.json")))
    c = Check()
    if a.mode == "private":
        user, pw = asyncio.run(private(a, cfg, rs, c))
        if a.save_account:
            with open(a.save_account, "w") as f:
                f.write(f"{user}:{pw}")
    else:
        asyncio.run(public(a, cfg, rs, c))
    print(json.dumps({"mode": a.mode, "ok": not c.failed, "passed": len(c.steps), "failed": c.failed}))
    return 0 if not c.failed else 1


if __name__ == "__main__":
    sys.exit(main())
