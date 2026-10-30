"""The Leyline Sample Hangout: realm/profiles/sampler.env (the overlay), realm/sampler.sh (check / on / off on a
fake server: docker, soap-cmd.sh and sleep are stubs on PATH), realm/lean.sh's guard, and slices/sampler.json
against slices/mini.json.

    python3 -I tests/test_sampler.py        (from the stream folder)
"""
import importlib.util, json, os, re, shutil, subprocess, sys, tempfile
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
REALM = os.path.join(REPO, "realm")
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {str(extra)[-600:]}" if extra and not cond else ""))
    fails += 0 if cond else 1


def kv(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


OVERLAY = os.path.join(REALM, "profiles", "sampler.env")
ov = kv(OVERLAY)
main = kv(os.path.join(REALM, "profiles", "main.env"))
mods = kv(os.path.join(REALM, "modules.env"))

# ---- 1. the overlay ------------------------------------------------------------------------------------
check("overlay: OV_SAMPLER=1 and the Dalaran build area", ov.get("OV_SAMPLER") == "1" and ov.get("OV_BUILD_DALARAN") == "1")
check("overlay: every line is an AC_/OV_ key with a plain value (sampler.sh's own rule)",
      all(re.fullmatch(r"(AC|OV)_[A-Z0-9_]+", k) and re.fullmatch(r"[A-Za-z0-9.,_-]*", v) for k, v in ov.items()), ov)
bots = int(ov["AC_PLAYERBOTS_MAX_RANDOM_BOTS"])
check("overlay: 10-15 random bots, min = max", 10 <= bots <= 15 and ov["AC_PLAYERBOTS_MIN_RANDOM_BOTS"] == str(bots))
check("overlay: fewer random bots than modules.env today", bots < int(mods["AC_PLAYERBOTS_MAX_RANDOM_BOTS"]))
check("overlay: the bot counts live in modules.env (it is read after the profile and wins)",
      "AC_PLAYERBOTS_MIN_RANDOM_BOTS" in mods and "AC_PLAYERBOTS_MAX_RANDOM_BOTS" in mods)
# The owner's correction (20:53): dungeons, raids and Companions stay as on main.
check("overlay: the Dungeon Finder is not touched", "AC_DUNGEON_FINDER_OPTIONS_MASK" not in ov and mods.get("AC_DUNGEON_FINDER_OPTIONS_MASK") == "7")
check("overlay: Companions are not touched (parties and 10-player raids as on main)",
      not any(k.startswith("OV_COMPANIONS") for k in ov) and "AC_PLAYERBOTS_MAX_ADDED_BOTS" not in ov
      and main.get("OV_COMPANIONS") == "1" and main.get("OV_COMPANIONS_GROUP_MAX") == "10")
check("overlay: random bots still join the Dungeon Finder", "AC_PLAYERBOTS_RANDOM_BOT_JOIN_LFG" not in ov and mods.get("AC_PLAYERBOTS_RANDOM_BOT_JOIN_LFG") == "1")
check("overlay: no raid, instance or arena switch", not any(re.search(r"RAID|INSTANCE|ARENA|BATTLEGROUND|LFG|DUNGEON", k) for k in ov), ov)
check("overlay: idle grids unload after a minute", ov.get("AC_GRID_UNLOAD") == "1" and int(ov["AC_GRID_CLEAN_UP_DELAY"]) <= 60000)
check("overlay: open-world visibility below the stock 90, above 50", 50 <= int(ov["AC_VISIBILITY_DISTANCE_CONTINENTS"]) < 90)
# Env names follow AzerothCore's IniKeyToEnvVarKey (the same converter as the bot specs).
conv = load("ms", os.path.join(REPO, "tools", "playerbots-specs", "make_specs_env.py")).ini_key_to_env
INI = {"Playerbots.MinRandomBots", "Playerbots.MaxRandomBots", "Playerbots.RandomBotMinLevel", "Playerbots.RandomBotMaxLevel",
       "Playerbots.ProbTeleToBankers", "Playerbots.RandomBotMaps", "GridUnload", "GridCleanUpDelay",
       "Visibility.Distance.Continents"}
names = {conv(k) for k in INI}
check("overlay: every AC_ key is the env name of a real config key", {k for k in ov if k.startswith("AC_")} <= names,
      {k for k in ov if k.startswith("AC_")} - names)
check("overlay: bots level 80 (Dalaran's bankers are for 71+), teleports to bankers always, Northrend only",
      ov["AC_PLAYERBOTS_RANDOM_BOT_MIN_LEVEL"] == "80" and ov["AC_PLAYERBOTS_RANDOM_BOT_MAX_LEVEL"] == "80"
      and ov["AC_PLAYERBOTS_PROB_TELE_TO_BANKERS"] == "1" and ov["AC_PLAYERBOTS_RANDOM_BOT_MAPS"] == "571")
# serverpass.sh (the realm / scripts steps) and lean.sh rewrite keys in the profile: none may fight the overlay.
sp = open(os.path.join(REALM, "serverpass.sh"), encoding="utf-8").read()
sp_keys = dict(re.findall(r"\b((?:AC|OV)_[A-Z0-9_]+)=([0-9]+)\b", sp.split("== 3. profile")[1].split("3b.")[0]))
clash = {k for k in ov if k in sp_keys and sp_keys[k] != ov[k]}
check("overlay: no key serverpass.sh sets to another value", not clash, clash)
lean = open(os.path.join(REALM, "lean.sh"), encoding="utf-8").read()
lean_keys = dict(re.findall(r"setkv \"\$\w+\" (\w+) (\w+)", lean))
same = {k for k in ov if k in lean_keys and lean_keys[k] == ov[k]}
check("overlay: lean.sh's grid values are the overlay's own", same >= {"AC_GRID_UNLOAD", "AC_GRID_CLEAN_UP_DELAY"}, lean_keys)
check("lean.sh: leaves the Sample Hangout's bot count alone", "Leyline Sample Hangout" in lean and lean.index("Leyline Sample Hangout") < lean.index("setkv \"$MF\""))

# ---- 2. sampler.sh on a fake server --------------------------------------------------------------------
STUB_DOCKER = r'''#!/usr/bin/env bash
# fake docker: the world server's env is the profile, then modules.env (later wins), when "compose up" runs
S="$FAKE_STATE"
echo "docker $*" >> "$S/calls"
case "$1" in
  exec)
    if [ "$2" = ov-ac-worldserver ] && [ "$3" = printenv ]; then grep -E "^$4=" "$S/live.env" | tail -1 | cut -d= -f2-; exit 0; fi
    if [ "$2" = -i ] && [ "$3" = ov-ac-database ]; then
      sql=$(cat); echo "$sql" >> "$S/sql"
      case "$sql" in *"SELECT name FROM acore_auth.realmlist"*) cat "$S/realm-name" ;; esac
      case "$sql" in *"UPDATE acore_auth.realmlist SET name = '"*) echo "$sql" | sed "s/.*SET name = '\([^']*\)'.*/\1/" > "$S/realm-name" ;; esac
      exit 0
    fi
    exit 0 ;;
  compose)
    : > "$S/live.env"
    for f in profiles/main.env modules.env; do grep -E '^[A-Z]' "$f" >> "$S/live.env"; done
    awk -F= '{v[$1]=$0} END{for (k in v) print v[k]}' "$S/live.env" > "$S/live.tmp" && mv "$S/live.tmp" "$S/live.env"
    echo $(( $(cat "$S/started") + 1 )) > "$S/started"; exit 0 ;;
  inspect) cat "$S/started"; exit 0 ;;
  logs) echo "WORLD: World initialized ready..."; exit 0 ;;
  restart) echo $(( $(cat "$S/started") + 1 )) > "$S/started"; exit 0 ;;
  stats) echo "  ov-ac-worldserver 1.2GiB / 7.6GiB cpu 20%"; exit 0 ;;
esac
exit 0
'''


def server():
    d = tempfile.mkdtemp()
    w, st, bin_ = os.path.join(d, "wrath"), os.path.join(d, "state"), os.path.join(d, "bin")
    for p in (w, st, bin_, os.path.join(w, "profiles")):
        os.makedirs(p, exist_ok=True)
    shutil.copy(os.path.join(REALM, "profiles", "main.env"), os.path.join(w, "profiles", "main.env"))
    shutil.copy(os.path.join(REALM, "modules.env"), os.path.join(w, "modules.env"))
    open(os.path.join(w, ".env"), "w").write("OV_PROFILE=main\n")
    open(os.path.join(w, "portal.env"), "w").write("REALM_NAME=WrathUnleashed\nSTREAM_SLICES=mini\n")
    open(os.path.join(w, "soap-cmd.sh"), "w").write('echo "$*" >> "$FAKE_STATE/soap"\n')
    open(os.path.join(st, "realm-name"), "w").write("WrathUnleashed\n")
    open(os.path.join(st, "started"), "w").write("1\n")
    open(os.path.join(st, "live.env"), "w").write("")
    for name, body in (("docker", STUB_DOCKER), ("sleep", "#!/bin/sh\nexit 0\n")):
        p = os.path.join(bin_, name); open(p, "w").write(body); os.chmod(p, 0o755)
    return d, w, st, bin_


def run(d, w, st, bin_, *args):
    env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"], WU_DIR=w, FAKE_STATE=st, SAMPLER_WARN_MIN="0",
               HOME=d)
    script = os.path.join(d, "sampler.sh")
    src = open(os.path.join(REALM, "sampler.sh"), encoding="utf-8").read().replace("/root/sampler-backups", os.path.join(d, "bk"))
    open(script, "w").write(src)
    return subprocess.run(["bash", script, *args], capture_output=True, text=True, env=env, cwd=w)


