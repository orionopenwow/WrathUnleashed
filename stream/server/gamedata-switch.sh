#!/usr/bin/env bash
# The game data killswitch: one action that stops this server serving ANY game-derived data to players.
#
#   bash /srv/wrath/stream/gamedata-switch.sh off [--park]   game data OFF (the killswitch is ON)
#   bash /srv/wrath/stream/gamedata-switch.sh on             game data back ON (streaming as before)
#   bash /srv/wrath/stream/gamedata-switch.sh status         what is served now (read-only)
#
# off:
#   1. the flag file $WU/portal/gamedata-off (wu-portal sees it at /app/gamedata-off on its next request, no
#      restart): /wrath/play sends everyone to "Play with my own game files", /__auth answers 410 for /data,
#      /wrath/status.json says "gamedata_streaming": false (the launcher and the admin console read it), and the
#      screenshots on the public pages answer 410;
#   2. Caddy: a block inside the stream site (gamedata-caddy.py) answers 410 Gone for /data, /data/*,
#      /boot-manifest.json and /world-manifest.json before the gate or wu-play is asked;
#   3. every stream account is released on the realm (no one stays held to the slice);
#   4. --park (optional): the slices, the Forever UI overlay and the two manifests move off the served folders
#      into $WU/offline-gamedata/<time>/ (never deleted), and wu-play restarts on empty placeholders.
#   The page, the client's own code and /ws stay: the browser client then plays only with the player's own
#   3.3.5a game folder (ownfiles.js).
# on: the reverse (an earlier --park is moved back first). Streaming resumes for the next Play.
#
# Both print what was served before and after, check the public answers (410 for the tier index and a slice
# file when off; the sign-in gate again when on), and append one line to $WU/gamedata-switch.log.
# A Caddy that refuses the change gets its previous Caddyfile back. Turning game data OFF never rolls the
# flag back: a half-done "off" still keeps /data closed at the sign-in gate (wu-portal's /__auth).
# Ends with "GAMEDATA OFF OK" / "GAMEDATA ON OK" / "GAMEDATA STATUS OK".
set -euo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
if [ -f "$HERE/stream-lib.sh" ]; then . "$HERE/stream-lib.sh"; else
  WU="${WU_DIR:-/srv/wrath}"; ST="${WU_STREAM_DIR:-$WU/stream}"; CF="${WU_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}"
  CADDY_DIR="${WU_CADDY_DIR:-/opt/wenilla-realm}"; STREAM_HOST="${WU_STREAM_HOST:-wrath.openvanilla.app}"
  UPSTREAM="${WU_UPSTREAM:-play.openvanilla.app}"
  log() { printf '\n== %s\n' "$*"; }
  die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
  caddy_reload() { (cd "$CADDY_DIR" && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile); }
fi
FLAG="${WU_GAMEDATA_FLAG_HOST:-$WU/portal/gamedata-off}"
OFFLINE="$WU/offline-gamedata"
GLOG="$WU/gamedata-switch.log"
GCADDY="$HERE/gamedata-caddy.py"
TS=$(date -u +%Y%m%d-%H%M%S)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BY="${WU_GAMEDATA_BY:-${SUDO_USER:-owner}}"
BY=$(printf '%s' "$BY" | tr -cd 'A-Za-z0-9 _.@-' | cut -c1-40)
BK="${WU_BACKUPS:-/root/gamedata-backups}/$TS"
# A file in every slice that the checks ask for (any /data name answers the same; this one is in every slice).
SLICE_FILE="/data/DBFilesClient%5CMap.dbc"

caddy_state() { [ -f "$CF" ] && python3 -I "$GCADDY" status "$CF" 2>/dev/null || echo "no-caddyfile"; }
code() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$1" 2>/dev/null || true; }
flag_since() { python3 -I -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("since","?"))
except Exception: print("?")' "$FLAG"; }

