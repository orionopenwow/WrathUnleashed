#!/usr/bin/env bash
# WrathUnleashed: "Play in the browser, streamed". Run as root on the server after the kit and a
# slice are uploaded ("Make mini slice.bat"):   bash /srv/wrath/stream/stream-up.sh
# Safe to run again (it replaces what it made). Undo: bash /srv/wrath/stream/stream-down.sh
#
#   1 checks          the realm, the website, the kit, the slice, DNS for wrath.openvanilla.app
#   2 client page     index.html loads /__env.js (the login from the sign-in gate, never the URL)
#   3 realm rule      acore_auth.ov_stream_accounts + lua_scripts/ov_slices.lua (+ the slice's tiers
#                     and the Dungeon Finder ids: ov_slices_tiers.lua, ov_slices_lfg.lua)
#   4 sign-in gate    the new wrath_portal.py in /srv/wrath/portal, WU_STREAM=1, WU_OWNFILES=1
#                     ("Play with my own game files" uses the same site), wu-portal recreated
#   5 slice host      container wu-play: wenilla-host --only-listed on the slice, 256 MB, read-only
#   6 Caddy           a site block for wrath.openvanilla.app (backup kept; restored if Caddy refuses)
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
cd "$WU"
SLICE="${WU_SLICE:-mini}"
SLICE_DIR="$ST/slices/$SLICE"
trap 'echo "!! stream-up stopped at line $LINENO. Players on their own game files are not affected; bash $ST/stream-down.sh undoes the streaming parts." >&2' ERR

log "1/6 Checks"
command -v docker >/dev/null || die "docker not found"
docker network inspect "$NET" >/dev/null 2>&1 || die "network $NET not found (is the website stack running?)"
docker ps --format '{{.Names}}' | grep -cx ov-ac-worldserver >/dev/null || die "the Wrath world server (ov-ac-worldserver) is not running: run deploy.sh first"
docker ps --format '{{.Names}}' | grep -cx ov-ac-database >/dev/null || die "the Wrath database (ov-ac-database) is not running"
docker ps --format '{{.Names}}' | grep -cx wu-portal >/dev/null || die "the Wrath sign-in page (wu-portal) is not running: run deploy.sh first"
[ -f "$WU/portal.env" ] || die "$WU/portal.env missing (deploy.sh makes it)"
[ -f "$WU/soap-cmd.sh" ] || die "$WU/soap-cmd.sh missing"
[ -d "$WU/custom/lua_scripts" ] || die "$WU/custom/lua_scripts missing (the realm's mod-ale scripts)"
[ -f "$CF" ] || die "$CF not found"
for f in bin/wenilla-host wrath_portal.py lua/ov_slices.lua lua/lfg_ids.py lua/tiers_lua.py sql/ov_stream_accounts.sql "slices/$SLICE.json"; do
  [ -f "$ST/$f" ] || die "$ST/$f missing: upload the streaming kit (Make mini slice.bat does)"
