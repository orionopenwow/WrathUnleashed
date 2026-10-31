"""The Leyline Discord bridge (hosting/discord/wudiscord/bridge.py) against a fake Discord API and a fake AzerothCore
SOAP, both at the urlopen level: no network, no token, nothing posted anywhere. Also runs the game side
(hosting/tests/test_ov_discord.lua on realm/custom/lua_scripts/ov_discord.lua, needs lua5.1) and the install script
(hosting/discord/deploy/discord-up.sh) against a stub systemctl.

    python3 -I hosting/tests/test_discord_bridge.py
"""
import io
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTING = os.path.dirname(HERE)
ROOT = os.path.dirname(HOSTING)
sys.path.insert(0, os.path.join(HOSTING, "discord"))
sys.dont_write_bytecode = True
from wudiscord import bridge as B  # noqa: E402

TOKEN = "FAKE.TOKEN.for-tests-only-0123456789"
SOAP_PASS = "soap-secret-pw"
BRAND = re.compile(r"(?i)world\s+of\s+warcraft|warcraft|\bwow\b|lich\s+king|blizzard")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def http_error(url, code, body=b""):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(body))


class FakeDiscord:
    """The few Discord REST routes the bridge uses."""

    def __init__(self, channels=("100", "200")):
        self.messages = {c: [] for c in channels}
        self.next_id = 1000
        self.requests = []
        self.posted = []           # (channel, payload)
        self.rate_limit_next = 0
        self.down = False

    def add(self, channel, content, author_id="5", username="sam", bot=False, **extra):
        self.next_id += 1
        m = {"id": str(self.next_id), "type": 0, "content": content,
             "author": {"id": author_id, "username": username, "bot": bot}, "mentions": [], "attachments": []}
        m.update(extra)
        self.messages[channel].append(m)
        return m

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.down:
            raise urllib.error.URLError("refused")
        if req.get_header("Authorization") != "Bot " + TOKEN:
            raise http_error(req.full_url, 401)
        if self.rate_limit_next:
            self.rate_limit_next -= 1
            raise http_error(req.full_url, 429, b'{"retry_after": 0.25}')
        u = urllib.parse.urlsplit(req.full_url)
        path, q = u.path.split("/api/v10", 1)[-1], dict(urllib.parse.parse_qsl(u.query))
        if path == "/users/@me":
            return Resp(json.dumps({"id": "999", "username": "Leyline", "bot": True}).encode())
        m = re.match(r"^/channels/(\d+)/messages$", path)
        if not m or m.group(1) not in self.messages:
            raise http_error(req.full_url, 404)
        ch = m.group(1)
        if req.get_method() == "POST":
            payload = json.loads(req.data)
            self.posted.append((ch, payload))
            self.add(ch, payload["content"], author_id="999", username="Leyline", bot=True)
            return Resp(b"{}")
        msgs = self.messages[ch]
        if "after" in q:
            msgs = [x for x in msgs if int(x["id"]) > int(q["after"])][: int(q.get("limit", 50))]
        else:
            msgs = msgs[-int(q.get("limit", 50)):]
        return Resp(json.dumps(list(reversed(msgs))).encode())   # newest first, like Discord


