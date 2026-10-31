"""Vanilla Remastered: the ov112-on step (tools/ov112-off/start-112-realm.sh) and the vr-beacon step
(hosting/vanilla-remastered/vr-beacon-up.sh) against stub docker/curl (no Docker daemon, no network, nothing deployed),
the 1.12 probes against a fake login and world server, and the step wiring.

    python3 -I -m unittest discover -s hosting/vanilla-remastered/tests
"""
import ast
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VR = os.path.dirname(HERE)
HOSTING = os.path.dirname(VR)
ROOT = os.path.dirname(HOSTING)
REALM_ON = os.path.join(ROOT, "tools", "ov112-off", "start-112-realm.sh")
BEACON = os.path.join(VR, "vr-beacon-up.sh")
PROBE = os.path.join(VR, "probe112.py")
BRAND = ("world of warcraft", "warcraft", "lich king", "blizzard")

# ---------------------------------------------------------------------------------------------- stub docker
DOCKER = r"""#!/usr/bin/env bash
S="$STUB_STATE"; echo "docker $*" >> "$S/docker.log"
has() { [ -f "$S/$1" ]; }
case "$1" in
  ps) all=0; [ "$2" = -a ] && all=1
      for f in "$S"/exists_*; do [ -e "$f" ] || continue; n=${f##*/exists_}
        if [ $all = 1 ] || has "running_$n"; then echo "$n"; fi; done; exit 0 ;;
  image) has "noimage" && exit 1; exit 0 ;;
  inspect)
    t="$3"; n="$4"
    case "$t" in
      *PortBindings*) echo "8085/tcp 3724/tcp " ;;
      *'$k'*) echo "wenilla-realm_default " ;;
      *Config.Image*) echo "ghcr.io/orionopenwow/openvanilla-mangos:live" ;;
      '{{.Image}}') echo "sha256:1112old$n" ;;
      *Config.User*) echo "" ;;
      *WorkingDir*) echo "/opt/mangos" ;;
      *Config.Tty*) echo false ;;
      *OpenStdin*) echo true ;;
      *HostConfig.Memory*) echo 0 ;;
      *Config.Env*) printf 'PATH=/usr/bin\nDB_PASSWORD=DBSECRET-sentinel\nREALMD_HOST=realmd\n' ;;
      *Mounts*) printf 'volume|wenilla-realm_maps||/opt/mangos/data|false\nbind||/opt/wenilla-realm/etc|/opt/mangos/etc|true\n' ;;
      *'json .Config.Entrypoint'*) echo null ;;
      *'json .Config.Cmd'*) echo '["./bin/mangosd", "-c", "etc/mangosd.conf"]' ;;
      *Aliases*) case "$n" in wenilla-realm-mariadb-1) printf 'mariadb\nwenilla-realm-mariadb-1\n' ;;
                   wu-portal) printf 'mangosd\nwu-portal\n' ;; wenilla-realm-realm-1) has alias_clash && echo mangosd ;; esac ;;
      *compose.service*) echo mariadb ;;
      *RestartCount*) if has world_restarts; then echo "3 true"; else echo "0 true"; fi ;;
    esac; exit 0 ;;
  exec) echo "$*" >> "$S/exec.log"
        case "$*" in *mariadb-dump*|*mysqldump*) head -c 5000 /dev/urandom; exit 0 ;; esac
        case "$*" in *WrongPass*) [ -f "$S/wrongpass" ] && cat "$S/wrongpass"; exit 0 ;; esac
        if [ ! -t 0 ]; then q=$(cat); echo "$q" >> "$S/sql.log"
          case "$q" in SELECT*) cat "$S/realmlist" ;; esac; fi; exit 0 ;;
  network)
    case "$2" in
      inspect) n="$3"; [ "$n" = vr-112 ] && ! has net_vr-112 && exit 1
               if [ "$4" = -f ]; then
                 if [ "$n" = vr-112 ]; then cat "$S/net_vr-112"; else printf 'wu-portal\nwenilla-realm-realm-1\nwenilla-realm-mariadb-1\n'; fi
               fi; exit 0 ;;
      create) : > "$S/net_vr-112"; echo "$*" >> "$S/net.log"; exit 0 ;;
      connect) for a; do last2=$last; last=$a; done; [ "$last2" = vr-112 ] && echo "$last" >> "$S/net_vr-112"; echo "$*" >> "$S/net.log"; exit 0 ;;
      disconnect) echo "$*" >> "$S/net.log"; sed -i "/^$4$/d" "$S/net_vr-112" 2>/dev/null; exit 0 ;;
      rm) rm -f "$S/net_vr-112"; echo "$*" >> "$S/net.log"; exit 0 ;;
    esac ;;
  run) shift
    if [ "$1" = --rm ]; then   # a probe: ... /p/probe112.py WHAT HOST PORT
      for a; do p3=$p2; p2=$p1; p1=$a; done
      case "$p3" in
        logon) has fail_logon && { echo "no answer: OSError"; exit 1; }; echo "logon answer 0x04 (ok)" ;;
        world) has fail_world && { echo "no answer: OSError"; exit 1; }; echo "world greeting 0x01ec (ok)" ;;
        *) echo "HTTP 200" ;;
      esac; exit 0
    fi
    name=""; prev=""; for a; do [ "$prev" = --name ] && name=$a; prev=$a; done
    echo "$*" > "$S/run_$name"; touch "$S/exists_$name" "$S/running_$name"; exit 0 ;;
  update) echo "$*" >> "$S/update.log"; exit 0 ;;
  start) touch "$S/running_$2"; exit 0 ;;
  stop) for a; do rm -f "$S/running_$a"; done; exit 0 ;;
  rm) for a; do rm -f "$S/running_$a" "$S/exists_$a"; done; exit 0 ;;
  logs) echo "stub log"; exit 0 ;;
esac
exit 0
"""