def read(p):
    return open(p, encoding="utf-8").read()


d, w, st, bin_ = server()
pf, mf = os.path.join(w, "profiles", "main.env"), os.path.join(w, "modules.env")
orig_pf, orig_mf = read(pf), read(mf)
r = run(d, w, st, bin_, "check", OVERLAY)
check("check: reports success", r.returncode == 0 and r.stdout.rstrip().endswith("SAMPLER CHECK OK"), r.stdout + r.stderr)
check("check: changes nothing", read(pf) == orig_pf and read(mf) == orig_mf and not os.path.exists(os.path.join(st, "sql")) or
      "UPDATE" not in read(os.path.join(st, "sql")))
check("check: prints every overlay key with old and new value",
      all(k in r.stdout for k in ov) and "AC_PLAYERBOTS_MAX_RANDOM_BOTS" in r.stdout and "30 -> 12" in r.stdout, r.stdout)
check("check: says the realm name it would show", "'WrathUnleashed' -> 'Leyline Sample Hangout'" in r.stdout, r.stdout)
check("check: says the restart it would announce", "-minute restart and recreate the world server" in r.stdout)

r = run(d, w, st, bin_, "on", OVERLAY)
check("on: reports success", r.returncode == 0 and r.stdout.rstrip().endswith("SAMPLER OK"), r.stdout + r.stderr)
live = kv(os.path.join(st, "live.env"))
check("on: the world server runs with OV_SAMPLER=1 and 12 bots",
      live.get("OV_SAMPLER") == "1" and live.get("AC_PLAYERBOTS_MAX_RANDOM_BOTS") == "12" and live.get("AC_PLAYERBOTS_MIN_RANDOM_BOTS") == "12", live)
