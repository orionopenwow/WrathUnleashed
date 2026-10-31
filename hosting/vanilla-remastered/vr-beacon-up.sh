#!/usr/bin/env bash
# Vanilla Remastered on Leyline: the old 1.12 realm (CMaNGOS Classic, client build 5875) listed as an OFFICIAL
# Beacon through the relay, the same way as Wrath Unleashed (hosting/hangout/hangout-up.sh): we host it for now,
# a community host takes it over through the Leyline P2P network later (docs/VANILLA-REMASTERED.md).
# Run as root by "Put Vanilla Remastered on Leyline.bat" (one SSH login: this folder and kit/tools arrive as a
# tarball over stdin). Needs the ov112-on step first (vr-realmd and vr-mangosd running on the vr-112 network).
#
#   bash vr-beacon-up.sh <extracted source dir>            install or update (safe to run again)
#   bash vr-beacon-up.sh <extracted source dir> --remove   take it off Leyline (the key is kept)
#
# What it runs: one small container.
#   wu-vr-agent   the host kit's own agent (wuhost/agent.py; read-only, no capabilities, 64 MB), on the site's network
#                 (the relay's web side) and on vr-112 (the 1.12 realm's own network). It keeps one tunnel to the relay
#                 and signs the listing heartbeat. Players reach the 1.12 login server (vr-realmd:3724) and world
#                 server (vr-mangosd:8085) only through it.
# Config: `setup.py official` (public, signup off, its realm list, accounts and GM rights left alone), then the
# listing record says what this realm really is: core cmangos, client build 5875, ruleset custom.
# The one database change: the 1.12 realm list row's address and port become the relay's (the relay's world port
# for this realm), so a stock 1.12.1 client that logged in through the relay comes back through it for the world
# server. The row is backed up first and put back on --remove or on a failure. No account is made or changed.
#
#   1 checks   root, Docker, the relay, vr-realmd + vr-mangosd running, the networks, the realm list row, the login
#              server's wrong-password lock (every relay player arrives from the agent's address)
#   2 backup   $DIR/backups/<time>/: state.tgz (host.json + the key), the realm list row, the id files;
#              image -> wu-vr-tools:rollback
#   3 image    docker build wu-vr-tools:1 from kit/tools (the running agent keeps going if this fails)
#   4 config   setup.py official + the record's core/build/ruleset/tags
#   5 start    the agent, on both networks
#   6 health   the tunnel is up, the relay sees the realm online, the world server answers through the agent, a 1.12.1
#              logon through the relay's own port answers, the listing has it; then the realm list address and the id
#              files (vr-realm.id) for the website and the in-game list. Else: roll back.
#
# Last line: "VR BEACON OK" (or "VR BEACON REMOVED"), or an error (exit 1, everything put back as it was).
set -euo pipefail
SRC="${1:?usage: vr-beacon-up.sh <source dir> [--remove]}"
MODE="${2:-up}"
DIR="${VR_BEACON_DIR:-/srv/wrath/vr-beacon}"
RELAY_DIR="${WU_RELAY_DIR:-/opt/wu-relay}"
PORTAL_DIR="${WU_PORTAL_DIR:-/srv/wrath/portal}"
WRATH_DIR="${WU_WRATH_DIR:-/srv/wrath}"
SITE_NET="${VR_SITE_NET:-wenilla-realm_default}"
NET="${VR_NET:-vr-112}"
DB="${VR_DB:-wenilla-realm-mariadb-1}"
AUTH_DB="${VR_AUTH_DB:-classicrealmd}"
LOGON_C=vr-realmd
WORLD_C=vr-mangosd
AUTH="$LOGON_C:3724"
WORLD="$WORLD_C:8085"
NAME="${VR_NAME:-Vanilla Remastered}"
TAGLINE="${VR_TAGLINE:-The original world, remastered: Classic+ at its own pace. Official, hosted by Leyline for now.}"
SUMMARY="${VR_SUMMARY:-The Open Vanilla realm is back as Vanilla Remastered: the original world to level 60 with Classic+ changes, your old characters and logins. Hosted by the Leyline team for now, until a community host takes it over through the Leyline network. Play it with your own 1.12.1 client.}"
TAGS="${VR_TAGS:-custom}"
TRIES="${WU_HEALTH_TRIES:-30}"
PAUSE="${WU_HEALTH_PAUSE:-2}"
C=wu-vr-agent
IMG=wu-vr-tools:1
UIDGID=10001:10001        # the tools image's "wu" user
BRAND_RE='world *of *warcraft|(^|[^a-z])wow([^a-z]|$)|warcraft|lich *king|blizzard'
log() { printf '\n== %s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf '\nVR BEACON FAILED: %s\n' "$*" >&2; exit 1; }
envget() { sed -n "s/^$2=\([^ #]*\).*/\1/p" "$1" 2>/dev/null | tail -1; }
jget() {  # jget FILE KEY: a top-level value of a small JSON file, or nothing
  python3 -I - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2])
