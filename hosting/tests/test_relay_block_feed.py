"""The relay's block feed from Leyline HQ (RELAY_BLOCK_FEED, stream/admin.py relay_block_feed): signature, the cap on new
ids per update, removals, the block file's own lines and "allow" lines, cutting a live realm off, the cache across
restarts, and a feed that does not answer.

    cd hosting/tests && python3 -m pytest -q test_relay_block_feed.py     (or python3 -m unittest test_relay_block_feed)
"""
import asyncio
import hashlib
import hmac
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import Rig, http

KEY = "feed-test-key"


def sign(doc, key=KEY):
    body = {k: v for k, v in doc.items() if k != "sig"}
    return dict(doc, sig=hmac.new(key.encode(), json.dumps(body, sort_keys=True, separators=(",", ":"),
                                                           ensure_ascii=False).encode(), hashlib.sha256).hexdigest())


def feed(ids, key=KEY):
    doc = {"format": 1, "updated_at": "2026-10-31T00:00:00Z", "blocked": [{"id": i, "at": f"2026-10-31T00:00:{n:02d}Z"}
                                                                       for n, i in enumerate(ids)]}
    return sign(doc, key) if key else doc


def _unused(n):
    return ("abcdefghijklmnop" + "a" * 16)[:12] + "a2b3c4d5efghijkl"[n % 16] * 4


class BlockFeed(unittest.IsolatedAsyncioTestCase):
    async def test_feed_signed_capped_removals_and_file_override(self):
        async with Rig() as r:
            relay = r.relay
            relay.cfg.block_feed_key = KEY
            relay.cfg.block_feed_max_new = 3
            beat = r.agent.beat(await r.agent.status())
            st, _, _ = await http("POST", f"{r.http}/api/listing/heartbeat", beat)
            self.assertEqual(st, 200)
            s = relay.sessions[r.rid]
            # unsigned or wrongly signed: ignored
            self.assertIsNone(relay.take_feed(feed([r.rid], key="")))
            self.assertIsNone(relay.take_feed(feed([r.rid], key="other")))
            self.assertIsNone(relay.take_feed({"format": 2, "blocked": []}))
            self.assertNotIn(r.rid, relay.blocked)
            self.assertFalse(s.closed)
            # signed: the live realm is cut off and delisted
            self.assertEqual(relay.take_feed(feed([r.rid])), 1)
            self.assertIn(r.rid, relay.blocked)
            self.assertTrue(s.closed)
            st, doc, _ = await http("GET", f"{r.http}/api/listing/realms.json")
            self.assertEqual(doc["realms"], [])
            # the cap: 8 new ids, 3 per update
            many = ["bbbbbbbbbbbbbbb" + c for c in "abcdefgh"]
            self.assertEqual(relay.take_feed(feed([r.rid] + many)), 3)
            self.assertEqual(len(relay.feed_ids), 4)
            self.assertEqual(relay.take_feed(feed([r.rid] + many)), 3)
            self.assertEqual(relay.take_feed(feed([r.rid] + many)), 2)
            self.assertEqual(len(relay.feed_ids), 9)
            # junk ids never get in
            self.assertEqual(relay.take_feed(feed([r.rid] + many + ["../../etc", "UPPERCASEUPPERCA"])), 0)
            # a removal takes effect at once
            relay.take_feed(feed(many))
            self.assertNotIn(r.rid, relay.blocked)
            # the cache survives a restart
            self.assertEqual(set(json.load(open(relay._feed_cache()))), set(many))
            relay.feed_ids = set()
            relay.load_feed_cache()
            self.assertEqual(relay.feed_ids, set(many))
            # the block file: its own ids block too, and "allow" wins over the feed
            path = os.path.join(r.tmp, "block.txt")
            with open(path, "w") as f:
                f.write("# operator\n" + r.rid + "\nallow " + many[0] + "\n")
            relay.cfg.block_file = path
            relay.load_blocklist()
            self.assertIn(r.rid, relay.blocked)
            self.assertNotIn(many[0], relay.blocked)
            self.assertIn(many[1], relay.blocked)

    async def test_poll_fetches_and_survives_a_dead_feed(self):
        doc = feed(["cccccccccccccccc"])

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                b = json.dumps(doc).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            async with Rig() as r:
                relay = r.relay
                relay.cfg.block_feed_key = KEY
                relay.cfg.block_feed = f"http://127.0.0.1:{srv.server_address[1]}/wrath/leyline/relay-block.json"
                await relay.poll_feed()
                self.assertIn("cccccccccccccccc", relay.blocked)
                relay.cfg.block_feed = "http://127.0.0.1:9/nothing"
                await relay.poll_feed()   # no answer: the last list stays
                self.assertIn("cccccccccccccccc", relay.blocked)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
