"""Keeps the bot talent specs consistent: realm/serverpass.sh's embedded copy and realm/profiles/main.env must
hold exactly realm/playerbots-specs.env, and every spec ov_companions.lua asks bots for must exist in it.
Run from the repo root: python3 -I stream/tests/test_serverpass_specs.py"""
import re
import sys

env = open("realm/playerbots-specs.env").read()
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails += 1


sp = open("realm/serverpass.sh").read()
m = re.search(r"<<'OV_SPECS_EOF'\n(.*?)OV_SPECS_EOF\n", sp, re.S)
check("serverpass.sh embeds the specs", m is not None and m.group(1) == env)
prof = open("realm/profiles/main.env").read()
specs_in_profile = "".join(l + "\n" for l in prof.splitlines() if l.startswith("AC_PLAYERBOTS_PREMADE_SPEC_"))
check("main.env holds the same specs", specs_in_profile == env)

names = {}
for line in env.splitlines():
    k, v = line.split("=", 1)
    mm = re.fullmatch(r"AC_PLAYERBOTS_PREMADE_SPEC_NAME_(\d+)__(\d+)", k)
    if mm:
        names.setdefault(int(mm.group(1)), set()).add(v)
check("specs for all 10 classes", sorted(names) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11])
cls = {"warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4, "priest": 5, "dk": 6, "shaman": 7, "mage": 8,
       "warlock": 9, "druid": 11}
lua = open("realm/custom/lua_scripts/ov_companions.lua").read()
asked = re.findall(r'\{ *"(\w+)", *"([a-z ]+ pv[ep])" *\}', lua)
check("ov_companions.lua asks for specs", len(asked) >= 10)
for c, spec in asked:
    check("spec exists: %s %s" % (c, spec), spec in names.get(cls.get(c, 0), set()))
sys.exit(1 if fails else 0)