except (OSError, ValueError, AttributeError):
    sys.exit(0)
print("" if v is None else (str(v).lower() if isinstance(v, bool) else v))
PY
}
running() { docker ps --format '{{.Names}}' | grep -x "$1" >/dev/null; }
sql() {  # the 1.12 login database, as root inside its own container (the password never leaves it)
  docker exec -i "$DB" sh -c 'p="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"; c=$(command -v mariadb || command -v mysql); MYSQL_PWD="$p" exec "$c" -uroot -N -B "$0"' "$AUTH_DB"
}

find "$SRC" -type f \( -name '*.sh' -o -name '*.py' -o -name '*.txt' -o -name 'Dockerfile' -o -name '*.env' \) \
  -exec sed -i 's/\r$//' {} +

log "1/6 Checks"
[ "${WU_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root"
command -v docker >/dev/null || die "docker not found"
for f in kit/tools/Dockerfile kit/tools/wuhost/agent.py kit/tools/wuhost/setup.py kit/tools/wunet/keys.py \
         vanilla-remastered/rules.txt vanilla-remastered/probe112.py; do
  [ -f "$SRC/$f" ] || die "$f is missing from the upload"
done

remove_ids() { rm -f "$PORTAL_DIR/vr-realm.id" "$WRATH_DIR/vr-realm.id"; }
restore_row() {  # restore_row FILE: the realm list row's address and port as they were (id<TAB>name<TAB>address<TAB>port)
  [ -s "$1" ] || return 0
  local id name addr port
  IFS=$'\t' read -r id name addr port < "$1" || return 1
  [[ "$id" =~ ^[0-9]+$ ]] && [[ "$port" =~ ^[0-9]+$ ]] && [[ "$addr" =~ ^[A-Za-z0-9.:-]+$ ]] || { note "!! the saved realm list row in $1 looks wrong; left as is"; return 1; }
  echo "UPDATE realmlist SET address = '$addr', port = $port WHERE id = $id;" | sql >/dev/null \
    && note "realm list row $id: address back to $addr:$port" || { note "!! could not put the realm list row back (see $1)"; return 1; }
}
refresh_lists() { [ -f "$WRATH_DIR/leyline-fetch.py" ] && { python3 -I "$WRATH_DIR/leyline-fetch.py" >/dev/null 2>&1 || true; }; return 0; }

if [ "$MODE" = "--remove" ]; then
  log "Remove: Vanilla Remastered leaves Leyline"
  docker rm -f "$C" >/dev/null 2>&1 || true
  remove_ids
  last=$(ls -1d "$DIR"/backups/*/ 2>/dev/null | sort | while read -r d; do [ -s "$d/realmlist.row" ] && echo "$d"; done | head -1 || true)
  if [ -n "$last" ] && running "$DB"; then restore_row "$last/realmlist.row" || true; fi
  note "the agent is gone, the id files are gone; the key stays in $DIR/state (running vr-beacon again brings the same realm back)"
  note "the 1.12 game servers keep running (the ov112-realm-off step stops them)"
  refresh_lists
  echo "VR BEACON REMOVED"
  exit 0
fi

running wu-relay || die "the relay (wu-relay) is not running: run the relay step first. Nothing was changed."
[ -f "$RELAY_DIR/relay.env" ] || die "$RELAY_DIR/relay.env is missing (the relay step writes it). Nothing was changed."
BIND="$(envget "$RELAY_DIR/relay.env" RELAY_HTTP_BIND)"
RELAY_NAME="$(envget "$RELAY_DIR/relay.env" RELAY_NAME)"
RELAY_NAME="${RELAY_NAME:-relay.openvanilla.app}"
[[ "$BIND" =~ ^[0-9.]+:[0-9]+$ ]] || die "RELAY_HTTP_BIND in $RELAY_DIR/relay.env is '$BIND', not address:port. Nothing was changed."
for c in "$LOGON_C" "$WORLD_C" "$DB"; do
  running "$c" || die "$c is not running: run the ov112-on step first (it starts the 1.12 realm). Nothing was changed."
done
for n in "$SITE_NET" "$NET"; do
  docker network inspect "$n" >/dev/null 2>&1 || die "Docker network $n not found (the ov112-on step makes $NET). Nothing was changed."
done
curl -fsS -m 3 "http://$BIND/healthz" >/dev/null 2>&1 || die "the relay does not answer on http://$BIND/healthz. Nothing was changed."
rows=$(echo "SELECT id, name, address, port FROM realmlist ORDER BY id;" | sql) || die "could not read the 1.12 realm list ($AUTH_DB.realmlist). Nothing was changed."
nrows=$(printf '%s\n' "$rows" | grep -c . || true)
if [ -n "${VR_REALM_ID:-}" ]; then
  ROW=$(printf '%s\n' "$rows" | awk -F'\t' -v id="$VR_REALM_ID" '$1 == id')
else
  [ "$nrows" = 1 ] || die "the 1.12 realm list has $nrows rows; say which one is the realm with VR_REALM_ID=<id>. Nothing was changed."
  ROW=$rows
fi
[ -n "$ROW" ] || die "no realm list row ${VR_REALM_ID:-}. Nothing was changed."
RL_ID=$(printf '%s' "$ROW" | cut -f1); RL_NAME=$(printf '%s' "$ROW" | cut -f2)
note "realm list row $RL_ID: '$RL_NAME' at $(printf '%s' "$ROW" | cut -f3 | tr -d '\n'):$(printf '%s' "$ROW" | cut -f4)"
if printf '%s' "$RL_NAME" | tr 'A-Z' 'a-z' | grep -E "$BRAND_RE" >/dev/null; then
  note "WARNING: the in-game realm name '$RL_NAME' carries a game or publisher brand word: players see it in the 1.12 client's realm list (see the runbook's open questions)"
fi
# Every relay player reaches the login server from the agent's address: a per-IP wrong-password lock would lock
# everyone out at once (the hangout runs a second login server for this; the kit's 1.12 profile sets
# WrongPass.MaxCount = 0). The relay counts wrong passwords per player IP itself.
wp=$(docker exec "$LOGON_C" sh -c 'for f in $(find / -xdev -name realmd.conf 2>/dev/null | head -5); do grep -hiE "^[[:space:]]*WrongPass\.MaxCount[[:space:]]*=" "$f"; done' 2>/dev/null \
     | tail -1 | sed 's/.*=[[:space:]]*//; s/[^0-9].*//' || true)
case "$wp" in
  ""|0) note "login server wrong-password lock: ${wp:-not set, the core default is off}" ;;
  *) [ "${VR_ALLOW_WRONGPASS_LOCK:-0}" = 1 ] || die "the 1.12 login server locks an IP after $wp wrong passwords (WrongPass.MaxCount in its realmd.conf): through the relay every player shares one address, so one player's typos would lock everyone out. Set it to 0 in that file (then the ov112-on step), or accept it with VR_ALLOW_WRONGPASS_LOCK=1. Nothing was changed." ;;
