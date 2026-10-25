#!/bin/sh
# Fetches AzerothCore (mod-playerbots fork) and every module at the commits in sources.lock.
# Runs inside the alpine/git container started by "Build custom realm.bat"; /w is realm\custom.
# Safe to run again: anything already at the right commit is left alone.
set -e
cd /w
git config --global --add safe.directory '*'
git config --global core.autocrlf false
fetch() { # dir repo commit
  if [ -d "$1/.git" ] && [ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" = "$3" ]; then
    echo "  ok      $1"; return
  fi
  echo "  fetch   $1"
  mkdir -p "$1"
  git -C "$1" init -q
  git -C "$1" remote remove origin 2>/dev/null || true
  git -C "$1" remote add origin "$2"
  git -C "$1" fetch -q --depth 1 origin "$3"
  git -C "$1" checkout -q --force FETCH_HEAD
}
# patches/<name>.patch: a fix the pinned commit still needs against this core (e.g. a hook whose
# signature changed upstream). Applied once; an already-applied patch is left alone.
patch_dir() { # dir name
  p="patches/$2.patch"
  [ -f "$p" ] || return 0
  if git -C "$1" apply --check -R "$(pwd)/$p" 2>/dev/null; then
    echo "  patched $2 (already)"
  else
    git -C "$1" apply "$(pwd)/$p" && echo "  patched $2"
  fi
}
grep -v '^#' sources.lock | while read -r name repo branch commit; do
  [ -z "$name" ] && continue
  if [ "$name" = core ]; then
    fetch acore "$repo" "$commit"; patch_dir acore core
  else
    fetch "acore/modules/$name" "$repo" "$commit"; patch_dir "acore/modules/$name" "$name"
  fi
done
echo "Sources ready."
