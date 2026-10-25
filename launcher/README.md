# Leyline launcher

One desktop app (Windows, macOS, Linux) for Leyline: pick your game client, point it at a realm, play.
Later phases add the mod manager, publishing mods from GitHub, hosting a realm and the peer-to-peer realm list.

Leyline uses the client **you already have** on your PC. It never downloads, copies or ships game files.
No telemetry, no accounts.

## What works now (phase L0)

| Page | State |
|---|---|
| **Play** | pick a client and a realm, then PLAY: writes the client's `realmlist.wtf` (the original is kept as `realmlist.wtf.leyline-backup`) and starts it. *Play in the browser* opens https://play.openvanilla.app/wrath. |
| **Clients** | add a client by folder. The build is read from the executable's version resource (3.3.5a = 3.3.5.12340, 1.12.1 = 1.12.1.5875), falling back to the data files (the expansion archives or `Data/common-2.MPQ` for 3.3.5a; `Data/patch.MPQ` + `Data/dbc.MPQ` and no expansion archives for 1.12.1). It checks the install looks complete and lists what is missing. |
| **Settings** | Wine on/off, the wine command and an optional prefix (macOS and Linux). |
| Mods | coming in the next phase. Shows the catalog count (read-only). |
| Realms | coming in the next phase. Shows the community realm count (read-only). |
| Host | coming in a later phase. |

Where the realm address goes: 3.3.5a reads `Data/<locale>/realmlist.wtf` (and, if it has a `realmList` line,
`WTF/Config.wtf`, which is updated too); 1.12.1 reads `realmlist.wtf` in the client folder.

Settings and caches live in the OS app-data folder:
`%APPDATA%\Leyline` (Windows), `~/Library/Application Support/Leyline` (macOS), `~/.local/share/Leyline` (Linux).
The two listings (`https://play.openvanilla.app/wrath/mods/catalog.json` and
`https://relay.openvanilla.app/api/listing/realms.json`) are fetched with an 8 second timeout and cached there,
so the app works offline.

## Layout

| Path | What it is |
|---|---|
| `ui/` | the web UI: `index.html`, `style.css`, `app.js`, and the Leyline art and font in `ui/art/`. No framework, no bundler. |
| `src-tauri/src/clients.rs` | add a client by folder, detect the build, completeness, realmlist read/write with backup |
| `src-tauri/src/pe_version.rs` | the executable's file version (VS_FIXEDFILEINFO), parsed from bytes on any OS |
| `src-tauri/src/launch.rs` | start the client in its folder; through Wine on macOS/Linux |
| `src-tauri/src/settings.rs` | the JSON settings file, saved atomically |
| `src-tauri/src/net.rs`, `catalog.rs`, `realms.rs` | the read-only listings with timeout and offline cache |
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

The core needs no webview, so its tests run anywhere Rust does:

```sh
cd launcher/src-tauri
cargo test --no-default-features
```

`cargo check` (with the default `app` feature) also checks the Tauri layer; that one needs the webview libraries.

## Releases

Push a tag such as `launcher-v0.1.0` and the workflow (once copied to `.github/workflows/`) builds Windows
(.msi, setup .exe), macOS (.dmg for Apple Silicon and Intel) and Linux (.AppImage, .deb) and attaches them to a
release for the tag. Builds are not code-signed yet: on Windows choose *More info, Run anyway*; on macOS
right-click the app and choose *Open*.

## Notes

- Network fetches do not go through a system proxy.
- The UI opens only one outside address (the browser client); it has no general "open URL" command.
- Rules for this folder: no game data, no secrets, and no game or publisher brand names in anything a user sees.
