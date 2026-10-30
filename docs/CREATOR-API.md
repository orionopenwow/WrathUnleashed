# Leyline Modes: the creator API

<!-- Made by tools/creator-api/gen.lua from stream/fui-web/Interface/AddOns/WrathUnleashedUI/ModeAPI.lua. Edit that file, then run the tool. -->

Version 2. A **mode** is one Lua script: a small game that a host plays with their party. Write one in game with `/modes edit`. This page lists everything a script can use.

## How a script runs

- **The host's client runs the script**, in a sandbox. It has the safe parts of `string`, `math` and `table` and the API below. It has no game UI, no chat, no network and no way to load more code.
- **Everyone else only draws what the host sends**, and sends back the keys the mode asked for. Joining a mode never runs its code on your client.
- **Every call into the script has a time budget** of 30 ms: loading it, each callback and each timer. A script that runs too long, such as an endless loop, is stopped. Only that mode stops, and the editor shows the line it was on.
- **Coordinates** are yards, in a frame placed where the host stood: +x is right, +y is up and +z is forward. Build around `0, 0, 0`.
- **Publishing:** a GM reviews every published mode before others can see it. You can always play and host your own.

## The script editor

- `/modes edit` opens it. It has line numbers and keyword colours (**Colours** turns them off).
- **Play** runs a copy of the script here, on your own. **Play Here** hosts a copy where you stand and invites your party nearby. The realm checks it first.
- **Stop** ends the test and brings the editor back. A test never changes your text or your saved draft.
- **Save** keeps the script in this browser and on your account. **Save while a test runs to hot-reload it**: the new script takes over, and State values and scores are kept. The old shapes go, and `OnStart` runs again. If the new script has an error, the old one keeps running.
- **The console** lists errors with their line. Click one to jump to that line. `print` output shows there too.
- **Check** looks for problems without running anything. **Publish** saves, then sends the script for GM review.
- **Start from** opens the template, the built-in modes or the two examples below. **API** lists the functions in the console.

## Settings

| Setting | What it does |
|---|---|
| `Mode.Title = "My Mode"` | Shown in /modes and on the banner (40 characters). |
| `Mode.Keys = { "W", "A", "S", "D" }` | The keys captured from every player while they play. Esc lets go. |
| `Mode.Players = { 1, 8 }` | The fewest and most players. |
| `Mode.Api = 2` | The API version the script needs. An older client says so instead of running it. *(new in 2)* |

Keys a mode can ask for: `W` `A` `S` `D` `Q` `E` `F` `R` `SPACE` `UP` `DOWN` `LEFT` `RIGHT` `1` `2` `3` `4`.

## Callbacks

Define these as globals. The host calls them, each under the time budget.

| Callback | When |
|---|---|
| `function OnStart(players)` | The game starts. players is a list of names, like { "Ann", "Bo" }. Build the arena here. |
| `function OnTick(dt)` | 20 times a second; dt is 0.05. |
| `function OnKey(player, key, down)` | A player pressed (down = true) or let go of one of Mode.Keys. |
| `function OnJoin(player)` | Someone joined a game that was already running. |
| `function OnLeave(player)` | Someone left. |

## Functions

### Ent

Shapes in the arena. Every player sees them; moves are eased smoothly.

| Call | Returns | What it does |
|---|---|---|
| `Ent.Spawn{ shape, x, y, z, sx, sy, sz, yaw, color }` | `id` | Adds a shape: "box", "ball" or "cyl". Sizes are full widths in yards, yaw is degrees, color is "rrggbb". |
| `Ent.Move(id, x, y, z [, yaw])` |  | Moves a shape. |
| `Ent.Set(id, { field = value, ... })` |  | Changes any field: x y z sx sy sz yaw color shape. |
| `Ent.Remove(id)` |  | Removes a shape. |
| `Ent.Get(id)` | `table or nil` | A copy of a shape's fields. |
| `Ent.Clear()` |  | Removes every shape. *(new in 2)* |
| `Ent.Count()` | `n` | How many shapes there are. *(new in 2)* |

### Players

The players in the game, by name.

| Call | Returns | What it does |
|---|---|---|
| `Players.List()` | `{ names }` | A copy of the list. |
| `Players.Count()` | `n` | How many. |
| `Players.Has(player)` | `true/false` | Whether that player is in the game. *(new in 2)* |

### HUD

Text on the players' screens. Text is one line, 120 characters at most.

| Call | Returns | What it does |
|---|---|---|
| `HUD.Banner(text)` |  | Sets the banner at the top, for everyone. |
| `HUD.Say(text)` |  | Posts a line under the banner, for everyone (a broadcast). |
| `HUD.Tell(player, text)` |  | Posts a line under the banner for one player only. *(new in 2)* |
| `HUD.Text(slot, text [, player])` |  | Your own HUD: a named line in the panel on the left (8 slots). With a player, only they see it. Empty text clears it. *(new in 2)* |

