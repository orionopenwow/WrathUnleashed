#!/usr/bin/env python3
"""tools/site-art/publish_home_art.py: names to slides, 1600 px WebP with no metadata, home.json with captions as plain
data, unknown names skipped; and the step's files exist (the .bat, the server half, the Autopilot entry, .gitignore).

    python3 -I tools/site-art/test_publish_home_art.py      (Pillow needed for the picture checks; skipped without)
"""
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import publish_home_art as P  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class Names(unittest.TestCase):
    def test_find(self):
        d = tempfile.mkdtemp()
        for n in ("hangout.png", "hangout-2.JPG", "browser.jpeg", "mode-minigolf.png", "mode-nope.png", "castle.png",
                  "notes.txt", "den.png", "den.webp", "captions.json"):
            open(os.path.join(d, n), "wb").close()
        items, skipped = P.find(d)
        self.assertEqual([(i[0], i[1]) for i in items], [("browser", "browser.webp"), ("den", "den.webp"),
                         ("hangout", "hangout-2.webp"), ("hangout", "hangout.webp"), ("mode-minigolf", "mode-minigolf.webp")])
        self.assertEqual(sorted(s[0] for s in skipped), ["castle.png", "den.webp", "mode-nope.png", "notes.txt"])

    def test_manifest(self):
        m = P.manifest([("hangout", "hangout.webp", ""), ("hangout", "hangout-2.webp", ""), ("den", "den.webp", "")],
                       {"hangout-2": {"alt": "  Two <b>x</b>\n", "credit": "c" * 300}, "den": "not a dict"})
        self.assertEqual(m["slides"]["hangout"][0]["alt"], P.WHAT["hangout"])
        self.assertEqual(m["slides"]["hangout"][1], {"file": "hangout-2.webp", "alt": "Two <b>x</b>", "credit": "c" * 120})
        self.assertEqual(m["slides"]["den"][0]["alt"], P.WHAT["den"])

    def test_step_files(self):
        bat = read("tools/site-art/Publish home screenshots.bat")
        self.assertIn("publish_home_art.py\" build", bat)
        self.assertIn("install-home-art.sh", bat)
        self.assertIn("root@play.openvanilla.app", bat)
        sh = read("tools/site-art/install-home-art.sh")
        for want in ("/srv/wrath/portal/art", "art-backups/home-", "HOMEART OK", "home.old", "/wrath/art/home/home.json"):
            self.assertIn(want, sh)
        self.assertIn('"homeart": ("tools/site-art/Publish home screenshots.bat"', read("tools/control/control.py"))
        self.assertIn("/site-art/", read(".gitignore").splitlines())


@unittest.skipIf(Image is None, "Pillow is not installed")
class Build(unittest.TestCase):
    def test_build(self):
        src, out = tempfile.mkdtemp(), tempfile.mkdtemp()
        im = Image.new("RGB", (2400, 1350), (40, 90, 160))
        exif = Image.Exif()
        exif[0x010F] = "SomeCamera"
        im.save(os.path.join(src, "hangout.jpg"), "JPEG", exif=exif.tobytes())
        Image.new("RGBA", (800, 450), (10, 200, 10, 128)).save(os.path.join(src, "news.png"))
        with open(os.path.join(src, "captions.json"), "w") as f:
            json.dump({"hangout": {"alt": "In Dalaran", "credit": "Orion"}}, f)
        self.assertEqual(P.main(["build", "--src", src, "--out", out]), 0)
        self.assertEqual(sorted(os.listdir(out)), ["hangout.webp", "home.json", "news.webp"])
        with Image.open(os.path.join(out, "hangout.webp")) as w:
            self.assertEqual((w.format, w.size), ("WEBP", (1600, 900)))
            self.assertFalse(w.info.get("exif") or w.info.get("icc_profile"), "no metadata")
        with Image.open(os.path.join(out, "news.webp")) as w:
            self.assertEqual(w.size, (800, 450), "never made wider")
        j = json.load(open(os.path.join(out, "home.json")))
        self.assertEqual(j["slides"]["hangout"], [{"file": "hangout.webp", "alt": "In Dalaran", "credit": "Orion"}])
        self.assertEqual(P.main(["build", "--src", tempfile.mkdtemp(), "--out", out]), 1, "nothing to publish")


if __name__ == "__main__":
    unittest.main()
