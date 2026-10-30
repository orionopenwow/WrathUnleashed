import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(__file__))
import gh_cleanup as g

class Fake:
    def __init__(self, who="orionopenwow", pk_ok=True):
        self.who, self.pk_ok, self.calls = who, pk_ok, []
        self.rels = [{"id": i, "tag_name": f"v1.{i}", "name": f"R {i}"} for i in range(56, 50, -1)] + [{"id": 9, "tag_name": "engine", "name": "Engine"}]
    def __call__(self, args):
        self.calls.append(args); s = " ".join(args)
        if s.endswith("user --jq .login"): return 0, self.who
        if "releases/latest" in s: return 0, "v1.56"
        if "releases?per_page" in s: return 0, json.dumps(self.rels)
        if "packages?package_type" in s: return (0, json.dumps([{"name": n} for n in ("openvanilla-realm", "openwow-realm")])) if self.pk_ok else (1, "HTTP 403 needs read:packages")
        if "-X DELETE" in s: return 0, ""
        return 1, "?"

def go(fake, plan=None, argv=()):
    d = tempfile.mkdtemp(); pf = os.path.join(d, "PLAN.json")
    if plan is not None: json.dump(plan, open(pf, "w"))
    out = []
    rc = g.main(list(argv), gh=g.GitHub(fake), out=out.append, plan_file=pf)
    return rc, "\n".join(out)

class T(unittest.TestCase):
    def test_dry(self):
        f = Fake(); rc, o = go(f)
        self.assertEqual(rc, 0); self.assertIn("keep the newest release 'v1.56'", o); self.assertIn("5 other", o)
        self.assertFalse(any("DELETE" in a for a in f.calls))
    def test_wrong_account(self):
        rc, o = go(Fake(who="chumpton"), argv=["--go"]); self.assertEqual(rc, 1); self.assertIn("not orionopenwow", o)
    def test_plan_mismatch(self):
        f = Fake(); rc, o = go(f, {"keep_release": "v1.55", "delete_release_tags": []}, ["--go"])
        self.assertEqual(rc, 1); self.assertFalse(any("DELETE" in a for a in f.calls))
    def test_go(self):
        f = Fake(); plan = {"keep_release": "v1.56", "delete_release_tags": [f"v1.{i}" for i in range(51, 56)], "delete_packages": ["openwow-realm", "openvanilla-realm", "gone-one"]}
        rc, o = go(f, plan, ["--go"]); self.assertEqual(rc, 0, o)
        dels = [" ".join(a) for a in f.calls if "DELETE" in a]
        self.assertFalse(any("releases/56" in d or "releases/9" in d for d in dels), "newest and engine kept"); self.assertEqual(sum("git/refs/tags" in d for d in dels), 5)
        self.assertTrue(any("container/openwow-realm" in d for d in dels)); self.assertIn("gone-one: already gone", o)
    def test_no_scope(self):
        f = Fake(pk_ok=False); plan = {"keep_release": "v1.56", "delete_release_tags": [f"v1.{i}" for i in range(51, 56)], "delete_packages": ["openwow-realm"]}
        rc, o = go(f, plan, ["--go"]); self.assertEqual(rc, 1); self.assertIn("gh auth refresh", o)

if __name__ == "__main__": unittest.main()
