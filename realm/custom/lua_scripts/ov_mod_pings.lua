-- "Pings & World Markers" sample mod, server half. Rides on ov_modapi.lua (OVMOD addon messages).
--
-- client -> server (mod "pings")
--   ping     x,y,z,mapId,kind                  kind: attack | onmyway | danger | assist
--   marker   place,slot,x,y,z,mapId            slot 1-8; leader or assistant only
--   marker   clear,slot                        slot 1-8, or 0 for all; leader or assistant only
--   marker   sync                              re-send the group's markers for your map
-- server -> client (mod "pings")
--   ping     x,y,z,mapId,kind,senderGuidLow,senderName
--   marker   set,slot,x,y,z,mapId,placerName
--   marker   clear,slot                        slot 0 = all
--   denied   reason                            rate | notleader | nogroup | bad | far
--
-- Pings and markers go to group members on the sender's map and instance (not back to the
-- sender: the client draws its own ping when it sends it). A point more than 100 yards from the
-- sender is pulled in to 100 yards. 5 messages per 5 seconds per player, pings and markers
-- together. Markers are kept per group in memory and re-sent to members who join the group,
-- log in or change map; .reload ale or a restart forgets them.

local OVMod = require("ov_modapi")

local MOD = "pings"
local KINDS = { attack = true, onmyway = true, danger = true, assist = true }
local RATE_COUNT, RATE_WINDOW = 5, 5
local MAX_DISTANCE = 100
local MAX_COORD = 20000
local MARKER_SLOTS = 8

local recent = {}  -- [guidLow] = { times... }
local markers = {} -- [groupKey] = { [slot] = { x, y, z, map, inst, by } }

local function number(s)
    if type(s) ~= "string" or #s > 16 then return nil end
    if not (s:match("^%-?%d+%.?%d*$") or s:match("^%-?%.%d+$")) then return nil end
    local v = tonumber(s)
    if not v or v ~= v or v > MAX_COORD or v < -MAX_COORD then return nil end
    return v
end

