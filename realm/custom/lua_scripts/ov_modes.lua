-- Leyline Modes, the realm half (mod-ale / Eluna): sessions and the relay for scripted minigames.
--
-- A mode is a Lua script that runs only on the session host's browser client (WrathUnleashedUI/Modes.lua runs it
-- in a sandbox). This script never runs mode code: it opens sessions, invites party members nearby, hands the
-- host the script, and relays: the host's state to everyone else ("st"), everyone's keys to the host ("in"). Each
-- relayed message is size- and rate-limited. Published modes wait for a GM's approval before anyone else can see
-- them (a mode is code, unlike a minigolf course, which is only geometry).
--
-- OVMOD channel (ov_modapi.lua), mod "wumodes":
--   client -> server   list | host <key> | solo <key> | join <id> | go | leave
--                      in <KEY> <0|1>             a player's key, relayed to the host
--                      st <state>                 the host's state, relayed to the other players
--                      keys <KEY ...>             the host's mode keys, relayed to the other players
--                      snap <name>\n<state>       the host's catch-up for a late joiner
--                      end <text>                 the host finishes the game
--                      publish <script>           (in parts) a mode for review
--                      dsave <title>\n<script>     save a draft to your account | dlist | dload <title> | ddel <title>
--   server -> client   modes key,title,author,min,max;...  | invite <id> <host> <title> | lobby <id> <host> <names> <title>
--                      start <id> <host> <x> <y> <z> <o> <seed> <names>\n<script, for the host only>
--                      script <script> (solo) | st | keys | in <name> <KEY> <0|1> | joined <name> | left <name>
--                      msg <text> | end <text> | published <key>
--                      drafts <title;title...> | draft <title>\n<script> | dsaved <title>
-- Device modes (Modes.lua / ModeDevices.lua) are ordinary modes whose script is one Devices.Run[=[ ... ]=] block of
-- data; they publish, host and relay like any other. Review lists them as "(devices)" when that's all they are.
-- GM: .modes pending | approve <key> | reject <key> | unlist <key>
-- mod-ale events: 4 ON_LOGOUT, 28 ON_MAP_CHANGE, 42 ON_COMMAND.

local OVMod
do
    local ok, m = pcall(function() return require("ov_modapi") end)
    OVMod = (ok and type(m) == "table" and m) or _G.OVMod
    if not OVMod then
        print("[ov_modes] ov_modapi.lua is missing: modes need the OVMOD channel; not loaded")
        return
    end
end

local MOD = "wumodes"
local TAG = "|cffb48cff[Modes]|r "
local MAX_PLAYERS = 8
local INVITE_RANGE = 40
local MAX_SCRIPT = 14 * 1024
local ST_PER_SEC = 25
local IN_PER_SEC = 30
local MAX_ST = 4000

