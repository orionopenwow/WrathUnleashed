"""Turn on GitHub builds (github_builds.py): the scope refresh only when needed, Actions on, the workflow files copied
in from tools/github-workflows/ and pushed (only those paths), the launcher tag, no double image build, safe to run
again, the checklist and the pages it opens, never the helper account. Real git against local bare repos; gh is faked.

    python3 tools/github-builds/test_github_builds.py
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import github_builds as gb  # noqa: E402

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="Owner", GIT_AUTHOR_EMAIL="owner@example.com",
               GIT_COMMITTER_NAME="Owner", GIT_COMMITTER_EMAIL="owner@example.com", GIT_TERMINAL_PROMPT="0")


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True).stdout


class FakeGitHub:
    def __init__(self, tmp):
        self.tmp = tmp
        self.scopes = "repo, read:org, gist"
        self.login = "orionopenwow"
        self.org_actions = {"enabled_repositories": "none", "allowed_actions": "all"}
        self.repo_actions = {gb.WU_REPO: False, gb.LY_REPO: True}
        self.secrets = []
        self.runs = []                      # wu-images runs, newest first
        self.ly_runs = []
        self.packages = {}
        self.calls = []
        self.remotes = {}                   # local folder -> slug

    def __call__(self, args, cwd=None, capture=True):
        self.calls.append((tuple(args), str(cwd) if cwd else None, capture))
        if args[0] == "git":
            if args[1:3] == ["remote", "get-url"]:
                slug = self.remotes.get(str(cwd))
                return (0, f"https://github.com/{slug}.git\n", "") if slug else (2, "", "no origin")
            if args[1:] == ["--version"]:
                return 0, "git version 2", ""
            p = subprocess.run(args, cwd=cwd, env=GIT_ENV, capture_output=True, text=True)
            if args[-2:] == ["origin", "HEAD:main"] and "wu-images.yml" in self.pushed_files(cwd):
                self.runs.insert(0, {"status": "in_progress", "conclusion": None})
            return p.returncode, p.stdout, p.stderr
        a = args[1:]
        if a == ["--version"]:
            return 0, "gh version 2", ""
        if a[:2] == ["auth", "refresh"]:
            assert capture is False                       # the device flow talks to the owner directly
            self.scopes = "repo, read:org, gist, workflow, write:packages, admin:org"
            return 0, "", ""
        if a[0] == "api":
            return self.api(a[1:])
        if a[:2] == ["secret", "list"]:
            return 0, json.dumps([{"name": n} for n in self.secrets]), ""
        if a[:2] == ["repo", "view"]:
            return 0, '{"name":"x"}', ""
        if a[:2] == ["run", "list"]:
            wf = a[a.index("--workflow") + 1]
            return 0, json.dumps(self.runs if wf == "wu-images.yml" else self.ly_runs), ""
        if a[:2] == ["workflow", "run"]:
            self.runs.insert(0, {"status": "queued", "conclusion": None})
            return 0, "", ""
        raise AssertionError(f"unexpected gh call {args}")

    def pushed_files(self, cwd):
        out = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=cwd, capture_output=True,
                             text=True).stdout
        return out

    def api(self, a):
        method = "GET"
        if "-X" in a:
            method = a[a.index("-X") + 1]
        path = a[-1]
        if path == "user":
            return 0, f"HTTP/2.0 200 OK\nX-Oauth-Scopes: {self.scopes}\n\n" + json.dumps({"login": self.login}), ""
        if path == f"users/{gb.OWNER}":
            return 0, json.dumps({"type": "Organization"}), ""
        if path == f"orgs/{gb.OWNER}/actions/permissions":
            if method == "PUT":
                self.org_actions = {"enabled_repositories": "all", "allowed_actions": "all"}
                return 0, "", ""
            return 0, json.dumps(self.org_actions), ""
        for r in (gb.WU_REPO, gb.LY_REPO):
            if path == f"repos/{r}/actions/permissions":
                if method == "PUT":
                    self.repo_actions[r] = True
                    return 0, "", ""
                return 0, json.dumps({"enabled": self.repo_actions[r]}), ""
        if "/packages/container/" in path:
            name = path.rsplit("/", 1)[1]
            if name in self.packages:
                return 0, json.dumps({"visibility": self.packages[name]}), ""
            return 1, "", "Not Found"
        raise AssertionError(f"unexpected api {a}")


class TurnOn(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wu-ghb-"))
        self.gh = FakeGitHub(self.tmp)
        self.wu = self.make_repo("WrathUnleashed", gb.WU_REPO)
        conf = self.wu / "launcher" / "src-tauri"
        conf.mkdir(parents=True)
        (conf / "tauri.conf.json").write_text('{"productName": "Leyline", "version": "0.2.0"}')
        git("add", "-A", cwd=self.wu)
        git("commit", "-qm", "launcher", cwd=self.wu)
        git("push", "-q", "origin", "HEAD:main", cwd=self.wu)
        (self.wu / "work-in-progress.txt").write_text("not for this commit\n")      # the owner's other changes
        self.ly = self.make_repo("Leyline", gb.LY_REPO)
        (self.ly / "launcher" / "src-tauri").mkdir(parents=True)
        (self.ly / "launcher" / "src-tauri" / "tauri.conf.json").write_text('{"version": "0.2.0"}')
        git("add", "-A", cwd=self.ly)
        git("commit", "-qm", "export", cwd=self.ly)
        git("push", "-q", "origin", "HEAD:main", cwd=self.ly)
        self.opened = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_repo(self, name, slug):
        bare = self.tmp / f"{name}.git"
        git("init", "-q", "--bare", "-b", "main", str(bare), cwd=self.tmp)
        d = self.tmp / name
        git("clone", "-q", str(bare), str(d), cwd=self.tmp)
        git("checkout", "-q", "-b", "main", cwd=d)
        (d / "README.md").write_text(name + "\n")
        git("add", "-A", cwd=d)
        git("commit", "-qm", "first", cwd=d)
        git("push", "-q", "origin", "HEAD:main", cwd=d)
        self.gh.remotes[str(d)] = slug
        return d

    def go(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = gb.main(["--repo-dir", str(self.wu), "--leyline-dir", str(self.ly), "--no-wait", *extra],
                         gh=gb.GitHub(self.gh), sleep=lambda s: None, opener=self.opened.append)
        return rc, out.getvalue()

    def remote_files(self, name, ref="main"):
        return git("ls-tree", "-r", "--name-only", ref, cwd=self.tmp / f"{name}.git").split()

    def calls(self, *prefix):
        return [c for c in self.gh.calls if c[0][:len(prefix)] == prefix]

    def test_first_run(self):
        rc, out = self.go()
        self.assertEqual(rc, 0, out)
        self.assertIn("GITHUB BUILDS OK", out)
        # the permissions: one refresh, with exactly the three scopes, in the owner's own console
        refresh = self.calls("gh", "auth", "refresh")
        self.assertEqual(len(refresh), 1)
        self.assertEqual(refresh[0][0][-1], "workflow,write:packages,admin:org")
        # Actions turned on (org was off, WrathUnleashed was off)
        self.assertEqual(self.gh.org_actions["enabled_repositories"], "all")
        self.assertTrue(self.gh.repo_actions[gb.WU_REPO])
        # the workflow files, byte for byte the source copies, and nothing else of the owner's
        wu_files = self.remote_files("WrathUnleashed")
        for f in gb.WU_FILES:
            self.assertIn(f".github/workflows/{f}", wu_files)
            self.assertEqual(git("show", f"main:.github/workflows/{f}", cwd=self.tmp / "WrathUnleashed.git"),
                             (gb.SRC / f).read_text().replace("\r\n", "\n"))
        self.assertNotIn(".github/workflows/realm-scripts.yml", wu_files)      # no deploy secret yet
        self.assertNotIn(".github/workflows/leyline-launcher.yml", wu_files)   # the launcher builds in Leyline
        self.assertNotIn("work-in-progress.txt", wu_files)
        self.assertIn(".github/workflows/leyline-launcher.yml", self.remote_files("Leyline"))
        # the push started wu-images: no second (1-3 hour) build
        self.assertEqual(self.calls("gh", "workflow", "run"), [])
        self.assertIn("wu-images started by the push", out)
        # the launcher tag on Leyline, at the commit that has the workflow
        tags = git("tag", "--points-at", "main", cwd=self.tmp / "Leyline.git").split()
        self.assertEqual(tags, ["launcher-v0.2.0"])
        # every push used gh's credential for that one command
        for c in self.calls("git"):
            if "push" in c[0]:
                self.assertIn("credential.helper=!gh auth git-credential", c[0])
        # not built yet: no package pages yet, but the org package setting and the checklist
        self.assertIn("Not built yet", out)
        self.assertEqual(self.opened, [f"https://github.com/organizations/{gb.OWNER}/settings/packages"])
        self.assertIn("40000-40999", out)
        self.assertIn("releases/tag/launcher-v0.2.0", out)

    def test_owner_folder_untouched(self):
        (self.wu / "unshipped.txt").write_text("a local commit Ship hasn't pushed yet\n")
        git("add", "unshipped.txt", cwd=self.wu)
        git("commit", "-qm", "local only", cwd=self.wu)
        head = git("rev-parse", "HEAD", cwd=self.wu)
        rc, out = self.go()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("unshipped.txt", self.remote_files("WrathUnleashed"))       # only the workflow commit
        self.assertIn(".github/workflows/wu-images.yml", self.remote_files("WrathUnleashed"))
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.wu), head)                # branch as it was
        self.assertFalse((self.wu / ".github").exists())                              # working tree as it was
        self.assertEqual(len(git("worktree", "list", cwd=self.wu).splitlines()), 1)  # no worktree left
        self.assertEqual(len(git("worktree", "list", cwd=self.ly).splitlines()), 1)
        # the next Ship merges GitHub's main in without trouble
        git("fetch", "-q", "origin", cwd=self.wu)
        git("merge", "-q", "--no-edit", "origin/main", cwd=self.wu)
        self.assertTrue((self.wu / ".github" / "workflows" / "wu-images.yml").is_file())

    def test_run_again(self):
        self.assertEqual(self.go()[0], 0)
        head_wu = git("rev-parse", "main", cwd=self.tmp / "WrathUnleashed.git")
        head_ly = git("rev-parse", "main", cwd=self.tmp / "Leyline.git")
        self.gh.runs = [{"status": "completed", "conclusion": "success"}]
        self.gh.packages = {n: "private" for n in gb.PACKAGES}
        self.gh.packages["wu-relay"] = "public"
        self.gh.calls.clear()
        self.opened.clear()
        rc, out = self.go()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls("gh", "auth", "refresh"), [])                # scopes already there
        self.assertEqual(git("rev-parse", "main", cwd=self.tmp / "WrathUnleashed.git"), head_wu)  # nothing new
        self.assertEqual(git("rev-parse", "main", cwd=self.tmp / "Leyline.git"), head_ly)
        self.assertIn("already up to date", out)
        self.assertIn("launcher-v0.2.0 is already on GitHub", out)
        self.assertEqual(self.calls("gh", "workflow", "run"), [])                 # last build passed
        want = [gb.package_url("Organization", n) for n in gb.PACKAGES if n != "wu-relay"]
        self.assertEqual(self.opened[1:], want)
        self.assertIn("/orgs/orionopenwow/packages/container/wu-ac-wotlk-worldserver/settings", out)
        self.assertNotIn("wu-relay/settings", out)

    def test_all_public_opens_nothing(self):
        self.go()
        self.gh.runs = [{"status": "completed", "conclusion": "success"}]
        self.gh.packages = {n: "public" for n in gb.PACKAGES}
        self.opened.clear()
        rc, out = self.go()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.opened, [])
        self.assertNotIn("Change visibility", out)

    def test_failed_build_is_restarted(self):
        self.go()
        self.gh.runs = [{"status": "completed", "conclusion": "failure"}]
        self.gh.calls.clear()
        rc, out = self.go()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls("gh", "workflow", "run")), 1)

    def test_deploy_workflow_only_with_its_secret(self):
        self.gh.secrets = ["WU_DEPLOY_SSH_KEY", "WU_KNOWN_HOSTS"]
        self.assertEqual(self.go()[0], 0)
        self.assertIn(".github/workflows/realm-scripts.yml", self.remote_files("WrathUnleashed"))

    def test_never_the_helper_account(self):
        self.gh.login = "Chumpton"
        rc, out = self.go()
        self.assertEqual(rc, 1)
        self.assertIn("gh auth switch", out)
        self.assertEqual(self.calls("gh", "auth", "refresh"), [])
        self.assertNotIn(".github/workflows/wu-images.yml", self.remote_files("WrathUnleashed"))

    def test_wait_shows_progress(self):
        self.gh.runs = [{"status": "completed", "conclusion": "success"}]
        self.gh.ly_runs = [{"status": "completed", "conclusion": "success"}]
        out = io.StringIO()
        with redirect_stdout(out):
            res = gb.wait_runs(gb.GitHub(self.gh), [(gb.WU_REPO, "wu-images.yml"), (gb.LY_REPO, "leyline-launcher.yml")],
                               5, sleep=lambda s: None)
        self.assertEqual(set(res.values()), {"success"})
        self.assertIn("wu-images: success", out.getvalue())

    def test_scopes(self):
        self.assertEqual(gb.parse_scopes("x-oauth-scopes: repo, workflow, admin:org\n"), {"repo", "workflow", "admin:org"})
        self.assertEqual(gb.has_scopes({"repo", "workflow", "write:packages", "admin:org"}), [])
        self.assertEqual(gb.has_scopes({"repo", "read:packages"}), ["workflow", "write:packages", "admin:org"])
        self.assertEqual(gb.has_scopes(set()), list(gb.NEED_SCOPES))

    def test_bat(self):
        bat = (gb.ROOT / "Turn on GitHub builds.bat").read_text()
        self.assertIn(r"tools\github-builds\github_builds.py", bat)
        self.assertIn("pause", bat)
        said = "\n".join(ln for ln in bat.splitlines() if ln.lower().startswith("echo") or "echo " in ln.lower())
        for w in ("warcraft", "blizzard", "lich king"):
            self.assertNotIn(w, said.lower())
        src = gb.ROOT / "tools" / "github-workflows"
        for f in gb.WU_FILES + gb.LY_FILES + (gb.DEPLOY_FILE,):
            self.assertTrue((src / f).is_file(), f)


if __name__ == "__main__":
    unittest.main()
