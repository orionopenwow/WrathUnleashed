#!/usr/bin/env python3
"""Delete the deployment history (the "Deployments" list on a repo's GitHub page).

    py -3 tools\\github-deployments\\clean_deployments.py                 list only (counts per repo)
    py -3 tools\\github-deployments\\clean_deployments.py --delete [--keep-latest] [--repo owner/name ...]

Run by the owner himself, with his own gh sign-in (never by Autopilot): deleting is permanent, so --delete
asks him to type YES first. A deployment record is only history: deleting it never takes a site down or
touches a release, a package or a workflow run. GitHub only deletes inactive deployments, so each one is
marked inactive first, then deleted. Standard library only; tokens are never printed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

OWNER = "orionopenwow"
REPOS = (f"{OWNER}/Leyline-Launcher", f"{OWNER}/WrathUnleashed", f"{OWNER}/Leyline")
NOT_OWNER = ("chumpton",)


class Stop(Exception):
    pass


def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, f"{args[0]}: not found"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class GitHub:
    def __init__(self, runner=run):
        self.runner = runner

    def login(self):
        rc, out = self.runner(["gh", "api", "user", "--jq", ".login"])
        if rc != 0:
            raise Stop("GitHub CLI not signed in: run  gh auth login")
        return out.strip()

    def deployments(self, repo):
        rc, out = self.runner(["gh", "api", "--paginate", f"repos/{repo}/deployments?per_page=100"])
        if rc != 0:
            raise Stop(f"could not list the deployments of {repo}: {out.strip()[:200]}")
        items, dec, i = [], json.JSONDecoder(), 0
        out = out.strip()
        while i < len(out):                      # --paginate prints one JSON array per page
            arr, j = dec.raw_decode(out, i)
            items.extend(arr)
            i = j
            while i < len(out) and out[i] in " \r\n\t":
                i += 1
        return items

    def deactivate(self, repo, dep_id):
        return self.runner(["gh", "api", "-X", "POST", f"repos/{repo}/deployments/{dep_id}/statuses",
                            "-f", "state=inactive"])

    def delete(self, repo, dep_id):
        return self.runner(["gh", "api", "-X", "DELETE", f"repos/{repo}/deployments/{dep_id}"])


def to_delete(deps, keep_latest=False):
    """The deployments to delete: all of them, or all but the newest per environment."""
    deps = sorted(deps, key=lambda d: d.get("created_at") or "", reverse=True)
    if not keep_latest:
        return deps
    seen, out = set(), []
    for d in deps:
        env = d.get("environment") or ""
        if env in seen:
            out.append(d)
        else:
            seen.add(env)
    return out


def main(argv=None, gh=None, ask=input, out=print):
    ap = argparse.ArgumentParser(description="List, then delete, a repo's deployment history.")
    ap.add_argument("--repo", action="append", help="owner/name (repeatable); default: the three Leyline repos")
    ap.add_argument("--delete", action="store_true", help="delete (asks you to type YES first)")
    ap.add_argument("--yes", action="store_true", help="already confirmed (the .bat asked you to type YES)")
    ap.add_argument("--keep-latest", action="store_true", help="keep the newest deployment of each environment")
    a = ap.parse_args(argv)
    gh = gh or GitHub()
    repos = a.repo or list(REPOS)
    try:
        who = gh.login()
        if who.lower() in NOT_OWNER:
            raise Stop(f"gh is signed in as {who}: switch to {OWNER} first (gh auth switch)")
        out(f"Signed in as {who}")
        plan = {}
        for repo in repos:
            deps = gh.deployments(repo)
            doomed = to_delete(deps, a.keep_latest)
            envs = sorted({d.get("environment") or "?" for d in deps})
            out(f"  {repo}: {len(deps)} deployment(s) ({', '.join(envs) or 'none'}); "
                f"{len(doomed)} would be deleted")
            plan[repo] = doomed
        total = sum(len(v) for v in plan.values())
        if not a.delete:
            out("Nothing deleted (list only). To delete: run 'Clean deployments.bat delete'.")
            return 0
        if total == 0:
            out("Nothing to delete.")
            return 0
        out(f"\nThis permanently deletes {total} deployment record(s). Sites, releases and packages stay.")
        if not a.yes and ask("Type YES to delete them: ").strip() != "YES":
            out("Not confirmed: nothing deleted.")
            return 1
        done = failed = 0
        for repo, doomed in plan.items():
            for d in doomed:
                gh.deactivate(repo, d["id"])            # GitHub refuses to delete an active deployment
                rc, txt = gh.delete(repo, d["id"])
                if rc == 0:
                    done += 1
                else:
                    failed += 1
                    out(f"  {repo} #{d['id']}: not deleted ({txt.strip()[:120]})")
            out(f"  {repo}: done")
        out(f"Deleted {done} deployment record(s)" + (f"; {failed} could not be deleted" if failed else "") + ".")
        return 0 if not failed else 2
    except Stop as e:
        out("STOPPED: " + str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
