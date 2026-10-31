"""tools/security and the hardening around it: secrets never leave the server in the Caddy check, the Caddyfile
hardening is right and idempotent, the firewall is a dry run unless told and fills its own chain idempotently,
the CI deploy key's forced command takes only realm scripts the realm already runs, the key migration keeps the key
and adds the command, and the chat anti-spam settings are the same in the profile and the Server pass.

    python3 -I tools/security/test_security.py
"""
import importlib.util
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


R = load("wu_redact", HERE / "redact.py")
H = load("wu_harden", HERE / "caddyfile_harden.py")


class Redact(unittest.TestCase):
    def test_secrets_go(self):
        text = (
            "{\n\temail me@example.com\n}\nplay.openvanilla.app {\n\tbasicauth /x* {\n\t\tbob $2a$14$Zkx19XLiW6VYouLHR5NmfOFU0z2GTNmpkT/5qqR7hx4IjWJPDhjvG\n\t}\n"
            "\ttls {\n\t\tdns cloudflare tok123\n\t}\n\treverse_proxy x:1 {\n\t\theader_up Authorization \"Bearer abc\"\n\t}\n}\n"
            "services:\n  db:\n    environment:\n      MYSQL_ROOT_PASSWORD: hunter2\n      - SOAP_PASS=abc\n"
            "      AC_LOGIN_DATABASE_INFO: \"ac-database;3306;root;pw;acore_auth\"\n      URL: mysql://root:pw2@db/x\n"
            "      GM_TOKEN=zzz\n      PORTAL_URL: http://ovlive-realm:8090\n-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n")
        out = R.redact(text)
        for secret in ("hunter2", "=abc", "tok123", "Bearer abc", "Zkx19", "pw2", "zzz", "AAAA\n", ";pw;"):
            self.assertNotIn(secret, out, secret)
        self.assertIn("PORTAL_URL: http://ovlive-realm:8090", out)
        self.assertIn("reverse_proxy x:1 {", out)
        self.assertIn("bob <redacted>", out)

    def test_check_script_never_prints_env_files(self):
        sh = (HERE / "caddy-check.sh").read_text()
        self.assertIn("names only", sh)
        self.assertNotRegex(sh, r"cat [^\n]*\.env")
        self.assertIn("python3 -I redact.py \"$CF\"", sh)
        self.assertTrue(sh.rstrip().endswith('echo "CADDY CHECK OK"'))


CF = """{
\temail owner@example.com
}

play.openvanilla.app {
\thandle /wrath* {
\t\treverse_proxy wu-portal:8091
\t}
\treverse_proxy ovlive-realm:8090
}

# >>> WrathUnleashed streaming (stream-up.sh): x
wrath.openvanilla.app {
\trequest_body {
\t\tmax_size 2MB
\t}
\treverse_proxy wu-play:8090 {
\t\tflush_interval -1
\t}
}
"""


class Harden(unittest.TestCase):
    def test_adds_timeouts_and_body_cap(self):
        out, did = H.harden(CF)
        self.assertIn("\tservers {\n\t\ttimeouts {\n\t\t\tread_header 10s\n\t\t\tread_body 30s\n\t\t\tidle 120s", out)
        self.assertNotIn("write", out, "no write timeout: downloads and WebSockets stay open")
        play = out[out.index("play.openvanilla.app {"):out.index("# >>>")]
        self.assertIn("request_body /wrath* {\n\t\tmax_size 2MB", play)
        self.assertEqual(out.count("request_body"), 2, "the stream site already had one")
        self.assertIn("email owner@example.com", out)
        again, did2 = H.harden(out)
        self.assertEqual(again, out, "idempotent")
        self.assertEqual(did2, [])

    def test_no_global_block(self):
        out, _ = H.harden("play.openvanilla.app {\n\treverse_proxy x:1\n}\n")
        self.assertTrue(out.startswith("{\n\tservers {"))
        self.assertEqual([b[3] for b in H.blocks(out)], ["", "play.openvanilla.app"])

    def test_existing_servers_block(self):
        out, _ = H.harden("{\n\tservers {\n\t\tprotocols h1 h2\n\t}\n}\nplay.openvanilla.app {\n}\n")
        self.assertEqual(out.count("servers {"), 1)
        self.assertIn("protocols h1 h2", out)
        self.assertIn("read_body 30s", out)

    def test_apply_is_a_draft_with_rollback(self):
        sh = (HERE / "caddy-apply.sh").read_text()
        self.assertIn("DRAFT", sh)
        self.assertIn('APPLY=""; [ "${1:-}" = "--apply" ] && APPLY=1', sh)
        self.assertIn("older than 2.7", sh)
        self.assertGreaterEqual(sh.count('cat "$BK/Caddyfile" > "$CF"'), 2)

    def test_stream_up_caps_bodies(self):
        sh = (REPO / "stream/server/stream-up.sh").read_text()
        block = sh[sh.index("$STREAM_HOST {"):sh.index("$MARK_END")]
        self.assertIn("request_body {\n\t\tmax_size 2MB\n\t}", block)
        self.assertIn("flush_interval -1", block)


