# Leyline Modes: write your own minigame

A **mode** is one Lua file. Open `/modes` in game:
- **Play solo** runs a mode on your own.
- **Host here** opens a game where you stand and invites your party.
- **Bumper Balls** and **Coin Dash** ship as built-in examples.
- **Mode editor** (or `/modes edit`) writes modes in game. It has a template, the two built-ins to start from, **Run solo**, **Save** and **Publish**.

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
