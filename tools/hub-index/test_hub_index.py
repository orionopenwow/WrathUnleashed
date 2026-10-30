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

    def test_only_keeps_the_rest_of_holding_and_builds_keep_thumbs(self):
        self.run_build()
        doc = HI.read_json(HI.INDEX, {})
        for e in doc["entries"]:
            if e["repo"].endswith("/frame-kit"):
                e.update(thumb="/wrath/art/hub-thumbs/alice__frame-kit.webp", thumb_credit=HI.THUMB_CREDIT)
        HI.write_json(HI.INDEX, doc)
        keys = H.ENTRY_KEYS
        H.ENTRY_KEYS = set(keys) | set(HI.THUMB_FIELDS)
        try:
            self.assertEqual(HI.build(1, self.approved, "", ["alice/frame-kit"], "", api=self.NoApi(), probe_fn=self.probe), 0)
        finally:
            H.ENTRY_KEYS = keys
        e = {e["repo"]: e for e in HI.read_json(HI.INDEX, {})["entries"]}["https://github.com/alice/frame-kit"]
        self.assertEqual(e["thumb"], "/wrath/art/hub-thumbs/alice__frame-kit.webp")
        hold = HI.read_json(HI.HOLDING, {})
        self.assertIn("https://github.com/bob/tiny", {r["repo"] for r in hold["excluded"]}, "--only leaves other repos' places")
        self.assertEqual([r["repo"] for r in hold["needs_licence"]], ["https://github.com/x/nolic"])


def entry(repo, **kw):
    c = H.canonical(repo)
    e = {"id": "link:" + c["id"], "name": c["repo"], "author": c["owner"], "owner": c["owner"], "repo": c["url"],
         "forge": "github", "licence": "MIT", "category": "addons", "type": "addon", "builds": ["3.3.5a"],
         "summary": "An addon for the 3.3.5a client.", "description": "", "stars": 10, "updated": "2026-10-01",
         "archived": False, "source": "discovered", "score": 10.0}
    e.update(kw)
    return e


def index(*es):
    return {"format": 2, "policy": "x", "builds": H.BUILDS, "categories": H.CATEGORY_IDS,
            "entries": sorted(es, key=H.entry_order)}


