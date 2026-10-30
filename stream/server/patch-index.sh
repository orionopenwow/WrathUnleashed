#!/usr/bin/env bash
# After a new browser client build is uploaded to /srv/wrath/stream/www: make its page take the
# login from /__env.js again (stream-up.sh does the same). "Make mini slice.bat" runs it.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/stream-lib.sh"
[ -f "$ST/www/index.html" ] || die "$ST/www/index.html missing"
patch_index
# Forever UI's files back into the new client's boot list, when the server has it (fui-install.sh).
if [ -f "$ST/fui-install.sh" ]; then bash "$ST/fui-install.sh" reapply-www || echo "  WARNING: Forever UI's files are not in the boot list: they load on demand"; fi
# The catalog mods' addons too (mods-install.sh).
if [ -f "$ST/mods-install.sh" ]; then bash "$ST/mods-install.sh" reapply-www || echo "  WARNING: the mods' addons are not in the boot list: they load on demand"; fi
grep -q 'src="/__env.js"' "$ST/www/index.html" && echo "  index.html loads /__env.js"
