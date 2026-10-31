#!/usr/bin/env python3
"""Clean old releases and container packages off GitHub (owner 2026-10-30 12:27: "scrub releases and packages").

    py -3 tools\\github-cleanup\\gh_cleanup.py            dry run: what would go (nothing changes)
    py -3 tools\\github-cleanup\\gh_cleanup.py --go       does it, only if PLAN.json matches what GitHub shows now

The owner's choices (2026-10-30): on orionopenwow/Leyline-Launcher keep the newest release and delete every other
release with its tag (installed launchers update from the newest one, and the site's Download points there);
delete the container packages listed in PLAN.json ("Delete all 4"), except the 1.12 images, which are never deleted
(PROTECTED_PACKAGE_WORDS; owner 2026-10-30 20:38). PLAN.json, written by Claude after the dry
run, names the release that is kept, the tags that go and the packages that go: --go refuses when GitHub shows
anything else (a new release since, a different newest one), so nothing unexpected is ever deleted. gh must be
signed in as orionopenwow (never Chumpton). Deleting packages needs the delete:packages scope; when gh lacks it
this says how to add it (gh auth refresh -s read:packages,delete:packages) and deletes nothing else.
Standard library only; tokens are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

OWNER = "orionopenwow"
# Never deleted, whatever PLAN.json says (owner 2026-10-30 20:38: "do NOT run the GitHub package cleanup on the 1.12
# images"): the 1.12 realm's images (openvanilla-realm, openvanilla-mangos, their old openwow-* names and anything else
# of the 1.12 stack) run Vanilla Remastered (docs/VANILLA-REMASTERED.md) and are what a community host takes it over
# from. Matched on the package name, case-insensitive.
PROTECTED_PACKAGE_WORDS = ("openvanilla", "openwow", "wenilla", "mangos", "realmd", "vanilla", "classic", "112")


def protected_package(name: str) -> bool:
    n = (name or "").lower()
    return n.startswith("leyline") or any(w in n for w in PROTECTED_PACKAGE_WORDS)
REPO = f"{OWNER}/Leyline-Launcher"
HERE = os.path.dirname(os.path.abspath(__file__))


class Stop(Exception):
    pass


def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, f"{args[0]}: not found"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def pages(out: str) -> list:
    items, dec, i, out = [], json.JSONDecoder(), 0, out.strip()
    while i < len(out):                          # --paginate prints one JSON array per page
        arr, j = dec.raw_decode(out, i)
        items.extend(arr if isinstance(arr, list) else [arr])
        i = j
        while i < len(out) and out[i] in " \r\n\t":
            i += 1
    return items


class GitHub:
    def __init__(self, runner=run):
        self.r = runner

    def login(self) -> str:
        rc, out = self.r(["gh", "api", "user", "--jq", ".login"])
        if rc != 0:
            raise Stop("GitHub CLI not signed in: run  gh auth login")
        return out.strip()

    def releases(self) -> list[dict]:
        rc, out = self.r(["gh", "api", "--paginate", f"repos/{REPO}/releases?per_page=100"])
        if rc != 0:
            raise Stop(f"could not list the releases of {REPO}: {out.strip()[:200]}")
        return pages(out)

    def latest(self) -> str:
        rc, out = self.r(["gh", "api", f"repos/{REPO}/releases/latest", "--jq", ".tag_name"])
        return out.strip() if rc == 0 else ""

    def delete_release(self, rid: int) -> tuple[int, str]:
        return self.r(["gh", "api", "-X", "DELETE", f"repos/{REPO}/releases/{rid}"])

    def delete_tag(self, tag: str) -> tuple[int, str]:
        return self.r(["gh", "api", "-X", "DELETE", f"repos/{REPO}/git/refs/tags/{tag}"])

    def packages(self) -> tuple[str, list[str]]:
        """('users'|'orgs', container package names) owned by OWNER."""
        for kind in ("users", "orgs"):
            rc, out = self.r(["gh", "api", "--paginate", f"{kind}/{OWNER}/packages?package_type=container&per_page=100"])
            if rc == 0:
                return kind, sorted(p.get("name", "") for p in pages(out) if p.get("name"))
            if "read:packages" in out or "delete:packages" in out or "403" in out:
                raise Stop("gh can't see packages yet: run  gh auth refresh -s read:packages,delete:packages  then run this again")
        raise Stop(f"could not list the packages of {OWNER}")

    def delete_package(self, kind: str, name: str) -> tuple[int, str]:
        return self.r(["gh", "api", "-X", "DELETE", f"{kind}/{OWNER}/packages/container/{name}"])


def plan_now(gh: GitHub, keep_also=()) -> dict:
    rels = gh.releases()
    keep = gh.latest() or (rels[0].get("tag_name", "") if rels else "")
    go = [r for r in rels if r.get("tag_name") != keep and r.get("tag_name") not in keep_also]
    return {"keep_release": keep, "releases": [(r["id"], r.get("tag_name", ""), r.get("name") or "") for r in go]}


def main(argv=None, gh: GitHub | None = None, out=print, plan_file: str | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args(argv)
    gh = gh or GitHub()
    plan_file = plan_file or os.path.join(HERE, "PLAN.json")
    try:
        who = gh.login()
        if who.lower() != OWNER:
            raise Stop(f"gh is signed in as {who}, not {OWNER}: nothing done")
        out(f"[1/4] signed in as {who}")
        plan = json.load(open(plan_file, encoding="utf-8")) if os.path.isfile(plan_file) else {}
        keep_also = tuple(plan.get("keep_also", ("engine",)))   # the "engine" pre-release feeds release builds
        now = plan_now(gh, keep_also)
        out(f"[2/4] {REPO}: keep the newest release '{now['keep_release']}' (and {', '.join(keep_also)}); {len(now['releases'])} other release(s) and their tags would go:")
        for _, tag, name in now["releases"]:
            out(f"      - {tag}  {name}")
        try:
            kind, pkgs = gh.packages()
            out(f"[3/4] container packages of {OWNER}: {', '.join(pkgs) or '(none)'}")
            kept = [p for p in pkgs if protected_package(p)]
            if kept:
                out(f"      always kept (the 1.12 images, Leyline's own): {', '.join(kept)}")
        except Stop as e:
            kind, pkgs = "", None
            out(f"[3/4] {e}")
        if not a.go:
            out("DRY RUN OK: nothing changed")
            return 0
        if not os.path.isfile(plan_file):
            raise Stop(f"{plan_file} is missing: nothing done (Claude writes it after the dry run)")
        want_tags = sorted(plan.get("delete_release_tags", []))
        if plan.get("keep_release") != now["keep_release"] or not {t for _, t, _ in now["releases"]} <= set(want_tags):
            raise Stop("GitHub's releases changed since the plan was written: nothing done (run the dry run again)")
        asked = list(plan.get("delete_packages", []))
        want_pkgs = [p for p in asked if not protected_package(p)]
        out("[4/4] deleting")
        for p in asked:
            if protected_package(p):
                out(f"      package {p}: KEPT (protected: the 1.12 images stay, owner 2026-10-30 20:38)")
        bad = 0
        for rid, tag, _ in now["releases"]:
            rc, msg = gh.delete_release(rid)
            rc2, msg2 = gh.delete_tag(tag) if rc == 0 else (1, "")
            ok = rc == 0 and (rc2 == 0 or "Reference does not exist" in msg2 or "422" in msg2)
            bad += not ok
            out(f"      release {tag}: {'deleted (and its tag)' if ok else 'FAILED ' + (msg or msg2).strip()[:120]}")
        if want_pkgs:
            if pkgs is None:
                bad += 1
                out("      packages: not deleted. gh needs the packages scope: run  gh auth refresh -s read:packages,delete:packages")
            for p in ([] if pkgs is None else want_pkgs):
                if p not in pkgs:
                    out(f"      package {p}: already gone")
                    continue
                rc, msg = gh.delete_package(kind, p)
                bad += rc != 0
                out(f"      package {p}: {'deleted' if rc == 0 else 'FAILED ' + msg.strip()[:160]}")
        if bad:
            out(f"CLEANUP FINISHED WITH {bad} PROBLEM(S): see above")
            return 1
        out("CLEANUP OK")
        return 0
    except Stop as e:
        out(f"STOPPED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
