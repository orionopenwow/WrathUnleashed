"""The relay, end to end in one process: real relay + real agent + fake AzerothCore realm + the
real headless 3.3.5a client. Multiplexing, private secrets, caps, reconnects, accounts, status."""
import asyncio
import json
import time
import unittest

from helpers import Rig, http, srp_account, ws_opener, free_port
from wunet import keys, mux, ws, wire335


async def full(r, user, pw, auth_port=None, opener=None, **kw):
    return await wire335.full_run("127.0.0.1", auth_port or r.ports[0], user, pw, opener=opener, **kw)


def local_world(r):
    """Clients in tests reach 'relay.test:<port>' at 127.0.0.1."""
    return f"127.0.0.1:{r.ports[1]}"


class Public(unittest.IsolatedAsyncioTestCase):
    async def test_login_through_relay_per_realm_port(self):
        async with Rig() as r:
            r.realm.add_account("alice", "pw")
            # the agent pointed the realm list at the relay's per-realm world port
            self.assertEqual(r.realm.world_address, f"relay.test:{r.ports[1]}")
            self.assertEqual(r.db.address_calls[-1], ("Test Realm", "relay.test", r.ports[1]))
            rep = await full(r, "alice", "pw", world_override=local_world(r))
            self.assertEqual(rep["steps"][-1], "logout")
            self.assertEqual(rep["realm"]["address"], f"relay.test:{r.ports[1]}")
            # nothing lingers
            await asyncio.sleep(0.2)
            self.assertEqual(len(r.relay.sessions[r.rid].streams), 0)
            self.assertEqual(len(r.agent.streams), 0)

    async def test_shared_port_needs_a_knock(self):
        async with Rig() as r:
            r.realm.add_account("bob", "pw")
            with self.assertRaises((wire335.WowError, asyncio.IncompleteReadError, ConnectionError)):
                await wire335.logon("127.0.0.1", r.shared, "bob", "pw", timeout=3)
            st, body, hdr = await http("POST", f"{r.http}/api/realms/{r.rid}/knock", {},
                                       {"Origin": "https://openvanilla.test"})
            self.assertEqual(st, 200, body)
            self.assertEqual(hdr.get("access-control-allow-origin"), "https://openvanilla.test")
            self.assertTrue(body["realmlist_port"].endswith(str(r.ports[0])))
            rep = await full(r, "bob", "pw", auth_port=r.shared, world_override=local_world(r))
            self.assertIn("enter_world", rep["steps"])

    async def test_browser_websocket_path(self):
        async with Rig() as r:
            r.realm.add_account("carol", "pw")
            op = ws_opener(r.base, r.rid)
            rep = await wire335.full_run("relay.test", 3724, "carol", "pw", opener=op)  # world via the realm's port
            self.assertEqual(rep["steps"][-1], "logout")
            st, body, _ = await http("GET", f"{r.http}/r/{r.rid}/ws/9999")
            self.assertEqual(st, 404)

    async def test_many_players_multiplexed(self):
        # every test player shares 127.0.0.1, so lift the per-IP caps (tested in Caps)
        async with Rig(max_streams_per_ip=64, max_streams_per_ip_total=64, conn_rate_per_ip=500) as r:
            for i in range(12):
                r.realm.add_account(f"p{i}", "pw")
            reps = await asyncio.gather(*[full(r, f"p{i}", "pw", world_override=local_world(r)) for i in range(12)])
            self.assertTrue(all(x["steps"][-1] == "logout" for x in reps))
            self.assertEqual(len({x["character"]["name"] for x in reps}), 12)
            self.assertGreaterEqual(r.relay.metrics["streams_opened"], 24)
            # one tunnel carried all of them
            self.assertEqual(r.relay.metrics["agent_logins"], 1)

    async def test_status_and_metrics(self):
        async with Rig() as r:
            st, body, hdr = await http("GET", f"{r.http}/r/{r.rid}/status.json")
            self.assertEqual(st, 200)
            self.assertEqual(hdr["access-control-allow-origin"], "*")
            self.assertEqual((body["online"], body["players"], body["bots"], body["build"]), (True, 2, 40, "3.3.5a"))
            self.assertEqual(body["realm"], "Test Realm")
            st, text, _ = await http("GET", f"{r.http}/metrics")
            self.assertIn("wu_relay_realms_online 1", text)
            st, info, _ = await http("GET", f"{r.http}/api/realms/{r.rid}")
            self.assertEqual((info["online"], info["auth_port"]), (True, r.ports[0]))


