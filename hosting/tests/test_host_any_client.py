"""Host any client: the host kit's realm profiles on other server cores (hosting/kit/profiles/<id>/, their facts in
tools/wuhost/cores.py). Pinned sources, no downloads in the extractors, licences, the compose files' isolation, the
account glue per core (checked against each core's own maths and data), setup's listing fields, the self-check's
probes per build, the join pages and the relay's status, and the launcher's table.

Nothing here builds a server (no C++ compiles on this machine): CI or a host's PC does that from the same files.
"""
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import helpers  # noqa: F401
from helpers import Rig, http
from wunet import srp6, wire335
from wuhost import cores, coredb, selfcheck

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTING = os.path.dirname(HERE)
REPO = os.path.dirname(HOSTING)
KIT = os.path.join(HOSTING, "kit")
PROFILES = os.path.join(KIT, "profiles")
sys.path.insert(0, os.path.join(REPO, "tools", "leyline-repo"))
import export  # noqa: E402  (the Leyline export's safety and naming rules)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
# The same CMaNGOS recipe in both CMaNGOS profiles (the tests keep the copies identical).
CMANGOS_SHARED = ("Dockerfile", "extract.sh", "db-import.sh", "run-server.sh", "leyline-mangosd.conf", "leyline-realmd.conf")


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def lock(profile):
    out = {}
    for ln in read(PROFILES, profile, "profile.lock").splitlines():
        m = re.match(r"^(LL_[A-Z0-9_]+)=(.+)$", ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


class Profiles(unittest.TestCase):
    def test_every_profile_has_its_folder_and_files(self):
        on_disk = sorted(d for d in os.listdir(PROFILES) if os.path.isfile(os.path.join(PROFILES, d, "profile.lock")))
        self.assertEqual(on_disk, sorted(cores.PROFILES), "cores.py and profiles/ list the same profiles")
        for pid, p in cores.PROFILES.items():
            lk = lock(pid)
            self.assertEqual((lk["LL_PROFILE"], lk["LL_CORE"], int(lk["LL_BUILD"]), lk["LL_VERSION"]),
                             (pid, p["core"], p["build"], p["version"]), pid)
            self.assertEqual(cores.BUILDS[p["build"]], p["version"])
            for f in ("Dockerfile", "extract.sh", "run-server.sh", "NOTICE.md", lk["LL_COMPOSE"]):
                self.assertTrue(os.path.isfile(os.path.join(PROFILES, pid, f)), f"{pid}/{f}")
            self.assertRegex(lk["LL_COMPOSE"], rf"^docker-compose\.{re.escape(pid)}\.yml$")
            self.assertTrue(lk["LL_IMAGE"].startswith("leyline-"), pid)
            self.assertTrue(lk.get("LL_READY") and lk.get("LL_CLIENT_FILES"), pid)
            df = read(PROFILES, pid, "Dockerfile")
            for target in ("source", "build", "server", "extractors", "db-import"):
                self.assertRegex(df, rf"(?m)^FROM \S+ AS {target}$", f"{pid}: stage {target}")

    def test_sources_are_pinned(self):
        for pid in cores.PROFILES:
            lk = lock(pid)
            self.assertRegex(lk["LL_CORE_COMMIT"], HEX40, pid)
            self.assertTrue(lk["LL_CORE_REPO"].startswith("https://github.com/"), pid)
            if "LL_DB_COMMIT" in lk:     # the world database in git: the commit pins every byte
                self.assertRegex(lk["LL_DB_COMMIT"], HEX40, pid)
                self.assertTrue(lk["LL_DB_REPO"].startswith("https://github.com/"), pid)
            else:                        # a release file: a sha256, or the owner's TODO (then the kit refuses it)
                self.assertTrue(lk["LL_DB_URL"].startswith("https://github.com/"), pid)
                self.assertTrue(re.match(r"^[0-9a-f]{64}$", lk["LL_DB_SHA256"]) or "TODO" in read(PROFILES, pid, "profile.lock"),
                                pid)
            df = read(PROFILES, pid, "Dockerfile")
            self.assertIn('git rev-parse HEAD)" = "', df, f"{pid}: the checkout is checked against the pin")
            self.assertIn("HTTPS", df.upper())
            if "LL_DB_URL" in lk:
                self.assertIn("sha256sum -c", df, f"{pid}: the release file is checked")

    def test_cmangos_copies_are_identical(self):
        for f in CMANGOS_SHARED:
            self.assertEqual(read(PROFILES, "cmangos-1.12.1", f), read(PROFILES, "cmangos-2.4.3", f), f)

    def test_extractors_read_the_hosts_client_and_download_nothing(self):
        for pid in cores.PROFILES:
            ex = read(PROFILES, pid, "extract.sh")
            code = "\n".join(ln for ln in ex.splitlines() if not ln.lstrip().startswith("#"))
            for word in ("curl", "wget", "git ", "http://", "https://", "apt-get", "pip "):
                self.assertNotIn(word, code, f"{pid}/extract.sh: {word}")
            self.assertIn("C=/client", code)
            self.assertIn("D=/data", code)
            # the extractors stage holds only the core's tools and our script
            df = read(PROFILES, pid, "Dockerfile")
            stage = df.split(" AS extractors")[1].split("\nFROM ")[0]
            self.assertNotRegex(stage, r"curl|wget|ADD ", pid)
        host = read(PROFILES, "host-profile.sh")
        bat = read(PROFILES, "Host a profile realm.bat")
        self.assertIn('-v "$client:/client:ro"', host)
        self.assertIn('-v "%CLIENT%:/client:ro"', bat)

    def test_licences_and_notices(self):
        for pid in cores.PROFILES:
            df = read(PROFILES, pid, "Dockerfile")
            self.assertIn("/licenses/SOURCES.txt", df)
            self.assertGreaterEqual(df.count("COPY --from=source /licenses /licenses"), 2, pid)
            notice = read(PROFILES, pid, "NOTICE.md")
            lk = lock(pid)
            self.assertIn(lk["LL_CORE_REPO"], notice, pid)
            self.assertIn("GPL-2.0", notice)
            self.assertIn("Game data", notice)

    def test_compose_files_keep_the_realm_off_the_network(self):
        for pid, p in cores.PROFILES.items():
            lk = lock(pid)
            yml = read(PROFILES, pid, lk["LL_COMPOSE"])
            self.assertNotRegex(yml, r"(?m)^\s+ports:", f"{pid}: nothing published")
            self.assertIn("internal: true", yml)
            self.assertRegex(yml, r"(?m)^  realm-logon:$")
            self.assertRegex(yml, r"(?m)^  realm-world:$")
            self.assertEqual((cores.LOGON, cores.WORLD), ("realm-logon:3724", "realm-world:8085"))
            self.assertIn("container_name: wu-host-realm-world", yml, "host-profile.sh waits on its log")
            self.assertIn(f"WU_CORE: {p['core']}", yml)
            self.assertIn(f"WU_DB_AUTH: {p['databases']['auth']}", yml)
            self.assertIn(f"WU_DB_CHARS: {p['databases']['chars']}", yml)
            self.assertIn(f'WU_EXPANSION: "{p["expansion"]}"', yml)
            vol = "leyline-" + lk["LL_IMAGE"][len("leyline-"):] + "-client-data"
            self.assertIn(f"name: {vol}", yml, "the volume host-profile.sh fills")
            self.assertRegex(yml, r"client-data:/data:ro")
            self.assertIn("read_only: true", yml)
            self.assertIn("cap_drop: [ALL]", yml)

    def test_db_import_removes_the_sample_accounts(self):
        di = read(PROFILES, "cmangos-1.12.1", "db-import.sh")
        self.assertIn("'ADMINISTRATOR', 'GAMEMASTER', 'MODERATOR', 'PLAYER'", di)
        self.assertIn("-InstallAll", di)
        self.assertRegex(di, r'if ! has_table "\$REALM" account; then\n.*\n\s+run -InstallAll',
                         "the destructive install only when there are no accounts yet")

    def test_safe_to_publish(self):
        """export.py's rules over every file of the profiles (game data, secrets, decompiled code, the naming rule)."""
        for d, _, names in os.walk(PROFILES):
            for n in names:
                p = os.path.join(d, n)
                rel = os.path.relpath(p, REPO).replace(os.sep, "/")
                with open(p, "rb") as fh:
                    data = fh.read()
                self.assertIsNone(export.refusal(rel, data), rel)
                self.assertEqual(export.brand_hits(rel, data), [], rel)

    def test_line_ends(self):
        for d, _, names in os.walk(PROFILES):
            for n in names:
                self.assertNotIn(b"\r\n", open(os.path.join(d, n), "rb").read(), n)   # the kit zip writes .bat CRLF


class HostScript(unittest.TestCase):
    def sh(self, body):
        script = (f'KIT={json.dumps(KIT)}; die() {{ echo "DIE: $*"; exit 3; }}; say() {{ echo "$*"; }}\n'
                  f'. "$KIT/profiles/host-profile.sh"\n{body}')
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)

    def test_lock_and_build_args(self):
        r = self.sh('profile_lock cmangos-2.4.3; echo "$LL_TAG|$LL_IMAGE|$LL_READY"; profile_build_args; profile_volume')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out[0], "2.4.3-37767e954241|leyline-cmangos-243|World initialized")
        self.assertIn("LL_CORE_COMMIT=37767e954241e346453260b8bc8c1fb2e2afdf7d", out)
        self.assertIn("LL_DB_REPO=https://github.com/cmangos/tbc-db", out)
        self.assertEqual(out[-1], "leyline-cmangos-243-client-data")

    def test_known_and_listed(self):
        r = self.sh('profile_list; profile_known cmangos-1.12.1 && echo yes; profile_known ../x || echo no; '
                    'profile_known dalaran || echo no')
        self.assertEqual(r.stdout.split(), sorted(cores.PROFILES) + ["yes", "no", "no"])

    def test_an_unpinned_database_is_refused(self):
        lk = lock("tcpp-4.3.4")
        if re.match(r"^[0-9a-f]{64}$", lk["LL_DB_SHA256"]):
            self.skipTest("pinned")
        r = self.sh("profile_lock tcpp-4.3.4; echo built")
        self.assertIn("DIE: The 4.3.4 profile is not ready yet", r.stdout)
        self.assertNotIn("built", r.stdout)

    def test_client_folder_check(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Data"))
            r = self.sh(f'profile_lock cmangos-2.4.3; profile_is_client {json.dumps(d)} && echo yes || echo no')
            self.assertEqual(r.stdout.strip(), "no")
            for f in ("common.MPQ", "expansion.mpq"):
                open(os.path.join(d, "Data", f), "w").close()
            r = self.sh(f'profile_lock cmangos-2.4.3; profile_is_client {json.dumps(d)} && echo yes || echo no')
            self.assertEqual(r.stdout.strip(), "yes")

    def test_entry_points_route_to_the_profiles(self):
        hw = read(KIT, "host-wrath-realm.sh")
        self.assertIn('profile_up "$WU_PROFILE"; return', hw)
        self.assertIn('profiles/$(state_get profile)"/docker-compose.*.yml', hw)
        bat = read(KIT, "Host a Wrath realm.bat")
        self.assertIn('call "%~dp0profiles\\Host a profile realm.bat"', bat)
        for b in ("Check my realm.bat", "Stop my realm.bat", "Realm tools.bat"):
            self.assertIn('call "%~dp0profiles\\pick-compose.bat"', read(KIT, b), b)
        for f in ("host-wrath-realm.sh", "leyline", os.path.join("profiles", "host-profile.sh")):
            subprocess.run(["bash", "-n", os.path.join(KIT, f)], check=True)


# ---------------------------------------------------------------------------------------- the account glue
# CMaNGOS's own sample account, from sql/base/realmd.sql of cmangos/mangos-classic (and mangos-tbc) at the pinned
# commits: ADMINISTRATOR / ADMINISTRATOR, v and s as the core stores them (BigNumber::AsHexStr).
CM_V = "312B99EEF1C0196BB73B79D114CE161C5D089319E6EF54FAA6117DAB8B672C14"
CM_S = "8EB5DE915AA3D805FA7099CF61C0BB8A77990EA869078A0C5B9EEE55828F4505"


class FakeCursor:
    def __init__(self, log, answers):
        self.log, self.answers = log, answers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        self.log.append((" ".join(sql.split()), args))

    def fetchone(self):
        return self.answers.pop(0) if self.answers else None


class FakeConn:
    def __init__(self, log, answers):
        self.log, self.answers = log, answers

    def cursor(self):
        return FakeCursor(self.log, self.answers)

    def close(self):
        pass


def fake_db(cls, answers=None, **kw):
    db = cls("db", 3306, "root", "pw", **kw)
    db.log, db.dbs = [], []
    ans = list(answers or [])

    def conn(name):
        db.dbs.append(name)
        return FakeConn(db.log, ans)
    db._conn = conn
    return db


class Glue(unittest.TestCase):
    def test_cmangos_hex_against_the_cores_own_account(self):
        salt = coredb.from_mangos_hex(CM_S)
        _, ver = srp6.make_verifier("ADMINISTRATOR", "ADMINISTRATOR", salt)
        self.assertEqual(coredb.to_mangos_hex(ver.hex()), CM_V, "our verifier in CMaNGOS's form is the core's own")
        self.assertEqual(coredb.to_mangos_hex(salt.hex()), CM_S)
        self.assertTrue(coredb.salt_ok(salt.hex()))

    def test_salts_are_32_bytes_on_every_core(self):
        self.assertFalse(coredb.salt_ok("00" * 32))
        self.assertFalse(coredb.salt_ok("11" * 31 + "00"), "a zero top byte: CMaNGOS would send 31 bytes")
        self.assertTrue(coredb.salt_ok("00" * 31 + "01"))
        for _ in range(300):
            self.assertNotEqual(srp6.new_salt()[-1], 0)
            self.assertNotEqual(srp6.make_verifier("A", "B")[0][-1], 0)

    def test_cmangos_accounts(self):
        salt, ver = srp6.make_verifier("ALICE", "PW")
        db = fake_db(coredb.CmangosDB, [None], auth="tbcrealmd", chars="tbccharacters", expansion=1)
        self.assertEqual(db.create_account("ALICE", salt.hex(), ver.hex()), "ok")
        self.assertEqual(db.dbs, ["tbcrealmd"])
        ins = db.log[1]
        self.assertTrue(ins[0].startswith("INSERT INTO account (username, gmlevel, v, s, joindate, expansion)"))
        self.assertEqual(ins[1], ("ALICE", 0, coredb.to_mangos_hex(ver.hex()), coredb.to_mangos_hex(salt.hex()), 1))
        self.assertIn("realmcharacters", db.log[2][0])
        bad = fake_db(coredb.CmangosDB)
        self.assertEqual(bad.create_account("BOB", "11" * 31 + "00", ver.hex()), "bad_salt")
        self.assertEqual(bad.log, [], "nothing written")
        taken = fake_db(coredb.CmangosDB, [(5,)])
        self.assertEqual(taken.create_account("ALICE", salt.hex(), ver.hex()), "taken")
        gm = fake_db(coredb.CmangosDB, [(0,)])
        self.assertEqual(gm.grant_gm("alice"), "ok")
        self.assertEqual(gm.log[-1], ("UPDATE account SET gmlevel = %s WHERE username = %s", (3, "ALICE")))
        self.assertEqual(fake_db(coredb.CmangosDB, [(3,)]).grant_gm("alice"), "unchanged")
        self.assertEqual(fake_db(coredb.CmangosDB, []).grant_gm("alice"), "missing")
        addr = fake_db(coredb.CmangosDB, [("Old", "127.0.0.1", 8085)])
        self.assertEqual(addr.set_realm_address("New", "1.2.3.4", 40001), "updated")
        self.assertNotIn("localAddress", addr.log[-1][0], "CMaNGOS's realmlist has no localAddress")

    def test_trinitycore_accounts(self):
        salt, ver = srp6.make_verifier("ALICE", "PW")
        db = fake_db(coredb.TrinityDB, [None, None])
        self.assertEqual(db.create_account("ALICE", salt.hex(), ver.hex(), gmlevel=3), "ok")
        self.assertEqual(db.dbs, ["auth"])
        self.assertEqual(db.log[1][1], ("ALICE", salt, ver, 3), "AzerothCore's bytes, expansion 3")
        self.assertIn("account_access (AccountID, SecurityLevel, RealmID)", db.log[2][0])
        gm = fake_db(coredb.TrinityDB, [(7,), None])
        self.assertEqual(gm.grant_gm("alice"), "ok")
        self.assertIn("ON DUPLICATE KEY UPDATE SecurityLevel", gm.log[-1][0])
        self.assertEqual(fake_db(coredb.TrinityDB).create_account("X", "00" * 32, ver.hex()), "bad_salt")

    def test_db_from_the_environment(self):
        self.assertIsNone(coredb.open_db({}))
        base = {"DB_HOST": "realm-db", "DB_PASSWORD": "pw"}
        cm = coredb.open_db(dict(base, WU_CORE="cmangos", WU_DB_AUTH="classicrealmd", WU_DB_CHARS="classiccharacters",
                                 WU_EXPANSION="0"))
        self.assertIsInstance(cm, coredb.CmangosDB)
        self.assertEqual((cm.AUTH, cm.CHARS, cm.expansion), ("classicrealmd", "classiccharacters", 0))
        self.assertIsInstance(coredb.open_db(dict(base, WU_CORE="trinitycore")), coredb.TrinityDB)
        ac = coredb.open_db(base)
        self.assertIs(type(ac), helpers.agentmod.RealmDB, "AzerothCore when WU_CORE is unset")


class Setup(unittest.TestCase):
    def setUp(self):
        self.kit = tempfile.mkdtemp(prefix="wu-kit-")
        os.environ["WU_KIT"] = self.kit
        import importlib
        from wuhost import setup
        self.setup = importlib.reload(setup)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.setup.main(list(argv))
        return out.getvalue(), err.getvalue()

    def test_init_for_another_client(self):
        self.run_cmd("init", "--name", "Old Times", "--profile", "cmangos-2.4.3", "--visibility", "public",
                     "--image", "leyline-cmangos-243", "--tag", "2.4.3-37767e954241")
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertEqual((cfg["auth_service"], cfg["world_service"]), ("realm-logon:3724", "realm-world:8085"))
        self.assertEqual((cfg["record"]["core"], cfg["record"]["build"]), ("cmangos", 8606))
        self.assertEqual((cfg["bots"], cfg["record"]["tags"]), (0, ["blizzlike"]))
        self.assertIn("2.4.3", cfg["record"]["tagline"])
        self.assertNotEqual(bytes.fromhex(cfg["gm"]["salt"])[-1], 0, "the generated GM login works on CMaNGOS")
        env = open(os.path.join(self.kit, ".env")).read()
        self.assertIn("WU_IMAGE=leyline-cmangos-243\n", env)
        with self.assertRaises(SystemExit) as cm:
            self.run_cmd("friend", "BOB")
        self.assertIn("join page", str(cm.exception))
        # back to a 3.3.5a profile: AzerothCore again
        self.run_cmd("init", "--profile", "dalaran")
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertEqual((cfg["auth_service"], cfg["record"]["core"], cfg["record"]["build"]),
                         ("ac-authserver:3724", "azerothcore", 12340))

    def test_every_profile_is_accepted(self):
        for pid, p in cores.PROFILES.items():
            self.run_cmd("init", "--name", "R", "--profile", pid, "--visibility", "private")
            cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
            self.assertEqual(cfg["record"]["build"], p["build"], pid)


class Probes(unittest.TestCase):
    def test_logon_challenge_per_build(self):
        for build, ver in ((5875, (1, 12, 1)), (8606, (2, 4, 3)), (12340, (3, 3, 5)), (15595, (4, 3, 4))):
            pkt = wire335.logon_challenge("PROBE", build)
            self.assertEqual(tuple(pkt[8:11]), ver, build)
            self.assertEqual(int.from_bytes(pkt[11:13], "little"), build)

    def test_world_greeting_per_build(self):
        self.assertTrue(selfcheck.world_ok(wire335.SMSG_AUTH_CHALLENGE, 8606))
        self.assertFalse(selfcheck.world_ok(0x1234, 5875))
        self.assertTrue(selfcheck.world_ok(0x1234, 15595), "4.3.4 greets differently: up is up")


class JoinSide(unittest.IsolatedAsyncioTestCase):
    async def test_status_says_which_client(self):
        async with Rig() as r:
            r.agent.cfg["record"] = dict(r.agent.cfg.get("record") or {}, build=8606)
            st, body, _ = await http("GET", f"{r.http}/r/{r.rid}/status.json")
            self.assertEqual((st, body["build"]), (200, "2.4.3"))

    def test_join_pages_name_the_client_and_draw_good_salts(self):
        for f in (os.path.join(HOSTING, "relay", "wurelay", "www", "join.html"), os.path.join(HOSTING, "site", "join", "index.html")):
            page = read(f)
            self.assertIn("if (!salt[31]) salt[31] = 1;", page)
            self.assertIn('forClient(st.doc.build)', page)
            for v in ("1.12.1", "2.4.3", "4.3.4"):
                self.assertIn(f'"{v}"', page)
            self.assertEqual(export.brand_hits(f, page.encode()), [])


class Launcher(unittest.TestCase):
    def test_launcher_table_matches_cores(self):
        rs = read(REPO, "launcher", "src-tauri", "src", "host", "profiles.rs")
        rows = re.findall(r'KitProfile \{ id: "([^"]+)", label: "[^"]*", build: Build::(\w+), core: "(\w+)", own_folder: (\w+) \}', rs)
        names = {"V1121": 5875, "V243": 8606, "V335a": 12340, "V434": 15595, "V548": 18414}
        other = {i: (names[b], c) for i, b, c, own in rows if own == "true"}
        self.assertEqual(other, {k: (p["build"], p["core"]) for k, p in cores.PROFILES.items()})


if __name__ == "__main__":
    unittest.main()
