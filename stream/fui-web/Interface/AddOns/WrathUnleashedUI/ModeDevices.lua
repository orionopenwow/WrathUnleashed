-- ModeDevices (3.3.5a API): Leyline Devices, modes built from parts with no code, and the device editor.
--
-- A device mode is an ordinary mode whose script is one call with a block of data:
--
--   Mode.Title = "Pressure Plates"
--   Mode.Players = { 1, 8 }
--   Devices.Run[=[
--   set area=16 floor=34384a
--   d 1 spawn z=-8                        a device: id, kind, then the properties that differ from the defaults
--   d 2 trigger name=Pad%20A x=-5 once=1
--   w 2 enter 5 add 1                     a wire: (device 2, event "enter") -> (device 5, function "add", argument "1")
--   ]=]
--
-- M.DEVICES_LIB below is the runtime. It is not part of the client's trusted code path: Modes.lua loads it into
-- each device mode's own sandbox (the same environment the mode's script gets) and it runs under the same 30 ms
-- guard, using only the creator API (Ent, HUD, Score, Camera, Timer, Players, Mode). So devices are built on
-- the mode API, every client still only draws what the host sends, and the realm relays it as it does any mode.
-- Wires are queued and run once per tick, at most MAX_EVENTS of them, so a wire loop can't hang the host.
--
-- The editor (/modes devices, or "Device editor" in the mode editor) edits a layout as data. Play runs a copy
-- of it (the layout is turned into its text and run from that); Stop throws the copy away and reopens the
-- editor on the authored layout, which play never touches. Save keeps it here and on your account (the realm,
-- "dsave"), and Publish goes through the same publish and GM review path as a script.

local W = WrathUnleashedUI
local M = W.Modes
if not M then return end

