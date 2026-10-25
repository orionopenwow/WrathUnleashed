# WrathUnleashed

The Wrath of the Lich King (3.3.5a) project, split out of Open Vanilla on 2026-10-24. Private,
local, nothing pushed or published, no Blizzard data: the page reads game files from your own
3.3.5a install. The originals stay in `OpenVanilla\_local\wotlk` for now.

- **Play:** `Play WotLK (one click).bat`. The first run here also assembles the client build
  from `play\dist\wasm.part.*`.
- **Realm:** `realm\` (Docker, AzerothCore). The realm's database stays in Docker under the
  name `ov-wotlk`, so accounts and characters carry over; both folders drive the same realm, so
  run one at a time.
- **GM addons:** `addons\fetch-addons.sh` downloads AzerothAdmin again (left out of the copy;
  MiniGM is included).
- **Plan:** the WrathUnleashed doc (Brawl, main realm, Armory, progression slices).

# 3.3.5a in the browser: benilla-wotlk web port (private, work in progress)

This folder holds the port of wenilla's browser support onto benilla-wotlk
(github.com/Onixaz/benilla-wotlk, Apache-2.0/MIT). Nothing here is pushed or published.
It contains no Blizzard data. The page reads game files from your own 3.3.5a install.

## Status (2026-10-23)
- The desktop workspace builds and its tests compile. The 3.3.5a protocol crate passes 335+
  tests, and the app's 275 `net::` tests pass (login, realm list, character select against fake
  3.3.5 servers).
- The browser build (WebGPU) compiles, links and boots in headless Chromium:
  - the renderer comes up;
  - the Lua VM starts;
  - the network parks at the login screen.
  Every other line is "file not in patch chain", because the smoke test serves no game data.
- Left to do:
  - glue music on the async loader;
  - the page bridge (`webbridge`);
  - 3.3.5a boot/world prefetch manifests;
  - character rename;
  - a run with real data.

## One click
`Play WotLK (one click).bat` does it all: it starts Docker Desktop, extracts dbc + maps from your
install the first time, starts the local AzerothCore realm and waits for it, asks for a login
the first time, starts the page host and opens the browser. The server is in `realm/` and the
page is in `play/`.

## Try it with your own install
1. `git clone https://github.com/Onixaz/benilla-wotlk && cd benilla-wotlk && git checkout b9a4942`
2. `git checkout -b web-port && git apply ../wotlk-web-port-wip.patch`
3. `scripts/web-setup.sh`: gets the wasm target, wasm-bindgen 0.2.122 and wasi-sdk 27. The C Lua
   needs wasi-sdk.
4. `scripts/web-build.sh` builds WebGPU into `web/dist`. `WEB_BACKEND=webgl2` builds WebGL2 instead.
   The release build wants about 16 GB of RAM. `rebuild.sh` here makes the lighter dev build.
5. `cargo run -p wenilla-host -- --www web/dist --data "C:/path/to/WoW 3.3.5a/Data"`, then
   open http://127.0.0.1:8090.
6. To log in, the host's `/ws` proxy dials a 3.3.5a realm (`--upstream`), for example an
   AzerothCore test realm.

`smoke.js` + `smoke-serve.py` are the data-free boot check: serve `dist` with
`python smoke-serve.py dist`, then run `node smoke.js`.

## GM window and client addons
`addons/` holds AzerothAdmin (`/aa`) and MiniGM (`/mgm`). `addons\install-gm-addons.bat` copies
them into your client and can add the addon pack (Questie-335, Deadly Boss Mods, Details!, AtlasLoot,
AdiBags, MultiBot) and the all-races patch. See `addons/README.md`.

## Custom realm
`realm\Build custom realm.bat` builds AzerothCore with playerbots, transmog, autobalance, Mythic+,
1v1 arena, individual progression and more. See `realm/README.md`.
