#!/usr/bin/env bash
# Runs one worldserver console command over SOAP (127.0.0.1:7878) and prints the answer.
#
#   sudo /srv/wrath/soap-cmd.sh "server info"
#   sudo /srv/wrath/soap-cmd.sh "announce Restart in 5 minutes"
#   sudo /srv/wrath/soap-cmd.sh "reload ale"
#
# Logs in as SOAP_USER / SOAP_PASS from /srv/wrath/signup.env (a GM level 3 account; see
# RUNBOOK step 8). Commands are written WITHOUT the leading dot, as in the console.
# The credentials go to curl through a config on stdin, so they never show up in `ps`.
# Exit code: 0 on success, 1 if the server reported a failure, 2 on usage/connection errors.

set -euo pipefail

WU_DIR="${WU_DIR:-/srv/wrath}"
[[ $# -ge 1 && -n "$1" ]] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
cmd="$*"

set -a
# shellcheck disable=SC1091
. "${WU_DIR}/signup.env"
set +a
: "${SOAP_USER:?SOAP_USER missing in signup.env}" "${SOAP_PASS:?SOAP_PASS missing in signup.env}"
url="${SOAP_URL:-http://127.0.0.1:7878/}"

xml_escape() { local s="$1"; s="${s//&/&amp;}"; s="${s//</&lt;}"; s="${s//>/&gt;}"; printf '%s' "$s"; }

# Same envelope the signup service sends: method executeCommand in namespace urn:AC.
body="<?xml version=\"1.0\" encoding=\"utf-8\"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:ns1=\"urn:AC\">
<SOAP-ENV:Body><ns1:executeCommand><command>$(xml_escape "$cmd")</command></ns1:executeCommand></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"

# curl reads its options (including the basic-auth user) from fd 3, the body from stdin.
resp="$(curl -sS --max-time 30 -K /dev/fd/3 -H 'Content-Type: text/xml; charset=utf-8' \
  --data-binary @- -w '\n%{http_code}' "$url" <<<"$body" 3<<<"user = \"${SOAP_USER}:${SOAP_PASS}\"")" \
  || { echo "could not reach SOAP at $url (is the worldserver up with AC_SOAP_ENABLED=1?)" >&2; exit 2; }

code="${resp##*$'\n'}"
xml="${resp%$'\n'*}"
# Pull <result> (success) or <faultstring> (failure) out of the reply; the text may span lines.
extract() { python3 -I -c '
import sys, xml.etree.ElementTree as ET
tag = sys.argv[1]
try:
    root = ET.fromstring(sys.stdin.read())
except ET.ParseError:
    sys.exit(0)
for el in root.iter():
    if el.tag.rsplit("}", 1)[-1] == tag and el.text:
        print(el.text.rstrip()); break
' "$1"; }

case "$code" in
  200) printf '%s' "$xml" | extract result; exit 0 ;;
  401) echo "SOAP login rejected (wrong SOAP_USER/SOAP_PASS, or the account does not exist)" >&2; exit 2 ;;
  403) echo "SOAP account exists but is below GM level 3" >&2; exit 2 ;;
  *)   echo "server answered HTTP ${code}:" >&2; printf '%s' "$xml" | extract faultstring >&2; exit 1 ;;
esac
