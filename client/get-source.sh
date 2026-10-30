#!/usr/bin/env bash
# Get the WrathUnleashed browser client's source: benilla-wotlk (Apache-2.0/MIT, no Blizzard
# code) at the pinned commit, with our web port applied. Run from this folder:
#   bash get-source.sh            -> ./benilla-wotlk, ready to build (see README.md)
set -euo pipefail
cd "$(dirname "$0")"
PIN=b9a49428
if [ ! -d benilla-wotlk/.git ]; then
  git clone https://github.com/Onixaz/benilla-wotlk benilla-wotlk
fi
cd benilla-wotlk
git fetch origin
git checkout -B wrathunleashed "$PIN"
git apply --whitespace=nowarn ../../wotlk-web-port-wip.patch
git add -A
git -c user.name="WrathUnleashed" -c user.email="wrathunleashed@localhost" \
  commit -qm "WrathUnleashed web port (from wotlk-web-port-wip.patch)"
echo "Ready: $(pwd) on branch wrathunleashed."