class RealmOn(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="vr-realm-on-")
        self.bin, self.st, self.bk = (os.path.join(self.t, d) for d in ("bin", "stub", "backups"))
        for d in (self.bin, self.st, self.bk):
            os.makedirs(d)
        p = os.path.join(self.bin, "docker")
        with open(p, "w") as f:
            f.write(DOCKER)
        os.chmod(p, 0o755)
        self.src = os.path.join(self.t, "src")
        shutil.copytree(os.path.join(HOSTING, "kit", "tools", "wunet"), os.path.join(self.src, "hosting/kit/tools/wunet"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(self.src, "hosting/vanilla-remastered"))
        shutil.copy(PROBE, os.path.join(self.src, "hosting/vanilla-remastered/probe112.py"))
        for c in ("wenilla-realm-realmd-1", "wenilla-realm-mangosd-1", "wenilla-realm-mariadb-1", "wenilla-realm-realm-1",
                  "wu-portal", "ov-ac-authserver", "ov-ac-worldserver"):
            self.touch("exists_" + c)
            if not c.startswith("wenilla-realm-m") and c != "wenilla-realm-realmd-1":
                self.touch("running_" + c)
        self.touch("running_wenilla-realm-mariadb-1")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_STATE=self.st, VR_TEST="1",
                        VR_BACKUP_ROOT=self.bk, VR_ENV_DIR=os.path.join(self.t, "env"), VR_MIN_FREE_MB="0",
                        VR_MIN_DISK_MB="0", VR_WORLD_WAIT="0", VR_PAUSE="0", VR_SETTLE="0",
                        VR_CADDYFILE=os.path.join(self.t, "none"), VR_SITE_URLS="http://127.0.0.1:9/")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def touch(self, n):
        open(os.path.join(self.st, n), "w").close()

    def has(self, n):
        return os.path.exists(os.path.join(self.st, n))

    def read(self, n):
        p = os.path.join(self.st, n)
        return open(p).read() if os.path.exists(p) else ""

    def run_it(self, *a):
        return subprocess.run(["bash", REALM_ON, self.src] + list(a), env=self.env, capture_output=True, text=True,
                              timeout=120)

    def test_dry_run_changes_nothing(self):
        r = self.run_it()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith("OV112 REALM DRY"))
        self.assertIn("published ports: 8085/tcp 3724/tcp", r.stdout)
        log = self.read("docker.log")
        for verb in ("docker run", "docker network create", "docker update", "docker start", "docker stop", "docker rm"):
            self.assertNotIn(verb, log)
        self.assertNotIn("DBSECRET", r.stdout + r.stderr)

    def test_go(self):
        r = self.run_it("--go")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith("OV112 REALM ON"))
        self.assertNotIn("DBSECRET", r.stdout + r.stderr)
        for c in ("vr-realmd", "vr-mangosd"):
            args = self.read("run_" + c)
            self.assertIn("--network vr-112", args)
            self.assertNotIn(" -p ", args); self.assertNotIn("--publish", args)
            self.assertNotIn("wenilla-realm_default", args)
            self.assertIn("--restart unless-stopped", args)
            self.assertIn("type=volume,src=wenilla-realm_maps,dst=/opt/mangos/data,readonly", args)
            self.assertIn("type=bind,src=/opt/wenilla-realm/etc,dst=/opt/mangos/etc", args)
            self.assertIn("sha256:1112old", args)
            self.assertTrue(args.rstrip().endswith("./bin/mangosd -c etc/mangosd.conf"), args)
            env = os.path.join(self.t, "env", c + ".env")
            self.assertEqual(oct(os.stat(env).st_mode & 0o777), "0o600")
        self.assertIn("--internal", self.read("net.log"))
        self.assertIn("--alias mariadb", self.read("net.log"))
        # the old containers are never started, changed or removed
        log = self.read("docker.log")
        for old in ("wenilla-realm-realmd-1", "wenilla-realm-mangosd-1"):
            for verb in ("start", "update", "stop", "rm"):
                self.assertNotIn(f"docker {verb} {old}", log)
        bks = os.listdir(self.bk)
        self.assertEqual(len(bks), 1)
        self.assertTrue(os.path.getsize(os.path.join(self.bk, bks[0], "mariadb-all.sql.gz")) > 0)

    def test_go_twice_is_safe(self):
        self.assertEqual(self.run_it("--go").returncode, 0)
        r = self.run_it("--go")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("vr-mangosd: already running", r.stdout)

    def test_world_never_greets_rolls_back(self):
        self.touch("fail_world")
        r = self.run_it("--go")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rolled back", r.stderr)
        self.assertFalse(self.has("exists_vr-mangosd") or self.has("exists_vr-realmd"))
        self.assertFalse(self.has("net_vr-112"), "the network made by this run is gone again")

    def test_name_clash_rolls_back(self):
        self.touch("alias_clash")
        r = self.run_it("--go")
        self.assertEqual(r.returncode, 1)
        self.assertIn("accounts would split", r.stderr)
        self.assertFalse(self.has("exists_vr-mangosd"))

    def test_restarting_world_rolls_back(self):
        self.touch("world_restarts")
        r = self.run_it("--go")
        self.assertEqual(r.returncode, 1)
        self.assertIn("restarted or stopped", r.stderr)

    def test_old_container_running_refuses(self):
        self.touch("running_wenilla-realm-mangosd-1")
        r = self.run_it("--go")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("docker run -d", self.read("docker.log"))

    def test_off(self):
        self.assertEqual(self.run_it("--go").returncode, 0)
        r = self.run_it("--off")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith("OV112 REALM OFF"))
        self.assertTrue(self.has("exists_vr-mangosd"), "kept, not removed")
        self.assertFalse(self.has("running_vr-mangosd"))

    def test_off_refuses_while_listed(self):
        self.touch("exists_wu-vr-agent"); self.touch("running_wu-vr-agent")
        r = self.run_it("--off")
        self.assertEqual(r.returncode, 1)
        self.assertIn("vr-beacon-off", r.stderr)


