# Dens: your own room to build in

A Den is a realm on the player's own PC (the host kit's `den` profile), private and invite-only by default.
Every character starts alone in a plain white room and builds it into their Den: F7 is edit mode, the realm's
Builder (`realm/custom/lua_scripts/ov_build.lua`) places and checks every prop, and `ov_den.lua` is the room
around it. Friends join through the relay with the realm's invite link; the owner decides who may build.

Status: 2026-10-30, workstream E of the Leyline launch. Server side and addon built and tested; the browser
client's engine hooks below are still to do.

## Hosting a Den

```
leyline host --ruleset den --private --name "My Den" --gm <your account>
```

or the launcher's Host page, "Make my Den" (to add: see Launcher below). The profile (`realm/profiles/den.env`,
`hosting/kit/tools/wuhost/setup.py`): private, sign-up from the invite link only, no bots (never: `NO_BOTS`),
`WU_DB_BUFFER=256M`, at most 10 players, every builder on the full tier from the first minute, nothing that
teleports players elsewhere (`OV_MAIN`, `OV_QOL_HUB` off). The kit writes `realm-files/lua_scripts/den-invite.dat`
(the invite link, data only, mode 0600) for the in-game "Invite a friend"; only this profile does, and leaving it
removes the file.

## The room

**Where:** the sealed island in the far north-east corner of Kalimdor (map 1), AzerothCore's `game_tele` 424
"GMIsland" (16226.2, 16257.0, 13.2). Chosen over an emptied instance map because, from the AzerothCore world
database (`data/sql/base/db_world`):

- every 3.3.5a client has the island's terrain (Kalimdor's own tiles; nothing new to ship);
- `creature.sql` has one spawn within 600 yards, its Spirit Healer (6491); `gameobject.sql` has 15, the island's
  own chairs and building, 30+ yards north of the room;
- the nearest other spawn on map 1 is more than 5000 yards away (x at most 11078, y at most 3825), so nothing
  wanders in, and the grid unloads when nobody is there;
- an instance map would need its creatures removed from the world database (the mod rules keep scripts to their
  own tables) and would split friends into separate copies unless grouped.

The browser stream does not carry this part of Kalimdor yet (see Requests). `OV_DEN_X / _Y / _Z` move the room;
the exact spot is "to verify in game".

**What:** a floor, four walls with a doorway in the south wall to the yard, and four lights, all catalog props
owned by the Den itself (owner 0): free of every budget, changed only by the owner (GM), never selectable by
builders. Looks: white (big light blocks, the default), stone, wood (`.den room <look>`). It goes up the first time
anyone stands in the Den (the floor height is measured there with `Map:GetHeight` and kept in `mod_den_settings`).
Sizes and spacing are "to verify": `OV_DEN_TILE` sets the spacing, `OV_DEN_SIZE` the room's half width (8-20).

**The edge:** every 2 seconds anyone outside the Den (more than `half + 14` yards from the middle, 12 yards below
the floor or 50 above it, or on another map) is put back in the room. GMs with `.gm on` are free. New characters
start in the room with their hearth set there.

## Midnight's decor placement, and where we are

Owner decision: "crafting means placing objects to the level of Midnight's full functionality". The table lists
what the official newest housing system does (sources at the bottom), and our state: **built**, **engine hook**
(needs the browser client, spec below), or **later**.

