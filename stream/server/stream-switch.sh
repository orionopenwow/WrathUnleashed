#!/usr/bin/env bash
# The off switch for browser streaming:  bash /srv/wrath/stream/stream-switch.sh off|on
#   off: /wrath/play says "Streaming is off right now — play with your own game files", the stream
#        site refuses the game data and the login, and every stream account is released at once
#        (no one stays held to the slice). wu-play and the Caddy site stay in place.
#   on:  streaming again (after stream-up.sh has run once).
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
cd "$WU"
case "${1:-}" in
  on)  v=1 ;;
  off) v=0 ;;
  *)   die "usage: bash $ST/stream-switch.sh on|off" ;;
esac
[ -f "$WU/portal.env" ] || die "$WU/portal.env missing"
if [ "$v" = 1 ]; then
  grep -q 'stream_play' "$WU/portal/wrath_portal.py" || die "the sign-in page has no streaming yet: run stream-up.sh"
  docker ps --format '{{.Names}}' | grep -cx wu-play >/dev/null || die "wu-play is not running: run stream-up.sh"
fi
kv_set "$WU/portal.env" WU_STREAM "$v"
recreate_portal || die "wu-portal did not come back (docker logs wu-portal)"
if [ "$v" = 0 ]; then
  echo "DELETE FROM ov_stream_accounts;" | docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' 2>/dev/null \
    && echo "  stream accounts released" || echo "  (no stream accounts table)"
  soap "reload ale" >/dev/null 2>&1 || echo "  WARNING: reload ale failed; marks still in the world server's memory end within 12 h"
  echo "Streaming is OFF."
else
  echo "Streaming is ON."
fi
