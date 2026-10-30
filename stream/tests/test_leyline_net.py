"""stream/leyline_net.py: the P2P/torrent flags file (all off by default, sha256 the launcher checks, the
admin console's writer) and the Host pack listing (/wrath/leyline/hostpack.json, the all.json "tools" entry).

    python3 -I stream/tests/test_leyline_net.py
"""
import importlib.util, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("leyline_net", os.path.join(HERE, "..", "leyline_net.py"))
ln = importlib.util.module_from_spec(spec); spec.loader.exec_module(ln)

SHA = "ab" * 32
PACK = {"format": 1, "name": "Host pack", "version": "2026.1029.1700", "sha256": SHA, "size": 306275,
        "download": "https://github.com/orionopenwow/Leyline/releases/download/host-pack/leyline-host-pack-2026.1029.1700.zip",
        "torrent": "https://github.com/orionopenwow/Leyline/releases/download/host-pack/leyline-host-pack-2026.1029.1700.torrent"}


class Flags(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = os.path.join(self.d.name, "leyline", "flags.json")

    def tearDown(self):
        self.d.cleanup()

    def test_defaults_are_all_off(self):
        doc = ln.load(self.p)
        self.assertTrue(ln.check(doc))
        self.assertEqual(set(doc["flags"]), set(ln.KNOWN))
        self.assertFalse(any(doc["flags"].values()))
        self.assertEqual(doc["limits"], {"seed_upload_kbps": 0, "seed_ratio_pct": 0, "max_peers": 0})

    def test_same_hash_as_the_launcher(self):
        # launcher/src-tauri/src/p2p/flags.rs tests::site_file_is_hash_checked builds the same document.
        d = ln.make_doc({"torrent_downloads": True}, updated_at="2026-10-29T00:00:00Z")
        self.assertEqual(d["sha256"], "20affec29fa6541d09d81479ec436d351671096f3a8c6cfe0c50245724b7c39a")

    def test_writer(self):
        doc = ln.write_flags(self.p, {"torrent_downloads": True}, by="Admin<script>")
        self.assertTrue(doc["flags"]["torrent_downloads"] and not doc["flags"]["p2p_hosting"])
        on_disk = ln.load(self.p)
        self.assertEqual(on_disk, doc)
        doc2 = ln.write_flags(self.p, {"p2p_hosting": True}, limits={"seed_upload_kbps": 10**9})
        self.assertTrue(doc2["flags"]["torrent_downloads"] and doc2["flags"]["p2p_hosting"], "earlier changes kept")
        self.assertEqual(doc2["limits"]["seed_upload_kbps"], 100_000, "capped")
        for bad in ({"nope": True}, {"p2p_hosting": "yes"}, {"p2p_hosting": 1}):
            with self.assertRaises(ValueError):
                ln.write_flags(self.p, bad)
        with self.assertRaises(ValueError):
            ln.write_flags(self.p, {}, limits={"evil": 1})
        log = open(self.p + ".log", encoding="utf-8").read().splitlines()
        self.assertEqual(len(log), 2)
        self.assertEqual(json.loads(log[0])["by"], "Adminscript")
        self.assertNotIn("Admin", open(self.p, encoding="utf-8").read(), "the served file never names the admin")

    def test_tampered_file_serves_defaults(self):
        doc = ln.write_flags(self.p, {"p2p_hosting": True})
        doc["flags"]["torrent_downloads"] = True   # hash no longer matches
        with open(self.p, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        self.assertFalse(ln.load(self.p)["flags"]["p2p_hosting"])

    def test_stun_list_is_checked(self):
        d = ln.make_doc(stun=["stun.example.org:3478", "bad host:1", "x" * 300 + ":1", 5])
        self.assertEqual(d["stun"], ["stun.example.org:3478"])


class HostPack(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.f = os.path.join(self.d.name, "hostpack.json")

    def tearDown(self):
        self.d.cleanup()

    def write(self, doc):
        with open(self.f, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def test_descriptor_is_checked(self):
        self.assertIsNone(ln.hostpack((self.f,)))
        self.write(PACK)
        self.assertEqual(ln.hostpack((self.f,))["version"], "2026.1029.1700")
        for k, v in (("download", "https://evil.example.com/x.zip"), ("sha256", "nothex"), ("version", "1.x"),
                     ("format", 2)):
            self.write(dict(PACK, **{k: v}))
            self.assertIsNone(ln.hostpack((self.f,)), k)
        self.write(dict(PACK, torrent="https://evil.example.com/t"))
        self.assertIsNone(ln.hostpack((self.f,))["torrent"])

    def test_all_json_gets_one_tools_entry(self):
        body = json.dumps({"format": 1, "projects": [{"id": "mod:pings", "category": "addons"}]}).encode()
        self.assertEqual(ln.add_hostpack(body, {}), body, "no pack: unchanged")
        out = json.loads(ln.add_hostpack(body, PACK))
        hp = [p for p in out["projects"] if p["id"] == "mod:host-pack"]
        self.assertEqual(len(hp), 1)
        self.assertEqual((hp[0]["category"], hp[0]["kind"], hp[0]["source"]), ("tools", "hostpack", "packaged"))
        self.assertEqual((hp[0]["sha256"], hp[0]["download"]), (SHA, PACK["download"]))
        again = ln.add_hostpack(json.dumps(out).encode(), PACK)
        self.assertEqual(len([p for p in json.loads(again)["projects"] if p["id"] == "mod:host-pack"]), 1)
        self.assertEqual(ln.add_hostpack(b"<html>", PACK), b"<html>")
        text = json.dumps(hp[0]).lower()
        for word in ("world of warcraft", "warcraft", "blizzard", "lich king"):
            self.assertNotIn(word, text)

    def test_serve(self):
        old = ln.DIR
        ln.DIR = self.d.name
        try:
            st, body, ctype = ln.serve("/wrath/leyline/flags.json")
            self.assertEqual(st, 200)
            self.assertTrue(ln.check(json.loads(body)))
            self.assertEqual(ln.serve("/wrath/leyline/hostpack.json")[0], 404 if not os.path.exists(
                os.path.join(ln.HERE, "hostpack.json")) else 200)
            self.write(PACK)
            st, body, _ = ln.serve("/wrath/leyline/hostpack.json")
            self.assertEqual((st, json.loads(body)["sha256"]), (200, SHA))
            self.assertIsNone(ln.serve("/wrath/leyline/other"))
        finally:
            ln.DIR = old


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
