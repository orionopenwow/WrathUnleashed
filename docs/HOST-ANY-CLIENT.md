# Host any client

Leyline's host kit hosts a realm for any client the launcher finds on the host's PC: 1.12.1, 2.4.3, 3.3.5a and
4.3.4 today, 5.4.8 not yet (see below). One click on the launcher's Host page (or `leyline host`, or
"Host a Wrath realm.bat"), and the realm shows on the Leyline realm list with the client it needs.

How every profile works, whatever the client:

* **The server is built on the host's own PC** from its authors' public source, at a commit pinned in the kit.
  Leyline ships no server binaries and changes none of their code.
* **The world database is the core's own community SQL**, pinned by a git commit or by the sha256 of the
  project's release file.
* **The server data (dbc, maps, vmaps, monster paths) is made from the host's OWN client** of that version,
  mounted read-only. Nothing of the game is downloaded and nothing leaves the PC. Players use their own client.
* **Nothing is published on the host's network**: the realm talks out to the relay, players come in through it.
  Accounts are made on the join page; the password never leaves the player's browser.

No core here is built from leaked or decompiled code, and none that ships client files.

## The cores

| Client | Profile | Core (licence) | Pinned commit | Database | Server data from | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1.12.1 (5875) | `cmangos-1.12.1` | [CMaNGOS Classic](https://github.com/cmangos/mangos-classic) (GPL-2.0) | `5731249195520323cb5fb9aa29761d4f033272ce` (2026-10-28) | [classic-db](https://github.com/cmangos/classic-db) in git, `603ece10…` (2026-10-25), the project's `InstallFullDB.sh` | the core's `ad`, `vmap_extractor`, `vmap_assembler`, `MoveMapGen` | **implemented** |
| 2.4.3 (8606) | `cmangos-2.4.3` | [CMaNGOS TBC](https://github.com/cmangos/mangos-tbc) (GPL-2.0) | `37767e954241e346453260b8bc8c1fb2e2afdf7d` (2026-10-28) | [tbc-db](https://github.com/cmangos/tbc-db) in git, `1c54acd2…` (2026-10-26), `InstallFullDB.sh` | the same tools | **implemented** |
| 3.3.5a (12340) | `main`, `brawl`, `progression`, `dalaran` | [AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) (its own licence) | `realm/custom/sources.lock` | AzerothCore's own | AzerothCore's `map_extractor` | live (the kit's default) |
| 4.3.4 (15595) | `tcpp-4.3.4` | [TrinityCore 4.3.4, The Cataclysm Preservation Project](https://github.com/The-Cataclysm-Preservation-Project/TrinityCore) (GPL-2.0) | `b061f46ef86f84f713ea3956b2318383e0b71278` (2026-10-25) | TDB 434.22011 release file, sha256 **TODO(owner)**; the world server's own updater (`--update-databases-only`) | the core's `mapextractor`, `vmap4extractor`, `vmap4assembler`, `mmaps_generator` | **implemented, gated** on the owner pinning the database file's sha256 |
| 5.4.8 (18414) | none yet | candidate: [SkyFire 5.4.8](https://github.com/ProjectSkyfire/SkyFire_548) (GPL-3.0) | — | SFDB release 26 (GitHub lists its sha256: `d12ba9ecad381f3b5460612af2a172cd373afdd796c289e2ccc11315db21dd5f`) | the core's TrinityCore-style tools | **documented only** |

Each was checked in its own repository on 2026-10-29: active (commits this week), licence file present, the
database is the project's community SQL, and the extractors read a local client folder.

### Feasibility per profile (estimates: no C++ is compiled on the build machine; CI or a host's PC builds)

| Profile | First build | Disk (images + build cache) | Server data from the client | Database first load | Runs on |
| --- | --- | --- | --- | --- | --- |
| `cmangos-1.12.1` | 40-90 min (4 CPUs) | about 5 GB, 1.5 GB after `docker builder prune` | 30-60 min, plus 1-3 h for monster paths (`LL_MMAPS=0` skips them) | 5-15 min | 4 GB RAM |
| `cmangos-2.4.3` | 40-90 min | about 5 GB | 40-70 min, plus 2-3 h for monster paths | 5-15 min | 4 GB RAM |
| `tcpp-4.3.4` | 60-150 min | about 8 GB | 40-90 min, plus 2-4 h for monster paths | 10-20 min | 6 GB RAM |

### Why these cores

* **1.12.1: CMaNGOS Classic over VMaNGOS.** Both are maintained and GPL-2.0. CMaNGOS keeps its whole world
  database in git, so the kit pins it by a commit and builds without trusting an unchecksummed download; it also
  shares one recipe with the 2.4.3 profile. VMaNGOS (https://github.com/vmangos/core) is the stronger 1.12 core
  for content and progression; its database comes as release files. The paused Hordes branch already builds a
  VMaNGOS fork (`wuhost/vmangos.py`), so a `vmangos-1.12.1` profile is a small follow-up when the owner wants it.
* **2.4.3: CMaNGOS TBC.** The maintained 2.4.3 core; same project, same tools.
* **4.3.4: The Cataclysm Preservation Project's TrinityCore.** The maintained continuation of TrinityCore's
  4.3.4 branch (TrinityCore itself moved on to newer clients). `cmangos/mangos-cata` was last changed in 2018.
* **5.4.8: no profile yet.** Excluded: `Legends-of-Azeroth/Legends-of-Azeroth-Pandaria-5.4.8` and the
  `alexkulya/pandaria_5.4.8` code it descends from: unclear provenance, and their READMEs link client executables
  and extracted game data for download. SkyFire 5.4.8 is acceptable (GPL-3.0, derived from TrinityCore and
  MaNGOS, active in 2026) but not implemented here: it needs Boost 1.91 and OpenSSL 4 built from source inside the
  image (no distribution ships them yet), it has no automatic database updater, its database carries in-game shop
  tables that must be checked switched off (no money, ever), and how much of the game works on it is limited. A
  decision for the owner.

## How a host uses it

* **Launcher**: Host page → **WHICH GAME** lists the realms the kit can run, the ones a client on this PC can play
  first, with that client's folder filled in → START MY REALM. The choice is kept in the kit
  (`state/launcher-host.json`) and handed to the kit's script.
* **Mac / Linux**: `WU_PROFILE=cmangos-2.4.3 WU_CLIENT_DIR=~/Games/2.4.3 bash leyline host` (or answer the
  question).
* **Windows**: "Host a Wrath realm.bat" lists the profiles; or set `WU_PROFILE` and `WU_CLIENT_DIR` first.

Then, once: the server images build (the slow part, kept afterwards), the server data is made from the client,
the databases load, the realm connects to the relay. The realm list shows its core and build; the join page and
the launcher's Realms page ("Only realms my clients can play") tell players which client they need.

## Layout (for maintainers)

```
hosting/kit/profiles/
  host-profile.sh               the steps on Mac / Linux (sourced by host-wrath-realm.sh)
  Host a profile realm.bat      the same on Windows (called by Host a Wrath realm.bat)
  pick-compose.bat              which compose file Check / Stop / Realm tools use
  <core>-<version>/
    profile.lock                LL_* pins: core repo + commit, database commit or URL + sha256, build, image name
    Dockerfile                  stages: source (pinned, licences kept), build, server, extractors, db-import
    docker-compose.<id>.yml     realm-db, realm-db-import, realm-logon, realm-world, wu-agent; nothing published
    extract.sh                  reads /client (read-only), writes /data, downloads nothing
    db-import.sh / run-server.sh   the core's own installer / updater; config from the core's .conf.dist
    NOTICE.md                   credits and licences
hosting/kit/tools/wuhost/cores.py    the profiles' facts (core, build, databases, listing tags)
hosting/kit/tools/wuhost/coredb.py   accounts, GM rights, realm address and status per core
launcher/src-tauri/src/host/profiles.rs   the launcher's table (tests keep it in step with cores.py)
```

Account glue: the relay sends AzerothCore's form (salt and verifier, 32 little-endian bytes, made in the
player's browser). TrinityCore 4.3.4 stores the same bytes. CMaNGOS stores upper-case hex of the big-endian
number and sends the salt without leading zeros, so every salt Leyline draws has a non-zero top byte (the join
pages and `wunet/srp6.new_salt`), and the glue refuses one that does not. The test vector is CMaNGOS's own sample
account from `sql/base/realmd.sql`. The CMaNGOS import deletes those sample accounts (their passwords are public).

Adding a profile: a new folder with the files above, an entry in `cores.py` and in `profiles.rs`, then
`python3 -m unittest discover -s hosting/tests` and `cargo test --no-default-features --lib`.

## Risks

* **Untested builds.** The Dockerfiles follow each project's own build and install steps but have not been
  compiled here; the first CI or host build may need a package name fixed (Boost runtime libraries, the MySQL
  client library for TrinityCore).
* **CMaNGOS's installer is driven without questions** (`-InstallAll` on the first run only, then `-World` /
  `-UpdateCore`). A future change to its command line would stop the import with a clear error, not lose data.
* **4.3.4 needs the owner's sha256** before it builds (TODO(owner) in `profile.lock`). The 4.3.4 client may
  also need its own launch options on some setups; the core's client patchers are not built or used.
* **Monster paths** take hours on small PCs; `LL_MMAPS=0` starts the realm without them.
* **Game completeness** is up to each core's authors.
