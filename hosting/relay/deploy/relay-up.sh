#!/usr/bin/env bash
# Beacons relay on the existing box (play.openvanilla.app): install or update wu-relay at
# relay.openvanilla.app. Run as root by "hosting/relay/Deploy relay.bat" (one SSH login: this folder
# arrives as a tarball over stdin):   bash relay-up.sh <extracted source dir>
# Safe to run again: it replaces only what it made, keeps relay.env (and its listing secret), state/
# (the realms' port book) and the rest of the Caddyfile.
#
#   1 checks     root, Docker, the site's Caddy, free memory, ports, DNS for relay.openvanilla.app
#   2 backup     /opt/wu-relay/backups/<time>/: compose.yml, relay.env, state/, the Caddyfile; image -> wu-relay:rollback
#   3 files      /opt/wu-relay/{compose.yml,.env,relay.env,state/}
#   4 image      docker build wu-relay:1 (the running relay keeps going if this fails)
#   5 start      docker compose up -d (memory capped: WU_RELAY_MEM, default 192m)
#   6 health     /healthz from the box AND from inside the Caddy container; else roll back to the backup
#   7 Caddy      a site block for relay.openvanilla.app (only once DNS points here; restored if Caddy refuses)
#
# Last line: "RELAY OK", or "RELAY WAITING FOR DNS" (installed and healthy, but players can't reach it until the
# owner adds the A record; exit 3), or an error (exit 1, everything put back as it was).
# Everything below can be moved for tests (hosting/tests/test_relay_deploy.py).
set -euo pipefail
SRC="${1:?usage: relay-up.sh <source dir>}"
DIR="${WU_RELAY_DIR:-/opt/wu-relay}"
HOST="${WU_RELAY_HOST:-relay.openvanilla.app}"
CADDY="${WU_CADDY_CONTAINER:-wenilla-realm-caddy-1}"
NET="${WU_CADDY_NET:-wenilla-realm_default}"
CF="${WU_CADDYFILE:-}"
PORT="${WU_RELAY_HTTP_PORT:-8099}"
MEM="${WU_RELAY_MEM:-192m}"
PORTAL_DIR="${WU_PORTAL_DIR:-/srv/wrath/portal}"
TRIES="${WU_HEALTH_TRIES:-15}"
PAUSE="${WU_HEALTH_PAUSE:-2}"
PMIN=40000 PMAX=40999
MARK_BEGIN="# >>> WrathUnleashed Beacons relay (relay-up.sh)"
MARK_END="# <<< WrathUnleashed Beacons relay"
COMPOSE=(docker compose -p wu-relay --project-directory "$DIR" -f "$DIR/compose.yml")
log() { printf '\n== %s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf '\nRELAY FAILED: %s\n' "$*" >&2; exit 1; }
kv_set() { local f=$1 k=$2 v=$3; touch "$f"; if grep -q "^$k=" "$f"; then sed -i "s#^$k=.*#$k=$v#" "$f"; else echo "$k=$v" >> "$f"; fi; }
resolve() {  # resolve A|AAAA name -> addresses, one per line (nothing when there is no record)
  local fake="WU_FAKE_DNS_$1"
  if [ -n "${!fake+x}" ]; then [ "${!fake}" = none ] || tr ',' '\n' <<<"${!fake}"; return 0; fi
  python3 -I - "$1" "$2" <<'PY' 2>/dev/null || true
import socket, sys
fam = socket.AF_INET if sys.argv[1] == "A" else socket.AF_INET6
try:
    seen = []
    for info in socket.getaddrinfo(sys.argv[2], None, fam, socket.SOCK_STREAM):
        a = info[4][0]
        if a not in seen and not a.startswith("::ffff:"):
            seen.append(a); print(a)
except OSError:
    pass
PY
}
listening() { { ss -ltnH 2>/dev/null || true; } | awk '{print $4}' | sed 's/.*://' ; }

# CRLF from a Windows checkout would break the shell and env files.
find "$SRC" -type f \( -name '*.sh' -o -name '*.yml' -o -name '*.env*' -o -name '*.py' -o -name 'Dockerfile' -o -name 'Caddyfile' \) \
  -exec sed -i 's/\r$//' {} +

log "1/7 Checks"
[ "${WU_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root"
command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose (v2) not found"
for f in relay/Dockerfile relay/wurelay/relay.py relay/wurelay/listing.py kit/tools/wunet/mux.py relay/deploy/compose.box.yml relay/deploy/relay.env.example; do
  [ -f "$SRC/$f" ] || die "$f is missing from the upload"
done
docker ps --format '{{.Names}}' | grep -x "$CADDY" >/dev/null || die "the site's Caddy ($CADDY) is not running: the relay needs it for https/wss. Nothing was changed."
if [ -z "$CF" ]; then
  CF=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$CADDY" 2>/dev/null || true)
  [ -n "$CF" ] || CF=/opt/openvanilla-classicplus/Caddyfile
fi
[ -f "$CF" ] || die "the Caddyfile ($CF) was not found. Nothing was changed."
note "Caddy: $CADDY, Caddyfile $CF"
GW=$(docker network inspect -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' "$NET" 2>/dev/null || true)
SUBNET=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$NET" 2>/dev/null || true)
[ -n "$SUBNET" ] || die "Docker network $NET not found (is the website stack running?). Nothing was changed."
if [ -z "$GW" ]; then   # some Docker versions leave Gateway out: the bridge takes the subnet's first address
  GW=$(python3 -I -c 'import ipaddress,sys;print(next(ipaddress.ip_network(sys.argv[1]).hosts()))' "$SUBNET")
fi
BIND="$GW:$PORT"
note "the relay's web side: $BIND (only Caddy and wu-portal on $NET reach it), trusted proxy range $SUBNET"
AVAIL=$(free -m | awk '/^Mem:/{print $7}')
note "memory available: ${AVAIL:-?} MB, relay capped at $MEM"
[ -z "$AVAIL" ] || [ "$AVAIL" -ge 300 ] || die "only ${AVAIL} MB of memory available; the relay needs ~200 MB. Nothing was changed."
RUNNING=0
if docker ps --format '{{.Names}}' | grep -x wu-relay >/dev/null; then RUNNING=1; fi
LISTEN=$(listening)
SHARED=3724
if grep -qx 3724 <<<"$LISTEN"; then
  if [ "$RUNNING" = 1 ] && grep -q '^RELAY_SHARED_AUTH_PORT=3724' "$DIR/relay.env" 2>/dev/null; then :; else
    SHARED=0
    note "port 3724 is the realm's own login server here: the shared port is off, players use $HOST:<realm's port>"
  fi
fi
if [ "$RUNNING" = 0 ]; then
  if grep -qx "$PORT" <<<"$LISTEN"; then die "port $PORT is already in use on this box (set WU_RELAY_HTTP_PORT). Nothing was changed."; fi
  busy=$(awk -v a=$PMIN -v b=$PMAX '$1>=a && $1<=b' <<<"$LISTEN" | head -3 | tr '\n' ' ')
  [ -z "$busy" ] || die "ports $busy in the relay's range $PMIN-$PMAX are already in use. Nothing was changed."
fi
# DNS: an A record to this box, no AAAA (the stock 3.3.5a client is IPv4 only).
MYIP="${WU_PUBLIC_IP:-$(curl -4 -s -m 8 https://api.ipify.org 2>/dev/null || true)}"
[ -n "$MYIP" ] || MYIP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
A=$(resolve A "$HOST" | tr '\n' ' ' | sed 's/ $//')
AAAA=$(resolve AAAA "$HOST" | tr '\n' ' ' | sed 's/ $//')
DNS=ok
if [ -z "$A" ]; then
  DNS=missing; note "DNS: $HOST has NO A record yet"
elif [ -n "$MYIP" ] && ! grep -qw -- "$MYIP" <<<"$A"; then
  DNS=wrong; note "DNS: $HOST points at $A, but this box is $MYIP"
else
  note "DNS: $HOST -> $A"
fi
[ -z "$AAAA" ] || note "WARNING: $HOST also has an AAAA record ($AAAA). Remove it: stock 3.3.5a clients are IPv4 only, and a browser that knocks over IPv6 opens the wrong address."

log "2/7 Backup"
mkdir -p "$DIR/backups"
BK="$DIR/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
for f in compose.yml .env relay.env; do if [ -f "$DIR/$f" ]; then cp -p "$DIR/$f" "$BK/$f"; fi; done
if [ -d "$DIR/state" ]; then tar -czf "$BK/state.tgz" -C "$DIR" state; fi
cp -p "$CF" "$BK/Caddyfile"
HAD_IMAGE=0
if docker image inspect wu-relay:1 >/dev/null 2>&1; then docker tag wu-relay:1 wu-relay:rollback; HAD_IMAGE=1; fi
note "backup: $BK (previous image kept as wu-relay:rollback: $HAD_IMAGE)"
ls -1d "$DIR"/backups/*/ 2>/dev/null | sort | head -n -5 | xargs -r rm -rf   # keep the last five

rollback() {  # put the relay back as it was before this run
  echo "  rolling back to $BK" >&2
  for f in compose.yml .env relay.env; do
    if [ -f "$BK/$f" ]; then cp -p "$BK/$f" "$DIR/$f"; else rm -f "$DIR/$f"; fi
  done
  if [ "$HAD_IMAGE" = 1 ]; then
    docker tag wu-relay:rollback wu-relay:1
    if [ -f "$BK/compose.yml" ]; then "${COMPOSE[@]}" up -d --remove-orphans >/dev/null 2>&1 || true; fi
  else
    if [ ! -f "$DIR/compose.yml" ]; then cp "$SRC/relay/deploy/compose.box.yml" "$DIR/compose.yml"; fi
    "${COMPOSE[@]}" down >/dev/null 2>&1 || true
    if [ ! -f "$BK/compose.yml" ]; then rm -f "$DIR/compose.yml"; fi
  fi
}
caddy_reload() { docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; }
caddy_strip() {  # remove our block, in place (the Caddyfile is bind-mounted: keep its inode)
  python3 -I - "$CF" "$MARK_BEGIN" "$MARK_END" <<'PY'
import sys
p, b, e = sys.argv[1:4]
s = open(p).read()
while b in s:
    i = s.index(b)
    j = s.find(e, i)
    if j < 0:
        sys.exit("start marker without end marker in the Caddyfile")
    j = s.find("\n", j)
    s = s[:i].rstrip("\n") + "\n" + (s[j + 1:] if j >= 0 else "")
with open(p, "r+") as f:
    f.seek(0); f.write(s); f.truncate()
PY
}

log "3/7 Files ($DIR)"
mkdir -p "$DIR/state"
chown 10002:10002 "$DIR/state" 2>/dev/null || true   # the image's "relay" user
install -m 644 "$SRC/relay/deploy/compose.box.yml" "$DIR/compose.yml"
kv_set "$DIR/.env" WU_RELAY_MEM "$MEM"
if [ ! -f "$DIR/relay.env" ]; then
  ( umask 077
    sed "s/^RELAY_LISTING_SITE_SECRET=.*/RELAY_LISTING_SITE_SECRET=$(openssl rand -hex 24)/" \
      "$SRC/relay/deploy/relay.env.example" > "$DIR/relay.env" )
  note "wrote $DIR/relay.env with a new listing site secret (not shown; the website's claim service needs it later)"
fi
chmod 600 "$DIR/relay.env"
kv_set "$DIR/relay.env" RELAY_NAME "$HOST"
kv_set "$DIR/relay.env" RELAY_HTTP_BIND "$BIND"
kv_set "$DIR/relay.env" RELAY_TRUSTED_PROXIES "127.0.0.1/32,$SUBNET"
kv_set "$DIR/relay.env" RELAY_SHARED_AUTH_PORT "$SHARED"
kv_set "$DIR/relay.env" RELAY_PORT_MIN "$PMIN"
kv_set "$DIR/relay.env" RELAY_PORT_MAX "$PMAX"
note "relay.env: RELAY_HTTP_BIND=$BIND RELAY_SHARED_AUTH_PORT=$SHARED RELAY_PORT_MIN/MAX=$PMIN-$PMAX"

log "4/7 Image wu-relay:1"
if ! docker build -q -f "$SRC/relay/Dockerfile" -t wu-relay:1 "$SRC" >/dev/null; then
  rollback; die "building the relay image failed (see above); the relay is as it was."
fi
note "built"

log "5/7 Start"
if ! "${COMPOSE[@]}" up -d --remove-orphans; then
  rollback; die "docker compose up failed; rolled back."
fi
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep '^Status: active' >/dev/null; then
  ufw allow $PMIN:$PMAX/tcp >/dev/null
  [ "$SHARED" = 0 ] || ufw allow 3724/tcp >/dev/null
  ufw allow from "$SUBNET" to "$GW" port "$PORT" proto tcp >/dev/null
  note "ufw: $PMIN-$PMAX open, $SUBNET -> $BIND allowed"
fi
note "if this box also has a Hetzner Cloud Firewall, allow TCP $PMIN-$PMAX there too (it can't be seen from here)"

log "6/7 Health check"
ok=""
for _ in $(seq 1 "$TRIES"); do
  if curl -fsS -m 3 "http://$BIND/healthz" >/dev/null 2>&1; then ok=1; break; fi
  sleep "$PAUSE"
done
if [ -z "$ok" ]; then
  docker logs --tail 30 wu-relay >&2 2>&1 || true
  rollback; die "the relay did not answer http://$BIND/healthz; rolled back to the previous version."
fi
note "healthz ok from the box"
if ! docker exec "$CADDY" wget -q -O- -T 3 "http://$BIND/healthz" >/dev/null 2>&1; then
  rollback; die "Caddy ($CADDY) cannot reach the relay at $BIND (a firewall between Docker and the host?); rolled back."
fi
note "healthz ok from inside Caddy"
lim=$(docker inspect -f '{{.HostConfig.Memory}}' wu-relay 2>/dev/null || echo 0)
[ "${lim:-0}" -gt 0 ] || { rollback; die "the relay container has no memory limit; rolled back."; }
note "memory limit $(( lim / 1048576 )) MB, in use $(docker stats --no-stream --format '{{.MemUsage}}' wu-relay 2>/dev/null || echo '?')"
curl -fsS -m 3 "http://$BIND/api/listing/realms.json" | python3 -I -c 'import json,sys;d=json.load(sys.stdin);print("  listing ok:", len(d["realms"]), "community realm(s)")' \
  || { rollback; die "the listing API (/api/listing/realms.json) did not answer; rolled back."; }
# The play page's realm list (stream/wrath_portal.py, /wrath/realms) reads the listing straight from here,
# not through DNS: wu-portal is on the same Docker network as Caddy and reads this file at each refresh.
if [ -d "$PORTAL_DIR" ]; then
  echo "http://$BIND/api/listing/realms.json" > "$PORTAL_DIR/relay-listing.url"
  chmod 644 "$PORTAL_DIR/relay-listing.url"
  note "$PORTAL_DIR/relay-listing.url: the play page's realm list reads the relay here"
fi

log "7/7 Caddy: https://$HOST"
if [ "$DNS" != ok ]; then
  note "skipped until DNS points here (so Let's Encrypt is not asked for a certificate it can't get)"
  IP_SHOW="${MYIP:-the public IPv4 address of play.openvanilla.app}"
  WRONG=""
  if [ "$DNS" = wrong ]; then WRONG=" Right now $HOST points at $A: change it to $IP_SHOW."; fi
  cat <<EOF

=====================================================================
 ACTION NEEDED (owner): add this DNS record, then run this step again
   Type: A     Name: relay     (relay.openvanilla.app)
   Value: $IP_SHOW     TTL: 300 (or the default)
   Do NOT add an AAAA record for relay.
$WRONG
 The relay itself is installed and healthy; only the public name is missing.
=====================================================================
RELAY WAITING FOR DNS
EOF
  exit 3
fi
cp -p "$CF" "$DIR/Caddyfile.before-relay-run"
caddy_strip || { cat "$BK/Caddyfile" > "$CF"; die "could not edit $CF; it is unchanged."; }
cat >> "$CF" <<EOF

$MARK_BEGIN: home-hosted Wrath realms (Beacons). https and wss
# (/agent, /r/<id>/ws/<port>, /join/<id>, /api/...) go to wu-relay on the bridge gateway; the raw game
# ports (40000-40999) do not pass through Caddy. No access log: it would hold player IPs.
$HOST {
	@metrics path /metrics
	respond @metrics 403
	reverse_proxy $BIND {
		header_up X-Forwarded-For {remote_host}
		flush_interval -1
	}
	header -Server
}
$MARK_END
EOF
if ! caddy_reload; then
  cat "$BK/Caddyfile" > "$CF"
  caddy_reload || true
  rollback
  die "Caddy refused the relay's site block; the previous Caddyfile is back and the relay is rolled back."
fi
note "site block loaded"
code=000
for _ in 1 2 3 4 5 6; do
  code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://$HOST/healthz" || true)
  [ "$code" = 200 ] && break
  sleep 5
done
if [ "$code" = 200 ]; then
  note "https://$HOST/healthz -> 200"
else
  note "https://$HOST/healthz -> $code (the certificate can take a minute; Caddy keeps trying by itself)"
fi
echo
echo "Relay: https://$HOST  (agents: wss://$HOST/agent, listing: https://$HOST/api/listing/realms.json)"
echo "Logs: docker logs -f wu-relay    Undo: restore $BK (compose.yml, relay.env, Caddyfile) or run an earlier version"
free -h | sed -n 2p
echo "RELAY OK"
