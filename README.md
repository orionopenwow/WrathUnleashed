# WrathUnleashed: the private Leyline monorepo

This is the private home of **Leyline**: a mod launcher and a peer-to-peer realm network. Anyone can host a
realm in one click, from the browser or the desktop launcher, and it is listed for everyone. Players find realms
and mods in one place and play in the browser or with their own client.

Our own realm is only the temporary **Dalaran Hangout** (3.3.5a, AzerothCore). It is the sample realm, and it
gets our client additions first. The public repo, github.com/orionopenwow/Leyline, is copied from here by
`tools/leyline-repo/export.py` (launcher, host kit, relay and their docs only). No game data is in either repo.

Every folder, and what is core, ops or labs: **`docs/REPO-MAP.md`**.

## The parts

| Part | Where |
|---|---|
| Leyline launcher (Tauri 2: clients, mods, realms, hosting, themes) | `launcher/` |
| P2P/relay network and one-click hosting: host kit, relay, Discord bridge, mesh, the Hangout as a Beacon | `hosting/` |
| Website, portal and hub: sign-in, hub and Workshop, `/wrath/host`, realm list, social, docs | `stream/*.py`, `stream/www-files/` |
| Browser game layer and our client patches for the Hangout | `stream/www-files/`, `stream/fui-web/`, `client/`, `play/` |
| The Dalaran Hangout realm (AzerothCore 3.3.5a, custom modules and Lua) | `realm/` |
| Mods and addons | `mods/`, `addons/` |
| Autopilot, deploys and ops tools | root `.bat` files, `tools/`, `server/`, `gmconsole/`, `control/` |
| Paused tools and plans, kept for later | `labs/` |

## Day to day

- **Updates:** `WrathUnleashed Control.bat` (the control window, with Autopilot) or `UPDATE.bat` runs what Claude
  queued in `UPDATES-PENDING.txt`. The steps are listed in `tools/control/control.py` (`STEPS`).
- **Save to GitHub:** `Ship WrathUnleashed.bat` (the `ship` step); every ship also refreshes the public Leyline
  copy (`tools/leyline-repo/Update Leyline repo.bat`).
- **Release the launcher:** `Ship the Leyline launcher.bat`.
- **Host a realm:** `hosting/kit/Host a Leyline realm.bat`, or `/wrath/host` on the site. Guide:
  `hosting/INSTALL-OPERATE.md`.
- **Play locally:** `Play WotLK (one click).bat` starts Docker, the local realm (`realm/`) and the page host
  (`play/`). It reads game files from your own 3.3.5a install.

## The browser client

The client is benilla-wotlk (github.com/Onixaz/benilla-wotlk, Apache-2.0/MIT) with our web port and changes,
kept as patches in `client/patches/`. `client/README.md` says how to get the source (`client/get-source.sh`),
build it on your PC or on GitHub, and where the build goes (`play/dist`). Dev helpers (lighter rebuild,
data-free boot check) are in `client/dev/`.

## Tests

```sh
for t in stream/tests/test_*.py; do python3 -I "$t"; done        # portal, hub, page, server scripts
NODE_PATH=$(npm root -g) node stream/tests/<name>.test.cjs        # page and UI (Playwright)
(cd hosting && python3 -m pytest -q tests)                        # host kit, relay, network
python3 -I tools/<tool>/test_<tool>.py                            # each ops tool
```