### Score

The scoreboard on everyone's screen, one number per player.

| Call | Returns | What it does |
|---|---|---|
| `Score.Set(player, n)` |  | Sets a score. |
| `Score.Add(player, n)` |  | Adds to a score (n can be negative). |
| `Score.Get(player)` | `n` | Reads a score (0 if none). |
| `Score.Top()` | `{ { name, score }, ... }` | Every score, highest first. *(new in 2)* |
| `Score.Reset()` |  | Sets every score to 0. *(new in 2)* |

### Camera

Each player's camera.

| Call | Returns | What it does |
|---|---|---|
| `Camera.Follow(player, id [, distance, height])` |  | That player's camera follows a shape. |
| `Camera.Top([height])` |  | A top-down view for everyone. |

### Timer

Run code later. Each timer runs under the time guard, like a callback.

| Call | Returns | What it does |
|---|---|---|
| `Timer.After(seconds, fn)` | `id` | Runs fn once, later. |
| `Timer.Every(seconds, fn)` | `id` | Runs fn again and again (0.05 s at the shortest). *(new in 2)* |
| `Timer.Cancel(id)` |  | Stops a timer. *(new in 2)* |

### State

Named values with change events. They survive a hot reload; handlers do not.

| Call | Returns | What it does |
|---|---|---|
| `State.Set(key, value)` |  | Sets a value (a number, text, true/false or nil). Handlers run only if it changed. *(new in 2)* |
| `State.Get(key [, default])` | `value` | Reads a value. *(new in 2)* |
| `State.On(key, fn(value, old, key))` |  | Runs fn when key changes. Use "*" for every key. *(new in 2)* |

### Vec

Small helpers for positions on the ground (x, z) and angles in degrees.

| Call | Returns | What it does |
|---|---|---|
| `Vec.Len(x, z)` | `length` | The length of (x, z). *(new in 2)* |
| `Vec.Dist(x1, z1, x2, z2)` | `distance` | The distance between two points on the ground. *(new in 2)* |
| `Vec.Dist3(x1, y1, z1, x2, y2, z2)` | `distance` | The distance in 3D. *(new in 2)* |
| `Vec.Norm(x, z)` | `x, z, length` | (x, z) scaled to length 1 (0, 0 stays 0, 0). *(new in 2)* |
| `Vec.Angle(x, z)` | `degrees` | The yaw that faces along (x, z), as Ent.Move takes it. *(new in 2)* |
| `Vec.Dir(degrees)` | `x, z` | The unit step for a yaw. *(new in 2)* |
| `Vec.Rotate(x, z, degrees)` | `x, z` | (x, z) turned by a yaw. *(new in 2)* |
| `Vec.Lerp(a, b, t)` | `number` | From a to b by t (0 to 1). *(new in 2)* |
| `Vec.Clamp(v, low, high)` | `number` | v kept between low and high. *(new in 2)* |

### Mode

The mode itself (see the settings above).

| Call | Returns | What it does |
|---|---|---|
| `Mode.End(text)` |  | Ends the game and shows everyone the text. |

### Other globals

| Call | Returns | What it does |
|---|---|---|
| `Random(n)` | `1..n` | A whole number from 1 to n, from a seed shared by the game. |
| `print(...)` |  | Writes to the host's screen and the editor's console, for debugging. |

### Devices (device modes only)

A mode that uses `Devices.Run` gets this table too. See MODES.md for the devices and wires.

| Call | What it does |
|---|---|
| `Devices.Run[=[ layout ]=]` | Builds the mode from devices and wires (see MODES.md). |
| `Devices.On(id, event, fn(player))` | Runs fn on a device's event. |
| `Devices.Call(id, function, argument, player)` | Calls a device's function. |

## The standard library

- Base functions: `pairs` `ipairs` `next` `select` `type` `tostring` `tonumber` `unpack` `pcall` `error` `assert`. `pcall` can't catch the time budget: a script that catches it is stopped anyway.
- `string`: Lua's string library without string.dump. string.rep's result is capped at 64 KB.
- `math`: Lua's math library without math.random and math.randomseed (use Random).
- `table`: Lua's table library.

## Limits

| Limit | What |
|---|---|
| 14336 | bytes of script (about 14 KB) |
| 30 | milliseconds each call into your script may run; then the mode stops with the line it was on |
| 300 | shapes at once |
| 64 | timers waiting at once |
| 16 | timers that fire in one tick (the rest fire next tick) |
| 128 | State keys |
| 8 | change events inside change events |
| 8 | HUD.Text slots |
| 120 | characters in one HUD line |