local function split(data)
    local out = {}
    for field in (data .. ","):gmatch("([^,]*),") do out[#out + 1] = field end
    return out
end

local function allow(player)
    local guid, now = player:GetGUIDLow(), os.time()
    local list = recent[guid] or {}
    local kept = {}
    for _, t in ipairs(list) do
        if now - t < RATE_WINDOW then kept[#kept + 1] = t end
    end
    if #kept >= RATE_COUNT then
        recent[guid] = kept
        return false
    end
    kept[#kept + 1] = now
    recent[guid] = kept
    return true
end

local function deny(player, reason)
    OVMod.Send(player, MOD, "denied", reason)
end

local function groupKey(group)
    local guid = group:GetGUID()
    if type(GetGUIDLow) == "function" then return tostring(GetGUIDLow(guid)) end
    return tostring(guid)
end

local function clampPoint(player, x, y, z)
    local px, py, pz = player:GetLocation()
    local dx, dy, dz = x - px, y - py, z - pz
    local d = math.sqrt(dx * dx + dy * dy + dz * dz)
    if d <= MAX_DISTANCE then return x, y, z end
    local k = MAX_DISTANCE / d
    return px + dx * k, py + dy * k, pz + dz * k
end

local function fmt(v)
    return string.format("%.2f", v)
end

local function sameInstance(a, map, inst)
    return a:IsInWorld() and a:GetMapId() == map and a:GetInstanceId() == inst
end

local function relay(sender, name, data)
    local group = sender:GetGroup()
    if not group then return 0 end
    local map, inst, me = sender:GetMapId(), sender:GetInstanceId(), sender:GetGUIDLow()
    local n = 0
    for _, member in ipairs(group:GetMembers()) do
        if member:GetGUIDLow() ~= me and sameInstance(member, map, inst) then
            OVMod.Send(member, MOD, name, data)
            n = n + 1
        end
    end
    return n
end

local function readPoint(player, f, at)
    local x, y, z, map = number(f[at]), number(f[at + 1]), number(f[at + 2]), number(f[at + 3])
    if not (x and y and z and map) or map ~= player:GetMapId() then return nil end
    return clampPoint(player, x, y, z)
end

local function onPing(player, data)
    local f = split(data)
    if #f ~= 5 or not KINDS[f[5]] then return deny(player, "bad") end
    local x, y, z = readPoint(player, f, 1)
    if not x then return deny(player, "bad") end
    if not allow(player) then return deny(player, "rate") end
    relay(player, "ping", table.concat({ fmt(x), fmt(y), fmt(z), player:GetMapId(), f[5],
        player:GetGUIDLow(), player:GetName() }, ","))
end

local function canMark(player, group)
    local guid = player:GetGUID()
    return group:IsLeader(guid) or group:IsAssistant(guid)
end

local function markerSet(slot, m)
    return table.concat({ "set", slot, fmt(m.x), fmt(m.y), fmt(m.z), m.map, m.by }, ",")
end

local function sendMarkers(player)
    local group = player and player:GetGroup()
    if not group then return end
    local list = markers[groupKey(group)]
    OVMod.Send(player, MOD, "marker", "clear,0")
    if not list then return end
    local map, inst = player:GetMapId(), player:GetInstanceId()
    for slot = 1, MARKER_SLOTS do
        local m = list[slot]
        if m and m.map == map and m.inst == inst then
            OVMod.Send(player, MOD, "marker", markerSet(slot, m))
        end
    end
end

local function onMarker(player, data)
    local f = split(data)
    if f[1] == "sync" and #f == 1 then
        if not allow(player) then return deny(player, "rate") end
        return sendMarkers(player)
    end
    local group = player:GetGroup()
    if not group then return deny(player, "nogroup") end
    if not canMark(player, group) then return deny(player, "notleader") end
    local slot = f[2] and f[2]:match("^%d$") and tonumber(f[2])
    if not slot or slot > MARKER_SLOTS then return deny(player, "bad") end
    local key = groupKey(group)
    if f[1] == "place" and #f == 6 and slot >= 1 then
        local x, y, z = readPoint(player, f, 3)
        if not x then return deny(player, "bad") end
        if not allow(player) then return deny(player, "rate") end
        markers[key] = markers[key] or {}
        local m = { x = x, y = y, z = z, map = player:GetMapId(), inst = player:GetInstanceId(), by = player:GetName() }
        markers[key][slot] = m
        relay(player, "marker", markerSet(slot, m))
    elseif f[1] == "clear" and #f == 2 then
        if not allow(player) then return deny(player, "rate") end
        if markers[key] then
            if slot == 0 then markers[key] = nil else markers[key][slot] = nil end
        end
        relay(player, "marker", "clear," .. slot)
    else
        deny(player, "bad")
    end
end

local function onLogout(event, player)
    recent[player:GetGUIDLow()] = nil
end

local function onEnter(event, player)
    sendMarkers(player)
end

local function onMemberAdd(event, group, guid)
    sendMarkers(GetPlayerByGUID(guid))
end

local function onMemberRemove(event, group, guid)
    local p = GetPlayerByGUID(guid)
    if p then OVMod.Send(p, MOD, "marker", "clear,0") end
end

local function onDisband(event, group)
    local key = groupKey(group)
    if markers[key] then
        for _, member in ipairs(group:GetMembers()) do OVMod.Send(member, MOD, "marker", "clear,0") end
    end
    markers[key] = nil
end

OVMod.On(MOD, "ping", onPing)
OVMod.On(MOD, "marker", onMarker)

RegisterPlayerEvent(3, onEnter)          -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, onLogout)         -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(28, onEnter)         -- PLAYER_EVENT_ON_MAP_CHANGE
RegisterGroupEvent(1, onMemberAdd)       -- GROUP_EVENT_ON_MEMBER_ADD
RegisterGroupEvent(3, onMemberRemove)    -- GROUP_EVENT_ON_MEMBER_REMOVE
RegisterGroupEvent(5, onDisband)         -- GROUP_EVENT_ON_DISBAND
