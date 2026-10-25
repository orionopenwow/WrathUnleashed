"""The "hangout" step: hosting/hangout/Deploy Dalaran hangout.bat + hangout-up.sh, against stub docker/curl (no Docker
daemon, no network, nothing deployed). The stub docker runs the REAL `setup.py official` for the config step.
Covers: a clean install (the key made there, 0600; the container's flags; the id files for the play page and the
in-game list), an idempotent re-run (same realm id), a failed connect rolling back to nothing, a failed listing on a
re-run rolling back to the previous agent, a missing relay changing nothing, --remove, and the .bat / step wiring."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTING = os.path.dirname(HERE)
ROOT = os.path.dirname(HOSTING)
SCRIPT = os.path.join(HOSTING, "hangout", "hangout-up.sh")
BAT = os.path.join(HOSTING, "hangout", "Deploy Dalaran hangout.bat")
OFF_BAT = os.path.join(HOSTING, "hangout", "Take Dalaran hangout off Leyline.bat")

DOCKER = r"""#!/usr/bin/env bash
S="$STUB_STATE"; echo "docker $*" >> "$S/docker.log"
rid() { python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["realm_id"])' "$WU_HANGOUT_DIR/state/host.json" 2>/dev/null; }
case "$1" in
  ps) for c in wu-relay ov-ac-authserver ov-ac-worldserver wu-portal; do [ -f "$S/down_$c" ] || echo $c; done
      [ -f "$S/agent" ] && echo wu-hangout-agent; [ -f "$S/auth" ] && echo wu-hangout-auth; exit 0 ;;
  inspect)
    case "$*" in
      *Config.Image*) echo "ov/ac-wotlk-authserver:custom" ;;
      *WorkingDir*) echo /azerothcore ;;
      *Config.Env*) printf 'PATH=/usr/bin\nAC_LOGIN_DATABASE_INFO=ac-database;3306;root;DBSECRET-sentinel;acore_auth\nAC_WRONG_PASS_MAX_COUNT=10\nAC_WRONG_PASS_BAN_TYPE=0\n' ;;
      *NetworkSettings.Networks*) printf 'ov-wotlk_backend\nov-wotlk_edge\n' ;;
    esac; exit 0 ;;
  exec) [ -f "$S/fail_auth" ] && exit 1; exit 0 ;;
  network)
    case "$2" in
      inspect) [ -f "$S/nonet_$3" ] && exit 1; [ "$4" = -f ] && [ -f "$S/auth" ] && echo wu-hangout-auth; exit 0 ;;
      connect) echo "$*" >> "$S/connect.log"; exit 0 ;;
    esac ;;
  image) [ -f "$S/img_${3//[:\/]/_}" ]; exit $? ;;
  tag) [ -f "$S/img_${2//[:\/]/_}" ] || exit 1; cp "$S/img_${2//[:\/]/_}" "$S/img_${3//[:\/]/_}"; exit 0 ;;
  build) [ -f "$S/fail_build" ] && exit 1; n=$(cat "$S/builds" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$S/builds"
         echo "build$n" > "$S/img_wu-hangout-tools_1"; exit 0 ;;
  rm) for a in "$@"; do [ "$a" = wu-hangout-agent ] && rm -f "$S/agent"; [ "$a" = wu-hangout-auth ] && rm -f "$S/auth"; done; exit 0 ;;
  logs) echo "stub agent log"; exit 0 ;;
  run)
    shift
    if [ "$1" = "-d" ] && [[ " $* " == *" --name wu-hangout-auth "* ]]; then
      echo "$*" > "$S/auth_args"; touch "$S/auth"; exit 0
    fi
    if [ "$1" = "-d" ]; then
      echo "$*" > "$S/agent_args"; cat "$S/img_wu-hangout-tools_1" > "$S/agent_image" 2>/dev/null
      touch "$S/agent"
      if [ ! -f "$S/fail_connect" ]; then printf '{"connected": true}' > "$WU_HANGOUT_DIR/state/relay-state.json"
      else printf '{"connected": false, "last_error": "relay refused: test"}' > "$WU_HANGOUT_DIR/state/relay-state.json"; fi
      exit 0
    fi
    # docker run --rm ... IMAGE python -m wuhost.setup ARGS: the real setup.py, /kit = the hangout folder
    args=(); seen=0
    for a in "$@"; do
      if [ $seen = 1 ]; then args+=("${a//\/kit\//$WU_HANGOUT_DIR/}"); fi
      [ "$a" = wuhost.setup ] && seen=1
    done
    WU_KIT="$WU_HANGOUT_DIR" PYTHONPATH="$STUB_SRC/kit/tools" python3 -m wuhost.setup "${args[@]}"; exit $? ;;
