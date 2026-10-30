"""The published host kit (hostkit.py): what goes in and what never does, line ends, the safety check refusing
secrets / game data / brand words, a zip that sets up a realm from zero after unzipping, the upload (made once,
replaced after, owner only, public repo only), and the site's default link.

    python3 tools/leyline-repo/test_hostkit.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hostkit  # noqa: E402

REPO = HERE.parents[1]
KIT = REPO / "hosting" / "kit"


class Contents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wu-hostkit-"))
        cls.files = hostkit.collect(KIT, REPO / "realm")
        cls.zip = cls.tmp / hostkit.NAME
        hostkit.write_zip(cls.files, cls.zip)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_clean(self):
        self.assertEqual(hostkit.problems(self.files), [])

    def test_what_is_in(self):
        names = set(self.files)
        for must in ("Host a Wrath realm.bat", "Check my realm.bat", "Realm tools.bat", "Stop my realm.bat",
                     "host-wrath-realm.sh", "leyline", "docker-compose.host.yml", "tools/Dockerfile",
                     "tools/wuhost/setup.py", "tools/wuhost/agent.py", "tools/wunet/leyline.env",
                     "realm-files/modules.env", "realm-files/MANIFEST.sha256", "realm-files/build/sources.lock",
                     "realm-files/build/fetch.sh", "realm-files/lua_scripts/ov_main.lua",
                     "realm-files/sql/main_world.sql"):
            self.assertIn(must, names)
        for p in hostkit.PRESETS:
            self.assertIn(f"realm-files/profiles/{p}.env", names)
        for p in (REPO / "realm" / "custom" / "patches").glob("*.patch"):
            self.assertIn(f"realm-files/build/patches/{p.name}", names)
        self.assertEqual(self.files["realm-files/build/sources.lock"],
                         (REPO / "realm" / "custom" / "sources.lock").read_bytes().replace(b"\r\n", b"\n"))

    def test_what_never_is(self):
        for rel in self.files:
            parts = rel.split("/")
            self.assertFalse({"state", "cache", "__pycache__", ".git"} & set(parts), rel)
            self.assertNotIn(rel.rsplit("/", 1)[-1], hostkit.OWNER_ONLY, rel)
            self.assertNotEqual(rel, ".env")
            self.assertFalse(rel.endswith((".zip", ".pyc", ".log")), rel)
        self.assertNotIn(b"DATABASE_INFO", self.files["realm-files/modules.env"])
        self.assertNotIn(b"ov-local-test", b"".join(self.files.values()))

    def test_line_ends_and_modes(self):
        with zipfile.ZipFile(self.zip) as z:
            infos = {i.filename: i for i in z.infolist()}
            for name, info in infos.items():
                self.assertTrue(name.startswith(hostkit.TOP + "/"), name)
                data = z.read(name)
                if name.endswith(".bat"):
                    self.assertNotRegex(data, rb"[^\r]\n", name)
                else:
                    self.assertNotIn(b"\r\n", data, name)
            for exe in ("leyline", "host-wrath-realm.sh"):
                self.assertEqual((infos[f"{hostkit.TOP}/{exe}"].external_attr >> 16) & 0o111, 0o111, exe)
            self.assertEqual((infos[f"{hostkit.TOP}/docker-compose.host.yml"].external_attr >> 16) & 0o111, 0)

    def test_same_bytes_every_time(self):
        other = self.tmp / "again.zip"
        hostkit.write_zip(hostkit.collect(KIT, REPO / "realm"), other)
        self.assertEqual(other.read_bytes(), self.zip.read_bytes())

    def test_unzipped_kit_sets_up_a_realm(self):
        d = self.tmp / "player"
        with zipfile.ZipFile(self.zip) as z:
            z.extractall(d)
        kit = d / hostkit.TOP
        for exe in ("leyline", "host-wrath-realm.sh"):       # extractall drops modes; unzip(1) keeps them
            os.chmod(kit / exe, 0o755)
        env = dict(os.environ, LEYLINE_LOCAL_TOOLS="1", LEYLINE_NAME="Zero Realm", LEYLINE_GM="HOSTGM",
                   LEYLINE_VISIBILITY="private", LEYLINE_NONINTERACTIVE="1")
        p = subprocess.run(["bash", str(kit / "leyline"), "host", "--config-only"], env=env, cwd=str(kit),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-800:] + p.stderr[-800:])
        cfg = (kit / "state" / "host.json").read_text()
        self.assertIn('"Zero Realm"', cfg)
        self.assertTrue((kit / "state" / "realm.key").is_file())


class SafetyCheck(unittest.TestCase):
    def base(self):
        return dict(hostkit.collect(KIT, REPO / "realm"))

    def test_refusals(self):
        cases = {
            "state-copy/.env": b"DB_ROOT_PASSWORD=hunter2\n",
            "tools/wuhost/creds.txt": b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n",
            "tools/Spell.dbc": b"WDBC",
            "tools/run.log": b"log",
            "tools/wunet/leyline.env": b"LEYLINE_DOMAIN=x\nSECRET=1\n",
            "notes/README.md": b"Play World of Warcraft here\n",
        }
        for rel, data in cases.items():
            files = self.base()
            files[rel] = data
            self.assertTrue(hostkit.problems(files), rel)
        files = self.base()
        files["realm-files/modules.env"] += b"\nAC_SOAP_PASSWORD=x\n"
        self.assertTrue(any("AC_SOAP_PASSWORD" in p for p in hostkit.problems(files)))
        files = self.base()
        files["realm-files/profiles/main.env"] += b"\nAC_PLAYERBOTS_DATABASE_INFO=a;b;root;pw;db\n"
        self.assertTrue(hostkit.problems(files))
        files = self.base()
        del files["realm-files/build/sources.lock"]
        self.assertTrue(any("missing" in p for p in hostkit.problems(files)))

    def test_cli_refuses_and_writes_nothing(self):
        t = Path(tempfile.mkdtemp())
        try:
            kit = t / "kit"
            shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("__pycache__", "state", "cache", "realm-files"))
            (kit / "tools" / "Spell.dbc").write_bytes(b"WDBC")
            out = t / "k.zip"
            err = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(err):
                rc = hostkit.main(["--kit", str(kit), "--realm", str(REPO / "realm"), "--out", str(out), "--upload"],
                                  run=lambda a: self.fail("must not upload"))
            self.assertEqual(rc, 1)
            self.assertIn("game data", err.getvalue())
            self.assertFalse(out.exists())
        finally:
            shutil.rmtree(t, ignore_errors=True)


class Upload(unittest.TestCase):
    def fake(self, login="orionopenwow", visibility="PUBLIC", has_release=False):
        calls = []

        def run(args):
            calls.append(args)
            if args[:2] == ["api", "user"]:
                return 0, login + "\n"
            if args[:2] == ["repo", "view"]:
                return 0, visibility + "\n"
            if args[:2] == ["release", "view"]:
                return (0, "{}") if has_release else (1, "release not found")
            if args[:2] in (["release", "create"], ["release", "upload"]):
                return 0, ""
            raise AssertionError(args)
        return run, calls

    def go(self, run):
        checked = []
        out = StringIO()
        with redirect_stdout(out):
            url = hostkit.upload(Path("/tmp/x.zip"), run, fetch=checked.append)
        return url, checked, out.getvalue()

    def test_first_time_creates_the_release(self):
        run, calls = self.fake()
        url, checked, _ = self.go(run)
        self.assertEqual(url, "https://github.com/orionopenwow/Leyline/releases/download/host-kit/WrathUnleashed-host-kit.zip")
        create = [c for c in calls if c[:2] == ["release", "create"]][0]
        self.assertEqual(create[2], "host-kit")
        self.assertEqual(create[create.index("-R") + 1], "orionopenwow/Leyline")
        self.assertEqual(checked, [url])
        self.assertFalse(re.search(r"warcraft|blizzard", hostkit.NOTES, re.I))

    def test_again_replaces_the_file(self):
        run, calls = self.fake(has_release=True)
        self.go(run)
        up = [c for c in calls if c[:2] == ["release", "upload"]][0]
        self.assertIn("--clobber", up)
        self.assertFalse([c for c in calls if c[:2] == ["release", "create"]])

    def test_owner_and_public_only(self):
        for kw in ({"login": "Chumpton"}, {"visibility": "PRIVATE"}):
            run, calls = self.fake(**kw)
            with self.assertRaises(hostkit.Refused):
                self.go(run)
            self.assertFalse([c for c in calls if c[0] == "release" and c[1] != "view"])

    def test_the_site_links_this_file(self):
        src = (REPO / "stream" / "hostflow.py").read_text()
        self.assertIn(f'"{hostkit.URL}"', src)

    def test_bat(self):
        bat = (KIT / "Publish host kit.bat").read_text()
        self.assertIn(r"tools\leyline-repo\hostkit.py", bat)
        self.assertIn("--upload", bat)
        self.assertNotRegex(bat, r"(?im)^\s*pause\b")                 # runs under Autopilot
        ctl = (REPO / "tools" / "control" / "control.py").read_text()
        m = re.search(r'"hostkit":\s*\("([^"]+)",\s*"[^"]+",\s*(True|False)\)', ctl)
        self.assertTrue(m, "control.py has the hostkit step")
        self.assertEqual(m.group(1), "hosting/kit/Publish host kit.bat")
        self.assertEqual(m.group(2), "False")
        self.assertTrue((REPO / m.group(1)).is_file())


if __name__ == "__main__":
    unittest.main()
