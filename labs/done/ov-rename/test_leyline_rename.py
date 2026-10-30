#!/usr/bin/env python3
"""Where leyline_rename.py looks for the Leyline-Launcher clone (after "Move to Leyline.bat" too).

    python3 -I labs/done/ov-rename/test_leyline_rename.py
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("leyline_rename", os.path.join(HERE, "leyline_rename.py"))
lr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lr)


class Candidates(unittest.TestCase):
    def test_order(self):
        home = os.path.join(os.sep, "u")
        ws = os.path.join(home, "Desktop", "Leyline")
        c = lr.clone_candidates(ws, {"USERPROFILE": home})
        self.assertEqual(c[0], os.path.join(ws, ".repos", "leyline-launcher"))
        self.assertIn(os.path.join(home, "Desktop", "OpenVanilla"), c)          # the old place still works
        c2 = lr.clone_candidates(ws, {"USERPROFILE": home, "OPENVANILLA_DIR": "/x"})
        self.assertEqual(c2[:2], ["/x", os.path.join(ws, ".repos", "leyline-launcher")])

    def test_finds_the_moved_clone_first(self):
        t = tempfile.mkdtemp()
        ws = os.path.join(t, "Desktop", "Leyline")
        moved = os.path.join(ws, ".repos", "leyline-launcher")
        old = os.path.join(t, "Desktop", "OpenVanilla")
        for d in (moved, old):
            os.makedirs(os.path.join(d, ".git"))
        origins = {moved: "https://github.com/orionopenwow/Leyline-Launcher.git",
                   old: "https://github.com/orionopenwow/OpenVanilla.git"}

        def runner(cmd):
            return 0, origins[cmd[2]] + "\n"
        self.assertEqual(lr.find_clone(lr.clone_candidates(ws, {"USERPROFILE": t}), runner), os.path.abspath(moved))
        self.assertEqual(lr.find_clone([old], runner), os.path.abspath(old))


if __name__ == "__main__":
    unittest.main()