check("on: main.env keeps everything else (boost, Companions, the bot specs)",
      live.get("OV_MAIN") == "1" and live.get("OV_COMPANIONS") == "1" and live.get("AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__0") == "arms pve")
check("on: the bot counts went into modules.env, the old lines kept as #sampler-was:",
      "#sampler-was: AC_PLAYERBOTS_MIN_RANDOM_BOTS=30" in read(mf) and "AC_PLAYERBOTS_MAX_RANDOM_BOTS=12" in read(mf)
      and "AC_PLAYERBOTS_MAX_RANDOM_BOTS" not in read(pf))
check("on: one block in main.env", read(pf).count("# >>> Leyline Sample Hangout") == 1 and "OV_SAMPLER=1" in read(pf))
check("on: the realm list name is the Sample Hangout", read(os.path.join(st, "realm-name")).strip() == "Leyline Sample Hangout")
check("on: the old name is kept for off", read(os.path.join(w, "sampler-state", "realm-name.txt")).strip() == "WrathUnleashed")
check("on: portal.env WU_SAMPLER=1", "WU_SAMPLER=1" in read(os.path.join(w, "portal.env")))
check("on: everyone saved before the restart", "saveall" in read(os.path.join(st, "soap")))
check("on: backups kept", any(os.path.isfile(os.path.join(dp, "main.env")) for dp, _, _ in os.walk(os.path.join(d, "bk"))))
sqls = read(os.path.join(st, "sql"))
check("on: no character row is changed or deleted", not re.search(r"(UPDATE|DELETE|INSERT|REPLACE|DROP|ALTER)[^;]*characters", sqls, re.I), sqls)
r = run(d, w, st, bin_, "on", OVERLAY)
check("on twice: still one block, old lines once", r.returncode == 0 and read(pf).count("# >>> Leyline Sample Hangout") == 1
      and read(mf).count("#sampler-was: AC_PLAYERBOTS_MIN_RANDOM_BOTS=30") == 1, r.stderr)