| Feature (Midnight) | Ours | State | Source |
|---|---|---|---|
| Decor catalog in categories (furniture, wall decor, walls/floors/ceilings, lighting, small decor, effects) | 378 props in 12 categories, a new `structure` one for floors, walls and stairs | built | [1] |
| Search and filters in the storage window | the Builder window's search and categories; the spawn menu's search and tabs | built | [2] |
| Click an item, click where it goes | spawn menu (Q) or the Builder, then a click: `.build spawnat` | built (Q: engine hook) | [2] |
| Move, any time | carry (G), the handles, `placeat`, `setpos` | built | [2] |
| Rotate in 15 degree steps (basic) | Turn button (15/45/90), Q/E while carrying | built | [1][3] |
| Rotate on any axis (advanced gimbal) | yaw, pitch, roll stored (`mod_builder_prop_tilt`); pitch and roll show only with mod-sandbox-core | built (tilt needs the module on the realm image) | [1] |
| Scale within generous limits | 0.5 to 2.5, stored (`mod_builder_prop_scale`) | built; in-place resize needs the module or the engine (below) | [1][2] |
| Grid snap, shown and toggled; the grid shrinks on small surfaces | Snap 0 / 0.5 / 1 / 2 yards (client CVar) | built; surface-sized grid: engine hook | [1][3] |
| Snap to surfaces: rugs to floors, paintings to walls, ceilings | `.build floor` puts the selection down on the floor below | built for floors; walls and ceilings: engine hook (raycast) | [1][3] |
| Small decor parents to big decor (books move with the shelf) | groups: `.build group`, a click on one selects them all | built (an explicit group, not automatic) | [1][3] |
| Collision on (basic), clipping on (advanced) | no collision checks: everything clips (advanced mode's rule) | later (needs model bounds) | [1][2] |
| Dye decor | none: the 3.3.5a client has no per-object tint for gameobjects | later (engine) | [2] |
| Customize walls, floors, doors to a theme | the room's look: white, stone, wood | built | [2] |
| Clean-up: click to send back to storage | Put away (`.build store`) | built | [2] |
| Decor storage of owned items | storage per character (`mod_builder_storage`), a Storage tab with counts; placing one takes it out | built (the catalog itself stays free: creative) | [2][4] |
| Multi-select | Shift-click, box select, Select mine, group ops as one undo entry | built (box drag and Shift-click: engine hooks) | not documented for Midnight; ours anyway |
| Undo and redo | `.build undo` / `redo`, 30 deep, Ctrl+Z / Ctrl+Y | built (Ctrl+Y: engine hook) | not documented for Midnight; ours anyway |
| Copy, paste, duplicate (an addon adds these in Midnight) | Copy, Paste at a click, Duplicate (V) | built (Ctrl+C/V: engine hook) | [5] |
| Layouts: save, load, share at room, plot or house level | `.den save/load <name> [replace]`: the whole Den with size and tilt; builds and prefabs share as 6-letter codes | built; layout codes: later | [4] |
| Inside and outside are separate | the room (inside the walls) and its yard | built | [1] |
| Budgets (placement budget, room limit; outside smaller, rising with house level) | build points per prop; two Den budgets, room 1000 and yard 300 (`OV_DEN_INSIDE_POINTS`, `_OUTSIDE_POINTS`) | built (no levels) | [1][4][6] |
| Floorplan: add rooms | one room | later | [2] |
| Visitor permissions (neighbours, guild, friends, party) and visitor codes | invite link only (the realm is private); view, build, owner (`.den allow <name> build|view`); the host's allow list | built | [4][7] |
| Guest book | none | later | [4] |

Sources (read 2026-10-30): [1] A fan news site (Tavern), "Decorating Preview for Player Housing in Midnight". [2] Icy Veins,
"Player Housing: Interior Customization Guide". [3] Icy Veins, "Midnight's Player Housing: A Deep Dive into Basic
Mode". [4] The official news site, "A Look Ahead at Housing in Midnight". [5] CurseForge, the "ADT - Advanced
Decoration Tools" addon. [6] The game's API wiki, `C_HousingDecor.GetAllMaxPlacementBudgets` (interior and exterior
budgets). [7] The official EU forums, "Housing permissions needs a bit more". Full links are in the project doc
`claude/den-plan.md`.

## Commands

```
.den                          what this is, and your role
.den home                     back to the middle of the room
.den invite                   (owner) the invite link; the Den panel shows it to copy
.den builders                 who may build
.den allow <name> build|view  (owner) a friend builds, or only looks
.den room white|stone|wood|rebuild|clear   (owner) the room's look
.den budget                   the room's and the yard's decor budgets
.den save|load <name> [replace] / .den layouts   the whole Den as a layout
.build redo | store | storage | group | ungroup | floor | layout save|load|list|delete <name> [replace]
```

In game: F7 (edit mode), the third tool bar (Group, Ungroup, Put away, Storage, Floor, Den), `/den` for the Den
panel outside edit mode.

## Engine hooks for the browser client (edit_mode.rs)

Everything below already has its addon side; the client calls the hook or sends the command.

