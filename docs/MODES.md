# Leyline Modes: write your own minigame

A **mode** is one Lua file. Open `/modes` in game:
- **Play solo** runs a mode on your own.
- **Host here** opens a game where you stand and invites your party.
- **Bumper Balls** and **Coin Dash** ship as built-in examples, and **Pressure Plates** is made only of devices.
- **Mode editor** (or `/modes edit`) writes modes in game. It has a template, the two built-ins to start from, **Run solo**, **Save** and **Publish**.
- **Device editor** (or `/modes devices`) builds a mode from parts with no code. See [Devices](#devices) below.

## How it runs

- **The host's client runs the script.** It runs in a sandbox: the safe parts of `string`, `math` and `table`, plus the API below. The sandbox has no game UI, no chat, no network and no way to load more code.
- **Everyone else only draws what the host sends** and sends back the keys the mode asked for. Joining a mode never runs its code on your client.
- **Each callback has a 30 ms budget.** A script that loops forever is stopped with an error.
- **Limits:** 300 entities at most, and 14 KB of script.
- **Publishing:** published modes are reviewed by a GM before others can see them, but you can always host your own.

## The script

```lua
Mode.Title   = "Coin Dash"                       -- shown in /modes and on the banner
Mode.Keys    = { "W", "A", "S", "D", "SPACE" }   -- captured from every player while they play (Esc lets go)
Mode.Players = { 1, 8 }                          -- min, max

function OnStart(players) end      -- players = { "Ann", "Bo" }; build the arena here
function OnTick(dt) end            -- 20 times a second, dt = 0.05
function OnKey(player, key, down) end
function OnLeave(player) end
function OnJoin(player) end        -- someone joined a game that was already running
```

Allowed keys: W A S D Q E F R SPACE UP DOWN LEFT RIGHT 1 2 3 4.

## The API

| Call | What it does |
|---|---|
| `Ent.Spawn{ shape = "box"\|"ball"\|"cyl", x, y, z, sx, sy, sz, yaw, color = "ff8800" }` → id | Adds a shape. Sizes are full widths in yards, and yaw is in degrees. |
| `Ent.Move(id, x, y, z [, yaw])` | Moves a shape. Players see it eased smoothly. |
| `Ent.Set(id, { color = "...", sx = 2, ... })` | Changes any field. |
| `Ent.Remove(id)` / `Ent.Get(id)` | Removes a shape, or reads its fields. |
| `Players.List()` / `Players.Count()` | The players in the game. |
| `HUD.Banner(text)` / `HUD.Say(text)` | Sets the top banner, or posts a line under it for everyone. |
| `Score.Set(p, n)` / `Score.Add(p, n)` / `Score.Get(p)` | The scoreboard on everyone's screen. |
| `Camera.Follow(player, id [, distance, height])` / `Camera.Top([height])` | Sets that player's camera, or a top-down view for everyone. |
| `Timer.After(seconds, fn)` | Runs `fn` later. |
| `Random(n)` | Returns 1..n from a per-game seed. |
| `Mode.End(text)` | Ends the game and shows everyone the text. |
| `print(...)` | Writes to the host's screen, for debugging. |

**Coordinates:** yards, in a frame placed where the host stood. +x is right, +y is up and +z is forward, so build around `0, 0, 0`.

## Example

`Modes.lua` → `M.BUILTIN` is Bumper Balls, about 120 lines. It has:
- an arena and one ball per player
- WASD rolling and a Space dash
- ball-to-ball bumps
- rounds and scores
- a follow camera

## Publishing

1. Write the script and test it with **Play solo**.
2. Publish from `/modes`. It stays "in review" until a GM runs `.modes approve <key>`.
3. Once approved, it appears for everyone on the realm.

**GM commands:** `.modes pending`, `.modes approve <key>`, `.modes reject <key>`.

## Devices

A **device mode** is built from parts, with no code. You place devices, set their properties, and wire them together. A **wire** says "when device A does *event*, call *function* on device B", with an optional argument.

**Pressure Plates** is the sample. Step on the three pads in order: the door opens, the timer stops and your time shows. Walk through the door to finish. Open it with **Sample** in the device editor, or play it with `/modes plates`.

### The device editor

Open it with `/modes devices`, or with **Device editor** in the mode editor. The layout is drawn in front of you while you edit.

- **Add:** pick a kind, then **At my spot** (where you stood when the editor opened) or **Click to place** (click the ground; right-click cancels). Points snap to half a yard.
- **Devices:** click one to select it. It turns white and gets a marker. **Delete**, **Move: click** and **Move to my spot** act on the selected device.
- **Properties:** the selected device's settings. Press Enter to apply one. On/off settings take `0` or `1`.
- **Wires:** pick the source device and its event, the target device and its function, and an optional argument, then **Add wire**. Each wire in the list has an **x** to delete it.
- **Play** tests the layout where the preview is. **Stop** (or **Leave**) brings you back to the editor. Play runs a copy, so nothing that happens in a test changes your layout.
- **Save** keeps the layout in this browser and on your account. **Open mine** goes through your saved layouts.
- **Publish** sends it for GM review, the same as a script. **As script** shows the layout as mode text.

### The devices

Every device has `name`, `x`, `y` and `z`. Coordinates are yards in the arena: +z is forward, and the floor is at `y = 0`.

| Device | Properties | Events | Functions |
|---|---|---|---|
| **Spawn Point** | `speed` 7, `cam` 9 (follow distance, 0 = none), `color` (blank = one per player) | `spawned` | `respawn`, `respawnall` |
| **Trigger Volume** | `w` 3, `d` 3, `h` 3, `on` 1, `once` 0, `show` 1, `color`, `offcolor`, `hitcolor` | `enter`, `leave`, `denied` (walked in while off) | `enable`, `disable`, `reset` |
| **Button** | `size` 1, `range` 2.5, `on` 1, `cooldown` 0.5, `color` | `pressed`, `denied` | `enable`, `disable`, `reset` |
| **Timer** | `seconds` 30, `dir` down/up, `auto` 0, `show` 1 (on the banner), `label` "Time" | `started`, `stopped`, `done` | `start`, `stop`, `reset`, `add` (seconds) |
| **Counter** | `start` 0, `target` 3, `show` 0, `label` | `changed`, `reached` | `add` (default 1), `sub`, `set`, `reset` |
| **Score Keeper** | `points` 1, `target` 0 (none) | `reached` | `add` (points), `sub`, `reset`, `win` (ends the game, text optional) |
| **Teleporter** | `r` 1.5, `tx`, `ty`, `tz` (the target), `on` 1, `show` 1, `color` | `teleported` | `enable`, `disable`, `send`, `reset` |
| **Round Manager** | `rounds` 1, `delay` 1, `wait` 3, `auto` 1, `endtext` "Game over" | `roundstart`, `roundend`, `gameover` | `start`, `endround` (text optional), `finish` (text optional) |
| **HUD Message** | `text` "Hello", `where` say/banner | `shown` | `show` (the argument replaces the text), `clear` |
| **Mover** | `shape` box/ball/cyl, `sx` `sy` `sz` 2, `yaw`, `color`, `path`, `speed` 3, `loop` once/loop/pingpong, `auto` 0, `solid` 1 | `arrived`, `returned` | `start`, `stop`, `back`, `reset` |

How they behave:
- **Players:** each player is a ball at a Spawn Point, rolled with WASD. With more players than spawn points, they share. A layout with a Button also takes E, which presses a button within `range`.
- **Who did it:** events remember the player who set them off. Score Keeper `add` gives the points to that player, and Teleporter `send` moves that player.
- **Text:** in HUD text, `endtext` and wire arguments, `{player}` is that player and `{6}` is device 6's value. The value is the time for a Timer, the number for a Counter, the round for a Round Manager, and the points for a Score Keeper.
- **The area:** `set area=` is half the arena's width (4 to 60 yards; the default is 20). Players and teleports stay inside it.
- **Mover paths** are points relative to where the mover starts, like `0,3,0/4,3,0` (up to 8). A mover with no path is a plain shape, such as a wall. A solid mover blocks players.
- **Rounds:** each round resets every device except Round Managers and Score Keepers, and puts the players back at their spawn. Without a Round Manager, the game starts once and ends when a Score Keeper's `win` runs.

### Limits and safety

- A layout has at most 64 devices and 128 wires.
- Wires run on the host, inside the mode sandbox, under the same 30 ms guard as scripts.
- At most 64 events go through wires each tick. If a wire loop makes more, the rest are dropped, the host sees a note, and the game keeps running.
- The layout is data, not code. The realm marks a mode that is only devices as `(devices)` in `.modes pending`. It is still reviewed like any mode.

### The layout as text

**As script** shows a layout like this:

```lua
Mode.Title = "Pressure Plates"
Mode.Players = { 1, 8 }
Devices.Run[=[
set area=14 floor=34384a
d 1 spawn name=Start z=-9
d 2 trigger name=Pad%201 x=-6 z=-2 once=1 color=ff5a3c
d 5 counter name=Pads%20done
w 2 enter 5 add
]=]
```

- `d <id> <kind> key=value ...` is a device. It lists only the settings that differ from the defaults. Spaces and symbols in values are written as `%20` and so on.
- `w <from> <event> <to> <function> [argument]` is a wire.

A script can use devices too. `Devices.Run` sets up `OnStart`, `OnTick`, `OnKey`, `OnLeave` and `OnJoin`. After it:
- `Devices.On(id, event, function(player) ... end)` runs your code on a device event.
- `Devices.Call(id, fn, arg, player)` calls a device's function.
