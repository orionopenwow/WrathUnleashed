# Repo map

What every top-level folder is for, as of 2026-10-30. The owner's direction that day: Leyline is the mod launcher
and the P2P realm network where anyone can host a realm in one click, from the browser or the desktop. Our own
realm is only the temporary **Dalaran Hangout** (3.3.5a), and it gets our client additions as we go. All tools
we made are kept; the ones that are not part of the core today are in `labs/`.

- **Core**: part of Leyline today.
- **Ops**: our own running and shipping tools (Autopilot, deploys, GitHub housekeeping). Kept, not public.
- **Labs**: kept for later, not used by anything live (`labs/README.md`).
- **Public**: copied into the public Leyline repo by `tools/leyline-repo/export.py` (its `ALLOW` list).

## Top level

| Path | What it is | Kind | Public |
|---|---|---|---|
| `launcher/` | The Leyline desktop launcher (Tauri 2): game clients, mods, realms, hosting, themes, self-update. `launcher/README.md` | Core | yes |
| `hosting/` | The P2P/relay network and one-click hosting (see below) | Core | partly |
| `stream/` | The website, portal and hub on our server, and the browser game page layer (see below) | Core | a few files |
| `client/` | Our browser client for the Dalaran Hangout: `get-source.sh`, the CI build, `patches/` (the web port, the newest change, smooth frames; older series in `patches/history/`), `dev/` (rebuild and boot-check helpers) | Core | no |
| `play/` | Local play: `Play 3.3.5a in browser.bat` and the test-build launchers (smooth frames, nameplates, Azeroth Survivors, newest test build) | Core (test bats: experimental, in place) | no |
| `realm/` | The Dalaran Hangout realm: AzerothCore 3.3.5a in Docker, custom modules and Lua scripts (`custom/`), profiles, SQL, the brand and sampler switches, server passes | Core | two scripts |
| `mods/` | The mod package format (`SPEC.md`), the checker `wu-mod.py`, the template, the catalog and categories | Core | `SPEC.md` |
| `addons/` | Our client addons for the Hangout (OVArmory, OVQoL, MiniGM) and the GM addon fetcher | Core | no |
| `docs/` | Feature docs (hub, hosting, P2P, social, themes, modes, workshop, admin console...); `docs/leyline/` is the player and host guide served at `/wrath/docs`; `docs/history/` old launch notes | Core | `docs/leyline/` |
| `tools/` | Ops tools (see below) | Ops | no |
| `gmconsole/` | The owner-only GM console on the server (Autopilot step `gm`) | Ops | no |
| `server/` | Our server's deploy kit: Caddy, the realm deploy and rollback, backups, sign-up service, runbook | Ops | no |
| `control/` | Autopilot's state files (`autopilot.json`, `claude-status.json`, `last-run.json`), read and written by `tools/control/control.py` | Ops | no |
| `players/` | The old tester package (`Make player package.bat` builds the zip from `play/` and `addons/`) | Experimental, in place | no |
| `labs/` | Paused tools and plans, kept for later: the 1.12 client repo maker, the 1.12 login carry-over, the sandbox roadmap. `labs/README.md` | Labs | no |
| `.github/workflows/` | CI that runs here: hosting tests, realm images, hub index, scout. Mirrors in `tools/github-workflows/` | Ops | no |

## Root files

| File | What it is |
|---|---|
| `README.md` | This repo in short |
| `UPDATE.bat`, `UPDATES-PENDING.txt`, `UPDATES-DONE.txt` | The update queue: Claude adds steps, `UPDATE.bat` or the control window runs them |
| `WrathUnleashed Control.bat` | The control window with Autopilot (`tools/control/control.py`) |
| `Turn on Autopilot (start with Windows).bat` | Starts the control window at sign-in |
| `Ship WrathUnleashed.bat` | Saves the repo to the private GitHub repo (Autopilot step `ship`) |
| `Ship the Leyline launcher.bat`, `Turn on launcher updates.bat`, `Turn on GitHub builds.bat` | Launcher release: update key, save, public repo, tag |
| `Set up automatic deploys.bat` | One time: the deploy key GitHub uses for realm scripts |
| `Play WotLK (one click).bat` | Local realm and browser client on this PC (Docker, your own game folder) |
| `Install Forever UI.bat` | Puts Forever UI into your own game folder for the browser client |
| `Make player package.bat` | Builds `players/WrathUnleashed-Player.zip` (experimental, in place) |

## hosting/