1. **Hold Q: the spawn menu.** Q down with nothing carried: `WrathUnleashedUI.EditMode.SpawnMenu(true)`; Q up:
   `SpawnMenu(false)`. While carrying, Q / E keep turning.
2. **Shift-click.** A click on a prop: `EditMode.Clicked(x, y, z, objectId, shift)` with `shift = true` when Shift
   is held (the addon also reads `IsShiftKeyDown()`).
3. **Box select.** Left-drag on empty ground draws a screen rectangle; on release, the two ground corners under it:
   `EditMode.BoxSelect(x1, y1, x2, y2, add)` (add: Shift held).
4. **Group carry ghost.** `LeylineEdit("group <guid counters>")` arrives with every state; while G-carrying or
   dragging a handle, draw every listed object moved by the same offset and turn (around the last-picked object),
   then one `EditMode.Drop` / `GizmoCommit` on release.
5. **Ctrl+C / Ctrl+V / Ctrl+Y.** Ctrl+C: `EditMode.Cmd("copy")`; Ctrl+V: `EditMode.StartPasting()` (the next ground
   click pastes); Ctrl+Y and Ctrl+Shift+Z: `EditMode.Cmd("redo")`. Optional: `Cmd("store")` on Ctrl+X,
   `Cmd("group")` on Ctrl+G, `Cmd("floor")` on End.
6. **GameObject SetScale.** Without mod-sandbox-core the realm sets `OBJECT_FIELD_SCALE_X` after spawning (and
   respawns on a change). The client must apply that field to the gameobject's model on create and on a values
   update, and the handles must preview a size change (a scale handle: commit `.build scale <id> <size>`).
7. **Surface snap.** The click point should come from a raycast that hits gameobject models (a table top, a wall),
   not only the terrain, and report the surface normal: walls then place facing out (`.build move <id> x y z yaw`),
   and the grid can shrink to the surface's size.
8. **Pitch and roll preview.** The ring handles for pitch and roll (the realm stores them; with the module it shows
   them); without the module, preview locally and send `.build rotate <id> <yaw> <pitch> <roll>`.

## Requests

- **Launcher** (other agents own `launcher/ui/app.js`, `index.html`, `style.css`, `hostconsole.*`):
  1. The play bar's realm picker: replace "Solo (coming soon)" with **My Den**. When a den realm exists on this PC
     (`state/host.json` profile `den`), it plays it (`leyline://` join to the realm's own invite, like the Host
     page's Play); when none exists, it opens the Host page with the Den ruleset chosen.
  2. The Host page: a **Make my Den** ruleset (`preset: den`, label "My Den", note "A private room to build in:
     you and the friends you invite. No bots."), private and sign-up "invite" by default, the bots and max-players
     controls hidden (the kit refuses bots for den). It runs `leyline host --ruleset den --private`.
  3. Rust: `launcher/src-tauri/src/deeplink.rs` presets for azerothcore (add `den`, refuse bots like `dalaran`),
     `host/profiles.rs` a `KitProfile { id: "den", label: "3.3.5a: My Den (a private room to build in)", ... }`,
     `hostconsole.js` ORDER and labels, `app.js` preset names.
- **Host kit flows** (being edited by workstream A): add `den` to the ruleset lists of `hosting/kit/leyline`,
  `host-wrath-realm.sh` and `Host a Wrath realm.bat`, and in `leyline` default the visibility to private for den.
  `leyline host --ruleset den --private` already works (answers from flags are not checked against the list).
- **Website** (`stream/hostflow.py`): a `den` recipe beside the others, if the site should offer Dens.
- **CI** (`tools/github-workflows/realm-scripts.yml`): `lua5.1 stream/tests/test_ov_den.lua`.
- **Browser stream**: the island's terrain tile (Kalimdor, the tile holding x 16226, y 16257: both indices 1) in the
  slice, so browser players can visit a Den without their own game folder.
- **Realm image**: mod-sandbox-core on the host kit's image, for in-place moves, pitch and roll, and resize.

## Next phases

1. In game: verify the spot, the floor height, the blocks' sizes and colours, and tune `OV_DEN_TILE` and the looks.
2. The engine hooks above.
3. Layout codes (share a Den's layout with anyone), a guest book, more looks (doors, ceilings), more rooms.
4. A Den on the Leyline network: a public Den as a showcase (read-only visitors, Midnight's snapshot visits).
