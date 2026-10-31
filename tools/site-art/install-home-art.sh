#!/bin/sh
# The server half of "Publish home screenshots.bat" (the Autopilot step "homeart"): put the new Home screenshots in
# /srv/wrath/portal/art/home (wu-portal serves that folder at /wrath/art/home/, read on every request: no restart).
# Backs up what was there (art-backups/home-<time>, the last five kept) and puts it back if the site does not
# answer with the new list. Run from the unpacked upload: ./art/ holds the .webp files and home.json.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
A=/srv/wrath/portal/art
B=/srv/wrath/portal/art-backups
S=$(date +%Y%m%d-%H%M%S)
[ -f "$HERE/art/home.json" ] || { echo "ERROR: no home.json in the upload" >&2; exit 1; }
python3 -c 'import json, sys; j = json.load(open(sys.argv[1])); assert isinstance(j.get("slides"), dict)' "$HERE/art/home.json" \
  || { echo "ERROR: home.json is not a list of slides" >&2; exit 1; }
mkdir -p "$A" "$B"
rm -rf "$A/home.new" "$A/home.old"
mkdir -p "$A/home.new"
# only the pictures and the list, nothing else from the upload
find "$HERE/art" -maxdepth 1 -type f \( -name '*.webp' -o -name home.json \) -exec install -m 644 {} "$A/home.new/" \;
chmod 755 "$A/home.new"
if [ -d "$A/home" ]; then cp -a "$A/home" "$B/home-$S"; mv "$A/home" "$A/home.old"; fi
mv "$A/home.new" "$A/home"
sleep 1
if curl -fs -m 20 https://play.openvanilla.app/wrath/art/home/home.json | grep -q '"slides"'; then
  rm -rf "$A/home.old"
  ls -1t "$B" | grep '^home-' | tail -n +6 | while read -r d; do rm -rf "$B/$d"; done
  echo "  $(find "$A/home" -name '*.webp' | wc -l) screenshots -> $A/home (backup: $B/home-$S)"
  echo "HOMEART OK"
else
  rm -rf "$A/home"
  if [ -d "$A/home.old" ]; then mv "$A/home.old" "$A/home"; fi
  echo "ERROR: https://play.openvanilla.app/wrath/art/home/home.json did not answer with the new list; the old screenshots are back." >&2
  exit 1
fi