| Path | What it is | Public |
|---|---|---|
| `kit/` | The host kit: the `leyline` command, `Host a Leyline realm.bat`, compose files, host agent and self-check (`tools/wuhost`), shared network code (`tools/wunet`), profiles for other clients (1.12.1, 2.4.3; 4.3.4 hidden) | yes |
| `relay/` | The relay: tunnels for hosts, join page, realm listing (Beacons), per-IP limits; `Deploy relay.bat` (Autopilot `relay`) | yes |
| `discord/` | The Discord bridge | yes |
| `hangout/` | The Dalaran Hangout as a Beacon on Leyline (Autopilot `hangout`, `hangout-off`) | no |
| `pack/` | `make-hostpack.py`: the host kit as a versioned download for the launcher's Host page | no |
| `mesh-sim/` | The mesh simulator (realm list and relays without us), used by `tests/test_mesh.py`. Experimental, in place | no |
| `site/` | The join page and the community-record schema | no |
| `server/` | `set-realm-address.sh` for hosted realms | no |
| `tests/` | Tests for all of the above | yes |
| `README.md`, `INSTALL-OPERATE.md` | Design and the host guide | yes |
| `RESULTS.md`, `STATUS-2026-10-29.md` | Test results and status notes | no |

## stream/

| Path | What it is |
|---|---|
| `wrath_portal.py` | The website's sign-in bridge and router; loads the modules beside it |
| `hub.py`, `hub_rank.py`, `hub/` | The Leyline hub and its community index |
| `hostflow.py`, `hostpack.json` | One-click hosting from the browser (`/wrath/host`) |
| `network.py`, `leyline_net.py`, `links.py` | The realm browser and listing, the P2P/torrent and mesh flags (all OFF), short share links |
| `social.py`, `herokey_sso.py`, `ed25519_pure.py` | Friends and messages, Hero Key sign-in for Beacons |
| `workshop.py`, `creations.py`, `projects.py`, `modes.py`, `modes_data.py`, `playmodes.py`, `playmodes.json` | Mods Workshop, creations, linked projects, the Modes hub and play modes |
| `armory.py`, `admin.py`, `docs.py` | Web armory, the admin console, the docs pages |
| `demo.py` | The guest demo (OFF unless `WU_GUEST_DEMO=1`). Experimental, in place |
| `www-files/` | The game page, sign-in page and site art |
| `fui-web/` | The in-game UI addon layer (Forever UI web, WrathUnleashedUI, the Leyline window) |
| `server/` | Scripts that run on our server: stream up/down, slices, game data switch, overlays |
| `slices/`, `lua/`, `sql/` | Streamed-file manifests, slice helpers, stream accounts SQL |
| `fastloop.sh`, `*.bat` | The deploy steps (Autopilot `client`, `signin`, `page`, `foreverui`, `slice`, `slice-sampler`, `gamedata-*`) |
| `wenilla-host-stream.patch` | The page host's streaming changes |
| `tests/` | Tests for the portal, hub, page and UI addons |

## tools/

| Path | What it is |
|---|---|
| `control/` | The control window and Autopilot (`control.py`: its `STEPS` name every step it can run) |
| `leyline-repo/` | The public Leyline export (`export.py`, `Update Leyline repo.bat`, Autopilot `leyline`) and the host-kit zip |
| `hub-index/` | Hub index and scout (GitHub workflows `hub-index.yml`, `scout.yml`), hub thumbnails (Autopilot `thumbs`) |
| `github-workflows/` | The workflow files `Turn on GitHub builds.bat` installs (here and in the Leyline repo) |
| `github-builds/`, `github-cleanup/`, `github-deployments/` | GitHub: turn on builds, why a build failed, old releases and packages, old deployments |
| `launcher-updates/` | The launcher's update signing key (`Turn on launcher updates.bat`) |
| `discord-leyline/` | The Leyline Discord server's channels and art |
| `fresh-history/` | One-commit fresh history for the Leyline repo |
| `ov-rename/` | Rename the older Python launcher's repo and land its branch (Autopilot `ovrename`, `ovland`) |
| `cleanup/` | Remove files a change took out (`REMOVE.txt`, Autopilot `remove-files`) |
| `art/` | Share card and launcher screenshot renderers |
| `creator-api/` | Writes `docs/CREATOR-API.md` and `docs/creator-api.html` from the Modes API |
| `playerbots-specs/` | Turns playerbots talent specs into the realm's env lines |

## Experimental, in place

These are prototypes that live scripts, tests or the client build still point at, so they stay where they are:
the extra realm profiles (`realm/profiles/brawl.env`, `progression.env`, `casual.env`, with `Make it Brawl.bat`,
`Make it Main.bat` and their SQL; `server/deploy.sh` and the host kit apply the same SQL), `hosting/mesh-sim/`,
the P2P/torrent and mesh flags (OFF), `stream/demo.py` (OFF), the test-build launchers in `play/`, and `players/`.
Hordes of Azeroth lives only on its own branch.

## Rules of thumb

- Anything an Autopilot step runs (`STEPS` in `tools/control/control.py`, `UPDATE.bat`) stays at its path. Moving
  one means updating `control.py`, `UPDATE.bat`, the .bat files that call it, `stream/fastloop.sh`, the server
  scripts, the workflows and `tools/leyline-repo/export.py`.
- New experiments go in `labs/<name>/` with a row in `labs/README.md`.
- Nothing in `labs/` is exported, run by Autopilot or used by CI.
