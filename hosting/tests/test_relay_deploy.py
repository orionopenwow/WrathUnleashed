"""The "relay" step: hosting/relay/Deploy relay.bat + relay/deploy/relay-up.sh, run against stub
docker/curl/ss/free (no Docker daemon, no network, nothing deployed). Covers: DNS missing / pointing
elsewhere (plain instructions, exit 3, Caddy untouched), a clean install, an idempotent re-run, a failed
health check rolling back, Caddy refusing the block, and the memory cap."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTING = os.path.dirname(HERE)
ROOT = os.path.dirname(HOSTING)
SCRIPT = os.path.join(HOSTING, "relay", "deploy", "relay-up.sh")
BAT = os.path.join(HOSTING, "relay", "Deploy relay.bat")

DOCKER = r"""#!/usr/bin/env bash
S="$STUB_STATE"; echo "docker $*" >> "$S/docker.log"
case "$1" in
  compose)
    case " $* " in
      *" version "*) exit 0 ;;
      *" up "*) [ -f "$S/fail_up" ] && exit 1; touch "$S/running"; cp "$WU_RELAY_DIR/relay.env" "$S/running.env"; exit 0 ;;
      *" down "*) rm -f "$S/running"; exit 0 ;;
    esac ;;
  ps) echo "$WU_CADDY_CONTAINER"; echo wenilla-realm-mariadb-1; [ -f "$S/running" ] && echo wu-relay; exit 0 ;;
  network)
    case "$*" in *Gateway*) echo 172.18.0.1 ;; *Subnet*) echo 172.18.0.0/16 ;; esac; exit 0 ;;
  image) [ -f "$S/img_${3//[:\/]/_}" ]; exit $? ;;
  tag) [ -f "$S/img_${2//[:\/]/_}" ] || exit 1; cp "$S/img_${2//[:\/]/_}" "$S/img_${3//[:\/]/_}"; exit 0 ;;
  build) [ -f "$S/fail_build" ] && exit 1; n=$(cat "$S/builds" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$S/builds"
         echo "build$n" > "$S/img_wu-relay_1"; exit 0 ;;
  exec)
    case "$*" in
      *"caddy reload"*) [ -f "$S/fail_reload" ] && exit 1; exit 0 ;;
      *wget*) [ -f "$S/fail_caddy_reach" ] && exit 1; echo ok; exit 0 ;;
    esac ;;
  inspect) echo 201326592; exit 0 ;;
  logs|stats) echo "stub"; exit 0 ;;
esac
exit 0
"""
CURL = r"""#!/usr/bin/env bash
S="$STUB_STATE"; echo "curl $*" >> "$S/curl.log"
for a in "$@"; do u="$a"; done
case "$u" in
  http://*/healthz) [ -f "$S/fail_health" ] && exit 7; [ -f "$S/running" ] || exit 7; echo ok ;;
  http://*/api/listing/realms.json) echo '{"schema":1,"realms":[]}' ;;
  https://*/healthz) printf 200 ;;
  *) exit 6 ;;