# ---------------------------------------------------------------------------------------------- the probes
class FakeServers:
    """A login server that answers a logon challenge with 'unknown account' and a world server that greets."""
    def __init__(self, logon_code=0x04):
        self.logon_code = logon_code
        self.ports = {}
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        fut = asyncio.run_coroutine_threadsafe(self.start(), self.loop)
        fut.result(5)

    async def start(self):
        async def logon(r, w):
            head = await r.readexactly(4)
            body = await r.readexactly(int.from_bytes(head[2:4], "little"))
            self.build = int.from_bytes(body[7:9], "little")
            w.write(bytes([0x00, 0x00, self.logon_code])); await w.drain(); w.close()

        async def world(r, w):
            w.write((6).to_bytes(2, "big") + (0x1EC).to_bytes(2, "little") + b"\x01\x02\x03\x04"); await w.drain(); w.close()
        for k, h in (("logon", logon), ("world", world)):
            s = await asyncio.start_server(h, "127.0.0.1", 0)
            self.ports[k] = s.sockets[0].getsockname()[1]


class Probes(unittest.TestCase):
    def probe(self, *a):
        env = dict(os.environ, PYTHONPATH="")
        d = tempfile.mkdtemp(prefix="vr-probe-")
        shutil.copytree(os.path.join(HOSTING, "kit", "tools", "wunet"), os.path.join(d, "wunet"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(PROBE, d)
        try:
            return subprocess.run([sys.executable, "-I", os.path.join(d, "probe112.py")] + [str(x) for x in a],
                                  capture_output=True, text=True, env=env, timeout=30)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_logon_and_world(self):
        f = FakeServers()
        r = self.probe("logon", "127.0.0.1", f.ports["logon"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("0x04", r.stdout)
        self.assertEqual(f.build, 5875)
        r = self.probe("world", "127.0.0.1", f.ports["world"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("0x01ec", r.stdout)

    def test_wrong_version_is_not_ok(self):
        f = FakeServers(logon_code=0x09)
        r = self.probe("logon", "127.0.0.1", f.ports["logon"])
        self.assertEqual(r.returncode, 1)

    def test_nothing_listening(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        r = self.probe("world", "127.0.0.1", port)
        self.assertEqual(r.returncode, 1); self.assertIn("no answer", r.stdout)



# ---------------------------------------------------------------------------------------------- the vr-beacon step
BDOCKER = r"""#!/usr/bin/env bash
S="$STUB_STATE"; echo "docker $*" >> "$S/docker.log"
case "$1" in
  ps) for c in wu-relay vr-realmd vr-mangosd wenilla-realm-mariadb-1; do [ -f "$S/down_$c" ] || echo $c; done
      [ -f "$S/agent" ] && echo wu-vr-agent; exit 0 ;;
  exec) case "$*" in *WrongPass*) [ -f "$S/wrongpass" ] && cat "$S/wrongpass"; exit 0 ;; esac
        q=$(cat); echo "$q" >> "$S/sql.log"
        case "$q" in SELECT*) cat "$S/realmlist" ;;
          UPDATE*) python3 -I - "$S/realmlist" "$q" <<'PY'
import re, sys
p, q = sys.argv[1], sys.argv[2]
m = re.search(r"address = '([^']+)', port = (\d+) WHERE id = (\d+)", q)
rows = [l.rstrip("\n").split("\t") for l in open(p) if l.strip()]
for r in rows:
    if r[0] == m.group(3):
        r[2], r[3] = m.group(1), m.group(2)
open(p, "w").write("".join("\t".join(r) + "\n" for r in rows))
PY
          ;; esac; exit 0 ;;
  network) [ -f "$S/nonet_$3" ] && exit 1; exit 0 ;;
  image) [ -f "$S/img_${3//[:\/]/_}" ]; exit $? ;;
  tag) [ -f "$S/img_${2//[:\/]/_}" ] || exit 1; cp "$S/img_${2//[:\/]/_}" "$S/img_${3//[:\/]/_}"; exit 0 ;;
  build) echo built > "$S/img_wu-vr-tools_1"; exit 0 ;;
  rm) for a; do [ "$a" = wu-vr-agent ] && rm -f "$S/agent"; done; exit 0 ;;
  logs) echo "stub agent log"; exit 0 ;;
  run) shift
    if [ "$1" = "-d" ]; then
      echo "$*" > "$S/agent_args"; touch "$S/agent"
      if [ -f "$S/fail_connect" ]; then printf '{"connected": false, "last_error": "test"}' > "$VR_BEACON_DIR/state/relay-state.json"
      else printf '{"connected": true, "address": "127.0.0.1", "auth_port": 9100, "world_port": 9101}' > "$VR_BEACON_DIR/state/relay-state.json"; fi
      exit 0
    fi
    case " $* " in
      *" --network host "*) [ -f "$S/fail_logon" ] && { echo "no answer"; exit 1; }; echo "logon answer 0x04 (ok)"; exit 0 ;;
      *" wuhost.setup "*) args=(); seen=0
        for a in "$@"; do [ $seen = 1 ] && args+=("${a//\/kit\//$VR_BEACON_DIR/}"); [ "$a" = wuhost.setup ] && seen=1; done
        WU_KIT="$VR_BEACON_DIR" PYTHONPATH="$STUB_SRC/kit/tools" python3 -m wuhost.setup "${args[@]}"; exit $? ;;
      *" -c "*) code=""; prev=""; for a in "$@"; do [ "$prev" = -c ] && code=$a; prev=$a; done
        VR_TAGS=custom python3 -I -c "${code//\/kit\//$VR_BEACON_DIR/}"; exit $? ;;
    esac ;;
esac
exit 0
"""
BCURL = r"""#!/usr/bin/env bash
S="$STUB_STATE"; for a in "$@"; do u="$a"; done
rid=$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["realm_id"])' "$VR_BEACON_DIR/state/host.json" 2>/dev/null)
case "$u" in
  http://*/healthz) echo ok ;;
  http://*/api/realms/*) [ -f "$S/agent" ] || exit 22; echo '{"online": true}' ;;
  http://*/r/*/status.json) [ -f "$S/agent" ] || exit 22; echo '{"online": true, "build": "1.12.1"}' ;;
  http://*/api/listing/realms.json) if [ -f "$S/agent" ] && [ ! -f "$S/fail_listing" ]; then
      printf '{"realms": [{"community": {"realmId": "%s"}}]}' "$rid"; else echo '{"realms": []}'; fi ;;
  *) exit 6 ;;
esac
"""


class Beacon(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="vr-beacon-")
        self.bin, self.st = os.path.join(self.t, "bin"), os.path.join(self.t, "stub")
        os.makedirs(self.bin); os.makedirs(self.st)
        for name, body in (("docker", BDOCKER), ("curl", BCURL)):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.src = os.path.join(self.t, "src")
        for d in ("kit/tools/wunet", "kit/tools/wuhost"):
            shutil.copytree(os.path.join(HOSTING, d), os.path.join(self.src, d), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(HOSTING, "kit", "tools", "Dockerfile"), os.path.join(self.src, "kit", "tools", "Dockerfile"))
        shutil.copytree(VR, os.path.join(self.src, "vanilla-remastered"), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        self.relay = os.path.join(self.t, "relay"); os.makedirs(self.relay)
        with open(os.path.join(self.relay, "relay.env"), "w") as f:
            f.write("RELAY_NAME=relay.openvanilla.app\nRELAY_HTTP_BIND=172.18.0.1:8100\n")
        self.dir, self.portal, self.wrath = (os.path.join(self.t, d) for d in ("vr-beacon", "portal", "wrath"))
        os.makedirs(self.portal); os.makedirs(self.wrath)
        with open(os.path.join(self.st, "realmlist"), "w") as f:
            f.write("1\tOpen Vanilla\tplay.openvanilla.app\t8085\n")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_STATE=self.st, STUB_SRC=self.src,
                        WU_TEST="1", VR_BEACON_DIR=self.dir, WU_RELAY_DIR=self.relay, WU_PORTAL_DIR=self.portal,
                        WU_WRATH_DIR=self.wrath, WU_HEALTH_TRIES="2", WU_HEALTH_PAUSE="0")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def up(self, *a):
        return subprocess.run(["bash", BEACON, self.src] + list(a), env=self.env, capture_output=True, text=True, timeout=120)

    def row(self):
        with open(os.path.join(self.st, "realmlist")) as f:
            return f.read().strip()

    def test_up(self):
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith("VR BEACON OK"))
        with open(os.path.join(self.dir, "state", "host.json")) as f:
            cfg = json.load(f)
        self.assertTrue(cfg["official"]); self.assertEqual(cfg["signup"], "off"); self.assertEqual(cfg["name"], "Vanilla Remastered")
        self.assertEqual((cfg["auth_service"], cfg["world_service"]), ("vr-realmd:3724", "vr-mangosd:8085"))
        self.assertEqual(cfg["profile"], "cmangos-1.12.1")
        rec = cfg["record"]
        self.assertEqual((rec["core"], rec["build"], rec["ruleset"], rec["tags"]), ("cmangos", 5875, "custom", ["custom"]))
        self.assertEqual(self.row(), "1\tOpen Vanilla\t127.0.0.1\t9101")
        with open(os.path.join(self.portal, "vr-realm.id")) as f:
            self.assertEqual(f.read().strip(), cfg["realm_id"])
        args = open(os.path.join(self.st, "agent_args")).read()
        for need in ("--name wu-vr-agent", "--network wenilla-realm_default", "--read-only", "--cap-drop ALL"):
            self.assertIn(need, args)
        self.assertIn("network connect vr-112 wu-vr-agent", open(os.path.join(self.st, "docker.log")).read())
        r2 = self.up()   # again: same realm id
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        with open(os.path.join(self.dir, "state", "host.json")) as f:
            self.assertEqual(json.load(f)["realm_id"], cfg["realm_id"])
        r3 = self.up("--remove")
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
        self.assertEqual(self.row(), "1\tOpen Vanilla\tplay.openvanilla.app\t8085", "the original address is back")
        self.assertFalse(os.path.exists(os.path.join(self.portal, "vr-realm.id")))

    def test_needs_the_realm(self):
        open(os.path.join(self.st, "down_vr-mangosd"), "w").close()
        r = self.up()
        self.assertEqual(r.returncode, 1); self.assertIn("ov112-on", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.st, "agent_args")))

    def test_wrong_password_lock_refuses(self):
        with open(os.path.join(self.st, "wrongpass"), "w") as f:
            f.write("WrongPass.MaxCount = 5\n")
        r = self.up()
        self.assertEqual(r.returncode, 1); self.assertIn("WrongPass.MaxCount", r.stderr)
        self.assertNotIn("UPDATE", open(os.path.join(self.st, "sql.log")).read())

    def test_listing_fails_rolls_back_row(self):
        open(os.path.join(self.st, "fail_listing"), "w").close()
        r = self.up()
        self.assertEqual(r.returncode, 1); self.assertIn("rolled back", r.stderr)
        self.assertEqual(self.row(), "1\tOpen Vanilla\tplay.openvanilla.app\t8085")
        self.assertFalse(os.path.exists(os.path.join(self.st, "agent")))

    def test_two_rows_need_an_id(self):
        with open(os.path.join(self.st, "realmlist"), "a") as f:
            f.write("2\tTest\t127.0.0.1\t8086\n")
        r = self.up()
        self.assertEqual(r.returncode, 1); self.assertIn("VR_REALM_ID", r.stderr)

# ---------------------------------------------------------------------------------------------- wiring and words
class Wiring(unittest.TestCase):
    def steps(self):
        tree = ast.parse(open(os.path.join(ROOT, "tools", "control", "control.py"), encoding="utf-8").read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "STEPS" for t in node.targets):
                return ast.literal_eval(node.value)

    def test_steps(self):
        st = self.steps()
        want = {"ov112-realm-check": "Turn on the 1.12 realm - check.bat", "ov112-on": "Turn on the 1.12 realm.bat",
                "ov112-realm-off": "Turn off the 1.12 realm.bat", "vr-beacon": "Put Vanilla Remastered on Leyline.bat",
                "vr-beacon-off": "Take Vanilla Remastered off Leyline.bat"}
        for step, bat in want.items():
            self.assertIn(step, st)
            self.assertTrue(st[step][0].endswith(bat), st[step])
            self.assertTrue(os.path.isfile(os.path.join(ROOT, st[step][0])), st[step][0])

    def test_bats(self):
        for rel, mode, mark in (("tools/ov112-off/Turn on the 1.12 realm - check.bat", "--check", "OV112 REALM DRY"),
                                ("tools/ov112-off/Turn on the 1.12 realm.bat", "--go", "OV112 REALM ON"),
                                ("tools/ov112-off/Turn off the 1.12 realm.bat", "--off", "OV112 REALM OFF")):
            b = open(os.path.join(ROOT, rel), encoding="utf-8", newline="").read()
            self.assertIn(f"$T {mode} 2>&1", b); self.assertIn(f"'^{mark}'", b)
            for f in ("tools/ov112-off/start-112-realm.sh", "hosting/vanilla-remastered/probe112.py", "hosting/kit/tools/wunet"):
                self.assertIn(f, b)
            self.assertIn("\r\n", b)
        b = open(os.path.join(VR, "Put Vanilla Remastered on Leyline.bat"), encoding="utf-8").read()
        self.assertIn("vanilla-remastered", b); self.assertIn("'^VR BEACON OK'", b); self.assertIn("--exclude=tests", b)
        off = open(os.path.join(VR, "Take Vanilla Remastered off Leyline.bat"), encoding="utf-8").read()
        self.assertIn('Put Vanilla Remastered on Leyline.bat" remove', off)

    def test_beacon_shape(self):
        s = open(BEACON, encoding="utf-8").read()
        for need in ('NAME="${VR_NAME:-Vanilla Remastered}"', "setup official", "--auth-service \"$AUTH\"",
                     'AUTH="$LOGON_C:3724"', 'WORLD="$WORLD_C:8085"', 'core="cmangos", build=5875',
                     "--cap-drop ALL", "--read-only", "vr-realm.id"):
            self.assertIn(need, s)
        self.assertNotIn("--status-url", s.split("setup official")[1].split("2>&1")[0])

    def test_no_brand_words_for_players(self):
        texts = [open(os.path.join(VR, "rules.txt"), encoding="utf-8").read()]
        s = open(BEACON, encoding="utf-8").read()
        for var in ("TAGLINE", "SUMMARY", "NAME"):
            line = [l for l in s.splitlines() if l.startswith(var + '="')][0]
            texts.append(line)
        for t in texts:
            low = t.lower()
            for w in BRAND:
                self.assertNotIn(w, low)
            self.assertNotRegex(low, r"(^|[^a-z])wow([^a-z]|$)")

    def test_syntax(self):
        for p in (REALM_ON, BEACON):
            r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