class Private(unittest.IsolatedAsyncioTestCase):
    async def test_private_needs_the_secret(self):
        async with Rig(visibility="private") as r:
            r.realm.add_account("dave", "pw")
            # TCP from an IP that never knocked: closed at once
            with self.assertRaises((wire335.WowError, asyncio.IncompleteReadError, ConnectionError)):
                await wire335.logon("127.0.0.1", r.ports[0], "dave", "pw", timeout=3)
            self.assertGreaterEqual(r.relay.metrics["refused_403"], 1)
            # wrong secret
            st, body, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/knock", {"invite": "WRONG"})
            self.assertEqual(st, 403)
            # websocket without / with the secret
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/r/{r.rid}/ws/3724")
            self.assertEqual(cm.exception.status, 403)
            rep = await wire335.full_run("relay.test", 3724, "dave", "pw",
                                         opener=ws_opener(r.base, r.rid, invite=r.cfg["invite_secret"]))
            self.assertIn("enter_world", rep["steps"])
            # the path form (for clients that only take a base URL)
            sock = await ws.connect(f"{r.base}/r/{r.rid}/i/{r.cfg['invite_secret']}/ws/3724")
            sock.abort()

    async def test_knock_then_tcp_works_and_new_secret_locks_out(self):
        async with Rig(visibility="private") as r:
            r.realm.add_account("erin", "pw")
            st, body, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/knock", {"invite": r.cfg["invite_secret"]})
            self.assertEqual(st, 200, body)
            rep = await full(r, "erin", "pw", world_override=local_world(r))
            self.assertIn("logout", rep["steps"])
            # host makes a new invite link: the old secret stops working for new knocks
            cfg = json.load(open(f"{r.host_dir}/host.json"))
            old = cfg["invite_secret"]
            cfg["invite_secret"] = "NEWSECRETNEWSECRET22"
            json.dump(cfg, open(f"{r.host_dir}/host.json", "w"))
            r.agent.cfg_mtime = 0
            for _ in range(100):
                await asyncio.sleep(0.05)
                if r.relay.sessions[r.rid].invite_sha != r.agent.invite_sha() or \
                        r.relay.sessions[r.rid].invite_sha == __import__("hashlib").sha256(b"NEWSECRETNEWSECRET22").hexdigest():
                    break
            st, _, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/knock", {"invite": old})
            self.assertEqual(st, 403)
            st, _, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/knock", {"invite": "NEWSECRETNEWSECRET22"})
            self.assertEqual(st, 200)


class Accounts(unittest.IsolatedAsyncioTestCase):
    async def test_signup_from_join_page_then_play(self):
        async with Rig(visibility="private") as r:
            acc = srp_account("friend1", "hunter2")
            st, body, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts", acc)
            self.assertEqual(st, 403)   # no invite
            st, body, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts",
                                     dict(acc, invite=r.cfg["invite_secret"]))
            self.assertEqual(st, 201, body)
            st, body, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts",
                                     dict(acc, invite=r.cfg["invite_secret"]))
            self.assertEqual(st, 409)   # taken
            # signing up knocked this IP: the stock-client path works now
            rep = await full(r, "friend1", "hunter2", world_override=local_world(r))
            self.assertIn("enter_world", rep["steps"])
            st, body, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts",
                                     dict(srp_account("x!", "y"), invite=r.cfg["invite_secret"]))
            self.assertEqual(st, 400)

    async def test_signup_rate_limit_and_off(self):
        async with Rig(visibility="public", signup="open", accounts_per_ip_hour=2) as r:
            for i in range(2):
                st, _, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts", srp_account(f"pl{i}", "pw"))
                self.assertEqual(st, 201)
            st, _, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts", srp_account("pl9", "pw"))
            self.assertEqual(st, 429)
        async with Rig(visibility="public", signup="off") as r:
            st, _, _ = await http("POST", f"{r.http}/api/realms/{r.rid}/accounts", srp_account("zz1", "pw"))
            self.assertEqual(st, 403)