done
[ -f "$ST/www/index.html" ] && ls "$ST"/www/*.wasm >/dev/null 2>&1 \
  || die "$ST/www has no browser client (index.html + wenilla_bg.wasm): copy the WotLK web build there"
grep -q "__wenilla_env" "$ST/www/index.html" || die "$ST/www/index.html is not the benilla client page (no __wenilla_env)"
for f in sections.js sections-worker.js ownfiles.js ownfiles-worker.js mpq.js chain.js; do
  [ -f "$ST/www/$f" ] || echo "  WARNING: www/$f missing: copy stream\\www-files\\* into stream\\www (Make mini slice.bat does) for \"Download this section\" and \"Play with my own game files\""
done
python3 -I "$ST/lua/tiers_lua.py" "$ST/slices/$SLICE.json" > /dev/null || die "slices/$SLICE.json: the tier list is broken (see above)"
[ -d "$SLICE_DIR" ] && [ -n "$(ls -A "$SLICE_DIR" 2>/dev/null)" ] || die "$SLICE_DIR is empty: build and upload the slice first (Make mini slice.bat)"
find "$SLICE_DIR" -maxdepth 2 -iname 'DBFilesClient' | grep -c . >/dev/null || die "$SLICE_DIR has no DBFilesClient folder: that is not an exported slice"
chmod 755 "$ST/bin/wenilla-host"
"$ST/bin/wenilla-host" --help >/dev/null 2>&1 || die "$ST/bin/wenilla-host does not run on this machine"
echo "  slice $SLICE: $(du -sh "$SLICE_DIR" | cut -f1), $(find "$SLICE_DIR" -type f | wc -l) files"
MYIP=$(curl -s -m 10 https://api.ipify.org || true)
DNSIP=$(getent ahostsv4 "$STREAM_HOST" | awk 'NR==1{print $1}' || true)
if [ -z "$DNSIP" ]; then
  echo "  WARNING: $STREAM_HOST has no DNS record yet. Add an A record -> ${MYIP:-the server IP}; Caddy gets the certificate once it resolves."
elif [ -n "$MYIP" ] && [ "$DNSIP" != "$MYIP" ]; then
  echo "  WARNING: $STREAM_HOST points at $DNSIP, this server is $MYIP"
else
  echo "  DNS $STREAM_HOST -> $DNSIP"
fi
df -h / | sed -n 2p; free -h | sed -n 2p

log "2/6 Client page: the login comes from /__env.js"
patch_index || die "could not edit $ST/www/index.html"
grep -q 'src="/__env.js"' "$ST/www/index.html" && echo "  index.html loads /__env.js"

log "3/6 Realm rule: stream accounts stay inside the slice"
docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' < "$ST/sql/ov_stream_accounts.sql" \
  || die "could not create acore_auth.ov_stream_accounts"
install -m 644 "$ST/lua/ov_slices.lua" "$WU/custom/lua_scripts/ov_slices.lua"
realm_tables "$ST/slices/$SLICE.json" "$SLICE_DIR" || die "could not make ov_slices_tiers.lua from slices/$SLICE.json"
soap "reload ale" >/dev/null || die "the world server refused \"reload ale\" (soap-cmd.sh \"reload ale\" to see why)"
sleep 2
probe=$(soap "ovstream clear WUSOAP" 2>&1 || true)
case "$probe" in
  *"ovstream ok"*) echo "  ov_slices.lua is live (console command answers)" ;;
  *) die "ov_slices.lua did not load (answer: ${probe:0:200}). Check: docker logs --tail 50 ov-ac-worldserver | grep -i lua" ;;
esac

log "4/6 Sign-in gate (wu-portal)"
[ -f "$WU/portal/wrath_portal.py.before-stream" ] || cp -p "$WU/portal/wrath_portal.py" "$WU/portal/wrath_portal.py.before-stream"
install -m 644 "$ST/wrath_portal.py" "$WU/portal/wrath_portal.py"
[ -f "$ST/links.py" ] && install -m 644 "$ST/links.py" "$WU/portal/links.py"   # the /r /h /q /m /u share links (optional)
install -d -m 755 "$WU/portal/slices"
install -m 644 "$ST/slices/$SLICE.json" "$WU/portal/slices/$SLICE.json"
[ -f "$WU/portal.env.before-stream" ] || cp -p "$WU/portal.env" "$WU/portal.env.before-stream"
kv_set "$WU/portal.env" WU_STREAM 1
kv_set "$WU/portal.env" STREAM_HOST "$STREAM_HOST"
kv_set "$WU/portal.env" STREAM_SLICES "$SLICE"
kv_set "$WU/portal.env" WU_OWNFILES 1
recreate_portal || die "wu-portal did not come back (docker logs wu-portal). The old page: cp $WU/portal/wrath_portal.py.before-stream $WU/portal/wrath_portal.py, then run this again or stream-down.sh"
echo "  wu-portal up, WU_STREAM=1"

log "5/6 Slice host (wu-play)"
docker image inspect debian:bookworm-slim >/dev/null 2>&1 || docker pull -q debian:bookworm-slim >/dev/null
docker rm -f wu-play >/dev/null 2>&1 || true
docker run -d --name wu-play --restart unless-stopped --memory 256m --cpus 1.5 \
  --network "$NET" --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 \
  -v "$ST/www:/www:ro" -v "$SLICE_DIR:/slice:ro" -v "$ST/bin/wenilla-host:/usr/local/bin/wenilla-host:ro" \
  debian:bookworm-slim /usr/local/bin/wenilla-host --www /www --patch /slice --only-listed \
  --bind 0.0.0.0:8090 --upstream "$UPSTREAM" >/dev/null
ok=""
for _ in $(seq 1 20); do
  if docker exec wu-portal python3 -c 'import json,urllib.request;json.load(urllib.request.urlopen("http://wu-play:8090/data/__index",timeout=10))' >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || { docker logs --tail 30 wu-play >&2; die "wu-play does not answer on wu-play:8090"; }
echo "  wu-play serves the slice ($(docker stats --no-stream --format '{{.MemUsage}}' wu-play))"

log "6/6 Caddy: https://$STREAM_HOST"
[ -f "$WU/Caddyfile.before-stream" ] || cp -p "$CF" "$WU/Caddyfile.before-stream"
cp -p "$CF" "$WU/Caddyfile.stream-backup"
caddy_strip
cat >> "$CF" <<EOF

$MARK_BEGIN: the browser client streams the "mini" slice here, behind the
# play.openvanilla.app sign-in (wu-portal). /__gate and /__env.js go to wu-portal; everything
# else needs its wu_play cookie (forward_auth /__auth) and goes to wu-play (page, /data, /ws).
# "Play with my own game files" uses the same site without /data (wu-portal's /__auth refuses it).
# wu-play's COOP/COEP headers pass through unchanged: the page must stay cross-origin isolated.
$STREAM_HOST {
	# compresses what wu-play doesn't already send compressed (the page, scripts, /__env.js)
	encode zstd gzip
	@gate path /__gate /__env.js
	handle @gate {
		reverse_proxy wu-portal:8091 {
			header_up X-Real-IP {remote_host}
			header_up X-Forwarded-For {remote_host}
		}
	}
	# the browser client's own files (no game data) skip the gate, so the realm list can warm them
	@client path /warm.html /boot.js /wenilla.js /wenilla_bg.wasm /wasi_stubs.js /platform.js /bridge.js /automate.js /boot-manifest.json /world-manifest.json /snippets/*
	handle @client {
		header Cross-Origin-Resource-Policy same-site
		reverse_proxy wu-play:8090
	}
	handle {
		forward_auth wu-portal:8091 {
			uri /__auth
			header_up X-Real-IP {remote_host}
			header_up X-Forwarded-For {remote_host}
		}
		# WebSockets (/ws/3724, /ws/8085) pass through and stay open as long as the game does.
		reverse_proxy wu-play:8090 {
			flush_interval -1
		}
	}
}
$MARK_END
EOF
if ! caddy_reload; then
  cat "$WU/Caddyfile.stream-backup" > "$CF"
  caddy_reload || true
  die "Caddy refused the new site block; the previous Caddyfile is back. Streaming parts are up but not reachable."
fi
sleep 3
code=$(curl -s -m 25 -o /dev/null -w '%{http_code}' "https://$STREAM_HOST/" || true)
echo "  https://$STREAM_HOST/ -> $code (302 = the sign-in gate is in front; 000 = DNS or certificate not ready yet)"
code=$(curl -s -m 25 -o /dev/null -w '%{http_code}' "https://${UPSTREAM}/wrath/play?mini=$SLICE" || true)
echo "  https://${UPSTREAM}/wrath/play?mini=$SLICE -> $code (200 = sign-in page for a signed-out visitor)"

echo
echo "Streaming is on. Players: sign in at https://${UPSTREAM}/wrath and press \"Play in your browser\"."
echo "Off switch: bash $ST/stream-switch.sh off   (on again: stream-switch.sh on)"
echo "Remove it all: bash $ST/stream-down.sh"
free -h | sed -n 2p
