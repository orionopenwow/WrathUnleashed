# The cmangos-2.4.3 profile: credits and licences

This profile hosts a plain 2.4.3 realm for the 2.4.3 client on **CMaNGOS TBC**. Leyline does not make the
server, does not change it and ships none of it: this folder only tells your PC how to build and run it from its
authors' own source, and how to reach it through the Leyline relay.

| Part | By | Licence | Source |
| --- | --- | --- | --- |
| The server (mangosd, realmd, the extractors) | the CMaNGOS project | GPL-2.0 | https://github.com/cmangos/mangos-tbc |
| The world database and its installer (InstallFullDB.sh) | the CMaNGOS project | GPL-2.0 | https://github.com/cmangos/tbc-db |
| MariaDB (the database server image) | MariaDB Foundation | GPL-2.0 | https://mariadb.org |

The exact commits are pinned in `profile.lock`. Their licence texts and a `SOURCES.txt` with the commits are
copied into every image this folder builds (`/licenses`). Nothing here is relicensed: the files in this folder are
Leyline's own build recipe (MIT, like the rest of the host kit), and the programs they build stay under their
authors' licences.

## What the GPL asks, and how this folder meets it

* The server is compiled on the host's own PC from the public source at the pinned commit (`Dockerfile`, the
  `source` stage). The source is one `git clone` away for anyone the host runs it for, at the commit in
  `/licenses/SOURCES.txt`.
* The host kit ships no binaries of theirs and no modified copies of their code.
* Their licence and copyright files stay with the build (`/licenses` in each image).

## Game data

None in this folder and none downloaded by it. The world database is the project's community SQL (creatures,
quests, loot and the like, written by its contributors). The server's map data (dbc, maps, vmaps and the monster
paths) is made on the host's PC by `extract.sh` from the host's OWN 2.4.3 client folder, mounted read-only, and
never leaves it. Players use their own 2.4.3 client.

## Not ours to promise

How complete the game is on this server is up to its authors. Report problems with the server on its issue
tracker (https://github.com/cmangos/issues/issues). Problems with the host kit: Leyline.
