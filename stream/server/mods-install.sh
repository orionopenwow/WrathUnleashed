#!/usr/bin/env bash
# The mods catalog (mods/catalog/<id>/) onto the live realm, into the streamed client, and onto the site.
#
#   mods-install.sh install <upload dir>     from "mods/Put mods on Wrath.bat" (one SSH, tar on stdin)
#   mods-install.sh reapply-slice <name> [<dir>]   slice-install.sh: lay the mods over a freshly uploaded slice
#   mods-install.sh reapply-www              patch-index.sh: back into a freshly uploaded client's boot list
#   mods-install.sh status
#
# install, in order; nothing changes until the whole catalog passes wu-mod.py:
#   1. check + pack: wu-mod.py catalog (every mod checked, zips + catalog.json + the WUModCatalog addon).
#   2. realm: each realm/ half into custom/lua_scripts/mods/<id>/ (the folder is exactly the catalog), the old
#      folder backed up, then a live "reload ale". A refused reload, or a Lua error from mods/ in the world
#      server's log, puts the old folder back and reloads again. Unchanged scripts: no reload at all.
#   3. stream: the ui/ halves (and WUModCatalog) as $ST/overlays/mods, laid over every slice and into the
#      client's boot list by mods-overlay.py (the sibling of fui-overlay.py), wu-play restarted only when the
#      addons changed. A failure here puts the previous addons back, and the previous realm scripts too.
#      No streaming kit on the server: skipped (said so).
#   4. site: catalog.json, installed.json, the zips and screenshots into $WU/portal/mods, which wu-portal
#      serves at /wrath/mods (stream/workshop.py). Swapped in whole.
# Ends with "MODS OK". Backups in /root/mods-backups/<time>.
set -euo pipefail
WU="${WU_DIR:-/srv/wrath}"
ST="${WU_STREAM_DIR:-$WU/stream}"
if [ -f "$ST/stream-lib.sh" ]; then . "$ST/stream-lib.sh"; else
  log() { printf '\n== %s\n' "$*"; }
  die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
fi
LUA_DIR="${WU_LUA_DIR:-$WU/custom/lua_scripts}"
MODS_LUA="$LUA_DIR/mods"
PUB="${WU_MODS_PUB:-$WU/portal/mods}"
OV="$ST/overlays/mods"
WORLD="${WU_WORLD_CONTAINER:-ov-ac-worldserver}"
ovl() { python3 -I "$ST/mods-overlay.py" "$@"; }

slice_dirs() {
  local d
  for d in "$ST"/slices/*/; do
    d=${d%/}
    case "$d" in *.new|*.old|*.stage) continue ;; esac
    [ -d "$d" ] || continue
    if [ -n "$(find "$d" -maxdepth 2 -iname DBFilesClient)" ]; then echo "$d"; fi
  done
  return 0
}

served_slice() {
  local s
  s=$(grep -m1 '^STREAM_SLICES=' "$WU/portal.env" 2>/dev/null | cut -d= -f2 | cut -d, -f1 || true)
  [ -n "$s" ] && [ -d "$ST/slices/$s" ] && { echo "$ST/slices/$s"; return; }
  [ -d "$ST/slices/mini" ] && { echo "$ST/slices/mini"; return; }
  slice_dirs | head -1
}

www_apply() {
  local s; s=$(served_slice || true)
  if [ -f "$ST/www/boot-manifest.json" ] && [ -n "$s" ]; then ovl apply-www "$s" "$ST/www"; fi
}

restart_play() {
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx wu-play; then
    docker restart wu-play >/dev/null && echo "  wu-play restarted (it rebuilds /data/__index with the mods' addons)"
  else
    echo "  wu-play is not running: it picks the mods up when it starts"
  fi
}

reload_ale() {   # 0 = reloaded with no Lua error from mods/ in the log
  local since out
  since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  out=$(bash "$WU/soap-cmd.sh" "reload ale" 2>&1) || { echo "  reload ale refused: $out"; return 1; }
  echo "  reload ale: ${out:-ok}"
  sleep "${WU_RELOAD_WAIT:-3}"
  local errs
  errs=$(docker logs --since "$since" "$WORLD" 2>&1 | grep -E 'lua_scripts/mods/|mods/[a-z][a-z0-9-]*/[^ ]*\.lua' \
         | grep -iE 'error|failed|attempt to' | tail -5 || true)
  if [ -n "$errs" ]; then echo "  Lua errors from the mods:"; printf '    %s\n' "$errs"; return 1; fi
  return 0
}