class FakeRealm:
    """AzerothCore SOAP with ov_discord.lua's console verbs (the same protocol the Lua test checks)."""

    def __init__(self):
        self.boot = 111
        self.seq = 0
        self.queue = []            # (seq, name, text)
        self.bugs = []             # dicts
        self.said = []             # (name, text) shown in game
        self.commands = []
        self.auth_ok = True

    def chat(self, name, text):
        self.seq += 1
        self.queue.append((self.seq, name, text))

    def restart(self):
        self.boot += 1
        self.seq = 0
        self.queue = []

    def run(self, cmd):
        self.commands.append(cmd)
        p = cmd.split()
        if p[:2] == ["wudiscord", "pull"]:
            after, bug_after, boot = int(p[2]), int(p[3]), int(p[4])
            if boot != self.boot or after > self.seq:
                after = 0
            lines = [f"C {s} {n.encode().hex()} {t.encode().hex()}" for s, n, t in self.queue if s > after][:25]
            if bug_after >= 0:
                lines += [f"B {b['id']} {b['name'].encode().hex()} {b['level']} {b['map']} {b['zone']} {b['text'].encode().hex()}"
                          for b in self.bugs if b["id"] > bug_after][:5]
            return "\n".join([f"wudiscord ok {self.boot} {self.seq} {len(lines)}"] + lines)
        if p[:2] == ["wudiscord", "bugmax"]:
            return f"wudiscord bugmax {max([b['id'] for b in self.bugs] or [0])}"
        if p[:2] == ["wudiscord", "say"]:
            self.said.append((bytes.fromhex(p[2]).decode(), bytes.fromhex(p[3]).decode()))
            return "wudiscord ok said 3"
        return "unknown"

    def __call__(self, req, timeout=None):
        if not self.auth_ok:
            raise http_error(req.full_url, 401)
        assert req.get_header("Authorization").startswith("Basic ")
        root = ET.fromstring(req.data)
        cmd = next(el.text for el in root.iter() if el.tag.endswith("command"))
        body = ('<?xml version="1.0"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
                'xmlns:ns1="urn:AC"><SOAP-ENV:Body><ns1:executeCommandResponse><result>'
                + (self.run(cmd).replace("&", "&amp;").replace("<", "&lt;"))
                + "</result></ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>")
        return Resp(body.encode())


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp, env_extra=None, discord=None, realm=None):
    env = {"DISCORD_BOT_TOKEN": TOKEN, "DISCORD_CHAT_CHANNEL_ID": "100", "DISCORD_BUG_CHANNEL_ID": "200",
           "SOAP_USER": "WUSOAP", "SOAP_PASS": SOAP_PASS, "WU_DISCORD_STATE": os.path.join(tmp, "state.json"),
           "WU_DISCORD_LINK_ALLOW": "openvanilla.app"}
    env.update(env_extra or {})
    cfg = B.Config(env)
    discord = discord or FakeDiscord()
    realm = realm or FakeRealm()
    clock = Clock()
    sleeps = []
    br = B.Bridge(cfg, B.Discord(cfg.token, cfg.api, urlopen=discord, sleep=sleeps.append),
                  B.Soap(cfg.soap_url, cfg.soap_user, cfg.soap_pass, urlopen=realm), B.State(cfg.state_path), clock=clock)
    return br, discord, realm, clock, sleeps


class Text(unittest.TestCase):
    A = {"openvanilla.app"}

    def test_mentions_never_ping(self):
        s = B.clean_for_discord("@everyone @here <@123> <@&456> <#789> hi", self.A)
        self.assertNotRegex(s, r"@everyone|@here|<@\d|<@&|<#\d")
        self.assertIn("hi", s)

    def test_markdown_escaped(self):
        s = B.clean_for_discord("**bold** __u__ `code` ||spoiler|| > quote [x](y)", self.A)
        for raw in ("**bold**", "__u__", "`code`", "||spoiler||", "[x](y)"):
            self.assertNotIn(raw, s)
        self.assertIn(r"\*\*bold\*\*", s)

    def test_links_dropped_unless_allowed(self):
        s = B.clean_for_discord("free gold at https://evil.example/x and www.bad.com or scam.ru/a, see play.openvanilla.app/wrath", self.A)
        self.assertNotIn("evil", s); self.assertNotIn("bad.com", s); self.assertNotIn("scam.ru", s)
        self.assertEqual(s.count("[link removed]"), 3)
        self.assertIn("<https://play.openvanilla.app/wrath>", s)
        self.assertIn("[link removed]", B.clean_for_discord("discord.gg/abc", self.A))
        self.assertIn("[link removed]", B.clean_for_discord("https://openvanilla.app.evil.com/", self.A))

    def test_game_markup_stripped(self):
        s = B.clean_for_discord("look |cffa335ee|Hitem:49623:0|h[Shadowmourne]|h|r |TInterface\\x:0|t ok", self.A)
        self.assertNotIn("|H", s); self.assertNotIn("|c", s); self.assertNotIn("Interface", s)
        self.assertIn(r"\[Shadowmourne\]", s)

    def test_length_cap(self):
        self.assertLessEqual(len(B.clean_for_discord("x" * 5000, self.A)), B.CHAT_LINE_MAX)
        self.assertTrue(all(len(m) <= 2000 for m in B.pack(["y" * 300] * 30)))

    def test_chat_line_format(self):
        self.assertEqual(B.chat_line("Alice", "hello", self.A), "[Alice]: hello")

    def test_discord_to_game(self):
        m = {"content": "hi <@1> <@&2> @everyone **bold** <:pog:3> <#4> on World of Warcraft, Lich King", "attachments": [{}],
             "mentions": [{"id": "1", "username": "bob", "global_name": "Bobby"}]}
        s = B.clean_for_game(m)
        self.assertNotIn("@everyone", s); self.assertNotIn("<", s); self.assertIn(" bold ", s)
        self.assertIn("@Bobby", s); self.assertIn(":pog:", s); self.assertIn("[attachment]", s)
        self.assertIsNone(BRAND.search(s), s)
        self.assertLessEqual(len(B.clean_for_game({"content": "z" * 999})), B.GAME_TEXT_MAX)
        self.assertEqual(B.display_name({"author": {"username": "x" * 80}}), "x" * B.NAME_MAX)
        self.assertEqual(B.display_name({"author": {"username": "u"}, "member": {"nick": "Nick"}}), "Nick")

    def test_window(self):
        c = Clock(); w = B.Window(2, 10, c)
        self.assertEqual([w.allow("a"), w.allow("a"), w.allow("a"), w.allow("b")], [True, True, False, True])
        c.t += 11
        self.assertTrue(w.allow("a"))


class BridgeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_start_does_not_replay_history(self):
        d = FakeDiscord(); d.add("100", "old message from yesterday")
        r = FakeRealm(); r.bugs.append({"id": 9, "name": "Old", "level": 1, "map": 0, "zone": 1, "text": "old bug"})
        br, d, r, _, _ = make(self.tmp, discord=d, realm=r)
        br.start(); br.step()
        self.assertEqual(r.said, [])
        self.assertEqual(d.posted, [])
        self.assertEqual(br.state.data["bug_after"], 9)

    def test_game_to_discord(self):
        br, d, r, _, _ = make(self.tmp)
        br.start()
        r.chat("Alice", "hello @everyone https://evil.example/x")
        r.chat("Bob", "|cffa335ee|Hitem:1|h[Frostmourne]|h|r for sale")
        br.step()
        self.assertEqual(len(d.posted), 1)        # both lines in one message
        ch, payload = d.posted[0]
        self.assertEqual(ch, "100")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        lines = payload["content"].split("\n")
        self.assertTrue(lines[0].startswith("[Alice]: hello @​everyone [link removed]"), lines[0])
        self.assertEqual(lines[1], r"[Bob]: \[Frostmourne\] for sale")
        br.step()
        self.assertEqual(len(d.posted), 1, "nothing posted twice")

    def test_discord_to_game(self):
        br, d, r, _, _ = make(self.tmp)
        br.start()
        d.add("100", "hi all <@&1> @here", username="sam", member={"nick": "Sammy"})
        d.add("100", "a bot", bot=True)
        d.add("100", "a webhook", webhook_id="77")
        d.add("100", "joined", type=7)
        d.add("100", "   ")
        br.step()
        self.assertEqual(r.said, [("Sammy", "hi all")])
        # our own posts come back from the channel and are not echoed into the game
        r.chat("Alice", "echo test")
        br.step(); br.step()
        self.assertEqual(r.said, [("Sammy", "hi all")])

    def test_mutes_both_ways(self):
        mf = os.path.join(self.tmp, "mutes.txt")
        with open(mf, "w") as f:
            f.write("# muted\nTroll\n")
        br, d, r, _, _ = make(self.tmp, {"WU_DISCORD_MUTE": "42", "WU_DISCORD_MUTE_FILE": mf})
        br.start()
        d.add("100", "from a muted id", author_id="42")
        d.add("100", "fine", author_id="43", username="ok")
        r.chat("troll", "muted in game"); r.chat("Alice", "fine too")
        br.step()
        self.assertEqual(r.said, [("ok", "fine")])
        self.assertEqual(d.posted[0][1]["content"], "[Alice]: fine too")
        os.utime(mf, (1, 1))
        with open(mf, "w") as f:
            f.write("alice\n")
        os.utime(mf, (5, 5))
        r.chat("Alice", "now muted"); r.chat("Troll", "unmuted now")
        br.step()
        self.assertEqual(d.posted[-1][1]["content"], "[Troll]: unmuted now")

    def test_rate_limits(self):
        br, d, r, clock, _ = make(self.tmp)
        br.start()
        for i in range(10):
            d.add("100", f"spam {i}", author_id="5")
        for i in range(10):
            r.chat("Spammer", f"line {i}")
        br.step()
        self.assertEqual(len(r.said), B.USER_MAX)
        self.assertEqual(d.posted[0][1]["content"].count("[Spammer]"), B.PLAYER_MAX)
        clock.t += 100
        d.add("100", "later", author_id="5")
        br.step()
        self.assertEqual(r.said[-1], ("sam", "later"))

    def test_discord_post_rate_and_backlog(self):
        br, d, r, clock, _ = make(self.tmp)
        br.start()
        for i in range(150):                      # 150 different players, long lines: many Discord messages
            r.chat(f"P{i}", "x" * 250)
        for _ in range(6):
            br.step()
        self.assertLessEqual(len(d.posted), B.POSTS_PER_WINDOW, "never more than the window allows")
        clock.t += 10
        br.step()
        self.assertTrue(any("lines skipped" in p["content"] for _, p in d.posted))
        self.assertGreater(len(d.posted), B.POSTS_PER_WINDOW)
        self.assertTrue(all(len(p["content"]) <= 2000 for _, p in d.posted))

    def test_bug_feed(self):
        br, d, r, _, _ = make(self.tmp)
        br.start()
        r.bugs.append({"id": 1, "name": "Alice", "level": 80, "map": 571, "zone": 4395,
                       "text": "quest giver gone @everyone see https://evil.example"})
        br.step()
        bugs = [p for ch, p in d.posted if ch == "200"]
        self.assertEqual(len(bugs), 1)
        self.assertIn("**Bug #1** from Alice (level 80, map 571, zone 4395)", bugs[0]["content"])
        self.assertNotIn("evil", bugs[0]["content"])
        self.assertNotIn("@everyone", bugs[0]["content"])
        br.step()
        self.assertEqual(len([p for ch, p in d.posted if ch == "200"]), 1)
        self.assertEqual(json.loads(read(os.path.join(self.tmp, "state.json")))["bug_after"], 1)

    def test_no_bug_channel_no_bug_pull(self):
        br, d, r, _, _ = make(self.tmp, {"DISCORD_BUG_CHANNEL_ID": ""})
        br.start(); br.step()
        self.assertFalse(any("bugmax" in c for c in r.commands))
        self.assertTrue(all(c.split()[3] == "-1" for c in r.commands if c.startswith("wudiscord pull")))

    def test_realm_restart(self):
        br, d, r, _, _ = make(self.tmp)
        br.start()
        r.chat("A", "one"); r.chat("A", "two"); br.step()
        r.restart()
        for i in range(3):
            r.chat("B", f"after restart {i}")     # fewer lines than before the restart: none may be missed
        br.step()
        self.assertIn("[B]: after restart 0", d.posted[-1][1]["content"])
        self.assertIn("[B]: after restart 2", d.posted[-1][1]["content"])

    def test_state_survives_daemon_restart(self):
        br, d, r, _, _ = make(self.tmp)
        br.start()
        d.add("100", "first"); br.step()
        br2, _, _, _, _ = make(self.tmp, discord=d, realm=r)
        br2.start()
        d.add("100", "second"); br2.step()
        self.assertEqual([t for _, t in r.said], ["first", "second"])

    def test_discord_429_waits_and_retries(self):
        br, d, r, _, sleeps = make(self.tmp)
        br.start()
        d.rate_limit_next = 1
        r.chat("A", "hello"); br.step()
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(len(d.posted), 1)

    def test_outages_are_survived(self):
        br, d, r, _, _ = make(self.tmp)
        br.start()
        d.down = True
        r.chat("A", "while Discord is down")
        errs = br.step()
        self.assertTrue(errs and all(e.kind == "down" for e in errs))
        d.down = False
        br.step()
        self.assertIn("while Discord is down", d.posted[-1][1]["content"])

    def test_dry_run_touches_nothing(self):
        br, d, r, _, _ = make(self.tmp, {"WU_DISCORD_DRY_RUN": "1"})
        br.start()
        r.chat("A", "x"); d.add("100", "y")
        br.step()
        self.assertEqual(d.posted, [])
        self.assertFalse(any(c.startswith("wudiscord say") for c in r.commands))