class Firewall(unittest.TestCase):
    def run_fw(self, *args, chains=True):
        d = tempfile.mkdtemp()
        log = Path(d, "calls")
        fake = Path(d, "iptables")
        # a fake iptables: the chains "exist" when chains=True; -C (check) says "no"; every call is logged
        fake.write_text("#!/bin/sh\necho \"$0 $*\" >> %s\ncase \"$*\" in *-C*) exit 1;; *-L*) %s;; esac\nexit 0\n"
                        % (log, "exit 0" if chains else "exit 1"))
        fake.chmod(0o755)
        Path(d, "ip").write_text("#!/bin/sh\nexit 1\n"); Path(d, "ip").chmod(0o755)
        env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}", WU_FW_IF="eth9", WU_AUTH_LOG=str(Path(d, "Auth.log")))
        p = subprocess.run(["bash", str(HERE / "firewall.sh"), *args], env=env, capture_output=True, text=True)
        return p, (log.read_text() if log.exists() else "")

    def test_dry_run_by_default_changes_nothing(self):
        p, calls = self.run_fw()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("FIREWALL DRY", p.stdout)
        self.assertNotRegex(calls, r" -(A|I|N|F|X|D) ", "a dry run only looks")
        for port in ("3724", "8085", "40000:40999", "443", "80"):
            self.assertIn(f"--ctorigdstport {port} -m connlimit", p.stdout)
        self.assertIn("--connlimit-above 10 --connlimit-mask 32", p.stdout)
        self.assertIn("-I DOCKER-USER 1 -j WU-LIMIT", p.stdout)
        self.assertIn("-i eth9", p.stdout)
        self.assertIn("chain=DOCKER-USER", p.stdout)
        self.assertIn("tried to login with invalid password", p.stdout)

    def test_web_limits_can_be_off(self):
        d = dict(os.environ)
        os.environ["WU_FW_WEB"] = "0"
        try:
            p, _ = self.run_fw()
        finally:
            os.environ.clear(); os.environ.update(d)
        self.assertNotIn("--ctorigdstport 443", p.stdout)
        self.assertIn("--ctorigdstport 3724", p.stdout)

    def test_hashlimit_names_fit(self):
        sh = (HERE / "firewall.sh").read_text()
        self.assertIn('name="wu${p//:/-}${M}"', sh)
        self.assertLessEqual(len("wu40000-4099964"), 15)

    def test_filter_matches_the_authserver_line(self):
        import re
        line = "'203.0.113.9:51234' [AuthChallenge] account BOB tried to login with invalid password!"
        rx = r"^'(?P<host>[^:']+):\d+' \[AuthChallenge\] account \S+ tried to login with invalid password!$"
        self.assertRegex(line, rx)
        sh = (HERE / "firewall.sh").read_text()
        self.assertIn(r"failregex = ^'<HOST>:\d+' \[AuthChallenge\] account \S+ tried to login with invalid password!\$", sh)


def tar_of(path, files, extra=None):
    with tarfile.open(path, "w") as t:
        for name, data in files.items():
            p = Path(path).with_name("src_" + name.replace("/", "_"))
            p.write_bytes(data)
            t.add(p, arcname=name)
        if extra:
            extra(t)
    return path


