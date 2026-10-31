#!/usr/bin/env python3
"""The Leyline addons pack (make-addonpack.py): what goes in, what is refused, and the publish order.

    python3 -I addons/pack/test_make_addonpack.py
"""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("make_addonpack", HERE / "make-addonpack.py")
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)


def fake_repo(root: Path) -> Path:
    """A repo with the real addons copied in (so a test can spoil them)."""
    for _, rel in mp.ADDONS:
        shutil.copytree(mp.REPO / rel, root / rel)
    (root / "mods").mkdir(parents=True)
    shutil.copy(mp.REPO / "mods" / "catalog.json", root / "mods" / "catalog.json")
    return root


class Pack(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.out = self.t / "out"

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def test_the_real_pack(self):
        made = mp.build(self.out, "2026.1031.900")
        d = json.loads(made["json"].read_text())
        self.assertEqual([a["name"] for a in d["addons"]], ["OVArmory", "OVQoL", "WUModCatalog", "WrathUnleashedUI"])
        self.assertEqual(d["build"], "3.3.5a")
        self.assertEqual(d["download"], "https://github.com/orionopenwow/Leyline/releases/download/leyline-addons/leyline-addons-2026.1031.900.zip")
        data = made["zip"].read_bytes()
        self.assertEqual(d["sha256"], hashlib.sha256(data).hexdigest())
        with zipfile.ZipFile(made["zip"]) as z:
            names = z.namelist()
            self.assertEqual(sorted(names), sorted(d["files"]))
            for n in names:
                self.assertEqual(d["files"][n], hashlib.sha256(z.read(n)).hexdigest())
                self.assertTrue(n.lower().endswith(mp.ALLOWED), n)
            self.assertFalse(any(n.lower().startswith("foreverui/") for n in names))
            self.assertNotIn("OVQoL/README.md", names)
            toc = z.read("WrathUnleashedUI/WrathUnleashedUI.toc").decode()
            self.assertIn("## Title: Leyline UI", toc)
            self.assertIn("## Title: Leyline Armory", z.read("OVArmory/OVArmory.toc").decode())
            self.assertIn("WU_MOD_CATALOG", z.read("WUModCatalog/WUModCatalog.lua").decode())
        # Same files, same bytes.
        again = mp.build(self.t / "again", "2026.1031.900")
        self.assertEqual(again["zip"].read_bytes(), data)

    def test_no_brand_keeps_the_old_names(self):
        made = mp.build(self.out, "1.0.0", branded=False, with_catalog=False)
        with zipfile.ZipFile(made["zip"]) as z:
            self.assertIn("## Title: WrathUnleashed UI", z.read("WrathUnleashedUI/WrathUnleashedUI.toc").decode())
            self.assertFalse(any(n.startswith("WUModCatalog/") for n in z.namelist()))

    def refused(self, spoil):
        repo = fake_repo(Path(tempfile.mkdtemp(dir=self.t)))
        spoil(repo)
        with self.assertRaises(mp.Refused) as e:
            mp.build(self.out, "1.0.0", repo=repo)
        self.assertFalse((self.out / "addonpack.json").exists(), "nothing made")
        return str(e.exception)

    def test_game_data_is_refused(self):
        wui = "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
        msg = self.refused(lambda r: (r / wui / "Media" / "x.blp").write_bytes(b"BLP2...."))
        self.assertIn("x.blp", msg)
        msg = self.refused(lambda r: (r / wui / "Media" / "renamed.tga").write_bytes(b"BLP2...."))
        self.assertIn("renamed.tga: game data", msg)

    def test_other_files_and_bad_tocs_are_refused(self):
        self.assertIn("not an addon file", self.refused(lambda r: (r / "addons/OVQoL/tool.exe").write_bytes(b"MZ")))
        self.assertIn("## Interface must be 30300", self.refused(
            lambda r: (r / "addons/OVQoL/OVQoL.toc").write_text("## Interface: 11200\n## Title: OVQoL\nOVQoL.lua\n")))
        self.assertIn("lists Gone.lua", self.refused(
            lambda r: (r / "addons/OVQoL/OVQoL.toc").write_text("## Interface: 30300\n## Title: OVQoL\nOVQoL.lua\nGone.lua\n")))
        self.assertIn("the addon list says", self.refused(
            lambda r: (r / "addons/OVQoL/OVQoL.toc").write_text("## Interface: 30300\n## Title: Blizzard helper\nOVQoL.lua\n")))

    def test_publish_order_and_owner_only(self):
        made = mp.build(self.out, "1.0.0")
        calls = []

        def gh(args, who="orionopenwow"):
            calls.append(args)
            if args[:2] == ["api", "user"]:
                return 0, who
            if args[:2] == ["repo", "view"]:
                return 0, "PUBLIC"
            return 0, ""
        mp.upload(made, gh)
        ups = [a for a in calls if a[0] == "release" and a[1] in ("upload", "create")]
        self.assertTrue(any(str(x).endswith(".zip") for x in ups[0]), "the zip goes up first")
        self.assertTrue(any(str(x).endswith("addonpack.json") for x in ups[-1]), "the listing goes up last")
        self.assertFalse(any(str(x).endswith("addonpack.json") for x in ups[0]))
        with self.assertRaises(mp.Refused):
            mp.upload(made, lambda a: gh(a, who="chumpton"))


if __name__ == "__main__":
    unittest.main()