check("on twice: the remembered old name stays the real one", read(os.path.join(w, "sampler-state", "realm-name.txt")).strip() == "WrathUnleashed")
r = run(d, w, st, bin_, "check", OVERLAY)
check("check while on: notes the block is there", "already has the Sample Hangout block" in r.stdout and r.returncode == 0)

r = run(d, w, st, bin_, "off")
check("off: reports success", r.returncode == 0 and r.stdout.rstrip().endswith("SAMPLER OK"), r.stdout + r.stderr)
check("off: main.env and modules.env are byte for byte as before", read(pf) == orig_pf and read(mf) == orig_mf)
live = kv(os.path.join(st, "live.env"))
check("off: the world server is back on 30 bots, no OV_SAMPLER", "OV_SAMPLER" not in live and live.get("AC_PLAYERBOTS_MAX_RANDOM_BOTS") == "30", live)
check("off: the realm name is back", read(os.path.join(st, "realm-name")).strip() == "WrathUnleashed")
check("off: portal.env WU_SAMPLER=0", "WU_SAMPLER=0" in read(os.path.join(w, "portal.env")))

bad = os.path.join(d, "bad.env")
open(bad, "w").write("OV_SAMPLER=1\nAC_X=1;rm -rf /\n")
r = run(d, w, st, bin_, "on", bad)
check("on: an overlay line with shell or sed characters is refused, nothing changed",
      r.returncode != 0 and "not accepted" in r.stderr and read(pf) == orig_pf)
open(os.path.join(w, ".env"), "w").write("OV_PROFILE=brawl\n")
r = run(d, w, st, bin_, "check", OVERLAY)
check("refuses a realm that is not on the main profile", r.returncode != 0 and "not 'main'" in r.stderr)
open(os.path.join(w, ".env"), "w").write("OV_PROFILE=main\n")

# lean.sh with the Sample Hangout on: nothing changes
run(d, w, st, bin_, "on", OVERLAY)
before = read(mf)
src = read(os.path.join(REALM, "lean.sh")).replace("cd /srv/wrath", f"cd {w}").replace("/root/lean-backups", os.path.join(d, "lb"))
open(os.path.join(d, "lean.sh"), "w").write(src)
env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"], FAKE_STATE=st, LEAN_WARN_MIN="0")
r = subprocess.run(["bash", os.path.join(d, "lean.sh")], capture_output=True, text=True, env=env, cwd=w)
check("lean.sh with the Sample Hangout on: LEAN OK, bot count kept", r.returncode == 0 and "LEAN OK" in r.stdout
      and read(mf) == before and "AC_PLAYERBOTS_MAX_RANDOM_BOTS=12" in before, r.stdout + r.stderr)
shutil.rmtree(d, ignore_errors=True)

# ---- 3. slices/sampler.json ----------------------------------------------------------------------------
mini = json.load(open(os.path.join(HERE, "slices", "mini.json"), encoding="utf-8"))
samp = json.load(open(os.path.join(HERE, "slices", "sampler.json"), encoding="utf-8"))
tl = load("tl", os.path.join(HERE, "lua", "tiers_lua.py"))
mk = {t["key"]: t for t in mini["tiers"]}
sk = {t["key"]: t for t in samp["tiers"]}
check("sampler.json: its own slice name", samp["slice"] == "sampler")
check("sampler.json: order lists every tier once", sorted(samp["order"]) == sorted(sk))
check("sampler.json: base then Dalaran first", samp["order"][:2] == ["base", "dalaran"])
check("sampler.json: the starting areas and Ebon Hold", {"northshire", "valley-of-trials", "ebon-hold"} <= set(sk))
check("sampler.json: no capitals, no Goldshire inn", not ({"stormwind", "orgrimmar", "goldshire-inn"} & set(sk))
      and not any(t["kind"] == "city" for t in samp["tiers"]))
