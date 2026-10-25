"""Host self-check: is my realm reachable, and if not, what do I do? Plain language, one line per
check. Runs in the tools container on the realm's network (Check my realm.bat / check-realm.sh).

  python -m wuhost.selfcheck [--state /state] [--no-login]

Exit code 0 when players can reach the realm, 1 otherwise.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request

from wunet import keys, wire335

OK, BAD, WARN = "  OK      ", "  PROBLEM ", "  NOTE    "


class Report:
    def __init__(self):
        self.bad = 0

    def ok(self, msg):
        print(OK + msg)

    def warn(self, msg, fix=None):
        print(WARN + msg)
        if fix:
            print("            -> " + fix)

    def fail(self, msg, fix=None):
        self.bad += 1
        print(BAD + msg)
        if fix:
            print("            -> " + fix)


def http_json(url, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "wu-selfcheck/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


async def world_hello(host, port, timeout=10):
    """Connect to a world port and read the server's first packet (SMSG_AUTH_CHALLENGE)."""
    r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    try:
        head = await asyncio.wait_for(r.readexactly(4), timeout)
        return int.from_bytes(head[2:4], "little")
    finally:
        w.close()


def read_login(state):
    try:
        with open(os.path.join(state, "host-login.txt"), encoding="utf-8") as f:
            t = f.read()
        user = t.split("account:")[1].split()[0]
        pw = t.split("password:")[1].split()[0]
        return user, pw
    except (OSError, IndexError):
        return None, None


