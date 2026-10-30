# labs/: tools and experiments kept for later

Leyline's core today is the launcher, the P2P/relay network with one-click hosting, the website and hub, the
browser game layer with our client patches, the Dalaran Hangout realm, mods, and the Autopilot/ops tools
(see `docs/REPO-MAP.md`). Everything here is **not** part of that core right now, but the owner wants to keep
it for later upgrade and refinement (2026-10-30). Nothing here is run by Autopilot (`tools/control/control.py`),
`UPDATE.bat`, CI or the Leyline export.

Each folder keeps its files exactly as they were, moved with `git mv` (`git log --follow` shows the history).

| Folder | What it is | Status | How to revive it |
|---|---|---|---|
| `leyline-client-112/` | `Make the Leyline 1.12 client repo.bat`: makes the private `orionopenwow/leyline-client-112` repo (our maintained 1.12 browser client, from wenilla + a sync bundle) and pushes a sync branch. | Paused. Our own realm is now the 3.3.5a Dalaran Hangout only; 1.12 stays a client the launcher and host kit support, not a client we maintain. Was `tools/leyline-client-112/`. | It sits at the same depth as `tools/`, so `%~dp0..\..` is still the repo and it runs from here as before. Needs `wenilla-sync.bundle` beside it or in Downloads. To make it an Autopilot step, add it to `STEPS` in `tools/control/control.py`. |
| `ov-112-logins/` | `Carry over 1.12 logins.bat` + `carry-112-logins.sh`: copies old Open Vanilla 1.12 logins (SRP6 salt/verifier) into the 3.3.5a realm's accounts, dry run first. | Done once; the 1.12 realm is gone from our plans. Was in `server/`. | Self-contained (the .bat sends the .sh over SSH to `/srv/wrath`). Run it from here; it only works while the old 1.12 database container is still on the server. |
| `plans/sandbox-roadmap.md` | The "build anything" sandbox roadmap: Builder, Logic Editor, game-mode kits, GLB importer, player spaces. | A plan, not a commitment. The Builder MVP itself is live on the Hangout (`realm/custom/lua_scripts/ov_build.lua`) and stays in place. Was `docs/sandbox-roadmap.md`. | Move it back to `docs/` when the sandbox is on the roadmap again. |

## Experiments that stay where they are

Some prototypes are wired into live scripts, tests or the client build, so moving them would break things.
They stay in place and are listed in `docs/REPO-MAP.md` under "Experimental, in place":
the extra realm profiles (`realm/profiles/brawl.env`, `progression.env`, `casual.env` and their SQL), the mesh
simulator (`hosting/mesh-sim/`), the P2P/torrent and mesh flags (all OFF, `stream/leyline_net.py`), the guest
demo (`stream/demo.py`, OFF), the test-build launchers in `play/` (smooth frames, nameplates, Azeroth Survivors),
the player package (`Make player package.bat`, `players/`), and the Hordes of Azeroth work (only on its own branch).

## Adding to labs/

Put each experiment in its own folder with its files as they were, then add a row above: what it is, its status,
and the exact steps to run it again. Never leave a `labs/` path in `STEPS`, `UPDATE.bat`, a workflow or the
export's `ALLOW` list: anything those need belongs in the core folders.