inst = {k for k, t in mk.items() if t["kind"] in ("dungeon", "raid", "arena", "battleground")}
check("sampler.json: every dungeon, raid, arena and battleground of mini.json", inst <= set(sk), inst - set(sk))
check("sampler.json: the deferred music tier last", samp["order"][-1] == "music" and sk["music"].get("collectDeferred"))
same = [k for k in sk if sk[k] != mk.get(k)]
check("sampler.json: every tier is mini.json's own, unchanged (one source of truth)", not same, same)
check("sampler.json: the mini order, less the dropped tiers", samp["order"] == [k for k in mini["order"] if k in sk])
check("sampler.json: maxTier is the last tier", samp["maxTier"] == len(samp["order"]) - 1)
check("sampler.json: a budget, at most mini.json's (whose tiers all fit it)", 0 < samp["budgetMB"] <= mini["budgetMB"])
for k in ("lite", "soundPolicy", "lowLevel"):
    check(f"sampler.json: {k} as mini.json", samp.get(k) == mini.get(k))
out = tl.lua(samp)
check("sampler.json: tiers_lua.py reads it", '[1] = { key = "dalaran"' in out and 'slice = "sampler"' in out, out[:300])
bad_words = re.compile(r"world of warcraft|warcraft|blizzard|lich king|\bwow\b", re.I)
check("sampler.json: title and notes say Sample Hangout, no game-brand words",
      "Leyline Sample Hangout" in samp["title"] and not bad_words.search(samp["title"] + samp.get("comment", "") + samp.get("notStreamed", "")))

# ---- 4. slice-install.sh beside the served slice, slice-serve.sh to switch -------------------------------
d = tempfile.mkdtemp()
wu, bin_ = os.path.join(d, "srv", "wrath"), os.path.join(d, "bin")
stp = os.path.join(wu, "stream")
for p in (bin_, os.path.join(stp, "lua"), os.path.join(stp, "slices", "mini", "DBFilesClient"), os.path.join(wu, "portal"),
          os.path.join(wu, "custom", "lua_scripts"), os.path.join(d, "work", "sampler", "DBFilesClient")):
    os.makedirs(p, exist_ok=True)
for f in ("stream-lib.sh", "slice-install.sh", "slice-serve.sh"):
    shutil.copy(os.path.join(HERE, "server", f), stp)
for f in ("tiers_lua.py", "lfg_ids.py", "ov_slices.lua"):
    shutil.copy(os.path.join(HERE, "lua", f), os.path.join(stp, "lua"))
shutil.copy(os.path.join(HERE, "lua", "ov_slices.lua"), os.path.join(wu, "custom", "lua_scripts"))
shutil.copy(os.path.join(HERE, "slices", "mini.json"), os.path.join(stp, "slices"))
shutil.copy(os.path.join(HERE, "slices", "sampler.json"), os.path.join(d, "work"))
open(os.path.join(d, "work", "sampler", "DBFilesClient", "Map.dbc"), "w").write("x")
open(os.path.join(wu, "portal.env"), "w").write("WU_STREAM=1\nSTREAM_SLICES=mini\n")
open(os.path.join(wu, "soap-cmd.sh"), "w").write('echo "$*" >> "$FAKE_LOG"\n')
open(os.path.join(bin_, "docker"), "w").write('#!/bin/sh\necho "docker $*" >> "$FAKE_LOG"\nexit 0\n')
open(os.path.join(bin_, "sleep"), "w").write("#!/bin/sh\nexit 0\n")
for f in ("docker", "sleep"):
    os.chmod(os.path.join(bin_, f), 0o755)
