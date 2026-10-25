"""Realm hopping: the relay's WebSocket-to-TCP bridge (/ws/<realm id>/auth and /ws/<realm id>/world) against a
fake Beacon (the real agent + a fake AzerothCore realm), driven by the real headless 3.3.5a client with the same
URL rewrite the browser page does (stream/www-files/wrath-early.js: /ws/3724 -> auth, any other port -> world).
Also: only connected Beacons, Origin allow-list, per-IP upgrade rate, the total caps, and the join page's
hop-mode headers."""
import asyncio
import unittest

from helpers import Rig, http, ws_opener, WSStream
from wunet import ws, wire335

PLAY = "https://wrath.openvanilla.test"


def hop_opener(base, rid, headers=None, log=None):
    """opener(host, port) for wire335 that dials the hop bridge, rewriting ports the way the page does."""
    async def opener(host, port):
        url = f"{base}/ws/{rid}/{'auth' if port == 3724 else 'world'}?host={host}"
        if log is not None:
            log.append(url)
        sock = await ws.connect(url, headers=headers)
        s = WSStream(sock)
        return s.reader, s
    return opener


def rig(**over):
    over.setdefault("play_origins", [PLAY])
    return Rig(**over)


class Bridge(unittest.IsolatedAsyncioTestCase):
    async def test_full_login_through_the_bridge(self):
        async with rig() as r:
            r.realm.add_account("hopper", "pw")
            urls = []
            rep = await wire335.full_run("relay.test", 3724, "hopper", "pw",
                                         opener=hop_opener(r.base, r.rid, {"Origin": PLAY}, urls))
            self.assertEqual(rep["steps"][-1], "logout")
            # the Beacon's realm list points at its relay world port; the page sends that to /world
            self.assertEqual(rep["realm"]["address"], f"relay.test:{r.ports[1]}")
            self.assertEqual([u.split("?")[0].rsplit("/", 1)[1] for u in urls], ["auth", "world"])
            await asyncio.sleep(0.2)
            self.assertEqual(len(r.relay.sessions[r.rid].streams), 0)
            self.assertEqual(r.relay.ws_open, 0)
            self.assertIn("wu_relay_ws_streams_open 0", r.relay.metrics_text())

    async def test_same_framing_as_the_port_path(self):
        # one TCP read per binary message, reassembled: the old /r/<id>/ws/<port> and the bridge carry the same bytes
        async with rig() as r:
            r.realm.add_account("frames", "pw")
            a = await wire335.full_run("relay.test", 3724, "frames", "pw", opener=ws_opener(r.base, r.rid))
            b = await wire335.full_run("relay.test", 3724, "frames", "pw", opener=hop_opener(r.base, r.rid))
            self.assertEqual([x for x in a["steps"] if x != "char_create"], b["steps"])   # 2nd run: the character exists
            self.assertEqual(a["character"]["name"], b["character"]["name"])

    async def test_only_registered_connected_beacons(self):
        async with rig() as r:
            # well-formed but unknown realm, a bad service name, a bad id: never a connection anywhere
            for path, want in ((f"/ws/{'a' * 16}/auth", 404), (f"/ws/{r.rid}/admin", 404),
                               (f"/ws/{r.rid}/3306", 404), ("/ws/NOTANID/auth", 404)):
                st, body, _ = await http("GET", r.http + path)
                self.assertEqual(st, want, (path, body))
            # ?host= names nothing: the stream still goes down this Beacon's own tunnel
            sock = await ws.connect(f"{r.base}/ws/{r.rid}/auth?host=127.0.0.1:22")
            await asyncio.sleep(0.1)
            self.assertEqual([st.port for st in r.relay.sessions[r.rid].streams.values()], [3724])
            sock.abort()
            # the Beacon goes offline: refused at once
            for a in r.agents:
                a.stop_ev.set(); a.close_all(); a.task.cancel()
            r.relay.sessions[r.rid].shutdown("test")
            del r.relay.sessions[r.rid]
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/world")
            self.assertEqual(cm.exception.status, 404)

    async def test_origin_allow_list(self):
        async with rig() as r:
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"Origin": "https://evil.example"})
            self.assertEqual(cm.exception.status, 403)
            for h in ({"Origin": PLAY}, {"Origin": "https://openvanilla.test"}, {}):   # play, site, no Origin
                s = await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers=h)
                s.abort()
            self.assertGreaterEqual(r.relay.metrics["refused_ws_origin"], 1)

    async def test_private_beacon_needs_the_invite(self):
        async with rig(visibility="private") as r:
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/auth")
            self.assertEqual(cm.exception.status, 403)
            s = await ws.connect(f"{r.base}/ws/{r.rid}/auth?invite={r.cfg['invite_secret']}")
            s.abort()


class Limits(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_rate_per_ip(self):
        async with rig(ws_rate_per_ip=3) as r:
            ip = {"X-Forwarded-For": "198.51.100.20"}
            for _ in range(3):
                (await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers=ip)).abort()
                await asyncio.sleep(0.05)
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers=ip)
            self.assertEqual(cm.exception.status, 429)
            # another address is not held up
            (await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.21"})).abort()

    async def test_concurrent_cap_per_realm_and_total(self):
        async with rig(max_ws_total=2) as r:
            a = await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.30"})
            b = await ws.connect(f"{r.base}/ws/{r.rid}/world", headers={"X-Forwarded-For": "198.51.100.31"})
            await asyncio.sleep(0.05)
            self.assertEqual(r.relay.ws_open, 2)
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.32"})
            self.assertEqual(cm.exception.status, 503)
            a.abort()
            for _ in range(50):
                if r.relay.ws_open < 2:
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(r.relay.ws_open, 1)
            c = await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.32"})
            b.abort(); c.abort()
        async with rig(max_streams=1) as r:   # the realm's own cap applies to the bridge too
            a = await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.40"})
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.41"})
            self.assertEqual(cm.exception.status, 503)
            a.abort()

    async def test_total_streams_cap_counts_tcp_too(self):
        async with rig(max_streams_total=1) as r:
            rd, wr = await asyncio.open_connection("127.0.0.1", r.ports[0])
            await asyncio.sleep(0.1)
            with self.assertRaises(ws.HandshakeError) as cm:
                await ws.connect(f"{r.base}/ws/{r.rid}/auth", headers={"X-Forwarded-For": "198.51.100.50"})
            self.assertEqual(cm.exception.status, 503)
            wr.close()


class JoinPageHop(unittest.IsolatedAsyncioTestCase):
    async def test_join_page_can_be_framed_by_the_game_only(self):
        async with rig() as r:
            st, body, hdr = await http("GET", f"{r.http}/join/{r.rid}?hop=1&from={PLAY}")
            self.assertEqual(st, 200)
            self.assertEqual(hdr["content-security-policy"], f"frame-ancestors {PLAY}")
            self.assertEqual(hdr["cross-origin-embedder-policy"], "require-corp")
            self.assertEqual(hdr["cross-origin-resource-policy"], "cross-origin")
            self.assertIn(f'data-hop-origins="{PLAY}"', body)
            self.assertIn('postMessage({ type: "leyline-login"', body)
            self.assertIn("hopOrigins.indexOf(hopFrom) >= 0", body)   # never posts to an unlisted origin


if __name__ == "__main__":
    unittest.main()
