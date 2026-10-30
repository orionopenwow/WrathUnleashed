"""The host kit's image choice (host-wrath-realm.sh pick_images, and the same logic in "Host a Wrath realm.bat"):
prebuilt first; the PC's own build next; images not published yet (the registry says denied / not found) is said
plainly, offline is said as offline, and the host can build them here (the realm's own recipe) or start stock.
Docker is a fake on PATH that records its calls.

    python3 tests/test_kit_images.py          (from hosting/)
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

HOSTING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(HOSTING, "kit")

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "pull -q") case "$FAKE_PULL" in
      ok) exit 0 ;;
      missing) echo "Error response from daemon: Head \"https://ghcr.io/v2/x/manifests/stable\": denied" >&2; exit 1 ;;
      *) echo "Error response from daemon: Get \"https://ghcr.io/v2/\": dial tcp: lookup ghcr.io: no such host" >&2; exit 1 ;;
    esac ;;
  "image inspect") [ "$FAKE_LOCAL" = 1 ] && exit 0; exit 1 ;;
esac
exit 0
"""


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class PickImages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wu-kit-img-")
        self.kit = os.path.join(self.tmp, "kit")
        os.makedirs(os.path.join(self.kit, "realm-files", "build", "patches"))
        with open(os.path.join(KIT, "host-wrath-realm.sh")) as f:
            src = f.read()
        cut = src.index('case "${1:-up}" in')
        with open(os.path.join(self.kit, "host-wrath-realm.sh"), "w") as f:
            f.write(src[:cut] + '"$@"\n')            # every function, then the one this test calls
        shutil.copytree(os.path.join(KIT, "tools"), os.path.join(self.kit, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        for n in ("sources.lock", "fetch.sh", "patches/mod-x.patch"):
            put(os.path.join(self.kit, "realm-files", "build", n), "# test\n")
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        d = os.path.join(bindir, "docker")
        put(d, FAKE_DOCKER)
        os.chmod(d, os.stat(d).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmp, "docker.log")
        self.env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], FAKE_LOG=self.log,
                        LEYLINE_LOCAL_TOOLS="1")
        self.env.pop("WU_BUILD", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pick(self, **env):
        e = dict(self.env, **env)
        p = subprocess.run(["bash", "-c", f'source "{self.kit}/host-wrath-realm.sh" true; pick_images; echo "IMG=$IMG TAG=$TAG"'],
                           env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        calls = []
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = f.read().splitlines()
        return p.returncode, p.stdout + p.stderr, calls

    def test_prebuilt(self):
        rc, out, calls = self.pick(FAKE_PULL="ok")
        self.assertEqual(rc, 0, out)
        self.assertIn("IMG=ghcr.io/orionopenwow/wu-ac-wotlk TAG=stable", out)
        self.assertEqual([c for c in calls if c.startswith("pull")],
                         [f"pull -q ghcr.io/orionopenwow/wu-ac-wotlk-{p}:stable" for p in ("worldserver", "authserver", "db-import")])

    def test_own_build_first(self):
        rc, out, _ = self.pick(FAKE_PULL="missing", FAKE_LOCAL="1")
        self.assertIn("IMG=ov/ac-wotlk TAG=custom", out)
        self.assertNotIn("not published", out)

    def test_not_published_says_so_and_stock_without_a_terminal(self):
        rc, out, calls = self.pick(FAKE_PULL="missing")
        self.assertEqual(rc, 0, out)
        self.assertIn("The ready-made realm images are not published yet.", out)
        self.assertIn("build   build them on this PC now", out)
        self.assertIn("IMG=acore/ac-wotlk TAG=master", out)
        self.assertFalse([c for c in calls if c.startswith("build")])

    def test_offline_is_not_called_unpublished(self):
        rc, out, _ = self.pick(FAKE_PULL="offline")
        self.assertIn("is this PC online?", out)
        self.assertNotIn("not published", out)

    def test_build_here(self):
        rc, out, calls = self.pick(FAKE_PULL="missing", WU_BUILD="1")
        self.assertEqual(rc, 0, out)
        self.assertIn("IMG=ov/ac-wotlk TAG=custom", out)
        b = os.path.join(self.kit, "cache", "build")
        self.assertTrue(os.path.isfile(os.path.join(b, "sources.lock")))
        self.assertTrue(os.path.isfile(os.path.join(b, "patches", "mod-x.patch")))
        fetch = [c for c in calls if c.startswith("run ")]
        self.assertEqual(fetch, [f"run --rm --entrypoint sh -v {b}:/w alpine/git:latest /w/fetch.sh"])
        builds = [c for c in calls if c.startswith("build ")]
        self.assertEqual(len(builds), 3)
        for c, t in zip(builds, ("worldserver", "authserver", "db-import")):
            self.assertIn(f"--target {t} --build-arg CTOOLS_BUILD=db-only --build-arg CWITH_WARNINGS=OFF "
                          f"--build-arg CTYPE=Release -f {b}/acore/apps/docker/Dockerfile -t ov/ac-wotlk-{t}:custom {b}/acore", c)

    def test_build_needs_the_recipe(self):
        shutil.rmtree(os.path.join(self.kit, "realm-files", "build"))
        rc, out, _ = self.pick(FAKE_PULL="missing", WU_BUILD="1")
        self.assertNotEqual(rc, 0)
        self.assertIn("realm-files/build", out)

    def test_bat_does_the_same(self):
        with open(os.path.join(KIT, "Host a Wrath realm.bat")) as f:
            bat = f.read()
        self.assertIn("call :noimages", bat)
        self.assertIn("The ready-made realm images are not published yet.", bat)
        self.assertIn('/c:"denied"', bat)
        self.assertIn("is this PC online?", bat)
        self.assertIn('if "%HOW%"=="1" set "HOW=build"', bat)
        self.assertIn("alpine/git:latest /w/fetch.sh", bat)
        self.assertIn("--target %%T --build-arg CTOOLS_BUILD=db-only --build-arg CWITH_WARNINGS=OFF --build-arg CTYPE=Release", bat)
        self.assertIn("for %%T in (worldserver authserver db-import)", bat)
        said = [ln for ln in bat.splitlines() if "echo" in ln.lower() or "set /p" in ln.lower()]
        for ln in said:
            self.assertNotRegex(ln.lower(), r"world of warcraft|warcraft|blizzard", ln)


if __name__ == "__main__":
    unittest.main()