class LuaupCI(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.lua = self.d / "custom/lua_scripts"
        self.lua.mkdir(parents=True)
        (self.lua / "ov_main.lua").write_text("-- old\n")
        self.fake = self.d / "luaup.sh"
        self.fake.write_text("#!/bin/bash\nmkdir -p %s/got && tar -x -C %s/got -f - && ls %s/got && echo 'LUAUP OK'\n" % ((self.d,) * 3))

    def run_ci(self, tar_path):
        env = dict(os.environ, WU_DIR=str(self.d), WU_LUAUP=str(self.fake), SSH_ORIGINAL_COMMAND="rm -rf /")
        with open(tar_path, "rb") as f:
            return subprocess.run(["bash", str(REPO / "server/luaup-ci.sh")], stdin=f, env=env, capture_output=True, text=True)

    def test_known_script_goes_through(self):
        p = self.run_ci(tar_of(self.d / "a.tar", {"ov_main.lua": b"-- new\n"}))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("LUAUP OK", p.stdout)
        self.assertEqual((self.d / "got/ov_main.lua").read_text(), "-- new\n")

    def test_dot_slash_tar_from_the_workflow(self):
        src = self.d / "up"; src.mkdir(); (src / "ov_main.lua").write_text("x\n")
        subprocess.run(["tar", "-cf", str(self.d / "w.tar"), "-C", str(src), "."], check=True)
        p = self.run_ci(self.d / "w.tar")
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_refusals(self):
        cases = {
            "new script": {"ov_new.lua": b"x"},
            "not lua": {"evil.sh": b"x"},
            "path": {"../ov_main.lua": b"x"},
            "binary": {"ov_main.lua": b"\0\1"},
        }
        for why, files in cases.items():
            p = self.run_ci(tar_of(self.d / "r.tar", files))
            self.assertNotEqual(p.returncode, 0, why)
            self.assertIn("LUAUP REFUSED", p.stderr, why)
            self.assertFalse((self.d / "got").exists(), why)

        def link(t):
            info = tarfile.TarInfo("ov_main.lua"); info.type = tarfile.SYMTYPE; info.linkname = "/etc/passwd"
            t.addfile(info)
        p = self.run_ci(tar_of(self.d / "l.tar", {}, link))
        self.assertIn("LUAUP REFUSED", p.stderr)
        (self.d / "junk").write_bytes(b"not a tar at all" * 100)
        p = self.run_ci(self.d / "junk")
        self.assertIn("LUAUP REFUSED", p.stderr)

    def test_workflow_and_setup_use_it(self):
        wf = (REPO / "tools/github-workflows/realm-scripts.yml").read_text()
        deploy = wf[wf.index("deploy (reload ale)"):]
        self.assertIn("-T root@play.openvanilla.app < /tmp/up.tar", deploy)
        self.assertNotIn("bash $T", deploy, "no remote shell command any more")
        self.assertNotIn("luaup.sh.txt", deploy)
        bat = (REPO / "setup/Set up automatic deploys.bat").read_text()
        self.assertIn("echo 'restrict,command=\\\"/srv/wrath/luaup-ci.sh\\\" '\\\"$k\\\"", bat)
        self.assertIn("sed -i '/ wu-deploy-github-actions$/d'", bat)
        self.assertNotIn('echo \\"restrict $k\\"', bat)


class CIKeyMigrate(unittest.TestCase):
    def test_rewrites_the_line_keeps_the_key(self):
        d = Path(tempfile.mkdtemp())
        ak = d / "authorized_keys"
        owner = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOwner owner@pc"
        ci = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICIkey wu-deploy-github-actions"
        ak.write_text(f"{owner}\nrestrict {ci}\n")
        work = d / "w"; work.mkdir()
        for f in ("ci-key-migrate.sh",):
            (work / f).write_text((HERE / f).read_text())
        (work / "luaup-ci.sh").write_text((REPO / "server/luaup-ci.sh").read_text())
        (work / "luaup.sh").write_text((REPO / "realm/luaup.sh").read_text())
        wu = d / "srv"; wu.mkdir()
        env = dict(os.environ, WU_AUTH_KEYS=str(ak), WU_DIR=str(wu))
        p = subprocess.run(["bash", str(work / "ci-key-migrate.sh")], env=env, capture_output=True, text=True)
        self.assertIn("CI KEY DRY", p.stdout, p.stderr)
        self.assertEqual(ak.read_text(), f"{owner}\nrestrict {ci}\n", "dry run: unchanged")
        self.assertNotIn("AAAAICIkey", p.stdout, "keys shortened in the output")
        p = subprocess.run(["bash", str(work / "ci-key-migrate.sh"), "--apply"], env=env, capture_output=True, text=True)
        self.assertIn("CI KEY OK", p.stdout, p.stderr)
        self.assertEqual(ak.read_text(), f'{owner}\nrestrict,command="{wu}/luaup-ci.sh" {ci}\n')
        self.assertTrue((wu / "luaup-ci.sh").is_file() and (wu / "luaup.sh").is_file())
        self.assertTrue(list(d.glob("authorized_keys.before-ci-*")))
        p = subprocess.run(["bash", str(work / "ci-key-migrate.sh"), "--apply"], env=env, capture_output=True, text=True)
        self.assertEqual(ak.read_text().count("command="), 1, "idempotent")


class ChatSettings(unittest.TestCase):
    WANT = {"AC_CHAT_FLOOD_MESSAGE_COUNT": "6", "AC_CHAT_FLOOD_MESSAGE_DELAY": "1", "AC_CHAT_FLOOD_MUTE_TIME": "30",
            "AC_CHAT_LEVEL_REQ_SAY": "1", "AC_CHAT_LEVEL_REQ_CHANNEL": "5", "AC_CHAT_LEVEL_REQ_WHISPER": "5",
            "AC_CHAT_STRICT_LINK_CHECKING_SEVERITY": "1", "AC_CHAT_STRICT_LINK_CHECKING_KICK": "0"}

    def test_profile_and_serverpass_agree(self):
        prof = dict(l.split("=", 1) for l in (REPO / "realm/profiles/main.env").read_text().splitlines()
                    if l and not l.startswith("#") and "=" in l)
        sp = (REPO / "realm/serverpass.sh").read_text()
        for k, v in self.WANT.items():
            self.assertEqual(prof.get(k), v, k)
            self.assertIn(f"{k}={v}", sp, k)


if __name__ == "__main__":
    unittest.main(verbosity=1)
