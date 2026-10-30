"""The hub index pipeline (tools/hub-index/hub_index.py) and the shared rules in stream/hub.py: every filter rule,
the brand-word display check, dedupe, deterministic output, the submissions/decisions merge, and the checked-in
index itself. No network: the forge API and git are faked.

    python3 -I tools/hub-index/test_hub_index.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("hub_index", os.path.join(HERE, "hub_index.py"))
HI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(HI)
H = HI.H


def facts(**kw):
    f = {"ok": True, "head": "abc", "updated": "2026-10-01", "files_n": 20, "game_data": [], "binaries": [],
         "decomp_files": [], "cpp": 0, "lua": 0, "conf_dist": False, "cmake": False, "core_dirs": False,
         "docker": False, "licence": "MIT", "licence_file": "LICENSE", "readme": "", "tocs": []}
    f.update(kw)
    return f


def cand(repo="https://github.com/alice/frame-kit", origin="discovered", **kw):
    c = H.canonical(repo)
    out = {"url": c["url"], "key": c["key"], "id": c["id"], "forge": c["forge"], "owner": c["owner"],
           "name_raw": c["repo"], "origin": origin, "hint_builds": [], "builds_given": [], "pool": {}}
    out.update(kw)
    return out


ADDON_335 = {"tocs": [{"file": "FrameKit.toc", "interface": "30300", "title": "FrameKit", "author": "alice"}]}
META = {"stars": 40, "licence": "", "description": "Tidy raid frames.", "topics": [], "archived": False}


class Rules(unittest.TestCase):
    def j(self, c=None, f=None, m=None, block=None):
        return HI.judge(c or cand(), facts(**(f or ADDON_335)), {**META, **(m or {})}, block or {})

    def test_listed_addon(self):
        v = self.j()
        self.assertEqual(v["verdict"], "listed", v)
        e = v["entry"]
        self.assertEqual((e["builds"], e["type"], e["category"], e["licence"]), (["3.3.5a"], "addon", "addons", "MIT"))
        self.assertEqual(e["summary"], "An addon for the 3.3.5a client.")
        self.assertEqual(e["description"], "Tidy raid frames.")

    def test_toc_decides_the_build(self):
        v = self.j(f={"tocs": [{"interface": "11200"}, {"interface": "20400"}]})
        self.assertEqual(v["entry"]["builds"], ["1.12", "2.4.3"])
        for n, b in (("40300", "4.3.4"), ("50400", "5.4.8")):
            self.assertEqual(self.j(f={"tocs": [{"interface": n}]})["entry"]["builds"], [b])
        v = self.j(f={"tocs": [{"interface": "110002"}]})
        self.assertEqual(v["verdict"], "excluded")
        self.assertIn("another client build", v["reason"])
        v = self.j(c=cand(origin="seed", builds_given=["3.3.5a"]), f={"tocs": [{"interface": "11200"}]})
        self.assertEqual(v["verdict"], "review")
        v = self.j(c=cand(origin="seed", builds_given=["1.12"]), f={"tocs": [{"interface": "11200"}, {"interface": "30300"}]})
        self.assertEqual(v["entry"]["builds"], ["1.12"])          # the curated build narrows a multi-TOC addon

    def test_no_game_data(self):
        v = self.j(f={**ADDON_335, "game_data": ["Textures/icon.blp"]})
        self.assertEqual(v["verdict"], "excluded")
        self.assertIn("game-format", v["reason"])
        for name in ("hd-client-patch", "wotlk-repack", "full-client-download"):
            v = self.j(c=cand(f"https://github.com/bob/{name}"))
            self.assertEqual(v["verdict"], "excluded", name)
        self.assertTrue(HI.GAME_DATA_EXT.search("World/Maps/x.adt") and HI.GAME_DATA_EXT.search("patch-4.MPQ"))
        self.assertFalse(HI.GAME_DATA_EXT.search("art/icon.tga"))

    def test_no_binaries(self):
        v = self.j(f={**ADDON_335, "binaries": ["release/FrameKit.zip"]})
        self.assertEqual(v["verdict"], "excluded")
        self.assertIn("binaries", v["reason"])

    def test_nothing_paid(self):
        for desc in ("A VIP system for your server", "Donation shop NPC", "PayPal payments for realms", "cash shop"):
            self.assertEqual(self.j(m={"description": desc})["verdict"], "excluded", desc)
        self.assertEqual(self.j(f={**ADDON_335, "readme": "Get the premium version on our site"})["verdict"], "excluded")
        v = self.j(f={**ADDON_335, "readme": "Support me on Patreon"})
        self.assertEqual(v["verdict"], "review")
        self.assertEqual(self.j(c=cand(origin="seed", builds_given=["3.3.5a"]),
                                f={**ADDON_335, "readme": "Support me on Patreon"})["verdict"], "listed")

    def test_no_chumpton(self):
        self.assertEqual(self.j(c=cand("https://github.com/Chumpton/frames"))["verdict"], "excluded")
        self.assertEqual(self.j(f={**ADDON_335, "readme": "Thanks to chumpton for the idea"})["verdict"], "excluded")

    def test_no_decompiled(self):
        for d in ("Built from wowdecomp", "Waystone-based client", "decompiled client source"):
            v = self.j(m={"description": d})
            self.assertEqual(v["verdict"], "excluded", d)
            self.assertIn("wowdecomp", v["reason"])
        self.assertEqual(self.j(f={**ADDON_335, "decomp_files": ["db.i64"]})["verdict"], "excluded")
        self.assertEqual(self.j(f={**ADDON_335, "readme": "Port of the WOWDECOMP tree"})["verdict"], "excluded")

    def test_no_bots_or_cheats(self):
        for d in ("Lua unlocker for 3.3.5a", "fishing bot", "speedhack and teleport", "Warden bypass"):
            self.assertEqual(self.j(m={"description": d})["verdict"], "excluded", d)
        self.assertEqual(self.j(c=cand("https://github.com/azerothcore/mod-anticheat"), f={"conf_dist": True, "cpp": 9},
                                m={"description": "Anticheat for AzerothCore"})["verdict"], "listed")

    def test_licence(self):
        v = self.j(f={**ADDON_335, "licence": "", "licence_file": ""})
        self.assertEqual(v["verdict"], "needs_licence")
        v = self.j(f={**ADDON_335, "licence": "NONFREE"})
        self.assertEqual(v["verdict"], "excluded")
        v = self.j(f={**ADDON_335, "licence": ""}, m={"licence": "GPL-3.0"})
        self.assertEqual(v["entry"]["licence"], "GPL-3.0")
        self.assertEqual(HI.classify_licence("MIT License\n\nPermission is hereby granted, free of charge, to any"), "MIT")
        self.assertEqual(HI.classify_licence("GNU GENERAL PUBLIC LICENSE\n Version 3, 29 June 2007"), "GPL-3.0")
        self.assertEqual(HI.classify_licence("Attribution-NonCommercial 4.0"), "NONFREE")
        self.assertEqual(HI.spdx("NOASSERTION"), "")

    def test_discovered_need_signal(self):
        self.assertEqual(self.j(m={"stars": 1})["verdict"], "excluded")
        self.assertEqual(self.j(m={"stars": None})["verdict"], "excluded")
        self.assertEqual(self.j(c=cand(origin="submitted", builds_given=["3.3.5a"]), m={"stars": 0})["verdict"], "listed")
        # a name match alone is not enough: "tbc" is also a bank
        v = HI.judge(cand("https://github.com/bank/tbc-sdk", hint_builds=["2.4.3"]), facts(), {**META, "description": "SDK"}, {})
        self.assertEqual(v["verdict"], "excluded")

    def test_server_side_builds_and_types(self):
        v = self.j(c=cand("https://github.com/bob/mod-boss-rush"), f={"conf_dist": True, "cpp": 12},
                   m={"description": "Boss rush mode for AzerothCore"})
        e = v["entry"]
        self.assertEqual((e["builds"], e["type"], e["category"], e["needs"]), (["3.3.5a"], "module", "encounters", "AzerothCore"))
        v = self.j(c=cand("https://github.com/bob/vanilla-events"), f={"lua": 5},
                   m={"description": "Eluna event scripts for vmangos 1.12.1 realms"})
        self.assertEqual((v["entry"]["builds"], v["entry"]["type"]), (["1.12"], "lua"))
        v = self.j(c=cand("https://github.com/bob/emu"), f={"cmake": True, "core_dirs": True, "cpp": 900,
                                                           "readme": "A 5.4.8 server emulator"}, m={"description": ""})
        self.assertEqual((v["entry"]["builds"], v["entry"]["type"], v["entry"]["category"]), (["5.4.8"], "core", "presets"))

    def test_blocklist(self):
        block = {"owners": [{"owner": "evil", "reason": "nope"}], "repos": [{"repo": "https://github.com/alice/frame-kit",
                                                                            "reason": "asked to be removed"}],
                 "patterns": [{"pattern": "resocket", "reason": "lure"}]}
        self.assertEqual(self.j(block=block)["reason"], "asked to be removed")
        self.assertEqual(self.j(c=cand("https://github.com/Evil/x"), block=block)["reason"], "nope")
        self.assertEqual(self.j(c=cand("https://github.com/x/resocket-y"), block=block)["reason"], "lure")
        real = HI.read_json(HI.BLOCKLIST, {})
        self.assertIn("chumpton", [o["owner"].lower() for o in real["owners"]])
        self.assertIn("wowdecomp", [o["owner"].lower() for o in real["owners"]])


class Display(unittest.TestCase):
    def test_banned_words(self):
        for s in ("World of Warcraft", "WoW addon", "wow", "MalfurionWoW", "WowDevTools", "warcraft", "Lich King",
                  "Blizzard", "WOW", "my-wow-addon", "BlizzardInterfaceCode"):
            self.assertTrue(H.banned(s), s)
        for s in ("WotLK", "Wrath", "wowing", "Glowworm", "Workshop", "flow", "Leyline"):
            self.assertFalse(H.banned(s), s)

    def test_clean_name_and_scrub(self):
        self.assertEqual(H.clean_name("WoW-Spell-Editor"), "Spell-Editor")
        self.assertEqual(H.clean_name("wow-vanilla-gearmenu"), "vanilla-gearmenu")
        self.assertEqual(H.clean_name("|cff33ffccpf|rUI"), "pfUI")
        self.assertEqual(H.clean_name("mangos-wotlk"), "mangos-wotlk")
        self.assertEqual(H.scrub("An addon for World of Warcraft"), "An addon for the game")
        self.assertEqual(H.scrub("An experimental WoW emulator in Rust"), "An experimental emulator in Rust")
        self.assertEqual(H.scrub("Vanilla WoW 1.12.1 and Turtle WoW addon"), "Vanilla 1.12.1 and Turtle addon")
        self.assertEqual(H.scrub("ElvUI for World of Warcraft - Wrath of the Lich King (3.3.5a)"), "ElvUI for the game - Wrath (3.3.5a)")
        self.assertEqual(HI.humanize("mod-llm-guide"), "LLM Guide")
        self.assertEqual(HI.display_name(cand("https://github.com/TrinityTBC/core"), {}), "TrinityTBC core")
        self.assertEqual(HI.display_name(cand("https://github.com/fondlez/wow-sounds"), {}), "Sounds")
        self.assertFalse(H.banned(H.scrub("WoW Lich King Blizzard warcraft")))

    def test_entries_never_show_brand_words(self):
        v = HI.judge(cand("https://github.com/alice/WoW-FrameKit"), facts(**ADDON_335),
                     {**META, "description": "The best WoW frames for World of Warcraft"}, {})
        e = v["entry"]
        self.assertFalse(H.banned(H.visible_text(e)), e)
        self.assertEqual(e["name"], "FrameKit")
        v = HI.judge(cand("https://github.com/MalfurionWoW/frames"), facts(**ADDON_335), META, {})
        self.assertEqual(v["verdict"], "review")

    def test_validate_index_catches_brand_words(self):
        e = HI.judge(cand(), facts(**ADDON_335), META, {})["entry"]
        e["score"] = 1.0
        doc = {"format": 2, "entries": [e]}
        self.assertEqual(H.validate_index(doc), [])
        bad = dict(e, name="WoW Frames")
        self.assertTrue(any("brand" in p for p in H.validate_index({"format": 2, "entries": [bad]})))
        bad = dict(e, licence="")
        self.assertTrue(H.validate_index({"format": 2, "entries": [bad]}))
        bad = dict(e, description="<script>")
        self.assertTrue(H.validate_index({"format": 2, "entries": [bad]}))


class Submissions(unittest.TestCase):
    def test_parse_issue(self):
        body = ("### Repo link\n\nhttps://github.com/alice/frame-kit\n\n### Client build\n\n1.12.1\n\n"
                "### Category\n\nAddons and UI\n\n### A short note for the reviewers\n\n_No response_\n")
        self.assertEqual(HI.parse_issue(body), {"repo": "https://github.com/alice/frame-kit", "build": "1.12",
                                                "category": "addons"})

    def test_canonical(self):
        a = H.canonical("https://github.com/Alice/Frame-Kit.git")
        b = H.canonical("https://www.github.com/alice/frame-kit/tree/main/src")
        self.assertEqual(a["key"], b["key"])
        self.assertEqual(a["url"], "https://github.com/Alice/Frame-Kit")
        self.assertIsNone(H.canonical("https://example.com/a/b"))
        self.assertIsNone(H.canonical("https://github.com/topics/wow"))
        self.assertIsNone(H.canonical("javascript:alert(1)"))
        self.assertEqual(H.canonical("https://codeberg.org/bob/x")["forge"], "codeberg")


class Pipeline(unittest.TestCase):
    """build() end to end with a fake API and probe, in a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hubidx-test-")
        self.saved = {k: getattr(HI, k) for k in ("SEEDS", "CANDIDATES", "BLOCKLIST", "HOLDING", "CACHE", "INDEX")}
        for k in self.saved:
            setattr(HI, k, os.path.join(self.tmp, k.lower() + ".json"))
        HI.write_json(HI.SEEDS, {"seeds": [
            {"repo": "https://github.com/core/emu", "builds": ["1.12"], "category": "presets", "type": "core",
             "name": "Emu", "description": "A server core, curated."},
            {"repo": "https://github.com/x/bet", "skip": "wagering, left out by choice"},
            {"repo": "https://github.com/x/nolic", "skip": "no licence file in the repo"}]})
        HI.write_json(HI.CANDIDATES, {"candidates": [
            {"repo": "https://github.com/alice/frame-kit", "stars": 40, "builds": ["3.3.5a"], "description": "Frames."},
            {"repo": "https://github.com/mirror/frame-kit", "stars": 5, "builds": ["3.3.5a"], "description": "Frames."},
            {"repo": "https://github.com/bob/tiny", "stars": 1, "builds": ["3.3.5a"]},
            {"repo": "https://github.com/bob/wotlk-repack", "stars": 90, "builds": ["3.3.5a"]},
            {"repo": "https://github.com/carol/delisted", "stars": 90, "builds": ["3.3.5a"]}]})
        HI.write_json(HI.BLOCKLIST, {"owners": [], "repos": [], "patterns": []})
        self.approved = os.path.join(self.tmp, "approved.json")
        HI.write_json(self.approved, {"format": 1,
                                      "approved": [{"id": "x", "repo": "https://github.com/dave/sounds", "build": "2.4.3",
                                                    "category": "audio"}],
                                      "delisted": [{"id": "y", "repo": "https://github.com/carol/delisted"}]})

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(HI, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    class NoApi:
        calls = 0

        def ok(self):
            return False

        def issues(self, slug):
            return []

    def probe(self, url, cache):
        if url.endswith("/emu"):
            return facts(cmake=True, core_dirs=True, cpp=500, licence="GPL-2.0")
        if url.endswith("/nolic"):
            return facts(licence="", licence_file="", lua=3, readme="Eluna scripts for AzerothCore")
        if url.endswith("/sounds"):
            return facts(lua=1, readme="Sound pack for 2.4.3 realms", licence="CC0-1.0")
        return facts(**ADDON_335)

    def run_build(self):
        rc = HI.build(1, self.approved, "", [], "", api=self.NoApi(), probe_fn=self.probe)
        self.assertEqual(rc, 0)
        with open(HI.INDEX, "rb") as f:
            return f.read()

    def test_end_to_end(self):
        first = self.run_build()
        doc = json.loads(first)
        self.assertEqual(H.validate_index(doc), [])
        repos = [e["repo"] for e in doc["entries"]]
        self.assertEqual(repos, ["https://github.com/alice/frame-kit", "https://github.com/dave/sounds",
                                 "https://github.com/core/emu"])
        by = {e["repo"]: e for e in doc["entries"]}
        self.assertEqual(by["https://github.com/dave/sounds"]["source"], "submitted")
        self.assertEqual(by["https://github.com/dave/sounds"]["builds"], ["2.4.3"])
        self.assertEqual(by["https://github.com/dave/sounds"]["category"], "audio")
        self.assertEqual(by["https://github.com/core/emu"]["summary"], "A server core, curated.")
        hold = HI.read_json(HI.HOLDING, {})
        reasons = {r["repo"]: r["reason"] for r in hold["excluded"]}
        self.assertIn("same project as https://github.com/alice/frame-kit", reasons["https://github.com/mirror/frame-kit"])
        self.assertIn("below the bar", reasons["https://github.com/bob/tiny"])
        self.assertIn("repack", reasons["https://github.com/bob/wotlk-repack"])
        self.assertEqual(reasons["https://github.com/carol/delisted"], "delisted by an admin")
        self.assertEqual(reasons["https://github.com/x/bet"], "wagering, left out by choice")
        self.assertEqual([r["repo"] for r in hold["needs_licence"]], ["https://github.com/x/nolic"])   # re-checked
        # deterministic: the same input gives the same bytes
        self.assertEqual(self.run_build(), first)
        self.assertNotIn("generated", doc)


class CheckedIn(unittest.TestCase):
    """The index in the repo passes the rules, and every entry is spot-checked."""

    def test_index(self):
        doc = HI.read_json(os.path.join(HI.REPO, "stream", "hub", "community-index.json"), None)
        self.assertIsNotNone(doc)
        self.assertEqual(H.validate_index(doc), [])
        es = doc["entries"]
        self.assertGreaterEqual(len(es), 100)
        self.assertLessEqual(len(es), 250)
        for b in H.BUILDS:
            self.assertTrue(any(b in e["builds"] for e in es), b)
        block = HI.read_json(HI.BLOCKLIST, {})
        for e in es:
            text = json.dumps(e).lower()
            self.assertNotIn("chumpton", text)
            self.assertFalse(HI.DECOMP_RE.search(text), e["repo"])
            self.assertNotIn(e["owner"].lower(), {o["owner"].lower() for o in block["owners"]}, e["repo"])
            self.assertNotIn(e["repo"].lower(), {r["repo"] for r in block["repos"]})
            self.assertFalse(HI.MONEY_RE.search(e["name"] + " " + e.get("description", "")), e["repo"])
            self.assertFalse(HI.REPACK_RE.search(e["name"] + " " + e.get("description", "")), e["repo"])
            self.assertIn(e["licence"], H.OPEN_LICENCES)
        hold = HI.read_json(HI.HOLDING, None)
        self.assertEqual(set(hold), {"format", "needs_licence", "review", "excluded"})
        listed = {e["repo"] for e in es}
        for k in ("needs_licence", "review", "excluded"):
            self.assertFalse(listed & {r["repo"] for r in hold[k]}, k)


if __name__ == "__main__":
    unittest.main()