esac
note "relay $RELAY_NAME, web side $BIND; the 1.12 realm: $AUTH (login) and $WORLD (world) on $NET"

log "2/6 Backup"
mkdir -p "$DIR/state" "$DIR/backups"
chmod 711 "$DIR"
chmod 700 "$DIR/backups"
BK="$DIR/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
tar -czf "$BK/state.tgz" -C "$DIR" state
printf '%s\n' "$ROW" > "$BK/realmlist.row"
for f in "$PORTAL_DIR/vr-realm.id" "$WRATH_DIR/vr-realm.id"; do
  [ -f "$f" ] && cp -p "$f" "$BK/$(basename "$(dirname "$f")")-vr-realm.id"
done
HAD_IMAGE=0
if docker image inspect "$IMG" >/dev/null 2>&1; then docker tag "$IMG" wu-vr-tools:rollback; HAD_IMAGE=1; fi
WAS_RUNNING=0
running "$C" && WAS_RUNNING=1
note "backup: $BK (realm list row, state, image kept as wu-vr-tools:rollback: $HAD_IMAGE, agent was running: $WAS_RUNNING)"

start_agent() {  # start_agent IMAGE
  docker rm -f "$C" >/dev/null 2>&1 || true
  docker run -d --name "$C" --restart unless-stopped --network "$SITE_NET" --memory 64m --memory-swap 64m \
    --cpus 0.5 --pids-limit 64 --read-only --tmpfs /tmp:size=8m --cap-drop ALL --security-opt no-new-privileges \
    --user "$UIDGID" -v "$DIR/state:/state" -e LOG_LEVEL=INFO --log-opt max-size=10m --log-opt max-file=3 \
    "$1" python -m wuhost.agent --state /state >/dev/null || return 1
  docker network connect "$NET" "$C" >/dev/null 2>&1 || return 1
}
ROW_CHANGED=0
rollback() {
  echo "  rolling back to $BK" >&2
  docker rm -f "$C" >/dev/null 2>&1 || true
  [ "$ROW_CHANGED" = 1 ] && { restore_row "$BK/realmlist.row" || true; }
  rm -rf "$DIR/state.rollback"; mkdir -p "$DIR/state.rollback"
  tar -xzf "$BK/state.tgz" -C "$DIR/state.rollback" && rm -rf "$DIR/state" && mv "$DIR/state.rollback/state" "$DIR/state"
  rm -rf "$DIR/state.rollback"
  remove_ids
  for f in "$BK"/*-vr-realm.id; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in
      "$(basename "$PORTAL_DIR")-vr-realm.id") cp -p "$f" "$PORTAL_DIR/vr-realm.id" ;;
      *) cp -p "$f" "$WRATH_DIR/vr-realm.id" ;;
    esac
  done
  if [ "$HAD_IMAGE" = 1 ]; then docker tag wu-vr-tools:rollback "$IMG"; fi
  if [ "$WAS_RUNNING" = 1 ] && [ "$HAD_IMAGE" = 1 ]; then start_agent "$IMG" || true; fi
}

log "3/6 Image $IMG"
docker build -q -t "$IMG" "$SRC/kit/tools" >/dev/null || die "building the agent image failed; nothing changed (the running agent, if any, keeps going)."
note "built"

log "4/6 Config ($DIR/state/host.json)"
install -m 644 "$SRC/vanilla-remastered/rules.txt" "$DIR/rules.txt"
chown -R "$UIDGID" "$DIR/state" "$DIR/rules.txt" 2>/dev/null || true
chmod 700 "$DIR/state"
out=$(docker run --rm --user "$UIDGID" --network none -v "$DIR:/kit" -e WU_KIT=/kit "$IMG" python -m wuhost.setup official \
  --name "$NAME" --relay "$RELAY_NAME" --relay-url "ws://$BIND/agent" --listing-url "http://$BIND/api/listing/heartbeat" \
  --auth-service "$AUTH" --world-service "$WORLD" \
  --tagline "$TAGLINE" --summary "$SUMMARY" --rules-file /kit/rules.txt 2>&1) || { echo "$out" >&2; rollback; die "writing the config failed; rolled back."; }
RID=$(python3 -I -c 'import json,sys;print(json.loads(sys.stdin.read().strip().splitlines()[-1])["realm_id"])' <<<"$out" 2>/dev/null || true)
[[ "$RID" =~ ^[a-z2-7]{16}$ ]] || { echo "$out" >&2; rollback; die "the config did not give a realm id; rolled back."; }
# `setup.py official` writes Wrath Unleashed's shape (AzerothCore, 3.3.5a): this realm is CMaNGOS Classic for the
# 1.12.1 client. The record is what the listing shows (the agent sends it as is); "profile" is what its status says.
out2=$(docker run --rm --user "$UIDGID" --network none -v "$DIR:/kit" -e VR_TAGS="$TAGS" --entrypoint python "$IMG" -I -c '
import json, os
p = "/kit/state/host.json"
cfg = json.load(open(p))
tags = [t for t in os.environ.get("VR_TAGS", "").split(",") if t in ("blizzlike", "boosted", "custom", "pvp", "rp", "hangout")]
cfg["profile"] = "cmangos-1.12.1"
cfg["record"].update(core="cmangos", build=5875, ruleset="custom", tags=tags, max_players=None, direct=False)
tmp = p + ".tmp"
with open(tmp, "w") as f:
    json.dump(cfg, f, indent=1)
os.chmod(tmp, 0o600)
os.replace(tmp, p)
print(json.dumps({k: cfg["record"].get(k) for k in ("name", "core", "build", "ruleset", "tags")}))
' 2>&1) || { echo "$out2" >&2; rollback; die "setting the listing's core and client build failed; rolled back."; }
note "realm id $RID (key made on this box: $DIR/state/realm.key, never copied anywhere); record $out2"
[ "$(stat -c %a "$DIR/state/realm.key" 2>/dev/null || echo 600)" = 600 ] || { rollback; die "state/realm.key is not 0600; rolled back."; }

log "5/6 Start $C"
rm -f "$DIR/state/relay-state.json"
start_agent "$IMG" || { rollback; die "the agent container did not start; rolled back."; }
note "on $SITE_NET + $NET, 64 MB, read-only"

log "6/6 Health check"
ok=""
for _ in $(seq 1 "$TRIES"); do
  if [ "$(jget "$DIR/state/relay-state.json" connected)" = true ]; then ok=1; break; fi
  sleep "$PAUSE"
done
if [ -z "$ok" ]; then
  docker logs --tail 30 "$C" >&2 2>&1 || true
  why=$(jget "$DIR/state/relay-state.json" last_error)
  rollback; die "the agent did not connect to the relay${why:+ ($why)}; rolled back."
fi
note "tunnel up"
online=$(curl -fsS -m 3 "http://$BIND/api/realms/$RID" 2>/dev/null | python3 -I -c 'import json,sys;print(json.load(sys.stdin).get("online"))' 2>/dev/null || true)
[ "$online" = True ] || { rollback; die "the relay does not see realm $RID online; rolled back."; }
st=$(curl -fsS -m 10 "http://$BIND/r/$RID/status.json" 2>/dev/null | python3 -I -c 'import json,sys;d=json.load(sys.stdin);print(d.get("online"), d.get("build"))' 2>/dev/null || true)
case "$st" in True*) note "the world server answers through the relay (status: online, client ${st#True })" ;;
  *) rollback; die "the 1.12 world server does not answer through the agent (status: ${st:-none}); rolled back." ;; esac

# The realm list address: the relay's address and this realm's world port, so stock clients come back through it.
RADDR=$(jget "$DIR/state/relay-state.json" address)
WPORT=$(jget "$DIR/state/relay-state.json" world_port)
APORT=$(jget "$DIR/state/relay-state.json" auth_port)
[[ "$WPORT" =~ ^[0-9]+$ ]] && [[ "$APORT" =~ ^[0-9]+$ ]] && [ -n "$RADDR" ] || { rollback; die "the relay gave no address and ports (relay-state.json); rolled back."; }
if [[ "$RADDR" =~ ^[0-9.]+$ ]]; then IP4=$RADDR; else IP4=$(getent ahostsv4 "$RADDR" 2>/dev/null | awk 'NR==1 {print $1}'); fi
[[ "${IP4:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { rollback; die "could not find the IPv4 address of $RADDR; rolled back."; }
OLD_AT="$(printf '%s' "$ROW" | cut -f3):$(printf '%s' "$ROW" | cut -f4)"
if [ "$OLD_AT" != "$IP4:$WPORT" ]; then
  ROW_CHANGED=1
  echo "UPDATE realmlist SET address = '$IP4', port = $WPORT WHERE id = $RL_ID;" | sql >/dev/null \
    || { rollback; die "could not point the 1.12 realm list at the relay; rolled back."; }
  note "realm list row $RL_ID: address $IP4:$WPORT (the relay's world port for this realm; was $OLD_AT)"
else
  note "realm list row $RL_ID already points at the relay ($IP4:$WPORT)"
fi

# A 1.12.1 logon through the relay's own port for this realm, from this box (the way a stock client comes in).
PY_IMG=""
for i in "$IMG" python:3.12-alpine; do docker image inspect "$i" >/dev/null 2>&1 && { PY_IMG=$i; break; }; done
lo=$(docker run --rm --network host --memory 64m --cap-drop ALL --security-opt no-new-privileges --read-only \
     -v "$SRC/kit/tools/wunet:/p/wunet:ro" -v "$SRC/vanilla-remastered/probe112.py:/p/probe112.py:ro" --entrypoint python3 \
     "$PY_IMG" -I /p/probe112.py logon "$IP4" "$APORT" 2>&1) || { rollback; die "a 1.12.1 logon through the relay ($IP4:$APORT) got no answer (${lo:-none}); rolled back."; }
note "logon through the relay ($RELAY_NAME:$APORT): $lo"

listed=""
for _ in $(seq 1 "$TRIES"); do
  if curl -fsS -m 3 "http://$BIND/api/listing/realms.json" 2>/dev/null | grep "\"realmId\": *\"$RID\"" >/dev/null; then listed=1; break; fi
  sleep "$PAUSE"
done
if [ -z "$listed" ]; then
  why=$(jget "$DIR/state/relay-state.json" listing_reply)
  rollback; die "the Leyline listing does not show Vanilla Remastered${why:+ (listing said: $why)}; rolled back."
fi
note "listed on Leyline"
mkdir -p "$PORTAL_DIR"
for f in "$PORTAL_DIR/vr-realm.id" "$WRATH_DIR/vr-realm.id"; do
  printf '%s\n' "$RID" > "$f.tmp" && chmod 644 "$f.tmp" && mv "$f.tmp" "$f"
done
note "$PORTAL_DIR/vr-realm.id and $WRATH_DIR/vr-realm.id: the website and the in-game list can mark it official (see the runbook)"
refresh_lists
echo
echo "Vanilla Remastered: realm $RID on $RELAY_NAME (https://$RELAY_NAME/r/$RID/status.json)"
echo "Stock 1.12.1 clients: set realmlist $RELAY_NAME:$APORT (or open its join page first, then $RELAY_NAME)"
echo "Logs: docker logs -f $C    Off Leyline: the vr-beacon-off step    Backup: $BK"
echo "VR BEACON OK"
