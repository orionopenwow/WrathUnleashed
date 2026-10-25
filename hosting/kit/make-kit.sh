#!/usr/bin/env bash
# Fills realm-files/ from the WrathUnleashed realm folder and (optionally) zips the host kit for
# players. Runs on the owner's PC (WSL/Git Bash) or in CI. Never copies state/, .env or cache/:
# those are one host's secrets.
#   bash make-kit.sh [REALM_DIR] [--zip OUT.zip]      REALM_DIR default: ../realm
set -euo pipefail
KIT="$(cd "$(dirname "$0")" && pwd)"
REALM="${1:-$KIT/../realm}"
[ -f "$REALM/profiles/main.env" ] || { echo "no realm folder at $REALM" >&2; exit 1; }
rm -rf "$KIT/realm-files"
mkdir -p "$KIT/realm-files/profiles" "$KIT/realm-files/sql"
cp "$REALM"/profiles/{main,brawl,progression,casual,dalaran}.env "$KIT/realm-files/profiles/"
cp "$REALM/modules.env" "$KIT/realm-files/"
cp -r "$REALM/custom/lua_scripts" "$KIT/realm-files/lua_scripts"
for f in brawl_world.sql brawl_world_2.sql main_unbrawl.sql main_world.sql modern_combos.sql; do
  [ -f "$REALM/$f" ] && cp "$REALM/$f" "$KIT/realm-files/sql/"
done
sed -i 's/\r$//' "$KIT"/realm-files/profiles/*.env "$KIT/realm-files/modules.env"
( cd "$KIT/realm-files" && find . -type f | sort | xargs sha256sum > MANIFEST.sha256 )
echo "realm-files/ ready ($(find "$KIT/realm-files" -type f | wc -l) files)"
if [ "${2:-}" = "--zip" ]; then
  out="${3:?--zip needs a file name}"
  ( cd "$KIT/.." && zip -qr "$out" "$(basename "$KIT")" -x '*/state/*' '*/.env' '*/cache/*' '*/__pycache__/*' )
  echo "kit: $out"
fi