esac
"""
SS = r"""#!/usr/bin/env bash
printf 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 128 0.0.0.0:3724 0.0.0.0:*\nLISTEN 0 128 0.0.0.0:8085 0.0.0.0:*\n'
[ -f "$STUB_STATE/extra_listen" ] && while read -r p; do printf 'LISTEN 0 128 0.0.0.0:%s 0.0.0.0:*\n' "$p"; done < "$STUB_STATE/extra_listen"
"""
FREE = "#!/usr/bin/env bash\necho '              total used free shared buff/cache available'\necho 'Mem:  3800 1000 500 10 2300 3300'\n"


class RelayDeploy(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="wu-relay-deploy-")
        self.bin = os.path.join(self.t, "bin")
        self.st = os.path.join(self.t, "stub")
        os.makedirs(self.bin)
        os.makedirs(self.st)
        for name, body in (("docker", DOCKER), ("curl", CURL), ("ss", SS), ("free", FREE)):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        # the upload, as the .bat packs it
        self.src = os.path.join(self.t, "src")
        for d in ("kit/tools/wunet", "relay/wurelay", "relay/deploy"):
            shutil.copytree(os.path.join(HOSTING, d), os.path.join(self.src, d),
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(HOSTING, "relay", "Dockerfile"), os.path.join(self.src, "relay", "Dockerfile"))
        # a Windows checkout: CRLF everywhere
        for dp, _, fs in os.walk(os.path.join(self.src, "relay", "deploy")):
            for fn in fs:
                p = os.path.join(dp, fn)
                data = open(p, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                open(p, "wb").write(data)
        self.cf = os.path.join(self.t, "Caddyfile")
        self.cf_orig = "play.openvanilla.app {\n\treverse_proxy realm:8090\n}\n"
        with open(self.cf, "w") as f:
            f.write(self.cf_orig)
        self.portal = os.path.join(self.t, "portal")
        os.makedirs(self.portal)
        self.dir = os.path.join(self.t, "opt-wu-relay")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_STATE=self.st,
                        WU_TEST="1", WU_RELAY_DIR=self.dir, WU_CADDYFILE=self.cf,
                        WU_CADDY_CONTAINER="wenilla-realm-caddy-1", WU_PORTAL_DIR=self.portal,
                        WU_PUBLIC_IP="203.0.113.10", WU_FAKE_DNS_A="203.0.113.10", WU_FAKE_DNS_AAAA="none",
                        WU_HEALTH_TRIES="2", WU_HEALTH_PAUSE="0")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def run_up(self, **env):
        e = dict(self.env, **env)
        p = subprocess.run(["bash", SCRIPT, self.src], env=e, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def flag(self, name, on=True):
        p = os.path.join(self.st, name)
        if on:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def read(self, *p):
        with open(os.path.join(*p)) as f:
            return f.read()

    def relay_env(self):
        return dict(l.split("=", 1) for l in self.read(self.dir, "relay.env").splitlines() if "=" in l and not l.startswith("#"))

    def test_dns_missing_says_what_to_add(self):
        rc, out = self.run_up(WU_FAKE_DNS_A="none")
        self.assertEqual(rc, 3, out)
        self.assertIn("ACTION NEEDED", out)
        self.assertIn("Type: A     Name: relay", out)
        self.assertIn("Value: 203.0.113.10", out)
        self.assertIn("Do NOT add an AAAA record", out)
        self.assertTrue(out.rstrip().endswith("RELAY WAITING FOR DNS"), out[-300:])
        self.assertNotIn("RELAY OK", out)
        self.assertEqual(self.read(self.cf), self.cf_orig)            # no certificate attempts yet
        env = self.relay_env()
        self.assertEqual(env["RELAY_HTTP_BIND"], "172.18.0.1:8099")
        self.assertEqual(env["RELAY_TRUSTED_PROXIES"], "127.0.0.1/32,172.18.0.0/16")
        self.assertEqual(env["RELAY_SHARED_AUTH_PORT"], "0")         # 3724 is the realm's own authserver
        self.assertRegex(env["RELAY_LISTING_SITE_SECRET"], r"^[0-9a-f]{48}$")
        self.assertNotIn(env["RELAY_LISTING_SITE_SECRET"], out)       # never printed
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "relay.env")).st_mode), 0o600)
        self.assertNotIn("\r", self.read(self.dir, "relay.env") + self.read(self.dir, "compose.yml"))
        self.assertEqual(self.read(self.portal, "relay-listing.url"), "http://172.18.0.1:8099/api/listing/realms.json\n")
        # rerun once DNS is there: completes, same secret
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.relay_env()["RELAY_LISTING_SITE_SECRET"], env["RELAY_LISTING_SITE_SECRET"])

    def test_dns_pointing_elsewhere(self):
        rc, out = self.run_up(WU_FAKE_DNS_A="198.51.100.99", WU_FAKE_DNS_AAAA="2001:db8::1")
        self.assertEqual(rc, 3, out)
        self.assertIn("points at 198.51.100.99", out)
        self.assertIn("change it to 203.0.113.10", out)
        self.assertIn("also has an AAAA record", out)
        self.assertEqual(self.read(self.cf), self.cf_orig)

    def test_install_then_idempotent_rerun(self):
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.rstrip().endswith("RELAY OK"), out[-300:])
        cf = self.read(self.cf)
        self.assertTrue(cf.startswith(self.cf_orig.rstrip("\n")))
        self.assertIn("relay.openvanilla.app {", cf)
        self.assertIn("reverse_proxy 172.18.0.1:8099 {", cf)
        self.assertIn("header_up X-Forwarded-For {remote_host}", cf)
        self.assertIn("respond @metrics 403", cf)
        compose = self.read(self.dir, "compose.yml")
        self.assertIn("mem_limit: ${WU_RELAY_MEM:-192m}", compose)
        self.assertIn("network_mode: host", compose)
        self.assertNotIn("caddy", re.sub(r"#.*", "", compose).lower())   # uses the site's Caddy, no second one
        self.assertIn("WU_RELAY_MEM=192m", self.read(self.dir, ".env"))
        secret = self.relay_env()["RELAY_LISTING_SITE_SECRET"]
        log = self.read(self.st, "docker.log")
        self.assertIn("exec wenilla-realm-caddy-1 caddy reload", log)
        self.assertIn("exec wenilla-realm-caddy-1 wget", log)                # health checked through Caddy's network
        # second run: one block, same secret, a backup with the previous Caddyfile and image
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        cf2 = self.read(self.cf)
        self.assertEqual(cf2.count("relay.openvanilla.app {"), 1)
        self.assertEqual(cf2.count("# >>> WrathUnleashed Beacons relay"), 1)
        self.assertEqual(self.relay_env()["RELAY_LISTING_SITE_SECRET"], secret)
        self.assertTrue(os.path.exists(os.path.join(self.st, "img_wu-relay_rollback")))
        bks = os.listdir(os.path.join(self.dir, "backups"))
        self.assertTrue(bks)
        latest = os.path.join(self.dir, "backups", sorted(bks)[-1])
        self.assertTrue(os.path.exists(os.path.join(latest, "Caddyfile")))
        self.assertTrue(os.path.exists(os.path.join(latest, "relay.env")))

    def test_taken_web_port_moves_to_a_free_one_and_stays(self):
        # live 2026-10-25: 8099 was taken on the box
        with open(os.path.join(self.st, "extra_listen"), "w") as f:
            f.write("8099\n8100\n")
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        self.assertIn("uses 8101", out)
        self.assertTrue(self.relay_env()["RELAY_HTTP_BIND"].endswith(":8101"))
        self.assertIn("reverse_proxy 172.18.0.1:8101 {", self.read(self.cf))
        # a re-run keeps its port even though 8099 is still taken
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.relay_env()["RELAY_HTTP_BIND"].endswith(":8101"))
        self.assertEqual(self.read(self.cf).count("relay.openvanilla.app {"), 1)

    def test_failed_health_rolls_back(self):
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        before_env, before_cf = self.read(self.dir, "relay.env"), self.read(self.cf)
        self.flag("fail_health")
        rc, out = self.run_up(WU_RELAY_HTTP_PORT="8100")       # an update that breaks
        self.assertEqual(rc, 1, out)
        self.assertIn("RELAY FAILED", out)
        self.assertIn("rolled back", out)
        self.assertNotIn("RELAY OK", out)
        self.assertEqual(self.read(self.dir, "relay.env"), before_env)          # config put back
        self.assertEqual(self.read(self.cf), before_cf)                          # Caddy untouched
        self.assertEqual(self.read(self.st, "img_wu-relay_1"), "build1\n")       # the old image is back
        self.assertIn("docker tag wu-relay:rollback wu-relay:1", self.read(self.st, "docker.log"))

    def test_first_install_failing_leaves_nothing_running(self):
        self.flag("fail_caddy_reach")
        rc, out = self.run_up()
        self.assertEqual(rc, 1, out)
        self.assertIn("cannot reach the relay", out)
        self.assertFalse(os.path.exists(os.path.join(self.st, "running")))
        self.assertEqual(self.read(self.cf), self.cf_orig)

    def test_caddy_refusing_restores_the_caddyfile(self):
        self.flag("fail_reload")
        rc, out = self.run_up()
        self.assertEqual(rc, 1, out)
        self.assertIn("Caddy refused", out)
        self.assertEqual(self.read(self.cf), self.cf_orig)

    def test_build_failure_changes_nothing_running(self):
        rc, _ = self.run_up()
        self.assertEqual(rc, 0)
        env_before = self.read(self.dir, "relay.env")
        self.flag("fail_build")
        rc, out = self.run_up(WU_RELAY_HTTP_PORT="8100")
        self.assertEqual(rc, 1, out)
        self.assertIn("building the relay image failed", out)
        self.assertEqual(self.read(self.dir, "relay.env"), env_before)

    def test_bat_matches_the_other_steps(self):
        bat = open(BAT).read()
        ssh = [l for l in bat.splitlines() if l.lstrip().lower().startswith("ssh ")]
        self.assertEqual(len(ssh), 1, "exactly one SSH login")
        line = ssh[0]
        self.assertIn('-i "%USERPROFILE%\\.ssh\\openwow"', line)
        self.assertIn("root@play.openvanilla.app", line)
        self.assertIn("sed 's/\\r$//'", line)
        self.assertIn("'^RELAY OK'", line)
        self.assertTrue(line.rstrip().endswith('< "%TGZ%"'))       # the payload goes over stdin
        self.assertNotIn("scp", bat.lower())
        for need in ("kit/tools/wunet", "relay/wurelay", "relay/Dockerfile", "relay/deploy"):
            self.assertIn(need, bat)
        ctl = open(os.path.join(ROOT, "tools", "control", "control.py")).read()
        self.assertIn('"relay": ("hosting/relay/Deploy relay.bat", "Beacons relay (relay.openvanilla.app)", False)', ctl)

    def test_script_syntax(self):
        subprocess.run(["bash", "-n", SCRIPT], check=True)


if __name__ == "__main__":
    unittest.main()
