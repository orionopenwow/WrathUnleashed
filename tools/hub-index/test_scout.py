#!/usr/bin/env python3
"""The scout (tools/hub-index/scout.py) against fakes: GitHub's API, Codeberg, GitLab, r/wowservers' RSS and JSON
feeds and the git probe. No network.

    python3 -I tools/hub-index/test_scout.py
"""
import datetime
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("scout", os.path.join(HERE, "scout.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
HI, H = S.HI, S.H
TODAY = datetime.date(2026, 10, 30)


def gh(owner, name, stars, created, desc="", lic="MIT", topics=(), pushed="2026-10-29"):
    return {"html_url": f"https://github.com/{owner}/{name}", "stargazers_count": stars, "created_at": created + "T10:00:00Z",
            "pushed_at": pushed + "T10:00:00Z", "description": desc, "topics": list(topics), "archived": False,
            "fork": False, "private": False, "license": {"spdx_id": lic} if lic else None}


NEW = [
    gh("alice", "leyline-web-viewer", 40, "2026-10-20", "A WebGPU viewer for 3.3.5a realms in the browser"),
    gh("bob", "realm-panel", 25, "2026-10-18", "A control panel for AzerothCore 3.3.5a realms"),
    gh("carol", "client-src", 30, "2026-10-21", "Client sources for 3.3.5a"),
    gh("x1", "wotlk-hd-launcher", 17, "2026-10-24", "Best HD launcher"),
    gh("x2", "wotlk-hd-launcher-2026", 17, "2026-10-25", "Best HD launcher"),
    gh("x3", "hd-launcher-wotlk", 17, "2026-10-26", "Best HD launcher"),
    gh("freeguy", "azerothcore-wotlk-free", 2, "2026-10-25", "AzerothCore 3.3.5a"),
    gh("dave", "realm-booster", 12, "2026-10-22", "Realm booster for 3.3.5a"),
]
RISERS = [gh("erin", "mod-companions", 120, "2025-01-01", "Companion bots for AzerothCore 3.3.5a", topics=["azerothcore-module"])]
FRANK = gh("frank", "mobile-realm-client", 9, "2026-10-27", "An Android client for 3.3.5a realms")
README = {
    "alice/leyline-web-viewer": "Runs in your browser with WebGPU. Host it with docker-compose.",
    "bob/realm-panel": "A panel.",
    "carol/client-src": "This code was decompiled from the game client binary.",
    "x1/wotlk-hd-launcher": "Download the latest version from Releases. Password: 1234",
    "x2/wotlk-hd-launcher-2026": "Download the latest version from Releases. Password: 1234",
    "x3/hd-launcher-wotlk": "Download the latest version from Releases. Password: 1234",
    "freeguy/azerothcore-wotlk-free": "Download from Releases.",
    "dave/realm-booster": "Download it from the Releases page and run as administrator.",
    "erin/mod-companions": "Companions that fight beside you, for AzerothCore 3.3.5a.",
    "frank/mobile-realm-client": "An Android app to play on your 3.3.5a realm.",
    "gina/vanilla-sky-addon": "An addon.",
}
RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>I made a mobile client for my realm</title>
<link href="https://www.reddit.com/r/wowservers/comments/abc123/i_made_a_mobile_client/"/>
<content type="html">&lt;p&gt;Source: &lt;a href="https://github.com/frank/mobile-realm-client"&gt;here&lt;/a&gt;
&lt;img src="https://i.redd.it/screenshot.png"/&gt; &lt;a href="https://preview.redd.it/x.jpg"&gt;pic&lt;/a&gt;&lt;/p&gt;</content></entry>
<entry><title>No links here</title><link href="https://www.reddit.com/r/wowservers/comments/def456/no_links/"/>
<content type="html">just text</content></entry>
<entry><title>Off-site</title><link href="https://evil.example/r/wowservers/comments/zzz/"/>
<content type="html">https://github.com/evil/repo</content></entry>
</feed>"""
TOP = json.dumps({"data": {"children": [
    {"data": {"permalink": "/r/wowservers/comments/ghi789/web_viewer_for_realms/", "title": "Web viewer for realms",
              "url": "https://github.com/alice/leyline-web-viewer", "selftext": "also https://gitlab.com/gl/tools.", "score": 88}},
    {"data": {"permalink": "/r/wowservers/comments/jkl000/screenshot/", "title": "Look at this", "url": "https://i.redd.it/a.png",
              "selftext": "", "score": 300}},
]}}).encode()


class FakeApi(HI.Api):
    def __init__(self, token="", limit_after=None):
        super().__init__(token=token, sleep=lambda s: None)
        self.urls = []
        self.limit_after = limit_after

    def get(self, url, accept="application/vnd.github+json"):
        self.urls.append(url)
        gh_ = url.startswith("https://api.github.com/")
        if gh_ and self.limited:
            return 429, None, {}
        if url == "https://api.github.com/repos/azerothcore/azerothcore-wotlk":
            return 200, {"full_name": "azerothcore/azerothcore-wotlk"}, {}
        if url.startswith("https://api.github.com/search/repositories?"):
            n = sum(1 for u in self.urls if u.startswith("https://api.github.com/search/"))
            if self.limit_after is not None and n > self.limit_after:
                self.limited = True
                return 403, None, {"X-RateLimit-Remaining": "0"}
            q = url.split("q=", 1)[1]
            return 200, {"items": NEW if "created" in q else RISERS if "pushed" in q else []}, {}
        if url == "https://api.github.com/repos/frank/mobile-realm-client":
            return 200, FRANK, {}
        if url.startswith("https://api.github.com/repos/"):
            return 404, None, {}
        if url.startswith("https://codeberg.org/api/v1/repos/search?"):
            return 200, {"data": [{"html_url": "https://codeberg.org/gina/vanilla-sky-addon", "stars_count": 4,
                                   "created_at": "2026-10-28T00:00:00Z", "updated_at": "2026-10-29T00:00:00Z",
                                   "description": "A vanilla 1.12.1 addon", "licenses": ["MIT"], "topics": []}]}, {}
        if url.startswith("https://gitlab.com/api/v4/projects?"):
            return 200, [{"web_url": "https://gitlab.com/old/thing", "star_count": 50, "created_at": "2020-01-01T00:00:00Z",
                          "description": "old", "topics": [], "path_with_namespace": "old/thing"}], {}
        return 404, None, {}


class FakeReddit:
    def __init__(self, rss=(200, RSS), top=(200, TOP)):
        self.urls, self.rss, self.top = [], rss, top

    def get(self, url, hosts, cap, headers=None):
        self.urls.append((url, dict(headers or {})))
        if url == S.REDDIT_FEEDS[0]:
            return self.rss[0], self.rss[1], {}
        if url == S.REDDIT_FEEDS[1]:
            return self.top[0], self.top[1], {}
        return 0, b"", {}


def facts_for(url, files_n=40, **kw):
    key = url.split("/", 3)[-1]
    f = {"ok": True, "head": "x", "updated": "2026-10-29", "files_n": files_n, "game_data": [], "binaries": [],
         "decomp_files": [], "cpp": 10, "lua": 0, "conf_dist": False, "cmake": True, "core_dirs": False, "docker": False,
         "licence": "MIT", "licence_file": "LICENSE", "readme": README.get(key, ""), "tocs": []}
    f.update(kw)
    return f


PROBED = []


def probe(url, cache):
    PROBED.append(url)
    key = url.split("/", 3)[-1]
    if key == "bob/realm-panel":
        return facts_for(url, licence="NONFREE")                  # "MIT License (with Additional Restriction)"
    if key.startswith(("x1/", "x2/", "x3/", "dave/")):
        return facts_for(url, files_n=2, cpp=0, cmake=False)
    return facts_for(url)


class ScoutRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scout-test-")
        self.saved = (HI.CANDIDATES, HI.CACHE, S.STATE)
        HI.CANDIDATES = os.path.join(self.tmp, "candidates.json")
        HI.CACHE = os.path.join(self.tmp, "probes.json")
        S.STATE = os.path.join(self.tmp, "scout-state.json")
        HI.write_json(HI.CANDIDATES, {"format": 1, "candidates": [
            {"repo": "https://github.com/erin/mod-companions", "via": ["github:topic:azerothcore-module"], "builds": ["3.3.5a"],
             "stars": 50}]})
        HI.write_json(S.STATE, {"format": 1, "last_run": "2026-10-23", "repos": {
            "https://github.com/erin/mod-companions": {"first_seen": "2026-10-16", "stars": [["2026-10-23", 50]]}}, "reddit": {}})
        self.out = os.path.join(self.tmp, "scout")
        PROBED.clear()

    def tearDown(self):
        HI.CANDIDATES, HI.CACHE, S.STATE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_scout(self, api=None, reddit=None, probe_n=40):
        self.api = api or FakeApi()
        self.reddit = reddit or FakeReddit()
        sc = S.Scout(TODAY, api=self.api, fetcher=self.reddit, probe_fn=probe, sleep=lambda s: None)
        self.assertEqual(S.run(TODAY, sc, probe_n, out_dir=self.out), 0)
        with open(os.path.join(self.out, "2026-10-30.md"), encoding="utf-8") as f:
            self.md = f.read()
        self.state = HI.read_json(S.STATE, {})
        self.pool = {r["repo"]: r for r in HI.read_json(HI.CANDIDATES, {})["candidates"]}
        return sc

    def verdict(self, repo):
        return self.state["repos"][repo.lower()]["verdict"], self.state["repos"][repo.lower()]["reason"]

    def test_vetting_with_the_index_rules(self):
        self.run_scout()
        self.assertEqual(self.verdict("https://github.com/alice/leyline-web-viewer")[0], "index")
        v, why = self.verdict("https://github.com/bob/realm-panel")
        self.assertEqual(v, "rejected")
        self.assertIn("rider", why)                                      # MIT on the forge, a rider in the file
        v, why = self.verdict("https://github.com/carol/client-src")
        self.assertEqual(v, "rejected")
        self.assertIn("decompiled", why)

    def test_lures(self):
        self.run_scout()
        for r in ("x1/wotlk-hd-launcher", "x2/wotlk-hd-launcher-2026", "x3/hd-launcher-wotlk"):
            v, why = self.verdict("https://github.com/" + r)
            self.assertEqual(v, "lure", r)
            self.assertIn("exactly 17 stars", why)
        v, why = self.verdict("https://github.com/freeguy/azerothcore-wotlk-free")
        self.assertEqual(v, "lure")
        self.assertIn("look-alike of https://github.com/azerothcore/azerothcore-wotlk", why)
        v, why = self.verdict("https://github.com/dave/realm-booster")
        self.assertEqual(v, "lure")
        self.assertIn("release-only", why)
        lures = self.md.split("## Suspected lures")[1]
        for r in ("x1/wotlk-hd-launcher", "freeguy/azerothcore-wotlk-free", "dave/realm-booster"):
            self.assertIn("https://github.com/" + r, lures)

    def test_strong_readme_patterns_alone(self):
        f = {"key": "k", "name": "thing", "owner": "o", "age": 400}
        self.assertIn("antivirus", S.lure_reason(f, {"ok": True, "readme": "Please disable your antivirus first", "cpp": 5}, {}, {}))
        self.assertEqual(S.lure_reason(f, {"ok": True, "readme": "Download it from Releases.", "cpp": 50, "files_n": 300}, {}, {}), "")

    def test_reddit_mentions_read_only(self):
        self.run_scout()
        fetched = [u for u, _h in self.reddit.urls]
        self.assertEqual(fetched, list(S.REDDIT_FEEDS))                  # the two feeds and nothing else: no images
        self.assertTrue(all(h.get("User-Agent", "").startswith("leyline-scout/") for _u, h in self.reddit.urls))
        self.assertFalse(any("redd.it" in u for u in self.api.urls))
        sec = self.md.split("## Reddit mentions")[1].split("## ")[0]
        self.assertIn("(https://www.reddit.com/r/wowservers/comments/abc123/i_made_a_mobile_client/)", sec)
        self.assertIn("(https://www.reddit.com/r/wowservers/comments/ghi789/web_viewer_for_realms/) (88 points)", sec)
        self.assertIn("frank/mobile-realm-client", sec)
        self.assertNotIn("def456", sec)                                  # no links: not a mention
        self.assertNotIn("jkl000", sec)                                  # an image post: not a mention
        self.assertNotIn("evil", self.md)                                # a link off Reddit's own host is ignored
        self.assertIn("https://github.com/frank/mobile-realm-client", self.pool)
        self.assertIn("scout:reddit", self.pool["https://github.com/frank/mobile-realm-client"]["via"])
        self.assertIn("https://www.reddit.com/r/wowservers/comments/abc123/i_made_a_mobile_client/", self.state["reddit"])

    def test_reddit_refusing_is_fine(self):
        self.run_scout(reddit=FakeReddit(rss=(403, b""), top=(429, b"")))
        self.assertIn("Reddit new (RSS): HTTP 403, skipped today.", self.md)
        self.assertIn("Reddit top of the week (JSON): HTTP 429, skipped today.", self.md)
        self.assertIn("No posts linking a repo today", self.md)

    def test_merge_tags_and_digest(self):
        self.run_scout()
        for h in ("## Top 15 new", "## Top risers", "## Reddit mentions", "## Merge candidates by tag", "## Rejected",
                  "## Suspected lures"):
            self.assertIn(h, self.md)
        tags = self.md.split("## Merge candidates by tag")[1].split("## Rejected")[0]
        self.assertIn("### web client", tags)
        self.assertRegex(tags, r"alice/leyline-web-viewer\]\(https://github.com/alice/leyline-web-viewer\) \(40 stars, index\): "
                               r"'browser', 'webgpu' in its description|'webgpu'")
        self.assertIn("### realm hosting", tags)
        self.assertIn("'docker-compose' in its README", tags)
        self.assertIn("### mobile", tags)
        self.assertIn("### bots", tags)
        self.assertNotIn("wotlk-hd-launcher", tags)                      # lures are never merge candidates
        risers = self.md.split("## Top risers")[1].split("## ")[0]
        self.assertIn("erin/mod-companions", risers)
        self.assertIn("+70.0", risers)                                   # 50 -> 120 stars in a week
        rej = self.md.split("## Rejected")[1].split("## ")[0]
        self.assertIn("bob/realm-panel", rej)
        self.assertIn("carol/client-src", rej)

    def test_pool_and_state(self):
        self.run_scout()
        for r in ("alice/leyline-web-viewer", "frank/mobile-realm-client", "erin/mod-companions"):
            self.assertIn("https://github.com/" + r, self.pool, r)
        self.assertIn("https://codeberg.org/gina/vanilla-sky-addon", self.pool)
        self.assertIn("scout:github:new", self.pool["https://github.com/alice/leyline-web-viewer"]["via"])
        for r in ("bob/realm-panel", "carol/client-src", "x1/wotlk-hd-launcher", "freeguy/azerothcore-wotlk-free",
                  "dave/realm-booster"):
            self.assertNotIn("https://github.com/" + r, self.pool, r)      # rejected and lures never join the pool
        self.assertNotIn("https://gitlab.com/old/thing", self.pool)       # GitLab: only the last 30 days
        self.assertEqual(self.state["repos"]["https://github.com/erin/mod-companions"]["stars"],
                         [["2026-10-23", 50], ["2026-10-30", 120]])
        self.assertEqual(self.state["last_run"], "2026-10-30")

    def test_deterministic(self):
        self.run_scout()
        first = self.md
        self.tearDown()
        self.setUp()
        self.run_scout()
        self.assertEqual(self.md, first)

    def test_probe_budget(self):
        self.run_scout(probe_n=3)
        self.assertEqual(len(PROBED), 3)
        self.assertIn("not probed this run", self.md)

    def test_without_a_token_and_out_of_calls(self):
        self.run_scout(api=FakeApi(token="", limit_after=3))
        self.assertIn("rate limit ran out", self.md)
        self.assertIn("no token", self.md)
        n = sum(1 for u in self.api.urls if u.startswith("https://api.github.com/search/"))
        self.assertEqual(n, 4)                                           # stops asking once GitHub says no
        self.assertTrue(os.path.exists(os.path.join(self.out, "2026-10-30.md")))

    def test_parsers_refuse_odd_input(self):
        self.assertEqual(S.parse_reddit_rss(b'<!DOCTYPE x [<!ENTITY a "b">]><feed/>'), [])
        self.assertEqual(S.parse_reddit_rss(b"not xml"), [])
        self.assertEqual(S.parse_reddit_json(b"{"), [])
        self.assertEqual(S._post_links("see https://github.com/a/b, and https://github.com/topics/x"), ["https://github.com/a/b"])

    def test_markdown_is_escaped(self):
        self.assertEqual(S.md("a|b [x](javascript:alert(1)) <img>"), "a\\|b \\[x\\](javascript:alert(1)) img")


class Workflow(unittest.TestCase):
    def test_scout_workflow(self):
        for path in (os.path.join(HI.REPO, ".github", "workflows", "scout.yml"),
                     os.path.join(HI.REPO, "tools", "github-workflows", "scout.yml")):
            with open(path, encoding="utf-8") as f:
                wf = f.read()
            self.assertIn("scout.py run", wf)
            self.assertIn("test_scout.py", wf)
            self.assertIn('--title "Scout digest', wf)
            self.assertNotIn("gh pr merge", wf)
            self.assertNotRegex(wf, r"git push[^\n]*\bmain\b")
            self.assertEqual(set(__import__("re").findall(r"secrets\.([A-Za-z_]+)", wf)), {"GITHUB_TOKEN"})
            self.assertIn("docs/scout", wf)
            self.assertIn("tools/hub-index/scout-state.json", wf)
            self.assertIn("tools/hub-index/candidates.json", wf)


if __name__ == "__main__":
    unittest.main()
