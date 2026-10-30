#!/usr/bin/env bash
# Switch which installed slice the browser stream serves:   bash /srv/wrath/stream/slice-serve.sh <slice>
#   bash slice-serve.sh sampler   the Leyline Sample Hangout's slice (slices/sampler.json: no capitals)
#   bash slice-serve.sh mini      back to the full mini slice (the rollback)
# Only the serving part of stream-up.sh, for a slice already installed (slice-install.sh): the realm rule's
# tier list and Dungeon Finder ids from slices/<slice>.json ("reload ale"), portal.env STREAM_SLICES and
# WU_PLAY_SLICE (the play page's "Play now" and every ?mini=mini link then use it), wu-portal recreated, and
# wu-play recreated on the slice. Caddy, the client page and the portal's code are not touched. The other slice
# stays on disk, so switching back takes a minute. Streamed players reconnect after a short drop.
# Last line: SLICE SERVE OK, or an error (exit 1; the old slice keeps serving).
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
NAME="${1:-}"
[[ "$NAME" =~ ^[a-z0-9-]{1,32}$ ]] || die "usage: slice-serve.sh <slice name>"
D="$ST/slices"
[ -f "$D/$NAME.json" ] || die "$D/$NAME.json missing: install the slice first (Make mini slice.bat / Make sampler slice.bat)"
[ -d "$D/$NAME" ] && find "$D/$NAME" -maxdepth 2 -iname DBFilesClient | grep -c . >/dev/null \
  || die "$D/$NAME is not an exported slice (no DBFilesClient): install it first"
python3 -I "$ST/lua/tiers_lua.py" "$D/$NAME.json" > /dev/null || die "slices/$NAME.json: the tier list is broken; nothing changed"
[ -f "$WU/portal.env" ] || die "$WU/portal.env missing"
old=$(grep -E '^STREAM_SLICES=' "$WU/portal.env" | tail -1 | cut -d= -f2 || true)
echo "== serving slice $NAME (was: ${old:-mini}): $(du -sh "$D/$NAME" | cut -f1)"

log "1/3 Realm rule: the tier list of slices/$NAME.json"
realm_tables "$D/$NAME.json" "$D/$NAME" || die "could not make the realm tables from slices/$NAME.json; nothing changed"
soap "reload ale" >/dev/null 2>&1 && echo "  realm rule reloaded" || echo "  WARNING: reload ale failed: the realm keeps the old tier list until it restarts"

log "2/3 Sign-in gate"
install -d -m 755 "$WU/portal/slices"
install -m 644 "$D/$NAME.json" "$WU/portal/slices/$NAME.json"
kv_set "$WU/portal.env" STREAM_SLICES "$NAME"
kv_set "$WU/portal.env" WU_PLAY_SLICE "$NAME"
recreate_portal || die "wu-portal did not come back (docker logs wu-portal); portal.env says STREAM_SLICES=$NAME"
echo "  wu-portal up, STREAM_SLICES=$NAME"

log "3/3 Slice host (wu-play)"
docker rm -f wu-play >/dev/null 2>&1 || true
docker run -d --name wu-play --restart unless-stopped --memory 256m --cpus 1.5 \
  --network "$NET" --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 \
  -v "$ST/www:/www:ro" -v "$D/$NAME:/slice:ro" -v "$ST/bin/wenilla-host:/usr/local/bin/wenilla-host:ro" \
  debian:bookworm-slim /usr/local/bin/wenilla-host --www /www --patch /slice --only-listed \
  --bind 0.0.0.0:8090 --upstream "$UPSTREAM" >/dev/null
ok=""
for _ in $(seq 1 20); do
  if docker exec wu-portal python3 -c 'import json,urllib.request;json.load(urllib.request.urlopen("http://wu-play:8090/data/__index",timeout=10))' >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || { docker logs --tail 30 wu-play >&2 || true; die "wu-play does not answer on the $NAME slice: bash $ST/slice-serve.sh ${old:-mini} puts the old one back"; }
echo "  wu-play serves $NAME"
echo "SLICE SERVE OK"
