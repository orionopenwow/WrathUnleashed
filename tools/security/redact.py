"""Redact secrets from config text (Caddyfile, compose files, .env lines) before it leaves the server.

    python3 -I redact.py FILE...      prints each file, secrets replaced by <redacted>

A value is redacted when its key looks secret, when it is a URL's or an AzerothCore database line's password, (pass, secret, token, key, auth, credential, dsn, private, cookie,
salt, hash), when it is a Caddy basicauth/basic_auth line or a bcrypt hash, or when it is a PEM block.
"""
import re
import sys

SECRET = r"(pass|pwd|secret|token|api[_-]?key|private|credential|dsn|auth|cookie|salt|hash|_key\b|^key\b|webhook)"
KV = re.compile(r"^(\s*-?\s*[\"']?)([A-Za-z0-9_.\-]+)([\"']?\s*[:=]\s*)(.+)$")
BCRYPT = re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}")
URL_CRED = re.compile(r"(://[^/\s:@]+:)[^@\s/]+@")
AC_DB_INFO = re.compile(r"(;\d+;[^;\"'\s]+;)[^;\"'\s]+(;)")   # AzerothCore "host;port;user;PASS;db"


def redact_line(line: str, state: dict) -> str:
    if "-----BEGIN" in line:
        state["pem"] = True
    if state.get("pem"):
        if "-----END" in line:
            state["pem"] = False
        return "<redacted PEM line>\n"
    line = BCRYPT.sub("<redacted bcrypt>", line)
    line = URL_CRED.sub(r"\1<redacted>@", line)
    line = AC_DB_INFO.sub(r"\1<redacted>\2", line)
    m = KV.match(line.rstrip("\n"))
    if m and re.search(SECRET, m.group(2), re.I) and m.group(4).strip() not in ("", "|", ">"):
        return f"{m.group(1)}{m.group(2)}{m.group(3)}<redacted>\n"
    s = line.strip()
    indent = line[: len(line) - len(line.lstrip())]
    if re.match(r"(basicauth|basic_auth)\b.*\{$", s, re.I):   # a block of "user hash" lines follows
        state["auth"] = True
        return line
    if state.get("auth"):
        if s == "}":
            state["auth"] = False
            return line
        return (indent + s.split()[0] + " <redacted>\n") if s else line
    if re.match(r"(basicauth|basic_auth|api_token)\b", s, re.I):
        return indent + s.split()[0] + " <redacted>\n"
    if re.match(r"(dns\s+\S+|header_up\s+-?Authorization|header\s+-?Authorization|request_header\s+-?Authorization)\b", s, re.I):
        w = s.split()
        return indent + " ".join(w[:2]) + (" <redacted>" if len(w) > 2 else "") + "\n"
    return line


def redact(text: str) -> str:
    state: dict = {}
    return "".join(redact_line(l, state) for l in text.splitlines(keepends=True))


if __name__ == "__main__":
    for path in sys.argv[1:]:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError as e:
            print(f"### {path}: not readable ({e.strerror})")
            continue
        print(f"### {path}")
        sys.stdout.write(redact(body))
        if not body.endswith("\n"):
            print()