class Announce(unittest.TestCase):
    """New-realm announcements: off by default; on, one line per claimed, filtered, listed-long-enough realm, once."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def rec(rid, name, age=1200, claimed=True, name_ok=True, live=True, **com):
        import time as _t
        return {"name": name, "state": "live" if live else "offline", "official": False,
                "community": dict({"realmId": rid, "claimed": claimed, "nameOk": name_ok,
                                   "firstSeen": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() - age))}, **com)}

    def test_off_by_default(self):
        br, d, _r, clock, _ = make(self.tmp)
        self.assertFalse(br.cfg.announce)
        br.fetch = lambda url: self.fail("the realm list must not be read while announcements are off")
        br.start(); br.step()
        self.assertEqual(d.posted, [])

    def test_on_posts_each_good_realm_once_and_never_floods(self):
        br, d, _r, clock, _ = make(self.tmp, {"WU_DISCORD_ANNOUNCE_REALMS": "1"})
        listing = [self.rec("aaaaaaaaaaaaaaaa", "Old Realm")]
        br.fetch = lambda url: listing
        br.start(); br.step()
        self.assertEqual(d.posted, [], "first run: what is already listed is marked seen, not posted")
        listing += [self.rec("bbbbbbbbbbbbbbbb", "Frost Haven @everyone"),
                    self.rec("cccccccccccccccc", "Too Fresh", age=60),
                    self.rec("dddddddddddddddd", "Unclaimed", claimed=False),
                    self.rec("eeeeeeeeeeeeeeee", "Filtered", name_ok=False),
                    self.rec("ffffffffffffffff", "WoW Night"),
                    self.rec("gggggggggggggggg", "Ours", sample=True),
                    self.rec("hhhhhhhhhhhhhhhh", "Asleep", live=False)]
        clock.t += 301; br.step()
        self.assertEqual(len(d.posted), 1, d.posted)
        ch, payload = d.posted[0]
        self.assertEqual(ch, "100")
        self.assertTrue(payload["content"].startswith("New realm listed: Frost Haven @"))
        self.assertIn("https://play.openvanilla.app/wrath/r/bbbbbbbbbbbbbbbb", payload["content"])
        self.assertNotIn("@everyone", payload["content"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        clock.t += 301; br.step()
        self.assertEqual(len(d.posted), 1, "each realm once")
        clock.t += 10; listing.append(self.rec("iiiiiiiiiiiiiiii", "Later")); br.step()
        self.assertEqual(len(d.posted), 1, "not before WU_DISCORD_ANNOUNCE_EVERY")

    def test_site_down_never_stops_the_bridge(self):
        br, d, _r, clock, _ = make(self.tmp, {"WU_DISCORD_ANNOUNCE_REALMS": "1"})
        def down(url):
            raise OSError("refused")
        br.fetch = down
        br.start()
        self.assertEqual(br.step(), [])

    def test_documented_as_off_and_the_owners_choice(self):
        doc = B.__doc__
        self.assertIn("OFF by default", doc)
        self.assertIn("owner", doc)
        self.assertIn("WU_DISCORD_ANNOUNCE_REALMS", doc)


class Secrets(unittest.TestCase):
    def test_token_only_in_the_header_and_never_logged(self):
        tmp = tempfile.mkdtemp()
        try:
            stream = io.StringIO()
            h = logging.StreamHandler(stream); h.addFilter(B.SecretFilter(TOKEN, SOAP_PASS))
            B.log.addHandler(h); B.log.setLevel(logging.DEBUG)
            br, d, r, _, _ = make(tmp)
            br.start()
            d.down = True; r.chat("A", "x"); br.step()
            B.log.warning("accidental %s and %s", TOKEN, SOAP_PASS)      # the filter must catch even this
            B.log.removeHandler(h)
            out = stream.getvalue()
            self.assertNotIn(TOKEN, out); self.assertNotIn(SOAP_PASS, out)
            self.assertIn("[redacted]", out)
            for req in d.requests:
                self.assertNotIn(TOKEN, req.full_url)
                self.assertNotIn(TOKEN, (req.data or b"").decode())
            self.assertNotIn(TOKEN, repr(br.cfg) + repr(br.discord))
            self.assertNotIn(SOAP_PASS, repr(br.cfg) + repr(br.soap))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_errors_do_not_carry_the_token(self):
        bad = B.Discord("wrong-token-abcdef", "https://discord.invalid/api/v10", urlopen=FakeDiscord())
        with self.assertRaises(B.TransportError) as e:
            bad.me()
        self.assertEqual(e.exception.kind, "auth")
        self.assertNotIn("wrong-token", str(e.exception))

    def test_config_only_from_env(self):
        self.assertTrue(B.Config({}).problems())
        self.assertEqual(B.Config({"DISCORD_BOT_TOKEN": "t", "DISCORD_CHAT_CHANNEL_ID": "1", "SOAP_USER": "u",
                                   "SOAP_PASS": "p"}).problems(), [])
        self.assertTrue(B.Config({"DISCORD_BOT_TOKEN": "t", "DISCORD_CHAT_CHANNEL_ID": "general", "SOAP_USER": "u",
                                  "SOAP_PASS": "p"}).problems())

    def test_main_check_is_offline_and_main_refuses_without_settings(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DISCORD_", "SOAP_", "WU_DISCORD"))}
        env["PYTHONPATH"] = os.path.join(HOSTING, "discord")
        r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from wudiscord import bridge; "
                            "sys.exit(bridge.main(['--check']))", os.path.join(HOSTING, "discord")],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("DISCORD_BOT_TOKEN is not set", r.stderr)
        env.update(DISCORD_BOT_TOKEN=TOKEN, DISCORD_CHAT_CHANNEL_ID="100", SOAP_USER="WUSOAP", SOAP_PASS=SOAP_PASS,
                   WU_DISCORD_API="http://127.0.0.1:9/api/v10")
        code = ("import sys, urllib.request; sys.path.insert(0, sys.argv[1]);"
                "urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network'));"
                "from wudiscord import bridge; sys.exit(bridge.main(['--check']))")
        r = subprocess.run([sys.executable, "-I", "-c", code, os.path.join(HOSTING, "discord")],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CHECK OK", r.stdout)
        self.assertNotIn(TOKEN, r.stdout + r.stderr); self.assertNotIn(SOAP_PASS, r.stdout + r.stderr)


class GameSide(unittest.TestCase):
    @unittest.skipUnless(shutil.which("lua5.1"), "lua5.1 not installed")
    def test_ov_discord_lua(self):
        r = subprocess.run(["lua5.1", os.path.join(HERE, "test_ov_discord.lua"),
                            os.path.join(ROOT, "realm", "custom", "lua_scripts", "ov_discord.lua")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        print("\n  " + r.stdout.strip().splitlines()[-1] + " (ov_discord.lua)", file=sys.stderr)


SYSTEMCTL = r"""#!/usr/bin/env bash
echo "systemctl $*" >> "$STUB_STATE/systemctl.log"
case "$1" in
  is-enabled) [ -f "$STUB_STATE/enabled" ]; exit $? ;;
  is-active) [ -f "$STUB_STATE/fail_active" ] && exit 3; exit 0 ;;
