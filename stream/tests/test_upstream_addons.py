"""stream/upstream_addons.py: reviewed upstream addons merged into /wrath/mods/all.json, each checked again
(own repo, allowed address shape, pinned commit, reviewed, no native code, no brand words).

    python3 -I stream/tests/test_upstream_addons.py
"""
import importlib.util, json, os, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("upstream_addons", os.path.join(HERE, "..", "upstream_addons.py"))
ua = importlib.util.module_from_spec(spec); spec.loader.exec_module(ua)

C = "0123456789abcdef0123456789abcdef01234567"


def entry(**kw):
    e = {"id": "up:frames", "source": "upstream", "name": "Frames", "description": "Unit frames.", "native": False,
         "repo": "https://github.com/alice/Frames", "blp": "none", "review": {"by": "owner", "at": "2026-10-31", "notes": ""},
         "install": {"from": "commit-archive", "url": f"https://github.com/alice/Frames/archive/{C}.zip", "rev": C,
                     "folders": {"Frames": "Frames"}, "files_digest": "ab" * 32, "sha256": None}}
    for k, v in kw.items():
        if k.startswith("install_"):
            e["install"][k[8:]] = v
        else:
            e[k] = v
    return e


ALL = json.dumps({"format": 1, "projects": [{"id": "mod:pings", "source": "packaged", "name": "Pings"},
                                            {"id": "link:aaaaaaaaaaaa", "source": "community", "name": "Zed"}]}).encode()


class Upstream(unittest.TestCase):
    def test_merges_reviewed_entries_sorted_by_name(self):
        out = json.loads(ua.add_upstream(ALL, [entry(), entry(id="up:aaa", name="Alpha")]))
        self.assertEqual([p["id"] for p in out["projects"]], ["up:aaa", "up:frames", "mod:pings", "link:aaaaaaaaaaaa"])
        again = json.loads(ua.add_upstream(json.dumps(out).encode(), [entry()]))
        self.assertEqual(len(again["projects"]), 4, "once")

    def test_every_entry_is_checked_again(self):
        bad = [
            entry(id="mod:frames"), entry(id="up:Bad"), entry(source="community"), entry(native=True),
            entry(review={"by": "", "at": "", "notes": ""}), entry(name="WoW Frames"), entry(name="Lich King Frames"),
            entry(description="For World of Warcraft"), entry(blp="maybe"),
            entry(install_url=f"https://github.com/mallory/Frames/archive/{C}.zip"),
            entry(install_url="https://github.com/alice/Frames/archive/refs/heads/main.zip"),
            entry(install_rev="main", install_url="https://github.com/alice/Frames/archive/main.zip"),
            entry(install_from="mirror", install_url="https://play.openvanilla.app/wrath/mods/up/frames.zip"),
            entry(install_from="release-asset", install_url="https://github.com/alice/Frames/releases/download/v1/x.exe"),
            entry(install_from="release-asset", install_url="https://github.com/alice/Frames/releases/download/v1/../x.zip"),
            entry(install_files_digest="nothex"), entry(install_folders={}),
            entry(repo="https://evil.example.com/alice/Frames"),
        ]
        for b in bad:
            self.assertFalse(ua.valid(b), b)
        self.assertTrue(ua.valid(entry()))
        self.assertTrue(ua.valid(entry(install_from="release-asset", install_rev="v1.2",
                                       install_url="https://github.com/alice/Frames/releases/download/v1.2/Frames.zip")))
        self.assertTrue(ua.valid(entry(repo="https://codeberg.org/alice/Frames",
                                       install_url=f"https://codeberg.org/alice/Frames/archive/{C}.zip")))
        self.assertEqual(ua.add_upstream(ALL, bad), ALL, "nothing valid: the body is unchanged")

    def test_reads_the_published_file_and_survives_odd_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "upstream-addons.json")
            self.assertEqual(ua.projects(p), [])
            with open(p, "w") as f:
                json.dump({"format": 1, "projects": [entry(), entry(id="up:x", native=True)]}, f)
            self.assertEqual([x["id"] for x in ua.projects(p)], ["up:frames"])
            with open(p, "w") as f:
                f.write("{not json")
            os.utime(p, (1, 1))
            self.assertEqual(ua.projects(p), [])
        self.assertEqual(ua.add_upstream(b"not json", [entry()]), b"not json")
        self.assertEqual(ua.add_upstream(b'{"projects": 5}', [entry()]), b'{"projects": 5}')

    def test_the_committed_list_is_valid(self):
        path = os.path.join(HERE, "..", "upstream-addons.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        for p in doc["projects"]:
            self.assertTrue(ua.valid(p), p.get("id"))
            self.assertNotIn("files", p["install"], "all.json carries the digest, not the list")


if __name__ == "__main__":
    unittest.main()
