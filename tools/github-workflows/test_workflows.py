"""The workflow source copies (tools/github-workflows/*.yml): each parses, and wu-images publishes exactly what the
host kit pulls, with only the built-in token, from the realm's own build recipe, with no game data in the context.

    python3 tools/github-workflows/test_workflows.py        (needs PyYAML)
"""
import os
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load(name):
    text = (HERE / name).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    doc["on"] = doc.get("on", doc.pop(True, None))      # YAML 1.1 reads a bare `on` as True
    return text, doc


def steps(doc, job):
    return doc["jobs"][job]["steps"]


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class Workflows(unittest.TestCase):
    def test_all_parse(self):
        names = sorted(p.name for p in HERE.glob("*.yml"))
        self.assertEqual(names, ["leyline-launcher.yml", "realm-scripts.yml", "wu-hosting.yml", "wu-images.yml"])
        for n in names:
            text, doc = load(n)
            self.assertTrue(doc["name"] and doc["on"] and doc["jobs"], n)
            for job, j in doc["jobs"].items():
                self.assertIn("runs-on", j, f"{n}:{job}")
                for s in j["steps"]:
                    self.assertTrue("uses" in s or "run" in s, f"{n}:{job}: {s}")
                    if "uses" in s and not s["uses"].startswith("./"):
                        self.assertRegex(s["uses"], r"^[\w.-]+/[\w.-]+@(v\d+|stable)$", f"{n}: pin actions to a major")
            self.assertNotIn("\t", text, n)

    def test_images(self):
        text, doc = load("wu-images.yml")
        self.assertEqual(doc["on"]["push"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", doc["on"])
        paths = doc["on"]["push"]["paths"]
        for p in ("realm/custom/sources.lock", "realm/custom/patches/**", "realm/custom/fetch.sh",
                  "hosting/kit/tools/**", "hosting/relay/**"):
            self.assertIn(p, paths)
        self.assertEqual(doc["permissions"], {"contents": "read", "packages": "write"})
        self.assertEqual(set(re.findall(r"secrets\.([A-Za-z_]+)", text)), {"GITHUB_TOKEN"})
        # what the kit pulls (Host a Wrath realm.bat, host-wrath-realm.sh, setup.py)
        kit = (REPO / "hosting" / "kit" / "host-wrath-realm.sh").read_text()
        self.assertIn('WU_IMAGE:-ghcr.io/orionopenwow/wu-ac-wotlk}', kit)
        self.assertIn('WU_TAG:-stable}', kit)
        self.assertIn("ghcr.io/orionopenwow/wu-host-tools:1", kit)
        pushed = []
        for job in ("small", "realm"):
            for s in steps(doc, job):
                if s.get("uses", "").startswith("docker/build-push-action"):
                    w = s["with"]
                    self.assertTrue(w["push"])
                    tags = [t.strip() for t in w["tags"].splitlines() if t.strip()]
                    self.assertEqual(len(tags), 2)
                    self.assertTrue(tags[1].endswith(":${{ steps.t.outputs.sha }}"), tags)
                    pushed.append(tags[0])
                    if job == "realm":
                        # the realm's own recipe: realm/docker-compose.build.yml
                        self.assertEqual(w["context"], "realm/custom/acore")
                        self.assertEqual(w["file"], "realm/custom/acore/apps/docker/Dockerfile")
                        self.assertEqual(sorted(w["build-args"].split()),
                                         ["CTOOLS_BUILD=db-only", "CTYPE=Release", "CWITH_WARNINGS=OFF"])
                        self.assertEqual(tags[0], f"ghcr.io/orionopenwow/wu-ac-wotlk-{w['target']}:stable")
        self.assertEqual(sorted(pushed), sorted([
            "ghcr.io/orionopenwow/wu-ac-wotlk-db-import:stable", "ghcr.io/orionopenwow/wu-ac-wotlk-authserver:stable",
            "ghcr.io/orionopenwow/wu-ac-wotlk-worldserver:stable", "ghcr.io/orionopenwow/wu-host-tools:1",
            "ghcr.io/orionopenwow/wu-relay:1"]))
        compose = yaml.safe_load((REPO / "realm" / "docker-compose.build.yml").read_text())
        args = compose["x-build"]["args"]
        for k, v in args.items():
            self.assertIn(f"{k}={v}", text)
        # sources: fetch.sh (pinned commits + patches) before the build; no game data in the context
        realm = steps(doc, "realm")
        names = [s.get("name", s.get("uses", "")) for s in realm]
        i_fetch = next(i for i, s in enumerate(realm) if "fetch.sh" in s.get("run", ""))
        i_clean = next(i for i, s in enumerate(realm) if "patch-contents" in s.get("run", ""))
        i_build = next(i for i, s in enumerate(realm) if s.get("uses", "").startswith("docker/build-push-action"))
        self.assertLess(i_fetch, i_clean, names)
        self.assertLess(i_clean, i_build, names)
        self.assertIn("rm -rf realm/custom/acore/modules/mod-arac/patch-contents", realm[i_clean]["run"])
        self.assertIn("exit 1", realm[i_clean]["run"])
        owners = set(re.findall(r"ghcr\.io/([a-z0-9-]+)/", text)) | set(re.findall(r"github\.com/([A-Za-z0-9-]+)/", text))
        self.assertEqual(owners, {"orionopenwow"})

    def test_hosting_tests(self):
        text, doc = load("wu-hosting.yml")
        self.assertEqual(doc["permissions"], {"contents": "read"})
        self.assertNotRegex(text, r"secrets\.\w")
        run = "\n".join(s.get("run", "") for s in steps(doc, "tests"))
        self.assertIn("discover -s hosting/tests", run)

    def test_launcher(self):
        text, doc = load("leyline-launcher.yml")
        self.assertEqual(doc["on"]["push"]["tags"], ["launcher-v*"])
        self.assertEqual(doc["permissions"], {"contents": "read"})
        self.assertEqual(doc["jobs"]["release"]["permissions"], {"contents": "write"})
        self.assertEqual(set(re.findall(r"secrets\.([A-Za-z_]+)", text)), {"GITHUB_TOKEN"})
        # the update check reads the same (public) repo's releases
        upd = (REPO / "launcher" / "src-tauri" / "src" / "update.rs").read_text()
        self.assertIn('"https://api.github.com/repos/orionopenwow/Leyline/releases', upd)


if __name__ == "__main__":
    unittest.main()
