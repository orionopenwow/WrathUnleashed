# Editing the WrathUnleashed client

Three ways to change the client. The first two need no build at all.

| What you change | Where | How it shows up |
|---|---|---|
| UI, frames, Lua, addons | your WoW install's `Interface\AddOns\` (e.g. `OVArmory`, `ForeverUI`) | `/reload` in game, or reload the page |
| Any game file: DBC tables, textures, stock FrameXML/GlueXML | `WrathUnleashed\patch\<game path>` | reload the page (never cached) |
| The engine itself (Rust: rendering, networking, the Lua API) | the client source, below | a new build in `play\dist` |

## Engine changes (Rust)

1. `bash get-source.sh` (Git Bash or WSL) clones benilla-wotlk at the pinned commit and applies
   `..\wotlk-web-port-wip.patch` onto branch `wrathunleashed`.
2. Edit, then either:
   - **build on your PC** (Linux/WSL, ~16 GB RAM): `bash scripts/web-setup.sh` once, then
     `bash scripts/web-build.sh`; copy `web/dist` into `WrathUnleashed\play\dist`; or
   - **let GitHub build it:** push the branch to your own fork with `github/web-build.yml`
     copied to `.github/workflows/`. Each push produces `client-dist` and `wenilla-host`
     artifacts to download.
3. Or ask Claude: it builds in the cloud and drops `play\dist\wasm.part.*`; the one-click
   launcher puts the build together on the next start.

Useful switches on the page address: `?moderncombos=1` (retail race/class pairs),
`?cinematics=1` (cinematics are off by default), `?boottrace=1` (record the load list),
`?gpudebug=1` (WebGPU errors), and any CVar as `?name=value` (`farclip=777`).