class Caps(unittest.IsolatedAsyncioTestCase):
    async def test_stream_caps(self):
        async with Rig(max_streams=3, max_streams_per_ip=2) as r:
            conns = []
            for _ in range(2):
                conns.append(await asyncio.open_connection("127.0.0.1", r.ports[0]))
            await asyncio.sleep(0.1)
            rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
            self.assertEqual(await asyncio.wait_for(rd.read(), 3), b"")    # third from one IP: cut
            self.assertGreaterEqual(r.relay.metrics["refused_429"], 1)
            # another "IP" via the WebSocket path (X-Forwarded-For from loopback is trusted)
            s1 = await ws.connect(f"{r.base}/r/{r.rid}/ws/3724", headers={"X-Forwarded-For": "198.51.100.7"})
            with self.assertRaises(ws.HandshakeError) as cm:   # realm full (3)
                await ws.connect(f"{r.base}/r/{r.rid}/ws/3724", headers={"X-Forwarded-For": "198.51.100.8"})
            self.assertEqual(cm.exception.status, 503)
            s1.abort()
            for _, w in conns:
                w.close()

    async def test_connection_rate(self):
        async with Rig(conn_rate_per_ip=5) as r:
            got = []
            for _ in range(7):
                rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
                try:
                    wr.write(wire335.logon_challenge("NOBODY"))
                    await wr.drain()
                    got.append(await asyncio.wait_for(rd.read(3), 3))
                except ConnectionResetError:   # refused: the relay closed it unread
                    got.append(b"")
                wr.close()
            self.assertEqual(sum(1 for g in got if g == bytes([0, 0, 4])), 5)
            self.assertEqual(sum(1 for g in got if g == b""), 2)

    async def test_bandwidth_is_shaped(self):
        async with Rig(kbps=64) as r:     # 64 KB/s, 1 s burst
            # a raw echo through the tunnel: point the auth service at an echo server
            async def echo(rd, wr):
                while data := await rd.read(65536):
                    wr.write(data)
                    await wr.drain()
                wr.close()
            srv = await asyncio.start_server(echo, "127.0.0.1", 0)
            r.agent.services[3724] = ("127.0.0.1", srv.sockets[0].getsockname()[1])
            rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
            payload = b"x" * (192 * 1024)
            t0 = time.monotonic()
            wr.write(payload)
            await wr.drain()
            got = 0
            while got < len(payload):
                chunk = await asyncio.wait_for(rd.read(65536), 20)
                self.assertTrue(chunk)
                got += len(chunk)
            dt = time.monotonic() - t0
            # 384 KB counted (both directions) at 64 KB/s with a 64 KB burst: >= ~5 s
            self.assertGreater(dt, 4.0)
            wr.close()
            srv.close()

    async def test_daily_quota(self):
        async with Rig(daily_gb=1) as r:
            r.relay.usage(r.rid)["bytes"] = 1 << 30
            rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
            self.assertEqual(await asyncio.wait_for(rd.read(), 3), b"")
            self.assertGreaterEqual(r.relay.metrics["refused_429"], 1)

    async def test_idle_streams_are_closed(self):
        async with Rig(stream_idle=1) as r:
            sweeper = asyncio.ensure_future(r.relay.sweeper(every=0.2))
            rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
            self.assertEqual(await asyncio.wait_for(rd.read(), 5), b"")
            sweeper.cancel()

    async def test_slow_player_is_cut_not_the_tunnel(self):
        async with Rig(kbps=1 << 20) as r:
            s = r.relay.sessions[r.rid]
            rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
            await asyncio.sleep(0.1)
            st = next(iter(s.streams.values()))

            class Stuck:  # a player whose socket never drains
                kind = "tcp"

                def __init__(self):
                    self.n = 0

                async def read(self):
                    await asyncio.sleep(3600)

                def write(self, data):
                    self.n += len(data)
                    return self.n <= mux.MAX_BUFFER

                def close(self):
                    pass
            st.conn = Stuck()
            for _ in range(40):
                r.agent.ws.send_nowait(mux.pack(mux.DATA, st.sid, b"z" * 32768))
            await asyncio.sleep(0.5)
            self.assertNotIn(st.sid, s.streams)
            self.assertIs(r.relay.sessions[r.rid], s)      # tunnel still up
            wr.close()


