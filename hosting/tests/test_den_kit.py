"""My Den in the host kit flows (docs/DEN.md): `leyline host --ruleset den` with no answers given is private, runs no
bots, and the ruleset lists of leyline, host-wrath-realm.sh and "Host a Wrath realm.bat" name den."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import ROOT


class DenKit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="leyline-den-")
        self.kit = os.path.join(self.tmp, "kit")
        os.makedirs(self.kit)
        src = os.path.join(ROOT, "kit")
        for f in ("leyline", "host-wrath-realm.sh"):
            shutil.copy(os.path.join(src, f), self.kit)
        shutil.copytree(os.path.join(src, "tools"), os.path.join(self.kit, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_den_defaults_private_no_bots(self):
        env = dict(os.environ, LEYLINE_LOCAL_TOOLS="1", LEYLINE_NONINTERACTIVE="1", LEYLINE_NAME="My Den",
                   LEYLINE_GM="denboss", LEYLINE_RULESET="den", WU_RELAY="relay.test")
        env.pop("LEYLINE_VISIBILITY", None)
        p = subprocess.run(["bash", os.path.join(self.kit, "leyline"), "host", "--config-only"], env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-800:] + p.stderr[-800:])
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertEqual((cfg["profile"], cfg["visibility"], cfg["bots"], cfg["signup"]), ("den", "private", 0, "invite"))
        env_txt = open(os.path.join(self.kit, ".env")).read()
        self.assertIn("WU_BOTS=0", env_txt)

    def test_ruleset_lists_name_den(self):
        src = os.path.join(ROOT, "kit")
        ley = open(os.path.join(src, "leyline")).read()
        sh = open(os.path.join(src, "host-wrath-realm.sh")).read()
        raw = open(os.path.join(src, "Host a Wrath realm.bat"), "rb").read()
        self.assertIn("vanillaplus den $others", ley)
        self.assertIn("dalaran vanillaplus den $others", sh)
        bat = raw.decode()
        self.assertIn('if /i not "%WU_PROFILE%"=="den"', bat)
        self.assertIn("echo   den ", bat)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))   # CRLF throughout


if __name__ == "__main__":
    unittest.main()
