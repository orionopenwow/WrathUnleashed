#!/usr/bin/env bash
# Undo stream-up.sh: the stream site, the slice host, the realm rule and the gate's streaming.
# The slice files stay in /srv/wrath/stream/slices (delete them yourself to free the disk).
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
cd "$WU" || exit 1
warn() { echo "!! $*" >&2; }
log "1/4 Caddy site block"
if [ -f "$CF" ] && grep -qF "$MARK_BEGIN" "$CF"; then
  cp -p "$CF" "$WU/Caddyfile.stream-down-backup"
  caddy_strip || warn "could not edit $CF"
  caddy_reload || { cat "$WU/Caddyfile.stream-down-backup" > "$CF"; caddy_reload; warn "Caddy refused the Caddyfile without the block; left as it was"; }
else
  echo "  no streaming block in $CF"
fi
log "2/4 Slice host"
docker rm -f wu-play >/dev/null 2>&1 && echo "  wu-play removed" || echo "  wu-play was not running"
log "3/4 Sign-in gate"
[ -f "$WU/portal.env" ] && kv_set "$WU/portal.env" WU_STREAM 0
[ -f "$WU/portal.env" ] && kv_set "$WU/portal.env" WU_OWNFILES 0
if [ -f "$WU/portal/wrath_portal.py.before-stream" ]; then
  cp -p "$WU/portal/wrath_portal.py.before-stream" "$WU/portal/wrath_portal.py"
  echo "  the previous wrath_portal.py is back"
fi
recreate_portal || warn "wu-portal did not come back (docker logs wu-portal)"
log "4/4 Realm rule"
echo "DELETE FROM ov_stream_accounts;" | docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' >/dev/null 2>&1 \
  && echo "  stream accounts released"
rm -f "$WU/custom/lua_scripts/ov_slices.lua" "$WU/custom/lua_scripts/ov_slices_lfg.lua" "$WU/custom/lua_scripts/ov_slices_tiers.lua"
soap "reload ale" >/dev/null 2>&1 || warn "reload ale failed (restart the world server to unload ov_slices.lua)"
echo
echo "Streaming is removed. The DNS record for $STREAM_HOST can stay or go."