class DailyRefresh(Pipeline):
    """The daily run: refreshes go live, new entries wait, a forge that doesn't answer never wipes an entry."""

    def test_gate(self):
        a, b, c, g = (f"https://github.com/o/{n}" for n in ("a", "b", "c", "g"))
        rel = {"tag": "v2.0", "date": "2026-10-28", "url": a + "/releases/tag/v2.0"}
        base = index(entry(a), entry(b), entry(c), entry(g, stars=3))
        new = index(entry(a, stars=99, updated="2026-10-28", score=30.0, release=rel, name="Renamed"),
                    entry(g, stars=4), entry("https://github.com/o/d"))
        hold = {"excluded": [{"repo": b, "reason": "ships game-format files: x.mpq"},
                             {"repo": c, "reason": "could not read the repo: timeout"}], "review": [], "needs_licence": []}
        doc, wait = HI.gate(base, new, hold)
        self.assertEqual(H.validate_index(doc), [])
        by = {e["repo"]: e for e in doc["entries"]}
        self.assertEqual(sorted(by), [a, c, g])                       # b off (hard rule), c kept, d not added yet
        self.assertEqual((by[a]["stars"], by[a]["updated"], by[a]["score"], by[a]["release"]), (99, "2026-10-28", 30.0, rel))
        self.assertEqual(by[a]["name"], "a", "a rename waits for review")
        self.assertEqual(by[g]["stars"], 4)
        self.assertEqual([r["repo"] for r in wait["new"]], ["https://github.com/o/d"])
        self.assertEqual(wait["changed"], [{"repo": a, "name": "a", "fields": ["name"]}])
        self.assertEqual([r["repo"] for r in wait["kept"]], [c])
        self.assertEqual([r["repo"] for r in wait["removed"]], [b])
        # a release that went away goes away with the refresh
        doc2, _ = HI.gate(doc, index(entry(a, stars=99, updated="2026-10-28", score=30.0), entry(c), entry(g, stars=4)), hold)
        self.assertNotIn("release", {e["repo"]: e for e in doc2["entries"]}[a])
        # a licence that became non-open: off now
        _, w3 = HI.gate(base, index(entry(a), entry(c), entry(g)), {"needs_licence": [{"repo": b, "reason": "no open licence file"}]})
        self.assertEqual([r["repo"] for r in w3["removed"]], [b])

    def test_run_gate_files(self):
        base = os.path.join(self.tmp, "base.json")
        HI.write_json(base, index(entry("https://github.com/o/a")))
        HI.write_json(HI.INDEX, index(entry("https://github.com/o/a", stars=50), entry("https://github.com/o/new")))
        HI.write_json(HI.HOLDING, {"format": 1, "needs_licence": [], "review": [], "excluded": []})
        full, summ = os.path.join(self.tmp, "full.json"), os.path.join(self.tmp, "sum.json")
        self.assertEqual(HI.run_gate(base, full, summ, ""), 0)
        live = HI.read_json(HI.INDEX, {})
        self.assertEqual([(e["name"], e["stars"]) for e in live["entries"]], [("a", 50)])
        self.assertEqual(len(HI.read_json(full, {})["entries"]), 2)
        self.assertEqual(HI.read_json(summ, {})["new"], 1)
        self.assertEqual([r["repo"] for r in HI.read_json(HI.HOLDING, {})["pending_new"]], ["https://github.com/o/new"])

    def test_a_forge_that_does_not_answer_keeps_the_entry(self):
        doc = json.loads(self.run_build())
        before = {e["repo"]: e for e in doc["entries"]}["https://github.com/alice/frame-kit"]

        def flaky(url, cache):
            return {"ok": False, "error": "connection timed out"} if url.endswith("/frame-kit") else self.probe(url, cache)
        self.assertEqual(HI.build(1, self.approved, "", [], "", api=self.NoApi(), probe_fn=flaky), 0)
        after = {e["repo"]: e for e in HI.read_json(HI.INDEX, {})["entries"]}
        self.assertEqual(after["https://github.com/alice/frame-kit"], before)
        self.assertNotIn("https://github.com/mirror/frame-kit", after, "the kept original still wins over its mirror")

    def test_a_run_that_would_wipe_the_index_writes_nothing(self):
        HI.write_json(HI.INDEX, index(*(entry(f"https://github.com/old/m{k}") for k in range(30))))
        before = open(HI.INDEX, "rb").read()
        self.assertEqual(HI.build(1, self.approved, "", [], "", api=self.NoApi(), probe_fn=self.probe), 3)
        self.assertEqual(open(HI.INDEX, "rb").read(), before)
        self.assertEqual(HI.build(1, self.approved, "", [], "", api=self.NoApi(), probe_fn=self.probe, allow_shrink=True), 0)

    def test_release_kept_when_the_api_does_not_answer(self):
        rel = {"tag": "v1.2", "date": "2026-10-20", "url": "https://github.com/alice/frame-kit/releases/tag/v1.2"}

        class Api(self.NoApi):
            def __init__(s, release):
                s.release = release

            def ok(s):
                return True

            def github_repo(s, owner, repo):
                return {"stars": 41, "licence": "MIT", "description": "Frames.", "topics": [], "archived": False}

            def github_release(s, owner, repo):
                return s.release if repo == "frame-kit" else {}
        self.assertEqual(HI.build(1, self.approved, "", [], "", api=Api(rel), probe_fn=self.probe), 0)
        get = lambda: {e["repo"]: e for e in HI.read_json(HI.INDEX, {})["entries"]}["https://github.com/alice/frame-kit"]  # noqa: E731
        self.assertEqual(get()["release"], rel)
        self.assertEqual(get()["stars"], 41)
        HI.build(1, self.approved, "", [], "", api=Api(None), probe_fn=self.probe)          # no answer: kept
        self.assertEqual(get()["release"], rel)
        HI.build(1, self.approved, "", [], "", api=Api({}), probe_fn=self.probe)            # no release any more: gone
        self.assertNotIn("release", get())

    def test_release_meta(self):
        repo = "https://github.com/alice/frame-kit"
        ok = HI.release_meta({"tag_name": "v1.0", "published_at": "2026-10-01T00:00:00Z",
                              "html_url": repo + "/releases/tag/v1.0"}, repo)
        self.assertEqual(ok, {"tag": "v1.0", "date": "2026-10-01", "url": repo + "/releases/tag/v1.0"})
        self.assertEqual(HI.release_meta({"tag_name": "v1", "html_url": "https://evil.example/x"}, repo), {})
        self.assertEqual(HI.release_meta({"tag_name": "v1", "draft": True, "html_url": repo + "/r"}, repo), {})
        self.assertEqual(HI.release_meta({"tag_name": "<b>", "html_url": repo + "/r"}, repo), {})
        bad = index(entry(repo, release={"tag": "v1", "url": "https://github.com/someone/else/releases"}))
        self.assertTrue(any("release url" in p for p in H.validate_index(bad)))

    def test_rate_limit_and_retry(self):
        import io
        import urllib.error
        seen = []

        def opener(req, timeout):
            seen.append(req.full_url)
            if "limited" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 403, "rate", {"X-RateLimit-Remaining": "0"}, io.BytesIO(b""))
            if "flaky" in req.full_url and seen.count(req.full_url) == 1:
                raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, io.BytesIO(b""))

            class R(io.BytesIO):
                status = 200
                headers = {}

                def __enter__(s):
                    return s

                def __exit__(s, *a):
                    return False
            return R(b'{"full_name": "x"}')
        api = HI.Api(token="t", opener=opener, sleep=lambda s: None)
        self.assertEqual(api.get("https://api.github.com/repos/flaky/x")[0], 200, "one retry after a 5xx")
        self.assertEqual(api.get("https://api.github.com/repos/limited/x")[0], 403)
        self.assertTrue(api.limited)
        n = len(seen)
        self.assertEqual(api.get("https://api.github.com/repos/other/y")[0], 429)
        self.assertEqual(len(seen), n, "no more GitHub calls once the limit is used up")
        self.assertEqual(api.get("https://codeberg.org/api/v1/x")[0], 200, "other forges still answer")


