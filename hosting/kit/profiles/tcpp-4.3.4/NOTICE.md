# The tcpp-4.3.4 profile: credits and licences

This profile hosts a plain 4.3.4 realm for the 4.3.4 client on **TrinityCore**, the 4.3.4 fork kept by The
Cataclysm Preservation Project. Leyline does not make the server, does not change it and ships none of it: this
folder only tells your PC how to build and run it from its authors' own source, and how to reach it through the
Leyline relay.

| Part | By | Licence | Source |
| --- | --- | --- | --- |
| The server (worldserver, authserver, the extractors) | TrinityCore contributors, The Cataclysm Preservation Project | GPL-2.0 | https://github.com/The-Cataclysm-Preservation-Project/TrinityCore |
| The world and hotfix databases (TDB 434.22011) | the same project | GPL-2.0 | that repository's releases (`profile.lock`) |
| MariaDB (the database server image) | MariaDB Foundation | GPL-2.0 | https://mariadb.org |

The exact commit and release file are pinned in `profile.lock`. The licence text (`COPYING`), `AUTHORS` and a
`SOURCES.txt` with the commit are copied into every image this folder builds (`/licenses`). Nothing here is
relicensed: the files in this folder are Leyline's own build recipe (MIT, like the rest of the host kit), and the
programs they build stay under their authors' licences.

## What the GPL asks, and how this folder meets it

* The server is compiled on the host's own PC from the public source at the pinned commit (`Dockerfile`, the
  `source` stage). The source is one `git clone` away for anyone the host runs it for.
* The host kit ships no binaries of theirs and no modified copies of their code.

## Game data

None in this folder and none downloaded by it. The databases are the project's community SQL. The server's map
data (dbc, maps, vmaps and the monster paths) is made on the host's PC by `extract.sh` from the host's OWN 4.3.4
client folder, mounted read-only, and never leaves it. Players use their own 4.3.4 client. The core's own
client-patching tools (`src/tools/client_*`, `connection_patcher`) are not copied into any image and never
touch the player's client.

## Not ours to promise

How complete the game is on this server is up to its authors. Report problems with the server on its issue
tracker (https://github.com/The-Cataclysm-Preservation-Project/TrinityCore/issues). Problems with the host kit:
Leyline.
