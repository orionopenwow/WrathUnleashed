#!/usr/bin/env python3
"""Tests for move_to_leyline.py on a fake PC (folders in memory, a fake gh/git/netstat, a fake control window).

    python3 -I tools/workspace-move/test_move_to_leyline.py
"""
import importlib.util
import os
import sys
import unittest
from pathlib import PurePosixPath as P

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("move_to_leyline", os.path.join(HERE, "move_to_leyline.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

DESK = P("/home/u/Desktop")
WU = DESK / "WrathUnleashed"
LY = DESK / "Leyline"
OV = DESK / "OpenVanilla"
APPDATA = P("/home/u/AppData/Roaming")
STARTUP = APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


class FakePC(m.System):
    def __init__(self):
        self.dirs = {P("/"), P("/home"), P("/home/u"), DESK, P("/tmp"), APPDATA, STARTUP.parent.parent.parent,
                     STARTUP.parent.parent, STARTUP.parent, STARTUP}
        self.files = {}
        self.origins = {}
        self.calls = []
        self.login = "orionopenwow"
        self.state = None                 # the control window: None (closed), a dict, or "unknown"
        self.busy = {}                    # src path -> how many renames fail first
        self.listening = ["  TCP    127.0.0.1:8097     0.0.0.0:0     LISTENING     4242"]
        self.renamed_on_github = False
        self.patch_fails = False
        self.renames = []

    # folders
    def add_dir(self, p, origin=None):
        p = P(p)
        for a in [p] + list(p.parents):
            self.dirs.add(a)
        if origin is not None:
            self.dirs.add(p / ".git")
            self.origins[p] = origin

    def exists(self, p):
        p = P(p)
        return p in self.dirs or p in self.files

    def isdir(self, p):
        return P(p) in self.dirs

    def listdir(self, p):
        p = P(p)
        return sorted({x.relative_to(p).parts[0] for x in list(self.dirs) + list(self.files)
                       if x != p and p in x.parents})

    def mkdir(self, p):
        p = P(p)
        if p.parent not in self.dirs or self.exists(p):
            raise OSError("mkdir")
        self.dirs.add(p)

    def rmdir(self, p):
        p = P(p)
        if self.listdir(p):
            raise OSError("not empty")
        self.dirs.discard(p)

    def rename(self, src, dst):
        src, dst = P(src), P(dst)
        if self.busy.get(src, 0) > 0:
            self.busy[src] -= 1
            raise PermissionError("in use")
        if not self.exists(src) or self.exists(dst) or dst.parent not in self.dirs:
            raise OSError(f"rename {src} {dst}")

        def mv(x):
            return dst / x.relative_to(src) if (x == src or src in x.parents) else x
        self.dirs = {mv(x) for x in self.dirs}
        self.files = {mv(k): v for k, v in self.files.items()}
        self.origins = {mv(k): v for k, v in self.origins.items()}
        self.renames.append((str(src), str(dst)))

    def read_text(self, p):
        v = self.files.get(P(p))
        return None if v is None else (v.decode() if isinstance(v, bytes) else v)

    def read_bytes(self, p):
        v = self.files.get(P(p))
        return None if v is None else (v if isinstance(v, bytes) else v.encode())

    def write_text(self, p, text):
        p = P(p)
        self.add_dir(p.parent)
        self.files[p] = text

    def remove(self, p):
        del self.files[P(p)]

    def control_state(self, token):
        return self.state

    def sleep(self, s):
        pass

    def run(self, cmd):
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "api", "user"]:
            return (0, self.login + "\n") if self.login else (1, "")
        if cmd[:2] == ["gh", "api"] and cmd[2] == "repos/orionopenwow/leyline-workspace":
            return (0, "orionopenwow/leyline-workspace\n") if self.renamed_on_github else (1, "Not Found")
        if cmd[:4] == ["gh", "api", "-X", "PATCH"]:
            if self.patch_fails:
                return 1, "HTTP 403"
            self.renamed_on_github = True
            return 0, "{}"
        if cmd[:2] == ["git", "-C"] and cmd[3:5] == ["remote", "get-url"]:
            o = self.origins.get(P(cmd[2]))
            return (0, o + "\n") if o else (2, "no origin")
        if cmd[:2] == ["git", "-C"] and cmd[3:5] == ["remote", "set-url"]:
            self.origins[P(cmd[2])] = cmd[6]
            return 0, ""
        if cmd[0] == "netstat":
            return 0, "\n".join(self.listening)
        if cmd[0] == "taskkill":
            self.listening = []
            return 0, ""
        return 127, ""


def pc_today():
    pc = FakePC()
    pc.add_dir(WU, "https://github.com/orionopenwow/WrathUnleashed.git")
    pc.files[WU / "UPDATES-PENDING.txt"] = "# header\n1030a ship save\n1030b leyline copy\n"
    pc.files[WU / "UPDATES-DONE.txt"] = "1030a\n1030b\n"
    pc.add_dir(WU / "tools" / "control")
    pc.add_dir(LY, "https://github.com/orionopenwow/Leyline.git")
    pc.files[LY / "README.md"] = "public"
    pc.add_dir(OV, "https://github.com/orionopenwow/Leyline-Launcher.git")
    pc.files[STARTUP / "WrathUnleashed Control.bat"] = "old"
    return pc


def mover(pc, root=WU, **kw):
    out = []
    mv = m.Mover(root, pc, {"APPDATA": str(APPDATA), "TEMP": "/tmp", "LOCALAPPDATA": "/home/u/AppData/Local"},
                 out.append, log_path=P("/tmp/leyline-move.log"), **kw)
    return mv, out


class DryRun(unittest.TestCase):
    def test_dry_run_changes_nothing(self):
        pc = pc_today()
        before = (set(pc.dirs), dict(pc.files), dict(pc.origins))
        mv, out = mover(pc)
        self.assertEqual(mv.run(False), 0)
        self.assertEqual(pc.renames, [])
        self.assertFalse(any(c[0] in ("taskkill",) or c[:4] == ["gh", "api", "-X", "PATCH"] or "set-url" in c
                             for c in pc.calls))
        files = dict(pc.files)
        files.pop(P("/tmp/leyline-move.log"), None)
        self.assertEqual((set(pc.dirs) - {P("/tmp")} | {P("/tmp")}, files, pc.origins), before)
        self.assertIn("DRY RUN OK: nothing was changed.", out)

    def test_plan_order(self):
        mv, _ = mover(pc_today())
        moves = [(str(s), str(d)) for s, d, _ in mv.plan()["moves"]]
        self.assertEqual(moves, [(str(LY), str(DESK / "Leyline-public-moving")),
                                 (str(WU), str(LY)),
                                 (str(DESK / "Leyline-public-moving"), str(LY / ".repos" / "leyline-public")),
                                 (str(OV), str(LY / ".repos" / "leyline-launcher"))])


class Refusals(unittest.TestCase):
    def refused(self, pc, text, go=True):
        mv, out = mover(pc)
        self.assertEqual(mv.run(go), 1)
        self.assertEqual(pc.renames, [])
        self.assertTrue(any(text in l for l in out if l.startswith("REFUSED")), out)
        self.assertFalse(any(c[0] == "taskkill" for c in pc.calls))

    def test_wrong_account(self):
        pc = pc_today(); pc.login = "Chumpton"
        self.refused(pc, "signed in as Chumpton")

    def test_other_account(self):
        pc = pc_today(); pc.login = "someone"
        self.refused(pc, "not orionopenwow")

    def test_not_signed_in(self):
        pc = pc_today(); pc.login = ""
        self.refused(pc, "not signed in")

    def test_pending_steps(self):
        pc = pc_today(); pc.files[WU / "UPDATES-PENDING.txt"] += "1030c client new build\n"
        self.refused(pc, "waiting in UPDATES-PENDING.txt")

    def test_step_running(self):
        pc = pc_today(); pc.state = {"running": {"step": "slice", "title": "Streamed game files"}}
        self.refused(pc, "running a step (Streamed game files)")

    def test_control_window_unknown(self):
        pc = pc_today(); pc.state = "unknown"
        self.refused(pc, "won't say")

    def test_git_half_way(self):
        pc = pc_today(); pc.files[WU / ".git" / "index.lock"] = ""
        self.refused(pc, "index.lock")

    def test_desktop_leyline_is_something_else(self):
        pc = pc_today(); pc.origins[LY] = "https://github.com/someone/else.git"
        self.refused(pc, "is not the clone")

    def test_aside_in_the_way(self):
        pc = pc_today(); pc.add_dir(DESK / "Leyline-public-moving")
        self.refused(pc, "in the way")

    def test_not_the_workspace(self):
        pc = pc_today(); pc.origins[WU] = "https://github.com/orionopenwow/Other.git"
        self.refused(pc, "is not the workspace")


class Go(unittest.TestCase):
    def test_everything(self):
        pc = pc_today()
        mv, out = mover(pc)
        self.assertEqual(mv.run(True), 0, "\n".join(out))
        self.assertEqual(pc.calls.index(["taskkill", "/f", "/pid", "4242"]) < len(pc.calls), True)
        self.assertTrue(pc.isdir(LY / "tools" / "control"))
        self.assertEqual(pc.read_text(LY / ".repos" / "leyline-public" / "README.md"), "public")
        self.assertEqual(pc.origins[LY / ".repos" / "leyline-public"], "https://github.com/orionopenwow/Leyline.git")
        self.assertIn(LY / ".repos" / "leyline-launcher", pc.origins)
        self.assertFalse(pc.exists(WU) or pc.exists(OV) or pc.exists(DESK / "Leyline-public-moving"))
        # GitHub rename, then the origin
        self.assertIn(["gh", "api", "-X", "PATCH", "repos/orionopenwow/WrathUnleashed", "-f", "name=leyline-workspace"],
                      pc.calls)
        self.assertEqual(pc.origins[LY], "https://github.com/orionopenwow/leyline-workspace.git")
        # Startup entry renamed and pointed at the new place
        self.assertNotIn(STARTUP / "WrathUnleashed Control.bat", pc.files)
        self.assertIn(f'cd /d "{LY}"', pc.files[STARTUP / "Leyline Control.bat"])
        self.assertIn("control.py --quiet", pc.files[STARTUP / "Leyline Control.bat"])
        self.assertIn(P("/tmp/leyline-move.log"), pc.files)
        self.assertTrue(any(l.startswith("DONE.") for l in out))
        # the undo plan was written before the first move
        self.assertTrue(any("Undo plan" in l for l in out))

    def test_stops_control_before_moving(self):
        pc = pc_today()
        order = []
        real_rename, real_run = pc.rename, pc.run
        pc.rename = lambda s, d: (order.append("rename"), real_rename(s, d))[1]
        pc.run = lambda c: (order.append(c[0]), real_run(c))[1]
        mv, _ = mover(pc)
        self.assertEqual(mv.run(True), 0)
        self.assertLess(order.index("taskkill"), order.index("rename"))

    def test_busy_then_free(self):
        pc = pc_today(); pc.busy[WU] = 2
        mv, out = mover(pc)
        self.assertEqual(mv.run(True), 0)
        self.assertTrue(any("trying again (2/5)" in l for l in out))

    def test_partial_failure_puts_everything_back(self):
        pc = pc_today(); pc.busy[OV] = 99            # the last move never works
        before_dirs = set(pc.dirs)
        mv, out = mover(pc)
        self.assertEqual(mv.run(True), 1)
        self.assertTrue(pc.isdir(WU) and pc.isdir(LY) and pc.isdir(OV))
        self.assertEqual(pc.origins[LY], "https://github.com/orionopenwow/Leyline.git")
        self.assertEqual(pc.origins[WU], "https://github.com/orionopenwow/WrathUnleashed.git")
        self.assertEqual({d for d in pc.dirs if d != P("/tmp")}, {d for d in before_dirs if d != P("/tmp")})
        self.assertTrue(any("Everything was put back" in l for l in out))
        self.assertFalse(any(c[:4] == ["gh", "api", "-X", "PATCH"] for c in pc.calls))
        self.assertIn("Undo plan", pc.files[P("/tmp/leyline-move.log")])

    def test_partial_failure_stuck_writes_the_plan(self):
        pc = pc_today(); pc.busy[OV] = 99
        mv, out = mover(pc)
        real = pc.rename

        def rename(s, d):
            if P(s) == LY and P(d) == WU:          # putting the workspace back fails too
                raise PermissionError("in use")
            real(s, d)
        pc.rename = rename
        self.assertEqual(mv.run(True), 1)
        log = pc.files[P("/tmp/leyline-move.log")]
        self.assertIn("NOT EVERYTHING COULD BE PUT BACK", log)
        self.assertIn(f'move "{LY}" "{WU}"', log)

    def test_github_rename_fails_keeps_old_origin(self):
        pc = pc_today(); pc.patch_fails = True
        mv, out = mover(pc)
        self.assertEqual(mv.run(True), 0)
        self.assertEqual(pc.origins[LY], "https://github.com/orionopenwow/WrathUnleashed.git")
        self.assertTrue(any("rename to leyline-workspace failed" in l for l in out))

    def test_already_renamed_on_github(self):
        pc = pc_today(); pc.renamed_on_github = True
        mv, _ = mover(pc)
        self.assertEqual(mv.run(True), 0)
        self.assertFalse(any(c[:4] == ["gh", "api", "-X", "PATCH"] for c in pc.calls))
        self.assertEqual(pc.origins[LY], "https://github.com/orionopenwow/leyline-workspace.git")

    def test_no_public_clone_and_no_launcher_clone(self):
        pc = FakePC()
        pc.add_dir(WU, "https://github.com/orionopenwow/WrathUnleashed.git")
        mv, out = mover(pc)
        self.assertEqual(mv.run(True), 0)
        self.assertEqual(pc.renames, [(str(WU), str(LY))])
        self.assertTrue(any("Autopilot at sign-in is off" in l for l in out))

    def test_run_again_from_the_new_place(self):
        pc = pc_today()
        mover(pc)[0].run(True)
        pc.renames.clear()
        mv, out = mover(pc, root=LY)
        self.assertEqual(mv.run(True), 0)
        self.assertEqual(pc.renames, [])

    def test_shortcuts_listed(self):
        pc = pc_today()
        pc.files[DESK / "Control.lnk"] = ("xx" + str(WU) + "\\tools").encode("utf-16-le")
        pc.files[DESK / "Other.lnk"] = b"C:\\Games"
        mv, out = mover(pc)
        self.assertEqual(mv.run(True), 0)
        self.assertTrue(any("Control.lnk" in l and "shortcut" in l for l in out))
        self.assertFalse(any("Other.lnk" in l for l in out))


class Files(unittest.TestCase):
    def test_bat_runs_from_a_copy_dry_first_then_yes(self):
        bat = open(os.path.join(HERE, "..", "..", "Move to Leyline.bat"), encoding="utf-8").read()
        self.assertIn("move_to_leyline.py", bat)
        self.assertIn("%TEMP%", bat)
        self.assertIn('cd /d "%USERPROFILE%"', bat)
        dry, yes, go = bat.index('--root "%WS%"'), bat.index("Type YES"), bat.index('--root "%WS%" --go')
        self.assertLess(dry, yes)
        self.assertLess(yes, go)
        self.assertIn("new-root.txt", bat)
        self.assertIn("Leyline Control.bat", bat)

    def test_standard_library_only_and_standalone(self):
        src = open(os.path.join(HERE, "move_to_leyline.py"), encoding="utf-8").read()
        imports = {l.split()[1].split(".")[0] for l in src.splitlines() if l.startswith(("import ", "from "))}
        self.assertTrue(imports <= {"__future__", "argparse", "json", "os", "re", "subprocess", "sys", "time",
                                    "urllib", "pathlib"}, imports)

    def test_repos_ignored(self):
        gi = open(os.path.join(HERE, "..", "..", ".gitignore"), encoding="utf-8").read()
        self.assertIn("/.repos/", gi)


if __name__ == "__main__":
    unittest.main()
