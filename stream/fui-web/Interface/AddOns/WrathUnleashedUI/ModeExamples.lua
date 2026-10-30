-- ModeExamples (3.3.5a API): two short example modes, written only against the public creator API (ModeAPI.lua).
-- The script editor offers them under "Start from", /modes collect and /modes hill play them solo, and
-- tools/creator-api/gen.lua prints them in docs/CREATOR-API.md. stream/tests/test_ov_modes.lua runs both and
-- checks they use nothing outside the API and pass the realm's review checks.
-- Plain data: loads in the game and in plain Lua 5.1 (dofile).

local EXAMPLES = {}

EXAMPLES[1] = { key = "collect", title = "Coin Collect", text = [==[
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
]==] }

EXAMPLES[2] = { key = "hill", title = "King of the Hill", text = [==[
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
]==] }

local W = rawget(_G, "WrathUnleashedUI")
if type(W) == "table" then W.ModeExamples = EXAMPLES end
return EXAMPLES
