# The Host pack

Hosting a realm is an add-on to Leyline. The base launcher stays small. Only people who host download the
**Host pack** (the host kit's scripts, the realm tooling, the relay agent and the realm Lua/presets), and only
they need Docker.

The Host pack is **our code only**. It holds no game data and no game client. The host's own 3.3.5a game
files are read on their PC by the kit's extractor, and nothing is ever downloaded from us for that.

**Any client**: the Host page's **WHICH GAME** card hosts a realm for a client Leyline found on the PC (1.12.1,
2.4.3 and 3.3.5a for now), each built on the host's PC from its core's own source. See
[HOST-ANY-CLIENT.md](HOST-ANY-CLIENT.md).

## For hosts

1. In Leyline, open **Host**. The **HOST PACK** card says whether the pack is installed and whether a newer one is out.
2. Press **GET THE HOST PACK**. Leyline:
   1. downloads it;
   2. checks its sha256 and the refusal list;
   3. unpacks it into its own app data folder (`<app data>/Leyline/hostpack/kit`);
   4. makes that folder your host kit.
3. The card also checks **Docker**:
   * **Windows:** Docker Desktop (it sets up WSL 2).
   * **Mac:** Docker Desktop.
   * **Linux:** Docker Engine with the compose plugin, with your user in the `docker` group.

   If Docker is missing or stopped, the card says what to do and links the right page.
4. **START MY REALM** (step 3 on the page) opens the kit in a window of its own. The first start asks a few
   questions and imports the databases (5 to 20 minutes).
5. Once the realm is up, the **YOUR REALM** card shows:
   * its status from the relay (online, on the realm list, players, bots);
   * **STOP**, which keeps characters, accounts and the invite link;
   * **LOGS**, the last 200 lines of every service;
   * **COPY INVITE LINK**;
   * **NEW INVITE LINK**, after which the old link stops letting anyone new in.
6. When the catalog lists a newer pack, the card offers **UPDATE TO x**. An update replaces the kit's files
   and keeps your realm's own: `state/` (realm key, invite, logins), `.env` and `cache/`.

Without the pack, nothing changes: **CHOOSE THE KIT FOLDER…** still takes a kit you unzipped yourself, and seed
files from the website (`leyline-<realm id>.bat/.sh`) work the same way.

## On the realm list (the Leyline network)

Community realms are the front of the Leyline network: the website's `/wrath/realms`, the hub, the launcher's
Realms page and the in-game Leyline window all list them first. Our own realm is a temporary "Leyline Sample
Hangout", pinned below the featured community realms.

**What a host sets** (the launcher's Host page, card **ON THE REALM LIST**, or `setup.py listing`, or by hand in
`state/beacon.json`):
* rules tags: `blizzlike`, `boosted`, `custom`, `pvp`, `rp`, `hangout` (`bots` is set by itself when the realm runs
  bots); each profile starts with a few;
* region: `na-east`, `na-west`, `sa`, `eu`, `africa`, `me`, `asia`, `oce`, or not shown;
* language: a code like `en`, `de`, `pt-BR`;
* the player limit (shown as "12 of 40 playing");
* "Allow direct connections": off by default, and the network only advertises it when the relay operator
  turns `RELAY_ADVERTISE_DIRECT` on and the player has `p2p_hosting` on. Nothing here turns a flag on.

```
setup.py listing --tags pvp,rp --region eu --language de --max-players 80 --direct off
```
The agent sends the new text with its next heartbeat (within a minute). The core (`azerothcore`) and the build
(12340) come from the kit.

**What the listing works out itself** (`hosting/relay/wurelay/listing.py`): uptime over 24 h and 7 d from the
heartbeats, "new" (first seen in the last 7 days), a coarse region estimate (the relay's `RELAY_REGION` when the
realm's tunnel answers in under 45 ms), and the fair score: players now (diminishing), bots counted apart (at most
5 points), uptime, a small boost while new. Nothing can be bought or voted on. Staff can mark a realm **featured**
(above the sample) or **verified** (a badge) in the admin console. A realm whose tunnel drops shows offline at
once and leaves the list 6 h after its last heartbeat.

**Reports.** Players report a realm from any list (Report: the website's `/wrath/realms/report?realm=<id>`,
signed in). Staff see them in the admin console (Reports, and under each realm on Realms) and can resolve,
dismiss, hide or flag.

## How it is listed

* **The Workshop catalog** `/wrath/mods/all.json` has one project with id `mod:host-pack`, `category: "tools"`,
  `kind: "hostpack"` and `source: "packaged"`. It carries `version`, `download`, `sha256` and `size`, plus
  `torrent` (all.json gets it from `stream/leyline_net.py: add_hostpack`).
* **`/wrath/leyline/hostpack.json`** has the same data as the descriptor
  `{"format":1, name, version, download, sha256, size, torrent, info_hash}`.
* **The fallback** is the release's own `hostpack.json`:
  `https://github.com/orionopenwow/Leyline/releases/download/host-pack/hostpack.json`.

Leyline accepts a download only from `https://play.openvanilla.app/` or the `orionopenwow/Leyline` release
downloads, and only with a 64-hex sha256. Versions are `YYYY.MMDD.HHMM` (UTC), so a newer build always
compares newer.

Note for the launcher-core owner: `catalog.rs` keeps the entry, but its `kind` is not one of `ui`, `realm` or
`both`, so it is cleared. Its download is on the release, not the catalog site, so Discover shows the
entry as not installable. A "Get it on the Host page" button there would be a nice touch.

## Building and publishing (owner)

`hosting/pack/make-hostpack.py` builds the pack:

```
py -3 hosting\pack\make-hostpack.py [--version 2026.1029.1700] [--out DIR] [--upload] [--write-site]
```

* It uses the host kit's own file list and safety check (`tools/leyline-repo/hostkit.py`). That check leaves
  out owner-only tools and every host's secrets, and refuses game data, secrets and brand words. On top of it,
  the script runs the launcher's refusal list.
* It writes four files:
  * `leyline-host-pack-<v>.zip`;
  * `.zip.sha256`;
  * a single-file `.torrent` whose web seed is the release file;
  * `hostpack.json`.
* `--upload` puts them on the `host-pack` release of `orionopenwow/Leyline`, using your own `gh`. The file
  names carry the version, so an old `hostpack.json` never points at a changed file.
* `--write-site` copies `hostpack.json` to `stream/hostpack.json`. The sign-in step (`signin`) deploys it.
  This option needs `--upload`.

The Autopilot step **`hostkit`** (`hosting/kit/Publish host kit.bat`) now runs both: first the classic host-kit
zip, then the Host pack with `--upload --write-site`. After it, commit `stream/hostpack.json` and run
**`signin`**.

## Code

| Part | Where |
|---|---|
| Descriptor, install, update, keep `state/` | `launcher/src-tauri/src/host/pack.rs` |
| Docker detection and help per OS, stop, logs, new invite | `launcher/src-tauri/src/host/docker.rs`, `host.rs` |
| Download path (HTTPS or torrent, sha256, refusal list) | `launcher/src-tauri/src/p2p/transfer.rs`, `checker.rs` |
| Tauri commands | `launcher/src-tauri/src/p2p/cmds.rs` (registered in `app.rs`) |
| UI | `launcher/ui/host.js` |
| Site | `stream/leyline_net.py` |
| Builder | `hosting/pack/make-hostpack.py` |

| Tests | Where |
|---|---|
| Launcher core | `cargo test --no-default-features` |
| Builder | `python3 -m unittest hosting/tests/test_hostpack.py` |
| Site | `python3 -I stream/tests/test_leyline_net.py` |
