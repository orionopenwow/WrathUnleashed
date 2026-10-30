#!/usr/bin/env python3
"""Turns mod-playerbots' premade talent specs (Playerbots.PremadeSpecName/Glyph/Link.* in playerbots.conf.dist)
into AC_ environment lines, because the realm runs on env settings only and never installs the module's .conf:
without them every bot answers "talents spec list" with "Total 0 specs found" and Companions can't set roles.

Usage: make_specs_env.py <playerbots.conf.dist> > realm/playerbots-specs.env
The env names follow AzerothCore's IniKeyToEnvVarKey (src/common/Configuration/Config.cpp) exactly,
so "Playerbots.PremadeSpecName.2.0" becomes AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__0.
"""
import re
import sys


def ini_key_to_env(key):
    out = []
    n = len(key)
    for i, c in enumerate(key):
        if c in " .-":
            out.append("_")
            continue
        if i < n - 1:
            nxt = key[i + 1]
            if not c.isupper() and nxt.isupper():
                out.append(c.upper() + "_")
                continue
            if not c.isdigit() and nxt.isdigit():
                out.append(c.upper() + "_")
                continue
            if c.isdigit() and not nxt.isdigit():
                out.append(c.upper() + "_")
                continue
        out.append(c.upper())
    return "AC_" + "".join(out)


LINE = re.compile(r"^(Playerbots\.PremadeSpec(?:Name|Glyph|Link)\.[0-9.]+)\s*=\s*(.*?)\s*$")


def main(path):
    lines = []
    for raw in open(path, encoding="utf-8"):
        m = LINE.match(raw)
        if not m:
            continue
        val = m.group(2).strip('"')
        if not re.fullmatch(r"[A-Za-z0-9 ,\-]*", val):
            raise SystemExit("unexpected value for %s: %r" % (m.group(1), val))
        lines.append("%s=%s" % (ini_key_to_env(m.group(1)), val))
    if not lines:
        raise SystemExit("no PremadeSpec lines in " + path)
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
