# Smooth frames patch (browser client)

`wotlk-smooth-frames.patch` applies on top of `wotlk-web-port-wip.patch` (benilla-wotlk b9a4942),
both in this folder (`client/patches/`). From the `client/benilla-wotlk` checkout that `get-source.sh` makes:

    git apply ../patches/wotlk-web-port-wip.patch && git commit -am wip
    git apply ../patches/wotlk-smooth-frames.patch

Plan and reasoning: the "WotLK browser client: smooth frames plan" doc.

## What it changes
Hover
- Every mode cursor (talk, attack, loot, ...) is built behind the loading cover on web, so the
  first hover of each kind changes the cursor at once (`cursor.rs`).
- The cursor drive and the unit tooltip run after the targeting chain, so they follow this
  frame's hover, not last frame's (`cursor.rs`, `ui_tooltip/mod.rs`).

Loading and stutter
- One page-side file store (256 MB, least-recently-used out) behind every read: sync reads
  convert bytes in JavaScript in one pass and hit the store on repeat; async reads join a download
  already in flight; a 404 is remembered (`benilla-formats/src/web.rs`, `benilla-assets/src/lib.rs`).
- Parallel downloads: a tile's layer textures, a model's skin and .anim files, a building's groups
  (`adt.rs`, `m2.rs`, `wmo.rs`).
- Tiles one tile-width ahead of the heading are downloaded before the window reaches them
  (`terrain_stream.rs`).
- Terrain collision in 16 cell pieces instead of one whole-tile mesh; one tile spawned per frame
  (`terrain_stream.rs`, `terrain_stream/collider.rs`).
- GPU uploads capped at 8 MB a frame; at most 2 merged-mesh bakes a frame (`world_plugins.rs`,
  `static_gx/bake.rs`).
- Tuning knobs from the address for test passes: `?farclip=`, `?upload_budget=`, `?tile_unload=`,
  `?static_gx=`, `?no_bc=`, ... (`WEB_TUNABLE` in `benilla-formats/src/web.rs`).

Upscaling
- A `renderScale` below 1 now upscales with a Catmull-Rom bicubic read plus contrast-adaptive
  sharpening instead of a bilinear stretch (`shaders/ffx_glow.wgsl`). Try `/console renderScale 0.75`.

## Checked
- The wasm build compiles with no errors or warnings (`client/dev/rebuild.sh` settings).
- The data-free boot check (`client/dev/smoke.js`) boots to the login park as before.
- The combine shader validates with naga (both gamma variants).
- The file store's JavaScript passes a unit test (store hits, shared downloads, remembered 404s).
- Not yet run against real 3.3.5a data: the frame-time and hover test pass from the plan is next.
