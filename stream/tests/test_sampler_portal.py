"""The portal under the Leyline Sample Hangout (WU_SAMPLER=1, WU_PLAY_SLICE=sampler): the play page, /wrath/realms
and /wrath/leyline name it and say it is temporary; ?mini=mini links reach the served slice; without the flags,
nothing changes.

    python3 -I stream/tests/test_sampler_portal.py stream/wrath_portal.py
"""
import importlib.util, json, os, re, shutil, sys, tempfile

fails = count = 0


def check(name, cond, extra=""):
    global fails, count
    count += 1
    print(("PASS " if cond else "FAIL ") + name + (f"  {str(extra)[:400]}" if extra and not cond else ""))
    fails += 0 if cond else 1


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
for n in ("mini", "sampler"):
    shutil.copy(os.path.join(HERE, "slices", n + ".json"), tmp)
BASE = dict(SOAP_USER="WUSOAP", SOAP_PASS="x", AC_SOAP_URL="http://127.0.0.1:9/", PORTAL_URL="http://127.0.0.1:9",
            WU_STREAM="1", STREAM_HOST="wrath.example", WU_RELAY_LISTING="http://127.0.0.1:9/realms.json",
            WU_JOIN_BASE="https://relay.example", WU_SLICE_DIR=tmp)


def portal(**env):
    for k in ("WU_SAMPLER", "WU_PLAY_SLICE", "STREAM_SLICES"):
        os.environ.pop(k, None)
    os.environ.update(BASE, **env)
    spec = importlib.util.spec_from_file_location("wp" + str(count), sys.argv[1])
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


BRAND = re.compile(r"world of warcraft|warcraft|blizzard|lich king|\bwow\b", re.I)


def text(b):
    s = b.decode("utf-8") if isinstance(b, bytes) else str(b)
    return re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", s, flags=re.S))


wp = portal(WU_SAMPLER="1", WU_PLAY_SLICE="sampler", STREAM_SLICES="sampler")
check("sampler: ?mini=mini resolves to the served sampler slice", (wp.slice_info("mini") or {}).get("tier") == json.load(
    open(os.path.join(tmp, "sampler.json")))["maxTier"], wp.slice_info("mini"))
check("sampler: the mini slice itself is not served", wp.slice_info("mini") is not None and "mini" not in wp.STREAM_SLICES)
page = text(wp.realms_page())
check("/wrath/realms: the official card is the Leyline Sample Hangout, temporary",
      "Leyline Sample Hangout" in page and "Temporary" in page, page[:400])
check("/wrath/realms: says to add your own game folder for the whole world, and community realms",
      "add your own 3.3.5a game folder to explore the whole world" in page and "Community realms on Leyline" in page)
check("/wrath/realms: no game-brand words", not BRAND.search(page))
ly = text(wp.leyline_page())
check("/wrath/leyline: the official row says Sample Hangout, temporary", "Leyline Sample Hangout" in ly and "temporary" in ly)
acct = text(wp.account_page("Tester", "WR000123", "pw", "nonce"))
check("play page: the first card is the Leyline Sample Hangout, temporary, Play now",
      "Leyline Sample Hangout" in acct and "Temporary" in acct and "Play now" in acct, acct[:600])
check("play page: no game-brand words", not BRAND.search(acct))
check("the copy line is marked for the owner", "TODO(owner)" in open(sys.argv[1], encoding="utf-8").read().split("SAMPLER_NOTE")[1][:800])

wp = portal(STREAM_SLICES="mini")
check("no sampler: ?mini=mini is the mini slice", (wp.slice_info("mini") or {}).get("tier") == json.load(
    open(os.path.join(tmp, "mini.json")))["maxTier"])
page = text(wp.realms_page())
check("no sampler: the realm list as before (no Sample Hangout)", "Sample Hangout" not in page and "WrathUnleashed" in page)
acct = text(wp.account_page("Tester", "WR000123", "pw", "nonce"))
check("no sampler: the play page's Dalaran card as before", "Jump straight in: Dalaran" in acct and "Sample Hangout" not in acct)
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{count - fails}/{count} passed")
sys.exit(1 if fails else 0)