restart_world() {   # a 5-minute in-game warning (MODS_WARN_MIN), then a world server restart; 0 = back up
  local min=${MODS_WARN_MIN:-5} started
  if [ "$min" -gt 0 ]; then
    echo "  announcing a restart in $min minute(s)"
    bash "$WU/soap-cmd.sh" "announce Server restart in $min minutes: new mods are coming. Back in a few minutes." >/dev/null 2>&1 || true
    sleep $(( min * 60 - 60 )) || true
    bash "$WU/soap-cmd.sh" "announce Server restart in 1 minute." >/dev/null 2>&1 || true
    sleep 60
    bash "$WU/soap-cmd.sh" "saveall" >/dev/null 2>&1 || true
  fi
  docker restart "$WORLD" >/dev/null || return 1
  started=$(docker inspect -f '{{.State.StartedAt}}' "$WORLD")
  for _ in $(seq 1 120); do
    if docker logs --since "$started" "$WORLD" 2>&1 | grep -F 'ready...' >/dev/null; then echo "  world server ready"; return 0; fi
    sleep 10
  done
  return 1
}

realm_rollback() {   # $1 = backup dir
  rm -rf "$MODS_LUA"
  if [ -d "$1/lua-mods" ]; then cp -a "$1/lua-mods" "$MODS_LUA"; fi
  bash "$WU/soap-cmd.sh" "reload ale" >/dev/null 2>&1 || true
  echo "  the previous realm mod scripts are back"
}

ui_rollback() {
  rm -rf "$OV"
  if [ -d "$OV.old" ]; then mv "$OV.old" "$OV"; fi
  while read -r s; do
    [ -n "$s" ] || continue
    if [ -d "$OV" ]; then ovl apply-slice "$OV" "$s" || true; else ovl unapply-slice "$s" || true; fi
  done < <(slice_dirs)
  if [ -d "$OV" ]; then www_apply || true; elif [ -f "$ST/www/boot-manifest.json" ]; then ovl unapply-www "$ST/www" || true; fi
  echo "  the previous mod addons are back in the stream"
}

cmd="${1:-status}"
case "$cmd" in
  install)
    U="${2:?usage: mods-install.sh install <upload dir>}"
    [ -d "$U/catalog" ] || die "the upload holds no catalog folder"
    [ -f "$U/kit/wu-mod.py" ] || die "the upload holds no kit/wu-mod.py"
    find "$U" -type f \( -name '*.lua' -o -name '*.sh' -o -name '*.py' -o -name '*.toc' -o -name '*.xml' -o -name '*.json' \) \
      -exec sed -i 's/\r$//' {} +
    O="$U/out"; rm -rf "$O"; mkdir -p "$O/files" "$O/addons"

    log "1. check and pack the catalog"
    python3 -I "$U/kit/wu-mod.py" catalog "$U/catalog" -o "$O/catalog.json" --dist "$O/files" --lua "$O/addons" \
      || die "a mod in the catalog does not pass wu-mod.py: nothing changed"
    python3 -I "$U/kit/mods-overlay.py" build "$O/catalog.json" "$U/catalog" "$O/addons" "$O/overlay" >/dev/null
    BK=${WU_MODS_BACKUPS:-/root/mods-backups}/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
    [ -d "$MODS_LUA" ] && cp -a "$MODS_LUA" "$BK/lua-mods"
    [ -d "$PUB" ] && cp -a "$PUB" "$BK/site-mods"

    log "2. realm scripts (custom/lua_scripts/mods)"
    [ -d "$LUA_DIR" ] || die "no $LUA_DIR: is this the realm server?"
    NEW="$MODS_LUA.new"; rm -rf "$NEW"; mkdir -p "$NEW"
    python3 -I - "$O/catalog.json" "$U/catalog" "$NEW" <<'PY'
import json, os, shutil, sys
cat, src, dst = sys.argv[1:4]
for m in json.load(open(cat))["mods"]:
    if not m["realm_files"]:
        continue
    os.makedirs(os.path.join(dst, m["id"]))
    for f in m["realm_files"]:
        out = os.path.join(dst, m["id"], f)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copyfile(os.path.join(src, m["id"], "realm", f), out)
        print(f"  {m['id']}/{f}")