class LicencesAndWaivers(unittest.TestCase):
    def test_a_rider_makes_a_licence_not_open(self):
        mit = ("MIT License (with Additional Restriction)\n\nPermission is hereby granted, free of charge, to any person "
               "obtaining a copy of this software...\n\nADDITIONAL RESTRICTION: the Software may not be used, in whole or "
               "in part, as the basis for any commercial video game.")
        self.assertEqual(HI.classify_licence(mit), "NONFREE")
        self.assertEqual(HI.classify_licence("Permission is hereby granted, free of charge, to any person"), "MIT")
        self.assertEqual(HI.classify_licence("Apache License\nVersion 2.0, January 2004\n... Commons Clause ..."), "NONFREE")
        v = HI.judge(cand(), facts(**ADDON_335, licence="NONFREE"), META, {})
        self.assertEqual(v["verdict"], "excluded")

    def test_no_paid_features_is_not_a_paid_version(self):
        self.assertFalse(HI.PAID_STRONG.search("It is free, with no ads and no paid features."))
        self.assertFalse(HI.PAID_STRONG.search("without a paywall"))
        self.assertTrue(HI.PAID_STRONG.search("The paid version adds more zones."))

    def test_a_curated_waiver_covers_only_the_named_files(self):
        c = cand(origin="seed", builds_given=["3.3.5a"],
                 waive=[{"file": "src/scripts/decompile.ts", "why": "reads database script rows"},
                        {"file": "docs/index.mdx", "why": "a docs page"}])
        f = dict(ADDON_335, decomp_files=["src/scripts/decompile.ts"], game_data=["docs/index.mdx"])
        self.assertEqual(HI.judge(c, facts(**f), META, {})["verdict"], "listed")
        f2 = dict(f, game_data=["docs/index.mdx", "Art/x.blp"])
        self.assertIn("game-format", HI.judge(c, facts(**f2), META, {})["reason"])
        nowhy = cand(origin="seed", builds_given=["3.3.5a"], waive=[{"file": "src/scripts/decompile.ts"}])
        self.assertIn("decompiled", HI.judge(nowhy, facts(**f), META, {})["reason"])
        full = dict(ADDON_335, game_data=[f"a{i}.mdx" for i in range(5)])          # a capped list is never waived
        many = cand(origin="seed", builds_given=["3.3.5a"], waive=[{"file": f"a{i}.mdx", "why": "docs"} for i in range(5)])
        self.assertEqual(HI.judge(many, facts(**full), META, {})["verdict"], "excluded")


