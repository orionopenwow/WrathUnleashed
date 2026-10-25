#!/usr/bin/env bash
# Leyline Discord bridge on the realm box: install or update /opt/wu-discord. Run as root by
# "hosting/discord/Deploy Discord bridge.bat" (the folder arrives as a tarball over stdin):  bash discord-up.sh <source dir>
# Safe to run again: it replaces only the code and the unit, and keeps discord.env, mutes.txt and the state.
#
#   1 checks   root, python3 3.10+, systemd, the upload
#   2 files    /opt/wu-discord/app/wudiscord, discord.env (from the example, chmod 600; the SOAP login from
#              /srv/wrath/signup.env when empty), mutes.txt, the wu-discord user, /etc/systemd/system/wu-discord.service
#   3 check    python3 -m wudiscord.bridge --check (settings only, no network)
#   4 service  restarted only if the owner already turned it on (systemctl is-enabled); never enabled from here
#
# Last line: "DISCORD BRIDGE OK" (running the new code), "DISCORD BRIDGE INSTALLED (OFF)" (waiting for the owner),
# or an error (exit 1). Paths can be moved for tests (hosting/tests/test_discord_bridge.py).
set -euo pipefail
SRC="${1:?usage: discord-up.sh <source dir>}"
DIR="${WU_DISCORD_DIR:-/opt/wu-discord}"
UNIT_DIR="${WU_UNIT_DIR:-/etc/systemd/system}"
SIGNUP_ENV="${WU_SIGNUP_ENV:-/srv/wrath/signup.env}"
PY="${WU_PYTHON:-python3}"
log() { printf '\n== %s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf '\nDISCORD BRIDGE FAILED: %s\n' "$*" >&2; exit 1; }
kv_get() { sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1; }
kv_set() {  # in place, without sed (a password may hold any character)
  "$PY" -I - "$1" "$2" "$3" <<'PY'
import sys
f, k, v = sys.argv[1:]
lines = open(f).read().split("\n")
if any(l.startswith(k + "=") for l in lines):
    lines = [f"{k}={v}" if l.startswith(k + "=") else l for l in lines]
else:
    lines.insert(len(lines) - 1 if lines and lines[-1] == "" else len(lines), f"{k}={v}")
open(f, "w").write("\n".join(lines))
PY
}

# CRLF from a Windows checkout would break the shell, unit and env files.
find "$SRC" -type f \( -name '*.sh' -o -name '*.py' -o -name '*.service' -o -name '*.example' \) -exec sed -i 's/\r$//' {} +

log "1/4 Checks"
[ "${WU_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root"
command -v "$PY" >/dev/null || die "python3 not found"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "python3 3.10 or later is needed"
command -v systemctl >/dev/null || die "systemd (systemctl) not found"
for f in discord/wudiscord/bridge.py discord/wudiscord/__init__.py discord/deploy/wu-discord.service discord/deploy/discord.env.example; do
  [ -f "$SRC/$f" ] || die "$f is missing from the upload. Nothing was changed."
done

log "2/4 Files in $DIR"
mkdir -p "$DIR/app"
rm -rf "$DIR/app/wudiscord.new" "$DIR/app/wudiscord.old"
cp -r "$SRC/discord/wudiscord" "$DIR/app/wudiscord.new"
find "$DIR/app/wudiscord.new" -name '__pycache__' -prune -exec rm -rf {} +
if [ -d "$DIR/app/wudiscord" ]; then mv "$DIR/app/wudiscord" "$DIR/app/wudiscord.old"; fi
mv "$DIR/app/wudiscord.new" "$DIR/app/wudiscord"
note "code installed (the previous copy, if any, is app/wudiscord.old)"
ENVF="$DIR/discord.env"
if [ ! -f "$ENVF" ]; then
  install -m 600 "$SRC/discord/deploy/discord.env.example" "$ENVF"
  note "discord.env made from the example: the owner fills in DISCORD_BOT_TOKEN and the channel ids"
fi
chmod 600 "$ENVF"
if [ -z "$(kv_get "$ENVF" SOAP_USER)" ] && [ -f "$SIGNUP_ENV" ]; then
  kv_set "$ENVF" SOAP_USER "$(kv_get "$SIGNUP_ENV" SOAP_USER)"
  kv_set "$ENVF" SOAP_PASS "$(kv_get "$SIGNUP_ENV" SOAP_PASS)"
  note "SOAP login copied from $SIGNUP_ENV"
fi
[ -f "$DIR/mutes.txt" ] || printf '# Muted both ways: one Discord user id or character name per line. Re-read live.\n' > "$DIR/mutes.txt"
if [ "${WU_TEST:-0}" != 1 ]; then
  id -u wu-discord >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin wu-discord
  chown root:root "$ENVF"
  chown wu-discord "$DIR/mutes.txt"
fi
install -m 644 "$SRC/discord/deploy/wu-discord.service" "$UNIT_DIR/wu-discord.service"
systemctl daemon-reload
note "unit installed: $UNIT_DIR/wu-discord.service"

log "3/4 Settings check (no network)"
set +e
CHECK=$(env -u DISCORD_BOT_TOKEN PYTHONPATH="$DIR/app" "$PY" -m wudiscord.bridge --check --env-file "$ENVF" 2>&1)
RC=$?
set -e
# the check prints channel ids and the SOAP user only, never the token or the password
printf '%s\n' "$CHECK" | sed 's/^/  /'

log "4/4 Service"
if systemctl is-enabled wu-discord >/dev/null 2>&1; then
  [ "$RC" = 0 ] || die "the bridge is turned on but its settings are incomplete (see above); the running copy was not restarted"
  systemctl restart wu-discord
  sleep "${WU_SETTLE:-3}"
  if ! systemctl is-active wu-discord >/dev/null 2>&1; then
    rm -rf "$DIR/app/wudiscord"
    if [ -d "$DIR/app/wudiscord.old" ]; then mv "$DIR/app/wudiscord.old" "$DIR/app/wudiscord"; fi
    systemctl restart wu-discord || true
    die "wu-discord did not stay up with the new code (journalctl -u wu-discord); the previous code is back"
  fi
  echo "DISCORD BRIDGE OK"
else
  note "not turned on (the owner does that):"
  note "  1. edit $ENVF (DISCORD_BOT_TOKEN, DISCORD_CHAT_CHANNEL_ID, DISCORD_BUG_CHANNEL_ID)"
  note "  2. systemctl enable --now wu-discord        (logs: journalctl -u wu-discord -f)"
  echo "DISCORD BRIDGE INSTALLED (OFF)"
fi
