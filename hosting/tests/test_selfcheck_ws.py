"""The host self-check against a live rig, and the WebSocket implementation's edge cases."""
import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stdout

from helpers import Rig
from wunet import srp6, ws


class SelfCheck(unittest.IsolatedAsyncioTestCase):
    async def run_check(self, r, **kw):
        from wuhost import selfcheck
        out = io.StringIO()
        with redirect_stdout(out):
            args = dict(db=r.db, relay_http=r.http, relay_host="127.0.0.1")
            if r.realm.auth_server:
                args.update(local_auth=("127.0.0.1", r.realm.auth_port), local_world=("127.0.0.1", r.realm.world_port))
            args.update(kw)
            rep = await selfcheck.run(r.host_dir, **args)
        return rep, out.getvalue()

    async def test_all_good_private(self):
        async with Rig(visibility="private", listing=False) as r:
            cfg = json.load(open(os.path.join(r.host_dir, "host.json")))
            cfg["relay"] = "relay.test"
            json.dump(cfg, open(os.path.join(r.host_dir, "host.json"), "w"))
            user, pw = "HOSTABCD", "PASSWORD1"
            r.realm.add_account(user, pw)
            with open(os.path.join(r.host_dir, "host-login.txt"), "w") as f:
                f.write(f"  account:  {user}\n  password: {pw}\n")
            with open(os.path.join(r.host_dir, "invite.txt"), "w") as f:
                f.write("https://openvanilla.test/join/x#y\n")
            rep, text = await self.run_check(r)
            self.assertEqual(rep.bad, 0, text)
            self.assertIn("A real login through the relay works", text)
            self.assertIn("Your invite link works", text)
            self.assertIn("All good", text)

    async def test_problems_are_plain(self):
        async with Rig(visibility="public") as r:
            cfg = json.load(open(os.path.join(r.host_dir, "host.json")))
            cfg["relay"] = "relay.test"
            json.dump(cfg, open(os.path.join(r.host_dir, "host.json"), "w"))
            await r.realm.stop()                       # the game servers are down
            r.realm.auth_server = r.realm.world_server = None
            rep, text = await self.run_check(r, local_auth=("127.0.0.1", 1), local_world=("127.0.0.1", 1), login=False)
            self.assertGreater(rep.bad, 0)
            self.assertIn("The login server is not running", text)
            self.assertIn("->", text)                  # every problem says what to do


class WebSocketEdges(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.got = asyncio.Queue()

        async def handler(reader, writer):
            from wurelay import httpd
            req = await httpd.read_request(reader, "x")
            sock = await ws.server_upgrade(req, reader, writer, max_message=1000)
            try:
                while True:
                    op, data = await sock.recv()
                    await self.got.put((op, data))
                    await sock.send(data, op)
            except ws.WSClosed as e:
                await self.got.put(("closed", e.code))
        self.srv = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.srv.sockets[0].getsockname()[1]}/"

    async def asyncTearDown(self):
        self.srv.close()

    async def test_echo_text_binary_and_sizes(self):
        c = await ws.connect(self.url)
        for payload in (b"", b"a", bytes(125), bytes(126), bytes(999)):
            await c.send(payload, ws.OP_BIN)
            self.assertEqual(await c.recv(), (ws.OP_BIN, payload))
        await c.send("hé")
        self.assertEqual(await c.recv(), (ws.OP_TEXT, "hé"))
        await c.close()
        self.assertEqual((await self.got.get())[0], ws.OP_BIN)

    async def test_fragmented_message_with_ping_between(self):
        c = await ws.connect(self.url)
        # fragments: BIN(fin=0) "ab", PING, CONT(fin=1) "cd"
        def frag(op, data, fin):
            f = bytearray(c._frame(op, data))
            if not fin:
                f[0] &= 0x7F
            return bytes(f)
        c.writer.write(frag(ws.OP_BIN, b"ab", False) + frag(ws.OP_PING, b"p", True) + frag(ws.OP_CONT, b"cd", True))
        op, data = await c.recv()        # the server's pong is skipped by recv
        self.assertEqual((op, data), (ws.OP_BIN, b"abcd"))
        c.abort()

    async def test_oversize_is_refused(self):
        c = await ws.connect(self.url)
        await c.send(bytes(1001), ws.OP_BIN)
        kind, code = await asyncio.wait_for(self.got.get(), 5)
        self.assertEqual((kind, code), ("closed", 1009))
        c.abort()

    async def test_unmasked_client_frame_is_refused(self):
        c = await ws.connect(self.url)
        c.client = False                 # send like a server would: no mask
        c.writer.write(c._frame(ws.OP_BIN, b"x"))
        kind, code = await asyncio.wait_for(self.got.get(), 5)
        self.assertEqual((kind, code), ("closed", 1002))
        c.abort()

    async def test_handshake_errors(self):
        async def not_ws(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
        srv = await asyncio.start_server(not_ws, "127.0.0.1", 0)
        with self.assertRaises(ws.HandshakeError) as cm:
            await ws.connect(f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}/x")
        self.assertEqual(cm.exception.status, 403)
        srv.close()


if __name__ == "__main__":
    unittest.main()
