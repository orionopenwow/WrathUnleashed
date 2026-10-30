#!/usr/bin/env python3
"""Fresh start as Leyline: replace the WrathUnleashed repo's history on GitHub with one commit.

    py -3 tools\\fresh-history\\fresh_history.py            dry run: says exactly what would happen
    py -3 tools\\fresh-history\\fresh_history.py --go       does it (needs CONFIRM, see below)

The owner chose this on 2026-10-30 ("Rebrand + fresh repo history"). What it does, in order, and it stops at
the first problem without having changed anything on GitHub:
  1. gh signed in as orionopenwow (never the helper account);
  2. this folder is a clean checkout of main and has nothing GitHub doesn't (so no work is lost);
  3. GitHub's main is exactly the commit named in tools/fresh-history/CONFIRM (written by Claude when the
     step is queued): if anyone pushed since, it stops;
  4. a full backup of the old history (every branch and tag) as a git bundle on the Desktop, checked with
     `git bundle verify` before going on: Leyline-history-backup-<time>.bundle — the only copy, keep it;
  5. one new commit, "Leyline", with exactly the files of today's main (no file changes);
  6. GitHub: main is replaced with it (force-with-lease on the expected commit), then every other branch and
     every tag on GitHub (they would keep the old history reachable) is deleted — all are in the backup;
  7. this folder: main points at the new commit (files untouched), the old commits stay only in the bundle.
Open pull requests on GitHub keep their old commits until closed; the report lists them.
Standard library only; tokens are never printed.
"""
from __future__ import annotations

import argparse
import os
import sys
import subprocess
import time

OWNER = "orionopenwow"
REPO = f"{OWNER}/WrathUnleashed"
NOT_OWNER = ("chumpton",)
MESSAGE = "Leyline"
AUTOPILOT_FILES = {"UPDATES-DONE.txt", "UPDATES-PENDING.txt", "control/autopilot.json", "control/claude-status.json",
                   "control/last-run.json"}
AUTHOR = ("Orion", "orionopenwow@users.noreply.github.com")


class Stop(Exception):
    pass