class Tunnel(unittest.IsolatedAsyncioTestCase):
    async def test_agent_reconnects_with_same_ports(self):
        async with Rig() as r:
            r.realm.add_account("gina", "pw")
            ports = r.ports
            r.relay.sessions[r.rid].ws.abort()            # the relay drops the tunnel
            for _ in range(200):
                await asyncio.sleep(0.05)
                s = r.relay.sessions.get(r.rid)
                if s and r.relay.metrics["agent_logins"] >= 2:
                    break
            self.assertGreaterEqual(r.relay.metrics["agent_logins"], 2)
            self.assertEqual(r.ports, ports)
            rep = await full(r, "gina", "pw", world_override=local_world(r))
            self.assertIn("logout", rep["steps"])

    async def test_relay_restart_keeps_ports(self):
        async with Rig() as r:
            ports = r.ports
            cfg = r.relay.cfg
            await r.relay.stop()
            from wurelay import relay as relaymod
            r.relay = await relaymod.Relay(cfg).start()
            r.base = f"ws://127.0.0.1:{r.relay.http_port()}"
            r.agent.cfg["relay_url"] = r.base + "/agent"
            for _ in range(400):
                await asyncio.sleep(0.05)
                if r.relay.sessions.get(r.rid):
                    break
            self.assertIn(r.rid, r.relay.sessions)
            self.assertEqual(r.ports, ports)

    async def test_new_agent_replaces_old(self):
        async with Rig() as r:
            old = r.relay.sessions[r.rid]
            r.agent.stop_ev.set()
            r.agent.close_all()
            r.agent = r.new_agent()
            for _ in range(100):
                await asyncio.sleep(0.05)
                if r.relay.sessions.get(r.rid) not in (None, old):
                    break
            self.assertIsNot(r.relay.sessions[r.rid], old)
            self.assertTrue(old.closed)

    async def test_bad_logins_refused(self):
        async with Rig(new_realms_per_ip_hour=1) as r:
            async def hello(mutate, sec=None):
                sock = await ws.connect(r.base + "/agent")
                _, m = await sock.recv()
                ch = json.loads(m)
                sec = sec or keys.new_secret()
                pub = keys.public_key(sec)
                h = {"realm_id": keys.realm_id(pub), "pubkey": pub.hex(), "challenge": ch["challenge"],
                     "relay": ch["relay"], "name": "X", "visibility": "public", "invite_sha256": None}
                h = mutate(h) or h
                sig = keys.sign_doc(sec, h, keys.CTX_RELAY_LOGIN)
                if h.get("_badsig"):
                    del h["_badsig"]
                await sock.send(json.dumps({"hello": h, "sig": sig}))
                _, m = await sock.recv()
                sock.abort()
                return json.loads(m)
            self.assertIn("does not match", (await hello(lambda h: h.update(realm_id="aaaaaaaaaaaaaaaa")))["error"])
            self.assertIn("signature", (await hello(lambda h: h.update(_badsig=1)))["error"])
            self.assertIn("challenge", (await hello(lambda h: h.update(challenge="00")))["error"])
            self.assertIn("invite", (await hello(lambda h: h.update(visibility="private")))["error"])
            # registration rate: the rig's realm already used this IP's one new realm this hour
            self.assertIn("too many new realms", (await hello(lambda h: None))["error"])

    async def test_agent_waits_for_database(self):
        async with Rig() as r:
            r.db.fail_address = 3              # database still importing: three failures
            r.realm.world_address = "127.0.0.1:8085"
            r.agent.address_done = None
            for _ in range(200):
                await asyncio.sleep(0.05)
                if r.agent.address_done:
                    break
            self.assertEqual(r.db.fail_address, 0)
            self.assertEqual(r.realm.world_address, f"relay.test:{r.ports[1]}")
            state = json.load(open(f"{r.host_dir}/relay-state.json"))
            self.assertTrue(state["connected"] and state["realmlist_ok"])
            self.assertEqual(state["world_port"], r.ports[1])