# The slice folders on disk (not an upload in progress), placeholders included.
slice_dirs() {
  local d
  for d in "$ST"/slices/*/; do
    [ -d "$d" ] || continue
    d=${d%/}
    case "$d" in *.new|*.old|*.stage) continue ;; esac
    echo "$d"
  done
  return 0
}
size_of() { if [ -e "$1" ]; then echo "$(du -sh "$1" 2>/dev/null | cut -f1), $(find "$1" -type f 2>/dev/null | wc -l) files"; else echo "none"; fi; }

play_running() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx wu-play; }
# How many names wu-play's /data/__index lists, asked inside the Docker network (never public); "-" when it can't.
index_count() {
  play_running || { echo "-"; return 0; }
  docker exec wu-portal python3 -c 'import json,urllib.request
print(len(json.load(urllib.request.urlopen("http://wu-play:8090/data/__index",timeout=10))))' 2>/dev/null || echo "-"
}
# wu-play still serves the page (the client's own code): 0 = yes.
page_ok() {
  local _
  for _ in $(seq 1 "${WU_PLAY_WAIT:-20}"); do
    docker exec wu-portal python3 -c 'import urllib.request,sys
sys.exit(0 if urllib.request.urlopen("http://wu-play:8090/index.html",timeout=10).status==200 else 1)' >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

report() {   # $1 = "before" / "after"
  echo "  -- $1 --"
  if [ -f "$FLAG" ]; then echo "  game data streaming: OFF since $(flag_since) (flag $FLAG)"; else echo "  game data streaming: ON (no flag)"; fi
  echo "  Caddy killswitch block: $(caddy_state)   (on = 410 for the game-data routes)"
  local d
  while read -r d; do
    [ -n "$d" ] || continue
    if [ -f "$d/.gamedata-parked" ]; then echo "  slice $(basename "$d"): parked (empty placeholder)"; else echo "  slice $(basename "$d"): $(size_of "$d")"; fi
  done < <(slice_dirs)
  [ -d "$ST/overlays/foreverui" ] && echo "  Forever UI overlay (art from the game client): $(size_of "$ST/overlays/foreverui")"
  local m
  for m in boot-manifest.json world-manifest.json; do [ -f "$ST/www/$m" ] && echo "  www/$m (game file names): $(size_of "$ST/www/$m")"; done
  [ -f "$OFFLINE/CURRENT" ] && echo "  parked off the served folders: $(cat "$OFFLINE/CURRENT") ($(size_of "$(cat "$OFFLINE/CURRENT")"))"
  echo "  wu-play: $(play_running && echo running || echo 'not running'); /data/__index lists $(index_count) names (inside the Docker network)"
  echo "  public answers (no sign-in; 410 = gone, 302/401/403 = behind the sign-in gate, 200 = served):"
  echo "    /data/__tier/index.json  $(code "https://$STREAM_HOST/data/__tier/index.json")"
  echo "    /data/__index            $(code "https://$STREAM_HOST/data/__index")"
  echo "    $SLICE_FILE  $(code "https://$STREAM_HOST$SLICE_FILE")"
  echo "    /boot-manifest.json      $(code "https://$STREAM_HOST/boot-manifest.json")"
  echo "    /world-manifest.json     $(code "https://$STREAM_HOST/world-manifest.json")"
  echo "    /wenilla_bg.wasm (our client, stays) $(code "https://$STREAM_HOST/wenilla_bg.wasm")"
  echo "    /wrath/art/leyline-shot-city.webp (a game screenshot) $(code "https://$UPSTREAM/wrath/art/leyline-shot-city.webp")"
}

glog() {
  echo "$NOW $1 by=$BY $2" >> "$GLOG"
  # what the sign-in page shows as "since" (the admin console's status line; /wrath/status.json)
  printf '{"state": "%s", "at": "%s", "by": "%s"}\n' "$1" "$NOW" "$BY" > "$WU/portal/gamedata-last.json.tmp" 2>/dev/null \
    && chmod 644 "$WU/portal/gamedata-last.json.tmp" && mv -f "$WU/portal/gamedata-last.json.tmp" "$WU/portal/gamedata-last.json" || true
}

caddy_apply() {   # $1 = add|remove; 0 = done (or nothing to do), 1 = Caddy refused (the old file is back)
  [ -f "$CF" ] || { echo "  no Caddyfile at $CF: nothing to change there"; return 0; }
  mkdir -p "$BK"; cp -p "$CF" "$BK/Caddyfile"
  local rc=0
  python3 -I "$GCADDY" "$1" "$CF" "$STREAM_HOST" || rc=$?
  if [ "$rc" = 3 ]; then echo "  no streaming site in the Caddyfile: $STREAM_HOST serves nothing (stream-up.sh adds the 410 block when it runs)"; return 0; fi
  [ "$rc" = 0 ] || { cat "$BK/Caddyfile" > "$CF"; echo "  could not edit $CF (left as it was)"; return 1; }
  if cmp -s "$CF" "$BK/Caddyfile"; then echo "  Caddy: already so"; return 0; fi
  if ! caddy_reload; then
    cat "$BK/Caddyfile" > "$CF"; caddy_reload || true
    echo "  Caddy refused the change: the previous Caddyfile is back ($BK/Caddyfile)"
    return 1
  fi
  echo "  Caddy reloaded (backup: $BK/Caddyfile)"
}

release_accounts() {
  echo "DELETE FROM ov_stream_accounts;" | docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' >/dev/null 2>&1 \
    && echo "  stream accounts released (no one is held to the slice)" || echo "  (no stream accounts table: nothing to release)"
  if [ -f "$WU/soap-cmd.sh" ]; then
    bash "$WU/soap-cmd.sh" "reload ale" >/dev/null 2>&1 || echo "  WARNING: reload ale failed; marks still in the world server's memory end within 12 h"
  fi
}

park() {
  local dest="$OFFLINE/$TS" d n=0
  mkdir -p "$dest/slices" "$dest/overlays" "$dest/www"; chmod 700 "$OFFLINE"
  : > "$dest/parked.txt"
  while read -r d; do
    [ -n "$d" ] && [ ! -f "$d/.gamedata-parked" ] || continue
    mv "$d" "$dest/slices/"
    mkdir -p "$d/DBFilesClient"; touch "$d/.gamedata-parked"; chmod -R a+rX "$d"
    printf '%s\t%s\n' "$d" "$dest/slices/$(basename "$d")" >> "$dest/parked.txt"; n=$((n+1))
  done < <(slice_dirs)
  if [ -d "$ST/overlays/foreverui" ]; then
    mv "$ST/overlays/foreverui" "$dest/overlays/"; printf '%s\t%s\n' "$ST/overlays/foreverui" "$dest/overlays/foreverui" >> "$dest/parked.txt"
  fi
  local f
  for f in "$ST"/www/boot-manifest.json* "$ST"/www/world-manifest.json*; do
    [ -f "$f" ] || continue
    mv "$f" "$dest/www/"; printf '%s\t%s\n' "$f" "$dest/www/$(basename "$f")" >> "$dest/parked.txt"
  done
  echo "$dest" > "$OFFLINE/CURRENT"
  echo "  parked $n slice(s), the Forever UI overlay and the manifests in $dest (never deleted)"
  if play_running; then
    docker restart wu-play >/dev/null
    if page_ok; then echo "  wu-play restarted on the empty placeholders: the page still answers"
    else
      echo "  wu-play does not serve the page on the placeholders: moving everything back"
      unpark; return 1
    fi
  fi
}

unpark() {
  [ -f "$OFFLINE/CURRENT" ] || return 0
  local dest from to
  dest=$(cat "$OFFLINE/CURRENT")
  [ -f "$dest/parked.txt" ] || die "$dest/parked.txt missing: move the parked files back by hand from $dest"
  while IFS=$'\t' read -r from to; do
    [ -n "$from" ] && [ -e "$to" ] || continue
    if [ -d "$from" ]; then
      if [ -f "$from/.gamedata-parked" ]; then rm -rf "$from"; else die "$from exists and is not a placeholder: the parked copy stays in $to; sort it out by hand"; fi
    fi
    mv "$to" "$from"
  done < "$dest/parked.txt"
  rm -f "$OFFLINE/CURRENT"
  mv "$dest/parked.txt" "$dest/restored-$TS.txt"
  find "$dest" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  echo "  the parked files are back where they were served from"
  if play_running; then docker restart wu-play >/dev/null && echo "  wu-play restarted on the real slice"; fi
}

checks_off() {
  local bad=0 c u
  for u in /data/__tier/index.json "$SLICE_FILE" /boot-manifest.json; do
    c=$(code "https://$STREAM_HOST$u")
    if [ "$c" = 410 ]; then echo "  CHECK $u -> 410 Gone"; else echo "  CHECK FAILED $u -> $c (want 410)"; bad=1; fi
  done
  return $bad
}
checks_on() {
  local c bad=0
  c=$(code "https://$STREAM_HOST/data/__tier/index.json")
  case "$c" in 302|401|403) echo "  CHECK /data/__tier/index.json -> $c (behind the sign-in gate again)" ;;
    *) echo "  CHECK FAILED /data/__tier/index.json -> $c (want the sign-in gate: 302/401/403)"; bad=1 ;; esac
  return $bad
}
portal_knows() {
  if ! grep -q 'gamedata_off' "$WU/portal/wrath_portal.py" 2>/dev/null; then
    echo "  WARNING: the sign-in page on this server predates the killswitch: Caddy still answers 410, but the Play"
    echo "           page and status.json don't know yet. Let Autopilot run the \"signin\" step."
  fi
}

cmd="${1:-status}"; opt="${2:-}"
[ -f "$GCADDY" ] || die "$GCADDY missing (Game data killswitch ON.bat uploads it)"
case "$cmd" in
  off)
    log "Game data OFF (the killswitch)"
    report before
    log "1/4 Flag: $FLAG"
    if [ -f "$FLAG" ]; then echo "  already off since $(flag_since)"; else
      mkdir -p "$(dirname "$FLAG")"
      printf '{"gamedata_streaming": false, "since": "%s", "by": "%s"}\n' "$NOW" "$BY" > "$FLAG.tmp"
      chmod 644 "$FLAG.tmp"; mv -f "$FLAG.tmp" "$FLAG"
      echo "  written (wu-portal reads it on every request)"
    fi
    portal_knows
    log "2/4 Caddy: 410 Gone for the game-data routes"
    caddy_ok=1; caddy_apply add || caddy_ok=0
    log "3/4 Realm: stream accounts released"
    release_accounts
    log "4/4 Park the files"
    park_ok=1
    if [ "$opt" = "--park" ]; then park || park_ok=0; else echo "  skipped (add --park to move the slices off the served folders too)"; fi
    sleep "${WU_SETTLE:-2}"
    log "Check"
    ok=1; checks_off || ok=0
    log "After"
    report after
    glog off "park=$([ "$opt" = --park ] && echo 1 || echo 0) caddy=$caddy_ok park_ok=$park_ok checks=$ok"
    if [ "$caddy_ok" = 1 ] && [ "$park_ok" = 1 ] && [ "$ok" = 1 ]; then
      echo; echo "Game data is OFF: this server serves no game data. Players use their own 3.3.5a game folder."
      echo "On again: bash $ST/gamedata-switch.sh on   (or \"Game data killswitch OFF.bat\")"
      echo "GAMEDATA OFF OK"
    else
      echo; echo "Game data is switched off at the sign-in gate, but not every check passed (see above). The flag stays on." >&2
      exit 1
    fi
    ;;
  on)
    log "Game data back ON"
    report before
    log "1/3 Parked files back"
    unpark
    log "2/3 Caddy: the 410 block out"
    caddy_apply remove || die "Caddy refused: game data stays OFF (the flag is kept). Nothing else changed."
    log "3/3 Flag removed"
    if [ -f "$FLAG" ]; then mkdir -p "$BK"; mv -f "$FLAG" "$BK/gamedata-off"; echo "  removed (kept in $BK)"; else echo "  there was none"; fi
    sleep "${WU_SETTLE:-2}"
    log "Check"
    ok=1; checks_on || ok=0
    log "After"
    report after
    glog on "checks=$ok"
    [ "$ok" = 1 ] || { echo "Game data is back on, but a check did not pass (see above)." >&2; exit 1; }
    echo; echo "Game data streaming is ON again (the next Play streams the slice)."
    echo "GAMEDATA ON OK"
    ;;
  status)
    report now
    echo "GAMEDATA STATUS OK"
    ;;
  *) die "usage: bash $ST/gamedata-switch.sh off [--park] | on | status" ;;
esac
