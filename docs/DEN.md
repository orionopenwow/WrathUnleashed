# Dens: your own room to build in

A Den is a realm on the player's own PC (the host kit's `den` profile), private and invite-only by default.
Every character starts alone in a plain white room and builds it into their Den: F7 is edit mode, the realm's
Builder (`realm/custom/lua_scripts/ov_build.lua`) places and checks every prop, and `ov_den.lua` is the room
around it. Friends join through the relay with the realm's invite link; the owner decides who may build.

Status: 2026-10-30, workstream E of the Leyline launch; the editor to the world editors' level (any object, models,
exact transforms, lock, hide, measure, align, stack) the same evening, workstream L. Server side and addon built and
tested under the fake realm; not yet run on a real PC with Docker (the owner's test script is at the bottom). The
browser client's engine hooks below are still to do.

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
`OV_DEN_TILE` sets the spacing (4 yards), `OV_DEN_SIZE` the room's half width (8-32; the den profile sets 16: a 32 x 32
yard floor). **A seamless, flat floor:** when the realm can read its own `GameObjectDisplayInfo.dbc` (the dbc folder
the kit extracted from the host's own game, `AC_DATA_DIR/dbc`; read on the host's PC, never shipped), every floor and
wall block is sized from its model's bounds to exactly one tile and the floor's tops sit level with the ground, so the
floor is one flat surface with no gaps or steps (`OVBuild.ModelBox`, `ov_den.lua` `plan`). Without the file the blocks
stand at their own size on the ground and the spacing is "to verify" in game. The look of the white block, and how flat
the island's own ground is under a 32-yard room, are to verify in game.

**The edge:** every 2 seconds anyone outside the Den (more than `half + 14` yards from the middle, 12 yards below
the floor or 50 above it, or on another map) is put back in the room. GMs with `.gm on` are free. New characters
start in the room with their hearth set there.

## Midnight's decor placement, and where we are

Owner decision: "crafting means placing objects to the level of Midnight's full functionality". The table lists
what the official newest housing system does (sources at the bottom), and our state: **built**, **engine hook**
(needs the browser client, spec below), or **later**.