M.DEVICES_LIB = [==[
-- Leyline Devices runtime (runs inside a mode's sandbox; see ModeDevices.lua).
local D = {}
Devices = D
local MAX_DEVICES, MAX_WIRES, MAX_EVENTS, MAX_QUEUE = 64, 128, 64, 256
D.MAX_DEVICES, D.MAX_WIRES, D.MAX_EVENTS = MAX_DEVICES, MAX_WIRES, MAX_EVENTS

-- ------------------------------------------------------------ the devices: properties, events, functions
local S, ORDER = {}, {}
D.Schema, D.Order = S, ORDER
local function def(kind, title, help, props, events, fns)
    local p = { { "name", "", "s" }, { "x", 0, "n" }, { "y", 0, "n" }, { "z", 0, "n" } }
    for _, e in ipairs(props) do p[#p + 1] = e end
    S[kind] = { kind = kind, title = title, help = help, props = p, events = events, fns = fns }
    ORDER[#ORDER + 1] = kind
end
def("spawn", "Spawn Point", "Players start here as a ball they roll with WASD.",
    { { "speed", 7, "n" }, { "cam", 9, "n" }, { "color", "", "c" } },
    { "spawned" }, { "respawn", "respawnall" })
def("trigger", "Trigger Volume", "A box on the ground: fires when a player walks in or out.",
    { { "w", 3, "n" }, { "d", 3, "n" }, { "h", 3, "n" }, { "on", 1, "b" }, { "once", 0, "b" }, { "show", 1, "b" },
      { "color", "4fa3ff", "c" }, { "offcolor", "4a4a58", "c" }, { "hitcolor", "50ff78", "c" } },
    { "enter", "leave", "denied" }, { "enable", "disable", "reset" })
def("button", "Button", "Players press E next to it.",
    { { "size", 1, "n" }, { "range", 2.5, "n" }, { "on", 1, "b" }, { "cooldown", 0.5, "n" }, { "color", "ff4040", "c" } },
    { "pressed", "denied" }, { "enable", "disable", "reset" })
def("timer", "Timer", "Counts down from seconds, or up (up with seconds 0 has no limit).",
    { { "seconds", 30, "n" }, { "dir", "down", "e", { "down", "up" } }, { "auto", 0, "b" }, { "show", 1, "b" }, { "label", "Time", "s" } },
    { "started", "stopped", "done" }, { "start", "stop", "reset", "add" })
def("counter", "Counter", "A number. Fires when it reaches the target.",
    { { "start", 0, "n" }, { "target", 3, "n" }, { "show", 0, "b" }, { "label", "", "s" } },
    { "changed", "reached" }, { "add", "sub", "set", "reset" })
def("score", "Score Keeper", "Points for the player who set off the wire.",
    { { "points", 1, "n" }, { "target", 0, "n" } },
    { "reached" }, { "add", "sub", "reset", "win" })
def("teleport", "Teleporter", "A pad that moves a player to the target point, inside the area.",
    { { "r", 1.5, "n" }, { "tx", 0, "n" }, { "ty", 0, "n" }, { "tz", 0, "n" }, { "on", 1, "b" }, { "show", 1, "b" }, { "color", "b48cff", "c" } },
    { "teleported" }, { "enable", "disable", "send", "reset" })
def("round", "Round Manager", "Rounds. Each one resets the devices and the players.",
    { { "rounds", 1, "n" }, { "delay", 1, "n" }, { "wait", 3, "n" }, { "auto", 1, "b" }, { "endtext", "Game over", "s" } },
    { "roundstart", "roundend", "gameover" }, { "start", "endround", "finish" })
def("hud", "HUD Message", "Text for everyone. {player} and {3} (device 3's value) fill in.",
    { { "text", "Hello", "s" }, { "where", "say", "e", { "say", "banner" } } },
    { "shown" }, { "show", "clear" })
def("mover", "Mover", "A shape. With a path it moves; a solid one blocks players.",
    { { "shape", "box", "e", { "box", "ball", "cyl" } }, { "sx", 2, "n" }, { "sy", 2, "n" }, { "sz", 2, "n" }, { "yaw", 0, "n" },
      { "color", "c0a060", "c" }, { "path", "", "p" }, { "speed", 3, "n" }, { "loop", "once", "e", { "once", "loop", "pingpong" } },
      { "auto", 0, "b" }, { "solid", 1, "b" } },
    { "arrived", "returned" }, { "start", "stop", "back", "reset" })

local function has(list, v) for _, x in ipairs(list) do if x == v then return true end end return false end
local function clamp(v, a, b) v = tonumber(v) or 0 if v ~= v then v = 0 end return math.max(a, math.min(b, v)) end
local function round2(v) return math.floor(v * 100 + 0.5) / 100 end
function D.Spec(kind, key)
    for _, e in ipairs((S[kind] or { props = {} }).props) do if e[1] == key then return e end end
end
local function cleanValue(e, v)
    local kind, dflt = e[3], e[2]
    if kind == "n" then
        v = tonumber(v)
        if not v or v ~= v then return dflt end
        return round2(clamp(v, -999, 999))
    elseif kind == "b" then
        return (v == 1 or v == "1" or v == true or v == "true" or v == "on" or v == "yes") and 1 or 0
    elseif kind == "c" then
        v = (tostring(v or ""):gsub("#", "")):lower()
        if v:match("^%x%x%x%x%x%x$") then return v end
        return dflt
    elseif kind == "e" then
        v = tostring(v or ""):lower()
        return has(e[4], v) and v or dflt
    elseif kind == "p" then
        local pts = {}
        for a, b, c in tostring(v or ""):gmatch("([^,/%s]+),([^,/%s]+),([^,/%s]+)") do
            if #pts < 8 then pts[#pts + 1] = round2(clamp(a, -60, 60)) .. "," .. round2(clamp(b, -60, 60)) .. "," .. round2(clamp(c, -60, 60)) end
        end
        return table.concat(pts, "/")
    end
    return (tostring(v or ""):gsub("[|\n\r]", "")):sub(1, 80)
end
D.Clean = cleanValue
function D.Defaults(kind)
    local p = {}
    for _, e in ipairs(S[kind].props) do p[e[1]] = e[2] end
    return p
end
function D.SetProp(dv, key, v)
    local e = D.Spec(dv.kind, key)
    if not e then return false end
    dv.p[key] = cleanValue(e, v)
    return true
end

-- ------------------------------------------------------------ the layout as text (data, never run as code)
local function enc(v) return (tostring(v):gsub("[^%w%.%-_,/#]", function(c) return string.format("%%%02X", c:byte()) end)) end
local function dec(v) return (tostring(v):gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end)) end
D.Encode, D.Decode = enc, dec

function D.Parse(body)
    local L = { area = 20, floor = "34384a", devs = {}, wires = {}, byId = {} }
    local wires, n = {}, 0
    for line in (tostring(body or "") .. "\n"):gmatch("([^\n]*)\n") do
        n = n + 1
        if n > 400 then return nil, "too many lines" end
        local w = {}
        for word in line:gmatch("%S+") do w[#w + 1] = word end
        local k = w[1]
        if k == "set" then
            for i = 2, #w do
                local a, b = w[i]:match("^(%w+)=(.*)$")
                if a == "area" then L.area = round2(clamp(b, 4, 60))
                elseif a == "floor" then b = dec(b):lower(); L.floor = (b == "none" or b:match("^%x%x%x%x%x%x$")) and b or L.floor end
            end
        elseif k == "d" then
            local id, kind = tonumber(w[2]), w[3]
            if not id or id ~= math.floor(id) or id < 1 or id > 999 then return nil, "line " .. n .. ": a device needs an id from 1 to 999" end
            if L.byId[id] then return nil, "line " .. n .. ": device " .. id .. " is there twice" end
            if not S[kind or ""] then return nil, "line " .. n .. ": no device called '" .. tostring(kind) .. "'" end
            if #L.devs >= MAX_DEVICES then return nil, "too many devices (" .. MAX_DEVICES .. " at most)" end
            local dv = { id = id, kind = kind, p = D.Defaults(kind) }
            for i = 4, #w do
                local a, b = w[i]:match("^(%w+)=(.*)$")
                if a then D.SetProp(dv, a, dec(b)) end
            end
            L.devs[#L.devs + 1] = dv
            L.byId[id] = dv
        elseif k == "w" then
            if #wires >= MAX_WIRES then return nil, "too many wires (" .. MAX_WIRES .. " at most)" end
            wires[#wires + 1] = { n = n, src = tonumber(w[2]), ev = w[3], dst = tonumber(w[4]), fn = w[5], arg = w[6] and dec(w[6]) or "" }
        elseif k ~= nil and k:sub(1, 2) ~= "--" then
            return nil, "line " .. n .. ": '" .. k .. "' isn't a device or a wire"
        end
    end
    for _, w in ipairs(wires) do
        local a, b = L.byId[w.src or -1], L.byId[w.dst or -1]
        if not a or not b then return nil, "line " .. w.n .. ": the wire needs two devices that exist" end
        if not has(S[a.kind].events, w.ev) then return nil, "line " .. w.n .. ": a " .. S[a.kind].title .. " has no event '" .. tostring(w.ev) .. "'" end
        if not has(S[b.kind].fns, w.fn) then return nil, "line " .. w.n .. ": a " .. S[b.kind].title .. " has no function '" .. tostring(w.fn) .. "'" end
        L.wires[#L.wires + 1] = { src = w.src, ev = w.ev, dst = w.dst, fn = w.fn, arg = (w.arg:gsub("[|\n\r]", "")):sub(1, 80) }
    end
    return L
end

function D.Title(t) return ((tostring(t or ""):gsub("[^%w %-!&'%.]", "")):sub(1, 40)) end

function D.Serialize(L)
    local out = { "-- Made in the device editor. Everything in Devices.Run is data: devices and wires.",
        string.format('Mode.Title = "%s"', D.Title(L.title) ~= "" and D.Title(L.title) or "My Devices"),
        string.format("Mode.Players = { %d, %d }", clamp(L.min or 1, 1, 8), clamp(L.max or 8, 1, 8)),
        "Devices.Run[=[",
        "set area=" .. enc(L.area or 20) .. " floor=" .. enc(L.floor or "34384a") }
    for _, dv in ipairs(L.devs) do
        local parts = { "d", dv.id, dv.kind }
        for _, e in ipairs(S[dv.kind].props) do
            local v = dv.p[e[1]]
            if v ~= nil and v ~= e[2] then parts[#parts + 1] = e[1] .. "=" .. enc(v) end
        end
        out[#out + 1] = table.concat(parts, " ")
    end
    for _, w in ipairs(L.wires) do
        out[#out + 1] = table.concat({ "w", w.src, w.ev, w.dst, w.fn }, " ") .. ((w.arg or "") ~= "" and (" " .. enc(w.arg)) or "")
    end
    out[#out + 1] = "]=]"
    return table.concat(out, "\n") .. "\n"
end

function D.ParseMode(text)
    text = tostring(text or "")
    local body = text:match("Devices%.Run%s*%(?%s*%[=%[(.-)%]=%]")
    if not body then return nil, "That isn't a device layout." end
    local L, err = D.Parse(body)
    if not L then return nil, err end
    L.title = D.Title(text:match('Mode%.Title%s*=%s*"([^"\n]+)"') or "My Devices")
    local mn, mx = text:match("Mode%.Players%s*=%s*{%s*(%d+)%s*,%s*(%d+)%s*}")
    L.min, L.max = clamp(tonumber(mn) or 1, 1, 8), clamp(tonumber(mx) or 8, 1, 8)
    return L
end

-- What a layout looks like at rest: one entry per shape (the editor's preview draws these too).
function D.Shapes(L, preview)
    local out = {}
    local function add(dv, role, shape, x, y, z, sx, sy, sz, yaw, color)
        out[#out + 1] = { dev = dv and dv.id, role = role, shape = shape, x = x, y = y, z = z, sx = sx, sy = sy, sz = sz, yaw = yaw or 0, color = color }
    end
    if L.floor ~= "none" then add(nil, "floor", "box", 0, -0.1, 0, L.area * 2, 0.2, L.area * 2, 0, L.floor) end
    for _, dv in ipairs(L.devs) do
        local p = dv.p
        if dv.kind == "spawn" then
            add(dv, "main", "cyl", p.x, p.y + 0.03, p.z, 1.4, 0.05, 1.4, 0, "6a6a7a")
        elseif dv.kind == "trigger" then
            if p.show == 1 or preview then add(dv, "main", "box", p.x, p.y + 0.04, p.z, math.max(0.2, p.w), 0.08, math.max(0.2, p.d), 0, p.on == 1 and p.color or p.offcolor) end
        elseif dv.kind == "button" then
            local s = clamp(p.size, 0.2, 6)
            add(dv, "main", "cyl", p.x, p.y + 0.4 * s, p.z, s, 0.8 * s, s, 0, p.on == 1 and p.color or "555560")
        elseif dv.kind == "teleport" then
            if p.show == 1 or preview then
                local r = clamp(p.r, 0.3, 10)
                add(dv, "main", "cyl", p.x, p.y + 0.05, p.z, r * 2, 0.1, r * 2, 0, p.on == 1 and p.color or "4a4a58")
                add(dv, "dest", "cyl", p.tx, p.ty + 0.03, p.tz, 1, 0.06, 1, 0, p.color)
            end
        elseif dv.kind == "mover" then
            add(dv, "main", p.shape, p.x, p.y, p.z, clamp(p.sx, 0.05, 60), clamp(p.sy, 0.05, 60), clamp(p.sz, 0.05, 60), p.yaw, p.color)
        elseif preview then
            -- Logic devices have no shape in play; the editor shows a small marker so you can pick them.
            local tint = { timer = "ffd23c", counter = "3cb4ff", score = "ffd700", round = "c878ff", hud = "ffffff" }
            add(dv, "main", "box", p.x, p.y + 0.5, p.z, 0.6, 0.6, 0.6, 45, tint[dv.kind] or "ffffff")
        end
    end
    return out
end

-- ------------------------------------------------------------ the runtime
local PALETTE = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local AV_Y, AV_R = 0.6, 0.5

function D.Run(body)
    local L, err = D.Parse(body)
    if not L then error("device layout: " .. tostring(err), 2) end
    local rt = { L = L, devs = {}, list = {}, wires = {}, hooks = {}, avatars = {}, seat = {}, nseat = 0, queue = {},
        clock = 0, fired = 0, lastEvents = 0, dropped = 0, spawns = {} }
    D.rt = rt
    local area = L.area
    local F = {}   -- kind -> { fn = function(d, arg, player) }

    for _, dv in ipairs(L.devs) do
        local d = { id = dv.id, kind = dv.kind, p = {} }
        for k, v in pairs(dv.p) do d.p[k] = v end
        rt.devs[d.id] = d
        rt.list[#rt.list + 1] = d
        if d.kind == "spawn" then rt.spawns[#rt.spawns + 1] = d end
    end
    for _, w in ipairs(L.wires) do
        local key = w.src .. ":" .. w.ev
        rt.wires[key] = rt.wires[key] or {}
        table.insert(rt.wires[key], w)
    end

    local function emit(d, ev, player)
        if #rt.queue >= MAX_QUEUE then rt.dropped = rt.dropped + 1 return end
        rt.queue[#rt.queue + 1] = { d.id, ev, player }
    end
    rt.emit = emit

    local function value(d, player)
        if d.kind == "timer" then return string.format("%.1f", d.t or 0)
        elseif d.kind == "counter" then return tostring(d.v or 0)
        elseif d.kind == "round" then return tostring(d.round or 0)
        elseif d.kind == "score" then
            if player then return tostring(Score.Get(player)) end
            local best = 0
            for _, p in ipairs(Players.List()) do best = math.max(best, Score.Get(p)) end
            return tostring(best)
        end
        return ""
    end
    local function fill(text, player)
        return (tostring(text or ""):gsub("{(%w+)}", function(k)
            if k == "player" then return player or "Someone" end
            local t = rt.devs[tonumber(k) or -1]
            if t then return value(t, player) end
        end))
    end
    rt.fill = fill

    local function inArea(x, z)
        local a = area - AV_R
        return math.max(-a, math.min(a, x)), math.max(-a, math.min(a, z))
    end

    -- shapes
    local function paint(d)
        if not d.ent then return end
        local p, c = d.p, nil
        if d.kind == "trigger" then c = d.done and p.hitcolor or (d.on and p.color or p.offcolor)
        elseif d.kind == "button" then c = d.on and p.color or "555560"
        elseif d.kind == "teleport" then c = d.on and p.color or "4a4a58" end
        if c then Ent.Set(d.ent, { color = c }) end
    end

    -- players
    local function place(player)
        local n = #rt.spawns
        if n == 0 then return end
        local i = rt.seat[player] or 1
        local sp = rt.spawns[(i - 1) % n + 1]
        local ring = math.floor((i - 1) / n)
        local ox, oz = 0, 0
        if ring > 0 then local a = ring * 2.1 ox, oz = math.sin(a) * 1.4, math.cos(a) * 1.4 end
        local x, z = inArea(sp.p.x + ox, sp.p.z + oz)
        local a = rt.avatars[player]
        if not a then
            a = { keys = {}, color = sp.p.color ~= "" and sp.p.color or PALETTE[(i - 1) % #PALETTE + 1] }
            a.id = Ent.Spawn{ shape = "ball", x = x, y = AV_Y, z = z, sx = 1.2, sy = 1.2, sz = 1.2, color = a.color }
            rt.avatars[player] = a
        else
            Ent.Move(a.id, x, AV_Y, z)
        end
        a.x, a.y, a.z, a.speed = x, AV_Y, z, clamp(sp.p.speed, 0, 30)
        if sp.p.cam > 0 then Camera.Follow(player, a.id, clamp(sp.p.cam, 2, 40), clamp(sp.p.cam * 0.7, 1, 30)) end
        emit(sp, "spawned", player)
    end
    local function placeAll()
        for _, p in ipairs(Players.List()) do place(p) end
    end
    local function teleportTo(player, x, z)
        local a = rt.avatars[player]
        if not a then return false end
        a.x, a.z = inArea(x, z)
        Ent.Move(a.id, a.x, a.y, a.z)
        return true
    end

    -- per kind: reset (to the authored state), tick, functions
    local function resetDev(d)
        local p = d.p
        if d.kind == "trigger" or d.kind == "teleport" then d.on, d.done, d.inside = p.on == 1, false, {}; paint(d)
        elseif d.kind == "button" then d.on, d.ready = p.on == 1, 0; paint(d)
        elseif d.kind == "timer" then d.run, d.t, d.shownAt = false, p.dir == "up" and 0 or math.max(0, p.seconds), -1
        elseif d.kind == "counter" then d.v = p.start
        elseif d.kind == "mover" then
            d.pts = { { p.x, p.y, p.z } }
            for a, b, c in tostring(p.path):gmatch("([^,/]+),([^,/]+),([^,/]+)") do
                d.pts[#d.pts + 1] = { p.x + (tonumber(a) or 0), p.y + (tonumber(b) or 0), p.z + (tonumber(c) or 0) }
            end
            d.cx, d.cy, d.cz, d.dir, d.ti, d.moving = p.x, p.y, p.z, -1, 1, false
            if d.ent then Ent.Move(d.ent, p.x, p.y, p.z, p.yaw) end
        end
    end

    local function timerShow(d)
        if d.p.show == 1 then HUD.Banner((d.p.label ~= "" and (d.p.label .. " ") or "") .. value(d)) end
    end

    F.spawn = {
        respawn = function(d, arg, player) if player then place(player) else placeAll() end end,
        respawnall = function(d) placeAll() end,
    }
    local function onoff(on) return function(d) if d.on ~= on then d.on = on; paint(d) end end end
    F.trigger = {
        enable = onoff(true), disable = onoff(false),
        reset = function(d) resetDev(d) end,
    }
    F.button = { enable = onoff(true), disable = onoff(false), reset = function(d) resetDev(d) end }
    F.teleport = {
        enable = onoff(true), disable = onoff(false), reset = function(d) resetDev(d) end,
        send = function(d, arg, player)
            if player and teleportTo(player, d.p.tx, d.p.tz) then emit(d, "teleported", player) end
        end,
    }
    F.timer = {
        start = function(d) if not d.run then d.run = true; timerShow(d); emit(d, "started") end end,
        stop = function(d) if d.run then d.run = false; timerShow(d); emit(d, "stopped") end end,
        reset = function(d) resetDev(d) end,
        add = function(d, arg) d.t = math.max(0, d.t + (tonumber(arg) or 0)) end,
    }
    local function setCount(d, v, player)
        local old = d.v
        d.v = round2(clamp(v, -99999, 99999))
        if d.v == old then return end
        if d.p.show == 1 then HUD.Say((d.p.label ~= "" and (d.p.label .. ": ") or "") .. d.v) end
        emit(d, "changed", player)
        if old < d.p.target and d.v >= d.p.target then emit(d, "reached", player) end
    end
    F.counter = {
        add = function(d, arg, player) setCount(d, d.v + (tonumber(arg) or 1), player) end,
        sub = function(d, arg, player) setCount(d, d.v - (tonumber(arg) or 1), player) end,
        set = function(d, arg, player) setCount(d, tonumber(arg) or 0, player) end,
        reset = function(d) d.v = d.p.start end,
    }
    local endGame
    local function addScore(d, n, player)
        if not player then return end
        local before = Score.Get(player)
        Score.Add(player, n)
        if d.p.target > 0 and before < d.p.target and Score.Get(player) >= d.p.target then emit(d, "reached", player) end
    end
    F.score = {
        add = function(d, arg, player) addScore(d, tonumber(arg) or d.p.points, player) end,
        sub = function(d, arg, player) addScore(d, -(tonumber(arg) or d.p.points), player) end,
        reset = function(d) for _, p in ipairs(Players.List()) do Score.Set(p, 0) end end,
        win = function(d, arg, player) endGame(arg ~= "" and arg or "{player} wins!", player) end,
    }
    local roundStart
    F.round = {
        start = function(d) roundStart(d) end,
        endround = function(d, arg, player)
            if not d.playing then return end
            d.playing = false
            emit(d, "roundend", player)
            if arg ~= "" then HUD.Say(fill(arg, player)) end
            if d.round >= d.p.rounds then
                endGame(d.p.endtext, player, d)
            else
                Timer.After(clamp(d.p.wait, 0, 60), function() roundStart(d) end)
            end
        end,
        finish = function(d, arg, player) d.playing = false; endGame(arg ~= "" and arg or d.p.endtext, player, d) end,
    }
    F.hud = {
        show = function(d, arg, player)
            local text = fill(arg ~= "" and arg or d.p.text, player)
            if d.p.where == "banner" then HUD.Banner(text) else HUD.Say(text) end
            emit(d, "shown", player)
        end,
        clear = function(d) if d.p.where == "banner" then HUD.Banner("") end end,
    }
    F.mover = {
        start = function(d) if #d.pts > 1 then if d.dir ~= 1 then d.ti, d.dir = d.ti + 1, 1 end d.moving = true end end,
        back = function(d) if #d.pts > 1 then if d.dir ~= -1 then d.ti, d.dir = d.ti - 1, -1 end d.moving = true end end,
        stop = function(d) d.moving = false end,
        reset = function(d) resetDev(d) end,
    }
    D.Fns = F

    endGame = function(text, player, rd)
        if rt.ending or rt.over then return end
        if rd then emit(rd, "gameover", player) end
        rt.ending = { text = text, player = player }
    end

    local function begin()
        for _, d in ipairs(rt.list) do
            if d.kind ~= "round" and d.kind ~= "score" then resetDev(d) end
        end
        placeAll()
        for _, d in ipairs(rt.list) do
            if d.kind == "timer" and d.p.auto == 1 then F.timer.start(d) end
            if d.kind == "mover" and d.p.auto == 1 then F.mover.start(d) end
        end
    end
    roundStart = function(d)
        if rt.over or rt.ending then return end
        if d.round >= d.p.rounds then return end
        d.round, d.playing = d.round + 1, true
        if not rt.fresh then begin() end
        rt.fresh = false
        if d.p.rounds > 1 then HUD.Banner("Round " .. d.round .. " of " .. d.p.rounds) end
        emit(d, "roundstart")
    end

    -- Every queued event, through its wires, at most MAX_EVENTS per tick; the rest are dropped.
    local function flush()
        local q, i = rt.queue, 1
        while q[i] do
            if i > MAX_EVENTS then
                rt.dropped = rt.dropped + (#q - i + 1)
                break
            end
            local ev = q[i]
            i = i + 1
            local key = ev[1] .. ":" .. ev[2]
            for _, fn in ipairs(rt.hooks[key] or {}) do fn(ev[3]) end
            for _, w in ipairs(rt.wires[key] or {}) do
                local t = rt.devs[w.dst]
                local f = t and F[t.kind] and F[t.kind][w.fn]
                if f then f(t, w.arg or "", ev[3]) end
            end
        end
        rt.lastEvents = i - 1
        rt.fired = rt.fired + i - 1
        rt.queue = {}
        if rt.dropped > 0 and not rt.warned then
            rt.warned = true
            print("Too many device events at once (a wire loop?). The extra ones were dropped.")
        end
        if rt.ending and not rt.over then
            rt.over = true
            Mode.End(fill(rt.ending.text, rt.ending.player))
        end
    end
    rt.flush = flush

    -- solid movers push players out (yaw is taken as 0 or 90 degrees)
    local function collide(a)
        for _, d in ipairs(rt.list) do
            if d.kind == "mover" and d.p.solid == 1 then
                local hx, hy, hz = d.p.sx / 2, d.p.sy / 2, d.p.sz / 2
                local yaw = math.abs(d.p.yaw) % 180
                if yaw > 45 and yaw < 135 then hx, hz = hz, hx end
                if d.cy - hy < a.y + AV_R and d.cy + hy > a.y - AV_R then
                    local dx, dz = a.x - d.cx, a.z - d.cz
                    local px, pz = hx + AV_R - math.abs(dx), hz + AV_R - math.abs(dz)
                    if px > 0 and pz > 0 then
                        if px < pz then a.x = a.x + (dx < 0 and -px or px) else a.z = a.z + (dz < 0 and -pz or pz) end
                    end
                end
            end
        end
    end

    local function moveMover(d, dt)
        local step, guard = clamp(d.p.speed, 0, 60) * dt, 0
        while d.moving and step > 0 and guard < 10 do
            guard = guard + 1
            local t = d.pts[d.ti]
            if not t then d.moving = false break end
            local dx, dy, dz = t[1] - d.cx, t[2] - d.cy, t[3] - d.cz
            local dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist <= step then
                d.cx, d.cy, d.cz = t[1], t[2], t[3]
                step = step - dist
                if d.dir == 1 and d.ti == #d.pts then
                    emit(d, "arrived")
                    if d.p.loop == "loop" then d.ti = 1
                    elseif d.p.loop == "pingpong" then d.dir, d.ti = -1, d.ti - 1
                    else d.moving = false end
                elseif d.dir == -1 and d.ti == 1 then
                    emit(d, "returned")
                    if d.p.loop == "pingpong" then d.dir, d.ti = 1, 2 else d.moving = false end
                else
                    d.ti = d.ti + d.dir
                end
            else
                d.cx, d.cy, d.cz = d.cx + dx / dist * step, d.cy + dy / dist * step, d.cz + dz / dist * step
                step = 0
            end
        end
        Ent.Move(d.ent, d.cx, d.cy, d.cz, d.p.yaw)
    end

    local function inBox(a, d)
        return math.abs(a.x - d.p.x) <= d.p.w / 2 and math.abs(a.z - d.p.z) <= d.p.d / 2 and a.y >= d.p.y - 1 and a.y <= d.p.y + d.p.h
    end
    local function inPad(a, d)
        local dx, dz = a.x - d.p.x, a.z - d.p.z
        return dx * dx + dz * dz <= d.p.r * d.p.r and a.y >= d.p.y - 1 and a.y <= d.p.y + 3
    end

    -- the mode's callbacks
    OnStart = function(players)
        for _, s in ipairs(D.Shapes(L, false)) do
            local id = Ent.Spawn(s)
            local d = s.dev and rt.devs[s.dev]
            if d then if s.role == "dest" then d.ent2 = id else d.ent = id end end
        end
        for _, p in ipairs(players) do rt.nseat = rt.nseat + 1; rt.seat[p] = rt.nseat end
        for _, d in ipairs(rt.list) do if d.kind == "round" or d.kind == "score" then d.round, d.playing = 0, false end end
        begin()
        rt.fresh = true
        for _, d in ipairs(rt.list) do
            if d.kind == "round" and d.p.auto == 1 then
                if d.p.delay > 0 then Timer.After(clamp(d.p.delay, 0, 60), function() roundStart(d) end) else roundStart(d) end
            end
        end
        flush()
    end

    OnTick = function(dt)
        if rt.over then return end
        rt.fresh = false
        rt.clock = rt.clock + dt
        for _, a in pairs(rt.avatars) do
            local ax, az = 0, 0
            if a.keys.W then az = az + 1 end
            if a.keys.S then az = az - 1 end
            if a.keys.D then ax = ax + 1 end
            if a.keys.A then ax = ax - 1 end
            local n = math.sqrt(ax * ax + az * az)
            local ox, oz = a.x, a.z
            if n > 0 then a.x, a.z = a.x + ax / n * a.speed * dt, a.z + az / n * a.speed * dt end
            collide(a)
            a.x, a.z = inArea(a.x, a.z)
            if a.x ~= ox or a.z ~= oz then Ent.Move(a.id, a.x, a.y, a.z) end
        end
        for _, d in ipairs(rt.list) do
            if d.kind == "trigger" then
                for p, a in pairs(rt.avatars) do
                    local now, was = inBox(a, d), d.inside[p]
                    if now and not was then
                        d.inside[p] = true
                        if d.done then
                        elseif d.on then
                            emit(d, "enter", p)
                            if d.p.once == 1 then d.done = true; paint(d) end
                        else
                            emit(d, "denied", p)
                        end
                    elseif was and not now then
                        d.inside[p] = nil
                        if d.on and not d.done then emit(d, "leave", p) end
                    end
                end
            elseif d.kind == "teleport" then
                for p, a in pairs(rt.avatars) do
                    local now, was = inPad(a, d), d.inside[p]
                    if now and not was then
                        d.inside[p] = true
                        if d.on and teleportTo(p, d.p.tx, d.p.tz) then emit(d, "teleported", p) end
                    elseif was and not now then
                        d.inside[p] = nil
                    end
                end
            elseif d.kind == "timer" and d.run then
                if d.p.dir == "up" then
                    d.t = d.t + dt
                    if d.p.seconds > 0 and d.t >= d.p.seconds then d.t, d.run = d.p.seconds, false; timerShow(d); emit(d, "done") end
                else
                    d.t = d.t - dt
                    if d.t <= 0 then d.t, d.run = 0, false; timerShow(d); emit(d, "done") end
                end
                if d.run and rt.clock - d.shownAt >= 0.2 then d.shownAt = rt.clock; timerShow(d) end
            elseif d.kind == "mover" and d.moving then
                moveMover(d, dt)
            end
        end
        flush()
    end

    OnKey = function(player, key, down)
        local a = rt.avatars[player]
        if not a then return end
        a.keys[key] = down or nil
        if key ~= "E" or not down then return end
        for _, d in ipairs(rt.list) do
            if d.kind == "button" then
                local dx, dz = a.x - d.p.x, a.z - d.p.z
                if dx * dx + dz * dz <= d.p.range * d.p.range then
                    if not d.on then emit(d, "denied", player)
                    elseif rt.clock >= d.ready then
                        d.ready = rt.clock + clamp(d.p.cooldown, 0, 60)
                        emit(d, "pressed", player)
                        if d.ent then
                            Ent.Set(d.ent, { color = "ffffff" })
                            Timer.After(0.25, function() paint(d) end)
                        end
                    end
                end
            end
        end
    end

    OnLeave = function(player)
        local a = rt.avatars[player]
        if a then Ent.Remove(a.id) end
        rt.avatars[player] = nil
        for _, d in ipairs(rt.list) do if d.inside then d.inside[player] = nil end end
    end

    OnJoin = function(player)
        if rt.seat[player] then return end
        rt.nseat = rt.nseat + 1
        rt.seat[player] = rt.nseat
        place(player)
    end

    local keys = { "W", "A", "S", "D" }
    for _, d in ipairs(rt.list) do if d.kind == "button" then keys[#keys + 1] = "E" break end end
    Mode.Keys = keys
    return rt
end

-- For scripts that mix code with devices: run your own function on a device event, or call a device.
function D.On(id, ev, fn)
    local rt = D.rt
    if not rt or type(fn) ~= "function" then return end
    local key = tostring(id) .. ":" .. tostring(ev)
    rt.hooks[key] = rt.hooks[key] or {}
    table.insert(rt.hooks[key], fn)
end
function D.Call(id, fn, arg, player)
    local rt = D.rt
    local d = rt and rt.devs[tonumber(id) or -1]
    local f = d and D.Fns[d.kind] and D.Fns[d.kind][fn]
    if f then f(d, arg and tostring(arg) or "", player) end
end
]==]

-- The built-in sample, made only of devices. Step on the three pads in order: the door opens, the timer stops
-- and your time shows. Walk through the door to finish. (The realm has a copy: ov_modes.lua PLATES.)
M.PLATES = [==[
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

-- ---------------------------------------------------------------- the library in the editor (its own copy)

-- The editor uses the same code for the schema, parsing and saving, in an empty environment of its own.
function M.DeviceLib()
    if M.devLib then return M.devLib end
    local env = { string = string, math = math, table = table, pairs = pairs, ipairs = ipairs, next = next, type = type,
        tostring = tostring, tonumber = tonumber, select = select, error = error, unpack = unpack, print = function() end, Mode = {} }
    local chunk = loadstring(M.DEVICES_LIB, "=devices")
    setfenv(chunk, env)
    chunk()
    M.devLib = env.Devices
    return M.devLib
end

-- ---------------------------------------------------------------- the device editor

local E = { L = nil, sel = nil, offset = 0, woffset = 0, preview = false, playing = false, wire = {}, remote = {} }
M.DevEditor = E

local function now() return (GetTime and GetTime()) or 0 end
local function has() return type(LeylineMode) == "function" and type(LeylineGuard) == "function" end
local function draw(text) if has() then return LeylineMode(text) end end
local function tidy(s) return (tostring(s or ""):gsub("|", "")) end
local function send(name, data) if M.Send then return M.Send(name, data) end end

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlightSmall")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end
local function button(parent, text, w, onClick, ...)
    if W.Style then local b = W.Style.Button(parent, text, w, onClick, nil, ...); b:SetHeight(20); return b end
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(20)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end
local function input(parent, w, ...)
    local b = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    b:SetWidth(w); b:SetHeight(18)
    b:SetAutoFocus(false)
    b:SetPoint(...)
    b:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return b
end

local ui

local function info(text) E.info = text; if ui then ui.info:SetText(text or "") end end

function E.Lib() return M.DeviceLib() end

local function devName(dv)
    local S = E.Lib().Schema
    if not dv then return "-" end
    local n = dv.p.name ~= "" and dv.p.name or S[dv.kind].title
    return string.format("%d %s", dv.id, n)
end
E.DevName = devName

function E.New()
    local L = E.Lib().Parse("")
    L.title, L.min, L.max = "My Devices", 1, 8
    E.L, E.sel, E.offset, E.woffset = L, nil, 0, 0
    E.AddDevice("spawn", 0, 0, -8)
    E.sel = nil
    E.Refresh()
end

-- Opens a layout from mode text. Returns true if it was a device layout.
function E.LoadText(text)
    local L, err = E.Lib().ParseMode(text)
    if not L then info(err); return false end
    E.L, E.sel, E.offset, E.woffset = L, nil, 0, 0
    E.Refresh()
    return true
end

function E.Text() return E.Lib().Serialize(E.L) end

local function nextId()
    local id = 1
    for _, dv in ipairs(E.L.devs) do if dv.id >= id then id = dv.id + 1 end end
    return id
end

function E.AddDevice(kind, x, y, z)
    local D = E.Lib()
    if not D.Schema[kind] then return nil end
    if #E.L.devs >= D.MAX_DEVICES then info("That's the most devices a layout can have."); return nil end
    local dv = { id = nextId(), kind = kind, p = D.Defaults(kind) }
    D.SetProp(dv, "x", x or 0); D.SetProp(dv, "y", y or 0); D.SetProp(dv, "z", z or 0)
    if kind == "mover" then D.SetProp(dv, "y", (y or 0) + 1) end
    E.L.devs[#E.L.devs + 1] = dv
    E.L.byId[dv.id] = dv
    E.sel = dv.id
    E.Refresh()
    return dv
end

function E.DeleteDevice(id)
    for i, dv in ipairs(E.L.devs) do
        if dv.id == id then
            table.remove(E.L.devs, i)
            E.L.byId[id] = nil
            for j = #E.L.wires, 1, -1 do
                local w = E.L.wires[j]
                if w.src == id or w.dst == id then table.remove(E.L.wires, j) end
            end
            if E.sel == id then E.sel = nil end
            E.Refresh()
            return true
        end
    end
    return false
end

function E.SetProp(id, key, value)
    local dv = E.L.byId[id]
    if not dv then return false end
    local ok = E.Lib().SetProp(dv, key, value)
    E.Refresh()
    return ok
end

function E.AddWire(src, ev, dst, fn, arg)
    local D = E.Lib()
    local a, b = E.L.byId[src or -1], E.L.byId[dst or -1]
    if not a or not b then info("Pick both devices."); return false end
    local ok1, ok2 = false, false
    for _, x in ipairs(D.Schema[a.kind].events) do if x == ev then ok1 = true end end
    for _, x in ipairs(D.Schema[b.kind].fns) do if x == fn then ok2 = true end end
    if not ok1 or not ok2 then info("Pick an event and a function."); return false end
    if #E.L.wires >= D.MAX_WIRES then info("That's the most wires a layout can have."); return false end
    E.L.wires[#E.L.wires + 1] = { src = src, ev = ev, dst = dst, fn = fn, arg = (tostring(arg or ""):gsub("[|\n\r]", "")):sub(1, 80) }
    info(string.format("Wired: when %s %s, %s %s.", devName(a), ev, fn, devName(b)))
    E.Refresh()
    return true
end

function E.DeleteWire(i)
    if not E.L.wires[i] then return false end
    table.remove(E.L.wires, i)
    E.Refresh()
    return true
end

-- The preview: the layout drawn where you stand, so you can see it and point at the ground to place things.
-- The arena is put 14 yards ahead of you, so where you stood is 0, 0, -14.
E.ME = { 0, 0, -14 }

function E.Redraw()
    if not E.preview or E.playing or not E.L then return end
    draw("clear")
    draw("origin keep")
    local shapes = E.Lib().Shapes(E.L, true)
    for i, s in ipairs(shapes) do
        local c = s.color
        if s.dev and s.dev == E.sel and s.role == "main" then c = "ffffff" end
        draw(string.format("ent %d %s %.2f %.2f %.2f %.2f %.2f %.2f %.1f %s", i, s.shape, s.x, s.y, s.z, s.sx, s.sy, s.sz, s.yaw, c))
    end
    local dv = E.sel and E.L.byId[E.sel]
    if dv then
        draw(string.format("ent %d cyl %.2f %.2f %.2f 0.15 4 0.15 0 ffffff", #shapes + 1, dv.p.x, dv.p.y + 2, dv.p.z))
    end
end

function E.StartPreview()
    if E.playing or M.host or (M.state ~= "idle" and M.state ~= nil) then return false end
    if not E.preview then
        draw("clear")
        -- The first preview goes where you stand; after a test it stays where it was.
        draw(E.anchored and "origin keep" or "origin here")
        E.preview, E.anchored = true, true
    end
    E.Redraw()
    return true
end

function E.EndPreview()
    if E.preview and not E.playing then draw("clear") end
    E.preview, E.anchored = false, false
end

-- Where the mouse points on the ground of the preview (arena yards), or nil.
function E.Cursor()
    local c = draw("cursor")
    local x, y, z = tostring(c or ""):match("^(%S+) (%S+) (%S+)$")
    x, z = tonumber(x), tonumber(z)
    if not x then return nil end
    local snap = function(v) return math.floor(v * 2 + 0.5) / 2 end
    return snap(x), 0, snap(z)
end

-- Click-to-place: a see-through layer under the editor; the next click on the ground places or moves.
function E.Arm(what)
    E.armed = what
    if ui then ui.catcher:Show() end
    info(what == "move" and "Click the ground to move the device there (right-click cancels)."
        or "Click the ground to place it (right-click cancels).")
end

function E.Click(btn)
    local what = E.armed
    E.armed = nil
    if ui then ui.catcher:Hide() end
    if btn == "RightButton" or not what then info(""); return end
    local x, y, z = E.Cursor()
    if not x then info("Point at the ground inside the preview."); return end
    if what == "move" then
        if E.sel then E.SetProp(E.sel, "x", x); E.SetProp(E.sel, "z", z) end
    else
        E.AddDevice(what, x, y, z)
    end
end

-- ---------------------------------------------------------------- Play / Stop, Save, Publish

function E.Play()
    if not E.L then return false end
    local text = E.Text()
    local origin = E.preview and "keep" or "here"
    E.playing = true
    E.preview = false
    if ui then ui:Hide() end
    M.Solo(text, origin)
    if not M.host then
        E.playing = false
        info("It didn't start: " .. tostring(M.status or ""))
        E.Show()
        return false
    end
    M.onStop = function() E.Restore() end
    if ui then ui.stopBar:Show() end
    return true
end

function E.Stop()
    if E.playing then
        if M.state ~= "idle" then M.Leave() else E.Restore() end
    end
end

-- Back from a test: the authored layout was never handed to the game (it ran from a copy), so just reopen it.
function E.Restore()
    E.playing = false
    M.onStop = nil
    if ui then ui.stopBar:Hide() end
    E.Show()
    info("Stopped. The layout is as you left it.")
end

function E.Save()
    local text = E.Text()
    local title = E.L.title
    M.SaveMode(title, text)
    send("dsave", title .. "\n" .. text)
    info("Saved \"" .. tidy(title) .. "\" here and on your account.")
end

function E.Publish()
    local text = E.Text()
    E.Save()
    M.Publish(text)
    info("Sent for review. A GM approves new modes before others see them.")
end

-- Your saved layouts: the ones here, and the ones on your account (asked for when the editor opens).
function E.Mine()
    local list, seen = {}, {}
    for _, m in ipairs(M.MyModes()) do
        if m.text:find("Devices.Run", 1, true) then list[#list + 1] = { title = m.title, text = m.text }; seen[m.title] = true end
    end
    for _, t in ipairs(E.remote) do if not seen[t] then list[#list + 1] = { title = t } end end
    return list
end

function E.OpenNext()
    local mine = E.Mine()
    if #mine == 0 then info("Nothing saved yet."); return end
    E.pick = (E.pick or 0) % #mine + 1
    local m = mine[E.pick]
    if m.text then E.LoadText(m.text); info("Opened \"" .. tidy(m.title) .. "\".")
    else send("dload", m.title); info("Fetching \"" .. tidy(m.title) .. "\" from your account...") end
end

-- From the realm: drafts <title;title> | draft <title>\n<text> | dsaved <title>
function M.OnDraftMessage(name, data)
    if name == "drafts" then
        E.remote = {}
        for t in tostring(data or ""):gmatch("[^;]+") do E.remote[#E.remote + 1] = tidy(t) end
    elseif name == "draft" then
        local title, text = tostring(data or ""):match("^([^\n]*)\n(.*)$")
        if text and E.LoadText(text) then E.Show(); info("Opened \"" .. tidy(title) .. "\" from your account.")
        elseif text then M.Editor(text) end
    elseif name == "dsaved" then
        info("Saved \"" .. tidy(data) .. "\" on your account.")
    end
end

-- ---------------------------------------------------------------- the window

-- A small drop-down: one shared list that opens under whichever button was clicked.
local menu
local function openMenu(anchor, options, onPick)
    if not menu then
        menu = CreateFrame("Frame", "LeylineDevicesMenu", UIParent)
        menu:SetFrameStrata("FULLSCREEN_DIALOG")
        menu:SetWidth(180)
        menu:EnableMouse(true)
        if W.Style then W.Style.Backdrop(menu, W.Style.C.bg2) else menu:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
            tile = true, tileSize = 16, edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } }) end
        menu:SetBackdropColor(0.05, 0.04, 0.1, 0.96)
        menu.rows = {}
        for i = 1, 14 do
            local r = CreateFrame("Button", nil, menu)
            r:SetWidth(170); r:SetHeight(16)
            r:SetPoint("TOPLEFT", 5, -5 - (i - 1) * 16)
            r:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
            r.text = label(r, "", "GameFontHighlightSmall", "LEFT", 4, 0)
            r:SetScript("OnClick", function(self) menu.choose(self) end)
            menu.rows[i] = r
        end
        menu:EnableMouseWheel(true)
        menu:SetScript("OnMouseWheel", function(_, delta)
            menu.offset = math.max(0, math.min(#menu.options - 14, menu.offset - delta))
            menu.fill()
        end)
        menu.choose = function(r)
            menu:Hide()
            if menu.onPick and r.value ~= nil then menu.onPick(r.value) end
        end
        menu.fill = function()
            for i, r in ipairs(menu.rows) do
                local o = menu.options[i + menu.offset]
                if o then r.value = o.value; r.text:SetText(o.text); r:Show() else r.value = nil; r:Hide() end
            end
        end
        tinsert(UISpecialFrames, "LeylineDevicesMenu")
    end
    menu.options, menu.onPick, menu.offset = options, onPick, 0
    menu:SetHeight(10 + math.min(14, math.max(1, #options)) * 16)
    menu:ClearAllPoints()
    menu:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, -2)
    menu.fill()
    menu:Show()
end
E.OpenMenu = openMenu
function E.MenuPick(i) if menu and menu.rows[i] and menu.rows[i].value ~= nil then menu.choose(menu.rows[i]) return true end end

local function dropdown(parent, w, getOptions, onPick, ...)
    local b = button(parent, "-", w, nil, ...)
    b:SetScript("OnClick", function(self) openMenu(self, getOptions(), onPick) end)
    return b
end

local PROP_ROWS = 16

local function devOptions(filter)
    local o = {}
    for _, dv in ipairs(E.L.devs) do
        if not filter or filter(dv) then o[#o + 1] = { value = dv.id, text = devName(dv) .. "  |cffa0a0a0" .. E.Lib().Schema[dv.kind].title .. "|r" } end
    end
    return o
end
local function nameOptions(list) local o = {} for _, v in ipairs(list or {}) do o[#o + 1] = { value = v, text = v } end return o end

local function build()
    ui = CreateFrame("Frame", "LeylineDevicesEditor", UIParent)
    ui:SetWidth(720); ui:SetHeight(560)
    ui:SetPoint("CENTER", 0, 20)
    ui:SetFrameStrata("DIALOG")
    ui:EnableMouse(true)
    ui:SetMovable(true)
    ui:RegisterForDrag("LeftButton")
    ui:SetScript("OnDragStart", ui.StartMoving)
    ui:SetScript("OnDragStop", ui.StopMovingOrSizing)
    if not W.Style then   -- Style.lua draws the window (S.Window, at its title)
        ui:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    end
    ui:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = ui:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.094, 0.106, 0.137, 0.97)   -- #181b23 (Style.lua)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    local _ = (W.Style and W.Style.Window(ui, "Device editor") or label(ui, "Device editor", "GameFontNormalLarge", "TOP", -40, -18))
    local close = (W.Style and W.Style.Close(ui) or CreateFrame("Button", nil, ui, "UIPanelCloseButton"))
    close:SetPoint("TOPRIGHT", -6, -6)
    tinsert(UISpecialFrames, "LeylineDevicesEditor")

    -- name and area
    label(ui, "Name", nil, "TOPLEFT", 22, -48)
    ui.title = input(ui, 170, "TOPLEFT", 60, -44)
    ui.title:SetMaxLetters(40)
    ui.title:SetScript("OnEditFocusLost", function(self) if E.L then E.L.title = E.Lib().Title(self:GetText()) end end)
    ui.title:SetScript("OnEnterPressed", function(self) self:ClearFocus(); if E.L then E.L.title = E.Lib().Title(self:GetText()) end end)
    label(ui, "Area", nil, "TOPLEFT", 244, -48)
    ui.area = input(ui, 36, "TOPLEFT", 276, -44)
    local function setArea(self) self:ClearFocus(); if E.L then E.L.area = math.max(4, math.min(60, tonumber(self:GetText()) or E.L.area)); E.Refresh() end end
    ui.area:SetScript("OnEnterPressed", setArea)
    ui.area:SetScript("OnEditFocusLost", setArea)

    -- add a device
    label(ui, "Add", "GameFontNormalSmall", "TOPLEFT", 22, -78)
    ui.kind = dropdown(ui, 120, function()
        local o = {}
        for _, k in ipairs(E.Lib().Order) do o[#o + 1] = { value = k, text = E.Lib().Schema[k].title } end
        return o
    end, function(k) E.kind = k; E.Refresh() end, "TOPLEFT", 50, -74)
    button(ui, "At my spot", 84, function() E.AddDevice(E.kind or "trigger", E.ME[1], E.ME[2], E.ME[3]) end, "TOPLEFT", 174, -74)
    button(ui, "Click to place", 96, function() E.Arm(E.kind or "trigger") end, "TOPLEFT", 260, -74)

    -- the devices
    label(ui, "Devices", "GameFontNormalSmall", "TOPLEFT", 22, -102)
    ui.rows = {}
    for i = 1, 8 do
        local r = CreateFrame("Button", nil, ui)
        r:SetWidth(330); r:SetHeight(17)
        r:SetPoint("TOPLEFT", 22, -118 - (i - 1) * 17)
        r:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        r.text = label(r, "", "GameFontHighlightSmall", "LEFT", 4, 0)
        r:SetScript("OnClick", function(self) if self.id then E.sel = self.id; E.Refresh() end end)
        ui.rows[i] = r
    end
    ui:EnableMouseWheel(true)
    ui:SetScript("OnMouseWheel", function(_, delta)
        E.offset = math.max(0, math.min(math.max(0, #E.L.devs - 8), E.offset - delta))
        E.Refresh()
    end)
    button(ui, "Delete", 70, function() if E.sel then E.DeleteDevice(E.sel) end end, "TOPLEFT", 22, -258)
    button(ui, "Move: click", 90, function() if E.sel then E.Arm("move") end end, "TOPLEFT", 96, -258)
    button(ui, "Move to my spot", 116, function() if E.sel then E.SetProp(E.sel, "x", E.ME[1]); E.SetProp(E.sel, "z", E.ME[3]) end end, "TOPLEFT", 190, -258)

    -- the selected device's properties, two columns
    ui.help = label(ui, "", "GameFontHighlightSmall", "TOPLEFT", 22, -286)
    ui.help:SetWidth(330)
    ui.props = {}
    for i = 1, PROP_ROWS do
        local col, row = math.floor((i - 1) / 8), (i - 1) % 8
        local x, y = 22 + col * 168, -304 - row * 22
        local p = { name = label(ui, "", "GameFontHighlightSmall", "TOPLEFT", x, y - 4) }
        p.box = input(ui, 88, "TOPLEFT", x + 70, y)
        local function commit(self)
            self:ClearFocus()
            if E.sel and p.key then E.SetProp(E.sel, p.key, self:GetText() or "") end
        end
        p.box:SetScript("OnEnterPressed", commit)
        p.box:SetScript("OnEditFocusLost", function(self) if E.sel and p.key and self:GetText() ~= p.shown then commit(self) end end)
        ui.props[i] = p
    end

    -- wires
    label(ui, "Wires: when this happens...", "GameFontNormalSmall", "TOPLEFT", 380, -78)
    ui.wsrc = dropdown(ui, 160, function() return devOptions(function(dv) return #E.Lib().Schema[dv.kind].events > 0 end) end,
        function(id) E.wire.src, E.wire.ev = id, nil; E.Refresh() end, "TOPLEFT", 380, -94)
    ui.wev = dropdown(ui, 140, function()
        local dv = E.L.byId[E.wire.src or -1]
        return nameOptions(dv and E.Lib().Schema[dv.kind].events)
    end, function(v) E.wire.ev = v; E.Refresh() end, "TOPLEFT", 544, -94)
    label(ui, "...do this", "GameFontNormalSmall", "TOPLEFT", 380, -120)
    ui.wdst = dropdown(ui, 160, function() return devOptions() end,
        function(id) E.wire.dst, E.wire.fn = id, nil; E.Refresh() end, "TOPLEFT", 380, -136)
    ui.wfn = dropdown(ui, 140, function()
        local dv = E.L.byId[E.wire.dst or -1]
        return nameOptions(dv and E.Lib().Schema[dv.kind].fns)
    end, function(v) E.wire.fn = v; E.Refresh() end, "TOPLEFT", 544, -136)
    label(ui, "Argument", nil, "TOPLEFT", 380, -166)
    ui.warg = input(ui, 140, "TOPLEFT", 440, -162)
    ui.warg:SetMaxLetters(80)
    button(ui, "Add wire", 96, function()
        if E.AddWire(E.wire.src, E.wire.ev, E.wire.dst, E.wire.fn, ui.warg:GetText() or "") then ui.warg:SetText("") end
    end, "TOPLEFT", 588, -162)
    ui.wrows = {}
    for i = 1, 11 do
        local r = CreateFrame("Frame", nil, ui)
        r:SetWidth(310); r:SetHeight(20)
        r:SetPoint("TOPLEFT", 380, -192 - (i - 1) * 21)
        r.text = label(r, "", "GameFontHighlightSmall", "LEFT", 2, 0)
        r.text:SetWidth(280)
        r.del = button(r, "x", 22, function() if r.index then E.DeleteWire(r.index) end end, "RIGHT", 0, 0)
        ui.wrows[i] = r
    end
    ui.wmore = label(ui, "", "GameFontHighlightSmall", "TOPLEFT", 380, -426)
    button(ui, "<", 22, function() E.woffset = math.max(0, E.woffset - 11); E.Refresh() end, "TOPLEFT", 620, -424)
    button(ui, ">", 22, function() if E.woffset + 11 < #E.L.wires then E.woffset = E.woffset + 11 end E.Refresh() end, "TOPLEFT", 644, -424)

    -- the bottom row
    local bx = 22
    local function bottom(text, w, fn) button(ui, text, w, fn, "BOTTOMLEFT", bx, 40); bx = bx + w + 4 end
    bottom("Play", 60, function() E.Play() end)
    bottom("Stop", 56, function() E.Stop() end)
    bottom("Save", 56, function() E.Save() end)
    bottom("Open mine", 84, function() E.OpenNext() end)
    bottom("Publish", 70, function() E.Publish() end)
    bottom("Sample: Pressure Plates", 168, function() E.LoadText(M.PLATES); info("Pressure Plates: three pads, a door, a timer. Press Play.") end)
    bottom("New", 50, function() E.New() end)
    bottom("As script", 76, function() local t = E.Text(); ui:Hide(); M.Editor(t) end)
    ui.info = label(ui, "", "GameFontHighlightSmall", "BOTTOMLEFT", 22, 18)
    ui.info:SetWidth(670)

    -- click-to-place: under the editor, over the world
    ui.catcher = CreateFrame("Frame", "LeylineDevicesPick", UIParent)
    ui.catcher:SetAllPoints(UIParent)
    ui.catcher:SetFrameStrata("HIGH")
    ui.catcher:EnableMouse(true)
    ui.catcher:SetScript("OnMouseDown", function(_, btn) E.Click(btn) end)
    ui.catcher:Hide()

    -- while testing: a way back
    ui.stopBar = CreateFrame("Frame", "LeylineDevicesStop", UIParent)
    ui.stopBar:SetWidth(210); ui.stopBar:SetHeight(34)
    ui.stopBar:SetPoint("TOPLEFT", 18, -90)
    ui.stopBar:SetFrameStrata("HIGH")
    button(ui.stopBar, "Stop: back to the editor", 200, function() E.Stop() end, "CENTER", 0, 0)
    ui.stopBar:Hide()

    ui:SetScript("OnShow", function() send("dlist", ""); E.StartPreview() end)
    ui:SetScript("OnHide", function()
        if menu then menu:Hide() end
        ui.catcher:Hide()
        E.armed = nil
        if not E.playing then E.EndPreview() end
    end)
    ui:Hide()
end

function E.Refresh()
    if not E.L then return end
    E.Redraw()
    if not ui then return end
    local S = E.Lib().Schema
    if ui.title:GetText() ~= E.L.title then ui.title:SetText(E.L.title) end
    ui.area:SetText(tostring(E.L.area))
    ui.kind:SetText(S[E.kind or "trigger"].title)
    E.offset = math.max(0, math.min(E.offset, math.max(0, #E.L.devs - 8)))
    for i, r in ipairs(ui.rows) do
        local dv = E.L.devs[i + E.offset]
        r.id = dv and dv.id
        if dv then
            r.text:SetText((dv.id == E.sel and "|cff40ff40> |r" or "") .. devName(dv) .. "  |cffa0a0a0" .. S[dv.kind].title
                .. string.format("  (%g, %g)|r", dv.p.x, dv.p.z))
            r:Show()
        else
            r:Hide()
        end
    end
    local dv = E.sel and E.L.byId[E.sel]
    ui.help:SetText(dv and ("|cffffd100" .. S[dv.kind].title .. ":|r " .. S[dv.kind].help) or "Pick a device to set its properties.")
    for i, p in ipairs(ui.props) do
        local e = dv and S[dv.kind].props[i]
        p.key = e and e[1]
        if e then
            local v = dv.p[e[1]]
            p.shown = tostring(v)
            p.name:SetText(e[1] .. (e[3] == "b" and " (0/1)" or ""))
            p.box:SetText(p.shown)
            p.name:Show(); p.box:Show()
        else
            p.name:SetText(""); p.box:SetText(""); p.name:Hide(); p.box:Hide()
        end
    end
    local src, dst = E.L.byId[E.wire.src or -1], E.L.byId[E.wire.dst or -1]
    if not src then E.wire.src, E.wire.ev = nil, nil end
    if not dst then E.wire.dst, E.wire.fn = nil, nil end
    ui.wsrc:SetText(src and devName(src) or "From device...")
    ui.wev:SetText(E.wire.ev or "event...")
    ui.wdst:SetText(dst and devName(dst) or "To device...")
    ui.wfn:SetText(E.wire.fn or "function...")
    E.woffset = math.max(0, math.min(E.woffset, math.max(0, #E.L.wires - 1)))
    for i, r in ipairs(ui.wrows) do
        local idx = i + E.woffset
        local w = E.L.wires[idx]
        r.index = w and idx
        if w then
            r.text:SetText(string.format("%s |cffffd100%s|r -> %s |cff9fd6ff%s|r%s", devName(E.L.byId[w.src]), w.ev,
                devName(E.L.byId[w.dst]), w.fn, w.arg ~= "" and (" (" .. w.arg .. ")") or ""))
            r:Show()
        else
            r:Hide()
        end
    end
    ui.wmore:SetText(#E.L.wires > 0 and string.format("%d wires", #E.L.wires) or "No wires yet.")
end

function E.Show()
    if not ui then build() end
    if not E.L then E.New() end
    ui:Show()
    E.StartPreview()
    E.Refresh()
end

function E.Toggle()
    if ui and ui:IsShown() then ui:Hide() else E.Show() end
end

-- The mode editor's "Device editor" button: open its text as a layout if it is one.
function M.DeviceEditor(text)
    if text and text:find("Devices.Run", 1, true) then E.LoadText(text) end
    E.Show()
end
