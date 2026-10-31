#!/usr/bin/env python3
"""tools/hq/hq_sync.py and "HQ sync.bat": what the owner's PC sends to Leyline HQ and what it brings back.

    python3 -I tools/hq/test_hq_sync.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOL = HERE / "hq_sync.py"


def run(root, *args):
    env = dict(os.environ, LEYLINE_ROOT=str(root))
    return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, env=env)


class Sync(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        (self.t / "control").mkdir()
        (self.t / "logs").mkdir()
        (self.t / "tools" / "control").mkdir(parents=True)
        (self.t / "tools" / "control" / "control.py").write_text((ROOT / "tools" / "control" / "control.py").read_text(encoding="utf-8"),
                                                                 encoding="utf-8")
        (self.t / "UPDATES-PENDING.txt").write_text(
            "# comment\n1090a signin  Leyline HQ: the home page\n1090b relay  Relay block feed\n1090c ship  Save\n", encoding="utf-8")
        (self.t / "UPDATES-DONE.txt").write_text("1090a\n", encoding="utf-8")
        (self.t / "control" / "last-run.json").write_text(json.dumps({"ids": ["1090b"], "ok": False, "failed_step": "relay"}))
        (self.t / "control" / "last-check.json").write_text(json.dumps({"at": "2026-10-31T01:00:00Z", "id": "check-auto-1", "ok": True}))
        (self.t / "logs" / "1090a-signin.log").write_text("SOAP_PASS=sekrit\nsome log line LOGSECRET\n")

    def test_build(self):
        (self.t / "control" / "hq-notes.json").write_text(json.dumps({"format": 1, "notes": [
            {"id": "n1", "date": "2026-10-31", "title": "HQ is live", "items": ["one", "two\nlines", 3]}],
            "ack": ["o20261031120000ab12", "../evil"]}))
        out = self.t / "out"
        r = run(self.t, "build", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ch = json.loads((out / "changes.json").read_text())
        self.assertEqual([s["id"] for s in ch["steps"]], ["1090c", "1090b", "1090a"])   # newest first
        st = {s["id"]: s for s in ch["steps"]}
        self.assertIs(st["1090a"]["ok"], True)
        self.assertIs(st["1090b"]["ok"], False)
        self.assertIsNone(st["1090c"]["ok"])
        self.assertEqual(st["1090a"]["title"], "Play page and sign-in")
        self.assertTrue(st["1090a"]["at"].endswith("Z"))
        self.assertEqual(ch["last_check"], {"at": "2026-10-31T01:00:00Z", "ok": True, "id": "check-auto-1"})
        whole = (out / "changes.json").read_text() + (out / "claude-notes.json").read_text()
        self.assertNotIn("sekrit", whole)          # never a log line
        self.assertNotIn("LOGSECRET", whole)
        cn = json.loads((out / "claude-notes.json").read_text())
        self.assertEqual(cn["notes"][0]["items"], ["one", "two lines", "3"])
        self.assertEqual(cn["ack"], ["o20261031120000ab12"])

    def test_brand_words_refused(self):
        (self.t / "control" / "hq-notes.json").write_text(json.dumps({"notes": [{"id": "n1", "title": "WoW news", "items": []}]}))
        r = run(self.t, "build", str(self.t / "out"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("Nothing was uploaded", r.stdout)
        self.assertFalse((self.t / "out" / "changes.json").exists())

    def test_inbox(self):
        (self.t / "control" / "hq-notes.json").write_text(json.dumps({"ack": ["o20261031120000ab12"]}))
        src = self.t / "owner-notes.jsonl"
        src.write_text("\n".join(json.dumps(x) for x in [
            {"id": "o20261031120000ab12", "at": "2026-10-31T12:00:00Z", "by": "owner1", "text": "First"},
            {"id": "o20261031130000cd34", "at": "2026-10-31T13:00:00Z", "by": "owner1", "text": "Second\nline"},
            {"id": "o20261031140000ef56", "at": "2026-10-31T14:00:00Z", "by": "owner1", "text": "Closed one"},
            {"id": "o20261031140000ef56", "status": "closed"}, {"id": "bad", "text": "x"}]) + "\nnot json\n")
        r = run(self.t, "inbox", str(src))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = json.loads((self.t / "control" / "notes-from-owner.json").read_text())
        self.assertEqual([(n["id"], n["status"]) for n in doc["notes"]],
                         [("o20261031130000cd34", "new"), ("o20261031120000ab12", "seen")])
        self.assertEqual(doc["notes"][0]["text"], "Second\nline")
        self.assertIn("1 new", r.stdout)

    def test_bat(self):
        bat = (HERE / "HQ sync.bat").read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0..\\.."', bat)
        self.assertIn("/srv/wrath/portal-data/hq", bat)
        self.assertIn("mv -f $D/.changes.json $D/changes.json", bat)      # atomic
        self.assertIn("hq_sync.py\" inbox", bat)
        self.assertIn("%%Y-%%m-%%dT%%H:%%M:%%SZ", bat)                    # % doubled inside a bat
        self.assertLess(bat.index("cat $D/owner-notes.jsonl"), bat.index("picked-up-at"))
        self.assertNotIn("pause", bat.lower())                           # Autopilot runs it hands-free
        for step in ("hq-sync", "hqnote", "hq-inbox"):
            self.assertIn(f'"{step}": ("tools/hq/HQ sync.bat"', (ROOT / "tools" / "control" / "control.py").read_text(encoding="utf-8"))
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/control/notes-from-owner.json", gi)
        self.assertIn("/control/hq-notes.json", gi)


if __name__ == "__main__":
    unittest.main()
