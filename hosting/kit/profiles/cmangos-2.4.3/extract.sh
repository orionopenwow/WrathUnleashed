#!/bin/sh
# Server data for a CMaNGOS realm from the HOST'S OWN client (Leyline host kit, profiles cmangos-1.12.1 and
# cmangos-2.4.3: the same file in both). Runs in the extractors image with the client folder mounted read-only at
# /client and the data volume at /data. Nothing is downloaded: dbc, maps, vmaps and the monster paths (mmaps) are
# made here by the core's own tools from the files on this PC, the same steps as the core's
# contrib/extractor_scripts/ExtractResources.sh, and they never leave it. Safe to run again: finished steps are kept.
#   LL_THREADS   parallel monster-path jobs (default: all CPUs)
#   LL_MMAPS     1 (default) builds the monster paths, 0 skips them (creatures then walk in straight lines)
#   LL_CLIENT_FILES   files the client folder must have (from profile.lock, comma separated)
set -eu
X=/opt/cmangos/bin/tools
C=/client
D=/data
T="${LL_THREADS:-$(nproc)}"
have() { [ -f "$C/$1" ] || [ -f "$C/$(dirname "$1")/$(basename "$1" | tr 'A-Z' 'a-z')" ]; }
for f in $(echo "${LL_CLIENT_FILES:-Data/dbc.MPQ}" | tr ',' ' '); do
  have "$f" || { echo "No game files of this client in the folder you picked (it needs $f). Pick your own game folder of the right version." >&2; exit 2; }
done
mkdir -p "$D"

if [ ! -f "$D/.maps-done" ]; then
  echo "== dbc and maps (a few minutes)"
  rm -rf "$D/dbc" "$D/maps" "$D/Cameras"
  "$X/ad" -i "$C" -o "$D"
  touch "$D/.maps-done"
fi

if [ ! -f "$D/vmaps/.done" ]; then
  echo "== vmaps (10-30 minutes)"
  rm -rf "$D/Buildings" "$D/vmaps"
  mkdir -p "$D/vmaps"
  "$X/vmap_extractor" -d "$C/Data" -o "$D"
  "$X/vmap_assembler" "$D/Buildings" "$D/vmaps"
  rm -rf "$D/Buildings"
  touch "$D/vmaps/.done"
fi

if [ "${LL_MMAPS:-1}" = 0 ]; then
  echo "== monster paths: skipped (LL_MMAPS=0)"
elif [ ! -f "$D/mmaps/.done" ]; then
  echo "== monster paths on $T CPU threads (the slow part: 1-3 hours)"
  mkdir -p "$D/mmaps"
  cd "$X"
  "$X/MoveMapGen" --silent --configInputPath "$X/config.json" --offMeshInput "$X/offmesh.txt" \
    --workdir "$D/" --buildGameObjects --threads "$T" \
    || { echo "building the monster paths failed; run again to finish them" >&2; exit 1; }
  touch "$D/mmaps/.done"
fi
touch "$D/.ready"
echo "== client data ready"
