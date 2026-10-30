"""hosting/pack/make-hostpack.py: the Host pack zip, its sha256, torrent (web seed) and hostpack.json, the refusal of
game data, and the publish step against a stub gh.

    python3 -m unittest hosting/tests/test_hostpack.py
"""
import hashlib, importlib.util, json, os, shutil, tempfile, unittest, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("make_hostpack", REPO / "hosting" / "pack" / "make-hostpack.py")
mh = importlib.util.module_from_spec(spec); spec.loader.exec_module(mh)


def bdecode(b, i=0):
    c = b[i:i + 1]
    if c == b"i":
        j = b.index(b"e", i)
        return int(b[i + 1:j]), j + 1
    if c == b"l":
        i += 1; out = []
        while b[i:i + 1] != b"e":
            v, i = bdecode(b, i); out.append(v)
        return out, i + 1
    if c == b"d":
        i += 1; out = {}
        while b[i:i + 1] != b"e":
            k, i = bdecode(b, i); v, i = bdecode(b, i); out[k] = v
        return out, i + 1
    j = b.index(b":", i)
    n = int(b[i:j])
    return b[j + 1:j + 1 + n], j + 1 + n


class Build(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_pack_torrent_and_descriptor(self):
        made = mh.build(self.out, "2026.1029.1700")
        d = made["desc"]
        data = made["zip"].read_bytes()
        self.assertEqual(d["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(d["size"], len(data))
        self.assertTrue(d["download"].startswith("https://github.com/orionopenwow/Leyline/releases/download/host-pack/"))
        self.assertEqual(json.loads(made["json"].read_text()), d)
        names = zipfile.ZipFile(made["zip"]).namelist()
        top = {n.split("/")[0] for n in names}
        self.assertEqual(top, {"WrathUnleashed host"}, "one top folder (Leyline strips it)")
        for must in ("Host a Wrath realm.bat", "leyline", "host-wrath-realm.sh", "docker-compose.host.yml",
                     "realm-files/profiles/main.env", "HOSTPACK-VERSION.txt"):
            self.assertIn(f"WrathUnleashed host/{must}", names)
        for n in names:
            self.assertFalse("/state/" in n or n.endswith("/.env"), n)
            self.assertFalse(n.lower().endswith((".mpq", ".blp", ".m2", ".dbc", ".exe")), n)
        t, end = bdecode(made["torrent"].read_bytes())
        info = t[b"info"]
        self.assertEqual((info[b"length"], info[b"name"].decode()), (len(data), made["zip"].name))
        pl = info[b"piece length"]
        pieces = b"".join(hashlib.sha1(data[i:i + pl]).digest() for i in range(0, len(data), pl))
        self.assertEqual(info[b"pieces"], pieces)
        self.assertEqual([u.decode() for u in t[b"url-list"]], [d["download"]])
        self.assertEqual(hashlib.sha1(mh.bencode({k.decode(): v for k, v in info.items()})).hexdigest(), d["info_hash"])

    def test_same_bytes_twice(self):
        a = mh.build(self.out / "a", "2026.1029.1700")
        b = mh.build(self.out / "b", "2026.1029.1700")
        self.assertEqual(a["desc"]["sha256"], b["desc"]["sha256"])

    def test_game_data_stops_it(self):
        kit = self.out / "kit"
        shutil.copytree(REPO / "hosting" / "kit", kit, ignore=shutil.ignore_patterns("state", "cache", "realm-files", "__pycache__"))
        (kit / "tools" / "sneaky.txt").write_bytes(b"MPQ\x1a" + b"\0" * 32)
        with self.assertRaises((mh.Refused, mh.hostkit.Refused)):
            mh.build(self.out / "o", "2026.1029.1700", kit=kit, realm=REPO / "realm")
        self.assertFalse((self.out / "o" / "hostpack.json").exists())
        self.assertTrue(mh.floor_check({"x/Wow.exe": b"MZ"}))
        self.assertFalse(mh.floor_check({"x/leyline": b"#!/bin/sh"}))

    def test_version(self):
        self.assertEqual(mh.version_now(0), "1970.101.0")
        self.assertEqual(mh.version_now(1793289600), "2026.1029.1600")
        self.assertEqual(mh.main(["--version", "abc", "--out", str(self.out)]), 2)
        self.assertEqual(mh.main(["--write-site", "--out", str(self.out)]), 2)

    def test_upload_with_a_stub_gh(self):
        made = mh.build(self.out, "2026.1029.1700")
        calls = []

        def gh(args):
            calls.append(args)
            if args[:2] == ["api", "user"]:
                return 0, "owner\n"
            if args[:2] == ["repo", "view"]:
                return 0, "PUBLIC\n"
            if args[:2] == ["release", "view"]:
                return 1, "not found"
            return 0, ""
        mh.upload(made, gh)
        create = [c for c in calls if c[:2] == ["release", "create"]][0]
        self.assertIn(str(made["zip"]), create)
        self.assertIn(str(made["json"]), create)
        with self.assertRaises(mh.Refused):
            mh.upload(made, lambda a: (0, "chumpton") if a[0] == "api" else (0, "PUBLIC"))


if __name__ == "__main__":
    unittest.main()