The realm also limits how often you can save (one draft every 2 s), test with Play Here (one every 5 s) and publish (one every 10 s).

## Not available

A script that names one of these is refused before it runs, with the line: `getfenv` `setfenv` `loadstring` `loadfile` `dofile` `require` `getmetatable` `setmetatable` `rawget` `rawset` `rawequal` `newproxy` `collectgarbage` `gcinfo` `debug` `coroutine` `os` `io` `LeylineMode` `LeylineGuard`. So is `string.dump`, and `s:rep(n)` (write `string.rep(s, n)`, which is capped). Nothing else from the game is in the sandbox either.

## Examples

Both use only the API on this page. Open them in the editor with **Start from**, or play them with `/modes collect` and `/modes hill`.

### Coin Collect

```lua
-- Coin Collect: grab gold for 45 seconds. Your own count and the leader show on the left.
Mode.Title = "Coin Collect"
Mode.Keys = { "W", "A", "S", "D" }
Mode.Players = { 1, 8 }
Mode.Api = 2

local R, SPEED, GAME = 11, 7, 45
local COLORS = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local runners, coins, joined = {}, {}, 0

local function spawnCoin()
    local x, z = Vec.Dir(Random(360))
    local d = Random(100) / 100 * (R - 1.5)
    local id = Ent.Spawn{ shape = "cyl", x = x * d, y = 0.8, z = z * d, sx = 0.8, sy = 0.15, sz = 0.8, color = "ffd700" }
    coins[id] = { x = x * d, z = z * d }
end

local function showHud()
    local top = Score.Top()[1]
    HUD.Text("lead", top and top.score > 0 and ("Leader: " .. top.name .. " (" .. top.score .. ")") or "Leader: nobody yet")
    for p in pairs(runners) do HUD.Text("mine", "Your coins: " .. Score.Get(p), p) end
end

local function addRunner(p)
    joined = joined + 1
    local x, z = Vec.Dir(joined * 137)
    local r = { x = x * 4, z = z * 4, keys = {} }
    r.id = Ent.Spawn{ shape = "ball", x = r.x, y = 0.6, z = r.z, sx = 1.2, sy = 1.2, sz = 1.2, color = COLORS[(joined - 1) % #COLORS + 1] }
    runners[p] = r
    Camera.Follow(p, r.id, 10, 9)
end

-- The clock is State, so a hot reload keeps the time left. Its change event drives the HUD and the end.
State.On("left", function(left)
    HUD.Text("time", "Time: " .. left)
    if left == 10 then HUD.Say("10 seconds left!") end
    if left <= 0 then
        local top = Score.Top()[1]
        Mode.End(top and (top.name .. " wins Coin Collect with " .. top.score .. "!") or "Nobody wins.")
    end
end)

function OnStart(players)
    Ent.Spawn{ shape = "cyl", x = 0, y = -0.25, z = 0, sx = R * 2, sy = 0.5, sz = R * 2, color = "2d4a6a" }
    for _, p in ipairs(players) do addRunner(p); Score.Add(p, 0) end
    for i = 1, 10 do spawnCoin() end
    HUD.Banner("Coin Collect")
    HUD.Say("WASD to run. Grab the gold!")
    State.Set("left", State.Get("left", GAME))
    HUD.Text("time", "Time: " .. State.Get("left"))
    Timer.Every(1, function() State.Set("left", State.Get("left") - 1) end)
    Timer.Every(3, function() if Ent.Count() < 40 then spawnCoin() end end)
    showHud()
end

function OnJoin(player) addRunner(player); Score.Add(player, 0); showHud() end

function OnLeave(player)
    local r = runners[player]
    if r then Ent.Remove(r.id) end
    runners[player] = nil
end

function OnKey(player, key, down)
    local r = runners[player]
    if r then r.keys[key] = down or nil end
end

function OnTick(dt)
    for p, r in pairs(runners) do
        local ax = (r.keys.D and 1 or 0) - (r.keys.A and 1 or 0)
        local az = (r.keys.W and 1 or 0) - (r.keys.S and 1 or 0)
        ax, az = Vec.Norm(ax, az)
        r.x, r.z = r.x + ax * SPEED * dt, r.z + az * SPEED * dt
        local nx, nz, d = Vec.Norm(r.x, r.z)
        if d > R - 0.6 then r.x, r.z = nx * (R - 0.6), nz * (R - 0.6) end
        Ent.Move(r.id, r.x, 0.6, r.z)
        for id, c in pairs(coins) do
            if Vec.Dist(r.x, r.z, c.x, c.z) < 1 then
                Ent.Remove(id)
                coins[id] = nil
                Score.Add(p, 1)
                if Score.Get(p) % 5 == 0 then HUD.Tell(p, Score.Get(p) .. " coins!") end
                spawnCoin()
                showHud()
            end
        end
    end
end
```

