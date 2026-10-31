#!/usr/bin/env bash
# The ONLY thing GitHub's deploy key may run on the server (/srv/wrath/luaup-ci.sh). Its line in
# /root/.ssh/authorized_keys is
#     restrict,command="/srv/wrath/luaup-ci.sh" ssh-ed25519 AAAA... wu-deploy-github-actions
# so sshd runs this for every login with that key, whatever the client asked for (no shell, no port forwarding,
# no pty, no agent). It takes a tar of realm .lua scripts on stdin and nothing else:
#   * every entry must be a plain file named like ov_main.lua (letters, digits, underscores) at the top of the tar,
#     at most 2 MB each, 8 MB and 64 files in all; anything else (a folder, a link, ../, another name) refuses
#     the whole upload;
#   * only scripts the realm already runs: a NEW script needs a restart with the 5-minute warning (a live
#     "reload ale" that added new scripts once crashed the world server), so it goes through the Server pass;
#   * then the existing live path: /srv/wrath/luaup.sh (backs up each file, "reload ale", puts the old ones back
#     if the reload fails).
# Prints LUAUP OK at the end on success (the workflow checks for it).
set -euo pipefail
umask 077
WU=${WU_DIR:-/srv/wrath}
DST=${WU_LUA_DIR:-$WU/custom/lua_scripts}
LUAUP=${WU_LUAUP:-$WU/luaup.sh}
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/wu-luaup-ci.XXXXXX"); trap 'rm -rf "$STAGE"' EXIT
from=${SSH_CLIENT:-local}; from=${from%% *}
logger -t wu-luaup-ci "deploy from $from (asked: ${SSH_ORIGINAL_COMMAND:-none})" 2>/dev/null || true

# Read at most 9 MB of stdin, then check and unpack it with Python's tarfile (no tar flags to get wrong).
head -c 9437184 > "$STAGE/up.tar"
python3 -I - "$STAGE/up.tar" "$STAGE/files" "$DST" <<'PY'
import os, re, sys, tarfile
src, out, dst = sys.argv[1:4]
NAME = re.compile(r"^[A-Za-z0-9_]{1,64}\.lua$")
def no(msg):
    print("LUAUP REFUSED: " + msg, file=sys.stderr)
    sys.exit(3)
try:
    tf = tarfile.open(src, "r:")
except (tarfile.TarError, OSError):
    no("stdin is not a tar")
os.makedirs(out)
total = n = 0
with tf:
    for m in tf.getmembers():
        name = m.name[2:] if m.name.startswith("./") else m.name
        if m.isdir() and name in ("", "."):
            continue
        if not m.isfile() or not NAME.fullmatch(name):
            no(f"only top-level .lua files may be sent (got {m.name!r})")
        if m.size > 2 * 1024 * 1024:
            no(f"{name} is over 2 MB")
        total += m.size; n += 1
        if total > 8 * 1024 * 1024 or n > 64:
            no("the upload is too big (8 MB, 64 files at most)")
        if not os.path.isfile(os.path.join(dst, name)):
            no(f"{name} is a new script: new scripts load with a restart (the Server pass), not a live reload")
        data = tf.extractfile(m).read()
        if b"\0" in data:
            no(f"{name} is not text")
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
if n == 0:
    no("no .lua files in the upload")
print(f"  {n} script(s) checked")
PY
[ -x "$LUAUP" ] || [ -f "$LUAUP" ] || { echo "LUAUP REFUSED: $LUAUP is missing" >&2; exit 3; }
(cd "$STAGE/files" && tar -cf - -- *.lua) | bash "$LUAUP"
