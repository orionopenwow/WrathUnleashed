#!/bin/sh
# Fetches the addon pack (addons.lock) and stages each addon under _pack/<AddOns name>.
# Runs in the alpine/git container started by install-gm-addons.bat; /w is this folder.
set -e
cd /w
git config --global --add safe.directory '*'
git config --global core.autocrlf false
rm -rf _pack && mkdir -p _src _pack
grep -v '^#' addons.lock | while read -r name repo commit folders; do
  [ -z "$name" ] && continue
  d="_src/$name"
  if [ ! -d "$d/.git" ] || [ "$(git -C "$d" rev-parse HEAD)" != "$commit" ]; then
    echo "  fetch   $name"
    mkdir -p "$d"; git -C "$d" init -q
    git -C "$d" remote remove origin 2>/dev/null || true
    git -C "$d" remote add origin "$repo"
    git -C "$d" fetch -q --depth 1 origin "$commit"
    git -C "$d" checkout -q --force FETCH_HEAD
  else
    echo "  ok      $name"
  fi
  case "$folders" in
    .:*) dest="${folders#.:}"; mkdir -p "_pack/$dest"; cp -r "$d/." "_pack/$dest/"; rm -rf "_pack/$dest/.git" ;;
    *)   for f in $d/$folders; do [ -d "$f" ] && cp -r "$f" "_pack/$(basename "$f")"; done ;;
  esac
done
ls _pack | wc -l | xargs echo "Addons staged:"
