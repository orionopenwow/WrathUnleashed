# mod-sandbox-core

An AzerothCore module (3.3.5a, the mod-playerbots fork pinned in `realm/custom/sources.lock`) for the realm's
Builder (`realm/custom/lua_scripts/ov_build.lua`): props move, turn, tilt and change size **in place**, keep their
GUID, and everyone near them sees the change at once.

| File | What |
|---|---|
| `src/SandboxCore.cpp` | the scripts: the bridge, spawn / move / scale / despawn, the registry, the free list |
| `src/SandboxMath.h` | pure helpers (quaternions, the core's packed rotation, the free list, the rate window, the protocol) |
| `src/mod_sandbox_core_loader.cpp` | `Addmod_sandbox_coreScripts()` |
| `conf/mod_sandbox_core.conf.dist` | settings (all optional; the defaults are built in) |
| `data/sql/db-characters/base/sandbox_core.sql` | `sandbox_go_scale`, `sandbox_go_registry`, `sandbox_core_status` |
| `tests/test_sandbox_math.cpp` | `g++ -std=c++17 -I../src test_sandbox_math.cpp && ./a.out` (no core needed) |
| `../../lua_scripts/ov_sandbox_core.lua` | the Lua side: the global `Sandbox` table |

## How Lua reaches it

mod-ale (pinned 84b85cc) has no way for another module to add Lua functions: its function tables are compiled into
mod-ale, and its `lua_State` is only reachable by including mod-ale's headers and linking its Lua, which the
module build doesn't set up. A queued chat command (`RunCommand`) runs a tick later and can't return anything.
So the module uses a **synchronous packet bridge**:

1. Lua builds a packet with opcode `CMSG_DBLOOKUP` (0x002, a client-to-server debug opcode the server never sends)
   and sends it to a player's own session: `player:SendPacket(packet)`.
2. `WorldSession::SendPacket` calls `ServerScript::OnPacketSent` first. The module reads the request, does the
   work and rewrites the packet in place with the reply. (The hook passes it as `const&`; the object is mod-ale's
   own non-const `WorldPacket`, so the `const_cast` is well defined.)
3. `ServerScript::CanPacketSend` then returns false for that opcode, so the packet never reaches a socket.
4. Back in Lua, `player:SendPacket` has returned and the same packet object now holds the reply.

Request: `uint32 'SBX1', uint8 version (1), uint8 op, args`. Reply: `uint32 'SBXR', uint8 status, results`.

| op | args | result |
|---|---|---|
| 1 ping | | uint32 version, uint8 move mode |
| 2 spawn | uint32 prop id, uint32 entry, uint32 map, float x y z, float qx qy qz qw, float size (0 = the template's, below 0 = the size kept for this prop) | uint64 GUID |
| 3 move | uint64 GUID, float x y z, float qx qy qz qw | uint64 GUID (the same one in mode 0) |
| 4 scale | uint64 GUID, float size (0 = back to the template's) | |
| 5 despawn | uint64 GUID, uint8 forget (1 = also drop its kept size) | |
| 6 find | uint32 prop id | uint64 GUID of the prop's object in the world (after a Lua reload) |

Only server code can send a packet to a session, so a player can't reach the bridge; the realm scripts are the
only callers, and they check role, plot, budget, rate and distance first (ov_build.lua). Lua sends nothing until
it has read the `sandbox_core_status` row the module writes at startup (and removes at shutdown) and a ping has
come back, so a realm without the module never sends a bridge packet.

## Moving in place, and the choice for stock clients

- A GameObject's create block carries its position from `m_stationaryPosition` (Object.cpp,
  `UPDATEFLAG_STATIONARY_POSITION`), which only `GameObject::Create` sets and which is protected. So the module
  spawns builder props as its own subclass, `SandboxGameObject`, which can update it. Only those objects (in the
  registry, and checked with `dynamic_cast`) are ever moved, scaled or removed: never the world's own spawns.
- **Move (mode 0, the default):** stationary position and rotation, then `Map::GameObjectRelocation` (grid cell,
  collision model, visibility), then every player who has it on screen gets `SMSG_DESTROY_OBJECT` and a fresh create
  block (`SandboxCore.Refresh = 1`). The GUID stays. The Leyline browser client re-reads a re-created object's pose
  (`benilla-app/src/net/objects.rs`: "A re-create is a fresh snapshot: refresh identity and pose"), so the edit shows
  at once and edit mode's handles stay on the same object.
- **Stock 3.3.5a clients:** the core's own `.gobject move` comment says the stock client keeps recently destroyed
  objects and, when a create block for the same GUID comes again, reuses the position it knew and skips the new
  one. So a destroy + create with the same GUID is *not* reliable there. For a realm that serves stock clients,
  set `SandboxCore.MoveMode = 1`: every move respawns the prop under a fresh GUID (as ov_build.lua's fallback
  does), and Lua takes the new GUID from the reply.
- **Size:** `OBJECT_FIELD_SCALE_X`, the collision model rebuilt, and the same refresh. Kept in `sandbox_go_scale`.
- **Rotation:** a full quaternion (`gameobject.rotation0..3` order: x, y, z, w). `Sandbox.QuatFromYawPitchRoll`
  builds the one `GameObject::SetWorldRotationAngles(yaw, pitch, roll)` would: R = Rz(yaw) Ry(pitch) Rx(roll).
  The collision model follows position and size, not tilt (the core's models only turn about z).
- **Rows:** builder props are never saved into the world's `gameobject` table (ov_build.lua keeps its own
  `mod_builder_props`); the module mirrors each one in `sandbox_go_registry` (map, entry, live GUID counter,
  x y z, rotation0..3, size).

## The GUID free list

A GameObject GUID counter is 24 bits per map, and the core shuts the realm down when it runs out. Every move used
to be a respawn with a new GUID, and so is every prop that comes back after its grid unloads. Now a builder object
that leaves the world (despawn, grid unload) puts its counter on its map's free list; the next builder spawn takes
the oldest one that has waited `SandboxCore.ReuseDelaySec` (300 s) and is not in the map's object store under its
old or new entry. In mode 0 a move costs no GUID at all.

## Limits

`SandboxCore.MaxMoveDistance` (200 yd a move), `MinScale` / `MaxScale` (0.1 to 5; ov_build.lua allows 0.5 to 2.5),
`MaxOpsPerSecond` (400 for the realm), `MaxObjects` (20000), and only base continent maps (no instances).

## Build

`realm/custom/fetch.sh` copies this folder into `acore/modules/` (sources.lock line `mod-sandbox-core local - -`,
without `tests/`), so "Build custom realm.bat" and the `wu-images` workflow build it like any other module. The
workflow's `sandbox-core` job runs the unit test and a syntax-only compile against the pinned core's headers.

## Verify with two characters

On a realm running the new image (`wu-ac-wotlk-worldserver` built from this branch) with `ov_build.lua` and
`ov_sandbox_core.lua` uploaded:

1. The worldserver log at startup says `mod-sandbox-core: on (move mode 0, ...)`, and
   `SELECT * FROM sandbox_core_status` (characters database) has one row.
2. Character A (a GM, or granted with `.build grant A`) and character B log in and stand in Goldshire green
   (`.build where`), within sight of each other.
3. A: `.build spawn chair`. Both see it. `SELECT prop_id, guid_low FROM sandbox_go_registry` has the prop and
   its GUID counter (a row there means the module spawned it, so it can move in place).
4. A: `.build near`, note the prop id `N` (or read `sel=` in the Properties panel's title), then
   `.build move N <x+2> <y> <z> 90 0 20`. B sees it jump 2 yards, face east and lean 20 degrees, with no
   despawn-respawn fade on the browser client; `guid_low` in `sandbox_go_registry` is unchanged.
5. A: `.build scale N 2`. B sees it double. `SELECT * FROM sandbox_go_scale` has it.
6. A (browser client, F7 edit mode): click the chair, drag the up arrow, let go. B sees one change, when A lets go.
   `.build undo` puts it back for both. A GM's `.build rollback A 3` undoes the last three changes for both.
7. Without the module (the stock image, or `OV_BUILD_CORE=0` in the worldserver environment) steps 4 to 6 still
   work: the prop is respawned under a new GUID and B sees it reappear at the new spot; tilt is dropped with a note.

