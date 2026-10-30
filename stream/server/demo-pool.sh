#!/usr/bin/env bash
# Leyline guest pass ("Try Leyline in the Goldshire Inn"): the operator's pool of guest accounts.
# Run as root on the server, yourself (nothing runs this for you):
#
#   bash /srv/wrath/stream/demo-pool.sh make <count> <TemplateCharacter>
#        Makes accounts LYDEMO01..LYDEMO<count> (skips ones that exist), copies the template character
#        into each one as Visitoraa, Visitorab, ... (.pdump write / .pdump load), and lists them in
#        /srv/wrath/portal/demo-pool.txt ("<ACCOUNT> <Character>" per line; no passwords).
#        Each account is created with a throwaway random password that is never shown or stored: the
#        website gives the account a fresh random password every time a pass opens and again when it
#        ends, so nobody (you included) needs to know it.
#   bash /srv/wrath/stream/demo-pool.sh on       WU_GUEST_DEMO=1 in portal.env, wu-portal recreated
#   bash /srv/wrath/stream/demo-pool.sh off      WU_GUEST_DEMO=0, every open pass ended (guests logged out)
#   bash /srv/wrath/stream/demo-pool.sh list     the pool file
#
# Before "make":
#   1. ov_demo.lua is on the realm (realm/custom/lua_scripts, deployed with the other ov_*.lua scripts;
#      then soap-cmd.sh "reload ale"). This script checks that it answers.
#   2. Make the template yourself in the game: a new level-1 human on an ordinary account (not a GM),
#      walked into the Lion's Pride Inn in Goldshire, logged out there. Its gear and bags are what every
#      guest gets, so keep it plain. Note its name.
#   3. Streaming is set up (stream-up.sh) with the slice that has the "goldshire-inn" tier.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
POOL="$WU/portal/demo-pool.txt"
DUMP=/tmp/ov-demo-template.dump     # inside the world server's container
PREFIX=LYDEMO

letters() {  # 1 -> aa, 2 -> ab, ... 26 -> az, 27 -> ba
  local n=$(( $1 - 1 )) a=abcdefghijklmnopqrstuvwxyz
  printf '%s%s' "${a:$(( n / 26 % 26 )):1}" "${a:$(( n % 26 )):1}"
}

cmd=${1:-}
case "$cmd" in
  make)
    count=${2:-}; template=${3:-}
    [[ "$count" =~ ^[0-9]+$ ]] && [ "$count" -ge 1 ] && [ "$count" -le 99 ] || die "usage: demo-pool.sh make <count 1-99> <TemplateCharacter>"
    [[ "$template" =~ ^[A-Za-z]{2,12}$ ]] || die "the template character's name: letters only"
    probe=$(soap "ovdemo end ${PREFIX}00" 2>&1 || true)
    case "$probe" in *ovdemo*) echo "  ov_demo.lua answers" ;; *) die "ov_demo.lua is not loaded (answer: ${probe:0:200}). Deploy it, then soap-cmd.sh \"reload ale\"" ;; esac
    log "Template $template -> $DUMP (in the world server)"
    soap "pdump write $DUMP $template"
    touch "$POOL"; chmod 644 "$POOL"
    for i in $(seq 1 "$count"); do
      acct=$(printf '%s%02d' "$PREFIX" "$i")
      char="Visitor$(letters "$i")"
      if grep -q "^$acct " "$POOL"; then echo "  $acct: already in the pool"; continue; fi
      pw=$(openssl rand -hex 8)
      out=$(soap "account create $acct $pw" 2>&1 || true)
      unset pw
      case "$out" in *exist*) echo "  $acct: account exists" ;; *) echo "  $acct: account made" ;; esac
      out=$(soap "pdump load $DUMP $acct $char" 2>&1 || true)
      echo "  $acct: $char: ${out:0:160}"
      echo "$acct $char" >> "$POOL"
    done
    echo
    echo "Pool: $(grep -c . "$POOL") passes in $POOL. Check each character loaded (above), then:"
    echo "  bash $ST/demo-pool.sh on"
    ;;
  on)
    [ -s "$POOL" ] || die "$POOL is empty: run demo-pool.sh make first"
    [ -f "$WU/portal/demo.py" ] || die "$WU/portal/demo.py missing: run stream-up.sh (it installs it next to wrath_portal.py)"
    kv_set "$WU/portal.env" WU_GUEST_DEMO 1
    recreate_portal || die "wu-portal did not come back (docker logs wu-portal)"
    echo "Guest passes are on: https://$UPSTREAM/wrath?demo=1  (preview of the section: https://$UPSTREAM/wrath/demo)"
    ;;
  off)
    kv_set "$WU/portal.env" WU_GUEST_DEMO 0
    recreate_portal || die "wu-portal did not come back (docker logs wu-portal)"
    if [ -f "$POOL" ]; then
      while read -r acct _; do
        [[ "$acct" =~ ^$PREFIX[0-9A-Z]+$ ]] || continue
        soap "ovdemo end $acct" >/dev/null 2>&1 || echo "  $acct: ovdemo end failed (the pass still ends by itself)"
      done < "$POOL"
    fi
    echo "Guest passes are off; open passes ended."
    ;;
  list)
    cat "$POOL" 2>/dev/null || echo "(no pool yet)"
    ;;
  *)
    sed -n '2,16p' "$0"; exit 2 ;;
esac