LOG = os.path.join(d, "log")
env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"], WU_DIR=wu, FAKE_LOG=LOG)
tiers = os.path.join(wu, "custom", "lua_scripts", "ov_slices_tiers.lua")
subprocess.run(["bash", os.path.join(stp, "slice-serve.sh"), "mini"], env=env, capture_output=True, text=True)
mini_tiers = read(tiers)
open(LOG, "w").close()
tar = subprocess.run(["tar", "-cf", "-", "-C", os.path.join(d, "work"), "sampler.json", "sampler"], capture_output=True).stdout
r = subprocess.run(["bash", os.path.join(stp, "slice-install.sh"), "sampler", "100"], input=tar, env=env, capture_output=True)
out = r.stdout.decode() + r.stderr.decode()
check("slice-install sampler: installed beside mini", r.returncode == 0 and os.path.isdir(os.path.join(stp, "slices", "sampler"))
      and os.path.isdir(os.path.join(stp, "slices", "mini")) and "beside the served one" in out, out)
check("slice-install sampler: the realm rule and wu-play left alone", read(tiers) == mini_tiers
      and "wu-play" not in read(LOG) and "reload ale" not in read(LOG), read(LOG))
r = subprocess.run(["bash", os.path.join(stp, "slice-serve.sh"), "sampler"], env=env, capture_output=True, text=True)
pe = read(os.path.join(wu, "portal.env"))
check("slice-serve sampler: SLICE SERVE OK", r.returncode == 0 and r.stdout.rstrip().endswith("SLICE SERVE OK"), r.stdout + r.stderr)
check("slice-serve sampler: realm tiers from sampler.json", 'slice = "sampler"' in read(tiers) and "stormwind" not in read(tiers))
check("slice-serve sampler: portal serves it", "STREAM_SLICES=sampler" in pe and "WU_PLAY_SLICE=sampler" in pe)
check("slice-serve sampler: wu-play mounts the sampler slice read-only", "/slices/sampler:/slice:ro" in read(LOG) and "reload ale" in read(LOG))
r = subprocess.run(["bash", os.path.join(stp, "slice-serve.sh"), "mini"], env=env, capture_output=True, text=True)
check("slice-serve mini: the rollback, mini's tiers again", r.returncode == 0 and read(tiers) == mini_tiers
      and "STREAM_SLICES=mini" in read(os.path.join(wu, "portal.env")))
r = subprocess.run(["bash", os.path.join(stp, "slice-serve.sh"), "nope"], env=env, capture_output=True, text=True)
check("slice-serve: an uninstalled slice refused", r.returncode != 0 and "missing" in r.stderr)
env1 = dict(env, WU_SLICE_SERVE="1")
r = subprocess.run(["bash", os.path.join(stp, "slice-install.sh"), "sampler", "100"], input=tar, env=env1, capture_output=True)
check("slice-install with WU_SLICE_SERVE=1 (Make sampler slice.bat): serves it at once",
      r.returncode == 0 and "SLICE SERVE OK" in r.stdout.decode() and "STREAM_SLICES=sampler" in read(os.path.join(wu, "portal.env")))
shutil.rmtree(d, ignore_errors=True)
bat = read(os.path.join(HERE, "Make sampler slice.bat"))
check("Make sampler slice.bat: WU_SLICE=sampler, serve, then the mini script", 'set "WU_SLICE=sampler"' in bat
      and 'set "WU_SLICE_SERVE=1"' in bat and 'Make mini slice.bat' in bat)
mk_bat = read(os.path.join(HERE, "Make mini slice.bat"))
check("Make mini slice.bat: defaults to mini, uses the slice name everywhere",
      'if not defined WU_SLICE set "WU_SLICE=mini"' in mk_bat and "slice-install.sh %SL%" in mk_bat
      and not re.search(r"^(?!rem).*slices\\mini\.json(?! \"%W%\\kit)", mk_bat, re.M))
ctl = read(os.path.join(REPO, "tools", "control", "control.py"))
for step, f in (("sampler-check", "Sample hangout - check.bat"), ("sampler", "Sample hangout - on.bat"),
                ("sampler-off", "Sample hangout - off.bat"), ("slice-sampler", "Make sampler slice.bat")):
    check(f"Autopilot step {step} -> {f}", f'"{step}":' in ctl and f in ctl
          and os.path.isfile(os.path.join(REALM if f.startswith("Sample") else HERE, f)))

print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
