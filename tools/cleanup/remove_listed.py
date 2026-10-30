#!/usr/bin/env python3
"""Remove the files named in tools/cleanup/REMOVE.txt (one repo-relative path per line, # comments).

The cleanup list for files a change took out of the repo (this PC can't be told to delete otherwise); the
next ship then records the deletions. Only files git tracks, inside this repo, are removed: anything
outside it, a folder, a missing file or an untracked file is skipped and named. Prints what it did.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIST = os.path.join(ROOT, "tools", "cleanup", "REMOVE.txt")


def tracked(root, rel):
    r = subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", "--", rel], capture_output=True, text=True)
    return r.returncode == 0


def remove(root=ROOT, listfile=LIST, out=print, is_tracked=tracked):
    if not os.path.isfile(listfile):
        out("Nothing to remove (no REMOVE.txt).")
        return 0
    real_root = os.path.realpath(root)
    removed = skipped = 0
    for line in open(listfile, encoding="utf-8"):
        rel = line.strip().replace("\\", "/")
        if not rel or rel.startswith("#"):
            continue
        path = os.path.realpath(os.path.join(root, rel))
        if os.path.isabs(rel) or ".." in rel.split("/") or not path.startswith(real_root + os.sep):
            out(f"  skipped (outside the repo): {rel}"); skipped += 1; continue
        if not os.path.exists(path):
            out(f"  already gone: {rel}"); continue
        if not os.path.isfile(path):
            out(f"  skipped (not a file): {rel}"); skipped += 1; continue
        if not is_tracked(root, rel):
            out(f"  skipped (not in git): {rel}"); skipped += 1; continue
        os.remove(path)
        removed += 1
        out(f"  removed {rel}")
        d = os.path.dirname(path)
        while d.startswith(real_root + os.sep) and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d); d = os.path.dirname(d)
    out(f"REMOVE OK: {removed} removed, {skipped} skipped. The next ship records the deletions.")
    return 0


if __name__ == "__main__":
    sys.exit(remove())