def run(args, cwd=None, env=None):
    try:
        p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError:
        return 127, f"{args[0]}: not found"
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def fresh(root, go=False, confirm_file=None, backup_dir=None, runner=run, out=print, now=time.strftime):
    git = lambda *a, env=None: runner(["git", "-C", root] + list(a), env=env)
    say = out

    rc, who = runner(["gh", "api", "user", "--jq", ".login"])
    if rc != 0:
        raise Stop("the GitHub CLI is not signed in (gh auth login)")
    if who.strip().lower() in NOT_OWNER or who.strip() != OWNER:
        raise Stop(f"gh is signed in as {who.strip()}: it must be {OWNER} (gh auth switch)")
    say(f"[1/7] signed in as {who.strip()}")

    rc, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or branch != "main":
        raise Stop(f"this folder is on '{branch}', not main")
    rc, dirty = git("status", "--porcelain", "--untracked-files=no")
    # Autopilot rewrites its own bookkeeping after every step; those changes are not work to lose.
    paths = [ln.split(None, 1)[1].strip().strip('"') for ln in dirty.splitlines() if len(ln.split(None, 1)) == 2]
    own = [p for p in paths if p not in AUTOPILOT_FILES]
    if own:
        raise Stop("this folder has changes that aren't saved to GitHub yet: run Ship first (" + ", ".join(own[:5]) + ")")
    rc, txt = git("fetch", "-q", "--prune", "--tags", "origin")
    if rc != 0:
        raise Stop("git fetch failed: " + txt)
    rc, head = git("rev-parse", "HEAD")
    rc2, remote = git("rev-parse", "refs/remotes/origin/main")
    if rc != 0 or rc2 != 0:
        raise Stop("could not read main here or on GitHub")
    if head != remote:
        raise Stop(f"this folder's main ({head[:7]}) and GitHub's ({remote[:7]}) differ: run Ship first")
    say(f"[2/7] this folder matches GitHub's main ({head[:7]})")

    expected = ""
    if confirm_file and os.path.isfile(confirm_file):
        expected = open(confirm_file, encoding="utf-8").read().strip()
    if go and not expected:
        raise Stop(f"{confirm_file} is missing: nothing done (Claude writes it when queuing this step)")
    if go and not remote.startswith(expected):
        raise Stop(f"GitHub's main is {remote[:7]}, CONFIRM expects {expected[:7]}: someone pushed since; "
                   "nothing done")
    say(f"[3/7] GitHub's main is the expected commit" if go else "[3/7] (dry run: CONFIRM not checked)")

    rc, refs = runner(["git", "-C", root, "ls-remote", "--heads", "--tags", "origin"])
    if rc != 0:
        raise Stop("could not list GitHub's branches and tags: " + refs)
    other_heads, tags = [], []
    for line in refs.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/heads/") and ref != "refs/heads/main":
            other_heads.append(ref[len("refs/heads/"):])
        elif ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref[len("refs/tags/"):])
    rc, prs = runner(["gh", "pr", "list", "-R", REPO, "--state", "open", "--json", "number,title",
                      "--jq", '.[] | "#\\(.number) \\(.title)"'])
    open_prs = [p for p in (prs.splitlines() if rc == 0 else []) if p.strip()]

    stamp = now("%Y%m%d-%H%M%S")
    bdir = backup_dir or os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Desktop")
    bundle = os.path.join(bdir, f"Leyline-history-backup-{stamp}.bundle")
    say(f"[4/7] backup of the whole old history -> {bundle}")
    if not go:
        say(f"      would delete on GitHub: {len(other_heads)} other branch(es) {other_heads[:8]} and "
            f"{len(tags)} tag(s) {tags[:8]}")
        if open_prs:
            say(f"      open pull requests keep old commits until closed: {', '.join(open_prs[:5])}")
        say(f"      would replace GitHub's main ({remote[:7]}) with one commit '{MESSAGE}' (same files)")
        say("DRY RUN OK: nothing changed")
        return 0
    os.makedirs(bdir, exist_ok=True)
    rc, txt = git("bundle", "create", bundle, "--all")
    if rc != 0:
        raise Stop("the backup failed: " + txt)
    rc, txt = git("bundle", "verify", bundle)
    if rc != 0:
        raise Stop("the backup did not verify: " + txt)
    size = os.path.getsize(bundle)
    say(f"      backup written and verified ({size // (1024 * 1024)} MB). Keep it: it is the only copy.")

    env = dict(os.environ, GIT_AUTHOR_NAME=AUTHOR[0], GIT_AUTHOR_EMAIL=AUTHOR[1],
               GIT_COMMITTER_NAME=AUTHOR[0], GIT_COMMITTER_EMAIL=AUTHOR[1])
    rc, tree = git("rev-parse", "HEAD^{tree}")
    rc2, new = git("commit-tree", tree, "-m", MESSAGE, env=env)
    if rc != 0 or rc2 != 0 or not new:
        raise Stop("could not make the new commit: " + new)
    rc, t2 = git("rev-parse", f"{new}^{{tree}}")
    if t2 != tree:
        raise Stop("the new commit's files differ from main's: nothing pushed")
    say(f"[5/7] new commit {new[:7]} '{MESSAGE}' with exactly main's files")

    rc, txt = git("push", f"--force-with-lease=refs/heads/main:{remote}", "origin", f"{new}:refs/heads/main")
    if rc != 0:
        raise Stop("GitHub refused the new main (nothing else changed): " + txt)
    deleted, failed = 0, []
    for name in other_heads:
        rc, txt = git("push", "origin", "--delete", f"refs/heads/{name}")
        (failed.append(name) if rc != 0 else None)
        deleted += rc == 0
    for name in tags:
        rc, txt = git("push", "origin", "--delete", f"refs/tags/{name}")
        (failed.append(name) if rc != 0 else None)
        deleted += rc == 0
    say(f"[6/7] GitHub's main is now {new[:7]}; deleted {deleted} old branch(es)/tag(s)"
        + (f"; could not delete {failed}" if failed else ""))
    if open_prs:
        say(f"      open pull requests still hold old commits until closed: {', '.join(open_prs)}")

    rc, txt = git("reset", "-q", "--soft", new)
    if rc != 0:
        raise Stop("GitHub is done, but this folder's main could not move: run  git reset --soft " + new)
    for name in tags:
        git("tag", "-d", name)
    git("fetch", "-q", "--prune", "--prune-tags", "origin")
    say(f"[7/7] this folder's main is {new[:7]} (files untouched); the old history is only in the backup")
    say("FRESH HISTORY OK")
    return 0


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Replace the repo's history with one 'Leyline' commit.")
    ap.add_argument("--go", action="store_true", help="do it (default: dry run)")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(here)))
    ap.add_argument("--backup-dir")
    a = ap.parse_args(argv)
    try:
        return fresh(a.root, go=a.go, confirm_file=os.path.join(here, "CONFIRM"), backup_dir=a.backup_dir)
    except Stop as e:
        print("STOPPED: " + str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