### King of the Hill

```lua
-- King of the Hill: stand alone on the hill in the middle to score a point a second. First to 20 wins.
Mode.Title = "King of the Hill"
Mode.Keys = { "W", "A", "S", "D", "SPACE" }
Mode.Players = { 1, 8 }
Mode.Api = 2

local R, HILL, WIN = 12, 2.5, 20
local COLORS = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local balls, hill, joined = {}, nil, 0

local function addBall(p)
    joined = joined + 1
    local x, z = Vec.Dir(joined * 360 / 8)
    local b = { x = x * (R - 2), z = z * (R - 2), vx = 0, vz = 0, keys = {}, dash = 0 }
    b.id = Ent.Spawn{ shape = "ball", x = b.x, y = 0.7, z = b.z, sx = 1.4, sy = 1.4, sz = 1.4, color = COLORS[(joined - 1) % #COLORS + 1] }
    balls[p] = b
    Camera.Follow(p, b.id, 11, 8)
end

-- Who holds the hill is State: "" (nobody), "*" (contested) or a name. The change event recolours it.
local function showHill(who)
    if not hill then return end
    if who == "" then Ent.Set(hill, { color = "8a8aa0" }); HUD.Text("hill", "The hill is free")
    elseif who == "*" then Ent.Set(hill, { color = "ff5050" }); HUD.Text("hill", "The hill is contested!")
    else Ent.Set(hill, { color = "ffd24a" }); HUD.Text("hill", who .. " holds the hill"); HUD.Say(who .. " takes the hill!") end
end
State.On("holder", showHill)

function OnStart(players)
    Ent.Spawn{ shape = "cyl", x = 0, y = -0.25, z = 0, sx = R * 2, sy = 0.5, sz = R * 2, color = "3a3550" }
    hill = Ent.Spawn{ shape = "cyl", x = 0, y = 0.05, z = 0, sx = HILL * 2, sy = 0.1, sz = HILL * 2, color = "8a8aa0" }
    for _, p in ipairs(players) do addBall(p); Score.Add(p, 0) end
    HUD.Banner("King of the Hill - first to " .. WIN)
    HUD.Say("WASD to roll, Space to dash. Hold the hill alone!")
    showHill(State.Get("holder", ""))
    Timer.Every(1, function()
        local who = State.Get("holder", "")
        if who == "" or who == "*" then return end
        Score.Add(who, 1)
        HUD.Text("you", "Your points: " .. Score.Get(who) .. " / " .. WIN, who)
        if Score.Get(who) >= WIN then Mode.End(who .. " is King of the Hill!") end
    end)
end

function OnJoin(player) addBall(player); Score.Add(player, 0) end

function OnLeave(player)
    local b = balls[player]
    if b then Ent.Remove(b.id) end
    balls[player] = nil
end

function OnKey(player, key, down)
    local b = balls[player]
    if not b then return end
    b.keys[key] = down or nil
    if key == "SPACE" and down and b.dash <= 0 then
        local nx, nz = Vec.Norm(b.vx, b.vz)
        b.vx, b.vz, b.dash = nx * 12, nz * 12, 2
    end
end

function OnTick(dt)
    local on, who = 0, ""
    for p, b in pairs(balls) do
        local ax = (b.keys.D and 1 or 0) - (b.keys.A and 1 or 0)
        local az = (b.keys.W and 1 or 0) - (b.keys.S and 1 or 0)
        b.vx, b.vz = (b.vx + ax * 16 * dt) * 0.92, (b.vz + az * 16 * dt) * 0.92
        b.dash = Vec.Clamp(b.dash - dt, 0, 2)
        for q, o in pairs(balls) do
            local d = Vec.Dist(b.x, b.z, o.x, o.z)
            if q ~= p and d < 1.4 then
                local nx, nz = Vec.Norm(b.x - o.x, b.z - o.z)
                b.vx, b.vz = b.vx + nx * 4, b.vz + nz * 4
            end
        end
        b.x, b.z = b.x + b.vx * dt, b.z + b.vz * dt
        local nx, nz, d = Vec.Norm(b.x, b.z)
        if d > R - 0.7 then b.x, b.z, b.vx, b.vz = nx * (R - 0.7), nz * (R - 0.7), -b.vx * 0.5, -b.vz * 0.5 end
        Ent.Move(b.id, b.x, 0.7, b.z)
        if Vec.Len(b.x, b.z) < HILL then on, who = on + 1, p end
    end
    State.Set("holder", on == 0 and "" or (on == 1 and who or "*"))
end
```