PY
    find "$NEW" -type d -exec chmod 755 {} + ; find "$NEW" -type f -exec chmod 644 {} +
    if [ -d "$MODS_LUA" ] && diff -rq "$MODS_LUA" "$NEW" >/dev/null 2>&1; then
      rm -rf "$NEW"; echo "  unchanged: no reload"; realm_changed=0
    else
      # A script file the realm has never run loads by a restart with a warning, never by a live
      # "reload ale" (a live reload that added new scripts crashed the world server on 2026-10-25).
      added=$( (cd "$NEW" && find . -type f -name '*.lua' | sort) | while read -r f; do [ -f "$MODS_LUA/$f" ] || echo "$f"; done)
      rm -rf "$MODS_LUA"; mv "$NEW" "$MODS_LUA"; realm_changed=1
      if [ -n "$added" ]; then
        echo "  new mod scripts:" $added "(loaded by a restart)"
        restart_world || die "the world server did not come back after the restart: docker logs --tail 80 $WORLD. Backups: $BK"
      else
        reload_ale || { realm_rollback "$BK"; die "the realm refused the new mod scripts; the previous ones are back"; }
      fi
    fi

    log "3. addons in the streamed client"
    if [ -f "$ST/stream-lib.sh" ] && [ -d "$ST/slices" ]; then
      for f in mods-install.sh mods-overlay.py; do
        if [ -f "$ST/$f" ] && ! cmp -s "$U/kit/$f" "$ST/$f"; then cp -p "$ST/$f" "$BK/$f"; fi
        install -m 755 "$U/kit/$f" "$ST/$f"
      done
      mkdir -p "$ST/overlays"
      before=$(ovl digest "$OV"); after=$(ovl digest "$O/overlay")
      rm -rf "$OV.old"; [ -d "$OV" ] && mv "$OV" "$OV.old"
      mv "$O/overlay" "$OV"
      n=0
      while read -r s; do
        [ -n "$s" ] || continue
        ovl apply-slice "$OV" "$s" || { ui_rollback; [ "$realm_changed" = 1 ] && realm_rollback "$BK"; die "could not lay the mods over $s"; }
        n=$((n+1))
      done < <(slice_dirs)
      [ "$n" -gt 0 ] || echo "  no slice on the server yet: Make mini slice.bat lays the mods over it on upload"
      www_apply || { ui_rollback; [ "$realm_changed" = 1 ] && realm_rollback "$BK"; die "could not list the mods in the client's boot list"; }
      rm -rf "$OV.old"
      if [ "$before" != "$after" ]; then restart_play; else echo "  addons unchanged: wu-play keeps running"; fi
    else
      echo "  no streaming kit on this server ($ST): the addons are not streamed (the realm and site parts still are)"
    fi

    log "4. the site (/wrath/mods)"
    P="$PUB.new"; rm -rf "$P"; mkdir -p "$P/files" "$P/shots"
    cp -p "$O/catalog.json" "$P/catalog.json"
    cp -p "$O"/files/*.zip "$O"/files/*.zip.sha256 "$P/files/"
    python3 -I - "$O/catalog.json" "$U/catalog" "$P" <<'PY'
import json, os, shutil, sys, time
cat, src, dst = sys.argv[1:4]
mods = json.load(open(cat))["mods"]
for m in mods:
    for s in m["screenshots"]:
        d = os.path.join(dst, "shots", m["id"])
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(os.path.join(src, m["id"], s), os.path.join(d, os.path.basename(s)))
json.dump({"installed": {m["id"]: m["version"] for m in mods}, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
          open(os.path.join(dst, "installed.json"), "w"), indent=1, sort_keys=True)
print(f"  {len(mods)} mod(s) published")
PY
    find "$P" -type d -exec chmod 755 {} + ; find "$P" -type f -exec chmod 644 {} +
    rm -rf "$PUB.old"; [ -d "$PUB" ] && mv "$PUB" "$PUB.old"
    mv "$P" "$PUB"; rm -rf "$PUB.old"
    echo "  backups: $BK"
    echo "MODS OK"
    ;;
  reapply-slice)
    name="${2:?usage: mods-install.sh reapply-slice <name> [<dir>]}"; dir="${3:-$ST/slices/$name}"
    [ -d "$OV" ] || exit 0
    ovl apply-slice "$OV" "$dir"
    if [ -f "$ST/www/boot-manifest.json" ]; then ovl apply-www "$dir" "$ST/www"; fi
    ;;
  reapply-www)
    [ -d "$OV" ] || exit 0
    www_apply
    ;;
  status)
    [ -f "$PUB/installed.json" ] && echo "  on the site: $(tr -d '\n' < "$PUB/installed.json")" || echo "  no mods on the site"
    [ -d "$MODS_LUA" ] && echo "  realm: $(ls "$MODS_LUA" | tr '\n' ' ')" || echo "  realm: no mod scripts"
    while read -r s; do [ -n "$s" ] && ovl status "$s"; done < <(slice_dirs)
    ;;
  *) die "usage: mods-install.sh install <dir> | reapply-slice <name> [<dir>] | reapply-www | status" ;;
esac