esac
exit 0
"""


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin"); os.makedirs(self.bin)
        self.state = os.path.join(self.tmp, "stub"); os.makedirs(self.state)
        p = os.path.join(self.bin, "systemctl")
        with open(p, "w") as f:
            f.write(SYSTEMCTL)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        shutil.copytree(os.path.join(HOSTING, "discord", "wudiscord"), os.path.join(self.src, "discord", "wudiscord"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(HOSTING, "discord", "deploy"), os.path.join(self.src, "discord", "deploy"))
        self.dir = os.path.join(self.tmp, "opt"); self.units = os.path.join(self.tmp, "units"); os.makedirs(self.units)
        self.signup = os.path.join(self.tmp, "signup.env")
        with open(self.signup, "w") as f:
            f.write("SOAP_USER=WUSOAP\nSOAP_PASS=p&a|ss#1\nSOAP_URL=http://127.0.0.1:7878/\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_up(self):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_STATE=self.state, WU_TEST="1",
                   WU_DISCORD_DIR=self.dir, WU_UNIT_DIR=self.units, WU_SIGNUP_ENV=self.signup, WU_SETTLE="0",
                   WU_PYTHON=sys.executable)
        for k in list(env):
            if k.startswith(("DISCORD_", "SOAP_")):
                env.pop(k)
        return subprocess.run(["bash", os.path.join(self.src, "discord", "deploy", "discord-up.sh"), self.src],
                              env=env, capture_output=True, text=True, timeout=60)

    def envf(self):
        return read(os.path.join(self.dir, "discord.env"))

    def test_fresh_install_stays_off(self):
        r = self.run_up()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith("DISCORD BRIDGE INSTALLED (OFF)"), r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "app", "wudiscord", "bridge.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.units, "wu-discord.service")))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "discord.env")).st_mode), 0o600)
        self.assertIn("SOAP_USER=WUSOAP\n", self.envf()); self.assertIn("SOAP_PASS=p&a|ss#1\n", self.envf())
        self.assertIn("DISCORD_BOT_TOKEN is not set", r.stdout)
        log = read(os.path.join(self.state, "systemctl.log"))
        self.assertNotIn("enable", log.replace("is-enabled", "")); self.assertNotIn("restart", log)
        self.assertNotIn("p&a|ss#1", r.stdout + r.stderr)

    def test_rerun_keeps_settings_and_restarts_only_when_on(self):
        self.run_up()
        p = os.path.join(self.dir, "discord.env")
        s = self.envf().replace("DISCORD_BOT_TOKEN=\n", f"DISCORD_BOT_TOKEN={TOKEN}\n") \
                       .replace("DISCORD_CHAT_CHANNEL_ID=\n", "DISCORD_CHAT_CHANNEL_ID=100\n")
        with open(p, "w") as f:
            f.write(s)
        open(os.path.join(self.state, "enabled"), "w").close()
        r = self.run_up()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith("DISCORD BRIDGE OK"), r.stdout)
        self.assertIn(f"DISCORD_BOT_TOKEN={TOKEN}", self.envf())
        self.assertNotIn(TOKEN, r.stdout + r.stderr)
        self.assertIn("systemctl restart wu-discord", read(os.path.join(self.state, "systemctl.log")))

    def test_failed_restart_puts_old_code_back(self):
        self.run_up()
        with open(os.path.join(self.dir, "app", "wudiscord", "MARK"), "w") as f:
            f.write("old")
        s = self.envf().replace("DISCORD_BOT_TOKEN=\n", "DISCORD_BOT_TOKEN=x\n").replace("DISCORD_CHAT_CHANNEL_ID=\n", "DISCORD_CHAT_CHANNEL_ID=1\n")
        with open(os.path.join(self.dir, "discord.env"), "w") as f:
            f.write(s)
        open(os.path.join(self.state, "enabled"), "w").close()
        open(os.path.join(self.state, "fail_active"), "w").close()
        r = self.run_up()
        self.assertEqual(r.returncode, 1)
        self.assertIn("previous code is back", r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "app", "wudiscord", "MARK")))

    def test_enabled_but_incomplete_is_not_restarted(self):
        self.run_up()
        open(os.path.join(self.state, "enabled"), "w").close()
        r = self.run_up()
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("restart", read(os.path.join(self.state, "systemctl.log")))


class Brand(unittest.TestCase):
    def test_no_game_brand_names_in_what_players_or_discord_see(self):
        for rel in ("hosting/discord/wudiscord/bridge.py", "realm/custom/lua_scripts/ov_discord.lua",
                    "hosting/discord/deploy/discord.env.example", "hosting/discord/Deploy Discord bridge.bat"):
            text = read(os.path.join(ROOT, rel))
            if rel.endswith("bridge.py"):     # the mask itself names them, on purpose
                text = text.replace(text[text.index("GAME_BRAND_WORDS = re.compile"):].split("\n", 1)[0], "")
            self.assertIsNone(BRAND.search(text), rel)
            self.assertNotIn("OpenVanilla", text, rel); self.assertNotIn("OpenWoW", text, rel)


if __name__ == "__main__":
    unittest.main(verbosity=1)
