#!/usr/bin/env bash
# WrathUnleashed: install realm Lua scripts (a tar on stdin) and reload them live (no restart).
# Backs up each replaced file first; a failed reload puts the old files back.
set -euo pipefail
cd /srv/wrath
DST=custom/lua_scripts
BK=/root/lua-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
tar -x -C "$T" -f -
n=0
for f in "$T"/*.lua; do
  [ -f "$f" ] || continue
  b=$(basename "$f"); sed -i 's/\r$//' "$f"
  [ -f "$DST/$b" ] && cp -p "$DST/$b" "$BK/$b"
  install -m 644 "$f" "$DST/$b"; echo "  $b installed"; n=$((n+1))
done
[ "$n" -gt 0 ] || { echo "LUAUP FAILED: no .lua files in the upload" >&2; exit 1; }
if out=$(bash soap-cmd.sh "reload ale" 2>&1); then
  echo "  reload ale: ${out:-ok}"
else
  for b in "$BK"/*.lua; do [ -f "$b" ] && cp -p "$b" "$DST/"; done
  bash soap-cmd.sh "reload ale" >/dev/null 2>&1 || true
  echo "LUAUP FAILED: reload ale refused ($out); the previous scripts are back" >&2; exit 1
fi
sleep 2
if docker logs --since 30s ov-ac-worldserver 2>&1 | grep -iE 'lua.*(error|failed)|\[Eluna\].*error|ALE.*error' | tail -5 | grep . ; then
  echo "  (the lines above are Lua errors since the reload: check them)"
fi
echo "  backups: $BK"
echo "LUAUP OK"
