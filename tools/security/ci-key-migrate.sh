#!/usr/bin/env bash
# DRAFT (not wired to Autopilot; the main session decides). Turns the GitHub deploy key that is already on the
# server into a one-command key, without making a new key (the WU_DEPLOY_SSH_KEY secret stays as it is):
#   ssh-ed25519 AAAA... wu-deploy-github-actions          (today: "restrict" only = a full root shell)
# becomes
#   restrict,command="/srv/wrath/luaup-ci.sh" ssh-ed25519 AAAA... wu-deploy-github-actions
#
#   bash ci-key-migrate.sh            dry run: shows the old and new line (keys shortened), changes nothing
#   bash ci-key-migrate.sh --apply    installs luaup-ci.sh and luaup.sh (from beside this file) into /srv/wrath,
#                                     backs up authorized_keys, rewrites the line(s)
# Run from a folder holding luaup-ci.sh and luaup.sh ("CI key - restrict (draft).bat" sends all three).
# Undo: cp /root/.ssh/authorized_keys.before-ci-<time> /root/.ssh/authorized_keys
# After: push a small realm-script change (or run the "realm scripts" workflow) and check its deploy says LUAUP OK.
set -euo pipefail
cd "$(dirname "$0")"
AK=${WU_AUTH_KEYS:-/root/.ssh/authorized_keys}
WU=${WU_DIR:-/srv/wrath}
TAG=${WU_CI_KEY_TAG:-wu-deploy-github-actions}
APPLY=""; [ "${1:-}" = "--apply" ] && APPLY=1
[ -f "$AK" ] || { echo "No $AK."; exit 1; }
n=$(grep -c " $TAG\$" "$AK" || true)
echo "deploy key lines ($TAG): $n"
[ "$n" -gt 0 ] || { echo "Nothing to change (run 'setup\\Set up automatic deploys.bat' to make one)."; echo "CI KEY OK"; exit 0; }
NEW=$(mktemp); trap 'rm -f "$NEW"' EXIT
python3 -I - "$AK" "$NEW" "$TAG" "$WU/luaup-ci.sh" <<'PY'
import re, sys
src, dst, tag, cmd = sys.argv[1:5]
KEYTYPE = re.compile(r"(?:^|\s)((?:ssh-|ecdsa-|sk-)\S+\s+\S+.*)$")
out = []
for line in open(src, encoding="utf-8").read().splitlines():
    if line.endswith(" " + tag) and not line.lstrip().startswith("#"):
        m = KEYTYPE.search(line)
        if not m:
            sys.exit("a deploy key line I can't read; nothing changed")
        new = f'restrict,command="{cmd}" {m.group(1)}'
        short = lambda s: re.sub(r"(AAAA\S{6})\S+", r"\1...", s)
        print("  old: " + short(line)); print("  new: " + short(new))
        line = new
    out.append(line)
open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
if [ -z "$APPLY" ]; then echo "Dry run: nothing changed. --apply to do it."; echo "CI KEY DRY"; exit 0; fi
for f in luaup-ci.sh luaup.sh; do [ -f "$f" ] || { echo "$f is missing beside this script."; exit 1; }; done
sed -i 's/\r$//' luaup-ci.sh luaup.sh
bash -n luaup-ci.sh && bash -n luaup.sh
install -m 755 luaup-ci.sh "$WU/luaup-ci.sh"
install -m 755 luaup.sh "$WU/luaup.sh"
BK="$AK.before-ci-$(date +%Y%m%d-%H%M%S)"; cp -p "$AK" "$BK"
cat "$NEW" > "$AK"; chmod 600 "$AK"
echo "Done. Backup: $BK"
echo "CI KEY OK"
