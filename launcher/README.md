# Leyline launcher

One desktop app (Windows, macOS, Linux) for Leyline: pick your game client, install and manage mods in it, find a
realm and play, or host your own. The window says "Leyline".

Leyline uses the client **you already have** on your PC. It never downloads, copies or ships game files.
No telemetry, no accounts.

## What works now (phase L1, version 0.2)

| Page | State |
|---|---|
| **Home** | pick a client and a realm, then PLAY: writes the client's `realmlist.wtf` (the original is kept as `realmlist.wtf.leyline-backup`) and starts it. *Browser* opens https://play.openvanilla.app/wrath. |
| **Game clients** | add a client by folder. The build is read from the executable's version resource (3.3.5a = 3.3.5.12340, 1.12.1 = 1.12.1.5875), falling back to the data files. It checks the install looks complete and lists what is missing. |
| **Discover** | the Workshop catalog (`/wrath/mods/all.json`): 12 categories, search, credits, links to each project's page, source and author; INSTALL / UPDATE into the picked client; mods for the other build are flagged and can't be installed. |
| **My Mods** | per client: what is installed, update available, turn off / on, remove; drop (or choose) a .zip, an addon folder or a .MPQ patch. |
| **Realms** | the official realm plus the relay's Beacons, with status and players; PLAY sets the realmlist (and Config.wtf on 3.3.5a) and starts the client; join a private realm with its invite link; BACK TO WRATH; put back your own realmlist. |
| **Host** | plain-words steps: HOST A REALM (the website's /wrath/host gives the realm file), choose the host kit folder, start the realm file or the kit's host script in its own window, the realm's status from the relay. |
| **Settings** | Wine on/off, the wine command and an optional prefix (macOS and Linux); the update check (GitHub releases, tags `launcher-v*`, link only). |

Where the realm address goes: 3.3.5a reads `Data/<locale>/realmlist.wtf` (and, if it has a `realmList` line,
`WTF/Config.wtf`, which is updated too); 1.12.1 reads `realmlist.wtf` in the client folder.

### Mods: where files go and what is checked

- UI addons go to `Interface/AddOns/<Name>/`; a client patch (.MPQ) goes to a free `Data/patch-<X>.MPQ` slot
  (4-9, then A-Z). A mod package's `realm/` half is skipped. Packages may not contain .MPQ files (mod format).
- Zips and folders are staged in `<client>/Leyline/staging/` and checked with the UI rules of `mods/wu-mod.py` and
  `stream/www-files/wu-addons-core.js` (layout, `<Name>.toc` with Interface 30300 or 11200 for the client,
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
| `src-tauri/src/clients.rs` | add a client by folder, detect the build, completeness, realmlist read/write with backup |
| `src-tauri/src/pe_version.rs` | the executable's file version (VS_FIXEDFILEINFO), parsed from bytes on any OS |
| `src-tauri/src/launch.rs` | start the client in its folder; through Wine on macOS/Linux |
| `src-tauri/src/settings.rs` | the JSON settings file, saved atomically |
| `src-tauri/src/net.rs` | listings with timeout and offline cache, capped downloads with sha256, the relay calls |
| `src-tauri/src/catalog.rs` | the Workshop's all.json: parsing, checking every field, per-build fit |
| `src-tauri/src/mods.rs` | the mod manager: staging, zip checks, the UI rules, install, on/off, removal, the per-client manifest, updates |
| `src-tauri/src/realms.rs` | the official realm and the relay's Beacons, relay lookup, invite links and the knock |
| `src-tauri/src/host.rs` | the host kit: finding it, its realm and the website's realm files, starting it, the realm's relay status |
| `src-tauri/src/update.rs` | the launcher's own update check (GitHub releases, `launcher-v*`) |
| `src-tauri/src/status.rs` | a realm's live status: login-port ping plus its status file |
| `src-tauri/src/app.rs` | the Tauri commands the UI calls (only built with the `app` feature) |
| `../tools/github-workflows/leyline-launcher.yml` | CI: tests, and release builds on a `launcher-v*` tag |

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

Push a tag such as `launcher-v0.2.0` and the workflow (once copied to `.github/workflows/`) builds Windows
(.msi, setup .exe), macOS (.dmg for Apple Silicon and Intel) and Linux (.AppImage, .deb) and attaches them to a
release for the tag. Builds are not code-signed yet: on Windows choose *More info, Run anyway*; on macOS
right-click the app and choose *Open*.

Copying the workflow into `.github/workflows/` needs a token with the `workflow` scope: run
`gh auth refresh -s workflow` once, then copy, commit and push it, then push the tag.

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