-- The built-in modes. Copies of Modes.lua's M.BUILTIN and M.COINDASH and ModeDevices.lua's M.PLATES
-- (stream/tests/test_ov_modes.lua checks they match).
local BUMPER = [==[
-- Bumper Balls: push the others off the arena. Last ball rolling wins.
Mode.Title = "Bumper Balls"
Mode.Keys = { "W", "A", "S", "D", "SPACE" }

local R = 9            -- arena radius
local balls = {}       -- player -> { id, x, z, vx, vz, keys = {}, out }
local COLORS = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local round = 0

local function reset()
    round = round + 1
    local list = Players.List()
    for i, p in ipairs(list) do
        local a = (i - 1) / #list * math.pi * 2
        local b = balls[p] or {}
        b.x, b.z, b.vx, b.vz, b.out, b.keys, b.dash = math.sin(a) * (R - 3), math.cos(a) * (R - 3), 0, 0, false, b.keys or {}, 0
        if b.id then Ent.Move(b.id, b.x, 0.7, b.z) else
            b.id = Ent.Spawn{ shape = "ball", x = b.x, y = 0.7, z = b.z, sx = 1.4, sy = 1.4, sz = 1.4, color = COLORS[(i - 1) % #COLORS + 1] }
        end
        balls[p] = b
        Camera.Follow(p, b.id, 9, 6)
    end
    HUD.Banner("Bumper Balls - round " .. round)
    HUD.Say("WASD to roll, Space to dash. Knock everyone off!")
end

function OnStart(players)
    Ent.Spawn{ shape = "cyl", x = 0, y = -0.25, z = 0, sx = R * 2, sy = 0.5, sz = R * 2, color = "3a3550" }
    Ent.Spawn{ shape = "cyl", x = 0, y = 0.02, z = 0, sx = R * 2 - 0.6, sy = 0.06, sz = R * 2 - 0.6, color = "5a4f8a" }
    Ent.Spawn{ shape = "cyl", x = 0, y = 0.04, z = 0, sx = 3, sy = 0.06, sz = 3, color = "ffd24a" }
    for _, p in ipairs(players) do Score.Set(p, 0) end
    reset()
end

function OnKey(player, key, down)
    local b = balls[player]
    if not b then return end
    b.keys[key] = down or nil
    if key == "SPACE" and down and b.dash <= 0 and not b.out then
        local sp = math.sqrt(b.vx * b.vx + b.vz * b.vz)
        if sp > 0.1 then b.vx, b.vz = b.vx / sp * 14, b.vz / sp * 14 end
        b.dash = 2
    end
end

function OnLeave(player)
    local b = balls[player]
    if b and b.id then Ent.Remove(b.id) end
    balls[player] = nil
end

local over = false
function OnTick(dt)
    if over then return end
    local alive, last = 0, nil
    for p, b in pairs(balls) do
        if not b.out then
            local ax, az = 0, 0
            if b.keys.W then az = az + 1 end
            if b.keys.S then az = az - 1 end
            if b.keys.D then ax = ax + 1 end
            if b.keys.A then ax = ax - 1 end
            b.vx = (b.vx + ax * 18 * dt) * 0.985
            b.vz = (b.vz + az * 18 * dt) * 0.985
            b.dash = math.max(0, b.dash - dt)
        end
    end
    -- Bumps: equal balls trade momentum along the line between them.
    local list = {}
    for p, b in pairs(balls) do if not b.out then list[#list + 1] = b end end
    for i = 1, #list do for j = i + 1, #list do
        local a, c = list[i], list[j]
        local dx, dz = c.x - a.x, c.z - a.z
        local d = math.sqrt(dx * dx + dz * dz)
        if d < 1.4 and d > 0.001 then
            local nx, nz = dx / d, dz / d
            local rel = (a.vx - c.vx) * nx + (a.vz - c.vz) * nz
            if rel > 0 then
                local j2 = rel * 1.15
                a.vx, a.vz = a.vx - j2 * nx, a.vz - j2 * nz
                c.vx, c.vz = c.vx + j2 * nx, c.vz + j2 * nz
            end
            local push = (1.4 - d) / 2
            a.x, a.z = a.x - nx * push, a.z - nz * push
            c.x, c.z = c.x + nx * push, c.z + nz * push
        end
    end end
    for p, b in pairs(balls) do
        if not b.out then
            b.x, b.z = b.x + b.vx * dt, b.z + b.vz * dt
            if b.x * b.x + b.z * b.z > R * R then
                b.out = true
                HUD.Say(p .. " is out!")
                Ent.Move(b.id, b.x * 1.1, -6, b.z * 1.1)
            else
                Ent.Move(b.id, b.x, 0.7, b.z, math.deg(math.atan2(b.vx, b.vz)))
                alive, last = alive + 1, p
            end
        end
    end
    local n = Players.Count()
    if (n > 1 and alive <= 1) or (n == 1 and alive == 0) then
        if last then Score.Add(last, 1); HUD.Say(last .. " wins round " .. round .. "!") end
        if last and Score.Get(last) >= 3 then
            over = true
            Mode.End(last .. " wins Bumper Balls!")
            return
        end
        over = true
        Timer.After(2.5, function() over = false; reset() end)
    end
end
]==]

local COINDASH = [==[
-- Coin Dash: grab the most coins in 60 seconds. Gold is 1, blue gems are 3.
Mode.Title = "Coin Dash"
Mode.Keys = { "W", "A", "S", "D" }
Mode.Players = { 1, 8 }

local R = 12
local runners, coins = {}, {}
local COLORS = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local left, over = 60, false

local function spawnCoin()
    local a = Random(360) * math.pi / 180
    local d = math.sqrt(Random(1000) / 1000) * (R - 1.5)
    local gem = Random(6) == 1
    local id = Ent.Spawn{ shape = gem and "box" or "cyl", x = math.sin(a) * d, y = 0.8, z = math.cos(a) * d,
        sx = gem and 0.6 or 0.8, sy = gem and 0.6 or 0.15, sz = gem and 0.6 or 0.8, yaw = 45, color = gem and "50b4ff" or "ffd700" }
    coins[id] = { x = math.sin(a) * d, z = math.cos(a) * d, value = gem and 3 or 1, spin = 0 }
end

function OnStart(players)
    Ent.Spawn{ shape = "cyl", x = 0, y = -0.25, z = 0, sx = R * 2, sy = 0.5, sz = R * 2, color = "2f5a36" }
    Ent.Spawn{ shape = "cyl", x = 0, y = 0.02, z = 0, sx = R * 2 - 0.8, sy = 0.06, sz = R * 2 - 0.8, color = "4f8a4a" }
    for i, p in ipairs(players) do
        local a = (i - 1) / #players * math.pi * 2
        runners[p] = { x = math.sin(a) * 4, z = math.cos(a) * 4, keys = {},
            id = Ent.Spawn{ shape = "ball", x = math.sin(a) * 4, y = 0.6, z = math.cos(a) * 4, sx = 1.2, sy = 1.2, sz = 1.2, color = COLORS[(i - 1) % #COLORS + 1] } }
        Score.Set(p, 0)
        Camera.Follow(p, runners[p].id, 10, 9)
    end
    for i = 1, 14 do spawnCoin() end
    HUD.Banner("Coin Dash - 60")
    HUD.Say("WASD to run. Gold is 1, blue gems are 3!")
end

function OnKey(player, key, down)
    local r = runners[player]
    if r then r.keys[key] = down or nil end
end

function OnLeave(player)
    local r = runners[player]
    if r then Ent.Remove(r.id) end
    runners[player] = nil
end

local tick = 0
function OnTick(dt)
    if over then return end
    tick = tick + 1
    left = left - dt
    if tick % 20 == 0 then HUD.Banner("Coin Dash - " .. math.max(0, math.ceil(left))) end
    for p, r in pairs(runners) do
        local ax, az = 0, 0
        if r.keys.W then az = az + 1 end
        if r.keys.S then az = az - 1 end
        if r.keys.D then ax = ax + 1 end
        if r.keys.A then ax = ax - 1 end
        local n = math.sqrt(ax * ax + az * az)
        if n > 0 then ax, az = ax / n, az / n end
        r.x, r.z = r.x + ax * 7 * dt, r.z + az * 7 * dt
        local d = math.sqrt(r.x * r.x + r.z * r.z)
        if d > R - 0.6 then r.x, r.z = r.x / d * (R - 0.6), r.z / d * (R - 0.6) end
        Ent.Move(r.id, r.x, 0.6, r.z)
        for id, c in pairs(coins) do
            local dx, dz = c.x - r.x, c.z - r.z
            if dx * dx + dz * dz < 1.0 then
                Ent.Remove(id)
                coins[id] = nil
                Score.Add(p, c.value)
                spawnCoin()
            end
        end
    end
    if tick % 4 == 0 then
        for id, c in pairs(coins) do c.spin = (c.spin + 30) % 360; Ent.Move(id, c.x, 0.8, c.z, c.spin) end
    end
    if left <= 0 then
        over = true
        local best, who = -1, nil
        for p in pairs(runners) do if Score.Get(p) > best then best, who = Score.Get(p), p end end
        Mode.End((who or "Nobody") .. " wins Coin Dash with " .. math.max(best, 0) .. "!")
    end
end
]==]

-- Pressure Plates: made only of devices. Three pads in order open a door and stop the clock.
local PLATES = [==[
-- Made in the device editor. Everything in Devices.Run is data: devices and wires.
Mode.Title = "Pressure Plates"
Mode.Players = { 1, 8 }
Devices.Run[=[
set area=14 floor=34384a
d 1 spawn name=Start z=-9
d 2 trigger name=Pad%201 x=-6 z=-2 once=1 color=ff5a3c
d 3 trigger name=Pad%202 x=6 z=-2 on=0 once=1 color=ffd23c
d 4 trigger name=Pad%203 z=3 on=0 once=1 color=3cb4ff
d 5 counter name=Pads%20done
d 6 timer name=Clock x=3 z=-9 seconds=0 dir=up auto=1
d 7 mover name=Door y=1.5 z=8 sx=4 sy=3 sz=0.5 color=b48cff path=0,3.4,0 speed=2.5
d 8 mover name=Wall%20left x=-8 y=1.5 z=8 sx=12 sy=3 sz=0.5 color=6a5f8a
d 9 mover name=Wall%20right x=8 y=1.5 z=8 sx=12 sy=3 sz=0.5 color=6a5f8a
d 10 hud name=Opened text=Door%20open%21%20Your%20time%3A%20%7B6%7D%20s
d 11 hud name=Wrong%20order text=Not%20yet%3A%20pads%20go%201,%202,%203.
d 12 trigger name=Finish z=11.5 w=4 d=2 on=0 once=1 color=50ff78
d 13 round name=Game delay=0 endtext=%7Bplayer%7D%20got%20through%20in%20%7B6%7D%20s%21
d 14 hud name=Hello x=-3 z=-9 text=Step%20on%20the%20pads%20in%20order%3A%201,%202,%203.
w 13 roundstart 14 show
w 2 enter 3 enable
w 3 enter 4 enable
w 2 enter 5 add
w 3 enter 5 add
w 4 enter 5 add
w 3 denied 11 show
w 4 denied 11 show
w 5 reached 7 start
w 5 reached 6 stop
w 5 reached 10 show
w 5 reached 12 enable
w 12 enter 13 finish
]=]
]==]

local modes = {}      -- key -> { key, title, author, guid, min, max, text, approved }
local order = {}

local function meta(text)
    local title = text:match('Mode%.Title%s*=%s*"([^"\n]+)"') or "Untitled mode"
    local mn, mx = text:match("Mode%.Players%s*=%s*{%s*(%d+)%s*,%s*(%d+)%s*}")
    mn, mx = tonumber(mn) or 1, tonumber(mx) or MAX_PLAYERS
    return (title:gsub("[^%w %-!&'%.]", "")):sub(1, 40), math.max(1, math.min(mn, MAX_PLAYERS)), math.max(1, math.min(mx, MAX_PLAYERS))
end

local function addMode(key, text, author, guid, approved)
    local title, mn, mx = meta(text)
    if not modes[key] then order[#order + 1] = key end
    modes[key] = { key = key, title = title, author = author, guid = guid, min = mn, max = mx, text = text, approved = approved }
    return modes[key]
end

addMode("bumper", BUMPER, "Leyline", 0, true)
addMode("coindash", COINDASH, "Leyline", 0, true)
addMode("plates", PLATES, "Leyline", 0, true)
local BUILTIN = { bumper = true, coindash = true, plates = true }

-- A mode that is nothing but devices: header lines, comments and one Devices.Run block of data.
local function isDevices(text)
    local rest = text:gsub("Devices%.Run%s*%[=%[.-%]=%]", "", 1)
    if rest == text then return false end
    for line in (rest .. "\n"):gmatch("([^\n]*)\n") do
        line = line:match("^%s*(.-)%s*$")
        if line ~= "" and not line:match("^%-%-") and not line:match('^Mode%.Title%s*=%s*"[^"]*"$')
            and not line:match("^Mode%.Players%s*=%s*{%s*%d+%s*,%s*%d+%s*}$") then return false end
    end
    return true
end

local function exec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end
exec([[CREATE TABLE IF NOT EXISTS mod_modes (
  mkey VARCHAR(32) NOT NULL PRIMARY KEY, author_guid INT UNSIGNED NOT NULL, author VARCHAR(12) NOT NULL,
  title VARCHAR(40) NOT NULL, script MEDIUMTEXT NOT NULL, approved TINYINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at INT UNSIGNED NOT NULL)]])

-- Stored scripts are hex, so no quoting or escaping is ever involved.
local function hex(s) return (s:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end
local function unhex(h) return (h:gsub("%x%x", function(x) return string.char(tonumber(x, 16)) end)) end

if CharDBQuery then
    local ok, q = pcall(CharDBQuery, "SELECT mkey, author, author_guid, script, approved FROM mod_modes")
    if ok and q then
        repeat
            addMode(q:GetString(0), unhex(q:GetString(3)), q:GetString(1), q:GetUInt32(2), q:GetUInt32(4) == 1)
        until not q:NextRow()
    end
end

local function try(obj, method, ...)
    if not obj or not obj[method] then return nil end
    local ok, a = pcall(obj[method], obj, ...)
    if ok then return a end
end
local function say(player, text) try(player, "SendBroadcastMessage", TAG .. text) end
local function send(player, name, data) if player then OVMod.Send(player, MOD, name, data or "") end end
local function now() return os.time() end
local function isGM(player) return (tonumber(try(player, "GetGMRank")) or 0) > 0 end

local sessions, bySeat, nextId = {}, {}, 1

local function playerOf(seat) return (GetPlayerByGUID and GetPlayerByGUID(seat.guid)) or seat.player end
local function names(s) local n = {} for _, p in ipairs(s.players) do n[#n + 1] = p.name end return table.concat(n, ",") end
local function each(s, fn) for _, p in ipairs(s.players) do local pl = playerOf(p) if pl then fn(pl, p) end end end
local function seatOf(s, guid) for i, p in ipairs(s.players) do if p.guid == guid then return p, i end end end

local function lobbyText(s) return string.format("%d %s %s %s", s.id, s.players[1].name, names(s), s.mode.title) end

local function closeSession(s, text)
    if sessions[s.id] ~= s then return end
    sessions[s.id] = nil
    each(s, function(pl, p)
        if bySeat[p.guid] == s.id then bySeat[p.guid] = nil end
        send(pl, "end", text or "")
    end)
    for g, id in pairs(bySeat) do if id == s.id then bySeat[g] = nil end end
end

local function leave(player)
    local guid = player:GetGUIDLow()
    local s = sessions[bySeat[guid] or -1]
    bySeat[guid] = nil
    if not s then return end
    local seat, i = seatOf(s, guid)
    if not seat then return end
    table.remove(s.players, i)
    if i == 1 then return closeSession(s, "The host left; the game is over.") end
    if #s.players == 0 then return closeSession(s, nil) end
    if s.state == "lobby" then
        each(s, function(pl) send(pl, "lobby", lobbyText(s)) end)
    else
        local host = playerOf(s.players[1])
        send(host, "left", seat.name)
        each(s, function(pl) send(pl, "msg", seat.name .. " left.") end)
    end
end

local function seat(player)
    return { guid = player:GetGUIDLow(), name = player:GetName(), player = player, st = { sec = 0, n = 0 } }
end

local function hostCommand(player, key)
    local m = modes[(key or ""):lower()]
    if not m or (not m.approved and m.guid ~= player:GetGUIDLow()) then return say(player, "No mode called '" .. tostring(key) .. "'.") end
    if bySeat[player:GetGUIDLow()] then leave(player) end
    if try(player, "IsInCombat") then return say(player, "Not in combat.") end
    local s = { id = nextId, mode = m, state = "lobby", t0 = now(), players = { seat(player) },
        map = player:GetMapId(), z = player:GetZ(), o = player:GetO() }
    -- The arena goes ahead of the host, not around them.
    s.x, s.y = player:GetX() + math.cos(s.o) * 14, player:GetY() + math.sin(s.o) * 14
    nextId = nextId + 1
    sessions[s.id] = s
    bySeat[player:GetGUIDLow()] = s.id
    local invited = 0
    local group = try(player, "GetGroup")
    for _, p in ipairs((group and try(group, "GetMembers")) or {}) do
        if p:GetGUIDLow() ~= player:GetGUIDLow() and p:GetMapId() == s.map and (try(player, "GetDistance", p) or 999) <= INVITE_RANGE
            and not bySeat[p:GetGUIDLow()] then
            send(p, "invite", string.format("%d %s %s", s.id, player:GetName(), m.title))
            say(p, player:GetName() .. " invites you to play " .. m.title .. ". Open /modes to join.")
            invited = invited + 1
        end
    end
    send(player, "lobby", lobbyText(s))
    say(player, m.title .. (invited > 0 and (": invited " .. invited .. ". Press Start when everyone's in.") or ": press Start (join a party first to play together)."))
end

local function startFor(s, pl, p)
    local head = string.format("%d %s %.3f %.3f %.3f %.4f %d %s", s.id, s.players[1].name, s.x, s.y, s.z, s.o, s.seed, names(s))
    send(pl, "start", p == s.players[1] and (head .. "\n" .. s.mode.text) or head)
end

local function joinCommand(player, id)
    local s = sessions[tonumber(id or "") or -1]
    if not s then return say(player, "That game has ended.") end
    if #s.players >= math.min(MAX_PLAYERS, s.mode.max) then return say(player, "That game is full.") end
    if seatOf(s, player:GetGUIDLow()) then return end
    if bySeat[player:GetGUIDLow()] then leave(player) end
    local p = seat(player)
    s.players[#s.players + 1] = p
    bySeat[p.guid] = s.id
    if s.state == "lobby" then
        each(s, function(pl) send(pl, "lobby", lobbyText(s)) end)
    else
        -- Late: the host adds them and sends what's on the field so far.
        startFor(s, player, p)
        send(playerOf(s.players[1]), "joined", p.name)
        each(s, function(pl) send(pl, "msg", p.name .. " joined.") end)
    end
end

local function goCommand(player)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if not s or s.players[1].guid ~= player:GetGUIDLow() or s.state ~= "lobby" then return end
    if #s.players < s.mode.min then return say(player, s.mode.title .. " needs at least " .. s.mode.min .. " players.") end
    s.state, s.seed = "play", (now() % 100000) + 1
    each(s, function(pl, p) startFor(s, pl, p) end)
end

local function soloCommand(player, key)
    local m = modes[(key or ""):lower()]
    if not m or (not m.approved and m.guid ~= player:GetGUIDLow()) then return say(player, "No mode called '" .. tostring(key) .. "'.") end
    send(player, "script", m.text)
end

local function rate(p, n)
    local t = now()
    if p.st.sec ~= t then p.st.sec, p.st.n = t, 0 end
    p.st.n = p.st.n + 1
    return p.st.n <= n
end

local function hostOf(player)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if s and s.state == "play" and s.players[1].guid == player:GetGUIDLow() then return s end
end

local function stCommand(player, data)
    local s = hostOf(player)
    if not s or #data > MAX_ST or not rate(s.players[1], ST_PER_SEC) then return end
    for i = 2, #s.players do local pl = playerOf(s.players[i]) if pl then send(pl, "st", data) end end
end

local function keysCommand(player, data)
    local s = hostOf(player)
    if not s or #data > 120 then return end
    for i = 2, #s.players do local pl = playerOf(s.players[i]) if pl then send(pl, "keys", data) end end
end

local function snapCommand(player, data)
    local s = hostOf(player)
    if not s then return end
    local who, state = data:match("^(%S+)\n(.*)$")
    if not who or #state > 12000 then return end
    for i = 2, #s.players do
        if s.players[i].name == who then local pl = playerOf(s.players[i]) if pl then send(pl, "st", state) end end
    end
end

local function inCommand(player, data)
    local s = sessions[bySeat[player:GetGUIDLow()] or -1]
    if not s or s.state ~= "play" then return end
    local key, down = data:match("^(%u[%u%d]*) ([01])$")
    if not key or #key > 8 then return end
    local p = seatOf(s, player:GetGUIDLow())
    if not p or not rate(p, IN_PER_SEC) then return end
    local host = playerOf(s.players[1])
    if host then send(host, "in", p.name .. " " .. key .. " " .. down) end
end

local function endCommand(player, text)
    local s = hostOf(player)
    if not s then return end
    closeSession(s, (text or ""):gsub("[|\n]", ""):sub(1, 150))
end

local function publishCommand(player, text)
    if #text < 20 or #text > MAX_SCRIPT then return say(player, "A mode must be between 20 bytes and 14 KB.") end
    if text:find("\27", 1, true) then return say(player, "Compiled chunks aren't allowed.") end
    local title = meta(text)
    local slug = function(x) return ((x or ""):lower():gsub("[^%w]", "")):sub(1, 14) end
    local key = slug(player:GetName()) .. "_" .. slug(title)
    if key:match("_$") then return say(player, "Give the mode a title: Mode.Title = \"...\"") end
    local mine = 0
    for _, m in pairs(modes) do if m.guid == player:GetGUIDLow() then mine = mine + 1 end end
    if not modes[key] and mine >= 5 then return say(player, "You have 5 modes already; publish one again by its title to update it.") end
    local m = addMode(key, text, player:GetName(), player:GetGUIDLow(), false)
    exec(string.format("REPLACE INTO mod_modes (mkey, author_guid, author, title, script, approved, updated_at) VALUES ('%s', %d, '%s', '%s', '%s', 0, %d)",
        key, m.guid, (m.author:gsub("[^%w]", "")), (m.title:gsub("[^%w %-!&%.]", "")), hex(text), now()))
    say(player, m.title .. " sent for review. You can host it already; a GM approves it for everyone.")
    send(player, "published", key)
end

-- Drafts: your saved modes and device layouts, on your account (private; nothing is reviewed or shared).
local MAX_DRAFTS = 20
exec([[CREATE TABLE IF NOT EXISTS mod_mode_drafts (
  account INT UNSIGNED NOT NULL, title VARCHAR(40) NOT NULL, script MEDIUMTEXT NOT NULL,
  updated_at INT UNSIGNED NOT NULL, PRIMARY KEY (account, title))]])
local drafts, draftAt = {}, {}

local function accountOf(player)
    -- Without GetAccountId (an old core), drafts follow the character instead.
    return tonumber(try(player, "GetAccountId")) or player:GetGUIDLow()
end
local function draftTitle(t) return ((t or ""):gsub("[^%w %-!&%.]", "")):sub(1, 40) end
local function draftsOf(player)
    local a = accountOf(player)
    if not drafts[a] then
        drafts[a] = {}
        if CharDBQuery then
            local ok, q = pcall(CharDBQuery, string.format("SELECT title, script FROM mod_mode_drafts WHERE account = %d", a))
            if ok and q then
                repeat drafts[a][q:GetString(0)] = unhex(q:GetString(1)) until not q:NextRow()
            end
        end
    end
    return drafts[a], a
end

local function dsaveCommand(player, data)
    local title, text = data:match("^([^\n]*)\n(.*)$")
    title = draftTitle(title)
    if not text or title == "" then return say(player, "A draft needs a name.") end
    if #text < 20 or #text > MAX_SCRIPT then return say(player, "A draft must be between 20 bytes and 14 KB.") end
    if text:find("\27", 1, true) then return say(player, "Compiled chunks aren't allowed.") end
    local g = player:GetGUIDLow()
    if draftAt[g] and now() - draftAt[g] < 2 then return say(player, "Saving too fast; try again in a moment.") end
    draftAt[g] = now()
    local mine, a = draftsOf(player)
    local n = 0
    for _ in pairs(mine) do n = n + 1 end
    if not mine[title] and n >= MAX_DRAFTS then return say(player, "You have " .. MAX_DRAFTS .. " drafts; delete one first.") end
    mine[title] = text
    exec(string.format("REPLACE INTO mod_mode_drafts (account, title, script, updated_at) VALUES (%d, '%s', '%s', %d)", a, title, hex(text), now()))
    send(player, "dsaved", title)
end

local function dlistCommand(player)
    local l = {}
    for t in pairs(draftsOf(player)) do l[#l + 1] = t end
    table.sort(l)
    send(player, "drafts", table.concat(l, ";"))
end

local function dloadCommand(player, title)
    title = draftTitle(title)
    local text = draftsOf(player)[title]
    if not text then return say(player, "No draft called '" .. title .. "'.") end
    send(player, "draft", title .. "\n" .. text)
end

local function ddelCommand(player, title)
    title = draftTitle(title)
    local mine, a = draftsOf(player)
    if not mine[title] then return end
    mine[title] = nil
    exec(string.format("DELETE FROM mod_mode_drafts WHERE account = %d AND title = '%s'", a, title))
    dlistCommand(player)
end

local function gmCommand(player, word, key)
    if not isGM(player) then return say(player, "That's for GMs.") end
    if word == "pending" then
        local l = {}
        for _, k in ipairs(order) do local m = modes[k] if m and not m.approved then l[#l + 1] = k .. " (" .. m.title .. " by " .. m.author .. (isDevices(m.text) and ", devices" or "") .. ")" end end
        return say(player, #l > 0 and ("Waiting: " .. table.concat(l, ", ")) or "Nothing waiting for review.")
    end
    local m = modes[key or ""]
    if not m or BUILTIN[key] then return say(player, "No such mode: " .. tostring(key)) end
    if word == "approve" then
        m.approved = true
        exec(string.format("UPDATE mod_modes SET approved = 1 WHERE mkey = '%s'", (key:gsub("[^%w_]", ""))))
        say(player, m.title .. " approved: everyone sees it in /modes.")
    elseif word == "reject" or word == "unlist" then
        modes[key] = nil
        for i, k in ipairs(order) do if k == key then table.remove(order, i) break end end
        exec(string.format("DELETE FROM mod_modes WHERE mkey = '%s'", (key:gsub("[^%w_]", ""))))
        say(player, "Removed " .. key .. ".")
    end
end

local function listText(player)
    local l = {}
    for _, k in ipairs(order) do
        local m = modes[k]
        if m and (m.approved or m.guid == player:GetGUIDLow()) then
            l[#l + 1] = string.format("%s,%s%s,%s,%d,%d", k, (m.title:gsub("[,;]", "")), m.approved and "" or " (in review)", m.author, m.min, m.max)
        end
    end
    return table.concat(l, ";")
end

local handlers = {
    list = function(p) send(p, "modes", listText(p)) end,
    host = hostCommand, solo = soloCommand, join = joinCommand, go = goCommand,
    leave = function(p) leave(p) end,
    ["in"] = inCommand, st = stCommand, keys = keysCommand, snap = snapCommand, ["end"] = endCommand,
    publish = publishCommand,
    dsave = dsaveCommand, dlist = function(p) dlistCommand(p) end, dload = dloadCommand, ddel = ddelCommand,
}
for name, fn in pairs(handlers) do OVMod.On(MOD, name, function(player, data) fn(player, data or "") end) end

RegisterPlayerEvent(42, function(event, player, command)
    local rest = (command or ""):match("^modes%s*(.*)$")
    if not rest then return end
    local word, key = rest:match("^(%S*)%s*(%S*)")
    if word == "pending" or word == "approve" or word == "reject" or word == "unlist" then gmCommand(player, word, key)
    else say(player, "Open /modes in the browser client. GMs: .modes pending | approve <key> | reject <key>") end
    return false
end)
RegisterPlayerEvent(4, function(event, player) leave(player) end)
RegisterPlayerEvent(28, function(event, player) leave(player) end)

return { sessions = sessions, modes = modes, drafts = drafts, BUMPER = BUMPER, COINDASH = COINDASH, PLATES = PLATES, isDevices = isDevices }
