"""realm/custom/leyline-fetch.py: the in-game Leyline window's realm list lists the Dalaran Hangout first (its id from
OV_LEYLINE_HOME or the hangout step's id file), then live realms, busiest first; with no hangout, as before.

    python3 -I stream/tests/test_leyline_fetch.py [realm/custom/leyline-fetch.py]
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FETCH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "realm", "custom", "leyline-fetch.py")
HANG = "hangouthangout22"
fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    fails += 0 if cond else 1


def rec(rid, name, live, players):
    return {"name": name, "state": "live" if live else "offline", "profile": {"ruleset": "dalaran"},
            "community": {"realmId": rid, "lastHeartbeat": {"players": players, "bots": 0}}}


tmp = tempfile.mkdtemp()
listing = os.path.join(tmp, "listing.json")
with open(listing, "w") as f:
    json.dump({"realms": [rec("abcdefghijklmnop", "Busy Den", True, 40), rec(HANG, "Dalaran Hangout", True, 2),
                          rec("qrstuvwxyz234567", "Quiet Corner", False, 0)]}, f)


def run(**env):
    out = os.path.join(tmp, "out.dat")
    e = dict(os.environ, OV_LEYLINE_OUT=out, OV_LEYLINE_HOME_FILE=os.path.join(tmp, "none.id"))
    e.pop("OV_LEYLINE_HOME", None)
    e.update(env)
    p = subprocess.run([sys.executable, "-I", FETCH, "--from", listing], env=e, capture_output=True, text=True)
    return p.returncode, re.findall(r'id = "([a-z2-7]{16})"', open(out).read()) if p.returncode == 0 else p.stderr


rc, ids = run()
check("no hangout: busiest live first", rc == 0 and ids == ["abcdefghijklmnop", HANG, "qrstuvwxyz234567"], ids)
rc, ids = run(OV_LEYLINE_HOME=HANG)
check("hangout first (env)", rc == 0 and ids[0] == HANG and ids[1:] == ["abcdefghijklmnop", "qrstuvwxyz234567"], ids)
idf = os.path.join(tmp, "hangout-realm.id")
with open(idf, "w") as f:
    f.write(HANG + "\n")
rc, ids = run(OV_LEYLINE_HOME_FILE=idf)
check("hangout first (the hangout step's id file)", rc == 0 and ids[0] == HANG, ids)
rc, ids = run(OV_LEYLINE_HOME="../../etc")
check("a junk hangout id changes nothing", rc == 0 and ids[0] == "abcdefghijklmnop", ids)
print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
