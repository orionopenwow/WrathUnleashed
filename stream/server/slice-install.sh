#!/usr/bin/env bash
# Install a slice sent as a tar stream on stdin (from "Make mini slice.bat" / "Upload a mini slice.bat"):
#   tar -cf - -C work mini.json mini | ssh root@server "bash /srv/wrath/stream/slice-install.sh mini <bytes>"
# (mini.json, the slice description with the maxTier that fit, is optional in the tar)
# Unpacks to slices/<name>.new, swaps it in, refreshes the realm's tier list and Dungeon Finder ids
# (ov_slices_tiers.lua, ov_slices_lfg.lua: the uploaded slices/<name>.json may have a new order or
# maxTier) and restarts wu-play when it runs. With too little disk for old + new side by side, the old slice goes first (the
# stream is down for the upload then).
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
NAME="${1:-}"; BYTES="${2:-0}"
[[ "$NAME" =~ ^[a-z0-9-]{1,32}$ ]] || die "usage: slice-install.sh <slice name> [bytes]"
[[ "$BYTES" =~ ^[0-9]+$ ]] || BYTES=0
D="$ST/slices"; mkdir -p "$D"
# leftovers of an earlier run that stopped halfway (any slice name), and the client kept for rollback
rm -rf "$D"/*.new "$D"/*.old "$D"/*.stage "$ST/www.old"
# Room for the new copy plus 2 GB kept free for the database, logs and Docker. Short of that, the old
# slice goes first (the stream is down during the upload); old and new are never both kept.
KEEP_FREE=$(( 2 * 1024 * 1024 * 1024 ))
need=$(( BYTES + BYTES / 20 + KEEP_FREE ))
avail=$(( $(df --output=avail -k "$D" | tail -1) * 1024 ))
if [ "$BYTES" -gt 0 ] && [ "$avail" -lt "$need" ]; then
  if [ -d "$D/$NAME" ]; then
    echo "  not enough disk for both copies ($((avail/1048576)) MB free, $((need/1048576)) MB needed): removing the old slice first"
    docker rm -f wu-play >/dev/null 2>&1 || true
    rm -rf "${D:?}/$NAME"
    avail=$(( $(df --output=avail -k "$D" | tail -1) * 1024 ))
  fi
  [ "$avail" -ge "$need" ] || die "not enough disk: $((avail/1048576)) MB free, $((need/1048576)) MB needed"
fi
mkdir "$D/$NAME.new"
tar -x -C "$D/$NAME.new" -f - --no-same-owner --no-same-permissions
# the tar holds one top folder (the slice); take its contents
inner="$D/$NAME.new/$NAME"
[ -d "$inner" ] || inner=$(find "$D/$NAME.new" -mindepth 1 -maxdepth 1 -type d | head -1)
[ -n "$inner" ] && [ -d "$inner" ] || die "the upload held no slice folder"
find "$inner" -maxdepth 2 -iname DBFilesClient | grep -c . >/dev/null || die "the upload is not an exported slice (no DBFilesClient)"
# The tar may carry the slice description next to the folder (<name>.json): one SSH connection.
if [ -f "$D/$NAME.new/$NAME.json" ]; then
  python3 -I "$ST/lua/tiers_lua.py" "$D/$NAME.new/$NAME.json" > /dev/null || die "the uploaded $NAME.json's tier list is broken: nothing changed"
  mv -f "$D/$NAME.new/$NAME.json" "$D/$NAME.json"
fi
mv "$inner" "$D/$NAME.stage"; rm -rf "$D/$NAME.new"
chmod -R a+rX "$D/$NAME.stage"
# Forever UI, when the server has it (fui-install.sh), goes back over the new slice before the swap.
if [ -f "$ST/fui-install.sh" ]; then
  bash "$ST/fui-install.sh" reapply-slice "$NAME" "$D/$NAME.stage" || echo "  WARNING: Forever UI could not be laid over the new slice: it streams with the stock interface (bash $ST/fui-install.sh status)"
fi
# The catalog mods' addons (mods-install.sh), when the server has them, go back over it too.
if [ -f "$ST/mods-install.sh" ]; then
  bash "$ST/mods-install.sh" reapply-slice "$NAME" "$D/$NAME.stage" || echo "  WARNING: the mods' addons could not be laid over the new slice (bash $ST/mods-install.sh status)"
fi
[ -d "$D/$NAME" ] && mv "$D/$NAME" "$D/$NAME.old"
mv "$D/$NAME.stage" "$D/$NAME"
rm -rf "$D/$NAME.old"
echo "  old slice removed; disk free now: $(df -h --output=avail "$D" | tail -1 | tr -d ' ')"
echo "  slice $NAME: $(du -sh "$D/$NAME" | cut -f1), $(find "$D/$NAME" -type f | wc -l) files"
if [ -f "$D/$NAME.json" ] && [ -d "$WU/portal/slices" ]; then install -m 644 "$D/$NAME.json" "$WU/portal/slices/$NAME.json"; fi
# Only the slice wu-play serves (STREAM_SLICES in portal.env, default mini) feeds the realm rule and wu-play. Another
# one (the Leyline Sample Hangout's "sampler") waits beside it until slice-serve.sh switches over; WU_SLICE_SERVE=1
# ("Make sampler slice.bat") does that right away.
served=$(grep -E '^STREAM_SLICES=' "$WU/portal.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
served=${served:-mini}
case ",$served," in
  *",$NAME,"*) ;;
  *)
    if [ "${WU_SLICE_SERVE:-}" = 1 ]; then
      exec bash "$ST/slice-serve.sh" "$NAME"
    fi
    echo "  slice $NAME is installed beside the served one ($served): the realm rule and wu-play are unchanged"
    echo "  to serve it: bash $ST/slice-serve.sh $NAME   (back: bash $ST/slice-serve.sh $served)"
    exit 0 ;;
esac
if [ -f "$D/$NAME.json" ] && [ -f "$WU/custom/lua_scripts/ov_slices.lua" ]; then
  if realm_tables "$D/$NAME.json" "$D/$NAME"; then
    soap "reload ale" >/dev/null 2>&1 && echo "  realm rule reloaded" || echo "  WARNING: reload ale failed: the realm keeps the old tier list until it restarts"
  else
    echo "  WARNING: $NAME.json's tier list is broken: the realm keeps the old one"
  fi
fi
if docker ps -a --format '{{.Names}}' | grep -cx wu-play >/dev/null; then
  docker restart wu-play >/dev/null && echo "  wu-play restarted on the new slice"
elif grep -qF "$MARK_BEGIN" "$CF" 2>/dev/null; then
  echo "  wu-play is not running: bash $ST/stream-up.sh starts it"
else
  echo "  next: bash $ST/stream-up.sh"
fi