class ExternalPacks(unittest.TestCase):
    URL = "https://example.org/forum/thread/hd-pack"

    def item(self, **kw):
        x = {"id": HI.external_id(self.URL), "name": "HD Pack", "author": "", "url": self.URL, "category": "graphics",
             "type": HI.EXTERNAL_TYPE, "builds": ["3.3.5a"], "summary": "Sharper textures, from its authors' page.",
             "external": True, "note": HI.EXTERNAL_NOTE}
        x.update(kw)
        return x

    def test_rules(self):
        self.assertEqual(HI.external_problems(self.item()), [])
        bad = {
            "file": dict(url="https://example.org/files/pack.zip"),
            "release asset": dict(url="https://github.com/a/b/releases/download/v1/pack.7z"),
            "file host": dict(url="https://mega.nz/file/abc"),
            "brand": dict(summary="HD textures for World of Warcraft."),
            "number": dict(name="HD Pack 3.3.5a"),
            "flag": dict(external=False),
            "note": dict(note="hosted"),
            "decomp": dict(summary="Built from wowdecomp output."),
            "repack": dict(summary="A full client repack."),
            "paid": dict(summary="Premium pack for donors."),
            "thumb without repo": dict(thumb="/wrath/art/hub-thumbs/a__b.webp", thumb_credit=HI.THUMB_CREDIT),
            "extra": dict(download="https://example.org/x"),
        }
        for why, kw in bad.items():
            x = self.item(**kw)
            if "url" in kw:
                x["id"] = HI.external_id(kw["url"])
            self.assertTrue(HI.external_problems(x), why)
        blocked = {"repos": [{"repo": "https://github.com/bad/pack", "reason": "lure"}]}
        self.assertTrue(HI.external_problems(self.item(repo="https://github.com/bad/pack"), blocked))

    def test_built_from_the_curated_file_and_kept_apart(self):
        tmp = tempfile.mkdtemp(prefix="hubext-")
        saved = HI.EXTERNAL
        try:
            HI.EXTERNAL = os.path.join(tmp, "ext.json")
            HI.write_json(HI.EXTERNAL, {"packs": [
                {"name": "Zeta Pack", "url": self.URL, "summary": "Sharper textures.", "builds": ["3.3.5a"]},
                {"name": "Alpha Pack", "url": "https://example.org/a", "summary": "Better water.",
                 "repo": "https://github.com/Owner/alpha-pack.git"},
                {"name": "Bad", "url": "https://example.org/dl/x.mpq", "summary": "Patch file."}]})
            items, probs = HI.external_items({})
            self.assertEqual([x["name"] for x in items], ["Alpha Pack", "Zeta Pack"])
            self.assertEqual(items[0]["repo"], "https://github.com/Owner/alpha-pack")
            self.assertTrue(all(x["external"] and x["note"] == HI.EXTERNAL_NOTE and x["type"] == "external-pack" for x in items))
            self.assertEqual(len(probs), 1)
            doc = index(entry("https://github.com/o/a"))
            doc["external"] = items
            self.assertEqual(HI.validate(doc), [])
            self.assertEqual(H.validate_index(doc), [], "the hub's own check ignores the separate list")
            doc["external"] = list(reversed(items))
            self.assertTrue(any("canonical order" in p for p in HI.validate(doc)))
        finally:
            HI.EXTERNAL = saved
            shutil.rmtree(tmp, ignore_errors=True)


