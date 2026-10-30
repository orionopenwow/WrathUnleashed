"""Leyline Discord rebrand (discord_leyline.py) against a fake Discord REST API on localhost.

Covers: the preview never writes; the backup lands before the first write; matching channels are reused (history
kept); old channels move into a hidden read-only ARCHIVE; a second run changes nothing; 429 and 5xx retries; the
@everyone role, managed roles, roles above the bot and the owner's roles are never touched; the delete flags need their
typed confirmations; the token never reaches the output or any file; no banned words or version numbers in any name or
topic.

    python3 tools/discord-leyline/test_discord_leyline.py
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "discord_leyline.py"
sys.path.insert(0, str(HERE))
import discord_leyline as dl  # noqa: E402

TOKEN = "MTk4NjIyNDgzNDcxOTI1MjQ4.FAKE-tok.en_SECRET_value"
GID, BOT, OWNER = "1", "900", "100"


def base_world(community=False):
    roles = [
        {"id": GID, "name": "@everyone", "position": 0, "color": 0, "hoist": False, "managed": False,
         "permissions": "1024"},
        {"id": "50", "name": "Leyline setup", "position": 10, "color": 0, "hoist": False, "managed": True,
         "tags": {"bot_id": BOT}, "permissions": "8"},
        {"id": "51", "name": "Admin", "position": 11, "color": 0xff0000, "hoist": True, "managed": False,
         "permissions": "8"},
        {"id": "52", "name": "Founder", "position": 5, "color": 0x00ff00, "hoist": True, "managed": False,
         "permissions": "0"},
        {"id": "53", "name": "Realm-Ally", "position": 3, "color": 0x123456, "hoist": False, "managed": False,
         "permissions": "0"},
        {"id": "54", "name": "moderator", "position": 4, "color": 0x111111, "hoist": False, "managed": False,
         "permissions": "8192"},
        {"id": "55", "name": "Server Booster", "position": 2, "color": 0xf47fff, "hoist": False, "managed": True,
         "tags": {"premium_subscriber": None}, "permissions": "0"},
    ]

    def ch(i, name, t, parent=None, pos=0, ow=None, topic=None):
        return {"id": i, "name": name, "type": t, "parent_id": parent, "position": pos, "guild_id": GID,
                "permission_overwrites": ow or [], "topic": topic, "rate_limit_per_user": 0}
    channels = [
        ch("10", "OpenVanilla", 4, pos=0),
        ch("11", "Text Channels", 4, pos=1),
        ch("20", "general", 0, "11", 0, topic="old topic"),
        ch("21", "announcements", 0, "11", 1, ow=[{"id": GID, "type": 0, "allow": "0", "deny": "2048"}]),
        ch("22", "ov-realm-help", 0, "10", 0),
        ch("23", "wrath-dev", 0, "10", 1, ow=[{"id": "53", "type": 0, "allow": "1024", "deny": "0"}]),
        ch("24", "rules", 0, "11", 2),
        ch("30", "General", 2, "11", 0),
        ch("31", "AFK", 2, None, 5),
    ]
    guild = {"id": GID, "name": "OpenVanilla Wrath", "owner_id": OWNER, "icon": None, "banner": None,
             "splash": None, "system_channel_id": "24", "afk_channel_id": "31", "rules_channel_id": None,
             "public_updates_channel_id": None, "features": []}
    if community:
        guild["features"] = ["COMMUNITY", "NEWS", "BANNER"]
        guild["rules_channel_id"] = "24"
        channels.append(ch("25", "moderator-only", 0, "11", 3,
                           ow=[{"id": GID, "type": 0, "allow": "0", "deny": "1024"}]))
        guild["public_updates_channel_id"] = "25"
    msgs = {"20": [{"id": str(100000 + i), "content": f"hello {i}", "timestamp": f"2026-01-01T00:00:{i % 60:02d}",
                    "author": {"id": "7", "username": "ann", "global_name": "Ann"},
                    "attachments": [{"url": f"https://cdn.example/{i}.png"}] if i % 50 == 0 else []}
                   for i in range(250)][::-1],
            "22": [{"id": "200001", "content": "realm down?", "timestamp": "2026-02-01T00:00:00",
                    "author": {"id": "8", "username": "bo"}, "attachments": []}]}
    members = {BOT: {"user": {"id": BOT}, "roles": ["50"]}, OWNER: {"user": {"id": OWNER}, "roles": ["52"]}}
    return {"guild": guild, "roles": roles, "channels": channels, "messages": msgs, "members": members,
            "guilds": [{"id": GID, "name": guild["name"]}]}


class Fake:
    def __init__(self, world, backup_root):
        self.w = world
        self.backup_root = Path(backup_root)
        self.log = []                # every request: (method, path, body, headers, backup_ready)
        self.fail_once = {}          # (method, path) -> status to answer once
        self.served_429 = 0
        self.served_5xx = 0
        self.next_id = 5000
        self.lock = threading.Lock()

    def writes(self):
        return [x for x in self.log if x[0] != "GET"]

    def backup_ready(self):
        return any((d / "channels.json").exists() for d in self.backup_root.glob("Leyline-discord-backup-*"))

    def nid(self):
        self.next_id += 1
        return str(self.next_id)

    def chan(self, cid):
        return next((c for c in self.w["channels"] if c["id"] == cid), None)

    def handle(self, method, path, query, body, headers):
        with self.lock:
            self.log.append((method, path, body, dict(headers), self.backup_ready() if method != "GET" else None))
            if headers.get("Authorization") != "Bot " + TOKEN:
                return 401, {"message": "401: Unauthorized", "code": 0}
            key = (method, path)
            if key in self.fail_once:
                st = self.fail_once.pop(key)
                if st == 429:
                    self.served_429 += 1
                    return 429, {"message": "You are being rate limited.", "retry_after": 0.01, "global": False}
                self.served_5xx += 1
                return st, {"message": "oops"}
            return self.route(method, path, query, body)

    def route(self, m, path, q, body):
        w = self.w
        p = path.split("/")[1:]
        if path == "/users/@me":
            return 200, {"id": BOT, "username": "Leyline setup", "bot": True}
        if path == "/users/@me/guilds":
            return 200, w["guilds"]
        if p[0] == "guilds" and p[1] == GID:
            rest = p[2:]
            if not rest:
                if m == "GET":
                    return 200, w["guild"]
                if m == "PATCH":
                    for k, v in body.items():
                        if k in ("icon", "banner", "splash"):
                            w["guild"][k] = "h" + str(abs(hash(v)) % 10 ** 8) if v else None
                        else:
                            w["guild"][k] = v
                    return 200, w["guild"]
            if rest == ["roles"]:
                if m == "GET":
                    return 200, w["roles"]
                if m == "POST":
                    for r in w["roles"]:
                        if r["id"] != GID and r["position"] >= 1:
                            r["position"] += 1
                    r = {"id": self.nid(), "name": body["name"], "color": body.get("color", 0),
                         "hoist": body.get("hoist", False), "position": 1, "managed": False,
                         "mentionable": body.get("mentionable", False), "permissions": body.get("permissions", "0")}
                    w["roles"].append(r)
                    return 200, r
                if m == "PATCH":
                    for b in body:
                        next(r for r in w["roles"] if r["id"] == b["id"])["position"] = b["position"]
                    return 200, w["roles"]
            if rest[0] == "roles" and len(rest) == 2:
                r = next((r for r in w["roles"] if r["id"] == rest[1]), None)
                if r is None:
                    return 404, {"message": "Unknown Role"}
                if m == "PATCH":
                    r.update(body)
                    return 200, r
                if m == "DELETE":
                    w["roles"].remove(r)
                    return 204, None
            if rest == ["channels"]:
                if m == "GET":
                    return 200, w["channels"]
                if m == "POST":
                    c = {"id": self.nid(), "guild_id": GID, "name": body["name"], "type": body.get("type", 0),
                         "parent_id": body.get("parent_id"), "topic": body.get("topic"),
                         "rate_limit_per_user": body.get("rate_limit_per_user", 0),
                         "permission_overwrites": body.get("permission_overwrites") or [],
                         "position": max([c["position"] for c in w["channels"]] or [0]) + 1}
                    w["channels"].append(c)
                    return 201, c
                if m == "PATCH":
                    for b in body:
                        self.chan(b["id"])["position"] = b["position"]
                    return 204, None
            if rest[0] == "members":
                mem = w["members"].get(rest[1])
                return (200, mem) if mem else (404, {"message": "Unknown Member"})
        if p[0] == "channels":
            c = self.chan(p[1])
            if c is None:
                return 404, {"message": "Unknown Channel"}
            rest = p[2:]
            if not rest:
                if m == "PATCH":
                    c.update(body)
                    return 200, c
                if m == "DELETE":
                    w["channels"].remove(c)
                    return 200, c
            if rest == ["messages"] and m == "GET":
                msgs = w["messages"].get(c["id"], [])
                if "before" in q:
                    msgs = [x for x in msgs if int(x["id"]) < int(q["before"])]
                return 200, msgs[:int(q.get("limit", 50))]
            if rest[0] == "permissions":
                ow = [o for o in c["permission_overwrites"] if o["id"] != rest[1]]
                if m == "PUT":
                    ow.append({"id": rest[1], "type": body["type"], "allow": body["allow"], "deny": body["deny"]})
                c["permission_overwrites"] = ow
                return 204, None
        return 404, {"message": f"fake has no {m} {path}"}


def serve(fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def go(self):
            u = urllib.parse.urlparse(self.path)
            path = u.path[len("/api"):]
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            q = dict(urllib.parse.parse_qsl(u.query))
            st, out = fake.handle(self.command, path, q, body, self.headers)
            raw = json.dumps(out).encode() if out is not None else b""
            self.send_response(st)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = go

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Base(unittest.TestCase):
    community = False

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="leyline-discord-test-"))
        self.backups = self.tmp / "Desktop"
        self.backups.mkdir()
        self.fake = Fake(base_world(self.community), self.backups)
        self.srv = serve(self.fake)
        self.token_file = self.tmp / "token.txt"
        self.token_file.write_text(TOKEN + "\n")
        self.outputs = []

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def run_script(self, *args, stdin="", token_file=None):
        env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
        env.update(LEYLINE_DISCORD_API=f"http://127.0.0.1:{self.srv.server_address[1]}/api",
                   LEYLINE_BACKUP_ROOT=str(self.backups), LEYLINE_STATE_FILE=str(self.tmp / "state.json"),
                   LEYLINE_DISCORD_BACKOFF="0.01", NO_PROXY="*", PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "--token-file", str(token_file or self.token_file), *args],
                           input=stdin, capture_output=True, text=True, env=env, timeout=120, encoding="utf-8")
        self.outputs.append(p.stdout + p.stderr)
        return p

    def apply(self, *args, stdin="YES\n"):
        p = self.run_script("--apply", *args, stdin=stdin)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def ch(self, name_slug, types=(0, 2, 4, 5)):
        hits = [c for c in self.fake.w["channels"] if dl.slug(c["name"]) == name_slug and c["type"] in types]
        self.assertEqual(len(hits), 1, f"{name_slug}: {hits}")
        return hits[0]

    def role(self, name):
        return next(r for r in self.fake.w["roles"] if r["name"].lower() == name.lower())

    def backup_dirs(self):
        return sorted(self.backups.glob("Leyline-discord-backup-*"))


class TestPreview(Base):
    def test_preview_makes_no_writes_and_shows_the_plan(self):
        before = copy.deepcopy(self.fake.w)
        p = self.run_script()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(self.fake.w, before)
        self.assertEqual(self.backup_dirs(), [])
        out = p.stdout
        for s in ("PREVIEW", "rename 'OpenVanilla Wrath' -> 'Leyline'", "icon -> leyline-discord-icon-512.png",
                  "New channels:", "category START", "◆︱looking-for-group in PLAY",
                  "Reused channels", "general -> ◆︱general", "General -> ◆︱Hangout",
                  "ov-realm-help -> ARCHIVE", "wrath-dev -> ARCHIVE", "AFK -> ARCHIVE",
                  "create Helper", "restyle Moderator", "--delete-old-roles", "Realm-Ally",
                  "Do these by hand", "Vanity URL", "Enable Community", "Nothing changed"):
            self.assertIn(s, out)
        self.assertIn("nothing (archived channels stay; --delete-archived would delete them)", out)
        self.assertIn("Moderator can post", out)
        self.assertIn("for the server 'OpenVanilla Wrath'", out)

    def test_preview_with_delete_flags_lists_deletions_but_still_writes_nothing(self):
        p = self.run_script("--delete-archived", "--delete-old-roles")
        self.assertEqual(self.fake.writes(), [])
        self.assertIn("DELETED:", p.stdout)
        self.assertIn("role Realm-Ally", p.stdout)
        self.assertIn("channel wrath-dev (from ARCHIVE)", p.stdout)
        for never in ("role Admin", "role Founder", "role Server Booster", "role Leyline setup", "role @everyone"):
            self.assertNotIn(never, p.stdout)

    def test_preview_lists_the_same_changes_the_apply_makes(self):
        prev = self.run_script()
        n_prev = int(prev.stdout.split(" change(s).")[0].rsplit("\n", 1)[-1])
        self.apply()
        done = [l for l in self.outputs[-1].splitlines() if l.strip().startswith("done:")]
        self.assertEqual(len(done), n_prev)


class TestApply(Base):
    def test_backup_is_written_before_any_write(self):
        self.apply()
        writes = self.fake.writes()
        self.assertTrue(writes)
        self.assertTrue(all(w[4] for w in writes), "a write happened before the backup existed")
        [b] = self.backup_dirs()
        self.assertIn(str(b), self.outputs[-1])
        g = json.loads((b / "guild.json").read_text(encoding="utf-8"))
        self.assertEqual(g["name"], "OpenVanilla Wrath")       # the state before the change
        chans = json.loads((b / "channels.json").read_text(encoding="utf-8"))
        self.assertTrue(any(c["id"] == "23" and c["permission_overwrites"] for c in chans))
        roles = json.loads((b / "roles.json").read_text(encoding="utf-8"))
        self.assertIn("Realm-Ally", [r["name"] for r in roles])
        gen = json.loads((b / "messages" / "general-20.json").read_text(encoding="utf-8"))
        self.assertEqual(len(gen["messages"]), 250)
        m0 = gen["messages"][0]
        self.assertEqual(set(m0), {"id", "author", "author_id", "time", "edited", "content", "pinned", "attachments"})
        self.assertEqual(m0["author"], "Ann")
        self.assertTrue(any(m["attachments"] for m in gen["messages"]))
        self.assertTrue((b / "welcome-message.txt").exists())
        self.assertTrue((b / "help-getting-in.txt").exists())
        self.assertTrue((b / "what-changed.txt").exists())

    def test_backup_message_limit(self):
        self.apply("--backup-messages", "120")
        b = self.backup_dirs()[-1]
        gen = json.loads((b / "messages" / "general-20.json").read_text(encoding="utf-8"))
        self.assertEqual(len(gen["messages"]), 120)
        self.apply("--backup-messages", "0")
        self.assertEqual(list((self.backup_dirs()[-1] / "messages").iterdir()), [])

    def test_layout_reuse_and_theme(self):
        self.apply()
        w = self.fake.w
        self.assertEqual(w["guild"]["name"], "Leyline")
        self.assertTrue(w["guild"]["icon"])
        self.assertIsNone(w["guild"]["banner"])                 # no BANNER feature: left for later
        self.assertIsNone(w["guild"]["afk_channel_id"])
        cats = {c["name"]: c for c in w["channels"] if c["type"] == 4}
        for cat in ("START", "PLAY", "CREATE", "FEEDBACK", "ARCHIVE"):
            self.assertIn(cat, cats)
        # reused, history kept: same ids
        gen, ann, hang = self.ch("general", (0,)), self.ch("announcements"), self.ch("hangout", (2,))
        self.assertEqual((gen["id"], ann["id"], hang["id"]), ("20", "21", "30"))
        self.assertEqual(gen["name"], "◆︱general")
        self.assertEqual(gen["parent_id"], cats["PLAY"]["id"])
        self.assertEqual(gen["topic"], "Talk about anything Leyline.")
        self.assertEqual(ann["name"], "✦︱announcements")
        self.assertEqual(hang["name"], "◆︱Hangout")
        welcome = self.ch("welcome")
        self.assertEqual(w["guild"]["system_channel_id"], welcome["id"])
        for name, cat in (("help", "PLAY"), ("looking-for-group", "PLAY"), ("mods-and-workshop", "CREATE"),
                          ("host-a-beacon", "CREATE"), ("showcase", "CREATE"), ("bug-reports", "FEEDBACK"),
                          ("ideas", "FEEDBACK"), ("welcome", "START")):
            c = self.ch(name)
            self.assertEqual(c["parent_id"], cats[cat]["id"], name)
            self.assertTrue(c["name"].startswith(dl.GLYPHS[cat] + dl.GLYPH_SEP), c["name"])
        self.assertEqual(self.ch("help")["rate_limit_per_user"], 10)
        self.assertEqual(self.ch("ideas")["rate_limit_per_user"], 10)
        self.assertEqual(self.ch("general", (0,))["rate_limit_per_user"], 0)
        # read-only #welcome and #announcements; Moderator may post
        mod = self.role("Moderator")
        for c in (welcome, ann):
            ow = dl.ow_map(c)
            self.assertTrue(int(ow[GID]["deny"]) & dl.P_SEND)
            self.assertFalse(int(ow[GID]["deny"]) & dl.P_VIEW)
            self.assertTrue(int(ow[mod["id"]]["allow"]) & dl.P_SEND)
        # order: categories START, PLAY, CREATE, FEEDBACK, ARCHIVE first
        order = [c["name"] for c in sorted((c for c in w["channels"] if c["type"] == 4), key=dl.okey)]
        self.assertEqual(order[:5], ["START", "PLAY", "CREATE", "FEEDBACK", "ARCHIVE"])
        play = [dl.slug(c["name"]) for c in sorted((c for c in w["channels"] if c["parent_id"] == cats["PLAY"]["id"]
                                                     and c["type"] == 0), key=dl.okey)]
        self.assertEqual(play, ["general", "help", "looking-for-group"])
        # roles
        for name, colour, hoist, *_ in dl.ROLES:
            r = self.role(name)
            self.assertEqual((r["color"], r["hoist"]), (colour, hoist), name)
        pos = [self.role(n)["position"] for n, *_ in dl.ROLES]
        self.assertEqual(pos, sorted(pos, reverse=True))
        self.assertEqual(self.role("Moderator")["id"], "54")     # reused, not duplicated
        self.assertEqual(sum(r["name"].lower() == "moderator" for r in w["roles"]), 1)

    def test_archive_moves_and_hides(self):
        self.apply()
        w = self.fake.w
        arch = self.ch("archive", (4,))
        mod = self.role("Moderator")
        aow = dl.ow_map(arch)
        self.assertTrue(int(aow[GID]["deny"]) & dl.P_VIEW)
        self.assertTrue(int(aow[mod["id"]]["allow"]) & dl.P_VIEW)
        self.assertTrue(int(aow[mod["id"]]["deny"]) & dl.P_SEND)
        for cid in ("22", "23", "24", "31"):
            c = self.fake.chan(cid)
            self.assertIsNotNone(c, cid)                        # nothing deleted
            self.assertEqual(c["parent_id"], arch["id"], cid)
            self.assertEqual(dl.ow_norm(c["permission_overwrites"]), dl.ow_norm(arch["permission_overwrites"]))
            self.assertNotIn("53", dl.ow_map(c))                # an old role's view grant is gone (synced)
        for cid in ("10", "11"):                                # empty old categories hidden, not deleted
            self.assertTrue(int(dl.ow_map(self.fake.chan(cid))[GID]["deny"]) & dl.P_VIEW)
        self.assertEqual(len(w["messages"]["20"]), 250)

    def test_second_run_changes_nothing(self):
        self.apply()
        n = len(self.fake.writes())
        snap = copy.deepcopy(self.fake.w)
        p = self.run_script("--apply", stdin="")                 # nothing to confirm when nothing changes
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(self.fake.writes()), n, [x[:3] for x in self.fake.writes()[n:]])
        self.assertEqual(self.fake.w, snap)
        self.assertIn("Nothing to change", p.stdout)
        prev = self.run_script()
        self.assertIn("Nothing to change", prev.stdout)

    def test_plain_names(self):
        self.apply("--plain")
        self.assertEqual(self.ch("general", (0,))["name"], "general")
        self.assertEqual(self.ch("hangout", (2,))["name"], "Hangout")
        self.apply()                                            # switching back to glyphs is a plain rename
        self.assertEqual(self.ch("general", (0,))["name"], "◆︱general")

    def test_no_yes_no_change(self):
        p = self.run_script("--apply", stdin="yes please\n")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(self.backup_dirs(), [])

    def test_audit_reason_and_user_agent(self):
        self.apply()
        for m, path, body, headers, _ in self.fake.writes():
            self.assertEqual(urllib.parse.unquote(headers.get("X-Audit-Log-Reason", "")), "Leyline rebrand", path)
            self.assertTrue(headers.get("User-Agent", "").startswith("DiscordBot ("))


class TestRetries(Base):
    def test_429_and_5xx_are_retried(self):
        self.fake.fail_once[("PATCH", f"/guilds/{GID}")] = 429
        self.fake.fail_once[("POST", f"/guilds/{GID}/roles")] = 429
        self.fake.fail_once[("GET", f"/guilds/{GID}/channels")] = 502
        self.apply()
        self.assertEqual(self.fake.served_429, 2)
        self.assertEqual(self.fake.served_5xx, 1)
        self.assertEqual(self.fake.w["guild"]["name"], "Leyline")
        self.assertEqual(sum(r["name"] == "Helper" for r in self.fake.w["roles"]), 1)

    def test_retry_after_is_honoured(self):
        slept = []
        api = dl.Discord(TOKEN, allow_writes=True, sleep=slept.append)
        self.fake.fail_once[("GET", "/users/@me")] = 429
        old = dl.API_BASE
        dl.API_BASE = f"http://127.0.0.1:{self.srv.server_address[1]}/api"
        try:
            env_proxy = {k: os.environ.pop(k) for k in list(os.environ) if "proxy" in k.lower()}
            try:
                self.assertEqual(api.request("GET", "/users/@me")["id"], BOT)
            finally:
                os.environ.update(env_proxy)
        finally:
            dl.API_BASE = old
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 0.06, places=3)

    def test_preview_client_refuses_writes(self):
        with self.assertRaises(RuntimeError):
            dl.Discord(TOKEN).request("PATCH", "/guilds/1", {"name": "x"})


class TestNeverTouch(Base):
    PROTECTED = {GID, "50", "51", "52", "55"}    # @everyone, bot's managed role, above bot, owner's role, booster

    def check_untouched(self):
        for m, path, body, *_ in self.fake.writes():
            parts = path.split("/")
            if len(parts) >= 5 and parts[3] == "roles":
                self.assertNotIn(parts[4], self.PROTECTED, f"{m} {path}")
            if path == f"/guilds/{GID}/roles" and m == "PATCH":
                self.assertFalse({b["id"] for b in body} & self.PROTECTED, body)
        ids = {r["id"] for r in self.fake.w["roles"]}
        self.assertTrue(self.PROTECTED <= ids)
        everyone = self.role("@everyone")
        self.assertEqual((everyone["permissions"], everyone["position"]), ("1024", 0))
        self.assertEqual(self.role("Admin")["color"], 0xff0000)
        self.assertEqual(self.role("Founder")["color"], 0x00ff00)

    def test_default_run(self):
        self.apply()
        self.check_untouched()
        self.assertIn("53", {r["id"] for r in self.fake.w["roles"]})      # old roles stay without the flag

    def test_delete_old_roles(self):
        p = self.apply("--delete-old-roles", stdin="YES\nDELETE ROLES\n")
        self.check_untouched()
        self.assertNotIn("53", {r["id"] for r in self.fake.w["roles"]})
        self.assertIn("keep Admin (above the bot's role)", p.stdout)
        self.assertIn("keep Founder (you have this role)", p.stdout)
        deleted = [x[1] for x in self.fake.writes() if x[0] == "DELETE" and "/roles/" in x[1]]
        self.assertEqual(deleted, [f"/guilds/{GID}/roles/53"])

    def test_owner_holds_a_target_role(self):
        self.fake.w["members"][OWNER]["roles"].append("54")              # owner is a "moderator" too
        p = self.apply()
        self.assertEqual(self.role("moderator")["color"], 0x111111)
        self.assertIn("keep Moderator as it is (you have this role)", p.stdout)
        self.check_untouched()


class TestDeleteFlags(Base):
    def test_delete_archived_needs_the_server_name(self):
        p = self.run_script("--apply", "--delete-archived", stdin="YES\nLeyline\n")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.fake.writes(), [])
        p = self.run_script("--apply", "--delete-archived", stdin="YES\n\n")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.fake.writes(), [])

    def test_delete_old_roles_needs_its_words(self):
        p = self.run_script("--apply", "--delete-old-roles", stdin="YES\ndelete\n")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.fake.writes(), [])

    def test_delete_archived_after_backup(self):
        self.apply("--delete-archived", stdin="YES\nOpenVanilla Wrath\n")
        b = self.backup_dirs()[-1]
        self.assertTrue((b / "messages" / "ov-realm-help-22.json").exists())
        for cid in ("22", "23", "24", "31", "10", "11"):
            self.assertIsNone(self.fake.chan(cid), cid)
        self.assertFalse([c for c in self.fake.w["channels"] if c["name"] == "ARCHIVE"])
        self.assertEqual(self.fake.chan("20")["name"], "◆︱general")     # reused channels never deleted
        dels = [x for x in self.fake.writes() if x[0] == "DELETE"]
        self.assertTrue(dels and all(x[4] for x in dels))
        # again: nothing left to delete, nothing changes
        n = len(self.fake.writes())
        self.apply("--delete-archived", stdin="Leyline\n")
        self.assertEqual(len(self.fake.writes()), n)


class TestCommunity(Base):
    community = True

    def test_community_server(self):
        self.apply()
        g = self.fake.w["guild"]
        welcome = self.ch("welcome")
        self.assertEqual(g["rules_channel_id"], welcome["id"])
        self.assertTrue(g["banner"])
        self.assertTrue(g["icon"])
        mo = self.fake.chan("25")
        self.assertEqual(mo["parent_id"], "11")                             # Community updates channel left alone
        self.assertFalse(int(dl.ow_map(self.fake.chan("11")).get(GID, {}).get("deny", 0)) & dl.P_VIEW)
        # rules channel moved to #welcome before the old one was archived
        w = self.fake.writes()
        i_rules = next(i for i, x in enumerate(w) if x[1] == f"/guilds/{GID}" and "rules_channel_id" in x[2])
        i_arch = next(i for i, x in enumerate(w) if x[1] == "/channels/24")
        self.assertLess(i_rules, i_arch)
        n = len(self.fake.writes())
        self.apply()
        self.assertEqual(len(self.fake.writes()), n)                       # icon/banner not re-uploaded


class TestGuildChoice(Base):
    def test_one_guild_is_named(self):
        p = self.run_script()
        self.assertIn("The bot is in one server: OpenVanilla Wrath (id 1)", p.stdout)

    def test_many_guilds_asks(self):
        self.fake.w["guilds"].append({"id": "2", "name": "Other"})
        p = self.run_script(stdin="1\n")
        self.assertIn("more than one server", p.stdout)
        self.assertEqual(p.returncode, 0, p.stdout)
        p = self.run_script(stdin="3\n")
        self.assertNotEqual(p.returncode, 0)
        p = self.run_script("--guild", "1")
        self.assertEqual(p.returncode, 0)


class TestSecretsAndWords(Base):
    def test_token_never_in_output_or_files(self):
        self.apply("--delete-old-roles", stdin="YES\nDELETE ROLES\n")
        self.apply()
        self.run_script()
        bad = self.tmp / "bad.txt"
        bad.write_text("Bot not-the-right-one\n")
        p = self.run_script(token_file=bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("didn't accept that token", p.stdout + p.stderr)
        self.assertNotIn("not-the-right-one", p.stdout + p.stderr)
        for out in self.outputs:
            self.assertNotIn(TOKEN, out)
            self.assertNotIn(TOKEN[:20], out)
        for f in self.tmp.rglob("*"):
            if f.is_file() and f != self.token_file:
                self.assertNotIn(TOKEN, f.read_text(encoding="utf-8", errors="replace"), str(f))
        # the token only ever travels in the Authorization header
        for m, path, body, headers, _ in self.fake.log:
            self.assertNotIn(TOKEN, path + json.dumps(body))

    def test_no_banned_words_or_versions(self):
        texts = [dl.SERVER_NAME, dl.ARCHIVE, dl.WELCOME_DRAFT, dl.HELP_DRAFT]
        for cat, chans in dl.LAYOUT:
            texts.append(cat)
            for name, _, topic, *_ in chans:
                texts += [name, topic or ""]
        texts += [n for n, *_ in dl.ROLES]
        for t in texts:
            self.assertIsNone(dl.BANNED.search(t), t)
        self.apply()
        for m, path, body, *_ in self.fake.writes():
            for b in (body if isinstance(body, list) else [body or {}]):
                for k in ("name", "topic"):
                    if isinstance(b.get(k), str):
                        self.assertIsNone(dl.BANNED.search(b[k]), b[k])
        # the guard itself catches what it should
        for bad in ("World of Warcraft", "WoW", "warcraft", "Lich King", "Blizzard", "3.3.5a", "1.12"):
            self.assertIsNotNone(dl.BANNED.search(bad), bad)

    def test_welcome_draft(self):
        for s in (dl.LINK_PLAY, dl.LINK_LAUNCHER, dl.LINK_HOST, "TODO(owner)", "Hero Key", "password",
                  "Be decent", "mod launcher"):
            self.assertIn(s, dl.WELCOME_DRAFT)
        self.assertIn("TODO(owner)", dl.HELP_DRAFT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
