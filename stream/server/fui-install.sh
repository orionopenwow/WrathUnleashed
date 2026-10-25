#!/usr/bin/env bash
# Forever UI (github.com/Adrestie/mod-forever-ui, GPL-2.0, by Adrestie) over the streamed slice.
# Its art comes from the modern WoW client: it lives only in the gated stream (wu-play, behind the
# sign-in cookie), like the slice itself, and is never put anywhere public.
#
#   fui-install.sh install <upload dir>      from "Add Forever UI to the stream.bat" (one SSH, tar on stdin)
#   fui-install.sh remove                    from "Remove Forever UI from the stream.bat"
#   fui-install.sh reapply-slice <name> [<dir>]   slice-install.sh: lay it over a freshly uploaded slice
#   fui-install.sh reapply-www               patch-index.sh: back into a freshly uploaded client's boot list
#   fui-install.sh status
#
# Layout: $ST/overlays/foreverui/ holds Forever UI in game-path layout (the one real copy). Every
# slice in $ST/slices/ gets hard links to it (fui-overlay.py: files the slice lacks, plus
# GlueXML.toc with its one extra line; a record in <slice>/.overlay-foreverui/ makes it exact to
# undo), and $ST/www/boot-manifest.json lists its text files. wu-play caches /data/__index, so it is
# restarted. Idempotent: install twice and the second run replaces the first.
set -euo pipefail
ST0="${WU_STREAM_DIR:-${WU_DIR:-/srv/wrath}/stream}"
[ -f "$ST0/stream-lib.sh" ] || { echo "ERROR: $ST0/stream-lib.sh missing: the streaming kit is not on this server (run Make mini slice.bat first)" >&2; exit 1; }
. "$ST0/stream-lib.sh"
OV="$ST/overlays/foreverui"
BK="$ST/overlays/backup"
fui() { python3 -I "$ST/fui-overlay.py" "$@"; }

