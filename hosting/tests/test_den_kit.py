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

    def test_kit_ships_the_den_scripts_and_editor(self):
        """make-kit copies the whole lua_scripts folder: the Den's room, the Builder, the module's Lua side and the
        addon channel all reach realm-files/; no game data rides along (no dbc, maps or models)."""
        src = os.path.join(ROOT, "kit")
        for f in ("make-kit.sh",):
            shutil.copy(os.path.join(src, f), self.kit)
        realm = os.path.join(os.path.dirname(ROOT), "realm")
        p = subprocess.run(["bash", os.path.join(self.kit, "make-kit.sh"), realm], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-800:] + p.stderr[-800:])
        lua = os.path.join(self.kit, "realm-files", "lua_scripts")
        for f in ("ov_den.lua", "ov_build.lua", "ov_sandbox_core.lua", "ov_modapi.lua"):
            self.assertTrue(os.path.isfile(os.path.join(lua, f)), f)
        for root, _, files in os.walk(os.path.join(self.kit, "realm-files")):
            for f in files:
                self.assertFalse(f.lower().endswith((".dbc", ".map", ".vmtree", ".mmap", ".m2", ".wmo", ".blp", ".mpq")), f)
        den = open(os.path.join(self.kit, "realm-files", "profiles", "den.env")).read()
        for line in ("OV_DEN=1", "OV_BUILD_ANY=1", "OV_BUILD_MODELS=1", "OV_BUILD_SCALE_MIN=0.1", "OV_BUILD_SCALE_MAX=5"):
            self.assertIn("\n" + line + "\n", den)
        build = open(os.path.join(lua, "ov_build.lua")).read()
        for key in ("OV_BUILD_ANY", "OV_BUILD_MODELS", "OV_BUILD_SCALE_MIN", "OV_DEN_SIZE"):
            self.assertIn(key, build)


if __name__ == "__main__":
    unittest.main()
