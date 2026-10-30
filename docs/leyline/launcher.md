# Launcher

The Leyline Launcher is a desktop app for Windows, macOS and Linux, built with Tauri. Its window says "Leyline". It uses the game client you already have: it never downloads, copies or ships game files. It has no telemetry and no accounts.

Version 0.3 adds every client build, every server type and self-updates. See [Getting a build](#getting-a-build).

## What it does

| Page | What you can do |
|---|---|
| **Home** | Pick a client and a realm, then PLAY. Or play Wrath in the browser. |
| **Game clients** | Add a client folder you already have: 1.12.1 (5875), 2.4.3 (8606), 3.3.5a (12340), 4.3.4 (15595) or 5.4.8 (18414). Leyline reads the build from the game's .exe and checks the install is complete. Any other build shows as "other": it can play realms, but gets no mods. Leyline never downloads a client. |
| **Discover** | Browse the Workshop: categories, search, credits, links to each project's page, source and author. Install a mod into the client you pick. |
| **My Mods** | See what is installed in each client. One click to update or remove; turn mods off and on; UPDATE ALL. Drop a .zip, an addon folder, a .MPQ patch or a native mod (.dll, .asi, after a one-time OK) to add your own. |
| **Realms** | The official realm and every community Beacon, with their server (AzerothCore, TrinityCore, CMaNGOS, vMaNGOS, MaNGOS), build, status and player counts. PLAY picks one of your clients of the right build, sets its realm address and starts the game, or says which client is missing. Join a private realm with its invite link. |
| **Host** | Run your own realm on your PC through the relay, step by step. |
| **Settings** | Wine (macOS and Linux run Windows clients through it), updates (Stable or Beta), where your data lives. |

## Mods

Discover reads the Workshop list at `https://play.openvanilla.app/wrath/mods/all.json` (see `mods/all-json.md`). It shows the same projects as the [Workshop](https://play.openvanilla.app/wrath/mods): packaged mods, which Leyline can install, and community links, which you get from their own page.

- **Per client.** Every install goes into one client folder. A mod made for the other build is flagged and can't be installed. "Only mods for this client" hides them.
- **Where files go.** UI addons go to `Interface\AddOns\<Name>`. A client patch goes to a free `Data\patch-<X>.MPQ` slot (4 to 9, then A to Z; the game's own patch files are never touched). A mod package's realm half (`realm/`) is not for a client and is left out.
- **Checks.** A download is capped at 60 MB and its sha256 must match the catalog. Every zip and folder is checked with the same UI rules as `wu-mod.py` and the website's addon drop: a `<Name>/<Name>.toc` with the client's Interface number (11200 for 1.12, 20400 for 2.4.3, 30300 for 3.3.5a, 40300 for 4.3.4, 50400 for 5.4.8), every file the TOC lists present, `<Script>` and `<Include>` pointing at real files, addon file types only, no game data (checked by extension and by the file's first bytes), 10 MB a file, 50 MB in all, 2000 files. A mod package may not carry `.MPQ` files: a patch comes on its own.
- **Contained.** Zips are unpacked into a staging folder inside the client first, with zip-slip, symbolic-link, password and size checks. Nothing is ever written outside the client folder, or through a link that leads out of it. An addon folder Leyline did not install is never overwritten.
- **Clean removal.** Each client keeps a list of every file Leyline put in it, in `Leyline\mods.json` inside the client folder. Removing a mod removes exactly those files, and the last removal takes the `Leyline` folder away too. Files you added to an addon's folder yourself are kept, and the game's own saved settings in `WTF` stay.
- **Off and on.** A turned-off mod's files wait in `Leyline\disabled\` inside the client, where the game does not look.
- **Updates.** When the Workshop has a newer version of an installed mod, My Mods shows "Update available" and an UPDATE button.

Decided for now: every mod is allowed, with no review queue and no code signing. Nobody but you decides whether a mod is safe, so only install mods you trust.

## Realms

The Realms page lists the official realm first, then the Beacons from the relay's listing (`https://relay.openvanilla.app/api/listing/realms.json`), with their status, players and bots counted apart, and house rules.

- **PLAY** writes the client's `realmlist.wtf` (and the `realmList` line of `WTF\Config.wtf` on 3.3.5a, when it has one), then starts the game. Your original files are kept as `.leyline-backup` the first time.
- **A Beacon** is reached through the relay. The relay gives each realm its own login port, so its realmlist is `relay.openvanilla.app:<port>`. The listing carries that address; when it doesn't, Leyline asks the relay (`/api/realms/<id>`). The relay's public ports 40000 to 40999 must be open for this. The relay's setup opens them in its firewall; a cloud firewall in front of the box must allow them too.
- **Your account** on a Beacon is made on its join page in your browser ("Make an account"), so your password never leaves the browser.
- **A private realm**: paste its invite link under "A private realm". Leyline does what opening the link does (the relay's "knock" for this PC's address, valid 24 hours) and points your client at the realm.
- **BACK TO WRATH** points the client at the official realm again. **MY OWN REALMLIST** puts back the files you had before Leyline.

Where the realm address goes: 1.12 reads `realmlist.wtf` next to the game; 2.4.3 and 3.3.5a read `Data/<locale>/realmlist.wtf`; 4.3.4 and 5.4.8 read `SET realmlist` in `WTF/Config.wtf`. Leyline keeps your original as a backup the first time.

Beacons run 3.3.5a, so they need a 3.3.5a client.

## Hosting

Hosting runs on your own PC. There are no hosted slots on our servers: the realm runs only while your PC does. See [Hosting](hosting.md) for the host kit itself.

1. **HOST A REALM** opens [play.openvanilla.app/wrath/host](https://play.openvanilla.app/wrath/host). Sign in, choose a name, a ruleset and house rules, and download your realm file (`leyline-<realm id>.bat` for Windows, `.sh` for Mac and Linux).
2. Unzip the host kit and choose its folder in Leyline. You also need Docker Desktop.
3. Leyline finds your realm file, in the kit or in Downloads, and copies it into the kit. START runs it in a window of its own. After the first run, START MY REALM runs the kit's own host script (`Host a Wrath realm.bat`, or `leyline host`).
4. Leyline shows the realm's status from the relay: online, on the realm list, players and bots, and its realmlist address.

## Updates and privacy

Leyline checks GitHub for a newer launcher release (tags `launcher-v*`) when it starts and every 6 hours, downloads it in the background and checks its signature. The title bar then says "Update ready, restart". It installs only when you press that, and never while a game you started from Leyline is open. Settings has a Stable and a Beta channel.

What it fetches: the Workshop list and the mods you install, the realm list and realm status, relay lookups for the realm you pick or host, and GitHub's release list. Each request gives up after 8 seconds (a mod download may take longer once it has started). The lists are kept, so Leyline works offline. It sends nothing about you. Settings and caches live in `%APPDATA%\Leyline` (Windows), `~/Library/Application Support/Leyline` (macOS) or `~/.local/share/Leyline` (Linux).

## Getting a build

Installers are on the [Leyline releases page](https://github.com/orionopenwow/Leyline/releases) (tags `launcher-v*`): Windows (.msi and setup .exe), macOS (one .dmg for Apple Silicon and Intel) and Linux (.AppImage, .deb).

Builds are not code-signed yet. On Windows choose "More info, Run anyway". On macOS right-click the app and choose Open (if it says the app is damaged: `xattr -dr com.apple.quarantine /Applications/Leyline.app`). On Linux make the .AppImage executable.

The build workflow is `.github/workflows/leyline-launcher.yml` in the Leyline repo. It runs the tests on every change and, for a tag such as `launcher-v0.3.0`, builds the installers and attaches them to a release. The owner turns it on once with `Turn on GitHub builds.bat`, which also pushes the first tag; a new version is a new tag.

To build it yourself, see `launcher/README.md` in the repo.

## Not yet

- Publishing a mod from a GitHub repository.
- A peer-to-peer realm list next to the relay's listing.
- Signed mods and a review step.
- Starting and stopping a realm without the kit's own window.
