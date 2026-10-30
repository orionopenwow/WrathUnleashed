#!/usr/bin/env python3
"""Move to Leyline: one workspace folder instead of three (owner, 2026-10-30: "we are fully Leyline").

    py -3 move_to_leyline.py --root "C:\\Users\\you\\Desktop\\WrathUnleashed"          dry run: the plan, changes nothing
    py -3 move_to_leyline.py --root "C:\\Users\\you\\Desktop\\WrathUnleashed" --go     do it

"Move to Leyline.bat" at the top of the workspace runs this from a copy in %TEMP% (a folder can't be renamed while
a window is standing in it): dry run first, then YES, then --go. What --go does, in this order:

  1. checks again: the GitHub CLI is signed in as orionopenwow (never Chumpton or anyone else), no step is waiting
     in UPDATES-PENDING.txt, the control window is not running a step, no git command is half-way in the workspace;
  2. stops the control window (whatever listens on 127.0.0.1:8097), so nothing works in the folder while it moves;
  3. the moves, each a plain rename on the same drive, retried while a file is busy:
       Desktop\\Leyline (the clone of the public orionopenwow/Leyline)  -> Desktop\\Leyline-public-moving (aside)
       Desktop\\WrathUnleashed                                          -> Desktop\\Leyline   (the workspace)
       Desktop\\Leyline-public-moving                                   -> Desktop\\Leyline\\.repos\\leyline-public
       Desktop\\OpenVanilla (the clone of orionopenwow/Leyline-Launcher) -> Desktop\\Leyline\\.repos\\leyline-launcher
     If one fails, the moves already made are undone in reverse, so nothing has changed; if even that fails, the
     log says exactly which folder to move back where (the undo plan is written before the first move);
  4. renames the private GitHub repo WrathUnleashed -> leyline-workspace (GitHub redirects the old name) and points
     the workspace's origin at https://github.com/orionopenwow/leyline-workspace.git;
  5. the Startup entry "WrathUnleashed Control.bat" (Autopilot at sign-in) becomes "Leyline Control.bat" at the new
     place; Desktop shortcuts that still point at the old folders are listed;
  6. writes the new folder to new-root.txt beside this file, for the .bat to restart the control window there.

Exit codes: 0 done (or the dry run is fine), 1 refused or failed (nothing changed unless the output says so),
2 usage. Standard library only, and no imports from the repo: it runs from a copy outside it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "orionopenwow"
FORBIDDEN_ACCOUNTS = {"chumpton"}
OLD_REPO = "WrathUnleashed"
NEW_REPO = "leyline-workspace"
NEW_URL = f"https://github.com/{OWNER}/{NEW_REPO}.git"
WORKSPACE = "Leyline"                 # the one folder on the Desktop
ASIDE = "Leyline-public-moving"       # the public clone's name while the workspace takes its place
REPOS = ".repos"
PUBLIC = "leyline-public"
LAUNCHER = "leyline-launcher"
LAUNCHER_DIRS = ("OpenVanilla", "Leyline-Launcher", "openvanilla", "Open Vanilla")
CONTROL_PORT = 8097
OLD_STARTUP = "WrathUnleashed Control.bat"
NEW_STARTUP = "Leyline Control.bat"

PUBLIC_RE = re.compile(rf"github\.com[:/]{OWNER}/Leyline(\.git)?/?$", re.I)
LAUNCHER_RE = re.compile(rf"github\.com[:/]{OWNER}/(OpenVanilla|Leyline-Launcher)(\.git)?/?$", re.I)
WORKSPACE_RE = re.compile(rf"github\.com[:/]{OWNER}/({OLD_REPO}|{NEW_REPO})(\.git)?/?$", re.I)
OLD_ORIGIN_RE = re.compile(rf"github\.com[:/]{OWNER}/{OLD_REPO}(\.git)?/?$", re.I)


class Refused(Exception):
    pass


# --------------------------------------------------------------------------------------- the outside world
class System:
    """Everything that touches the PC, in one place, so the tests can swap it for a fake."""

    def run(self, cmd: list[str]) -> tuple[int, str]:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            return 127, ""
        except subprocess.TimeoutExpired:
            return 124, ""
        return p.returncode, (p.stdout or "") + (p.stderr if p.returncode else "")

    def exists(self, p: Path) -> bool:
        return os.path.lexists(p)

    def isdir(self, p: Path) -> bool:
        return os.path.isdir(p)

    def rename(self, src: Path, dst: Path) -> None:
        os.rename(src, dst)

    def mkdir(self, p: Path) -> None:
        os.mkdir(p)

    def rmdir(self, p: Path) -> None:
        os.rmdir(p)

    def listdir(self, p: Path) -> list[str]:
        try:
            return sorted(os.listdir(p))
        except OSError:
            return []

    def read_text(self, p: Path) -> str | None:
        try:
            return Path(p).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return None

    def read_bytes(self, p: Path) -> bytes | None:
        try:
            return Path(p).read_bytes()
        except OSError:
            return None

    def write_text(self, p: Path, text: str) -> None:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(text, encoding="utf-8")

    def remove(self, p: Path) -> None:
        os.remove(p)

    def control_state(self, token: str | None):
        """The control window's /api/state: a dict, None when nothing listens, or "unknown"."""
        req = urllib.request.Request(f"http://127.0.0.1:{CONTROL_PORT}/api/state",
                                     headers={"X-Token": token or "", "Host": f"127.0.0.1:{CONTROL_PORT}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return "unknown"
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def sleep(self, s: float) -> None:
        time.sleep(s)


# ----------------------------------------------------------------------------------------------- helpers
def origin(sysm: System, folder: Path) -> str:
    if not sysm.exists(folder / ".git"):
        return ""
    rc, out = sysm.run(["git", "-C", str(folder), "remote", "get-url", "origin"])
    return out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""


def pending_lines(sysm: System, root: Path) -> list[str]:
    """The steps in UPDATES-PENDING.txt that are not in UPDATES-DONE.txt (the control window's own rule)."""
    done = {l.strip() for l in (sysm.read_text(root / "UPDATES-DONE.txt") or "").splitlines()}
    out = []
    for line in (sysm.read_text(root / "UPDATES-PENDING.txt") or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0] not in done:
            out.append(line)
    return out


def token_path(env: dict) -> Path:
    return Path(env.get("LOCALAPPDATA") or Path.home()) / "WrathUnleashed" / "control-token"


def startup_dir(env: dict) -> Path | None:
    return Path(env["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" \
        if env.get("APPDATA") else None


def startup_bat(root: Path) -> str:
    return ("@echo off\r\n"
            f'cd /d "{root}"\r\n'
            'where py >nul 2>&1 && (start "Leyline Control" /min py -3 tools\\control\\control.py --quiet & exit /b 0)\r\n'
            'start "Leyline Control" /min python tools\\control\\control.py --quiet\r\n')


class Mover:
    def __init__(self, root, sysm: System | None = None, env: dict | None = None, out=print, retries=5, wait=2.0,
                 log_path: Path | None = None):
        self.root = Path(root)
        self.desk = self.root.parent
        self.new = self.desk / WORKSPACE
        self.sys = sysm or System()
        self.env = dict(os.environ if env is None else env)
        self._out = out
        self.retries, self.wait = retries, wait
        self.log_lines: list[str] = []
        self.log_path = log_path or Path(self.env.get("TEMP") or self.env.get("TMP") or "/tmp") / "leyline-move.log"

    def say(self, msg: str = "") -> None:
        self.log_lines.append(msg)
        self._out(msg)

    def write_log(self) -> None:
        try:
            self.sys.write_text(self.log_path, "\n".join(self.log_lines) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------------------------------ the plan
    def launcher_clone(self) -> Path | None:
        for n in LAUNCHER_DIRS:
            p = self.desk / n
            if self.sys.isdir(p) and LAUNCHER_RE.search(origin(self.sys, p)):
                return p
        return None

    def plan(self) -> dict:
        """{moves: [(src, dst, what)], notes: [...]}; raises Refused when the folders aren't as expected."""
        moves, notes = [], []
        already = self.root == self.new
        if not self.sys.isdir(self.root):
            raise Refused(f"{self.root} is not a folder")
        if not WORKSPACE_RE.search(origin(self.sys, self.root)):
            raise Refused(f"{self.root} is not the workspace (its origin is not github.com/{OWNER}/{OLD_REPO})")
        repos = self.new / REPOS
        public_src = None
        if not already:
            if self.sys.exists(self.new):
                if self.sys.isdir(self.new) and PUBLIC_RE.search(origin(self.sys, self.new)):
                    aside = self.desk / ASIDE
                    if self.sys.exists(aside):
                        raise Refused(f"{aside} is in the way (left from an earlier try?): move it back to "
                                      f"{self.new} or out of the Desktop, then run this again")
                    moves.append((self.new, aside, "the public Leyline clone, out of the way for a moment"))
                    public_src = aside
                else:
                    raise Refused(f"{self.new} already exists and is not the clone of github.com/{OWNER}/Leyline: "
                                  "rename or move it first, then run this again")
            else:
                notes.append(f"No {self.new} yet: the leyline step makes .repos\\{PUBLIC} on its next run.")
            moves.append((self.root, self.new, "the workspace (Autopilot, the control window, every step)"))
            if public_src:
                moves.append((public_src, repos / PUBLIC, "the public Leyline clone (the leyline step's copy)"))
        else:
            notes.append(f"The workspace is already {self.new}.")
            if not self.sys.exists(repos / PUBLIC):
                notes.append(f"No .repos\\{PUBLIC} yet: the leyline step makes it on its next run.")
        lc = self.launcher_clone()
        if lc and not self.sys.exists(repos / LAUNCHER):
            moves.append((lc, repos / LAUNCHER, "the Leyline-Launcher clone (ovland, ovrename, its releases)"))
        elif lc:
            raise Refused(f"both {lc} and {repos / LAUNCHER} exist: keep one, then run this again")
        elif not self.sys.exists(repos / LAUNCHER):
            notes.append("No OpenVanilla / Leyline-Launcher clone on the Desktop: nothing to move for it.")
        for src, dst, _ in moves:
            if dst != self.new and self.sys.exists(dst):
                raise Refused(f"{dst} already exists: nothing was moved")
        return {"moves": moves, "notes": notes}

    # ------------------------------------------------------------------------------------------ checks
    def check_account(self) -> str:
        rc, out = self.sys.run(["gh", "api", "user", "--jq", ".login"])
        if rc == 127:
            raise Refused("the GitHub CLI is not installed: winget install GitHub.cli, then gh auth login")
        who = out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""
        if not who:
            raise Refused(f"the GitHub CLI is not signed in: gh auth login (as {OWNER})")
        if who.lower() in FORBIDDEN_ACCOUNTS or who.lower() != OWNER.lower():
            raise Refused(f"the GitHub CLI is signed in as {who}, not {OWNER}: gh auth switch (nothing was changed)")
        return who

    def control(self):
        tok = (self.sys.read_text(token_path(self.env)) or "").strip() or None
        return self.sys.control_state(tok)

    def check_idle(self) -> None:
        waiting = pending_lines(self.sys, self.root)
        if waiting:
            raise Refused("steps are still waiting in UPDATES-PENDING.txt (run them, or let Autopilot finish):\n    "
                          + "\n    ".join(waiting[:8]))
        st = self.control()
        if st == "unknown":
            raise Refused("the control window answers but won't say whether a step is running: close it, then "
                          "run this again")
        if isinstance(st, dict) and st.get("running"):
            r = st["running"]
            raise Refused(f"the control window is running a step ({r.get('title') or r.get('step')}): wait for it")
        if self.sys.exists(self.root / ".git" / "index.lock"):
            raise Refused("a git command is half-way in the workspace (.git\\index.lock): wait, or ask Claude")

    def checks(self) -> str:
        who = self.check_account()
        self.check_idle()
        return who

    # ------------------------------------------------------------------------------------------ doing
    def stop_control(self) -> None:
        rc, out = self.sys.run(["netstat", "-ano"])
        pids = set()
        for line in out.splitlines() if rc == 0 else []:
            f = line.split()
            if len(f) >= 5 and f[1] == f"127.0.0.1:{CONTROL_PORT}" and f[3].upper() == "LISTENING":
                pids.add(f[4])
        for pid in sorted(pids):
            self.sys.run(["taskkill", "/f", "/pid", pid])
            self.say(f"  stopped the control window (process {pid})")
        if not pids:
            self.say("  the control window was not open")

    def _rename(self, src: Path, dst: Path) -> bool:
        for i in range(self.retries):
            try:
                self.sys.rename(src, dst)
                return True
            except OSError as e:
                self.say(f"    busy ({e.__class__.__name__}: {e}); trying again ({i + 1}/{self.retries})")
                if i + 1 < self.retries:
                    self.sys.sleep(self.wait)
        return False

    def do_moves(self, moves) -> bool:
        self.say("Undo plan, if it ever comes to that (each line: move this folder back to that place):")
        for src, dst, _ in reversed(moves):
            self.say(f'    move "{dst}" "{src}"')
        self.write_log()
        done, made = [], []
        for src, dst, what in moves:
            parent = dst.parent
            if not self.sys.exists(parent):
                try:
                    self.sys.mkdir(parent)
                    made.append(parent)
                except OSError as e:
                    self.say(f"  could not make {parent}: {e}")
                    return self.undo(done, made)
            self.say(f"  {src} -> {dst}   ({what})")
            if not self._rename(src, dst):
                self.say(f"  STOPPED: {src} could not be moved (a window, an editor or a program is still using it).")
                return self.undo(done, made)
            done.append((src, dst))
        return True

    def undo(self, done, made) -> bool:
        stuck = []

        def drop_made():                     # .repos, once empty and while it is still where it was made
            for d in reversed(made):
                try:
                    if self.sys.isdir(d) and not self.sys.listdir(d):
                        self.sys.rmdir(d)
                except OSError:
                    pass
        for src, dst in reversed(done):
            drop_made()
            if self._rename(dst, src):
                self.say(f"  put back: {dst} -> {src}")
            else:
                stuck.append((src, dst))
        drop_made()
        if stuck:
            self.say("NOT EVERYTHING COULD BE PUT BACK. Close every window and program using these folders, then "
                     "move them back by hand (in this order):")
            for src, dst in stuck:
                self.say(f'    move "{dst}" "{src}"')
        else:
            self.say("Everything was put back: nothing has changed. Close what was using the folder and run this again.")
        self.write_log()
        return False

    def rename_github(self) -> bool:
        rc, out = self.sys.run(["gh", "api", f"repos/{OWNER}/{NEW_REPO}", "--jq", ".full_name"])
        if rc == 0 and out.strip().lower() == f"{OWNER}/{NEW_REPO}".lower():
            self.say(f"  GitHub: {OWNER}/{NEW_REPO} already (nothing to rename)")
            return True
        rc, out = self.sys.run(["gh", "api", "-X", "PATCH", f"repos/{OWNER}/{OLD_REPO}", "-f", f"name={NEW_REPO}"])
        if rc != 0:
            self.say(f"  GitHub: the rename to {NEW_REPO} failed ({out.strip()[:200]}). The folders are moved; Ship "
                     f"still works with the old name. Ask Claude.")
            return False
        self.say(f"  GitHub: {OWNER}/{OLD_REPO} is now {OWNER}/{NEW_REPO} (the old address redirects)")
        return True

    def set_origin(self, ws: Path) -> None:
        cur = origin(self.sys, ws)
        if not OLD_ORIGIN_RE.search(cur):
            self.say(f"  origin: {cur or '(none)'} (left as it is)")
            return
        rc, out = self.sys.run(["git", "-C", str(ws), "remote", "set-url", "origin", NEW_URL])
        self.say(f"  origin: {NEW_URL}" if rc == 0 else f"  origin: could not set it ({out.strip()[:200]})")

    def startup(self, ws: Path) -> None:
        sd = startup_dir(self.env)
        if not sd or not self.sys.isdir(sd):
            self.say("  Startup: no Startup folder here (Autopilot at sign-in was never turned on)")
            return
        old, new = sd / OLD_STARTUP, sd / NEW_STARTUP
        if not self.sys.exists(old) and not self.sys.exists(new):
            self.say("  Startup: Autopilot at sign-in is off (no entry): left off")
            return
        self.sys.write_text(new, startup_bat(ws))
        if self.sys.exists(old):
            self.sys.remove(old)
        self.say(f'  Startup: "{NEW_STARTUP}" starts the control window from {ws} at sign-in')

    def shortcuts(self) -> list[Path]:
        """Desktop shortcuts (.lnk, .url) whose target still names an old folder (listed, not changed)."""
        olds = [str(self.root), str(self.desk / "OpenVanilla")]
        needles = [s.encode(enc) for s in olds for enc in ("utf-16-le", "utf-8")]
        found = []
        for name in self.sys.listdir(self.desk):
            if name.lower().endswith((".lnk", ".url")):
                b = self.sys.read_bytes(self.desk / name) or b""
                if any(n in b for n in needles):
                    found.append(self.desk / name)
        return found

    # ------------------------------------------------------------------------------------------ the run
    def run(self, go: bool) -> int:
        self.say(f"Move to Leyline ({'DOING IT' if go else 'dry run: nothing changes'})")
        try:
            who = self.checks()
            p = self.plan()
        except Refused as e:
            self.say(f"REFUSED: {e}")
            self.write_log()
            return 1
        self.say(f"  GitHub CLI: signed in as {who}; nothing waiting; no step running")
        self.say("The moves:")
        for src, dst, what in p["moves"]:
            self.say(f"  {src}\n      -> {dst}   ({what})")
        if not p["moves"]:
            self.say("  none")
        for n in p["notes"]:
            self.say(f"  note: {n}")
        self.say(f"Then: GitHub repo {OWNER}/{OLD_REPO} -> {OWNER}/{NEW_REPO}, origin -> {NEW_URL},")
        self.say(f'      the Startup entry -> "{NEW_STARTUP}", the control window restarts from {self.new}.')
        if not go:
            self.say("DRY RUN OK: nothing was changed.")
            self.write_log()
            return 0
        self.say("Stopping the control window...")
        try:
            self.check_idle()                       # again, right before stopping it
        except Refused as e:
            self.say(f"REFUSED: {e}")
            self.write_log()
            return 1
        self.stop_control()
        self.say("Moving...")
        if not self.do_moves(p["moves"]):
            return 1
        ws = self.new
        self.say("After the moves:")
        if self.rename_github():
            self.set_origin(ws)
        self.startup(ws)
        for s in self.shortcuts():
            self.say(f"  shortcut still points at an old folder (re-make it from {ws}): {s}")
        here = Path(__file__).resolve().parent
        try:
            self.sys.write_text(here / "new-root.txt", str(ws))
        except OSError:
            pass
        self.say("")
        self.say(f"DONE. The workspace is {ws}")
        self.say("In the Claude desktop app: remove the old WrathUnleashed folder from this project's folders and add")
        self.say(f"  {ws}  so Claude can reach it again. Tell Claude \"moved to Leyline\".")
        self.write_log()
        try:
            self.sys.write_text(ws / "logs" / "move-to-leyline.log", "\n".join(self.log_lines) + "\n")
        except OSError:
            pass
        return 0


def main(argv=None, sysm: System | None = None, env: dict | None = None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Move the workspace to Desktop\\Leyline (one folder).")
    ap.add_argument("--root", required=True, help="the workspace folder (today Desktop\\WrathUnleashed)")
    ap.add_argument("--go", action="store_true", help="do it (default: a dry run that changes nothing)")
    a = ap.parse_args(argv)
    return Mover(Path(a.root).resolve() if sysm is None else Path(a.root), sysm, env, out).run(a.go)


if __name__ == "__main__":
    sys.exit(main())
