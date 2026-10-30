#!/bin/sh
# Server data for the TrinityCore 4.3.4 realm from the HOST'S OWN 4.3.4 client (Leyline host kit, profile
# tcpp-4.3.4). Runs in the extractors image with the client folder mounted read-only at /client and the data volume
# at /data. Nothing is downloaded: dbc, maps, vmaps and the monster paths (mmaps) are made here by the core's own
# tools from the files on this PC, and they never leave it. Safe to run again: finished steps are kept.
#   LL_THREADS   monster-path threads (default: all CPUs)
#   LL_MMAPS     1 (default) builds the monster paths, 0 skips them
#   LL_CLIENT_FILES   files the client folder must have (from profile.lock, comma separated)
set -eu
X=/opt/tc/bin
C=/client
D=/data
T="${LL_THREADS:-$(nproc)}"
have() { [ -f "$C/$1" ] || [ -f "$C/$(dirname "$1")/$(basename "$1" | tr 'A-Z' 'a-z')" ]; }
for f in $(echo "${LL_CLIENT_FILES:-Data/art.MPQ}" | tr ',' ' '); do
  have "$f" || { echo "No game files of this client in the folder you picked (it needs $f). Pick your own 4.3.4 game folder." >&2; exit 2; }
done
mkdir -p "$D"
cd "$D"

if [ ! -f "$D/.maps-done" ]; then
  echo "== dbc and maps (a few minutes)"
  rm -rf "$D/dbc" "$D/maps" "$D/Cameras"
  "$X/mapextractor" -i "$C" -o "$D"
  touch "$D/.maps-done"
fi

if [ ! -f "$D/vmaps/.done" ]; then
  echo "== vmaps (10-40 minutes)"
  rm -rf "$D/Buildings" "$D/vmaps"
  mkdir -p "$D/vmaps"
  "$X/vmap4extractor" -d "$C/Data"
  "$X/vmap4assembler" Buildings vmaps
  rm -rf "$D/Buildings"
  touch "$D/vmaps/.done"
fi

if [ "${LL_MMAPS:-1}" = 0 ]; then
  echo "== monster paths: skipped (LL_MMAPS=0)"
elif [ ! -f "$D/mmaps/.done" ]; then
  echo "== monster paths on $T CPU threads (the slow part: 2-4 hours)"
  mkdir -p "$D/mmaps"
  "$X/mmaps_generator" --threads "$T" --silent \
    || { echo "building the monster paths failed; run again to finish them" >&2; exit 1; }
  touch "$D/mmaps/.done"
fi
touch "$D/.ready"
echo "== client data ready"