# The slice folders wu-play may serve (not the .new/.old/.stage of an upload in progress).
slice_dirs() {
  local d
  for d in "$ST"/slices/*/; do
    d=${d%/}
    case "$d" in *.new|*.old|*.stage) continue ;; esac
    if [ -n "$(find "$d" -maxdepth 2 -iname DBFilesClient)" ]; then echo "$d"; fi
  done
  return 0
}

# The slice whose record feeds the client's boot list: the one wu-play serves.
served_slice() {
  local s
  s=$(grep -m1 '^STREAM_SLICES=' "$WU/portal.env" 2>/dev/null | cut -d= -f2 | cut -d, -f1 || true)
  [ -n "$s" ] && [ -d "$ST/slices/$s" ] && { echo "$ST/slices/$s"; return; }
  [ -d "$ST/slices/mini" ] && { echo "$ST/slices/mini"; return; }
  slice_dirs | head -1
}

restart_play() {
  if docker ps -a --format '{{.Names}}' | grep -qx wu-play; then
    docker restart wu-play >/dev/null && echo "  wu-play restarted (it rebuilds /data/__index)"
    local _ want="$1"
    for _ in $(seq 1 20); do
      if docker exec wu-portal python3 -c "
import json,sys,urllib.request
n=json.load(urllib.request.urlopen('http://wu-play:8090/data/__index',timeout=10))
has=any(x.lower()==r'interface\addons\foreverui\foreverui.toc' for x in n)
sys.exit(0 if has==($want==1) else 3)" >/dev/null 2>&1; then
        [ "$want" = 1 ] && echo "  /data/__index lists Interface\\AddOns\\ForeverUI" || echo "  /data/__index no longer lists Forever UI"
        return 0
      fi
      sleep 1
    done
    echo "  WARNING: could not confirm /data/__index from wu-portal (docker logs wu-play)"
  else
    echo "  wu-play is not running: it picks Forever UI up when it starts (bash $ST/stream-up.sh)"
  fi
}

www_apply() {
  local s; s=$(served_slice || true)
  if [ -f "$ST/www/boot-manifest.json" ] && [ -n "$s" ]; then fui apply-www "$s" "$ST/www" "$BK"; fi
}

cmd="${1:-status}"
case "$cmd" in
  install)
    U="${2:?usage: fui-install.sh install <upload dir>}"
    [ -d "$U/foreverui" ] || die "the upload holds no foreverui folder"
    fui_py="$U/kit/fui-overlay.py"; [ -f "$fui_py" ] || fui_py="$ST/fui-overlay.py"
    python3 -I "$fui_py" check "$U/foreverui" || die "the upload is not Forever UI: nothing changed"
    log "Forever UI -> the streamed slice"
    mkdir -p "$BK"
    # The scripts first (backing up what they replace): the hooks in slice-install.sh and
    # patch-index.sh lay Forever UI over every later slice or client upload.
    for f in fui-install.sh fui-overlay.py slice-install.sh patch-index.sh; do
      [ -f "$U/kit/$f" ] || continue
      if [ -f "$ST/$f" ] && ! cmp -s "$U/kit/$f" "$ST/$f"; then cp -p "$ST/$f" "$BK/$f.$(date +%Y%m%d-%H%M%S)"; fi
      install -m 755 "$U/kit/$f" "$ST/$f"
    done
    sed -i 's/\r$//' "$ST"/*.sh
    chmod -R a+rX "$U/foreverui"
    rm -rf "$OV.old"
    [ -d "$OV" ] && mv "$OV" "$OV.old"
    mv "$U/foreverui" "$OV"
    n=0
    while read -r s; do
      [ -n "$s" ] || continue
      fui apply-slice "$OV" "$s" || { [ -d "$OV.old" ] && { rm -rf "$OV"; mv "$OV.old" "$OV"; fui apply-slice "$OV" "$s" || true; }; die "could not lay Forever UI over $s (the previous state is back)"; }
      n=$((n+1))
    done < <(slice_dirs)
    rm -rf "$OV.old"
    [ "$n" -gt 0 ] || echo "  no slice on the server yet: Make mini slice.bat lays Forever UI over it on upload"
    www_apply
    restart_play 1
    echo "  disk free now: $(df -h --output=avail "$ST" | tail -1 | tr -d ' ')"
    echo "  Forever UI is on in the stream (players: ?foreverui=0 on the page for the stock look)"
    ;;
  remove)
    log "Forever UI off the streamed slice"
    while read -r s; do [ -n "$s" ] && fui unapply-slice "$s"; done < <(slice_dirs)
    if [ -f "$ST/www/boot-manifest.json" ]; then fui unapply-www "$ST/www"; fi
    rm -rf "$OV" "$OV.old"
    restart_play 0
    echo "  Forever UI removed (the slice and the client are as uploaded)"
    ;;
  reapply-slice)
    name="${2:?usage: fui-install.sh reapply-slice <name> [<dir>]}"; dir="${3:-$ST/slices/$name}"
    [ -d "$OV" ] || exit 0
    fui apply-slice "$OV" "$dir"
    if [ -f "$ST/www/boot-manifest.json" ]; then fui apply-www "$dir" "$ST/www" "$BK"; fi
    ;;
  reapply-www)
    [ -d "$OV" ] || exit 0
    www_apply
    ;;
  status)
    [ -d "$OV" ] && fui check "$OV" || echo "  no Forever UI overlay on the server"
    while read -r s; do [ -n "$s" ] && fui status "$s"; done < <(slice_dirs)
    if [ -f "$ST/www/boot-manifest.json" ] && [ -n "$(served_slice)" ]; then fui status "$(served_slice)" "$ST/www" | tail -1; fi
    ;;
  *) die "usage: fui-install.sh install <dir> | remove | reapply-slice <name> [<dir>] | reapply-www | status" ;;
esac
