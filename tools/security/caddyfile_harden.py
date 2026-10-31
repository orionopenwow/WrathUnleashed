"""Add the hardening to a Caddyfile (used by caddy-apply.sh; a DRAFT, not wired to Autopilot).

    python3 -I caddyfile_harden.py IN OUT [--site play.openvanilla.app]

1. Global options: servers { timeouts { read_header 10s  read_body 30s  idle 120s } }. No write timeout, so
   game-file downloads and WebSockets (/ws/3724, /ws/8085, the relay) are never cut. Kept if one is already there.
2. In the named site block (and the stream site, wrath.openvanilla.app, when stream-up.sh did not add it already):
   request_body /wrath* { max_size 2MB } (the portal's forms and JSON are a few KB; nothing under /wrath uploads).
Prints what it changed; exit 0 with no change when everything is there already.
"""
import re
import sys

TIMEOUTS = "\tservers {\n\t\ttimeouts {\n\t\t\tread_header 10s\n\t\t\tread_body 30s\n\t\t\tidle 120s\n\t\t}\n\t}\n"
BODY = "\t# hardening (tools/security/caddy-apply.sh): the portal's forms and JSON are a few KB\n\trequest_body /wrath* {\n\t\tmax_size 2MB\n\t}\n"


def blocks(text: str):
    """(start, open_brace_end, close_end, head) of each top-level block."""
    out, depth, i, n = [], 0, 0, len(text)
    start = head_start = 0
    while i < n:
        c = text[i]
        if c == "#" and (i == 0 or text[i - 1] in " \t\n"):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            if depth == 0:
                start = text.rfind("\n", 0, i) + 1
                head = text[start:i].strip()
                brace = i + 1
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                out.append((start, brace, i + 1, head))
        i += 1
    return out


def harden(text: str, sites=("play.openvanilla.app",)) -> tuple[str, list]:
    did = []
    bl = blocks(text)
    glob = next((b for b in bl if b[3] == ""), None)
    if glob is None:
        text = "{\n" + TIMEOUTS + "}\n\n" + text
        did.append("added a global options block with server timeouts")
    elif "timeouts" not in text[glob[1]:glob[2]]:
        body = text[glob[1]:glob[2] - 1]
        if re.search(r"^\s*servers\b[^\n]*\{", body, re.M):
            m = re.search(r"^(\s*servers\b[^\n]*\{\n)", body, re.M)
            ins = glob[1] + m.end()
            text = text[:ins] + "\t\ttimeouts {\n\t\t\tread_header 10s\n\t\t\tread_body 30s\n\t\t\tidle 120s\n\t\t}\n" + text[ins:]
        else:
            ins = glob[1]
            if not text[ins:ins + 1] == "\n":
                text = text[:ins] + "\n" + text[ins:]
            ins += 1
            text = text[:ins] + TIMEOUTS + text[ins:]
        did.append("added server timeouts to the global options")
    for site in list(sites) + ["wrath.openvanilla.app"]:
        bl = blocks(text)
        b = next((x for x in bl if site in re.split(r"[\s,]+", x[3].replace("https://", ""))), None)
        if b is None:
            if site in sites:
                did.append(f"site {site}: not found (nothing changed there)")
            continue
        if "request_body" in text[b[1]:b[2]]:
            continue
        ins = b[1]
        if text[ins:ins + 1] == "\n":
            ins += 1
        text = text[:ins] + BODY + text[ins:]
        did.append(f"site {site}: request bodies under /wrath capped at 2MB")
    return text, did


if __name__ == "__main__":
    args = sys.argv[1:]
    sites = ["play.openvanilla.app"]
    if "--site" in args:
        k = args.index("--site")
        sites = [args[k + 1]]
        del args[k:k + 2]
    src, dst = args[0], args[1]
    with open(src, encoding="utf-8") as f:
        text = f.read()
    new, did = harden(text, sites)
    for d in did:
        print("  " + d)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(new)
