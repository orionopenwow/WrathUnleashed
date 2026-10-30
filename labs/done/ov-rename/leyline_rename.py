#!/usr/bin/env python3
"""Rename the GitHub repo orionopenwow/OpenVanilla to orionopenwow/Leyline-Launcher, using this PC's own
GitHub CLI sign-in (owner decision 2026-10-29: "rename repo to Leyline Launcher").

    py -3 tools\\rename\\leyline_rename.py                 rename, set description + homepage, fix origin
    py -3 tools\\rename\\leyline_rename.py --dry-run       only say what it would do
    py -3 leyline_rename.py --find-clone --wu C:\\...\\WrathUnleashed
                                                         (the Autopilot copy) find the PC's clone first
    py -3 leyline_rename.py --find-clone --land FILE.bundle [--branch NAME]
                                                         fast-forward main to a branch from a git bundle, push main

Safe to run again: every step looks first and skips what is already done.
  1. GitHub sign-in: gh must be signed in as orionopenwow. It refuses the account "Chumpton", always.
  2. The repo: renamed with `gh repo rename`, unless GitHub already has it under the new name.
     GitHub redirects the old address (web, git, API and release downloads) to the new one.
  3. Description and homepage: set with `gh repo edit` when they differ.
  4. The PC's clone: its `origin` remote is pointed at the new address (same scheme: https or ssh).
Never prints a token: it never asks gh for one, and any URL it shows has its user/password part removed.

Standard library only; Python 3.8+.
"""
import argparse
import json
import os
import time
import re
import subprocess
import sys

OWNER = "orionopenwow"
OLD_NAME = "OpenVanilla"
NEW_NAME = "Leyline-Launcher"
REFUSED_ACCOUNTS = ("chumpton",)
DESCRIPTION = ("Leyline Launcher (formerly Open Vanilla): the 1.12.1 launcher, website and realm tools. "
               "Bring your own game files.")
HOMEPAGE = "https://play.openvanilla.app/wrath/leyline"

TOKEN_RE = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})")
GH_URL_RE = re.compile(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.I)


class RenameError(Exception):
    pass


def redact(text):
    """Text safe to print: no tokens, no user:password@ in URLs."""
    text = TOKEN_RE.sub("***", str(text))
    return re.sub(r"(https?://)[^/@\s]+@", r"\1", text)


