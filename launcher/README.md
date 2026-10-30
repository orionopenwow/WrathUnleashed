# Leyline launcher

One desktop app (Windows, macOS, Linux) for Leyline: pick your game client, install and manage mods in it, find a
realm and play, or host your own. The window says "Leyline".

Leyline uses the client **you already have** on your PC. It never downloads, copies or ships game files.
No telemetry, no accounts.

## What works now (version 0.3)

| Page | State |
|---|---|
| **Home** | pick a client and a realm, then PLAY: sets the client's realm address (see below; the original is kept as `<file>.leyline-backup`) and starts it. A realm of another build says which client it needs. *Browser* opens https://play.openvanilla.app/wrath. |
| **Game clients** | add a client by folder. The build is read from the executable's version resource: 1.12.1 (5875), 2.4.3 (8606) and 3.3.5a (12340) for now; anything else (4.3.4 and 5.4.8 included, see below) is listed as **other** (realms only, no mods). No executable version: the data files decide. It checks the install looks complete and lists what is missing. Leyline never downloads a client. |
| **Discover** | the Workshop catalog (`/wrath/mods/all.json`): 12 categories, search, credits, links to each project's page, source and author; one-click INSTALL / UPDATE into the picked client; mods for other builds are flagged and can't be installed. |
| **My Mods** | per client: what is installed, the update ready, native code; one click to update or remove, turn off / on, UPDATE ALL; drop (or choose) a .zip, an addon folder, a .MPQ patch or a native mod (.dll, .asi; a one-time OK per mod). The title bar's pill counts Workshop updates across all clients. |
| **Realms** | the official realm plus the relay's Beacons, with their server (AzerothCore, TrinityCore, CMaNGOS, vMaNGOS, MaNGOS, other), build, status and players; PLAY picks one of your clients of the realm's build (or says which is missing), sets its realm address and starts it; "Only realms my clients can play"; join a private realm with its invite link; BACK TO WRATH; put back your own realmlist. |
| **Host** | plain-words steps: HOST A REALM (the website's /wrath/host gives the realm file), choose the host kit folder, start the realm file or the kit's host script in its own window, the realm's status from the relay. |
| **Themes** | Settings › Themes and Discover › Themes: Dark (the default) and Light, plus theme packs (CSS and images only, checked by an allowlist) from the Workshop's `themes` category or a zip. See [docs/THEMES.md](../docs/THEMES.md). |
| **Settings** | Wine on/off, the wine command and an optional prefix (macOS and Linux run Windows clients through Wine); updates: the Stable or Beta channel, CHECK NOW, RESTART TO UPDATE. |

### Builds: what Leyline knows per client

**For now Leyline offers the 1.12.1, 2.4.3 and 3.3.5a clients only** (the owner's call, 2026-10-30). 4.3.4 and 5.4.8 stay in the code but are hidden from players and hosts; `MAX_OFFERED_BUILD` (`clients.rs`, `app.js`) or `LEYLINE_ALL_CLIENTS=1` brings them back.

| Build | Executable version | Realm address goes to | Addon `## Interface:` | Client patches (.MPQ) |
|---|---|---|---|---|
| 1.12.1 | 1.12.1.5875 | `realmlist.wtf` next to the game | 11200 | yes |
| 2.4.3 | 2.4.3.8606 | `Data/<locale>/realmlist.wtf` (+ `realmList` in `WTF/Config.wtf` if there is one) | 20400 | yes |
| 3.3.5a | 3.3.5.12340 | `Data/<locale>/realmlist.wtf` (+ `realmList` in `WTF/Config.wtf` if there is one) | 30300 | yes |
| 4.3.4 (hidden for now) | 4.3.4.15595 | `SET realmlist "..."` in `WTF/Config.wtf` (added if missing) | 40300 | no |
| 5.4.8 (hidden for now) | 5.4.8.18414 | `SET realmlist "..."` in `WTF/Config.wtf` (added if missing) | 50400 | no |
| other | anything else | by its major version: 1 next to the game, 2-3 `Data/<locale>`, 4+ `WTF/Config.wtf` | no addons | no |

The first time Leyline changes a realm file it keeps the original next to it as `<file>.leyline-backup`; MY OWN
REALMLIST puts it back. A realm listing names its build (`profile.build`, `profile.version` or `profile.game`)
and server (`profile.core`); Beacons from the host kit are AzerothCore 3.3.5a.

### Leyline's own updates

Leyline checks the public repo's GitHub releases (tags `launcher-v*`) at start and every 6 hours. On the
**stable** channel it takes releases; on **beta**, pre-releases too (a version with a `-`, such as
`0.3.1-beta.1`). Each release carries `latest.json`, made by CI; Leyline checks that its downloads are this
release's own files, then Tauri's updater downloads the new version in the background and checks its signature
against the public key in `tauri.conf.json`. The title bar then says **Update ready, restart**. Nothing installs
until the player presses it, and it refuses while a game Leyline started is still open (Windows: the installer
runs in passive mode and starts the new Leyline; macOS and Linux: Leyline restarts itself).

Until the owner has run **setup\Turn on launcher updates.bat** once (see Releases), builds carry no public key and
Leyline only links to the release page.

### Mods: where files go and what is checked

- UI addons go to `Interface/AddOns/<Name>/`; a client patch (.MPQ) goes to a free `Data/patch-<X>.MPQ` slot
  (4-9, then A-Z; 1.12, 2.4.3 and 3.3.5a only). A mod package's `realm/` half is skipped. Packages may not contain .MPQ files (mod format).
- Zips and folders are staged in `<client>/Leyline/staging/` and checked with the UI rules of `mods/wu-mod.py` and
  `stream/www-files/wu-addons-core.js` (layout, `<Name>.toc` with the client build's Interface number (table above),
  TOC files present, XML `file=` references, allowed file types, no game data by extension or magic bytes,
  10 MB a file, 50 MB, 2000 files). Zip-slip, symlinks, passwords and odd packing methods are refused.
- Catalog downloads come only from the catalog's own site, are capped at 60 MB and must match its sha256.
- Nothing is written outside the client folder or through a symlink. An addon folder Leyline did not install is
  never overwritten.
- `<client>/Leyline/mods.json` lists every file Leyline installed, so removal is exact; turned-off mods wait in
  `<client>/Leyline/disabled/`. The last removal removes `Leyline/` and any folder Leyline created.
- Every mod is allowed (owner decision): no review queue, no signing yet.

### Realms: how a desktop client reaches a Beacon

The relay gives each realm its own TCP login port; `set realmlist relay.openvanilla.app:<port>` reaches it, and
the realm advertises the relay's world port, so the client stays on the relay. The listing record carries it
(`profile.address`, `profile.port`); otherwise `GET https://<relay>/api/realms/<id>` gives `auth_port`. Private
realms let in an address that knocked with the invite (`POST /api/realms/<id>/knock`), which the invite box does.
Needs the relay's ports 40000-40999 open to the internet (the relay install opens them in ufw; a cloud firewall
needs them by hand). Accounts are made on the realm's join page in the browser.

Settings and caches live in the OS app-data folder:
`%APPDATA%\Leyline` (Windows), `~/Library/Application Support/Leyline` (macOS), `~/.local/share/Leyline` (Linux).
The listings (the Workshop's all.json, the relay's realms.json, GitHub's releases) are fetched with an 8 second
timeout and cached there, so the app works offline. A mod download connects within 8 seconds and may then take
up to 30 seconds between reads.

## Layout

| Path | What it is |
|---|---|
| `ui/` | the web UI: `index.html`, `style.css`, `app.js`, and the Leyline art and font in `ui/art/`. No framework, no bundler. |
| `src-tauri/src/clients.rs` | add a client by folder, detect the build (five known builds and "other"), completeness, the realm file per build with backup and restore |
| `src-tauri/src/pe_version.rs` | the executable's file version (VS_FIXEDFILEINFO), parsed from bytes on any OS |
| `src-tauri/src/launch.rs` | start the client in its folder; through Wine on macOS/Linux |
| `src-tauri/src/settings.rs` | the JSON settings file, saved atomically |
| `src-tauri/src/net.rs` | listings with timeout and offline cache, capped downloads with sha256, the relay calls |
| `src-tauri/src/catalog.rs` | the Workshop's all.json: parsing, checking every field, per-build fit |
| `src-tauri/src/mods.rs` | the mod manager: staging, zip checks, the UI rules, install, on/off, removal, the per-client manifest, updates |
| `src-tauri/src/realms.rs` | the official realm and the relay's Beacons, their server core and build, picking a client that fits, relay lookup, invite links and the knock |
| `src-tauri/src/host.rs` | the host kit: finding it, its realm and the website's realm files, starting it, the realm's relay status |
| `src-tauri/src/update.rs` | the launcher's own updates: the channel's newest release (GitHub, `launcher-v*`), semver order, the `latest.json` check |
| `src-tauri/src/status.rs` | a realm's live status: login-port ping plus its status file |
| `ui/themes.js`, `ui/themes/` | themes: applied before paint, the Themes section and its cards (the looks and `--t-*` tokens are in `ui/style.css`) |
| `src-tauri/src/themes.rs` | theme packs: the format, the CSS allowlist, install (catalog with sha256, zip, folder), list, apply, remove |
| `src-tauri/src/app.rs` | the Tauri commands the UI calls (only built with the `app` feature) |
| `../tools/github-workflows/leyline-launcher.yml` | CI: tests, and release builds on a `launcher-v*` tag (Windows, macOS universal, Linux; signed for the updater when the key is set) |
| `../tools/launcher-updates/` | the script behind `setup\Turn on launcher updates.bat`: the updater's key pair into GitHub secrets, the public key into `tauri.conf.json` |
| `CHANGELOG.md` | what changed; each `## <version>` section becomes that release's text |

## Build and run

You need [Rust](https://rustup.rs) (stable) and the Tauri CLI, plus the system webview:

- **Windows**: WebView2 (already on Windows 10/11) and the MSVC build tools.
- **macOS**: Xcode command line tools (`xcode-select --install`).
- **Linux** (Debian/Ubuntu): `sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev build-essential`

Get the Tauri CLI one of two ways:

```sh
cd launcher
npm install                 # installs @tauri-apps/cli locally (Node 18+), then: npm run tauri dev
# or
cargo install tauri-cli --version "^2" --locked   # then: cargo tauri dev
```

Run it in development (opens the window, reloads the UI on save):

```sh
cd launcher
npm run tauri dev           # or: cargo tauri dev
```

Build the installers for your OS (output in `src-tauri/target/release/bundle/`):

```sh
npm run tauri build         # or: cargo tauri build
```

### Test the core

The core needs no webview, so its tests run anywhere Rust does. They use fake client folders, fake zips and a
local HTTP server (no network):

```sh
cd launcher/src-tauri
cargo test --no-default-features
```

`cargo check` (with the default `app` feature) also checks the Tauri layer; that one needs the webview libraries.

## Releases

One tag push makes a release: `launcher-v<version>`, with `<version>` exactly the one in
`src-tauri/tauri.conf.json` (and `Cargo.toml`, `package.json`). The workflow (copied to the public Leyline repo's
`.github/workflows/` by "setup\Turn on GitHub builds.bat", which also pushes the tag for the current version) then:

1. tests the core on Windows, Linux and macOS (the macOS job may fail without failing the run);
2. makes the GitHub release, its text from this version's section of `CHANGELOG.md`; a version with a `-` is a
   pre-release (beta channel only);
3. builds and attaches: Windows setup .exe (NSIS) and .msi; Linux .AppImage and .deb; macOS one universal .dmg
   (a separate job that may fail without failing the run: re-run it later for the .dmg);
4. with the updater key set, signs the updater files and attaches `latest.json`.

The owner's order for a release:

1. Once ever: **setup\Turn on launcher updates.bat** (makes the updater key pair on the PC, stores the private key and
   its password as the Leyline repo's Actions secrets with `gh secret set`, never shown, and writes only the
   public key into `src-tauri/tauri.conf.json`; running it again keeps the key).
2. Bump the version in `tauri.conf.json`, `Cargo.toml` and `package.json` and add a CHANGELOG section (Claude does
   this), then **Ship**, then the **Leyline** step (copies `launcher/` to the public repo).
3. **setup\Turn on GitHub builds.bat**: pushes the `launcher-v<version>` tag; the release appears in about 20 minutes.

Builds are not code-signed yet: on Windows choose *More info, Run anyway*. On **macOS** Gatekeeper blocks an
unsigned app the first time: right-click (or Control-click) Leyline in Applications and choose *Open*, then
*Open* again; if macOS says the app "is damaged", run `xattr -dr com.apple.quarantine /Applications/Leyline.app`
once. On **Linux**, make the .AppImage executable (`chmod +x Leyline_*.AppImage`); the .AppImage updates itself,
the .deb updates through `pkexec` (it asks for your password). Both start Windows game clients through Wine
(Settings).

A Windows build from Linux (no installer, just the app's .exe; it needs WebView2, which Windows 10 and 11 have):

```sh
rustup target add x86_64-pc-windows-gnu      # plus the mingw-w64 cross compiler
cd launcher/src-tauri
cargo build --release --target x86_64-pc-windows-gnu
# -> target/x86_64-pc-windows-gnu/release/leyline.exe
```

## Notes

- Network fetches do not go through a system proxy.
- The UI cannot open any address it likes: links open by name from a fixed list (`LINKS` in `lib.rs`) or, for
  catalog credits, realm join pages and the release page, only addresses the core itself handed the UI.
- Installs never take a URL from the UI: a catalog install names a project id, looked up in the cached catalog.
- Rules for this folder: no game data, no secrets, and no game or publisher brand names in anything a user sees.