def _png(w=1200, h=600):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 60, 90)).save(buf, "PNG")
    return buf.getvalue()


def _have_encoder():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_have_encoder(), "Pillow is needed to make test images")
class Thumbs(unittest.TestCase):
    """The thumbs command against a local fake GitHub: host allow-list, magic bytes, size cap, file name, fields."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading
        png = _png()
        routes = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                r = routes.get(self.path)
                if r is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                code, ctype, body, extra = r
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in extra.items():
                    self.send_header(k, v)
                if code == 200 and self.headers.get("If-None-Match") and extra.get("ETag") == self.headers.get("If-None-Match"):
                    pass
                self.end_headers()
                self.wfile.write(body)

        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.port}"
        other = f"http://localhost:{cls.port}"

        def page(img, title="o/r", desc="A tool."):
            return (200, "text/html", (f'<html><head><meta property="og:image" content="{img}" />'
                                       f'<meta property="og:title" content="{title}"><meta property="og:description" '
                                       f'content="{desc}"></head></html>').encode(), {})
        routes.update({
            "/o/good": page(base + "/img/good.png"),
            "/o/offlist": page(other + "/img/good.png"),
            "/o/html": page(base + "/img/fake.png"),
            "/o/big": page(base + "/img/big.png"),
            "/o/hop": page(base + "/img/hop"),
            "/o/brand": page(base + "/img/good.png", title="o/brand: a World of Warcraft addon"),
            "/img/good.png": (200, "image/png", png, {"ETag": '"v1"'}),
            "/img/fake.png": (200, "image/png", b"<html><script>alert(1)</script></html>", {}),
            "/img/big.png": (200, "image/png", png[:8] + b"\0" * (HI.THUMB_MAX_IN + 10), {}),
            "/img/hop": (302, "text/plain", b"", {"Location": other + "/img/good.png"}),
        })
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hubthumb-test-")
        self.saved = {k: getattr(HI, k) for k in ("INDEX", "THUMBS_CACHE", "GENERATED_CARD_HOST")}
        HI.INDEX = os.path.join(self.tmp, "index.json")
        HI.THUMBS_CACHE = os.path.join(self.tmp, "cache.json")
        self.keys = H.ENTRY_KEYS
        H.ENTRY_KEYS = set(H.ENTRY_KEYS) | set(HI.THUMB_FIELDS)
        self.dir = os.path.join(self.tmp, "thumbs")
        self.fetcher = HI.Fetcher(page_base=self.base, page_hosts={"127.0.0.1"}, image_hosts={"127.0.0.1"},
                                  schemes=("http",), timeout=5)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(HI, k, v)
        H.ENTRY_KEYS = self.keys
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_thumbs(self, *names, refresh=False):
        HI.write_json(HI.INDEX, index(*(entry(f"https://github.com/o/{n}") for n in names)))
        self.assertEqual(HI.thumbs(0, [f"o/{n}" for n in names], refresh, self.fetcher, self.dir), 0)
        return {e["repo"].rsplit("/", 1)[1]: e for e in HI.read_json(HI.INDEX, {})["entries"]}

    def test_a_good_image_becomes_a_small_webp_with_its_fields(self):
        es = self.run_thumbs("good")
        path = os.path.join(self.dir, "o__good.webp")
        with open(path, "rb") as f:
            data = f.read()
        self.assertEqual(HI.image_kind(data), "webp")
        self.assertLessEqual(len(data), HI.THUMB_MAX_OUT)
        from PIL import Image
        with Image.open(path) as im:
            self.assertEqual(im.size, HI.THUMB_SIZE)
        self.assertEqual(es["good"]["thumb"], "/wrath/art/hub-thumbs/o__good.webp")
        self.assertEqual(es["good"]["thumb_credit"], "Preview image from the project's GitHub page")
        self.assertEqual(HI.validate(HI.read_json(HI.INDEX, {}), self.dir), [])
        mtime = os.path.getmtime(path)
        self.run_thumbs("good", refresh=True)                         # same image (ETag): the file isn't rewritten
        self.assertEqual(os.path.getmtime(path), mtime)

    def test_only_allowed_hosts_and_real_images_are_kept(self):
        es = self.run_thumbs("offlist", "html", "big", "hop")
        for n in ("offlist", "html", "big", "hop"):
            self.assertNotIn("thumb", es[n], n)
            self.assertFalse(os.path.exists(os.path.join(self.dir, f"o__{n}.webp")), n)
        st, _, _ = self.fetcher.get("https://evil.example/x.png", self.fetcher.image_hosts, 10)
        self.assertEqual(st, 0)
        self.assertFalse(self.fetcher.allowed("http://user:pw@127.0.0.1/x", {"127.0.0.1"}))

    def test_generated_card_text_must_be_clean(self):
        HI.GENERATED_CARD_HOST = "127.0.0.1"
        es = self.run_thumbs("brand", "good")
        self.assertNotIn("thumb", es["brand"])
        self.assertIn("thumb", es["good"])

    def test_fields_wait_until_the_hub_accepts_them(self):
        H.ENTRY_KEYS = self.keys - set(HI.THUMB_FIELDS)
        es = self.run_thumbs("good")
        self.assertNotIn("thumb", es["good"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "o__good.webp")))

    def test_names_magic_and_field_checks(self):
        self.assertEqual(HI.thumb_name("https://github.com/Some-Owner/My.Repo"), "some-owner__my.repo.webp")
        self.assertEqual(HI.thumb_name("https://gitlab.com/a/b"), "")
        self.assertEqual(HI.thumb_name("https://example.org/a/b"), "")
        self.assertEqual(HI.image_kind(b"\x89PNG\r\n\x1a\nxxxx"), "png")
        self.assertEqual(HI.image_kind(b"\xff\xd8\xff\xe0"), "jpeg")
        self.assertEqual(HI.image_kind(b"RIFF\0\0\0\0WEBPVP8 "), "webp")
        self.assertEqual(HI.image_kind(b"<svg xmlns="), "")
        self.assertEqual(HI.image_kind(b"MZ\x90\0"), "")
        e = entry("https://github.com/o/a", thumb="/wrath/art/hub-thumbs/o__other.webp", thumb_credit=HI.THUMB_CREDIT)
        self.assertTrue(HI.thumb_problems(e))
        self.assertTrue(HI.thumb_problems(entry("https://github.com/o/a", thumb="/wrath/art/hub-thumbs/o__a.webp")))
        ok = entry("https://github.com/o/a", thumb="/wrath/art/hub-thumbs/o__a.webp", thumb_credit=HI.THUMB_CREDIT)
        self.assertEqual(HI.thumb_problems(ok), [])
        self.assertIn("missing", " ".join(HI.thumb_problems(ok, self.dir)))


class Workflow(unittest.TestCase):
    def test_daily_with_a_review_gate(self):
        with open(os.path.join(HI.REPO, "tools", "github-workflows", "hub-index.yml"), encoding="utf-8") as f:
            wf = f.read()
        self.assertIn('cron: "17 7 * * *"', wf)
        self.assertIn("hub_index.py gate --base", wf)
        self.assertIn("hub-index/daily", wf)
        self.assertIn("hub-index/review", wf)
        merge = [l for l in wf.splitlines() if "gh pr merge" in l]
        self.assertTrue(merge and all("hub-index/daily" in l or "$DAILY" in l for l in merge), merge)


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
        self.assertLessEqual(set(hold), {"format", "needs_licence", "review", "excluded", "pending_new"})
        self.assertLessEqual({"format", "needs_licence", "review", "excluded"}, set(hold))
        listed = {e["repo"] for e in es}
        for k in ("needs_licence", "review", "excluded"):
            self.assertFalse(listed & {r["repo"] for r in hold[k]}, k)


if __name__ == "__main__":
    unittest.main()