async def run(state, login=True, db=None, local_auth=("ac-authserver", 3724), local_world=("ac-worldserver", 8085),
              relay_http=None, relay_host=None):
    """relay_http / relay_host: where to reach the relay (default https://<relay>, <relay>)."""
    rep = Report()
    print("Checking your WrathUnleashed realm...\n")
    try:
        with open(os.path.join(state, "host.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        sec = keys.load_or_create(os.path.join(state, "realm.key"))
        if keys.realm_id(keys.public_key(sec)) != cfg["realm_id"]:
            raise ValueError("key and realm id differ")
        rep.ok(f"Realm settings found: \"{cfg['name']}\" ({cfg['profile']}, {cfg['visibility']}).")
    except (OSError, ValueError, KeyError) as e:
        rep.fail(f"The realm settings are missing or broken ({e}).", "Run \"Host a Wrath realm\" again.")
        return rep
    relay = cfg["relay"]
    relay_http = relay_http or f"https://{relay}"
    relay_host = relay_host or relay

    # 1. the database
    if db is not None:
        try:
            st = await asyncio.to_thread(db.status)
            rep.ok(f"The database answers ({st['players']} players and {st['bots']} bots online).")
        except Exception as e:
            rep.fail(f"The realm's database does not answer ({type(e).__name__}).",
                     "Wait a few minutes after starting (the first start imports everything), then check again.")

    # 2. the game servers on this PC
    try:
        code = await wire335.logon_probe(*local_auth, timeout=8)
        if code == 0x04:
            rep.ok("The login server is running.")
        else:
            rep.fail(f"The login server answered oddly (code {code}).", "Look at: docker logs wu-host-authserver")
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, wire335.WowError):
        rep.fail("The login server is not running.", "Start the realm with \"Host a Wrath realm\"; first starts take minutes.")
    try:
        op = await world_hello(*local_world)
        if op == wire335.SMSG_AUTH_CHALLENGE:
            rep.ok("The world server is running.")
        else:
            rep.fail("The world server answered oddly.", "Look at: docker logs wu-host-worldserver")
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
        rep.fail("The world server is not up yet.", "It can take 5-15 minutes on the first start (it builds the bots).")

    # 3. the tunnel
    rs = {}
    try:
        with open(os.path.join(state, "relay-state.json"), encoding="utf-8") as f:
            rs = json.load(f)
    except (OSError, ValueError):
        pass
    if rs.get("connected") and time.time() - rs.get("updated", 0) < 3600 * 24 * 30:
        rep.ok(f"Your realm is connected to the relay ({relay}). Your home address stays hidden.")
    else:
        why = rs.get("last_error") or "no connection yet"
        rep.fail(f"Your realm is not connected to the relay ({why}).",
                 "Check this PC is online; firewalls must allow outgoing HTTPS (port 443). It retries by itself.")
    if rs.get("realmlist_ok"):
        rep.ok(f"The realm list sends players back through the relay (port {rs.get('world_port')}).")
    elif rs.get("connected"):
        rep.fail("The realm list does not point at the relay yet.",
                 "Usually fixes itself within a minute after the database is up. If not: docker logs wu-host-agent")

    # 4. from the outside, through the relay, like a player
    ap, wp = rs.get("auth_port"), rs.get("world_port")
    if ap:
        body = {"invite": cfg["invite_secret"]} if cfg["visibility"] == "private" else {}
        try:
            st, doc = await asyncio.to_thread(http_json, f"{relay_http}/api/realms/{cfg['realm_id']}/knock", body)
            if st == 200:
                rep.ok("Your invite link works." if cfg["visibility"] == "private" else "The join page works.")
            else:
                rep.fail(f"The join page answered {st}: {(doc or {}).get('error')}.")
        except OSError as e:
            rep.fail(f"Could not reach the relay's website ({e}).", "Is this PC online?")
        try:
            code = await wire335.logon_probe(relay_host, ap, timeout=10)
            if code == 0x04:
                rep.ok(f"Players can reach your login server through the relay ({relay}:{ap}).")
            else:
                rep.fail(f"Through the relay the login server answered code {code}.")
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, wire335.WowError) as e:
            rep.fail(f"Players cannot reach your realm through the relay ({type(e).__name__}).",
                     "Run the check again in a minute; if it stays, send the output of this check to the realm team.")
        try:
            op = await world_hello(relay_host, wp)
            if op == wire335.SMSG_AUTH_CHALLENGE:
                rep.ok("Players can reach your world server through the relay.")
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            rep.fail("The world server is not reachable through the relay.")
        user, pw = read_login(state)
        if login and user:
            try:
                rep_ = await wire335.full_run(relay_host, ap, user, pw, enter=False, timeout=20,
                                              world_override=None if relay_host == relay else f"{relay_host}:{wp}")
                rep.ok(f"A real login through the relay works (account {user}, realm \"{rep_['realm']['name']}\").")
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, wire335.WowError) as e:
                rep.fail(f"A real login through the relay failed: {e}", "If the realm just started, wait and check again.")

    # 5. public: the Beacons listing
    if cfg["visibility"] == "public":
        try:
            st, doc = await asyncio.to_thread(http_json, f"{relay_http}/api/listing/realms.json")
            mine = [r for r in (doc or {}).get("realms", []) if r.get("community", {}).get("realmId") == cfg["realm_id"]]
            if mine:
                c = mine[0]["community"]
                rep.ok("Your realm is listed in Beacons" + (f", claimed by {c['claimedBy']}." if c.get("claimed")
                                                             else " (unclaimed: claim it with your Hero Key on the site)."))
            else:
                rep.warn("Your realm is not in the Beacons list yet.", "It appears within a minute or two of going online.")
        except OSError as e:
            rep.warn(f"Could not read the Beacons list ({e}).")
    else:
        rep.ok("Private realm: it is not listed anywhere; only people with your invite link can join.")

    print()
    if rep.bad:
        print(f"{rep.bad} problem(s) found. Players can't join until they're fixed.")
    else:
        realmlist = relay if rs.get("shared_auth_port") == 3724 else f"{relay}:{ap}"
        print("All good. Send your friends the invite link:")
        try:
            with open(os.path.join(state, "invite.txt"), encoding="utf-8") as f:
                print("  " + f.read().strip())
        except OSError:
            pass
        print(f"They open it once on their PC, then play with:  set realmlist {realmlist}")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=os.environ.get("WU_STATE", "/state"))
    ap.add_argument("--no-login", action="store_true")
    a = ap.parse_args(argv)
    db = None
    if os.environ.get("DB_HOST"):
        from .agent import RealmDB
        db = RealmDB(os.environ["DB_HOST"], 3306, "root", os.environ.get("DB_PASSWORD", ""))
    rep = asyncio.run(run(a.state, login=not a.no_login, db=db))
    return 1 if rep.bad else 0


if __name__ == "__main__":
    sys.exit(main())
