#!/usr/bin/env python3
"""Every step file exists: the .bat of each Autopilot step (STEPS in control.py), each step UPDATE.bat knows, and
every file "Ship the Leyline launcher.bat" calls. None of them lives in labs/ (labs/README.md), and the top of the
workspace holds only what the owner clicks regularly (docs/REPO-MAP.md, "Root files").

    python3 -I tools/control/test_step_paths.py
"""
import ast
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def control_steps():
    """STEPS from control.py's source (importing it would start nothing, but it writes a token file)."""
    tree = ast.parse(read("tools/control/control.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "STEPS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("no STEPS in control.py")


def win(rel):
    return rel.replace("\\", "/")


class StepPaths(unittest.TestCase):
    def test_control_steps_exist(self):
        steps = control_steps()
        self.assertIn("ship", steps)
        self.assertEqual(steps["ship"][0], "Ship to GitHub.bat")
        for step, (bat, _title, _interactive) in steps.items():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, bat)), f"{step}: {bat}")
            self.assertFalse(win(bat).startswith("labs/"), f"{step} points into labs/: {bat}")
        for gone in ("ovrename", "ovland"):
            self.assertNotIn(gone, steps)

    def test_update_bat_steps_exist(self):
        bats = re.findall(r'if /i "%STEP%"=="([^"]+)"\s+\(?set "BAT=([^"]+)"', read("UPDATE.bat"))
        self.assertGreater(len(bats), 10)
        self.assertIn(("ship", "Ship to GitHub.bat"), bats)
        for step, bat in bats:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, win(bat))), f"UPDATE.bat {step}: {bat}")
            self.assertFalse(win(bat).startswith("labs/"), bat)
        for bat in re.findall(r'call "(tools\\[^"]+\.bat)"', read("UPDATE.bat")):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, win(bat))), bat)

    def test_launcher_release_calls_exist(self):
        calls = re.findall(r'call "%~dp0([^"]+)"', read("Ship the Leyline launcher.bat"))
        self.assertEqual(len(calls), 4, calls)
        for bat in calls:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, win(bat))), bat)

    def test_ship_is_one_click(self):
        bat = read("Ship to GitHub.bat")
        self.assertNotIn("set /p", bat.lower())                      # no questions
        for var in ("WU_SHIP_AUTO", "LEYLINE_SHIP_AUTO", "WU_SHIP_MSG", "LEYLINE_SHIP_MSG"):
            self.assertIn(var, bat)
        self.assertIn("git add -A", bat)
        self.assertIn("git push -q -u origin HEAD:main", bat)
        self.assertIn("Leyline update", bat)
        self.assertIn("--shortstat", bat)
        self.assertIn("timeout /t 5", bat)
        self.assertIn("https://github.com/orionopenwow/leyline-workspace.git", bat)
        self.assertIn('if /i not "%%F"=="Ship to GitHub.bat"', bat)   # its own scan patterns are not a secret
        self.assertLess(bat.index("git merge -q"), bat.index("git add -A ||"))
        self.assertLess(bat.index("SECRET?"), bat.index("git commit"))
        self.assertNotIn("WrathUnleashed", "\n".join(l for l in bat.splitlines() if "echo" in l.lower() or "title" in l))
        # errors keep the window open; success never waits for a key
        ok = bat[bat.index(":push"):bat.index(":fail")]
        self.assertNotIn("pause", ok)
        self.assertIn("pause", bat[bat.index(":fail"):])

    def test_root_is_only_what_gets_clicked(self):
        out = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True, check=True).stdout
        top = sorted({p for p in out.splitlines() if "/" not in p})
        self.assertEqual(top, sorted([".gitignore", "Leyline Control.bat", "README.md", "Ship the Leyline launcher.bat",
                                      "Ship to GitHub.bat", "UPDATE.bat", "UPDATES-DONE.txt", "UPDATES-PENDING.txt"]))

    def test_setup_files_run_from_the_workspace(self):
        for name in ("Turn on Autopilot (start with Windows).bat", "Turn on GitHub builds.bat",
                     "Turn on launcher updates.bat", "Set up automatic deploys.bat"):
            bat = read("setup/" + name)
            self.assertIn('cd /d "%~dp0.."', bat, name)
            self.assertNotIn("%~dp0tools", bat, name)
            self.assertNotIn("%~dp0logs", bat, name)


if __name__ == "__main__":
    unittest.main()