| Feature (Midnight) | Ours | State | Source |
|---|---|---|---|
| Decor catalog in categories (furniture, wall decor, walls/floors/ceilings, lighting, small decor, effects) | 378 props in 12 categories, a new `structure` one for floors, walls and stairs; in a Den also **every object** (any safe gameobject template, `.build find`) and **every model** (`.build models`) | built | [1] |
| Search and filters in the storage window | the Builder window's search and categories; the spawn menu's search and tabs | built | [2] |
| Click an item, click where it goes | spawn menu (Q) or the Builder, then a click: `.build spawnat` | built (Q: engine hook) | [2] |
| Move, any time | carry (G), the handles, `placeat`, `setpos` | built | [2] |
| Rotate in 15 degree steps (basic) | Turn button (15/45/90), Q/E while carrying | built | [1][3] |
| Rotate on any axis (advanced gimbal) | yaw, pitch, roll stored (`mod_builder_prop_tilt`); pitch and roll show only with mod-sandbox-core | built (tilt needs the module on the realm image) | [1] |
| Scale within generous limits | 0.1 to 5 in a Den (0.5 to 2.5 elsewhere; `OV_BUILD_SCALE_MIN/_MAX`), stored (`mod_builder_prop_scale`) | built; in-place resize needs the module or the engine (below) | [1][2] |
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
.build find <words> [page] | models <words> [page] | spawn t<entry> | spawn m<display>   any object, any model
.build lock | unlock | hide | show [all] | measure | align x|y|z|top|bottom | stack | stackon <id>
.build tilt yaw|pitch|roll <deg> | setrot <yaw> [pitch roll] | move <id> x y z [yaw pitch roll] | scale <id> <size>
```

In game: F7 (edit mode), the third tool bar (Group, Ungroup, Put away, Storage, Floor, Den), `/den` for the Den
panel outside edit mode.

## The editor: any object, to the world editors' level

Owner request (2026-10-30): "start placing any game object exactly to the level of forge / noggit". What that means
for a Den, and where we are. Object placement only: see "Terrain" below for why sculpting the ground is not in it.

| World editor feature | Ours | Where |
|---|---|---|
| Any object, not a short list | `.build find <words> [page]`: every gameobject template of the realm's world database of a safe kind (no AIName or ScriptName, a display; door, generic, chair, spell focus, text, or goober without quest, event, spell or trap; never chests, traps, transports, casters, aura generators, flags, capture points, destructible buildings). 30 a page. The Builder's and the spawn menu's **Every object** | `ov_build.lua` X.CMD.find, X.safeRow (the SQL filters and Lua checks again) |
| Any model | `.build models <words>`: every model (M2) in the host's own `GameObjectDisplayInfo.dbc`, by file name (WMO files left out). A model prop is the carrier template (`OV_BUILD_MODEL_CARRIER`, the catalog's Bottle) given that display through `GAMEOBJECT_DISPLAYID` each time it spawns; its entry is 2000000000 + the display, so copies, builds, prefabs, layouts, storage and undo carry it unchanged. The Builder's and the spawn menu's **Models** | X.CMD.models, X.readDisplays, spawn() |
| Search, categories, recent, favourites | the catalog's search and 12 categories; Every object and Models search on the realm (Enter; Down for the next page); Recent and Favourites keep found objects and models too (per character) | `Builder.lua` |
| Exact position | Properties: X, Y, Z boxes (Enter or Apply): `.build move <id> x y z yaw pitch roll` (one prop) / `setpos` (a group) | built |
| Nudges 0.01 to 10 yards | the Step button: 0.01, 0.1, 0.25, 1, 3, 10 yards (window and Properties' - / + on X, Y, Z) | built |
| Full rotation | yaw, pitch, roll boxes and - / + by 1, 5, 15, 45 or 90 degrees (`.build tilt yaw|pitch|roll <deg>`, each prop about itself; `.build setrot <yaw> [pitch roll]` for a group). The quaternion is the core's (rotation0-3, `GameObject::SetWorldRotationAngles`) | pitch and roll show only with **mod-sandbox-core** on the realm image (in `sources.lock`, so the kit's image has it once rebuilt from this branch); without it they are refused or dropped with a note, never stored wrong |
| Scale per object | Size box and - / + by 0.1, 0.1 to 5 in a Den, kept in `mod_builder_prop_scale`, put back on every spawn | built |
| Snap: grid | edit mode's Snap (0, 0.5, 1, 2 yards) | built (browser client) |
| Snap: to the floor, onto another object | `.build floor`; **Stack**: `.build stack` (the rest of the selection set on top of the first picked), `stackon <id>`, edit mode's Stack then a click on the prop, from the models' bounds | built (bounds need the host's dbc) |
| Align | `.build align x|y|z` (on the last picked), `align top|bottom` (faces, from the bounds) | built |
| Copy, paste, duplicate | Copy, Paste (at your feet or a click), Duplicate (V) | built |
| Multi-select, group move and rotate | Shift-click, box select, Select mine, groups; every op on the whole selection, one undo entry | built |
| Undo / redo history | 30 deep each, per character; a GM's rollback from the op log, after restarts too | built |
| Lock | `.build lock / unlock`: no move, turn, size, delete or clear until unlocked (stored, shared by the Den's builders) | built |
| Hide / show | `.build hide`, `show`, `show all`: out of the world and back, kept on file | built |
| Measure | `.build measure`: one prop from you (and its height and width from the bounds), or first to last picked: dx, dy, dz, the straight line and on the ground | built |
| Properties panel with numeric fields | Properties (`/builder` > Properties): X Y Z, Turn Pitch Roll, Size, each with - and +, Step and Angle, and the tools Lock, Unlock, Hide, Show all, Measure, Align X/Y/Z, Stack on, Bottoms, Undo, Redo | built |
| Gizmo handles in 3D | the browser client draws the arrows and the ring (edit mode); a stock client's UI can't draw in the 3D world, so there the Properties panel and the nudges are the gizmo | built in the browser client; numbers on a player's own game |
| Rotation and scale handles | pitch, roll and scale handles in the browser client | engine hooks 6 and 8 below |
| Collision against object models, surface snap on walls | | later: engine hook 7 |
| Terrain sculpting, texture painting, water, holes | | not planned: see Terrain |

Safety: every command is checked on the realm (role, area, budget, rate, numbers); the searches only ever return the
safe kinds and every placed entry is checked again; per Den the room has 1000 build points, the yard 300, a player 400
props (den.env); one spawn and one search a second, five moves a second, one paste every 5 seconds; a selection up to
40 props, a layout up to 800. A model or object's points rise with its size (1, plus 1 per 8 yards of its longest side,
up to 6). Nothing from the game's files is in this repo: the realm reads the host's own dbc folder on their PC.

**Desktop and browser.** In the browser client F7 is edit mode (the free camera, clicks, handles). On a player's own
game the camera can't leave the character, so F7 and `/edit` open the Builder and the Properties panel instead:
the same tools, placed at your feet and moved by exact numbers and nudges. The tools are the Leyline UI addon
(WrathUnleashedUI): built into the browser client; for a player's own game the launcher installs it (workstream K,
Addons: the pack `addons/pack/make-addonpack.py` takes `stream/fui-web/Interface/AddOns/WrathUnleashedUI`). A Den tells a
player whose game hasn't said hello within 20 seconds of logging in where to get it (ov_den.lua: the addon asks for
the Den's info on entering the world).

### Terrain (why sculpting is out of scope)

Noggit edits the map files themselves (ADT tiles: heights, texture layers, water, holes, doodad and WMO placements),
and a 3.3.5a client draws terrain only from the map files on the player's own disk (or the browser stream's slices):
the server sends no terrain. Sculpting a Den's ground would mean making new ADT files and getting them onto every
visitor's PC (a patch MPQ) or into the browser stream, and matching server maps, vmaps and mmaps for heights, line of
sight and paths: shipping map files, which this project doesn't do. So a Den is built from objects on top of the
island's ground; the flat white floor is the "terrain" you build on, and big flat objects (platforms, blocks, any
model) stand in for raised or sunk ground.

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
9. **Stack by a click.** `EditMode.StartStack()` waits for the next click; a click on a prop sends
   `.build stackon obj <object id>` (no client change: Clicked already passes the object id).
10. **A gameobject's display from its fields.** Model props (`.build models`) are the carrier template with
   `GAMEOBJECT_DISPLAYID` (field 8) set to another display: the client must draw the model of the field's display
   (on create and on a values update), not the template's, and fetch that model if the stream hasn't got it.

## Requests

- **Launcher addon install** (workstream K): the Leyline UI addon pack must keep `WrathUnleashedUI` (it does:
  `addons/pack/make-addonpack.py`); the Den's hint names "the Leyline launcher (Addons, then Leyline UI)", so the
  Addons page should call it that.
- **Launcher** (done in ed0fa37: My Den in the picker, Make my Den, the Rust presets; kept here for reference):
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

## The owner's test on a real PC

Needs: Docker Desktop running, the host kit from this branch (Make host kit), your own 3.3.5a game folder (the kit
extracts its dbc and maps into the realm's data volume at setup), the launcher. What you should see is under each step.

1. **Make the Den.** Launcher > Host > Make my Den (or `leyline host --ruleset den --private --name "My Den" --gm <you>`).
   The kit pulls or builds the realm image and starts it. The worldserver log has `mod-sandbox-core: on` (pitch, roll
   and in-place moves need it; without it everything else works). Play bar's realm picker: **My Den**.
2. **First login.** PLAY on My Den, make a character (or use one). You land alone in a plain white room: a flat floor
   of white blocks about 32 x 32 yards, four walls with a doorway to the south, four lights, no creatures, nobody else.
   Chat: "Welcome to the Den". Check: walk to every corner, the floor has no gaps or steps; jump off the yard's edge
   and within a few seconds you're back in the room. `.den` says you're the owner.
3. **The addon.** On your own game without Leyline UI: after about 20 seconds the Den says where to get it
   (launcher, Addons, Leyline UI). Install it from the launcher, restart the game, log in: no such message; `/den`
   opens the Den panel. In the browser client it's built in.
4. **Any object.** `/builder`, Category: Every object, type `bench`, Enter: a page of benches from the whole game
   (not only the catalog); Down at the end loads more. Double-click one: it appears at your feet. Category: Models,
   type `lamp`, Enter: models by file name; double-click one: that model appears (on the carrier). Chat:
   `.build find chest` finds no chests (loot), `.build find 1234` checks one entry.
5. **Exact transforms.** Properties: type X, Y, Z and a Turn, Enter: it jumps exactly there. Step 0.01, X + ten times:
   it creeps 0.1 yard. Size + : 1.10. Pitch 20, Enter: it leans (needs the module; else the panel says so). Undo
   (Ctrl+Z / Undo) steps back through each change, Redo forward again.
6. **Groups.** Select two props (browser: click, Shift-click; own game: `.build near`, `.build select <n>`, Select mine),
   Copy, Paste, Duplicate; Align X lines them up; Stack on (first pick the table, then the vase) sets the vase on the
   table's top; Measure says the distance; Lock then try to move: "is locked"; Hide, then Show all.
7. **Restart.** Stop my realm, Host again (or restart Docker), log in: everything is where you left it, sizes, tilts,
   models, locks and hidden props included; you log in inside your Den.
8. **A friend.** Den panel > Invite a friend: the link (Ctrl+C). Your friend joins with it, lands in the room, can
   look but not build ("You're visiting"). Den panel > name > Can build: now they place and move props; View only takes
   it back. `.den home` (Den panel: Back to the room) brings anyone back to the middle.
9. **Layouts.** `.den save house`, `.den room stone`, `.den load house replace`: the whole Den comes back.

Report back what differs, especially: the white block's look and the floor's flatness, the carrier's size for models
(a model should appear at its own size), and any model that shows nothing or looks wrong.