def run(cmd, cwd=None):
    """(exit code, stdout+stderr text). A missing program is exit code 127."""
    try:
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out"
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def repo_slug(url):
    """(owner, name) of a github.com remote URL, else None."""
    m = GH_URL_RE.search((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def new_remote_url(url, owner=OWNER, new=NEW_NAME):
    """The same remote, pointed at the new repo: keeps https/ssh, any user part and a trailing .git."""
    url = (url or "").strip()
    m = GH_URL_RE.search(url)
    if not m:
        return None
    git = ".git" if url.endswith(".git") else ""
    return url[:m.start()] + "github.com" + url[m.start() + 10] + f"{owner}/{new}{git}"


def is_ours(url, owner=OWNER, names=(OLD_NAME, NEW_NAME)):
    s = repo_slug(url)
    return bool(s) and s[0].lower() == owner.lower() and s[1].lower() in {n.lower() for n in names}


def find_clone(candidates, runner=run):
    """The first folder that is a git clone of the old or new repo (by its origin), else None."""
    for c in candidates:
        if not c or not os.path.isdir(os.path.join(c, ".git")):
            continue
        rc, url = runner(["git", "-C", c, "remote", "get-url", "origin"])
        if rc == 0 and is_ours(url):
            return os.path.abspath(c)
    return None


def clone_candidates(wu=None, env=None):
    """Where the PC's clone usually is: OPENVANILLA_DIR, then the workspace's .repos\\leyline-launcher (since "Move to
    Leyline.bat"), then beside the workspace, then the Desktop, Documents\\GitHub, source\\repos and the user folder
    (both spellings)."""
    env = os.environ if env is None else env
    out = []
    if env.get("OPENVANILLA_DIR"):
        out.append(env["OPENVANILLA_DIR"])
    if wu:
        out.append(os.path.join(os.path.abspath(wu), ".repos", "leyline-launcher"))
    home = env.get("USERPROFILE") or env.get("HOME") or os.path.expanduser("~")
    bases = []
    if wu:
        bases.append(os.path.dirname(os.path.abspath(wu)))
    bases += [os.path.join(home, "Desktop"), os.path.join(home, "Documents", "GitHub"),
              os.path.join(home, "source", "repos"), home]
    for b in bases:
        for n in ("OpenVanilla", "openvanilla", "Open Vanilla", NEW_NAME):
            out.append(os.path.join(b, n))
    return list(dict.fromkeys(out))


class Renamer:
    def __init__(self, clone=None, owner=OWNER, old=OLD_NAME, new=NEW_NAME, account=OWNER,
                 description=DESCRIPTION, homepage=HOMEPAGE, dry_run=False, runner=run, out=print):
        self.clone, self.owner, self.old, self.new = clone, owner, old, new
        self.account, self.description, self.homepage = account, description, homepage
        self.dry, self.runner, self._out = dry_run, runner, out

    def say(self, msg):
        self._out(redact(msg))

    def gh(self, *args):
        return self.runner(["gh"] + list(args))

    def gh_json(self, *args):
        rc, txt = self.gh(*args)
        if rc != 0:
            return None
        try:
            return json.loads(txt)
        except ValueError:
            return None

    # 1
    def check_account(self):
        rc, login = self.gh("api", "user", "--jq", ".login")
        login = (login or "").strip().splitlines()[-1].strip() if rc == 0 and login else ""
        if rc == 127:
            raise RenameError("The GitHub CLI (gh) is not installed: winget install GitHub.cli, then gh auth login")
        if not login:
            raise RenameError(f"The GitHub CLI is not signed in. Run once: gh auth login  (as {self.account})")
        if login.lower() in REFUSED_ACCOUNTS:
            raise RenameError(f"The GitHub CLI is signed in as {login}. That account is never used for this. "
                              f"Switch with: gh auth switch  (to {self.account})")
        if self.account and login.lower() != self.account.lower():
            raise RenameError(f"The GitHub CLI is signed in as {login}, not {self.account}. "
                              f"Switch with: gh auth switch")
        self.say(f"  signed in as {login}")
        return login

    def repo(self, name):
        return self.gh_json("api", f"repos/{self.owner}/{name}", "--jq",
                            "{id: .id, full_name: .full_name, description: .description, homepage: .homepage}")

    # 2
    def rename(self):
        new_full = f"{self.owner}/{self.new}"
        old = self.repo(self.old)            # GitHub answers the old name with the renamed repo
        new = self.repo(self.new)
        if old is None and new is None:
            raise RenameError(f"Neither {self.owner}/{self.old} nor {new_full} is on GitHub (or gh can't see it).")
        if new is not None and (new.get("full_name") or "").lower() == new_full.lower():
            if old is not None and old.get("id") != new.get("id"):
                raise RenameError(f"{new_full} already exists and is a different repo from {self.owner}/{self.old}. "
                                  "Nothing was renamed: rename or delete that one first.")
            self.say(f"  already renamed: {new.get('full_name')}  (skipped)")
            return new, False
        if self.dry:
            self.say(f"  would rename {old.get('full_name')} -> {new_full}")
            return dict(old, full_name=new_full), True
        rc, txt = self.gh("repo", "rename", self.new, "--repo", old.get("full_name"), "--yes")
        if rc != 0:
            raise RenameError("gh repo rename failed: " + txt)
        got = self.repo(self.new)
        if not got or (got.get("full_name") or "").lower() != new_full.lower():
            raise RenameError(f"GitHub did not report {new_full} after the rename; check github.com/{self.owner}")
        self.say(f"  renamed {old.get('full_name')} -> {got.get('full_name')}")
        return got, True

    # 3
    def edit(self, info):
        full = info.get("full_name") or f"{self.owner}/{self.new}"
        args = []
        if (info.get("description") or "") != self.description:
            args += ["--description", self.description]
        if (info.get("homepage") or "") != self.homepage:
            args += ["--homepage", self.homepage]
        if not args:
            self.say("  description and homepage already set  (skipped)")
            return False
        if self.dry:
            self.say(f"  would set description and homepage ({self.homepage})")
            return True
        rc, txt = self.gh("repo", "edit", full, *args)
        if rc != 0:
            raise RenameError("gh repo edit failed: " + txt)
        self.say(f"  description set; homepage {self.homepage}")
        return True

    # 4
    def fix_origin(self):
        if not self.clone:
            self.say("  no clone on this PC was found  (skipped; set OPENVANILLA_DIR to its folder)")
            return False
        rc, url = self.runner(["git", "-C", self.clone, "remote", "get-url", "origin"])
        if rc != 0:
            raise RenameError(f"{self.clone} has no origin remote")
        s = repo_slug(url)
        if s and s[0].lower() == self.owner.lower() and s[1] == self.new:
            self.say(f"  origin already {redact(url)}  (skipped)")
            return False
        if not is_ours(url, self.owner, (self.old, self.new)):
            raise RenameError(f"origin of {self.clone} is {redact(url)}, not {self.owner}/{self.old}: left alone")
        new = new_remote_url(url, self.owner, self.new)
        if self.dry:
            self.say(f"  would set origin to {redact(new)}")
            return True
        rc, txt = self.runner(["git", "-C", self.clone, "remote", "set-url", "origin", new])
        if rc != 0:
            raise RenameError("git remote set-url failed: " + txt)
        self.say(f"  origin: {redact(url)} -> {redact(new)}")
        return True

    def main(self):
        self.say(f"Rename {self.owner}/{self.old} -> {self.owner}/{self.new}" + ("  (dry run: nothing changes)" if self.dry else ""))
        self.say("[1/4] GitHub sign-in")
        self.check_account()
        self.say("[2/4] The repo")
        info, _ = self.rename()
        self.say("[3/4] Description and homepage")
        self.edit(info)
        self.say(f"[4/4] This PC's clone: {self.clone or '(none found)'}")
        self.fix_origin()
        self.say(f"Done. https://github.com/{self.owner}/{self.new}  (the old address redirects here)")
        return 0


def adopt_scrubbed(git, say, dry_run=False):
    """After a history rewrite on GitHub (the 2026-10-29 scrub), a PC clone can still hold the old history: same
    files, different commits. Then main (and stable) can't fast-forward, and pushing them would bring the old
    history back. When a local branch has exactly the same files as GitHub's, point it at GitHub's commit
    (files untouched: same tree) and keep the old commit under refs/backup/ (never pushed). Anything else (real
    local work) is left alone and the landing stops as before."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in ("main", "stable"):
        rc, local = git("rev-parse", "-q", "--verify", f"refs/heads/{name}")
        rc2, remote = git("rev-parse", "-q", "--verify", f"refs/remotes/origin/{name}")
        if rc != 0 or rc2 != 0:
            continue
        local, remote = local.strip(), remote.strip()
        if local == remote:
            continue
        rc, _ = git("merge-base", "--is-ancestor", local, remote)
        if rc == 0:
            continue                      # simply behind GitHub: nothing old to hide, fast-forward later works
        rc, lt = git("rev-parse", f"{local}^{{tree}}")
        rc2, rt = git("rev-parse", f"{remote}^{{tree}}")
        if rc != 0 or rc2 != 0 or lt.strip() != rt.strip():
            continue                      # different files: real local work, not ours to move
        say(f"  {name}: this PC still has the history from before the scrub (same files as GitHub)")
        if dry_run:
            say(f"  would point {name} at GitHub's {remote[:7]} and keep {local[:7]} as refs/backup/{name}-{stamp}")
            continue
        rc, txt = git("update-ref", f"refs/backup/{name}-{stamp}", local)
        if rc != 0:
            raise RenameError("could not keep a backup of the old " + name + ": " + txt)
        rc, cur = git("rev-parse", "--abbrev-ref", "HEAD")
        if cur.strip() == name:
            rc, txt = git("reset", "-q", "--soft", remote)       # same tree: index and files stay as they are
        else:
            rc, txt = git("update-ref", f"refs/heads/{name}", remote, local)
        if rc != 0:
            raise RenameError(f"could not point {name} at GitHub's history: " + txt)
        say(f"  {name} now follows GitHub ({remote[:7]}); the old commit is kept as refs/backup/{name}-{stamp}")
    adopt_tags(git, say, stamp, dry_run)


def adopt_tags(git, say, stamp, dry_run=False):
    """Tags from the old history would bring it back with a `git push --tags`. A local tag that GitHub has with a
    different target is pointed at GitHub's; a local-only tag whose commit GitHub's history doesn't contain is
    moved under refs/backup/tags/ (kept, never pushed). Tags GitHub has as they are, and new tags made on
    GitHub's history, are left alone."""
    rc, out = git("ls-remote", "--tags", "origin")
    if rc != 0:
        return
    remote = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/tags/") and not parts[1].endswith("^{}"):
            remote[parts[1][len("refs/tags/"):]] = parts[0]
    rc, out = git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/tags/")
    if rc != 0:
        return
    moved = 0
    for line in out.splitlines():
        try:
            tag, obj = line.split()
        except ValueError:
            continue
        if remote.get(tag) == obj:
            continue
        if tag not in remote:
            on_github = False
            for base in ("refs/remotes/origin/main", "refs/remotes/origin/stable"):
                rc, _ = git("merge-base", "--is-ancestor", f"{obj}^{{commit}}", base)
                if rc == 0:
                    on_github = True
                    break
            if on_github:
                continue
        moved += 1
        if dry_run:
            continue
        git("update-ref", f"refs/backup/tags-{stamp}/{tag}", obj)
        if tag in remote:
            git("fetch", "-q", "origin", f"+refs/tags/{tag}:refs/tags/{tag}")
        else:
            git("tag", "-d", tag)
    if moved:
        say(f"  {moved} tag(s) from the old history {'would be' if dry_run else 'were'} set aside "
            f"(kept under refs/backup/tags-{stamp}/, never pushed)")


def land(clone, bundle, branch, runner=run, out=print, account=OWNER, dry_run=False):
    """Bring a branch from a git bundle (made where GitHub can't be pushed to) onto the clone's main and push
    main: fast-forward only, a clean checkout of main only, gh signed in as the owner. Makes no commits and
    never force-pushes. Run after the rename (origin then points at the new address)."""
    say = lambda m: out(redact(m))
    git = lambda *a: runner(["git", "-C", clone] + list(a))
    Renamer(runner=runner, out=out, account=account).check_account()
    if not clone or not os.path.isdir(os.path.join(clone, ".git")):
        raise RenameError("no clone to land the branch in (pass --clone, or set OPENVANILLA_DIR)")
    if not os.path.isfile(bundle):
        raise RenameError(f"the bundle {bundle} is not on this PC")
    rc, head = git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or head.strip() != "main":
        raise RenameError(f"{clone} is on '{head.strip()}', not main: switch to main first (git switch main)")
    rc, dirty = git("status", "--porcelain", "--untracked-files=no")
    if rc != 0 or dirty.strip():
        raise RenameError(f"{clone} has changes that aren't committed: commit or stash them first")
    rc, txt = git("fetch", "-q", "origin", "main", "stable")
    if rc != 0:
        rc, txt = git("fetch", "-q", "origin", "main")
    if rc != 0:
        raise RenameError("git fetch origin failed: " + txt)
    adopt_scrubbed(git, say, dry_run)
    ref = f"refs/remotes/bundle/{branch}"
    rc, txt = git("fetch", "-q", os.path.abspath(bundle), f"+{branch}:{ref}")
    if rc != 0:
        raise RenameError("could not read the branch from the bundle: " + txt)
    for base in ("origin/main", "HEAD"):
        rc, _ = git("merge-base", "--is-ancestor", base, ref)
        if rc != 0:
            raise RenameError(f"{branch} does not build on {base} (someone pushed since it was made): "
                              "nothing landed; ask Claude for a fresh bundle")
    rc, n = git("rev-list", "--count", f"origin/main..{ref}")
    say(f"  {branch}: {n.strip()} new commit(s) on top of origin/main")
    if n.strip() == "0":
        say("  already on GitHub  (skipped)")
        return 0
    if dry_run:
        say("  would fast-forward main and push it")
        return 0
    rc, txt = git("merge", "-q", "--ff-only", ref)
    if rc != 0:
        raise RenameError("fast-forward failed: " + txt)
    rc, txt = git("push", "origin", "main")
    if rc != 0:
        raise RenameError("git push failed: " + txt)
    say("  main pushed. Next: the release (dev\\Release.bat 1.57.0 in this folder).")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--clone", help="the PC's clone (default: the repo this file is in)")
    ap.add_argument("--find-clone", action="store_true", help="look for the clone in the usual places")
    ap.add_argument("--wu", help="the WrathUnleashed folder (with --find-clone: also look beside it)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--account", default=OWNER, help="the gh account to require (never Chumpton)")
    ap.add_argument("--land", metavar="BUNDLE", help="instead of renaming: fast-forward main to --branch from this "
                    "git bundle and push main")
    ap.add_argument("--branch", default="feat-leyline-launcher-rename")
    a = ap.parse_args(argv)
    if a.clone:
        clone = os.path.abspath(a.clone) if os.path.isdir(os.path.join(a.clone, ".git")) else None
    elif a.find_clone:
        clone = find_clone(clone_candidates(a.wu))
    else:
        root = os.path.dirname(os.path.dirname(here))
        clone = root if os.path.isdir(os.path.join(root, ".git")) else None
    try:
        if a.land:
            print(f"Land {a.branch} on main and push it: {clone or '(no clone found)'}")
            return land(clone, a.land, a.branch, account=a.account, dry_run=a.dry_run)
        return Renamer(clone=clone, account=a.account, dry_run=a.dry_run).main()
    except RenameError as e:
        print("  STOPPED: " + redact(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
