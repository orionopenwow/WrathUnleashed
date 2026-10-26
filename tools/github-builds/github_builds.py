#!/usr/bin/env python3
"""Turn on GitHub builds: everything "Turn on GitHub builds.bat" does, on the owner's PC, with his own gh sign-in.

    py -3 tools\\github-builds\\github_builds.py [--no-wait] [--no-browser] [--leyline-dir DIR]

1. GitHub sign-in: the active gh account (never the helper account), and the scopes the builds need
   (workflow, write:packages, admin:org). Missing ones: `gh auth refresh` (browser device flow, one click).
   Scopes are read from the X-OAuth-Scopes header; no token is ever printed.
2. Actions on, where the API allows it: the organization (if Actions are off for it, or the repos are not on
   its "selected" list) and both repos (WrathUnleashed, Leyline).
3. The workflow files, copied from tools/github-workflows/ (the source copies) and pushed with gh's credential:
     WrathUnleashed (.github/workflows/): wu-images.yml, wu-hosting.yml, and realm-scripts.yml once the deploy
       secret exists ("Set up automatic deploys.bat"), so its deploy job can't fail for lack of it;
     Leyline (the public repo, %USERPROFILE%\\Desktop\\Leyline): leyline-launcher.yml. Launcher releases go
       there because players can't download release files from the private repo, and Actions minutes are free
       on a public repo.
   The commit is made on top of GitHub's own main in a throwaway worktree: the folders' branches, working
   trees and unshipped commits are never touched or pushed.
4. Builds: wu-images starts by itself from the push that adds it; otherwise it is started (gh workflow run)
   unless a run is going or the last one passed. The launcher tag launcher-v<version> (from
   launcher/src-tauri/tauri.conf.json) is pushed to Leyline unless it is already there.
5. Waits and shows progress (one line a minute; Ctrl+C is fine: running this again picks up where it left off),
   then opens the pages GitHub has no API for (each image's visibility -> Public, the org's package setting)
   and prints the checklist.

Safe to run again: every step checks first and does nothing when it is already done.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the WrathUnleashed folder (a git clone of the repo)
OWNER = "orionopenwow"
WU_REPO = f"{OWNER}/WrathUnleashed"
LY_REPO = f"{OWNER}/Leyline"
SRC = ROOT / "tools" / "github-workflows"
NEED_SCOPES = ("workflow", "write:packages", "admin:org")
WU_FILES = ("wu-images.yml", "wu-hosting.yml")
DEPLOY_FILE, DEPLOY_SECRET = "realm-scripts.yml", "WU_DEPLOY_SSH_KEY"
LY_FILES = ("leyline-launcher.yml",)
PACKAGES = ("wu-ac-wotlk-db-import", "wu-ac-wotlk-authserver", "wu-ac-wotlk-worldserver", "wu-host-tools", "wu-relay")
NOT_OWNER = ("chumpton",)                           # the helper account never publishes for the owner
# git pushes with gh's own credential for this one command (no change to git's config, nothing printed)
GH_CRED = ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
HETZNER_STEPS = [
    "Open https://console.hetzner.cloud and pick the project with the play server.",
    "Left menu: Firewalls. No firewall listed, or none applied to the server: nothing to do.",
    "Open the firewall that is applied to the server, tab Rules, under Inbound: Add rule.",
    "Protocol TCP, Port 40000-40999, Source IPs: Any IPv4 (0.0.0.0/0) and Any IPv6 (::/0). Save (Add rule).",
    "Check with the relay step again: it ends with 'game ports 40000-40999: reachable'.",
]


class Fail(Exception):
    pass


LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "github-builds.log"


def say(msg=""):
    print(msg, flush=True)
    # Also kept in logs\github-builds.log, so the result can be read back without the window.
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except OSError:
        pass


class GitHub:
    """Every outside command goes through runner(args, cwd, capture) -> (rc, stdout, stderr); the tests replace it."""

    def __init__(self, runner=None):
        self.runner = runner or self._run

    @staticmethod
    def _run(args, cwd=None, capture=True):
        try:
            p = subprocess.run(args, cwd=cwd, capture_output=capture, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return 127, "", f"{args[0]}: not found"
        return p.returncode, p.stdout or "", p.stderr or ""

    def run(self, args, cwd=None, capture=True):
        """(rc, stdout + stderr). Captured output is only parsed, never printed."""
        rc, out, err = self.runner(list(args), cwd=cwd, capture=capture)
        return rc, (out or "") + ("\n" + err if err else "")

    def api(self, path, *extra):
        return self.run(["gh", "api", *extra, path])

    def api_json(self, path):
        rc, out, _ = self.runner(["gh", "api", path], cwd=None, capture=True)
        if rc != 0:
            return None
        try:
            return json.loads(out)
        except ValueError:
            return None


# ------------------------------------------------------------------------------------------------ sign-in
def parse_scopes(headers: str) -> set[str]:
    m = re.search(r"(?im)^x-oauth-scopes:\s*(.*)$", headers)
    if not m:
        return set()
    return {s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()}


def has_scopes(have: set[str], need=NEED_SCOPES) -> list[str]:
    implied = set(have)
    if "admin:org" in have:
        implied |= {"write:org", "read:org"}
    if "write:packages" in have:
        implied |= {"read:packages"}
    return [s for s in need if s not in implied]


def signin(gh: GitHub) -> str:
    rc, out = gh.api("user", "-i")
    if rc != 0:
        raise Fail("The GitHub CLI is not signed in. Run once:  gh auth login   (as the owner), then run this again.")
    login = (re.search(r'"login"\s*:\s*"([^"]+)"', out) or [None, ""])[1]
    if not login or login.lower() in NOT_OWNER:
        raise Fail(f"The GitHub CLI is signed in as {login or '?'}. Switch to the owner's account (gh auth switch), "
                   "then run this again.")
    missing = has_scopes(parse_scopes(out))
    if missing:
        say(f"  GitHub needs {', '.join(missing)} for the builds. A browser page opens: sign in if asked, enter the")
        say("  code shown here, and click Authorize.")
        rc, _ = gh.run(["gh", "auth", "refresh", "-h", "github.com", "-s", ",".join(NEED_SCOPES)], capture=False)
        if rc != 0:
            raise Fail("The permission step did not finish. Run this again and click Authorize in the browser.")
        rc, out = gh.api("user", "-i")
        missing = has_scopes(parse_scopes(out))
        if missing:
            raise Fail(f"GitHub still lacks {', '.join(missing)}. Run this again.")
    say(f"  signed in as {login}, permissions ok")
    return login


# ------------------------------------------------------------------------------------------------ Actions on
def actions_on(gh: GitHub, owner_type: str, todo: list[str]) -> None:
    repos = [WU_REPO, LY_REPO]
    if owner_type == "Organization":
        cur = gh.api_json(f"orgs/{OWNER}/actions/permissions") or {}
        enabled, allowed = cur.get("enabled_repositories"), cur.get("allowed_actions")
        if enabled == "none":
            rc, _ = gh.api(f"orgs/{OWNER}/actions/permissions", "-X", "PUT", "-f", "enabled_repositories=all",
                           "-f", "allowed_actions=all")
            say("  Actions turned on for the organization" if rc == 0 else "  !! could not turn on Actions for the org")
            if rc != 0:
                todo.append(f"Organization Actions: allow Actions for all repositories: "
                            f"https://github.com/organizations/{OWNER}/settings/actions")
        elif enabled == "selected":
            for r in repos:
                info = gh.api_json(f"repos/{r}") or {}
                if info.get("id"):
                    gh.api(f"orgs/{OWNER}/actions/permissions/repositories/{info['id']}", "-X", "PUT")
            say("  Actions: both repos are on the organization's list")
        elif enabled == "all":
            say("  Actions are on for the organization")
        else:
            todo.append(f"Organization Actions (could not read the setting): allow Actions for all repositories: "
                        f"https://github.com/organizations/{OWNER}/settings/actions")
        if allowed not in (None, "all") and enabled != "none":
            todo.append(f"Organization Actions: 'Allow all actions and reusable workflows' (the builds use "
                        f"docker/*, tauri-apps, dtolnay, swatinem): https://github.com/organizations/{OWNER}/settings/actions")
    for r in repos:
        cur = gh.api_json(f"repos/{r}/actions/permissions")
        if cur is None:
            continue                                   # repo missing (Leyline not made yet): handled later
        if not cur.get("enabled"):
            rc, _ = gh.api(f"repos/{r}/actions/permissions", "-X", "PUT", "-F", "enabled=true", "-f", "allowed_actions=all")
            say(f"  Actions turned on for {r}" if rc == 0 else f"  !! could not turn on Actions for {r}")
            if rc != 0:
                todo.append(f"{r}: Settings > Actions > General > Allow all actions: https://github.com/{r}/settings/actions")
        else:
            say(f"  Actions are on for {r}")


# ------------------------------------------------------------------------------------------------ git
def origin_ok(gh: GitHub, d: Path, slug: str) -> bool:
    rc, out = gh.run(["git", "remote", "get-url", "origin"], cwd=d)
    u = out.strip().lower()
    return rc == 0 and (f"github.com/{slug.lower()}" in u or f"github.com:{slug.lower()}" in u)


def put_workflows(gh: GitHub, d: Path, slug: str, files, msg: str) -> tuple[list[str], str]:
    """Commits the files as .github/workflows/<file> on top of GitHub's own main, in a throwaway worktree, and
    pushes that one commit. The folder's own branch, working tree and unshipped commits are never touched or
    pushed (the next Ship / Leyline step merges GitHub's main in as usual). Returns (changed files, commit)."""
    rc, out = gh.run(["git", *GH_CRED, "fetch", "-q", "origin"], cwd=d)
    if rc != 0 or gh.run(["git", "rev-parse", "-q", "--verify", "origin/main"], cwd=d)[0] != 0:
        raise Fail(f"Could not read {slug}'s main from GitHub (is this PC online?). Nothing was pushed.")
    tmp = Path(tempfile.mkdtemp(prefix="wu-ghb-"))
    wt = tmp / "wt"
    rc, out = gh.run(["git", "worktree", "add", "-q", "--detach", str(wt), "origin/main"], cwd=d)
    if rc != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise Fail(f"Could not prepare the commit in {d} (git worktree). Nothing was pushed.")
    try:
        (wt / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        changed = []
        for f in files:
            (wt / ".github" / "workflows" / f).write_bytes((SRC / f).read_bytes().replace(b"\r\n", b"\n"))
            rel = f".github/workflows/{f}"
            gh.run(["git", "add", "--", rel], cwd=wt)
            if gh.run(["git", "diff", "--cached", "--quiet", "--", rel], cwd=wt)[0] != 0:
                changed.append(f)
        if changed:
            rc, out = gh.run(["git", "commit", "-q", "-m", msg], cwd=wt)
            if rc != 0:
                raise Fail(f"Could not commit the workflow files in {d} (set git user.name and user.email once).")
            rc, out = gh.run(["git", *GH_CRED, "push", "-q", "origin", "HEAD:main"], cwd=wt)
            if rc != 0:
                raise Fail(f"Pushing to {slug} failed (GitHub's main moved?). Nothing was forced. Run this again.")
            say(f"  {slug}: pushed {', '.join(changed)}")
        else:
            say(f"  {slug}: workflow files already up to date")
        rev = gh.run(["git", "rev-parse", "HEAD"], cwd=wt)[1].strip().split("\n")[0]
        return changed, rev
    finally:
        gh.run(["git", "worktree", "remove", "--force", str(wt)], cwd=d)
        gh.run(["git", "worktree", "prune"], cwd=d)
        shutil.rmtree(tmp, ignore_errors=True)


def launcher_version(d: Path) -> str:
    conf = json.loads((d / "launcher" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8-sig"))
    v = conf.get("version") or ""
    if not re.fullmatch(r"\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?", v):
        raise Fail(f"launcher/src-tauri/tauri.conf.json has no usable version ({v!r}).")
    return v


def push_tag(gh: GitHub, d: Path, tag: str, rev: str) -> bool:
    """Tags GitHub's main (rev, with the workflow in it). True when pushed now, False when GitHub already has it."""
    rc, out = gh.run(["git", *GH_CRED, "ls-remote", "--tags", "origin", f"refs/tags/{tag}"], cwd=d)
    if rc == 0 and tag in out:
        say(f"  {tag} is already on GitHub")
        return False
    rc, _ = gh.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=d)
    if rc != 0:
        rc, _ = gh.run(["git", "tag", tag, rev], cwd=d)
        if rc != 0:
            raise Fail(f"Could not make the tag {tag}.")
    rc, _ = gh.run(["git", *GH_CRED, "push", "-q", "origin", f"refs/tags/{tag}"], cwd=d)
    if rc != 0:
        raise Fail(f"Pushing the tag {tag} failed.")
    say(f"  {tag} pushed: the launcher installers build now (about 20 minutes)")
    return True


# ------------------------------------------------------------------------------------------------ runs
def runs(gh: GitHub, repo: str, workflow: str) -> list[dict]:
    rc, out = gh.run(["gh", "run", "list", "-R", repo, "--workflow", workflow, "--limit", "5",
                      "--json", "databaseId,status,conclusion,event,headBranch,createdAt,url"])
    if rc != 0:
        return []
    try:
        return json.loads(out[out.index("["):out.rindex("]") + 1])
    except ValueError:
        return []


def start_images(gh: GitHub, pushed_now: bool, sleep=time.sleep) -> str:
    """wu-images: 'started' (pushed or dispatched now), 'running', or 'done' (the last run passed)."""
    if pushed_now:
        for _ in range(12):                            # the push starts it; wait for it to show up
            if any(r.get("status") != "completed" for r in runs(gh, WU_REPO, "wu-images.yml")):
                say("  wu-images started by the push")
                return "started"
            sleep(5)
    rs = runs(gh, WU_REPO, "wu-images.yml")
    if any(r.get("status") != "completed" for r in rs):
        say("  wu-images is already running")
        return "running"
    if rs and rs[0].get("conclusion") == "success":
        say("  wu-images: the last build passed (images published)")
        return "done"
    rc, _ = gh.run(["gh", "workflow", "run", "wu-images.yml", "-R", WU_REPO, "--ref", "main"])
    if rc != 0:
        raise Fail("Could not start wu-images (Actions > wu-images > Run workflow on GitHub does the same).")
    say("  wu-images started")
    return "started"


def wait_runs(gh: GitHub, watch: list[tuple[str, str]], minutes: int, sleep=time.sleep, now=time.time) -> dict:
    """Polls until every watched workflow's newest run is completed. {(repo, wf): conclusion or 'running'}."""
    end = now() + minutes * 60
    last = {}
    while True:
        for key in watch:
            rs = runs(gh, *key)
            last[key] = (rs[0].get("conclusion") or "running") if rs and rs[0].get("status") == "completed" else \
                ("running" if rs else "not started")
        line = "  " + "   ".join(f"{wf.replace('.yml', '')}: {st}" for (_, wf), st in last.items())
        say(time.strftime("%H:%M ") + line.strip())
        if all(st not in ("running", "not started") for st in last.values()) or now() >= end:
            return last
        sleep(60)


def package_state(gh: GitHub, owner_type: str, name: str) -> str | None:
    base = f"orgs/{OWNER}" if owner_type == "Organization" else f"users/{OWNER}"
    doc = gh.api_json(f"{base}/packages/container/{name}")
    return (doc or {}).get("visibility")


def package_url(owner_type: str, name: str) -> str:
    who = "orgs" if owner_type == "Organization" else "users"
    return f"https://github.com/{who}/{OWNER}/packages/container/{name}/settings"


# ------------------------------------------------------------------------------------------------ main
def main(argv=None, gh: GitHub | None = None, sleep=time.sleep, now=time.time, opener=webbrowser.open) -> int:
    ap = argparse.ArgumentParser(description="Turn on the GitHub builds (images, host tests, launcher).")
    ap.add_argument("--repo-dir", default=str(ROOT))
    ap.add_argument("--leyline-dir", default=os.environ.get("LEYLINE_REPO_DIR")
                    or str(Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop" / "Leyline"))
    ap.add_argument("--no-wait", action="store_true", help="start the builds, don't wait for them")
    ap.add_argument("--wait-minutes", type=int, default=300)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    gh = gh or GitHub()
    wu, ly = Path(a.repo_dir), Path(a.leyline_dir)
    todo: list[str] = []
    try:
        for tool in ("gh", "git"):
            if gh.run([tool, "--version"])[0] != 0:
                raise Fail("The GitHub CLI is missing: winget install GitHub.cli   then: gh auth login" if tool == "gh"
                           else "Git is missing: https://git-scm.com/download/win")
        say("[1/5] GitHub sign-in and permissions")
        signin(gh)
        owner = gh.api_json(f"users/{OWNER}") or {}
        owner_type = owner.get("type") or "Organization"

        say("[2/5] Actions on")
        actions_on(gh, owner_type, todo)

        say("[3/5] Workflow files")
        if not (wu / ".git").exists() or not origin_ok(gh, wu, WU_REPO):
            raise Fail(f"{wu} is not the {WU_REPO} folder. Run this from the WrathUnleashed folder.")
        files = list(WU_FILES)
        rc, out = gh.run(["gh", "secret", "list", "-R", WU_REPO, "--json", "name"])
        if rc == 0 and f'"{DEPLOY_SECRET}"' in out:
            files.append(DEPLOY_FILE)
        else:
            say(f"  realm-scripts.yml waits for 'Set up automatic deploys.bat' (no {DEPLOY_SECRET} secret yet)")
        changed, _ = put_workflows(gh, wu, WU_REPO, files, "Turn on GitHub builds: image build and hosting tests")

        ly_ok = False
        if gh.run(["gh", "repo", "view", LY_REPO, "--json", "name"])[0] != 0:
            todo.append("The public Leyline repo isn't on GitHub yet: run the Leyline step once, then this again "
                        "(the launcher builds there).")
        else:
            if not (ly / ".git").exists():
                say(f"  getting the Leyline folder: {ly}")
                if gh.run(["gh", "repo", "clone", LY_REPO, str(ly)])[0] != 0:
                    raise Fail(f"Could not get {LY_REPO} into {ly}.")
            if not origin_ok(gh, ly, LY_REPO):
                raise Fail(f"{ly} does not point at {LY_REPO}. Nothing was pushed there. Ask Claude.")
            if not (ly / "launcher" / "src-tauri" / "tauri.conf.json").is_file():
                todo.append("The Leyline repo has no launcher/ yet: run the Leyline step, then this again.")
            else:
                _, ly_rev = put_workflows(gh, ly, LY_REPO, LY_FILES, "Launcher builds: installers on launcher-v* tags")
                ly_ok = True

        say("[4/5] Builds")
        images = start_images(gh, "wu-images.yml" in changed, sleep=sleep)
        tag = None
        if ly_ok:
            tag = "launcher-v" + launcher_version(wu)
            push_tag(gh, ly, tag, ly_rev)

        say("[5/5] Waiting for the builds" + (" (skipped)" if a.no_wait else
            ": the realm images take 1-3 hours. You can close this window; running it again picks up here."))
        watch = [(WU_REPO, "wu-images.yml")] + ([(LY_REPO, "leyline-launcher.yml")] if ly_ok else [])
        result = {} if a.no_wait else wait_runs(gh, watch, a.wait_minutes, sleep=sleep, now=now)
        for (repo, wf), st in result.items():
            if st not in ("success", "running", "not started"):
                todo.append(f"{wf} ended '{st}': open https://github.com/{repo}/actions and send Claude the failing step.")

        pages = []
        vis_of = {name: package_state(gh, owner_type, name) for name in PACKAGES}
        if owner_type == "Organization" and any(v != "public" for v in vis_of.values()):
            todo.append(f"Organization > Settings > Packages: under 'Package creation' tick Public, Save: "
                        f"https://github.com/organizations/{OWNER}/settings/packages")
            pages.append(f"https://github.com/organizations/{OWNER}/settings/packages")
        later = []
        for name, vis in vis_of.items():
            if vis == "public":
                say(f"  {name}: public")
            elif vis:
                todo.append(f"{name}: Danger Zone > Change visibility > Public (type the name to confirm): "
                            f"{package_url(owner_type, name)}")
                pages.append(package_url(owner_type, name))
            else:
                later.append(name)
        if later:
            todo.append("Not built yet (run this again when wu-images is green, it opens their pages then): "
                        + ", ".join(later))
        if tag:
            todo.append(f"Launcher installers (when 'leyline launcher' is green): https://github.com/{LY_REPO}/releases/tag/{tag}")
        todo.append("Desktop joins need TCP 40000-40999 open on the server. If the relay step said 'blocked':")
        todo.extend("    " + s for s in HETZNER_STEPS)
        say()
        say("== What GitHub needs you to click (it has no API for these)")
        for i, t in enumerate(todo, 1):
            say(f" {i:>2}. {t}" if not t.startswith("    ") else t)
        if pages and not a.no_browser:
            for u in pages:
                opener(u)
            say(f"  (opened {len(pages)} page(s) in your browser)")
        say()
        say("GITHUB BUILDS OK")
        return 0
    except Fail as e:
        say(f"\nProblem: {e}")
        say("GITHUB BUILDS FAILED")
        return 1
    except KeyboardInterrupt:
        say("\nStopped. Run this again any time: it picks up where it left off.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        say("STOPPED with an error:\n" + traceback.format_exc())
        sys.exit(1)
