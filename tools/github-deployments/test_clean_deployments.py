import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clean_deployments as C  # noqa: E402


class FakeGH(C.GitHub):
    def __init__(self, deps, login="orionopenwow"):
        self.deps = {r: list(v) for r, v in deps.items()}
        self.who = login
        self.calls = []
        super().__init__(runner=self.fake)

    def fake(self, args):
        self.calls.append(args)
        if args[:3] == ["gh", "api", "user"]:
            return 0, self.who + "\n"
        if args[:3] == ["gh", "api", "--paginate"]:
            repo = args[3].split("/deployments")[0][len("repos/"):]
            items = self.deps.get(repo, [])
            pages = [items[i:i + 2] for i in range(0, len(items), 2)] or [[]]
            return 0, "".join(json.dumps(p) + "\n" for p in pages)
        if "-X" in args and args[args.index("-X") + 1] == "DELETE":
            repo, dep = args[-1][len("repos/"):].split("/deployments/")
            self.deps[repo] = [d for d in self.deps[repo] if str(d["id"]) != dep]
            return 0, ""
        if "-X" in args:
            return 0, "{}"
        raise AssertionError(args)


def dep(i, env="github-pages", t="2026-10-29T10:00:00Z"):
    return {"id": i, "environment": env, "created_at": t}


R = "orionopenwow/Leyline-Launcher"


class Tests(unittest.TestCase):
    def setUp(self):
        self.lines = []

    def go(self, argv, gh, answer="YES"):
        return C.main(argv, gh=gh, ask=lambda _: answer, out=self.lines.append)

    def test_list_only_by_default(self):
        gh = FakeGH({R: [dep(1), dep(2), dep(3)]})
        self.assertEqual(self.go(["--repo", R], gh), 0)
        self.assertEqual(len(gh.deps[R]), 3)
        self.assertFalse(any("DELETE" in c for c in gh.calls))
        self.assertIn("3 deployment(s)", "\n".join(self.lines))

    def test_delete_all_after_yes_deactivating_first(self):
        gh = FakeGH({R: [dep(i, t=f"2026-10-{10 + i}T00:00:00Z") for i in range(1, 6)]})
        self.assertEqual(self.go(["--repo", R, "--delete"], gh), 0)
        self.assertEqual(gh.deps[R], [])
        kinds = [c[c.index("-X") + 1] for c in gh.calls if "-X" in c]
        self.assertEqual(kinds, ["POST", "DELETE"] * 5)          # inactive first, then delete
        self.assertIn("Deleted 5", "\n".join(self.lines))

    def test_nothing_without_yes(self):
        gh = FakeGH({R: [dep(1)]})
        self.assertEqual(self.go(["--repo", R, "--delete"], gh, answer="yes please"), 1)
        self.assertEqual(len(gh.deps[R]), 1)

    def test_yes_flag_skips_the_second_question(self):
        gh = FakeGH({R: [dep(1)]})
        self.assertEqual(self.go(["--repo", R, "--delete", "--yes"], gh, answer="no"), 0)
        self.assertEqual(gh.deps[R], [])

    def test_keep_latest_per_environment(self):
        deps = [dep(1, t="2026-10-01T00:00:00Z"), dep(2, t="2026-10-29T00:00:00Z"),
                dep(3, env="preview", t="2026-10-05T00:00:00Z")]
        gh = FakeGH({R: deps})
        self.go(["--repo", R, "--delete", "--keep-latest"], gh)
        self.assertEqual(sorted(d["id"] for d in gh.deps[R]), [2, 3])

    def test_never_the_helper_account(self):
        gh = FakeGH({R: [dep(1)]}, login="Chumpton")
        self.assertEqual(self.go(["--repo", R, "--delete"], gh), 1)
        self.assertEqual(len(gh.deps[R]), 1)
        self.assertIn("STOPPED", "\n".join(self.lines))


if __name__ == "__main__":
    unittest.main()