esac
exit 0
"""
CURL = r"""#!/usr/bin/env bash
S="$STUB_STATE"; echo "curl $*" >> "$S/curl.log"
for a in "$@"; do u="$a"; done
rid=$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["realm_id"])' "$WU_HANGOUT_DIR/state/host.json" 2>/dev/null)
case "$u" in
  http://*/healthz) [ -f "$S/relay_dead" ] && exit 7; echo ok ;;
  http://*/api/realms/*) [ -f "$S/agent" ] || exit 22; echo '{"online": true}' ;;
  http://*/r/*/status.json) [ -f "$S/agent" ] || exit 22; echo '{"online": true, "players": 4}' ;;
  http://*/api/listing/realms.json) if [ -f "$S/agent" ] && [ ! -f "$S/fail_listing" ]; then
      printf '{"realms": [{"community": {"realmId": "%s"}}]}' "$rid"; else echo '{"realms": []}'; fi ;;
  *) exit 6 ;;
esac
"""


class HangoutDeploy(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="wu-hangout-deploy-")
        self.bin, self.st = os.path.join(self.t, "bin"), os.path.join(self.t, "stub")
        os.makedirs(self.bin); os.makedirs(self.st)
        for name, body in (("docker", DOCKER), ("curl", CURL)):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        # the upload, as the .bat packs it (a Windows checkout: CRLF in the scripts)
        self.src = os.path.join(self.t, "src")
        for d in ("kit/tools/wunet", "kit/tools/wuhost", "hangout"):
            shutil.copytree(os.path.join(HOSTING, d), os.path.join(self.src, d), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(HOSTING, "kit", "tools", "Dockerfile"), os.path.join(self.src, "kit", "tools", "Dockerfile"))
        for fn in ("hangout-up.sh", "rules.txt"):
            p = os.path.join(self.src, "hangout", fn)
            data = open(p, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            open(p, "wb").write(data)
        self.relay_dir = os.path.join(self.t, "opt-wu-relay")
        os.makedirs(self.relay_dir)
        with open(os.path.join(self.relay_dir, "relay.env"), "w") as f:
            f.write("RELAY_NAME=relay.openvanilla.app\nRELAY_HTTP_BIND=172.18.0.1:8100\n")
        self.dir = os.path.join(self.t, "hangout-beacon")
        self.portal = os.path.join(self.t, "portal")
        self.wrath = os.path.join(self.t, "wrath")
        os.makedirs(self.portal); os.makedirs(self.wrath)
        with open(os.path.join(self.wrath, "leyline-fetch.py"), "w") as f:
            f.write(f"open({os.path.join(self.st, 'fetched')!r}, 'w').write('yes')\n")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_STATE=self.st, STUB_SRC=self.src,
                        WU_TEST="1", WU_HANGOUT_DIR=self.dir, WU_RELAY_DIR=self.relay_dir, WU_PORTAL_DIR=self.portal,
                        WU_WRATH_DIR=self.wrath, WU_HEALTH_TRIES="2", WU_HEALTH_PAUSE="0")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def run_up(self, *extra, **env):
        p = subprocess.run(["bash", SCRIPT, self.src] + list(extra), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def flag(self, name, on=True):
        p = os.path.join(self.st, name)
        if on:
            open(p, "w").close()
        elif os.path.exists(p):
            os.remove(p)

    def cfg(self):
        return json.load(open(os.path.join(self.dir, "state", "host.json")))

    def ids(self):
        out = []
        for d in (self.portal, self.wrath):
            p = os.path.join(d, "hangout-realm.id")
            out.append(open(p).read().strip() if os.path.exists(p) else None)
        return out

    def test_install_then_idempotent_rerun(self):
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.rstrip().endswith("HANGOUT OK"), out[-400:])
        cfg = self.cfg()
        rid = cfg["realm_id"]
        self.assertTrue(cfg["official"])
        self.assertEqual((cfg["name"], cfg["visibility"], cfg["signup"], cfg["realmlist"]), ("Dalaran Hangout", "public", "off", "keep"))
        self.assertEqual((cfg["relay_url"], cfg["listing_url"]), ("ws://172.18.0.1:8100/agent", "http://172.18.0.1:8100/api/listing/heartbeat"))
        self.assertEqual((cfg["auth_service"], cfg["world_service"], cfg["status_url"]),
                         ("wu-hangout-auth:3724", "ov-ac-worldserver:8085", "http://wu-portal:8091/wrath/status.json"))
        # the relay players' login server: the realm's own image and settings, no IP bans, no port, never printed
        auth = open(os.path.join(self.st, "auth_args")).read()
        for need in ("--name wu-hangout-auth", "--network ov-wotlk_backend", f"--env-file {self.dir}/auth.env",
                     "-w /azerothcore", "ov/ac-wotlk-authserver:custom"):
            self.assertIn(need, auth)
        self.assertNotIn("-p ", auth)
        aenv = open(os.path.join(self.dir, "auth.env")).read()
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "auth.env")).st_mode), 0o600)
        self.assertIn("AC_WRONG_PASS_MAX_COUNT=0", aenv)
        self.assertNotIn("AC_WRONG_PASS_MAX_COUNT=10", aenv)
        self.assertIn("AC_LOGIN_DATABASE_INFO=", aenv)
        self.assertNotIn("DBSECRET-sentinel", out, "the database login is never printed")
        self.assertIn("network connect ov-wotlk_edge wu-hangout-auth", open(os.path.join(self.st, "connect.log")).read())
        self.assertEqual(cfg["record"]["rules"][0], "Be kind: no harassment, hate speech or spam.")
        self.assertNotRegex(json.dumps(cfg["record"]), r"(?i)world of warcraft|\bwow\b|warcraft|lich king|blizzard")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "state", "realm.key")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o711)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "backups")).st_mode), 0o700)
        self.assertEqual(self.ids(), [rid, rid])
        self.assertTrue(os.path.exists(os.path.join(self.st, "fetched")), "the in-game list refreshed at once")
        args = open(os.path.join(self.st, "agent_args")).read()
        for need in ("--name wu-hangout-agent", "--restart unless-stopped", "--network wenilla-realm_default", "--memory 64m",
                     "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--user 10001:10001",
                     f"-v {self.dir}/state:/state", "wu-hangout-tools:1 python -m wuhost.agent --state /state"):
            self.assertIn(need, args)
        self.assertNotIn("-p ", args, "no published port")
        self.assertIn("network connect ov-wotlk_edge wu-hangout-agent", open(os.path.join(self.st, "connect.log")).read())
        log = open(os.path.join(self.st, "docker.log")).read()
        self.assertIn("--network none", log, "the config step runs with no network")
        self.assertNotRegex(log + out, r"(?i)account create|passw(or)?d\s*=")
        # again: the same realm, the previous image kept for a rollback
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.cfg()["realm_id"], rid)
        self.assertTrue(os.path.exists(os.path.join(self.st, "img_wu-hangout-tools_rollback")))
        self.assertEqual(self.ids(), [rid, rid])

    def test_failed_connect_rolls_back_to_nothing(self):
        self.flag("fail_connect")
        rc, out = self.run_up()
        self.assertEqual(rc, 1, out)
        self.assertIn("did not connect to the relay (relay refused: test)", out)
        self.assertFalse(os.path.exists(os.path.join(self.st, "agent")), "no agent left running")
        self.assertFalse(os.path.exists(os.path.join(self.st, "auth")), "no login server left running")
        self.assertEqual(self.ids(), [None, None])

    def test_failed_listing_on_rerun_keeps_the_previous_agent(self):
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        rid = self.cfg()["realm_id"]
        self.flag("fail_listing")
        rc, out = self.run_up()
        self.assertEqual(rc, 1, out)
        self.assertIn("does not show the hangout", out)
        self.assertTrue(os.path.exists(os.path.join(self.st, "agent")), "the previous agent is running again")
        self.assertEqual(open(os.path.join(self.st, "agent_image")).read().strip(), "build1", "on the previous image")
        self.assertEqual(self.ids(), [rid, rid])
        self.assertEqual(self.cfg()["realm_id"], rid)

    def test_login_server_that_never_answers_rolls_back(self):
        self.flag("fail_auth")
        rc, out = self.run_up()
        self.assertEqual(rc, 1, out)
        self.assertIn("login server (wu-hangout-auth, from ov-ac-authserver) did not start", out)
        self.assertFalse(os.path.exists(os.path.join(self.st, "auth")) or os.path.exists(os.path.join(self.st, "agent")))

    def test_missing_relay_or_realm_changes_nothing(self):
        self.flag("down_wu-relay")
        rc, out = self.run_up()
        self.assertEqual(rc, 1)
        self.assertIn("run the relay step first", out)
        self.flag("down_wu-relay", False)
        self.flag("down_ov-ac-worldserver")
        rc, out = self.run_up()
        self.assertEqual(rc, 1)
        self.assertIn("ov-ac-worldserver is not running", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "state", "host.json")))
        self.assertFalse(os.path.exists(os.path.join(self.st, "agent")))

    def test_remove(self):
        rc, out = self.run_up()
        self.assertEqual(rc, 0, out)
        key = open(os.path.join(self.dir, "state", "realm.key")).read()
        rc, out = self.run_up("--remove")
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.rstrip().endswith("HANGOUT REMOVED"))
        self.assertFalse(os.path.exists(os.path.join(self.st, "agent")) or os.path.exists(os.path.join(self.st, "auth")))
        self.assertEqual(self.ids(), [None, None])
        self.assertEqual(open(os.path.join(self.dir, "state", "realm.key")).read(), key, "the key stays")

    def test_bat_and_step_wiring(self):
        bat = open(BAT).read()
        ssh = [l for l in bat.splitlines() if l.lstrip().lower().startswith("ssh ")]
        self.assertEqual(len(ssh), 1, "exactly one SSH login")
        line = ssh[0]
        self.assertIn('-i "%USERPROFILE%\\.ssh\\openwow"', line)
        self.assertIn("root@play.openvanilla.app", line)
        self.assertIn("sed 's/\\r$//'", line)
        self.assertIn("'^HANGOUT OK'", line)
        self.assertTrue(line.rstrip().endswith('< "%TGZ%"'))
        self.assertNotIn("scp", bat.lower())
        for need in ("kit/tools/wunet", "kit/tools/wuhost", "kit/tools/Dockerfile", "hangout", "--exclude=state"):
            self.assertIn(need, bat)
        self.assertIn('Deploy Dalaran hangout.bat" remove', open(OFF_BAT).read())
        ctl = open(os.path.join(ROOT, "tools", "control", "control.py")).read()
        self.assertIn('"hangout": ("hosting/hangout/Deploy Dalaran hangout.bat"', ctl)
        self.assertIn('"hangout-off": ("hosting/hangout/Take Dalaran hangout off Leyline.bat"', ctl)
        upd = open(os.path.join(ROOT, "UPDATE.bat")).read()
        self.assertIn('if /i "%STEP%"=="hangout" set "BAT=hosting\\hangout\\Deploy Dalaran hangout.bat"', upd)
        self.assertIn('if /i "%STEP%"=="hangout-off" set "BAT=hosting\\hangout\\Take Dalaran hangout off Leyline.bat"', upd)

    def test_script_syntax(self):
        subprocess.run(["bash", "-n", SCRIPT], check=True)


if __name__ == "__main__":
    unittest.main()