class Blocklist(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_realm_is_cut_refused_and_delisted(self):
        import os
        async with Rig() as r:
            beat = r.agent.beat(await r.agent.status())
            st, _, _ = await http("POST", f"{r.http}/api/listing/heartbeat", beat)
            self.assertEqual(st, 200)
            path = os.path.join(r.tmp, "block.txt")
            with open(path, "w") as f:
                f.write("# abuse report 2026-10-24\n" + r.rid + "\n")
            r.relay.cfg.block_file = path
            s = r.relay.sessions[r.rid]
            r.relay.load_blocklist()
            self.assertTrue(s.closed)
            st, doc, _ = await http("GET", f"{r.http}/api/listing/realms.json")
            self.assertEqual(doc["realms"], [])
            await asyncio.sleep(1.5)   # the agent retries; the relay refuses it
            self.assertNotIn(r.rid, r.relay.sessions)
            self.assertIn("blocked", json.load(open(f"{r.host_dir}/relay-state.json"))["last_error"])


class Listing(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_listing_and_claim(self):
        async with Rig() as r:
            r.agent.cfg["claim"] = "CLAIMTOKEN0123456789"
            beat = r.agent.beat(await r.agent.status())
            st, body, _ = await http("POST", f"{r.http}/api/listing/heartbeat", beat)
            self.assertEqual(st, 200, body)
            st, body, _ = await http("POST", f"{r.http}/api/listing/heartbeat", beat)
            self.assertEqual(st, 409)                       # replay
            tampered = json.loads(json.dumps(beat))
            tampered["beat"]["seq"] += 10
            tampered["beat"]["record"]["name"] = "Hijacked"
            st, _, _ = await http("POST", f"{r.http}/api/listing/heartbeat", tampered)
            self.assertEqual(st, 403)                       # signature
            st, doc, hdr = await http("GET", f"{r.http}/api/listing/realms.json")
            self.assertEqual(hdr["access-control-allow-origin"], "*")
            rec = doc["realms"][0]
            self.assertEqual((rec["slug"], rec["official"], rec["state"]), ("c-" + r.rid, False, "live"))
            self.assertEqual(rec["profile"]["address"], "relay.test")
            self.assertEqual(rec["profile"]["port"], r.ports[0])
            self.assertEqual(rec["status"]["format"], "openvanilla-status-1")
            self.assertEqual(rec["community"]["lastHeartbeat"]["bots"], 40)
            self.assertFalse(rec["community"]["claimed"])
            # claim: site-only, and only with the token the realm's signed beat carries
            st, _, _ = await http("POST", f"{r.http}/api/listing/claims", {"realm_id": r.rid, "token": "x"})
            self.assertEqual(st, 401)
            auth = {"Authorization": "Bearer site-secret"}
            st, _, _ = await http("POST", f"{r.http}/api/listing/claims",
                                  {"realm_id": r.rid, "token": "WRONGTOKEN0123456789"}, auth)
            self.assertEqual(st, 409)
            st, body, _ = await http("POST", f"{r.http}/api/listing/claims",
                                     {"realm_id": r.rid, "token": "CLAIMTOKEN0123456789", "claimed_by": "Orion"}, auth)
            self.assertEqual(st, 200, body)
            st, doc, _ = await http("GET", f"{r.http}/api/listing/realms.json")
            self.assertEqual(doc["realms"][0]["community"]["claimedBy"], "Orion")

    async def test_listing_rules(self):
        from wurelay import listing
        rec = listing.clean_record({"name": "  A  B ", "type": "Evil", "discord": "https://evil.example/x",
                                    "rules": ["x" * 500] * 20, "official": True, "order": -5})
        self.assertEqual(rec["name"], "A B")
        self.assertEqual(rec["type"], "PvE")
        self.assertIsNone(rec["discord"])
        self.assertEqual(len(rec["rules"]), 10)
        self.assertNotIn("official", rec)
        L = listing.Listing(type("C", (), {"state_file": "/tmp/wu-x/state.json", "name": "r", "site_url": "s"})())
        sec = keys.new_secret()
        pub = keys.public_key(sec)
        beat = {"v": 1, "realm_id": keys.realm_id(pub), "pubkey": pub.hex(), "seq": 1, "ts": int(time.time()) - 900,
                "record": {"name": "Old"}, "status": {}}
        st, body = L.heartbeat({"beat": beat, "sig": keys.sign_doc(sec, beat, keys.CTX_HEARTBEAT)}, "1.2.3.4")
        self.assertEqual(st, 400)   # clock skew
        self.assertIn("clock", body["error"])


if __name__ == "__main__":
    unittest.main()
